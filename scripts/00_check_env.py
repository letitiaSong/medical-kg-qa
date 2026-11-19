# -*- coding: utf-8 -*-
"""第 1 步：环境自检（Python、依赖、配置、数据、图库、模型）。

把结果写成 outputs/env_report.json，报告里可以直接截图这张表。

用法：
    python scripts/00_check_env.py
    python scripts/00_check_env.py --mock      # 不尝试连 TuGraph
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from medkg.config import (  # noqa: E402
    CLEAN_QA,
    DATA_DIR,
    ENTITY_DICT,
    LLM,
    MOCK_STORE,
    OUTPUT_DIR,
    PROJECT_ROOT,
    RAW_QA,
    T2C_TESTSET,
    TUGRAPH,
    ensure_dirs,
)

ROWS: list[dict] = []


def item(name: str, status: str, detail: str) -> None:
    ROWS.append({"item": name, "status": status, "detail": detail})
    mark = {"OK": "✓", "WARN": "!", "FAIL": "×"}.get(status, "?")
    print(f"[{mark}] {name:<22} {detail}")


def check_python() -> None:
    version = platform.python_version()
    ok = sys.version_info >= (3, 9)
    item("Python 版本", "OK" if ok else "FAIL", f"{version}（要求 ≥ 3.9）")


def check_packages() -> None:
    packages = ["requests", "pandas", "fastapi", "uvicorn", "dotenv", "pydantic"]
    missing = []
    for name in packages:
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    if missing:
        item("第三方依赖", "WARN", f"缺少 {', '.join(missing)}；核心流程只用标准库也能跑")
    else:
        item("第三方依赖", "OK", "requests / pandas / fastapi / uvicorn / dotenv 均已安装")


def check_config() -> None:
    item("TuGraph 地址", "OK", f"{TUGRAPH.base_url}（图 {TUGRAPH.graph}，账号 {TUGRAPH.user}）")
    item("TuGraph 密码", "OK", f"{TUGRAPH.user} / {TUGRAPH.masked()['password']}（.env 中配置）")
    if LLM.use_llm:
        item("大模型配置", "OK", f"{LLM.model} @ {LLM.base_url}，Key {LLM.masked()}")
    else:
        item("大模型配置", "WARN", "未配置 DASHSCOPE_API_KEY，将使用离线规则模型（--llm fake）")


def check_data() -> None:
    items = [
        ("原始问答数据", RAW_QA),
        ("清洗后数据", CLEAN_QA),
        ("实体词典", ENTITY_DICT),
        ("Text2Cypher 测例", T2C_TESTSET),
        ("离线图库", MOCK_STORE),
    ]
    for name, path in items:
        rel = path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path
        if path.exists():
            if path.suffix == ".csv":
                lines = max(0, sum(1 for _ in path.open(encoding="utf-8-sig")) - 1)
                detail = f"{rel}（{lines} 行）"
            elif path.suffix == ".json":
                detail = f"{rel}（{path.stat().st_size / 1024:.0f} KB）"
            else:
                detail = str(rel)
            item(name, "OK", detail)
        else:
            hint = "先跑 01_preprocess.py" if "clean" in path.name else "先跑对应脚本生成"
            item(name, "WARN", f"缺失 {rel}，{hint}")


def check_tugraph(mock: bool) -> None:
    if mock:
        item("TuGraph 连接", "WARN", "已指定 --mock，跳过真实连接测试")
        return
    try:
        from medkg.storage import open_store

        store, note = open_store(mode="rest", verbose=False)
        store.connect()
        info = store.server_info()
        item("TuGraph 连接", "OK", f"{store.name}，节点 {store.count_nodes()} / 关系 {store.count_edges()}")
        item("TuGraph 版本", "OK", json.dumps(info, ensure_ascii=False)[:120])
        store.close()
    except Exception as exc:  # noqa: BLE001
        item("TuGraph 连接", "WARN", f"连不上（{type(exc).__name__}）；离线演示可用 --mock。{str(exc)[:80]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="实验环境自检")
    parser.add_argument("--mock", action="store_true", help="跳过 TuGraph 连接测试")
    args = parser.parse_args(argv)
    ensure_dirs()

    print("=" * 62)
    print("步骤 1 / 环境自检")
    print("=" * 62)
    print(f"项目目录：{PROJECT_ROOT}")
    print(f"数据目录：{DATA_DIR}")
    print()

    check_python()
    check_packages()
    check_config()
    check_data()
    check_tugraph(args.mock)

    counts = {s: sum(1 for r in ROWS if r["status"] == s) for s in ("OK", "WARN", "FAIL")}
    print(f"\n合计：正常 {counts['OK']} 项，提醒 {counts['WARN']} 项，失败 {counts['FAIL']} 项")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "project_root": str(PROJECT_ROOT),
        "tugraph": {"url": TUGRAPH.base_url, "graph": TUGRAPH.graph, "password": TUGRAPH.masked()},
        "llm": {"model": LLM.model, "base_url": LLM.base_url, "configured": LLM.use_llm,
                "mode": LLM.mode},
        "items": ROWS,
        "summary": counts,
    }
    path = OUTPUT_DIR / "env_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"自检报告已写入 {path}")
    print("\n下一步：python scripts/test_connection.py    # 测试 TuGraph 客户端连接")
    return 0 if counts["FAIL"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())