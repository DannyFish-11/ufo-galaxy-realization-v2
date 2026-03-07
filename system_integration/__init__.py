"""
系统集成模块
"""

from .hardware_trigger import (
    HardwareTriggerManager,
    SystemStateMachine,
    IntegratedSystemController,
    TriggerType,
    SystemState,
    TriggerEvent,
    StateTransition
)

from .fused_wake_decision import (
    FusedWakeDecision,
    FusedWakeResult,
    FusionRule,
    fused_wake_decision,
)

__all__ = [
    'HardwareTriggerManager',
    'SystemStateMachine',
    'IntegratedSystemController',
    'TriggerType',
    'SystemState',
    'TriggerEvent',
    'StateTransition',
    # 多模态融合唤醒决策
    'FusedWakeDecision',
    'FusedWakeResult',
    'FusionRule',
    'fused_wake_decision',
]
