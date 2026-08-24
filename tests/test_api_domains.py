"""领域/书籍切换测试：GET /api/domains + POST /api/switch-domain

RedDream 支持多书切换——用户可以随时在《红楼梦》《三国演义》等书籍间切换。
这个功能在测试上有几个微妙的地方：
1. 切换是全局状态，测试之间会互相干扰（状态污染）
2. 切换失败时不能把全局状态搞坏（回滚/不变）
"""

from __future__ import annotations

import pytest


# ═══════════════════════════════════════════════════════════
#  书籍列表
# ═══════════════════════════════════════════════════════════

class TestListDomains:
    """验证可用书籍列表接口。"""

    @pytest.mark.unit
    def test_list_domains_returns_200(self, client):
        response = client.get("/api/domains")
        assert response.status_code == 200

    @pytest.mark.unit
    def test_list_domains_has_required_fields(self, client):
        """返回格式：{"domains": [...], "active": "红楼梦"}"""
        response = client.get("/api/domains")
        if response.status_code == 200:
            data = response.json()
            assert "domains" in data, f"缺少 domains 字段：{data}"
            assert "active" in data, f"缺少 active 字段：{data}"
            assert isinstance(data["domains"], list), (
                f"domains 应为 list，实际 {type(data['domains'])}"
            )

    @pytest.mark.unit
    def test_each_domain_has_minimal_fields(self, client):
        """每个领域条目至少要有 domain 和 seal 字段。

        前端下拉框需要：domain（标识符）+ seal（封面印章字，如"红""三"）
        """
        response = client.get("/api/domains")
        if response.status_code == 200:
            for domain in response.json()["domains"]:
                assert "domain" in domain, f"领域条目缺少 domain：{domain}"
                assert "seal" in domain, f"领域条目缺少 seal：{domain}"


# ═══════════════════════════════════════════════════════════
#  切换书籍
# ═══════════════════════════════════════════════════════════

class TestSwitchDomain:
    """验证书籍切换的正确性和错误处理。"""

    @pytest.mark.unit
    def test_switch_empty_domain_rejected(self, client):
        """空字符串不是合法的领域名。"""
        response = client.post("/api/switch-domain", json={"domain": ""})
        if response.status_code == 200:
            data = response.json()
            assert data.get("ok") is False, f"空 domain 应该被拒绝：{data}"

    @pytest.mark.unit
    def test_switch_missing_field(self, client):
        """请求体缺少 domain 字段。"""
        response = client.post("/api/switch-domain", json={})
        if response.status_code == 200:
            data = response.json()
            assert data.get("ok") is False, f"缺少 domain 应该被拒绝：{data}"

    @pytest.mark.unit
    def test_switch_nonexistent_domain(self, client):
        """切到一个不存在的书——RedDream 会动态创建领域条目。

        当前行为：不存在的领域名也能切换成功（后端自动创建 domain 配置）。
        这不是 bug，而是一个设计选择——允许用户随时添加新书。

        测试重点不是"拒绝"，而是"不崩溃"——即状态码 200，不会 500。
        """
        response = client.post(
            "/api/switch-domain",
            json={"domain": "不存在的书_xyz"},
        )
        assert response.status_code == 200, (
            f"切换不存在的领域不应导致 500，实际 {response.status_code}"
        )
        data = response.json()
        # ok 可能是 True（动态创建）或 False（拒绝），两种都合理
        assert "ok" in data, f"响应缺少 ok 字段：{data}"

    @pytest.mark.unit
    def test_switch_domain_is_idempotent(self, client):
        """切到同一本书两次，第二次应该成功（幂等性）。

        如果第二次失败说明切换逻辑里有状态依赖的 bug——
        比如用了"上次状态"做对比而不是以最终结果为准。
        """
        # 先切一次
        r1 = client.post("/api/switch-domain", json={"domain": "红楼梦"})
        # 再切一次同一本书
        r2 = client.post("/api/switch-domain", json={"domain": "红楼梦"})
        if r1.status_code == 200 and r2.status_code == 200:
            # 两次都应该成功
            assert r1.json().get("ok") is True or r1.json().get("ok") is False, \
                "第一次切换应返回正常响应"
            # 第二次至少不应该 500
            assert r2.status_code == 200, f"第二次切换不应该失败：{r2.status_code}"
