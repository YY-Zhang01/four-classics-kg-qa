"""embedding 生成层（P1）：把文本转成语义向量。

走 OpenAI 兼容的 /v1/embeddings 接口（本地 Ollama 的 bge-m3）。
和聊天大脑共用同一套接入方式，换模型只改 .env。
"""
from __future__ import annotations

import httpx

from config.settings import EMBED_API_KEY, EMBED_BASE_URL, EMBED_MODEL


def _endpoint() -> str:
    return f"{EMBED_BASE_URL.rstrip('/')}/embeddings"


def _headers() -> dict:
    # 本地 Ollama 不校验密钥，给个占位即可
    return {
        "Authorization": f"Bearer {EMBED_API_KEY or 'ollama'}",
        "Content-Type": "application/json",
    }


def embed_many(texts: list[str], timeout: float = 180.0) -> list[list[float]]:
    """一次给一批文本算向量，按输入顺序返回向量列表。"""
    if not texts:
        return []
    payload = {"model": EMBED_MODEL, "input": texts}
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(_endpoint(), json=payload, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
    # OpenAI 格式：data["data"] 是按 index 排列的列表，每项含 embedding
    items = sorted(data["data"], key=lambda x: x.get("index", 0))
    return [it["embedding"] for it in items]


def embed_one(text: str, timeout: float = 180.0) -> list[float]:
    """给单条文本算向量。"""
    return embed_many([text], timeout=timeout)[0]
