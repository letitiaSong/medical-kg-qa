# -*- coding: utf-8 -*-
"""只读 Cypher 子集解释器（离线模拟库的执行引擎）。

支持范围（够覆盖本作业的 Text2Cypher 测例与验证脚本）：
    MATCH (n) / (n:Disease) / (n {name: 'x'}) / (d:Disease)-[:HAS_SYMPTOM]->(s:Symptom)
    MATCH 多跳链： (a)-[:R1]->(b)<-[:R2]-(c)
    关系可省略类型： -[r]-> / <-[r]- ；可带属性过滤 {qa_id: 'Q001'}
    WHERE：= <> != > >= < <= CONTAINS STARTS WITH ENDS WITH IN IS [NOT] NULL，AND / OR / NOT
    RETURN：var.prop、var、count(var)、count(*)、count(DISTINCT var)、type(r)，支持 AS 别名
    RETURN DISTINCT / ORDER BY x [ASC|DESC] / LIMIT n
写操作（CREATE/MERGE/SET/DELETE/CALL 等）一律拒绝——这正是"离线库"和"真库"的边界。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .base import QueryResult


class CyperSubsetError(RuntimeError):
    """离线库不支持的 Cypher 写法。"""


WRITE_KEYWORDS = ("CREATE", "MERGE", "DELETE", "SET ", "REMOVE", "CALL", "DROP", "LOAD CSV")

NODE_RE = re.compile(r"\(([^()]*)\)")
NODE_BODY_RE = re.compile(
    r"^\s*(?:(\w+))?\s*(?::\s*(\w+))?\s*(?:\{([^{}]*)\})?\s*$"
)
REL_BODY_RE = re.compile(
    r"^\s*(?:(?:(\w+))?\s*:?\s*([\w|:]+))?\s*(?:\{([^{}]*)\})?\s*(?:\*\s*(\d+)?\s*(?:\.\.\s*(\d+))?)?\s*$"
)
RET_ITEM_RE = re.compile(
    r"^(?:(count)\s*\(\s*(distinct\s+)?(.+?)\)|(.+?))(?:\s+as\s+(\w+))?$", re.IGNORECASE
)
COND_RE = re.compile(
    r"^\s*(?:NOT\s+)?\(?\s*(?P<var>\w+)\.(?P<prop>\w+)\s*"
    r"(?P<op><>|!=|>=|<=|=|>|<|CONTAINS|STARTS WITH|ENDS WITH|IN|IS NOT NULL|IS NULL)\s*"
    r"(?P<value>.*?)\s*\)?\s*$",
    re.IGNORECASE,
)


@dataclass
class NodeSpec:
    var: str
    label: Optional[str] = None
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class RelSpec:
    var: Optional[str] = None
    types: list[str] = field(default_factory=list)
    incoming: bool = False
    props: dict[str, Any] = field(default_factory=dict)
    min_hops: int = 1
    max_hops: int = 1


@dataclass
class Cond:
    var: str
    prop: str
    op: str
    value: Any = None


@dataclass
class RetItem:
    kind: str  # prop / var / count / count_distinct / type
    var: str = ""
    prop: str = ""
    alias: str = ""


@dataclass
class ParsedQuery:
    nodes: list[NodeSpec] = field(default_factory=list)
    rels: list[RelSpec] = field(default_factory=list)
    where: list[list[Cond]] = field(default_factory=list)  # 外层 OR，内层 AND
    returns: list[RetItem] = field(default_factory=list)
    distinct: bool = False
    order_by: Optional[str] = None
    order_desc: bool = False
    limit: Optional[int] = None

    # 兼容旧字段名
    @property
    def first(self) -> Optional[NodeSpec]:
        return self.nodes[0] if self.nodes else None

    @property
    def hops(self) -> list[RelSpec]:
        return self.rels


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def parse(cypher: str) -> ParsedQuery:
    text = " ".join(cypher.split())
    if not text:
        raise CyperSubsetError("空语句")
    upper = text.upper()
    for kw in WRITE_KEYWORDS:
        if re.search(rf"(^|\s){re.escape(kw)}", upper):
            raise CyperSubsetError(f"离线模拟库只支持只读查询，拒绝执行：{kw.strip()}")
    if "OPTIONAL MATCH" in upper:
        raise CyperSubsetError("离线模拟库不支持 OPTIONAL MATCH，请改用 MATCH")
    if "UNION" in upper:
        raise CyperSubsetError("离线模拟库不支持 UNION")
    if "MERGE" in upper:
        raise CyperSubsetError("离线模拟库不支持 MERGE")

    match_start = upper.find("MATCH")
    if match_start < 0:
        raise CyperSubsetError("语句里没有 MATCH 子句")
    rest = text[match_start + len("MATCH") :]

    ret_idx = _find_keyword(rest.upper(), "RETURN")
    if ret_idx < 0:
        raise CyperSubsetError("语句里没有 RETURN 子句")
    pattern_part = rest[:ret_idx]
    tail = rest[ret_idx + len("RETURN") :]

    where_idx = _find_keyword(pattern_part.upper(), "WHERE")
    if where_idx >= 0:
        where_part = pattern_part[where_idx + len("WHERE") :]
        pattern_part = pattern_part[:where_idx]
    else:
        where_part = ""

    parsed = ParsedQuery()
    _parse_pattern(pattern_part.strip(), parsed)
    if where_part.strip():
        parsed.where = _parse_where(where_part)

    # RETURN 之后：先切掉 ORDER BY / LIMIT
    order_idx = _find_keyword(tail.upper(), "ORDER BY")
    limit_idx = _find_keyword(tail.upper(), "LIMIT")
    cut = len(tail)
    if order_idx >= 0:
        cut = min(cut, order_idx)
    if limit_idx >= 0:
        cut = min(cut, limit_idx)
    return_part = tail[:cut].strip()
    if return_part.upper().startswith("DISTINCT"):
        parsed.distinct = True
        return_part = return_part[len("DISTINCT") :].strip()

    if order_idx >= 0:
        order_text = tail[order_idx + len("ORDER BY") :]
        if limit_idx >= 0:
            order_text = tail[order_idx + len("ORDER BY") : limit_idx]
        order_text = order_text.strip()
        if order_text.upper().endswith("DESC"):
            parsed.order_desc = True
            order_text = order_text[:-4].strip()
        elif order_text.upper().endswith("ASC"):
            order_text = order_text[:-3].strip()
        parsed.order_by = order_text
    if limit_idx >= 0:
        limit_text = tail[limit_idx + len("LIMIT") :].strip()
        num = re.match(r"(\d+)", limit_text)
        if not num:
            raise CyperSubsetError(f"LIMIT 需要整数：{limit_text}")
        parsed.limit = int(num.group(1))

    if not return_part:
        raise CyperSubsetError("RETURN 子句为空")
    parsed.returns = [_parse_ret_item(item) for item in _split_top(return_part, ",")]
    return parsed


def _find_keyword(text: str, keyword: str) -> int:
    idx = 0
    while True:
        idx = text.find(keyword, idx)
        if idx < 0:
            return -1
        if idx == 0 or text[idx - 1] in " )}\n\t":
            return idx
        idx += len(keyword)


def _parse_pattern(text: str, parsed: ParsedQuery) -> None:
    text = text.strip()
    if not text:
        raise CyperSubsetError("MATCH 后面缺少模式")
    if text.startswith("p=") or re.match(r"^\w+\s*=", text):
        raise CyperSubsetError("离线模拟库不支持给路径起变量名（如 p=...）")
    matches = list(NODE_RE.finditer(text))
    if not matches:
        raise CyperSubsetError("MATCH 里没有节点模式 (…)")
    for i, m in enumerate(matches):
        spec = _parse_node(m.group(1))
        if spec.var == "__anon":
            spec.var = f"__anon{i}"
        parsed.nodes.append(spec)
        if i == 0:
            continue
        between = text[matches[i - 1].end() : m.start()]
        parsed.rels.append(_parse_rel(between))
    if len(parsed.nodes) < 2:
        parsed.rels = []


def _parse_node(body: str) -> NodeSpec:
    m = NODE_BODY_RE.match(body)
    if not m:
        raise CyperSubsetError(f"无法解析节点模式：({body})")
    var, label, props_text = m.groups()
    if not var and not label:
        var = "__anon"
    return NodeSpec(var=var or "__anon", label=label, props=_parse_props(props_text or ""))


def _parse_rel(segment: str) -> RelSpec:
    seg = segment.strip()
    if not seg:
        raise CyperSubsetError("两个节点之间缺少关系")
    incoming = seg.startswith("<")
    body_match = re.search(r"\[([^\]]*)\]", seg)
    spec = RelSpec(incoming=incoming)
    if not body_match:
        if "-" not in seg:
            raise CyperSubsetError(f"无法解析关系：{seg}")
        return spec

    body = body_match.group(1).strip()
    # 先摘出属性 {…} 和变长 *1..2
    props_text = ""
    m_props = re.search(r"\{([^{}]*)\}", body)
    if m_props:
        props_text = m_props.group(1)
        body = (body[: m_props.start()] + body[m_props.end() :]).strip()
    hops = ""
    if "*" in body:
        body, _, hops = body.partition("*")
        body = body.strip()
        hops = hops.strip()
    spec.props = _parse_props(props_text)

    # 剩下的形如 r / :TYPE / r:TYPE / TYPE  （无冒号时按变量名处理）
    if body.startswith(":"):
        spec.types = [t.strip() for t in body[1:].split("|") if t.strip()]
    elif ":" in body:
        var, _, types = body.partition(":")
        spec.var = var.strip() or None
        spec.types = [t.strip() for t in types.split("|") if t.strip()]
    elif body:
        if body.upper() in {"", }:
            spec.var = None
        else:
            spec.var = body

    if hops:
        if ".." in hops:
            low, _, high = hops.partition("..")
            spec.min_hops = int(low) if low.strip() else 1
            spec.max_hops = int(high) if high.strip() else 3
        else:
            spec.min_hops = spec.max_hops = int(hops or 1)
        if spec.max_hops > 3:
            raise CyperSubsetError("离线模拟库最多支持 3 跳")
    return spec


def _parse_props(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    out: dict[str, Any] = {}
    for part in _split_top(text, ","):
        key, _, value = part.partition(":")
        if not key.strip():
            continue
        out[key.strip()] = _literal(value.strip())
    return out


def _literal(text: str) -> Any:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1].replace("\\'", "'").replace('\\"', '"')
    low = text.lower()
    if low in {"true", "false"}:
        return low == "true"
    if low == "null":
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _split_top(text: str, sep: str) -> list[str]:
    """按分隔符切分，忽略括号/引号内部的分隔符。"""
    parts: list[str] = []
    depth = 0
    quote: Optional[str] = None
    current: list[str] = []
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
            current.append(ch)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    if current:
        parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _parse_where(text: str) -> list[list[Cond]]:
    groups: list[list[Cond]] = []
    for or_part in _split_keyword_top(text, "OR"):
        conds: list[Cond] = []
        negate = False
        for and_part in _split_keyword_top(or_part, "AND"):
            item = and_part.strip()
            while item.startswith("(") and item.endswith(")"):
                item = item[1:-1].strip()
            if item.upper().startswith("NOT "):
                negate = True
                item = item[4:].strip()
            m = COND_RE.match(item)
            if not m:
                raise CyperSubsetError(f"离线模拟库不支持的 WHERE 条件：{item}")
            op = m.group("op").upper()
            raw = m.group("value").strip()
            value: Any = None
            if op == "IN":
                value = [_literal(v) for v in _split_top(raw.strip("[]"), ",")]
            elif op in {"IS NULL", "IS NOT NULL"}:
                value = None
            elif raw.upper().startswith("NOT "):
                op = "NOT CONTAINS"
                value = _literal(raw[4:].strip())
            else:
                value = _literal(raw)
            conds.append(Cond(var=m.group("var"), prop=m.group("prop"), op=op, value=value))
        if negate and conds:
            conds[0] = Cond(conds[0].var, conds[0].prop, "NOT " + conds[0].op, conds[0].value)
        groups.append(conds)
    return groups


def _split_keyword_top(text: str, keyword: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    quote: Optional[str] = None
    current: list[str] = []
    kw = " " + keyword + " "
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            current.append(ch)
            i += 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if depth == 0 and text[i : i + len(kw)].upper() == kw:
            parts.append("".join(current))
            current = []
            i += len(kw)
            continue
        current.append(ch)
        i += 1
    if current:
        parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _parse_ret_item(text: str) -> RetItem:
    item = text.strip()
    alias = ""
    m_alias = re.search(r"\s+AS\s+(\w+)$", item, re.IGNORECASE)
    if m_alias:
        alias = m_alias.group(1)
        item = item[: m_alias.start()].strip()

    if item == "*":
        return RetItem(kind="star", alias=alias or "*")

    m = re.match(r"^count\s*\(\s*(distinct\s+)?(.+?)\s*\)$", item, re.IGNORECASE)
    if m:
        distinct = bool(m.group(1))
        arg = m.group(2).strip()
        if arg == "*":
            return RetItem(kind="count", alias=alias or "count")
        kind = "count_distinct" if distinct else "count"
        if "." in arg:
            var, _, prop = arg.partition(".")
            return RetItem(kind=kind, var=var.strip(), prop=prop.strip(), alias=alias or f"count({arg})")
        return RetItem(kind=kind, var=arg, alias=alias or f"count({arg})")

    m = re.match(r"^type\s*\(\s*(\w+)\s*\)$", item, re.IGNORECASE)
    if m:
        name = m.group(1)
        return RetItem(kind="type", var=name, alias=alias or f"type({name})")

    if "." in item:
        var, _, prop = item.partition(".")
        var, prop = var.strip(), prop.strip()
        if not var.isidentifier() or not prop.isidentifier():
            raise CyperSubsetError(f"无法解析 RETURN 项：{item}")
        return RetItem(kind="prop", var=var, prop=prop, alias=alias or prop)

    if item.isidentifier():
        return RetItem(kind="var", var=item, alias=alias or item)
    raise CyperSubsetError(f"无法解析 RETURN 项：{item}")


# --------------------------------------------------------------------------- #
# 求值
# --------------------------------------------------------------------------- #
def evaluate(
    parsed: ParsedQuery, nodes: list[dict], edges: list[dict], cypher: str = ""
) -> QueryResult:
    node_index = {n["id"]: n for n in nodes}
    edge_list = list(edges)

    # 1) 第一个节点
    first = parsed.nodes[0]
    bindings: list[dict[str, dict]] = []
    for node in nodes:
        if _match_node(first, node):
            bindings.append({first.var: node})
    if not parsed.rels:
        # 单节点：后面若还有孤立节点模式（MATCH (a),(b)）不支持，直接按第一个算
        pass

    # 2) 逐跳扩展
    for hop_index, rel in enumerate(parsed.rels):
        next_spec = parsed.nodes[hop_index + 1]
        prev_var = parsed.nodes[hop_index].var
        expanded: list[dict[str, dict]] = []
        for binding in bindings:
            src = binding[prev_var]
            for target, edge in _neighbours(src, rel, edge_list, node_index):
                if not _match_node(next_spec, target):
                    continue
                if next_spec.var in binding:
                    if binding[next_spec.var]["id"] != target["id"]:
                        continue
                    new_binding = dict(binding)
                else:
                    new_binding = dict(binding)
                    new_binding[next_spec.var] = target
                if rel.var:
                    new_binding[rel.var] = edge
                expanded.append(new_binding)
        bindings = expanded
        if not bindings:
            break

    # 3) WHERE 过滤
    if parsed.where:
        bindings = [b for b in bindings if _match_where(b, parsed.where)]

    # 4) RETURN 投影 + 聚合
    return _project(parsed, bindings, cypher)


def _neighbours(
    src: dict, rel: RelSpec, edges: list[dict], node_index: dict[str, dict]
) -> list[tuple[dict, dict]]:
    out: list[tuple[dict, dict]] = []
    if rel.max_hops > 1:
        return _reach(src, rel, edges, node_index)
    for edge in edges:
        if rel.types and edge["rel"] not in rel.types:
            continue
        if rel.props:
            if not all(_eq(edge.get("props", {}).get(k), v) for k, v in rel.props.items()):
                continue
        if rel.incoming:
            if edge["dst"] != src["id"]:
                continue
            target = node_index.get(edge["src"])
        else:
            if edge["src"] != src["id"]:
                continue
            target = node_index.get(edge["dst"])
        if target is not None:
            out.append((target, edge))
    return out


def _reach(
    src: dict, rel: RelSpec, edges: list[dict], node_index: dict[str, dict]
) -> list[tuple[dict, dict]]:
    """变长关系 *1..n。"""
    results: list[tuple[dict, dict]] = []
    frontier: list[tuple[dict, int]] = [(src, 0)]
    visited = {src["id"]}
    while frontier:
        current, depth = frontier.pop(0)
        if depth >= rel.max_hops:
            continue
        for edge in edges:
            if rel.types and edge["rel"] not in rel.types:
                continue
            if rel.incoming:
                if edge["dst"] != current["id"]:
                    continue
                nxt = node_index.get(edge["src"])
            else:
                if edge["src"] != current["id"]:
                    continue
                nxt = node_index.get(edge["dst"])
            if nxt is None or nxt["id"] in visited:
                continue
            visited.add(nxt["id"])
            results.append((nxt, edge))
            frontier.append((nxt, depth + 1))
    return results


def _match_node(spec: NodeSpec, node: dict) -> bool:
    if spec.label and node["label"] != spec.label:
        return False
    props = node.get("props", {})
    for key, value in spec.props.items():
        if not _eq(props.get(key), value):
            return False
    return True


def _match_where(binding: dict[str, dict], groups: list[list[Cond]]) -> bool:
    for group in groups:
        if all(_eval_cond(binding, cond) for cond in group):
            return True
    return False


def _eval_cond(binding: dict[str, dict], cond: Cond) -> bool:
    entity = binding.get(cond.var)
    if entity is None:
        return False
    if cond.var in binding and "type" in entity.get("props", {}) and cond.prop == "type":
        actual = entity["props"].get("type")
    else:
        actual = entity.get("props", {}).get(cond.prop)
        if actual is None and cond.prop == "type" and "rel" in entity:
            actual = entity["rel"]
    op = cond.op
    negated = op.startswith("NOT ")
    if negated and op != "NOT CONTAINS":
        op = op[4:]
    expected = cond.value

    if op in {"IS NULL", "IS NOT NULL"}:
        result = actual is None if op == "IS NULL" else actual is not None
    elif op == "IN":
        result = any(_eq(actual, v) for v in (expected or []))
    elif op == "CONTAINS":
        result = expected is not None and str(actual).lower().find(str(expected).lower()) >= 0
    elif op == "STARTS WITH":
        result = str(actual).startswith(str(expected))
    elif op == "ENDS WITH":
        result = str(actual).endswith(str(expected))
    elif op in {"=", "<>", "!="}:
        equal = _eq(actual, expected)
        result = equal if op == "=" else not equal
    elif op in {">", ">=", "<", "<="}:
        result = _compare(actual, expected, op)
    else:
        raise CyperSubsetError(f"不支持的运算符：{op}")
    if negated:
        result = not result
    return result


def _compare(actual: Any, expected: Any, op: str) -> bool:
    a, b = _to_number(actual), _to_number(expected)
    if a is None or b is None:
        a, b = str(actual), str(expected)
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b
    if op == "<":
        return a < b
    return a <= b


def _to_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _eq(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    if isinstance(left, (int, float)) or isinstance(right, (int, float)):
        num_l, num_r = _to_number(left), _to_number(right)
        if num_l is not None and num_r is not None:
            return num_l == num_r
    return str(left) == str(right)


def _value_of(binding: dict[str, dict], item: RetItem) -> Any:
    entity = binding.get(item.var)
    if entity is None:
        return None
    if item.kind == "var":
        props = entity.get("props", {})
        return props.get("name") or props.get("id") or entity.get("id")
    if item.kind == "prop":
        return entity.get("props", {}).get(item.prop)
    if item.kind == "type":
        if "rel" in entity:
            return entity["rel"]
        return entity.get("label")
    return None


def _project(parsed: ParsedQuery, bindings: list[dict], cypher: str) -> QueryResult:
    items = parsed.returns
    has_agg = any(item.kind in {"count", "count_distinct"} for item in items)
    plain = [item for item in items if item.kind not in {"count", "count_distinct"}]
    aggs = [item for item in items if item.kind in {"count", "count_distinct"}]

    if any(item.kind == "star" for item in items):
        keys: list[str] = []
        for binding in bindings:
            for var in binding:
                if var not in keys:
                    keys.append(var)
        items = [RetItem(kind="var", var=var, alias=var) for var in keys] or items
        plain = items
        aggs = []

    columns = [item.alias or item.prop or item.var for item in items]

    if not has_agg:
        rows = []
        for binding in bindings:
            rows.append([_value_of(binding, item) for item in plain])
        if parsed.distinct:
            seen: set[tuple] = set()
            unique = []
            for row in rows:
                key = tuple(_hashable(v) for v in row)
                if key in seen:
                    continue
                seen.add(key)
                unique.append(row)
            rows = unique
    else:
        groups: dict[tuple, list[dict]] = {}
        order_keys: list[tuple] = []
        for binding in bindings:
            key = tuple(_value_of(binding, item) for item in plain)
            hkey = tuple(_hashable(v) for v in key)
            if hkey not in groups:
                groups[hkey] = []
                order_keys.append(hkey)
            groups[hkey].append(binding)
        if not plain:
            groups = {(): bindings}
            order_keys = [()]

        cursor = 0
        agg_columns = [item.alias or "count" for item in aggs]
        columns = [item.alias or item.prop or item.var for item in plain] + agg_columns
        rows = []
        for hkey in order_keys:
            group = groups[hkey]
            key_values = list(hkey)
            row = list(key_values)
            for item in aggs:
                if item.kind == "count_distinct":
                    values = {_hashable(_value_of(b, item)) for b in group}
                    values.discard("__none__")
                    row.append(len(values))
                else:
                    if item.var == "*" or not item.var:
                        row.append(len(group))
                    else:
                        row.append(sum(1 for b in group if item.var in b))
            rows.append(row)
            cursor += 1

    # ORDER BY
    if parsed.order_by:
        key = parsed.order_by.strip()
        index = None
        for i, col in enumerate(columns):
            if col == key:
                index = i
                break
        if index is None and "." in key:
            var, _, prop = key.partition(".")
            for i, item in enumerate(plain):
                if item.var == var and item.prop == prop:
                    index = i
                    break
        if index is not None:
            rows.sort(key=lambda r: (r[index] is None, _sort_key(r[index])), reverse=parsed.order_desc)

    if parsed.limit is not None:
        rows = rows[: parsed.limit]

    return QueryResult(columns=columns, rows=rows, cypher=cypher)


def _hashable(value: Any) -> Any:
    if value is None:
        return "__none__"
    if isinstance(value, (int, float)):
        return float(value)
    return str(value)


def _sort_key(value: Any) -> Any:
    if isinstance(value, (int, float)):
        return (0, float(value))
    return (1, str(value))