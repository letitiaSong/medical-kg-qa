# -*- coding: utf-8 -*-
"""第 3 步演示：批量跑一组问答，生成可直接贴进报告的对话记录。

覆盖：单跳查询、反向查询、计数、多轮追问、无法回答、域外问题。
输出：outputs/qa_transcript.txt（纯文本）+ outputs/qa_transcript.json（结构化）

用法：
    python scripts/04_ask.py --mock --fake
    python scripts/04_ask.py --mock            # 有 API Key 时自动用大模型
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from medkg.config import OUTPUT_DIR, ensure_dirs  # noqa: E402
from medkg.extract.dictionary import load_dictionary  # noqa: E402
from medkg.qa import QAEngine  # noqa: E402
from medkg.storage import open_store  # noqa: E402
from medkg.t2c import Text2Cypher  # noqa: E402

# 每个元素是一段对话：(标题, [问题, ...])
DIALOGUES: list[tuple[str, list[str]]] = [
    ("单跳：疾病 -> 检查", ["癫痫要做哪些检查？"]),
    ("单跳：疾病 -> 症状", ["肝硬化有哪些症状？"]),
    ("单跳：疾病 -> 用药", ["心力衰竭吃什么药？"]),
    ("单跳：疾病 -> 科室", ["偏头痛属于哪个科室？"]),
    ("反向：症状 -> 疾病", ["哪些疾病会出现头痛？"]),
    ("反向：药品 -> 疾病", ["哪些疾病需要用奥美拉唑？"]),
    ("多跳：两个疾病的共同用药", ["脑梗死和冠心病有没有相同的用药？"]),
    ("聚合：疾病计数", ["图谱里一共有多少种疾病？"]),
    ("多轮：检查 -> 科室", ["癫痫要做哪些检查？", "那属于哪个科室？"]),
    ("多轮：症状 -> 用药 -> 检查", ["胃溃疡有哪些症状？", "吃什么药？", "那要做什么检查？"]),
    ("实体存在但缺关系", ["糖尿病有哪些症状？"]),
    ("实体未入库", ["青光眼用什么药？"]),
    ("域外问题", ["今天天气怎么样？"]),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="批量问答并生成对话记录")
    parser.add_argument("--mode", choices=["auto", "rest", "mock"], default=None)
    parser.add_argument("--llm", choices=["auto", "real", "fake"], default=None)
    parser.add_argument("--mock", action="store_true", help="等同 --mode mock")
    parser.add_argument("--fake", action="store_true", help="等同 --llm fake")
    parser.add_argument("--out", default=None, help="文本输出路径，默认 outputs/qa_transcript.txt")
    args = parser.parse_args(argv)
    if args.mock:
        args.mode = "mock"
    if args.fake:
        args.llm = "fake"

    ensure_dirs()
    store, note = open_store(mode=args.mode, verbose=False)
    store.connect()
    dictionary = load_dictionary()
    t2c = Text2Cypher(store=store, dictionary=dictionary, mode=args.llm, verbose=False)
    engine = QAEngine(store=store, dictionary=dictionary, t2c=t2c, verbose=False)

    lines: list[str] = []
    records: list[dict] = []

    def emit(text: str = "") -> None:
        lines.append(text)
        print(text)

    emit("===== 医学知识图谱问答系统 · 对话记录 =====")
    emit(f"图库：{store.name}（{note}）")
    emit(f"节点 {store.count_nodes()} 个 / 关系 {store.count_edges()} 条")
    emit(f"模型：{t2c.llm.model}（{t2c.llm.name}）")
    emit()

    for index, (title, questions) in enumerate(DIALOGUES, start=1):
        engine.reset()
        emit(f"--- 场景 {index}：{title} ---")
        for question in questions:
            emit(f"问题> {question}")
            response = engine.ask(question)
            emit(f"回答> {response.answer}")
            if response.cypher:
                emit(f"Cypher> {response.cypher}")
            emit(f"[状态] intent={response.intent} source={response.source} "
                 f"rows={response.row_count} 行 耗时={response.elapsed_ms:.0f}ms")
            emit()
            records.append(
                {
                    "scene": title,
                    "question": question,
                    "answer": response.answer,
                    "cypher": response.cypher,
                    "intent": response.intent,
                    "source": response.source,
                    "row_count": response.row_count,
                    "ok": response.ok,
                    "elapsed_ms": round(response.elapsed_ms, 1),
                }
            )
    emit("问答结束。")
    store.close()

    out_path = Path(args.out) if args.out else OUTPUT_DIR / "qa_transcript.txt"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUTPUT_DIR / "qa_transcript.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    total = len(records)
    answered = sum(1 for r in records if r["source"] != "none" and r["cypher"])
    print(f"\n共 {total} 轮提问，生成 Cypher {answered} 条，记录写入 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())