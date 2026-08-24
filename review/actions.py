"""审核操作（P4）：approve / reject / revise / deprecate。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from retrieval.db import get_conn
from review.models import (
    STATUS_APPROVED, STATUS_REJECTED, STATUS_NEEDS_REVISION,
    STATUS_DEPRECATED, VALID_STATUSES,
)


def _table_for(target_type: str) -> str:
    """target_type 到表名的映射。"""
    return {"chunk": "chunks", "kg_triple": "kg_triples", "wiki_page": "wiki_pages"}[target_type]


# 允许 revise 直接修改的列（白名单）。
# 杜绝 SQL 注入 / 越权改 id、review_status 等受控字段。
_EDITABLE_COLUMNS: dict[str, frozenset[str]] = {
    "chunk": frozenset({
        "source", "chapter", "body", "page_no", "paragraph_no",
        "content_hash", "source_url",
    }),
    "kg_triple": frozenset({
        "subject", "relation", "object", "source",
        "confidence", "source_chunk_id", "extract_method",
    }),
    "wiki_page": frozenset({
        "page_type", "title", "domain", "content", "entities", "confidence",
    }),
}


def _write_log(
    target_type: str,
    target_id: str,
    action: str,
    reviewer: str = "",
    reason: str = "",
    old_value: dict | None = None,
    new_value: dict | None = None,
) -> None:
    """写审核操作日志到 review_log 表。"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO review_log (target_type, target_id, action, reviewer, reason, old_value, new_value)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                target_type,
                target_id,
                action,
                reviewer or "admin",
                reason or "",
                json.dumps(old_value, ensure_ascii=False) if old_value else None,
                json.dumps(new_value, ensure_ascii=False) if new_value else None,
            ),
        )
        conn.commit()


def approve(target_type: str, target_id: str, reviewer: str = "") -> bool:
    """审核通过：将目标状态改为 approved。

    Returns:
        True 表示操作成功
    """
    if target_type not in ("chunk", "kg_triple", "wiki_page"):
        raise ValueError(f"未知目标类型: {target_type}")

    table = _table_for(target_type)

    with get_conn() as conn, conn.cursor() as cur:
        # 读取旧状态
        cur.execute(
            f"SELECT review_status FROM {table} WHERE id = %s",
            (int(target_id) if target_type != "chunk" else target_id,),
        )
        row = cur.fetchone()
        if not row:
            return False
        old_status = row[0]

        # 更新状态
        cur.execute(
            f"UPDATE {table} SET review_status = %s WHERE id = %s",
            (STATUS_APPROVED, int(target_id) if target_type != "chunk" else target_id),
        )
        conn.commit()

    _write_log(
        target_type, target_id, "approved", reviewer=reviewer,
        old_value={"review_status": old_status},
        new_value={"review_status": STATUS_APPROVED},
    )
    return True


def reject(target_type: str, target_id: str, reason: str = "", reviewer: str = "") -> bool:
    """驳回：将目标状态改为 rejected，并记录原因。

    Returns:
        True 表示操作成功
    """
    if target_type not in ("chunk", "kg_triple", "wiki_page"):
        raise ValueError(f"未知目标类型: {target_type}")

    table = _table_for(target_type)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT review_status FROM {table} WHERE id = %s",
            (int(target_id) if target_type != "chunk" else target_id,),
        )
        row = cur.fetchone()
        if not row:
            return False
        old_status = row[0]

        cur.execute(
            f"UPDATE {table} SET review_status = %s WHERE id = %s",
            (STATUS_REJECTED, int(target_id) if target_type != "chunk" else target_id),
        )
        conn.commit()

    _write_log(
        target_type, target_id, "rejected", reviewer=reviewer, reason=reason,
        old_value={"review_status": old_status},
        new_value={"review_status": STATUS_REJECTED},
    )
    return True


def revise(
    target_type: str, target_id: str,
    updates: dict, reviewer: str = "",
) -> bool:
    """修正并标记为 needs_revision：更新目标内容，状态改为待复审。

    Args:
        updates: 要更新的字段，如 {"body": "修正后的文本"} 或 {"object": "正确值"}
    """
    if target_type not in _EDITABLE_COLUMNS:
        raise ValueError(f"未知目标类型: {target_type}")
    if not updates:
        raise ValueError("updates 不能为空")

    # 列名白名单校验：只允许修改内容字段，杜绝 SQL 注入 / 越权改 id、review_status 等
    allowed = _EDITABLE_COLUMNS[target_type]
    bad = sorted(str(c) for c in updates if c not in allowed)
    if bad:
        raise ValueError(f"不允许修改的字段: {', '.join(bad)}")

    table = _table_for(target_type)

    with get_conn() as conn, conn.cursor() as cur:
        # 读取旧值
        cur.execute(
            f"SELECT review_status FROM {table} WHERE id = %s",
            (int(target_id) if target_type != "chunk" else target_id,),
        )
        row = cur.fetchone()
        if not row:
            return False
        old_status = row[0]

        # 构建 SET 子句（列名均来自白名单，安全；review_status 一并改为待复审）
        set_parts = ["review_status = %s"]
        values: list = [STATUS_NEEDS_REVISION]
        for col, val in updates.items():
            set_parts.append(f"{col} = %s")
            values.append(val)
        values.append(int(target_id) if target_type != "chunk" else target_id)

        cur.execute(
            f"UPDATE {table} SET {', '.join(set_parts)} WHERE id = %s",
            values,
        )
        conn.commit()

    _write_log(
        target_type, target_id, "revised", reviewer=reviewer,
        old_value={"review_status": old_status},
        new_value={"review_status": STATUS_NEEDS_REVISION, "updates": updates},
    )
    return True


def deprecate(target_type: str, target_id: str, reviewer: str = "") -> bool:
    """标记为废弃（旧版本不再使用）。"""
    if target_type not in ("chunk", "kg_triple", "wiki_page"):
        raise ValueError(f"未知目标类型: {target_type}")

    table = _table_for(target_type)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT review_status FROM {table} WHERE id = %s",
            (int(target_id) if target_type != "chunk" else target_id,),
        )
        row = cur.fetchone()
        if not row:
            return False
        old_status = row[0]

        cur.execute(
            f"UPDATE {table} SET review_status = %s WHERE id = %s",
            (STATUS_DEPRECATED, int(target_id) if target_type != "chunk" else target_id),
        )

    _write_log(
        target_type, target_id, "deprecated", reviewer=reviewer,
        old_value={"review_status": old_status},
        new_value={"review_status": STATUS_DEPRECATED},
    )
    return True


def get_history(target_type: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
    """查询审核历史记录。"""
    with get_conn() as conn, conn.cursor() as cur:
        if target_type:
            cur.execute(
                """SELECT id, target_type, target_id, action, reviewer, reason, created_at
                   FROM review_log
                   WHERE target_type = %s
                   ORDER BY created_at DESC
                   LIMIT %s OFFSET %s""",
                (target_type, limit, offset),
            )
        else:
            cur.execute(
                """SELECT id, target_type, target_id, action, reviewer, reason, created_at
                   FROM review_log
                   ORDER BY created_at DESC
                   LIMIT %s OFFSET %s""",
                (limit, offset),
            )

        return [
            {
                "id": row[0],
                "target_type": row[1],
                "target_id": row[2],
                "action": row[3],
                "reviewer": row[4],
                "reason": row[5],
                "created_at": row[6].isoformat() if row[6] else "",
            }
            for row in cur.fetchall()
        ]
