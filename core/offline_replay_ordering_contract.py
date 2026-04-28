#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/offline_replay_ordering_contract.py
=========================================
PR-P0-3 (post-533 dual-repo runtime-unification track):
Authoritative V2-side Offline Replay Ordering Contract.

Problem addressed
-----------------
The dual-repo system has an honest, acknowledged gap (P0-3):

* Android PR-277 formalised offline queue replay ordering / authority
  semantics, but explicitly recorded:
  - replay ordering guarantee = DEFERRED
  - replay authority           = NON_AUTHORITATIVE (Android side)
  - duplicate avoidance        = PARTIALLY_SUPPORTED
  - eventual recovery          = ACCEPTED_LIMITATION

* V2 side (``core.recovery_durability_closure_validator`` RS-16) reflected
  this as ``deferred`` and provided no authoritative ownership statement.

The gap is not whether a replay queue *exists* on Android — it does.  The
gap is:

1. **Who is the replay ordering authority?**
2. **What are the formal ordering semantics?**
3. **Where is the authoritative duplicate-avoidance boundary?**
4. **How does replay relate to canonical task continuity?**
5. **How does replay relate to truth convergence / result reconciliation?**

This module closes gap P0-3 by establishing the **V2-side Authoritative
Offline Replay Ordering Contract** — a structured, machine-consumable,
testable policy layer that:

* Declares V2 as the **replay ordering authority** (Android provides the
  queue drain; V2 defines what ordering is valid and enforces it via the
  signal guard).
* Defines the **formal ordering semantics** for replay sequences.
* Establishes the **authoritative duplicate-avoidance boundary** (V2 signal
  guard + idempotency registry, not Android-local deduplication alone).
* Specifies the **canonical interpretation** of replay sequences under
  normal, out-of-order, duplicate, stale, and partial scenarios.
* Expresses the **continuity and truth-convergence relations** for replayed
  tasks.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────────┐
    │  OFFLINE REPLAY ORDERING CONTRACT  (this module — PR-P0-3)          │
    │                                                                      │
    │  Declares:                                                           │
    │    • V2 IS the replay ordering authority                            │
    │    • Formal ordering semantics (FIFO within-session; best-effort    │
    │      across sessions; stale window enforcement)                     │
    │    • Duplicate-avoidance boundary: V2 signal guard + idempotency   │
    │    • Canonical replay sequence interpretation                       │
    │    • Continuity and truth-convergence relations                     │
    │                                                                      │
    │  Provides:                                                           │
    │    • evaluate_replay_sequence()  — validates a replay sequence      │
    │      against the contract; returns per-item decisions + verdict     │
    │    • build_offline_replay_ordering_report() — baseline report for   │
    │      this process instance (no live drain yet → not_yet_evidenced)  │
    │    • get / reset singletons for test isolation                      │
    │                                                                      │
    │  Consumed by:                                                        │
    │    • core.recovery_durability_closure_validator  (RS-16 → advisory) │
    │    • core.recovery_truth_surface  (extra evidence signal)           │
    │    • system_final_acceptance_verdict (recovery_truth_surface dim)   │
    │    • Tests (test_offline_replay_ordering_contract.py)               │
    └──────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified by importing this.
2. **Policy-sentinel-first** — every boundary and rule is expressed as a
   named, importable, non-empty string constant.
3. **Fail-conservative** — ambiguous authority MUST NOT be optimistically
   upgraded to ``authoritative_contract_defined``; it MUST produce
   ``downgraded``.
4. **Honest partial** — absence of live replay evidence yields
   ``contract_not_yet_evidenced``, not ``authoritative_contract_defined``.
   The *contract* is always defined; the *evidence* may be partial.
5. **Testable** — ``evaluate_replay_sequence()`` is a pure function (given
   a list of item dicts) so automated tests can exercise every semantic
   without requiring a live Android participant.

Sentinel constants
------------------
:data:`OFFLINE_REPLAY_ORDERING_CONTRACT_AUTHORITY`
    Affirms this module is the canonical V2-side offline replay ordering
    contract authority.

:data:`OFFLINE_REPLAY_ORDERING_CONTRACT_PR_P03_SENTINEL`
    Monotonic sentinel string for PR-P0-3 feature identification.

:data:`V2_IS_REPLAY_ORDERING_AUTHORITY_POLICY`
    V2 is the authoritative owner of replay ordering semantics.  Android
    provides the queue drain; V2 decides what ordering is valid.

:data:`REPLAY_ORDERING_FORMAL_SEMANTICS_POLICY`
    Formal semantics: items MUST arrive in non-decreasing ``seq`` order
    within a single session.  Items whose ``seq`` is below the current
    session maximum by more than :data:`STALE_SEQ_WINDOW` are stale and
    MUST be rejected.  Items with the same ``item_id`` seen more than once
    MUST be rejected as duplicates regardless of seq.

:data:`DUPLICATE_AVOIDANCE_BOUNDARY_IS_V2_SIGNAL_GUARD_POLICY`
    The authoritative duplicate-avoidance boundary is V2's signal guard
    (``core.attached_runtime_recovery_readiness``) plus the idempotency
    registry in ``core.delegated_flow_recovery_coordinator``.  Android-local
    deduplication is advisory only.

:data:`STALE_REPLAY_MUST_DOWNGRADE_NOT_ACCEPT_POLICY`
    A stale replay item (``seq`` more than :data:`STALE_SEQ_WINDOW` below
    current session maximum) MUST produce decision ``reject_stale`` and MUST
    NOT be silently accepted.

:data:`OUT_OF_ORDER_REPLAY_MUST_NOT_SILENTLY_ACCEPT_POLICY`
    An out-of-order replay item (``seq`` below current session maximum but
    within the stale window) MUST produce decision ``reject_out_of_order``
    and MUST NOT be silently accepted.

:data:`AMBIGUOUS_AUTHORITY_MUST_NOT_OPTIMISTICALLY_UPGRADE_POLICY`
    When the authority cannot be positively confirmed as V2-side, the
    overall contract verdict MUST be ``downgraded`` and MUST NOT be
    ``authoritative_contract_defined``.  Silence is not acceptance.

:data:`PARTIAL_REPLAY_STAYS_ADVISORY_NOT_FULLY_CLOSED_POLICY`
    A replay sequence that is only partially received (not all expected
    items arrived or the session terminated before drain completion) MUST
    NOT be promoted to a fully-closed status.  The verdict MUST remain
    ``contract_partially_evidenced`` at best.

:data:`REPLAY_CONTINUITY_REQUIRES_CANONICAL_TASK_IDENTITY_POLICY`
    A replayed task item is only considered continuity-preserving when
    the replayed ``task_id`` or ``correlation_id`` matches a known
    in-flight delegated task recorded by V2 before the disconnect.
    Unknown ``task_id`` values from replay MUST be treated as new
    attachments, not as continuations.

:data:`REPLAY_TRUTH_CONVERGENCE_REQUIRES_V2_ABSORPTION_POLICY`
    Truth convergence for a replayed task result requires V2 to explicitly
    absorb the result into its canonical task state (via
    ``canonical_completion_ingress`` or equivalent).  A replayed result
    that V2 has not absorbed is NOT considered truth-converged.

Public API
----------
Enumerations::

    ReplayOrderingAuthority
    ReplayOrderingGuarantee
    DuplicateAvoidanceBoundary
    ReplaySequenceStatus
    OfflineReplayItemDecision
    OfflineReplayContractVerdict

Dataclasses::

    OfflineReplayItemEvaluation
    OfflineReplayOrderingReport

Constants::

    STALE_SEQ_WINDOW

Functions::

    evaluate_replay_sequence
    build_offline_replay_ordering_report
    get_offline_replay_ordering_report
    reset_offline_replay_ordering_report
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("Galaxy.OfflineReplayOrderingContract")

# ---------------------------------------------------------------------------
# Public __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "OFFLINE_REPLAY_ORDERING_CONTRACT_AUTHORITY",
    "OFFLINE_REPLAY_ORDERING_CONTRACT_PR_P03_SENTINEL",
    "V2_IS_REPLAY_ORDERING_AUTHORITY_POLICY",
    "REPLAY_ORDERING_FORMAL_SEMANTICS_POLICY",
    "DUPLICATE_AVOIDANCE_BOUNDARY_IS_V2_SIGNAL_GUARD_POLICY",
    "STALE_REPLAY_MUST_DOWNGRADE_NOT_ACCEPT_POLICY",
    "OUT_OF_ORDER_REPLAY_MUST_NOT_SILENTLY_ACCEPT_POLICY",
    "AMBIGUOUS_AUTHORITY_MUST_NOT_OPTIMISTICALLY_UPGRADE_POLICY",
    "PARTIAL_REPLAY_STAYS_ADVISORY_NOT_FULLY_CLOSED_POLICY",
    "REPLAY_CONTINUITY_REQUIRES_CANONICAL_TASK_IDENTITY_POLICY",
    "REPLAY_TRUTH_CONVERGENCE_REQUIRES_V2_ABSORPTION_POLICY",
    # Constants
    "STALE_SEQ_WINDOW",
    # Enumerations
    "ReplayOrderingAuthority",
    "ReplayOrderingGuarantee",
    "DuplicateAvoidanceBoundary",
    "ReplaySequenceStatus",
    "OfflineReplayItemDecision",
    "OfflineReplayContractVerdict",
    # Dataclasses
    "OfflineReplayItemEvaluation",
    "OfflineReplayOrderingReport",
    # Functions
    "evaluate_replay_sequence",
    "build_offline_replay_ordering_report",
    "get_offline_replay_ordering_report",
    "reset_offline_replay_ordering_report",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

OFFLINE_REPLAY_ORDERING_CONTRACT_AUTHORITY: str = (
    "OFFLINE_REPLAY_ORDERING_CONTRACT_AUTHORITY::"
    "core.offline_replay_ordering_contract::PR-P0-3::"
    "v2-side-authoritative-offline-replay-ordering-contract-for-galaxy"
)
"""Sentinel: this module is the canonical V2-side authority for offline
replay ordering semantics.

Import to assert that a recovery pipeline, acceptance verdict, or
cross-repo evidence consumer is reading the ordering contract from the
correct canonical module rather than deriving ordering semantics ad-hoc."""

OFFLINE_REPLAY_ORDERING_CONTRACT_PR_P03_SENTINEL: str = (
    "OFFLINE_REPLAY_ORDERING_CONTRACT_PR_P03_SENTINEL::"
    "package=PR-P0-3::profile=offline-replay-ordering-contract-v1::"
    "module=core.offline_replay_ordering_contract::"
    "resolves=RS-16-deferred"
)
"""Package sentinel for PR-P0-3 (resolves P0-3 gap: offline queue replay
ordering deferred)."""

V2_IS_REPLAY_ORDERING_AUTHORITY_POLICY: str = (
    "POLICY::V2_IS_REPLAY_ORDERING_AUTHORITY_PR_P03: "
    "V2 is the authoritative owner of offline replay ordering semantics.  "
    "Android provides the queue drain sequence; V2 defines what ordering is "
    "valid, enforces ordering via the signal guard "
    "(core.attached_runtime_recovery_readiness), and decides the canonical "
    "interpretation of each replayed item (accept / reject_duplicate / "
    "reject_stale / reject_out_of_order / downgrade_to_partial).  Android-"
    "side ordering is advisory only.  (PR-P0-3)"
)

REPLAY_ORDERING_FORMAL_SEMANTICS_POLICY: str = (
    "POLICY::REPLAY_ORDERING_FORMAL_SEMANTICS_PR_P03: "
    "Formal ordering semantics for Android offline queue replay: "
    "(1) Within a single session, items MUST arrive in non-decreasing seq "
    "order.  An item whose seq equals or exceeds the current session maximum "
    "is accepted.  "
    "(2) An item whose seq is below the current session maximum but within "
    "STALE_SEQ_WINDOW is classified out_of_order and rejected.  "
    "(3) An item whose seq is more than STALE_SEQ_WINDOW below the current "
    "session maximum is classified stale and rejected.  "
    "(4) An item whose item_id has already been seen in this session is "
    "classified duplicate and rejected regardless of seq.  "
    "(5) Across sessions, best-effort ordering applies; strict cross-session "
    "ordering is not guaranteed.  (PR-P0-3)"
)

DUPLICATE_AVOIDANCE_BOUNDARY_IS_V2_SIGNAL_GUARD_POLICY: str = (
    "POLICY::DUPLICATE_AVOIDANCE_BOUNDARY_IS_V2_SIGNAL_GUARD_PR_P03: "
    "The authoritative duplicate-avoidance boundary for offline replay is "
    "V2's signal guard (core.attached_runtime_recovery_readiness) combined "
    "with the idempotency registry in DelegatedFlowRecoveryCoordinator "
    "(core.delegated_flow_recovery_coordinator).  Android-local deduplication "
    "is advisory and MUST NOT be treated as the sole authoritative boundary.  "
    "V2 MUST apply its own duplicate-detection layer regardless of Android-"
    "side deduplication status.  (PR-P0-3)"
)

STALE_REPLAY_MUST_DOWNGRADE_NOT_ACCEPT_POLICY: str = (
    "POLICY::STALE_REPLAY_MUST_DOWNGRADE_NOT_ACCEPT_PR_P03: "
    "A stale replay item — one whose seq value is more than STALE_SEQ_WINDOW "
    "below the current session maximum — MUST be classified with decision "
    "reject_stale and MUST NOT be silently accepted as if it were in-order.  "
    "Accepting stale replays would allow outdated Android-side state to "
    "overwrite canonical V2 task state.  (PR-P0-3)"
)

OUT_OF_ORDER_REPLAY_MUST_NOT_SILENTLY_ACCEPT_POLICY: str = (
    "POLICY::OUT_OF_ORDER_REPLAY_MUST_NOT_SILENTLY_ACCEPT_PR_P03: "
    "An out-of-order replay item — one whose seq value is below the current "
    "session maximum but within STALE_SEQ_WINDOW — MUST be classified with "
    "decision reject_out_of_order and MUST NOT be silently accepted.  Silent "
    "acceptance of out-of-order replays is prohibited because it would "
    "corrupt the canonical task execution sequence.  (PR-P0-3)"
)

AMBIGUOUS_AUTHORITY_MUST_NOT_OPTIMISTICALLY_UPGRADE_POLICY: str = (
    "POLICY::AMBIGUOUS_AUTHORITY_MUST_NOT_OPTIMISTICALLY_UPGRADE_PR_P03: "
    "When the replay ordering authority cannot be positively confirmed as "
    "V2-side (e.g. the ordering_authority parameter is ambiguous or the "
    "evaluator cannot determine which side owns the sequence), the overall "
    "contract verdict MUST be downgraded and MUST NOT be "
    "authoritative_contract_defined.  Silence and ambiguity are never "
    "optimistically resolved as acceptance.  (PR-P0-3)"
)

PARTIAL_REPLAY_STAYS_ADVISORY_NOT_FULLY_CLOSED_POLICY: str = (
    "POLICY::PARTIAL_REPLAY_STAYS_ADVISORY_NOT_FULLY_CLOSED_PR_P03: "
    "A replay sequence that was only partially received (session terminated "
    "before drain completion, or not all expected items arrived) MUST produce "
    "verdict contract_partially_evidenced at best and MUST NOT be promoted "
    "to a fully_closed status.  The distinction between partial receipt and "
    "complete drain MUST be preserved in the report.  (PR-P0-3)"
)

REPLAY_CONTINUITY_REQUIRES_CANONICAL_TASK_IDENTITY_POLICY: str = (
    "POLICY::REPLAY_CONTINUITY_REQUIRES_CANONICAL_TASK_IDENTITY_PR_P03: "
    "A replayed task item is only considered continuity-preserving — i.e. a "
    "genuine resumption of a known in-flight delegated task — when the "
    "replayed task_id or correlation_id matches a task recorded by V2 before "
    "the disconnect.  A replayed item whose task_id is unknown to V2 MUST be "
    "treated as a new attachment, not as a continuation of an existing task.  "
    "Continuity without canonical identity match is prohibited.  (PR-P0-3)"
)

REPLAY_TRUTH_CONVERGENCE_REQUIRES_V2_ABSORPTION_POLICY: str = (
    "POLICY::REPLAY_TRUTH_CONVERGENCE_REQUIRES_V2_ABSORPTION_PR_P03: "
    "Truth convergence for a replayed task result requires V2 to explicitly "
    "absorb the result into its canonical task state via "
    "canonical_completion_ingress or an equivalent authoritative absorption "
    "path.  A replayed result that V2 has not absorbed is NOT considered "
    "truth-converged regardless of Android-side confirmation.  "
    "Android-side result recording does not constitute V2-side truth "
    "convergence.  (PR-P0-3)"
)

# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------

STALE_SEQ_WINDOW: int = 10
"""Items whose seq is more than STALE_SEQ_WINDOW below the current session
maximum are classified as stale and rejected (decision: reject_stale).
Items within STALE_SEQ_WINDOW are classified as out_of_order (decision:
reject_out_of_order).

This constant governs the boundary between *stale* and *out-of-order*
semantics.  It is deliberately conservative (10 steps) to prevent
large-batch replays from overwriting canonical state."""

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ReplayOrderingAuthority(str, Enum):
    """Which side owns the replay ordering decision.

    Values
    ------
    v2_side
        V2 is the replay ordering authority (canonical for this contract).
    android_side
        Android side is asserting authority (advisory only from V2's
        perspective; V2 still enforces its own guard).
    shared
        Both sides collaborate on ordering (not currently supported;
        recorded for completeness).
    ambiguous
        Authority cannot be determined.  Contract verdict MUST be
        downgraded.
    """

    v2_side = "v2_side"
    android_side = "android_side"
    shared = "shared"
    ambiguous = "ambiguous"

    @classmethod
    def from_string(
        cls, value: str, *, default: "ReplayOrderingAuthority" = None
    ) -> "ReplayOrderingAuthority":
        if not isinstance(value, str):
            return default if default is not None else cls.ambiguous
        try:
            return cls(value.lower().strip())
        except ValueError:
            return default if default is not None else cls.ambiguous


class ReplayOrderingGuarantee(str, Enum):
    """The ordering guarantee provided by the V2-side contract.

    Values
    ------
    strict_fifo_within_session
        All items within a single session MUST arrive in non-decreasing
        seq order; violations are rejected.
    best_effort_cross_session
        Across sessions, ordering is best-effort; strict cross-session
        ordering is not guaranteed.
    no_guarantee
        No ordering is guaranteed (should not occur with V2 authority).
    """

    strict_fifo_within_session = "strict_fifo_within_session"
    best_effort_cross_session = "best_effort_cross_session"
    no_guarantee = "no_guarantee"


class DuplicateAvoidanceBoundary(str, Enum):
    """The authoritative duplicate-avoidance boundary.

    Values
    ------
    v2_signal_guard
        V2's signal guard (core.attached_runtime_recovery_readiness) is
        the primary boundary.
    android_local
        Android-local deduplication only (advisory from V2's perspective).
    both
        Both V2 signal guard and Android-local deduplication are active
        (defence-in-depth).
    none
        No deduplication is active (should not occur with V2 authority).
    """

    v2_signal_guard = "v2_signal_guard"
    android_local = "android_local"
    both = "both"
    none = "none"


class ReplaySequenceStatus(str, Enum):
    """Semantic status of a single replay item within its sequence.

    Values
    ------
    in_order
        Item's seq >= current session maximum; accepted.
    out_of_order
        Item's seq < current session maximum but within STALE_SEQ_WINDOW.
    duplicate
        Item's item_id has already been seen in this session.
    stale
        Item's seq is more than STALE_SEQ_WINDOW below current maximum.
    partial
        Item is part of an incomplete drain (session terminated early).
    ambiguous
        Item's status cannot be determined (missing fields, etc.).
    """

    in_order = "in_order"
    out_of_order = "out_of_order"
    duplicate = "duplicate"
    stale = "stale"
    partial = "partial"
    ambiguous = "ambiguous"


class OfflineReplayItemDecision(str, Enum):
    """V2-side decision for a single replay item.

    Values
    ------
    accept
        Item is in-order; forward to reconciler.
    reject_duplicate
        Item is a duplicate; suppress silently.
    reject_stale
        Item is stale; discard without processing.
    reject_out_of_order
        Item is out of order; discard without processing.
    downgrade_to_partial
        Item is from an incomplete drain; treat as partial evidence only.
    ambiguous_authority
        Authority could not be confirmed; item held pending clarification.
    """

    accept = "accept"
    reject_duplicate = "reject_duplicate"
    reject_stale = "reject_stale"
    reject_out_of_order = "reject_out_of_order"
    downgrade_to_partial = "downgrade_to_partial"
    ambiguous_authority = "ambiguous_authority"


class OfflineReplayContractVerdict(str, Enum):
    """Contract-level verdict for an evaluated replay sequence.

    Values
    ------
    authoritative_contract_defined
        The contract is formally defined AND the evaluated sequence
        demonstrated at least one successfully accepted item with no
        ambiguity in ordering authority.  Full contract semantics are
        active.

    contract_partially_evidenced
        The contract is formally defined but the evaluated sequence has
        mixed results: some items rejected (stale/out-of-order/duplicate)
        or the drain was partial.  Contract semantics are active and being
        enforced, but not all items were accepted.

    contract_not_yet_evidenced
        The contract is formally defined but no live replay sequence has
        been evaluated in this process instance.  This is the baseline
        state at process startup.

    downgraded
        Authority was ambiguous or insufficient to claim the full contract.
        The contract MUST NOT be reported as authoritative_contract_defined.
    """

    authoritative_contract_defined = "authoritative_contract_defined"
    contract_partially_evidenced = "contract_partially_evidenced"
    contract_not_yet_evidenced = "contract_not_yet_evidenced"
    downgraded = "downgraded"

    @property
    def is_contract_active(self) -> bool:
        """Return True when the contract is formally active (not downgraded)."""
        return self in (
            OfflineReplayContractVerdict.authoritative_contract_defined,
            OfflineReplayContractVerdict.contract_partially_evidenced,
            OfflineReplayContractVerdict.contract_not_yet_evidenced,
        )

    @property
    def is_fully_evidenced(self) -> bool:
        """Return True only when the contract has positive acceptance evidence."""
        return self == OfflineReplayContractVerdict.authoritative_contract_defined


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class OfflineReplayItemEvaluation:
    """Evaluation result for one item in a replay sequence.

    Attributes
    ----------
    item_id
        Unique identifier for this replay item (e.g. signal_id or task_id).
    seq
        Sequence number of this item as reported by the Android drain.
    status
        Semantic classification of this item in its sequence context.
    decision
        V2-side decision for this item.
    is_duplicate
        True when item_id was already seen in this session.
    is_stale
        True when seq is more than STALE_SEQ_WINDOW below session max.
    is_out_of_order
        True when seq is below session max but within STALE_SEQ_WINDOW.
    note
        Human-readable explanation of the decision.
    evaluated_at
        Unix timestamp of evaluation.
    """

    item_id: str = ""
    seq: int = 0
    status: ReplaySequenceStatus = ReplaySequenceStatus.ambiguous
    decision: OfflineReplayItemDecision = OfflineReplayItemDecision.ambiguous_authority
    is_duplicate: bool = False
    is_stale: bool = False
    is_out_of_order: bool = False
    note: str = ""
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "seq": self.seq,
            "status": self.status.value,
            "decision": self.decision.value,
            "is_duplicate": self.is_duplicate,
            "is_stale": self.is_stale,
            "is_out_of_order": self.is_out_of_order,
            "note": self.note,
            "evaluated_at": self.evaluated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "OfflineReplayItemEvaluation":
        return cls(
            item_id=str(d.get("item_id", "")),
            seq=int(d.get("seq", 0)),
            status=ReplaySequenceStatus(
                d.get("status", ReplaySequenceStatus.ambiguous.value)
            ),
            decision=OfflineReplayItemDecision(
                d.get("decision", OfflineReplayItemDecision.ambiguous_authority.value)
            ),
            is_duplicate=bool(d.get("is_duplicate", False)),
            is_stale=bool(d.get("is_stale", False)),
            is_out_of_order=bool(d.get("is_out_of_order", False)),
            note=str(d.get("note", "")),
            evaluated_at=float(d.get("evaluated_at", time.time())),
        )


@dataclass
class OfflineReplayOrderingReport:
    """Structured report from evaluating an offline replay sequence.

    This is the machine-consumable output of
    :func:`evaluate_replay_sequence` or
    :func:`build_offline_replay_ordering_report`.

    Attributes
    ----------
    report_id
        Unique identifier for this report.
    generated_at
        Unix timestamp when this report was built.
    authority_sentinel
        Copy of :data:`OFFLINE_REPLAY_ORDERING_CONTRACT_AUTHORITY`.
    pr_sentinel
        Copy of :data:`OFFLINE_REPLAY_ORDERING_CONTRACT_PR_P03_SENTINEL`.
    ordering_authority
        Which side owns the replay ordering decision for this evaluation.
    ordering_guarantee
        The ordering guarantee that applies to this sequence.
    duplicate_avoidance_boundary
        The authoritative duplicate-avoidance boundary in effect.
    verdict
        Contract-level verdict for this evaluation.
    items
        Per-item evaluation results.
    accepted_count
        Count of items with decision ``accept``.
    rejected_duplicate_count
        Count of items rejected as duplicates.
    rejected_stale_count
        Count of items rejected as stale.
    rejected_out_of_order_count
        Count of items rejected as out-of-order.
    downgraded_count
        Count of items downgraded to partial.
    ambiguous_count
        Count of items with ambiguous authority/status.
    total_items
        Total items evaluated.
    partial_drain
        True when the drain was known to be incomplete.
    continuity_relation_note
        Human-readable note about task continuity semantics.
    truth_convergence_note
        Human-readable note about truth-convergence semantics.
    summary
        Human-readable multi-line summary of the evaluation.
    """

    report_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    generated_at: float = field(default_factory=time.time)
    authority_sentinel: str = OFFLINE_REPLAY_ORDERING_CONTRACT_AUTHORITY
    pr_sentinel: str = OFFLINE_REPLAY_ORDERING_CONTRACT_PR_P03_SENTINEL
    ordering_authority: ReplayOrderingAuthority = ReplayOrderingAuthority.v2_side
    ordering_guarantee: ReplayOrderingGuarantee = (
        ReplayOrderingGuarantee.strict_fifo_within_session
    )
    duplicate_avoidance_boundary: DuplicateAvoidanceBoundary = (
        DuplicateAvoidanceBoundary.v2_signal_guard
    )
    verdict: OfflineReplayContractVerdict = (
        OfflineReplayContractVerdict.contract_not_yet_evidenced
    )
    items: List[OfflineReplayItemEvaluation] = field(default_factory=list)
    accepted_count: int = 0
    rejected_duplicate_count: int = 0
    rejected_stale_count: int = 0
    rejected_out_of_order_count: int = 0
    downgraded_count: int = 0
    ambiguous_count: int = 0
    total_items: int = 0
    partial_drain: bool = False
    continuity_relation_note: str = (
        "A replayed task item is continuity-preserving only when its "
        "task_id matches a V2-tracked in-flight task.  Unknown task_ids "
        "from replay are new attachments.  "
        "(REPLAY_CONTINUITY_REQUIRES_CANONICAL_TASK_IDENTITY_POLICY)"
    )
    truth_convergence_note: str = (
        "Truth convergence for a replayed result requires explicit V2 "
        "absorption via canonical_completion_ingress.  Android-side "
        "confirmation alone is not sufficient.  "
        "(REPLAY_TRUTH_CONVERGENCE_REQUIRES_V2_ABSORPTION_POLICY)"
    )
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "authority_sentinel": self.authority_sentinel,
            "pr_sentinel": self.pr_sentinel,
            "ordering_authority": self.ordering_authority.value,
            "ordering_guarantee": self.ordering_guarantee.value,
            "duplicate_avoidance_boundary": self.duplicate_avoidance_boundary.value,
            "verdict": self.verdict.value,
            "items": [i.to_dict() for i in self.items],
            "accepted_count": self.accepted_count,
            "rejected_duplicate_count": self.rejected_duplicate_count,
            "rejected_stale_count": self.rejected_stale_count,
            "rejected_out_of_order_count": self.rejected_out_of_order_count,
            "downgraded_count": self.downgraded_count,
            "ambiguous_count": self.ambiguous_count,
            "total_items": self.total_items,
            "partial_drain": self.partial_drain,
            "continuity_relation_note": self.continuity_relation_note,
            "truth_convergence_note": self.truth_convergence_note,
            "summary": self.summary,
            "is_contract_active": self.verdict.is_contract_active,
            "is_fully_evidenced": self.verdict.is_fully_evidenced,
        }

    def to_json(self, *, indent: int = 2) -> str:
        """Return a JSON representation of this report."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "OfflineReplayOrderingReport":
        return cls(
            report_id=d.get("report_id", ""),
            generated_at=float(d.get("generated_at", 0.0)),
            authority_sentinel=d.get("authority_sentinel", ""),
            pr_sentinel=d.get("pr_sentinel", ""),
            ordering_authority=ReplayOrderingAuthority(
                d.get("ordering_authority", ReplayOrderingAuthority.v2_side.value)
            ),
            ordering_guarantee=ReplayOrderingGuarantee(
                d.get(
                    "ordering_guarantee",
                    ReplayOrderingGuarantee.strict_fifo_within_session.value,
                )
            ),
            duplicate_avoidance_boundary=DuplicateAvoidanceBoundary(
                d.get(
                    "duplicate_avoidance_boundary",
                    DuplicateAvoidanceBoundary.v2_signal_guard.value,
                )
            ),
            verdict=OfflineReplayContractVerdict(
                d.get(
                    "verdict",
                    OfflineReplayContractVerdict.contract_not_yet_evidenced.value,
                )
            ),
            items=[
                OfflineReplayItemEvaluation.from_dict(i)
                for i in d.get("items", [])
            ],
            accepted_count=int(d.get("accepted_count", 0)),
            rejected_duplicate_count=int(d.get("rejected_duplicate_count", 0)),
            rejected_stale_count=int(d.get("rejected_stale_count", 0)),
            rejected_out_of_order_count=int(d.get("rejected_out_of_order_count", 0)),
            downgraded_count=int(d.get("downgraded_count", 0)),
            ambiguous_count=int(d.get("ambiguous_count", 0)),
            total_items=int(d.get("total_items", 0)),
            partial_drain=bool(d.get("partial_drain", False)),
            continuity_relation_note=d.get("continuity_relation_note", ""),
            truth_convergence_note=d.get("truth_convergence_note", ""),
            summary=d.get("summary", ""),
        )


# ---------------------------------------------------------------------------
# Core evaluation logic
# ---------------------------------------------------------------------------


def evaluate_replay_sequence(
    items: Sequence[Dict[str, Any]],
    *,
    ordering_authority: ReplayOrderingAuthority = ReplayOrderingAuthority.v2_side,
    partial_drain: bool = False,
    stale_window: int = STALE_SEQ_WINDOW,
) -> OfflineReplayOrderingReport:
    """Evaluate a replay sequence against the V2 offline replay ordering contract.

    This is a pure function (given the same inputs, produces the same
    outputs) suitable for deterministic unit testing without a live Android
    participant.

    Parameters
    ----------
    items
        Ordered list of replay item dicts.  Each dict SHOULD contain:
        ``item_id`` (str) — unique item identifier, used for duplicate
        detection.  ``seq`` (int) — sequence number, used for ordering
        enforcement.  Additional keys are preserved but not evaluated.
    ordering_authority
        Which side asserts authority for this sequence.  If ``ambiguous``,
        the overall verdict is ``downgraded`` regardless of item decisions.
    partial_drain
        If True, the sequence is known to be incomplete (drain terminated
        early).  The verdict is capped at ``contract_partially_evidenced``.
    stale_window
        Number of seq steps below max_seen at which an item is classified
        as stale rather than out-of-order.  Defaults to
        :data:`STALE_SEQ_WINDOW`.

    Returns
    -------
    OfflineReplayOrderingReport
        Per-item evaluation results and overall contract verdict.

    Notes
    -----
    Ambiguous authority MUST produce verdict ``downgraded`` (policy:
    :data:`AMBIGUOUS_AUTHORITY_MUST_NOT_OPTIMISTICALLY_UPGRADE_POLICY`).
    Partial drain MUST cap verdict at ``contract_partially_evidenced``
    (policy: :data:`PARTIAL_REPLAY_STAYS_ADVISORY_NOT_FULLY_CLOSED_POLICY`).
    """
    report = OfflineReplayOrderingReport(
        ordering_authority=ordering_authority,
        partial_drain=partial_drain,
    )

    # Guard: ambiguous authority → downgraded immediately, still evaluate items
    if ordering_authority == ReplayOrderingAuthority.ambiguous:
        _evaluate_items_into_report(report, items, stale_window=stale_window)
        report.verdict = OfflineReplayContractVerdict.downgraded
        report.summary = _build_summary(report)
        return report

    _evaluate_items_into_report(report, items, stale_window=stale_window)

    # Determine verdict
    if report.total_items == 0:
        verdict = OfflineReplayContractVerdict.contract_not_yet_evidenced
    elif partial_drain:
        verdict = OfflineReplayContractVerdict.contract_partially_evidenced
    elif report.ambiguous_count > 0:
        verdict = OfflineReplayContractVerdict.downgraded
    elif (
        report.rejected_duplicate_count > 0
        or report.rejected_stale_count > 0
        or report.rejected_out_of_order_count > 0
        or report.downgraded_count > 0
    ):
        # Rejections are EXPECTED CONTRACT BEHAVIOUR (not failures), but they
        # mean the sequence was not purely in-order → partially evidenced.
        verdict = OfflineReplayContractVerdict.contract_partially_evidenced
    elif report.accepted_count > 0:
        verdict = OfflineReplayContractVerdict.authoritative_contract_defined
    else:
        verdict = OfflineReplayContractVerdict.contract_not_yet_evidenced

    report.verdict = verdict
    report.summary = _build_summary(report)
    return report


def _evaluate_items_into_report(
    report: OfflineReplayOrderingReport,
    items: Sequence[Dict[str, Any]],
    *,
    stale_window: int,
) -> None:
    """Mutate *report* by evaluating each item and recording decisions."""
    seen_ids: set = set()
    max_seq: int = -1

    for raw in items:
        item_id = str(raw.get("item_id", ""))
        try:
            seq = int(raw.get("seq", 0))
        except (TypeError, ValueError):
            seq = 0

        report.total_items += 1
        is_dup = item_id in seen_ids
        is_stale = (not is_dup) and (max_seq - seq > stale_window)
        is_oor = (not is_dup) and (not is_stale) and (seq < max_seq)

        if is_dup:
            status = ReplaySequenceStatus.duplicate
            decision = OfflineReplayItemDecision.reject_duplicate
            note = (
                f"Duplicate item_id {item_id!r}: already seen in this session.  "
                "Rejected per DUPLICATE_AVOIDANCE_BOUNDARY_IS_V2_SIGNAL_GUARD_POLICY."
            )
            report.rejected_duplicate_count += 1
        elif is_stale:
            status = ReplaySequenceStatus.stale
            decision = OfflineReplayItemDecision.reject_stale
            note = (
                f"Stale seq={seq} (session max={max_seq}, window={stale_window}): "
                "more than STALE_SEQ_WINDOW behind.  "
                "Rejected per STALE_REPLAY_MUST_DOWNGRADE_NOT_ACCEPT_POLICY."
            )
            report.rejected_stale_count += 1
        elif is_oor:
            status = ReplaySequenceStatus.out_of_order
            decision = OfflineReplayItemDecision.reject_out_of_order
            note = (
                f"Out-of-order seq={seq} (session max={max_seq}): "
                "below session maximum but within stale window.  "
                "Rejected per OUT_OF_ORDER_REPLAY_MUST_NOT_SILENTLY_ACCEPT_POLICY."
            )
            report.rejected_out_of_order_count += 1
        elif not item_id:
            # Missing item_id: cannot deduplicate → ambiguous
            status = ReplaySequenceStatus.ambiguous
            decision = OfflineReplayItemDecision.ambiguous_authority
            note = "Item has no item_id; cannot apply duplicate-avoidance contract."
            report.ambiguous_count += 1
        else:
            status = ReplaySequenceStatus.in_order
            decision = OfflineReplayItemDecision.accept
            note = f"In-order seq={seq} (session max was {max_seq}).  Accepted."
            report.accepted_count += 1
            seen_ids.add(item_id)
            if seq > max_seq:
                max_seq = seq

        # Update max_seq even for non-accepted items (stale detection uses it)
        if not is_dup and not is_oor and not is_stale:
            # only advance max for accepted/ambiguous items
            if seq > max_seq:
                max_seq = seq
        # For duplicates, seen_ids already has item_id; max_seq is unchanged.
        # For stale/oor: max_seq is unchanged (they're behind it).

        eval_item = OfflineReplayItemEvaluation(
            item_id=item_id,
            seq=seq,
            status=status,
            decision=decision,
            is_duplicate=is_dup,
            is_stale=is_stale,
            is_out_of_order=is_oor,
            note=note,
        )
        report.items.append(eval_item)
        if item_id and not is_dup:
            seen_ids.add(item_id)


def _build_summary(report: OfflineReplayOrderingReport) -> str:
    """Build a human-readable summary for *report*."""
    lines = [
        "=" * 68,
        "GALAXY V2 — OFFLINE REPLAY ORDERING CONTRACT (PR-P0-3)",
        "=" * 68,
        f"Ordering authority  : {report.ordering_authority.value}",
        f"Ordering guarantee  : {report.ordering_guarantee.value}",
        f"Dup-avoidance bound : {report.duplicate_avoidance_boundary.value}",
        f"Contract verdict    : {report.verdict.value}",
        f"Partial drain       : {report.partial_drain}",
        "",
        "ITEM EVALUATION SUMMARY",
        "-" * 40,
        f"  Total items       : {report.total_items}",
        f"  Accepted          : {report.accepted_count}",
        f"  Rej. duplicate    : {report.rejected_duplicate_count}",
        f"  Rej. stale        : {report.rejected_stale_count}",
        f"  Rej. out-of-order : {report.rejected_out_of_order_count}",
        f"  Downgraded        : {report.downgraded_count}",
        f"  Ambiguous         : {report.ambiguous_count}",
        "",
        "CONTINUITY RELATION",
        "-" * 40,
        f"  {report.continuity_relation_note}",
        "",
        "TRUTH CONVERGENCE RELATION",
        "-" * 40,
        f"  {report.truth_convergence_note}",
        "=" * 68,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Baseline process-level report
# ---------------------------------------------------------------------------


def build_offline_replay_ordering_report() -> OfflineReplayOrderingReport:
    """Build the baseline V2-side offline replay ordering report.

    This represents the contract state at process startup before any live
    Android offline drain has been evaluated.  The contract IS formally
    defined (this module provides it); no live replay sequence has been
    evaluated yet, so the verdict is ``contract_not_yet_evidenced``.

    For live sequence evaluation use :func:`evaluate_replay_sequence`.

    Returns
    -------
    OfflineReplayOrderingReport
        Baseline report with ``contract_not_yet_evidenced`` verdict.
    """
    report = OfflineReplayOrderingReport(
        ordering_authority=ReplayOrderingAuthority.v2_side,
        ordering_guarantee=ReplayOrderingGuarantee.strict_fifo_within_session,
        duplicate_avoidance_boundary=DuplicateAvoidanceBoundary.v2_signal_guard,
        verdict=OfflineReplayContractVerdict.contract_not_yet_evidenced,
        partial_drain=False,
    )
    report.summary = _build_summary(report)
    return report


# ---------------------------------------------------------------------------
# Process-global singleton
# ---------------------------------------------------------------------------

_REPORT_LOCK = threading.Lock()
_cached_report: Optional[OfflineReplayOrderingReport] = None


def get_offline_replay_ordering_report() -> OfflineReplayOrderingReport:
    """Return the process-level :class:`OfflineReplayOrderingReport` singleton.

    Builds the baseline report on first call and caches it.  Call
    :func:`reset_offline_replay_ordering_report` to discard the cache (test
    isolation).

    Returns
    -------
    OfflineReplayOrderingReport
    """
    global _cached_report  # noqa: PLW0603
    if _cached_report is None:
        with _REPORT_LOCK:
            if _cached_report is None:
                _cached_report = build_offline_replay_ordering_report()
    return _cached_report


def reset_offline_replay_ordering_report() -> None:
    """Discard the cached report singleton (test isolation helper)."""
    global _cached_report  # noqa: PLW0603
    with _REPORT_LOCK:
        _cached_report = None
