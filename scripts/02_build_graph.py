# -*- coding: utf-8 -*-
"""步骤 2：实体/关系抽取 -> 知识融合 -> 导出 -> 导入 TuGraph -> Cypher 验证 -> 质量评估。

用法：
    python scripts/02_build_graph.py            # auto：优先真库，连不上用离线模拟库
    python scripts/02_build_graph.py --mock     # 强制离线模拟库
    python scripts/02_build_graph.py --mode rest
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from medkg.config import CLEAN_QA, OUTPUT_DIR, TUGRAPH, ensure_dirs
from medkg.etl.preprocess import load_clean
from medkg.extract import load_dictionary
from medkg.graph import build_graph_data, evaluate, export, load_into_store, spot_check_queries
from medkg.storage import GraphError, open_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建医疗知识图谱并导入 TuGraph")
    parser.add_argument("--mock", action="store_true", help="强制使用离线模拟库")
    parser.add_argument("--mode", default=None, choices=["auto", "rest", "mock"], help="图库连接模式")
    parser.add_argument("--ner", default="synonym", choices=["naive", "longest", "synonym"], help="NER 策略")
    args = parser.parse_args(argv)
    mode = "mock" if args.mock else args.mode

    ensure_dirs()
    print("=" * 62)
    print("步骤 2 / 图谱构建与导入")
    print("=" * 62)

    records = load_clean(CLEAN_QA)
    dictionary = load_dictionary()
    print(f"读取清洗数据 {len(records)} 条，词典 {dictionary.size} 个实体")

    print("\n[1/4] 实体识别 + 关系抽取 + 知识融合 ...")
    graph = build_graph_data(records, dictionary, ner_mode=args.ner)
    print(f"  节点 {len(graph.nodes)} 个，关系 {len(graph.edges)} 条")
    print("  节点分布：" + "，".join(f"{k} {v}" for k, v in sorted(graph.stats["nodes_by_label"].items())))
    print("  关系分布：" + "，".join(f"{k} {v}" for k, v in sorted(graph.stats["edges_by_rel"].items())))
    print(f"  同义合并 {sum(graph.stats['alias_merges'].values())} 次，多来源关系 {graph.stats['multi_source_edges']} 条，待审核 {graph.stats['review_items']} 项")

    print("\n[2/4] 导出 CSV / import.yaml ...")
    paths = export(graph)
    for name in ("nodes", "edges", "import_yaml", "review", "stats"):
        print(f"  {name}: {paths[name]}")

    print("\n[3/4] 写入图库 ...")
    try:
        store, note = open_store(mode=mode)
    except GraphError as exc:
        print(f"  连接失败：{exc}", file=sys.stderr)
        return 2
    if note:
        print(f"  {note}")
    try:
        load_into_store(store, graph)
        print("\n[4/4] 用标准 Cypher 验证入库结果 ...")
        for title, cypher in spot_check_queries():
            try:
                result = store.execute(cypher)
                print(f"\n  · {title}（{result.count} 行，{result.elapsed_ms:.1f} ms）")
                print("    " + cypher)
                for line in result.to_table(max_rows=5).splitlines():
                    print("    " + line)
            except GraphError as exc:
                print(f"  · {title} 执行失败：{exc}")

        report = evaluate(graph, qa_ids=[r.qa_id for r in records])
        print("\n图谱质量评估：")
        for key, value in report["metrics"].items():
            print(f"  {key}: {value}")
        report["backend"] = store.server_info()
        report["graph"] = {"nodes": len(graph.nodes), "edges": len(graph.edges)}
        (OUTPUT_DIR / "graph_quality.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n质量报告已写入 {OUTPUT_DIR / 'graph_quality.json'}")
    finally:
        store.close()

    print("\n完成。下一步：python scripts/03_verify_graph.py 查看检索与问答效果。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())