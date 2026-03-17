"""
Galaxy 事件总线系统
实现UI与L4主循环之间的双向通信
"""

import asyncio
import json
import logging
import os
import uuid
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Set


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
    
    # 命令路由事件
    COMMAND_DISPATCHED = auto()           # 命令已分发
    COMMAND_PROGRESS = auto()             # 命令执行进度
    COMMAND_RESULT = auto()               # 命令执行结果
    COMMAND_CANCELLED = auto()            # 命令已取消

    # AI 意图事件
    AI_INTENT_PARSED = auto()             # AI 意图已解析
    AI_RECOMMENDATION = auto()            # AI 推荐生成

    # 性能/监控事件
    PERFORMANCE_ALERT = auto()            # 性能告警
    CIRCUIT_BREAKER_OPEN = auto()         # 熔断器打开
    CIRCUIT_BREAKER_CLOSE = auto()        # 熔断器关闭

    # UI状态 → 硬件触发 事件
    ANIMATION_STARTED = auto()            # 动画开始
    ANIMATION_COMPLETED = auto()          # 动画完成
    UI_STATE_CHANGED = auto()             # UI状态改变

    # 设备生命周期事件
    DEVICE_CONNECTED = auto()             # 设备连接
    DEVICE_DISCONNECTED = auto()          # 设备断开
    DEVICE_HEARTBEAT = auto()             # 设备心跳
    DEVICE_REGISTERED = auto()            # 设备注册
    DEVICE_UNREGISTERED = auto()          # 设备注销

    # 编排事件
    ORCHESTRATION_STARTED = auto()        # 编排任务开始
    ORCHESTRATION_PROGRESS = auto()       # 编排任务进度
    ORCHESTRATION_COMPLETED = auto()      # 编排任务完成

    # 会话事件
    SESSION_MIGRATED = auto()             # 会话迁移
    SESSION_CREATED = auto()              # 会话创建
    SESSION_CLOSED = auto()               # 会话关闭

    # Agentic OS — MasterBrain 任务生命周期
    TASK_DISPATCHED = auto()              # 任务已分发到 Worker
    TASK_RESULT_RECEIVED = auto()         # 收到 Worker 任务结果

    # Agentic OS — Worker 拓扑
    WORKER_REGISTERED = auto()            # Worker 注册
    WORKER_HEARTBEAT_RECEIVED = auto()    # Worker 心跳
    WORKER_DEAD = auto()                  # Worker 失联

    # Agentic OS — MCP 自工具制造
    MCP_TOOL_GENERATED = auto()           # LLM 生成了工具代码
    MCP_TOOL_REGISTERED = auto()          # 工具已注册到 MCP Gateway
    MCP_TOOL_RELOADED = auto()            # 工具已热重载

    # 能力总线更新事件（MCP/Skill 加载/卸载后触发）
    CAPABILITY_UPDATED = auto()           # CapabilityRegistry 已刷新（MCP/Skill 变更后）

    # Agentic OS — ACL 审计
    ACL_VALIDATION_FAILED = auto()        # ACL 验证失败
    ACL_NORMALIZATION_APPLIED = auto()    # ACL 应用了归一化

    # Agentic OS — NATS 总线健康
    NATS_CONNECTED = auto()               # NATS 已连接
    NATS_DISCONNECTED = auto()            # NATS 已断开
    NATS_RECONNECTING = auto()            # NATS 正在重连

    # Multimodal Perception Bus (PR 1)
    PERCEPTION_INGESTED = auto()          # 多模态输入已摄入（原始）
    PERCEPTION_FUSED = auto()             # 多模态上下文已融合（摘要就绪）


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
    Galaxy 事件总线
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
        from collections import deque
        self._event_history: deque = deque(maxlen=1000)
        self._max_history = 1000
        self._logger = logging.getLogger("EventBus")
        
        # 事件队列（有界，防止 OOM；满时丢弃最旧事件）
        self._event_queue: asyncio.Queue = asyncio.Queue(maxsize=5000)
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

    def _dispatch_sync_callbacks(self, event: UIGalaxyEvent):
        """仅调用同步回调（无事件循环时使用）"""
        for callback in self._subscribers.get(event.event_type, set()):
            try:
                callback(event)
            except Exception as e:
                self._logger.error(f"同步回调错误: {e}")
    
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
            try:
                self._event_queue.put_nowait(event)
            except asyncio.QueueFull:
                self._logger.warning(f"事件队列已满，丢弃事件: {event.event_type.name}")
        else:
            # 同步分发: 优先尝试在运行中的事件循环创建 task, 无循环时直接调用同步回调
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._dispatch_event(event))
            except RuntimeError:
                # 没有运行中的事件循环 — 直接调用同步回调
                self._dispatch_sync_callbacks(event)
    
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


# ============================================================================
# M2 统一事件 Schema 校验与发布
# ============================================================================

_m2_logger = logging.getLogger("EventBus.M2")

# 缓存加载的 JSON Schema（懒加载）
_m2_schema: Optional[Dict[str, Any]] = None
_jsonschema_available: Optional[bool] = None


def _load_m2_schema() -> Optional[Dict[str, Any]]:
    """懒加载 contracts/event_schema.json"""
    global _m2_schema
    if _m2_schema is not None:
        return _m2_schema

    schema_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "contracts",
        "event_schema.json",
    )
    try:
        with open(schema_path, "r", encoding="utf-8") as fh:
            _m2_schema = json.load(fh)
        return _m2_schema
    except Exception as exc:
        _m2_logger.warning("M2 schema 文件加载失败: %s", exc)
        return None


def _is_jsonschema_available() -> bool:
    global _jsonschema_available
    if _jsonschema_available is None:
        try:
            import jsonschema  # noqa: F401
            _jsonschema_available = True
        except ImportError:
            _jsonschema_available = False
    return _jsonschema_available


def validate_m2_event(event_dict: Dict[str, Any]) -> bool:
    """
    校验 M2 事件对象是否符合 contracts/event_schema.json。

    - 如果 jsonschema 库不可用，仅做基础必填字段检查。
    - 校验失败时记录日志但不抛出异常（不崩溃）。

    Returns:
        True  校验通过
        False 校验失败（已记录日志）
    """
    required = {"event_id", "event_type", "timestamp", "source", "payload"}
    missing = required - set(event_dict.keys())
    if missing:
        _m2_logger.warning("M2 事件缺少必填字段: %s | event=%s", missing, event_dict.get("event_id", "<unknown>"))
        return False

    if not isinstance(event_dict.get("source"), dict) or not event_dict["source"].get("device_id"):
        _m2_logger.warning("M2 事件 source.device_id 缺失 | event_id=%s", event_dict.get("event_id"))
        return False

    if _is_jsonschema_available():
        schema = _load_m2_schema()
        if schema is not None:
            try:
                import jsonschema
                jsonschema.validate(instance=event_dict, schema=schema)
            except jsonschema.ValidationError as exc:
                _m2_logger.warning(
                    "M2 事件 schema 校验失败: %s | event_id=%s event_type=%s",
                    exc.message,
                    event_dict.get("event_id"),
                    event_dict.get("event_type"),
                )
                return False
            except Exception as exc:
                _m2_logger.warning("M2 schema 校验异常: %s", exc)
                return False

    return True


def build_m2_event(
    event_type: str,
    device_id: str,
    payload: Dict[str, Any],
    *,
    node: Optional[str] = None,
    task_id: Optional[str] = None,
    span_id: Optional[str] = None,
    event_id: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """
    构建符合 M2 统一事件 Schema 的事件字典。

    Args:
        event_type: M2 事件类型（如 "task.lifecycle"）
        device_id: 来源设备 ID
        payload: 事件 payload
        node: 可选，组件名称
        task_id: 可选，关联任务 ID
        span_id: 可选，Span ID
        event_id: 可选，覆盖自动生成的 event_id
        timestamp: 可选，覆盖自动生成的时间戳（ISO 8601 UTC）

    Returns:
        M2 事件字典
    """
    source: Dict[str, Any] = {"device_id": device_id}
    if node:
        source["node"] = node

    event: Dict[str, Any] = {
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": event_type,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "source": source,
        "payload": payload,
    }

    trace: Dict[str, str] = {}
    if task_id:
        trace["task_id"] = task_id
    if span_id:
        trace["span_id"] = span_id
    if trace:
        event["trace"] = trace

    return event


def publish_m2_event(
    event_dict: Dict[str, Any],
    *,
    validate: bool = True,
) -> bool:
    """
    发布 M2 统一事件。

    发布前可选地校验 schema（失败不崩溃，仅记录日志）。
    同时将事件以 UIGalaxyEvent 格式发布到现有 EventBus，
    保持旧有订阅者的兼容性。

    Args:
        event_dict: M2 事件字典（建议通过 build_m2_event 构建）
        validate: 是否在发布前进行 schema 校验（默认 True）

    Returns:
        True  发布成功（含校验通过）
        False 校验失败（事件未发布）
    """
    if validate and not validate_m2_event(event_dict):
        return False

    # 将 M2 事件发布到 EventBus（作为通用数据事件，不破坏现有订阅）
    try:
        m2_legacy_event = UIGalaxyEvent(
            event_type=EventType.COMMAND_DISPATCHED,  # 中性事件类型，仅作传输载体
            source=event_dict.get("source", {}).get("device_id", "m2"),
            data={
                "_m2": True,
                **event_dict,
            },
        )
        event_bus.publish(m2_legacy_event)
    except Exception as exc:
        _m2_logger.debug("M2 事件写入 EventBus 失败（非致命）: %s", exc)

    _m2_logger.debug(
        "M2 事件已发布: event_type=%s event_id=%s",
        event_dict.get("event_type"),
        event_dict.get("event_id"),
    )
    return True


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
