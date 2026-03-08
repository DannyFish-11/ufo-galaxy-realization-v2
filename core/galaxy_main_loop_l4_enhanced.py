"""
galaxy_main_loop_l4_enhanced — 兼容层 (shim)
============================================

为 integration/ 和 windows_client/ 提供 GalaxyMainLoopL4Enhanced 接口,
实际底层使用项目根目录的 galaxy_main_loop_l4.GalaxyMainLoopL4。

外部代码可直接导入:
    from core.galaxy_main_loop_l4_enhanced import (
        GalaxyMainLoopL4Enhanced, get_galaxy_loop, PendingGoal
    )
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# 确保项目根目录在 sys.path 中，使 galaxy_main_loop_l4 可导入
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from galaxy_main_loop_l4 import GalaxyMainLoopL4  # noqa: E402


class GalaxyMainLoopL4Enhanced(GalaxyMainLoopL4):
    """
    GalaxyMainLoopL4 的增强封装，补充 UI / WebSocket 层需要的同步入口。

    向后兼容: 与 GalaxyMainLoopL4 完全相同，额外提供:
    - receive_goal(description) → goal_id (同步方法，供 UI 层直接调用)
    """

    def receive_goal(self, goal_description: str, goal_type: str = "task_execution") -> str:
        """
        同步接收目标，将其加入内部目标队列并返回生成的目标 ID。

        这是 UI / WebSocket 层向 L4 主循环提交目标的主要入口。

        Args:
            goal_description: 自然语言目标描述。
            goal_type: 目标类型字符串，默认 "task_execution"。

        Returns:
            生成的目标 ID 字符串（可用于后续状态查询）。
        """
        # 延迟导入：enhancements.reasoning 依赖 numpy 等可选包，放在方法内部
        # 可在缺少这些依赖时跳过，而不影响模块级导入
        from enhancements.reasoning.goal_decomposer import Goal, GoalType  # noqa: PLC0415

        goal_id = f"goal_{uuid.uuid4().hex[:12]}"

        try:
            gt = GoalType[goal_type.upper()]
        except (KeyError, AttributeError):
            gt = GoalType.TASK_EXECUTION

        goal = Goal(
            description=goal_description,
            type=gt,
            constraints=[],
            success_criteria=[],
            deadline=None,
        )
        self._goal_queue.put_nowait(goal)
        self.logger.info(f"目标已入队 [id={goal_id}]: {goal_description}")
        return goal_id


@dataclass
class PendingGoal:
    """
    轻量级待处理目标容器。

    供 WebSocket 服务层和 UI 层在将目标提交给 L4 主循环之前暂存使用。
    """
    description: str
    goal_type: str = "task_execution"
    priority: int = 5
    metadata: Dict[str, Any] = field(default_factory=dict)


def get_galaxy_loop(config: Optional[Dict[str, Any]] = None) -> GalaxyMainLoopL4Enhanced:
    """
    工厂函数：返回一个新的 GalaxyMainLoopL4Enhanced 实例。

    Args:
        config: 可选配置字典，传递给 GalaxyMainLoopL4。

    Returns:
        已初始化（未启动）的 GalaxyMainLoopL4Enhanced 实例。
    """
    return GalaxyMainLoopL4Enhanced(config or {})


__all__ = [
    "GalaxyMainLoopL4Enhanced",
    "GalaxyMainLoopL4",
    "PendingGoal",
    "get_galaxy_loop",
]
