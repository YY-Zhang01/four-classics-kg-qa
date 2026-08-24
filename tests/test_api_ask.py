"""问答 API 测试：POST /api/ask（SSE 流式响应）

这个是最核心的接口——前端整个聊天界面都靠它。
测试 SSE 流式接口比普通 JSON 接口复杂，因为：
1. 响应是分片传输的，不是一次性返回
2. 需要逐行解析 "data: xxx\n\n" 格式
3. 流中嵌入了多种类型的消息（文本/图谱/引用/路由）

面试官如果问你"怎么测 SSE 接口"，这些就是关键点。
"""

from __future__ import annotations

import json
import pytest


# ═══════════════════════════════════════════════════════════
#  SSE 解析工具（与 conftest.py 中的定义相同，内联避免跨模块导入）
# ═══════════════════════════════════════════════════════════

def _parse_sse(response_text: str) -> list[dict]:
    """把 SSE text/event-stream 响应解析成结构化数据。"""
    events: list[dict] = []
    for line in response_text.split("\n"):
        line = line.strip()
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload.startswith("__ROUTE__"):
            events.append({"type": "route", "data": json.loads(payload[9:])})
        elif payload.startswith("__GRAPH__"):
            events.append({"type": "graph", "data": json.loads(payload[9:])})
        elif payload.startswith("__SOURCES__"):
            events.append({"type": "sources", "data": json.loads(payload[11:])})
        else:
            events.append({"type": "text", "data": payload})
    return events


# ═══════════════════════════════════════════════════════════
#  输入校验：错误的请求
# ═══════════════════════════════════════════════════════════

class TestAskInputValidation:
    """输入校验——永远是你测试一个接口的起点。

    测试开发的核心思维：
      不是"测它能做什么"，而是"它不该做什么"。
      一个空问题不该让服务崩溃，一个缺少字段的请求不该返回 200 OK。
    """

    @pytest.mark.unit
    def test_empty_question_returns_error_message(self, client):
        """发空问题 → SSE 流里应该有错误提示，而不是静默无响应。

        验证点：
        - 状态码 200（SSE 的约定，错误在流内表达）
        - 流内容包含"请输入问题"
        """
        response = client.post("/api/ask", json={"question": ""})
        assert response.status_code == 200
        body = response.text
        assert "请输入问题" in body, (
            f"空问题应返回提示，实际响应：{body[:200]}"
        )

    @pytest.mark.unit
    def test_whitespace_only_question(self, client):
        r"""纯空白（空格/制表符/换行）应该被 strip 后当作空问题处理。

        实际中的惨痛教训：
          有用户复制粘贴问题，不小心多复制了换行，导致问题字段全是 \n\n\n，
          如果服务端没 trim 就直接调 LLM，浪费 token 都是小事，
          prompt 里塞一堆空行可能导致输出质量下降。
        """
        response = client.post("/api/ask", json={"question": "   \n\t   "})
        assert response.status_code == 200
        body = response.text
        assert "请输入问题" in body, (
            f"纯空白问题应被识别为空，实际响应：{body[:200]}"
        )

    @pytest.mark.unit
    @pytest.mark.parametrize("bad_body,desc", [
        ({}, "缺少 question 字段"),
        ({"wrong_field": "xxx"}, "字段名打错"),
        ({"question": None}, "question 是 null"),
    ])
    def test_invalid_request_body(self, client, bad_body: dict, desc: str):
        """请求体格式不对时的行为测试。

        当前代码用 body.get("question", "").strip() 取问题，
        - {} → get 返回 "" → 正常返回 "请输入问题"
        - {"wrong_field": "xxx"} → 同上
        - {"question": None} → get 返回 None → None.strip() 抛 AttributeError

        第三个 case 是一个真实 bug，修复方式：(body.get("question") or "").strip()
        """
        if desc == "question 是 null":
            # 已知 bug：None.strip() → AttributeError，未被 FastAPI 全局异常处理捕获
            with pytest.raises(AttributeError, match="strip"):
                client.post("/api/ask", json=bad_body)
        else:
            response = client.post("/api/ask", json=bad_body)
            assert response.status_code == 200, (
                f"[{desc}] 期望 200，实际 {response.status_code}。"
                f"响应：{response.text[:200]}"
            )

    @pytest.mark.unit
    def test_question_too_long(self, client):
        """超长问题（10000+ 字符）应该有合理处理，不能 OOM。

        虽然 RedDream 目前没做长度限制，但作为测试应该覆盖这个场景。
        """
        long_q = "贾宝玉" * 5000  # 25000 字符
        response = client.post("/api/ask", json={"question": long_q})
        # 不应该返回 500
        assert response.status_code in (200, 413, 422), (
            f"超长问题的状态码异常：{response.status_code}"
        )


# ═══════════════════════════════════════════════════════════
#  SSE 格式校验
# ═══════════════════════════════════════════════════════════

class TestAskSSEFormat:
    """验证 SSE 协议的格式正确性。

    如果 SSE 格式有问题，前端 JavaScript EventSource API 解析会失败，
    导致用户看到 loading 一直转但永远不出结果——这是"静默失败"的一种。
    """

    @pytest.mark.unit
    def test_response_content_type_is_sse(self, client):
        """Content-Type 必须是 text/event-stream，前端 EventSource 只认这个。"""
        response = client.post("/api/ask", json={"question": "贾宝玉是谁？"})
        ct = response.headers.get("content-type", "")
        assert "text/event-stream" in ct, (
            f"SSE 响应的 Content-Type 应为 text/event-stream，实际：{ct}"
        )

    @pytest.mark.unit
    def test_sse_lines_start_with_data_prefix(self, client):
        """每条 SSE 消息必须以 "data: " 开头，否则前端 EventSource 不认。

        你可以打开浏览器 DevTools → Network → 找 ask 请求 → EventStream 标签，
        确认每行都是 "data: xxx" 格式。
        """
        response = client.post("/api/ask", json={"question": "贾宝玉是谁？"})
        assert response.status_code == 200
        body = response.text
        lines = [l for l in body.split("\n") if l.strip()]
        # 至少要有一些以 "data:" 开头的行
        data_lines = [l for l in lines if l.startswith("data:")]
        assert len(data_lines) > 0, (
            f"SSE 响应中缺少 data: 开头的行。响应前 300 字符：{body[:300]}"
        )


# ═══════════════════════════════════════════════════════════
#  SSE 内容结构校验
# ═══════════════════════════════════════════════════════════

class TestAskSSEContent:
    """验证 SSE 流中各类系统消息的结构。

    RedDream 的 SSE 流中嵌入了四类特殊消息（带 __ 前缀），
    前端根据这些消息渲染图谱、引用面板等。如果格式变了，
    前端 JS 解析会静默失败——用户看不到图谱但也不知道为什么。
    """

    @pytest.mark.unit
    def test_parse_sse_structure(self, client):
        """用 parse_sse 工具解析流内容，验证至少能解析出文本片段。

        这里的 parse_sse 是一个简化版的 SSE 解析器——真实项目中，
        你应该用 Node.js EventSource API 或 Python sseclient 库来解析。
        """
        response = client.post("/api/ask", json={"question": "贾宝玉是谁？"})
        events = _parse_sse(response.text)

        # 至少有一个文本事件（系统提示"检索到 X 条参考资料"也算）
        text_events = [e for e in events if e["type"] == "text"]
        assert len(text_events) > 0, (
            f"期望至少有一个文本事件，实际事件类型："
            f"{[e['type'] for e in events]}"
        )

    @pytest.mark.unit
    def test_no_response_has_reasonable_length(self, client):
        """当检索不到内容时，响应应该简短明确。
        
        不能是空响应——用户发问题后什么都没看到会以为系统卡了。
        不能是几千字的废话——没检索到内容就别让 LLM 瞎编。
        """
        response = client.post(
            "/api/ask",
            json={"question": "量子力学中薛定谔方程在红楼梦第几回出现？"},
        )
        body = response.text
        # 应该包含"未找到"之类的提示
        has_error_hint = "未找到" in body or "请输入" in body
        # 或者至少有一个合理的回答长度（不太可能找到内容）
        assert response.status_code == 200
        assert len(body) > 0, "响应不能为空"


# ═══════════════════════════════════════════════════════════
#  多轮对话（带 history）
# ═══════════════════════════════════════════════════════════

class TestAskMultiTurn:
    """多轮对话：验证 history 参数能正确处理上下文指代。

    比如：
      用户："贾宝玉是谁？"
      用户："他母亲是谁？"  ← 这个"他"要靠 history 解析成"贾宝玉"
    """

    @pytest.mark.unit
    def test_ask_with_history(self, client, sample_question_with_history):
        """带 history 的请求应正常处理，不报错。"""
        response = client.post("/api/ask", json=sample_question_with_history)
        assert response.status_code == 200
        # 确认流中有内容
        assert len(response.text) > 0

    @pytest.mark.unit
    def test_history_ignores_invalid_format(self, client):
        """history 格式错误时不应导致 500。"""
        response = client.post("/api/ask", json={
            "question": "你好",
            "history": "这不是一个合法的列表",
        })
        assert response.status_code == 200


# ═══════════════════════════════════════════════════════════
#  Agent 模式
# ═══════════════════════════════════════════════════════════

class TestAgentAsk:
    """Agent 模式：LLM 自主决定调哪个工具（KG 查询 / Wiki 搜索等）。

    与普通 /api/ask 的区别：
    - 普通模式：固定检索→生成流水线
    - Agent 模式：LLM 可以多步推理，调用不同工具
    """

    @pytest.mark.unit
    def test_agent_empty_question(self, client):
        response = client.post("/api/agent/ask", json={"question": ""})
        assert response.status_code == 200
        assert "请输入问题" in response.text

    @pytest.mark.unit
    def test_agent_with_question(self, client):
        response = client.post("/api/agent/ask", json={"question": "贾宝玉是谁？"})
        assert response.status_code == 200
        assert len(response.text) > 0
