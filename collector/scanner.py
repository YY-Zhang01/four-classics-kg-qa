"""变更扫描器（P5）：对比文件 hash，发现新增/变更/删除。

策略：
1. 遍历已注册的数据源（enabled + active）
2. 对每个数据源计算当前文件 hash
3. 与上次记录的 hash 对比 → 判定状态
4. 写入 update_log 记录变更
5. 更新数据源的 file_hash / last_scan
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from collector.sources import (
    list_sources,
    update_status,
    mark_changed,
    compute_file_hash,
    STATUS_ACTIVE,
    STATUS_CHANGED,
    STATUS_ERROR,
)
from retrieval.db import get_conn


def _write_log(source_id: int | None, domain: str, action: str, detail: dict) -> None:
    """写一条更新日志。"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO update_log (source_id, domain, action, detail) "
            "VALUES (%s, %s, %s, %s)",
            (source_id, domain, action, json.dumps(detail, ensure_ascii=False)),
        )
        conn.commit()


def scan_source(source: dict) -> dict:
    """扫描单个数据源，返回变更摘要。

    Returns:
        {
            "source_id": int,
            "name": str,
            "action": "new" | "changed" | "unchanged" | "error",
            "old_hash": str,
            "new_hash": str,
            "error": str,
        }
    """
    source_id = source["id"]
    name = source["name"]
    path = source["path"]
    old_hash = source.get("file_hash") or ""

    try:
        new_hash = compute_file_hash(path)
    except Exception as e:
        update_status(source_id, status=STATUS_ERROR, error_msg=str(e))
        _write_log(source_id, source["domain"], "error", {"error": str(e)})
        return {
            "source_id": source_id, "name": name,
            "action": "error", "old_hash": old_hash,
            "new_hash": "", "error": str(e),
        }

    if not new_hash:
        update_status(source_id, status=STATUS_ERROR, error_msg="文件不存在或无法读取")
        return {
            "source_id": source_id, "name": name,
            "action": "error", "old_hash": old_hash,
            "new_hash": "", "error": "文件不存在",
        }

    import os
    file_size = os.path.getsize(path) if os.path.exists(path) else 0

    if not old_hash:
        # 新数据源，首次扫描
        update_status(
            source_id, status=STATUS_ACTIVE,
            file_hash=new_hash, file_size=file_size,
        )
        _write_log(source_id, source["domain"], "new_file", {
            "name": name, "hash": new_hash[:16], "size": file_size,
        })
        return {
            "source_id": source_id, "name": name,
            "action": "new", "old_hash": "", "new_hash": new_hash,
            "error": "",
        }

    if new_hash != old_hash:
        # 文件已变更
        mark_changed(source_id)
        update_status(
            source_id, file_hash=new_hash, file_size=file_size,
        )
        _write_log(source_id, source["domain"], "changed", {
            "name": name, "old_hash": old_hash[:16],
            "new_hash": new_hash[:16], "size": file_size,
        })
        return {
            "source_id": source_id, "name": name,
            "action": "changed", "old_hash": old_hash,
            "new_hash": new_hash, "error": "",
        }

    # 未变更
    update_status(source_id, status=STATUS_ACTIVE)
    return {
        "source_id": source_id, "name": name,
        "action": "unchanged", "old_hash": old_hash,
        "new_hash": new_hash, "error": "",
    }


def scan_all(domain: str = "") -> list[dict]:
    """扫描所有活跃数据源，返回变更摘要列表。

    Args:
        domain: 领域过滤，空字符串 = 全部

    Returns:
        [{source_id, name, action, old_hash, new_hash, error}, ...]
    """
    sources = list_sources(domain=domain, enabled_only=True)
    if not sources:
        return []

    results = []
    for s in sources:
        result = scan_source(s)
        results.append(result)

    # 统计
    new_count = sum(1 for r in results if r["action"] == "new")
    changed_count = sum(1 for r in results if r["action"] == "changed")
    error_count = sum(1 for r in results if r["action"] == "error")

    # 全局扫描日志（source_id=NULL 表示汇总）
    _write_log(None, domain or "_all", "scan_complete", {
        "total": len(results),
        "new": new_count,
        "changed": changed_count,
        "unchanged": len(results) - new_count - changed_count - error_count,
        "error": error_count,
    })

    return results


def get_changed(domain: str = "") -> list[dict]:
    """快速获取当前有变更的数据源（不重新扫描）。"""
    sources = list_sources(domain=domain, enabled_only=True)
    return [s for s in sources if s.get("status") == STATUS_CHANGED]
