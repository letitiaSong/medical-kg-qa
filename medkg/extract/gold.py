# -*- coding: utf-8 -*-
"""金标准标注的加载与关系金标准的推导。"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ..config import NER_GOLD, RE_GOLD
from ..etl.preprocess import QARecord
from .dictionary import EntityDictionary

# 词典刻意未收录的实体（用来模拟"词典覆盖不足"），金标准里仍然要标注
GOLD_ALIASES: dict[str, tuple[str, str]] = {
    "耳石症": ("良性阵发性位置性眩晕", "Disease"),
    "24小时动态心电图": ("动态心电图", "Examination"),
}


@dataclass
class GoldMention:
    qa_id: str
    surface: str
    type: str
    start: int = -1
    canonical: str = ""


def _canonical(surface: str, type_name: str, dictionary: EntityDictionary) -> str:
    mapped = dictionary.canonicalize(surface)
    if mapped != surface:
        return mapped
    if surface in GOLD_ALIASES:
        return GOLD_ALIASES[surface][0]
    return surface


def load_ner_gold(
    path: Path | str = NER_GOLD, dictionary: EntityDictionary | None = None
) -> dict[str, set[tuple[str, str]]]:
    path = Path(path)
    gold: dict[str, set[tuple[str, str]]] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for raw in csv.DictReader(fh):
            qa_id = (raw.get("qa_id") or "").strip()
            surface = (raw.get("surface") or "").strip()
            type_name = (raw.get("type") or "").strip()
            if not qa_id or not surface:
                continue
            canonical = _canonical(surface, type_name, dictionary) if dictionary else surface
            gold.setdefault(qa_id, set()).add((canonical, type_name))
    return gold


def load_gold_mentions(
    path: Path | str = NER_GOLD, dictionary: EntityDictionary | None = None
) -> dict[str, list[GoldMention]]:
    path = Path(path)
    out: dict[str, list[GoldMention]] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for raw in csv.DictReader(fh):
            qa_id = (raw.get("qa_id") or "").strip()
            surface = (raw.get("surface") or "").strip()
            type_name = (raw.get("type") or "").strip()
            if not qa_id or not surface:
                continue
            canonical = _canonical(surface, type_name, dictionary) if dictionary else surface
            out.setdefault(qa_id, []).append(GoldMention(qa_id, surface, type_name, -1, canonical))
    return out


REL_BY_TAIL = {
    "Symptom": "HAS_SYMPTOM",
    "Drug": "USES_DRUG",
    "Examination": "REQUIRES_EXAM",
}


def derive_re_gold(
    records: list[QARecord],
    gold_mentions: dict[str, list[GoldMention]],
    out_path: Path | str = RE_GOLD,
) -> list[dict]:
    """按"主病种 × 同条问答出现的实体"推导关系金标准。

    标注约定（写进实验报告）：
    1. 关系只挂在"主病种"上（问答中最早出现的疾病实体）；
    2. 同一条问答中出现的症状/药品/检查/科室都视为该主病种的关系实例；
    3. 多病种同现的条目，非主病种的关系不进入金标准（留待人工审核）。
    """
    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for rec in records:
        mentions = gold_mentions.get(rec.qa_id, [])
        if not mentions:
            continue
        for m in mentions:
            idx = rec.text.find(m.surface)
            m.start = idx if idx >= 0 else 10**6
        diseases = [m for m in mentions if m.type == "Disease"]
        if not diseases:
            continue
        q_end = rec.text.find(" ")
        if q_end < 0:
            q_end = len(rec.text)
        in_question = [m for m in diseases if m.start < q_end]
        head = min(in_question or diseases, key=lambda m: m.start)

        for m in mentions:
            relation = REL_BY_TAIL.get(m.type)
            if not relation:
                continue
            key = (head.canonical, relation, m.canonical)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "qa_id": rec.qa_id,
                    "head": head.canonical,
                    "head_type": "Disease",
                    "relation": relation,
                    "tail": m.canonical,
                    "tail_type": m.type,
                    "evidence": rec.title,
                }
            )
        key = (head.canonical, "BELONGS_TO", rec.department)
        if rec.department and key not in seen:
            seen.add(key)
            rows.append(
                {
                    "qa_id": rec.qa_id,
                    "head": head.canonical,
                    "head_type": "Disease",
                    "relation": "BELONGS_TO",
                    "tail": rec.department,
                    "tail_type": "Department",
                    "evidence": rec.title,
                }
            )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "qa_id",
                "head",
                "head_type",
                "relation",
                "tail",
                "tail_type",
                "evidence",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    return rows


def load_re_gold(path: Path | str = RE_GOLD) -> set[tuple[str, str, str]]:
    path = Path(path)
    if not path.exists():
        return set()
    out: set[tuple[str, str, str]] = set()
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for raw in csv.DictReader(fh):
            head = (raw.get("head") or "").strip()
            relation = (raw.get("relation") or "").strip()
            tail = (raw.get("tail") or "").strip()
            if head and relation and tail:
                out.add((head, relation, tail))
    return out