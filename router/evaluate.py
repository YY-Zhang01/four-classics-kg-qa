"""路由效果评测脚本（P2）。

用法：python -m router.evaluate

用一组标注了预期类型的测试用例，分别跑规则通道和 LLM 通道，
统计分类准确率、各类型 F1 等指标。

测试用例覆盖四大名著常见问法，也包含政务场景的示例问题。
"""
from __future__ import annotations

import sys
from router.classifier import classify, classify_rule, classify_llm, RouteResult

# ── 测试用例：问题 → 预期类型 ──────────────────────────
# 名著场景
TEST_CASES: list[tuple[str, str]] = [
    # === FACT（查事实）===
    ("林黛玉是什么性格", "FACT"),
    ("贾宝玉是什么身份", "FACT"),
    ("大观园里有哪些景点", "FACT"),
    ("林黛玉在第几回出场", "FACT"),
    ("贾府有哪些人", "FACT"),
    ("什么叫木石前盟", "FACT"),
    ("王熙凤的特点是什么", "FACT"),
    ("贾宝玉的出身是什么", "FACT"),
    ("金陵十二钗是谁", "FACT"),
    ("孙悟空是什么来历", "FACT"),

    # === RELATION（查关系）===
    ("林黛玉和薛宝钗是什么关系", "RELATION"),
    ("贾宝玉的母亲是谁", "RELATION"),
    ("谁和贾宝玉有亲戚关系", "RELATION"),
    ("林黛玉的父亲是谁", "RELATION"),
    ("贾母和贾宝玉的关系", "RELATION"),
    ("林黛玉和贾宝玉的关系", "RELATION"),
    ("王熙凤是谁的夫人", "RELATION"),
    ("探春和贾宝玉的关系", "RELATION"),
    ("需要哪些材料", "RELATION"),
    ("申请需要什么证件", "RELATION"),

    # === COMPARE（查对比）===
    ("林黛玉和薛宝钗性格有什么不同", "COMPARE"),
    ("林黛玉和王熙凤有什么区别", "COMPARE"),
    ("贾宝玉和甄宝玉有什么不同", "COMPARE"),
    ("林黛玉和薛宝钗谁更美", "COMPARE"),
    ("请对比林黛玉和薛宝钗", "COMPARE"),
    ("孙悟空和猪八戒谁更厉害", "COMPARE"),
    ("新旧版本有什么区别", "COMPARE"),

    # === PROCEDURE（查流程）===
    ("怎么办理食品经营许可证", "PROCEDURE"),
    ("申请流程是什么", "PROCEDURE"),
    ("如何申请", "PROCEDURE"),
    ("大观园怎么走", "PROCEDURE"),
    ("怎么操作", "PROCEDURE"),
    ("办理步骤是什么", "PROCEDURE"),
    ("第一步怎么做", "PROCEDURE"),

    # === LATEST（查最新）===
    ("最近有什么变化", "LATEST"),
    ("最新版本是什么", "LATEST"),
    ("有什么更新吗", "LATEST"),
    ("最近新增了什么", "LATEST"),
    ("最新政策是什么", "LATEST"),
]


def evaluate_rule() -> dict:
    """只评测规则通道。"""
    total = len(TEST_CASES)
    correct = 0
    errors: list[dict] = []

    for query, expected in TEST_CASES:
        result = classify_rule(query)
        predicted = result.question_type if result else "UNKNOWN"
        if predicted == expected:
            correct += 1
        else:
            errors.append({
                "query": query,
                "expected": expected,
                "predicted": predicted,
                "reason": result.reason if result else "规则未匹配",
            })

    return {
        "method": "rule",
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total * 100, 1),
        "errors": errors,
    }


def evaluate_all(force_llm: bool = False) -> dict:
    """评测完整分类器（规则 + LLM 回退）。

    Args:
        force_llm: True 时跳过规则，强制全部走 LLM（评测 LLM 独立准确率）
    """
    total = len(TEST_CASES)
    correct = 0
    rule_hits = 0
    llm_hits = 0
    errors: list[dict] = []
    confusion: dict[str, dict[str, int]] = {}  # confusion[expected][predicted] = count

    for query, expected in TEST_CASES:
        result = classify(query, force_llm=force_llm)
        predicted = result.question_type

        # 初始化混淆矩阵
        if expected not in confusion:
            confusion[expected] = {}
        confusion[expected][predicted] = confusion[expected].get(predicted, 0) + 1

        if predicted == expected:
            correct += 1
            if result.method == "rule":
                rule_hits += 1
            else:
                llm_hits += 1
        else:
            errors.append({
                "query": query,
                "expected": expected,
                "predicted": predicted,
                "method": result.method,
                "confidence": result.confidence,
                "reason": result.reason,
            })

    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total * 100, 1),
        "rule_hits": rule_hits,
        "llm_hits": llm_hits,
        "errors": errors,
        "confusion": confusion,
    }


def print_report(results: dict) -> None:
    """格式化打印评测报告。"""
    print("\n" + "=" * 60)
    print("  P2 路由评测报告")
    print("=" * 60)
    print(f"  总用例数：{results['total']}")
    print(f"  正确数：  {results['correct']}")
    print(f"  准确率：  {results['accuracy']}%")
    if "rule_hits" in results:
        print(f"  规则命中：{results['rule_hits']}")
        print(f"  LLM 命中：{results['llm_hits']}")
    print("-" * 60)

    if results["errors"]:
        print(f"\n  错误用例（{len(results['errors'])} 条）：")
        for e in results["errors"]:
            print(f"    X [{e['expected']}->{e['predicted']}] {e['query']}")
            if e.get("reason"):
                print(f"      原因：{e['reason']}")
    else:
        print("\n  [OK] 全部正确！")

    # 混淆矩阵
    if "confusion" in results and results["confusion"]:
        print("\n  混淆矩阵（预期 → 预测）：")
        types = sorted(set(
            list(results["confusion"].keys()) +
            [p for row in results["confusion"].values() for p in row]
        ))
        header = "        " + "  ".join(f"{t:>8}" for t in types)
        print(header)
        for expected in types:
            row_counts = results["confusion"].get(expected, {})
            cells = "  ".join(f"{row_counts.get(pred, 0):>8}" for pred in types)
            print(f"  {expected:>6}  {cells}")

    print("=" * 60 + "\n")


def main():
    """运行评测。"""
    force_llm = "--llm" in sys.argv

    if force_llm:
        print("\n[模式] 强制 LLM 通道（跳过规则）")
    else:
        print("\n[模式] 规则优先 + LLM 回退")
        # 先单独评测规则通道
        rule_results = evaluate_rule()
        print("\n--- 规则通道独立评测 ---")
        print_report(rule_results)

    all_results = evaluate_all(force_llm=force_llm)
    print("\n--- 完整路由评测 ---")
    print_report(all_results)


if __name__ == "__main__":
    main()
