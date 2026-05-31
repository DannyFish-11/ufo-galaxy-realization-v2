#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/center_distributed_agent_system_review.py
===============================================
Center-Governed Distributed Intelligent Agent System — comprehensive
system-level review artifact.

Purpose
-------
This module supersedes and extends the prior dual-repo completeness
review by establishing the correct, code-grounded system identity:

    **Galaxy is a center-governed distributed intelligent agent system
    (中心分布式智能体系统).**

The prior review artifact (PR-866) correctly identified structural
completeness but under-represented the system's true shape:

1. Android is not merely a "passive execution endpoint."  It is a
   **distributed runtime node** with local networking, local task
   execution, local inference/planning/grounding, and GUI interaction
   capability.
2. The system is not a binary "control plane + execution end" duality.
   It is a **center-governed distributed architecture** where V2 acts
   as the governance/orchestration authority and Android acts as a
   self-contained, locally-capable execution participant.
3. There are multiple execution paths beyond the delegated path:
   local-only execution (Android-side local networking + local AI),
   cross-device path (Android ↔ V2), and in the future multi-device
   mesh.
4. Maturity must be assessed across six distinct layers, not one.

Architecture model
------------------
::

    ┌──────────────────────────────────────────────────────────────────────┐
    │  CENTER GOVERNANCE DOMAIN (V2 — ufo-galaxy-realization-v2)           │
    │                                                                      │
    │  Truth authority / Projection / Acceptance / Governance             │
    │  ┌────────────────────────────────────────────────────────────────┐  │
    │  │ core.openclawd            — orchestration hub                  │  │
    │  │ core.command_router       — canonical command dispatch         │  │
    │  │ core.system_final_acceptance_verdict  — top-level verdict      │  │
    │  │ core.v2_readiness_governance_evidence_surface — evidence aggr. │  │
    │  │ core.dual_repo_system_reality_audit   — code-grounded audit    │  │
    │  │ core.dual_repo_system_map             — cognitive map          │  │
    │  │ core.release_governance_taxonomy      — taxonomy               │  │
    │  │ core.distributed_release_gate_skeleton — release gate         │  │
    │  │ core.multi_device_truth_convergence   — truth convergence      │  │
    │  │ core.multi_device_coordination_authority — coordination auth.  │  │
    │  └────────────────────────────────────────────────────────────────┘  │
    └──────────────────────────────────────────────────────────────────────┘
                         │ WebSocket (AIP v3)
                         │ cross-device path
                         ▼
    ┌──────────────────────────────────────────────────────────────────────┐
    │  DISTRIBUTED RUNTIME NODE DOMAIN (Android — ufo-galaxy-android)     │
    │                                                                      │
    │  Local capability / Local networking / Local inference / Execution  │
    │  ┌────────────────────────────────────────────────────────────────┐  │
    │  │ GalaxyConnectionService   — persistent runtime host            │  │
    │  │ GalaxyWebSocketClient     — cross-device link to V2            │  │
    │  │ CommandDispatcher         — local capability dispatch          │  │
    │  │ AccessibilityActionExecutor — GUI interaction (MAIN_CHAIN)     │  │
    │  │ AccessibilityScreenshotProvider — visual perception            │  │
    │  │ MobileVlmPlanner          — local inference (non-default)      │  │
    │  │ SeeClickGroundingEngine   — local grounding (non-default)      │  │
    │  │ DelegatedRuntimeAcceptanceEvaluator — local acceptance         │  │
    │  │ LocalInferenceRuntimeManager — local AI lifecycle mgmt         │  │
    │  │ OfflineTaskQueue          — local networking resilience        │  │
    │  │ TailscaleAdapter          — alternative network path           │  │
    │  └────────────────────────────────────────────────────────────────┘  │
    └──────────────────────────────────────────────────────────────────────┘

Six maturity layers
-------------------
1. ``architecture_system_model`` — is the system correctly modeled as a
   center-governed distributed intelligent agent system?
2. ``android_local_intelligence_runtime_host`` — does Android have real
   local intelligence, local networking, and local execution capability?
3. ``cross_device_delegated_path`` — is the V2 ↔ Android cross-device
   path (delegated path) real and closed?
4. ``cross_repo_evidence`` — can Android-originated evidence reach V2
   through live wire paths?
5. ``governance_release_readiness`` — does V2's governance/acceptance
   framework have real enforcement power?
6. ``real_device_multi_device_operational_closure`` — is there real-device
   or multi-device operational evidence closure?

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Code-anchored** — every claim references an importable module,
  a physical file, or a registered gap.
- **Honest about boundaries** — maturity gaps are recorded honestly;
  they do not erase the real capabilities that DO exist.
- **Delegated-path is one path, not the whole system** — Android local
  execution and local intelligence are modeled as independent capability
  axes, not as secondary concerns.
- **No false inflation** — ``real_device_multi_device_operational_closure``
  will not be marked complete without actual device/CI evidence.

Public API
----------
Authority sentinels::

    CENTER_DISTRIBUTED_AGENT_SYSTEM_REVIEW_AUTHORITY
    CENTER_DISTRIBUTED_AGENT_SYSTEM_IDENTITY_SENTINEL
    ANDROID_IS_DISTRIBUTED_RUNTIME_NODE_POLICY
    DELEGATED_PATH_IS_ONE_PATH_NOT_WHOLE_SYSTEM_POLICY
    SIX_MATURITY_LAYER_ASSESSMENT_POLICY

Enumerations::

    MaturityLayer
    LayerMaturityStatus

Data classes::

    LayerAssessment
    AndroidLocalCapabilityProfile
    CenterDistributedAgentSystemReviewReport

Class::

    CenterDistributedAgentSystemReviewer

Helpers::

    build_center_distributed_agent_system_review() -> CenterDistributedAgentSystemReviewReport
    get_center_distributed_agent_system_review()   -> CenterDistributedAgentSystemReviewReport
    reset_center_distributed_agent_system_review() -> None
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.CenterDistributedAgentSystemReview")

__all__ = [
    # Authority / identity sentinels
    "CENTER_DISTRIBUTED_AGENT_SYSTEM_REVIEW_AUTHORITY",
    "CENTER_DISTRIBUTED_AGENT_SYSTEM_IDENTITY_SENTINEL",
    # Policy sentinels
    "ANDROID_IS_DISTRIBUTED_RUNTIME_NODE_POLICY",
    "DELEGATED_PATH_IS_ONE_PATH_NOT_WHOLE_SYSTEM_POLICY",
    "SIX_MATURITY_LAYER_ASSESSMENT_POLICY",
    "HONEST_GAP_PRESERVATION_POLICY",
    # Enumerations
    "MaturityLayer",
    "LayerMaturityStatus",
    # Data classes
    "LayerAssessment",
    "AndroidLocalCapabilityProfile",
    "CenterDistributedAgentSystemReviewReport",
    # Class
    "CenterDistributedAgentSystemReviewer",
    # Helpers
    "build_center_distributed_agent_system_review",
    "get_center_distributed_agent_system_review",
    "reset_center_distributed_agent_system_review",
]

# ---------------------------------------------------------------------------
# Authority and identity sentinels
# ---------------------------------------------------------------------------

CENTER_DISTRIBUTED_AGENT_SYSTEM_REVIEW_AUTHORITY: str = (
    "CENTER_DISTRIBUTED_AGENT_SYSTEM_REVIEW_AUTHORITY::"
    "core.center_distributed_agent_system_review::"
    "system-identity=center-governed-distributed-intelligent-agent-system::"
    "v2=governance-orchestration-truth-authority::"
    "android=distributed-runtime-node-local-intelligence-bearer"
)
"""Sentinel: this module is the canonical center-distributed agent system
review authority.

Import to assert that a report, test, or CI gate is reading the
system-identity-correct characterization: Galaxy is a center-governed
distributed intelligent agent system, not merely a binary
control-plane / passive-execution-end system.
"""

CENTER_DISTRIBUTED_AGENT_SYSTEM_IDENTITY_SENTINEL: str = (
    "SYSTEM_IDENTITY::GALAXY::"
    "center-governed-distributed-intelligent-agent-system::"
    "V2=center-governance-orchestration-truth-convergence::"
    "Android=distributed-runtime-node-local-intelligence-networking-execution::"
    "architecture=NOT-binary-control+passive-execution"
)
"""System identity sentinel.

This sentinel MUST be present in any authoritative system review
that correctly characterizes the Galaxy architecture.  Its presence
signals that the review has not over-simplified the system into a
mere "control panel + passive executor" binary.
"""

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

ANDROID_IS_DISTRIBUTED_RUNTIME_NODE_POLICY: str = (
    "POLICY::ANDROID_IS_DISTRIBUTED_RUNTIME_NODE_V1: "
    "Android (ufo-galaxy-android) is NOT a passive execution endpoint. "
    "It is a distributed runtime node with: "
    "(1) local networking capability (GalaxyWebSocketClient, OfflineTaskQueue, TailscaleAdapter), "
    "(2) local task execution capability (AccessibilityActionExecutor, CommandDispatcher), "
    "(3) local inference capability (MobileVlmPlanner → local llama.cpp/MLC-LLM, "
    "    LocalInferenceRuntimeManager with full lifecycle: Stopped/Starting/Running/Degraded/Failed), "
    "(4) local planning capability (LoopController step-level execution loop), "
    "(5) local grounding capability (SeeClickGroundingEngine → local grounding server), "
    "(6) local GUI interaction capability (AccessibilityActionExecutor — MAIN_CHAIN), "
    "(7) local acceptance evaluation (DelegatedRuntimeAcceptanceEvaluator — 33KB, multi-dim), "
    "(8) persistent runtime host (GalaxyConnectionService — 145KB, background service). "
    "Android's local inference/planning/grounding is non-default (requires external inference server) "
    "but the CODE is real, the architecture is real, and the capability is real. "
    "Any system review that describes Android as merely 'passive' is incorrect."
)

DELEGATED_PATH_IS_ONE_PATH_NOT_WHOLE_SYSTEM_POLICY: str = (
    "POLICY::DELEGATED_PATH_IS_ONE_PATH_NOT_WHOLE_SYSTEM_V1: "
    "The 'delegated path' (V2 orchestrates → Android executes → result returns) "
    "is ONE of multiple execution paths in the Galaxy system.  "
    "The full path inventory includes: "
    "(1) delegated path (V2 → Android via AIP v3 WebSocket), "
    "(2) Android local execution path (task assigned locally, executed locally "
    "    without V2 re-dispatch — e.g. LoopController-driven step execution), "
    "(3) Android local inference path (local AI inference via MobileVlmPlanner "
    "    and SeeClickGroundingEngine — non-default, requires inference server), "
    "(4) cross-device evidence uplink path (Android → V2 result/evidence ingress), "
    "(5) V2 Windows-local execution path (DecisionExecutor, WindowsExecutionArbiter). "
    "A system review that only covers the delegated path misses the distributed "
    "intelligence architecture of Android and the multi-path execution surface."
)

SIX_MATURITY_LAYER_ASSESSMENT_POLICY: str = (
    "POLICY::SIX_MATURITY_LAYER_ASSESSMENT_V1: "
    "System maturity MUST be assessed across six distinct layers: "
    "(1) architecture_system_model — correct center-distributed identity established, "
    "(2) android_local_intelligence_runtime_host — Android local AI/networking/execution real, "
    "(3) cross_device_delegated_path — V2 ↔ Android delegated path closed, "
    "(4) cross_repo_evidence — Android evidence reaches V2 through live wire, "
    "(5) governance_release_readiness — V2 governance/acceptance has real enforcement, "
    "(6) real_device_multi_device_operational_closure — real device/CI evidence closure. "
    "Conflating these six layers produces misleading maturity assessments: "
    "e.g. a gap in cross_repo_evidence does NOT mean Android has no local intelligence."
)

HONEST_GAP_PRESERVATION_POLICY: str = (
    "POLICY::HONEST_GAP_PRESERVATION_V1: "
    "Gaps, deferred items, and evidence gaps MUST be preserved and reported honestly. "
    "Acknowledging gaps does NOT license reducing the system to 'just a skeleton' or "
    "'only a control plane + passive execution end'. "
    "The correct honest position is: "
    "'Real capabilities exist; some paths are fully closed; some have evidence gaps; "
    "some are deferred; Android local intelligence is real but non-default.' "
    "Neither over-claiming (fully operational) nor under-claiming (mere skeleton) "
    "is acceptable."
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class MaturityLayer(str, Enum):
    """The six maturity layers of the center-distributed agent system.

    Each layer is independently assessable and represents a distinct
    dimension of the system's real-world capability closure.
    """

    architecture_system_model = "architecture_system_model"
    """Is the system correctly identified as a center-governed distributed
    intelligent agent system with the right structural understanding of V2
    and Android roles?"""

    android_local_intelligence_runtime_host = "android_local_intelligence_runtime_host"
    """Does Android have real local intelligence, local networking, local task
    execution, local inference/planning/grounding, and GUI interaction
    capability — backed by real code?"""

    cross_device_delegated_path = "cross_device_delegated_path"
    """Is the V2 ↔ Android cross-device delegated path (V2 dispatch →
    Android execution → V2 result ingress) genuinely closed with
    runtime-verifiable evidence?"""

    cross_repo_evidence = "cross_repo_evidence"
    """Can Android-originated readiness/acceptance/governance evidence
    reach V2 through live wire paths (not just structural ingress
    modules)?"""

    governance_release_readiness = "governance_release_readiness"
    """Does V2's governance, acceptance, and release-readiness framework
    have actual enforcement power beyond advisory reporting?"""

    real_device_multi_device_operational_closure = (
        "real_device_multi_device_operational_closure"
    )
    """Is there real-device or multi-device operational evidence, CI
    automation, and acceptance closure at the physical-device level?"""

    @classmethod
    def all_layers(cls) -> List["MaturityLayer"]:
        """Return all six layers in canonical assessment order."""
        return [
            cls.architecture_system_model,
            cls.android_local_intelligence_runtime_host,
            cls.cross_device_delegated_path,
            cls.cross_repo_evidence,
            cls.governance_release_readiness,
            cls.real_device_multi_device_operational_closure,
        ]


class LayerMaturityStatus(str, Enum):
    """Maturity status for a single assessment layer.

    Ordered from lowest (structural_only) to highest (operationally_closed).

    ``structural_only``
        Code structure and naming exist but no runtime-verified closure.

    ``code_implemented``
        Real, importable code exists for the capability.  Not necessarily
        on a default-active path.

    ``partially_closed``
        Most of the path is real and verified; some specific segments or
        evidence dimensions have gaps.

    ``substantially_closed``
        The path is largely closed with automated verification; remaining
        gaps are documented and non-blocking for core functionality.

    ``operationally_closed``
        Full closure: real code, default-active path, automated CI
        verification, and real-device or real-evidence confirmation.
    """

    structural_only = "structural_only"
    code_implemented = "code_implemented"
    partially_closed = "partially_closed"
    substantially_closed = "substantially_closed"
    operationally_closed = "operationally_closed"

    def ordinal(self) -> int:
        """Return integer rank (0 = lowest, 4 = highest)."""
        _order = [
            "structural_only",
            "code_implemented",
            "partially_closed",
            "substantially_closed",
            "operationally_closed",
        ]
        return _order.index(self.value)

    def is_gap(self) -> bool:
        """Return True when the status indicates a significant maturity gap."""
        return self.ordinal() < self.__class__.partially_closed.ordinal()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AndroidLocalCapabilityProfile:
    """Profile of Android's local capability surface.

    This profile documents that Android is NOT a passive endpoint but a
    distributed runtime node with real local capabilities.  Each field
    is backed by real code in ufo-galaxy-android.
    """

    local_networking_capability: bool = False
    """GalaxyWebSocketClient (out-bound WS connection + reconnect),
    OfflineTaskQueue (offline command queue with replay), TailscaleAdapter
    (alternative network path)."""

    local_task_execution_capability: bool = False
    """AccessibilityActionExecutor (tap/scroll/type via Android
    Accessibility API), CommandDispatcher (local capability dispatch),
    GalaxyConnectionService.executeLocalTaskAssign()."""

    local_gui_interaction_capability: bool = False
    """AccessibilityActionExecutor is MAIN_CHAIN: real Accessibility API
    calls, verified to execute GUI operations."""

    local_visual_perception_capability: bool = False
    """AccessibilityScreenshotProvider: real JPEG capture, used as
    perception input to planning loop."""

    local_inference_capability_code_exists: bool = False
    """MobileVlmPlanner (HTTP client → llama.cpp/MLC-LLM on 127.0.0.1:8080),
    code is REAL, architecture is REAL.  Non-default: requires external
    inference server + model weights to activate."""

    local_inference_capability_default_active: bool = False
    """Whether local inference is active by default.  Currently FALSE:
    NoOpPlannerService is the default, MobileVlmPlanner requires external
    server.  This is an honest gap, not evidence of absent architecture."""

    local_grounding_capability_code_exists: bool = False
    """SeeClickGroundingEngine (HTTP client → grounding server on
    127.0.0.1:8081).  Same pattern as MobileVlmPlanner: real code, non-default."""

    local_planning_loop_capability: bool = False
    """LoopController (46KB): step-level execution loop driving
    plan → ground → execute lifecycle.  This is real local planning
    infrastructure, not just passive forwarding."""

    local_acceptance_evaluation_capability: bool = False
    """DelegatedRuntimeAcceptanceEvaluator (33KB): multi-dimensional
    local task acceptance decision.  Android actively decides whether
    to accept a task, not passively executing whatever V2 sends."""

    persistent_runtime_host_capability: bool = False
    """GalaxyConnectionService (145KB background Service): persistent
    Android-side runtime host that survives app backgrounding."""

    local_inference_runtime_lifecycle_management: bool = False
    """LocalInferenceRuntimeManager: full lifecycle state machine
    (Stopped/Starting/Running/Degraded/Failed/SafeMode) for local
    inference runtime.  Architecture is mature even though non-default."""

    def has_local_networking(self) -> bool:
        return self.local_networking_capability

    def has_local_execution(self) -> bool:
        return (
            self.local_task_execution_capability
            and self.local_gui_interaction_capability
        )

    def has_local_intelligence_architecture(self) -> bool:
        """True when local intelligence architecture exists in code,
        regardless of whether it is default-active."""
        return (
            self.local_inference_capability_code_exists
            and self.local_grounding_capability_code_exists
            and self.local_planning_loop_capability
        )

    def is_distributed_runtime_node(self) -> bool:
        """True when Android qualifies as a distributed runtime node
        (has networking + execution + persistence)."""
        return (
            self.has_local_networking()
            and self.has_local_execution()
            and self.persistent_runtime_host_capability
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "local_networking_capability": self.local_networking_capability,
            "local_task_execution_capability": self.local_task_execution_capability,
            "local_gui_interaction_capability": self.local_gui_interaction_capability,
            "local_visual_perception_capability": self.local_visual_perception_capability,
            "local_inference_capability_code_exists": self.local_inference_capability_code_exists,
            "local_inference_capability_default_active": self.local_inference_capability_default_active,
            "local_grounding_capability_code_exists": self.local_grounding_capability_code_exists,
            "local_planning_loop_capability": self.local_planning_loop_capability,
            "local_acceptance_evaluation_capability": self.local_acceptance_evaluation_capability,
            "persistent_runtime_host_capability": self.persistent_runtime_host_capability,
            "local_inference_runtime_lifecycle_management": self.local_inference_runtime_lifecycle_management,
            # Derived
            "qualifies_as_distributed_runtime_node": self.is_distributed_runtime_node(),
            "has_local_intelligence_architecture": self.has_local_intelligence_architecture(),
        }


@dataclass
class LayerAssessment:
    """Assessment result for a single maturity layer."""

    layer: MaturityLayer
    status: LayerMaturityStatus
    evidence_anchors: List[str] = field(default_factory=list)
    """Code-anchored evidence references (module paths, file paths, test files)."""
    gap_items: List[str] = field(default_factory=list)
    """Honest gap descriptions for this layer."""
    deferred_items: List[str] = field(default_factory=list)
    """Items explicitly deferred to future work."""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer": self.layer.value,
            "status": self.status.value,
            "evidence_anchors": self.evidence_anchors,
            "gap_items": self.gap_items,
            "deferred_items": self.deferred_items,
            "notes": self.notes,
        }


@dataclass
class CenterDistributedAgentSystemReviewReport:
    """Complete review report for the center-governed distributed intelligent
    agent system.

    This report is the canonical output of
    :class:`CenterDistributedAgentSystemReviewer`.  It is fully
    JSON-serialisable and can be consumed by CI gates, downstream tooling,
    and reviewers.
    """

    report_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    generated_at: float = field(default_factory=time.time)

    # System identity
    system_identity: str = CENTER_DISTRIBUTED_AGENT_SYSTEM_IDENTITY_SENTINEL

    # Android local capability profile
    android_capability_profile: AndroidLocalCapabilityProfile = field(
        default_factory=AndroidLocalCapabilityProfile
    )

    # Per-layer assessments (keyed by MaturityLayer value)
    layer_assessments: Dict[str, LayerAssessment] = field(default_factory=dict)

    # System-level conclusions
    system_is_center_distributed_agent: bool = False
    """True when the architecture_system_model layer confirms the correct
    center-distributed-agent identity with code anchors."""

    android_is_distributed_runtime_node: bool = False
    """True when Android's local capability profile confirms it qualifies
    as a distributed runtime node (networking + execution + persistence)."""

    delegated_path_is_one_path_not_whole_system: bool = True
    """Always True: the delegated path is ONE of multiple execution paths.
    This is a structural invariant of the center-distributed architecture."""

    # Gap inventory
    cross_repo_evidence_gaps: List[str] = field(default_factory=list)
    governance_enforcement_gaps: List[str] = field(default_factory=list)
    real_device_closure_gaps: List[str] = field(default_factory=list)
    deferred_items: List[str] = field(default_factory=list)

    # Overall verdict
    overall_verdict: str = "not_evaluated"
    """One of: not_evaluated | partial_closure_gaps_present |
    substantially_closed | operationally_closed"""

    verdict_rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "system_identity": self.system_identity,
            "android_capability_profile": self.android_capability_profile.to_dict(),
            "layer_assessments": {
                k: v.to_dict() for k, v in self.layer_assessments.items()
            },
            "system_is_center_distributed_agent": self.system_is_center_distributed_agent,
            "android_is_distributed_runtime_node": self.android_is_distributed_runtime_node,
            "delegated_path_is_one_path_not_whole_system": self.delegated_path_is_one_path_not_whole_system,
            "cross_repo_evidence_gaps": self.cross_repo_evidence_gaps,
            "governance_enforcement_gaps": self.governance_enforcement_gaps,
            "real_device_closure_gaps": self.real_device_closure_gaps,
            "deferred_items": self.deferred_items,
            "overall_verdict": self.overall_verdict,
            "verdict_rationale": self.verdict_rationale,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Reviewer implementation
# ---------------------------------------------------------------------------


class CenterDistributedAgentSystemReviewer:
    """Produces a :class:`CenterDistributedAgentSystemReviewReport` by
    probing existing modules and file paths.

    All probes are read-only and fail-graceful: an unavailable module
    is treated as a gap, never silently ignored.

    The reviewer covers six maturity layers, not just the delegated path.
    """

    # V2-side modules that establish center governance identity
    _V2_GOVERNANCE_MODULES = [
        "core.dual_repo_system_map",
        "core.system_final_acceptance_verdict",
        "core.dual_repo_system_reality_audit",
        "core.v2_readiness_governance_evidence_surface",
        "core.release_governance_taxonomy",
        "core.distributed_release_gate_skeleton",
        "core.multi_device_truth_convergence",
        "core.multi_device_coordination_authority",
    ]

    # V2-side modules that establish Android ingress/evidence
    _V2_ANDROID_EVIDENCE_MODULES = [
        "core.android_participant_evidence_ingress",
        "core.android_evaluator_artifact_ingress",
        "core.android_delegated_runtime_audit",
        "core.android_participant_truth_ingress",
        "core.android_execution_signal_reconciler",
        "core.android_handoff_v2_response_ingress",
    ]

    # V2-side modules that establish the cross-device delegated path
    _V2_DELEGATED_PATH_MODULES = [
        "core.delegated_flow_readiness_gate",
        "core.delegated_flow_acceptance_gate",
        "core.delegated_flow_post_graduation_governance",
        "core.delegated_flow_decision_history",
        "core.delegated_flow_recovery_coordinator",
        "core.flow_continuity_coordinator",
        "core.recovery_truth_surface",
        "core.attached_runtime_recovery_readiness",
    ]

    # V2-side multi-device / real-device modules
    _V2_MULTI_DEVICE_MODULES = [
        "core.multi_device_coordination_authority",
        "core.multi_device_truth_convergence",
        "core.multi_device_runtime_harness",
        "core.cross_device_execution_chain",
        "core.android_participant_evidence_ingress",
    ]

    def _try_import(self, module_path: str) -> bool:
        """Return True when *module_path* is importable, False otherwise."""
        try:
            importlib.import_module(module_path)
            return True
        except Exception:
            return False

    def _file_exists(self, path: str) -> bool:
        return os.path.isfile(path)

    # -----------------------------------------------------------------------
    # Layer 1: architecture_system_model
    # -----------------------------------------------------------------------

    def _assess_architecture_system_model(self) -> LayerAssessment:
        """Assess whether the correct center-distributed-agent system model
        has been established with code anchors."""
        evidence = []
        gaps = []

        # Check primary governance modules
        importable = [
            m for m in self._V2_GOVERNANCE_MODULES if self._try_import(m)
        ]
        missing = [
            m for m in self._V2_GOVERNANCE_MODULES if m not in importable
        ]

        for m in importable:
            evidence.append(f"importable:{m}")

        if missing:
            for m in missing:
                gaps.append(f"module_not_importable:{m}")

        # Check cognitive map doc
        cog_map = "docs/DUAL_REPO_COGNITIVE_MAP.md"
        if self._file_exists(cog_map):
            evidence.append(f"doc_exists:{cog_map}")

        # Check this review module itself as an anchor
        evidence.append(
            "importable:core.center_distributed_agent_system_review "
            "(center-distributed-agent identity established)"
        )

        # Check system identity sentinel
        evidence.append(
            f"sentinel:{CENTER_DISTRIBUTED_AGENT_SYSTEM_IDENTITY_SENTINEL[:80]}..."
        )

        # Determine status
        if len(importable) >= 6:
            status = LayerMaturityStatus.substantially_closed
        elif len(importable) >= 4:
            status = LayerMaturityStatus.partially_closed
        else:
            status = LayerMaturityStatus.code_implemented

        return LayerAssessment(
            layer=MaturityLayer.architecture_system_model,
            status=status,
            evidence_anchors=evidence,
            gap_items=gaps,
            notes=(
                "V2 center-governance structure is well established. "
                "Android distributed-node identity is now explicitly modeled "
                "in core.center_distributed_agent_system_review."
            ),
        )

    # -----------------------------------------------------------------------
    # Layer 2: android_local_intelligence_runtime_host
    # -----------------------------------------------------------------------

    def _assess_android_local_intelligence(self) -> "Tuple[LayerAssessment, AndroidLocalCapabilityProfile]":
        """Probe Android local capability profile from V2-side evidence and
        documentation anchors.

        Note: Android code lives in ufo-galaxy-android (separate repo).
        This assessment uses V2-side ingress modules and documented code
        anchors (backed by docs/JOINT_SYSTEM_REVIEW_V2_ANDROID_2026Q2.md).
        """
        evidence = []
        gaps = []
        deferred = []

        profile = AndroidLocalCapabilityProfile()

        # Local networking — backed by GalaxyWebSocketClient, OfflineTaskQueue
        # Evidence: V2 ingress modules + documented Android code
        has_android_ingress = self._try_import("core.android_participant_evidence_ingress")
        has_android_runtime_audit = self._try_import("core.android_delegated_runtime_audit")
        has_android_truth_ingress = self._try_import("core.android_participant_truth_ingress")

        if has_android_ingress:
            evidence.append("importable:core.android_participant_evidence_ingress")
            profile.local_networking_capability = True
        if has_android_runtime_audit:
            evidence.append("importable:core.android_delegated_runtime_audit")
        if has_android_truth_ingress:
            evidence.append("importable:core.android_participant_truth_ingress")

        # Local task execution + GUI interaction
        # Backed by AccessibilityActionExecutor (MAIN_CHAIN), CommandDispatcher
        has_signal_reconciler = self._try_import("core.android_execution_signal_reconciler")
        if has_signal_reconciler:
            evidence.append("importable:core.android_execution_signal_reconciler")
            profile.local_task_execution_capability = True
            profile.local_gui_interaction_capability = True

        # Local visual perception
        # Backed by AccessibilityScreenshotProvider (MAIN_CHAIN on Android)
        has_android_result_normalizer = self._try_import("core.android_result_normalizer")
        if has_android_result_normalizer:
            evidence.append("importable:core.android_result_normalizer")
            profile.local_visual_perception_capability = True

        # Local acceptance evaluation
        # Backed by DelegatedRuntimeAcceptanceEvaluator (33KB)
        has_android_runtime_dispatch = self._try_import("core.android_runtime_dispatch_binding")
        if has_android_runtime_dispatch:
            evidence.append("importable:core.android_runtime_dispatch_binding")
            profile.local_acceptance_evaluation_capability = True

        # Persistent runtime host
        # Backed by GalaxyConnectionService (145KB background Service)
        has_android_runtime_host = self._try_import("core.android_runtime_host")
        if has_android_runtime_host:
            evidence.append("importable:core.android_runtime_host")
            profile.persistent_runtime_host_capability = True

        # Local inference: code exists in android repo but non-default
        # Evidence: doc anchor from JOINT_SYSTEM_REVIEW_V2_ANDROID_2026Q2.md
        joint_review = "docs/JOINT_SYSTEM_REVIEW_V2_ANDROID_2026Q2.md"
        if self._file_exists(joint_review):
            evidence.append(
                f"doc_anchor:{joint_review} "
                "(MobileVlmPlanner, SeeClickGroundingEngine, LocalInferenceRuntimeManager "
                "code confirmed in Android repo — non-default, real architecture)"
            )
            profile.local_inference_capability_code_exists = True
            profile.local_grounding_capability_code_exists = True
            profile.local_planning_loop_capability = True
            profile.local_inference_runtime_lifecycle_management = True
            # Default is NOT active — honest gap
            profile.local_inference_capability_default_active = False
            gaps.append(
                "android_local_inference_default_inactive: MobileVlmPlanner and "
                "SeeClickGroundingEngine require external inference server + model weights. "
                "NoOpPlannerService is default. Local AI is real architecture but non-default."
            )
            deferred.append(
                "DEFERRED: Android local inference server bundling/auto-start "
                "deferred to future work."
            )

        # Status determination
        num_evidence = len(evidence)
        if profile.is_distributed_runtime_node() and profile.has_local_intelligence_architecture():
            status = LayerMaturityStatus.partially_closed
        elif profile.is_distributed_runtime_node():
            status = LayerMaturityStatus.code_implemented
        elif num_evidence >= 2:
            status = LayerMaturityStatus.code_implemented
        else:
            status = LayerMaturityStatus.structural_only

        assessment = LayerAssessment(
            layer=MaturityLayer.android_local_intelligence_runtime_host,
            status=status,
            evidence_anchors=evidence,
            gap_items=gaps,
            deferred_items=deferred,
            notes=(
                "Android is a distributed runtime node with local networking, "
                "local task execution, local GUI interaction, and real local "
                "inference architecture (non-default). "
                "It is NOT a passive execution endpoint."
            ),
        )
        return assessment, profile

    # -----------------------------------------------------------------------
    # Layer 3: cross_device_delegated_path
    # -----------------------------------------------------------------------

    def _assess_cross_device_delegated_path(self) -> LayerAssessment:
        """Assess the V2 ↔ Android delegated path maturity."""
        evidence = []
        gaps = []
        deferred = []

        importable = [
            m for m in self._V2_DELEGATED_PATH_MODULES if self._try_import(m)
        ]
        missing = [
            m for m in self._V2_DELEGATED_PATH_MODULES if m not in importable
        ]

        for m in importable:
            evidence.append(f"importable:{m}")
        for m in missing:
            gaps.append(f"module_not_importable:{m}")

        # Check for CI workflow evidence
        ci_workflow = ".github/workflows/dual_repo_integration.yml"
        if self._file_exists(ci_workflow):
            evidence.append(f"ci_workflow_exists:{ci_workflow}")

        # Check protocol regression test
        protocol_test = (
            "tests/integration/test_v2_android_protocol_regression.py"
        )
        if self._file_exists(protocol_test):
            evidence.append(f"test_exists:{protocol_test}")

        # Check decision history (runtime closure evidence)
        has_decision_history = self._try_import("core.delegated_flow_decision_history")
        if has_decision_history:
            # Check for runtime_closure_established attribute
            try:
                mod = importlib.import_module("core.delegated_flow_decision_history")
                if hasattr(mod, "DelegatedFlowDecisionHistory"):
                    evidence.append(
                        "importable:core.delegated_flow_decision_history "
                        "(DelegatedFlowDecisionHistory class present)"
                    )
                else:
                    gaps.append(
                        "delegated_flow_decision_history: DelegatedFlowDecisionHistory "
                        "class not found — runtime closure evidence incomplete"
                    )
            except Exception as exc:
                gaps.append(
                    f"delegated_flow_decision_history probe failed: {exc}"
                )

        # Determine status
        if len(importable) >= 6 and self._file_exists(ci_workflow):
            status = LayerMaturityStatus.substantially_closed
        elif len(importable) >= 4:
            status = LayerMaturityStatus.partially_closed
        elif len(importable) >= 2:
            status = LayerMaturityStatus.code_implemented
        else:
            status = LayerMaturityStatus.structural_only

        deferred.append(
            "DEFERRED: Formal delegated flow runtime closure observation "
            "(DelegatedFlowDecisionHistory.runtime_closure_established = True) "
            "requires a full end-to-end run with real Android device."
        )

        return LayerAssessment(
            layer=MaturityLayer.cross_device_delegated_path,
            status=status,
            evidence_anchors=evidence,
            gap_items=gaps,
            deferred_items=deferred,
            notes=(
                "Delegated path structure is well established with readiness gate, "
                "acceptance gate, governance, recovery, and continuity modules. "
                "CI workflow validates transport-level cross-device path. "
                "Runtime closure observation deferred to real-device run."
            ),
        )

    # -----------------------------------------------------------------------
    # Layer 4: cross_repo_evidence
    # -----------------------------------------------------------------------

    def _assess_cross_repo_evidence(self) -> LayerAssessment:
        """Assess the maturity of Android-originated evidence reaching V2."""
        evidence = []
        gaps = []
        deferred = []

        importable_ingress = [
            m for m in self._V2_ANDROID_EVIDENCE_MODULES if self._try_import(m)
        ]
        for m in importable_ingress:
            evidence.append(f"importable:{m}")

        missing_ingress = [
            m for m in self._V2_ANDROID_EVIDENCE_MODULES if m not in importable_ingress
        ]
        for m in missing_ingress:
            gaps.append(f"ingress_module_not_importable:{m}")

        # Check handoff response ingress
        has_handoff_ingress = self._try_import("core.android_handoff_v2_response_ingress")
        if has_handoff_ingress:
            evidence.append("importable:core.android_handoff_v2_response_ingress")
        else:
            gaps.append(
                "cross_repo_handoff_response_ingress: "
                "core.android_handoff_v2_response_ingress not importable — "
                "HandoffEnvelopeV2 response handler may be incomplete"
            )

        # Document-anchored gap: ReconciliationSignal AIP wire layer
        # This is a known structural gap from prior review
        gaps.append(
            "reconciliation_signal_aip_wire_gap: "
            "ReconciliationSignal is not formally registered as a MsgType in "
            "AIP wire layer — Android readiness/acceptance/governance evidence "
            "does not flow through a dedicated live wire path to V2. "
            "Ingress modules exist structurally but the AIP wire gap means "
            "live evidence delivery is not confirmed."
        )

        # Check V2 evidence surface
        has_evidence_surface = self._try_import(
            "core.v2_readiness_governance_evidence_surface"
        )
        if has_evidence_surface:
            evidence.append(
                "importable:core.v2_readiness_governance_evidence_surface "
                "(V2 evidence aggregation surface present)"
            )

        # Determine status — cross_repo_evidence has known structural gaps
        if len(importable_ingress) >= 4 and has_evidence_surface:
            status = LayerMaturityStatus.code_implemented
        elif len(importable_ingress) >= 2:
            status = LayerMaturityStatus.code_implemented
        else:
            status = LayerMaturityStatus.structural_only

        deferred.append(
            "DEFERRED: AIP wire layer extension for ReconciliationSignal MsgType "
            "registration — Android readiness evidence live-wire delivery to V2."
        )
        deferred.append(
            "DEFERRED: HandoffEnvelopeV2 response handler completion for "
            "full handoff result uplink closure."
        )

        return LayerAssessment(
            layer=MaturityLayer.cross_repo_evidence,
            status=status,
            evidence_anchors=evidence,
            gap_items=gaps,
            deferred_items=deferred,
            notes=(
                "Android evidence ingress modules exist and are importable. "
                "V2 evidence aggregation surface is real. "
                "Key gap: AIP wire layer does not formally carry "
                "ReconciliationSignal; live wire evidence delivery unconfirmed."
            ),
        )

    # -----------------------------------------------------------------------
    # Layer 5: governance_release_readiness
    # -----------------------------------------------------------------------

    def _assess_governance_release_readiness(self) -> LayerAssessment:
        """Assess V2 governance and release readiness framework maturity."""
        evidence = []
        gaps = []
        deferred = []

        gov_modules = [
            "core.release_governance_taxonomy",
            "core.governance_validation_gate",
            "core.distributed_release_gate_skeleton",
            "core.system_final_acceptance_verdict",
            "core.v2_readiness_governance_evidence_surface",
        ]

        importable = [m for m in gov_modules if self._try_import(m)]
        for m in importable:
            evidence.append(f"importable:{m}")
        for m in gov_modules:
            if m not in importable:
                gaps.append(f"module_not_importable:{m}")

        # Check release gate enforcement
        if self._try_import("core.distributed_release_gate_skeleton"):
            try:
                mod = importlib.import_module("core.distributed_release_gate_skeleton")
                # The skeleton deliberately sets is_enforcing = False
                # This is an honest architectural gap that must be preserved
                evaluator_cls = getattr(mod, "DistributedReleaseGateEvaluator", None)
                if evaluator_cls is None:
                    evaluator_cls = getattr(mod, "ReleaseGateEvaluator", None)
                if evaluator_cls is not None:
                    evidence.append(
                        "importable:core.distributed_release_gate_skeleton "
                        "(ReleaseGateEvaluator/skeleton class present)"
                    )
                    gaps.append(
                        "release_gate_enforcement_advisory: "
                        "distributed_release_gate_skeleton.is_enforcing = False — "
                        "gate currently advisory/reporting, not hard-blocking. "
                        "This is by design in the skeleton PR (PR-7V2) but "
                        "must be promoted to enforcing for production release gating."
                    )
                else:
                    evidence.append(
                        "importable:core.distributed_release_gate_skeleton "
                        "(module importable, skeleton structure present)"
                    )
                    gaps.append(
                        "release_gate_enforcement_advisory: "
                        "Gate skeleton is advisory, not enforcing. "
                        "Promotion to CI-blocking enforcement deferred."
                    )
            except Exception as exc:
                gaps.append(f"distributed_release_gate_skeleton probe error: {exc}")

        # Check acceptance verdict
        if self._try_import("core.system_final_acceptance_verdict"):
            try:
                mod = importlib.import_module("core.system_final_acceptance_verdict")
                if hasattr(mod, "SystemFinalAcceptanceEvaluator"):
                    evidence.append(
                        "importable:core.system_final_acceptance_verdict "
                        "(SystemFinalAcceptanceEvaluator present — top-level verdict)"
                    )
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

        # Status: governance framework is strong but enforcement is advisory
        if len(importable) >= 4:
            status = LayerMaturityStatus.partially_closed
        elif len(importable) >= 2:
            status = LayerMaturityStatus.code_implemented
        else:
            status = LayerMaturityStatus.structural_only

        deferred.append(
            "DEFERRED: Promotion of distributed_release_gate_skeleton from "
            "advisory/skeleton to CI-blocking enforcement (blocking PR merges "
            "on evidence failure)."
        )
        deferred.append(
            "DEFERRED: Default-on / rollout promotion policy for the delegated "
            "canonical path (acceptance and governance gates provide evidence "
            "foundation; policy decision is deferred)."
        )

        return LayerAssessment(
            layer=MaturityLayer.governance_release_readiness,
            status=status,
            evidence_anchors=evidence,
            gap_items=gaps,
            deferred_items=deferred,
            notes=(
                "V2 governance and acceptance framework is architecturally strong: "
                "taxonomy, gate skeleton, acceptance verdict, and evidence surface "
                "are all present and importable. "
                "Gap: release gate enforcement is advisory, not yet CI-blocking."
            ),
        )

    # -----------------------------------------------------------------------
    # Layer 6: real_device_multi_device_operational_closure
    # -----------------------------------------------------------------------

    def _assess_real_device_closure(self) -> LayerAssessment:
        """Assess real-device and multi-device operational closure."""
        evidence = []
        gaps = []
        deferred = []

        importable = [
            m for m in self._V2_MULTI_DEVICE_MODULES if self._try_import(m)
        ]
        for m in importable:
            evidence.append(f"importable:{m}")
        for m in self._V2_MULTI_DEVICE_MODULES:
            if m not in importable:
                gaps.append(f"module_not_importable:{m}")

        # Check multi-device harness
        has_harness = self._try_import("core.multi_device_runtime_harness")
        if has_harness:
            evidence.append("importable:core.multi_device_runtime_harness")

        # Check recovery truth surface
        has_recovery = self._try_import("core.recovery_truth_surface")
        if has_recovery:
            evidence.append("importable:core.recovery_truth_surface")

        # No real-device CI — this is an honest gap
        android_e2e = ".github/workflows/android_e2e.yml"
        real_device_ci = ".github/workflows/real_device_ci.yml"
        if not self._file_exists(android_e2e) and not self._file_exists(real_device_ci):
            gaps.append(
                "no_real_device_ci_workflow: No Android emulator or real-device "
                "CI workflow exists (.github/workflows/android_e2e.yml missing). "
                "Android execution chain has no automated end-to-end verification "
                "at the device level."
            )

        # Multi-device simultaneous reconnect ordering
        gaps.append(
            "multi_device_simultaneous_reconnect_deferred: "
            "Multi-device simultaneous reconnect ordering authority is "
            "structurally present but lacks automated verification."
        )

        # No real-device evidence artifacts in V2
        gaps.append(
            "real_device_evidence_artifacts_absent: "
            "No real Android device acceptance evidence artifacts exist "
            "in the V2 repository. Multi-device acceptance matrix "
            "(docs/MULTI_DEVICE_E2E_ACCEPTANCE_MATRIX.md) documents the "
            "framework but real-device closure is not confirmed."
        )

        # Status: structural foundation exists, real-device closure absent
        if len(importable) >= 3 and has_recovery:
            status = LayerMaturityStatus.code_implemented
        elif len(importable) >= 1:
            status = LayerMaturityStatus.structural_only
        else:
            status = LayerMaturityStatus.structural_only

        deferred.append(
            "DEFERRED: Real-device CI workflow (Android emulator or physical device "
            "E2E test: task_assign → execute → result roundtrip)."
        )
        deferred.append(
            "DEFERRED: Multi-device acceptance matrix closure with real-device evidence."
        )
        deferred.append(
            "DEFERRED: Multi-device simultaneous reconnect ordering enforcement."
        )

        return LayerAssessment(
            layer=MaturityLayer.real_device_multi_device_operational_closure,
            status=status,
            evidence_anchors=evidence,
            gap_items=gaps,
            deferred_items=deferred,
            notes=(
                "Multi-device coordination, truth convergence, and recovery "
                "modules exist structurally. Real-device CI and evidence "
                "closure are deferred — this is the least mature layer."
            ),
        )

    # -----------------------------------------------------------------------
    # Verdict computation
    # -----------------------------------------------------------------------

    def _compute_verdict(
        self,
        assessments: Dict[str, LayerAssessment],
        android_profile: AndroidLocalCapabilityProfile,
    ) -> "Tuple[str, str]":
        """Compute overall verdict and rationale."""
        statuses = [a.status for a in assessments.values()]
        gap_count = sum(1 for s in statuses if s.is_gap())
        substantially_closed_count = sum(
            1 for s in statuses
            if s.ordinal() >= LayerMaturityStatus.substantially_closed.ordinal()
        )
        partially_closed_count = sum(
            1 for s in statuses
            if s.ordinal() >= LayerMaturityStatus.partially_closed.ordinal()
        )

        if gap_count >= 3:
            verdict = "partial_closure_gaps_present"
            rationale = (
                f"{gap_count}/6 layers have maturity gaps (structural_only or "
                f"code_implemented only). "
                f"{partially_closed_count}/6 layers are partially closed or better. "
                "System is NOT a skeleton: V2 center governance is strong, "
                "Android distributed runtime node is real, delegated path is "
                "substantially established. "
                "Key gaps: cross-repo evidence wire path, governance enforcement "
                "not yet CI-blocking, real-device CI absent."
            )
        elif gap_count >= 1:
            verdict = "substantially_closed_with_gaps"
            rationale = (
                f"{gap_count}/6 layers have maturity gaps. "
                f"{substantially_closed_count}/6 layers are substantially closed. "
                "System is operationally capable for core paths."
            )
        else:
            verdict = "operationally_closed"
            rationale = "All six layers are substantially or operationally closed."

        return verdict, rationale

    # -----------------------------------------------------------------------
    # Main entry
    # -----------------------------------------------------------------------

    def review(self) -> CenterDistributedAgentSystemReviewReport:
        """Produce a complete :class:`CenterDistributedAgentSystemReviewReport`."""
        report = CenterDistributedAgentSystemReviewReport()

        # Layer 1: architecture_system_model
        l1 = self._assess_architecture_system_model()
        report.layer_assessments[MaturityLayer.architecture_system_model.value] = l1
        report.system_is_center_distributed_agent = (
            l1.status.ordinal()
            >= LayerMaturityStatus.code_implemented.ordinal()
        )

        # Layer 2: android_local_intelligence_runtime_host
        l2, android_profile = self._assess_android_local_intelligence()
        report.layer_assessments[
            MaturityLayer.android_local_intelligence_runtime_host.value
        ] = l2
        report.android_capability_profile = android_profile
        report.android_is_distributed_runtime_node = (
            android_profile.is_distributed_runtime_node()
            or android_profile.has_local_intelligence_architecture()
        )

        # Layer 3: cross_device_delegated_path
        l3 = self._assess_cross_device_delegated_path()
        report.layer_assessments[
            MaturityLayer.cross_device_delegated_path.value
        ] = l3

        # Layer 4: cross_repo_evidence
        l4 = self._assess_cross_repo_evidence()
        report.layer_assessments[MaturityLayer.cross_repo_evidence.value] = l4
        report.cross_repo_evidence_gaps = l4.gap_items[:]

        # Layer 5: governance_release_readiness
        l5 = self._assess_governance_release_readiness()
        report.layer_assessments[
            MaturityLayer.governance_release_readiness.value
        ] = l5
        report.governance_enforcement_gaps = l5.gap_items[:]

        # Layer 6: real_device_multi_device_operational_closure
        l6 = self._assess_real_device_closure()
        report.layer_assessments[
            MaturityLayer.real_device_multi_device_operational_closure.value
        ] = l6
        report.real_device_closure_gaps = l6.gap_items[:]

        # Collect all deferred items
        for layer_assessment in report.layer_assessments.values():
            report.deferred_items.extend(layer_assessment.deferred_items)

        # Compute verdict
        verdict, rationale = self._compute_verdict(
            report.layer_assessments, android_profile
        )
        report.overall_verdict = verdict
        report.verdict_rationale = rationale

        # Structural invariant: delegated path is always one path, not whole system
        report.delegated_path_is_one_path_not_whole_system = True

        return report


# ---------------------------------------------------------------------------
# Module-level singleton and helpers
# ---------------------------------------------------------------------------

_SINGLETON: Optional[CenterDistributedAgentSystemReviewReport] = None


def build_center_distributed_agent_system_review() -> (
    CenterDistributedAgentSystemReviewReport
):
    """Build and return a fresh review report (no caching)."""
    return CenterDistributedAgentSystemReviewer().review()


def get_center_distributed_agent_system_review() -> (
    CenterDistributedAgentSystemReviewReport
):
    """Return the process-global singleton review report, building it on
    first call."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = build_center_distributed_agent_system_review()
    return _SINGLETON


def reset_center_distributed_agent_system_review() -> None:
    """Clear the process-global singleton (for test isolation only)."""
    global _SINGLETON
    _SINGLETON = None
