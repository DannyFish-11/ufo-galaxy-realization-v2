"""
core.execution_observability.fallback_schema
=============================================

Defines :class:`FallbackReason` (structured enum) and :class:`FallbackContext`
(dataclass) for unified fallback observability.

These types cover the fallback cases already implied by the existing code base:

* ``no_system_api_match``    — ``WinExecLevel.SYSTEM_API`` returned no match.
* ``uia_unavailable``        — UIAutomation COM layer not accessible.
* ``visual_anchor_required`` — action requires a visual coordinate; structural
  path skipped.
* ``cross_device_required``  — task must be executed on a remote node.
* ``local_capability_missing`` — required local capability (mic, camera, etc.)
  not available.
* ``model_confidence_low``   — VLM / planner confidence below threshold.
* ``safety_hold``            — safety / HITL policy vetoed execution.
* ``timeout``                — executor timed out.
* ``partial_failure``        — some subtasks of a DAG failed.
* ``unknown``                — reason could not be determined.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from .executor_level import ExecutorLevel


class FallbackReason(str, Enum):
    """Structured reason code explaining why a fallback occurred.

    Values align with the fallback patterns observed in
    ``core/windows_execution_arbiter.py``, ``core/e2e_orchestrator.py``, and
    the task-graph / device dispatch layers.
    """

    NO_SYSTEM_API_MATCH = "no_system_api_match"
    """System API level had no handler for the requested action."""

    UIA_UNAVAILABLE = "uia_unavailable"
    """UIAutomation COM layer is not accessible or returned an error."""

    VISUAL_ANCHOR_REQUIRED = "visual_anchor_required"
    """Action requires a visual / coordinate anchor; structural path skipped."""

    CROSS_DEVICE_REQUIRED = "cross_device_required"
    """Task must be routed to a remote device / node."""

    LOCAL_CAPABILITY_MISSING = "local_capability_missing"
    """Required local capability (sensor, peripheral, etc.) is not present."""

    MODEL_CONFIDENCE_LOW = "model_confidence_low"
    """Model confidence is below the configured threshold."""

    SAFETY_HOLD = "safety_hold"
    """Safety policy or HITL gate vetoed execution."""

    TIMEOUT = "timeout"
    """Executor timed out before completing the action."""

    PARTIAL_FAILURE = "partial_failure"
    """One or more subtasks in a DAG/plan failed while others succeeded."""

    UNKNOWN = "unknown"
    """Fallback reason could not be determined from available context."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_string(cls, value: str) -> "FallbackReason":
        """Return the matching enum member, falling back to ``UNKNOWN``.

        Case-insensitive.

        >>> FallbackReason.from_string("timeout")
        <FallbackReason.TIMEOUT: 'timeout'>
        >>> FallbackReason.from_string("bad_value")
        <FallbackReason.UNKNOWN: 'unknown'>
        """
        normalised = (value or "").strip().lower()
        for member in cls:
            if member.value == normalised:
                return member
        return cls.UNKNOWN


@dataclass
class FallbackContext:
    """Carries the full context of a single fallback event.

    Attributes
    ----------
    from_level:
        The :class:`~core.execution_observability.ExecutorLevel` that was
        attempted and failed / was skipped.
    to_level:
        The :class:`~core.execution_observability.ExecutorLevel` that will be
        tried next.  ``None`` if no further fallback is planned.
    reason:
        Structured :class:`FallbackReason`.
    raw_reason:
        The raw string reason as emitted by the originating code path (for
        round-trip fidelity).
    message:
        Human-readable explanation.
    metadata:
        Arbitrary key-value pairs for additional context (e.g.
        ``{"action": "click", "device_id": "win-1"}``).
    """

    from_level: ExecutorLevel = ExecutorLevel.UNKNOWN
    to_level: Optional[ExecutorLevel] = None
    reason: FallbackReason = FallbackReason.UNKNOWN
    raw_reason: str = ""
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "from_level": self.from_level.value,
            "to_level": self.to_level.value if self.to_level is not None else None,
            "reason": self.reason.value,
            "raw_reason": self.raw_reason,
            "message": self.message,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FallbackContext":
        """Reconstruct a :class:`FallbackContext` from a dict."""
        to_level_raw = data.get("to_level")
        return cls(
            from_level=ExecutorLevel.from_string(data.get("from_level", "")),
            to_level=ExecutorLevel.from_string(to_level_raw) if to_level_raw else None,
            reason=FallbackReason.from_string(data.get("reason", "")),
            raw_reason=data.get("raw_reason", ""),
            message=data.get("message", ""),
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def from_arbiter_attempt(cls, attempt: Any) -> "FallbackContext":
        """Build from a ``WinExecAttempt`` dataclass (arbiter log entry).

        Accepts any object with ``executor_level`` and ``fallback_reason``
        attributes, or a plain dict with the same keys.  No hard import of
        ``core.windows_execution_arbiter`` is required.
        """
        if isinstance(attempt, dict):
            level_raw = attempt.get("executor_level", "")
            raw_reason = attempt.get("fallback_reason", "")
        else:
            level_raw = getattr(attempt, "executor_level", "") or ""
            if hasattr(level_raw, "value"):
                level_raw = level_raw.value
            raw_reason = getattr(attempt, "fallback_reason", "") or ""

        from_level = ExecutorLevel.from_string(str(level_raw))
        reason = FallbackReason.from_string(str(raw_reason))
        return cls(
            from_level=from_level,
            reason=reason,
            raw_reason=str(raw_reason),
            message=f"Fallback from {from_level.value}: {raw_reason or reason.value}",
        )
