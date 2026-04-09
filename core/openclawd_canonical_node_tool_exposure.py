#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/openclawd_canonical_node_tool_exposure.py
===============================================
PR-10: Remove OpenClawd Legacy Layer 3 Node Discovery —
Make Canonical Node Tool Exposure Registry-Only.

This module is the **canonical authority** for defining the boundary between
the canonical OpenClawd node-tool-exposure path and all legacy Layer 3 node
discovery paths that previously read from deprecated metadata sources.

Problem addressed
-----------------
Prior to PR-10, OpenClawd's ``_collect_tools()`` method contained a legacy
"Layer 3" node discovery block that:

1. **Read from** ``config/node_registry.json`` — a deprecated static metadata
   file that has no runtime awareness, no governance filtering, and no
   architectural-class enforcement.

2. **Scanned** ``nodes/<key>/fusion_entry.py`` directly — bypassing
   :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry` and the
   governance eligibility layer to infer which actions a node exposes.

Both of these discovery paths operated as *peer authorities* alongside the
canonical capability/tool-exposure path, meaning the system had two competing
definitions of what node tools exist:

* **Canonical** — tools sourced from
  ``NodeFabricRegistry → sync_capabilities_to_registry()
  → CapabilityRegistry → CapabilityResolver(CapabilitySource.NODE)``

* **Legacy** — tools sourced from ``config/node_registry.json`` and direct
  ``fusion_entry.py`` filesystem scans.

Even when canonical node tool exposure was already available, the legacy scan
still executed and was only deduplicated after the fact.

This module makes the architectural boundary explicit and programmatically
enforceable.

Canonical node tool exposure path
----------------------------------
The single canonical path for all OpenClawd node tool exposure is::

    NodeFabricRegistry.sync_capabilities_to_registry()
    → CapabilityRegistry (source="node", name="node__<id>__<action>")
    → CapabilityResolver.collect_tool_schemas(CapabilitySource.NODE)
    → OpenClawd._collect_tools()

Only healthy ``CAPABILITY_NODE`` nodes pass through this path.
``SERVICE_NODE``, ``LEGACY_ORCHESTRATOR_NODE``, ``EXPERIMENTAL_NODE``, and
``ARCHIVED_NODE`` are excluded by the NodeFabricRegistry governance eligibility
filter (``CAPABILITY_SYNC_ELIGIBLE``).

Legacy paths demoted by this module
-------------------------------------
+--------------------------------------------+-------------------------------+----------------------+
| Legacy surface                             | Status after PR-10            | Canonical alternative|
+============================================+===============================+======================+
| ``config/node_registry.json`` reads        | REMOVED_FROM_CANONICAL_PATH   | NodeFabricRegistry   |
| ``fusion_entry.py`` direct fs scan         | REMOVED_FROM_CANONICAL_PATH   | NodeFabricRegistry   |
| Layer 3 ``_CORE_NODE_ACTIONS`` static dict | COMPAT_ONLY (behind flag)     | NodeFabricRegistry   |
| ``_discover_node_actions()`` dynamic scan  | COMPAT_ONLY (behind flag)     | NodeFabricRegistry   |
+--------------------------------------------+-------------------------------+----------------------+

Compatibility
-------------
If a compat fallback is ever re-enabled, it must be isolated behind the
explicit ``OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED`` flag (default
``False``) and must not silently function as a peer authority.

Public API
----------
Authority sentinels::

    OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_IS_AUTHORITY
    OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_PR10_SENTINEL

Policy sentinels::

    CANONICAL_NODE_TOOLS_COME_FROM_RUNTIME_REGISTRY_ONLY_POLICY
    NODE_REGISTRY_JSON_IS_NOT_TOOL_EXPOSURE_AUTHORITY_POLICY
    FUSION_ENTRY_SCAN_IS_NOT_TOOL_EXPOSURE_AUTHORITY_POLICY
    LEGACY_LAYER3_IS_COMPAT_ONLY_POLICY
    CANONICAL_TOOL_EXPOSURE_REQUIRES_GOVERNANCE_FILTER_POLICY

Enum::

    LegacyNodeDiscoveryStatus

Dataclasses::

    LegacyNodeDiscoverySurface
    CanonicalNodeToolExposureSnapshot

Functions::

    build_legacy_discovery_surface_registry()
    get_legacy_discovery_summary()
    is_legacy_node_scan_compat_enabled()
    build_canonical_tool_exposure_snapshot()
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.OpenClawd.CanonicalNodeToolExposure")

# ===========================================================================
# Authority sentinels
# ===========================================================================

OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_IS_AUTHORITY: str = (
    "OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE::PR10_AUTHORITY_V1: "
    "core/openclawd_canonical_node_tool_exposure.py is the canonical authority "
    "for defining the boundary between canonical OpenClawd node-tool-exposure "
    "and all legacy Layer 3 node-discovery paths.  The single canonical path for "
    "node tool exposure is: NodeFabricRegistry → sync_capabilities_to_registry() "
    "→ CapabilityRegistry → CapabilityResolver(CapabilitySource.NODE).  "
    "config/node_registry.json reads and direct fusion_entry.py filesystem scans "
    "are removed from the canonical tool-exposure path.  Any remaining compat "
    "surface is explicitly isolated behind OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED "
    "(default False) and is non-canonical by design."
)

OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_PR10_SENTINEL: str = (
    "OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE::PR10_SENTINEL_V1"
)

# ===========================================================================
# Policy sentinels
# ===========================================================================

CANONICAL_NODE_TOOLS_COME_FROM_RUNTIME_REGISTRY_ONLY_POLICY: str = (
    "OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE::CANONICAL_REGISTRY_ONLY_POLICY_V1: "
    "All OpenClawd node tool exposure must originate from the canonical runtime "
    "registry path: NodeFabricRegistry.sync_capabilities_to_registry() feeds "
    "CapabilityRegistry, which is consumed by CapabilityResolver.  No other source "
    "may act as a node tool authority in canonical tool collection."
)

NODE_REGISTRY_JSON_IS_NOT_TOOL_EXPOSURE_AUTHORITY_POLICY: str = (
    "OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE::NO_REGISTRY_JSON_AUTHORITY_POLICY_V1: "
    "config/node_registry.json must not be read as part of canonical OpenClawd node "
    "tool exposure.  It is a deprecated static metadata file with no runtime "
    "awareness, no governance filtering, and no architectural-class enforcement.  "
    "Any remaining read of this file in _collect_tools() is a compatibility-only "
    "fallback and must be explicitly gated behind the compat flag."
)

FUSION_ENTRY_SCAN_IS_NOT_TOOL_EXPOSURE_AUTHORITY_POLICY: str = (
    "OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE::NO_FUSION_ENTRY_SCAN_POLICY_V1: "
    "Direct filesystem scanning of nodes/<key>/fusion_entry.py to discover node "
    "actions is not permitted in canonical OpenClawd node tool exposure.  "
    "fusion_entry.py is an execution-adapter-only file (per PR-5 / "
    "FUSION_ENTRY_ADAPTER_CONTRACT_PR5_SENTINEL).  Action discovery must go "
    "through NodeFabricRegistry → CapabilityRegistry."
)

LEGACY_LAYER3_IS_COMPAT_ONLY_POLICY: str = (
    "OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE::LEGACY_LAYER3_COMPAT_ONLY_POLICY_V1: "
    "The legacy Layer 3 node-discovery block in OpenClawd._collect_tools() "
    "(_CORE_NODE_ACTIONS static dict, _node_registry.json scan, and "
    "_discover_node_actions() dynamic fusion_entry scan) is demoted to "
    "compatibility-only status.  It must not execute by default.  It may only be "
    "re-enabled by setting OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED=true in the "
    "environment, and even then it is explicitly non-canonical.  Diagnostics must "
    "log a warning whenever the compat path is active."
)

CANONICAL_TOOL_EXPOSURE_REQUIRES_GOVERNANCE_FILTER_POLICY: str = (
    "OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE::GOVERNANCE_FILTER_REQUIRED_POLICY_V1: "
    "Canonical node tool exposure must only surface nodes that pass the "
    "NodeFabricRegistry governance eligibility filter (CAPABILITY_SYNC_ELIGIBLE).  "
    "Only CAPABILITY_NODE architectural class nodes are eligible for canonical tool "
    "exposure.  SERVICE_NODE, LEGACY_ORCHESTRATOR_NODE, EXPERIMENTAL_NODE, and "
    "ARCHIVED_NODE architectural classes must never appear in the canonical OpenClawd "
    "tool list."
)

# ===========================================================================
# Compat flag
# ===========================================================================

#: Environment variable name that gates the legacy Layer 3 compat path.
OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENV_VAR: str = "OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED"


def is_legacy_node_scan_compat_enabled() -> bool:
    """Return ``True`` only if the legacy Layer 3 compat path is explicitly
    opted-in via the environment.

    Default is ``False`` — legacy scan is **disabled** by default after PR-10.
    Set ``OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENABLED`` to any of the following
    truthy values to re-enable the compat path:
    ``"true"``, ``"1"``, ``"yes"``, ``"on"``.

    Re-enabling the compat path is not recommended; it is non-canonical and
    will be removed in a future cleanup pass.
    """
    val = os.environ.get(OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENV_VAR, "").strip().lower()
    return val in ("1", "true", "yes", "on")


# ===========================================================================
# Enum: legacy surface status
# ===========================================================================

class LegacyNodeDiscoveryStatus(str, Enum):
    """Lifecycle status for a legacy Layer 3 node-discovery surface."""

    REMOVED_FROM_CANONICAL_PATH = "removed_from_canonical_path"
    """Surface has been removed from the canonical ``_collect_tools()`` path.
    It may still exist in code for compat purposes but is not executed by
    default."""

    COMPAT_ONLY = "compat_only"
    """Surface is retained solely for backward-compatibility behind an explicit
    opt-in flag.  It is non-canonical and does not act as a peer tool-exposure
    authority."""

    DEPRECATED = "deprecated"
    """Surface is deprecated and will be removed in a future pass."""


# ===========================================================================
# Dataclass: per-surface descriptor
# ===========================================================================

@dataclass
class LegacyNodeDiscoverySurface:
    """Describes a single legacy Layer 3 node-discovery surface and its status
    after PR-10.
    """

    name: str
    """Short identifier for the surface (e.g. ``'node_registry_json_read'``)."""

    status: LegacyNodeDiscoveryStatus
    """Status after PR-10 treatment."""

    description: str
    """Human-readable description of what this surface did and why it is
    demoted."""

    canonical_replacement: str
    """The canonical path that replaces this surface."""

    is_compat_flag_gated: bool = False
    """Whether this surface can be re-enabled via
    :data:`OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENV_VAR`."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "description": self.description,
            "canonical_replacement": self.canonical_replacement,
            "is_compat_flag_gated": self.is_compat_flag_gated,
        }


# ===========================================================================
# Dataclass: snapshot
# ===========================================================================

@dataclass
class CanonicalNodeToolExposureSnapshot:
    """Point-in-time snapshot of the canonical node tool exposure state."""

    legacy_surfaces: List[LegacyNodeDiscoverySurface] = field(default_factory=list)
    compat_enabled: bool = False
    canonical_path_active: bool = True
    pr10_sentinel: str = OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE_PR10_SENTINEL

    @property
    def removed_surface_count(self) -> int:
        return sum(
            1 for s in self.legacy_surfaces
            if s.status == LegacyNodeDiscoveryStatus.REMOVED_FROM_CANONICAL_PATH
        )

    @property
    def compat_surface_count(self) -> int:
        return sum(
            1 for s in self.legacy_surfaces
            if s.status == LegacyNodeDiscoveryStatus.COMPAT_ONLY
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "legacy_surfaces": [s.to_dict() for s in self.legacy_surfaces],
            "removed_surface_count": self.removed_surface_count,
            "compat_surface_count": self.compat_surface_count,
            "compat_enabled": self.compat_enabled,
            "canonical_path_active": self.canonical_path_active,
            "pr10_sentinel": self.pr10_sentinel,
        }


# ===========================================================================
# Legacy surface catalogue
# ===========================================================================

#: Canonical catalogue of all legacy Layer 3 surfaces demoted by PR-10.
_LEGACY_DISCOVERY_SURFACES: List[LegacyNodeDiscoverySurface] = [
    LegacyNodeDiscoverySurface(
        name="node_registry_json_read",
        status=LegacyNodeDiscoveryStatus.REMOVED_FROM_CANONICAL_PATH,
        description=(
            "OpenClawd._collect_tools() Layer 3 previously read "
            "config/node_registry.json to build a node_id→node_key mapping "
            "and node display names.  This file is a deprecated static "
            "metadata source with no runtime awareness and no governance "
            "filtering.  Reading it as a tool-exposure authority created a "
            "parallel node-list definition that could diverge from the "
            "canonical NodeFabricRegistry state."
        ),
        canonical_replacement=(
            "NodeFabricRegistry.list_nodes() / get_node_fabric_registry()"
        ),
        is_compat_flag_gated=True,
    ),
    LegacyNodeDiscoverySurface(
        name="fusion_entry_dynamic_scan",
        status=LegacyNodeDiscoveryStatus.REMOVED_FROM_CANONICAL_PATH,
        description=(
            "OpenClawd._discover_node_actions() scanned nodes/<key>/fusion_entry.py "
            "directly to discover available actions by loading the module and "
            "calling help/status.  This bypassed NodeFabricRegistry entirely and "
            "used fusion_entry.py as a node-action-discovery authority, which "
            "violates PR-5 (FUSION_ENTRY_ADAPTER_CONTRACT_PR5_SENTINEL): "
            "fusion_entry.py is an execution-adapter-only file, not a registry "
            "or discovery authority."
        ),
        canonical_replacement=(
            "NodeFabricRegistry → sync_capabilities_to_registry() "
            "→ CapabilityRegistry → CapabilityResolver(CapabilitySource.NODE)"
        ),
        is_compat_flag_gated=True,
    ),
    LegacyNodeDiscoverySurface(
        name="core_node_actions_static_dict",
        status=LegacyNodeDiscoveryStatus.COMPAT_ONLY,
        description=(
            "OpenClawd._CORE_NODE_ACTIONS is a hardcoded static dict mapping "
            "node_id to {action_name: description}.  It was used as a fallback "
            "when fusion_entry discovery failed or was not available.  It "
            "provided a fixed snapshot that could become stale and diverge from "
            "the runtime-registered capabilities."
        ),
        canonical_replacement=(
            "NodeFabricRegistry.sync_capabilities_to_registry() pushes "
            "live capability entries for all healthy CAPABILITY_NODE nodes."
        ),
        is_compat_flag_gated=True,
    ),
]


def build_legacy_discovery_surface_registry() -> List[LegacyNodeDiscoverySurface]:
    """Return the complete catalogue of legacy Layer 3 node-discovery surfaces
    demoted by PR-10.
    """
    return list(_LEGACY_DISCOVERY_SURFACES)


# ===========================================================================
# Snapshot / summary helpers
# ===========================================================================

def build_canonical_tool_exposure_snapshot() -> CanonicalNodeToolExposureSnapshot:
    """Build a :class:`CanonicalNodeToolExposureSnapshot` reflecting the
    current state of canonical node tool exposure after PR-10.
    """
    compat_enabled = is_legacy_node_scan_compat_enabled()
    if compat_enabled:
        logger.warning(
            "OPENCLAWD_CANONICAL_NODE_TOOL_EXPOSURE: Legacy Layer 3 compat path "
            "is ENABLED via %s.  This path is non-canonical and should only be "
            "used for temporary backward-compatibility.  The canonical node tool "
            "exposure path is: NodeFabricRegistry → CapabilityRegistry → "
            "CapabilityResolver(CapabilitySource.NODE).",
            OPENCLAWD_LEGACY_NODE_SCAN_COMPAT_ENV_VAR,
        )
    return CanonicalNodeToolExposureSnapshot(
        legacy_surfaces=build_legacy_discovery_surface_registry(),
        compat_enabled=compat_enabled,
        canonical_path_active=True,
    )


def get_legacy_discovery_summary() -> Dict[str, Any]:
    """Return a summary dict suitable for diagnostics / projection endpoints."""
    snapshot = build_canonical_tool_exposure_snapshot()
    return {
        "pr10_sentinel": snapshot.pr10_sentinel,
        "canonical_path_active": snapshot.canonical_path_active,
        "compat_enabled": snapshot.compat_enabled,
        "legacy_surface_count": len(snapshot.legacy_surfaces),
        "removed_surface_count": snapshot.removed_surface_count,
        "compat_surface_count": snapshot.compat_surface_count,
        "surfaces": [s.to_dict() for s in snapshot.legacy_surfaces],
        "policy": {
            "canonical_only": CANONICAL_NODE_TOOLS_COME_FROM_RUNTIME_REGISTRY_ONLY_POLICY,
            "no_registry_json": NODE_REGISTRY_JSON_IS_NOT_TOOL_EXPOSURE_AUTHORITY_POLICY,
            "no_fusion_entry_scan": FUSION_ENTRY_SCAN_IS_NOT_TOOL_EXPOSURE_AUTHORITY_POLICY,
            "legacy_layer3_compat_only": LEGACY_LAYER3_IS_COMPAT_ONLY_POLICY,
            "governance_filter_required": CANONICAL_TOOL_EXPOSURE_REQUIRES_GOVERNANCE_FILTER_POLICY,
        },
    }
