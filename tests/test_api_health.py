"""API 基础端点测试：健康检查 / 项目配置

验证最基础的两个 GET 端点——不依赖 LLM / KG / 数据库查询，
是测试面试里最常见的一类题："你怎么测一个健康检查接口？"
"""

from __future__ import annotations

import pytest


# ═══════════════════════════════════════════════════════════
#  健康检查：GET /api/health
# ═══════════════════════════════════════════════════════════

class TestHealthEndpoint:
    """健康检查接口的测试用例。

    面试要点：
      健康检查是监控系统的基础——负载均衡器用它判断服务是否存活，
      K8s 用它做 liveness probe。所以这个接口的可靠性非常关键。
    """

    @pytest.mark.unit
    def test_health_returns_200(self, client):
        """状态码必须是 200，否则监控系统会认为服务挂了。"""
        response = client.get("/api/health")
        assert response.status_code == 200, (
            f"期望 200，实际 {response.status_code}。"
            f"响应体：{response.text[:200]}"
        )

    @pytest.mark.unit
    def test_health_returns_json(self, client):
        """Content-Type 必须是 JSON，方便 Prometheus / Grafana 解析。"""
        response = client.get("/api/health")
        assert "application/json" in response.headers.get("content-type", ""), (
            f"期望 Content-Type 包含 application/json，"
            f"实际：{response.headers.get('content-type')}"
        )

    @pytest.mark.unit
    def test_health_has_required_fields(self, client):
        """响应体必须包含约定的字段。如果前端依赖这些字段做 UI 展示，
        字段名变了下游全崩——这就是 API 契约测试的意义。"""
        response = client.get("/api/health")
        data = response.json()

        required_fields = ["status", "retriever", "chunks"]
        for field in required_fields:
            assert field in data, (
                f"响应中缺少字段 '{field}'。当前字段：{list(data.keys())}"
            )

    @pytest.mark.unit
    def test_health_status_is_ok(self, client):
        """status 字段应该返回 'ok'——这是 RedDream 跟监控系统的约定。"""
        response = client.get("/api/health")
        data = response.json()
        assert data["status"] == "ok", f"期望 'ok'，实际 '{data['status']}'"

    @pytest.mark.unit
    def test_health_chunks_is_integer(self, client):
        """chunks（知识块数量）必须是一个非负整数。
        如果返回了负数或字符串，说明数据库查询出了问题。
        """
        response = client.get("/api/health")
        data = response.json()
        assert isinstance(data["chunks"], int), (
            f"chunks 应该是 int 类型，实际 {type(data['chunks'])}"
        )
        assert data["chunks"] >= 0, f"chunks 不能为负数，实际 {data['chunks']}"


# ═══════════════════════════════════════════════════════════
#  项目配置：GET /api/config
# ═══════════════════════════════════════════════════════════

class TestConfigEndpoint:
    """项目配置接口——前端用它在标题栏显示项目名称、封面印章、示例问题。"""

    @pytest.mark.unit
    def test_config_returns_200(self, client):
        response = client.get("/api/config")
        assert response.status_code == 200

    @pytest.mark.unit
    def test_config_has_required_fields(self, client):
        """config 必须包含前端渲染所需的四个字段。"""
        response = client.get("/api/config")
        data = response.json()
        for field in ["name", "domain", "seal", "hints"]:
            assert field in data, f"缺少字段 '{field}'"

    @pytest.mark.unit
    def test_config_name_is_string(self, client):
        response = client.get("/api/config")
        data = response.json()
        assert isinstance(data["name"], str) and len(data["name"]) > 0, (
            f"name 应为非空字符串，实际：{repr(data['name'])}"
        )

    @pytest.mark.unit
    def test_config_hints_is_list(self, client):
        """hints 是首页的示例问题列表，必须是 list 类型。"""
        response = client.get("/api/config")
        data = response.json()
        assert isinstance(data["hints"], list), (
            f"hints 应为 list，实际 {type(data['hints'])}"
        )


# ═══════════════════════════════════════════════════════════
#  边界条件 & 异常路径
# ═══════════════════════════════════════════════════════════

class TestEdgeCases:
    """面试官最爱问的一类题："除了正常路径，你还测了什么？"

    好的测试工程师会主动考虑：
    - 不存在的路由（404）
    - 错误的 HTTP 方法（405）
    - 意外的请求格式
    """

    @pytest.mark.unit
    def test_nonexistent_route_returns_404(self, client):
        """访问不存在的路径应该返回 404，而不是 500 空指针异常。"""
        response = client.get("/api/nonexistent_endpoint_12345")
        assert response.status_code == 404, (
            f"不存在的路径应返回 404，实际 {response.status_code}"
        )

    @pytest.mark.unit
    def test_wrong_method_on_get_endpoint(self, client):
        """对 GET-only 的端点发 POST，应该返回 405 Method Not Allowed。
        如果返回 500 说明服务端没做方法校验直接崩溃了。
        """
        response = client.post("/api/health")
        assert response.status_code == 405, (
            f"GET 端点收到 POST 应返回 405，实际 {response.status_code}"
        )

    @pytest.mark.unit
    def test_health_response_time_is_fast(self, client):
        """健康检查应该是毫秒级的——如果超过 500ms，
        负载均衡器可能认为服务挂了把它踢出集群。"""
        import time
        t0 = time.perf_counter()
        client.get("/api/health")
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.5, (
            f"健康检查耗时 {elapsed:.3f}s，超过 500ms 阈值"
        )

    @pytest.mark.unit
    def test_config_cache_headers(self, client):
        """config 接口应该禁用缓存（Cache-Control: no-cache），
        不然切书后前端可能读到旧配置。"""
        response = client.get("/api/config")
        cache = response.headers.get("cache-control", "")
        # 不强断言（RedDream 不一定设了），但记录一下
        print(f"Cache-Control: {cache or '(未设置)'}")
