"""
core/galaxy_main_loop_l4_enhanced.py
====================================
Galaxy L4 增强主循环 (canonical L4 runtime module)

L4 是一套自主认知增强循环（感知 → 目标分解 → 规划 → 执行 → 监控 → 学习），
作为后台增强层运行。系统主运行链仍是 main.py → unified_launcher.py；
本模块不在 per-request 路径上（参见 docs/FINAL_INTEGRATED_SYSTEM_AUDIT.md §3）。

集成点:
    UI → L4:   ``GalaxyMainLoopL4.receive_goal()`` 接收外部目标并入队
    L4 → UI:   通过 ``integration.event_bus`` 发布进度事件
    服务端:    ``integration/websocket_server.py`` 通过 ``get_galaxy_loop()``
               获取单例并调用 ``start()/stop()/get_status()/get_task_history()``

设计原则:
    - 每个 L4 组件均以"可选降级"方式加载（try/except ImportError），
      任何增强模块缺失都不会阻止本模块导入或运行。
    - 模块可用性通过模块级 ``_*_AVAILABLE`` 标志暴露，便于审计与测试。
    - 单例通过 ``get_galaxy_loop()`` / ``reset_galaxy_loop()`` 管理
      （threading.Lock 保护）。

GalaxyMainLoopL4 是规范类名；GalaxyMainLoopL4Enhanced 是其向后兼容别名。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.MainLoopL4Enhanced")

L4_CANONICAL_RUNTIME_SENTINEL = (
    "L4_CANONICAL_RUNTIME::core.galaxy_main_loop_l4_enhanced"
)

# ---------------------------------------------------------------------------
# 可选增强组件 — 全部以降级方式加载
# ---------------------------------------------------------------------------

try:
    from enhancements.perception.environment_scanner import EnvironmentScanner
    _PERCEPTION_AVAILABLE = True
except Exception as _e:  # pragma: no cover - depends on environment
    logger.warning("感知模块不可用: %s", _e)
    EnvironmentScanner = None  # type: ignore[assignment]
    _PERCEPTION_AVAILABLE = False

try:
    from enhancements.reasoning.goal_decomposer import (
        Goal,
        GoalDecomposer,
        GoalType,
    )
    _GOAL_DECOMPOSER_AVAILABLE = True
except Exception as _e:  # pragma: no cover
    logger.warning("目标分解模块不可用: %s", _e)
    Goal = None  # type: ignore[assignment]
    GoalDecomposer = None  # type: ignore[assignment]
    GoalType = None  # type: ignore[assignment]
    _GOAL_DECOMPOSER_AVAILABLE = False

try:
    from enhancements.reasoning.autonomous_planner import AutonomousPlanner
    _PLANNER_AVAILABLE = True
except Exception as _e:  # pragma: no cover
    logger.warning("规划模块不可用: %s", _e)
    AutonomousPlanner = None  # type: ignore[assignment]
    _PLANNER_AVAILABLE = False

try:
    from enhancements.reasoning.world_model import WorldModel
    _WORLD_MODEL_AVAILABLE = True
except Exception as _e:  # pragma: no cover
    logger.warning("世界模型模块不可用: %s", _e)
    WorldModel = None  # type: ignore[assignment]
    _WORLD_MODEL_AVAILABLE = False

try:
    from enhancements.reasoning.metacognition_service import MetaCognitionService
    _METACOGNITION_AVAILABLE = True
except Exception as _e:  # pragma: no cover
    logger.warning("元认知模块不可用: %s", _e)
    MetaCognitionService = None  # type: ignore[assignment]
    _METACOGNITION_AVAILABLE = False

try:
    from enhancements.reasoning.autonomous_coder import AutonomousCoder
    _CODER_AVAILABLE = True
except Exception as _e:  # pragma: no cover
    logger.warning("自主编码模块不可用: %s", _e)
    AutonomousCoder = None  # type: ignore[assignment]
    _CODER_AVAILABLE = False

try:
    from enhancements.execution.action_executor import ActionExecutor
    _EXECUTOR_AVAILABLE = True
except Exception as _e:  # pragma: no cover
    logger.warning("动作执行模块不可用: %s", _e)
    ActionExecutor = None  # type: ignore[assignment]
    _EXECUTOR_AVAILABLE = False

try:
    from enhancements.monitoring.status_monitor import StatusMonitor
    _MONITOR_AVAILABLE = True
except Exception as _e:  # pragma: no cover
    logger.warning("状态监控模块不可用: %s", _e)
    StatusMonitor = None  # type: ignore[assignment]
    _MONITOR_AVAILABLE = False

try:
    from enhancements.safety.safety_manager import SafetyManager
    _SAFETY_AVAILABLE = True
except Exception as _e:  # pragma: no cover
    logger.warning("安全管理模块不可用: %s", _e)
    SafetyManager = None  # type: ignore[assignment]
    _SAFETY_AVAILABLE = False

try:
    from enhancements.learning.learning_optimizer import LearningOptimizer
    _LEARNING_AVAILABLE = True
except Exception as _e:  # pragma: no cover
    logger.warning("学习优化模块不可用: %s", _e)
    LearningOptimizer = None  # type: ignore[assignment]
    _LEARNING_AVAILABLE = False

# 事件总线（L4 → UI 进度回调通道）
try:
    from integration.event_bus import EventType, event_bus, ui_progress_callback
    _EVENT_BUS_AVAILABLE = True
except Exception as _e:  # pragma: no cover
    logger.warning("事件总线不可用: %s", _e)
    EventType = None  # type: ignore[assignment]
    event_bus = None  # type: ignore[assignment]
    ui_progress_callback = None  # type: ignore[assignment]
    _EVENT_BUS_AVAILABLE = False


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass
class PendingGoal:
    """等待 L4 主循环处理的外部目标（UI → L4 入口载体）。"""

    goal_id: str
    description: str
    goal_type: Any = None
    constraints: List[str] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    deadline: Optional[float] = None
    priority: int = 0
    submitted_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于状态/历史序列化）。"""
        return {
            "goal_id": self.goal_id,
            "description": self.description,
            "goal_type": getattr(self.goal_type, "value", self.goal_type),
            "constraints": list(self.constraints),
            "success_criteria": list(self.success_criteria),
            "deadline": self.deadline,
            "priority": self.priority,
            "submitted_at": self.submitted_at,
        }


# ---------------------------------------------------------------------------
# L4 主循环
# ---------------------------------------------------------------------------

class GalaxyMainLoopL4:
    """
    Galaxy L4 增强主循环（规范类）。

    周期: 感知 → 目标分解 → 规划 → 执行 → 监控 → 学习。
    所有增强组件均为可选；缺失时相应阶段降级为 no-op。

    Args:
        config: 可选配置字典，支持:
            - ``cycle_interval``    (float) 主循环周期间隔秒数，默认 5.0
            - ``auto_scan_interval`` (float) 环境自动扫描间隔秒数，默认 300.0
            - ``max_task_history``  (int)   任务历史上限，默认 1000
            - ``max_pending_goals`` (int)   目标队列上限，默认 1000
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config: Dict[str, Any] = dict(config or {})
        self.cycle_interval: float = float(self.config.get("cycle_interval", 5.0))
        self.auto_scan_interval: float = float(
            self.config.get("auto_scan_interval", 300.0)
        )

        # 运行状态
        self.running: bool = False
        self.state: str = "idle"
        self.cycle_count: int = 0
        self._main_task: Optional[asyncio.Task] = None
        self._last_scan_at: float = 0.0

        # 目标队列（UI → L4）
        self._goal_queue: asyncio.Queue = asyncio.Queue(
            maxsize=int(self.config.get("max_pending_goals", 1000))
        )

        # 任务历史（有界，防止无限增长）
        self.task_history: List[Dict[str, Any]] = []
        self._max_task_history: int = int(
            self.config.get("max_task_history", 1000)
        )

        # 增强组件（全部可选，初始化失败时降级为 None）
        self.environment_scanner = self._safe_init(
            "environment_scanner", EnvironmentScanner, _PERCEPTION_AVAILABLE
        )
        self.goal_decomposer = self._safe_init(
            "goal_decomposer", GoalDecomposer, _GOAL_DECOMPOSER_AVAILABLE
        )
        self.planner = self._safe_init(
            "planner", AutonomousPlanner, _PLANNER_AVAILABLE
        )
        self.world_model = self._safe_init(
            "world_model", WorldModel, _WORLD_MODEL_AVAILABLE
        )
        self.metacognition = self._safe_init(
            "metacognition", MetaCognitionService, _METACOGNITION_AVAILABLE
        )
        # AutonomousCoder 构造时会创建沙箱临时目录 — 懒加载，首次使用再实例化
        self.coder = None
        self.executor = self._safe_init(
            "executor", ActionExecutor, _EXECUTOR_AVAILABLE
        )
        self.monitor = self._safe_init(
            "monitor", StatusMonitor, _MONITOR_AVAILABLE
        )
        self.safety_manager = self._safe_init(
            "safety_manager", SafetyManager, _SAFETY_AVAILABLE
        )
        self.learning_optimizer = self._safe_init(
            "learning_optimizer", LearningOptimizer, _LEARNING_AVAILABLE
        )

        logger.info(
            "GalaxyMainLoopL4 initialized (cycle_interval=%.2fs, modules=%s)",
            self.cycle_interval,
            sum(1 for v in self._module_status().values() if v),
        )

    # ------------------------------------------------------------------
    # 组件管理
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_init(name: str, cls: Any, available: bool) -> Any:
        """实例化一个可选组件；任何失败都降级为 None。"""
        if not available or cls is None:
            return None
        try:
            return cls()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("组件 %s 初始化失败，降级为 None: %s", name, exc)
            return None

    def _module_status(self) -> Dict[str, bool]:
        """返回各 L4 增强模块的可用性快照（>= 10 项）。"""
        return {
            "perception": _PERCEPTION_AVAILABLE,
            "goal_decomposer": _GOAL_DECOMPOSER_AVAILABLE,
            "planner": _PLANNER_AVAILABLE,
            "world_model": _WORLD_MODEL_AVAILABLE,
            "metacognition": _METACOGNITION_AVAILABLE,
            "coder": _CODER_AVAILABLE,
            "executor": _EXECUTOR_AVAILABLE,
            "monitor": _MONITOR_AVAILABLE,
            "safety": _SAFETY_AVAILABLE,
            "learning": _LEARNING_AVAILABLE,
            "event_bus": _EVENT_BUS_AVAILABLE,
        }

    # ------------------------------------------------------------------
    # UI → L4 入口
    # ------------------------------------------------------------------

    def receive_goal(
        self,
        goal_description: str,
        goal_type: Any = None,
        constraints: Optional[List[str]] = None,
        success_criteria: Optional[List[str]] = None,
        priority: int = 0,
    ) -> str:
        """
        接收外部目标（UI → L4 集成点）。

        创建 :class:`PendingGoal` 入队，并发布 ``GOAL_SUBMITTED`` 事件。

        Returns:
            分配的目标 ID（``goal_`` 前缀）。
        """
        goal_id = f"goal_{uuid.uuid4().hex}"
        pending_goal = PendingGoal(
            goal_id=goal_id,
            description=goal_description,
            goal_type=goal_type,
            constraints=list(constraints or []),
            success_criteria=list(success_criteria or []),
            deadline=None,
            priority=priority,
        )

        try:
            self._goal_queue.put_nowait(pending_goal)
        except asyncio.QueueFull:
            logger.warning("目标队列已满，丢弃目标: %s", goal_description)

        if _EVENT_BUS_AVAILABLE and event_bus is not None:
            try:
                event_bus.publish_sync(
                    EventType.GOAL_SUBMITTED,
                    "ui",
                    {"goal_id": goal_id, "description": goal_description},
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("GOAL_SUBMITTED 事件发布失败（非致命）: %s", exc)

        logger.info("收到目标 %s: %s", goal_id, goal_description)
        return goal_id

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动 L4 主循环（长驻协程，直至 :meth:`stop` 被调用）。"""
        if self.running:
            logger.debug("L4 主循环已在运行，忽略重复启动")
            return

        self.running = True
        self.state = "running"
        self._main_task = asyncio.current_task()
        logger.info("L4 主循环已启动")

        try:
            while self.running:
                try:
                    await self.run_cycle()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # pragma: no cover - defensive
                    logger.error("L4 周期执行错误: %s", exc)
                await asyncio.sleep(self.cycle_interval)
        except asyncio.CancelledError:
            logger.debug("L4 主循环任务被取消")
        finally:
            self.running = False
            if self.state != "stopped":
                self.state = "stopped"
            logger.info("L4 主循环已退出 (cycles=%d)", self.cycle_count)

    async def stop(self) -> None:
        """停止 L4 主循环。在未启动时调用也是安全的。"""
        self.running = False
        self.state = "stopped"

        task = self._main_task
        self._main_task = None
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        logger.info("L4 主循环已停止")

    # ------------------------------------------------------------------
    # 主循环周期
    # ------------------------------------------------------------------

    async def run_cycle(self) -> None:
        """
        执行一个完整 L4 周期:
        感知（定期环境扫描）→ 取目标 → 分解 → 规划 → 执行 → 记录/学习。
        """
        self.cycle_count += 1

        await self._maybe_scan_environment()

        try:
            pending = self._goal_queue.get_nowait()
        except asyncio.QueueEmpty:
            return

        await self._process_goal(pending)

    async def _maybe_scan_environment(self) -> None:
        """按 ``auto_scan_interval`` 周期执行环境感知扫描（可选阶段）。"""
        if self.environment_scanner is None:
            return
        now = time.time()
        if now - self._last_scan_at < self.auto_scan_interval:
            return
        self._last_scan_at = now
        try:
            await asyncio.to_thread(self.environment_scanner.scan_and_register_all)
            logger.debug("环境扫描完成")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("环境扫描失败（非致命）: %s", exc)

    async def _process_goal(self, pending: PendingGoal) -> None:
        """处理单个目标: 分解 → 规划 → 执行 → 完成通知 + 历史记录。"""
        started_at = time.time()
        success = False
        actions_count = 0
        error: Optional[str] = None

        callback = ui_progress_callback if _EVENT_BUS_AVAILABLE else None

        try:
            # 1. 目标分解
            if callback is not None:
                callback.on_goal_decomposition_started(pending.description)

            decomposition = self._decompose_goal(pending)
            subtasks: List[Dict[str, Any]] = []
            if decomposition is not None:
                subtasks = [
                    {
                        "id": st.id,
                        "type": getattr(st.type, "value", str(st.type)),
                        "description": st.description,
                    }
                    for st in decomposition.subtasks
                ]
            if callback is not None:
                callback.on_goal_decomposition_completed(
                    pending.description, subtasks
                )

            # 2. 计划生成
            plan = None
            if self.planner is not None and decomposition is not None:
                if callback is not None:
                    callback.on_plan_generation_started(pending.description)
                plan = self._create_plan(decomposition)
                actions_list = list(getattr(plan, "actions", []) or [])
                actions_count = len(actions_list)
                if callback is not None:
                    callback.on_plan_generation_completed(
                        pending.description,
                        [
                            {"id": getattr(a, "id", ""), "description": getattr(a, "description", "")}
                            for a in actions_list
                        ],
                    )

            # 3. 计划执行
            if self.executor is not None and plan is not None:
                context = await self._execute_plan(plan)
                completed = list(getattr(context, "completed_actions", []) or [])
                failed = list(getattr(context, "failed_actions", []) or [])
                success = len(failed) == 0
                actions_count = max(actions_count, len(completed) + len(failed))
            else:
                # 执行器不可用 — 降级为已接收/已规划状态
                success = True

        except Exception as exc:
            error = str(exc)
            logger.error("目标处理失败 %s: %s", pending.goal_id, exc)
            if callback is not None:
                try:
                    callback.on_error(error, {"goal_id": pending.goal_id})
                except Exception:  # pragma: no cover - defensive
                    pass

        duration = time.time() - started_at
        self._record_task(pending, success, duration, actions_count, error)

        if callback is not None:
            try:
                callback.on_task_completed(
                    pending.description,
                    success,
                    {
                        "goal_id": pending.goal_id,
                        "duration": duration,
                        "actions_count": actions_count,
                        "error": error,
                    },
                )
            except Exception:  # pragma: no cover - defensive
                pass

    # ------------------------------------------------------------------
    # 周期阶段（每个阶段都是可降级的）
    # ------------------------------------------------------------------

    def _decompose_goal(self, pending: PendingGoal) -> Any:
        """目标分解阶段（goal_decomposer 不可用时返回 None）。"""
        if self.goal_decomposer is None or Goal is None:
            return None

        goal_type = pending.goal_type
        if GoalType is not None and not isinstance(goal_type, GoalType):
            goal_type = GoalType.TASK_EXECUTION

        goal = Goal(
            description=pending.description,
            type=goal_type,
            constraints=list(pending.constraints),
            success_criteria=list(pending.success_criteria),
            deadline=int(pending.deadline) if pending.deadline else None,
        )
        return self.goal_decomposer.decompose(goal)

    def _create_plan(self, decomposition: Any) -> Any:
        """计划生成阶段。"""
        return self.planner.create_plan(decomposition)

    async def _execute_plan(self, plan: Any) -> Any:
        """计划执行阶段。"""
        return await self.executor.execute_plan(plan, self.world_model)

    def _record_task(
        self,
        pending: PendingGoal,
        success: bool,
        duration: float,
        actions_count: int,
        error: Optional[str] = None,
    ) -> None:
        """记录任务历史并裁剪（防止无限增长）。"""
        record: Dict[str, Any] = {
            "goal_id": pending.goal_id,
            "goal": pending.description,
            "success": success,
            "duration": duration,
            "actions_count": actions_count,
            "success_rate": 1.0 if success else 0.0,
            "completed_at": time.time(),
        }
        if error:
            record["error"] = error
        self.task_history.append(record)
        if len(self.task_history) > self._max_task_history:
            self.task_history = self.task_history[-self._max_task_history:]

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """返回 L4 主循环运行状态快照。"""
        return {
            "running": self.running,
            "state": self.state,
            "cycle_count": self.cycle_count,
            "pending_goals": self._goal_queue.qsize(),
            "completed_tasks": len(self.task_history),
            "cycle_interval": self.cycle_interval,
            "modules": self._module_status(),
        }

    def get_task_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """返回最近的任务历史（最多 ``limit`` 条）。"""
        if limit <= 0:
            return []
        return list(self.task_history[-limit:])


# 向后兼容别名 — GalaxyMainLoopL4 是规范类名
GalaxyMainLoopL4Enhanced = GalaxyMainLoopL4


# ---------------------------------------------------------------------------
# 单例管理
# ---------------------------------------------------------------------------

_galaxy_loop_instance: Optional[GalaxyMainLoopL4] = None
_galaxy_loop_lock = threading.Lock()


def get_galaxy_loop(config: Optional[Dict[str, Any]] = None) -> GalaxyMainLoopL4:
    """
    获取 L4 主循环单例。

    首次调用时使用 ``config`` 创建实例；后续调用返回同一实例
    （此时 ``config`` 被忽略）。
    """
    global _galaxy_loop_instance
    if _galaxy_loop_instance is None:
        with _galaxy_loop_lock:
            if _galaxy_loop_instance is None:
                _galaxy_loop_instance = GalaxyMainLoopL4(config)
    return _galaxy_loop_instance


def reset_galaxy_loop() -> None:
    """重置单例（主要用于测试）。不会 await 正在运行的循环。"""
    global _galaxy_loop_instance
    with _galaxy_loop_lock:
        if _galaxy_loop_instance is not None:
            _galaxy_loop_instance.running = False
        _galaxy_loop_instance = None


__all__ = [
    "GalaxyMainLoopL4",
    "GalaxyMainLoopL4Enhanced",
    "PendingGoal",
    "get_galaxy_loop",
    "reset_galaxy_loop",
    "L4_CANONICAL_RUNTIME_SENTINEL",
]
