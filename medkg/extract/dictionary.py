# -*- coding: utf-8 -*-
"""医疗实体词典：别名归一 + 类型约束。

词典是规则 NER 的知识来源，也是"实体归一"（fusion）的依据。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from ..config import ENTITY_DICT


@dataclass
class DictEntry:
    canonical: str
    type: str
    synonyms: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def aliases(self) -> list[str]:
        out = [self.canonical]
        out.extend(s for s in self.synonyms if s and s != self.canonical)
        return out


class EntityDictionary:
    def __init__(self, entries: list[DictEntry]) -> None:
        self.entries = entries
        self.alias2canonical: dict[str, str] = {}
        self.canonical_type: dict[str, str] = {}
        self.alias_type: dict[str, str] = {}
        for entry in entries:
            self.canonical_type[entry.canonical] = entry.type
            for alias in entry.aliases:
                self.alias2canonical[alias] = entry.canonical
                self.alias_type[alias] = entry.type

    # ---- 查询 ----
    def canonicalize(self, surface: str) -> str:
        return self.alias2canonical.get(surface, surface)

    def type_of(self, surface: str) -> str | None:
        return self.alias_type.get(surface) or self.canonical_type.get(surface)

    def aliases_sorted(self, include_synonyms: bool = True) -> list[str]:
        aliases = list(self.alias_type.keys()) if include_synonyms else list(self.canonical_type.keys())
        return sorted(aliases, key=len, reverse=True)

    def by_type(self, type_name: str) -> list[str]:
        return [e.canonical for e in self.entries if e.type == type_name]

    @property
    def size(self) -> int:
        return len(self.entries)

    @property
    def alias_size(self) -> int:
        return len(self.alias_type)

    def type_stats(self) -> dict[str, int]:
        stats: dict[str, int] = {}
        for entry in self.entries:
            stats[entry.type] = stats.get(entry.type, 0) + 1
        return stats


def load_dictionary(path: Path | str = ENTITY_DICT) -> EntityDictionary:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"找不到实体词典：{path}")
    entries: list[DictEntry] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for raw in csv.DictReader(fh):
            canonical = (raw.get("canonical") or "").strip()
            if not canonical:
                continue
            synonyms = [s.strip() for s in (raw.get("synonyms") or "").split(";") if s.strip()]
            entries.append(
                DictEntry(
                    canonical=canonical,
                    type=(raw.get("type") or "").strip(),
                    synonyms=synonyms,
                    note=(raw.get("note") or "").strip(),
                )
            )
    if not entries:
        raise ValueError(f"词典为空：{path}")
    return EntityDictionary(entries)