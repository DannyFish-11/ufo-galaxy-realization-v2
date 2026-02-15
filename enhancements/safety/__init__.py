"""
安全模块 (Safety Module)
负责错误处理、故障恢复和安全检查
"""

from .safety_manager import (
    SafetyManager,
    ErrorHandler,
    SafetyLevel,
    RecoveryStrategy,
    SafetyRule,
    SafetyViolation,
    RecoveryAction
)

__all__ = [
    'SafetyManager',
    'ErrorHandler',
    'SafetyLevel',
    'RecoveryStrategy',
    'SafetyRule',
    'SafetyViolation',
    'RecoveryAction'
]
