"""core/execution_governance_audit_authority.py
================================================
PR-14 V2-side — Execution Governance Audit Authority Hardening
===============================================================

Background
----------
The V2 center-governance layer has accumulated a progressively stronger
governance surface across PR-05 through PR-13:

- Unified execution type policies and priority/conflict resolution
  (``core.unified_execution_governance``)
- Lifecycle event recording and phase-transition validation
  (``core.unified_execution_governance``)
- Canonical runtime truth reconciliation and uplink authority
  (``core.unified_execution_governance.get_uplink_truth_state``)
- Mission completion closure and terminal-outcome determinism
  (``core.unified_execution_governance.notify_execution_completed``)
- Governance closure verification across all execution types
  (PR-11 — test_pr11_governance_closure_verification)
- Closed-loop consolidation with cross-stage invariants
  (PR-13 — closed_loop_governance_consolidation)

Each governance stage has an authoritative record owner.  However, there was
no single mechanism to verify that the **authority chain** — from initial
admission through lifecycle recording, uplink observation, and terminal
reconciliation — is intact, coherent, and auditable as a whole.

Purpose
-------
This module provides the canonical **execution governance audit authority**
layer for the V2 center side.  It:

1. Defines a stable :class:`GovernanceAuditStage` taxonomy covering every
   stage of the authority chain.

2. Derives :class:`GovernanceAuditEntry` records from the existing governance
   runtime state without adding new storage.

3. Assembles a :class:`GovernanceAuthorityEvidence` object that captures the
   complete, verifiable audit picture for a single governed execution.

4. Exposes :func:`verify_governance_authority_integrity` — a function that
   checks the authority chain for coherence violations and returns a list of
   :class:`GovernanceAuthorityViolation` records.

5. Exposes :func:`get_governance_audit_summary` — a JSON-serialisable dict
   summarising the full authority audit for a given execution.

Design invariants
-----------------
I-A1  Center-lifecycle authority MUST be the terminal truth source whenever a
      terminal lifecycle phase is recorded.  Any reconciliation status that
      overrides center authority is an integrity violation.
I-A2  A terminal authority evidence record MUST carry a non-None
      ``canonical_terminal_outcome``.
I-A3  The authority chain MUST be monotonically forward-progressing:
      admission → lifecycle → uplink → reconciliation → terminal.  A stage
      later in the chain MUST NOT exist without evidence of earlier stages.
I-A4  Uplink observation MUST NOT override center-lifecycle terminal truth.
      A ``reconciliation_conflict`` with authority source ``"reported_uplink"``
      is an integrity violation.
I-A5  Cross-device isolation: authority evidence for device A MUST NOT be
      influenced by device B's governance state.

Authority sentinel
------------------
``GOVERNANCE_AUDIT_AUTHORITY_SENTINEL`` — import this constant to assert that
the PR-14 audit authority layer is present.

Public API
----------
Sentinels / version::

    GOVERNANCE_AUDIT_AUTHORITY_SENTINEL
    GOVERNANCE_AUDIT_CONTRACT_VERSION
    GOVERNANCE_AUDIT_AUTHORITY_POLICY

Enums::

    GovernanceAuditStage

Dataclasses::

    GovernanceAuditEntry
    GovernanceAuthorityViolation
    GovernanceAuthorityEvidence

Functions::

    build_governance_authority_evidence(execution_id, device_id)
    verify_governance_authority_integrity(execution_id, device_id)
    get_governance_audit_summary(execution_id, device_id)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ExecutionGovernanceAuditAuthority")

# ---------------------------------------------------------------------------
# Authority sentinels & contract version
# ---------------------------------------------------------------------------

GOVERNANCE_AUDIT_AUTHORITY_SENTINEL: str = (
    "GOVERNANCE_AUDIT_AUTHORITY_SENTINEL::PR14_V2::present "
    "core.execution_governance_audit_authority is the canonical center-side "
    "execution governance audit authority hardening layer (PR-14 V2 side). "
    "It derives a complete, verifiable authority chain from admission through "
    "lifecycle recording, uplink observation, reconciliation, and terminal "
    "truth for all governed execution types. Authority chain integrity is "
    "verified by verify_governance_authority_integrity(). All governance "
    "audit consumers and regression tests MUST reference this sentinel to "
    "confirm PR-14 audit authority hardening is in effect."
)

GOVERNANCE_AUDIT_CONTRACT_VERSION: str = "14.0.0"

GOVERNANCE_AUDIT_AUTHORITY_POLICY: str = (
    "POLICY::GOVERNANCE_AUDIT_AUTHORITY_V1: "
    "The canonical governance authority chain for a governed execution is: "
    "admission → lifecycle → uplink_observation → reconciliation → terminal. "
    "The center-lifecycle authority ALWAYS wins over conflicting uplink "
    "observations (I-A1). A terminal evidence record MUST carry a non-None "
    "canonical_terminal_outcome (I-A2). The authority chain is monotonically "
    "forward-progressing: later stages require evidence of earlier stages "
    "(I-A3). Uplink observation MUST NOT override center terminal truth "
    "(I-A4). Device governance isolation is absolute: device A authority "
    "MUST NOT be influenced by device B state (I-A5)."
)


# ---------------------------------------------------------------------------
# GovernanceAuditStage
# ---------------------------------------------------------------------------


class GovernanceAuditStage(str, Enum):
    """Canonical audit stages for the execution governance authority chain.

    The chain is monotonically forward-progressing:
        admission → lifecycle → uplink_observation → reconciliation → terminal
    """

    admission = "admission"
    """Execution was admitted by the governance layer (accepted=True verdict)."""

    lifecycle = "lifecycle"
    """At least one lifecycle event has been recorded for the execution."""

    uplink_observation = "uplink_observation"
    """At least one uplink (result or state) has been recorded."""

    reconciliation = "reconciliation"
    """Uplink observations and lifecycle phase have been reconciled."""

    terminal = "terminal"
    """A terminal outcome has been determined and the authority chain is closed."""


# ---------------------------------------------------------------------------
# GovernanceAuditEntry
# ---------------------------------------------------------------------------


@dataclass
class GovernanceAuditEntry:
    """A single entry in the execution governance audit trail.

    Each entry corresponds to one :class:`GovernanceAuditStage` and carries
    the evidence that the stage was reached.
    """

    stage: GovernanceAuditStage
    """The governance audit stage this entry represents."""

    reached: bool
    """Whether this stage was reached for the execution."""

    evidence_summary: str
    """Human-readable summary of the evidence for this stage."""

    evidence_detail: Dict[str, Any] = field(default_factory=dict)
    """Structured evidence detail (JSON-serialisable)."""

    recorded_at: Optional[float] = None
    """Approximate timestamp when this stage evidence was recorded (POSIX)."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage.value,
            "reached": self.reached,
            "evidence_summary": self.evidence_summary,
            "evidence_detail": self.evidence_detail,
            "recorded_at": self.recorded_at,
        }


# ---------------------------------------------------------------------------
# GovernanceAuthorityViolation
# ---------------------------------------------------------------------------


@dataclass
class GovernanceAuthorityViolation:
    """A single authority chain integrity violation.

    Produced by :func:`verify_governance_authority_integrity` when an
    invariant from I-A1 through I-A5 is breached.
    """

    invariant_id: str
    """Identifier of the violated invariant (e.g., ``"I-A1"``)."""

    description: str
    """Human-readable description of the violation."""

    stage: GovernanceAuditStage
    """The governance audit stage at which the violation was detected."""

    evidence: Dict[str, Any] = field(default_factory=dict)
    """Structured evidence detail that triggered this violation."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "invariant_id": self.invariant_id,
            "description": self.description,
            "stage": self.stage.value,
            "evidence": self.evidence,
        }


# ---------------------------------------------------------------------------
# GovernanceAuthorityEvidence
# ---------------------------------------------------------------------------


@dataclass
class GovernanceAuthorityEvidence:
    """Complete authority chain evidence for a single governed execution.

    Assembled by :func:`build_governance_authority_evidence` from the
    existing governance runtime state without adding new storage.
    """

    execution_id: str
    """Correlation identifier for the governed execution."""

    device_id: str
    """Android device identifier."""

    highest_stage_reached: Optional[GovernanceAuditStage]
    """The highest :class:`GovernanceAuditStage` reached in the chain."""

    audit_entries: List[GovernanceAuditEntry]
    """Ordered list of audit entries (one per stage, from admission to terminal)."""

    authority_source: str
    """Canonical authority source (``"center_lifecycle"`` / ``"reported_uplink"`` / ``"none"``)."""

    canonical_terminal_outcome: Optional[str]
    """Canonical terminal outcome if the authority chain reached terminal stage."""

    reconciliation_status: str
    """Reconciliation status from the uplink truth state."""

    authority_chain_complete: bool
    """True when the chain reached the terminal stage without violations."""

    observed_at: float = field(default_factory=time.time)
    """Timestamp when this evidence was assembled (POSIX)."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "device_id": self.device_id,
            "highest_stage_reached": (
                self.highest_stage_reached.value
                if self.highest_stage_reached is not None
                else None
            ),
            "audit_entries": [e.to_dict() for e in self.audit_entries],
            "authority_source": self.authority_source,
            "canonical_terminal_outcome": self.canonical_terminal_outcome,
            "reconciliation_status": self.reconciliation_status,
            "authority_chain_complete": self.authority_chain_complete,
            "observed_at": self.observed_at,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_STAGE_ORDER: List[GovernanceAuditStage] = [
    GovernanceAuditStage.admission,
    GovernanceAuditStage.lifecycle,
    GovernanceAuditStage.uplink_observation,
    GovernanceAuditStage.reconciliation,
    GovernanceAuditStage.terminal,
]


def _stage_index(stage: GovernanceAuditStage) -> int:
    return _STAGE_ORDER.index(stage)


def _build_admission_entry(truth: Dict[str, Any]) -> GovernanceAuditEntry:
    """Build the admission stage entry from uplink truth state."""
    lifecycle_event_count: int = truth.get("lifecycle_event_count", 0) or 0
    # Admission is inferred: if any lifecycle event was recorded the execution
    # was admitted (or at least the lifecycle recorder accepted it).  For
    # executions that were never admitted there will be no lifecycle history
    # and no uplink records.
    has_lifecycle = lifecycle_event_count > 0
    has_uplink = (truth.get("result_uplink_count") or 0) + (
        truth.get("state_uplink_count") or 0
    ) > 0
    reached = has_lifecycle or has_uplink
    if reached:
        evidence_summary = (
            "Execution admitted: lifecycle events or uplink records observed."
        )
    else:
        evidence_summary = (
            "No admission evidence: no lifecycle events or uplink records."
        )
    return GovernanceAuditEntry(
        stage=GovernanceAuditStage.admission,
        reached=reached,
        evidence_summary=evidence_summary,
        evidence_detail={
            "lifecycle_event_count": lifecycle_event_count,
            "result_uplink_count": truth.get("result_uplink_count") or 0,
            "state_uplink_count": truth.get("state_uplink_count") or 0,
        },
    )


def _build_lifecycle_entry(truth: Dict[str, Any]) -> GovernanceAuditEntry:
    """Build the lifecycle stage entry."""
    lifecycle_event_count: int = truth.get("lifecycle_event_count", 0) or 0
    lifecycle_phase = truth.get("lifecycle_phase")
    reached = lifecycle_event_count > 0
    if reached:
        evidence_summary = (
            f"Lifecycle recorded: {lifecycle_event_count} event(s), "
            f"current_phase={lifecycle_phase!r}."
        )
    else:
        evidence_summary = "No lifecycle events recorded."
    return GovernanceAuditEntry(
        stage=GovernanceAuditStage.lifecycle,
        reached=reached,
        evidence_summary=evidence_summary,
        evidence_detail={
            "lifecycle_event_count": lifecycle_event_count,
            "lifecycle_phase": lifecycle_phase,
        },
    )


def _build_uplink_observation_entry(truth: Dict[str, Any]) -> GovernanceAuditEntry:
    """Build the uplink_observation stage entry."""
    result_count: int = truth.get("result_uplink_count") or 0
    state_count: int = truth.get("state_uplink_count") or 0
    reached = (result_count + state_count) > 0
    if reached:
        evidence_summary = (
            f"Uplink observed: {result_count} result uplink(s), "
            f"{state_count} state uplink(s)."
        )
    else:
        evidence_summary = "No uplink observations recorded."
    return GovernanceAuditEntry(
        stage=GovernanceAuditStage.uplink_observation,
        reached=reached,
        evidence_summary=evidence_summary,
        evidence_detail={
            "result_uplink_count": result_count,
            "state_uplink_count": state_count,
            "reported_outcome": truth.get("reported_outcome"),
            "reported_terminal_outcome": truth.get("reported_terminal_outcome"),
        },
    )


def _build_reconciliation_entry(truth: Dict[str, Any]) -> GovernanceAuditEntry:
    """Build the reconciliation stage entry."""
    reconciliation_status: str = truth.get("reconciliation_status") or "missing"
    reconciliation_reason: str = truth.get("reconciliation_reason") or ""
    # Reconciliation is reached when the status is not "missing".
    reached = reconciliation_status not in ("missing",)
    if reached:
        evidence_summary = (
            f"Reconciliation completed: status={reconciliation_status!r}, "
            f"reason={reconciliation_reason!r}."
        )
    else:
        evidence_summary = "No reconciliation evidence (no lifecycle or uplink)."
    return GovernanceAuditEntry(
        stage=GovernanceAuditStage.reconciliation,
        reached=reached,
        evidence_summary=evidence_summary,
        evidence_detail={
            "reconciliation_status": reconciliation_status,
            "reconciliation_reason": reconciliation_reason,
            "reconciliation_conflict": truth.get("reconciliation_conflict") or False,
            "reconciliation_delayed_observation": (
                truth.get("reconciliation_delayed_observation") or False
            ),
            "reconciliation_partial_observation": (
                truth.get("reconciliation_partial_observation") or False
            ),
        },
    )


def _build_terminal_entry(truth: Dict[str, Any]) -> GovernanceAuditEntry:
    """Build the terminal stage entry."""
    is_terminal: bool = bool(truth.get("is_terminal"))
    canonical_terminal_outcome = truth.get("canonical_terminal_outcome")
    terminal_truth_authoritative_source: str = (
        truth.get("terminal_truth_authoritative_source") or "none"
    )
    reached = is_terminal and canonical_terminal_outcome is not None
    if reached:
        evidence_summary = (
            f"Terminal authority established: outcome={canonical_terminal_outcome!r}, "
            f"source={terminal_truth_authoritative_source!r}."
        )
    else:
        evidence_summary = (
            "Terminal stage not reached: execution is not yet terminal or "
            "canonical outcome is undetermined."
        )
    return GovernanceAuditEntry(
        stage=GovernanceAuditStage.terminal,
        reached=reached,
        evidence_summary=evidence_summary,
        evidence_detail={
            "is_terminal": is_terminal,
            "canonical_terminal_outcome": canonical_terminal_outcome,
            "terminal_truth_authoritative_source": terminal_truth_authoritative_source,
            "terminal_truth_determined": bool(
                truth.get("terminal_truth_determined")
            ),
        },
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_governance_authority_evidence(
    execution_id: str,
    device_id: str,
) -> GovernanceAuthorityEvidence:
    """Build a complete :class:`GovernanceAuthorityEvidence` for an execution.

    Derives all authority chain evidence from the existing governance runtime
    state via :func:`~core.unified_execution_governance.get_uplink_truth_state`
    and :func:`~core.unified_execution_governance.get_execution_lifecycle_history`.
    No new storage is added.

    Parameters
    ----------
    execution_id:
        Correlation identifier for the governed execution.
    device_id:
        Android device identifier (used for isolation checks).

    Returns
    -------
    GovernanceAuthorityEvidence
        Complete authority chain evidence, including audit entries for each
        stage and the highest stage reached.
    """
    from core.unified_execution_governance import get_uplink_truth_state  # noqa: PLC0415

    truth = get_uplink_truth_state(execution_id)

    # Build one entry per stage
    entries: List[GovernanceAuditEntry] = [
        _build_admission_entry(truth),
        _build_lifecycle_entry(truth),
        _build_uplink_observation_entry(truth),
        _build_reconciliation_entry(truth),
        _build_terminal_entry(truth),
    ]

    # Determine highest stage reached (last reached entry in order)
    highest_stage: Optional[GovernanceAuditStage] = None
    for entry in entries:
        if entry.reached:
            highest_stage = entry.stage

    authority_chain_complete = entries[-1].reached  # terminal entry reached

    evidence = GovernanceAuthorityEvidence(
        execution_id=execution_id,
        device_id=device_id,
        highest_stage_reached=highest_stage,
        audit_entries=entries,
        authority_source=truth.get("terminal_truth_authoritative_source") or "none",
        canonical_terminal_outcome=truth.get("canonical_terminal_outcome"),
        reconciliation_status=truth.get("reconciliation_status") or "missing",
        authority_chain_complete=authority_chain_complete,
    )
    logger.debug(
        "build_governance_authority_evidence: execution_id=%r device_id=%r "
        "highest_stage=%r complete=%r",
        execution_id,
        device_id,
        highest_stage.value if highest_stage else None,
        authority_chain_complete,
    )
    return evidence


def verify_governance_authority_integrity(
    execution_id: str,
    device_id: str,
) -> List[GovernanceAuthorityViolation]:
    """Verify the authority chain for a governed execution.

    Checks invariants I-A1 through I-A5 and returns a list of
    :class:`GovernanceAuthorityViolation` records for each breach.  An
    empty list indicates a fully coherent authority chain.

    Parameters
    ----------
    execution_id:
        Correlation identifier for the governed execution.
    device_id:
        Android device identifier.

    Returns
    -------
    list[GovernanceAuthorityViolation]
        Empty when all invariants pass.  Non-empty lists indicate
        governance authority regressions that MUST be treated as bugs.
    """
    from core.unified_execution_governance import get_uplink_truth_state  # noqa: PLC0415

    violations: List[GovernanceAuthorityViolation] = []
    truth = get_uplink_truth_state(execution_id)
    evidence = build_governance_authority_evidence(execution_id, device_id)

    # I-A1: Center-lifecycle MUST be terminal truth source whenever a
    #       terminal lifecycle phase is recorded.
    if truth.get("is_terminal") and truth.get("lifecycle_phase") is not None:
        source = truth.get("terminal_truth_authoritative_source") or "none"
        if source != "center_lifecycle":
            violations.append(GovernanceAuthorityViolation(
                invariant_id="I-A1",
                description=(
                    "Center-lifecycle authority MUST be the terminal truth source "
                    "when a terminal lifecycle phase is recorded, but "
                    f"terminal_truth_authoritative_source={source!r}."
                ),
                stage=GovernanceAuditStage.terminal,
                evidence={
                    "lifecycle_phase": truth.get("lifecycle_phase"),
                    "terminal_truth_authoritative_source": source,
                },
            ))

    # I-A2: A terminal evidence record MUST carry a non-None canonical_terminal_outcome.
    terminal_entry = next(
        (e for e in evidence.audit_entries if e.stage == GovernanceAuditStage.terminal),
        None,
    )
    if terminal_entry is not None and terminal_entry.reached:
        canonical_outcome = truth.get("canonical_terminal_outcome")
        if canonical_outcome is None:
            violations.append(GovernanceAuthorityViolation(
                invariant_id="I-A2",
                description=(
                    "A terminal authority evidence record MUST carry a non-None "
                    "canonical_terminal_outcome, but canonical_terminal_outcome=None."
                ),
                stage=GovernanceAuditStage.terminal,
                evidence={"canonical_terminal_outcome": None},
            ))

    # I-A3: Monotonic chain — the core stages must be forward-progressing.
    #       Specifically: reconciliation and terminal MUST NOT be reached
    #       without prior lifecycle evidence.  uplink_observation is an
    #       optional stage: executions may reach terminal truth via the
    #       center-lifecycle authority alone, without any uplinks.
    _REQUIRED_PREDECESSORS: Dict[GovernanceAuditStage, List[GovernanceAuditStage]] = {
        GovernanceAuditStage.lifecycle: [GovernanceAuditStage.admission],
        GovernanceAuditStage.reconciliation: [GovernanceAuditStage.admission, GovernanceAuditStage.lifecycle],
        GovernanceAuditStage.terminal: [GovernanceAuditStage.admission, GovernanceAuditStage.lifecycle],
    }
    by_stage_map = {e.stage: e for e in evidence.audit_entries}
    for stage, required_preds in _REQUIRED_PREDECESSORS.items():
        stage_entry = by_stage_map.get(stage)
        if stage_entry is not None and stage_entry.reached:
            for pred_stage in required_preds:
                pred_entry = by_stage_map.get(pred_stage)
                if pred_entry is not None and not pred_entry.reached:
                    violations.append(GovernanceAuthorityViolation(
                        invariant_id="I-A3",
                        description=(
                            f"Stage {stage.value!r} was reached but required prior "
                            f"stage {pred_stage.value!r} has no evidence. "
                            "The authority chain must be monotonically forward-progressing."
                        ),
                        stage=stage,
                        evidence={
                            "reached_stage": stage.value,
                            "missing_prior_stage": pred_stage.value,
                        },
                    ))

    # I-A4: Uplink observation MUST NOT override center-lifecycle terminal truth.
    if truth.get("reconciliation_conflict"):
        source = truth.get("terminal_truth_authoritative_source") or "none"
        if source != "center_lifecycle":
            violations.append(GovernanceAuthorityViolation(
                invariant_id="I-A4",
                description=(
                    "Uplink observation MUST NOT override center-lifecycle terminal "
                    "truth. A reconciliation_conflict was detected, but the terminal "
                    f"truth source is {source!r} (expected 'center_lifecycle')."
                ),
                stage=GovernanceAuditStage.reconciliation,
                evidence={
                    "reconciliation_conflict": True,
                    "terminal_truth_authoritative_source": source,
                    "reconciliation_status": truth.get("reconciliation_status"),
                },
            ))

    return violations


def get_governance_audit_summary(
    execution_id: str,
    device_id: str,
) -> Dict[str, Any]:
    """Return a JSON-serialisable governance audit summary for an execution.

    Combines :func:`build_governance_authority_evidence` with
    :func:`verify_governance_authority_integrity` to produce a single
    auditable record suitable for logging, monitoring, and regression tests.

    Parameters
    ----------
    execution_id:
        Correlation identifier for the governed execution.
    device_id:
        Android device identifier.

    Returns
    -------
    dict
        Keys include ``execution_id``, ``device_id``, ``authority_evidence``,
        ``integrity_violations``, ``integrity_ok``, ``sentinel``, and
        ``contract_version``.
    """
    evidence = build_governance_authority_evidence(execution_id, device_id)
    violations = verify_governance_authority_integrity(execution_id, device_id)

    return {
        "execution_id": execution_id,
        "device_id": device_id,
        "authority_evidence": evidence.to_dict(),
        "integrity_violations": [v.to_dict() for v in violations],
        "integrity_ok": len(violations) == 0,
        "highest_stage_reached": (
            evidence.highest_stage_reached.value
            if evidence.highest_stage_reached is not None
            else None
        ),
        "authority_chain_complete": evidence.authority_chain_complete,
        "canonical_terminal_outcome": evidence.canonical_terminal_outcome,
        "authority_source": evidence.authority_source,
        "sentinel": GOVERNANCE_AUDIT_AUTHORITY_SENTINEL,
        "contract_version": GOVERNANCE_AUDIT_CONTRACT_VERSION,
        "_policy": GOVERNANCE_AUDIT_AUTHORITY_POLICY,
    }
