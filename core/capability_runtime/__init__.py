#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.capability_runtime
========================

PR-20 (V4) — Capability Runtime State

A focused additive package that formalises **capability runtime state** —
availability posture, constraint flags, routing preferences, and health-gating
signals — across the Galaxy runtime's existing capability, routing, and
dispatch infrastructure.

This package answers:
  - Is a given capability currently available, degraded, or unavailable?
  - Which devices are bound to or preferred for this capability?
  - Are there constraint flags (e.g., requires confirmation, cross-device
    restricted, latency-sensitive)?
  - What health or reliability signals are attached to this capability?

Source signals consumed (read-only, not modified)
--------------------------------------------------
* :class:`~core.unified.capability_contract.CapabilityContract` — name /
  source / available fields used as seeds.
* :class:`~core.agent.capability_registry.CapabilityRegistry` — existing
  static registry; the runtime layer sits alongside it.
* :class:`~core.unified.device_manager.UnifiedDeviceManager` — device
  capabilities list and health signals.
* :class:`~core.unified.device_health.DeviceHealthScorer` — health scores
  fed into reliability_flags.

What this package does NOT do
------------------------------
- It does **not** replace the existing
  :class:`~core.agent.capability_registry.CapabilityRegistry`.
- It does **not** change transport or orchestration behaviour.
- It does **not** create a new runtime or message bus.
- It does **not** introduce automated capability scoring from health
  (that is a future step).

Public API
----------
CapabilityAvailability
    Stable enum: ``available``, ``degraded``, ``unavailable``, ``unknown``.

CapabilityRuntimeState
    Serialisable runtime state for a single capability.

CapabilityConstraintFlags
    Immutable constraint flag set for a capability.

CapabilityPreference
    Routing preference model for a capability.

CapabilityRuntimeSummary
    Public-safe, read-only summary combining all runtime dimensions.

CapabilityRuntimeRegistry
    Process-level singleton runtime state store.

UNKNOWN_CAPABILITY_SUMMARY
    Safe sentinel for unknown/missing capabilities.

make_capability_summary
    One-call factory for creating :class:`CapabilityRuntimeSummary` instances.

get_capability_runtime_snapshot
    Return all summaries as a JSON-serialisable dict.

attach_runtime_summary_to_projection
    Additively enrich a projection dict with a capability runtime summary.

NO_CONSTRAINTS, CONFIRMATION_REQUIRED, LOCAL_ONLY, LATENCY_CRITICAL,
EXCLUSIVE_LOCAL
    Pre-built :class:`CapabilityConstraintFlags` sentinels.

NO_PREFERENCE
    Pre-built :class:`CapabilityPreference` sentinel.
"""

from __future__ import annotations

from .capability_constraint import (
    CapabilityConstraintFlags,
    NO_CONSTRAINTS,
    CONFIRMATION_REQUIRED,
    LOCAL_ONLY,
    LATENCY_CRITICAL,
    EXCLUSIVE_LOCAL,
)
from .capability_preference import (
    CapabilityPreference,
    NO_PREFERENCE,
)
from .capability_registry_runtime import CapabilityRuntimeRegistry
from .capability_state import (
    CapabilityAvailability,
    CapabilityRuntimeState,
    availability_description,
    AVAILABILITY_DESCRIPTIONS,
)
from .capability_summary import (
    CapabilityRuntimeSummary,
    UNKNOWN_CAPABILITY_SUMMARY,
    make_capability_summary,
    get_capability_runtime_snapshot,
    attach_runtime_summary_to_projection,
    SCHEMA_VERSION,
)

__all__ = [
    # state
    "CapabilityAvailability",
    "CapabilityRuntimeState",
    "availability_description",
    "AVAILABILITY_DESCRIPTIONS",
    # constraint
    "CapabilityConstraintFlags",
    "NO_CONSTRAINTS",
    "CONFIRMATION_REQUIRED",
    "LOCAL_ONLY",
    "LATENCY_CRITICAL",
    "EXCLUSIVE_LOCAL",
    # preference
    "CapabilityPreference",
    "NO_PREFERENCE",
    # registry
    "CapabilityRuntimeRegistry",
    # summary
    "CapabilityRuntimeSummary",
    "UNKNOWN_CAPABILITY_SUMMARY",
    "make_capability_summary",
    "get_capability_runtime_snapshot",
    "attach_runtime_summary_to_projection",
    "SCHEMA_VERSION",
]
