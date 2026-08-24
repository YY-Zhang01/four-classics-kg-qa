"""检索评测：Recall@K / MRR

衡量"检索能不能把正确答案排在前面"，不依赖 LLM 生成。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from retrieval.retriever import search, label as retriever_label
from kg.store import query_by_entity, count_triples
from retrieval.kg_search import _extract_entities


def load_dataset() -> list[dict]:
    path = Path(__file__).resolve().parent / "qa_dataset.json"
    return json.loads(path.read_text(encoding="utf-8"))


def score_kg_hit(question: str, expected: list[str] | None, k: int = 5) -> tuple[int, float]:
    """KG 检索命中评测。先提取实体名再查图谱。"""
    if expected is None:
        return 0, 0.0

    # 先从问题中提取人物名，再用实体名去查 KG
    entities = _extract_entities(question)
    if not entities:
        return 0, 0.0

    # 查所有提取到的实体，合并结果
    all_rows = []
    for ent in entities:
        rows = query_by_entity(ent) or []
        all_rows.extend(rows)

    if not all_rows:
        return 0, 0.0

    # 看答案里的人物名/关系名是否出现在 KG 三元组中
    got = set()
    for r in all_rows[:k]:
        got.add(r.get("object", ""))
        got.add(r.get("subject", ""))
        got.add(r.get("relation", ""))

    hits = sum(1 for e in expected if e in got)

    # MRR: 看第一个期望答案出现在第几位
    rr = 0.0
    for rank, r in enumerate(all_rows[:k], 1):
        fields = {r.get("object", ""), r.get("subject", ""), r.get("relation", "")}
        if any(e in fields for e in expected):
            rr = 1.0 / rank
            break

    return hits, rr


def score_chunk_hit(question: str, keywords: list[str] | None, k: int = 5) -> tuple[int, float]:
    """向量检索命中评测。"""
    if keywords is None:
        return 0, 0.0

    hits = search(question, top_k=k)
    if not hits:
        return 0, 0.0

    # 合并所有命中块的文本
    all_text = " ".join(h.get("text", "") for h in hits[:k])

    matched = sum(1 for kw in keywords if kw in all_text)

    rr = 0.0
    for rank, h in enumerate(hits[:k], 1):
        text = h.get("text", "")
        if any(kw in text for kw in keywords):
            rr = 1.0 / rank
            break

    return matched, rr


def run_eval(k: int = 5):
    items = load_dataset()
    print(f"评测数据集：{len(items)} 题  |  检索方式：{retriever_label()}  |  知识库：{count_triples()} 三元组\n")
    print(f"{'ID':<12} {'类型':<8} {'KG命中':<8} {'KG_MRR':<8} {'块命中':<8} {'块_MRR':<8} 问题")
    print("-" * 90)

    total_kg_hits = 0
    total_chunk_hits = 0
    total_kg_rr = 0.0
    total_chunk_rr = 0.0
    kg_count = 0
    chunk_count = 0

    for item in items:
        qid = item["id"]
        qtype = item["type"]
        question = item["question"]
        kg_ans = item.get("kg_answers")
        chunk_kw = item.get("chunks_should_contain")

        # KG 评测
        kh, krr = 0, 0.0
        if kg_ans:
            kh, krr = score_kg_hit(question, kg_ans, k)
            total_kg_hits += kh
            total_kg_rr += krr
            kg_count += 1

        # 块评测
        ch, crr = 0, 0.0
        if chunk_kw:
            ch, crr = score_chunk_hit(question, chunk_kw, k)
            total_chunk_hits += ch
            total_chunk_rr += crr
            chunk_count += 1

        print(f"{qid:<12} {qtype:<8} {kh}/{len(kg_ans or [])}  {krr:.3f}   {ch}/{len(chunk_kw or [])}  {crr:.3f}   {question}")

    print("-" * 90)
    print(f"\n{'='*50}")
    print(f"  检索评测报告")
    print(f"{'='*50}")
    if kg_count:
        print(f"  KG 检索:")
        print(f"    总命中数:    {total_kg_hits}")
        print(f"    Recall@{k}:   {total_kg_hits / sum(len(d.get('kg_answers',[]) or []) for d in items):.1%}")
        print(f"    MRR:          {total_kg_rr / kg_count:.3f}")
    if chunk_count:
        print(f"  向量检索:")
        print(f"    总命中数:    {total_chunk_hits}")
        total_kw = sum(len(d.get("chunks_should_contain", []) or []) for d in items)
        print(f"    Recall@{k}:   {total_chunk_hits / max(total_kw, 1):.1%}")
        print(f"    MRR:          {total_chunk_rr / max(chunk_count, 1):.3f}")
    print(f"{'='*50}")


if __name__ == "__main__":
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    run_eval(k)
