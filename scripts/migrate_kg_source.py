"""KG 表迁移：加 source 列并给已有数据打标签。"""
import sys, os
sys.path.insert(0, '.')
from retrieval.db import get_conn

# 1. 加 source 列
with get_conn() as conn, conn.cursor() as cur:
    cur.execute("ALTER TABLE kg_triples ADD COLUMN IF NOT EXISTS source VARCHAR(50)")
    conn.commit()
    print("source 列已就绪")

# 2. 手动指定两本书的人物集合（不依赖 env 切换）
sanguo_names = {
    "刘备","关羽","张飞","诸葛亮","赵云","马超","黄忠",
    "曹操","司马懿","夏侯惇","夏侯渊","张辽","许褚","典韦","徐晃","曹仁",
    "孙权","周瑜","鲁肃","吕蒙","陆逊","甘宁","太史慈",
    "吕布","貂蝉","董卓","袁绍","袁术",
    "庞统","魏延","姜维","黄忠","马谡","关平","张苞",
    "刘禅","曹丕","曹植","孙策","华佗","祢衡",
}
hlm_names = {
    "贾宝玉","林黛玉","薛宝钗","王熙凤","贾母","贾政","王夫人","史湘云",
    "妙玉","李纨","秦可卿","贾元春","贾迎春","贾探春","贾惜春",
    "贾琏","贾珍","贾蓉","贾环","贾兰","薛姨妈","薛蟠",
    "晴雯","袭人","麝月","平儿","鸳鸯","紫鹃","刘姥姥",
    "贾雨村","尤二姐","尤三姐","巧姐","邢夫人","薛宝琴","林如海","秦钟",
    "尤氏","赵姨娘","金钏儿","雪雁","莺儿",
}

# 3. 打标签
with get_conn() as conn, conn.cursor() as cur:
    cur.execute("SELECT id, subject FROM kg_triples WHERE source IS NULL")
    rows = cur.fetchall()
    for tid, subj in rows:
        dom = None
        if subj in sanguo_names:
            dom = "三国演义"
        elif subj in hlm_names:
            dom = "红楼梦"
        if dom:
            cur.execute("UPDATE kg_triples SET source=%s WHERE id=%s", (dom, tid))
    conn.commit()
    print(f"已为 {len(rows)} 条打标签")

    # 统计
    cur.execute("SELECT source, count(*) FROM kg_triples GROUP BY source ORDER BY source")
    for row in cur.fetchall():
        print(f"  {row[0] or '(null)'}: {row[1]} 条")
