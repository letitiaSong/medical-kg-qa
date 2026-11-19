# -*- coding: utf-8 -*-
"""把查询结果组织成中文回答：编号、来源、证据、审核状态。"""
from __future__ import annotations

from typing import Iterable, Optional

from ..storage.base import QueryResult

SCOPE_CN = {
    "definite": "确诊/必须",
    "recommend": "建议做",
    "unspecified": "未说明",
}
PROVENANCE_COLS = {"来源", "证据", "性质"}
DISCLAIMER = "审核状态：课堂参考，未经医学核验"


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _clip(text: str, limit: int = 40) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _one_line(names: Iterable[str], extras: dict[str, str]) -> str:
    parts = [name for name in names if name]
    line = " / ".join(parts)
    tags: list[str] = []
    scope = extras.get("性质")
    if scope:
        tags.append(SCOPE_CN.get(scope, scope))
    if tags:
        line += "（" + "，".join(tags) + "）"
    return line


def format_rows(result: QueryResult, max_rows: int = 10) -> list[str]:
    rows = result.to_dicts()
    columns = result.columns
    name_cols = [c for c in columns if c not in PROVENANCE_COLS]
    lines: list[str] = []
    for i, row in enumerate(rows[:max_rows], 1):
        extras = {c: _cell(row.get(c)) for c in columns if c in PROVENANCE_COLS}
        line = f"{i}. " + _one_line([_cell(row.get(c)) for c in name_cols], extras)
        if extras.get("来源"):
            line += f"  来源：{extras['来源']}"
        if extras.get("证据"):
            line += f"  证据：{_clip(extras['证据'])}"
        lines.append(line)
    if len(rows) > max_rows:
        lines.append(f"……另有 {len(rows) - max_rows} 条记录已省略")
    return lines


def format_answer(
    result: QueryResult,
    intent_name: str = "",
    entity: str = "",
    max_rows: int = 10,
    with_disclaimer: bool = True,
) -> str:
    columns = result.columns
    rows = result.to_dicts()
    if not rows:
        return "当前图谱中没有查到相关记录。可以换一种问法，或确认实体名称是否在图谱中。"

    # 统计类问题
    if len(columns) == 1 and intent_name == "count_disease":
        value = _cell(rows[0].get(columns[0]))
        return f"图谱中共有 {value} 种疾病。"

    # 科室归属
    if intent_name == "department" and "科室" in columns and entity:
        depts = [_cell(r.get("科室")) for r in rows if _cell(r.get("科室"))]
        if depts:
            text = f"{entity} 属于 {'、'.join(depts)}。"
            return text + (f"\n{DISCLAIMER}" if with_disclaimer else "")

    # 疾病简介
    if intent_name == "description" and "简介" in columns:
        name = _cell(rows[0].get("疾病")) or entity
        desc = _cell(rows[0].get("简介")) or "图谱中暂无简介。"
        text = f"{name}：{desc}"
        return text + (f"\n{DISCLAIMER}" if with_disclaimer else "")

    lines = [f"查询到 {result.count} 条记录："]
    lines.extend(format_rows(result, max_rows=max_rows))
    if with_disclaimer:
        lines.append(DISCLAIMER)
    return "\n".join(lines)


def collect_sources(result: QueryResult) -> list[str]:
    sources: list[str] = []
    if "来源" not in result.columns:
        return sources
    for row in result.to_dicts():
        value = _cell(row.get("来源"))
        if value and value not in sources:
            sources.append(value)
    return sources