"""
Galaxy 集成模块
实现UI与L4主循环的双向通信
"""

from .event_bus import (
    EventBus,
    EventType,
    UIGalaxyEvent,
    UIProgressCallback,
    event_bus,
    ui_progress_callback,
    build_m2_event,
    publish_m2_event,
    validate_m2_event,
    safe_json_dumps,
)

__all__ = [
    'EventBus',
    'EventType',
    'UIGalaxyEvent',
    'UIProgressCallback',
    'event_bus',
    'ui_progress_callback',
    'build_m2_event',
    'publish_m2_event',
    'validate_m2_event',
    'safe_json_dumps',
]
