#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/unified/command_envelope.py
==================================
PR-2 (Block-2) — Unified Command Envelope

Defines the canonical command envelope used across the entire
planner → gateway → device → result chain.

Every command issued by any component (planner, gateway, orchestrator)
MUST be wrapped in a :class:`CommandEnvelope` before dispatch.
Result callbacks use :class:`ResultEnvelope` to carry structured responses.

Design goals
------------
- **Additive** — existing TaskEnvelope and AIPMessage formats are preserved;
  this envelope supplements them with extra trace and idempotency fields.
- **Observable** — all canonical fields are logged at DEBUG level on creation,
  providing a full audit trail without side effects.
- **No external dependencies** — stdlib + dataclasses so this module can be
  imported from anywhere.

Canonical fields
----------------
trace_id            : str  — distributed trace identifier (propagated through all hops)
runtime_session_id  : str  — session scope (ties commands within one user interaction)
task_id             : str  — unique task identifier
device_id           : str  — target device (may be empty for broadcast commands)
version             : str  — protocol version (e.g. "3.0")
idempotency_key     : Optional[str] — client-assigned dedup key; generated when absent
payload             : dict  — command-specific data
response_metadata   : dict  — populated by the executor with result metadata

Usage::

    from core.unified.command_envelope import CommandEnvelope, ResultEnvelope

    env = CommandEnvelope(
        trace_id="trace-abc",
        runtime_session_id="session-xyz",
        task_id="task-001",
        device_id="android_01",
        payload={"action": "screenshot"},
    )
    log_command_envelope(env)
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.Unified.CommandEnvelope")

# ---------------------------------------------------------------------------
# Protocol version constants
# ---------------------------------------------------------------------------

ENVELOPE_VERSION = "3.0"
"""Current canonical protocol version carried in all envelopes."""


# ---------------------------------------------------------------------------
# CommandEnvelope
# ---------------------------------------------------------------------------


@dataclass
class CommandEnvelope:
    """Canonical command envelope for the planner → gateway → device chain.

    All fields except *payload* have auto-generated defaults so that partial
    construction is valid; consumers that require specific fields must validate
    them with :func:`validate_command_envelope`.
    """

    # ── Identity ────────────────────────────────────────────────────────────
    trace_id: str = field(
        default_factory=lambda: f"trace_{uuid.uuid4().hex[:12]}"
    )
    """Distributed trace identifier.  Set by the originating component and
    propagated unchanged through the entire call chain."""

    runtime_session_id: str = field(
        default_factory=lambda: f"session_{uuid.uuid4().hex[:12]}"
    )
    """Session identifier tying commands to a single user/agent interaction."""

    task_id: str = field(
        default_factory=lambda: f"task_{uuid.uuid4().hex[:16]}"
    )
    """Globally unique task identifier."""

    device_id: str = ""
    """Target device identifier.  Empty string means broadcast / unrouted."""

    # ── Protocol ────────────────────────────────────────────────────────────
    version: str = ENVELOPE_VERSION
    """Protocol version string — MUST match :data:`ENVELOPE_VERSION`."""

    # ── Idempotency ─────────────────────────────────────────────────────────
    idempotency_key: Optional[str] = None
    """Client-supplied dedup key.  Auto-generated from *task_id* when absent.
    Two envelopes with the same idempotency_key MUST produce the same
    side-effect exactly once."""

    # ── Payload ─────────────────────────────────────────────────────────────
    payload: Dict[str, Any] = field(default_factory=dict)
    """Command-specific data (action, parameters, …)."""

    # ── Metadata ────────────────────────────────────────────────────────────
    response_metadata: Dict[str, Any] = field(default_factory=dict)
    """Populated by the executor with result metadata (status, elapsed_ms, …)."""

    created_at: float = field(default_factory=time.time)
    """Unix timestamp (seconds) at envelope creation."""

    # ── Extras ──────────────────────────────────────────────────────────────
    extra: Dict[str, Any] = field(default_factory=dict)
    """Arbitrary extension fields.  Prefer explicit fields for new requirements."""

    def __post_init__(self) -> None:
        if not self.idempotency_key:
            self.idempotency_key = f"idem_{self.task_id}"

    # ── Serialisation helpers ───────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation of this envelope."""
        return {
            "trace_id": self.trace_id,
            "runtime_session_id": self.runtime_session_id,
            "task_id": self.task_id,
            "device_id": self.device_id,
            "version": self.version,
            "idempotency_key": self.idempotency_key,
            "payload": dict(self.payload),
            "response_metadata": dict(self.response_metadata),
            "created_at": self.created_at,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CommandEnvelope":
        """Reconstruct a :class:`CommandEnvelope` from a plain dict.

        Unknown keys are collected into :attr:`extra` so forward-compatibility
        is preserved.
        """
        known = {
            "trace_id", "runtime_session_id", "task_id", "device_id",
            "version", "idempotency_key", "payload", "response_metadata",
            "created_at", "extra",
        }
        kwargs: Dict[str, Any] = {}
        extra: Dict[str, Any] = {}
        for k, v in data.items():
            if k in known:
                kwargs[k] = v
            else:
                extra[k] = v
        if extra:
            kwargs.setdefault("extra", {}).update(extra)
        return cls(**kwargs)

    @classmethod
    def from_task_envelope(cls, task_envelope: Any) -> "CommandEnvelope":
        """Construct from a :class:`~core.schemas.task_envelope.TaskEnvelope`.

        Preserves existing trace_id / session_id / task_id when present so
        that the envelope chain remains coherent.
        """
        te = task_envelope
        return cls(
            trace_id=getattr(te, "trace_id", "") or f"trace_{uuid.uuid4().hex[:12]}",
            runtime_session_id=getattr(te, "session_id", "") or f"session_{uuid.uuid4().hex[:12]}",
            task_id=getattr(te, "task_id", "") or f"task_{uuid.uuid4().hex[:16]}",
            device_id=_first_target(te),
            payload=dict(getattr(te, "args", {}) or {}),
            extra={"tool_name": getattr(te, "tool_name", ""), "source": getattr(te, "source", "")},
        )

    @classmethod
    def from_aip_message(cls, msg: Any) -> "CommandEnvelope":
        """Construct from an :class:`~galaxy_gateway.protocol.aip_v3.AIPMessage`.

        Uses the AIP message's existing trace / session / task fields so no new
        IDs are generated unnecessarily.
        """
        trace_id = getattr(msg, "trace_id", None) or getattr(
            msg.payload, "get", lambda k, d: d
        )("trace_id", "") if hasattr(msg, "payload") and isinstance(msg.payload, dict) else ""
        trace_id = trace_id or f"trace_{uuid.uuid4().hex[:12]}"

        runtime_session_id = ""
        if hasattr(msg, "payload") and isinstance(msg.payload, dict):
            runtime_session_id = msg.payload.get("runtime_session_id", "")
        runtime_session_id = runtime_session_id or f"session_{uuid.uuid4().hex[:12]}"

        return cls(
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
            task_id=getattr(msg, "task_id", None) or f"task_{uuid.uuid4().hex[:16]}",
            device_id=getattr(msg, "device_id", ""),
            version=getattr(msg, "version", ENVELOPE_VERSION),
            payload=dict(msg.payload) if isinstance(getattr(msg, "payload", None), dict) else {},
            extra={"message_id": getattr(msg, "message_id", ""), "type": str(getattr(msg, "type", ""))},
        )


# ---------------------------------------------------------------------------
# ResultEnvelope
# ---------------------------------------------------------------------------


@dataclass
class ResultEnvelope:
    """Canonical result envelope returned by executors to their callers.

    Correlates with a :class:`CommandEnvelope` via *task_id* and *trace_id*.
    """

    task_id: str
    trace_id: str
    success: bool
    device_id: str = ""
    runtime_session_id: str = ""
    version: str = ENVELOPE_VERSION
    idempotency_key: Optional[str] = None

    result: Dict[str, Any] = field(default_factory=dict)
    """Executor-returned output data."""

    error: Optional[str] = None
    """Human-readable error description when *success* is False."""

    error_code: Optional[str] = None
    """Machine-readable error code (see ``core/unified/error_codes.py``)."""

    elapsed_ms: float = 0.0
    """Wall-clock time for the execution in milliseconds."""

    completed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "success": self.success,
            "device_id": self.device_id,
            "runtime_session_id": self.runtime_session_id,
            "version": self.version,
            "idempotency_key": self.idempotency_key,
            "result": dict(self.result),
            "error": self.error,
            "error_code": self.error_code,
            "elapsed_ms": self.elapsed_ms,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResultEnvelope":
        return cls(
            task_id=data.get("task_id", ""),
            trace_id=data.get("trace_id", ""),
            success=bool(data.get("success", False)),
            device_id=data.get("device_id", ""),
            runtime_session_id=data.get("runtime_session_id", ""),
            version=data.get("version", ENVELOPE_VERSION),
            idempotency_key=data.get("idempotency_key"),
            result=data.get("result", {}),
            error=data.get("error"),
            error_code=data.get("error_code"),
            elapsed_ms=float(data.get("elapsed_ms", 0.0)),
            completed_at=float(data.get("completed_at", time.time())),
        )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

REQUIRED_COMMAND_FIELDS = ("trace_id", "runtime_session_id", "task_id", "version")
"""Fields that MUST be non-empty for a command envelope to be considered valid."""

REQUIRED_RESULT_FIELDS = ("task_id", "trace_id")
"""Fields that MUST be non-empty for a result envelope to be valid."""


class EnvelopeValidationError(ValueError):
    """Raised when an envelope is missing required fields.

    Attributes
    ----------
    missing_fields : list[str]
        Names of the fields that are absent or empty.
    error_code : str
        Machine-readable error code (``MISSING_ENVELOPE_FIELDS``).
    """

    error_code = "MISSING_ENVELOPE_FIELDS"

    def __init__(self, missing_fields: list, envelope_type: str = "command") -> None:
        self.missing_fields = missing_fields
        self.envelope_type = envelope_type
        super().__init__(
            f"{envelope_type} envelope missing required fields: {missing_fields}"
        )


def validate_command_envelope(envelope: CommandEnvelope) -> None:
    """Raise :class:`EnvelopeValidationError` if required fields are empty.

    This is a *fail-fast* check intended for use at ingress points
    (gateway handlers, orchestrator entry points).
    """
    missing = [f for f in REQUIRED_COMMAND_FIELDS if not getattr(envelope, f, "")]
    if missing:
        logger.error(
            "CommandEnvelope validation failed",
            extra={
                "event": "envelope_validation_failed",
                "missing_fields": missing,
                "task_id": getattr(envelope, "task_id", ""),
                "trace_id": getattr(envelope, "trace_id", ""),
                "error_code": EnvelopeValidationError.error_code,
            },
        )
        raise EnvelopeValidationError(missing, "command")


def validate_result_envelope(envelope: ResultEnvelope) -> None:
    """Raise :class:`EnvelopeValidationError` if required result fields are empty."""
    missing = [f for f in REQUIRED_RESULT_FIELDS if not getattr(envelope, f, "")]
    if missing:
        raise EnvelopeValidationError(missing, "result")


# ---------------------------------------------------------------------------
# Observability helpers
# ---------------------------------------------------------------------------


def log_command_envelope(envelope: CommandEnvelope, event: str = "command_envelope_created") -> None:
    """Emit a structured DEBUG log for *envelope*.

    Call this at every hop that creates or forwards a command envelope so
    that the complete chain is visible in logs.
    """
    logger.debug(
        "CommandEnvelope: %s task=%s trace=%s device=%s version=%s",
        event,
        envelope.task_id,
        envelope.trace_id,
        envelope.device_id,
        envelope.version,
        extra={
            "event": event,
            "trace_id": envelope.trace_id,
            "runtime_session_id": envelope.runtime_session_id,
            "task_id": envelope.task_id,
            "device_id": envelope.device_id,
            "version": envelope.version,
            "idempotency_key": envelope.idempotency_key,
        },
    )


def log_result_envelope(envelope: ResultEnvelope, event: str = "result_envelope_received") -> None:
    """Emit a structured DEBUG log for *envelope*."""
    logger.debug(
        "ResultEnvelope: %s task=%s trace=%s success=%s elapsed=%.1fms",
        event,
        envelope.task_id,
        envelope.trace_id,
        envelope.success,
        envelope.elapsed_ms,
        extra={
            "event": event,
            "trace_id": envelope.trace_id,
            "task_id": envelope.task_id,
            "success": envelope.success,
            "error_code": envelope.error_code,
            "elapsed_ms": envelope.elapsed_ms,
        },
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _first_target(task_envelope: Any) -> str:
    """Extract the first target device_id from a TaskEnvelope-like object."""
    targets = getattr(task_envelope, "targets", None)
    if targets and isinstance(targets, list) and targets:
        return str(targets[0])
    return getattr(task_envelope, "device_id", "") or ""
