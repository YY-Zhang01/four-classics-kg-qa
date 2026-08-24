"""三国演义 KG 种子数据灌库"""
from kg.store import ensure_table, insert_triples, count_triples
from scripts.seed_kg_sanguo import TRIPLES

ensure_table()
before = count_triples()
insert_triples(TRIPLES)
after = count_triples()
print(f"三国 KG 灌库完成：{before} → {after}（新增 {after - before} 条）")
