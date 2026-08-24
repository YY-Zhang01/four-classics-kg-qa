"""MinerU 解析封装：把 PDF 解析成 Markdown，产物落到 parsed/。

MinerU 作为外部命令调用（系统已装 CPU 版），不绑进本项目虚拟环境，保持环境轻量。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from config.settings import PARSED_DIR, PDF_DIR


def parse_pdf(pdf_path: Path, out_dir: Path = PARSED_DIR) -> None:
    """调用 mineru CLI 解析单个 PDF。"""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"找不到 PDF：{pdf_path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["mineru", "-p", str(pdf_path), "-o", str(out_dir)]
    print(f"[MinerU] 执行：{' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise RuntimeError("MinerU 解析失败：请确认已安装 mineru、PDF 可读。")
    print(f"[MinerU] 完成，产物在：{out_dir}")


def parse_all() -> None:
    """把 pdfs/ 下所有 PDF 逐个解析。"""
    pdfs = list(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"pdfs/ 下没有 PDF，请先放入原著 PDF：{PDF_DIR}")
        return
    for pdf in pdfs:
        parse_pdf(pdf)


if __name__ == "__main__":
    parse_all()
