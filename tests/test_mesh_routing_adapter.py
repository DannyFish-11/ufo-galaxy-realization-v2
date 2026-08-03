#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_mesh_routing_adapter.py
======================================
阶段 2（AODV 多跳 mesh 适配器）的回归钉。

判据是外部可观察结果：三个**真实监听 localhost 的节点** A–B–C，强制邻接
（A 只认识 B，B 认识 A/C，C 只认识 B —— A 摸不到 C），A 发给 C 的消息必须
经 B 真实中继送达（C 的 handler 收到、回执带 2 跳路径），而不是「代码里有
个 RoutingTable」。

反向验证（人工执行过，结论记录在此）：
* 注掉 lifecycle 的 mesh 注册段 → test_lifecycle_registers_mesh_adapter 红；
* 把 _handle_data 的中继分支改成直接返回失败 → test_three_node_relay 红。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple

import pytest

from core.adapters.mesh_routing_adapter import MeshRoutingAdapter


async def _make_chain() -> Tuple[MeshRoutingAdapter, MeshRoutingAdapter, MeshRoutingAdapter]:
    """A–B–C 链：localhost 三个真实监听端口，强制邻接（A 与 C 互不认识）。"""
    a = MeshRoutingAdapter(node_id="node_a")
    b = MeshRoutingAdapter(node_id="node_b")
    c = MeshRoutingAdapter(node_id="node_c")
    pa = await a.start_server(host="127.0.0.1", port=0)
    pb = await b.start_server(host="127.0.0.1", port=0)
    pc = await c.start_server(host="127.0.0.1", port=0)
    a.add_neighbor("node_b", "127.0.0.1", pb)
    b.add_neighbor("node_a", "127.0.0.1", pa)
    b.add_neighbor("node_c", "127.0.0.1", pc)
    c.add_neighbor("node_b", "127.0.0.1", pb)
    return a, b, c


async def _close_all(*adapters: MeshRoutingAdapter) -> None:
    for ad in adapters:
        await ad.close()


def test_three_node_relay_end_to_end() -> None:
    """A→C 必须经 B 真实中继：RREQ 洪泛找到路 + 数据帧逐跳转发 + 端到端回执。"""
    received: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []

    async def _run() -> Dict[str, Any]:
        a, b, c = await _make_chain()
        c.set_message_handler(lambda aip, meta: received.append((aip, meta)))
        try:
            return await a.send({"type": "task_assign", "payload": {"probe": 1}}, "node_c")
        finally:
            await _close_all(a, b, c)

    result = asyncio.run(_run())
    assert result.get("success") is True, f"A→C 多跳投递失败：{result}"
    assert received, "C 的 handler 没收到消息 —— 中继是空转"
    aip, meta = received[0]
    assert aip == {"type": "task_assign", "payload": {"probe": 1}}
    assert meta["src"] == "node_a"
    assert meta["path"] == ["node_a", "node_b", "node_c"], f"中继路径不对：{meta['path']}"
    # 回执里的路径同样必须体现真实两跳（端到端确认，不是「发出去了」）
    assert result.get("path") == ["node_a", "node_b", "node_c"], f"回执路径不对：{result}"


def test_direct_neighbor_send() -> None:
    """直连邻居单跳可达（mesh 的退化情形）。"""
    received: List[Dict[str, Any]] = []

    async def _run() -> Dict[str, Any]:
        a, b, c = await _make_chain()
        b.set_message_handler(lambda aip, meta: received.append(aip))
        try:
            return await a.send({"type": "heartbeat"}, "node_b")
        finally:
            await _close_all(a, b, c)

    result = asyncio.run(_run())
    assert result.get("success") is True
    assert received == [{"type": "heartbeat"}]


def test_unreachable_target_fails_honestly() -> None:
    """没有任何路能到的目标：如实返回失败，不假装成功、不无限等。"""

    async def _run() -> Dict[str, Any]:
        a, b, c = await _make_chain()
        try:
            return await asyncio.wait_for(a.send({"type": "heartbeat"}, "node_ghost"), timeout=10.0)
        finally:
            await _close_all(a, b, c)

    result = asyncio.run(_run())
    assert result.get("success") is False
    assert "no route" in str(result.get("error", ""))


def test_is_available_false_without_peers() -> None:
    """无 peers ⇒ is_available 恒 False（单节点部署下 mesh 天然沉默）。"""

    async def _run() -> Tuple[bool, bool]:
        lone = MeshRoutingAdapter(node_id="lone")
        await lone.start_server(host="127.0.0.1", port=0)
        try:
            no_peer = await lone.is_available("anyone")
            lone.add_neighbor("peer", "127.0.0.1", 1)
            with_peer = await lone.is_available("anyone")
        finally:
            await lone.close()
        return no_peer, with_peer

    no_peer, with_peer = asyncio.run(_run())
    assert no_peer is False, "没有邻接却报可用 —— 会把 mesh 卷进永远失败的 fallback"
    assert with_peer is True


def test_route_cache_survives_discovery() -> None:
    """RREQ/RREP 建立的路由进了 node_communication.RoutingTable（真实复用，非装饰）。"""

    async def _run() -> Any:
        a, b, c = await _make_chain()
        c.set_message_handler(lambda aip, meta: None)
        try:
            await a.send({"type": "heartbeat"}, "node_c")
            return await a._routing_table.get_route("node_c")
        finally:
            await _close_all(a, b, c)

    route = asyncio.run(_run())
    assert route is not None, "发现后路由表仍为空 —— RoutingTable 只是摆设"
    assert route.next_hop == "node_b"


def test_mesh_registered_in_lifecycle_and_priority() -> None:
    """融入点钉：lifecycle Phase 8 注册 mesh；优先级表把 mesh 放最后兜底。

    钉在 AST 层而不是源码字符串层：反向验证时发现，把注册行注释掉后
    字符串匹配依然通过（注释里字符串还在）—— 字符串钉是假钉。
    """
    import ast
    import inspect

    import galaxy_gateway.bootstrap.lifecycle as lc
    from core.aip_transport import AIPTransport

    tree = ast.parse(inspect.getsource(lc))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "register_adapter"
        and any(isinstance(a, ast.Name) and a.id == "mesh_adapter" for a in node.args)
    ]
    assert calls, "lifecycle 不再把 mesh_adapter 注册进 AIPTransport（真实调用消失，注释不算）"

    # 终点投递也必须接进 ingress 汇聚点：没有 handler，中继成功但内容进黑洞
    handler_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "set_message_handler"
    ]
    assert handler_calls, "mesh 收到的消息没有消费方（set_message_handler 未接 message_handler）"

    prio = AIPTransport()._transport_priority
    assert "mesh" in prio, "mesh 不在自动选路候选里 —— 注册了也永远轮不到"
    assert prio[-1] == "mesh", f"mesh 必须是最后兜底，实际位置：{prio}"


def test_wire_format_matches_tcp_adapter() -> None:
    """线协议与 tcp_adapter 一致：4 字节大端长度前缀 + UTF-8 JSON（Android 阶段 1 依赖）。"""
    import json

    from core.node_communication import Message, MessageType

    class _W:
        def __init__(self) -> None:
            self.buf = b""

        def write(self, b: bytes) -> None:
            self.buf += b

    w = _W()
    frame = Message(message_type=MessageType.DATA_REQUEST, source_id="a", target_id="b", payload={"aip": {"k": "v"}})
    MeshRoutingAdapter._write_frame(w, frame)  # type: ignore[arg-type]
    assert int.from_bytes(w.buf[:4], "big") == len(w.buf) - 4
    decoded = json.loads(w.buf[4:].decode("utf-8"))
    assert decoded["message_type"] == "data_request"
    assert decoded["payload"]["aip"] == {"k": "v"}


def test_flood_dedup_is_bounded() -> None:
    """洪泛查重必须有界（长期运行不膨胀），且真的去重。"""
    ad = MeshRoutingAdapter(node_id="x")
    assert ad._mark_seen("m1") is True
    assert ad._mark_seen("m1") is False
    for i in range(3000):
        ad._mark_seen(f"bulk_{i}")
    assert len(ad._seen_set) <= 2048


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
