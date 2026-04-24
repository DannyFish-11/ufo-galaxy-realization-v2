#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/compat_legacy_path_blocking_canonicalization.py
=====================================================
PR-8 — Compat / Legacy Path Blocking Canonicalization.

Problem addressed
-----------------
Prior to PR-8 the compat/legacy enforcement skeleton in
``core/compat_fallback_authority_guard.py`` and
``core/legacy_dispatch_registry.py`` operated primarily in
*logging / observability* mode.  Guard helpers returned structured verdicts
and emitted log messages, but by default they did **not** block execution.
This left several invisible-flow vectors open:

* Compat paths could soft-bypass routing decisions without operator
  visibility.
* Truth ingress could be influenced by legacy contracts without a canonical
  gate enforcing single-path ownership.
* Handoff / delegated-flow paths could be contaminated by legacy dispatch
  semantics without a formal quarantine checkpoint.
* Audit and recovery systems could not rely on seeing every compat influence
  event because non-blocking paths produced no mandatory artifact.

This module introduces the **Compat / Legacy Path Blocking Canonicalization**
layer.  It is the single runtime gate that every compat/legacy influence must
cross before reaching a canonical decision surface.  It:

1. **Defines blocking decision semantics** — five formal decision outcomes
   that replace the implicit *log-and-continue* default:

   * ``canonical_path_confirmed``  — no compat influence detected; proceed.
   * ``allow_for_observation_only`` — compat path is whitelisted as a
     read-only observer; allow but record.
   * ``block_due_to_legacy_dispatch`` — compat path attempted dispatch
     authority that belongs to the canonical spine; block and record.
   * ``block_due_to_compat_truth_influence`` — compat path attempted to
     write or assert canonical truth; block and record.
   * ``quarantine_due_to_ambiguous_contract`` — compat/legacy influence is
     present but its contract semantics are ambiguous; quarantine and record
     for operator review.

2. **Provides a runtime enforcement engine** — ``CompatLegacyPathBlockingEnforcer``
   evaluates incoming compat/legacy influence against a policy table and
   emits a ``CompatLegacyBlockingRecord`` artifact for every decision.

3. **Provides operator / audit / recovery artifacts** — every decision
   produces a ``CompatLegacyBlockingRecord`` with full context; a snapshot
   builder aggregates the session decision history for operator inspection and
   release-gate readiness checks.

4. **Is blocking-first by default** — when no explicit whitelist entry
   permits a compat path, the gate blocks.  Operators must explicitly allow
   observation-only paths; silence is denial.

Architecture invariants (PR-8)
--------------------------------
* The canonical path is the **only** legitimate routing, truth, and handoff
  authority.  Any compat/legacy path that attempts to assert equivalent
  authority MUST be blocked at this gate.
* Observation-only exceptions MUST be explicitly declared in
  ``_OBSERVATION_WHITELIST`` with a documented rationale.
* Quarantine is not silence — a quarantined path produces a mandatory audit
  artifact and must not proceed to influence canonical surfaces until an
  operator resolves the contract ambiguity.
* Every blocking or quarantine decision MUST be reflected in the operator
  snapshot and in the audit log.

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`COMPAT_LEGACY_BLOCKING_CANONICALIZATION_AUTHORITY`
:data:`COMPAT_LEGACY_BLOCKING_CANONICALIZATION_PR8_SENTINEL`
:data:`BLOCKING_FIRST_ENFORCEMENT_ACTIVE_POLICY`
:data:`CANONICAL_PATH_IS_SOLE_ROUTING_TRUTH_HANDOFF_AUTHORITY_POLICY`
:data:`COMPAT_SILENT_PASS_THROUGH_IS_PROHIBITED_POLICY`
:data:`LEGACY_DISPATCH_BLOCKING_FIRST_POLICY`
:data:`COMPAT_TRUTH_INFLUENCE_BLOCKING_FIRST_POLICY`
:data:`QUARANTINE_AMBIGUOUS_CONTRACT_POLICY`
:data:`OBSERVATION_ONLY_REQUIRES_EXPLICIT_WHITELIST_POLICY`

Enumerations
~~~~~~~~~~~~
:class:`CompatLegacyBlockingDecision`
:class:`CompatLegacyPathKind`
:class:`CompatLegacyBlockingOutcome`

Data classes
~~~~~~~~~~~~
:class:`CompatLegacyBlockingRecord`
:class:`CompatLegacyBlockingSnapshot`

Classes
~~~~~~~
:class:`CompatLegacyPathBlockingEnforcer`

Functions
~~~~~~~~~
:func:`get_blocking_enforcer`
:func:`enforce_canonical_gate`
:func:`build_blocking_canonicalization_snapshot`
:func:`reset_blocking_enforcer`
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.CompatLegacyPathBlockingCanonicalization")

__all__ = [
    # Sentinels
    "COMPAT_LEGACY_BLOCKING_CANONICALIZATION_AUTHORITY",
    "COMPAT_LEGACY_BLOCKING_CANONICALIZATION_PR8_SENTINEL",
    "BLOCKING_FIRST_ENFORCEMENT_ACTIVE_POLICY",
    "CANONICAL_PATH_IS_SOLE_ROUTING_TRUTH_HANDOFF_AUTHORITY_POLICY",
    "COMPAT_SILENT_PASS_THROUGH_IS_PROHIBITED_POLICY",
    "LEGACY_DISPATCH_BLOCKING_FIRST_POLICY",
    "COMPAT_TRUTH_INFLUENCE_BLOCKING_FIRST_POLICY",
    "QUARANTINE_AMBIGUOUS_CONTRACT_POLICY",
    "OBSERVATION_ONLY_REQUIRES_EXPLICIT_WHITELIST_POLICY",
    # Enumerations
    "CompatLegacyBlockingDecision",
    "CompatLegacyPathKind",
    "CompatLegacyBlockingOutcome",
    # Data classes
    "CompatLegacyBlockingRecord",
    "CompatLegacyBlockingSnapshot",
    # Class
    "CompatLegacyPathBlockingEnforcer",
    # Functions
    "get_blocking_enforcer",
    "enforce_canonical_gate",
    "build_blocking_canonicalization_snapshot",
    "reset_blocking_enforcer",
]


# ===========================================================================
# Authority and policy sentinels
# ===========================================================================

COMPAT_LEGACY_BLOCKING_CANONICALIZATION_AUTHORITY: str = (
    "COMPAT_LEGACY_BLOCKING_CANONICALIZATION_AUTHORITY::"
    "core.compat_legacy_path_blocking_canonicalization is the PR-8 "
    "blocking canonicalization authority for the Galaxy V2 canonical runtime.  "
    "It is the single runtime gate that every compat/legacy influence must "
    "cross before reaching a canonical routing, truth, or handoff surface.  "
    "Blocking-first by default: silence is denial."
)

COMPAT_LEGACY_BLOCKING_CANONICALIZATION_PR8_SENTINEL: str = (
    "COMPAT_LEGACY_BLOCKING_CANONICALIZATION_PR8_SENTINEL::"
    "package=PR8::profile=blocking-canonicalization-v1::"
    "module=core.compat_legacy_path_blocking_canonicalization"
)

BLOCKING_FIRST_ENFORCEMENT_ACTIVE_POLICY: str = (
    "POLICY::BLOCKING_FIRST_ENFORCEMENT_ACTIVE_V1: "
    "The compat/legacy path blocking canonicalization gate operates in "
    "blocking-first mode.  Any compat or legacy influence that is not "
    "explicitly whitelisted as observation-only MUST be blocked at the "
    "canonical gate.  Logging/observability without a formal blocking "
    "record is insufficient and constitutes a policy violation.  "
    "Every compat/legacy influence crossing a canonical decision surface "
    "MUST produce a CompatLegacyBlockingRecord artifact."
)

CANONICAL_PATH_IS_SOLE_ROUTING_TRUTH_HANDOFF_AUTHORITY_POLICY: str = (
    "POLICY::CANONICAL_PATH_IS_SOLE_ROUTING_TRUTH_HANDOFF_AUTHORITY_V1: "
    "The canonical execution spine "
    "(CanonicalTask → TaskEnvelope → CommandRouter.route_envelope()) "
    "is the sole legitimate authority for routing, truth ingress, and "
    "delegated-flow handoff decisions.  Compat and legacy paths MUST NOT "
    "assert equivalent authority or produce equivalent artifacts at these "
    "surfaces.  Any attempt to do so MUST be blocked by this gate and "
    "recorded as block_due_to_legacy_dispatch or "
    "block_due_to_compat_truth_influence."
)

COMPAT_SILENT_PASS_THROUGH_IS_PROHIBITED_POLICY: str = (
    "POLICY::COMPAT_SILENT_PASS_THROUGH_IS_PROHIBITED_V1: "
    "Compat and legacy paths MUST NOT pass through canonical decision "
    "surfaces without producing a formal CompatLegacyBlockingRecord.  "
    "Silent pass-through — reaching canonical routing, truth, or handoff "
    "surfaces without triggering this gate — is a policy violation and "
    "constitutes an invisible flow.  All invisible flows MUST be "
    "converged to this canonical gate."
)

LEGACY_DISPATCH_BLOCKING_FIRST_POLICY: str = (
    "POLICY::LEGACY_DISPATCH_BLOCKING_FIRST_V1: "
    "Any legacy dispatch path that attempts to assert dispatch authority "
    "equivalent to CommandRouter.route_envelope() MUST be blocked at the "
    "canonical gate and produce a block_due_to_legacy_dispatch artifact.  "
    "Legacy dispatch paths registered in legacy_dispatch_registry.py as "
    "FACADE_ONLY or COMPAT_ONLY are permitted only as degraded fallbacks "
    "when the canonical spine is explicitly unavailable; they MUST NOT "
    "silently bypass the canonical spine."
)

COMPAT_TRUTH_INFLUENCE_BLOCKING_FIRST_POLICY: str = (
    "POLICY::COMPAT_TRUTH_INFLUENCE_BLOCKING_FIRST_V1: "
    "Any compat or legacy path that attempts to write, assert, or override "
    "canonical truth (task truth, session truth, result truth, or routing "
    "truth) MUST be blocked at the canonical gate and produce a "
    "block_due_to_compat_truth_influence artifact.  The canonical truth "
    "authority chain (CanonicalTask / CanonicalSessionTruthRuntime / "
    "CanonicalResultRecord) is the sole truth write authority."
)

QUARANTINE_AMBIGUOUS_CONTRACT_POLICY: str = (
    "POLICY::QUARANTINE_AMBIGUOUS_CONTRACT_V1: "
    "When a compat or legacy path presents contract semantics that cannot "
    "be definitively classified as either a pure observer or a canonical "
    "authority violation, the gate MUST quarantine the influence and produce "
    "a quarantine_due_to_ambiguous_contract artifact.  Quarantine is NOT "
    "permission to proceed — the path MUST NOT reach canonical surfaces "
    "until an operator resolves the contract ambiguity.  Ambiguous contracts "
    "are treated as blocked pending resolution."
)

OBSERVATION_ONLY_REQUIRES_EXPLICIT_WHITELIST_POLICY: str = (
    "POLICY::OBSERVATION_ONLY_REQUIRES_EXPLICIT_WHITELIST_V1: "
    "A compat or legacy path may be permitted to observe (read-only, "
    "non-directing) canonical state only when it is explicitly declared in "
    "the observation whitelist with a documented rationale and scope.  "
    "Observation-only paths MUST produce allow_for_observation_only "
    "artifacts.  Unlisted paths that attempt observation are treated as "
    "quarantine_due_to_ambiguous_contract until the operator provides an "
    "explicit whitelist entry."
)


# ===========================================================================
# Enumerations
# ===========================================================================


class CompatLegacyBlockingDecision(str, Enum):
    """The five formal blocking decision outcomes at the canonical gate.

    canonical_path_confirmed
        No compat or legacy influence was detected.  The canonical path is
        the sole active decision authority.  Proceed without restriction.

    allow_for_observation_only
        The compat/legacy path is explicitly whitelisted as a read-only
        observer.  It may observe canonical state but must not alter routing,
        truth, or handoff decisions.  A record artifact is produced.

    block_due_to_legacy_dispatch
        A legacy dispatch path attempted to assert dispatch authority that
        belongs to the canonical execution spine.  The path is blocked.
        A blocking artifact is produced for audit.

    block_due_to_compat_truth_influence
        A compat or legacy path attempted to write, assert, or override
        canonical truth.  The path is blocked.  A blocking artifact is
        produced for audit.

    quarantine_due_to_ambiguous_contract
        The compat/legacy influence is present but its contract semantics
        are ambiguous.  The path is quarantined — it MUST NOT proceed to
        canonical surfaces until an operator resolves the ambiguity.
        A quarantine artifact is produced.
    """

    canonical_path_confirmed = "canonical_path_confirmed"
    allow_for_observation_only = "allow_for_observation_only"
    block_due_to_legacy_dispatch = "block_due_to_legacy_dispatch"
    block_due_to_compat_truth_influence = "block_due_to_compat_truth_influence"
    quarantine_due_to_ambiguous_contract = "quarantine_due_to_ambiguous_contract"


class CompatLegacyPathKind(str, Enum):
    """Classification of the type of compat/legacy path being evaluated.

    legacy_dispatch
        A path that bypasses the canonical execution spine for dispatch.

    compat_truth
        A path that asserts or modifies canonical truth outside the canonical
        truth authority chain.

    handoff_bypass
        A path that bypasses the canonical HandoffContract / AgentBridge
        handoff chain.

    route_bypass
        A path that bypasses canonical route resolution (CommandRouter /
        DeviceRouter).

    recovery_injection
        A path that injects legacy recovery semantics into the canonical
        recovery or continuity path.

    observation_candidate
        A path that appears to be read-only but has not yet been verified;
        pending whitelist confirmation.
    """

    legacy_dispatch = "legacy_dispatch"
    compat_truth = "compat_truth"
    handoff_bypass = "handoff_bypass"
    route_bypass = "route_bypass"
    recovery_injection = "recovery_injection"
    observation_candidate = "observation_candidate"


class CompatLegacyBlockingOutcome(str, Enum):
    """High-level outcome of a gate evaluation (is execution allowed?).

    allowed
        Execution may proceed.  Applies to canonical_path_confirmed and
        allow_for_observation_only decisions.

    blocked
        Execution is blocked.  Applies to block_due_to_legacy_dispatch and
        block_due_to_compat_truth_influence decisions.

    quarantined
        Execution is held pending operator resolution.  Applies to
        quarantine_due_to_ambiguous_contract.
    """

    allowed = "allowed"
    blocked = "blocked"
    quarantined = "quarantined"


# ===========================================================================
# Data classes
# ===========================================================================


@dataclass
class CompatLegacyBlockingRecord:
    """Artifact produced by the canonical gate for every compat/legacy evaluation.

    Every CompatLegacyBlockingRecord is an auditable, operator-visible record
    of a canonical-gate decision.  Records are stored in the enforcer's
    decision history and included in snapshots for operator / audit /
    recovery / readiness inspection.

    Fields
    ------
    record_id
        Unique identifier for this record (UUID hex prefix).
    decision
        The formal blocking decision outcome.
    outcome
        Whether execution is allowed, blocked, or quarantined.
    path_kind
        Classification of the compat/legacy path kind.
    calling_site
        Human-readable description of the decision site (e.g. module or
        function name) where the gate was invoked.
    compat_path
        Identifier or description of the compat/legacy path being evaluated.
    canonical_path
        Identifier or description of the canonical path that should be the
        sole authority at this site.
    rationale
        Human-readable explanation of why this decision was reached.
    influence_id
        Optional reference to the CompatInfluenceRecord in
        ``compat_fallback_authority_guard.py`` (e.g. ``"INFL-011"``).
    operator_note
        Optional note from the operator or policy entry for operator review.
    timestamp
        Unix timestamp of the decision.
    """

    record_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    decision: CompatLegacyBlockingDecision = (
        CompatLegacyBlockingDecision.canonical_path_confirmed
    )
    outcome: CompatLegacyBlockingOutcome = CompatLegacyBlockingOutcome.allowed
    path_kind: CompatLegacyPathKind = CompatLegacyPathKind.observation_candidate
    calling_site: str = ""
    compat_path: str = ""
    canonical_path: str = ""
    rationale: str = ""
    influence_id: str = ""
    operator_note: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "decision": self.decision.value,
            "outcome": self.outcome.value,
            "path_kind": self.path_kind.value,
            "calling_site": self.calling_site,
            "compat_path": self.compat_path,
            "canonical_path": self.canonical_path,
            "rationale": self.rationale,
            "influence_id": self.influence_id,
            "operator_note": self.operator_note,
            "timestamp": self.timestamp,
        }

    @property
    def is_blocked(self) -> bool:
        """Return True when this record represents a blocking decision."""
        return self.outcome == CompatLegacyBlockingOutcome.blocked

    @property
    def is_quarantined(self) -> bool:
        """Return True when this record represents a quarantine decision."""
        return self.outcome == CompatLegacyBlockingOutcome.quarantined

    @property
    def is_allowed(self) -> bool:
        """Return True when this record represents an allow decision."""
        return self.outcome == CompatLegacyBlockingOutcome.allowed


@dataclass
class CompatLegacyBlockingSnapshot:
    """Aggregate snapshot of compat/legacy blocking canonicalization state.

    Suitable for operator inspection, CI release-gate evaluation, and
    recovery / readiness checks.

    Fields
    ------
    total_evaluations
        Total number of gate evaluations recorded in this session.
    canonical_confirmed_count
        Evaluations with canonical_path_confirmed decision.
    observation_allowed_count
        Evaluations with allow_for_observation_only decision.
    blocked_legacy_dispatch_count
        Evaluations with block_due_to_legacy_dispatch decision.
    blocked_compat_truth_count
        Evaluations with block_due_to_compat_truth_influence decision.
    quarantined_count
        Evaluations with quarantine_due_to_ambiguous_contract decision.
    invisible_flow_count
        Sum of all non-canonical outcomes that did not produce a proper
        blocking artifact (should always be 0; non-zero is a policy
        violation indicator).
    blocking_canonicalization_healthy
        ``True`` when quarantined_count == 0 and invisible_flow_count == 0.
        Indicates no unresolved quarantines or invisible flows.
    policy_sentinels
        List of active policy sentinel strings for operator reference.
    recent_records
        Most recent blocking records (last N) for operator inspection.
    generated_at
        Unix timestamp of snapshot generation.
    """

    total_evaluations: int = 0
    canonical_confirmed_count: int = 0
    observation_allowed_count: int = 0
    blocked_legacy_dispatch_count: int = 0
    blocked_compat_truth_count: int = 0
    quarantined_count: int = 0
    invisible_flow_count: int = 0
    blocking_canonicalization_healthy: bool = True
    policy_sentinels: List[str] = field(default_factory=list)
    recent_records: List[Dict[str, Any]] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_evaluations": self.total_evaluations,
            "by_decision": {
                "canonical_path_confirmed": self.canonical_confirmed_count,
                "allow_for_observation_only": self.observation_allowed_count,
                "block_due_to_legacy_dispatch": self.blocked_legacy_dispatch_count,
                "block_due_to_compat_truth_influence": self.blocked_compat_truth_count,
                "quarantine_due_to_ambiguous_contract": self.quarantined_count,
            },
            "invisible_flow_count": self.invisible_flow_count,
            "blocking_canonicalization_healthy": self.blocking_canonicalization_healthy,
            "policy_sentinels": self.policy_sentinels,
            "recent_records": self.recent_records,
            "generated_at": self.generated_at,
        }


# ===========================================================================
# Observation whitelist
# ===========================================================================

@dataclass
class _ObservationWhitelistEntry:
    """Internal record for explicitly whitelisted observation-only paths."""

    path_id: str
    """Identifier matching the compat_path argument passed to enforce_canonical_gate."""

    rationale: str
    """Documented rationale for why this path is permitted as observer-only."""

    scope: str
    """Scope restriction for the observer permission (e.g. 'read projection state')."""

    pr_origin: str = "PR-8"


# Paths that are explicitly whitelisted as observation-only.
# These MUST NOT write to or drive any canonical surface.
# Entries are keyed by path_id (matched against compat_path argument).
_OBSERVATION_WHITELIST: Dict[str, _ObservationWhitelistEntry] = {
    "core.runtime_closure_audit": _ObservationWhitelistEntry(
        path_id="core.runtime_closure_audit",
        rationale=(
            "Runtime closure audit is a read-only diagnostic surface.  "
            "It observes canonical closure state but does not drive decisions."
        ),
        scope="read-only runtime closure health check",
        pr_origin="PR-8",
    ),
    "core.authority_boundary_classification": _ObservationWhitelistEntry(
        path_id="core.authority_boundary_classification",
        rationale=(
            "Authority boundary classification is a read-only classification "
            "surface.  It does not alter routing, truth, or handoff decisions."
        ),
        scope="read-only authority surface classification",
        pr_origin="PR-8",
    ),
    "core.compat_surface_retirement": _ObservationWhitelistEntry(
        path_id="core.compat_surface_retirement",
        rationale=(
            "Compat surface retirement inventory is a read-only audit surface.  "
            "It observes retirement status but does not alter canonical state."
        ),
        scope="read-only compat surface retirement inventory observation",
        pr_origin="PR-8",
    ),
}


# ===========================================================================
# CompatLegacyPathBlockingEnforcer
# ===========================================================================


class CompatLegacyPathBlockingEnforcer:
    """Blocking-first enforcement engine for compat/legacy path canonicalization.

    This is the canonical gate that every compat/legacy influence must cross
    before reaching canonical routing, truth, or handoff surfaces.

    The enforcer maintains a decision history for operator/audit inspection.
    Use :func:`get_blocking_enforcer` to obtain the process-global singleton.

    Policy
    ------
    * Blocking-first by default: any compat/legacy path that is not explicitly
      whitelisted as observation-only is blocked or quarantined.
    * Every decision produces a :class:`CompatLegacyBlockingRecord` artifact.
    * Decisions are stored in ``_decision_history`` for snapshot generation.

    Usage
    -----
    ::

        enforcer = get_blocking_enforcer()
        record = enforcer.evaluate(
            calling_site="core.some_module.SomeClass.some_method",
            compat_path="core.legacy_task_queue",
            canonical_path="core.canonical_task.CanonicalTask",
            path_kind=CompatLegacyPathKind.legacy_dispatch,
        )
        if record.is_blocked:
            raise RuntimeError(f"Canonical gate blocked: {record.rationale}")
    """

    _MAX_HISTORY: int = 1000
    """Maximum number of recent records to retain in memory."""

    def __init__(self) -> None:
        self._decision_history: List[CompatLegacyBlockingRecord] = []

    # ------------------------------------------------------------------
    # Core gate evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        calling_site: str,
        compat_path: str,
        canonical_path: str,
        path_kind: CompatLegacyPathKind,
        *,
        compat_influence_active: bool = True,
        influence_id: str = "",
        operator_note: str = "",
        raise_on_block: bool = False,
    ) -> CompatLegacyBlockingRecord:
        """Evaluate a compat/legacy influence against the canonical gate.

        Parameters
        ----------
        calling_site:
            Human-readable description of the decision site where the gate is
            being invoked (e.g. ``"core.some_module.SomeClass.method"``).
        compat_path:
            Identifier or description of the compat/legacy path being
            evaluated.
        canonical_path:
            Identifier or description of the canonical path that is the sole
            authority at this site.
        path_kind:
            :class:`CompatLegacyPathKind` classification of the compat path.
        compat_influence_active:
            ``True`` (default) when the compat/legacy path is actively
            attempting to influence the decision.  ``False`` means no
            compat influence detected — returns canonical_path_confirmed.
        influence_id:
            Optional reference to a CompatInfluenceRecord in
            ``compat_fallback_authority_guard.py``.
        operator_note:
            Optional note for operator visibility.
        raise_on_block:
            When ``True``, raise :class:`CompatLegacyBlockingError` if the
            gate produces a blocking or quarantine decision.  Default is
            ``False`` (record and return, caller handles).

        Returns
        -------
        CompatLegacyBlockingRecord
        """
        record = self._make_decision(
            calling_site=calling_site,
            compat_path=compat_path,
            canonical_path=canonical_path,
            path_kind=path_kind,
            compat_influence_active=compat_influence_active,
            influence_id=influence_id,
            operator_note=operator_note,
        )
        self._record(record)
        self._emit_log(record)
        if raise_on_block and record.outcome in (
            CompatLegacyBlockingOutcome.blocked,
            CompatLegacyBlockingOutcome.quarantined,
        ):
            raise CompatLegacyBlockingError(record)
        return record

    def _make_decision(
        self,
        *,
        calling_site: str,
        compat_path: str,
        canonical_path: str,
        path_kind: CompatLegacyPathKind,
        compat_influence_active: bool,
        influence_id: str,
        operator_note: str,
    ) -> CompatLegacyBlockingRecord:
        """Compute the blocking decision for the given inputs."""

        # ── No compat influence: canonical path is confirmed ────────────
        if not compat_influence_active:
            return CompatLegacyBlockingRecord(
                decision=CompatLegacyBlockingDecision.canonical_path_confirmed,
                outcome=CompatLegacyBlockingOutcome.allowed,
                path_kind=path_kind,
                calling_site=calling_site,
                compat_path=compat_path,
                canonical_path=canonical_path,
                rationale=(
                    "No compat/legacy influence detected.  "
                    "Canonical path is the sole active authority."
                ),
                influence_id=influence_id,
                operator_note=operator_note,
            )

        # ── Check observation whitelist ─────────────────────────────────
        whitelist_entry = _OBSERVATION_WHITELIST.get(compat_path)
        if whitelist_entry is not None:
            return CompatLegacyBlockingRecord(
                decision=CompatLegacyBlockingDecision.allow_for_observation_only,
                outcome=CompatLegacyBlockingOutcome.allowed,
                path_kind=path_kind,
                calling_site=calling_site,
                compat_path=compat_path,
                canonical_path=canonical_path,
                rationale=(
                    f"Compat path is explicitly whitelisted for observation-only "
                    f"access.  Scope: {whitelist_entry.scope}.  "
                    f"Rationale: {whitelist_entry.rationale}"
                ),
                influence_id=influence_id,
                operator_note=operator_note or whitelist_entry.rationale,
            )

        # ── Evaluate by path kind ───────────────────────────────────────
        if path_kind == CompatLegacyPathKind.legacy_dispatch:
            return CompatLegacyBlockingRecord(
                decision=CompatLegacyBlockingDecision.block_due_to_legacy_dispatch,
                outcome=CompatLegacyBlockingOutcome.blocked,
                path_kind=path_kind,
                calling_site=calling_site,
                compat_path=compat_path,
                canonical_path=canonical_path,
                rationale=(
                    f"BLOCKING: legacy dispatch path {compat_path!r} attempted "
                    f"dispatch authority at {calling_site!r}.  "
                    f"Canonical spine {canonical_path!r} is the sole dispatch "
                    f"authority.  "
                    f"Policy: {LEGACY_DISPATCH_BLOCKING_FIRST_POLICY[:80]}…"
                ),
                influence_id=influence_id,
                operator_note=operator_note,
            )

        if path_kind == CompatLegacyPathKind.compat_truth:
            return CompatLegacyBlockingRecord(
                decision=(
                    CompatLegacyBlockingDecision.block_due_to_compat_truth_influence
                ),
                outcome=CompatLegacyBlockingOutcome.blocked,
                path_kind=path_kind,
                calling_site=calling_site,
                compat_path=compat_path,
                canonical_path=canonical_path,
                rationale=(
                    f"BLOCKING: compat truth path {compat_path!r} attempted to "
                    f"influence canonical truth at {calling_site!r}.  "
                    f"Canonical truth authority {canonical_path!r} is the sole "
                    f"truth write authority.  "
                    f"Policy: {COMPAT_TRUTH_INFLUENCE_BLOCKING_FIRST_POLICY[:80]}…"
                ),
                influence_id=influence_id,
                operator_note=operator_note,
            )

        if path_kind in (
            CompatLegacyPathKind.handoff_bypass,
            CompatLegacyPathKind.route_bypass,
            CompatLegacyPathKind.recovery_injection,
        ):
            # Treat handoff bypass, route bypass, and recovery injection as
            # legacy dispatch equivalents — block with legacy dispatch decision.
            return CompatLegacyBlockingRecord(
                decision=CompatLegacyBlockingDecision.block_due_to_legacy_dispatch,
                outcome=CompatLegacyBlockingOutcome.blocked,
                path_kind=path_kind,
                calling_site=calling_site,
                compat_path=compat_path,
                canonical_path=canonical_path,
                rationale=(
                    f"BLOCKING: {path_kind.value} path {compat_path!r} attempted "
                    f"to bypass canonical authority at {calling_site!r}.  "
                    f"path_kind={path_kind.value} is treated as a legacy dispatch "
                    f"authority violation.  "
                    f"Canonical path: {canonical_path!r}."
                ),
                influence_id=influence_id,
                operator_note=operator_note,
            )

        # ── observation_candidate — ambiguous; quarantine ───────────────
        return CompatLegacyBlockingRecord(
            decision=(
                CompatLegacyBlockingDecision.quarantine_due_to_ambiguous_contract
            ),
            outcome=CompatLegacyBlockingOutcome.quarantined,
            path_kind=path_kind,
            calling_site=calling_site,
            compat_path=compat_path,
            canonical_path=canonical_path,
            rationale=(
                f"QUARANTINE: compat path {compat_path!r} at {calling_site!r} "
                f"has ambiguous contract semantics (path_kind="
                f"{path_kind.value}).  "
                "Path is quarantined pending operator resolution.  "
                "Add an explicit observation whitelist entry or reclassify "
                "path_kind to resolve the quarantine.  "
                f"Policy: {QUARANTINE_AMBIGUOUS_CONTRACT_POLICY[:80]}…"
            ),
            influence_id=influence_id,
            operator_note=operator_note,
        )

    def _record(self, record: CompatLegacyBlockingRecord) -> None:
        """Append record to history, capping at _MAX_HISTORY."""
        self._decision_history.append(record)
        if len(self._decision_history) > self._MAX_HISTORY:
            self._decision_history = self._decision_history[-self._MAX_HISTORY :]

    def _emit_log(self, record: CompatLegacyBlockingRecord) -> None:
        """Emit a structured log message for the decision."""
        if record.outcome == CompatLegacyBlockingOutcome.allowed:
            if record.decision == CompatLegacyBlockingDecision.canonical_path_confirmed:
                logger.debug(
                    "COMPAT_BLOCKING_GATE [%s] canonical_path_confirmed | "
                    "site=%s canonical=%s",
                    record.record_id,
                    record.calling_site,
                    record.canonical_path,
                )
            else:
                logger.info(
                    "COMPAT_BLOCKING_GATE [%s] allow_for_observation_only | "
                    "site=%s compat=%s",
                    record.record_id,
                    record.calling_site,
                    record.compat_path,
                )
        elif record.outcome == CompatLegacyBlockingOutcome.blocked:
            logger.error(
                "COMPAT_BLOCKING_GATE [%s] BLOCKED decision=%s | "
                "site=%s compat=%s canonical=%s | %s",
                record.record_id,
                record.decision.value,
                record.calling_site,
                record.compat_path,
                record.canonical_path,
                record.rationale,
            )
        else:
            logger.warning(
                "COMPAT_BLOCKING_GATE [%s] QUARANTINED | "
                "site=%s compat=%s | %s",
                record.record_id,
                record.calling_site,
                record.compat_path,
                record.rationale,
            )

    def decision_history(self) -> List[CompatLegacyBlockingRecord]:
        """Return a copy of the decision history."""
        return list(self._decision_history)

    def snapshot(self, recent_n: int = 20) -> CompatLegacyBlockingSnapshot:
        """Build a :class:`CompatLegacyBlockingSnapshot` from current history."""
        history = self._decision_history
        canonical_count = sum(
            1 for r in history
            if r.decision == CompatLegacyBlockingDecision.canonical_path_confirmed
        )
        obs_count = sum(
            1 for r in history
            if r.decision == CompatLegacyBlockingDecision.allow_for_observation_only
        )
        block_dispatch_count = sum(
            1 for r in history
            if r.decision == CompatLegacyBlockingDecision.block_due_to_legacy_dispatch
        )
        block_truth_count = sum(
            1 for r in history
            if r.decision
            == CompatLegacyBlockingDecision.block_due_to_compat_truth_influence
        )
        quarantine_count = sum(
            1 for r in history
            if r.decision
            == CompatLegacyBlockingDecision.quarantine_due_to_ambiguous_contract
        )
        total = len(history)
        accounted = (
            canonical_count
            + obs_count
            + block_dispatch_count
            + block_truth_count
            + quarantine_count
        )
        invisible = total - accounted  # should always be 0
        healthy = quarantine_count == 0 and invisible == 0
        recent = [
            r.to_dict() for r in history[-recent_n:]
        ]
        return CompatLegacyBlockingSnapshot(
            total_evaluations=total,
            canonical_confirmed_count=canonical_count,
            observation_allowed_count=obs_count,
            blocked_legacy_dispatch_count=block_dispatch_count,
            blocked_compat_truth_count=block_truth_count,
            quarantined_count=quarantine_count,
            invisible_flow_count=invisible,
            blocking_canonicalization_healthy=healthy,
            policy_sentinels=[
                BLOCKING_FIRST_ENFORCEMENT_ACTIVE_POLICY,
                CANONICAL_PATH_IS_SOLE_ROUTING_TRUTH_HANDOFF_AUTHORITY_POLICY,
                COMPAT_SILENT_PASS_THROUGH_IS_PROHIBITED_POLICY,
                LEGACY_DISPATCH_BLOCKING_FIRST_POLICY,
                COMPAT_TRUTH_INFLUENCE_BLOCKING_FIRST_POLICY,
                QUARANTINE_AMBIGUOUS_CONTRACT_POLICY,
                OBSERVATION_ONLY_REQUIRES_EXPLICIT_WHITELIST_POLICY,
            ],
            recent_records=recent,
            generated_at=time.time(),
        )


# ===========================================================================
# Exception
# ===========================================================================


class CompatLegacyBlockingError(RuntimeError):
    """Raised when raise_on_block=True and the gate blocks or quarantines.

    Attributes
    ----------
    blocking_record
        The :class:`CompatLegacyBlockingRecord` that triggered the raise.
    """

    def __init__(self, blocking_record: CompatLegacyBlockingRecord) -> None:
        self.blocking_record = blocking_record
        super().__init__(
            f"CompatLegacyBlockingError: {blocking_record.decision.value} | "
            f"site={blocking_record.calling_site!r} "
            f"compat={blocking_record.compat_path!r} | "
            f"{blocking_record.rationale}"
        )


# ===========================================================================
# Singleton management
# ===========================================================================

_enforcer_instance: Optional[CompatLegacyPathBlockingEnforcer] = None


def get_blocking_enforcer() -> CompatLegacyPathBlockingEnforcer:
    """Return the process-global :class:`CompatLegacyPathBlockingEnforcer` singleton."""
    global _enforcer_instance
    if _enforcer_instance is None:
        _enforcer_instance = CompatLegacyPathBlockingEnforcer()
    return _enforcer_instance


def reset_blocking_enforcer() -> None:
    """Reset the singleton (for testing only)."""
    global _enforcer_instance
    _enforcer_instance = None


# ===========================================================================
# Module-level convenience function
# ===========================================================================


def enforce_canonical_gate(
    calling_site: str,
    compat_path: str,
    canonical_path: str,
    path_kind: CompatLegacyPathKind,
    *,
    compat_influence_active: bool = True,
    influence_id: str = "",
    operator_note: str = "",
    raise_on_block: bool = False,
) -> CompatLegacyBlockingRecord:
    """Evaluate a compat/legacy influence at the canonical gate.

    Convenience wrapper around
    ``get_blocking_enforcer().evaluate()``.

    Parameters
    ----------
    calling_site:
        Human-readable description of the decision site.
    compat_path:
        Identifier of the compat/legacy path being evaluated.
    canonical_path:
        Identifier of the canonical authority at this site.
    path_kind:
        :class:`CompatLegacyPathKind` of the compat path.
    compat_influence_active:
        Whether compat influence is actively present.
    influence_id:
        Optional reference to CompatInfluenceRecord.
    operator_note:
        Optional operator note.
    raise_on_block:
        Raise :class:`CompatLegacyBlockingError` on block/quarantine.

    Returns
    -------
    CompatLegacyBlockingRecord
    """
    return get_blocking_enforcer().evaluate(
        calling_site=calling_site,
        compat_path=compat_path,
        canonical_path=canonical_path,
        path_kind=path_kind,
        compat_influence_active=compat_influence_active,
        influence_id=influence_id,
        operator_note=operator_note,
        raise_on_block=raise_on_block,
    )


def build_blocking_canonicalization_snapshot(
    recent_n: int = 20,
) -> CompatLegacyBlockingSnapshot:
    """Build an aggregate snapshot of the blocking canonicalization state.

    Returns
    -------
    CompatLegacyBlockingSnapshot
        Suitable for operator inspection, CI release-gate evaluation, and
        recovery / readiness checks.
    """
    return get_blocking_enforcer().snapshot(recent_n=recent_n)
