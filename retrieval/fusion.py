"""融合检索（P2+P2router+P3）：KG + Wiki + 向量 + Neo4j图谱 四路召回 → 重排 → 统一输出。

支持两种模式：
1. search() — 传统模式：根据 query 自动判断，向后兼容
2. search_with_strategy() — 策略模式：接收 router 下发的策略，精确控制各路配额

P3: 当 Neo4j 可用时，关系型问题自动触发多跳图谱探索，结果合并到 KG 事实中。

对外暴露 search() / count() / label()，与 retriever 工厂接口一致。
"""
from __future__ import annotations

from config.settings import get_top_k
from retrieval import vector_search, kg_search


def label() -> str:
    try:
        from kg.neo4j_conn import is_available
        base = "KG+Wiki+向量+Neo4j图谱" if is_available() else "KG+Wiki+向量"
    except ImportError:
        base = "KG+Wiki+向量"
    return f"{base}融合检索"


def count() -> int:
    return vector_search.count()


def _get_wiki_search():
    """延迟导入 Wiki 搜索，避免硬依赖。"""
    try:
        from wiki.query import search as wiki_search, count as wiki_count
        if wiki_count() > 0:
            return wiki_search
    except ImportError:
        pass
    return None


def search(query: str, top_k: int | None = None) -> list[dict]:
    """融合检索入口（兼容模式）。

    策略：
    1. 判断是否关系型问题 → 是则优先走 KG 拿结构化事实
    2. Wiki 检索：人物/事项类问题走百科页面
    3. 向量检索始终作为兜底（原文块总是有用的）
    4. 合并后按置信度/相关度排序
    """
    k = top_k if top_k is not None else get_top_k()
    kg_facts: list[dict] = []
    wiki_pages: list[dict] = []
    vec_chunks: list[dict] = []

    # KG 检索：只对关系型问题触发
    if kg_search.is_relation_question(query) and kg_search.count() > 0:
        kg_facts = kg_search.search(query, top_k=5)

    # Wiki 检索：检查是否有匹配的百科页面
    wiki_fn = _get_wiki_search()
    if wiki_fn:
        wiki_pages = wiki_fn(query, top_k=2)

    # 向量检索：始终触发
    used = len(kg_facts) + len(wiki_pages)
    vec_k = max(k - used, 2)
    vec_chunks = vector_search.search(query, top_k=vec_k)

    # 合并：KG 事实最前面（结构化），Wiki 次之（百科摘要），向量块兜底（原文）
    combined = kg_facts + wiki_pages + vec_chunks
    combined.sort(key=lambda h: h.get("score", 0), reverse=True)
    return combined[:k]


def search_with_strategy(
    query: str,
    strategy=None,  # router.strategies.Strategy
    top_k: int | None = None,
) -> list[dict]:
    """策略化融合检索（P2 路由模式）。

    根据路由下发的策略，精确控制 KG/Wiki/向量 三路的召回配额和排序优先级。
    策略中 quota=0 的路不会触发检索（省资源）。

    Args:
        query: 用户问题
        strategy: router.strategies.Strategy 对象
        top_k: 总召回数上限

    Returns:
        合并排序后的结果列表
    """
    k = top_k if top_k is not None else get_top_k()

    # 默认策略：三路均衡
    kg_q = 3
    wiki_q = 2
    vec_q = k
    sort_order = "kg_wiki_vector"

    if strategy is not None:
        kg_q = strategy.kg_quota
        wiki_q = strategy.wiki_quota
        vec_q = strategy.vector_quota
        sort_order = strategy.sort_order

    kg_facts: list[dict] = []
    wiki_pages: list[dict] = []
    vec_chunks: list[dict] = []

    # KG 检索
    if kg_q > 0 and kg_search.count() > 0:
        kg_facts = kg_search.search(query, top_k=kg_q)

    # ── P3 Neo4j 图谱多跳探索 ──
    graph_paths: list[dict] = []
    if kg_q > 0:
        graph_paths = _get_graph_paths(query)

    # Wiki 检索
    if wiki_q > 0:
        wiki_fn = _get_wiki_search()
        if wiki_fn:
            wiki_pages = wiki_fn(query, top_k=wiki_q)

    # 向量检索
    if vec_q > 0:
        vec_chunks = vector_search.search(query, top_k=vec_q)

    # 按策略指定的顺序合并
    order_map = {
        "kg_wiki_vector": lambda: kg_facts + wiki_pages + vec_chunks,
        "kg_vector_wiki": lambda: kg_facts + vec_chunks + wiki_pages,
        "wiki_kg_vector": lambda: wiki_pages + kg_facts + vec_chunks,
        "wiki_vector": lambda: wiki_pages + vec_chunks,
        "vector_wiki": lambda: vec_chunks + wiki_pages,
    }
    combined = order_map.get(sort_order, order_map["kg_wiki_vector"])()

    # P3: 混合图谱路径结果（放在 KG 事实后面，比原文更结构化）
    combined = combined + graph_paths

    # 按 score 重排（保证高质量内容靠前）
    combined.sort(key=lambda h: h.get("score", 0), reverse=True)
    return combined[:k]


def _get_graph_paths(query: str, max_paths: int = 3) -> list[dict]:
    """P3: 从 Neo4j 图谱中获取与 query 相关的多跳路径。

    仅当 Neo4j 可用时触发。提取 query 中的人名实体，
    对每对实体查找最短路径。

    Returns:
        graph_chunk 格式的结果列表，可直接混入 fusion 结果
    """
    try:
        from kg.neo4j_conn import is_available
        if not is_available():
            return []
    except ImportError:
        return []

    try:
        from retrieval.graph_search import find_paths, search_entities
    except ImportError:
        return []

    # 简单实体提取：从配置中加载实体词典，匹配 query 中的实体
    try:
        from config.settings import get_entities, get_active_domain
        entities_dict = get_entities()
        common_names = entities_dict.get("common_names", [])
        # 找出 query 中出现的实体名
        found = [name for name in common_names if name in query]
    except Exception:
        found = []

    if len(found) < 2:
        return []

    # 对前几个实体对查找路径
    results: list[dict] = []
    seen_pairs = set()

    for i, a in enumerate(found[:3]):
        for b in found[i + 1 : 4]:
            pair = (a, b) if a < b else (b, a)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            paths = find_paths(a, b, max_depth=3)
            for p in paths[:max_paths]:
                segs = p.get("segments", [])
                if segs:
                    path_text = " → ".join(
                        f"{s['from']}—{s['relation']}→{s['to']}" for s in segs
                    )
                    results.append({
                        "type": "graph_path",
                        "text": f"图谱路径（{a} 到 {b}，{p.get('length', '?')} 跳）: {path_text}",
                        "source": "Neo4j知识图谱",
                        "chapter": f"{a}↔{b}关系链",
                        "score": 0.85,
                        "path_segments": segs,
                    })

    return results
