"""Agent 主循环：ReAct 模式，LLM 自主决策调用工具。

流程：
  用户问题 → LLM 分析 → 决定调工具(或直接回答) → 执行工具 → 
  结果塞回 → LLM 再分析 → 可能再调 → 最终生成答案

不依赖 OpenAI function-calling 协议，走纯文本解析，适配任意 OpenAI 兼容接口。
"""
from __future__ import annotations

import json
import re
from typing import Iterator

from llm.base import get_llm
from agent.tools import get_registry

_MAX_ITERATIONS = 5  # 最多调 5 次工具，防止死循环

def _build_system_prompt() -> str:
    """动态生成系统提示词（根据当前激活的书籍领域和注册的工具）。"""
    from config.settings import get_active_domain
    domain = get_active_domain()
    registry = get_registry()
    tool_defs = registry.list_definitions()

    # 构建工具列表
    tool_lines = []
    for i, t in enumerate(tool_defs, 1):
        name = t.get("function", {}).get("name", f"tool_{i}")
        desc = t.get("function", {}).get("description", "")
        params = t.get("function", {}).get("parameters", {}).get("properties", {})
        param_names = list(params.keys()) if params else []
        params_str = ", ".join(param_names) if param_names else ""
        tool_lines.append(f"{i}. {name}({params_str}) — {desc}")

    tool_list = "\n".join(tool_lines) if tool_lines else "1. search_knowledge(query) — 搜索原文语料库"

    # 工具选择指南
    tool_guide = """- 问人物简介、身份、性格等事实 → 优先用 query_wiki（百科卡片）
- 问人物关系、归属 → 优先用 query_graph（知识图谱）
- 问情节、典故、诗词等原文 → 用 search_knowledge（原文检索）
- 问两个人物的异同、对比 → 用 compare_entities（实体对比）"""

    return f"""你是《{domain}》知识助手。你可以调用工具来检索信息。

## 可用工具

{tool_list}

## 工具选择指南
{tool_guide}

## 工作流程

收到问题后，按以下格式回复：

- 如需查资料，输出：
  TOOL: 工具名
  ARGS: {{"参数名": "参数值"}}

- 如信息足够直接回答，输出：
  FINAL: 你的回答（必须基于已查到的资料，不要编造）

## 规则

- 每次只调一个工具，最多调 5 次
- 所有回答必须引用工具返回的信息
- 回答末尾标注出处
- 资料不足时说'现有资料未找到相关信息'
- 使用 Markdown 格式组织回答，让层次清晰"""


def _parse_tool_call(text: str) -> tuple[str | None, dict | None]:
    """从 LLM 输出中提取工具调用。返回 (工具名, 参数字典) 或 (None, None)。"""
    tool_match = re.search(r"TOOL:\s*(\w+)", text)
    args_match = re.search(r"ARGS:\s*(\{.*?\})", text, re.DOTALL)
    if tool_match and args_match:
        try:
            args = json.loads(args_match.group(1))
        except json.JSONDecodeError:
            return None, None
        return tool_match.group(1), args
    return None, None


def _is_final(text: str) -> str | None:
    """检测是否为最终回答。返回回答文本或 None。"""
    m = re.search(r"FINAL:\s*(.+)", text, re.DOTALL)
    return m.group(1).strip() if m else None


def agent_ask(question: str, history: list[dict] | None = None) -> Iterator[str]:
    """Agent 问答（生成器，yield 事件）。"""
    registry = get_registry()
    llm = get_llm()

    # 构建消息
    messages = [{"role": "system", "content": _build_system_prompt()}]
    if history:
        messages += history
    messages.append({"role": "user", "content": question})

    tool_results: list[str] = []

    for iteration in range(_MAX_ITERATIONS):
        # LLM 思考
        raw = llm.chat(messages)

        # 检查是否是最终回答
        final = _is_final(raw)
        if final:
            yield f"data: {final}\n\n"
            return

        # 检查是否是工具调用
        tool_name, args = _parse_tool_call(raw)
        if tool_name is None:
            # 既不是 FINAL 也不是 TOOL，就当作最终回答
            yield f"data: {raw}\n\n"
            return

        # 执行工具
        tool = registry.get(tool_name)
        if tool is None:
            result = f"未知工具：{tool_name}"
        else:
            try:
                result = tool.execute(**args)
            except Exception as e:
                result = f"工具执行失败：{e}"

        tool_results.append(f"[{tool_name}] {result[:200]}")
        yield f"data: [调用工具 {tool_name}]\n\n"

        # 把工具结果塞回对话
        messages.append({"role": "assistant", "content": raw})
        messages.append({
            "role": "user",
            "content": f"工具 {tool_name} 返回结果：\n{result}\n\n请根据以上信息继续回答。如果信息充足，请输出 FINAL: ..."
        })

    # 超限，强行生成
    yield f"data: （达到最大查询次数，基于已有信息回答）\n\n"
    final = llm.chat(messages + [{
        "role": "user",
        "content": "请基于以上所有信息，直接输出 FINAL: 最终回答。不要调用工具。"
    }])
    yield f"data: {final}\n\n"


def agent_ask_stream(question: str, history: list[dict] | None = None) -> Iterator[str]:
    """Agent 问答（兼容 SSE 流式输出格式）。"""
    yield from agent_ask(question, history)
