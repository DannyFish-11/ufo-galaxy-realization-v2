"""
core.runtime_registry — AgentRuntime注册表
===========================================
每个注册设备在V2中创建一个AgentRuntime实例。
提供双向接管能力。
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger("Galaxy.RuntimeRegistry")


class RuntimeStatus(str, Enum):
    """AgentRuntime状态枚举"""
    ONLINE = "online"
    BUSY = "busy"
    OFFLINE = "offline"


@dataclass
class AgentRuntime:
    """AgentRuntime — 每个注册设备的运行时实例"""
    device_id: str
    device_type: str  # "desktop" / "android" / "tablet"
    websocket: object  # WebSocket connection
    capabilities: List[str] = field(default_factory=list)
    status: RuntimeStatus = RuntimeStatus.ONLINE
    current_task: Optional[str] = None
    registered_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    tailscale_ip: Optional[str] = None
    lan_ip: Optional[str] = None


class RuntimeRegistry:
    """AgentRuntime注册表 — 单例"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._runtimes: Dict[str, AgentRuntime] = {}
        return cls._instance

    def register(self, runtime: AgentRuntime):
        """注册AgentRuntime"""
        self._runtimes[runtime.device_id] = runtime
        logger.info("Runtime registered: %s (%s)", runtime.device_id, runtime.device_type)

    def unregister(self, device_id: str):
        """注销AgentRuntime"""
        if device_id in self._runtimes:
            del self._runtimes[device_id]
            logger.info("Runtime unregistered: %s", device_id)

    def get(self, device_id: str) -> Optional[AgentRuntime]:
        """获取指定设备的AgentRuntime"""
        return self._runtimes.get(device_id)

    def get_by_type(self, device_type: str) -> List[AgentRuntime]:
        """获取指定类型的所有AgentRuntime"""
        return [r for r in self._runtimes.values() if r.device_type == device_type]

    def get_online(self) -> List[AgentRuntime]:
        """获取所有在线的AgentRuntime"""
        return [r for r in self._runtimes.values() if r.status == RuntimeStatus.ONLINE]

    def get_all(self) -> Dict[str, AgentRuntime]:
        """获取所有注册的AgentRuntime"""
        return dict(self._runtimes)

    def update_status(self, device_id: str, status: RuntimeStatus):
        """更新设备状态"""
        runtime = self._runtimes.get(device_id)
        if runtime:
            runtime.status = status
            runtime.last_heartbeat = time.time()

    def update_heartbeat(self, device_id: str):
        """更新设备心跳"""
        runtime = self._runtimes.get(device_id)
        if runtime:
            runtime.last_heartbeat = time.time()

    async def dispatch_task(self, task: Dict, target_device: Optional[str] = None) -> Dict:
        """派发任务到指定设备或自动选择"""
        if target_device:
            runtime = self._runtimes.get(target_device)
            if runtime and runtime.status == RuntimeStatus.ONLINE:
                return await self._send_task(runtime, task)
            return {"success": False, "error": f"Device {target_device} not available"}

        # 自动选择
        capable = [r for r in self.get_online() if task.get("type") in r.capabilities]
        if capable:
            best = min(capable, key=lambda r: r.current_task is not None)
            return await self._send_task(best, task)
        return {"success": False, "error": "No capable device available"}

    async def _send_task(self, runtime: AgentRuntime, task: Dict) -> Dict:
        """通过WebSocket发送任务"""
        try:
            runtime.status = RuntimeStatus.BUSY
            runtime.current_task = task.get("id", "unknown")
            await runtime.websocket.send_text(json.dumps({
                "type": "task_dispatch",
                "task": task,
                "from": "v2_center",
            }))
            return {"success": True, "dispatched_to": runtime.device_id}
        except Exception as exc:
            logger.error("Failed to dispatch to %s: %s", runtime.device_id, exc)
            runtime.status = RuntimeStatus.OFFLINE
            return {"success": False, "error": str(exc)}


def get_runtime_registry() -> RuntimeRegistry:
    """获取RuntimeRegistry单例"""
    return RuntimeRegistry()
