"""
UFO Galaxy Gateway - 跨平台分布式 Agent 网关

核心功能:
1. WebSocket 服务端，接收设备连接
2. AIP v3.0 协议处理
3. 任务调度和编排
4. 多设备协同
5. 智能唤醒路由 (WakeRouter)
6. 统一唤醒事件总线 (WakeEventBus)
7. 会话漫游管理 (SessionRoaming)
"""

__version__ = "3.0.0"
__author__ = "UFO Galaxy Team"

from .wake_router import WakeRouter, WakeEvent, WakeTaskType, RouteDecision, wake_router
from .wake_event_bus import WakeEventBus, RawWakeEvent, wake_event_bus
from .session_roaming import (
    SessionRoamingManager,
    Session,
    SessionContext,
    SessionState,
    session_roaming,
)

__all__ = [
    # 智能唤醒路由
    "WakeRouter",
    "WakeEvent",
    "WakeTaskType",
    "RouteDecision",
    "wake_router",
    # 唤醒事件总线
    "WakeEventBus",
    "RawWakeEvent",
    "wake_event_bus",
    # 会话漫游
    "SessionRoamingManager",
    "Session",
    "SessionContext",
    "SessionState",
    "session_roaming",
]
