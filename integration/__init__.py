"""
UFO Galaxy 集成模块
实现UI与L4主循环的双向通信
"""

from .event_bus import (
    EventBus,
    EventType,
    UIGalaxyEvent,
    UIProgressCallback,
    event_bus,
    ui_progress_callback
)

__all__ = [
    'EventBus',
    'EventType',
    'UIGalaxyEvent',
    'UIProgressCallback',
    'event_bus',
    'ui_progress_callback'
]
