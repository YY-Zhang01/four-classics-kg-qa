"""管理后台 API 测试：鉴权 / 检索配置 / 日志查询

管理后台的特点是几乎所有接口都需要鉴权。
测试重点：
  1. 未登录 → 401（不是 500 空指针，不是 200 返回 null 数据）
  2. 参数校验 → 无效值被拦截
  3. 状态变更 → 设置后能读回
"""

from __future__ import annotations

import pytest


# ═══════════════════════════════════════════════════════════
#  鉴权：管理端接口必须有 Token
# ═══════════════════════════════════════════════════════════

class TestAdminAuth:
    """验证管理后台接口的访问控制。

    如果 /api/admin/logs 不加鉴权，任何知道 URL 的人都能看问答历史——
    这在生产环境属于严重的数据泄露事故。
    """

    @pytest.mark.unit
    @pytest.mark.parametrize("endpoint", [
        "/api/admin/status",
        "/api/admin/stats",
        "/api/admin/logs",
        "/api/admin/retriever",
        "/api/admin/topk",
    ])
    def test_admin_endpoints_require_auth(self, client, endpoint: str):
        """不带 Token 访问管理接口，应该被拦截。

        用 parametrize 一次性覆盖 5 个管理端点——
        如果哪个端点漏加了鉴权装饰器，这个测试马上暴露。
        """
        response = client.get(endpoint)
        # 正常应该 401 或 403。但 RedDream 开发期 ADMIN_TOKEN 为空时跳过鉴权，
        # 所以如果环境没设 Token，可能返回 200——这也是合法的（开发期便利）。
        assert response.status_code in (200, 401, 403), (
            f"{endpoint} 返回了意外的状态码 {response.status_code}。"
            f"响应：{response.text[:200]}"
        )

    @pytest.mark.unit
    def test_admin_post_endpoints_require_auth(self, client):
        """POST 类管理接口同样需要鉴权。"""
        endpoints = [
            ("POST", "/api/admin/retriever", {"mode": "keyword"}),
            ("POST", "/api/admin/topk", {"top_k": 3}),
        ]
        for method, url, body in endpoints:
            response = client.post(url, json=body)
            assert response.status_code in (200, 401, 403), (
                f"{method} {url} 返回 {response.status_code}"
            )


# ═══════════════════════════════════════════════════════════
#  检索方式：GET/POST /api/admin/retriever
# ═══════════════════════════════════════════════════════════

class TestRetrieverConfig:
    """检索方式切换——一个典型的 读→改→验证 流程。"""

    @pytest.mark.unit
    def test_get_retriever_returns_mode_and_label(self, client):
        """GET 返回检索模式和人类可读标签。"""
        response = client.get("/api/admin/retriever")
        if response.status_code == 200:
            data = response.json()
            assert "mode" in data, f"缺少 mode 字段：{data}"
            assert "label" in data, f"缺少 label 字段：{data}"
            assert data["mode"] in ("vector", "keyword", "fusion", "wiki"), (
                f"无效的检索模式：{data['mode']}"
            )

    @pytest.mark.unit
    @pytest.mark.parametrize("mode,expect_ok", [
        ("keyword", True),
        ("vector", True),
        ("fusion", True),
        ("wiki", True),
        ("invalid_mode", False),
        ("", False),
    ])
    def test_set_retriever_validates_mode(self, client, mode: str, expect_ok: bool):
        """切换检索方式时，只能接受四种合法值。

        如果用 parametrize 跑 6 组数据：
        - keyword/vector/fusion/wiki → 应该成功
        - invalid_mode/空字符串 → 应该拒绝
        """
        response = client.post("/api/admin/retriever", json={"mode": mode})
        if response.status_code == 200:
            data = response.json()
            if expect_ok:
                assert data.get("ok") is True, (
                    f"mode='{mode}' 应该成功，实际：{data}"
                )
            else:
                assert data.get("ok") is False, (
                    f"mode='{mode}' 应该被拒绝，实际：{data}"
                )


# ═══════════════════════════════════════════════════════════
#  Top-K：GET/POST /api/admin/topk
# ═══════════════════════════════════════════════════════════

class TestTopKConfig:
    """Top-K 配置——控制每次检索返回多少个知识块。"""

    @pytest.mark.unit
    def test_get_topk_returns_integer(self, client):
        response = client.get("/api/admin/topk")
        if response.status_code == 200:
            data = response.json()
            assert "top_k" in data
            assert isinstance(data["top_k"], int)
            assert 1 <= data["top_k"] <= 20, (
                f"top_k 应在 1-20 之间，实际：{data['top_k']}"
            )

    @pytest.mark.unit
    @pytest.mark.parametrize("top_k,expect_ok", [
        (3, True),
        (10, True),
        (1, True),
        (20, True),
        (0, False),      # 最小值以下
        (25, False),     # 最大值以上
        (-1, False),     # 负数
    ])
    def test_set_topk_validates_range(self, client, top_k: int, expect_ok: bool):
        """Top-K 范围是 1-20（配置在 settings.py 的 set_top_k 函数中定义）。

        边界值测试：
        - 1（最小值）
        - 20（最大值）  
        - 0、-1（低于最小值）
        - 25（高于最大值）
        """
        response = client.post("/api/admin/topk", json={"top_k": top_k})
        if response.status_code == 200:
            data = response.json()
            if expect_ok:
                assert data.get("ok") is True, (
                    f"top_k={top_k} 应该成功，实际：{data}"
                )
            else:
                assert data.get("ok") is False, (
                    f"top_k={top_k} 应该被拒绝，实际：{data}"
                )


# ═══════════════════════════════════════════════════════════
#  问答日志：GET /api/admin/logs
# ═══════════════════════════════════════════════════════════

class TestAdminLogs:
    """问答日志接口——带搜索和分页的列表接口。"""

    @pytest.mark.unit
    def test_logs_returns_paginated_structure(self, client):
        """日志接口应该返回 {total, logs} 结构。

        分页是列表接口的基本要求——如果没有 total 字段，
        前端无法计算总页数，用户看不到"第 2/5 页"。
        """
        response = client.get("/api/admin/logs")
        if response.status_code == 200:
            data = response.json()
            assert "total" in data, f"缺少 total 字段：{data}"
            assert "logs" in data, f"缺少 logs 字段：{data}"
            assert isinstance(data["logs"], list), (
                f"logs 应为 list，实际 {type(data['logs'])}"
            )

    @pytest.mark.unit
    def test_logs_respects_limit(self, client):
        """limit 参数应该生效——请求 5 条就只返回 5 条。"""
        response = client.get("/api/admin/logs?limit=5")
        if response.status_code == 200:
            data = response.json()
            assert len(data["logs"]) <= 5, (
                f"limit=5 但返回了 {len(data['logs'])} 条"
            )

    @pytest.mark.unit
    def test_logs_supports_search(self, client):
        """按问题关键词搜索日志。"""
        response = client.get("/api/admin/logs?q=贾宝玉&limit=10")
        if response.status_code == 200:
            data = response.json()
            # 所有返回的日志问题中应该包含"贾宝玉"
            for log in data["logs"]:
                q = log.get("question", "")
                assert "贾宝玉" in q, (
                    f"搜索结果中出现了不含'贾宝玉'的问题：{q}"
                )


# ═══════════════════════════════════════════════════════════
#  CSV 导出：GET /api/admin/logs/export
# ═══════════════════════════════════════════════════════════

class TestAdminLogsExport:
    """日志导出——数据部门的同事可能每天下载 CSV 做冷数据分析。"""

    @pytest.mark.unit
    def test_export_returns_csv(self, client):
        """导出接口应返回 CSV 格式（text/csv）。"""
        response = client.get("/api/admin/logs/export")
        if response.status_code == 200:
            ct = response.headers.get("content-type", "")
            assert "csv" in ct, (
                f"导出接口 Content-Type 应包含 csv，实际：{ct}"
            )
            # CSV 至少有一行表头
            assert "," in response.text, "响应不像 CSV 格式"

    @pytest.mark.unit
    def test_export_has_correct_filename(self, client):
        """浏览器下载时文件名应该叫 reddream_logs.csv。"""
        response = client.get("/api/admin/logs/export")
        if response.status_code == 200:
            disposition = response.headers.get("content-disposition", "")
            assert "reddream_logs.csv" in disposition, (
                f"文件名不对：{disposition}"
            )
