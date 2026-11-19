# -*- coding: utf-8 -*-
"""图谱构建：实体归一（融合）→ 关系合并 → 导出 CSV/import.yaml → 写入图库。

知识融合在这里做了三件事：
1. 同义合并：别名统一到规范名（词典 alias -> canonical）；
2. 重复关系合并：不同问答支持同一条 (头, 关系, 尾) 时只保留一条，用 qa_id 串记来源；
3. 冲突处理：同一关系的 scope 不一致时，"确定要做"优先于"建议做"。
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from ..config import GRAPH_DIR, ensure_dirs
from ..etl.preprocess import QARecord
from ..extract.dictionary import EntityDictionary
from ..extract.relation import Triple, extract_relations
from ..extract.rule_ner import Mention, extract_mentions
from ..schema import NODE_DEFS

TYPE_CN = {k: v["cn"] for k, v in NODE_DEFS.items()}

# 建议/必须 的判定线索：同一关系在不同问答里 scope 可能不同
_MUST_HINTS = ("必须", "一定要", "首选", "确诊", "需要做", "应当")
_SUGGEST_HINTS = ("可以", "建议", "可选", "酌情")


@dataclass
class GraphNode:
    label: str
    id: str
    name: str
    description: str = ""

    def as_row(self) -> dict:
        return {
            "label": self.label,
            "id": self.id,
            "name": self.name,
            "description": self.description,
        }


@dataclass
class GraphEdge:
    rel: str
    src: str
    src_label: str
    dst: str
    dst_label: str
    qa_ids: list[str] = field(default_factory=list)
    evidence: str = ""
    scope: str = ""
    support: int = 1

    @property
    def weight(self) -> float:
        return round(min(1.0, 0.4 + 0.2 * self.support), 2)

    def as_row(self) -> dict:
        return {
            "rel": self.rel,
            "src": self.src,
            "src_label": self.src_label,
            "dst": self.dst,
            "dst_label": self.dst_label,
            "qa_id": ";".join(self.qa_ids[:5]),
            "evidence": self.evidence,
            "weight": self.weight,
            "scope": self.scope,
        }


@dataclass
class GraphData:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    review: list[dict] = field(default_factory=list)

    @property
    def edge_triples(self) -> set[tuple[str, str, str]]:
        return {(e.src, e.rel, e.dst) for e in self.edges}

    def node_ids(self) -> set[str]:
        return {n.id for n in self.nodes}


def _scope_of(text: str, relation: str) -> str:
    if relation != "REQUIRES_EXAM":
        return ""
    if any(h in text for h in _MUST_HINTS):
        return "definite"
    if any(h in text for h in _SUGGEST_HINTS):
        return "recommend"
    return "unspecified"


def _describe(label: str, name: str, dictionary: EntityDictionary) -> str:
    for entry in dictionary.entries:
        if entry.canonical == name:
            parts = []
            if entry.note:
                parts.append(entry.note)
            if entry.synonyms:
                parts.append("别名：" + "、".join(entry.synonyms))
            parts.append(f"来源：课堂问答整理，未经医学核验")
            return "；".join(parts)
    return f"{TYPE_CN.get(label, label)}：{name}；来源：课堂问答整理，未经医学核验"


def build_graph_data(
    records: list[QARecord],
    dictionary: EntityDictionary,
    ner_mode: str = "synonym",
    mention_override: dict[str, list[Mention]] | None = None,
) -> GraphData:
    """从清洗后的问答构建节点与关系（纯内存，不依赖数据库）。"""
    nodes: dict[tuple[str, str], GraphNode] = {}
    edge_map: dict[tuple[str, str, str], GraphEdge] = {}
    review: list[dict] = []
    support_counter: Counter = Counter()
    scope_votes: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    alias_hits: Counter = Counter()

    for rec in records:
        mentions = (mention_override or {}).get(rec.qa_id)
        if mentions is None:
            mentions = extract_mentions(rec.text, dictionary, mode=ner_mode)
        for m in mentions:
            alias_hits[m.text] += 1 if m.text != m.canonical else 0
            key = (m.type, m.canonical)
            if key not in nodes:
                nodes[key] = GraphNode(
                    label=m.type,
                    id=m.canonical,
                    name=m.canonical,
                    description=_describe(m.type, m.canonical, dictionary),
                )

        result = extract_relations(
            mentions,
            text=rec.text,
            qa_id=rec.qa_id,
            department=rec.department,
            evidence=rec.title,
            scope=_scope_of(rec.text, "REQUIRES_EXAM"),
        )
        review.extend(result.review)
        for triple in result.triples:
            _absorb(triple, rec, edge_map, support_counter, scope_votes)

    for key, edge in edge_map.items():
        scopes = scope_votes[key]
        if "definite" in scopes:
            edge.scope = "definite"
        elif "recommend" in scopes:
            edge.scope = "recommend"
        else:
            edge.scope = "unspecified"
        edge.support = support_counter[key]

    # 只保留有关系的节点？——保留全部，孤立节点单独统计（可能是分词边界问题）
    connected = {e.src for e in edge_map.values()} | {e.dst for e in edge_map.values()}
    isolated = [n for n in nodes.values() if n.id not in connected]

    stats = {
        "qa_total": len(records),
        "nodes": len(nodes),
        "nodes_by_label": dict(Counter(n.label for n in nodes.values())),
        "edges": len(edge_map),
        "edges_by_rel": dict(Counter(e.rel for e in edge_map.values())),
        "isolated_nodes": [f"{n.label}:{n.name}" for n in isolated],
        "alias_merges": dict(alias_hits.most_common(15)),
        "multi_source_edges": sum(1 for e in edge_map.values() if len(e.qa_ids) > 1),
        "review_items": len(review),
        "ner_mode": ner_mode,
    }
    return GraphData(
        nodes=sorted(nodes.values(), key=lambda n: (n.label, n.id)),
        edges=sorted(edge_map.values(), key=lambda e: (e.rel, e.src, e.dst)),
        stats=stats,
        review=review,
    )


def _absorb(
    triple: Triple,
    rec: QARecord,
    edge_map: dict[tuple[str, str, str], GraphEdge],
    support_counter: Counter,
    scope_votes: dict[tuple[str, str, str], list[str]],
) -> None:
    key = (triple.head, triple.relation, triple.tail)
    support_counter[key] += 1
    scope_votes[key].append(triple.scope)
    if key in edge_map:
        edge = edge_map[key]
        if rec.qa_id not in edge.qa_ids:
            edge.qa_ids.append(rec.qa_id)
        return
    edge_map[key] = GraphEdge(
        rel=triple.relation,
        src=triple.head,
        src_label=triple.head_type,
        dst=triple.tail,
        dst_label=triple.tail_type,
        qa_ids=[rec.qa_id],
        evidence=triple.evidence,
        scope=triple.scope,
    )


# ---------------- 导出 ----------------
def export(graph: GraphData, out_dir: Path | str = GRAPH_DIR) -> dict[str, Path]:
    ensure_dirs()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    node_path = out / "nodes.csv"
    with node_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["label", "id", "name", "description"])
        writer.writeheader()
        for node in graph.nodes:
            writer.writerow(node.as_row())

    edge_path = out / "edges.csv"
    with edge_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "rel",
                "src",
                "src_label",
                "dst",
                "dst_label",
                "qa_id",
                "evidence",
                "weight",
                "scope",
            ],
        )
        writer.writeheader()
        for edge in graph.edges:
            writer.writerow(edge.as_row())

    # 每类节点一个文件：TuGraph 的批量导入要求一类标签一个文件
    per_label_dir = out / "by_label"
    per_label_dir.mkdir(exist_ok=True)
    for label in NODE_DEFS:
        rows = [n for n in graph.nodes if n.label == label]
        with (per_label_dir / f"vertex_{label}.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["id", "name", "description"])
            writer.writeheader()
            for node in rows:
                writer.writerow({"id": node.id, "name": node.name, "description": node.description})

    yaml_path = out / "import.yaml"
    yaml_path.write_text(_import_yaml(), encoding="utf-8")

    review_path = out / "review_items.csv"
    with review_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["qa_id", "reason", "text"])
        writer.writeheader()
        for item in graph.review:
            writer.writerow({k: item.get(k, "") for k in ("qa_id", "reason", "text")})

    stats_path = out / "graph_stats.json"
    stats_path.write_text(
        json.dumps(graph.stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "nodes": node_path,
        "edges": edge_path,
        "by_label": per_label_dir,
        "import_yaml": yaml_path,
        "review": review_path,
        "stats": stats_path,
    }


def _import_yaml() -> str:
    lines = ["schema:"]
    for label, spec in NODE_DEFS.items():
        lines.append(f"  - label: {label}")
        lines.append("    type: VERTEX")
        lines.append("    primary: id")
        lines.append("    properties:")
        for prop, ptype in spec["props"].items():
            lines.append(f"      - name: {prop}")
            lines.append(f"        type: {ptype}")
    from ..schema import REL_DEFS

    for rel, spec in REL_DEFS.items():
        lines.append(f"  - label: {rel}")
        lines.append("    type: EDGE")
        lines.append(f"    constraints: [{spec['from'][0]}, {spec['to'][0]}]")
        lines.append("    properties:")
        for prop, ptype in spec["props"].items():
            lines.append(f"      - name: {prop}")
            lines.append(f"        type: {ptype}")
    lines.append("files:")
    for label in NODE_DEFS:
        lines.append(f"  - path: by_label/vertex_{label}.csv")
        lines.append("    type: CSV")
        lines.append("    header: true")
    lines.append("  - path: edges.csv")
    lines.append("    type: CSV")
    lines.append("    header: true")
    return "\n".join(lines) + "\n"


# ---------------- 写入图库 ----------------
def load_into_store(store, graph: GraphData, progress: bool = True) -> dict:
    store.ensure_schema()
    store.clear_all()
    for node in graph.nodes:
        store.add_node(
            node.label,
            {"id": node.id, "name": node.name, "description": node.description},
        )
    for edge in graph.edges:
        props = {
            "qa_id": ";".join(edge.qa_ids[:5]),
            "evidence": edge.evidence,
            "weight": edge.weight,
        }
        if edge.rel == "REQUIRES_EXAM":
            props["scope"] = edge.scope or "unspecified"
        store.add_edge(
            edge.rel,
            edge.src,
            edge.dst,
            props,
            src_label=edge.src_label,
            dst_label=edge.dst_label,
        )
    if hasattr(store, "save"):
        store.save()
    if progress:
        print(f"  已写入节点 {store.count_nodes()} 个，关系 {store.count_edges()} 条")
    return {"nodes": store.count_nodes(), "edges": store.count_edges()}