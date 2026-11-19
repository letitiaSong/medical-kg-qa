# -*- coding: utf-8 -*-
"""通用评测指标：P/R/F1、micro/macro、执行准确率。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence


def prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def evaluate_sets(
    gold: dict[str, set],
    pred: dict[str, set],
    key_labels: Sequence[str] = (),
) -> dict:
    """按"每条样本一个集合"计算 micro / macro / 分类别指标。

    gold/pred 形如 {qa_id: {(名称, 类型), ...}}。
    """
    keys = sorted(set(gold) | set(pred))
    tp_all = fp_all = fn_all = 0
    per_label: dict[str, dict[str, int]] = {label: {"tp": 0, "fp": 0, "fn": 0} for label in key_labels}
    f1_scores: list[float] = []
    errors: list[dict] = []

    for key in keys:
        g = set(gold.get(key, set()))
        p = set(pred.get(key, set()))
        tp = g & p
        fp = p - g
        fn = g - p
        tp_all += len(tp)
        fp_all += len(fp)
        fn_all += len(fn)
        for item in tp:
            label = _label_of(item, key_labels)
            if label in per_label:
                per_label[label]["tp"] += 1
        for item in fp:
            label = _label_of(item, key_labels)
            if label in per_label:
                per_label[label]["fp"] += 1
        for item in fn:
            label = _label_of(item, key_labels)
            if label in per_label:
                per_label[label]["fn"] += 1
        sample = prf(len(tp), len(fp), len(fn))
        f1_scores.append(sample["f1"])
        if fp or fn:
            errors.append(
                {
                    "key": key,
                    "tp": sorted(x[0] for x in tp),
                    "fp": sorted(f"{x[0]}({x[1]})" for x in fp),
                    "fn": sorted(f"{x[0]}({x[1]})" for x in fn),
                }
            )

    detail = {
        label: prf(v["tp"], v["fp"], v["fn"]) for label, v in per_label.items() if label
    }
    return {
        "micro": prf(tp_all, fp_all, fn_all),
        "macro_f1": round(sum(f1_scores) / len(f1_scores), 4) if f1_scores else 0.0,
        "per_label": detail,
        "errors": errors,
        "num_samples": len(keys),
    }


def _label_of(item: tuple, key_labels: Sequence[str]) -> str:
    if isinstance(item, tuple) and len(item) > 1:
        return item[1]
    return ""


def exact_match(gold: str, pred: str, normalizer=None) -> bool:
    g = _norm(gold, normalizer)
    p = _norm(pred, normalizer)
    return g == p


def _norm(value: str, normalizer) -> str:
    text = (value or "").strip()
    text = " ".join(text.split())
    if normalizer:
        text = normalizer(text)
    return text.rstrip(";").strip()


@dataclass
class Tally:
    """累加器，供多批次评测使用。"""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    extra: dict[str, int] = field(default_factory=dict)

    def add(self, tp: int, fp: int, fn: int) -> None:
        self.tp += tp
        self.fp += fp
        self.fn += fn

    def bump(self, name: str, value: int = 1) -> None:
        self.extra[name] = self.extra.get(name, 0) + value

    def as_dict(self) -> dict:
        out = prf(self.tp, self.fp, self.fn)
        out.update(self.extra)
        return out


def format_table(rows: Iterable[dict], columns: Sequence[str]) -> str:
    rows = list(rows)
    widths = {c: len(c) for c in columns}
    for row in rows:
        for c in columns:
            widths[c] = max(widths[c], len(str(row.get(c, ""))))
    header = "  ".join(str(c).ljust(widths[c]) for c in columns)
    sep = "  ".join("-" * widths[c] for c in columns)
    body = [
        "  ".join(str(row.get(c, "")).ljust(widths[c]) for c in columns) for row in rows
    ]
    return "\n".join([header, sep, *body])