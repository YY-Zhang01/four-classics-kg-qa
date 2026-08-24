"""向量检索（P1）：语义相似度召回。

思路：把库里每个块的向量拉进内存排成一张大表（归一化后），
查询也算成向量，用点积（等价余弦相似度）比"意思"的接近程度，取最像的 Top-K。
对外的 search() 接口与 P0 关键词检索保持一致，方便上层无感切换。
"""
from __future__ import annotations

import numpy as np

from config.settings import TOP_K, get_active_domain
from llm.embedding import embed_one
from retrieval.db import get_conn

# 进程内缓存：按 domain 分桶存储 (元信息列表, 归一化向量矩阵)
# 支持用户端和管理端各自维护独立的 domain 缓存
_CACHES: dict[str, tuple[list[dict], np.ndarray]] = {}


def _load_matrix(domain: str | None = None) -> tuple[list[dict], np.ndarray]:
    """加载指定 domain 的向量矩阵。不传 domain 则用当前激活的。"""
    if domain is None:
        domain = get_active_domain()

    # 缓存命中
    if domain in _CACHES:
        return _CACHES[domain]

    # 缓存未命中：从数据库加载
    with get_conn() as conn, conn.cursor() as cur:
        if domain:
            cur.execute(
                "SELECT id, source, chapter, body, embedding, "
                "page_no, paragraph_no, content_hash "
                "FROM chunks WHERE embedding IS NOT NULL AND source = %s "
                "AND (review_status IS NULL OR review_status != 'rejected')",
                (domain,),
            )
        else:
            cur.execute(
                "SELECT id, source, chapter, body, embedding, "
                "page_no, paragraph_no, content_hash "
                "FROM chunks WHERE embedding IS NOT NULL "
                "AND (review_status IS NULL OR review_status != 'rejected')"
            )
        rows = cur.fetchall()
    metas = [
        {
            "id": r[0], "source": r[1], "chapter": r[2], "text": r[3],
            "page_no": r[5], "paragraph_no": r[6], "content_hash": r[7],
        }
        for r in rows
    ]
    if rows:
        mat = np.array([r[4] for r in rows], dtype=np.float32)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        mat = mat / norms  # 归一化：之后点积即余弦相似度
    else:
        mat = np.zeros((0, 0), dtype=np.float32)
    _CACHES[domain] = (metas, mat)
    return metas, mat


def invalidate_cache(domain: str | None = None) -> None:
    """清除向量缓存。传 domain 只清指定书的；不传全清。"""
    if domain:
        _CACHES.pop(domain, None)
    else:
        _CACHES.clear()


def count() -> int:
    """库中已带向量的块数（给上层显示/判空用）。"""
    metas, _ = _load_matrix()
    return len(metas)


def search(query: str, chunks=None, top_k: int = TOP_K) -> list[dict]:
    """按语义相似度返回最相关的 top_k 块。chunks 参数仅为接口兼容，未使用。"""
    metas, mat = _load_matrix()
    if not metas:
        return []
    q = np.array(embed_one(query), dtype=np.float32)
    qn = np.linalg.norm(q) or 1.0
    q = q / qn
    sims = mat @ q
    idx = np.argsort(-sims)[:top_k]
    results = []
    for i in idx:
        r = dict(metas[i])
        r["score"] = round(float(sims[i]), 4)
        r["type"] = "vector"
        results.append(r)
    return results


if __name__ == "__main__":
    import sys

    qq = sys.argv[1] if len(sys.argv) > 1 else "黛玉葬花"
    hits = search(qq)
    print(f"查询：{qq}，命中 {len(hits)} 块")
    for h in hits:
        print(f"  [{h['source']} · {h['chapter'][:20]}] {h['text'][:40]}...")
