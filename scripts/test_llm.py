"""连通性自测：不依赖知识块，直接问大模型一句，确认 LLM 配置通不通。

用法（在项目根，已激活 venv 且配好 .env）：
    python -m scripts.test_llm
"""
from __future__ import annotations

from llm.base import get_llm


def main() -> None:
    llm = get_llm()
    print("正在测试与大模型服务的连通性...")
    messages = [{"role": "user", "content": "用一句话自我介绍。"}]
    print("答：", end="", flush=True)
    for piece in llm.chat_stream(messages):
        print(piece, end="", flush=True)
    print("\n连通性测试完成 [OK]")


if __name__ == "__main__":
    main()
