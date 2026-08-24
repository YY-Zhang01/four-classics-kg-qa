"""切块：把 parsed/ 下的 Markdown 切成带出处的文本块，落到 chunks/*.json。

策略：先按《红楼梦》回目（"第X回"）分节，每节再按字数切成带重叠的小块，
尽量在句末断开，保证句子完整、可溯源。

P0 证据升级：切块时自动计算 content_hash(SHA256) 和页码信息。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from config.settings import CHUNK_DIR, CHUNK_OVERLAP, CHUNK_SIZE, PARSED_DIR

# 匹配"第一回 / 第十二回 / 第一百二十回"这类回目标题
CHAPTER_RE = re.compile(r"(第[一二三四五六七八九十百零]+回[^\n]*)")

# 匹配 MinerU 输出的页码标记，如 "第 1 页 / 共 120 页" 或 "Page 1"
PAGE_MARKER_RE = re.compile(r"第\s*(\d+)\s*页|Page\s+(\d+)", re.IGNORECASE)


def _clean(text: str) -> str:
    """规整空白：合并行内多余空格，压缩连续空行，但保留段落结构。"""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_by_chapter(text: str) -> list[tuple[str, str]]:
    """返回 [(章节标题, 章节正文), ...]；匹配不到回目则整篇作为一节。"""
    parts = CHAPTER_RE.split(text)
    if len(parts) <= 1:
        return [("全文", text)]
    result: list[tuple[str, str]] = []
    # split 后结构：[前言, 标题1, 正文1, 标题2, 正文2, ...]
    preface = parts[0].strip()
    if preface:
        result.append(("卷首", preface))
    for i in range(1, len(parts), 2):
        title = parts[i].strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        result.append((title, body))
    return result


def _window(text: str, size: int, overlap: int) -> list[str]:
    """把长文本按字数切成带重叠的窗口，尽量在句末（。！？”）断开。"""
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        # 往后找一个句末标点，避免硬切断句
        if end < len(text):
            m = re.search(r"[。！？”]", text[end:end + 40])
            if m:
                end = end + m.end()
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _extract_page(text: str) -> int | None:
    """尝试从文本中提取 MinerU 的页码标记，返回整数页码或 None。"""
    m = PAGE_MARKER_RE.search(text)
    if m:
        # group(1) 匹配中文格式，group(2) 匹配英文格式
        return int(m.group(1) or m.group(2))
    return None


def _compute_hash(text: str) -> str:
    """对文本内容计算 SHA256，用于去重和变更检测。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_file(md_path: Path, source_name: str) -> list[dict]:
    """把单个 Markdown 文件切成块列表。P0: 每条块带 content_hash 和页码。"""
    raw = _clean(md_path.read_text(encoding="utf-8", errors="ignore"))
    results: list[dict] = []
    idx = 0
    para_no = 0
    for chapter, body in _split_by_chapter(raw):
        for piece in _window(body, CHUNK_SIZE, CHUNK_OVERLAP):
            para_no += 1
            results.append({
                "id": f"{source_name}#{idx}",
                "source": source_name,
                "chapter": chapter,
                "text": piece,
                "page_no": _extract_page(piece),
                "paragraph_no": para_no,
                "content_hash": _compute_hash(piece),
            })
            idx += 1
    return results


def build_all() -> None:
    """把 parsed/ 下所有 Markdown 切块，逐文件写成 chunks/<名>.json。"""
    CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    md_files = list(PARSED_DIR.rglob("*.md"))
    if not md_files:
        print(f"parsed/ 下没有 .md，请先跑 MinerU 解析：{PARSED_DIR}")
        return
    total = 0
    for md in md_files:
        source_name = md.stem
        chunks = split_file(md, source_name)
        out = CHUNK_DIR / f"{source_name}.json"
        out.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
        total += len(chunks)
        print(f"[切块] {md.name} -> {out.name}（{len(chunks)} 块）")
    print(f"[切块] 完成，共 {total} 块。")


if __name__ == "__main__":
    build_all()
