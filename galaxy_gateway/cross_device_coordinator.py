"""
Cross-Device Coordinator - 跨设备协同协调器

实现多设备协同任务的编排和执行
支持设备间数据传递和状态同步

Author: Manus AI
Version: 1.0
Date: 2026-01-22
"""

import asyncio
import json
import logging
import os
import shutil
import hashlib
import tempfile
from typing import Dict, List, Optional, Any
from datetime import datetime
from galaxy_gateway.device_router import device_router
from core.device_types import DeviceType

logger = logging.getLogger(__name__)


class CrossDeviceCoordinator:
    """跨设备协同协调器"""
    
    def __init__(self):
        self.shared_clipboard: Dict[str, Any] = {}
        self.device_states: Dict[str, Dict] = {}
    
    async def execute_cross_device_task(self, command: str, context: Dict = None) -> Dict:
        """
        执行跨设备协同任务
        
        典型场景：
        1. 从手机复制文本到电脑
        2. 在电脑上打开手机拍的照片
        3. 手机和电脑同步播放控制
        4. 跨设备剪贴板共享
        """
        try:
            logger.info(f"🔄 开始执行跨设备任务: {command}")
            
            # 分析任务类型
            task_type = self._analyze_cross_device_task(command)
            
            # 根据任务类型执行
            if task_type == "clipboard_sync":
                result = await self._sync_clipboard(command, context)
            elif task_type == "file_transfer":
                result = await self._transfer_file(command, context)
            elif task_type == "media_control":
                result = await self._sync_media_control(command, context)
            elif task_type == "notification_sync":
                result = await self._sync_notification(command, context)
            else:
                result = await self._execute_generic_cross_device_task(command, context)
            
            return result
            
        except Exception as e:
            logger.error(f"❌ 跨设备任务执行失败: {e}")
            return {
                "success": False,
                "error": f"跨设备任务执行失败: {str(e)}"
            }
    
    def _analyze_cross_device_task(self, command: str) -> str:
        """分析跨设备任务类型"""
        command_lower = command.lower()
        
        if any(kw in command_lower for kw in ["复制", "粘贴", "剪贴板", "clipboard"]):
            return "clipboard_sync"
        elif any(kw in command_lower for kw in ["传输", "发送", "transfer", "send"]):
            return "file_transfer"
        elif any(kw in command_lower for kw in ["播放", "暂停", "音乐", "视频", "media"]):
            return "media_control"
        elif any(kw in command_lower for kw in ["通知", "提醒", "notification"]):
            return "notification_sync"
        else:
            return "generic"
    
    async def _sync_clipboard(self, command: str, context: Dict = None) -> Dict:
        """
        同步剪贴板
        
        场景：
        - "把手机上的文本复制到电脑"
        - "把电脑上的链接发送到手机"
        """
        try:
            logger.info("📋 执行剪贴板同步")
            
            # 解析源设备和目标设备
            source_type, target_type = self._parse_devices_from_command(command)
            
            # 步骤 1: 从源设备获取剪贴板内容
            source_task = {
                "task_type": "query",
                "action": "get_clipboard",
                "target": "",
                "params": {}
            }
            
            source_devices = device_router.get_devices_by_type(source_type)
            if not source_devices:
                return {"success": False, "error": f"没有可用的{source_type}设备"}
            
            # 发送查询任务到源设备
            source_result = await device_router.dispatch_task(
                {"task_id": "clipboard_get", "payload": source_task},
                source_devices[0]
            )
            
            if not source_result.get("success"):
                return {"success": False, "error": "获取剪贴板内容失败"}
            
            clipboard_content = source_result.get("data", {}).get("clipboard", "")
            
            # 步骤 2: 将内容设置到目标设备剪贴板
            target_task = {
                "task_type": "system_control",
                "action": "set_clipboard",
                "target": "",
                "params": {
                    "content": clipboard_content
                }
            }
            
            target_devices = device_router.get_devices_by_type(target_type)
            if not target_devices:
                return {"success": False, "error": f"没有可用的{target_type}设备"}
            
            target_result = await device_router.dispatch_task(
                {"task_id": "clipboard_set", "payload": target_task},
                target_devices[0]
            )
            
            return {
                "success": target_result.get("success", False),
                "message": "剪贴板同步完成",
                "content_length": len(clipboard_content)
            }
            
        except Exception as e:
            logger.error(f"❌ 剪贴板同步失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def _transfer_file(self, command: str, context: Dict = None) -> Dict:
        """
        跨设备文件传输 - 通过中转目录实现

        场景：
        - "把手机上的照片发送到电脑"
        - "把电脑上的文档传到手机"
        """
        try:
            logger.info("📁 执行文件传输")
            context = context or {}

            # 解析源设备和目标设备
            source_type, target_type = self._parse_devices_from_command(command)

            # 创建中转目录
            transfer_dir = os.path.join(tempfile.gettempdir(), "galaxy_transfers")
            os.makedirs(transfer_dir, exist_ok=True)

            # 从上下文获取文件路径
            file_path = context.get("file_path", "")
            file_name = context.get("file_name", os.path.basename(file_path) if file_path else "")

            # 获取源设备和目标设备
            source_devices = device_router.get_devices_by_type(source_type)
            target_devices = device_router.get_devices_by_type(target_type)

            if not source_devices:
                return {"success": False, "error": f"没有可用的{source_type}设备"}
            if not target_devices:
                return {"success": False, "error": f"没有可用的{target_type}设备"}

            source_device = source_devices[0]
            target_device = target_devices[0]

            # 步骤 1: 从源设备拉取文件到中转目录
            transfer_path = os.path.join(transfer_dir, f"{hashlib.md5(file_name.encode()).hexdigest()}_{file_name}")

            if source_type == DeviceType.ANDROID:
                # ADB pull 从安卓设备拉取
                pull_task = {
                    "task_type": "system_control",
                    "action": "shell",
                    "target": "",
                    "params": {"command": f"pull {file_path} {transfer_path}"}
                }
                pull_result = await device_router.dispatch_task(
                    {"task_id": "file_pull", "payload": pull_task}, source_device
                )
            elif source_type == DeviceType.WINDOWS:
                # 本地文件复制
                if os.path.exists(file_path):
                    shutil.copy2(file_path, transfer_path)
                    pull_result = {"success": True}
                else:
                    pull_result = {"success": False, "error": f"文件不存在: {file_path}"}
            else:
                pull_result = {"success": False, "error": f"不支持的源设备类型: {source_type}"}

            if not pull_result.get("success") and not os.path.exists(transfer_path):
                # 如果文件传输失败但没有错误信息，尝试查找最新的文件
                return {"success": False, "error": f"从源设备获取文件失败: {pull_result.get('error', '未知错误')}"}

            # 步骤 2: 将文件推送到目标设备
            if target_type == DeviceType.ANDROID:
                # ADB push 推送到安卓设备
                target_path = context.get("target_path", f"/sdcard/Download/{file_name}")
                push_task = {
                    "task_type": "system_control",
                    "action": "shell",
                    "target": "",
                    "params": {"command": f"push {transfer_path} {target_path}"}
                }
                push_result = await device_router.dispatch_task(
                    {"task_id": "file_push", "payload": push_task}, target_device
                )
            elif target_type == DeviceType.WINDOWS:
                # 本地文件复制
                target_path = context.get("target_path", os.path.join(os.path.expanduser("~"), "Downloads", file_name))
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                shutil.copy2(transfer_path, target_path)
                push_result = {"success": True}
            else:
                push_result = {"success": False, "error": f"不支持的目标设备类型: {target_type}"}

            # 清理中转文件
            try:
                if os.path.exists(transfer_path):
                    os.remove(transfer_path)
            except OSError:
                pass

            # 记录传输到共享数据
            if push_result.get("success"):
                self.set_shared_data("last_transfer", {
                    "file_name": file_name,
                    "source": source_type,
                    "target": target_type,
                    "target_path": target_path if target_type == DeviceType.WINDOWS else context.get("target_path", ""),
                    "timestamp": datetime.now().isoformat()
                })

            return {
                "success": push_result.get("success", False),
                "message": "文件传输完成" if push_result.get("success") else "文件传输失败",
                "file_name": file_name,
                "source_device": source_type,
                "target_device": target_type,
                "target_path": target_path if target_type == DeviceType.WINDOWS else context.get("target_path", "")
            }

        except Exception as e:
            logger.error(f"❌ 文件传输失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def _sync_media_control(self, command: str, context: Dict = None) -> Dict:
        """
        同步媒体控制
        
        场景：
        - "手机开始放音乐，电脑暂停视频"
        - "所有设备静音"
        """
        try:
            logger.info("🎵 执行媒体控制同步")
            
            # 获取所有在线设备
            all_devices = [d for d in device_router.devices.values() if d.status == "online"]
            
            # 解析媒体控制命令
            action = self._parse_media_action(command)
            
            # 并行发送到所有设备
            tasks = []
            for device in all_devices:
                task = {
                    "task_type": "system_control",
                    "action": action,
                    "target": "",
                    "params": {}
                }
                
                tasks.append(device_router.dispatch_task(
                    {"task_id": f"media_{device.device_id}", "payload": task},
                    device
                ))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            success_count = sum(1 for r in results if isinstance(r, dict) and r.get("success"))
            
            return {
                "success": success_count > 0,
                "message": f"媒体控制已同步到 {success_count}/{len(all_devices)} 个设备"
            }
            
        except Exception as e:
            logger.error(f"❌ 媒体控制同步失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def _sync_notification(self, command: str, context: Dict = None) -> Dict:
        """
        同步通知
        
        场景：
        - "把手机的通知显示在电脑上"
        - "所有设备显示提醒"
        """
        try:
            logger.info("🔔 执行通知同步")
            
            # 提取通知内容
            notification_text = context.get("notification_text", command)
            
            # 获取所有在线设备
            all_devices = [d for d in device_router.devices.values() if d.status == "online"]
            
            # 并行发送通知到所有设备
            tasks = []
            for device in all_devices:
                task = {
                    "task_type": "system_control",
                    "action": "show_notification",
                    "target": "",
                    "params": {
                        "title": "Galaxy",
                        "message": notification_text
                    }
                }
                
                tasks.append(device_router.dispatch_task(
                    {"task_id": f"notify_{device.device_id}", "payload": task},
                    device
                ))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            success_count = sum(1 for r in results if isinstance(r, dict) and r.get("success"))
            
            return {
                "success": success_count > 0,
                "message": f"通知已发送到 {success_count}/{len(all_devices)} 个设备"
            }
            
        except Exception as e:
            logger.error(f"❌ 通知同步失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def _execute_generic_cross_device_task(self, command: str, context: Dict = None) -> Dict:
        """执行通用跨设备任务"""
        try:
            logger.info("🔄 执行通用跨设备任务")
            
            # 将任务分解为多个子任务
            # 每个子任务指定目标设备
            
            # 简化实现：路由到主设备
            return await device_router.route_task(command, context)
            
        except Exception as e:
            logger.error(f"❌ 通用跨设备任务执行失败: {e}")
            return {"success": False, "error": str(e)}
    
    def _parse_devices_from_command(self, command: str) -> tuple:
        """从命令中解析源设备和目标设备"""
        command_lower = command.lower()
        
        source_type = DeviceType.UNKNOWN
        target_type = DeviceType.UNKNOWN
        
        # 解析源设备
        if "手机" in command_lower or "android" in command_lower:
            if command_lower.index("手机") < len(command_lower) // 2:
                source_type = DeviceType.ANDROID
            else:
                target_type = DeviceType.ANDROID
        
        # 解析目标设备
        if "电脑" in command_lower or "pc" in command_lower or "windows" in command_lower:
            if "电脑" in command_lower and command_lower.index("电脑") > len(command_lower) // 2:
                target_type = DeviceType.WINDOWS
            else:
                source_type = DeviceType.WINDOWS
        
        # 默认值
        if source_type == DeviceType.UNKNOWN:
            source_type = DeviceType.ANDROID
        if target_type == DeviceType.UNKNOWN:
            target_type = DeviceType.WINDOWS
        
        return source_type, target_type
    
    def _parse_media_action(self, command: str) -> str:
        """解析媒体控制动作"""
        command_lower = command.lower()
        
        if "暂停" in command_lower or "pause" in command_lower:
            return "pause_media"
        elif "播放" in command_lower or "play" in command_lower:
            return "play_media"
        elif "静音" in command_lower or "mute" in command_lower:
            return "mute"
        elif "音量" in command_lower or "volume" in command_lower:
            return "volume"
        else:
            return "pause_media"
    
    def set_shared_data(self, key: str, value: Any):
        """设置共享数据"""
        self.shared_clipboard[key] = {
            "value": value,
            "timestamp": datetime.now().isoformat()
        }
        logger.info(f"✅ 共享数据已设置: {key}")
    
    def get_shared_data(self, key: str) -> Optional[Any]:
        """获取共享数据"""
        data = self.shared_clipboard.get(key)
        if data:
            return data.get("value")
        return None
    
    def update_device_state(self, device_id: str, state: Dict):
        """更新设备状态"""
        self.device_states[device_id] = {
            **state,
            "updated_at": datetime.now().isoformat()
        }
    
    def get_device_state(self, device_id: str) -> Optional[Dict]:
        """获取设备状态"""
        return self.device_states.get(device_id)


# 全局跨设备协调器实例
cross_device_coordinator = CrossDeviceCoordinator()
