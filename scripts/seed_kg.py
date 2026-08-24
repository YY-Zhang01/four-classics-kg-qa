"""扩展 KG 测试三元组"""
from kg.store import ensure_table, insert_triples, count_triples

ensure_table()

new_triples = [
    # ═══════ 贾府直系 ═══════
    {"subject": "贾母", "relation": "祖母", "object": "贾宝玉"},
    {"subject": "贾母", "relation": "母亲", "object": "贾政"},
    {"subject": "贾母", "relation": "母亲", "object": "贾赦"},
    {"subject": "贾母", "relation": "婆婆", "object": "王夫人"},
    {"subject": "王夫人", "relation": "母亲", "object": "贾宝玉"},
    {"subject": "王夫人", "relation": "母亲", "object": "贾元春"},
    {"subject": "贾政", "relation": "父亲", "object": "贾元春"},
    {"subject": "贾政", "relation": "父亲", "object": "贾探春"},
    {"subject": "赵姨娘", "relation": "母亲", "object": "贾探春"},
    {"subject": "赵姨娘", "relation": "母亲", "object": "贾环"},
    {"subject": "贾宝玉", "relation": "兄弟", "object": "贾环"},

    # ═══════ 四春姐妹 ═══════
    {"subject": "贾宝玉", "relation": "姐妹", "object": "贾元春"},
    {"subject": "贾宝玉", "relation": "姐妹", "object": "贾迎春"},
    {"subject": "贾宝玉", "relation": "姐妹", "object": "贾探春"},
    {"subject": "贾宝玉", "relation": "姐妹", "object": "贾惜春"},
    {"subject": "贾元春", "relation": "姐妹", "object": "贾迎春"},
    {"subject": "贾元春", "relation": "姐妹", "object": "贾探春"},
    {"subject": "贾元春", "relation": "姐妹", "object": "贾惜春"},

    # ═══════ 宁国府 ═══════
    {"subject": "贾珍", "relation": "夫妻", "object": "尤氏"},
    {"subject": "贾蓉", "relation": "夫妻", "object": "秦可卿"},
    {"subject": "贾珍", "relation": "公公", "object": "秦可卿"},

    # ═══════ 姻亲 ═══════
    {"subject": "贾赦", "relation": "父亲", "object": "贾琏"},
    {"subject": "贾琏", "relation": "夫妻", "object": "王熙凤"},
    {"subject": "林黛玉", "relation": "父亲", "object": "林如海"},
    {"subject": "薛姨妈", "relation": "母亲", "object": "薛宝钗"},
    {"subject": "薛蟠", "relation": "兄妹", "object": "薛宝钗"},

    # ═══════ 主仆 ═══════
    {"subject": "贾宝玉", "relation": "丫鬟", "object": "袭人"},
    {"subject": "贾宝玉", "relation": "丫鬟", "object": "晴雯"},
    {"subject": "林黛玉", "relation": "丫鬟", "object": "紫鹃"},
    {"subject": "林黛玉", "relation": "丫鬟", "object": "雪雁"},
    {"subject": "贾母", "relation": "丫鬟", "object": "鸳鸯"},
    {"subject": "王熙凤", "relation": "丫鬟", "object": "平儿"},
    {"subject": "王夫人", "relation": "丫鬟", "object": "金钏儿"},
    {"subject": "薛宝钗", "relation": "丫鬟", "object": "莺儿"},

    # ═══════ 居住地 ═══════
    {"subject": "贾宝玉", "relation": "住在", "object": "怡红院"},
    {"subject": "林黛玉", "relation": "住在", "object": "潇湘馆"},
    {"subject": "薛宝钗", "relation": "住在", "object": "蘅芜苑"},
    {"subject": "贾母", "relation": "住在", "object": "荣庆堂"},
    {"subject": "王夫人", "relation": "住在", "object": "荣禧堂"},
    {"subject": "李纨", "relation": "住在", "object": "稻香村"},

    # ═══════ 情感/社交 ═══════
    {"subject": "贾宝玉", "relation": "知己", "object": "林黛玉"},
    {"subject": "贾宝玉", "relation": "朋友", "object": "秦钟"},
    {"subject": "刘姥姥", "relation": "远亲", "object": "王熙凤"},
    {"subject": "贾雨村", "relation": "门客", "object": "贾政"},
    {"subject": "妙玉", "relation": "知己", "object": "贾宝玉"},
    {"subject": "史湘云", "relation": "表亲", "object": "贾宝玉"},

    # ═══════ 事件 ═══════
    {"subject": "贾宝玉", "relation": "梦游", "object": "太虚幻境"},
    {"subject": "林黛玉", "relation": "事件", "object": "葬花"},
    {"subject": "贾府", "relation": "被抄", "object": "锦衣军"},

    # ═══════ 人物属性 ═══════
    {"subject": "林如海", "relation": "官职", "object": "巡盐御史"},
    {"subject": "林如海", "relation": "出身", "object": "前科探花"},
]

n = insert_triples(new_triples)
print(f"新增 {n} 条，库中共 {count_triples()} 条三元组")
