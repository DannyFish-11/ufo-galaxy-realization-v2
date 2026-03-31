"""core/orchestration/lifecycle.py — Lifecycle helpers for Galaxy orchestration.

PR-7: Extracted from core/openclawd.py.  Contains the local-device detection
helpers and the parallel-group state machine that tracks concurrent subtask
execution across multiple devices.

External consumers should import from this module directly (or via
``core.orchestration``) rather than from ``core.openclawd``.
"""

from __future__ import annotations

import dataclasses
import enum
import logging
import socket
import time
from typing import Dict, List, Optional

logger = logging.getLogger("Galaxy.Orchestration.Lifecycle")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

LIFECYCLE_MANAGER_AUTHORITY = "LIFECYCLE_MANAGER_AUTHORITY"

# ---------------------------------------------------------------------------
# Helper: local-device detection (originally PR155)
# ---------------------------------------------------------------------------

_LOCAL_DEVICE_PREFIXES = ("local", "openclawd", "server")
_LOCAL_HOSTNAME = socket.gethostname().lower()


def _is_local_device(device_id: str) -> bool:
    """Return True when *device_id* refers to the local host / process.

    A device is considered local when its ID:
      - starts with a known local prefix (``local``, ``openclawd``, ``server``), or
      - contains the current hostname, or
      - is empty / None.
    """
    if not device_id:
        return True
    dl = device_id.lower()
    if any(dl.startswith(p) for p in _LOCAL_DEVICE_PREFIXES):
        return True
    if _LOCAL_HOSTNAME and _LOCAL_HOSTNAME in dl:
        return True
    return False


# ---------------------------------------------------------------------------
# Parallel-group state machine
# ---------------------------------------------------------------------------

class _SubtaskStatus(str, enum.Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCESS   = "success"
    FAILED    = "failed"
    TIMEOUT   = "timeout"
    CANCELLED = "cancelled"


@dataclasses.dataclass
class _SubtaskEntry:
    task_id:       str
    group_id:      str
    subtask_index: int
    device_id:     str
    subtask:       str
    status:        _SubtaskStatus = _SubtaskStatus.PENDING
    started_at:    Optional[float] = None
    finished_at:   Optional[float] = None
    result:        Optional[Dict] = None
    error:         Optional[str] = None
    retry_count:   int = 0


@dataclasses.dataclass
class ParallelResult:
    """Aggregated result for a parallel_group execution."""
    group_id:       str
    device_results: List[Dict]
    summary_status: str          # "success" | "partial" | "failed" | "cancelled"
    succeeded:      int
    failed:         int
    cancelled:      int
    total:          int

    def to_dict(self) -> Dict:
        return dataclasses.asdict(self)


class ParallelGroupTracker:
    """
    State machine for tracking parallel subtask groups.

    Lifecycle per group:
      register_group() → mark_running() → mark_done() (or mark_timeout()) → aggregate()

    Retry policy: 1 retry per subtask, exponential backoff starting at 2 s, capped at 30 s.
    """

    _MAX_RETRIES: int = 1
    _BACKOFF_BASE: float = 2.0
    _BACKOFF_CAP: float = 30.0

    def __init__(self) -> None:
        # group_id → {task_id → _SubtaskEntry}
        self._groups: Dict[str, Dict[str, _SubtaskEntry]] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_group(
        self,
        group_id: str,
        entries: List[_SubtaskEntry],
    ) -> None:
        self._groups[group_id] = {e.task_id: e for e in entries}
        logger.debug(
            "ParallelGroupTracker: registered group=%s subtasks=%d",
            group_id, len(entries),
        )

    def mark_running(self, group_id: str, task_id: str) -> None:
        entry = self._get_entry(group_id, task_id)
        if entry:
            entry.status = _SubtaskStatus.RUNNING
            entry.started_at = time.monotonic()

    def mark_done(
        self,
        group_id: str,
        task_id: str,
        result: Dict,
        *,
        success: bool,
    ) -> None:
        entry = self._get_entry(group_id, task_id)
        if entry:
            entry.status = _SubtaskStatus.SUCCESS if success else _SubtaskStatus.FAILED
            entry.finished_at = time.monotonic()
            entry.result = result
            if not success:
                entry.error = result.get("response") or result.get("error") or "unknown error"

    def mark_timeout(self, group_id: str, task_id: str) -> None:
        entry = self._get_entry(group_id, task_id)
        if entry:
            entry.status = _SubtaskStatus.TIMEOUT
            entry.finished_at = time.monotonic()
            entry.error = "timeout"

    def mark_cancelled(self, group_id: str, task_id: str) -> None:
        """Mark a subtask as cancelled (idempotent — safe to call multiple times)."""
        entry = self._get_entry(group_id, task_id)
        if entry and entry.status != _SubtaskStatus.CANCELLED:
            entry.status = _SubtaskStatus.CANCELLED
            entry.finished_at = time.monotonic()
            entry.error = "cancelled"

    # ------------------------------------------------------------------
    # Retry helpers
    # ------------------------------------------------------------------

    def needs_retry(self, group_id: str, task_id: str) -> bool:
        entry = self._get_entry(group_id, task_id)
        if entry is None:
            return False
        return (
            entry.status in (_SubtaskStatus.FAILED, _SubtaskStatus.TIMEOUT)
            and entry.retry_count < self._MAX_RETRIES
        )

    def backoff_delay(self, group_id: str, task_id: str) -> float:
        entry = self._get_entry(group_id, task_id)
        if entry is None:
            return 0.0
        delay = self._BACKOFF_BASE ** (entry.retry_count + 1)
        return min(delay, self._BACKOFF_CAP)

    def increment_retry(self, group_id: str, task_id: str) -> None:
        entry = self._get_entry(group_id, task_id)
        if entry:
            entry.retry_count += 1
            entry.status = _SubtaskStatus.PENDING
            entry.started_at = None
            entry.finished_at = None
            entry.result = None
            entry.error = None

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def aggregate(self, group_id: str) -> ParallelResult:
        entries = list(self._groups.get(group_id, {}).values())
        device_results: List[Dict] = []
        for e in entries:
            latency_ms: Optional[float] = None
            if e.started_at is not None and e.finished_at is not None:
                latency_ms = round((e.finished_at - e.started_at) * 1000, 1)
            device_results.append({
                "group_id":      group_id,
                "subtask_index": e.subtask_index,
                "device_id":     e.device_id,
                "task_id":       e.task_id,
                "status":        e.status.value,
                "result":        e.result,
                "error":         e.error,
                "latency_ms":    latency_ms,
            })

        succeeded  = sum(1 for e in entries if e.status == _SubtaskStatus.SUCCESS)
        cancelled  = sum(1 for e in entries if e.status == _SubtaskStatus.CANCELLED)
        # "failed" here includes both FAILED and TIMEOUT statuses (any non-success,
        # non-cancelled terminal state). Matches the ParallelResult.failed field semantics.
        failed     = len(entries) - succeeded - cancelled

        if succeeded == len(entries):
            summary = "success"
        elif succeeded > 0:
            summary = "partial"
        elif cancelled == len(entries):
            summary = "cancelled"
        else:
            summary = "failed"

        return ParallelResult(
            group_id=group_id,
            device_results=device_results,
            summary_status=summary,
            succeeded=succeeded,
            failed=failed,
            cancelled=cancelled,
            total=len(entries),
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_entry(self, group_id: str, task_id: str) -> Optional[_SubtaskEntry]:
        return self._groups.get(group_id, {}).get(task_id)


# ---------------------------------------------------------------------------
# LifecycleManager
# ---------------------------------------------------------------------------

class LifecycleManager:
    """Manages task/group cancellation registry and plan lifecycle transitions."""

    LIFECYCLE_MANAGER_AUTHORITY = LIFECYCLE_MANAGER_AUTHORITY

    def __init__(self) -> None:
        self._cancel_registry: set = set()

    def cancel_task(self, task_id: str) -> bool:
        """Register *task_id* for cancellation.  Returns True if newly added."""
        if task_id in self._cancel_registry:
            return False
        self._cancel_registry.add(task_id)
        logger.debug("LifecycleManager: cancelled task=%s", task_id)
        return True

    def cancel_group(self, group_id: str) -> bool:
        """Register *group_id* for cancellation.  Returns True if newly added."""
        if group_id in self._cancel_registry:
            return False
        self._cancel_registry.add(group_id)
        logger.debug("LifecycleManager: cancelled group=%s", group_id)
        return True

    def is_cancelled(self, task_id: str, group_id: Optional[str] = None) -> bool:
        """Return True if *task_id* or *group_id* is in the cancel registry."""
        if task_id in self._cancel_registry:
            return True
        if group_id and group_id in self._cancel_registry:
            return True
        return False

    @staticmethod
    def finalise_plan(plan: object, *, success: bool) -> None:
        """Thin delegation to _finalise_plan_lifecycle logic.

        Marks *plan* as completed or failed depending on *success*.  The plan
        object is expected to have a ``status`` attribute (string).
        """
        try:
            plan.status = "completed" if success else "failed"  # type: ignore[union-attr]
        except Exception:
            pass
