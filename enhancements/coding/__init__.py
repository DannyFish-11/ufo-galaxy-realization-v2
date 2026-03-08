"""
自主编程模块（v2）
"""

from .autonomous_coding_engine_v2 import (
    AutonomousCodingEngineV2,
    CodingContext,
    CodingResult,
    CodingTaskType,
)

# 向后兼容别名
AutonomousCodingEngine = AutonomousCodingEngineV2

__all__ = [
    'AutonomousCodingEngine',
    'AutonomousCodingEngineV2',
    'CodingContext',
    'CodingResult',
    'CodingTaskType',
]
