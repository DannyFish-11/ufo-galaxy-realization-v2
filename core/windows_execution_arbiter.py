"""Windows Execution Arbiter — Windows 执行仲裁器
===============================================

Implements a single entrypoint for all Windows execution requests with a
strict four-level fallback chain:

  Level 1 – System API   (preferred)
      Direct Win32 / OS-level calls via :mod:`core.system_api`.
      Best for app launch, window focus, hotkey, and tray actions.

  Level 2 – UIAutomation (UIA)
      COM-based accessibility-tree control via
      :mod:`windows_client.autonomy.autonomy_manager`.
      Best for element-level interactions (click by name, type into field).

  Level 3 – GUI automation
      Coordinate-based input simulation.
      Falls back to :mod:`core.device_control_service` or the
      Node_36_UIAWindows HTTP API.

  Level 4 – VLM (vision-language model)
      Screenshot + VLM reasoning as a last resort when all structural
      approaches have failed.

Observability
-------------
Every execution attempt emits a structured log entry containing:

  - ``executor_level``  – which level was tried (system_api / uia / gui / vlm)
  - ``fallback_reason`` – why the previous level was skipped or failed
  - ``action_summary``  – brief human-readable description of the action
  - ``device_id``       – target device identifier

External APIs remain stable; this module is an internal routing layer.

Usage
-----
::

    from core.windows_execution_arbiter import get_windows_arbiter

    arbiter = get_windows_arbiter()
    result = await arbiter.execute(
        action="click",
        params={"x": 100, "y": 200},
        device_id="windows-1",
        instruction="Click the OK button",
    )
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("Galaxy.WindowsArbiter")

# ---------------------------------------------------------------------------
# Public enumerations
# ---------------------------------------------------------------------------


class WinExecLevel(str, Enum):
    """Ordered execution levels used by the arbiter."""

    SYSTEM_API = "system_api"  # Win32 / OS-level API calls
    UIA = "uia"                # UIAutomation COM accessibility
    GUI = "gui"                # Coordinate-based GUI automation
    VLM = "vlm"                # Vision-Language Model fallback


class WinExecStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"   # executor not configured / not applicable
    TIMEOUT = "timeout"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class WinExecAttempt:
    """Record of a single execution attempt at one level."""

    level: WinExecLevel
    status: WinExecStatus
    result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    fallback_reason: str = ""  # why this level was reached (non-empty from L2 onward)
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level.value,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "fallback_reason": self.fallback_reason,
            "latency_ms": round(self.latency_ms, 2),
        }


@dataclass
class WinExecResult:
    """Final result returned by :meth:`WindowsExecutionArbiter.execute`."""

    request_id: str
    success: bool
    final_level: WinExecLevel
    device_id: str
    action_summary: str
    result: Dict[str, Any] = field(default_factory=dict)
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    total_latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "success": self.success,
            "final_level": self.final_level.value,
            "device_id": self.device_id,
            "action_summary": self.action_summary,
            "result": self.result,
            "attempts": self.attempts,
            "total_latency_ms": round(self.total_latency_ms, 2),
        }


# ---------------------------------------------------------------------------
# Executor callable type aliases
# ---------------------------------------------------------------------------

# Each executor is an async callable returning {"success": bool, ...}.
# Using callables keeps adapters swappable and simplifies unit testing.

# system_api executor: (action, params, device_id) -> result_dict
SystemAPIExecutor = Callable[[str, Dict[str, Any], str], Awaitable[Dict[str, Any]]]

# uia executor: (action, params, device_id) -> result_dict
UIAExecutor = Callable[[str, Dict[str, Any], str], Awaitable[Dict[str, Any]]]

# gui executor: (action, params, device_id) -> result_dict
GUIExecutor = Callable[[str, Dict[str, Any], str], Awaitable[Dict[str, Any]]]

# vlm executor: (device_id, instruction, screenshot_b64) -> result_dict
VLMExecutor = Callable[[str, str, Optional[str]], Awaitable[Dict[str, Any]]]

# screenshot getter: (device_id) -> base64_string | None
ScreenshotGetter = Callable[[str], Awaitable[Optional[str]]]


# ---------------------------------------------------------------------------
# Built-in default adapters
# ---------------------------------------------------------------------------


def _make_default_system_api_executor() -> Optional[SystemAPIExecutor]:
    """Return an async adapter over the :class:`~core.system_api.windows_system_api.WindowsSystemAPI`
    facade or *None* when the facade is disabled / unavailable.

    The facade is the preferred entry-point for all System API actions because
    it provides a consistent request/response model, structured logging, and
    in-process metrics.  It routes to the lower-level
    :class:`~core.system_api.platform_api.SystemAPI` adapter internally.
    """

    try:
        from core.system_api.windows_system_api import (  # type: ignore[import]
            get_windows_system_api,
        )

        facade = get_windows_system_api()
        if not facade.is_available:
            return None

        async def _system_api_exec(
            action: str, params: Dict[str, Any], device_id: str
        ) -> Dict[str, Any]:
            resp = facade.dispatch(action, params, device_id=device_id)
            if not resp.handled:
                # Facade explicitly says it cannot handle this action.
                return {
                    "success": False,
                    "error": resp.fallback_reason or f"system_api: unsupported action '{action}'",
                }
            return {
                "success": resp.success,
                "error": resp.error or "",
                **resp.data,
            }

        return _system_api_exec
    except Exception:
        return None


def _make_default_uia_executor() -> Optional[UIAExecutor]:
    """Return an async adapter over :class:`windows_client.autonomy.autonomy_manager.WindowsAutonomyManager` or *None*.

    This adapter requires the ``windows_client`` package and COM/UIAutomation
    support — both of which are only available on Windows.  On other platforms
    the import silently fails and the UIA level is skipped.
    """

    try:
        from windows_client.autonomy.autonomy_manager import (  # type: ignore[import]
            WindowsAutonomyManager,
        )

        manager = WindowsAutonomyManager()

        async def _uia_exec(
            action: str, params: Dict[str, Any], device_id: str
        ) -> Dict[str, Any]:
            try:
                uia_action = {"type": action, "params": params}
                result = manager.execute_action(uia_action)
                return result if isinstance(result, dict) else {"success": bool(result)}
            except Exception as exc:
                return {"success": False, "error": str(exc)}

        return _uia_exec
    except Exception:
        return None


def _make_default_gui_executor() -> Optional[GUIExecutor]:
    """Return an async adapter over :mod:`core.device_control_service` or *None*."""

    try:
        from core.device_control_service import device_control  # type: ignore[import]

        async def _gui_exec(
            action: str, params: Dict[str, Any], device_id: str
        ) -> Dict[str, Any]:
            try:
                result = await device_control.execute_action(
                    device_id=device_id,
                    action=action,
                    params=params,
                )
                return result if isinstance(result, dict) else {"success": bool(result)}
            except Exception as exc:
                return {"success": False, "error": str(exc)}

        return _gui_exec
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main arbiter
# ---------------------------------------------------------------------------


class WindowsExecutionArbiter:
    """Single entrypoint for all Windows execution requests.

    Enforces a strict four-level fallback chain:
    ``system_api`` → ``uia`` → ``gui`` → ``vlm``.

    Each level is attempted in order; the first success terminates the chain.
    When a level fails the failure reason is recorded and propagated as
    ``fallback_reason`` to the next level's attempt log entry.

    Parameters
    ----------
    system_api_executor:
        Async callable for System-API-level execution.  When *None* the
        System API level is skipped.
    uia_executor:
        Async callable for UIAutomation-level execution.
    gui_executor:
        Async callable for GUI-automation-level execution.
    vlm_executor:
        Async callable for VLM-level execution (last resort).
    screenshot_getter:
        Async callable that returns a base64 screenshot for the VLM level.
    use_defaults:
        When *True* (default) auto-populate any *None* executor with the
        built-in default adapter (best-effort; silently skips if the
        underlying module is unavailable).
    """

    def __init__(
        self,
        system_api_executor: Optional[SystemAPIExecutor] = None,
        uia_executor: Optional[UIAExecutor] = None,
        gui_executor: Optional[GUIExecutor] = None,
        vlm_executor: Optional[VLMExecutor] = None,
        screenshot_getter: Optional[ScreenshotGetter] = None,
        use_defaults: bool = True,
    ) -> None:
        self._system_api = system_api_executor
        self._uia = uia_executor
        self._gui = gui_executor
        self._vlm = vlm_executor
        self._screenshot = screenshot_getter

        if use_defaults:
            if self._system_api is None:
                self._system_api = _make_default_system_api_executor()
            if self._uia is None:
                self._uia = _make_default_uia_executor()
            if self._gui is None:
                self._gui = _make_default_gui_executor()

        self._stats: Dict[str, int] = {
            "total": 0,
            "system_api_success": 0,
            "uia_success": 0,
            "gui_success": 0,
            "vlm_success": 0,
            "all_failed": 0,
        }
        self._history: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_executors(
        self,
        system_api: Optional[SystemAPIExecutor] = None,
        uia: Optional[UIAExecutor] = None,
        gui: Optional[GUIExecutor] = None,
        vlm: Optional[VLMExecutor] = None,
        screenshot: Optional[ScreenshotGetter] = None,
    ) -> None:
        """Replace one or more executors at runtime (useful for testing)."""
        if system_api is not None:
            self._system_api = system_api
        if uia is not None:
            self._uia = uia
        if gui is not None:
            self._gui = gui
        if vlm is not None:
            self._vlm = vlm
        if screenshot is not None:
            self._screenshot = screenshot

    async def execute(
        self,
        action: str,
        params: Optional[Dict[str, Any]] = None,
        device_id: str = "local",
        instruction: str = "",
        force_level: Optional[WinExecLevel] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> WinExecResult:
        """Execute a Windows action through the strict fallback chain.

        Parameters
        ----------
        action:
            Action name (e.g. ``"click"``, ``"launch_app"``, ``"type"``).
        params:
            Action parameters dict.
        device_id:
            Target device identifier used for logging and executor routing.
        instruction:
            Natural-language instruction forwarded to the VLM executor.
        force_level:
            Skip the fallback chain and use only the specified level.
        context:
            Optional ambient context (e.g. current app, window title).

        Returns
        -------
        WinExecResult
            Contains the final outcome, all attempt records, and timing.
        """
        params = params or {}
        context = context or {}
        request_id = str(uuid.uuid4())[:12]
        start = time.time()
        self._stats["total"] += 1

        action_summary = _build_action_summary(action, params, device_id)

        if force_level is not None:
            levels: List[WinExecLevel] = [force_level]
        else:
            levels = [
                WinExecLevel.SYSTEM_API,
                WinExecLevel.UIA,
                WinExecLevel.GUI,
                WinExecLevel.VLM,
            ]

        attempts: List[WinExecAttempt] = []
        last_failure_reason = ""

        for level in levels:
            attempt = await self._try_level(
                level=level,
                action=action,
                params=params,
                device_id=device_id,
                instruction=instruction or action_summary,
                fallback_reason=last_failure_reason,
            )
            attempts.append(attempt)

            _emit_attempt_log(
                level=level,
                status=attempt.status,
                fallback_reason=last_failure_reason,
                action_summary=action_summary,
                device_id=device_id,
                error=attempt.error,
            )

            if attempt.status == WinExecStatus.SUCCESS:
                self._stats[f"{level.value}_success"] += 1
                win_result = WinExecResult(
                    request_id=request_id,
                    success=True,
                    final_level=level,
                    device_id=device_id,
                    action_summary=action_summary,
                    result=attempt.result,
                    attempts=[a.to_dict() for a in attempts],
                    total_latency_ms=(time.time() - start) * 1000,
                )
                self._record(win_result)
                return win_result

            # Propagate failure reason to next level
            if attempt.status != WinExecStatus.SKIPPED:
                last_failure_reason = (
                    attempt.error or f"{level.value} returned non-success"
                )
            else:
                last_failure_reason = attempt.error  # e.g. "No UIA executor configured"

        # All levels exhausted
        self._stats["all_failed"] += 1
        win_result = WinExecResult(
            request_id=request_id,
            success=False,
            final_level=levels[-1] if levels else WinExecLevel.VLM,
            device_id=device_id,
            action_summary=action_summary,
            result={"error": "All Windows execution levels failed"},
            attempts=[a.to_dict() for a in attempts],
            total_latency_ms=(time.time() - start) * 1000,
        )
        self._record(win_result)
        logger.warning(
            "windows_arbiter | all_failed | %s | device=%s | attempts=%d",
            action_summary,
            device_id,
            len(attempts),
        )
        return win_result

    # ------------------------------------------------------------------
    # Stats / history
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Return aggregated execution statistics."""
        return dict(self._stats)

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent execution results (newest last)."""
        return self._history[-limit:]

    def route_command(
        self,
        action: str,
        params: Optional[Dict[str, Any]] = None,
        device_id: str = "local",
        instruction: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Synchronous wrapper around :meth:`execute` for use in non-async callers.

        This is the **unified entry point** for the Windows AIP client and any
        other synchronous caller that needs to dispatch a Windows action.  It
        runs :meth:`execute` inside a new or existing event loop and returns
        the plain dict representation of :class:`WinExecResult`.

        Parameters
        ----------
        action:
            Action name (e.g. ``"click"``, ``"launch_app"``, ``"screenshot"``).
        params:
            Action parameters dict.
        device_id:
            Target device identifier.
        instruction:
            Natural-language instruction forwarded to the VLM executor.
        context:
            Optional ambient context.

        Returns
        -------
        dict
            ``WinExecResult.to_dict()`` with at minimum ``success``,
            ``final_level``, and ``result`` keys.
        """
        coro = self.execute(
            action=action,
            params=params,
            device_id=device_id,
            instruction=instruction,
            context=context,
        )
        try:
            loop = asyncio.get_running_loop()
            # Already inside a running event loop — cannot call run_until_complete.
            # Dispatch to a separate thread with its own event loop via asyncio.run().
            # Note: this approach spawns a new thread and loop, so thread-local state
            # or resources tied to the caller's loop are NOT shared.  For most Windows
            # automation actions this is acceptable; callers that need tighter loop
            # coupling should use `await execute(...)` directly.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                win_result = future.result(timeout=30)
        except RuntimeError:
            # No running event loop — use asyncio.run() which creates one.
            win_result = asyncio.run(coro)
        return win_result.to_dict()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _try_level(
        self,
        level: WinExecLevel,
        action: str,
        params: Dict[str, Any],
        device_id: str,
        instruction: str,
        fallback_reason: str,
    ) -> WinExecAttempt:
        """Dispatch to the correct executor for *level*."""
        start = time.time()
        try:
            if level == WinExecLevel.SYSTEM_API:
                return await self._try_system_api(action, params, device_id, start, fallback_reason)
            if level == WinExecLevel.UIA:
                return await self._try_uia(action, params, device_id, start, fallback_reason)
            if level == WinExecLevel.GUI:
                return await self._try_gui(action, params, device_id, start, fallback_reason)
            if level == WinExecLevel.VLM:
                return await self._try_vlm(device_id, instruction, start, fallback_reason)
            return WinExecAttempt(
                level=level,
                status=WinExecStatus.FAILED,
                error=f"Unknown execution level: {level}",
                fallback_reason=fallback_reason,
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as exc:
            return WinExecAttempt(
                level=level,
                status=WinExecStatus.FAILED,
                error=str(exc),
                fallback_reason=fallback_reason,
                latency_ms=(time.time() - start) * 1000,
            )

    async def _try_system_api(
        self,
        action: str,
        params: Dict[str, Any],
        device_id: str,
        start: float,
        fallback_reason: str,
    ) -> WinExecAttempt:
        """Level 1: System API (Win32 / OS calls)."""
        if self._system_api is None:
            return WinExecAttempt(
                level=WinExecLevel.SYSTEM_API,
                status=WinExecStatus.SKIPPED,
                error="No System API executor configured",
                fallback_reason=fallback_reason,
                latency_ms=(time.time() - start) * 1000,
            )
        result = await self._system_api(action, params, device_id)
        ok = result.get("success", False) or result.get("status") == "success"
        return WinExecAttempt(
            level=WinExecLevel.SYSTEM_API,
            status=WinExecStatus.SUCCESS if ok else WinExecStatus.FAILED,
            result=result,
            error="" if ok else result.get("error", "system_api returned non-success"),
            fallback_reason=fallback_reason,
            latency_ms=(time.time() - start) * 1000,
        )

    async def _try_uia(
        self,
        action: str,
        params: Dict[str, Any],
        device_id: str,
        start: float,
        fallback_reason: str,
    ) -> WinExecAttempt:
        """Level 2: UIAutomation (COM accessibility tree)."""
        if self._uia is None:
            return WinExecAttempt(
                level=WinExecLevel.UIA,
                status=WinExecStatus.SKIPPED,
                error="No UIA executor configured",
                fallback_reason=fallback_reason,
                latency_ms=(time.time() - start) * 1000,
            )
        result = await self._uia(action, params, device_id)
        ok = result.get("success", False) or result.get("status") == "success"
        return WinExecAttempt(
            level=WinExecLevel.UIA,
            status=WinExecStatus.SUCCESS if ok else WinExecStatus.FAILED,
            result=result,
            error="" if ok else result.get("error", "uia returned non-success"),
            fallback_reason=fallback_reason,
            latency_ms=(time.time() - start) * 1000,
        )

    async def _try_gui(
        self,
        action: str,
        params: Dict[str, Any],
        device_id: str,
        start: float,
        fallback_reason: str,
    ) -> WinExecAttempt:
        """Level 3: GUI automation (coordinate-based input simulation)."""
        if self._gui is None:
            return WinExecAttempt(
                level=WinExecLevel.GUI,
                status=WinExecStatus.SKIPPED,
                error="No GUI executor configured",
                fallback_reason=fallback_reason,
                latency_ms=(time.time() - start) * 1000,
            )
        result = await self._gui(action, params, device_id)
        ok = result.get("success", False) or result.get("status") == "success"
        return WinExecAttempt(
            level=WinExecLevel.GUI,
            status=WinExecStatus.SUCCESS if ok else WinExecStatus.FAILED,
            result=result,
            error="" if ok else result.get("error", "gui automation returned non-success"),
            fallback_reason=fallback_reason,
            latency_ms=(time.time() - start) * 1000,
        )

    async def _try_vlm(
        self,
        device_id: str,
        instruction: str,
        start: float,
        fallback_reason: str,
    ) -> WinExecAttempt:
        """Level 4: VLM – screenshot + vision-language model (last resort)."""
        if self._vlm is None:
            return WinExecAttempt(
                level=WinExecLevel.VLM,
                status=WinExecStatus.SKIPPED,
                error="No VLM executor configured",
                fallback_reason=fallback_reason,
                latency_ms=(time.time() - start) * 1000,
            )

        screenshot_b64: Optional[str] = None
        if self._screenshot is not None:
            try:
                screenshot_b64 = await self._screenshot(device_id)
            except Exception as exc:
                logger.warning("windows_arbiter | screenshot_failed | %s", exc)

        result = await self._vlm(device_id, instruction, screenshot_b64)
        ok = result.get("success", False) or result.get("status") == "success"
        return WinExecAttempt(
            level=WinExecLevel.VLM,
            status=WinExecStatus.SUCCESS if ok else WinExecStatus.FAILED,
            result=result,
            error="" if ok else result.get("error", "vlm returned non-success"),
            fallback_reason=fallback_reason,
            latency_ms=(time.time() - start) * 1000,
        )

    def _record(self, result: WinExecResult) -> None:
        self._history.append(result.to_dict())
        if len(self._history) > 200:
            self._history = self._history[-200:]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_action_summary(
    action: str, params: Dict[str, Any], device_id: str
) -> str:
    """Build a concise human-readable summary of the action."""
    key_params = {
        k: v
        for k, v in params.items()
        if k in ("x", "y", "target", "app", "title", "text", "key")
    }
    if key_params:
        param_str = " ".join(f"{k}={v}" for k, v in key_params.items())
        return f"{action}({param_str}) on {device_id}"
    return f"{action} on {device_id}"


def _emit_attempt_log(
    level: WinExecLevel,
    status: WinExecStatus,
    fallback_reason: str,
    action_summary: str,
    device_id: str,
    error: str,
) -> None:
    """Emit a structured log line for each execution attempt."""
    if status == WinExecStatus.SUCCESS:
        logger.info(
            "windows_arbiter | executor_level=%s | status=success | action=%s | device=%s",
            level.value,
            action_summary,
            device_id,
        )
    elif status == WinExecStatus.SKIPPED:
        logger.debug(
            "windows_arbiter | executor_level=%s | status=skipped | reason=%s | action=%s | device=%s",
            level.value,
            error,
            action_summary,
            device_id,
        )
    else:
        msg = (
            "windows_arbiter | executor_level=%s | status=%s | fallback_reason=%s"
            " | error=%s | action=%s | device=%s"
        )
        logger.warning(
            msg,
            level.value,
            status.value,
            fallback_reason or "none",
            error,
            action_summary,
            device_id,
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_arbiter_instance: Optional[WindowsExecutionArbiter] = None


def get_windows_arbiter() -> WindowsExecutionArbiter:
    """Return the process-wide :class:`WindowsExecutionArbiter` singleton.

    Lazily instantiated on first call; subsequent calls return the same
    instance.  Use :func:`reset_windows_arbiter` in tests to obtain a fresh
    instance.
    """
    global _arbiter_instance
    if _arbiter_instance is None:
        _arbiter_instance = WindowsExecutionArbiter()
    return _arbiter_instance


def reset_windows_arbiter() -> None:
    """Reset the singleton (intended for test isolation)."""
    global _arbiter_instance
    _arbiter_instance = None
