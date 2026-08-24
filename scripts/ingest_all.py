"""灌库：指定 domain，按 ON CONFLICT 幂等写入。"""
import sys, time, json
sys.path.insert(0, '.')
from config.settings import switch_domain
from retrieval.db import get_conn
from llm.embedding import embed_many

BATCH = 32

def ingest_domain(domain: str):
    # 切换到目标 domain（让 load_chunks 只加载对应文件）
    switch_domain(domain)
    from retrieval.search import load_chunks
    chunks = load_chunks()
    if not chunks:
        print(f"[{domain}] 无数据，跳过")
        return
    print(f"[{domain}] {len(chunks)} 块，开始算向量...")
    t0 = time.time()
    with get_conn() as conn:
        done = 0
        for i in range(0, len(chunks), BATCH):
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
                    [(c["id"], c["source"], c.get("chapter"), c["text"], v,
                      c.get("page_no"), c.get("paragraph_no"), c.get("content_hash"))
                     for c, v in zip(batch, vecs)],
                )
            conn.commit()
            done += len(batch)
            print(f"  [{domain}] {done}/{len(chunks)}")
    print(f"[{domain}] 完成：{done} 块，{time.time()-t0:.0f}s")

if __name__ == "__main__":
    for dom in ["红楼梦", "三国演义"]:
        ingest_domain(dom)
