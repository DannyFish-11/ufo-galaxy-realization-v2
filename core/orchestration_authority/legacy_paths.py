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
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "DeviceRouter.route_task performs gateway-level routing analysis "
            "and cross-device dispatch that is now owned by OpenClawd and "
            "CommandRouter.  New cross-device tasks must enter through "
            "OpenClawd._dispatch_device → OpenClawd.send_gateway_command → "
            "CommandRouter.route_envelope.  DeviceRouter.route_task is "
            "retained as a compatibility fallback only."
        ),
        pr_guardrail_added="PR-7",
        notes=(
            "DeviceRouter.route_task — gateway-level task router.  "
            "Demoted in PR-7: routing authority belongs to OpenClawd and "
            "CommandRouter, not the gateway.  Do not call directly in new code."
        ),
    ),
    LegacyPathEntry(
        module_path="galaxy_gateway.cross_device_coordinator.CrossDeviceCoordinator",
        status=LegacyPathStatus.LEGACY_COMPATIBILITY,
        recommendation=(
            "CrossDeviceCoordinator is a gateway-internal coordinator that "
            "predates the CommandRouter substrate root.  It is invoked as a "
            "fallback when the AgentBridge import fails in DeviceRouter.  "
            "New code should not call it directly; route through "
            "CommandRouter.route_envelope instead."
        ),
        pr_guardrail_added="PR-7",
        notes=(
            "CrossDeviceCoordinator — gateway-internal fallback coordinator.  "
            "Demoted in PR-7: not a primary cross-device entrypoint.  "
            "Used only as a last-resort fallback within DeviceRouter."
        ),
    ),
)

#: Frozenset of node module prefixes that are LEGACY_ORCHESTRATOR_NODE class.
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
# Compatibility shim: expose same symbol as constellation_runtime
# ---------------------------------------------------------------------------

#: Frozenset of legacy paths — same shape as ``LEGACY_ORCHESTRATOR_PATHS``
#: in ``core/constellation_runtime.py``, extended with PR-9 additions.
LEGACY_ORCHESTRATOR_PATHS: frozenset = frozenset(LEGACY_PATH_REGISTRY.keys())
