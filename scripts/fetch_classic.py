"""通用古典名著下载 + 切块工具。

用法：python scripts/fetch_classic.py 水浒传
"""
from __future__ import annotations
import re, json, sys
from pathlib import Path
from urllib.parse import quote
import httpx

BOOK = sys.argv[1] if len(sys.argv) > 1 else "水浒传"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config.settings import PARSED_DIR, CHUNK_DIR, CHUNK_SIZE, CHUNK_OVERLAP

URLS = [
    f"https://raw.githubusercontent.com/tennessine/corpus/master/{quote(BOOK)}.txt",
]
CHAPTER_RE = re.compile(r"(第[一二三四五六七八九十百零]+回)")
HEADERS = {"User-Agent": "Mozilla/5.0 (RedDream; educational use)"}


def download():
    for url in URLS:
        print(f"尝试: {url}")
        try:
            resp = httpx.get(url, headers=HEADERS, timeout=60, follow_redirects=True)
            resp.raise_for_status()
            for enc in ("utf-8-sig", "utf-8", "gb18030"):
                try:
                    text = resp.content.decode(enc); break
                except UnicodeDecodeError:
                    continue
            else:
                text = resp.content.decode("utf-8", errors="ignore")
            if len(text) < 100_000:
                print(f"  太短 ({len(text)} 字)"); continue
            if "第一回" not in text:
                print("  缺回目"); continue
            print(f"  成功！{len(text)} 字")
            return text
        except Exception as e:
            print(f"  失败: {e}")
    raise RuntimeError("下载失败")


def normalize(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = CHAPTER_RE.sub(r"\n\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def split_chunks(text, size=None, overlap=None):
    size = size or CHUNK_SIZE
    overlap = overlap or CHUNK_OVERLAP
    parts = CHAPTER_RE.split(text)
    current_chapter = "前言"
    chunks, seen = [], set()
    step = size - overlap

    for part in parts:
        part = part.strip()
        if not part: continue
        if CHAPTER_RE.fullmatch(part):
            current_chapter = part; continue
        words = list(part)
        for start in range(0, max(len(words) - overlap, 1), step):
            end = min(start + size, len(words))
            if end - start < 50: continue
            ctext = "".join(words[start:end])
            key = ctext[:30]
            if key not in seen:
                seen.add(key)
                chunks.append({"source": BOOK, "chapter": current_chapter, "text": ctext, "char_offset": start})
    # 加 id
    prefix = {"水浒传": "sh", "西游记": "xy", "红楼梦": "hlm", "三国演义": "sg"}.get(BOOK, "bk")
    for i, c in enumerate(chunks, 1):
        c["id"] = f"{prefix}_{i:05d}"
    return chunks


def main():
    print(f"=== {BOOK} 文本处理 ===\n[1/3] 下载...")
    text = download()
    text = normalize(text)
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    (PARSED_DIR / f"{BOOK}.md").write_text(text, encoding="utf-8")
    print(f"  已保存: parsed/{BOOK}.md")

    print(f"\n[2/3] 切块 (size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP})...")
    chunks = split_chunks(text)
    CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    out = CHUNK_DIR / f"{BOOK}.json"
    out.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  已保存: chunks/{BOOK}.json ({len(chunks)} 块)")

    print(f"\n[3/3] 下一步: python scripts/ingest_one.py {BOOK}")
    print(f"完成！")


if __name__ == "__main__":
    main()
