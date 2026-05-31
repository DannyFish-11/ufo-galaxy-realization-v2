#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/decision_diff_telemetry.py
================================
PR-14 — Decision-Diff Telemetry for Legacy vs Canonical Cross-Device Routing.

This module provides **observability-only** telemetry that records both the
legacy and canonical decision outputs at key cross-device routing and
scheduling decision points.  The telemetry is used during rollout to:

- Compare legacy vs canonical decisions side-by-side.
- Understand where and why decisions diverge.
- Identify whether the canonical logic is more accurate or merely stricter.

Design goals
------------
- **No behavior change** — the final decision selected for requests is
  *never* altered by this module.
- **Gated** — telemetry emission is controlled by
  ``GALAXY_DECISION_DIFF_TELEMETRY=1``.  The default is **off**.
- **Low overhead** — structured logs only; an optional in-memory ring buffer
  (capped at 256 entries by default) is available for test inspection.
- **Graceful degradation** — every subsystem call is wrapped; missing
  optional subsystems produce a ``diff_reason_code`` entry and continue.
- **Additive only** — no existing module is modified by importing this one.

Public API
----------
Models:
    DecisionDiffRecord

Helpers:
    record_entry_mode_diff(...)
    record_candidate_diff(...)
    get_diff_store()
    clear_diff_store()
    is_telemetry_enabled()

Authority sentinel:
    DECISION_DIFF_TELEMETRY_AUTHORITY

Reason codes (normalised strings emitted in ``diff_reason_codes``)
------------------------------------------------------------------
``legacy_used_online_presence``
    Legacy path counted UDM online devices; canonical path uses readiness.
``canonical_requires_readiness``
    Canonical path required the device to pass the full readiness gate.
``target_device_not_ready``
    The requested target device failed the canonical readiness check.
``target_device_not_eligible``
    The requested target device failed orchestration eligibility.
``capability_mismatch``
    One or more required capabilities are not matched by the candidate.
``insufficient_orchestration_ready_devices``
    Fewer candidates passed the orchestration gate than required.
``formation_unavailable``
    The formation/mesh layer returned no usable formation.
``session_unavailable``
    No active session was found for the candidate device.
``decisions_match``
    Legacy and canonical paths produced the same decision.
"""

from __future__ import annotations

import collections
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("Galaxy.DecisionDiffTelemetry")

__all__ = [
    "DecisionDiffRecord",
    "record_entry_mode_diff",
    "record_candidate_diff",
    "get_diff_store",
    "clear_diff_store",
    "is_telemetry_enabled",
    "DECISION_DIFF_TELEMETRY_AUTHORITY",
    # Reason-code constants
    "REASON_LEGACY_USED_ONLINE_PRESENCE",
    "REASON_CANONICAL_REQUIRES_READINESS",
    "REASON_TARGET_NOT_READY",
    "REASON_TARGET_NOT_ELIGIBLE",
    "REASON_CAPABILITY_MISMATCH",
    "REASON_INSUFFICIENT_ORCH_READY",
    "REASON_FORMATION_UNAVAILABLE",
    "REASON_SESSION_UNAVAILABLE",
    "REASON_DECISIONS_MATCH",
]

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

DECISION_DIFF_TELEMETRY_AUTHORITY = (
    "core.decision_diff_telemetry"
    " — decision-diff telemetry for legacy vs canonical routing (PR-14)"
)

# ---------------------------------------------------------------------------
# Reason-code constants
# ---------------------------------------------------------------------------

REASON_LEGACY_USED_ONLINE_PRESENCE = "legacy_used_online_presence"
REASON_CANONICAL_REQUIRES_READINESS = "canonical_requires_readiness"
REASON_TARGET_NOT_READY = "target_device_not_ready"
REASON_TARGET_NOT_ELIGIBLE = "target_device_not_eligible"
REASON_CAPABILITY_MISMATCH = "capability_mismatch"
REASON_INSUFFICIENT_ORCH_READY = "insufficient_orchestration_ready_devices"
REASON_FORMATION_UNAVAILABLE = "formation_unavailable"
REASON_SESSION_UNAVAILABLE = "session_unavailable"
REASON_DECISIONS_MATCH = "decisions_match"

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

_ENV_FLAG = "GALAXY_DECISION_DIFF_TELEMETRY"
_RING_BUFFER_SIZE = 256


def is_telemetry_enabled() -> bool:
    """Return ``True`` when decision-diff telemetry is active.

    Controlled by the ``GALAXY_DECISION_DIFF_TELEMETRY`` environment variable.
    Any value equal to ``"1"`` or ``"true"`` (case-insensitive) enables it.
    The default is **disabled**.
    """
    val = os.environ.get(_ENV_FLAG, "0").strip().lower()
    return val in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# DecisionDiffRecord
# ---------------------------------------------------------------------------


@dataclass
class DecisionDiffRecord:
    """Serialisable record capturing a single legacy-vs-canonical decision diff.

    All fields are optional so that partial records can be created when only
    some subsystems are available.

    Fields
    ------
    request_id
        End-to-end correlation / trace ID for the request.
    task_id
        Optional task identifier if a specific task is being routed.
    decision_point
        Short label identifying which decision point emitted this record,
        e.g. ``"entry_mode"``, ``"candidate_selection"``.
    requested_target_device
        The device ID explicitly requested by the caller, if any.
    legacy_decision
        The outcome the legacy path would have produced.
    canonical_decision
        The outcome the canonical path produced.
    legacy_selected_device_ids
        Device IDs the legacy path would have selected.
    canonical_selected_device_ids
        Device IDs the canonical path selected.
    ready_device_count
        Number of devices that passed the readiness gate.
    orchestration_ready_device_count
        Number of devices that passed the orchestration eligibility gate.
    required_capabilities
        Capability labels that were required for this request.
    diff_reason_codes
        Normalised reason codes explaining why legacy and canonical differ.
        Empty when the decisions match (``decisions_match`` is added instead).
    sources
        Arbitrary key/value pairs capturing subsystem names or version labels
        for auditability.
    timestamp
        Unix timestamp (float) when the record was created.
    """

    request_id: Optional[str] = None
    task_id: Optional[str] = None
    decision_point: str = "unknown"
    requested_target_device: Optional[str] = None
    legacy_decision: Optional[str] = None
    canonical_decision: Optional[str] = None
    legacy_selected_device_ids: List[str] = field(default_factory=list)
    canonical_selected_device_ids: List[str] = field(default_factory=list)
    ready_device_count: Optional[int] = None
    orchestration_ready_device_count: Optional[int] = None
    required_capabilities: List[str] = field(default_factory=list)
    diff_reason_codes: List[str] = field(default_factory=list)
    sources: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def decisions_differ(self) -> bool:
        """``True`` when legacy and canonical decisions are not identical."""
        return self.legacy_decision != self.canonical_decision

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "request_id": self.request_id,
            "task_id": self.task_id,
            "decision_point": self.decision_point,
            "requested_target_device": self.requested_target_device,
            "legacy_decision": self.legacy_decision,
            "canonical_decision": self.canonical_decision,
            "legacy_selected_device_ids": list(self.legacy_selected_device_ids),
            "canonical_selected_device_ids": list(self.canonical_selected_device_ids),
            "ready_device_count": self.ready_device_count,
            "orchestration_ready_device_count": self.orchestration_ready_device_count,
            "required_capabilities": list(self.required_capabilities),
            "diff_reason_codes": list(self.diff_reason_codes),
            "sources": dict(self.sources),
            "timestamp": self.timestamp,
            "decisions_differ": self.decisions_differ,
        }


# ---------------------------------------------------------------------------
# In-memory ring buffer
# ---------------------------------------------------------------------------

_diff_store: Deque[DecisionDiffRecord] = collections.deque(maxlen=_RING_BUFFER_SIZE)


def get_diff_store() -> List[DecisionDiffRecord]:
    """Return a snapshot list of all records currently in the ring buffer."""
    return list(_diff_store)


def clear_diff_store() -> None:
    """Clear all records from the in-memory ring buffer (for testing)."""
    _diff_store.clear()


# ---------------------------------------------------------------------------
# Internal helper: emit a record
# ---------------------------------------------------------------------------


def _emit_record(record: DecisionDiffRecord) -> None:
    """Append *record* to the ring buffer and emit a structured log entry."""
    _diff_store.append(record)

    log_level = logging.WARNING if record.decisions_differ else logging.DEBUG
    logger.log(
        log_level,
        "decision_diff decision_point=%s request_id=%s "
        "legacy=%s canonical=%s diff=%s reason_codes=%s",
        record.decision_point,
        record.request_id or "",
        record.legacy_decision or "?",
        record.canonical_decision or "?",
        record.decisions_differ,
        ",".join(record.diff_reason_codes) or "-",
    )

    # Best-effort: forward to state event bus
    try:
        from core.state_event_bus import emit as _seb_emit, StateEventType
        _seb_emit(
            StateEventType.GENERIC,
            source="decision_diff_telemetry",
            payload={
                "event_kind": "decision_diff",
                **record.to_dict(),
            },
            trace_id=record.request_id or "",
        )
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)


# ---------------------------------------------------------------------------
# Public helper: entry-mode diff
# ---------------------------------------------------------------------------


def record_entry_mode_diff(
    *,
    request_id: Optional[str] = None,
    target_device: Optional[str] = None,
    legacy_decision: Optional[str] = None,
    canonical_decision: Optional[str] = None,
    ready_device_count: Optional[int] = None,
    online_device_count: Optional[int] = None,
    diff_reason_codes: Optional[List[str]] = None,
    sources: Optional[Dict[str, Any]] = None,
) -> Optional[DecisionDiffRecord]:
    """Record an entry-mode legacy-vs-canonical decision diff.

    This is the primary telemetry hook for
    :func:`core.unified.entrypoint_router.resolve_entry_mode`.  It is safe
    to call at any time; when telemetry is disabled it returns ``None``
    immediately without any side effects.

    Parameters
    ----------
    request_id:
        End-to-end trace/correlation ID.
    target_device:
        Explicit target device from the request, if any.
    legacy_decision:
        Entry mode resolved by the legacy path (e.g. ``"local"`` or
        ``"cross_device"``).
    canonical_decision:
        Entry mode resolved by the canonical (readiness-based) path.
    ready_device_count:
        Number of devices that passed the canonical readiness gate.
    online_device_count:
        Number of devices that the legacy UDM online-count heuristic saw.
    diff_reason_codes:
        Explicit reason codes to attach.  Auto-populated when not provided.
    sources:
        Subsystem labels for auditability.

    Returns
    -------
    DecisionDiffRecord | None
        The emitted record, or ``None`` when telemetry is disabled.
    """
    if not is_telemetry_enabled():
        return None

    try:
        reasons: List[str] = list(diff_reason_codes or [])

        if legacy_decision != canonical_decision:
            if not reasons:
                reasons.append(REASON_LEGACY_USED_ONLINE_PRESENCE)
                reasons.append(REASON_CANONICAL_REQUIRES_READINESS)
                if target_device:
                    reasons.append(REASON_TARGET_NOT_READY)
        else:
            if not reasons:
                reasons.append(REASON_DECISIONS_MATCH)

        extra_sources: Dict[str, Any] = dict(sources or {})
        extra_sources.setdefault("layer", "entry_mode_resolution")
        if online_device_count is not None:
            extra_sources["legacy_online_device_count"] = online_device_count

        record = DecisionDiffRecord(
            request_id=request_id,
            decision_point="entry_mode",
            requested_target_device=target_device,
            legacy_decision=legacy_decision,
            canonical_decision=canonical_decision,
            ready_device_count=ready_device_count,
            diff_reason_codes=reasons,
            sources=extra_sources,
        )
        _emit_record(record)
        return record
    except Exception:
        logger.debug(
            "decision_diff_telemetry.record_entry_mode_diff: suppressed exception",
            exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# Public helper: candidate selection diff
# ---------------------------------------------------------------------------


def record_candidate_diff(
    *,
    request_id: Optional[str] = None,
    task_id: Optional[str] = None,
    target_device: Optional[str] = None,
    legacy_decision: Optional[str] = None,
    canonical_decision: Optional[str] = None,
    legacy_selected_device_ids: Optional[List[str]] = None,
    canonical_selected_device_ids: Optional[List[str]] = None,
    ready_device_count: Optional[int] = None,
    orchestration_ready_device_count: Optional[int] = None,
    required_capabilities: Optional[List[str]] = None,
    diff_reason_codes: Optional[List[str]] = None,
    sources: Optional[Dict[str, Any]] = None,
) -> Optional[DecisionDiffRecord]:
    """Record a cross-device candidate selection legacy-vs-canonical diff.

    Used at the candidate resolution / orchestration gating decision point.
    Safe to call at any time; returns ``None`` when telemetry is disabled.

    Parameters
    ----------
    request_id:
        End-to-end trace/correlation ID.
    task_id:
        Optional task identifier.
    target_device:
        Explicit target device, if any.
    legacy_decision:
        Selection outcome produced by the legacy path.
    canonical_decision:
        Selection outcome produced by the canonical path.
    legacy_selected_device_ids:
        Devices the legacy path would have used.
    canonical_selected_device_ids:
        Devices the canonical path selected.
    ready_device_count:
        Devices that passed the readiness gate.
    orchestration_ready_device_count:
        Devices that passed the orchestration eligibility gate.
    required_capabilities:
        Capability labels required for this request.
    diff_reason_codes:
        Explicit reason codes.  Auto-populated when not provided.
    sources:
        Subsystem labels for auditability.

    Returns
    -------
    DecisionDiffRecord | None
    """
    if not is_telemetry_enabled():
        return None

    try:
        legacy_ids = list(legacy_selected_device_ids or [])
        canonical_ids = list(canonical_selected_device_ids or [])
        reasons: List[str] = list(diff_reason_codes or [])

        if legacy_decision != canonical_decision or set(legacy_ids) != set(canonical_ids):
            if not reasons:
                reasons.append(REASON_CANONICAL_REQUIRES_READINESS)
                if required_capabilities:
                    reasons.append(REASON_CAPABILITY_MISMATCH)
                if (
                    orchestration_ready_device_count is not None
                    and orchestration_ready_device_count < 2
                ):
                    reasons.append(REASON_INSUFFICIENT_ORCH_READY)
                if target_device:
                    reasons.append(REASON_TARGET_NOT_ELIGIBLE)
        else:
            if not reasons:
                reasons.append(REASON_DECISIONS_MATCH)

        extra_sources: Dict[str, Any] = dict(sources or {})
        extra_sources.setdefault("layer", "candidate_resolution")

        record = DecisionDiffRecord(
            request_id=request_id,
            task_id=task_id,
            decision_point="candidate_selection",
            requested_target_device=target_device,
            legacy_decision=legacy_decision,
            canonical_decision=canonical_decision,
            legacy_selected_device_ids=legacy_ids,
            canonical_selected_device_ids=canonical_ids,
            ready_device_count=ready_device_count,
            orchestration_ready_device_count=orchestration_ready_device_count,
            required_capabilities=list(required_capabilities or []),
            diff_reason_codes=reasons,
            sources=extra_sources,
        )
        _emit_record(record)
        return record
    except Exception:
        logger.debug(
            "decision_diff_telemetry.record_candidate_diff: suppressed exception",
            exc_info=True,
        )
        return None
