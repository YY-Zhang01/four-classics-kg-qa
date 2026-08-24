"""大模型接入层抽象：定义统一接口 + 工厂。

这一层是手册里的“模型可插拔”：上层业务只依赖 LLMClient 这个契约，
以后换模型、换供应商（本地部署 / 别的网关），只改这一层，业务代码一行不动。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator


class LLMClient(ABC):
    """所有大模型客户端的统一契约。"""

    @abstractmethod
    def chat(self, messages: list[dict]) -> str:
        """一次性返回完整回复。"""
        raise NotImplementedError

    @abstractmethod
    def chat_stream(self, messages: list[dict]) -> Iterator[str]:
        """流式返回，逐段 yield 文本增量。"""
        raise NotImplementedError


def get_llm() -> LLMClient:
    """工厂：按配置里的 provider 返回对应实现。

    以后要接本地模型 / 其它供应商，在这里加一个分支即可。
    """
    from config.settings import llm_config

    provider = llm_config.provider
    if provider == "gateway":
        from llm.gateway_client import GatewayLLM

        return GatewayLLM()
    raise ValueError(f"未知的 LLM_PROVIDER: {provider}（当前仅支持 'gateway'）")
