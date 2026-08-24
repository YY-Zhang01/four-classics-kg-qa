"""三元组抽取（P2）：给大模型一段原文 + Schema，吐出三元组 JSON 并校验。

流程：读 chunks → 分批送 LLM 抽取 → 校验白名单 → 去重 → 写入 JSON。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from config.settings import PROMPT_DIR, CHUNK_DIR
from llm.base import get_llm

KG_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = KG_DIR / "schema.json"
OUTPUT_PATH = KG_DIR / "triples.json"
PROMPT_PATH = KG_DIR / "extract_prompt.txt"

# 每批送多少块去抽取（控制上下文长度和成本）
BATCH_CHUNKS = 3


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _allowed_relations() -> set[str]:
    return set(_load_schema()["关系白名单"])


def _load_prompt_template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _build_prompt(text: str) -> str:
    """把原文填入提示词模板。"""
    template = _load_prompt_template()
    return template.replace("{text}", text)


def _parse_response(content: str) -> list[dict]:
    """从大模型返回中提取 JSON，容错处理。"""
    # 尝试直接解析
    try:
        data = json.loads(content)
        return data.get("triples", [])
    except json.JSONDecodeError:
        pass

    # 尝试提取 JSON 块
    m = re.search(r"\{[\s\S]*\"triples\"[\s\S]*\}", content)
    if m:
        try:
            return json.loads(m.group()).get("triples", [])
        except json.JSONDecodeError:
            pass

    return []


def _validate_triples(triples: list[dict], allowed: set[str]) -> list[dict]:
    """校验：关系必须在白名单内，必填字段不能空。P0: 保留 confidence。"""
    valid = []
    for t in triples:
        rel = (t.get("relation") or "").strip()
        subj = (t.get("subject") or "").strip()
        obj = (t.get("object") or "").strip()
        if not rel or not subj or not obj:
            continue
        if rel not in allowed:
            continue
        valid.append({
            "subject": subj, "relation": rel, "object": obj,
            "confidence": t.get("confidence", 0.0),
        })
    return valid


def _deduplicate(triples: list[dict]) -> list[dict]:
    """去重：按 (subject, relation, object) 三元去重，保持顺序。"""
    seen = set()
    unique = []
    for t in triples:
        key = (t["subject"], t["relation"], t["object"])
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique


def extract_from_chunks(chunks: list[dict], limit: int = 0) -> list[dict]:
    """对一批知识块抽取三元组。

    limit > 0 时只处理前 N 块（调试用）。
    """
    if limit > 0:
        chunks = chunks[:limit]

    llm = get_llm()
    allowed = _allowed_relations()
    all_triples: list[dict] = []
    total = len(chunks)

    for i in range(0, total, BATCH_CHUNKS):
        batch = chunks[i : i + BATCH_CHUNKS]
        # 收集这批 chunk 的 id，用于溯源
        batch_ids = [c.get("id", f"unk#{j}") for j, c in enumerate(batch)]
        combined = "\n\n---\n\n".join(c["text"] for c in batch)
        prompt = _build_prompt(combined)
        messages = [{"role": "user", "content": prompt}]

        try:
            answer = llm.chat(messages)
        except Exception as e:
            print(f"  块 {i + 1}-{min(i + BATCH_CHUNKS, total)} 抽取失败：{e}")
            continue

        triples = _parse_response(answer)
        valid = _validate_triples(triples, allowed)
        # P0: 每条三元组标注来源 chunk_id（用这批的第一个 chunk 作为代表）
        for t in valid:
            t["source_chunk_id"] = batch_ids[0]
            t["extract_method"] = "llm"
        all_triples.extend(valid)
        print(f"  块 {i + 1}-{min(i + BATCH_CHUNKS, total)}/{total}  抽到 {len(triples)} 条，有效 {len(valid)} 条",
              flush=True)

    all_triples = _deduplicate(all_triples)
    print(f"\n总计：{len(all_triples)} 条有效三元组（去重后）")
    return all_triples


def main(limit: int = 0) -> None:
    """入口：读 chunks → 抽取 → 校验 → 写入 triples.json。"""
    # 读 chunks
    chunks: list[dict] = []
    for f in sorted(CHUNK_DIR.glob("*.json")):
        chunks.extend(json.loads(f.read_text(encoding="utf-8")))

    if not chunks:
        print("没有知识块，先做切块。")
        return

    print(f"待处理知识块：{len(chunks)}")
    triples = extract_from_chunks(chunks, limit=limit)

    # 写入
    OUTPUT_PATH.write_text(
        json.dumps(triples, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"结果已写入 {OUTPUT_PATH}")


if __name__ == "__main__":
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    main(limit=limit)
