"""core/v2_android_truth_ssot.py
=================================
V2 侧 Android Truth 单一可信来源（SSOT）块。

背景
----
在本模块引入之前，V2 侧对 Android 设备的 truth 散落在至少五个不同模块中：

- ``core.android_device_state_store`` — 设备快照（model_ready、local_loop_ready 等）
- ``core.android_network_participation`` — 参与等级（tier）和阻断原因
- ``core.android_mode_gate_policy`` — 模式门控（cross_device/local）和执行门
- ``core.unified_panel_aggregation`` — android_participation_verdict（面板聚合）
- ``core.v2_unified_state_contract`` — participation_evidence（状态合约）

各层分别独立摄取 Android truth，导致：

1. 字段别名不统一（同一字段在不同路径用不同键名表达）
2. 不同路由（readiness / closure / panel / board / operator）消费形状不同
3. 无清晰的 V2 侧 SSOT block

本模块通过提供 :func:`build_v2_android_truth_block` 关闭以上缺口：

- 将摄取逻辑集中到一处
- 定义规范字段别名映射
- 让 routing / readiness / closure / panel / board / operator 从同一 truth block 消费

设计原则
--------
1. **单一权威** — ``build_v2_android_truth_block(device_id)`` 是产生设备级完整
   Android truth block 的唯一路径。下游消费模块 SHOULD 消费此 block，而非各自
   独立重组 truth。
2. **不引入新存储** — 本模块只读取已有权威存储（state_store、
   android_network_participation、android_mode_gate_policy），不创建额外真值存储。
3. **统一字段别名** — 所有 Android 报告的别名在 ``normalize_android_field_aliases``
   中规范化，下游无需重复处理。
4. **保守降级** — 任何子模块不可用时返回保守默认值，而不是断言更高状态。
5. **不抛异常** — 所有公开函数在子系统不可用时返回 well-typed 默认结果。

公开 API
--------
权威哨兵::

    V2_ANDROID_TRUTH_SSOT_AUTHORITY
    V2_ANDROID_TRUTH_SSOT_CONTRACT_VERSION
    V2_ANDROID_TRUTH_SSOT_POLICY

数据类::

    V2AndroidTruthBlock

函数::

    normalize_android_field_aliases(raw_payload) -> Dict[str, Any]
    build_v2_android_truth_block(device_id, *, include_history_limit) -> V2AndroidTruthBlock
    build_v2_android_truth_block_multi(device_ids, ...) -> Dict[str, V2AndroidTruthBlock]
    get_best_v2_android_truth_block(device_ids, ...) -> V2AndroidTruthBlock
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.V2AndroidTruthSSOT")

# ---------------------------------------------------------------------------
# 权威哨兵
# ---------------------------------------------------------------------------

V2_ANDROID_TRUTH_SSOT_AUTHORITY: str = (
    "V2_ANDROID_TRUTH_SSOT_V1::"
    "core.v2_android_truth_ssot 是 V2 侧 Android truth 的单一可信来源（SSOT）。"
    "build_v2_android_truth_block() 是产生设备级完整 Android truth block 的唯一路径。"
    "所有 routing / readiness / closure / panel / board / operator 消费路径"
    "SHOULD 从此 block 消费，而非各自重组 truth。"
)

V2_ANDROID_TRUTH_SSOT_CONTRACT_VERSION: str = "1.0.0"

V2_ANDROID_TRUTH_SSOT_POLICY: str = (
    "POLICY::V2_ANDROID_TRUTH_SSOT_SINGLE_BUILD_PATH: "
    "任何需要 Android 设备 participation tier / readiness / mode 信息的 V2 模块，"
    "MUST 通过 build_v2_android_truth_block(device_id) 获取统一 truth block，"
    "而不是分别调用 android_network_participation、android_device_state_store "
    "和 android_mode_gate_policy 的私有接口重组 truth。"
)

# ---------------------------------------------------------------------------
# 字段别名映射
# ---------------------------------------------------------------------------

# Android 上报字段的别名映射。键 = Android 上报的原始字段名，值 = V2 侧规范字段名。
# 这是 V2 侧的唯一别名归一化入口。
ANDROID_FIELD_ALIAS_MAP: Dict[str, str] = {
    # 模式相关别名
    "local_only": "local",
    "cross_device_active": "cross_device",
    "cross_device_degraded": "cross_device",
    "delegated": "cross_device",
    "inactive": "unknown",
    # 推理能力相关别名
    "local_intelligence_status": "local_inference_status",
    "llm_ready": "local_inference_ready",
    "model_loaded": "model_ready",
    # 可达性别名
    "a11y_ready": "accessibility_ready",
    "accessibility_service_ready": "accessibility_ready",
    # 运行时类型别名
    "LLAMA_CPP": "llama_cpp",
    "NCNN": "ncnn",
    "CENTER": "center",
    "HYBRID": "hybrid",
}

# Android 上报的可读性（readiness）状态规范值集合
ANDROID_CANONICAL_READINESS_VALUES: frozenset = frozenset(
    {"ready", "degraded", "blocked", "unknown", "transitioning"}
)

# Android 本地推理状态规范值集合
ANDROID_CANONICAL_LOCAL_INFERENCE_STATUS_VALUES: frozenset = frozenset(
    {"ready", "enabled", "degraded", "disabled", "unavailable", "unknown"}
)

# 导致本地推理不可用的状态值
ANDROID_LOCAL_INFERENCE_UNAVAILABLE_STATUSES: frozenset = frozenset(
    {"disabled", "unavailable", "unknown"}
)


def normalize_android_field_aliases(raw_payload: Dict[str, Any]) -> Dict[str, Any]:
    """对 Android 上报的原始 payload 执行字段别名归一化。

    将已知的非规范字段名替换为 V2 侧规范字段名，同时保留未知字段。
    这是 V2 侧的唯一别名归一化入口，下游消费模块不应重复此逻辑。

    Parameters
    ----------
    raw_payload:
        从 Android 设备收到的原始 payload dict（如 DEVICE_STATE_SNAPSHOT）。

    Returns
    -------
    归一化后的 payload dict（新对象，不修改输入）。
    """
    if not raw_payload:
        return {}
    normalized: Dict[str, Any] = {}
    for k, v in raw_payload.items():
        canonical_key = ANDROID_FIELD_ALIAS_MAP.get(k, k)
        # 对 mode 类字符串值同样做别名替换
        if isinstance(v, str):
            canonical_val = ANDROID_FIELD_ALIAS_MAP.get(v, v)
        else:
            canonical_val = v
        normalized[canonical_key] = canonical_val
    return normalized


# ---------------------------------------------------------------------------
# V2AndroidTruthBlock 数据类
# ---------------------------------------------------------------------------


@dataclass
class V2AndroidTruthBlock:
    """V2 侧 Android 设备完整 truth block。

    该 block 将来自 state_store / android_network_participation /
    android_mode_gate_policy 的字段聚合为一个统一的、可序列化的结构，
    供 routing / readiness / closure / panel / board / operator 路径共同消费。

    字段分组
    --------

    身份
        ``device_id`` — 设备 ID。

    参与等级（来自 android_network_participation）
        ``participation_tier`` — AndroidNetworkParticipationTier 值（字符串）。
        ``dispatch_eligible`` — 是否满足调度资格（tier >= dispatch_eligible）。
        ``distributed_participant`` — 是否为分布式参与节点（tier >= distributed_participant）。
        ``participation_blocking_reasons`` — 阻断当前等级晋升的原因列表。
        ``participation_tier_notes`` — 等级推导说明列表。
        ``participation_last_signal`` — 最后一次导致等级变更的信号名称。
        ``participation_prior_tier`` — 变更前的等级。
        ``participation_transition_history`` — 最近 N 次等级变更历史。

    可读性（来自 android_device_state_store）
        ``model_ready`` — 本地模型是否就绪。
        ``accessibility_ready`` — 无障碍服务是否就绪。
        ``local_loop_ready`` — 完整本地循环（规划/落地/执行）是否就绪。
        ``overlay_ready`` — 浮窗权限是否已授权。
        ``warmup_result`` — 模型预热结果（"ok"/"failed"/"skipped" 等）。
        ``degraded_reasons`` — 设备降级原因列表。
        ``pending_first_download`` — 是否等待初始模型下载。

    本地推理能力
        ``local_inference_ready`` — 本地推理是否就绪（来自 capability_report）。
        ``local_inference_available`` — 本地推理是否可用（来自 capability_report）。
        ``llama_cpp_available`` — libllama.so 是否加载成功。
        ``ncnn_available`` — libncnn.so 是否加载成功。
        ``active_runtime_type`` — 当前使用的推理运行时类型。

    队列/降级
        ``offline_queue_depth`` — 设备离线队列深度。
        ``current_fallback_tier`` — 当前降级阶梯等级。

    模式门控（来自 android_mode_gate_policy）
        ``device_mode`` — 设备当前模式（"local"/"cross_device"/"transitioning"/"unknown"）。
        ``cross_device_eligibility`` — 跨设备执行门是否开启。
        ``goal_execution_eligibility`` — 目标执行门是否开启。
        ``parallel_execution_eligibility`` — 并行执行门是否开启。
        ``mode_readiness_state`` — 模式可读性状态字符串。

    来源元数据
        ``built_at`` — block 构建时间戳。
        ``sources`` — 所有贡献字段的来源模块列表。
        ``build_error_notes`` — 构建过程中遇到的降级/异常说明。
    """

    # ── 身份 ────────────────────────────────────────────────────────────────
    device_id: str = ""

    # ── 参与等级 ─────────────────────────────────────────────────────────────
    participation_tier: str = "local_only"
    dispatch_eligible: bool = False
    distributed_participant: bool = False
    participation_blocking_reasons: List[str] = field(default_factory=list)
    participation_tier_notes: List[str] = field(default_factory=list)
    participation_last_signal: Optional[str] = None
    participation_prior_tier: Optional[str] = None
    participation_transition_history: List[Any] = field(default_factory=list)

    # ── 可读性 ───────────────────────────────────────────────────────────────
    model_ready: Optional[bool] = None
    accessibility_ready: Optional[bool] = None
    local_loop_ready: Optional[bool] = None
    overlay_ready: Optional[bool] = None
    warmup_result: Optional[str] = None
    degraded_reasons: List[str] = field(default_factory=list)
    pending_first_download: Optional[bool] = None

    # ── 本地推理能力 ──────────────────────────────────────────────────────────
    local_inference_ready: Optional[bool] = None
    local_inference_available: Optional[bool] = None
    llama_cpp_available: Optional[bool] = None
    ncnn_available: Optional[bool] = None
    active_runtime_type: Optional[str] = None

    # ── 队列/降级 ─────────────────────────────────────────────────────────────
    offline_queue_depth: Optional[int] = None
    current_fallback_tier: Optional[str] = None

    # ── 模式门控 ─────────────────────────────────────────────────────────────
    device_mode: str = "unknown"
    cross_device_eligibility: Optional[bool] = None
    goal_execution_eligibility: Optional[bool] = None
    parallel_execution_eligibility: Optional[bool] = None
    mode_readiness_state: Optional[str] = None

    # ── 来源元数据 ────────────────────────────────────────────────────────────
    built_at: float = field(default_factory=time.time)
    sources: List[str] = field(default_factory=list)
    build_error_notes: List[str] = field(default_factory=list)

    # ── SSOT 版本 ─────────────────────────────────────────────────────────────
    ssot_version: str = V2_ANDROID_TRUTH_SSOT_CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        """返回 JSON 可序列化的 dict 表示。"""
        return {
            # 身份
            "device_id": self.device_id,
            # 参与等级
            "participation_tier": self.participation_tier,
            "dispatch_eligible": self.dispatch_eligible,
            "distributed_participant": self.distributed_participant,
            "participation_blocking_reasons": list(self.participation_blocking_reasons),
            "participation_tier_notes": list(self.participation_tier_notes),
            "participation_last_signal": self.participation_last_signal,
            "participation_prior_tier": self.participation_prior_tier,
            "participation_transition_history": list(self.participation_transition_history),
            # 可读性
            "model_ready": self.model_ready,
            "accessibility_ready": self.accessibility_ready,
            "local_loop_ready": self.local_loop_ready,
            "overlay_ready": self.overlay_ready,
            "warmup_result": self.warmup_result,
            "degraded_reasons": list(self.degraded_reasons),
            "pending_first_download": self.pending_first_download,
            # 本地推理能力
            "local_inference_ready": self.local_inference_ready,
            "local_inference_available": self.local_inference_available,
            "llama_cpp_available": self.llama_cpp_available,
            "ncnn_available": self.ncnn_available,
            "active_runtime_type": self.active_runtime_type,
            # 队列/降级
            "offline_queue_depth": self.offline_queue_depth,
            "current_fallback_tier": self.current_fallback_tier,
            # 模式门控
            "device_mode": self.device_mode,
            "cross_device_eligibility": self.cross_device_eligibility,
            "goal_execution_eligibility": self.goal_execution_eligibility,
            "parallel_execution_eligibility": self.parallel_execution_eligibility,
            "mode_readiness_state": self.mode_readiness_state,
            # 来源元数据
            "built_at": self.built_at,
            "sources": list(self.sources),
            "build_error_notes": list(self.build_error_notes),
            "ssot_version": self.ssot_version,
            "_authority": V2_ANDROID_TRUTH_SSOT_AUTHORITY,
        }

    def as_participation_evidence(self) -> Dict[str, Any]:
        """将此 block 转为 participation_evidence 格式，供 v2_unified_state_contract 消费。

        该方法保证与 get_android_participation_evidence() 的现有返回格式兼容，
        使下游无需改变消费接口。
        """
        return {
            "device_id": self.device_id,
            "tier": self.participation_tier,
            "blocking_reasons": list(self.participation_blocking_reasons),
            "tier_derivation_notes": list(self.participation_tier_notes),
            "source": "core.v2_android_truth_ssot",
            "transition_history": list(self.participation_transition_history),
            "last_signal": self.participation_last_signal,
            "prior_tier": self.participation_prior_tier,
        }

    def as_participation_verdict(self) -> Dict[str, Any]:
        """将此 block 转为 android_participation_verdict 格式，供 panel / board 消费。

        该方法保证与 unified_panel_aggregation._fill_android_participation_verdict()
        的现有输出格式兼容，使下游无需改变消费接口。
        """
        return {
            "device_id": self.device_id,
            "tier": self.participation_tier,
            "blocking_reasons": list(self.participation_blocking_reasons),
            "tier_derivation_notes": list(self.participation_tier_notes),
            "_source": "core.v2_android_truth_ssot",
        }


# ---------------------------------------------------------------------------
# build_v2_android_truth_block
# ---------------------------------------------------------------------------


def build_v2_android_truth_block(
    device_id: str,
    *,
    include_history_limit: int = 10,
) -> V2AndroidTruthBlock:
    """构建指定设备的 V2 侧 Android truth SSOT block。

    从以下权威来源聚合字段，返回统一的 :class:`V2AndroidTruthBlock`：

    1. ``core.android_network_participation`` — 参与等级 + 阻断原因
    2. ``core.android_device_state_store`` — 设备快照（readiness / 能力 / 队列）
    3. ``core.android_mode_gate_policy`` — 模式门控（mode / eligibility）

    所有子系统均在独立 try/except 块中读取，任何单一来源失败不影响其他字段。

    Parameters
    ----------
    device_id:
        目标设备 ID。
    include_history_limit:
        参与等级变更历史条数上限（默认 10）。

    Returns
    -------
    填充的 :class:`V2AndroidTruthBlock`。当所有子系统不可用时返回带保守默认值的 block。
    """
    block = V2AndroidTruthBlock(device_id=device_id)

    # ── 1. 参与等级（android_network_participation）─────────────────────────
    try:
        from core.android_network_participation import (
            AndroidNetworkParticipationTier,
            get_participation_state_for_device,
            list_participation_transition_history,
        )

        state = get_participation_state_for_device(device_id)
        tier = state.tier
        block.participation_tier = tier.value
        block.dispatch_eligible = (
            tier >= AndroidNetworkParticipationTier.dispatch_eligible
        )
        block.distributed_participant = (
            tier >= AndroidNetworkParticipationTier.distributed_participant
        )
        block.participation_blocking_reasons = list(state.blocking_reasons)
        block.participation_tier_notes = list(state.tier_derivation_notes)
        block.participation_last_signal = (
            state.last_signal.value if state.last_signal is not None else None
        )
        block.participation_prior_tier = (
            state.prior_tier.value if state.prior_tier is not None else None
        )
        block.participation_transition_history = list(
            list_participation_transition_history(device_id, limit=include_history_limit)
        )
        block.sources.append("core.android_network_participation")
    except Exception as exc:  # noqa: BLE001
        note = f"android_network_participation unavailable: {exc}"
        logger.debug("build_v2_android_truth_block[%s]: %s", device_id, note)
        block.build_error_notes.append(note)
        block.participation_blocking_reasons.append("participation_evidence_unavailable")

    # ── 2. 设备快照（android_device_state_store）────────────────────────────
    try:
        from core.android_device_state_store import get_device_state_snapshot

        snap = get_device_state_snapshot(device_id)
        if snap is not None:
            block.model_ready = snap.model_ready
            block.accessibility_ready = snap.accessibility_ready
            block.local_loop_ready = snap.local_loop_ready
            block.overlay_ready = snap.overlay_ready
            block.warmup_result = snap.warmup_result
            block.degraded_reasons = list(snap.degraded_reasons)
            block.pending_first_download = snap.pending_first_download
            block.llama_cpp_available = snap.llama_cpp_available
            block.ncnn_available = snap.ncnn_available
            block.active_runtime_type = snap.active_runtime_type
            block.offline_queue_depth = snap.offline_queue_depth
            block.current_fallback_tier = snap.current_fallback_tier

            # 从 capability_report 元数据中提取本地推理能力字段
            cap_meta = getattr(snap, "raw_payload", {}) or {}
            cap_report = cap_meta.get("capability_report", {}) or {}
            if cap_report:
                cap_normalized = normalize_android_field_aliases(cap_report)
                block.local_inference_ready = _coerce_optional_bool(
                    cap_normalized.get("local_inference_ready")
                )
                block.local_inference_available = _coerce_optional_bool(
                    cap_normalized.get("local_inference_available")
                )
                block.cross_device_eligibility = _coerce_optional_bool(
                    cap_normalized.get("cross_device_eligibility")
                )
                block.goal_execution_eligibility = _coerce_optional_bool(
                    cap_normalized.get("goal_execution_eligibility")
                )
                block.parallel_execution_eligibility = _coerce_optional_bool(
                    cap_normalized.get("parallel_execution_eligibility")
                )
            block.sources.append("core.android_device_state_store")
    except Exception as exc:  # noqa: BLE001
        note = f"android_device_state_store unavailable: {exc}"
        logger.debug("build_v2_android_truth_block[%s]: %s", device_id, note)
        block.build_error_notes.append(note)

    # ── 3. 模式门控（android_mode_gate_policy）──────────────────────────────
    try:
        from core.android_mode_gate_policy import build_mode_state_for_device

        mode_state = build_mode_state_for_device(device_id)
        if mode_state is not None:
            block.device_mode = getattr(mode_state, "mode", block.device_mode)
            if block.device_mode is None:
                block.device_mode = "unknown"
            # 将 Enum 转为字符串
            if hasattr(block.device_mode, "value"):
                block.device_mode = block.device_mode.value  # type: ignore[union-attr]
            # 若 mode_state 有 cross_device_eligibility 等字段且快照未填入，补充之
            if block.cross_device_eligibility is None:
                _cde = getattr(mode_state, "cross_device_eligibility", None)
                if _cde is not None:
                    block.cross_device_eligibility = bool(_cde)
            if block.goal_execution_eligibility is None:
                _gee = getattr(mode_state, "goal_execution_eligibility", None)
                if _gee is not None:
                    block.goal_execution_eligibility = bool(_gee)
            if block.parallel_execution_eligibility is None:
                _pee = getattr(mode_state, "parallel_execution_eligibility", None)
                if _pee is not None:
                    block.parallel_execution_eligibility = bool(_pee)
            _mrs = getattr(mode_state, "mode_readiness_state", None)
            if _mrs is not None:
                block.mode_readiness_state = (
                    _mrs.value if hasattr(_mrs, "value") else str(_mrs)
                )
            block.sources.append("core.android_mode_gate_policy")
    except Exception as exc:  # noqa: BLE001
        note = f"android_mode_gate_policy unavailable: {exc}"
        logger.debug("build_v2_android_truth_block[%s]: %s", device_id, note)
        block.build_error_notes.append(note)

    return block


# ---------------------------------------------------------------------------
# build_v2_android_truth_block_multi
# ---------------------------------------------------------------------------


def build_v2_android_truth_block_multi(
    device_ids: List[str],
    *,
    include_history_limit: int = 10,
) -> Dict[str, "V2AndroidTruthBlock"]:
    """为多个设备批量构建 Android truth block。

    Parameters
    ----------
    device_ids:
        设备 ID 列表。
    include_history_limit:
        每设备参与等级变更历史条数上限。

    Returns
    -------
    以 device_id 为键的 dict，值为对应的 :class:`V2AndroidTruthBlock`。
    """
    result: Dict[str, V2AndroidTruthBlock] = {}
    for did in device_ids:
        result[did] = build_v2_android_truth_block(
            did, include_history_limit=include_history_limit
        )
    return result


# ---------------------------------------------------------------------------
# get_best_v2_android_truth_block
# ---------------------------------------------------------------------------

# 参与等级有序列表（从低到高），作为公共常量供消费模块共用
ANDROID_PARTICIPATION_TIER_ORDER: List[str] = [
    "local_only",
    "control_only",
    "cross_device_capable",
    "cross_device_enabled",
    "fully_attached",
    "dispatch_eligible",
    "distributed_participant",
]

# 内部别名，保持向后兼容
_TIER_ORDER: List[str] = ANDROID_PARTICIPATION_TIER_ORDER


def get_best_v2_android_truth_block(
    device_ids: Optional[List[str]] = None,
    *,
    include_history_limit: int = 10,
) -> "V2AndroidTruthBlock":
    """从所有已连接设备中选出参与等级最高的设备的 truth block。

    若 *device_ids* 为 None 或空，则自动从 android_device_state_store 获取设备列表。
    当无任何已连接设备时，返回带保守默认值的空 block。

    这是 panel / board 路径的推荐入口，用于替代
    unified_panel_aggregation._fill_android_participation_verdict() 中的本地循环逻辑。

    Parameters
    ----------
    device_ids:
        可选设备 ID 列表；为 None 时自动发现。
    include_history_limit:
        参与等级变更历史条数上限。

    Returns
    -------
    参与等级最高的设备的 :class:`V2AndroidTruthBlock`，或空 block。
    """
    # 如未传入，自动发现已连接设备
    if device_ids is None:
        device_ids = _discover_connected_device_ids()

    if not device_ids:
        empty = V2AndroidTruthBlock()
        empty.participation_blocking_reasons = ["no_connected_devices"]
        return empty

    best: Optional[V2AndroidTruthBlock] = None
    best_ordinal = -1

    for did in device_ids:
        blk = build_v2_android_truth_block(did, include_history_limit=include_history_limit)
        try:
            ordinal = _TIER_ORDER.index(blk.participation_tier)
        except ValueError:
            ordinal = 0
        if ordinal > best_ordinal:
            best_ordinal = ordinal
            best = blk

    return best or V2AndroidTruthBlock()


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _discover_connected_device_ids() -> List[str]:
    """从 android_device_state_store 发现所有已有快照的设备 ID 列表。"""
    try:
        from core.android_device_state_store import list_device_state_snapshots

        snapshots = list_device_state_snapshots()
        return [s.device_id for s in snapshots if s.device_id]
    except Exception as exc:  # noqa: BLE001
        logger.debug("_discover_connected_device_ids: failed: %s", exc)
        return []


def _coerce_optional_bool(value: Any) -> Optional[bool]:
    """将 value 强转为 Optional[bool]，None 保持 None。"""
    if value is None:
        return None
    return bool(value)
