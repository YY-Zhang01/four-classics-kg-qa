"""RAG 评测脚本

零外部依赖：关键词命中率 + LLM-as-Judge 裁判打分。
用法：python -m eval.run_eval          # 跑全部 12 题
      python -m eval.run_eval --fast   # 快速版：只测检索，不调 LLM 裁判
"""
from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from pathlib import Path

from retrieval.retriever import search
from core.ask import answer_stream

HERE = Path(__file__).resolve().parent
TEST_SET_PATH = HERE / "test_set.json"
REPORT_PATH = HERE / "eval_report.json"


def load_test_set() -> list[dict]:
    return json.loads(TEST_SET_PATH.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════
#  检索评测
# ═══════════════════════════════════════════════════════════

def _hit_text(h: dict) -> str:
    """把 hit 变成可搜索的文本。kg_fact 用三元拼接，向量块用原文。"""
    if h.get("type") == "kg_fact":
        return f"{h.get('subject', '')} {h.get('relation', '')} {h.get('object', '')}"
    return h.get("text", "")


def eval_retrieval(keywords: list[str], hits: list[dict]) -> dict:
    """检索命中率 + MRR：预期关键词是否在召回块中出现。"""
    if not keywords or not hits:
        return {"hit": False, "rank": -1, "matching_kw": []}

    matched = []
    for rank, h in enumerate(hits, 1):
        txt = _hit_text(h)
        for kw in keywords:
            if kw in txt and kw not in matched:
                matched.append(kw)
        if len(matched) >= len(keywords):
            break

    # 找第一个命中关键词的 rank
    first_rank = -1
    for rank, h in enumerate(hits, 1):
        txt = _hit_text(h)
        if any(kw in txt for kw in keywords):
            first_rank = rank
            break

    return {
        "hit": len(matched) > 0,
        "hit_count": len(matched),
        "total_kw": len(keywords),
        "rank": first_rank,
    }


# ═══════════════════════════════════════════════════════════
#  LLM 裁判
# ═══════════════════════════════════════════════════════════

JUDGE_SYSTEM = (
    "你是一个严格的评测裁判。请根据以下标准给回答打分（只回复一个 1-5 的数字）：\n"
    "5 = 完全正确，关键信息齐全\n"
    "4 = 基本正确，略有遗漏\n"
    "3 = 部分正确，有重要遗漏\n"
    "2 = 大部分错误\n"
    "1 = 完全错误或不相关"
)


def eval_judge(question: str, golden: str, answer: str, keywords: list[str]) -> int:
    """让 LLM 做裁判，给回答打分 1-5。"""
    from llm.base import get_llm

    llm = get_llm()
    prompt = (
        f"问题：{question}\n"
        f"期望答案（参考）：{golden}\n"
        f"实际回答：{answer}\n"
        f"关键信息应包含：{'、'.join(keywords) if keywords else '（无）'}\n\n"
        "请打分（1-5）："
    )
    try:
        result = llm.chat([
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": prompt},
        ])
        m = re.search(r"[1-5]", result)
        return int(m.group()) if m else 3
    except Exception:
        return 3


# ═══════════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════════

def run(fast: bool = False) -> tuple[list[dict], dict]:
    test_cases = load_test_set()
    n = len(test_cases)
    print(f"评测集：{n} 题  {'（快速模式，跳过 LLM 裁判）' if fast else ''}\n")

    results: list[dict] = []
    by_cat: dict[str, list[dict]] = defaultdict(list)
    total_ret_time = 0.0
    total_gen_time = 0.0

    for i, tc in enumerate(test_cases, 1):
        q = tc["question"]
        kw = tc.get("keywords", [])
        golden = tc.get("golden_answer", "")
        cat = tc.get("category", "其他")

        # ── 检索 ──
        t0 = time.perf_counter()
        hits = search(q)
        ret_time = time.perf_counter() - t0

        # ── 生成 ──
        t1 = time.perf_counter()
        collected: list[str] = []
        try:
            for piece in answer_stream(q, hits):
                collected.append(piece)
        except Exception:
            collected.append("[生成失败]")
        answer = "".join(collected)
        gen_time = time.perf_counter() - t1

        # ── 检索评测 ──
        ret_eval = eval_retrieval(kw, hits)

        # ── 关键词命中（字符串匹配） ──
        kw_all = all(k in answer for k in kw) if kw else None

        # ── LLM 裁判 ──
        judge_score = eval_judge(q, golden, answer, kw) if not fast else 0

        # ── 记录 ──
        r = {
            "id": tc["id"],
            "question": q,
            "golden": golden,
            "answer": answer[:300],
            "category": cat,
            "retrieval_hit": ret_eval["hit"],
            "retrieval_hit_kw": f"{ret_eval['hit_count']}/{ret_eval['total_kw']}",
            "retrieval_rank": ret_eval["rank"],
            "retrieval_time": round(ret_time, 3),
            "generation_time": round(gen_time, 3),
            "keyword_in_answer": kw_all,
            "judge_score": judge_score,
            "hit_count": len(hits),
        }
        results.append(r)
        by_cat[cat].append(r)
        total_ret_time += ret_time
        total_gen_time += gen_time

        # 终端状态
        icon = "✓" if ret_eval["hit"] and judge_score >= 4 else ("△" if ret_eval["hit"] or judge_score >= 3 else "✗")
        kw_status = f"关键词{ret_eval['hit_count']}/{ret_eval['total_kw']}命中"
        print(f"[{i:2d}/{n}] {icon} {q}")
        print(f"     检索{kw_status}  |  裁判{judge_score}分  |  {ret_time+gen_time:.1f}s\n")

    # ═══════════ 汇总报告 ═══════════
    total = len(results)
    hit = sum(1 for r in results if r["retrieval_hit"])
    mrr = sum(1.0 / r["retrieval_rank"] for r in results if r["retrieval_rank"] > 0) / total
    avg_judge = sum(r["judge_score"] for r in results) / total if not fast else 0
    avg_kw = sum(
        int(r["retrieval_hit_kw"].split("/")[0]) / max(int(r["retrieval_hit_kw"].split("/")[1]), 1)
        for r in results
    ) / total
    avg_ret = total_ret_time / total
    avg_gen = total_gen_time / total

    print("=" * 56)
    print("  评测报告")
    print("=" * 56)
    print(f"  题目数             {total}")
    print(f"  检索命中率          {hit}/{total} = {hit/total*100:.1f}%")
    print(f"  关键词覆盖          {avg_kw*100:.0f}%")
    print(f"  MRR                {mrr:.3f}")
    if not fast:
        print(f"  裁判均分            {avg_judge:.1f}/5")
    print(f"  平均检索耗时        {avg_ret:.2f}s")
    print(f"  平均生成耗时        {avg_gen:.2f}s")
    print(f"  总耗时              {total_ret_time+total_gen_time:.1f}s")
    print(f"\n  ── 按类别 ──")
    for cat, items in sorted(by_cat.items()):
        c_n = len(items)
        c_hit = sum(1 for r in items if r["retrieval_hit"])
        c_judge = sum(r["judge_score"] for r in items) / c_n if not fast else 0
        print(f"  {cat:6s}  {c_hit}/{c_n} 命中  |  裁判均分 {c_judge:.1f}")

    # 保存报告
    report = {
        "test_date": time.strftime("%Y-%m-%d %H:%M"),
        "test_count": total,
        "fast_mode": fast,
        "stats": {
            "hit_rate": round(hit / total, 3),
            "keyword_coverage": round(avg_kw, 3),
            "mrr": round(mrr, 3),
            "avg_judge": round(avg_judge, 2),
            "avg_retrieval_time": round(avg_ret, 3),
            "avg_generation_time": round(avg_gen, 3),
        },
        "by_category": {
            cat: {
                "count": len(items),
                "hit_rate": sum(1 for r in items if r["retrieval_hit"]) / len(items),
                "avg_judge": round(sum(r["judge_score"] for r in items) / len(items), 2),
            }
            for cat, items in by_cat.items()
        },
        "details": results,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  详细报告 → eval/eval_report.json")

    return results, report


if __name__ == "__main__":
    import sys
    fast = "--fast" in sys.argv
    run(fast=fast)
