"""Agent 工具抽象：定义统一接口 + 注册表。

每个工具暴露三样东西：
- 描述：告诉 LLM "我能干什么"
- 输入 schema：告诉 LLM "怎么调用我"
- 执行方法：真正干活
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """单个工具的抽象契约。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """工具唯一标识，如 'search_knowledge'"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """功能说明，LLM 据此决定用不用。要写清楚适用场景。"""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict:
        """输入参数的 JSON Schema。"""
        ...

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """执行工具，返回文本结果（塞回给 LLM 的上下文）。"""
        ...

    def as_openai_function(self) -> dict:
        """转成 OpenAI function-calling 格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """工具注册表：注册 + 枚举 + 按名查找。"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def list_definitions(self) -> list[dict]:
        """返回所有工具的 OpenAI function 定义列表。"""
        return [t.as_openai_function() for t in self._tools.values()]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())
