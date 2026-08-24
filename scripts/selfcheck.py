"""离线自检：不联网、不需要密钥，验证核心链路的代码逻辑是否正常。

覆盖：模块导入 + 切块（回目识别/窗口重叠）+ 关键词检索打分。
用法：python -m scripts.selfcheck
"""
from __future__ import annotations

import importlib


def check_imports() -> None:
    for mod in [
        "config.settings",
        "llm.base",
        "llm.gateway_client",
        "parser.run_mineru",
        "kb_builder.split",
        "retrieval.search",
        "core.ask",
        "main",
    ]:
        importlib.import_module(mod)
    print("[1/3] 模块导入：全部通过 [OK]")


def check_split() -> None:
    from kb_builder.split import split_file
    from pathlib import Path
    import tempfile

    # 合成一段带两个回目的文本
    sample = (
        "第一回 甄士隐梦幻识通灵\n"
        + "此开卷第一回也。" * 60
        + "\n第二回 贾夫人仙逝扬州城\n"
        + "却说封肃因听见公差传唤。" * 60
    )
    with tempfile.TemporaryDirectory() as d:
        md = Path(d) / "测试.md"
        md.write_text(sample, encoding="utf-8")
        chunks = split_file(md, "测试")
    chapters = {c["chapter"] for c in chunks}
    assert any("第一回" in c for c in chapters), "未识别到第一回"
    assert any("第二回" in c for c in chapters), "未识别到第二回"
    assert all(c["text"] for c in chunks), "存在空块"
    print(f"[2/3] 切块：识别 {len(chapters)} 个章节，产出 {len(chunks)} 块 [OK]")


def check_search() -> None:
    from retrieval.search import search

    chunks = [
        {"id": "a#0", "source": "红楼梦", "chapter": "第一回", "text": "黛玉葬花，感花伤己。"},
        {"id": "a#1", "source": "红楼梦", "chapter": "第二回", "text": "宝玉与众人饮酒作诗。"},
    ]
    hits = search("黛玉葬花", chunks=chunks, top_k=2)
    assert hits and hits[0]["id"] == "a#0", "检索未命中预期块"
    print(f"[3/3] 检索：'黛玉葬花' 命中 {len(hits)} 块，Top1 正确 [OK]")


def main() -> None:
    check_imports()
    check_split()
    check_search()
    print("\n离线自检全部通过。接下来配好 .env 即可测网关连通性。")


if __name__ == "__main__":
    main()
