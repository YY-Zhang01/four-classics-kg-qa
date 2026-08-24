"""抓取《红楼梦》公版全文，落成 parsed/红楼梦.md，供后续切块使用。

《红楼梦》为公有领域作品（曹雪芹，18 世纪），可自由用于学习。
策略：依次尝试多个公开的纯文本源，自动识别编码、校验内容完整性，
成功后规整为「回目各自独立成行」的 Markdown，写入 parsed/ 目录。
"""
from __future__ import annotations

import re
import sys
from urllib.parse import quote

import httpx

from config.settings import PARSED_DIR

# 候选源：公版全本纯文本（简体优先）。按顺序尝试，取第一个校验通过的。
CANDIDATE_URLS = [
    "https://raw.githubusercontent.com/tennessine/corpus/master/" + quote("红楼梦") + ".txt",
    "https://raw.githubusercontent.com/hankinghu/literature-books/master/" + quote("红楼梦") + ".txt",
]

OUT_FILE = PARSED_DIR / "红楼梦.md"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (RedDream-KB-Builder; educational use, public-domain text)",
}

# 回目标题：第一回 / 第十二回 / 第一百二十回
CHAPTER_LINE_RE = re.compile(r"(第[一二三四五六七八九十百零]+回)")


def _decode(raw: bytes) -> str:
    """自动识别编码：优先 utf-8，失败再退 gb18030。"""
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    # 实在不行，用 utf-8 容错解码
    return raw.decode("utf-8", errors="ignore")


def _looks_like_hongloumeng(text: str) -> bool:
    """校验抓到的是不是真·红楼梦全本，避免存进残缺或错误内容。"""
    if len(text) < 300_000:  # 全本约 70 万字，太短说明不完整
        return False
    if "第一回" not in text:
        return False
    if ("宝玉" not in text) and ("寶玉" not in text):
        return False
    return True


def _normalize(text: str) -> str:
    """规整：统一换行、确保每个回目标题独立成行、压缩多余空行。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 回目标题前补一个换行，保证它单独起一行（便于按回目切分）
    text = CHAPTER_LINE_RE.sub(r"\n\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def _count_chapters(text: str) -> int:
    return len(set(CHAPTER_LINE_RE.findall(text)))


def fetch() -> None:
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    last_err = None
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=60.0) as client:
        for url in CANDIDATE_URLS:
            try:
                print(f"[抓取] 尝试源：{url}")
                resp = client.get(url)
                resp.raise_for_status()
                text = _decode(resp.content)
                if not _looks_like_hongloumeng(text):
                    print(f"[抓取] 内容校验不通过（长度 {len(text)}），换下一个源")
                    continue
                text = _normalize(text)
                OUT_FILE.write_text(text, encoding="utf-8")
                print(f"[抓取] 成功！字数约 {len(text):,}，识别回目 {_count_chapters(text)} 个")
                print(f"[抓取] 已写入：{OUT_FILE}")
                return
            except Exception as e:  # noqa: BLE001 — 逐源兜底，失败即换下一个
                last_err = e
                print(f"[抓取] 该源失败：{e!r}")
                continue
    print("[抓取] 所有源均失败。最后一个错误：", repr(last_err), file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    fetch()
