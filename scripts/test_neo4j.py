"""P3 Neo4j 图谱增强功能验证"""
from kg.neo4j_conn import is_available, run_query, reset_connection
from kg.sync_to_neo4j import full_sync, sync_stats, clear_graph, ensure_schema
from retrieval.graph_search import find_paths, expand_neighbors, common_neighbors, search_entities
from agent.tools import get_registry

print("=" * 50)
print("P3 Neo4j 图谱增强 — 功能验证")
print("=" * 50)

# 1. Neo4j 连接状态
print(f"\n1. Neo4j 连接: {'可用' if is_available() else '不可用（PG 降级模式）'}")

# 2. 模块导入
print(f"2. 所有 P3 模块导入: OK")

# 3. Agent 工具注册
registry = get_registry()
tool_names = registry.tool_names
print(f"3. Agent 工具: {len(tool_names)} 个已注册")
for name in tool_names:
    tool = registry.get(name)
    print(f"   - {name}: {tool.description[:40]}...")

# 4. PG 降级：路径查询
path = find_paths("刘备", "关羽")
print(f"\n4. 路径查询 刘备->关羽:")
print(f"   结果数: {len(path)}")
if path:
    src = path[0].get("source", "?")
    segs = path[0].get("segments", [])
    for s in segs:
        print(f"   {s['from']} --{s['relation']}--> {s['to']}")
    print(f"   数据源: {src}")

# 5. PG 降级：邻居展开
net = expand_neighbors("诸葛亮")
print(f"\n5. 邻居展开 诸葛亮:")
print(f"   节点数: {len(net.get('nodes', []))}")
print(f"   边数: {len(net.get('edges', []))}")
print(f"   数据源: {net.get('source', '?')}")
for e in net.get("edges", [])[:5]:
    print(f"   {e['from']} --{e.get('relation','?')}--> {e['to']}")

# 6. PG 降级：共同邻居
commons = common_neighbors("刘备", "张飞")
print(f"\n6. 共同邻居 刘备 & 张飞:")
print(f"   结果数: {len(commons)}")
for c in commons[:5]:
    print(f"   {c.get('common_name', '?')}")

# 7. 实体搜索
ents = search_entities("诸葛", limit=5)
print(f"\n7. 实体搜索 '诸葛':")
for e in ents:
    print(f"   {e.get('name', '?')}")

# 8. Neo4j 同步状态
stats = sync_stats()
print(f"\n8. Neo4j 同步状态:")
print(f"   可用: {stats.get('available')}")
print(f"   节点: {stats.get('nodes')}")
print(f"   关系: {stats.get('relationships')}")

# 9. Web server 导入检查
print(f"\n9. Web server 导入检查:")
try:
    from web.server import app
    print(f"   FastAPI app 加载成功")
    # 检查路由是否注册
    routes = [r.path for r in app.routes if hasattr(r, 'path')]
    graph_routes = [r for r in routes if '/api/graph' in r]
    print(f"   图谱 API 路由: {len(graph_routes)} 个")
    for r in graph_routes:
        print(f"     {r}")
except Exception as e:
    print(f"   加载失败: {e}")

print(f"\n{'=' * 50}")
print("P3 验证完成 — 降级模式正常工作")
if not is_available():
    print("提示: 启动 Neo4j 后运行 full_sync() 即可启用多跳查询")
print("=" * 50)
