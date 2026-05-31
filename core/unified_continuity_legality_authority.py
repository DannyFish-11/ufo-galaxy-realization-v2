"""core/unified_continuity_legality_authority.py
=================================================
Unified Continuity Legality Authority — the single canonical gate for all
inbound-action continuity legality decisions in this distributed agent system.

Background
----------
Prior to this module the system evaluated continuity legality in a fragmented
way:

* Reconnect / re-register used ``classify_reconnect_outcome()`` in
  ``core.attached_runtime_session_registry``.
* Replay and delegated recovery used ``FlowContinuityCoordinator`` in
  ``core.flow_continuity_coordinator``.
* Online dispatch acceptance ran attachment-state checks inside
  ``core.unified_dispatch_readiness_gate``.
* Online execution signal ingestion used the guard layer in
  ``core.attached_runtime_recovery_readiness``.
* Terminal result ingestion (``core.unified_result_ingress``) and online
  runtime truth ingress (``core.unified_runtime_truth_ingress``) performed
  **no continuity legality gate** before forwarding to the truth chain.

This split interpretation created the possibility of:

* Stale runtime identities (revoked ``runtime_session_id``) reaching the
  truth chain through the result-ingress path.
* Stale attachment sessions reaching signal processing without being blocked.
* Late delegated-recovery signals being treated equivalently to fresh
  online-execution signals.
* Replayed stale results bypassing session-epoch checks.

This module closes all of those gaps by providing **one** function —
:func:`evaluate_continuity_legality` — that every inbound-action path MUST
call before forwarding to its respective truth chain, processing chain, or
dispatch path.

Design
------
1. **Single authority** — this module is the canonical continuity legality
   gate.  No other module may implement a competing continuity legality
   decision for the paths enumerated in :class:`ContinuityLegalityPath`.
2. **Additive only** — does not modify any existing module.  Wiring is
   achieved by inserting a call to :func:`evaluate_continuity_legality` as
   the first step in each path's processing chain.
3. **Composing, not duplicating** — delegates dimension checks to existing
   sub-authorities:
   - ``core.attached_runtime_session_registry`` — session/attachment state.
   - ``core.attached_runtime_recovery_readiness`` — signal guard
     (duplicate/replay/stale/out-of-order).
   - ``core.flow_continuity_coordinator`` — reconnect/attach/stale-identity
     classification.
4. **Fail-closed** — when a sub-authority is unavailable, the dimension is
   marked ``unknown`` and the overall verdict depends on path policy (some
   paths allow ``unknown`` through, others require a positive ``allow``).
5. **Fully serialisable** — :meth:`ContinuityLegalityReport.to_dict`
   produces stable JSON for observability and audit.

Continuity dimensions evaluated
--------------------------------
:class:`ContinuityLegalityDimension` enumerates all twelve dimensions that
this authority unifies:

1.  ``runtime_session_continuity``   — runtime_session_id still valid?
2.  ``attachment_session_continuity``— runtime_attachment_session_id valid?
3.  ``durable_session_continuity``   — durable_session_id still valid?
4.  ``continuity_epoch_ordering``    — epoch is acceptably ordered?
5.  ``stale_runtime_rejection``      — runtime_session stale?
6.  ``stale_attachment_rejection``   — attachment session stale?
7.  ``late_signal_rejection``        — signal arrived too late?
8.  ``duplicate_signal_rejection``   — duplicate signal?
9.  ``out_of_order_signal_rejection``— out-of-order signal?
10. ``replay_legality``              — is this a legitimate replay?
11. ``delegated_recovery_legality``  — is delegated recovery legal?
12. ``online_execution_legality``    — is online dispatch/execution legal?

Paths that share this authority
---------------------------------
:class:`ContinuityLegalityPath` enumerates all paths covered:

* ``RECONNECT``
* ``RE_REGISTER``
* ``REPLAY_INGRESS``
* ``DELEGATED_RECOVERY``
* ``ATTACHMENT_RESUME``
* ``ONLINE_DISPATCH_ACCEPTANCE``
* ``ONLINE_SIGNAL_INGESTION``
* ``TERMINAL_RESULT_INGESTION``

Authority sentinel
------------------
:data:`UNIFIED_CONTINUITY_LEGALITY_AUTHORITY`

Policy sentinels
----------------
:data:`ALL_PATHS_MUST_USE_UNIFIED_AUTHORITY_POLICY`
:data:`CONTINUITY_FIELDS_ARE_ACTIVE_GATE_NOT_PAYLOAD_POLICY`
:data:`STALE_IDENTITY_MUST_BE_REJECTED_POLICY`
:data:`ONLINE_EXECUTION_SUBMITS_TO_SAME_AUTHORITY_POLICY`
:data:`FAIL_CLOSED_ON_AUTHORITY_UNAVAILABILITY_POLICY`
:data:`UNIFIED_CONTINUITY_LEGALITY_AUTHORITY_PR_SENTINEL`

Public API
----------
Enums::

    ContinuityLegalityPath
    ContinuityLegalityDimension
    ContinuityLegalityVerdict

Dataclasses::

    ContinuityLegalityContext
    DimensionLegalityOutcome
    ContinuityLegalityReport

Functions::

    evaluate_continuity_legality(path, ctx) -> ContinuityLegalityReport
    get_unified_continuity_legality_authority()
    reset_unified_continuity_legality_authority()   (testing only)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.UnifiedContinuityLegalityAuthority")

# ---------------------------------------------------------------------------
# Authority + policy sentinels
# ---------------------------------------------------------------------------

UNIFIED_CONTINUITY_LEGALITY_AUTHORITY: str = (
    "UNIFIED_CONTINUITY_LEGALITY_AUTHORITY::"
    "core.unified_continuity_legality_authority is the single canonical "
    "continuity legality gate for ALL inbound-action paths in this "
    "distributed agent system.  No other module may implement a competing "
    "continuity legality decision for the paths enumerated in "
    "ContinuityLegalityPath.  Every critical path MUST call "
    "evaluate_continuity_legality() before forwarding to its truth chain, "
    "processing chain, or dispatch path."
)

UNIFIED_CONTINUITY_LEGALITY_AUTHORITY_PR_SENTINEL: str = (
    "UNIFIED_CONTINUITY_LEGALITY_AUTHORITY_PR::"
    "unified-continuity-legality-closure::"
    "single-authority-all-paths::post-533-dual-repo-runtime-unification"
)

ALL_PATHS_MUST_USE_UNIFIED_AUTHORITY_POLICY: str = (
    "POLICY::ALL_PATHS_MUST_USE_UNIFIED_AUTHORITY: "
    "Reconnect, re-register, replay ingress, delegated recovery, attachment "
    "resume, online dispatch acceptance, online execution signal ingestion, "
    "and terminal result ingestion MUST all route continuity legality "
    "evaluation through evaluate_continuity_legality().  No path may "
    "implement its own isolated continuity legality judgment."
)

CONTINUITY_FIELDS_ARE_ACTIVE_GATE_NOT_PAYLOAD_POLICY: str = (
    "POLICY::CONTINUITY_FIELDS_ARE_ACTIVE_GATE: "
    "runtime_session_id, runtime_attachment_session_id, durable_session_id, "
    "and continuity_epoch MUST be actively consumed as legality gate inputs "
    "on every critical inbound-action path.  These fields MUST NOT remain "
    "passive payload, audit-only, or compatibility-only fields.  When the "
    "authority issues a REJECT verdict the calling path MUST NOT proceed "
    "to its truth chain or dispatch layer."
)

STALE_IDENTITY_MUST_BE_REJECTED_POLICY: str = (
    "POLICY::STALE_IDENTITY_MUST_BE_REJECTED: "
    "An inbound action carrying a runtime_session_id or "
    "runtime_attachment_session_id that the registry holds in a terminal "
    "state (replaced / invalidated) MUST be rejected.  Stale attachment "
    "identities MUST NOT reach the truth chain.  This policy applies "
    "uniformly to reconnect, replay, delegated recovery, and online "
    "execution paths alike."
)

ONLINE_EXECUTION_SUBMITS_TO_SAME_AUTHORITY_POLICY: str = (
    "POLICY::ONLINE_EXECUTION_SUBMITS_TO_SAME_AUTHORITY: "
    "Online dispatch acceptance, online execution signal ingestion, and "
    "terminal result ingestion are subject to the SAME continuity legality "
    "authority as recovery-oriented paths (replay, delegated recovery, "
    "attachment resume).  Continuity legality is NOT a recovery-only "
    "concern.  Any action claiming to belong to the current runtime/session "
    "reality MUST first answer whether it still belongs to the current legal "
    "continuity reality."
)

FAIL_CLOSED_ON_AUTHORITY_UNAVAILABILITY_POLICY: str = (
    "POLICY::FAIL_CLOSED_ON_AUTHORITY_UNAVAILABILITY: "
    "When a continuity sub-authority (session registry, signal guard, flow "
    "coordinator) is unavailable the affected dimension is marked 'unknown'. "
    "For paths with strict mode (RECONNECT, REPLAY_INGRESS, "
    "DELEGATED_RECOVERY, TERMINAL_RESULT_INGESTION) an 'unknown' verdict on "
    "any identity dimension escalates to REQUIRE_REVIEW.  Only paths "
    "explicitly configured for lenient mode may pass through on 'unknown'."
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ContinuityLegalityPath(str, Enum):
    """All inbound-action paths covered by the unified authority."""

    RECONNECT = "reconnect"
    RE_REGISTER = "re_register"
    REPLAY_INGRESS = "replay_ingress"
    DELEGATED_RECOVERY = "delegated_recovery"
    ATTACHMENT_RESUME = "attachment_resume"
    ONLINE_DISPATCH_ACCEPTANCE = "online_dispatch_acceptance"
    ONLINE_SIGNAL_INGESTION = "online_signal_ingestion"
    TERMINAL_RESULT_INGESTION = "terminal_result_ingestion"

    @classmethod
    def from_string(
        cls, value: Any, *, default: "ContinuityLegalityPath" = None
    ) -> Optional["ContinuityLegalityPath"]:
        try:
            return cls(str(value).lower().strip())
        except ValueError:
            return default


class ContinuityLegalityDimension(str, Enum):
    """All twelve continuity legality dimensions evaluated by this authority."""

    runtime_session_continuity = "runtime_session_continuity"
    attachment_session_continuity = "attachment_session_continuity"
    durable_session_continuity = "durable_session_continuity"
    continuity_epoch_ordering = "continuity_epoch_ordering"
    stale_runtime_rejection = "stale_runtime_rejection"
    stale_attachment_rejection = "stale_attachment_rejection"
    late_signal_rejection = "late_signal_rejection"
    duplicate_signal_rejection = "duplicate_signal_rejection"
    out_of_order_signal_rejection = "out_of_order_signal_rejection"
    replay_legality = "replay_legality"
    delegated_recovery_legality = "delegated_recovery_legality"
    online_execution_legality = "online_execution_legality"


class ContinuityLegalityVerdict(str, Enum):
    """Authoritative continuity legality verdict.

    Values
    ------
    ALLOW
        The inbound action passes all evaluated continuity dimensions.
        The calling path may proceed to its truth chain or dispatch layer.
    REJECT
        The inbound action fails at least one continuity dimension.
        The calling path MUST NOT proceed; it must return an appropriate
        rejection response to the sender.
    REQUIRE_REVIEW
        The authority cannot safely classify the action (e.g. sub-authority
        unavailable, ambiguous session state).  The calling path should
        treat this as a soft rejection and return an advisory rejection.
    """

    ALLOW = "allow"
    REJECT = "reject"
    REQUIRE_REVIEW = "require_review"

    def is_rejected(self) -> bool:
        """Return True for REJECT or REQUIRE_REVIEW."""
        return self in (
            ContinuityLegalityVerdict.REJECT,
            ContinuityLegalityVerdict.REQUIRE_REVIEW,
        )

    def is_hard_rejected(self) -> bool:
        """Return True only for REJECT (not REQUIRE_REVIEW)."""
        return self is ContinuityLegalityVerdict.REJECT


class ContinuityLegalityMode(str, Enum):
    """Continuity legality gating strictness.

    STRICT
        ``require_review`` is blocking (fail-closed with review requirement).
    COMPAT
        ``require_review`` is advisory and does not block the hot path.
    RELAXED
        Most permissive compatibility mode; keeps review signals advisory.
    """

    STRICT = "strict"
    COMPAT = "compat"
    RELAXED = "relaxed"


DEFAULT_CONTINUITY_LEGALITY_MODE_ENV = "GALAXY_CONTINUITY_LEGALITY_MODE"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ContinuityLegalityContext:
    """All continuity identity fields for an inbound action.

    Callers should populate every field they have.  Empty / None values are
    allowed — the authority treats missing identity fields as non-constraining
    (it cannot assert illegality from an absent field).

    Fields
    ------
    device_id:
        The originating device identifier.
    runtime_session_id:
        The runtime session identifier carried by the inbound action.
    runtime_attachment_session_id:
        The attachment session identifier (persistent cross-device identity).
    durable_session_id:
        The durable / long-lived session identifier.
    continuity_epoch:
        The continuity epoch counter (0 if absent).
    signal_id:
        Idempotency signal identifier (for duplicate/replay guard).
    emission_seq:
        Signal emission sequence number (for stale/out-of-order guard).
    contract_id:
        Delegated execution contract identifier.
    flow_id:
        Flow entity identifier.
    metadata:
        Arbitrary extra context (replay flags, recovery reason, etc.).
    """

    device_id: str = ""
    runtime_session_id: str = ""
    runtime_attachment_session_id: str = ""
    durable_session_id: str = ""
    continuity_epoch: int = 0
    signal_id: str = ""
    emission_seq: int = 0
    contract_id: str = ""
    flow_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "runtime_session_id": self.runtime_session_id,
            "runtime_attachment_session_id": self.runtime_attachment_session_id,
            "durable_session_id": self.durable_session_id,
            "continuity_epoch": self.continuity_epoch,
            "signal_id": self.signal_id,
            "emission_seq": self.emission_seq,
            "contract_id": self.contract_id,
            "flow_id": self.flow_id,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))


@dataclass
class DimensionLegalityOutcome:
    """Result of evaluating one :class:`ContinuityLegalityDimension`.

    Fields
    ------
    dimension:
        Which dimension was evaluated.
    verdict:
        ``ALLOW`` / ``REJECT`` / ``REQUIRE_REVIEW`` for this dimension.
    reason:
        Human-readable explanation.  Empty when ``verdict == ALLOW``.
    evidence:
        Structured evidence used to reach the verdict (for diagnostics).
    """

    dimension: ContinuityLegalityDimension
    verdict: ContinuityLegalityVerdict = ContinuityLegalityVerdict.ALLOW
    reason: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "verdict": self.verdict.value,
            "reason": self.reason,
            "evidence": dict(self.evidence),
        }


@dataclass
class ContinuityLegalityReport:
    """Full continuity legality report produced by :func:`evaluate_continuity_legality`.

    The overall :attr:`verdict` is the aggregation of all individual dimension
    outcomes: ``ALLOW`` only if ALL dimensions allow; ``REJECT`` if any
    dimension rejects; ``REQUIRE_REVIEW`` if any dimension is uncertain and
    no dimension rejects.

    Fields
    ------
    path:
        Which inbound-action path was being evaluated.
    verdict:
        Overall aggregated verdict.
    reject_reason:
        Human-readable summary of the first rejecting dimension.  Empty when
        ``verdict == ALLOW``.
    dimensions:
        Per-dimension outcomes.
    context_snapshot:
        A copy of the :class:`ContinuityLegalityContext` that was evaluated.
    report_id:
        Unique identifier for this report instance (for correlation).
    authority:
        The authority sentinel string.
    """

    path: ContinuityLegalityPath = ContinuityLegalityPath.ONLINE_DISPATCH_ACCEPTANCE
    verdict: ContinuityLegalityVerdict = ContinuityLegalityVerdict.ALLOW
    reject_reason: str = ""
    dimensions: List[DimensionLegalityOutcome] = field(default_factory=list)
    context_snapshot: Dict[str, Any] = field(default_factory=dict)
    report_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    authority: str = UNIFIED_CONTINUITY_LEGALITY_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "path": self.path.value,
            "verdict": self.verdict.value,
            "reject_reason": self.reject_reason,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "context_snapshot": dict(self.context_snapshot),
            "authority": self.authority,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), **kwargs)

    @property
    def is_allowed(self) -> bool:
        return self.verdict is ContinuityLegalityVerdict.ALLOW

    @property
    def is_rejected(self) -> bool:
        return self.verdict.is_rejected()

    @property
    def is_hard_rejected(self) -> bool:
        return self.verdict is ContinuityLegalityVerdict.REJECT


# ---------------------------------------------------------------------------
# Path policy configuration
# ---------------------------------------------------------------------------

# Paths that evaluate session / attachment identity dimensions (strict)
_IDENTITY_STRICT_PATHS = frozenset({
    ContinuityLegalityPath.RECONNECT,
    ContinuityLegalityPath.RE_REGISTER,
    ContinuityLegalityPath.ATTACHMENT_RESUME,
    ContinuityLegalityPath.REPLAY_INGRESS,
    ContinuityLegalityPath.DELEGATED_RECOVERY,
    ContinuityLegalityPath.TERMINAL_RESULT_INGESTION,
    ContinuityLegalityPath.ONLINE_DISPATCH_ACCEPTANCE,
    ContinuityLegalityPath.ONLINE_SIGNAL_INGESTION,
})

# Paths that evaluate signal guard dimensions
_SIGNAL_GUARD_PATHS = frozenset({
    ContinuityLegalityPath.ONLINE_SIGNAL_INGESTION,
    ContinuityLegalityPath.REPLAY_INGRESS,
    ContinuityLegalityPath.DELEGATED_RECOVERY,
})

# Paths that evaluate epoch ordering
_EPOCH_PATHS = frozenset({
    ContinuityLegalityPath.RECONNECT,
    ContinuityLegalityPath.RE_REGISTER,
    ContinuityLegalityPath.REPLAY_INGRESS,
    ContinuityLegalityPath.DELEGATED_RECOVERY,
    ContinuityLegalityPath.TERMINAL_RESULT_INGESTION,
})

# Paths where 'unknown' on identity dimensions escalates to REQUIRE_REVIEW
_STRICT_MODE_PATHS = frozenset({
    ContinuityLegalityPath.RECONNECT,
    ContinuityLegalityPath.REPLAY_INGRESS,
    ContinuityLegalityPath.DELEGATED_RECOVERY,
    ContinuityLegalityPath.TERMINAL_RESULT_INGESTION,
    ContinuityLegalityPath.ONLINE_DISPATCH_ACCEPTANCE,
})


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_singleton_lock = threading.Lock()
_singleton: Optional["UnifiedContinuityLegalityAuthority"] = None


def get_unified_continuity_legality_authority() -> "UnifiedContinuityLegalityAuthority":
    """Return the process-level singleton :class:`UnifiedContinuityLegalityAuthority`."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = UnifiedContinuityLegalityAuthority()
    return _singleton


def reset_unified_continuity_legality_authority() -> None:
    """Reset the process-level singleton.  For testing only."""
    global _singleton
    with _singleton_lock:
        _singleton = None


# ---------------------------------------------------------------------------
# Main evaluation function (module-level convenience)
# ---------------------------------------------------------------------------


def evaluate_continuity_legality(
    path: ContinuityLegalityPath,
    ctx: ContinuityLegalityContext,
    mode: Optional[Any] = None,
) -> ContinuityLegalityReport:
    """Evaluate continuity legality for *ctx* on the given *path*.

    This is the **single canonical continuity legality gate** that every
    critical inbound-action path MUST call.

    Parameters
    ----------
    path:
        Which path is requesting the legality evaluation.
    ctx:
        All continuity identity fields for the inbound action.

    Returns
    -------
    ContinuityLegalityReport
        Full report.  The calling path MUST check ``report.is_allowed``
        before proceeding.  When ``report.is_rejected`` the path MUST
        abort and return a rejection response.
    """
    return get_unified_continuity_legality_authority().evaluate(path, ctx, mode=mode)


def resolve_continuity_legality_mode(
    path: ContinuityLegalityPath,
    *,
    explicit_mode: Optional[Any] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> ContinuityLegalityMode:
    """Resolve strictness mode for continuity legality decisions."""

    def _parse(raw: Any) -> Optional[ContinuityLegalityMode]:
        try:
            return ContinuityLegalityMode(str(raw).strip().lower())
        except Exception as exc:
            return None

    if explicit_mode is not None:
        parsed = _parse(explicit_mode)
        if parsed is not None:
            return parsed

    if metadata:
        for key in (
            "continuity_legality_mode",
            "canonical_continuity_mode",
            "canonical_governance_mode",
        ):
            parsed = _parse(metadata.get(key))
            if parsed is not None:
                return parsed

    parsed = _parse(os.environ.get(DEFAULT_CONTINUITY_LEGALITY_MODE_ENV, ""))
    if parsed is not None:
        return parsed

    if path in _STRICT_MODE_PATHS:
        return ContinuityLegalityMode.STRICT
    return ContinuityLegalityMode.COMPAT


# ---------------------------------------------------------------------------
# Authority class
# ---------------------------------------------------------------------------


class UnifiedContinuityLegalityAuthority:
    """Single canonical authority for continuity legality decisions.

    Thread-safe.  Use :func:`get_unified_continuity_legality_authority` to
    obtain the process-level singleton rather than constructing directly.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        path: ContinuityLegalityPath,
        ctx: ContinuityLegalityContext,
        mode: Optional[Any] = None,
    ) -> ContinuityLegalityReport:
        """Evaluate all relevant continuity dimensions for *path* + *ctx*.

        Returns a :class:`ContinuityLegalityReport` with an aggregated
        :attr:`~ContinuityLegalityReport.verdict`.
        """
        dimension_outcomes: List[DimensionLegalityOutcome] = []

        # ── Dimension 1 & 2: Runtime session + attachment session identity ─
        if path in _IDENTITY_STRICT_PATHS:
            outcome = self._check_session_identity(ctx)
            dimension_outcomes.append(outcome)

        # ── Dimension 5 & 6: Stale runtime + stale attachment rejection ────
        if path in _IDENTITY_STRICT_PATHS:
            stale_rt = self._check_stale_runtime(ctx)
            if stale_rt is not None:
                dimension_outcomes.append(stale_rt)

            stale_att = self._check_stale_attachment(ctx)
            if stale_att is not None:
                dimension_outcomes.append(stale_att)

        # ── Dimension 4: Continuity epoch ordering ─────────────────────────
        if path in _EPOCH_PATHS and ctx.continuity_epoch > 0:
            epoch_outcome = self._check_epoch_ordering(ctx, path)
            dimension_outcomes.append(epoch_outcome)

        # ── Dimensions 7–10: Signal guard (late/duplicate/OOO/replay) ─────
        if path in _SIGNAL_GUARD_PATHS and ctx.signal_id:
            guard_outcome = self._check_signal_guard(ctx, path)
            dimension_outcomes.append(guard_outcome)

        # ── Dimension 11: Delegated recovery legality ──────────────────────
        if path is ContinuityLegalityPath.DELEGATED_RECOVERY:
            outcome = self._check_delegated_recovery_legality(ctx)
            dimension_outcomes.append(outcome)

        # ── Dimension 12: Online execution legality ────────────────────────
        if path in (
            ContinuityLegalityPath.ONLINE_DISPATCH_ACCEPTANCE,
            ContinuityLegalityPath.ONLINE_SIGNAL_INGESTION,
            ContinuityLegalityPath.TERMINAL_RESULT_INGESTION,
        ):
            outcome = self._check_online_execution_legality(ctx, path)
            dimension_outcomes.append(outcome)

        # ── Aggregate ──────────────────────────────────────────────────────
        resolved_mode = resolve_continuity_legality_mode(path, explicit_mode=mode)
        overall, reject_reason = self._aggregate(
            dimension_outcomes, path, resolved_mode
        )

        return ContinuityLegalityReport(
            path=path,
            verdict=overall,
            reject_reason=reject_reason,
            dimensions=dimension_outcomes,
            context_snapshot=ctx.to_dict(),
        )

    # ------------------------------------------------------------------
    # Dimension evaluators
    # ------------------------------------------------------------------

    def _check_session_identity(
        self, ctx: ContinuityLegalityContext
    ) -> DimensionLegalityOutcome:
        """Check runtime session + attachment session identity against registry.

        Covers dimensions 1 (runtime_session_continuity) and
        2 (attachment_session_continuity).  Also guards against
        dimensioned stale-identity at the registry level.
        """
        dim = ContinuityLegalityDimension.runtime_session_continuity
        evidence: Dict[str, Any] = {
            "runtime_session_id": ctx.runtime_session_id,
            "runtime_attachment_session_id": ctx.runtime_attachment_session_id,
            "device_id": ctx.device_id,
        }

        # When no identity fields are present, cannot assert illegality
        if (
            not ctx.runtime_session_id
            and not ctx.runtime_attachment_session_id
            and not ctx.device_id
        ):
            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.ALLOW,
                reason="",
                evidence=evidence,
            )

        try:
            from core.attached_runtime_session_registry import (
                get_session_registry,
                lookup_session_by_device,
            )
        except Exception as _import_err:
            logger.debug("Fallback triggered: %s", _import_err)
            evidence["registry_unavailable"] = str(_import_err)
            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.REQUIRE_REVIEW,
                reason=(
                    "Session registry unavailable; cannot verify identity legality. "
                    f"({_import_err})"
                ),
                evidence=evidence,
            )

        try:
            entry = None
            # Check active entry first; also try attachment-id-based lookup for
            # terminal-state detection when device_id produces no active entry.
            if ctx.device_id:
                entry = lookup_session_by_device(ctx.device_id)

            if entry is None and ctx.runtime_attachment_session_id:
                # Try non-active lookup via attachment ID so terminal states are caught
                try:
                    registry = get_session_registry()
                    entry = registry.get_by_runtime_attachment_session_id(
                        ctx.runtime_attachment_session_id, active_only=False
                    )
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)

            if entry is None:
                # No registry entry — cannot assert illegality
                evidence["registry_entry"] = "absent"
                return DimensionLegalityOutcome(
                    dimension=dim,
                    verdict=ContinuityLegalityVerdict.ALLOW,
                    reason="",
                    evidence=evidence,
                )

            state = entry.attachment_state
            state_val = state.value if hasattr(state, "value") else str(state)
            evidence["registry_state"] = state_val
            evidence["registry_runtime_session_id"] = getattr(
                entry, "runtime_session_id", ""
            )
            evidence["registry_attachment_id"] = getattr(
                entry, "runtime_attachment_session_id", ""
            )

            # Check terminal state → stale identity
            is_terminal = (
                hasattr(state, "is_terminal") and state.is_terminal()
            ) or state_val in ("replaced", "invalidated")

            if is_terminal:
                return DimensionLegalityOutcome(
                    dimension=dim,
                    verdict=ContinuityLegalityVerdict.REJECT,
                    reason=(
                        f"Runtime attachment session is in terminal state "
                        f"'{state_val}' for device_id={ctx.device_id!r}. "
                        "Action rejected per STALE_IDENTITY_MUST_BE_REJECTED_POLICY."
                    ),
                    evidence=evidence,
                )

            # Check attachment_id mismatch when caller provides one
            if (
                ctx.runtime_attachment_session_id
                and entry.runtime_attachment_session_id
                and ctx.runtime_attachment_session_id
                != entry.runtime_attachment_session_id
            ):
                return DimensionLegalityOutcome(
                    dimension=dim,
                    verdict=ContinuityLegalityVerdict.REJECT,
                    reason=(
                        f"runtime_attachment_session_id mismatch: "
                        f"provided={ctx.runtime_attachment_session_id!r} "
                        f"registry={entry.runtime_attachment_session_id!r}."
                    ),
                    evidence=evidence,
                )

            # Check runtime_session_id mismatch when caller provides one
            if (
                ctx.runtime_session_id
                and entry.runtime_session_id
                and ctx.runtime_session_id != entry.runtime_session_id
            ):
                return DimensionLegalityOutcome(
                    dimension=dim,
                    verdict=ContinuityLegalityVerdict.REJECT,
                    reason=(
                        f"runtime_session_id mismatch: "
                        f"provided={ctx.runtime_session_id!r} "
                        f"registry={entry.runtime_session_id!r}."
                    ),
                    evidence=evidence,
                )

            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.ALLOW,
                reason="",
                evidence=evidence,
            )

        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            evidence["check_error"] = str(exc)
            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.REQUIRE_REVIEW,
                reason=f"Session identity check raised: {exc}",
                evidence=evidence,
            )

    def _check_stale_runtime(
        self, ctx: ContinuityLegalityContext
    ) -> Optional[DimensionLegalityOutcome]:
        """Check stale runtime dimension (5) via FlowContinuityCoordinator."""
        # Only meaningful when a runtime_session_id is present
        if not ctx.runtime_session_id:
            return None

        dim = ContinuityLegalityDimension.stale_runtime_rejection
        evidence: Dict[str, Any] = {
            "runtime_session_id": ctx.runtime_session_id,
            "device_id": ctx.device_id,
        }

        try:
            from core.flow_continuity_coordinator import (
                ContinuityEventContext,
                ContinuityEventKind,
                get_flow_continuity_coordinator,
            )
        except Exception as _imp:
            logger.debug("Fallback triggered: %s", _imp)
            evidence["coordinator_unavailable"] = str(_imp)
            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.REQUIRE_REVIEW,
                reason=f"FlowContinuityCoordinator unavailable: {_imp}",
                evidence=evidence,
            )

        try:
            coordinator = get_flow_continuity_coordinator()
            event_ctx = ContinuityEventContext(
                event_kind=ContinuityEventKind.stale_identity,
                device_id=ctx.device_id,
                session_id=ctx.runtime_session_id,
                runtime_attachment_session_id=ctx.runtime_attachment_session_id,
                contract_id=ctx.contract_id,
                flow_id=ctx.flow_id,
                metadata=dict(ctx.metadata),
            )
            artifact = coordinator.decide_stale_identity(event_ctx)
            decision_val = (
                artifact.decision.value
                if hasattr(artifact.decision, "value")
                else str(artifact.decision)
            )
            evidence["coordinator_decision"] = decision_val
            evidence["coordinator_detail"] = artifact.detail

            if decision_val == "reject_stale_identity":
                return DimensionLegalityOutcome(
                    dimension=dim,
                    verdict=ContinuityLegalityVerdict.REJECT,
                    reason=(
                        f"Stale runtime identity detected: {artifact.detail}"
                    ),
                    evidence=evidence,
                )
            if decision_val == "fail_closed":
                return DimensionLegalityOutcome(
                    dimension=dim,
                    verdict=ContinuityLegalityVerdict.REQUIRE_REVIEW,
                    reason=(
                        f"Stale runtime check fail_closed: {artifact.detail}"
                    ),
                    evidence=evidence,
                )
            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.ALLOW,
                reason="",
                evidence=evidence,
            )

        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            evidence["check_error"] = str(exc)
            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.REQUIRE_REVIEW,
                reason=f"Stale runtime check raised: {exc}",
                evidence=evidence,
            )

    def _check_stale_attachment(
        self, ctx: ContinuityLegalityContext
    ) -> Optional[DimensionLegalityOutcome]:
        """Check stale attachment dimension (6) via registry terminal state."""
        if not ctx.runtime_attachment_session_id:
            return None

        dim = ContinuityLegalityDimension.stale_attachment_rejection
        evidence: Dict[str, Any] = {
            "runtime_attachment_session_id": ctx.runtime_attachment_session_id,
            "device_id": ctx.device_id,
        }

        try:
            from core.attached_runtime_session_registry import (
                get_session_registry,
                lookup_session_by_device,
            )
        except Exception as _imp:
            logger.debug("Fallback triggered: %s", _imp)
            evidence["registry_unavailable"] = str(_imp)
            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.REQUIRE_REVIEW,
                reason=f"Registry unavailable for stale attachment check: {_imp}",
                evidence=evidence,
            )

        try:
            entry = None
            if ctx.device_id:
                entry = lookup_session_by_device(ctx.device_id)

            if entry is None:
                # Also try non-active lookup by attachment ID
                try:
                    registry = get_session_registry()
                    entry = registry.get_by_runtime_attachment_session_id(
                        ctx.runtime_attachment_session_id, active_only=False
                    )
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)

            if entry is None:
                evidence["registry_entry"] = "absent"
                return DimensionLegalityOutcome(
                    dimension=dim,
                    verdict=ContinuityLegalityVerdict.ALLOW,
                    reason="",
                    evidence=evidence,
                )

            # Check the attachment_id matches the registry entry
            registry_attachment_id = getattr(
                entry, "runtime_attachment_session_id", ""
            )
            evidence["registry_attachment_id"] = registry_attachment_id
            state = entry.attachment_state
            state_val = state.value if hasattr(state, "value") else str(state)
            evidence["registry_state"] = state_val

            is_terminal = (
                hasattr(state, "is_terminal") and state.is_terminal()
            ) or state_val in ("replaced", "invalidated")

            if (
                registry_attachment_id
                and ctx.runtime_attachment_session_id != registry_attachment_id
            ):
                # Attachment ID mismatch with a live registry entry
                return DimensionLegalityOutcome(
                    dimension=dim,
                    verdict=ContinuityLegalityVerdict.REJECT,
                    reason=(
                        f"Stale attachment: provided attachment_id="
                        f"{ctx.runtime_attachment_session_id!r} does not match "
                        f"active registry attachment_id={registry_attachment_id!r}."
                    ),
                    evidence=evidence,
                )

            if is_terminal:
                return DimensionLegalityOutcome(
                    dimension=dim,
                    verdict=ContinuityLegalityVerdict.REJECT,
                    reason=(
                        f"Stale attachment: session in terminal state "
                        f"'{state_val}' for device_id={ctx.device_id!r}."
                    ),
                    evidence=evidence,
                )

            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.ALLOW,
                reason="",
                evidence=evidence,
            )

        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            evidence["check_error"] = str(exc)
            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.REQUIRE_REVIEW,
                reason=f"Stale attachment check raised: {exc}",
                evidence=evidence,
            )

    def _check_epoch_ordering(
        self, ctx: ContinuityLegalityContext, path: ContinuityLegalityPath
    ) -> DimensionLegalityOutcome:
        """Check continuity epoch ordering (dimension 4).

        Consults the FlowContinuityCoordinator snapshot to determine whether
        the epoch in *ctx* is acceptably ordered relative to the recorded
        maximum.  A continuity_epoch of 0 is treated as 'unset' and always
        passes.
        """
        dim = ContinuityLegalityDimension.continuity_epoch_ordering
        evidence: Dict[str, Any] = {
            "provided_epoch": ctx.continuity_epoch,
            "path": path.value,
        }

        try:
            from core.flow_continuity_coordinator import (
                get_flow_continuity_coordinator,
            )
            coordinator = get_flow_continuity_coordinator()
            snapshot = coordinator.build_snapshot()
            snap_dict = snapshot.to_dict() if hasattr(snapshot, "to_dict") else {}
            max_epoch_seen: int = int(
                snap_dict.get("max_continuity_epoch", 0) or 0
            )
            evidence["max_epoch_seen"] = max_epoch_seen
        except Exception as _exc:
            logger.debug("Fallback triggered: %s", _exc)
            evidence["coordinator_error"] = str(_exc)
            # Cannot assert ordering without coordinator — pass through
            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.ALLOW,
                reason="",
                evidence=evidence,
            )

        if max_epoch_seen > 0 and ctx.continuity_epoch < max_epoch_seen:
            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.REJECT,
                reason=(
                    f"Continuity epoch {ctx.continuity_epoch} is behind "
                    f"the recorded maximum {max_epoch_seen}. "
                    "This action belongs to a superseded continuity epoch."
                ),
                evidence=evidence,
            )

        return DimensionLegalityOutcome(
            dimension=dim,
            verdict=ContinuityLegalityVerdict.ALLOW,
            reason="",
            evidence=evidence,
        )

    def _check_signal_guard(
        self, ctx: ContinuityLegalityContext, path: ContinuityLegalityPath
    ) -> DimensionLegalityOutcome:
        """Check signal guard dimensions 7–10 via the recovery readiness guard.

        Covers late_signal_rejection, duplicate_signal_rejection,
        out_of_order_signal_rejection, and replay_legality in one pass via
        :func:`core.attached_runtime_recovery_readiness.guard_inbound_signal`.
        """
        dim = ContinuityLegalityDimension.duplicate_signal_rejection
        evidence: Dict[str, Any] = {
            "signal_id": ctx.signal_id,
            "emission_seq": ctx.emission_seq,
            "path": path.value,
        }

        try:
            from core.attached_runtime_recovery_readiness import (
                SignalGuardDecision,
                build_idempotency_key,
                check_signal_guard,
            )
        except Exception as _imp:
            logger.debug("Fallback triggered: %s", _imp)
            evidence["guard_unavailable"] = str(_imp)
            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.REQUIRE_REVIEW,
                reason=f"Signal guard unavailable: {_imp}",
                evidence=evidence,
            )

        try:
            key = build_idempotency_key(
                signal_id=ctx.signal_id,
                contract_id=ctx.contract_id or "",
                session_id=ctx.runtime_session_id or ctx.runtime_attachment_session_id or "",
            )
            decision = check_signal_guard(key, ctx.emission_seq)
            decision_val = (
                decision.value if hasattr(decision, "value") else str(decision)
            )
            evidence["guard_decision"] = decision_val

            if decision is SignalGuardDecision.accept:
                return DimensionLegalityOutcome(
                    dimension=dim,
                    verdict=ContinuityLegalityVerdict.ALLOW,
                    reason="",
                    evidence=evidence,
                )
            if decision is SignalGuardDecision.duplicate:
                return DimensionLegalityOutcome(
                    dimension=ContinuityLegalityDimension.duplicate_signal_rejection,
                    verdict=ContinuityLegalityVerdict.REJECT,
                    reason=f"Duplicate signal: signal_id={ctx.signal_id!r} already seen.",
                    evidence=evidence,
                )
            if decision is SignalGuardDecision.replay:
                # For REPLAY_INGRESS path replay is expected/legal; for others reject
                if path is ContinuityLegalityPath.REPLAY_INGRESS:
                    return DimensionLegalityOutcome(
                        dimension=ContinuityLegalityDimension.replay_legality,
                        verdict=ContinuityLegalityVerdict.ALLOW,
                        reason="Replay signal on REPLAY_INGRESS path — allowed.",
                        evidence=evidence,
                    )
                return DimensionLegalityOutcome(
                    dimension=ContinuityLegalityDimension.replay_legality,
                    verdict=ContinuityLegalityVerdict.REJECT,
                    reason=(
                        f"Replay signal rejected on {path.value} path: "
                        f"emission_seq={ctx.emission_seq} re-emitted at same position."
                    ),
                    evidence=evidence,
                )
            if decision is SignalGuardDecision.stale:
                return DimensionLegalityOutcome(
                    dimension=ContinuityLegalityDimension.late_signal_rejection,
                    verdict=ContinuityLegalityVerdict.REJECT,
                    reason=(
                        f"Late/stale signal: emission_seq={ctx.emission_seq} is far "
                        "behind the recorded maximum."
                    ),
                    evidence=evidence,
                )
            if decision is SignalGuardDecision.out_of_order:
                return DimensionLegalityOutcome(
                    dimension=ContinuityLegalityDimension.out_of_order_signal_rejection,
                    verdict=ContinuityLegalityVerdict.REJECT,
                    reason=(
                        f"Out-of-order signal: emission_seq={ctx.emission_seq} is "
                        "behind the recorded maximum."
                    ),
                    evidence=evidence,
                )

            # Unknown decision — pass through conservatively
            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.ALLOW,
                reason="",
                evidence=evidence,
            )

        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            evidence["check_error"] = str(exc)
            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.REQUIRE_REVIEW,
                reason=f"Signal guard check raised: {exc}",
                evidence=evidence,
            )

    def _check_delegated_recovery_legality(
        self, ctx: ContinuityLegalityContext
    ) -> DimensionLegalityOutcome:
        """Check delegated recovery legality (dimension 11).

        Consults the FlowContinuityCoordinator for the stale-identity verdict
        specific to recovery-oriented paths (delegated/handoff recovery).
        """
        dim = ContinuityLegalityDimension.delegated_recovery_legality
        evidence: Dict[str, Any] = {
            "contract_id": ctx.contract_id,
            "flow_id": ctx.flow_id,
            "device_id": ctx.device_id,
        }

        if not ctx.contract_id and not ctx.flow_id:
            # No delegated flow context — cannot assert illegality
            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.ALLOW,
                reason="",
                evidence=evidence,
            )

        try:
            from core.flow_continuity_coordinator import (
                ContinuityEventContext,
                ContinuityEventKind,
                get_flow_continuity_coordinator,
            )
        except Exception as _imp:
            logger.debug("Fallback triggered: %s", _imp)
            evidence["coordinator_unavailable"] = str(_imp)
            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.REQUIRE_REVIEW,
                reason=f"FlowContinuityCoordinator unavailable: {_imp}",
                evidence=evidence,
            )

        try:
            coordinator = get_flow_continuity_coordinator()
            event_ctx = ContinuityEventContext(
                event_kind=ContinuityEventKind.stale_identity,
                device_id=ctx.device_id,
                session_id=ctx.runtime_session_id,
                runtime_attachment_session_id=ctx.runtime_attachment_session_id,
                contract_id=ctx.contract_id,
                flow_id=ctx.flow_id,
                metadata=dict(ctx.metadata),
            )
            artifact = coordinator.decide_stale_identity(event_ctx)
            decision_val = (
                artifact.decision.value
                if hasattr(artifact.decision, "value")
                else str(artifact.decision)
            )
            evidence["coordinator_decision"] = decision_val
            evidence["coordinator_detail"] = artifact.detail

            if decision_val == "reject_stale_identity":
                return DimensionLegalityOutcome(
                    dimension=dim,
                    verdict=ContinuityLegalityVerdict.REJECT,
                    reason=(
                        f"Delegated recovery rejected: stale identity. "
                        f"{artifact.detail}"
                    ),
                    evidence=evidence,
                )
            if decision_val == "fail_closed":
                return DimensionLegalityOutcome(
                    dimension=dim,
                    verdict=ContinuityLegalityVerdict.REQUIRE_REVIEW,
                    reason=f"Delegated recovery fail_closed: {artifact.detail}",
                    evidence=evidence,
                )
            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.ALLOW,
                reason="",
                evidence=evidence,
            )

        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            evidence["check_error"] = str(exc)
            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.REQUIRE_REVIEW,
                reason=f"Delegated recovery legality check raised: {exc}",
                evidence=evidence,
            )

    def _check_online_execution_legality(
        self, ctx: ContinuityLegalityContext, path: ContinuityLegalityPath
    ) -> DimensionLegalityOutcome:
        """Check online execution legality (dimension 12).

        Applies to ONLINE_DISPATCH_ACCEPTANCE, ONLINE_SIGNAL_INGESTION, and
        TERMINAL_RESULT_INGESTION.  Verifies that the inbound action's
        identity is consistent with the current active runtime/session reality
        — the same check that applies to recovery paths, ensuring that online
        execution is NOT exempt from continuity authority.
        """
        dim = ContinuityLegalityDimension.online_execution_legality
        evidence: Dict[str, Any] = {
            "path": path.value,
            "runtime_session_id": ctx.runtime_session_id,
            "runtime_attachment_session_id": ctx.runtime_attachment_session_id,
            "device_id": ctx.device_id,
        }

        # Delegate to session identity check — same logic, different dimension label
        identity_outcome = self._check_session_identity(ctx)
        if not identity_outcome.verdict.is_rejected():
            return DimensionLegalityOutcome(
                dimension=dim,
                verdict=ContinuityLegalityVerdict.ALLOW,
                reason="",
                evidence={**identity_outcome.evidence, **evidence},
            )

        # Session identity rejected — escalate to this dimension
        return DimensionLegalityOutcome(
            dimension=dim,
            verdict=identity_outcome.verdict,
            reason=(
                f"Online execution legality failed for path={path.value}: "
                f"{identity_outcome.reason}"
            ),
            evidence={**identity_outcome.evidence, **evidence},
        )

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate(
        outcomes: List[DimensionLegalityOutcome],
        path: ContinuityLegalityPath,
        mode: ContinuityLegalityMode,
    ) -> tuple:  # Tuple[ContinuityLegalityVerdict, str]: (overall_verdict, reject_reason)
        """Aggregate dimension outcomes into the overall verdict.

        Rules
        -----
        1. Any REJECT → overall REJECT (earliest rejection wins).
        2. Any REQUIRE_REVIEW on a strict path → REQUIRE_REVIEW (if no REJECT).
        3. All ALLOW (or empty) → ALLOW.
        """
        if not outcomes:
            return ContinuityLegalityVerdict.ALLOW, ""

        for outcome in outcomes:
            if outcome.verdict is ContinuityLegalityVerdict.REJECT:
                return ContinuityLegalityVerdict.REJECT, outcome.reason

        for outcome in outcomes:
            if outcome.verdict is ContinuityLegalityVerdict.REQUIRE_REVIEW:
                if mode == ContinuityLegalityMode.STRICT:
                    return ContinuityLegalityVerdict.REQUIRE_REVIEW, outcome.reason
                # Compat/relaxed modes: REQUIRE_REVIEW is advisory — pass through
                logger.debug(
                    "unified_continuity_legality: REQUIRE_REVIEW advisory "
                    "path=%s mode=%s dim=%s reason=%s — passing through",
                    path.value,
                    mode.value,
                    outcome.dimension.value,
                    outcome.reason,
                )

        return ContinuityLegalityVerdict.ALLOW, ""


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "UNIFIED_CONTINUITY_LEGALITY_AUTHORITY",
    "UNIFIED_CONTINUITY_LEGALITY_AUTHORITY_PR_SENTINEL",
    "ALL_PATHS_MUST_USE_UNIFIED_AUTHORITY_POLICY",
    "CONTINUITY_FIELDS_ARE_ACTIVE_GATE_NOT_PAYLOAD_POLICY",
    "STALE_IDENTITY_MUST_BE_REJECTED_POLICY",
    "ONLINE_EXECUTION_SUBMITS_TO_SAME_AUTHORITY_POLICY",
    "FAIL_CLOSED_ON_AUTHORITY_UNAVAILABILITY_POLICY",
    # Enums
    "ContinuityLegalityPath",
    "ContinuityLegalityDimension",
    "ContinuityLegalityVerdict",
    "ContinuityLegalityMode",
    "DEFAULT_CONTINUITY_LEGALITY_MODE_ENV",
    # Dataclasses
    "ContinuityLegalityContext",
    "DimensionLegalityOutcome",
    "ContinuityLegalityReport",
    # Functions
    "evaluate_continuity_legality",
    "resolve_continuity_legality_mode",
    "get_unified_continuity_legality_authority",
    "reset_unified_continuity_legality_authority",
    # Class
    "UnifiedContinuityLegalityAuthority",
]
