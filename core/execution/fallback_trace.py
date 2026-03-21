"""core/execution/fallback_trace.py
=====================================
FallbackDecisionTrace — canonical fallback decision trace layer for Galaxy.

PR-24: Fallback Decision Trace

This module introduces the **FallbackDecisionTrace**: a serialisable, wire-safe
object that captures *why* execution fell back from a primary path and *which*
fallback path was selected, enabling the fallback behaviour to be explicit,
inspectable, and governable.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **No breaking API changes** — fully backward-compatible.
- **Fully serialisable** — :meth:`FallbackDecisionTrace.to_dict` and
  :meth:`FallbackDecisionTrace.to_json` produce stable, round-trippable output.
- **Graceful defaults** — all fields beyond the minimal required set are optional
  and carry safe defaults so callers with partial metadata can always build
  a valid trace.
- **Tolerant of missing metadata** — every builder function catches exceptions
  and degrades gracefully; never raises to the caller.

Usage::

    from core.execution.fallback_trace import (
        build_fallback_trace,
        summarize_fallback_trace,
    )

    trace = build_fallback_trace(
        intent_profile=profile,
        readiness_result=readiness,
        execution_result=exec_result,
    )
    payload = trace.to_dict()
    summary = summarize_fallback_trace(trace)

See ``docs/FALLBACK_DECISION_TRACE.md`` for the full specification.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# FallbackOutcome — canonical outcome vocabulary
# ---------------------------------------------------------------------------


class FallbackOutcome(str, Enum):
    """Canonical outcome of a fallback decision.

    selected
        A fallback path was identified and selected; execution proceeded on the
        fallback path.
    blocked
        Execution was fully blocked — neither the primary path nor any fallback
        path was available (e.g. policy denial with no viable alternative).
    noop
        No execution was attempted; the action level or policy permitted only
        an observe/hint response.  This is a benign, expected outcome.
    degraded
        Execution proceeded, but at a reduced capability level compared to the
        originally intended path.
    failed
        The selected fallback path was attempted but ultimately failed.
    """

    SELECTED = "selected"
    BLOCKED = "blocked"
    NOOP = "noop"
    DEGRADED = "degraded"
    FAILED = "failed"

    @classmethod
    def from_string(cls, value: str) -> "FallbackOutcome":
        """Return the matching member, falling back to ``BLOCKED`` on unknown input."""
        normalised = (value or "").strip().lower()
        for member in cls:
            if member.value == normalised:
                return member
        return cls.BLOCKED


# ---------------------------------------------------------------------------
# FallbackDecisionSource — who made the fallback decision
# ---------------------------------------------------------------------------


class FallbackDecisionSource(str, Enum):
    """Identifies which component authored the fallback decision.

    policy
        The execution-policy layer (PolicyBand / PolicyResolver) determined
        that the primary path was not permitted.
    readiness_gate
        The Execution Readiness Gate (PR-23) blocked the primary path due to
        readiness failure (missing target, HITL requirement, domain mismatch,
        …).
    runtime
        Runtime signals (tri-state phase, runtime domain, continuum state)
        caused the primary path to be unavailable.
    bridge
        The bridge / remote-handoff layer (e.g. cross-device dispatch) fell
        back to a local path because the remote target was unavailable.
    executor
        An executor-level failure (UIA unavailable, no system API match, VLM
        confidence low, …) triggered the fallback.
    unknown
        Decision source could not be determined from available context.
    """

    POLICY = "policy"
    READINESS_GATE = "readiness_gate"
    RUNTIME = "runtime"
    BRIDGE = "bridge"
    EXECUTOR = "executor"
    UNKNOWN = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "FallbackDecisionSource":
        """Return the matching member, falling back to ``UNKNOWN``."""
        normalised = (value or "").strip().lower()
        for member in cls:
            if member.value == normalised:
                return member
        return cls.UNKNOWN


# ---------------------------------------------------------------------------
# FallbackCandidate — a single path considered during fallback selection
# ---------------------------------------------------------------------------


@dataclass
class FallbackCandidate:
    """A single execution path considered during fallback selection.

    Attributes
    ----------
    path:
        Human-readable name or identifier of this candidate path
        (e.g. ``"local_executor"``, ``"remote_executor"``,
        ``"system_api"``, ``"noop"``).
    executor_level:
        The executor tier this candidate corresponds to (optional).
    reason_blocked:
        Why this candidate was not selected, or ``None`` if it *was* selected.
    evaluated:
        ``True`` when this candidate was actually evaluated by the gate/
        policy layer.  ``False`` means it was skipped without evaluation.
    selected:
        ``True`` when this candidate was the final chosen fallback path.
    metadata:
        Arbitrary additional context (e.g. error message, capability flags).
    """

    path: str = "unknown"
    executor_level: Optional[str] = None
    reason_blocked: Optional[str] = None
    evaluated: bool = True
    selected: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "path": self.path,
            "executor_level": self.executor_level,
            "reason_blocked": self.reason_blocked,
            "evaluated": self.evaluated,
            "selected": self.selected,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FallbackCandidate":
        """Reconstruct a :class:`FallbackCandidate` from a dict."""
        return cls(
            path=data.get("path", "unknown"),
            executor_level=data.get("executor_level"),
            reason_blocked=data.get("reason_blocked"),
            evaluated=bool(data.get("evaluated", True)),
            selected=bool(data.get("selected", False)),
            metadata=dict(data.get("metadata") or {}),
        )


# ---------------------------------------------------------------------------
# FallbackDecisionTrace — canonical fallback decision record
# ---------------------------------------------------------------------------


class FallbackDecisionTrace(BaseModel):
    """Canonical, wire-safe fallback decision trace record.

    Captures the full context of a single fallback decision event: what was
    attempted, why the primary path was not taken, which fallback path was
    selected, and what the final outcome was.

    Fields
    ------
    trace_id
        Unique identifier for this fallback trace record (UUID4).
    runtime_session_id
        Identifier of the active runtime/OpenClawd session.  ``None`` when
        not available.
    intent_id
        Identifier of the :class:`~core.execution.intent_profile.ExecutionIntentProfile`
        that originated this execution attempt.  ``None`` when unavailable.
    action_level
        Graduated action level from the Decision Gate
        (``"observe"`` / ``"hint"`` / ``"assist"`` / ``"execute"``).
    primary_path
        Description of the execution path that was originally attempted
        (e.g. ``"local_executor"``, ``"system_api"``, ``"cross_device"``).
        ``None`` when no primary path was established.
    primary_block_reason
        Human-readable explanation of why the primary path was not taken.
        ``None`` when the primary path was not blocked (i.e. a degraded
        path was taken voluntarily).
    fallback_path
        Description of the fallback path that was selected
        (e.g. ``"noop"``, ``"local_fallback"``, ``"degraded_assist"``).
        ``None`` when no fallback was available.
    fallback_reason
        Human-readable explanation of the fallback selection.
    decision_source
        Which component made the fallback decision (``FallbackDecisionSource``
        value string: ``"policy"``, ``"readiness_gate"``, ``"runtime"``,
        ``"bridge"``, ``"executor"``, ``"unknown"``).
    candidate_paths
        Optional ordered list of :class:`FallbackCandidate` dicts — all paths
        considered during fallback selection, including the one selected.
    outcome
        Final outcome of the fallback decision (``FallbackOutcome`` value
        string: ``"selected"``, ``"blocked"``, ``"noop"``, ``"degraded"``,
        ``"failed"``).
    notes
        Optional human-readable notes or debug context.
    timestamp
        Unix timestamp (seconds since epoch) when this trace was created.
    """

    trace_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this fallback trace record.",
    )
    runtime_session_id: Optional[str] = Field(
        default=None,
        description="Active runtime / OpenClawd session ID.",
    )
    intent_id: Optional[str] = Field(
        default=None,
        description="ExecutionIntentProfile ID that originated this execution attempt.",
    )
    action_level: str = Field(
        default="observe",
        description="Graduated action level from the Decision Gate.",
    )
    primary_path: Optional[str] = Field(
        default=None,
        description="Execution path that was originally attempted.",
    )
    primary_block_reason: Optional[str] = Field(
        default=None,
        description="Why the primary path was not taken.",
    )
    fallback_path: Optional[str] = Field(
        default=None,
        description="Fallback path that was selected.",
    )
    fallback_reason: Optional[str] = Field(
        default=None,
        description="Explanation of the fallback selection.",
    )
    decision_source: str = Field(
        default=FallbackDecisionSource.UNKNOWN.value,
        description=(
            "Which component made the fallback decision "
            "(policy / readiness_gate / runtime / bridge / executor / unknown)."
        ),
    )
    candidate_paths: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="All paths considered during fallback selection.",
    )
    outcome: str = Field(
        default=FallbackOutcome.BLOCKED.value,
        description=(
            "Final outcome of the fallback decision "
            "(selected / blocked / noop / degraded / failed)."
        ),
    )
    notes: Optional[str] = Field(
        default=None,
        description="Optional human-readable notes or debug context.",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix timestamp when this trace was created.",
    )

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation of this trace."""
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        """Return a compact JSON string representation of this trace."""
        return json.dumps(self.to_dict(), **kwargs)

    # ------------------------------------------------------------------
    # Compact summary
    # ------------------------------------------------------------------

    def compact_summary(self) -> Dict[str, Any]:
        """Return a compact, governance-safe summary of key trace fields.

        Suitable for inclusion in governance surfaces, projection enrichment,
        or debug logging without bloating the full schema.
        """
        return {
            "trace_id": self.trace_id,
            "intent_id": self.intent_id,
            "action_level": self.action_level,
            "primary_path": self.primary_path,
            "primary_block_reason": self.primary_block_reason,
            "fallback_path": self.fallback_path,
            "decision_source": self.decision_source,
            "outcome": self.outcome,
        }


# ---------------------------------------------------------------------------
# FallbackDecisionResult — wraps trace + outcome for consumers
# ---------------------------------------------------------------------------


class FallbackDecisionResult(BaseModel):
    """Wraps a :class:`FallbackDecisionTrace` together with a resolved outcome.

    Intended as the return type of :func:`build_fallback_trace` so that
    callers can access both the full trace and a top-level outcome without
    unpacking the trace themselves.

    Fields
    ------
    trace
        The full :class:`FallbackDecisionTrace` record (as a dict).
    outcome
        The resolved :class:`FallbackOutcome` value (string).
    has_fallback
        ``True`` when a fallback path was selected (outcome == ``"selected"``
        or ``"degraded"``).
    """

    trace: Dict[str, Any] = Field(
        default_factory=dict,
        description="Full FallbackDecisionTrace as a serialisable dict.",
    )
    outcome: str = Field(
        default=FallbackOutcome.BLOCKED.value,
        description="Resolved fallback outcome value.",
    )
    has_fallback: bool = Field(
        default=False,
        description="True when a fallback path was selected.",
    )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        """Return a compact JSON string representation."""
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# Module-level builder (preferred public API)
# ---------------------------------------------------------------------------


def build_fallback_trace(
    intent_profile: Optional[Any] = None,
    readiness_result: Optional[Any] = None,
    execution_result: Optional[Dict[str, Any]] = None,
    *,
    runtime_session_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> FallbackDecisionTrace:
    """Build a :class:`FallbackDecisionTrace` from available execution signals.

    This is the **preferred entry-point** for constructing a fallback trace.
    It derives fallback decisions from existing repository conditions:

    * Readiness gate failure or partial readiness (PR-23 ``ReadinessResult``)
    * Policy denial / confirmation requirement
    * Missing target / unsupported domain
    * Unavailable executor (skipped_reason from ``execution_result``)
    * Runtime-domain mismatch
    * Degraded / no-op execution cases

    Parameters
    ----------
    intent_profile:
        An :class:`~core.execution.intent_profile.ExecutionIntentProfile`
        (or any object with ``intent_id``, ``action_level``,
        ``runtime_session_id``, ``runtime_domain`` attributes).
        ``None`` is safe — the trace will carry minimal fields.
    readiness_result:
        A :class:`~core.execution.readiness_gate.ReadinessResult` (or any
        object with ``ready``, ``status``, ``blocked_by``, ``reason``
        attributes).  ``None`` is safe.
    execution_result:
        Serialised dict returned by
        :meth:`~core.openclawd.OpenClawd._run_execution`.  Used to derive
        the executor-level fallback reason and outcome.  ``None`` is safe.
    runtime_session_id:
        Explicit session ID to stamp on the trace.  Overrides the value
        extracted from *intent_profile* when provided.
    notes:
        Optional debug/context note to attach.

    Returns
    -------
    FallbackDecisionTrace
        Always returns a valid trace; never raises.
    """
    try:
        return _build_trace(
            intent_profile=intent_profile,
            readiness_result=readiness_result,
            execution_result=execution_result,
            runtime_session_id=runtime_session_id,
            notes=notes,
        )
    except Exception:
        # Last-resort fallback — return a minimal, safe trace
        return FallbackDecisionTrace(
            runtime_session_id=runtime_session_id,
            notes=notes,
        )


def summarize_fallback_trace(trace: FallbackDecisionTrace) -> Dict[str, Any]:
    """Return a compact, governance-safe summary of *trace*.

    This is the **preferred hook** for later projection/governance consumers
    so they can enrich their surfaces with fallback state without re-deriving
    it from raw signals.

    Parameters
    ----------
    trace:
        A :class:`FallbackDecisionTrace` instance.

    Returns
    -------
    dict
        A compact dict with the key governance-relevant fields.  Never raises.
    """
    try:
        return trace.compact_summary()
    except Exception:
        return {"outcome": FallbackOutcome.BLOCKED.value}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_trace(
    intent_profile: Optional[Any],
    readiness_result: Optional[Any],
    execution_result: Optional[Dict[str, Any]],
    *,
    runtime_session_id: Optional[str],
    notes: Optional[str],
) -> FallbackDecisionTrace:
    """Internal implementation that derives trace fields from available signals."""
    # --- Extract intent profile fields -----------------------------------
    intent_id: Optional[str] = None
    action_level: str = "observe"
    profile_session_id: Optional[str] = None
    primary_path: Optional[str] = None
    runtime_domain: Optional[str] = None

    try:
        if intent_profile is not None:
            intent_id = str(getattr(intent_profile, "intent_id", "") or "")
            if not intent_id:
                intent_id = None
            action_level = str(getattr(intent_profile, "action_level", "observe") or "observe")
            profile_session_id = getattr(intent_profile, "runtime_session_id", None)
            runtime_domain = getattr(intent_profile, "runtime_domain", None)
            # Derive primary path from intent profile device/domain signals
            device_scope = getattr(intent_profile, "device_scope", None)
            if device_scope in ("remote", "multi-device"):
                primary_path = "cross_device"
            elif runtime_domain and runtime_domain != "local":
                primary_path = runtime_domain
            else:
                primary_path = "local_executor"
    except Exception:
        pass

    eff_session_id = runtime_session_id or profile_session_id

    # --- Derive decision source + block reason from readiness result ------
    decision_source = FallbackDecisionSource.UNKNOWN.value
    primary_block_reason: Optional[str] = None
    candidate_paths: List[Dict[str, Any]] = []
    readiness_status: Optional[str] = None
    readiness_blocked_by: Optional[str] = None

    try:
        if readiness_result is not None:
            readiness_status = str(getattr(readiness_result, "status", "") or "")
            readiness_blocked_by = str(getattr(readiness_result, "blocked_by", "") or "")
            readiness_reason = str(getattr(readiness_result, "reason", "") or "")
            is_ready = bool(getattr(readiness_result, "ready", True))

            if not is_ready:
                decision_source = _source_from_blocked_by(readiness_blocked_by)
                primary_block_reason = readiness_reason or readiness_blocked_by or "readiness_gate_blocked"

                # Record the primary path as a blocked candidate
                if primary_path:
                    candidate_paths.append(
                        FallbackCandidate(
                            path=primary_path,
                            reason_blocked=primary_block_reason,
                            evaluated=True,
                            selected=False,
                        ).to_dict()
                    )
    except Exception:
        pass

    # --- Derive fallback path + outcome from execution result -------------
    fallback_path: Optional[str] = None
    fallback_reason: Optional[str] = None
    outcome = FallbackOutcome.BLOCKED.value

    try:
        if execution_result is not None and isinstance(execution_result, dict):
            action_taken = str(execution_result.get("action_taken", "") or "")
            success = bool(execution_result.get("success", False))
            skipped_reason = str(execution_result.get("skipped_reason", "") or "")
            metadata = execution_result.get("metadata") or {}

            outcome, fallback_path, fallback_reason = _derive_outcome_and_fallback(
                action_taken=action_taken,
                success=success,
                skipped_reason=skipped_reason,
                metadata=metadata if isinstance(metadata, dict) else {},
                action_level=action_level,
                readiness_blocked_by=readiness_blocked_by or "",
            )

            # If decision_source was not set by readiness result, try to infer from execution
            if decision_source == FallbackDecisionSource.UNKNOWN.value and skipped_reason:
                decision_source = _source_from_skipped_reason(skipped_reason)

            # Bridge fallback: remote_fallback flag in metadata → bridge source
            if decision_source == FallbackDecisionSource.UNKNOWN.value:
                _meta_check = execution_result.get("metadata") or {}
                if isinstance(_meta_check, dict) and _meta_check.get("remote_fallback"):
                    decision_source = FallbackDecisionSource.BRIDGE.value

            # If primary_block_reason not yet set, derive from skipped_reason
            if not primary_block_reason and skipped_reason and action_taken in ("none", "error"):
                primary_block_reason = skipped_reason

        elif readiness_result is not None:
            # Execution didn't run (gate blocked) — infer noop/blocked from readiness
            is_ready = bool(getattr(readiness_result, "ready", True))
            if not is_ready:
                readiness_status_str = str(getattr(readiness_result, "status", "") or "")
                if readiness_status_str in ("observe_only",):
                    outcome = FallbackOutcome.NOOP.value
                    fallback_path = "noop"
                    fallback_reason = "action_level_observe_only"
                else:
                    outcome = FallbackOutcome.BLOCKED.value
                    fallback_path = None
                    fallback_reason = primary_block_reason
    except Exception:
        pass

    # --- Add selected fallback candidate ---------------------------------
    try:
        if fallback_path and fallback_path != primary_path:
            candidate_paths.append(
                FallbackCandidate(
                    path=fallback_path,
                    reason_blocked=None,
                    evaluated=True,
                    selected=True,
                ).to_dict()
            )
    except Exception:
        pass

    return FallbackDecisionTrace(
        runtime_session_id=eff_session_id,
        intent_id=intent_id,
        action_level=action_level,
        primary_path=primary_path,
        primary_block_reason=primary_block_reason,
        fallback_path=fallback_path,
        fallback_reason=fallback_reason,
        decision_source=decision_source,
        candidate_paths=candidate_paths,
        outcome=outcome,
        notes=notes,
    )


def _source_from_blocked_by(blocked_by: str) -> str:
    """Map a ``BlockedBy`` string to a :class:`FallbackDecisionSource` value."""
    mapping: Dict[str, str] = {
        "policy": FallbackDecisionSource.POLICY.value,
        "hitl": FallbackDecisionSource.POLICY.value,
        "confirmation_required": FallbackDecisionSource.POLICY.value,
        "runtime_phase": FallbackDecisionSource.RUNTIME.value,
        "domain": FallbackDecisionSource.RUNTIME.value,
        "missing_target": FallbackDecisionSource.READINESS_GATE.value,
        "missing_intent": FallbackDecisionSource.READINESS_GATE.value,
        "action_level": FallbackDecisionSource.READINESS_GATE.value,
        "none": FallbackDecisionSource.UNKNOWN.value,
    }
    return mapping.get((blocked_by or "").lower(), FallbackDecisionSource.READINESS_GATE.value)


def _source_from_skipped_reason(skipped_reason: str) -> str:
    """Infer a :class:`FallbackDecisionSource` from an execution ``skipped_reason``."""
    lower = (skipped_reason or "").lower()
    if lower.startswith("readiness_gate"):
        return FallbackDecisionSource.READINESS_GATE.value
    if "policy" in lower or "hitl" in lower or "band" in lower:
        return FallbackDecisionSource.POLICY.value
    if "executor" in lower or "uia" in lower or "system_api" in lower:
        return FallbackDecisionSource.EXECUTOR.value
    if "remote" in lower or "bridge" in lower or "cross_device" in lower:
        return FallbackDecisionSource.BRIDGE.value
    if "runtime" in lower or "domain" in lower or "phase" in lower:
        return FallbackDecisionSource.RUNTIME.value
    return FallbackDecisionSource.UNKNOWN.value


def _derive_outcome_and_fallback(
    action_taken: str,
    success: bool,
    skipped_reason: str,
    metadata: Dict[str, Any],
    action_level: str,
    readiness_blocked_by: str,
) -> tuple:
    """Derive (outcome, fallback_path, fallback_reason) from execution result signals.

    Returns a 3-tuple of strings (outcome_value, fallback_path, fallback_reason).
    """
    remote_fallback = bool(metadata.get("remote_fallback", False))

    # Noop: observe/hint action levels that ran successfully as advisory
    if action_level in ("observe", "hint") and action_taken in ("noop", "none") and not skipped_reason:
        return FallbackOutcome.NOOP.value, "noop", "action_level_observe_only"

    # Readiness gate / observe-only block
    if skipped_reason and "observe_only" in skipped_reason:
        return FallbackOutcome.NOOP.value, "noop", skipped_reason

    # Readiness gate blocked (not observe-only)
    if skipped_reason and skipped_reason.startswith("readiness_gate:"):
        # Was it a confirmation requirement? → still blocked until confirmed
        if "confirm" in skipped_reason:
            return FallbackOutcome.BLOCKED.value, None, skipped_reason
        return FallbackOutcome.BLOCKED.value, None, skipped_reason

    # Executor unavailable — local fallback to noop/degraded
    if skipped_reason == "executor_unavailable":
        return FallbackOutcome.DEGRADED.value, "local_fallback", "executor_unavailable"

    # Remote fallback scenario (bridge fell back to local)
    if remote_fallback:
        fallback_reason = str(metadata.get("fallback_reason", "remote_unavailable") or "remote_unavailable")
        return FallbackOutcome.SELECTED.value, "local_fallback", fallback_reason

    # Internal error during execution → failed
    if action_taken == "error" or (skipped_reason and skipped_reason.startswith("internal_error")):
        return FallbackOutcome.FAILED.value, None, skipped_reason or "internal_error"

    # Explicit noop / skipped action (non-error)
    if action_taken in ("noop", "none") and skipped_reason:
        return FallbackOutcome.BLOCKED.value, None, skipped_reason

    # Successful execution — no fallback occurred
    if success and action_taken not in ("none", "noop", "error"):
        return FallbackOutcome.SELECTED.value, action_taken, None

    # Generic blocked fallback
    if not success:
        return FallbackOutcome.BLOCKED.value, None, skipped_reason or "execution_failed"

    # Default: noop
    return FallbackOutcome.NOOP.value, "noop", skipped_reason or None
