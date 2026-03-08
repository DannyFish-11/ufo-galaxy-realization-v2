"""
ProxyRelay — 设备间指令转发中继
================================

Phase 2 Matrix OS 核心组件。

当前架构是星型拓扑 (所有设备 → 服务端 WebSocket)。
ProxyRelay 利用服务端作为中继, 实现任意设备 A → 设备 B 的指令转发。

核心功能:
1. device_to_device: A → Server → B (指令转发)
2. device_to_device_with_reply: A → Server → B → Server → A (带回复)
3. relay_agent: 将 AgentManifest 从一台设备迁移到另一台
4. relay_broadcast: 从一台设备广播到所有其他设备
5. relay_chain: A → B → C 链式转发

协议消息类型 (扩展 AIP v2):
- RELAY_REQUEST: 设备 A 发起的转发请求
- RELAY_FORWARD: 服务端转发给设备 B 的实际消息
- RELAY_REPLY: 设备 B 返回的响应
- RELAY_ACK: 服务端确认转发成功
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Dict, Any, Optional, Callable, Awaitable, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("Galaxy.ProxyRelay")


class RelayStatus(str, Enum):
    PENDING = "pending"
    FORWARDED = "forwarded"
    DELIVERED = "delivered"
    REPLIED = "replied"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class RelayRequest:
    """设备间转发请求"""
    relay_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_device: str = ""
    target_device: str = ""
    payload_type: str = ""       # task / command / agent_deploy / chat / custom
    payload: Dict[str, Any] = field(default_factory=dict)
    expect_reply: bool = False
    timeout_seconds: float = 30.0
    priority: int = 5            # 1=highest, 10=lowest
    created_at: float = field(default_factory=time.time)
    chain: List[str] = field(default_factory=list)  # 链式转发目标

    def to_dict(self) -> Dict:
        return {
            "relay_id": self.relay_id,
            "source_device": self.source_device,
            "target_device": self.target_device,
            "payload_type": self.payload_type,
            "payload": self.payload,
            "expect_reply": self.expect_reply,
            "timeout_seconds": self.timeout_seconds,
            "priority": self.priority,
            "created_at": self.created_at,
            "chain": self.chain,
        }


@dataclass
class RelayResult:
    """转发结果"""
    relay_id: str
    status: RelayStatus
    source_device: str = ""
    target_device: str = ""
    reply_payload: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    latency_ms: float = 0

    def to_dict(self) -> Dict:
        return {
            "relay_id": self.relay_id,
            "status": self.status.value,
            "source_device": self.source_device,
            "target_device": self.target_device,
            "reply_payload": self.reply_payload,
            "error": self.error,
            "latency_ms": self.latency_ms,
        }


# WS 发送回调类型: (device_id, message_dict) -> bool
DeviceSender = Callable[[str, Dict[str, Any]], Awaitable[bool]]


class ProxyRelay:
    """
    代理中继器 — 设备间指令转发

    职责:
    1. 接收设备 A 的 relay_request
    2. 通过 WebSocket 转发给设备 B
    3. 可选: 等待设备 B 的 relay_reply 回传给 A
    4. 支持链式转发 (A → B → C)
    5. 支持广播转发 (A → 所有设备)
    """

    def __init__(self, device_sender: DeviceSender = None, get_online_devices: Callable = None):
        """
        Args:
            device_sender: 向指定设备发送 WS 消息的回调
            get_online_devices: 获取在线设备列表的回调
        """
        self._sender = device_sender
        self._get_online = get_online_devices
        self._pending_relays: Dict[str, RelayRequest] = {}
        self._reply_futures: Dict[str, asyncio.Future] = {}
        self._relay_history: List[Dict] = []  # 最近 200 条
        self._stats = {"total": 0, "success": 0, "failed": 0, "timeout": 0}

    def set_sender(self, sender: DeviceSender):
        self._sender = sender

    def set_online_getter(self, getter: Callable):
        self._get_online = getter

    # ================================================================
    # 核心中继方法
    # ================================================================

    async def relay(self, request: RelayRequest) -> RelayResult:
        """
        核心中继入口 — 处理一个设备间转发请求

        流程:
        0. [Phase 5] 先检查 MeshCoordinator 是否可以 P2P 直连
        1. 验证目标设备在线
        2. 构建 relay_forward 消息
        3. 通过 WS 发送给目标设备
        4. 如果 expect_reply, 等待响应
        5. 返回结果
        """
        start = time.time()

        # Phase 5: 尝试 Mesh P2P 直连 (非 expect_reply 场景)
        if not request.expect_reply and not request.chain:
            try:
                from core.mesh_coordinator import get_mesh_coordinator
                mesh = get_mesh_coordinator()
                if mesh.is_peer_direct(request.target_device):
                    result = await mesh.send(
                        target_device=request.target_device,
                        payload=request.payload,
                        payload_type=request.payload_type,
                        source_device=request.source_device,
                    )
                    if result.success:
                        self._stats["total"] += 1
                        self._stats["success"] += 1
                        return RelayResult(
                            relay_id=request.relay_id,
                            status=RelayStatus.FORWARDED,
                            source_device=request.source_device,
                            target_device=request.target_device,
                            latency_ms=result.latency_ms,
                        )
            except Exception:
                pass  # Mesh 不可用, 继续走原有 WS 中继
        self._stats["total"] += 1
        self._pending_relays[request.relay_id] = request

        try:
            if not self._sender:
                return self._fail(request, "No device sender configured", start)

            # 链式转发
            if request.chain:
                return await self._relay_chain(request, start)

            # 单设备转发
            return await self._relay_single(request, start)

        except Exception as e:
            logger.error(f"Relay failed: {e}")
            return self._fail(request, str(e), start)
        finally:
            self._pending_relays.pop(request.relay_id, None)

    async def _relay_single(self, request: RelayRequest, start: float) -> RelayResult:
        """单目标转发"""
        forward_msg = {
            "type": "relay_forward",
            "relay_id": request.relay_id,
            "source_device": request.source_device,
            "payload_type": request.payload_type,
            "payload": request.payload,
            "expect_reply": request.expect_reply,
        }

        success = await self._sender(request.target_device, forward_msg)
        if not success:
            return self._fail(request, f"Device {request.target_device} not reachable", start)

        logger.info(
            f"Relay {request.relay_id[:8]}: "
            f"{request.source_device} → {request.target_device} "
            f"[{request.payload_type}]"
        )

        if not request.expect_reply:
            result = RelayResult(
                relay_id=request.relay_id,
                status=RelayStatus.FORWARDED,
                source_device=request.source_device,
                target_device=request.target_device,
                latency_ms=(time.time() - start) * 1000,
            )
            self._stats["success"] += 1
            self._record(result)
            return result

        # 等待回复
        future = asyncio.get_running_loop().create_future()
        self._reply_futures[request.relay_id] = future

        try:
            reply_data = await asyncio.wait_for(future, timeout=request.timeout_seconds)
            result = RelayResult(
                relay_id=request.relay_id,
                status=RelayStatus.REPLIED,
                source_device=request.source_device,
                target_device=request.target_device,
                reply_payload=reply_data,
                latency_ms=(time.time() - start) * 1000,
            )
            self._stats["success"] += 1
            self._record(result)
            return result
        except asyncio.TimeoutError:
            result = RelayResult(
                relay_id=request.relay_id,
                status=RelayStatus.TIMEOUT,
                source_device=request.source_device,
                target_device=request.target_device,
                error=f"Reply timeout after {request.timeout_seconds}s",
                latency_ms=(time.time() - start) * 1000,
            )
            self._stats["timeout"] += 1
            self._record(result)
            return result
        finally:
            self._reply_futures.pop(request.relay_id, None)

    async def _relay_chain(self, request: RelayRequest, start: float) -> RelayResult:
        """链式转发 A → B → C → ..."""
        chain = [request.target_device] + list(request.chain)
        current_payload = request.payload

        for i, target in enumerate(chain):
            is_last = (i == len(chain) - 1)
            step_req = RelayRequest(
                relay_id=f"{request.relay_id}_step{i}",
                source_device=request.source_device if i == 0 else chain[i - 1],
                target_device=target,
                payload_type=request.payload_type,
                payload=current_payload,
                expect_reply=request.expect_reply and is_last,
                timeout_seconds=request.timeout_seconds / len(chain),
            )
            result = await self._relay_single(step_req, start)
            if result.status in (RelayStatus.FAILED, RelayStatus.TIMEOUT):
                return RelayResult(
                    relay_id=request.relay_id,
                    status=result.status,
                    source_device=request.source_device,
                    target_device=target,
                    error=f"Chain failed at step {i}: {result.error}",
                    latency_ms=(time.time() - start) * 1000,
                )
            if result.reply_payload:
                current_payload = result.reply_payload

        return RelayResult(
            relay_id=request.relay_id,
            status=RelayStatus.REPLIED if request.expect_reply else RelayStatus.FORWARDED,
            source_device=request.source_device,
            target_device=chain[-1],
            reply_payload=current_payload if request.expect_reply else {},
            latency_ms=(time.time() - start) * 1000,
        )

    async def relay_broadcast(
        self, source_device: str, payload_type: str, payload: Dict
    ) -> Dict[str, RelayResult]:
        """广播转发 — 从 source 发送到所有其他在线设备"""
        results = {}
        online = self._get_online() if self._get_online else []
        targets = [d for d in online if d != source_device]

        for target in targets:
            req = RelayRequest(
                source_device=source_device,
                target_device=target,
                payload_type=payload_type,
                payload=payload,
                expect_reply=False,
            )
            results[target] = await self.relay(req)

        return results

    async def relay_agent_manifest(
        self, source_device: str, target_device: str, manifest_dict: Dict
    ) -> RelayResult:
        """Agent Manifest 中继 — 从一台设备迁移 Agent 到另一台"""
        from core.agent_manifest import AgentManifest
        manifest = AgentManifest.from_dict(manifest_dict)

        req = RelayRequest(
            source_device=source_device,
            target_device=target_device,
            payload_type="agent_deploy",
            payload={
                "manifest": manifest.to_dict(),
                "checksum": manifest.checksum(),
            },
            expect_reply=True,
            timeout_seconds=60.0,
        )
        return await self.relay(req)

    # ================================================================
    # 接收端回调
    # ================================================================

    async def handle_relay_reply(self, relay_id: str, reply_payload: Dict):
        """处理设备 B 的回复 — 解除等待中的 Future"""
        future = self._reply_futures.get(relay_id)
        if future and not future.done():
            future.set_result(reply_payload)
            logger.info(f"Relay reply received: {relay_id[:8]}")
        else:
            logger.warning(f"Relay reply for unknown/completed relay: {relay_id[:8]}")

    async def handle_relay_request_from_device(
        self, source_device: str, data: Dict
    ) -> RelayResult:
        """
        处理来自设备 A 的 relay_request WS 消息

        这是设备端发起 D2D 通信的入口。
        设备 A 通过 WS 发送 {"type": "relay_request", ...},
        服务端收到后调用此方法转发给设备 B。
        """
        request = RelayRequest(
            relay_id=data.get("relay_id", str(uuid.uuid4())),
            source_device=source_device,
            target_device=data.get("target_device", ""),
            payload_type=data.get("payload_type", "custom"),
            payload=data.get("payload", {}),
            expect_reply=data.get("expect_reply", False),
            timeout_seconds=data.get("timeout_seconds", 30.0),
            chain=data.get("chain", []),
        )

        if not request.target_device:
            return RelayResult(
                relay_id=request.relay_id,
                status=RelayStatus.FAILED,
                source_device=source_device,
                error="target_device is required",
            )

        return await self.relay(request)

    # ================================================================
    # 辅助方法
    # ================================================================

    def _fail(self, request: RelayRequest, error: str, start: float) -> RelayResult:
        self._stats["failed"] += 1
        result = RelayResult(
            relay_id=request.relay_id,
            status=RelayStatus.FAILED,
            source_device=request.source_device,
            target_device=request.target_device,
            error=error,
            latency_ms=(time.time() - start) * 1000,
        )
        self._record(result)
        return result

    def _record(self, result: RelayResult):
        self._relay_history.append(result.to_dict())
        if len(self._relay_history) > 200:
            self._relay_history = self._relay_history[-200:]

    def get_stats(self) -> Dict:
        return {
            **self._stats,
            "pending": len(self._pending_relays),
            "awaiting_reply": len(self._reply_futures),
        }

    def get_history(self, limit: int = 50) -> List[Dict]:
        return self._relay_history[-limit:]


# ============================================================================
# 单例
# ============================================================================

_relay_instance: Optional[ProxyRelay] = None


def get_proxy_relay() -> ProxyRelay:
    global _relay_instance
    if _relay_instance is None:
        _relay_instance = ProxyRelay()
    return _relay_instance
