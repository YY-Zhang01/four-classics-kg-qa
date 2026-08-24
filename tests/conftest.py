"""pytest 共享配置：Fixture、Mock、Marker 定义

Mock 策略：在 import web.server 之前，先把所有外部依赖模块注入 sys.modules。
这样 app 启动和运行时都不会尝试连接真实的 DB / LLM / 文件系统。
"""

from __future__ import annotations

import sys
import pytest
from unittest.mock import patch, MagicMock


# ═══════════════════════════════════════════════════════════
#  pytest 配置（marker 定义）
# ═══════════════════════════════════════════════════════════

pytest_plugins: list[str] = []


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "unit: 单元测试，不需要外部服务")
    config.addinivalue_line("markers", "integration: 集成测试，需要 Ollama + PG 运行")


# ═══════════════════════════════════════════════════════════
#  假数据工厂
# ═══════════════════════════════════════════════════════════

def _fake_hits() -> list[dict]:
    """模拟 search() 返回的检索命中结果（kg_fact + text 两种类型）。"""
    return [
        {
            "id": "kg_001", "type": "kg_fact",
            "subject": "贾宝玉", "relation": "表兄妹", "object": "林黛玉",
            "score": 0.95, "confidence": 0.9,
            "source": "红楼梦", "chapter": "第三回", "source_chunk_id": "chunk_123",
        },
        {
            "id": "chunk_042", "type": "text",
            "source": "红楼梦", "chapter": "第三回 贾雨村夤缘复旧职 林黛玉抛父进京都",
            "text": "黛玉方进入房时，只见两个人搀着一位鬓发如银的老母迎上来...",
            "score": 0.88, "page_no": 42, "content_hash": "a1b2c3d4e5f6",
        },
    ]


def _fake_stream() -> list[str]:
    """模拟 answer_stream() 的输出片段。"""
    return [
        "贾宝玉和林黛玉是表兄妹关系。",
        "林黛玉的母亲贾敏是贾宝玉的姑母。",
        "两人青梅竹马，",
        "最终却未能在一起。",
    ]


# ═══════════════════════════════════════════════════════════
#  预填 sys.modules：在 import web.server 之前替换外部依赖
# ═══════════════════════════════════════════════════════════

def _pre_mock_modules():
    """把所有 web.server 间接依赖的外部模块替换成 MagicMock。

    这些模块在真实环境中需要 PostgreSQL、Ollama、Neo4j 等，
    单元测试中我们用假模块替代，让代码路径走通但不动真实服务。
    """
    # -- 检索相关 --
    mock_retrieval_retriever = MagicMock()
    mock_retrieval_retriever.search = MagicMock(return_value=_fake_hits())
    mock_retrieval_retriever.count = MagicMock(return_value=42)
    mock_retrieval_retriever.label = MagicMock(return_value="向量检索 (bge-m3)")
    sys.modules["retrieval.retriever"] = mock_retrieval_retriever
    sys.modules["retrieval"] = MagicMock()

    # -- KG 检索（_stream 内部 from retrieval.kg_search import rewrite_query）--
    mock_kg_search = MagicMock()
    mock_kg_search.rewrite_query = MagicMock(side_effect=lambda q, h: q)
    mock_kg_search._extract_entities = MagicMock(return_value=["贾宝玉"])
    sys.modules["retrieval.kg_search"] = mock_kg_search

    # -- 向量检索 --
    sys.modules["retrieval.vector_search"] = MagicMock()

    # -- 融合检索 --
    mock_fusion = MagicMock()
    mock_fusion.search_with_strategy = MagicMock(return_value=_fake_hits())
    sys.modules["retrieval.fusion"] = mock_fusion

    # -- 图谱搜索 --
    sys.modules["retrieval.graph_search"] = MagicMock()

    # -- DB 层 --
    sys.modules["retrieval.db"] = MagicMock()

    # -- 路由（用 SimpleNamespace 替代 MagicMock，避免 JSON 序列化报错）--
    from types import SimpleNamespace
    mock_router = MagicMock()
    mock_router.route = MagicMock(return_value=(
        SimpleNamespace(question_type="factual", method="fusion", confidence=0.8, reason="mock"),
        SimpleNamespace(name="default"),
    ))
    sys.modules["router"] = mock_router

    # -- LLM 层 --
    mock_llm_base = MagicMock()
    mock_llm = MagicMock()
    mock_llm.chat = MagicMock(return_value="5")
    mock_llm_base.get_llm = MagicMock(return_value=mock_llm)
    sys.modules["llm.base"] = mock_llm_base
    sys.modules["llm.gateway_client"] = MagicMock()

    # -- 核心生成 --
    mock_core_ask = MagicMock()
    mock_core_ask.answer_stream = MagicMock(return_value=iter(_fake_stream()))
    sys.modules["core.ask"] = mock_core_ask

    # -- KG 存储 --
    mock_kg_store = MagicMock()
    mock_kg_store.count_triples = MagicMock(return_value=128)
    mock_kg_store.query_by_entity = MagicMock(return_value=[])
    mock_kg_store.set_kg_domain = MagicMock()
    sys.modules["kg.store"] = mock_kg_store

    # -- Neo4j --
    sys.modules["kg.neo4j_conn"] = MagicMock()
    sys.modules["kg.sync_to_neo4j"] = MagicMock()

    # -- Agent --
    mock_agent = MagicMock()
    mock_agent.agent_ask_stream = MagicMock(return_value=iter(["mock agent response"]))
    sys.modules["agent.loop"] = mock_agent

    # -- Auth（必须用 def/lambda，不能用 MagicMock——
    #     FastAPI 的 Depends() 会检查函数签名，MagicMock 的 *args/**kwargs 导致 422）--
    mock_auth = MagicMock()
    mock_auth.get_current_user = lambda: {"username": "test", "role": "user"}
    mock_auth.get_current_user_or_none = lambda: None
    mock_auth.get_current_admin = lambda: {"username": "admin", "role": "admin"}
    mock_auth.register = MagicMock(return_value={"ok": True, "username": "test"})
    mock_auth.login = MagicMock(return_value={"ok": True, "token": "mock_token"})
    sys.modules["auth.auth"] = mock_auth

    # -- Wiki --
    sys.modules["wiki.query"] = MagicMock()
    sys.modules["wiki.store"] = MagicMock()

    # -- Review --
    sys.modules["review"] = MagicMock()

    # -- Collector / Updater --
    sys.modules["collector.sources"] = MagicMock()
    sys.modules["collector.scanner"] = MagicMock()
    sys.modules["updater.pipeline"] = MagicMock()
    sys.modules["updater.reporter"] = MagicMock()


def _cleanup_mock_modules():
    """测试结束后清理注入的假模块。"""
    for mod in list(sys.modules.keys()):
        if mod.startswith(("retrieval.", "router", "llm.", "core.", "kg.", "agent.", "auth.", "wiki.", "review", "collector.", "updater.")):
            sys.modules.pop(mod, None)


# ═══════════════════════════════════════════════════════════
#  Fixture：FastAPI TestClient
# ═══════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient，所有外部依赖已 mock。

    在 web.server 被 import 之前，我们先用 MagicMock 填满 sys.modules，
    这样 FastAPI 的 lifespan 和 _stream 函数里所有 `from xxx import yyy`
    拿到的都是假对象，不会碰真实 DB / LLM。
    """
    _pre_mock_modules()

    from web.server import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c

    _cleanup_mock_modules()


# ═══════════════════════════════════════════════════════════
#  测试数据 Fixture
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def sample_question() -> dict:
    return {"question": "贾宝玉和林黛玉是什么关系？"}


@pytest.fixture
def sample_question_with_history() -> dict:
    return {
        "question": "他最后怎么样了？",
        "history": [
            {"role": "user", "content": "贾宝玉是谁？"},
            {"role": "assistant", "content": "贾宝玉是《红楼梦》的男主角，荣国府贾政之子。"},
        ],
    }


@pytest.fixture
def sample_register_user() -> dict:
    return {
        "username": "testuser_qa",
        "password": "Test123456",
        "display_name": "测试用户",
    }


# ═══════════════════════════════════════════════════════════
#  SSE 解析工具
# ═══════════════════════════════════════════════════════════

def parse_sse(response_text: str) -> list[dict]:
    """把 SSE text/event-stream 响应解析成结构化数据。"""
    import json
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
