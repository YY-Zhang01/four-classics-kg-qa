"""SSE 安全编码工具：防止换行 / `data:` 前缀注入破坏事件帧。"""
from __future__ import annotations


def sse_text(text: str) -> str:
    """把一段文本安全编码为单个 SSE data 事件。

    换行会被转义为字面量 ``\\n``（前端再还原），从而：
    1. 事件帧永远是单行，杜绝 ``\\n\\n`` 提前结束事件、``data:`` 前缀注入伪事件；
    2. 保留回答中的换行，让 Markdown 正常分段渲染。
    """
    safe = (
        (text or "")
        .replace("\\", "\\\\")   # 先转义反斜杠，避免与 \n 转义混淆
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
    )
    return f"data: {safe}\n\n"
