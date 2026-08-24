"""OpenAI 兼容接口客户端（/v1/chat/completions）。

只负责"怎么跟大模型说话"，不掺业务逻辑。换供应商时新增一个同类文件即可。"""
from __future__ import annotations

import json
from typing import Iterator

import httpx

from config.settings import llm_config
from llm.base import LLMClient


class GatewayLLM(LLMClient):
    def __init__(self) -> None:
        # 调用前先确认网关地址/模型/密钥都已就位
        llm_config.require()
        self.base_url = llm_config.base_url.rstrip("/")
        self.model = llm_config.model
        self.timeout = llm_config.timeout
        self.headers = {
            "Authorization": f"Bearer {llm_config.api_key}",
            "Content-Type": "application/json",
        }

    @property
    def _endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def chat(self, messages: list[dict]) -> str:
        payload = {"model": self.model, "messages": messages, "stream": False}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self._endpoint, headers=self.headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]

    def chat_stream(self, messages: list[dict]) -> Iterator[str]:
        payload = {"model": self.model, "messages": messages, "stream": True}
        with httpx.Client(timeout=self.timeout) as client:
            with client.stream("POST", self._endpoint, headers=self.headers, json=payload) as resp:
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
                    piece = choices[0].get("delta", {}).get("content")
                    if piece:
                        yield piece
