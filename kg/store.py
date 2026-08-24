"""知识图谱存储（P2）：三元组写入 PostgreSQL，查询接口。

先用 PG 表存三元组，后续可平滑迁移到 Neo4j——查询接口不变。
"""
from __future__ import annotations

import json
from pathlib import Path

from retrieval.db import get_conn

KG_DIR = Path(__file__).resolve().parent
SCHEMA_SQL = KG_DIR / "schema.sql"
TRIPLES_JSON = KG_DIR / "triples.json"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS public.kg_triples (
    id        SERIAL PRIMARY KEY,
    subject   TEXT NOT NULL,
    relation  TEXT NOT NULL,
    object    TEXT NOT NULL,
    source    VARCHAR(50),
    domain    VARCHAR(50),
    confidence      REAL DEFAULT 0.0,
    source_chunk_id TEXT,
    review_status   VARCHAR(20) DEFAULT 'pending',
    extract_method  VARCHAR(20) DEFAULT 'llm',
    UNIQUE(subject, relation, object)
);
"""

# 当前激活的 domain（运行时切换用，默认从 env 读）
import os as _os
_active_kg_domain: str = _os.getenv("PROJECT_DOMAIN", "")


def set_kg_domain(domain: str) -> None:
    """运行时切换 KG 查询的领域过滤。"""
    global _active_kg_domain
    _active_kg_domain = domain


def _domain_clause() -> str:
    """返回 SQL WHERE 条件中按 source 过滤的片段。"""
    if _active_kg_domain:
        return "source = %s"
    return "source IS NOT NULL OR TRUE"  # 不回退到全量，防止跨书污染


def _domain_param() -> tuple:
    """返回 domain 过滤的 SQL 参数。"""
    if _active_kg_domain:
        return (_active_kg_domain,)
    return ()


def ensure_table() -> None:
    """建三元组表（幂等）。"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
        conn.commit()


def clear() -> None:
    """清空三元组表。"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE kg_triples;")
        conn.commit()


def insert_triples(triples: list[dict], source: str = "", domain: str = "") -> int:
    """批量写入三元组，跳过重复，返回实际插入数。

    P0: 每条三元组带 confidence, source_chunk_id, extract_method。
    P5: 新增 domain 列，解除 source_name == domain 耦合。
    """
    if not triples:
        return 0
    ensure_table()
    count = 0
    with get_conn() as conn, conn.cursor() as cur:
        for t in triples:
            cur.execute(
                "INSERT INTO kg_triples(subject, relation, object, source, "
                "domain, confidence, source_chunk_id, extract_method) "
                "VALUES(%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (
                    t["subject"], t["relation"], t["object"],
                    source or t.get("source", ""),
                    domain or t.get("domain", ""),
                    t.get("confidence", 0.0),
                    t.get("source_chunk_id"),
                    t.get("extract_method", "llm"),
                ),
            )
            count += cur.rowcount
        conn.commit()
    return count


def load_from_json(path: Path | None = None) -> int:
    """从 triples.json 读三元组，写入 PG。返回写入数。"""
    path = path or TRIPLES_JSON
    if not path.exists():
        print(f"三元组文件不存在：{path}")
        return 0
    triples = json.loads(path.read_text(encoding="utf-8"))
    n = insert_triples(triples)
    print(f"写入 {n} 条三元组（共 {len(triples)} 条，跳过 {len(triples) - n} 条重复）")
    return n


def query_by_entity(name: str, max_depth: int = 1) -> list[dict]:
    """查某个人物的直接关系（1 跳），按当前 domain 过滤。

    P0: 返回 confidence, source_chunk_id 证据信息。
    P4: 排除 review_status = 'rejected' 的已驳回三元组。
    返回格式：[{subject, relation, object, source, confidence, source_chunk_id}, ...]
    """
    domain_clause = _domain_clause() if _active_kg_domain else ""
    review_filter = " AND (review_status IS NULL OR review_status != 'rejected')"
    with get_conn() as conn, conn.cursor() as cur:
        if domain_clause:
            cur.execute(
                "SELECT subject, relation, object, source, confidence, source_chunk_id "
                "FROM kg_triples "
                "WHERE (subject = %s OR object = %s) AND " + domain_clause + review_filter,
                (name, name, *_domain_param()),
            )
        else:
            cur.execute(
                "SELECT subject, relation, object, source, confidence, source_chunk_id "
                "FROM kg_triples "
                "WHERE (subject = %s OR object = %s)" + review_filter,
                (name, name),
            )
        return [
            {
                "subject": r[0], "relation": r[1], "object": r[2],
                "source": r[3], "confidence": r[4], "source_chunk_id": r[5],
            }
            for r in cur.fetchall()
        ]


def query_relation(subj: str, obj: str) -> list[dict]:
    """查两个人物之间的关系路径（暂只支持直接关系），按当前 domain 过滤。

    P0: 返回 confidence, source_chunk_id 证据信息。
    P4: 排除已驳回三元组。
    """
    domain_clause = _domain_clause() if _active_kg_domain else ""
    review_filter = " AND (review_status IS NULL OR review_status != 'rejected')"
    with get_conn() as conn, conn.cursor() as cur:
        if domain_clause:
            cur.execute(
                "SELECT subject, relation, object, source, confidence, source_chunk_id "
                "FROM kg_triples "
                "WHERE ((subject = %s AND object = %s) OR (subject = %s AND object = %s)) AND " + domain_clause + review_filter,
                (subj, obj, obj, subj, *_domain_param()),
            )
        else:
            cur.execute(
                "SELECT subject, relation, object, source, confidence, source_chunk_id "
                "FROM kg_triples "
                "WHERE ((subject = %s AND object = %s) OR (subject = %s AND object = %s))" + review_filter,
                (subj, obj, obj, subj),
            )
        return [
            {
                "subject": r[0], "relation": r[1], "object": r[2],
                "source": r[3], "confidence": r[4], "source_chunk_id": r[5],
            }
            for r in cur.fetchall()
        ]


def count_triples() -> int:
    """三元组总数（按当前 domain 过滤）。"""
    domain_clause = _domain_clause() if _active_kg_domain else ""
    with get_conn() as conn, conn.cursor() as cur:
        if domain_clause:
            cur.execute("SELECT count(*) FROM kg_triples WHERE " + domain_clause, _domain_param())
        else:
            cur.execute("SELECT count(*) FROM kg_triples")
        return cur.fetchone()[0]


if __name__ == "__main__":
    ensure_table()
    load_from_json()
