"""三国演义知识图谱种子数据（人物关系 + 归属）

三国人物关系复杂，这里只覆盖最核心的几组关系。
"""
TRIPLES = [
    # ── 蜀汉 ──
    {"subject": "刘备", "relation": "结义兄弟", "object": "关羽"},
    {"subject": "刘备", "relation": "结义兄弟", "object": "张飞"},
    {"subject": "关羽", "relation": "结义兄弟", "object": "张飞"},
    {"subject": "刘备", "relation": "君主", "object": "诸葛亮"},
    {"subject": "诸葛亮", "relation": "军师", "object": "刘备"},
    {"subject": "刘备", "relation": "君主", "object": "赵云"},
    {"subject": "刘备", "relation": "君主", "object": "马超"},
    {"subject": "刘备", "relation": "君主", "object": "黄忠"},
    {"subject": "刘备", "relation": "君主", "object": "魏延"},
    {"subject": "诸葛亮", "relation": "学生", "object": "姜维"},
    {"subject": "刘备", "relation": "儿子", "object": "刘禅"},
    {"subject": "张飞", "relation": "儿子", "object": "张苞"},

    # ── 曹魏 ──
    {"subject": "曹操", "relation": "君主", "object": "司马懿"},
    {"subject": "曹操", "relation": "君主", "object": "夏侯惇"},
    {"subject": "曹操", "relation": "君主", "object": "夏侯渊"},
    {"subject": "曹操", "relation": "君主", "object": "张辽"},
    {"subject": "曹操", "relation": "君主", "object": "许褚"},
    {"subject": "曹操", "relation": "君主", "object": "典韦"},
    {"subject": "曹操", "relation": "君主", "object": "徐晃"},
    {"subject": "曹操", "relation": "君主", "object": "曹仁"},
    {"subject": "曹操", "relation": "儿子", "object": "曹丕"},
    {"subject": "曹操", "relation": "儿子", "object": "曹植"},
    {"subject": "曹丕", "relation": "兄弟", "object": "曹植"},

    # ── 东吴 ──
    {"subject": "孙权", "relation": "君主", "object": "周瑜"},
    {"subject": "孙权", "relation": "君主", "object": "鲁肃"},
    {"subject": "孙权", "relation": "君主", "object": "吕蒙"},
    {"subject": "孙权", "relation": "君主", "object": "陆逊"},
    {"subject": "孙权", "relation": "君主", "object": "甘宁"},
    {"subject": "孙权", "relation": "君主", "object": "太史慈"},
    {"subject": "孙策", "relation": "兄弟", "object": "孙权"},

    # ── 跨势力关系 ──
    {"subject": "诸葛亮", "relation": "对手", "object": "司马懿"},
    {"subject": "诸葛亮", "relation": "对手", "object": "周瑜"},
    {"subject": "关羽", "relation": "对手", "object": "吕布"},
    {"subject": "曹操", "relation": "对手", "object": "刘备"},
    {"subject": "曹操", "relation": "对手", "object": "孙权"},
    {"subject": "刘备", "relation": "对手", "object": "孙权"},
    {"subject": "吕布", "relation": "义父", "object": "董卓"},
    {"subject": "董卓", "relation": "义子", "object": "吕布"},
    {"subject": "吕布", "relation": "配偶", "object": "貂蝉"},

    # ── 其他 ──
    {"subject": "袁绍", "relation": "兄弟", "object": "袁术"},
    {"subject": "诸葛亮", "relation": "同学", "object": "庞统"},
]
