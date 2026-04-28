#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/delegated_flow_decision_history.py
========================================
PR-V2-4DH (delegated flow decision history and evidence closure):
Delegated Flow Decision History — formal runtime event recording and
evidence-closure assessment for the delegated canonical path.

Background
----------
The delegated canonical path has progressively gained code-level gates,
readiness checks, and acceptance verdicts (PR-9V2 through PR-12V2).
However, in an idle or newly-deployed environment those gates produce
"unknown" or "rejected" verdicts simply because no delegated flow has
ever been exercised — not because the path is broken.

Without a dedicated decision history mechanism:

* The system cannot distinguish "never triggered" from "triggered but
  consistently rejected".
* Audit reviewers and release operators cannot tell whether the delegated
  path has been exercised end-to-end even once.
* The ``system_final_acceptance_verdict`` (PR-17V2) conflates all forms of
  "insufficient evidence" into a single opaque pending/unresolved bucket.

This module closes that gap by establishing the **Delegated Flow Decision
History** — the authoritative registry that records every material event
on the delegated canonical path (trigger, readiness decision, acceptance
decision, reroute, reject, accept, complete) and evaluates the resulting
history into a structured evidence-closure report.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  DELEGATED FLOW DECISION HISTORY  (this module — PR-V2-4DH)        │
    │                                                                     │
    │  Records:                                                          │
    │    • triggered          — a delegated flow was initiated            │
    │    • readiness_decision — readiness gate decided pass/fail         │
    │    • acceptance_decision— acceptance gate decided pass/fail        │
    │    • rerouted           — flow was rerouted to alternate path      │
    │    • rejected           — flow was rejected at a gate              │
    │    • accepted           — flow was accepted / graduated            │
    │    • completed          — flow reached terminal completed state    │
    │                                                                     │
    │  Produces HistoryEvidenceStatus:                                   │
    │    • no_history_yet              — registry is empty               │
    │    • insufficient_evidence       — too few events for conclusion   │
    │    • observed_but_incomplete     — some branches seen, not all     │
    │    • observed_and_closed         — all required events witnessed   │
    │    • historical_evidence_stale   — history exists but is old       │
    │                                                                     │
    │  Exposes:                                                          │
    │    • structure_present           — gates/code importable (static)  │
    │    • runtime_closure_established — real run history proves it works │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified.
2. **Fail-conservative** — when history is absent or stale, the module
   never optimistically promotes the verdict.  Silence is NOT evidence
   of correctness.
3. **Fine-grained evidence status** — five distinct states prevent the
   "everything is just pending" problem.
4. **Layered reporting** — ``structure_present`` and
   ``runtime_closure_established`` are separate boolean fields so
   consumers can distinguish "code exists" from "run history proves it".
5. **Stable artifacts** — all data classes are JSON-serialisable
   (``to_dict`` / ``to_json``).
6. **Singleton with test-reset** — :func:`get_decision_history` returns
   the process-global singleton; :func:`reset_decision_history` clears
   it for test isolation.

Public API
----------
Authority sentinels::

    DELEGATED_FLOW_DECISION_HISTORY_AUTHORITY
    DELEGATED_FLOW_DECISION_HISTORY_PR_V2_4DH_SENTINEL

Policy sentinels::

    HISTORY_FAIL_CONSERVATIVE_POLICY
    HISTORY_FIVE_STATE_EVIDENCE_STATUS_POLICY
    HISTORY_STRUCTURE_VS_RUNTIME_CLOSURE_POLICY
    HISTORY_STALENESS_IS_DOWNGRADE_POLICY
    HISTORY_SILENCE_IS_NOT_EVIDENCE_POLICY

Enumerations::

    HistoryEvidenceStatus
    DelegatedFlowEventKind

Data classes::

    DelegatedFlowHistoryEntry
    DelegatedFlowHistoryReport

Class::

    DelegatedFlowDecisionHistory

Helpers::

    record_delegated_flow_event(kind, ...) -> DelegatedFlowHistoryEntry
    evaluate_delegated_flow_history()      -> DelegatedFlowHistoryReport
    get_decision_history()                 -> DelegatedFlowDecisionHistory
    reset_decision_history()               -> None  (testing only)
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.DelegatedFlowDecisionHistory")

__all__ = [
    # Authority sentinels
    "DELEGATED_FLOW_DECISION_HISTORY_AUTHORITY",
    "DELEGATED_FLOW_DECISION_HISTORY_PR_V2_4DH_SENTINEL",
    # Policy sentinels
    "HISTORY_FAIL_CONSERVATIVE_POLICY",
    "HISTORY_FIVE_STATE_EVIDENCE_STATUS_POLICY",
    "HISTORY_STRUCTURE_VS_RUNTIME_CLOSURE_POLICY",
    "HISTORY_STALENESS_IS_DOWNGRADE_POLICY",
    "HISTORY_SILENCE_IS_NOT_EVIDENCE_POLICY",
    # Enumerations
    "HistoryEvidenceStatus",
    "DelegatedFlowEventKind",
    # Data classes
    "DelegatedFlowHistoryEntry",
    "DelegatedFlowHistoryReport",
    # Class
    "DelegatedFlowDecisionHistory",
    # Helpers
    "record_delegated_flow_event",
    "evaluate_delegated_flow_history",
    "get_decision_history",
    "reset_decision_history",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

DELEGATED_FLOW_DECISION_HISTORY_AUTHORITY: str = (
    "DELEGATED_FLOW_DECISION_HISTORY_AUTHORITY::"
    "core.delegated_flow_decision_history::PR-V2-4DH::"
    "delegated-flow-decision-history-evidence-closure::"
    "runtime-history-not-static-structure"
)
"""Sentinel: this module is the canonical delegated flow decision history
authority.

Import to assert that a release pipeline, audit reviewer, or acceptance
evaluator is consuming real runtime history rather than static structure
assertions."""

DELEGATED_FLOW_DECISION_HISTORY_PR_V2_4DH_SENTINEL: str = (
    "DELEGATED_FLOW_DECISION_HISTORY_PR_V2_4DH_SENTINEL::"
    "package=PR-V2-4DH::profile=delegated-flow-decision-history-v1::"
    "module=core.delegated_flow_decision_history"
)
"""Package sentinel for PR-V2-4DH."""

HISTORY_FAIL_CONSERVATIVE_POLICY: str = (
    "POLICY::HISTORY_FAIL_CONSERVATIVE_V1: "
    "When the decision history registry is empty, stale, or insufficient, "
    "DelegatedFlowDecisionHistory.evaluate() MUST return a HistoryEvidenceStatus "
    "that reflects the actual evidence deficit.  It MUST NOT optimistically "
    "promote the status to observed_and_closed or return "
    "runtime_closure_established=True without witnessing the required event "
    "sequence.  Silence is NOT evidence of correctness.  PR-V2-4DH."
)

HISTORY_FIVE_STATE_EVIDENCE_STATUS_POLICY: str = (
    "POLICY::HISTORY_FIVE_STATE_EVIDENCE_STATUS_V1: "
    "Evidence status MUST be reported using all five HistoryEvidenceStatus "
    "values as appropriate: no_history_yet, insufficient_evidence, "
    "observed_but_incomplete, observed_and_closed, historical_evidence_stale.  "
    "Collapsing distinct evidence gaps into a single 'pending' is prohibited.  "
    "PR-V2-4DH."
)

HISTORY_STRUCTURE_VS_RUNTIME_CLOSURE_POLICY: str = (
    "POLICY::HISTORY_STRUCTURE_VS_RUNTIME_CLOSURE_V1: "
    "DelegatedFlowHistoryReport MUST separately surface structure_present "
    "(delegated flow gate code is importable) and runtime_closure_established "
    "(real run history proves end-to-end closure).  Treating 'code exists' as "
    "'run history proves it works' is prohibited.  PR-V2-4DH."
)

HISTORY_STALENESS_IS_DOWNGRADE_POLICY: str = (
    "POLICY::HISTORY_STALENESS_IS_DOWNGRADE_V1: "
    "When the most recent history entry is older than the configured "
    "staleness_threshold_seconds, the evidence status MUST be downgraded to "
    "historical_evidence_stale regardless of how complete the prior history "
    "was.  Stale history MUST NOT produce runtime_closure_established=True.  "
    "PR-V2-4DH."
)

HISTORY_SILENCE_IS_NOT_EVIDENCE_POLICY: str = (
    "POLICY::HISTORY_SILENCE_IS_NOT_EVIDENCE_V1: "
    "An empty history registry MUST produce HistoryEvidenceStatus.no_history_yet "
    "and runtime_closure_established=False.  No inference about operational "
    "correctness MAY be drawn from the absence of error events.  PR-V2-4DH."
)


# ---------------------------------------------------------------------------
# HistoryEvidenceStatus
# ---------------------------------------------------------------------------


class HistoryEvidenceStatus(str, Enum):
    """Five-tier evidence status for the delegated flow decision history.

    Tiers represent increasing levels of run-history confidence.

    ``no_history_yet``
        The history registry is completely empty.  No delegated flow has
        ever been triggered in this process lifetime.  The system is idle
        or freshly deployed.

    ``insufficient_evidence``
        At least one event has been recorded but the history does not yet
        contain enough events to draw a meaningful conclusion about
        end-to-end closure.  A single "triggered" event without any gate
        decision falls here.

    ``observed_but_incomplete``
        Multiple event types have been recorded (e.g. triggered and
        readiness_decision) but at least one required branch (accept,
        reject, complete, or reroute) has not yet been witnessed.

    ``observed_and_closed``
        All required event types have been witnessed in at least one
        complete flow cycle (triggered → gate decision → terminal event).
        This is the only status that allows
        ``runtime_closure_established=True``.

    ``historical_evidence_stale``
        A complete closed history existed but the most recent entry is
        older than the configured staleness threshold.  Prior completeness
        does not guarantee current operational status.
    """

    no_history_yet = "no_history_yet"
    insufficient_evidence = "insufficient_evidence"
    observed_but_incomplete = "observed_but_incomplete"
    observed_and_closed = "observed_and_closed"
    historical_evidence_stale = "historical_evidence_stale"

    @classmethod
    def from_string(cls, value: str) -> "HistoryEvidenceStatus":
        """Return the member matching *value*, defaulting to ``no_history_yet``."""
        if not isinstance(value, str):
            return cls.no_history_yet
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.no_history_yet

    @property
    def allows_runtime_closure(self) -> bool:
        """Return ``True`` only when status permits runtime_closure_established=True."""
        return self == HistoryEvidenceStatus.observed_and_closed

    @property
    def is_definitive_gap(self) -> bool:
        """Return ``True`` when the status represents a clear evidence deficit."""
        return self in (
            HistoryEvidenceStatus.no_history_yet,
            HistoryEvidenceStatus.historical_evidence_stale,
        )


# ---------------------------------------------------------------------------
# DelegatedFlowEventKind
# ---------------------------------------------------------------------------


class DelegatedFlowEventKind(str, Enum):
    """Kind of event recorded in the delegated flow decision history.

    ``triggered``
        A delegated flow was initiated.  This is the entry point of the
        evidence chain.  A flow that was triggered but never decided is
        an incomplete history.

    ``readiness_decision``
        The delegated flow readiness gate (PR-9V2) produced a decision for
        this flow.  The ``decision_result`` field carries the verdict value
        (e.g. ``"ready_for_release"`` / ``"not_ready_*"``).

    ``acceptance_decision``
        The delegated flow acceptance gate (PR-10V2) produced a decision.
        The ``decision_result`` field carries the verdict value.

    ``rerouted``
        The flow was rerouted to an alternate execution path (e.g. local
        fallback, different device, recovery coordinator redirect).

    ``rejected``
        The flow was rejected at a gate (readiness, acceptance, or policy
        gate).  The ``decision_result`` field carries the rejection reason.

    ``accepted``
        The flow was formally accepted / graduated by the acceptance gate
        or a downstream routing decision.

    ``completed``
        The flow reached a terminal ``completed`` state (all work done,
        result reconciled, no further routing needed).
    """

    triggered = "triggered"
    readiness_decision = "readiness_decision"
    acceptance_decision = "acceptance_decision"
    rerouted = "rerouted"
    rejected = "rejected"
    accepted = "accepted"
    completed = "completed"

    @classmethod
    def from_string(cls, value: str) -> "DelegatedFlowEventKind":
        """Return the member matching *value*, defaulting to ``triggered``."""
        if not isinstance(value, str):
            return cls.triggered
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.triggered

    @property
    def is_terminal(self) -> bool:
        """Return ``True`` when this event kind marks a terminal flow outcome."""
        return self in (
            DelegatedFlowEventKind.completed,
            DelegatedFlowEventKind.rejected,
            DelegatedFlowEventKind.rerouted,
            DelegatedFlowEventKind.accepted,
        )


# ---------------------------------------------------------------------------
# DelegatedFlowHistoryEntry
# ---------------------------------------------------------------------------


@dataclass
class DelegatedFlowHistoryEntry:
    """A single recorded event in the delegated flow decision history.

    Fields
    ------
    entry_id
        Unique identifier for this history entry (UUID hex prefix).
    kind
        The type of event recorded.
    flow_id
        Delegated flow entity identifier.  May be empty when not available
        at recording time.
    decision_result
        The decision outcome string (e.g. verdict value, rejection reason,
        routing target).  Empty string for non-decision events like
        ``triggered`` or ``completed``.
    context
        Minimum necessary context for audit and capability routing linkage.
        Callers should include capability name, session ID, contract ID,
        and/or continuity artifact ID as available.
    recorded_at
        Unix timestamp when this entry was recorded.
    """

    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    kind: DelegatedFlowEventKind = DelegatedFlowEventKind.triggered
    flow_id: str = ""
    decision_result: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    recorded_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "entry_id": self.entry_id,
            "kind": self.kind.value,
            "flow_id": self.flow_id,
            "decision_result": self.decision_result,
            "context": self.context,
            "recorded_at": self.recorded_at,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedFlowHistoryEntry":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        return cls(
            entry_id=data.get("entry_id", uuid.uuid4().hex[:12]),
            kind=DelegatedFlowEventKind.from_string(data.get("kind", "")),
            flow_id=data.get("flow_id", ""),
            decision_result=data.get("decision_result", ""),
            context=data.get("context", {}),
            recorded_at=data.get("recorded_at", time.time()),
        )


# ---------------------------------------------------------------------------
# DelegatedFlowHistoryReport
# ---------------------------------------------------------------------------

#: Minimum number of distinct event kind categories required for
#: ``observed_and_closed`` status.  A complete cycle requires:
#: triggered + at least one gate decision + at least one terminal event.
_MIN_KINDS_FOR_CLOSURE = 3

#: Event kinds that constitute "gate decisions".
_DECISION_KINDS = frozenset(
    [
        DelegatedFlowEventKind.readiness_decision,
        DelegatedFlowEventKind.acceptance_decision,
    ]
)

#: Event kinds that constitute "terminal outcomes".
_TERMINAL_KINDS = frozenset(
    [
        DelegatedFlowEventKind.completed,
        DelegatedFlowEventKind.rejected,
        DelegatedFlowEventKind.rerouted,
        DelegatedFlowEventKind.accepted,
    ]
)

#: Default staleness threshold in seconds (24 hours).
DEFAULT_STALENESS_THRESHOLD_SECONDS: float = 86400.0


@dataclass
class DelegatedFlowHistoryReport:
    """Evidence-closure report for the delegated flow decision history.

    Fields
    ------
    report_id
        Unique identifier for this report (UUID hex prefix).
    evidence_status
        Five-tier status describing the quality and completeness of the
        recorded history.  This is the primary signal for consumers.
    structure_present
        ``True`` when the delegated flow gate / code is confirmed importable
        (i.e. the *structural* prerequisite exists).  This is a static
        property of the deployment; it does NOT imply real runs have
        occurred.
    runtime_closure_established
        ``True`` ONLY when ``evidence_status`` is ``observed_and_closed``
        and the history is not stale.  This flag is the formal claim that
        real runtime evidence proves end-to-end delegated flow closure.
    total_entries
        Total number of history entries recorded.
    observed_kinds
        Set of DelegatedFlowEventKind values that have been witnessed at
        least once.
    gap_description
        Human-readable description of any evidence gap.  Must be non-empty
        when ``evidence_status`` is not ``observed_and_closed``.
    summary
        One-line human-readable summary of the history state.
    staleness_threshold_seconds
        The threshold used for staleness evaluation.
    latest_entry_age_seconds
        Age of the most recent history entry in seconds, or ``None`` when
        the registry is empty.
    evaluated_at
        Unix timestamp when this report was generated.
    """

    report_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    evidence_status: HistoryEvidenceStatus = HistoryEvidenceStatus.no_history_yet
    structure_present: bool = False
    runtime_closure_established: bool = False
    total_entries: int = 0
    observed_kinds: List[str] = field(default_factory=list)
    gap_description: str = ""
    summary: str = ""
    staleness_threshold_seconds: float = DEFAULT_STALENESS_THRESHOLD_SECONDS
    latest_entry_age_seconds: Optional[float] = None
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "report_id": self.report_id,
            "evidence_status": self.evidence_status.value,
            "structure_present": self.structure_present,
            "runtime_closure_established": self.runtime_closure_established,
            "total_entries": self.total_entries,
            "observed_kinds": self.observed_kinds,
            "gap_description": self.gap_description,
            "summary": self.summary,
            "staleness_threshold_seconds": self.staleness_threshold_seconds,
            "latest_entry_age_seconds": self.latest_entry_age_seconds,
            "evaluated_at": self.evaluated_at,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedFlowHistoryReport":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        return cls(
            report_id=data.get("report_id", uuid.uuid4().hex[:12]),
            evidence_status=HistoryEvidenceStatus.from_string(
                data.get("evidence_status", "")
            ),
            structure_present=data.get("structure_present", False),
            runtime_closure_established=data.get("runtime_closure_established", False),
            total_entries=data.get("total_entries", 0),
            observed_kinds=data.get("observed_kinds", []),
            gap_description=data.get("gap_description", ""),
            summary=data.get("summary", ""),
            staleness_threshold_seconds=data.get(
                "staleness_threshold_seconds", DEFAULT_STALENESS_THRESHOLD_SECONDS
            ),
            latest_entry_age_seconds=data.get("latest_entry_age_seconds"),
            evaluated_at=data.get("evaluated_at", time.time()),
        )


# ---------------------------------------------------------------------------
# Structure probe — imported lazily to avoid circular imports
# ---------------------------------------------------------------------------

def _probe_structure_present() -> bool:
    """Return True when the delegated flow acceptance gate is importable.

    This is a static deployment-time check.  It does not imply that any
    real delegated flow has ever been triggered.
    """
    try:
        import core.delegated_flow_acceptance_gate as _m  # noqa: F401
        return hasattr(_m, "DelegatedFlowAcceptanceGate")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# DelegatedFlowDecisionHistory
# ---------------------------------------------------------------------------


class DelegatedFlowDecisionHistory:
    """Registry for recording and evaluating delegated flow decision history.

    The registry stores all material events on the delegated canonical path
    in an append-only in-memory list.  Events survive process restarts only
    if persisted externally; within a process lifetime, the registry is the
    authoritative source for history evidence.

    Use :func:`get_decision_history` to obtain the process-global singleton.
    Use :func:`reset_decision_history` for test isolation.

    Usage
    -----
    ::

        from core.delegated_flow_decision_history import (
            get_decision_history,
            DelegatedFlowEventKind,
        )

        history = get_decision_history()
        history.record(
            kind=DelegatedFlowEventKind.triggered,
            flow_id="flow-abc",
            context={"capability": "execute_task", "session_id": "s-123"},
        )
        report = history.evaluate()
        if not report.runtime_closure_established:
            print(f"[HISTORY] {report.evidence_status.value}: {report.gap_description}")
    """

    def __init__(
        self,
        *,
        staleness_threshold_seconds: float = DEFAULT_STALENESS_THRESHOLD_SECONDS,
    ) -> None:
        self._entries: List[DelegatedFlowHistoryEntry] = []
        self._staleness_threshold_seconds = staleness_threshold_seconds

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        kind: DelegatedFlowEventKind,
        *,
        flow_id: str = "",
        decision_result: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> DelegatedFlowHistoryEntry:
        """Record a delegated flow event and return the created entry.

        Parameters
        ----------
        kind
            The type of event being recorded.
        flow_id
            Delegated flow entity identifier (optional).
        decision_result
            Decision outcome string (optional; relevant for decision events).
        context
            Minimum necessary context dict (capability, session, contract,
            continuity artifact, etc.).

        Returns
        -------
        DelegatedFlowHistoryEntry
            The newly created and stored history entry.
        """
        entry = DelegatedFlowHistoryEntry(
            kind=kind,
            flow_id=flow_id,
            decision_result=decision_result,
            context=context or {},
        )
        self._entries.append(entry)
        logger.debug(
            "DelegatedFlowDecisionHistory.record: kind=%s flow_id=%r result=%r",
            kind.value,
            flow_id,
            decision_result,
        )
        return entry

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> List[DelegatedFlowHistoryEntry]:
        """Return a snapshot (copy) of all recorded entries."""
        return list(self._entries)

    def entry_count(self) -> int:
        """Return the number of recorded entries."""
        return len(self._entries)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(self) -> DelegatedFlowHistoryReport:
        """Evaluate the recorded history and return an evidence-closure report.

        Evaluation logic
        ----------------
        1. Check ``structure_present`` (static deployment probe).
        2. If no entries → ``no_history_yet``.
        3. If entries exist, find the latest entry age.
        4. If latest entry is stale AND history was otherwise complete →
           ``historical_evidence_stale``.
        5. Check whether all three required categories are witnessed:
           - at least one ``triggered`` event
           - at least one gate decision event (readiness or acceptance)
           - at least one terminal outcome event (completed/rejected/rerouted/accepted)
        6. If all three categories witnessed and not stale →
           ``observed_and_closed``.
        7. If triggered + at least one other category but not all →
           ``observed_but_incomplete``.
        8. If only triggered (or only one category) → ``insufficient_evidence``.

        Returns
        -------
        DelegatedFlowHistoryReport
        """
        structure_present = _probe_structure_present()
        entries = self._entries
        now = time.time()

        if not entries:
            return DelegatedFlowHistoryReport(
                evidence_status=HistoryEvidenceStatus.no_history_yet,
                structure_present=structure_present,
                runtime_closure_established=False,
                total_entries=0,
                observed_kinds=[],
                gap_description=(
                    "No delegated flow events have been recorded.  "
                    "The system is idle or freshly deployed.  "
                    "A delegated flow must be triggered at least once "
                    "before history-based evidence can be evaluated."
                ),
                summary="no_history_yet: registry empty; no delegated flow has been triggered",
                staleness_threshold_seconds=self._staleness_threshold_seconds,
                latest_entry_age_seconds=None,
            )

        # Collect observed kinds and latest timestamp
        observed_kind_set: set = set()
        latest_ts = 0.0
        for e in entries:
            observed_kind_set.add(e.kind)
            if e.recorded_at > latest_ts:
                latest_ts = e.recorded_at

        latest_age = now - latest_ts
        observed_kinds_list = sorted(k.value for k in observed_kind_set)
        total = len(entries)

        has_trigger = DelegatedFlowEventKind.triggered in observed_kind_set
        has_decision = bool(observed_kind_set & _DECISION_KINDS)
        has_terminal = bool(observed_kind_set & _TERMINAL_KINDS)

        # Check staleness before completeness
        is_stale = latest_age > self._staleness_threshold_seconds

        # Completeness: trigger + decision + terminal
        is_complete = has_trigger and has_decision and has_terminal

        if is_stale:
            # Stale beats completeness — even a previously complete history
            # does not establish current runtime closure.
            return DelegatedFlowHistoryReport(
                evidence_status=HistoryEvidenceStatus.historical_evidence_stale,
                structure_present=structure_present,
                runtime_closure_established=False,
                total_entries=total,
                observed_kinds=observed_kinds_list,
                gap_description=(
                    f"History exists ({total} entries) but the most recent entry is "
                    f"{latest_age:.0f}s old (threshold: "
                    f"{self._staleness_threshold_seconds:.0f}s).  "
                    "Stale history does not establish current runtime closure."
                ),
                summary=(
                    f"historical_evidence_stale: {total} entries; "
                    f"latest {latest_age:.0f}s ago (threshold "
                    f"{self._staleness_threshold_seconds:.0f}s)"
                ),
                staleness_threshold_seconds=self._staleness_threshold_seconds,
                latest_entry_age_seconds=latest_age,
            )

        if is_complete:
            return DelegatedFlowHistoryReport(
                evidence_status=HistoryEvidenceStatus.observed_and_closed,
                structure_present=structure_present,
                runtime_closure_established=True,
                total_entries=total,
                observed_kinds=observed_kinds_list,
                gap_description="",
                summary=(
                    f"observed_and_closed: {total} entries; "
                    f"trigger+decision+terminal all witnessed; "
                    f"runtime closure established"
                ),
                staleness_threshold_seconds=self._staleness_threshold_seconds,
                latest_entry_age_seconds=latest_age,
            )

        # Determine partial/insufficient
        categories_seen = sum([has_trigger, has_decision, has_terminal])
        missing_parts = []
        if not has_trigger:
            missing_parts.append("trigger event")
        if not has_decision:
            missing_parts.append("gate decision event (readiness or acceptance)")
        if not has_terminal:
            missing_parts.append("terminal outcome event (accepted/rejected/rerouted/completed)")

        if categories_seen >= 2:
            status = HistoryEvidenceStatus.observed_but_incomplete
            gap_desc = (
                f"Partial history: {total} entries; "
                f"missing: {'; '.join(missing_parts)}.  "
                "End-to-end closure has not been witnessed."
            )
            summary_str = (
                f"observed_but_incomplete: {total} entries; "
                f"missing {len(missing_parts)} category/ies"
            )
        else:
            status = HistoryEvidenceStatus.insufficient_evidence
            gap_desc = (
                f"Insufficient history: {total} entries recorded but only "
                f"{categories_seen} of 3 required event categories seen.  "
                f"Missing: {'; '.join(missing_parts)}.  "
                "Cannot assess end-to-end closure."
            )
            summary_str = (
                f"insufficient_evidence: {total} entries; "
                f"{categories_seen}/3 required categories"
            )

        return DelegatedFlowHistoryReport(
            evidence_status=status,
            structure_present=structure_present,
            runtime_closure_established=False,
            total_entries=total,
            observed_kinds=observed_kinds_list,
            gap_description=gap_desc,
            summary=summary_str,
            staleness_threshold_seconds=self._staleness_threshold_seconds,
            latest_entry_age_seconds=latest_age,
        )


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_SINGLETON: Optional[DelegatedFlowDecisionHistory] = None


def get_decision_history() -> DelegatedFlowDecisionHistory:
    """Return the process-global :class:`DelegatedFlowDecisionHistory` singleton.

    The singleton is created on first call and reused on subsequent calls.
    Use :func:`reset_decision_history` in tests to obtain a fresh instance.
    """
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = DelegatedFlowDecisionHistory()
    return _SINGLETON


def reset_decision_history() -> None:
    """Reset the process-global singleton (for test isolation only).

    After calling this function, the next call to :func:`get_decision_history`
    will return a fresh, empty :class:`DelegatedFlowDecisionHistory`.
    """
    global _SINGLETON
    _SINGLETON = None


# ---------------------------------------------------------------------------
# Module-level convenience helpers
# ---------------------------------------------------------------------------


def record_delegated_flow_event(
    kind: DelegatedFlowEventKind,
    *,
    flow_id: str = "",
    decision_result: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> DelegatedFlowHistoryEntry:
    """Record a delegated flow event in the process-global singleton registry.

    Parameters
    ----------
    kind
        The :class:`DelegatedFlowEventKind` to record.
    flow_id
        Delegated flow entity identifier (optional).
    decision_result
        Decision outcome / verdict string (optional).
    context
        Minimum necessary context dict (optional).

    Returns
    -------
    DelegatedFlowHistoryEntry
        The newly recorded entry.
    """
    return get_decision_history().record(
        kind=kind,
        flow_id=flow_id,
        decision_result=decision_result,
        context=context,
    )


def evaluate_delegated_flow_history() -> DelegatedFlowHistoryReport:
    """Evaluate the process-global singleton history and return a report.

    Returns
    -------
    DelegatedFlowHistoryReport
        Evidence-closure report for the current process's delegated flow
        history.
    """
    return get_decision_history().evaluate()
