# -*- coding: utf-8 -*-
"""离线模拟图库（JSON 文件 + Cypher 子集解释器）。

用途：在没有安装 TuGraph 的电脑上，也能完整演示"建 Schema → 导入数据 →
Cypher 验证 → 问答 → 评测"的链路，方便写作业、录屏和自动化测试。
真实提交时把 TUGRAPH_MODE 设为 rest（或 auto）即可切换到真库。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from ..schema import ddl_statements, node_labels, relation_types
from .base import GraphError, GraphStore, QueryResult
from . import cypher_subset

SCHEMA_STATEMENTS = ddl_statements()


class MockStore(GraphStore):
    name = "mock-json"

    def __init__(self, path: Path | str, graph: str = "medical_course_2026") -> None:
        self.path = Path(path)
        self.graph = graph
        self._data: dict[str, Any] = {"graphs": {}}
        self._dirty = False

    # ---------------- 生命周期 ----------------
    def connect(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                self._data = {"graphs": {}}
        self._data.setdefault("graphs", {})
        self._ensure_graph()

    def close(self) -> None:
        self.save()

    def save(self) -> None:
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        self._dirty = False

    def ping(self) -> bool:
        return True

    def server_info(self) -> dict:
        return {
            "backend": self.name,
            "graph": self.graph,
            "file": str(self.path),
            "note": "离线模拟库：用于无 TuGraph 环境下演示，Cypher 由内置子集解释器执行",
        }

    # ---------------- 内部 ----------------
    def _ensure_graph(self) -> dict:
        graphs = self._data["graphs"]
        g = graphs.setdefault(
            self.graph,
            {"nodes": [], "edges": [], "schema": {"labels": [], "rels": [], "ddl": []}},
        )
        g.setdefault("nodes", [])
        g.setdefault("edges", [])
        g.setdefault("schema", {"labels": [], "rels": [], "ddl": []})
        g["schema"].setdefault("ddl", [])
        return g

    @property
    def graph_data(self) -> dict:
        return self._ensure_graph()

    def list_graphs(self) -> list[str]:
        return list(self._data.get("graphs", {}).keys())

    # ---------------- Schema ----------------
    def ensure_schema(self, force: bool = False) -> list[str]:
        g = self._ensure_graph()
        if force:
            g["schema"] = {"labels": [], "rels": [], "ddl": []}
        g["schema"]["labels"] = node_labels()
        g["schema"]["rels"] = relation_types()
        g["schema"]["ddl"] = list(SCHEMA_STATEMENTS)
        self._dirty = True
        return list(SCHEMA_STATEMENTS)

    def clear_all(self) -> None:
        g = self._ensure_graph()
        g["nodes"] = []
        g["edges"] = []
        self._dirty = True
        self.save()

    # ---------------- 写入 ----------------
    def add_node(self, label: str, props: dict[str, Any]) -> None:
        g = self._ensure_graph()
        node_id = str(props.get("id") or f"{label}:{props.get('name')}")
        props = {**props, "id": node_id}
        for node in g["nodes"]:
            if node["id"] == node_id:
                node["label"] = label
                node["props"].update(props)
                self._dirty = True
                return
        g["nodes"].append({"id": node_id, "label": label, "props": props})
        if label not in g["schema"]["labels"]:
            g["schema"]["labels"].append(label)
        self._dirty = True

    def add_edge(
        self,
        rel: str,
        src_id: str,
        dst_id: str,
        props: Optional[dict[str, Any]] = None,
        src_label: Optional[str] = None,
        dst_label: Optional[str] = None,
    ) -> None:
        g = self._ensure_graph()
        ids = {n["id"] for n in g["nodes"]}
        if src_id not in ids or dst_id not in ids:
            raise GraphError(f"关系两端节点不存在：{src_id} -> {dst_id}")
        props = props or {}
        for edge in g["edges"]:
            if edge["src"] == src_id and edge["dst"] == dst_id and edge["rel"] == rel:
                edge["props"].update(props)
                self._dirty = True
                return
        g["edges"].append({"src": src_id, "dst": dst_id, "rel": rel, "props": dict(props)})
        if rel not in g["schema"]["rels"]:
            g["schema"]["rels"].append(rel)
        self._dirty = True

    # ---------------- 统计与查询 ----------------
    def count_nodes(self, label: Optional[str] = None) -> int:
        nodes = self.graph_data["nodes"]
        return len([n for n in nodes if label is None or n["label"] == label])

    def count_edges(self, rel: Optional[str] = None) -> int:
        edges = self.graph_data["edges"]
        return len([e for e in edges if rel is None or e["rel"] == rel])

    def execute(self, cypher: str) -> QueryResult:
        try:
            parsed = cypher_subset.parse(cypher)
        except cypher_subset.CyperSubsetError as exc:
            raise GraphError(f"[离线模拟库] {exc}") from exc
        g = self.graph_data
        result = cypher_subset.evaluate(parsed, g["nodes"], g["edges"], cypher)
        return result

    def node_ids_by_label(self, label: str) -> list[str]:
        return [n["id"] for n in self.graph_data["nodes"] if n["label"] == label]

    def describe(self) -> dict:
        g = self.graph_data
        by_label: dict[str, int] = {}
        for n in g["nodes"]:
            by_label[n["label"]] = by_label.get(n["label"], 0) + 1
        by_rel: dict[str, int] = {}
        for e in g["edges"]:
            by_rel[e["rel"]] = by_rel.get(e["rel"], 0) + 1
        return {
            "graph": self.graph,
            "nodes": len(g["nodes"]),
            "edges": len(g["edges"]),
            "nodes_by_label": by_label,
            "edges_by_rel": by_rel,
            "schema": g["schema"],
        }