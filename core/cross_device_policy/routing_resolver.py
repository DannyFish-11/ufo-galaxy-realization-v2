#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.cross_device_policy.routing_resolver
==========================================

PR-13 (V4) — Cross-Device Role & Routing Policy

Provides the **routing resolver** that derives a :class:`~.routing_policy.RoutingPolicy`
from available runtime signals.

The resolver is designed to degrade gracefully: all inputs are optional,
and it falls back to a conservative local policy whenever signals are absent
or unrecognised.

Signal Sources (read-only, not modified)
-----------------------------------------
* ``runtime_domain`` — :class:`~core.continuum.types.RuntimeDomain` string
  or object.  Drives whether cross-device routing is considered at all.
* ``execution_policy`` — :class:`~core.execution_policy.ExecutionPolicy`
  or ``None``.  Gates expansion and confirmation requirements.
* ``source_device_id`` — string identifier of the originating device.
* ``target_device_ids`` — explicit list of device IDs already designated
  as targets (e.g. from a ``CommandEnvelope`` or task metadata).
* ``task_id`` / ``trace_id`` — traceability fields.
* ``authority_role`` — :class:`~core.orchestration_authority.AuthorityRole`
  string or object.  Legacy roles downgrade cross-device permissions.
* ``task_envelope_meta`` — dict of extra task-envelope metadata (used to
  extract ``requires_cross_device``, ``split_execution`` hints, etc.).

Resolution Logic
----------------
1. If ``runtime_domain`` is not ``cross_device``, return a
   ``LOCAL_PREFERRED`` policy regardless of other inputs.
2. If ``runtime_domain`` is ``cross_device``:
   a. Check ``execution_policy.cross_device_allowed``.  If ``False``,
      return ``LOCAL_PREFERRED`` with expansion blocked.
   b. Check for ``split_execution`` hint in task envelope metadata.
      If present, use ``SPLIT_EXECUTION`` posture.
   c. Check for ``remote_required`` hint.  If present, use
      ``REMOTE_REQUIRED`` posture.
   d. If explicit ``target_device_ids`` are given, use
      ``LOCAL_THEN_EXPAND`` posture (explicit targets available).
   e. Otherwise use ``LOCAL_THEN_EXPAND`` as the default cross-device
      posture.
3. Build :class:`~.device_role.DeviceRoleAssignment` entries from the
   available device IDs:
   - ``source_device_id`` → :attr:`~.device_role.DeviceRole.SOURCE`
   - first ``target_device_ids`` entry → :attr:`~.device_role.DeviceRole.PRIMARY_EXECUTION`
   - remaining entries → :attr:`~.device_role.DeviceRole.SUPPORT`
4. Propagate ``expansion_allowed`` and ``confirmation_required`` from
   the execution policy.
5. Return the resolved :class:`~.routing_policy.RoutingPolicy`.

Public API
----------
resolve_routing(…) → RoutingPolicy
    Derive a routing policy from available signals.

resolve_routing_summary(…) → CrossDeviceAssignmentSummary
    Convenience wrapper: resolve and convert to summary in one call.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .device_role import DeviceRole, DeviceRoleAssignment
from .routing_policy import RoutingPolicy, RoutingPosture, DEFAULT_LOCAL_ROUTING_POLICY
from .assignment_summary import CrossDeviceAssignmentSummary, build_assignment_summary

logger = logging.getLogger("Galaxy.CrossDevicePolicy.Resolver")

__all__ = [
    "resolve_routing",
    "resolve_routing_summary",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _coerce_str(value: Any) -> Optional[str]:
    """Coerce a value to a plain string, or return None."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    # Enum objects have .value
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _is_cross_device_domain(domain: Optional[str]) -> bool:
    """Return True if *domain* represents a cross-device runtime domain."""
    if domain is None:
        return False
    return domain.lower() in ("cross_device",)


def _extract_execution_policy_flags(
    execution_policy: Any,
) -> tuple[bool, bool]:
    """Extract (cross_device_allowed, requires_confirmation) from a policy.

    Accepts:
    - :class:`~core.execution_policy.ExecutionPolicy` instances
    - dicts with the expected keys
    - ``None`` → conservative defaults (False, True)
    """
    if execution_policy is None:
        return False, True

    if isinstance(execution_policy, dict):
        return (
            bool(execution_policy.get("cross_device_allowed", False)),
            bool(execution_policy.get("requires_confirmation", True)),
        )

    # ExecutionPolicy dataclass (or duck-typed equivalent)
    try:
        return (
            bool(getattr(execution_policy, "cross_device_allowed", False)),
            bool(getattr(execution_policy, "requires_confirmation", True)),
        )
    except Exception:  # pragma: no cover
        return False, True


def _is_legacy_authority(authority_role: Any) -> bool:
    """Return True if *authority_role* represents a legacy or deprecated path."""
    if authority_role is None:
        return False
    role_str = _coerce_str(authority_role) or ""
    return role_str.lower() in ("legacy_compatibility", "deprecated")


def _build_assignments(
    source_device_id: Optional[str],
    target_device_ids: List[str],
    posture: RoutingPosture,
) -> List[DeviceRoleAssignment]:
    """Build a list of :class:`DeviceRoleAssignment` entries.

    Logic:
    - ``source_device_id`` → SOURCE (always included if not None)
    - For non-local postures, the first target becomes PRIMARY_EXECUTION
    - Remaining targets become SUPPORT (for SPLIT_EXECUTION) or
      SUPPORT / OBSERVER depending on posture
    - For MIRRORED_OBSERVATION, all targets after the first become OBSERVER
    """
    assignments: List[DeviceRoleAssignment] = []

    if source_device_id:
        assignments.append(
            DeviceRoleAssignment(
                device_id=source_device_id,
                role=DeviceRole.SOURCE,
                reason="device that originated the request",
                is_local=True,
            )
        )

    if not target_device_ids:
        return assignments

    # Determine roles for target devices based on posture
    for idx, device_id in enumerate(target_device_ids):
        if idx == 0:
            role = DeviceRole.PRIMARY_EXECUTION
            reason = "designated primary executor"
        elif posture is RoutingPosture.MIRRORED_OBSERVATION:
            role = DeviceRole.OBSERVER
            reason = "mirrored observer"
        elif posture is RoutingPosture.SPLIT_EXECUTION:
            role = DeviceRole.SUPPORT
            reason = f"split execution branch {idx}"
        else:
            role = DeviceRole.SUPPORT
            reason = "support device"

        assignments.append(
            DeviceRoleAssignment(
                device_id=device_id,
                role=role,
                reason=reason,
                is_local=False,
            )
        )

    return assignments


# ---------------------------------------------------------------------------
# Public resolver
# ---------------------------------------------------------------------------


def resolve_routing(
    *,
    runtime_domain: Optional[Any] = None,
    execution_policy: Optional[Any] = None,
    source_device_id: Optional[str] = None,
    target_device_ids: Optional[List[str]] = None,
    authority_role: Optional[Any] = None,
    task_envelope_meta: Optional[Dict[str, Any]] = None,
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> RoutingPolicy:
    """Derive a :class:`~.routing_policy.RoutingPolicy` from available signals.

    All parameters are optional.  The resolver degrades gracefully when
    signals are absent or unrecognised, returning a conservative local policy.

    Parameters
    ----------
    runtime_domain:
        The current :class:`~core.continuum.types.RuntimeDomain` value.
        Accepts the enum, its string value, or ``None``.  When ``None`` or
        not ``"cross_device"``, a local policy is returned.
    execution_policy:
        The active :class:`~core.execution_policy.ExecutionPolicy`, or a
        dict, or ``None``.  Used to gate cross-device expansion and derive
        confirmation requirements.
    source_device_id:
        Identifier of the device that originated the request.
    target_device_ids:
        List of target device IDs already designated for this task.  May be
        ``None`` or empty.
    authority_role:
        The current :class:`~core.orchestration_authority.AuthorityRole`.
        Legacy / deprecated roles downgrade cross-device permissions.
    task_envelope_meta:
        Extra metadata from the task envelope.  Recognised keys:
        - ``"requires_cross_device"`` (bool)
        - ``"split_execution"`` (bool)
        - ``"remote_required"`` (bool)
        - ``"mirrored_observation"`` (bool)
    task_id:
        Optional task identifier for traceability.
    trace_id:
        Optional distributed-trace identifier.

    Returns
    -------
    RoutingPolicy
        The resolved routing policy.  Never raises.
    """
    try:
        return _resolve_routing_impl(
            runtime_domain=runtime_domain,
            execution_policy=execution_policy,
            source_device_id=source_device_id,
            target_device_ids=target_device_ids or [],
            authority_role=authority_role,
            task_envelope_meta=task_envelope_meta or {},
            task_id=task_id,
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.warning("resolve_routing: error resolving routing policy: %s", exc)
        return DEFAULT_LOCAL_ROUTING_POLICY


def resolve_routing_summary(
    *,
    runtime_domain: Optional[Any] = None,
    execution_policy: Optional[Any] = None,
    source_device_id: Optional[str] = None,
    target_device_ids: Optional[List[str]] = None,
    authority_role: Optional[Any] = None,
    task_envelope_meta: Optional[Dict[str, Any]] = None,
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> CrossDeviceAssignmentSummary:
    """Resolve a routing policy and immediately convert it to a summary.

    This is a convenience wrapper combining :func:`resolve_routing` and
    :func:`~.assignment_summary.build_assignment_summary`.

    All parameters are the same as :func:`resolve_routing`.

    Returns
    -------
    CrossDeviceAssignmentSummary
        The stable summary.  Never raises.
    """
    policy = resolve_routing(
        runtime_domain=runtime_domain,
        execution_policy=execution_policy,
        source_device_id=source_device_id,
        target_device_ids=target_device_ids,
        authority_role=authority_role,
        task_envelope_meta=task_envelope_meta,
        task_id=task_id,
        trace_id=trace_id,
    )
    return build_assignment_summary(policy)


# ---------------------------------------------------------------------------
# Internal implementation
# ---------------------------------------------------------------------------


def _resolve_routing_impl(
    *,
    runtime_domain: Optional[Any],
    execution_policy: Optional[Any],
    source_device_id: Optional[str],
    target_device_ids: List[str],
    authority_role: Optional[Any],
    task_envelope_meta: Dict[str, Any],
    task_id: Optional[str],
    trace_id: Optional[str],
) -> RoutingPolicy:
    """Internal implementation of the routing resolver."""

    domain_str = _coerce_str(runtime_domain)

    # ------------------------------------------------------------------
    # 1. Non-cross-device domain → always local
    # ------------------------------------------------------------------
    if not _is_cross_device_domain(domain_str):
        return RoutingPolicy(
            posture=RoutingPosture.LOCAL_PREFERRED,
            source_device_id=source_device_id,
            assigned_devices=_build_assignments(
                source_device_id, [], RoutingPosture.LOCAL_PREFERRED
            ),
            runtime_domain_intent=domain_str or "local",
            policy_reason="runtime domain is not cross_device; local execution preferred",
            expansion_allowed_by_execution_policy=False,
            confirmation_required_before_expansion=True,
            task_id=task_id,
            trace_id=trace_id,
        )

    # ------------------------------------------------------------------
    # 2. Cross-device domain: extract execution policy gates
    # ------------------------------------------------------------------
    cross_device_allowed, requires_confirmation = _extract_execution_policy_flags(
        execution_policy
    )

    # Legacy authority roles downgrade cross-device permission
    if _is_legacy_authority(authority_role):
        cross_device_allowed = False
        requires_confirmation = True
        logger.debug(
            "resolve_routing: legacy/deprecated authority role detected — "
            "cross-device expansion downgraded to disabled"
        )

    # ------------------------------------------------------------------
    # 3. Check execution policy gate
    # ------------------------------------------------------------------
    if not cross_device_allowed:
        return RoutingPolicy(
            posture=RoutingPosture.LOCAL_PREFERRED,
            source_device_id=source_device_id,
            assigned_devices=_build_assignments(
                source_device_id, [], RoutingPosture.LOCAL_PREFERRED
            ),
            runtime_domain_intent="cross_device",
            policy_reason=(
                "cross_device domain requested but execution policy does not "
                "allow cross-device expansion"
            ),
            expansion_allowed_by_execution_policy=False,
            confirmation_required_before_expansion=requires_confirmation,
            task_id=task_id,
            trace_id=trace_id,
        )

    # ------------------------------------------------------------------
    # 4. Determine routing posture from task envelope hints
    # ------------------------------------------------------------------
    if task_envelope_meta.get("split_execution"):
        posture = RoutingPosture.SPLIT_EXECUTION
        reason = "split_execution hint in task envelope"
    elif task_envelope_meta.get("remote_required"):
        posture = RoutingPosture.REMOTE_REQUIRED
        reason = "remote_required hint in task envelope"
    elif task_envelope_meta.get("mirrored_observation"):
        posture = RoutingPosture.MIRRORED_OBSERVATION
        reason = "mirrored_observation hint in task envelope"
    elif target_device_ids:
        posture = RoutingPosture.LOCAL_THEN_EXPAND
        reason = "explicit target devices provided — local then expand"
    else:
        posture = RoutingPosture.LOCAL_THEN_EXPAND
        reason = "cross_device domain with no explicit posture — default local then expand"

    # ------------------------------------------------------------------
    # 5. Build device role assignments
    # ------------------------------------------------------------------
    assignments = _build_assignments(source_device_id, target_device_ids, posture)

    return RoutingPolicy(
        posture=posture,
        source_device_id=source_device_id,
        assigned_devices=assignments,
        runtime_domain_intent="cross_device",
        policy_reason=reason,
        expansion_allowed_by_execution_policy=cross_device_allowed,
        confirmation_required_before_expansion=requires_confirmation,
        task_id=task_id,
        trace_id=trace_id,
    )
