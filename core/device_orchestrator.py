#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UFO Galaxy - 统一设备编排器 (Device Orchestrator)
==================================================

统一设备编排入口，委托到已有模块（DeviceRegistry、NodeRegistry、
ConnectionManager）完成实际工作。提供高层 API 用于设备发现、命令下发、
文件传输、剪贴板同步和遥测采集。

使用方法：
    from core.device_orchestrator import get_device_orchestrator

    orch = get_device_orchestrator()
    devices = await orch.discover_devices(device_type="android")
    result  = await orch.send_command("dev_001", "screenshot", {"quality": 80})
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.DeviceOrchestrator")


# ---------------------------------------------------------------------------
# Lazy imports — 避免循环依赖
# ---------------------------------------------------------------------------

def _get_device_registry():
    """延迟导入设备注册表"""
    try:
        from core.device_registry import DeviceRegistry
        return DeviceRegistry.get_instance()
    except Exception as exc:
        logger.debug(f"DeviceRegistry 不可用: {exc}")
        return None


def _get_node_registry():
    """延迟导入节点注册表"""
    try:
        from core.node_registry import get_registry
        return get_registry()
    except Exception as exc:
        logger.debug(f"NodeRegistry 不可用: {exc}")
        return None


def _get_connection_manager():
    """延迟导入连接管理器"""
    try:
        from core.connection_manager import get_connection_manager
        return get_connection_manager()
    except Exception as exc:
        logger.debug(f"ConnectionManager 不可用: {exc}")
        return None


def _resolve_device_type(raw: str):
    """延迟导入设备类型解析"""
    try:
        from core.device_types import resolve_device_type
        return resolve_device_type(raw)
    except Exception:
        return None


# ===========================================================================
# DeviceOrchestrator
# ===========================================================================

class DeviceOrchestrator:
    """统一设备编排器 — 所有设备操作的高层入口。

    内部委托到 DeviceRegistry（设备注册/发现）、NodeRegistry（节点调用）
    和 ConnectionManager（连接管理），在任一模块不可用时优雅降级。
    """

    _instance: Optional["DeviceOrchestrator"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        logger.info("设备编排器已初始化")

    # ------------------------------------------------------------------
    # discover_devices
    # ------------------------------------------------------------------

    async def discover_devices(
        self,
        device_type: Optional[str] = None,
        online_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """发现设备。

        优先使用 Node_71（发现引擎节点）执行网络层发现，
        若不可用则回退到 DeviceRegistry 的本地注册列表。

        Args:
            device_type: 按设备类型过滤（可选）。
            online_only: 是否仅返回在线设备。

        Returns:
            设备信息字典列表。
        """
        # 尝试通过 Node_71 发现引擎
        node_registry = _get_node_registry()
        if node_registry is not None:
            discovery_node = node_registry.get_node("Node_71")
            if discovery_node is not None:
                try:
                    params: Dict[str, Any] = {}
                    if device_type:
                        params["device_type"] = device_type
                    params["online_only"] = online_only
                    result = await node_registry.call_node(
                        "Node_71", "discover", params
                    )
                    if result.get("success") and "data" in result:
                        data = result["data"]
                        if isinstance(data, list):
                            return data
                        if isinstance(data, dict) and "devices" in data:
                            return data["devices"]
                except Exception as exc:
                    logger.warning(f"Node_71 发现引擎调用失败，回退到注册表: {exc}")

        # 回退到 DeviceRegistry
        device_registry = _get_device_registry()
        if device_registry is not None:
            try:
                devices = await device_registry.discover(
                    device_type=device_type,
                    online_only=online_only,
                )
                return [d.to_dict() for d in devices]
            except Exception as exc:
                logger.error(f"DeviceRegistry.discover 失败: {exc}")

        logger.warning("无可用发现源，返回空列表")
        return []

    # ------------------------------------------------------------------
    # get_device_status
    # ------------------------------------------------------------------

    async def get_device_status(self, device_id: str) -> Dict[str, Any]:
        """获取设备状态信息。

        Args:
            device_id: 设备唯一标识。

        Returns:
            包含 device_id / status / online / last_seen / telemetry 的字典。
        """
        device_registry = _get_device_registry()
        if device_registry is not None:
            device = device_registry.get(device_id)
            if device is not None:
                return {
                    "device_id": device.device_id,
                    "status": device.status.value,
                    "online": device.is_online(),
                    "last_seen": datetime.fromtimestamp(device.last_seen).isoformat(),
                    "telemetry": device.metadata.get("telemetry", {}),
                }

        # 尝试通过连接管理器获取连接状态
        conn_mgr = _get_connection_manager()
        if conn_mgr is not None:
            conn_info = conn_mgr.get_connection(device_id)
            if conn_info is not None:
                return {
                    "device_id": device_id,
                    "status": conn_info.state.value,
                    "online": conn_info.state.value == "connected",
                    "last_seen": (
                        conn_info.last_heartbeat.isoformat()
                        if conn_info.last_heartbeat
                        else None
                    ),
                    "telemetry": {},
                }

        return {
            "device_id": device_id,
            "status": "unknown",
            "online": False,
            "last_seen": None,
            "telemetry": {},
        }

    # ------------------------------------------------------------------
    # send_command
    # ------------------------------------------------------------------

    async def send_command(
        self,
        device_id: str,
        command: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """向设备发送 AIP v3.0 命令。

        Args:
            device_id: 目标设备 ID。
            command: 命令名称。
            params: 命令参数。
            timeout: 超时秒数。

        Returns:
            包含 command_id / status / result / execution_time_ms 的字典。
        """
        command_id = uuid.uuid4().hex[:12]
        params = params or {}
        start = time.monotonic()

        # 通过 NodeRegistry 调用
        node_registry = _get_node_registry()
        if node_registry is not None:
            try:
                result = await asyncio.wait_for(
                    node_registry.call_node(device_id, command, params),
                    timeout=timeout,
                )
                elapsed_ms = (time.monotonic() - start) * 1000
                return {
                    "device_id": device_id,
                    "command_id": command_id,
                    "status": "success" if result.get("success") else "error",
                    "result": result.get("data", result.get("error")),
                    "execution_time_ms": round(elapsed_ms, 2),
                }
            except asyncio.TimeoutError:
                elapsed_ms = (time.monotonic() - start) * 1000
                return {
                    "device_id": device_id,
                    "command_id": command_id,
                    "status": "timeout",
                    "result": f"命令超时 ({timeout}s)",
                    "execution_time_ms": round(elapsed_ms, 2),
                }
            except Exception as exc:
                elapsed_ms = (time.monotonic() - start) * 1000
                logger.error(f"send_command 失败 [{device_id}:{command}]: {exc}")
                return {
                    "device_id": device_id,
                    "command_id": command_id,
                    "status": "error",
                    "result": str(exc),
                    "execution_time_ms": round(elapsed_ms, 2),
                }

        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "device_id": device_id,
            "command_id": command_id,
            "status": "error",
            "result": "NodeRegistry 不可用",
            "execution_time_ms": round(elapsed_ms, 2),
        }

    # ------------------------------------------------------------------
    # parallel_commands
    # ------------------------------------------------------------------

    async def parallel_commands(
        self,
        commands: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """并行向多台设备发送命令。

        Args:
            commands: 命令列表，每项包含 device_id / command / params（可选）/ timeout（可选）。

        Returns:
            结果列表，顺序与输入一致。
        """
        tasks = []
        for cmd in commands:
            device_id = cmd.get("device_id", "")
            command = cmd.get("command", "")
            params = cmd.get("params", {})
            timeout = cmd.get("timeout", 30)
            tasks.append(self.send_command(device_id, command, params, timeout))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: List[Dict[str, Any]] = []
        for idx, res in enumerate(results):
            if isinstance(res, Exception):
                output.append({
                    "device_id": commands[idx].get("device_id", ""),
                    "command_id": "",
                    "status": "error",
                    "result": str(res),
                    "execution_time_ms": 0.0,
                })
            else:
                output.append(res)
        return output

    # ------------------------------------------------------------------
    # transfer_file
    # ------------------------------------------------------------------

    async def transfer_file(
        self,
        source_device: str,
        target_device: str,
        file_path: str,
    ) -> Dict[str, Any]:
        """跨设备文件传输。

        通过向源设备发送 file_read 命令获取内容，再向目标设备发送
        file_write 命令写入。

        Args:
            source_device: 源设备 ID。
            target_device: 目标设备 ID。
            file_path: 文件路径。

        Returns:
            传输结果。
        """
        transfer_id = uuid.uuid4().hex[:12]
        start = time.monotonic()

        try:
            # 从源设备读取
            read_result = await self.send_command(
                source_device, "file_read", {"path": file_path}
            )
            if read_result.get("status") != "success":
                return {
                    "transfer_id": transfer_id,
                    "status": "error",
                    "error": f"源设备读取失败: {read_result.get('result')}",
                    "elapsed_ms": round((time.monotonic() - start) * 1000, 2),
                }

            file_data = read_result.get("result", {})

            # 写入目标设备
            write_result = await self.send_command(
                target_device, "file_write", {"path": file_path, "data": file_data}
            )
            elapsed_ms = round((time.monotonic() - start) * 1000, 2)

            if write_result.get("status") != "success":
                return {
                    "transfer_id": transfer_id,
                    "status": "error",
                    "error": f"目标设备写入失败: {write_result.get('result')}",
                    "elapsed_ms": elapsed_ms,
                }

            return {
                "transfer_id": transfer_id,
                "status": "success",
                "source_device": source_device,
                "target_device": target_device,
                "file_path": file_path,
                "elapsed_ms": elapsed_ms,
            }
        except Exception as exc:
            logger.error(f"文件传输失败: {exc}")
            return {
                "transfer_id": transfer_id,
                "status": "error",
                "error": str(exc),
                "elapsed_ms": round((time.monotonic() - start) * 1000, 2),
            }

    # ------------------------------------------------------------------
    # sync_clipboard
    # ------------------------------------------------------------------

    async def sync_clipboard(
        self,
        source_device: str,
        target_device: str,
    ) -> Dict[str, Any]:
        """跨设备剪贴板同步。

        从源设备获取剪贴板内容，写入目标设备。

        Args:
            source_device: 源设备 ID。
            target_device: 目标设备 ID。

        Returns:
            同步结果。
        """
        start = time.monotonic()

        try:
            # 读取源剪贴板
            read_result = await self.send_command(
                source_device, "clipboard_read", {}
            )
            if read_result.get("status") != "success":
                return {
                    "status": "error",
                    "error": f"源设备剪贴板读取失败: {read_result.get('result')}",
                    "elapsed_ms": round((time.monotonic() - start) * 1000, 2),
                }

            clipboard_data = read_result.get("result", "")

            # 写入目标剪贴板
            write_result = await self.send_command(
                target_device, "clipboard_write", {"content": clipboard_data}
            )
            elapsed_ms = round((time.monotonic() - start) * 1000, 2)

            if write_result.get("status") != "success":
                return {
                    "status": "error",
                    "error": f"目标设备剪贴板写入失败: {write_result.get('result')}",
                    "elapsed_ms": elapsed_ms,
                }

            return {
                "status": "success",
                "source_device": source_device,
                "target_device": target_device,
                "content_length": len(str(clipboard_data)),
                "elapsed_ms": elapsed_ms,
            }
        except Exception as exc:
            logger.error(f"剪贴板同步失败: {exc}")
            return {
                "status": "error",
                "error": str(exc),
                "elapsed_ms": round((time.monotonic() - start) * 1000, 2),
            }

    # ------------------------------------------------------------------
    # get_telemetry
    # ------------------------------------------------------------------

    async def get_telemetry(self, device_id: str) -> Dict[str, Any]:
        """获取设备遥测数据。

        优先从 DeviceRegistry 元数据获取，回退到向设备发送
        telemetry 命令。

        Args:
            device_id: 设备唯一标识。

        Returns:
            遥测数据字典。
        """
        # 尝试从注册表元数据获取
        device_registry = _get_device_registry()
        if device_registry is not None:
            device = device_registry.get(device_id)
            if device is not None:
                telemetry = device.metadata.get("telemetry")
                if telemetry:
                    return {
                        "device_id": device_id,
                        "source": "registry_cache",
                        "telemetry": telemetry,
                        "timestamp": datetime.fromtimestamp(
                            device.last_seen
                        ).isoformat(),
                    }

        # 回退：直接向设备请求
        try:
            result = await self.send_command(device_id, "telemetry", {})
            if result.get("status") == "success":
                return {
                    "device_id": device_id,
                    "source": "device_direct",
                    "telemetry": result.get("result", {}),
                    "timestamp": datetime.now().isoformat(),
                }
        except Exception as exc:
            logger.warning(f"遥测数据获取失败 [{device_id}]: {exc}")

        return {
            "device_id": device_id,
            "source": "unavailable",
            "telemetry": {},
            "timestamp": datetime.now().isoformat(),
        }


# ===========================================================================
# 全局单例
# ===========================================================================

_device_orchestrator: Optional[DeviceOrchestrator] = None


def get_device_orchestrator() -> DeviceOrchestrator:
    """获取全局 DeviceOrchestrator 实例。"""
    global _device_orchestrator
    if _device_orchestrator is None:
        _device_orchestrator = DeviceOrchestrator()
    return _device_orchestrator
