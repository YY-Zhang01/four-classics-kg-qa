"""Wiki 页面生成器（P1）：从 chunk 聚合 → LLM 生成结构化百科页面。

流程：
1. 加载某领域的所有 chunk
2. 按实体分组（人物/事件/地点）
3. 每批 chunk 送 LLM 生成 Wiki JSON
4. 校验后写入 wiki_pages 表
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from config.settings import get_active_domain
from llm.base import get_llm
from wiki.store import upsert_page, count_pages

WIKI_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = WIKI_DIR / "schema.json"
PROMPT_PATH = WIKI_DIR / "generate_prompt.txt"

# 每个实体最多拼多少字上下文（控制 LLM 输入长度）
MAX_CONTEXT_CHARS = 3000


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _load_prompt_template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _load_chunks(domain: str) -> list[dict]:
    """加载指定领域的 chunk（优先从 DB 读，回退到 JSON 文件）。"""
    from retrieval.db import get_conn
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, source, chapter, body, page_no "
            "FROM chunks WHERE source = %s ORDER BY id",
            (domain,),
        )
        rows = cur.fetchall()
    if rows:
        return [
            {"id": r[0], "source": r[1], "chapter": r[2], "text": r[3], "page_no": r[4]}
            for r in rows
        ]
    # 回退：读 JSON 文件
    from config.settings import CHUNK_DIR
    chunks = []
    domain_file = CHUNK_DIR / f"{domain}.json"
    if domain_file.exists():
        chunks = json.loads(domain_file.read_text(encoding="utf-8"))
    return chunks


def _group_chunks_by_entity(
    chunks: list[dict],
    entity_names: list[str],
) -> dict[str, list[dict]]:
    """把 chunk 按提到的实体名分组。每个 chunk 可能属于多个实体。"""
    groups: dict[str, list[dict]] = {name: [] for name in entity_names}
    for c in chunks:
        text = c.get("text", "")
        for name in entity_names:
            if name in text:
                groups[name].append(c)
    return groups


def _build_context(chunks: list[dict], max_chars: int = MAX_CONTEXT_CHARS) -> str:
    """把一组 chunk 拼成带编号的参考资料，控制总长度。"""
    blocks = []
    total = 0
    for i, c in enumerate(chunks, 1):
        text = c.get("text", "")
        chapter = c.get("chapter", "")
        header = f"[资料{i}｜{chapter}]\n"
        block = header + text
        if total + len(block) > max_chars:
            # 截断
            remaining = max_chars - total - len(header) - 20
            if remaining > 50:
                block = header + text[:remaining] + "…"
            else:
                break
        blocks.append(block)
        total += len(block)
    return "\n\n---\n\n".join(blocks)


def _build_sections_list(page_type: str) -> str:
    """从 schema 读取该页面类型的章节列表，格式化为 prompt 用的清单。"""
    schema = _load_schema()
    pt = schema["page_types"].get(page_type, {})
    sections = pt.get("sections", {})
    lines = []
    for name, desc in sections.items():
        lines.append(f"- **{name}**：{desc}")
    return "\n".join(lines)


def _parse_wiki_response(content: str) -> dict | None:
    """从 LLM 返回中提取 Wiki JSON。容错处理 markdown 代码块。"""
    # 去掉 markdown 代码块标记（```json 和 ```）
    cleaned = content.strip()
    cleaned = re.sub(r"```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"```", "", cleaned)
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
        if "title" in data and "sections" in data:
            return data
    except json.JSONDecodeError:
        pass

    # 尝试用正则提取 JSON 对象
    m = re.search(r"\{[\s\S]*\"title\"[\s\S]*\"sections\"[\s\S]*\}", content)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    return None


def generate_for_entity(
    entity_name: str,
    entity_chunks: list[dict],
    domain: str,
    page_type: str = "character",
) -> dict | None:
    """为单个实体生成 Wiki 页面。返回生成结果 dict 或 None。"""
    if not entity_chunks:
        return None

    schema = _load_schema()
    pt = schema["page_types"].get(page_type, {})
    page_type_label = pt.get("label", page_type)

    template = _load_prompt_template()
    prompt = template.format(
        domain=domain,
        page_type=page_type,
        page_type_label=page_type_label,
        sections_list=_build_sections_list(page_type),
        context=_build_context(entity_chunks),
    )

    llm = get_llm()
    try:
        raw = llm.chat([{"role": "user", "content": prompt}])
    except Exception as e:
        print(f"  [{entity_name}] LLM 调用失败：{e}")
        return None

    result = _parse_wiki_response(raw)
    if result is None:
        print(f"  [{entity_name}] JSON 解析失败，原始输出前 200 字：{raw[:200]}")
        return None

    # 确保 title 正确
    if not result.get("title"):
        result["title"] = entity_name

    return result


def generate_all(
    domain: str,
    page_type: str = "character",
    entities: list[str] | None = None,
    limit: int = 0,
    dry_run: bool = False,
) -> dict:
    """批量生成 Wiki 页面。

    Args:
        domain: 领域名，如 "红楼梦"
        page_type: 页面类型，如 "character"
        entities: 要生成的实体列表，不传则从 config/entities_{domain}.json 读取
        limit: 限制生成数量（0 = 全部）
        dry_run: 只预览不写入

    Returns:
        {total, success, failed, skipped}
    """
    schema = _load_schema()
    if page_type not in schema["page_types"]:
        return {"error": f"未知页面类型：{page_type}"}

    # 加载实体列表
    if entities is None:
        from config.settings import get_entities
        ent = get_entities(domain)
        entities = ent.get("common_names", [])
    if not entities:
        return {"error": f"未找到领域 '{domain}' 的实体列表"}

    if limit > 0:
        entities = entities[:limit]

    chunks = _load_chunks(domain)
    if not chunks:
        return {"error": f"领域 '{domain}' 没有知识块"}

    print(f"领域：{domain}  页面类型：{page_type}  实体数：{len(entities)}  知识块：{len(chunks)}")
    print(f"{'[DRY RUN] ' if dry_run else ''}开始生成...\n")

    # 按实体分组 chunk
    groups = _group_chunks_by_entity(chunks, entities)

    stats = {"total": len(entities), "success": 0, "failed": 0, "skipped": 0}

    for name in entities:
        entity_chunks = groups.get(name, [])
        if len(entity_chunks) < 2:
            print(f"  [{name}] 跳过（只有 {len(entity_chunks)} 个关联块）")
            stats["skipped"] += 1
            continue

        print(f"  [{name}] {len(entity_chunks)} 个关联块 ...", end=" ", flush=True)

        result = generate_for_entity(name, entity_chunks, domain, page_type)
        if result is None:
            stats["failed"] += 1
            print("失败")
            continue

        conf = result.get("confidence", 0)
        ent_list = result.get("entities", [name])

        if dry_run:
            print(f"OK (confidence={conf:.0%})")
            stats["success"] += 1
        else:
            try:
                pid = upsert_page(
                    page_type=page_type,
                    title=result["title"],
                    domain=domain,
                    content={"sections": result.get("sections", {})},
                    entities=ent_list,
                    confidence=conf,
                )
                print(f"OK (id={pid}, confidence={conf:.0%})")
                stats["success"] += 1
            except Exception as e:
                print(f"写入失败：{e}")
                stats["failed"] += 1

    print(f"\n完成：成功 {stats['success']}  /  失败 {stats['failed']}  /  跳过 {stats['skipped']}")
    return stats


if __name__ == "__main__":
    import sys

    domain = sys.argv[1] if len(sys.argv) > 1 else get_active_domain()
    page_type = sys.argv[2] if len(sys.argv) > 2 else "character"
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    dry_run = "--dry-run" in sys.argv

    generate_all(domain=domain, page_type=page_type, limit=limit, dry_run=dry_run)
