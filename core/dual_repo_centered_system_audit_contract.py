"""core/dual_repo_centered_system_audit_contract.py
=====================================================

双仓中心化分布式系统统一审计契约 V4（机器可校验）

定义基线：PR #993（已合并）、PR #1041（已合并）、PR #1042（已合并）、PR #1043（已合并）

本模块是"中心化分布式系统双仓统一认知审计"的机器可校验 contract 层。
它明确区分以下证明质量层级：

    - structural_only       仅有模块/代码结构存在
    - mainline_path_exists  主链路已接通（但缺少真实双运行时 regression）
    - v2_regression_exists  V2 内部回归测试存在（但非跨仓双进程 regression）
    - cross_repo_mock_proof 有跨仓 mock/stub 级别的协议契约证明
    - runtime_grounded      真实双运行时 / 跨仓 canonical 证明（当前不存在任何项）

与 ``core.joint_dual_repo_cognition_closure_review`` 的关系：
- 本模块 **替代** PR #1041 的旧 joint review contract，提供更强的双仓视角。
- 它不重复计算旧的 77.3% 总分——而是引入"跨仓证明质量"维度，明确区分
  "V2 单侧已充分"与"跨仓 canonical 已证明"。

Authority sentinel
------------------
``DUAL_REPO_CENTERED_SYSTEM_AUDIT_AUTHORITY`` 是本模块的权威标识符。

Public API
----------
Constants/sentinels::

    DUAL_REPO_CENTERED_SYSTEM_AUDIT_AUTHORITY
    DUAL_REPO_CENTERED_SYSTEM_AUDIT_CONTRACT_VERSION
    DUAL_REPO_AUDIT_BASELINE_PRS

Enums::

    ProofQualityLevel
    DualRepoOwnership
    SystemNatureVerdict
    DefinitionFulfillmentStatus

Dataclasses::

    DualRepoCodeAnchor
    DualRepoIssue
    DefinitionAreaAudit
    CrossRepoPathSegment
    CanonicalPathTrace
    FakeVsTrueE2EClassification
    DualRepoPRRoadmapItem
    DualRepoCenteredSystemAuditReport

Functions::

    build_dual_repo_centered_system_audit()
    get_cross_repo_proof_summary()
    get_combined_issue_list()
    get_roadmap()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Authority Sentinels
# ---------------------------------------------------------------------------

DUAL_REPO_CENTERED_SYSTEM_AUDIT_AUTHORITY: str = (
    "DUAL_REPO_CENTERED_SYSTEM_AUDIT_V4::"
    "core.dual_repo_centered_system_audit_contract::"
    "two-repo-unified-audit-pr993-pr1041-pr1042-pr1043-baseline"
)

DUAL_REPO_CENTERED_SYSTEM_AUDIT_CONTRACT_VERSION: str = "4.0.0"

DUAL_REPO_AUDIT_BASELINE_PRS: List[int] = [993, 1041, 1042, 1043]

DUAL_REPO_AUDIT_METHODOLOGY: str = (
    "METHOD::以 PR #993/#1041/#1042/#1043 已合并定义为基线。"
    "所有结论必须来自两仓可核实真实代码锚点。"
    "不以历史设计文档、PR 叙事、路线图散文为事实证据。"
    "明确区分 V2-only-proven 与 cross-repo-canonical-proven。"
)

SYSTEM_NATURE_DEFINITION: str = (
    "这套系统是以 ufo-galaxy-realization-v2 为中心治理核的"
    "中心化分布式智能网络系统（Center-Governed Distributed Intelligent Network）。"
    "V2 持有全部治理权威；Android 是强运行参与节点、可接管参与者、跨设备参与者；"
    "两仓共同构成一个 AI 主体的认知-执行-感知-显化循环。"
)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ProofQualityLevel(str, Enum):
    """跨仓证明质量层级（从最低到最高）。"""

    STRUCTURAL_ONLY = "structural_only"
    """仅有模块/代码结构存在，无运行路径证明。"""

    MAINLINE_PATH_EXISTS = "mainline_path_exists"
    """主链路已接通（代码路径可追踪），但缺少回归测试。"""

    V2_REGRESSION_EXISTS = "v2_regression_exists"
    """V2 内部回归测试存在，但非真实双进程/跨仓回归。"""

    CROSS_REPO_MOCK_PROOF = "cross_repo_mock_proof"
    """有跨仓 mock/stub 级别的协议契约证明。"""

    RUNTIME_GROUNDED = "runtime_grounded"
    """真实双运行时 / 跨仓 canonical 证明（当前此层级不存在任何项）。"""


class DualRepoOwnership(str, Enum):
    """问题根因归属。"""

    V2_ONLY = "v2_only"
    ANDROID_ONLY = "android_only"
    DUAL_REPO = "dual_repo"


class SystemNatureVerdict(str, Enum):
    """系统本质判定。"""

    CENTER_GOVERNED_DISTRIBUTED_NETWORK = "center_governed_distributed_network"
    """以 V2 为中心治理核的中心化分布式智能网络。"""


class DefinitionFulfillmentStatus(str, Enum):
    """定义满足状态。"""

    FULFILLED = "fulfilled"
    """已满足（有真实跨仓代码支持）。"""

    PARTIALLY_FULFILLED = "partially_fulfilled"
    """部分满足（V2 侧充分，跨仓运行级证明不足）。"""

    NOT_FULFILLED = "not_fulfilled"
    """未满足（缺乏必要代码支持）。"""

    V2_SIDE_ONLY = "v2_side_only"
    """仅 V2 侧满足，Android 侧或跨仓层面未满足。"""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DualRepoCodeAnchor:
    """双仓代码锚点。"""

    repo: str  # "v2" or "android"
    file_path: str
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repo": self.repo,
            "file_path": self.file_path,
            "description": self.description,
        }


@dataclass
class DualRepoIssue:
    """双仓联合系统问题。"""

    issue_id: str
    title: str
    issue_type: str
    severity: str  # "high" | "medium" | "low"
    impact: str
    v2_anchors: List[DualRepoCodeAnchor] = field(default_factory=list)
    android_anchors: List[DualRepoCodeAnchor] = field(default_factory=list)
    root_cause_ownership: DualRepoOwnership = DualRepoOwnership.DUAL_REPO
    resolution_scope: DualRepoOwnership = DualRepoOwnership.DUAL_REPO

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "title": self.title,
            "issue_type": self.issue_type,
            "severity": self.severity,
            "impact": self.impact,
            "v2_anchors": [a.to_dict() for a in self.v2_anchors],
            "android_anchors": [a.to_dict() for a in self.android_anchors],
            "root_cause_ownership": self.root_cause_ownership.value,
            "resolution_scope": self.resolution_scope.value,
        }


@dataclass
class DefinitionAreaAudit:
    """单个定义域的双仓审计结果。"""

    domain_id: str
    domain_name: str
    baseline_prs: List[int]
    v2_implementation_summary: str
    android_implementation_summary: str
    combined_behavior_summary: str
    proof_quality: ProofQualityLevel
    fulfillment_status: DefinitionFulfillmentStatus
    v2_anchors: List[DualRepoCodeAnchor] = field(default_factory=list)
    android_anchors: List[DualRepoCodeAnchor] = field(default_factory=list)
    known_gaps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "domain_name": self.domain_name,
            "baseline_prs": self.baseline_prs,
            "v2_implementation_summary": self.v2_implementation_summary,
            "android_implementation_summary": self.android_implementation_summary,
            "combined_behavior_summary": self.combined_behavior_summary,
            "proof_quality": self.proof_quality.value,
            "fulfillment_status": self.fulfillment_status.value,
            "v2_anchors": [a.to_dict() for a in self.v2_anchors],
            "android_anchors": [a.to_dict() for a in self.android_anchors],
            "known_gaps": self.known_gaps,
        }


@dataclass
class CrossRepoPathSegment:
    """跨仓路径段（用于 canonical path trace）。"""

    repo: str  # "v2" or "android"
    module_or_file: str
    role: str  # 该路径段在整体路径中的角色描述

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repo": self.repo,
            "module_or_file": self.module_or_file,
            "role": self.role,
        }


@dataclass
class CanonicalPathTrace:
    """一条双仓 canonical 路径的完整追踪。"""

    path_id: str
    path_name: str
    segments: List[CrossRepoPathSegment] = field(default_factory=list)
    proof_quality: ProofQualityLevel = ProofQualityLevel.MAINLINE_PATH_EXISTS
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path_id": self.path_id,
            "path_name": self.path_name,
            "segments": [s.to_dict() for s in self.segments],
            "proof_quality": self.proof_quality.value,
            "notes": self.notes,
        }


@dataclass
class FakeVsTrueE2EClassification:
    """Fake E2E vs True E2E 分类条目。"""

    test_id: str
    test_file: str
    test_repo: str  # "v2" or "android"
    classification: str  # 见下方分类常量
    what_it_proves: str
    what_it_does_not_prove: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "test_file": self.test_file,
            "test_repo": self.test_repo,
            "classification": self.classification,
            "what_it_proves": self.what_it_proves,
            "what_it_does_not_prove": self.what_it_does_not_prove,
        }


# E2E 分类常量
E2E_CLASS_V2_UNIT = "v2_only_unit"
E2E_CLASS_ANDROID_UNIT = "android_only_local"
E2E_CLASS_V2_STUB = "v2_protocol_simulation_stub"
E2E_CLASS_CROSS_REPO_MOCK = "cross_repo_mock_proof"
E2E_CLASS_TRUE_CROSS_REPO = "true_cross_repo_two_runtime"


@dataclass
class DualRepoPRRoadmapItem:
    """双仓 PR 路线图条目。"""

    pr_id: str
    title: str
    repo_scope: DualRepoOwnership
    targeted_problems: List[str]
    key_landing_zones_v2: List[str] = field(default_factory=list)
    key_landing_zones_android: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    definition_fulfillment_advance: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pr_id": self.pr_id,
            "title": self.title,
            "repo_scope": self.repo_scope.value,
            "targeted_problems": self.targeted_problems,
            "key_landing_zones_v2": self.key_landing_zones_v2,
            "key_landing_zones_android": self.key_landing_zones_android,
            "dependencies": [],
            "acceptance_criteria": self.acceptance_criteria,
            "definition_fulfillment_advance": self.definition_fulfillment_advance,
        }


@dataclass
class DualRepoCenteredSystemAuditReport:
    """双仓中心化分布式系统审计报告（完整机器可读结构）。"""

    contract_version: str
    authority: str
    baseline_prs: List[int]
    system_nature_verdict: SystemNatureVerdict
    system_nature_description: str

    # Section 1: 定义域审计
    definition_area_audits: List[DefinitionAreaAudit] = field(default_factory=list)

    # Section 3: 路径追踪
    canonical_path_traces: List[CanonicalPathTrace] = field(default_factory=list)

    # Section 4+5: 问题列表 + E2E 分类
    combined_issues: List[DualRepoIssue] = field(default_factory=list)
    e2e_classifications: List[FakeVsTrueE2EClassification] = field(default_factory=list)

    # Section 7: 路线图
    roadmap: List[DualRepoPRRoadmapItem] = field(default_factory=list)

    # Section 8: 结论
    overall_system_description_zh: str = ""
    current_completion_stage: str = "mid_stage_consolidation"
    pr_993_fulfillment: DefinitionFulfillmentStatus = (
        DefinitionFulfillmentStatus.PARTIALLY_FULFILLED
    )
    pr_1041_fulfillment: DefinitionFulfillmentStatus = (
        DefinitionFulfillmentStatus.PARTIALLY_FULFILLED
    )
    pr_1042_fulfillment: DefinitionFulfillmentStatus = (
        DefinitionFulfillmentStatus.FULFILLED
    )
    pr_1043_fulfillment: DefinitionFulfillmentStatus = (
        DefinitionFulfillmentStatus.PARTIALLY_FULFILLED
    )
    claims_backed_by_real_code: List[str] = field(default_factory=list)
    claims_structural_or_v2_only: List[str] = field(default_factory=list)
    top_combined_system_gaps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "authority": self.authority,
            "baseline_prs": self.baseline_prs,
            "system_nature_verdict": self.system_nature_verdict.value,
            "system_nature_description": self.system_nature_description,
            "definition_area_audits": [
                d.to_dict() for d in self.definition_area_audits
            ],
            "canonical_path_traces": [p.to_dict() for p in self.canonical_path_traces],
            "combined_issues": [i.to_dict() for i in self.combined_issues],
            "e2e_classifications": [e.to_dict() for e in self.e2e_classifications],
            "roadmap": [r.to_dict() for r in self.roadmap],
            "overall_system_description_zh": self.overall_system_description_zh,
            "current_completion_stage": self.current_completion_stage,
            "pr_993_fulfillment": self.pr_993_fulfillment.value,
            "pr_1041_fulfillment": self.pr_1041_fulfillment.value,
            "pr_1042_fulfillment": self.pr_1042_fulfillment.value,
            "pr_1043_fulfillment": self.pr_1043_fulfillment.value,
            "claims_backed_by_real_code": self.claims_backed_by_real_code,
            "claims_structural_or_v2_only": self.claims_structural_or_v2_only,
            "top_combined_system_gaps": self.top_combined_system_gaps,
        }


# ---------------------------------------------------------------------------
# Builder Functions
# ---------------------------------------------------------------------------


def _build_definition_area_audits() -> List[DefinitionAreaAudit]:
    """构建 8 个定义域的双仓审计结果。"""
    return [
        DefinitionAreaAudit(
            domain_id="D1",
            domain_name="中心治理权威（Center Governance Authority）",
            baseline_prs=[993, 1041, 1042],
            v2_implementation_summary=(
                "core/unified_execution_governance.py、core/unified_governance_semantics.py、"
                "core/android_mode_gate_policy.py、core/execution_governance_audit_authority.py（PR-14-V2）、"
                "core/closed_loop_governance_consolidation.py（PR-13-V2）均已集中定义。"
                "PR #1042 通过 get_execution_runtime_snapshot() 使 decision_causality "
                "与真实 runtime 状态强绑定。"
            ),
            android_implementation_summary=(
                "Android 不持有治理权威。通过 AppSettings 维护本地模式门（cross_device_enabled 等 flag），"
                "与 V2 mode gate 对应，但无强同步协议。Android 是受治理约束的参与者。"
            ),
            combined_behavior_summary=(
                "V2 治理中心已形成，决策因果链绑定真实 runtime 状态。"
                "跨仓漂移风险：Android 本地门与 V2 门之间无实时同步确认协议。"
            ),
            proof_quality=ProofQualityLevel.V2_REGRESSION_EXISTS,
            fulfillment_status=DefinitionFulfillmentStatus.PARTIALLY_FULFILLED,
            v2_anchors=[
                DualRepoCodeAnchor("v2", "core/unified_execution_governance.py", "统一执行治理契约"),
                DualRepoCodeAnchor("v2", "core/unified_governance_semantics.py", "统一治理语义"),
                DualRepoCodeAnchor("v2", "core/android_mode_gate_policy.py", "Android 模式门治理"),
                DualRepoCodeAnchor("v2", "core/execution_governance_audit_authority.py", "治理审计权威（PR-14-V2）"),
                DualRepoCodeAnchor("v2", "core/closed_loop_governance_consolidation.py", "闭环治理收口（PR-13-V2）"),
            ],
            android_anchors=[
                DualRepoCodeAnchor("android", "AppSettings", "本地模式门（cross_device_enabled）"),
                DualRepoCodeAnchor("android", "GalaxyWebSocketClient", "接收治理下发命令"),
            ],
            known_gaps=[
                "Android AppSettings 门与 V2 mode gate 之间无实时同步协议",
                "跨仓治理一致性无 CI 门控验证",
            ],
        ),
        DefinitionAreaAudit(
            domain_id="D2",
            domain_name="Android 运行参与节点（Android Runtime Node）",
            baseline_prs=[993, 1041],
            v2_implementation_summary=(
                "galaxy_gateway/android/handlers/ 下有完整 handler 集（registration、capability_report、"
                "goal_execution、takeover_response、handoff_v2_result、reconciliation_signal、"
                "device_state_snapshot）。PR-11-V2 lifecycle coordinator 统一 facade 已形成。"
            ),
            android_implementation_summary=(
                "GalaxyConnectionService（持久宿主）、GalaxyWebSocketClient（传输）、"
                "CommandDispatcher（命令分发）、AccessibilityActionExecutor（GUI 执行）、"
                "AccessibilityScreenshotProvider（视觉感知）、LlamaCppPlannerService（本地 AI）、"
                "NcnnGroundingService（Grounding）、LoopController（执行循环）、"
                "AutonomousExecutionPipeline（自治管线）、OfflineTaskQueue（离线弹性）均存在。"
            ),
            combined_behavior_summary=(
                "Android 作为强运行参与节点的代码结构充分。V2 侧接收链完整。"
                "跨仓 E2E 运行闭环（真实双进程回归）仍不足。"
                "Android 本地 AI 需首次运行下载 ~1.65GB 模型（运营前置，非代码缺口）。"
            ),
            proof_quality=ProofQualityLevel.MAINLINE_PATH_EXISTS,
            fulfillment_status=DefinitionFulfillmentStatus.PARTIALLY_FULFILLED,
            v2_anchors=[
                DualRepoCodeAnchor("v2", "galaxy_gateway/android/handlers/registration.py", "设备注册"),
                DualRepoCodeAnchor("v2", "galaxy_gateway/android/handlers/goal_execution.py", "目标执行信号"),
                DualRepoCodeAnchor("v2", "galaxy_gateway/android/handlers/takeover_response.py", "接管响应（PR-11-V2）"),
                DualRepoCodeAnchor("v2", "core/android_delegated_runtime_lifecycle_coordinator.py", "生命周期协调器"),
            ],
            android_anchors=[
                DualRepoCodeAnchor("android", "GalaxyConnectionService", "持久运行时宿主"),
                DualRepoCodeAnchor("android", "LoopController", "本地 step-level 执行循环"),
                DualRepoCodeAnchor("android", "LlamaCppPlannerService", "本地 AI 规划（llama.cpp JNI）"),
                DualRepoCodeAnchor("android", "NcnnGroundingService", "本地 Grounding（NCNN JNI）"),
                DualRepoCodeAnchor("android", "AutonomousExecutionPipeline", "本地自治执行管线"),
            ],
            known_gaps=[
                "缺乏真实双进程/双运行时 E2E 回归测试",
                "Android 本地 AI 首次运行需模型下载（~1.65GB）",
            ],
        ),
        DefinitionAreaAudit(
            domain_id="D3",
            domain_name="执行生命周期与治理绑定（Execution Lifecycle Governance Binding）",
            baseline_prs=[1042],
            v2_implementation_summary=(
                "PR #1042 引入 get_execution_runtime_snapshot()，"
                "build_unified_governance_state() 现包含 decision_causality "
                "（active_execution_count、highest_priority_execution_type、blocked_execution_types）。"
                "core/unified_panel_aggregation.py 严格从 canonical governance 读取 mesh_runtime_state。"
            ),
            android_implementation_summary=(
                "Android 无自身执行治理状态机，执行信号通过 WebSocket 上报 V2。"
                "治理权威完全在 V2 侧，符合中心化分布设计。"
            ),
            combined_behavior_summary=(
                "V2 执行治理与 runtime 状态绑定已在 PR #1042 接通。"
                "panel 投影对齐 canonical，消除漂移风险。"
                "跨仓 E2E 绑定回归测试仍为 V2 stub 级别。"
            ),
            proof_quality=ProofQualityLevel.V2_REGRESSION_EXISTS,
            fulfillment_status=DefinitionFulfillmentStatus.FULFILLED,
            v2_anchors=[
                DualRepoCodeAnchor("v2", "core/unified_execution_governance.py", "get_execution_runtime_snapshot()"),
                DualRepoCodeAnchor("v2", "core/unified_governance_semantics.py", "build_unified_governance_state()"),
                DualRepoCodeAnchor("v2", "core/unified_panel_aggregation.py", "panel mesh_runtime_state 对齐"),
                DualRepoCodeAnchor("v2", "core/android_delegated_runtime_lifecycle_coordinator.py", "lifecycle coordinator facade"),
            ],
            android_anchors=[
                DualRepoCodeAnchor("android", "GalaxyWebSocketClient", "执行信号上报传输"),
            ],
            known_gaps=[
                "跨仓真实 runtime 状态一致性验证仅为 V2 stub，非真实双进程",
            ],
        ),
        DefinitionAreaAudit(
            domain_id="D4",
            domain_name="Mesh 运行时中心闭合（Mesh Runtime Center Closure）",
            baseline_prs=[1043],
            v2_implementation_summary=(
                "PR #1043 引入 core/mesh/mesh_runtime_center_state.py：10 态状态机、"
                "强制转移表、MeshParticipantCenterEligibility、evaluate_center_runtime_status()、"
                "build_mesh_runtime_center_state()、5 个 policy sentinel。"
                "116 测试覆盖 18 个测试组（A–R）。"
                "participation_ready ≠ runtime_closed 合同已强制执行。"
                "proof_quality（live/stale/structurally_inferred/missing）已在治理语义层输出。"
            ),
            android_implementation_summary=(
                "AndroidMeshParticipationContract 明示 Android 是 mesh 参与节点，非协调 authority。"
                "LocalCollaborationAgent 提供参与式协作接口。"
                "Android 端无 mesh 状态机——mesh 全局状态机权威在 V2。"
            ),
            combined_behavior_summary=(
                "V2 中心 mesh 状态机已形成（PR #1043）。"
                "但 runtime_closed 态从未通过真实 Android 参与的完整 barrier 协调周期触发。"
                "Android 参与式 mesh 仍为 deferred（AndroidMeshParticipationContract 明示）。"
            ),
            proof_quality=ProofQualityLevel.V2_REGRESSION_EXISTS,
            fulfillment_status=DefinitionFulfillmentStatus.PARTIALLY_FULFILLED,
            v2_anchors=[
                DualRepoCodeAnchor("v2", "core/mesh/mesh_runtime_center_state.py", "10 态中心 mesh 状态机（PR #1043）"),
                DualRepoCodeAnchor("v2", "core/mesh/live_mesh_runtime_engine.py", "live mesh 引擎"),
                DualRepoCodeAnchor("v2", "core/mesh/body_mesh_registry.py", "mesh 角色注册"),
                DualRepoCodeAnchor("v2", "core/unified_governance_semantics.py", "proof_quality 分级输出"),
            ],
            android_anchors=[
                DualRepoCodeAnchor("android", "AndroidMeshParticipationContract", "mesh 参与契约（deferred 声明）"),
                DualRepoCodeAnchor("android", "LocalCollaborationAgent", "本地协作参与接口"),
            ],
            known_gaps=[
                "runtime_closed 态从未通过真实 Android 参与触发（deferred）",
                "Android barrier 协调无跨仓 E2E 回归证据",
            ],
        ),
        DefinitionAreaAudit(
            domain_id="D5",
            domain_name="接管语义（Takeover / Delegated Ownership Transfer）",
            baseline_prs=[993, 1041],
            v2_implementation_summary=(
                "takeover_request 是优先级最高的 ExecutionType（PRIORITY_1_TAKEOVER）。"
                "takeover_response handler（PR-11-V2）完全委托 lifecycle coordinator。"
                "takeover tracking、session reduction、audit 统一由 coordinator 处理。"
                "lookup_session_by_device() 确保 session_id 可从注册表补全。"
            ),
            android_implementation_summary=(
                "CommandDispatcher 处理 takeover_request，AppSettings 门控接受/拒绝。"
                "通过 GalaxyWebSocketClient 发回 takeover_response。"
                "接管后本地循环暂停逻辑的跨仓闭合证据不足。"
            ),
            combined_behavior_summary=(
                "V2 接管治理链已在 PR-11-V2 完整闭合。"
                "Android 断连重连后的 resumed ownership transfer 无跨仓回归证据。"
            ),
            proof_quality=ProofQualityLevel.MAINLINE_PATH_EXISTS,
            fulfillment_status=DefinitionFulfillmentStatus.PARTIALLY_FULFILLED,
            v2_anchors=[
                DualRepoCodeAnchor("v2", "galaxy_gateway/android/handlers/takeover_response.py", "接管响应 handler（PR-11-V2）"),
                DualRepoCodeAnchor("v2", "core/android_delegated_runtime_lifecycle_coordinator.py", "on_takeover_response()"),
                DualRepoCodeAnchor("v2", "core/attached_runtime_session_registry.py", "lookup_session_by_device()"),
                DualRepoCodeAnchor("v2", "core/attached_runtime_recovery_readiness.py", "恢复就绪性评估"),
            ],
            android_anchors=[
                DualRepoCodeAnchor("android", "CommandDispatcher", "接收并处理 takeover_request"),
                DualRepoCodeAnchor("android", "GalaxyWebSocketClient", "发送 takeover_response"),
            ],
            known_gaps=[
                "resumed ownership transfer（断连后重连接管恢复）无跨仓回归证据",
                "接管后 Android 本地循环暂停的跨仓闭合证据不足",
            ],
        ),
        DefinitionAreaAudit(
            domain_id="D6",
            domain_name="连续性 / 重连 / 恢复（Continuity / Reconnect / Recovery）",
            baseline_prs=[993, 1041],
            v2_implementation_summary=(
                "core/android_v2_continuity_contract.py、core/attached_runtime_reuse_binding.py、"
                "core/attached_runtime_reuse_dispatch.py、core/attached_runtime_recovery_readiness.py 均存在。"
                "test_pr6_hybrid_continuity_closure.py、test_prf_dispatch_continuity_recovery_context.py "
                "提供 V2 侧回归测试。"
            ),
            android_implementation_summary=(
                "OfflineTaskQueue（离线队列）、GalaxyWebSocketClient（断连重连逻辑）、"
                "TailscaleAdapter（备用网络路径）均存在。"
            ),
            combined_behavior_summary=(
                "V2 侧连续性/恢复机制有回归测试覆盖（V2 stub 级别）。"
                "跨仓 reconnect 场景（Android 断连 → V2 状态保持 → 重连恢复）缺真实双进程证据。"
            ),
            proof_quality=ProofQualityLevel.CROSS_REPO_MOCK_PROOF,
            fulfillment_status=DefinitionFulfillmentStatus.PARTIALLY_FULFILLED,
            v2_anchors=[
                DualRepoCodeAnchor("v2", "core/android_v2_continuity_contract.py", "V2-Android 连续性契约"),
                DualRepoCodeAnchor("v2", "core/attached_runtime_session_registry.py", "session 注册表"),
                DualRepoCodeAnchor("v2", "tests/test_pr6_hybrid_continuity_closure.py", "hybrid continuity 回归测试"),
                DualRepoCodeAnchor("v2", "tests/integration/test_v2_android_protocol_regression.py", "协议回归测试（mock）"),
            ],
            android_anchors=[
                DualRepoCodeAnchor("android", "OfflineTaskQueue", "离线队列"),
                DualRepoCodeAnchor("android", "GalaxyWebSocketClient", "断连重连逻辑"),
            ],
            known_gaps=[
                "跨仓断连-重连 E2E 场景缺真实双进程回归证据",
            ],
        ),
        DefinitionAreaAudit(
            domain_id="D7",
            domain_name="可观测性 / 诊断 / 审计面（Observability / Diagnostics）",
            baseline_prs=[993, 1041, 1042],
            v2_implementation_summary=(
                "/api/v1/operator/action（operator 汇聚面）、/api/v1/panel/unified（panel 统一状态面）、"
                "core/execution_governance_audit_authority.py（PR-14-V2，5 阶段审计路径）、"
                "classify_canonical_proof_input_diagnosis()（Android proof 输入分类）均存在。"
            ),
            android_implementation_summary=(
                "Android 端仅有基础 log 和 WebSocket 状态报告，"
                "无结构化 operator-consumable 诊断接口（AI 推理状态、LoopController 状态不可观测）。"
                "galaxy_gateway/android/handlers/diagnostics.py 接收 Android 诊断信号（V2 侧）。"
            ),
            combined_behavior_summary=(
                "V2 侧可观测面丰富，但 Android 侧无结构化诊断暴露接口。"
                "可观测性严重非对称：V2 视角强，Android 本地 AI 状态对 operator 不透明。"
            ),
            proof_quality=ProofQualityLevel.V2_REGRESSION_EXISTS,
            fulfillment_status=DefinitionFulfillmentStatus.PARTIALLY_FULFILLED,
            v2_anchors=[
                DualRepoCodeAnchor("v2", "core/routes/operator.py", "/api/v1/operator/action"),
                DualRepoCodeAnchor("v2", "core/routes/panel.py", "/api/v1/panel/unified"),
                DualRepoCodeAnchor("v2", "core/execution_governance_audit_authority.py", "治理审计权威（PR-14-V2）"),
                DualRepoCodeAnchor("v2", "core/unified_governance_semantics.py", "classify_canonical_proof_input_diagnosis()"),
                DualRepoCodeAnchor("v2", "galaxy_gateway/android/handlers/diagnostics.py", "Android 诊断信号接收"),
            ],
            android_anchors=[],
            known_gaps=[
                "Android 侧无结构化诊断接口（AI 推理状态、LoopController 状态不可观测）",
                "Android 状态透明度：store 存在，wire path 不完整（PR #993 已明确指出）",
            ],
        ),
        DefinitionAreaAudit(
            domain_id="D8",
            domain_name="Capability 网络 / 就绪性 / Policy（Capability Network）",
            baseline_prs=[993, 1041],
            v2_implementation_summary=(
                "core/canonical_capability_status.py、core/canonical_capability_scheduling_basis.py、"
                "core/admissibility_policy_convergence.py、core/android_participant_evidence_ingress.py、"
                "core/canonical_cross_repo_evidence_pipeline.py 均存在。"
                "capability 中心治理面成形。"
            ),
            android_implementation_summary=(
                "Android 通过 capability_report handler 向 V2 汇报本地能力。"
                "本地能力管理（llama.cpp/NCNN 是否可用）与 V2 capability truth 之间缺乏双向同步协议。"
            ),
            combined_behavior_summary=(
                "V2 capability 中心治理已成形，汇报路径存在。"
                "capability truth 反馈（V2 → Android）不足，缺稳定双向同步。"
                "capability drift 治理未形成稳定 gate。"
            ),
            proof_quality=ProofQualityLevel.MAINLINE_PATH_EXISTS,
            fulfillment_status=DefinitionFulfillmentStatus.PARTIALLY_FULFILLED,
            v2_anchors=[
                DualRepoCodeAnchor("v2", "core/canonical_capability_status.py", "规范能力状态"),
                DualRepoCodeAnchor("v2", "core/android_participant_evidence_ingress.py", "Android 参与者证据入口"),
                DualRepoCodeAnchor("v2", "core/canonical_cross_repo_evidence_pipeline.py", "跨仓证据管线"),
            ],
            android_anchors=[
                DualRepoCodeAnchor("android", "capability_report（通过 WebSocket）", "本地能力汇报"),
            ],
            known_gaps=[
                "capability truth 反馈（V2 → Android）不足",
                "capability drift 治理未形成稳定 gate",
            ],
        ),
    ]


def _build_canonical_path_traces() -> List[CanonicalPathTrace]:
    """构建关键双仓 canonical 路径追踪。"""
    return [
        CanonicalPathTrace(
            path_id="PATH-01",
            path_name="能力生产与消费路径",
            segments=[
                CrossRepoPathSegment("android", "GalaxyConnectionService + GalaxyWebSocketClient", "连接建立与维护"),
                CrossRepoPathSegment("android", "AccessibilityScreenshotProvider / LlamaCppPlannerService", "本地能力执行"),
                CrossRepoPathSegment("v2", "galaxy_gateway/android/handlers/capability_report.py", "能力汇报接收"),
                CrossRepoPathSegment("v2", "core/canonical_capability_status.py", "canonical 能力状态维护"),
                CrossRepoPathSegment("v2", "core/android_participant_evidence_ingress.py", "参与者证据入口"),
                CrossRepoPathSegment("v2", "core/canonical_cross_repo_evidence_pipeline.py", "跨仓证据管线"),
            ],
            proof_quality=ProofQualityLevel.MAINLINE_PATH_EXISTS,
            notes="V2 侧接收和处理链存在，Android → V2 单向汇报路径接通。V2 → Android 能力反馈路径不足。",
        ),
        CanonicalPathTrace(
            path_id="PATH-02",
            path_name="执行生命周期与治理绑定路径",
            segments=[
                CrossRepoPathSegment("v2", "core/openclawd.py", "意图 → 决策"),
                CrossRepoPathSegment("v2", "core/unified_execution_governance.py evaluate_execution_governance()", "统一执行治理判定"),
                CrossRepoPathSegment("v2", "core/command_router.py", "唯一路由权威"),
                CrossRepoPathSegment("v2", "galaxy_gateway/device_router.py", "WebSocket 传输到 Android"),
                CrossRepoPathSegment("android", "CommandDispatcher", "命令分发到本地 executor"),
                CrossRepoPathSegment("android", "AccessibilityActionExecutor + LoopController", "GUI 执行 + step 循环"),
                CrossRepoPathSegment("android", "GalaxyWebSocketClient", "执行结果上报"),
                CrossRepoPathSegment("v2", "galaxy_gateway/android/handlers/goal_execution.py", "执行信号接收"),
                CrossRepoPathSegment("v2", "core/android_delegated_runtime_lifecycle_coordinator.py on_execution_signal()", "lifecycle coordinator 处理"),
                CrossRepoPathSegment("v2", "core/unified_execution_governance.py", "runtime 状态更新"),
            ],
            proof_quality=ProofQualityLevel.MAINLINE_PATH_EXISTS,
            notes="路径代码存在且可追踪。缺真实双进程 E2E 回归验证。",
        ),
        CanonicalPathTrace(
            path_id="PATH-03",
            path_name="接管 / Ownership Transfer 路径",
            segments=[
                CrossRepoPathSegment("v2", "core/unified_execution_governance.py", "takeover_request 决策（最高优先级）"),
                CrossRepoPathSegment("v2", "core/command_router.py → galaxy_gateway/device_router.py", "下发接管命令"),
                CrossRepoPathSegment("android", "CommandDispatcher", "接收 takeover_request"),
                CrossRepoPathSegment("android", "AppSettings 门控", "本地接受/拒绝判断"),
                CrossRepoPathSegment("android", "GalaxyWebSocketClient", "发回 takeover_response"),
                CrossRepoPathSegment("v2", "galaxy_gateway/android/handlers/takeover_response.py", "接管响应 handler（PR-11-V2）"),
                CrossRepoPathSegment("v2", "core/android_delegated_runtime_lifecycle_coordinator.py on_takeover_response()", "lifecycle coordinator 统一处理"),
                CrossRepoPathSegment("v2", "core/takeover_tracking.py", "接管状态跟踪"),
                CrossRepoPathSegment("v2", "core/android_runtime_transition_reducer.py", "状态转换"),
                CrossRepoPathSegment("v2", "core/audit_event_semantics.py", "审计事件记录"),
            ],
            proof_quality=ProofQualityLevel.MAINLINE_PATH_EXISTS,
            notes="V2 侧接管治理链已在 PR-11-V2 完整闭合。resumed ownership transfer 无跨仓回归。",
        ),
        CanonicalPathTrace(
            path_id="PATH-04",
            path_name="连续性 / 重连 / 恢复路径",
            segments=[
                CrossRepoPathSegment("android", "GalaxyWebSocketClient 断连检测", "连接断开"),
                CrossRepoPathSegment("android", "OfflineTaskQueue", "离线任务入队"),
                CrossRepoPathSegment("android", "GalaxyWebSocketClient 重连", "重连触发"),
                CrossRepoPathSegment("v2", "core/attached_runtime_session_registry.py lookup_session_by_device()", "session 查找"),
                CrossRepoPathSegment("v2", "core/attached_runtime_reuse_binding.py", "runtime 复用绑定"),
                CrossRepoPathSegment("v2", "core/attached_runtime_recovery_readiness.py", "恢复就绪性评估"),
                CrossRepoPathSegment("v2", "core/android_v2_continuity_contract.py", "连续性契约"),
            ],
            proof_quality=ProofQualityLevel.CROSS_REPO_MOCK_PROOF,
            notes="V2 侧连续性机制有 stub 级回归测试。真实跨进程断连重连 E2E 场景缺证据。",
        ),
        CanonicalPathTrace(
            path_id="PATH-05",
            path_name="Mesh 参与 / 证明质量 / 就绪性路径",
            segments=[
                CrossRepoPathSegment("android", "AndroidMeshParticipationContract", "mesh 参与声明"),
                CrossRepoPathSegment("android", "LocalCollaborationAgent", "协作参与"),
                CrossRepoPathSegment("v2", "galaxy_gateway/android/handlers/mesh_topology.py", "mesh 拓扑信号接收"),
                CrossRepoPathSegment("v2", "core/mesh/body_mesh_registry.py", "mesh 角色注册"),
                CrossRepoPathSegment("v2", "core/mesh/mesh_session_coordinator.py", "mesh 会话协调"),
                CrossRepoPathSegment("v2", "core/mesh/mesh_runtime_center_state.py evaluate_center_runtime_status()", "中心 mesh 状态机评估"),
                CrossRepoPathSegment("v2", "core/unified_governance_semantics.py build_mesh_runtime_state()", "proof quality 输出"),
                CrossRepoPathSegment("v2", "core/unified_governance_semantics.py resolve_governance_path_decision()", "治理路径决策（proof_quality 影响 multimodal）"),
            ],
            proof_quality=ProofQualityLevel.V2_REGRESSION_EXISTS,
            notes="V2 中心 mesh 状态机 + 116 测试。runtime_closed 从未通过真实 Android 参与触发。",
        ),
    ]


def _build_combined_issues() -> List[DualRepoIssue]:
    """构建双仓综合问题列表。"""
    return [
        DualRepoIssue(
            issue_id="P1",
            title="Capability Drift（能力漂移）",
            issue_type="跨仓状态漂移",
            severity="high",
            impact="V2 基于 Android 汇报 capability 做治理决策，但 Android 本地实际能力可能不同步，导致错误执行路径决策",
            v2_anchors=[
                DualRepoCodeAnchor("v2", "core/canonical_capability_status.py", "capability truth SSOT"),
                DualRepoCodeAnchor("v2", "core/android_participant_evidence_ingress.py", "Android 证据入口"),
            ],
            android_anchors=[
                DualRepoCodeAnchor("android", "capability_report（WebSocket）", "本地能力单向上报"),
            ],
            root_cause_ownership=DualRepoOwnership.DUAL_REPO,
            resolution_scope=DualRepoOwnership.DUAL_REPO,
        ),
        DualRepoIssue(
            issue_id="P2",
            title="Schema Drift（协议模式漂移）",
            issue_type="跨仓协议不一致",
            severity="high",
            impact="V2 Python dataclass 与 Android Kotlin data class 可能在迭代中出现字段不一致，导致解析失败或静默数据丢失",
            v2_anchors=[
                DualRepoCodeAnchor("v2", "contracts/handoff_envelope_v2.py", "V2 协议 envelope"),
                DualRepoCodeAnchor("v2", "core/cross_device_execution_chain.py", "跨设备执行链协议"),
            ],
            android_anchors=[
                DualRepoCodeAnchor("android", "AipModels.kt（103KB）", "Android 端完整 AIP 协议类型"),
            ],
            root_cause_ownership=DualRepoOwnership.DUAL_REPO,
            resolution_scope=DualRepoOwnership.DUAL_REPO,
        ),
        DualRepoIssue(
            issue_id="P3",
            title="Execution Runtime Truth Drift（执行运行时真相漂移）",
            issue_type="跨仓状态漂移",
            severity="high",
            impact="Android 本地执行进度（LoopController step 状态）与 V2 规范执行真相可能不一致，无 conflict resolution 协议",
            v2_anchors=[
                DualRepoCodeAnchor("v2", "core/unified_execution_governance.py get_uplink_truth_state()", "V2 规范执行真相"),
            ],
            android_anchors=[
                DualRepoCodeAnchor("android", "LoopController", "本地执行状态"),
                DualRepoCodeAnchor("android", "GalaxyWebSocketClient", "状态上报"),
            ],
            root_cause_ownership=DualRepoOwnership.DUAL_REPO,
            resolution_scope=DualRepoOwnership.DUAL_REPO,
        ),
        DualRepoIssue(
            issue_id="P4",
            title="Proof Overstatement（证明高估）",
            issue_type="Proof 质量问题",
            severity="medium",
            impact="系统级审查文档将'结构存在'误述为'运行级已证明'，导致外部观察者高估系统就绪程度",
            v2_anchors=[
                DualRepoCodeAnchor("v2", "core/unified_governance_semantics.py", "proof_quality 分级（需更严格应用）"),
                DualRepoCodeAnchor("v2", "core/execution_governance_audit_authority.py", "治理审计权威"),
            ],
            android_anchors=[],
            root_cause_ownership=DualRepoOwnership.V2_ONLY,
            resolution_scope=DualRepoOwnership.V2_ONLY,
        ),
        DualRepoIssue(
            issue_id="P5",
            title="Fake E2E（假 E2E 问题）",
            issue_type="测试证明弱",
            severity="high",
            impact="当前'E2E'测试实际为 V2 单侧 mock/stub，无法证明真实 Android → V2 完整执行链",
            v2_anchors=[
                DualRepoCodeAnchor("v2", "tests/integration/test_v2_android_protocol_regression.py", "跨仓 mock 协议回归（非真实双进程）"),
            ],
            android_anchors=[
                DualRepoCodeAnchor("android", "Pr8AndroidMeshParticipationContractTest.kt", "Android 本地测试（非跨仓）"),
            ],
            root_cause_ownership=DualRepoOwnership.DUAL_REPO,
            resolution_scope=DualRepoOwnership.DUAL_REPO,
        ),
        DualRepoIssue(
            issue_id="P6",
            title="Android Local Truth vs V2 Canonical Truth（本地真相 vs 规范真相分歧）",
            issue_type="真相分歧",
            severity="high",
            impact="Android 本地状态机可能与 V2 规范状态机产生分歧，无明确 conflict resolution 协议",
            v2_anchors=[
                DualRepoCodeAnchor("v2", "core/unified_execution_governance.py", "canonical truth"),
                DualRepoCodeAnchor("v2", "core/android_device_state_store.py", "Android 设备状态存储"),
            ],
            android_anchors=[
                DualRepoCodeAnchor("android", "LoopController 本地状态", "Android 本地步骤状态"),
                DualRepoCodeAnchor("android", "AppSettings", "本地配置"),
            ],
            root_cause_ownership=DualRepoOwnership.DUAL_REPO,
            resolution_scope=DualRepoOwnership.DUAL_REPO,
        ),
        DualRepoIssue(
            issue_id="P7",
            title="Resumed Ownership Transfer Proof 弱（恢复后接管所有权证明弱）",
            issue_type="接管恢复场景",
            severity="medium",
            impact="Android 接受接管后断连重连时，重连后 ownership 状态是否正确恢复无跨仓回归证据",
            v2_anchors=[
                DualRepoCodeAnchor("v2", "galaxy_gateway/android/handlers/takeover_response.py", "_resolve_session_id_for_takeover_response()"),
                DualRepoCodeAnchor("v2", "core/attached_runtime_recovery_readiness.py", "恢复就绪性"),
            ],
            android_anchors=[
                DualRepoCodeAnchor("android", "GalaxyWebSocketClient", "断连重连"),
                DualRepoCodeAnchor("android", "OfflineTaskQueue", "离线队列"),
            ],
            root_cause_ownership=DualRepoOwnership.DUAL_REPO,
            resolution_scope=DualRepoOwnership.DUAL_REPO,
        ),
        DualRepoIssue(
            issue_id="P8",
            title="Mesh runtime_closed 真实不可达（Mesh Runtime Closed Real Unreachability）",
            issue_type="Mesh 闭合",
            severity="high",
            impact="runtime_closed 态定义在 V2 状态机，但从未通过真实 Android 参与的完整 barrier 协调周期触发",
            v2_anchors=[
                DualRepoCodeAnchor("v2", "core/mesh/mesh_runtime_center_state.py", "runtime_closed 终止态（PR #1043）"),
                DualRepoCodeAnchor("v2", "core/mesh/live_mesh_runtime_engine.py", "live mesh 引擎"),
            ],
            android_anchors=[
                DualRepoCodeAnchor("android", "AndroidMeshParticipationContract", "deferred 声明"),
            ],
            root_cause_ownership=DualRepoOwnership.DUAL_REPO,
            resolution_scope=DualRepoOwnership.DUAL_REPO,
        ),
        DualRepoIssue(
            issue_id="P9",
            title="Observability Asymmetry（可观测性非对称）",
            issue_type="诊断缺口",
            severity="medium",
            impact="V2 侧观测面丰富，但 Android 本地 AI 状态（llama.cpp/NCNN 状态、LoopController 步骤）对 operator 不透明",
            v2_anchors=[
                DualRepoCodeAnchor("v2", "core/execution_governance_audit_authority.py", "治理审计权威（丰富）"),
                DualRepoCodeAnchor("v2", "galaxy_gateway/android/handlers/diagnostics.py", "Android 诊断接收（有限）"),
            ],
            android_anchors=[],
            root_cause_ownership=DualRepoOwnership.ANDROID_ONLY,
            resolution_scope=DualRepoOwnership.DUAL_REPO,
        ),
        DualRepoIssue(
            issue_id="P10",
            title="Definition Wording Overstatement（定义用词高估）",
            issue_type="证明质量问题",
            severity="low",
            impact="现有审查文档将若干'结构存在'项描述为'已闭合'或'已成立'，与实际跨仓 runtime 证据不符",
            v2_anchors=[
                DualRepoCodeAnchor("v2", "docs/JOINT_DUAL_REPO_COGNITION_CLOSURE_BASELINE_ZH.md", "旧审查文档"),
                DualRepoCodeAnchor("v2", "core/joint_dual_repo_cognition_closure_review.py", "PR #1041 contract"),
            ],
            android_anchors=[],
            root_cause_ownership=DualRepoOwnership.V2_ONLY,
            resolution_scope=DualRepoOwnership.V2_ONLY,
        ),
        DualRepoIssue(
            issue_id="P11",
            title="Android AppSettings vs V2 mode gate 同步缺失",
            issue_type="治理缺口",
            severity="high",
            impact="Android 本地模式门（cross_device_enabled 等）与 V2 mode gate 之间无实时同步确认协议，可能产生治理不一致",
            v2_anchors=[
                DualRepoCodeAnchor("v2", "core/android_mode_gate_policy.py", "V2 Android 模式门"),
            ],
            android_anchors=[
                DualRepoCodeAnchor("android", "AppSettings cross_device_enabled", "Android 本地模式门"),
            ],
            root_cause_ownership=DualRepoOwnership.DUAL_REPO,
            resolution_scope=DualRepoOwnership.DUAL_REPO,
        ),
        DualRepoIssue(
            issue_id="P12",
            title="Multimodal 运行级 E2E 证据不足",
            issue_type="运行级缺口",
            severity="medium",
            impact="多模态主链（Android 感知 → V2 ingress → 推理 → 执行）无跨仓真实运行证明",
            v2_anchors=[
                DualRepoCodeAnchor("v2", "core/multimodal/ingress_bus.py", "多模态感知总线"),
                DualRepoCodeAnchor("v2", "core/android_nl_semantic_chain_contract.py", "Android NL 语义链契约"),
            ],
            android_anchors=[
                DualRepoCodeAnchor("android", "AccessibilityScreenshotProvider", "视觉感知"),
            ],
            root_cause_ownership=DualRepoOwnership.DUAL_REPO,
            resolution_scope=DualRepoOwnership.DUAL_REPO,
        ),
    ]


def _build_e2e_classifications() -> List[FakeVsTrueE2EClassification]:
    """构建 Fake E2E vs True E2E 分类列表。"""
    return [
        FakeVsTrueE2EClassification(
            test_id="T01",
            test_file="tests/test_pr11_governance_closure_verification.py（36 tests）",
            test_repo="v2",
            classification=E2E_CLASS_V2_UNIT,
            what_it_proves="V2 生命周期协调器内部逻辑正确性（PR-11-V2）",
            what_it_does_not_prove="跨仓真实 Android 行为、真实接管响应传输",
        ),
        FakeVsTrueE2EClassification(
            test_id="T02",
            test_file="tests/test_pr14_governance_audit_authority.py（41 tests，A–E 组）",
            test_repo="v2",
            classification=E2E_CLASS_V2_UNIT,
            what_it_proves="V2 治理审计权威链内部正确性（PR-14-V2）",
            what_it_does_not_prove="Android 真实审计信号处理",
        ),
        FakeVsTrueE2EClassification(
            test_id="T03",
            test_file="tests/test_pr03_mesh_runtime_center_closure.py（116 tests，A–R 组）",
            test_repo="v2",
            classification=E2E_CLASS_V2_UNIT,
            what_it_proves="V2 中心 mesh 状态机转换正确性（PR #1043）",
            what_it_does_not_prove="真实 Android mesh 参与、runtime_closed 真实触发",
        ),
        FakeVsTrueE2EClassification(
            test_id="T04",
            test_file="tests/test_pr8v2_mesh_proof_degradation_semantics.py（33 tests，A–E 组）",
            test_repo="v2",
            classification=E2E_CLASS_V2_UNIT,
            what_it_proves="proof quality 降级语义逻辑正确性",
            what_it_does_not_prove="真实 mesh 证明质量测量、Android 参与后的 proof 状态",
        ),
        FakeVsTrueE2EClassification(
            test_id="T05",
            test_file="tests/test_android_mode_switch_integration.py",
            test_repo="v2",
            classification=E2E_CLASS_V2_STUB,
            what_it_proves="V2 接收 Android 模式切换消息的处理逻辑",
            what_it_does_not_prove="Android 真实模式切换行为、AppSettings 与 V2 门控一致性",
        ),
        FakeVsTrueE2EClassification(
            test_id="T06",
            test_file="tests/test_android_device_state_store.py",
            test_repo="v2",
            classification=E2E_CLASS_V2_STUB,
            what_it_proves="V2 侧设备状态存储逻辑",
            what_it_does_not_prove="Android 真实状态上报序列",
        ),
        FakeVsTrueE2EClassification(
            test_id="T07",
            test_file="tests/test_pr4v2_android_participant_truth_ingress.py",
            test_repo="v2",
            classification=E2E_CLASS_V2_STUB,
            what_it_proves="V2 侧 participant truth ingress 处理逻辑",
            what_it_does_not_prove="Android 真实 truth 信号发送行为",
        ),
        FakeVsTrueE2EClassification(
            test_id="T08",
            test_file="tests/integration/test_v2_android_protocol_regression.py",
            test_repo="v2",
            classification=E2E_CLASS_CROSS_REPO_MOCK,
            what_it_proves="协议 schema 契约级正确性（mock 级别）",
            what_it_does_not_prove="真实 Android 运行时行为、网络层异常、真实 WebSocket 传输",
        ),
        FakeVsTrueE2EClassification(
            test_id="T09",
            test_file="Pr8AndroidMeshParticipationContractTest.kt（Android 仓）",
            test_repo="android",
            classification=E2E_CLASS_ANDROID_UNIT,
            what_it_proves="Android mesh 参与契约本地逻辑",
            what_it_does_not_prove="V2 侧 mesh 消费行为、跨仓 barrier 协调",
        ),
        FakeVsTrueE2EClassification(
            test_id="T10",
            test_file="tests/test_pr6_hybrid_continuity_closure.py",
            test_repo="v2",
            classification=E2E_CLASS_V2_STUB,
            what_it_proves="V2 侧 hybrid continuity 处理",
            what_it_does_not_prove="真实 Android 断连重连、OfflineTaskQueue 与 V2 状态保持联动",
        ),
        FakeVsTrueE2EClassification(
            test_id="T_NONE",
            test_file="（不存在）",
            test_repo="both",
            classification=E2E_CLASS_TRUE_CROSS_REPO,
            what_it_proves="N/A — 真实双运行时回归测试当前不存在",
            what_it_does_not_prove="所有真实跨仓运行时语义均未经真实双进程回归验证",
        ),
    ]


def _build_roadmap() -> List[DualRepoPRRoadmapItem]:
    """构建双仓 PR 路线图。"""
    return [
        DualRepoPRRoadmapItem(
            pr_id="PR-ROADMAP-01",
            title="跨仓协议 Schema 一致性门控",
            repo_scope=DualRepoOwnership.DUAL_REPO,
            targeted_problems=["P2（Schema drift）"],
            key_landing_zones_v2=["contracts/handoff_envelope_v2.py", "CI 校验脚本"],
            key_landing_zones_android=["AipModels.kt", "CI JSON schema 对比"],
            dependencies=[],
            acceptance_criteria=[
                "V2 和 Android 核心消息类型字段在 CI 中自动比对",
                "schema 不一致时阻断 PR 合并",
            ],
            definition_fulfillment_advance="消除最高优先级跨仓静默 drift 风险，为 P1/P3 治理奠定基础",
        ),
        DualRepoPRRoadmapItem(
            pr_id="PR-ROADMAP-02",
            title="Android AppSettings 门与 V2 mode gate 双向同步协议",
            repo_scope=DualRepoOwnership.DUAL_REPO,
            targeted_problems=["P1（Capability drift）", "P11（门控同步缺失）", "P6（local truth vs canonical truth）"],
            key_landing_zones_v2=["core/android_mode_gate_policy.py", "新增门控同步验证 API"],
            key_landing_zones_android=["AppSettings", "新增门控状态上报消息"],
            dependencies=["PR-ROADMAP-01"],
            acceptance_criteria=[
                "Android 关键 flag 变化时，V2 侧自动感知并更新 mode gate 状态",
                "门控状态差异超过阈值时触发 reconciliation",
            ],
            definition_fulfillment_advance="消除治理一致性最大风险，推进 D1/D8 定义域满足度",
        ),
        DualRepoPRRoadmapItem(
            pr_id="PR-ROADMAP-03",
            title="Android 结构化诊断接口（可观测性对称化）",
            repo_scope=DualRepoOwnership.DUAL_REPO,
            targeted_problems=["P9（Observability asymmetry）"],
            key_landing_zones_v2=["galaxy_gateway/android/handlers/diagnostics.py", "core/routes/panel.py"],
            key_landing_zones_android=["新增结构化诊断上报接口（AI 推理状态、LoopController 状态）"],
            dependencies=["PR-ROADMAP-01"],
            acceptance_criteria=[
                "V2 侧 /api/v1/panel/unified 能展示 Android 本地 AI 推理状态（llama.cpp/NCNN 是否可用）",
                "可在 operator 面查询 Android 本地 LoopController 步骤状态",
            ],
            definition_fulfillment_advance="实现可观测性对称化，满足 PR #993 D7 定义中 Android 状态透明度要求",
        ),
        DualRepoPRRoadmapItem(
            pr_id="PR-ROADMAP-04",
            title="Capability 双向同步协议（消除 capability drift）",
            repo_scope=DualRepoOwnership.DUAL_REPO,
            targeted_problems=["P1（Capability drift）"],
            key_landing_zones_v2=["core/canonical_capability_status.py", "新增 capability_ack 下发"],
            key_landing_zones_android=["接收 capability_ack 并更新本地状态"],
            dependencies=["PR-ROADMAP-01", "PR-ROADMAP-02"],
            acceptance_criteria=[
                "Android 汇报能力变化后，V2 回发 capability_ack",
                "Android 本地状态与 V2 canonical 状态差异 < 1 个心跳周期",
            ],
            definition_fulfillment_advance="消除 capability drift，提升 D8 定义域满足度至充分",
        ),
        DualRepoPRRoadmapItem(
            pr_id="PR-ROADMAP-05",
            title="真实跨仓双运行时回归测试框架",
            repo_scope=DualRepoOwnership.DUAL_REPO,
            targeted_problems=["P5（Fake E2E）", "P8（Mesh runtime_closed 不可达）"],
            key_landing_zones_v2=["tests/integration/ 新增真实双进程测试基础设施"],
            key_landing_zones_android=["新增集成测试 runner（Android emulator/真实设备 JVM）"],
            dependencies=["PR-ROADMAP-01", "PR-ROADMAP-02"],
            acceptance_criteria=[
                "至少一条 Android → V2 → Android 真实全链路回归测试可通过 CI",
                "runtime_closed 状态可在真实 Android 参与后被触发",
            ],
            definition_fulfillment_advance="将测试证明质量从 V2-only 升级到 runtime_grounded，满足 PR #1041 proof 质量要求",
        ),
        DualRepoPRRoadmapItem(
            pr_id="PR-ROADMAP-06",
            title="Execution Runtime Truth 一致性协议",
            repo_scope=DualRepoOwnership.DUAL_REPO,
            targeted_problems=["P3（Execution runtime truth drift）", "P6（local truth vs canonical truth）"],
            key_landing_zones_v2=["core/unified_execution_governance.py", "新增 execution state reconciliation API"],
            key_landing_zones_android=["LoopController 新增周期性状态上报（heartbeat with step progress）"],
            dependencies=["PR-ROADMAP-01", "PR-ROADMAP-02"],
            acceptance_criteria=[
                "Android step 执行状态差异在 V2 侧可被检测到",
                "超过阈值时触发 reconciliation 流程，无静默分歧状态",
            ],
            definition_fulfillment_advance="解决执行状态最高严重度双仓漂移，满足 PR #1042 runtime truth 绑定定义",
        ),
        DualRepoPRRoadmapItem(
            pr_id="PR-ROADMAP-07",
            title="Resumed Ownership Transfer 完整回归闭合",
            repo_scope=DualRepoOwnership.DUAL_REPO,
            targeted_problems=["P7（Resumed ownership transfer proof 弱）"],
            key_landing_zones_v2=["core/attached_runtime_recovery_readiness.py", "core/android_v2_continuity_contract.py"],
            key_landing_zones_android=["断连重连后 ownership 状态恢复逻辑"],
            dependencies=["PR-ROADMAP-05"],
            acceptance_criteria=[
                "Android 接受接管后断连，重连后 V2 侧 ownership 状态正确恢复",
                "回归测试可通过（需真实双运行时框架）",
            ],
            definition_fulfillment_advance="满足 PR #993 中 Android 可接管参与者的完整接管语义",
        ),
        DualRepoPRRoadmapItem(
            pr_id="PR-ROADMAP-08",
            title="Proof Quality 自动化报告与门控",
            repo_scope=DualRepoOwnership.V2_ONLY,
            targeted_problems=["P4（Proof overstatement）", "P10（Definition wording overstatement）"],
            key_landing_zones_v2=[
                "core/execution_governance_audit_authority.py",
                "core/joint_dual_repo_cognition_closure_review.py",
                "core/dual_repo_centered_system_audit_contract.py（本模块）",
            ],
            key_landing_zones_android=[],
            dependencies=[],
            acceptance_criteria=[
                "每个系统级命题自动输出 proof quality 分级（structural_only/v2_regression/cross_repo_mock/runtime_grounded）",
                "scorecard 中 runtime_grounded 项需真实跨仓回归支持才可标记",
            ],
            definition_fulfillment_advance="消除审计结论和实际状态的系统性高估，使 PR #1041 scorecard 更可靠",
        ),
    ]


def build_dual_repo_centered_system_audit() -> DualRepoCenteredSystemAuditReport:
    """构建完整的双仓中心化分布式系统审计报告。

    Returns
    -------
    DualRepoCenteredSystemAuditReport
        包含 8 个定义域审计、路径追踪、12 个综合问题、11 个 E2E 分类、
        8 条路线图 PR、以及最终中文决策结论的完整审计报告。
    """
    return DualRepoCenteredSystemAuditReport(
        contract_version=DUAL_REPO_CENTERED_SYSTEM_AUDIT_CONTRACT_VERSION,
        authority=DUAL_REPO_CENTERED_SYSTEM_AUDIT_AUTHORITY,
        baseline_prs=DUAL_REPO_AUDIT_BASELINE_PRS,
        system_nature_verdict=SystemNatureVerdict.CENTER_GOVERNED_DISTRIBUTED_NETWORK,
        system_nature_description=SYSTEM_NATURE_DEFINITION,
        definition_area_audits=_build_definition_area_audits(),
        canonical_path_traces=_build_canonical_path_traces(),
        combined_issues=_build_combined_issues(),
        e2e_classifications=_build_e2e_classifications(),
        roadmap=_build_roadmap(),
        overall_system_description_zh=(
            "这套系统是以 ufo-galaxy-realization-v2 为中心治理核的中心化分布式智能网络系统。"
            "V2 持有全部治理权威（调度/路由/任务真相/capability truth/配置/设备准入/gateway/operator 汇聚）。"
            "Android 是强运行参与节点（本地执行/本地 AI/可接管参与/跨设备参与/多模态感知发射）。"
            "两仓通过 WebSocket + AIP 协议构成中心化分布式智能网络，共同承载一个 AI 主体的认知-执行-感知-显化循环。"
            "系统已越过 PoC 阶段，处于 mid-stage consolidation。V2 内部治理充分，跨仓运行级闭合是主要剩余债务。"
        ),
        current_completion_stage="mid_stage_consolidation",
        pr_993_fulfillment=DefinitionFulfillmentStatus.PARTIALLY_FULFILLED,
        pr_1041_fulfillment=DefinitionFulfillmentStatus.PARTIALLY_FULFILLED,
        pr_1042_fulfillment=DefinitionFulfillmentStatus.FULFILLED,
        pr_1043_fulfillment=DefinitionFulfillmentStatus.PARTIALLY_FULFILLED,
        claims_backed_by_real_code=[
            "V2 是唯一中心治理权威（8 个治理维度均有 V2 代码锚点）",
            "Android 是可接管的强运行参与节点（handlers/lifecycle coordinator 完整）",
            "V2 execution governance 与 runtime 状态强绑定（PR #1042 引入 get_execution_runtime_snapshot()）",
            "V2 mesh 中心状态机已形成（PR #1043 的 10 态状态机 + 116 测试）",
            "V2 lifecycle coordinator 统一 facade 已形成（PR-11-V2）",
            "V2 治理审计权威链已形成（PR-14-V2）",
            "proof quality 分级已在治理语义层输出（live/stale/structurally_inferred/missing）",
            "Android 本地 AI 结构（llama.cpp + NCNN）已存在（gradle 依赖已确认）",
        ],
        claims_structural_or_v2_only=[
            "跨仓 E2E 闭合——实际仅有 V2 侧 mock/stub",
            "mesh full runtime closed（runtime_closed 态真实触发 deferred）",
            "Android local truth 与 V2 canonical truth 对齐——无双向同步协议",
            "resumed ownership transfer 正确性——无跨仓回归测试",
            "capability drift 消除——无双向能力同步协议",
            "schema drift 已门控——无跨仓协议 CI 验证",
        ],
        top_combined_system_gaps=[
            "P2：跨仓协议 Schema drift 无 CI 门控（最高优先级，无声 drift 风险）",
            "P5：所有'E2E'声明均基于 mock，无真实双进程回归",
            "P3：Android/V2 执行状态分歧无 conflict resolution 协议",
            "P8：Mesh runtime_closed 从未通过真实 Android 参与触发",
            "P1/P4：能力状态单向上报，无回传确认，drift 无检测机制",
            "P9：Android 本地 AI 状态对 V2 operator 不透明",
        ],
    )


def get_cross_repo_proof_summary(
    report: Optional[DualRepoCenteredSystemAuditReport] = None,
) -> Dict[str, Any]:
    """提取跨仓证明质量摘要。

    Parameters
    ----------
    report:
        审计报告实例；若为 None 则自动构建。

    Returns
    -------
    Dict[str, Any]
        以定义域 ID 为 key 的证明质量摘要。
    """
    if report is None:
        report = build_dual_repo_centered_system_audit()
    return {
        audit.domain_id: {
            "domain_name": audit.domain_name,
            "proof_quality": audit.proof_quality.value,
            "fulfillment_status": audit.fulfillment_status.value,
        }
        for audit in report.definition_area_audits
    }


def get_combined_issue_list(
    report: Optional[DualRepoCenteredSystemAuditReport] = None,
    severity_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """提取双仓综合问题列表。

    Parameters
    ----------
    report:
        审计报告实例；若为 None 则自动构建。
    severity_filter:
        若提供，则只返回该严重度的问题（"high" / "medium" / "low"）。

    Returns
    -------
    List[Dict[str, Any]]
        问题字典列表。
    """
    if report is None:
        report = build_dual_repo_centered_system_audit()
    issues = [i.to_dict() for i in report.combined_issues]
    if severity_filter:
        issues = [i for i in issues if i["severity"] == severity_filter]
    return issues


def get_roadmap(
    report: Optional[DualRepoCenteredSystemAuditReport] = None,
    repo_scope_filter: Optional[DualRepoOwnership] = None,
) -> List[Dict[str, Any]]:
    """提取双仓 PR 路线图。

    Parameters
    ----------
    report:
        审计报告实例；若为 None 则自动构建。
    repo_scope_filter:
        若提供，则只返回该仓库范围的 PR（V2_ONLY / ANDROID_ONLY / DUAL_REPO）。

    Returns
    -------
    List[Dict[str, Any]]
        路线图 PR 字典列表。
    """
    if report is None:
        report = build_dual_repo_centered_system_audit()
    items = [r.to_dict() for r in report.roadmap]
    if repo_scope_filter:
        items = [i for i in items if i["repo_scope"] == repo_scope_filter.value]
    return items
