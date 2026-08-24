"""受控生成：把检索到的块拼成上下文，喂给大模型，流式输出。

核心红线：检索为空就直接说“未找到”，不调用模型、不编造。
提示词从 prompts/ 读取，与代码分离，方便随时调而不动代码。
"""
from __future__ import annotations

from typing import Iterator

from config.settings import PROMPT_DIR, PROJECT_DOMAIN
from llm.base import get_llm

_SYSTEM_PROMPT_CACHE: str | None = None


def _system_prompt() -> str:
    """惰性读取系统提示词（避免导入期读文件，首次调用时加载并缓存）。"""
    global _SYSTEM_PROMPT_CACHE
    if _SYSTEM_PROMPT_CACHE is None:
        raw = (PROMPT_DIR / "qa_system_prompt.txt").read_text(encoding="utf-8")
        _SYSTEM_PROMPT_CACHE = raw.replace("{domain}", PROJECT_DOMAIN)
    return _SYSTEM_PROMPT_CACHE

NO_CONTEXT_ANSWER = "根据现有资料未找到相关内容。"


def build_context(chunks: list[dict]) -> str:
    """把召回的块拼成带编号和出处标签的参考资料。

    P0: 出处包含页码信息（如果有的话）。
    支持两种格式：
    - 普通知识块：{source, chapter, page_no, text}
    - KG 事实：{type:"kg_fact", subject, relation, object, confidence}
    """
    blocks = []
    for i, c in enumerate(chunks, 1):
        if c.get("type") == "kg_fact":
            # KG 结构化事实，带置信度
            conf = c.get("confidence", 0)
            conf_str = f" [置信度:{conf:.0%}]" if conf > 0 else ""
            blocks.append(
                f"[资料{i}｜知识图谱{conf_str}] {c['subject']} ——{c['relation']}→ {c['object']}"
            )
        elif c.get("type") == "wiki":
            # Wiki 百科页面摘要
            blocks.append(
                f"[资料{i}｜Wiki百科·{c.get('page_type','')}] {c.get('title','')}\n{c.get('text','')}"
            )
        else:
            # 原文块，带页码
            chapter = c.get("chapter", "")
            source = c.get("source", "")
            page = c.get("page_no")
            loc = f"出处：{source}·{chapter}"
            if page:
                loc += f"·第{page}页"
            text = c.get("text", "")
            blocks.append(f"[资料{i}｜{loc}]\n{text}")
    return "\n\n".join(blocks)


def build_messages(
    question: str,
    chunks: list[dict],
    history: list[dict] | None = None,
    max_history: int = 10,
) -> list[dict]:
    """构造喂给大模型的消息：系统规则 + 历史对话 + 参考资料 + 问题。

    history: [{role, content}, ...]，按时间顺序
    max_history: 最多保留最近多少轮消息（每轮含 user+assistant）
    """
    context = build_context(chunks)
    user_content = (
        f"【参考资料】\n{context}\n\n"
        f"【问题】{question}\n\n"
        f"请依据以上参考资料回答，并在结论后标注【出处：来源·章节】。"
    )
    messages: list[dict] = [{"role": "system", "content": _system_prompt()}]

    # 插入最近 N 轮历史（截断过长内容，每段最多 300 字）
    if history:
        recent = history[-max_history:]
        for h in recent:
            content = h.get("content", "")
            if isinstance(content, str) and len(content) > 300:
                content = content[:300] + "…"
            messages.append({"role": h.get("role", "user"), "content": content})

    messages.append({"role": "user", "content": user_content})
    return messages


def answer_stream(
    question: str,
    chunks: list[dict],
    history: list[dict] | None = None,
) -> Iterator[str]:
    """流式作答；检索为空则直接返回"未找到"，不碰大模型。"""
    if not chunks:
        yield NO_CONTEXT_ANSWER
        return
    messages = build_messages(question, chunks, history=history)
    llm = get_llm()
    yield from llm.chat_stream(messages)
