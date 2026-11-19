# -*- coding: utf-8 -*-
"""多轮问答流水线：意图识别 -> 槽位补全 -> Text2Cypher -> 执行 -> 组织回答。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from ..extract.dictionary import EntityDictionary, load_dictionary
from ..nlu.intent import Intent, detect, rewrite_followup, slot_of
from ..storage.base import GraphStore
from ..t2c.generator import Text2Cypher
from .formatter import DISCLAIMER, collect_sources, format_answer

HELP_TEXT = (
    "可以这样问：\n"
    "  · 高血压有哪些症状？\n"
    "  · 癫痫属于哪个科室？\n"
    "  · 心力衰竭吃什么药？\n"
    "  · 冠心病需要做哪些检查？\n"
    "  · 哪些疾病会出现头痛？\n"
    "  · 图谱里一共有多少种疾病？\n"
    "追问示例：问完“癫痫有哪些症状”后，直接问“那属于哪个科室”也会自动补全疾病。"
)


@dataclass
class QAResponse:
    question: str
    answer: str
    ok: bool = True
    cypher: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    intent: str = ""
    entity: str = ""
    rewritten: str = ""
    reason: str = ""
    source: str = ""
    row_count: int = 0
    valid: bool = True
    executed: bool = False
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "answer": self.answer,
            "ok": self.ok,
            "cypher": self.cypher,
            "columns": self.columns,
            "rows": self.rows,
            "sources": self.sources,
            "intent": self.intent,
            "entity": self.entity,
            "rewritten": self.rewritten,
            "reason": self.reason,
            "source": self.source,
            "row_count": self.row_count,
            "valid": self.valid,
            "executed": self.executed,
            "elapsed_ms": round(self.elapsed_ms, 1),
        }


class QAEngine:
    def __init__(
        self,
        store: GraphStore,
        dictionary: Optional[EntityDictionary] = None,
        t2c: Optional[Text2Cypher] = None,
        max_turns: int = 3,
        verbose: bool = True,
    ) -> None:
        self.store = store
        self.dictionary = dictionary or load_dictionary()
        self.t2c = t2c or Text2Cypher(store=store, dictionary=self.dictionary, verbose=False)
        self.max_turns = max_turns
        self.verbose = verbose
        self.context: dict = {}
        self._history: list[dict] = []

    # ---------------- 上下文 ----------------
    def reset(self) -> None:
        self.context.clear()
        self._history.clear()

    @property
    def history(self) -> list[dict]:
        return list(self._history[-self.max_turns :])

    def _update_context(self, slots: dict, intent: Intent) -> None:
        if slots.get("disease"):
            self.context["disease"] = slots["disease"]
        for key in ("symptom", "drug", "exam", "department"):
            if slots.get(key):
                self.context[key] = slots[key]
        if intent.canonical:
            self.context["last_entity"] = intent.canonical
            self.context["last_intent"] = intent.name

    # ---------------- 主流程 ----------------
    def ask(self, question: str) -> QAResponse:
        started = time.perf_counter()
        question = (question or "").strip()
        response = QAResponse(question=question, answer="")

        if not question:
            response.ok = False
            response.answer = "请输入一个问题，例如：高血压有哪些症状？"
            return response

        intent = detect(question, self.dictionary, context=self.context)
        rewritten, used_context = rewrite_followup(question, intent, self.context)
        if used_context:
            intent = detect(rewritten, self.dictionary)
            response.rewritten = rewritten
            if self.verbose:
                print(f"  （结合上文补全为：{rewritten}）")

        self._update_context(slot_of(rewritten, self.dictionary), intent)
        response.intent = intent.name
        response.entity = intent.canonical

        if intent.name == "unknown" and not intent.canonical:
            response.ok = False
            response.reason = "无法识别问句意图"
            response.answer = "抱歉，没听懂这个问题。\n" + HELP_TEXT
            response.elapsed_ms = (time.perf_counter() - started) * 1000
            return response

        result, query_result = self.t2c.run(rewritten, history=self.history)
        response.source = result.source
        response.cypher = result.cypher
        response.valid = result.valid
        response.executed = query_result is not None
        if result.row_count is not None:
            response.row_count = result.row_count

        if result.unanswerable:
            response.ok = False
            response.reason = result.reason
            response.answer = f"当前图谱无法回答：{result.reason}"
        elif not result.ok:
            response.ok = False
            response.reason = result.reason
            response.answer = (
                "生成的 Cypher 未通过校验或执行失败，无法回答这个问题。\n"
                f"原因：{result.reason}"
            )
        elif query_result is None or query_result.count == 0:
            response.ok = False
            response.reason = "图谱中没有相关记录"
            response.answer = (
                "当前图谱中没有查到相关记录。\n"
                "可能原因：该实体尚未入库，或课堂问答里没有提到这层关系。"
            )
        else:
            response.columns = list(query_result.columns)
            response.rows = query_result.to_dicts()
            response.sources = collect_sources(query_result)
            response.answer = format_answer(
                query_result,
                intent_name=intent.name,
                entity=intent.canonical,
            )

        response.elapsed_ms = (time.perf_counter() - started) * 1000
        if response.cypher:
            self._history.append(
                {"question": rewritten, "cypher": response.cypher, "answer": response.answer}
            )
        return response

    def ask_many(self, questions: list[str]) -> list[QAResponse]:
        return [self.ask(q) for q in questions]

    def describe(self) -> dict:
        return {
            "store": getattr(self.store, "name", "unknown"),
            "nodes": self.store.count_nodes(),
            "edges": self.store.count_edges(),
            "llm": self.t2c.describe(),
            "context": dict(self.context),
            "disclaimer": DISCLAIMER,
        }