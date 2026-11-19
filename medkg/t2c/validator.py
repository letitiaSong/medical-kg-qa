# -*- coding: utf-8 -*-
"""Cypher 安全校验：只允许只读查询，禁止建/删/改，防止大模型把库写坏。

这是作业里"提示词工程 + 安全兜底"的一环：即使模型生成了 CREATE/DELETE，
也会在执行前被拦下来，并把原因反馈给模型让它重写。
"""
from __future__ import annotations

import re

from ..config import LABELS, RELATIONS

FORBIDDEN = (
    "CREATE",
    "MERGE",
    "DELETE",
    "DETACH",
    "SET ",
    "REMOVE",
    "DROP",
    "CALL",
    "LOAD CSV",
    "FOREACH",
    "ALTER",
    "GRANT",
    "REVOKE",
    "USE ",
)

LABEL_USE_RE = re.compile(r"\(\s*(?:\w+)?\s*:\s*(\w+)")
REL_USE_RE = re.compile(r"\[\s*(?:\w+)?\s*:\s*(\w+)")
AGG_RE = re.compile(r"\b(count|sum|avg|min|max)\s*\(", re.IGNORECASE)


def validate(cypher: str) -> list[dict]:
    """返回问题清单：[{"level": "error"|"warn", "message": str}]，没有 error 即可执行。"""
    issues: list[dict] = []
    text = (cypher or "").strip()
    if not text:
        return [{"level": "error", "message": "生成的 Cypher 为空"}]

    body = text.rstrip(";").strip()
    if ";" in body:
        issues.append({"level": "error", "message": "不允许一次执行多条语句（出现分号）"})

    upper = body.upper()
    for kw in FORBIDDEN:
        if re.search(rf"(^|[\s(]){re.escape(kw)}", upper):
            issues.append(
                {"level": "error", "message": f"包含写操作关键字 {kw.strip()}，本系统只允许只读查询"}
            )
    if "OPTIONAL MATCH" in upper:
        issues.append({"level": "warn", "message": "使用了 OPTIONAL MATCH，离线模拟库不支持"})
    if "UNION" in upper:
        issues.append({"level": "warn", "message": "使用了 UNION，离线模拟库不支持"})

    if not upper.startswith("MATCH"):
        issues.append({"level": "error", "message": "查询必须以 MATCH 开头"})
    if "RETURN" not in upper:
        issues.append({"level": "error", "message": "查询缺少 RETURN 子句"})

    known = set(LABELS) | set(RELATIONS)
    used = set(LABEL_USE_RE.findall(body)) | set(REL_USE_RE.findall(body))
    unknown = sorted(label for label in used if label not in known)
    if unknown:
        issues.append(
            {
                "level": "error",
                "message": "使用了 Schema 中不存在的标签/关系：" + "、".join(unknown),
            }
        )

    if "LIMIT" not in upper and not AGG_RE.search(body):
        issues.append({"level": "warn", "message": "没有 LIMIT，可能返回过多结果"})
    if re.fullmatch(r"MATCH\s*\(\s*\w*\s*\)\s*RETURN\s+\w+\s*", body + " ", re.IGNORECASE):
        issues.append({"level": "warn", "message": "全图扫描返回整节点，建议限定标签与属性"})
    return issues


def has_error(issues: list[dict]) -> bool:
    return any(item["level"] == "error" for item in issues)


def normalize(cypher: str) -> str:
    """去掉代码块围栏、压缩空白，方便写入测试集和做完全匹配比较。"""
    text = (cypher or "").strip()
    text = re.sub(r"^```(?:cypher|sql)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip().rstrip(";").strip()
    text = re.sub(r"\s+", " ", text)
    return text