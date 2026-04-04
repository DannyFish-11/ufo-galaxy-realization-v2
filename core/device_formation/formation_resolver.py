#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.device_formation.formation_resolver
==========================================

PR-17 (V4) — Device Formation & Multi-Device Group Model

Provides the **resolve_formation()** helper, which derives a
:class:`~.formation_group.DeviceFormationGroup` and
:class:`~.formation_policy.FormationPolicy` from available runtime signals.

All inputs are optional — the resolver degrades gracefully when only partial
information is present, always returning a valid result.

Signal consumption order
------------------------
The resolver reads (but does not modify) the following upstream layers:

1. **Cross-device routing summary** (PR-13, ``core.cross_device_policy``) —
   used to seed source/primary device IDs and role assignments.
2. **Execution policy** (PR-11, ``core.execution_policy``) —
   used to derive ``multi_device_required`` and ``merge_confirmation_required``
   from policy band and gate flags.
3. **Target device lists** — raw lists of device IDs may be supplied directly.
4. **Merge/recovery summary** (PR-14, ``core.distributed_execution``) —
   when available, used to seed merge-owner derivation.
5. **Task/trace metadata** — ``task_id`` and ``trace_id`` from task envelopes
   or context.
6. **Runtime domain** — governs whether a cross-device formation is warranted.

Non-goals
---------
- Does not write to UDM, device router, TaskGraph, or any orchestration
  module.
- Does not implement live membership rebalancing or health-driven reshaping
  (planned for future work).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .formation_group import DeviceFormationGroup, EMPTY_FORMATION_GROUP
from .formation_policy import BarrierPosture, FormationPolicy, DEFAULT_LOCAL_FORMATION_POLICY
from .formation_role import FormationMember, FormationRole

__all__ = [
    "resolve_formation",
]

logger = logging.getLogger("Galaxy.DeviceFormation.Resolver")


# ---------------------------------------------------------------------------
# Public resolver
# ---------------------------------------------------------------------------


def resolve_formation(
    *,
    runtime_domain: Optional[str] = None,
    source_device_id: Optional[str] = None,
    source_runtime_posture: str = "control_only",
    primary_device_id: Optional[str] = None,
    target_device_ids: Optional[List[str]] = None,
    fallback_device_ids: Optional[List[str]] = None,
    support_device_ids: Optional[List[str]] = None,
    observer_device_ids: Optional[List[str]] = None,
    relay_device_ids: Optional[List[str]] = None,
    merge_owner_device_id: Optional[str] = None,
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    cross_device_routing_summary: Optional[Dict[str, Any]] = None,
    execution_policy: Optional[Any] = None,
    merge_summary: Optional[Any] = None,
    formation_reason: Optional[str] = None,
) -> tuple[DeviceFormationGroup, FormationPolicy]:
    """Derive a :class:`~.formation_group.DeviceFormationGroup` and
    :class:`~.formation_policy.FormationPolicy` from available signals.

    All parameters are keyword-only and optional.  The function always returns
    a valid ``(group, policy)`` pair — it never raises; any error is caught and
    logged, and the safe idle defaults are returned.

    Parameters
    ----------
    runtime_domain:
        Current :class:`~core.continuum.types.RuntimeDomain` string value.
        A value of ``"cross_device"`` enables cross-device formation assembly.
    source_device_id:
        Device ID of the device that originated the request.
    primary_device_id:
        Device ID of the intended PRIMARY_EXECUTION device.
    target_device_ids:
        Full list of target device IDs.  Devices not present in more specific
        lists (support, observer, etc.) are assigned the FALLBACK role.
    fallback_device_ids:
        Device IDs to explicitly assign the FALLBACK role.
    support_device_ids:
        Device IDs to assign the SUPPORT role.
    observer_device_ids:
        Device IDs to assign the OBSERVER role.
    relay_device_ids:
        Device IDs to assign the RELAY role.
    merge_owner_device_id:
        Device ID of the explicit merge owner.  Falls back to primary when
        absent.
    task_id:
        Task identifier for traceability.
    trace_id:
        Distributed-trace identifier.
    cross_device_routing_summary:
        Optional dict output of
        :func:`~core.cross_device_policy.build_assignment_summary`.  When
        present, used to seed device IDs and role assignments that were not
        supplied directly.
    execution_policy:
        Optional :class:`~core.execution_policy.ExecutionPolicy` or its
        ``to_dict()`` serialisation.  Used to derive policy gates.
    merge_summary:
        Optional :class:`~core.distributed_execution.MergeSummary` or its
        ``to_dict()`` serialisation.  Used to seed merge-owner derivation.
    formation_reason:
        Optional human-readable explanation for why this formation was
        assembled.  Defaults to an inferred reason.

    Returns
    -------
    tuple[DeviceFormationGroup, FormationPolicy]
        A ``(group, policy)`` pair.  Both are immutable and serialisable.
    """
    try:
        return _resolve_formation_inner(
            runtime_domain=runtime_domain,
            source_device_id=source_device_id,
            source_runtime_posture=source_runtime_posture,
            primary_device_id=primary_device_id,
            target_device_ids=target_device_ids or [],
            fallback_device_ids=fallback_device_ids or [],
            support_device_ids=support_device_ids or [],
            observer_device_ids=observer_device_ids or [],
            relay_device_ids=relay_device_ids or [],
            merge_owner_device_id=merge_owner_device_id,
            task_id=task_id,
            trace_id=trace_id,
            cross_device_routing_summary=cross_device_routing_summary or {},
            execution_policy=execution_policy,
            merge_summary=merge_summary,
            formation_reason=formation_reason,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("Formation resolution failed, returning idle defaults: %s", exc)
        return EMPTY_FORMATION_GROUP, DEFAULT_LOCAL_FORMATION_POLICY


# ---------------------------------------------------------------------------
# Internal implementation
# ---------------------------------------------------------------------------


def _resolve_formation_inner(
    *,
    runtime_domain: Optional[str],
    source_device_id: Optional[str],
    source_runtime_posture: str,
    primary_device_id: Optional[str],
    target_device_ids: List[str],
    fallback_device_ids: List[str],
    support_device_ids: List[str],
    observer_device_ids: List[str],
    relay_device_ids: List[str],
    merge_owner_device_id: Optional[str],
    task_id: Optional[str],
    trace_id: Optional[str],
    cross_device_routing_summary: Dict[str, Any],
    execution_policy: Optional[Any],
    merge_summary: Optional[Any],
    formation_reason: Optional[str],
) -> tuple[DeviceFormationGroup, FormationPolicy]:
    """Internal implementation — assumes inputs are already validated."""

    # ------------------------------------------------------------------
    # Step 1: Seed from cross-device routing summary (PR-13) when direct
    #         inputs are absent.
    # ------------------------------------------------------------------
    cdr = cross_device_routing_summary

    if not source_device_id:
        source_device_id = cdr.get("source_device_id")

    if not primary_device_id:
        primary_device_id = cdr.get("primary_execution_device_id")

    if not fallback_device_ids:
        fallback_device_ids = list(cdr.get("fallback_device_ids", []))

    if not support_device_ids:
        support_device_ids = list(cdr.get("support_device_ids", []))

    if not observer_device_ids:
        observer_device_ids = list(cdr.get("observer_device_ids", []))

    if not relay_device_ids:
        relay_device_ids = list(cdr.get("relay_device_ids", []))

    # Posture from routing summary as a seeding hint
    cdr_posture = cdr.get("posture", "")

    # ------------------------------------------------------------------
    # Step 2: Determine effective runtime domain
    # ------------------------------------------------------------------
    effective_domain = runtime_domain or cdr.get("runtime_domain_intent", "local")
    is_cross_device = effective_domain == "cross_device" or cdr.get("is_cross_device", False)

    # ------------------------------------------------------------------
    # Step 3: Build member list
    # ------------------------------------------------------------------
    members: List[FormationMember] = []
    seen_device_ids: set = set()

    def _add_member(
        device_id: Optional[str],
        role: FormationRole,
        reason: str,
        capabilities: Optional[List[str]] = None,
        is_local: bool = False,
    ) -> None:
        if device_id is None:
            return
        if device_id in seen_device_ids and role not in {
            FormationRole.MERGE_OWNER,
        }:
            return
        seen_device_ids.add(device_id)
        members.append(
            FormationMember(
                device_id=device_id,
                role=role,
                reason=reason,
                capabilities=capabilities or [],
                is_local=is_local,
            )
        )

    # SOURCE
    _add_member(source_device_id, FormationRole.SOURCE, "source device from routing context")

    # PRIMARY_EXECUTION
    _add_member(
        primary_device_id,
        FormationRole.PRIMARY_EXECUTION,
        "primary execution device from routing context",
    )

    # SUPPORT
    for dev_id in support_device_ids:
        _add_member(dev_id, FormationRole.SUPPORT, "support device from routing summary")

    # RELAY
    for dev_id in relay_device_ids:
        _add_member(dev_id, FormationRole.RELAY, "relay device from routing summary")

    # OBSERVER
    for dev_id in observer_device_ids:
        _add_member(dev_id, FormationRole.OBSERVER, "observer device from routing summary")

    # FALLBACK
    for dev_id in fallback_device_ids:
        _add_member(dev_id, FormationRole.FALLBACK, "fallback device from routing summary")

    # TARGET devices not yet classified → assign FALLBACK
    for dev_id in target_device_ids:
        if dev_id not in seen_device_ids:
            _add_member(dev_id, FormationRole.FALLBACK, "target device, role unresolved")

    # MERGE_OWNER
    effective_merge_owner = merge_owner_device_id
    if not effective_merge_owner and merge_summary is not None:
        # Attempt to extract merge owner from merge summary dict or object
        if isinstance(merge_summary, dict):
            effective_merge_owner = merge_summary.get("merge_owner_device_id")
        else:
            effective_merge_owner = getattr(merge_summary, "merge_owner_device_id", None)

    if effective_merge_owner and effective_merge_owner != primary_device_id:
        # Add an explicit MERGE_OWNER member (may duplicate device, which is
        # intentional — a device can hold both roles)
        members.append(
            FormationMember(
                device_id=effective_merge_owner,
                role=FormationRole.MERGE_OWNER,
                reason="explicit merge owner assignment",
            )
        )

    # ------------------------------------------------------------------
    # Step 4: Derive barrier posture
    # ------------------------------------------------------------------
    barrier_posture = _derive_barrier_posture(
        members=members,
        cdr_posture=cdr_posture,
        is_cross_device=is_cross_device,
    )

    # ------------------------------------------------------------------
    # Step 5: Derive formation reason
    # ------------------------------------------------------------------
    if formation_reason is None:
        if is_cross_device:
            formation_reason = f"cross_device formation for domain={effective_domain!r}"
        else:
            formation_reason = "local single-device formation"

    # ------------------------------------------------------------------
    # Step 6: Build FormationPolicy
    # ------------------------------------------------------------------
    policy = _derive_policy(
        members=members,
        barrier_posture=barrier_posture,
        is_cross_device=is_cross_device,
        execution_policy=execution_policy,
        effective_merge_owner=effective_merge_owner,
    )

    # ------------------------------------------------------------------
    # Step 7: Build DeviceFormationGroup
    # ------------------------------------------------------------------
    group = DeviceFormationGroup(
        task_id=task_id,
        trace_id=trace_id,
        source_device_id=source_device_id,
        source_runtime_posture=source_runtime_posture,
        members=members,
        merge_owner_device_id=effective_merge_owner,
        barrier_posture=barrier_posture.value,
        formation_reason=formation_reason,
        runtime_domain_intent=effective_domain,
    )

    return group, policy


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _derive_barrier_posture(
    *,
    members: List[FormationMember],
    cdr_posture: str,
    is_cross_device: bool,
) -> BarrierPosture:
    """Derive an appropriate :class:`BarrierPosture` from available signals."""
    if not is_cross_device:
        return BarrierPosture.WAIT_PRIMARY

    has_merge_owner = any(m.role == FormationRole.MERGE_OWNER for m in members)
    if has_merge_owner:
        return BarrierPosture.WAIT_MERGE_OWNER

    # Routing postures that imply a broader barrier
    if cdr_posture in ("split_execution", "mirrored_observation"):
        return BarrierPosture.WAIT_ALL

    if cdr_posture == "remote_required":
        return BarrierPosture.WAIT_PRIMARY

    # Default
    return BarrierPosture.WAIT_PRIMARY


def _derive_policy(
    *,
    members: List[FormationMember],
    barrier_posture: BarrierPosture,
    is_cross_device: bool,
    execution_policy: Optional[Any],
    effective_merge_owner: Optional[str],
) -> FormationPolicy:
    """Derive a :class:`FormationPolicy` from available signals."""
    multi_device_required = is_cross_device and len({m.device_id for m in members if m.device_id}) > 1

    merge_confirmation_required = False
    fallback_intent = "promote_fallback_device"

    # Probe execution policy for confirmation gate
    if execution_policy is not None:
        try:
            if isinstance(execution_policy, dict):
                merge_confirmation_required = bool(execution_policy.get("requires_confirmation", False))
            else:
                merge_confirmation_required = bool(getattr(execution_policy, "requires_confirmation", False))
        except Exception:
            pass

    has_fallback = any(m.role == FormationRole.FALLBACK for m in members)
    if not has_fallback:
        fallback_intent = "abort"

    # Determine minimum required devices (source + primary)
    min_required: List[str] = []
    for m in members:
        if m.role in (FormationRole.SOURCE, FormationRole.PRIMARY_EXECUTION):
            if m.device_id:
                min_required.append(m.device_id)

    policy_reason = (
        f"derived from formation signals: domain=cross_device={is_cross_device!r}, "
        f"posture={barrier_posture.value!r}, "
        f"merge_owner={effective_merge_owner!r}"
    )

    return FormationPolicy(
        barrier_posture=barrier_posture,
        multi_device_required=multi_device_required,
        merge_confirmation_required=merge_confirmation_required,
        minimum_required_device_ids=min_required,
        fallback_intent=fallback_intent,
        policy_reason=policy_reason,
    )
