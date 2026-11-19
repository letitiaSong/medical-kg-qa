# -*- coding: utf-8 -*-
"""图谱质量评估：Schema 合规、属性完整、连通性、重复与冲突、覆盖度。

作业第 2 步要求"对图谱质量进行评估"，这里给出 6 个可量化指标 + 1 条 Cypher
抽查（用标准 Cypher 从图库里取数，证明入库后的数据可查）。
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque

from ..config import LABELS, RELATIONS
from ..schema import NODE_DEFS, REL_DEFS
from .builder import GraphData


def _weak_components(nodes: list[str], edges: list[tuple[str, str]]) -> list[int]:
    adj: dict[str, set[str]] = defaultdict(set)
    for src, dst in edges:
        adj[src].add(dst)
        adj[dst].add(src)
    seen: set[str] = set()
    sizes: list[int] = []
    for node in nodes:
        if node in seen:
            continue
        queue = deque([node])
        seen.add(node)
        size = 0
        while queue:
            cur = queue.popleft()
            size += 1
            for nxt in adj[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        sizes.append(size)
    return sorted(sizes, reverse=True)


def evaluate(graph: GraphData, qa_ids: list[str] | None = None) -> dict:
    node_names = [n.id for n in graph.nodes]
    edges = [(e.src, e.dst) for e in graph.edges]
    components = _weak_components(node_names, edges)

    # 1. Schema 合规：标签/关系合法、方向正确
    illegal_labels = [n.label for n in graph.nodes if n.label not in LABELS]
    illegal_rels = [e.rel for e in graph.edges if e.rel not in RELATIONS]
    wrong_direction = [
        f"{e.src}-[{e.rel}]->{e.dst}"
        for e in graph.edges
        if e.rel in REL_DEFS
        and (e.src_label != REL_DEFS[e.rel]["from"][0] or e.dst_label != REL_DEFS[e.rel]["to"][0])
    ]

    # 2. 属性完整性
    missing_desc = [n.id for n in graph.nodes if not n.description.strip()]
    missing_source = [f"{e.src}-{e.rel}-{e.dst}" for e in graph.edges if not e.qa_ids]
    missing_evidence = [f"{e.src}-{e.rel}-{e.dst}" for e in graph.edges if not e.evidence.strip()]
    missing_scope = [
        f"{e.src}-{e.rel}-{e.dst}"
        for e in graph.edges
        if e.rel == "REQUIRES_EXAM" and not e.scope
    ]

    # 3. 重复与冲突
    triples = Counter((e.src, e.rel, e.dst) for e in graph.edges)
    duplicates = [k for k, v in triples.items() if v > 1]
    same_pair = Counter((e.src, e.rel) for e in graph.edges)
    multi_tail = {k: v for k, v in same_pair.items() if v > 1}
    # 同一疾病的检查，有的原文说"必须做"、有的说"建议做"——需要人工统一口径
    scope_by_src: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        if edge.rel == "REQUIRES_EXAM":
            scope_by_src[edge.src].add(edge.scope)
    scope_inconsistent = {src: sorted(v) for src, v in scope_by_src.items() if len(v) > 1}

    # 4. 覆盖度
    covered_qa = {qid for e in graph.edges for qid in e.qa_ids}
    total_qa = len(qa_ids) if qa_ids else len(covered_qa)
    covers_department = {e.dst for e in graph.edges if e.rel == "BELONGS_TO"}

    # 5. 规模与结构
    degree = Counter()
    for src, dst in edges:
        degree[src] += 1
        degree[dst] += 1
    avg_degree = round(sum(degree.values()) / max(1, len(node_names)), 2)

    node_label_cover = sorted({n.label for n in graph.nodes})
    rel_cover = sorted({e.rel for e in graph.edges})

    metrics = {
        "节点数": len(graph.nodes),
        "关系数": len(graph.edges),
        "节点标签覆盖": f"{len(node_label_cover)}/{len(LABELS)}",
        "关系类型覆盖": f"{len(rel_cover)}/{len(RELATIONS)}",
        "Schema合规率": _ratio(
            len(graph.nodes) + len(graph.edges) - len(illegal_labels) - len(illegal_rels) - len(wrong_direction),
            len(graph.nodes) + len(graph.edges),
        ),
        "属性完整率": _ratio(
            (len(graph.nodes) - len(missing_desc))
            + (len(graph.edges) - len(missing_source) - len(missing_evidence) - len(missing_scope)),
            len(graph.nodes) + len(graph.edges),
        ),
        "重复三元组": len(duplicates),
        "检查强度不一致": len(scope_inconsistent),
        "待人工审核项": len(graph.review),
        "孤立节点": len(graph.stats.get("isolated_nodes", [])),
        "弱连通分量": len(components),
        "最大连通分量占比": _ratio(components[0] if components else 0, len(node_names)),
        "平均度": avg_degree,
        "问答覆盖率": _ratio(len(covered_qa), total_qa),
        "科室覆盖": f"{len(covers_department)}/4",
    }

    details = {
        "illegal_labels": illegal_labels,
        "illegal_relations": illegal_rels,
        "wrong_direction": wrong_direction,
        "missing_description": missing_desc,
        "missing_source": missing_source,
        "missing_evidence": missing_evidence,
        "missing_scope": missing_scope,
        "duplicate_triples": duplicates[:20],
        "scope_inconsistent": scope_inconsistent,
        "isolated_nodes": graph.stats.get("isolated_nodes", []),
        "multi_tail_relations": {f"{k[0]}-{k[1]}": v for k, v in list(multi_tail.items())[:10]},
        "component_sizes": components,
        "nodes_by_label": dict(Counter(n.label for n in graph.nodes)),
        "edges_by_rel": dict(Counter(e.rel for e in graph.edges)),
        "uncovered_qa": sorted(set(qa_ids or []) - covered_qa)[:20],
    }
    return {"metrics": metrics, "details": details}


def _ratio(num: int, den: int) -> str:
    if den <= 0:
        return "N/A"
    return f"{num / den:.2%}"


def spot_check_queries() -> list[tuple[str, str]]:
    """用标准 Cypher 抽查（作业要求：入图后用 Cypher 验证）。"""
    return [
        ("图谱规模", "MATCH (n) RETURN count(n) AS 节点数"),
        ("关系规模", "MATCH ()-[r]->() RETURN count(r) AS 关系数"),
        ("标签分布", "MATCH (n) RETURN n.id AS 名称 LIMIT 5"),
        (
            "疾病-症状抽样",
            "MATCH (d:Disease)-[r:HAS_SYMPTOM]->(s:Symptom) "
            "RETURN d.name AS 疾病, s.name AS 症状, r.qa_id AS 来源 LIMIT 5",
        ),
        (
            "疾病-检查抽样",
            "MATCH (d:Disease)-[r:REQUIRES_EXAM]->(e:Examination) "
            "RETURN d.name AS 疾病, e.name AS 检查, r.scope AS 性质 LIMIT 5",
        ),
        (
            "癫痫相关",
            "MATCH (d:Disease {name: '癫痫'})-[r]->(x) RETURN x.name AS 关联实体, r.qa_id AS 来源 LIMIT 10",
        ),
    ]