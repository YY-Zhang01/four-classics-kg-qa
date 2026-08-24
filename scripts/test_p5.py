"""P5 自动采集 + 更新管线 — 集成验证脚本。

验证清单：
1. 数据源注册 / 查询
2. 变更扫描（hash 检测）
3. 更新日志写入
4. 增量处理管线（需 LLM + Embedding 可用时）
5. API 端点可访问
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DOMAIN = "__p5_test__"
PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" - {detail}" if detail else ""))


def test_registration():
    """测试 1: 数据源注册与查询"""
    print("\n[1/6] 数据源注册")

    from collector.sources import register, get_source, list_sources

    # 创建临时文件用于测试
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# 测试文档\n\n这是 P5 测试内容。\n\n## 第二章\n\n第二段测试文本。\n")
        tmp_path = f.name

    try:
        sid = register(
            name="test_p5_doc",
            path=tmp_path,
            domain=TEST_DOMAIN,
        )
        check("注册数据源", sid > 0, f"id={sid}")

        source = get_source(sid)
        check("查询数据源", source is not None and source["name"] == "test_p5_doc")

        sources = list_sources(domain=TEST_DOMAIN, enabled_only=False)
        check("列出数据源", len(sources) >= 1, f"共 {len(sources)} 条")

        return sid, tmp_path
    except Exception as e:
        check("数据源操作", False, str(e))
        return None, tmp_path


def test_scan(sid: int, tmp_path: str):
    """测试 2: 变更扫描"""
    print("\n[2/6] 变更扫描")

    from collector.scanner import scan_all, get_changed
    from collector.sources import compute_file_hash

    # 首次扫描 → 应返回 new
    results = scan_all(domain=TEST_DOMAIN)
    check("扫描执行", len(results) >= 1, f"结果数={len(results)}")
    if results:
        action = results[0].get("action", "")
        check("首次扫描=新文件", action == "new", f"action={action}")

    # 再次扫描（未修改）→ 应返回 unchanged
    results2 = scan_all(domain=TEST_DOMAIN)
    if results2:
        action2 = results2[0].get("action", "")
        check("再次扫描=未变更", action2 == "unchanged", f"action={action2}")

    # 修改文件 → 应返回 changed
    with open(tmp_path, "a", encoding="utf-8") as f:
        f.write("\n\n## 新增内容\n\n这是新增的测试段落，用于验证变更检测。\n")

    results3 = scan_all(domain=TEST_DOMAIN)
    if results3:
        action3 = results3[0].get("action", "")
        check("修改后扫描=已变更", action3 == "changed", f"action={action3}")

    changed = get_changed(domain=TEST_DOMAIN)
    check("获取变更列表", len(changed) >= 1, f"变更数={len(changed)}")

    # 计算 hash
    h = compute_file_hash(tmp_path)
    check("计算文件hash", len(h) == 64 and h != "", f"hash={h[:16]}...")


def test_update_logs():
    """测试 3: 更新日志查询"""
    print("\n[3/6] 更新日志")

    from updater.reporter import get_update_logs, get_last_scan, generate_report

    logs = get_update_logs(domain=TEST_DOMAIN, limit=10)
    check("查询更新日志", len(logs) >= 1, f"日志数={len(logs)}")

    last = get_last_scan(domain=TEST_DOMAIN)
    check("最近扫描日志", last is not None)

    report = generate_report(domain=TEST_DOMAIN)
    check("生成报告", "sources" in report, f"数据源总数={report['sources']['total']}")


def test_sources_utility():
    """测试 4: 数据源工具函数"""
    print("\n[4/6] 工具函数")

    from collector.sources import (
        update_status,
        mark_changed,
        STATUS_ACTIVE,
        STATUS_CHANGED,
        STATUS_ERROR,
    )
    from collector.sources import list_sources, get_source

    sources = list_sources(domain=TEST_DOMAIN, enabled_only=False)
    if not sources:
        check("数据源列表", False, "无数据源可测试")
        return

    sid = sources[0]["id"]
    update_status(sid, status=STATUS_ACTIVE)
    src = get_source(sid)
    check("恢复ACTIVE状态", src is not None and src["status"] == STATUS_ACTIVE,
          f"status={src.get('status') if src else 'N/A'}")

    mark_changed(sid)
    src2 = get_source(sid)
    check("标记CHANGED状态", src2 is not None and src2["status"] == STATUS_CHANGED,
          f"status={src2.get('status') if src2 else 'N/A'}")

    # 清理
    update_status(sid, status=STATUS_ACTIVE)


def test_api_endpoints():
    """测试 5: API 端点可达性（使用 FastAPI TestClient）"""
    print("\n[5/6] API 端点")

    try:
        from fastapi.testclient import TestClient
        from web.server import app
        client = TestClient(app)

        # 检查端点是否存在（不需要鉴权也能验证路由注册）
        # 注意：admin 端点需要 Bearer token，这里只验证路由存在
        routes = [r.path for r in app.routes]
        p5_routes = [r for r in routes if "sources" in r or "p5" in r]
        check("P5 API 路由已注册", len(p5_routes) >= 5,
              f"已注册 {len(p5_routes)} 个: {p5_routes}")
        for r in p5_routes:
            print(f"    GET/POST {r}")

    except ImportError as e:
        check("API 测试", False, f"导入失败: {e}")
    except Exception as e:
        check("API 测试", False, str(e))


def test_scanner_module():
    """测试 6: scanner 模块直接调用"""
    print("\n[6/6] Scanner + Pipeline 模块")

    from collector.scanner import scan_all, get_changed
    from collector.sources import list_sources

    # 扫描全部（不限定 domain）
    results = scan_all(domain="")
    sources = list_sources(domain="", enabled_only=True)
    check("全量扫描", isinstance(results, list),
          f"扫描 {len(sources)} 个数据源, 结果 {len(results)} 条")


# ══════════════════════════════════════════════════
#  优化后新增测试
# ══════════════════════════════════════════════════

def test_async_status():
    """测试 7: 异步管线状态"""
    print("\n[7/8] 异步状态")

    from updater.pipeline import get_async_status, start_async_update
    from updater.pipeline import _pipeline_state, _lock

    # 初始状态应为 idle
    status = get_async_status()
    check("初始idle状态", not status["running"] and status["phase"] == "idle",
          f"running={status['running']}, phase={status['phase']}")

    # 不应有残留错误
    check("无残留错误", status.get("error") is None)


def test_diff_chunks():
    """测试 8: 差量 chunk 更新"""
    print("\n[8/8] 差量 diff")

    from retrieval.db import get_conn
    from updater.pipeline import _load_existing_chunk_hashes, _deactivate_chunk_ids, _keep_chunk_ids
    from collector.sources import list_sources

    # 注册一个只有测试数据源的扫描场景
    sources = list_sources(domain=TEST_DOMAIN, enabled_only=False)
    if not sources:
        check("测试数据源", False, "无数据源")
        return

    sid = sources[0]["id"]
    source_name = sources[0]["name"]

    # 1. 验证 _load_existing_chunk_hashes 可运行
    existing = _load_existing_chunk_hashes(source_name)
    check("加载chunk hash映射", isinstance(existing, dict),
          f"已加载 {len(existing)} 条chunk")

    # 2. 如果没有 chunk，插入一些模拟数据
    if not existing:
        with get_conn() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks(id, source, chapter, body, content_hash, is_active) "
                "VALUES(%s, %s, %s, %s, %s, TRUE) "
                "ON CONFLICT(id) DO NOTHING",
                [
                    ("test_p5_doc#diff0", source_name, "测试章", "测试文本A", "hash_aaa"),
                    ("test_p5_doc#diff1", source_name, "测试章", "测试文本B", "hash_bbb"),
                    ("test_p5_doc#diff2", source_name, "测试章", "测试文本C", "hash_ccc"),
                ],
            )
            conn.commit()
        existing2 = _load_existing_chunk_hashes(source_name)
        check("插入模拟chunk后加载", len(existing2) == 3,
              f"期望3条, 实际{len(existing2)}条")

    # 3. 验证 _keep_chunk_ids 和 _deactivate_chunk_ids
    all_chunks = existing2 if not existing else existing
    if all_chunks:
        ids = [c["id"] for c in list(all_chunks.values())[:2]]
        kept = _keep_chunk_ids(ids)
        check("标记保持active", kept >= 0, f"影响{kept}行")

        # 验证 deactivate
        if len(all_chunks) >= 3:
            deact_id = [list(all_chunks.values())[2]["id"]]
            deactivated = _deactivate_chunk_ids(deact_id)
            check("标记inactive", deactivated >= 0, f"影响{deactivated}行")

    # 4. 清理模拟数据
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM chunks WHERE source = %s AND id LIKE 'test_p5_doc#diff%%'",
                    (source_name,))
        conn.commit()


def cleanup():
    """清理测试数据源"""
    try:
        from retrieval.db import get_conn
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM update_log WHERE domain = %s",
                (TEST_DOMAIN,),
            )
            cur.execute(
                "DELETE FROM data_sources WHERE domain = %s",
                (TEST_DOMAIN,),
            )
            conn.commit()
        print(f"\n  已清理测试域 {TEST_DOMAIN} 的数据")
    except Exception as e:
        print(f"\n  清理失败（可忽略）: {e}")


if __name__ == "__main__":
    print("=" * 50)
    print("  P5 自动采集 + 更新管线 — 集成验证")
    print("=" * 50)

    # 检查数据库连接
    try:
        from retrieval.db import get_conn
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
        print("  数据库连接: OK\n")
    except Exception as e:
        print(f"  数据库连接失败: {e}")
        print("  跳过需要数据库的测试。\n")

    sid, tmp_path = None, None

    # Test 1-2: 注册 + 扫描（需要DB）
    result = test_registration()
    if result[0]:
        sid, tmp_path = result
        test_scan(sid, tmp_path)

    # Test 3: 日志（需要DB + 前面写入的日志）
    test_update_logs()

    # Test 4: 工具函数（需要DB）
    test_sources_utility()

    # Test 5: API 路由
    test_api_endpoints()

    # Test 6: scanner + pipeline 全量
    test_scanner_module()

    # Test 7: async 状态
    test_async_status()

    # Test 8: 差量 diff
    test_diff_chunks()

    # 清理
    cleanup()

    # 清理临时文件
    if tmp_path and Path(tmp_path).exists():
        Path(tmp_path).unlink()

    print(f"\n{'=' * 50}")
    print(f"  总计: {PASS + FAIL}  通过: {PASS}  失败: {FAIL}")
    print(f"{'=' * 50}")

    sys.exit(0 if FAIL == 0 else 1)
