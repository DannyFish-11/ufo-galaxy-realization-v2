#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_tcp_ingress_wiring.py
====================================
阶段 1 配套（V2 侧）：tcp_adapter 入站帧必须有真实消费方。

此前 ``_handle_incoming`` 的结尾是 ``# TODO: 分发到消息处理器`` —— 设备经
TCP 直连发上来的任何消息都只登记 peer 然后丢弃。Android 端阶段 1 接的就是
这条通道，没有消费方它就是空转。

判据是外部可观察结果：对着**真实监听的 TCPAdapter 服务端**发真实帧，
处理器必须收到解析后的消息；处理器的响应必须按同一线协议回到客户端。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

from core.adapters.tcp_adapter import TCPAdapter


def _frame(obj: Dict[str, Any]) -> bytes:
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return len(payload).to_bytes(4, "big") + payload


async def _start_server(adapter: TCPAdapter) -> int:
    adapter._running = True
    adapter._server = await asyncio.start_server(adapter._handle_incoming, "127.0.0.1", 0)
    return adapter._server.sockets[0].getsockname()[1]


def test_inbound_frame_reaches_handler_and_response_returns() -> None:
    """入站帧 → 处理器收到 (device_id, message)；处理器响应按线协议写回。"""
    received: List[Tuple[str, Dict[str, Any]]] = []

    async def _handler(device_id: str, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        received.append((device_id, message))
        return {"type": "ack", "echo": message.get("type")}

    async def _run() -> Dict[str, Any]:
        adapter = TCPAdapter(local_port=0)
        adapter.set_message_handler(_handler)
        port = await _start_server(adapter)
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(_frame({"type": "task_result", "device_id": "dev_tcp_probe", "payload": {"状态": "成功"}}))
            await writer.drain()
            ln = await asyncio.wait_for(reader.readexactly(4), timeout=5.0)
            body = await asyncio.wait_for(reader.readexactly(int.from_bytes(ln, "big")), timeout=5.0)
            writer.close()
            return json.loads(body.decode("utf-8"))
        finally:
            await adapter.close()

    resp = asyncio.run(_run())
    assert received, "入站帧没有到达消息处理器 —— TCP ingress 还是黑洞"
    dev, msg = received[0]
    assert dev == "dev_tcp_probe"
    assert msg["payload"] == {"状态": "成功"}
    assert resp == {"type": "ack", "echo": "task_result"}, f"响应没有按线协议回到客户端：{resp}"


def test_handler_error_keeps_connection_alive() -> None:
    """一条坏消息不断连：处理器抛错后，后续帧仍然被消费。"""
    seen: List[str] = []

    async def _handler(device_id: str, message: Dict[str, Any]) -> None:
        seen.append(message.get("type", ""))
        if message.get("type") == "boom":
            raise RuntimeError("handler exploded")
        return None

    async def _run() -> None:
        adapter = TCPAdapter(local_port=0)
        adapter.set_message_handler(_handler)
        port = await _start_server(adapter)
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(_frame({"type": "boom", "device_id": "d1"}))
            writer.write(_frame({"type": "heartbeat", "device_id": "d1"}))
            await writer.drain()
            await asyncio.sleep(0.3)
            writer.close()
        finally:
            await adapter.close()

    asyncio.run(_run())
    assert seen == ["boom", "heartbeat"], f"坏消息断掉了连接，后续帧丢失：{seen}"


def test_without_handler_old_behavior_is_kept() -> None:
    """未设置处理器时保持旧行为：登记 peer、不崩、不回帧。"""

    async def _run() -> bool:
        adapter = TCPAdapter(local_port=0)
        port = await _start_server(adapter)
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(_frame({"type": "heartbeat", "device_id": "legacy_peer"}))
            await writer.drain()
            await asyncio.sleep(0.3)
            writer.close()
            return "legacy_peer" in adapter._peers
        finally:
            await adapter.close()

    assert asyncio.run(_run()) is True, "无处理器时连 peer 登记都没了 —— 旧行为被破坏"


def test_envelope_frames_bridge_to_mesh_over_plain_port() -> None:
    """mesh 信封帧打到普通 tcp 端口必须桥接给 mesh 并把应答原路写回。

    发现型 mesh 邻接(UDM mDNS 记录)指向的就是这个端口 —— 没有桥,经发现
    建立的邻接发出的每一帧都被当普通帧丢弃,mesh 只在显式注入邻接时才通。
    """
    from core.adapters.mesh_routing_adapter import MeshRoutingAdapter
    from core.node_communication import Message, MessageType

    delivered: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []

    async def _run() -> Dict[str, Any]:
        mesh = MeshRoutingAdapter(node_id="gateway")
        mesh._running = True  # 只作为信封处理方,不必开自己的监听
        mesh.set_message_handler(lambda aip, meta: delivered.append((aip, meta)))

        tcp = TCPAdapter(local_port=0)
        tcp.set_envelope_handler(mesh.handle_envelope)
        port = await _start_server(tcp)
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            frame = Message(
                message_type=MessageType.DATA_REQUEST,
                source_id="phone",
                target_id="gateway",
                payload={"aip": {"type": "heartbeat"}, "path": ["phone"]},
            )
            writer.write(_frame(frame.to_dict()))
            await writer.drain()
            ln = await asyncio.wait_for(reader.readexactly(4), timeout=5.0)
            body = await asyncio.wait_for(reader.readexactly(int.from_bytes(ln, "big")), timeout=5.0)
            writer.close()
            return json.loads(body.decode("utf-8"))
        finally:
            await tcp.close()

    resp = asyncio.run(_run())
    assert delivered and delivered[0][0] == {"type": "heartbeat"}, "信封帧没有桥接到 mesh 投递"
    assert resp.get("message_type") == "data_response" and resp["payload"].get("success") is True, f"应答不对:{resp}"


def test_lifecycle_wires_tcp_ingress() -> None:
    """融入点 AST 钉：lifecycle 必须真实调用 tcp_adapter.set_message_handler(…)。"""
    import ast
    import inspect

    import galaxy_gateway.bootstrap.lifecycle as lc

    tree = ast.parse(inspect.getsource(lc))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "set_message_handler"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "tcp_adapter"
    ]
    assert calls, "lifecycle 不再把 TCP 入站接到 ingress 汇聚点（真实调用消失，注释不算）"
