"""
系统集成模块
"""

from .hardware_trigger import (
    HardwareTriggerManager,
    SystemStateMachine,
    IntegratedSystemController,
    TriggerType,
    SystemState,
    GestureType,
    TriggerEvent,
    StateTransition
)

__all__ = [
    'HardwareTriggerManager',
    'SystemStateMachine',
    'IntegratedSystemController',
    'TriggerType',
    'SystemState',
    'GestureType',
    'TriggerEvent',
    'StateTransition'
]
