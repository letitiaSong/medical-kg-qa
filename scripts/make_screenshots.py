"""把脚本的真实运行输出渲染成"终端截图"，并把数据文件渲染成表格截图。

实验报告需要 21 张截图，其中绝大多数是命令行输出或数据文件；
本脚本按 `docs/images/README.md` 的编号生成 PNG，内容直接来自真实运行，
不手工编造任何数字。

用法：
    python scripts/make_screenshots.py                 # 连真实 TuGraph（--mode rest）
    python scripts/make_screenshots.py --mock          # 离线模拟库
    python scripts/make_screenshots.py --only 02,03    # 只生成指定编号
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "docs" / "images"
PY = sys.executable

# ---------------------------------------------------------------- 画布参数
WIDTH = 1500
MARGIN = 26
TITLE_H = 42
FONT_SIZE = 15
LINE_H = 26
MAX_LINES = 62
PROMPT = r"PS E:\工作\医疗图谱\medical_kg_qa>"

BG = (30, 30, 30)
TITLE_BG = (45, 45, 48)
TITLE_FG = (200, 200, 205)
FG = (228, 228, 228)
GREEN = (126, 214, 140)
RED = (255, 118, 118)
YELLOW = (255, 202, 112)
CYAN = (120, 205, 235)
GRAY = (150, 150, 155)

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]


def load_font(size: int = FONT_SIZE) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size, index=0)
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default()


ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def color_of(line: str, kind: str) -> tuple[int, int, int]:
    if kind == "prompt":
        return GREEN
    stripped = line.strip()
    if stripped.startswith("[PASS]") or stripped.startswith("[✓]"):
        return GREEN
    if stripped.startswith("[FAIL]") or stripped.startswith("[×]"):
        return RED
    if stripped.startswith("[!]") or stripped.startswith("["):
        return YELLOW
    if set(stripped) <= set("=-─ "):
        return GRAY
    if stripped.startswith("步骤") or stripped.startswith("[1/") or stripped.startswith("[2/"):
        return CYAN
    return FG


def wrap_line(text: str, font, max_width: int) -> list[str]:
    if not text:
        return [""]
    out, current, current_w = [], "", 0.0
    for ch in text:
        w = font.getlength(ch)
        if current_w + w > max_width and current:
            out.append(current)
            current, current_w = ch, w
        else:
            current += ch
            current_w += w
    out.append(current)
    return out


def render_terminal(segments: list[tuple[str, str]], out_path: Path, title: str) -> Path:
    """segments: [(kind, text)]，kind ∈ {prompt, out}。"""
    font = load_font()
    max_width = WIDTH - 2 * MARGIN - 8

    lines: list[tuple[str, str]] = []
    for kind, text in segments:
        text = strip_ansi(text.rstrip("\n"))
        chunks = wrap_line(text, font, max_width - (font.getlength("    ") if kind == "out" else 0))
        for i, chunk in enumerate(chunks):
            lines.append((kind if i == 0 else kind, chunk))

    elided = 0
    if len(lines) > MAX_LINES:
        head, tail = lines[: MAX_LINES - 20], lines[-(20 - 1):]
        elided = len(lines) - len(head) - len(tail)
        lines = head + [("note", f"…… 中间省略 {elided} 行 ……")] + tail

    height = TITLE_H + MARGIN * 2 + len(lines) * LINE_H + 10
    image = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(image)

    # 标题栏
    draw.rectangle([0, 0, WIDTH, TITLE_H], fill=TITLE_BG)
    for i, dot in enumerate([(46, 21, 7), (68, 21, 7), (90, 21, 7)]):
        x, y, r = dot
        draw.ellipse([x - r, y - r, x + r, y + r], fill=[(255, 95, 86), (255, 189, 46), (39, 201, 63)][i])
    draw.text((112, 12), title, font=load_font(14), fill=TITLE_FG)

    y = TITLE_H + MARGIN
    for kind, line in lines:
        x = MARGIN
        if kind == "prompt":
            draw.text((x, y), "❯ ", font=font, fill=GREEN)
            draw.text((x + 22, y), line, font=font, fill=GREEN)
        elif kind == "note":
            draw.text((x + 22, y), line, font=font, fill=GRAY)
        else:
            draw.text((x + 22, y), line, font=font, fill=color_of(line, kind))
        y += LINE_H

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, "PNG", optimize=True)
    return out_path


def render_table(rows: list[list[str]], out_path: Path, title: str, max_rows: int = 26) -> Path:
    """把 CSV 渲染成电子表格样式的截图。"""
    font = load_font(14)
    header_font = load_font(14)
    row_h, pad_x = 30, 10

    elided = 0
    if len(rows) > max_rows:
        elided = len(rows) - max_rows
        rows = rows[:max_rows]
        rows.append([f"…… 其余 {elided} 行省略 ……"] + [""] * (len(rows[0]) - 1))

    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    widths = []
    for c in range(ncols):
        w = max(font.getlength(r[c]) for r in rows)
        widths.append(min(max(w + pad_x * 2, 70), 340))

    total = sum(widths)
    if total + 2 * MARGIN > WIDTH:
        scale = (WIDTH - 2 * MARGIN) / total
        widths = [max(60, int(w * scale)) for w in widths]
    total = sum(widths)
    height = TITLE_H + 2 * MARGIN + len(rows) * row_h + 8

    image = Image.new("RGB", (max(WIDTH, total + 2 * MARGIN), height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, image.width, TITLE_H], fill=TITLE_BG)
    for i, dot in enumerate([(46, 21, 7), (68, 21, 7), (90, 21, 7)]):
        x, y, r = dot
        draw.ellipse([x - r, y - r, x + r, y + r], fill=[(255, 95, 86), (255, 189, 46), (39, 201, 63)][i])
    draw.text((112, 12), title, font=load_font(14), fill=TITLE_FG)

    y = TITLE_H + MARGIN
    for i, row in enumerate(rows):
        x = MARGIN
        bg = (232, 238, 247) if i == 0 else ((250, 251, 252) if i % 2 == 0 else (255, 255, 255))
        draw.rectangle([MARGIN, y, MARGIN + total, y + row_h], fill=bg, outline=(208, 212, 218))
        for c, cell in enumerate(row):
            text = cell
            while font.getlength(text) > widths[c] - 2 * pad_x and len(text) > 1:
                text = text[:-1]
            if text != cell:
                text = text[:-1] + "…"
            draw.text((x + pad_x, y + 7), text, font=header_font, fill=(32, 32, 32))
            x += widths[c]
            if c:
                draw.line([x, y, x, y + row_h], fill=(208, 212, 218))
        y += row_h

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, "PNG", optimize=True)
    return out_path


def run_cmd(args: list[str]) -> list[str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [PY] + args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    text = strip_ansi(proc.stdout + ("\n" + proc.stderr if proc.stderr.strip() else ""))
    return [ln.rstrip() for ln in text.splitlines()]


def section(lines: list[str], start: str | None, end: str | None) -> list[str]:
    begin = 0
    if start:
        for i, ln in enumerate(lines):
            if start in ln:
                begin = i
                break
    finish = len(lines)
    if end:
        for i in range(begin + 1, len(lines)):
            if end in lines[i]:
                finish = i
                break
    return lines[begin:finish]


def read_csv_rows(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.reader(handle)]


def build_shots(mock: bool) -> dict[str, dict]:
    graph_args = ["--mock"] if mock else ["--mode", "rest"]
    shots: dict[str, dict] = {}

    shots["02"] = {
        "title": "测试 TuGraph Python 客户端连接",
        "cmd": ["scripts/test_connection.py"],
        "prompt": "python scripts/test_connection.py",
    }
    shots["03"] = {
        "title": "环境自检",
        "cmd": ["scripts/00_check_env.py"] + (["--mock"] if mock else []),
        "prompt": "python scripts/00_check_env.py",
    }
    shots["04"] = {
        "title": "建图与建 Schema",
        "cmd": ["scripts/init_schema.py"] if not mock else ["scripts/init_schema.py"],
        "prompt": "python scripts/init_schema.py",
        "fallback_cmd": ["scripts/init_schema.py", "--dry-run"],
        "fallback_prompt": "python scripts/init_schema.py --dry-run",
    }
    shots["06"] = {
        "title": "实体识别与关系抽取",
        "cmd": ["scripts/01_preprocess.py"],
        "prompt": "python scripts/01_preprocess.py",
    }
    shots["08"] = {
        "title": "构建图谱并写入图库",
        "cmd": ["scripts/02_build_graph.py"] + graph_args,
        "prompt": "python scripts/02_build_graph.py " + ("--mock" if mock else "--mode rest"),
        "end": "图谱质量评估",
    }
    shots["10"] = {
        "title": "用标准 Cypher 验证入图结果",
        "cmd": ["scripts/03_verify_graph.py"] + graph_args,
        "prompt": "python scripts/03_verify_graph.py " + ("--mock" if mock else "--mode rest"),
    }
    shots["12"] = {
        "title": "图谱质量评估",
        "cmd": ["scripts/02_build_graph.py"] + graph_args,
        "prompt": "python scripts/02_build_graph.py " + ("--mock" if mock else "--mode rest"),
        "start": "图谱质量评估",
    }
    shots["13"] = {
        "title": "大模型 API 配置（Key 已打码）",
        "file": ".env.example",
        "prompt": "type .env.example   # .env 同结构，Key 用环境变量注入",
    }
    shots["14"] = {
        "title": "交互式问答演示",
        "cmd": ["cli.py"] + (["--mock", "--llm", "fake"] if mock else ["--mode", "rest"]) + ["--demo"],
        "prompt": "python cli.py " + ("--mock --llm fake --demo" if mock else "--mode rest --demo"),
    }
    shots["15"] = {
        "title": "13 个场景的批量问答记录",
        "cmd": ["scripts/04_ask.py"] + graph_args + (["--fake"] if mock else []),
        "prompt": "python scripts/04_ask.py " + ("--mock --fake" if mock else "--mode rest"),
    }
    shots["16"] = {
        "title": "三套系统总体对比",
        "cmd": ["scripts/05_evaluate.py"] + graph_args,
        "prompt": "python scripts/05_evaluate.py " + ("--mock" if mock else "--mode rest"),
        "start": "| 系统 |",
        "end": "分类型结果",
    }
    shots["17"] = {
        "title": "分类型结果",
        "cmd": ["scripts/05_evaluate.py"] + graph_args,
        "prompt": "python scripts/05_evaluate.py " + ("--mock" if mock else "--mode rest"),
        "start": "分类型结果",
        "end": "明细已写入",
    }
    shots["05"] = {
        "title": "清洗后的问答数据 data/clean/qa_clean.csv",
        "csv": "data/clean/qa_clean.csv",
        "max_rows": 24,
    }
    shots["07"] = {
        "title": "待审核与冲突项 data/graph/review_items.csv",
        "csv": "data/graph/review_items.csv",
        "max_rows": 24,
    }
    shots["18"] = {
        "title": "评测失败样例 outputs/t2c_eval.csv（correct=False）",
        "csv": "outputs/t2c_eval.csv",
        "filter_failed": True,
        "max_rows": 22,
    }
    shots["19"] = {
        "title": "评测汇总 outputs/t2c_eval.json",
        "file": "outputs/t2c_eval.json",
        "prompt": "type outputs\\t2c_eval.json",
    }
    return shots


def make_one(key: str, spec: dict, mock: bool) -> Path | None:
    if "csv" in spec:
        rows = read_csv_rows(ROOT / spec["csv"])
        if spec.get("filter_failed") and rows:
            header, body = rows[0], rows[1:]
            idx = header.index("correct") if "correct" in header else None
            if idx is not None:
                body = [r for r in body if str(r[idx]).strip().lower() not in ("true", "1", "yes")]
            rows = [header] + body
        target = IMAGES / f"{key}-{SHOT_NAMES[key]}.png"
        return render_table(rows, target, spec["title"], spec.get("max_rows", 26))

    if "file" in spec:
        text = (ROOT / spec["file"]).read_text(encoding="utf-8", errors="replace")
        segments = [("prompt", spec["prompt"])]
        for line in text.splitlines():
            segments.append(("out", line))
        target = IMAGES / f"{key}-{SHOT_NAMES[key]}.png"
        return render_terminal(segments, target, spec["title"])

    cmd = spec["cmd"]
    prompt = spec["prompt"]
    lines = run_cmd(cmd)
    # 需要真实 TuGraph 但连不上时，退回 --dry-run（只打印 DDL）
    if spec.get("fallback_cmd") and any(
        marker in "\n".join(lines) for marker in ("无法连接", "TuGraph HTTP", "不可用")
    ):
        cmd = spec["fallback_cmd"]
        prompt = spec["fallback_prompt"]
        lines = run_cmd(cmd)

    body = section(lines, spec.get("start"), spec.get("end")) if ("start" in spec or "end" in spec) else lines
    segments = [("prompt", prompt)] + [("out", ln) for ln in body]
    target = IMAGES / f"{key}-{SHOT_NAMES[key]}.png"
    return render_terminal(segments, target, spec["title"])


SHOT_NAMES = {
    "02": "connection-test",
    "03": "env-check",
    "04": "init-schema",
    "05": "clean-data",
    "06": "ner-result",
    "07": "review-items",
    "08": "import-graph",
    "10": "verify-graph",
    "12": "graph-quality",
    "13": "llm-config",
    "14": "cli-demo",
    "15": "cli-transcript",
    "16": "eval-overall",
    "17": "eval-bytype",
    "18": "eval-detail",
    "19": "eval-json",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="生成实验报告用的操作截图")
    parser.add_argument("--mock", action="store_true", help="用离线模拟库运行")
    parser.add_argument("--only", default="", help="只生成指定编号，如 02,03,06")
    args = parser.parse_args()

    wanted = [k.strip().zfill(2) for k in args.only.split(",") if k.strip()] or sorted(SHOT_NAMES)
    shots = build_shots(args.mock)
    IMAGES.mkdir(parents=True, exist_ok=True)

    for key in wanted:
        spec = shots.get(key)
        if spec is None:
            print(f"[跳过] {key}：由浏览器/手工截图生成")
            continue
        path = make_one(key, spec, args.mock)
        print(f"[OK] {key} {spec['title']} -> {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())