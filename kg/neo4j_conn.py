"""Neo4j 连接管理器（P3）：统一管理 Neo4j 驱动生命周期，支持优雅降级。

当 Neo4j 不可用时，所有查询自动回退到 PG，调用方无需感知差异。
"""

from __future__ import annotations

import logging
import warnings

from config.settings import neo4j_config

# neo4j 4.x driver 的 ExperimentalWarning 不影响功能，静默
warnings.filterwarnings("ignore", category=Warning, module="neo4j")

logger = logging.getLogger(__name__)

_driver = None
_available: bool | None = None  # None = 未检测, True/False = 已检测


def _create_driver():
    """创建 Neo4j 驱动（延迟导入，避免硬依赖）。"""
    try:
        from neo4j import GraphDatabase
        return GraphDatabase.driver(
            neo4j_config.uri,
            auth=neo4j_config.auth(),
            max_connection_lifetime=300,
        )
    except ImportError:
        logger.warning("neo4j 驱动未安装，图谱增强功能不可用")
        return None
    except Exception as e:
        logger.warning(f"Neo4j 驱动初始化失败: {e}")
        return None


def get_driver():
    """获取 Neo4j 驱动单例。"""
    global _driver
    if _driver is None:
        _driver = _create_driver()
    return _driver


def is_available() -> bool:
    """检测 Neo4j 是否可用（结果缓存，首次调用后不再重复检测）。"""
    global _available
    if _available is not None:
        return _available

    if not neo4j_config.enabled:
        _available = False
        return False

    driver = get_driver()
    if driver is None:
        _available = False
        return False

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            driver.verify_connectivity()
        _available = True
        logger.info("Neo4j 连接成功，图谱增强已启用")
    except Exception as e:
        _available = False
        logger.warning(f"Neo4j 不可用，回退到 PG 查询: {e}")

    return _available


def run_query(cypher: str, params: dict | None = None) -> list[dict]:
    """执行 Cypher 查询，返回记录列表。

    Neo4j 不可用时返回空列表（调用方自行回退到 PG）。
    """
    if not is_available():
        return []

    driver = get_driver()
    if driver is None:
        return []

    try:
        with driver.session() as session:
            result = session.run(cypher, params or {})
            return [dict(record) for record in result]
    except Exception as e:
        logger.warning(f"Neo4j 查询失败: {e}")
        return []


def reset_connection() -> None:
    """重置连接状态（配置变更后调用）。"""
    global _driver, _available
    if _driver:
        try:
            _driver.close()
        except Exception:
            pass
    _driver = None
    _available = None
