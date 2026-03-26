#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.orchestration_authority.legacy_paths
==========================================

PR-9 (V3) — Orchestration Authority Consolidation

Centralised registry of **legacy and deprecated** orchestration entry-point
paths, together with a structured guardrail helper.

This module builds upon — but does not replace — the existing
``LEGACY_ORCHESTRATOR_PATHS`` / ``warn_legacy_path`` machinery already
present in ``core/constellation_runtime.py``.  It extends that list with
additional paths identified during PR-9 review and exposes a richer
:class:`LegacyPathEntry` metadata type so that downstream tooling (authority
resolver, API catalogs) can programmatically inspect legacy-path status.

The guardrail emitted here deliberately mirrors the format used in
``core/constellation_runtime.py`` so that log-aggregation pipelines see a
consistent ``LEGACY PATH GUARDRAIL`` prefix regardless of which module
produced the warning.

Usage::

    from core.orchestration_authority.legacy_paths import (
        LEGACY_PATH_REGISTRY,
        LegacyPathStatus,
        is_legacy_path,
        emit_legacy_guardrail,
    )

    if is_legacy_path("galaxy_gateway.orchestrator.task_orchestrator"):
        emit_legacy_guardrail(
            caller="galaxy_gateway.orchestrator.task_orchestrator",
            trace_id="abc123",
        )
"""

from __future__ import annotations

import dataclasses
import logging
from enum import Enum
from typing import Dict, Optional, Tuple

logger = logging.getLogger("Galaxy.OrchestrationAuthority")

__all__ = [
    "LegacyPathStatus",
    "LegacyPathEntry",
    "LEGACY_PATH_REGISTRY",
    "LEGACY_ORCHESTRATOR_NODE_PREFIXES",
    "is_legacy_path",
    "get_legacy_entry",
    "emit_legacy_guardrail",
    "classify_path_status",
]


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------


class LegacyPathStatus(str, Enum):
    """Classification status of an orchestration entry-point path.

    ``LEGACY_COMPATIBILITY``
        Path is still used by existing integrations; do not invoke as a new
        primary entrypoint.

    ``DEPRECATED``
        Path has been superseded; kept only for thin-wrapper compatibility.
        No new calls should be directed here.

    ``ACTIVE``
        Path is part of the authoritative entry chain.
    """

    LEGACY_COMPATIBILITY = "legacy_compatibility"
    DEPRECATED = "deprecated"
    ACTIVE = "active"


# ---------------------------------------------------------------------------
# LegacyPathEntry dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class LegacyPathEntry:
    """Metadata record for a single known legacy/deprecated path.

    Attributes
    ----------
    module_path:
        Dotted module/sub-module path as it would appear in Python imports or
        stack frames (e.g. ``"nodes.Node_110_SmartOrchestrator.server"``).
    status:
        :class:`LegacyPathStatus` classification.
    recommendation:
        Human-readable migration guidance.
    pr_guardrail_added:
        PR that first added an active guardrail for this path (if any).
    notes:
        Optional free-form notes.
    """

    module_path: str
    status: LegacyPathStatus
    recommendation: str
    pr_guardrail_added: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {
            "module_path": self.module_path,
            "status": self.status.value,
            "recommendation": self.recommendation,
            "pr_guardrail_added": self.pr_guardrail_added,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

#: Master registry of all known legacy / deprecated orchestration paths.
#:
#: Keys are the ``module_path`` values (dotted strings).  This dict is the
#: single source of truth consulted by :func:`is_legacy_path` and
#: :func:`emit_legacy_guardrail`.
LEGACY_PATH_REGISTRY: Dict[str, LegacyPathEntry] = {}

def _register(*entries: LegacyPathEntry) -> None:
    for entry in entries:
        LEGACY_PATH_REGISTRY[entry.module_path] = entry


_register(
    # ── Already guarded by core/constellation_runtime.py ──────────────────
    LegacyPathEntry(
        module_path="nodes.Node_110_SmartOrchestrator.server",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "Use core.constellation_runtime.get_constellation_runtime() "
            "or core.e2e_orchestrator.process_user_input() instead."
        ),
        pr_guardrail_added="PR-1 (constellation_runtime)",
        notes="Node_110 SmartOrchestrator server entry — legacy scheduler path.",
    ),
    LegacyPathEntry(
        module_path="nodes.Node_110_SmartOrchestrator.main",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "Use core.constellation_runtime.get_constellation_runtime() instead."
        ),
        pr_guardrail_added="PR-1 (constellation_runtime)",
        notes="Node_110 SmartOrchestrator main — legacy scheduler path.",
    ),
    LegacyPathEntry(
        module_path="nodes.Node_81_Orchestrator.main",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "Use core.constellation_runtime.get_constellation_runtime() instead."
        ),
        pr_guardrail_added="PR-1 (constellation_runtime)",
        notes="Node_81 Orchestrator — older multi-node orchestration path.",
    ),
    LegacyPathEntry(
        module_path="nodes.Node_50_Transformer.task_orchestrator",
        status=LegacyPathStatus.DEPRECATED,
        recommendation=(
            "Superseded by TaskEnvelope routing.  "
            "Use core.schemas.task_envelope.TaskEnvelope for internal routing."
        ),
        pr_guardrail_added="PR-1 (constellation_runtime)",
        notes="Node_50 Transformer task orchestrator — deprecated in favour of TaskEnvelope.",
    ),
    LegacyPathEntry(
        module_path="galaxy_gateway.orchestrator.task_orchestrator",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "Route new tasks through core.e2e_orchestrator.process_user_input() "
            "which delegates to DesktopPresenceRuntime and ConstellationRuntime."
        ),
        pr_guardrail_added="PR-1 (constellation_runtime)",
        notes=(
            "Galaxy Gateway task orchestrator — still active for multi-device "
            "dispatch but should not be the primary new-code entrypoint."
        ),
    ),
    # ── Additional paths identified in PR-9 review ────────────────────────
    LegacyPathEntry(
        module_path="fusion.unified_orchestrator",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "Use core.e2e_orchestrator.process_user_input() for unified "
            "orchestration.  fusion.unified_orchestrator is a parallel layer "
            "that predates the current authority chain."
        ),
        pr_guardrail_added="PR-9",
        notes=(
            "Fusion unified orchestrator — older parallel orchestration layer; "
            "predates DesktopPresenceRuntime authority chain."
        ),
    ),
    LegacyPathEntry(
        module_path="core.orchestrator_engine",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "core.orchestrator_engine (DAGScheduler) is valid for LLM-driven "
            "SubTask decomposition within ConstellationRuntime.  Do not call "
            "it directly as a top-level request entrypoint."
        ),
        pr_guardrail_added="PR-9",
        notes=(
            "DAGScheduler — used internally by ConstellationRuntime for "
            "LLM-driven decomposition.  Not a primary entrypoint."
        ),
    ),
)

# PR-36: Register additional paths that are explicitly retired to secondary
# status as part of the production-baseline promotion.  These paths may still
# exist in the codebase for backward compatibility, but are formally demoted.
_register(
    LegacyPathEntry(
        module_path="response.metadata.multimodal_context",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "Use response.metadata.canonical_perception_state (PR-16) as the "
            "authoritative perception source.  multimodal_context is the raw "
            "fused MultimodalBus.ingest() output retained for backward "
            "compatibility only.  Do not add new consumers of this key."
        ),
        pr_guardrail_added="PR-36",
        notes=(
            "Raw fused multimodal context — deprecated perception path. "
            "Formally demoted to LEGACY_SECONDARY in PR-36 production-baseline promotion."
        ),
    ),
    LegacyPathEntry(
        module_path="response.metadata.multimodal_route_decision",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "Use response.metadata.unified_control_plan['multimodal_route_decision'] "
            "as the canonical routing decision.  The top-level "
            "multimodal_route_decision key is retained only for backward "
            "compatibility and must not be used in new code."
        ),
        pr_guardrail_added="PR-36",
        notes=(
            "Top-level routing decision dict — deprecated compat shim. "
            "Formally demoted to LEGACY_SECONDARY in PR-36 production-baseline promotion."
        ),
    ),
)


# PR-003: Explicitly record legacy orchestrator nodes as LEGACY_ORCHESTRATOR_NODE
# architectural class entries.  These paths are already guarded above; these
# entries extend the registry with the canonical architectural-class mapping so
# that diagnostics and contributor tooling can cross-reference the two layers.
_register(
    LegacyPathEntry(
        module_path="nodes.Node_110_SmartOrchestrator",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "Node_110_SmartOrchestrator is classified as a LEGACY_ORCHESTRATOR_NODE. "
            "Register it with architectural_class=NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE "
            "in NodeFabricRegistry.  Do not use as a capability source or primary authority. "
            "Route new requests through core.openclawd (OpenClawd) instead."
        ),
        pr_guardrail_added="PR-003",
        notes=(
            "Node_110 SmartOrchestrator — LEGACY_ORCHESTRATOR_NODE. "
            "Demoted in PR-003 node classification.  Not a capability-bus source."
        ),
    ),
    LegacyPathEntry(
        module_path="nodes.Node_81_Orchestrator",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "Node_81_Orchestrator is classified as a LEGACY_ORCHESTRATOR_NODE. "
            "Register it with architectural_class=NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE "
            "in NodeFabricRegistry.  Do not use as a capability source or primary authority. "
            "Route new requests through core.openclawd (OpenClawd) instead."
        ),
        pr_guardrail_added="PR-003",
        notes=(
            "Node_81 Orchestrator — LEGACY_ORCHESTRATOR_NODE. "
            "Demoted in PR-003 node classification.  Not a capability-bus source."
        ),
    ),
    LegacyPathEntry(
        module_path="nodes.Node_50_Transformer",
        status=LegacyPathStatus.DEPRECATED,
        recommendation=(
            "Node_50_Transformer is classified as a LEGACY_ORCHESTRATOR_NODE. "
            "Register it with architectural_class=NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE "
            "in NodeFabricRegistry.  Superseded by TaskEnvelope routing. "
            "Use core.schemas.task_envelope.TaskEnvelope for internal routing."
        ),
        pr_guardrail_added="PR-003",
        notes=(
            "Node_50 Transformer — LEGACY_ORCHESTRATOR_NODE (deprecated). "
            "Demoted in PR-003 node classification.  Not a capability-bus source."
        ),
    ),
)

# PR-7: Formally demote gateway orchestrator paths that bypass the canonical
# cross-device execution chain (OpenClawd → CommandRouter → TaskEnvelope →
# Gateway substrate → Worker/Device/Node → ResultEnvelope → OpenClawd feedback).
# These paths previously allowed the gateway to act as a routing authority or
# planning brain; they are now demoted to LEGACY_COMPATIBILITY substrates.
_register(
    LegacyPathEntry(
        module_path="galaxy_gateway.orchestrator.galaxy_orchestrator",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "GalaxyOrchestrator is a legacy gateway-level planner.  "
            "The canonical cross-device chain is: "
            "OpenClawd → CommandRouter → TaskEnvelope → Gateway substrate → "
            "Worker/Device/Node → ResultEnvelope → OpenClawd feedback.  "
            "Gateway substrate components must not make routing decisions; "
            "route new cross-device tasks through core.openclawd.OpenClawd "
            "which delegates to core.command_router.CommandRouter."
        ),
        pr_guardrail_added="PR-7",
        notes=(
            "GalaxyOrchestrator — legacy gateway-level orchestration planner.  "
            "Demoted in PR-7: gateway is execution substrate only, not a "
            "planning brain.  Do not invoke as a primary cross-device entrypoint."
        ),
    ),
    LegacyPathEntry(
        module_path="galaxy_gateway.orchestrator.task_orchestrator.TaskOrchestrator",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "TaskOrchestrator in the gateway orchestrator package predates "
            "CommandRouter.route_envelope as the canonical substrate root.  "
            "Use core.command_router.CommandRouter.route_envelope for all "
            "cross-device task dispatch.  TaskOrchestrator is retained only "
            "as a compatibility fallback for existing integrations."
        ),
        pr_guardrail_added="PR-7",
        notes=(
            "Gateway TaskOrchestrator — legacy multi-device dispatch path.  "
            "Demoted in PR-7: CommandRouter.route_envelope is the sole router. "
            "Not a primary entrypoint for new cross-device work."
        ),
    ),
    LegacyPathEntry(
        module_path="galaxy_gateway.device_router.DeviceRouter.route_task",
        status=LegacyPathStatus.ACTIVE,
        recommendation=(
            "DeviceRouter.route_task is the CANONICAL SINGLE DISPATCH ENTRY "
            "(PR-S3) for all device-bound tasks and cross-device orchestration "
            "decisions.  All previously fragmented dispatch paths "
            "(AndroidBridge.assign_task, RepoCoordinator.dispatch_agent_to_android) "
            "now delegate here.  Use DeviceRouter.route_task as the primary "
            "entrypoint for all new device-bound task dispatch."
        ),
        pr_guardrail_added="PR-S3",
        notes=(
            "DeviceRouter.route_task — CANONICAL DISPATCH AUTHORITY (PR-S3).  "
            "Promoted from LEGACY_COMPATIBILITY (PR-7) to ACTIVE.  "
            "DeviceRouter is the single entry for all device-bound dispatch "
            "and cross-device orchestration decisions."
        ),
    ),
    LegacyPathEntry(
        module_path="galaxy_gateway.cross_device_coordinator.CrossDeviceCoordinator",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "CrossDeviceCoordinator is a DeviceRouter-internal coordinator "
            "(PR-S3).  It is invoked by DeviceRouter as a fallback when the "
            "AgentBridge import fails.  External code must not call it "
            "directly; route through DeviceRouter.route_task instead."
        ),
        pr_guardrail_added="PR-S3",
        notes=(
            "CrossDeviceCoordinator — DeviceRouter-internal fallback coordinator.  "
            "Not a public dispatch entry (PR-S3).  "
            "External callers must use DeviceRouter.route_task."
        ),
    ),
)

# PR-S3: Consolidate dispatch authority in DeviceRouter.
# AndroidBridge.assign_task and RepoCoordinator.dispatch_agent_to_android
# previously held independent dispatch authority and bypassed DeviceRouter.
# They are now demoted to LEGACY_COMPATIBILITY adapters that delegate to
# DeviceRouter.route_task() / DeviceRouter.dispatch_task().
_register(
    LegacyPathEntry(
        module_path="galaxy_gateway.android_bridge.AndroidBridge.assign_task",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "AndroidBridge.assign_task previously dispatched tasks directly "
            "via send_to_device(), bypassing DeviceRouter (PR-S3).  It now "
            "delegates to DeviceRouter.dispatch_task() as the canonical single "
            "dispatch entry.  The compatibility fallback to send_to_device() "
            "is retained only when the device is not registered in DeviceRouter.  "
            "New code should dispatch through DeviceRouter.route_task() directly."
        ),
        pr_guardrail_added="PR-S3",
        notes=(
            "AndroidBridge.assign_task — demoted in PR-S3.  "
            "Now a thin adapter that delegates dispatch to DeviceRouter.  "
            "Android-specific action translation (MessageBuilder) remains here."
        ),
    ),
    LegacyPathEntry(
        module_path="core.repo_coordinator.RepoCoordinator.dispatch_agent_to_android",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "RepoCoordinator.dispatch_agent_to_android previously built AIP "
            "messages and dispatched them directly via WebSocket/HTTP, "
            "bypassing DeviceRouter (PR-S3).  It now delegates to "
            "DeviceRouter.route_task() as the canonical single dispatch entry.  "
            "New code should dispatch through DeviceRouter.route_task() directly."
        ),
        pr_guardrail_added="PR-S3",
        notes=(
            "RepoCoordinator.dispatch_agent_to_android — demoted in PR-S3.  "
            "Now a thin adapter that delegates dispatch to DeviceRouter.  "
            "Compatibility fallback (direct send) retained for when "
            "DeviceRouter is unavailable."
        ),
    ),
)

# PR-8: Formally demote legacy UI surfaces that risk implying architectural
# authority or parallel state ownership.  The canonical outward-facing status
# model is the projection-driven windows_client.status_board_v2 which reads
# from GET /api/v1/projection/runtime (RuntimeProjection /
# DesktopStatusProjection contract).  dashboard/ and windows_client/ (excluding
# status_board_v2) are hereby classified as legacy compatibility surfaces.
_register(
    LegacyPathEntry(
        module_path="dashboard.backend.main",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "dashboard/backend/main.py is a LEGACY UI SURFACE (PR-8).  "
            "The /api/v1/* routes defined here are historical; the authoritative "
            "REST API is core/api_routes.py and the core/routes/* sub-modules.  "
            "For outward-facing system status, consumers must read from "
            "GET /api/v1/projection/runtime (RuntimeProjection / "
            "DesktopStatusProjection contract) rather than dashboard-owned "
            "endpoints.  dashboard/ may remain as a static-file server and "
            "management convenience panel, but it must not define system "
            "structure or maintain a parallel authoritative state."
        ),
        pr_guardrail_added="PR-8",
        notes=(
            "dashboard/ — LEGACY UI SURFACE.  "
            "Demoted in PR-8: not the architectural source of truth for system "
            "state.  Do not add new status-authority endpoints here."
        ),
    ),
    LegacyPathEntry(
        module_path="dashboard",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "dashboard/ package is a LEGACY UI SURFACE (PR-8).  "
            "See dashboard.backend.main entry for migration guidance."
        ),
        pr_guardrail_added="PR-8",
        notes="dashboard/ — LEGACY UI SURFACE.  Demoted in PR-8.",
    ),
    LegacyPathEntry(
        module_path="windows_client.main",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "windows_client/main.py is a HOST-SPECIFIC LEGACY SHELL (PR-8).  "
            "It must not define the primary desktop interaction philosophy or "
            "act as the outward-facing status authority.  "
            "New desktop status consumers must use the projection-driven "
            "windows_client.status_board_v2 which reads from "
            "GET /api/v1/projection/runtime."
        ),
        pr_guardrail_added="PR-8",
        notes=(
            "windows_client/ — HOST-SPECIFIC LEGACY SHELL.  "
            "Demoted in PR-8: projection is the single outward truth for "
            "status presentation."
        ),
    ),
    LegacyPathEntry(
        module_path="windows_client.status_board",
        status=LegacyPathStatus.DEPRECATED,
        recommendation=(
            "windows_client/status_board.py is a LEGACY STATUS BOARD (PR-8).  "
            "It polls /api/v1/continuum/state which is an ad-hoc non-projection "
            "endpoint.  The canonical replacement is windows_client.status_board_v2 "
            "which consumes the RuntimeProjection contract from "
            "GET /api/v1/projection/runtime.  "
            "Do not extend this module; extend status_board_v2/ instead."
        ),
        pr_guardrail_added="PR-8",
        notes=(
            "windows_client/status_board.py — LEGACY STATUS BOARD (deprecated).  "
            "Superseded by status_board_v2/ in PR-8.  "
            "Uses ad-hoc /api/v1/continuum/state endpoint instead of projection."
        ),
    ),
    LegacyPathEntry(
        module_path="windows_client",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "windows_client/ package is a HOST-SPECIFIC LEGACY SHELL (PR-8).  "
            "See windows_client.main entry for migration guidance."
        ),
        pr_guardrail_added="PR-8",
        notes="windows_client/ — HOST-SPECIFIC LEGACY SHELL.  Demoted in PR-8.",
    ),
)

# ---------------------------------------------------------------------------
# PR-8-layout: Register transitional surface paths introduced by the
# repository-layout reorganisation PR.
# ---------------------------------------------------------------------------

_register(
    LegacyPathEntry(
        module_path="enhancements.clients.windows_client.run_ui",
        status=LegacyPathStatus.DEPRECATED,
        recommendation=(
            "enhancements/clients/windows_client/run_ui.py is HARD-DISABLED (PR-3).  "
            "It targeted the retired legacy chat/sidebar client.  "
            "Active Windows direction: DesktopPresenceRuntime + status_board_v2/.  "
            "Authoritative startup path: python unified_launcher.py"
        ),
        pr_guardrail_added="PR-8-layout",
        notes=(
            "Hard-disabled stub.  Emits DeprecationWarning on import.  "
            "See enhancements/LEGACY_TRANSITION.md."
        ),
    ),
)

_register(
    LegacyPathEntry(
        module_path="enhancements.clients.windows_client",
        status=LegacyPathStatus.DEPRECATED,
        recommendation=(
            "enhancements/clients/windows_client/ is a TRANSITIONAL directory (PR-8-layout).  "
            "The run_ui launcher is hard-disabled.  "
            "Active Windows direction: DesktopPresenceRuntime + status_board_v2/."
        ),
        pr_guardrail_added="PR-8-layout",
        notes="enhancements/clients/windows_client/ — TRANSITIONAL.  See enhancements/LEGACY_TRANSITION.md.",
    ),
)

# ---------------------------------------------------------------------------
# PR-routing-authority: Demote legacy model-routing paths to bridge-only roles.
#
# The canonical model-routing authority is:
#   core.model_topology.topology_router.TopologyRouter  (TopologyRoutePlan output)
#
# Legacy routing helpers listed below are retained only for backward
# compatibility.  They must not be used as authoritative routing sources
# in new code.  See docs/MODEL_ROUTING_AUTHORITY.md for the full policy.
# ---------------------------------------------------------------------------

_register(
    LegacyPathEntry(
        module_path="core.multi_llm_router.MultiLLMRouter",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "MultiLLMRouter is a LEGACY ROUTING HELPER (PR-routing-authority).  "
            "It selects a provider/model at runtime but does not produce a "
            "TopologyRoutePlan and is not the canonical routing authority.  "
            "New routing decisions must go through "
            "core.model_topology.topology_router.TopologyRouter which produces "
            "a TopologyRoutePlan as the sole canonical routing output.  "
            "MultiLLMRouter is retained as a compatibility bridge only; "
            "do not treat its output as authoritative routing truth."
        ),
        pr_guardrail_added="PR-routing-authority",
        notes=(
            "MultiLLMRouter — LEGACY ROUTING HELPER.  "
            "Demoted in PR-routing-authority: not the canonical routing authority.  "
            "Canonical authority: TopologyRouter → TopologyRoutePlan."
        ),
    ),
    LegacyPathEntry(
        module_path="core.multi_llm_router",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "core/multi_llm_router.py is a LEGACY ROUTING MODULE (PR-routing-authority).  "
            "See core.multi_llm_router.MultiLLMRouter entry for migration guidance."
        ),
        pr_guardrail_added="PR-routing-authority",
        notes="core/multi_llm_router.py — LEGACY ROUTING MODULE.  Demoted in PR-routing-authority.",
    ),
    LegacyPathEntry(
        module_path="dashboard.backend.main.llm_providers",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "dashboard/backend/main.py llm_providers endpoint is a LEGACY PROVIDER "
            "ROUTING SURFACE (PR-routing-authority).  "
            "Provider/model selection data served from this endpoint is not the "
            "canonical routing truth.  The canonical routing authority is "
            "core.model_topology.topology_router.TopologyRouter.  "
            "Consumers needing model routing state must read from "
            "GET /api/v1/projection/runtime (RuntimeProjection) or "
            "GET /api/v1/projection/return (DesktopStatusProjection) which embed "
            "routing data sourced from TopologyRoutePlan.  "
            "This endpoint is retained only for legacy dashboard UI compatibility."
        ),
        pr_guardrail_added="PR-routing-authority",
        notes=(
            "dashboard llm_providers — LEGACY PROVIDER ROUTING SURFACE.  "
            "Demoted in PR-routing-authority: not canonical routing truth.  "
            "Do not use as a model/provider selection authority."
        ),
    ),
)

# ---------------------------------------------------------------------------
# PR-oneapi-system-position entries
# ---------------------------------------------------------------------------
# These entries document paths related to the OneAPI aggregator integration.
# They are NOT "broken" or "to-be-removed" paths; they are ACTIVE_INTEGRATION
# entries that record the canonical system-wide effect semantics for
# OneAPI-related configuration and state flows.
#
# Rule: any component that reads ONEAPI_BASE_URL / ONEAPI_API_KEY or
# accesses the "oneapi" provider record must treat those values as
# system-wide aggregator integration inputs, not as dashboard-local state.
# ---------------------------------------------------------------------------

_register(
    LegacyPathEntry(
        module_path="nodes.Node_01_OneAPI.main",
        status=LegacyPathStatus.ACTIVE,
        recommendation=(
            "nodes/Node_01_OneAPI/main.py is the GALAXY INTEGRATION POINT "
            "for the external OneAPI aggregator gateway.  "
            "ONEAPI_BASE_URL and ONEAPI_API_KEY configured here have "
            "SYSTEM-WIDE EFFECT: they enter ProviderInventory "
            "(ProviderCategory.ONEAPI), propagate to TopologyRouter's routing "
            "candidate pool, and surface via DesktopStatusProjection.  "
            "Do NOT treat this node as a local/isolated configuration surface.  "
            "See docs/ONEAPI_SYSTEM_POSITION.md for the canonical definition."
        ),
        pr_guardrail_added="PR-oneapi-system-position",
        notes=(
            "Node_01_OneAPI — AGGREGATOR INTEGRATION LAYER (not a direct provider).  "
            "System-wide effect: ProviderCategory.ONEAPI → TopologyRouter → "
            "DesktopStatusProjection → status board lower row."
        ),
    ),
    LegacyPathEntry(
        module_path="dashboard.backend.main.oneapi_configured",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "The 'oneapi_configured' status flag in the dashboard backend is a "
            "LEGACY SURFACE (PR-oneapi-system-position).  "
            "OneAPI configuration/availability truth must be sourced from "
            "core.oneapi_system_position.build_oneapi_integration_summary() and "
            "reflected via DesktopStatusProjection (ModelRoutingProjection) rather "
            "than as a standalone dashboard endpoint.  "
            "This endpoint is retained only for legacy dashboard UI compatibility."
        ),
        pr_guardrail_added="PR-oneapi-system-position",
        notes=(
            "dashboard oneapi_configured flag — LEGACY STATUS SURFACE.  "
            "Canonical OneAPI state must flow through DesktopStatusProjection."
        ),
    ),
    LegacyPathEntry(
        module_path="core.api_manager.APIManager._validate_oneapi",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "APIManager._validate_oneapi() is a LEGACY VALIDATION HELPER "
            "(PR-oneapi-system-position).  "
            "OneAPI availability must be determined by ProviderInventory / "
            "TopologyRouter participation rather than ad-hoc API-manager probes.  "
            "This helper is retained for the API key validation endpoint only."
        ),
        pr_guardrail_added="PR-oneapi-system-position",
        notes=(
            "api_manager OneAPI validation — LEGACY HELPER.  "
            "Availability truth belongs in ProviderInventory / TopologyRouter."
        ),
    ),
)

#: Contributors: when registering any node whose module path starts with one of
#: these prefixes, set architectural_class=NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE.
LEGACY_ORCHESTRATOR_NODE_PREFIXES: frozenset = frozenset({
    "nodes.Node_110_SmartOrchestrator",
    "nodes.Node_81_Orchestrator",
    "nodes.Node_50_Transformer",
})


def is_legacy_path(module_path: str) -> bool:
    """Return True if *module_path* is in the :data:`LEGACY_PATH_REGISTRY`."""
    return module_path in LEGACY_PATH_REGISTRY


def get_legacy_entry(module_path: str) -> Optional[LegacyPathEntry]:
    """Return the :class:`LegacyPathEntry` for *module_path*, or ``None``."""
    return LEGACY_PATH_REGISTRY.get(module_path)


def classify_path_status(module_path: str) -> LegacyPathStatus:
    """Return :class:`LegacyPathStatus` for *module_path*.

    Paths not found in the registry are treated as
    :attr:`~LegacyPathStatus.ACTIVE` (unclassified active).
    """
    entry = LEGACY_PATH_REGISTRY.get(module_path)
    if entry is None:
        return LegacyPathStatus.ACTIVE
    return entry.status


# ---------------------------------------------------------------------------
# Structured guardrail emitter
# ---------------------------------------------------------------------------


def emit_legacy_guardrail(
    caller: str,
    trace_id: Optional[str] = None,
    override_recommendation: Optional[str] = None,
) -> None:
    """Emit a structured ``WARNING`` when a legacy orchestration path is invoked.

    The log format is intentionally identical to the existing
    ``warn_legacy_path()`` format in ``core/constellation_runtime.py`` so that
    log-aggregation pipelines see a single consistent ``LEGACY PATH GUARDRAIL``
    prefix.

    Parameters
    ----------
    caller:
        Module path or class name of the legacy caller.
    trace_id:
        Optional request trace ID for log correlation.
    override_recommendation:
        If provided, replaces the registry recommendation (useful for callers
        that know a more specific migration path).
    """
    entry = LEGACY_PATH_REGISTRY.get(caller)
    if override_recommendation:
        recommendation = override_recommendation
    elif entry is not None:
        recommendation = entry.recommendation
    else:
        recommendation = (
            "Use core.desktop_presence_runtime.get_desktop_presence_runtime() "
            "or core.e2e_orchestrator.process_user_input() instead."
        )

    status_tag = entry.status.value if entry else "unregistered"
    logger.warning(
        "LEGACY PATH GUARDRAIL | caller=%r | status=%s | trace_id=%s | %s",
        caller,
        status_tag,
        trace_id or "n/a",
        recommendation,
    )


# ---------------------------------------------------------------------------
# PR-S4: Demote android_bridge device query surface, repo_coordinator Android
# control-plane posture, and _shared.py compat state helpers.
#
# android_bridge.py public device query methods (get_all_devices, etc.) still
# read from the local transport/session cache (_devices) as if it were
# authoritative.  They are transport-cache views, not canonical device state.
#
# repo_coordinator.py android_devices dict and its registration/heartbeat
# methods previously acted as an independent Android control plane; they now
# delegate all canonical writes to UDM and treat android_devices as a
# legacy compat cache.
#
# _shared.py RouteConnectionPool.active_devices and registered_devices dict
# are compat/transport surfaces; presence authority is UCM, device SSOT is UDM.
# ---------------------------------------------------------------------------
_register(
    LegacyPathEntry(
        module_path="galaxy_gateway.android_bridge.AndroidBridge.get_all_devices",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "AndroidBridge.get_all_devices() returns the local transport/session "
            "cache (_devices), NOT the canonical device registry.  "
            "It reflects only devices with an active WebSocket session in the "
            "current AndroidBridge instance.  "
            "For the canonical device registry, use "
            "UnifiedDeviceManager.list_devices() or "
            "UnifiedDeviceManager.get_devices_by_type().  "
            "PR-S4: transport-cache posture clarified."
        ),
        pr_guardrail_added="PR-S4",
        notes=(
            "AndroidBridge.get_all_devices — transport cache view (PR-S4).  "
            "Not an independent device registry.  "
            "Delegate canonical reads to UDM."
        ),
    ),
    LegacyPathEntry(
        module_path="galaxy_gateway.android_bridge.AndroidBridge.get_connected_devices",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "AndroidBridge.get_connected_devices() is a transport-cache view.  "
            "Use UnifiedConnectionManager or UDM for canonical presence state.  "
            "PR-S4: transport-cache posture clarified."
        ),
        pr_guardrail_added="PR-S4",
        notes="AndroidBridge.get_connected_devices — transport cache view (PR-S4).",
    ),
    LegacyPathEntry(
        module_path="galaxy_gateway.android_bridge.AndroidBridge.get_android_devices",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "AndroidBridge.get_android_devices() is a transport-cache view.  "
            "Use UnifiedDeviceManager.get_devices_by_type() for canonical "
            "Android device list.  PR-S4: transport-cache posture clarified."
        ),
        pr_guardrail_added="PR-S4",
        notes="AndroidBridge.get_android_devices — transport cache view (PR-S4).",
    ),
    LegacyPathEntry(
        module_path="galaxy_gateway.android_bridge.AndroidBridge.get_device_health",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "AndroidBridge.get_device_health() derives health from transport-layer "
            "session state, not the canonical DeviceHealthRegistry.  "
            "For authoritative health/circuit-breaker state, use DeviceHealthRegistry "
            "or GET /api/v1/devices/{id}/health.  PR-S4: transport-cache posture "
            "clarified."
        ),
        pr_guardrail_added="PR-S4",
        notes="AndroidBridge.get_device_health — transport cache view (PR-S4).",
    ),
)

_register(
    LegacyPathEntry(
        module_path="core.repo_coordinator.RepoCoordinator.android_devices",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "RepoCoordinator.android_devices is a LEGACY COMPAT CACHE, not a "
            "canonical Android device registry (PR-S4).  "
            "All canonical device writes go through UnifiedDeviceManager (UDM).  "
            "Read canonical device state from UDM, not from this dict.  "
            "This dict is retained only for backward-compatible reads by legacy "
            "callers (dashboard routes, tests)."
        ),
        pr_guardrail_added="PR-S4",
        notes=(
            "RepoCoordinator.android_devices — LEGACY COMPAT CACHE (PR-S4).  "
            "Not the SSOT for Android devices.  Canonical write path is UDM."
        ),
    ),
    LegacyPathEntry(
        module_path="core.repo_coordinator.RepoCoordinator.register_android_device",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "RepoCoordinator.register_android_device() previously wrote directly "
            "to the local android_devices dict, acting as an independent Android "
            "control plane (PR-S4).  It now delegates canonical writes to "
            "UnifiedDeviceManager (UDM) and updates android_devices only as a "
            "legacy compat cache.  New code should register devices via the "
            "canonical POST /api/v1/devices/register route which writes to UDM."
        ),
        pr_guardrail_added="PR-S4",
        notes=(
            "RepoCoordinator.register_android_device — demoted in PR-S4.  "
            "Now delegates canonical writes to UDM."
        ),
    ),
    LegacyPathEntry(
        module_path="core.repo_coordinator.RepoCoordinator.get_android_devices",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "RepoCoordinator.get_android_devices() previously read exclusively "
            "from the local android_devices compat cache (PR-S4).  It now "
            "prefers UnifiedDeviceManager (UDM) for canonical device lists; "
            "the compat cache is the fallback.  New code should query UDM "
            "directly via UnifiedDeviceManager.list_devices()."
        ),
        pr_guardrail_added="PR-S4",
        notes=(
            "RepoCoordinator.get_android_devices — demoted in PR-S4.  "
            "Now prefers UDM; compat cache is fallback."
        ),
    ),
)

_register(
    LegacyPathEntry(
        module_path="core.routes._shared.registered_devices",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "core.routes._shared.registered_devices is a LEGACY COMPAT CACHE "
            "(PR-S4).  Device SSOT is UnifiedDeviceManager (UDM).  "
            "This dict is populated at startup from the persisted JSON file "
            "for backward compat; canonical device reads should use UDM.  "
            "Do not add new write paths here; writes must go through UDM first."
        ),
        pr_guardrail_added="PR-S4",
        notes=(
            "core.routes._shared.registered_devices — LEGACY COMPAT CACHE (PR-S4).  "
            "Not the SSOT for devices.  Use UDM for canonical reads/writes."
        ),
    ),
    LegacyPathEntry(
        module_path="core.routes._shared.RouteConnectionPool.active_devices",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "RouteConnectionPool.active_devices is a TRANSPORT HANDLE CACHE / "
            "COMPAT SURFACE (PR-S4).  Presence authority is "
            "core.unified.UnifiedConnectionManager (UCM).  "
            "active_devices retains WebSocket handles for compat; all writes are "
            "mirrored to UCM.  New code should use UCM directly for presence "
            "queries and connection management."
        ),
        pr_guardrail_added="PR-S4",
        notes=(
            "RouteConnectionPool.active_devices — transport handle compat surface "
            "(PR-S4).  Not the canonical presence store.  Use UCM."
        ),
    ),
)

# ---------------------------------------------------------------------------
# PR-S5: Collapse remaining legacy runtime duplication.
#
# After PR-S4 (Android bridge / repo-coordinator / shared-state demotion), the
# following server-side modules still maintained independent runtime control
# paths or state stores that compete with the canonical pipeline:
#
#   galaxy_gateway.orchestrator.task_orchestrator.MultiDeviceOrchestrator
#       Subclass of the already-demoted TaskOrchestrator.  Retained only as a
#       compatibility shim; canonical multi-device execution goes through the
#       TaskGraph → DeviceRouter chain.
#
#   galaxy_gateway.orchestrator.parallel_tracker.ParallelGroupTracker
#       Tracks parallel subtask results across *both* websocket_handler and
#       task_orchestrator entry chains.  The canonical entry is the
#       websocket_handler → DeviceRouter chain (entry A).  Entry chain B
#       (handlers/message_handler → task_orchestrator) is the legacy path; the
#       tracker is retained only to avoid breaking the legacy chain.
#
#   core.local_agent_runtime.LocalAgentRuntime
#       Phase-1 Matrix OS component that runs its own Thought/Action/Observation
#       loop.  Server-side agent execution is now brokered via the canonical
#       OpenClawd → CommandRouter → TaskEnvelope → DeviceRouter pipeline.
#       LocalAgentRuntime is retained as a device-side execution sandbox that
#       receives already-dispatched manifests; it must not be invoked as a
#       primary server-side execution planner.
# ---------------------------------------------------------------------------
_register(
    LegacyPathEntry(
        module_path="galaxy_gateway.orchestrator.task_orchestrator.MultiDeviceOrchestrator",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "MultiDeviceOrchestrator is a LEGACY COMPAT SUBCLASS of the already-demoted "
            "TaskOrchestrator (PR-7, PR-S5).  "
            "Canonical multi-device execution is:  "
            "OpenClawd → CommandRouter → TaskEnvelope → TaskGraph (core.task_graph) → "
            "DeviceRouter.route_task.  "
            "MultiDeviceOrchestrator.submit_multi_device_task() now delegates to "
            "submit_dag_task() which uses core.task_graph for multi-device dispatch.  "
            "New code must route directly through core.e2e_orchestrator.process_user_input() "
            "or DeviceRouter.route_task(), not through this class."
        ),
        pr_guardrail_added="PR-S5",
        notes=(
            "MultiDeviceOrchestrator — LEGACY COMPAT SUBCLASS (PR-S5).  "
            "Extends TaskOrchestrator; both are demoted compatibility paths.  "
            "Canonical multi-device path is TaskGraph → DeviceRouter."
        ),
    ),
    LegacyPathEntry(
        module_path="galaxy_gateway.orchestrator.parallel_tracker.ParallelGroupTracker",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "ParallelGroupTracker is a LEGACY COMPAT STATE STORE (PR-S5).  "
            "It bridges two entry chains: the canonical entry "
            "(websocket_handler → DeviceRouter, chain A) and the legacy entry "
            "(handlers/message_handler → TaskOrchestrator, chain B).  "
            "The canonical server pipeline is chain A only.  "
            "The tracker is retained so that legacy chain-B callers can still collect "
            "parallel results without data loss during migration, but new code must "
            "route through DeviceRouter and rely on core.cross_device_execution_chain "
            "for parallel result aggregation."
        ),
        pr_guardrail_added="PR-S5",
        notes=(
            "ParallelGroupTracker — bridges canonical chain A and legacy chain B (PR-S5).  "
            "Canonical parallel result authority is cross_device_execution_chain.  "
            "Legacy chain B is TaskOrchestrator; not a primary entrypoint."
        ),
    ),
    LegacyPathEntry(
        module_path="core.local_agent_runtime.LocalAgentRuntime",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "LocalAgentRuntime is a PHASE-1 DEVICE-SIDE EXECUTION SANDBOX (PR-S5).  "
            "It is NOT a server-side primary execution planner.  "
            "Server-side agent execution is brokered by:  "
            "OpenClawd → CommandRouter → TaskEnvelope → DeviceRouter → device.  "
            "LocalAgentRuntime runs on the device side after a manifest has already "
            "been dispatched by the canonical pipeline.  Do not call it as a "
            "server-side planner or scheduler; it receives already-decided manifests."
        ),
        pr_guardrail_added="PR-S5",
        notes=(
            "LocalAgentRuntime — Phase-1 device-side execution sandbox (PR-S5).  "
            "Not a server-side canonical planner.  Receives dispatched manifests only.  "
            "Canonical server execution path is OpenClawd → DeviceRouter."
        ),
    ),
)

# ---------------------------------------------------------------------------
# PR-S6: Finalize server-side legacy demotion — remove non-canonical runtime
# entry leftovers.
#
# After PR-S5 (MultiDeviceOrchestrator / ParallelGroupTracker /
# LocalAgentRuntime demotion) the following server-side entry points still
# carried independent runtime authority that can bypass the canonical pipeline:
#
#   galaxy_gateway.task_router.TaskScheduler
#       Standalone topological scheduler that builds ExecutionPlan objects
#       independently of the canonical TaskGraph (core.task_graph).  Retained
#       as a legacy compatibility utility for gateway-internal callers; new
#       code must use core.task_graph directly.
#
#   galaxy_gateway.task_router.TaskRouter
#       Standalone task-dispatch loop that routes tasks to devices via raw
#       HTTP, bypassing the canonical DeviceRouter / TaskEnvelope / cross-
#       device chain pipeline.  Retained as a compatibility shim; all new
#       dispatch must go through DeviceRouter.route_task or the canonical
#       OpenClawd → DeviceRouter chain.
#
#   galaxy_gateway.handlers.message_handler.MessageHandler
#       The legacy "chain B" gateway message dispatcher
#       (handlers/message_handler → TaskOrchestrator path).  The canonical
#       server ingress is websocket_handler → DeviceRouter (chain A).
#       MessageHandler is retained only so existing integrations do not
#       immediately break; new routing must use chain A exclusively.
# ---------------------------------------------------------------------------
_register(
    LegacyPathEntry(
        module_path="galaxy_gateway.task_router.TaskScheduler",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "TaskScheduler is a LEGACY COMPAT SCHEDULER (PR-S6).  "
            "It builds topological ExecutionPlan objects independently of the "
            "canonical TaskGraph (core.task_graph).  "
            "New code must use core.task_graph.TaskGraph directly for dependency-"
            "ordered multi-device execution, which integrates with the canonical "
            "OpenClawd → CommandRouter → TaskEnvelope → DeviceRouter pipeline.  "
            "TaskScheduler is retained only so gateway-internal code that pre-dates "
            "the TaskGraph migration does not immediately break."
        ),
        pr_guardrail_added="PR-S6",
        notes=(
            "TaskScheduler — LEGACY COMPAT topological scheduler (PR-S6).  "
            "Canonical scheduling authority is core.task_graph.TaskGraph.  "
            "Not a primary entrypoint; delegate to core.task_graph for new work."
        ),
    ),
    LegacyPathEntry(
        module_path="galaxy_gateway.task_router.TaskRouter",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "TaskRouter is a LEGACY COMPAT DISPATCH LOOP (PR-S6).  "
            "It dispatches tasks to devices via raw HTTP, bypassing the canonical "
            "DeviceRouter / TaskEnvelope / cross-device chain pipeline.  "
            "Canonical task dispatch is:  "
            "OpenClawd → CommandRouter → TaskEnvelope → TaskGraph (core.task_graph) "
            "→ DeviceRouter.route_task → Worker/Device → ResultEnvelope.  "
            "TaskRouter is retained only for backward compatibility; all new dispatch "
            "must route through DeviceRouter.route_task or "
            "core.e2e_orchestrator.process_user_input()."
        ),
        pr_guardrail_added="PR-S6",
        notes=(
            "TaskRouter — LEGACY COMPAT raw-HTTP dispatch loop (PR-S6).  "
            "Canonical dispatch authority is DeviceRouter.route_task.  "
            "Not a primary entrypoint; must not be invoked for new work."
        ),
    ),
    LegacyPathEntry(
        module_path="galaxy_gateway.handlers.message_handler.MessageHandler",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "MessageHandler is the LEGACY CHAIN B gateway ingress (PR-S6).  "
            "It routes messages through the legacy path:  "
            "handlers/message_handler → TaskOrchestrator (chain B).  "
            "The canonical server ingress is chain A:  "
            "websocket_handler → DeviceRouter.  "
            "MessageHandler is retained only so existing integrations wired to "
            "chain B do not immediately break.  New message routing must be wired "
            "through websocket_handler (chain A) only."
        ),
        pr_guardrail_added="PR-S6",
        notes=(
            "MessageHandler — LEGACY CHAIN B gateway ingress (PR-S6).  "
            "Canonical ingress chain is websocket_handler → DeviceRouter (chain A).  "
            "MessageHandler → TaskOrchestrator path is the legacy chain B surface."
        ),
    ),
)

# ---------------------------------------------------------------------------
# PR-S7: Finalize server-side compatibility demotion — demote last remaining
# legacy control surfaces so they are operationally passive and clearly
# delegating.
#
# After PR-S6 (TaskScheduler / TaskRouter / MessageHandler demotion) the
# following server-side surfaces still carry independent runtime authority
# that can bypass or obscure the canonical pipeline:
#
#   galaxy_gateway.task_decomposer.TaskDecomposer
#       Rule-based complex-task splitter that creates sub-tasks independently
#       of the canonical TaskGraph (core.task_graph).  Retained as a legacy
#       compatibility utility; new task decomposition must use
#       core.task_graph.TaskGraph directly.
#
#   galaxy_gateway.task_decomposer.IntelligentTaskPlanner
#       LLM-based task planner that invokes TaskDecomposer independently of
#       the canonical OpenClawd → CommandRouter → TaskGraph pipeline.
#       Retained as a compatibility shim; new planning must route through
#       core.e2e_orchestrator.process_user_input() or the canonical
#       OpenClawd pipeline.
#
#   galaxy_gateway.capability_registry.GatewayCapabilityRegistry
#       In-gateway per-device action-schema store introduced before
#       core.capability_bus (CapabilityBus) existed.  Retained so existing
#       DeviceRouter capability-report pathways do not immediately break;
#       new capability registration must use core.capability_bus.CapabilityBus.
# ---------------------------------------------------------------------------
_register(
    LegacyPathEntry(
        module_path="galaxy_gateway.task_decomposer.TaskDecomposer",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "TaskDecomposer is a LEGACY COMPAT TASK SPLITTER (PR-S7).  "
            "It creates sub-tasks using hard-coded rule patterns independently "
            "of the canonical TaskGraph (core.task_graph).  "
            "New task decomposition must use core.task_graph.TaskGraph directly, "
            "which integrates with the canonical OpenClawd → CommandRouter → "
            "TaskEnvelope → DeviceRouter pipeline.  "
            "TaskDecomposer is retained only so gateway-internal code that "
            "pre-dates the TaskGraph migration does not immediately break."
        ),
        pr_guardrail_added="PR-S7",
        notes=(
            "TaskDecomposer — LEGACY COMPAT rule-based task splitter (PR-S7).  "
            "Canonical task decomposition authority is core.task_graph.TaskGraph.  "
            "Not a primary entrypoint; delegate to core.task_graph for new work."
        ),
    ),
    LegacyPathEntry(
        module_path="galaxy_gateway.task_decomposer.IntelligentTaskPlanner",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "IntelligentTaskPlanner is a LEGACY COMPAT LLM PLANNER (PR-S7).  "
            "It uses an LLM client to generate sub-tasks independently of the "
            "canonical OpenClawd → CommandRouter → TaskGraph pipeline.  "
            "Canonical task planning is: "
            "core.e2e_orchestrator.process_user_input() or directly through "
            "OpenClawd → CommandRouter → TaskEnvelope → TaskGraph → DeviceRouter.  "
            "IntelligentTaskPlanner is retained only for backward compatibility; "
            "all new planning must route through core.e2e_orchestrator or the "
            "canonical OpenClawd pipeline."
        ),
        pr_guardrail_added="PR-S7",
        notes=(
            "IntelligentTaskPlanner — LEGACY COMPAT LLM task planner (PR-S7).  "
            "Canonical planning authority is core.e2e_orchestrator.process_user_input().  "
            "Not a primary entrypoint; must not be used for new work."
        ),
    ),
    LegacyPathEntry(
        module_path="galaxy_gateway.capability_registry.GatewayCapabilityRegistry",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "GatewayCapabilityRegistry is a LEGACY COMPAT CAPABILITY STORE (PR-S7).  "
            "It is an in-gateway per-device action-schema map introduced before "
            "core.capability_bus (CapabilityBus) existed.  "
            "Canonical capability registration and lookup is: "
            "core.capability_bus.get_capability_bus() — use register_device_capability() "
            "for device capabilities and register_mcp_tool() / register_skill() for "
            "MCP / Skill capabilities.  "
            "GatewayCapabilityRegistry is retained so existing DeviceRouter and "
            "capability-report pathways do not immediately break; new capability "
            "registration and lookup must use core.capability_bus.CapabilityBus."
        ),
        pr_guardrail_added="PR-S7",
        notes=(
            "GatewayCapabilityRegistry — LEGACY COMPAT in-gateway capability store (PR-S7).  "
            "Canonical capability authority is core.capability_bus.CapabilityBus.  "
            "Delegating surface only; must not be used for new capability work."
        ),
    ),
)

# ---------------------------------------------------------------------------
# Compatibility shim: expose same symbol as constellation_runtime
#
# NOTE: This definition MUST remain at the end of the module, after ALL
# _register() calls.  Moving it earlier would freeze the frozenset before
# later _register() calls are evaluated, causing the shim to omit those paths.
# ---------------------------------------------------------------------------

#: Frozenset of legacy paths — same shape as ``LEGACY_ORCHESTRATOR_PATHS``
#: in ``core/constellation_runtime.py``, extended with all PR additions.
LEGACY_ORCHESTRATOR_PATHS: frozenset = frozenset(LEGACY_PATH_REGISTRY.keys())
