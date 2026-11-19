# -*- coding: utf-8 -*-
"""把 docs/实验报告.md 转成排版好的 docs/实验报告.docx。

只处理报告实际用到的 Markdown 子集：#/##/### 标题、表格、代码块、引用、
有序/无序列表、行内 **加粗** 与 `代码`。
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

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "实验报告.md"
DST = ROOT / "docs" / "实验报告.docx"

EA_BODY = "宋体"
EA_HEAD = "黑体"
LATIN = "Calibri"
MONO = "Consolas"
GRAY = RGBColor(0x59, 0x59, 0x59)
PLACEHOLDER = RGBColor(0xB0, 0x50, 0x00)


# ---------------------------------------------------------------- 字体工具
def set_run_font(run, *, latin=LATIN, ea=EA_BODY, size=None, bold=None,
                 color=None, italic=None) -> None:
    run.font.name = latin
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:ascii"), latin)
    rfonts.set(qn("w:hAnsi"), latin)
    rfonts.set(qn("w:eastAsia"), ea)
    rfonts.set(qn("w:cs"), latin)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color


def style_font(style, *, latin=LATIN, ea=EA_BODY, size=None, bold=None, color=None) -> None:
    style.font.name = latin
    if size is not None:
        style.font.size = Pt(size)
    if bold is not None:
        style.font.bold = bold
    if color is not None:
        style.font.color.rgb = color
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:ascii"), latin)
    rfonts.set(qn("w:hAnsi"), latin)
    rfonts.set(qn("w:eastAsia"), ea)


def shade(paragraph_or_cell, hex_fill: str) -> None:
    element = paragraph_or_cell._element
    pr = element.get_or_add_pPr() if hasattr(element, "get_or_add_pPr") else element.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    pr.append(shd)


def add_page_number_footer(section) -> None:
    paragraph = section.footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_end)
    set_run_font(run, size=9, color=GRAY)


# ---------------------------------------------------------------- 行内解析
INLINE_RE = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")


def add_inline(paragraph, text: str, *, size=10.5, ea=EA_BODY) -> None:
    for chunk in INLINE_RE.split(text):
        if not chunk:
            continue
        if chunk.startswith("**") and chunk.endswith("**") and len(chunk) > 4:
            run = paragraph.add_run(chunk[2:-2])
            set_run_font(run, ea=ea, size=size, bold=True)
        elif chunk.startswith("`") and chunk.endswith("`") and len(chunk) > 2:
            run = paragraph.add_run(chunk[1:-1])
            set_run_font(run, latin=MONO, ea=EA_BODY, size=size - 1)
            run.font.color.rgb = RGBColor(0xC7, 0x25, 0x4E)
        else:
            run = paragraph.add_run(chunk)
            set_run_font(run, ea=ea, size=size)


# ---------------------------------------------------------------- 各类块
def add_heading(doc, text: str, level: int) -> None:
    paragraph = doc.add_paragraph()
    sizes = {1: 16, 2: 13, 3: 11.5}
    paragraph.paragraph_format.space_before = Pt(14 if level == 1 else 10)
    paragraph.paragraph_format.space_after = Pt(6)
    paragraph.paragraph_format.keep_with_next = True
    run = paragraph.add_run(text)
    set_run_font(run, ea=EA_HEAD, size=sizes.get(level, 11), bold=True,
                 color=RGBColor(0x1F, 0x3B, 0x63) if level == 1 else RGBColor(0x2E, 0x4A, 0x6E))
    if level == 1:
        bottom_border(paragraph, "1F3B63", 8)


def bottom_border(paragraph, color: str, size: int) -> None:
    ppr = paragraph._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "2")
    bottom.set(qn("w:color"), color)
    pbdr.append(bottom)
    ppr.append(pbdr)


def add_body(doc, text: str) -> None:
    paragraph = doc.add_paragraph()
    fmt = paragraph.paragraph_format
    fmt.space_before = Pt(2)
    fmt.space_after = Pt(4)
    fmt.first_line_indent = Cm(0.0)
    fmt.line_spacing = 1.25
    add_inline(paragraph, text)


def add_bullet(doc, text: str, ordered: bool) -> None:
    paragraph = doc.add_paragraph(style="List Number" if ordered else "List Bullet")
    paragraph.paragraph_format.space_after = Pt(2)
    paragraph.paragraph_format.line_spacing = 1.2
    add_inline(paragraph, text)


def add_quote(doc, text: str) -> None:
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.left_indent = Cm(0.5)
    paragraph.paragraph_format.space_before = Pt(2)
    paragraph.paragraph_format.space_after = Pt(4)
    add_inline(paragraph, text, size=10)
    for run in paragraph.runs:
        run.font.color.rgb = GRAY


def add_placeholder(doc, text: str) -> None:
    text = text.replace("`", "")
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(6)
    paragraph.paragraph_format.space_after = Pt(8)
    run = paragraph.add_run(text)
    set_run_font(run, ea=EA_BODY, size=9.5, italic=True, color=PLACEHOLDER)
    ppr = paragraph._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    for side in ("top", "left", "bottom", "right"):
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:val"), "dashed")
        node.set(qn("w:sz"), "6")
        node.set(qn("w:space"), "4")
        node.set(qn("w:color"), "D9A441")
        pbdr.append(node)
    ppr.append(pbdr)


def add_image(doc, alt: str, rel_path: str) -> None:
    """插入一张居中的截图 + 图注；超高的图按可打印高度等比缩小。"""
    # md 里的图片路径是相对 docs/ 的（GitHub 也按 md 所在目录解析），
    # 这里优先按 md 所在目录找，兼容旧写法里的 docs/ 前缀。
    path = SRC.parent / rel_path
    if not path.exists():
        path = ROOT / rel_path
    if not path.exists():
        add_placeholder(doc, f"【截图缺失：{rel_path}】")
        return
    from PIL import Image

    with Image.open(path) as img:
        width_px, height_px = img.size
    max_w, max_h = Cm(15.4), Cm(20.5)
    width = max_w
    if width_px and height_px:
        height_cm = 15.4 * height_px / width_px
        if height_cm > 20.5:
            width = Cm(20.5 * width_px / height_px)

    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(8)
    paragraph.paragraph_format.space_after = Pt(2)
    paragraph.paragraph_format.keep_with_next = True
    paragraph.add_run().add_picture(str(path), width=width)

    caption = doc.add_paragraph()
    caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption.paragraph_format.space_after = Pt(10)
    run = caption.add_run(alt)
    set_run_font(run, ea=EA_BODY, size=9, italic=True, color=GRAY)


def add_code(doc, lines: list[str]) -> None:
    paragraph = doc.add_paragraph()
    fmt = paragraph.paragraph_format
    fmt.left_indent = Cm(0.3)
    fmt.space_before = Pt(4)
    fmt.space_after = Pt(6)
    fmt.line_spacing = 1.0
    shade(paragraph, "F4F5F7")
    text = "\n".join(lines)
    run = paragraph.add_run(text)
    set_run_font(run, latin=MONO, ea=EA_BODY, size=8.5)
    ppr = paragraph._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    for side in ("top", "left", "bottom", "right"):
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), "4")
        node.set(qn("w:space"), "4")
        node.set(qn("w:color"), "DDE1E6")
        pbdr.append(node)
    ppr.append(pbdr)


def add_table(doc, header: list[str], rows: list[list[str]]) -> None:
    table = doc.add_table(rows=1, cols=len(header))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    hdr = table.rows[0].cells
    for index, text in enumerate(header):
        cell = hdr[index]
        cell.text = ""
        paragraph = cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_after = Pt(2)
        add_inline(paragraph, text, size=9)
        for run in paragraph.runs:
            run.font.bold = True
            run.font.color.rgb = RGBColor(0x1F, 0x3B, 0x63)
        shade(cell, "E8EEF7")
    for values in rows:
        cells = table.add_row().cells
        for index in range(len(header)):
            text = values[index] if index < len(values) else ""
            cell = cells[index]
            cell.text = ""
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(2)
            add_inline(paragraph, text, size=9)
    # 表头重复
    tr_pr = table.rows[0]._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_after = Pt(2)
    spacer.paragraph_format.line_spacing = 1.0
    for run in spacer.runs:
        run.font.size = Pt(4)


# ---------------------------------------------------------------- 封面
def build_cover(doc) -> None:
    """GitHub 项目页式开头：标题 + 一句话定位 + 元信息，不含个人身份字段。"""
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(28)

    kicker = doc.add_paragraph()
    kicker.paragraph_format.space_after = Pt(4)
    run = kicker.add_run("实验报告")
    set_run_font(run, ea=EA_HEAD, size=11, color=GRAY)

    title = doc.add_paragraph()
    title.paragraph_format.space_before = Pt(0)
    title.paragraph_format.space_after = Pt(2)
    run = title.add_run("医疗知识图谱对话系统")
    set_run_font(run, ea=EA_HEAD, size=26, bold=True, color=RGBColor(0x14, 0x2A, 0x47))

    rule = doc.add_paragraph()
    rule.paragraph_format.space_before = Pt(4)
    rule.paragraph_format.space_after = Pt(8)
    bottom_border(rule, "C9D3E0", 6)

    meta = doc.add_paragraph()
    meta.paragraph_format.space_before = Pt(6)
    run = meta.add_run("完成日期　2026 年 11 月 19 日　·　运行环境　Python 3.12 + TuGraph 4.x　·　"
                       "图谱规模　93 节点 / 138 边　·　测例　73 条")
    set_run_font(run, ea=EA_BODY, size=9.5, color=GRAY)

    note = doc.add_paragraph()
    note.paragraph_format.space_before = Pt(4)
    run = note.add_run("本报告数据仅用于课程实验，未经医学核验，不能作为诊疗依据。")
    set_run_font(run, ea=EA_BODY, size=9, color=GRAY)

    intro = doc.add_paragraph()
    intro.paragraph_format.space_before = Pt(2)
    run = intro.add_run("复现步骤见附录 A，语料与脚本分别在 data/ 与 scripts/ 目录下。")
    set_run_font(run, ea=EA_BODY, size=9, color=GRAY)


# ---------------------------------------------------------------- 主流程
def parse_markdown(text: str):
    blocks = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            index += 1
            code = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index].rstrip())
                index += 1
            index += 1
            blocks.append(("code", code))
            continue
        if not stripped:
            index += 1
            continue
        if stripped.startswith("|"):
            table_lines = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index].strip())
                index += 1
            blocks.append(("table", table_lines))
            continue
        if stripped.startswith("#### "):
            blocks.append(("h3", stripped[5:]))
        elif stripped.startswith("### "):
            blocks.append(("h2", stripped[4:]))
        elif stripped.startswith("## "):
            blocks.append(("h1", stripped[3:]))
        elif stripped.startswith("# "):
            blocks.append(("title", stripped[2:]))
        elif stripped.startswith("> "):
            blocks.append(("quote", stripped[2:]))
        elif stripped.startswith("【截图"):
            blocks.append(("placeholder", stripped))
        elif re.match(r"^!\[[^\]]*\]\([^)]+\)$", stripped):
            match = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", stripped)
            blocks.append(("image", (match.group(1), match.group(2))))
        elif re.match(r"^[-*] ", stripped):
            blocks.append(("bullet", stripped[2:]))
        elif re.match(r"^\d+\. ", stripped):
            blocks.append(("number", re.sub(r"^\d+\. ", "", stripped)))
        elif set(stripped) <= {"-", " "}:
            pass
        else:
            blocks.append(("p", stripped))
        index += 1
    return blocks


def build_table(lines: list[str]):
    rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells if cell):
            continue
        rows.append(cells)
    header, body = rows[0], rows[1:]
    width = len(header)
    body = [row + [""] * (width - len(row)) if len(row) < width else row[:width] for row in body]
    return header, body


def main() -> None:
    text = SRC.read_text(encoding="utf-8")
    doc = Document()

    section = doc.sections[0]
    section.page_height = Cm(29.7)
    section.page_width = Cm(21.0)
    section.top_margin = Cm(2.4)
    section.bottom_margin = Cm(2.2)
    section.left_margin = Cm(2.6)
    section.right_margin = Cm(2.4)

    normal = doc.styles["Normal"]
    style_font(normal, size=10.5)
    normal.paragraph_format.line_spacing = 1.25

    add_page_number_footer(section)
    build_cover(doc)

    for kind, payload in parse_markdown(text):
        if kind == "title":
            continue
        if kind == "h1":
            add_heading(doc, payload, 1)
        elif kind == "h2":
            add_heading(doc, payload, 2)
        elif kind == "h3":
            add_heading(doc, payload, 3)
        elif kind == "p":
            add_body(doc, payload)
        elif kind == "quote":
            add_quote(doc, payload)
        elif kind == "placeholder":
            add_placeholder(doc, payload)
        elif kind == "image":
            add_image(doc, payload[0], payload[1])
        elif kind == "bullet":
            add_bullet(doc, payload, ordered=False)
        elif kind == "number":
            add_bullet(doc, payload, ordered=True)
        elif kind == "code":
            add_code(doc, payload)
        elif kind == "table":
            header, body = build_table(payload)
            add_table(doc, header, body)

    DST.parent.mkdir(parents=True, exist_ok=True)
    doc.save(DST)
    print(f"已生成 {DST}")
    print(f"段落 {len(doc.paragraphs)} 个，表格 {len(doc.tables)} 个")


if __name__ == "__main__":
    main()