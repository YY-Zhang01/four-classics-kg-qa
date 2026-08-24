"""单书灌库：chunks + KG 三数元组 一并入 PostgreSQL。

用法：python scripts/ingest_one.py 水浒传
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from llm.embedding import embed_many
from retrieval.db import get_conn

BOOK = sys.argv[1]
CHUNK_FILE = ROOT / "chunks" / f"{BOOK}.json"
KG_FILE = ROOT / "data" / f"kg_{BOOK}.json"
BATCH = 32


def ingest_chunks():
    if not CHUNK_FILE.exists():
        print(f"[跳过] chunks 文件不存在: {CHUNK_FILE}")
        return
    chunks = json.loads(CHUNK_FILE.read_text(encoding="utf-8"))
    total = len(chunks)
    print(f"[chunks] {total} 块 → PostgreSQL (含向量)")
    with get_conn() as conn:
        done = 0
        for i in range(0, total, BATCH):
            batch = chunks[i : i + BATCH]
            vecs = embed_many([c["text"] for c in batch])
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks(id, source, chapter, body, embedding) "
                    "VALUES(%s, %s, %s, %s, %s) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "source = EXCLUDED.source, "
                    "body = EXCLUDED.body, embedding = EXCLUDED.embedding",
                    [(c["id"], c["source"], c.get("chapter"), c["text"], v)
                     for c, v in zip(batch, vecs)],
                )
            conn.commit()
            done += len(batch)
            print(f"  chunks {done}/{total}", flush=True)
    print(f"  完成。{done} 块入库。")


def ingest_kg():
    if not KG_FILE.exists():
        print(f"[跳过] KG 文件不存在: {KG_FILE}")
        return
    triples = json.loads(KG_FILE.read_text(encoding="utf-8"))
    print(f"[KG] {len(triples)} 条三元组 → PostgreSQL")
    with get_conn() as conn, conn.cursor() as cur:
        inserted = 0
        for subj, rel, obj in triples:
            cur.execute(
                "INSERT INTO kg_triples(subject, relation, object, source) "
                "VALUES(%s, %s, %s, %s) "
                "ON CONFLICT(subject, relation, object) DO NOTHING",
                (subj, rel, obj, BOOK),
            )
            inserted += cur.rowcount
        conn.commit()
    print(f"  完成。新增 {inserted} 条，跳过重复。")


if __name__ == "__main__":
    print(f"=== {BOOK} 灌库 ===\n")
    ingest_chunks()
    print()
    ingest_kg()
    print(f"\n全部完成。")
