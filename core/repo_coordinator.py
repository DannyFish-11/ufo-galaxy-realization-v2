"""
仓库协调层 — 遗留 / 管理 Facade
=================================

架构角色 (PR-S4)
-----------------
``RepoCoordinator`` 是一个 **遗留/管理 facade**，不再是 Android 设备的主控
平面（control plane）。

- 设备注册 / 心跳 / 注销的 **canonical 状态写入** 经由
  ``UnifiedDeviceManager`` (UDM) 完成。
- ``self.android_devices`` 仅保留为 **legacy compatibility cache**，
  供外部遗留调用方（dashboard、旧路由）只读使用；它不再是设备事实来源（SSOT）。
- 所有写操作必须先写 UDM，再更新本地 compat cache。
- 设备查询（``get_android_devices``、``get_android_device``）优先委托 UDM。

版本: v2.3.23
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 导入已有协议
try:
    from galaxy_gateway.protocol.aip_v3 import (
        AIPMessage, MessageType as AIPMessageType
    )
    AIPProtocol = None  # no AIPProtocol in v3; legacy enhancements only
except ImportError:
    AIPMessage = AIPMessageType = AIPProtocol = None

import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RepoCoordinator")


class RepoCoordinator:
    """
    仓库协调器 — 遗留/管理 facade（PR-S4）。

    协调主仓库和 Android 仓库的遗留管理接口。

    ⚠️  架构角色约束
    ----------------
    RepoCoordinator **不是** Android 设备的主控平面。

    - 设备注册 / 心跳 / 注销的 canonical 写入委托给
      ``UnifiedDeviceManager`` (UDM)。
    - ``self.android_devices`` 是 **legacy compat cache**，
      不是设备事实来源（SSOT）。  外部代码若需权威设备列表，
      应查询 UDM，而非直接读取此字段。
    - 任务分发已委托给 DeviceRouter（PR-S3）。
    """
    
    def __init__(self):
        # 主仓库配置
        self.main_repo_url = os.getenv("MAIN_REPO_URL", "http://localhost:8080")
        
        # ⚠️  LEGACY COMPAT CACHE — 不是设备事实来源（SSOT）。
        # 事实来源已迁移到 core.unified.device_manager.UnifiedDeviceManager (UDM)。
        # 此字典仅供遗留代码只读兼容使用；所有写操作应优先通过 UDM 进行。
        self.android_devices: Dict[str, Dict] = {}
        
        # HTTP 客户端
        self._http_client: Optional[httpx.AsyncClient] = None
        
        logger.info("仓库协调器初始化完成")
    
    async def _get_http_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端"""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client
    
    # =========================================================================
    # Android 设备注册 — delegates to UDM (PR-S4)
    # =========================================================================
    
    async def register_android_device(
        self,
        device_id: str,
        device_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """注册 Android 设备 — canonical 写入委托 UDM（PR-S4）。

        Canonical write path: UnifiedDeviceManager (UDM).
        ``self.android_devices`` is updated as a legacy compat cache after
        the UDM write succeeds.

        Android 仓库通过此接口注册到主仓库。
        """
        device_record = {
            "device_id": device_id,
            "device_type": "android",
            "name": device_info.get("name", "Android Device"),
            "model": device_info.get("model", ""),
            "android_version": device_info.get("android_version", ""),
            "endpoint": device_info.get("endpoint", ""),
            "websocket_url": device_info.get("websocket_url", ""),
            "capabilities": device_info.get("capabilities", [
                "click", "swipe", "input", "screenshot", "open_app"
            ]),
            "status": "online",
            "registered_at": datetime.now().isoformat()
        }

        # Step 1 — canonical write to UDM (SSOT).
        try:
            from core.unified.device_manager import UnifiedDeviceManager
            udm = UnifiedDeviceManager()
            udm.register_device_from_dict(device_id, device_record)
            logger.info(
                "repo_coordinator: wrote registration to UDM (SSOT): device_id=%s",
                device_id,
            )
        except Exception as udm_err:
            logger.warning(
                "repo_coordinator: UDM registration write failed (non-fatal): "
                "device_id=%s error=%s",
                device_id, udm_err,
            )

        # Step 2 — update legacy compat cache.
        self.android_devices[device_id] = device_record
        
        logger.info(f"已注册 Android 设备: {device_id}")
        
        # Construct AIPMessage for protocol validation only (not dispatched here).
        # AIPMessage / AIPMessageType may be None when the optional package
        # is not installed.
        if AIPMessage is not None and AIPMessageType is not None:
            AIPMessage(  # protocol validation — raises ValidationError on bad input
                type=AIPMessageType.DEVICE_REGISTER,
                device_id=device_id,
                payload={
                    "device_type": "android",
                    "name": device_info.get("name", "Android Device"),
                    "capabilities": device_info.get("capabilities", [])
                }
            )
        
        return {
            "success": True,
            "device_id": device_id,
            "message": "Device registered successfully"
        }
    
    async def unregister_android_device(self, device_id: str) -> Dict[str, Any]:
        """注销 Android 设备 — canonical 写入委托 UDM（PR-S4）。

        Canonical write path: UnifiedDeviceManager (UDM).
        ``self.android_devices`` compat cache is also cleared.
        """
        # Step 1 — canonical unregister in UDM.
        try:
            from core.unified.device_manager import UnifiedDeviceManager
            udm = UnifiedDeviceManager()
            udm.unregister_device(device_id)
            logger.info(
                "repo_coordinator: unregistered from UDM: device_id=%s", device_id,
            )
        except Exception as udm_err:
            logger.warning(
                "repo_coordinator: UDM unregister failed (non-fatal): "
                "device_id=%s error=%s",
                device_id, udm_err,
            )

        # Step 2 — clear legacy compat cache.
        if device_id in self.android_devices:
            del self.android_devices[device_id]
            logger.info(f"已注销 Android 设备: {device_id}")
            return {"success": True}
        return {"success": False, "error": "Device not found"}
    
    async def heartbeat_android_device(self, device_id: str) -> Dict[str, Any]:
        """Android 设备心跳 — canonical 写入委托 UDM（PR-S4）。

        Canonical write path: UnifiedDeviceManager (UDM).
        ``self.android_devices`` compat cache is also updated.
        """
        # Step 1 — canonical heartbeat in UDM.
        try:
            from core.unified.device_manager import UnifiedDeviceManager
            udm = UnifiedDeviceManager()
            udm.heartbeat(device_id)
        except Exception as udm_err:
            logger.debug(
                "repo_coordinator: UDM heartbeat failed (non-fatal): "
                "device_id=%s error=%s",
                device_id, udm_err,
            )

        # Step 2 — update legacy compat cache.
        if device_id in self.android_devices:
            self.android_devices[device_id]["last_heartbeat"] = datetime.now().isoformat()
            self.android_devices[device_id]["status"] = "online"
            return {"success": True}
        return {"success": False, "error": "Device not found"}
    
    # =========================================================================
    # Agent 分发到 Android 设备
    # =========================================================================
    
    async def dispatch_agent_to_android(
        self,
        device_id: str,
        task_type: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """分发 Agent 到 Android 设备 — delegates to DeviceRouter (PR-S3).

        Dispatch authority is delegated to DeviceRouter.route_task() as the
        canonical single dispatch entry.  Direct WebSocket/HTTP send paths are
        preserved as a compatibility fallback only.

        Args:
            device_id: Target Android device identifier.
            task_type: Type of task to dispatch.
            params: Task parameters.
        """
        if device_id not in self.android_devices:
            return {"success": False, "error": f"Device {device_id} not found"}

        # PR-S3: delegate dispatch authority to DeviceRouter.route_task().
        try:
            from galaxy_gateway.device_router import device_router as _device_router
            command = task_type
            context = {
                "device_id": device_id,
                "task_type": task_type,
                "params": params,
                "source": "repo_coordinator",
            }
            result = await _device_router.route_task(command, context)
            return result
        except Exception as _router_err:
            logger.warning(
                "RepoCoordinator.dispatch_agent_to_android: DeviceRouter fallback — %s",
                _router_err,
            )

        # Compatibility fallback: direct send when DeviceRouter is unavailable.
        device = self.android_devices[device_id]

        # 创建 AIP 任务消息（使用 v3 字段名 type / device_id）
        message = None
        if AIPMessage is not None and AIPMessageType is not None:
            message = AIPMessage(
                type=AIPMessageType.TASK_ASSIGN,
                device_id=device_id,
                payload={
                    "task_type": task_type,
                    "params": params,
                    "timestamp": datetime.now().isoformat()
                }
            )

        try:
            # 优先使用 WebSocket
            ws_url = device.get("websocket_url")
            if ws_url:
                return await self._send_via_websocket(ws_url, message)

            # 否则使用 HTTP
            endpoint = device.get("endpoint")
            if endpoint:
                return await self._send_via_http(endpoint, message)

            return {"success": False, "error": "No endpoint available"}

        except Exception as e:
            logger.error(f"分发 Agent 到 {device_id} 失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def _send_via_websocket(
        self,
        ws_url: str,
        message: AIPMessage
    ) -> Dict[str, Any]:
        """通过 WebSocket 发送"""
        import websockets
        
        try:
            async with websockets.connect(ws_url, timeout=10) as ws:
                await ws.send(message.to_json())
                response = await ws.recv()
                return json.loads(response)
        except Exception as e:
            logger.error(f"WebSocket 发送失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def _send_via_http(
        self,
        endpoint: str,
        message: AIPMessage
    ) -> Dict[str, Any]:
        """通过 HTTP 发送"""
        try:
            client = await self._get_http_client()
            response = await client.post(
                f"{endpoint}/task/execute",
                json=message.to_dict(),
                timeout=30
            )
            return response.json()
        except Exception as e:
            logger.error(f"HTTP 发送失败: {e}")
            return {"success": False, "error": str(e)}
    
    # =========================================================================
    # 批量操作
    # =========================================================================
    
    async def broadcast_to_all_android(
        self,
        task_type: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """广播到所有 Android 设备 — device list from UDM (PR-S4).

        Reads the target device list from UnifiedDeviceManager for canonical
        coverage; falls back to the legacy compat cache when UDM is
        unavailable.
        """
        # Prefer UDM device list for canonical coverage.
        device_ids: List[str] = []
        try:
            from core.unified.device_manager import UnifiedDeviceManager
            udm = UnifiedDeviceManager()
            device_ids = [
                d.device_id for d in udm.list_devices()
                if str(getattr(d.device_type, "value", d.device_type)).lower()
                in ("android", "android_phone", "android_tablet")
            ]
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            device_ids = list(self.android_devices.keys())

        results = {}
        
        tasks = [
            self.dispatch_agent_to_android(device_id, task_type, params)
            for device_id in device_ids
        ]
        
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        for device_id, response in zip(device_ids, responses):
            if isinstance(response, Exception):
                results[device_id] = {"success": False, "error": str(response)}
            else:
                results[device_id] = response
        
        return {
            "success": True,
            "total": len(results),
            "results": results
        }
    
    # =========================================================================
    # 状态查询 — delegates to UDM (PR-S4)
    # =========================================================================
    
    def get_android_devices(self) -> List[Dict[str, Any]]:
        """获取所有 Android 设备 — 优先委托 UDM（PR-S4）。

        Returns the canonical device list from UnifiedDeviceManager when
        available; falls back to the legacy compat cache ``android_devices``
        if UDM is unavailable.
        """
        try:
            from core.unified.device_manager import UnifiedDeviceManager
            udm = UnifiedDeviceManager()
            udm_devices = [
                {
                    "device_id": d.device_id,
                    "device_type": getattr(d.device_type, "value", str(d.device_type)),
                    "name": d.device_name,
                    "capabilities": d.capabilities,
                    "status": getattr(d.status, "value", str(d.status)),
                    "source": "udm",
                    **d.metadata,
                }
                for d in udm.list_devices()
                if str(getattr(d.device_type, "value", d.device_type)).lower() in (
                    "android", "android_phone", "android_tablet"
                )
            ]
            if udm_devices:
                return udm_devices
        except Exception as udm_err:
            logger.debug(
                "repo_coordinator: UDM query failed, falling back to compat cache: %s",
                udm_err,
            )
        # Legacy compat cache fallback.
        return list(self.android_devices.values())
    
    def get_android_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """获取指定 Android 设备 — 优先委托 UDM（PR-S4）。

        Queries UnifiedDeviceManager for canonical device state; falls back to
        the legacy compat cache ``android_devices`` if UDM is unavailable.
        """
        try:
            from core.unified.device_manager import UnifiedDeviceManager
            udm = UnifiedDeviceManager()
            device = udm.get_device(device_id)
            if device is not None:
                return {
                    "device_id": device.device_id,
                    "device_type": getattr(device.device_type, "value", str(device.device_type)),
                    "name": device.device_name,
                    "capabilities": device.capabilities,
                    "status": getattr(device.status, "value", str(device.status)),
                    "source": "udm",
                    **device.metadata,
                }
        except Exception as udm_err:
            logger.debug(
                "repo_coordinator: UDM get_device failed, falling back to compat cache: %s",
                udm_err,
            )
        # Legacy compat cache fallback.
        return self.android_devices.get(device_id)
    
    def get_status(self) -> Dict[str, Any]:
        """获取协调器状态摘要 — 优先使用 UDM 设备计数（PR-S4）。"""
        try:
            from core.unified.device_manager import UnifiedDeviceManager
            udm = UnifiedDeviceManager()
            all_devices = udm.list_devices()
            from core.unified.models import UnifiedDeviceStatus
            android_devices = [
                d for d in all_devices
                if str(getattr(d.device_type, "value", d.device_type)).lower()
                in ("android", "android_phone", "android_tablet")
            ]
            online_count = sum(
                1 for d in android_devices
                if getattr(d.status, "value", d.status) == UnifiedDeviceStatus.ONLINE.value
            )
            return {
                "android_devices": len(android_devices),
                "online_devices": online_count,
                "main_repo_url": self.main_repo_url,
                "timestamp": datetime.now().isoformat(),
                "source": "udm",
            }
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

        # Legacy compat cache fallback.
        online_count = sum(
            1 for d in self.android_devices.values()
            if d.get("status") == "online"
        )
        return {
            "android_devices": len(self.android_devices),
            "online_devices": online_count,
            "main_repo_url": self.main_repo_url,
            "timestamp": datetime.now().isoformat(),
        }


# 全局实例
repo_coordinator = RepoCoordinator()
