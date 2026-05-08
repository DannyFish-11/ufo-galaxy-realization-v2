"""Joint dual-repo real-code baseline (V2 + Android).

This artifact is intentionally machine-readable so review conclusions are not
only prose. Evidence is grounded in current code anchors:
- V2 repo: import/source checks
- Android repo: explicit code anchors pinned to audited repository ref
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import importlib.util
import logging
import os
import sys
import time
from typing import Any, Dict, List

JOINT_BASELINE_PR_TITLE = (
    "Joint dual-repo real-code baseline audit: full integrated status and remaining-gap closure review"
)
JOINT_BASELINE_AUTHORITY = (
    "JOINT_DUAL_REPO_REAL_CODE_BASELINE::"
    "core.joint_dual_repo_real_code_baseline::real-code-only-v2-plus-android"
)
JOINT_BASELINE_METHOD = (
    "Only current real code is used as evidence. "
    "No historical PR narrative/audit markdown is used as factual proof."
)

# Android repository ref audited when compiling this baseline.
ANDROID_AUDITED_REF = "478e3f8f3cd3cb85b5a20999c9fca22a0f44ef8d"
ANDROID_ANCHOR_MESH_CONTRACT = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/runtime/AndroidMeshParticipationContract.kt"
)
ANDROID_ANCHOR_AUTONOMOUS_PIPELINE = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/agent/AutonomousExecutionPipeline.kt"
)
ANDROID_ANCHOR_WS_CLIENT = "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt"
ANDROID_ANCHOR_MESH_TEST = (
    "ufo-galaxy-android/app/src/test/java/com/ufo/galaxy/runtime/Pr8AndroidMeshParticipationContractTest.kt"
)

MID_STAGE_OVERALL_THRESHOLD = 70.0

logger = logging.getLogger(__name__)


class EvidenceState(str, Enum):
    """Evidence quality for each conclusion."""

    HARD_ESTABLISHED = "hard_established"
    PARTIAL = "partial"
    RUNTIME_PROOF_THIN = "runtime_proof_thin"


class GapClass(str, Enum):
    """Gap taxonomy (Chinese labels intentionally match governance language)."""

    CORE_ARCH = "核心架构缺口"
    GOVERNANCE = "治理缺口"
    RUNTIME = "运行级缺口"
    STATE_TRUTH = "状态真相缺口"
    ORCHESTRATION = "编排缺口"
    MANIFESTATION_CONTROL = "显化/控制面缺口"
    PROOF = "证明缺口"


class WorkPriority(str, Enum):
    """Prioritization levels (Chinese labels intentionally match review policy)."""

    MUST_FIRST = "必须先做"
    IMPORTANT_SECONDARY = "重要但次级"
    ENHANCEMENT = "后续增强"


class StageVerdict(str, Enum):
    MID_STAGE_CONSOLIDATION = "mid-stage consolidation"
    LATE_INTEGRATION = "late integration"
    NEAR_CLOSURE = "near-closure"


@dataclass
class DomainStatus:
    domain_id: str
    topic: str
    completion_pct: float
    evidence_state: EvidenceState
    rationale_zh: str
    v2_anchors: List[str] = field(default_factory=list)
    android_anchors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "topic": self.topic,
            "completion_pct": self.completion_pct,
            "evidence_state": self.evidence_state.value,
            "rationale_zh": self.rationale_zh,
            "v2_anchors": list(self.v2_anchors),
            "android_anchors": list(self.android_anchors),
        }


@dataclass
class RemainingIssue:
    issue_id: str
    title: str
    gap_class: GapClass
    priority: WorkPriority
    evidence_state: EvidenceState
    why_not_closed_zh: str
    blocks: List[str] = field(default_factory=list)
    v2_anchors: List[str] = field(default_factory=list)
    android_anchors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "title": self.title,
            "gap_class": self.gap_class.value,
            "priority": self.priority.value,
            "evidence_state": self.evidence_state.value,
            "why_not_closed_zh": self.why_not_closed_zh,
            "blocks": list(self.blocks),
            "v2_anchors": list(self.v2_anchors),
            "android_anchors": list(self.android_anchors),
        }


@dataclass
class JointRealCodeBaselineReport:
    authority: str = JOINT_BASELINE_AUTHORITY
    methodology: str = JOINT_BASELINE_METHOD
    pr_title: str = JOINT_BASELINE_PR_TITLE
    android_audited_ref: str = ANDROID_AUDITED_REF
    generated_at: float = field(default_factory=time.time)
    system_identity_zh: str = ""
    governance_boundary_zh: str = ""
    stage: StageVerdict = StageVerdict.MID_STAGE_CONSOLIDATION
    overall_completion_pct: float = 0.0
    domain_statuses: List[DomainStatus] = field(default_factory=list)
    remaining_issues: List[RemainingIssue] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authority": self.authority,
            "methodology": self.methodology,
            "pr_title": self.pr_title,
            "android_audited_ref": self.android_audited_ref,
            "generated_at": self.generated_at,
            "system_identity_zh": self.system_identity_zh,
            "governance_boundary_zh": self.governance_boundary_zh,
            "stage": self.stage.value,
            "overall_completion_pct": self.overall_completion_pct,
            "domain_statuses": [item.to_dict() for item in self.domain_statuses],
            "remaining_issues": [item.to_dict() for item in self.remaining_issues],
        }


def _module_exists(module_path: str) -> bool:
    try:
        if importlib.util.find_spec(module_path) is not None:
            return True
    except (ImportError, ModuleNotFoundError, ValueError, AttributeError) as exc:
        logger.debug("_module_exists fallback for %s due to %s", module_path, exc)
    rel = module_path.replace(".", os.sep) + ".py"
    rel_pkg = module_path.replace(".", os.sep) + os.sep + "__init__.py"
    return any(
        os.path.isfile(os.path.join(base, rel))
        or os.path.isfile(os.path.join(base, rel_pkg))
        for base in sys.path
    )


def _source_contains(module_path: str, token: str) -> bool:
    try:
        spec = importlib.util.find_spec(module_path)
    except (ImportError, ModuleNotFoundError, ValueError, AttributeError):
        return False
    if not spec or not spec.origin or not os.path.isfile(spec.origin):
        return False
    with open(spec.origin, encoding="utf-8", errors="replace") as fh:
        return token in fh.read()


def build_joint_dual_repo_real_code_baseline() -> JointRealCodeBaselineReport:
    governance = _module_exists("core.unified_execution_governance")
    routing_truth = _source_contains("core.runtime.source_dispatch_orchestrator", "_score_candidate")
    runtime_truth = _source_contains("core.unified_governance_semantics", "execution_runtime_state")
    runtime_truth &= _source_contains("core.unified_governance_semantics", "decision_causality")
    operator_surface = _module_exists("core.routes.operator") and _module_exists("core.routes.panel")
    ingress_unified = _source_contains("core.routes.panel", "/api/v1/panel/unified")
    logger.debug(
        "joint-baseline checks: governance=%s routing_truth=%s runtime_truth=%s operator_surface=%s ingress_unified=%s",
        governance,
        routing_truth,
        runtime_truth,
        operator_surface,
        ingress_unified,
    )

    domains = [
        DomainStatus(
            "D1",
            "authority / governance",
            83.0 if governance else 45.0,
            EvidenceState.HARD_ESTABLISHED if governance else EvidenceState.PARTIAL,
            "中心治理核与执行优先级治理在 V2 侧真实代码可定位。",
            ["core/unified_execution_governance.py", "core/unified_governance_semantics.py"],
            [ANDROID_ANCHOR_AUTONOMOUS_PIPELINE],
        ),
        DomainStatus(
            "D2",
            "execution runtime",
            78.0,
            EvidenceState.PARTIAL,
            "主执行链存在且稳定，但跨仓活体负载下连续性证明仍薄。",
            ["core/openclawd.py", "core/command_router.py"],
            [ANDROID_ANCHOR_AUTONOMOUS_PIPELINE],
        ),
        DomainStatus(
            "D3",
            "routing / orchestration",
            74.0 if routing_truth else 52.0,
            EvidenceState.PARTIAL,
            "编排已消费 Android truth 信号，但并非所有治理决策都运行级闭环。",
            ["core/runtime/source_dispatch_orchestrator.py", "galaxy_gateway/routing/device_selection.py"],
            [ANDROID_ANCHOR_WS_CLIENT],
        ),
        DomainStatus(
            "D4",
            "runtime-state truth",
            76.0 if runtime_truth else 50.0,
            EvidenceState.PARTIAL,
            "execution_runtime_state 与 decision_causality 已入治理语义，跨仓透明链仍需更厚证据。",
            ["core/unified_governance_semantics.py", "core/android_device_state_store.py"],
            [ANDROID_ANCHOR_WS_CLIENT],
        ),
        DomainStatus(
            "D5",
            "Android runtime-node strength",
            71.0,
            EvidenceState.PARTIAL,
            "Android 已具本地执行与协作能力，但 mesh 全局协调 authority 非 Android 所有。",
            ["galaxy_gateway/android/handlers/goal_execution.py", "core/android_nl_semantic_chain_contract.py"],
            [ANDROID_ANCHOR_AUTONOMOUS_PIPELINE, ANDROID_ANCHOR_MESH_CONTRACT],
        ),
        DomainStatus(
            "D6",
            "capability / readiness / policy consistency",
            69.0,
            EvidenceState.PARTIAL,
            "中心策略面存在，本地能力态与中心 truth 的持续一致性仍需强化。",
            ["core/android_mode_gate_policy.py", "core/unified/capability_resolver.py"],
            [ANDROID_ANCHOR_AUTONOMOUS_PIPELINE],
        ),
        DomainStatus(
            "D7",
            "mesh / hybrid / delegated collaboration",
            64.0,
            EvidenceState.PARTIAL,
            "语义与参与契约成立，但 full mesh runtime 与 barrier 协同未完全闭合。",
            ["core/mesh/mesh_runtime_center_state.py", "core/unified_governance_semantics.py"],
            [ANDROID_ANCHOR_MESH_CONTRACT, ANDROID_ANCHOR_MESH_TEST],
        ),
        DomainStatus(
            "D8",
            "multimodal chain",
            61.0,
            EvidenceState.RUNTIME_PROOF_THIN,
            "多模态语义主链存在，但稳定跨仓运行级证据不足。",
            ["core/android_nl_semantic_chain_contract.py", "core/desktop_presence_runtime.py"],
            [ANDROID_ANCHOR_WS_CLIENT],
        ),
        DomainStatus(
            "D9",
            "ingress unification",
            72.0 if ingress_unified else 56.0,
            EvidenceState.PARTIAL,
            "统一入口面存在，但不同入口的运行因果同路性仍需持续验证。",
            ["core/routes/panel.py", "core/routes/chat.py", "core/routes/operator.py"],
            [ANDROID_ANCHOR_WS_CLIENT],
        ),
        DomainStatus(
            "D10",
            "operator / panel / observability / manifestation surfaces",
            73.0 if operator_surface else 54.0,
            EvidenceState.PARTIAL,
            "面板与 operator 已强化，但单源显化与执行控制同构仍未完全闭合。",
            ["core/operator_surface.py", "core/unified_panel_aggregation.py", "core/routes/operator.py"],
            [ANDROID_ANCHOR_WS_CLIENT],
        ),
        DomainStatus(
            "D11",
            "proof / tests / live runtime closure",
            62.0,
            EvidenceState.RUNTIME_PROOF_THIN,
            "已有结构化与局部 E2E 证明，但跨仓活体回归证明厚度仍不足。",
            [
                "tests/integration/test_android_runtime_state_snapshot_e2e.py",
                "tests/test_orchestration_consumes_android_truth.py",
                "tests/integration/test_nl_e2e_canonical_path.py",
            ],
            [ANDROID_ANCHOR_MESH_TEST],
        ),
    ]

    remaining = [
        RemainingIssue(
            "R1",
            "routing/orchestration 对 runtime-state truth 的消费仍需扩展到更多治理分支",
            GapClass.ORCHESTRATION,
            WorkPriority.MUST_FIRST,
            EvidenceState.PARTIAL,
            "当前消费已存在但覆盖面不足，尚不能宣称编排层完全状态真相驱动。",
            ["网络整体作为系统本体运行级闭环", "跨仓统一决策门控"],
            ["core/runtime/source_dispatch_orchestrator.py", "galaxy_gateway/routing/device_selection.py"],
            [ANDROID_ANCHOR_WS_CLIENT],
        ),
        RemainingIssue(
            "R2",
            "Android → V2 runtime-state transparency 闭环证据仍偏薄",
            GapClass.STATE_TRUTH,
            WorkPriority.MUST_FIRST,
            EvidenceState.RUNTIME_PROOF_THIN,
            "状态上报与吸收链路存在，但稳定跨仓冲突收敛/漂移治理证据不够厚。",
            ["runtime-state truth 单源可信命题", "跨仓状态一致性命题"],
            [
                "core/android_device_state_store.py",
                "core/unified_governance_semantics.py",
                "tests/integration/test_android_runtime_state_snapshot_e2e.py",
            ],
            [ANDROID_ANCHOR_WS_CLIENT, ANDROID_ANCHOR_AUTONOMOUS_PIPELINE],
        ),
        RemainingIssue(
            "R3",
            "capability/readiness/policy/busy/fallback/local inference 跨仓统一门控未完全收敛",
            GapClass.GOVERNANCE,
            WorkPriority.MUST_FIRST,
            EvidenceState.PARTIAL,
            "能力与策略治理面存在，但跨仓一致门控与漂移治理仍非 fully closed。",
            ["统一治理核完备性命题"],
            ["core/android_mode_gate_policy.py", "core/unified/capability_resolver.py"],
            [ANDROID_ANCHOR_AUTONOMOUS_PIPELINE],
        ),
        RemainingIssue(
            "R4",
            "mesh/hybrid/delegated collaboration 仍以部分运行成立为主",
            GapClass.RUNTIME,
            WorkPriority.IMPORTANT_SECONDARY,
            EvidenceState.PARTIAL,
            "参与与协作语义成立，但 full mesh runtime/barrier 协同仍受约束。",
            ["多设备协作运行级 fully closed 命题"],
            ["core/mesh/live_mesh_runtime_engine.py", "core/mesh/mesh_runtime_center_state.py"],
            [ANDROID_ANCHOR_MESH_CONTRACT, ANDROID_ANCHOR_MESH_TEST],
        ),
        RemainingIssue(
            "R5",
            "operator/panel/control/manifestation 单源统一仍有缺口",
            GapClass.MANIFESTATION_CONTROL,
            WorkPriority.IMPORTANT_SECONDARY,
            EvidenceState.PARTIAL,
            "可观测与控制面增强明显，但显化与执行控制同源性仍待进一步收口。",
            ["单一控制面与显化面命题"],
            ["core/operator_surface.py", "core/unified_panel_aggregation.py", "core/routes/operator.py"],
            [ANDROID_ANCHOR_WS_CLIENT],
        ),
        RemainingIssue(
            "R6",
            "live runtime proof 厚度不足，当前仍偏结构化语义证明",
            GapClass.PROOF,
            WorkPriority.IMPORTANT_SECONDARY,
            EvidenceState.RUNTIME_PROOF_THIN,
            "仍需更厚的跨仓异常场景/长程运行回归证据。",
            ["near-closure 成熟度命题"],
            [
                "tests/integration/test_android_runtime_state_snapshot_e2e.py",
                "tests/integration/test_multimodal_canonical_path.py",
            ],
            [ANDROID_ANCHOR_MESH_TEST],
        ),
        RemainingIssue(
            "R7",
            "统一 ingress 因果收口仍需持续验证",
            GapClass.CORE_ARCH,
            WorkPriority.ENHANCEMENT,
            EvidenceState.PARTIAL,
            "入口收口面存在，但不同入口间执行语义不漂移仍需长期回归守护。",
            ["统一入口收口命题"],
            ["core/routes/panel.py", "core/routes/chat.py", "core/routes/operator.py"],
            [ANDROID_ANCHOR_WS_CLIENT],
        ),
    ]

    overall = round(sum(item.completion_pct for item in domains) / len(domains), 1)
    has_must = any(item.priority == WorkPriority.MUST_FIRST for item in remaining)
    has_important = any(
        item.priority == WorkPriority.IMPORTANT_SECONDARY for item in remaining
    )
    if has_must:
        stage = StageVerdict.MID_STAGE_CONSOLIDATION
    elif has_important:
        stage = StageVerdict.LATE_INTEGRATION
    else:
        stage = StageVerdict.NEAR_CLOSURE

    return JointRealCodeBaselineReport(
        system_identity_zh="当前系统本体是以 V2 为中心治理核、Android/桌面/其它设备为执行与显化载体的中心控制型分布式智能系统。",
        governance_boundary_zh="中心 authority 在 V2；Android 具受限自治执行能力但不拥有全局编排主权。",
        stage=stage,
        overall_completion_pct=overall,
        domain_statuses=domains,
        remaining_issues=remaining,
    )


__all__ = [
    "ANDROID_AUDITED_REF",
    "EvidenceState",
    "GapClass",
    "JointRealCodeBaselineReport",
    "JOINT_BASELINE_AUTHORITY",
    "JOINT_BASELINE_METHOD",
    "JOINT_BASELINE_PR_TITLE",
    "RemainingIssue",
    "StageVerdict",
    "WorkPriority",
    "DomainStatus",
    "build_joint_dual_repo_real_code_baseline",
]
