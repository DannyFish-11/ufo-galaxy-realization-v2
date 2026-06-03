"""
MeshCoordinator — 设备协同网络层
==================================

职责: 设备组网、状态同步、多设备协同
不负责: 消息传输（已移至 AIPTransport）

核心功能:
1. 设备发现 — peer_announce / peer_exchange
2. 拓扑维护 — get_topology / build_peer_exchange
3. 多设备协同 — 同步设备状态、协同决策

与现有组件的关系:
- p2p_connector.py: 真正的 P2P TCP 直连（独立组件）
- proxy_relay.py: 服务端中继（独立组件）
- AIPTransport: 统一传输入口（新建）
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Dict, Any, Optional, Callable, Awaitable, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("Galaxy.MeshCoordinator")

# ---------------------------------------------------------------------------
# PR-4 transport role sentinels (FIXED)
# Mesh is a PRIMARY transport for cross-device / multi-device scenarios.
# Mesh acts as the preferred path when peers are reachable via P2P,
# with Relay and WebSocket as fallback options.
# ---------------------------------------------------------------------------
MESH_TRANSPORT_ROLE: str = "MESH::PRIMARY_TRANSPORT"
MESH_ORCHESTRATION_EXCLUDED: bool = False


class ConnectionType(str, Enum):
    DIRECT = "direct"       # LAN TCP 直连
    RELAY = "relay"         # 服务端中继
    UNKNOWN = "unknown"


@dataclass
class PeerEntry:
    """Peer 表条目"""
    device_id: str
    local_ip: str = ""
    local_port: int = 0
    public_ip: str = ""
    public_port: int = 0
    reachable_direct: bool = False
    connection_type: ConnectionType = ConnectionType.UNKNOWN
    latency_ms: float = -1          # -1 = 未探测
    last_seen: float = field(default_factory=time.time)
    last_probe: float = 0
    probe_failures: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "device_id": self.device_id,
            "local_ip": self.local_ip,
            "local_port": self.local_port,
            "public_ip": self.public_ip,
            "public_port": self.public_port,
            "reachable_direct": self.reachable_direct,
            "connection_type": self.connection_type.value,
            "latency_ms": self.latency_ms,
            "last_seen": self.last_seen,
            "probe_failures": self.probe_failures,
            "metadata": self.metadata,
        }


@dataclass
class MeshSendResult:
    """DEPRECATED: mesh.send() 已删除，此类保留用于向后兼容"""
    success: bool
    via: ConnectionType
    target_device: str = ""
    latency_ms: float = 0
    error: str = ""
    direct_attempted: bool = False
    direct_health_checked: bool = False
    fallback_used: bool = False
    fallback_reason: str = ""
    route_decision: str = ""

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "via": self.via.value,
            "target_device": self.target_device,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "route_decision": self.route_decision,
        }


# P2P 发送回调: (device_id, message_bytes) -> bool
P2PSender = Callable[[str, bytes], Awaitable[bool]]

# Relay 发送回调: (source, target, payload_type, payload) -> result_dict
RelaySender = Callable[[str, str, str, Dict], Awaitable[Dict]]

# WS 发送回调: (device_id, message_dict) -> bool
WSSender = Callable[[str, Dict], Awaitable[bool]]


class MeshCoordinator:
    """
    P2P 混合组网协调器

    职责:
    1. 维护 peer 表 (device_id → PeerEntry)
    2. 每条消息自动选路 (P2P direct vs server relay)
    3. 定期探测 peer 可达性
    4. 提供拓扑查询 API
    """

    PROBE_INTERVAL = 60        # 秒: 重探测间隔
    PROBE_TIMEOUT = 3          # 秒: 单次探测超时
    MAX_PROBE_FAILURES = 3     # 连续失败 N 次后标记不可达
    PEER_EXPIRE = 300          # 秒: peer 过期时间 (无心跳)

    def __init__(
        self,
        local_device_id: str = "server",
        p2p_sender: P2PSender = None,
        relay_sender: RelaySender = None,
        ws_sender: WSSender = None,
    ):
        self._local_id = local_device_id
        # DEPRECATED: senders 已移至 AIPTransport，保留兼容
        self._p2p_send = p2p_sender   # legacy, do not use
        self._relay_send = relay_sender  # legacy, do not use
        self._ws_send = ws_sender  # legacy, do not use
        self._peers: Dict[str, PeerEntry] = {}
        self._stats = {
            "total_sent": 0,
            "via_direct": 0,
            "via_relay": 0,
            "direct_attempted": 0,
            "direct_unavailable": 0,
            "fallback_relay": 0,
            "fallback_ws": 0,
            "probe_success": 0,
            "probe_fail": 0,
        }
        self._last_overlay_dispatch: Dict[str, Any] = {"available": False}

    # ================================================================
    # Peer 管理
    # ================================================================

    def register_peer(
        self,
        device_id: str,
        local_ip: str = "",
        local_port: int = 0,
        public_ip: str = "",
        public_port: int = 0,
        metadata: Dict = None,
    ) -> PeerEntry:
        """注册或更新一个 peer"""
        if device_id in self._peers:
            peer = self._peers[device_id]
            if local_ip:
                peer.local_ip = local_ip
            if local_port:
                peer.local_port = local_port
            if public_ip:
                peer.public_ip = public_ip
            if public_port:
                peer.public_port = public_port
            peer.last_seen = time.time()
            if metadata:
                peer.metadata.update(metadata)
        else:
            peer = PeerEntry(
                device_id=device_id,
                local_ip=local_ip,
                local_port=local_port,
                public_ip=public_ip,
                public_port=public_port,
                metadata=metadata or {},
            )
            self._peers[device_id] = peer
            logger.info(f"Peer registered: {device_id} ({local_ip}:{local_port})")
        return peer

    def unregister_peer(self, device_id: str):
        """注销 peer"""
        self._peers.pop(device_id, None)

    def get_peer(self, device_id: str) -> Optional[PeerEntry]:
        return self._peers.get(device_id)

    def is_peer_direct(self, device_id: str) -> bool:
        """判断是否可以直连"""
        peer = self._peers.get(device_id)
        return bool(peer and peer.reachable_direct)

    def list_peers(self) -> List[Dict]:
        return [p.to_dict() for p in self._peers.values()]

    # ================================================================
    # 核心选路 + 发送
    # ================================================================

    async def _check_direct_viability(self, target_device: str, peer: Optional[PeerEntry]) -> tuple[bool, bool, str]:
        """检查 direct path 是否可用，并在需要时执行健康探测。

        Returns:
            (is_viable, health_checked, reason)
            - is_viable: True 表示可以尝试 direct send。
            - health_checked: True 表示本次执行了 probe 健康探测；未探测时为 False。
            - reason: 仅在 is_viable=False 时给出失败原因；成功时为空字符串。
        """
        if not peer:
            return False, False, "peer_not_registered"
        if not peer.reachable_direct:
            return False, False, "peer_marked_relay_only"
        if not self._p2p_send:
            return False, False, "p2p_sender_unconfigured"
        if not peer.local_ip:
            return False, False, "peer_local_ip_missing"

        now = time.time()
        should_probe = peer.last_probe <= 0 or (now - peer.last_probe) > self.PROBE_INTERVAL
        if should_probe:
            probe_ok = await self.probe_peer(target_device)
            if not probe_ok:
                peer.reachable_direct = False
                peer.connection_type = ConnectionType.RELAY
                return False, True, "direct_probe_failed"
            return True, True, ""
        return True, False, ""

    # ================================================================
    # Peer 探测
    # ================================================================

    async def probe_peer(self, device_id: str) -> bool:
        """探测单个 peer 的 TCP 可达性"""
        peer = self._peers.get(device_id)
        if not peer or not peer.local_ip:
            return False

        port = peer.local_port or 19720
        start = time.time()

        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(peer.local_ip, port),
                timeout=self.PROBE_TIMEOUT,
            )
            writer.close()
            await writer.wait_closed()

            latency = (time.time() - start) * 1000
            peer.reachable_direct = True
            peer.latency_ms = latency
            peer.connection_type = ConnectionType.DIRECT
            peer.probe_failures = 0
            peer.last_probe = time.time()
            self._stats["probe_success"] += 1
            logger.debug(f"Probe OK: {device_id} ({latency:.1f}ms)")
            return True
        except (asyncio.TimeoutError, OSError, ConnectionRefusedError):
            peer.probe_failures += 1
            if peer.probe_failures >= self.MAX_PROBE_FAILURES:
                peer.reachable_direct = False
                peer.connection_type = ConnectionType.RELAY
            peer.last_probe = time.time()
            self._stats["probe_fail"] += 1
            return False

    async def probe_all_peers(self):
        """探测所有 peer (并行)"""
        tasks = []
        now = time.time()
        for device_id, peer in self._peers.items():
            if peer.local_ip and (now - peer.last_probe) > self.PROBE_INTERVAL:
                tasks.append(self.probe_peer(device_id))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ================================================================
    # Peer 交换协议 (服务端侧)
    # ================================================================

    def build_peer_exchange(self, exclude_device: str = "") -> List[Dict]:
        """
        构建 peer_exchange 消息 — 服务端下发给设备

        包含所有在线 peer 的 LAN 信息,
        设备收到后可以尝试直连。
        """
        peers = []
        now = time.time()
        for device_id, peer in self._peers.items():
            if device_id == exclude_device:
                continue
            if (now - peer.last_seen) > self.PEER_EXPIRE:
                continue
            peers.append({
                "device_id": peer.device_id,
                "local_ip": peer.local_ip,
                "local_port": peer.local_port,
                "public_ip": peer.public_ip,
                "public_port": peer.public_port,
            })
        return peers

    async def broadcast_peer_exchange(self):
        """向所有在线设备广播 peer 列表"""
        if not self._ws_send:
            return

        for device_id in list(self._peers.keys()):
            peer_list = self.build_peer_exchange(exclude_device=device_id)
            if peer_list:
                await self._ws_send(device_id, {
                    "type": "peer_exchange",
                    "peers": peer_list,
                    "timestamp": time.time(),
                })

    def handle_peer_announce(self, device_id: str, data: Dict) -> PeerEntry:
        """
        处理设备的 peer_announce 消息

        设备连接 WS 后上报: {"type": "peer_announce", "local_ip": ..., "local_port": ...}
        """
        return self.register_peer(
            device_id=device_id,
            local_ip=data.get("local_ip", ""),
            local_port=data.get("local_port", 0),
            public_ip=data.get("public_ip", ""),
            public_port=data.get("public_port", 0),
            metadata=data.get("metadata", {}),
        )

    # ================================================================
    # 拓扑
    # ================================================================

    def get_topology(self) -> Dict:
        """返回完整拓扑信息"""
        now = time.time()
        nodes = []
        edges = []

        # 服务端节点
        nodes.append({
            "id": self._local_id,
            "type": "server",
            "role": "hub",
        })

        for device_id, peer in self._peers.items():
            alive = (now - peer.last_seen) < self.PEER_EXPIRE
            nodes.append({
                "id": device_id,
                "type": "device",
                "local_ip": peer.local_ip,
                "alive": alive,
                "connection_type": peer.connection_type.value,
            })

            # 服务端 ↔ 设备 (WS)
            edges.append({
                "source": self._local_id,
                "target": device_id,
                "type": "websocket",
                "active": alive,
            })

            # P2P 直连边
            if peer.reachable_direct:
                # 查找其他 direct peer 在同一 LAN
                for other_id, other_peer in self._peers.items():
                    if other_id != device_id and other_peer.reachable_direct:
                        if peer.local_ip and other_peer.local_ip:
                            # 同网段检测 (简化: 取前三段)
                            if (peer.local_ip.rsplit(".", 1)[0] ==
                                    other_peer.local_ip.rsplit(".", 1)[0]):
                                edge_id = tuple(sorted([device_id, other_id]))
                                edge = {
                                    "source": edge_id[0],
                                    "target": edge_id[1],
                                    "type": "p2p_direct",
                                    "active": True,
                                }
                                if edge not in edges:
                                    edges.append(edge)

        alive_peer_count = sum(1 for p in self._peers.values() if (now - p.last_seen) < self.PEER_EXPIRE)
        topology_ready = alive_peer_count >= 2
        canonical_closure: Dict[str, Any] = {"available": False, "closure_authority": "canonical_result_ingress"}
        try:
            from core.unified_result_ingress import get_last_result_closure_outcome

            closure = get_last_result_closure_outcome()
            if closure:
                canonical_closure = {
                    **closure,
                    "available": True,
                    "closure_authority": "canonical_result_ingress",
                }
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

        merged_result_summary: Optional[Dict[str, Any]] = None
        if canonical_closure.get("available"):
            try:
                from contracts.cross_runtime_result_merge import (
                    from_execution_output,
                    merge_runtime_results,
                    build_result_merge_summary,
                )

                task_id = str(canonical_closure.get("task_id") or "")
                normalized_status = str(canonical_closure.get("normalized_status") or "")
                merge_unit = from_execution_output(
                    {
                        "success": normalized_status == "completed",
                        "action_taken": "mesh_result_ingressed",
                        "result": {"task_id": task_id},
                    },
                    task_id=task_id or None,
                    trace_id=task_id or None,
                    device_id=canonical_closure.get("device_id") or None,
                    metadata={"source": "mesh_loop_baseline"},
                )
                merged = merge_runtime_results(
                    result_units=[merge_unit],
                    task_id=task_id or None,
                    trace_id=task_id or None,
                    merge_reason="mesh_loop_baseline_single_result",
                )
                merged_result_summary = build_result_merge_summary(result=merged).to_dict()
            except Exception as exc:
                logger.debug("Fallback triggered: %s", exc)
                merged_result_summary = None

        if merged_result_summary is not None:
            canonical_closure["merged_result_summary"] = merged_result_summary

        loop_baseline = {
            "overlay_coordination": {
                "authority": "mesh_overlay_coordination",
                "topology_ready": topology_ready,
                "alive_peers": alive_peer_count,
                "last_dispatch": dict(self._last_overlay_dispatch),
            },
            "canonical_closure": canonical_closure,
            "end_to_end_closed": bool(
                topology_ready
                and self._last_overlay_dispatch.get("success")
                and canonical_closure.get("is_fully_closed")
            ),
        }

        return {
            "nodes": nodes,
            "edges": edges,
            "total_peers": len(self._peers),
            "direct_peers": sum(1 for p in self._peers.values() if p.reachable_direct),
            "relay_peers": sum(1 for p in self._peers.values() if not p.reachable_direct),
            "topology_readiness": "ready" if topology_ready else "not_ready",
            "loop_baseline": loop_baseline,
        }

    def get_stats(self) -> Dict:
        return {
            **self._stats,
            "total_peers": len(self._peers),
            "direct_peers": sum(1 for p in self._peers.values() if p.reachable_direct),
        }

    # ================================================================
    # 清理
    # ================================================================

    def cleanup_expired(self):
        """清理过期 peer"""
        now = time.time()
        expired = [
            did for did, p in self._peers.items()
            if (now - p.last_seen) > self.PEER_EXPIRE
        ]
        for did in expired:
            del self._peers[did]
            logger.info(f"Peer expired: {did}")


# ============================================================================
# 单例
# ============================================================================

_mesh_instance: Optional[MeshCoordinator] = None


def get_mesh_coordinator(
    *,
    p2p_sender: Optional[Callable[..., Awaitable[Any]]] = None,
    relay_sender: Optional[Callable[..., Awaitable[Any]]] = None,
    ws_sender: Optional[Callable[..., Awaitable[Any]]] = None,
) -> MeshCoordinator:
    global _mesh_instance
    if _mesh_instance is None:
        _mesh_instance = MeshCoordinator()
    if p2p_sender is not None:
        _mesh_instance._p2p_send = p2p_sender
    if relay_sender is not None:
        _mesh_instance._relay_send = relay_sender
    if ws_sender is not None:
        _mesh_instance._ws_send = ws_sender
    return _mesh_instance


def inject_mesh_senders(
    p2p_sender: Optional[Callable[..., Awaitable[Any]]] = None,
    relay_sender: Optional[Callable[..., Awaitable[Any]]] = None,
    ws_sender: Optional[Callable[..., Awaitable[Any]]] = None,
) -> None:
    get_mesh_coordinator(
        p2p_sender=p2p_sender,
        relay_sender=relay_sender,
        ws_sender=ws_sender,
    )
    logger.info(
        "Mesh senders injected | p2p=%s relay=%s ws=%s",
        p2p_sender is not None,
        relay_sender is not None,
        ws_sender is not None,
    )
