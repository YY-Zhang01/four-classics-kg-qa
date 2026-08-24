"""OpenAI 兼容接口客户端（/v1/chat/completions）。

只负责"怎么跟大模型说话"，不掺业务逻辑。换供应商时新增一个同类文件即可。"""
from __future__ import annotations

import json
from typing import Iterator

import httpx

from config.settings import llm_config
from llm.base import LLMClient

# 进程级共享连接池：复用连接、网络抖动自动重试，
# 避免每请求新建 Client 导致连接不释放、以及抖动直接失败。
_shared_client: httpx.Client | None = None


def _get_shared_client() -> httpx.Client:
    """懒加载一个进程级共享的 httpx.Client（连接复用 + 重试）。"""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.Client(
            timeout=llm_config.timeout,
            transport=httpx.HTTPTransport(retries=2),
        )
    return _shared_client


class GatewayLLM(LLMClient):
    def __init__(self) -> None:
        # 调用前先确认网关地址/模型/密钥都已就位
        llm_config.require()
        self.base_url = llm_config.base_url.rstrip("/")
        self.model = llm_config.model
        self.headers = {
            "Authorization": f"Bearer {llm_config.api_key}",
            "Content-Type": "application/json",
        }

    @property
    def _endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def chat(self, messages: list[dict]) -> str:
        payload = {"model": self.model, "messages": messages, "stream": False}
        resp = _get_shared_client().post(self._endpoint, headers=self.headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or [{}]
        message = (choices[0].get("message") or {}) if choices else {}
        return message.get("content", "")

    def chat_stream(self, messages: list[dict]) -> Iterator[str]:
        payload = {"model": self.model, "messages": messages, "stream": True}
        with _get_shared_client().stream("POST", self._endpoint, headers=self.headers, json=payload) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                # OpenAI 兼容协议每行形如：data: {...}
                if line.startswith("data:"):
                    line = line[len("data:"):].strip()
                if line == "[DONE]":
                    break
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or [{}]
                piece = (choices[0].get("delta") or {}).get("content")
                if piece:
                    yield piece
