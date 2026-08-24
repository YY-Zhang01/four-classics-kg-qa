"""审核队列查询（P4）：从 PG 拉取待审项，支持分页、按类型筛选。"""
from __future__ import annotations

from retrieval.db import get_conn
from review.models import ReviewTarget, ReviewStats, STATUS_PENDING


def query_queue(
    domain: str,
    target_type: str = "",
    limit: int = 20,
    offset: int = 0,
) -> list[ReviewTarget]:
    """查询待审队列。

    Args:
        domain: 领域（红楼梦/三国演义等）
        target_type: 空=全部, "chunk"/"kg"/"wiki"
        limit: 每页条数
        offset: 偏移
    """
    results: list[ReviewTarget] = []

    with get_conn() as conn, conn.cursor() as cur:
        # ── chunks ──
        if not target_type or target_type == "chunk":
            cur.execute(
                """SELECT id, source, chapter, body, page_no, review_status, content_hash
                   FROM chunks
                   WHERE source = %s AND review_status = %s
                   ORDER BY id
                   LIMIT %s OFFSET %s""",
                (domain, STATUS_PENDING, limit, offset),
            )
            for row in cur.fetchall():
                results.append(ReviewTarget(
                    target_type="chunk",
                    target_id=row[0],
                    title=f"{row[1]}·{row[2] or ''}"[:60],
                    detail={
                        "source": row[1],
                        "chapter": row[2],
                        "body": row[3][:500],
                        "page_no": row[4],
                        "content_hash": row[6],
                    },
                    confidence=0,  # chunks 表没有单独的 confidence
                    review_status=row[5] or STATUS_PENDING,
                    domain=domain,
                ))

        # ── kg_triples ──
        if not target_type or target_type == "kg":
            cur.execute(
                """SELECT id, subject, relation, object, source, confidence, review_status,
                          source_chunk_id, extract_method
                   FROM kg_triples
                   WHERE source = %s AND review_status = %s
                   ORDER BY confidence ASC NULLS FIRST
                   LIMIT %s OFFSET %s""",
                (domain, STATUS_PENDING, limit, offset),
            )
            for row in cur.fetchall():
                results.append(ReviewTarget(
                    target_type="kg_triple",
                    target_id=str(row[0]),
                    title=f"{row[1]} —{row[2]}→ {row[3]}",
                    detail={
                        "subject": row[1],
                        "relation": row[2],
                        "object": row[3],
                        "source_chunk_id": row[7],
                        "extract_method": row[8],
                    },
                    confidence=row[5] or 0,
                    review_status=row[6] or STATUS_PENDING,
                    domain=domain,
                ))

        # ── wiki_pages ──
        if not target_type or target_type == "wiki":
            cur.execute(
                """SELECT id, page_type, title, domain, content, confidence, review_status, version, created_at
                   FROM wiki_pages
                   WHERE domain = %s AND review_status = %s
                   ORDER BY created_at DESC
                   LIMIT %s OFFSET %s""",
                (domain, STATUS_PENDING, limit, offset),
            )
            for row in cur.fetchall():
                created = row[8].isoformat() if row[8] else ""
                results.append(ReviewTarget(
                    target_type="wiki_page",
                    target_id=str(row[0]),
                    title=row[2],
                    detail={
                        "page_type": row[1],
                        "content": row[4] if isinstance(row[4], dict) else {},
                        "entities": [],  # will be added if needed
                        "version": row[7],
                    },
                    confidence=row[5] or 0,
                    review_status=row[6] or STATUS_PENDING,
                    domain=domain,
                    created_at=created,
                ))

    return results


def get_stats(domain: str) -> ReviewStats:
    """获取审核统计（按领域）。"""
    stats = ReviewStats()
    today = __import__("datetime").date.today().isoformat()

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM chunks WHERE source = %s AND review_status = %s",
            (domain, STATUS_PENDING),
        )
        stats.pending_chunks = cur.fetchone()[0]

        cur.execute(
            "SELECT count(*) FROM kg_triples WHERE source = %s AND review_status = %s",
            (domain, STATUS_PENDING),
        )
        stats.pending_kg = cur.fetchone()[0]

        cur.execute(
            "SELECT count(*) FROM wiki_pages WHERE domain = %s AND review_status = %s",
            (domain, STATUS_PENDING),
        )
        stats.pending_wiki = cur.fetchone()[0]

        stats.total_pending = stats.pending_chunks + stats.pending_kg + stats.pending_wiki

        # 今日审核数量
        cur.execute(
            "SELECT count(*) FROM review_log WHERE action = 'approved' AND created_at::date = %s",
            (today,),
        )
        stats.approved_today = cur.fetchone()[0]

        cur.execute(
            "SELECT count(*) FROM review_log WHERE action = 'rejected' AND created_at::date = %s",
            (today,),
        )
        stats.rejected_today = cur.fetchone()[0]

    return stats
