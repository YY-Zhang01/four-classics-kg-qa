"""Agent 工具实现（P2 扩展）：检索、KG、Wiki、对比 四大工具。

新增工具只需：继承 Tool → 实现4个抽象方法 → 在 get_registry() 里注册。
"""
from __future__ import annotations

from agent.base import Tool, ToolRegistry
from retrieval.retriever import search as retriever_search
from kg.store import query_by_entity


# ── 全局注册表（单例延迟初始化）─────────────────────────
_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """获取工具注册表（首次调用时初始化）。"""
    global _registry
    if _registry is not None:
        return _registry
    _registry = ToolRegistry()
    _registry.register(SearchKnowledgeTool())
    _registry.register(QueryGraphTool())
    _registry.register(QueryWikiTool())
    _registry.register(CompareEntitiesTool())
    _registry.register(ExploreGraphTool())      # P3 新增
    return _registry


# ── 工具 1：知识库检索 ──────────────────────────────────

class SearchKnowledgeTool(Tool):
    """在原文语料库中检索相关段落。"""

    @property
    def name(self) -> str:
        return "search_knowledge"

    @property
    def description(self) -> str:
        return (
            "在当前书籍的原文语料库中搜索与问题相关的段落。"
            "适用场景：情节、人物分析、典故、诗词等需要查原文的问题。"
            "返回带出处的原文片段列表。"
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或问题，用最精炼的词组描述要查的内容，如 '黛玉葬花' '宝玉挨打 原因'",
                },
            },
            "required": ["query"],
        }

    def execute(self, query: str, **kwargs) -> str:
        hits = retriever_search(query, top_k=5)
        if not hits:
            return "未找到相关内容。"
        lines = [f"共 {len(hits)} 条结果："]
        for i, h in enumerate(hits, 1):
            src = h.get("source", "未知")
            ch = h.get("chapter", "")
            text = h.get("text", "")[:300]
            lines.append(f"[{i}] {src} · {ch}\n{text}\n")
        return "\n".join(lines)


# ── 工具 2：知识图谱查询 ────────────────────────────────

class QueryGraphTool(Tool):
    """查询知识图谱中的人物关系和属性。"""

    @property
    def name(self) -> str:
        return "query_graph"

    @property
    def description(self) -> str:
        return (
            "查询当前书籍的人物知识图谱。"
            "适用场景：人物关系（如'某人的母亲是谁''两人什么关系'）、"
            "人物属性（如'某人的身份是什么'）。"
            "返回三元组列表（主体-关系-客体）。"
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "description": "要查询的人物全名。一次只能查一个人物。",
                },
            },
            "required": ["entity"],
        }

    def execute(self, entity: str, **kwargs) -> str:
        rows = query_by_entity(entity)
        if not rows:
            return f"图谱中未找到'{entity}'的相关信息。"
        lines = [f"'{entity}'的图谱信息（{len(rows)} 条）："]
        for r in rows:
            lines.append(f"  {r['subject']} —{r['relation']}→ {r['object']}")
        return "\n".join(lines)


# ── 工具 3：Wiki 百科查询（P2 新增）─────────────────────

class QueryWikiTool(Tool):
    """查询 Wiki 百科页面，获取人物/事项的结构化介绍。"""

    @property
    def name(self) -> str:
        return "query_wiki"

    @property
    def description(self) -> str:
        return (
            "查询当前书籍的 Wiki 百科页面。"
            "适用场景：查人物简介、身份背景、经典情节等结构化介绍。"
            "返回百科卡片的文本摘要，包含简介、身份、关系、经典情节等板块。"
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "要查询的人物名或关键词，如 '林黛玉' '贾宝玉' '大观园'",
                },
            },
            "required": ["query"],
        }

    def execute(self, query: str, **kwargs) -> str:
        try:
            from wiki.query import search as wiki_search
            pages = wiki_search(query, top_k=2)
        except ImportError:
            return "Wiki 百科模块未启用。"

        if not pages:
            return f"Wiki 百科中未找到'{query}'的相关页面。"

        lines = [f"'{query}'的 Wiki 百科信息："]
        for p in pages:
            title = p.get("title", "未知")
            ptype = p.get("page_type", "")
            text = p.get("text", "")
            lines.append(f"\n## {title}（{ptype}）")
            lines.append(text[:500])
        return "\n".join(lines)


# ── 工具 4：实体对比（P2 新增）───────────────────────────

class CompareEntitiesTool(Tool):
    """对比两个人物/实体，找出异同。"""

    @property
    def name(self) -> str:
        return "compare_entities"

    @property
    def description(self) -> str:
        return (
            "对比两个人物或实体的异同。"
            "适用场景：'A和B有什么不同''A和B谁更厉害'等对比类问题。"
            "会分别查询两个实体的 Wiki 页面和 KG 关系，汇总后返回。"
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "entity_a": {
                    "type": "string",
                    "description": "第一个实体名称",
                },
                "entity_b": {
                    "type": "string",
                    "description": "第二个实体名称",
                },
            },
            "required": ["entity_a", "entity_b"],
        }

    def execute(self, entity_a: str, entity_b: str, **kwargs) -> str:
        parts = [f"对比：{entity_a} vs {entity_b}\n"]

        # 1. 查 Wiki
        try:
            from wiki.query import search as wiki_search
            for ent in (entity_a, entity_b):
                pages = wiki_search(ent, top_k=1)
                if pages:
                    parts.append(f"【{ent}·Wiki】{pages[0].get('text', '')[:300]}")
                else:
                    parts.append(f"【{ent}·Wiki】未找到百科页面")
        except ImportError:
            parts.append("【Wiki】模块未启用")

        # 2. 查 KG 关系
        for ent in (entity_a, entity_b):
            rows = query_by_entity(ent)
            if rows:
                rels = [f"{r['subject']}—{r['relation']}→{r['object']}" for r in rows[:5]]
                parts.append(f"【{ent}·关系】" + "；".join(rels))
            else:
                parts.append(f"【{ent}·关系】图谱中未找到")

        return "\n".join(parts)


# ── 工具 5：图谱多跳探索（P3 新增）─────────────────────────

class ExploreGraphTool(Tool):
    """探索知识图谱中的多跳关系路径和邻居网络。"""

    @property
    def name(self) -> str:
        return "explore_graph"

    @property
    def description(self) -> str:
        return (
            "在知识图谱中探索实体之间的多跳关系路径和邻居网络。"
            "适用场景："
            "'A和B之间有什么关系'（查路径）、"
            "'和某人有关的所有人'（查邻居）、"
            "'A和B的共同点'（查共同邻居）。"
            "返回图谱路径或邻居列表。"
            "Neo4j 不可用时自动降级为 PG 单跳查询。"
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["path", "neighbors", "common"],
                    "description": "探索模式: path=两实体间路径, neighbors=某实体邻居网络, common=两实体共同邻居",
                },
                "entity_a": {
                    "type": "string",
                    "description": "第一个实体名（path/common 模式必填，neighbors 模式选填）",
                },
                "entity_b": {
                    "type": "string",
                    "description": "第二个实体名（path/common 模式必填）",
                },
                "entity": {
                    "type": "string",
                    "description": "中心实体名（neighbors 模式必填）",
                },
            },
            "required": ["mode"],
        }

    def execute(self, mode: str, entity_a: str = "", entity_b: str = "",
                entity: str = "", **kwargs) -> str:
        try:
            from retrieval.graph_search import find_paths, expand_neighbors, common_neighbors
        except ImportError:
            return "图谱探索模块未启用。"

        if mode == "path":
            if not entity_a or not entity_b:
                return "path 模式需要 entity_a 和 entity_b"
            paths = find_paths(entity_a, entity_b, max_depth=3)
            if not paths:
                return f"未找到 '{entity_a}' 到 '{entity_b}' 的关系路径。"
            lines = [f"'{entity_a}' 到 '{entity_b}' 的关系路径："]
            for i, p in enumerate(paths[:3], 1):
                segs = p.get("segments", [])
                chain = " → ".join(
                    f"{s['from']}—{s['relation']}→{s['to']}" for s in segs
                )
                src = p.get("source", "Neo4j")
                lines.append(f"  路径{i}（{p.get('length', '?')}跳, {src}）: {chain}")
            return "\n".join(lines)

        elif mode == "neighbors":
            ent = entity or entity_a
            if not ent:
                return "neighbors 模式需要 entity 或 entity_a"
            net = expand_neighbors(ent, max_depth=2)
            nodes = net.get("nodes", [])
            edges = net.get("edges", [])
            src = net.get("source", "Neo4j")
            if not nodes:
                return f"图谱中未找到 '{ent}' 的邻居。"
            lines = [f"'{ent}' 的邻居网络（{len(nodes)} 节点, {len(edges)} 边, {src}）："]
            for e in edges[:10]:
                lines.append(f"  {e['from']} —{e.get('relation','?')}→ {e['to']}")
            return "\n".join(lines)

        elif mode == "common":
            if not entity_a or not entity_b:
                return "common 模式需要 entity_a 和 entity_b"
            commons = common_neighbors(entity_a, entity_b)
            if not commons:
                return f"未找到 '{entity_a}' 和 '{entity_b}' 的共同邻居。"
            names = [c.get("common_name", "?") for c in commons[:10]]
            src = commons[0].get("source", "Neo4j") if commons else "Unknown"
            return f"'{entity_a}' 和 '{entity_b}' 的共同邻居（{src}）：" + "、".join(names)

        else:
            return f"未知探索模式: {mode}，可选: path / neighbors / common"
