# -*- coding: utf-8 -*-
"""意图识别与实体槽位（供 Text2Cypher 的离线模式与多轮问答共用）。

把"高血压要吃什么药"识别成 intent=drug + 实体 高血压，
后面的追问"那要做什么检查"就能靠上下文里的 disease 槽位补全。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..extract.dictionary import EntityDictionary
from ..extract.rule_ner import Mention, extract_mentions

INTENT_CN = {
    "symptom": "查询症状",
    "drug": "查询用药",
    "exam": "查询检查",
    "department": "查询科室",
    "description": "查询简介",
    "shared_drug": "查询共同用药",
    "diseases_by_symptom": "按症状查疾病",
    "diseases_by_drug": "按药品查疾病",
    "diseases_by_exam": "按检查查疾病",
    "count_disease": "统计疾病数量",
    "unknown": "未识别",
}

# 该意图需要哪个类型的实体做槽位
NEED_TYPE: dict[str, Optional[str]] = {
    "symptom": "Disease",
    "drug": "Disease",
    "exam": "Disease",
    "department": "Disease",
    "description": "Disease",
    "shared_drug": "Disease",
    "diseases_by_symptom": "Symptom",
    "diseases_by_drug": "Drug",
    "diseases_by_exam": "Examination",
    "count_disease": None,
    "unknown": None,
}

FORWARD_INTENTS = {"symptom", "drug", "exam", "department", "description", "shared_drug"}

_PATTERNS: list[tuple[str, str]] = [
    ("count_disease", r"(多少|几)\s*(种|个|类)?\s*(疾病|病)"),
    ("shared_drug", r"(相同|同样|共同|一样|共用).{0,8}(药|用药)|(药|用药).{0,8}(相同|同样|共同|一样|共用)"),
]


@dataclass
class Intent:
    name: str = "unknown"
    entity_text: str = ""
    canonical: str = ""
    entity_type: str = ""
    needs_context: bool = False
    mentions: list[Mention] = field(default_factory=list)
    raw_question: str = ""

    @property
    def ok(self) -> bool:
        return self.name != "unknown" and bool(self.canonical)

    @property
    def cn(self) -> str:
        return INTENT_CN.get(self.name, self.name)


def _pick(mentions: list[Mention], want: Optional[str]) -> Optional[Mention]:
    if want is None:
        return None
    typed = [m for m in mentions if m.type == want]
    if not typed:
        return None
    # 文本最长者优先（"2型糖尿病" 优于 "糖尿病"）
    return max(typed, key=lambda m: len(m.text))


def detect(
    question: str,
    dictionary: EntityDictionary,
    context: Optional[dict] = None,
) -> Intent:
    q = (question or "").strip()
    intent = Intent(raw_question=q)
    if not q:
        return intent

    mentions = extract_mentions(q, dictionary, mode="synonym")
    intent.mentions = mentions

    name = _classify(q, mentions)
    intent.name = name
    want = NEED_TYPE.get(name)
    best = _pick(mentions, want)

    if best is None and name in FORWARD_INTENTS and mentions:
        # 问句里没出现疾病名，但出现了症状/药品（如"头痛吃什么药"）：用第一个实体兜底
        best = max(mentions, key=lambda m: len(m.text))
        want = best.type

    if best is not None:
        intent.entity_text = best.text
        intent.canonical = best.canonical
        intent.entity_type = best.type
        return intent

    if name in FORWARD_INTENTS and context and context.get("disease"):
        intent.needs_context = True
        intent.entity_type = "Disease"
    return intent


def _classify(q: str, mentions: list[Mention] | None = None) -> str:
    mentions = mentions or []
    for name, pattern in _PATTERNS:
        if re.search(pattern, q):
            return name
    reverse = bool(re.search(r"(哪些|什么|哪种|哪几种|什么病)\s*(疾病|病|人)", q))
    if re.search(r"科室|哪个科|挂哪(个)?科|看哪个科|属于.*科", q):
        return "department"
    if re.search(r"检查|检验|查什么|做什么查|怎么查", q):
        return "diseases_by_exam" if reverse else "exam"
    if re.search(r"药|用药|治疗", q):
        return "diseases_by_drug" if reverse else "drug"
    if re.search(r"症状|表现|不舒服|感觉", q):
        return "diseases_by_symptom" if reverse else "symptom"
    if reverse:
        types = {m.type for m in mentions}
        if "Symptom" in types:
            return "diseases_by_symptom"
        if "Drug" in types:
            return "diseases_by_drug"
        if "Examination" in types:
            return "diseases_by_exam"
    if re.search(r"是什么病|什么病|介绍|怎么回事|严重|概述|简介", q):
        return "description"
    return "unknown"


def rewrite_followup(question: str, intent: Intent, context: dict) -> tuple[str, bool]:
    """把省略了主语的追问补全成完整问句，返回 (新问句, 是否用了上下文)。"""
    if not intent.needs_context:
        return question, False
    disease = (context or {}).get("disease")
    if not disease:
        return question, False
    body = re.sub(r"^(那|那么|它|这个病|这种病|该病|这种|这个|还有|另外)[，,、]?\s*", "", question)
    return f"{disease} {body}".strip(), True


def slot_of(question: str, dictionary: EntityDictionary) -> dict:
    """抽取问句里的所有槽位（疾病/症状/药品/检查/科室），用于多轮上下文更新。"""
    mentions = extract_mentions(question, dictionary, mode="synonym")
    slots: dict[str, str] = {}
    for m in mentions:
        key = {
            "Disease": "disease",
            "Symptom": "symptom",
            "Drug": "drug",
            "Examination": "exam",
            "Department": "department",
        }.get(m.type)
        if key and key not in slots:
            slots[key] = m.canonical
    return slots