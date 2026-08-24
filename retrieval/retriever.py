"""检索器工厂：按 RETRIEVER 配置在 关键词/向量/融合 之间切换。

对外只暴露统一的 search() / count() / label()，上层（main、core.ask）无感。
换检索方式只改配置一行，业务代码一行不动——这就是"可插拔"。

模式：keyword = 关键词（P0） / vector = 语义向量（P1） / fusion = KG+向量融合（P2）
"""
from __future__ import annotations

from config.settings import get_retriever, get_top_k

_LABELS = {
    "keyword": "关键词检索",
    "vector": "语义向量检索",
    "fusion": "KG+Wiki+向量融合检索",
    "wiki": "Wiki 百科检索",
}


def _impl():
    mode = get_retriever()
    if mode == "vector":
        from retrieval import vector_search as m
    elif mode == "fusion":
        from retrieval import fusion as m
    elif mode == "wiki":
        from wiki import query as m
    else:
        from retrieval import search as m
    return m


def label() -> str:
    """当前检索方式的人话说明。"""
    return _LABELS.get(get_retriever(), "未知检索")


def count() -> int:
    """当前检索源里的知识块数量。"""
    return _impl().count()


def search(query: str, top_k: int | None = None) -> list[dict]:
    """统一检索入口：返回最相关的 top_k 块（不传则用当前配置值）。"""
    k = top_k if top_k is not None else get_top_k()
    return _impl().search(query, top_k=k)
