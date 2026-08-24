"""增量更新管线（P5）：对变更的数据源执行完整处理流程。

策略（v1 简单重处理）：
1. 对变更的源文件重新切块
2. 软删除旧块（is_active = false）
3. 新块计算向量 + upsert 入库
4. 抽取 KG 三元组
5. 受影响实体刷新 Wiki 页面
6. 更新数据源状态
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from collector.scanner import scan_all, scan_source
from collector.sources import (
    update_status,
    get_source,
    STATUS_ACTIVE,
    STATUS_CHANGED,
    STATUS_ERROR,
)
from kb_builder.split import split_file, _compute_hash
from llm.embedding import embed_many
from retrieval.db import get_conn

BATCH_SIZE = 32


# ══════════════════════════════════════════════════════
#  块更新（v2：差量 diff，按 content_hash 只更新变更块）
# ══════════════════════════════════════════════════════

def _load_existing_chunk_hashes(source_name: str) -> dict[str, dict]:
    """加载某数据源现存 chunk 的 hash 映射。返回 {content_hash: {id, source, ...}}"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, source, chapter, body, content_hash, page_no, paragraph_no "
            "FROM chunks WHERE source = %s AND is_active = TRUE",
            (source_name,),
        )
        rows = cur.fetchall()
    result = {}
    for r in rows:
        h = r[4]  # content_hash
        if h:
            result[h] = {
                "id": r[0], "source": r[1], "chapter": r[2],
                "text": r[3], "content_hash": h,
                "page_no": r[5], "paragraph_no": r[6],
            }
    return result


def _deactivate_chunk_ids(chunk_ids: list[str]) -> int:
    """按 chunk id 列表批量设为 is_active = false。返回影响行数。"""
    if not chunk_ids:
        return 0
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE chunks SET is_active = FALSE WHERE id = ANY(%s)",
            (chunk_ids,),
        )
        n = cur.rowcount
        conn.commit()
    return n


def _keep_chunk_ids(chunk_ids: list[str]) -> int:
    """标记这些 chunk 保持 is_active = true。返回影响行数。"""
    if not chunk_ids:
        return 0
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE chunks SET is_active = TRUE WHERE id = ANY(%s)",
            (chunk_ids,),
        )
        n = cur.rowcount
        conn.commit()
    return n


def _upsert_chunks_batch(new_chunks: list[dict]) -> int:
    """仅对新增/变更的 chunk 做 embedding + upsert。返回写入数。"""
    if not new_chunks:
        return 0
    total = len(new_chunks)
    done = 0
    with get_conn() as conn:
        for i in range(0, total, BATCH_SIZE):
            batch = new_chunks[i : i + BATCH_SIZE]
            texts = [c["text"] for c in batch]
            vecs = embed_many(texts)
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks(id, source, chapter, body, embedding, "
                    "page_no, paragraph_no, content_hash, is_active) "
                    "VALUES(%s, %s, %s, %s, %s, %s, %s, %s, TRUE) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "source = EXCLUDED.source, "
                    "chapter = EXCLUDED.chapter, "
                    "body = EXCLUDED.body, "
                    "embedding = EXCLUDED.embedding, "
                    "page_no = EXCLUDED.page_no, "
                    "paragraph_no = EXCLUDED.paragraph_no, "
                    "content_hash = EXCLUDED.content_hash, "
                    "is_active = TRUE",
                    [(c["id"], c["source"], c.get("chapter"), c["text"], v,
                      c.get("page_no"), c.get("paragraph_no"), c.get("content_hash"))
                     for c, v in zip(batch, vecs)],
                )
            conn.commit()
            done += len(batch)
    return done


def update_chunks(source: dict) -> dict:
    """更新单个数据源的 chunk（v2：差量 diff）。

    1. 加载现存 chunk hash 映射
    2. 重新切块
    3. 新块 hash 在映射中 → 保持 is_active（未变更）
    4. 新块 hash 不在映射中 → 做 embedding + upsert（新增/变更）
    5. 映射中未被引用的 → 设为 is_active = false（已删除）

    Returns:
        {source_id, status, total, unchanged, new_or_changed, deactivated}
    """
    source_id = source["id"]
    source_name = source["name"]
    file_path = Path(source["path"])

    if not file_path.exists():
        update_status(source_id, status=STATUS_ERROR, error_msg="文件不存在")
        return {"source_id": source_id, "status": "error", "error": "文件不存在"}

    # 1. 加载现存 chunk hash
    existing = _load_existing_chunk_hashes(source_name)

    # 2. 重新切块
    try:
        new_chunks = split_file(file_path, source_name)
    except Exception as e:
        update_status(source_id, status=STATUS_ERROR, error_msg=str(e))
        return {"source_id": source_id, "status": "error", "error": f"切块失败: {e}"}

    if not new_chunks:
        # 文件变空了：deactivate 全部
        all_ids = [c["id"] for c in existing.values()]
        deactivated = _deactivate_chunk_ids(all_ids)
        update_status(source_id, status=STATUS_ACTIVE, chunk_count=0)
        return {
            "source_id": source_id, "status": "ok",
            "total": 0, "unchanged": 0, "new_or_changed": 0,
            "deactivated": deactivated,
        }

    # 3. 分类：已存在（hash匹配）vs 新/变更
    unchanged_ids: list[str] = []
    changed_chunks: list[dict] = []
    seen_hashes: set[str] = set()

    for c in new_chunks:
        h = c.get("content_hash", "")
        seen_hashes.add(h)
        if h and h in existing:
            unchanged_ids.append(existing[h]["id"])
        else:
            changed_chunks.append(c)

    # 4. 找出被删除的 chunk（旧有但新文件中不存在）
    removed_ids = [
        c["id"] for h, c in existing.items()
        if h not in seen_hashes
    ]

    # 5. 执行数据库操作
    deactivated = _deactivate_chunk_ids(removed_ids)
    kept = _keep_chunk_ids(unchanged_ids)

    new_count = 0
    if changed_chunks:
        try:
            new_count = _upsert_chunks_batch(changed_chunks)
        except Exception as e:
            update_status(source_id, status=STATUS_ERROR, error_msg=f"向量入库失败: {e}")
            return {"source_id": source_id, "status": "error", "error": f"向量入库失败: {e}"}

    # 6. 更新数据源状态
    total_active = len(unchanged_ids) + new_count
    update_status(
        source_id,
        status=STATUS_ACTIVE,
        chunk_count=total_active,
    )

    return {
        "source_id": source_id,
        "status": "ok",
        "total": total_active,
        "unchanged": len(unchanged_ids),
        "new_or_changed": new_count,
        "deactivated": deactivated,
    }


# ══════════════════════════════════════════════════════
#  KG 更新
# ══════════════════════════════════════════════════════

def _load_chunks_for_source(source_name: str) -> list[dict]:
    """从 DB 加载某数据源当前激活的 chunk。"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, source, chapter, body, page_no "
            "FROM chunks WHERE source = %s AND is_active = TRUE "
            "ORDER BY id",
            (source_name,),
        )
        rows = cur.fetchall()
    return [
        {"id": r[0], "source": r[1], "chapter": r[2], "text": r[3], "page_no": r[4]}
        for r in rows
    ]


def _deactivate_old_triples(domain: str, source_name: str) -> int:
    """软删除某 domain + source 的旧三元组。返回影响行数。"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE kg_triples SET review_status = 'deprecated' "
            "WHERE domain = %s AND source = %s "
            "AND (review_status IS NULL OR review_status != 'rejected')",
            (domain, source_name),
        )
        n = cur.rowcount
        conn.commit()
    return n


def update_kg(source: dict) -> dict:
    """更新单个数据源的 KG：重新抽取三元组 → 软删除旧三元组 → 写入新三元组。

    Returns:
        {source_id, status, extracted, inserted}
    """
    source_id = source["id"]
    source_name = source["name"]
    domain = source["domain"]

    # 1. 加载当前激活的 chunk
    chunks = _load_chunks_for_source(source_name)
    if not chunks:
        return {
            "source_id": source_id,
            "status": "warning",
            "error": "没有激活的 chunk，跳过 KG 抽取",
        }

    # 2. 抽取三元组
    try:
        from kg.extract import extract_from_chunks
        triples = extract_from_chunks(chunks)
    except Exception as e:
        update_status(source_id, status=STATUS_ERROR, error_msg=f"KG 抽取失败: {e}")
        return {
            "source_id": source_id,
            "status": "error",
            "error": f"KG 抽取失败: {e}",
        }

    if not triples:
        return {
            "source_id": source_id,
            "status": "ok",
            "extracted": 0,
            "inserted": 0,
        }

    # 3. 软删除旧三元组（按 domain 定位）
    old_deactivated = _deactivate_old_triples(domain, source_name)

    # 4. 写入新三元组（带 domain）
    from kg.store import insert_triples
    inserted = insert_triples(triples, source=source_name, domain=domain)

    return {
        "source_id": source_id,
        "status": "ok",
        "extracted": len(triples),
        "inserted": inserted,
        "old_deactivated": old_deactivated,
    }


# ══════════════════════════════════════════════════════
#  Wiki 更新
# ══════════════════════════════════════════════════════

def update_wiki(domain: str, entity_names: list[str] | None = None) -> dict:
    """为指定领域刷新 Wiki 页面。

    Args:
        domain: 领域名（如 "红楼梦"）
        entity_names: 要刷新的实体列表，不传则全部重新生成

    Returns:
        {domain, total, success, failed, skipped}
    """
    try:
        from wiki.generator import generate_all
        stats = generate_all(
            domain=domain,
            page_type="character",
            entities=entity_names,
        )
        return {"domain": domain, **stats}
    except Exception as e:
        return {"domain": domain, "status": "error", "error": str(e)}


def _find_affected_entities(domain: str) -> list[str]:
    """从某领域的三元组中找出受影响的实体名列表。

    策略：取 subject/object 中出现频率最高的 top-N 实体。
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT subject FROM kg_triples WHERE domain = %s "
            "AND (review_status IS NULL OR review_status = 'pending') "
            "UNION ALL "
            "SELECT object FROM kg_triples WHERE domain = %s "
            "AND (review_status IS NULL OR review_status = 'pending')",
            (domain, domain),
        )
        rows = cur.fetchall()

    from collections import Counter
    counter = Counter(r[0] for r in rows)
    # 返回出现次数 >= 2 的实体
    return [name for name, cnt in counter.most_common() if cnt >= 2]


# ══════════════════════════════════════════════════════
#  完整增量更新流程
# ══════════════════════════════════════════════════════

def process_source(source_id: int) -> dict:
    """对单个数据源执行完整的增量处理（chunks + KG）。"""
    source = get_source(source_id)
    if not source:
        return {"status": "error", "error": f"数据源不存在: {source_id}"}

    name = source["name"]
    domain = source["domain"]
    result = {
        "source_id": source_id,
        "name": name,
        "domain": domain,
    }

    # Step 1: 重新扫描（更新 hash）
    scan_result = scan_source(source)
    action = scan_result.get("action", "error")
    result["scan_action"] = action

    if action == "unchanged":
        result["status"] = "skipped"
        result["reason"] = "文件未变更"
        return result

    if action == "error":
        result["status"] = "error"
        result["error"] = scan_result.get("error", "扫描失败")
        return result

    # Step 2: 更新 chunks
    print(f"  [{name}] 重新切块 + 向量入库 ...", flush=True)
    chunk_result = update_chunks(source)
    result["chunks"] = chunk_result

    if chunk_result.get("status") != "ok":
        result["status"] = "error"
        result["error"] = chunk_result.get("error", "chunk 更新失败")
        return result

    # Step 3: 更新 KG
    print(f"  [{name}] KG 三元组抽取 ...", flush=True)
    kg_result = update_kg(source)
    result["kg"] = kg_result

    # Step 4: 刷新数据源 hash + 状态
    from collector.sources import compute_file_hash
    import os
    new_hash = compute_file_hash(source["path"])
    file_size = os.path.getsize(source["path"]) if os.path.exists(source["path"]) else 0
    update_status(
        source_id,
        status=STATUS_ACTIVE,
        file_hash=new_hash,
        file_size=file_size,
        chunk_count=chunk_result.get("total", 0),
    )

    result["status"] = "ok"
    return result


def process_all(domain: str = "", entities_refresh: bool = True) -> dict:
    """扫描 + 增量处理所有变更的数据源。

    Args:
        domain: 领域过滤，空 = 全部
        entities_refresh: 是否自动刷新受影响的 Wiki 页面

    Returns:
        {
            ok: bool,
            total_sources: int,
            scanned: int,
            processed: int,
            skipped: int,
            errors: int,
            results: [...],
            wiki: {...} | None,
        }
    """
    # Step 1: 扫描
    print("=" * 50)
    print("  P5 增量更新管线")
    print("=" * 50)
    print(f"\n[1/4] 扫描变更 ...")
    scan_results = scan_all(domain=domain)

    new_or_changed = [r for r in scan_results if r["action"] in ("new", "changed")]
    unchanged = [r for r in scan_results if r["action"] == "unchanged"]
    errors = [r for r in scan_results if r["action"] == "error"]

    print(f"  总计 {len(scan_results)} 个数据源: "
          f"{len(new_or_changed)} 需处理, {len(unchanged)} 未变更, {len(errors)} 异常")

    if not new_or_changed:
        print("  没有需要处理的数据源，跳过。")
        return {
            "ok": True,
            "total_sources": len(scan_results),
            "scanned": len(scan_results),
            "processed": 0,
            "skipped": len(unchanged),
            "errors": len(errors),
            "results": [],
            "wiki": None,
        }

    # Step 2: 逐个处理
    print(f"\n[2/4] 处理 {len(new_or_changed)} 个变更数据源 ...")
    results = []
    # v1 假设: source_name == domain（如"红楼梦"既是文件名也是领域名）
    # 收集 {source_name: domain} 映射，Wiki 刷新时 source_name 查 KG，domain 调生成器
    affected_map: dict[str, str] = {}

    for i, sr in enumerate(new_or_changed, 1):
        source_id = sr["source_id"]
        print(f"\n  ({i}/{len(new_or_changed)}) {sr['name']} [{sr['action']}]")
        result = process_source(source_id)
        results.append(result)
        if result["status"] == "ok":
            affected_map[result["name"]] = result["domain"]

    # Step 3: Wiki 刷新
    wiki_result = None
    if entities_refresh and affected_map:
        domains = set(affected_map.values())
        print(f"\n[3/4] Wiki 刷新（受影响领域: {', '.join(domains)}）...")
        wiki_results = {}
        for src_name, dom in affected_map.items():
            entities = _find_affected_entities(dom)
            if entities:
                print(f"  [{dom}] 受影响实体 ({len(entities)}): {', '.join(entities[:10])}...")
            else:
                print(f"  [{dom}] 未检测到明确受影响的实体，跳过 Wiki 刷新")
            wr = update_wiki(dom, entity_names=entities if entities else None)
            wiki_results[dom] = wr
        wiki_result = wiki_results
    else:
        print(f"\n[3/4] 跳过 Wiki 刷新")

    # Step 4: 汇总
    print(f"\n[4/4] 完成！")
    processed = sum(1 for r in results if r["status"] == "ok")
    failed = sum(1 for r in results if r["status"] == "error")

    summary = {
        "ok": True,
        "total_sources": len(scan_results),
        "scanned": len(scan_results),
        "processed": processed,
        "skipped": len(unchanged),
        "errors": len(errors) + failed,
        "results": results,
        "wiki": wiki_result,
    }

    print(f"\n  === 更新汇总 ===")
    print(f"  扫描: {summary['scanned']}")
    print(f"  处理: {summary['processed']}")
    print(f"  跳过: {summary['skipped']}")
    print(f"  异常: {summary['errors']}")

    return summary


def quick_update(source_id: int) -> dict:
    """快速增量更新单个数据源（不重新扫描，直接处理）。"""
    return process_source(source_id)


# ══════════════════════════════════════════════════════
#  异步执行（后台线程 + 状态轮询）
# ══════════════════════════════════════════════════════

import threading
from datetime import datetime as _dt

_pipeline_state: dict = {
    "running": False,
    "domain": "",
    "phase": "idle",         # idle / scanning / processing / wiki / done / error
    "started_at": None,
    "finished_at": None,
    "progress": {"current": 0, "total": 0},
    "summary": None,
    "error": None,
}
_lock = threading.Lock()


def get_async_status() -> dict:
    """获取当前管线异步执行状态（线程安全）。"""
    with _lock:
        return dict(_pipeline_state)


def _run_async(domain: str, entities_refresh: bool) -> None:
    """后台线程入口：执行 process_all 并更新状态。"""
    import io
    try:
        with _lock:
            _pipeline_state["running"] = True
            _pipeline_state["phase"] = "scanning"
            _pipeline_state["started_at"] = _dt.now().isoformat()
            _pipeline_state["progress"] = {"current": 0, "total": 0}
            _pipeline_state["summary"] = None
            _pipeline_state["error"] = None

        # 重定向 print 到内存缓冲（避免后台输出混乱）
        summary = process_all(domain=domain, entities_refresh=entities_refresh)

        with _lock:
            _pipeline_state["phase"] = "done"
            _pipeline_state["finished_at"] = _dt.now().isoformat()
            _pipeline_state["summary"] = summary
            _pipeline_state["progress"]["current"] = _pipeline_state["progress"]["total"]
            _pipeline_state["running"] = False
    except Exception as e:
        with _lock:
            _pipeline_state["phase"] = "error"
            _pipeline_state["error"] = str(e)
            _pipeline_state["finished_at"] = _dt.now().isoformat()
            _pipeline_state["running"] = False


def start_async_update(domain: str = "", entities_refresh: bool = True) -> dict:
    """启动后台增量更新。如果已有任务在跑，返回冲突。

    Returns:
        {ok, message, status}
    """
    with _lock:
        if _pipeline_state["running"]:
            return {
                "ok": False,
                "message": "已有更新任务正在执行中",
                "status": dict(_pipeline_state),
            }
        _pipeline_state["running"] = True
        _pipeline_state["domain"] = domain or "all"
        _pipeline_state["phase"] = "starting"
        _pipeline_state["started_at"] = _dt.now().isoformat()
        _pipeline_state["finished_at"] = None
        _pipeline_state["progress"] = {"current": 0, "total": 0}
        _pipeline_state["summary"] = None
        _pipeline_state["error"] = None

    t = threading.Thread(
        target=_run_async,
        args=(domain, entities_refresh),
        daemon=True,
        name="p5-pipeline",
    )
    t.start()

    return {
        "ok": True,
        "message": "增量更新已启动",
        "status": dict(_pipeline_state),
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--source":
        sid = int(sys.argv[2])
        result = quick_update(sid)
        print(f"\n结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
    else:
        domain = sys.argv[1] if len(sys.argv) > 1 else ""
        result = process_all(domain=domain)
