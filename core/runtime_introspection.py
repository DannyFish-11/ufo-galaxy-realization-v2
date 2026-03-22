#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.runtime_introspection — Structured Runtime Introspection Helpers
======================================================================

PR-14 — Runtime Introspection and Architecture/Execution Status Reporting

Provides structured, developer-oriented helpers that assemble a coherent
snapshot of how a request was **interpreted, planned, routed, executed, and
validated** across the full runtime stack.

Before this module, the relevant information was scattered across:

* ``metadata`` dicts returned by each execution layer
* router / substrate results
* :mod:`core.architecture_diagnostics` reports
* logs and response envelopes

This module consolidates those sources into a single
:class:`RuntimeIntrospectionSnapshot` that captures all the key dimensions of
a runtime execution in one place.

Design goals
------------
* **Additive and non-breaking** — introspection never alters execution logic.
  All collection is opportunistic: missing keys produce ``None`` rather than
  errors.
* **Developer/test-oriented** — this is not a production telemetry pipeline.
  It is an internal helper for debugging, test assertions, and governance
  guardrails.
* **Structured and serialisable** — :class:`RuntimeIntrospectionSnapshot` can
  be converted to a plain dict via :meth:`~RuntimeIntrospectionSnapshot.to_dict`
  so it can be embedded in responses or compared in tests.
* **Reuses existing schemas** — authority, plan, lifecycle, failure-domain, and
  diagnostics data are drawn from the canonical modules established in PR-9
  through PR-13.

Main API
--------
:class:`RuntimeIntrospectionSnapshot`
    The primary data container.  Holds all inspectable runtime dimensions.

:func:`build_introspection_snapshot`
    Assemble a snapshot from one or more layer result dicts.  This is the
    preferred high-level entry point; callers that do not need a snapshot
    continue to work unchanged.

:func:`introspection_snapshot_from_response`
    Convenience wrapper that extracts a snapshot from a single top-level
    response dict (e.g. the result of :meth:`OpenClawd.process`).

:func:`merge_layer_snapshots`
    Merge a runtime-shell result, subject-core result, substrate result, and
    optional orchestration metadata into one consolidated snapshot.

Usage (in tests or developer tooling)::

    from core.runtime_introspection import build_introspection_snapshot

    # Collect layer results (any subset is fine)
    snapshot = build_introspection_snapshot(
        runtime_shell_result=runtime_result,
        subject_core_result=openclawd_result,
        substrate_result=router_result,
    )
    assert snapshot.execution_mode in (None, "agent_runtime", "command_only")
    assert snapshot.authority_chain_valid is not False
    d = snapshot.to_dict()
    assert isinstance(d, dict)
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.RuntimeIntrospection")

__all__ = [
    "RuntimeIntrospectionSnapshot",
    "build_introspection_snapshot",
    "introspection_snapshot_from_response",
    "merge_layer_snapshots",
]


# ---------------------------------------------------------------------------
# RuntimeIntrospectionSnapshot
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class RuntimeIntrospectionSnapshot:
    """Structured snapshot of runtime introspection data for a single request.

    All fields are optional so that partial snapshots (e.g. only the
    subject-core result is available) are still useful.  Missing information
    produces ``None`` rather than errors.

    Attributes
    ----------
    entry_surface:
        The API / transport surface that received the request (e.g.
        ``"chat_adapter"``, ``"websocket"``, ``"cli"``).
    entry_source:
        The originating source string as set by the runtime shell
        (``"local"``, ``"api"``, etc.).
    runtime_shell_authority:
        The ``layer_role`` value from the runtime-shell authority metadata
        (expected: ``"runtime_shell_authority"``).
    subject_decision_authority:
        The ``authority_role`` from the subject core metadata
        (expected: ``"subject_decision_authority"``).
    cognition_layer_role:
        The authority role of the cognition / planning layer
        (expected: ``"cognition_planning_layer"``).
    execution_substrate_role:
        The ``execution_substrate_role`` value from the substrate result
        (expected: ``"execution_substrate"``).
    orchestration_role:
        The orchestration layer role when multi-device orchestration was
        involved (e.g. ``"orchestration_layer"``).
    execution_plan_summary:
        Compact dict summary of the :class:`~core.schemas.execution_plan.ExecutionPlan`
        produced by the subject core, as returned by
        :func:`~core.schemas.execution_plan.plan_summary`.
    lifecycle_state:
        The terminal lifecycle state of the plan
        (e.g. ``"succeeded"``, ``"failed"``).
    lifecycle_trail:
        List of serialised :class:`~core.schemas.execution_lifecycle.LifecycleTransition`
        dicts, when available.
    execution_mode:
        The :class:`~core.schemas.remote_execution.RemoteExecutionMode` value
        selected for the request (``"agent_runtime"``, ``"command_only"``, or
        ``None`` for local execution).
    target_devices:
        List of device IDs that were targeted during execution.
    resolver_decision:
        Summary dict from the remote execution mode resolver, when available.
    delegation_point:
        The delegation boundary label used by
        :class:`~core.openclawd.OpenClawd` (e.g. ``"local"``,
        ``"single_remote"``, ``"multi_device_orchestration"``).
    failure_domain:
        The :class:`~core.failure_domains.FailureDomain` value string when a
        failure occurred (e.g. ``"timeout_failure"``).
    failure_classification:
        Full serialised :class:`~core.failure_domains.FailureClassification`
        dict, when available.
    retry_policy:
        Serialised :class:`~core.failure_domains.RetryPolicy` dict, when
        available.
    fallback_policy:
        Serialised :class:`~core.failure_domains.FallbackPolicy` dict, when
        available.
    diagnostics_report:
        Serialised :class:`~core.architecture_diagnostics.DiagnosticsReport`
        dict, when available.  Generated by
        :func:`~core.architecture_diagnostics.run_architecture_diagnostics`.
    authority_chain_valid:
        ``True`` when the architecture diagnostics report carries no
        ERROR-severity findings; ``False`` when errors were found; ``None``
        when diagnostics were not run or not available.
    trace_id:
        The trace / runtime-session identifier propagated by the runtime
        shell and subject core.
    request_success:
        Whether the overall request was considered successful.
    raw_metadata:
        Merged metadata dict from all layers for lower-level inspection.
    """

    # Entry surface
    entry_surface: Optional[str] = None
    entry_source: Optional[str] = None

    # Authority chain
    runtime_shell_authority: Optional[str] = None
    subject_decision_authority: Optional[str] = None
    cognition_layer_role: Optional[str] = None
    execution_substrate_role: Optional[str] = None
    orchestration_role: Optional[str] = None

    # Execution plan / lifecycle
    execution_plan_summary: Optional[Dict[str, Any]] = None
    lifecycle_state: Optional[str] = None
    lifecycle_trail: Optional[List[Dict[str, Any]]] = None

    # Execution mode / target
    execution_mode: Optional[str] = None
    target_devices: Optional[List[str]] = None
    resolver_decision: Optional[Dict[str, Any]] = None
    delegation_point: Optional[str] = None

    # Failure / fallback
    failure_domain: Optional[str] = None
    failure_classification: Optional[Dict[str, Any]] = None
    retry_policy: Optional[Dict[str, Any]] = None
    fallback_policy: Optional[Dict[str, Any]] = None

    # Diagnostics / validation
    diagnostics_report: Optional[Dict[str, Any]] = None
    authority_chain_valid: Optional[bool] = None

    # Tracing / identity
    trace_id: Optional[str] = None
    request_success: Optional[bool] = None

    # Low-level merged metadata (always a dict, never None)
    raw_metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation of the snapshot.

        All :class:`RuntimeIntrospectionSnapshot` fields are included.
        ``None`` values are preserved so callers can distinguish "not set"
        from "explicitly empty".

        Returns
        -------
        Dict[str, Any]
        """
        return {
            "entry_surface": self.entry_surface,
            "entry_source": self.entry_source,
            "runtime_shell_authority": self.runtime_shell_authority,
            "subject_decision_authority": self.subject_decision_authority,
            "cognition_layer_role": self.cognition_layer_role,
            "execution_substrate_role": self.execution_substrate_role,
            "orchestration_role": self.orchestration_role,
            "execution_plan_summary": self.execution_plan_summary,
            "lifecycle_state": self.lifecycle_state,
            "lifecycle_trail": self.lifecycle_trail,
            "execution_mode": self.execution_mode,
            "target_devices": self.target_devices,
            "resolver_decision": self.resolver_decision,
            "delegation_point": self.delegation_point,
            "failure_domain": self.failure_domain,
            "failure_classification": self.failure_classification,
            "retry_policy": self.retry_policy,
            "fallback_policy": self.fallback_policy,
            "diagnostics_report": self.diagnostics_report,
            "authority_chain_valid": self.authority_chain_valid,
            "trace_id": self.trace_id,
            "request_success": self.request_success,
            "raw_metadata": self.raw_metadata,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"RuntimeIntrospectionSnapshot("
            f"trace_id={self.trace_id!r}, "
            f"execution_mode={self.execution_mode!r}, "
            f"lifecycle_state={self.lifecycle_state!r}, "
            f"request_success={self.request_success!r}, "
            f"authority_chain_valid={self.authority_chain_valid!r})"
        )


# ---------------------------------------------------------------------------
# Internal helpers — extract data from layer result dicts
# ---------------------------------------------------------------------------


def _safe_get(d: Any, *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dicts; return *default* on any miss or type error."""
    if not isinstance(d, dict):
        return default
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


def _extract_runtime_shell(result: Dict[str, Any]) -> Dict[str, Any]:
    """Extract runtime-shell–level introspection fields."""
    authority_meta = _safe_get(result, "authority_metadata", default={}) or {}
    return {
        "entry_surface": _safe_get(result, "entry_surface"),
        "entry_source": _safe_get(result, "entrypoint_source"),
        "runtime_shell_authority": _safe_get(authority_meta, "layer_role"),
        "trace_id": _safe_get(result, "trace_id")
            or _safe_get(result, "runtime_session_id"),
    }


def _extract_subject_core(result: Dict[str, Any]) -> Dict[str, Any]:
    """Extract subject-core–level introspection fields."""
    meta = _safe_get(result, "metadata", default={}) or {}
    execution_plan = _safe_get(result, "execution_plan", default={}) or {}
    execution_plan_summary = _safe_get(result, "execution_plan_summary")
    if execution_plan_summary is None:
        execution_plan_summary = _safe_get(meta, "execution_plan_summary")

    lifecycle_state = _safe_get(result, "execution_lifecycle_state")
    if lifecycle_state is None:
        lifecycle_state = _safe_get(meta, "execution_lifecycle_state")
    if lifecycle_state is None and execution_plan:
        lifecycle_state = _safe_get(execution_plan, "lifecycle_state")

    delegation_point = _safe_get(meta, "delegation_point")
    if delegation_point is None:
        delegation_point = _safe_get(result, "delegation_point")

    remote_mode = _safe_get(meta, "remote_execution_mode")
    if remote_mode is None:
        remote_mode = _safe_get(result, "remote_execution_mode")

    target_device_id = _safe_get(meta, "device_id")
    device_ids: Optional[List[str]] = (
        [target_device_id] if target_device_id else None
    )

    # Kernel / cognition-layer role (may be embedded in metadata)
    cognition_role = _safe_get(meta, "kernel_cognition_role")

    return {
        "subject_decision_authority": _safe_get(meta, "authority_role"),
        "cognition_layer_role": cognition_role,
        "execution_plan_summary": execution_plan_summary,
        "lifecycle_state": lifecycle_state,
        "delegation_point": delegation_point,
        "execution_mode": remote_mode,
        "target_devices": device_ids,
        "trace_id": _safe_get(meta, "trace_id")
            or _safe_get(result, "trace_id"),
        "request_success": result.get("success"),
    }


def _extract_substrate(result: Dict[str, Any]) -> Dict[str, Any]:
    """Extract substrate-level introspection fields."""
    remote_mode = _safe_get(result, "remote_execution_mode")
    lifecycle_state = _safe_get(result, "lifecycle_state")

    # Failure domain fields
    failure_domain = _safe_get(result, "failure_domain")
    failure_cls_dict = _safe_get(result, "failure_classification")
    retry_policy_dict = _safe_get(result, "retry_policy")
    fallback_policy_dict = _safe_get(result, "fallback_policy")

    return {
        "execution_substrate_role": _safe_get(result, "execution_substrate_role"),
        "execution_mode": remote_mode,
        "lifecycle_state": lifecycle_state,
        "failure_domain": failure_domain,
        "failure_classification": failure_cls_dict,
        "retry_policy": retry_policy_dict,
        "fallback_policy": fallback_policy_dict,
    }


def _extract_orchestration(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Extract orchestration-layer introspection fields."""
    orch_role = _safe_get(meta, "orchestration_role")
    if orch_role is None and "orchestration" in str(meta.get("arch_layer_id", "")):
        orch_role = "orchestration_layer"
    target_devices = _safe_get(meta, "device_ids") or _safe_get(meta, "target_devices")
    return {
        "orchestration_role": orch_role,
        "target_devices": list(target_devices) if target_devices else None,
    }


def _run_diagnostics(
    runtime_shell_result: Optional[Dict[str, Any]],
    subject_core_result: Optional[Dict[str, Any]],
    substrate_result: Optional[Dict[str, Any]],
    orchestration_meta: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Run architecture diagnostics if possible; return serialised report dict."""
    try:
        from core.architecture_diagnostics import (
            build_diagnostics_snapshot_from_layers,
            run_architecture_diagnostics,
        )
        layers = [r for r in [
            runtime_shell_result,
            subject_core_result,
            substrate_result,
            orchestration_meta,
        ] if r is not None]
        snap = build_diagnostics_snapshot_from_layers(*layers)
        if not snap:
            return None
        report = run_architecture_diagnostics(snap)
        return report.to_dict()
    except Exception as _exc:
        logger.debug("Introspection: diagnostics skipped: %s", _exc)
        return None


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------


def build_introspection_snapshot(
    *,
    runtime_shell_result: Optional[Dict[str, Any]] = None,
    subject_core_result: Optional[Dict[str, Any]] = None,
    substrate_result: Optional[Dict[str, Any]] = None,
    orchestration_meta: Optional[Dict[str, Any]] = None,
    run_diagnostics: bool = True,
) -> RuntimeIntrospectionSnapshot:
    """Assemble a :class:`RuntimeIntrospectionSnapshot` from layer result dicts.

    Each argument is optional.  Pass whatever layer results are available;
    missing layers are handled gracefully.  The snapshot is assembled by
    priority: subject-core data takes precedence over substrate data for
    shared fields (e.g. ``execution_mode``, ``lifecycle_state``).

    Parameters
    ----------
    runtime_shell_result:
        Result dict from :meth:`~core.desktop_presence_runtime.DesktopPresenceRuntime.handle_request`
        (carries ``authority_metadata``, ``arch_layer_id="runtime_shell"``).
    subject_core_result:
        Result dict from :meth:`~core.openclawd.OpenClawd.process`
        (carries ``metadata``, ``execution_plan``, ``arch_layer_id="subject_core"``).
    substrate_result:
        Result dict from :meth:`~core.command_router.CommandRouter.route_envelope`
        (carries ``execution_substrate_role``, ``arch_layer_id="execution_substrate"``).
    orchestration_meta:
        Optional metadata dict from an orchestration layer
        (:class:`~core.swarm_coordinator.SwarmCoordinator` or similar).
    run_diagnostics:
        When ``True`` (the default), automatically run architecture
        diagnostics and populate ``diagnostics_report`` and
        ``authority_chain_valid``.  Set to ``False`` to skip for performance.

    Returns
    -------
    RuntimeIntrospectionSnapshot
    """
    snap = RuntimeIntrospectionSnapshot()

    # ── Merge raw_metadata from all available layers ─────────────────────────
    merged_meta: Dict[str, Any] = {}
    for layer in [runtime_shell_result, subject_core_result, substrate_result, orchestration_meta]:
        if isinstance(layer, dict):
            merged_meta.update(layer)
    snap.raw_metadata = merged_meta

    # ── Runtime shell ─────────────────────────────────────────────────────────
    if runtime_shell_result:
        shell_data = _extract_runtime_shell(runtime_shell_result)
        snap.entry_surface = shell_data.get("entry_surface")
        snap.entry_source = shell_data.get("entry_source")
        snap.runtime_shell_authority = shell_data.get("runtime_shell_authority")
        if snap.trace_id is None:
            snap.trace_id = shell_data.get("trace_id")

    # ── Subject core ──────────────────────────────────────────────────────────
    if subject_core_result:
        core_data = _extract_subject_core(subject_core_result)
        snap.subject_decision_authority = core_data.get("subject_decision_authority")
        snap.cognition_layer_role = core_data.get("cognition_layer_role")
        snap.execution_plan_summary = core_data.get("execution_plan_summary")
        snap.lifecycle_state = core_data.get("lifecycle_state")
        snap.delegation_point = core_data.get("delegation_point")
        snap.execution_mode = core_data.get("execution_mode")
        if core_data.get("target_devices"):
            snap.target_devices = core_data["target_devices"]
        if snap.trace_id is None:
            snap.trace_id = core_data.get("trace_id")
        if snap.request_success is None:
            snap.request_success = core_data.get("request_success")

    # ── Substrate ─────────────────────────────────────────────────────────────
    if substrate_result:
        sub_data = _extract_substrate(substrate_result)
        snap.execution_substrate_role = sub_data.get("execution_substrate_role")
        # Only fill in from substrate if not already set by subject core
        if snap.execution_mode is None:
            snap.execution_mode = sub_data.get("execution_mode")
        if snap.lifecycle_state is None:
            snap.lifecycle_state = sub_data.get("lifecycle_state")
        snap.failure_domain = sub_data.get("failure_domain")
        snap.failure_classification = sub_data.get("failure_classification")
        snap.retry_policy = sub_data.get("retry_policy")
        snap.fallback_policy = sub_data.get("fallback_policy")
        if snap.request_success is None:
            snap.request_success = substrate_result.get("success")

    # ── Orchestration ─────────────────────────────────────────────────────────
    if orchestration_meta:
        orch_data = _extract_orchestration(orchestration_meta)
        snap.orchestration_role = orch_data.get("orchestration_role")
        if orch_data.get("target_devices") and not snap.target_devices:
            snap.target_devices = orch_data["target_devices"]

    # ── Resolver decision (if embedded in metadata) ───────────────────────────
    resolver_hint = _safe_get(merged_meta, "resolver_decision")
    if resolver_hint:
        snap.resolver_decision = resolver_hint

    # ── Diagnostics / validation ──────────────────────────────────────────────
    if run_diagnostics:
        diag_dict = _run_diagnostics(
            runtime_shell_result, subject_core_result, substrate_result, orchestration_meta
        )
        if diag_dict:
            snap.diagnostics_report = diag_dict
            snap.authority_chain_valid = diag_dict.get("overall_valid")

    return snap


def introspection_snapshot_from_response(
    response: Dict[str, Any],
    *,
    run_diagnostics: bool = True,
) -> RuntimeIntrospectionSnapshot:
    """Build a snapshot from a single top-level response dict.

    This is a convenience wrapper for callers that have a single composite
    response dict rather than individual layer results.  It uses the
    ``"arch_layer_id"`` key (if present) to route the dict to the correct
    layer extractor; otherwise the dict is treated as the subject-core result.

    Parameters
    ----------
    response:
        Any response dict that may carry ``arch_layer_id``, ``metadata``,
        ``authority_metadata``, ``execution_plan``, etc.
    run_diagnostics:
        Whether to run architecture diagnostics.

    Returns
    -------
    RuntimeIntrospectionSnapshot
    """
    if not isinstance(response, dict):
        return RuntimeIntrospectionSnapshot()

    layer_id = response.get("arch_layer_id", "subject_core")
    kwargs: Dict[str, Any] = {"run_diagnostics": run_diagnostics}
    if layer_id == "runtime_shell":
        kwargs["runtime_shell_result"] = response
    elif layer_id == "execution_substrate":
        kwargs["substrate_result"] = response
    elif layer_id == "orchestration_layer":
        kwargs["orchestration_meta"] = response
    else:
        kwargs["subject_core_result"] = response

    return build_introspection_snapshot(**kwargs)


def merge_layer_snapshots(
    *snapshots: RuntimeIntrospectionSnapshot,
) -> RuntimeIntrospectionSnapshot:
    """Merge multiple partial :class:`RuntimeIntrospectionSnapshot` objects.

    Fields are filled in priority order: earlier snapshots take precedence
    for non-``None`` values.  ``raw_metadata`` dicts are merged (later items
    do not overwrite earlier keys).

    Parameters
    ----------
    *snapshots:
        One or more partial snapshots to merge.

    Returns
    -------
    RuntimeIntrospectionSnapshot
        A new merged snapshot.
    """
    merged = RuntimeIntrospectionSnapshot()
    merged_raw: Dict[str, Any] = {}

    for snap in reversed(list(snapshots)):
        if not isinstance(snap, RuntimeIntrospectionSnapshot):
            continue
        # Raw metadata: later (lower-priority) items fill gaps
        merged_raw.update(snap.raw_metadata or {})

        d = snap.to_dict()
        for field_name, value in d.items():
            if field_name == "raw_metadata":
                continue
            if value is not None:
                setattr(merged, field_name, value)

    merged.raw_metadata = merged_raw
    return merged
