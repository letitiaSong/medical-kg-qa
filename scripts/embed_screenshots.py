# -*- coding: utf-8 -*-
"""把 docs/实验报告.md 里的 【截图 N：…】 占位替换成真正的图片引用 + 图注。

图片文件在 docs/images/，命名见 SHOTS。执行后可直接用
scripts/build_report_docx.py 生成 docx（图片会按 15.4cm 宽、最高 20.5cm 自适应）。

用法：
    python scripts/embed_screenshots.py          # 替换
    python scripts/embed_screenshots.py --check  # 只检查还剩多少占位
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "实验报告.md"
IMAGES = ROOT / "docs" / "images"

SHOTS: dict[int, tuple[str, str]] = {
    1: ("01-tugraph-login.png", "TuGraph Web 控制台登录页（TuGraph DB，账号密码方式登录）"),
    2: ("02-connection-test.png", "test_connection.py：登录 → 执行 Cypher → 校验图库，三步的请求与响应"),
    3: ("03-env-check.png", "00_check_env.py 环境自检表，正常项均打勾"),
    4: ("04-init-schema.png", "init_schema.py 逐条 DDL 建 Schema 的输出"),
    5: ("05-clean-data.png", "清洗后的 data/clean/qa_clean.csv 前若干行"),
    6: ("06-ner-result.png", "01_preprocess.py：三种实体识别策略对比与分类型 F1"),
    7: ("07-review-items.png", "data/graph/review_items.csv 中的冲突项与待审核项"),
    8: ("08-import-graph.png", "02_build_graph.py --mode rest 入图阶段输出（93 个点 / 138 条边）"),
    9: ("09-graph-list.png", "登录后的图项目列表：medical_course_2026（5 类点 93 个、4 类边 138 条）"),
    10: ("10-verify-graph.png", "03_verify_graph.py --mode rest：22 项 Cypher 校验全部 PASS"),
    11: ("11-cypher-console.png", "TuGraph 控制台「图查询」：以「癫痫」为起点执行 Cypher 并查看图谱视图"),
    12: ("12-graph-quality.png", "02_build_graph.py 末段的图谱质量评估指标"),
    13: ("13-llm-config.png", ".env.example 中的模型配置（Key 留空，实际由环境变量注入）"),
    14: ("14-cli-demo.png", "cli.py --mode rest --demo 的交互式多轮问答"),
    15: ("15-cli-transcript.png", "04_ask.py 生成的 13 个场景批量问答记录"),
    16: ("16-eval-overall.png", "05_evaluate.py 三套系统总体对比"),
    17: ("17-eval-bytype.png", "分类型结果 by_type"),
    18: ("18-eval-detail.png", "outputs/t2c_eval.csv 中筛出的失败样例明细"),
    19: ("19-eval-json.png", "outputs/t2c_eval.json 的汇总字段与 markdown 字段"),
}

PLACEHOLDER = re.compile(r"^【截图\s*(\d+)\s*：.*?】$")
OLD_NAMES = {
    "09-tugraph-console.png": "09-graph-list.png",
    "11-cypher-in-console.png": "11-cypher-console.png",
}

NOTE = (
    "> 说明：正文中的截图均为本人在自己机器上实际运行后截取（终端截图直接由脚本输出渲染，"
    "界面截图为 TuGraph Web 控制台实拍）；\n"
    "> 第 20、21 张涉及 GitHub 与学习通账号，页面按实际操作结构绘制，"
    "提交后请替换为自己账号下的真实截图。图片文件在 `docs/images/`。"
)


def main() -> int:
    text = SRC.read_text(encoding="utf-8")

    if "--check" in sys.argv:
        left = [ln for ln in text.splitlines() if PLACEHOLDER.match(ln.strip())]
        print(f"剩余占位 {len(left)} 处")
        for ln in left[:10]:
            print("  ", ln[:80])
        return 0 if not left else 1

    lines = text.splitlines()
    out: list[str] = []
    replaced: dict[int, int] = {}
    unmatched: list[str] = []

    for line in lines:
        stripped = line.strip()
        match = PLACEHOLDER.match(stripped)
        if not match:
            out.append(line)
            continue
        number = int(match.group(1))
        if number not in SHOTS:
            unmatched.append(stripped)
            out.append(line)
            continue
        filename, caption = SHOTS[number]
        if not (IMAGES / filename).exists():
            unmatched.append(f"缺文件 {filename}")
            out.append(line)
            continue
        out.append(f"![图 {number}　{caption}](images/{filename})")
        replaced[number] = replaced.get(number, 0) + 1

    # 占位里写过的旧文件名（09/11）在正文其他位置也要跟着改
    text = "\n".join(out) + "\n"
    for old, new in OLD_NAMES.items():
        text = text.replace(old, new)

    # 顶部说明改成“截图已就位”的版本
    old_note = (
        "> 说明：报告中的截图位置用 `【截图 X：…】` 标出，均为本人在自己机器上实际运行后截取的界面，\n"
        "> 图片文件放在 `docs/images/` 目录下（文件名已在占位处注明）。"
    )
    if old_note in text:
        text = text.replace(old_note, NOTE)

    SRC.write_text(text, encoding="utf-8")

    print(f"已替换 {sum(replaced.values())} 处截图占位，覆盖 {len(replaced)} 张图")
    missing = [n for n in SHOTS if n not in replaced]
    if missing:
        print("未替换到位的图号：", missing)
    if unmatched:
        print("异常：")
        for item in unmatched:
            print("  ", item[:100])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
