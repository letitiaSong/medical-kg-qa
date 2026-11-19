# -*- coding: utf-8 -*-
"""Prompt 构建：Schema 感知 + 少样本示例 + 输出格式约束。

作业第 3、4 步都围绕这里：Schema 卡（schema_card）直接决定模型会不会编造
不存在的标签；少样本示例覆盖四类关系、反向查询、计数与多跳。
"""
from __future__ import annotations

import json
from typing import Iterable, Optional

from ..schema import schema_card

SYSTEM_TEMPLATE = """你是一名图数据库工程师，负责把中文医学问题翻译成 TuGraph 的 Cypher 查询。

{schema}

【生成规则】
1. 只能生成只读查询：以 MATCH 开头，包含 RETURN，禁止 CREATE / MERGE / SET / DELETE / CALL 等写操作。
2. 节点名称属性统一用 name（不是 title / label / 实体名），节点主键属性是 id。
3. 关系方向必须与 Schema 一致，不要把箭头写反；需要反向查找时把变量位置对调。
4. 除统计类问题外都要加 LIMIT（默认 LIMIT 20），避免一次返回过多数据。
5. 关系查询要带上来源字段，便于溯源：r.qa_id AS 来源, r.evidence AS 证据。
6. RETURN 的列名用中文别名，方便直接展示给用户。
7. 如果问题超出图谱范围（问天气、问图谱里没有的实体、问需要推理的内容），不要编造 Cypher，
   返回 {{"unanswerable": true, "reason": "用一句中文说明原因"}}。
8. 只输出一个 JSON 对象，不要输出 Markdown 代码块、不要解释过程。

【输出格式】
{{"cypher": "MATCH ... RETURN ...", "explanation": "一句话说明这条查询做了什么", "unanswerable": false}}

【示例】
{examples}
"""

EXAMPLES: list[dict[str, str]] = [
    {
        "q": "高血压有哪些症状？",
        "cypher": "MATCH (d:Disease {name: '高血压'})-[:HAS_SYMPTOM]->(s:Symptom) "
        "RETURN s.name AS 症状 LIMIT 20",
    },
    {
        "q": "癫痫属于哪个科室？",
        "cypher": "MATCH (d:Disease {name: '癫痫'})-[:BELONGS_TO]->(dept:Department) "
        "RETURN dept.name AS 科室 LIMIT 5",
    },
    {
        "q": "2型糖尿病常用什么药？",
        "cypher": "MATCH (d:Disease {name: '2型糖尿病'})-[:USES_DRUG]->(dr:Drug) "
        "RETURN dr.name AS 药品 LIMIT 20",
    },
    {
        "q": "冠心病要做哪些检查？",
        "cypher": "MATCH (d:Disease {name: '冠心病'})-[r:REQUIRES_EXAM]->(e:Examination) "
        "RETURN e.name AS 检查, r.scope AS 性质, r.qa_id AS 来源 LIMIT 20",
    },
    {
        "q": "哪些疾病会出现头痛？",
        "cypher": "MATCH (d:Disease)-[r:HAS_SYMPTOM]->(s:Symptom {name: '头痛'}) "
        "RETURN d.name AS 疾病, r.qa_id AS 来源 LIMIT 20",
    },
    {
        "q": "图谱里一共有多少种疾病？",
        "cypher": "MATCH (d:Disease) RETURN count(d) AS 疾病数",
    },
    {
        "q": "失眠和焦虑障碍有没有相同的用药？",
        "cypher": "MATCH (d:Disease {name: '失眠'})-[:USES_DRUG]->(dr:Drug)<-[:USES_DRUG]-(other:Disease) "
        "WHERE other.name <> '失眠' RETURN other.name AS 疾病, dr.name AS 共同药品 LIMIT 10",
    },
    {
        "q": "今天天气怎么样？",
        "answer": "unanswerable",
    },
]


def _format_examples(examples: Iterable[dict[str, str]] = EXAMPLES) -> str:
    lines: list[str] = []
    for i, item in enumerate(examples, 1):
        lines.append(f"例{i}：问题：{item['q']}")
        if item.get("answer") == "unanswerable":
            lines.append('输出：{"unanswerable": true, "reason": "问题与医疗知识图谱无关"}')
        else:
            payload = {"cypher": item["cypher"], "explanation": "", "unanswerable": False}
            lines.append("输出：" + json.dumps(payload, ensure_ascii=False))
        lines.append("")
    return "\n".join(lines).strip()


def build_system_prompt(examples: Optional[list[dict]] = None) -> str:
    return SYSTEM_TEMPLATE.format(
        schema=schema_card(), examples=_format_examples(examples or EXAMPLES)
    )


def build_messages(
    question: str,
    history: Optional[list[dict]] = None,
    entity_hints: Optional[list[str]] = None,
    examples: Optional[list[dict]] = None,
) -> list[dict]:
    """构造 chat messages。history 只保留最后一轮问答，避免上下文过长。"""
    messages: list[dict] = [{"role": "system", "content": build_system_prompt(examples)}]
    if history:
        for turn in history[-2:]:
            q = turn.get("question", "")
            if q:
                messages.append({"role": "user", "content": f"问题：{q}"})
            cypher = turn.get("cypher", "")
            if cypher:
                payload = {"cypher": cypher, "explanation": "", "unanswerable": False}
                messages.append(
                    {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)}
                )
    content = f"问题：{question}"
    if entity_hints:
        content += "\n图谱中匹配到的实体：" + "；".join(entity_hints)
    messages.append({"role": "user", "content": content})
    return messages