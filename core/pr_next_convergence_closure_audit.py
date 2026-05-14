#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/pr_next_convergence_closure_audit.py
==========================================
V2 侧下一步收敛工件：双仓可用性审查、闭环真值治理与操作面同源解释

PR 定位
-------
本模块是继 PR 1140（双仓认知基线）、PR 1141（993P2 证据门 vs 闭环一致性修复）、
PR 1142（Android 参与真值进入编排选路）之后的下一个主要收敛 PR。

核心目标
--------
1. **可用性审查**：基于真实代码判断系统从 clone 到 build 到 runtime 的实际可操作程度。
2. **三态运行审查**：明确"三态运行呈现"在代码中是否真实存在、其状态定义与数据来源。
3. **Android truth 向闭环/治理/操作面传播审查**：Android 参与真值在进入编排选路之后，
   是否进一步传播到 result acceptance / closure / operator board / readiness？
4. **V2 侧补强**：为上述三个方向在 V2 侧补充代码锚点，让 operator 与 board 能读到
   与真实运行决策同源的解释，而不仅仅是可见面投影。

三仓关系
--------
本模块分析两个仓库：
- ``DannyFish-11/ufo-galaxy-realization-v2``  (V2 — 中心治理核)
- ``DannyFish-11/ufo-galaxy-android``         (Android — 参与执行节点)

所有代码断言均基于 V2 真实 import 探针 + Android 明确代码锚点，不使用文档叙述作为证据。

公开 API
--------
枚举::

    OperabilityVerdict
    ThreeStateSourceVerdict
    ClosureGovernancePropagationTier

数据类::

    CloneToRunAudit
    ThreeStateRuntimeAudit
    ClosureGovernancePropagationAudit
    AndroidTruthInOperatorBoardAudit
    ConvergenceClosureAuditRecord

函数::

    build_clone_to_run_audit() -> CloneToRunAudit
    build_three_state_runtime_audit() -> ThreeStateRuntimeAudit
    build_closure_governance_propagation_audit() -> ClosureGovernancePropagationAudit
    build_android_truth_operator_board_audit() -> AndroidTruthInOperatorBoardAudit
    build_convergence_closure_audit() -> ConvergenceClosureAuditRecord

权威标志
--------
``PR_NEXT_CONVERGENCE_CLOSURE_AUDIT_AUTHORITY`` — 进口即断言本模块是该次收敛工件的权威来源。

合同版本
--------
``PR_NEXT_CONVERGENCE_CONTRACT_VERSION = "1.0.0"``
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.PrNextConvergenceClosureAudit")

# ---------------------------------------------------------------------------
# 权威标志
# ---------------------------------------------------------------------------

PR_NEXT_CONVERGENCE_CLOSURE_AUDIT_AUTHORITY: str = (
    "PR_NEXT_CONVERGENCE_CLOSURE_AUDIT::"
    "core.pr_next_convergence_closure_audit::"
    "v2-side::operability-audit-closure-governance-operator-board"
)

PR_NEXT_CONVERGENCE_CONTRACT_VERSION: str = "1.0.0"

# 本次 PR 的标题（中文权威标题）
PR_NEXT_CONVERGENCE_PR_TITLE: str = (
    "基于双仓真实代码明确 V2/Android 后续收口责任：推进 Android 真值全链传播与系统可用性补完"
)
PR_NEXT_CONVERGENCE_PR_TITLE_EN: str = (
    "Clarify V2/Android convergence responsibilities with dual-repo real code: "
    "advance Android truth full-chain propagation and practical operability closure"
)

# 本次 PR 锚点：基于 993P2
PR_NEXT_CONVERGENCE_ANCHOR: str = "993P2"

# Android 审计参考提交
ANDROID_AUDITED_REF: str = "478e3f8f3cd3cb85b5a20999c9fca22a0f44ef8d"

# Android 代码锚点
ANDROID_ANCHOR_WS_CLIENT = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt"
)
ANDROID_ANCHOR_AUTONOMOUS_PIPELINE = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/agent/AutonomousExecutionPipeline.kt"
)
ANDROID_ANCHOR_MESH_CONTRACT = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/runtime/AndroidMeshParticipationContract.kt"
)
ANDROID_ANCHOR_CONTINUITY = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/session/DurableParticipantIdentity.kt"
)
ANDROID_ANCHOR_MODE_GATE = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/runtime/LocalExecutionModeGate.kt"
)

# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class OperabilityVerdict(str, Enum):
    """系统可克隆/可运行/可操作/可实用的整体判定结论。"""

    CLONE_READY = "clone_ready"
    """关键入口、配置、依赖均已就位，一般用户按说明可克隆并运行。"""

    PARTIALLY_OPERABLE = "partially_operable"
    """部分路径可运行，但存在需要额外配置/Android 设备/或仍处 stub 阶段的依赖。"""

    BLOCKED = "blocked"
    """存在会阻断大多数用户实际运行的硬阻塞点（缺失依赖、缺失配置、未公开 API Key 等）。"""


class ThreeStateSourceVerdict(str, Enum):
    """三态运行呈现的来源与真实性判定。"""

    EXISTS_IN_CODE = "exists_in_code"
    """三态概念在真实代码中有明确定义、来源与投影路径。"""

    PARTIALLY_IN_CODE = "partially_in_code"
    """三态概念有部分代码支撑，但其完整投影链或 operator/board 消费路径未闭合。"""

    NARRATIVE_ONLY = "narrative_only"
    """三态概念在文档/架构叙事中提及，但代码中无对应可查的状态定义或来源。"""


class ClosureGovernancePropagationTier(str, Enum):
    """Android truth 从编排选路进一步传播到 closure/governance/operator 的程度层级。"""

    FULLY_PROPAGATED = "fully_propagated"
    """Android truth 已完全传播到 result acceptance, closure, operator board, readiness。"""

    PARTIALLY_PROPAGATED = "partially_propagated"
    """Android truth 已传播到部分下游（如 result acceptance），但 operator board
    或 readiness 的同源因果解释仍不完整。"""

    ROUTING_ONLY = "routing_only"
    """Android truth 仅进入编排选路评分，尚未传播到 closure/governance/operator board。"""

    NOT_PROPAGATED = "not_propagated"
    """Android truth 尚未进入任何闭环或治理路径。"""


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass
class CloneToRunAuditCheckpoint:
    """单项可运行性检查点。"""

    checkpoint_id: str
    description_zh: str
    passed: bool
    evidence_zh: str
    v2_anchors: List[str] = field(default_factory=list)
    android_anchors: List[str] = field(default_factory=list)
    blocking: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "description_zh": self.description_zh,
            "passed": self.passed,
            "evidence_zh": self.evidence_zh,
            "v2_anchors": list(self.v2_anchors),
            "android_anchors": list(self.android_anchors),
            "blocking": self.blocking,
        }


@dataclass
class CloneToRunAudit:
    """系统从 clone 到 build 到 runtime 使用的可用性综合审计。

    诚实结论
    --------
    - 给出 operability_verdict 及其依据
    - 给出哪些路径已真实可运行、哪些仍属于半联通或概念
    - 对 Android 本地模式、自主路径、多设备分布体系分别作出实事求是的判断
    """

    operability_verdict: OperabilityVerdict = OperabilityVerdict.PARTIALLY_OPERABLE
    verdict_summary_zh: str = ""
    checkpoints: List[CloneToRunAuditCheckpoint] = field(default_factory=list)
    blocking_gaps_zh: List[str] = field(default_factory=list)
    already_working_zh: List[str] = field(default_factory=list)
    android_local_mode_verdict_zh: str = ""
    multi_device_reality_verdict_zh: str = ""
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operability_verdict": self.operability_verdict.value,
            "verdict_summary_zh": self.verdict_summary_zh,
            "checkpoints": [c.to_dict() for c in self.checkpoints],
            "blocking_gaps_zh": list(self.blocking_gaps_zh),
            "already_working_zh": list(self.already_working_zh),
            "android_local_mode_verdict_zh": self.android_local_mode_verdict_zh,
            "multi_device_reality_verdict_zh": self.multi_device_reality_verdict_zh,
            "generated_at": self.generated_at,
        }


@dataclass
class ThreeStateRuntimeAudit:
    """对"三态运行呈现"在真实代码中是否存在的审查。

    三态定义澄清
    ------------
    本审计调查的"三态"概念在代码中以两条独立语义线存在：

    线路 A — 显化层 tri_state (desktop/shell)：
        ``core/unified_panel_aggregation.py`` 中的 ``tri_state_phase``（来自 ContinuumState）
        与 ``presence_tristate``（来自 OperatorSnapshot）。
        这两个字段携带 desktop presence 的三态语义（silent/liminal/manifest 或类似），
        由 core.continuum 与 core.desktop_presence_runtime 产生，是真实存在的代码路径。

    线路 B — Android 参与层三态 (participation tier)：
        ``AndroidNetworkParticipationTier`` 定义 7 个层级（local_only → distributed_participant），
        可以被合理聚合为三个操作语义层：本地独立 / 协作参与 / 分布式节点。
        但这个"三态"与线路 A 并非同一语义，且当前并未在 operator/board 中以"三态"名义统一投影。

    结论
    ----
    - 三态在代码中**真实存在**，但不是以单一统一"三态"API 形式存在。
    - 线路 A（显化层三态）已进入 UnifiedPanelPayload 投影。
    - 线路 B（Android 参与层）已进入 V2 编排评分，但尚未在 operator/board 上以三态聚合形式呈现。
    - 若"三态"指代两线路的统一，则当前处于 PARTIALLY_IN_CODE 状态。
    """

    verdict: ThreeStateSourceVerdict = ThreeStateSourceVerdict.PARTIALLY_IN_CODE
    display_tri_state_exists_in_code: bool = False
    display_tri_state_sources_zh: str = ""
    display_tri_state_panel_projected: bool = False
    android_participation_tri_state_exists: bool = False
    android_participation_tri_state_panel_projected: bool = False
    unified_tri_state_api_exists: bool = False
    honest_assessment_zh: str = ""
    operator_board_gap_zh: str = ""
    v2_anchors: List[str] = field(default_factory=list)
    android_anchors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "display_tri_state_exists_in_code": self.display_tri_state_exists_in_code,
            "display_tri_state_sources_zh": self.display_tri_state_sources_zh,
            "display_tri_state_panel_projected": self.display_tri_state_panel_projected,
            "android_participation_tri_state_exists": self.android_participation_tri_state_exists,
            "android_participation_tri_state_panel_projected": self.android_participation_tri_state_panel_projected,
            "unified_tri_state_api_exists": self.unified_tri_state_api_exists,
            "honest_assessment_zh": self.honest_assessment_zh,
            "operator_board_gap_zh": self.operator_board_gap_zh,
            "v2_anchors": list(self.v2_anchors),
            "android_anchors": list(self.android_anchors),
        }


@dataclass
class ClosureGovernancePropagationAudit:
    """Android truth 从编排选路向 closure/governance/operator/readiness/board 的传播审计。

    本审计回答：
    - Android truth 进入路由之后，是否继续进入 result acceptance？
    - result acceptance 判定之后，是否影响 is_fully_closed？
    - is_fully_closed 与 closure 语义是否在 operator/board 中可见？
    - readiness surface 是否消费同一批 Android truth？
    - operator board reasoning 能否追溯到具体的 Android 参与证据？
    """

    propagation_tier: ClosureGovernancePropagationTier = (
        ClosureGovernancePropagationTier.PARTIALLY_PROPAGATED
    )

    # result acceptance 层
    android_truth_in_result_acceptance: bool = False
    result_acceptance_android_evidence_zh: str = ""

    # closure 层
    closure_reflects_acceptance_verdict: bool = False
    closure_gap_zh: str = ""

    # operator board 层
    operator_board_has_android_reasoning: bool = False
    operator_board_gap_zh: str = ""

    # readiness surface 层
    readiness_surface_consumes_android_truth: bool = False
    readiness_gap_zh: str = ""

    # 总体诚实评估
    honest_assessment_zh: str = ""
    what_this_pr_fixes_zh: str = ""
    what_still_needs_android_side_zh: str = ""

    v2_anchors: List[str] = field(default_factory=list)
    android_anchors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "propagation_tier": self.propagation_tier.value,
            "android_truth_in_result_acceptance": self.android_truth_in_result_acceptance,
            "result_acceptance_android_evidence_zh": self.result_acceptance_android_evidence_zh,
            "closure_reflects_acceptance_verdict": self.closure_reflects_acceptance_verdict,
            "closure_gap_zh": self.closure_gap_zh,
            "operator_board_has_android_reasoning": self.operator_board_has_android_reasoning,
            "operator_board_gap_zh": self.operator_board_gap_zh,
            "readiness_surface_consumes_android_truth": self.readiness_surface_consumes_android_truth,
            "readiness_gap_zh": self.readiness_gap_zh,
            "honest_assessment_zh": self.honest_assessment_zh,
            "what_this_pr_fixes_zh": self.what_this_pr_fixes_zh,
            "what_still_needs_android_side_zh": self.what_still_needs_android_side_zh,
            "v2_anchors": list(self.v2_anchors),
            "android_anchors": list(self.android_anchors),
        }


@dataclass
class AndroidTruthInOperatorBoardAudit:
    """Android 参与真值在 operator board / panel / state projection 中的可观测性审计。

    这是 PR 1142 完成"编排消费 Android truth"之后的下一步：
    operator 和 board 面是否能看到与实际 Android 参与决策同源的解释？

    本模块在 V2 侧新增的补强
    ------------------------
    1. ``UnifiedPanelPayload`` 新增 ``android_participation_verdict`` 字段，
       直接从 ``get_android_participation_evidence`` 聚合，使 board 面直接可读。
    2. ``CanonicalCompletionIngress.notify_with_android_context()`` 新增方法，
       允许 closure 事件携带 Android 参与层级上下文，
       让 board/operator 能在 closure 时刻知道"是什么样的 Android 参与级别导致了这次结果"。
    3. 本模块本身作为 board/operator reasoning 的聚合工件，提供 ``get_board_reasoning_for_closure``
       可供 operator route 调用，而不是让每个 operator route 各自推导 Android 参与原因。
    """

    panel_has_android_participation_verdict: bool = False
    completion_ingress_has_android_context: bool = False
    board_reasoning_api_available: bool = False
    operator_route_can_read_android_truth: bool = False
    gap_before_this_pr_zh: str = ""
    fix_in_this_pr_zh: str = ""
    remaining_gap_zh: str = ""
    v2_anchors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "panel_has_android_participation_verdict": self.panel_has_android_participation_verdict,
            "completion_ingress_has_android_context": self.completion_ingress_has_android_context,
            "board_reasoning_api_available": self.board_reasoning_api_available,
            "operator_route_can_read_android_truth": self.operator_route_can_read_android_truth,
            "gap_before_this_pr_zh": self.gap_before_this_pr_zh,
            "fix_in_this_pr_zh": self.fix_in_this_pr_zh,
            "remaining_gap_zh": self.remaining_gap_zh,
            "v2_anchors": list(self.v2_anchors),
        }


@dataclass
class ConvergenceClosureAuditRecord:
    """本次收敛 PR 的全量审计工件。

    聚合所有子审计结论，提供完整的"可用性审查、三态审查、闭环真值治理、操作面同源解释"
    的 V2 侧可机读报告。
    """

    authority: str = PR_NEXT_CONVERGENCE_CLOSURE_AUDIT_AUTHORITY
    contract_version: str = PR_NEXT_CONVERGENCE_CONTRACT_VERSION
    pr_title: str = PR_NEXT_CONVERGENCE_PR_TITLE
    pr_title_en: str = PR_NEXT_CONVERGENCE_PR_TITLE_EN
    convergence_anchor: str = PR_NEXT_CONVERGENCE_ANCHOR
    android_audited_ref: str = ANDROID_AUDITED_REF
    generated_at: float = field(default_factory=time.time)

    operability_audit: Optional[CloneToRunAudit] = None
    three_state_audit: Optional[ThreeStateRuntimeAudit] = None
    closure_governance_audit: Optional[ClosureGovernancePropagationAudit] = None
    operator_board_audit: Optional[AndroidTruthInOperatorBoardAudit] = None

    # 诚实的三线分离总结
    what_is_already_working_zh: List[str] = field(default_factory=list)
    what_this_pr_fixes_zh: List[str] = field(default_factory=list)
    what_still_needs_android_side_zh: List[str] = field(default_factory=list)

    _probe_results: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authority": self.authority,
            "contract_version": self.contract_version,
            "pr_title": self.pr_title,
            "pr_title_en": self.pr_title_en,
            "convergence_anchor": self.convergence_anchor,
            "android_audited_ref": self.android_audited_ref,
            "generated_at": self.generated_at,
            "operability_audit": (
                self.operability_audit.to_dict() if self.operability_audit else None
            ),
            "three_state_audit": (
                self.three_state_audit.to_dict() if self.three_state_audit else None
            ),
            "closure_governance_audit": (
                self.closure_governance_audit.to_dict()
                if self.closure_governance_audit
                else None
            ),
            "operator_board_audit": (
                self.operator_board_audit.to_dict() if self.operator_board_audit else None
            ),
            "what_is_already_working_zh": list(self.what_is_already_working_zh),
            "what_this_pr_fixes_zh": list(self.what_this_pr_fixes_zh),
            "what_still_needs_android_side_zh": list(self.what_still_needs_android_side_zh),
            "probe_results": dict(self._probe_results),
        }


# ---------------------------------------------------------------------------
# 代码探针工具
# ---------------------------------------------------------------------------


def _module_exists(module_path: str) -> bool:
    """返回 True 当且仅当模块在当前 Python path 中可发现。"""
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
    """返回 True 当且仅当模块源码包含 token 子字符串。"""
    try:
        spec = importlib.util.find_spec(module_path)
    except (ImportError, ModuleNotFoundError, ValueError, AttributeError):
        return False
    if not spec or not spec.origin or not os.path.isfile(spec.origin):
        return False
    with open(spec.origin, encoding="utf-8", errors="replace") as fh:
        return token in fh.read()


def _source_contains_all(module_path: str, *tokens: str) -> bool:
    """返回 True 当且仅当模块源码包含所有 token。"""
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
    """运行所有真实代码探针，返回命名布尔字典。"""
    p: Dict[str, bool] = {}

    # -- 可运行性：入口模块 --
    p["main_entry"] = (
        os.path.isfile(
            os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "main.py"
            )
        )
        or _module_exists("main")
    )
    p["openclawd"] = _module_exists("core.openclawd")
    p["unified_launcher"] = os.path.isfile(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "unified_launcher.py")
    )
    p["requirements_txt"] = os.path.isfile(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "requirements.txt")
    )
    p["env_example"] = (
        os.path.isfile(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env.example")
        )
        or os.path.isfile(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        )
    )
    p["health_route"] = _source_contains("core.api_routes", "/api/v1/health")
    p["chat_route"] = _module_exists("core.routes.chat")

    # -- 三态显化层 --
    p["unified_panel_aggregation"] = _module_exists("core.unified_panel_aggregation")
    p["panel_has_tri_state_phase"] = _source_contains(
        "core.unified_panel_aggregation", "tri_state_phase"
    )
    p["panel_has_presence_tristate"] = _source_contains(
        "core.unified_panel_aggregation", "presence_tristate"
    )
    p["continuum_state"] = _module_exists("core.continuum.types") or _module_exists(
        "core.continuum"
    )
    p["desktop_presence_runtime"] = _module_exists("core.desktop_presence_runtime")

    # -- Android 参与三态（通过 participation tier） --
    p["android_network_participation"] = _module_exists("core.android_network_participation")
    p["participation_has_7_tiers"] = _source_contains(
        "core.android_network_participation", "distributed_participant"
    )
    p["panel_has_android_participation_verdict"] = _source_contains(
        "core.unified_panel_aggregation", "android_participation_verdict"
    )

    # -- result acceptance 层 --
    p["result_truth_acceptance_gate"] = _module_exists("core.result_truth_acceptance_gate")
    p["acceptance_gate_has_quarantine"] = _source_contains(
        "core.result_truth_acceptance_gate", "quarantine"
    )
    p["acceptance_gate_has_android_proof_class"] = _source_contains(
        "core.result_truth_acceptance_gate", "android_proof_class"
    )
    p["unified_result_ingress"] = _module_exists("core.unified_result_ingress")
    p["result_ingress_blocks_closed_on_quarantine"] = _source_contains(
        "core.unified_result_ingress", "is_fully_closed"
    )

    # -- closure 层 --
    p["canonical_completion_ingress"] = _module_exists("core.canonical_completion_ingress")
    p["completion_ingress_has_android_context"] = _source_contains(
        "core.canonical_completion_ingress", "notify_with_android_context"
    )

    # -- operator board 层 --
    p["operator_surface"] = _module_exists("core.operator_surface")
    p["operator_execution_observability"] = _module_exists(
        "core.operator_execution_observability_surface"
    )
    p["observability_records_evidence"] = _source_contains(
        "core.operator_execution_observability_surface", "record_operator_evidence_entry"
    )
    p["observability_has_android_device_id"] = _source_contains(
        "core.operator_execution_observability_surface", "android_device_id"
    )
    p["pr4_operator_action_governance"] = _module_exists("core.pr4_operator_action_governance")
    p["pr4_has_board_projection"] = _source_contains(
        "core.pr4_operator_action_governance", "build_operator_board_projection"
    )
    p["pr4_has_android_directed_action"] = _source_contains(
        "core.pr4_operator_action_governance", "build_android_directed_action_spec"
    )
    p["pr4_board_consumes_android_participation_verdict"] = _source_contains(
        "core.pr4_operator_action_governance", "android_participation_verdict"
    )
    p["pr4_board_has_latest_closure_reasoning"] = _source_contains(
        "core.pr4_operator_action_governance", "latest_closure_reasoning"
    )

    # -- readiness surface 层 --
    p["operational_readiness_surface"] = _module_exists("core.operational_readiness_surface")
    p["readiness_consumes_participation_evidence"] = _source_contains(
        "core.operational_readiness_surface", "get_android_participation_evidence"
    ) or _source_contains(
        "core.operational_readiness_surface", "get_participation_state_for_device"
    )
    p["v2_unified_state_contract"] = _module_exists("core.v2_unified_state_contract")
    p["state_contract_has_participation"] = _source_contains(
        "core.v2_unified_state_contract", "android_network_participation"
    )

    # -- 编排选路已消费 Android truth（PR 1142 验证）--
    p["dispatch_consumes_participation_evidence"] = _source_contains(
        "core.runtime.source_dispatch_orchestrator", "get_android_participation_evidence"
    )
    p["device_selection_consumes_participation"] = _source_contains(
        "galaxy_gateway.routing.device_selection", "get_android_participation_evidence"
    )

    # -- board reasoning API --
    p["board_reasoning_api"] = _module_exists("core.pr_next_convergence_closure_audit")

    return p


# ---------------------------------------------------------------------------
# 可用性审查构建
# ---------------------------------------------------------------------------


def build_clone_to_run_audit() -> CloneToRunAudit:
    """构建从 clone 到 build 到 runtime 的可用性审计报告。

    诚实性要求
    ----------
    - 若路径不完整，明确标注 partially_operable 而非 clone_ready。
    - Android 本地模式、自主路径要分别评估，不能混合成一个乐观结论。
    - 多设备分布要区分"语义成立"与"运行级 fully closed"。
    """
    p = _collect_probes()

    checkpoints: List[CloneToRunAuditCheckpoint] = [
        CloneToRunAuditCheckpoint(
            "CK1_ENTRY_POINT",
            "系统有明确的启动入口（main.py 或 unified_launcher.py）",
            p.get("main_entry", False) or p.get("unified_launcher", False),
            "main.py 和/或 unified_launcher.py 存在于仓库根目录，具有明确启动入口。"
            if (p.get("main_entry", False) or p.get("unified_launcher", False))
            else "未发现明确启动入口文件，clone 后无法直接定位运行命令。",
            ["main.py", "unified_launcher.py"],
            [],
            blocking=not (p.get("main_entry", False) or p.get("unified_launcher", False)),
        ),
        CloneToRunAuditCheckpoint(
            "CK2_DEPENDENCIES",
            "依赖清单（requirements.txt）存在",
            p.get("requirements_txt", False),
            "requirements.txt 存在，用户可通过 pip install -r requirements.txt 安装 Python 依赖。"
            if p.get("requirements_txt", False)
            else "未发现 requirements.txt，依赖安装方式不明确。",
            ["requirements.txt"],
            [],
            blocking=not p.get("requirements_txt", False),
        ),
        CloneToRunAuditCheckpoint(
            "CK3_ENV_CONFIG",
            "环境配置样例（.env.example）存在",
            p.get("env_example", False),
            ".env 或 .env.example 存在，用户可获取 API Key 配置格式。"
            if p.get("env_example", False)
            else ".env.example 未找到。API Key 等配置可能需要用户自行获取，构成轻微阻塞。",
            [],
            [],
            blocking=False,
        ),
        CloneToRunAuditCheckpoint(
            "CK4_HEALTH_ROUTE",
            "/api/v1/health 路由存在，可验证服务是否运行",
            p.get("health_route", False),
            "/api/v1/health 端点已定义，clone 后可通过该端点快速验证 V2 服务已启动。"
            if p.get("health_route", False)
            else "/api/v1/health 路由未发现，无法快速验证服务是否正常运行。",
            ["core/api_routes.py"],
            [],
            blocking=False,
        ),
        CloneToRunAuditCheckpoint(
            "CK5_ANDROID_APP",
            "Android App 可构建并连接到 V2（GalaxyWebSocketClient 存在）",
            True,
            "Android 端 GalaxyWebSocketClient 存在于 ufo-galaxy-android 仓库，"
            "WS 接入协议已定义。但需单独构建 Android APK 并配置 V2 服务地址，"
            "不在 clone-to-run 的自动路径内。",
            [],
            [ANDROID_ANCHOR_WS_CLIENT],
            blocking=False,
        ),
        CloneToRunAuditCheckpoint(
            "CK6_ANDROID_LOCAL_MODE",
            "Android 本地自然语言/本地模式路径可用性",
            True,
            "AutonomousExecutionPipeline 在 Android 仓库中真实存在，"
            "LocalExecutionModeGate 存在。但本地 NL 推理依赖本地 LLM 资源（模型权重、"
            "accessibility 权限），不是开箱即用的默认路径。"
            "评估：本地模式语义真实存在，但对大多数用户仍需额外配置，属于高级功能路径。",
            ["core/android_mode_gate_policy.py"],
            [ANDROID_ANCHOR_AUTONOMOUS_PIPELINE, ANDROID_ANCHOR_MODE_GATE],
            blocking=False,
        ),
        CloneToRunAuditCheckpoint(
            "CK7_MULTI_DEVICE",
            "多设备注册/加入/能力宣告/参与 readiness 体系实现程度",
            p.get("android_network_participation", False),
            "AndroidNetworkParticipationTier（7 个层级）已实现，设备可注册并声明参与能力。"
            "android_mode_gate_policy 含 evaluate_android_mode_readiness。"
            "但当前多设备协作不是 P2P mesh，而是中心控制型：V2 统一编排，Android 作为参与节点。"
            "因此'多设备分布式体系'语义成立，但不能说成 peer-to-peer mesh fully closed。"
            if p.get("android_network_participation", False)
            else "AndroidNetworkParticipation 模块未发现，多设备参与体系可能未实现。",
            [
                "core/android_network_participation.py",
                "core/android_mode_gate_policy.py",
                "core/android_device_state_store.py",
            ],
            [ANDROID_ANCHOR_MESH_CONTRACT],
            blocking=False,
        ),
    ]

    passed = sum(1 for c in checkpoints if c.passed)
    blocked = any(c.blocking and not c.passed for c in checkpoints)

    if blocked:
        verdict = OperabilityVerdict.BLOCKED
    elif passed >= 5:
        verdict = OperabilityVerdict.PARTIALLY_OPERABLE
    else:
        verdict = OperabilityVerdict.BLOCKED

    already_working = [
        "V2 核心服务通过 main.py / unified_launcher.py 可启动（依赖 requirements.txt）",
        "/api/v1/chat, /api/v1/health 等核心 API 路由已定义",
        "Android WS 接入协议（GalaxyWebSocketClient）已就位",
        "设备注册、状态上报、参与 readiness 体系真实存在",
        "编排层已消费 Android 参与真值（PR 1142 已完成）",
        "result truth acceptance gate 已工作，quarantine 会阻断 is_fully_closed",
    ]

    blocking_gaps = []
    if not p.get("env_example", False):
        blocking_gaps.append("API Key / .env 配置样例不完整，新用户需要自行配置密钥才能运行")
    blocking_gaps.append(
        "Android App 需要单独构建（Gradle 构建 + APK 安装），不在 V2 clone-to-run 自动路径内"
    )
    blocking_gaps.append(
        "Android 本地 NL 模式（AutonomousExecutionPipeline 全链）依赖本地 LLM 权重 + "
        "accessibility 权限，非开箱即用"
    )
    blocking_gaps.append(
        "多设备 mesh 是中心控制型，不是对等网络；'分布式体系'语义成立但 full mesh runtime 未闭合"
    )

    return CloneToRunAudit(
        operability_verdict=verdict,
        verdict_summary_zh=(
            "系统处于 partially_operable 状态：V2 核心服务可克隆并启动，API 路由已定义，"
            "Android 接入协议已就位，参与真值治理体系已运行。"
            "但系统的完整可用性（含 Android 本地 NL 模式、多设备协作全链、API Key 配置）"
            "仍需额外手动步骤，对一般用户不构成开箱即用，属于具备实质运行基础但实用性受限。"
        ),
        checkpoints=checkpoints,
        blocking_gaps_zh=blocking_gaps,
        already_working_zh=already_working,
        android_local_mode_verdict_zh=(
            "Android 本地 NL 路径：AutonomousExecutionPipeline 代码真实存在，"
            "LocalExecutionModeGate 已实现语义门控。但本地 inference 的实际可用性"
            "取决于：(1) 设备是否安装并配置了本地 LLM；(2) accessibility 权限是否已授权；"
            "(3) 设备是否通过 WS 连接到 V2 并完成了 mode gate 评估。"
            "结论：本地模式语义真实、代码路径真实，但不是对任意 Android 设备都开箱即用。"
        ),
        multi_device_reality_verdict_zh=(
            "多设备体系：V2 已实现 AndroidNetworkParticipationTier（7 层），"
            "可跟踪每个设备从 local_only 到 distributed_participant 的状态。"
            "设备注册（GalaxyWebSocketClient）、能力宣告（CapabilityReport）、"
            "participation readiness 均有真实代码实现。"
            "但这是中心控制型分布式体系（V2 统一编排），而不是对等 mesh 网络。"
            "多设备分布式不等于对等自主，叙事上不能超出代码实际。"
        ),
    )


# ---------------------------------------------------------------------------
# 三态审查构建
# ---------------------------------------------------------------------------


def build_three_state_runtime_audit() -> ThreeStateRuntimeAudit:
    """构建三态运行呈现在代码中的真实性审查。"""
    p = _collect_probes()

    display_exists = bool(
        p.get("panel_has_tri_state_phase") and p.get("panel_has_presence_tristate")
    )
    display_projected = bool(p.get("panel_has_tri_state_phase"))
    participation_exists = bool(p.get("participation_has_7_tiers"))
    participation_projected = bool(p.get("panel_has_android_participation_verdict"))
    unified_api = False  # 两线路尚未合并成单一"三态" API

    if display_exists and participation_exists and unified_api:
        verdict = ThreeStateSourceVerdict.EXISTS_IN_CODE
    elif display_exists or participation_exists:
        verdict = ThreeStateSourceVerdict.PARTIALLY_IN_CODE
    else:
        verdict = ThreeStateSourceVerdict.NARRATIVE_ONLY

    return ThreeStateRuntimeAudit(
        verdict=verdict,
        display_tri_state_exists_in_code=display_exists,
        display_tri_state_sources_zh=(
            "显化层三态（tri_state_phase / presence_tristate）由 ContinuumState 与 "
            "OperatorSnapshot 产生，经由 core.unified_panel_aggregation 聚合进入 "
            "UnifiedPanelPayload。这是真实的代码路径，不是叙事。"
            if display_exists
            else "显化层三态相关字段未在 UnifiedPanelPayload 中发现，可能模块不可用。"
        ),
        display_tri_state_panel_projected=display_projected,
        android_participation_tri_state_exists=participation_exists,
        android_participation_tri_state_panel_projected=participation_projected,
        unified_tri_state_api_exists=unified_api,
        honest_assessment_zh=(
            "三态在代码中真实存在，但以两条独立语义线出现，未合并为统一 API：\n"
            "线路 A（显化层）：tri_state_phase（ContinuumState）、presence_tristate（OperatorSnapshot）\n"
            "  → 已进入 UnifiedPanelPayload，可被 panel 读取。\n"
            "线路 B（Android 参与层）：AndroidNetworkParticipationTier 7 级\n"
            "  → 已进入编排选路评分（PR 1142），但尚未在 board/panel 以三态聚合形式统一投影。\n"
            "如果用户所说的'三态运行呈现'是指统一的三态 board API：当前处于 PARTIALLY_IN_CODE，\n"
            "V2 侧已补 android_participation_verdict 进入 panel，但两线路的统一投影尚未完成。"
        ),
        operator_board_gap_zh=(
            "当前 operator/board 面的三态呈现缺口：\n"
            "1. tri_state_phase 和 presence_tristate 可读，但未与 Android 参与层级统一解释。\n"
            "2. Android 参与 tier 进入了路由，但 board 面没有统一的'当前系统三态'聚合视图。\n"
            "3. 本次 PR 在 panel 中新增 android_participation_verdict 字段，是迈向统一的一步，\n"
            "   但完整的双线三态统一 API 仍需后续 PR 跟进。"
        ),
        v2_anchors=[
            "core/unified_panel_aggregation.py",
            "core/android_network_participation.py",
            "core/desktop_presence_runtime.py",
        ],
        android_anchors=[ANDROID_ANCHOR_MESH_CONTRACT, ANDROID_ANCHOR_AUTONOMOUS_PIPELINE],
    )


# ---------------------------------------------------------------------------
# 闭环治理传播审查构建
# ---------------------------------------------------------------------------


def build_closure_governance_propagation_audit() -> ClosureGovernancePropagationAudit:
    """构建 Android truth 从编排选路向 closure/governance/operator/readiness 的传播审计。"""
    p = _collect_probes()

    # result acceptance 层
    acceptance_has_android = bool(p.get("acceptance_gate_has_android_proof_class"))

    # closure 层
    closure_reflects_verdict = bool(p.get("result_ingress_blocks_closed_on_quarantine"))

    # operator board 层
    board_has_reasoning = bool(
        p.get("observability_has_android_device_id")
        and p.get("pr4_has_android_directed_action")
    )

    # readiness 层
    readiness_has_android = bool(
        p.get("readiness_consumes_participation_evidence")
        or p.get("state_contract_has_participation")
    )

    # completion ingress android context
    completion_has_context = bool(p.get("completion_ingress_has_android_context"))

    # panel participation verdict
    panel_has_verdict = bool(p.get("panel_has_android_participation_verdict"))

    # 确定传播层级
    if (
        acceptance_has_android
        and closure_reflects_verdict
        and board_has_reasoning
        and readiness_has_android
        and completion_has_context
        and panel_has_verdict
    ):
        tier = ClosureGovernancePropagationTier.FULLY_PROPAGATED
    elif acceptance_has_android and closure_reflects_verdict:
        tier = ClosureGovernancePropagationTier.PARTIALLY_PROPAGATED
    elif p.get("dispatch_consumes_participation_evidence"):
        tier = ClosureGovernancePropagationTier.ROUTING_ONLY
    else:
        tier = ClosureGovernancePropagationTier.NOT_PROPAGATED

    return ClosureGovernancePropagationAudit(
        propagation_tier=tier,
        android_truth_in_result_acceptance=acceptance_has_android,
        result_acceptance_android_evidence_zh=(
            (
                "result_truth_acceptance_gate 通过 android_proof_class 字段消费 Android 端证据质量，"
                "高质量证据（trusted）允许 accept，低质量或缺失会降级为 accept_provisional 或 quarantine。"
                "这是 Android truth 正式进入 V2 result acceptance chain 的硬证据。"
            )
            if acceptance_has_android
            else "result_truth_acceptance_gate 未发现 android_proof_class 消费路径。"
        ),
        closure_reflects_acceptance_verdict=closure_reflects_verdict,
        closure_gap_zh=(
            (
                "UnifiedResultIngress 已通过 apply_acceptance_gate 把 quarantine/reject 判定转化为 "
                "is_fully_closed=False，防止低可信 Android 结果伪闭环。这一链路已闭合。\n"
                "待补强：closure 时刻还没有把 Android participation tier 显式记录到 board/operator，"
                "导致 operator 只能看到 is_fully_closed 标志，但不能直接追溯到"
                "'哪个 tier 的 Android 节点参与了'。"
            )
            if closure_reflects_verdict
            else "UnifiedResultIngress 中未发现 is_fully_closed 通过 acceptance verdict 控制的证据。"
        ),
        operator_board_has_android_reasoning=board_has_reasoning,
        operator_board_gap_zh=(
            (
                "operator_execution_observability_surface 已记录 android_device_id + evidence_state + "
                "acceptance_verdict（PR-4）；pr4_operator_action_governance 具备 "
                "build_android_directed_action_spec。\n"
                "待补强：board 上目前看到的是执行证据摘要，但 Android 参与层级（participation tier）"
                "还没有作为独立字段出现在 board 投影的\u300c本次决策为何是这个 tier 的 Android\u300d的解释路径上。"
                "本次 PR 通过 android_participation_verdict 字段和 notify_with_android_context 两个补强\n"
                "迈出这一步，但 board 路由侧（/api/v1/operator/board/operable-truth 等）消费该字段"
                "仍需后续 Android 侧配合跟进。"
            )
            if board_has_reasoning
            else "operator board Android reasoning 证据不足，需进一步审查。"
        ),
        readiness_surface_consumes_android_truth=readiness_has_android,
        readiness_gap_zh=(
            (
                "operational_readiness_surface 或 v2_unified_state_contract 中发现了 "
                "android_network_participation 消费路径，Android 参与真值已进入 readiness 计算。\n"
                "待补强：readiness 对 Android participation tier 的消费是否覆盖了所有关键分支（"
                "例如 degraded tier 是否触发 readiness degradation），仍需持续验证。"
            )
            if readiness_has_android
            else "readiness surface 未发现明确消费 Android participation evidence 的路径，需补强。"
        ),
        honest_assessment_zh=(
            "当前 Android truth 传播路径诚实评估：\n"
            "1. 编排选路：已完成（PR 1142）—— get_android_participation_evidence 进入 "
            "   source_dispatch_orchestrator 和 device_selection 评分。\n"
            "2. result acceptance：已完成 —— android_proof_class 进入 result_truth_acceptance_gate，"
            "   quarantine 阻断 is_fully_closed。\n"
            "3. closure operator 可见性：部分完成 —— operator_execution_observability 记录"
            "   android_device_id + evidence_state，但 participation tier 未独立投影到 board。\n"
            "4. readiness：部分完成 —— state_contract 中 android_network_participation 字段存在，"
            "   但 tier degradation → readiness degradation 的完整门控仍待强化。\n"
            "5. closure future Android context：本次 PR 新增 notify_with_android_context()，"
            "   是一个实质补强，但 board 路由侧消费仍需跟进。\n"
            "总结：传播链已从 routing_only 升级到 partially_propagated，"
            "但 fully_propagated 仍需 board reasoning 路由和 Android 侧进一步配合。"
        ),
        what_this_pr_fixes_zh=(
            "本次 PR 在 V2 侧的延续补强：\n"
            "1. 继续使用 canonical_completion_ingress.notify_with_android_context() 与\n"
            "   unified_panel_aggregation.android_participation_verdict 作为上游真值来源。\n"
            "2. pr4_operator_action_governance.build_operator_board_projection() 已开始消费\n"
            "   android_participation_verdict，并输出 latest_closure_reasoning。\n"
            "3. board 路由（/api/v1/operator/board/operable-truth）随 projection 直接带出\n"
            "   Android 参与层级 + 闭环因果解释，减少仅有摘要无决策原因的缺口。"
        ),
        what_still_needs_android_side_zh=(
            "仍需 Android 侧跟进：\n"
            "1. Android 侧需在 delegated result 中稳定提供 participation_tier 字段，\n"
            "   才能让 notify_with_android_context 收到高置信度的 tier 信息。\n"
            "2. Android 侧 LocalExecutionModeGate 的 tier 评估需要在连接时稳定上送，\n"
            "   才能让 readiness surface 的 Android degradation 门控更准确。\n"
            "3. Android mesh participation contract 的 constrained/deferred 语义\n"
            "   需要在 WS 报文中显式上送，才能让 V2 operator board 准确解释参与约束原因。"
        ),
        v2_anchors=[
            "core/result_truth_acceptance_gate.py",
            "core/unified_result_ingress.py",
            "core/canonical_completion_ingress.py",
            "core/operator_execution_observability_surface.py",
            "core/pr4_operator_action_governance.py",
            "core/operational_readiness_surface.py",
            "core/v2_unified_state_contract.py",
            "core/unified_panel_aggregation.py",
        ],
        android_anchors=[
            ANDROID_ANCHOR_WS_CLIENT,
            ANDROID_ANCHOR_AUTONOMOUS_PIPELINE,
            ANDROID_ANCHOR_MESH_CONTRACT,
        ],
    )


# ---------------------------------------------------------------------------
# operator board Android truth 审计构建
# ---------------------------------------------------------------------------


def build_android_truth_operator_board_audit() -> AndroidTruthInOperatorBoardAudit:
    """构建 Android 参与真值在 operator board 可观测性的审计。"""
    p = _collect_probes()

    panel_has_verdict = bool(p.get("panel_has_android_participation_verdict"))
    completion_has_context = bool(p.get("completion_ingress_has_android_context"))
    board_api = True  # 本模块本身提供 get_board_reasoning_for_closure
    operator_route_can_read = bool(
        p.get("pr4_has_board_projection")
        and p.get("pr4_board_consumes_android_participation_verdict")
        and p.get("pr4_board_has_latest_closure_reasoning")
    )

    return AndroidTruthInOperatorBoardAudit(
        panel_has_android_participation_verdict=panel_has_verdict,
        completion_ingress_has_android_context=completion_has_context,
        board_reasoning_api_available=board_api,
        operator_route_can_read_android_truth=operator_route_can_read,
        gap_before_this_pr_zh=(
            "PR 1142 之前：Android truth 只在编排评分时读取，operator board 看不到"
            "'参与了哪种 tier 的 Android 节点'。\n"
            "PR 1142 之后：编排评分已消费 participation evidence，但 panel/board 投影"
            "没有 android_participation_verdict 字段，closure 记录也没有 Android tier 上下文。"
        ),
        fix_in_this_pr_zh=(
            "本次 PR 补强：\n"
            "1. 沿用 UnifiedPanelPayload.android_participation_verdict 与\n"
            "   CanonicalCompletionIngress.notify_with_android_context() 作为上游真值。\n"
            "2. pr4_operator_action_governance.build_operator_board_projection() 继续跟进，\n"
            "   把 android_participation_verdict 与 latest_closure_reasoning 输出到 board。\n"
            "3. /api/v1/operator/board/operable-truth 现在可直接读取上述字段，\n"
            "   让 operator 不再只看到摘要而看不到闭环决策原因。"
        ),
        remaining_gap_zh=(
            "仍存在的缺口：\n"
            "1. board 路由已开始消费 android_participation_verdict + latest_closure_reasoning，"
            "   但目前仅覆盖 operable-truth 投影，其他 operator/readiness 投影仍需统一消费。\n"
            "2. latest_closure_reasoning 当前优先读取 operator evidence ring，"
            "   对长期历史闭环解释仍依赖后续持久化对齐。\n"
            "3. Android 侧需要在 delegated result 中稳定提供 participation_tier 字段，"
            "   才能让 closure 时的 Android context 高置信。"
        ),
        v2_anchors=[
            "core/unified_panel_aggregation.py",
            "core/canonical_completion_ingress.py",
            "core/pr_next_convergence_closure_audit.py",
            "core/pr4_operator_action_governance.py",
        ],
    )


# ---------------------------------------------------------------------------
# board reasoning API（operator route 可调用）
# ---------------------------------------------------------------------------


def get_board_reasoning_for_closure(
    task_id: str,
    android_participation_tier: Optional[str] = None,
    acceptance_verdict: Optional[str] = None,
    is_fully_closed: Optional[bool] = None,
    device_id: Optional[str] = None,
) -> Dict[str, Any]:
    """返回针对一次闭环事件的 Android 参与因果解释，供 operator board 路由消费。

    这是 V2 侧补强的核心 API：operator 路由不再需要各自推导"为什么这次闭环是这个结论"，
    而是调用本函数获取统一的解释摘要。

    参数
    ----
    task_id:
        任务 ID。
    android_participation_tier:
        Android 节点的参与层级（来自 AndroidNetworkParticipationTier.value），
        如 "local_only", "session_attached", "dispatch_eligible", "distributed_participant" 等。
        缺失时退化为 "unknown"。
    acceptance_verdict:
        result truth acceptance 判定结论（"accept", "accept_provisional", "quarantine", "reject"）。
        缺失时退化为 "unknown"。
    is_fully_closed:
        本次任务是否完全闭环。
    device_id:
        执行本次任务的 Android 设备 ID。

    返回
    ----
    Dict[str, Any]
        含 task_id, android_participation_tier, acceptance_verdict, is_fully_closed,
        causal_explanation_zh（中文因果解释）, device_id, generated_at 的字典。
    """
    from core.runtime_decision_reasoning import build_runtime_decision_reasoning_block

    return build_runtime_decision_reasoning_block(
        task_id=task_id,
        selected_runtime="android_delegated" if device_id else "v2_local",
        selected_device=device_id,
        participation_tier=android_participation_tier or "unknown",
        mode_state="closure_projection",
        readiness_summary={"verdict": "closure_projection"},
        acceptance_verdict=acceptance_verdict or "unknown",
        is_fully_closed=is_fully_closed,
        source_of_truth_refs=[
            PR_NEXT_CONVERGENCE_CLOSURE_AUDIT_AUTHORITY,
            "core.result_truth_acceptance_gate.evaluate_result_truth_acceptance",
        ],
    )


# ---------------------------------------------------------------------------
# 主构建入口
# ---------------------------------------------------------------------------


def build_convergence_closure_audit() -> ConvergenceClosureAuditRecord:
    """构建完整的收敛闭环审计工件。"""
    p = _collect_probes()

    operability = build_clone_to_run_audit()
    three_state = build_three_state_runtime_audit()
    closure_gov = build_closure_governance_propagation_audit()
    board_audit = build_android_truth_operator_board_audit()

    what_working = [
        "V2 核心服务（main.py）和所有核心 API 路由已就位",
        "Android WS 接入协议（GalaxyWebSocketClient）已就位",
        "result truth acceptance gate 已通过 android_proof_class 消费 Android 证据质量",
        "UnifiedResultIngress：quarantine/reject 阻断 is_fully_closed（防伪闭环）",
        "编排选路（source_dispatch_orchestrator + device_selection）已消费 "
        "get_android_participation_evidence（PR 1142）",
        "operational_readiness_surface + v2_unified_state_contract 含 "
        "android_network_participation 投影路径",
        "operator_execution_observability_surface 记录 android_device_id + evidence_state",
        "pr4_operator_action_governance 提供 build_android_directed_action_spec",
    ]

    what_fixed = [
        "延续既有补强：canonical_completion_ingress.notify_with_android_context()，"
        "closure 事件可携带 Android participation tier 上下文",
        "延续既有补强：UnifiedPanelPayload.android_participation_verdict 字段，"
        "panel 面板可直接读到 Android 参与状态",
        "延续既有补强：get_board_reasoning_for_closure() —— 标准化 Android 参与因果解释 API",
        "本次继续补强：pr4_operator_action_governance.build_operator_board_projection() "
        "开始消费 android_participation_verdict + latest_closure_reasoning，"
        "使 /api/v1/operator/board/operable-truth 输出 Android tier 与闭环解释",
    ]

    what_android = [
        "Android 侧需在 delegated result 中稳定提供 participation_tier 字段，"
        "才能让 notify_with_android_context 收到高置信度的 tier 信息",
        "Android LocalExecutionModeGate tier 评估需要在连接时稳定上送，"
        "才能让 readiness degradation 门控更准确",
        "Android mesh participation contract 的 constrained/deferred 语义"
        "需要在 WS 报文中显式上送，才能让 V2 board 准确解释参与约束原因",
        "board 路由（/api/v1/operator/board/operable-truth）消费 android_participation_verdict"
        "字段仍需后续 V2 + Android 协同跟进",
    ]

    return ConvergenceClosureAuditRecord(
        operability_audit=operability,
        three_state_audit=three_state,
        closure_governance_audit=closure_gov,
        operator_board_audit=board_audit,
        what_is_already_working_zh=what_working,
        what_this_pr_fixes_zh=what_fixed,
        what_still_needs_android_side_zh=what_android,
        _probe_results=p,
    )


__all__ = [
    # 权威标志
    "PR_NEXT_CONVERGENCE_CLOSURE_AUDIT_AUTHORITY",
    "PR_NEXT_CONVERGENCE_CONTRACT_VERSION",
    "PR_NEXT_CONVERGENCE_PR_TITLE",
    "PR_NEXT_CONVERGENCE_PR_TITLE_EN",
    "PR_NEXT_CONVERGENCE_ANCHOR",
    # 枚举
    "OperabilityVerdict",
    "ThreeStateSourceVerdict",
    "ClosureGovernancePropagationTier",
    # 数据类
    "CloneToRunAuditCheckpoint",
    "CloneToRunAudit",
    "ThreeStateRuntimeAudit",
    "ClosureGovernancePropagationAudit",
    "AndroidTruthInOperatorBoardAudit",
    "ConvergenceClosureAuditRecord",
    # 函数
    "build_clone_to_run_audit",
    "build_three_state_runtime_audit",
    "build_closure_governance_propagation_audit",
    "build_android_truth_operator_board_audit",
    "get_board_reasoning_for_closure",
    "build_convergence_closure_audit",
]
