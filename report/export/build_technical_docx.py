# -*- coding: utf-8 -*-
"""Build report/export/technical_document.docx from report/02_technical_document.md."""
from pathlib import Path

from build_docx import build

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "report" / "02_technical_document.md"
OUT = ROOT / "report" / "export" / "technical_document.docx"

if __name__ == "__main__":
    build(
        src=SRC,
        out=OUT,
        subtitle="技术文档",
        header="超声扫描三维建模与异常检测系统 · 技术文档",
    )
