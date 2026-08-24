"""Wiki 查询接口（P1）：搜索 Wiki 页面，为检索融合提供结构化知识。"""
from __future__ import annotations

from config.settings import get_active_domain
from wiki.store import search_pages, get_page, list_pages, count_pages


def search(query: str, top_k: int = 3) -> list[dict]:
    """搜索 Wiki 页面，返回格式与检索器兼容。

    返回 [{type: "wiki", title, page_type, content, confidence, ...}, ...]
    """
    domain = get_active_domain()
    pages = search_pages(domain, query=query, limit=top_k)

    results = []
    for p in pages:
        # 把 sections 展平成文本摘要
        sections = p.get("content", {}).get("sections", {})
        summary_parts = []
        for sec_name, sec_data in sections.items():
            text = sec_data.get("content", "")
            if text and text != "资料不足":
                summary_parts.append(f"【{sec_name}】{text[:200]}")

        results.append({
            "type": "wiki",
            "id": f"wiki#{p['id']}",
            "title": p["title"],
            "page_type": p["page_type"],
            "text": "\n".join(summary_parts),
            "confidence": p.get("confidence", 0),
            "score": p.get("confidence", 0),  # 用 confidence 当检索分数
            "entities": p.get("entities", []),
            "source": f"Wiki·{p['page_type']}",
            "chapter": p["title"],
        })

    return results


def search_by_entity(entity_name: str) -> list[dict]:
    """按实体名精确查找 Wiki 页面。"""
    domain = get_active_domain()
    pages = search_pages(domain, query=entity_name, limit=3)
    return [
        {
            "type": "wiki",
            "id": f"wiki#{p['id']}",
            "title": p["title"],
            "page_type": p["page_type"],
            "content": p.get("content", {}),
            "confidence": p.get("confidence", 0),
        }
        for p in pages
        if entity_name in (p.get("entities") or [])
    ]


def label() -> str:
    return "Wiki 百科检索"


def count() -> int:
    return count_pages(get_active_domain())
