# -*- coding: utf-8 -*-
"""第 1 步：创建图库与 Schema（5 类点、4 类边）。

TuGraph 的 DDL 通过 CALL db.createVertexLabel / db.createEdgeLabel 执行。
脚本是幂等的：标签已存在会报"已存在"，这里按"跳过"处理。

用法：
    python scripts/init_schema.py
    python scripts/init_schema.py --host 127.0.0.1 --port 7070 --graph medical_course_2026
    python scripts/init_schema.py --dry-run     # 只打印 DDL，不连库（写报告时截图用）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from medkg.config import TUGRAPH  # noqa: E402
from medkg.schema import ddl_statements, node_labels, relation_types  # noqa: E402

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

TIMEOUT = 10
ALREADY = ("already exist", "已存在", "exist", "Existed")
# 4.x 的错误字段是 error_message，3.x 是 errorCode/errorMessage，两种都要认
ERROR_MARKERS = ('"error_message"', '"errorMessage"', '"errorCode"')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="创建 TuGraph 图库与 Schema")
    parser.add_argument("--host", default=TUGRAPH.host)
    parser.add_argument("--port", type=int, default=TUGRAPH.port)
    parser.add_argument("--user", default=TUGRAPH.user)
    parser.add_argument("--password", default=TUGRAPH.password)
    parser.add_argument("--graph", default=TUGRAPH.graph)
    parser.add_argument("--dry-run", action="store_true", help="只打印 DDL")
    parser.add_argument("--legacy", action="store_true", help="3.x 写法（不带引号的类型）")
    args = parser.parse_args(argv)

    statements = ddl_statements(legacy_types=args.legacy)
    print("=" * 62)
    print("步骤 1 / 建库与建 Schema")
    print("=" * 62)
    print(f"节点标签：{', '.join(node_labels())}")
    print(f"关系类型：{', '.join(relation_types())}")
    print(f"DDL 共 {len(statements)} 条\n")
    for statement in statements:
        print(f"  {statement}")

    if args.dry_run:
        print("\n--dry-run：仅打印，不连库。")
        return 0

    if requests is None:  # pragma: no cover
        print("\n缺少 requests，无法连接 TuGraph。")
        return 2

    base = f"http://{args.host}:{args.port}"
    try:
        login = requests.post(
            f"{base}/login",
            json={"user": args.user, "password": args.password},
            timeout=TIMEOUT,
        )
        token = login.json().get("jwt", "")
    except Exception as exc:  # noqa: BLE001
        print(f"\n登录失败：{exc}")
        print("请先确认 TuGraph 已启动（python scripts/test_connection.py）")
        return 0
    if not token:
        print(f"\n登录失败：{login.text[:200]}")
        return 0

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    # 建图：4.x 用 dbms.graph.createGraph（必须在 default 图上执行），老版本用 db.createGraph
    print("\n建图：")
    for creator in (
        f"CALL dbms.graph.createGraph('{args.graph}')",
        f"CALL db.createGraph('{args.graph}')",
    ):
        try:
            resp = requests.post(
                f"{base}/cypher",
                headers=headers,
                json={"script": creator, "graph": "default"},
                timeout=TIMEOUT,
            )
            body = resp.text
        except Exception as exc:  # noqa: BLE001
            body = str(exc)
        print(f"  {creator}")
        if any(word in body for word in ALREADY):
            print(f"    已存在，跳过（{body[:80]}）")
            break
        if not any(marker in body for marker in ERROR_MARKERS):
            print(f"    已创建（{body[:80]}）")
            break
        print(f"    不可用：{body[:160]}")

    created = skipped = failed = 0
    print("\n执行 DDL：")
    for statement in statements:
        try:
            resp = requests.post(
                f"{base}/cypher",
                headers=headers,
                json={"script": statement, "graph": args.graph},
                timeout=TIMEOUT,
            )
            body = resp.text
        except Exception as exc:  # noqa: BLE001
            body = str(exc)
        if any(word in body for word in ALREADY):
            skipped += 1
            print(f"  [跳过] {statement[:70]}… 已存在")
        elif any(marker in body for marker in ERROR_MARKERS):
            failed += 1
            print(f"  [失败] {statement[:70]}…")
            print(f"         {body[:300]}")
        else:
            created += 1
            print(f"  [成功] {statement[:70]}…")

    summary = {"graph": args.graph, "created": created, "skipped": skipped, "failed": failed}
    print("\n汇总：" + json.dumps(summary, ensure_ascii=False))
    if failed:
        print("有 DDL 执行失败，可加 --legacy 兼容 TuGraph 3.x 的类型写法。")
    print("\n下一步：python scripts/02_build_graph.py --mode rest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())