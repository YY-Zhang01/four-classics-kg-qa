"""RAG 问答系统 · P2 命令行全链路：

三模检索 → 受控生成 → 流式回答 + 出处 + 审计日志。
"""
from __future__ import annotations

import json
from datetime import datetime

from config.settings import LOG_DIR, PROJECT_NAME
from core.ask import answer_stream
from retrieval.retriever import count, label, search


def _hit_label(h: dict) -> str:
    """把 hit 转成一行可读的出处标签。兼容 kg_fact 和向量块两种类型。"""
    if h.get("type") == "kg_fact":
        return f"KG:{h['subject']}→{h.get('relation','')}→{h['object']}"
    return f"{h.get('source','?')}·{h.get('chapter','?')}"


def log_audit(question: str, hits: list[dict], answer: str) -> None:
    """把每次问答写入审计日志，满足"可审计"红线。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "question": question,
        "hit_ids": [h.get("id", f"kg:{h.get('subject','')}-{h.get('object','')}") for h in hits],
        "hit_sources": [_hit_label(h) for h in hits],
        "answer": answer,
    }
    with (LOG_DIR / "qa_audit.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    print("=" * 48)
    print(f" {PROJECT_NAME} · P2（输入问题，exit 退出）")
    print("=" * 48)
    n = count()
    if n == 0:
        print("[!] 还没有知识块。若走向量检索，请先灌数据入库：")
        print("   python -m scripts.ingest_db")
        return
    print(f"已加载 {n} 个知识块（{label()}）。\n")
    while True:
        try:
            question = input("你问> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break
        if not question:
            continue
        if question.lower() in {"exit", "quit", "q"}:
            print("再见！")
            break

        hits = search(question)
        print("答> ", end="", flush=True)
        collected: list[str] = []
        for piece in answer_stream(question, hits):
            print(piece, end="", flush=True)
            collected.append(piece)
        answer = "".join(collected)
        print()
        if hits:
            srcs = "，".join(_hit_label(h) for h in hits)
            print(f"  （参考出处：{srcs}）")
        log_audit(question, hits, answer)
        print()


if __name__ == "__main__":
    main()
