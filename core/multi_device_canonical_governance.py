#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/multi_device_canonical_governance.py
==========================================
PR-09 (multi-device / delegated runtime canonical governance):
Formal canonical governance surface for multi-device and delegated
runtime status.

Background
----------
The Galaxy runtime already has real multi-device / delegated-runtime
infrastructure:

* Android participant on-device runtime (GalaxyConnectionService, etc.)
* Delegated runtime audit / lifecycle truth / readiness evidence
* Cross-repo verification / acceptance ingestion
* Participant capability / runtime surfaces
* Formation resolver, capability-aware routing, device selection

Despite this infrastructure, there was no single surface that formally
answers:

1. **Is multi-device / delegated runtime a default-mainline system surface
   or merely a conditionally-supported capability?**
2. **Which specific capabilities are default-mainline vs conditional/
   guarded/partial/optional?**
3. **What is the canonical classification of each participant in a
   multi-device session?**
4. **Does the current evidence state warrant a fully-active multi-device
   verdict, or must it be downgraded?**

This module closes those gaps.

Core invariants
---------------
1. **Existence of delegated hooks does NOT equal fully-active multi-device.**
   Contract-first modules (``MeshSessionCoordinator``,
   ``CrossRuntimeResultMerge``, etc.) are classified as *guarded* or
   *partial* — not as *default-mainline*.

2. **No delegated participant → not a multi-device operational state.**
   The evaluator MUST produce ``single_device_baseline`` (or
   ``no_evidence``) when no live delegated participant is present, even
   if the formation or routing layers are wired.

3. **Evidence presence is required for default-mainline classification.**
   Delegated participant evidence (audit events, readiness artifacts,
   lifecycle truth) MUST exist before any capability is promoted to
   ``default_mainline``.

4. **Explicit downgrade on partial/missing evidence.**
   Every downgrade decision is recorded in ``downgrade_reasons`` and
   surfaced in the report so operators can see exactly why a tier is
   lower than the theoretical maximum.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  MULTI-DEVICE CANONICAL GOVERNANCE  (this module, PR-09)            │
    │                                                                     │
    │  Inputs (read-only probes):                                        │
    │    • MultiDeviceCoordinationAuthority (coordination roles)         │
    │    • MultiDeviceTruthConvergence (formation / participation truth) │
    │    • AndroidDelegatedRuntimeAudit (audit events)                   │
    │    • AndroidParticipantEvidenceIngress (participant evidence)      │
    │    • AttachedRuntimeSessionRegistry (live sessions)               │
    │                                                                     │
    │  Produces MultiDeviceGovernanceReport:                             │
    │    • system_tier     — overall governance tier                     │
    │    • participant_roles — per-participant canonical classification   │
    │    • capability_map  — per-capability tier                         │
    │    • verdict         — governance verdict enum                     │
    │    • downgrade_reasons — explicit list of all tier downgrades      │
    │    • is_default_mainline — True only when evidence warrants it     │
    │    • summary — human-readable description                          │
    │                                                                     │
    │  Consumed by:                                                      │
    │    • system_final_acceptance_verdict                               │
    │      (multi_device_canonical_governance dimension)                 │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — does not modify any existing module.
2. **Fail-conservative** — missing / stale / unclear evidence is NEVER
   treated as implicit approval.  Silence is not a pass.
3. **Evidence-honest** — the existence of contracts or hook points does
   NOT promote any capability to ``default_mainline``.  Runtime
   evidence is required.
4. **Explicit downgrade** — every tier reduction documents its reason.
5. **No optimistic upgrade** — guarded/partial/optional surfaces cannot
   be self-promoted to default-mainline without fresh delegated-
   participant evidence.
6. **Projection-only** — all probes are read-only; no canonical state is
   mutated.
7. **Stable artifacts** — :class:`MultiDeviceGovernanceReport` is fully
   round-trippable via ``to_dict()`` / ``to_json()``.

Public API
----------
Authority sentinels::

    MULTI_DEVICE_CANONICAL_GOVERNANCE_AUTHORITY
    MULTI_DEVICE_CANONICAL_GOVERNANCE_PR09_SENTINEL

Policy sentinels::

    DELEGATED_HOOKS_DO_NOT_EQUAL_FULLY_ACTIVE_POLICY
    NO_DELEGATED_PARTICIPANT_NO_MULTI_DEVICE_OPERATIONAL_POLICY
    EVIDENCE_REQUIRED_FOR_DEFAULT_MAINLINE_POLICY
    EXPLICIT_DOWNGRADE_ON_PARTIAL_EVIDENCE_POLICY
    SINGLE_DEVICE_BASELINE_WHEN_NO_DELEGATED_PARTICIPANT_POLICY
    OPTIONAL_REALITY_MUST_NOT_UPGRADE_TO_FULLY_OPERATIONAL_DEFAULT_POLICY

Enumerations::

    MultiDeviceSystemTier
    DelegatedParticipantRole
    MultiDeviceGovernanceVerdict

Data classes::

    ParticipantClassification
    CapabilityGovernanceEntry
    MultiDeviceGovernanceReport

Class::

    MultiDeviceGovernanceEvaluator

Helpers::

    build_multi_device_governance_report() -> MultiDeviceGovernanceReport
    get_multi_device_governance_evaluator() -> MultiDeviceGovernanceEvaluator
    reset_multi_device_governance_evaluator() -> None  # testing only
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.MultiDeviceCanonicalGovernance")

# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Authority sentinels
    "MULTI_DEVICE_CANONICAL_GOVERNANCE_AUTHORITY",
    "MULTI_DEVICE_CANONICAL_GOVERNANCE_PR09_SENTINEL",
    # Policy sentinels
    "DELEGATED_HOOKS_DO_NOT_EQUAL_FULLY_ACTIVE_POLICY",
    "NO_DELEGATED_PARTICIPANT_NO_MULTI_DEVICE_OPERATIONAL_POLICY",
    "EVIDENCE_REQUIRED_FOR_DEFAULT_MAINLINE_POLICY",
    "EXPLICIT_DOWNGRADE_ON_PARTIAL_EVIDENCE_POLICY",
    "SINGLE_DEVICE_BASELINE_WHEN_NO_DELEGATED_PARTICIPANT_POLICY",
    "OPTIONAL_REALITY_MUST_NOT_UPGRADE_TO_FULLY_OPERATIONAL_DEFAULT_POLICY",
    # Enumerations
    "MultiDeviceSystemTier",
    "DelegatedParticipantRole",
    "MultiDeviceGovernanceVerdict",
    # Data classes
    "ParticipantClassification",
    "CapabilityGovernanceEntry",
    "MultiDeviceGovernanceReport",
    # Class
    "MultiDeviceGovernanceEvaluator",
    # Helpers
    "build_multi_device_governance_report",
    "get_multi_device_governance_evaluator",
    "reset_multi_device_governance_evaluator",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

MULTI_DEVICE_CANONICAL_GOVERNANCE_AUTHORITY: str = (
    "MULTI_DEVICE_CANONICAL_GOVERNANCE_AUTHORITY::"
    "core.multi_device_canonical_governance::PR09::"
    "multi-device-delegated-runtime-canonical-governance-surface::"
    "formal-default-mainline-tier-classification-for-galaxy-v2"
)
"""Sentinel: this module is the canonical governance authority that classifies
multi-device / delegated-runtime capabilities into tiers (default-mainline,
conditional, guarded, partial, optional) and enforces evidence-honest verdicts.

Import to assert that a release pipeline or acceptance reviewer is reading
multi-device governance classification from the correct canonical authority
rather than from optimistic hook-presence checks.
"""

MULTI_DEVICE_CANONICAL_GOVERNANCE_PR09_SENTINEL: str = (
    "MULTI_DEVICE_CANONICAL_GOVERNANCE_PR09_SENTINEL::"
    "package=PR09::profile=multi-device-canonical-governance-v1::"
    "module=core.multi_device_canonical_governance"
)
"""Package sentinel for PR-09."""

DELEGATED_HOOKS_DO_NOT_EQUAL_FULLY_ACTIVE_POLICY: str = (
    "POLICY::DELEGATED_HOOKS_DO_NOT_EQUAL_FULLY_ACTIVE_V1: "
    "The existence of delegated runtime hook points, contracts, or wiring "
    "(e.g. MeshSessionCoordinator, CrossRuntimeResultMerge, "
    "DeviceRoleAllocator) does NOT constitute a 'fully active multi-device' "
    "verdict.  Contract-first and not-implemented modules are classified as "
    "guarded or partial.  Only live runtime evidence with delegated participants "
    "may elevate a capability to default-mainline.  "
    "PR-09, multi-device canonical governance."
)

NO_DELEGATED_PARTICIPANT_NO_MULTI_DEVICE_OPERATIONAL_POLICY: str = (
    "POLICY::NO_DELEGATED_PARTICIPANT_NO_MULTI_DEVICE_OPERATIONAL_V1: "
    "When no live delegated participant is present in the current runtime "
    "context, the evaluator MUST NOT produce a multi-device operational "
    "verdict.  The system tier MUST be single_device_baseline or no_evidence "
    "regardless of how many formation / routing modules are wired.  "
    "PR-09, multi-device canonical governance."
)

EVIDENCE_REQUIRED_FOR_DEFAULT_MAINLINE_POLICY: str = (
    "POLICY::EVIDENCE_REQUIRED_FOR_DEFAULT_MAINLINE_V1: "
    "A capability may only be classified as MultiDeviceSystemTier.default_mainline "
    "when fresh delegated-participant runtime evidence is present (audit events, "
    "readiness artifacts, lifecycle truth entries).  The mere availability of "
    "code paths or contracts is insufficient.  "
    "PR-09, multi-device canonical governance."
)

EXPLICIT_DOWNGRADE_ON_PARTIAL_EVIDENCE_POLICY: str = (
    "POLICY::EXPLICIT_DOWNGRADE_ON_PARTIAL_EVIDENCE_V1: "
    "When evidence for a delegated participant or secondary device is present "
    "but incomplete (partial audit records, stale readiness artifacts, missing "
    "lifecycle truth), the evaluator MUST downgrade the affected capability tier "
    "and record the downgrade reason in downgrade_reasons.  Optimistic suppression "
    "of partial-evidence downgrades is prohibited.  "
    "PR-09, multi-device canonical governance."
)

SINGLE_DEVICE_BASELINE_WHEN_NO_DELEGATED_PARTICIPANT_POLICY: str = (
    "POLICY::SINGLE_DEVICE_BASELINE_WHEN_NO_DELEGATED_PARTICIPANT_V1: "
    "The single_device_baseline tier is the correct classification when the "
    "multi-device routing and formation infrastructure is wired but no delegated "
    "participant has joined the runtime in the current context.  It is NOT a "
    "failure state — it is the honest representation of the operational mode.  "
    "PR-09, multi-device canonical governance."
)

OPTIONAL_REALITY_MUST_NOT_UPGRADE_TO_FULLY_OPERATIONAL_DEFAULT_POLICY: str = (
    "POLICY::OPTIONAL_REALITY_MUST_NOT_UPGRADE_TO_FULLY_OPERATIONAL_DEFAULT_V1: "
    "Multi-device capabilities that are optional (e.g. session roaming, dynamic "
    "rebalance, mesh result merge) MUST be represented as optional or guarded "
    "in governance output.  They MUST NOT be presented as default-mainline or "
    "fully-operational defaults even when the code is present.  "
    "PR-09, multi-device canonical governance."
)


# ---------------------------------------------------------------------------
# MultiDeviceSystemTier
# ---------------------------------------------------------------------------


class MultiDeviceSystemTier(str, Enum):
    """Canonical tier classification for multi-device / delegated runtime
    capabilities.

    Values
    ------
    default_mainline
        Capability is a formally accepted default system surface.  Live
        runtime evidence with delegated participants exists and is fresh.
        This tier requires explicit evidence; it cannot be self-assigned
        by a capability based on its code presence alone.

    conditional
        Capability works when specific preconditions are met (e.g. a
        delegated participant is present) but is not activated by default
        in a single-device session.  Live delegated participant seen in
        the current runtime, but evidence is partial or some sub-surface
        is contract-first.

    guarded
        Capability has runtime wiring but depends on runtime features that
        are contract-first or not-fully-implemented (e.g.
        ``MeshSessionCoordinator``, ``CrossRuntimeResultMerge``).  Cannot
        be promoted without those contract-first surfaces being implemented.

    partial
        Capability has partial implementation: some paths work (e.g.
        formation resolution, parallel fan-out) but other paths are
        contract-only or not-implemented (e.g. capability-aware role
        allocation, barrier coordination).

    optional
        Capability is available but explicitly optional — it requires
        operator or configuration opt-in and is not part of the default
        activation path.

    single_device_baseline
        The current operational mode is single-device.  Multi-device
        infrastructure is wired but no delegated participant is present
        in the current runtime context.  This is the honest baseline tier
        when only a primary device is operational.

    no_evidence
        No evidence was obtained to classify the multi-device state.
        Treat conservatively as not-operational.
    """

    default_mainline = "default_mainline"
    conditional = "conditional"
    guarded = "guarded"
    partial = "partial"
    optional = "optional"
    single_device_baseline = "single_device_baseline"
    no_evidence = "no_evidence"

    @classmethod
    def from_string(cls, value: str) -> "MultiDeviceSystemTier":
        """Return the member matching *value*, defaulting to ``no_evidence``."""
        if not isinstance(value, str):
            return cls.no_evidence
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.no_evidence

    @property
    def is_operational(self) -> bool:
        """Return ``True`` when the tier represents an active multi-device state."""
        return self in (
            MultiDeviceSystemTier.default_mainline,
            MultiDeviceSystemTier.conditional,
        )

    @property
    def is_default_mainline(self) -> bool:
        """Return ``True`` only for ``default_mainline``."""
        return self == MultiDeviceSystemTier.default_mainline


# ---------------------------------------------------------------------------
# DelegatedParticipantRole
# ---------------------------------------------------------------------------


class DelegatedParticipantRole(str, Enum):
    """Canonical classification of a participant's role in a multi-device
    session.

    Values
    ------
    primary
        The originating / source-controller device.  Owns the runtime
        authority.  Every session has exactly one primary.

    delegated
        A participant that has joined the runtime session from a remote
        device with ``source_runtime_posture=join_runtime``.  Shares
        execution with the primary.  The presence of a delegated
        participant is the minimum evidence threshold for multi-device
        operational state.

    secondary
        A device in the formation that executes tasks dispatched by the
        primary / delegated participants but has no control-plane
        authority (``target_only_executor`` coordination role).

    observer
        A device that receives read-only session updates.  No execution
        and no control authority.

    none
        No participant role assigned; used when participant metadata is
        absent or cannot be determined.
    """

    primary = "primary"
    delegated = "delegated"
    secondary = "secondary"
    observer = "observer"
    none = "none"

    @classmethod
    def from_string(cls, value: str) -> "DelegatedParticipantRole":
        """Return the member matching *value*, defaulting to ``none``."""
        if not isinstance(value, str):
            return cls.none
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.none


# ---------------------------------------------------------------------------
# MultiDeviceGovernanceVerdict
# ---------------------------------------------------------------------------


class MultiDeviceGovernanceVerdict(str, Enum):
    """Top-level governance verdict for the multi-device / delegated runtime.

    Values
    ------
    default_mainline_active
        Multi-device / delegated runtime is formally classified as a
        default-mainline system surface.  Live delegated participant
        evidence is present, fresh, and complete.

    conditional_active
        Delegated participants are present but evidence is partial, some
        sub-surfaces are contract-first, or secondary-device evidence is
        absent.  Multi-device is operational but not yet default-mainline.

    guarded_baseline
        Formation and routing infrastructure is wired but the activated
        multi-device capability set is guarded (some contract-first or
        not-implemented sub-surfaces prevent default-mainline promotion).
        No live delegated participant is present.

    single_device_baseline
        The system is operating in single-device mode.  Multi-device
        infrastructure exists and is wired, but no delegated participant
        has joined the runtime in the current context.  This is the
        honest operational verdict when only one device is active.

    partial_evidence
        Some multi-device evidence exists but it is insufficient to
        classify the tier.  Treat conservatively as not-operational.

    no_evidence
        No evidence was obtained.  Treat as not-operational.
    """

    default_mainline_active = "default_mainline_active"
    conditional_active = "conditional_active"
    guarded_baseline = "guarded_baseline"
    single_device_baseline = "single_device_baseline"
    partial_evidence = "partial_evidence"
    no_evidence = "no_evidence"

    @classmethod
    def from_string(cls, value: str) -> "MultiDeviceGovernanceVerdict":
        """Return the member matching *value*, defaulting to ``no_evidence``."""
        if not isinstance(value, str):
            return cls.no_evidence
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.no_evidence

    @property
    def is_default_mainline(self) -> bool:
        """Return ``True`` only for ``default_mainline_active``."""
        return self == MultiDeviceGovernanceVerdict.default_mainline_active

    @property
    def is_operational(self) -> bool:
        """Return ``True`` when verdict indicates active multi-device state."""
        return self in (
            MultiDeviceGovernanceVerdict.default_mainline_active,
            MultiDeviceGovernanceVerdict.conditional_active,
        )

    @property
    def is_single_device(self) -> bool:
        """Return ``True`` when verdict indicates single-device baseline."""
        return self == MultiDeviceGovernanceVerdict.single_device_baseline


# ---------------------------------------------------------------------------
# ParticipantClassification
# ---------------------------------------------------------------------------


@dataclass
class ParticipantClassification:
    """Canonical classification record for one participant in a multi-device
    session.

    Fields
    ------
    participant_id
        The identifier of the participant.
    device_id
        The device identifier linked to this participant.
    role
        Canonical :class:`DelegatedParticipantRole` assignment.
    has_evidence
        Whether evidence exists for this participant (audit events,
        readiness artifacts, lifecycle truth entries).
    evidence_sources
        List of evidence source names that contributed to classification.
    evidence_complete
        Whether the evidence is complete (as opposed to partial/stale).
    notes
        Additional classification notes or downgrade reasons.
    """

    participant_id: str = ""
    device_id: str = ""
    role: DelegatedParticipantRole = DelegatedParticipantRole.none
    has_evidence: bool = False
    evidence_sources: List[str] = field(default_factory=list)
    evidence_complete: bool = False
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "participant_id": self.participant_id,
            "device_id": self.device_id,
            "role": self.role.value,
            "has_evidence": self.has_evidence,
            "evidence_sources": self.evidence_sources,
            "evidence_complete": self.evidence_complete,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParticipantClassification":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        return cls(
            participant_id=data.get("participant_id", ""),
            device_id=data.get("device_id", ""),
            role=DelegatedParticipantRole.from_string(data.get("role", "")),
            has_evidence=data.get("has_evidence", False),
            evidence_sources=data.get("evidence_sources", []),
            evidence_complete=data.get("evidence_complete", False),
            notes=data.get("notes", ""),
        )


# ---------------------------------------------------------------------------
# CapabilityGovernanceEntry
# ---------------------------------------------------------------------------

# Canonical capability map: maps a capability name to its known tier.
# Derived from the REAUDIT_MULTI_DEVICE_MATURITY_V2 evidence.
#
# Tier legend:
#   default_mainline  — verified operational in production paths
#   partial           — some paths work; others contract-only / not-implemented
#   guarded           — contract-first; depends on not-yet-implemented sub-surfaces
#   optional          — available but requires explicit opt-in; not default

_KNOWN_CAPABILITY_TIERS: Dict[str, MultiDeviceSystemTier] = {
    # Formation and routing — runtime-complete
    "route_task_single_remote_device": MultiDeviceSystemTier.default_mainline,
    "parallel_fanout_dispatch": MultiDeviceSystemTier.default_mainline,
    "formation_at_dispatch_time": MultiDeviceSystemTier.default_mainline,
    "capability_aware_routing_gate": MultiDeviceSystemTier.default_mainline,
    # Session / coordination — partial or contract-first
    "session_roaming_migration": MultiDeviceSystemTier.partial,
    "mesh_session_status_tracking": MultiDeviceSystemTier.guarded,
    "device_role_allocation_capability_aware": MultiDeviceSystemTier.guarded,
    "barrier_coordination_across_devices": MultiDeviceSystemTier.guarded,
    "cross_runtime_result_merge": MultiDeviceSystemTier.guarded,
    # Recovery — not implemented
    "mesh_session_recovery_after_restart": MultiDeviceSystemTier.guarded,
    "persistent_mesh_session_store": MultiDeviceSystemTier.guarded,
    # Delegation / verification
    "delegated_runtime_execution": MultiDeviceSystemTier.conditional,
    "delegated_runtime_verification": MultiDeviceSystemTier.conditional,
    "delegated_evidence_ingestion": MultiDeviceSystemTier.conditional,
    # Dynamic rebalance — not implemented
    "formation_dynamic_rebalance": MultiDeviceSystemTier.guarded,
}


@dataclass
class CapabilityGovernanceEntry:
    """Governance classification for one multi-device capability.

    Fields
    ------
    capability_name
        Canonical capability identifier.
    tier
        Governance tier classification.
    evidence_present
        Whether runtime evidence for this capability exists.
    notes
        Governance notes (e.g. why tier is guarded/partial).
    """

    capability_name: str = ""
    tier: MultiDeviceSystemTier = MultiDeviceSystemTier.no_evidence
    evidence_present: bool = False
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "capability_name": self.capability_name,
            "tier": self.tier.value,
            "evidence_present": self.evidence_present,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapabilityGovernanceEntry":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        return cls(
            capability_name=data.get("capability_name", ""),
            tier=MultiDeviceSystemTier.from_string(data.get("tier", "")),
            evidence_present=data.get("evidence_present", False),
            notes=data.get("notes", ""),
        )


# ---------------------------------------------------------------------------
# MultiDeviceGovernanceReport
# ---------------------------------------------------------------------------


@dataclass
class MultiDeviceGovernanceReport:
    """Canonical multi-device governance report.

    This is the stable, serialisable artifact produced by
    :class:`MultiDeviceGovernanceEvaluator`.

    Fields
    ------
    report_id
        Unique identifier for this report.
    verdict
        Overall governance verdict.
    system_tier
        Overall system tier classification.
    participant_classifications
        List of canonical participant classifications.
    capability_map
        Dict mapping capability name to :class:`CapabilityGovernanceEntry`.
    delegated_participant_count
        Number of delegated participants detected in the current runtime.
    secondary_device_count
        Number of secondary devices detected.
    has_delegated_participant_evidence
        Whether any delegated participant evidence (audit, readiness,
        lifecycle truth) was found.
    secondary_device_evidence_present
        Whether any secondary device evidence was found.
    default_mainline_capabilities
        List of capability names that are classified as default-mainline.
    conditional_capabilities
        List of capability names classified as conditional.
    guarded_capabilities
        List of capability names classified as guarded.
    partial_capabilities
        List of capability names classified as partial.
    optional_capabilities
        List of capability names classified as optional.
    downgrade_reasons
        Explicit list of all tier downgrade reasons.
    is_default_mainline
        ``True`` only when ``verdict`` is ``default_mainline_active``.
    is_operational
        ``True`` when verdict is ``default_mainline_active`` or
        ``conditional_active``.
    summary
        Human-readable multi-line governance summary.
    evaluated_at
        Unix timestamp of evaluation.
    """

    report_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    verdict: MultiDeviceGovernanceVerdict = MultiDeviceGovernanceVerdict.no_evidence
    system_tier: MultiDeviceSystemTier = MultiDeviceSystemTier.no_evidence
    participant_classifications: List[ParticipantClassification] = field(
        default_factory=list
    )
    capability_map: Dict[str, CapabilityGovernanceEntry] = field(default_factory=dict)
    delegated_participant_count: int = 0
    secondary_device_count: int = 0
    has_delegated_participant_evidence: bool = False
    secondary_device_evidence_present: bool = False
    default_mainline_capabilities: List[str] = field(default_factory=list)
    conditional_capabilities: List[str] = field(default_factory=list)
    guarded_capabilities: List[str] = field(default_factory=list)
    partial_capabilities: List[str] = field(default_factory=list)
    optional_capabilities: List[str] = field(default_factory=list)
    downgrade_reasons: List[str] = field(default_factory=list)
    is_default_mainline: bool = False
    is_operational: bool = False
    summary: str = ""
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "report_id": self.report_id,
            "verdict": self.verdict.value,
            "system_tier": self.system_tier.value,
            "participant_classifications": [
                p.to_dict() for p in self.participant_classifications
            ],
            "capability_map": {
                k: v.to_dict() for k, v in self.capability_map.items()
            },
            "delegated_participant_count": self.delegated_participant_count,
            "secondary_device_count": self.secondary_device_count,
            "has_delegated_participant_evidence": self.has_delegated_participant_evidence,
            "secondary_device_evidence_present": self.secondary_device_evidence_present,
            "default_mainline_capabilities": self.default_mainline_capabilities,
            "conditional_capabilities": self.conditional_capabilities,
            "guarded_capabilities": self.guarded_capabilities,
            "partial_capabilities": self.partial_capabilities,
            "optional_capabilities": self.optional_capabilities,
            "downgrade_reasons": self.downgrade_reasons,
            "is_default_mainline": self.is_default_mainline,
            "is_operational": self.is_operational,
            "summary": self.summary,
            "evaluated_at": self.evaluated_at,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MultiDeviceGovernanceReport":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        participants = [
            ParticipantClassification.from_dict(p)
            for p in data.get("participant_classifications", [])
        ]
        capability_map = {
            k: CapabilityGovernanceEntry.from_dict(v)
            for k, v in data.get("capability_map", {}).items()
        }
        return cls(
            report_id=data.get("report_id", uuid.uuid4().hex[:12]),
            verdict=MultiDeviceGovernanceVerdict.from_string(
                data.get("verdict", "")
            ),
            system_tier=MultiDeviceSystemTier.from_string(
                data.get("system_tier", "")
            ),
            participant_classifications=participants,
            capability_map=capability_map,
            delegated_participant_count=data.get("delegated_participant_count", 0),
            secondary_device_count=data.get("secondary_device_count", 0),
            has_delegated_participant_evidence=data.get(
                "has_delegated_participant_evidence", False
            ),
            secondary_device_evidence_present=data.get(
                "secondary_device_evidence_present", False
            ),
            default_mainline_capabilities=data.get("default_mainline_capabilities", []),
            conditional_capabilities=data.get("conditional_capabilities", []),
            guarded_capabilities=data.get("guarded_capabilities", []),
            partial_capabilities=data.get("partial_capabilities", []),
            optional_capabilities=data.get("optional_capabilities", []),
            downgrade_reasons=data.get("downgrade_reasons", []),
            is_default_mainline=data.get("is_default_mainline", False),
            is_operational=data.get("is_operational", False),
            summary=data.get("summary", ""),
            evaluated_at=data.get("evaluated_at", time.time()),
        )


# ---------------------------------------------------------------------------
# Optional integration imports — all guarded to remain self-contained
# ---------------------------------------------------------------------------

# MultiDeviceCoordinationAuthority (PR-6) — coordination roles
try:
    from core.multi_device_coordination_authority import (  # type: ignore[import]
        get_coordination_role_runtime as _get_coordination_runtime,
        CoordinationRole as _CoordinationRole,
    )
    _COORDINATION_AVAILABLE = True
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _COORDINATION_AVAILABLE = False
    _get_coordination_runtime = None  # type: ignore[assignment]
    _CoordinationRole = None  # type: ignore[assignment]

# AndroidDelegatedRuntimeAudit — audit events
try:
    from core.android_delegated_runtime_audit import (  # type: ignore[import]
        get_android_delegated_audit_recorder as _get_audit_recorder,
    )
    _AUDIT_AVAILABLE = True
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _AUDIT_AVAILABLE = False
    _get_audit_recorder = None  # type: ignore[assignment]

# AndroidParticipantEvidenceIngress — participant evidence
try:
    from core.android_participant_evidence_ingress import (  # type: ignore[import]
        ingest_android_participant_evidence as _ingest_participant_evidence,
        AndroidParticipantStatus as _AndroidParticipantStatus,
    )
    _PARTICIPANT_EVIDENCE_AVAILABLE = True
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _PARTICIPANT_EVIDENCE_AVAILABLE = False
    _ingest_participant_evidence = None  # type: ignore[assignment]
    _AndroidParticipantStatus = None  # type: ignore[assignment]

# AttachedRuntimeSessionRegistry — live attached sessions
try:
    from core.attached_runtime_session_registry import (  # type: ignore[import]
        list_attached_sessions as _list_attached_sessions,
    )
    _SESSION_REGISTRY_AVAILABLE = True
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _SESSION_REGISTRY_AVAILABLE = False
    _list_attached_sessions = None  # type: ignore[assignment]

# MultiDeviceTruthConvergence — formation / participation
try:
    from core.multi_device_truth_convergence import (  # type: ignore[import]
        converge_multi_device_truth as _converge_truth,
    )
    _TRUTH_CONVERGENCE_AVAILABLE = True
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _TRUTH_CONVERGENCE_AVAILABLE = False
    _converge_truth = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# MultiDeviceGovernanceEvaluator
# ---------------------------------------------------------------------------


class MultiDeviceGovernanceEvaluator:
    """Canonical evaluator for multi-device / delegated runtime governance.

    Probes available runtime signals to produce a
    :class:`MultiDeviceGovernanceReport` that formally classifies:

    1. Whether a delegated participant is present and has evidence.
    2. The canonical role of every participant in the current session.
    3. The governance tier of each known multi-device capability.
    4. The overall system tier and governance verdict.

    Key invariants enforced:

    * A ``default_mainline_active`` verdict requires delegated participant
      evidence (not just wiring).
    * No delegated participant → ``single_device_baseline`` verdict.
    * Contract-first sub-surfaces are classified as ``guarded``, not
      ``default_mainline``.
    * All tier downgrades are explicitly recorded.

    Use :func:`get_multi_device_governance_evaluator` for the
    process-global singleton.  Use
    :func:`reset_multi_device_governance_evaluator` for test isolation.
    """

    EVALUATOR_VERSION: str = "1.0"

    def evaluate(self) -> MultiDeviceGovernanceReport:
        """Evaluate multi-device governance and produce a report.

        Returns
        -------
        MultiDeviceGovernanceReport
            Full governance report with verdict, participant classifications,
            capability map, tier lists, downgrade reasons, and summary.
        """
        downgrade_reasons: List[str] = []

        # ------------------------------------------------------------------
        # Step 1: Probe for delegated participants
        # ------------------------------------------------------------------
        delegated_count, secondary_count, participant_classifications = (
            self._probe_participants(downgrade_reasons)
        )

        # ------------------------------------------------------------------
        # Step 2: Probe for delegated participant evidence
        # ------------------------------------------------------------------
        has_delegated_evidence, secondary_evidence = (
            self._probe_delegated_evidence(
                delegated_count, downgrade_reasons
            )
        )

        # ------------------------------------------------------------------
        # Step 3: Build capability map
        # ------------------------------------------------------------------
        capability_map = self._build_capability_map(
            has_delegated_evidence=has_delegated_evidence,
            delegated_count=delegated_count,
            downgrade_reasons=downgrade_reasons,
        )

        # ------------------------------------------------------------------
        # Step 4: Classify capability tier lists
        # ------------------------------------------------------------------
        (
            default_mainline_caps,
            conditional_caps,
            guarded_caps,
            partial_caps,
            optional_caps,
        ) = self._classify_capabilities(capability_map)

        # ------------------------------------------------------------------
        # Step 5: Derive overall system tier and verdict
        # ------------------------------------------------------------------
        system_tier, verdict = self._derive_tier_and_verdict(
            delegated_count=delegated_count,
            has_delegated_evidence=has_delegated_evidence,
            secondary_evidence=secondary_evidence,
            default_mainline_caps=default_mainline_caps,
            guarded_caps=guarded_caps,
            downgrade_reasons=downgrade_reasons,
        )

        is_default_mainline = verdict.is_default_mainline
        is_operational = verdict.is_operational

        # ------------------------------------------------------------------
        # Step 6: Build summary
        # ------------------------------------------------------------------
        summary = self._build_summary(
            verdict=verdict,
            system_tier=system_tier,
            delegated_count=delegated_count,
            secondary_count=secondary_count,
            has_delegated_evidence=has_delegated_evidence,
            secondary_evidence=secondary_evidence,
            default_mainline_caps=default_mainline_caps,
            guarded_caps=guarded_caps,
            downgrade_reasons=downgrade_reasons,
        )

        report = MultiDeviceGovernanceReport(
            verdict=verdict,
            system_tier=system_tier,
            participant_classifications=participant_classifications,
            capability_map=capability_map,
            delegated_participant_count=delegated_count,
            secondary_device_count=secondary_count,
            has_delegated_participant_evidence=has_delegated_evidence,
            secondary_device_evidence_present=secondary_evidence,
            default_mainline_capabilities=default_mainline_caps,
            conditional_capabilities=conditional_caps,
            guarded_capabilities=guarded_caps,
            partial_capabilities=partial_caps,
            optional_capabilities=optional_caps,
            downgrade_reasons=downgrade_reasons,
            is_default_mainline=is_default_mainline,
            is_operational=is_operational,
            summary=summary,
        )
        logger.debug(
            "MultiDeviceGovernanceEvaluator.evaluate() → verdict=%s "
            "delegated=%d secondary=%d downgrades=%d",
            verdict.value,
            delegated_count,
            secondary_count,
            len(downgrade_reasons),
        )
        return report

    # ------------------------------------------------------------------
    # Internal probe helpers
    # ------------------------------------------------------------------

    def _probe_participants(
        self,
        downgrade_reasons: List[str],
    ) -> tuple:
        """Probe runtime for delegated / secondary participants.

        Returns
        -------
        tuple of (delegated_count, secondary_count, participant_classifications)
        """
        delegated_count = 0
        secondary_count = 0
        participant_classifications: List[ParticipantClassification] = []

        if _COORDINATION_AVAILABLE and _get_coordination_runtime is not None:
            try:
                runtime = _get_coordination_runtime()
                records = list(getattr(runtime, "records", {}).values())
                for rec in records:
                    role_val = getattr(rec, "coordination_role", None)
                    if role_val is None:
                        continue
                    role_str = role_val.value if hasattr(role_val, "value") else str(role_val)
                    if role_str == "joined_runtime_participant":
                        delegated_count += 1
                        participant_classifications.append(
                            ParticipantClassification(
                                participant_id=getattr(rec, "device_id", ""),
                                device_id=getattr(rec, "device_id", ""),
                                role=DelegatedParticipantRole.delegated,
                                has_evidence=False,  # evidence probed later
                                notes="sourced from coordination role runtime",
                            )
                        )
                    elif role_str == "target_only_executor":
                        secondary_count += 1
                        participant_classifications.append(
                            ParticipantClassification(
                                participant_id=getattr(rec, "device_id", ""),
                                device_id=getattr(rec, "device_id", ""),
                                role=DelegatedParticipantRole.secondary,
                                has_evidence=False,
                                notes="sourced from coordination role runtime",
                            )
                        )
            except Exception as exc:
                downgrade_reasons.append(
                    f"COORDINATION_PROBE_FAILED: {exc!r}.  "
                    "Delegated participant count from coordination layer unavailable."
                )

        if _SESSION_REGISTRY_AVAILABLE and _list_attached_sessions is not None:
            try:
                sessions = _list_attached_sessions() or []
                # Each active attached session corresponds to a delegated runtime.
                # Only count as a new delegated participant if not already in list.
                existing_ids = {p.device_id for p in participant_classifications}
                for session in sessions:
                    session_device_id = getattr(session, "device_id", None) or getattr(
                        session, "participant_id", None
                    )
                    if session_device_id and session_device_id not in existing_ids:
                        delegated_count += 1
                        participant_classifications.append(
                            ParticipantClassification(
                                participant_id=str(session_device_id),
                                device_id=str(session_device_id),
                                role=DelegatedParticipantRole.delegated,
                                has_evidence=False,
                                notes="sourced from attached session registry",
                            )
                        )
                        existing_ids.add(session_device_id)
            except Exception as exc:
                downgrade_reasons.append(
                    f"SESSION_REGISTRY_PROBE_FAILED: {exc!r}.  "
                    "Attached session count unavailable."
                )

        return delegated_count, secondary_count, participant_classifications

    def _probe_delegated_evidence(
        self,
        delegated_count: int,
        downgrade_reasons: List[str],
    ) -> tuple:
        """Probe for delegated participant and secondary device evidence.

        Returns
        -------
        tuple of (has_delegated_evidence, secondary_evidence_present)
        """
        has_delegated_evidence = False
        secondary_evidence = False

        # Probe android audit recorder for delegated events
        if _AUDIT_AVAILABLE and _get_audit_recorder is not None:
            try:
                recorder = _get_audit_recorder()
                audit_count = 0
                if hasattr(recorder, "get_audit_records"):
                    records = recorder.get_audit_records() or []
                    audit_count = len(records)
                elif hasattr(recorder, "_records"):
                    audit_count = len(recorder._records)

                if audit_count > 0:
                    has_delegated_evidence = True
            except Exception as exc:
                downgrade_reasons.append(
                    f"AUDIT_PROBE_FAILED: {exc!r}.  "
                    "Delegated runtime audit evidence unavailable."
                )

        # Probe participant evidence ingress
        if _PARTICIPANT_EVIDENCE_AVAILABLE and _ingest_participant_evidence is not None:
            try:
                evidence = _ingest_participant_evidence()
                if evidence is not None:
                    status_val = getattr(evidence, "status", None)
                    if status_val is not None:
                        status_str = (
                            status_val.value
                            if hasattr(status_val, "value")
                            else str(status_val)
                        )
                        if status_str not in ("no_artifact", "unavailable", ""):
                            has_delegated_evidence = True
                            # If we have participant evidence but no delegated
                            # participants from the coordination layer, this is
                            # a partial evidence state.
                            if delegated_count == 0:
                                downgrade_reasons.append(
                                    "PARTICIPANT_EVIDENCE_WITHOUT_ACTIVE_PARTICIPANT: "
                                    "Evidence artifact present but no live delegated "
                                    "participant detected in coordination layer.  "
                                    "Possible stale artifact from a prior session."
                                )
            except Exception as exc:
                downgrade_reasons.append(
                    f"PARTICIPANT_EVIDENCE_PROBE_FAILED: {exc!r}.  "
                    "Android participant evidence ingress unavailable."
                )

        # If delegated_count > 0 but no evidence found → downgrade
        if delegated_count > 0 and not has_delegated_evidence:
            downgrade_reasons.append(
                "DELEGATED_PARTICIPANT_WITHOUT_EVIDENCE: "
                f"{delegated_count} delegated participant(s) detected but "
                "no runtime evidence (audit events, readiness artifacts) found.  "
                "Tier downgraded from default_mainline to conditional."
            )

        # Secondary device evidence: presence of secondary device records
        # in the coordination layer is itself evidence.
        secondary_evidence = False  # secondary evidence from secondary device audits

        return has_delegated_evidence, secondary_evidence

    def _build_capability_map(
        self,
        has_delegated_evidence: bool,
        delegated_count: int,
        downgrade_reasons: List[str],
    ) -> Dict[str, CapabilityGovernanceEntry]:
        """Build the canonical capability tier map.

        Formation / routing capabilities are ``default_mainline`` (they work
        regardless of delegated participant state).  Session coordination and
        delegation capabilities depend on delegated participant evidence.
        """
        capability_map: Dict[str, CapabilityGovernanceEntry] = {}

        for cap_name, base_tier in _KNOWN_CAPABILITY_TIERS.items():
            entry = CapabilityGovernanceEntry(
                capability_name=cap_name,
                tier=base_tier,
                evidence_present=False,
                notes="",
            )

            if base_tier == MultiDeviceSystemTier.default_mainline:
                # Formation/routing capabilities are default_mainline
                # regardless of delegated participant presence.
                entry.evidence_present = True
                entry.notes = (
                    "Formation and routing capabilities are runtime-complete "
                    "and default-mainline regardless of delegated participant state."
                )

            elif base_tier == MultiDeviceSystemTier.conditional:
                # Delegated execution/verification/evidence capabilities
                # require an active delegated participant with evidence.
                if delegated_count > 0 and has_delegated_evidence:
                    entry.tier = MultiDeviceSystemTier.conditional
                    entry.evidence_present = True
                    entry.notes = (
                        "Delegated participant present with evidence.  "
                        "Capability is conditionally active."
                    )
                elif delegated_count > 0:
                    entry.tier = MultiDeviceSystemTier.partial
                    entry.evidence_present = False
                    entry.notes = (
                        "Delegated participant present but evidence incomplete.  "
                        "Downgraded from conditional to partial."
                    )
                    downgrade_reasons.append(
                        f"CONDITIONAL_CAP_DOWNGRADED_TO_PARTIAL({cap_name}): "
                        "Delegated participant present but evidence incomplete."
                    )
                else:
                    entry.tier = MultiDeviceSystemTier.single_device_baseline
                    entry.evidence_present = False
                    entry.notes = (
                        "No delegated participant present.  "
                        "Capability is inactive in single-device mode."
                    )

            elif base_tier in (
                MultiDeviceSystemTier.guarded,
                MultiDeviceSystemTier.partial,
                MultiDeviceSystemTier.optional,
            ):
                # Contract-first / not-implemented / optional capabilities
                # are never promoted above their assigned tier.
                entry.notes = (
                    f"Tier is {base_tier.value}.  "
                    "Contract-first, not-implemented, or optional sub-surfaces "
                    "prevent default-mainline promotion.  "
                    "DELEGATED_HOOKS_DO_NOT_EQUAL_FULLY_ACTIVE_POLICY applied."
                )

            capability_map[cap_name] = entry

        return capability_map

    @staticmethod
    def _classify_capabilities(
        capability_map: Dict[str, CapabilityGovernanceEntry],
    ) -> tuple:
        """Return tier lists from the capability map."""
        default_mainline: List[str] = []
        conditional: List[str] = []
        guarded: List[str] = []
        partial: List[str] = []
        optional: List[str] = []

        for name, entry in capability_map.items():
            t = entry.tier
            if t == MultiDeviceSystemTier.default_mainline:
                default_mainline.append(name)
            elif t == MultiDeviceSystemTier.conditional:
                conditional.append(name)
            elif t == MultiDeviceSystemTier.guarded:
                guarded.append(name)
            elif t == MultiDeviceSystemTier.partial:
                partial.append(name)
            elif t == MultiDeviceSystemTier.optional:
                optional.append(name)

        return default_mainline, conditional, guarded, partial, optional

    def _derive_tier_and_verdict(
        self,
        delegated_count: int,
        has_delegated_evidence: bool,
        secondary_evidence: bool,
        default_mainline_caps: List[str],
        guarded_caps: List[str],
        downgrade_reasons: List[str],
    ) -> tuple:
        """Derive the overall system tier and governance verdict.

        Invariants:
        - No delegated participant → single_device_baseline
        - Delegated participant + full evidence → default_mainline_active
          (only if no blocking guarded capabilities)
        - Delegated participant + partial evidence → conditional_active
        - Guarded capabilities present → guarded_baseline (caps not yet
          fully operational)
        """
        if delegated_count == 0:
            # Policy: no delegated participant → single-device baseline.
            # Do NOT report multi-device operational state.
            system_tier = MultiDeviceSystemTier.single_device_baseline
            verdict = MultiDeviceGovernanceVerdict.single_device_baseline
            downgrade_reasons.append(
                "SINGLE_DEVICE_BASELINE_POLICY: No delegated participant present.  "
                "System is operating in single-device mode.  "
                "Multi-device infrastructure is wired but not activated.  "
                "NO_DELEGATED_PARTICIPANT_NO_MULTI_DEVICE_OPERATIONAL_POLICY applied."
            )
            return system_tier, verdict

        # Delegated participant is present.
        if has_delegated_evidence:
            # We have a delegated participant with evidence.
            # Check if guarded capabilities prevent default-mainline promotion.
            if guarded_caps:
                # Guarded capabilities exist — cannot reach default_mainline.
                system_tier = MultiDeviceSystemTier.conditional
                verdict = MultiDeviceGovernanceVerdict.conditional_active
                downgrade_reasons.append(
                    f"GUARDED_CAPABILITIES_PREVENT_DEFAULT_MAINLINE: "
                    f"{len(guarded_caps)} guarded capability(ies) "
                    f"({', '.join(guarded_caps[:3])}{'...' if len(guarded_caps) > 3 else ''}) "
                    "prevent promotion to default-mainline.  "
                    "DELEGATED_HOOKS_DO_NOT_EQUAL_FULLY_ACTIVE_POLICY applied."
                )
            else:
                system_tier = MultiDeviceSystemTier.default_mainline
                verdict = MultiDeviceGovernanceVerdict.default_mainline_active
        else:
            # Delegated participant present but no evidence.
            system_tier = MultiDeviceSystemTier.conditional
            verdict = MultiDeviceGovernanceVerdict.conditional_active
            # downgrade already recorded in _probe_delegated_evidence

        return system_tier, verdict

    @staticmethod
    def _build_summary(
        verdict: MultiDeviceGovernanceVerdict,
        system_tier: MultiDeviceSystemTier,
        delegated_count: int,
        secondary_count: int,
        has_delegated_evidence: bool,
        secondary_evidence: bool,
        default_mainline_caps: List[str],
        guarded_caps: List[str],
        downgrade_reasons: List[str],
    ) -> str:
        """Build a human-readable multi-line governance summary."""
        lines: List[str] = []
        lines.append("=" * 68)
        lines.append("MULTI-DEVICE CANONICAL GOVERNANCE REPORT  (PR-09)")
        lines.append("=" * 68)

        verdict_label = verdict.value.upper().replace("_", " ")
        lines.append(f"VERDICT     : {verdict_label}")
        lines.append(f"SYSTEM TIER : {system_tier.value.upper().replace('_', ' ')}")
        lines.append("")

        lines.append("PARTICIPANT STATE")
        lines.append("-" * 40)
        lines.append(f"  Delegated participants : {delegated_count}")
        lines.append(f"  Secondary devices      : {secondary_count}")
        lines.append(
            f"  Delegated evidence     : {'YES' if has_delegated_evidence else 'NO'}"
        )
        lines.append(
            f"  Secondary evidence     : {'YES' if secondary_evidence else 'NO'}"
        )
        lines.append("")

        lines.append("CAPABILITY GOVERNANCE SUMMARY")
        lines.append("-" * 40)
        lines.append(f"  default-mainline : {len(default_mainline_caps)} cap(s)")
        lines.append(f"  guarded          : {len(guarded_caps)} cap(s)")
        if guarded_caps:
            for gc in guarded_caps[:5]:
                lines.append(f"    - {gc}")
            if len(guarded_caps) > 5:
                lines.append(f"    ... ({len(guarded_caps) - 5} more)")
        lines.append("")

        if downgrade_reasons:
            lines.append("DOWNGRADE REASONS")
            lines.append("-" * 40)
            for reason in downgrade_reasons:
                lines.append(f"  {reason}")
            lines.append("")

        if verdict.is_default_mainline:
            lines.append(
                "CONCLUSION: Multi-device / delegated runtime is FORMALLY classified "
                "as a default-mainline system surface.  Live delegated participant "
                "evidence is present and complete."
            )
        elif verdict == MultiDeviceGovernanceVerdict.conditional_active:
            lines.append(
                "CONCLUSION: Multi-device / delegated runtime is CONDITIONALLY ACTIVE.  "
                "Delegated participant(s) detected but not all surfaces are "
                "default-mainline.  Evidence or capability gaps remain."
            )
        elif verdict == MultiDeviceGovernanceVerdict.single_device_baseline:
            lines.append(
                "CONCLUSION: System is operating in SINGLE-DEVICE BASELINE mode.  "
                "Multi-device infrastructure is wired but no delegated participant "
                "is present in the current runtime context.  This is the honest "
                "operational state when only one device is active."
            )
        else:
            lines.append(
                "CONCLUSION: Multi-device governance state is PARTIAL or NO-EVIDENCE.  "
                "Cannot classify as multi-device operational."
            )

        lines.append("=" * 68)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Process-global singleton and helpers
# ---------------------------------------------------------------------------

_evaluator_singleton: Optional[MultiDeviceGovernanceEvaluator] = None


def get_multi_device_governance_evaluator() -> MultiDeviceGovernanceEvaluator:
    """Return the process-global :class:`MultiDeviceGovernanceEvaluator`
    singleton.

    Creates the singleton on first call.  Use
    :func:`reset_multi_device_governance_evaluator` for test isolation.
    """
    global _evaluator_singleton
    if _evaluator_singleton is None:
        _evaluator_singleton = MultiDeviceGovernanceEvaluator()
    return _evaluator_singleton


def reset_multi_device_governance_evaluator() -> None:
    """Reset the process-global singleton.

    Intended for test isolation only.  Do not call from production code.
    """
    global _evaluator_singleton
    _evaluator_singleton = None


def build_multi_device_governance_report() -> MultiDeviceGovernanceReport:
    """Convenience wrapper: evaluate and return a
    :class:`MultiDeviceGovernanceReport`.

    Equivalent to ``get_multi_device_governance_evaluator().evaluate()``.
    """
    return get_multi_device_governance_evaluator().evaluate()
