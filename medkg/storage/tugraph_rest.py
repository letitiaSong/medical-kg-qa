# -*- coding: utf-8 -*-
"""TuGraph REST（HTTP）后端。

对应 PPT 第 4 页的三种本地连接方式：
  1. Bolt 客户端      （需要 tugraph-python，见 docs/连接说明.md）
  2. REST 的 GET/POST （本模块实现，参考官方 9.restful-api-legacy.md）
  3. python-client    （官方 lgraph 客户端）

TuGraph 的 HTTP 接口约定：
  POST http://{host}:7070/cypher
  body: {"script": "<cypher>", "graph": "<图名>"}
  成功: {"header": [...], "result": [[...], ...], "size": n}
  失败: {"errorCode": "...", "errorMessage": "..."}
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any, Optional

import requests

from ..schema import ddl_statements
from .base import GraphError, GraphStore, QueryResult


class TuGraphRESTStore(GraphStore):
    name = "tugraph-rest"

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        graph: str,
        timeout: int = 15,
    ) -> None:
        self.base_url = f"http://{host}:{port}"
        self.user = user
        self.password = password
        self.graph = graph
        self.timeout = timeout
        self.session = requests.Session()
        self._jwt: Optional[str] = None
        self._headers: dict[str, str] = {}
        self.log: list[str] = []

    # ---------------- 连接 ----------------
    def connect(self) -> None:
        self.session.headers.update({"Content-Type": "application/json"})
        self._login()
        self.ensure_graph()

    def _login(self) -> None:
        """优先走 /login 拿 JWT；失败则退回 HTTP Basic。"""
        try:
            resp = self.session.post(
                f"{self.base_url}/login",
                json={"user": self.user, "password": self.password},
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                data = _safe_json(resp)
                token = data.get("jwt") or data.get("token")
                if token:
                    self._jwt = token
                    self._headers = {"Authorization": f"Bearer {token}"}
                    return
        except (requests.RequestException, GraphError):
            pass
        token = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        self._headers = {"Authorization": f"Basic {token}"}

    def ensure_graph(self) -> None:
        """图不存在时尝试创建；创建不了就给出可操作的提示，而不是抛一堆堆栈。"""
        try:
            self.execute("MATCH (n) RETURN count(n) AS c")
            return
        except GraphError as exc:
            first_error = str(exc)
        # 连不上服务端时不要再尝试建图，直接抛原始错误（否则会误导成"图不存在"）
        if first_error.startswith("无法连接") or first_error.startswith("TuGraph HTTP"):
            raise GraphError(first_error)
        # 4.x 是 dbms.graph.createGraph，老版本是 db.createGraph；建图要在 default 图上执行
        for stmt in (
            f"CALL dbms.graph.createGraph('{self.graph}')",
            f"CALL db.createGraph('{self.graph}')",
        ):
            try:
                self.execute(stmt, graph="default")
            except GraphError:
                continue
            try:
                self.execute("MATCH (n) RETURN count(n) AS c")
                return
            except GraphError:
                continue
        raise GraphError(
            f"TuGraph 已连通，但图 '{self.graph}' 不可用。"
            f"请在 Web 控制台（{self.base_url}）新建同名图，或修改 .env 里的 TUGRAPH_GRAPH。"
            f"原始错误：{first_error}"
        )

    def list_graphs(self) -> list[str]:
        res = self.execute("CALL dbms.graph.listGraphs()", graph="default")
        return [str(row[0]) for row in res.rows]

    def ping(self) -> bool:
        try:
            res = self.execute("MATCH (n) RETURN count(n) AS c")
            return res.count >= 0
        except GraphError:
            return False

    def server_info(self) -> dict:
        info = {
            "backend": self.name,
            "base_url": self.base_url,
            "graph": self.graph,
            "user": self.user,
            "auth": "jwt" if self._jwt else "basic",
        }
        try:
            resp = self.session.get(f"{self.base_url}/", timeout=self.timeout)
            info["root_status"] = resp.status_code
        except requests.RequestException as exc:
            info["root_status"] = f"unreachable: {exc.__class__.__name__}"
        return info

    # ---------------- 执行 ----------------
    def execute(self, cypher: str, graph: Optional[str] = None) -> QueryResult:
        started = time.perf_counter()
        payload = {"script": cypher, "graph": graph or self.graph}
        try:
            resp = self.session.post(
                f"{self.base_url}/cypher",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers=self._headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise GraphError(f"无法连接 TuGraph（{self.base_url}）：{exc}") from exc

        if resp.status_code != 200:
            raise GraphError(f"TuGraph HTTP {resp.status_code}: {resp.text[:300]}")
        data = _safe_json(resp)
        message = _error_message(data)
        if message:
            raise GraphError(f"TuGraph 执行失败：{message}")

        header = data.get("header") or []
        rows = data.get("result") or []
        elapsed = (time.perf_counter() - started) * 1000
        self.log.append(f"[{elapsed:.1f}ms] {cypher[:120]}")
        return QueryResult(
            columns=[_header_name(col) for col in header],
            rows=[list(r) for r in rows],
            elapsed_ms=elapsed,
            cypher=cypher,
        )

    def run_script(self, scripts: list[str]) -> list[str]:
        """批量执行（DDL / 数据导入用），失败即抛错。"""
        done: list[str] = []
        for stmt in scripts:
            self.execute(stmt)
            done.append(stmt)
        return done

    # ---------------- Schema ----------------
    def ensure_schema(self, force: bool = False) -> list[str]:
        """TuGraph 的 Schema 需要显式声明。

        4.x 的属性类型要写成带引号的 'STRING'、3.x 则是 STRING，
        这里先按 4.x 建，遇到类型/语法报错再退回 3.x 写法；
        "already exists" 视为成功（建图脚本可重复执行）。
        """
        done, errors = self._run_ddl(ddl_statements(legacy_types=False))
        if errors and all(_looks_like_type_error(msg) for _, msg in errors):
            self.log.append(f"[warn] 4.x 写法失败，改用 3.x 写法：{errors[0][1]}")
            done, errors = self._run_ddl(ddl_statements(legacy_types=True))
        if errors:
            raise GraphError(errors[0][1])
        self.log.extend(done)
        return done

    def _run_ddl(self, scripts: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
        done: list[str] = []
        errors: list[tuple[str, str]] = []
        for stmt in scripts:
            try:
                self.execute(stmt)
                done.append(stmt)
            except GraphError as exc:
                if "already exist" in str(exc).lower():
                    done.append(stmt + "  # 已存在，跳过")
                else:
                    errors.append((stmt, str(exc)))
        return done, errors

    def clear_all(self) -> None:
        self.execute("MATCH (n) DETACH DELETE n")

    # ---------------- 写入 ----------------
    def add_node(self, label: str, props: dict[str, Any]) -> None:
        body = ", ".join(f"{k}: {_lit(v)}" for k, v in props.items())
        self.execute(f"CREATE (n:{label} {{{body}}})")

    def add_edge(
        self,
        rel: str,
        src_id: str,
        dst_id: str,
        props: Optional[dict[str, Any]] = None,
        src_label: Optional[str] = None,
        dst_label: Optional[str] = None,
    ) -> None:
        props = props or {}
        body = ", ".join(f"{k}: {_lit(v)}" for k, v in props.items())
        a = f"a:{src_label}" if src_label else "a"
        b = f"b:{dst_label}" if dst_label else "b"
        cypher = (
            f"MATCH ({a}),({b}) WHERE a.id = {_lit(src_id)} AND b.id = {_lit(dst_id)} "
            f"CREATE (a)-[:{rel} {{{body}}}]->(b)"
        )
        self.execute(cypher)

    # ---------------- 统计 ----------------
    def count_nodes(self, label: Optional[str] = None) -> int:
        pattern = f"(n:{label})" if label else "(n)"
        res = self.execute(f"MATCH {pattern} RETURN count(n) AS c")
        return int(res.rows[0][0]) if res.rows else 0

    def count_edges(self, rel: Optional[str] = None) -> int:
        pattern = f"()-[r:{rel}]->()" if rel else "()-[r]->()"
        res = self.execute(f"MATCH {pattern} RETURN count(r) AS c")
        return int(res.rows[0][0]) if res.rows else 0


def _looks_like_type_error(message: str) -> bool:
    """区分"版本写法不对"和"权限/其它错误"，只有前者才退回 3.x 写法。"""
    text = message.lower()
    return any(word in text for word in ("syntax", "type", "unexpected", "parse", "invalid"))


def _error_message(data: Any) -> str:
    """把不同版本的错误字段统一成一句话；没有错误返回空串。

    4.x：{"error_message": "..."}；3.x：{"errorCode": ..., "errorMessage": ...}
    """
    if not isinstance(data, dict):
        return ""
    for key in ("error_message", "errorMessage"):
        if data.get(key):
            return str(data[key])
    if data.get("errorCode"):
        return f"{data['errorCode']}"
    return ""


def _header_name(column: Any) -> str:
    """4.x 的 header 是 [{"name": "ok", "type": 0}]，3.x 是 ["ok"]。"""
    if isinstance(column, dict):
        return str(column.get("name", ""))
    return str(column)


def _safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except ValueError as exc:
        raise GraphError(f"TuGraph 返回内容不是 JSON：{resp.text[:200]}") from exc


def _lit(value: Any) -> str:
    """把 Python 值写成 Cypher 字面量：数字不加引号，其余按字符串转义。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"