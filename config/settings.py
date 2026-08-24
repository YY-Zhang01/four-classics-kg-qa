"""全局配置：集中管理网关地址、模型、路径、检索/切块参数。

铁律：密钥只从环境变量 / .env 读取，绝不写死在代码里，也绝不进 git。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# 项目根目录（config 的上一级）
ROOT = Path(__file__).resolve().parent.parent

try:
    # 显式加载项目根目录下的 .env（该文件已被 .gitignore 忽略）
    # 不依赖启动时的当前工作目录，从哪里跑都能读到
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    # 没装 python-dotenv 也不报错，直接读系统环境变量
    pass

# 各类数据目录
PDF_DIR = ROOT / "pdfs"       # 原始 PDF
PARSED_DIR = ROOT / "parsed"  # MinerU 解析产物（Markdown）
CHUNK_DIR = ROOT / "chunks"   # 切块结果（JSON）
LOG_DIR = ROOT / "logs"       # 审计 / 决策日志
PROMPT_DIR = ROOT / "prompts" # 提示词（与代码分离）
CONFIG_DIR = ROOT / "config"  # 领域配置文件


@dataclass
class LLMConfig:
    """大模型接入配置。默认走 OpenAI 兼容接口（本地 Ollama / 第三方 API 通用）。"""

    base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", ""))
    api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", ""))
    timeout: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT", "60")))
    provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "gateway"))

    def require(self) -> None:
        """调用大模型前校验必填配置是否就位。

        网关地址/模型/密钥都不写死在代码里，只从 .env 读。
        """
        missing = [
            name
            for name, value in {
                "LLM_BASE_URL": self.base_url,
                "LLM_API_KEY": self.api_key,
                "LLM_MODEL": self.model,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(
                f"缺少配置：{', '.join(missing)}。请把 config/.env.example 复制成项目根目录的 "
                ".env 并填写（.env 已被 .gitignore 忽略，不会进 git）。"
            )


llm_config = LLMConfig()

# 检索参数：召回块数（支持运行时热更新）
_TOP_K_OVERRIDE: int | None = None


def get_top_k() -> int:
    """当前生效的 Top-K（优先运行时覆盖，其次 .env）。"""
    if _TOP_K_OVERRIDE is not None:
        return _TOP_K_OVERRIDE
    return int(os.getenv("TOP_K", "5"))


def set_top_k(k: int) -> None:
    """运行时调整召回块数，不影响 .env。"""
    global _TOP_K_OVERRIDE
    if k < 1 or k > 20:
        raise ValueError(f"Top-K 范围 1-20，收到 {k}")
    _TOP_K_OVERRIDE = k


TOP_K = get_top_k()  # 兼容旧代码的直接导入

# 切块参数：单块目标字数 + 相邻块重叠字数（保证跨块语义不断裂）
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "80"))

# ── 项目标识 ──────────────────────────────────────────────
# 用在页面标题、启动横幅、prompt 等领域提示中。
# 换文档时只改这两个值即可切换领域（前提：KG schema 也同步更新）。
PROJECT_NAME = os.getenv("PROJECT_NAME", "四大名著知识问答")
PROJECT_DOMAIN = os.getenv("PROJECT_DOMAIN", "红楼梦")

# ── 运行时领域切换（支持前端书籍选择）─────────────────────
# 用户端和管理端各自维护独立的 domain 状态，互不干扰。
# 用户页面切换书 → 只影响用户端；管理后台切换 → 只影响管理后台。

# ── 用户端状态 ──
_active_domain: str = PROJECT_DOMAIN
_active_name: str = PROJECT_NAME

# ── 管理端状态 ──
_admin_active_domain: str = PROJECT_DOMAIN
_admin_active_name: str = PROJECT_NAME


def get_active_domain() -> str:
    """用户端当前生效的领域标识。"""
    return _active_domain


def get_active_name() -> str:
    """用户端当前生效的项目名称。"""
    return _active_name


def get_admin_domain() -> str:
    """管理端当前生效的领域标识（独立于用户端）。"""
    return _admin_active_domain


def get_admin_name() -> str:
    """管理端当前生效的项目名称。"""
    return _admin_active_name


# 领域标识合法字符：字母/数字/下划线 + 中文 + 中点/连字符
_DOMAIN_RE = re.compile(r"^[\w\u4e00-\u9fff·-]{1,50}$")


def validate_domain(domain: str) -> str:
    """校验领域标识，防止路径穿越（../、\\ 等）。

    领域名只允许字母数字下划线、中文、· 和 -，长度 1-50。
    返回清理后的字符串；非法时抛 ValueError。
    """
    domain = (domain or "").strip()
    if not domain:
        raise ValueError("domain 不能为空")
    if not _DOMAIN_RE.fullmatch(domain):
        raise ValueError("domain 含非法字符（仅允许中英文/数字/下划线/·/-）")
    return domain


def _load_domain_info(domain: str) -> dict:
    """加载指定领域的 UI 配置（印章、提示词等）。"""
    import json
    info = {"domain": domain, "name": f"{domain}问答"}
    for candidate in [CONFIG_DIR / f"domain_{domain}.json", CONFIG_DIR / "domain.json"]:
        if candidate.is_file():
            dc = json.loads(candidate.read_text(encoding="utf-8"))
            info["seal"] = dc.get("seal", "?")
            info["hints"] = dc.get("hints", [])
            break
    return info


def switch_domain(domain: str) -> dict:
    """用户端运行时切换到指定领域。不影响管理端状态。"""
    global _active_domain, _active_name, _ENTITIES_CACHE

    # 清除实体缓存（只清此 domain 的，保留其他书）
    _ENTITIES_CACHE.pop(domain, None)

    # 清除向量缓存（只清此 domain）
    try:
        from retrieval.vector_search import invalidate_cache
        invalidate_cache(domain)
    except ImportError:
        pass

    # 切换 KG 过滤（全局——但 KG 查询都在用户端 API 中，不会与管理端冲突）
    try:
        from kg.store import set_kg_domain
        set_kg_domain(domain)
    except ImportError:
        pass

    _active_domain = domain
    _active_name = f"{domain}问答"
    return _load_domain_info(domain)


def switch_admin_domain(domain: str) -> dict:
    """管理端运行时切换到指定领域。不影响用户端状态。"""
    global _admin_active_domain, _admin_active_name

    _admin_active_domain = domain
    _admin_active_name = f"{domain}问答"
    return _load_domain_info(domain)

# ── 管理后台鉴权 ──────────────────────────────────────────
# 访问 /admin 及 /api/admin/* 需要的 Bearer Token。
# 为空字符串时跳过鉴权（开发期便利，正式环境务必设置）。
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

# ── 向量检索（P1）──────────────────────────────────────────
# 检索方式：vector = 语义向量检索（P1）；keyword = 关键词检索（P0，随时可回退）
_RETRIEVER_OVERRIDE: str | None = None  # 运行时覆盖，管理后台可切换


def get_retriever() -> str:
    """当前生效的检索方式（优先运行时覆盖，其次 .env）。"""
    return _RETRIEVER_OVERRIDE or os.getenv("RETRIEVER", "vector")


def set_retriever(mode: str) -> None:
    """运行时切换检索方式（keyword / vector / fusion），不影响 .env。"""
    global _RETRIEVER_OVERRIDE
    if mode not in ("vector", "keyword", "fusion", "wiki"):
        raise ValueError(f"无效检索方式：{mode}，可选 vector / keyword / fusion / wiki")
    _RETRIEVER_OVERRIDE = mode


RETRIEVER = get_retriever()  # 兼容旧代码的直接导入

# embedding（向量生成）模型，复用同一个 OpenAI 兼容接口（本地 Ollama）
EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-m3")
EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", "") or llm_config.base_url
EMBED_API_KEY = os.getenv("EMBED_API_KEY", "") or llm_config.api_key


@dataclass
class DBConfig:
    """本地 PostgreSQL 连接配置，全部从 .env 读，绝不写死、绝不进 git。"""

    host: str = field(default_factory=lambda: os.getenv("PG_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("PG_PORT", "5432")))
    dbname: str = field(default_factory=lambda: os.getenv("PG_DB", "reddream"))
    user: str = field(default_factory=lambda: os.getenv("PG_USER", ""))
    password: str = field(default_factory=lambda: os.getenv("PG_PASSWORD", ""))

    def require(self) -> None:
        missing = [
            name
            for name, value in {"PG_USER": self.user, "PG_PASSWORD": self.password}.items()
            if not value
        ]
        if missing:
            raise RuntimeError(
                f"缺少数据库配置：{', '.join(missing)}。请在项目根目录 .env 里填写"
                "（.env 已被 .gitignore 忽略，不会进 git）。"
            )

    def dsn(self) -> dict:
        """给 psycopg2.connect(**dsn()) 用的连接参数。"""
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.dbname,
            "user": self.user,
            "password": self.password,
        }


db_config = DBConfig()


# ── Neo4j 图谱配置（P3）─────────────────────────────────────

@dataclass
class Neo4jConfig:
    """Neo4j 连接配置，全部从 .env 读。未配置时 Neo4j 功能静默降级。"""

    uri: str = field(default_factory=lambda: os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    user: str = field(default_factory=lambda: os.getenv("NEO4J_USER", "neo4j"))
    password: str = field(default_factory=lambda: os.getenv("NEO4J_PASSWORD", "neo4j"))

    @property
    def enabled(self) -> bool:
        """是否启用 Neo4j 功能（所有配置项都非空即为启用）。"""
        return bool(self.uri and self.user and self.password)

    def auth(self) -> tuple[str, str]:
        return (self.user, self.password)


neo4j_config = Neo4jConfig()


# ── KG 实体词典（领域相关，按 domain 分桶缓存）────────────────
_ENTITIES_CACHE: dict[str, dict] = {}


def get_entities(domain: str | None = None) -> dict:
    """加载领域人物实体词典。不传 domain 则用用户端当前领域。

    优先加载 config/entities_{domain}.json，找不到则回退到 config/entities.json。
    """
    import json
    if domain is None:
        domain = get_active_domain()
    if domain in _ENTITIES_CACHE:
        return _ENTITIES_CACHE[domain]
    candidates = []
    if domain:
        candidates.append(CONFIG_DIR / f"entities_{domain}.json")
    candidates.append(CONFIG_DIR / "entities.json")  # 默认回退
    for path in candidates:
        if path.is_file():
            _ENTITIES_CACHE[domain] = json.loads(path.read_text(encoding="utf-8"))
            return _ENTITIES_CACHE[domain]
    _ENTITIES_CACHE[domain] = {"aliases": {}, "short_names": {}, "common_names": []}
    return _ENTITIES_CACHE[domain]


def reload_entities(domain: str | None = None) -> dict:
    """强制重新加载实体词典。"""
    if domain is None:
        domain = get_active_domain()
    _ENTITIES_CACHE.pop(domain, None)
    return get_entities(domain)
