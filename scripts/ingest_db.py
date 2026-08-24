"""灌库脚本（P1）：把 chunks/*.json 的知识块灌进 PostgreSQL，并为每块算好语义向量。

流程：读切块 JSON → 分批调 embedding 算向量 → 写入 reddream 库的 chunks 表。
可重复执行：每次先清空表再灌，保证幂等。
"""
from __future__ import annotations

import time

from llm.embedding import embed_many
from retrieval.db import get_conn
from retrieval.search import load_chunks

BATCH = 32  # 每批算多少条向量


def main() -> None:
    chunks = load_chunks()
    total = len(chunks)
    print(f"待入库知识块：{total}")
    if total == 0:
        print("chunks/ 下没有知识块，先跑切块。")
        return

    t0 = time.time()
    with get_conn() as conn:
        # 不再 TRUNCATE——改为按 id 幂等写入，支持多书共存。
        # 如需清空旧数据，在管理后台 / pgAdmin 手动操作。

        done = 0
        for i in range(0, total, BATCH):
            batch = chunks[i : i + BATCH]
            vecs = embed_many([c["text"] for c in batch])
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks(id, source, chapter, body, embedding, "
                    "page_no, paragraph_no, content_hash) "
                    "VALUES(%s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "source = EXCLUDED.source, "
                    "chapter = EXCLUDED.chapter, "
                    "body = EXCLUDED.body, embedding = EXCLUDED.embedding, "
                    "page_no = EXCLUDED.page_no, "
                    "paragraph_no = EXCLUDED.paragraph_no, "
                    "content_hash = EXCLUDED.content_hash",
                    [
                        (c["id"], c["source"], c.get("chapter"), c["text"], v,
                         c.get("page_no"), c.get("paragraph_no"), c.get("content_hash"))
                        for c, v in zip(batch, vecs)
                    ],
                )
            conn.commit()
            done += len(batch)
            print(f"  已入库 {done}/{total}", flush=True)

    dim = len(vecs[0]) if vecs else 0
    print(f"完成。共 {done} 块，向量维度 {dim}，耗时 {time.time() - t0:.1f}s。")


if __name__ == "__main__":
    main()
