#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.device_formation
=======================

PR-17 (V4) — Device Formation & Multi-Device Group Model

A focused, additive package that formalises **multi-device formation
semantics** on top of the existing cross-device architecture.

This package answers:
  - Which devices currently belong to the same execution formation?
  - Which device is the source/origin device?
  - Which device is the primary execution device?
  - Which devices are support / observer / relay / fallback members?
  - Which device owns merge responsibility?
  - What barrier/completion posture is intended for the group?
  - How can this formation be serialised, inspected, and attached to
    projection payloads?

Source signals consumed (read-only, not modified)
--------------------------------------------------
* :class:`~core.cross_device_policy.CrossDeviceAssignmentSummary` — PR-13
* :class:`~core.execution_policy.ExecutionPolicy` — PR-11
* :class:`~core.distributed_execution.MergeSummary` — PR-14
* :class:`~core.contract_map.ContractDescriptor` — PR-16
* Task/task-envelope metadata (``task_id``, ``trace_id``, device lists)
* Device manager / health signals (optional)

What this package does NOT do
------------------------------
- It does **not** replace or modify the existing device manager, device
  router (:mod:`~galaxy_gateway.device_router`), TaskGraph,
  :class:`~core.unified.device_manager.UnifiedDeviceManager`, or any other
  orchestration module.
- It does **not** introduce a competing orchestrator or runtime.
- All paths are additive and read-only from the perspective of existing
  orchestration layers.

Public API
----------
FormationRole
    Stable enum of formation member roles:
    ``source_device``, ``primary_execution_device``, ``support_device``,
    ``observer_device``, ``relay_device``, ``fallback_device``,
    ``merge_owner_device``, ``unassigned``.

FORMATION_ROLE_PRECEDENCE
    Ordered list of :class:`FormationRole` values from most to least
    authoritative.

formation_role_description(role) → str
    Human-readable description for a :class:`FormationRole`.

FormationMember
    Immutable, serialisable per-device member record.  Fields: ``device_id``,
    ``role``, ``reason``, ``capabilities``, ``is_local``, ``health_score``.

DeviceFormationGroup
    Central, wire-safe model of a multi-device formation group.  Fields cover
    formation/group id, task/trace id, source device, members, merge owner,
    barrier posture, formation reason, and runtime domain intent.  Properties:
    ``primary_execution_device_id``, ``fallback_device_ids``,
    ``support_device_ids``, ``observer_device_ids``, ``relay_device_ids``,
    ``all_member_device_ids``, ``effective_merge_owner_device_id``,
    ``member_count``, ``is_multi_device``.

EMPTY_FORMATION_GROUP
    Pre-built empty formation group for idle/uninitialised state.

BARRIER_POSTURES
    Dict of stable barrier posture string values to descriptions.

BarrierPosture
    Stable enum of barrier/completion postures: ``wait_all``,
    ``wait_primary``, ``best_effort``, ``wait_merge_owner``.

BARRIER_POSTURE_DESCRIPTIONS
    Dict of human-readable descriptions for each posture.

FormationPolicy
    Immutable, serialisable policy contract.  Fields: ``barrier_posture``,
    ``multi_device_required``, ``merge_confirmation_required``,
    ``minimum_required_device_ids``, ``fallback_intent``, ``policy_reason``.

DEFAULT_LOCAL_FORMATION_POLICY
    Pre-built conservative local-only policy for safe-fallback use.

resolve_formation(…) → (DeviceFormationGroup, FormationPolicy)
    Derive formation group and policy from available signals.  All inputs
    optional.  Degrades gracefully when signals are absent.

FormationSummary
    Compact, public-safe summary dataclass for API/projection use.

IDLE_FORMATION_SUMMARY
    Pre-built idle summary for local/no-formation state.

build_formation_summary(group, policy) → FormationSummary
    Build a summary from a group + policy pair.

attach_formation_to_projection(projection_dict, summary) → dict
    Attach a formation summary to a ``RuntimeProjection`` dict additively.

get_formation_hints(summary) → dict
    Compact boolean/scalar hints for quick downstream checks.

resolve_formation_summary(…) → FormationSummary
    One-call convenience helper: resolve and summarise in one step.

See Also
--------
docs/DEVICE_FORMATION_AND_MULTI_DEVICE_GROUPS.md — design document.
core/cross_device_policy/ — PR-13 routing role & policy (upstream signal).
core/distributed_execution/ — PR-14 merge/recovery (upstream signal).
core/execution_policy/ — PR-11 execution policy (upstream signal).
core/contract_map/ — PR-16 cross-plane contract map (upstream signal).
"""

from __future__ import annotations

from .formation_role import (
    FormationRole,
    FORMATION_ROLE_PRECEDENCE,
    formation_role_description,
    FormationMember,
)
from .formation_group import (
    DeviceFormationGroup,
    EMPTY_FORMATION_GROUP,
    BARRIER_POSTURES,
)
from .formation_policy import (
    BarrierPosture,
    BARRIER_POSTURE_DESCRIPTIONS,
    FormationPolicy,
    DEFAULT_LOCAL_FORMATION_POLICY,
)
from .formation_resolver import resolve_formation
from .formation_rebalance_engine import (
    FormationHealthSignal,
    MemberRebalanceAction,
    RebalanceDecision,
    FormationRebalanceEngine,
    evaluate_formation_health,
    apply_rebalance,
    maybe_promote_fallback,
    maybe_remove_unhealthy,
    FORMATION_REBALANCE_ENGINE_IS_AUTHORITY,
    FORMATION_REBALANCE_GAP_CLOSURE_SENTINEL,
    REBALANCE_MUST_PRESERVE_SOURCE_POLICY,
    REBALANCE_MUST_MAINTAIN_PRIMARY_POLICY,
    HEALTH_THRESHOLD_GOVERNS_REMOVAL_POLICY,
)
from .formation_summary import (
    FormationSummary,
    IDLE_FORMATION_SUMMARY,
    build_formation_summary,
    attach_formation_to_projection,
    get_formation_hints,
    resolve_formation_summary,
)
from .formation_runtime_coordinator import (
    FormationParticipantState,
    FormationRuntimeState,
    RecoveryActionType,
    FormationParticipantStatus,
    FormationRecoveryAction,
    FormationRuntimeDecision,
    FormationRuntimeSnapshot,
    FormationRuntimeCoordinator,
    make_formation_runtime_coordinator,
    FORMATION_RUNTIME_COORDINATOR_IS_AUTHORITY,
    FORMATION_RECOVERY_HOOKS_GAP_CLOSURE_SENTINEL,
    DEGRADED_CONTINUATION_REQUIRES_PRIMARY_POLICY,
    RECOVERY_PRESERVES_SOURCE_POLICY,
)
from .formation_auto_enrollment import (
    FormationParticipantEntry,
    FormationAutoEnrollmentManager,
    get_formation_auto_enrollment_manager,
    reset_formation_auto_enrollment_manager,
    FORMATION_AUTO_ENROLLMENT_MANAGER_IS_AUTHORITY,
    FORMATION_AUTO_ENROLLMENT_IS_IDEMPOTENT_POLICY,
)
from .formation_rebalance_trigger import (
    FormationRuntimeEventType,
    FormationRuntimeEvent,
    FormationRebuildResult,
    on_runtime_event,
    trigger_rebalance_if_needed,
    FORMATION_REBALANCE_TRIGGER_IS_AUTHORITY,
    FORMATION_TRIGGER_WIRES_COORDINATOR_TO_ENGINE_POLICY,
    FORMATION_TRIGGER_DOES_NOT_OWN_STATE_POLICY,
)

__all__ = [
    # Formation roles
    "FormationRole",
    "FORMATION_ROLE_PRECEDENCE",
    "formation_role_description",
    "FormationMember",
    # Formation group
    "DeviceFormationGroup",
    "EMPTY_FORMATION_GROUP",
    "BARRIER_POSTURES",
    # Formation policy
    "BarrierPosture",
    "BARRIER_POSTURE_DESCRIPTIONS",
    "FormationPolicy",
    "DEFAULT_LOCAL_FORMATION_POLICY",
    # Resolver
    "resolve_formation",
    # Rebalance engine
    "FormationHealthSignal",
    "MemberRebalanceAction",
    "RebalanceDecision",
    "FormationRebalanceEngine",
    "evaluate_formation_health",
    "apply_rebalance",
    "maybe_promote_fallback",
    "maybe_remove_unhealthy",
    "FORMATION_REBALANCE_ENGINE_IS_AUTHORITY",
    "FORMATION_REBALANCE_GAP_CLOSURE_SENTINEL",
    "REBALANCE_MUST_PRESERVE_SOURCE_POLICY",
    "REBALANCE_MUST_MAINTAIN_PRIMARY_POLICY",
    "HEALTH_THRESHOLD_GOVERNS_REMOVAL_POLICY",
    # Summary helpers
    "FormationSummary",
    "IDLE_FORMATION_SUMMARY",
    "build_formation_summary",
    "attach_formation_to_projection",
    "get_formation_hints",
    "resolve_formation_summary",
    # Runtime coordinator
    "FormationParticipantState",
    "FormationRuntimeState",
    "RecoveryActionType",
    "FormationParticipantStatus",
    "FormationRecoveryAction",
    "FormationRuntimeDecision",
    "FormationRuntimeSnapshot",
    "FormationRuntimeCoordinator",
    "make_formation_runtime_coordinator",
    "FORMATION_RUNTIME_COORDINATOR_IS_AUTHORITY",
    "FORMATION_RECOVERY_HOOKS_GAP_CLOSURE_SENTINEL",
    "DEGRADED_CONTINUATION_REQUIRES_PRIMARY_POLICY",
    "RECOVERY_PRESERVES_SOURCE_POLICY",
    # Auto-enrollment manager
    "FormationParticipantEntry",
    "FormationAutoEnrollmentManager",
    "get_formation_auto_enrollment_manager",
    "reset_formation_auto_enrollment_manager",
    "FORMATION_AUTO_ENROLLMENT_MANAGER_IS_AUTHORITY",
    "FORMATION_AUTO_ENROLLMENT_IS_IDEMPOTENT_POLICY",
    # Rebalance trigger
    "FormationRuntimeEventType",
    "FormationRuntimeEvent",
    "FormationRebuildResult",
    "on_runtime_event",
    "trigger_rebalance_if_needed",
    "FORMATION_REBALANCE_TRIGGER_IS_AUTHORITY",
    "FORMATION_TRIGGER_WIRES_COORDINATOR_TO_ENGINE_POLICY",
    "FORMATION_TRIGGER_DOES_NOT_OWN_STATE_POLICY",
]
