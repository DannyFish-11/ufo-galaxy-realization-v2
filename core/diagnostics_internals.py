"""core/diagnostics_internals.py — 各子系统写好了、却读不出来的内部快照，收在一个只读诊断索引里。

一批注册表 / 投影 / 审计各自有「给诊断看」的读取方法（docstring 里多半直接写着「供面板 / 诊断
取用」），却没有任何端点把它们读出来：协议漂移只进不出、设备激活表写了没人能读、发布闸门、
关键路径、每类事件的订阅数、会话执行通道、重绑表……

这里把它们按名字登记成「段」，``GET /api/v1/diagnostics/internals`` 列出全部段，
``GET /api/v1/diagnostics/internals/{name}`` 读一段（需要参数的段用 ``?q=``）。

- **只读**：每一段只调读取方法，不改任何状态。
- **不上面板**：这是给排查问题的人看的，面板不画它（所有者的取舍：该放面板的放，不该的收起来）。
- **一段坏了不连累别的段**：每段独立吞异常，把错误写进返回值。
"""

from __future__ import annotations

import dataclasses
import enum
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_ITEMS = 200


def jsonable(value: Any, _depth: int = 0) -> Any:
    """尽量把各种快照对象转成 JSON 能装的东西（to_dict / model_dump / dataclass / 枚举 / 集合）。"""
    if _depth > 8:
        return str(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dict):
        return {str(jsonable(k, _depth + 1)): jsonable(v, _depth + 1) for k, v in list(value.items())[:_MAX_ITEMS]}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=str) if isinstance(value, (set, frozenset)) else value
        return [jsonable(v, _depth + 1) for v in list(items)[:_MAX_ITEMS]]
    for attr in ("to_dict", "model_dump"):
        method = getattr(value, attr, None)
        if callable(method):
            try:
                return jsonable(method(), _depth + 1)
            except Exception:  # noqa: BLE001
                pass
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return jsonable(dataclasses.asdict(value), _depth + 1)
    return str(value)


# ---------------------------------------------------------------------------
# 各段
# ---------------------------------------------------------------------------


def _fast_loop(_q: str) -> Any:
    from core.fast_loop import active_loop_name

    return {"active_loop": active_loop_name()}


def _admission(_q: str) -> Any:
    from core.request_admission import admission_snapshot

    return admission_snapshot()


def _pending_envelopes(_q: str) -> Any:
    from core.task_envelope_lifecycle_registry import get_lifecycle_registry

    pending = get_lifecycle_registry().all_pending_task_ids()
    return {"count": len(pending), "task_ids": pending}


def _budget_sessions(_q: str) -> Any:
    from core.governance.budget_enforcer import get_budget_enforcer

    return {"session_ids": get_budget_enforcer().all_session_ids()}


def _authority_hardening(_q: str) -> Any:
    from core.compat_fallback_authority_guard import build_authority_hardening_snapshot

    return build_authority_hardening_snapshot()


def _dispatch_chain(_q: str) -> Any:
    from core.canonical_task_dispatch_chain import (
        DispatchPathKind,
        build_dispatch_chain_snapshot,
        classify_dispatch_path,
        is_android_inbound_path,
        is_canonical_path,
    )

    return {
        "snapshot": build_dispatch_chain_snapshot(),
        "paths": {
            kind.value: {
                "canonical": is_canonical_path(kind),
                "android_inbound": is_android_inbound_path(kind),
                "record": classify_dispatch_path(kind),
            }
            for kind in DispatchPathKind
        },
    }


def _memory_bias_scope(_q: str) -> Any:
    from core.cognitive.memory_bias_layer import build_memory_bias_active_scope_diagnostics

    return build_memory_bias_active_scope_diagnostics()


def _session_axis(q: str) -> Any:
    """会话轴快照；``?q=<标识字段名>`` 查这个字段属于哪一类会话。"""
    from core.canonical_session_axis import build_session_axis_snapshot, resolve_session_family_for_identifier

    if q:
        return {"identifier": q, "family": resolve_session_family_for_identifier(q)}
    return build_session_axis_snapshot()


def _capability_bus(_q: str) -> Any:
    from core.capabilities.canonical_dispatcher import get_canonical_dispatcher

    return get_canonical_dispatcher().bus_catalog()


def _observability_events(_q: str) -> Any:
    from core.runtime.runtime_observability_sink import get_observability_sink

    sink = get_observability_sink()
    return {
        "counters": sink.counters(),
        "device_lifecycle": sink.list_device_lifecycle_events()[-50:],
        "dispatch_decisions": sink.list_dispatch_decision_events()[-50:],
        "mesh_session_transitions": sink.list_mesh_session_transition_events()[-50:],
        "recovery_decisions": sink.list_recovery_decision_events()[-50:],
    }


def _device_activation(_q: str) -> Any:
    from core.device_activation_registry import get_registry

    return get_registry().export_json(limit=_MAX_ITEMS)


def _protocol_drift(_q: str) -> Any:
    from core.protocol_drift_registry import drift_entries, drift_summary, has_unrecognized_drift

    return {"has_unrecognized": has_unrecognized_drift(), "summary": drift_summary(), "entries": drift_entries()}


def _presence_projection(_q: str) -> Any:
    from core.presence.presence_projection import get_presence_projection

    return get_presence_projection().last_events(20)


def _formation(_q: str) -> Any:
    from core.device_formation.formation_auto_enrollment import get_formation_auto_enrollment_manager

    return {"active_device_ids": get_formation_auto_enrollment_manager().list_active_device_ids()}


def _mesh(_q: str) -> Any:
    from core.mesh.mesh_auto_enrollment import get_auto_enrollment_service
    from core.mesh.mesh_session_lifecycle import get_lifecycle_coordinator

    lifecycle = get_lifecycle_coordinator()
    return {
        "active_session_ids": lifecycle.list_active_session_ids(),
        "restorable_session_ids": lifecycle.list_restorable_session_ids(),
        "enrolled_device_ids": get_auto_enrollment_service().list_enrolled_device_ids(),
    }


def _capability_tiers(_q: str) -> Any:
    from core.capability_tier import CapabilityTier, list_capabilities_by_tier

    return {tier.value: list_capabilities_by_tier(tier) for tier in CapabilityTier}


def _device_resolver(_q: str) -> Any:
    from core.device_node_resolver import get_resolver

    resolver = get_resolver()
    return {
        "device_types": resolver.list_supported_device_types(),
        "transports": resolver.list_supported_transports(),
    }


def _release_flags(_q: str) -> Any:
    from core.unified.release_gate import get_release_gate

    return get_release_gate().list_flags()


def _hybrid_executions(_q: str) -> Any:
    from core.hybrid_orchestration_continuity import get_continuity_registry

    registry = get_continuity_registry()
    return {"non_terminal": registry.list_non_terminal(), "interrupted": registry.list_interrupted()}


def _session_lanes(_q: str) -> Any:
    from core.session_execution_lane import get_session_execution_lane_manager

    return get_session_execution_lane_manager().list_lanes()


def _continuation_rebind(q: str) -> Any:
    """重绑表的计数与待重绑任务；``?q=<task_id>`` 查这一个任务待重绑 / 已闭环。"""
    from core.continuation_rebind_registry import get_continuation_rebind_registry

    registry = get_continuation_rebind_registry()
    if q:
        return {
            "task_id": q,
            "pending_rebind": registry.is_pending_rebind(q),
            "loop_closed": registry.is_loop_closed(q),
        }
    return {
        "pending": registry.pending_rebind_count(),
        "rebound": registry.rebound_count(),
        "pending_task_ids": registry.list_pending_task_ids(),
    }


def _critical_path(_q: str) -> Any:
    from core.critical_path_harness import snapshot_critical_path

    return snapshot_critical_path()


def _canonical_runtime(_q: str) -> Any:
    from core.capability_network_runtime_policy import snapshot_canonical_runtime

    return snapshot_canonical_runtime()


def _interruptibility(_q: str) -> Any:
    from core.interruptibility_registry import get_interruptibility_registry

    return get_interruptibility_registry().snapshot_all()


def _state_event_bus(_q: str) -> Any:
    """每类状态事件当前有几个订阅方 —— 没人订阅的事件一眼可见。"""
    from core.state_event_bus import StateEventType, get_state_event_bus

    bus = get_state_event_bus()
    counts = {etype.value: bus.subscriber_count(etype) for etype in StateEventType}
    return {
        "wildcard": bus.subscriber_count(None),
        "by_event": counts,
        "unsubscribed": sorted(k for k, v in counts.items() if not v),
    }


def _multi_device_harness(_q: str) -> Any:
    from core.multi_device_runtime_harness import get_multi_device_runtime_harness

    return get_multi_device_runtime_harness().to_canonical_projection()


def _provider_inventory(_q: str) -> Any:
    """运行中的路由器眼里每个厂商的状态与可用性（含各自型号名单）。

    读的是**路由器自己**，不是 ``runtime/config.json`` 的 provider 维度 —— 后者没有运行时读取方
    （``tests/test_config_json_dims_have_no_runtime_reader.py``），拿它当事实会误导。
    """
    from core.llm.route_authority import get_llm_route_authority

    router = get_llm_route_authority().execution_router
    return {"default_model": router.get_default_model(), "providers": router.get_provider_status()}


def _transports(_q: str) -> Any:
    """AIP 各链路的统计（选路依据），外加 BLE 已连设备与 Tailscale 直连登记表。"""
    from core.aip_transport import get_aip_transport

    transport = get_aip_transport()
    ble = transport.get_adapter("ble")
    p2p = transport.get_adapter("tailscale_p2p")
    return {
        "links": transport.transport_stats(),
        "ble_connected": ble.list_connected() if ble is not None else None,
        "tailscale_p2p_devices": p2p.list_registered_devices() if p2p is not None else None,
    }


def _closure_audit(_q: str) -> Any:
    from core.runtime_closure_audit import run_closure_audit

    return run_closure_audit()


def _coordination_roles(_q: str) -> Any:
    from core.multi_device_coordination_authority import CoordinationRole, coordination_role_description

    return {role.value: coordination_role_description(role) for role in CoordinationRole}


def _node_actions(q: str) -> Any:
    """``?q=<node_id>``：这个节点提供哪些动作。"""
    from core.node_capability_loader import get_capability_loader

    if not q:
        return {"error": "需要 ?q=<node_id>"}
    return {"node_id": q, "actions": get_capability_loader().list_node_actions(q)}


def _registry_surface(q: str) -> Any:
    """``?q=<模块路径>``：这个模块在设备 / 节点注册面里属于哪一类。"""
    from core.device_node_domain_governance import classify_registry_surface

    if not q:
        return {"error": "需要 ?q=<模块路径>"}
    return {"module_path": q, "classification": classify_registry_surface(q)}


def _truth_boundary(q: str) -> Any:
    """``?q=<面的路径>``：它在真相 / 投影边界的哪一侧。"""
    from core.truth_projection_boundary import classify_surface_boundary

    if not q:
        return {"error": "需要 ?q=<面的路径>"}
    return {"surface_ref": q, "boundary": classify_surface_boundary(q)}


def _model_openness(_q: str) -> Any:
    """每家供应商的模型按开放权重 / 闭源摊开，判不出的单列（不参与路由决策）。"""
    from core.model_openness import audit_registry
    from core.multi_llm_router import get_llm_router

    registry: Dict[str, List[str]] = {}
    for name, cfg in get_llm_router().providers.items():
        models = list(getattr(cfg, "models", None) or [])
        default = getattr(cfg, "default_model", None) or getattr(cfg, "model", None)
        if default and default not in models:
            models.append(default)
        registry[name] = [str(m) for m in models]
    return audit_registry(registry)


#: 段名 → (读取函数, 一句话说明)。读取函数只读，参数是 ?q= 的值（多数段不用）。
SECTIONS: Dict[str, "tuple[Callable[[str], Any], str]"] = {
    "admission": (_admission, "全局准入仲裁：运行中的请求、配额、最近决定"),
    "authority_hardening": (_authority_hardening, "兼容 / 回退路径的权威加固态势"),
    "budget_sessions": (_budget_sessions, "治理预算里有计费记录的会话"),
    "canonical_runtime": (_canonical_runtime, "能力 + 网络的统一运行时快照"),
    "capability_bus": (_capability_bus, "统一能力总线目录"),
    "capability_tiers": (_capability_tiers, "按主链 / 实验 / 兼容分层的能力"),
    "closure_audit": (_closure_audit, "运行时闭环审计（残余缺口图）"),
    "continuation_rebind": (_continuation_rebind, "重启后待重绑 / 已重绑的任务（?q=task_id 查单个）"),
    "coordination_roles": (_coordination_roles, "多设备协调角色的人话说明"),
    "critical_path": (_critical_path, "关键路径 harness 快照"),
    "device_activation": (_device_activation, "设备激活登记表"),
    "device_resolver": (_device_resolver, "设备→节点解析器支持的设备类型与传输"),
    "dispatch_chain": (_dispatch_chain, "派发链快照与各路径分类"),
    "fast_loop": (_fast_loop, "当前生效的事件循环实现"),
    "formation": (_formation, "设备编组里当前的设备"),
    "hybrid_executions": (_hybrid_executions, "混合执行：未终结 / 被中断的"),
    "interruptibility": (_interruptibility, "各执行的可打断性登记"),
    "memory_bias_scope": (_memory_bias_scope, "记忆偏置的作用域诊断"),
    "mesh": (_mesh, "Mesh 活跃 / 可恢复会话与已编组设备"),
    "model_openness": (_model_openness, "各家模型的开放权重 / 闭源成分"),
    "multi_device_harness": (_multi_device_harness, "多设备一致性 harness 的规范投影"),
    "node_actions": (_node_actions, "某节点提供的动作（?q=node_id）"),
    "observability_events": (_observability_events, "运行时观测事件：设备生命周期、派发决策、Mesh 转移、恢复决策"),
    "pending_envelopes": (_pending_envelopes, "还在等结果的任务信封"),
    "presence_projection": (_presence_projection, "最近的在场投射事件"),
    "protocol_drift": (_protocol_drift, "协议漂移：设备发来的认不出的枚举值"),
    "provider_inventory": (_provider_inventory, "运行中的路由器眼里的厂商状态、可用性与各自型号名单"),
    "registry_surface": (_registry_surface, "模块在注册面的分类（?q=模块路径）"),
    "release_flags": (_release_flags, "发布闸门各开关当前状态"),
    "session_axis": (_session_axis, "会话轴快照（?q=标识字段 查所属会话类）"),
    "session_lanes": (_session_lanes, "会话执行通道"),
    "state_event_bus": (_state_event_bus, "每类状态事件的订阅数（没人订阅的单列）"),
    "transports": (_transports, "AIP 链路统计、BLE 已连设备、Tailscale 直连登记"),
    "truth_boundary": (_truth_boundary, "真相 / 投影边界分类（?q=面的路径）"),
}


def list_sections() -> List[Dict[str, str]]:
    return [{"name": name, "description": desc} for name, (_fn, desc) in sorted(SECTIONS.items())]


def read_section(name: str, q: str = "") -> Optional[Dict[str, Any]]:
    """读一段；段名不存在返回 ``None``。读取失败不抛，错误写进返回值。"""
    entry = SECTIONS.get(name)
    if entry is None:
        return None
    fn, desc = entry
    try:
        return {"name": name, "description": desc, "data": jsonable(fn(q or ""))}
    except Exception as exc:  # noqa: BLE001 — 一段坏了不连累别的段
        logger.debug("internals section %s failed: %s", name, exc)
        return {"name": name, "description": desc, "error": f"{type(exc).__name__}: {exc}"[:300]}


__all__ = ["SECTIONS", "jsonable", "list_sections", "read_section"]
