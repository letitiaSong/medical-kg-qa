# -*- coding: utf-8 -*-
"""Text2Cypher 评测：规则基线 / 消融 / 本系统 三组对比。

指标：
  · 可执行率：生成的 Cypher 能通过安全校验并在图谱上跑通的比例
  · EM（Exact Match）：规范化后与 gold_cypher 完全一致
  · EX（Execution Accuracy）：执行结果（按 gold 的目标列做集合比较）与标准答案一致
  · 端到端正确率：可回答问题答对 + 不可回答问题正确拒答

用法：
    python scripts/05_evaluate.py                 # 离线三组对比（无需 API Key）
    python scripts/05_evaluate.py --llm real      # 接真实大模型（需要 .env 里的 DASHSCOPE_API_KEY）
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from medkg.config import OUTPUT_DIR, T2C_TESTSET, ensure_dirs  # noqa: E402
from medkg.extract.dictionary import load_dictionary  # noqa: E402
from medkg.qa import QAEngine  # noqa: E402
from medkg.storage import GraphError, open_store  # noqa: E402
from medkg.t2c import FakeLLM, Text2Cypher, build_llm  # noqa: E402

UNANSWERABLE_TYPES = {"无法回答", "域外问题", "边界问题"}
EMPTY_TYPES = {"空结果"}


def load_cases() -> list[dict]:
    with T2C_TESTSET.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def normalize_cypher(text: str) -> str:
    text = (text or "").strip().rstrip(";")
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def value_set(result, column: str | None) -> set[str]:
    if result is None:
        return set()
    columns = list(result.columns)
    if column and column in columns:
        index = columns.index(column)
    else:
        index = 0
    values: set[str] = set()
    for row in result.rows:
        cell = row[index]
        if cell is None:
            continue
        if isinstance(cell, float) and cell.is_integer():
            cell = int(cell)
        values.add(str(cell).strip())
    return values


def run_variant(name: str, store, dictionary, llm, cases, max_retries: int = 1) -> list[dict]:
    engine = QAEngine(
        store=store,
        dictionary=dictionary,
        t2c=Text2Cypher(store=store, dictionary=dictionary, llm=llm, max_retries=max_retries),
        verbose=False,
    )
    records: list[dict] = []
    for case in cases:
        engine.reset()
        if case["context"].strip():
            engine.ask(case["context"].strip())
        response = engine.ask(case["question"].strip())

        gold_cypher = case["gold_cypher"].strip()
        gold_result = None
        gold_column = None
        if gold_cypher:
            try:
                gold_result = store.execute(gold_cypher)
                gold_column = list(gold_result.columns)[0]
            except GraphError as exc:  # pragma: no cover - 测试集自身错误
                print(f"[warn] {case['id']} gold 查询失败：{exc}")
        gold_set = value_set(gold_result, gold_column)
        pred_set = value_set(store.execute(response.cypher), gold_column) if response.executed else set()

        unanswerable = case["type"] in UNANSWERABLE_TYPES
        if unanswerable:
            correct = (not response.ok) and not response.executed
        elif case["type"] in EMPTY_TYPES:
            correct = response.executed and response.row_count == 0
        else:
            correct = response.executed and pred_set == gold_set

        records.append(
            {
                "variant": name,
                "id": case["id"],
                "type": case["type"],
                "question": case["question"],
                "context": case["context"],
                "gold_cypher": gold_cypher,
                "pred_cypher": response.cypher,
                "executed": response.executed,
                "unanswerable": unanswerable,
                "em": bool(gold_cypher) and normalize_cypher(response.cypher) == normalize_cypher(gold_cypher),
                "ex": (pred_set == gold_set) if gold_cypher else False,
                "correct": bool(correct),
                "note": case["note"],
            }
        )
    return records


def summarize(records: list[dict]) -> dict:
    total = len(records)
    answerable = [r for r in records if not r["unanswerable"]]
    executed = [r for r in answerable if r["executed"]]
    em = sum(1 for r in records if r["em"])
    ex = sum(1 for r in answerable if r["ex"])
    correct = sum(1 for r in records if r["correct"])
    return {
        "n": total,
        "n_answerable": len(answerable),
        "executable": len(executed),
        "executable_rate": len(executed) / len(answerable) if answerable else 0.0,
        "em": em,
        "em_rate": em / total if total else 0.0,
        "ex": ex,
        "ex_rate": ex / len(answerable) if answerable else 0.0,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
    }


def by_type(records: list[dict]) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for record in records:
        groups.setdefault(record["type"], []).append(record)
    return {key: summarize(value) for key, value in groups.items()}


def _rate(summary: dict, key: str) -> str:
    if key in {"executable_rate", "ex_rate"} and summary["n_answerable"] == 0:
        return "—"
    return f"{summary[key]:.1%}"


def markdown_table(variants: list[tuple[str, dict]]) -> str:
    header = "| 系统 | 可执行率 | EM | EX | 端到端正确率 |\n|---|---|---|---|---|"
    lines = [header]
    for name, summary in variants:
        lines.append(
            f"| {name} | {_rate(summary, 'executable_rate')} | {_rate(summary, 'em_rate')} "
            f"| {_rate(summary, 'ex_rate')} | {_rate(summary, 'accuracy')} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Text2Cypher 评测")
    parser.add_argument("--mode", choices=["auto", "rest", "mock"], default=None)
    parser.add_argument("--mock", action="store_true", help="等同 --mode mock")
    parser.add_argument("--llm", choices=["auto", "real", "fake"], default="fake")
    parser.add_argument("--max-retries", type=int, default=1)
    args = parser.parse_args(argv)
    if args.mock:
        args.mode = "mock"

    ensure_dirs()
    cases = load_cases()
    store, note = open_store(mode=args.mode, verbose=False)
    store.connect()
    dictionary = load_dictionary()

    variants: list[tuple[str, object]] = []
    if args.llm == "real":
        llm, llm_note = build_llm("real", dictionary=dictionary, verbose=False)
        variants.append(("大模型（Qwen，Schema+实体提示）", llm))
        print(f"使用真实模型：{llm_note}")
    else:
        variants.extend(
            [
                ("B0 关键词基线", FakeLLM(dictionary, naive=True)),
                ("B1 消融：去掉别名归一", FakeLLM(dictionary, canonical=False)),
                ("B2 本系统（规则管线）", FakeLLM(dictionary)),
            ]
        )

    all_records: list[dict] = []
    summaries: list[tuple[str, dict]] = []
    for name, llm in variants:
        records = run_variant(name, store, dictionary, llm, cases, max_retries=args.max_retries)
        all_records.extend(records)
        summary = summarize(records)
        summaries.append((name, summary))
        print(f"\n[{name}] 可执行率 {summary['executable_rate']:.1%}  "
              f"EM {summary['em_rate']:.1%}  EX {summary['ex_rate']:.1%}  "
              f"端到端 {summary['accuracy']:.1%}")

    print("\n" + markdown_table(summaries))

    best_name, best_records = summaries[-1][0], [r for r in all_records if r["variant"] == summaries[-1][0]]
    print(f"\n分类型结果（{best_name}）：")
    print("| 类型 | 条数 | 可执行率 | EX | 端到端 |")
    print("|---|---|---|---|---|")
    type_stats = by_type(best_records)
    for key, summary in type_stats.items():
        print(f"| {key} | {summary['n']} | {_rate(summary, 'executable_rate')} "
              f"| {_rate(summary, 'ex_rate')} | {_rate(summary, 'accuracy')} |")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUTPUT_DIR / "t2c_eval.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(all_records[0].keys()))
        writer.writeheader()
        writer.writerows(all_records)
    report = {
        "note": note,
        "variants": [{"name": name, **summary} for name, summary in summaries],
        "by_type": {name: by_type([r for r in all_records if r["variant"] == name]) for name, _ in summaries},
        "markdown": markdown_table(summaries),
    }
    (OUTPUT_DIR / "t2c_eval.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n明细已写入 {OUTPUT_DIR / 't2c_eval.csv'}")
    print(f"汇总已写入 {OUTPUT_DIR / 't2c_eval.json'}")

    failed = [r for r in best_records if not r["correct"]]
    if failed:
        print(f"\n未通过样例（{len(failed)} 条）：")
        for record in failed[:10]:
            print(f"  {record['id']} [{record['type']}] {record['question']} -> {record['pred_cypher'][:80]}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())