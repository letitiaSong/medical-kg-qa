# -*- coding: utf-8 -*-
"""步骤 1：数据清洗 + 词典统计 + 三种规则 NER 对比。

用法：
    python scripts/01_preprocess.py
输出：
    data/clean/qa_clean.csv
    outputs/ner_eval_*.csv
    outputs/preprocess_report.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from medkg.config import OUTPUT_DIR, ensure_dirs
from medkg.etl import preprocess
from medkg.eval import evaluate_sets, format_table
from medkg.extract import (
    MODES,
    derive_re_gold,
    entity_set,
    extract_mentions,
    load_dictionary,
    load_gold_mentions,
    load_ner_gold,
)


def main() -> int:
    ensure_dirs()
    records, report = preprocess.run()
    print("=" * 62)
    print("步骤 1 / 数据清洗")
    print("=" * 62)
    print(f"原始条数：{report.total}，保留：{report.kept}，丢弃：{report.dropped}")
    print(f"平均文本长度：{report.avg_len} 字")
    print("科室分布：" + "，".join(f"{k} {v} 条" for k, v in sorted(report.by_department.items())))
    if report.warnings:
        print("警告：" + "；".join(report.warnings[:5]))

    dictionary = load_dictionary()
    print(f"\n实体词典：{dictionary.size} 个实体，{dictionary.alias_size} 个表面形式")
    print("类型分布：" + "，".join(f"{k} {v}" for k, v in sorted(dictionary.type_stats().items())))

    gold_mentions = load_gold_mentions(dictionary=dictionary)
    gold_sets = load_ner_gold(dictionary=dictionary)
    total_gold = sum(len(v) for v in gold_sets.values())
    print(f"\n金标准：{len(gold_sets)} 条问答，{total_gold} 个实体标注（按实体去重）")

    re_gold = derive_re_gold(records, gold_mentions)
    print(f"关系金标准：{len(re_gold)} 条三元组")

    print("\n" + "-" * 62)
    print("三种规则 NER 策略对比（实体级，按 (规范名, 类型) 计分）")
    print("-" * 62)
    rows = []
    all_results = {}
    for mode in MODES:
        pred_sets = {}
        for rec in records:
            mentions = extract_mentions(rec.text, dictionary, mode=mode)
            pred_sets[rec.qa_id] = entity_set(mentions)
        result = evaluate_sets(gold_sets, pred_sets, key_labels=("Disease", "Symptom", "Drug", "Department", "Examination"))
        all_results[mode] = result
        micro = result["micro"]
        rows.append(
            {
                "策略": mode,
                "精确率": f"{micro['precision']:.4f}",
                "召回率": f"{micro['recall']:.4f}",
                "F1": f"{micro['f1']:.4f}",
                "FP": micro["fp"],
                "FN": micro["fn"],
                "样本F1均值": f"{result['macro_f1']:.4f}",
            }
        )
    print(format_table(rows, ["策略", "精确率", "召回率", "F1", "FP", "FN", "样本F1均值"]))

    print("\n各类型指标（synonym 模式）：")
    per_label = all_results["synonym"]["per_label"]
    detail_rows = [
        {
            "类型": label,
            "P": f"{v['precision']:.4f}",
            "R": f"{v['recall']:.4f}",
            "F1": f"{v['f1']:.4f}",
            "TP": v["tp"],
            "FP": v["fp"],
            "FN": v["fn"],
        }
        for label, v in per_label.items()
    ]
    print(format_table(detail_rows, ["类型", "P", "R", "F1", "TP", "FP", "FN"]))

    print("\nsynonym 模式的错误样例（前 6 条）：")
    for err in all_results["synonym"]["errors"][:6]:
        print(f"  {err['key']}  漏标={err['fn']}  多标={err['fp']}")

    (OUTPUT_DIR / "preprocess_report.json").write_text(
        json.dumps(
            {
                "clean": report.to_dict(),
                "dictionary": {
                    "entities": dictionary.size,
                    "aliases": dictionary.alias_size,
                    "by_type": dictionary.type_stats(),
                },
                "gold": {"qa": len(gold_sets), "mentions": total_gold, "relations": len(re_gold)},
                "ner": {
                    mode: {
                        "micro": res["micro"],
                        "macro_f1": res["macro_f1"],
                        "per_label": res["per_label"],
                    }
                    for mode, res in all_results.items()
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n已写出 {OUTPUT_DIR / 'preprocess_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())