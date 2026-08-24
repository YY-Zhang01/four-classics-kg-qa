"""知识图谱检索（P2）：从三元组表查询人物关系。

对上暴露 search(query) 接口，与向量/关键词检索保持同构。
"""
from __future__ import annotations

import re

from kg.store import query_by_entity, query_relation, count_triples

# 关系型问题的关键词模式
_RELATION_PATTERNS = [
    r"(谁|什么).*(关系|亲戚|亲属)",
    r"关系",  # 覆盖"宝黛关系""人物关系"等简短问法
    r"(是|叫).*(什么|谁).*(表妹|表姐|表哥|表弟|堂妹|堂姐|堂哥|堂弟|妹妹|姐姐|哥哥|弟弟|母亲|父亲|女儿|儿子|夫人|妻子|丈夫|丫鬟|主人)",
    r"(表妹|表姐|表哥|表弟|堂妹|堂姐|堂哥|堂弟)是谁",
    r"(.*)和(.*)什么关系",
    r"(.*)是(.*)的(什么|谁)",
    r"(.*)的(父亲|母亲|妻子|丈夫|丫鬟|主人|官职|出身)是",
    r"(.*)是什么(官|官职|职位)",
    r"(.*)和(.*).*(关系|亲戚)",  # "A和B的关系"
    r"(.*)与(.*).*(关系|亲戚)",  # "A与B的关系"
]


def is_relation_question(query: str) -> bool:
    """判断问题是否属于关系型（应该走 KG 检索）。"""
    for pat in _RELATION_PATTERNS:
        if re.search(pat, query):
            return True
    return False


def _extract_entities(query: str) -> list[str]:
    """从问题中简单提取可能的人物名。实体词典从 config/entities.json 加载。"""
    from config.settings import get_entities
    ent = get_entities()
    aliases = ent.get("aliases", {})
    short_names = ent.get("short_names", {})
    common_names = ent.get("common_names", [])

    found: list[str] = []

    # 先检查合称
    for alias, names in aliases.items():
        if alias in query:
            found.extend(names)

    # 再检查全名
    for n in common_names:
        if n in query and n not in found:
            found.append(n)

    # 最后检查简称（优先级低，避免重复）
    for short, full in short_names.items():
        if short in query and full not in found:
            found.append(full)

    # 只返回前 3 个，避免查询过于宽泛
    return found[:3]


_PRONOUN_PATTERN = re.compile(r"他|她|它|他们|其")


def rewrite_query(query: str, history: list[dict] | None) -> str:
    """多轮对话：把代词替换成上一轮提到的人名，让检索更精准。

    例：query="他是什么官"，上轮提到林如海 → "林如海 他是什么官"
    """
    if not history or not _PRONOUN_PATTERN.search(query):
        return query

    # 找最近一轮 assistant 回复中的人名
    names = []
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            # 用已有的实体提取逻辑找出人名
            names = _extract_entities(content)
            if names:
                break

    if names:
        # 用最后提到的实体（通常是回答的核心对象），而非第一个
        return f"{names[-1]} {query}"
    return query


def search(query: str, top_k: int = 5) -> list[dict]:
    """KG 检索入口：返回结构化事实列表，按与查询的相关度排序。

    每条事实格式：{type: "kg_fact", subject, relation, object}
    """
    entities = _extract_entities(query)

    results: list[dict] = []

    # 如果提到两个实体，直接查关系
    if len(entities) >= 2:
        rels = query_relation(entities[0], entities[1])
        for r in rels:
            results.append({"type": "kg_fact", **r})

    # 查每个实体的周边关系
    for ent in entities:
        rels = query_by_entity(ent)
        for r in rels:
            results.append({"type": "kg_fact", **r})

    # 去重
    seen = set()
    unique = []
    for r in results:
        key = (r["subject"], r["relation"], r["object"])
        if key not in seen:
            seen.add(key)
            unique.append(r)

    # 按相关度排序并赋分：实体命中为主（最可靠），关系匹配为辅
    def _calc_score(r):
        rel = r.get("relation", "")
        subj = r.get("subject", "")
        obj = r.get("object", "")
        s = 0.0
        # 实体命中：这是 KG 的绝对优势，权重最高
        matched = 0
        if subj in query:
            matched += 1
        if obj in query:
            matched += 1
        if matched == 2:
            s += 0.6
        elif matched == 1:
            s += 0.4
        # 关系词命中：加分但不喧宾夺主（关系词通常是"答案"不在问句中）
        if rel in query:
            s += 0.3
        elif any(ch in query for ch in rel) and len(rel) >= 2:
            s += 0.2
        return round(min(s, 1.0), 2)

    for r in unique:
        r["score"] = _calc_score(r)

    unique.sort(key=lambda r: r["score"], reverse=True)

    return unique[:top_k]


def count() -> int:
    """三元组总数（给上层显示用）。"""
    return count_triples()
