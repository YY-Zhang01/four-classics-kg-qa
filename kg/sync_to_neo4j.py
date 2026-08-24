"""PG → Neo4j 同步器（P3）：将 PostgreSQL 中已审核通过的三元组同步到 Neo4j。

设计原则：
- PG 是"账本"（权威数据源），Neo4j 是"查询副本"
- 只同步 review_status = 'approved' 的三元组
- 支持全量同步和增量同步
- Neo4j 不可用时静默跳过
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from retrieval.db import get_conn
from kg.neo4j_conn import is_available, run_query, get_driver

logger = logging.getLogger(__name__)

# Neo4j 约束创建 Cypher（幂等）
_ENSURE_CONSTRAINTS = [
    "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Entity) REQUIRE n.name IS UNIQUE",
    "CREATE INDEX IF NOT EXISTS FOR (n:Entity) ON (n.source)",
]

# 上次同步时间戳（内存中，重启后重置为全量同步）
_last_sync: dict[str, datetime] = {}  # domain → last_sync_time


def ensure_schema() -> bool:
    """在 Neo4j 中创建必要的约束和索引（幂等）。"""
    if not is_available():
        return False
    for stmt in _ENSURE_CONSTRAINTS:
        try:
            run_query(stmt)
        except Exception as e:
            logger.warning(f"Neo4j schema 初始化警告: {e}")
    return True


def full_sync(domain: str = "") -> int:
    """全量同步：将 PG 中某领域所有 approved 三元组写入 Neo4j。

    Args:
        domain: 领域过滤（如 '红楼梦'），空字符串 = 全量

    Returns:
        同步的三元组数量。Neo4j 不可用时返回 0。
    """
    if not is_available():
        logger.info("Neo4j 不可用，跳过同步")
        return 0

    # 从 PG 读取已审核的三元组
    with get_conn() as conn, conn.cursor() as cur:
        if domain:
            cur.execute(
                "SELECT subject, relation, object, source, confidence, source_chunk_id "
                "FROM kg_triples "
                "WHERE review_status = 'approved' AND source = %s",
                (domain,),
            )
        else:
            cur.execute(
                "SELECT subject, relation, object, source, confidence, source_chunk_id "
                "FROM kg_triples "
                "WHERE review_status = 'approved'",
            )
        rows = cur.fetchall()

    if not rows:
        logger.info(f"没有待同步的三元组（domain={domain or '全量'}）")
        return 0

    ensure_schema()

    # 批量写入 Neo4j
    driver = get_driver()
    if driver is None:
        return 0

    count = 0
    with driver.session() as session:
        for row in rows:
            subject, relation, object_, source, confidence, chunk_id = row
            try:
                session.run(
                    """
                    MERGE (a:Entity {name: $subject})
                    SET a.source = COALESCE(a.source, $source)
                    MERGE (b:Entity {name: $object})
                    SET b.source = COALESCE(b.source, $source)
                    MERGE (a)-[r:%s]->(b)
                    SET r.confidence = $confidence,
                        r.source_chunk_id = $chunk_id,
                        r.source = $source
                    """ % _safe_rel_name(relation),
                    {
                        "subject": subject,
                        "object": object_,
                        "source": source or "",
                        "confidence": confidence or 0.0,
                        "chunk_id": chunk_id or "",
                    },
                )
                count += 1
            except Exception as e:
                logger.warning(f"同步三元组失败 ({subject}-{relation}->{object_}): {e}")

    # 更新同步时间
    _last_sync[domain or "_all"] = datetime.now(timezone.utc)

    logger.info(f"Neo4j 全量同步完成: {count} 条三元组（domain={domain or '全量'}）")
    return count


def _safe_rel_name(relation: str) -> str:
    """将关系名转为合法的 Neo4j 关系类型名。

    Neo4j 关系类型只允许字母、数字、下划线；中文需要映射或包裹。
    我们用反引号包裹中文关系名。
    """
    # Neo4j 支持反引号包裹任意字符的关系类型
    return f"`{relation}`"


def clear_graph(domain: str = "") -> int:
    """清空 Neo4j 中某领域的节点和关系。

    Args:
        domain: 领域过滤，空字符串 = 全量清空

    Returns:
        删除的节点数
    """
    if not is_available():
        return 0

    if domain:
        result = run_query(
            "MATCH (n:Entity {source: $domain}) DETACH DELETE n",
            {"domain": domain},
        )
    else:
        result = run_query("MATCH (n) DETACH DELETE n")
    deleted = len(result) if result else 0
    logger.info(f"Neo4j 清空完成: 约 {deleted} 个节点（domain={domain or '全量'}）")
    return deleted


def sync_stats() -> dict:
    """获取 Neo4j 同步状态统计。"""
    if not is_available():
        return {"available": False, "nodes": 0, "relationships": 0}

    node_count = run_query("MATCH (n:Entity) RETURN count(n) AS cnt")
    rel_count = run_query("MATCH ()-[r]->() RETURN count(r) AS cnt")

    return {
        "available": True,
        "nodes": node_count[0]["cnt"] if node_count else 0,
        "relationships": rel_count[0]["cnt"] if rel_count else 0,
        "last_sync": {
            k: v.isoformat() for k, v in _last_sync.items()
        },
    }
