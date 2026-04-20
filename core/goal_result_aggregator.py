"""
core/goal_result_aggregator.py
================================
PR-D: Server-side canonical result aggregator for GOAL_EXECUTION_RESULT.

Provides thread-safe tracking and aggregation of parallel / grouped subtask
results so that the server can form a single unified "group complete" event
when all subtasks belonging to the same ``group_id`` have delivered a result.

Design principles
-----------------
- **Single canonical store** — all goal results for a group flow through this
  module; it is the authoritative in-memory completion state for grouped tasks.
- **Idempotent** — recording the same ``(group_id, task_id)`` pair a second
  time is a no-op (first write wins).
- **Non-destructive on unknown group** — if a result arrives for a group that
  was never registered via :func:`register_group`, the record is created on
  the fly with ``expected_count=None``; aggregation is still tracked but no
  group-complete event is emitted (because we don't know the expected total).
- **Thread-safe** — the internal registry is protected by a :class:`threading.Lock`.
  All public functions are safe to call from multiple asyncio tasks.

Public API
----------
::

    register_group(group_id, expected_count, *, session_id="", trace_id="")
    record_subtask_result(group_id, task_id, status, result_text, device_id,
                          subtask_index=None) -> GroupResultState
    get_group_state(group_id) -> Optional[GroupResultState]
    get_goal_result_aggregator() -> GoalResultAggregator

Dataclasses
-----------
    SubtaskResultEntry
    GroupResultState
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.GoalResultAggregator")

# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------

_SUCCESS_STATUSES = frozenset({"completed", "success", "done", "true"})
_FAILED_STATUSES = frozenset({"failed", "failure", "error", "false"})
_CANCELLED_STATUSES = frozenset({"cancelled", "canceled"})


def _is_terminal_status(status: str) -> bool:
    s = (status or "").lower().strip()
    return s in _SUCCESS_STATUSES or s in _FAILED_STATUSES or s in _CANCELLED_STATUSES


def _is_success_status(status: str) -> bool:
    return (status or "").lower().strip() in _SUCCESS_STATUSES


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SubtaskResultEntry:
    """Result record for a single subtask within a group."""

    task_id: str
    device_id: str
    status: str
    result_text: str
    subtask_index: Optional[int]
    received_at: float = field(default_factory=time.time)
    success: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "device_id": self.device_id,
            "status": self.status,
            "result_text": self.result_text,
            "subtask_index": self.subtask_index,
            "received_at": self.received_at,
            "success": self.success,
        }


@dataclass
class GroupResultState:
    """Aggregated state of a parallel/grouped task group.

    Attributes
    ----------
    group_id:
        Stable group identifier shared by all subtasks in the parallel batch.
    expected_count:
        Total number of subtasks expected for this group.  ``None`` if not
        registered in advance (arrived out-of-order).
    results:
        Dict mapping ``task_id`` → :class:`SubtaskResultEntry` for every
        subtask whose result has been recorded so far.
    session_id:
        Optional session identifier propagated from the dispatch context.
    trace_id:
        Optional trace identifier for observability correlation.
    created_at:
        Unix timestamp when this group state was first created.
    completed_at:
        Unix timestamp when the group reached a terminal (all-done) state.
        ``None`` if the group is not yet complete.
    all_done:
        ``True`` when all expected subtasks have delivered a result.
    summary:
        Optional summary dict produced at group-completion time.
    """

    group_id: str
    expected_count: Optional[int]
    results: Dict[str, SubtaskResultEntry] = field(default_factory=dict)
    session_id: str = ""
    trace_id: str = ""
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    all_done: bool = False
    summary: Optional[Dict[str, Any]] = None

    @property
    def completed_count(self) -> int:
        return len(self.results)

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results.values() if r.success)

    @property
    def failure_count(self) -> int:
        return sum(1 for r in self.results.values() if not r.success)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "expected_count": self.expected_count,
            "completed_count": self.completed_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "all_done": self.all_done,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "results": {tid: r.to_dict() for tid, r in self.results.items()},
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# GoalResultAggregator — the canonical in-memory group result store
# ---------------------------------------------------------------------------


class GoalResultAggregator:
    """Thread-safe server-side aggregator for GOAL_EXECUTION_RESULT messages.

    Usage
    -----
    At dispatch time (in ``handle_parallel_subtask``)::

        aggregator = get_goal_result_aggregator()
        aggregator.register_group(
            group_id=group_id,
            expected_count=len(target_device_ids),
            session_id=session_id,
            trace_id=trace_id,
        )

    When a result arrives (in ``handle_goal_execution_result``)::

        aggregator = get_goal_result_aggregator()
        state = aggregator.record_subtask_result(
            group_id=group_id,
            task_id=task_id,
            status=status,
            result_text=result_text,
            device_id=device_id,
            subtask_index=subtask_index,
        )
        if state is not None and state.all_done:
            # All subtasks complete — fire group-level completion logic
            ...
    """

    # Max number of groups retained in memory at once.
    # Groups are evicted in insertion order (oldest first) when this limit is
    # reached.  512 covers typical multi-device session concurrency while
    # keeping memory usage bounded (each entry is O(subtask_count) dicts).
    _MAX_GROUPS: int = 512

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # group_id → GroupResultState
        self._groups: Dict[str, GroupResultState] = {}
        # Ordered insertion list for eviction (oldest first)
        self._insertion_order: List[str] = []

    # ── Registration ─────────────────────────────────────────────────────

    def register_group(
        self,
        group_id: str,
        expected_count: int,
        *,
        session_id: str = "",
        trace_id: str = "",
    ) -> GroupResultState:
        """Register a new group before results begin to arrive.

        Subsequent calls with the same ``group_id`` are idempotent — the
        existing state is returned unchanged (no overwrite).

        Parameters
        ----------
        group_id:
            Stable group identifier for the parallel batch.
        expected_count:
            Total number of subtasks expected.  Must be ≥ 1.
        session_id:
            Optional session context propagated from the dispatch caller.
        trace_id:
            Optional trace identifier for observability correlation.
        """
        with self._lock:
            if group_id in self._groups:
                return self._groups[group_id]
            state = GroupResultState(
                group_id=group_id,
                expected_count=expected_count,
                session_id=session_id,
                trace_id=trace_id,
            )
            self._groups[group_id] = state
            self._insertion_order.append(group_id)
            self._evict_if_needed()
            logger.debug(
                "GoalResultAggregator.register_group | group_id=%s expected=%d",
                group_id,
                expected_count,
            )
            return state

    # ── Result recording ─────────────────────────────────────────────────

    def record_subtask_result(
        self,
        group_id: str,
        task_id: str,
        status: str,
        result_text: str,
        device_id: str,
        subtask_index: Optional[int] = None,
    ) -> Optional[GroupResultState]:
        """Record a subtask result and return the updated group state.

        Parameters
        ----------
        group_id:
            The group this subtask belongs to.  If the group was never
            registered, a new state entry is created with
            ``expected_count=None``.
        task_id:
            Unique identifier for this subtask's result.
        status:
            Status string from the Android result payload.
        result_text:
            Human-readable result or summary text.
        device_id:
            ID of the device that produced this result.
        subtask_index:
            Zero-based index within the parallel batch (optional).

        Returns
        -------
        GroupResultState | None
            The updated group state, or ``None`` if ``group_id`` is empty
            (non-grouped result — caller should skip aggregation).
        """
        if not group_id:
            return None

        with self._lock:
            if group_id not in self._groups:
                # Result arrived before register_group() — create on the fly.
                state = GroupResultState(
                    group_id=group_id,
                    expected_count=None,  # unknown
                )
                self._groups[group_id] = state
                self._insertion_order.append(group_id)
                self._evict_if_needed()
                logger.debug(
                    "GoalResultAggregator: on-the-fly group creation for "
                    "group_id=%s (no prior register_group call)",
                    group_id,
                )
            else:
                state = self._groups[group_id]

            # Idempotent: first write wins for a given task_id
            if task_id in state.results:
                logger.debug(
                    "GoalResultAggregator: duplicate result ignored | "
                    "group_id=%s task_id=%s",
                    group_id,
                    task_id,
                )
                return state

            entry = SubtaskResultEntry(
                task_id=task_id,
                device_id=device_id,
                status=status,
                result_text=result_text,
                subtask_index=subtask_index,
                success=_is_success_status(status),
            )
            state.results[task_id] = entry

            # Check if the group is now complete
            if (
                state.expected_count is not None
                and state.completed_count >= state.expected_count
                and not state.all_done
            ):
                state.all_done = True
                state.completed_at = time.time()
                state.summary = self._build_summary(state)
                logger.info(
                    "GoalResultAggregator: group COMPLETE | group_id=%s "
                    "expected=%d completed=%d success=%d failure=%d",
                    group_id,
                    state.expected_count,
                    state.completed_count,
                    state.success_count,
                    state.failure_count,
                )
            else:
                logger.debug(
                    "GoalResultAggregator: subtask recorded | group_id=%s "
                    "task_id=%s completed=%d/%s",
                    group_id,
                    task_id,
                    state.completed_count,
                    state.expected_count if state.expected_count is not None else "?",
                )

            return state

    # ── Query ────────────────────────────────────────────────────────────

    def get_group_state(self, group_id: str) -> Optional[GroupResultState]:
        """Return the current state for *group_id*, or ``None`` if not found."""
        with self._lock:
            return self._groups.get(group_id)

    # ── Internal helpers ─────────────────────────────────────────────────

    @staticmethod
    def _build_summary(state: GroupResultState) -> Dict[str, Any]:
        """Build a human-readable summary dict for a completed group."""
        overall_success = state.failure_count == 0
        return {
            "group_id": state.group_id,
            "overall_success": overall_success,
            "expected_count": state.expected_count,
            "completed_count": state.completed_count,
            "success_count": state.success_count,
            "failure_count": state.failure_count,
            "session_id": state.session_id,
            "trace_id": state.trace_id,
            "completed_at": state.completed_at,
            "subtask_statuses": [
                {"task_id": r.task_id, "device_id": r.device_id, "success": r.success}
                for r in state.results.values()
            ],
        }

    def _evict_if_needed(self) -> None:
        """Evict the oldest group entries when the registry exceeds capacity."""
        while len(self._groups) > self._MAX_GROUPS and self._insertion_order:
            oldest = self._insertion_order.pop(0)
            self._groups.pop(oldest, None)
            logger.debug(
                "GoalResultAggregator: evicted oldest group_id=%s", oldest
            )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_aggregator_instance: Optional[GoalResultAggregator] = None
_aggregator_lock = threading.Lock()


def get_goal_result_aggregator() -> GoalResultAggregator:
    """Return the process-global :class:`GoalResultAggregator` singleton."""
    global _aggregator_instance
    if _aggregator_instance is None:
        with _aggregator_lock:
            if _aggregator_instance is None:
                _aggregator_instance = GoalResultAggregator()
    return _aggregator_instance


def reset_goal_result_aggregator() -> None:
    """Reset the singleton (for testing only)."""
    global _aggregator_instance
    _aggregator_instance = None
