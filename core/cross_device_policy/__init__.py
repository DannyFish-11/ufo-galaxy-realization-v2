#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.cross_device_policy
==========================

PR-13 (V4) — Cross-Device Role & Routing Policy

A focused, additive package that formalises cross-device role semantics and
routing policy for the Galaxy runtime.

This package answers, given current system signals:
  - Which device originated the request? (``source_device_id``)
  - Which device is the primary executor? (``primary_execution_device_id``)
  - What is each participating device's role? (:class:`DeviceRole`)
  - What routing posture is intended? (:class:`RoutingPosture`)
  - Is cross-device expansion permitted by execution policy?
  - Is confirmation required before expansion?

Source signals consumed (read-only, not modified)
--------------------------------------------------
* :class:`~core.continuum.types.RuntimeDomain` — PR-3
* :class:`~core.execution_policy.ExecutionPolicy` — PR-11
* :class:`~core.orchestration_authority.AuthorityRole` — PR-9
* Task/task-envelope metadata (``task_id``, ``trace_id``, hints)
* ``source_device_id`` / ``target_device_ids`` from device assignment layers

Public API
----------
DeviceRole
    Enum of device participation roles: ``source_device``,
    ``primary_execution_device``, ``support_device``, ``observer_device``,
    ``relay_device``, ``fallback_device``, ``unassigned``.

ROLE_PRECEDENCE
    Ordered list of :class:`DeviceRole` values from most to least authoritative.

role_description(role) → str
    Human-readable description for a :class:`DeviceRole`.

DeviceRoleAssignment
    Immutable, serialisable per-device role record.  Fields: ``device_id``,
    ``role``, ``reason``, ``capabilities``, ``is_local``.

RoutingPosture
    Enum of routing postures: ``local_preferred``, ``local_then_expand``,
    ``remote_required``, ``split_execution``, ``mirrored_observation``,
    ``undecided``.

POSTURE_DESCRIPTIONS
    Dict mapping each posture string value to its description.

RoutingPolicy
    Immutable, serialisable routing-policy dataclass.  Fields: ``posture``,
    ``source_device_id``, ``assigned_devices``, ``runtime_domain_intent``,
    ``policy_reason``, ``expansion_allowed_by_execution_policy``,
    ``confirmation_required_before_expansion``, ``task_id``, ``trace_id``.
    Properties: ``is_cross_device``, ``primary_execution_device_id``,
    ``source_assignment``.

DEFAULT_LOCAL_ROUTING_POLICY
    Pre-built :class:`RoutingPolicy` for safe-fallback use (local, no expansion).

CrossDeviceAssignmentSummary
    Serialisable summary dataclass.  Fields cover all role-grouped device lists,
    posture, gates, and traceability.

IDLE_ASSIGNMENT_SUMMARY
    Pre-built :class:`CrossDeviceAssignmentSummary` for local-only state.

build_assignment_summary(policy) → CrossDeviceAssignmentSummary
    Convert a :class:`RoutingPolicy` to a public-safe summary.

attach_cross_device_to_projection(projection_dict, summary) → dict
    Attach a routing summary to a ``RuntimeProjection`` dict additively.

get_assignment_hints(summary) → dict
    Compact boolean/scalar hints for quick downstream checks.

resolve_routing(…) → RoutingPolicy
    Derive a routing policy from available signals.  All inputs optional.
    Degrades gracefully when signals are absent.

resolve_routing_summary(…) → CrossDeviceAssignmentSummary
    Convenience wrapper: resolve and convert to summary in one call.

What this package does NOT do
------------------------------
- It does **not** replace or modify the existing device manager, device
  router, TaskGraph, or orchestration modules.
- It does **not** implement distributed merge/recovery logic (planned for
  a later PR).
- All paths are additive and read-only from the perspective of existing
  orchestration layers.

See Also
--------
docs/CROSS_DEVICE_ROLE_ROUTING_POLICY.md — design document for this package.
core/execution_policy/ — PR-11 execution policy schema (upstream signal).
core/orchestration_authority/ — PR-9 authority roles (upstream signal).
"""

from __future__ import annotations

from .device_role import (
    DeviceRole,
    ROLE_PRECEDENCE,
    role_description,
    DeviceRoleAssignment,
)
from .routing_policy import (
    RoutingPosture,
    POSTURE_DESCRIPTIONS,
    RoutingPolicy,
    DEFAULT_LOCAL_ROUTING_POLICY,
)
from .assignment_summary import (
    CrossDeviceAssignmentSummary,
    IDLE_ASSIGNMENT_SUMMARY,
    build_assignment_summary,
    attach_cross_device_to_projection,
    get_assignment_hints,
)
from .routing_resolver import (
    resolve_routing,
    resolve_routing_summary,
)

# PR-6: Re-export participation semantics so callers can import them from
# the cross_device_policy package directly.
from core.device_selection import DeviceParticipationStatus

__all__ = [
    # Device role
    "DeviceRole",
    "ROLE_PRECEDENCE",
    "role_description",
    "DeviceRoleAssignment",
    # Routing posture and policy
    "RoutingPosture",
    "POSTURE_DESCRIPTIONS",
    "RoutingPolicy",
    "DEFAULT_LOCAL_ROUTING_POLICY",
    # Summary helpers
    "CrossDeviceAssignmentSummary",
    "IDLE_ASSIGNMENT_SUMMARY",
    "build_assignment_summary",
    "attach_cross_device_to_projection",
    "get_assignment_hints",
    # Resolver
    "resolve_routing",
    "resolve_routing_summary",
    # PR-6: participation semantics
    "DeviceParticipationStatus",
]
