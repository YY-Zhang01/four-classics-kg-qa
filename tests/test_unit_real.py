"""真实单元测试：auth / kg.store / retrieval.search 的纯逻辑（不 mock 被测函数）。

现有 test_api_*.py 为了不碰 DB/LLM 把外部依赖全 MagicMock 掉，只测 API 契约；
这里直接测真实函数，覆盖密码强度、bcrypt、JWT、领域过滤、关键词打分这些纯逻辑。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException

from auth.auth import (
    JWT_SECRET,
    JWT_ALGORITHM,
    _validate_password,
    hash_password,
    verify_password,
    create_token,
    decode_token,
)
from retrieval.search import search, _tokenize
import kg.store as kg_store


# ── auth：密码强度 ──────────────────────────────────────────

@pytest.mark.unit
def test_password_weak_rejected():
    for bad in ["short", "abcdefgh", "12345678", "abc1234", ""]:
        with pytest.raises(ValueError):
            _validate_password(bad)


@pytest.mark.unit
def test_password_strong_accepted():
    _validate_password("Test123456")  # 不抛异常即通过


# ── auth：bcrypt 哈希往返 ──────────────────────────────────

@pytest.mark.unit
def test_password_hash_roundtrip():
    hashed = hash_password("Secret123")
    assert hashed != "Secret123"
    assert verify_password("Secret123", hashed) is True
    assert verify_password("Wrong123", hashed) is False


# ── auth：JWT 签发/校验 ────────────────────────────────────

@pytest.mark.unit
def test_jwt_roundtrip():
    token = create_token(1, "alice", role="admin")
    payload = decode_token(token)
    assert payload["sub"] == "1"
    assert payload["username"] == "alice"
    assert payload["role"] == "admin"


@pytest.mark.unit
def test_jwt_tampered_rejected():
    token = create_token(1, "alice")
    # 改中间字符（避开 base64 尾部 padding 位），确保签名被破坏
    mid = len(token) // 2
    tampered = token[:mid] + ("A" if token[mid] != "A" else "B") + token[mid + 1:]
    with pytest.raises(HTTPException) as ei:
        decode_token(tampered)
    assert ei.value.status_code == 401


@pytest.mark.unit
def test_jwt_expired_rejected():
    exp = datetime.now(timezone.utc) - timedelta(hours=1)
    payload = {"sub": "1", "username": "u", "role": "user", "iat": exp, "exp": exp}
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    with pytest.raises(HTTPException) as ei:
        decode_token(token)
    assert ei.value.status_code == 401


# ── kg.store：领域过滤 ──────────────────────────────────────

@pytest.mark.unit
def test_domain_clause_with_domain():
    old = kg_store._active_kg_domain
    kg_store._active_kg_domain = "红楼梦"
    try:
        assert kg_store._domain_clause() == "source = %s"
        assert kg_store._domain_param() == ("红楼梦",)
    finally:
        kg_store._active_kg_domain = old


@pytest.mark.unit
def test_domain_clause_without_domain():
    old = kg_store._active_kg_domain
    kg_store._active_kg_domain = ""
    try:
        assert kg_store._domain_clause() == ""
        assert kg_store._domain_param() == ()
    finally:
        kg_store._active_kg_domain = old


# ── retrieval.search：关键词分词/打分 ──────────────────────

_CHUNKS = [
    {"source": "红楼梦", "chapter": "第一回", "text": "黛玉葬花，感花伤己，葬的是桃花。"},
    {"source": "红楼梦", "chapter": "第二回", "text": "宝玉与众人饮酒作诗，好不快活。"},
    {"source": "红楼梦", "chapter": "第三回", "text": "黛玉进了贾府，见到贾母。"},
]


@pytest.mark.unit
def test_tokenize_filters_stopwords():
    toks = _tokenize("黛玉的葬花？")
    assert "黛玉" in toks
    assert "葬花" in toks
    assert "的" not in toks   # 停用词被过滤
    assert "？" not in toks   # 纯标点被过滤


@pytest.mark.unit
def test_search_returns_most_relevant():
    hits = search("葬花", chunks=_CHUNKS, top_k=2)
    assert hits, "应命中至少一块"
    assert hits[0]["chapter"] == "第一回"  # 唯一含"葬花"的块排最前


@pytest.mark.unit
def test_search_empty_query_returns_empty():
    assert search("", chunks=_CHUNKS) == []
    assert search("怎么？", chunks=_CHUNKS) == []  # 全是停用词/标点
