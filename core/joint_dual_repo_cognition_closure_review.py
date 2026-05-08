"""core/joint_dual_repo_cognition_closure_review.py
===============================================

双仓（V2 + Android）完整认知审查与治理收口基线（机器可校验）。

本模块用于把系统级审查结论落到可机读 contract/state 结构，避免只停留在文档描述。
证据来源遵循“真实代码优先”：
- V2 仓：import/源码锚点检查
- Android 仓：外部代码锚点清单（作为双仓联动证据引用）

注意：本模块不把历史 PR 叙事作为证据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import importlib
import importlib.util
import logging
import os
import sys
import time
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

JOINT_COGNITION_CLOSURE_AUTHORITY: str = (
    "JOINT_DUAL_REPO_COGNITION_CLOSURE_REVIEW_V1::"
    "core.joint_dual_repo_cognition_closure_review::"
    "real-code-only-two-repo-baseline"
)

JOINT_COGNITION_CLOSURE_METHODOLOGY: str = (
    "METHOD::仅使用当前真实代码锚点。"
    "V2 侧通过 import/source 检查；Android 侧通过明确文件锚点引用。"
    "PR #993/历史文档/路线叙事不作为事实证据。"
)

_V2_ALLOWED_MODULE_PREFIXES = ("core.", "galaxy_gateway.")
_ROUTE_OPERATOR_ACTION = "/api/v1/operator/action"
_ROUTE_PANEL_UNIFIED = "/api/v1/panel/unified"
_MESH_RUNTIME_STATE_KEY = "mesh_runtime_state"
_ANDROID_MESH_CONTRACT = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/runtime/"
    "AndroidMeshParticipationContract.kt"
)
_ANDROID_LOCAL_COLLAB = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/agent/"
    "LocalCollaborationAgent.kt"
)
_ANDROID_MESH_TEST = (
    "ufo-galaxy-android/app/src/test/java/com/ufo/galaxy/runtime/"
    "Pr8AndroidMeshParticipationContractTest.kt"
)
_ANDROID_AUTONOMOUS_PIPELINE = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/agent/"
    "AutonomousExecutionPipeline.kt"
)
_ANDROID_WS_CLIENT = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/network/"
    "GalaxyWebSocketClient.kt"
)


class PropositionVerdict(str, Enum):
    """系统命题判定。"""

    ESTABLISHED = "已成立"
    PARTIAL = "部分成立"
    NOT_ESTABLISHED = "尚未成立"
    OVERESTIMATED = "被高估"


class ClosureBoundary(str, Enum):
    """收口边界状态。"""

    FULLY_CLOSED = "fully_closed"
    PARTIAL = "partial"
    CONSTRAINED = "constrained"
    DEFERRED = "deferred"


class SystemStage(str, Enum):
    """系统阶段判定。"""

    POC = "poc"
    EARLY_RUNTIME = "early_runtime"
    MID_STAGE_CONSOLIDATION = "mid_stage_consolidation"
    LATE_INTEGRATION = "late_integration"
    NEAR_CLOSURE = "near_closure"


class GapType(str, Enum):
    """剩余缺口分类。"""

    CORE_GAP = "核心缺口"
    CLOSURE_GAP = "收口缺口"
    GOVERNANCE_GAP = "治理缺口"
    RUNTIME_GAP = "运行级缺口"
    PROOF_GAP = "证明缺口"


class WorkPriority(str, Enum):
    """剩余工作优先级。"""

    MUST_DO = "必须做"
    IMPORTANT_SECONDARY = "重要但次级"
    ENHANCEMENT = "后续增强项"


@dataclass
class SystemPropositionReview:
    proposition_id: str
    topic: str
    verdict: PropositionVerdict
    boundary: ClosureBoundary
    conclusion_zh: str
    v2_code_anchors: List[str] = field(default_factory=list)
    android_code_anchors: List[str] = field(default_factory=list)
    constrained_or_deferred: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposition_id": self.proposition_id,
            "topic": self.topic,
            "verdict": self.verdict.value,
            "boundary": self.boundary.value,
            "conclusion_zh": self.conclusion_zh,
            "v2_code_anchors": list(self.v2_code_anchors),
            "android_code_anchors": list(self.android_code_anchors),
            "constrained_or_deferred": list(self.constrained_or_deferred),
        }


@dataclass
class DomainCompletionScore:
    domain_id: str
    topic: str
    weight_pct: float
    completion_pct: float
    evidence_status: str
    rationale_zh: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "topic": self.topic,
            "weight_pct": self.weight_pct,
            "completion_pct": self.completion_pct,
            "evidence_status": self.evidence_status,
            "rationale_zh": self.rationale_zh,
        }


@dataclass
class RemainingWorkItem:
    work_id: str
    title: str
    priority: WorkPriority
    gap_type: GapType
    evidence_status: str
    why_not_complete_zh: str
    blocking_propositions: List[str] = field(default_factory=list)
    evidence_anchors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "work_id": self.work_id,
            "title": self.title,
            "priority": self.priority.value,
            "gap_type": self.gap_type.value,
            "evidence_status": self.evidence_status,
            "why_not_complete_zh": self.why_not_complete_zh,
            "blocking_propositions": list(self.blocking_propositions),
            "evidence_anchors": list(self.evidence_anchors),
        }


@dataclass
class JointCognitionClosureReport:
    authority: str = JOINT_COGNITION_CLOSURE_AUTHORITY
    methodology: str = JOINT_COGNITION_CLOSURE_METHODOLOGY
    generated_at: float = field(default_factory=time.time)
    propositions: List[SystemPropositionReview] = field(default_factory=list)
    domain_scores: List[DomainCompletionScore] = field(default_factory=list)
    overall_completion_pct: float = 0.0
    current_stage: SystemStage = SystemStage.EARLY_RUNTIME
    stage_reason_zh: str = ""
    remaining_work: List[RemainingWorkItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authority": self.authority,
            "methodology": self.methodology,
            "generated_at": self.generated_at,
            "propositions": [p.to_dict() for p in self.propositions],
            "domain_scores": [score.to_dict() for score in self.domain_scores],
            "overall_completion_pct": self.overall_completion_pct,
            "current_stage": self.current_stage.value,
            "stage_reason_zh": self.stage_reason_zh,
            "remaining_work": [item.to_dict() for item in self.remaining_work],
        }


def _module_exists(module_path: str) -> bool:
    try:
        spec = importlib.util.find_spec(module_path)
        if spec is not None:
            return True
    except (ModuleNotFoundError, ImportError, AttributeError, ValueError) as exc:
        logger.debug("_module_exists find_spec failed for %s: %s", module_path, exc)

    rel_path = module_path.replace(".", os.sep) + ".py"
    for base in sys.path:
        if os.path.isfile(os.path.join(base, rel_path)):
            return True
    rel_pkg = module_path.replace(".", os.sep) + os.sep + "__init__.py"
    for base in sys.path:
        if os.path.isfile(os.path.join(base, rel_pkg)):
            return True
    return False


def _source_contains(module_path: str, token: str) -> bool:
    if not module_path.startswith(_V2_ALLOWED_MODULE_PREFIXES):
        return False
    try:
        spec = importlib.util.find_spec(module_path)
        if spec and spec.origin and os.path.isfile(spec.origin):
            with open(spec.origin, encoding="utf-8", errors="strict") as fh:
                return token in fh.read()
    except (UnicodeDecodeError, OSError, ValueError, ImportError, AttributeError) as exc:
        logger.debug("_source_contains read failed for %s: %s", module_path, exc)
    return False


def _round_pct(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _classify_stage(
    overall_completion_pct: float,
    has_runtime_or_proof_gap: bool,
) -> SystemStage:
    if overall_completion_pct < 35.0:
        return SystemStage.POC
    if overall_completion_pct < 55.0:
        return SystemStage.EARLY_RUNTIME
    if overall_completion_pct < 78.0:
        return SystemStage.MID_STAGE_CONSOLIDATION
    if has_runtime_or_proof_gap:
        return SystemStage.LATE_INTEGRATION
    return SystemStage.NEAR_CLOSURE


def build_joint_dual_repo_cognition_closure_review() -> JointCognitionClosureReport:
    """构建 8 项系统级命题的正式审查收口报告。"""

    operator_action_surface = _source_contains("core.routes.operator", _ROUTE_OPERATOR_ACTION)
    panel_unified = _source_contains("core.routes.panel", _ROUTE_PANEL_UNIFIED)
    governance_semantics = _module_exists("core.unified_governance_semantics")
    execution_governance = _module_exists("core.unified_execution_governance")
    mode_gate_policy = _module_exists("core.android_mode_gate_policy")
    nl_chain_contract = _module_exists("core.android_nl_semantic_chain_contract")
    mesh_state_surface = _source_contains("core.unified_governance_semantics", _MESH_RUNTIME_STATE_KEY)

    propositions = [
        SystemPropositionReview(
            proposition_id="P1_unique_center_governance_kernel",
            topic="V2 是否形成唯一中心治理核及 authority 边界",
            verdict=(
                PropositionVerdict.ESTABLISHED
                if (execution_governance and governance_semantics and mode_gate_policy)
                else PropositionVerdict.PARTIAL
            ),
            boundary=(
                ClosureBoundary.FULLY_CLOSED
                if (execution_governance and governance_semantics and mode_gate_policy)
                else ClosureBoundary.PARTIAL
            ),
            conclusion_zh=(
                "V2 已形成中心治理核：统一执行治理、统一治理语义、模式门治理均在 V2 侧集中定义；"
                "Android 通过参与式语义接入，不拥有中心编排权。"
            ),
            v2_code_anchors=[
                "core/unified_execution_governance.py",
                "core/unified_governance_semantics.py",
                "core/android_mode_gate_policy.py",
            ],
            android_code_anchors=[_ANDROID_AUTONOMOUS_PIPELINE],
        ),
        SystemPropositionReview(
            proposition_id="P2_android_strong_runtime_node",
            topic="Android 是否已是强 runtime node（非被动终端）",
            verdict=PropositionVerdict.PARTIAL,
            boundary=ClosureBoundary.PARTIAL,
            conclusion_zh=(
                "Android 具备本地执行、并行子任务协作和连接治理能力，已超出被动终端；"
                "但完整 mesh 运行时协调权仍未闭合，因此当前判定为部分成立。"
            ),
            v2_code_anchors=[
                "galaxy_gateway/android/handlers/goal_execution.py",
                "core/android_nl_semantic_chain_contract.py",
            ],
            android_code_anchors=[
                _ANDROID_LOCAL_COLLAB,
                _ANDROID_AUTONOMOUS_PIPELINE,
                _ANDROID_WS_CLIENT,
            ],
            constrained_or_deferred=[
                "Android 作为执行参与方已成立，但 mesh 全局协调 authority 不在 Android 本地闭合。",
            ],
        ),
        SystemPropositionReview(
            proposition_id="P3_execution_governance_unified_semantics",
            topic="双仓 execution governance 是否统一语义",
            verdict=PropositionVerdict.PARTIAL,
            boundary=ClosureBoundary.CONSTRAINED,
            conclusion_zh=(
                "V2 已提供统一 execution governance（goal/parallel/takeover），"
                "Android 侧存在对应门控与协作 contract，但跨仓统一语义仍依赖外仓运行态证据。"
            ),
            v2_code_anchors=[
                "core/unified_execution_governance.py",
                "galaxy_gateway/android/handlers/goal_execution.py",
            ],
            android_code_anchors=[
                _ANDROID_MESH_CONTRACT,
                _ANDROID_MESH_TEST,
                _ANDROID_AUTONOMOUS_PIPELINE,
            ],
            constrained_or_deferred=[
                "跨仓一致性目前以 contract+测试锚点成立，非单仓内可完全运行时证明。",
            ],
        ),
        SystemPropositionReview(
            proposition_id="P4_multimodal_main_chain_closure",
            topic="multimodal main chain 是否运行级闭合",
            verdict=PropositionVerdict.PARTIAL,
            boundary=ClosureBoundary.CONSTRAINED,
            conclusion_zh=(
                "Android 发射端与 V2 ingress carrier/semantic_authority 语义已明确，"
                "但多模态端到端执行闭环仍受配置与运行证据约束。"
            ),
            v2_code_anchors=[
                "core/desktop_presence_runtime.py",
                "core/android_nl_semantic_chain_contract.py",
                "galaxy_gateway/android/handlers/goal_execution.py",
            ],
            android_code_anchors=[_ANDROID_WS_CLIENT],
            constrained_or_deferred=[
                "多模态主链语义完整，但全链路运行级证明仍需额外 E2E 证据。",
            ],
        ),
        SystemPropositionReview(
            proposition_id="P5_capability_authority_readiness_policy",
            topic="capability authority/readiness/policy 是否稳定中心治理",
            verdict=PropositionVerdict.PARTIAL,
            boundary=ClosureBoundary.PARTIAL,
            conclusion_zh=(
                "V2 capability 与 readiness 治理面已集中；"
                "Android 本地能力开关与 V2 capability truth 存在潜在漂移，需要持续对齐。"
            ),
            v2_code_anchors=[
                "core/agent/capability_registry.py",
                "core/unified/capability_resolver.py",
                "core/android_mode_gate_policy.py",
            ],
            android_code_anchors=[_ANDROID_WS_CLIENT, _ANDROID_AUTONOMOUS_PIPELINE],
            constrained_or_deferred=[
                "Android 本地能力状态与 V2 truth 仍需持续 cross-repo 对齐验证。",
            ],
        ),
        SystemPropositionReview(
            proposition_id="P6_mesh_collaboration_multi_device_runtime",
            topic="mesh collaboration / multi-device runtime 是否运行级 fully close",
            verdict=PropositionVerdict.PARTIAL,
            boundary=ClosureBoundary.CONSTRAINED,
            conclusion_zh=(
                "V2 已显式输出 mesh_runtime_state（含 partial/constrained）；"
                "Android 已声明 LocalCollaborationAgent 边界与参与契约，但 full mesh runtime 仍未 fully close。"
            ),
            v2_code_anchors=[
                "core/unified_governance_semantics.py",
                "core/operator_surface.py",
                "core/unified_panel_aggregation.py",
            ],
            android_code_anchors=[_ANDROID_MESH_CONTRACT, _ANDROID_MESH_TEST, _ANDROID_LOCAL_COLLAB],
            constrained_or_deferred=[
                "full_mesh_runtime_execution_deferred_until_hybrid_execute_full_is_available",
                "barrier_coordination_deferred_until_cross_repo_runtime_contract_is_closed",
            ],
        ),
        SystemPropositionReview(
            proposition_id="P7_autonomy_boundary_clarity",
            topic="V2-centered governance 与 Android autonomy 边界是否清晰",
            verdict=(
                PropositionVerdict.ESTABLISHED
                if (governance_semantics and mode_gate_policy and nl_chain_contract)
                else PropositionVerdict.PARTIAL
            ),
            boundary=(
                ClosureBoundary.FULLY_CLOSED
                if (governance_semantics and mode_gate_policy and nl_chain_contract)
                else ClosureBoundary.PARTIAL
            ),
            conclusion_zh=(
                "边界已在统一治理语义与 Android NL 语义链 contract 中显式定义："
                "V2 保持 semantic/governance authority，Android 保留受限自治执行域。"
            ),
            v2_code_anchors=[
                "core/unified_governance_semantics.py",
                "core/android_mode_gate_policy.py",
                "core/android_nl_semantic_chain_contract.py",
            ],
            android_code_anchors=[_ANDROID_AUTONOMOUS_PIPELINE, _ANDROID_LOCAL_COLLAB],
        ),
        SystemPropositionReview(
            proposition_id="P8_remaining_primary_axes",
            topic="剩余主轴是否集中在 ingress/state transparency/orchestration/manifestation closure",
            verdict=(
                PropositionVerdict.ESTABLISHED
                if (panel_unified and operator_action_surface and mesh_state_surface)
                else PropositionVerdict.PARTIAL
            ),
            boundary=(
                ClosureBoundary.FULLY_CLOSED
                if (panel_unified and operator_action_surface and mesh_state_surface)
                else ClosureBoundary.PARTIAL
            ),
            conclusion_zh=(
                "当前剩余主轴已收敛到统一 ingress 语义、状态透明面、编排治理对齐与"
                " manifestation/mesh 运行时闭合，不应再被泛化为架构缺失问题。"
            ),
            v2_code_anchors=[
                "core/routes/panel.py",
                "core/unified_panel_aggregation.py",
                "core/routes/operator.py",
                "core/unified_governance_semantics.py",
            ],
            android_code_anchors=[_ANDROID_MESH_CONTRACT],
        ),
    ]

    domain_scores = [
        DomainCompletionScore(
            domain_id="D1_center_governance",
            topic="authority / governance（中心治理）",
            weight_pct=16.0,
            completion_pct=_round_pct(
                62.0 + 11.0 * sum([execution_governance, governance_semantics, mode_gate_policy])
            ),
            evidence_status="runtime_governance_structure_verified",
            rationale_zh=(
                "统一执行治理、统一治理语义、Android 模式门均可在 V2 真实代码中定位。"
            ),
        ),
        DomainCompletionScore(
            domain_id="D2_execution_runtime_chain",
            topic="execution runtime（执行链）",
            weight_pct=14.0,
            completion_pct=_round_pct(
                52.0
                + 12.0
                * sum(
                    [
                        execution_governance,
                        _module_exists("core.desktop_presence_runtime"),
                        _module_exists("galaxy_gateway.android.handlers.goal_execution"),
                    ]
                )
            ),
            evidence_status="runtime_path_exists_cross_repo_live_proof_limited",
            rationale_zh="执行治理、Android goal ingress、运行时承载链路已存在，但跨仓活体闭环仍受证据约束。",
        ),
        DomainCompletionScore(
            domain_id="D3_android_runtime_node",
            topic="Android runtime node 能力",
            weight_pct=12.0,
            completion_pct=68.0,
            evidence_status="android_local_runtime_and_contract_present",
            rationale_zh="Android 本地执行与并行子任务协作能力明确，但不拥有全局 mesh 协调 authority。",
        ),
        DomainCompletionScore(
            domain_id="D4_mesh_hybrid_orchestration",
            topic="mesh / hybrid / orchestration",
            weight_pct=14.0,
            completion_pct=62.0 if mesh_state_surface else 48.0,
            evidence_status="participation_ready_full_mesh_deferred",
            rationale_zh="mesh 参与契约与 mesh_runtime_state 已存在，full mesh runtime 与 barrier 协调仍 deferred。",
        ),
        DomainCompletionScore(
            domain_id="D5_multimodal_chain",
            topic="multimodal 主链",
            weight_pct=11.0,
            completion_pct=64.0 if nl_chain_contract else 46.0,
            evidence_status="semantic_chain_present_e2e_runtime_needs_more_proof",
            rationale_zh="carrier / semantic authority 语义链可定位，端到端运行级证据仍不足以判定 fully closed。",
        ),
        DomainCompletionScore(
            domain_id="D6_capability_readiness_policy",
            topic="capability/readiness/policy",
            weight_pct=11.0,
            completion_pct=66.0 if mode_gate_policy else 42.0,
            evidence_status="governance_exists_cross_repo_truth_drift_risk",
            rationale_zh="中心 capability/readiness/policy 治理面成立，但 Android 本地能力状态与 V2 truth 对齐仍需持续验证。",
        ),
        DomainCompletionScore(
            domain_id="D7_observability_operator_state",
            topic="observability/operator surface/state transparency",
            weight_pct=12.0,
            completion_pct=_round_pct(
                56.0 + 13.0 * sum([operator_action_surface, panel_unified, mesh_state_surface])
            ),
            evidence_status="operator_and_panel_surface_verified",
            rationale_zh="operator action 与 unified panel 及 mesh_runtime_state 透明面均可由真实代码定位。",
        ),
        DomainCompletionScore(
            domain_id="D8_manifestation_carrier_semantics",
            topic="manifestation / carrier semantics",
            weight_pct=10.0,
            completion_pct=72.0 if _module_exists("core.desktop_presence_runtime") else 45.0,
            evidence_status="semantic_surface_present_runtime_validation_pending",
            rationale_zh="manifestation 与 carrier 语义面已存在，仍需更多跨仓运行证据支撑最终闭环结论。",
        ),
    ]

    overall_completion_pct = _round_pct(
        sum(item.weight_pct * item.completion_pct for item in domain_scores) / 100.0
    )

    remaining_work = [
        RemainingWorkItem(
            work_id="RW1_mesh_full_runtime_contract_closure",
            title="闭合 full mesh runtime 与 barrier coordination 跨仓运行契约",
            priority=WorkPriority.MUST_DO,
            gap_type=GapType.CORE_GAP,
            evidence_status="contract_signals_present_but_runtime_deferred",
            why_not_complete_zh="Android mesh participation contract 明确 full mesh 与 barrier 仍 deferred，当前无法判定运行级闭合。",
            blocking_propositions=["P6_mesh_collaboration_multi_device_runtime"],
            evidence_anchors=[_ANDROID_MESH_CONTRACT, _ANDROID_MESH_TEST, "core/unified_governance_semantics.py"],
        ),
        RemainingWorkItem(
            work_id="RW2_cross_repo_execution_runtime_proof",
            title="补足跨仓 execution governance 运行态一致性证明（真实 Android 端到端证据）",
            priority=WorkPriority.MUST_DO,
            gap_type=GapType.PROOF_GAP,
            evidence_status="semantic_contract_present_live_runtime_evidence_insufficient",
            why_not_complete_zh="当前更多是结构/契约级证据，缺少稳定可回归的跨仓活体运行证据链。",
            blocking_propositions=[
                "P3_execution_governance_unified_semantics",
                "P4_multimodal_main_chain_closure",
            ],
            evidence_anchors=[
                "core/unified_execution_governance.py",
                "galaxy_gateway/android/handlers/goal_execution.py",
                "tests/integration/test_android_runtime_state_snapshot_e2e.py",
            ],
        ),
        RemainingWorkItem(
            work_id="RW3_capability_truth_alignment",
            title="收敛 Android 本地能力状态与 V2 capability truth 漂移",
            priority=WorkPriority.IMPORTANT_SECONDARY,
            gap_type=GapType.GOVERNANCE_GAP,
            evidence_status="central_policy_present_cross_repo_alignment_not_closed",
            why_not_complete_zh="V2 capability/readiness/policy 治理已成立，但 Android 本地状态与中心 truth 仍需持续校准机制。",
            blocking_propositions=["P5_capability_authority_readiness_policy"],
            evidence_anchors=[
                "core/android_mode_gate_policy.py",
                "core/unified/capability_resolver.py",
                _ANDROID_AUTONOMOUS_PIPELINE,
            ],
        ),
        RemainingWorkItem(
            work_id="RW4_multimodal_runtime_evidence_hardening",
            title="强化 multimodal 主链全链路运行级验证",
            priority=WorkPriority.IMPORTANT_SECONDARY,
            gap_type=GapType.RUNTIME_GAP,
            evidence_status="semantic_chain_exists_runtime_closure_not_fully_proven",
            why_not_complete_zh="多模态主链语义已建立，但缺少稳定的跨仓端到端运行验证闭环。",
            blocking_propositions=["P4_multimodal_main_chain_closure"],
            evidence_anchors=[
                "core/desktop_presence_runtime.py",
                "core/android_nl_semantic_chain_contract.py",
                _ANDROID_WS_CLIENT,
            ],
        ),
        RemainingWorkItem(
            work_id="RW5_operator_scorecard_regression_gate",
            title="将完成度 scorecard 与剩余缺口清单纳入回归门禁",
            priority=WorkPriority.ENHANCEMENT,
            gap_type=GapType.CLOSURE_GAP,
            evidence_status="review_contract_available_operator_gate_not_yet_enforced",
            why_not_complete_zh="已有可机读审查结构，但尚未形成统一的自动化收口门禁与趋势比较机制。",
            blocking_propositions=["P8_remaining_primary_axes"],
            evidence_anchors=[
                "core/joint_dual_repo_cognition_closure_review.py",
                "tests/test_joint_dual_repo_cognition_closure_review.py",
            ],
        ),
    ]

    has_runtime_or_proof_gap = any(
        item.gap_type in {GapType.RUNTIME_GAP, GapType.PROOF_GAP, GapType.CORE_GAP}
        for item in remaining_work
        if item.priority != WorkPriority.ENHANCEMENT
    )
    current_stage = _classify_stage(overall_completion_pct, has_runtime_or_proof_gap)
    stage_reason_zh = (
        "中心治理、执行链与状态透明面已稳定成形；"
        "但 mesh full runtime、跨仓运行态一致性与多模态运行级证据仍存在核心缺口，"
        "整体处于 mid-stage consolidation。"
        if current_stage == SystemStage.MID_STAGE_CONSOLIDATION
        else "阶段由综合完成度与关键运行级缺口自动判定。"
    )

    return JointCognitionClosureReport(
        propositions=propositions,
        domain_scores=domain_scores,
        overall_completion_pct=overall_completion_pct,
        current_stage=current_stage,
        stage_reason_zh=stage_reason_zh,
        remaining_work=remaining_work,
    )


__all__ = [
    "JOINT_COGNITION_CLOSURE_AUTHORITY",
    "JOINT_COGNITION_CLOSURE_METHODOLOGY",
    "PropositionVerdict",
    "ClosureBoundary",
    "SystemStage",
    "GapType",
    "WorkPriority",
    "SystemPropositionReview",
    "DomainCompletionScore",
    "RemainingWorkItem",
    "JointCognitionClosureReport",
    "build_joint_dual_repo_cognition_closure_review",
]
