"""core/skill_contract.py
=========================
Unified Skill / MCP Contract (PR-4)

Defines the canonical request/response envelope, standardised error codes,
and validation helpers that every Skill and MCP tool invocation must pass
through.  All call sites (OpenClawd, API routes, test harnesses, …) use
these models so the rest of the system never needs to deal with ad-hoc dicts.

Key objects
-----------
SkillRequest
    Input envelope – carries the skill name, arguments, and tracing context.
SkillResponse
    Output envelope – carries status, outputs, errors, and timing metrics.
SkillErrorCode
    Enumerated error codes shared across all callers, including a flag that
    indicates whether the caller may safely retry.
SkillError
    Structured error container embedded in :class:`SkillResponse`.

Validation helpers
------------------
validate_skill_request(req)   → raises ``ValueError`` on contract violations.
validate_skill_response(resp) → raises ``ValueError`` on contract violations.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Error catalogue
# ---------------------------------------------------------------------------


class SkillErrorCode(str, Enum):
    """Standardised error codes for skill / MCP invocations.

    Each code has a companion *retryable* flag (see
    :func:`is_retryable_error`).
    """

    # Input / routing errors (non-retryable)
    NOT_FOUND = "skill_not_found"
    INVALID_INPUT = "invalid_input"
    PERMISSION_DENIED = "permission_denied"

    # Execution errors (potentially retryable)
    EXECUTION_ERROR = "execution_error"
    TIMEOUT = "timeout"
    HANDLER_MISSING = "handler_missing"

    # Infrastructure errors (retryable)
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    RATE_LIMITED = "rate_limited"

    # Unexpected errors (non-retryable by default)
    INTERNAL_ERROR = "internal_error"


#: Error codes that callers *may* automatically retry.
_RETRYABLE_ERRORS: frozenset[SkillErrorCode] = frozenset(
    [
        SkillErrorCode.EXECUTION_ERROR,
        SkillErrorCode.TIMEOUT,
        SkillErrorCode.DEPENDENCY_UNAVAILABLE,
        SkillErrorCode.RATE_LIMITED,
    ]
)


def is_retryable_error(code: SkillErrorCode) -> bool:
    """Return ``True`` if *code* represents a transient condition.

    Args:
        code: The :class:`SkillErrorCode` to test.

    Returns:
        ``True`` when the caller may safely retry the invocation.
    """
    return code in _RETRYABLE_ERRORS


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


@dataclass
class SkillRequest:
    """Canonical invocation request for a skill or MCP tool.

    Attributes:
        skill_name: Registered skill name or MCP tool identifier
            (e.g. ``"weather_lookup"`` or ``"mcp__filesystem__read_file"``).
        inputs: Keyword arguments forwarded verbatim to the handler.
        context: Caller-supplied contextual metadata (e.g. user intent,
            session state).  Never passed directly to the handler.
        device_id: Target device identifier, if the skill operates on a
            specific device.
        trace_id: Opaque trace identifier propagated across subsystems for
            end-to-end observability.  Auto-generated if not provided.
        runtime_session_id: The session that initiated this call.
        caller: Human-readable label for the originating component
            (e.g. ``"openclawd"``, ``"api_route"``).
        timeout_s: Maximum execution time in seconds.  ``None`` means no
            explicit deadline.
    """

    skill_name: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    device_id: str = ""
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    runtime_session_id: str = ""
    caller: str = ""
    timeout_s: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "skill_name": self.skill_name,
            "inputs": self.inputs,
            "context": self.context,
            "device_id": self.device_id,
            "trace_id": self.trace_id,
            "runtime_session_id": self.runtime_session_id,
            "caller": self.caller,
            "timeout_s": self.timeout_s,
        }


# ---------------------------------------------------------------------------
# Response / error models
# ---------------------------------------------------------------------------


@dataclass
class SkillError:
    """Structured error descriptor embedded in :class:`SkillResponse`.

    Attributes:
        code: Enumerated :class:`SkillErrorCode`.
        message: Human-readable description.
        retryable: Whether the caller may safely retry.
        details: Optional machine-readable supplemental data.
    """

    code: SkillErrorCode
    message: str
    retryable: bool = field(init=False)
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.retryable = is_retryable_error(self.code)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
        }


class SkillStatus(str, Enum):
    """Top-level outcome of a skill invocation."""

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"     # handler returned a result but with warnings


@dataclass
class SkillMetrics:
    """Timing and resource counters attached to every :class:`SkillResponse`.

    Attributes:
        started_at: Unix timestamp (seconds) when execution began.
        finished_at: Unix timestamp when execution finished.
        duration_ms: Wall-clock elapsed time in milliseconds.
        executor: Label of the subsystem that ran the skill (e.g.
            ``"skill_loader"``, ``"mcp_loader"``).
    """

    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    duration_ms: float = 0.0
    executor: str = ""

    def finish(self) -> None:
        """Record the finish timestamp and compute *duration_ms*."""
        self.finished_at = time.time()
        self.duration_ms = (self.finished_at - self.started_at) * 1_000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round(self.duration_ms, 3),
            "executor": self.executor,
        }


@dataclass
class SkillResponse:
    """Canonical response envelope returned by all skill / MCP invocations.

    Attributes:
        skill_name: Echo of the requested skill name.
        trace_id: Trace identifier copied from the originating request.
        status: Outcome enum (:class:`SkillStatus`).
        outputs: Result payload produced by the handler.  ``None`` on failure.
        errors: List of :class:`SkillError` instances (empty on success).
        metrics: Timing and executor metadata.
    """

    skill_name: str
    trace_id: str
    status: SkillStatus = SkillStatus.SUCCESS
    outputs: Optional[Any] = None
    errors: List[SkillError] = field(default_factory=list)
    metrics: SkillMetrics = field(default_factory=SkillMetrics)

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------

    @classmethod
    def success(
        cls,
        skill_name: str,
        trace_id: str,
        outputs: Any,
        metrics: Optional[SkillMetrics] = None,
    ) -> "SkillResponse":
        """Build a successful response."""
        return cls(
            skill_name=skill_name,
            trace_id=trace_id,
            status=SkillStatus.SUCCESS,
            outputs=outputs,
            metrics=metrics or SkillMetrics(),
        )

    @classmethod
    def failure(
        cls,
        skill_name: str,
        trace_id: str,
        code: SkillErrorCode,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        metrics: Optional[SkillMetrics] = None,
    ) -> "SkillResponse":
        """Build a failure response."""
        return cls(
            skill_name=skill_name,
            trace_id=trace_id,
            status=SkillStatus.FAILURE,
            errors=[SkillError(code=code, message=message, details=details or {})],
            metrics=metrics or SkillMetrics(),
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dictionary (gateway-safe)."""
        return {
            "skill_name": self.skill_name,
            "trace_id": self.trace_id,
            "status": self.status.value,
            "outputs": self.outputs,
            "errors": [e.to_dict() for e in self.errors],
            "metrics": self.metrics.to_dict(),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def ok(self) -> bool:
        """``True`` when the invocation succeeded."""
        return self.status == SkillStatus.SUCCESS

    @property
    def first_error(self) -> Optional[SkillError]:
        """Return the first error, or ``None`` if there are none."""
        return self.errors[0] if self.errors else None


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_skill_request(req: SkillRequest) -> None:
    """Validate a :class:`SkillRequest` and raise :class:`ValueError` on
    contract violations.

    Checks:
    * ``skill_name`` is a non-empty string.
    * ``inputs`` is a mapping (dict).
    * ``timeout_s``, if set, is a positive number.
    * ``trace_id`` is a non-empty string (auto-assigned by the dataclass
      default, so only empty-string abuse is caught).

    Args:
        req: The request to validate.

    Raises:
        ValueError: When the contract is violated.
    """
    if not isinstance(req.skill_name, str) or not req.skill_name.strip():
        raise ValueError("SkillRequest.skill_name must be a non-empty string")
    if not isinstance(req.inputs, dict):
        raise ValueError("SkillRequest.inputs must be a dict")
    if req.timeout_s is not None and req.timeout_s <= 0:
        raise ValueError("SkillRequest.timeout_s must be positive")
    if not req.trace_id:
        raise ValueError("SkillRequest.trace_id must be non-empty")


def validate_skill_response(resp: SkillResponse) -> None:
    """Validate a :class:`SkillResponse` and raise :class:`ValueError` on
    contract violations.

    Checks:
    * ``skill_name`` is a non-empty string.
    * ``status`` is a valid :class:`SkillStatus`.
    * On failure, ``errors`` is a non-empty list.
    * On success, ``errors`` is empty.

    Args:
        resp: The response to validate.

    Raises:
        ValueError: When the contract is violated.
    """
    if not isinstance(resp.skill_name, str) or not resp.skill_name.strip():
        raise ValueError("SkillResponse.skill_name must be a non-empty string")
    if resp.status == SkillStatus.FAILURE and not resp.errors:
        raise ValueError(
            "SkillResponse with status=failure must contain at least one error"
        )
    if resp.status == SkillStatus.SUCCESS and resp.errors:
        raise ValueError(
            "SkillResponse with status=success must not contain errors"
        )
