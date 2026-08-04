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


def test_direct_link_failure_falls_back_to_multihop() -> None:
    """直连邻居的**链路**断了(地址死了)不等于没路:必须按 AODV 回退多跳。

    真实路径复跑发现:原实现直连失败就地放弃,A–C 直连断、A–B–C 活的场景发不出去。
    """
    received: List[Dict[str, Any]] = []

    async def _run() -> Dict[str, Any]:
        a, b, c = await _make_chain()
        c.set_message_handler(lambda aip, meta: received.append(meta))
        a.add_neighbor("node_c", "127.0.0.1", 1)  # 直连地址是死端口
        try:
            return await a.send({"type": "heartbeat"}, "node_c")
        finally:
            await _close_all(a, b, c)

    result = asyncio.run(_run())
    assert result.get("success") is True, f"直连断后没有回退多跳:{result}"
    assert received and received[0]["path"] == ["node_a", "node_b", "node_c"]


def test_stale_route_is_invalidated_and_rediscovered() -> None:
    """陈旧路由(next_hop 已不是邻居)必须失效并重新发现,不能挡住发现路径。"""
    received: List[Dict[str, Any]] = []

    async def _run() -> Dict[str, Any]:
        a, b, c = await _make_chain()
        c.set_message_handler(lambda aip, meta: received.append(aip))
        await a._routing_table.add_route("node_c", "ghost", 1, 999)  # 预埋陈旧路由
        try:
            return await a.send({"type": "heartbeat"}, "node_c")
        finally:
            await _close_all(a, b, c)

    result = asyncio.run(_run())
    assert result.get("success") is True and received, f"陈旧路由挡住了重新发现:{result}"


def test_rrep_forward_respects_ttl() -> None:
    """RREP 转发必须减 TTL 并在耗尽时丢弃 —— 病态路由状态下不得无限转发。"""
    from core.node_communication import Message, MessageType

    ad = MeshRoutingAdapter(node_id="mid")
    ad.add_neighbor("prev", "127.0.0.1", 1)
    forwarded: List[Any] = []

    async def _spy(rrep: Any) -> None:
        forwarded.append(rrep)

    ad._forward_rrep = _spy  # type: ignore[method-assign]
    payload = {"originator": "orig", "target": "t", "hop_count": 3, "sender_id": "prev"}
    dead = Message(message_type=MessageType.RREP, source_id="n", target_id="orig", payload=dict(payload), ttl=1)
    alive = Message(message_type=MessageType.RREP, source_id="n", target_id="orig", payload=dict(payload), ttl=5)
    asyncio.run(ad._handle_rrep(dead))
    asyncio.run(ad._handle_rrep(alive))
    assert len(forwarded) == 1, f"TTL 防环失效:forwarded={len(forwarded)}"
    assert forwarded[0].ttl == 4


def test_neighbor_refresh_syncs_with_real_udm(tmp_path, monkeypatch) -> None:
    """邻接刷新对着**真实 UDM API**:上线加入、下线清理、显式注入不动。

    真实路径复跑发现:第一版调用了不存在的 get_all_devices(),AttributeError 被
    防御 except 吞掉 —— 发现型邻接自始至终静默空转。此钉用真实 UDM 防止再犯。
    """
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    from core.unified.device_manager import get_unified_device_manager

    dm = get_unified_device_manager()
    dm.register_device_from_dict("mdns_mesh_probe", {"device_type": "iot", "device_name": "probe"})
    dm.upsert_device_state(
        "mdns_mesh_probe",
        {
            "status": "online",
            "ip_address": "127.0.0.9",
            "port": 12345,
            "metadata": {"protocol": "mdns", "service_type": "_galaxy._tcp.local."},
        },
        source="lan_discovery",
    )
    ad = MeshRoutingAdapter(node_id="x")
    ad.add_neighbor("manual_peer", "127.0.0.8", 999)
    added = ad.refresh_neighbors_from_discovery()
    assert added >= 1 and "mdns_mesh_probe" in ad._neighbors, f"在线 peer 没进邻接:{list(ad._neighbors)}"

    dm.upsert_device_state("mdns_mesh_probe", {"status": "offline"}, source="lan_discovery")
    ad._last_refresh = 0.0
    ad.refresh_neighbors_from_discovery()
    assert "mdns_mesh_probe" not in ad._neighbors, "下线 peer 没被清理"
    assert "manual_peer" in ad._neighbors, "显式注入的邻接被误清"


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
