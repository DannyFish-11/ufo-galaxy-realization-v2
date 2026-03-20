#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/unified/error_codes.py
============================
Block-5: Unified Error Taxonomy

Defines a canonical set of structured error codes covering all major subsystems
(planner, executor, gateway, device, transport, idempotency, arbiter).

Each code carries:
  - A machine-readable string identifier (e.g. ``"EXEC_001"``)
  - A human-readable description
  - Retryability semantics (``Retryable`` enum)
  - Severity (``ErrorSeverity``)
  - Owning subsystem (``ErrorDomain``)

Usage::

    from core.unified.error_codes import GalaxyErrorCode, ErrorPayload

    payload = ErrorPayload.from_code(GalaxyErrorCode.DEVICE_TIMEOUT)
    if payload.retryable:
        # schedule a retry
        ...
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Retryable(str, Enum):
    """Retryability classification for an error."""

    YES = "yes"          # Transient — safe to retry immediately or after back-off
    BACKOFF = "backoff"  # Retry only after an exponential back-off delay
    NO = "no"            # Permanent / fatal — do not retry
    CONDITIONAL = "conditional"  # Context-dependent (inspect payload for hint)


class ErrorSeverity(str, Enum):
    """Operational severity of an error."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ErrorDomain(str, Enum):
    """Owning subsystem / layer."""

    PLANNER = "planner"
    EXECUTOR = "executor"
    GATEWAY = "gateway"
    DEVICE = "device"
    TRANSPORT = "transport"
    IDEMPOTENCY = "idempotency"
    ARBITER = "arbiter"
    COGNITIVE = "cognitive"
    RELEASE = "release"
    INTERNAL = "internal"


# ---------------------------------------------------------------------------
# Error code definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ErrorCodeDef:
    """Immutable descriptor for one error code."""

    code: str
    description: str
    retryable: Retryable
    severity: ErrorSeverity
    domain: ErrorDomain


class GalaxyErrorCode(str, Enum):
    """Canonical error codes for the Galaxy system.

    Values are the string code identifiers; descriptors live in
    ``ERROR_CODE_REGISTRY``.
    """

    # ------------------------------------------------------------------
    # Planner errors  PL-xxx
    # ------------------------------------------------------------------
    PLAN_DECOMPOSE_FAILED = "PL_001"
    PLAN_NO_CAPABLE_DEVICE = "PL_002"
    PLAN_CYCLE_DETECTED = "PL_003"
    PLAN_TIMEOUT = "PL_004"

    # ------------------------------------------------------------------
    # Executor errors  EX-xxx
    # ------------------------------------------------------------------
    EXEC_DISPATCH_FAILED = "EX_001"
    EXEC_TASK_TIMEOUT = "EX_002"
    EXEC_RESOURCE_EXHAUSTED = "EX_003"
    EXEC_PREEMPTED = "EX_004"
    EXEC_CANCELLED = "EX_005"

    # ------------------------------------------------------------------
    # Gateway / protocol errors  GW-xxx
    # ------------------------------------------------------------------
    GW_ENVELOPE_INVALID = "GW_001"
    GW_ROUTE_NOT_FOUND = "GW_002"
    GW_AUTH_FAILED = "GW_003"
    GW_RATE_LIMITED = "GW_004"
    GW_PROTOCOL_MISMATCH = "GW_005"

    # ------------------------------------------------------------------
    # Device errors  DV-xxx
    # ------------------------------------------------------------------
    DEVICE_NOT_FOUND = "DV_001"
    DEVICE_TIMEOUT = "DV_002"
    DEVICE_SEND_FAILED = "DV_003"
    DEVICE_CAPABILITY_MISSING = "DV_004"
    DEVICE_OFFLINE = "DV_005"

    # ------------------------------------------------------------------
    # Transport / NATS errors  TR-xxx
    # ------------------------------------------------------------------
    TRANSPORT_CONNECT_FAILED = "TR_001"
    TRANSPORT_PUBLISH_FAILED = "TR_002"
    TRANSPORT_SUBSCRIBE_FAILED = "TR_003"
    TRANSPORT_DISCONNECT = "TR_004"

    # ------------------------------------------------------------------
    # Idempotency errors  ID-xxx
    # ------------------------------------------------------------------
    IDEMPOTENCY_DUPLICATE = "ID_001"
    IDEMPOTENCY_CONFLICT = "ID_002"

    # ------------------------------------------------------------------
    # Arbiter / scheduler errors  AR-xxx
    # ------------------------------------------------------------------
    ARBITER_PREEMPTED = "AR_001"
    ARBITER_QUOTA_EXCEEDED = "AR_002"
    ARBITER_NO_SLOT = "AR_003"

    # ------------------------------------------------------------------
    # Release / feature-gate errors  RL-xxx
    # ------------------------------------------------------------------
    RELEASE_FEATURE_DISABLED = "RL_001"
    RELEASE_ROLLOUT_BLOCKED = "RL_002"

    # ------------------------------------------------------------------
    # Catch-all
    # ------------------------------------------------------------------
    INTERNAL_UNKNOWN = "XX_000"


# ---------------------------------------------------------------------------
# Registry: code → descriptor
# ---------------------------------------------------------------------------

ERROR_CODE_REGISTRY: Dict[str, _ErrorCodeDef] = {
    # Planner
    GalaxyErrorCode.PLAN_DECOMPOSE_FAILED: _ErrorCodeDef(
        GalaxyErrorCode.PLAN_DECOMPOSE_FAILED,
        "Task decomposition failed",
        Retryable.BACKOFF, ErrorSeverity.ERROR, ErrorDomain.PLANNER,
    ),
    GalaxyErrorCode.PLAN_NO_CAPABLE_DEVICE: _ErrorCodeDef(
        GalaxyErrorCode.PLAN_NO_CAPABLE_DEVICE,
        "No capable device available for the planned step",
        Retryable.CONDITIONAL, ErrorSeverity.WARNING, ErrorDomain.PLANNER,
    ),
    GalaxyErrorCode.PLAN_CYCLE_DETECTED: _ErrorCodeDef(
        GalaxyErrorCode.PLAN_CYCLE_DETECTED,
        "Cycle detected in task dependency graph",
        Retryable.NO, ErrorSeverity.ERROR, ErrorDomain.PLANNER,
    ),
    GalaxyErrorCode.PLAN_TIMEOUT: _ErrorCodeDef(
        GalaxyErrorCode.PLAN_TIMEOUT,
        "Planner exceeded maximum allowed time",
        Retryable.BACKOFF, ErrorSeverity.WARNING, ErrorDomain.PLANNER,
    ),
    # Executor
    GalaxyErrorCode.EXEC_DISPATCH_FAILED: _ErrorCodeDef(
        GalaxyErrorCode.EXEC_DISPATCH_FAILED,
        "Task dispatch to executor failed",
        Retryable.YES, ErrorSeverity.ERROR, ErrorDomain.EXECUTOR,
    ),
    GalaxyErrorCode.EXEC_TASK_TIMEOUT: _ErrorCodeDef(
        GalaxyErrorCode.EXEC_TASK_TIMEOUT,
        "Executor task exceeded deadline",
        Retryable.BACKOFF, ErrorSeverity.WARNING, ErrorDomain.EXECUTOR,
    ),
    GalaxyErrorCode.EXEC_RESOURCE_EXHAUSTED: _ErrorCodeDef(
        GalaxyErrorCode.EXEC_RESOURCE_EXHAUSTED,
        "Executor resource quota exhausted",
        Retryable.BACKOFF, ErrorSeverity.ERROR, ErrorDomain.EXECUTOR,
    ),
    GalaxyErrorCode.EXEC_PREEMPTED: _ErrorCodeDef(
        GalaxyErrorCode.EXEC_PREEMPTED,
        "Execution preempted by higher-priority task",
        Retryable.YES, ErrorSeverity.INFO, ErrorDomain.EXECUTOR,
    ),
    GalaxyErrorCode.EXEC_CANCELLED: _ErrorCodeDef(
        GalaxyErrorCode.EXEC_CANCELLED,
        "Execution cancelled by operator or policy",
        Retryable.NO, ErrorSeverity.INFO, ErrorDomain.EXECUTOR,
    ),
    # Gateway
    GalaxyErrorCode.GW_ENVELOPE_INVALID: _ErrorCodeDef(
        GalaxyErrorCode.GW_ENVELOPE_INVALID,
        "Command envelope failed validation",
        Retryable.NO, ErrorSeverity.ERROR, ErrorDomain.GATEWAY,
    ),
    GalaxyErrorCode.GW_ROUTE_NOT_FOUND: _ErrorCodeDef(
        GalaxyErrorCode.GW_ROUTE_NOT_FOUND,
        "No matching route in gateway",
        Retryable.CONDITIONAL, ErrorSeverity.WARNING, ErrorDomain.GATEWAY,
    ),
    GalaxyErrorCode.GW_AUTH_FAILED: _ErrorCodeDef(
        GalaxyErrorCode.GW_AUTH_FAILED,
        "Gateway authentication / authorisation failed",
        Retryable.NO, ErrorSeverity.ERROR, ErrorDomain.GATEWAY,
    ),
    GalaxyErrorCode.GW_RATE_LIMITED: _ErrorCodeDef(
        GalaxyErrorCode.GW_RATE_LIMITED,
        "Gateway rate limit exceeded",
        Retryable.BACKOFF, ErrorSeverity.WARNING, ErrorDomain.GATEWAY,
    ),
    GalaxyErrorCode.GW_PROTOCOL_MISMATCH: _ErrorCodeDef(
        GalaxyErrorCode.GW_PROTOCOL_MISMATCH,
        "Protocol version mismatch at gateway",
        Retryable.NO, ErrorSeverity.ERROR, ErrorDomain.GATEWAY,
    ),
    # Device
    GalaxyErrorCode.DEVICE_NOT_FOUND: _ErrorCodeDef(
        GalaxyErrorCode.DEVICE_NOT_FOUND,
        "Target device not found or not registered",
        Retryable.CONDITIONAL, ErrorSeverity.WARNING, ErrorDomain.DEVICE,
    ),
    GalaxyErrorCode.DEVICE_TIMEOUT: _ErrorCodeDef(
        GalaxyErrorCode.DEVICE_TIMEOUT,
        "Device command timed out",
        Retryable.BACKOFF, ErrorSeverity.WARNING, ErrorDomain.DEVICE,
    ),
    GalaxyErrorCode.DEVICE_SEND_FAILED: _ErrorCodeDef(
        GalaxyErrorCode.DEVICE_SEND_FAILED,
        "Failed to send message to device",
        Retryable.YES, ErrorSeverity.ERROR, ErrorDomain.DEVICE,
    ),
    GalaxyErrorCode.DEVICE_CAPABILITY_MISSING: _ErrorCodeDef(
        GalaxyErrorCode.DEVICE_CAPABILITY_MISSING,
        "Device does not expose required capability",
        Retryable.NO, ErrorSeverity.WARNING, ErrorDomain.DEVICE,
    ),
    GalaxyErrorCode.DEVICE_OFFLINE: _ErrorCodeDef(
        GalaxyErrorCode.DEVICE_OFFLINE,
        "Device is offline or unreachable",
        Retryable.BACKOFF, ErrorSeverity.WARNING, ErrorDomain.DEVICE,
    ),
    # Transport
    GalaxyErrorCode.TRANSPORT_CONNECT_FAILED: _ErrorCodeDef(
        GalaxyErrorCode.TRANSPORT_CONNECT_FAILED,
        "Transport layer connection failed",
        Retryable.BACKOFF, ErrorSeverity.ERROR, ErrorDomain.TRANSPORT,
    ),
    GalaxyErrorCode.TRANSPORT_PUBLISH_FAILED: _ErrorCodeDef(
        GalaxyErrorCode.TRANSPORT_PUBLISH_FAILED,
        "Failed to publish message over transport",
        Retryable.YES, ErrorSeverity.ERROR, ErrorDomain.TRANSPORT,
    ),
    GalaxyErrorCode.TRANSPORT_SUBSCRIBE_FAILED: _ErrorCodeDef(
        GalaxyErrorCode.TRANSPORT_SUBSCRIBE_FAILED,
        "Failed to subscribe to transport topic",
        Retryable.BACKOFF, ErrorSeverity.ERROR, ErrorDomain.TRANSPORT,
    ),
    GalaxyErrorCode.TRANSPORT_DISCONNECT: _ErrorCodeDef(
        GalaxyErrorCode.TRANSPORT_DISCONNECT,
        "Unexpected transport disconnect",
        Retryable.YES, ErrorSeverity.WARNING, ErrorDomain.TRANSPORT,
    ),
    # Idempotency
    GalaxyErrorCode.IDEMPOTENCY_DUPLICATE: _ErrorCodeDef(
        GalaxyErrorCode.IDEMPOTENCY_DUPLICATE,
        "Duplicate command detected — idempotency key already processed",
        Retryable.NO, ErrorSeverity.INFO, ErrorDomain.IDEMPOTENCY,
    ),
    GalaxyErrorCode.IDEMPOTENCY_CONFLICT: _ErrorCodeDef(
        GalaxyErrorCode.IDEMPOTENCY_CONFLICT,
        "Idempotency key conflict: same key, different payload",
        Retryable.NO, ErrorSeverity.ERROR, ErrorDomain.IDEMPOTENCY,
    ),
    # Arbiter
    GalaxyErrorCode.ARBITER_PREEMPTED: _ErrorCodeDef(
        GalaxyErrorCode.ARBITER_PREEMPTED,
        "Task preempted by global scheduler arbiter",
        Retryable.YES, ErrorSeverity.INFO, ErrorDomain.ARBITER,
    ),
    GalaxyErrorCode.ARBITER_QUOTA_EXCEEDED: _ErrorCodeDef(
        GalaxyErrorCode.ARBITER_QUOTA_EXCEEDED,
        "Scheduler concurrency quota exceeded",
        Retryable.BACKOFF, ErrorSeverity.WARNING, ErrorDomain.ARBITER,
    ),
    GalaxyErrorCode.ARBITER_NO_SLOT: _ErrorCodeDef(
        GalaxyErrorCode.ARBITER_NO_SLOT,
        "No scheduling slot available right now",
        Retryable.BACKOFF, ErrorSeverity.INFO, ErrorDomain.ARBITER,
    ),
    # Release
    GalaxyErrorCode.RELEASE_FEATURE_DISABLED: _ErrorCodeDef(
        GalaxyErrorCode.RELEASE_FEATURE_DISABLED,
        "Feature is disabled via feature flag",
        Retryable.NO, ErrorSeverity.INFO, ErrorDomain.RELEASE,
    ),
    GalaxyErrorCode.RELEASE_ROLLOUT_BLOCKED: _ErrorCodeDef(
        GalaxyErrorCode.RELEASE_ROLLOUT_BLOCKED,
        "Request blocked by staged rollout gate",
        Retryable.BACKOFF, ErrorSeverity.INFO, ErrorDomain.RELEASE,
    ),
    # Catch-all
    GalaxyErrorCode.INTERNAL_UNKNOWN: _ErrorCodeDef(
        GalaxyErrorCode.INTERNAL_UNKNOWN,
        "Unknown internal error",
        Retryable.CONDITIONAL, ErrorSeverity.ERROR, ErrorDomain.INTERNAL,
    ),
}  # type: ignore[assignment]


def _registry() -> Dict[str, _ErrorCodeDef]:
    """Return the error-code registry (normalising enum-keyed entries)."""
    result: Dict[str, _ErrorCodeDef] = {}
    for k, v in ERROR_CODE_REGISTRY.items():
        key = k.value if isinstance(k, GalaxyErrorCode) else str(k)
        result[key] = v
    return result


# ---------------------------------------------------------------------------
# Structured error payload
# ---------------------------------------------------------------------------


@dataclass
class ErrorPayload:
    """A fully-structured, serialisable error payload.

    Instances are produced via :meth:`from_code` (preferred) or by direct
    construction.  They are designed to be embedded in API responses,
    audit logs, and inter-service messages.
    """

    error_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    code: str = ""
    description: str = ""
    domain: str = ""
    retryable: bool = False
    retryable_class: str = Retryable.NO.value
    severity: str = ErrorSeverity.ERROR.value
    message: str = ""
    detail: Optional[Dict[str, Any]] = None
    timestamp: float = field(default_factory=time.time)
    trace_id: str = ""
    task_id: str = ""

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_code(
        cls,
        code: GalaxyErrorCode,
        *,
        message: str = "",
        detail: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
        task_id: str = "",
    ) -> "ErrorPayload":
        """Create an ``ErrorPayload`` from a :class:`GalaxyErrorCode`."""
        reg = _registry()
        defn = reg.get(code.value)
        if defn is None:
            defn = _ErrorCodeDef(
                code.value, code.value,
                Retryable.CONDITIONAL, ErrorSeverity.ERROR, ErrorDomain.INTERNAL,
            )
        return cls(
            code=defn.code,
            description=defn.description,
            domain=defn.domain.value,
            retryable=defn.retryable in (Retryable.YES, Retryable.BACKOFF),
            retryable_class=defn.retryable.value,
            severity=defn.severity.value,
            message=message or defn.description,
            detail=detail,
            trace_id=trace_id,
            task_id=task_id,
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_id": self.error_id,
            "code": self.code,
            "description": self.description,
            "domain": self.domain,
            "retryable": self.retryable,
            "retryable_class": self.retryable_class,
            "severity": self.severity,
            "message": self.message,
            "detail": self.detail or {},
            "timestamp": self.timestamp,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ErrorPayload":
        return cls(
            error_id=data.get("error_id", str(uuid.uuid4())),
            code=data.get("code", ""),
            description=data.get("description", ""),
            domain=data.get("domain", ""),
            retryable=bool(data.get("retryable", False)),
            retryable_class=data.get("retryable_class", Retryable.NO.value),
            severity=data.get("severity", ErrorSeverity.ERROR.value),
            message=data.get("message", ""),
            detail=data.get("detail"),
            timestamp=float(data.get("timestamp", time.time())),
            trace_id=data.get("trace_id", ""),
            task_id=data.get("task_id", ""),
        )


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def is_retryable(code: GalaxyErrorCode) -> bool:
    """Return ``True`` if the error code is unconditionally or back-off retryable."""
    reg = _registry()
    defn = reg.get(code.value)
    if defn is None:
        return False
    return defn.retryable in (Retryable.YES, Retryable.BACKOFF)


def get_descriptor(code: GalaxyErrorCode) -> Optional[_ErrorCodeDef]:
    """Return the :class:`_ErrorCodeDef` for *code*, or ``None``."""
    return _registry().get(code.value)
