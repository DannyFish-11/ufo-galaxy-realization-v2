#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/dual_repo_system_map.py
=============================
Dual-repository system boundary registry and cognitive map.

Purpose
-------
This module is the **single authoritative source** for the structural
reality of the two-repository Galaxy system:

  - ``DannyFish-11/ufo-galaxy-realization-v2`` — V2 (this repo): control /
    orchestration authority
  - ``DannyFish-11/ufo-galaxy-android`` — Android: persistent execution
    participant and local-capability bearer

It solves a documented problem: the V2 codebase contains a large number of
modules named with terms like ``AUTHORITY``, ``SENTINEL``, ``POLICY``,
``CANONICAL``, ``INVARIANT``, ``GATE``, ``READINESS``, ``TRUTH``,
``PROJECTION``, ``POSTURE``, and ``CONVERGENCE``.  The *actual runtime
significance* of these modules varies widely—some are critical runtime entry
points, some are advisory/declarative scaffolding, some are pure semantic
annotations.  Without a central map, reviewers and future contributors
cannot quickly distinguish:

  - which modules are **runtime-critical** (blocking real execution)
  - which modules are **semi-executable** (guard helpers, importable checks)
  - which modules are **declarative-only** (sentinel strings, policy labels,
    audit snapshots—no runtime enforcement)

This module provides:

1. **System plane registry** — maps every major module category to one of
   five planes.
2. **Module semantic type registry** — classifies modules by their actual
   execution role: DECLARATIVE, SEMI_EXECUTABLE, or RUNTIME_CRITICAL.
3. **Dual-repo main-chain path** — explicit declaration of the canonical
   end-to-end execution path across both repositories.
4. **Workstream gap registry** — explicitly registers the known high-priority
   gaps so they cannot be silently lost between PRs.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Machine-checkable** — all registries are plain dicts/enums; the
  companion test module (``tests/test_dual_repo_system_map.py``) validates
  completeness and consistency.
- **No new sentinels without enforcement** — this module deliberately avoids
  adding more ``*_AUTHORITY`` strings.  Its own sentinel is minimal and
  points at the actual runtime entry points it documents.
- **Honest about gaps** — gap entries carry a ``resolved`` flag; unresolved
  gaps are flagged by the test suite.

Planes
------
CONTROL_PLANE
    V2-side orchestration, agent execution, and task lifecycle management.
    Owner: V2 (ufo-galaxy-realization-v2).

EXECUTION_PLANE
    Android-side task execution and local capability delivery.
    Owner: Android (ufo-galaxy-android).

GATEWAY_TRANSPORT
    The WebSocket/HTTP boundary layer between V2 and Android.
    Owner: V2 galaxy_gateway/ module family.

PROVIDER_PLANE
    LLM and model routing layer (OpenAI, Claude, Ollama, etc.).
    Owner: V2 core/unified/ module family.

TRUTH_CONTINUITY_PLANE
    Session state, device identity (UDM), task lifecycle truth,
    reconnect/replay, and migration.
    Owner: V2 core/ truth/session module family.

Module semantic types
---------------------
RUNTIME_CRITICAL
    Module contains code that is exercised on every real request or is
    structurally necessary for the system to start.  A failure or missing
    import here breaks real functionality.

SEMI_EXECUTABLE
    Module contains guard functions, assertion helpers, or gate evaluators
    that *can* be called at runtime but are only exercised when explicitly
    invoked (e.g. in CI, release gate, or diagnostic paths).  Not called on
    every request.

DECLARATIVE
    Module contains sentinel strings, policy labels, posture snapshots, or
    classification enumerations.  It provides human/CI-readable declarations
    but has no runtime enforcement effect.  Its absence would not break any
    user-facing execution path.

Workstream gap severity levels
-------------------------------
P0  Directly affects reliability or correctness of the dual-repo main chain.
    Cannot be left open indefinitely.
P1  Significant gap in verifiability or safety; should be addressed in the
    next major PR cycle.
P2  Meaningful improvement but not blocking; can be deferred.

Public surface
--------------
Constants::

    DUAL_REPO_SYSTEM_MAP_VERSION

Enumerations::

    SystemPlane
    ModuleSemanticType
    GapSeverity

Data classes::

    PlaneEntry
    ModuleSemanticEntry
    WorkstreamGapEntry

Registries::

    SYSTEM_PLANE_REGISTRY
    MODULE_SEMANTIC_TYPE_REGISTRY
    WORKSTREAM_GAP_REGISTRY

Functions::

    get_plane(module_path) -> Optional[SystemPlane]
    get_semantic_type(module_path) -> Optional[ModuleSemanticType]
    list_modules_by_plane(plane) -> List[str]
    list_modules_by_semantic_type(semantic_type) -> List[str]
    list_open_gaps_by_severity(severity) -> List[WorkstreamGapEntry]
    build_system_map_snapshot() -> dict
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger("Galaxy.DualRepoSystemMap")

__all__ = [
    "DUAL_REPO_SYSTEM_MAP_VERSION",
    # Enumerations
    "SystemPlane",
    "ModuleSemanticType",
    "GapSeverity",
    # Data classes
    "PlaneEntry",
    "ModuleSemanticEntry",
    "WorkstreamGapEntry",
    # Registries
    "SYSTEM_PLANE_REGISTRY",
    "MODULE_SEMANTIC_TYPE_REGISTRY",
    "WORKSTREAM_GAP_REGISTRY",
    # Functions
    "get_plane",
    "get_semantic_type",
    "list_modules_by_plane",
    "list_modules_by_semantic_type",
    "list_open_gaps_by_severity",
    "build_system_map_snapshot",
    # Main-chain declaration
    "DUAL_REPO_MAIN_CHAIN",
]

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

DUAL_REPO_SYSTEM_MAP_VERSION: str = "1.0.0"
"""Semantic version of this map.  Increment when registries change materially."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SystemPlane(str, Enum):
    """The five planes of the dual-repo Galaxy system.

    Each plane has a clear owner and boundary.
    """

    CONTROL_PLANE = "CONTROL_PLANE"
    """V2 orchestration, agent execution, task lifecycle management."""

    EXECUTION_PLANE = "EXECUTION_PLANE"
    """Android-side task execution and local capability delivery."""

    GATEWAY_TRANSPORT = "GATEWAY_TRANSPORT"
    """WebSocket/HTTP boundary layer between V2 and Android."""

    PROVIDER_PLANE = "PROVIDER_PLANE"
    """LLM and model routing (OpenAI, Claude, Ollama, etc.)."""

    TRUTH_CONTINUITY_PLANE = "TRUTH_CONTINUITY_PLANE"
    """Session state, device identity (UDM), task lifecycle truth,
    reconnect/replay, and migration."""


class ModuleSemanticType(str, Enum):
    """The three semantic execution roles a module can have.

    This is the key distinction that has been unclear in the V2 codebase:
    not every module named AUTHORITY/SENTINEL/POLICY/GATE is a runtime gate.
    """

    RUNTIME_CRITICAL = "RUNTIME_CRITICAL"
    """Module is exercised on every real request or is structurally required
    for system startup.  Missing or broken → real functionality breaks."""

    SEMI_EXECUTABLE = "SEMI_EXECUTABLE"
    """Module contains callable guards/gates/assertions that can enforce
    behavior but are only invoked in explicit CI/diagnostic/gate call sites.
    Not called on every user request."""

    DECLARATIVE = "DECLARATIVE"
    """Module contains sentinel strings, policy labels, snapshot builders,
    or classification enumerations.  Provides human/CI-readable declarations
    with no runtime enforcement effect."""


class GapSeverity(str, Enum):
    """Priority level for workstream gaps."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PlaneEntry:
    """An entry in the system plane registry."""

    module_path: str
    """Dotted Python module path (e.g. 'core.api_routes')."""

    plane: SystemPlane
    """The plane this module belongs to."""

    notes: str = ""
    """Optional clarifying notes."""


@dataclass
class ModuleSemanticEntry:
    """An entry in the module semantic type registry."""

    module_path: str
    """Dotted Python module path."""

    semantic_type: ModuleSemanticType
    """The actual execution role of this module."""

    naming_pattern: str = ""
    """The authority/sentinel/policy naming pattern this module uses."""

    notes: str = ""
    """Optional clarifying notes (especially important for DECLARATIVE entries
    that might appear to be enforcement modules based on their name)."""


@dataclass
class WorkstreamGapEntry:
    """A registered high-priority system gap."""

    gap_id: str
    """Short unique identifier (e.g. 'GAP_JOINT_INTEGRATION_TEST')."""

    title: str
    """Human-readable title."""

    severity: GapSeverity
    """P0 / P1 / P2."""

    description: str
    """Accurate, non-misleading description of the gap."""

    resolved: bool = False
    """True only when the gap has been closed by a concrete PR.
    Do NOT set to True based on declarative/sentinel PRs alone."""

    resolution_pr: str = ""
    """PR reference (e.g. '#850') when resolved."""

    resolution_evidence: str = ""
    """Formal evidence binding for the resolution: test file(s), workflow job(s),
    and implementation references that prove the gap is closed.  Must be non-empty
    for any resolved P0 gap."""


# ---------------------------------------------------------------------------
# Dual-repo main chain declaration
# ---------------------------------------------------------------------------

DUAL_REPO_MAIN_CHAIN: List[str] = [
    # V2 side
    "main.py (FastAPI app startup)",
    "core.openclawd.OpenClawd (orchestration hub)",
    "core.command_router.CommandRouter (command dispatch)",
    "galaxy_gateway.routing.device_router.DeviceRouter (device routing)",
    "galaxy_gateway.websocket_handler.dispatch_to_websocket (transport dispatch)",
    # Cross-repo boundary (V2 → Android)
    "[WebSocket/HTTP: galaxy_gateway /ws/device/{device_id}]",
    # Android side
    "ufo-galaxy-android: GalaxyAndroidService (persistent background service)",
    "ufo-galaxy-android: WebSocketClient (connection and reconnect)",
    "ufo-galaxy-android: CommandDispatcher (local capability dispatch)",
    "ufo-galaxy-android: AccessibilityService / InputService (screen/touch/keyboard)",
    # Android → V2 result path
    "[WebSocket result message back to galaxy_gateway]",
    "core.canonical_completion_ingress.CanonicalCompletionIngress (result ingress)",
    "core.unified_runtime_truth_ingress (UDM / session state update)",
]
"""Ordered list of nodes in the canonical dual-repo end-to-end execution path.

This is the ground-truth chain.  Any module claiming to be on the main chain
should trace its position here.  Modules that are additive/advisory/declarative
are NOT part of this chain.
"""


# ---------------------------------------------------------------------------
# System plane registry
# ---------------------------------------------------------------------------

SYSTEM_PLANE_REGISTRY: List[PlaneEntry] = [
    # -----------------------------------------------------------------------
    # CONTROL_PLANE — V2 orchestration and agent execution
    # -----------------------------------------------------------------------
    PlaneEntry("core.openclawd", SystemPlane.CONTROL_PLANE,
               "Primary orchestration hub; owns task lifecycle on V2 side"),
    PlaneEntry("core.command_router", SystemPlane.CONTROL_PLANE,
               "Routes commands from OpenClawd to device/execution layer"),
    PlaneEntry("core.agent_factory", SystemPlane.CONTROL_PLANE,
               "Agent instantiation and capability assignment"),
    PlaneEntry("core.task_graph", SystemPlane.CONTROL_PLANE,
               "Task dependency graph management"),
    PlaneEntry("core.canonical_task", SystemPlane.CONTROL_PLANE,
               "Canonical task data contract"),
    PlaneEntry("core.canonical_task_dispatch_chain", SystemPlane.CONTROL_PLANE,
               "Task dispatch chain in control plane"),
    PlaneEntry("core.api_routes", SystemPlane.CONTROL_PLANE,
               "REST API aggregation entry point"),
    PlaneEntry("main", SystemPlane.CONTROL_PLANE,
               "System startup and FastAPI app"),

    # -----------------------------------------------------------------------
    # EXECUTION_PLANE — Android-side execution (other repo)
    # -----------------------------------------------------------------------
    PlaneEntry("android:GalaxyAndroidService", SystemPlane.EXECUTION_PLANE,
               "Persistent background service; receives and executes commands"),
    PlaneEntry("android:WebSocketClient", SystemPlane.EXECUTION_PLANE,
               "Maintains persistent connection to V2 gateway"),
    PlaneEntry("android:CommandDispatcher", SystemPlane.EXECUTION_PLANE,
               "Dispatches commands to local capability handlers"),
    PlaneEntry("android:AccessibilityService", SystemPlane.EXECUTION_PLANE,
               "Provides screen/touch/keyboard capabilities"),
    PlaneEntry("android:OfflineQueue", SystemPlane.EXECUTION_PLANE,
               "Queues commands during disconnection for replay on reconnect"),

    # -----------------------------------------------------------------------
    # GATEWAY_TRANSPORT — V2/Android boundary layer
    # -----------------------------------------------------------------------
    PlaneEntry("galaxy_gateway.routes.websocket", SystemPlane.GATEWAY_TRANSPORT,
               "CANONICAL device ingress /ws/device/{device_id}"),
    PlaneEntry("galaxy_gateway.routing.device_router", SystemPlane.GATEWAY_TRANSPORT,
               "Device selection and WebSocket dispatch"),
    PlaneEntry("galaxy_gateway.websocket_handler", SystemPlane.GATEWAY_TRANSPORT,
               "WebSocket lifecycle management and dispatch_to_websocket"),
    PlaneEntry("galaxy_gateway.protocol.aip_v3", SystemPlane.GATEWAY_TRANSPORT,
               "AIP v3 message protocol (canonical cross-repo envelope)"),
    PlaneEntry("core.android_bridge", SystemPlane.GATEWAY_TRANSPORT,
               "Android device registration/heartbeat/disconnect handler (UDM write)"),
    PlaneEntry("core.android_runtime_dispatch_binding", SystemPlane.GATEWAY_TRANSPORT,
               "Binds Android runtime state updates to device dispatch"),

    # -----------------------------------------------------------------------
    # PROVIDER_PLANE — LLM and model routing
    # -----------------------------------------------------------------------
    PlaneEntry("core.unified.llm_router", SystemPlane.PROVIDER_PLANE,
               "UnifiedLLMRouter: sole legitimate model-access entry for orchestration"),
    PlaneEntry("core.multi_llm_router", SystemPlane.PROVIDER_PLANE,
               "MultiLLMRouter: execution backend for provider selection/failover"),
    PlaneEntry("core.unified.config_manager", SystemPlane.PROVIDER_PLANE,
               "Unified configuration management for provider layer"),

    # -----------------------------------------------------------------------
    # TRUTH_CONTINUITY_PLANE — session, UDM, task truth, reconnect/replay
    # -----------------------------------------------------------------------
    PlaneEntry("core.unified_runtime_truth_ingress", SystemPlane.TRUTH_CONTINUITY_PLANE,
               "Ingest Android runtime state updates into UDM (NEAR_MAINLINE: additive, not hard-enforced)"),
    PlaneEntry("core.canonical_completion_ingress", SystemPlane.TRUTH_CONTINUITY_PLANE,
               "Canonical task result ingress; writes completion to session truth"),
    PlaneEntry("core.canonical_session_truth", SystemPlane.TRUTH_CONTINUITY_PLANE,
               "Session truth data contract"),
    PlaneEntry("core.canonical_session_axis", SystemPlane.TRUTH_CONTINUITY_PLANE,
               "Session identifier axis definition"),
    PlaneEntry("core.device_registry", SystemPlane.TRUTH_CONTINUITY_PLANE,
               "UDM — Unified Device Model: SSOT for device identity and state"),
    PlaneEntry("core.attached_runtime_session_registry", SystemPlane.TRUTH_CONTINUITY_PLANE,
               "Registry of active runtime sessions"),
]


# ---------------------------------------------------------------------------
# Module semantic type registry
# ---------------------------------------------------------------------------
# Key rule: a module's NAME does not determine its type.
# Only its actual runtime call pattern does.

MODULE_SEMANTIC_TYPE_REGISTRY: List[ModuleSemanticEntry] = [
    # -----------------------------------------------------------------------
    # RUNTIME_CRITICAL — called on real requests or required for startup
    # -----------------------------------------------------------------------
    ModuleSemanticEntry(
        "core.openclawd",
        ModuleSemanticType.RUNTIME_CRITICAL,
        notes="Primary orchestration hub; all user requests flow through here",
    ),
    ModuleSemanticEntry(
        "core.command_router",
        ModuleSemanticType.RUNTIME_CRITICAL,
        notes="Routes every command in the main dispatch path",
    ),
    ModuleSemanticEntry(
        "galaxy_gateway.routes.websocket",
        ModuleSemanticType.RUNTIME_CRITICAL,
        notes="Canonical WebSocket ingress; all Android connections go here",
    ),
    ModuleSemanticEntry(
        "galaxy_gateway.routing.device_router",
        ModuleSemanticType.RUNTIME_CRITICAL,
        notes="Selects device and dispatches; called on every device command",
    ),
    ModuleSemanticEntry(
        "core.unified.llm_router",
        ModuleSemanticType.RUNTIME_CRITICAL,
        notes="LLM routing entry; called on every AI inference request after PR-837 fix",
    ),
    ModuleSemanticEntry(
        "core.android_bridge",
        ModuleSemanticType.RUNTIME_CRITICAL,
        notes="Handles Android registration/heartbeat/disconnect; UDM writes are live",
    ),
    ModuleSemanticEntry(
        "core.canonical_completion_ingress",
        ModuleSemanticType.RUNTIME_CRITICAL,
        notes="Result ingress on task completion; live path",
    ),
    ModuleSemanticEntry(
        "core.device_registry",
        ModuleSemanticType.RUNTIME_CRITICAL,
        notes="UDM; all device state reads/writes flow through here at runtime",
    ),
    ModuleSemanticEntry(
        "core.api_routes",
        ModuleSemanticType.RUNTIME_CRITICAL,
        notes="REST API aggregation; loaded at startup",
    ),

    # -----------------------------------------------------------------------
    # SEMI_EXECUTABLE — callable guards/gates, only invoked explicitly
    # -----------------------------------------------------------------------
    ModuleSemanticEntry(
        "core.capability_routing_gate",
        ModuleSemanticType.SEMI_EXECUTABLE,
        naming_pattern="GATE / AUTHORITY",
        notes=(
            "evaluate_capability_gate() is a real function and is now wired "
            "into send_gateway_command() via "
            "core.gateway_capability_default_enforcement.  "
            "GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT closed: the gate is a "
            "default-enforced invariant on the canonical gateway path, not "
            "an additive optional layer."
        ),
    ),
    ModuleSemanticEntry(
        "core.capability_tier",
        ModuleSemanticType.SEMI_EXECUTABLE,
        naming_pattern="AUTHORITY / POLICY",
        notes=(
            "assert_main_chain_capability() is callable but only used in tests "
            "and explicit call sites; not invoked on every dispatch."
        ),
    ),
    ModuleSemanticEntry(
        "core.unified.release_gate",
        ModuleSemanticType.SEMI_EXECUTABLE,
        naming_pattern="GATE",
        notes=(
            "ReleaseGate.require_enabled() is real but get_release_gate() "
            "returns a new instance each call; no state persistence. "
            "Distributed release gate now enforcing: "
            "core.distributed_release_gate_skeleton produces is_enforcing=True "
            "reports; governance_gate_enforcement.yml blocks CI on FAIL verdict."
        ),
    ),
    ModuleSemanticEntry(
        "core.cross_repo_consistency_gates",
        ModuleSemanticType.SEMI_EXECUTABLE,
        naming_pattern="GATE / AUTHORITY",
        notes=(
            "build_consistency_gate_snapshot() returns structured results; "
            "non-breaking by design (reports drift but does not raise). "
            "Wired into CI via governance_gate_enforcement.yml: "
            "failed_gates > 0 causes CI exit 1, blocking merges on drift."
        ),
    ),
    ModuleSemanticEntry(
        "core.governance_validation_gate",
        ModuleSemanticType.SEMI_EXECUTABLE,
        naming_pattern="GATE",
        notes=(
            "run_governance_verdict_ci() is called by governance_gate_enforcement.yml "
            "on every push/PR to main; exit code 1 on FAIL blocks CI. "
            "GovernanceValidationGate.validate() is still advisory when called "
            "without enforce=True, but CI now enforces the FAIL path."
        ),
    ),
    ModuleSemanticEntry(
        "core.unified_runtime_truth_ingress",
        ModuleSemanticType.SEMI_EXECUTABLE,
        naming_pattern="TRUTH / INGRESS",
        notes=(
            "ingest_android_runtime_state_update() is callable and correct, "
            "but module is additive (not hard-replacing old ingress paths). "
            "websocket_handler.py:588 is a documented live bypass; full "
            "convergence to single ingress is not yet enforced."
        ),
    ),
    ModuleSemanticEntry(
        "core.architecture_invariants",
        ModuleSemanticType.SEMI_EXECUTABLE,
        naming_pattern="INVARIANT",
        notes="Contains callable invariant checkers; invoked in tests/CI only.",
    ),

    # -----------------------------------------------------------------------
    # DECLARATIVE — sentinel strings, policy labels, snapshots
    # -----------------------------------------------------------------------
    ModuleSemanticEntry(
        "core.final_cleanup_invariant_tightening",
        ModuleSemanticType.DECLARATIVE,
        naming_pattern="AUTHORITY / SENTINEL / POLICY / INVARIANT",
        notes=(
            "892-line module added in PR-837. Contains 9 policy sentinel "
            "strings, 5 assert_*_is_canonical() guards (importability only), "
            "CapabilityTier enum, and posture snapshot builder. "
            "Guards prove modules are importable, NOT that bypass paths are "
            "closed. is_final_cleanup_posture_acceptable() reports a snapshot "
            "but does not block execution."
        ),
    ),
    ModuleSemanticEntry(
        "core.architecture_completion",
        ModuleSemanticType.DECLARATIVE,
        naming_pattern="AUTHORITY / SENTINEL",
        notes="Status labels and completion percentage declarations; no runtime effect.",
    ),
    ModuleSemanticEntry(
        "core.architecture_truth_guards",
        ModuleSemanticType.DECLARATIVE,
        naming_pattern="TRUTH / GUARD",
        notes="Declarative truth guard strings; no runtime enforcement.",
    ),
    ModuleSemanticEntry(
        "core.canonical_authoritative_path_convergence",
        ModuleSemanticType.DECLARATIVE,
        naming_pattern="CANONICAL / AUTHORITY / CONVERGENCE",
        notes="Path convergence authority sentinel; declarative registration.",
    ),
    ModuleSemanticEntry(
        "core.authority_boundary_classification",
        ModuleSemanticType.DECLARATIVE,
        naming_pattern="AUTHORITY",
        notes="Classification labels for authority boundaries; no runtime effect.",
    ),
    ModuleSemanticEntry(
        "core.admissibility_policy_convergence",
        ModuleSemanticType.DECLARATIVE,
        naming_pattern="POLICY / CONVERGENCE",
        notes="Policy convergence declarations; no runtime enforcement.",
    ),
    ModuleSemanticEntry(
        "core.architecture_stabilization_baseline",
        ModuleSemanticType.DECLARATIVE,
        naming_pattern="AUTHORITY / SENTINEL",
        notes="Stabilization baseline labels and sentinels.",
    ),
    ModuleSemanticEntry(
        "core.compat_legacy_path_blocking_canonicalization",
        ModuleSemanticType.DECLARATIVE,
        naming_pattern="CANONICAL / POLICY",
        notes=(
            "Declares that legacy paths should be blocked; does not "
            "programmatically block them. No runtime import enforcement."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Workstream gap registry
# ---------------------------------------------------------------------------
# IMPORTANT: resolved=False entries are verified by the test suite.
# Do NOT change resolved=False to resolved=True without a concrete PR reference.

WORKSTREAM_GAP_REGISTRY: List[WorkstreamGapEntry] = [
    WorkstreamGapEntry(
        gap_id="GAP_JOINT_INTEGRATION_TEST",
        title="Dual-repo joint integration test framework missing",
        severity=GapSeverity.P0,
        description=(
            "No automated test framework verifies the full dual-repo path: "
            "V2 gateway → Android WebSocket → local capability execution → "
            "result return → V2 completion ingress. All current tests are "
            "single-repo unit or structural tests. A real Android device or "
            "Android emulator is required for true E2E coverage."
        ),
        resolved=True,
        resolution_pr="GAP_JOINT_INTEGRATION_TEST_CLOSURE_SEPARATED_PROCESS_WS_E2E",
        resolution_evidence=(
            "Test file: tests/integration/test_separated_process_ws_e2e.py; "
            "Server helper: tests/integration/_ws_e2e_server_helper.py; "
            "CI workflow job: .github/workflows/dual_repo_integration.yml "
            "#separated-process-ws-e2e [BLOCKING]; "
            "Closure audit: core.platform_closure_audit "
            "GAP_JOINT_INTEGRATION_TEST → GapClosureStatus.CLOSED"
        ),
    ),
    WorkstreamGapEntry(
        gap_id="GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT",
        title="capability_routing_gate not enforced by default in send_gateway_command",
        severity=GapSeverity.P0,
        description=(
            "evaluate_capability_gate() exists and is correct, but "
            "send_gateway_command() passes device_id explicitly in many call "
            "sites without required_capabilities, causing _effective_caps=None "
            "and silently skipping the capability gate. The gate is advisory, "
            "not a default-enforced invariant."
        ),
        resolved=True,
        resolution_pr="GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT_CLOSURE_V1",
        resolution_evidence=(
            "Implementation: "
            "core.gateway_capability_default_enforcement"
            ".enforce_gateway_default_capability_gate; "
            "core.capability_enforcement_hardener.enforce_mainline_capability_gate; "
            "Test files: tests/test_pr4_entry_mode_readiness.py; "
            "tests/test_pr4_config_driven_inventory.py; "
            "CI workflow job: .github/workflows/dual_repo_integration.yml "
            "#capability-enforcement-gate [BLOCKING]; "
            "Closure audit: core.platform_closure_audit "
            "GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT → GapClosureStatus.CLOSED"
        ),
    ),
    WorkstreamGapEntry(
        gap_id="GAP_V2_TRUTH_PERSISTENCE",
        title="V2 task lifecycle and session truth persistence on restart missing",
        severity=GapSeverity.P0,
        description=(
            "core.unified_runtime_truth_ingress and core.canonical_session_truth "
            "exist but do not persist to durable storage. On V2 restart, all "
            "in-progress task state and session truth is lost. No restart recovery "
            "mechanism exists for V2-side state."
        ),
        resolved=True,
        resolution_pr="#850",
        resolution_evidence=(
            "Implementation: core.runtime_restart_recovery.RuntimeRestartRecoveryCoordinator; "
            "core.canonical_session_truth.CanonicalSessionTruthRuntime; "
            "core.task_lifecycle_persistence.TaskLifecyclePersistenceStore; "
            "Test files: tests/test_gap_v2_truth_persistence_closure.py; "
            "tests/test_pr5_runtime_restart_recovery.py; "
            "Closure audit: core.platform_closure_audit "
            "GAP_V2_TRUTH_PERSISTENCE → GapClosureStatus.CLOSED"
        ),
    ),
    WorkstreamGapEntry(
        gap_id="GAP_RUNTIME_TRUTH_SINGLE_INGRESS",
        title="Runtime truth ingress convergence incomplete (multiple active paths)",
        severity=GapSeverity.P1,
        description=(
            "unified_runtime_truth_ingress.py is additive; it does not replace "
            "old ingress paths. websocket_handler.py:588 is a documented live "
            "bypass that writes device state directly without going through "
            "the canonical ingress. Full convergence to single ingress "
            "is not yet enforced."
        ),
        resolved=False,
    ),
    WorkstreamGapEntry(
        gap_id="GAP_ANDROID_CI",
        title="Android repository (ufo-galaxy-android) CI pipeline missing",
        severity=GapSeverity.P1,
        description=(
            "ufo-galaxy-android has no automated CI pipeline. Android-side "
            "contract regressions (WebSocket protocol, command envelope, "
            "capability reporting) are not caught automatically. This is "
            "particularly risky given the AIP v3 protocol dependency."
        ),
        resolved=False,
    ),
    WorkstreamGapEntry(
        gap_id="GAP_ANDROID_LOCAL_AI_DEFAULT_OFF",
        title="Android local AI inference runtime libraries not bundled in APK build",
        severity=GapSeverity.P1,
        description=(
            "Android local AI model download pipeline (8-stage HuggingFace "
            "provisioning for MobileVLM V2-1.7B and SeeClick), service "
            "interfaces (LocalPlannerService, LocalGroundingService), and "
            "capability-report wiring are all implemented.  However, the "
            "native inference runtime libraries are absent from app/build.gradle: "
            "(1) llama.cpp Android binding is missing — required for MobileVLM "
            "GGUF execution via LocalPlannerService; "
            "(2) NCNN Android AAR is missing — required for SeeClick CNN "
            "inference via LocalGroundingService. "
            "V2-side status: core/canonical_capability_status.py now classifies "
            "local_ai, local_grounding, local_planner, on_device_inference as "
            "DEGRADED (upgraded from STRUCTURAL_ONLY) — V2-side done. "
            "Remaining work: add llama.cpp-android and ncnn-android to "
            "ufo-galaxy-android app/build.gradle.  Reference template at "
            "android_client/build.gradle.template."
        ),
        resolved=False,
        resolution_evidence=(
            "V2-side partial: canonical_capability_status.py upgraded local_ai "
            "group from STRUCTURAL_ONLY to DEGRADED.  Android build.gradle "
            "changes still required in ufo-galaxy-android repo."
        ),
    ),
    WorkstreamGapEntry(
        gap_id="GAP_RELEASE_GATE_HARD_ENFORCEMENT",
        title="Governance/release gate not wired to hard CI or deploy blocking",
        severity=GapSeverity.P2,
        description=(
            "ReleaseGate, GovernanceValidationGate, and readiness checks exist "
            "but are advisory. get_release_gate() returns a new instance each "
            "call (no persistent state). is_final_cleanup_posture_acceptable() "
            "is not called in any CI blocking step. Production code almost "
            "never calls require_enabled()."
        ),
        resolved=False,
    ),
    WorkstreamGapEntry(
        gap_id="GAP_DURABLE_TRUTH_AUTHORITY_CONVERGENCE",
        title="Session truth, task lifecycle, and result continuity form parallel persistence fragments rather than a unified authority chain",
        severity=GapSeverity.P1,
        description=(
            "After PR-1 (GAP_V2_TRUTH_PERSISTENCE closure), V2 gained "
            "SessionTruthSnapshotStore, TaskLifecyclePersistenceStore, and "
            "DurableResultIdSet.  However, the CanonicalSessionTruthRuntime "
            "ring buffer was described as 'the authoritative runtime read surface' "
            "while durable stores were described as forensic/audit sinks.  "
            "This creates semantic ambiguity: are the runtime ring buffer and "
            "durable stores competing truth sources?  A unified authority "
            "declaration (durable path IS the authority; ring buffer is a "
            "read-cache) was missing."
        ),
        resolved=True,
        resolution_pr="PR-2::core.durable_truth_authority_chain",
    ),
    WorkstreamGapEntry(
        gap_id="GAP_CONTINUATION_REBIND_CLOSED_LOOP",
        title="Continuation/waiter cross-restart rebind (second half of closed loop) not tracked",
        severity=GapSeverity.P1,
        description=(
            "PR-1 added _reconcile_continuation_waiters() which fails stale "
            "asyncio.Future waiters with a restart error (first half of the "
            "closed loop).  However, there was no mechanism to track the "
            "second half: re-dispatch → new waiter registered → result "
            "delivered.  Without this, the control chain 'restarts from "
            "scratch' with no structural proof that the loop was closed after "
            "the restart."
        ),
        resolved=True,
        resolution_pr="PR-2::core.continuation_rebind_registry",
    ),
    WorkstreamGapEntry(
        gap_id="GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION",
        title="Multi-device, delegated takeover, and failure/recovery paths lack automated network-level integration assurance",
        severity=GapSeverity.P0,
        description=(
            "Existing separated-process E2E covers the single-participant "
            "happy path at true network/transport level (GAP_JOINT_INTEGRATION_TEST "
            "closure).  However, multi-device concurrent registration, per-device "
            "capability isolation, delegated takeover (eligibility → assignment → "
            "result propagation → continuation), participant disconnect/reconnect "
            "with task recovery, degraded-participant handling, and capability "
            "mismatch routing are not covered by any automated network-level test. "
            "CI has no blocking gate for regressions in these paths."
        ),
        resolved=True,
        resolution_pr=(
            "#854 (PR-7): tests/integration/test_multi_device_failure_recovery_e2e.py "
            "covers 8 network-level scenarios: multi-device concurrent registration, "
            "per-device capability isolation, concurrent task execution, delegated "
            "takeover with result continuity, disconnect/reconnect/recovery, "
            "capability mismatch routing, multi-device result aggregation, and "
            "degraded participant handling.  CI gate added in "
            ".github/workflows/dual_repo_integration.yml "
            "(multi-device-failure-recovery-e2e job)."
        ),
        resolution_evidence=(
            "Test file: tests/integration/test_multi_device_failure_recovery_e2e.py; "
            "Server helper: tests/integration/_ws_e2e_multi_device_server_helper.py; "
            "Implementation: core.multi_device_runtime_harness; "
            "CI workflow job: .github/workflows/dual_repo_integration.yml "
            "#multi-device-failure-recovery-e2e [BLOCKING]; "
            "Closure audit: core.platform_closure_audit "
            "GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION → GapClosureStatus.CLOSED"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------


def get_plane(module_path: str) -> Optional[SystemPlane]:
    """Return the :class:`SystemPlane` for *module_path*, or ``None``.

    Parameters
    ----------
    module_path : str
        Dotted Python module path or android: prefixed path.
    """
    for entry in SYSTEM_PLANE_REGISTRY:
        if entry.module_path == module_path:
            return entry.plane
    return None


def get_semantic_type(module_path: str) -> Optional[ModuleSemanticType]:
    """Return the :class:`ModuleSemanticType` for *module_path*, or ``None``."""
    for entry in MODULE_SEMANTIC_TYPE_REGISTRY:
        if entry.module_path == module_path:
            return entry.semantic_type
    return None


def list_modules_by_plane(plane: SystemPlane) -> List[str]:
    """Return sorted list of module paths in *plane*."""
    return sorted(e.module_path for e in SYSTEM_PLANE_REGISTRY if e.plane == plane)


def list_modules_by_semantic_type(semantic_type: ModuleSemanticType) -> List[str]:
    """Return sorted list of module paths with *semantic_type*."""
    return sorted(
        e.module_path
        for e in MODULE_SEMANTIC_TYPE_REGISTRY
        if e.semantic_type == semantic_type
    )


def list_open_gaps_by_severity(severity: GapSeverity) -> List[WorkstreamGapEntry]:
    """Return all open (unresolved) gaps with *severity*."""
    return [
        e for e in WORKSTREAM_GAP_REGISTRY
        if e.severity == severity and not e.resolved
    ]


def build_system_map_snapshot() -> dict:
    """Build a JSON-serialisable snapshot of the system map for CI consumption.

    Returns
    -------
    dict
        Contains version, plane counts, semantic type counts, open gap counts,
        and details of all open P0 gaps.
    """
    open_p0 = list_open_gaps_by_severity(GapSeverity.P0)
    open_p1 = list_open_gaps_by_severity(GapSeverity.P1)
    open_p2 = list_open_gaps_by_severity(GapSeverity.P2)

    plane_counts = {}
    for plane in SystemPlane:
        plane_counts[plane.value] = len(list_modules_by_plane(plane))

    semantic_counts = {}
    for stype in ModuleSemanticType:
        semantic_counts[stype.value] = len(list_modules_by_semantic_type(stype))

    return {
        "version": DUAL_REPO_SYSTEM_MAP_VERSION,
        "plane_counts": plane_counts,
        "semantic_type_counts": semantic_counts,
        "main_chain_node_count": len(DUAL_REPO_MAIN_CHAIN),
        "open_gaps": {
            "P0": [{"id": g.gap_id, "title": g.title} for g in open_p0],
            "P1": [{"id": g.gap_id, "title": g.title} for g in open_p1],
            "P2": [{"id": g.gap_id, "title": g.title} for g in open_p2],
        },
        "total_open_gaps": len(open_p0) + len(open_p1) + len(open_p2),
    }
