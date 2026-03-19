"""core.execution.decision_executor — Windows Execution Layer
=============================================================

Consumes a ``state_continuum`` dict (as produced by
:meth:`~core.openclawd.OpenClawd._run_continuum`) and dispatches OS-level
actions based on the :class:`~core.continuum.types.ActionLevel` emitted by
the Decision Gate.

Action mapping
--------------
+---------------+-----------------------------------------------------+
| action_level  | behaviour                                           |
+===============+=====================================================+
| observe       | no-op                                               |
+---------------+-----------------------------------------------------+
| hint          | no-op (lightweight notification stub, future use)   |
+---------------+-----------------------------------------------------+
| assist        | soft action — focus the most-relevant window or     |
|               | open a context app from the allowlist               |
+---------------+-----------------------------------------------------+
| execute       | explicit app launch / command execution (guarded    |
|               | by allowlist and ``enable_system_actions`` flag)    |
+---------------+-----------------------------------------------------+

Safety constraints
------------------
* Execution is **disabled by default** (``enable_system_actions: false``).
* Only apps/commands present in ``execution_app_allowlist`` can be launched.
* The ``PolicyGate`` validates every action before dispatch.
* All exceptions are caught, logged at DEBUG level, and never re-raised so
  the calling response flow is never interrupted.

Configuration keys (``config.json``)
-------------------------------------
``enable_system_actions`` : bool, default ``false``
    Master on/off switch.  Set to ``true`` to enable execution.

``execution_app_allowlist`` : list[str], default ``[]``
    Absolute paths, executable names, or URI schemes that may be launched.
    An empty list means no app can be launched even if the flag is enabled.

``execution_assist_app`` : str | null, default ``null``
    Optional default app to focus/open when action_level is ``assist``.
    If absent, the assist action performs a best-effort window-focus only.

Usage::

    from core.execution.decision_executor import DecisionExecutor

    executor = DecisionExecutor()
    result = executor.execute(state_continuum_dict)
    # result.action_taken, result.target, result.skipped_reason
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    """Return value from :meth:`DecisionExecutor.execute`.

    An ``ExecutionResult`` is always returned; the executor never raises.
    """

    action_taken: str = "none"
    """Short description of what was done (e.g. ``'focus_window'``, ``'launch_app'``, ``'noop'``)."""

    target: Optional[str] = None
    """The specific target that was acted on (window title, app path, …)."""

    success: bool = False
    """True when the OS call was made and reported success."""

    skipped_reason: Optional[str] = None
    """Non-None when execution was intentionally skipped (disabled, policy, …)."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Extensibility bag for future fields."""


# ---------------------------------------------------------------------------
# Policy gate
# ---------------------------------------------------------------------------


class PolicyGate:
    """Validates an action against the configured allowlist.

    Instantiate once with the current config and reuse across calls.

    Parameters
    ----------
    enabled:
        Master switch; when False every action is blocked.
    allowlist:
        Set of allowed targets.  Comparison is case-insensitive.
    """

    def __init__(
        self,
        enabled: bool = False,
        allowlist: Optional[List[str]] = None,
    ) -> None:
        self._enabled = enabled
        self._allowlist: List[str] = [a.lower() for a in (allowlist or [])]

    # ------------------------------------------------------------------

    @property
    def is_enabled(self) -> bool:
        """True when system-action execution is switched on."""
        return self._enabled

    def allows(self, target: str) -> bool:
        """Return True if *target* is permitted under current policy.

        An empty allowlist always returns False (deny-by-default).
        """
        if not self._enabled:
            return False
        if not self._allowlist:
            return False
        tgt_lower = target.lower()
        return any(tgt_lower == entry or tgt_lower.startswith(entry) for entry in self._allowlist)

    def check_action_level(self, action_level_str: str) -> bool:
        """Return True when the action level is at least ``assist``.

        Parameters
        ----------
        action_level_str:
            String value of the :class:`~core.continuum.types.ActionLevel`
            (``'observe'``, ``'hint'``, ``'assist'``, ``'execute'``).
        """
        return action_level_str in ("assist", "execute")


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class DecisionExecutor:
    """Binds Decision Gate outputs to System API actions.

    The executor is constructed lazily — it reads configuration on first
    :meth:`execute` call so callers do not need to pass config explicitly.

    All OS calls are routed through
    :func:`core.system_api.get_system_api` which returns
    :class:`~core.system_api.platform_api.NoOpSystemAPI` on non-Windows
    hosts, guaranteeing safe cross-platform operation.
    """

    def __init__(self) -> None:
        self._policy: Optional[PolicyGate] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_policy(self) -> PolicyGate:
        """Lazy-initialise and return the cached :class:`PolicyGate`."""
        if self._policy is None:
            try:
                from core.unified_config import config as _cfg  # type: ignore[import]
                enabled: bool = bool(_cfg.get("enable_system_actions", False))
                allowlist: List[str] = list(_cfg.get("execution_app_allowlist", []))
            except Exception as exc:
                logger.debug("DecisionExecutor: failed to load config — disabling: %s", exc)
                enabled = False
                allowlist = []
            self._policy = PolicyGate(enabled=enabled, allowlist=allowlist)
        return self._policy

    def _get_assist_app(self) -> Optional[str]:
        """Return the configured assist-app target (may be None)."""
        try:
            from core.unified_config import config as _cfg  # type: ignore[import]
            return _cfg.get("execution_assist_app") or None
        except Exception:
            return None

    @staticmethod
    def _get_system_api():
        """Return the platform system API, with safe fallback."""
        try:
            from core.system_api import get_system_api  # type: ignore[import]
            return get_system_api()
        except Exception as exc:
            logger.debug("DecisionExecutor: system_api unavailable: %s", exc)
            try:
                from core.system_api.platform_api import NoOpSystemAPI
                return NoOpSystemAPI()
            except Exception:
                return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        state_continuum: Optional[Dict[str, Any]],
    ) -> ExecutionResult:
        """Dispatch an OS action derived from *state_continuum*.

        Parameters
        ----------
        state_continuum:
            Serialised :class:`~core.continuum.types.ContinuumState` dict
            (as returned by ``OpenClawd._run_continuum()``).  A ``None``
            value is treated as *observe* (no-op).

        Returns
        -------
        ExecutionResult
            Always returned; never raises.
        """
        try:
            return self._execute_inner(state_continuum)
        except Exception as exc:
            logger.debug("DecisionExecutor.execute error (swallowed): %s", exc)
            return ExecutionResult(
                action_taken="error",
                skipped_reason=f"internal_error: {exc}",
                success=False,
            )

    def _execute_inner(
        self,
        state_continuum: Optional[Dict[str, Any]],
    ) -> ExecutionResult:
        """Core dispatch logic — called inside a try/except in :meth:`execute`."""
        # ── 1. Extract action_level from continuum dict ──────────────────────
        action_level_str = _extract_action_level(state_continuum)

        # ── 2. Fast-path: observe / hint → no-op ────────────────────────────
        if action_level_str in ("observe", "hint"):
            logger.debug(
                "DecisionExecutor: action_level=%s → noop", action_level_str
            )
            return ExecutionResult(
                action_taken="noop",
                success=True,
                skipped_reason=f"action_level={action_level_str}",
            )

        # ── 3. Policy gate check ─────────────────────────────────────────────
        policy = self._get_policy()
        if not policy.is_enabled:
            logger.debug(
                "DecisionExecutor: enable_system_actions=false → skipping action_level=%s",
                action_level_str,
            )
            return ExecutionResult(
                action_taken="noop",
                success=True,
                skipped_reason="enable_system_actions=false",
            )

        # ── 4. Dispatch by action level ──────────────────────────────────────
        if action_level_str == "assist":
            return self._dispatch_assist(policy)
        if action_level_str == "execute":
            return self._dispatch_execute(state_continuum, policy)

        # Unknown level — no-op
        return ExecutionResult(
            action_taken="noop",
            success=True,
            skipped_reason=f"unknown_action_level={action_level_str}",
        )

    # ------------------------------------------------------------------
    # Assist dispatch (soft action: focus window or open context app)
    # ------------------------------------------------------------------

    def _dispatch_assist(self, policy: PolicyGate) -> ExecutionResult:
        """Handle action_level=assist: focus window or open context app."""
        api = self._get_system_api()
        if api is None:
            return ExecutionResult(
                action_taken="noop",
                skipped_reason="system_api_unavailable",
                success=False,
            )

        assist_app = self._get_assist_app()

        # If an assist app is configured and allowlisted, try to focus it.
        if assist_app and policy.allows(assist_app):
            focused = api.focus_window(assist_app)
            if focused:
                logger.debug(
                    "DecisionExecutor: assist → focused window %r", assist_app
                )
                return ExecutionResult(
                    action_taken="focus_window",
                    target=assist_app,
                    success=True,
                )
            # Focus failed — fall through to launch
            result = api.launch_app(assist_app)
            logger.debug(
                "DecisionExecutor: assist → launch_app %r success=%s",
                assist_app, result.success,
            )
            return ExecutionResult(
                action_taken="launch_app",
                target=assist_app,
                success=result.success,
                metadata={"error": result.error} if result.error else {},
            )

        # No assist app configured — best-effort focus (no target, safe)
        logger.debug("DecisionExecutor: assist → no target configured, noop")
        return ExecutionResult(
            action_taken="noop",
            success=True,
            skipped_reason="no_assist_target_configured",
        )

    # ------------------------------------------------------------------
    # Execute dispatch (explicit app launch, guarded by allowlist)
    # ------------------------------------------------------------------

    def _dispatch_execute(
        self,
        state_continuum: Optional[Dict[str, Any]],
        policy: PolicyGate,
    ) -> ExecutionResult:
        """Handle action_level=execute: launch an allowlisted app."""
        api = self._get_system_api()
        if api is None:
            return ExecutionResult(
                action_taken="noop",
                skipped_reason="system_api_unavailable",
                success=False,
            )

        # Prefer execution_target from continuum metadata; fall back to
        # execution_assist_app; disallow if neither is allowlisted.
        target = _extract_execution_target(state_continuum) or self._get_assist_app()

        if not target:
            logger.debug(
                "DecisionExecutor: execute → no target in state or config, skipping"
            )
            return ExecutionResult(
                action_taken="noop",
                success=True,
                skipped_reason="no_execution_target",
            )

        if not policy.allows(target):
            logger.debug(
                "DecisionExecutor: execute → target %r not in allowlist, blocking",
                target,
            )
            return ExecutionResult(
                action_taken="noop",
                success=False,
                skipped_reason=f"target_not_in_allowlist: {target}",
            )

        result = api.launch_app(target)
        logger.debug(
            "DecisionExecutor: execute → launch_app %r success=%s error=%s",
            target, result.success, result.error,
        )
        return ExecutionResult(
            action_taken="launch_app",
            target=target,
            success=result.success,
            metadata={"pid": result.pid, "error": result.error},
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _extract_action_level(state_continuum: Optional[Dict[str, Any]]) -> str:
    """Return the action_level string from a serialised ContinuumState dict.

    Returns ``'observe'`` when the dict is absent or malformed.
    """
    if not state_continuum or not isinstance(state_continuum, dict):
        return "observe"
    try:
        decision = state_continuum.get("decision") or {}
        if isinstance(decision, dict):
            return str(decision.get("action_level", "observe"))
    except Exception:
        pass
    return "observe"


def _extract_execution_target(state_continuum: Optional[Dict[str, Any]]) -> Optional[str]:
    """Return an explicit execution target from the continuum state metadata.

    Looks for ``state_continuum["metadata"]["execution_target"]``.
    Returns ``None`` when absent.
    """
    if not state_continuum or not isinstance(state_continuum, dict):
        return None
    try:
        meta = state_continuum.get("metadata") or {}
        if isinstance(meta, dict):
            return meta.get("execution_target") or None
    except Exception:
        pass
    return None
