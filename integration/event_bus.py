"""
UFO Galaxy 事件总线系统
实现UI与L4主循环之间的双向通信
"""

import asyncio
import logging
from typing import Dict, Any, List, Callable, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
import json
import weakref


class EventType(Enum):
    """事件类型枚举"""
    # UI → L4 事件
    GOAL_SUBMITTED = auto()           # 用户提交目标
    COMMAND_RECEIVED = auto()         # 接收到命令
    USER_INPUT = auto()               # 用户输入
    
    # L4 → UI 事件
    GOAL_DECOMPOSITION_STARTED = auto()   # 目标分解开始
    GOAL_DECOMPOSITION_COMPLETED = auto() # 目标分解完成
    PLAN_GENERATION_STARTED = auto()      # 计划生成开始
    PLAN_GENERATION_COMPLETED = auto()    # 计划生成完成
    ACTION_EXECUTION_STARTED = auto()     # 动作执行开始
    ACTION_EXECUTION_PROGRESS = auto()    # 动作执行进度
    ACTION_EXECUTION_COMPLETED = auto()   # 动作执行完成
    TASK_COMPLETED = auto()               # 任务完成
    ERROR_OCCURRED = auto()               # 错误发生
    
    # 硬件触发 → UI 事件
    HARDWARE_TRIGGER_DETECTED = auto()    # 硬件触发检测
    STATE_TRANSITION = auto()             # 状态转换
    WAKEUP_SIGNAL = auto()                # 唤醒信号
    
    # UI状态 → 硬件触发 事件
    ANIMATION_STARTED = auto()            # 动画开始
    ANIMATION_COMPLETED = auto()          # 动画完成
    UI_STATE_CHANGED = auto()             # UI状态改变


@dataclass
class UIGalaxyEvent:
    """UI-Galaxy事件数据类"""
    event_type: EventType
    source: str                          # 事件来源 (ui/l4/hardware)
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    event_id: str = field(default_factory=lambda: f"evt_{datetime.now().timestamp()}")
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.name,
            "source": self.source,
            "data": self.data,
            "timestamp": self.timestamp.isoformat()
        }
    
    def to_json(self) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), default=str)


class EventBus:
    """
    UFO Galaxy 事件总线
    实现发布-订阅模式，支持同步和异步回调
    """
    
    _instance: Optional['EventBus'] = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self._subscribers: Dict[EventType, Set[Callable]] = {event_type: set() for event_type in EventType}
        self._async_subscribers: Dict[EventType, Set[Callable]] = {event_type: set() for event_type in EventType}
        self._event_history: List[UIGalaxyEvent] = []
        self._max_history = 1000
        self._logger = logging.getLogger("EventBus")
        
        # 事件队列（用于异步处理）
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._processing_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self):
        """启动事件总线"""
        if not self._running:
            self._running = True
            self._processing_task = asyncio.create_task(self._process_events())
            self._logger.info("事件总线已启动")
    
    async def stop(self):
        """停止事件总线"""
        if self._running:
            self._running = False
            if self._processing_task:
                self._processing_task.cancel()
                try:
                    await self._processing_task
                except asyncio.CancelledError:
                    pass
            self._logger.info("事件总线已停止")
    
    async def _process_events(self):
        """处理事件队列"""
        while self._running:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)
                await self._dispatch_event(event)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self._logger.error(f"事件处理错误: {e}")
    
    async def _dispatch_event(self, event: UIGalaxyEvent):
        """分发事件到所有订阅者"""
        # 同步订阅者
        for callback in self._subscribers.get(event.event_type, set()):
            try:
                callback(event)
            except Exception as e:
                self._logger.error(f"同步回调错误: {e}")
        
        # 异步订阅者
        for async_callback in self._async_subscribers.get(event.event_type, set()):
            try:
                await async_callback(event)
            except Exception as e:
                self._logger.error(f"异步回调错误: {e}")
    
    def subscribe(self, event_type: EventType, callback: Callable, async_callback: bool = False):
        """
        订阅事件
        
        Args:
            event_type: 事件类型
            callback: 回调函数
            async_callback: 是否为异步回调
        """
        if async_callback:
            self._async_subscribers[event_type].add(callback)
        else:
            self._subscribers[event_type].add(callback)
        
        self._logger.debug(f"订阅 {event_type.name}, 异步={async_callback}")
    
    def unsubscribe(self, event_type: EventType, callback: Callable, async_callback: bool = False):
        """取消订阅"""
        if async_callback:
            self._async_subscribers[event_type].discard(callback)
        else:
            self._subscribers[event_type].discard(callback)
    
    def publish(self, event: UIGalaxyEvent, async_dispatch: bool = True):
        """
        发布事件
        
        Args:
            event: 要发布的事件
            async_dispatch: 是否异步分发
        """
        # 记录事件历史
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]
        
        if async_dispatch and self._running:
            # 异步分发
            self._event_queue.put_nowait(event)
        else:
            # 同步分发
            asyncio.create_task(self._dispatch_event(event))
    
    def publish_sync(self, event_type: EventType, source: str, data: Dict[str, Any] = None):
        """同步发布事件（快捷方法）"""
        event = UIGalaxyEvent(
            event_type=event_type,
            source=source,
            data=data or {}
        )
        self.publish(event)
    
    def get_event_history(self, event_type: Optional[EventType] = None, 
                          limit: int = 100) -> List[UIGalaxyEvent]:
        """获取事件历史"""
        events = self._event_history
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events[-limit:]
    
    def clear_history(self):
        """清空事件历史"""
        self._event_history.clear()


# 全局事件总线实例
event_bus = EventBus()


class UIProgressCallback:
    """
    UI进度回调类
    用于L4主循环向UI报告进度
    """
    
    def __init__(self):
        self._logger = logging.getLogger("UIProgressCallback")
    
    def on_goal_decomposition_started(self, goal_description: str):
        """目标分解开始"""
        event_bus.publish_sync(
            EventType.GOAL_DECOMPOSITION_STARTED,
            "l4",
            {"goal_description": goal_description}
        )
        self._logger.info(f"目标分解开始: {goal_description}")
    
    def on_goal_decomposition_completed(self, goal_description: str, subtasks: List[Dict]):
        """目标分解完成"""
        event_bus.publish_sync(
            EventType.GOAL_DECOMPOSITION_COMPLETED,
            "l4",
            {
                "goal_description": goal_description,
                "subtasks": subtasks,
                "subtask_count": len(subtasks)
            }
        )
        self._logger.info(f"目标分解完成: {len(subtasks)} 个子任务")
    
    def on_plan_generation_started(self, goal_description: str):
        """计划生成开始"""
        event_bus.publish_sync(
            EventType.PLAN_GENERATION_STARTED,
            "l4",
            {"goal_description": goal_description}
        )
    
    def on_plan_generation_completed(self, goal_description: str, actions: List[Dict]):
        """计划生成完成"""
        event_bus.publish_sync(
            EventType.PLAN_GENERATION_COMPLETED,
            "l4",
            {
                "goal_description": goal_description,
                "actions": actions,
                "action_count": len(actions)
            }
        )
        self._logger.info(f"计划生成完成: {len(actions)} 个动作")
    
    def on_action_execution_started(self, action_id: str, action_command: str):
        """动作执行开始"""
        event_bus.publish_sync(
            EventType.ACTION_EXECUTION_STARTED,
            "l4",
            {
                "action_id": action_id,
                "action_command": action_command
            }
        )
    
    def on_action_execution_progress(self, action_id: str, progress: float, message: str = ""):
        """动作执行进度更新"""
        event_bus.publish_sync(
            EventType.ACTION_EXECUTION_PROGRESS,
            "l4",
            {
                "action_id": action_id,
                "progress": progress,
                "message": message
            }
        )
    
    def on_action_execution_completed(self, action_id: str, success: bool, result: Dict):
        """动作执行完成"""
        event_bus.publish_sync(
            EventType.ACTION_EXECUTION_COMPLETED,
            "l4",
            {
                "action_id": action_id,
                "success": success,
                "result": result
            }
        )
    
    def on_task_completed(self, goal_description: str, success: bool, summary: Dict):
        """任务完成"""
        event_bus.publish_sync(
            EventType.TASK_COMPLETED,
            "l4",
            {
                "goal_description": goal_description,
                "success": success,
                "summary": summary
            }
        )
        self._logger.info(f"任务完成: {goal_description}, 成功={success}")
    
    def on_error(self, error_message: str, error_details: Dict = None):
        """错误发生"""
        event_bus.publish_sync(
            EventType.ERROR_OCCURRED,
            "l4",
            {
                "error_message": error_message,
                "error_details": error_details or {}
            }
        )
        self._logger.error(f"错误: {error_message}")


# 全局进度回调实例
ui_progress_callback = UIProgressCallback()
