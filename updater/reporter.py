"""更新报告（P5）：生成变更摘要、影响分析、历史查询。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from retrieval.db import get_conn


def get_update_logs(
    domain: str = "",
    action: str = "",
    source_id: int = 0,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """查询更新日志。可按领域、动作、数据源过滤。

    Returns:
        [{id, source_id, domain, action, detail, created_at}, ...]
    """
    with get_conn() as conn, conn.cursor() as cur:
        sql = (
            "SELECT id, source_id, domain, action, detail, created_at "
            "FROM update_log WHERE 1=1"
        )
        params: list = []

        if domain:
            sql += " AND domain = %s"
            params.append(domain)
        if action:
            sql += " AND action = %s"
            params.append(action)
        if source_id:
            sql += " AND source_id = %s"
            params.append(source_id)

        sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cur.execute(sql, params)
        rows = cur.fetchall()

    result = []
    for r in rows:
        detail = r[4]
        if isinstance(detail, str):
            import json
            detail = json.loads(detail)
        result.append({
            "id": r[0],
            "source_id": r[1],
            "domain": r[2],
            "action": r[3],
            "detail": detail,
            "created_at": r[5].isoformat() if r[5] else None,
        })
    return result


def get_last_scan(domain: str = "") -> dict | None:
    """获取最近的扫描日志。"""
    logs = get_update_logs(domain=domain, action="scan_complete", limit=1)
    return logs[0] if logs else None


def get_source_history(source_id: int, limit: int = 20) -> list[dict]:
    """获取某数据源的更新历史。"""
    return get_update_logs(source_id=source_id, limit=limit)


def generate_report(domain: str = "") -> dict:
    """生成当前更新状态报告。

    Returns:
        {
            domain,
            sources: {total, active, changed, error, archived},
            last_scan: {...},
            recent_changes: [...],
        }
    """
    from collector.sources import list_sources, STATUS_ACTIVE, STATUS_CHANGED, STATUS_ERROR, STATUS_ARCHIVED

    sources = list_sources(domain=domain, enabled_only=False)

    stats = {
        "total": len(sources),
        "active": 0,
        "changed": 0,
        "error": 0,
        "archived": 0,
    }
    for s in sources:
        st = s.get("status", "")
        if st in stats:
            stats[st] += 1

    last_scan = get_last_scan(domain=domain)
    recent_changes = get_update_logs(
        domain=domain,
        action="changed",
        limit=10,
    )

    return {
        "domain": domain or "all",
        "sources": stats,
        "last_scan": last_scan,
        "recent_changes": recent_changes,
    }
