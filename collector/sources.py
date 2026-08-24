"""数据源管理（P5）：注册、查询、更新数据源状态。

数据源是知识库的"原材料入口"——文件、URL、目录。
每个数据源记录其 hash、处理状态和最后更新时间，
供 scanner 检测变更后触发增量处理。
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from retrieval.db import get_conn

STATUS_ACTIVE = "active"
STATUS_CHANGED = "changed"
STATUS_ERROR = "error"
STATUS_ARCHIVED = "archived"

SOURCE_FILE = "file"
SOURCE_URL = "url"
SOURCE_DIR = "directory"


def register(
    name: str,
    path: str,
    domain: str,
    source_type: str = SOURCE_FILE,
) -> int:
    """注册或更新一个数据源。返回数据源 id。

    已存在的同名+同 domain 数据源会更新 path 和 source_type，
    但不会覆盖 hash/状态等运行时信息。
    """
    now = datetime.now(timezone.utc)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO data_sources (name, path, domain, source_type, updated_at) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (domain, name) DO UPDATE SET "
            "path = EXCLUDED.path, "
            "source_type = EXCLUDED.source_type, "
            "updated_at = EXCLUDED.updated_at "
            "RETURNING id",
            (name, path, domain, source_type, now),
        )
        row = cur.fetchone()
        conn.commit()
    return row[0] if row else 0


def get_source(source_id: int) -> dict | None:
    """获取单个数据源详情。"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, source_type, path, domain, file_hash, file_size, "
            "chunk_count, enabled, status, last_scan, last_update, error_msg, "
            "created_at, updated_at "
            "FROM data_sources WHERE id = %s",
            (source_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return _row_to_dict(row)


def list_sources(domain: str = "", enabled_only: bool = True) -> list[dict]:
    """列出数据源（可按领域和启用状态过滤）。"""
    with get_conn() as conn, conn.cursor() as cur:
        sql = (
            "SELECT id, name, source_type, path, domain, file_hash, file_size, "
            "chunk_count, enabled, status, last_scan, last_update, error_msg "
            "FROM data_sources WHERE 1=1"
        )
        params: list = []
        if domain:
            sql += " AND domain = %s"
            params.append(domain)
        if enabled_only:
            sql += " AND enabled = TRUE"
        sql += " ORDER BY domain, name"
        cur.execute(sql, params)
        return [_row_to_dict(r) for r in cur.fetchall()]


def update_status(
    source_id: int,
    status: str = "",
    file_hash: str = "",
    file_size: int = 0,
    chunk_count: int = 0,
    error_msg: str = "",
) -> None:
    """更新数据源的运行时状态（hash、大小、chunk 数、错误信息等）。"""
    now = datetime.now(timezone.utc)
    updates = ["updated_at = %s"]
    params: list = [now]

    if status:
        updates.append("status = %s")
        params.append(status)
    if file_hash:
        updates.append("file_hash = %s")
        params.append(file_hash)
    if file_size > 0:
        updates.append("file_size = %s")
        params.append(file_size)
    if chunk_count >= 0:
        updates.append("chunk_count = %s")
        params.append(chunk_count)
    if error_msg:
        updates.append("error_msg = %s")
        params.append(error_msg)

    updates.append("last_scan = %s")
    params.append(now)

    sql = f"UPDATE data_sources SET {', '.join(updates)} WHERE id = %s"
    params.append(source_id)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        conn.commit()


def mark_changed(source_id: int) -> None:
    """标记数据源为'已变更'状态。"""
    now = datetime.now(timezone.utc)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE data_sources SET status = %s, last_update = %s, updated_at = %s "
            "WHERE id = %s",
            (STATUS_CHANGED, now, now, source_id),
        )
        conn.commit()


def compute_file_hash(filepath: str | Path) -> str:
    """计算文件的 SHA256 哈希（用于变更检测）。"""
    path = Path(filepath)
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def auto_register_files(
    directory: str | Path,
    domain: str,
    pattern: str = "*.md",
) -> list[int]:
    """自动扫描目录，为匹配的文件注册数据源。返回新注册的 id 列表。"""
    dir_path = Path(directory)
    if not dir_path.exists():
        return []

    ids = []
    for f in sorted(dir_path.glob(pattern)):
        name = f.stem
        path = str(f.resolve())
        sid = register(name=name, path=path, domain=domain, source_type=SOURCE_FILE)
        ids.append(sid)
    return ids


def _row_to_dict(row) -> dict:
    cols = [
        "id", "name", "source_type", "path", "domain",
        "file_hash", "file_size", "chunk_count", "enabled",
        "status", "last_scan", "last_update", "error_msg",
    ]
    result = {}
    for i, col in enumerate(cols):
        val = row[i] if i < len(row) else None
        if isinstance(val, datetime):
            val = val.isoformat()
        result[col] = val
    return result
