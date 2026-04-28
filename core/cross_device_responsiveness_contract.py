#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/cross_device_responsiveness_contract.py
=============================================
PR-11 — Cross-Device / Remote Execution Responsiveness Contract.

Background
----------
The Galaxy V2 system supports cross-device and delegated-remote execution, but
until this module the system expressed only *capability existence* ("remote
execution is supported") rather than a formal *responsiveness contract* ("remote
execution is supported at a specific, verifiable responsiveness level").

This left a gap between "can run" and "can acceptably respond":

* Users and reviewers had no way to know whether to expect near-interactive,
  deferred, eventual, or degraded response from a remote participant.
* Truth / readiness / acceptance / governance surfaces did not treat
  responsiveness as a first-class operational dimension.
* There was no downgrade mechanism: systems with stale, partial, or absent
  delegated participants could optimistically report the same responsiveness as
  systems with healthy participants.

This module establishes the **formal responsiveness contract** for
cross-device / remote-execution paths in Galaxy V2 by:

1. Defining a **ResponsivenessLevel taxonomy** (five levels) that maps
   directly to observable runtime / participant conditions.
2. Defining a **ResponsivenessContract** dataclass that packages the
   classification together with the evidence used to derive it.
3. Providing **classify_responsiveness()** — the canonical classifier that:
   * Derives the correct level from participant readiness, health score,
     evidence availability, and execution domain.
   * Never optimistically upgrades responsiveness when participants are
     stale, partial, or missing.
   * Always downgrades when evidence is absent.
4. Exposing **governance/truth/acceptance integration** sentinels so that
   release gates, readiness evaluators, and acceptance pipelines can assert
   alignment with this contract.

Responsiveness Level Definitions
---------------------------------
+---------------------+----------------------------------------------------+
| Level               | Meaning                                            |
+=====================+====================================================+
| near_interactive    | Participant is fully ready, healthy (health ≥ 0.8),|
|                     | and evidence-backed.  Round-trip latency is        |
|                     | expected to be low enough for interactive use.     |
|                     | ONLY valid for single-device local execution or    |
|                     | cross-device execution with a fully-ready,         |
|                     | evidence-backed remote participant.                |
+---------------------+----------------------------------------------------+
| bounded_deferred    | Participant is present and at least degraded-ready,|
|                     | health ≥ 0.5, with sufficient evidence.  Execution |
|                     | will complete but latency is non-trivially higher  |
|                     | than interactive.  Bounded by a finite upper       |
|                     | deadline.                                          |
+---------------------+----------------------------------------------------+
| eventual            | Participant is partially ready or evidence is      |
|                     | incomplete.  Execution may complete but latency    |
|                     | is unbounded from the user's perspective.          |
|                     | Recovery / reconciliation in progress.             |
+---------------------+----------------------------------------------------+
| degraded            | Participant exists but is stale, health < 0.5, or  |
|                     | evidence is critically insufficient.  Execution   |
|                     | may produce incomplete or reduced-quality results. |
+---------------------+----------------------------------------------------+
| unavailable         | No participant, or participant health is zero / the|
|                     | participant is missing.  Remote execution cannot   |
|                     | be attempted at this time.                         |
+---------------------+----------------------------------------------------+

Downgrade rules (fail-conservative)
------------------------------------
1. A **missing** remote participant MUST produce ``unavailable``.
2. A **stale** participant (last_seen > staleness_threshold) MUST produce
   at most ``degraded``.
3. A **partial-ready** participant (health 0.5–0.8, evidence incomplete)
   MUST produce at most ``eventual``.
4. An **absent evidence** state (no readiness artifact) MUST NOT produce
   ``near_interactive`` or ``bounded_deferred``.
5. Single-device local execution without a cross-device path MAY produce
   ``near_interactive`` on healthy state, but is separately classified as
   ``LOCAL`` domain to distinguish it from remote-execution responsiveness.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────┐
    │  CROSS-DEVICE RESPONSIVENESS CONTRACT  (this module, PR-11)      │
    │                                                                  │
    │  Consumed by (import only — no mutations):                       │
    │    • system_final_acceptance_verdict  (responsiveness dimension) │
    │    • release_governance_taxonomy      (aligned taxonomy)         │
    │    • multi_device_runtime_harness     (participant readiness)    │
    │    • canonical_cross_repo_evidence_pipeline  (evidence gate)     │
    │                                                                  │
    │  Defines:                                                        │
    │    • ResponsivenessLevel    — 5-value canonical enum             │
    │    • ParticipantReadinessState — 5-value participant enum        │
    │    • ExecutionDomain        — LOCAL vs REMOTE classifier         │
    │    • ResponsivenessInput    — structured classifier input        │
    │    • ResponsivenessContract — output contract dataclass          │
    │                                                                  │
    │  Helpers:                                                        │
    │    • classify_responsiveness(input) → ResponsivenessContract     │
    │    • responsiveness_for_participant(...)                         │
    │      → ResponsivenessContract                                    │
    └──────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — does not modify any existing module.
2. **Fail-conservative** — missing / unknown state ALWAYS downgrades;
   never upgrades.
3. **No semantic upgrade** — evidence absence MUST produce at most
   ``eventual``, never ``near_interactive`` or ``bounded_deferred``.
4. **Domain-distinguishing** — local single-device classification is
   explicitly separated from remote/delegated classification so that
   "supports remote execution" cannot be silently equated with
   "near_interactive remote execution".
5. **Import-safe** — no heavy dependencies; falls back gracefully.

Public API
----------
Authority / policy sentinels::

    CROSS_DEVICE_RESPONSIVENESS_CONTRACT_AUTHORITY
    CROSS_DEVICE_RESPONSIVENESS_CONTRACT_PR11_SENTINEL
    RESPONSIVENESS_IS_FIRST_CLASS_OPERATIONAL_DIMENSION_POLICY
    MISSING_PARTICIPANT_MUST_NOT_CLAIM_NEAR_INTERACTIVE_POLICY
    STALE_PARTICIPANT_MUST_DOWNGRADE_POLICY
    EVIDENCE_ABSENCE_BLOCKS_NEAR_INTERACTIVE_POLICY
    LOCAL_VS_REMOTE_DOMAIN_MUST_BE_DISTINGUISHED_POLICY

Enumerations::

    ResponsivenessLevel
    ParticipantReadinessState
    ExecutionDomain

Data classes::

    ResponsivenessInput
    ResponsivenessContract

Functions::

    classify_responsiveness(inp) -> ResponsivenessContract
    responsiveness_for_participant(
        participant_readiness,
        health_score,
        evidence_available,
        is_stale,
        execution_domain,
        ...
    ) -> ResponsivenessContract
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.CrossDeviceResponsivenessContract")

__all__ = [
    # Authority sentinels
    "CROSS_DEVICE_RESPONSIVENESS_CONTRACT_AUTHORITY",
    "CROSS_DEVICE_RESPONSIVENESS_CONTRACT_PR11_SENTINEL",
    # Policy sentinels
    "RESPONSIVENESS_IS_FIRST_CLASS_OPERATIONAL_DIMENSION_POLICY",
    "MISSING_PARTICIPANT_MUST_NOT_CLAIM_NEAR_INTERACTIVE_POLICY",
    "STALE_PARTICIPANT_MUST_DOWNGRADE_POLICY",
    "EVIDENCE_ABSENCE_BLOCKS_NEAR_INTERACTIVE_POLICY",
    "LOCAL_VS_REMOTE_DOMAIN_MUST_BE_DISTINGUISHED_POLICY",
    "DEGRADED_MUST_NOT_BE_REPORTED_AS_BOUNDED_NEAR_REAL_TIME_POLICY",
    # Enumerations
    "ResponsivenessLevel",
    "ParticipantReadinessState",
    "ExecutionDomain",
    # Data classes
    "ResponsivenessInput",
    "ResponsivenessContract",
    # Functions
    "classify_responsiveness",
    "responsiveness_for_participant",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

CROSS_DEVICE_RESPONSIVENESS_CONTRACT_AUTHORITY: str = (
    "CROSS_DEVICE_RESPONSIVENESS_CONTRACT_AUTHORITY::"
    "core.cross_device_responsiveness_contract::PR11::"
    "cross-device-remote-execution-responsiveness-taxonomy::"
    "formal-responsiveness-contract-for-galaxy-v2-platform"
)
"""Sentinel: this module is the canonical authority for cross-device /
remote-execution responsiveness classification in Galaxy V2.

Import this sentinel to assert that a release gate, governance surface,
acceptance evaluator, or runtime truth layer is consuming a formal
responsiveness classification rather than an implicit capability flag."""

CROSS_DEVICE_RESPONSIVENESS_CONTRACT_PR11_SENTINEL: str = (
    "CROSS_DEVICE_RESPONSIVENESS_CONTRACT_PR11_SENTINEL::"
    "package=PR11::profile=cross-device-responsiveness-contract-v1::"
    "module=core.cross_device_responsiveness_contract"
)
"""Package sentinel for PR-11 responsiveness contract."""

RESPONSIVENESS_IS_FIRST_CLASS_OPERATIONAL_DIMENSION_POLICY: str = (
    "POLICY::RESPONSIVENESS_IS_FIRST_CLASS_OPERATIONAL_DIMENSION_V1: "
    "Cross-device / remote-execution responsiveness MUST be treated as a "
    "first-class operational dimension by truth surfaces, readiness gates, "
    "acceptance evaluators, and governance pipelines.  Surfaces MUST NOT "
    "conflate 'remote execution is supported' (capability existence) with "
    "'remote execution is near_interactive' (responsiveness level).  "
    "Every cross-device execution verdict MUST include a "
    "ResponsivenessContract that identifies the applicable level.  "
    "See: ResponsivenessLevel taxonomy in "
    "core.cross_device_responsiveness_contract (PR-11)."
)
"""Policy: responsiveness is a first-class operational dimension."""

MISSING_PARTICIPANT_MUST_NOT_CLAIM_NEAR_INTERACTIVE_POLICY: str = (
    "POLICY::MISSING_PARTICIPANT_MUST_NOT_CLAIM_NEAR_INTERACTIVE_V1: "
    "When a remote / delegated participant is absent, missing, or has never "
    "been observed, the responsiveness classification MUST be set to "
    "unavailable.  It is a policy violation to report near_interactive, "
    "bounded_deferred, or eventual when the participant is missing.  "
    "Absence of the remote participant is not an optimistic baseline; it is "
    "an evidence of non-availability.  "
    "See: ResponsivenessLevel.unavailable in "
    "core.cross_device_responsiveness_contract (PR-11)."
)
"""Policy: missing participants produce unavailable, not near_interactive."""

STALE_PARTICIPANT_MUST_DOWNGRADE_POLICY: str = (
    "POLICY::STALE_PARTICIPANT_MUST_DOWNGRADE_V1: "
    "When the last-seen timestamp of a remote / delegated participant "
    "exceeds the staleness threshold, the responsiveness level MUST be "
    "capped at degraded.  A stale participant cannot be treated as "
    "near_interactive or bounded_deferred even if its last-known health "
    "score was high.  Staleness implies an unknown current state, which "
    "MUST be treated conservatively.  "
    "See: is_stale handling in classify_responsiveness() (PR-11)."
)
"""Policy: stale participants must downgrade responsiveness."""

EVIDENCE_ABSENCE_BLOCKS_NEAR_INTERACTIVE_POLICY: str = (
    "POLICY::EVIDENCE_ABSENCE_BLOCKS_NEAR_INTERACTIVE_V1: "
    "The near_interactive and bounded_deferred responsiveness levels "
    "REQUIRE positive evidence of participant readiness (readiness "
    "artifact, health signal, or canonical lifecycle confirmation).  "
    "In the absence of such evidence, the classification MUST NOT "
    "produce near_interactive or bounded_deferred.  Evidence absence "
    "results in at most eventual.  Self-attestation ('the participant "
    "exists') is not sufficient evidence for near_interactive.  "
    "See: evidence_available flag in classify_responsiveness() (PR-11)."
)
"""Policy: evidence absence blocks near_interactive and bounded_deferred."""

LOCAL_VS_REMOTE_DOMAIN_MUST_BE_DISTINGUISHED_POLICY: str = (
    "POLICY::LOCAL_VS_REMOTE_DOMAIN_MUST_BE_DISTINGUISHED_V1: "
    "Single-device local execution and cross-device remote execution MUST "
    "be classified separately.  A local near_interactive verdict MUST NOT "
    "be used to imply cross-device near_interactive responsiveness.  "
    "ExecutionDomain.LOCAL and ExecutionDomain.REMOTE are distinct; "
    "consumers of ResponsivenessContract MUST check the domain before "
    "inferring latency expectations.  "
    "See: ExecutionDomain enum in "
    "core.cross_device_responsiveness_contract (PR-11)."
)
"""Policy: local and remote execution domains must be explicitly distinguished."""

DEGRADED_MUST_NOT_BE_REPORTED_AS_BOUNDED_NEAR_REAL_TIME_POLICY: str = (
    "POLICY::DEGRADED_MUST_NOT_BE_REPORTED_AS_BOUNDED_NEAR_REAL_TIME_V1: "
    "The degraded and eventual responsiveness levels MUST NOT be reported "
    "as bounded near-real-time by any governance, acceptance, or truth "
    "surface.  Only near_interactive and bounded_deferred qualify as "
    "'bounded near-real-time'.  A degraded or eventual classification "
    "indicates unbounded or reduced-quality execution and MUST be "
    "surfaced as such to operators and reviewers.  "
    "See: ResponsivenessLevel.degraded / eventual in "
    "core.cross_device_responsiveness_contract (PR-11)."
)
"""Policy: degraded and eventual must never be reported as bounded near-real-time."""


# ---------------------------------------------------------------------------
# ResponsivenessLevel
# ---------------------------------------------------------------------------


class ResponsivenessLevel(str, Enum):
    """Five-level responsiveness taxonomy for cross-device / remote execution.

    String values are stable identifiers safe for serialisation, logging,
    and API responses.

    Ordering (from best to worst):
      near_interactive > bounded_deferred > eventual > degraded > unavailable
    """

    near_interactive = "near_interactive"
    """Participant is fully ready, healthy (health ≥ 0.8), and evidence-backed.
    Round-trip latency is expected to support interactive use.

    Requirements:
    - ParticipantReadinessState.ready
    - health_score >= 0.8
    - evidence_available = True
    - is_stale = False
    - participant is not missing
    """

    bounded_deferred = "bounded_deferred"
    """Participant is present and at least degraded-ready, health ≥ 0.5,
    with sufficient evidence.  Execution will complete within a finite
    (though higher-than-interactive) deadline.

    Requirements:
    - ParticipantReadinessState.ready OR degraded
    - health_score >= 0.5
    - evidence_available = True
    - is_stale = False
    """

    eventual = "eventual"
    """Participant is partially ready or evidence is incomplete.  Execution
    may complete but latency is unbounded from the user's perspective.
    Recovery / reconciliation may be in progress.

    Requirements:
    - ParticipantReadinessState is NOT missing
    - Some evidence OR partial readiness exists
    """

    degraded = "degraded"
    """Participant exists but is stale, health < 0.5, or evidence is
    critically insufficient.  Execution may produce incomplete or
    reduced-quality results.  Must not be confused with bounded_deferred.

    Requirements:
    - Participant exists but is stale OR health < 0.5 OR partial readiness
      with no evidence
    """

    unavailable = "unavailable"
    """No participant, or participant health is zero, or participant is
    missing.  Remote execution cannot be attempted at this time.

    Requirements:
    - ParticipantReadinessState.missing
    - OR health_score = 0.0
    - OR participant_id is None and domain is REMOTE
    """


# Numeric rank for comparison (lower = worse)
_LEVEL_RANK: Dict[str, int] = {
    ResponsivenessLevel.unavailable.value: 0,
    ResponsivenessLevel.degraded.value: 1,
    ResponsivenessLevel.eventual.value: 2,
    ResponsivenessLevel.bounded_deferred.value: 3,
    ResponsivenessLevel.near_interactive.value: 4,
}


def _worse_or_equal(a: ResponsivenessLevel, b: ResponsivenessLevel) -> bool:
    """Return True if level *a* is worse than or equal to level *b*."""
    return _LEVEL_RANK[a.value] <= _LEVEL_RANK[b.value]


# ---------------------------------------------------------------------------
# ParticipantReadinessState
# ---------------------------------------------------------------------------


class ParticipantReadinessState(str, Enum):
    """Canonical five-value readiness state for a remote / delegated participant.

    These states align with the readiness signals emitted by
    :func:`~core.multi_device_runtime_harness.on_participant_readiness_changed`
    and consumed by the responsiveness classifier.
    """

    ready = "ready"
    """Participant has passed all readiness checks and is actively connected."""

    degraded = "degraded"
    """Participant is connected but operating below full capacity."""

    partial = "partial"
    """Participant is in an intermediate / transitional state (e.g. recovering,
    reconciling, or partially loaded)."""

    stale = "stale"
    """Participant has not been seen recently; its current state is unknown."""

    missing = "missing"
    """Participant has never been registered, or was lost and not recovered."""


# ---------------------------------------------------------------------------
# ExecutionDomain
# ---------------------------------------------------------------------------


class ExecutionDomain(str, Enum):
    """Distinguishes single-device local execution from cross-device remote
    execution for responsiveness classification purposes.

    A ``LOCAL`` near_interactive classification MUST NOT be used to imply
    cross-device near_interactive responsiveness — see
    :data:`LOCAL_VS_REMOTE_DOMAIN_MUST_BE_DISTINGUISHED_POLICY`.
    """

    LOCAL = "local"
    """Execution is confined to the local device.  No remote participant is
    involved in the execution path."""

    REMOTE = "remote"
    """Execution involves a remote / delegated participant.  Responsiveness
    is bounded by network latency and participant health."""


# ---------------------------------------------------------------------------
# ResponsivenessInput
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResponsivenessInput:
    """Structured input for the responsiveness classifier.

    All fields have safe defaults so that an absent signal does not silently
    produce an optimistic classification.

    Attributes
    ----------
    execution_domain:
        ``LOCAL`` for single-device execution; ``REMOTE`` for cross-device /
        delegated execution.  Defaults to ``REMOTE`` (conservative for
        ambiguous contexts).
    participant_id:
        Identifier of the remote / delegated participant, or ``None`` if
        no participant exists.
    participant_readiness:
        Current readiness state of the participant.  Defaults to
        ``ParticipantReadinessState.missing`` (conservative).
    health_score:
        Float in [0.0, 1.0] representing the participant's health.  Defaults
        to 0.0 (worst case).
    evidence_available:
        True only when a canonical readiness artifact (e.g.
        ``DeviceReadinessArtifact``, participant lifecycle confirmation, or
        real-device verification artifact) is present and non-stale.
        Defaults to False (conservative).
    is_stale:
        True when the participant's last-seen timestamp exceeds the staleness
        threshold.  Defaults to False (caller must set True explicitly when
        staleness is detected).
    task_id:
        Optional task identifier for traceability.
    trace_id:
        Optional distributed-trace identifier.
    extra_context:
        Optional dict of additional context signals (e.g. recovery phase,
        reconciliation state).  Not used in classification logic but included
        in the contract for auditability.
    """

    execution_domain: ExecutionDomain = ExecutionDomain.REMOTE
    participant_id: Optional[str] = None
    participant_readiness: ParticipantReadinessState = ParticipantReadinessState.missing
    health_score: float = 0.0
    evidence_available: bool = False
    is_stale: bool = False
    task_id: Optional[str] = None
    trace_id: Optional[str] = None
    extra_context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "execution_domain": self.execution_domain.value,
            "participant_id": self.participant_id,
            "participant_readiness": self.participant_readiness.value,
            "health_score": self.health_score,
            "evidence_available": self.evidence_available,
            "is_stale": self.is_stale,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "extra_context": dict(self.extra_context),
        }


# ---------------------------------------------------------------------------
# ResponsivenessContract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResponsivenessContract:
    """Formal responsiveness contract for a cross-device / remote execution.

    Produced by :func:`classify_responsiveness`.

    Attributes
    ----------
    level:
        The classified :class:`ResponsivenessLevel` for this execution.
    execution_domain:
        Whether this classification applies to local or remote execution.
    rationale:
        Human-readable explanation of why this level was assigned.  Always
        non-empty.
    downgrade_reasons:
        List of specific reasons that caused the level to be downgraded from
        an optimistic baseline.  Empty when no downgrade occurred.
    is_bounded_near_real_time:
        True only for ``near_interactive`` and ``bounded_deferred`` levels.
        MUST NOT be set for ``degraded`` or ``eventual``.
    participant_id:
        Identifier of the remote participant this contract applies to.
    evidence_present:
        Whether positive evidence was available during classification.
    classified_at:
        Unix timestamp (float) when this contract was produced.
    task_id:
        Optional task identifier for traceability.
    trace_id:
        Optional distributed-trace identifier.
    """

    level: ResponsivenessLevel
    execution_domain: ExecutionDomain
    rationale: str
    downgrade_reasons: List[str] = field(default_factory=list)
    is_bounded_near_real_time: bool = False
    participant_id: Optional[str] = None
    evidence_present: bool = False
    classified_at: float = field(default_factory=time.time)
    task_id: Optional[str] = None
    trace_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "level": self.level.value,
            "execution_domain": self.execution_domain.value,
            "rationale": self.rationale,
            "downgrade_reasons": list(self.downgrade_reasons),
            "is_bounded_near_real_time": self.is_bounded_near_real_time,
            "participant_id": self.participant_id,
            "evidence_present": self.evidence_present,
            "classified_at": self.classified_at,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
        }


# ---------------------------------------------------------------------------
# Core classifier
# ---------------------------------------------------------------------------

# Health thresholds — aligned with formation health semantics in
# core/device_formation/formation_rebalance_engine.py
_HEALTH_NEAR_INTERACTIVE_MIN: float = 0.8
_HEALTH_BOUNDED_DEFERRED_MIN: float = 0.5


def classify_responsiveness(inp: ResponsivenessInput) -> ResponsivenessContract:
    """Classify the responsiveness level for a cross-device / remote execution.

    This is the canonical entry point for responsiveness classification.
    It applies the fail-conservative downgrade rules defined in the module
    docstring and enforced by the policy sentinels.

    Parameters
    ----------
    inp:
        :class:`ResponsivenessInput` describing the participant and evidence
        state.

    Returns
    -------
    ResponsivenessContract
        Immutable contract recording the level, rationale, and any downgrade
        reasons.  Never raises; returns ``unavailable`` on any unexpected input.
    """
    try:
        return _classify_impl(inp)
    except Exception as exc:  # noqa: BLE001  # intentional: top-level safety wrapper; BaseException subclasses (KeyboardInterrupt, SystemExit) are NOT caught
        logger.warning(
            "classify_responsiveness: unexpected error during classification — %s; "
            "returning unavailable (fail-conservative)",
            exc,
        )
        return ResponsivenessContract(
            level=ResponsivenessLevel.unavailable,
            execution_domain=inp.execution_domain
            if isinstance(inp, ResponsivenessInput)
            else ExecutionDomain.REMOTE,
            rationale=(
                f"classification raised an unexpected error ({exc!r}); "
                "defaulting to unavailable (fail-conservative)"
            ),
            downgrade_reasons=[f"classifier_exception: {exc!r}"],
            is_bounded_near_real_time=False,
            participant_id=None,
            evidence_present=False,
            task_id=getattr(inp, "task_id", None),
            trace_id=getattr(inp, "trace_id", None),
        )


def _classify_impl(inp: ResponsivenessInput) -> ResponsivenessContract:
    """Internal classification implementation."""
    domain = inp.execution_domain
    readiness = inp.participant_readiness
    health = max(0.0, min(1.0, float(inp.health_score)))
    evidence = bool(inp.evidence_available)
    stale = bool(inp.is_stale)
    pid = inp.participant_id
    downgrade_reasons: List[str] = []

    # ------------------------------------------------------------------
    # LOCAL domain: single-device execution
    # ------------------------------------------------------------------
    if domain is ExecutionDomain.LOCAL:
        # For local execution, the participant is the local device itself.
        # We do not require a remote participant ID.
        if readiness is ParticipantReadinessState.missing or health == 0.0:
            downgrade_reasons.append("local_device_not_ready")
            return ResponsivenessContract(
                level=ResponsivenessLevel.unavailable,
                execution_domain=domain,
                rationale=(
                    "Local device is not ready (readiness=missing or health=0); "
                    "cannot execute."
                ),
                downgrade_reasons=downgrade_reasons,
                is_bounded_near_real_time=False,
                participant_id=pid,
                evidence_present=evidence,
                task_id=inp.task_id,
                trace_id=inp.trace_id,
            )

        if stale:
            downgrade_reasons.append("local_device_state_stale")
            # Stale local device → degraded (not unavailable, since it exists)
            return ResponsivenessContract(
                level=ResponsivenessLevel.degraded,
                execution_domain=domain,
                rationale=(
                    "Local device state is stale; downgraded to degraded.  "
                    "Refresh readiness signals to recover near_interactive."
                ),
                downgrade_reasons=downgrade_reasons,
                is_bounded_near_real_time=False,
                participant_id=pid,
                evidence_present=evidence,
                task_id=inp.task_id,
                trace_id=inp.trace_id,
            )

        if health >= _HEALTH_NEAR_INTERACTIVE_MIN and evidence:
            return ResponsivenessContract(
                level=ResponsivenessLevel.near_interactive,
                execution_domain=domain,
                rationale=(
                    f"Local single-device execution: health={health:.2f} ≥ "
                    f"{_HEALTH_NEAR_INTERACTIVE_MIN}, evidence present.  "
                    "near_interactive classified (LOCAL domain)."
                ),
                downgrade_reasons=[],
                is_bounded_near_real_time=True,
                participant_id=pid,
                evidence_present=evidence,
                task_id=inp.task_id,
                trace_id=inp.trace_id,
            )

        if health >= _HEALTH_BOUNDED_DEFERRED_MIN and evidence:
            downgrade_reasons.append(
                f"health={health:.2f} < {_HEALTH_NEAR_INTERACTIVE_MIN} threshold"
            )
            return ResponsivenessContract(
                level=ResponsivenessLevel.bounded_deferred,
                execution_domain=domain,
                rationale=(
                    f"Local device health={health:.2f} is below near_interactive "
                    f"threshold ({_HEALTH_NEAR_INTERACTIVE_MIN}) but above "
                    f"bounded_deferred threshold ({_HEALTH_BOUNDED_DEFERRED_MIN}).  "
                    "Classified as bounded_deferred (LOCAL domain)."
                ),
                downgrade_reasons=downgrade_reasons,
                is_bounded_near_real_time=True,
                participant_id=pid,
                evidence_present=evidence,
                task_id=inp.task_id,
                trace_id=inp.trace_id,
            )

        if not evidence:
            downgrade_reasons.append("evidence_absent_on_local_device")
        if health < _HEALTH_BOUNDED_DEFERRED_MIN:
            downgrade_reasons.append(
                f"health={health:.2f} < {_HEALTH_BOUNDED_DEFERRED_MIN} threshold"
            )
        return ResponsivenessContract(
            level=ResponsivenessLevel.eventual,
            execution_domain=domain,
            rationale=(
                "Local device has insufficient health or evidence for "
                "bounded classification; classified as eventual (LOCAL domain)."
            ),
            downgrade_reasons=downgrade_reasons,
            is_bounded_near_real_time=False,
            participant_id=pid,
            evidence_present=evidence,
            task_id=inp.task_id,
            trace_id=inp.trace_id,
        )

    # ------------------------------------------------------------------
    # REMOTE domain: cross-device / delegated execution
    # ------------------------------------------------------------------

    # Rule 1 (MISSING_PARTICIPANT_MUST_NOT_CLAIM_NEAR_INTERACTIVE_POLICY):
    # Missing participant → unavailable.
    if readiness is ParticipantReadinessState.missing or (pid is None and health == 0.0):
        downgrade_reasons.append("remote_participant_missing")
        return ResponsivenessContract(
            level=ResponsivenessLevel.unavailable,
            execution_domain=domain,
            rationale=(
                "Remote participant is missing or was never registered.  "
                "Cross-device execution is unavailable.  "
                "(MISSING_PARTICIPANT_MUST_NOT_CLAIM_NEAR_INTERACTIVE_POLICY)"
            ),
            downgrade_reasons=downgrade_reasons,
            is_bounded_near_real_time=False,
            participant_id=pid,
            evidence_present=evidence,
            task_id=inp.task_id,
            trace_id=inp.trace_id,
        )

    # Rule 2 (STALE_PARTICIPANT_MUST_DOWNGRADE_POLICY):
    # Stale participant → cap at degraded.
    if stale:
        downgrade_reasons.append("remote_participant_stale")
        return ResponsivenessContract(
            level=ResponsivenessLevel.degraded,
            execution_domain=domain,
            rationale=(
                "Remote participant state is stale; responsiveness capped at "
                "degraded.  A stale participant cannot claim near_interactive or "
                "bounded_deferred.  "
                "(STALE_PARTICIPANT_MUST_DOWNGRADE_POLICY)"
            ),
            downgrade_reasons=downgrade_reasons,
            is_bounded_near_real_time=False,
            participant_id=pid,
            evidence_present=evidence,
            task_id=inp.task_id,
            trace_id=inp.trace_id,
        )

    # Rule 3 (EVIDENCE_ABSENCE_BLOCKS_NEAR_INTERACTIVE_POLICY):
    # No evidence → cap at eventual.
    if not evidence:
        downgrade_reasons.append("evidence_absent_for_remote_participant")
        # Can still be eventual if participant exists and is not missing.
        if readiness is ParticipantReadinessState.partial:
            downgrade_reasons.append("participant_partial_ready")
        return ResponsivenessContract(
            level=ResponsivenessLevel.eventual,
            execution_domain=domain,
            rationale=(
                "No canonical readiness evidence available for remote participant.  "
                "Responsiveness capped at eventual.  "
                "near_interactive and bounded_deferred require positive evidence.  "
                "(EVIDENCE_ABSENCE_BLOCKS_NEAR_INTERACTIVE_POLICY)"
            ),
            downgrade_reasons=downgrade_reasons,
            is_bounded_near_real_time=False,
            participant_id=pid,
            evidence_present=False,
            task_id=inp.task_id,
            trace_id=inp.trace_id,
        )

    # Evidence is present beyond this point.
    # Apply health + readiness thresholds.

    # Degraded health (< bounded_deferred min) → degraded or eventual.
    if health < _HEALTH_BOUNDED_DEFERRED_MIN:
        downgrade_reasons.append(
            f"health={health:.2f} < {_HEALTH_BOUNDED_DEFERRED_MIN} threshold"
        )
        if readiness is ParticipantReadinessState.partial:
            downgrade_reasons.append("participant_partial_ready")
            return ResponsivenessContract(
                level=ResponsivenessLevel.eventual,
                execution_domain=domain,
                rationale=(
                    f"Remote participant health={health:.2f} is below "
                    f"bounded_deferred threshold and readiness is partial; "
                    "classified as eventual (REMOTE domain)."
                ),
                downgrade_reasons=downgrade_reasons,
                is_bounded_near_real_time=False,
                participant_id=pid,
                evidence_present=evidence,
                task_id=inp.task_id,
                trace_id=inp.trace_id,
            )
        return ResponsivenessContract(
            level=ResponsivenessLevel.degraded,
            execution_domain=domain,
            rationale=(
                f"Remote participant health={health:.2f} is below "
                f"bounded_deferred threshold ({_HEALTH_BOUNDED_DEFERRED_MIN}); "
                "classified as degraded (REMOTE domain).  "
                "(DEGRADED_MUST_NOT_BE_REPORTED_AS_BOUNDED_NEAR_REAL_TIME_POLICY)"
            ),
            downgrade_reasons=downgrade_reasons,
            is_bounded_near_real_time=False,
            participant_id=pid,
            evidence_present=evidence,
            task_id=inp.task_id,
            trace_id=inp.trace_id,
        )

    # Partial readiness → cap at eventual even with sufficient health.
    if readiness is ParticipantReadinessState.partial:
        downgrade_reasons.append("participant_partial_ready")
        return ResponsivenessContract(
            level=ResponsivenessLevel.eventual,
            execution_domain=domain,
            rationale=(
                f"Remote participant is partial-ready (health={health:.2f}); "
                "responsiveness capped at eventual.  "
                "Full readiness required for bounded classifications."
            ),
            downgrade_reasons=downgrade_reasons,
            is_bounded_near_real_time=False,
            participant_id=pid,
            evidence_present=evidence,
            task_id=inp.task_id,
            trace_id=inp.trace_id,
        )

    # Degraded readiness with sufficient health → bounded_deferred.
    if readiness is ParticipantReadinessState.degraded:
        if health >= _HEALTH_BOUNDED_DEFERRED_MIN:
            downgrade_reasons.append("participant_degraded_readiness")
            return ResponsivenessContract(
                level=ResponsivenessLevel.bounded_deferred,
                execution_domain=domain,
                rationale=(
                    f"Remote participant is degraded-ready (health={health:.2f} ≥ "
                    f"{_HEALTH_BOUNDED_DEFERRED_MIN}).  Classified as bounded_deferred "
                    "(REMOTE domain)."
                ),
                downgrade_reasons=downgrade_reasons,
                is_bounded_near_real_time=True,
                participant_id=pid,
                evidence_present=evidence,
                task_id=inp.task_id,
                trace_id=inp.trace_id,
            )

    # Ready readiness, high health → near_interactive (if health ≥ 0.8).
    if readiness is ParticipantReadinessState.ready:
        if health >= _HEALTH_NEAR_INTERACTIVE_MIN:
            return ResponsivenessContract(
                level=ResponsivenessLevel.near_interactive,
                execution_domain=domain,
                rationale=(
                    f"Remote participant is fully ready, health={health:.2f} ≥ "
                    f"{_HEALTH_NEAR_INTERACTIVE_MIN}, evidence present.  "
                    "Classified as near_interactive (REMOTE domain)."
                ),
                downgrade_reasons=[],
                is_bounded_near_real_time=True,
                participant_id=pid,
                evidence_present=evidence,
                task_id=inp.task_id,
                trace_id=inp.trace_id,
            )
        # Ready but health < 0.8 → bounded_deferred.
        downgrade_reasons.append(
            f"health={health:.2f} < {_HEALTH_NEAR_INTERACTIVE_MIN} threshold"
        )
        return ResponsivenessContract(
            level=ResponsivenessLevel.bounded_deferred,
            execution_domain=domain,
            rationale=(
                f"Remote participant is ready but health={health:.2f} is below "
                f"near_interactive threshold ({_HEALTH_NEAR_INTERACTIVE_MIN}).  "
                "Classified as bounded_deferred (REMOTE domain)."
            ),
            downgrade_reasons=downgrade_reasons,
            is_bounded_near_real_time=True,
            participant_id=pid,
            evidence_present=evidence,
            task_id=inp.task_id,
            trace_id=inp.trace_id,
        )

    # Fallback: cannot determine → eventual (conservative).
    downgrade_reasons.append("undetermined_readiness_fallback")
    return ResponsivenessContract(
        level=ResponsivenessLevel.eventual,
        execution_domain=domain,
        rationale=(
            "Could not determine a clear responsiveness level from the provided "
            "inputs; defaulting to eventual (fail-conservative fallback)."
        ),
        downgrade_reasons=downgrade_reasons,
        is_bounded_near_real_time=False,
        participant_id=pid,
        evidence_present=evidence,
        task_id=inp.task_id,
        trace_id=inp.trace_id,
    )


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------


def responsiveness_for_participant(
    participant_readiness: str,
    health_score: float,
    evidence_available: bool,
    is_stale: bool = False,
    execution_domain: str = "remote",
    participant_id: Optional[str] = None,
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> ResponsivenessContract:
    """Convenience wrapper for :func:`classify_responsiveness`.

    Accepts string values for enum parameters so callers do not need to
    import the enum classes directly.

    Parameters
    ----------
    participant_readiness:
        String value of :class:`ParticipantReadinessState` (e.g. ``"ready"``,
        ``"degraded"``, ``"stale"``, ``"partial"``, ``"missing"``).  Unknown
        values default to ``"missing"`` (fail-conservative).
    health_score:
        Float in [0.0, 1.0].
    evidence_available:
        Whether canonical readiness evidence is present.
    is_stale:
        Whether the participant's last-seen state is stale.
    execution_domain:
        ``"local"`` or ``"remote"`` (default ``"remote"``).
    participant_id:
        Optional participant identifier.
    task_id:
        Optional task identifier.
    trace_id:
        Optional trace identifier.

    Returns
    -------
    ResponsivenessContract
    """
    try:
        readiness_enum = ParticipantReadinessState(participant_readiness)
    except (ValueError, KeyError):
        logger.warning(
            "responsiveness_for_participant: unknown readiness value %r; "
            "defaulting to missing (fail-conservative)",
            participant_readiness,
        )
        readiness_enum = ParticipantReadinessState.missing

    try:
        domain_enum = ExecutionDomain(execution_domain)
    except (ValueError, KeyError):
        logger.warning(
            "responsiveness_for_participant: unknown domain value %r; "
            "defaulting to remote (conservative)",
            execution_domain,
        )
        domain_enum = ExecutionDomain.REMOTE

    inp = ResponsivenessInput(
        execution_domain=domain_enum,
        participant_id=participant_id,
        participant_readiness=readiness_enum,
        health_score=health_score,
        evidence_available=evidence_available,
        is_stale=is_stale,
        task_id=task_id,
        trace_id=trace_id,
    )
    return classify_responsiveness(inp)
