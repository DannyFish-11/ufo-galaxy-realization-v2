"""
Parallel Group Tracker — gateway-level shared state machine.

Tracks parallel subtask results arriving via WebSocket across **both** entry
chains (A: websocket_handler → device_router, B: handlers/message_handler →
task_orchestrator).  All in-memory; no persistence required.

Usage::

    from galaxy_gateway.orchestrator.parallel_tracker import get_tracker

    tracker = get_tracker()
    await tracker.start_group("grp-1", expected_count=3, timeout_s=30.0)
    await tracker.record_result("grp-1", subtask_index=0, status="success", latency_ms=120)
    status = await tracker.finalize_if_complete("grp-1")   # → ParallelGroupStatus or None
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data-transfer objects
# ---------------------------------------------------------------------------

@dataclass
class ParallelSubtaskResult:
    """Result record for one subtask within a parallel group."""

    group_id: str
    subtask_index: int
    status: str                         # success / failed / timeout
    latency_ms: int
    summary: Optional[str] = None
    errors: Optional[List[str]] = None
    outputs: Optional[Any] = None


@dataclass
class ParallelGroupStatus:
    """Finalized status of a complete (or timed-out) parallel group."""

    group_id: str
    status: str                          # success / partial_failed / timeout
    results: List[ParallelSubtaskResult]
    started_at: float
    finished_at: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "results": [
                {
                    "group_id": r.group_id,
                    "subtask_index": r.subtask_index,
                    "status": r.status,
                    "latency_ms": r.latency_ms,
                    "summary": r.summary,
                    "errors": r.errors,
                    "outputs": r.outputs,
                }
                for r in self.results
            ],
        }


# ---------------------------------------------------------------------------
# Internal group state
# ---------------------------------------------------------------------------

@dataclass
class _GroupState:
    group_id: str
    expected_count: Optional[int]   # None → open-ended (auto-created groups)
    timeout_s: float
    started_at: float
    results: Dict[int, ParallelSubtaskResult] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

class ParallelGroupTracker:
    """Shared in-memory tracker for parallel subtask groups.

    Thread-safe for asyncio (single-threaded event loop) via an asyncio.Lock
    created lazily on first use.
    """

    def __init__(self) -> None:
        self._lock: Optional[asyncio.Lock] = None
        self._groups: Dict[str, _GroupState] = {}
        self._finalized: Dict[str, ParallelGroupStatus] = {}

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # ------------------------------------------------------------------
    # Public API (async)
    # ------------------------------------------------------------------

    async def start_group(
        self,
        group_id: str,
        expected_count: int,
        timeout_s: float,
    ) -> None:
        """Register a new parallel group before dispatching subtasks."""
        async with self._get_lock():
            if group_id in self._groups or group_id in self._finalized:
                logger.debug(
                    "parallel_tracker: group=%s already registered — skip start",
                    group_id,
                )
                return
            self._groups[group_id] = _GroupState(
                group_id=group_id,
                expected_count=expected_count,
                timeout_s=timeout_s,
                started_at=time.time(),
            )
            logger.info(
                "parallel_tracker: started group=%s expected=%d timeout=%.1fs",
                group_id, expected_count, timeout_s,
            )

    async def record_result(
        self,
        group_id: str,
        subtask_index: int,
        status: str,
        latency_ms: int,
        summary: Optional[str] = None,
        errors: Optional[List[str]] = None,
        outputs: Optional[Any] = None,
    ) -> None:
        """Record one subtask result.  Auto-creates group when not pre-registered."""
        async with self._get_lock():
            if group_id not in self._groups:
                if group_id in self._finalized:
                    logger.debug(
                        "parallel_tracker: group=%s already finalized — ignoring record",
                        group_id,
                    )
                    return
                # Auto-create with unknown expected count
                self._groups[group_id] = _GroupState(
                    group_id=group_id,
                    expected_count=None,
                    timeout_s=60.0,
                    started_at=time.time(),
                )
                logger.debug(
                    "parallel_tracker: auto-created group=%s on first record",
                    group_id,
                )

            result = ParallelSubtaskResult(
                group_id=group_id,
                subtask_index=subtask_index,
                status=status,
                latency_ms=latency_ms,
                summary=summary,
                errors=errors,
                outputs=outputs,
            )
            self._groups[group_id].results[subtask_index] = result
            logger.debug(
                "parallel_tracker: recorded group=%s idx=%d status=%s",
                group_id, subtask_index, status,
            )

    async def finalize_if_complete(
        self, group_id: str
    ) -> Optional[ParallelGroupStatus]:
        """Return finalized status when all expected subtasks are recorded, else None."""
        async with self._get_lock():
            state = self._groups.get(group_id)
            if state is None:
                return self._finalized.get(group_id)

            if state.expected_count is None:
                return None
            if len(state.results) < state.expected_count:
                return None

            status = self._finalize_locked(state)
            del self._groups[group_id]
            self._finalized[group_id] = status
            return status

    async def expire_timeouts(self, now_ts: float) -> Dict[str, ParallelGroupStatus]:
        """Mark missing subtasks as *timeout* and finalize all overdue groups.

        Returns a mapping of ``group_id → ParallelGroupStatus`` for every
        group that was expired during this call.
        """
        expired: Dict[str, ParallelGroupStatus] = {}
        async with self._get_lock():
            overdue = [
                gid for gid, state in self._groups.items()
                if now_ts - state.started_at >= state.timeout_s
            ]
            for gid in overdue:
                state = self._groups[gid]
                expected = state.expected_count or max(
                    (max(state.results.keys()) + 1 if state.results else 0), 0
                )
                for idx in range(expected):
                    if idx not in state.results:
                        state.results[idx] = ParallelSubtaskResult(
                            group_id=gid,
                            subtask_index=idx,
                            status="timeout",
                            latency_ms=int((now_ts - state.started_at) * 1000),
                        )
                        logger.warning(
                            "parallel_tracker: timeout on group=%s idx=%d",
                            gid, idx,
                        )

                status = self._finalize_locked(state)
                del self._groups[gid]
                self._finalized[gid] = status
                expired[gid] = status
                logger.info(
                    "parallel_tracker: group=%s expired with status=%s",
                    gid, status.status,
                )
        return expired

    # ------------------------------------------------------------------
    # Public API (sync — safe for reading after coroutines settle)
    # ------------------------------------------------------------------

    def get_group_status(self, group_id: str) -> Optional[ParallelGroupStatus]:
        """Return finalized status if available, else current in-progress snapshot."""
        if group_id in self._finalized:
            return self._finalized[group_id]
        state = self._groups.get(group_id)
        if state is None:
            return None
        if state.expected_count is not None and len(state.results) >= state.expected_count:
            return self._finalize_locked(state)
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _finalize_locked(state: _GroupState) -> ParallelGroupStatus:
        results = list(state.results.values())
        statuses = {r.status for r in results}
        if all(r.status == "success" for r in results):
            group_status = "success"
        elif "timeout" in statuses:
            group_status = "timeout"
        else:
            group_status = "partial_failed"

        return ParallelGroupStatus(
            group_id=state.group_id,
            status=group_status,
            results=results,
            started_at=state.started_at,
            finished_at=time.time(),
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_tracker_instance: Optional[ParallelGroupTracker] = None


def get_tracker() -> ParallelGroupTracker:
    """Return the module-level singleton tracker."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = ParallelGroupTracker()
    return _tracker_instance


async def record_parallel_fields(payload: Dict[str, Any]) -> None:
    """Extract parallel fields from a message payload and record into the shared tracker.

    No-op when *group_id* is absent.  Safe to call from any entry point.

    Args:
        payload: A flat ``dict`` that may contain:
            ``group_id``, ``subtask_index``, ``status``, ``latency_ms``,
            ``summary``, ``errors``, ``outputs``.
    """
    group_id = payload.get("group_id")
    if not group_id:
        return
    try:
        subtask_index = int(payload.get("subtask_index") or 0)
        status = str(payload.get("status") or "success")
        latency_ms = int(payload.get("latency_ms") or 0)
        summary = payload.get("summary")
        errors_raw = payload.get("errors")
        errors = list(errors_raw) if errors_raw else None
        outputs = payload.get("outputs")
        await get_tracker().record_result(
            group_id=str(group_id),
            subtask_index=subtask_index,
            status=status,
            latency_ms=latency_ms,
            summary=summary,
            errors=errors,
            outputs=outputs,
        )
        logger.debug(
            "parallel_tracker: recorded group=%s idx=%d status=%s",
            group_id, subtask_index, status,
        )
    except Exception as _err:
        logger.warning("parallel_tracker: record_parallel_fields failed: %s", _err)
