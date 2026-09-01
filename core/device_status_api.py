# -*- coding: utf-8 -*-
"""
Galaxy - 设备状态统一管理层 API
====================================

**Architecture role: Presentation / projection layer (NOT a canonical truth source).**

``DeviceStatusManager`` is a *UI-facing presentation layer* that maintains
a rich hardware-state view (camera, Bluetooth, GPS, battery, …) for the
WebSocket push / REST endpoints consumed by the dashboard UI.

Canonical authority chain::

    UnifiedDeviceManager (UDM) — canonical SSOT for device registration / status
    ↑
    DeviceStatusManager         — UI presentation layer; writes canonical state
                                  to UDM first, then updates the local rich view

All ``register_device`` and ``unregister_device`` mutations write to UDM
**first** via the ``galaxy_gateway.ssot`` helpers before updating the local
``DeviceState`` cache.  ``DeviceState`` carries presentation-only fields
(hardware sensors, node counts, …) that UDM does not model, so the local
cache is kept as a projection supplement.

功能：
1. 统一管理所有设备的状态信息（UI 展示层）
2. 提供 RESTful API 供 UI 调用
3. 支持 WebSocket 实时推送状态更新
4. 与节点系统和 Device Agent 集成

作者：Manus AI
日期：2026-02-06
版本：2.0 (authority model clarified)
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 本模块**既是库也是脚本**(见文件末尾的 __main__ 守卫,CI 里就是
# `python core/device_status_api.py` 这么跑的)。直接跑时 sys.path[0] 是
# core/ 而不是仓库根,`from core import ...` 会 ModuleNotFoundError。
# 这里把仓库根补进去 —— 只在"没有包上下文"(即被当脚本跑)时补,正常 import 不受影响。
if __package__ in (None, ""):  # pragma: no cover - 只在直接执行时成立
    import os as _os
    import sys as _sys

    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

from core import upper_ports
from core.status_ws_envelope import build_status_frame
from nodes.common.cors_config import get_cors_origins

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# 数据模型
# ============================================================================


class DeviceCategory(str, Enum):
    """设备类别"""

    MOBILE = "mobile"  # 移动设备（Android、iOS）
    DESKTOP = "desktop"  # 桌面设备（Windows、macOS、Linux）
    IOT = "iot"  # 物联网设备
    PERIPHERAL = "peripheral"  # 外设（摄像头、串口等）
    NETWORK = "network"  # 网络设备
    CUSTOM = "custom"  # 自定义设备


@dataclass
class HardwareStatus:
    """硬件状态"""

    # 摄像头
    camera_available: bool = False
    camera_front: bool = False
    camera_back: bool = False
    camera_in_use: bool = False

    # 蓝牙
    bluetooth_supported: bool = False
    bluetooth_enabled: bool = False
    bluetooth_connected_devices: List[str] = field(default_factory=list)

    # NFC
    nfc_supported: bool = False
    nfc_enabled: bool = False

    # 音频
    microphone_available: bool = False
    speaker_available: bool = False
    audio_volume: int = 0
    audio_muted: bool = False

    # 网络
    wifi_connected: bool = False
    wifi_ssid: Optional[str] = None
    wifi_signal: int = 0
    mobile_data_connected: bool = False

    # 电池
    battery_level: int = 0
    battery_charging: bool = False

    # 传感器
    has_accelerometer: bool = False
    has_gyroscope: bool = False
    has_gps: bool = False

    # 串口/USB
    serial_ports: List[str] = field(default_factory=list)
    usb_devices: List[str] = field(default_factory=list)


@dataclass
class DeviceState:
    """设备状态"""

    device_id: str
    device_name: str
    device_type: str
    category: DeviceCategory

    # 连接状态
    is_online: bool = False
    is_connected_to_server: bool = False
    last_heartbeat: Optional[str] = None

    # 硬件状态
    hardware: HardwareStatus = field(default_factory=HardwareStatus)

    # 节点状态
    active_nodes: int = 0
    total_nodes: int = 0
    node_health: float = 100.0

    # 系统信息
    os_version: str = ""
    app_version: str = ""
    ip_address: str = ""

    # 扩展数据
    extra_data: Dict[str, Any] = field(default_factory=dict)

    def touch_heartbeat(self, ts: "Optional[str]" = None) -> None:
        """本地设备状态视图的心跳时间戳规范写口(专项③ ssot-udm-conformance)。

        权威心跳由 UnifiedDeviceManager 维护;此处仅更新本地状态视图,
        禁止外部直接对 ``.last_heartbeat`` 赋值绕过 SSOT UDM 写路径审计门。
        """
        self.last_heartbeat = ts if ts is not None else datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["category"] = self.category.value
        return result


# ============================================================================
# 设备状态管理器
# ============================================================================


class DeviceStatusManager:
    """设备状态管理器"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._devices: Dict[str, DeviceState] = {}
        self._websocket_clients: Set[WebSocket] = set()
        self._status_history: Dict[str, List[Dict[str, Any]]] = {}
        self._initialized = True

        logger.info("DeviceStatusManager initialized")

    def register_device(self, device_state: DeviceState) -> bool:
        """注册设备。

        Writes canonical state to UDM SSOT first, then updates the local
        rich ``DeviceState`` cache used for UI presentation.
        """
        # --- Canonical write to UDM SSOT ---
        self._udm_write_register(device_state)

        self._devices[device_state.device_id] = device_state
        self._status_history[device_state.device_id] = []
        logger.info(f"Device registered: {device_state.device_id} ({device_state.device_name})")
        from core.task_utils import create_tracked_task

        create_tracked_task(
            self._broadcast_update("device_registered", device_state.to_dict()), name="broadcast_device_registered"
        )
        return True

    def unregister_device(self, device_id: str) -> bool:
        """注销设备。

        Writes canonical offline state to UDM SSOT first, then removes from
        the local rich cache.
        """
        # --- Canonical write to UDM SSOT ---
        self._udm_write_unregister(device_id)

        if device_id in self._devices:
            self._devices.pop(device_id)
            self._status_history.pop(device_id, None)
            logger.info(f"Device unregistered: {device_id}")
            from core.task_utils import create_tracked_task

            create_tracked_task(
                self._broadcast_update("device_unregistered", {"device_id": device_id}),
                name="broadcast_device_unregistered",
            )
            return True
        return False

    # ------------------------------------------------------------------
    # UDM write-through helpers (private)
    # ------------------------------------------------------------------

    @staticmethod
    def _udm_write_register(device_state: "DeviceState") -> None:
        """Write device registration to UDM SSOT (best-effort, never raises)."""
        try:
            udm_write_register = upper_ports.resolve("gateway.ssot.udm_write_register")

            # Extract capability list from hardware fields where available.
            hw = device_state.hardware
            caps: list = []
            if getattr(hw, "camera_available", False):
                caps.append("camera")
            if getattr(hw, "microphone_available", False):
                caps.append("microphone")
            if getattr(hw, "bluetooth_supported", False):
                caps.append("bluetooth")
            if getattr(hw, "nfc_supported", False):
                caps.append("nfc")
            if getattr(hw, "has_gps", False):
                caps.append("gps")
            udm_write_register(
                device_id=device_state.device_id,
                device_name=device_state.device_name,
                device_type_raw=device_state.device_type,
                capabilities=caps,
                metadata={
                    "ip_address": device_state.ip_address,
                    "os_version": device_state.os_version,
                    "app_version": device_state.app_version,
                    "category": (
                        device_state.category.value
                        if hasattr(device_state.category, "value")
                        else str(device_state.category)
                    ),
                },
                source="device_status_api",
            )
        except Exception as exc:
            logger.warning(
                "DeviceStatusManager: UDM write failed for device %s — "
                "local status cache updated in degraded mode. error=%s",
                device_state.device_id,
                exc,
            )

    @staticmethod
    def _udm_write_unregister(device_id: str) -> None:
        """Write device offline/unregister to UDM SSOT (best-effort, never raises)."""
        try:
            udm_write_unregister = upper_ports.resolve("gateway.ssot.udm_write_unregister")

            udm_write_unregister(device_id)
        except Exception as exc:
            logger.warning(
                "DeviceStatusManager: UDM unregister write failed for device %s — "
                "local cache removed in degraded mode. error=%s",
                device_id,
                exc,
            )

    def update_device_status(self, device_id: str, status_update: Dict[str, Any]) -> bool:
        """更新设备状态"""
        if device_id not in self._devices:
            return False

        device = self._devices[device_id]

        # 更新硬件状态
        if "hardware" in status_update:
            hw = status_update["hardware"]
            for key, value in hw.items():
                if hasattr(device.hardware, key):
                    setattr(device.hardware, key, value)

        # 更新其他字段
        for key in [
            "is_online",
            "is_connected_to_server",
            "active_nodes",
            "total_nodes",
            "node_health",
            "os_version",
            "app_version",
            "ip_address",
        ]:
            if key in status_update:
                setattr(device, key, status_update[key])

        # 更新心跳时间
        device.touch_heartbeat()

        # 更新扩展数据
        if "extra_data" in status_update:
            device.extra_data.update(status_update["extra_data"])

        # 记录历史
        self._record_history(device_id, device.to_dict())

        # 广播更新
        from core.task_utils import create_tracked_task

        create_tracked_task(
            self._broadcast_update("device_status_updated", device.to_dict()), name="broadcast_device_status"
        )

        return True

    #: UDM 状态里表示"这台设备当前不在线"的取值。
    #: 只列**离线**侧:``UnifiedDeviceStatus`` 将来加新值时,默认应当保持本地
    #: 判断而不是被一个写死的白名单悄悄判成离线。
    _UDM_OFFLINE_STATUSES = frozenset({"offline", "error", "disconnected"})

    def _apply_udm_truth(self) -> None:
        """把 UDM(SSOT)的在线状态刷进本地缓存,在**每次读之前**调用。

        这个类的写路径早就 write-through 到 UDM 了(``register_device`` /
        ``update_device_status`` 都先写 SSOT),但**读路径从来没问过 UDM** ——
        于是 :8766 这个面板要查的 HTTP 接口会把 UDM 明知已离线的设备继续报成
        在线。文件头与 ``core/unified/device_manager.py:22`` 都写着本模块是
        "compatibility layer,不得作为平行真相源",写路径遵守了,读路径没有。

        做法与 ``core.device_registry.list_devices`` 保持一致(那边已经这么做了,
        这里复用同一套路,不另起炉灶):遍历本地缓存,凡是 UDM 里有记录的,就用
        UDM 的状态覆盖本地 ``is_online``。

        判据同样是**只覆盖、不臆造**:

        * UDM 里有记录 → 以 UDM 为准(在线/离线都听它的);
        * UDM 里**查不到**这台设备 → 保持本地值。write-through 是 best-effort
          (UDM 写失败时仍保留本地记录以维持展示),这时把它改成离线等于凭空
          制造一条假信息;
        * UDM 不可用 → 整体跳过,保持本地值。展示面不该因为 SSOT 抖动而全空。
        """
        try:
            from core.unified.device_manager import get_unified_device_manager

            udm = get_unified_device_manager()
        except Exception as exc:  # pragma: no cover - UDM 不可用是降级路径
            logger.debug("device_status_api: UDM 不可用,沿用本地缓存: %s", exc)
            return

        for device_id, device in self._devices.items():
            try:
                udm_device = udm.get_device(device_id)
            except Exception:  # pragma: no cover
                continue
            if udm_device is None:
                continue
            status = getattr(udm_device, "status", None)
            status_value = str(getattr(status, "value", status)).lower()
            device.is_online = status_value not in self._UDM_OFFLINE_STATUSES

    def get_device_status(self, device_id: str) -> Optional[Dict[str, Any]]:
        """获取设备状态"""
        self._apply_udm_truth()
        if device_id in self._devices:
            return self._devices[device_id].to_dict()
        return None

    def get_all_devices(self) -> List[Dict[str, Any]]:
        """获取所有设备状态"""
        self._apply_udm_truth()
        return [device.to_dict() for device in self._devices.values()]

    def get_devices_by_category(self, category: DeviceCategory) -> List[Dict[str, Any]]:
        """按类别获取设备"""
        self._apply_udm_truth()
        return [device.to_dict() for device in self._devices.values() if device.category == category]

    def get_online_devices(self) -> List[Dict[str, Any]]:
        """获取在线设备"""
        self._apply_udm_truth()
        return [device.to_dict() for device in self._devices.values() if device.is_online]

    def get_status_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        self._apply_udm_truth()
        total = len(self._devices)
        online = sum(1 for d in self._devices.values() if d.is_online)
        connected = sum(1 for d in self._devices.values() if d.is_connected_to_server)

        by_category = {}
        for cat in DeviceCategory:
            devices = [d for d in self._devices.values() if d.category == cat]
            if devices:
                by_category[cat.value] = {"total": len(devices), "online": sum(1 for d in devices if d.is_online)}

        return {
            "total_devices": total,
            "online_devices": online,
            "connected_devices": connected,
            "by_category": by_category,
            "last_updated": datetime.now().isoformat(),
        }

    def _record_history(self, device_id: str, status: Dict[str, Any]):
        """记录状态历史"""
        if device_id not in self._status_history:
            self._status_history[device_id] = []

        history = self._status_history[device_id]
        history.append({"timestamp": datetime.now().isoformat(), "status": status})

        # 只保留最近 100 条记录
        if len(history) > 100:
            self._status_history[device_id] = history[-100:]

    async def add_websocket_client(self, websocket: WebSocket):
        """添加 WebSocket 客户端"""
        self._websocket_clients.add(websocket)
        logger.info(f"WebSocket client connected. Total: {len(self._websocket_clients)}")

    async def remove_websocket_client(self, websocket: WebSocket):
        """移除 WebSocket 客户端"""
        self._websocket_clients.discard(websocket)
        logger.info(f"WebSocket client disconnected. Total: {len(self._websocket_clients)}")

    async def _broadcast_update(self, event_type: str, data: Dict[str, Any]):
        """广播状态更新"""
        if not self._websocket_clients:
            return

        # 规范键是 type;event 是这一侧的历史键,作为迁移垫片同值带出
        # (见 core/status_ws_envelope.py)。
        message = json.dumps(build_status_frame(event_type, legacy_event_key=True, data=data))

        disconnected = set()
        for client in list(self._websocket_clients):
            try:
                await client.send_text(message)
            except Exception as e:
                logger.error(f"Failed to send to WebSocket client: {e}")
                disconnected.add(client)

        # 清理断开的连接
        self._websocket_clients -= disconnected


# ============================================================================
# 全局实例
# ============================================================================

status_manager = DeviceStatusManager()


# ============================================================================
# FastAPI 应用
# ============================================================================

app = FastAPI(title="Galaxy Device Status API", description="统一设备状态管理 API", version="2.0")

app.add_middleware(
    CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)


# Pydantic 模型
class RegisterDeviceRequest(BaseModel):
    device_id: str
    device_name: str
    device_type: str
    category: str = "custom"
    os_version: str = ""
    app_version: str = ""


class UpdateStatusRequest(BaseModel):
    hardware: Optional[Dict[str, Any]] = None
    is_online: Optional[bool] = None
    is_connected_to_server: Optional[bool] = None
    active_nodes: Optional[int] = None
    total_nodes: Optional[int] = None
    node_health: Optional[float] = None
    extra_data: Optional[Dict[str, Any]] = None


# API 路由
@app.get("/")
async def root():
    return {"service": "Galaxy Device Status API", "version": "2.0"}


@app.get("/status/summary")
async def get_summary():
    """获取状态摘要"""
    return status_manager.get_status_summary()


@app.get("/devices")
async def list_devices(category: Optional[str] = None, online_only: bool = False):
    """列出所有设备"""
    if online_only:
        return status_manager.get_online_devices()
    if category:
        try:
            cat = DeviceCategory(category)
            return status_manager.get_devices_by_category(cat)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid category: {category}")
    return status_manager.get_all_devices()


@app.get("/devices/{device_id}")
async def get_device(device_id: str):
    """获取设备状态"""
    status = status_manager.get_device_status(device_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return status


@app.post("/devices/register")
async def register_device(request: RegisterDeviceRequest):
    """注册设备"""
    try:
        category = DeviceCategory(request.category)
    except ValueError:
        category = DeviceCategory.CUSTOM

    device_state = DeviceState(
        device_id=request.device_id,
        device_name=request.device_name,
        device_type=request.device_type,
        category=category,
        os_version=request.os_version,
        app_version=request.app_version,
    )

    success = status_manager.register_device(device_state)
    return {"success": success, "device_id": request.device_id}


@app.delete("/devices/{device_id}")
async def unregister_device(device_id: str):
    """注销设备"""
    success = status_manager.unregister_device(device_id)
    if not success:
        raise HTTPException(status_code=404, detail="Device not found")
    return {"success": True}


@app.put("/devices/{device_id}/status")
async def update_status(device_id: str, request: UpdateStatusRequest):
    """更新设备状态"""
    update_data = request.dict(exclude_none=True)
    success = status_manager.update_device_status(device_id, update_data)
    if not success:
        raise HTTPException(status_code=404, detail="Device not found")
    return {"success": True}


@app.post("/devices/{device_id}/heartbeat")
async def heartbeat(device_id: str):
    """设备心跳"""
    success = status_manager.update_device_status(device_id, {"is_online": True, "is_connected_to_server": True})
    if not success:
        raise HTTPException(status_code=404, detail="Device not found")
    return {"success": True, "timestamp": datetime.now().isoformat()}


# WebSocket 端点
@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    """WebSocket 实时状态推送"""
    await websocket.accept()
    await status_manager.add_websocket_client(websocket)

    try:
        # 发送当前状态
        await websocket.send_json(
            build_status_frame(
                "initial_status",
                legacy_event_key=True,
                data={"summary": status_manager.get_status_summary(), "devices": status_manager.get_all_devices()},
            )
        )

        # 保持连接并处理消息
        while True:
            data = await websocket.receive_text()
            # 可以处理客户端发送的消息
            message = json.loads(data)
            if message.get("type") == "ping":
                await websocket.send_json(build_status_frame("pong", legacy_event_key=True))
            elif message.get("type") == "get_status":
                device_id = message.get("device_id")
                if device_id:
                    status = status_manager.get_device_status(device_id)
                    await websocket.send_json(build_status_frame("device_status", legacy_event_key=True, data=status))

    except WebSocketDisconnect:
        await status_manager.remove_websocket_client(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await status_manager.remove_websocket_client(websocket)


# ============================================================================
# 启动函数
# ============================================================================


def run_server(host: str = "0.0.0.0", port: int = 8766):
    """运行服务器"""
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
