"""检索策略配置（P2）：每种问题类型对应不同的检索路径和权重。

策略定义了三路召回的优先级和配额分配：
  kg      — 知识图谱（结构化关系）
  wiki    — Wiki 百科页面（结构化摘要）
  vector  — 向量检索（原文语义匹配）

每种策略的配额是一个元组 (kg_top_k, wiki_top_k, vector_top_k)，
表示该类型问题从各路召回的最大条数。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Strategy:
    """单条检索策略。"""
    name: str                       # 策略名称（调试用）
    kg_quota: int = 0               # KG 召回数
    wiki_quota: int = 0             # Wiki 召回数
    vector_quota: int = 3           # 向量召回数（兜底）
    sort_order: str = "kg_wiki_vector"  # 排序优先级
    description: str = ""           # 说明


# ── 策略定义 ────────────────────────────────────────────────

STRATEGIES: dict[str, Strategy] = {
    "FACT": Strategy(
        name="事实查询",
        kg_quota=0,
        wiki_quota=2,       # Wiki 优先：百科卡片直接回答"是什么"
        vector_quota=3,     # 向量兜底
        sort_order="wiki_vector",
        description="Wiki 百科优先，向量检索兜底。适合查定义、属性、出处。",
    ),
    "RELATION": Strategy(
        name="关系查询",
        kg_quota=5,         # KG 优先：结构化关系最精准
        wiki_quota=1,       # Wiki 补充上下文
        vector_quota=2,     # 向量兜底
        sort_order="kg_wiki_vector",
        description="知识图谱优先，Wiki 补充，向量兜底。适合查人物关系、归属、材料要求。",
    ),
    "COMPARE": Strategy(
        name="对比查询",
        kg_quota=3,         # KG 找各自属性
        wiki_quota=2,       # Wiki 对比卡片
        vector_quota=3,     # 向量找差异段落
        sort_order="wiki_kg_vector",
        description="Wiki+KG 双路对比，向量补充差异细节。适合查异同、对比、优劣。",
    ),
    "PROCEDURE": Strategy(
        name="流程查询",
        kg_quota=0,
        wiki_quota=2,       # Wiki 流程段落
        vector_quota=3,     # 原文步骤描述
        sort_order="wiki_vector",
        description="Wiki 流程段落优先，向量检索补全步骤。适合查办事流程、操作步骤。",
    ),
    "LATEST": Strategy(
        name="最新查询",
        kg_quota=0,
        wiki_quota=1,       # Wiki 可能记录了版本
        vector_quota=3,     # 向量找最新内容
        sort_order="vector_wiki",
        description="向量检索优先（找最新入库内容），Wiki 补充。适合查更新、变化、版本。",
    ),
}

# 默认策略（未分类时）
DEFAULT_STRATEGY = Strategy(
    name="默认策略",
    kg_quota=3,
    wiki_quota=2,
    vector_quota=3,
    sort_order="kg_wiki_vector",
    description="三路均衡召回。",
)


def get_strategy(question_type: str) -> Strategy:
    """根据问题类型返回对应的检索策略。"""
    return STRATEGIES.get(question_type, DEFAULT_STRATEGY)


# ── 策略对 Agent 工具的映射 ──────────────────────────────

# 每种问题类型推荐优先使用的 Agent 工具
RECOMMENDED_TOOLS: dict[str, list[str]] = {
    "FACT":      ["search_knowledge", "query_wiki"],
    "RELATION":  ["query_graph", "query_wiki"],
    "COMPARE":   ["query_wiki", "query_graph", "compare_entities"],
    "PROCEDURE": ["query_wiki", "search_knowledge"],
    "LATEST":    ["search_knowledge", "query_wiki"],
}

DEFAULT_TOOLS = ["search_knowledge", "query_graph", "query_wiki"]


def get_recommended_tools(question_type: str) -> list[str]:
    """返回该类型问题推荐的工具列表。"""
    return RECOMMENDED_TOOLS.get(question_type, DEFAULT_TOOLS)
