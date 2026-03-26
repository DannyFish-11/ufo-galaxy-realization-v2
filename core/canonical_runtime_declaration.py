#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.canonical_runtime_declaration
====================================

PR-S7 — Make final server cleanup mechanical after canonical runtime
consolidation.

This module is the **single machine-readable source of truth** for the
canonical server runtime pipeline.  It answers, unambiguously:

  * What is the canonical pipeline?  (ordered steps, authority owners)
  * Which surfaces are canonical entry-points?
  * Which surfaces are legacy/compat wrappers that delegate to the canonical
    path?
  * What are the rules for classifying an arbitrary module as canonical vs
    legacy?

After this module exists, follow-up cleanup work (deletion of legacy code,
consolidation of wrappers, alignment of tests and documentation) is
**mechanical**: any surface not declared canonical here can be safely
flagged for removal or reduction.

Design principles
-----------------
* **Read-only metadata** — this module does not alter runtime behaviour.
  It is consumed by tests, tooling, and human maintainers.
* **Declarative** — each pipeline step and surface entry is expressed as a
  frozen dataclass with full provenance.
* **Aligned with existing registries** — legacy surfaces referenced here
  MUST have a corresponding entry in
  ``core.orchestration_authority.legacy_paths.LEGACY_PATH_REGISTRY`` and
  ``core.legacy_purge_registry.PURGE_REGISTRY``.
* **Minimal / additive** — nothing in this module removes, disables, or
  modifies existing code.

Canonical pipeline (complete, ordered)
---------------------------------------
::

    DesktopPresenceRuntime          (outer shell — tri-state lifecycle owner)
        └─ OpenClawd                (subject core — cognition / execution nucleus)
              └─ AgentKernel        (agent execution boundary)
                    └─ CommandRouter  (branch selector: local vs remote)
                          ├── LOCAL BRANCH
                          │     local_execution_chain → local executor
                          │     → LocalExecutionResult → OpenClawd feedback
                          └── REMOTE BRANCH
                                TaskEnvelope → TaskGraph (core.task_graph)
                                → DeviceRouter.route_task
                                → Worker/Device
                                → ResultEnvelope → OpenClawd feedback

Entry surfaces (canonical — these are the only legitimate ways to inject a
request into the pipeline from outside):

  1. ``core.routes.chat``          — REST /api/v1/chat  (HTTP ingress)
  2. ``galaxy_gateway.app``        — WebSocket /ws/*    (WebSocket ingress)
  3. ``core.e2e_orchestrator``     — ``process_user_input()``  (programmatic)

All other surfaces that could historically accept a request are legacy compat
surfaces that MUST delegate to one of the above entry surfaces, or to the
canonical pipeline directly, and MUST NOT carry independent runtime authority.

Usage::

    from core.canonical_runtime_declaration import (
        get_canonical_runtime_declaration,
        CanonicalPipelineStage,
        CanonicalSurfaceRole,
    )

    decl = get_canonical_runtime_declaration()
    print(decl.to_json(indent=2))

    # Enumerate canonical entry points
    for surface in decl.entry_surfaces:
        if surface.role == CanonicalSurfaceRole.CANONICAL_ENTRY:
            print(surface.module_path)
"""

from __future__ import annotations

import dataclasses
import json
from enum import Enum
from typing import Dict, List, Optional, Tuple

__all__ = [
    "CanonicalPipelineStage",
    "CanonicalSurfaceRole",
    "PipelineStepDeclaration",
    "CanonicalSurfaceDeclaration",
    "CanonicalRuntimeDeclaration",
    "build_canonical_runtime_declaration",
    "get_canonical_runtime_declaration",
    "reset_canonical_runtime_declaration",
]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CanonicalPipelineStage(str, Enum):
    """Ordered stages of the canonical server runtime pipeline.

    The numeric suffix in each member name encodes execution order.
    """

    STAGE_1_PRESENCE_SHELL = "stage_1_presence_shell"
    """DesktopPresenceRuntime — outer shell / tri-state lifecycle owner.

    Responsibilities: owns ``runtime_session_id``, drives tri-state
    (SILENT → LIMINAL → MANIFEST), owns native multimodal ingress.
    Canonical module: ``core.desktop_presence_runtime``.
    """

    STAGE_2_SUBJECT_CORE = "stage_2_subject_core"
    """OpenClawd — subject core / cognition + execution nucleus.

    Responsibilities: ingest, continuum, branch selection, manifest
    generation, memory backflow.
    Canonical module: ``core.openclawd``.
    """

    STAGE_3_AGENT_KERNEL = "stage_3_agent_kernel"
    """AgentKernel — agent execution boundary.

    Responsibilities: tool dispatch, capability lookup, execution
    governance.
    Canonical module: ``core.agent.kernel``.
    """

    STAGE_4_COMMAND_ROUTER = "stage_4_command_router"
    """CommandRouter — local vs remote branch selector.

    Responsibilities: decide LOCAL vs REMOTE execution path; emit
    ``TaskEnvelope`` for remote branch.
    Canonical module: ``core.command_router``.
    """

    STAGE_5_LOCAL_CHAIN = "stage_5_local_chain"
    """Local execution chain (LOCAL branch).

    Responsibilities: execute locally, record ``LocalExecutionResult``,
    feed result back to OpenClawd.
    Canonical module: ``core.local_execution_chain``.
    """

    STAGE_5_REMOTE_TASK_GRAPH = "stage_5_remote_task_graph"
    """TaskGraph (REMOTE branch) — dependency-ordered multi-device DAG.

    Responsibilities: build and execute the task dependency graph.
    Canonical module: ``core.task_graph``.
    """

    STAGE_6_DEVICE_ROUTER = "stage_6_device_router"
    """DeviceRouter — canonical device-bound dispatch authority.

    Responsibilities: route ``TaskEnvelope`` to a specific worker/device;
    the SINGLE canonical dispatch authority for device-bound tasks.
    Canonical module: ``galaxy_gateway.device_router.DeviceRouter``.
    """

    STAGE_7_RESULT_ENVELOPE = "stage_7_result_envelope"
    """ResultEnvelope — canonical result authority.

    Responsibilities: wrap device execution results, feed into
    ``core.cross_device_execution_chain`` and back to OpenClawd.
    Canonical module: ``core.cross_device_execution_chain`` (ResultEnvelope).
    """


class CanonicalSurfaceRole(str, Enum):
    """The role of a server-side module surface relative to the canonical pipeline.

    ``CANONICAL_PIPELINE``
        A module that IS part of the canonical pipeline (one of the stages
        above).  It has exclusive runtime authority for its stage.

    ``CANONICAL_ENTRY``
        A legitimate external entry surface — a module through which callers
        (HTTP, WebSocket, tests, programmatic code) may inject requests into
        the canonical pipeline.  Must delegate immediately to the pipeline.

    ``CANONICAL_HELPER``
        A support/utility module that is called BY canonical pipeline stages
        and has no independent runtime authority.  Provides infrastructure
        (e.g. device registry, connection manager, capability bus) without
        making routing or dispatch decisions of its own.

    ``LEGACY_COMPAT``
        A historical module that is retained for backward compatibility only.
        MUST NOT carry independent runtime authority.  MUST delegate to a
        canonical entry or pipeline stage.  Carries a guardrail and a
        ``LEGACY_PATH_REGISTRY`` entry.

    ``DEMOTED_ENTRY``
        A former entry surface that has been explicitly demoted (deprecated
        + guardrailed).  Treated the same as ``LEGACY_COMPAT`` but signals
        that this surface WAS previously a primary entrypoint.
    """

    CANONICAL_PIPELINE = "canonical_pipeline"
    CANONICAL_ENTRY = "canonical_entry"
    CANONICAL_HELPER = "canonical_helper"
    LEGACY_COMPAT = "legacy_compat"
    DEMOTED_ENTRY = "demoted_entry"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PipelineStepDeclaration:
    """Declaration of a single canonical pipeline step.

    Attributes
    ----------
    stage:
        The :class:`CanonicalPipelineStage` for this step.
    authority_module:
        Dotted Python import path for the canonical authority module.
    authority_class:
        Optional class name within *authority_module*.
    description:
        One-line human-readable description of the step's responsibility.
    pr_established:
        The PR that first established this as the canonical authority.
    """

    stage: CanonicalPipelineStage
    authority_module: str
    authority_class: Optional[str]
    description: str
    pr_established: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "stage": self.stage.value,
            "authority_module": self.authority_module,
            "authority_class": self.authority_class,
            "description": self.description,
            "pr_established": self.pr_established,
        }


@dataclasses.dataclass(frozen=True)
class CanonicalSurfaceDeclaration:
    """Declaration of a server-side module surface and its canonical role.

    Attributes
    ----------
    module_path:
        Dotted Python import path (e.g. ``core.e2e_orchestrator``).
    role:
        :class:`CanonicalSurfaceRole` for this surface.
    description:
        One-line description of this surface's responsibility.
    canonical_replacement:
        For LEGACY_COMPAT / DEMOTED_ENTRY surfaces: the canonical module or
        function callers must use instead.  ``None`` for canonical surfaces.
    legacy_registry_key:
        For LEGACY_COMPAT / DEMOTED_ENTRY surfaces: the key in
        ``LEGACY_PATH_REGISTRY`` and/or ``PURGE_REGISTRY``.  ``None`` for
        canonical surfaces.
    pr_last_updated:
        The PR that last updated the status of this surface.
    """

    module_path: str
    role: CanonicalSurfaceRole
    description: str
    canonical_replacement: Optional[str]
    legacy_registry_key: Optional[str]
    pr_last_updated: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "module_path": self.module_path,
            "role": self.role.value,
            "description": self.description,
            "canonical_replacement": self.canonical_replacement,
            "legacy_registry_key": self.legacy_registry_key,
            "pr_last_updated": self.pr_last_updated,
        }


@dataclasses.dataclass
class CanonicalRuntimeDeclaration:
    """Top-level declaration of the canonical server runtime.

    Attributes
    ----------
    declaration_version:
        Monotonically-incrementing version string (e.g. ``"1.0"``).
    generated_by_pr:
        The PR that generated this declaration.
    pipeline_steps:
        Ordered :class:`PipelineStepDeclaration` list describing the canonical
        pipeline from ingress to result.
    entry_surfaces:
        :class:`CanonicalSurfaceDeclaration` list covering canonical entries,
        helpers, and demoted/legacy surfaces.
    """

    declaration_version: str
    generated_by_pr: str
    pipeline_steps: List[PipelineStepDeclaration]
    entry_surfaces: List[CanonicalSurfaceDeclaration]

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def canonical_entries(self) -> List[CanonicalSurfaceDeclaration]:
        """Return all surfaces whose role is CANONICAL_ENTRY."""
        return [
            s for s in self.entry_surfaces
            if s.role == CanonicalSurfaceRole.CANONICAL_ENTRY
        ]

    @property
    def canonical_pipeline_surfaces(self) -> List[CanonicalSurfaceDeclaration]:
        """Return all surfaces whose role is CANONICAL_PIPELINE."""
        return [
            s for s in self.entry_surfaces
            if s.role == CanonicalSurfaceRole.CANONICAL_PIPELINE
        ]

    @property
    def legacy_surfaces(self) -> List[CanonicalSurfaceDeclaration]:
        """Return all surfaces that are LEGACY_COMPAT or DEMOTED_ENTRY."""
        return [
            s for s in self.entry_surfaces
            if s.role in (
                CanonicalSurfaceRole.LEGACY_COMPAT,
                CanonicalSurfaceRole.DEMOTED_ENTRY,
            )
        ]

    def surface_by_module(
        self, module_path: str
    ) -> Optional[CanonicalSurfaceDeclaration]:
        """Return the :class:`CanonicalSurfaceDeclaration` for *module_path*."""
        for s in self.entry_surfaces:
            if s.module_path == module_path:
                return s
        return None

    def is_canonical(self, module_path: str) -> bool:
        """Return ``True`` when *module_path* is a canonical surface."""
        surface = self.surface_by_module(module_path)
        if surface is None:
            return False
        return surface.role in (
            CanonicalSurfaceRole.CANONICAL_PIPELINE,
            CanonicalSurfaceRole.CANONICAL_ENTRY,
            CanonicalSurfaceRole.CANONICAL_HELPER,
        )

    def is_legacy(self, module_path: str) -> bool:
        """Return ``True`` when *module_path* is a legacy/demoted surface."""
        surface = self.surface_by_module(module_path)
        if surface is None:
            return False
        return surface.role in (
            CanonicalSurfaceRole.LEGACY_COMPAT,
            CanonicalSurfaceRole.DEMOTED_ENTRY,
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, object]:
        return {
            "declaration_version": self.declaration_version,
            "generated_by_pr": self.generated_by_pr,
            "pipeline_steps": [s.to_dict() for s in self.pipeline_steps],
            "entry_surfaces": [s.to_dict() for s in self.entry_surfaces],
            "canonical_entry_count": len(self.canonical_entries),
            "legacy_surface_count": len(self.legacy_surfaces),
        }

    def to_json(self, **kwargs: object) -> str:
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def _build_pipeline_steps() -> List[PipelineStepDeclaration]:
    """Return the ordered canonical pipeline step declarations."""
    return [
        PipelineStepDeclaration(
            stage=CanonicalPipelineStage.STAGE_1_PRESENCE_SHELL,
            authority_module="core.desktop_presence_runtime",
            authority_class="DesktopPresenceRuntime",
            description=(
                "Outer shell / tri-state lifecycle owner.  Owns runtime_session_id, "
                "drives SILENT → LIMINAL → MANIFEST transitions, owns native "
                "multimodal ingress."
            ),
            pr_established="PR-1",
        ),
        PipelineStepDeclaration(
            stage=CanonicalPipelineStage.STAGE_2_SUBJECT_CORE,
            authority_module="core.openclawd",
            authority_class="OpenClawd",
            description=(
                "Subject core — cognition + execution nucleus.  Ingest, continuum, "
                "branch selection, manifest generation, memory backflow."
            ),
            pr_established="PR-1",
        ),
        PipelineStepDeclaration(
            stage=CanonicalPipelineStage.STAGE_3_AGENT_KERNEL,
            authority_module="core.agent.kernel",
            authority_class="AgentKernel",
            description=(
                "Agent execution boundary.  Tool dispatch, capability lookup, "
                "execution governance."
            ),
            pr_established="PR-6",
        ),
        PipelineStepDeclaration(
            stage=CanonicalPipelineStage.STAGE_4_COMMAND_ROUTER,
            authority_module="core.command_router",
            authority_class="CommandRouter",
            description=(
                "Branch selector — decides LOCAL vs REMOTE execution path; emits "
                "TaskEnvelope for the remote branch."
            ),
            pr_established="PR-1",
        ),
        PipelineStepDeclaration(
            stage=CanonicalPipelineStage.STAGE_5_LOCAL_CHAIN,
            authority_module="core.local_execution_chain",
            authority_class="LocalExecutionChainSingleton",
            description=(
                "LOCAL branch: execute locally, record LocalExecutionResult, "
                "feed result back to OpenClawd."
            ),
            pr_established="PR-S4",
        ),
        PipelineStepDeclaration(
            stage=CanonicalPipelineStage.STAGE_5_REMOTE_TASK_GRAPH,
            authority_module="core.task_graph",
            authority_class="TaskGraph",
            description=(
                "REMOTE branch: dependency-ordered multi-device DAG execution.  "
                "Canonical multi-step scheduling authority."
            ),
            pr_established="PR-S3",
        ),
        PipelineStepDeclaration(
            stage=CanonicalPipelineStage.STAGE_6_DEVICE_ROUTER,
            authority_module="galaxy_gateway.device_router",
            authority_class="DeviceRouter",
            description=(
                "Canonical device-bound dispatch authority.  Routes TaskEnvelope "
                "to a specific worker/device via WebSocket.  "
                "CANONICAL_DISPATCH_AUTHORITY sentinel."
            ),
            pr_established="PR-S3",
        ),
        PipelineStepDeclaration(
            stage=CanonicalPipelineStage.STAGE_7_RESULT_ENVELOPE,
            authority_module="core.cross_device_execution_chain",
            authority_class="ResultEnvelope",
            description=(
                "Canonical result authority.  Wraps device execution results, "
                "feeds into cross_device_execution_chain and back to OpenClawd."
            ),
            pr_established="PR-7",
        ),
    ]


def _build_entry_surfaces() -> List[CanonicalSurfaceDeclaration]:
    """Return the complete surface catalog (canonical, helpers, and legacy)."""
    return [
        # ── Canonical pipeline stages ─────────────────────────────────────
        CanonicalSurfaceDeclaration(
            module_path="core.desktop_presence_runtime",
            role=CanonicalSurfaceRole.CANONICAL_PIPELINE,
            description=(
                "Outer runtime shell — stage 1 of the canonical pipeline.  "
                "Tri-state lifecycle owner.  Canonical session/request boundary."
            ),
            canonical_replacement=None,
            legacy_registry_key=None,
            pr_last_updated="PR-1",
        ),
        CanonicalSurfaceDeclaration(
            module_path="core.openclawd",
            role=CanonicalSurfaceRole.CANONICAL_PIPELINE,
            description=(
                "Subject core — stage 2 of the canonical pipeline.  "
                "Cognition + execution nucleus."
            ),
            canonical_replacement=None,
            legacy_registry_key=None,
            pr_last_updated="PR-6",
        ),
        CanonicalSurfaceDeclaration(
            module_path="core.command_router",
            role=CanonicalSurfaceRole.CANONICAL_PIPELINE,
            description=(
                "Branch selector — stage 4 of the canonical pipeline.  "
                "Local vs remote dispatch decision."
            ),
            canonical_replacement=None,
            legacy_registry_key=None,
            pr_last_updated="PR-1",
        ),
        CanonicalSurfaceDeclaration(
            module_path="core.task_graph",
            role=CanonicalSurfaceRole.CANONICAL_PIPELINE,
            description=(
                "Dependency-ordered task DAG — stage 5 (remote branch) of "
                "the canonical pipeline."
            ),
            canonical_replacement=None,
            legacy_registry_key=None,
            pr_last_updated="PR-S3",
        ),
        CanonicalSurfaceDeclaration(
            module_path="galaxy_gateway.device_router",
            role=CanonicalSurfaceRole.CANONICAL_PIPELINE,
            description=(
                "Canonical device-bound dispatch authority — stage 6 of the "
                "canonical pipeline.  CANONICAL_DISPATCH_AUTHORITY sentinel."
            ),
            canonical_replacement=None,
            legacy_registry_key=None,
            pr_last_updated="PR-S3",
        ),
        CanonicalSurfaceDeclaration(
            module_path="core.cross_device_execution_chain",
            role=CanonicalSurfaceRole.CANONICAL_PIPELINE,
            description=(
                "Result authority — stage 7 of the canonical pipeline.  "
                "ResultEnvelope wraps device results and feeds OpenClawd feedback."
            ),
            canonical_replacement=None,
            legacy_registry_key=None,
            pr_last_updated="PR-7",
        ),
        # ── Canonical entry surfaces ──────────────────────────────────────
        CanonicalSurfaceDeclaration(
            module_path="core.routes.chat",
            role=CanonicalSurfaceRole.CANONICAL_ENTRY,
            description=(
                "REST /api/v1/chat — canonical HTTP ingress.  "
                "Delegates to DesktopPresenceRuntime via e2e_orchestrator."
            ),
            canonical_replacement=None,
            legacy_registry_key=None,
            pr_last_updated="PR-1",
        ),
        CanonicalSurfaceDeclaration(
            module_path="galaxy_gateway.app",
            role=CanonicalSurfaceRole.CANONICAL_ENTRY,
            description=(
                "WebSocket /ws/* — canonical WebSocket ingress.  "
                "Internal cross-device execution substrate (NOT a primary subject "
                "entrypoint — it is the transport/protocol adapter layer).  "
                "Delegates commands to DeviceRouter."
            ),
            canonical_replacement=None,
            legacy_registry_key=None,
            pr_last_updated="PR-S3",
        ),
        CanonicalSurfaceDeclaration(
            module_path="core.e2e_orchestrator",
            role=CanonicalSurfaceRole.CANONICAL_ENTRY,
            description=(
                "process_user_input() — canonical programmatic entry.  "
                "Delegates to DesktopPresenceRuntime → OpenClawd chain."
            ),
            canonical_replacement=None,
            legacy_registry_key=None,
            pr_last_updated="PR-5",
        ),
        # ── Canonical helpers ─────────────────────────────────────────────
        CanonicalSurfaceDeclaration(
            module_path="core.device_registry",
            role=CanonicalSurfaceRole.CANONICAL_HELPER,
            description=(
                "Device identity / discovery registry.  "
                "Called by DeviceRouter and device_orchestrator; "
                "does not make routing or dispatch decisions."
            ),
            canonical_replacement=None,
            legacy_registry_key=None,
            pr_last_updated="PR-1",
        ),
        CanonicalSurfaceDeclaration(
            module_path="core.capability_bus",
            role=CanonicalSurfaceRole.CANONICAL_HELPER,
            description=(
                "Capability catalog — registers and looks up Node/MCP/Skill/Device "
                "capabilities.  Consumed by AgentKernel; does not dispatch."
            ),
            canonical_replacement=None,
            legacy_registry_key=None,
            pr_last_updated="PR-3",
        ),
        CanonicalSurfaceDeclaration(
            module_path="core.device_orchestrator",
            role=CanonicalSurfaceRole.CANONICAL_HELPER,
            description=(
                "High-level device operation helper — discover, command, file-transfer. "
                "Delegates to DeviceRegistry / NodeRegistry / ConnectionManager.  "
                "NOT a dispatch authority; does not bypass DeviceRouter for "
                "task routing decisions."
            ),
            canonical_replacement=None,
            legacy_registry_key=None,
            pr_last_updated="PR-S7",
        ),
        # ── Legacy / demoted surfaces ─────────────────────────────────────
        CanonicalSurfaceDeclaration(
            module_path="galaxy_gateway.orchestrator.galaxy_orchestrator",
            role=CanonicalSurfaceRole.LEGACY_COMPAT,
            description=(
                "Legacy gateway-level orchestration planner.  Demoted in PR-7.  "
                "The canonical cross-device execution chain supersedes it.  "
                "Retained for backward compatibility only."
            ),
            canonical_replacement=(
                "core.cross_device_execution_chain  (ResultEnvelope / "
                "build_chain_execution_record)  and  "
                "galaxy_gateway.device_router.DeviceRouter.route_task"
            ),
            legacy_registry_key="galaxy_gateway.orchestrator.galaxy_orchestrator.GalaxyOrchestrator",
            pr_last_updated="PR-7",
        ),
        CanonicalSurfaceDeclaration(
            module_path="galaxy_gateway.orchestrator.task_orchestrator",
            role=CanonicalSurfaceRole.LEGACY_COMPAT,
            description=(
                "Legacy task orchestration surface — chain B ingress "
                "(handlers/message_handler → TaskOrchestrator).  "
                "Canonical ingress is chain A: websocket_handler → DeviceRouter."
            ),
            canonical_replacement=(
                "galaxy_gateway.websocket_handler  (chain A)  →  "
                "galaxy_gateway.device_router.DeviceRouter.route_task"
            ),
            legacy_registry_key="galaxy_gateway.orchestrator.task_orchestrator",
            pr_last_updated="PR-1",
        ),
        CanonicalSurfaceDeclaration(
            module_path="galaxy_gateway.handlers.message_handler",
            role=CanonicalSurfaceRole.DEMOTED_ENTRY,
            description=(
                "Legacy chain B gateway ingress "
                "(MessageHandler → TaskOrchestrator).  Demoted in PR-S6.  "
                "Canonical ingress is websocket_handler → DeviceRouter (chain A)."
            ),
            canonical_replacement=(
                "galaxy_gateway.websocket_handler  (chain A: "
                "websocket_handler → DeviceRouter.route_task)"
            ),
            legacy_registry_key="galaxy_gateway.handlers.message_handler.MessageHandler",
            pr_last_updated="PR-S6",
        ),
        CanonicalSurfaceDeclaration(
            module_path="galaxy_gateway.task_router",
            role=CanonicalSurfaceRole.DEMOTED_ENTRY,
            description=(
                "Legacy task routing module (TaskScheduler + TaskRouter).  "
                "Demoted in PR-S6.  TaskScheduler is superseded by core.task_graph; "
                "TaskRouter is superseded by DeviceRouter.route_task."
            ),
            canonical_replacement=(
                "core.task_graph.TaskGraph  (scheduling)  and  "
                "galaxy_gateway.device_router.DeviceRouter.route_task  (dispatch)"
            ),
            legacy_registry_key="galaxy_gateway.task_router.TaskRouter",
            pr_last_updated="PR-S6",
        ),
        CanonicalSurfaceDeclaration(
            module_path="fusion.unified_orchestrator",
            role=CanonicalSurfaceRole.DEMOTED_ENTRY,
            description=(
                "Fusion unified orchestrator — deprecated legacy orchestration "
                "surface.  Canonical replacement is the full "
                "DesktopPresenceRuntime → OpenClawd → DeviceRouter pipeline, "
                "entered via core.e2e_orchestrator.process_user_input()."
            ),
            canonical_replacement=(
                "core.e2e_orchestrator.process_user_input()  (programmatic)  or  "
                "core.routes.chat  (HTTP ingress)"
            ),
            legacy_registry_key="fusion.unified_orchestrator",
            pr_last_updated="PR-S7",
        ),
        CanonicalSurfaceDeclaration(
            module_path="galaxy_gateway.orchestrator.task_orchestrator.MultiDeviceOrchestrator",
            role=CanonicalSurfaceRole.LEGACY_COMPAT,
            description=(
                "Legacy multi-device orchestrator — demoted in PR-S5.  "
                "Canonical parallel dispatch uses cross_device_execution_chain + "
                "DeviceRouter.route_task."
            ),
            canonical_replacement=(
                "core.cross_device_execution_chain  +  "
                "galaxy_gateway.device_router.DeviceRouter.route_task"
            ),
            legacy_registry_key=(
                "galaxy_gateway.orchestrator.task_orchestrator.MultiDeviceOrchestrator"
            ),
            pr_last_updated="PR-S5",
        ),
        CanonicalSurfaceDeclaration(
            module_path="core.local_agent_runtime",
            role=CanonicalSurfaceRole.LEGACY_COMPAT,
            description=(
                "Phase-1 device-side execution sandbox — demoted in PR-S5.  "
                "Receives dispatched manifests; not a server-side planner."
            ),
            canonical_replacement=(
                "core.openclawd → core.command_router → TaskEnvelope → "
                "galaxy_gateway.device_router.DeviceRouter.route_task"
            ),
            legacy_registry_key="core.local_agent_runtime.LocalAgentRuntime",
            pr_last_updated="PR-S5",
        ),
        CanonicalSurfaceDeclaration(
            module_path="core.constellation_runtime",
            role=CanonicalSurfaceRole.LEGACY_COMPAT,
            description=(
                "Legacy constellation runtime — historically the canonical "
                "dispatcher.  Superseded by the "
                "DesktopPresenceRuntime → OpenClawd pipeline.  Retained as "
                "compat layer; new code must use e2e_orchestrator."
            ),
            canonical_replacement=(
                "core.e2e_orchestrator.process_user_input()  or  "
                "core.desktop_presence_runtime.DesktopPresenceRuntime"
            ),
            legacy_registry_key="nodes.Node_110_SmartOrchestrator.server",
            pr_last_updated="PR-1",
        ),
    ]


def build_canonical_runtime_declaration() -> CanonicalRuntimeDeclaration:
    """Build and return a fresh :class:`CanonicalRuntimeDeclaration`.

    Returns
    -------
    CanonicalRuntimeDeclaration
        A fully populated declaration reflecting the PR-S7 state of the
        canonical server runtime.
    """
    return CanonicalRuntimeDeclaration(
        declaration_version="1.0",
        generated_by_pr="PR-S7",
        pipeline_steps=_build_pipeline_steps(),
        entry_surfaces=_build_entry_surfaces(),
    )


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_declaration_instance: Optional[CanonicalRuntimeDeclaration] = None


def get_canonical_runtime_declaration() -> CanonicalRuntimeDeclaration:
    """Return the global :class:`CanonicalRuntimeDeclaration` singleton.

    Builds the declaration on first call; subsequent calls return the cached
    instance.
    """
    global _declaration_instance
    if _declaration_instance is None:
        _declaration_instance = build_canonical_runtime_declaration()
    return _declaration_instance


def reset_canonical_runtime_declaration() -> None:
    """Reset the global singleton (intended for tests)."""
    global _declaration_instance
    _declaration_instance = None
