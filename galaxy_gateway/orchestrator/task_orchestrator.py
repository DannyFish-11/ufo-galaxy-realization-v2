"""
任务编排器 (Orchestrator)

核心功能:
1. 接收用户任务请求
2. 分解任务为子任务
3. 分配任务到合适的设备
4. 协调多设备执行
5. 汇总执行结果
"""

import asyncio
import logging
import uuid
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
from enum import Enum

from ..protocol import (
    AIPMessage, MessageType, Command, CommandResult,
    TaskStatus, ResultStatus, DeviceCapability,
    create_task_message, create_gui_click_message,
    create_gui_input_message, create_screenshot_message
)
from ..handlers import DeviceManager, MessageHandler
from ..transport import WebSocketManager

logger = logging.getLogger(__name__)


class TaskPriority(Enum):
    """任务优先级"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


class Task:
    """任务定义"""
    
    def __init__(
        self,
        task_id: str,
        user_request: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout: int = 300
    ):
        self.task_id = task_id
        self.user_request = user_request
        self.priority = priority
        self.timeout = timeout
        self.status = TaskStatus.PENDING
        self.created_at = datetime.utcnow()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.assigned_device: Optional[str] = None
        self.commands: List[Command] = []
        self.results: List[CommandResult] = []
        self.error: Optional[str] = None
        self.metadata: Dict[str, Any] = {}


class TaskOrchestrator:
    """任务编排器"""
    
    def __init__(
        self,
        device_manager: DeviceManager,
        message_handler: MessageHandler,
        websocket_manager: WebSocketManager
    ):
        self.device_manager = device_manager
        self.message_handler = message_handler
        self.websocket_manager = websocket_manager
        
        self.tasks: Dict[str, Task] = {}
        self.task_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        
    async def start(self):
        """启动编排器"""
        self._running = True
        self._worker_task = asyncio.create_task(self._task_worker())
        logger.info("Task Orchestrator started")
    
    async def stop(self):
        """停止编排器"""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Task Orchestrator stopped")
    
    async def submit_task(
        self,
        user_request: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        target_device: Optional[str] = None,
        timeout: int = 300
    ) -> Task:
        """提交新任务"""
        task_id = str(uuid.uuid4())
        task = Task(
            task_id=task_id,
            user_request=user_request,
            priority=priority,
            timeout=timeout
        )
        
        if target_device:
            task.assigned_device = target_device
        
        self.tasks[task_id] = task
        await self.task_queue.put(task)
        
        logger.info(f"Task submitted: {task_id} - {user_request[:50]}...")
        return task
    
    async def _task_worker(self):
        """任务处理工作线程"""
        while self._running:
            try:
                task = await asyncio.wait_for(
                    self.task_queue.get(),
                    timeout=1.0
                )
                await self._process_task(task)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Task worker error: {e}")
    
    async def _process_task(self, task: Task):
        """处理单个任务"""
        logger.info(f"Processing task: {task.task_id}")
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()
        
        try:
            # 1. 选择目标设备
            device_id = await self._select_device(task)
            if not device_id:
                task.status = TaskStatus.FAILED
                task.error = "No suitable device available"
                return
            
            task.assigned_device = device_id
            
            # 2. 分解任务为命令
            commands = await self._decompose_task(task)
            task.commands = commands
            
            # 3. 发送任务到设备
            await self._send_task_to_device(task)
            
            # 4. 等待结果（带超时）
            await self._wait_for_completion(task)
            
        except Exception as e:
            logger.error(f"Task processing error: {e}")
            task.status = TaskStatus.FAILED
            task.error = str(e)
        finally:
            task.completed_at = datetime.utcnow()
    
    async def _select_device(self, task: Task) -> Optional[str]:
        """选择执行任务的设备"""
        # 如果已指定设备
        if task.assigned_device:
            if self.websocket_manager.is_device_connected(task.assigned_device):
                return task.assigned_device
            else:
                logger.warning(f"Assigned device {task.assigned_device} not connected")
        
        # 获取所有在线设备
        connected_devices = self.websocket_manager.get_connected_devices()
        if not connected_devices:
            return None
        
        # 简单策略：选择第一个在线设备
        # TODO: 可以扩展为更复杂的负载均衡策略
        return connected_devices[0]
    
    async def _decompose_task(self, task: Task) -> List[Command]:
        """分解任务为命令序列"""
        commands = []
        request = task.user_request.lower()
        
        # 简单的任务分解逻辑（可以扩展为 LLM 驱动）
        if "截图" in request or "screenshot" in request:
            commands.append(Command(
                tool_name="screenshot",
                tool_type="data_collection",
                parameters={}
            ))
        
        if "点击" in request or "click" in request:
            # 解析点击目标
            commands.append(Command(
                tool_name="click",
                tool_type="action",
                parameters={"target": request}
            ))
        
        if "输入" in request or "input" in request or "type" in request:
            commands.append(Command(
                tool_name="input_text",
                tool_type="action",
                parameters={"text": request}
            ))
        
        if "滑动" in request or "swipe" in request:
            commands.append(Command(
                tool_name="swipe",
                tool_type="action",
                parameters={"direction": "down"}
            ))
        
        # 如果没有识别到具体命令，默认先截图获取屏幕信息
        if not commands:
            commands.append(Command(
                tool_name="get_screen_content",
                tool_type="data_collection",
                parameters={}
            ))
        
        return commands
    
    async def _send_task_to_device(self, task: Task):
        """发送任务到设备"""
        message = create_task_message(
            device_id=task.assigned_device,
            task_id=task.task_id,
            commands=task.commands
        )
        message.payload["user_request"] = task.user_request
        
        # 注册任务回调
        self.message_handler.create_task(
            task_id=task.task_id,
            device_id=task.assigned_device,
            task_type="user_task",
            callback=self._on_task_result
        )
        
        success = await self.websocket_manager.send_message(
            task.assigned_device,
            message
        )
        
        if not success:
            raise Exception(f"Failed to send task to device {task.assigned_device}")
    
    async def _wait_for_completion(self, task: Task):
        """等待任务完成"""
        start_time = datetime.utcnow()
        
        while True:
            # 检查超时
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            if elapsed > task.timeout:
                task.status = TaskStatus.FAILED
                task.error = "Task timeout"
                return
            
            # 检查任务状态
            task_info = self.message_handler.get_task(task.task_id)
            if task_info:
                if task_info["status"] == TaskStatus.COMPLETED:
                    task.status = TaskStatus.COMPLETED
                    task.results = task_info.get("results", [])
                    return
                elif task_info["status"] == TaskStatus.FAILED:
                    task.status = TaskStatus.FAILED
                    return
            
            await asyncio.sleep(0.5)
    
    async def _on_task_result(self, task_id: str, message: AIPMessage):
        """任务结果回调"""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.results = message.results
            logger.info(f"Task {task_id} received results")
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        return self.tasks.get(task_id)
    
    def get_all_tasks(self) -> List[Task]:
        """获取所有任务"""
        return list(self.tasks.values())
    
    def get_pending_tasks(self) -> List[Task]:
        """获取待处理任务"""
        return [t for t in self.tasks.values() if t.status == TaskStatus.PENDING]
    
    def get_running_tasks(self) -> List[Task]:
        """获取运行中任务"""
        return [t for t in self.tasks.values() if t.status == TaskStatus.RUNNING]
    
    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        if task_id not in self.tasks:
            return False
        
        task = self.tasks[task_id]
        if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
            return False
        
        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.utcnow()
        
        # 发送取消消息到设备
        if task.assigned_device:
            cancel_message = AIPMessage(
                type=MessageType.TASK_CANCEL,
                device_id=task.assigned_device,
                task_id=task_id
            )
            await self.websocket_manager.send_message(
                task.assigned_device,
                cancel_message
            )
        
        logger.info(f"Task cancelled: {task_id}")
        return True


class MultiDeviceOrchestrator(TaskOrchestrator):
    """多设备协同编排器"""
    
    async def submit_multi_device_task(
        self,
        user_request: str,
        device_ids: List[str],
        coordination_mode: str = "parallel"  # parallel, sequential, conditional
    ) -> List[Task]:
        """提交多设备协同任务"""
        tasks = []
        
        if coordination_mode == "parallel":
            # 并行执行
            for device_id in device_ids:
                task = await self.submit_task(
                    user_request=user_request,
                    target_device=device_id
                )
                tasks.append(task)
        
        elif coordination_mode == "sequential":
            # 顺序执行
            for device_id in device_ids:
                task = await self.submit_task(
                    user_request=user_request,
                    target_device=device_id
                )
                tasks.append(task)
                # 等待当前任务完成
                await self._wait_for_completion(task)
        
        return tasks
    
    async def broadcast_command(self, command: Command) -> Dict[str, CommandResult]:
        """向所有设备广播命令"""
        results = {}
        connected_devices = self.websocket_manager.get_connected_devices()
        
        for device_id in connected_devices:
            task = await self.submit_task(
                user_request=f"Execute command: {command.tool_name}",
                target_device=device_id
            )
            task.commands = [command]
            await self._send_task_to_device(task)
        
        return results
