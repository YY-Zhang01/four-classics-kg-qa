"""一键评测：检索 + 生成，输出汇总报告"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.retrieval_eval import run_eval as run_retrieval_eval
from eval.gen_eval import run_gen_eval


def main():
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    gen_limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    print("=" * 60)
    print(f"  四大名著知识问答系统 · 评测报告")
    print(f"  时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    t0 = time.time()

    print(f"\n[1/2] 检索评测 (Recall@{k}, MRR)")
    print("-" * 40)
    run_retrieval_eval(k)

    print(f"\n[2/2] 生成评测（抽样 {gen_limit} 条）")
    print("-" * 40)
    run_gen_eval(gen_limit)

    elapsed = time.time() - t0
    print(f"\n总耗时：{elapsed:.0f} 秒")


if __name__ == "__main__":
    main()
