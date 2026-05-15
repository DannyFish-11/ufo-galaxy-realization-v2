"""core/device_lifecycle_state.py
=================================
统一设备生命周期状态机 — 单一权威的设备状态路径实现。

## 背景

在此模块之前，V2 侧与 Android 侧对以下术语的含义各有不同定义，导致系统级
歧义：

* **registered** —— V2 侧指 UDM 中存在记录；Android 侧指已发送 device_register 消息。
* **connected** —— V2 侧指 WebSocket 连通；Android 侧指"已加入运行时"。
* **visible** —— V2 侧指 capability_report 已吸收；Android 侧无直接对应字段。
* **ready** —— V2 侧有多个分散的 readiness 门槛；Android 侧有 model_ready / accessibility_ready / local_loop_ready。
* **participating** —— V2 侧 dispatch_eligible / distributed_participant；Android 侧 execution active。
* **takeover_eligible** —— 仅出现在 android_mode_gate_policy；从未统一进生命周期路径。

本模块通过引入 **单一、分层、来自真实运行时条件的 DeviceLifecycleStage** 关闭上述
所有歧义。

## 生命周期阶段（六阶段）

::

    unregistered
        → registered
            → connected
                → ready
                    → participating
                    → takeover_eligible

阶段语义（与 Android 侧对齐）
-----------------------------
unregistered
    设备与 V2 网关之间**没有**活跃的 WebSocket 连接。设备在 V2 运行时网络中
    完全不可见。

registered
    设备已建立 WebSocket 连接**并**收到成功的 ``device_register_ack``。设备已
    在 V2 控制面中可见，但可能仍有下游注册步骤未完成（registration_gaps > 0）。

connected
    registration 完全附加（零 gaps）**且**设备能力已在 V2 上可见（capability_visible）。
    设备在结构上已准备好被选为调度目标，但运行时就绪条件尚未验证。

ready
    connected 的所有条件均满足**且** Android 侧三项就绪门槛全部通过：
    ``model_ready``、``accessibility_ready``、``local_loop_ready``，以及 V2 侧
    调度门通过（dispatch_gate_passed）。设备可以立即被选为调度目标。

participating
    ready 的所有条件均满足**且**设备正在主动参与任务执行会话
    （execution_active=True）。设备是中心—分布式运行时的活跃参与者。

takeover_eligible
    ready 的所有条件均满足**且** Android 侧接受接管条件成立
    （is_takeover_eligible=True）。设备可以接收接管请求。
    注意：takeover_eligible 与 participating 是**同级**阶段（不是更高层），
    两者都从 ready 阶段推进。

## 与现有模块的关系

* ``AndroidNetworkParticipationTier``（core/android_network_participation.py）
  ：详细的七层参与层级，仍是权威的参与层度量。DeviceLifecycleStage 是面向
  操作者和跨仓统一的六阶段视图。两者通过 ``tier_for_stage()`` / ``stage_for_tier()``
  辅助函数保持映射一致。

* ``evaluate_dispatch_readiness()``（core/unified_dispatch_readiness_gate.py）
  ：仍是调度前的权威门禁检查。DeviceLifecycleStage.ready 表示达到了
  evaluate_dispatch_readiness 期望的前置条件。

* ``AndroidModeReadinessVerdict``（core/android_mode_gate_policy.py）
  ：takeover_eligible 阶段直接消费 verdict.is_takeover_eligible。

## 公共 API

常量::

    DEVICE_LIFECYCLE_STATE_AUTHORITY
    DEVICE_LIFECYCLE_CONTRACT_VERSION
    LIFECYCLE_STAGE_SEMANTICS
    ANDROID_SIDE_LIFECYCLE_CONTRACT

枚举::

    DeviceLifecycleStage
    DeviceLifecycleTransitionEvent

数据类::

    DeviceLifecycleRecord

函数::

    evaluate_device_lifecycle_stage(device_id) -> DeviceLifecycleRecord
    transition_device_lifecycle(device_id, event, **conditions) -> DeviceLifecycleRecord
    get_lifecycle_record(device_id) -> DeviceLifecycleRecord
    record_lifecycle_state(record) -> None
    reset_lifecycle_store() -> None   # 仅用于测试隔离

辅助::

    stage_for_participation_tier(tier) -> DeviceLifecycleStage
    participation_tier_for_stage(stage) -> str
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.DeviceLifecycleState")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

DEVICE_LIFECYCLE_STATE_AUTHORITY: str = (
    "DEVICE_LIFECYCLE_STATE_AUTHORITY::"
    "core.device_lifecycle_state 是设备生命周期阶段的单一权威运行时来源。"
    "所有需要回答「该设备当前处于哪个生命周期阶段」的调用方，"
    "必须消费本模块的 get_lifecycle_record() 或 evaluate_device_lifecycle_stage()，"
    "而不是在本地重新推导分散的信号。"
)

DEVICE_LIFECYCLE_CONTRACT_VERSION: str = "1.0.0"

LIFECYCLE_STAGE_SEMANTICS: Dict[str, str] = {
    "unregistered": (
        "设备与 V2 网关之间没有活跃的 WebSocket 连接。"
        "设备在 V2 运行时网络中完全不可见。"
        "Android 侧对应：未连接或连接已断开。"
    ),
    "registered": (
        "设备已建立 WebSocket 连接并收到成功的 device_register_ack。"
        "设备已在 V2 控制面中可见，但可能仍有下游注册步骤未完成。"
        "Android 侧对应：device_register 消息已发送并收到 ack。"
    ),
    "connected": (
        "注册完全附加（零 gaps）且设备能力已在 V2 上可见。"
        "设备在结构上已准备好被选为调度目标，但运行时就绪条件尚未验证。"
        "Android 侧对应：cross_device_enabled=true，capability_report 已上报。"
    ),
    "ready": (
        "connected 的所有条件均满足，且 Android 侧三项就绪门槛全部通过："
        "model_ready、accessibility_ready、local_loop_ready，"
        "以及 V2 侧调度门通过（dispatch_gate_passed）。"
        "设备可以立即被选为调度目标。"
        "Android 侧对应：DEVICE_STATE_SNAPSHOT 报告 model_ready=true 等。"
    ),
    "participating": (
        "ready 的所有条件均满足，且设备正在主动参与任务执行会话。"
        "设备是中心—分布式运行时的活跃参与者。"
        "Android 侧对应：execution_session 活跃中。"
    ),
    "takeover_eligible": (
        "ready 的所有条件均满足，且 Android 侧接受接管条件成立。"
        "设备可以接收接管请求。"
        "Android 侧对应：is_takeover_eligible=true（来自模式门策略）。"
    ),
}

ANDROID_SIDE_LIFECYCLE_CONTRACT: str = (
    "ANDROID_SIDE_LIFECYCLE_CONTRACT::1.0.0::"
    "Android 设备（ufo-galaxy-android）必须提供以下内容以推进生命周期阶段："
    "(registered) device_register 消息 + 收到 device_register_ack；"
    "(connected) registration_gaps=[] + cross_device_enabled=true + capability_report；"
    "(ready) DEVICE_STATE_SNAPSHOT: model_ready=true, accessibility_ready=true, "
    "local_loop_ready=true；"
    "(participating) 设备已进入活跃 execution session；"
    "(takeover_eligible) mode_gate is_takeover_eligible=true。"
    "V2 侧生命周期阶段反映 V2 侧对这些条件的可观察投影，"
    "完整收敛需要 Android 侧同样维护对称的本地生命周期真相。"
)

# ---------------------------------------------------------------------------
# DeviceLifecycleStage
# ---------------------------------------------------------------------------


class DeviceLifecycleStage(str, Enum):
    """统一设备生命周期阶段枚举。

    表示严格的由低到高顺序。设备处于满足**所有**条件的最高阶段。

    Attributes
    ----------
    unregistered
        无 WebSocket 连接。设备在 V2 中完全不可见。
    registered
        WebSocket 连接已建立 + device_register_ack 已收到。可能存在注册 gaps。
    connected
        注册完全附加（零 gaps）+ 能力可见。结构就绪，等待运行时就绪验证。
    ready
        connected + model_ready + accessibility_ready + local_loop_ready +
        dispatch_gate 通过。可立即调度。
    participating
        ready + 执行会话活跃中。是中心—分布式运行时的活跃参与者。
    takeover_eligible
        ready + takeover 条件成立。可接收接管请求。
        （与 participating 同级，均从 ready 阶段推进）
    """

    unregistered = "unregistered"
    registered = "registered"
    connected = "connected"
    ready = "ready"
    participating = "participating"
    takeover_eligible = "takeover_eligible"

    def ordinal(self) -> int:
        """返回阶段的数字序号（0 = 最低）。"""
        _ord = {
            "unregistered": 0,
            "registered": 1,
            "connected": 2,
            "ready": 3,
            "participating": 4,
            "takeover_eligible": 4,   # 与 participating 同级
        }
        return _ord.get(self.value, 0)

    def __ge__(self, other: "DeviceLifecycleStage") -> bool:  # type: ignore[override]
        if not isinstance(other, DeviceLifecycleStage):
            return NotImplemented  # type: ignore[return-value]
        return self.ordinal() >= other.ordinal()

    def __gt__(self, other: "DeviceLifecycleStage") -> bool:  # type: ignore[override]
        if not isinstance(other, DeviceLifecycleStage):
            return NotImplemented  # type: ignore[return-value]
        return self.ordinal() > other.ordinal()

    def __le__(self, other: "DeviceLifecycleStage") -> bool:  # type: ignore[override]
        if not isinstance(other, DeviceLifecycleStage):
            return NotImplemented  # type: ignore[return-value]
        return self.ordinal() <= other.ordinal()

    def __lt__(self, other: "DeviceLifecycleStage") -> bool:  # type: ignore[override]
        if not isinstance(other, DeviceLifecycleStage):
            return NotImplemented  # type: ignore[return-value]
        return self.ordinal() < other.ordinal()

    @classmethod
    def from_string(cls, value: str) -> "DeviceLifecycleStage":
        """从字符串返回枚举成员，默认为 unregistered。"""
        try:
            return cls(value.lower().strip())
        except (ValueError, AttributeError):
            return cls.unregistered


# ---------------------------------------------------------------------------
# DeviceLifecycleTransitionEvent
# ---------------------------------------------------------------------------


class DeviceLifecycleTransitionEvent(str, Enum):
    """驱动生命周期阶段转换的命名事件。

    每个事件对应一个真实的运行时发生点，可被各个处理器在真实路径中触发。
    """

    # 上升事件
    websocket_connected = "websocket_connected"
    """WebSocket 连接已建立（来自网关）。"""

    register_ack_sent = "register_ack_sent"
    """device_register_ack 已成功发送。设备进入 registered 阶段。"""

    registration_fully_attached = "registration_fully_attached"
    """所有下游注册步骤完成（gaps = []）+ 能力可见。设备进入 connected 阶段。"""

    readiness_satisfied = "readiness_satisfied"
    """Android 侧三项就绪门槛通过 + dispatch gate 通过。设备进入 ready 阶段。"""

    execution_session_started = "execution_session_started"
    """活跃任务执行会话已启动。设备进入 participating 阶段。"""

    takeover_eligibility_gained = "takeover_eligibility_gained"
    """接管条件成立（is_takeover_eligible=True）。设备进入 takeover_eligible 阶段。"""

    operator_suspension_lifted = "operator_suspension_lifted"
    """运营商暂停已解除。从当前运行时条件重新推导阶段。"""

    # 下降事件
    websocket_disconnected = "websocket_disconnected"
    """WebSocket 连接已断开。设备强制回退到 unregistered。"""

    registration_gap_detected = "registration_gap_detected"
    """检测到注册 gap。设备从 connected 回退到 registered。"""

    readiness_lost = "readiness_lost"
    """就绪条件失去（model_ready 等变为 False）。设备从 ready 回退到 connected。"""

    execution_session_ended = "execution_session_ended"
    """活跃执行会话结束。设备从 participating 回退到 ready。"""

    takeover_eligibility_lost = "takeover_eligibility_lost"
    """接管条件不再成立。设备从 takeover_eligible 回退到 ready。"""

    operator_suspended = "operator_suspended"
    """运营商暂停已施加。设备强制退回到 registered 或更低阶段。"""

    attachment_break = "attachment_break"
    """注册/会话状态出现附加断裂。从当前注册状态重新推导阶段。"""


# ---------------------------------------------------------------------------
# DeviceLifecycleRecord
# ---------------------------------------------------------------------------


@dataclass
class DeviceLifecycleRecord:
    """单设备的完整生命周期状态记录。

    Attributes
    ----------
    device_id
        设备标识符。
    stage
        当前 :class:`DeviceLifecycleStage`。
    last_event
        最后一个触发阶段变化的 :class:`DeviceLifecycleTransitionEvent`，
        如果没有事件被应用则为 None。
    prior_stage
        上一次事件前的阶段，None 表示初次推导。
    derived_at
        推导时的 Unix 时间戳（秒）。

    运行时条件快照（均为可选）
    -------------------------
    websocket_connected
        WebSocket 连接是否活跃。
    registration_ack_success
        是否已收到成功的 device_register_ack。
    registration_fully_attached
        注册是否以零 gaps 完成。
    registration_gaps
        未完成的注册步骤名称列表（空 = 无 gap）。
    capability_visible
        设备能力是否在 V2 上可见。
    readiness_satisfied
        model_ready + accessibility_ready + local_loop_ready 是否全部通过。
    dispatch_gate_passed
        模式门 + V2 cross-device 开关检查是否通过。
    execution_active
        是否有活跃的任务执行会话正在进行。
    takeover_eligible
        是否满足接管条件（来自模式门策略）。
    operator_suspended
        是否有运营商暂停正在生效。

    诊断
    ----
    blocking_reasons
        阻止推进到更高阶段的条件列表（人类可读）。
    stage_derivation_notes
        推导追踪说明，供诊断使用。
    """

    device_id: str
    stage: DeviceLifecycleStage = DeviceLifecycleStage.unregistered
    last_event: Optional[DeviceLifecycleTransitionEvent] = None
    prior_stage: Optional[DeviceLifecycleStage] = None
    derived_at: float = field(default_factory=time.time)

    # 运行时条件
    websocket_connected: bool = False
    registration_ack_success: bool = False
    registration_fully_attached: bool = False
    registration_gaps: List[str] = field(default_factory=list)
    capability_visible: bool = False
    readiness_satisfied: bool = False
    dispatch_gate_passed: bool = False
    execution_active: bool = False
    takeover_eligible: bool = False
    operator_suspended: bool = False

    # 诊断
    blocking_reasons: List[str] = field(default_factory=list)
    stage_derivation_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "stage": self.stage.value,
            "last_event": self.last_event.value if self.last_event else None,
            "prior_stage": self.prior_stage.value if self.prior_stage else None,
            "derived_at": self.derived_at,
            "websocket_connected": self.websocket_connected,
            "registration_ack_success": self.registration_ack_success,
            "registration_fully_attached": self.registration_fully_attached,
            "registration_gaps": list(self.registration_gaps),
            "capability_visible": self.capability_visible,
            "readiness_satisfied": self.readiness_satisfied,
            "dispatch_gate_passed": self.dispatch_gate_passed,
            "execution_active": self.execution_active,
            "takeover_eligible": self.takeover_eligible,
            "operator_suspended": self.operator_suspended,
            "blocking_reasons": list(self.blocking_reasons),
            "stage_derivation_notes": list(self.stage_derivation_notes),
            "_authority": DEVICE_LIFECYCLE_STATE_AUTHORITY,
            "_contract_version": DEVICE_LIFECYCLE_CONTRACT_VERSION,
        }


# ---------------------------------------------------------------------------
# 核心推导函数
# ---------------------------------------------------------------------------


def derive_device_lifecycle_stage(
    *,
    websocket_connected: bool,
    registration_ack_success: bool,
    registration_fully_attached: bool,
    registration_gaps: Optional[List[str]] = None,
    capability_visible: bool,
    readiness_satisfied: bool,
    dispatch_gate_passed: bool,
    execution_active: bool = False,
    takeover_eligible: bool = False,
    operator_suspended: bool = False,
) -> tuple[DeviceLifecycleStage, List[str], List[str]]:
    """从运行时条件推导规范生命周期阶段。

    这是 **唯一权威的生命周期推导函数**。按严格的底层到顶层顺序评估条件，
    返回满足**所有**要求的最高阶段。

    Returns
    -------
    tuple[DeviceLifecycleStage, List[str], List[str]]
        ``(stage, blocking_reasons, derivation_notes)``
    """
    gaps = list(registration_gaps or [])
    blocking: List[str] = []
    notes: List[str] = []

    # --- 运营商暂停覆盖一切 ---
    if operator_suspended:
        blocking.append("operator_suspended: 设备处于运营商施加的暂停状态")
        notes.append("因运营商暂停，阶段上限为 registered（若已注册）或 unregistered。")
        if websocket_connected and registration_ack_success:
            return (DeviceLifecycleStage.registered, blocking, notes)
        return (DeviceLifecycleStage.unregistered, blocking, notes)

    # --- 阶段 0: unregistered ---
    if not websocket_connected:
        blocking.append("websocket_connected=False: 无活跃 WebSocket 连接")
        notes.append("无 WebSocket 连接 → unregistered。")
        return (DeviceLifecycleStage.unregistered, blocking, notes)

    notes.append("websocket_connected=True")

    # --- 阶段 1: registered ---
    if not registration_ack_success:
        blocking.append("registration_ack_success=False: device_register_ack 尚未收到")
        notes.append("WebSocket 已连接但注册 ack 未收到 → unregistered。")
        return (DeviceLifecycleStage.unregistered, blocking, notes)

    notes.append("registration_ack_success=True → registered")
    # 设备已注册；可能仍有 gaps，但不阻止 registered 阶段

    # --- 阶段 2: connected ---
    if gaps:
        blocking.append(
            f"registration_gaps={gaps}: 注册有未完成的下游步骤"
        )
        notes.append(f"已注册但有 {len(gaps)} 个 gap(s) → registered（非 connected）。")
        return (DeviceLifecycleStage.registered, blocking, notes)

    if not capability_visible:
        blocking.append(
            "capability_visible=False: 设备能力尚未在 V2 上可见"
        )
        notes.append("完全附加但 capability_visible=False → registered。")
        return (DeviceLifecycleStage.registered, blocking, notes)

    notes.append("registration_fully_attached=True（无 gap），capability_visible=True → connected")

    # --- 阶段 3: ready ---
    if not readiness_satisfied:
        blocking.append(
            "readiness_satisfied=False: model/accessibility/local_loop 就绪条件未满足"
        )
    if not dispatch_gate_passed:
        blocking.append(
            "dispatch_gate_passed=False: 模式门或 V2 cross-device 开关检查失败"
        )

    if not readiness_satisfied or not dispatch_gate_passed:
        notes.append(
            f"connected 但 readiness_satisfied={readiness_satisfied}，"
            f"dispatch_gate_passed={dispatch_gate_passed} → connected 阶段。"
        )
        return (DeviceLifecycleStage.connected, blocking, notes)

    notes.append("readiness_satisfied=True，dispatch_gate_passed=True → ready")

    # --- 阶段 4a: participating / 阶段 4b: takeover_eligible ---
    # 两者同级，同时评估，取已满足的阶段

    if execution_active:
        notes.append("execution_active=True → participating")
        return (DeviceLifecycleStage.participating, [], notes)

    if takeover_eligible:
        notes.append("takeover_eligible=True → takeover_eligible")
        return (DeviceLifecycleStage.takeover_eligible, [], notes)

    blocking.append(
        "execution_active=False: 无活跃分布式执行会话"
    )
    if not takeover_eligible:
        blocking.append(
            "takeover_eligible=False: 接管条件不成立"
        )
    notes.append("ready 但 execution_active=False，takeover_eligible=False → ready 阶段。")
    return (DeviceLifecycleStage.ready, blocking, notes)


# ---------------------------------------------------------------------------
# 阶段映射辅助
# ---------------------------------------------------------------------------

#: 将 AndroidNetworkParticipationTier 字符串映射到最接近的 DeviceLifecycleStage。
#: 用于保持与现有参与层的一致性。
_TIER_TO_STAGE: Dict[str, DeviceLifecycleStage] = {
    "local_only": DeviceLifecycleStage.unregistered,
    "control_only": DeviceLifecycleStage.registered,
    "cross_device_capable": DeviceLifecycleStage.registered,
    "cross_device_enabled": DeviceLifecycleStage.connected,
    "fully_attached": DeviceLifecycleStage.connected,
    "dispatch_eligible": DeviceLifecycleStage.ready,
    "distributed_participant": DeviceLifecycleStage.participating,
}

#: 将 DeviceLifecycleStage 映射回最接近的参与层级字符串（用于向后兼容）。
_STAGE_TO_TIER: Dict[DeviceLifecycleStage, str] = {
    DeviceLifecycleStage.unregistered: "local_only",
    DeviceLifecycleStage.registered: "control_only",
    DeviceLifecycleStage.connected: "fully_attached",
    DeviceLifecycleStage.ready: "dispatch_eligible",
    DeviceLifecycleStage.participating: "distributed_participant",
    DeviceLifecycleStage.takeover_eligible: "dispatch_eligible",
}


def stage_for_participation_tier(tier_value: str) -> DeviceLifecycleStage:
    """将 AndroidNetworkParticipationTier 字符串转换为 DeviceLifecycleStage。"""
    return _TIER_TO_STAGE.get(tier_value, DeviceLifecycleStage.unregistered)


def participation_tier_for_stage(stage: DeviceLifecycleStage) -> str:
    """将 DeviceLifecycleStage 转换为最接近的参与层级字符串（用于向后兼容）。"""
    return _STAGE_TO_TIER.get(stage, "local_only")


# ---------------------------------------------------------------------------
# 内存存储（有界 LRU）
# ---------------------------------------------------------------------------

_LIFECYCLE_STORE_MAX: int = 512
_lifecycle_store: OrderedDict = OrderedDict()  # device_id → DeviceLifecycleRecord
_lifecycle_store_lock = threading.Lock()


def record_lifecycle_state(record: DeviceLifecycleRecord) -> None:
    """持久化 *record* 到内存存储。线程安全，超过上限时 LRU 淘汰。"""
    if not record.device_id:
        return
    with _lifecycle_store_lock:
        _lifecycle_store.pop(record.device_id, None)  # 移动到末尾
        if len(_lifecycle_store) >= _LIFECYCLE_STORE_MAX:
            _lifecycle_store.popitem(last=False)
        _lifecycle_store[record.device_id] = record


def get_stored_lifecycle_record(device_id: str) -> Optional[DeviceLifecycleRecord]:
    """返回 *device_id* 存储的 :class:`DeviceLifecycleRecord`，不存在则返回 None。"""
    with _lifecycle_store_lock:
        return _lifecycle_store.get(device_id)


def reset_lifecycle_store() -> None:
    """清除所有存储的记录（仅用于测试隔离）。"""
    with _lifecycle_store_lock:
        _lifecycle_store.clear()


# ---------------------------------------------------------------------------
# 公共 API: get_lifecycle_record
# ---------------------------------------------------------------------------


def get_lifecycle_record(device_id: str) -> DeviceLifecycleRecord:
    """返回 *device_id* 的规范生命周期记录。

    优先返回存储的记录（由注册处理器等明确触发器更新），如果存储中没有则
    从真实运行时条件派生。

    这是推荐给大多数消费者使用的 API——它既尊重已处理的明确转换，又能在
    记录不存在时降级到实时推导。

    永不抛出异常。
    """
    stored = get_stored_lifecycle_record(device_id)
    if stored is not None:
        return stored
    return evaluate_device_lifecycle_stage(device_id)


# ---------------------------------------------------------------------------
# 公共 API: evaluate_device_lifecycle_stage（从真实运行时推导）
# ---------------------------------------------------------------------------


def evaluate_device_lifecycle_stage(device_id: str) -> DeviceLifecycleRecord:
    """从 V2 侧真实运行时存储推导 *device_id* 的生命周期阶段。

    读取以下真实运行时来源：
    1. ``core.attached_runtime_session_registry`` — WebSocket 连接、注册 ack、gaps
    2. ``core.android_device_state_store`` — 就绪条件（model/accessibility/local_loop）
    3. ``core.android_mode_gate_policy`` — capability_visible、dispatch_gate、takeover_eligible
    4. ``core.android_participant_session_state`` — execution_active

    永不抛出异常。当所有运行时存储都不可用时，退化为 unregistered。
    """
    websocket_connected = False
    registration_ack_success = False
    registration_fully_attached = False
    registration_gaps: List[str] = []
    capability_visible = False
    readiness_satisfied = False
    dispatch_gate_passed = False
    execution_active = False
    takeover_eligible_flag = False
    operator_suspended = False

    # 1. 从 attached_runtime_session_registry 读取
    try:
        from core.attached_runtime_session_registry import get_registry  # noqa: PLC0415
        registry = get_registry()
        entry = registry.lookup_session_by_device(device_id)
        if entry is not None:
            websocket_connected = True
            registration_ack_success = True
            if hasattr(entry, "registration_gaps"):
                registration_gaps = list(entry.registration_gaps or [])
            registration_fully_attached = len(registration_gaps) == 0
    except Exception as exc:
        logger.debug(
            "evaluate_device_lifecycle_stage: session_registry 读取失败 device_id=%r: %s",
            device_id, exc,
        )

    # 2. 从 android_device_state_store 读取就绪条件
    try:
        from core.android_device_state_store import get_device_state_snapshot  # noqa: PLC0415
        snapshot = get_device_state_snapshot(device_id)
        if snapshot is not None:
            model_ready = bool(getattr(snapshot, "model_ready", False))
            accessibility_ready = bool(getattr(snapshot, "accessibility_ready", False))
            local_loop_ready = bool(getattr(snapshot, "local_loop_ready", False))
            readiness_satisfied = model_ready and accessibility_ready and local_loop_ready
    except Exception as exc:
        logger.debug(
            "evaluate_device_lifecycle_stage: 快照读取失败 device_id=%r: %s",
            device_id, exc,
        )

    # 3. 从 android_mode_gate_policy 读取能力可见性、调度门、接管资格
    try:
        from core.android_mode_gate_policy import (  # noqa: PLC0415
            build_mode_state_for_device,
            evaluate_android_mode_readiness,
        )
        mode_state = build_mode_state_for_device(device_id)
        if mode_state is not None:
            capability_visible = bool(mode_state.cross_device_enabled)

        verdict = evaluate_android_mode_readiness(device_id)
        dispatch_gate_passed = bool(verdict.is_dispatch_eligible)
        takeover_eligible_flag = bool(verdict.is_takeover_eligible)
        if dispatch_gate_passed and not readiness_satisfied:
            # 如果门通过，说明就绪条件也满足
            readiness_satisfied = True
    except Exception as exc:
        logger.debug(
            "evaluate_device_lifecycle_stage: mode_gate 读取失败 device_id=%r: %s",
            device_id, exc,
        )

    # 4. 检测活跃执行会话
    try:
        from core.android_participant_session_state import list_active_participant_sessions  # noqa: PLC0415
        active_sessions = list_active_participant_sessions()
        execution_active = any(
            getattr(s, "device_id", "") == device_id
            and getattr(s, "phase", "").startswith("execution")
            for s in active_sessions
        )
    except Exception as exc:
        logger.debug(
            "evaluate_device_lifecycle_stage: 参与会话读取失败 device_id=%r: %s",
            device_id, exc,
        )

    stage, blocking, notes = derive_device_lifecycle_stage(
        websocket_connected=websocket_connected,
        registration_ack_success=registration_ack_success,
        registration_fully_attached=registration_fully_attached,
        registration_gaps=registration_gaps,
        capability_visible=capability_visible,
        readiness_satisfied=readiness_satisfied,
        dispatch_gate_passed=dispatch_gate_passed,
        execution_active=execution_active,
        takeover_eligible=takeover_eligible_flag,
        operator_suspended=operator_suspended,
    )

    return DeviceLifecycleRecord(
        device_id=device_id,
        stage=stage,
        last_event=None,
        prior_stage=None,
        websocket_connected=websocket_connected,
        registration_ack_success=registration_ack_success,
        registration_fully_attached=registration_fully_attached,
        registration_gaps=list(registration_gaps),
        capability_visible=capability_visible,
        readiness_satisfied=readiness_satisfied,
        dispatch_gate_passed=dispatch_gate_passed,
        execution_active=execution_active,
        takeover_eligible=takeover_eligible_flag,
        operator_suspended=operator_suspended,
        blocking_reasons=blocking,
        stage_derivation_notes=notes,
    )


# ---------------------------------------------------------------------------
# 公共 API: transition_device_lifecycle（事件驱动的显式转换）
# ---------------------------------------------------------------------------


def transition_device_lifecycle(
    device_id: str,
    event: DeviceLifecycleTransitionEvent,
    *,
    websocket_connected: Optional[bool] = None,
    registration_ack_success: Optional[bool] = None,
    registration_fully_attached: Optional[bool] = None,
    registration_gaps: Optional[List[str]] = None,
    capability_visible: Optional[bool] = None,
    readiness_satisfied: Optional[bool] = None,
    dispatch_gate_passed: Optional[bool] = None,
    execution_active: Optional[bool] = None,
    takeover_eligible: Optional[bool] = None,
    operator_suspended: Optional[bool] = None,
) -> DeviceLifecycleRecord:
    """对 *device_id* 应用 *event* 并持久化新的生命周期记录。

    从已存储的记录（或从运行时推导的基础状态）中取出当前条件，用调用方
    提供的 kwarg 覆盖相关条件，然后重新推导阶段并持久化。

    这是注册处理器、快照处理器等真实路径处理器应调用的 API。

    Parameters
    ----------
    device_id
        设备标识符。
    event
        触发本次转换的 :class:`DeviceLifecycleTransitionEvent`。
    **条件 kwargs**
        只传入本次事件**实际改变**的条件。未提供的条件沿用当前存储值。

    Returns
    -------
    DeviceLifecycleRecord
        应用事件后的新记录（已持久化）。
    """
    # 取当前基础状态
    current = get_stored_lifecycle_record(device_id)
    if current is None:
        current = evaluate_device_lifecycle_stage(device_id)

    # 用调用方提供的值覆盖条件
    new_ws = websocket_connected if websocket_connected is not None else current.websocket_connected
    new_ack = registration_ack_success if registration_ack_success is not None else current.registration_ack_success
    new_fully = registration_fully_attached if registration_fully_attached is not None else current.registration_fully_attached
    new_gaps = list(registration_gaps) if registration_gaps is not None else list(current.registration_gaps)
    new_cap = capability_visible if capability_visible is not None else current.capability_visible
    new_ready = readiness_satisfied if readiness_satisfied is not None else current.readiness_satisfied
    new_gate = dispatch_gate_passed if dispatch_gate_passed is not None else current.dispatch_gate_passed
    new_exec = execution_active if execution_active is not None else current.execution_active
    new_takeover = takeover_eligible if takeover_eligible is not None else current.takeover_eligible
    new_suspended = operator_suspended if operator_suspended is not None else current.operator_suspended

    # 特定事件的强制覆盖，确保下降事件正确清除条件
    if event == DeviceLifecycleTransitionEvent.websocket_disconnected:
        new_ws = False
        new_ack = False
        new_fully = False
        new_gaps = []
        new_cap = False
        new_ready = False
        new_gate = False
        new_exec = False
        new_takeover = False
        new_suspended = False

    elif event == DeviceLifecycleTransitionEvent.operator_suspended:
        new_suspended = True

    elif event == DeviceLifecycleTransitionEvent.operator_suspension_lifted:
        new_suspended = False

    elif event == DeviceLifecycleTransitionEvent.readiness_lost:
        new_ready = False
        new_gate = False

    elif event == DeviceLifecycleTransitionEvent.execution_session_ended:
        new_exec = False

    elif event == DeviceLifecycleTransitionEvent.takeover_eligibility_lost:
        new_takeover = False

    elif event == DeviceLifecycleTransitionEvent.registration_gap_detected:
        new_fully = False

    stage, blocking, notes = derive_device_lifecycle_stage(
        websocket_connected=new_ws,
        registration_ack_success=new_ack,
        registration_fully_attached=new_fully,
        registration_gaps=new_gaps,
        capability_visible=new_cap,
        readiness_satisfied=new_ready,
        dispatch_gate_passed=new_gate,
        execution_active=new_exec,
        takeover_eligible=new_takeover,
        operator_suspended=new_suspended,
    )

    new_record = DeviceLifecycleRecord(
        device_id=device_id,
        stage=stage,
        last_event=event,
        prior_stage=current.stage,
        websocket_connected=new_ws,
        registration_ack_success=new_ack,
        registration_fully_attached=new_fully,
        registration_gaps=new_gaps,
        capability_visible=new_cap,
        readiness_satisfied=new_ready,
        dispatch_gate_passed=new_gate,
        execution_active=new_exec,
        takeover_eligible=new_takeover,
        operator_suspended=new_suspended,
        blocking_reasons=blocking,
        stage_derivation_notes=notes,
    )
    record_lifecycle_state(new_record)

    logger.debug(
        "transition_device_lifecycle: device_id=%r event=%s %s → %s",
        device_id,
        event.value,
        current.stage.value,
        stage.value,
    )
    return new_record


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    "DEVICE_LIFECYCLE_STATE_AUTHORITY",
    "DEVICE_LIFECYCLE_CONTRACT_VERSION",
    "LIFECYCLE_STAGE_SEMANTICS",
    "ANDROID_SIDE_LIFECYCLE_CONTRACT",
    "DeviceLifecycleStage",
    "DeviceLifecycleTransitionEvent",
    "DeviceLifecycleRecord",
    "derive_device_lifecycle_stage",
    "evaluate_device_lifecycle_stage",
    "transition_device_lifecycle",
    "get_lifecycle_record",
    "record_lifecycle_state",
    "get_stored_lifecycle_record",
    "reset_lifecycle_store",
    "stage_for_participation_tier",
    "participation_tier_for_stage",
]
