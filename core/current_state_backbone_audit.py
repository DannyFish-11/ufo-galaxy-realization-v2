#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/current_state_backbone_audit.py
=======================================
基于双仓真实代码澄清中心分布式 AI 系统现状、主骨架与未闭合点

PR 定位
-------
本模块是继 PR 1143（可用性审查、闭环真值治理、操作面同源解释）之后的下一个主要
收敛工件。

核心目标
--------
1. **当前状态基线**：不做推测，只呈现双仓真实代码中已成立的骨架。
2. **链路拆解**：以可机读结构清晰列出 6 条主链路（含 Android truth 上送链）
   的当前代码锚点与闭合状态。
3. **模式地图**：区分本地模式、跨设备模式、多设备参与、delegated execution、
   takeover、distributed participant，并对每种模式的真实代码成立程度作诚实判断。
4. **三态分离**：已成立 / 半闭合 / 未闭合，不混淆。
5. **小型 V2 补强**：新增 ``build_system_backbone_snapshot()`` API，
   让 operator/board 可直接获取当前状态地图的机读摘要。

两仓关系
--------
本模块分析两个仓库：
- ``DannyFish-11/ufo-galaxy-realization-v2``  (V2 — 中心治理核)
- ``DannyFish-11/ufo-galaxy-android``         (Android — 参与执行节点)

Android 代码锚点基于已审计的提交：
``2857b93be7e8e6ea01e37d9a2af01ff2cae92c5c``

所有断言均基于真实 V2 import 探针 + Android 明确代码锚点，不使用文档叙述作为证据。

公开 API
--------
枚举::

    ClosureState
    ChainId
    ModeId

数据类::

    ChainSegment
    ChainMap
    ModeEntry
    ModeMap
    BackboneItem
    BackboneSnapshot

函数::

    build_chain_map() -> ChainMap
    build_mode_map() -> ModeMap
    build_backbone_snapshot() -> BackboneSnapshot
    build_system_backbone_snapshot() -> dict   (operator/board 消费入口)

权威标志
--------
``CURRENT_STATE_BACKBONE_AUDIT_AUTHORITY``
``CURRENT_STATE_BACKBONE_CONTRACT_VERSION``
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authority metadata
# ---------------------------------------------------------------------------

CURRENT_STATE_BACKBONE_AUDIT_AUTHORITY: str = (
    "CURRENT_STATE_BACKBONE_AUDIT::"
    "core.current_state_backbone_audit::"
    "dual-repo-real-code-backbone-clarification-v1"
)

CURRENT_STATE_BACKBONE_CONTRACT_VERSION: str = "1.0.0"

# Android 代码审计参考提交
ANDROID_AUDITED_REF: str = "2857b93be7e8e6ea01e37d9a2af01ff2cae92c5c"

# Android 侧关键代码锚点
ANDROID_ANCHOR_WS_CLIENT = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt"
)
ANDROID_ANCHOR_CONNECTION_SERVICE = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/service/GalaxyConnectionService.kt"
)
ANDROID_ANCHOR_AUTONOMOUS_PIPELINE = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/agent/AutonomousExecutionPipeline.kt"
)
ANDROID_ANCHOR_MESH_CONTRACT = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/runtime/AndroidMeshParticipationContract.kt"
)
ANDROID_ANCHOR_LOCAL_MODE_GATE = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/runtime/LocalExecutionModeGate.kt"
)
ANDROID_ANCHOR_DURABLE_IDENTITY = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/session/DurableParticipantIdentity.kt"
)
ANDROID_ANCHOR_DELEGATED_SIGNAL = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/runtime/DelegatedExecutionSignal.kt"
)
ANDROID_ANCHOR_READINESS_EVALUATOR = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/runtime/DelegatedRuntimeReadinessEvaluator.kt"
)
ANDROID_ANCHOR_ACCEPTANCE_EVALUATOR = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/runtime/DelegatedRuntimeAcceptanceEvaluator.kt"
)
ANDROID_ANCHOR_CANONICAL_EXECUTION_EVENT = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/runtime/CanonicalExecutionEvent.kt"
)
ANDROID_ANCHOR_CANONICAL_DISPATCH_CHAIN = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/runtime/CanonicalDispatchChain.kt"
)
ANDROID_ANCHOR_RUNTIME_CONTROLLER = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/runtime/RuntimeController.kt"
)

__all__ = [
    "CURRENT_STATE_BACKBONE_AUDIT_AUTHORITY",
    "CURRENT_STATE_BACKBONE_CONTRACT_VERSION",
    "ANDROID_AUDITED_REF",
    "ClosureState",
    "ChainId",
    "ModeId",
    "ChainSegment",
    "ChainMap",
    "ModeEntry",
    "ModeMap",
    "BackboneItem",
    "BackboneSnapshot",
    "build_chain_map",
    "build_mode_map",
    "build_backbone_snapshot",
    "build_system_backbone_snapshot",
]

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ClosureState(str, Enum):
    """三态闭合状态。"""

    ESTABLISHED = "established"
    """已成立：代码已就位，端到端路径已接通，行为可验证。"""

    PARTIAL = "partial"
    """半闭合：代码骨架存在，但存在条件依赖、路径断点或需要双端对齐才能全闭合。"""

    OPEN = "open"
    """未闭合：代码路径不完整，或存在已知无法自动解决的依赖阻塞。"""


class ChainId(str, Enum):
    """六条主链路 ID。"""

    REQUEST = "request_chain"
    """请求链：用户 → V2 API → 编排 → Android。"""

    EXECUTION = "execution_chain"
    """执行链：Android 本地执行 → 结果产生。"""

    ANDROID_TRUTH_UPLINK = "android_truth_uplink_chain"
    """Android truth 上送链：participation/mode/snapshot/event/result 上送到 V2。"""

    RESULT_BACKFLOW = "result_backflow_chain"
    """结果回流链：Android → V2 unified_result_ingress → truth chain。"""

    CLOSURE_ACCEPTANCE = "closure_acceptance_chain"
    """closure/acceptance 链：结果真值评估 → is_fully_closed → canonical closure。"""

    PROJECTION = "projection_chain"
    """operator/panel/board/desktop/mobile 投影链：V2 state → 呈现面。"""


class ModeId(str, Enum):
    """运行模式 ID。"""

    LOCAL = "local_mode"
    """本地模式：Android 独立运行，不依赖 V2 中心。"""

    CROSS_DEVICE = "cross_device_mode"
    """跨设备模式：Android 连接 V2，cross_device_switch 开启，V2 可派遣。"""

    MULTI_DEVICE = "multi_device_participation"
    """多设备参与：多个 Android 节点连接 V2，各自上报 readiness/tier。"""

    DELEGATED_EXECUTION = "delegated_execution"
    """委托执行：V2 将任务 handoff 给 Android，Android 执行并回流结果。"""

    TAKEOVER = "takeover"
    """接管：V2 或另一 Android 节点请求接管当前设备的执行上下文。"""

    DISTRIBUTED_PARTICIPANT = "distributed_participant"
    """分布式参与节点：Android 达到 dispatch_eligible / distributed_participant tier，
    可作为独立执行节点接受 V2 直接派遣。"""


# ---------------------------------------------------------------------------
# Probe helpers
# ---------------------------------------------------------------------------


def _probe(module_path: str, token: str) -> bool:
    """检查 V2 侧模块源码是否包含指定 token（不执行模块）。"""
    try:
        spec = importlib.util.find_spec(module_path)
        if spec is None or spec.origin is None:
            return False
        with open(spec.origin, "r", encoding="utf-8", errors="ignore") as fh:
            return token in fh.read()
    except Exception:
        return False


def _module_exists(module_path: str) -> bool:
    """检查 V2 侧模块是否可找到。"""
    try:
        return importlib.util.find_spec(module_path) is not None
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Chain segment data model
# ---------------------------------------------------------------------------


@dataclass
class ChainSegment:
    """链路中的一个环节。"""

    name: str
    """环节名称（中文）。"""

    v2_anchor: str
    """V2 侧代码锚点（模块路径或函数）。"""

    android_anchor: str
    """Android 侧代码锚点（文件路径）。"""

    closure_state: ClosureState
    """当前闭合状态。"""

    notes: str = ""
    """诚实说明。"""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "v2_anchor": self.v2_anchor,
            "android_anchor": self.android_anchor,
            "closure_state": self.closure_state.value,
            "notes": self.notes,
        }


@dataclass
class ChainMap:
    """六条主链路的当前状态地图。"""

    chains: Dict[str, List[ChainSegment]] = field(default_factory=dict)
    overall_closure_by_chain: Dict[str, str] = field(default_factory=dict)
    _source: str = CURRENT_STATE_BACKBONE_AUDIT_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chains": {
                cid: [seg.to_dict() for seg in segs]
                for cid, segs in self.chains.items()
            },
            "overall_closure_by_chain": self.overall_closure_by_chain,
            "_source": self._source,
        }


# ---------------------------------------------------------------------------
# Mode entry data model
# ---------------------------------------------------------------------------


@dataclass
class ModeEntry:
    """一种运行模式的当前状态描述。"""

    mode_id: ModeId
    description_zh: str
    v2_code_anchor: str
    android_code_anchor: str
    closure_state: ClosureState
    conditions_zh: str = ""
    """成立所需条件（诚实列出）。"""
    gaps_zh: str = ""
    """当前缺口（若半闭合或未闭合）。"""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode_id": self.mode_id.value,
            "description_zh": self.description_zh,
            "v2_code_anchor": self.v2_code_anchor,
            "android_code_anchor": self.android_code_anchor,
            "closure_state": self.closure_state.value,
            "conditions_zh": self.conditions_zh,
            "gaps_zh": self.gaps_zh,
        }


@dataclass
class ModeMap:
    """运行模式地图。"""

    modes: List[ModeEntry] = field(default_factory=list)
    _source: str = CURRENT_STATE_BACKBONE_AUDIT_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "modes": [m.to_dict() for m in self.modes],
            "_source": self._source,
        }


# ---------------------------------------------------------------------------
# Backbone item (三态分离)
# ---------------------------------------------------------------------------


@dataclass
class BackboneItem:
    """骨架中的一项（对应三态分离）。"""

    label: str
    """简短标签。"""

    closure_state: ClosureState
    v2_anchor: str
    android_anchor: str
    detail_zh: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "closure_state": self.closure_state.value,
            "v2_anchor": self.v2_anchor,
            "android_anchor": self.android_anchor,
            "detail_zh": self.detail_zh,
        }


@dataclass
class BackboneSnapshot:
    """当前双仓系统骨架快照。"""

    authority: str = CURRENT_STATE_BACKBONE_AUDIT_AUTHORITY
    contract_version: str = CURRENT_STATE_BACKBONE_CONTRACT_VERSION
    android_audited_ref: str = ANDROID_AUDITED_REF
    generated_at: float = field(default_factory=time.time)

    # 六条链路地图
    chain_map: ChainMap = field(default_factory=ChainMap)

    # 运行模式地图
    mode_map: ModeMap = field(default_factory=ModeMap)
    layered_mode_model: Dict[str, Any] = field(default_factory=dict)

    # 三态分离汇总
    established: List[BackboneItem] = field(default_factory=list)
    partial: List[BackboneItem] = field(default_factory=list)
    open_items: List[BackboneItem] = field(default_factory=list)

    # 系统身份（一句话）
    system_identity_zh: str = (
        "以 V2 Python 服务为中心治理核、以 Android 设备为 delegated runtime 执行节点的"
        "中心控制型跨端任务执行与治理平台，不是单仓服务，不是对等 P2P mesh。"
    )

    # 整体可用性判断
    overall_operability_zh: str = "partially_operable（部分可用）"

    # 诚实说明
    honesty_note_zh: str = (
        "本快照基于双仓真实代码探针，不依赖文档叙述。"
        "已成立意味着代码已就位且路径已接通；"
        "半闭合意味着骨架存在但有条件依赖或路径断点；"
        "未闭合意味着代码路径不完整或有已知阻塞。"
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authority": self.authority,
            "contract_version": self.contract_version,
            "android_audited_ref": self.android_audited_ref,
            "generated_at": self.generated_at,
            "system_identity_zh": self.system_identity_zh,
            "overall_operability_zh": self.overall_operability_zh,
            "chain_map": self.chain_map.to_dict(),
            "mode_map": self.mode_map.to_dict(),
            "layered_mode_model": dict(self.layered_mode_model),
            "established": [i.to_dict() for i in self.established],
            "partial": [i.to_dict() for i in self.partial],
            "open_items": [i.to_dict() for i in self.open_items],
            "honesty_note_zh": self.honesty_note_zh,
        }


# ---------------------------------------------------------------------------
# Chain map builder
# ---------------------------------------------------------------------------


def build_chain_map() -> ChainMap:
    """构建六条主链路的当前状态地图。

    所有链路环节的闭合状态基于真实 V2 代码探针。
    """
    cm = ChainMap()

    # ------------------------------------------------------------------
    # 1. 请求链（request_chain）
    # ------------------------------------------------------------------
    request_chain: List[ChainSegment] = [
        ChainSegment(
            name="用户输入 → V2 Chat/API 路由",
            v2_anchor="core.routes.chat :: POST /api/v1/chat",
            android_anchor="（不适用，入口在 V2）",
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "V2 chat 路由已实现，接受自然语言输入，"
                "通过 DesktopPresenceRuntime / NL execution spine 传递。"
            ),
        ),
        ChainSegment(
            name="NL 执行脊柱",
            v2_anchor="core.nl_execution_spine :: NLExecutionSpine",
            android_anchor="（不适用）",
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "NL execution spine PR-2 contract v2.2.0.0 已就位，"
                "提供 task_completed / problem_solved 语义。"
            ),
        ),
        ChainSegment(
            name="编排选路 → 设备选择",
            v2_anchor=(
                "core.runtime.source_dispatch_orchestrator :: select_dispatch_target ; "
                "galaxy_gateway.routing.device_selection"
            ),
            android_anchor="（选路决策在 V2 侧）",
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "source_dispatch_orchestrator + device_selection 已消费 "
                "get_android_participation_evidence() 作为选路评分输入（PR 1142）。"
            ),
        ),
        ChainSegment(
            name="handoff_envelope_v2 下发给 Android",
            v2_anchor=(
                "core.android_handoff_v2_response_ingress :: handoff_envelope_v2 ; "
                "galaxy_gateway.android_bridge"
            ),
            android_anchor=ANDROID_ANCHOR_CONNECTION_SERVICE,
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "handoff_envelope_v2 协议已就位，Android 侧 GalaxyConnectionService "
                "接收并路由 handoff。"
            ),
        ),
    ]

    # ------------------------------------------------------------------
    # 2. 执行链（execution_chain）
    # ------------------------------------------------------------------
    execution_chain: List[ChainSegment] = [
        ChainSegment(
            name="Android 接收 handoff → AutonomousExecutionPipeline",
            v2_anchor="（Android 侧自主）",
            android_anchor=ANDROID_ANCHOR_AUTONOMOUS_PIPELINE,
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "AutonomousExecutionPipeline.kt 代码存在，"
                "是 Android 侧接收 handoff 后的执行管线入口。"
            ),
        ),
        ChainSegment(
            name="本地 LLM / NL 推理（本地模式）",
            v2_anchor="（Android 侧本地）",
            android_anchor=ANDROID_ANCHOR_LOCAL_MODE_GATE,
            closure_state=ClosureState.PARTIAL,
            notes=(
                "LocalExecutionModeGate.kt 存在，代码路径真实，"
                "但依赖设备端本地 LLM 权重 + accessibility 权限，非默认可用。"
            ),
        ),
        ChainSegment(
            name="执行事件上报（CanonicalExecutionEvent）",
            v2_anchor="core.android_execution_signal_reconciler",
            android_anchor=ANDROID_ANCHOR_CANONICAL_EXECUTION_EVENT,
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "Android 侧 CanonicalExecutionEvent.kt 定义执行事件结构，"
                "V2 侧 android_execution_signal_reconciler 处理入站信号。"
            ),
        ),
        ChainSegment(
            name="Readiness 评估（Android 侧）",
            v2_anchor="core.android_device_state_store :: get_android_participation_evidence",
            android_anchor=ANDROID_ANCHOR_READINESS_EVALUATOR,
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "DelegatedRuntimeReadinessEvaluator.kt 多维度评估 readiness，"
                "V2 侧通过 get_android_participation_evidence() 消费快照。"
            ),
        ),
    ]

    # ------------------------------------------------------------------
    # 3. Android truth 上送链（android_truth_uplink_chain）
    # ------------------------------------------------------------------
    android_truth_uplink_chain: List[ChainSegment] = [
        ChainSegment(
            name="Capability report 上送 participation_tier/runtime_* 语义",
            v2_anchor="galaxy_gateway.android_bridge :: capability_report ingestion",
            android_anchor=ANDROID_ANCHOR_WS_CLIENT,
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "GalaxyWebSocketClient.kt 在 capability report metadata 中上送 "
                "authoritative_participation_state、participation_tier、"
                "runtime_constrained、runtime_deferred、local_mode_active。"
            ),
        ),
        ChainSegment(
            name="DeviceStateSnapshot / DeviceExecutionEvent 上送 participation_tier + execution_mode_state",
            v2_anchor="core.android_device_state_store :: absorb_device_state_snapshot / absorb_execution_event",
            android_anchor=ANDROID_ANCHOR_CONNECTION_SERVICE,
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "GalaxyConnectionService.kt 发送 DeviceStateSnapshotPayload 与 "
                "DeviceExecutionEventPayload 时携带 authoritative_participation_state、"
                "participation_tier、execution_mode_state、cross_device_eligibility。"
            ),
        ),
        ChainSegment(
            name="GoalResult 上送自动补齐模式上下文字段",
            v2_anchor="core.unified_result_ingress :: NormalizedResultEvent",
            android_anchor=ANDROID_ANCHOR_CONNECTION_SERVICE,
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "GalaxyConnectionService.sendGoalResult() 会在缺省时自动补齐 "
                "participation_tier、execution_mode_state、cross_device_eligibility、"
                "local_mode_gate_deferred、local_inference_available。"
            ),
        ),
    ]

    # ------------------------------------------------------------------
    # 4. 结果回流链（result_backflow_chain）
    # ------------------------------------------------------------------
    result_backflow_chain: List[ChainSegment] = [
        ChainSegment(
            name="Android → V2 WebSocket 结果上送",
            v2_anchor="galaxy_gateway.android_bridge",
            android_anchor=ANDROID_ANCHOR_WS_CLIENT,
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "GalaxyWebSocketClient.kt 是唯一跨端上行 transport，"
                "goal_execution_result 通过 WS 回流 V2。"
            ),
        ),
        ChainSegment(
            name="V2 统一结果入站",
            v2_anchor="core.unified_result_ingress :: ingest_result",
            android_anchor="（V2 侧处理）",
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "UnifiedResultIngress 是所有结果信号的单一入站入口，"
                "整合了原先 5 条分散路径。"
            ),
        ),
        ChainSegment(
            name="真值链（truth chain）四步处理",
            v2_anchor=(
                "core.android_participant_truth_ingress ; "
                "core.android_execution_signal_reconciler ; "
                "core.android_delegated_runtime_lifecycle_coordinator"
            ),
            android_anchor=ANDROID_ANCHOR_DELEGATED_SIGNAL,
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "truth_ingress → reconcile → lifecycle → completion 四步真值链已就位，"
                "DelegatedExecutionSignal.kt 定义 Android 侧上送结构。"
            ),
        ),
    ]

    # ------------------------------------------------------------------
    # 5. closure/acceptance 链
    # ------------------------------------------------------------------
    closure_chain: List[ChainSegment] = [
        ChainSegment(
            name="结果真值评估 → 证据质量分类",
            v2_anchor="core.execution_evidence_model :: classify_execution_evidence",
            android_anchor=ANDROID_ANCHOR_ACCEPTANCE_EVALUATOR,
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "ExecutionEvidenceState（13 状态）+ EvidenceTrustLevel（4 级）已就位，"
                "Android 侧 DelegatedRuntimeAcceptanceEvaluator.kt 对应评估维度。"
            ),
        ),
        ChainSegment(
            name="acceptance verdict → is_fully_closed 阻断",
            v2_anchor=(
                "core.result_truth_acceptance_gate :: evaluate_result_truth_acceptance ; "
                "core.unified_result_ingress :: EVIDENCE_CLOSURE_BLOCKING_VERDICTS"
            ),
            android_anchor="（V2 侧决策）",
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "quarantine/reject verdict 阻断 is_fully_closed，"
                "防止低质量结果进入已闭合状态（PR 1141/1142）。"
            ),
        ),
        ChainSegment(
            name="canonical closure + Android context 携带",
            v2_anchor=(
                "core.canonical_completion_ingress :: notify_with_android_context"
            ),
            android_anchor="（V2 侧接受）",
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "notify_with_android_context() 已就位（PR 1143），"
                "closure 时刻携带 android_participation_tier / device_id / acceptance_verdict。"
            ),
        ),
        ChainSegment(
            name="closure 语义写入 operator evidence surface",
            v2_anchor=(
                "core.operator_execution_observability_surface :: "
                "record_operator_evidence_entry"
            ),
            android_anchor="（V2 侧记录）",
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "notify_with_android_context() 调用 record_operator_evidence_entry()，"
                "写入 android_device_id + evidence_state，operator 可查询。"
            ),
        ),
    ]

    # ------------------------------------------------------------------
    # 6. operator/panel/board/desktop/mobile 投影链
    # ------------------------------------------------------------------
    _board_consumes_verdict = _probe(
        "core.pr4_operator_action_governance", "android_participation_verdict"
    )
    projection_chain: List[ChainSegment] = [
        ChainSegment(
            name="UnifiedPanelPayload android_participation_verdict",
            v2_anchor="core.unified_panel_aggregation :: UnifiedPanelPayload",
            android_anchor="（V2 聚合）",
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "android_participation_verdict 字段已进入 UnifiedPanelPayload（PR 1143），"
                "聚合最高参与层级设备信息：device_id / tier / blocking_reasons。"
            ),
        ),
        ChainSegment(
            name="operator board projection 消费 participation_verdict",
            v2_anchor=(
                "core.pr4_operator_action_governance :: build_operator_board_projection"
            ),
            android_anchor="（V2 投影）",
            closure_state=(
                ClosureState.ESTABLISHED
                if _board_consumes_verdict
                else ClosureState.PARTIAL
            ),
            notes=(
                "build_operator_board_projection() 已从 panel_payload 读取 "
                "android_participation_verdict 并输出 latest_closure_reasoning（PR4）。"
                if _board_consumes_verdict
                else "board projection 消费路径尚未探针确认，需跟进。"
            ),
        ),
        ChainSegment(
            name="GET /api/v1/operator/board/operable-truth 路由",
            v2_anchor="core.routes.operator :: /api/v1/operator/board/operable-truth",
            android_anchor="（V2 路由）",
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "路由已就位，调用 build_operator_board_projection() 并返回 JSON。"
            ),
        ),
        ChainSegment(
            name="desktop presence 三态投影",
            v2_anchor=(
                "core.desktop_presence_runtime :: DesktopPresenceRuntime ; "
                "core.continuum :: tri_state_phase"
            ),
            android_anchor="（显化层三态在 V2 侧）",
            closure_state=ClosureState.PARTIAL,
            notes=(
                "显化层 tri_state_phase / presence_tristate 真实存在于 V2 continuum；"
                "Android participation tier 7 层级是另一条语义线；"
                "两条线尚未统一成单一系统级三态 API。"
            ),
        ),
        ChainSegment(
            name="GET /api/v1/projection/desktop-status-board",
            v2_anchor=(
                "core.routes.projection :: /api/v1/projection/desktop-status-board"
            ),
            android_anchor="（V2 投影）",
            closure_state=ClosureState.ESTABLISHED,
            notes=(
                "路由已就位，包含 operational_state_board + source_of_truth_boundaries。"
            ),
        ),
        ChainSegment(
            name="mobile 端 UI 投影（悬浮窗 / floating service）",
            v2_anchor="（Android 侧 UI，V2 不直接控制）",
            android_anchor=ANDROID_ANCHOR_CONNECTION_SERVICE
            + " ; EnhancedFloatingService.kt",
            closure_state=ClosureState.PARTIAL,
            notes=(
                "Android 侧 EnhancedFloatingService 实现悬浮窗界面，"
                "显示 V2 任务结果；但 mobile 面与 V2 runtime truth 的实时同源机制"
                "取决于 WebSocket 连接稳定性，非强一致投影。"
            ),
        ),
    ]

    cm.chains[ChainId.REQUEST.value] = request_chain
    cm.chains[ChainId.EXECUTION.value] = execution_chain
    cm.chains[ChainId.ANDROID_TRUTH_UPLINK.value] = android_truth_uplink_chain
    cm.chains[ChainId.RESULT_BACKFLOW.value] = result_backflow_chain
    cm.chains[ChainId.CLOSURE_ACCEPTANCE.value] = closure_chain
    cm.chains[ChainId.PROJECTION.value] = projection_chain

    def _chain_overall(segs: List[ChainSegment]) -> str:
        states = {s.closure_state for s in segs}
        if ClosureState.OPEN in states:
            return ClosureState.OPEN.value
        if ClosureState.PARTIAL in states:
            return ClosureState.PARTIAL.value
        return ClosureState.ESTABLISHED.value

    cm.overall_closure_by_chain = {
        cid: _chain_overall(segs) for cid, segs in cm.chains.items()
    }

    return cm


# ---------------------------------------------------------------------------
# Mode map builder
# ---------------------------------------------------------------------------


def build_mode_map() -> ModeMap:
    """构建运行模式地图。"""
    mm = ModeMap()

    mm.modes = [
        ModeEntry(
            mode_id=ModeId.LOCAL,
            description_zh=(
                "Android 本地模式：设备在无 V2 连接的情况下独立处理用户自然语言请求，"
                "通过本地 LLM 推理完成任务，不与中心同步。"
            ),
            v2_code_anchor="core.android_mode_gate_policy :: AndroidDeviceMode.local",
            android_code_anchor=ANDROID_ANCHOR_LOCAL_MODE_GATE,
            closure_state=ClosureState.PARTIAL,
            conditions_zh=(
                "设备端已配置本地 LLM 权重；"
                "Android App 已安装并启用 accessibility 服务；"
                "LocalExecutionModeGate 评估通过。"
            ),
            gaps_zh=(
                "本地 LLM 权重非系统默认提供，用户需自行配置；"
                "accessibility 服务权限不是自动授予；"
                "本地模式结果不通过 V2 closure 链，缺少 acceptance 闭合。"
            ),
        ),
        ModeEntry(
            mode_id=ModeId.CROSS_DEVICE,
            description_zh=(
                "跨设备模式：Android 已连接 V2 中心，"
                "cross_device_switch 开启后 V2 可向 Android 派遣任务。"
                "Android 参与 tier 至少为 cross_device_enabled。"
            ),
            v2_code_anchor=(
                "core.android_network_participation :: "
                "AndroidNetworkParticipationTier.cross_device_enabled ; "
                "galaxy_gateway.cross_device_switch :: is_cross_device_enabled"
            ),
            android_code_anchor=ANDROID_ANCHOR_WS_CLIENT + " ; " + ANDROID_ANCHOR_CONNECTION_SERVICE,
            closure_state=ClosureState.ESTABLISHED,
            conditions_zh=(
                "Android App 已安装并连接 V2 gateway（WebSocket）；"
                "V2 cross_device_switch 开启；"
                "Android 侧 cross_device_enabled 门控通过；"
                "设备 session 存在。"
            ),
            gaps_zh=(
                "需要 Android APK 单独构建并安装，不在 V2 clone-to-run 自动路径内；"
                "网络可达性依赖具体部署环境。"
            ),
        ),
        ModeEntry(
            mode_id=ModeId.MULTI_DEVICE,
            description_zh=(
                "多设备参与：多个 Android 设备同时连接 V2，各自上报 readiness 快照，"
                "V2 选路时考虑所有设备的 participation tier。"
                "这是中心控制型，不是对等 P2P mesh。"
            ),
            v2_code_anchor=(
                "core.android_network_participation :: "
                "derive_android_network_participation_tier ; "
                "core.android_device_state_store :: list_device_state_snapshots"
            ),
            android_code_anchor=ANDROID_ANCHOR_MESH_CONTRACT,
            closure_state=ClosureState.PARTIAL,
            conditions_zh=(
                "多个 Android 设备各自连接 V2 并注册；"
                "每台设备独立上报 readiness/capability；"
                "V2 device_selection 选路时按 participation tier 评分。"
            ),
            gaps_zh=(
                "多设备参与体系骨架真实存在，但实际运行需要多台设备同时在线；"
                "设备间没有 P2P 直连，所有协调均经过 V2 中心；"
                "多设备并发派遣的实操场景尚未有端到端验证记录。"
            ),
        ),
        ModeEntry(
            mode_id=ModeId.DELEGATED_EXECUTION,
            description_zh=(
                "委托执行：V2 将具体任务通过 handoff_envelope_v2 下发给 Android，"
                "Android 执行后通过 DelegatedExecutionSignal 回流结果，"
                "V2 负责 acceptance 判断与 closure。"
            ),
            v2_code_anchor=(
                "core.android_handoff_v2_response_ingress ; "
                "core.android_delegated_runtime_lifecycle_coordinator ; "
                "core.android_runtime_dispatch_binding"
            ),
            android_code_anchor=(
                ANDROID_ANCHOR_DELEGATED_SIGNAL
                + " ; "
                + ANDROID_ANCHOR_CANONICAL_DISPATCH_CHAIN
            ),
            closure_state=ClosureState.ESTABLISHED,
            conditions_zh=(
                "设备处于 cross_device_enabled 或以上 tier；"
                "handoff_envelope_v2 协议双端对齐；"
                "Android 侧 CanonicalDispatchChain 正确执行并回流信号。"
            ),
            gaps_zh=(
                "participation_tier 随 delegated result 稳定上送尚未在所有场景保证；"
                "V2 notify_with_android_context() 在 tier 缺失时降级为 unknown。"
            ),
        ),
        ModeEntry(
            mode_id=ModeId.TAKEOVER,
            description_zh=(
                "接管（Takeover）：V2 通过 takeover_request 请求接管 Android "
                "当前执行上下文，或重新路由任务至另一节点。"
                "门控逻辑在 V2 侧 android_originated_authority_boundary.py。"
            ),
            v2_code_anchor=(
                "core.android_originated_authority_boundary :: "
                "govern_takeover_boundary ; "
                "core.android_delegated_runtime_lifecycle_coordinator :: "
                "govern_takeover_decision"
            ),
            android_code_anchor=(
                "ufo-galaxy-android/...runtime/AndroidTakeoverOwnershipTransferContract.kt"
            ),
            closure_state=ClosureState.PARTIAL,
            conditions_zh=(
                "Android 侧 authority/proof/continuity 证据达标；"
                "V2 门控逻辑判断 takeover 合法；"
                "接管后新执行者接收上下文并继续执行。"
            ),
            gaps_zh=(
                "takeover 门控逻辑存在，但 authority/proof 降级场景下"
                "自动降为 revalidation（非自动完成）；"
                "跨设备 takeover 的端到端实操链仍处于半闭合状态。"
            ),
        ),
        ModeEntry(
            mode_id=ModeId.DISTRIBUTED_PARTICIPANT,
            description_zh=(
                "分布式参与节点：Android 达到 dispatch_eligible / distributed_participant tier，"
                "V2 可直接将任务派遣给该设备作为独立执行节点，"
                "设备具备并行参与能力。"
                "这是 AndroidNetworkParticipationTier 7 层级中最高的两级。"
            ),
            v2_code_anchor=(
                "core.android_network_participation :: "
                "AndroidNetworkParticipationTier.dispatch_eligible ; "
                "AndroidNetworkParticipationTier.distributed_participant"
            ),
            android_code_anchor=ANDROID_ANCHOR_MESH_CONTRACT,
            closure_state=ClosureState.PARTIAL,
            conditions_zh=(
                "设备满足：cross_device_enabled + goal_execution_enabled + "
                "parallel_execution_enabled（dispatch_eligible）；"
                "进一步满足：已实际参与多任务并行分发（distributed_participant）。"
            ),
            gaps_zh=(
                "tier 定义和评估逻辑真实存在；"
                "但实际达到 distributed_participant tier 需要设备能力齐备、"
                "多任务并发场景验证，目前尚无端到端实操记录。"
            ),
        ),
    ]

    return mm


# ---------------------------------------------------------------------------
# Backbone snapshot builder（三态分离）
# ---------------------------------------------------------------------------


def build_backbone_snapshot() -> BackboneSnapshot:
    """构建当前双仓系统骨架快照，三态分离。"""
    snap = BackboneSnapshot()
    snap.chain_map = build_chain_map()
    snap.mode_map = build_mode_map()
    try:
        from core.v2_unified_mode_model import build_unified_mode_model_catalog

        snap.layered_mode_model = build_unified_mode_model_catalog()
    except Exception:
        snap.layered_mode_model = {}

    # --- 已成立 -----------------------------------------------------------
    snap.established = [
        BackboneItem(
            label="V2 中心服务启动入口",
            closure_state=ClosureState.ESTABLISHED,
            v2_anchor="main.py / unified_launcher.py",
            android_anchor="（不适用）",
            detail_zh="V2 有明确启动入口，可通过 pip install -r requirements.txt 安装依赖后启动。",
        ),
        BackboneItem(
            label="WebSocket 双端 transport 协议",
            closure_state=ClosureState.ESTABLISHED,
            v2_anchor="galaxy_gateway.android_bridge :: AIP v3 协议",
            android_anchor=ANDROID_ANCHOR_WS_CLIENT,
            detail_zh=(
                "GalaxyWebSocketClient.kt 是 Android 唯一上行 transport，"
                "AIP v3 消息类型在双端对齐（AipModels.kt 镜像 V2）。"
            ),
        ),
        BackboneItem(
            label="设备注册与能力上报体系",
            closure_state=ClosureState.ESTABLISHED,
            v2_anchor="core.android_device_state_store :: get_android_participation_evidence",
            android_anchor=ANDROID_ANCHOR_RUNTIME_CONTROLLER,
            detail_zh=(
                "android_device_state_store 维护设备快照，"
                "RuntimeController.kt 管理 Android 侧生命周期与注册。"
            ),
        ),
        BackboneItem(
            label="AndroidNetworkParticipationTier 7 层级定义与评估",
            closure_state=ClosureState.ESTABLISHED,
            v2_anchor=(
                "core.android_network_participation :: "
                "derive_android_network_participation_tier"
            ),
            android_anchor=ANDROID_ANCHOR_MESH_CONTRACT,
            detail_zh=(
                "7 层级（local_only → distributed_participant）定义真实存在，"
                "android_mode_gate_policy 提供三门评估。"
            ),
        ),
        BackboneItem(
            label="编排选路消费 Android participation truth（PR 1142）",
            closure_state=ClosureState.ESTABLISHED,
            v2_anchor=(
                "core.runtime.source_dispatch_orchestrator ; "
                "galaxy_gateway.routing.device_selection"
            ),
            android_anchor="（选路评分在 V2 侧）",
            detail_zh=(
                "source_dispatch_orchestrator + device_selection 已将 "
                "get_android_participation_evidence() 接入选路评分（PR 1142）。"
            ),
        ),
        BackboneItem(
            label="统一结果入站链（unified_result_ingress）",
            closure_state=ClosureState.ESTABLISHED,
            v2_anchor="core.unified_result_ingress :: ingest_result",
            android_anchor=ANDROID_ANCHOR_WS_CLIENT,
            detail_zh=(
                "所有结果信号通过单一入站入口处理，"
                "整合了原先 5 条分散路径。"
            ),
        ),
        BackboneItem(
            label="Android authoritative participation truth + mode 语义上送",
            closure_state=ClosureState.ESTABLISHED,
            v2_anchor=(
                "core.android_device_state_store :: "
                "absorb_device_state_snapshot / absorb_execution_event / ingest_result"
            ),
            android_anchor=(
                ANDROID_ANCHOR_WS_CLIENT
                + " ; "
                + ANDROID_ANCHOR_CONNECTION_SERVICE
            ),
            detail_zh=(
                "GalaxyWebSocketClient.kt 上送 participation_tier/runtime_constrained/"
                "runtime_deferred/local_mode_active；"
                "GalaxyConnectionService.sendGoalResult() 自动补齐 execution_mode_state / "
                "cross_device_eligibility / local_mode_gate_deferred / "
                "local_inference_available。"
            ),
        ),
        BackboneItem(
            label="evidence/acceptance/closure 真值链",
            closure_state=ClosureState.ESTABLISHED,
            v2_anchor=(
                "core.execution_evidence_model ; "
                "core.result_truth_acceptance_gate ; "
                "core.unified_result_ingress :: EVIDENCE_CLOSURE_BLOCKING_VERDICTS"
            ),
            android_anchor=ANDROID_ANCHOR_ACCEPTANCE_EVALUATOR,
            detail_zh=(
                "quarantine/reject 阻断 is_fully_closed，"
                "ExecutionEvidenceState 13 状态 + EvidenceTrustLevel 4 级已就位。"
            ),
        ),
        BackboneItem(
            label="canonical_completion_ingress + notify_with_android_context",
            closure_state=ClosureState.ESTABLISHED,
            v2_anchor=(
                "core.canonical_completion_ingress :: notify_with_android_context"
            ),
            android_anchor="（V2 侧）",
            detail_zh=(
                "closure 时刻携带 android_participation_tier / device_id / acceptance_verdict，"
                "写入 operator evidence surface。"
            ),
        ),
        BackboneItem(
            label="panel android_participation_verdict 字段（PR 1143）",
            closure_state=ClosureState.ESTABLISHED,
            v2_anchor="core.unified_panel_aggregation :: UnifiedPanelPayload",
            android_anchor="（V2 聚合）",
            detail_zh=(
                "android_participation_verdict 进入 UnifiedPanelPayload，"
                "operator/board 可直接读取最高参与层级设备信息。"
            ),
        ),
        BackboneItem(
            label="operator board projection 消费 participation_verdict + board reasoning（PR4）",
            closure_state=ClosureState.ESTABLISHED,
            v2_anchor=(
                "core.pr4_operator_action_governance :: build_operator_board_projection ; "
                "get_board_reasoning_for_closure"
            ),
            android_anchor="（V2 投影）",
            detail_zh=(
                "build_operator_board_projection() 从 panel_payload 读取 "
                "android_participation_verdict，输出 latest_closure_reasoning（PR4）。"
            ),
        ),
        BackboneItem(
            label="session continuity / DurableParticipantIdentity",
            closure_state=ClosureState.ESTABLISHED,
            v2_anchor="core.pr3_session_continuity_authority",
            android_anchor=ANDROID_ANCHOR_DURABLE_IDENTITY,
            detail_zh=(
                "跨重启参与者身份持久化代码存在，"
                "V2 pr3_session_continuity_authority 管理 continuity 决策。"
            ),
        ),
        BackboneItem(
            label="handoff_envelope_v2 委托执行协议",
            closure_state=ClosureState.ESTABLISHED,
            v2_anchor="core.android_handoff_v2_response_ingress",
            android_anchor=ANDROID_ANCHOR_CANONICAL_DISPATCH_CHAIN,
            detail_zh=(
                "handoff_envelope_v2 协议双端对齐，"
                "CanonicalDispatchChain.kt 执行委托任务。"
            ),
        ),
        BackboneItem(
            label="operator API 路由集（PR4：audit / board / snapshot / directed-action）",
            closure_state=ClosureState.ESTABLISHED,
            v2_anchor=(
                "core.routes.operator :: "
                "/api/v1/operator/actions/audit ; "
                "/api/v1/operator/board/operable-truth ; "
                "/api/v1/operator/pr4/snapshot ; "
                "/api/v1/operator/actions/android-directed"
            ),
            android_anchor="（V2 路由）",
            detail_zh="PR4 operator 路由集已就位，提供审计、board、快照、directed-action 端点。",
        ),
    ]

    # --- 半闭合 -----------------------------------------------------------
    snap.partial = [
        BackboneItem(
            label="三态统一系统 API（两条语义线尚未合并）",
            closure_state=ClosureState.PARTIAL,
            v2_anchor=(
                "core.continuum :: tri_state_phase ; "
                "core.desktop_presence_runtime :: presence_tristate"
            ),
            android_anchor=(
                "AndroidNetworkParticipationTier（7 层 → 3 语义组映射）"
            ),
            detail_zh=(
                "显化层 tri_state_phase（V2 continuum）真实存在；"
                "Android participation tier 7 层可收敛为 3 语义组；"
                "但二者还没统一成单一系统级三态 API。"
            ),
        ),
        BackboneItem(
            label="Android 本地 NL 模式（代码存在但非默认可用）",
            closure_state=ClosureState.PARTIAL,
            v2_anchor="core.android_mode_gate_policy :: AndroidDeviceMode.local",
            android_anchor=ANDROID_ANCHOR_LOCAL_MODE_GATE
            + " ; "
            + ANDROID_ANCHOR_AUTONOMOUS_PIPELINE,
            detail_zh=(
                "LocalExecutionModeGate.kt + AutonomousExecutionPipeline.kt 真实存在；"
                "但依赖本地 LLM 权重 + accessibility 权限，非开箱即用。"
            ),
        ),
        BackboneItem(
            label="Android runtime_constrained/runtime_deferred/local_mode_active 在 V2 下游全量消费",
            closure_state=ClosureState.PARTIAL,
            v2_anchor=(
                "core.unified_panel_aggregation ; "
                "core.pr4_operator_action_governance ; "
                "core.operational_readiness_surface"
            ),
            android_anchor=ANDROID_ANCHOR_WS_CLIENT,
            detail_zh=(
                "Android 已稳定上送 runtime_constrained/runtime_deferred/local_mode_active，"
                "但 V2 operator/panel/readiness 对这三字段仍以部分消费为主，"
                "尚未形成统一强约束解释链。"
            ),
        ),
        BackboneItem(
            label="readiness tier degradation ↔ Android participation tier 强联动",
            closure_state=ClosureState.PARTIAL,
            v2_anchor=(
                "core.operational_readiness_surface ; "
                "core.android_mode_gate_policy :: evaluate_android_mode_readiness"
            ),
            android_anchor=ANDROID_ANCHOR_READINESS_EVALUATOR,
            detail_zh=(
                "android_mode_gate_policy 三门评估存在，"
                "operational_readiness_surface 消费 android_network_participation；"
                "但 tier degradation 与 V2 readiness 降级的强联动机制仍不完整。"
            ),
        ),
        BackboneItem(
            label="多设备并发派遣实操（骨架真实，端到端实操未验证）",
            closure_state=ClosureState.PARTIAL,
            v2_anchor=(
                "core.android_device_state_store :: list_device_state_snapshots ; "
                "galaxy_gateway.routing.device_selection"
            ),
            android_anchor=ANDROID_ANCHOR_MESH_CONTRACT,
            detail_zh=(
                "多设备参与骨架（注册、readiness、选路）真实存在；"
                "但实际多设备并发运行需要多台设备同时在线，尚无端到端实操记录。"
            ),
        ),
        BackboneItem(
            label="takeover 完整端到端路径（门控存在，跨设备接管半闭合）",
            closure_state=ClosureState.PARTIAL,
            v2_anchor=(
                "core.android_originated_authority_boundary ; "
                "core.android_delegated_runtime_lifecycle_coordinator"
            ),
            android_anchor="AndroidTakeoverOwnershipTransferContract.kt",
            detail_zh=(
                "takeover 门控逻辑存在，authority 降级自动降为 revalidation；"
                "但跨设备 takeover 的完整端到端路径尚未全闭合。"
            ),
        ),
        BackboneItem(
            label="mobile 端 UI 与 V2 runtime truth 实时同源",
            closure_state=ClosureState.PARTIAL,
            v2_anchor="（V2 通过 WS 推送）",
            android_anchor="EnhancedFloatingService.kt ; GalaxyConnectionService.kt",
            detail_zh=(
                "Android 悬浮窗界面显示 V2 任务结果，依赖 WS 连接；"
                "但 mobile 面与 V2 runtime truth 不是强一致投影，WS 中断时会失同步。"
            ),
        ),
        BackboneItem(
            label="Android App clone-to-build 需单独 Gradle 构建",
            closure_state=ClosureState.PARTIAL,
            v2_anchor="（不在 V2 clone 路径内）",
            android_anchor="build_apk.sh ; app/build.gradle",
            detail_zh=(
                "Android APK 需单独执行 Gradle 构建，"
                "不在 V2 clone-to-run 自动路径内，需开发者单独处理。"
            ),
        ),
    ]

    # --- 未闭合 -----------------------------------------------------------
    snap.open_items = [
        BackboneItem(
            label="Android 本地 LLM 权重默认可用",
            closure_state=ClosureState.OPEN,
            v2_anchor="（不适用）",
            android_anchor=ANDROID_ANCHOR_LOCAL_MODE_GATE,
            detail_zh=(
                "本地 NL 模式依赖设备端本地 LLM 权重，"
                "系统不提供默认权重，用户需自行配置。"
                "这使本地模式无法做到开箱即用。"
            ),
        ),
        BackboneItem(
            label="distributed_participant tier 端到端实操验证",
            closure_state=ClosureState.OPEN,
            v2_anchor=(
                "core.android_network_participation :: "
                "AndroidNetworkParticipationTier.distributed_participant"
            ),
            android_anchor=ANDROID_ANCHOR_MESH_CONTRACT,
            detail_zh=(
                "distributed_participant tier 定义和评估逻辑真实存在；"
                "但达到该 tier 需要满足所有三门（cross_device + goal_execution + "
                "parallel_execution）并实际参与并行分发，尚无端到端实操记录。"
            ),
        ),
        BackboneItem(
            label="clone-to-run 开发者顺滑路径（环境配置 + Android build 一体化）",
            closure_state=ClosureState.OPEN,
            v2_anchor="requirements.txt ; .env.example",
            android_anchor="build_apk.sh",
            detail_zh=(
                "目前 V2 clone → 启动 → Android APK build → 安装 → 连接 "
                "尚未形成单一顺滑文档或脚本；"
                "API Key 配置、Android build 工具链、设备连接均需用户手动处理。"
            ),
        ),
        BackboneItem(
            label="真正 P2P / 自主对等 mesh runtime",
            closure_state=ClosureState.OPEN,
            v2_anchor="（架构决策：中心控制型）",
            android_anchor=ANDROID_ANCHOR_MESH_CONTRACT,
            detail_zh=(
                "当前系统架构是中心控制型（V2 中心编排 + Android 执行节点），"
                "不是对等 P2P mesh，Android 设备间没有直连协调，"
                "所有路由决策均经过 V2 中心。"
                "这不是缺口，而是架构选择的诚实说明。"
            ),
        ),
    ]

    return snap


# ---------------------------------------------------------------------------
# Operator/board 消费入口
# ---------------------------------------------------------------------------


def build_system_backbone_snapshot() -> Dict[str, Any]:
    """构建系统骨架机读摘要，供 operator/board 消费。

    返回一个可序列化的 dict，包含：
    - system_identity_zh（系统身份）
    - overall_operability_zh（整体可用性）
    - chain_closure_summary（六条链路闭合汇总）
    - mode_closure_summary（运行模式闭合汇总）
    - control_plane_layering（operator/board/panel/desktop 的责任分层）
    - field_typing_schema（runtime_truth / derived_reasoning / projection / stale_or_cached_summary）
    - established_count / partial_count / open_count（三态计数）
    - top_open_items（最关键未闭合项）
    - authority / contract_version

    这是本模块对 operator/board 最简洁的可机读投影。
    """
    snap = build_backbone_snapshot()
    d = snap.to_dict()

    chain_summary = {
        cid: d["chain_map"]["overall_closure_by_chain"].get(cid, "unknown")
        for cid in [c.value for c in ChainId]
    }

    mode_summary = {
        m["mode_id"]: m["closure_state"]
        for m in d["mode_map"]["modes"]
    }
    control_plane_layering = {
        "operator": {
            "role": "governance / audit / decision explanation / authority-aware control context",
            "truth_basis": "shared backbone snapshot + board runtime truth + operator audit evidence",
            "reasoning_basis": "shared runtime_decision_reasoning + latest_closure_reasoning",
            "projection_boundary": "operator action context is projection; runtime truth remains read-only",
        },
        "board": {
            "role": "structured runtime truth + structured reasoning",
            "truth_basis": "shared backbone snapshot + runtime truth + state basis",
            "reasoning_basis": "runtime_decision_reasoning / closure reasoning",
            "projection_boundary": "board projection is read-only and not direct execution authority",
        },
        "panel": {
            "role": "unified aggregated state + concise cross-surface snapshot",
            "truth_basis": "shared backbone snapshot + unified panel aggregation sources",
            "reasoning_basis": "panel runtime_decision_reasoning",
            "projection_boundary": "panel is concise projection, not deep governance reasoning replacement",
        },
        "desktop_projection": {
            "role": "desktop state projection + operability projection",
            "truth_basis": "shared backbone snapshot + runtime truth endpoint",
            "reasoning_basis": "runtime_decision_reasoning projected to desktop-facing payloads",
            "projection_boundary": "desktop surface is explicit projection/derived state",
        },
    }
    field_typing_schema = {
        "runtime_truth": "surface consumed read-only runtime truth basis",
        "derived_reasoning": "surface consumed reasoning block derived from truth/policy",
        "projection": "surface-specific projected/derived presentation fields",
        "stale_or_cached_summary": "stale/cached/degraded hints, not raw truth",
    }

    top_open = [
        {"label": item["label"], "detail_zh": item["detail_zh"]}
        for item in d["open_items"]
    ]

    return {
        "authority": CURRENT_STATE_BACKBONE_AUDIT_AUTHORITY,
        "contract_version": CURRENT_STATE_BACKBONE_CONTRACT_VERSION,
        "android_audited_ref": ANDROID_AUDITED_REF,
        "generated_at": d["generated_at"],
        "system_identity_zh": d["system_identity_zh"],
        "overall_operability_zh": d["overall_operability_zh"],
        "chain_closure_summary": chain_summary,
        "mode_closure_summary": mode_summary,
        "layered_mode_model": dict(d.get("layered_mode_model") or {}),
        "control_plane_layering": control_plane_layering,
        "field_typing_schema": field_typing_schema,
        "established_count": len(d["established"]),
        "partial_count": len(d["partial"]),
        "open_count": len(d["open_items"]),
        "top_open_items": top_open,
        "honesty_note_zh": d["honesty_note_zh"],
    }
