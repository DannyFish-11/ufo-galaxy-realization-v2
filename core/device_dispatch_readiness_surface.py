"""
core/device_dispatch_readiness_surface.py
==========================================
设备 Dispatch 就绪状态面（Device Dispatch Readiness Surface）

问题背景
--------
在此模块之前，注册 gap、dispatch gate 拦截原因与 fully-attached 状态分散在内部
运行时逻辑中，没有统一的 control-plane 面可供运维人员或下游消费者查看"为什么
某设备无法被派发或未完全附接"。
:mod:`core.unified_dispatch_readiness_gate` 中的 ``evaluate_dispatch_readiness``
已经计算出结构化的拦截原因，但这些信息从未暴露到任何算子端点或状态板。

本模块的职责
------------
1. **聚合** — 从 UDM / 注册 gap 存储中枚举所有已知设备 ID，对每台设备调用
   :func:`~core.unified_dispatch_readiness_gate.evaluate_dispatch_readiness`
   获取完整的 :class:`~core.unified_dispatch_readiness_gate.DispatchReadinessResult`。
2. **投影** — 把结构化的 blocker 原因（注册 gap 列表、阻断说明等）转换为面向
   运维人员的统一面板输出，而不只是布尔值。
3. **兼容** — 对无法到达 UDM 的环境优雅降级：缺少设备信息时返回最小可用载荷。

公共 API
--------
``DEVICE_DISPATCH_READINESS_SURFACE_AUTHORITY``
    权威哨兵字符串，识别本模块所产生的所有输出。

``get_device_dispatch_readiness(device_id)``
    查询单台设备的 dispatch 就绪状态，返回
    :class:`~core.unified_dispatch_readiness_gate.DispatchReadinessResult`
    dict，含完整结构化拦截原因。

``get_dispatch_readiness_panel()``
    返回全设备 dispatch 就绪面板：一个 dict，其中 ``devices`` 键是每台
    已知设备的就绪摘要列表，``summary`` 提供聚合统计（就绪数、各类拦截数等）。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from core.runtime_truth_governance import (
    TRUTH_GRADE_DURABLE,
    TRUTH_GRADE_PROJECTION,
    TRUTH_GRADE_RUNTIME_ONLY,
    build_truth_governance,
)

logger = logging.getLogger("Galaxy.DeviceDispatchReadinessSurface")

# ---------------------------------------------------------------------------
# 权威哨兵
# ---------------------------------------------------------------------------

DEVICE_DISPATCH_READINESS_SURFACE_AUTHORITY: str = (
    "DEVICE_DISPATCH_READINESS_SURFACE_V1: "
    "core/device_dispatch_readiness_surface.py "
    "是设备 dispatch 就绪控制面的规范权威。"
    "所有关于某设备为何无法被派发的结构化原因必须通过本模块暴露，"
    "不得仅作内部日志输出。"
)

DEVICE_DISPATCH_READINESS_SURFACE_POLICY: str = (
    "POLICY: 注册 gap 与 dispatch gate 拦截原因是第一类可观测事实，"
    "必须通过结构化字段暴露给运维消费者，不得仅扁平化为单一布尔值。"
)

# ---------------------------------------------------------------------------
# 内部辅助：枚举所有已知设备 ID
# ---------------------------------------------------------------------------


def _enumerate_known_device_ids() -> List[str]:
    """从多个信号源中枚举已知设备 ID，对任何失败都优雅降级。

    优先级：
    1. UDM（统一设备管理器）— 最权威
    2. 注册 gap 存储 — 含最近注册过（即使 UDM 写入失败）的设备
    3. android_device_state_store — 含近期通过 DEVICE_STATE_SNAPSHOT 上报过
       状态的设备
    4. 返回空列表（不抛异常）
    """
    known: Dict[str, None] = {}

    # 来源 1：UDM
    try:
        from core.unified.device_manager import get_unified_device_manager
        udm = get_unified_device_manager()
        for device in udm.list_devices():
            # UnifiedDevice 可以是 dataclass/dict；兼容两种形式
            did = (
                device.device_id
                if hasattr(device, "device_id")
                else device.get("device_id") if isinstance(device, dict) else None
            )
            if did:
                known[did] = None
    except Exception as exc:
        logger.debug("DeviceDispatchReadinessSurface: UDM 枚举失败: %s", exc)

    # 来源 2：注册 gap 存储（即使 UDM 不可用也能看到近期注册设备）
    try:
        from galaxy_gateway.android.handlers.registration import (
            get_all_devices_with_registration_gaps,
        )
        for did in get_all_devices_with_registration_gaps():
            known[did] = None
    except Exception as exc:
        logger.debug("DeviceDispatchReadinessSurface: 注册 gap 枚举失败: %s", exc)

    # 来源 3：android_device_state_store
    try:
        from core.android_device_state_store import get_device_ecosystem_summary
        summary = get_device_ecosystem_summary()
        for device_entry in summary.get("devices") or []:
            did = (
                device_entry.get("device_id")
                if isinstance(device_entry, dict)
                else None
            )
            if did:
                known[did] = None
    except Exception as exc:
        logger.debug("DeviceDispatchReadinessSurface: 状态快照枚举失败: %s", exc)

    return list(known.keys())


# ---------------------------------------------------------------------------
# 公共 API：单设备查询
# ---------------------------------------------------------------------------


def get_device_dispatch_readiness(
    device_id: str,
    *,
    required_capabilities: Optional[List[str]] = None,
    require_cross_device_eligible: bool = False,
    session_id: Optional[str] = None,
    runtime_attachment_session_id: Optional[str] = None,
    execution_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """查询单台设备的 dispatch 就绪状态。

    调用 :func:`~core.unified_dispatch_readiness_gate.evaluate_dispatch_readiness`
    并将 :class:`~core.unified_dispatch_readiness_gate.DispatchReadinessResult`
    序列化为 dict，在顶层附加本模块的权威哨兵。

    Parameters
    ----------
    device_id
        要查询的设备 ID。
    required_capabilities
        可选的能力过滤列表，缺失时触发 BLOCKED_CAPABILITY。
    require_cross_device_eligible
        为 ``True`` 时要求设备通过跨设备资格检查。
    session_id
        可选的会话 ID，用于与注册信息交叉验证。
    runtime_attachment_session_id
        可选的附接会话 ID，用于与注册表项交叉验证。
    execution_mode
        执行模式提示（仅用于日志上下文，不影响决策）。

    Returns
    -------
    dict
        ``DispatchReadinessResult.to_dict()`` 输出 + ``"surface_authority"`` 键。
    """
    try:
        from core.unified_dispatch_readiness_gate import evaluate_dispatch_readiness
        result = evaluate_dispatch_readiness(
            device_id,
            required_capabilities=required_capabilities,
            require_cross_device_eligible=require_cross_device_eligible,
            session_id=session_id,
            runtime_attachment_session_id=runtime_attachment_session_id,
            execution_mode=execution_mode,
        )
        payload = result.to_dict()
    except Exception as exc:
        logger.error(
            "DeviceDispatchReadinessSurface: evaluate_dispatch_readiness 失败 "
            "device_id=%r: %s",
            device_id,
            exc,
        )
        payload = {
            "device_id": device_id,
            "dispatch_ready": False,
            "registered": False,
            "status": "gate_error",
            "reason": f"dispatch 就绪评估失败: {exc}",
            "registration_gaps": [],
            "attachment_state": "unknown",
            "runtime_session_id": None,
            "runtime_attachment_session_id": None,
            "transport_alive": False,
            "blocking_notes": [f"gate_evaluation_error: {exc}"],
        }

    payload["surface_authority"] = DEVICE_DISPATCH_READINESS_SURFACE_AUTHORITY
    payload["evaluated_at"] = time.time()
    payload["truth_governance"] = build_truth_governance(
        TRUTH_GRADE_PROJECTION,
        source="core.device_dispatch_readiness_surface.get_device_dispatch_readiness",
        recovery_status="live",
        field_truth_grades={
            "dispatch_verdict": TRUTH_GRADE_PROJECTION,
            "operational_support_status": TRUTH_GRADE_DURABLE,
            "attachment_state": TRUTH_GRADE_RUNTIME_ONLY,
            "transport_alive": TRUTH_GRADE_RUNTIME_ONLY,
        },
        notes=[
            "Dispatch readiness is a live control-plane projection, not durable canonical truth.",
            "Operational support is durable policy truth; attachment and transport are runtime-only observations.",
        ],
    )
    return payload


# ---------------------------------------------------------------------------
# 公共 API：全设备面板
# ---------------------------------------------------------------------------


def get_dispatch_readiness_panel(
    device_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """返回全设备 dispatch 就绪面板。

    该面板统一暴露每台已知设备的：
    - ``dispatch_ready`` 布尔值（是否完全就绪）
    - ``status`` 结构化枚举（DISPATCH_READY / BLOCKED_REGISTRATION_GAP / ...）
    - ``reason`` 人类可读解释
    - ``registration_gaps`` 注册失败步骤列表（仅 BLOCKED_REGISTRATION_GAP 时非空）
    - ``blocking_notes`` 附加阻断上下文列表
    - ``attachment_state`` 当前运行时附接状态

    Parameters
    ----------
    device_ids
        显式提供的设备 ID 列表。若为 ``None``，则从 UDM、注册 gap 存储和
        状态快照存储中自动枚举。

    Returns
    -------
    dict
        包含 ``devices`` 列表、``summary`` 聚合统计和元信息字段。
    """
    ids = device_ids if device_ids is not None else _enumerate_known_device_ids()

    devices_out: List[Dict[str, Any]] = []
    summary: Dict[str, int] = {
        "total": 0,
        "dispatch_ready": 0,
        "blocked_registration_gap": 0,
        "blocked_stale_attachment": 0,
        "blocked_transport": 0,
        "blocked_capability": 0,
        "blocked_session_validity": 0,
        "blocked_cross_device_eligibility": 0,
        "blocked_operational_support": 0,
        "blocked_other": 0,
        "not_registered": 0,
        "gate_error": 0,
    }

    for did in ids:
        entry = get_device_dispatch_readiness(did)
        devices_out.append(entry)
        summary["total"] += 1
        status = (entry.get("status") or "").lower()
        if status == "dispatch_ready":
            summary["dispatch_ready"] += 1
        elif status == "blocked_registration_gap":
            summary["blocked_registration_gap"] += 1
        elif status == "blocked_stale_attachment":
            summary["blocked_stale_attachment"] += 1
        elif status == "blocked_transport":
            summary["blocked_transport"] += 1
        elif status == "blocked_capability":
            summary["blocked_capability"] += 1
        elif status == "blocked_session_validity":
            summary["blocked_session_validity"] += 1
        elif status == "blocked_cross_device_eligibility":
            summary["blocked_cross_device_eligibility"] += 1
        elif status == "blocked_operational_support":
            summary["blocked_operational_support"] += 1
        elif status == "not_registered":
            summary["not_registered"] += 1
        elif status == "gate_error":
            summary["gate_error"] += 1
        else:
            summary["blocked_other"] += 1

    # total_blocked：排除 dispatch_ready（正常就绪）和 gate_error（评估异常，
    # 无法判断是否真的被拦截，独立统计）后的所有拦截设备数。
    # 每台设备的 status 值是互斥的（来自 DispatchReadinessStatus 枚举），
    # 因此分类计数之和 == summary["total"]，不会重复计入。
    total_blocked = (
        summary["total"]
        - summary["dispatch_ready"]
        - summary["gate_error"]
    )
    summary["total_blocked"] = total_blocked

    return {
        "devices": devices_out,
        "summary": summary,
        "compiled_at": time.time(),
        "authority": DEVICE_DISPATCH_READINESS_SURFACE_AUTHORITY,
        "policy": DEVICE_DISPATCH_READINESS_SURFACE_POLICY,
        "truth_governance": build_truth_governance(
            TRUTH_GRADE_PROJECTION,
            source="core.device_dispatch_readiness_surface.get_dispatch_readiness_panel",
            recovery_status="live",
            field_truth_grades={
                "panel_summary": TRUTH_GRADE_PROJECTION,
                "operational_support_status": TRUTH_GRADE_DURABLE,
                "attachment_state": TRUTH_GRADE_RUNTIME_ONLY,
                "transport_alive": TRUTH_GRADE_RUNTIME_ONLY,
            },
        ),
    }


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    "DEVICE_DISPATCH_READINESS_SURFACE_AUTHORITY",
    "DEVICE_DISPATCH_READINESS_SURFACE_POLICY",
    "get_device_dispatch_readiness",
    "get_dispatch_readiness_panel",
]
