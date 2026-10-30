# -*- coding: utf-8 -*-
"""Build report/export/design_report.docx from report/01_design_report.md.

Run with the bundled Python (python-docx):
    <runtime-python> report/export/build_docx.py
"""
from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "report" / "01_design_report.md"
OUT = ROOT / "report" / "export" / "design_report.docx"

BODY_FONT = "宋体"
HEAD_FONT = "黑体"
CODE_FONT = "Consolas"
INK = RGBColor(0x1F, 0x29, 0x37)
BLUE = RGBColor(0x1F, 0x3A, 0x5F)
GREY = RGBColor(0x5B, 0x63, 0x70)


def set_run_font(run, name=BODY_FONT, size=None, bold=None, color=None, italic=None):
    run.font.name = name
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:ascii"), name)
    rFonts.set(qn("w:hAnsi"), name)
    rFonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color


def shade(paragraph_or_cell, hex_fill):
    el = paragraph_or_cell._element
    pPr = el.get_or_add_pPr() if hasattr(el, "get_or_add_pPr") else el.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    pPr.append(shd)


def cell_shade(cell, hex_fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def para_border(paragraph, color="BFC9D6", size="6"):
    pPr = paragraph._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), size)
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), color)
    pbdr.append(bottom)
    pPr.append(pbdr)


def add_field(paragraph, instr):
    run = paragraph.add_run()
    fldChar = OxmlElement("w:fldChar")
    fldChar.set(qn("w:fldCharType"), "begin")
    instrText = OxmlElement("w:instrText")
    instrText.set(qn("xml:space"), "preserve")
    instrText.text = instr
    fldChar2 = OxmlElement("w:fldChar")
    fldChar2.set(qn("w:fldCharType"), "end")
    run._r.append(fldChar)
    run._r.append(instrText)
    run._r.append(fldChar2)


def add_hyperlink(paragraph, url, text):
    part = paragraph.part
    r_id = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                          is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    new_run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "1F4E79")
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    rPr.append(color)
    rPr.append(u)
    new_run.append(rPr)
    t = OxmlElement("w:t")
    t.text = text
    new_run.append(t)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)


TOKEN = re.compile(r"(\*\*.+?\*\*|`.+?`|\[[^\]]+\]\([^)]+\)|<https?://[^>]+>)")


def add_inline(paragraph, text, size=10.5, color=INK):
    for token in TOKEN.split(text):
        if not token:
            continue
        if token.startswith("**") and token.endswith("**"):
            r = paragraph.add_run(token[2:-2])
            set_run_font(r, BODY_FONT, size, bold=True, color=color)
        elif token.startswith("`") and token.endswith("`"):
            r = paragraph.add_run(token[1:-1])
            set_run_font(r, CODE_FONT, max(size - 1.2, 7.5), color=RGBColor(0x8B, 0x1A, 0x1A))
        elif token.startswith("[") and "](" in token:
            m = re.match(r"\[([^\]]+)\]\(([^)]+)\)", token)
            if m:
                add_hyperlink(paragraph, m.group(2), m.group(1))
            else:
                paragraph.add_run(token)
        elif token.startswith("<http"):
            url = token[1:-1]
            add_hyperlink(paragraph, url, url)
        else:
            r = paragraph.add_run(token)
            set_run_font(r, BODY_FONT, size, color=color)


def setup_styles(doc):
    st = doc.styles["Normal"]
    st.font.name = BODY_FONT
    st.font.size = Pt(10.5)
    st._element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
    st.paragraph_format.line_spacing = 1.45
    st.paragraph_format.space_after = Pt(4)

    for name, size, before, after in (("Heading 1", 17, 12, 8), ("Heading 2", 13.5, 10, 5), ("Heading 3", 11.5, 8, 4)):
        h = doc.styles[name]
        h.font.name = HEAD_FONT
        h.font.size = Pt(size)
        h.font.bold = True
        h.font.color.rgb = BLUE
        h._element.rPr.rFonts.set(qn("w:eastAsia"), HEAD_FONT)
        h.paragraph_format.space_before = Pt(before)
        h.paragraph_format.space_after = Pt(after)
        h.paragraph_format.keep_with_next = True


def add_cover(doc, title, subtitle):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(70)
    r = p.add_run(title)
    set_run_font(r, HEAD_FONT, 24, bold=True, color=BLUE)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(14)
    r = p.add_run(subtitle)
    set_run_font(r, HEAD_FONT, 18, bold=False, color=GREY)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(24)
    r = p.add_run("2026 全国大学生嵌入式芯片与系统设计竞赛 · FPGA 创新设计赛道\nAMD 自主选题（初级组）")
    set_run_font(r, BODY_FONT, 11, color=INK)


def add_table(doc, rows):
    if not rows:
        return
    header = rows[0]
    body = rows[1:]
    ncol = len(header)
    table = doc.add_table(rows=1, cols=ncol)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    hdr = table.rows[0]
    for i, text in enumerate(header):
        cell = hdr.cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_inline(p, text, size=8.5, color=INK)
        for r in p.runs:
            r.font.bold = True
        cell_shade(cell, "D9E2F3")
    trPr = hdr._tr.get_or_add_trPr()
    tblHeader = OxmlElement("w:tblHeader")
    tblHeader.set(qn("w:val"), "true")
    trPr.append(tblHeader)

    for row in body:
        cells = table.add_row().cells
        for i in range(ncol):
            text = row[i] if i < len(row) else ""
            p = cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(1)
            p.paragraph_format.line_spacing = 1.1
            add_inline(p, text, size=8.3, color=INK)
    # small cell margins
    tblPr = table._tbl.tblPr
    margins = OxmlElement("w:tblCellMar")
    for side, w in (("top", "30"), ("bottom", "30"), ("left", "60"), ("right", "60")):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:w"), w)
        el.set(qn("w:type"), "dxa")
        margins.append(el)
    tblPr.append(margins)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def parse_table(lines, i):
    rows = []
    while i < len(lines) and lines[i].strip().startswith("|"):
        line = lines[i].strip()
        if re.match(r"^\|[\s:|-]+\|$", line):
            i += 1
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)
        i += 1
    return rows, i


def build(src=SRC, out=OUT, subtitle="设计报告",
          header="基于 AMD Zynq-7020 的实时超声三维扫描与形态异常检测系统 · 设计报告"):
    text = src.read_text(encoding="utf-8")
    lines = text.splitlines()

    doc = Document()
    setup_styles(doc)
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.left_margin = Cm(2.2)
    sec.right_margin = Cm(2.0)
    sec.top_margin = Cm(2.0)
    sec.bottom_margin = Cm(1.8)

    # header / footer
    hp = sec.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = hp.add_run(header)
    set_run_font(r, BODY_FONT, 8, color=GREY)
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = fp.add_run("第 ")
    set_run_font(r, BODY_FONT, 8.5, color=GREY)
    add_field(fp, "PAGE")
    r = fp.add_run(" 页")
    set_run_font(r, BODY_FONT, 8.5, color=GREY)

    # cover from the first H1 + following bold line
    i = 0
    while i < len(lines) and not lines[i].startswith("# "):
        i += 1
    title = lines[i][2:].strip() if i < len(lines) else "设计报告"
    add_cover(doc, title, subtitle)
    i += 1
    # metadata table between subtitle and the first ---
    j = i
    while j < len(lines) and lines[j].strip() != "---":
        if lines[j].strip().startswith("|"):
            rows, _ = parse_table(lines, j)
            add_table(doc, rows)
            break
        j += 1
    while i < len(lines) and lines[i].strip() != "---":
        i += 1
    i += 1  # skip ---
    doc.add_page_break()

    in_code = False
    code_buf = []
    first_h1 = True
    ol_counter = 1
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped and not stripped.startswith(("- ", "* ")) and not re.match(r"^\d+\.\s+", stripped):
            ol_counter = 1

        if stripped.startswith("```"):
            if in_code:
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Cm(0.3)
                p.paragraph_format.space_before = Pt(2)
                p.paragraph_format.space_after = Pt(6)
                p.paragraph_format.line_spacing = 1.0
                shade(p, "F2F4F7")
                for k, code_line in enumerate(code_buf):
                    r = p.add_run(code_line)
                    set_run_font(r, CODE_FONT, 8.3, color=RGBColor(0x22, 0x2A, 0x33))
                    if k != len(code_buf) - 1:
                        r.add_break()
                code_buf = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        if not stripped:
            i += 1
            continue

        if stripped == "---":
            p = doc.add_paragraph()
            para_border(p)
            p.paragraph_format.space_after = Pt(6)
            i += 1
            continue

        if stripped == "<!-- pagebreak -->":
            doc.add_page_break()
            i += 1
            continue

        if stripped.startswith("|"):
            rows, i = parse_table(lines, i)
            add_table(doc, rows)
            continue

        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            text_ = m.group(2).strip()
            if level == 1:
                if not first_h1:
                    doc.add_page_break()
                first_h1 = False
                h = doc.add_heading(level=1)
                add_inline(h, text_, size=17, color=BLUE)
            elif level == 2:
                if text_.startswith("附录 A"):
                    doc.add_page_break()
                h = doc.add_heading(level=2)
                add_inline(h, text_, size=13.5, color=BLUE)
            elif level == 3:
                h = doc.add_heading(level=3)
                add_inline(h, text_, size=11.5, color=BLUE)
            else:
                p = doc.add_paragraph()
                add_inline(p, text_, size=10.5, color=INK)
                for r in p.runs:
                    r.font.bold = True
            i += 1
            continue

        m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", stripped)
        if m:
            alt, rel = m.group(1), m.group(2)
            img = (src.parent / rel).resolve()
            if img.exists():
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_before = Pt(4)
                p.paragraph_format.space_after = Pt(2)
                run = p.add_run()
                if "fig_rig_photos" in rel:
                    width = Cm(12.0)
                elif "fig_system_architecture" in rel:
                    width = Cm(13.5)
                elif "photo_electronics" in rel or "diagram_wiring" in rel:
                    width = Cm(15.0)
                else:
                    width = Cm(16.8)
                run.add_picture(str(img), width=width)
                cap = doc.add_paragraph()
                cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                cap.paragraph_format.space_after = Pt(8)
                r = cap.add_run(alt)
                set_run_font(r, BODY_FONT, 8.8, color=GREY)
            i += 1
            continue

        if stripped.startswith(">"):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.5)
            p.paragraph_format.space_before = Pt(3)
            p.paragraph_format.space_after = Pt(5)
            shade(p, "EEF3F8")
            add_inline(p, stripped.lstrip("> ").strip(), size=9.8, color=RGBColor(0x2B, 0x3A, 0x4A))
            i += 1
            continue

        if re.match(r"^[-*]\s+", stripped):
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.space_after = Pt(1.5)
            add_inline(p, re.sub(r"^[-*]\s+", "", stripped), size=10.2)
            i += 1
            continue

        if re.match(r"^\d+\.\s+", stripped):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.75)
            p.paragraph_format.first_line_indent = Cm(-0.45)
            p.paragraph_format.space_after = Pt(1.5)
            r = p.add_run(f"{ol_counter}. ")
            set_run_font(r, BODY_FONT, 10.2, color=INK)
            add_inline(p, re.sub(r"^\d+\.\s+", "", stripped), size=10.2)
            ol_counter += 1
            i += 1
            continue

        if stripped.startswith("**电子系统与接线"):
            doc.add_page_break()

        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = Cm(0.74)
        add_inline(p, stripped, size=10.5)
        i += 1

    # remove the empty paragraph left by the cover flow if any
    doc.core_properties.title = "基于 AMD Zynq-7020 的实时超声三维扫描与形态异常检测系统 · 设计报告"
    doc.core_properties.author = "Ultrasound 3D Scanner Team"
    doc.core_properties.subject = "2026 FPGA 创新设计赛道 AMD 自主选题（初级组）"
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    print(f"DOCX_OK {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    build()
