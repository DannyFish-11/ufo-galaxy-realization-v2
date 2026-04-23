"""
HybridExecutionArbiter — 混合执行仲裁器
========================================

**Architecture role: FALLBACK EXECUTION HELPER — not a parallel authority**
----------------------------------------------------------------------------
``HybridExecutionArbiter`` is an **internal fallback execution helper**.
It implements a three-level degradation chain (A2A → GUI → VLM) for
*local* task execution.  It is NOT a parallel top-level dispatch authority
and MUST NOT bypass the canonical execution chain::

    OpenClawd (subject/execution core)
        └─ local execution path
              └─ HybridExecutionArbiter  ← internal helper (this module)
                   Level 1: A2A (direct API/MCP call)
                   Level 2: GUI Automation
                   Level 3: VLM (screenshot + reasoning)

For *cross-device* dispatch, the canonical chain is::

    OpenClawd → CommandRouter → DeviceRouter → device

``HybridExecutionArbiter`` MUST NOT be used as a substitute for
``CommandRouter`` in the cross-device path.

HYBRID_EXECUTOR_ROLE sentinel: "fallback_execution_helper"

Continuity wiring (HYBRID_EXECUTOR_CONTINUITY_WIRED)
-----------------------------------------------------
``HybridExecutionArbiter.execute()`` is wired into
:class:`~core.hybrid_orchestration_continuity.HybridOrchestrationContinuityRegistry`
so that every execution participates in live restart-aware continuity
tracking.  The lifecycle state transitions are::

    created → dispatched → running → completed   (success)
    created → dispatched → running → failed       (all levels exhausted)
    created → dispatched → running → interrupted  (asyncio.CancelledError or
                                                   unhandled exception)

Partial results from individual successful level attempts are preserved on
the :class:`~core.hybrid_orchestration_continuity.HybridOrchestrationRecord`
whenever execution is interrupted before a terminal state is reached.  Local
partial results are classified as ``preserved``; the recovery coordinator
marks remote partial results as ``invalidated`` on restart.

The continuity registry is injected via ``__init__(continuity_registry=…)``
for testability.  Production code uses the process-level singleton via
:func:`~core.hybrid_orchestration_continuity.get_continuity_registry`.

Phase 3 Matrix OS 核心组件。

三级降级执行链:
  Level 1: A2A (Agent-to-Agent) — 通过 API/MCP 直接调用目标应用/服务
  Level 2: GUI Automation      — 通过 UI 自动化 (点击/滑动/输入) 操控界面
  Level 3: VLM (Vision-Language Model) — 截图 + VLM 理解 + 坐标推理

每个执行请求按顺序尝试三级:
  - A2A 成功 → 直接返回结果 (最快, 最准)
  - A2A 失败 → 降级到 GUI (通过 accessibility/adb)
  - GUI 失败 → 降级到 VLM (截图 + 视觉理解 + 盲操作)

策略选择器:
  - 根据目标应用的能力声明决定首选执行级别
  - 如果已知某应用有 A2A API, 直接跳到 L1
  - 如果已知某应用只有 GUI, 跳过 L1

Windows 特殊路径:
  对于 Windows 平台请求, HybridExecutionArbiter 委托给
  :class:`core.windows_execution_arbiter.WindowsExecutionArbiter`,
  后者强制执行更精细的四级回退链:
    System API → UIAutomation → GUI automation → VLM
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Dict, Any, Optional, Callable, Awaitable, List, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("Galaxy.HybridExecutor")

# ---------------------------------------------------------------------------
# Architecture role declaration
# ---------------------------------------------------------------------------

HYBRID_EXECUTOR_ROLE: str = "fallback_execution_helper"
"""Role sentinel: HybridExecutionArbiter is an internal fallback execution
helper within OpenClawd's local execution path.  It MUST NOT act as a
parallel top-level dispatch authority or bypass the canonical execution chain
(OpenClawd → CommandRouter → DeviceRouter) for cross-device tasks."""

HYBRID_EXECUTOR_CONTINUITY_WIRED: str = (
    "HYBRID_EXECUTOR_CONTINUITY_WIRED::"
    "HybridExecutionArbiter.execute() is wired into "
    "HybridOrchestrationContinuityRegistry so every execution participates "
    "in live restart-aware continuity tracking.  Lifecycle state transitions "
    "(created→dispatched→running→completed/failed/interrupted) are applied "
    "to a HybridOrchestrationRecord that survives process restart.  Partial "
    "results from individual successful level attempts are preserved on "
    "interruption.  The continuity_registry parameter allows test injection."
)

#: Phase-A consolidation sentinel.  The former ``CapabilityRegistry`` class in
#: this module has been renamed to :class:`AppExecutionCapabilityRegistry` to
#: eliminate naming ambiguity with the canonical
#: :class:`core.agent.capability_registry.CapabilityRegistry` (the system-wide
#: capability truth source).  This class manages *app-level execution
#: preferences* (A2A / GUI / VLM level order per app_id) — a concern that is
#: entirely local to :class:`HybridExecutionArbiter` and has no connection to
#: the capability bus.
APP_EXECUTION_CAPABILITY_REGISTRY_RENAMED: str = (
    "CapabilityRegistry → AppExecutionCapabilityRegistry"
)

class ExecutionLevel(str, Enum):
    A2A = "a2a"          # Agent-to-Agent (API/MCP direct call)
    GUI = "gui"          # GUI Automation (accessibility, ADB)
    VLM = "vlm"          # Vision-Language Model (screenshot + reasoning)


class ExecutionStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    DEGRADED = "degraded"    # 低级别成功
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


@dataclass
class ExecutionAttempt:
    """单次执行尝试记录"""
    level: ExecutionLevel
    status: ExecutionStatus
    result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    latency_ms: float = 0


@dataclass
class HybridResult:
    """混合执行最终结果"""
    request_id: str
    success: bool
    final_level: ExecutionLevel
    result: Dict[str, Any] = field(default_factory=dict)
    attempts: List[Dict] = field(default_factory=list)
    total_latency_ms: float = 0

    def to_dict(self) -> Dict:
        return {
            "request_id": self.request_id,
            "success": self.success,
            "final_level": self.final_level.value,
            "result": self.result,
            "attempts": self.attempts,
            "total_latency_ms": self.total_latency_ms,
        }


# ============================================================================
# 能力注册表 — 记录每个应用/服务支持的执行级别
# ============================================================================

@dataclass
class AppCapability:
    """应用能力声明"""
    app_id: str                          # 包名或服务标识
    a2a_endpoint: str = ""               # A2A API 端点 (空=不支持)
    a2a_actions: List[str] = field(default_factory=list)  # 支持的 A2A 动作
    gui_supported: bool = True           # 是否支持 GUI 自动化
    vlm_supported: bool = True           # 是否支持 VLM (几乎所有应用都支持)
    preferred_level: Optional[ExecutionLevel] = None  # 强制首选级别


class AppExecutionCapabilityRegistry:
    """Per-app execution-level preference registry for HybridExecutionArbiter.

    .. note::
        This class is **not** the system-wide capability truth source.  It is a
        small, module-local helper that records which execution levels (A2A /
        GUI / VLM) each app supports and in what preferred order.

        The canonical system capability registry is
        :class:`core.agent.capability_registry.CapabilityRegistry`, which is
        populated by MCP/Skill/Node loaders and consumed by
        :class:`core.unified.capability_resolver.CapabilityResolver`.

    Previously named ``CapabilityRegistry`` (renamed in Phase-A consolidation;
    see :data:`APP_EXECUTION_CAPABILITY_REGISTRY_RENAMED`).
    """

    def __init__(self):
        self._apps: Dict[str, AppCapability] = {}
        self._register_defaults()

    def _register_defaults(self):
        """注册默认应用能力"""
        defaults = [
            AppCapability("com.tencent.mm", gui_supported=True,
                          a2a_actions=["send_message"],
                          a2a_endpoint=""),  # 微信: 暂无公开 A2A
            AppCapability("com.android.settings", gui_supported=True),
            AppCapability("com.android.chrome",
                          a2a_actions=["open_url", "search"],
                          a2a_endpoint="intent://"),
            AppCapability("system_shell",
                          a2a_endpoint="adb",
                          a2a_actions=["execute"],
                          preferred_level=ExecutionLevel.A2A),
            AppCapability("file_manager",
                          a2a_endpoint="filesystem",
                          a2a_actions=["read", "write", "list", "delete"],
                          preferred_level=ExecutionLevel.A2A),
        ]
        for cap in defaults:
            self._apps[cap.app_id] = cap

    def register(self, cap: AppCapability):
        self._apps[cap.app_id] = cap

    def get(self, app_id: str) -> Optional[AppCapability]:
        return self._apps.get(app_id)

    def get_preferred_levels(self, app_id: str) -> List[ExecutionLevel]:
        """根据应用能力返回执行级别优先序列"""
        cap = self._apps.get(app_id)
        if not cap:
            return [ExecutionLevel.A2A, ExecutionLevel.GUI, ExecutionLevel.VLM]

        if cap.preferred_level:
            levels = [cap.preferred_level]
            for lv in [ExecutionLevel.A2A, ExecutionLevel.GUI, ExecutionLevel.VLM]:
                if lv != cap.preferred_level:
                    levels.append(lv)
            return levels

        levels = []
        if cap.a2a_endpoint or cap.a2a_actions:
            levels.append(ExecutionLevel.A2A)
        if cap.gui_supported:
            levels.append(ExecutionLevel.GUI)
        if cap.vlm_supported:
            levels.append(ExecutionLevel.VLM)
        return levels or [ExecutionLevel.GUI, ExecutionLevel.VLM]

    def list_apps(self) -> List[Dict]:
        return [
            {"app_id": cap.app_id, "a2a": bool(cap.a2a_endpoint),
             "gui": cap.gui_supported, "vlm": cap.vlm_supported}
            for cap in self._apps.values()
        ]


# ============================================================================
# 执行器接口
# ============================================================================

# A2A 执行器: (app_id, action, params, device_id) -> result_dict
A2AExecutor = Callable[[str, str, Dict, str], Awaitable[Dict[str, Any]]]

# GUI 执行器: (device_id, action, params) -> result_dict
GUIExecutor = Callable[[str, str, Dict], Awaitable[Dict[str, Any]]]

# VLM 执行器: (device_id, instruction, screenshot_b64) -> result_dict
VLMExecutor = Callable[[str, str, Optional[str]], Awaitable[Dict[str, Any]]]

# 截图器: (device_id) -> base64_string
ScreenshotGetter = Callable[[str], Awaitable[str]]


class HybridExecutionArbiter:
    """
    混合执行仲裁器

    核心逻辑:
    1. 接收执行请求 (device_id, app_id, action, params)
    2. 查询能力注册表获取执行级别序列
    3. 按序尝试: A2A → GUI → VLM
    4. 返回最终结果 (包含所有尝试记录)
    """

    def __init__(
        self,
        a2a_executor: A2AExecutor = None,
        gui_executor: GUIExecutor = None,
        vlm_executor: VLMExecutor = None,
        screenshot_getter: ScreenshotGetter = None,
        continuity_registry=None,
    ):
        self._a2a = a2a_executor
        self._gui = gui_executor
        self._vlm = vlm_executor
        self._screenshot = screenshot_getter
        self.registry = AppExecutionCapabilityRegistry()
        self._execution_history: List[Dict] = []
        self._stats = {
            "total": 0,
            "a2a_success": 0,
            "gui_success": 0,
            "vlm_success": 0,
            "all_failed": 0,
        }
        # Continuity registry: injected for testing, or resolved lazily from
        # the process-level singleton on first use.  None means "use singleton".
        self._continuity_registry = continuity_registry

    def set_executors(
        self,
        a2a: A2AExecutor = None,
        gui: GUIExecutor = None,
        vlm: VLMExecutor = None,
        screenshot: ScreenshotGetter = None,
    ):
        if a2a:
            self._a2a = a2a
        if gui:
            self._gui = gui
        if vlm:
            self._vlm = vlm
        if screenshot:
            self._screenshot = screenshot

    def _get_continuity_registry(self):
        """Return the active continuity registry (injected or process singleton)."""
        if self._continuity_registry is not None:
            return self._continuity_registry
        try:
            from core.hybrid_orchestration_continuity import get_continuity_registry
            return get_continuity_registry()
        except Exception:
            return None

    @staticmethod
    def _is_windows_device(device_id: str) -> bool:
        """Heuristic: return True when *device_id* identifies a Windows host.

        A device is treated as Windows when its identifier starts with
        ``"windows"`` (case-insensitive) or ends with ``":win"`` or
        ``":windows"``.  This keeps the check cheap and dependency-free while
        covering the common naming conventions used in this codebase.

        The special ``"local"`` identifier is treated as Windows only when the
        current process is actually running on Win32 (``sys.platform``).
        """
        import sys as _sys
        lower = device_id.lower()
        return (
            lower.startswith("windows")
            or lower.endswith(":win")
            or lower.endswith(":windows")
            or (lower == "local" and _sys.platform == "win32")
        )

    async def execute(
        self,
        device_id: str,
        app_id: str,
        action: str,
        params: Dict[str, Any] = None,
        instruction: str = "",
        force_level: ExecutionLevel = None,
        windows_arbiter=None,
        decision_authority: str = "",
        session_id: str = "",
        task_id: str = "",
    ) -> HybridResult:
        """
        混合执行入口

        Args:
            device_id: 目标设备 ID
            app_id: 目标应用标识
            action: 要执行的动作
            params: 动作参数
            instruction: 自然语言指令 (VLM 模式使用)
            force_level: 强制使用指定级别 (跳过降级)
            windows_arbiter: 可选的 WindowsExecutionArbiter 实例，覆盖默认单例
                (用于测试注入). 传入 False 可强制禁用 Windows 路由.
            decision_authority: PR-2 — identifier of the component that made
                the primary decision (e.g. ``"openclawd"``).  When provided,
                it is logged so the trace shows who owns the decision.
                HybridExecutor itself never *makes* a primary decision; it
                only executes what it receives.
            session_id: Optional session identifier for continuity tracking.
            task_id: Optional canonical task identifier for continuity tracking.
        """
        params = params or {}
        request_id = str(uuid.uuid4())[:12]
        start = time.time()
        self._stats["total"] += 1

        # PR-2: Log that HybridExecutor is acting as executor, not decision
        # maker.  We do NOT re-evaluate intent or re-score the plan here.
        if decision_authority:
            logger.debug(
                "hybrid_executor | executing decision from authority=%s | "
                "device=%s app=%s action=%s request_id=%s",
                decision_authority,
                device_id,
                app_id,
                action,
                request_id,
            )

        # ------------------------------------------------------------------
        # Continuity wiring: register this execution in the continuity
        # registry so it participates in restart-aware lifecycle tracking.
        # The record survives process restart; live transport handles do not.
        # ------------------------------------------------------------------
        continuity_record = None
        try:
            from core.hybrid_orchestration_continuity import (
                HybridOrchestrationLifecycleState,
            )
            _registry = self._get_continuity_registry()
            if _registry is not None:
                continuity_record = _registry.create_and_register(
                    session_id=session_id,
                    task_id=task_id,
                    mode="sequential_degrade",
                )
                _registry.transition(
                    continuity_record.execution_id,
                    HybridOrchestrationLifecycleState.dispatched,
                )
                logger.debug(
                    "hybrid_executor | continuity_registered | "
                    "execution_id=%s device=%s app=%s action=%s",
                    continuity_record.execution_id,
                    device_id,
                    app_id,
                    action,
                )
        except Exception as _creg_exc:
            logger.debug(
                "hybrid_executor | continuity_register_skipped | %s", _creg_exc
            )

        # ------------------------------------------------------------------
        # Windows fast-path: delegate to WindowsExecutionArbiter which
        # enforces the strict System API → UIA → GUI → VLM fallback chain.
        # Only skip when the caller explicitly passes windows_arbiter=False.
        # ------------------------------------------------------------------
        if windows_arbiter is not False and self._is_windows_device(device_id):
            return await self._execute_windows(
                device_id=device_id,
                app_id=app_id,
                action=action,
                params=params,
                instruction=instruction,
                request_id=request_id,
                start=start,
                windows_arbiter=windows_arbiter,
                continuity_record=continuity_record,
            )

        # 确定执行级别序列
        # PR-2: The level sequence is derived solely from the registered app
        # capabilities and the caller-supplied force_level.  HybridExecutor
        # does NOT re-interpret the intent or change the plan.
        if force_level:
            levels = [force_level]
        else:
            levels = self.registry.get_preferred_levels(app_id)

        attempts = []
        # Track the last successful partial result for interruption preservation.
        last_partial_result: Optional[Dict[str, Any]] = None
        last_partial_origin: str = "local"

        # Transition to running once we start attempting levels.
        if continuity_record is not None:
            try:
                from core.hybrid_orchestration_continuity import (
                    HybridOrchestrationLifecycleState,
                )
                self._get_continuity_registry().transition(
                    continuity_record.execution_id,
                    HybridOrchestrationLifecycleState.running,
                )
            except Exception as _tr_exc:
                logger.debug(
                    "hybrid_executor | continuity_running_transition_failed | %s",
                    _tr_exc,
                )

        try:
            for level in levels:
                attempt = await self._try_level(
                    level, device_id, app_id, action, params, instruction
                )
                attempts.append(attempt)

                if attempt.status == ExecutionStatus.SUCCESS:
                    # Preserve the successful attempt result as a partial result
                    # in case execution is interrupted before returning.
                    last_partial_result = attempt.result
                    last_partial_origin = "local"

                    self._stats[f"{level.value}_success"] += 1
                    result = HybridResult(
                        request_id=request_id,
                        success=True,
                        final_level=level,
                        result=attempt.result,
                        attempts=[self._attempt_to_dict(a) for a in attempts],
                        total_latency_ms=(time.time() - start) * 1000,
                    )
                    self._record(result)
                    # Transition to completed in the continuity registry.
                    if continuity_record is not None:
                        try:
                            from core.hybrid_orchestration_continuity import (
                                HybridOrchestrationLifecycleState,
                            )
                            self._get_continuity_registry().transition(
                                continuity_record.execution_id,
                                HybridOrchestrationLifecycleState.completed,
                                result=result.to_dict(),
                            )
                        except Exception as _tc_exc:
                            logger.debug(
                                "hybrid_executor | continuity_completed_transition_failed | %s",
                                _tc_exc,
                            )
                    return result

                logger.info(
                    f"Level {level.value} failed for {app_id}.{action}: "
                    f"{attempt.error}. Trying next level..."
                )

            # 所有级别都失败
            # PR-2: Fallback exhaustion — this is a transport-level failure, NOT
            # a re-decision.  We return a failed result without altering the
            # original action or intent received from the primary authority.
            self._stats["all_failed"] += 1
            result = HybridResult(
                request_id=request_id,
                success=False,
                final_level=levels[-1] if levels else ExecutionLevel.A2A,
                result={"error": "All execution levels failed"},
                attempts=[self._attempt_to_dict(a) for a in attempts],
                total_latency_ms=(time.time() - start) * 1000,
            )
            self._record(result)
            # Transition to failed in the continuity registry.
            if continuity_record is not None:
                try:
                    from core.hybrid_orchestration_continuity import (
                        HybridOrchestrationLifecycleState,
                    )
                    self._get_continuity_registry().transition(
                        continuity_record.execution_id,
                        HybridOrchestrationLifecycleState.failed,
                        result=result.to_dict(),
                    )
                except Exception as _tf_exc:
                    logger.debug(
                        "hybrid_executor | continuity_failed_transition_failed | %s",
                        _tf_exc,
                    )
            return result

        except asyncio.CancelledError:
            # Execution was cancelled (e.g. device disconnect / process shutdown).
            # Preserve any partial result and mark the continuity record as
            # interrupted so restart recovery can classify and resume it.
            if continuity_record is not None:
                try:
                    from core.hybrid_orchestration_continuity import (
                        HybridOrchestrationLifecycleState,
                        HybridPartialResultDisposition,
                    )
                    if last_partial_result is not None:
                        continuity_record.set_partial_result(
                            last_partial_result,
                            last_partial_origin,
                            disposition=HybridPartialResultDisposition.preserved.value,
                        )
                    self._get_continuity_registry().transition(
                        continuity_record.execution_id,
                        HybridOrchestrationLifecycleState.interrupted,
                        reason="asyncio_cancelled",
                    )
                    logger.info(
                        "hybrid_executor | execution_interrupted | "
                        "execution_id=%s partial_result=%s",
                        continuity_record.execution_id,
                        last_partial_result is not None,
                    )
                except Exception as _ti_exc:
                    logger.debug(
                        "hybrid_executor | continuity_interrupted_transition_failed | %s",
                        _ti_exc,
                    )
            raise

        except Exception as _exc:
            # Unexpected exception: treat as interrupted so restart recovery
            # can decide whether to resume or re-issue.
            if continuity_record is not None:
                try:
                    from core.hybrid_orchestration_continuity import (
                        HybridOrchestrationLifecycleState,
                        HybridPartialResultDisposition,
                    )
                    if last_partial_result is not None:
                        continuity_record.set_partial_result(
                            last_partial_result,
                            last_partial_origin,
                            disposition=HybridPartialResultDisposition.preserved.value,
                        )
                    self._get_continuity_registry().transition(
                        continuity_record.execution_id,
                        HybridOrchestrationLifecycleState.interrupted,
                        reason=f"exception:{type(_exc).__name__}",
                    )
                    logger.info(
                        "hybrid_executor | execution_interrupted_by_exception | "
                        "execution_id=%s exc=%s partial_result=%s",
                        continuity_record.execution_id,
                        _exc,
                        last_partial_result is not None,
                    )
                except Exception as _ti2_exc:
                    logger.debug(
                        "hybrid_executor | continuity_exception_transition_failed | %s",
                        _ti2_exc,
                    )
            raise

    async def _execute_windows(
        self,
        device_id: str,
        app_id: str,
        action: str,
        params: Dict[str, Any],
        instruction: str,
        request_id: str,
        start: float,
        windows_arbiter=None,
        continuity_record=None,
    ) -> "HybridResult":
        """Delegate a Windows execution request to the WindowsExecutionArbiter.

        The Windows arbiter enforces the strict fallback chain:
          System API → UIA → GUI automation → VLM

        The result is mapped back to a :class:`HybridResult` so callers do
        not need to know which arbiter handled the request.
        """
        # Transition to running for the Windows path.
        if continuity_record is not None:
            try:
                from core.hybrid_orchestration_continuity import (
                    HybridOrchestrationLifecycleState,
                )
                self._get_continuity_registry().transition(
                    continuity_record.execution_id,
                    HybridOrchestrationLifecycleState.running,
                )
            except Exception as _trw_exc:
                logger.debug(
                    "hybrid_executor | continuity_windows_running_transition_failed | %s",
                    _trw_exc,
                )

        try:
            from core.windows_execution_arbiter import (  # type: ignore[import]
                get_windows_arbiter,
                WinExecLevel,
            )

            arbiter = windows_arbiter or get_windows_arbiter()
            # Propagate VLM / screenshot executors from this instance (if wired)
            # using the public set_executors() API to respect encapsulation.
            propagate: dict = {}
            if self._vlm is not None and arbiter._vlm is None:
                propagate["vlm"] = self._vlm
            if self._screenshot is not None and arbiter._screenshot is None:
                propagate["screenshot"] = self._screenshot
            if propagate:
                arbiter.set_executors(**propagate)

            win_result = await arbiter.execute(
                action=action,
                params=params,
                device_id=device_id,
                instruction=instruction or f"{action} {app_id}",
            )

            # Map WinExecLevel to the nearest ExecutionLevel for compatibility.
            _level_map = {
                WinExecLevel.SYSTEM_API: ExecutionLevel.A2A,
                WinExecLevel.UIA: ExecutionLevel.GUI,
                WinExecLevel.GUI: ExecutionLevel.GUI,
                WinExecLevel.VLM: ExecutionLevel.VLM,
            }
            mapped_level = _level_map.get(win_result.final_level, ExecutionLevel.GUI)

            if win_result.success:
                self._stats[f"{mapped_level.value}_success"] += 1
            else:
                self._stats["all_failed"] += 1

            hybrid = HybridResult(
                request_id=request_id,
                success=win_result.success,
                final_level=mapped_level,
                result=win_result.result,
                attempts=win_result.attempts,
                total_latency_ms=(time.time() - start) * 1000,
            )
            self._record(hybrid)
            # Apply terminal continuity transition for Windows path.
            if continuity_record is not None:
                try:
                    from core.hybrid_orchestration_continuity import (
                        HybridOrchestrationLifecycleState,
                    )
                    terminal = (
                        HybridOrchestrationLifecycleState.completed
                        if hybrid.success
                        else HybridOrchestrationLifecycleState.failed
                    )
                    self._get_continuity_registry().transition(
                        continuity_record.execution_id,
                        terminal,
                        result=hybrid.to_dict(),
                    )
                except Exception as _ttw_exc:
                    logger.debug(
                        "hybrid_executor | continuity_windows_terminal_transition_failed | %s",
                        _ttw_exc,
                    )
            return hybrid

        except Exception as exc:
            logger.exception(
                "hybrid_executor | windows_delegate_failed | device=%s | action=%s | error=%s",
                device_id,
                action,
                exc,
            )
            # Fall through to a failure result so execution still returns cleanly.
            self._stats["all_failed"] += 1
            fallback = HybridResult(
                request_id=request_id,
                success=False,
                final_level=ExecutionLevel.A2A,
                result={"error": f"Windows arbiter delegation failed: {exc}"},
                attempts=[],
                total_latency_ms=(time.time() - start) * 1000,
            )
            self._record(fallback)
            # Mark the continuity record as interrupted on unexpected exception.
            if continuity_record is not None:
                try:
                    from core.hybrid_orchestration_continuity import (
                        HybridOrchestrationLifecycleState,
                    )
                    self._get_continuity_registry().transition(
                        continuity_record.execution_id,
                        HybridOrchestrationLifecycleState.interrupted,
                        reason=f"windows_exception:{type(exc).__name__}",
                    )
                except Exception as _twf_exc:
                    logger.debug(
                        "hybrid_executor | continuity_windows_interrupted_failed | %s",
                        _twf_exc,
                    )
            return fallback

    async def _try_level(
        self,
        level: ExecutionLevel,
        device_id: str,
        app_id: str,
        action: str,
        params: Dict,
        instruction: str,
    ) -> ExecutionAttempt:
        """尝试单个执行级别"""
        start = time.time()

        try:
            if level == ExecutionLevel.A2A:
                return await self._try_a2a(device_id, app_id, action, params, start)
            elif level == ExecutionLevel.GUI:
                return await self._try_gui(device_id, action, params, start)
            elif level == ExecutionLevel.VLM:
                return await self._try_vlm(device_id, instruction or f"{action} {json.dumps(params)}", start)
            else:
                return ExecutionAttempt(
                    level=level,
                    status=ExecutionStatus.FAILED,
                    error=f"Unknown level: {level}",
                )
        except Exception as e:
            return ExecutionAttempt(
                level=level,
                status=ExecutionStatus.FAILED,
                error=str(e),
                latency_ms=(time.time() - start) * 1000,
            )

    async def _try_a2a(
        self, device_id: str, app_id: str, action: str, params: Dict, start: float
    ) -> ExecutionAttempt:
        """Level 1: A2A 直接调用"""
        if not self._a2a:
            return ExecutionAttempt(
                level=ExecutionLevel.A2A,
                status=ExecutionStatus.SKIPPED,
                error="No A2A executor configured",
                latency_ms=(time.time() - start) * 1000,
            )

        result = await self._a2a(app_id, action, params, device_id)

        if result.get("success", False) or result.get("status") == "success":
            return ExecutionAttempt(
                level=ExecutionLevel.A2A,
                status=ExecutionStatus.SUCCESS,
                result=result,
                latency_ms=(time.time() - start) * 1000,
            )
        return ExecutionAttempt(
            level=ExecutionLevel.A2A,
            status=ExecutionStatus.FAILED,
            error=result.get("error", "A2A call returned non-success"),
            result=result,
            latency_ms=(time.time() - start) * 1000,
        )

    async def _try_gui(
        self, device_id: str, action: str, params: Dict, start: float
    ) -> ExecutionAttempt:
        """Level 2: GUI 自动化"""
        if not self._gui:
            return ExecutionAttempt(
                level=ExecutionLevel.GUI,
                status=ExecutionStatus.SKIPPED,
                error="No GUI executor configured",
                latency_ms=(time.time() - start) * 1000,
            )

        result = await self._gui(device_id, action, params)

        if result.get("success", False) or result.get("status") == "success":
            return ExecutionAttempt(
                level=ExecutionLevel.GUI,
                status=ExecutionStatus.SUCCESS,
                result=result,
                latency_ms=(time.time() - start) * 1000,
            )
        return ExecutionAttempt(
            level=ExecutionLevel.GUI,
            status=ExecutionStatus.FAILED,
            error=result.get("error", "GUI automation failed"),
            result=result,
            latency_ms=(time.time() - start) * 1000,
        )

    async def _try_vlm(
        self, device_id: str, instruction: str, start: float
    ) -> ExecutionAttempt:
        """Level 3: VLM 视觉理解执行"""
        if not self._vlm:
            return ExecutionAttempt(
                level=ExecutionLevel.VLM,
                status=ExecutionStatus.SKIPPED,
                error="No VLM executor configured",
                latency_ms=(time.time() - start) * 1000,
            )

        # 获取截图
        screenshot_b64 = None
        if self._screenshot:
            try:
                screenshot_b64 = await self._screenshot(device_id)
            except Exception as e:
                logger.warning(f"Screenshot failed: {e}")

        result = await self._vlm(device_id, instruction, screenshot_b64)

        if result.get("success", False) or result.get("status") == "success":
            return ExecutionAttempt(
                level=ExecutionLevel.VLM,
                status=ExecutionStatus.SUCCESS,
                result=result,
                latency_ms=(time.time() - start) * 1000,
            )
        return ExecutionAttempt(
            level=ExecutionLevel.VLM,
            status=ExecutionStatus.FAILED,
            error=result.get("error", "VLM execution failed"),
            result=result,
            latency_ms=(time.time() - start) * 1000,
        )

    # ================================================================
    # 辅助
    # ================================================================

    @staticmethod
    def _attempt_to_dict(attempt: ExecutionAttempt) -> Dict:
        return {
            "level": attempt.level.value,
            "status": attempt.status.value,
            "result": attempt.result,
            "error": attempt.error,
            "latency_ms": attempt.latency_ms,
        }

    def _record(self, result: HybridResult):
        self._execution_history.append(result.to_dict())
        if len(self._execution_history) > 200:
            self._execution_history = self._execution_history[-200:]

    def get_stats(self) -> Dict:
        return {**self._stats, "registry_apps": len(self.registry._apps)}

    def get_history(self, limit: int = 50) -> List[Dict]:
        return self._execution_history[-limit:]


# ============================================================================
# 单例
# ============================================================================

_arbiter_instance: Optional[HybridExecutionArbiter] = None


def get_hybrid_arbiter() -> HybridExecutionArbiter:
    global _arbiter_instance
    if _arbiter_instance is None:
        _arbiter_instance = HybridExecutionArbiter()
    return _arbiter_instance
