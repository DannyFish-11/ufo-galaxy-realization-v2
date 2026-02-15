"""
跨设备任务编排器

功能：
1. 接收来自 NLU 引擎的任务步骤
2. 将任务分发到不同的设备
3. 管理任务依赖关系
4. 收集执行结果并返回

作者：Manus AI
日期：2025-01-20
"""

import asyncio
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import websockets

from enhanced_nlu_engine import TaskStep, TargetDevice

@dataclass
class DeviceInfo:
    """设备信息"""
    device_id: str
    device_type: TargetDevice
    websocket: Optional[Any]  # WebSocket 连接
    status: str  # "online", "offline", "busy"
    capabilities: List[str]

class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class TaskExecution:
    """任务执行记录"""
    task_id: str
    step: TaskStep
    device: DeviceInfo
    status: TaskStatus
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class TaskOrchestrator:
    """跨设备任务编排器"""
    
    def __init__(self):
        """初始化编排器"""
        self.devices: Dict[str, DeviceInfo] = {}
        self.task_executions: Dict[str, TaskExecution] = {}
        self.task_results: Dict[int, Dict[str, Any]] = {}  # step_id -> result
    
    def register_device(self, device_info: DeviceInfo):
        """
        注册设备
        
        Args:
            device_info: 设备信息
        """
        self.devices[device_info.device_id] = device_info
        print(f"设备已注册: {device_info.device_id} ({device_info.device_type.value})")
    
    def unregister_device(self, device_id: str):
        """注销设备"""
        if device_id in self.devices:
            del self.devices[device_id]
            print(f"设备已注销: {device_id}")
    
    def get_available_device(self, device_type: TargetDevice) -> Optional[DeviceInfo]:
        """
        获取可用设备
        
        Args:
            device_type: 设备类型
        
        Returns:
            可用的设备信息，如果没有则返回 None
        """
        for device in self.devices.values():
            if device.device_type == device_type and device.status == "online":
                return device
        return None
    
    async def execute_task(self, task_id: str, steps: List[TaskStep]) -> Dict[str, Any]:
        """
        执行任务
        
        Args:
            task_id: 任务 ID
            steps: 任务步骤列表
        
        Returns:
            执行结果
        """
        print(f"\n{'='*60}")
        print(f"开始执行任务: {task_id}")
        print(f"总步骤数: {len(steps)}")
        print(f"{'='*60}\n")
        
        # 清空之前的结果
        self.task_results.clear()
        
        # 按步骤执行
        for step in steps:
            # 检查依赖
            if not self._check_dependencies(step):
                return {
                    "status": "failed",
                    "message": f"步骤 {step.step_id} 的依赖未满足",
                    "step_id": step.step_id
                }
            
            # 执行步骤
            result = await self._execute_step(task_id, step)
            
            # 保存结果
            self.task_results[step.step_id] = result
            
            # 检查是否失败
            if result.get("status") == "failed":
                return {
                    "status": "failed",
                    "message": f"步骤 {step.step_id} 执行失败",
                    "step_id": step.step_id,
                    "error": result.get("error")
                }
        
        print(f"\n{'='*60}")
        print(f"任务执行完成: {task_id}")
        print(f"{'='*60}\n")
        
        return {
            "status": "completed",
            "task_id": task_id,
            "results": self.task_results
        }
    
    def _check_dependencies(self, step: TaskStep) -> bool:
        """检查步骤的依赖是否已完成"""
        for dep_id in step.depends_on:
            if dep_id not in self.task_results:
                return False
            if self.task_results[dep_id].get("status") != "completed":
                return False
        return True
    
    async def _execute_step(self, task_id: str, step: TaskStep) -> Dict[str, Any]:
        """
        执行单个步骤
        
        Args:
            task_id: 任务 ID
            step: 任务步骤
        
        Returns:
            执行结果
        """
        print(f"执行步骤 {step.step_id}: {step.action} on {step.device.value}")
        
        # 选择设备
        device = self.get_available_device(step.device)
        
        if device is None:
            # 如果是 AUTO，尝试其他设备
            if step.device == TargetDevice.AUTO:
                device = self._select_best_device(step.action)
            
            if device is None:
                return {
                    "status": "failed",
                    "error": f"没有可用的 {step.device.value} 设备"
                }
        
        # 标记设备为忙碌
        device.status = "busy"
        
        try:
            # 发送命令到设备
            result = await self._send_command_to_device(device, step)
            
            print(f"步骤 {step.step_id} 完成: {result.get('message', 'OK')}")
            
            return {
                "status": "completed",
                "step_id": step.step_id,
                "device_id": device.device_id,
                "result": result
            }
        except Exception as e:
            print(f"步骤 {step.step_id} 失败: {str(e)}")
            return {
                "status": "failed",
                "step_id": step.step_id,
                "error": str(e)
            }
        finally:
            # 恢复设备状态
            device.status = "online"
    
    def _select_best_device(self, action: str) -> Optional[DeviceInfo]:
        """根据动作选择最佳设备"""
        # 简单的启发式规则
        if "video" in action or "generate" in action:
            return self.get_available_device(TargetDevice.WINDOWS)
        elif "location" in action or "camera" in action:
            return self.get_available_device(TargetDevice.ANDROID)
        elif "quantum" in action or "compute" in action:
            return self.get_available_device(TargetDevice.CLOUD)
        else:
            # 默认选择第一个可用设备
            for device in self.devices.values():
                if device.status == "online":
                    return device
        return None
    
    async def _send_command_to_device(self, device: DeviceInfo, step: TaskStep) -> Dict[str, Any]:
        """
        发送命令到设备
        
        Args:
            device: 目标设备
            step: 任务步骤
        
        Returns:
            执行结果
        """
        # 构造 AIP 消息
        message = {
            "protocol": "AIP/1.0",
            "type": "command",
            "source_node": "Node_50_Transformer",
            "target_node": device.device_id,
            "timestamp": int(asyncio.get_event_loop().time()),
            "payload": {
                "action": step.action,
                "parameters": step.parameters
            }
        }
        
        if device.websocket:
            # 发送到真实设备
            await device.websocket.send(json.dumps(message))
            
            # 等待响应
            response = await device.websocket.recv()
            return json.loads(response)
        else:
            # 模拟执行（用于测试）
            return {
                "status": "success",
                "message": f"模拟执行: {step.action}",
                "device": device.device_id
            }

# 使用示例
async def main():
    orchestrator = TaskOrchestrator()
    
    # 注册模拟设备
    orchestrator.register_device(DeviceInfo(
        device_id="Windows_PC_001",
        device_type=TargetDevice.WINDOWS,
        websocket=None,
        status="online",
        capabilities=["ui_automation", "video_generation"]
    ))
    
    orchestrator.register_device(DeviceInfo(
        device_id="Android_Phone_001",
        device_type=TargetDevice.ANDROID,
        websocket=None,
        status="online",
        capabilities=["location", "camera", "ui_automation"]
    ))
    
    # 创建测试任务
    from enhanced_nlu_engine import EnhancedNLUEngine
    
    engine = EnhancedNLUEngine(use_ai_model=False)
    
    # 测试 1：简单任务
    intent = engine.understand("打开微信")
    steps = engine.plan_task(intent)
    result = await orchestrator.execute_task("task_001", steps)
    print(f"\n任务结果: {json.dumps(result, indent=2, ensure_ascii=False)}")
    
    # 测试 2：跨设备任务
    intent = engine.understand("把手机上的照片发送到电脑")
    steps = engine.plan_task(intent)
    result = await orchestrator.execute_task("task_002", steps)
    print(f"\n任务结果: {json.dumps(result, indent=2, ensure_ascii=False)}")

if __name__ == "__main__":
    asyncio.run(main())
