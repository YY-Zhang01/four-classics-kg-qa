"""图谱多跳搜索（P3）：基于 Neo4j 的多跳关系查询，支持路径探索。

当 Neo4j 不可用时，自动回退到 PG 单跳查询。
"""

from __future__ import annotations

from kg.neo4j_conn import is_available, run_query
from kg.store import query_by_entity, query_relation


# ── Neo4j 路径查询 ──────────────────────────────────────────

def _clamp_depth(max_depth, default: int, lo: int, hi: int) -> int:
    """把跳数夹取到安全整数范围，防止非法值拼进 Cypher。

    Neo4j 的变长路径长度（[*1..n]）不支持参数化，只能字符串拼接，
    因此这里必须把 n 严格限制为合法整数，作为最后一道防线。
    """
    try:
        d = int(max_depth)
    except (TypeError, ValueError):
        d = default
    return max(lo, min(d, hi))


def find_paths(
    start_entity: str,
    end_entity: str,
    max_depth: int = 3,
    domain: str = "",
) -> list[dict]:
    """查找两个实体之间的最短关系路径（Neo4j 多跳）。

    Args:
        start_entity: 起始实体名
        end_entity: 目标实体名
        max_depth: 最大跳数（1-5）
        domain: 领域过滤

    Returns:
        路径列表，每条格式: {paths: [[{entity, relation}...]], length: N}
        Neo4j 不可用时回退到 PG 直接关系查询
    """
    max_depth = _clamp_depth(max_depth, 3, 1, 5)
    if not is_available():
        return _pg_fallback_path(start_entity, end_entity)

    domain_filter = "WHERE n.source = $domain AND m.source = $domain" if domain else ""
    cypher = f"""
        MATCH p = shortestPath((n:Entity {{name: $start}})-[*1..{max_depth}]-(m:Entity {{name: $end}}))
        {domain_filter}
        RETURN p, length(p) AS path_length
        ORDER BY path_length
        LIMIT 5
    """

    params = {"start": start_entity, "end": end_entity}
    if domain:
        params["domain"] = domain

    records = run_query(cypher, params)
    if not records:
        return []

    paths = []
    for rec in records:
        path_data = rec.get("p")
        length = rec.get("path_length", 0)
        if path_data:
            segments = _parse_path(path_data)
            paths.append({"segments": segments, "length": length})

    return paths


def _parse_path(path) -> list[dict]:
    """解析 Neo4j 路径对象为可序列化的段落列表。"""
    segments = []
    try:
        # neo4j Path 对象
        for rel in path.relationships:
            segments.append({
                "from": rel.start_node.get("name", ""),
                "relation": rel.type,
                "to": rel.end_node.get("name", ""),
                "confidence": rel.get("confidence", 0),
            })
    except AttributeError:
        # 回退：可能是 dict 格式
        pass
    return segments


def _pg_fallback_path(start: str, end: str) -> list[dict]:
    """PG 回退：只能查直接关系（1 跳）。"""
    rows = query_relation(start, end)
    if not rows:
        return []
    return [{
        "segments": [{
            "from": r["subject"],
            "relation": r["relation"],
            "to": r["object"],
            "confidence": r.get("confidence", 0),
        } for r in rows],
        "length": 1,
        "source": "pg_fallback",
    }]


# ── 多跳邻居查询 ────────────────────────────────────────────

def expand_neighbors(
    entity: str,
    max_depth: int = 2,
    domain: str = "",
) -> dict:
    """展开某实体的多跳邻居网络。

    Args:
        entity: 中心实体名
        max_depth: 展开深度（1-3）
        domain: 领域过滤

    Returns:
        {nodes: [{name, source}], edges: [{from, relation, to, confidence}]}
    """
    max_depth = _clamp_depth(max_depth, 2, 1, 3)
    if not is_available():
        return _pg_fallback_neighbors(entity)

    domain_filter = "WHERE n.source = $domain" if domain else ""
    cypher = f"""
        MATCH (center:Entity {{name: $entity}})-[r*1..{max_depth}]-(neighbor:Entity)
        {domain_filter}
        WITH center, neighbor, r
        RETURN center.name AS center_name,
               neighbor.name AS neighbor_name,
               neighbor.source AS neighbor_source,
               [rel IN r | type(rel)] AS relations,
               length(r) AS depth
        LIMIT 50
    """

    params = {"entity": entity}
    if domain:
        params["domain"] = domain

    records = run_query(cypher, params)
    if not records:
        return {"nodes": [], "edges": []}

    nodes_set: dict[str, dict] = {}
    edges: list[dict] = []

    for rec in records:
        center_name = rec.get("center_name", entity)
        neighbor_name = rec.get("neighbor_name", "")
        source = rec.get("neighbor_source", "")
        relations = rec.get("relations", [])

        nodes_set[center_name] = {"name": center_name, "source": source}
        nodes_set[neighbor_name] = {"name": neighbor_name, "source": source}

        # 只展示一跳边（多跳中间节点会被自然包含在 nodes 中）
        if relations:
            edges.append({
                "from": center_name,
                "relation": relations[0],
                "to": neighbor_name,
                "depth": rec.get("depth", 1),
            })

    return {
        "nodes": list(nodes_set.values()),
        "edges": edges,
    }


def _pg_fallback_neighbors(entity: str) -> dict:
    """PG 回退：只能查直接邻居（1 跳）。"""
    rows = query_by_entity(entity)
    nodes_set: dict[str, dict] = {}
    edges: list[dict] = []

    for r in rows:
        nodes_set[r["subject"]] = {"name": r["subject"]}
        nodes_set[r["object"]] = {"name": r["object"]}
        edges.append({
            "from": r["subject"],
            "relation": r["relation"],
            "to": r["object"],
            "confidence": r.get("confidence", 0),
        })

    return {"nodes": list(nodes_set.values()), "edges": edges, "source": "pg_fallback"}


# ── 共同邻居查询 ────────────────────────────────────────────

def common_neighbors(
    entity_a: str,
    entity_b: str,
    domain: str = "",
) -> list[dict]:
    """查找两个实体的共同邻居（常用于'有什么共同点'类问题）。

    Neo4j 不可用时回退到 PG 计算。
    """
    if not is_available():
        return _pg_fallback_common(entity_a, entity_b)

    domain_filter = "WHERE n.source = $domain" if domain else ""
    cypher = f"""
        MATCH (a:Entity {{name: $entity_a}})-[r1]-(common:Entity)-[r2]-(b:Entity {{name: $entity_b}})
        {domain_filter}
        RETURN common.name AS common_name,
               type(r1) AS relation_to_a,
               type(r2) AS relation_to_b
        LIMIT 20
    """

    params = {"entity_a": entity_a, "entity_b": entity_b}
    if domain:
        params["domain"] = domain

    return run_query(cypher, params)


def _pg_fallback_common(a: str, b: str) -> list[dict]:
    """PG 回退：计算共同邻居。"""
    rows_a = query_by_entity(a)
    rows_b = query_by_entity(b)

    neighbors_a = set()
    for r in rows_a:
        if r["subject"] == a:
            neighbors_a.add(r["object"])
        else:
            neighbors_a.add(r["subject"])

    common = []
    for r in rows_b:
        other = r["object"] if r["subject"] == b else r["subject"]
        if other in neighbors_a:
            common.append({
                "common_name": other,
                "source": "pg_fallback",
            })

    return common


# ── 全文搜索实体 ────────────────────────────────────────────

def search_entities(keyword: str, domain: str = "", limit: int = 10) -> list[dict]:
    """模糊搜索 Neo4j 中的实体节点。

    Neo4j 不可用时从 PG kg_triples 搜索。
    """
    if not is_available():
        return _pg_search_entities(keyword, domain, limit)

    domain_filter = "AND n.source = $domain" if domain else ""
    cypher = f"""
        MATCH (n:Entity)
        WHERE n.name CONTAINS $keyword
        {domain_filter}
        RETURN n.name AS name, n.source AS source
        LIMIT $limit
    """

    return run_query(cypher, {"keyword": keyword, "limit": limit, "domain": domain})


def _pg_search_entities(keyword: str, domain: str, limit: int) -> list[dict]:
    """PG 回退：从 kg_triples 搜索实体名。"""
    from retrieval.db import get_conn
    with get_conn() as conn, conn.cursor() as cur:
        if domain:
            cur.execute(
                "SELECT DISTINCT subject AS name FROM kg_triples "
                "WHERE subject ILIKE %s AND source = %s "
                "UNION "
                "SELECT DISTINCT object AS name FROM kg_triples "
                "WHERE object ILIKE %s AND source = %s "
                "LIMIT %s",
                (f"%{keyword}%", domain, f"%{keyword}%", domain, limit),
            )
        else:
            cur.execute(
                "SELECT DISTINCT subject AS name FROM kg_triples "
                "WHERE subject ILIKE %s "
                "UNION "
                "SELECT DISTINCT object AS name FROM kg_triples "
                "WHERE object ILIKE %s "
                "LIMIT %s",
                (f"%{keyword}%", f"%{keyword}%", limit),
            )
        return [{"name": r[0]} for r in cur.fetchall()]
