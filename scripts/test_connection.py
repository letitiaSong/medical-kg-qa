# -*- coding: utf-8 -*-
"""第 1 步：测试 TuGraph Python 客户端（HTTP REST）连接。

对应作业要求"测试 TuGraph Python 客户端连接"。脚本按顺序做三件事，
每一步都把请求和响应打印出来，方便截图：
    1. GET  http://<host>:7070/          取服务版本信息
    2. POST http://<host>:7070/login     用账号密码换 JWT
    3. POST http://<host>:7070/cypher    带 JWT 执行 RETURN 1，验证图查询通道

用法：
    python scripts/test_connection.py
    python scripts/test_connection.py --host 127.0.0.1 --port 7070 --graph medical_course_2026
    python scripts/test_connection.py --strict      # 连不上时返回非 0（默认只提示）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from medkg.config import TUGRAPH  # noqa: E402

try:  # 有 requests 就用 requests，和课件示例脚本一致
    import requests
except ImportError:  # pragma: no cover
    requests = None
    import urllib.error
    import urllib.request

TIMEOUT = 5

# 不同 TuGraph 版本错误字段名不一样：4.x 用 error_message，3.x 用 errorCode/errorMessage
ERROR_MARKERS = ('"error_message"', '"errorMessage"', '"errorCode"', '"error_code"')


def _is_error(text: str) -> bool:
    return any(marker in text for marker in ERROR_MARKERS)


def _get(url: str) -> tuple[bool, str]:
    if requests is not None:
        try:
            resp = requests.get(url, timeout=TIMEOUT)
            return True, resp.text[:500]
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
    try:  # pragma: no cover
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            return True, resp.read().decode("utf-8", "replace")[:500]
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _post(url: str, payload: dict, token: str | None = None) -> tuple[bool, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if requests is not None:
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
            return True, resp.text[:800]
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
    try:  # pragma: no cover
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return True, resp.read().decode("utf-8", "replace")[:800]
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TuGraph REST 连接测试")
    parser.add_argument("--host", default=TUGRAPH.host)
    parser.add_argument("--port", type=int, default=TUGRAPH.port)
    parser.add_argument("--user", default=TUGRAPH.user)
    parser.add_argument("--password", default=TUGRAPH.password)
    parser.add_argument("--graph", default=TUGRAPH.graph)
    parser.add_argument("--strict", action="store_true", help="连接失败时返回非 0")
    args = parser.parse_args(argv)

    base = f"http://{args.host}:{args.port}"
    print("=" * 62)
    print("步骤 1 / TuGraph Python 客户端连接测试")
    print("=" * 62)
    print(f"目标：{base}")
    print(f"账号：{args.user} / {'*' * len(args.password)}")
    print(f"图名：{args.graph}")
    print(f"客户端：{'requests ' + requests.__version__ if requests else 'urllib（标准库）'}")

    print(f"\n[1/3] GET {base}/")
    ok, text = _get(f"{base}/")
    if not ok:
        print(f"  连接失败：{text}")
        print("\n排查清单：")
        print("  1) TuGraph 是否已启动：docker ps | grep tugraph")
        print("  2) 端口是否映射：docker run -p 7070:7070 -p 9090:9090 ... tugraph/tugraph-runtime-centos7")
        print("  3) 防火墙/代理是否拦截 7070")
        print("  4) 只想跑离线演示：python cli.py --mock")
        return 0 if not args.strict else 1
    print(f"  响应：{text}")

    print(f"\n[2/3] POST {base}/login")
    ok, text = _post(f"{base}/login", {"user": args.user, "password": args.password})
    if not ok:
        print(f"  登录请求失败：{text}")
        return 0 if not args.strict else 1
    print(f"  响应：{text}")
    token = ""
    try:
        token = json.loads(text).get("jwt", "")
    except json.JSONDecodeError:
        pass
    if not token:
        print("  未取到 jwt，后续 Cypher 请求会被拒绝，请检查账号密码")
        return 0 if not args.strict else 1
    print(f"  JWT 长度 {len(token)}，前 24 位：{token[:24]}...")

    print(f"\n[3/3] POST {base}/cypher  （RETURN 1）")
    payload = {"script": "RETURN 1 AS ok", "graph": args.graph}
    ok, text = _post(f"{base}/cypher", payload, token=token)
    if ok and _is_error(text):
        print(f"  响应：{text}")
        if "No such graph" in text:
            print(f"  图库里还没有 {args.graph}，先建图：CALL db.createGraph('{args.graph}')")
            _, created = _post(
                f"{base}/cypher",
                {"script": f"CALL db.createGraph('{args.graph}')", "graph": "default"},
                token=token,
            )
            print(f"  建图响应：{created}")
            ok, text = _post(f"{base}/cypher", payload, token=token)
    if not ok:
        print(f"  查询失败：{text}")
        return 0 if not args.strict else 1
    print(f"  响应：{text}")
    if _is_error(text):
        print("  图库返回错误，通常是图名不存在或权限不足")
        return 0 if not args.strict else 1

    print("\n连接测试通过：客户端已能登录 TuGraph 并执行 Cypher。")
    print("下一步：python scripts/init_schema.py   # 建标签")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())