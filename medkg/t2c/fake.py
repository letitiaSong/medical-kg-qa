# -*- coding: utf-8 -*-
"""离线"假模型"：用规则把问题映射成 Cypher，接口与真实模型完全一致。

它存在的意义有两个：
1. 没有任何 API Key 的电脑上也能把整套系统跑通（作业演示、录屏、自动评测）；
2. 作为 Text2Cypher 的对比基线（规则模板 vs 大模型）。
"""
from __future__ import annotations

import json
import time
from typing import Optional

from ..config import LLM
from ..extract.dictionary import EntityDictionary, load_dictionary
from ..nlu.intent import detect
from .llm import BaseLLM, LLMReply

# 每类意图的 Cypher 模板：{name} 是实体规范名，{label} 是实体标签
TEMPLATES: dict[str, str] = {
    "symptom": (
        "MATCH (d:Disease {{name: '{name}'}})-[r:HAS_SYMPTOM]->(s:Symptom) "
        "RETURN s.name AS 症状, r.qa_id AS 来源, r.evidence AS 证据 LIMIT 20"
    ),
    "drug": (
        "MATCH (d:Disease {{name: '{name}'}})-[r:USES_DRUG]->(dr:Drug) "
        "RETURN dr.name AS 药品, r.qa_id AS 来源, r.evidence AS 证据 LIMIT 20"
    ),
    "exam": (
        "MATCH (d:Disease {{name: '{name}'}})-[r:REQUIRES_EXAM]->(e:Examination) "
        "RETURN e.name AS 检查, r.scope AS 性质, r.qa_id AS 来源, r.evidence AS 证据 LIMIT 20"
    ),
    "department": (
        "MATCH (d:Disease {{name: '{name}'}})-[r:BELONGS_TO]->(dept:Department) "
        "RETURN dept.name AS 科室, r.qa_id AS 来源 LIMIT 5"
    ),
    "description": (
        "MATCH (d:Disease {{name: '{name}'}}) "
        "RETURN d.name AS 疾病, d.description AS 简介 LIMIT 5"
    ),
    "diseases_by_symptom": (
        "MATCH (d:Disease)-[r:HAS_SYMPTOM]->(s:Symptom {{name: '{name}'}}) "
        "RETURN d.name AS 疾病, r.qa_id AS 来源, r.evidence AS 证据 LIMIT 20"
    ),
    "diseases_by_drug": (
        "MATCH (d:Disease)-[r:USES_DRUG]->(dr:Drug {{name: '{name}'}}) "
        "RETURN d.name AS 疾病, r.qa_id AS 来源 LIMIT 20"
    ),
    "diseases_by_exam": (
        "MATCH (d:Disease)-[r:REQUIRES_EXAM]->(e:Examination {{name: '{name}'}}) "
        "RETURN d.name AS 疾病, r.scope AS 性质, r.qa_id AS 来源 LIMIT 20"
    ),
    "count_disease": "MATCH (d:Disease) RETURN count(d) AS 疾病数",
    "shared_drug": (
        "MATCH (a:Disease {{name: '{name}'}})-[:USES_DRUG]->(dr:Drug)"
        "<-[:USES_DRUG]-(b:Disease {{name: '{name2}'}}) "
        "RETURN dr.name AS 共同药品 LIMIT 10"
    ),
}

UNABLE_REASON = {
    "unknown": "这句话没有表达出可查询的医学问题（如症状、用药、检查、科室）。",
    "no_entity": "问句里没有出现图谱中已有的疾病/症状/药品/检查实体。",
}

# 关键词基线只覆盖这四类"疾病 -> 属性"的正向问法
NAIVE_INTENTS = {"symptom", "drug", "exam", "department"}


def _escape(name: str) -> str:
    return name.replace("\\", "\\\\").replace("'", "\\'")


def plan(
    question: str,
    dictionary: EntityDictionary,
    context: Optional[dict] = None,
    canonical: bool = True,
    naive: bool = False,
) -> dict:
    """规则版 Text2Cypher：返回与真实模型一致的 JSON 结构。

    canonical=False 时直接用问句里的原始说法（不做别名归一），用于消融实验；
    naive=True 时只支持四类正向关系、不支持反向/计数/多跳，作为规则基线。
    """
    intent = detect(question, dictionary, context=context)
    if intent.name == "unknown":
        return {"unanswerable": True, "reason": UNABLE_REASON["unknown"], "intent": intent.name}
    if naive and intent.name not in NAIVE_INTENTS:
        return {
            "unanswerable": True,
            "reason": "关键词基线不支持该问题类型（仅支持疾病->症状/用药/检查/科室）",
            "intent": intent.name,
        }
    if intent.name == "count_disease":
        return {
            "cypher": TEMPLATES["count_disease"],
            "explanation": "统计图谱中的疾病节点数量",
            "unanswerable": False,
            "intent": intent.name,
            "entity": "",
        }
    name = intent.canonical if canonical else (intent.entity_text or intent.canonical)
    if intent.name == "shared_drug":
        diseases: list[str] = []
        for mention in intent.mentions:
            if mention.type != "Disease":
                continue
            value = mention.canonical if canonical else mention.text
            if value and value not in diseases:
                diseases.append(value)
        if len(diseases) < 2:
            return {
                "unanswerable": True,
                "reason": "共同用药问题需要问句里出现两个疾病名称。",
                "intent": intent.name,
            }
        cypher = TEMPLATES["shared_drug"].format(name=_escape(diseases[0]), name2=_escape(diseases[1]))
        return {
            "cypher": cypher,
            "explanation": f"查询 {diseases[0]} 与 {diseases[1]} 的共同用药",
            "unanswerable": False,
            "intent": intent.name,
            "entity": diseases[0],
        }
    if not name:
        return {"unanswerable": True, "reason": UNABLE_REASON["no_entity"], "intent": intent.name}

    template = TEMPLATES.get(intent.name)
    if template is None:
        return {"unanswerable": True, "reason": f"暂不支持该意图：{intent.name}", "intent": intent.name}

    cypher = template.format(name=_escape(name))
    explanation = f"{intent.cn}：{name}（{intent.entity_type or '无实体'}）"
    return {
        "cypher": cypher,
        "explanation": explanation,
        "unanswerable": False,
        "intent": intent.name,
        "entity": name,
    }


def _last_question(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        for line in content.splitlines():
            if line.startswith("问题："):
                return line[len("问题：") :].strip()
        return content.strip()
    return ""


class FakeLLM(BaseLLM):
    name = "fake-rule"
    model = "rule-template-v1"

    def __init__(
        self,
        dictionary: Optional[EntityDictionary] = None,
        canonical: bool = True,
        naive: bool = False,
    ) -> None:
        self.dictionary = dictionary or load_dictionary()
        self.canonical = canonical
        self.naive = naive
        if naive:
            self.name = "keyword-baseline"
        elif not canonical:
            self.name = "no-alias-rule"
        else:
            self.name = "fake-rule"

    def available(self) -> bool:
        return True

    def chat(self, messages: list[dict], temperature: Optional[float] = None) -> LLMReply:
        started = time.perf_counter()
        question = _last_question(messages)
        payload = plan(
            question,
            self.dictionary,
            canonical=self.canonical,
            naive=self.naive,
        )
        text = json.dumps(payload, ensure_ascii=False)
        return LLMReply(
            text=text,
            model=self.model,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            source=self.name,
        )

    def describe(self) -> dict:
        return {"name": self.name, "model": self.model, "available": True}


def fake_llm_or_none(dictionary=None):
    if LLM.mode in {"real", "openai"}:
        return None
    return FakeLLM(dictionary)