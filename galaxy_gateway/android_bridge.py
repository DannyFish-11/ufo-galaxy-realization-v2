"""
Android Bridge Service — Android 动作适配器（PR-S4）
=======================================================

架构角色
--------
``AndroidBridge`` 是一个 **Android-specific action / payload 翻译适配器**，
不是独立的 presence 或 dispatch authority。

职责（保留）:
  1. 处理 AIP v3 WebSocket 协议的收发与规范化。
  2. 将服务端任务翻译为 Android 可执行的 AIP 命令（action/payload translation）。
  3. 处理安卓端返回的结果并触发记忆回流。
  4. 维护 WebSocket 连接句柄的 **传输/会话层本地缓存**（transport session cache）。

职责（已移除 — PR-2 / PR-S3 / PR-S4）:
  ✗ 不持有独立的设备 presence 权威（presence authority 在 UDM + UCM）。
  ✗ 不持有独立的任务 dispatch 权威（dispatch authority 在 DeviceRouter）。
  ✗ ``self._devices`` 不是设备事实来源（SSOT 在 UDM）。

模块结构（PR-3 modularization）:
  - galaxy_gateway.android.capabilities  — DeviceCapability
  - galaxy_gateway.android.models        — Rect, UIElement, AndroidDevice
  - galaxy_gateway.android.message_builder — MessageBuilder
  - galaxy_gateway.android.handlers.*   — isolated handler functions

与安卓端 AIPMessageV3.kt 完全对齐。

Author: Galaxy Team
Version: 3.0.0
"""

import asyncio
import logging
import time
import uuid
from typing import Dict, List, Optional, Any, Callable

# =============================================================================
# 模块导入 — 从拆分后的子模块导入（PR-3）
# =============================================================================

# 设备类型 — 单一事实来源
from core.device_types import (  # noqa: E402
    AIPDeviceType as DeviceType,
    DevicePlatform,
)

# 协议枚举 — 单一事实来源
from galaxy_gateway.protocol.aip_v3 import (  # noqa: E402
    MessageType,
    TaskStatus,
    ResultStatus,
)

# 子模块：能力、模型、消息构建器
from galaxy_gateway.android.capabilities import DeviceCapability
from galaxy_gateway.android.models import Rect, UIElement, AndroidDevice
from galaxy_gateway.android.message_builder import MessageBuilder

# 子模块：处理器
from galaxy_gateway.android.handlers.registration import (
    handle_device_register,
    handle_unregistered,
)
from galaxy_gateway.android.handlers.heartbeat import (
    handle_heartbeat,
    handle_device_status,
    handle_agent_ping,
)
from galaxy_gateway.android.handlers.task_lifecycle import (
    handle_task_result,
    handle_task_end,
    handle_task_progress,
    handle_command_result,
    handle_error,
)
from galaxy_gateway.android.handlers.task_submit import (
    handle_task_execute,
    handle_task_submit,
)
from galaxy_gateway.android.handlers.goal_execution import (
    handle_goal_execution,
    handle_parallel_subtask,
    handle_goal_execution_result,
)
from galaxy_gateway.android.handlers.capability_report import handle_capability_report
from galaxy_gateway.android.handlers.diagnostics import handle_diagnostics_payload
from galaxy_gateway.android.handlers.vision import handle_vision_request
from galaxy_gateway.android.handlers.generic import handle_generic_forward

# =============================================================================
# OpenClawd 记忆回流 — 顶层导入使测试可以通过 patch() 注入 mock
# =============================================================================
try:
    from core.openclawd_memory_backflow import store_task_result
except ImportError:
    store_task_result = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# =============================================================================
# Android Bridge 服务
# =============================================================================

class AndroidBridge:
    """
    Android 桥接服务 — transport registration + runtime presence adapter。

    负责管理所有安卓设备的连接、任务分发和结果收集。

    架构角色 (PR-2)
    ---------------
    AndroidBridge 是 **transport/session adapter**，不是独立的设备事实源。

    - 设备注册 / 心跳 / 断联 / 重连的 **canonical 状态写入** 经由
      ``UnifiedDeviceManager`` (UDM) 完成，UDM 是唯一的写入 SSOT。
    - ``self._devices`` 仅保留为 **transport/session operational cache**，
      用于维护 WebSocket 连接句柄与轻量级连接态，不再充当主设备注册表。
    - 所有外部代码若需要权威设备状态，应查询 UDM，而非直接读取 ``_devices``。

    模块结构 (PR-3)
    ---------------
    handler 逻辑已拆分到 ``galaxy_gateway.android.handlers.*`` 子包；
    此类仅保留 transport/session cache、UDM 辅助方法和消息分发逻辑。
    """

    def __init__(self):
        # transport/session operational cache — NOT the canonical device registry.
        self._devices: Dict[str, AndroidDevice] = {}
        self._pending_responses: Dict[str, asyncio.Future] = {}
        self._message_handlers: Dict[MessageType, Callable] = {}
        self._lock = asyncio.Lock()

        # 注册默认处理器
        self._register_default_handlers()

        logger.info("AndroidBridge initialized")

    # =========================================================================
    # UDM canonical write/patch helpers (PR-2)
    # =========================================================================

    def _write_registration_to_udm(self, device_id: str, message: Dict[str, Any]) -> None:
        """Write canonical device identity/state to UnifiedDeviceManager on registration."""
        try:
            from core.unified.device_manager import UnifiedDeviceManager
            from core.unified.models import UnifiedDevice, UnifiedDeviceType

            udm = UnifiedDeviceManager()

            raw_caps = message.get("capabilities", 0)
            if isinstance(raw_caps, int):
                caps_list = DeviceCapability.to_list(raw_caps)
            elif isinstance(raw_caps, (list, tuple)):
                caps_list = [str(c) for c in raw_caps]
            else:
                caps_list = []

            raw_device_type = str(message.get("device_type", "android_phone")).lower()
            try:
                utype = UnifiedDeviceType(raw_device_type)
            except ValueError:
                utype = UnifiedDeviceType.ANDROID

            metadata = {
                "model": message.get("model", ""),
                "os_version": message.get("os_version", ""),
                "sdk_version": message.get("sdk_version"),
                "screen_width": message.get("screen_width"),
                "screen_height": message.get("screen_height"),
                "platform": message.get("platform", "android"),
                "app_version": message.get("app_version", ""),
            }
            metadata = {k: v for k, v in metadata.items() if v is not None}

            device = UnifiedDevice(
                device_id=device_id,
                device_name=str(message.get("name") or "Android Device"),
                device_type=utype,
                capabilities=caps_list,
                metadata=metadata,
                source="android_bridge",
            )
            udm.register_device(device)
            logger.info(
                "android_bridge: wrote registration to UDM (SSOT): device_id=%s",
                device_id,
                extra={"event": "android_bridge_udm_register", "device_id": device_id},
            )
        except Exception as exc:
            logger.warning(
                "android_bridge: UDM registration write failed (non-fatal): device_id=%s error=%s",
                device_id, exc,
            )

    def _patch_runtime_state_to_udm(
        self,
        device_id: str,
        patch: Dict[str, Any],
        source: str = "android_bridge",
    ) -> None:
        """Patch canonical runtime state in UnifiedDeviceManager."""
        try:
            from core.unified.device_manager import UnifiedDeviceManager
            udm = UnifiedDeviceManager()
            result = udm.upsert_device_state(device_id, patch, source=source)
            if result is None:
                logger.debug(
                    "android_bridge: _patch_runtime_state_to_udm: device not in UDM yet, skipping: %s",
                    device_id,
                )
        except Exception as exc:
            logger.warning(
                "android_bridge: UDM state patch failed (non-fatal): device_id=%s error=%s",
                device_id, exc,
            )

    def _patch_heartbeat_to_udm(self, device_id: str) -> None:
        """Record heartbeat in UDM canonical state (updates last_heartbeat + keeps ONLINE)."""
        try:
            from core.unified.device_manager import UnifiedDeviceManager
            UnifiedDeviceManager().heartbeat(device_id)
        except Exception as exc:
            logger.debug(
                "android_bridge: UDM heartbeat patch failed (non-fatal): device_id=%s error=%s",
                device_id, exc,
            )

        try:
            from core.unified.connection_manager import get_unified_connection_manager
            get_unified_connection_manager().update_heartbeat(device_id)
        except Exception as exc:
            logger.debug(
                "android_bridge: UCM heartbeat patch failed (non-fatal): device_id=%s error=%s",
                device_id, exc,
            )

    def _patch_disconnect_to_udm(self, device_id: str) -> None:
        """Mark device as DISCONNECTED in UDM without removing canonical identity."""
        self._patch_runtime_state_to_udm(
            device_id,
            {"status": "disconnected"},
            source="android_bridge_disconnect",
        )

        try:
            from core.unified.connection_manager import get_unified_connection_manager
            get_unified_connection_manager().mark_offline(device_id)
        except Exception as exc:
            logger.debug(
                "android_bridge: UCM mark_offline failed (non-fatal): device_id=%s error=%s",
                device_id, exc,
            )

    def _patch_reconnect_to_udm(self, device_id: str) -> None:
        """Mark device as ONLINE in UDM on reconnect (no duplicate identity created)."""
        self._patch_runtime_state_to_udm(
            device_id,
            {"status": "online"},
            source="android_bridge_reconnect",
        )

        try:
            from core.unified.connection_manager import get_unified_connection_manager
            ucm = get_unified_connection_manager()
            ucm.update_heartbeat(device_id)
        except Exception as exc:
            logger.debug(
                "android_bridge: UCM reconnect patch failed (non-fatal): device_id=%s error=%s",
                device_id, exc,
            )

    # ─────────────────────────────────────────────────────────────────────────
    #  设备 Fan-out 辅助方法（PARALLEL_SUBTASK / 多设备协作）
    # ─────────────────────────────────────────────────────────────────────────

    async def _fan_out_task_assign(
        self,
        task_id: str,
        task_type: str,
        goal: str,
        device_ids: List[str],
        session_id: str,
        trace_id: str,
        max_steps: int = 10,
        constraints: Optional[List[str]] = None,
        group_id: Optional[str] = None,
        require_local_agent: bool = True,
    ) -> Dict[str, Any]:
        """将 task_assign 扇出（fan-out）到多台设备。"""
        constraints = constraints or []
        results: Dict[str, Any] = {"fanout": 0, "failed": 0, "device_ids": [], "errors": []}

        try:
            from core.unified.connection_manager import get_unified_connection_manager
            ucm = get_unified_connection_manager()
        except Exception as ucm_err:
            logger.warning(
                "PARALLEL_SUBTASK fan-out: UCM 不可用，跳过 fan-out | error=%s", ucm_err,
            )
            return {"fanout": 0, "failed": len(device_ids), "device_ids": [], "errors": [str(ucm_err)]}

        target_device_ids = device_ids

        for idx, did in enumerate(device_ids):
            try:
                task_assign_payload: Dict[str, Any] = {
                    "task_id": task_id,
                    "goal": goal,
                    "constraints": constraints,
                    "max_steps": max_steps,
                    "require_local_agent": require_local_agent,
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "runtime_session_id": trace_id,
                    "success": True,
                    "group_id": group_id,
                    "subtask_index": idx,
                    "device_ids": target_device_ids,
                }

                msg = MessageBuilder.task_assign(
                    device_id=did,
                    task_id=task_id,
                    task_type=task_type,
                    payload=task_assign_payload,
                )
                msg["trace_id"] = trace_id
                msg["session_id"] = session_id

                sent = await ucm.send_to_device(did, msg)
                if sent:
                    results["fanout"] += 1
                    results["device_ids"].append(did)
                    logger.debug(
                        "PARALLEL_SUBTASK fan-out → device_id=%s subtask_index=%s", did, idx,
                    )
                else:
                    results["failed"] += 1
                    results["errors"].append(f"device {did}: WebSocket not connected")

            except Exception as fan_err:
                results["failed"] += 1
                results["errors"].append(f"device {did}: {fan_err}")
                logger.warning(
                    "PARALLEL_SUBTASK fan-out → device_id=%s failed: %s", did, fan_err,
                )

        logger.info(
            "PARALLEL_SUBTASK fan-out 完成: fanout=%s failed=%s total=%s",
            results["fanout"], results["failed"], len(device_ids),
        )
        return results

    # =========================================================================
    # Handler registration and dispatch
    # =========================================================================

    def _register_default_handlers(self):
        """注册默认消息处理器，将消息类型映射到对应的处理函数。"""

        def _wrap(fn):
            """Wrap a standalone handler function as a bound-style coroutine."""
            async def _bound(websocket, message):
                return await fn(self, websocket, message)
            return _bound

        self._message_handlers[MessageType.DEVICE_REGISTER] = _wrap(handle_device_register)
        self._message_handlers[MessageType.DEVICE_HEARTBEAT] = _wrap(handle_heartbeat)
        self._message_handlers[MessageType.TASK_RESULT] = _wrap(handle_task_result)
        self._message_handlers[MessageType.TASK_PROGRESS] = _wrap(handle_task_progress)
        self._message_handlers[MessageType.COMMAND_RESULT] = _wrap(handle_command_result)
        self._message_handlers[MessageType.ERROR] = _wrap(handle_error)

        # AgentMessageHandler.kt 对齐类型
        self._message_handlers[MessageType.TASK_EXECUTE] = _wrap(handle_task_execute)
        self._message_handlers[MessageType.TASK_SUBMIT] = _wrap(handle_task_submit)
        self._message_handlers[MessageType.GOAL_EXECUTION] = _wrap(handle_goal_execution)
        self._message_handlers[MessageType.PARALLEL_SUBTASK] = _wrap(handle_parallel_subtask)
        self._message_handlers[MessageType.GOAL_EXECUTION_RESULT] = _wrap(handle_goal_execution_result)
        self._message_handlers[MessageType.TASK_CANCEL] = _wrap(handle_generic_forward)
        self._message_handlers[MessageType.TASK_STATUS] = _wrap(handle_generic_forward)
        self._message_handlers[MessageType.AGENT_PING] = _wrap(handle_agent_ping)
        self._message_handlers[MessageType.AGENT_CONFIG_UPDATE] = _wrap(handle_generic_forward)
        self._message_handlers[MessageType.AGENT_RESTART] = _wrap(handle_generic_forward)
        self._message_handlers[MessageType.UI_TREE_REQUEST] = _wrap(handle_generic_forward)
        self._message_handlers[MessageType.ACTION_EXECUTE] = _wrap(handle_generic_forward)
        self._message_handlers[MessageType.ACTION_SEQUENCE_EXECUTE] = _wrap(handle_generic_forward)
        self._message_handlers[MessageType.APP_START] = _wrap(handle_generic_forward)
        self._message_handlers[MessageType.APP_STOP] = _wrap(handle_generic_forward)
        self._message_handlers[MessageType.SYSTEM_COMMAND] = _wrap(handle_generic_forward)

        # 设备状态上报
        self._message_handlers[MessageType.DEVICE_STATUS] = _wrap(handle_device_status)

        # 任务生命周期：task_end 结束确认
        self._message_handlers[MessageType.TASK_END] = _wrap(handle_task_end)

        # 能力/诊断上报
        self._message_handlers[MessageType.CAPABILITY_REPORT] = _wrap(handle_capability_report)
        self._message_handlers[MessageType.DIAGNOSTICS_PAYLOAD] = _wrap(handle_diagnostics_payload)

        # 视觉请求
        self._message_handlers[MessageType.VISION_REQUEST] = _wrap(handle_vision_request)

        # Catch-all: 为所有未注册的消息类型添加通用日志处理器
        for msg_type in MessageType:
            if msg_type not in self._message_handlers:
                self._message_handlers[msg_type] = _wrap(handle_unregistered)

    # Fields that are hard requirements
    _V3_MANDATORY_FIELDS: tuple = ("type", "device_id")

    # Fields auto-generated for backward compatibility when absent
    _V3_AUTO_FILL_FIELDS: tuple = ("version", "timestamp", "message_id")

    async def handle_message(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理来自安卓设备的消息。

        验证流程：
        1. 通过 compat 层将所有协议版本规范化为 AIP v3 dict。
        2. 检查强制字段（type、device_id）。
        3. 派发到对应处理器。
        """
        device_id_pre = message.get("device_id", "unknown") if isinstance(message, dict) else "unknown"
        try:
            from galaxy_gateway.protocol.compat import normalise_to_v3_dict
            message = normalise_to_v3_dict(message)
        except Exception as norm_err:
            logger.warning(
                "android_bridge: failed to normalise message via compat: %s", norm_err,
                extra={
                    "event": "aip_normalise_error",
                    "device_id": device_id_pre,
                    "reason": str(norm_err),
                },
            )
            return MessageBuilder.error(
                device_id_pre,
                "PROTOCOL_PARSE_ERROR",
                f"Failed to parse message: {norm_err}",
                details={"reason": str(norm_err)},
            )

        device_id = message.get("device_id")
        msg_type_str = message.get("type")

        missing = [f for f in self._V3_MANDATORY_FIELDS if not message.get(f)]
        if missing:
            logger.warning(
                "handle_message: malformed message from %s — missing required fields: %s",
                device_id or "unknown",
                missing,
            )
            return MessageBuilder.error(
                device_id or "unknown",
                "MISSING_REQUIRED_FIELDS",
                f"AIP v3.0 required fields missing: {missing}",
                details={"missing_fields": missing, "received_type": msg_type_str},
            )

        try:
            msg_type = MessageType(msg_type_str)
        except ValueError:
            logger.warning("Unknown message type: %s", msg_type_str)
            return MessageBuilder.error(
                device_id or "unknown",
                "UNKNOWN_MESSAGE_TYPE",
                f"Unknown message type: {msg_type_str}",
            )

        handler = self._message_handlers.get(msg_type)
        if handler:
            response = await handler(websocket, message)
            # Propagate trace_id/route_mode into the response
            if response and isinstance(response, dict):
                trace_id = message.get("trace_id", "")
                route_mode = message.get("route_mode", "")
                resp_payload = response.get("payload")
                if isinstance(resp_payload, dict):
                    if trace_id:
                        resp_payload.setdefault("trace_id", trace_id)
                    if route_mode:
                        resp_payload.setdefault("route_mode", route_mode)
            return response
        else:
            logger.debug("No handler for message type: %s", msg_type)
            return None

    # =========================================================================
    # 公共 API
    # =========================================================================

    async def send_to_device(self, device_id: str, message: Dict[str, Any],
                             wait_response: bool = False,
                             timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """发送消息到设备"""
        async with self._lock:
            device = self._devices.get(device_id)

        if not device or not device.connected:
            logger.warning("Device not connected: %s", device_id)
            return None

        try:
            await device.websocket.send_json(message)

            if wait_response:
                message_id = message.get("message_id") or message.get("task_id")
                future = asyncio.get_event_loop().create_future()
                self._pending_responses[message_id] = future

                try:
                    return await asyncio.wait_for(future, timeout=timeout)
                except asyncio.TimeoutError:
                    self._pending_responses.pop(message_id, None)
                    logger.warning("Response timeout for message: %s", message_id)
                    return None

            return {"success": True}

        except Exception as e:
            logger.error("Failed to send message to %s: %s", device_id, e)
            return None

    async def click(self, device_id: str, x: int, y: int,
                    element_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Android GUI action adapter — translate click to AIP protocol and send."""
        msg = MessageBuilder.gui_click(device_id, x, y, element_id)
        return await self.send_to_device(device_id, msg, wait_response=True)

    async def swipe(self, device_id: str, start_x: int, start_y: int,
                    end_x: int, end_y: int, duration_ms: int = 300) -> Optional[Dict[str, Any]]:
        """Android GUI action adapter — translate swipe to AIP protocol and send."""
        msg = MessageBuilder.gui_swipe(device_id, start_x, start_y, end_x, end_y, duration_ms)
        return await self.send_to_device(device_id, msg, wait_response=True)

    async def input_text(self, device_id: str, text: str,
                         element_id: Optional[str] = None,
                         clear_first: bool = False) -> Optional[Dict[str, Any]]:
        """Android GUI action adapter — translate text input to AIP protocol and send."""
        msg = MessageBuilder.gui_input(device_id, text, element_id, clear_first)
        return await self.send_to_device(device_id, msg, wait_response=True)

    async def screenshot(self, device_id: str, quality: int = 80,
                         scale: float = 1.0) -> Optional[Dict[str, Any]]:
        """Android GUI action adapter — translate screenshot request to AIP protocol and send."""
        msg = MessageBuilder.gui_screenshot(device_id, quality, scale)
        return await self.send_to_device(device_id, msg, wait_response=True, timeout=60.0)

    async def query_elements(self, device_id: str,
                             text: Optional[str] = None,
                             class_name: Optional[str] = None,
                             view_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Android GUI action adapter — translate element query to AIP protocol and send."""
        msg = MessageBuilder.gui_element_query(device_id, text, class_name, view_id)
        return await self.send_to_device(device_id, msg, wait_response=True)

    async def assign_task(self, device_id: str, task_id: str, task_type: str,
                          payload: Dict[str, Any], priority: int = 5,
                          timeout: int = 300) -> Optional[Dict[str, Any]]:
        """分配任务到设备 — delegates dispatch authority to DeviceRouter (PR-S3)."""
        async with self._lock:
            if device_id in self._devices:
                self._devices[device_id].current_task_id = task_id

        try:
            from galaxy_gateway.device_router import device_router as _device_router
            router_device = _device_router.devices.get(device_id)
            if router_device is not None:
                task_dict = {
                    "task_id": task_id,
                    "payload": {
                        "task_type": task_type,
                        "priority": priority,
                        **payload,
                    },
                }
                return await _device_router.dispatch_task(task_dict, router_device)
        except Exception as _router_err:
            logger.warning(
                "AndroidBridge.assign_task: DeviceRouter dispatch failed, "
                "falling back to send_to_device — %s", _router_err
            )

        msg = MessageBuilder.task_assign(device_id, task_id, task_type, payload, priority, timeout)
        return await self.send_to_device(device_id, msg, wait_response=True, timeout=float(timeout))

    def get_device(self, device_id: str) -> Optional[AndroidDevice]:
        """获取设备的传输/会话层缓存条目（transport cache view）."""
        return self._devices.get(device_id)

    def get_all_devices(self) -> List[AndroidDevice]:
        """获取所有设备的传输/会话层缓存列表（transport cache view）."""
        return list(self._devices.values())

    def get_connected_devices(self) -> List[AndroidDevice]:
        """获取已连接设备的传输/会话层缓存列表（transport cache view）."""
        return [d for d in self._devices.values() if d.connected]

    def get_android_devices(self) -> List[AndroidDevice]:
        """获取 Android 平台设备的传输/会话层缓存列表（transport cache view）."""
        return [d for d in self._devices.values()
                if d.platform == DevicePlatform.ANDROID and d.connected]

    async def disconnect_device(self, device_id: str):
        """断开设备连接。"""
        self._patch_disconnect_to_udm(device_id)

        async with self._lock:
            if device_id in self._devices:
                self._devices[device_id].connected = False
                self._devices[device_id].websocket = None
                logger.info("Device disconnected: %s", device_id)

    async def cleanup_stale_devices(self, timeout_seconds: float = 120.0):
        """清理超时的设备"""
        current_time = time.time()
        stale_devices = []

        async with self._lock:
            for device_id, device in self._devices.items():
                if device.connected and (current_time - device.last_heartbeat) > timeout_seconds:
                    stale_devices.append(device_id)

        for device_id in stale_devices:
            await self.disconnect_device(device_id)
            logger.warning("Device timed out: %s", device_id)

    async def reconnect_device(self, device_id: str, websocket: Any) -> bool:
        """重新连接设备（WebSocket 断线重连时调用）."""
        async with self._lock:
            device = self._devices.get(device_id)
            if device is None:
                logger.warning("重连失败: 设备 %s 未曾注册", device_id)
                return False
            device.websocket = websocket
            device.connected = True
            device.last_heartbeat = time.time()

        self._patch_reconnect_to_udm(device_id)

        logger.info("设备重连成功: %s", device_id)
        return True

    def get_device_health(self) -> Dict[str, Any]:
        """获取所有设备的健康状态摘要（transport cache view）."""
        now = time.time()
        healthy = 0
        stale = 0
        disconnected = 0
        device_details = []
        for d in self._devices.values():
            if not d.connected:
                disconnected += 1
                status = "disconnected"
            elif now - d.last_heartbeat > 60:
                stale += 1
                status = "stale"
            else:
                healthy += 1
                status = "healthy"
            device_details.append({
                "device_id": d.device_id,
                "model": d.model,
                "status": status,
                "last_heartbeat_ago_s": round(now - d.last_heartbeat, 1) if d.last_heartbeat else None,
            })
        return {
            "total": len(self._devices),
            "healthy": healthy,
            "stale": stale,
            "disconnected": disconnected,
            "devices": device_details,
        }

    # =========================================================================
    # Backward-compatible _handle_* method wrappers (PR-3)
    # These preserve the old method-based API for tests and any callers that
    # invoke _handle_* directly on the AndroidBridge instance.
    # =========================================================================

    async def _handle_device_register(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_device_register(self, websocket, message)

    async def _handle_heartbeat(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_heartbeat(self, websocket, message)

    async def _handle_device_status(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_device_status(self, websocket, message)

    async def _handle_agent_ping(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_agent_ping(self, websocket, message)

    async def _handle_task_result(self, websocket: Any, message: Dict[str, Any]) -> None:
        return await handle_task_result(self, websocket, message)

    async def _handle_task_end(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_task_end(self, websocket, message)

    async def _handle_task_progress(self, websocket: Any, message: Dict[str, Any]) -> None:
        return await handle_task_progress(self, websocket, message)

    async def _handle_command_result(self, websocket: Any, message: Dict[str, Any]) -> None:
        return await handle_command_result(self, websocket, message)

    async def _handle_error(self, websocket: Any, message: Dict[str, Any]) -> None:
        return await handle_error(self, websocket, message)

    async def _handle_task_execute(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return await handle_task_execute(self, websocket, message)

    async def _handle_task_submit(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return await handle_task_submit(self, websocket, message)

    async def _handle_goal_execution(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return await handle_goal_execution(self, websocket, message)

    async def _handle_parallel_subtask(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return await handle_parallel_subtask(self, websocket, message)

    async def _handle_goal_execution_result(self, websocket: Any, message: Dict[str, Any]) -> None:
        return await handle_goal_execution_result(self, websocket, message)

    async def _handle_capability_report(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_capability_report(self, websocket, message)

    async def _handle_diagnostics_payload(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_diagnostics_payload(self, websocket, message)

    async def _handle_vision_request(self, websocket: Any, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return await handle_vision_request(self, websocket, message)

    async def _handle_generic_forward(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_generic_forward(self, websocket, message)

    async def _handle_unregistered(self, websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
        return await handle_unregistered(self, websocket, message)


# =============================================================================
# 全局实例
# =============================================================================

android_bridge = AndroidBridge()
