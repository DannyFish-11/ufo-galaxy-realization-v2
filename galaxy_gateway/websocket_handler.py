"""
WebSocket Handler - WebSocket 连接处理器

处理与 Android Agent 和其他设备的 WebSocket 连接。
所有 incoming 消息通过 :func:`parse_message_strict` 强制要求 AIP v3+
格式后再分发给各处理器。低版本消息会被拒绝并关闭连接。

强制要求：AIP v3.0+（version >= 3.0）；trace_id 和 route_mode 如缺失会被自动注入。

Normalization boundary (PR-5)
------------------------------
After AIP v3+ enforcement, every accepted message is immediately converted to a
:class:`~galaxy_gateway.protocol.normalized_ingress_event.NormalizedIngressEvent`
via :func:`~galaxy_gateway.protocol.normalized_ingress_event.to_normalized_ingress_event`.
Runtime dispatch uses the canonical ``event.kind`` string
(:class:`~galaxy_gateway.protocol.normalized_ingress_event.IngressEventKind`)
and the stable semantic class
(:func:`~galaxy_gateway.protocol.ingress_classifier.classify_ingress_kind`).

Correlation fields ``trace_id``, ``route_mode``, ``correlation_id``, and
``task_id`` are read from the normalized event and propagated into handler
payloads so that no downstream handler needs to rediscover them from raw dicts.

Architectural boundary (PR-10)
-------------------------------
This module is the **local transport state** handler for the gateway layer.
It reflects which WebSocket connections are currently open and routes
incoming messages to the appropriate in-process handlers.

Responsibilities
~~~~~~~~~~~~~~~~
- Accept and close WebSocket connections (device ingress/egress).
- Enforce AIP v3+ protocol framing; auto-inject missing trace_id/route_mode.
- Normalize accepted messages to NormalizedIngressEvent before dispatch.
- Dispatch transport-class messages (register, heartbeat, status, wake, session_migrate).
- **Delegate Android business messages** — identify Android-domain message kinds
  (task_result, goal_execution_result, delegated_execution_signal, handoff_*,
  etc.) and delegate them to :data:`~galaxy_gateway.android_bridge.android_bridge`
  (the canonical Android business ingress) rather than handling them independently.
  This is the PR-03-V2 delegation boundary; see ``ANDROID_INGRESS_DELEGATION_AUTHORITY``.
- Delegate authoritative online/routable state to
  :class:`~core.unified.connection_manager.UnifiedConnectionManager` (UCM).

NOT responsible for
~~~~~~~~~~~~~~~~~~~~
- **Android-specific business dispatch** — Android business messages are
  canonically handled by :class:`~galaxy_gateway.android_bridge.AndroidBridge`.
  This module only identifies and delegates them.
- **Global readiness truth** — whether the full stack is ready to serve requests.
  That is owned by :mod:`core.system_orchestrator`.
- **Entry-mode decisioning** — which mode a session starts in.
  Determined by the canonical orchestration layer in ``core/``.
- **Orchestration eligibility** — whether a device may participate in
  multi-device orchestration.  Assessed by
  :mod:`core.device_selection.canonical_device_selector`.
- **Formation / session truth** — the authoritative set of participating devices.
  Owned by :class:`~core.unified.device_manager.UnifiedDeviceManager` (UDM).

The local ``active_connections`` / ``device_connections`` maps maintained by
:class:`GatewayWSManager` are **operational caches** for connection-id → WebSocket
lookup only.  They do NOT represent canonical device identity or system readiness.

Author: Manus AI
Version: 2.0
Date: 2026-03-07
"""

# ---------------------------------------------------------------------------
# PR-10 transport-layer boundary sentinel
# Importing this sentinel from outside the gateway package signals that the
# import site is consuming transport/routing primitives only — not canonical
# readiness, orchestration eligibility, or formation truth.
# ---------------------------------------------------------------------------
WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY = "WEBSOCKET_HANDLER::TRANSPORT_SUBSTRATE_ONLY"

# ---------------------------------------------------------------------------
# PR-5 ingress normalization authority sentinel
# This sentinel declares that this module enforces the normalization boundary:
# every accepted device message is converted to NormalizedIngressEvent before
# it enters any runtime handler.  Downstream handlers consume the canonical
# event; they must not re-parse raw type strings or AIP version fields.
# ---------------------------------------------------------------------------
INGRESS_NORMALIZATION_AUTHORITY = (
    "WEBSOCKET_HANDLER::INGRESS_NORMALIZED_TO_AIP_V3_CANONICAL_BEFORE_DISPATCH"
)

# ---------------------------------------------------------------------------
# PR-03-V2 Android business ingress delegation authority sentinel
# This sentinel declares that this module delegates all Android-specific
# business messages to android_bridge (the canonical Android ingress) rather
# than independently maintaining a parallel Android dispatch table.
# websocket_handler is responsible for: transport, normalization, delegation.
# It is NOT responsible for Android-specific business dispatch semantics.
# ---------------------------------------------------------------------------
ANDROID_INGRESS_DELEGATION_AUTHORITY = (
    "WEBSOCKET_HANDLER::ANDROID_BUSINESS_MESSAGES_DELEGATED_TO_ANDROID_BRIDGE_CANONICAL_INGRESS"
)

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, FrozenSet, Set
import uuid
from fastapi import WebSocket, WebSocketDisconnect
from galaxy_gateway.device_router import device_router, map_device_type_to_platform
from galaxy_gateway.protocol.compat import parse_message_strict, AIPVersionError
from galaxy_gateway.protocol.aip_v3 import MessageType
from galaxy_gateway.protocol.normalized_ingress_event import (
    IngressEventKind,
    NormalizedIngressEvent,
    from_aip_message as _ingress_event_from_aip,
)
from galaxy_gateway.protocol.ingress_classifier import (
    IngressMessageClass,
    classify_ingress_kind,
)
from galaxy_gateway.ssot import udm_write_register, udm_write_heartbeat, udm_write_unregister

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PR-03-V2: Android business domain kinds
#
# These IngressEventKind values identify Android-specific business messages
# that must be delegated to android_bridge.handle_message() — the single
# canonical Android business ingress.  websocket_handler does NOT maintain
# independent dispatch logic for these kinds; it only identifies and delegates.
#
# Kinds NOT in this set (DEVICE_REGISTER, DEVICE_HEARTBEAT, DEVICE_STATUS,
# WAKE_EVENT, COMMAND) remain handled by websocket_handler as transport-level
# or routing concerns.
# ---------------------------------------------------------------------------
_ANDROID_DOMAIN_KINDS: FrozenSet[str] = frozenset({
    # Task lifecycle results
    IngressEventKind.TASK_RESULT,
    IngressEventKind.COMMAND_RESULT,
    IngressEventKind.PARALLEL_RESULT,
    # Goal execution results
    IngressEventKind.GOAL_EXECUTION_RESULT,
    # Android-initiated control messages
    IngressEventKind.TASK_SUBMIT,
    IngressEventKind.TASK_CANCEL,
    IngressEventKind.GOAL_EXECUTION,
    IngressEventKind.PARALLEL_SUBTASK,
    # Delegated execution lifecycle
    IngressEventKind.DELEGATED_EXECUTION_SIGNAL,
    # Handoff protocol uplink results (PR-02-V2 / PR-03-V2)
    IngressEventKind.HANDOFF_ACK,
    IngressEventKind.HANDOFF_RESULT,
    IngressEventKind.HANDOFF_FAILURE,
    IngressEventKind.HANDOFF_ENVELOPE_V2_RESULT,
    # Capability / diagnostics reporting
    IngressEventKind.CAPABILITY_REPORT,
    IngressEventKind.AGENT_STATUS,
    # P2P mesh overlay
    IngressEventKind.FILE_TRANSFER,
    IngressEventKind.PEER_ANNOUNCE,
    IngressEventKind.PEER_EXCHANGE,
    IngressEventKind.MESH_TOPOLOGY,
})


class GatewayWSManager:
    """WebSocket 连接管理器

    Thin ingress layer: accepts, normalises, and delegates presence ownership
    to :class:`~core.unified.connection_manager.UnifiedConnectionManager` (UCM),
    which is the authoritative runtime presence backbone.

    Local ``active_connections`` / ``device_connections`` maps are kept for
    connection-id → WebSocket lookup (needed because the gateway uses ephemeral
    connection IDs), but online/routable state truth lives in UCM.
    """

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.device_connections: Dict[str, str] = {}  # device_id -> connection_id

    # ------------------------------------------------------------------
    # Internal: lazy UCM accessor (avoids circular import at module load)
    # ------------------------------------------------------------------

    @staticmethod
    def _ucm():
        from core.unified.connection_manager import get_unified_connection_manager
        return get_unified_connection_manager()

    async def connect(self, websocket: WebSocket, connection_id: str):
        """接受新连接"""
        await websocket.accept()
        self.active_connections[connection_id] = websocket
        logger.info(f"✅ WebSocket 连接建立: {connection_id}")

    def disconnect(self, connection_id: str):
        """断开连接"""
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]

            # 注销设备
            device_id = None
            for did, cid in self.device_connections.items():
                if cid == connection_id:
                    device_id = did
                    break

            if device_id:
                # ── SSOT: write-through to UDM FIRST, then clean up local state ──
                # Even if UDM write fails the socket IS gone, so we must still
                # remove the local entry; the warning is logged by the helper.
                udm_write_unregister(device_id)

                # ── Presence backbone: unregister from UCM ──
                try:
                    ucm = self._ucm()
                    loop = None
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        pass
                    if loop is not None and loop.is_running():
                        loop.create_task(ucm.unregister_connection(device_id))
                    else:
                        ucm.mark_offline(device_id)
                except Exception as _ucm_err:
                    logger.debug("UCM unregister on disconnect failed (non-fatal): %s", _ucm_err)

                device_router.unregister_device(device_id)
                del self.device_connections[device_id]

                # COMPAT_MIRROR_WRITE: sync offline state to core compat cache AFTER
                # UDM write (udm_write_unregister already called above).
                # registered_devices is a read-only compat surface — this write
                # is a mirror only; UDM (SSOT) already reflects the offline state.
                try:
                    from core.routes._shared import registered_devices as core_registered_devices
                    if device_id in core_registered_devices:
                        core_registered_devices[device_id]["status"] = "offline"  # COMPAT_MIRROR_WRITE
                        core_registered_devices[device_id]["online"] = False  # COMPAT_MIRROR_WRITE
                except Exception:
                    pass

            logger.info(f"✅ WebSocket 连接断开: {connection_id}")

    async def send_message(self, connection_id: str, message: Dict):
        """发送消息到指定连接"""
        if connection_id in self.active_connections:
            websocket = self.active_connections[connection_id]
            await websocket.send_json(message)

    async def send_to_device(self, device_id: str, message: Dict):
        """发送消息到指定设备 — 委托 UCM 处理（含 fallback 逻辑）。"""
        # Fast path: use local connection_id map for direct send
        connection_id = self.device_connections.get(device_id)
        if connection_id and connection_id in self.active_connections:
            try:
                await self.send_message(connection_id, message)
                return
            except Exception as e:
                logger.warning("GatewayWSManager.send_to_device local send failed, delegating to UCM: %s", e)

        # Delegate to UCM (presence backbone) for fallback / gateway paths
        try:
            await self._ucm().send_to_device(device_id, message)
        except Exception as e:
            logger.error(f"❌ UCM send_to_device failed for {device_id}: {e}")

    def is_device_connected(self, device_id: str) -> bool:
        """Check if a device has an active connection (UCM is authoritative)."""
        if device_id in self.device_connections:
            return True
        return self._ucm().is_device_connected(device_id)

    async def broadcast(self, message: Dict):
        """广播消息到所有连接"""
        for connection_id in list(self.active_connections.keys()):
            try:
                await self.send_message(connection_id, message)
            except Exception as e:
                logger.error(f"❌ 广播消息失败: {e}")

    def get_connected_devices(self) -> list:
        """返回当前本地已连接的设备 ID 列表。"""
        return list(self.device_connections.keys())


# 全局连接管理器
connection_manager = GatewayWSManager()


async def handle_websocket(websocket: WebSocket, connection_id: str):
    """处理 WebSocket 连接"""
    await connection_manager.connect(websocket, connection_id)
    
    try:
        while True:
            # 接收消息
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # 处理消息
            await handle_message(connection_id, message, websocket)
            
    except WebSocketDisconnect:
        logger.info(f"📡 WebSocket 连接断开: {connection_id}")
        connection_manager.disconnect(connection_id)
    except Exception as e:
        logger.error(f"❌ WebSocket 处理异常: {e}")
        connection_manager.disconnect(connection_id)


async def handle_message(connection_id: str, message: Dict, websocket: WebSocket):
    """处理接收到的消息。

    Normalization boundary (PR-5):
    1. :func:`parse_message_strict` enforces AIP v3.0+; rejects lower versions.
    2. The accepted AIPMessage is immediately converted to a
       :class:`~galaxy_gateway.protocol.normalized_ingress_event.NormalizedIngressEvent`
       — this is the canonical internal representation.
    3. Dispatch uses ``event.kind`` (an :class:`IngressEventKind` constant) and
       the stable semantic class from :func:`classify_ingress_kind`.
    4. Correlation fields ``trace_id``, ``route_mode``, ``correlation_id``, and
       ``task_id`` are read from *event* (always non-empty after normalization)
       and propagated into ``aip_msg.payload`` for handler access.
    """
    try:
        if "type" not in message:
            logger.warning("⚠️ 收到缺少 type 字段的消息，已忽略")
            return

        # ── Step 1: enforce AIP v3; inject trace_id/route_mode ──────────────
        try:
            aip_msg = parse_message_strict(message)
        except AIPVersionError as ver_err:
            raw_version = message.get("version", "<missing>")
            logger.warning(
                "AIP version rejected",
                extra={
                    "event": "aip_version_rejected",
                    "raw_version": raw_version,
                    "connection_id": connection_id,
                    "message_type": message.get("type"),
                    "reason": str(ver_err),
                },
            )
            await websocket.send_json({
                "version": "3.0",
                "type": "error",
                "payload": {
                    "error": "protocol_version_rejected",
                    "detail": str(ver_err),
                    "required": "AIP v3.0+",
                    "received": raw_version,
                },
            })
            await websocket.close(code=4000)
            return
        except Exception as parse_err:
            logger.warning(f"⚠️ 消息解析失败（type={message.get('type')}）: {parse_err}")
            return

        # ── Step 2: normalize to canonical NormalizedIngressEvent ────────────
        # This is the PR-5 normalization boundary.  All dispatch below uses
        # event.kind (IngressEventKind) — not raw type strings or MessageType.
        event: NormalizedIngressEvent = _ingress_event_from_aip(aip_msg)

        # ── Step 3: propagate correlation fields from event into aip_msg ─────
        # event.trace_id / route_mode / correlation_id are guaranteed non-empty
        # (or stably defaulted) by the normalization layer.  Write them back
        # into aip_msg.payload so legacy handler code that reads payload fields
        # continues to work without modification.
        aip_msg.payload.setdefault("trace_id", event.trace_id)
        aip_msg.payload.setdefault("route_mode", event.route_mode)
        if event.correlation_id:
            aip_msg.payload.setdefault("correlation_id", event.correlation_id)
        if event.task_id:
            aip_msg.payload.setdefault("task_id", event.task_id)

        msg_class = classify_ingress_kind(event.kind)

        logger.info(
            f"📨 收到消息: kind={event.kind}, class={msg_class}, "
            f"device={event.device_id}, id={event.message_id}, "
            f"trace_id={event.trace_id}, route_mode={event.route_mode}"
        )

        # ── Step 4: dispatch via canonical IngressEventKind ──────────────────
        # Branch on event.kind (stable canonical strings), not raw type values.
        #
        # PR-03-V2: Android business domain messages are DELEGATED to
        # android_bridge (the canonical Android ingress) rather than handled
        # independently here.  Transport-class messages (register, heartbeat,
        # status, wake, command) remain handled by this module.
        if event.kind in _ANDROID_DOMAIN_KINDS:
            # Delegate to android_bridge — the canonical Android business ingress.
            # Pass the original raw message dict; android_bridge normalizes it
            # independently (double-normalisation is idempotent for v3 dicts).
            try:
                from galaxy_gateway.android_bridge import android_bridge as _android_bridge
                bridge_response = await _android_bridge.handle_message(websocket, message)
                if bridge_response:
                    await websocket.send_json(bridge_response)
            except Exception as _bridge_err:
                logger.error(
                    "android_bridge delegation failed: kind=%s error=%s",
                    event.kind, _bridge_err,
                )
        elif event.kind == IngressEventKind.DEVICE_REGISTER:
            await handle_register(connection_id, aip_msg, websocket)
        elif event.kind == IngressEventKind.DEVICE_HEARTBEAT:
            await handle_heartbeat(connection_id, aip_msg)
        elif event.kind == IngressEventKind.COMMAND:
            await handle_command(connection_id, aip_msg)
        elif event.kind == IngressEventKind.DEVICE_STATUS:
            await handle_status(connection_id, aip_msg)
        elif event.kind == IngressEventKind.WAKE_EVENT:
            await handle_wake_event(connection_id, aip_msg)
        else:
            # SESSION_MIGRATE and any future transport-class kinds are handled here
            # by falling through to per-type checks using MessageType for backward
            # compat until those handlers are also migrated.
            if aip_msg.type == MessageType.SESSION_MIGRATE:
                await handle_session_migrate(connection_id, aip_msg)
            else:
                logger.warning(f"⚠️ 未处理的消息类型: kind={event.kind}")
                error_resp = {
                    "version": "3.0",
                    "type": "error",
                    "device_id": event.device_id,
                    "correlation_id": event.message_id,
                    "trace_id": event.trace_id,
                    "payload": {
                        "error": f"Unsupported message kind: {event.kind}",
                        "original_type": event.original_type,
                    },
                }
                await websocket.send_json(error_resp)

    except Exception as e:
        logger.error(f"❌ 消息处理失败: {e}")


async def handle_register(connection_id: str, aip_msg, websocket: WebSocket):
    """处理设备注册（接受 AIPMessage 对象）"""
    try:
        device_id = aip_msg.device_id
        device_info = aip_msg.payload.get("device_info", {})
        device_type_raw = (aip_msg.device_type.value if aip_msg.device_type else None) or device_info.get("device_type", "unknown")
        capabilities = device_info.get("capabilities", [])
        metadata = device_info.get("metadata", {})
        device_name = device_info.get("name", device_info.get("model", f"Device-{device_id[:8]}"))

        # 映射为路由层平台大类
        platform = map_device_type_to_platform(device_type_raw)

        # ── SSOT: write-through to UnifiedDeviceManager FIRST ──
        udm_success = udm_write_register(
            device_id=device_id,
            device_name=device_name,
            device_type_raw=device_type_raw,
            capabilities=capabilities,
            metadata=metadata,
            source="gateway_ws",
        )

        # 注册设备（local gateway router — secondary, only when UDM succeeded）
        success = False
        if udm_success:
            success = device_router.register_device(
                device_id=device_id,
                device_type=platform,
                capabilities=capabilities,
                websocket=websocket,
                metadata=metadata,
            )

            if success:
                connection_manager.device_connections[device_id] = connection_id

                # ── Presence backbone: register with UCM (reconnect-safe) ──
                try:
                    ucm = connection_manager._ucm()
                    if ucm.is_device_connected(device_id):
                        await ucm.reconnect_patch(device_id, websocket, metadata)
                    else:
                        await ucm.register_connection(device_id, websocket, metadata)
                except Exception as _ucm_err:
                    logger.debug("UCM register on handle_register failed (non-fatal): %s", _ucm_err)

                # 同步设备能力到 CapabilityRegistry
                try:
                    from core.routes.devices import _sync_device_to_capability_registry
                    _sync_device_to_capability_registry({
                        "device_id": device_id,
                        "device_type": device_type_raw,
                        "device_name": device_name,
                        "capabilities": capabilities,
                        "metadata": metadata,
                    })
                except Exception as _sync_err:
                    logger.warning(f"WebSocket 设备能力同步到 CapabilityRegistry 失败: {_sync_err}")

        # 发送 AIP v3 注册确认响应
        response = {
            "version": "3.0",
            "message_id": str(uuid.uuid4()),
            "correlation_id": aip_msg.message_id,
            "type": MessageType.DEVICE_REGISTER_ACK.value,
            "device_id": device_id,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "payload": {
                "status": "registered" if success else "failed",
                "message": "设备注册成功" if success else "设备注册失败",
                "registered_at": datetime.now(timezone.utc).isoformat(),
            },
        }

        await websocket.send_json(response)

        # COMPAT_MIRROR_WRITE: update compat cache AFTER UDM write succeeds.
        # registered_devices is a read-only compat surface (SSOT=UDM).
        # This write is a mirror only — truth authority is UDM.
        if success and udm_success:
            try:
                from core.routes._shared import registered_devices as core_registered_devices
                core_registered_devices[device_id] = {  # COMPAT_MIRROR_WRITE
                    "device_id": device_id,
                    "device_type": device_type_raw,
                    "device_name": device_name,
                    "capabilities": capabilities,
                    "os_version": device_info.get("os_version", ""),
                    "registered_at": datetime.now(timezone.utc).isoformat(),
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                    "status": "online",
                    "online": True,
                    "source": "gateway_ws",
                }
            except Exception as sync_err:
                logger.debug(f"同步设备到 core registered_devices 失败: {sync_err}")

        logger.info(f"✅ 设备注册完成: {device_id} (type={device_type_raw}, udm={udm_success})")

    except Exception as e:
        logger.error(f"❌ 处理注册失败: {e}")


async def handle_heartbeat(connection_id: str, aip_msg):
    """处理心跳（接受 AIPMessage 对象）"""
    try:
        device_id = aip_msg.device_id

        # ── SSOT: write-through to UnifiedDeviceManager FIRST ──
        if udm_write_heartbeat(device_id):
            # Update local device state only when UDM write succeeded
            device = device_router.get_device(device_id)
            if device:
                device.last_seen = datetime.now()
                device.status = "online"

        # ── Presence backbone: update UCM heartbeat / last_seen ──
        try:
            connection_manager._ucm().update_heartbeat(device_id)
        except Exception as _ucm_err:
            logger.debug("UCM update_heartbeat failed (non-fatal): %s", _ucm_err)

        # 发送 AIP v3 心跳确认响应
        response = {
            "version": "3.0",
            "message_id": str(uuid.uuid4()),
            "correlation_id": aip_msg.message_id,
            "type": MessageType.DEVICE_HEARTBEAT_ACK.value,
            "device_id": device_id,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "payload": {"status": "ok"},
        }

        await connection_manager.send_message(connection_id, response)

    except Exception as e:
        logger.error(f"❌ 处理心跳失败: {e}")


async def handle_response(connection_id: str, aip_msg):
    """处理任务/命令执行结果（接受 AIPMessage 对象）"""
    try:
        task_id = aip_msg.task_id or aip_msg.correlation_id or aip_msg.message_id
        payload = {"results": [r.model_dump() for r in aip_msg.results], **aip_msg.payload}
        await device_router.handle_task_result(task_id, payload)

        # ── 并行闭环：将子任务结果记录到共享 ParallelGroupTracker ──
        parallel_payload = dict(aip_msg.payload)
        if not parallel_payload.get("group_id") and aip_msg.results:
            # 从 results 列表第一个元素补充并行字段（兼容 AIP v3 results 路径）
            parallel_payload.update(aip_msg.results[0].model_dump())

        try:
            from galaxy_gateway.orchestrator.parallel_tracker import record_parallel_fields
            await record_parallel_fields(parallel_payload)
        except Exception as _pt_err:
            logger.warning("parallel_tracker[A]: record failed: %s", _pt_err)

        logger.info(f"✅ 任务结果已处理: {task_id}")

    except Exception as e:
        logger.error(f"❌ 处理响应失败: {e}")


async def handle_command(connection_id: str, aip_msg):
    """处理命令（设备发起的命令，接受 AIPMessage 对象）"""
    try:
        command_text = aip_msg.payload.get("command", "")
        result = await device_router.route_task(command_text)

        # 发送 AIP v3 命令结果响应
        response = {
            "version": "3.0",
            "message_id": str(uuid.uuid4()),
            "correlation_id": aip_msg.message_id,
            "type": MessageType.COMMAND_RESULT.value,
            "device_id": aip_msg.device_id,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "payload": result,
        }

        await connection_manager.send_message(connection_id, response)

    except Exception as e:
        logger.error(f"❌ 处理命令失败: {e}")


async def handle_status(connection_id: str, aip_msg):
    """处理状态查询（接受 AIPMessage 对象）"""
    try:
        status = device_router.get_device_status()

        response = {
            "version": "3.0",
            "message_id": str(uuid.uuid4()),
            "correlation_id": aip_msg.message_id,
            "type": MessageType.DEVICE_STATUS.value,
            "device_id": aip_msg.device_id,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "payload": status,
        }

        await connection_manager.send_message(connection_id, response)

    except Exception as e:
        logger.error(f"❌ 处理状态查询失败: {e}")


async def push_command_result(request_id: str, status: str, results: Dict):
    """
    推送命令执行结果到所有订阅的 WebSocket 连接
    
    Args:
        request_id: 请求 ID
        status: 命令状态
        results: 执行结果
    """
    message = {
        "type": "command_result",
        "request_id": request_id,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": results
    }
    
    await connection_manager.broadcast(message)
    logger.info(f"✅ 命令结果已推送: request_id={request_id}, status={status}")


async def handle_wake_event(connection_id: str, aip_msg):
    """处理唤醒事件 — 转发给 WakeEventBus 进行去重和路由"""
    try:
        device_id = aip_msg.device_id
        payload = aip_msg.payload

        from galaxy_gateway.wake_event_bus import wake_event_bus

        dispatched = await wake_event_bus.handle_websocket_message(
            device_id,
            {"type": "WAKE_EVENT", "payload": payload},
        )

        # 唤醒同时创建/关联会话
        if dispatched:
            from core.e2e_orchestrator import process_wake_event

            wake_result = await process_wake_event(
                device_id=device_id,
                wake_word=payload.get("wake_word", ""),
                task_type=payload.get("task_type", "general"),
                extra=payload.get("extra", {}),
            )

            # 发送确认响应
            response = {
                "version": "3.0",
                "message_id": str(uuid.uuid4()),
                "correlation_id": aip_msg.message_id,
                "type": "wake_event_ack",
                "device_id": device_id,
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "payload": wake_result,
            }
            await connection_manager.send_message(connection_id, response)

        logger.info(
            f"✅ 唤醒事件已处理: device={device_id} "
            f"dispatched={dispatched}"
        )

    except Exception as e:
        logger.error(f"❌ 处理唤醒事件失败: {e}")


async def handle_session_migrate(connection_id: str, aip_msg):
    """处理会话迁移请求"""
    try:
        device_id = aip_msg.device_id
        payload = aip_msg.payload
        session_id = payload.get("session_id", "")
        target_device_id = payload.get("target_device_id", device_id)

        from galaxy_gateway.session_roaming import session_roaming

        success = await session_roaming.migrate_session(
            session_id, target_device_id
        )

        response = {
            "version": "3.0",
            "message_id": str(uuid.uuid4()),
            "correlation_id": aip_msg.message_id,
            "type": MessageType.SESSION_MIGRATE_ACK.value,
            "device_id": device_id,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "payload": {
                "session_id": session_id,
                "target_device_id": target_device_id,
                "success": success,
            },
        }
        await connection_manager.send_message(connection_id, response)

        logger.info(
            f"✅ 会话迁移{'成功' if success else '失败'}: "
            f"session={session_id} -> device={target_device_id}"
        )

    except Exception as e:
        logger.error(f"❌ 处理会话迁移失败: {e}")
