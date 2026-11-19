# -*- coding: utf-8 -*-
"""图数据库访问层的统一接口。

作业里前端（FastAPI / CLI / 评测脚本）都只依赖 GraphStore 这一层，
因此既可以在本机连真实 TuGraph，也可以在没装数据库的机器上用离线模拟库跑通全流程。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional


class GraphError(RuntimeError):
    """图数据库操作失败的统一异常。"""


@dataclass
class QueryResult:
    """一次 Cypher 查询的返回结果。"""

    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    elapsed_ms: float = 0.0
    cypher: str = ""

    def to_dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, row)) for row in self.rows]

    def to_table(self, max_rows: int = 50) -> str:
        """转成等宽文本表，方便命令行展示。"""
        if not self.columns:
            return "(空结果)"
        data = [["" if v is None else str(v) for v in row] for row in self.rows[:max_rows]]
        widths = [len(c) for c in self.columns]
        for row in data:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(cell))

        def line(cells: Iterable[str]) -> str:
            return " | ".join(c.ljust(widths[i]) for i, c in enumerate(cells))

        out = [line(self.columns), "-+-".join("-" * w for w in widths)]
        out.extend(line(r) for r in data)
        if len(self.rows) > max_rows:
            out.append(f"... 共 {len(self.rows)} 行，仅显示前 {max_rows} 行")
        return "\n".join(out)

    @property
    def count(self) -> int:
        return len(self.rows)


class GraphStore:
    """图数据库后端接口。"""

    name = "abstract"

    # ---- 连接与生命周期 ----
    def connect(self) -> None:  # pragma: no cover - 接口
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - 接口
        pass

    def ping(self) -> bool:  # pragma: no cover - 接口
        raise NotImplementedError

    def server_info(self) -> dict:  # pragma: no cover - 接口
        return {"backend": self.name}

    # ---- Schema ----
    def ensure_schema(self, force: bool = False) -> list[str]:
        """创建 5 类节点、4 类关系的 Schema，返回执行过的语句。"""
        raise NotImplementedError

    def clear_all(self) -> None:
        raise NotImplementedError

    # ---- 写入 ----
    def add_node(self, label: str, props: dict[str, Any]) -> None:
        raise NotImplementedError

    def add_edge(
        self,
        rel: str,
        src_id: str,
        dst_id: str,
        props: Optional[dict[str, Any]] = None,
        src_label: Optional[str] = None,
        dst_label: Optional[str] = None,
    ) -> None:
        raise NotImplementedError

    # ---- 统计与查询 ----
    def count_nodes(self, label: Optional[str] = None) -> int:
        raise NotImplementedError

    def count_edges(self, rel: Optional[str] = None) -> int:
        raise NotImplementedError

    def execute(self, cypher: str) -> QueryResult:
        raise NotImplementedError

    # ---- 便捷方法（用 Cypher 走一遍，保证"标准 Cypher"可用）----
    def query_disease_symptoms(self, name: str) -> QueryResult:
        cypher = (
            "MATCH (d:Disease)-[r:HAS_SYMPTOM]->(s:Symptom) "
            f"WHERE d.name = '{_esc(name)}' "
            "RETURN s.name AS symptom, r.qa_id AS source, r.evidence AS evidence "
            "ORDER BY s.name LIMIT 50"
        )
        return self.execute(cypher)

    def __enter__(self) -> "GraphStore":
        self.connect()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _esc(text: str) -> str:
    """Cypher 字符串字面量转义。"""
    return str(text).replace("\\", "\\\\").replace("'", "\\'")