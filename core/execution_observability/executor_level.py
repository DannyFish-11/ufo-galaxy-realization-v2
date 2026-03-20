"""
core.execution_observability.executor_level
============================================

Defines :class:`ExecutorLevel` — a stable enum of the ordered execution tiers
used throughout the Galaxy runtime.

Alignment
---------
The values are deliberately aligned with the existing implementations:

* ``system_api``      — ``WinExecLevel.SYSTEM_API`` in
  ``core/windows_execution_arbiter.py``
* ``uia``             — ``WinExecLevel.UIA``
* ``gui``             — ``WinExecLevel.GUI``
* ``vlm``             — ``WinExecLevel.VLM``
* ``remote_executor`` — cross-device / NATS-dispatched execution
* ``orchestrator``    — top-level orchestration decisions (TaskGraph, arbiter)

The enum is a ``str`` mixin so instances round-trip cleanly through JSON /
YAML serialisation without a custom encoder.
"""

from __future__ import annotations

from enum import Enum


class ExecutorLevel(str, Enum):
    """Ordered execution tier used to answer "which layer handled this?".

    Lower tiers (``system_api``, ``uia``) are preferred for on-device
    Windows execution.  ``remote_executor`` covers cross-device dispatch.
    ``orchestrator`` marks decisions made at the task-graph / arbiter level
    before any concrete executor was reached.
    """

    SYSTEM_API = "system_api"
    """Win32 / OS-level calls via ``core.system_api``."""

    UIA = "uia"
    """UIAutomation COM accessibility-tree control."""

    GUI = "gui"
    """Coordinate-based GUI automation / input simulation."""

    VLM = "vlm"
    """Vision-Language Model screenshot-based fallback."""

    REMOTE_EXECUTOR = "remote_executor"
    """Cross-device dispatch via NATS / TaskGraph remote nodes."""

    ORCHESTRATOR = "orchestrator"
    """Decision made at the orchestration layer (no concrete executor used)."""

    UNKNOWN = "unknown"
    """Executor level could not be determined from available context."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_string(cls, value: str) -> "ExecutorLevel":
        """Return the matching enum member, falling back to ``UNKNOWN``.

        Case-insensitive; accepts values from ``WinExecLevel`` as well.

        >>> ExecutorLevel.from_string("system_api")
        <ExecutorLevel.SYSTEM_API: 'system_api'>
        >>> ExecutorLevel.from_string("bogus")
        <ExecutorLevel.UNKNOWN: 'unknown'>
        """
        normalised = (value or "").strip().lower()
        for member in cls:
            if member.value == normalised:
                return member
        return cls.UNKNOWN

    @classmethod
    def from_win_exec_level(cls, level: object) -> "ExecutorLevel":
        """Convert a ``WinExecLevel`` enum value (or its string repr).

        This avoids a hard import of ``core.windows_execution_arbiter`` so
        that this schema module remains import-light.
        """
        try:
            raw = level.value if hasattr(level, "value") else str(level)  # type: ignore[union-attr]
            return cls.from_string(raw)
        except Exception:
            return cls.UNKNOWN

    def is_local(self) -> bool:
        """Return True for tiers that execute on the local device."""
        return self in (
            self.SYSTEM_API,
            self.UIA,
            self.GUI,
            self.VLM,
        )

    def is_remote(self) -> bool:
        """Return True for tiers that dispatch to a remote device."""
        return self is self.REMOTE_EXECUTOR
