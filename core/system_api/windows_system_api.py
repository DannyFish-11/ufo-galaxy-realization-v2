"""Unified Windows System API facade — PR-9.

This module provides a *single, consistent* entry-point for high-frequency
Windows system actions:

  - App / window management  (launch, focus, close)
  - File operations           (open, save/move, delete)
  - Process queries           (list, kill)
  - Clipboard                 (get / set text)
  - Notifications             (toast / balloon)

Every call is routed through :class:`WindowsSystemAPI` which:

1. Validates the incoming :class:`SystemAPIRequest`.
2. Dispatches to the appropriate :class:`~core.system_api.platform_api.SystemAPI`
   method.
3. Measures latency and emits a structured log entry (observability).
4. Returns a normalised :class:`SystemAPIResponse` — callers never need to
   know which low-level primitive handled the action.

Fallback behaviour
------------------
When the underlying :class:`SystemAPI` adapter is unavailable (non-Windows
host or ``is_available=False``) every method returns a
``SystemAPIResponse(success=False, handled=False, ...)`` so that callers
can gracefully fall through to UIA / GUI / VLM tiers.

Observability
-------------
Each invocation emits a ``Galaxy.SystemAPI`` log record at DEBUG level
containing::

    {
        "action":    "<action_name>",
        "success":   true | false,
        "duration_ms": 3.2,
        "error":     "<message or None>",
        "fallback_reason": "<why System API was skipped, or empty>"
    }

Global metrics counters are exposed via :func:`get_sysapi_metrics`.

Configuration
-------------
The facade respects the ``enable_windows_system_api`` flag in *config.json*
(default: ``true``).  Set it to ``false`` to disable the facade entirely so
the arbiter falls straight through to UIA.

Usage
-----
::

    from core.system_api.windows_system_api import get_windows_system_api

    facade = get_windows_system_api()
    resp = facade.dispatch("launch_app", {"target": "notepad.exe"})
    if resp.handled and resp.success:
        print("launched pid", resp.data.get("pid"))
    else:
        # fall back to UIA / GUI / VLM
        ...
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.SystemAPI")

# ---------------------------------------------------------------------------
# Public request / response model
# ---------------------------------------------------------------------------

# Actions supported by the facade
SUPPORTED_ACTIONS = frozenset(
    {
        # App / window management
        "launch_app",
        "launch",
        "focus_window",
        "focus",
        "close_window",
        "close",
        "enumerate_windows",
        # File operations
        "open_file",
        "move_file",
        "delete_file",
        # Process queries
        "list_processes",
        "kill_process",
        # Clipboard
        "get_clipboard",
        "set_clipboard",
        # Notifications
        "send_notification",
    }
)


@dataclass
class SystemAPIRequest:
    """Normalised request sent to :class:`WindowsSystemAPI.dispatch`."""

    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    device_id: str = ""
    request_id: str = ""


@dataclass
class SystemAPIResponse:
    """Normalised response from :class:`WindowsSystemAPI.dispatch`.

    Attributes
    ----------
    success:
        True when the action completed without error.
    handled:
        True when the facade *tried* to handle the action (even if it
        failed).  ``False`` means the action is not in scope for the
        System API tier; callers should pass it to the next tier.
    data:
        Arbitrary result payload (pid, text, window list, …).
    error:
        Human-readable error message or empty string.
    duration_ms:
        Wall-clock time taken by this call.
    fallback_reason:
        Non-empty when ``handled=False``; explains why.
    """

    success: bool
    handled: bool = True
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0.0
    fallback_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "handled": self.handled,
            "data": self.data,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
            "fallback_reason": self.fallback_reason,
        }


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class _SysAPIMetrics:
    """Lightweight in-process counters for observability."""

    def __init__(self) -> None:
        self.total: int = 0
        self.success: int = 0
        self.failed: int = 0
        self.skipped: int = 0  # handled=False
        self.by_action: Dict[str, int] = {}

    def record(self, action: str, *, success: bool, handled: bool) -> None:
        self.total += 1
        self.by_action[action] = self.by_action.get(action, 0) + 1
        if not handled:
            self.skipped += 1
        elif success:
            self.success += 1
        else:
            self.failed += 1

    def snapshot(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "skipped": self.skipped,
            "by_action": dict(self.by_action),
        }


_metrics_instance: Optional[_SysAPIMetrics] = None


def get_sysapi_metrics() -> _SysAPIMetrics:
    """Return the process-level metrics singleton."""
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = _SysAPIMetrics()
    return _metrics_instance


def reset_sysapi_metrics() -> None:
    """Reset the metrics singleton (intended for tests only)."""
    global _metrics_instance
    _metrics_instance = None


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------


class WindowsSystemAPI:
    """Unified Windows System API facade.

    Parameters
    ----------
    adapter:
        Optional :class:`~core.system_api.platform_api.SystemAPI` instance.
        When *None* the singleton from :func:`core.system_api.get_system_api`
        is used.
    enabled:
        If *False* every :meth:`dispatch` call returns
        ``handled=False`` immediately, letting the caller fall through.
    """

    def __init__(
        self,
        adapter=None,
        enabled: bool = True,
    ) -> None:
        self._enabled = enabled
        self._adapter = adapter  # resolved lazily

    # ------------------------------------------------------------------
    # Adapter resolution
    # ------------------------------------------------------------------

    def _get_adapter(self):
        if self._adapter is None:
            try:
                from core.system_api import get_system_api  # type: ignore[import]
                self._adapter = get_system_api()
            except Exception as exc:
                from core.system_api.platform_api import NoOpSystemAPI
                self._adapter = NoOpSystemAPI()
        return self._adapter

    @property
    def is_available(self) -> bool:
        """True when the facade is enabled and the adapter reports availability."""
        if not self._enabled:
            return False
        try:
            return bool(self._get_adapter().is_available)
        except Exception as exc:
            return False

    # ------------------------------------------------------------------
    # Unified dispatch
    # ------------------------------------------------------------------

    def dispatch(
        self,
        action: str,
        params: Optional[Dict[str, Any]] = None,
        device_id: str = "",
        request_id: str = "",
    ) -> SystemAPIResponse:
        """Route *action* to the appropriate adapter method.

        Parameters
        ----------
        action:
            One of the :data:`SUPPORTED_ACTIONS` strings.
        params:
            Action-specific parameters.
        device_id:
            Informational device identifier (used for logging only).
        request_id:
            Caller-provided correlation ID (used for logging only).

        Returns
        -------
        SystemAPIResponse
            Always returns a response; never raises.
        """
        params = params or {}
        start = time.monotonic()
        metrics = get_sysapi_metrics()

        # --- feature flag check ---
        if not self._enabled:
            resp = SystemAPIResponse(
                success=False,
                handled=False,
                fallback_reason="windows_system_api disabled",
            )
            metrics.record(action, success=False, handled=False)
            self._emit_log(action, resp, device_id, request_id, 0.0)
            return resp

        # --- adapter availability check ---
        adapter = self._get_adapter()
        if not adapter.is_available:
            resp = SystemAPIResponse(
                success=False,
                handled=False,
                fallback_reason="system_api adapter not available on this platform",
            )
            metrics.record(action, success=False, handled=False)
            self._emit_log(action, resp, device_id, request_id, 0.0)
            return resp

        # --- scope check ---
        if action not in SUPPORTED_ACTIONS:
            resp = SystemAPIResponse(
                success=False,
                handled=False,
                fallback_reason=f"action '{action}' not in system_api scope",
            )
            metrics.record(action, success=False, handled=False)
            self._emit_log(action, resp, device_id, request_id, 0.0)
            return resp

        # --- dispatch ---
        try:
            resp = self._dispatch_action(action, params, adapter)
        except Exception as exc:
            logger.exception("WindowsSystemAPI unexpected error action=%s: %s", action, exc)
            resp = SystemAPIResponse(
                success=False,
                handled=True,
                error=f"unexpected error: {exc}",
            )

        resp.duration_ms = (time.monotonic() - start) * 1000
        metrics.record(action, success=resp.success, handled=resp.handled)
        self._emit_log(action, resp, device_id, request_id, resp.duration_ms)
        return resp

    # ------------------------------------------------------------------
    # Internal dispatch table
    # ------------------------------------------------------------------

    def _dispatch_action(
        self,
        action: str,
        params: Dict[str, Any],
        adapter,
    ) -> SystemAPIResponse:
        """Dispatch *action* to the adapter and normalise the result."""

        # ---- App / window management --------------------------------

        if action in ("launch_app", "launch"):
            target = params.get("target") or params.get("app", "")
            if not target:
                return SystemAPIResponse(success=False, error="missing 'target' param")
            r = adapter.launch_app(
                target,
                args=params.get("args"),
                working_dir=params.get("working_dir"),
            )
            return SystemAPIResponse(
                success=r.success,
                data={"pid": r.pid} if r.pid else {},
                error=r.error or "",
            )

        if action in ("focus_window", "focus"):
            key = params.get("hwnd") or params.get("title") or params.get("window_title", "")
            ok = adapter.focus_window(key)
            return SystemAPIResponse(success=ok, error="" if ok else "window not found or focus failed")

        if action in ("close_window", "close"):
            key = params.get("hwnd") or params.get("title") or params.get("window_title", "")
            ok = adapter.close_window(key)
            return SystemAPIResponse(success=ok, error="" if ok else "window not found or close failed")

        if action == "enumerate_windows":
            windows = adapter.enumerate_windows(
                filter_title=params.get("title_filter") or params.get("filter")
            )
            return SystemAPIResponse(
                success=True,
                data={"windows": [w.__dict__ for w in windows]},
            )

        # ---- File operations ----------------------------------------

        if action == "open_file":
            path = params.get("path", "")
            r = adapter.open_file(path)
            return SystemAPIResponse(success=r.success, data={"path": r.path or ""}, error=r.error or "")

        if action == "move_file":
            src = params.get("src", "")
            dst = params.get("dst", "")
            r = adapter.move_file(src, dst)
            return SystemAPIResponse(success=r.success, data={"path": r.path or ""}, error=r.error or "")

        if action == "delete_file":
            path = params.get("path", "")
            r = adapter.delete_file(path)
            return SystemAPIResponse(success=r.success, data={"path": r.path or ""}, error=r.error or "")

        # ---- Process queries ----------------------------------------

        if action == "list_processes":
            procs = adapter.list_processes()
            return SystemAPIResponse(
                success=True,
                data={"processes": [p.__dict__ for p in procs]},
            )

        if action == "kill_process":
            pid = params.get("pid")
            if pid is None:
                return SystemAPIResponse(success=False, error="missing 'pid' param")
            ok = adapter.kill_process(int(pid))
            return SystemAPIResponse(success=ok, error="" if ok else f"process {pid} not found or not killed")

        # ---- Clipboard ----------------------------------------------

        if action == "get_clipboard":
            r = adapter.get_clipboard()
            return SystemAPIResponse(success=r.success, data={"text": r.text or ""}, error=r.error or "")

        if action == "set_clipboard":
            text = params.get("text", "")
            r = adapter.set_clipboard(text)
            return SystemAPIResponse(success=r.success, error=r.error or "")

        # ---- Notifications ------------------------------------------

        if action == "send_notification":
            title = params.get("title", "Galaxy")
            body = params.get("body", "")
            icon_path = params.get("icon_path")
            r = adapter.send_notification(title=title, body=body, icon_path=icon_path)
            return SystemAPIResponse(
                success=r.success,
                data={"notification_id": r.notification_id} if r.notification_id else {},
                error=r.error or "",
            )

        # Should not reach here due to scope guard above, but be safe.
        return SystemAPIResponse(
            success=False,
            handled=False,
            fallback_reason=f"unhandled action '{action}'",
        )

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    @staticmethod
    def _emit_log(
        action: str,
        resp: SystemAPIResponse,
        device_id: str,
        request_id: str,
        duration_ms: float,
    ) -> None:
        logger.debug(
            "system_api | action=%s | success=%s | handled=%s | "
            "duration_ms=%.2f | device=%s | req=%s | error=%r | fallback=%r",
            action,
            resp.success,
            resp.handled,
            duration_ms,
            device_id or "n/a",
            request_id or "n/a",
            resp.error or None,
            resp.fallback_reason or None,
        )


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------

_facade_instance: Optional[WindowsSystemAPI] = None


def get_windows_system_api(enabled: Optional[bool] = None) -> WindowsSystemAPI:
    """Return the process-level :class:`WindowsSystemAPI` singleton.

    Parameters
    ----------
    enabled:
        Override the ``enable_windows_system_api`` config flag.
        Pass *None* (default) to read from config.
    """
    global _facade_instance
    if _facade_instance is None:
        if enabled is None:
            try:
                import json
                import os as _os
                _cfg_path = _os.path.join(
                    _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))),
                    "config.json",
                )
                with open(_cfg_path, encoding="utf-8") as _f:
                    _cfg = json.load(_f)
                enabled = bool(_cfg.get("enable_windows_system_api", True))
            except Exception as exc:
                logger.debug("Fallback triggered: %s", exc)
                enabled = True
        _facade_instance = WindowsSystemAPI(enabled=enabled)
    return _facade_instance


def reset_windows_system_api() -> None:
    """Reset the singleton (intended for tests only)."""
    global _facade_instance
    _facade_instance = None
