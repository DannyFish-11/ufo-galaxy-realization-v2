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
class JointCognitionClosureReport:
    authority: str = JOINT_COGNITION_CLOSURE_AUTHORITY
    methodology: str = JOINT_COGNITION_CLOSURE_METHODOLOGY
    generated_at: float = field(default_factory=time.time)
    propositions: List[SystemPropositionReview] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authority": self.authority,
            "methodology": self.methodology,
            "generated_at": self.generated_at,
            "propositions": [p.to_dict() for p in self.propositions],
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

    return JointCognitionClosureReport(propositions=propositions)


__all__ = [
    "JOINT_COGNITION_CLOSURE_AUTHORITY",
    "JOINT_COGNITION_CLOSURE_METHODOLOGY",
    "PropositionVerdict",
    "ClosureBoundary",
    "SystemPropositionReview",
    "JointCognitionClosureReport",
    "build_joint_dual_repo_cognition_closure_review",
]
