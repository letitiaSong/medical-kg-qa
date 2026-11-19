# -*- coding: utf-8 -*-
"""数据清洗：把原始问答整理成统一格式，并做基本质量检查。

对应作业第 2 步"准备并清洗医疗 CSV 数据"。
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from ..config import CLEAN_QA, RAW_QA, ensure_dirs

REQUIRED_COLUMNS = ["qa_id", "department", "title", "ask", "answer"]

# 全角数字/字母 -> 半角，便于后续实体匹配
_FULL2HALF = {ord("０") + i: ord("0") + i for i in range(10)}
_FULL2HALF.update({ord("Ａ") + i: ord("A") + i for i in range(26)})
_FULL2HALF.update({ord("ａ") + i: ord("a") + i for i in range(26)})

_CTRL_RE = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]")
_SPACE_RE = re.compile(r"[ \t\u3000]{2,}")


@dataclass
class QARecord:
    qa_id: str
    department: str
    title: str
    ask: str
    answer: str
    text: str = ""
    char_len: int = 0

    def as_row(self) -> dict:
        return {
            "qa_id": self.qa_id,
            "department": self.department,
            "title": self.title,
            "ask": self.ask,
            "answer": self.answer,
            "text": self.text,
            "char_len": self.char_len,
        }


@dataclass
class CleanReport:
    total: int = 0
    kept: int = 0
    dropped: int = 0
    duplicates: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    by_department: dict[str, int] = field(default_factory=dict)
    avg_len: float = 0.0

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "kept": self.kept,
            "dropped": self.dropped,
            "duplicates": self.duplicates,
            "warnings": self.warnings,
            "by_department": self.by_department,
            "avg_len": round(self.avg_len, 2),
        }


def normalize_text(text: str) -> str:
    if text is None:
        return ""
    text = str(text).translate(_FULL2HALF)
    text = _CTRL_RE.sub("", text)
    text = text.replace("\r", " ").replace("\n", " ")
    text = _SPACE_RE.sub(" ", text)
    return text.strip()


def load_records(path: Path | str = RAW_QA) -> list[QARecord]:
    path = Path(path)
    rows: list[QARecord] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name} 缺少字段：{missing}")
        for raw in reader:
            rows.append(
                QARecord(
                    qa_id=normalize_text(raw.get("qa_id")),
                    department=normalize_text(raw.get("department")),
                    title=normalize_text(raw.get("title")),
                    ask=normalize_text(raw.get("ask")),
                    answer=normalize_text(raw.get("answer")),
                )
            )
    return rows


def clean(records: Iterable[QARecord]) -> tuple[list[QARecord], CleanReport]:
    report = CleanReport()
    seen_ids: set[str] = set()
    seen_text: dict[str, str] = {}
    kept: list[QARecord] = []
    for rec in records:
        report.total += 1
        if not rec.qa_id or not rec.ask or not rec.answer:
            report.dropped += 1
            report.warnings.append(f"{rec.qa_id or '<无ID>'} 缺少必填字段，已丢弃")
            continue
        if rec.qa_id in seen_ids:
            report.dropped += 1
            report.duplicates.append(rec.qa_id)
            continue
        text = f"{rec.ask} {rec.answer}".strip()
        key = text.replace(" ", "")
        if key in seen_text:
            report.dropped += 1
            report.duplicates.append(f"{rec.qa_id}(与{seen_text[key]}重复)")
            continue
        seen_ids.add(rec.qa_id)
        seen_text[key] = rec.qa_id
        rec.text = text
        rec.char_len = len(text)
        kept.append(rec)

    report.kept = len(kept)
    for rec in kept:
        report.by_department[rec.department] = report.by_department.get(rec.department, 0) + 1
    report.avg_len = sum(r.char_len for r in kept) / len(kept) if kept else 0.0
    return kept, report


def write_clean(records: list[QARecord], path: Path | str = CLEAN_QA) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["qa_id", "department", "title", "ask", "answer", "text", "char_len"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            writer.writerow(rec.as_row())
    return path


def load_clean(path: Path | str = CLEAN_QA) -> list[QARecord]:
    """读取清洗后的数据，并补齐 text/char_len（后续抽取都基于 text）。"""
    records = load_records(path)
    for rec in records:
        rec.text = f"{rec.ask} {rec.answer}".strip()
        rec.char_len = len(rec.text)
    return records


def run(raw_path: Path | str = RAW_QA, out_path: Path | str = CLEAN_QA) -> tuple[list[QARecord], CleanReport]:
    ensure_dirs()
    records = load_records(raw_path)
    kept, report = clean(records)
    write_clean(kept, out_path)
    return kept, report