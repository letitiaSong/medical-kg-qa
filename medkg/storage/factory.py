# -*- coding: utf-8 -*-
"""按配置选择后端：真实 TuGraph REST 或离线模拟库。"""
from __future__ import annotations

import sys
from typing import Optional

from ..config import MOCK_STORE, TUGRAPH, TuGraphConfig
from .base import GraphError, GraphStore
from .mock_store import MockStore
from .tugraph_rest import TuGraphRESTStore


def open_store(
    mode: Optional[str] = None,
    graph: Optional[str] = None,
    cfg: Optional[TuGraphConfig] = None,
    verbose: bool = True,
) -> tuple[GraphStore, str]:
    """打开图库连接，返回 (store, 说明文字)。

    mode=auto 时先尝试真实 TuGraph，连不上自动降级到离线模拟库并打印提示，
    保证任何电脑上都能跑通脚本。
    """
    cfg = cfg or TUGRAPH
    mode = (mode or cfg.mode or "auto").lower()
    graph = graph or cfg.graph

    if mode in {"rest", "real", "tugraph"}:
        store = TuGraphRESTStore(
            host=cfg.host,
            port=cfg.port,
            user=cfg.user,
            password=cfg.password,
            graph=graph,
            timeout=cfg.timeout,
        )
        store.connect()
        if not store.ping():
            raise GraphError(f"TuGraph 连接失败：{cfg.base_url}")
        note = f"已连接 TuGraph REST：{cfg.base_url} / graph={graph}"
        if verbose:
            print(note)
        return store, note

    if mode == "mock":
        store = MockStore(MOCK_STORE, graph=graph)
        store.connect()
        note = f"使用离线模拟库：{MOCK_STORE} / graph={graph}"
        if verbose:
            print(note)
        return store, note

    # auto
    rest = TuGraphRESTStore(
        host=cfg.host,
        port=cfg.port,
        user=cfg.user,
        password=cfg.password,
        graph=graph,
        timeout=5,
    )
    try:
        rest.connect()
        if rest.ping():
            note = f"已连接 TuGraph REST：{cfg.base_url} / graph={graph}"
            if verbose:
                print(note)
            return rest, note
        raise GraphError("ping 失败")
    except Exception as exc:  # noqa: BLE001 - 任何异常都降级
        note = (
            f"未能连接 TuGraph（{cfg.base_url}，{exc.__class__.__name__}），"
            f"已自动切换到离线模拟库：{MOCK_STORE}"
        )
        print(note, file=sys.stderr)
        store = MockStore(MOCK_STORE, graph=graph)
        store.connect()
        return store, note