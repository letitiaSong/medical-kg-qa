# -*- coding: utf-8 -*-
"""关系抽取：在"单主病种"假设下，把同一条问答里出现的症状/药品/检查/科室
挂到主疾病上，形成 (head, relation, tail) 三元组。

主疾病判定：问答文本中最早出现的 Disease 实体。多病种同现的条目只取主病种，
其余病种进入"待人工审核"清单——这正是知识融合阶段要处理的冲突。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .rule_ner import Mention

REL_BY_TAIL = {
    "Symptom": "HAS_SYMPTOM",
    "Drug": "USES_DRUG",
    "Examination": "REQUIRES_EXAM",
    "Department": "BELONGS_TO",
}


@dataclass
class Triple:
    head: str
    relation: str
    tail: str
    head_type: str
    tail_type: str
    qa_id: str
    evidence: str = ""
    scope: str = ""
    weight: float = 1.0

    def key(self) -> tuple[str, str, str]:
        return (self.head, self.relation, self.tail)


@dataclass
class RelationResult:
    triples: list[Triple] = field(default_factory=list)
    review: list[dict] = field(default_factory=list)

    def dedupe(self) -> "RelationResult":
        seen: dict[tuple[str, str, str], Triple] = {}
        for t in self.triples:
            if t.key() not in seen:
                seen[t.key()] = t
        self.triples = list(seen.values())
        return self


def primary_disease(mentions: list[Mention], text: str) -> Mention | None:
    diseases = [m for m in mentions if m.type == "Disease"]
    if not diseases:
        return None
    question_end = text.find(" ")
    if question_end < 0:
        question_end = len(text)
    in_question = [m for m in diseases if m.start < question_end]
    pool = in_question or diseases
    return min(pool, key=lambda m: m.start)


def extract_relations(
    mentions: list[Mention],
    text: str,
    qa_id: str,
    department: str = "",
    evidence: str = "",
    scope: str = "",
) -> RelationResult:
    result = RelationResult()
    head = primary_disease(mentions, text)
    if head is None:
        result.review.append(
            {"qa_id": qa_id, "reason": "问答中未识别出疾病实体，关系无法挂载", "text": text[:60]}
        )
        return result

    others = [m for m in mentions if m.type == "Disease" and m.canonical != head.canonical]
    for m in others:
        result.review.append(
            {
                "qa_id": qa_id,
                "reason": f"多病种同现：{m.canonical}（主病种为 {head.canonical}），关系归属需人工确认",
                "text": m.text,
            }
        )

    q_end = text.find(" ")
    if q_end < 0:
        q_end = len(text)

    seen_tail: set[tuple[str, str]] = set()
    for m in mentions:
        relation = REL_BY_TAIL.get(m.type)
        if not relation:
            continue
        if m.canonical == head.canonical and m.type == "Disease":
            continue
        key = (relation, m.canonical)
        if key in seen_tail:
            continue
        seen_tail.add(key)
        result.triples.append(
            Triple(
                head=head.canonical,
                relation=relation,
                tail=m.canonical,
                head_type="Disease",
                tail_type=m.type,
                qa_id=qa_id,
                evidence=evidence,
                scope=scope if relation == "REQUIRES_EXAM" else "",
                weight=1.0 if m.start < q_end else 0.9,
            )
        )

    if department and ("BELONGS_TO", department) not in seen_tail:
        result.triples.append(
            Triple(
                head=head.canonical,
                relation="BELONGS_TO",
                tail=department,
                head_type="Disease",
                tail_type="Department",
                qa_id=qa_id,
                evidence=evidence,
                weight=1.0,
            )
        )
    return result.dedupe()