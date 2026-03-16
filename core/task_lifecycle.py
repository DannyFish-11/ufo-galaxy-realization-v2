#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/task_lifecycle.py
======================
PR-5 Capability 1 — Task Lifecycle Manager

Manages mandatory task.lifecycle state transitions:
  created → running → done | failed

Responsibilities:
  1. Emit M2 ``task.lifecycle`` events on every transition.
  2. Write task summaries to TaskMemory on terminal states (done/failed).
  3. Provide a helper ``run_with_lifecycle()`` decorator that wraps any
     coroutine and handles state bookkeeping automatically.

Usage::

    from core.task_lifecycle import TaskLifecycleManager

    mgr = TaskLifecycleManager()
    envelope = TaskEnvelope(tool_name="list_files", args={"path": "/tmp"})

    envelope = mgr.mark_running(envelope)
    try:
        result = await execute(envelope)
        envelope = mgr.mark_done(envelope, result_summary=str(result))
    except Exception as exc:
        envelope = mgr.mark_failed(envelope, error=str(exc))
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Coroutine, Dict, Optional, Tuple

logger = logging.getLogger("Galaxy.TaskLifecycle")

# ---------------------------------------------------------------------------
# Optional integrations (fail-soft on import errors)
# ---------------------------------------------------------------------------

try:
    from core.task_memory import get_task_memory as _get_task_memory
    _MEMORY_OK = True
except ImportError:
    _MEMORY_OK = False

    def _get_task_memory() -> None:  # type: ignore[return-type]
        return None


def _emit_lifecycle_event(envelope: Any, status: str) -> None:
    """Best-effort M2 task.lifecycle event emission."""
    try:
        from integration.event_bus import event_bus, EventType
        et = getattr(EventType, "TASK_LIFECYCLE", None)
        if et is None:
            return
        event_bus.publish_sync(et, "task_lifecycle_manager", {
            "task_id": envelope.task_id,
            "trace_id": envelope.trace_id,
            "session_id": envelope.session_id,
            "tool_name": envelope.tool_name,
            "status": status,
            "ts": time.time(),
        })
    except Exception:
        pass


# ---------------------------------------------------------------------------
# TaskLifecycleManager
# ---------------------------------------------------------------------------

class TaskLifecycleManager:
    """Manages task.lifecycle state transitions for TaskEnvelope objects.

    Thread-safe: each method returns a *new* TaskEnvelope copy with the
    updated ``lifecycle_status``; the original is never mutated.
    """

    def mark_running(self, envelope: Any) -> Any:
        """Transition envelope from 'created' → 'running'.

        Emits M2 ``task.lifecycle`` event.
        """
        updated = envelope.transition("running")
        logger.info(
            "task.lifecycle | task_id=%s trace_id=%s status=running tool=%s",
            updated.task_id, updated.trace_id, updated.tool_name,
        )
        _emit_lifecycle_event(updated, "running")
        return updated

    def mark_done(
        self,
        envelope: Any,
        result_summary: str = "",
        result_data: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Transition envelope from 'running' → 'done'.

        Emits M2 ``task.lifecycle`` event and writes a summary to TaskMemory.
        """
        updated = envelope.transition("done")
        logger.info(
            "task.lifecycle | task_id=%s trace_id=%s status=done tool=%s summary=%r",
            updated.task_id, updated.trace_id, updated.tool_name,
            result_summary[:120] if result_summary else "",
        )
        _emit_lifecycle_event(updated, "done")
        self._write_memory(updated, result_summary=result_summary, success=True)
        return updated

    def mark_failed(
        self,
        envelope: Any,
        error: str = "",
    ) -> Any:
        """Transition envelope from 'running' → 'failed'.

        Emits M2 ``task.lifecycle`` event and writes a failure summary to
        TaskMemory.
        """
        updated = envelope.transition("failed")
        logger.warning(
            "task.lifecycle | task_id=%s trace_id=%s status=failed tool=%s error=%r",
            updated.task_id, updated.trace_id, updated.tool_name,
            error[:200] if error else "",
        )
        _emit_lifecycle_event(updated, "failed")
        self._write_memory(updated, result_summary=f"FAILED: {error}", success=False)
        return updated

    # ── Memory backflow (Capability 3) ──────────────────────────────────────

    def _write_memory(
        self,
        envelope: Any,
        result_summary: str,
        success: bool,
    ) -> None:
        """Write task result to TaskMemory (memory backflow).

        Logs an assertion-level message so tests can verify the write.
        """
        if not _MEMORY_OK or _get_task_memory is None:
            return
        try:
            mem = _get_task_memory()
            mem.record_task(
                task=envelope.tool_name or envelope.task_id,
                result_summary=result_summary,
                success=success,
                strategy=envelope.metadata.get("mode", "default"),
                task_type=envelope.tool_name,
            )
            logger.info(
                "task.memory_backflow | task_id=%s session_id=%s memory_written=True summary=%r",
                envelope.task_id,
                envelope.session_id or "",
                result_summary[:80],
            )
        except Exception as exc:
            logger.warning("task.memory_backflow failed: %s", exc)

    # ── Convenience wrapper ──────────────────────────────────────────────────

    async def run_with_lifecycle(
        self,
        envelope: Any,
        coro_factory: Callable[[Any], Coroutine[Any, Any, Tuple[Any, str]]],
    ) -> Tuple[Any, Any]:
        """Execute ``coro_factory(envelope)`` with automatic lifecycle bookkeeping.

        The coroutine must return ``(result, summary_str)``.

        Returns ``(final_envelope, result)`` where ``final_envelope`` has
        lifecycle_status 'done' or 'failed'.
        """
        envelope = self.mark_running(envelope)
        try:
            result, summary = await coro_factory(envelope)
            envelope = self.mark_done(envelope, result_summary=summary)
            return envelope, result
        except Exception as exc:
            envelope = self.mark_failed(envelope, error=str(exc))
            raise


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_lifecycle_manager: Optional[TaskLifecycleManager] = None


def get_lifecycle_manager() -> TaskLifecycleManager:
    """Return (or lazily create) the module-level TaskLifecycleManager."""
    global _lifecycle_manager
    if _lifecycle_manager is None:
        _lifecycle_manager = TaskLifecycleManager()
    return _lifecycle_manager
