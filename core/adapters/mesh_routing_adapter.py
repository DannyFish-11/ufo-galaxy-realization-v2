"""
core/adapters/mesh_routing_adapter.py — AODV 多跳 mesh 传输适配器（第 10 个适配器）

为什么存在
==========
既有 9 个适配器都是**单跳**：源直接摸得到目标才发得出去。断网自组网场景
（中心链路断、设备两两只有部分互通）需要的是**多跳中继**：A 摸不到 C，
但 A→B→C 都是活的 LAN 直连，消息就该经 B 转发过去。

复用而非重写
============
AODV 的路由语义完整复用 ``core.node_communication``（该模块此前被误删又恢复，
本适配器是它的真实调用方）：

* ``RoutingTable`` —— 路由记忆（序列号/跳数优选、过期、失效）；
* ``Message`` / ``MessageType.RREQ|RREP`` —— 路由发现的控制消息封装。

node_communication 缺的只是**真实网络层**（它经进程内 handler 投递），本适配器
补上这一层：线协议与 ``tcp_adapter`` 完全一致（4 字节大端长度前缀 + UTF-8 JSON），
Android 端阶段 1 的直连传输说的也是这套协议。

边界（评估结论，不越线）
========================
* 节点注册表视图 = **UDM**（peers 来自 lan_discovery 镜像进 UDM 的 mDNS 记录）；
  node_communication 自带的 NodeRegistry/LoadBalancer 与 UDM 冲突，**永不启用**。
* 无派发权力：mesh 只是传输，不做任务分配（单权威架构不变）。
* 无 peers 时 ``is_available`` 恒 False —— 单节点部署下本适配器天然沉默。

数据面语义
==========
逐跳同步中继：A→B 的连接保持打开，B 转发到 C 并**等到** C 的回执后原路回传。
因此 ``send`` 返回的 success 是**端到端**结果，不是"发出去了"。TTL + 路径查重
双重防环。
"""

import asyncio
import json
import logging
import os
import time
from collections import deque
from typing import Any, Callable, Dict, Optional, Tuple

from core.aip_transport import TransportAdapter
from core.node_communication import Message, MessageType, RoutingTable

logger = logging.getLogger("Galaxy.Adapter.Mesh")

DEFAULT_PORT = 19422  # tcp_adapter 是 19421，紧挨着
MAX_MESSAGE_SIZE = int(os.getenv("GALAXY_MAX_MESSAGE_SIZE", "10485760"))


def _discovery_timeout() -> float:
    try:
        return float(os.environ.get("GALAXY_MESH_DISCOVERY_TIMEOUT", "2.0") or "2.0")
    except ValueError:
        return 2.0


class MeshRoutingAdapter(TransportAdapter):
    """AODV 多跳 mesh 适配器。

    帧格式 = ``node_communication.Message.to_dict()`` 整体过 tcp_adapter 线协议。
    三种帧：DATA_REQUEST（数据 + 逐跳中继）、RREQ / RREP（路由发现）。
    """

    @property
    def transport_type(self) -> str:
        return "mesh"

    def __init__(self, node_id: str = "gateway", local_port: int = DEFAULT_PORT) -> None:
        self.node_id = node_id
        self._local_port = local_port
        self._neighbors: Dict[str, Tuple[str, int]] = {}  # node_id → (host, port)
        self._routing_table = RoutingTable()
        self._server: Optional[asyncio.Server] = None
        self._running = False
        self._sequence = 0
        self._seen: deque = deque(maxlen=2048)  # 洪泛查重（RREQ/RREP message_id）
        self._seen_set: set = set()
        self._message_handler: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Any]] = None
        self._last_refresh = 0.0

    # -- 邻接管理（注册表视图 = UDM，不用 NodeRegistry）---------------------

    def add_neighbor(self, node_id: str, host: str, port: int) -> None:
        """显式加一条直连邻接（测试注入强制邻接也走这里）。"""
        self._neighbors[node_id] = (host, port)

    def refresh_neighbors_from_discovery(self) -> int:
        """从 UDM 拉 lan_discovery 镜像进来的 ``_galaxy._tcp`` peers 作邻接。

        全程防御：UDM 不可用/无记录时保持现有邻接不变，返回本次新增数。
        """
        added = 0
        try:
            from core.unified.device_manager import get_unified_device_manager

            for dev in get_unified_device_manager().get_all_devices():
                meta = getattr(dev, "metadata", None) or {}
                if meta.get("protocol") != "mdns" or "_galaxy" not in str(meta.get("service_type", "")):
                    continue
                host = getattr(dev, "ip_address", None)
                port = getattr(dev, "port", None)
                if host and port and dev.device_id not in self._neighbors:
                    self.add_neighbor(dev.device_id, str(host), int(port))
                    added += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("mesh: 邻接刷新失败（保持现状）: %s", exc)
        self._last_refresh = time.time()
        return added

    def _maybe_refresh(self) -> None:
        if not self._neighbors and time.time() - self._last_refresh > 30.0:
            self.refresh_neighbors_from_discovery()

    def set_message_handler(self, handler: Callable[[Dict[str, Any], Dict[str, Any]], Any]) -> None:
        """终点投递回调：handler(aip_message, meta)。meta 含 src/path/hops。"""
        self._message_handler = handler

    # -- TransportAdapter 接口 ---------------------------------------------

    async def is_available(self, target: str) -> bool:
        self._maybe_refresh()
        return self._running and bool(self._neighbors) and target != self.node_id

    async def send(self, message: Dict[str, Any], target: str) -> Dict[str, Any]:
        """端到端发送：直连邻居 → 路由表 → 现场 RREQ 发现，三级都不通如实失败。"""
        if not self._running:
            return {"success": False, "via": "mesh", "error": "mesh server not running"}
        self._maybe_refresh()

        next_hop = target if target in self._neighbors else None
        if next_hop is None:
            route = await self._routing_table.get_route(target)
            if route is None:
                await self._discover_route(target)
                route = await self._routing_table.get_route(target)
            if route is not None and route.next_hop in self._neighbors:
                next_hop = route.next_hop
        if next_hop is None:
            return {"success": False, "via": "mesh", "error": f"mesh: no route to '{target}'"}

        frame = Message(
            message_type=MessageType.DATA_REQUEST,
            source_id=self.node_id,
            target_id=target,
            payload={"aip": message, "path": [self.node_id]},
        )
        return await self._send_data_frame(next_hop, frame)

    async def broadcast(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """只对直连邻居广播（多跳洪泛数据帧会放大风暴，不做）。"""
        results = {n: await self.send(message, n) for n in list(self._neighbors)}
        failed = [n for n, r in results.items() if not (r or {}).get("success")]
        return {"success": bool(results) and not failed, "via": "mesh", "results": results, "failed_targets": failed}

    async def close(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    # -- 服务端 ------------------------------------------------------------

    async def start_server(self, host: str = "0.0.0.0", port: Optional[int] = None) -> int:
        """启动监听；port=0 用临时端口（测试）。返回实际端口。"""
        if port is not None:
            self._local_port = port
        self._server = await asyncio.start_server(self._handle_conn, host, self._local_port)
        self._local_port = self._server.sockets[0].getsockname()[1]
        self._running = True
        logger.info("mesh 监听 %s:%d（node_id=%s）", host, self._local_port, self.node_id)
        return self._local_port

    async def _handle_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while self._running:
                try:
                    ln = await reader.readexactly(4)
                except asyncio.IncompleteReadError:
                    break
                size = int.from_bytes(ln, "big")
                if size > MAX_MESSAGE_SIZE:
                    break
                msg = Message.from_dict(json.loads((await reader.readexactly(size)).decode("utf-8")))
                if msg.message_type == MessageType.DATA_REQUEST:
                    result = await self._handle_data(msg)
                    self._write_frame(writer, self._result_frame(msg, result))
                    await writer.drain()
                elif msg.message_type == MessageType.RREQ:
                    await self._handle_rreq(msg)
                elif msg.message_type == MessageType.RREP:
                    await self._handle_rrep(msg)
        except Exception as exc:  # noqa: BLE001
            logger.debug("mesh 连接异常: %s", exc)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    # -- 数据面：逐跳同步中继 ----------------------------------------------

    async def _handle_data(self, msg: Message) -> Dict[str, Any]:
        path = list(msg.payload.get("path", []))
        if msg.target_id == self.node_id:
            meta = {"src": msg.source_id, "path": path + [self.node_id], "hops": len(path)}
            if self._message_handler is not None:
                try:
                    out = self._message_handler(msg.payload.get("aip", {}), meta)
                    if asyncio.iscoroutine(out):
                        await out
                except Exception as exc:  # noqa: BLE001
                    return {"success": False, "error": f"handler error: {exc}", **meta}
            return {"success": True, **meta}
        # 中继：TTL + 路径查重防环
        if msg.ttl <= 1 or self.node_id in path:
            return {"success": False, "error": "mesh: ttl exhausted or loop", "path": path}
        next_hop = msg.target_id if msg.target_id in self._neighbors else None
        if next_hop is None:
            route = await self._routing_table.get_route(msg.target_id)
            if route is not None and route.next_hop in self._neighbors:
                next_hop = route.next_hop
        if next_hop is None:
            return {"success": False, "error": f"mesh relay: no route to '{msg.target_id}'", "path": path}
        fwd = Message.from_dict(msg.to_dict())
        fwd.ttl = msg.ttl - 1
        fwd.payload = dict(msg.payload, path=path + [self.node_id])
        return await self._send_data_frame(next_hop, fwd)

    async def _send_data_frame(self, neighbor_id: str, frame: Message) -> Dict[str, Any]:
        host, port = self._neighbors[neighbor_id]
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=5.0)
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "via": "mesh", "error": f"mesh connect '{neighbor_id}' failed: {exc}"}
        try:
            self._write_frame(writer, frame)
            await writer.drain()
            ln = await asyncio.wait_for(reader.readexactly(4), timeout=15.0)
            body = await asyncio.wait_for(reader.readexactly(int.from_bytes(ln, "big")), timeout=15.0)
            resp = Message.from_dict(json.loads(body.decode("utf-8")))
            out = dict(resp.payload)
            out.setdefault("via", "mesh")
            return out
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "via": "mesh", "error": f"mesh send via '{neighbor_id}' failed: {exc}"}
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    def _result_frame(self, req: Message, result: Dict[str, Any]) -> Message:
        return Message(
            message_type=MessageType.DATA_RESPONSE,
            source_id=self.node_id,
            target_id=req.source_id,
            payload=result,
        )

    @staticmethod
    def _write_frame(writer: asyncio.StreamWriter, frame: Message) -> None:
        payload = json.dumps(frame.to_dict(), ensure_ascii=False).encode("utf-8")
        writer.write(len(payload).to_bytes(4, "big") + payload)

    # -- 控制面：AODV 路由发现（RREQ 洪泛 / RREP 逆路回传）-------------------

    async def _discover_route(self, target: str) -> None:
        self._sequence += 1
        rreq = Message(
            message_type=MessageType.RREQ,
            source_id=self.node_id,
            target_id="*",
            payload={
                "originator": self.node_id,
                "target": target,
                "originator_seq": self._sequence,
                "hop_count": 0,
                "sender_id": self.node_id,
            },
        )
        self._mark_seen(rreq.message_id)
        await self._flood(rreq, exclude=None)
        deadline = time.time() + _discovery_timeout()
        while time.time() < deadline:
            if await self._routing_table.get_route(target) is not None:
                return
            await asyncio.sleep(0.05)

    async def _handle_rreq(self, msg: Message) -> None:
        if not self._mark_seen(msg.message_id):
            return  # 洪泛回环，丢弃
        p = msg.payload
        originator, target = p.get("originator"), p.get("target")
        hop_count = int(p.get("hop_count", 0)) + 1
        sender = p.get("sender_id")
        if not originator or not target or sender is None:
            return
        # 逆向路由：回 originator 走 RREQ 进来的那个邻居
        if sender in self._neighbors and originator != self.node_id:
            await self._routing_table.add_route(originator, sender, hop_count, int(p.get("originator_seq", 0)))
        if target == self.node_id:
            await self._send_rrep(originator, target, hop_count=0)
            return
        route = await self._routing_table.get_route(target)
        if route is not None:
            await self._send_rrep(originator, target, hop_count=route.hop_count)
            return
        if msg.ttl > 1:
            fwd = Message.from_dict(msg.to_dict())
            fwd.ttl = msg.ttl - 1
            # from_dict 保留了原 message_id —— 同一洪泛 id，下游查重才有效
            fwd.payload = dict(p, hop_count=hop_count, sender_id=self.node_id)
            await self._flood(fwd, exclude=sender)

    async def _send_rrep(self, originator: str, target: str, hop_count: int) -> None:
        rrep = Message(
            message_type=MessageType.RREP,
            source_id=self.node_id,
            target_id=originator,
            payload={"originator": originator, "target": target, "hop_count": hop_count, "sender_id": self.node_id},
        )
        await self._forward_rrep(rrep)

    async def _handle_rrep(self, msg: Message) -> None:
        p = msg.payload
        target, sender = p.get("target"), p.get("sender_id")
        hop_count = int(p.get("hop_count", 0)) + 1
        if sender in self._neighbors and target and target != self.node_id:
            # 正向路由：去 target 走 RREP 进来的那个邻居
            await self._routing_table.add_route(target, sender, hop_count)
        if p.get("originator") != self.node_id:
            fwd = Message.from_dict(msg.to_dict())
            fwd.payload = dict(p, hop_count=hop_count, sender_id=self.node_id)
            await self._forward_rrep(fwd)

    async def _forward_rrep(self, rrep: Message) -> None:
        """RREP 沿逆向路由回传：originator 是邻居就直投，否则查路由表。"""
        originator = rrep.payload.get("originator", rrep.target_id)
        nh = originator if originator in self._neighbors else None
        if nh is None:
            route = await self._routing_table.get_route(originator)
            if route is not None and route.next_hop in self._neighbors:
                nh = route.next_hop
        if nh is None:
            logger.debug("mesh: RREP 无逆向路由可回 %s", originator)
            return
        await self._fire_frame(nh, rrep)

    async def _flood(self, frame: Message, exclude: Optional[str]) -> None:
        for nid in list(self._neighbors):
            if nid != exclude:
                await self._fire_frame(nid, frame)

    async def _fire_frame(self, neighbor_id: str, frame: Message) -> None:
        """控制帧单向投递（不等回执），失败只记 debug —— 洪泛允许部分失败。"""
        host, port = self._neighbors.get(neighbor_id, (None, None))
        if host is None:
            return
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=3.0)
            self._write_frame(writer, frame)
            await writer.drain()
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001
            logger.debug("mesh: 控制帧到 %s 投递失败: %s", neighbor_id, exc)

    def _mark_seen(self, message_id: str) -> bool:
        """未见过 → 记录并返回 True；见过 → False。有界，防长期运行膨胀。"""
        if message_id in self._seen_set:
            return False
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.discard(self._seen[0])
        self._seen.append(message_id)
        self._seen_set.add(message_id)
        return True
