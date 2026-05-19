#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""core/cross_device_dispatch_boundary.py — PR-02: Cross-Device Dispatch Boundary Contract
=============================================================================================

**PR-02: Cross-Device Dispatch Boundary Consolidation**
---------------------------------------------------------
This module is the single authoritative source of truth for the cross-device
dispatch boundary.  It consolidates the dispatch path categories, their string
constants, and boundary enforcement rules that were previously scattered as
inline string literals across ``device_router.py``, ``cross_device_coordinator.py``,
``capability_orchestrator.py``, and ``command_router.py``.

Boundary model
--------------
The cross-device dispatch boundary is governed by four distinct path categories.
Every cross-device dispatch call must be classifiable into exactly one of these
categories:

1. **Canonical dispatch** (``dispatch_path = "canonical_dispatch"``)

   The primary, governed path through which all new cross-device work MUST flow::

       CommandRouter.route_envelope()          (sole canonical entry, GAP-517-001)
           └─ DeviceRouter.route_task()         (transport substrate)
                 └─ AgentBridge.handoff()        (preferred execution transport)

   This path sets ``route_mode`` and ``dispatch_path`` from the envelope metadata
   before reaching the device substrate.  The ``_SUBSTRATE_CALLER_CTX_KEY`` is
   propagated through context so that inner substrate can verify canonical origin.

2. **Controlled canonical fallback** (``dispatch_path = "canonical_fallback"``)

   A sanctioned fallback that activates when ``AgentBridge`` is unavailable or its
   import fails.  Still initiated from the canonical ``DeviceRouter.route_task()``
   call stack::

       DeviceRouter.route_task()
           ├─ AgentBridge not configured / import error
           └─ CrossDeviceCoordinator.execute_cross_device_task()
                 _substrate_caller="device_router.route_task"

   This fallback is **controlled** because it originates from inside the canonical
   path and preserves the substrate-caller contract.  It is a legitimate fallback,
   not a bypass.

3. **Compat fallback** (``dispatch_path = "compat_fallback"``)

   An explicitly-labelled compatibility path used when ``CapabilityOrchestrator``'s
   ``builtin_cross_device`` capability cannot reach ``DeviceRouter`` (e.g., the
   router raises an unrecoverable exception at capability-dispatch time)::

       CapabilityOrchestrator._execute_builtin("builtin_cross_device")
           ├─ DeviceRouter.route_task()        ← preferred, tried first
           │   └─ exception
           └─ CrossDeviceCoordinator.execute_cross_device_task()
                 route_mode="cross_device_compat_fallback"
                 _substrate_caller="capability_orchestrator.compat_fallback"

   This path is retained for engineering resilience but MUST NOT be treated as
   the primary cross-device path for new work.

4. **Legacy bypass** (``dispatch_path = "legacy_bypass"``)

   Any direct invocation of ``CrossDeviceCoordinator.execute_cross_device_task()``
   without a canonical substrate caller.  These calls predate the canonical spine
   and are permitted to proceed (fail-open) but must emit a structured
   ``LEGACY_DISPATCH`` warning and record an integrity event.

   Legacy bypass calls are NOT valid for new code.  Callers must migrate to the
   canonical path.

Architecture boundary invariants
---------------------------------
1.  ``CommandRouter.route_envelope()`` is the **sole canonical cross-device entry**.
    (GAP-517-001 / PR-518).

2.  ``DeviceRouter.route_task()`` is the **canonical transport substrate**.  It is
    NOT a planning, orchestration, or policy authority.

3.  ``CrossDeviceCoordinator.execute_cross_device_task()`` is **substrate-only**
    plumbing invoked by DeviceRouter.  External callers MUST NOT call it directly.

4.  **DeviceRouter must not become a single point for all responsibilities.**
    Policy decisions, execution planning, and control-plane work must remain in
    their respective canonical modules.

5.  This module is **governance only** — it does NOT introduce new routing logic
    or change any dispatch behavior.

Public API
----------
Constants::

    DISPATCH_PATH_CANONICAL              = "canonical_dispatch"
    DISPATCH_PATH_CONTROLLED_FALLBACK    = "canonical_fallback"
    DISPATCH_PATH_COMPAT_FALLBACK        = "compat_fallback"
    DISPATCH_PATH_LEGACY_BYPASS          = "legacy_bypass"

    ROUTE_MODE_CROSS_DEVICE              = "cross_device"
    ROUTE_MODE_COMPAT_FALLBACK           = "cross_device_compat_fallback"

    SUBSTRATE_CALLER_DEVICE_ROUTER       = "device_router.route_task"
    SUBSTRATE_CALLER_COMPAT              = "capability_orchestrator.compat_fallback"

Authority sentinels::

    CROSS_DEVICE_DISPATCH_BOUNDARY_CONTRACT
    CROSS_DEVICE_DISPATCH_PR02_SENTINEL
    CANONICAL_PATH_ONLY_FOR_NEW_WORK_POLICY
    DEVICE_ROUTER_NOT_A_POLICY_AUTHORITY_POLICY
    COMPAT_FALLBACK_NOT_PRIMARY_PATH_POLICY
    LEGACY_BYPASS_MUST_EMIT_WARNING_POLICY

Enumerations::

    DispatchPathCategory

Dataclasses::

    DispatchBoundaryClassification

Functions::

    classify_dispatch_call(dispatch_path, substrate_caller, route_mode)
        → DispatchBoundaryClassification
    is_canonical_dispatch(classification)
    is_controlled_fallback(classification)
    is_compat_fallback(classification)
    is_legacy_bypass(classification)
    get_boundary_contract_snapshot()
        → dict
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger("Galaxy.CrossDeviceDispatchBoundary")

# ---------------------------------------------------------------------------
# PR-02 boundary contract sentinels
# ---------------------------------------------------------------------------

CROSS_DEVICE_DISPATCH_BOUNDARY_CONTRACT: str = (
    "CROSS_DEVICE_DISPATCH::BOUNDARY_CONTRACT_V1 (PR-02): "
    "The canonical cross-device dispatch chain is "
    "CommandRouter.route_envelope() → DeviceRouter.route_task() → "
    "AgentBridge.handoff() [canonical_dispatch]. "
    "Controlled canonical fallback: DeviceRouter → CrossDeviceCoordinator "
    "when AgentBridge is unavailable [canonical_fallback]. "
    "Compat fallback: CapabilityOrchestrator builtin_cross_device → "
    "CrossDeviceCoordinator when DeviceRouter raises [compat_fallback]. "
    "Legacy bypass: direct CrossDeviceCoordinator calls without substrate "
    "caller [legacy_bypass] — fail-open with structured warning. "
    "Resolves GAP-517-001 / GAP-517-003."
)

CROSS_DEVICE_DISPATCH_PR02_SENTINEL: str = (
    "CROSS_DEVICE_DISPATCH::PR02_BOUNDARY_CONSOLIDATION: "
    "PR-02 consolidates cross-device dispatch boundary markers from "
    "device_router.py, cross_device_coordinator.py, "
    "capability_orchestrator.py, and command_router.py into a single "
    "importable source of truth.  All dispatch path string constants "
    "are now canonical here."
)

CANONICAL_PATH_ONLY_FOR_NEW_WORK_POLICY: str = (
    "POLICY::CANONICAL_PATH_ONLY_FOR_NEW_WORK: "
    "All new cross-device work MUST route through "
    "CommandRouter.route_envelope() (canonical_dispatch). "
    "compat_fallback and legacy_bypass paths are not valid for new code."
)

DEVICE_ROUTER_NOT_A_POLICY_AUTHORITY_POLICY: str = (
    "POLICY::DEVICE_ROUTER_NOT_A_POLICY_AUTHORITY: "
    "DeviceRouter is a transport substrate only.  "
    "It must not accumulate execution policy, planning, or control-plane "
    "responsibilities.  Policy decisions must remain in core/."
)

COMPAT_FALLBACK_NOT_PRIMARY_PATH_POLICY: str = (
    "POLICY::COMPAT_FALLBACK_NOT_PRIMARY_PATH: "
    "cross_device_compat_fallback (CapabilityOrchestrator path) is a "
    "resilience fallback retained for engineering value.  "
    "It must not be treated as the primary cross-device execution path."
)

LEGACY_BYPASS_MUST_EMIT_WARNING_POLICY: str = (
    "POLICY::LEGACY_BYPASS_MUST_EMIT_WARNING: "
    "Any direct call to CrossDeviceCoordinator.execute_cross_device_task() "
    "without a substrate caller MUST emit a structured LEGACY_DISPATCH "
    "warning and record an integrity event.  Fail-open behavior is "
    "intentional to avoid blocking existing integrations."
)

# ---------------------------------------------------------------------------
# Canonical dispatch path string constants
# These exact strings are used as values for the ``dispatch_path`` key in
# every cross-device task context dict.  They are the stable contract across
# DeviceRouter, CrossDeviceCoordinator, CapabilityOrchestrator, and
# CommandRouter.
# ---------------------------------------------------------------------------

DISPATCH_PATH_CANONICAL: str = "canonical_dispatch"
"""Dispatch path for the primary canonical cross-device route.

Set by ``DeviceRouter.route_task()`` when it determines the task requires
cross-device routing and the canonical chain is active.
"""

DISPATCH_PATH_CONTROLLED_FALLBACK: str = "canonical_fallback"
"""Dispatch path for the controlled canonical fallback.

Set by ``DeviceRouter.route_task()`` when it falls back to
``CrossDeviceCoordinator`` because ``AgentBridge`` is unavailable or
its import fails.  The substrate-caller contract is preserved.
"""

DISPATCH_PATH_COMPAT_FALLBACK: str = "compat_fallback"
"""Dispatch path for the compat fallback.

Set by ``CapabilityOrchestrator._execute_builtin()`` when it falls back from
``DeviceRouter.route_task()`` to ``CrossDeviceCoordinator`` due to a router
exception.  The route_mode is set to ``ROUTE_MODE_COMPAT_FALLBACK``.
"""

DISPATCH_PATH_LEGACY_BYPASS: str = "legacy_bypass"
"""Dispatch path for legacy bypass calls.

Set by ``CrossDeviceCoordinator.execute_cross_device_task()`` when it
detects a direct call without a canonical substrate caller.
"""

# ---------------------------------------------------------------------------
# Canonical route mode string constants
# These exact strings are used as values for the ``route_mode`` key.
# ---------------------------------------------------------------------------

ROUTE_MODE_CROSS_DEVICE: str = "cross_device"
"""Standard cross-device route mode set by the canonical path."""

ROUTE_MODE_COMPAT_FALLBACK: str = "cross_device_compat_fallback"
"""Route mode set by CapabilityOrchestrator compat fallback path."""

# ---------------------------------------------------------------------------
# Substrate caller string constants
# These exact strings identify who is calling CrossDeviceCoordinator.
# ---------------------------------------------------------------------------

SUBSTRATE_CALLER_DEVICE_ROUTER: str = "device_router.route_task"
"""Substrate caller string passed by DeviceRouter (canonical path)."""

SUBSTRATE_CALLER_COMPAT: str = "capability_orchestrator.compat_fallback"
"""Substrate caller string passed by CapabilityOrchestrator compat fallback."""

# ---------------------------------------------------------------------------
# DispatchPathCategory enum
# ---------------------------------------------------------------------------


class DispatchPathCategory(str, Enum):
    """Classification of a cross-device dispatch call into one of the four
    canonical boundary categories.

    Used by :func:`classify_dispatch_call` and exposed through
    :class:`DispatchBoundaryClassification`.
    """

    CANONICAL = "canonical_dispatch"
    """Primary canonical path.  CommandRouter → DeviceRouter → AgentBridge."""

    CONTROLLED_FALLBACK = "canonical_fallback"
    """Controlled canonical fallback.  DeviceRouter → CrossDeviceCoordinator
    when AgentBridge is unavailable."""

    COMPAT_FALLBACK = "compat_fallback"
    """Compat fallback.  CapabilityOrchestrator → CrossDeviceCoordinator
    when DeviceRouter raises."""

    LEGACY_BYPASS = "legacy_bypass"
    """Legacy bypass.  Direct CrossDeviceCoordinator call without substrate
    caller.  Fail-open with warning."""

    UNKNOWN = "unknown"
    """Path could not be classified.  Treated conservatively as legacy_bypass."""


# ---------------------------------------------------------------------------
# DispatchBoundaryClassification dataclass
# ---------------------------------------------------------------------------


@dataclass
class DispatchBoundaryClassification:
    """Result of classifying a single cross-device dispatch call.

    Returned by :func:`classify_dispatch_call`.
    """

    category: DispatchPathCategory
    """Which of the four boundary categories this call falls into."""

    dispatch_path: str
    """The raw ``dispatch_path`` string from context (may be empty)."""

    substrate_caller: str
    """The raw ``_substrate_caller`` string (may be empty)."""

    route_mode: str
    """The raw ``route_mode`` string (may be empty)."""

    is_canonical: bool = field(init=False)
    """True when category is CANONICAL or CONTROLLED_FALLBACK."""

    is_fallback: bool = field(init=False)
    """True when category is CONTROLLED_FALLBACK or COMPAT_FALLBACK."""

    policy_notes: str = field(default="", init=False)
    """Human-readable policy note for this category."""

    def __post_init__(self) -> None:
        self.is_canonical = self.category in (
            DispatchPathCategory.CANONICAL,
            DispatchPathCategory.CONTROLLED_FALLBACK,
        )
        self.is_fallback = self.category in (
            DispatchPathCategory.CONTROLLED_FALLBACK,
            DispatchPathCategory.COMPAT_FALLBACK,
        )
        self.policy_notes = _CATEGORY_POLICY_NOTES.get(self.category, "")

    def to_dict(self) -> Dict[str, object]:
        """Serialise to a plain dict for observability / audit / test."""
        return {
            "category": self.category.value,
            "dispatch_path": self.dispatch_path,
            "substrate_caller": self.substrate_caller,
            "route_mode": self.route_mode,
            "is_canonical": self.is_canonical,
            "is_fallback": self.is_fallback,
            "policy_notes": self.policy_notes,
        }


_CATEGORY_POLICY_NOTES: Dict[DispatchPathCategory, str] = {
    DispatchPathCategory.CANONICAL: (
        "Primary governed path.  Valid for all new cross-device work."
    ),
    DispatchPathCategory.CONTROLLED_FALLBACK: (
        "Sanctioned fallback from DeviceRouter when AgentBridge is "
        "unavailable.  Substrate-caller contract preserved."
    ),
    DispatchPathCategory.COMPAT_FALLBACK: (
        "Resilience fallback from CapabilityOrchestrator.  Retained for "
        "engineering value.  Not valid for new cross-device work."
    ),
    DispatchPathCategory.LEGACY_BYPASS: (
        "Direct CrossDeviceCoordinator call without substrate caller.  "
        "Fail-open.  Emits LEGACY_DISPATCH warning.  Must not be used in "
        "new code."
    ),
    DispatchPathCategory.UNKNOWN: (
        "Unclassified dispatch path.  Treated conservatively as legacy_bypass."
    ),
}

# ---------------------------------------------------------------------------
# Classification function
# ---------------------------------------------------------------------------


def classify_dispatch_call(
    dispatch_path: str = "",
    substrate_caller: str = "",
    route_mode: str = "",
) -> DispatchBoundaryClassification:
    """Classify a cross-device dispatch call into one of the four boundary
    categories.

    This function is pure and stateless.  It consumes the same three context
    keys that ``CrossDeviceCoordinator.execute_cross_device_task()`` uses
    internally to determine dispatch path, so its output is always consistent
    with runtime behavior.

    Parameters
    ----------
    dispatch_path:
        Value of ``context["dispatch_path"]`` (or empty if absent).
    substrate_caller:
        Value of ``_substrate_caller`` kwarg or ``context["_substrate_caller"]``
        (or empty if absent).
    route_mode:
        Value of ``context["route_mode"]`` (or empty if absent).

    Returns
    -------
    DispatchBoundaryClassification
        Fully-populated classification with ``is_canonical``, ``is_fallback``,
        and ``policy_notes`` set.
    """
    _dp = str(dispatch_path or "").strip()
    _caller = str(substrate_caller or "").strip()
    _rm = str(route_mode or "").strip()

    # 1. Explicit dispatch_path from context wins (set by DeviceRouter or
    #    CapabilityOrchestrator before the call reaches the coordinator).
    if _dp == DISPATCH_PATH_CANONICAL:
        category = DispatchPathCategory.CANONICAL
    elif _dp == DISPATCH_PATH_CONTROLLED_FALLBACK:
        category = DispatchPathCategory.CONTROLLED_FALLBACK
    elif _dp == DISPATCH_PATH_COMPAT_FALLBACK:
        category = DispatchPathCategory.COMPAT_FALLBACK
    elif _dp == DISPATCH_PATH_LEGACY_BYPASS:
        category = DispatchPathCategory.LEGACY_BYPASS

    # 2. No explicit dispatch_path — infer from substrate_caller (mirrors
    #    CrossDeviceCoordinator internal logic).
    elif _caller == SUBSTRATE_CALLER_DEVICE_ROUTER:
        # DeviceRouter canonical calls that didn't pre-set dispatch_path;
        # this is the controlled fallback scenario (bridge unavailable).
        category = DispatchPathCategory.CONTROLLED_FALLBACK
    elif _caller:
        # Has a caller but it's not the canonical DeviceRouter — compat.
        category = DispatchPathCategory.COMPAT_FALLBACK

    # 3. No dispatch_path, no caller → legacy bypass.
    else:
        category = DispatchPathCategory.LEGACY_BYPASS

    return DispatchBoundaryClassification(
        category=category,
        dispatch_path=_dp,
        substrate_caller=_caller,
        route_mode=_rm,
    )


# ---------------------------------------------------------------------------
# Convenience predicate helpers
# ---------------------------------------------------------------------------


def is_canonical_dispatch(clf: DispatchBoundaryClassification) -> bool:
    """Return True when the call follows the primary canonical path."""
    return clf.category == DispatchPathCategory.CANONICAL


def is_controlled_fallback(clf: DispatchBoundaryClassification) -> bool:
    """Return True when the call is a controlled canonical fallback."""
    return clf.category == DispatchPathCategory.CONTROLLED_FALLBACK


def is_compat_fallback(clf: DispatchBoundaryClassification) -> bool:
    """Return True when the call is a compat fallback."""
    return clf.category == DispatchPathCategory.COMPAT_FALLBACK


def is_legacy_bypass(clf: DispatchBoundaryClassification) -> bool:
    """Return True when the call is a legacy bypass."""
    return clf.category in (
        DispatchPathCategory.LEGACY_BYPASS,
        DispatchPathCategory.UNKNOWN,
    )


# ---------------------------------------------------------------------------
# Operator-facing boundary contract snapshot
# ---------------------------------------------------------------------------


def get_boundary_contract_snapshot() -> Dict[str, object]:
    """Return a stable dict snapshot of the dispatch boundary contract.

    This snapshot is consumed by:
    - Operator tooling / runtime-truth endpoints
    - Diagnostic surfaces
    - Integration test assertions

    The shape is stable across PRs.  Keys and their semantics are governed
    by ``CROSS_DEVICE_DISPATCH_BOUNDARY_CONTRACT``.
    """
    return {
        "boundary_version": "pr02_v1",
        "sentinel": CROSS_DEVICE_DISPATCH_BOUNDARY_CONTRACT,
        "dispatch_path_categories": {
            "canonical_dispatch": {
                "constant": DISPATCH_PATH_CANONICAL,
                "description": "Primary governed path via CommandRouter → DeviceRouter → AgentBridge",
                "valid_for_new_work": True,
                "substrate_callers": [SUBSTRATE_CALLER_DEVICE_ROUTER],
                "route_modes": [ROUTE_MODE_CROSS_DEVICE],
            },
            "canonical_fallback": {
                "constant": DISPATCH_PATH_CONTROLLED_FALLBACK,
                "description": "Controlled fallback: DeviceRouter → CrossDeviceCoordinator (AgentBridge unavailable)",
                "valid_for_new_work": True,
                "substrate_callers": [SUBSTRATE_CALLER_DEVICE_ROUTER],
                "route_modes": [ROUTE_MODE_CROSS_DEVICE],
            },
            "compat_fallback": {
                "constant": DISPATCH_PATH_COMPAT_FALLBACK,
                "description": "Resilience fallback: CapabilityOrchestrator → CrossDeviceCoordinator",
                "valid_for_new_work": False,
                "substrate_callers": [SUBSTRATE_CALLER_COMPAT],
                "route_modes": [ROUTE_MODE_COMPAT_FALLBACK],
            },
            "legacy_bypass": {
                "constant": DISPATCH_PATH_LEGACY_BYPASS,
                "description": "Direct CrossDeviceCoordinator call without substrate caller (fail-open with warning)",
                "valid_for_new_work": False,
                "substrate_callers": [],
                "route_modes": [],
            },
        },
        "canonical_chain": [
            "CommandRouter.route_envelope()",
            "DeviceRouter.route_task()",
            "AgentBridge.handoff() [preferred] or CrossDeviceCoordinator.execute_cross_device_task() [fallback]",
        ],
        "android_dispatch_contract": {
            "inbound_path": "AIP v3 WebSocket → android_bridge → CommandRouter",
            "outbound_path": "CommandRouter → DeviceRouter → WebSocket → Android",
            "handoff_result_path": "Android → HandoffEnvelopeV2 uplink → V2 ingress handler",
            "dispatch_path_context_key": "dispatch_path",
            "route_mode_context_key": "route_mode",
            "substrate_caller_context_key": "_substrate_caller",
        },
        "policies": {
            "CANONICAL_PATH_ONLY_FOR_NEW_WORK": CANONICAL_PATH_ONLY_FOR_NEW_WORK_POLICY,
            "DEVICE_ROUTER_NOT_A_POLICY_AUTHORITY": DEVICE_ROUTER_NOT_A_POLICY_AUTHORITY_POLICY,
            "COMPAT_FALLBACK_NOT_PRIMARY_PATH": COMPAT_FALLBACK_NOT_PRIMARY_PATH_POLICY,
            "LEGACY_BYPASS_MUST_EMIT_WARNING": LEGACY_BYPASS_MUST_EMIT_WARNING_POLICY,
        },
    }
