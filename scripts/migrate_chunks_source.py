"""给 chunks 表加 source 列并打标签。"""
import sys; sys.path.insert(0, '.')
from retrieval.db import get_conn

with get_conn() as conn, conn.cursor() as cur:
    # 1. 加列
    cur.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS source VARCHAR(50)")
    conn.commit()
    print("chunks.source 列已就绪")

    # 2. 给已有数据打标签：根据 id 前缀判断
    cur.execute("UPDATE chunks SET source = '三国演义' WHERE id LIKE 'sg_%'")
    cur.execute("UPDATE chunks SET source = '红楼梦' WHERE id LIKE 'hlm_%' OR (source IS NULL AND id NOT LIKE 'sg_%')")
    conn.commit()

    # 3. 统计
    cur.execute("SELECT source, count(*) FROM chunks GROUP BY source ORDER BY source")
    for r in cur.fetchall():
        print(f"  {r[0] or '(null)'}: {r[1]} 块")
