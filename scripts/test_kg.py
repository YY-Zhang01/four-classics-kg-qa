"""测试 KG 存储 + 融合检索"""
from kg.store import ensure_table, insert_triples, query_by_entity, count_triples
from retrieval.kg_search import is_relation_question, search as kg_search

# 1. 写入测试三元组
ensure_table()
test = [
    {"subject": "贾宝玉", "relation": "钟情", "object": "林黛玉"},
    {"subject": "林黛玉", "relation": "住在", "object": "潇湘馆"},
    {"subject": "贾母", "relation": "外祖母", "object": "林黛玉"},
    {"subject": "贾政", "relation": "父亲", "object": "贾宝玉"},
    {"subject": "王夫人", "relation": "母亲", "object": "贾宝玉"},
    {"subject": "贾宝玉", "relation": "丫鬟", "object": "晴雯"},
    {"subject": "林黛玉", "relation": "表妹", "object": "贾宝玉"},
    {"subject": "薛宝钗", "relation": "表姐", "object": "贾宝玉"},
]
n = insert_triples(test)
print(f"写入 {n} 条，库中共 {count_triples()} 条\n")

# 2. 查贾宝玉的关系
print("=== 贾宝玉的关系 ===")
for r in query_by_entity("贾宝玉"):
    print(f"  {r['subject']} --{r['relation']}--> {r['object']}")

# 3. 查两实体间关系
from kg.store import query_relation
print("\n=== 贾宝玉和林黛玉的关系 ===")
for r in query_relation("贾宝玉", "林黛玉"):
    print(f"  {r['subject']} --{r['relation']}--> {r['object']}")

# 4. 测试关系型判断
print("\n=== 问题类型判断 ===")
for q in ["贾宝玉和林黛玉什么关系", "林黛玉的父亲是谁", "黛玉葬花", "刘姥姥进大观园"]:
    print(f"  '{q}' → 关系型: {is_relation_question(q)}")

# 5. 测试 KG 检索
print("\n=== KG 检索 ===")
for q in ["贾宝玉和林黛玉什么关系", "黛玉的父亲是谁"]:
    hits = kg_search(q)
    print(f"  '{q}' → {len(hits)} 条:")
    for h in hits:
        print(f"    {h.get('subject','')} --{h.get('relation','')}--> {h.get('object','')}")
