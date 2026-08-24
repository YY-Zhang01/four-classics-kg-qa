"""RAG 问答系统 · Web 服务端（FastAPI + SSE 流式）

启动：python -m web.server
     或 uvicorn web.server:app --host 127.0.0.1 --port 7860

路由：
  /                    用户聊天界面
  /admin               管理后台
  /api/ask             问答（SSE 流式 + 审计日志）
  /api/health          健康检查
  /api/config          项目配置（名称/领域）
  /api/admin/status    系统状态总览
  /api/admin/logs      问答日志（支持搜索/分页）
  /api/admin/stats     统计摘要
  /api/admin/retriever 检索方式 查看/切换
  /api/admin/topk      Top-K 查看/调整
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, date
from pathlib import Path

from fastapi import FastAPI, Request, Query, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles

from config.settings import (
    get_retriever, set_retriever,
    get_top_k, set_top_k,
    get_active_domain, get_active_name, switch_domain,
    get_admin_domain, get_admin_name, switch_admin_domain,
    llm_config, LOG_DIR, CONFIG_DIR,
    PROJECT_NAME, PROJECT_DOMAIN,
)
from retrieval.retriever import search, count as chunk_count, label as retriever_label
from core.ask import answer_stream
from kg.store import count_triples, query_by_entity
from agent.loop import agent_ask_stream
from auth.auth import (
    register as auth_register,
    login as auth_login,
    get_current_user,
    get_current_user_or_none,
    get_current_admin,
)

# P1 Wiki 模块（可选，导入失败不影响核心功能）
try:
    from wiki.query import search as wiki_search, count as wiki_count
    from wiki.store import list_pages as wiki_list, get_page as wiki_get
    _HAS_WIKI = True
except ImportError:
    _HAS_WIKI = False
    def wiki_search(q, top_k=3): return []
    def wiki_count(): return 0
    def wiki_list(domain, page_type=None, limit=50): return []
    def wiki_get(domain, page_type, title): return None

STATIC = Path(__file__).resolve().parent / "static"
_START_TIME = datetime.now()


# ── Admin 鉴权（委托给 JWT 角色校验）──
def _verify_admin(user: dict = Depends(get_current_admin)) -> dict:
    """要求管理员角色，否则 401/403。兼容旧调用 Depends(_verify_admin)。"""
    return user


@asynccontextmanager
async def lifespan(_app: FastAPI):
    n = chunk_count()
    name = get_active_name()
    label = retriever_label()
    print(f"{name}已就绪 · {label} · {n} 块知识")
    print(f"  用户页面  http://127.0.0.1:7860")
    print(f"  管理后台  http://127.0.0.1:7860/admin")
    yield


app = FastAPI(title=get_active_name(), lifespan=lifespan)

# 挂载静态文件目录（JS/CSS 等）
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


# ═══════════════════════════════════════════════════════════
#  页面
# ═══════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTMLResponse(
        content=(STATIC / "index.html").read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/login", response_class=HTMLResponse)
def login_page() -> str:
    return (STATIC / "login.html").read_text(encoding="utf-8")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page() -> str:
    return (STATIC / "dashboard.html").read_text(encoding="utf-8")


@app.get("/admin", response_class=HTMLResponse)
def admin_page() -> str:
    return (STATIC / "admin.html").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════
#  审计日志（记文件）
# ═══════════════════════════════════════════════════════════

def _write_audit(question: str, hits: list[dict], answer: str,
                 route_info: dict | None = None) -> None:
    """把每次问答写入审计日志，满足"可审计"红线。

    P2: route_info 包含路由分类信息 {type, method, confidence}。
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "question": question,
        "hit_ids": [h.get("id", f"kg:{h.get('subject','')}-{h.get('object','')}") for h in hits],
        "hit_sources": [f"{h['subject']}→{h['object']}" if h.get("type") == "kg_fact" else f"{h['source']}·{h['chapter'][:20]}" for h in hits],
        "answer": answer,
        "retriever": get_retriever(),
        "top_k": get_top_k(),
    }
    if route_info:
        record["route_type"] = route_info.get("type", "")
        record["route_method"] = route_info.get("method", "")
        record["route_confidence"] = route_info.get("confidence", 0)
    with (LOG_DIR / "qa_audit.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ═══════════════════════════════════════════════════════════
#  用户 API：SSE 问答（含审计日志）
# ═══════════════════════════════════════════════════════════

async def _stream(question: str, history: list[dict] | None = None):
    # 多轮：把"他"替换为上一轮提到的人名，让检索更精准
    from retrieval.kg_search import rewrite_query
    search_query = rewrite_query(question, history)

    # ── P2 智能路由：先分类问题类型，再走对应策略 ──
    route_info: dict | None = None
    try:
        from router import route as route_question
        route_result, strategy = route_question(search_query)
        route_info = {
            "type": route_result.question_type,
            "method": route_result.method,
            "confidence": route_result.confidence,
            "reason": route_result.reason,
            "strategy": strategy.name,
        }
        # 策略化检索
        from retrieval.fusion import search_with_strategy
        hits = search_with_strategy(search_query, strategy=strategy)
    except ImportError:
        # 未装 router 模块，回退到常规检索
        hits = search(search_query)

    # 通知前端路由类型
    if route_info:
        yield f"data: __ROUTE__{json.dumps(route_info, ensure_ascii=False)}\n\n"
    if not hits:
        yield f"data: 根据现有资料未找到相关内容。\n\n"
        _write_audit(question, [], "根据现有资料未找到相关内容。", route_info=route_info)
        return

    # ── KG 图谱数据：从 kg_fact 命中构建节点+边 ──
    kg_facts = [h for h in hits if h.get("type") == "kg_fact"]
    if kg_facts:
        nodes_set: dict[str, dict] = {}
        edges: list[dict] = []
        for f in kg_facts:
            s, r, o = f["subject"], f["relation"], f["object"]
            for name in (s, o):
                if name not in nodes_set:
                    nodes_set[name] = {"name": name, "category": 0}
            edges.append({"source": s, "target": o, "label": r})
        yield f"data: __GRAPH__{json.dumps({'nodes': list(nodes_set.values()), 'edges': edges}, ensure_ascii=False)}\n\n"

    # ── 原文引用数据（P0: 带页码、置信度等证据信息）──
    source_items = []
    for h in hits:
        item = {
            "source": h.get("source", "知识图谱"),
            "chapter": h.get("chapter", ""),
            "score": h.get("score", 0),
        }
        if h.get("type") == "kg_fact":
            item["text"] = f"{h['subject']} —{h['relation']}→ {h['object']}"
            item["kind"] = "kg"
            conf = h.get("confidence", 0)
            if conf > 0:
                item["confidence"] = round(conf, 2)
            if h.get("source_chunk_id"):
                item["source_chunk_id"] = h["source_chunk_id"]
        else:
            txt = h.get("text", "")
            item["text"] = txt[:300]
            item["has_more"] = len(txt) > 300
            item["kind"] = "text"
            if h.get("page_no"):
                item["page_no"] = h["page_no"]
            if h.get("content_hash"):
                item["content_hash"] = h["content_hash"][:12]  # 只传前 12 位，够区分了
        source_items.append(item)
    yield f"data: __SOURCES__{json.dumps(source_items, ensure_ascii=False)}\n\n"

    def _hit_label(h: dict) -> str:
        s = h.get("score", "")
        sc = f" [{s:.2f}]" if s else ""
        if h.get("type") == "kg_fact":
            return f"{h['subject']}→{h['object']}{sc}"
        return f"{h['source']}·{h['chapter'][:25]}{sc}"
    sources = "，".join(_hit_label(h) for h in hits)
    yield f"data: [检索到 {len(hits)} 条参考资料：{sources}]\n\n"

    collected: list[str] = []
    try:
        for piece in answer_stream(question, hits, history=history):
            collected.append(piece)
            yield f"data: {piece}\n\n"
    except Exception as e:
        yield f"data: [系统错误：生成回答失败，请检查 Ollama 服务是否运行]\n\n"
        collected.append(f"[ERROR: {e}]")
    _write_audit(question, hits, "".join(collected), route_info=route_info)


@app.post("/api/ask")
async def ask(request: Request):
    body = await request.json()
    question = body.get("question", "").strip()
    history = body.get("history", None)
    if not question:
        return StreamingResponse(
            iter(["data: 请输入问题。\n\n"]),
            media_type="text/event-stream",
        )
    return StreamingResponse(
        _stream(question, history=history),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@app.post("/api/agent/ask")
async def agent_ask(request: Request):
    """Agent 模式：LLM 自主决定调哪个工具。"""
    body = await request.json()
    question = body.get("question", "").strip()
    history = body.get("history", None)
    if not question:
        return StreamingResponse(
            iter(["data: 请输入问题。\n\n"]),
            media_type="text/event-stream",
        )
    return StreamingResponse(
        agent_ask_stream(question, history=history),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


# ═══════════════════════════════════════════════════════════
#  用户认证 API
# ═══════════════════════════════════════════════════════════

@app.post("/api/auth/register")
async def api_register(request: Request):
    """注册新用户。"""
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    display_name = body.get("display_name", "").strip() or None
    try:
        result = auth_register(username, password, display_name)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/login")
async def api_login(request: Request):
    """用户登录。"""
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    try:
        result = auth_login(username, password)
        return result
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.get("/api/auth/me")
def api_me(user: dict = Depends(get_current_user)):
    """获取当前登录用户信息。"""
    return {"ok": True, "user": user}


# ═══════════════════════════════════════════════════════════
#  管理 API
# ═══════════════════════════════════════════════════════════

# ── 辅助：读日志 ──

def _read_logs() -> list[dict]:
    log_file = LOG_DIR / "qa_audit.jsonl"
    if not log_file.exists():
        return []
    records = []
    for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


# ── 健康检查 ──

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "retriever": retriever_label(),
        "chunks": chunk_count(),
    }


# ── 项目配置（供前端读） ──

@app.get("/api/config")
def public_config():
    """返回前端需要的项目配置：名称、领域、印章字、示例问题。
    按当前激活的 domain 自动选择配置文件。"""
    domain = get_active_domain()
    cfg = {
        "name": get_active_name(),
        "domain": domain,
        "seal": "文",
        "hints": [],
    }
    # 优先按领域查找 domain_{领域}.json
    for candidate in [CONFIG_DIR / f"domain_{domain}.json", CONFIG_DIR / "domain.json"]:
        if candidate.is_file():
            dc = json.loads(candidate.read_text(encoding="utf-8"))
            cfg["seal"] = dc.get("seal", cfg["seal"])
            cfg["hints"] = dc.get("hints", cfg["hints"])
            break
    return cfg


# ── 系统状态 ──

@app.get("/api/admin/status", dependencies=[Depends(_verify_admin)])
def admin_status():
    logs = _read_logs()
    last_qa = logs[-1]["time"] if logs else None
    uptime = str(datetime.now() - _START_TIME).split(".")[0]
    # 用管理端领域查块数和 KG，不影响用户端
    admin_dom = get_admin_domain()
    from retrieval.db import get_conn
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM chunks WHERE source = %s AND embedding IS NOT NULL", (admin_dom,))
        admin_chunks = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM kg_triples WHERE source = %s", (admin_dom,))
        admin_kg = cur.fetchone()[0]
    return {
        "uptime": uptime,
        "started_at": _START_TIME.isoformat(timespec="seconds"),
        "retriever": retriever_label(),
        "retriever_mode": get_retriever(),
        "top_k": get_top_k(),
        "chunks": admin_chunks,
        "kg_triples": admin_kg,
        "wiki_pages": wiki_count(),
        "llm_model": llm_config.model,
        "llm_provider": llm_config.provider,
        "qa_log_count": len(logs),
        "last_qa_time": last_qa,
        # P4 审核统计
        "review_pending": _get_review_pending(admin_dom),
        # P3 Neo4j 图谱状态
        "neo4j": _get_neo4j_status(),
        # P5 数据源与更新管线
        "sources": _get_p5_status(),
    }


def _get_neo4j_status() -> dict:
    """获取 Neo4j 图谱连接和同步状态。"""
    try:
        from kg.neo4j_conn import is_available
        from kg.sync_to_neo4j import sync_stats
        if not is_available():
            return {"available": False, "nodes": 0, "relationships": 0}
        stats = sync_stats()
        return {
            "available": True,
            "nodes": stats.get("nodes", 0),
            "relationships": stats.get("relationships", 0),
        }
    except ImportError:
        return {"available": False, "nodes": 0, "relationships": 0}


def _get_p5_status() -> dict:
    """获取 P5 数据源与更新管线状态。"""
    try:
        from updater.reporter import generate_report
        report = generate_report()
        return report
    except ImportError:
        return {"sources": {"total": 0}, "last_scan": None}
    except Exception as e:
        return {"error": str(e)}


# ── 统计摘要 ──

@app.get("/api/admin/stats", dependencies=[Depends(_verify_admin)])
def admin_stats():
    """问答统计：总量、今日、命中率、热门问题。"""
    logs = _read_logs()
    today = date.today().isoformat()
    today_logs = [l for l in logs if (l.get("time") or "").startswith(today)]
    total = len(logs)
    hit_count = sum(1 for l in logs if l.get("hit_ids"))
    today_total = len(today_logs)
    today_hit = sum(1 for l in today_logs if l.get("hit_ids"))

    # 热门问题 top 5（按出现次数，简化：完全匹配）
    from collections import Counter
    q_counter = Counter(l.get("question", "") for l in logs if l.get("question"))
    top_questions = [{"q": q, "n": n} for q, n in q_counter.most_common(5) if n > 1]

    return {
        "total_qa": total,
        "hit_rate": round(hit_count / total * 100, 1) if total else 0,
        "today_qa": today_total,
        "today_hit_rate": round(today_hit / today_total * 100, 1) if today_total else 0,
        "retriever": retriever_label(),
        "top_questions": top_questions,
    }


# ── 问答日志（搜索 + 分页） ──

@app.get("/api/admin/logs", dependencies=[Depends(_verify_admin)])
def admin_logs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    q: str = Query("", description="搜索问题关键词"),
):
    """返回问答日志，支持搜索和分页。"""
    records = _read_logs()
    if q:
        records = [r for r in records if q.lower() in (r.get("question") or "").lower()]
    total = len(records)
    # 按时间倒序
    records.reverse()
    page = records[offset : offset + limit]
    return {"total": total, "logs": page}


# ── CSV 导出 ──

@app.get("/api/admin/logs/export", dependencies=[Depends(_verify_admin)])
def admin_logs_export():
    """导出全部问答日志为 CSV。"""
    import csv
    import io

    records = _read_logs()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["时间", "问题", "回答", "命中来源"])
    for r in records:
        sources = ", ".join(r.get("hit_sources", r.get("hit_ids", [])))
        writer.writerow([
            r.get("time", ""),
            r.get("question", ""),
            r.get("answer", ""),
            sources,
        ])

    csv_content = output.getvalue()
    output.close()
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": "attachment; filename=reddream_logs.csv"},
    )


# ── 检索方式 查看/切换 ──

@app.get("/api/admin/retriever", dependencies=[Depends(_verify_admin)])
def admin_get_retriever():
    return {"mode": get_retriever(), "label": retriever_label()}


@app.post("/api/admin/retriever", dependencies=[Depends(_verify_admin)])
async def admin_set_retriever(request: Request):
    body = await request.json()
    try:
        set_retriever(body.get("mode", ""))
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "mode": get_retriever(), "label": retriever_label()}


# ── Top-K 查看/调整 ──

# ── KG 关系图数据 ──

@app.get("/api/kg/graph")
def kg_graph(entity: str = ""):
    """返回某个人物的 KG 关系图数据（ECharts 格式）。"""
    if not entity:
        return {"nodes": [], "edges": []}
    triples = query_by_entity(entity)
    if not triples:
        return {"nodes": [], "edges": []}

    nodes_set: dict[str, dict] = {}
    edges: list[dict] = []

    for t in triples:
        s, r, o = t["subject"], t["relation"], t["object"]
        for name in (s, o):
            if name not in nodes_set:
                nodes_set[name] = {"name": name, "category": 0 if name == entity else 1}
        edges.append({"source": s, "target": o, "label": r})

    return {"nodes": list(nodes_set.values()), "edges": edges}


@app.get("/api/admin/topk", dependencies=[Depends(_verify_admin)])
def admin_get_topk():
    return {"top_k": get_top_k()}


@app.post("/api/admin/topk", dependencies=[Depends(_verify_admin)])
async def admin_set_topk(request: Request):
    body = await request.json()
    try:
        set_top_k(int(body.get("top_k", 5)))
    except (ValueError, TypeError) as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "top_k": get_top_k()}


# ── 领域/书籍 查看与切换 ──

@app.get("/api/domains")
def list_available_domains():
    """列出所有可用的书籍（公开接口，前端下拉框用）。"""
    from config.settings import ROOT
    domains = []
    seen = set()
    # 1. 扫描 entities_{domain}.json
    for f in sorted(CONFIG_DIR.glob("entities_*.json")):
        domain = f.stem.replace("entities_", "")
        _add_domain_entry(domains, seen, domain, ROOT)
    # 2. 如果 entities.json 存在，视为"红楼梦"（默认领域）
    default_path = CONFIG_DIR / "entities.json"
    if default_path.exists() and "红楼梦" not in seen:
        _add_domain_entry(domains, seen, "红楼梦", ROOT)
    return {"domains": domains, "active": get_active_domain()}


def _add_domain_entry(domains: list, seen: set, domain: str, root: Path) -> None:
    """构造一条领域条目。"""
    if domain in seen:
        return
    seen.add(domain)
    chunk_file = Path("chunks") / f"{domain}.json"
    dcfg_path = CONFIG_DIR / f"domain_{domain}.json"
    if dcfg_path.is_file():
        dc = json.loads(dcfg_path.read_text(encoding="utf-8"))
        seal = dc.get("seal", domain[0])
    else:
        # 回退到 domain.json
        fallback = CONFIG_DIR / "domain.json"
        if fallback.is_file():
            dc = json.loads(fallback.read_text(encoding="utf-8"))
            seal = dc.get("seal", domain[0])
        else:
            seal = domain[0]
    domains.append({
        "domain": domain,
        "seal": seal,
        "has_chunks": (root / chunk_file).exists(),
    })


@app.post("/api/switch-domain")
async def switch_domain_public(request: Request):
    """运行时切换书籍（公开接口，前端选择器用）。

    切换完成后前端刷新页面即可加载新书。
    """
    body = await request.json()
    domain = body.get("domain", "").strip()
    if not domain:
        return {"ok": False, "error": "domain 不能为空"}

    # 验证 domain 有效：先查 entities_{domain}.json，再回退 entities.json
    entity_path = CONFIG_DIR / f"entities_{domain}.json"
    default_path = CONFIG_DIR / "entities.json"
    if not entity_path.exists() and not default_path.exists():
        return {"ok": False, "error": f"未知领域：{domain}（缺少实体配置）"}

    info = switch_domain(domain)
    info["ok"] = True
    info["chunk_count"] = chunk_count()
    return info


# admin 版（保留，管理后台用）
@app.get("/api/admin/domains", dependencies=[Depends(_verify_admin)])
def admin_list_domains():
    """列出所有可用的书籍（管理后台用）。"""
    from config.settings import ROOT
    domains = []
    for f in CONFIG_DIR.glob("entities_*.json"):
        domain = f.stem.replace("entities_", "")
        chunk_file = Path("chunks") / f"{domain}.json"
        dcfg_path = CONFIG_DIR / f"domain_{domain}.json"
        has_config = dcfg_path.is_file()
        domains.append({
            "domain": domain,
            "has_chunks": (ROOT / chunk_file).exists(),
            "has_config": has_config,
        })
    return {"domains": domains, "active": get_admin_domain()}


@app.get("/api/admin/domain")
def admin_get_domain():
    """查看管理后台当前激活的领域。"""
    return {
        "domain": get_admin_domain(),
        "name": get_admin_name(),
    }


@app.post("/api/admin/switch-domain")
async def admin_switch_domain(request: Request):
    """管理后台切换书籍（不影响用户端状态）。"""
    body = await request.json()
    domain = body.get("domain", "").strip()
    if not domain:
        return {"ok": False, "error": "domain 不能为空"}

    # 验证 domain 有效
    entity_path = CONFIG_DIR / f"entities_{domain}.json"
    default_path = CONFIG_DIR / "entities.json"
    if not entity_path.exists() and not default_path.exists():
        return {"ok": False, "error": f"未知领域：{domain}（缺少实体配置）"}

    info = switch_admin_domain(domain)
    info["ok"] = True
    # 直接从数据库查当前 domain 的块数，不切全局状态
    from retrieval.db import get_conn
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM chunks WHERE source = %s AND embedding IS NOT NULL", (domain,))
        info["chunk_count"] = cur.fetchone()[0]
    return info


# ── P4 审核辅助 ──

def _get_review_pending(domain: str) -> dict:
    """获取审核待办统计（轻量，不依赖 review 模块导入成功）。"""
    try:
        from review import get_stats
        s = get_stats(domain)
        return {
            "chunks": s.pending_chunks,
            "kg": s.pending_kg,
            "wiki": s.pending_wiki,
            "total": s.total_pending,
        }
    except ImportError:
        return {"chunks": 0, "kg": 0, "wiki": 0, "total": 0}


# ═══════════════════════════════════════════════════════
#  审核 API（P4）
# ═══════════════════════════════════════════════════════

@app.get("/api/admin/review/queue", dependencies=[Depends(_verify_admin)])
def admin_review_queue(
    target_type: str = Query("", description="chunk / kg / wiki，空=全部"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """待审队列。"""
    domain = get_admin_domain()
    try:
        from review import query_queue
        items = query_queue(domain, target_type=target_type, limit=limit, offset=offset)
        return {
            "ok": True,
            "domain": domain,
            "items": [
                {
                    "target_type": it.target_type,
                    "target_id": it.target_id,
                    "title": it.title,
                    "confidence": it.confidence,
                    "review_status": it.review_status,
                    "detail": it.detail,
                    "created_at": it.created_at,
                }
                for it in items
            ],
        }
    except ImportError:
        return {"ok": False, "error": "审核模块未启用"}


@app.get("/api/admin/review/stats", dependencies=[Depends(_verify_admin)])
def admin_review_stats():
    """审核统计。"""
    domain = get_admin_domain()
    try:
        from review import get_stats
        s = get_stats(domain)
        return {
            "ok": True,
            "domain": domain,
            "pending_chunks": s.pending_chunks,
            "pending_kg": s.pending_kg,
            "pending_wiki": s.pending_wiki,
            "total_pending": s.total_pending,
            "approved_today": s.approved_today,
            "rejected_today": s.rejected_today,
        }
    except ImportError:
        return {"ok": False, "error": "审核模块未启用"}


@app.post("/api/admin/review/approve", dependencies=[Depends(_verify_admin)])
async def admin_review_approve(request: Request):
    """审核通过。"""
    body = await request.json()
    target_type = body.get("target_type", "")
    target_id = body.get("target_id", "")
    if not target_type or not target_id:
        raise HTTPException(status_code=400, detail="缺少 target_type 或 target_id")
    try:
        from review import approve
        ok = approve(target_type, str(target_id))
        return {"ok": ok, "action": "approved"}
    except ImportError:
        return {"ok": False, "error": "审核模块未启用"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/admin/review/reject", dependencies=[Depends(_verify_admin)])
async def admin_review_reject(request: Request):
    """驳回。"""
    body = await request.json()
    target_type = body.get("target_type", "")
    target_id = body.get("target_id", "")
    reason = body.get("reason", "")
    if not target_type or not target_id:
        raise HTTPException(status_code=400, detail="缺少 target_type 或 target_id")
    try:
        from review import reject
        ok = reject(target_type, str(target_id), reason=reason)
        return {"ok": ok, "action": "rejected"}
    except ImportError:
        return {"ok": False, "error": "审核模块未启用"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/admin/review/revise", dependencies=[Depends(_verify_admin)])
async def admin_review_revise(request: Request):
    """修正。"""
    body = await request.json()
    target_type = body.get("target_type", "")
    target_id = body.get("target_id", "")
    updates = body.get("updates", {})
    if not target_type or not target_id:
        raise HTTPException(status_code=400, detail="缺少 target_type 或 target_id")
    try:
        from review import revise
        ok = revise(target_type, str(target_id), updates)
        return {"ok": ok, "action": "revised"}
    except ImportError:
        return {"ok": False, "error": "审核模块未启用"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/admin/review/history", dependencies=[Depends(_verify_admin)])
def admin_review_history(
    target_type: str = Query("", description="筛选类型"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """审核历史。"""
    try:
        from review import get_history
        items = get_history(target_type=target_type, limit=limit, offset=offset)
        return {"ok": True, "items": items}
    except ImportError:
        return {"ok": False, "error": "审核模块未启用"}


# ═══════════════════════════════════════════════════════
#  图谱探索 API（P3 Neo4j 多跳查询）
# ═══════════════════════════════════════════════════════


@app.get("/api/graph/path")
def api_graph_path(
    entity_a: str = Query(..., description="起始实体"),
    entity_b: str = Query(..., description="目标实体"),
    max_depth: int = Query(3, ge=1, le=5),
):
    """查找两个实体之间的最短关系路径（支持多跳）。"""
    try:
        from retrieval.graph_search import find_paths
        domain = get_active_domain()
        paths = find_paths(entity_a, entity_b, max_depth=max_depth, domain=domain)
        return {"ok": True, "entity_a": entity_a, "entity_b": entity_b, "paths": paths}
    except ImportError:
        return {"ok": False, "error": "图谱搜索模块未启用"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/graph/neighbors")
def api_graph_neighbors(
    entity: str = Query(..., description="中心实体"),
    depth: int = Query(2, ge=1, le=3),
):
    """展开某实体的邻居网络。"""
    try:
        from retrieval.graph_search import expand_neighbors
        domain = get_active_domain()
        net = expand_neighbors(entity, max_depth=depth, domain=domain)
        return {"ok": True, "entity": entity, **net}
    except ImportError:
        return {"ok": False, "error": "图谱搜索模块未启用"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/graph/common")
def api_graph_common(
    entity_a: str = Query(..., description="实体 A"),
    entity_b: str = Query(..., description="实体 B"),
):
    """查找两个实体的共同邻居。"""
    try:
        from retrieval.graph_search import common_neighbors
        domain = get_active_domain()
        commons = common_neighbors(entity_a, entity_b, domain=domain)
        return {"ok": True, "entity_a": entity_a, "entity_b": entity_b, "commons": commons}
    except ImportError:
        return {"ok": False, "error": "图谱搜索模块未启用"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/graph/search")
def api_graph_search(
    q: str = Query(..., description="实体关键词"),
    limit: int = Query(10, ge=1, le=50),
):
    """搜索图谱中的实体。"""
    try:
        from retrieval.graph_search import search_entities
        domain = get_active_domain()
        entities = search_entities(q, domain=domain, limit=limit)
        return {"ok": True, "entities": entities}
    except ImportError:
        return {"ok": False, "error": "图谱搜索模块未启用"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/graph/sync-status")
def api_graph_sync_status():
    """Neo4j 同步状态。"""
    try:
        from kg.sync_to_neo4j import sync_stats
        stats = sync_stats()
        return {"ok": True, **stats}
    except ImportError:
        return {"ok": False, "error": "Neo4j 同步模块未启用"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/admin/graph/sync", dependencies=[Depends(_verify_admin)])
async def api_graph_sync(request: Request):
    """触发 Neo4j 全量同步（管理后台操作）。"""
    body = await request.json()
    domain = body.get("domain", "") or get_admin_domain()
    try:
        from kg.sync_to_neo4j import full_sync
        count = full_sync(domain=domain)
        return {"ok": True, "synced": count, "domain": domain}
    except ImportError:
        return {"ok": False, "error": "Neo4j 同步模块未启用"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════════
#  数据源与更新管线 API（P5）
# ═══════════════════════════════════════════════════════

@app.get("/api/sources", dependencies=[Depends(_verify_admin)])
def api_sources_list(domain: str = ""):
    """列出所有数据源。"""
    try:
        from collector.sources import list_sources
        sources = list_sources(domain=domain, enabled_only=False)
        return {"ok": True, "sources": sources, "total": len(sources)}
    except ImportError:
        return {"ok": False, "error": "P5 模块未启用"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/sources/register", dependencies=[Depends(_verify_admin)])
async def api_sources_register(request: Request):
    """注册新数据源。"""
    body = await request.json()
    name = body.get("name", "")
    path = body.get("path", "")
    domain = body.get("domain", "")
    source_type = body.get("source_type", "file")
    if not name or not path or not domain:
        return {"ok": False, "error": "缺少 name / path / domain"}
    try:
        from collector.sources import register
        sid = register(name=name, path=path, domain=domain, source_type=source_type)
        return {"ok": True, "source_id": sid}
    except ImportError:
        return {"ok": False, "error": "P5 模块未启用"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/sources/scan", dependencies=[Depends(_verify_admin)])
async def api_sources_scan(request: Request):
    """触发全量扫描。"""
    body = await request.json()
    domain = body.get("domain", "")
    try:
        from collector.scanner import scan_all
        results = scan_all(domain=domain)
        return {"ok": True, "results": results, "total": len(results)}
    except ImportError:
        return {"ok": False, "error": "P5 模块未启用"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/sources/update", dependencies=[Depends(_verify_admin)])
async def api_sources_update(request: Request):
    """启动后台增量更新管线（异步：扫描→处理→KG→Wiki）。"""
    body = await request.json()
    domain = body.get("domain", "")
    entities_refresh = body.get("entities_refresh", True)
    try:
        from updater.pipeline import start_async_update
        result = start_async_update(domain=domain, entities_refresh=entities_refresh)
        return result
    except ImportError:
        return {"ok": False, "error": "P5 更新模块未启用"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/sources/update/status", dependencies=[Depends(_verify_admin)])
def api_sources_update_status():
    """查询当前增量更新的执行状态。"""
    try:
        from updater.pipeline import get_async_status
        return {"ok": True, **get_async_status()}
    except ImportError:
        return {"ok": False, "error": "P5 更新模块未启用"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/sources/logs", dependencies=[Depends(_verify_admin)])
def api_sources_logs(domain: str = "", action: str = "", limit: int = 50):
    """查询更新日志。"""
    try:
        from updater.reporter import get_update_logs
        logs = get_update_logs(domain=domain, action=action, limit=limit)
        return {"ok": True, "logs": logs, "total": len(logs)}
    except ImportError:
        return {"ok": False, "error": "P5 模块未启用"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/sources/report", dependencies=[Depends(_verify_admin)])
def api_sources_report(domain: str = ""):
    """获取更新状态报告。"""
    try:
        from updater.reporter import generate_report
        report = generate_report(domain=domain)
        return {"ok": True, **report}
    except ImportError:
        return {"ok": False, "error": "P5 模块未启用"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════════
#  Wiki API（P1）
# ═══════════════════════════════════════════════════════

@app.get("/api/wiki/search")
def api_wiki_search(q: str = "", page_type: str = "", limit: int = 10):
    """搜索 Wiki 页面。"""
    if not _HAS_WIKI:
        return {"ok": False, "error": "Wiki 模块未启用"}
    results = wiki_search(q, top_k=limit) if q else []
    return {"ok": True, "pages": results, "total": wiki_count()}


@app.get("/api/wiki/list")
def api_wiki_list(page_type: str = ""):
    """列出当前领域的所有 Wiki 页面。"""
    if not _HAS_WIKI:
        return {"ok": False, "error": "Wiki 模块未启用"}
    domain = get_active_domain()
    pt = page_type if page_type else None
    pages = wiki_list(domain, page_type=pt)
    return {"ok": True, "domain": domain, "pages": pages, "total": len(pages)}


@app.get("/api/wiki/page")
def api_wiki_page(page_type: str = "", title: str = ""):
    """获取单页 Wiki 完整内容。"""
    if not _HAS_WIKI:
        return {"ok": False, "error": "Wiki 模块未启用"}
    if not page_type or not title:
        return {"ok": False, "error": "缺少 page_type 或 title"}
    domain = get_active_domain()
    page = wiki_get(domain, page_type, title)
    if page is None:
        return {"ok": False, "error": "页面不存在"}
    return {"ok": True, "page": page}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=7860)
