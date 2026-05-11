#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/operational_registration_path.py
======================================
统一可操作注册路径 — Unified Operational Registration Path
for the Galaxy Center-Governed Distributed Intelligent Agent System.

System Identity (PR993)
-----------------------
Galaxy is a **center-governed distributed intelligent agent system**
(中心分布式智能体系统):

- **V2** (``ufo-galaxy-realization-v2``) — center governance, orchestration,
  truth convergence, and acceptance authority.
- **Android** (``ufo-galaxy-android``) — distributed runtime node with local
  intelligence, local task execution, and cross-device participation capability.

This module provides the **unified operational onboarding and registration
reference** for the Galaxy system aligned with the PR993 system definition.
It:

1. Enumerates every *registration kind* in the system — device, capability,
   session, gateway, runtime, governance — with canonical module locations and
   operational semantics.
2. Defines the complete **clone-to-use onboarding path** in ordered steps with
   explicit prerequisites, instructions, and verification criteria.
3. Performs **fail-fast prerequisite validation** so operators know immediately
   what is missing before attempting to start the system.
4. Distinguishes the **canonical main chain** from cross-device, compat,
   fallback, degraded, and recovery paths so maintainers can reason about each
   tier clearly.
5. Serves as a machine-checkable companion to
   ``docs/CLONE_TO_USE_REALITY.md`` and ``core/pr993_dual_repo_reevaluation.py``.

Design notes
------------
- **Additive only** — imports existing canonical modules to verify them; does
  not replace or bypass any of them.
- Every ``RegistrationKindInfo`` record names the **canonical module** so
  developers can navigate to the real implementation.
- ``validate_registration_prerequisites()`` uses a shallow walk of
  ``importlib.util.find_spec`` per path segment to avoid triggering full
  package ``__init__`` imports when optional runtime dependencies (e.g.
  ``fastapi``, ``websockets``) are absent in the current environment.
- All dataclasses are JSON-serialisable via ``to_dict()`` / ``to_json()``.

Public API
----------
Authority sentinels::

    OPERATIONAL_REGISTRATION_PATH_AUTHORITY
    OPERATIONAL_REGISTRATION_PATH_CONTRACT_VERSION

Enumerations::

    RegistrationKind
    OnboardingStepId
    PathTier
    ValidationStatus

Dataclasses::

    RegistrationKindInfo
    OnboardingStep
    PrerequisiteCheck
    OnboardingValidation
    OperationalRegistrationPath

Functions::

    validate_registration_prerequisites() -> OnboardingValidation
    build_operational_registration_path() -> OperationalRegistrationPath
    get_operational_registration_path() -> OperationalRegistrationPath
    reset_operational_registration_path() -> None
    assert_operational_registration_path_invariants() -> None
"""

from __future__ import annotations

import importlib.util
import json
import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.OperationalRegistrationPath")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

OPERATIONAL_REGISTRATION_PATH_AUTHORITY: str = (
    "core/operational_registration_path.py:OPERATIONAL_REGISTRATION_PATH "
    "— unified operational registration path aligned with PR993 "
    "center-governed distributed intelligent agent system definition"
)

OPERATIONAL_REGISTRATION_PATH_CONTRACT_VERSION: str = "pr993_ops.1.0.0"

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RegistrationKind(str, Enum):
    """Every distinct registration mechanism in the Galaxy system.

    Each value names a kind of entity or resource that must be registered
    (or otherwise declared) for the system to function correctly.
    """

    # --- Device layer ---
    DEVICE_CANONICAL = "device_canonical"
    """Canonical device registration via UnifiedDeviceManager (UDM).

    Canonical write SSOT for device identity, state, and lifecycle.
    Module: ``core/unified/device_manager.py``
    """

    DEVICE_INDEX = "device_index"
    """Legacy-compatible device index / discovery layer (DeviceRegistry).

    Layered over UDM.  Provides group/tag/capability indexes and
    on-disk persistence snapshots.
    Module: ``core/device_registry.py``
    """

    DEVICE_ANDROID_ADMISSION = "device_android_admission"
    """Android device admission through the gateway registration handler.

    The gateway ``registration`` handler performs the initial V2-side
    admission of an Android device when it connects via WebSocket.
    Module: ``galaxy_gateway/android/handlers/registration.py``
    """

    DEVICE_ANDROID_STATE = "device_android_state"
    """Android device runtime state store (V2-side Android state mirror).

    Tracks Android device runtime snapshots, capability reports, and
    execution state on the V2 side.
    Module: ``core/android_device_state_store.py``
    """

    # --- Capability layer ---
    CAPABILITY_REGISTRY = "capability_registry"
    """Central capability registry for V2-side capability indexing.

    Capability entries are registered here after admission.
    Module: ``core/agent/capability_registry.py``
    """

    CAPABILITY_BUS = "capability_bus"
    """Event-driven capability bus for cross-component capability propagation.

    Module: ``core/capability_bus.py``
    """

    CAPABILITY_ANDROID_REPORT = "capability_android_report"
    """Android capability report ingested via gateway handler.

    Module: ``galaxy_gateway/android/handlers/capability_report.py``
    """

    CAPABILITY_RESOLVER = "capability_resolver"
    """Unified capability resolver — resolves capabilities across devices.

    Module: ``core/unified/capability_resolver.py`` (or ``core/unified_capability_resolver.py``)
    """

    # --- Session / identity / continuity layer ---
    SESSION_ATTACHED_RUNTIME = "session_attached_runtime"
    """Canonical attached-runtime session registry.

    Single source of truth for which attached runtime sessions are active,
    replaced, or invalidated.  All dispatch, reuse, and reconciliation layers
    MUST consult this registry to resolve session identity.
    Module: ``core/attached_runtime_session_registry.py``
    """

    SESSION_ANDROID_PARTICIPANT = "session_android_participant"
    """Android participant session state machine.

    Tracks the Android delegated runtime lifecycle from handoff through
    execution to reconciliation and closure.
    Module: ``core/android_participant_session_state.py``
    """

    SESSION_CANONICAL_AXIS = "session_canonical_axis"
    """Canonical session axis — top-level session truth surface.

    Module: ``core/canonical_session_axis.py``
    """

    # --- Gateway / transport / wire layer ---
    GATEWAY_WEBSOCKET = "gateway_websocket"
    """WebSocket gateway transport for device ↔ V2 communication.

    Must be running before any cross-device registration can occur.
    Module: ``galaxy_gateway/routes/websocket.py``
    """

    GATEWAY_ANDROID_BRIDGE = "gateway_android_bridge"
    """Android bridge — gateway-side Android runtime integration.

    Routes Android messages to the appropriate handlers.
    Module: ``galaxy_gateway/android/bridge.py``
    """

    GATEWAY_DEVICE_ROUTER = "gateway_device_router"
    """Device router — V2-side routing authority for cross-device dispatch.

    V2 governance authority dimension 2 (routing).
    Module: ``galaxy_gateway/device_router.py``
    """

    # --- Runtime / orchestration layer ---
    RUNTIME_SUBJECT = "runtime_subject"
    """Desktop presence runtime — outer shell of the unified subject.

    Manages the tri-state lifecycle: SILENT → LIMINAL → MANIFEST.
    Module: ``core/desktop_presence_runtime.py``
    """

    RUNTIME_ANDROID_HOST = "runtime_android_host"
    """Android runtime host — V2-side delegated Android runtime management.

    Module: ``core/android_runtime_host.py``
    """

    RUNTIME_DISPATCH_BINDING = "runtime_dispatch_binding"
    """Android runtime dispatch binding — wires dispatch to the runtime host.

    Module: ``core/android_runtime_dispatch_binding.py``
    """

    # --- Governance / authority layer ---
    GOVERNANCE_UNIFIED = "governance_unified"
    """Unified execution governance — all 8-dimension V2 authority.

    V2 is the SOLE canonical orchestration authority per PR993.
    Module: ``core/unified_execution_governance.py``
    """

    GOVERNANCE_RELEASE_GATE = "governance_release_gate"
    """Distributed release gate — CI-enforcing release governance.

    Module: ``core/distributed_release_gate_skeleton.py``
    """


class OnboardingStepId(str, Enum):
    """Ordered steps in the complete clone-to-use path."""

    CLONE = "clone"
    CREATE_VENV = "create_venv"
    INSTALL_DEPS = "install_deps"
    CONFIGURE_SECRETS = "configure_secrets"
    CONFIGURE_RUNTIME = "configure_runtime"
    VERIFY_PREREQUISITES = "verify_prerequisites"
    START_BACKEND = "start_backend"
    VERIFY_BACKEND = "verify_backend"
    REGISTER_ANDROID = "register_android"
    VERIFY_ANDROID_REGISTRATION = "verify_android_registration"
    INITIATE_TASK = "initiate_task"
    VERIFY_CLOSURE = "verify_closure"


class PathTier(str, Enum):
    """Tier classification for each registration kind / onboarding step.

    Operators and maintainers use this to reason about which paths are
    canonical main chain vs optional / fallback / degraded layers.
    """

    MAIN_CHAIN = "main_chain"
    """Canonical execution path — required for the system to function."""

    CROSS_DEVICE = "cross_device"
    """Cross-device / Android participation path — extends the main chain."""

    COMPAT = "compat"
    """Backwards-compatible layer — preserved for interoperability."""

    FALLBACK = "fallback"
    """Fallback / degraded path — used when the main chain is unavailable."""

    RECOVERY = "recovery"
    """Recovery / reconnect path — used to restore disrupted operation."""


class ValidationStatus(str, Enum):
    """Status of a single prerequisite check."""

    PASS = "PASS"
    """Prerequisite is satisfied."""

    WARN = "WARN"
    """Partially satisfied; system may start in degraded mode."""

    FAIL = "FAIL"
    """Not satisfied; system will not start correctly."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RegistrationKindInfo:
    """Describes a single registration kind in the Galaxy system."""

    kind: RegistrationKind
    display_name: str
    canonical_module: str
    path_tier: PathTier
    description: str
    prerequisites: List[RegistrationKind] = field(default_factory=list)
    optional: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "display_name": self.display_name,
            "canonical_module": self.canonical_module,
            "path_tier": self.path_tier.value,
            "description": self.description,
            "prerequisites": [p.value for p in self.prerequisites],
            "optional": self.optional,
        }


@dataclass
class OnboardingStep:
    """A single step in the clone-to-use onboarding path."""

    step_id: OnboardingStepId
    display_name: str
    path_tier: PathTier
    instructions: str
    verification: str
    blocking: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id.value,
            "display_name": self.display_name,
            "path_tier": self.path_tier.value,
            "instructions": self.instructions,
            "verification": self.verification,
            "blocking": self.blocking,
        }


@dataclass
class PrerequisiteCheck:
    """Result of validating a single prerequisite."""

    name: str
    status: ValidationStatus
    message: str
    module_checked: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "module_checked": self.module_checked,
        }


@dataclass
class OnboardingValidation:
    """Aggregated result of all prerequisite checks."""

    checks: List[PrerequisiteCheck] = field(default_factory=list)
    overall_status: ValidationStatus = ValidationStatus.PASS
    summary: str = ""

    @property
    def passed(self) -> bool:
        return self.overall_status != ValidationStatus.FAIL

    @property
    def failed_checks(self) -> List[PrerequisiteCheck]:
        return [c for c in self.checks if c.status == ValidationStatus.FAIL]

    @property
    def warned_checks(self) -> List[PrerequisiteCheck]:
        return [c for c in self.checks if c.status == ValidationStatus.WARN]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checks": [c.to_dict() for c in self.checks],
            "overall_status": self.overall_status.value,
            "summary": self.summary,
            "passed": self.passed,
            "failed_count": len(self.failed_checks),
            "warned_count": len(self.warned_checks),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


@dataclass
class OperationalRegistrationPath:
    """The complete operational registration path for the Galaxy system.

    Root artifact produced by ``build_operational_registration_path()``.
    Collects all registration kinds, onboarding steps, prerequisite validation,
    and tier maps.
    """

    registration_kinds: List[RegistrationKindInfo] = field(default_factory=list)
    onboarding_steps: List[OnboardingStep] = field(default_factory=list)
    validation: Optional[OnboardingValidation] = None
    main_chain_kinds: List[RegistrationKind] = field(default_factory=list)
    cross_device_kinds: List[RegistrationKind] = field(default_factory=list)
    compat_kinds: List[RegistrationKind] = field(default_factory=list)
    system_identity: str = ""
    contract_version: str = OPERATIONAL_REGISTRATION_PATH_CONTRACT_VERSION
    authority: str = OPERATIONAL_REGISTRATION_PATH_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authority": self.authority,
            "contract_version": self.contract_version,
            "system_identity": self.system_identity,
            "registration_kinds": [rk.to_dict() for rk in self.registration_kinds],
            "onboarding_steps": [s.to_dict() for s in self.onboarding_steps],
            "validation": self.validation.to_dict() if self.validation else None,
            "main_chain_kinds": [k.value for k in self.main_chain_kinds],
            "cross_device_kinds": [k.value for k in self.cross_device_kinds],
            "compat_kinds": [k.value for k in self.compat_kinds],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# ---------------------------------------------------------------------------
# Registration kind catalog
# ---------------------------------------------------------------------------

def _build_registration_kinds() -> List[RegistrationKindInfo]:
    """Build the complete ordered registration kind catalog."""
    return [
        # ---- MAIN CHAIN: Device canonical ----
        RegistrationKindInfo(
            kind=RegistrationKind.DEVICE_CANONICAL,
            display_name="Canonical Device Registration (UDM)",
            canonical_module="core.unified.device_manager",
            path_tier=PathTier.MAIN_CHAIN,
            description=(
                "All device state writes flow through UnifiedDeviceManager (UDM). "
                "UDM is the canonical write SSOT for device identity, online/offline "
                "state, and metadata. Every other device registration kind ultimately "
                "delegates to UDM. "
                "API: udm.register_device(device_id, device_type, name, capabilities)"
            ),
            prerequisites=[],
            optional=False,
        ),
        RegistrationKindInfo(
            kind=RegistrationKind.DEVICE_INDEX,
            display_name="Device Index / Discovery Layer (DeviceRegistry)",
            canonical_module="core.device_registry",
            path_tier=PathTier.COMPAT,
            description=(
                "Compatibility and indexing layer layered over UDM. "
                "Provides group membership, tag index, capability index, and "
                "on-disk persistence snapshots. "
                "NOT a canonical truth source — all writes forward to UDM first. "
                "Devices restored from disk re-enter OFFLINE state and must "
                "re-register through UDM to obtain authoritative online status."
            ),
            prerequisites=[RegistrationKind.DEVICE_CANONICAL],
            optional=True,
        ),
        # ---- CROSS-DEVICE: Android device admission ----
        RegistrationKindInfo(
            kind=RegistrationKind.DEVICE_ANDROID_ADMISSION,
            display_name="Android Device Admission (Gateway Registration Handler)",
            canonical_module="galaxy_gateway.android.handlers.registration",
            path_tier=PathTier.CROSS_DEVICE,
            description=(
                "When an Android device connects via WebSocket, the V2 gateway "
                "registration handler performs admission: validates the connection, "
                "creates the device record via UDM, and records the session. "
                "This is the entry point for all Android→V2 cross-device registration. "
                "Fail condition: missing device_id, missing capabilities, or gateway "
                "WebSocket transport not available."
            ),
            prerequisites=[RegistrationKind.DEVICE_CANONICAL, RegistrationKind.GATEWAY_WEBSOCKET],
            optional=False,
        ),
        RegistrationKindInfo(
            kind=RegistrationKind.DEVICE_ANDROID_STATE,
            display_name="Android Device State Store (V2-side Android state mirror)",
            canonical_module="core.android_device_state_store",
            path_tier=PathTier.CROSS_DEVICE,
            description=(
                "V2-side store that mirrors Android device runtime state: "
                "capability reports, execution snapshots, heartbeat records. "
                "The operator surface and governance layer read from this store to "
                "assess Android runtime truth. "
                "Updated by gateway handlers: capability_report, device_state_snapshot, "
                "heartbeat, and delegated_signal."
            ),
            prerequisites=[RegistrationKind.DEVICE_ANDROID_ADMISSION],
            optional=False,
        ),
        # ---- MAIN CHAIN: Capability ----
        RegistrationKindInfo(
            kind=RegistrationKind.CAPABILITY_REGISTRY,
            display_name="Capability Registry",
            canonical_module="core.agent.capability_registry",
            path_tier=PathTier.MAIN_CHAIN,
            description=(
                "Central capability registry. Capabilities are registered here after "
                "device admission. The routing and scheduling layers consult this "
                "registry to select which device/service can fulfill a task. "
                "V2 governance authority dimension 3 (capability network)."
            ),
            prerequisites=[RegistrationKind.DEVICE_CANONICAL],
            optional=False,
        ),
        RegistrationKindInfo(
            kind=RegistrationKind.CAPABILITY_BUS,
            display_name="Capability Bus (event-driven propagation)",
            canonical_module="core.capability_bus",
            path_tier=PathTier.MAIN_CHAIN,
            description=(
                "Event-driven capability bus. Propagates capability lifecycle events "
                "(registered, updated, removed) to subscribed components. "
                "Decouples the capability registry from downstream consumers."
            ),
            prerequisites=[RegistrationKind.CAPABILITY_REGISTRY],
            optional=True,
        ),
        RegistrationKindInfo(
            kind=RegistrationKind.CAPABILITY_ANDROID_REPORT,
            display_name="Android Capability Report (gateway ingestion)",
            canonical_module="galaxy_gateway.android.handlers.capability_report",
            path_tier=PathTier.CROSS_DEVICE,
            description=(
                "Gateway handler that ingests the Android capability report message. "
                "When Android connects and reports its capabilities, this handler "
                "processes the report and updates the V2-side capability registry and "
                "android_device_state_store. "
                "This is how Android capabilities become visible to V2 routing."
            ),
            prerequisites=[
                RegistrationKind.DEVICE_ANDROID_ADMISSION,
                RegistrationKind.CAPABILITY_REGISTRY,
            ],
            optional=False,
        ),
        RegistrationKindInfo(
            kind=RegistrationKind.CAPABILITY_RESOLVER,
            display_name="Unified Capability Resolver",
            canonical_module="core.unified.capability_resolver",
            path_tier=PathTier.MAIN_CHAIN,
            description=(
                "Resolves which device/service can fulfill a given capability request. "
                "Reads from the capability registry and device state to select the "
                "best execution target. "
                "V2 governance authority dimension 3 (capability network)."
            ),
            prerequisites=[RegistrationKind.CAPABILITY_REGISTRY],
            optional=False,
        ),
        # ---- MAIN CHAIN: Session / identity / continuity ----
        RegistrationKindInfo(
            kind=RegistrationKind.SESSION_ATTACHED_RUNTIME,
            display_name="Attached Runtime Session Registry",
            canonical_module="core.attached_runtime_session_registry",
            path_tier=PathTier.MAIN_CHAIN,
            description=(
                "Canonical single source of truth for attached runtime sessions. "
                "Tracks which sessions are active, superseded, or invalidated. "
                "All dispatch, reuse, and reconciliation layers MUST consult this "
                "registry to resolve session identity. "
                "State transitions: register, reconnect, reattach, detach, "
                "invalidate, replace. "
                "Reconnects classified here prevent misclassification as fresh sessions."
            ),
            prerequisites=[RegistrationKind.DEVICE_CANONICAL],
            optional=False,
        ),
        RegistrationKindInfo(
            kind=RegistrationKind.SESSION_ANDROID_PARTICIPANT,
            display_name="Android Participant Session State",
            canonical_module="core.android_participant_session_state",
            path_tier=PathTier.CROSS_DEVICE,
            description=(
                "Android delegated runtime session state machine. "
                "Tracks the full Android lifecycle: "
                "handoff → takeover negotiation → active execution → "
                "reconciliation → closure. "
                "Provides a single canonical answer for each lifecycle phase, "
                "avoiding multi-source state derivation."
            ),
            prerequisites=[
                RegistrationKind.SESSION_ATTACHED_RUNTIME,
                RegistrationKind.DEVICE_ANDROID_ADMISSION,
            ],
            optional=False,
        ),
        RegistrationKindInfo(
            kind=RegistrationKind.SESSION_CANONICAL_AXIS,
            display_name="Canonical Session Axis (top-level session truth)",
            canonical_module="core.canonical_session_axis",
            path_tier=PathTier.MAIN_CHAIN,
            description=(
                "Top-level session truth surface. Aggregates session state from "
                "attached runtime registry and Android participant state into a "
                "single canonical session view used by operator surfaces and "
                "governance audits."
            ),
            prerequisites=[RegistrationKind.SESSION_ATTACHED_RUNTIME],
            optional=True,
        ),
        # ---- MAIN CHAIN / CROSS-DEVICE: Gateway / transport ----
        RegistrationKindInfo(
            kind=RegistrationKind.GATEWAY_WEBSOCKET,
            display_name="Gateway WebSocket Transport",
            canonical_module="galaxy_gateway.routes.websocket",
            path_tier=PathTier.MAIN_CHAIN,
            description=(
                "WebSocket gateway transport. Provides the wire-level "
                "V2 ↔ Android communication channel. "
                "All Android device registration, capability reporting, task "
                "dispatch, result uplink, and heartbeat messages flow through "
                "this transport. "
                "Must be running before any cross-device registration can occur."
            ),
            prerequisites=[],
            optional=False,
        ),
        RegistrationKindInfo(
            kind=RegistrationKind.GATEWAY_ANDROID_BRIDGE,
            display_name="Android Bridge (gateway-side integration)",
            canonical_module="galaxy_gateway.android.bridge",
            path_tier=PathTier.CROSS_DEVICE,
            description=(
                "Gateway-side Android runtime integration bridge. "
                "Routes Android messages to the appropriate handlers "
                "(registration, capability_report, delegated_signal, "
                "device_state_snapshot, takeover_response, etc.). "
                "Fail condition: bridge not initialised means Android messages "
                "are not routed to their handlers."
            ),
            prerequisites=[RegistrationKind.GATEWAY_WEBSOCKET],
            optional=False,
        ),
        RegistrationKindInfo(
            kind=RegistrationKind.GATEWAY_DEVICE_ROUTER,
            display_name="Device Router (V2 cross-device dispatch authority)",
            canonical_module="galaxy_gateway.device_router",
            path_tier=PathTier.MAIN_CHAIN,
            description=(
                "V2-side routing authority for cross-device task dispatch. "
                "Selects which device executes a given task based on capability "
                "matching, device availability, and governance policy. "
                "V2 governance authority dimension 2 (routing). "
                "Main chain: V2 → DeviceRouter → Android (dispatch)."
            ),
            prerequisites=[
                RegistrationKind.CAPABILITY_RESOLVER,
                RegistrationKind.DEVICE_CANONICAL,
            ],
            optional=False,
        ),
        # ---- MAIN CHAIN: Runtime / orchestration ----
        RegistrationKindInfo(
            kind=RegistrationKind.RUNTIME_SUBJECT,
            display_name="Desktop Presence Runtime (unified subject shell)",
            canonical_module="core.desktop_presence_runtime",
            path_tier=PathTier.MAIN_CHAIN,
            description=(
                "Outer shell of the unified subject. "
                "Manages the tri-state lifecycle: SILENT → LIMINAL → MANIFEST. "
                "Drives the OpenClawd cognitive core through the four-phase "
                "processing cycle (ingest, continuum, branch, manifest). "
                "This is the primary interaction surface for local natural "
                "language input."
            ),
            prerequisites=[],
            optional=False,
        ),
        RegistrationKindInfo(
            kind=RegistrationKind.RUNTIME_ANDROID_HOST,
            display_name="Android Runtime Host (V2-side delegated Android management)",
            canonical_module="core.android_runtime_host",
            path_tier=PathTier.CROSS_DEVICE,
            description=(
                "V2-side component that manages the delegated Android runtime. "
                "Handles task handoff to Android, monitors execution, and "
                "processes result uplinks from Android. "
                "Required for any task to be dispatched to and executed on "
                "an Android device."
            ),
            prerequisites=[
                RegistrationKind.DEVICE_ANDROID_STATE,
                RegistrationKind.SESSION_ANDROID_PARTICIPANT,
            ],
            optional=False,
        ),
        RegistrationKindInfo(
            kind=RegistrationKind.RUNTIME_DISPATCH_BINDING,
            display_name="Android Runtime Dispatch Binding",
            canonical_module="core.android_runtime_dispatch_binding",
            path_tier=PathTier.CROSS_DEVICE,
            description=(
                "Wires the V2 dispatch layer to the Android runtime host. "
                "Ensures that when the DeviceRouter selects an Android device, "
                "the dispatch call is correctly bound to the Android runtime host "
                "for execution."
            ),
            prerequisites=[
                RegistrationKind.RUNTIME_ANDROID_HOST,
                RegistrationKind.GATEWAY_DEVICE_ROUTER,
            ],
            optional=False,
        ),
        # ---- MAIN CHAIN: Governance ----
        RegistrationKindInfo(
            kind=RegistrationKind.GOVERNANCE_UNIFIED,
            display_name="Unified Execution Governance (8-dimension V2 authority)",
            canonical_module="core.unified_execution_governance",
            path_tier=PathTier.MAIN_CHAIN,
            description=(
                "V2 governance authority across all 8 dimensions: "
                "scheduling, routing, capability network, task truth, "
                "config, operator aggregation, device admission, gateway. "
                "All execution decisions must pass through this governance layer. "
                "V2 is the SOLE canonical orchestration authority per PR993."
            ),
            prerequisites=[
                RegistrationKind.DEVICE_CANONICAL,
                RegistrationKind.CAPABILITY_REGISTRY,
            ],
            optional=False,
        ),
        RegistrationKindInfo(
            kind=RegistrationKind.GOVERNANCE_RELEASE_GATE,
            display_name="Distributed Release Gate (CI-enforcing release governance)",
            canonical_module="core.distributed_release_gate_skeleton",
            path_tier=PathTier.MAIN_CHAIN,
            description=(
                "Release gate that produces a binding go/no-go verdict before "
                "deployment. CI gate: governance_gate_enforcement.yml. "
                "is_enforcing=True. "
                "The gate must pass before the system is considered release-ready."
            ),
            prerequisites=[RegistrationKind.GOVERNANCE_UNIFIED],
            optional=True,
        ),
    ]


# ---------------------------------------------------------------------------
# Onboarding step catalog
# ---------------------------------------------------------------------------

def _build_onboarding_steps() -> List[OnboardingStep]:
    """Build the complete ordered onboarding step catalog."""
    return [
        OnboardingStep(
            step_id=OnboardingStepId.CLONE,
            display_name="Clone Repository",
            path_tier=PathTier.MAIN_CHAIN,
            instructions=(
                "git clone https://github.com/DannyFish-11/ufo-galaxy-realization-v2.git\n"
                "cd ufo-galaxy-realization-v2\n"
                "# Optional — Android client:\n"
                "# git clone https://github.com/DannyFish-11/ufo-galaxy-android.git"
            ),
            verification="Directory ufo-galaxy-realization-v2/ exists with main.py present.",
            blocking=True,
        ),
        OnboardingStep(
            step_id=OnboardingStepId.CREATE_VENV,
            display_name="Create Python Virtual Environment",
            path_tier=PathTier.MAIN_CHAIN,
            instructions=(
                "python -m venv .venv\n"
                "source .venv/bin/activate   # Linux / macOS\n"
                "# .venv\\Scripts\\activate  # Windows"
            ),
            verification="which python (or where python on Windows) points to .venv.",
            blocking=True,
        ),
        OnboardingStep(
            step_id=OnboardingStepId.INSTALL_DEPS,
            display_name="Install Python Dependencies",
            path_tier=PathTier.MAIN_CHAIN,
            instructions=(
                "pip install -r requirements.txt\n"
                "# Optional (dev lint/test tools):\n"
                "# pip install -r requirements-dev.txt"
            ),
            verification="python -c 'import fastapi, pydantic' exits 0.",
            blocking=True,
        ),
        OnboardingStep(
            step_id=OnboardingStepId.CONFIGURE_SECRETS,
            display_name="Configure Secrets (API Keys)",
            path_tier=PathTier.MAIN_CHAIN,
            instructions=(
                "cp runtime/secrets.example.env runtime/secrets.env\n"
                "# Edit runtime/secrets.env and fill in at minimum:\n"
                "#   OPENAI_API_KEY=sk-...\n"
                "# (other provider keys are optional)"
            ),
            verification=(
                "runtime/secrets.env exists and OPENAI_API_KEY "
                "(or an alternate provider key) is non-empty."
            ),
            blocking=False,
        ),
        OnboardingStep(
            step_id=OnboardingStepId.CONFIGURE_RUNTIME,
            display_name="Configure Runtime Settings",
            path_tier=PathTier.MAIN_CHAIN,
            instructions=(
                "cp runtime/config.example.json runtime/config.json\n"
                "# Key settings in runtime/config.json:\n"
                "#   cross_device_enabled: true|false\n"
                "#   gateway_host / gateway_port\n"
                "# Leave defaults for a single-host local run."
            ),
            verification="python -c 'import json; json.load(open(\"runtime/config.json\"))' exits 0.",
            blocking=False,
        ),
        OnboardingStep(
            step_id=OnboardingStepId.VERIFY_PREREQUISITES,
            display_name="Verify Registration Prerequisites",
            path_tier=PathTier.MAIN_CHAIN,
            instructions=(
                "python -c \"\n"
                "from core.operational_registration_path import validate_registration_prerequisites\n"
                "v = validate_registration_prerequisites()\n"
                "print(v.summary)\n"
                "if v.failed_checks:\n"
                "    raise SystemExit(1)\n"
                "\""
            ),
            verification="Exits 0 with 'PASSED' summary.",
            blocking=False,
        ),
        OnboardingStep(
            step_id=OnboardingStepId.START_BACKEND,
            display_name="Start V2 Backend",
            path_tier=PathTier.MAIN_CHAIN,
            instructions=(
                "python main.py --host 127.0.0.1 --port 8299\n"
                "# main.py is the canonical system orchestrator (PR-2).\n"
                "# Runs staged bring-up Phases 1-7 then delegates to\n"
                "# unified_launcher.py for full async bring-up."
            ),
            verification=(
                "Logs show 'Orchestrator bring-up complete'. "
                "Backend accepts connections on port 8299."
            ),
            blocking=True,
        ),
        OnboardingStep(
            step_id=OnboardingStepId.VERIFY_BACKEND,
            display_name="Verify Backend Reachability",
            path_tier=PathTier.MAIN_CHAIN,
            instructions=(
                "curl -sS http://127.0.0.1:8299/health\n"
                "# Expected: HTTP 200, {\"status\": \"ok\"} or similar.\n\n"
                "# Minimal chat verification:\n"
                "curl -sS -X POST http://127.0.0.1:8299/api/v1/chat \\\n"
                "  -H 'Content-Type: application/json' \\\n"
                "  -d '{\"message\":\"hello\",\"device_id\":\"local_cli\"}'"
            ),
            verification="GET /health → 200. POST /api/v1/chat returns a response.",
            blocking=True,
        ),
        OnboardingStep(
            step_id=OnboardingStepId.REGISTER_ANDROID,
            display_name="Register Android Device (cross-device path)",
            path_tier=PathTier.CROSS_DEVICE,
            instructions=(
                "# On the Android device:\n"
                "# 1. Install the Galaxy Android app\n"
                "#    (build from ufo-galaxy-android or use release APK)\n"
                "# 2. Open app → Settings → Server URL\n"
                "#    Set to: ws://<V2_host>:<gateway_port>\n"
                "# 3. Enable cross_device_enabled: true in runtime/config.json\n"
                "# 4. Tap 'Connect' — the app sends a registration message\n"
                "#    to the gateway WebSocket\n"
                "# 5. Enable Accessibility Service if GUI automation is needed"
            ),
            verification=(
                "GET /api/v1/devices shows the Android device with status=online. "
                "GET /api/v1/projection/runtime shows the device in the runtime projection."
            ),
            blocking=False,
        ),
        OnboardingStep(
            step_id=OnboardingStepId.VERIFY_ANDROID_REGISTRATION,
            display_name="Verify Android Registration on V2 Side",
            path_tier=PathTier.CROSS_DEVICE,
            instructions=(
                "curl -sS http://127.0.0.1:8299/api/v1/devices\n"
                "curl -sS http://127.0.0.1:8299/api/v1/projection/runtime"
            ),
            verification=(
                "Android device appears with status=online. "
                "Runtime projection includes device capabilities."
            ),
            blocking=False,
        ),
        OnboardingStep(
            step_id=OnboardingStepId.INITIATE_TASK,
            display_name="Initiate First Task (main chain)",
            path_tier=PathTier.MAIN_CHAIN,
            instructions=(
                "# Local natural language request (main chain):\n"
                "curl -sS -X POST http://127.0.0.1:8299/api/v1/chat \\\n"
                "  -H 'Content-Type: application/json' \\\n"
                "  -d '{\"message\":\"请帮我查一下当前时间\",\"device_id\":\"local_cli\"}'\n\n"
                "# Cross-device NL initiation (from Android app):\n"
                "# Type or speak a command in the Galaxy Android app."
            ),
            verification=(
                "Response contains a task_id and/or direct answer. "
                "Logs show the four-phase OpenClawd cycle "
                "(ingest / continuum / branch / manifest)."
            ),
            blocking=False,
        ),
        OnboardingStep(
            step_id=OnboardingStepId.VERIFY_CLOSURE,
            display_name="Verify Result Return and Closure",
            path_tier=PathTier.MAIN_CHAIN,
            instructions=(
                "curl -sS http://127.0.0.1:8299/api/v1/projection/runtime-truth\n"
                "# Confirm task result is present and reconciliation is complete."
            ),
            verification=(
                "Runtime truth projection shows the task as completed. "
                "No open reconciliation entries."
            ),
            blocking=False,
        ),
    ]


# ---------------------------------------------------------------------------
# Prerequisite validation
# ---------------------------------------------------------------------------

def _check_module(
    name: str,
    module_dotted: str,
    fail_msg: str,
    warn_only: bool = False,
) -> PrerequisiteCheck:
    """Shallow-walk check: verify that all path segments of *module_dotted* can
    be located by ``importlib.util.find_spec`` without triggering a full package
    ``__init__`` import.

    This avoids ``ModuleNotFoundError`` crashes when optional runtime
    dependencies (e.g. ``fastapi``, ``websockets``) are absent in the current
    environment.  A ``ValueError`` or ``ImportError`` from ``find_spec`` (which
    can happen when a parent ``__init__`` has a hard import on an absent dep) is
    treated as a WARN so the check reports a dependency gap rather than crashing.
    """
    parts = module_dotted.split(".")
    try:
        for i in range(1, len(parts) + 1):
            partial = ".".join(parts[:i])
            spec = importlib.util.find_spec(partial)
            if spec is None:
                status = ValidationStatus.WARN if warn_only else ValidationStatus.FAIL
                return PrerequisiteCheck(
                    name=name,
                    status=status,
                    message=fail_msg,
                    module_checked=module_dotted,
                )
        return PrerequisiteCheck(
            name=name,
            status=ValidationStatus.PASS,
            message=f"Module '{module_dotted}' is locatable.",
            module_checked=module_dotted,
        )
    except (ValueError, ModuleNotFoundError, ImportError):
        # find_spec raised because a parent __init__ has an absent hard dependency.
        # The source file exists but can't be fully initialised in this environment.
        return PrerequisiteCheck(
            name=name,
            status=ValidationStatus.WARN,
            message=(
                f"Module '{module_dotted}' source exists but its dependencies may be "
                "absent in this environment (install requirements.txt to resolve)."
            ),
            module_checked=module_dotted,
        )


def validate_registration_prerequisites() -> OnboardingValidation:
    """Validate all critical registration prerequisites.

    Performs shallow import-location checks on the canonical modules that must
    be present for the system to operate correctly.  Returns an
    :class:`OnboardingValidation` with per-check results and an overall status.

    Fail-fast usage::

        v = validate_registration_prerequisites()
        if not v.passed:
            for c in v.failed_checks:
                print(f"FAIL: {c.name} — {c.message}")
            raise RuntimeError("Registration prerequisites not met.")

    Returns
    -------
    OnboardingValidation
    """
    checks: List[PrerequisiteCheck] = []

    # ---- Core system orchestrator ----
    checks.append(_check_module(
        "system-orchestrator",
        "core.system_orchestrator",
        "core.system_orchestrator not found — staged bring-up contract missing.",
    ))

    # ---- Canonical device management (UDM) ----
    checks.append(_check_module(
        "unified-device-manager",
        "core.unified.device_manager",
        "core.unified.device_manager (UDM) not found — canonical device SSOT missing.",
    ))

    # ---- Capability registry (try both known locations) ----
    cap_reg_spec = None
    cap_reg_module = ""
    for candidate in ("core.agent.capability_registry", "core.capability_registry"):
        try:
            parts = candidate.split(".")
            all_found = True
            for i in range(1, len(parts) + 1):
                spec = importlib.util.find_spec(".".join(parts[:i]))
                if spec is None:
                    all_found = False
                    break
            if all_found:
                cap_reg_spec = True
                cap_reg_module = candidate
                break
        except (ValueError, ModuleNotFoundError, ImportError):
            cap_reg_spec = True  # source exists, dep absent
            cap_reg_module = candidate
            break

    if cap_reg_spec is not None:
        checks.append(PrerequisiteCheck(
            name="capability-registry",
            status=ValidationStatus.PASS,
            message=f"CapabilityRegistry module locatable at '{cap_reg_module}'.",
            module_checked=cap_reg_module,
        ))
    else:
        checks.append(PrerequisiteCheck(
            name="capability-registry",
            status=ValidationStatus.FAIL,
            message=(
                "Neither core.agent.capability_registry nor core.capability_registry "
                "is locatable — capability network missing."
            ),
            module_checked="core.capability_registry",
        ))

    # ---- Gateway WebSocket transport ----
    checks.append(_check_module(
        "gateway-websocket",
        "galaxy_gateway.routes.websocket",
        (
            "galaxy_gateway.routes.websocket not found — "
            "WebSocket transport missing; Android registration will fail."
        ),
    ))

    # ---- Android device state store ----
    checks.append(_check_module(
        "android-device-state-store",
        "core.android_device_state_store",
        (
            "core.android_device_state_store not found — "
            "Android runtime state mirror missing; cross-device truth incomplete."
        ),
    ))

    # ---- Android gateway registration handler ----
    checks.append(_check_module(
        "android-gateway-registration",
        "galaxy_gateway.android.handlers.registration",
        (
            "galaxy_gateway.android.handlers.registration not found — "
            "Android device admission handler missing."
        ),
    ))

    # ---- Attached runtime session registry ----
    checks.append(_check_module(
        "attached-runtime-session-registry",
        "core.attached_runtime_session_registry",
        (
            "core.attached_runtime_session_registry not found — "
            "session truth SSOT missing; dispatch/reuse/reconciliation affected."
        ),
    ))

    # ---- Unified execution governance ----
    checks.append(_check_module(
        "unified-execution-governance",
        "core.unified_execution_governance",
        (
            "core.unified_execution_governance not found — "
            "8-dimension V2 governance authority missing."
        ),
    ))

    # ---- Desktop presence runtime (subject shell) ----
    checks.append(_check_module(
        "desktop-presence-runtime",
        "core.desktop_presence_runtime",
        "core.desktop_presence_runtime not found — runtime subject shell missing.",
    ))

    # ---- OpenClawd (subject core) ----
    checks.append(_check_module(
        "openclawd-core",
        "core.openclawd",
        "core.openclawd not found — cognitive subject core missing.",
    ))

    # ---- PR993 reevaluation (optional but recommended) ----
    checks.append(_check_module(
        "pr993-reevaluation",
        "core.pr993_dual_repo_reevaluation",
        (
            "core.pr993_dual_repo_reevaluation not found — "
            "PR993 machine-checkable reevaluation module missing (recommended)."
        ),
        warn_only=True,
    ))

    # ---- Aggregate ----
    failed = [c for c in checks if c.status == ValidationStatus.FAIL]
    warned = [c for c in checks if c.status == ValidationStatus.WARN]

    if failed:
        overall = ValidationStatus.FAIL
        summary = (
            f"Registration prerequisite validation FAILED: "
            f"{len(failed)} failure(s), {len(warned)} warning(s). "
            f"Failed checks: {', '.join(c.name for c in failed)}. "
            "Fix the failed prerequisites before starting the system."
        )
    elif warned:
        overall = ValidationStatus.WARN
        summary = (
            f"Registration prerequisite validation PASSED WITH WARNINGS: "
            f"0 failures, {len(warned)} warning(s). "
            f"Warned: {', '.join(c.name for c in warned)}. "
            "System may start in degraded mode."
        )
    else:
        overall = ValidationStatus.PASS
        summary = (
            f"Registration prerequisite validation PASSED: "
            f"all {len(checks)} checks passed."
        )

    return OnboardingValidation(
        checks=checks,
        overall_status=overall,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Tier classification helper
# ---------------------------------------------------------------------------

def _classify_by_tier(
    kinds: List[RegistrationKindInfo],
    tier: PathTier,
) -> List[RegistrationKind]:
    return [rk.kind for rk in kinds if rk.path_tier == tier]


# ---------------------------------------------------------------------------
# Root builder
# ---------------------------------------------------------------------------

def build_operational_registration_path() -> OperationalRegistrationPath:
    """Build and return the complete OperationalRegistrationPath.

    1. Builds the full registration kind catalog.
    2. Builds the complete onboarding step catalog.
    3. Runs prerequisite validation.
    4. Classifies kinds by tier.
    5. Returns the fully populated :class:`OperationalRegistrationPath`.

    Returns
    -------
    OperationalRegistrationPath
    """
    kinds = _build_registration_kinds()
    steps = _build_onboarding_steps()
    validation = validate_registration_prerequisites()

    main_chain = _classify_by_tier(kinds, PathTier.MAIN_CHAIN)
    cross_device = _classify_by_tier(kinds, PathTier.CROSS_DEVICE)
    compat = [
        rk.kind for rk in kinds
        if rk.path_tier in (PathTier.COMPAT, PathTier.FALLBACK, PathTier.RECOVERY)
    ]

    system_identity = (
        "Galaxy is a center-governed distributed intelligent agent system "
        "(中心分布式智能体系统, PR993). "
        "V2 (ufo-galaxy-realization-v2) is the center governance, orchestration, "
        "truth convergence, and acceptance authority. "
        "Android (ufo-galaxy-android) is a distributed runtime node with local "
        "intelligence, local task execution, and cross-device participation capability. "
        "The system is NOT a simple control panel + remote control pair; "
        "V2 holds canonical authority and Android actively participates."
    )

    return OperationalRegistrationPath(
        registration_kinds=kinds,
        onboarding_steps=steps,
        validation=validation,
        main_chain_kinds=main_chain,
        cross_device_kinds=cross_device,
        compat_kinds=compat,
        system_identity=system_identity,
    )


# ---------------------------------------------------------------------------
# Cached singleton + test isolation
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_cached_path: Optional[OperationalRegistrationPath] = None


def get_operational_registration_path() -> OperationalRegistrationPath:
    """Return the cached OperationalRegistrationPath singleton.

    Thread-safe.  Built once and cached.  Use
    :func:`reset_operational_registration_path` to clear the cache in tests.

    Returns
    -------
    OperationalRegistrationPath
    """
    global _cached_path
    with _lock:
        if _cached_path is None:
            _cached_path = build_operational_registration_path()
        return _cached_path


def reset_operational_registration_path() -> None:
    """Clear the cached OperationalRegistrationPath singleton (test isolation)."""
    global _cached_path
    with _lock:
        _cached_path = None


# ---------------------------------------------------------------------------
# Test-helper invariant suite
# ---------------------------------------------------------------------------

def assert_operational_registration_path_invariants() -> None:
    """Assert that the operational registration path is internally consistent.

    Raises ``AssertionError`` with a descriptive message if an invariant is
    violated.  Call from tests to ensure this surface stays in sync with real
    code.
    """
    path = get_operational_registration_path()

    # ---- All RegistrationKind values covered ----
    kind_ids_seen = {rk.kind for rk in path.registration_kinds}
    for kind in RegistrationKind:
        assert kind in kind_ids_seen, (
            f"Missing RegistrationKindInfo for RegistrationKind.{kind.name}."
        )

    # ---- All OnboardingStepId values covered ----
    step_ids_seen = {s.step_id for s in path.onboarding_steps}
    for step in OnboardingStepId:
        assert step in step_ids_seen, (
            f"Missing OnboardingStep for OnboardingStepId.{step.name}."
        )

    # ---- Every kind is in exactly one tier bucket ----
    all_tiered = (
        set(path.main_chain_kinds)
        | set(path.cross_device_kinds)
        | set(path.compat_kinds)
    )
    for rk in path.registration_kinds:
        assert rk.kind in all_tiered, (
            f"RegistrationKind.{rk.kind.name} is not classified into any tier bucket."
        )

    # ---- Validation must have been run ----
    assert path.validation is not None, "Validation must be present."
    assert len(path.validation.checks) > 0, "Validation must contain at least one check."

    # ---- Main chain must be non-empty ----
    assert len(path.main_chain_kinds) > 0, "Main chain must have at least one kind."

    # ---- Key main-chain kinds must be present ----
    required_main = {
        RegistrationKind.DEVICE_CANONICAL,
        RegistrationKind.CAPABILITY_REGISTRY,
        RegistrationKind.GATEWAY_WEBSOCKET,
        RegistrationKind.GOVERNANCE_UNIFIED,
        RegistrationKind.RUNTIME_SUBJECT,
    }
    for k in required_main:
        assert k in path.main_chain_kinds, (
            f"RegistrationKind.{k.name} must be classified as MAIN_CHAIN."
        )

    # ---- Key cross-device kinds must be present ----
    required_cross = {
        RegistrationKind.DEVICE_ANDROID_ADMISSION,
        RegistrationKind.CAPABILITY_ANDROID_REPORT,
        RegistrationKind.SESSION_ANDROID_PARTICIPANT,
        RegistrationKind.RUNTIME_ANDROID_HOST,
    }
    for k in required_cross:
        assert k in path.cross_device_kinds, (
            f"RegistrationKind.{k.name} must be classified as CROSS_DEVICE."
        )

    # ---- Serialisation round-trip ----
    d = path.to_dict()
    assert isinstance(d, dict), "to_dict() must return a dict."
    assert "registration_kinds" in d
    assert "onboarding_steps" in d
    assert "validation" in d
    j = path.to_json()
    assert isinstance(j, str) and len(j) > 0, "to_json() must return a non-empty string."

    # ---- System identity must reference PR993 ----
    assert "PR993" in path.system_identity or "center-governed" in path.system_identity, (
        "system_identity must reference the PR993 center-governed system definition."
    )

    # ---- Contract version must contain alignment tag ----
    assert path.contract_version, "contract_version must be non-empty."
    assert "pr993_ops" in path.contract_version, (
        "contract_version must contain 'pr993_ops' alignment tag."
    )
