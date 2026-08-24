"""证据完整性自检脚本（P0）

检查项：
1. chunks 表中有多少条缺 content_hash
2. chunks 表中有多少条缺 page_no
3. kg_triples 表中有多少条缺 confidence / source_chunk_id
4. 低置信度（<0.5）的三元组占比
5. review_status 分布统计

用法：python -m scripts.selfcheck_evidence
"""
from __future__ import annotations

from retrieval.db import get_conn


def check_chunks() -> dict:
    """检查 chunks 表的证据完整性。"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM chunks")
        total = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM chunks WHERE content_hash IS NULL")
        missing_hash = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM chunks WHERE page_no IS NULL")
        missing_page = cur.fetchone()[0]

        cur.execute("SELECT review_status, count(*) FROM chunks GROUP BY review_status ORDER BY count(*) DESC")
        status_dist = {r[0] or "NULL": r[1] for r in cur.fetchall()}

    return {
        "total": total,
        "missing_hash": missing_hash,
        "missing_page": missing_page,
        "hash_coverage": f"{(total - missing_hash) / total * 100:.1f}%" if total else "N/A",
        "page_coverage": f"{(total - missing_page) / total * 100:.1f}%" if total else "N/A",
        "status_distribution": status_dist,
    }


def check_kg() -> dict:
    """检查 kg_triples 表的证据完整性。"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM kg_triples")
        total = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM kg_triples WHERE confidence IS NULL OR confidence = 0.0")
        missing_conf = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM kg_triples WHERE source_chunk_id IS NULL")
        missing_chunk = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM kg_triples WHERE confidence < 0.5 AND confidence > 0")
        low_conf = cur.fetchone()[0]

        cur.execute("SELECT review_status, count(*) FROM kg_triples GROUP BY review_status ORDER BY count(*) DESC")
        status_dist = {r[0] or "NULL": r[1] for r in cur.fetchall()}

    return {
        "total": total,
        "missing_confidence": missing_conf,
        "missing_source_chunk": missing_chunk,
        "low_confidence_count": low_conf,
        "low_confidence_pct": f"{low_conf / total * 100:.1f}%" if total else "N/A",
        "status_distribution": status_dist,
    }


def main():
    print("=" * 50)
    print("  RedDream P0 · 证据完整性自检")
    print("=" * 50)

    print("\n── chunks 表 ──")
    c = check_chunks()
    print(f"  总块数:        {c['total']}")
    print(f"  缺 content_hash: {c['missing_hash']}  ({c['hash_coverage']} 覆盖率)")
    print(f"  缺 page_no:      {c['missing_page']}  ({c['page_coverage']} 覆盖率)")
    print(f"  review_status 分布: {c['status_distribution']}")

    print("\n── kg_triples 表 ──")
    k = check_kg()
    print(f"  总三元组:          {k['total']}")
    print(f"  缺 confidence:     {k['missing_confidence']}")
    print(f"  缺 source_chunk:   {k['missing_source_chunk']}")
    print(f"  低置信度 (<0.5):    {k['low_confidence_count']}  ({k['low_confidence_pct']})")
    print(f"  review_status 分布: {k['status_distribution']}")

    # 综合评级
    print("\n── 综合评级 ──")
    issues = []
    if c["missing_hash"] > 0:
        issues.append(f"{c['missing_hash']} 块缺 hash")
    if k["missing_confidence"] > 0:
        issues.append(f"{k['missing_confidence']} 条三元组缺置信度")
    if k["low_confidence_count"] > 0:
        issues.append(f"{k['low_confidence_count']} 条低置信度待审")

    if not issues:
        print("  [OK] 证据完整，无异常")
    else:
        print(f"  [!] {len(issues)} 项待处理：")
        for issue in issues:
            print(f"     - {issue}")
        print("\n  修复建议：")
        print("     python -m kb_builder.enricher          # 补全 chunk 证据字段")
        print("     python -m kg.extract                   # 重新抽取三元组（带置信度）")


if __name__ == "__main__":
    main()
