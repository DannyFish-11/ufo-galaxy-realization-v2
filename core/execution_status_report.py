#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.execution_status_report — Execution Status Reporting
==========================================================

PR-14 — Runtime Introspection and Architecture/Execution Status Reporting

Provides a structured, developer-oriented summary of **how a request was
executed** — covering the execution plan, lifecycle progression, remote
execution mode, target devices, failure / fallback context, and resolver
decisions.

This module complements :mod:`core.architecture_status_report` (which
focuses on *architecture invariants*) by focusing on *execution decisions
and outcomes*.

Design goals
------------
* **Additive and non-breaking** — never alters execution logic.
* **Developer/test-oriented** — structured, serialisable, easy to assert on.
* **Consolidates PR-11 through PR-13 data** — draws on canonical plan,
  lifecycle, and failure-domain schemas.

Main API
--------
:class:`ExecutionStatusReport`
    The primary data container.

:func:`build_execution_status_report`
    Build from layer result dicts or a
    :class:`~core.runtime_introspection.RuntimeIntrospectionSnapshot`.

:func:`execution_status_from_snapshot`
    Convenience wrapper: build directly from a
    :class:`~core.runtime_introspection.RuntimeIntrospectionSnapshot`.

Usage::

    from core.execution_status_report import build_execution_status_report

    report = build_execution_status_report(
        subject_core_result=openclawd_result,
        substrate_result=router_result,
    )
    print(report.lifecycle_state)   # e.g. "succeeded"
    print(report.execution_mode)    # e.g. "command_only" or None
    print(report.failure_domain)    # e.g. "timeout_failure" or None
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ExecutionStatusReport")

__all__ = [
    "ExecutionStatusReport",
    "build_execution_status_report",
    "execution_status_from_snapshot",
]


# ---------------------------------------------------------------------------
# ExecutionStatusReport
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ExecutionStatusReport:
    """Structured summary of execution decisions and outcomes for a request.

    Attributes
    ----------
    execution_path:
        High-level execution path label (e.g. ``"local"``, ``"remote"``,
        ``"cross_device"``, ``"multi_device"``).
    delegation_point:
        The OpenClawd delegation boundary used (e.g. ``"local"``,
        ``"single_remote"``, ``"multi_device_orchestration"``).
    execution_mode:
        The :class:`~core.schemas.remote_execution.RemoteExecutionMode` value
        (``"agent_runtime"``, ``"command_only"``, or ``None`` for local).
    target_devices:
        List of device IDs targeted during execution.
    resolver_decision:
        Resolver decision summary dict, if available.
    execution_plan_summary:
        Compact dict summary of the canonical execution plan.
    plan_step_types:
        List of step-type strings from the plan
        (e.g. ``["local_manifestation"]``).
    lifecycle_state:
        Terminal lifecycle state (e.g. ``"succeeded"``, ``"failed"``).
    lifecycle_trail:
        Ordered list of lifecycle-transition dicts.
    is_terminal:
        ``True`` when the lifecycle state is a recognised terminal state.
    request_success:
        Whether the overall request was considered successful.
    failure_domain:
        The :class:`~core.failure_domains.FailureDomain` value string when a
        failure occurred.
    failure_classification:
        Full serialised failure-classification dict.
    retry_policy:
        Serialised retry-policy dict.
    fallback_policy:
        Serialised fallback-policy dict.
    failure_summary:
        Human-readable one-line summary of the failure context, when
        applicable.
    """

    # Execution routing
    execution_path: Optional[str] = None
    delegation_point: Optional[str] = None
    execution_mode: Optional[str] = None
    target_devices: Optional[List[str]] = None
    resolver_decision: Optional[Dict[str, Any]] = None

    # Plan
    execution_plan_summary: Optional[Dict[str, Any]] = None
    plan_step_types: Optional[List[str]] = None

    # Lifecycle
    lifecycle_state: Optional[str] = None
    lifecycle_trail: Optional[List[Dict[str, Any]]] = None
    is_terminal: Optional[bool] = None

    # Outcome
    request_success: Optional[bool] = None

    # Failure / fallback
    failure_domain: Optional[str] = None
    failure_classification: Optional[Dict[str, Any]] = None
    retry_policy: Optional[Dict[str, Any]] = None
    fallback_policy: Optional[Dict[str, Any]] = None
    failure_summary: Optional[str] = None

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation.

        Returns
        -------
        Dict[str, Any]
        """
        return {
            "execution_path": self.execution_path,
            "delegation_point": self.delegation_point,
            "execution_mode": self.execution_mode,
            "target_devices": self.target_devices,
            "resolver_decision": self.resolver_decision,
            "execution_plan_summary": self.execution_plan_summary,
            "plan_step_types": self.plan_step_types,
            "lifecycle_state": self.lifecycle_state,
            "lifecycle_trail": self.lifecycle_trail,
            "is_terminal": self.is_terminal,
            "request_success": self.request_success,
            "failure_domain": self.failure_domain,
            "failure_classification": self.failure_classification,
            "retry_policy": self.retry_policy,
            "fallback_policy": self.fallback_policy,
            "failure_summary": self.failure_summary,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"ExecutionStatusReport("
            f"execution_path={self.execution_path!r}, "
            f"execution_mode={self.execution_mode!r}, "
            f"lifecycle_state={self.lifecycle_state!r}, "
            f"request_success={self.request_success!r})"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe(d: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(d, dict):
        return default
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


def _check_is_terminal(state: Optional[str]) -> Optional[bool]:
    """Check whether *state* is a recognised terminal lifecycle state."""
    if state is None:
        return None
    _TERMINAL = {"succeeded", "failed", "timed_out", "cancelled", "degraded",
                 "partially_succeeded"}
    return state.lower() in _TERMINAL


def _build_failure_summary(
    failure_domain: Optional[str],
    failure_classification: Optional[Dict[str, Any]],
    retry_policy: Optional[Dict[str, Any]],
    fallback_policy: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Build a one-line human-readable failure summary."""
    if not failure_domain:
        return None
    parts = [f"domain={failure_domain}"]
    if failure_classification:
        if failure_classification.get("downgrade_hint"):
            parts.append(f"hint={failure_classification['downgrade_hint']}")
        retryable = failure_classification.get("is_retryable")
        if retryable is not None:
            parts.append(f"retryable={retryable}")
    if retry_policy:
        max_attempts = retry_policy.get("max_attempts")
        if max_attempts is not None:
            parts.append(f"max_attempts={max_attempts}")
    if fallback_policy:
        allow_local = fallback_policy.get("allow_local_fallback")
        if allow_local:
            parts.append("allow_local_fallback=True")
    return ", ".join(parts)


def _extract_plan_step_types(plan_summary: Optional[Dict[str, Any]]) -> Optional[List[str]]:
    """Extract step type list from a plan summary dict."""
    if not plan_summary:
        return None
    step_types = plan_summary.get("step_types")
    if isinstance(step_types, list):
        return [str(s) for s in step_types]
    primary = plan_summary.get("primary_step_type")
    if primary:
        return [str(primary)]
    return None


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------


def build_execution_status_report(
    *,
    subject_core_result: Optional[Dict[str, Any]] = None,
    substrate_result: Optional[Dict[str, Any]] = None,
    orchestration_meta: Optional[Dict[str, Any]] = None,
) -> "ExecutionStatusReport":
    """Build an :class:`ExecutionStatusReport` from layer result dicts.

    Each argument is optional.  Pass whatever results are available;
    missing data produces ``None`` fields rather than errors.

    Parameters
    ----------
    subject_core_result:
        Result dict from :meth:`~core.openclawd.OpenClawd.process`.
    substrate_result:
        Result dict from :meth:`~core.command_router.CommandRouter.route_envelope`.
    orchestration_meta:
        Optional metadata dict from an orchestration layer.

    Returns
    -------
    ExecutionStatusReport
    """
    report = ExecutionStatusReport()

    # ── Subject core data ─────────────────────────────────────────────────────
    if subject_core_result:
        meta = _safe(subject_core_result, "metadata") or {}
        plan_summary = _safe(subject_core_result, "execution_plan_summary")
        if plan_summary is None:
            plan_summary = _safe(meta, "execution_plan_summary")
        lifecycle_state = _safe(subject_core_result, "execution_lifecycle_state")
        if lifecycle_state is None:
            lifecycle_state = _safe(meta, "execution_lifecycle_state")
        exec_path = _safe(subject_core_result, "execution_path")
        if exec_path is None:
            exec_path = _safe(meta, "execution_path")
        delegation_point = _safe(meta, "delegation_point")
        remote_mode = _safe(meta, "remote_execution_mode")
        if remote_mode is None:
            remote_mode = _safe(subject_core_result, "remote_execution_mode")
        device_id = _safe(meta, "device_id")

        report.execution_path = exec_path
        report.delegation_point = delegation_point
        if remote_mode:
            report.execution_mode = remote_mode
        if device_id:
            report.target_devices = [device_id]
        report.execution_plan_summary = plan_summary
        report.plan_step_types = _extract_plan_step_types(plan_summary)
        if lifecycle_state:
            report.lifecycle_state = lifecycle_state
        report.request_success = subject_core_result.get("success")

        # Lifecycle trail from plan (if available)
        ep_dict = _safe(subject_core_result, "execution_plan") or {}
        trail = _safe(ep_dict, "lifecycle_trail")
        if isinstance(trail, list):
            report.lifecycle_trail = trail

    # ── Substrate data ────────────────────────────────────────────────────────
    if substrate_result:
        if report.execution_mode is None:
            remote_mode_sub = _safe(substrate_result, "remote_execution_mode")
            if remote_mode_sub:
                report.execution_mode = remote_mode_sub
        if report.lifecycle_state is None:
            lc_sub = _safe(substrate_result, "lifecycle_state")
            if lc_sub:
                report.lifecycle_state = lc_sub
        # Failure / fallback
        report.failure_domain = _safe(substrate_result, "failure_domain")
        report.failure_classification = _safe(substrate_result, "failure_classification")
        report.retry_policy = _safe(substrate_result, "retry_policy")
        report.fallback_policy = _safe(substrate_result, "fallback_policy")
        if report.request_success is None:
            report.request_success = substrate_result.get("success")

    # ── Orchestration data ────────────────────────────────────────────────────
    if orchestration_meta:
        target_devices = (
            _safe(orchestration_meta, "device_ids")
            or _safe(orchestration_meta, "target_devices")
        )
        if target_devices and not report.target_devices:
            report.target_devices = list(target_devices)
        resolver_decision = _safe(orchestration_meta, "resolver_decision")
        if resolver_decision:
            report.resolver_decision = resolver_decision

    # ── Derived fields ────────────────────────────────────────────────────────
    report.is_terminal = _check_is_terminal(report.lifecycle_state)
    report.failure_summary = _build_failure_summary(
        report.failure_domain,
        report.failure_classification,
        report.retry_policy,
        report.fallback_policy,
    )

    return report


def execution_status_from_snapshot(
    snapshot: Any,
) -> "ExecutionStatusReport":
    """Build an :class:`ExecutionStatusReport` from a
    :class:`~core.runtime_introspection.RuntimeIntrospectionSnapshot`.

    Parameters
    ----------
    snapshot:
        A :class:`~core.runtime_introspection.RuntimeIntrospectionSnapshot`
        instance.

    Returns
    -------
    ExecutionStatusReport
    """
    report = ExecutionStatusReport()

    report.delegation_point = getattr(snapshot, "delegation_point", None)
    report.execution_mode = getattr(snapshot, "execution_mode", None)
    report.target_devices = getattr(snapshot, "target_devices", None)
    report.resolver_decision = getattr(snapshot, "resolver_decision", None)
    report.execution_plan_summary = getattr(snapshot, "execution_plan_summary", None)
    report.plan_step_types = _extract_plan_step_types(report.execution_plan_summary)
    report.lifecycle_state = getattr(snapshot, "lifecycle_state", None)
    report.lifecycle_trail = getattr(snapshot, "lifecycle_trail", None)
    report.is_terminal = _check_is_terminal(report.lifecycle_state)
    report.request_success = getattr(snapshot, "request_success", None)
    report.failure_domain = getattr(snapshot, "failure_domain", None)
    report.failure_classification = getattr(snapshot, "failure_classification", None)
    report.retry_policy = getattr(snapshot, "retry_policy", None)
    report.fallback_policy = getattr(snapshot, "fallback_policy", None)
    report.failure_summary = _build_failure_summary(
        report.failure_domain,
        report.failure_classification,
        report.retry_policy,
        report.fallback_policy,
    )
    # Execution path from plan summary or snapshot raw_metadata
    if report.execution_plan_summary:
        report.execution_path = report.execution_plan_summary.get("execution_path")
    if report.execution_path is None:
        raw = getattr(snapshot, "raw_metadata", {}) or {}
        report.execution_path = raw.get("execution_path")

    return report
