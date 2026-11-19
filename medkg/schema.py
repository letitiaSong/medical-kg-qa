# -*- coding: utf-8 -*-
"""图谱 Schema 的单一事实来源。

节点 5 类：Disease / Symptom / Drug / Department / Examination
关系 4 类：HAS_SYMPTOM / USES_DRUG / BELONGS_TO / REQUIRES_EXAM

真实 TuGraph 的建表 DDL、离线模拟库、以及 Text2Cypher 的 Prompt 都从这里取，
避免"脚本里一套、提示词里另一套"导致大模型生成不存在的标签。
"""
from __future__ import annotations

from .config import COMMON_PROPS, LABELS, RELATION_ALIASES, RELATIONS

__all__ = [
    "NODE_DEFS",
    "REL_DEFS",
    "NODE_SIGNATURE",
    "EDGE_SIGNATURE",
    "ddl_statements",
    "schema_card",
    "node_labels",
    "relation_types",
]

NODE_DEFS: dict[str, dict] = {
    "Disease": {
        "cn": "疾病",
        "desc": "疾病、综合征或功能障碍，例如 高血压、癫痫",
        "props": {"id": "STRING", "name": "STRING", "description": "STRING"},
    },
    "Symptom": {
        "cn": "症状",
        "desc": "患者主观感受或可观察到的异常表现，例如 头晕、反酸",
        "props": {"id": "STRING", "name": "STRING", "description": "STRING"},
    },
    "Drug": {
        "cn": "药品",
        "desc": "治疗用药，例如 氨氯地平、奥美拉唑",
        "props": {"id": "STRING", "name": "STRING", "description": "STRING"},
    },
    "Department": {
        "cn": "科室",
        "desc": "就诊科室，例如 心血管内科、神经内科",
        "props": {"id": "STRING", "name": "STRING", "description": "STRING"},
    },
    "Examination": {
        "cn": "检查",
        "desc": "检查或检验项目，例如 心电图、胃镜",
        "props": {"id": "STRING", "name": "STRING", "description": "STRING"},
    },
}

REL_DEFS: dict[str, dict] = {
    "HAS_SYMPTOM": {
        "cn": "症状表现",
        "desc": "疾病 -> 症状，方向固定为 Disease -> Symptom",
        "from": ["Disease"],
        "to": ["Symptom"],
        "props": {"qa_id": "STRING", "evidence": "STRING", "weight": "DOUBLE"},
    },
    "USES_DRUG": {
        "cn": "用药",
        "desc": "疾病 -> 药品，方向固定为 Disease -> Drug",
        "from": ["Disease"],
        "to": ["Drug"],
        "props": {"qa_id": "STRING", "evidence": "STRING", "weight": "DOUBLE"},
    },
    "BELONGS_TO": {
        "cn": "归属科室",
        "desc": "疾病 -> 科室，方向固定为 Disease -> Department",
        "from": ["Disease"],
        "to": ["Department"],
        "props": {"qa_id": "STRING", "evidence": "STRING", "weight": "DOUBLE"},
    },
    "REQUIRES_EXAM": {
        "cn": "需要检查",
        "desc": "疾病 -> 检查，方向固定为 Disease -> Examination；scope='recommend' 表示原文是“建议做”",
        "from": ["Disease"],
        "to": ["Examination"],
        "props": {"qa_id": "STRING", "evidence": "STRING", "weight": "DOUBLE", "scope": "STRING"},
    },
}

NODE_SIGNATURE: dict[str, list[str]] = {label: list(NODE_DEFS[label]["props"]) for label in LABELS}
EDGE_SIGNATURE: dict[str, list[str]] = {rel: list(REL_DEFS[rel]["props"]) for rel in RELATIONS}


def node_labels() -> list[str]:
    return list(LABELS)


def relation_types() -> list[str]:
    return list(RELATIONS)


def _field_args(props: dict[str, str], primary: str | None = None) -> list[str]:
    args: list[str] = []
    for name, type_name in props.items():
        optional = "false" if name == primary else "true"
        args.extend([f"'{name}'", f"'{type_name}'", optional])
    return args


def ddl_statements(legacy_types: bool = False) -> list[str]:
    """生成建表语句。

    legacy_types=True 用于 TuGraph 3.x：类型名不加引号（STRING 而不是 'STRING'）。
    """
    statements: list[str] = []
    for label, spec in NODE_DEFS.items():
        props = spec["props"]
        primary = "id"
        args = _field_args(props, primary)
        if legacy_types:
            args = [a.replace("'STRING'", "STRING").replace("'DOUBLE'", "DOUBLE") for a in args]
        statements.append(f"CALL db.createVertexLabel('{label}', '{primary}', {', '.join(args)})")
    for rel, spec in REL_DEFS.items():
        props = spec["props"]
        args = _field_args(props)
        if legacy_types:
            args = [a.replace("'STRING'", "STRING").replace("'DOUBLE'", "DOUBLE") for a in args]
        extra = f", {', '.join(args)}" if args else ""
        statements.append(f"CALL db.createEdgeLabel('{rel}', '[]'{extra})")
    return statements


def schema_card() -> str:
    """给大模型看的 Schema 说明（Text2Cypher 的 Schema 感知部分）。"""
    lines = ["【节点类型】（括号内为属性）"]
    for label, spec in NODE_DEFS.items():
        props = ", ".join(spec["props"].keys())
        lines.append(f"- {label}（{spec['cn']}）: ({props})  {spec['desc']}")
    lines.append("")
    lines.append("【关系类型】（方向固定，不能反向写）")
    for rel, spec in REL_DEFS.items():
        props = ", ".join(spec["props"].keys())
        lines.append(
            f"- (:{spec['from'][0]})-[:{rel}]->(:{spec['to'][0]})  [{props}]  {spec['desc']}"
        )
    aliases = "、".join(f"{k} -> {v}" for k, v in RELATION_ALIASES.items())
    if aliases:
        lines.append(f"【关系别名】{aliases}（入库时已统一，查询时只用标准关系名）")
    lines.append(f"【节点主键】{COMMON_PROPS[0]}，同时提供 {', '.join(COMMON_PROPS[1:])} 属性。")
    return "\n".join(lines)