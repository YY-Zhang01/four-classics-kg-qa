"""生成评测：衡量 LLM 回答质量。

用另一个模型（或同一模型的不同 prompt）给回答打分，维度：
- 准确性：回答是否与参考资料一致
- 完整性：是否覆盖了关键信息点
- 引用率：是否标注出处
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from llm.base import get_llm
from core.ask import answer_stream
from retrieval.retriever import search

_EVAL_PROMPT = """你是红楼梦评测专家。请对以下问答进行评分。

【问题】{question}

【系统回答】
{answer}

【评分标准】
1. 准确性 (0-5)：回答是否基于资料、不编造？有事实错误扣分。
2. 完整性 (0-5)：是否覆盖了问题的关键信息点？
3. 引用率 (0-5)：是否标注了出处？

请按以下 JSON 格式输出（只输出 JSON，不要其他文字）：
{{"accuracy": 整数, "completeness": 整数, "citation": 整数, "notes": "简要说明"}}"""


def evaluate_answer(question: str, answer: str, max_retries: int = 2) -> dict:
    """用 LLM 给单个回答打分。"""
    prompt = _EVAL_PROMPT.format(question=question, answer=answer[:2000])
    llm = get_llm()

    for attempt in range(max_retries):
        try:
            raw = llm.chat([{"role": "user", "content": prompt}])
            # 尝试提取 JSON
            import re
            m = re.search(r"\{.*?\}", raw, re.DOTALL)
            if m:
                scores = json.loads(m.group())
                scores["accuracy"] = int(scores.get("accuracy", 0))
                scores["completeness"] = int(scores.get("completeness", 0))
                scores["citation"] = int(scores.get("citation", 0))
                scores["notes"] = str(scores.get("notes", ""))
                return scores
        except Exception:
            time.sleep(1)
    return {"accuracy": 0, "completeness": 0, "citation": 0, "notes": "评估失败"}


def load_dataset() -> list[dict]:
    path = Path(__file__).resolve().parent / "qa_dataset.json"
    return json.loads(path.read_text(encoding="utf-8"))


def run_gen_eval(limit: int = 10):
    items = load_dataset()[:limit]
    llm = get_llm()
    total = {"accuracy": 0, "completeness": 0, "citation": 0}
    count = 0

    print(f"生成评测：{len(items)} 题（抽样前 {limit} 条）\n")
    print(f"{'ID':<12} {'准确':>4} {'完整':>4} {'引用':>4} {'综合':>4}  问题")
    print("-" * 80)

    for item in items:
        q = item["question"]
        # 检索 + 生成
        hits = search(q, top_k=5)
        parts = list(answer_stream(q, hits))
        answer = "".join(parts)

        # 评估
        scores = evaluate_answer(q, answer)
        acc = scores["accuracy"]
        com = scores["completeness"]
        cit = scores["citation"]
        avg = (acc + com + cit) / 3

        total["accuracy"] += acc
        total["completeness"] += com
        total["citation"] += cit
        count += 1

        print(f"{item['id']:<12} {acc:>4}  {com:>4}  {cit:>4}  {avg:>4.1f}  {q}")

    print("-" * 80)
    n = max(count, 1)
    print(f"\n{'='*50}")
    print(f"  生成评测报告")
    print(f"{'='*50}")
    print(f"  评测题目数:  {count}")
    print(f"  准确性均分:  {total['accuracy'] / n:.1f} / 5")
    print(f"  完整性均分:  {total['completeness'] / n:.1f} / 5")
    print(f"  引用率均分:  {total['citation'] / n:.1f} / 5")
    print(f"  综合均分:    {(total['accuracy'] + total['completeness'] + total['citation']) / (n * 3):.1f} / 5")
    print(f"{'='*50}")


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    run_gen_eval(limit)
