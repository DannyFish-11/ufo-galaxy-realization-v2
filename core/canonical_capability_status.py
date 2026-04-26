#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/canonical_capability_status.py
=====================================
Explicit runtime status classification for optional, experimental, and
structural-only capabilities.

Problem addressed
-----------------
The system contains several capabilities that exist as structural code but
are not activated in the default runtime.  Without explicit status
classification, these capabilities risk being misread as active mainline
capabilities — leading to incorrect system assessments and potential
dispatch to paths that are not operational.

This module provides:

1. :class:`CapabilityRuntimeStatus` — the canonical taxonomy of runtime
   statuses for any capability in the system.
2. :class:`CapabilityStatusRecord` — a named, serialisable record pairing
   a capability identifier with its current runtime status and evidence
   rationale.
3. :func:`get_canonical_capability_status_registry` — the authoritative
   registry of runtime statuses for all system capabilities, including
   optional/experimental/structural-only ones.
4. :func:`is_mainline_active` — quick predicate for "is this capability
   active mainline and safe to dispatch to?".
5. Policy sentinels that make the structural-vs-operational distinction
   machine-checkable.

Coverage
--------
The registry explicitly classifies the following capabilities (among others):

- **local_ai / on-device inference** — structural-only; not default-active.
- **webrtc** — experimental; not mainline.
- **mesh / federation** — structural-only; not mainline.
- **advanced_handoff** — experimental.
- **register / capability_report / task_assign / task_result** — active mainline.
- **heartbeat / reconnect / offline_queue** — active mainline.
- **cross_device_dispatch** — active mainline.

Design principles
-----------------
- **Additive only** — does not modify any other module.
- **Explicit over implicit** — every capability in scope is classified;
  absence from the registry is treated as ``unknown``, not ``active``.
- **Machine-checkable** — callers can test ``is_mainline_active(cap)``
  without parsing strings.
- **Extensible** — new capabilities can be added to the registry without
  touching existing entries.

Public API
----------
Sentinels::

    CAPABILITY_STATUS_REGISTRY_AUTHORITY
    STRUCTURAL_CAPABILITY_IS_NOT_OPERATIONAL_POLICY
    DISPATCH_ONLY_TO_ACTIVE_MAINLINE_CAPABILITIES_POLICY
    LOCAL_AI_IS_STRUCTURAL_ONLY_STATUS
    WEBRTC_IS_EXPERIMENTAL_STATUS
    MESH_FEDERATION_IS_STRUCTURAL_ONLY_STATUS

Enumerations::

    CapabilityRuntimeStatus

Data class::

    CapabilityStatusRecord

Functions::

    get_canonical_capability_status_registry()  -> dict[str, CapabilityStatusRecord]
    get_capability_status(cap_id)               -> CapabilityStatusRecord
    is_mainline_active(cap_id)                  -> bool
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger("Galaxy.CanonicalCapabilityStatus")

__all__ = [
    # Sentinels
    "CAPABILITY_STATUS_REGISTRY_AUTHORITY",
    "STRUCTURAL_CAPABILITY_IS_NOT_OPERATIONAL_POLICY",
    "DISPATCH_ONLY_TO_ACTIVE_MAINLINE_CAPABILITIES_POLICY",
    "LOCAL_AI_IS_STRUCTURAL_ONLY_STATUS",
    "WEBRTC_IS_EXPERIMENTAL_STATUS",
    "MESH_FEDERATION_IS_STRUCTURAL_ONLY_STATUS",
    # Enumeration
    "CapabilityRuntimeStatus",
    # Data class
    "CapabilityStatusRecord",
    # Functions
    "get_canonical_capability_status_registry",
    "get_capability_status",
    "is_mainline_active",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

CAPABILITY_STATUS_REGISTRY_AUTHORITY: str = (
    "CAPABILITY_STATUS_REGISTRY_AUTHORITY_V1: "
    "core.canonical_capability_status is the authoritative registry for "
    "runtime status classification of all capabilities in the system.  "
    "Callers that need to know whether a capability is active mainline, "
    "experimental, degraded, or structural-only MUST consult this module "
    "rather than making assumptions based on code structure alone."
)

STRUCTURAL_CAPABILITY_IS_NOT_OPERATIONAL_POLICY: str = (
    "POLICY::STRUCTURAL_CAPABILITY_IS_NOT_OPERATIONAL_V1: "
    "A capability that has structural code (classes, interfaces, endpoints) "
    "in the codebase is NOT necessarily operational at runtime.  "
    "Structural existence must not be interpreted as active capability unless "
    "the canonical status registry classifies that capability as "
    "CapabilityRuntimeStatus.ACTIVE_MAINLINE.  "
    "Capabilities classified as STRUCTURAL_ONLY, EXPERIMENTAL, DISABLED, "
    "or COMPATIBILITY_ONLY must not be treated as operational mainline "
    "capabilities for dispatch, assurance, or release readiness purposes."
)

DISPATCH_ONLY_TO_ACTIVE_MAINLINE_CAPABILITIES_POLICY: str = (
    "POLICY::DISPATCH_ONLY_TO_ACTIVE_MAINLINE_CAPABILITIES_V1: "
    "Canonical mainline dispatch (V2 → Android task_assign and related "
    "message types) must only route to capability paths whose runtime status "
    "is CapabilityRuntimeStatus.ACTIVE_MAINLINE.  Attempting to dispatch to "
    "an EXPERIMENTAL, STRUCTURAL_ONLY, DISABLED, or DEGRADED capability on "
    "the canonical mainline path is a policy violation."
)

LOCAL_AI_IS_STRUCTURAL_ONLY_STATUS: str = (
    "STATUS::LOCAL_AI_STRUCTURAL_ONLY_V1: "
    "Android local AI / on-device inference (local_ai, local_grounding, "
    "local_planner, on_device_inference) is classified as STRUCTURAL_ONLY. "
    "The default implementations are NoOp stubs that return errors without "
    "performing inference.  This capability is NOT active mainline and must "
    "not be treated as an operational capability until explicit activation "
    "and a passing integration test confirm otherwise."
)

WEBRTC_IS_EXPERIMENTAL_STATUS: str = (
    "STATUS::WEBRTC_EXPERIMENTAL_V1: "
    "WebRTC capability (webrtc, webrtc_task_lifecycle) is classified as "
    "EXPERIMENTAL.  WebRTC session establishment is not part of the canonical "
    "mainline dispatch path.  The webrtc_task_lifecycle module provides "
    "structural scaffolding for future integration but is not verified as "
    "operational in the current dual-repo runtime."
)

MESH_FEDERATION_IS_STRUCTURAL_ONLY_STATUS: str = (
    "STATUS::MESH_FEDERATION_STRUCTURAL_ONLY_V1: "
    "Mesh networking (mesh, mesh_coordinator) and federation "
    "(galaxy_federation) capabilities are classified as STRUCTURAL_ONLY.  "
    "These capabilities exist as structural scaffolding for future "
    "distributed architecture but are not activated in the current runtime.  "
    "They must not be counted as operational mainline capabilities."
)


# ---------------------------------------------------------------------------
# CapabilityRuntimeStatus
# ---------------------------------------------------------------------------


class CapabilityRuntimeStatus(str, Enum):
    """Canonical taxonomy of runtime statuses for system capabilities.

    Values
    ------
    ACTIVE_MAINLINE
        Capability is fully operational on the canonical mainline path.
        It is safe to dispatch to, assert for assurance, and include in
        release readiness signals.

    DEGRADED
        Capability is partially operational; some degradation or limitation
        is present.  May be used on mainline with reduced functionality.
        Should be logged and tracked.

    EXPERIMENTAL
        Capability exists and is partly functional but is not part of the
        canonical mainline path.  Must not be used for mainline dispatch
        or assurance without explicit gate promotion.

    DISABLED
        Capability code exists but is explicitly disabled in the current
        runtime configuration.  Must not be used for any dispatch.

    STRUCTURAL_ONLY
        Capability code exists (classes, interfaces, endpoints) but default
        runtime implementations are NoOp stubs or return errors.
        Not operational.  Must not be counted as active for any purpose.

    COMPATIBILITY_ONLY
        Capability exists solely for backward-compatibility with older
        protocol versions or legacy clients.  Not mainline.

    UNKNOWN
        Capability status has not been classified in the registry.
        Treat as non-mainline until classified.
    """

    ACTIVE_MAINLINE = "active_mainline"
    DEGRADED = "degraded"
    EXPERIMENTAL = "experimental"
    DISABLED = "disabled"
    STRUCTURAL_ONLY = "structural_only"
    COMPATIBILITY_ONLY = "compatibility_only"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# CapabilityStatusRecord
# ---------------------------------------------------------------------------


@dataclass
class CapabilityStatusRecord:
    """Named, serialisable record pairing a capability with its runtime status.

    Fields
    ------
    capability_id
        Canonical string identifier for the capability (e.g. ``"tap"``,
        ``"local_ai"``, ``"webrtc"``).
    status
        :class:`CapabilityRuntimeStatus` value.
    display_name
        Human-readable name.
    rationale
        Brief explanation of why this status was assigned.
    source_sentinel
        Optional sentinel string from the originating module confirming
        the status.
    """

    capability_id: str
    status: CapabilityRuntimeStatus
    display_name: str = ""
    rationale: str = ""
    source_sentinel: str = ""

    def to_dict(self) -> Dict:
        return {
            "capability_id": self.capability_id,
            "status": self.status.value if isinstance(self.status, CapabilityRuntimeStatus) else str(self.status),
            "display_name": self.display_name,
            "rationale": self.rationale,
            "source_sentinel": self.source_sentinel,
        }


# ---------------------------------------------------------------------------
# Canonical registry
# ---------------------------------------------------------------------------

_REGISTRY: Optional[Dict[str, CapabilityStatusRecord]] = None


def _build_registry() -> Dict[str, CapabilityStatusRecord]:
    """Build and return the canonical capability status registry."""
    records = [
        # --- Active mainline: canonical V2 ↔ Android path ---
        CapabilityStatusRecord(
            capability_id="register",
            status=CapabilityRuntimeStatus.ACTIVE_MAINLINE,
            display_name="Device Registration",
            rationale="device_register → device_register_ack is the canonical "
                      "connection establishment step, verified by transport harness.",
        ),
        CapabilityStatusRecord(
            capability_id="capability_report",
            status=CapabilityRuntimeStatus.ACTIVE_MAINLINE,
            display_name="Capability Report",
            rationale="capability_report → capability_report_ack is verified by "
                      "transport harness and persisted to the bridge.",
        ),
        CapabilityStatusRecord(
            capability_id="task_assign",
            status=CapabilityRuntimeStatus.ACTIVE_MAINLINE,
            display_name="Task Assignment",
            rationale="task_assign is the canonical V2→Android dispatch message, "
                      "verified by the full roundtrip E2E test.",
        ),
        CapabilityStatusRecord(
            capability_id="task_result",
            status=CapabilityRuntimeStatus.ACTIVE_MAINLINE,
            display_name="Task Result",
            rationale="task_result is the canonical Android→V2 result delivery, "
                      "verified by waiter-unblock tests.",
        ),
        CapabilityStatusRecord(
            capability_id="heartbeat",
            status=CapabilityRuntimeStatus.ACTIVE_MAINLINE,
            display_name="Heartbeat",
            rationale="heartbeat → heartbeat_ack keepalive is part of the "
                      "canonical connection lifecycle.",
        ),
        CapabilityStatusRecord(
            capability_id="tap",
            status=CapabilityRuntimeStatus.ACTIVE_MAINLINE,
            display_name="Touch: Tap",
            rationale="Canonical Android accessibility action; registered via "
                      "capability_report.",
        ),
        CapabilityStatusRecord(
            capability_id="swipe",
            status=CapabilityRuntimeStatus.ACTIVE_MAINLINE,
            display_name="Touch: Swipe",
            rationale="Canonical Android accessibility action.",
        ),
        CapabilityStatusRecord(
            capability_id="screenshot",
            status=CapabilityRuntimeStatus.ACTIVE_MAINLINE,
            display_name="Screenshot Capture",
            rationale="Canonical Android execution capability.",
        ),
        CapabilityStatusRecord(
            capability_id="input_text",
            status=CapabilityRuntimeStatus.ACTIVE_MAINLINE,
            display_name="Text Input",
            rationale="Canonical Android accessibility action.",
        ),
        CapabilityStatusRecord(
            capability_id="cross_device_dispatch",
            status=CapabilityRuntimeStatus.ACTIVE_MAINLINE,
            display_name="Cross-Device Dispatch",
            rationale="V2→Android task dispatch over WebSocket is the core "
                      "cross-device capability; verified by transport harness.",
        ),
        CapabilityStatusRecord(
            capability_id="reconnect",
            status=CapabilityRuntimeStatus.ACTIVE_MAINLINE,
            display_name="Reconnect / Session Continuity",
            rationale="Reconnect path is tested in protocol regression suite.",
        ),
        CapabilityStatusRecord(
            capability_id="offline_queue",
            status=CapabilityRuntimeStatus.ACTIVE_MAINLINE,
            display_name="Offline Queue / Replay",
            rationale="Offline queue / replay path is tested in protocol regression suite.",
        ),
        # --- Experimental ---
        CapabilityStatusRecord(
            capability_id="webrtc",
            status=CapabilityRuntimeStatus.EXPERIMENTAL,
            display_name="WebRTC",
            rationale="WebRTC session establishment exists as structural scaffolding "
                      "but is not part of the canonical mainline dispatch path.  "
                      "Not verified as operational in the current runtime.",
            source_sentinel=WEBRTC_IS_EXPERIMENTAL_STATUS,
        ),
        CapabilityStatusRecord(
            capability_id="webrtc_task_lifecycle",
            status=CapabilityRuntimeStatus.EXPERIMENTAL,
            display_name="WebRTC Task Lifecycle",
            rationale="Structural scaffolding for WebRTC-backed task lifecycle. "
                      "Not operational on canonical mainline path.",
            source_sentinel=WEBRTC_IS_EXPERIMENTAL_STATUS,
        ),
        CapabilityStatusRecord(
            capability_id="advanced_handoff",
            status=CapabilityRuntimeStatus.EXPERIMENTAL,
            display_name="Advanced Handoff",
            rationale="Advanced cross-device handoff (beyond canonical task_assign "
                      "path) is structural/experimental.  Not mainline.",
        ),
        # --- Structural only ---
        CapabilityStatusRecord(
            capability_id="local_ai",
            status=CapabilityRuntimeStatus.STRUCTURAL_ONLY,
            display_name="Android Local AI / On-Device Inference",
            rationale="Default implementations are NoOp stubs that return errors "
                      "without performing inference.  Devices do not register with "
                      "local_ai unless explicitly configured and a model is loaded.  "
                      "Must not be treated as active capability.",
            source_sentinel=LOCAL_AI_IS_STRUCTURAL_ONLY_STATUS,
        ),
        CapabilityStatusRecord(
            capability_id="local_grounding",
            status=CapabilityRuntimeStatus.STRUCTURAL_ONLY,
            display_name="Android Local Grounding",
            rationale="LocalGroundingService defaults to NoOpGroundingService. "
                      "Not operational by default.",
            source_sentinel=LOCAL_AI_IS_STRUCTURAL_ONLY_STATUS,
        ),
        CapabilityStatusRecord(
            capability_id="local_planner",
            status=CapabilityRuntimeStatus.STRUCTURAL_ONLY,
            display_name="Android Local Planner",
            rationale="LocalPlannerService defaults to NoOp. Not operational by default.",
            source_sentinel=LOCAL_AI_IS_STRUCTURAL_ONLY_STATUS,
        ),
        CapabilityStatusRecord(
            capability_id="on_device_inference",
            status=CapabilityRuntimeStatus.STRUCTURAL_ONLY,
            display_name="On-Device Inference",
            rationale="On-device inference (LocalInferenceRuntimeManager) is "
                      "structural scaffolding.  Not operational by default.",
            source_sentinel=LOCAL_AI_IS_STRUCTURAL_ONLY_STATUS,
        ),
        CapabilityStatusRecord(
            capability_id="mesh",
            status=CapabilityRuntimeStatus.STRUCTURAL_ONLY,
            display_name="Mesh Networking",
            rationale="Mesh networking (mesh_coordinator) exists as structural "
                      "scaffolding for future distributed architecture.  "
                      "Not activated in the current runtime.",
            source_sentinel=MESH_FEDERATION_IS_STRUCTURAL_ONLY_STATUS,
        ),
        CapabilityStatusRecord(
            capability_id="federation",
            status=CapabilityRuntimeStatus.STRUCTURAL_ONLY,
            display_name="Galaxy Federation",
            rationale="Galaxy federation (galaxy_federation) is structural "
                      "scaffolding.  Not activated in the current runtime.",
            source_sentinel=MESH_FEDERATION_IS_STRUCTURAL_ONLY_STATUS,
        ),
        CapabilityStatusRecord(
            capability_id="mesh_participation",
            status=CapabilityRuntimeStatus.STRUCTURAL_ONLY,
            display_name="Mesh Participation",
            rationale="Structural-only; not activated in the current runtime.",
            source_sentinel=MESH_FEDERATION_IS_STRUCTURAL_ONLY_STATUS,
        ),
    ]

    return {rec.capability_id: rec for rec in records}


def get_canonical_capability_status_registry() -> Dict[str, CapabilityStatusRecord]:
    """Return the canonical capability status registry (singleton).

    Returns
    -------
    dict[str, CapabilityStatusRecord]
        Mapping of capability_id → :class:`CapabilityStatusRecord`.
    """
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


def get_capability_status(capability_id: str) -> CapabilityStatusRecord:
    """Look up the runtime status for a capability.

    Returns a record with :attr:`CapabilityRuntimeStatus.UNKNOWN` when
    the capability is not in the registry.

    Parameters
    ----------
    capability_id:
        Canonical capability identifier string.

    Returns
    -------
    CapabilityStatusRecord
    """
    registry = get_canonical_capability_status_registry()
    if capability_id in registry:
        return registry[capability_id]
    return CapabilityStatusRecord(
        capability_id=capability_id,
        status=CapabilityRuntimeStatus.UNKNOWN,
        display_name=capability_id,
        rationale="Not classified in the canonical capability status registry.",
    )


def is_mainline_active(capability_id: str) -> bool:
    """Return ``True`` iff the capability is classified as ACTIVE_MAINLINE.

    Parameters
    ----------
    capability_id:
        Canonical capability identifier string.

    Returns
    -------
    bool
        ``True`` only when status is :attr:`CapabilityRuntimeStatus.ACTIVE_MAINLINE`.
    """
    return get_capability_status(capability_id).status == CapabilityRuntimeStatus.ACTIVE_MAINLINE
