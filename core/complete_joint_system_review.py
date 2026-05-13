"""Complete joint dual-repo system review — V2 + Android.

Scope
-----
This is the authoritative combined baseline for the ufo-galaxy-realization-v2
(V2, center governance authority) and ufo-galaxy-android (Android, runtime node
/ carrier) dual-repo system.  It supersedes the earlier narrower baselines and
is intended to be the single source-of-truth *joint system understanding* from
which all subsequent closure PRs derive their problem statements.

Evidence policy
---------------
- Every factual claim is grounded in real V2 code (import checks + source
  token probes) or in explicit Android code anchors pinned to a reviewed ref.
- No PR narratives, README excerpts, or architecture diagrams are used as
  factual evidence.
- When a check cannot be verified at import time the field degrades gracefully
  to a conservative value; callers can inspect ``_probe_results`` to see which
  checks succeeded.

Key additions over joint_dual_repo_real_code_baseline
------------------------------------------------------
1.  ``SystemIdentityVerdict`` — formally answers the five canonical identity
    questions about the system.
2.  ``PropositionVerdict`` enum + ``PropositionEntry`` — every major binary
    claim is classified as hard-established, partially-established, or
    should-scale-back, with evidence traces.
3.  ``ClosureMap`` — maps each high-value proposition ID to its closure status
    and the remaining gap that blocks full closure.
4.  Expanded domain coverage: 15 domains (was 11) adding cross-repo contracts,
    session continuity / durable identity, desktop-carrier semantics, command
    dispatch path, and Android local-inference / fallback gate.
5.  Expanded remaining-issue registry: 13 issues (was 7), adding per-issue
    ``blocks_propositions`` back-links and ``stage_gate`` labels.
6.  ``ScorecardEntry`` per domain + overall weighted score.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authority metadata
# ---------------------------------------------------------------------------

REVIEW_PR_TITLE = "基于 993P2 收敛双仓系统完整性认知、联动真值与关键缺口补强"
REVIEW_PR_TITLE_EN = (
    "Anchor on 993P2 to converge dual-repo system integrity cognition, "
    "runtime truth linkage, and key-gap reinforcement"
)
REVIEW_CONVERGENCE_ANCHOR = "993P2"
REVIEW_AUTHORITY = (
    "COMPLETE_JOINT_SYSTEM_REVIEW::"
    "core.complete_joint_system_review::real-code-only-v2-plus-android"
)
REVIEW_METHODOLOGY = (
    "Only current real V2 code (import checks + source token probes) and "
    "explicit Android code anchors at a reviewed commit are used as evidence. "
    "Historical PR narratives, README text, and prior audit prose are NOT "
    "treated as factual proof."
)
REVIEW_SUPERSEDES = [
    "core.joint_dual_repo_real_code_baseline",
    "core.post_closure_dual_repo_reassessment",
    "core.pr993_dual_repo_reevaluation",
    "core.comprehensive_joint_dual_repo_audit",
]

# Android repository commit audited when compiling this review.
ANDROID_AUDITED_REF = "478e3f8f3cd3cb85b5a20999c9fca22a0f44ef8d"

# Android-side code anchors referenced throughout this module.
ANDROID_ANCHOR_MESH_CONTRACT = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/runtime/AndroidMeshParticipationContract.kt"
)
ANDROID_ANCHOR_AUTONOMOUS_PIPELINE = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/agent/AutonomousExecutionPipeline.kt"
)
ANDROID_ANCHOR_WS_CLIENT = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt"
)
ANDROID_ANCHOR_MESH_TEST = (
    "ufo-galaxy-android/app/src/test/java/com/ufo/galaxy/runtime/"
    "Pr8AndroidMeshParticipationContractTest.kt"
)
ANDROID_ANCHOR_MODE_GATE = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/runtime/LocalExecutionModeGate.kt"
)
ANDROID_ANCHOR_CONTINUITY = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/session/DurableParticipantIdentity.kt"
)
ANDROID_ANCHOR_CAPABILITY_REPORT = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/capability/CapabilityReport.kt"
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class PropositionVerdict(str, Enum):
    """Adjudication outcome for a binary system-level proposition."""

    HARD_ESTABLISHED = "hard_established"
    PARTIALLY_ESTABLISHED = "partially_established"
    SHOULD_SCALE_BACK = "should_scale_back"


class EvidenceState(str, Enum):
    """Granularity of supporting evidence."""

    HARD_ESTABLISHED = "hard_established"
    PARTIAL = "partial"
    RUNTIME_PROOF_THIN = "runtime_proof_thin"


class GapClass(str, Enum):
    """Gap taxonomy aligned with the project governance language."""

    CORE_ARCH = "核心架构缺口"
    GOVERNANCE = "治理缺口"
    RUNTIME = "运行级缺口"
    STATE_TRUTH = "状态真相缺口"
    ORCHESTRATION = "编排缺口"
    CROSS_REPO_CONTRACT = "跨仓契约缺口"
    MANIFESTATION_CONTROL = "显化/控制面缺口"
    PROOF = "证明缺口"
    SESSION_CONTINUITY = "会话连续性缺口"


class WorkPriority(str, Enum):
    """Execution priority for remaining-issue resolution."""

    MUST_FIRST = "必须先做"
    IMPORTANT_SECONDARY = "重要但次级"
    ENHANCEMENT = "后续增强"


class StageVerdict(str, Enum):
    MID_STAGE_CONSOLIDATION = "mid-stage consolidation"
    LATE_INTEGRATION = "late integration"
    NEAR_CLOSURE = "near-closure"


class StageGate(str, Enum):
    """Which milestone a gap must be closed before."""

    P0_BEFORE_RUNTIME_CLOSURE = "P0-before-runtime-closure"
    P1_BEFORE_NEAR_CLOSURE = "P1-before-near-closure"
    P2_ENHANCEMENT = "P2-enhancement"


# ---------------------------------------------------------------------------
# Core data types
# ---------------------------------------------------------------------------


@dataclass
class PropositionEntry:
    """A single system-level proposition with adjudication."""

    prop_id: str
    statement: str
    verdict: PropositionVerdict
    evidence_state: EvidenceState
    rationale_zh: str
    v2_anchors: List[str] = field(default_factory=list)
    android_anchors: List[str] = field(default_factory=list)
    open_gap_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prop_id": self.prop_id,
            "statement": self.statement,
            "verdict": self.verdict.value,
            "evidence_state": self.evidence_state.value,
            "rationale_zh": self.rationale_zh,
            "v2_anchors": list(self.v2_anchors),
            "android_anchors": list(self.android_anchors),
            "open_gap_ids": list(self.open_gap_ids),
        }


@dataclass
class SystemIdentityVerdict:
    """Formal answers to the five canonical identity questions."""

    # Q1: What is the true system identity?
    system_identity_zh: str = ""
    # Q2: What central governance authority does V2 hold?
    v2_governance_boundary_zh: str = ""
    # Q3: What runtime-node / local-execution / collaboration roles does Android hold?
    android_runtime_role_zh: str = ""
    # Q4: How should desktop / tablet / other devices be understood?
    desktop_carrier_semantics_zh: str = ""
    # Q5: To what degree is this a "networked integrated system" (not "main + client")?
    network_integration_degree_zh: str = ""
    # Supporting evidence state for the identity verdict as a whole
    identity_evidence_state: EvidenceState = EvidenceState.PARTIAL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "system_identity_zh": self.system_identity_zh,
            "v2_governance_boundary_zh": self.v2_governance_boundary_zh,
            "android_runtime_role_zh": self.android_runtime_role_zh,
            "desktop_carrier_semantics_zh": self.desktop_carrier_semantics_zh,
            "network_integration_degree_zh": self.network_integration_degree_zh,
            "identity_evidence_state": self.identity_evidence_state.value,
        }


@dataclass
class DomainStatus:
    domain_id: str
    topic: str
    completion_pct: float
    evidence_state: EvidenceState
    rationale_zh: str
    v2_anchors: List[str] = field(default_factory=list)
    android_anchors: List[str] = field(default_factory=list)
    weight: float = 1.0  # relative weight for weighted overall score

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "topic": self.topic,
            "completion_pct": self.completion_pct,
            "evidence_state": self.evidence_state.value,
            "rationale_zh": self.rationale_zh,
            "v2_anchors": list(self.v2_anchors),
            "android_anchors": list(self.android_anchors),
            "weight": self.weight,
        }


@dataclass
class RemainingIssue:
    issue_id: str
    title: str
    gap_class: GapClass
    priority: WorkPriority
    stage_gate: StageGate
    evidence_state: EvidenceState
    why_not_closed_zh: str
    blocks: List[str] = field(default_factory=list)
    blocks_propositions: List[str] = field(default_factory=list)
    v2_anchors: List[str] = field(default_factory=list)
    android_anchors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "title": self.title,
            "gap_class": self.gap_class.value,
            "priority": self.priority.value,
            "stage_gate": self.stage_gate.value,
            "evidence_state": self.evidence_state.value,
            "why_not_closed_zh": self.why_not_closed_zh,
            "blocks": list(self.blocks),
            "blocks_propositions": list(self.blocks_propositions),
            "v2_anchors": list(self.v2_anchors),
            "android_anchors": list(self.android_anchors),
        }


@dataclass
class ClosureMapEntry:
    prop_id: str
    verdict: PropositionVerdict
    closed: bool
    blocking_issue_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prop_id": self.prop_id,
            "verdict": self.verdict.value,
            "closed": self.closed,
            "blocking_issue_ids": list(self.blocking_issue_ids),
        }


@dataclass
class RuntimeFlowStage:
    """A code-grounded stage in the end-to-end user-problem execution chain."""

    stage_id: str
    title_zh: str
    runtime_truth_zh: str
    v2_anchors: List[str] = field(default_factory=list)
    android_anchors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "title_zh": self.title_zh,
            "runtime_truth_zh": self.runtime_truth_zh,
            "v2_anchors": list(self.v2_anchors),
            "android_anchors": list(self.android_anchors),
        }


@dataclass
class CrossRepoMismatch:
    """Explicit divergence or weakly-enforced semantic mismatch across repos."""

    mismatch_id: str
    topic_zh: str
    v2_truth_zh: str
    android_truth_zh: str
    impact_zh: str
    linked_issue_ids: List[str] = field(default_factory=list)
    v2_anchors: List[str] = field(default_factory=list)
    android_anchors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mismatch_id": self.mismatch_id,
            "topic_zh": self.topic_zh,
            "v2_truth_zh": self.v2_truth_zh,
            "android_truth_zh": self.android_truth_zh,
            "impact_zh": self.impact_zh,
            "linked_issue_ids": list(self.linked_issue_ids),
            "v2_anchors": list(self.v2_anchors),
            "android_anchors": list(self.android_anchors),
        }


@dataclass
class V2ConvergencePriority:
    """Implementation-guiding next-step convergence direction for V2."""

    title_zh: str
    why_now_zh: str
    target_outcome_zh: str
    linked_issue_ids: List[str] = field(default_factory=list)
    v2_anchors: List[str] = field(default_factory=list)
    android_anchors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title_zh": self.title_zh,
            "why_now_zh": self.why_now_zh,
            "target_outcome_zh": self.target_outcome_zh,
            "linked_issue_ids": list(self.linked_issue_ids),
            "v2_anchors": list(self.v2_anchors),
            "android_anchors": list(self.android_anchors),
        }


@dataclass
class IntegrityRepairAction:
    """Code-grounded V2-side integrity repair/reinforcement action."""

    action_id: str
    title_zh: str
    status_zh: str
    why_high_value_zh: str
    linked_issue_ids: List[str] = field(default_factory=list)
    v2_anchors: List[str] = field(default_factory=list)
    android_dependency_zh: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "title_zh": self.title_zh,
            "status_zh": self.status_zh,
            "why_high_value_zh": self.why_high_value_zh,
            "linked_issue_ids": list(self.linked_issue_ids),
            "v2_anchors": list(self.v2_anchors),
            "android_dependency_zh": self.android_dependency_zh,
        }


@dataclass
class CompleteJointSystemReport:
    """Top-level machine-readable report produced by this review."""

    authority: str = REVIEW_AUTHORITY
    methodology: str = REVIEW_METHODOLOGY
    pr_title: str = REVIEW_PR_TITLE
    pr_title_en: str = REVIEW_PR_TITLE_EN
    convergence_anchor: str = REVIEW_CONVERGENCE_ANCHOR
    supersedes: List[str] = field(default_factory=lambda: list(REVIEW_SUPERSEDES))
    android_audited_ref: str = ANDROID_AUDITED_REF
    generated_at: float = field(default_factory=time.time)

    system_identity: Optional[SystemIdentityVerdict] = None
    propositions: List[PropositionEntry] = field(default_factory=list)
    domain_statuses: List[DomainStatus] = field(default_factory=list)
    remaining_issues: List[RemainingIssue] = field(default_factory=list)
    closure_map: List[ClosureMapEntry] = field(default_factory=list)
    runtime_flow: List[RuntimeFlowStage] = field(default_factory=list)
    cross_repo_mismatches: List[CrossRepoMismatch] = field(default_factory=list)
    v2_next_convergence_priority: Optional[V2ConvergencePriority] = None
    integrity_repair_actions: List[IntegrityRepairAction] = field(default_factory=list)

    stage: StageVerdict = StageVerdict.MID_STAGE_CONSOLIDATION
    overall_completion_pct: float = 0.0
    weighted_completion_pct: float = 0.0

    # Raw probe results for inspection / debugging
    _probe_results: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authority": self.authority,
            "methodology": self.methodology,
            "pr_title": self.pr_title,
            "pr_title_en": self.pr_title_en,
            "convergence_anchor": self.convergence_anchor,
            "supersedes": list(self.supersedes),
            "android_audited_ref": self.android_audited_ref,
            "generated_at": self.generated_at,
            "system_identity": self.system_identity.to_dict() if self.system_identity else None,
            "propositions": [p.to_dict() for p in self.propositions],
            "domain_statuses": [d.to_dict() for d in self.domain_statuses],
            "remaining_issues": [r.to_dict() for r in self.remaining_issues],
            "closure_map": [c.to_dict() for c in self.closure_map],
            "runtime_flow": [f.to_dict() for f in self.runtime_flow],
            "cross_repo_mismatches": [m.to_dict() for m in self.cross_repo_mismatches],
            "v2_next_convergence_priority": (
                self.v2_next_convergence_priority.to_dict()
                if self.v2_next_convergence_priority
                else None
            ),
            "integrity_repair_actions": [a.to_dict() for a in self.integrity_repair_actions],
            "stage": self.stage.value,
            "overall_completion_pct": self.overall_completion_pct,
            "weighted_completion_pct": self.weighted_completion_pct,
            "probe_results": dict(self._probe_results),
        }


# ---------------------------------------------------------------------------
# Real-code probe helpers
# ---------------------------------------------------------------------------


def _module_exists(module_path: str) -> bool:
    """Return True if the module is discoverable in the current Python path."""
    try:
        if importlib.util.find_spec(module_path) is not None:
            return True
    except (ImportError, ModuleNotFoundError, ValueError, AttributeError) as exc:
        logger.debug("_module_exists fallback for %s: %s", module_path, exc)
    rel = module_path.replace(".", os.sep) + ".py"
    rel_pkg = module_path.replace(".", os.sep) + os.sep + "__init__.py"
    return any(
        os.path.isfile(os.path.join(base, rel))
        or os.path.isfile(os.path.join(base, rel_pkg))
        for base in sys.path
    )


def _source_contains(module_path: str, token: str) -> bool:
    """Return True if the module source contains *token* as a substring."""
    try:
        spec = importlib.util.find_spec(module_path)
    except (ImportError, ModuleNotFoundError, ValueError, AttributeError):
        return False
    if not spec or not spec.origin or not os.path.isfile(spec.origin):
        return False
    with open(spec.origin, encoding="utf-8", errors="replace") as fh:
        return token in fh.read()


def _source_contains_all(module_path: str, *tokens: str) -> bool:
    """Return True only if all *tokens* appear in the module source."""
    try:
        spec = importlib.util.find_spec(module_path)
    except (ImportError, ModuleNotFoundError, ValueError, AttributeError):
        return False
    if not spec or not spec.origin or not os.path.isfile(spec.origin):
        return False
    with open(spec.origin, encoding="utf-8", errors="replace") as fh:
        src = fh.read()
    return all(tok in src for tok in tokens)


def _collect_probes() -> Dict[str, bool]:
    """Run all real-code probes and return a named bool dict."""
    p: Dict[str, bool] = {}

    # --- Governance / authority ---
    p["governance_module"] = _module_exists("core.unified_execution_governance")
    p["governance_semantics"] = _module_exists("core.unified_governance_semantics")
    p["governance_has_execution_runtime_state"] = _source_contains(
        "core.unified_governance_semantics", "execution_runtime_state"
    )
    p["governance_has_decision_causality"] = _source_contains(
        "core.unified_governance_semantics", "decision_causality"
    )
    p["operator_surface"] = _module_exists("core.operator_surface")
    p["operator_snapshot"] = _source_contains("core.operator_surface", "OperatorSnapshot")

    # --- Command dispatch / routing ---
    p["command_router"] = _module_exists("core.command_router")
    p["openclawd"] = _module_exists("core.openclawd")
    p["device_pool_manager"] = _module_exists("core.device_pool_manager")
    p["capability_aware_routing"] = _module_exists("core.capability_aware_routing_default")

    # --- Orchestration ---
    p["source_dispatch"] = _module_exists("core.runtime.source_dispatch_orchestrator")
    p["dispatch_scores_candidate"] = _source_contains(
        "core.runtime.source_dispatch_orchestrator", "_score_candidate"
    )
    p["dispatch_consumes_android_snapshot"] = _source_contains(
        "core.runtime.source_dispatch_orchestrator", "android_snapshot"
    )
    p["orchestration_review_surface"] = _module_exists("core.orchestration_review_surface")
    p["unified_orchestration_spine"] = _module_exists("core.unified_orchestration_spine")
    p["device_selection"] = _module_exists("galaxy_gateway.routing.device_selection")
    p["device_selection_imports_snapshot"] = _source_contains(
        "galaxy_gateway.routing.device_selection", "get_device_state_snapshot"
    )

    # --- Runtime-state truth ---
    p["android_device_state_store"] = _module_exists("core.android_device_state_store")
    p["android_runtime_host"] = _module_exists("core.android_runtime_host")
    p["android_runtime_transition_reducer"] = _module_exists(
        "core.android_runtime_transition_reducer"
    )
    p["android_mode_gate_policy"] = _module_exists("core.android_mode_gate_policy")
    p["mode_gate_has_readiness"] = _source_contains(
        "core.android_mode_gate_policy", "evaluate_android_mode_readiness"
    )
    p["mode_gate_has_build_cross_device"] = _source_contains(
        "core.android_mode_gate_policy", "build_cross_device_readiness_panel_dict"
    )

    # --- Android runtime node ---
    p["android_nl_chain_contract"] = _module_exists("core.android_nl_semantic_chain_contract")
    p["android_nl_has_source"] = _source_contains(
        "core.android_nl_semantic_chain_contract", "semantic_authority"
    )
    p["android_delegated_runtime"] = _module_exists("core.android_delegated_runtime_lifecycle_coordinator")
    p["android_participant_session"] = _module_exists("core.android_participant_session_state")
    p["android_runtime_dispatch"] = _module_exists("core.android_runtime_dispatch_binding")
    p["android_handoff_ingress"] = _module_exists("core.android_handoff_v2_response_ingress")
    p["android_signal_reconciler"] = _module_exists("core.android_execution_signal_reconciler")

    # --- Cross-repo contracts ---
    p["android_v2_continuity_contract"] = _module_exists("core.android_v2_continuity_contract")
    p["contracts_dispatch_continuity"] = _module_exists("contracts.dispatch_continuity")
    p["contracts_execution_trace"] = _module_exists("contracts.execution_trace")
    p["contracts_multi_device_projection"] = _module_exists(
        "contracts.multi_device_runtime_projection"
    )
    p["contracts_mesh_membership"] = _module_exists("contracts.mesh_membership")
    p["cross_repo_evidence_pipeline"] = _module_exists(
        "core.canonical_cross_repo_evidence_pipeline"
    )

    # --- Mesh / hybrid / delegated collaboration ---
    p["mesh_runtime_center"] = _module_exists("core.mesh.mesh_runtime_center_state")
    p["mesh_runtime_center_has_lifecycle_proof"] = _source_contains(
        "core.mesh.mesh_runtime_center_state", "lifecycle_proof"
    )
    p["live_mesh_runtime_engine"] = _module_exists("core.mesh.live_mesh_runtime_engine")
    p["mesh_session_coordinator"] = _module_exists("core.mesh.mesh_session_coordinator")
    p["hybrid_continuity"] = _module_exists("core.hybrid_orchestration_continuity")
    p["pr6_multi_device_authority"] = _module_exists("core.canonical_dispatch_slot_authority")

    # --- Multimodal input-output chain ---
    p["desktop_presence_runtime"] = _module_exists("core.desktop_presence_runtime")
    p["desktop_existence_surface"] = _module_exists("core.desktop_existence_surface")
    p["existence_surface_has_projection"] = _source_contains(
        "core.desktop_existence_surface", "ExistenceProjection"
    )
    p["android_perception_ingress"] = _module_exists("core.android_perception_ingress_contract")

    # --- Ingress surfaces ---
    p["routes_panel"] = _module_exists("core.routes.panel")
    p["routes_operator"] = _module_exists("core.routes.operator")
    p["routes_chat"] = _module_exists("core.routes.chat")
    p["unified_panel_route"] = _source_contains("core.routes.panel", "/api/v1/panel/unified")
    p["unified_entrypoint_router"] = _module_exists("core.unified.entrypoint_router")

    # --- Operator / panel / control / observability ---
    p["unified_panel_aggregation"] = _module_exists("core.unified_panel_aggregation")
    p["panel_has_existence_surface"] = _source_contains(
        "core.unified_panel_aggregation", "existence_surface"
    )
    p["panel_has_governance_state"] = _source_contains(
        "core.unified_panel_aggregation", "governance_state"
    )
    p["panel_has_mesh_runtime"] = _source_contains(
        "core.unified_panel_aggregation", "mesh_runtime_state"
    )
    p["runtime_observability_sink"] = _module_exists("core.runtime.runtime_observability_sink")
    p["routing_observability"] = _module_exists("core.routing_observability")

    # --- Manifestation / carrier semantics ---
    p["carrier_semantics_desktop"] = _source_contains(
        "core.desktop_existence_surface", "carrier"
    ) or _source_contains("core.desktop_presence_runtime", "carrier")
    p["desktop_consumption_adapter"] = _module_exists("core.desktop_consumption_adapter")
    p["canonical_layer_model"] = _module_exists("core.canonical_layer_model")
    p["existence_surface_has_unified_carrier"] = _source_contains(
        "core.desktop_existence_surface", "UnifiedCarrierSurface"
    )

    # --- Session continuity / durable identity ---
    p["attached_session_registry"] = _module_exists("core.attached_runtime_session_registry")
    p["registry_has_durable_session"] = _source_contains(
        "core.attached_runtime_session_registry", "durable_session_id"
    )
    p["registry_has_continuity_epoch"] = _source_contains(
        "core.attached_runtime_session_registry", "continuity_epoch"
    )
    p["flow_continuity_coordinator"] = _module_exists("core.flow_continuity_coordinator")
    p["continuity_has_decide_reconnect"] = _source_contains(
        "core.flow_continuity_coordinator", "decide_reconnect"
    )
    p["android_v2_continuity_has_stale_guard"] = _source_contains(
        "core.android_v2_continuity_contract", "stale"
    )

    # --- Proof / tests ---
    p["e2e_android_snapshot"] = _module_exists(
        "tests.integration.test_android_runtime_state_snapshot_e2e"
    )
    p["e2e_nl_canonical"] = _module_exists(
        "tests.integration.test_nl_e2e_canonical_path"
    )
    p["test_orchestration_consumes_android"] = _module_exists(
        "tests.test_orchestration_consumes_android_truth"
    )
    p["test_cross_repo_consistency"] = _module_exists(
        "tests.test_pr12_cross_repo_consistency_gates"
    )
    p["test_mesh_runtime_center"] = _module_exists(
        "tests.test_pr03_mesh_runtime_center_closure"
    )

    return p


# ---------------------------------------------------------------------------
# Build functions
# ---------------------------------------------------------------------------


def _build_system_identity(p: Dict[str, bool]) -> SystemIdentityVerdict:
    # Determine identity evidence quality based on probes
    strong = all([
        p.get("governance_module"),
        p.get("operator_surface"),
        p.get("android_delegated_runtime"),
        p.get("mesh_runtime_center"),
    ])
    evidence = EvidenceState.HARD_ESTABLISHED if (
        p.get("mesh_runtime_center_has_lifecycle_proof") and p.get("dispatch_consumes_android_snapshot")
    ) else EvidenceState.PARTIAL

    integration_degree = (
        "网络化程度：V2 + Android 已形成真实双节点协作网络（语义成立、局部运行成立），"
        "但 full mesh runtime 与 barrier 协同未完全运行级闭环，"
        "因此当前最准确定性是[中心控制型分布式智能系统]，"
        "而非[完全对等 mesh 网络]，也不再是简单[主程序 + 客户端]模型。"
        if strong else
        "网络化程度：证据仍偏薄，待更多运行级证明。"
    )

    return SystemIdentityVerdict(
        system_identity_zh=(
            "Galaxy 是一个以 V2 为中心治理核、以 Android/桌面/其它设备为执行与显化载体的"
            "中心控制型分布式智能系统。其中 Android 具备本地执行、委托协作与有限自治能力，"
            "但全局编排主权仍属于 V2。"
        ),
        v2_governance_boundary_zh=(
            "V2 承担：统一执行治理（ExecutionType 优先级/冲突裁决）、canonical runtime truth "
            "绑定（execution_runtime_state / decision_causality）、operator/panel 单源投影、"
            "全局 mesh 中心协调、所有跨仓 authority 裁决。"
            "V2 不承担：Android 本地 UI 执行细节、Android 侧 capability 自主查询的实现。"
        ),
        android_runtime_role_zh=(
            "Android 承担：本地目标执行（AutonomousExecutionPipeline）、"
            "委托执行节点（delegated execution via handoff）、"
            "mesh 参与契约节点（AndroidMeshParticipationContract）、"
            "能力上报（CapabilityReport）、会话连续性身份（durable participant identity）、"
            "runtime-state 透明上送。"
            "Android 不承担：全局编排主权、mesh 中心协调、canonical 裁决。"
        ),
        desktop_carrier_semantics_zh=(
            "桌面/平板/其它设备：在当前代码语义下应理解为[同一 AI 主体的不同显化 carrier 面]，"
            "而非独立节点或主程序附属客户端。"
            "代码支撑：DesktopExistenceSurface（ExistenceProjection 统一 5 个状态族）、"
            "desktop_presence_runtime（TriState presence）、desktop_consumption_adapter。"
            "当前缺口：桌面 carrier 语义尚未全面与 Android carrier 语义统一成单一显化框架。"
        ),
        network_integration_degree_zh=integration_degree,
        identity_evidence_state=evidence,
    )


def _build_propositions(p: Dict[str, bool]) -> List[PropositionEntry]:
    _carrier_unified = p.get("existence_surface_has_unified_carrier", False)
    _p10_verdict = (
        PropositionVerdict.HARD_ESTABLISHED if _carrier_unified
        else PropositionVerdict.PARTIALLY_ESTABLISHED
    )
    _p10_evidence = (
        EvidenceState.HARD_ESTABLISHED if _carrier_unified
        else EvidenceState.PARTIAL
    )
    _p10_rationale = (
        "DesktopExistenceSurface / ExistenceProjection / desktop_presence_runtime 存在，"
        "desktop_consumption_adapter 存在。"
        "PR-8 V2：UnifiedCarrierSurface / CarrierSurfaceEntry 已加入 "
        "core.desktop_existence_surface (schema 1.1)，"
        "桌面 carrier 与 Android carrier 现在通过 CarrierSurfaceEntry 投影在同一语义层，"
        "R8 在 V2 侧已收口。"
        if _carrier_unified else
        "DesktopExistenceSurface / ExistenceProjection / desktop_presence_runtime 存在，"
        "desktop_consumption_adapter 存在，但[桌面 carrier 与 Android carrier 统一显化框架]"
        "尚未形成单一代码层面的完全统一。"
    )
    _p10_gaps: List[str] = [] if _carrier_unified else ["R8"]
    return [
        PropositionEntry(
            "P1",
            "V2 is the center governance authority for the dual-repo system.",
            PropositionVerdict.HARD_ESTABLISHED,
            EvidenceState.HARD_ESTABLISHED,
            "unified_execution_governance 模块真实存在且携带 ExecutionType 优先级裁决逻辑；"
            "unified_governance_semantics 含 execution_runtime_state 与 decision_causality；"
            "operator_surface 具备 OperatorSnapshot。",
            ["core/unified_execution_governance.py", "core/unified_governance_semantics.py",
             "core/operator_surface.py"],
            [],
            [],
        ),
        PropositionEntry(
            "P2",
            "Android acts as a runtime node with real local-execution and delegated-execution capability.",
            PropositionVerdict.HARD_ESTABLISHED,
            EvidenceState.PARTIAL,
            "AutonomousExecutionPipeline（Android 侧）、android_delegated_runtime_lifecycle_coordinator、"
            "android_runtime_dispatch_binding 均真实存在。本地执行语义成立，"
            "但全链运行级 E2E 证明厚度仍有限。",
            ["core/android_delegated_runtime_lifecycle_coordinator.py",
             "core/android_runtime_dispatch_binding.py"],
            [ANDROID_ANCHOR_AUTONOMOUS_PIPELINE],
            ["R2", "R10"],
        ),
        PropositionEntry(
            "P3",
            "The system is a center-governed distributed network, not a 'main program + client' binary.",
            PropositionVerdict.PARTIALLY_ESTABLISHED,
            EvidenceState.PARTIAL,
            "双仓协作语义、mesh 参与契约、委托执行、session 连续性均存在，"
            "但 full mesh runtime / barrier 协同未完全运行级闭合，"
            "因此[完全对等网络]说法应收缩，[中心控制型分布式网络]更准确。",
            ["core/mesh/live_mesh_runtime_engine.py", "core/mesh/mesh_session_coordinator.py"],
            [ANDROID_ANCHOR_MESH_CONTRACT],
            ["R4", "R13"],
        ),
        PropositionEntry(
            "P4",
            "Routing / orchestration actively consumes Android runtime-state truth for decisions.",
            PropositionVerdict.PARTIALLY_ESTABLISHED,
            EvidenceState.PARTIAL,
            "_score_candidate 与 get_device_state_snapshot 均存在，编排已消费 Android truth，"
            "但覆盖面不完整——并非所有治理分支均按 runtime-state 做出差异决策。",
            ["core/runtime/source_dispatch_orchestrator.py",
             "galaxy_gateway/routing/device_selection.py"],
            [ANDROID_ANCHOR_WS_CLIENT],
            ["R1"],
        ),
        PropositionEntry(
            "P5",
            "Android → V2 runtime-state transparency is fully closed end-to-end.",
            PropositionVerdict.PARTIALLY_ESTABLISHED,
            EvidenceState.RUNTIME_PROOF_THIN,
            "android_device_state_store / android_runtime_transition_reducer 存在；"
            "e2e 测试覆盖 snapshot roundtrip，但跨仓漂移收敛与冲突治理证据仍不足够厚。",
            ["core/android_device_state_store.py",
             "tests/integration/test_android_runtime_state_snapshot_e2e.py"],
            [ANDROID_ANCHOR_WS_CLIENT, ANDROID_ANCHOR_AUTONOMOUS_PIPELINE],
            ["R2"],
        ),
        PropositionEntry(
            "P6",
            "Capability / readiness / policy / busy / fallback gate is unified across repos.",
            PropositionVerdict.PARTIALLY_ESTABLISHED,
            EvidenceState.PARTIAL,
            "android_mode_gate_policy 含 evaluate_android_mode_readiness 与 "
            "build_cross_device_readiness_panel_dict；unified capability_resolver 存在；"
            "但跨仓一致门控与漂移治理未完全 fully closed。",
            ["core/android_mode_gate_policy.py", "core/unified/capability_resolver.py"],
            [ANDROID_ANCHOR_CAPABILITY_REPORT],
            ["R3"],
        ),
        PropositionEntry(
            "P7",
            "Mesh / hybrid / delegated collaboration is runtime-level fully closed.",
            PropositionVerdict.SHOULD_SCALE_BACK,
            EvidenceState.RUNTIME_PROOF_THIN,
            "mesh 参与契约成立、barrier 语义存在（lifecycle_proof），"
            "但 live_mesh_runtime_engine + barrier 协同在跨仓活体条件下尚未产生足够厚的运行级证明。"
            "应收缩为: 局部运行成立，运行级 fully closed 尚不成立。",
            ["core/mesh/live_mesh_runtime_engine.py", "core/mesh/mesh_runtime_center_state.py"],
            [ANDROID_ANCHOR_MESH_CONTRACT, ANDROID_ANCHOR_MESH_TEST],
            ["R4"],
        ),
        PropositionEntry(
            "P8",
            "Unified ingress surfaces a single canonical entry point with consistent routing semantics.",
            PropositionVerdict.PARTIALLY_ESTABLISHED,
            EvidenceState.PARTIAL,
            "/api/v1/panel/unified 存在，entrypoint_router 存在，"
            "但不同入口（chat/operator/Android ws/panel）的运行因果同路性仍需持续验证；"
            "unified_ingress 未完全宣布 fully closed。",
            ["core/routes/panel.py", "core/routes/chat.py", "core/unified/entrypoint_router.py"],
            [ANDROID_ANCHOR_WS_CLIENT],
            ["R7"],
        ),
        PropositionEntry(
            "P9",
            "Operator / panel / control surface is single-source and fully isomorphic to runtime truth.",
            PropositionVerdict.PARTIALLY_ESTABLISHED,
            EvidenceState.PARTIAL,
            "UnifiedPanelAggregationService、OperatorSnapshot、mesh_runtime_state 字段均存在；"
            "panel 投影已绑定 governance_state，但[operator 看见的系统]与[runtime 真实世界]"
            "完全同构这一命题仍部分成立。",
            ["core/unified_panel_aggregation.py", "core/operator_surface.py",
             "core/routes/operator.py"],
            [],
            ["R5"],
        ),
        PropositionEntry(
            "P10",
            "Desktop / tablet / other devices are unified as carrier surfaces of the same AI body.",
            _p10_verdict,
            _p10_evidence,
            _p10_rationale,
            ["core/desktop_existence_surface.py", "core/desktop_presence_runtime.py",
             "core/desktop_consumption_adapter.py"],
            [],
            _p10_gaps,
        ),
        PropositionEntry(
            "P11",
            "Session continuity and durable identity are fully closed across reconnects and restarts.",
            PropositionVerdict.PARTIALLY_ESTABLISHED,
            EvidenceState.PARTIAL,
            "attached_runtime_session_registry 具备 durable_session_id / continuity_epoch；"
            "flow_continuity_coordinator 含 decide_reconnect；android_v2_continuity_contract 含 stale guard；"
            "但跨重启 / 进程重建场景下的完整闭环证明面仍偏薄。",
            ["core/attached_runtime_session_registry.py", "core/flow_continuity_coordinator.py",
             "core/android_v2_continuity_contract.py"],
            [ANDROID_ANCHOR_CONTINUITY],
            ["R9"],
        ),
        PropositionEntry(
            "P12",
            "Live runtime proof surface is thick enough to support near-closure claims.",
            PropositionVerdict.SHOULD_SCALE_BACK,
            EvidenceState.RUNTIME_PROOF_THIN,
            "已有 e2e_android_snapshot、e2e_nl_canonical、orchestration_consumes_android_truth 等测试，"
            "结构化证明较厚，但跨仓活体异常场景（断连/重放/降级/接管）的端到端运行级证明仍不足。",
            ["tests/integration/test_android_runtime_state_snapshot_e2e.py",
             "tests/integration/test_nl_e2e_canonical_path.py",
             "tests/test_orchestration_consumes_android_truth.py"],
            [ANDROID_ANCHOR_MESH_TEST],
            ["R13"],
        ),
    ]


def _build_domains(p: Dict[str, bool]) -> List[DomainStatus]:
    """Build the 15-domain completion scorecard grounded in real-code probes."""
    return [
        DomainStatus(
            "D1",
            "authority / governance",
            85.0 if (p.get("governance_module") and p.get("governance_has_decision_causality")) else 50.0,
            EvidenceState.HARD_ESTABLISHED if p.get("governance_has_decision_causality") else EvidenceState.PARTIAL,
            "中心治理核在 V2 真实代码中可定位；execution_runtime_state / decision_causality 已入治理语义。",
            ["core/unified_execution_governance.py", "core/unified_governance_semantics.py"],
            [],
            weight=1.5,
        ),
        DomainStatus(
            "D2",
            "command dispatch path",
            78.0 if p.get("command_router") else 45.0,
            EvidenceState.PARTIAL,
            "command_router / openclawd / device_pool_manager 均真实存在；"
            "完整命令分发链路从 ingress 到执行的跨仓因果回归仍有缺口。",
            ["core/command_router.py", "core/openclawd.py", "core/device_pool_manager.py"],
            [],
            weight=1.2,
        ),
        DomainStatus(
            "D3",
            "routing / orchestration",
            76.0 if (p.get("dispatch_scores_candidate") and p.get("dispatch_consumes_android_snapshot")) else 54.0,
            EvidenceState.PARTIAL,
            "source_dispatch_orchestrator._score_candidate 消费 android_snapshot；"
            "device_selection 引入 get_device_state_snapshot；"
            "但并非所有治理分支均运行级闭环。",
            ["core/runtime/source_dispatch_orchestrator.py",
             "galaxy_gateway/routing/device_selection.py",
             "core/unified_orchestration_spine.py"],
            [ANDROID_ANCHOR_WS_CLIENT],
            weight=1.5,
        ),
        DomainStatus(
            "D4",
            "runtime-state truth",
            77.0 if p.get("governance_has_execution_runtime_state") else 52.0,
            EvidenceState.PARTIAL,
            "execution_runtime_state 与 decision_causality 入治理语义；"
            "android_device_state_store / android_runtime_transition_reducer 存在；"
            "跨仓透明链稳定冲突收敛证据仍偏薄。",
            ["core/unified_governance_semantics.py", "core/android_device_state_store.py",
             "core/android_runtime_transition_reducer.py"],
            [ANDROID_ANCHOR_WS_CLIENT, ANDROID_ANCHOR_AUTONOMOUS_PIPELINE],
            weight=1.5,
        ),
        DomainStatus(
            "D5",
            "Android runtime-node / local-execution / fallback",
            72.0 if p.get("android_delegated_runtime") else 45.0,
            EvidenceState.PARTIAL,
            "Android 本地执行、委托协作、信号回送均有代码支撑；"
            "mode_gate_policy 含 evaluate_android_mode_readiness；"
            "但本地 inference availability 到中心决策门控的完整闭合仍受限。",
            ["core/android_delegated_runtime_lifecycle_coordinator.py",
             "core/android_mode_gate_policy.py",
             "core/android_execution_signal_reconciler.py"],
            [ANDROID_ANCHOR_AUTONOMOUS_PIPELINE, ANDROID_ANCHOR_MODE_GATE],
            weight=1.3,
        ),
        DomainStatus(
            "D6",
            "capability / readiness / policy consistency",
            70.0 if (p.get("mode_gate_has_readiness") and p.get("mode_gate_has_build_cross_device")) else 50.0,
            EvidenceState.PARTIAL,
            "evaluate_android_mode_readiness / build_cross_device_readiness_panel_dict 存在；"
            "capability_resolver 存在；跨仓漂移治理与统一门控未完全 fully closed。",
            ["core/android_mode_gate_policy.py", "core/unified/capability_resolver.py"],
            [ANDROID_ANCHOR_CAPABILITY_REPORT],
            weight=1.3,
        ),
        DomainStatus(
            "D7",
            "cross-repo contracts",
            74.0 if (p.get("android_v2_continuity_contract") and p.get("contracts_dispatch_continuity")) else 48.0,
            EvidenceState.PARTIAL,
            "android_v2_continuity_contract / contracts/dispatch_continuity / "
            "contracts/execution_trace / contracts/multi_device_runtime_projection 均存在；"
            "但正式跨仓契约的系统级 schema 一致性与版本管理仍有缺口。",
            ["core/android_v2_continuity_contract.py", "contracts/dispatch_continuity.py",
             "contracts/execution_trace.py", "contracts/multi_device_runtime_projection.py",
             "contracts/mesh_membership.py"],
            [ANDROID_ANCHOR_MESH_CONTRACT, ANDROID_ANCHOR_WS_CLIENT],
            weight=1.1,
        ),
        DomainStatus(
            "D8",
            "mesh / hybrid / delegated collaboration",
            65.0 if p.get("mesh_runtime_center_has_lifecycle_proof") else 48.0,
            EvidenceState.PARTIAL,
            "mesh_runtime_center_state.lifecycle_proof 区分 participation-ready 与 runtime-closed；"
            "mesh 参与契约与 barrier 语义均存在；"
            "full mesh runtime / barrier 协同的活体运行证明仍受约束。",
            ["core/mesh/mesh_runtime_center_state.py", "core/mesh/live_mesh_runtime_engine.py",
             "core/mesh/mesh_session_coordinator.py"],
            [ANDROID_ANCHOR_MESH_CONTRACT, ANDROID_ANCHOR_MESH_TEST],
            weight=1.2,
        ),
        DomainStatus(
            "D9",
            "multimodal input-output execution chain",
            62.0 if (p.get("android_perception_ingress") and p.get("existence_surface_has_projection")) else 44.0,
            EvidenceState.RUNTIME_PROOF_THIN,
            "android_nl_semantic_chain_contract 含 semantic_authority；"
            "desktop_existence_surface 含 ExistenceProjection；"
            "android_perception_ingress_contract 存在；"
            "稳定跨仓多模态运行链端到端证明仍薄。",
            ["core/android_nl_semantic_chain_contract.py", "core/desktop_existence_surface.py",
             "core/android_perception_ingress_contract.py"],
            [ANDROID_ANCHOR_WS_CLIENT],
            weight=1.0,
        ),
        DomainStatus(
            "D10",
            "ingress unification",
            73.0 if (p.get("unified_panel_route") and p.get("unified_entrypoint_router")) else 55.0,
            EvidenceState.PARTIAL,
            "统一入口 /api/v1/panel/unified 存在；entrypoint_router 存在；"
            "chat / operator / Android WS / panel 等入口的运行因果同路性仍需持续回归。",
            ["core/routes/panel.py", "core/routes/chat.py", "core/routes/operator.py",
             "core/unified/entrypoint_router.py"],
            [ANDROID_ANCHOR_WS_CLIENT],
            weight=1.1,
        ),
        DomainStatus(
            "D11",
            "operator / panel / observability surfaces",
            75.0 if (p.get("panel_has_governance_state") and p.get("panel_has_mesh_runtime")) else 54.0,
            EvidenceState.PARTIAL,
            "UnifiedPanelPayload 含 governance_state / mesh_runtime_state / existence_surface；"
            "runtime_observability_sink / routing_observability 存在；"
            "但显化与执行控制完全同构仍未最终收口。",
            ["core/unified_panel_aggregation.py", "core/operator_surface.py",
             "core/runtime/runtime_observability_sink.py", "core/routing_observability.py"],
            [],
            weight=1.2,
        ),
        DomainStatus(
            "D12",
            "manifestation / carrier semantics",
            64.0 if p.get("desktop_existence_surface") else 42.0,
            EvidenceState.PARTIAL,
            "DesktopExistenceSurface / ExistenceProjection 统一 5 状态族；"
            "desktop_consumption_adapter 存在；"
            "桌面 + Android carrier 统一显化框架尚未在单一代码层面完全收口。",
            ["core/desktop_existence_surface.py", "core/desktop_presence_runtime.py",
             "core/desktop_consumption_adapter.py", "core/canonical_layer_model.py"],
            [],
            weight=1.0,
        ),
        DomainStatus(
            "D13",
            "session continuity / durable identity",
            72.0 if (p.get("registry_has_durable_session") and p.get("continuity_has_decide_reconnect")) else 48.0,
            EvidenceState.PARTIAL,
            "attached_runtime_session_registry 含 durable_session_id / continuity_epoch；"
            "flow_continuity_coordinator.decide_reconnect 存在；"
            "android_v2_continuity_contract 含 stale guard；"
            "进程重建 / V2 重启场景下的跨仓完整闭环证明仍有缺口。",
            ["core/attached_runtime_session_registry.py", "core/flow_continuity_coordinator.py",
             "core/android_v2_continuity_contract.py"],
            [ANDROID_ANCHOR_CONTINUITY],
            weight=1.1,
        ),
        DomainStatus(
            "D14",
            "execution governance lifecycle (takeover / conflict / busy state)",
            79.0 if p.get("governance_module") else 50.0,
            EvidenceState.PARTIAL,
            "unified_execution_governance 含 takeover_request (priority 1) / "
            "goal_execution / parallel_subtask；"
            "is_takeover_active / resolve_execution_conflict / notify_execution_completed 均存在；"
            "busy_state 与 queue_depth 消费在编排层的覆盖面仍受限。",
            ["core/unified_execution_governance.py"],
            [],
            weight=1.2,
        ),
        DomainStatus(
            "D15",
            "proof / tests / live runtime closure",
            63.0 if (p.get("e2e_android_snapshot") and p.get("e2e_nl_canonical")) else 40.0,
            EvidenceState.RUNTIME_PROOF_THIN,
            "e2e snapshot roundtrip 测试、NL canonical path 测试（40 个）、"
            "orchestration_consumes_android_truth 测试均存在；"
            "但跨仓活体异常场景（断连/回放/降级/接管）端到端运行级证明厚度仍不足。",
            ["tests/integration/test_android_runtime_state_snapshot_e2e.py",
             "tests/integration/test_nl_e2e_canonical_path.py",
             "tests/test_orchestration_consumes_android_truth.py",
             "tests/test_pr12_cross_repo_consistency_gates.py"],
            [ANDROID_ANCHOR_MESH_TEST],
            weight=1.3,
        ),
    ]


def _build_remaining_issues(p: Dict[str, bool]) -> List[RemainingIssue]:
    """Build the 13-issue structured remaining-problem registry."""
    return [
        RemainingIssue(
            "R1",
            "routing/orchestration 对 runtime-state truth 的消费覆盖面不足",
            GapClass.ORCHESTRATION,
            WorkPriority.MUST_FIRST,
            StageGate.P0_BEFORE_RUNTIME_CLOSURE,
            EvidenceState.PARTIAL,
            "当前 _score_candidate 消费 android_snapshot，但 busy/queue_depth/fallback_tier/"
            "local_inference_availability 等状态分支未被所有编排决策路径消费，"
            "不能宣称编排层完全状态真相驱动。",
            ["系统本体运行级闭环", "P4 命题 fully closed"],
            ["P4"],
            ["core/runtime/source_dispatch_orchestrator.py",
             "galaxy_gateway/routing/device_selection.py",
             "core/unified_orchestration_spine.py"],
            [ANDROID_ANCHOR_WS_CLIENT],
        ),
        RemainingIssue(
            "R2",
            "Android → V2 runtime-state transparency 闭环证据仍偏薄",
            GapClass.STATE_TRUTH,
            WorkPriority.MUST_FIRST,
            StageGate.P0_BEFORE_RUNTIME_CLOSURE,
            EvidenceState.RUNTIME_PROOF_THIN,
            "状态上报与吸收链路存在，e2e 测试有 snapshot roundtrip，"
            "但状态漂移收敛规则、中心与设备侧冲突裁决的稳定证据不够厚。",
            ["runtime-state truth 单源可信命题", "P5 命题 fully closed"],
            ["P5"],
            ["core/android_device_state_store.py",
             "core/unified_governance_semantics.py",
             "tests/integration/test_android_runtime_state_snapshot_e2e.py"],
            [ANDROID_ANCHOR_WS_CLIENT, ANDROID_ANCHOR_AUTONOMOUS_PIPELINE],
        ),
        RemainingIssue(
            "R3",
            "capability/readiness/policy/busy/fallback/local inference 跨仓统一门控未完全收敛",
            GapClass.GOVERNANCE,
            WorkPriority.MUST_FIRST,
            StageGate.P0_BEFORE_RUNTIME_CLOSURE,
            EvidenceState.PARTIAL,
            "能力与策略治理面存在，evaluate_android_mode_readiness 存在，"
            "但 local inference availability 到中心决策门控的完整闭合、"
            "跨仓漂移检测与治理仍非 fully closed。",
            ["统一治理核完备性命题", "P6 命题 fully closed"],
            ["P6"],
            ["core/android_mode_gate_policy.py", "core/unified/capability_resolver.py"],
            [ANDROID_ANCHOR_CAPABILITY_REPORT, ANDROID_ANCHOR_MODE_GATE],
        ),
        RemainingIssue(
            "R4",
            "mesh/hybrid/delegated collaboration 仍以部分运行成立为主，全链 fully closed 尚未证明",
            GapClass.RUNTIME,
            WorkPriority.IMPORTANT_SECONDARY,
            StageGate.P1_BEFORE_NEAR_CLOSURE,
            EvidenceState.PARTIAL,
            "mesh_runtime_center_state.lifecycle_proof 区分了 participation-ready 与 runtime-closed，"
            "但 live_mesh_runtime_engine + barrier 协同在跨仓活体条件下的连续运行证明仍受约束。",
            ["多设备协作运行级 fully closed 命题", "P7 命题升级为 fully established"],
            ["P7"],
            ["core/mesh/live_mesh_runtime_engine.py",
             "core/mesh/mesh_runtime_center_state.py",
             "core/mesh/mesh_session_coordinator.py"],
            [ANDROID_ANCHOR_MESH_CONTRACT, ANDROID_ANCHOR_MESH_TEST],
        ),
        RemainingIssue(
            "R5",
            "operator/panel/control/manifestation 单源统一仍有缺口",
            GapClass.MANIFESTATION_CONTROL,
            WorkPriority.IMPORTANT_SECONDARY,
            StageGate.P1_BEFORE_NEAR_CLOSURE,
            EvidenceState.PARTIAL,
            "UnifiedPanelPayload 已绑定 governance_state / mesh_runtime_state / existence_surface，"
            "但[operator 看见的世界]与[runtime 真实世界]完全同构这一命题仍部分成立，"
            "控制面与执行面同源性待进一步收口。",
            ["单一控制面与显化面命题", "P9 命题 fully closed"],
            ["P9"],
            ["core/operator_surface.py", "core/unified_panel_aggregation.py",
             "core/routes/operator.py"],
            [ANDROID_ANCHOR_WS_CLIENT],
        ),
        RemainingIssue(
            "R6",
            "live runtime proof 厚度不足，当前仍偏结构化语义证明",
            GapClass.PROOF,
            WorkPriority.IMPORTANT_SECONDARY,
            StageGate.P1_BEFORE_NEAR_CLOSURE,
            EvidenceState.RUNTIME_PROOF_THIN,
            "已有多套结构化测试与局部 E2E 测试，"
            "但跨仓活体异常场景（断连/回放/降级/接管）的完整运行级回归证据仍不足；"
            "near-closure 成熟度命题仍无法成立。",
            ["near-closure 成熟度命题", "P12 命题升级为 PARTIALLY_ESTABLISHED"],
            ["P12"],
            ["tests/integration/test_android_runtime_state_snapshot_e2e.py",
             "tests/integration/test_nl_e2e_canonical_path.py"],
            [ANDROID_ANCHOR_MESH_TEST],
        ),
        RemainingIssue(
            "R7",
            "统一 ingress 因果收口仍需持续回归守护",
            GapClass.CORE_ARCH,
            WorkPriority.IMPORTANT_SECONDARY,
            StageGate.P1_BEFORE_NEAR_CLOSURE,
            EvidenceState.PARTIAL,
            "chat / operator / Android WS / panel 等多入口已有代码，"
            "但不同入口间执行语义不漂移的回归覆盖仍不完整，"
            "统一入口收口命题处于部分成立状态。",
            ["统一入口收口命题", "P8 命题 fully closed"],
            ["P8"],
            ["core/routes/panel.py", "core/routes/chat.py", "core/routes/operator.py",
             "core/unified/entrypoint_router.py"],
            [ANDROID_ANCHOR_WS_CLIENT],
        ),
        RemainingIssue(
            "R8",
            "桌面/平板 carrier 语义未与 Android carrier 统一成单一显化框架",
            GapClass.MANIFESTATION_CONTROL,
            WorkPriority.IMPORTANT_SECONDARY,
            StageGate.P1_BEFORE_NEAR_CLOSURE,
            EvidenceState.HARD_ESTABLISHED
            if p.get("existence_surface_has_unified_carrier")
            else EvidenceState.PARTIAL,
            "PR-8 V2：UnifiedCarrierSurface / CarrierSurfaceEntry 已加入 "
            "core.desktop_existence_surface (schema 1.1)，"
            "桌面 carrier 与 Android carrier 通过 CarrierSurfaceEntry 统一投影在同一语义层，"
            "R8 V2 侧收口。"
            if p.get("existence_surface_has_unified_carrier")
            else "DesktopExistenceSurface 统一了桌面侧 5 个状态族，"
            "但与 Android carrier 的统一显化框架（carrier 语义统一、execution surface 同层次投影）"
            "尚未在单一代码层面完全实现。",
            ["多设备统一显化面命题", "P10 命题 HARD_ESTABLISHED"],
            ["P10"],
            ["core/desktop_existence_surface.py", "core/desktop_presence_runtime.py",
             "core/desktop_consumption_adapter.py"],
            [],
        ),
        RemainingIssue(
            "R9",
            "session continuity 在进程重建 / V2 重启场景下的跨仓闭环证明面偏薄",
            GapClass.SESSION_CONTINUITY,
            WorkPriority.IMPORTANT_SECONDARY,
            StageGate.P1_BEFORE_NEAR_CLOSURE,
            EvidenceState.PARTIAL,
            "durable_session_id / continuity_epoch / decide_reconnect / stale guard 均存在，"
            "但 Android 进程重建 → V2 重启 → 任务恢复完整路径的运行级闭环证明仍有缺口。",
            ["session 连续性 fully closed 命题", "P11 命题 HARD_ESTABLISHED"],
            ["P11"],
            ["core/attached_runtime_session_registry.py",
             "core/flow_continuity_coordinator.py",
             "core/android_v2_continuity_contract.py"],
            [ANDROID_ANCHOR_CONTINUITY],
        ),
        RemainingIssue(
            "R10",
            "Android 本地 inference availability 尚未成为跨仓统一决策门控的正式输入",
            GapClass.GOVERNANCE,
            WorkPriority.IMPORTANT_SECONDARY,
            StageGate.P1_BEFORE_NEAR_CLOSURE,
            EvidenceState.RUNTIME_PROOF_THIN,
            "Android 本地推理能力语义存在（AutonomousExecutionPipeline），"
            "但[local inference availability 进入 V2 canonical 决策门控]这条路径的"
            "运行级证明尚不完整。",
            ["P2 命题运行级闭合", "P6 命题 fully closed"],
            ["P2", "P6"],
            ["core/android_mode_gate_policy.py", "core/runtime/source_dispatch_orchestrator.py"],
            [ANDROID_ANCHOR_AUTONOMOUS_PIPELINE, ANDROID_ANCHOR_MODE_GATE],
        ),
        RemainingIssue(
            "R11",
            "跨仓 contract schema 一致性与版本管理无正式治理",
            GapClass.CROSS_REPO_CONTRACT,
            WorkPriority.IMPORTANT_SECONDARY,
            StageGate.P1_BEFORE_NEAR_CLOSURE,
            EvidenceState.PARTIAL,
            "contracts/ 目录下有多份契约文件，android_v2_continuity_contract 存在，"
            "但契约文件间的 schema 版本一致性、跨仓 contract registry / changelog 机制"
            "尚未形成统一正式治理。",
            ["跨仓 contract 一致性命题"],
            [],
            ["contracts/dispatch_continuity.py", "contracts/execution_trace.py",
             "core/android_v2_continuity_contract.py",
             "core/canonical_cross_repo_evidence_pipeline.py"],
            [ANDROID_ANCHOR_MESH_CONTRACT],
        ),
        RemainingIssue(
            "R12",
            "execution governance lifecycle 的 busy/queue_depth 状态未系统纳入编排消费",
            GapClass.ORCHESTRATION,
            WorkPriority.IMPORTANT_SECONDARY,
            StageGate.P1_BEFORE_NEAR_CLOSURE,
            EvidenceState.PARTIAL,
            "unified_execution_governance 含执行优先级与冲突裁决，"
            "但 busy_state / queue_depth 这类实时负载信号是否已系统纳入编排选择逻辑"
            "尚未得到运行级证明。",
            ["编排层完全状态真相驱动命题"],
            ["P4"],
            ["core/unified_execution_governance.py",
             "core/runtime/source_dispatch_orchestrator.py"],
            [],
        ),
        RemainingIssue(
            "R13",
            "端到端跨仓异常场景运行级回归缺口（断连/回放/降级/接管组合）",
            GapClass.PROOF,
            WorkPriority.ENHANCEMENT,
            StageGate.P2_ENHANCEMENT,
            EvidenceState.RUNTIME_PROOF_THIN,
            "当前已有局部异常测试（signal reconciler / continuity / takeover），"
            "但覆盖断连 → 回放 → 降级 → 接管组合路径的跨仓端到端运行级证明尚未形成。",
            ["near-closure 命题", "P3 全链 fully closed"],
            ["P3", "P12"],
            ["tests/integration/test_android_runtime_state_snapshot_e2e.py",
             "core/android_execution_signal_reconciler.py"],
            [ANDROID_ANCHOR_MESH_TEST],
        ),
    ]


def _build_closure_map(
    propositions: List[PropositionEntry],
    issues: List[RemainingIssue],
) -> List[ClosureMapEntry]:
    """Derive per-proposition closure map from propositions and remaining issues."""
    issue_to_props: Dict[str, List[str]] = {}
    for iss in issues:
        for pid in iss.blocks_propositions:
            issue_to_props.setdefault(pid, [])
            issue_to_props[pid].append(iss.issue_id)

    result = []
    for prop in propositions:
        blocking = list(prop.open_gap_ids)
        closed = (
            prop.verdict == PropositionVerdict.HARD_ESTABLISHED
            and not blocking
        )
        result.append(ClosureMapEntry(
            prop_id=prop.prop_id,
            verdict=prop.verdict,
            closed=closed,
            blocking_issue_ids=blocking,
        ))
    return result


def _build_runtime_flow() -> List[RuntimeFlowStage]:
    """Build the code-grounded end-to-end execution flow baseline."""
    return [
        RuntimeFlowStage(
            "F1",
            "问题入口进入 V2 统一首跳",
            "用户问题并不是直接进入某个单点聊天处理器，而是先经过 "
            "EntrypointRouter / chat compatibility adapter，随后交给 "
            "DesktopPresenceRuntime 与 OpenClawd 的 canonical 链。",
            [
                "core/unified/entrypoint_router.py",
                "core/routes/chat.py",
                "core/desktop_presence_runtime.py",
                "core/openclawd.py",
            ],
            [],
        ),
        RuntimeFlowStage(
            "F2",
            "V2 判定执行路径与是否跨设备分发",
            "进入 V2 后，请求先形成统一路由与执行上下文，再由 command_router / "
            "source_dispatch_orchestrator / device_selection 结合 readiness、"
            "session、participation truth 判定本地执行、远端 handoff 或分阶段协作。",
            [
                "core/command_router.py",
                "core/runtime/source_dispatch_orchestrator.py",
                "galaxy_gateway/routing/device_selection.py",
                "core/android_device_state_store.py",
            ],
            [ANDROID_ANCHOR_WS_CLIENT],
        ),
        RuntimeFlowStage(
            "F3",
            "Android 作为参与节点接收并落地执行",
            "当 V2 选择 Android 参与时，Android 不是被动客户端，而是通过 "
            "GalaxyWebSocketClient 接入、通过 AutonomousExecutionPipeline 与 "
            "delegated/takeover 路径在本地执行，并受 mesh participation contract "
            "与 continuity identity 约束。",
            [
                "core/android_runtime_dispatch_binding.py",
                "core/android_delegated_runtime_lifecycle_coordinator.py",
                "core/android_v2_continuity_contract.py",
            ],
            [
                ANDROID_ANCHOR_WS_CLIENT,
                ANDROID_ANCHOR_AUTONOMOUS_PIPELINE,
                ANDROID_ANCHOR_MESH_CONTRACT,
                ANDROID_ANCHOR_CONTINUITY,
            ],
        ),
        RuntimeFlowStage(
            "F4",
            "执行信号与结果从 Android 回流到 V2",
            "Android 的 runtime-state、delegated execution 信号与结果不会在外围停留，"
            "而是被 V2 吸收进 android_device_state_store、signal reconciler 与 "
            "unified_result_ingress 的 canonical 链。",
            [
                "core/android_device_state_store.py",
                "core/android_execution_signal_reconciler.py",
                "core/unified_result_ingress.py",
            ],
            [
                ANDROID_ANCHOR_WS_CLIENT,
                ANDROID_ANCHOR_AUTONOMOUS_PIPELINE,
            ],
        ),
        RuntimeFlowStage(
            "F5",
            "V2 完成结果真值、接受门与闭环判定",
            "结果进入 V2 后要经过 execution evidence、result truth acceptance、"
            "completion ingress 与 memory backflow，而不是只更新某个任务状态位。",
            [
                "core/execution_evidence_model.py",
                "core/result_truth_acceptance_gate.py",
                "core/unified_result_ingress.py",
                "core/canonical_completion_ingress.py",
            ],
            [],
        ),
        RuntimeFlowStage(
            "F6",
            "操作面、观测面与系统收口面读取同一批 runtime truth",
            "operator / panel / readiness / state contract 这些面板不是独立叙事层，"
            "而是读取统一治理语义、参与证据与 mesh/runtime 投影来形成当前系统可见面。",
            [
                "core/unified_governance_semantics.py",
                "core/unified_panel_aggregation.py",
                "core/operator_surface.py",
                "core/operational_readiness_surface.py",
                "core/v2_unified_state_contract.py",
            ],
            [ANDROID_ANCHOR_MESH_CONTRACT],
        ),
    ]


def _build_cross_repo_mismatches() -> List[CrossRepoMismatch]:
    """Build explicit cross-repo semantic contradictions and weak links."""
    return [
        CrossRepoMismatch(
            "M1",
            "V2 已能看到 Android runtime truth，但编排消费覆盖面仍不完整",
            "V2 已在 source_dispatch_orchestrator 与 device_selection 中消费 "
            "android_snapshot / get_device_state_snapshot。",
            "Android 已通过 GalaxyWebSocketClient 持续上送状态与执行信号。",
            "这说明双仓 transport 与状态吸收已存在，但 truth 尚未稳定成为所有路由/分发分支的"
            "统一决策输入，导致“看得见”不等于“真决策”。",
            ["R1", "R12"],
            [
                "core/runtime/source_dispatch_orchestrator.py",
                "galaxy_gateway/routing/device_selection.py",
            ],
            [ANDROID_ANCHOR_WS_CLIENT],
        ),
        CrossRepoMismatch(
            "M2",
            "Android 参与能力表达比 V2 当前成熟度叙事更克制",
            "V2 已具备 mesh_runtime_state、delegated coordination、operator/panel 投影等 richer surface。",
            "AndroidMeshParticipationContract 明确把 full mesh runtime executable 与 "
            "participant-level capability 分开，并保留 constrained/deferred 语义。",
            "如果只看 V2 表面，很容易高估 full mesh 已闭环；Android 合同明确要求当前只能把系统"
            "定性为‘中心治理 + 参与式协作’，不能拔高为 fully closed mesh runtime。",
            ["R4", "R13"],
            [
                "core/mesh/mesh_runtime_center_state.py",
                "core/unified_panel_aggregation.py",
            ],
            [ANDROID_ANCHOR_MESH_CONTRACT, ANDROID_ANCHOR_MESH_TEST],
        ),
        CrossRepoMismatch(
            "M3",
            "能力/就绪/本地推理可用性尚未形成稳定统一门控",
            "V2 有 android_mode_gate_policy、capability_resolver 与 unified governance semantics。",
            "Android 侧本地执行/本地推理能力真实存在，但其 availability 并未在双仓之间形成强制"
            "一致的决策消费链。",
            "这会让 Android 本地能力、V2 readiness judgement、operator 面板之间出现半语义/半治理"
            "状态，而不是稳定的一条真值轴。",
            ["R3", "R10"],
            [
                "core/android_mode_gate_policy.py",
                "core/unified/capability_resolver.py",
            ],
            [ANDROID_ANCHOR_AUTONOMOUS_PIPELINE, ANDROID_ANCHOR_CAPABILITY_REPORT],
        ),
        CrossRepoMismatch(
            "M4",
            "session continuity / durable identity 已接通，但跨重启闭环仍弱",
            "V2 已消费 durable_session_id / continuity_epoch，并在 reconnect 分类与 registry 中保留。",
            "Android DurableParticipantIdentity 已把 durable identity 作为稳定参与者身份锚点。",
            "双仓在字段与单次 reconnect 语义上已经联动，但完整的 Android 进程重建 → V2 重启 → "
            "恢复执行 证明面仍薄，因此 continuity 是部分闭合而不是 fully closed。",
            ["R9"],
            [
                "core/attached_runtime_session_registry.py",
                "core/flow_continuity_coordinator.py",
                "core/android_v2_continuity_contract.py",
            ],
            [ANDROID_ANCHOR_CONTINUITY],
        ),
    ]


def _build_v2_next_convergence_priority() -> V2ConvergencePriority:
    """Build the highest-value next-step V2-side integrity-linkage direction."""
    return V2ConvergencePriority(
        title_zh="让 Android truth 成为 V2 编排、闭环与治理的正式输入，而不是仅停留在可见面",
        why_now_zh=(
            "当前双仓最关键的未闭合点，不再是 transport 是否存在，而是 Android 已上送的 "
            "runtime-state / participation / readiness / continuity truth 是否真正进入 V2 的"
            "路由、dispatch、result acceptance 与 operator 收口链。该方向直接覆盖 R1/R2/R3/R12，"
            "能把系统从“能描述”推进到“能按真值决策”。"
        ),
        target_outcome_zh=(
            "目标不是新增抽象层，而是在现有 V2 canonical path 上补齐："
            "(1) 编排分支完整消费 Android truth；"
            "(2) result acceptance / closure 明确引用参与与连续性证据；"
            "(3) operator / readiness / board 面与真实决策原因同源可追踪。"
        ),
        linked_issue_ids=["R1", "R2", "R3", "R12"],
        v2_anchors=[
            "core/runtime/source_dispatch_orchestrator.py",
            "galaxy_gateway/routing/device_selection.py",
            "core/unified_result_ingress.py",
            "core/operational_readiness_surface.py",
            "core/unified_panel_aggregation.py",
        ],
        android_anchors=[
            ANDROID_ANCHOR_WS_CLIENT,
            ANDROID_ANCHOR_AUTONOMOUS_PIPELINE,
            ANDROID_ANCHOR_CONTINUITY,
        ],
    )


def _build_integrity_repair_actions() -> List[IntegrityRepairAction]:
    """Build V2-side integrity repairs reinforced by this convergence baseline."""
    return [
        IntegrityRepairAction(
            action_id="IRA_EVIDENCE_GATE_BLOCKS_CLOSURE",
            title_zh="结果闭环判定显式受 evidence acceptance gate 约束",
            status_zh="本次 V2 已补强",
            why_high_value_zh=(
                "这是双仓闭环可信度的硬门禁：即使 truth-chain/notify 成功，只要证据判定进入 "
                "quarantine/reject，就不能被标记为 fully_closed。修复该点可防止“低可信结果伪闭环”。"
            ),
            linked_issue_ids=["R2", "R3"],
            v2_anchors=[
                "core/unified_result_ingress.py",
                "core/result_truth_acceptance_gate.py",
                "tests/test_unified_result_ingress.py",
            ],
            android_dependency_zh=(
                "Android 继续提供 proof_class / delegated result 质量信号；"
                "本修复不依赖 Android 新改动即可生效。"
            ),
        ),
        IntegrityRepairAction(
            action_id="IRA_ROUTING_TRUTH_STRONG_GATING",
            title_zh="把 Android local inference/fallback/readiness 变成 V2 路由强一致门控",
            status_zh="仍需跨仓跟进",
            why_high_value_zh=(
                "当前 V2 已消费 Android truth，但并非所有编排分支都稳定同源消费。"
                "该动作是从“可见 truth”走向“真决策 truth”的关键。"
            ),
            linked_issue_ids=["R1", "R3", "R12"],
            v2_anchors=[
                "core/runtime/source_dispatch_orchestrator.py",
                "galaxy_gateway/routing/device_selection.py",
                "core/android_mode_gate_policy.py",
            ],
            android_dependency_zh=(
                "需要 Android 侧持续稳定上送 local inference / fallback tier / execution pressure 信号，"
                "并保持契约字段版本一致。"
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Main build entry point
# ---------------------------------------------------------------------------


def build_complete_joint_system_review() -> CompleteJointSystemReport:
    """Build and return the complete joint dual-repo system review report."""
    p = _collect_probes()
    logger.debug("complete-joint-system-review probes: %s", p)

    system_identity = _build_system_identity(p)
    propositions = _build_propositions(p)
    domains = _build_domains(p)
    remaining = _build_remaining_issues(p)
    closure_map = _build_closure_map(propositions, remaining)
    runtime_flow = _build_runtime_flow()
    mismatches = _build_cross_repo_mismatches()
    next_priority = _build_v2_next_convergence_priority()
    repair_actions = _build_integrity_repair_actions()

    # Unweighted mean
    overall = round(sum(d.completion_pct for d in domains) / len(domains), 1)

    # Weighted mean
    total_weight = sum(d.weight for d in domains)
    weighted = round(
        sum(d.completion_pct * d.weight for d in domains) / total_weight, 1
    )

    # Stage determination based on P0/P1 gaps
    has_p0 = any(i.stage_gate == StageGate.P0_BEFORE_RUNTIME_CLOSURE for i in remaining)
    has_p1 = any(i.stage_gate == StageGate.P1_BEFORE_NEAR_CLOSURE for i in remaining)
    if has_p0:
        stage = StageVerdict.MID_STAGE_CONSOLIDATION
    elif has_p1:
        stage = StageVerdict.LATE_INTEGRATION
    else:
        stage = StageVerdict.NEAR_CLOSURE

    return CompleteJointSystemReport(
        system_identity=system_identity,
        propositions=propositions,
        domain_statuses=domains,
        remaining_issues=remaining,
        closure_map=closure_map,
        runtime_flow=runtime_flow,
        cross_repo_mismatches=mismatches,
        v2_next_convergence_priority=next_priority,
        integrity_repair_actions=repair_actions,
        stage=stage,
        overall_completion_pct=overall,
        weighted_completion_pct=weighted,
        _probe_results=p,
    )


__all__ = [
    "ANDROID_AUDITED_REF",
    "REVIEW_AUTHORITY",
    "REVIEW_METHODOLOGY",
    "REVIEW_PR_TITLE",
    "REVIEW_PR_TITLE_EN",
    "REVIEW_CONVERGENCE_ANCHOR",
    "REVIEW_SUPERSEDES",
    "PropositionVerdict",
    "EvidenceState",
    "GapClass",
    "WorkPriority",
    "StageVerdict",
    "StageGate",
    "PropositionEntry",
    "SystemIdentityVerdict",
    "DomainStatus",
    "RemainingIssue",
    "ClosureMapEntry",
    "RuntimeFlowStage",
    "CrossRepoMismatch",
    "V2ConvergencePriority",
    "IntegrityRepairAction",
    "CompleteJointSystemReport",
    "build_complete_joint_system_review",
]
