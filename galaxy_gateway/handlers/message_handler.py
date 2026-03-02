"""
消息处理器

负责:
1. 路由不同类型的消息
2. 调用相应的处理逻辑
3. 生成响应消息
"""

import logging
from typing import Optional, Callable, Dict, Any
from datetime import datetime

from ..protocol import (
    AIPMessage, MessageType, TaskStatus, ResultStatus,
    create_error_message
)
from .device_manager import DeviceManager

logger = logging.getLogger(__name__)


class MessageHandler:
    """消息处理器"""
    
    def __init__(self, device_manager: DeviceManager):
        self.device_manager = device_manager
        self.task_handlers: Dict[str, Callable] = {}
        self.pending_tasks: Dict[str, dict] = {}  # task_id -> task_info
        
    def register_task_handler(self, task_type: str, handler: Callable):
        """注册任务处理器"""
        self.task_handlers[task_type] = handler
        logger.info(f"Registered task handler for: {task_type}")
    
    async def handle_message(self, device_id: str, message: AIPMessage) -> Optional[AIPMessage]:
        """处理消息并返回响应"""
        logger.debug(f"Handling message from {device_id}: {message.type}")
        
        try:
            handler = self._get_handler(message.type)
            if handler:
                return await handler(device_id, message)
            else:
                logger.warning(f"No handler for message type: {message.type}")
                return None
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            return create_error_message(device_id, str(e), message.message_id)
    
    def _get_handler(self, message_type: MessageType) -> Optional[Callable]:
        """获取消息处理器"""
        handlers = {
            MessageType.DEVICE_REGISTER: self._handle_register,
            MessageType.DEVICE_HEARTBEAT: self._handle_heartbeat,
            MessageType.DEVICE_STATUS: self._handle_device_status,
            MessageType.TASK_RESULT: self._handle_task_result,
            MessageType.COMMAND_RESULT: self._handle_command_result,
            MessageType.GUI_SCREEN_CONTENT: self._handle_screen_content,
            MessageType.ERROR: self._handle_error,
        }
        return handlers.get(message_type)
    
    async def _handle_register(self, device_id: str, message: AIPMessage) -> AIPMessage:
        """处理设备注册"""
        return self.device_manager.handle_register_message(message)
    
    async def _handle_heartbeat(self, device_id: str, message: AIPMessage) -> AIPMessage:
        """处理心跳"""
        self.device_manager.update_device_status(device_id, "online")
        return AIPMessage(
            type=MessageType.DEVICE_HEARTBEAT_ACK,
            device_id=device_id,
            correlation_id=message.message_id
        )
    
    async def _handle_device_status(self, device_id: str, message: AIPMessage) -> Optional[AIPMessage]:
        """处理设备状态更新"""
        status = message.payload.get("status", "unknown")
        self.device_manager.update_device_status(device_id, status)
        return None
    
    async def _handle_task_result(self, device_id: str, message: AIPMessage) -> Optional[AIPMessage]:
        """处理任务结果"""
        task_id = message.task_id
        if not task_id:
            return create_error_message(device_id, "Missing task_id", message.message_id)
        
        if task_id in self.pending_tasks:
            task_info = self.pending_tasks[task_id]
            task_info["status"] = message.task_status or TaskStatus.COMPLETED
            task_info["results"] = message.results
            task_info["completed_at"] = datetime.utcnow()
            
            logger.info(f"Task {task_id} completed with status: {task_info['status']}")
            
            # 如果有回调，执行回调
            if "callback" in task_info and task_info["callback"]:
                try:
                    await task_info["callback"](task_id, message)
                except Exception as e:
                    logger.error(f"Task callback error: {e}")
        
        return None
    
    async def _handle_command_result(self, device_id: str, message: AIPMessage) -> Optional[AIPMessage]:
        """处理命令结果"""
        for result in message.results:
            logger.info(f"Command {result.command_id} result: {result.status}")
        return None
    
    async def _handle_screen_content(self, device_id: str, message: AIPMessage) -> Optional[AIPMessage]:
        """处理屏幕内容"""
        logger.debug(f"Received screen content from {device_id}")
        # 可以在这里进行 GUI 分析
        return None
    
    async def _handle_error(self, device_id: str, message: AIPMessage) -> Optional[AIPMessage]:
        """处理错误消息"""
        logger.error(f"Error from device {device_id}: {message.error}")
        return None
    
    def create_task(
        self, 
        task_id: str, 
        device_id: str, 
        task_type: str,
        callback: Optional[Callable] = None
    ) -> dict:
        """创建任务记录"""
        task_info = {
            "task_id": task_id,
            "device_id": device_id,
            "task_type": task_type,
            "status": TaskStatus.PENDING,
            "created_at": datetime.utcnow(),
            "callback": callback
        }
        self.pending_tasks[task_id] = task_info
        return task_info
    
    def get_task(self, task_id: str) -> Optional[dict]:
        """获取任务信息"""
        return self.pending_tasks.get(task_id)
    
    def get_pending_tasks(self) -> list:
        """获取所有待处理任务"""
        return [
            t for t in self.pending_tasks.values()
            if t["status"] in [TaskStatus.PENDING, TaskStatus.RUNNING]
        ]
