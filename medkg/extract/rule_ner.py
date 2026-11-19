# -*- coding: utf-8 -*-
"""规则 NER：三种消融模式，用来回答"为什么要做最长匹配和同义词归一"。

- naive  ：词典全别名、逐词扫描、允许重叠（最容易写，也最容易错）
- longest：只认标准名、最长优先、禁止重叠（同义词全部漏召回）
- synonym：最长优先 + 同义归一（规则方案的完整版）

三种模式共用同一份词典，差别只在"怎么匹配"，因此对比结果可以直接
归因到匹配策略本身，而不是词典质量。
"""
from __future__ import annotations

from dataclasses import dataclass

from .dictionary import EntityDictionary

MODES = ("naive", "longest", "synonym")


@dataclass
class Mention:
    start: int
    end: int
    text: str
    canonical: str
    type: str
    method: str = "rule"

    def overlaps(self, other: "Mention") -> bool:
        return not (self.end <= other.start or other.end <= self.start)

    @property
    def key(self) -> tuple[str, str]:
        return (self.canonical, self.type)


def _find_all(haystack: str, needle: str) -> list[int]:
    out: list[int] = []
    if not needle:
        return out
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx < 0:
            return out
        out.append(idx)
        start = idx + 1


def extract_mentions(text: str, dictionary: EntityDictionary, mode: str = "synonym") -> list[Mention]:
    if mode not in MODES:
        raise ValueError(f"未知的 NER 模式：{mode}（可选 {MODES}）")

    if mode == "naive":
        # 短词优先：模拟"按词典顺序随手匹配"的朴素写法
        aliases = sorted(dictionary.alias_type.keys(), key=len)
        accepted: list[Mention] = []
        seen: set[tuple[int, int]] = set()
        for alias in aliases:
            for start in _find_all(text, alias):
                span = (start, start + len(alias))
                if span in seen:
                    continue
                seen.add(span)
                accepted.append(
                    Mention(
                        start=start,
                        end=start + len(alias),
                        text=alias,
                        canonical=dictionary.canonicalize(alias),
                        type=dictionary.type_of(alias) or "",
                        method="dict-naive",
                    )
                )
        return _sort(accepted)

    aliases = dictionary.aliases_sorted(include_synonyms=(mode == "synonym"))
    accepted = []
    for alias in aliases:
        for start in _find_all(text, alias):
            candidate = Mention(
                start=start,
                end=start + len(alias),
                text=alias,
                canonical=dictionary.canonicalize(alias),
                type=dictionary.type_of(alias) or "",
                method=f"dict-{mode}",
            )
            if any(candidate.overlaps(m) for m in accepted):
                continue
            accepted.append(candidate)
    return _sort(accepted)


def _sort(mentions: list[Mention]) -> list[Mention]:
    return sorted(mentions, key=lambda m: (m.start, -m.end))


def entity_set(mentions: list[Mention]) -> set[tuple[str, str]]:
    return {m.key for m in mentions}


def merge_mentions(*groups: list[Mention]) -> list[Mention]:
    """合并多路结果（规则 + 大模型），规则结果优先占位。"""
    merged: list[Mention] = []
    for group in groups:
        for mention in group:
            if mention.type not in {"Disease", "Symptom", "Drug", "Department", "Examination"}:
                continue
            if any(mention.overlaps(m) for m in merged):
                continue
            if mention.key in {m.key for m in merged}:
                continue
            merged.append(mention)
    return _sort(merged)