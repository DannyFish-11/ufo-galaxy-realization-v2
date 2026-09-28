"""core/dispatch_telemetry.py — 派发脊柱上的计数、审计与执行事件的唯一落点。

``CommandRouter.route_envelope`` 在四个时刻各调一次这里：

==========================  =====================================================
``on_dispatch_planned``     目标已定、即将执行
``on_route_rejected``       能力不匹配且没有可替代目标，拒绝派发
``on_fallback``             能力不匹配，改派到可替代目标
``on_dispatch_finished``    拿到结果（成功或失败）
==========================  =====================================================

它把原先各自写好、却没有生产调用方的采集点接到真实发生的位置上：

- 运行 SLO（:mod:`core.operational_slo_metrics`）：派发尝试 / 成功 / 失败、路由拒绝、
  回退触发。``/metrics``、监控端点、投影一直在读这些计数，而它们此前恒为 0。
- 审计事件（:mod:`core.audit_event_semantics`）：选路决定、失败归类、策略决定。
- 执行目标策略引擎：失败时求一次「怎么处理」、目标就绪度降级时求一次「降级怎么办」。
  与 PR-5A 的定位一致，它们是**建议**，不改变派发行为；建议写进审计与结果，给人和上层看。
- 选路解释：把当时生效的执行策略档位记进 :class:`LiveRoutingDecisionBuilder`。
- 关键路径（:mod:`core.critical_path_harness`）：执行派发记录。
- 统一执行事件（:mod:`core.execution_observability.event_log`）：信封 → 执行事件。

每个钩子都吞掉自己的异常：记账绝不拖垮派发。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SOURCE = "command_router.route_envelope"


def _targets(envelope: Any) -> List[str]:
    return [str(t) for t in (getattr(envelope, "targets", None) or []) if t]


def _slo():
    from core.operational_slo_metrics import get_operational_slo_metrics

    return get_operational_slo_metrics()


def on_dispatch_planned(envelope: Any, explanation: str = "", live_builder: Optional[Any] = None) -> None:
    task_id = str(getattr(envelope, "task_id", "") or "")
    trace_id = str(getattr(envelope, "trace_id", "") or "")
    targets = _targets(envelope)
    meta = getattr(envelope, "metadata", None) or {}
    try:
        _slo().record_dispatch_attempt(task_id=task_id, target=targets[0] if targets else "")
    except Exception as exc:  # noqa: BLE001
        logger.debug("dispatch_telemetry: SLO attempt skipped: %s", exc)
    try:
        from core.audit_event_semantics import audit_route_decision

        audit_route_decision(
            task_id,
            trace_id=trace_id,
            source=_SOURCE,
            selected_targets=targets,
            effective_path="command_router",
            route_explanation=explanation,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("dispatch_telemetry: route audit skipped: %s", exc)
    try:
        from core.critical_path_harness import record_execution_dispatch

        record_execution_dispatch(
            task_id=task_id,
            trace_id=trace_id,
            executor=targets[0] if targets else "local",
            dispatch_method=str(getattr(envelope, "executor_target_type", "") or "command_router"),
            source=_SOURCE,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("dispatch_telemetry: critical path skipped: %s", exc)
    try:
        from core.execution_observability.event_log import record_execution_event
        from core.execution_observability.normalizers import normalize_task_envelope

        record_execution_event(
            normalize_task_envelope(envelope, message=f"dispatch {getattr(envelope, 'tool_name', '')!r}"),
            origin="command_router",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("dispatch_telemetry: execution event skipped: %s", exc)
    if live_builder is not None:
        try:
            from core.execution_policy.policy_resolver import resolve_policy

            policy = resolve_policy(phase=meta.get("tri_state_phase"), domain=meta.get("runtime_domain"))
            live_builder.record_policy_band(policy.policy_band.value)
        except Exception as exc:  # noqa: BLE001
            logger.debug("dispatch_telemetry: policy band skipped: %s", exc)
    _consider_degraded_readiness(task_id, trace_id, targets)


def _consider_degraded_readiness(task_id: str, trace_id: str, targets: List[str]) -> None:
    """首选目标就绪度降级时，求一次降级策略并记审计。"""
    if not targets:
        return
    try:
        from core.device_readiness import get_device_readiness

        readiness = _readiness_label(get_device_readiness(targets[0]))
    except Exception:  # noqa: BLE001
        return
    if readiness in ("ready", "not_a_device"):
        return
    try:
        from core.audit_event_semantics import audit_policy_decision
        from core.runtime.execution_target_policy_engine import apply_degraded_readiness_policy

        decision = apply_degraded_readiness_policy(
            readiness=readiness,
            device_id=targets[0],
            alternative_available=len(targets) > 1,
            task_id=task_id,
            trace_id=trace_id,
        )
        audit_policy_decision(
            task_id,
            trace_id=trace_id,
            source=_SOURCE,
            verdict=str(getattr(decision.policy_kind, "value", decision.policy_kind)),
            degradation_reason=f"target {targets[0]} readiness={readiness}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("dispatch_telemetry: degraded readiness policy skipped: %s", exc)


def _readiness_label(summary: Any) -> str:
    """把 :class:`DeviceReadinessSummary` 的几个布尔位折成一个词。

    没注册的目标（``local`` 之类的伪目标）不是设备，不谈就绪度。
    """
    if not getattr(summary, "registered", False):
        return "not_a_device"
    for flag, label in (("online", "offline"), ("connected", "disconnected"), ("routable", "unroutable")):
        if not getattr(summary, flag, False):
            return label
    return "ready"


def on_route_rejected(envelope: Any, reason: str) -> None:
    try:
        _slo().record_route_rejection(task_id=str(getattr(envelope, "task_id", "") or ""), reason=reason)
    except Exception as exc:  # noqa: BLE001
        logger.debug("dispatch_telemetry: rejection skipped: %s", exc)


def on_fallback(envelope: Any, kind: str, reason: str = "") -> None:
    task_id = str(getattr(envelope, "task_id", "") or "")
    try:
        _slo().record_fallback_triggered(task_id=task_id, fallback_kind=kind)
    except Exception as exc:  # noqa: BLE001
        logger.debug("dispatch_telemetry: fallback skipped: %s", exc)
    try:
        from core.audit_event_semantics import audit_fallback_triggered

        audit_fallback_triggered(
            task_id, trace_id=str(getattr(envelope, "trace_id", "") or ""), source=_SOURCE, reason=reason or kind
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("dispatch_telemetry: fallback audit skipped: %s", exc)


def on_dispatch_finished(envelope: Any, result: Dict[str, Any]) -> None:
    task_id = str(getattr(envelope, "task_id", "") or "")
    trace_id = str(getattr(envelope, "trace_id", "") or "")
    targets = _targets(envelope)
    if result.get("success"):
        try:
            _slo().record_dispatch_success(task_id=task_id, target=targets[0] if targets else "")
        except Exception as exc:  # noqa: BLE001
            logger.debug("dispatch_telemetry: SLO success skipped: %s", exc)
        return
    error_code = str(result.get("error_code") or "")
    failure_domain = str(result.get("failure_domain") or "")
    try:
        _slo().record_dispatch_failure(task_id=task_id, reason=error_code or failure_domain or "unknown")
    except Exception as exc:  # noqa: BLE001
        logger.debug("dispatch_telemetry: SLO failure skipped: %s", exc)
    try:
        from core.audit_event_semantics import audit_failure_domain

        audit_failure_domain(
            task_id,
            trace_id=trace_id,
            source=_SOURCE,
            failure_domain=failure_domain,
            error_code=error_code,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("dispatch_telemetry: failure-domain audit skipped: %s", exc)
    try:
        from core.audit_event_semantics import audit_policy_decision
        from core.runtime.execution_target_policy_engine import apply_failure_handling_policy

        decision = apply_failure_handling_policy(
            failure_kind=failure_domain or error_code or "unknown",
            prior_device_id=targets[0] if targets else None,
            task_id=task_id,
            trace_id=trace_id,
            errors=[str(result.get("error_message") or "")],
        )
        verdict = str(getattr(decision.policy_kind, "value", decision.policy_kind))
        audit_policy_decision(task_id, trace_id=trace_id, source=_SOURCE, verdict=verdict)
        result.setdefault("failure_handling_advice", decision.to_dict() if hasattr(decision, "to_dict") else verdict)
    except Exception as exc:  # noqa: BLE001
        logger.debug("dispatch_telemetry: failure-handling policy skipped: %s", exc)


__all__ = ["on_dispatch_finished", "on_dispatch_planned", "on_fallback", "on_route_rejected"]
