# -*- coding: utf-8 -*-
"""第 2 步验证：入图后用标准 Cypher 抽查，并核对图库与导出文件是否一致。

检查项：
  1. 规模一致：图库里的节点/关系数与 data/graph/*.csv 相同
  2. 标签/关系分布逐项一致
  3. Schema 合规：标签、关系类型、方向都在 schema.py 里登记过
  4. 抽查查询：6 条标准 Cypher 都能跑通且结果非空
  5. 定点断言：癫痫检查数、冠心病症状数、高血压所属科室等
  6. 质量门禁：读取 02 步产出的 outputs/graph_quality.json，检查关键指标是否达标

用法：
    python scripts/03_verify_graph.py --mock
    python scripts/03_verify_graph.py            # 连真实 TuGraph
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from medkg.config import GRAPH_DIR, LABELS, OUTPUT_DIR, RELATIONS, ensure_dirs  # noqa: E402
from medkg.graph.quality import spot_check_queries  # noqa: E402
from medkg.schema import REL_DEFS  # noqa: E402
from medkg.storage import GraphError, open_store  # noqa: E402

FAILED = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global FAILED
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" —— {detail}" if detail else ""))
    if not ok:
        FAILED += 1
    return ok


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="入图验证与质量门禁")
    parser.add_argument("--mode", choices=["auto", "rest", "mock"], default=None)
    parser.add_argument("--mock", action="store_true", help="等同 --mode mock")
    args = parser.parse_args(argv)
    if args.mock:
        args.mode = "mock"

    ensure_dirs()
    nodes = read_csv(GRAPH_DIR / "nodes.csv")
    edges = read_csv(GRAPH_DIR / "edges.csv")
    store, note = open_store(mode=args.mode, verbose=False)
    store.connect()
    print(f"图库：{store.name}（{note}）\n")

    report: dict = {"store": store.name, "note": note, "checks": []}

    def record(name: str, ok: bool, detail: str = "") -> None:
        report["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
        check(name, ok, detail)

    # ---- 1. 规模 ----
    db_nodes = store.count_nodes()
    db_edges = store.count_edges()
    record("节点总数与导出文件一致", db_nodes == len(nodes), f"图库 {db_nodes} / 文件 {len(nodes)}")
    record("关系总数与导出文件一致", db_edges == len(edges), f"图库 {db_edges} / 文件 {len(edges)}")

    # ---- 2. 分布 ----
    label_file = Counter(row["label"] for row in nodes)
    label_db = {}
    for label in LABELS:
        result = store.execute(f"MATCH (n:{label}) RETURN count(n) AS c")
        label_db[label] = int(result.rows[0][0]) if result.rows else 0
    record(
        "各标签节点数一致",
        all(label_db.get(k, 0) == v for k, v in label_file.items()),
        "、".join(f"{k} {label_db.get(k, 0)}/{v}" for k, v in sorted(label_file.items())),
    )

    rel_file = Counter(row["rel"] for row in edges)
    rel_db = {}
    for rel in RELATIONS:
        result = store.execute(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS c")
        rel_db[rel] = int(result.rows[0][0]) if result.rows else 0
    record(
        "各关系类型边数一致",
        all(rel_db.get(k, 0) == v for k, v in rel_file.items()),
        "、".join(f"{k} {rel_db.get(k, 0)}/{v}" for k, v in sorted(rel_file.items())),
    )

    # ---- 3. Schema 合规 ----
    bad_label = sorted({row["label"] for row in nodes} - set(LABELS))
    bad_rel = sorted({row["rel"] for row in edges} - set(RELATIONS))
    record("节点标签均在 Schema 内", not bad_label, f"越界标签：{bad_label}" if bad_label else "5 类标签全部登记")
    record("关系类型均在 Schema 内", not bad_rel, f"越界关系：{bad_rel}" if bad_rel else "4 类关系全部登记")
    wrong_dir = [
        f"{row['src']}-[{row['rel']}]->{row['dst']}"
        for row in edges
        if row["rel"] in REL_DEFS
        and (row["src_label"] != REL_DEFS[row["rel"]]["from"][0]
             or row["dst_label"] != REL_DEFS[row["rel"]]["to"][0])
    ]
    record("关系方向与头尾标签正确", not wrong_dir, f"{len(wrong_dir)} 条方向错误" if wrong_dir else "全部正确")

    # ---- 4. 抽查查询 ----
    spot_rows: list[dict] = []
    for title, cypher in spot_check_queries():
        try:
            result = store.execute(cypher)
            ok = result.rows and result.rows[0][0] is not None
            detail = f"{result.count} 行"
            preview = result.to_table(max_rows=3).replace("\n", " / ")
        except GraphError as exc:
            ok, detail, preview = False, f"执行失败：{exc}", ""
        spot_rows.append({"title": title, "cypher": cypher, "ok": bool(ok), "detail": detail})
        record(f"抽查：{title}", bool(ok), f"{detail}｜{preview[:90]}")
    report["spot_checks"] = spot_rows

    # ---- 5. 定点断言 ----
    assertions = [
        ("癫痫需要做的检查是 2 项", "MATCH (d:Disease {name: '癫痫'})-[:REQUIRES_EXAM]->(e) RETURN count(e) AS c", 2),
        ("冠心病症状是 2 项", "MATCH (d:Disease {name: '冠心病'})-[:HAS_SYMPTOM]->(s) RETURN count(s) AS c", 2),
        ("高血压所属科室唯一", "MATCH (d:Disease {name: '高血压'})-[:BELONGS_TO]->(dept) RETURN count(dept) AS c", 1),
        ("疾病总数与导出文件一致", "MATCH (d:Disease) RETURN count(d) AS c", label_file.get("Disease", 0)),
    ]
    for name, cypher, expected in assertions:
        try:
            result = store.execute(cypher)
            actual = int(result.rows[0][0])
        except (GraphError, IndexError, TypeError, ValueError) as exc:
            record(name, False, f"执行失败：{exc}")
            continue
        record(name, actual == expected, f"实际 {actual}，期望 {expected}")

    # ---- 6. 质量门禁 ----
    quality_path = OUTPUT_DIR / "graph_quality.json"
    if quality_path.exists():
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        metrics = quality.get("metrics", {})
        gate = [
            ("Schema合规率", metrics.get("Schema合规率"), "100.00%"),
            ("属性完整率", metrics.get("属性完整率"), "100.00%"),
            ("重复三元组", metrics.get("重复三元组"), 0),
            ("最大连通分量占比", metrics.get("最大连通分量占比"), "96.77%"),
        ]
        for name, actual, expected in gate:
            record(f"质量门禁：{name}", actual == expected, f"实际 {actual}，期望 {expected}")
        coverage = metrics.get("问答覆盖率", "0%")
        record("质量门禁：问答覆盖率 ≥ 90%", float(coverage.rstrip("%")) >= 90.0, f"实际 {coverage}")
        report["quality"] = metrics
    else:
        print("[skip] 未找到 outputs/graph_quality.json，请先运行 02_build_graph.py")

    store.close()
    report["failed"] = FAILED
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "verify_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n共 {len(report['checks'])} 项检查，失败 {FAILED} 项")
    print(f"报告已写入 {OUTPUT_DIR / 'verify_report.json'}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())