#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Peripheral capability-layer ingress boundary declaration (PR-10V2).

This module explicitly classifies real existing surfaces so desktop/shell,
multimodal, continuation, and bridge-linked capabilities remain ingress/
adapter layers instead of parallel runtime/governance authorities.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Tuple

PERIPHERAL_CAPABILITY_BOUNDARY_AUTHORITY: str = (
    "core.peripheral_capability_boundary::PR10V2::outer-capability-ingress-boundary"
)
PERIPHERAL_CAPABILITY_BOUNDARY_PR10V2_SENTINEL: str = (
    "peripheral_capability_boundary_pr10v2_boundary_locked"
)

PERIPHERAL_LAYERS_ARE_INGRESS_NOT_RUNTIME_AUTHORITY_POLICY: str = (
    "desktop/shell/multimodal/continuation/bridge-adapter layers are ingress or "
    "handoff surfaces; they MUST NOT claim parallel runtime-mainline authority"
)
SPECIALISTS_AS_TOOLS_SUBLAYER_NOT_PARALLEL_MAINLINE_POLICY: str = (
    "specialists-as-tools sub-layer remains tool execution sub-layer under canonical "
    "runtime chain; not a new parallel main control chain"
)
OUTWARD_PROJECTION_OPERATOR_ARE_CONSUMERS_NOT_GOVERNANCE_POLICY: str = (
    "projection/operator surfaces consume and render runtime truth; they must not "
    "redefine governance or truth authority"
)
ANDROID_LINK_MUST_FLOW_THROUGH_CANONICAL_CHAIN_POLICY: str = (
    "android participation is first-class runtime host participation, but ingress/bridge "
    "signals must flow through canonical V2 runtime chain authorities"
)
NO_NEW_PARALLEL_PERIPHERAL_RUNTIME_POLICY: str = (
    "no new parallel peripheral runtime framework/control center may be introduced"
)


class PeripheralCapabilityRole(str, Enum):
    runtime_mainline_authority = "runtime_mainline_authority"
    specialists_as_tools_sublayer = "specialists_as_tools_sublayer"
    peripheral_capability_ingress = "peripheral_capability_ingress"
    outward_projection_operator_surface = "outward_projection_operator_surface"


@dataclass(frozen=True)
class PeripheralCapabilitySurface:
    surface_id: str
    module_path: str
    role: PeripheralCapabilityRole
    may_not_claim_runtime_authority: bool
    notes: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "surface_id": self.surface_id,
            "module_path": self.module_path,
            "role": self.role.value,
            "may_not_claim_runtime_authority": self.may_not_claim_runtime_authority,
            "notes": self.notes,
        }


PERIPHERAL_CAPABILITY_SURFACE_REGISTRY: List[PeripheralCapabilitySurface] = [
    PeripheralCapabilitySurface(
        surface_id="desktop_runtime_shell",
        module_path="core.desktop_presence_runtime",
        role=PeripheralCapabilityRole.runtime_mainline_authority,
        may_not_claim_runtime_authority=False,
        notes="Runtime shell is canonical entry shell in main chain; not parallel control center.",
    ),
    PeripheralCapabilitySurface(
        surface_id="openclawd_subject",
        module_path="core.openclawd",
        role=PeripheralCapabilityRole.runtime_mainline_authority,
        may_not_claim_runtime_authority=False,
        notes="Canonical runtime subject core.",
    ),
    PeripheralCapabilitySurface(
        surface_id="command_router",
        module_path="core.command_router",
        role=PeripheralCapabilityRole.runtime_mainline_authority,
        may_not_claim_runtime_authority=False,
        notes="Canonical orchestration authority.",
    ),
    PeripheralCapabilitySurface(
        surface_id="device_router",
        module_path="galaxy_gateway.device_router",
        role=PeripheralCapabilityRole.runtime_mainline_authority,
        may_not_claim_runtime_authority=False,
        notes="Canonical dispatch authority and transport session owner.",
    ),
    PeripheralCapabilitySurface(
        surface_id="specialist_kernel",
        module_path="core.agent.kernel",
        role=PeripheralCapabilityRole.specialists_as_tools_sublayer,
        may_not_claim_runtime_authority=True,
        notes="Specialists-as-tools execution helper, not runtime mainline authority.",
    ),
    PeripheralCapabilitySurface(
        surface_id="specialist_execution_planner",
        module_path="core.agent.execution_planner",
        role=PeripheralCapabilityRole.specialists_as_tools_sublayer,
        may_not_claim_runtime_authority=True,
        notes="Tool planning helper under specialists-as-tools sub-layer.",
    ),
    PeripheralCapabilitySurface(
        surface_id="specialist_agent_team",
        module_path="core.agent_team",
        role=PeripheralCapabilityRole.specialists_as_tools_sublayer,
        may_not_claim_runtime_authority=True,
        notes="Expert/tool team execution sub-layer, not parallel governance.",
    ),
    PeripheralCapabilitySurface(
        surface_id="multimodal_ingest_runtime",
        module_path="core.multimodal.ingest_runtime",
        role=PeripheralCapabilityRole.peripheral_capability_ingress,
        may_not_claim_runtime_authority=True,
        notes="Shell-owned multimodal ingress bus runtime (continuous host perception ingress).",
    ),
    PeripheralCapabilitySurface(
        surface_id="multimodal_ingress_bus",
        module_path="core.multimodal.ingress_bus",
        role=PeripheralCapabilityRole.peripheral_capability_ingress,
        may_not_claim_runtime_authority=True,
        notes="Ingress bus transport for multimodal shell sensing; not governance authority.",
    ),
    PeripheralCapabilitySurface(
        surface_id="continuation_rebind_registry",
        module_path="core.continuation_rebind_registry",
        role=PeripheralCapabilityRole.peripheral_capability_ingress,
        may_not_claim_runtime_authority=True,
        notes="Continuation/waiter rebind support surface; continuity adapter not control center.",
    ),
    PeripheralCapabilitySurface(
        surface_id="android_bridge",
        module_path="galaxy_gateway.android_bridge",
        role=PeripheralCapabilityRole.peripheral_capability_ingress,
        may_not_claim_runtime_authority=True,
        notes="Android protocol/action adapter and handoff ingress bridge.",
    ),
    PeripheralCapabilitySurface(
        surface_id="runtime_projection_routes",
        module_path="core.routes.projection",
        role=PeripheralCapabilityRole.outward_projection_operator_surface,
        may_not_claim_runtime_authority=True,
        notes="Board/operator projection surface consumes runtime truth outward.",
    ),
    PeripheralCapabilitySurface(
        surface_id="operator_action_governance_surface",
        module_path="core.pr4_operator_action_governance",
        role=PeripheralCapabilityRole.outward_projection_operator_surface,
        may_not_claim_runtime_authority=True,
        notes="Operator-visible governance interpretation/output surface.",
    ),
]


def get_peripheral_capability_surface_registry() -> List[PeripheralCapabilitySurface]:
    return list(PERIPHERAL_CAPABILITY_SURFACE_REGISTRY)


def classify_peripheral_capability_surface(module_path_or_surface_id: str) -> str:
    needle = str(module_path_or_surface_id or "").strip()
    if not needle:
        return "unknown"
    for surface in PERIPHERAL_CAPABILITY_SURFACE_REGISTRY:
        if needle == surface.surface_id or needle == surface.module_path:
            return surface.role.value
    return "unknown"


def get_surfaces_by_peripheral_role(role: PeripheralCapabilityRole) -> List[PeripheralCapabilitySurface]:
    return [s for s in PERIPHERAL_CAPABILITY_SURFACE_REGISTRY if s.role == role]


def get_android_v2_link_surfaces() -> Tuple[str, ...]:
    return (
        "galaxy_gateway.android_bridge",
        "galaxy_gateway.device_router",
        "core.android_runtime_dispatch_binding",
        "android.GalaxyWebSocketClient",
        "android.GalaxyConnectionService",
        "android.RuntimeController",
    )


def build_capability_registry_ingress_contract() -> Dict[str, object]:
    return {
        "surface_id": "capability_registry_ingress",
        "module_path": "core.agent.capability_registry.CapabilityRegistry",
        "role": "capability_ingress_surface",
        "may_not_claim_runtime_authority": True,
        "runtime_mainline_authority": [
            "core.desktop_presence_runtime.DesktopPresenceRuntime",
            "core.openclawd.OpenClawd",
            "core.command_router.CommandRouter",
            "galaxy_gateway.device_router.DeviceRouter",
        ],
        "specialists_as_tools_relation": "capability catalog serves tool sub-layer, not vice versa",
        "android_link_surface": list(get_android_v2_link_surfaces()),
    }


def build_peripheral_capability_boundary_snapshot() -> Dict[str, object]:
    surfaces = [s.to_dict() for s in PERIPHERAL_CAPABILITY_SURFACE_REGISTRY]
    by_role: Dict[str, int] = {}
    constrained: List[str] = []
    for surface in PERIPHERAL_CAPABILITY_SURFACE_REGISTRY:
        by_role[surface.role.value] = by_role.get(surface.role.value, 0) + 1
        if surface.may_not_claim_runtime_authority:
            constrained.append(surface.surface_id)
    return {
        "authority": PERIPHERAL_CAPABILITY_BOUNDARY_AUTHORITY,
        "sentinel": PERIPHERAL_CAPABILITY_BOUNDARY_PR10V2_SENTINEL,
        "policies": [
            PERIPHERAL_LAYERS_ARE_INGRESS_NOT_RUNTIME_AUTHORITY_POLICY,
            SPECIALISTS_AS_TOOLS_SUBLAYER_NOT_PARALLEL_MAINLINE_POLICY,
            OUTWARD_PROJECTION_OPERATOR_ARE_CONSUMERS_NOT_GOVERNANCE_POLICY,
            ANDROID_LINK_MUST_FLOW_THROUGH_CANONICAL_CHAIN_POLICY,
            NO_NEW_PARALLEL_PERIPHERAL_RUNTIME_POLICY,
        ],
        "total_surfaces": len(surfaces),
        "by_role": by_role,
        "constrained_surfaces": constrained,
        "android_v2_link_surfaces": list(get_android_v2_link_surfaces()),
        "surfaces": surfaces,
        "generated_at": time.time(),
    }
