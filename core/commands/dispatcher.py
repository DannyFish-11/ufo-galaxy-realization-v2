"""
core/commands/dispatcher.py — Command Dispatcher
=================================================

**Batch PR-5: Command routing decomposition**

This module provides the ``CommandDispatcher`` class, which handles the
low-level mechanics of dispatching a command to one or more targets:

* Building ``TaskEnvelope`` instances from a ``CommandRequest``.
* Iterating over targets in parallel or serial mode.
* Aggregating per-target results into a ``CommandResult``.

The dispatcher deliberately delegates all *orchestration* decisions (which
targets to use, whether HITL approval is needed, circuit-breaking) to
``CommandRouter``.  It only handles the *how* of delivering a command to
an already-selected set of targets.

Authority sentinel
------------------
``COMMAND_DISPATCHER_AUTHORITY = "core.commands.dispatcher"``

Design
------
``CommandDispatcher`` wraps a ``CommandRouter`` instance and provides a
simplified dispatch surface.  For full orchestration, callers should use
``CommandRouter.dispatch()`` directly.  ``CommandDispatcher`` is intended
for scenarios where the caller has already performed routing decisions and
simply needs to send a command to a concrete list of targets.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Coroutine, Dict, List, Optional

from core.command_router import (
    CommandMode,
    CommandRequest,
    CommandResult,
    CommandStatus,
    CommandRouter,
    TargetResult,
    get_command_router,
)

logger = logging.getLogger("Galaxy.Commands.Dispatcher")

# ── module authority sentinel ─────────────────────────────────────────────
COMMAND_DISPATCHER_AUTHORITY: str = "core.commands.dispatcher"
"""Sentinel: core.commands.dispatcher is the canonical command dispatch helper.

Import this symbol to assert that a call site is using the decomposed
dispatcher module.
"""


class CommandDispatcher:
    """Thin dispatch helper that wraps a ``CommandRouter``.

    Parameters
    ----------
    router:
        The underlying ``CommandRouter`` to dispatch through.  If not
        provided, the module-level default router is used.
    """

    def __init__(self, router: Optional[CommandRouter] = None) -> None:
        self._router: Optional[CommandRouter] = router
        self._dispatch_count: int = 0
        self._error_count: int = 0

    @property
    def router(self) -> CommandRouter:
        if self._router is None:
            self._router = get_command_router()
        return self._router

    # ------------------------------------------------------------------
    # Public dispatch surface
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        command: str,
        targets: List[str],
        params: Optional[Dict[str, Any]] = None,
        *,
        mode: CommandMode = CommandMode.SYNC,
        timeout: float = 30.0,
        max_retries: int = 2,
        priority: int = 5,
        source: str = "dispatcher",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CommandResult:
        """Dispatch *command* to all *targets* and return the aggregated result.

        This is a convenience wrapper over ``CommandRouter.dispatch()`` that
        builds the ``CommandRequest`` for the caller.

        Parameters
        ----------
        command:
            The command name (e.g. ``"screenshot"``, ``"click"``).
        targets:
            List of device / node identifiers to dispatch to.
        params:
            Command parameters dict (forwarded verbatim to the executor).
        mode:
            Dispatch mode (SYNC / ASYNC / PARALLEL / SERIAL).
        timeout:
            Per-target timeout in seconds.
        max_retries:
            Maximum number of retry attempts per target.
        priority:
            Priority 1–10 (1 = highest).
        source:
            Caller identification string stamped on the request.
        metadata:
            Arbitrary metadata forwarded through the request lifecycle.
        """
        request = CommandRequest(
            request_id=f"disp_{uuid.uuid4().hex[:12]}",
            source=source,
            targets=list(targets),
            command=command,
            params=dict(params or {}),
            mode=mode,
            timeout=timeout,
            max_retries=max_retries,
            priority=priority,
            metadata=dict(metadata or {}),
        )
        self._dispatch_count += 1
        try:
            result = await self.router.dispatch(request)
            return result
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            self._error_count += 1
            logger.error(
                "CommandDispatcher.dispatch error | command=%s targets=%s error=%s",
                command,
                targets,
                exc,
            )
            raise

    async def dispatch_single(
        self,
        command: str,
        target: str,
        params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> "TargetResult":
        """Convenience method to dispatch to exactly one *target*.

        Returns the ``TargetResult`` for that target rather than the full
        ``CommandResult``.
        """
        result = await self.dispatch(command, [target], params, **kwargs)
        return result.targets.get(target, TargetResult(target=target, status=CommandStatus.FAILED))

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, int]:
        """Return basic dispatch statistics."""
        return {
            "dispatch_count": self._dispatch_count,
            "error_count": self._error_count,
        }

    def set_router(self, router: CommandRouter) -> None:
        """Replace the underlying router (useful for testing)."""
        self._router = router


# ── module-level default dispatcher ──────────────────────────────────────
_DEFAULT_DISPATCHER: Optional[CommandDispatcher] = None


def get_command_dispatcher() -> CommandDispatcher:
    """Return the module-level default ``CommandDispatcher`` singleton."""
    global _DEFAULT_DISPATCHER
    if _DEFAULT_DISPATCHER is None:
        _DEFAULT_DISPATCHER = CommandDispatcher()
    return _DEFAULT_DISPATCHER


__all__ = [
    "COMMAND_DISPATCHER_AUTHORITY",
    "CommandDispatcher",
    "get_command_dispatcher",
]
