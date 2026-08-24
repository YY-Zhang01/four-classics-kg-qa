"""三国演义：下载公版全文 → 切块 → 灌库（一键脚本）

三国演义为公有领域作品（罗贯中，14 世纪），可自由用于学习。
"""
from __future__ import annotations

import re
import json
import sys
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import PARSED_DIR, CHUNK_DIR

BOOK_NAME = "三国演义"
PARSED_FILE = PARSED_DIR / f"{BOOK_NAME}.md"
CHUNK_FILE = CHUNK_DIR / f"{BOOK_NAME}.json"

# 公版源
URLS = [
    f"https://raw.githubusercontent.com/tennessine/corpus/master/{quote(BOOK_NAME)}.txt",
    f"https://raw.githubusercontent.com/hankinghu/literature-books/master/{quote(BOOK_NAME)}.txt",
]

CHAPTER_RE = re.compile(r"(第[一二三四五六七八九十百零]+回)")
HEADERS = {"User-Agent": "Mozilla/5.0 (RedDream-KB-Builder; educational use)"}


def download() -> str:
    """下载三国演义全文。"""
    for url in URLS:
        print(f"尝试下载: {url}")
        try:
            resp = httpx.get(url, headers=HEADERS, timeout=60, follow_redirects=True)
            resp.raise_for_status()
            # 自动识别编码
            for enc in ("utf-8-sig", "utf-8", "gb18030"):
                try:
                    text = resp.content.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                text = resp.content.decode("utf-8", errors="ignore")

            # 校验
            if len(text) < 200_000:
                print(f"  文本太短 ({len(text)} 字)，跳过")
                continue
            if "第一回" not in text:
                print("  缺少回目标记，跳过")
                continue
            if ("刘备" not in text) and ("關羽" not in text) and ("关羽" not in text):
                print("  未检测到三国人物，跳过")
                continue

            print(f"  下载成功！{len(text)} 字")
            return text
        except Exception as e:
            print(f"  失败: {e}")
    raise RuntimeError("所有源均下载失败")


def normalize(text: str) -> str:
    """规整：统一换行、回目独立成行。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = CHAPTER_RE.sub(r"\n\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def split_into_chunks(text: str, chunk_size: int = 500, overlap: int = 80):
    """按回目 + 滑动窗口切块，生成与红楼梦一致的 JSON 格式。"""
    chapters = CHAPTER_RE.split(text)
    # chapters: ['前言...', '第一回', '回目内容...', '第二回', ...]

    chunks = []
    current_chapter = "前言"

    for i in range(len(chapters)):
        part = chapters[i].strip()
        if not part:
            continue
        if CHAPTER_RE.fullmatch(part):
            current_chapter = part
            continue

        # 滑动窗口切块
        words = list(part)  # 按字符切（中文不需要分词）
        step = chunk_size - overlap
        for start in range(0, max(len(words) - overlap, 1), step):
            end = min(start + chunk_size, len(words))
            if end - start < 50:  # 太短的块不要
                continue
            chunk_text = "".join(words[start:end])
            chunks.append({
                "source": BOOK_NAME,
                "chapter": current_chapter,
                "text": chunk_text,
                "char_offset": start,
            })
        # 最后一个可能太短，合并到前一个
        if chunks and len(words) - (start or 0) < 50:
            chunks[-1]["text"] += "".join(words[start:])

    # 去重：连续相同开头的块（滑动窗口可能产生）
    seen = set()
    unique = []
    for c in chunks:
        key = c["text"][:30]
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def main():
    print(f"=== {BOOK_NAME} 文本处理 ===\n")

    # 1. 下载
    print("[1/3] 下载全文...")
    text = download()
    text = normalize(text)
    PARSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    PARSED_FILE.write_text(text, encoding="utf-8")
    print(f"  已保存: {PARSED_FILE}")

    # 2. 切块
    print("\n[2/3] 切块...")
    from config.settings import CHUNK_SIZE, CHUNK_OVERLAP
    chunks = split_into_chunks(text, CHUNK_SIZE, CHUNK_OVERLAP)
    CHUNK_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHUNK_FILE.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  已保存: {CHUNK_FILE} ({len(chunks)} 块)")

    # 3. 向量化灌库（如果有 ingest_db 脚本）
    print(f"\n[3/3] 下一步：向量化灌库")
    print(f"  python -m scripts.ingest_db --book {BOOK_NAME}")
    print(f"\n完成！{len(chunks)} 个知识块已就绪。")


if __name__ == "__main__":
    main()
