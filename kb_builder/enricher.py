"""证据富化器（P0）：给已有 chunk 补全证据元数据。

用途：
1. 升级旧 chunk（P0 之前切的）——补 content_hash 和 review_status
2. 批量更新 DB 中缺失的证据字段
3. 验证证据完整性

不依赖 LLM，纯本地计算。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from config.settings import CHUNK_DIR
from retrieval.db import get_conn


def _compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def enrich_chunk_file(json_path: Path, default_review: str = "approved") -> int:
    """给一个 chunks JSON 文件里的每条 chunk 补证据字段（原地修改）。

    对已有字段（如 page_no）不覆盖；只补缺失的。
    返回补全的条数。
    """
    if not json_path.exists():
        return 0

    chunks = json.loads(json_path.read_text(encoding="utf-8"))
    enriched = 0

    for c in chunks:
        if "content_hash" not in c or not c.get("content_hash"):
            c["content_hash"] = _compute_hash(c.get("text", ""))
            enriched += 1
        if "review_status" not in c:
            c["review_status"] = default_review
        if "page_no" not in c:
            c["page_no"] = None
        if "paragraph_no" not in c:
            c["paragraph_no"] = None

    if enriched > 0:
        json_path.write_text(
            json.dumps(chunks, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return enriched


def enrich_all_chunks(default_review: str = "approved") -> dict:
    """扫描 chunks/ 下所有 JSON，补全证据字段。返回统计信息。"""
    stats = {"files": 0, "enriched": 0, "skipped": 0}
    for f in sorted(CHUNK_DIR.glob("*.json")):
        n = enrich_chunk_file(f, default_review=default_review)
        if n > 0:
            stats["enriched"] += n
            stats["files"] += 1
            print(f"  [enrich] {f.name}: 补全 {n} 条")
        else:
            stats["skipped"] += 1
    return stats


def sync_evidence_to_db() -> dict:
    """把 chunks JSON 里的证据字段同步到 PostgreSQL。"""
    stats = {"synced": 0}
    for f in sorted(CHUNK_DIR.glob("*.json")):
        chunks = json.loads(f.read_text(encoding="utf-8"))
        with get_conn() as conn, conn.cursor() as cur:
            for c in chunks:
                updates = []
                params = []
                cid = c["id"]

                if c.get("content_hash"):
                    updates.append("content_hash = %s")
                    params.append(c["content_hash"])
                if c.get("page_no") is not None:
                    updates.append("page_no = %s")
                    params.append(c["page_no"])
                if c.get("paragraph_no") is not None:
                    updates.append("paragraph_no = %s")
                    params.append(c["paragraph_no"])

                if updates and cid:
                    params.append(cid)
                    cur.execute(
                        f"UPDATE chunks SET {', '.join(updates)} WHERE id = %s",
                        params,
                    )
                    stats["synced"] += cur.rowcount
            conn.commit()
    return stats


if __name__ == "__main__":
    print("=== 证据富化器 ===\n")

    # 1. 补全 JSON 文件
    print("[1/2] 补全 chunks JSON 文件中的证据字段...")
    stats = enrich_all_chunks()
    print(f"  处理 {stats['files']} 个文件，补全 {stats['enriched']} 条\n")

    # 2. 同步到 DB
    print("[2/2] 同步证据字段到 PostgreSQL...")
    db_stats = sync_evidence_to_db()
    print(f"  同步 {db_stats['synced']} 条记录到 DB")
