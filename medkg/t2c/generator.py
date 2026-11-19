# -*- coding: utf-8 -*-
"""Text2Cypher 生成器：Prompt -> LLM -> 解析 -> 安全校验 ->（可选）重试 -> 执行。"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from ..extract.dictionary import EntityDictionary, load_dictionary
from ..extract.rule_ner import extract_mentions
from ..storage.base import GraphError, QueryResult
from .llm import BaseLLM, LLMError, build_llm
from .prompt import build_messages
from .validator import has_error, normalize, validate


@dataclass
class T2CResult:
    question: str
    cypher: str = ""
    raw: str = ""
    source: str = ""
    model: str = ""
    explanation: str = ""
    unanswerable: bool = False
    reason: str = ""
    valid: bool = True
    issues: list[dict] = field(default_factory=list)
    elapsed_ms: float = 0.0
    attempts: int = 0
    row_count: Optional[int] = None

    @property
    def ok(self) -> bool:
        return (not self.unanswerable) and self.valid

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "cypher": self.cypher,
            "source": self.source,
            "model": self.model,
            "explanation": self.explanation,
            "unanswerable": self.unanswerable,
            "reason": self.reason,
            "valid": self.valid,
            "issues": self.issues,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "attempts": self.attempts,
            "row_count": self.row_count,
        }


def parse_output(text: str) -> dict:
    """解析模型输出：优先 JSON，其次代码块，最后兜底把整段当 Cypher。"""
    raw = (text or "").strip()
    if not raw:
        return {"unanswerable": True, "reason": "模型返回空内容"}
    cleaned = re.sub(r"^```(?:json|cypher)?\s*", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except ValueError:
            pass
    if "MATCH" in cleaned.upper():
        return {"cypher": cleaned, "explanation": "", "unanswerable": False}
    return {"unanswerable": True, "reason": "模型输出既不是 JSON 也不包含 Cypher"}


class Text2Cypher:
    """把生成器做成一个类，方便 CLI、API 和评测脚本共用。"""

    def __init__(
        self,
        store=None,
        dictionary: Optional[EntityDictionary] = None,
        llm: Optional[BaseLLM] = None,
        mode: Optional[str] = None,
        max_retries: int = 1,
        entity_hints: bool = True,
        verbose: bool = False,
    ) -> None:
        self.dictionary = dictionary or load_dictionary()
        self.store = store
        self.mode = mode
        self.max_retries = max_retries
        self.entity_hints = entity_hints
        self.verbose = verbose
        if llm is None:
            llm, self.llm_note = build_llm(mode, dictionary=self.dictionary, verbose=verbose)
        else:
            self.llm_note = f"使用注入的模型：{llm.name}"
        self.llm = llm

    # ---------------- 生成 ----------------
    def _hints(self, question: str) -> list[str]:
        if not self.entity_hints:
            return []
        mentions = extract_mentions(question, self.dictionary, mode="synonym")
        seen: set[str] = set()
        hints: list[str] = []
        for m in mentions:
            if m.canonical in seen:
                continue
            seen.add(m.canonical)
            hints.append(f"{m.text} -> {m.canonical}（{m.type}）")
        return hints

    def generate(self, question: str, history: Optional[list[dict]] = None) -> T2CResult:
        result = T2CResult(question=question, source=self.llm.name, model=self.llm.model)
        messages = build_messages(question, history=history, entity_hints=self._hints(question))
        started = time.perf_counter()

        for attempt in range(self.max_retries + 1):
            result.attempts = attempt + 1
            try:
                reply = self.llm.chat(messages)
            except LLMError as exc:
                result.valid = False
                result.reason = str(exc)
                result.elapsed_ms = (time.perf_counter() - started) * 1000
                return result

            result.raw = reply.text
            payload = parse_output(reply.text)
            result.explanation = str(payload.get("explanation", ""))
            if payload.get("unanswerable"):
                result.unanswerable = True
                result.reason = str(payload.get("reason", "模型判断该问题无法用图谱回答"))
                result.elapsed_ms = (time.perf_counter() - started) * 1000
                return result

            cypher = normalize(str(payload.get("cypher", "")))
            if not cypher:
                result.valid = False
                result.reason = "模型没有给出 cypher 字段"
                result.elapsed_ms = (time.perf_counter() - started) * 1000
                return result

            issues = validate(cypher)
            result.cypher = cypher
            result.issues = issues
            if not has_error(issues):
                result.valid = True
                result.elapsed_ms = (time.perf_counter() - started) * 1000
                if self.verbose:
                    print(f"  [Text2Cypher] {cypher}")
                return result

            # 校验失败：把问题反馈给模型重写一次
            errors = "；".join(item["message"] for item in issues if item["level"] == "error")
            result.valid = False
            result.reason = errors
            if attempt < self.max_retries:
                messages = messages + [
                    {"role": "assistant", "content": reply.text},
                    {
                        "role": "user",
                        "content": f"上面的 Cypher 不合格：{errors}。请只输出修正后的 JSON。",
                    },
                ]

        result.elapsed_ms = (time.perf_counter() - started) * 1000
        return result

    # ---------------- 生成并执行 ----------------
    def run(self, question: str, history: Optional[list[dict]] = None):
        result = self.generate(question, history=history)
        if not result.ok or self.store is None:
            return result, None
        try:
            query_result: QueryResult = self.store.execute(result.cypher)
        except GraphError as exc:
            result.valid = False
            result.reason = f"Cypher 执行失败：{exc}"
            return result, None
        result.row_count = query_result.count
        return result, query_result

    def describe(self) -> dict:
        return {
            "llm": self.llm.describe(),
            "note": self.llm_note,
            "max_retries": self.max_retries,
            "entity_hints": self.entity_hints,
        }