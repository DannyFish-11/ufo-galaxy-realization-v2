#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/offline_operational_contract.py
======================================
PR-10: Offline / Disconnected / Delayed-Sync Operational Contract.

Background
----------
The Galaxy V2 system already supports a range of connectivity scenarios:
participant lifecycle / readiness / delegated runtime surfaces, result /
evidence / verification / recovery ingestion, partial operation, deferred
completion, and post-hoc evidence return.  This demonstrates that the system
does not rely exclusively on stable real-time connectivity.

However, before this module the system had no formal operational contract that
distinguished *online operational* from *disconnected but resumable* from
*offline with deferred sync* from *evidence pending reconciliation* from
*unavailable*.  The practical risk was silent optimism: a participant that
"will eventually sync back" could be classified as "continuously operational"
because the system conflated eventual evidence return with uninterrupted
online presence.

Specifically, the following distinctions were absent:

* **online_operational** vs **bounded_disconnected_resumable** — is the
  participant actively connected and evidenced, or is it temporarily
  disconnected but within a known bounded recovery window?
* **offline_deferred_sync** — the participant is offline; results / evidence
  will be ingested asynchronously after reconnect.  This is NOT the same as
  continuously online.
* **pending_reconciliation** — evidence has been received but reconciliation
  has not yet completed; the operational picture is incomplete.
* **unavailable** — the participant cannot operate; no deferred sync can
  bridge this gap.

Without these distinctions, ``acceptance`` / ``readiness`` / ``governance`` /
``runtime truth`` surfaces cannot distinguish "always online and continuous"
from "offline but will eventually produce results".

This module closes that gap by establishing the **Offline / Disconnected /
Delayed-Sync Operational Contract** — a formal classification contract that:

1. Defines five mutually exclusive and exhaustive
   :class:`OfflineOperationalClass` values.
2. Specifies precise evidence requirements for each class.
3. Enforces conservative *downgrade semantics*: insufficient or stale
   evidence always produces the lowest defensible class rather than the
   optimistic one.
4. Prohibits treating deferred sync, eventual evidence return, or
   reconciliation initiation as equivalent to online operational presence.
5. Provides an :class:`OfflineOperationalVerdict` dataclass consumable by
   acceptance / readiness / governance / runtime truth pipelines.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  OFFLINE OPERATIONAL CONTRACT  (this module — PR-10)                │
    │                                                                     │
    │  Five operational classes (strictly ordered by connectivity):       │
    │    1. online_operational            (highest — participant          │
    │       actively connected, evidence fresh, operations continuous)    │
    │    2. bounded_disconnected_resumable  (temporarily disconnected;    │
    │       reconnect is expected within a bounded window; in-flight      │
    │       operations are tracked and can resume)                        │
    │    3. offline_deferred_sync         (participant is offline;        │
    │       results / evidence will arrive asynchronously after           │
    │       reconnect; current operations are deferred, NOT continuous)   │
    │    4. pending_reconciliation        (evidence received but          │
    │       reconciliation incomplete; operational picture is partial     │
    │       and MUST NOT be promoted to online_operational)               │
    │    5. unavailable                   (lowest — participant cannot    │
    │       operate; no deferred sync can bridge this gap)                │
    │                                                                     │
    │  Evidence dimensions evaluated:                                     │
    │    • connectivity_observed        — active connection confirmed     │
    │    • evidence_fresh               — evidence within freshness window│
    │    • reconnect_expected           — bounded reconnect window known  │
    │    • inflight_tracking_active     — in-flight ops are tracked       │
    │    • deferred_sync_acknowledged   — offline sync path is declared   │
    │    • reconciliation_in_progress   — reconciliation has been started │
    │    • reconciliation_complete      — reconciliation is complete      │
    │    • explicit_unavailable         — participant declared unavailable│
    │                                                                     │
    │  Downgrade semantics:                                               │
    │    • explicit_unavailable → ALWAYS unavailable                      │
    │    • no connectivity + no reconnect_expected → unavailable          │
    │    • reconciliation started but not complete →                      │
    │      NEVER online_operational or bounded_disconnected_resumable     │
    │    • deferred_sync_acknowledged + not connected →                   │
    │      NEVER online_operational (at most offline_deferred_sync)       │
    │    • evidence not fresh → NEVER online_operational                  │
    │    • no evidence at all → unavailable (fail-conservative)           │
    │                                                                     │
    │  Produces:                                                          │
    │    • OfflineOperationalVerdict  (structured output)                 │
    │                                                                     │
    │  Consumed by:                                                       │
    │    • system_final_acceptance_verdict (offline_operational dimension)│
    │    • acceptance / readiness / governance / runtime truth surfaces  │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified by this file.
2. **Fail-conservative** — missing or ambiguous evidence yields the lowest
   defensible class (``unavailable``) rather than the optimistic one.
3. **No optimistic promotion** — deferred sync, eventual evidence return,
   and reconciliation initiation are explicitly excluded from being promoted
   to ``online_operational``.
4. **Taxonomy boundary enforcement** — "will sync eventually" does NOT imply
   "is online operational"; "evidence arrived" does NOT imply "reconciliation
   complete"; "reconnect expected" does NOT imply "currently connected".
5. **Projection-only** — this module evaluates evidence fed to it; it never
   mutates external state.

Critical boundary: what counts as online_operational vs what does not
----------------------------------------------------------------------
- **Deferred sync acknowledged** — does NOT constitute online_operational;
  the participant is explicitly offline with a planned future sync path.
- **Reconciliation in progress** — does NOT constitute online_operational
  or bounded_disconnected_resumable; the operational picture is incomplete
  until reconciliation completes.
- **Reconnect expected** — does NOT constitute online_operational; the
  participant is currently disconnected even if reconnect is anticipated.
- **Evidence arrived post-hoc** — does NOT retroactively elevate the
  operational class to online_operational for the period when the
  participant was offline.
- **No evidence** — cannot be treated as online_operational; absence of
  connectivity and evidence confirmation is the conservative default.

Public API
----------
Authority sentinels::

    OFFLINE_OPERATIONAL_CONTRACT_AUTHORITY
    OFFLINE_OPERATIONAL_CONTRACT_PR10_SENTINEL

Policy sentinels::

    OPERATIONAL_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY
    DEFERRED_SYNC_MUST_NOT_CLAIM_ONLINE_OPERATIONAL_POLICY
    RECONNECT_EXPECTED_IS_NOT_ONLINE_OPERATIONAL_POLICY
    EVIDENCE_ABSENCE_DEFAULTS_TO_UNAVAILABLE_POLICY
    RECONCILIATION_INCOMPLETE_BLOCKS_ONLINE_OPERATIONAL_POLICY
    STALE_EVIDENCE_MUST_DOWNGRADE_CLASS_POLICY

Enumerations::

    OfflineOperationalClass
    ConnectivityState
    SyncMode

Data classes::

    OfflineOperationalEvidence
    OfflineOperationalVerdict

Functions::

    classify_offline_operational(evidence) -> OfflineOperationalVerdict
    build_offline_operational_verdict(evidence) -> OfflineOperationalVerdict
    build_baseline_offline_operational_verdict() -> OfflineOperationalVerdict
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.OfflineOperationalContract")

__all__ = [
    # Authority sentinels
    "OFFLINE_OPERATIONAL_CONTRACT_AUTHORITY",
    "OFFLINE_OPERATIONAL_CONTRACT_PR10_SENTINEL",
    # Policy sentinels
    "OPERATIONAL_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY",
    "DEFERRED_SYNC_MUST_NOT_CLAIM_ONLINE_OPERATIONAL_POLICY",
    "RECONNECT_EXPECTED_IS_NOT_ONLINE_OPERATIONAL_POLICY",
    "EVIDENCE_ABSENCE_DEFAULTS_TO_UNAVAILABLE_POLICY",
    "RECONCILIATION_INCOMPLETE_BLOCKS_ONLINE_OPERATIONAL_POLICY",
    "STALE_EVIDENCE_MUST_DOWNGRADE_CLASS_POLICY",
    # Enumerations
    "OfflineOperationalClass",
    "ConnectivityState",
    "SyncMode",
    # Data classes
    "OfflineOperationalEvidence",
    "OfflineOperationalVerdict",
    # Functions
    "classify_offline_operational",
    "build_offline_operational_verdict",
    "build_baseline_offline_operational_verdict",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

OFFLINE_OPERATIONAL_CONTRACT_AUTHORITY: str = (
    "OFFLINE_OPERATIONAL_CONTRACT_AUTHORITY::"
    "core.offline_operational_contract::PR10::"
    "offline-disconnected-delayed-sync-operational-taxonomy::"
    "formal-operational-contract-for-galaxy-v2-platform"
)
"""Sentinel: this module is the canonical authority for offline / disconnected
/ delayed-sync operational classification in Galaxy V2.

Import this sentinel to assert that a release gate, governance surface,
acceptance evaluator, or runtime truth layer is consuming a formal
operational classification rather than an implicit connectivity flag."""

OFFLINE_OPERATIONAL_CONTRACT_PR10_SENTINEL: str = (
    "OFFLINE_OPERATIONAL_CONTRACT_PR10_SENTINEL::"
    "package=PR10::profile=offline-operational-contract-v1::"
    "module=core.offline_operational_contract"
)
"""Package sentinel for PR-10 offline operational contract."""

OPERATIONAL_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY: str = (
    "POLICY::OPERATIONAL_TAXONOMY_IS_FIRST_CLASS_DIMENSION_V1: "
    "Offline / disconnected / delayed-sync operational status MUST be treated "
    "as a first-class operational dimension by truth surfaces, readiness gates, "
    "acceptance evaluators, and governance pipelines.  Surfaces MUST NOT "
    "conflate 'will eventually sync back' (deferred evidence return) with "
    "'is continuously online operational' (uninterrupted active connection).  "
    "Every operational verdict MUST include an OfflineOperationalVerdict that "
    "identifies the applicable class.  "
    "See: OfflineOperationalClass taxonomy in "
    "core.offline_operational_contract (PR-10)."
)
"""Policy: offline/disconnected operational status is a first-class dimension."""

DEFERRED_SYNC_MUST_NOT_CLAIM_ONLINE_OPERATIONAL_POLICY: str = (
    "POLICY::DEFERRED_SYNC_MUST_NOT_CLAIM_ONLINE_OPERATIONAL_V1: "
    "When a participant has an acknowledged deferred sync path (results or "
    "evidence will arrive after a future reconnect), the operational class "
    "MUST NOT be set to online_operational or bounded_disconnected_resumable.  "
    "Deferred sync explicitly means the participant is offline; at best the "
    "class is offline_deferred_sync.  "
    "'Eventually syncing back' is not the same as 'always online and continuous'.  "
    "See: OfflineOperationalClass.offline_deferred_sync in "
    "core.offline_operational_contract (PR-10)."
)
"""Policy: deferred sync must not produce online_operational classification."""

RECONNECT_EXPECTED_IS_NOT_ONLINE_OPERATIONAL_POLICY: str = (
    "POLICY::RECONNECT_EXPECTED_IS_NOT_ONLINE_OPERATIONAL_V1: "
    "When a participant is currently disconnected, the mere expectation that "
    "reconnect will occur within a bounded window MUST NOT produce an "
    "online_operational classification.  The participant is disconnected; "
    "the class MUST be at most bounded_disconnected_resumable.  "
    "Only an active, confirmed connection with fresh evidence qualifies as "
    "online_operational.  "
    "See: OfflineOperationalClass.bounded_disconnected_resumable vs "
    "OfflineOperationalClass.online_operational in "
    "core.offline_operational_contract (PR-10)."
)
"""Policy: reconnect_expected does not qualify as online_operational."""

EVIDENCE_ABSENCE_DEFAULTS_TO_UNAVAILABLE_POLICY: str = (
    "POLICY::EVIDENCE_ABSENCE_DEFAULTS_TO_UNAVAILABLE_V1: "
    "When no connectivity evidence, no freshness evidence, and no "
    "reconciliation evidence is present, the operational class MUST default "
    "to unavailable.  The absence of evidence is NOT a signal of "
    "online_operational status; it is a signal of unknown / worst-case state.  "
    "Silence is not connectivity.  "
    "See: OfflineOperationalClass.unavailable in "
    "core.offline_operational_contract (PR-10)."
)
"""Policy: absence of evidence defaults to unavailable (fail-conservative)."""

RECONCILIATION_INCOMPLETE_BLOCKS_ONLINE_OPERATIONAL_POLICY: str = (
    "POLICY::RECONCILIATION_INCOMPLETE_BLOCKS_ONLINE_OPERATIONAL_V1: "
    "When reconciliation has been initiated but has not yet completed, the "
    "operational class MUST be at most pending_reconciliation.  An incomplete "
    "reconciliation means the operational picture is partial; the class MUST "
    "NOT be promoted to online_operational or bounded_disconnected_resumable.  "
    "Evidence arriving post-hoc does not retroactively establish continuous "
    "online operation.  "
    "See: OfflineOperationalClass.pending_reconciliation in "
    "core.offline_operational_contract (PR-10)."
)
"""Policy: incomplete reconciliation blocks online_operational classification."""

STALE_EVIDENCE_MUST_DOWNGRADE_CLASS_POLICY: str = (
    "POLICY::STALE_EVIDENCE_MUST_DOWNGRADE_CLASS_V1: "
    "When connectivity or operational evidence is stale (exceeds the "
    "freshness window), the operational class MUST be downgraded.  Stale "
    "evidence implies an unknown current state; it MUST NOT be used to "
    "maintain an online_operational classification.  A participant with only "
    "stale evidence is at most offline_deferred_sync.  "
    "See: evidence_fresh flag in classify_offline_operational() (PR-10)."
)
"""Policy: stale evidence must downgrade the operational class."""


# ---------------------------------------------------------------------------
# OfflineOperationalClass
# ---------------------------------------------------------------------------


class OfflineOperationalClass(str, Enum):
    """Five-class operational taxonomy for offline / disconnected / delayed-sync
    semantics.

    String values are stable identifiers safe for serialisation, logging,
    and API responses.

    Ordering (from most connected to least):
      online_operational > bounded_disconnected_resumable >
      offline_deferred_sync > pending_reconciliation > unavailable
    """

    online_operational = "online_operational"
    """Participant is actively connected, evidence is fresh, and operations
    are continuous.  This is the only class that represents genuine
    uninterrupted online presence.

    Requirements (all must hold):
    - ConnectivityState.connected
    - evidence_fresh = True
    - reconciliation_in_progress = False OR reconciliation_complete = True
    - explicit_unavailable = False
    - deferred_sync_acknowledged = False
    """

    bounded_disconnected_resumable = "bounded_disconnected_resumable"
    """Participant is temporarily disconnected, but reconnect is expected
    within a bounded window.  In-flight operations are tracked and can
    resume once reconnect occurs.  This is NOT online_operational — the
    participant is not currently active.

    Requirements:
    - ConnectivityState.disconnected (not connected, not offline)
    - reconnect_expected = True
    - inflight_tracking_active = True
    - reconciliation_in_progress = False (no pending reconciliation)
    - explicit_unavailable = False
    - deferred_sync_acknowledged = False
    """

    offline_deferred_sync = "offline_deferred_sync"
    """Participant is offline.  Results and evidence will be ingested
    asynchronously after a future reconnect via a declared deferred sync
    path.  Current operations are deferred, NOT continuous.  This MUST
    NOT be confused with online_operational.

    Requirements:
    - ConnectivityState.offline OR ConnectivityState.disconnected
    - deferred_sync_acknowledged = True
    - reconciliation_in_progress = False OR reconciliation_complete = True
    - explicit_unavailable = False
    """

    pending_reconciliation = "pending_reconciliation"
    """Evidence has been received (possibly post-hoc from a deferred sync)
    but reconciliation has not yet completed.  The operational picture is
    incomplete.  This class MUST NOT be promoted to online_operational or
    bounded_disconnected_resumable until reconciliation is complete.

    Requirements:
    - reconciliation_in_progress = True
    - reconciliation_complete = False
    - explicit_unavailable = False
    """

    unavailable = "unavailable"
    """Participant cannot operate.  No deferred sync path, no bounded
    reconnect window, or explicit unavailability declared.  This is the
    fail-conservative default when evidence is absent.

    Requirements (any of):
    - explicit_unavailable = True
    - No connectivity AND no reconnect_expected AND no deferred_sync_acknowledged
    - No evidence at all (fail-conservative default)
    """


# Numeric rank for comparison (lower = worse)
_CLASS_RANK: Dict[str, int] = {
    OfflineOperationalClass.unavailable.value: 0,
    OfflineOperationalClass.pending_reconciliation.value: 1,
    OfflineOperationalClass.offline_deferred_sync.value: 2,
    OfflineOperationalClass.bounded_disconnected_resumable.value: 3,
    OfflineOperationalClass.online_operational.value: 4,
}


def _worse_or_equal(a: OfflineOperationalClass, b: OfflineOperationalClass) -> bool:
    """Return True if class *a* is worse than or equal to class *b*."""
    return _CLASS_RANK[a.value] <= _CLASS_RANK[b.value]


# ---------------------------------------------------------------------------
# ConnectivityState
# ---------------------------------------------------------------------------


class ConnectivityState(str, Enum):
    """Canonical connectivity state for an operational participant.

    Distinct values prevent conflation of temporary disconnect (resumable)
    with planned offline (deferred sync) with never-connected (unavailable).
    """

    connected = "connected"
    """Participant has an active, confirmed connection.  Evidence is expected
    to be fresh.  This is the only state that can support online_operational."""

    disconnected = "disconnected"
    """Participant was connected but the connection was interrupted.  Reconnect
    may be expected (bounded_disconnected_resumable) or not (unavailable)."""

    offline = "offline"
    """Participant is deliberately or structurally offline.  A deferred sync
    path may exist (offline_deferred_sync) or the participant may be
    unavailable."""

    unknown = "unknown"
    """Connectivity state cannot be determined.  Must be treated
    conservatively — downgrade to unavailable unless other evidence
    establishes a higher class."""


# ---------------------------------------------------------------------------
# SyncMode
# ---------------------------------------------------------------------------


class SyncMode(str, Enum):
    """Describes whether and how evidence / results are synchronised.

    Used together with :class:`ConnectivityState` to differentiate
    ``bounded_disconnected_resumable`` from ``offline_deferred_sync``.
    """

    realtime = "realtime"
    """Evidence is synchronised in real-time via the active connection.  Only
    valid when ConnectivityState is connected."""

    deferred = "deferred"
    """Evidence will be synchronised asynchronously after a future reconnect.
    Explicitly marks the offline deferred sync path."""

    none = "none"
    """No synchronisation path exists or is planned.  Conservative default."""


# ---------------------------------------------------------------------------
# OfflineOperationalEvidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OfflineOperationalEvidence:
    """Structured evidence input for the offline operational classifier.

    All fields have safe (fail-conservative) defaults so that an absent
    signal does not silently produce an optimistic classification.

    Attributes
    ----------
    connectivity_state:
        Current connectivity state of the participant.  Defaults to
        ``ConnectivityState.unknown`` (conservative).
    evidence_fresh:
        True only when operational evidence (connection confirmation,
        heartbeat, lifecycle signal) is within the freshness window.
        Defaults to False (conservative).
    reconnect_expected:
        True when a bounded reconnect window is established — i.e., the
        system has a concrete expectation (not just hope) that the
        participant will reconnect within a known deadline.  Defaults to
        False (conservative).
    inflight_tracking_active:
        True when in-flight operations are actively tracked and can be
        resumed upon reconnect.  Defaults to False (conservative).
    deferred_sync_acknowledged:
        True when the offline deferred sync path has been explicitly
        declared — i.e., results / evidence will arrive post-reconnect
        via a known sync mechanism.  This flag explicitly marks the
        participant as offline with a planned future sync.  Defaults to
        False (conservative).
    reconciliation_in_progress:
        True when reconciliation of post-hoc evidence has been initiated
        but has not yet completed.  Defaults to False.
    reconciliation_complete:
        True when reconciliation of post-hoc evidence has completed.
        Defaults to False.  Note: reconciliation_complete=True with
        reconciliation_in_progress=True is treated as complete.
    explicit_unavailable:
        True when the participant has been explicitly declared unavailable
        (e.g., hardware failure, operator lockout, permanent
        de-registration).  Defaults to False.  When True, ALWAYS produces
        unavailable regardless of other fields.
    participant_id:
        Optional participant identifier for traceability.
    trace_id:
        Optional distributed-trace identifier.
    extra_context:
        Optional dict of additional context signals.  Not used in
        classification logic but included in the verdict for auditability.
    """

    connectivity_state: ConnectivityState = ConnectivityState.unknown
    evidence_fresh: bool = False
    reconnect_expected: bool = False
    inflight_tracking_active: bool = False
    deferred_sync_acknowledged: bool = False
    reconciliation_in_progress: bool = False
    reconciliation_complete: bool = False
    explicit_unavailable: bool = False
    participant_id: Optional[str] = None
    trace_id: Optional[str] = None
    extra_context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "connectivity_state": self.connectivity_state.value,
            "evidence_fresh": self.evidence_fresh,
            "reconnect_expected": self.reconnect_expected,
            "inflight_tracking_active": self.inflight_tracking_active,
            "deferred_sync_acknowledged": self.deferred_sync_acknowledged,
            "reconciliation_in_progress": self.reconciliation_in_progress,
            "reconciliation_complete": self.reconciliation_complete,
            "explicit_unavailable": self.explicit_unavailable,
            "participant_id": self.participant_id,
            "trace_id": self.trace_id,
            "extra_context": dict(self.extra_context),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OfflineOperationalEvidence":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        connectivity_raw = data.get("connectivity_state", "unknown")
        try:
            connectivity = ConnectivityState(connectivity_raw)
        except ValueError:
            connectivity = ConnectivityState.unknown
        return cls(
            connectivity_state=connectivity,
            evidence_fresh=bool(data.get("evidence_fresh", False)),
            reconnect_expected=bool(data.get("reconnect_expected", False)),
            inflight_tracking_active=bool(data.get("inflight_tracking_active", False)),
            deferred_sync_acknowledged=bool(
                data.get("deferred_sync_acknowledged", False)
            ),
            reconciliation_in_progress=bool(
                data.get("reconciliation_in_progress", False)
            ),
            reconciliation_complete=bool(data.get("reconciliation_complete", False)),
            explicit_unavailable=bool(data.get("explicit_unavailable", False)),
            participant_id=data.get("participant_id"),
            trace_id=data.get("trace_id"),
            extra_context=dict(data.get("extra_context", {})),
        )


# ---------------------------------------------------------------------------
# OfflineOperationalVerdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OfflineOperationalVerdict:
    """Formal offline operational verdict for a participant or system surface.

    Produced by :func:`classify_offline_operational`.

    Attributes
    ----------
    operational_class:
        The classified :class:`OfflineOperationalClass` for this context.
    rationale:
        Human-readable explanation of why this class was assigned.  Always
        non-empty.
    downgrade_reasons:
        List of specific reasons that caused the class to be downgraded from
        an optimistic baseline.  Empty when no downgrade occurred.
    is_online_operational:
        True only for ``online_operational`` class.  MUST NOT be set for
        any other class.
    is_resumable:
        True for ``online_operational`` and
        ``bounded_disconnected_resumable``.  Indicates the participant can
        complete in-flight operations either now or after bounded reconnect.
    is_deferred:
        True for ``offline_deferred_sync`` and ``pending_reconciliation``.
        Indicates results / evidence will arrive asynchronously.
    participant_id:
        Identifier of the participant this verdict applies to.
    evidence_present:
        Whether any positive evidence was available during classification.
    classified_at:
        Unix timestamp (float) when this verdict was produced.
    verdict_id:
        Unique identifier for this verdict instance.
    trace_id:
        Optional distributed-trace identifier.
    """

    operational_class: OfflineOperationalClass
    rationale: str
    downgrade_reasons: List[str] = field(default_factory=list)
    is_online_operational: bool = False
    is_resumable: bool = False
    is_deferred: bool = False
    participant_id: Optional[str] = None
    evidence_present: bool = False
    classified_at: float = field(default_factory=time.time)
    verdict_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    trace_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "operational_class": self.operational_class.value,
            "rationale": self.rationale,
            "downgrade_reasons": list(self.downgrade_reasons),
            "is_online_operational": self.is_online_operational,
            "is_resumable": self.is_resumable,
            "is_deferred": self.is_deferred,
            "participant_id": self.participant_id,
            "evidence_present": self.evidence_present,
            "classified_at": self.classified_at,
            "verdict_id": self.verdict_id,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OfflineOperationalVerdict":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        class_raw = data.get("operational_class", "unavailable")
        try:
            op_class = OfflineOperationalClass(class_raw)
        except ValueError:
            op_class = OfflineOperationalClass.unavailable
        return cls(
            operational_class=op_class,
            rationale=data.get("rationale", ""),
            downgrade_reasons=list(data.get("downgrade_reasons", [])),
            is_online_operational=bool(data.get("is_online_operational", False)),
            is_resumable=bool(data.get("is_resumable", False)),
            is_deferred=bool(data.get("is_deferred", False)),
            participant_id=data.get("participant_id"),
            evidence_present=bool(data.get("evidence_present", False)),
            classified_at=float(data.get("classified_at", time.time())),
            verdict_id=data.get("verdict_id", uuid.uuid4().hex[:12]),
            trace_id=data.get("trace_id"),
        )


# ---------------------------------------------------------------------------
# Core classifier
# ---------------------------------------------------------------------------


def classify_offline_operational(
    evidence: OfflineOperationalEvidence,
) -> OfflineOperationalVerdict:
    """Classify the offline operational class for a participant.

    This is the canonical entry point for offline / disconnected /
    delayed-sync operational classification.  It applies the fail-conservative
    downgrade rules defined in the module docstring and enforced by the
    policy sentinels.

    Classification logic (evaluated in priority order):
    1. ``explicit_unavailable=True`` → **unavailable** (always, no exception)
    2. ``reconciliation_in_progress=True`` and
       ``reconciliation_complete=False`` → **pending_reconciliation**
    3. ``connectivity_state=connected`` and ``evidence_fresh=True`` and
       ``deferred_sync_acknowledged=False`` → **online_operational**
    4. ``connectivity_state in (disconnected, offline, connected)`` and
       ``deferred_sync_acknowledged=True`` → **offline_deferred_sync**
    5. ``connectivity_state=disconnected`` and
       ``reconnect_expected=True`` and
       ``inflight_tracking_active=True`` → **bounded_disconnected_resumable**
    6. All other cases → **unavailable** (fail-conservative)

    Parameters
    ----------
    evidence:
        :class:`OfflineOperationalEvidence` describing the participant's
        connectivity and evidence state.

    Returns
    -------
    OfflineOperationalVerdict
        Immutable verdict recording the class, rationale, and any downgrade
        reasons.  Never raises; returns ``unavailable`` on unexpected input.
    """
    try:
        return _classify(evidence)
    except Exception as exc:
        logger.warning(
            "classify_offline_operational raised unexpectedly: %r — defaulting to unavailable",
            exc,
        )
        return OfflineOperationalVerdict(
            operational_class=OfflineOperationalClass.unavailable,
            rationale=(
                f"Classification raised an unexpected exception ({exc!r}); "
                "defaulting to unavailable per fail-conservative policy."
            ),
            downgrade_reasons=[f"exception: {exc!r}"],
            is_online_operational=False,
            is_resumable=False,
            is_deferred=False,
            evidence_present=False,
        )


def _classify(evidence: OfflineOperationalEvidence) -> OfflineOperationalVerdict:
    """Internal classification logic (separated for testability)."""
    downgrade_reasons: List[str] = []

    # ------------------------------------------------------------------
    # Rule 1: explicit_unavailable always wins
    # ------------------------------------------------------------------
    if evidence.explicit_unavailable:
        return OfflineOperationalVerdict(
            operational_class=OfflineOperationalClass.unavailable,
            rationale=(
                "Participant has been explicitly declared unavailable.  "
                "EVIDENCE_ABSENCE_DEFAULTS_TO_UNAVAILABLE_POLICY and "
                "explicit_unavailable=True override all other signals."
            ),
            downgrade_reasons=["explicit_unavailable=True"],
            is_online_operational=False,
            is_resumable=False,
            is_deferred=False,
            participant_id=evidence.participant_id,
            evidence_present=False,
            trace_id=evidence.trace_id,
        )

    # ------------------------------------------------------------------
    # Rule 2: reconciliation in progress (but not complete) → pending
    # ------------------------------------------------------------------
    if evidence.reconciliation_in_progress and not evidence.reconciliation_complete:
        downgrade_reasons.append(
            "reconciliation_in_progress=True and reconciliation_complete=False: "
            "RECONCILIATION_INCOMPLETE_BLOCKS_ONLINE_OPERATIONAL_POLICY applied."
        )
        return OfflineOperationalVerdict(
            operational_class=OfflineOperationalClass.pending_reconciliation,
            rationale=(
                "Reconciliation has been initiated but has not completed.  "
                "The operational picture is partial.  "
                "RECONCILIATION_INCOMPLETE_BLOCKS_ONLINE_OPERATIONAL_POLICY "
                "prevents promotion to online_operational or "
                "bounded_disconnected_resumable."
            ),
            downgrade_reasons=downgrade_reasons,
            is_online_operational=False,
            is_resumable=False,
            is_deferred=True,
            participant_id=evidence.participant_id,
            evidence_present=True,
            trace_id=evidence.trace_id,
        )

    # ------------------------------------------------------------------
    # Rule 3: online_operational — requires active connection AND fresh
    #         evidence AND no deferred sync declaration
    # ------------------------------------------------------------------
    if (
        evidence.connectivity_state == ConnectivityState.connected
        and evidence.evidence_fresh
        and not evidence.deferred_sync_acknowledged
    ):
        return OfflineOperationalVerdict(
            operational_class=OfflineOperationalClass.online_operational,
            rationale=(
                "Participant is actively connected with fresh evidence and no "
                "deferred sync declaration.  Continuous online operational "
                "status is formally confirmed."
            ),
            downgrade_reasons=[],
            is_online_operational=True,
            is_resumable=True,
            is_deferred=False,
            participant_id=evidence.participant_id,
            evidence_present=True,
            trace_id=evidence.trace_id,
        )

    # ------------------------------------------------------------------
    # Collect downgrade reasons for non-online states
    # ------------------------------------------------------------------
    if evidence.connectivity_state != ConnectivityState.connected:
        downgrade_reasons.append(
            f"connectivity_state={evidence.connectivity_state.value} (not connected): "
            "RECONNECT_EXPECTED_IS_NOT_ONLINE_OPERATIONAL_POLICY applied."
        )
    if not evidence.evidence_fresh:
        downgrade_reasons.append(
            "evidence_fresh=False: "
            "STALE_EVIDENCE_MUST_DOWNGRADE_CLASS_POLICY applied."
        )
    if evidence.deferred_sync_acknowledged:
        downgrade_reasons.append(
            "deferred_sync_acknowledged=True: "
            "DEFERRED_SYNC_MUST_NOT_CLAIM_ONLINE_OPERATIONAL_POLICY applied."
        )

    # ------------------------------------------------------------------
    # Rule 4: offline_deferred_sync — deferred sync path explicitly declared
    # ------------------------------------------------------------------
    if evidence.deferred_sync_acknowledged:
        return OfflineOperationalVerdict(
            operational_class=OfflineOperationalClass.offline_deferred_sync,
            rationale=(
                "Participant has an acknowledged deferred sync path.  "
                "Results / evidence will arrive asynchronously after reconnect.  "
                "Current operations are deferred, NOT continuous.  "
                "DEFERRED_SYNC_MUST_NOT_CLAIM_ONLINE_OPERATIONAL_POLICY "
                "prevents classification as online_operational."
            ),
            downgrade_reasons=downgrade_reasons,
            is_online_operational=False,
            is_resumable=False,
            is_deferred=True,
            participant_id=evidence.participant_id,
            evidence_present=True,
            trace_id=evidence.trace_id,
        )

    # ------------------------------------------------------------------
    # Rule 5: bounded_disconnected_resumable — disconnected but expected
    #         to reconnect within a bounded window with inflight tracking
    # ------------------------------------------------------------------
    if (
        evidence.connectivity_state == ConnectivityState.disconnected
        and evidence.reconnect_expected
        and evidence.inflight_tracking_active
    ):
        return OfflineOperationalVerdict(
            operational_class=OfflineOperationalClass.bounded_disconnected_resumable,
            rationale=(
                "Participant is temporarily disconnected but reconnect is "
                "expected within a bounded window, and in-flight operations "
                "are actively tracked.  "
                "RECONNECT_EXPECTED_IS_NOT_ONLINE_OPERATIONAL_POLICY "
                "confirms this is NOT online_operational."
            ),
            downgrade_reasons=downgrade_reasons,
            is_online_operational=False,
            is_resumable=True,
            is_deferred=False,
            participant_id=evidence.participant_id,
            evidence_present=True,
            trace_id=evidence.trace_id,
        )

    # ------------------------------------------------------------------
    # Rule 6: fail-conservative default → unavailable
    # ------------------------------------------------------------------
    if not downgrade_reasons:
        downgrade_reasons.append(
            "No positive operational evidence; "
            "EVIDENCE_ABSENCE_DEFAULTS_TO_UNAVAILABLE_POLICY applied."
        )
    return OfflineOperationalVerdict(
        operational_class=OfflineOperationalClass.unavailable,
        rationale=(
            "No sufficient combination of connectivity, evidence freshness, "
            "deferred sync declaration, or bounded reconnect evidence was "
            "present.  Defaulting to unavailable per fail-conservative policy.  "
            "EVIDENCE_ABSENCE_DEFAULTS_TO_UNAVAILABLE_POLICY applied."
        ),
        downgrade_reasons=downgrade_reasons,
        is_online_operational=False,
        is_resumable=False,
        is_deferred=False,
        participant_id=evidence.participant_id,
        evidence_present=any(
            [
                evidence.evidence_fresh,
                evidence.reconnect_expected,
                evidence.inflight_tracking_active,
                evidence.reconciliation_in_progress,
                evidence.reconciliation_complete,
            ]
        ),
        trace_id=evidence.trace_id,
    )


# ---------------------------------------------------------------------------
# Public convenience wrappers
# ---------------------------------------------------------------------------


def build_offline_operational_verdict(
    evidence: OfflineOperationalEvidence,
) -> OfflineOperationalVerdict:
    """Convenience wrapper around :func:`classify_offline_operational`.

    Equivalent to calling ``classify_offline_operational(evidence)`` directly.
    Provided for naming symmetry with other taxonomy modules in the system.
    """
    return classify_offline_operational(evidence)


def build_baseline_offline_operational_verdict() -> OfflineOperationalVerdict:
    """Return the baseline (zero-evidence) offline operational verdict.

    This is the honest starting state for a process instance that has not
    yet received any connectivity or operational evidence.  The verdict will
    be ``unavailable`` with an appropriate rationale.

    Used by the acceptance evaluator to confirm the contract is wired and
    conservatively defaults rather than optimistically assuming online status.
    """
    evidence = OfflineOperationalEvidence()
    return classify_offline_operational(evidence)
