"""
Device Router - 设备路由和任务分发模块

负责将用户命令路由到正确的设备执行，支持多设备协同任务。

数据流说明
----------
此模块是 ``galaxy_gateway/main.py`` 和 ``websocket_handler.py`` 使用的路由层。
设备注册状态由 :class:`DeviceRouter` 维护（运行时 WebSocket 连接表），
仅在连接活跃期间有效。

内部消息处理使用 AIP v3 标准字段；向设备发送的命令也使用 AIP v3 格式。
接入层（``websocket_handler.py``）负责通过 compat 层将所有 incoming 消息
规范化为 v3 格式后再传入此模块。

标准端点（参见 galaxy_gateway/app.py）
--------------------------------------
- WebSocket : ``/ws/device/{device_id}`` (primary), ``/ws/android`` (initial)
- REST      : ``/api/v1/devices/*``

Author: Manus AI
Version: 2.0
Date: 2026-03-07
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

# 延迟导入以避免循环依赖
cross_device_coordinator = None

def get_cross_device_coordinator():
    global cross_device_coordinator
    if cross_device_coordinator is None:
        from galaxy_gateway.cross_device_coordinator import cross_device_coordinator as cdc
        cross_device_coordinator = cdc
    return cross_device_coordinator


from core.device_types import DeviceType, resolve_device_type  # noqa: E402


def map_device_type_to_platform(aip_device_type: str) -> str:
    """将 AIP v3 DeviceType 字符串映射为路由层平台大类（公共接口）。

    Example::

        >>> map_device_type_to_platform("android_phone")
        'android'
        >>> map_device_type_to_platform("windows_desktop")
        'windows'
    """
    return resolve_device_type(aip_device_type).value


class TaskType:
    """任务类型"""
    UI_AUTOMATION = "ui_automation"
    APP_CONTROL = "app_control"
    SYSTEM_CONTROL = "system_control"
    QUERY = "query"
    COMPOUND = "compound"
    CROSS_DEVICE = "cross_device"


class Device:
    """设备信息"""
    
    def __init__(self, device_id: str, device_type: str, capabilities: List[str]):
        self.device_id = device_id
        self.device_type = device_type
        self.capabilities = capabilities
        self.status = "online"
        self.last_seen = datetime.now()
        self.websocket = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": self.device_type,
            "capabilities": self.capabilities,
            "status": self.status,
            "last_seen": self.last_seen.isoformat()
        }


class DeviceRouter:
    """设备路由器"""
    
    def __init__(self):
        self.devices: Dict[str, Device] = {}
        self.task_queue: Dict[str, Dict] = {}
        self.task_results: Dict[str, Dict] = {}
    
    def register_device(self, device_id: str, device_type: str, 
                       capabilities: List[str], websocket=None) -> bool:
        """注册设备"""
        try:
            device = Device(device_id, device_type, capabilities)
            device.websocket = websocket
            self.devices[device_id] = device
            
            logger.info(f"✅ 设备注册成功: {device_id} ({device_type})")
            return True
            
        except Exception as e:
            logger.error(f"❌ 设备注册失败: {e}")
            return False
    
    def unregister_device(self, device_id: str) -> bool:
        """注销设备"""
        try:
            if device_id in self.devices:
                del self.devices[device_id]
                logger.info(f"✅ 设备注销成功: {device_id}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"❌ 设备注销失败: {e}")
            return False
    
    def get_device(self, device_id: str) -> Optional[Device]:
        """获取设备"""
        return self.devices.get(device_id)
    
    def get_devices_by_type(self, device_type: str) -> List[Device]:
        """根据类型获取设备列表"""
        return [d for d in self.devices.values() if d.device_type == device_type]
    
    def get_devices_by_capability(self, capability: str) -> List[Device]:
        """根据能力获取设备列表"""
        return [d for d in self.devices.values() if capability in d.capabilities]
    
    async def route_task(self, command: str, context: Dict = None) -> Dict:
        """
        路由任务到合适的设备
        
        Args:
            command: 用户命令
            context: 上下文信息
        
        Returns:
            任务执行结果
        """
        try:
            logger.info(f"🎯 开始路由任务: {command}")
            
            # 1. 分析命令，确定目标设备和任务类型
            analysis = await self._analyze_command(command, context)
            
            # 2. 判断是否需要跨设备协同
            if analysis.get("requires_cross_device", False):
                # 使用跨设备协调器
                coordinator = get_cross_device_coordinator()
                return await coordinator.execute_cross_device_task(command, context)
            
            # 3. 选择合适的设备
            target_devices = self._select_devices(analysis)
            
            if not target_devices:
                return {
                    "success": False,
                    "error": "没有可用的设备执行此任务"
                }
            
            # 3. 创建任务
            task = self._create_task(command, analysis, target_devices)
            
            # 4. 分发任务
            if len(target_devices) == 1:
                # 单设备任务
                result = await self._dispatch_single_device_task(task, target_devices[0])
            else:
                # 多设备协同任务
                result = await self._dispatch_cross_device_task(task, target_devices)
            
            return result
            
        except Exception as e:
            logger.error(f"❌ 任务路由失败: {e}")
            return {
                "success": False,
                "error": f"任务路由失败: {str(e)}"
            }
    
    async def _analyze_command(self, command: str, context: Dict = None) -> Dict:
        """
        分析命令，确定目标设备和任务类型
        
        这里使用简单的关键词匹配
        实际应该调用 NLU 引擎进行深度分析
        """
        analysis = {
            "command": command,
            "target_device_type": DeviceType.UNKNOWN,
            "task_type": TaskType.UI_AUTOMATION,
            "actions": [],
            "requires_cross_device": False
        }
        
        command_lower = command.lower()
        
        # 判断目标设备
        if any(keyword in command_lower for keyword in ["手机", "android", "移动端", "app"]):
            analysis["target_device_type"] = DeviceType.ANDROID
        elif any(keyword in command_lower for keyword in ["电脑", "pc", "windows", "桌面"]):
            analysis["target_device_type"] = DeviceType.WINDOWS
        elif any(keyword in command_lower for keyword in ["平板", "ipad", "tablet"]):
            analysis["target_device_type"] = DeviceType.IOS
        
        # 判断任务类型
        if any(keyword in command_lower for keyword in ["打开", "启动", "运行"]):
            analysis["task_type"] = TaskType.APP_CONTROL
            analysis["actions"].append("open")
        elif any(keyword in command_lower for keyword in ["点击", "按", "选择"]):
            analysis["task_type"] = TaskType.UI_AUTOMATION
            analysis["actions"].append("click")
        elif any(keyword in command_lower for keyword in ["输入", "填写", "写入"]):
            analysis["task_type"] = TaskType.UI_AUTOMATION
            analysis["actions"].append("input")
        elif any(keyword in command_lower for keyword in ["查询", "查看", "显示"]):
            analysis["task_type"] = TaskType.QUERY
            analysis["actions"].append("query")
        elif any(keyword in command_lower for keyword in ["音量", "亮度", "wifi", "蓝牙"]):
            analysis["task_type"] = TaskType.SYSTEM_CONTROL
        
        # 判断是否需要跨设备协同
        if any(keyword in command_lower for keyword in ["复制到", "发送到", "传输到", "同步"]):
            analysis["requires_cross_device"] = True
        
        return analysis
    
    def _select_devices(self, analysis: Dict) -> List[Device]:
        """选择合适的设备"""
        target_device_type = analysis["target_device_type"]
        
        if target_device_type == DeviceType.UNKNOWN:
            # 如果未指定设备，默认选择 Windows
            target_device_type = DeviceType.WINDOWS
        
        # 获取该类型的所有在线设备
        devices = self.get_devices_by_type(target_device_type)
        online_devices = [d for d in devices if d.status == "online"]
        
        if not online_devices:
            logger.warning(f"⚠️ 没有在线的 {target_device_type} 设备")
            return []
        
        # 简单策略：返回第一个在线设备
        # 实际可以根据设备负载、能力等进行智能选择
        return [online_devices[0]]
    
    def _create_task(self, command: str, analysis: Dict, target_devices: List[Device]) -> Dict:
        """创建任务"""
        task_id = str(uuid.uuid4())
        
        task = {
            "task_id": task_id,
            "command": command,
            "analysis": analysis,
            "target_devices": [d.device_id for d in target_devices],
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "payload": self._build_task_payload(analysis)
        }
        
        self.task_queue[task_id] = task
        return task
    
    def _build_task_payload(self, analysis: Dict) -> Dict:
        """构建任务 Payload"""
        payload = {
            "task_type": analysis["task_type"],
            "action": analysis["actions"][0] if analysis["actions"] else "",
            "target": "",
            "params": {}
        }
        
        # 根据任务类型构建具体参数
        # 这里是简化版本，实际应该更复杂
        
        return payload
    
    async def _dispatch_single_device_task(self, task: Dict, device: Device) -> Dict:
        """分发单设备任务 — 委托给 core.command_router 或直接 WebSocket"""
        try:
            logger.info(f"📤 分发任务到设备: {device.device_id}")

            # 优先通过统一命令路由器分发（已绑定 DeviceCommunication executor）
            try:
                from core.command_router import get_command_router, CommandRequest, CommandMode
                cmd_router = get_command_router()
                if cmd_router._executor is not None:
                    cmd_req = CommandRequest(
                        source="device_router",
                        targets=[device.device_id],
                        command=task["payload"].get("action", task["payload"].get("task_type", "")),
                        params=task["payload"].get("params", task["payload"]),
                        mode=CommandMode.SYNC,
                        timeout=30.0,
                    )
                    cmd_result = await cmd_router.dispatch(cmd_req)
                    target_result = cmd_result.targets.get(device.device_id)
                    if target_result:
                        return {
                            "success": target_result.status.value == "success",
                            "result": target_result.result,
                            "error": target_result.error,
                        }
            except Exception as route_err:
                logger.debug(f"CommandRouter 分发失败，回退 WebSocket: {route_err}")

            # 回退：直接通过 WebSocket 发送 AIP v3.0 消息
            if device.websocket:
                message = {
                    "version": "3.0",
                    "message_id": str(uuid.uuid4()),
                    "type": "command",
                    "device_id": device.device_id,
                    "task_id": task["task_id"],
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "payload": task["payload"],
                }
                await device.websocket.send(json.dumps(message))

                task_id = task["task_id"]
                for _ in range(30):
                    if task_id in self.task_results:
                        result = self.task_results[task_id]
                        del self.task_results[task_id]
                        return result
                    await asyncio.sleep(1)

                return {"success": False, "error": "任务执行超时"}
            else:
                return {"success": False, "error": "设备未连接"}

        except Exception as e:
            logger.error(f"❌ 任务分发失败: {e}")
            return {"success": False, "error": f"任务分发失败: {str(e)}"}
    
    async def _dispatch_cross_device_task(self, task: Dict, devices: List[Device]) -> Dict:
        """分发跨设备协同任务"""
        try:
            logger.info(f"🔄 分发跨设备任务到 {len(devices)} 个设备")
            
            # 将任务分解为多个子任务
            subtasks = self._decompose_task(task, devices)
            
            # 并行执行所有子任务
            results = await asyncio.gather(
                *[self._dispatch_single_device_task(subtask, device) 
                  for subtask, device in zip(subtasks, devices)],
                return_exceptions=True
            )
            
            # 汇总结果
            success = all(r.get("success", False) for r in results if isinstance(r, dict))
            
            return {
                "success": success,
                "subtask_results": results,
                "message": "跨设备任务执行完成" if success else "部分子任务执行失败"
            }
            
        except Exception as e:
            logger.error(f"❌ 跨设备任务分发失败: {e}")
            return {
                "success": False,
                "error": f"跨设备任务分发失败: {str(e)}"
            }
    
    def _decompose_task(self, task: Dict, devices: List[Device]) -> List[Dict]:
        """将跨设备任务分解为多个子任务"""
        # 简化版本：每个设备执行相同的任务
        # 实际应该根据任务类型智能分解
        return [task.copy() for _ in devices]
    
    async def handle_task_result(self, task_id: str, result: Dict):
        """处理任务执行结果"""
        try:
            self.task_results[task_id] = result
            
            if task_id in self.task_queue:
                task = self.task_queue[task_id]
                task["status"] = "completed" if result.get("success") else "failed"
                task["result"] = result
                task["completed_at"] = datetime.now().isoformat()
            
            logger.info(f"✅ 任务结果已记录: {task_id}")
            
        except Exception as e:
            logger.error(f"❌ 处理任务结果失败: {e}")
    
    def get_device_status(self) -> Dict:
        """获取所有设备状态"""
        return {
            "total_devices": len(self.devices),
            "online_devices": len([d for d in self.devices.values() if d.status == "online"]),
            "devices": [d.to_dict() for d in self.devices.values()]
        }


# 全局设备路由器实例
device_router = DeviceRouter()
