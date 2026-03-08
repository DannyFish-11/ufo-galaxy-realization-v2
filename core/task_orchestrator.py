"""
UFO Galaxy - 跨设备任务编排器
==============================

高层跨设备任务逻辑：剪贴板同步、文件传输、媒体控制、通知广播。
从 galaxy_gateway.cross_device_coordinator 提取，改用 core.device_communication 公共 API。
"""

import asyncio
import hashlib
import logging
import os
import shutil
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from core.device_types import DeviceType

logger = logging.getLogger("UFO-Galaxy.TaskOrchestrator")


class TaskOrchestrator:
    """高层跨设备任务编排

    不直接依赖 device_router（避免循环导入），
    而是通过 device_comm.send_command() 和 device_registry.list_devices() 工作。
    """

    def __init__(self, device_comm=None, device_registry=None):
        self._comm = device_comm
        self._registry = device_registry

    def _get_comm(self):
        if self._comm is None:
            from core.device_communication import device_comm
            self._comm = device_comm
        return self._comm

    def _get_registry(self):
        if self._registry is None:
            from core.device_registry import device_registry
            self._registry = device_registry
        return self._registry

    # === 主入口 ===

    async def execute_task(self, command: str, context: Dict = None) -> Dict:
        """执行跨设备协同任务"""
        try:
            logger.info(f"执行跨设备任务: {command}")
            task_type = self._analyze_task(command)

            if task_type == "clipboard_sync":
                return await self.sync_clipboard(command, context)
            elif task_type == "file_transfer":
                return await self.transfer_file(command, context)
            elif task_type == "media_control":
                return await self.sync_media_control(command, context)
            elif task_type == "notification_sync":
                return await self.broadcast_notification(command, context)
            else:
                return await self._execute_generic(command, context)

        except Exception as e:
            logger.error(f"跨设备任务执行失败: {e}")
            return {"success": False, "error": f"跨设备任务执行失败: {str(e)}"}

    # === 剪贴板同步 ===

    async def sync_clipboard(self, command: str, context: Dict = None) -> Dict:
        """同步剪贴板内容"""
        try:
            logger.info("执行剪贴板同步")
            source_type, target_type = self._parse_devices(command)
            comm = self._get_comm()

            # 找到源设备
            source_id = self._find_device_by_type(source_type)
            if not source_id:
                return {"success": False, "error": f"没有可用的{source_type.value}设备"}

            # 从源设备获取剪贴板
            source_result = await comm.send_command(source_id, "get_clipboard")
            if not source_result.get("success"):
                return {"success": False, "error": "获取剪贴板内容失败"}

            clipboard_content = source_result.get("data", {}).get("clipboard", "")

            # 找到目标设备
            target_id = self._find_device_by_type(target_type)
            if not target_id:
                return {"success": False, "error": f"没有可用的{target_type.value}设备"}

            # 设置到目标设备剪贴板
            target_result = await comm.send_command(
                target_id, "set_clipboard", {"content": clipboard_content}
            )

            return {
                "success": target_result.get("success", False),
                "message": "剪贴板同步完成",
                "content_length": len(clipboard_content),
            }

        except Exception as e:
            logger.error(f"剪贴板同步失败: {e}")
            return {"success": False, "error": str(e)}

    # === 文件传输 ===

    async def transfer_file(self, command: str, context: Dict = None) -> Dict:
        """跨设备文件传输（通过中转目录）"""
        try:
            logger.info("执行文件传输")
            context = context or {}
            source_type, target_type = self._parse_devices(command)
            comm = self._get_comm()

            transfer_dir = os.path.join(tempfile.gettempdir(), "galaxy_transfers")
            os.makedirs(transfer_dir, exist_ok=True)

            file_path = context.get("file_path", "")
            file_name = context.get("file_name", os.path.basename(file_path) if file_path else "")

            source_id = self._find_device_by_type(source_type)
            target_id = self._find_device_by_type(target_type)
            if not source_id:
                return {"success": False, "error": f"没有可用的{source_type.value}设备"}
            if not target_id:
                return {"success": False, "error": f"没有可用的{target_type.value}设备"}

            transfer_path = os.path.join(
                transfer_dir, f"{hashlib.md5(file_name.encode()).hexdigest()}_{file_name}"
            )

            # 步骤 1: 从源设备拉取文件
            if source_type == DeviceType.ANDROID:
                pull_result = await comm.send_command(
                    source_id, "shell", {"command": f"pull {file_path} {transfer_path}"}
                )
            elif source_type == DeviceType.WINDOWS:
                if os.path.exists(file_path):
                    shutil.copy2(file_path, transfer_path)
                    pull_result = {"success": True}
                else:
                    pull_result = {"success": False, "error": f"文件不存在: {file_path}"}
            else:
                pull_result = {"success": False, "error": f"不支持的源设备类型: {source_type.value}"}

            if not pull_result.get("success") and not os.path.exists(transfer_path):
                return {"success": False, "error": f"从源设备获取文件失败: {pull_result.get('error', '未知错误')}"}

            # 步骤 2: 推送到目标设备
            target_path = ""
            if target_type == DeviceType.ANDROID:
                target_path = context.get("target_path", f"/sdcard/Download/{file_name}")
                push_result = await comm.send_command(
                    target_id, "shell", {"command": f"push {transfer_path} {target_path}"}
                )
            elif target_type == DeviceType.WINDOWS:
                target_path = context.get(
                    "target_path",
                    os.path.join(os.path.expanduser("~"), "Downloads", file_name),
                )
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                shutil.copy2(transfer_path, target_path)
                push_result = {"success": True}
            else:
                push_result = {"success": False, "error": f"不支持的目标设备类型: {target_type.value}"}

            # 清理中转文件
            try:
                if os.path.exists(transfer_path):
                    os.remove(transfer_path)
            except OSError:
                pass

            return {
                "success": push_result.get("success", False),
                "message": "文件传输完成" if push_result.get("success") else "文件传输失败",
                "file_name": file_name,
                "source_device": source_type.value,
                "target_device": target_type.value,
                "target_path": target_path,
            }

        except Exception as e:
            logger.error(f"文件传输失败: {e}")
            return {"success": False, "error": str(e)}

    # === 媒体控制 ===

    async def sync_media_control(self, command: str, context: Dict = None) -> Dict:
        """同步媒体控制到所有在线设备"""
        try:
            logger.info("执行媒体控制同步")
            comm = self._get_comm()
            action = self._parse_media_action(command)

            connected = comm.list_connected_devices()
            if not connected:
                return {"success": False, "error": "没有已连接的设备"}

            tasks = [
                comm.send_command(device_id, action) for device_id in connected
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            success_count = sum(
                1 for r in results if isinstance(r, dict) and r.get("success")
            )

            return {
                "success": success_count > 0,
                "message": f"媒体控制已同步到 {success_count}/{len(connected)} 个设备",
            }

        except Exception as e:
            logger.error(f"媒体控制同步失败: {e}")
            return {"success": False, "error": str(e)}

    # === 通知广播 ===

    async def broadcast_notification(self, command: str, context: Dict = None) -> Dict:
        """向所有在线设备广播通知"""
        try:
            logger.info("执行通知广播")
            comm = self._get_comm()
            context = context or {}
            notification_text = context.get("notification_text", command)

            connected = comm.list_connected_devices()
            if not connected:
                return {"success": False, "error": "没有已连接的设备"}

            tasks = [
                comm.send_command(
                    device_id,
                    "show_notification",
                    {"title": "UFO Galaxy", "message": notification_text},
                )
                for device_id in connected
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            success_count = sum(
                1 for r in results if isinstance(r, dict) and r.get("success")
            )

            return {
                "success": success_count > 0,
                "message": f"通知已发送到 {success_count}/{len(connected)} 个设备",
            }

        except Exception as e:
            logger.error(f"通知广播失败: {e}")
            return {"success": False, "error": str(e)}

    # === 内部方法 ===

    async def _execute_generic(self, command: str, context: Dict = None) -> Dict:
        """执行通用跨设备任务 — 路由到 device_router"""
        try:
            from galaxy_gateway.device_router import device_router
            return await device_router.route_task(command, context)
        except ImportError:
            return {"success": False, "error": "device_router 不可用"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _analyze_task(self, command: str) -> str:
        """分析跨设备任务类型"""
        cmd = command.lower()
        if any(kw in cmd for kw in ["复制", "粘贴", "剪贴板", "clipboard"]):
            return "clipboard_sync"
        elif any(kw in cmd for kw in ["传输", "发送", "transfer", "send"]):
            return "file_transfer"
        elif any(kw in cmd for kw in ["播放", "暂停", "音乐", "视频", "media"]):
            return "media_control"
        elif any(kw in cmd for kw in ["通知", "提醒", "notification"]):
            return "notification_sync"
        return "generic"

    def _parse_devices(self, command: str) -> Tuple[DeviceType, DeviceType]:
        """从命令中解析源设备和目标设备"""
        cmd = command.lower()
        source_type = DeviceType.UNKNOWN
        target_type = DeviceType.UNKNOWN

        if "手机" in cmd or "android" in cmd:
            if cmd.index("手机") < len(cmd) // 2 if "手机" in cmd else True:
                source_type = DeviceType.ANDROID
            else:
                target_type = DeviceType.ANDROID

        if "电脑" in cmd or "pc" in cmd or "windows" in cmd:
            if "电脑" in cmd and cmd.index("电脑") > len(cmd) // 2:
                target_type = DeviceType.WINDOWS
            else:
                source_type = DeviceType.WINDOWS

        if source_type == DeviceType.UNKNOWN:
            source_type = DeviceType.ANDROID
        if target_type == DeviceType.UNKNOWN:
            target_type = DeviceType.WINDOWS

        return source_type, target_type

    def _parse_media_action(self, command: str) -> str:
        """解析媒体控制动作"""
        cmd = command.lower()
        if "暂停" in cmd or "pause" in cmd:
            return "pause_media"
        elif "播放" in cmd or "play" in cmd:
            return "play_media"
        elif "静音" in cmd or "mute" in cmd:
            return "mute"
        elif "音量" in cmd or "volume" in cmd:
            return "volume"
        return "pause_media"

    def _find_device_by_type(self, device_type: DeviceType) -> Optional[str]:
        """查找指定类型的已连接设备"""
        comm = self._get_comm()
        connected = comm.list_connected_devices()

        try:
            registry = self._get_registry()
            for device_id in connected:
                devices = registry.list_devices(device_type=device_type.value)
                for d in devices:
                    if (getattr(d, 'device_id', None) or getattr(d, 'id', None)) == device_id:
                        return device_id
        except Exception:
            pass

        # Fallback: return first connected device
        return connected[0] if connected else None
