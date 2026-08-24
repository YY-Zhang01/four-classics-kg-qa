"""Wiki 页面存储（P1）：wiki_pages 表的 CRUD，基于 PostgreSQL。

wiki_pages 存的是结构化 JSON——每页有多个 section，每个 section 带 content + source_chunk_ids。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from retrieval.db import get_conn


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS public.wiki_pages (
    id          SERIAL PRIMARY KEY,
    page_type   VARCHAR(30)  NOT NULL,
    title       TEXT         NOT NULL,
    domain      VARCHAR(50)  NOT NULL,
    content     JSONB        NOT NULL,
    entities    TEXT[]       DEFAULT '{}',
    confidence  REAL         DEFAULT 0.0,
    review_status VARCHAR(20) DEFAULT 'pending',
    version     INTEGER      DEFAULT 1,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE(domain, page_type, title)
);
CREATE INDEX IF NOT EXISTS idx_wiki_domain ON public.wiki_pages(domain);
CREATE INDEX IF NOT EXISTS idx_wiki_type   ON public.wiki_pages(page_type);
CREATE INDEX IF NOT EXISTS idx_wiki_entities ON public.wiki_pages USING GIN(entities);
CREATE INDEX IF NOT EXISTS idx_wiki_review ON public.wiki_pages(review_status);
"""


def ensure_table() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
        conn.commit()


def upsert_page(
    page_type: str,
    title: str,
    domain: str,
    content: dict,
    entities: list[str] | None = None,
    confidence: float = 0.0,
) -> int:
    """写入或更新一页 Wiki。返回 page id。"""
    ensure_table()
    now = datetime.now(timezone.utc)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO wiki_pages(page_type, title, domain, content, entities, "
            "confidence, updated_at) "
            "VALUES(%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT(domain, page_type, title) DO UPDATE SET "
            "content = EXCLUDED.content, "
            "entities = EXCLUDED.entities, "
            "confidence = EXCLUDED.confidence, "
            "version = wiki_pages.version + 1, "
            "updated_at = EXCLUDED.updated_at "
            "RETURNING id",
            (
                page_type, title, domain,
                json.dumps(content, ensure_ascii=False),
                entities or [],
                confidence, now,
            ),
        )
        row = cur.fetchone()
        conn.commit()
    return row[0] if row else 0


def get_page(domain: str, page_type: str, title: str) -> dict | None:
    """获取单页 Wiki。"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, page_type, title, domain, content, entities, confidence, "
            "review_status, version, created_at, updated_at "
            "FROM wiki_pages WHERE domain = %s AND page_type = %s AND title = %s",
            (domain, page_type, title),
        )
        row = cur.fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def search_pages(
    domain: str,
    query: str = "",
    page_type: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """搜索 Wiki 页面：按标题模糊匹配 + 可选按类型过滤。"""
    with get_conn() as conn, conn.cursor() as cur:
        sql = (
            "SELECT id, page_type, title, domain, content, entities, confidence, "
            "review_status, version, created_at, updated_at "
            "FROM wiki_pages WHERE domain = %s AND review_status = 'approved'"
        )
        params: list = [domain]

        if page_type:
            sql += " AND page_type = %s"
            params.append(page_type)

        if query:
            # 标题模糊匹配 或 实体包含
            sql += " AND (title ILIKE %s OR %s = ANY(entities))"
            like = f"%{query}%"
            params.extend([like, query])

        sql += " ORDER BY confidence DESC, updated_at DESC LIMIT %s"
        params.append(limit)

        cur.execute(sql, params)
        return [_row_to_dict(r) for r in cur.fetchall()]


def list_pages(domain: str, page_type: str | None = None, limit: int = 50) -> list[dict]:
    """列出某领域的所有 Wiki 页面（摘要：不含 content）。"""
    with get_conn() as conn, conn.cursor() as cur:
        if page_type:
            cur.execute(
                "SELECT id, page_type, title, domain, entities, confidence, "
                "review_status, version, updated_at "
                "FROM wiki_pages WHERE domain = %s AND page_type = %s "
                "ORDER BY title LIMIT %s",
                (domain, page_type, limit),
            )
        else:
            cur.execute(
                "SELECT id, page_type, title, domain, entities, confidence, "
                "review_status, version, updated_at "
                "FROM wiki_pages WHERE domain = %s "
                "ORDER BY page_type, title LIMIT %s",
                (domain, limit),
            )
        return [
            {
                "id": r[0], "page_type": r[1], "title": r[2], "domain": r[3],
                "entities": r[4], "confidence": r[5], "review_status": r[6],
                "version": r[7], "updated_at": str(r[8]),
            }
            for r in cur.fetchall()
        ]


def count_pages(domain: str) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM wiki_pages WHERE domain = %s", (domain,))
        return cur.fetchone()[0]


def _row_to_dict(row) -> dict:
    content = row[4]
    if isinstance(content, str):
        content = json.loads(content)
    return {
        "id": row[0], "page_type": row[1], "title": row[2], "domain": row[3],
        "content": content, "entities": row[5], "confidence": row[6],
        "review_status": row[7], "version": row[8],
        "created_at": str(row[9]), "updated_at": str(row[10]),
    }
