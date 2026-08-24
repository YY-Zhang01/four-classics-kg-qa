"""用户认证模块：注册、登录、JWT 验证。"""
from __future__ import annotations

import os
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from retrieval.db import get_conn

# ── JWT 配置 ──────────────────────────────────────────────────────────────────
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_urlsafe(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRES_HOURS = 24  # token 有效期 24 小时

# 首个注册用户是否自动成为管理员（可用环境变量关闭，显式化控制）
AUTO_FIRST_ADMIN = os.getenv("AUTO_FIRST_ADMIN", "true").strip().lower() in ("1", "true", "yes", "on")

# ── Bearer Token 提取器 ───────────────────────────────────────────────────────
security = HTTPBearer(auto_error=False)


def hash_password(plain: str) -> str:
    """返回 bcrypt 哈希后的密码字符串。"""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """验证明文密码是否与 bcrypt 哈希匹配。"""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_token(user_id: int, username: str, role: str = "user") -> str:
    """生成 JWT access token（含角色信息）。"""
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRES_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """解码 JWT token，失败抛 401。"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token 已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的 Token")


# ── FastAPI 依赖：获取当前用户（可选登录）─────────────────────────────────────
def get_current_user_or_none(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict | None:
    """从 Bearer Token 解析当前用户；未登录返回 None，token 无效则报 401。"""
    if credentials is None:
        return None
    payload = decode_token(credentials.credentials)
    return {"id": int(payload["sub"]), "username": payload["username"], "role": payload.get("role", "user")}


# ── FastAPI 依赖：必须登录 ────────────────────────────────────────────────────
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    """强制要求登录，否则 401。"""
    if credentials is None:
        raise HTTPException(status_code=401, detail="请先登录")
    payload = decode_token(credentials.credentials)
    return {"id": int(payload["sub"]), "username": payload["username"], "role": payload.get("role", "user")}


# ── FastAPI 依赖：仅限管理员 ──────────────────────────────────────────────────
def get_current_admin(
    user: dict = Depends(get_current_user),
) -> dict:
    """要求登录且角色为 admin，否则 403。"""
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


# ── 业务逻辑 ──────────────────────────────────────────────────────────────────

def _validate_password(password: str) -> None:
    """校验密码强度：至少 8 位，且同时包含字母和数字。"""
    if len(password) < 8:
        raise ValueError("密码至少 8 个字符")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("密码需同时包含字母和数字")


def register(username: str, password: str, display_name: str | None = None, role: str = "user") -> dict:
    """注册新用户。默认第一个注册的用户自动成为管理员（可用 AUTO_FIRST_ADMIN 关闭）。"""
    username = username.strip()
    if len(username) < 2:
        raise ValueError("用户名至少 2 个字符")
    _validate_password(password)
    if role not in ("user", "admin"):
        raise ValueError("角色只能是 user 或 admin")

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM public.users WHERE username = %s", (username,))
        if cur.fetchone():
            raise ValueError(f"用户名 '{username}' 已被注册")

        # 如果没有用户，且 AUTO_FIRST_ADMIN 开启，第一个注册者自动成为管理员
        cur.execute("SELECT count(*) FROM public.users")
        is_first = cur.fetchone()[0] == 0
        actual_role = "admin" if (is_first and AUTO_FIRST_ADMIN) else role

        cur.execute(
            "INSERT INTO public.users (username, password_hash, display_name, role) VALUES (%s, %s, %s, %s) RETURNING id",
            (username, hash_password(password), display_name or username, actual_role),
        )
        user_id = cur.fetchone()[0]
        conn.commit()

    token = create_token(user_id, username, actual_role)
    return {
        "ok": True, "token": token, "username": username,
        "user_id": user_id, "display_name": display_name or username,
        "role": actual_role,
    }


def login(username: str, password: str) -> dict:
    """用户登录，返回 JWT token（含角色）。"""
    username = username.strip()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, password_hash, display_name, role FROM public.users WHERE username = %s",
            (username,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("用户名或密码错误")

        user_id, pwd_hash, display_name, role = row
        if not verify_password(password, pwd_hash):
            raise ValueError("用户名或密码错误")

    token = create_token(user_id, username, role)
    return {
        "ok": True,
        "token": token,
        "username": username,
        "user_id": user_id,
        "display_name": display_name,
        "role": role,
    }
