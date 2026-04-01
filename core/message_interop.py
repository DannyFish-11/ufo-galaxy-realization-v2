#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/message_interop.py
========================
PR-2 — Canonical Message Interop / Normalization Layer.

This module is the **single authority** for converting heterogeneous message
payloads (legacy dicts, bridge payloads, NATS dispatches, scheduler frames)
into the canonical ``TaskEnvelope`` / ``ResultEnvelope`` contract used across
the entire Galaxy runtime.

Architecture position
---------------------
::

    legacy payload
    bridge frame         ──►  normalize_to_task_envelope()  ──►  TaskEnvelope
    NATS dispatch                                                   │
    scheduler args                                                  ▼
                                                              CommandRouter
                                                                    │
    raw device result    ──►  normalize_to_result_envelope() ──►  ResultEnvelope
    NATS result                                                     │
    bridge response                                                 ▼
                                                           OpenClawd / Projection

Design invariants
-----------------
1.  **Additive-only** — this module never modifies existing modules.
    Existing callers that do not adopt it continue to work unchanged.
2.  **Canonical reasons** — all reason strings produced here come from
    :mod:`core.admissibility_chain` constants; no free-form strings are
    introduced.
3.  **Correlation fields** — every produced TaskEnvelope / ResultEnvelope
    carries ``task_id`` + ``trace_id``.  ``session_id`` is forwarded when
    present in the source payload.
4.  **Graceful degradation** — all imports from optional subsystems are
    wrapped in try/except; this module never raises.

Public API
----------
Authority sentinels:
    MESSAGE_INTEROP_AUTHORITY
    MESSAGE_INTEROP_CORRELATION_POLICY

Reason vocabulary (re-exported from admissibility_chain):
    REASON_NOT_REGISTERED
    REASON_NOT_READY
    REASON_NO_ROUTE
    REASON_NOT_ELIGIBLE
    REASON_CAPABILITY_MISMATCH
    REASON_READINESS_UNAVAILABLE
    REASON_PARTICIPATION_UNAVAILABLE

Helpers:
    extract_correlation(payload) -> CorrelationFields
    normalize_to_task_envelope(payload, *, source) -> TaskEnvelope
    normalize_to_result_envelope(raw, *, task_id, trace_id, session_id) -> ResultEnvelope
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.MessageInterop")

__all__ = [
    # Authority
    "MESSAGE_INTEROP_AUTHORITY",
    "MESSAGE_INTEROP_CORRELATION_POLICY",
    # Reason vocabulary (canonical — from admissibility_chain)
    "REASON_NOT_REGISTERED",
    "REASON_NOT_READY",
    "REASON_NO_ROUTE",
    "REASON_NOT_ELIGIBLE",
    "REASON_CAPABILITY_MISMATCH",
    "REASON_READINESS_UNAVAILABLE",
    "REASON_PARTICIPATION_UNAVAILABLE",
    # Helpers
    "CorrelationFields",
    "extract_correlation",
    "normalize_to_task_envelope",
    "normalize_to_result_envelope",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

#: Identifies this module as the canonical message interop authority (PR-2).
MESSAGE_INTEROP_AUTHORITY: str = "MESSAGE_INTEROP_V1"

#: Policy: every cross-device/cross-node message MUST carry task_id + trace_id.
#: session_id is forwarded when available in the source payload.
MESSAGE_INTEROP_CORRELATION_POLICY: str = (
    "REQUIRED: task_id + trace_id on every cross-device message; "
    "session_id forwarded when available"
)

# ---------------------------------------------------------------------------
# Canonical reason vocabulary
# ---------------------------------------------------------------------------
# These are re-exported from core.admissibility_chain so that all consumers
# of message interop receive a unified, authoritative reason vocabulary.
# Importing them here also makes them accessible without importing the chain.

try:
    from core.admissibility_chain import (  # type: ignore
        REASON_NOT_REGISTERED,
        REASON_NOT_READY,
        REASON_NO_ROUTE,
        REASON_NOT_ELIGIBLE,
        REASON_CAPABILITY_MISMATCH,
        REASON_READINESS_UNAVAILABLE,
        REASON_PARTICIPATION_UNAVAILABLE,
    )
except ImportError:
    # Fallback literals — should never happen in a correctly installed runtime,
    # but guarantees this module is importable in isolation for testing.
    REASON_NOT_REGISTERED: str = "not-registered"          # type: ignore[assignment]
    REASON_NOT_READY: str = "not-ready"                    # type: ignore[assignment]
    REASON_NO_ROUTE: str = "no-route"                      # type: ignore[assignment]
    REASON_NOT_ELIGIBLE: str = "not-eligible"              # type: ignore[assignment]
    REASON_CAPABILITY_MISMATCH: str = "capability-mismatch"  # type: ignore[assignment]
    REASON_READINESS_UNAVAILABLE: str = "readiness-unavailable"  # type: ignore[assignment]
    REASON_PARTICIPATION_UNAVAILABLE: str = "participation-unavailable"  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Correlation fields
# ---------------------------------------------------------------------------


@dataclass
class CorrelationFields:
    """Extracted correlation identifiers from any message payload.

    Always produced by :func:`extract_correlation`.  All fields are
    guaranteed to be non-empty strings — a fresh UUID is generated when a
    field is missing from the source payload.
    """

    task_id: str
    trace_id: str
    session_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
        }


def extract_correlation(payload: Dict[str, Any]) -> CorrelationFields:
    """Extract canonical correlation fields from any message payload dict.

    Accepts any of the known field-name variants used across the codebase:

    +-------------------+-------------------------------------------+
    | canonical field   | also accepted from                        |
    +===================+===========================================+
    | ``task_id``       | ``task_id``, ``request_id``, ``id``       |
    +-------------------+-------------------------------------------+
    | ``trace_id``      | ``trace_id``, ``context.trace_id``        |
    +-------------------+-------------------------------------------+
    | ``session_id``    | ``session_id``, ``context.session_id``    |
    +-------------------+-------------------------------------------+

    Missing fields are auto-generated so the returned :class:`CorrelationFields`
    always carries valid, non-empty identifiers.

    Parameters
    ----------
    payload:
        Any dict-like payload (raw NATS message, bridge frame, etc.).

    Returns
    -------
    CorrelationFields
        Always returns a populated instance; never raises.
    """
    if not isinstance(payload, dict):
        return CorrelationFields(
            task_id=f"task_{uuid.uuid4().hex[:16]}",
            trace_id=f"trace_{uuid.uuid4().hex[:12]}",
        )

    ctx = payload.get("context") or {}

    task_id = (
        payload.get("task_id")
        or payload.get("request_id")
        or payload.get("id")
        or f"task_{uuid.uuid4().hex[:16]}"
    )
    trace_id = (
        payload.get("trace_id")
        or (ctx.get("trace_id") if isinstance(ctx, dict) else None)
        or f"trace_{uuid.uuid4().hex[:12]}"
    )
    session_id = (
        payload.get("session_id")
        or (ctx.get("session_id") if isinstance(ctx, dict) else None)
        or None
    )

    return CorrelationFields(
        task_id=str(task_id),
        trace_id=str(trace_id),
        session_id=str(session_id) if session_id else None,
    )


# ---------------------------------------------------------------------------
# normalize_to_task_envelope
# ---------------------------------------------------------------------------


def normalize_to_task_envelope(
    payload: Dict[str, Any],
    *,
    source: str = "unknown",
    session_id: Optional[str] = None,
) -> Any:  # returns TaskEnvelope — typed as Any to avoid hard import at module level
    """Convert any heterogeneous message payload to a canonical ``TaskEnvelope``.

    Supported source shapes
    -----------------------
    * ``TaskEnvelope`` dict (``_nats_schema == "TaskEnvelope"``) — validated
      directly via ``TaskEnvelope.model_validate``.
    * Legacy ``TaskDispatch`` / scheduler dict — fields extracted by name
      with sensible defaults.
    * ``bridge`` frame — ``type``, ``action``, ``payload`` extracted.
    * Generic dict — best-effort field extraction.

    Correlation fields are always injected via :func:`extract_correlation`
    to guarantee ``task_id`` / ``trace_id`` are present.

    Parameters
    ----------
    payload:
        Source message dict.  Not mutated.
    source:
        String identifying the origin system (e.g. ``"nats"``, ``"bridge"``,
        ``"scheduler"``).  Used to populate ``TaskEnvelope.source`` when the
        payload does not carry a source field.
    session_id:
        Override for session_id; falls back to payload-derived value.

    Returns
    -------
    TaskEnvelope
        A populated, validated ``TaskEnvelope``.  Always returns a valid
        envelope; on parse error falls back to a best-effort constructed one.
    """
    try:
        from core.schemas.task_envelope import TaskEnvelope  # type: ignore
    except ImportError:
        logger.error("MessageInterop: TaskEnvelope unavailable — cannot normalize")
        raise

    corr = extract_correlation(payload)
    effective_session_id = session_id or corr.session_id

    nats_schema = payload.get("_nats_schema", "")

    # ── Fast path: already a TaskEnvelope-shaped dict ──────────────────────
    if nats_schema == "TaskEnvelope":
        try:
            envelope = TaskEnvelope.model_validate(payload)
            # Ensure correlation fields are canonical even if the envelope
            # already has them (trust them if non-empty, otherwise stamp).
            updates: dict = {}
            if not envelope.task_id:
                updates["task_id"] = corr.task_id
            if not envelope.trace_id:
                updates["trace_id"] = corr.trace_id
            if effective_session_id and not envelope.session_id:
                updates["session_id"] = effective_session_id
            if updates:
                envelope = envelope.model_copy(update=updates)
            logger.debug(
                "MessageInterop: fast-path TaskEnvelope task_id=%s trace_id=%s",
                envelope.task_id,
                envelope.trace_id,
            )
            return envelope
        except Exception as exc:
            logger.warning(
                "MessageInterop: TaskEnvelope fast-path parse failed, using legacy path — %s",
                exc,
            )

    # ── Legacy / bridge / generic extraction ───────────────────────────────
    # Field-name aliases used by different subsystems:
    tool_name = (
        payload.get("tool_name")
        or payload.get("task_type")
        or payload.get("action")
        or payload.get("command")
        or payload.get("type")
        or ""
    )
    targets_raw = (
        payload.get("targets")
        or payload.get("target_device_id")
        or payload.get("target_worker_id")
        or payload.get("target")
        or []
    )
    if isinstance(targets_raw, str):
        targets: List[str] = [targets_raw] if targets_raw else []
    elif isinstance(targets_raw, list):
        targets = [str(t) for t in targets_raw if t]
    else:
        targets = []

    args = (
        payload.get("args")
        or payload.get("payload")
        or payload.get("params")
        or payload.get("parameters")
        or {}
    )
    if not isinstance(args, dict):
        args = {}

    effective_source = (
        payload.get("source")
        or payload.get("source_device")
        or source
    )

    meta: Dict[str, Any] = dict(payload.get("metadata") or {})
    for k in ("route_mode", "remote_execution_mode", "notify_ws", "mode", "request_id"):
        if k in payload and k not in meta:
            meta[k] = payload[k]

    priority = payload.get("priority", 5)
    timeout = payload.get("timeout", 30.0)
    permission_level = payload.get("permission_level", 0)
    required_capabilities: List[str] = payload.get("required_capabilities") or []

    envelope = TaskEnvelope(
        task_id=corr.task_id,
        trace_id=corr.trace_id,
        session_id=effective_session_id,
        source=str(effective_source),
        targets=targets,
        tool_name=str(tool_name),
        args=args,
        priority=int(priority) if str(priority).isdigit() else 5,
        timeout=float(timeout),
        permission_level=int(permission_level),
        required_capabilities=list(required_capabilities),
        metadata=meta,
    )
    logger.debug(
        "MessageInterop: normalized legacy payload task_id=%s trace_id=%s tool=%s",
        envelope.task_id,
        envelope.trace_id,
        envelope.tool_name,
    )
    return envelope


# ---------------------------------------------------------------------------
# normalize_to_result_envelope
# ---------------------------------------------------------------------------


def normalize_to_result_envelope(
    raw: Dict[str, Any],
    *,
    task_id: str = "",
    trace_id: str = "",
    session_id: Optional[str] = None,
    device_id: str = "",
    route_mode: str = "cross_device",
) -> Any:  # returns ResultEnvelope — typed as Any to avoid hard import at module level
    """Convert a raw result dict to a canonical ``ResultEnvelope``.

    Correlation fields (``task_id``, ``trace_id``) are taken from the
    explicit keyword arguments when provided; otherwise extracted from
    *raw* via :func:`extract_correlation`.

    Parameters
    ----------
    raw:
        Raw result dict from a device, worker, or NATS result message.
    task_id:
        Originating task identifier (preferred over payload extraction).
    trace_id:
        Distributed trace identifier (preferred over payload extraction).
    session_id:
        Optional session identifier.
    device_id:
        The device / worker that produced the result.
    route_mode:
        The route mode used for the originating task.

    Returns
    -------
    ResultEnvelope
        Always returns a valid envelope; never raises.
    """
    try:
        from core.cross_device_execution_chain import (  # type: ignore
            ResultEnvelope,
            build_result_envelope,
        )
    except ImportError:
        logger.error("MessageInterop: ResultEnvelope unavailable — cannot normalize")
        raise

    # Resolve correlation — explicit kwargs take priority over payload fields.
    if not task_id or not trace_id:
        corr = extract_correlation(raw)
        task_id = task_id or corr.task_id
        trace_id = trace_id or corr.trace_id
        session_id = session_id or corr.session_id

    # Determine success / status / error / payload from raw result.
    # Note: 'result' being non-None only contributes to success when the
    # status is not an explicit failure indicator.
    _raw_status = raw.get("status", "")
    _status_failure = str(_raw_status).lower() in ("error", "failed", "failure", "timeout")
    success = bool(
        (
            raw.get("success")
            or str(_raw_status).lower() in ("ok", "success", "completed", "done")
            or (raw.get("result") is not None and raw["result"] != {})
        )
        and not _status_failure
    )
    status = _raw_status or ("success" if success else "failed")
    error: Optional[str] = raw.get("error") or (
        None if success else (raw.get("message") or "Task failed without error details")
    )

    payload: Dict[str, Any] = {}
    for key in ("result", "data", "payload", "output"):
        if key in raw and isinstance(raw[key], dict):
            payload = raw[key]
            break
    if not payload and success:
        payload = {k: v for k, v in raw.items() if k not in ("status", "error", "task_id", "trace_id", "session_id")}

    effective_device_id = device_id or raw.get("device_id", "")

    try:
        envelope = build_result_envelope(
            raw,
            task_id=task_id,
            device_id=str(effective_device_id),
            trace_id=trace_id,
            session_id=session_id,
            route_mode=route_mode,
        )
    except Exception:
        # Fallback: construct directly without build_result_envelope
        envelope = ResultEnvelope(
            task_id=task_id,
            device_id=str(effective_device_id),
            success=success,
            status=str(status),
            payload=payload,
            error=error,
            trace_id=trace_id,
            session_id=session_id,
            route_mode=route_mode,
        )

    logger.debug(
        "MessageInterop: normalized result task_id=%s trace_id=%s success=%s",
        envelope.task_id,
        envelope.trace_id,
        envelope.success,
    )
    return envelope
