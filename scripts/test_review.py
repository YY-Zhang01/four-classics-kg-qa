"""P4 审核模块功能验证"""
from review import get_stats, query_queue, approve, reject, get_history
from config.settings import get_admin_domain

domain = get_admin_domain()
print(f"Domain: {domain}")

# 1. 统计
s = get_stats(domain)
print(f"Pending: chunks={s.pending_chunks} kg={s.pending_kg} wiki={s.pending_wiki} total={s.total_pending}")

# 2. 队列
items = query_queue(domain, limit=5)
print(f"Queue items: {len(items)}")
for it in items[:3]:
    print(f"  [{it.target_type}] {it.title[:50]} (conf={it.confidence:.0%})")

# 3. 历史
hist = get_history(limit=3)
print(f"Review history: {len(hist)} records")
for h in hist[:3]:
    print(f"  {h['action']} {h['target_type']}#{h['target_id']} at {h['created_at'][:19]}")

# 4. 测试 approve/reject (选第一个 pending item)
if items:
    test_item = items[0]
    print(f"\nTesting approve on: [{test_item.target_type}] {test_item.title[:30]}")
    ok = approve(test_item.target_type, test_item.target_id)
    print(f"  approve -> {ok}")
    
    # 再 reject 回来
    ok2 = reject(test_item.target_type, test_item.target_id, reason="test rollback")
    print(f"  reject -> {ok2}")

    # 确认历史有记录
    hist2 = get_history(limit=5)
    print(f"  history after test: {len(hist2)} records")
    for h in hist2[:2]:
        print(f"    {h['action']} {h['target_type']}#{h['target_id']} ({h.get('reason','')[:30]})")

print("\nDone.")
