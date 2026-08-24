"""关键词检索（P0）：jieba 分词 + TF-IDF 打分 + 停用词过滤，取 Top-K。

比纯词频强在：稀有关键词（如“葬花”）权重更高，高频废词（“怎么”“说明”）被压制或过滤，
避免满篇都是的词（如“黛玉”）淹没真正决定性的词。
P1 会把这里升级成向量检索（pgvector）做语义召回，但对外的 search() 接口保持稳定，方便替换。
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import jieba

from config.settings import CHUNK_DIR, TOP_K

# 把 jieba 词典缓存放到项目内 .cache/，避免写到 C 盘临时目录
_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
_CACHE_DIR.mkdir(exist_ok=True)
jieba.dt.tmp_dir = str(_CACHE_DIR)

# 停用词：高频虚词 + 提问用语，过滤掉，免得淹没真正的关键词
STOPWORDS = {
    "的", "了", "是", "在", "和", "与", "及", "也", "都", "就", "还", "又", "这", "那", "有",
    "我", "你", "他", "她", "它", "们", "之", "其", "为", "以", "于", "而", "则", "并", "把",
    "请", "问", "说", "什么", "怎么", "怎样", "如何", "回事", "简要", "一下", "关于", "以及",
    "介绍", "说明", "讲讲", "谈谈", "描述", "解释", "为什么", "哪些", "哪个", "是否", "可以",
    "怎么回事", "回事", "一回事", "讲述", "发生", "故事", "情节", "经过",
}
_PUNCT_RE = re.compile(r"^[\s，。！？、；：“”‘’（）《》〈〉…—·,.!?;:\"'()\[\]{}]+$")


def load_chunks() -> list[dict]:
    """把 chunks/ 下与当前激活领域匹配的 JSON 块合并成一个列表。
    
    优先加载 chunks/{domain}.json，找不到则加载所有 .json 文件。
    与 vector_search 不同，此函数读文件而非数据库。
    """
    from config.settings import get_active_domain
    domain = get_active_domain()
    chunks: list[dict] = []
    
    # 优先按领域加载
    if domain:
        domain_file = CHUNK_DIR / f"{domain}.json"
        if domain_file.exists():
            chunks.extend(json.loads(domain_file.read_text(encoding="utf-8")))
            return chunks
    
    # 回退：加载所有
    for f in CHUNK_DIR.glob("*.json"):
        chunks.extend(json.loads(Path(f).read_text(encoding="utf-8")))
    return chunks


def count() -> int:
    """知识块总数（给上层显示/判空用，与向量检索接口对齐）。"""
    return len(load_chunks())


def _tokenize(query: str) -> list[str]:
    """分词并过滤：去空白、纯标点、停用词；结果去重但保持顺序。"""
    seen: set[str] = set()
    uniq: list[str] = []
    for t in jieba.lcut(query):
        t = t.strip()
        if not t or _PUNCT_RE.match(t) or t in STOPWORDS:
            continue
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def _build_idf(terms: list[str], chunks: list[dict]) -> dict[str, float]:
    """对每个查询词统计文档频率 df（含该词的块数），算平滑 IDF：稀有词权重更高。"""
    n = len(chunks) or 1
    idf: dict[str, float] = {}
    for t in terms:
        df = sum(1 for c in chunks if t in c["text"])
        idf[t] = math.log((n + 1) / (df + 1)) + 1.0
    return idf


def _score(terms: list[str], idf: dict[str, float], text: str) -> float:
    """TF-IDF 打分：Σ (1+log 词频) × IDF。

    对 TF 取对数衰减：一个词在块里出现 50 次不再线性算 50 倍，
    免得“黛玉”这种满篇都是的词靠堆量把稀有关键词“葬花”压死。
    """
    score = 0.0
    for t in terms:
        tf = text.count(t)
        if tf > 0:
            score += (1.0 + math.log(tf)) * idf[t]
    return score


def search(query: str, chunks: list[dict] | None = None, top_k: int = TOP_K) -> list[dict]:
    """按 TF-IDF 给块打分，返回得分最高的 top_k 块（得分为 0 的丢弃）。"""
    if chunks is None:
        chunks = load_chunks()
    terms = _tokenize(query)
    if not terms:
        return []
    idf = _build_idf(terms, chunks)
    scored: list[tuple[float, dict]] = []
    for c in chunks:
        s = _score(terms, idf, c["text"])
        if s > 0:
            scored.append((s, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:top_k]]


if __name__ == "__main__":
    import sys

    q = sys.argv[1] if len(sys.argv) > 1 else "黛玉葬花"
    hits = search(q)
    print(f"查询：{q}，命中 {len(hits)} 块，关键词：{_tokenize(q)}")
    for h in hits:
        print(f"  [{h['source']} · {h['chapter']}] {h['text'][:40]}...")
