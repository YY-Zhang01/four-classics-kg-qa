"""数据库连接助手（P1）：统一从 .env 读连接参数，交出一个连接。"""
from __future__ import annotations

import contextlib

import psycopg2

from config.settings import db_config


@contextlib.contextmanager
def get_conn():
    """上下文管理器：进去拿连接，出来自动关。"""
    db_config.require()
    conn = psycopg2.connect(**db_config.dsn())
    try:
        yield conn
    finally:
        conn.close()
