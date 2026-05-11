"""
core/operational_readiness_surface.py
=====================================
PR1114 follow-up: unified registration state, clone-to-use acceptance chain,
and Android↔V2 minimum access standard surface.

This module is intentionally **additive**.  It does not replace any existing
canonical owner.  Instead, it aggregates read-only signals from:

- ``core.operational_registration_path`` (PR1114 registration/onboarding spine)
- ``core.runtime_readiness_matrix`` (runtime/blocking verdict)
- ``core.system_final_acceptance_verdict`` (system acceptance verdict)
- ``core.device_readiness`` / UDM (device admission + cross-device readiness)
- ``core.android_device_state_store`` (Android capability/device-state truth)
- ``core.attached_runtime_session_registry`` (session continuity SSOT)
- ``core.android_participant_session_state`` (participant lifecycle truth)

Goal
----
Give operators and maintainers one answer to:

* the system has currently registered up to which layer,
* which layers are blocked / degraded / merely pending,
* whether the runtime is on main-chain, cross-device, compat, degraded, or
  recovery posture,
* whether clone-to-use acceptance currently stops at prerequisites/API or has
  actually progressed through Android attachment, capability visibility, task
  initiation, and result closure.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from core.operational_registration_path import (
    OPERATIONAL_REGISTRATION_PATH_AUTHORITY,
    OPERATIONAL_REGISTRATION_PATH_CONTRACT_VERSION,
    OnboardingValidation,
    OperationalRegistrationPath,
    PathTier,
    RegistrationKind,
    ValidationStatus,
    get_operational_registration_path,
    validate_registration_prerequisites,
)

logger = logging.getLogger("Galaxy.OperationalReadinessSurface")

__all__ = [
    "OPERATIONAL_READINESS_SURFACE_AUTHORITY",
    "OPERATIONAL_READINESS_SURFACE_CONTRACT_VERSION",
    "SurfaceStatus",
    "RegistrationKindState",
    "RegistrationDomainState",
    "AcceptanceCheckpoint",
    "OperationalChainState",
    "OperationalReadinessReport",
    "build_operational_readiness_report",
    "collect_app_route_paths",
]


OPERATIONAL_READINESS_SURFACE_AUTHORITY: str = (
    "core.operational_readiness_surface::pr1114-followup::"
    "registration-state-and-clone-to-use-acceptance-surface"
)

OPERATIONAL_READINESS_SURFACE_CONTRACT_VERSION: str = "pr1114_followup.2.0.0"

_REQUIRED_API_PATHS: tuple[str, ...] = (
    "/api/v1/health",
    "/api/v1/chat",
    "/api/v1/projection/runtime",
    "/api/v1/projection/operational-readiness",
    "/api/v1/projection/clone-to-use-acceptance",
)

_DYNAMIC_KIND_STATUS: frozenset[RegistrationKind] = frozenset(
    {
        RegistrationKind.DEVICE_ANDROID_ADMISSION,
        RegistrationKind.DEVICE_ANDROID_STATE,
        RegistrationKind.CAPABILITY_ANDROID_REPORT,
        RegistrationKind.SESSION_ATTACHED_RUNTIME,
        RegistrationKind.SESSION_ANDROID_PARTICIPANT,
        RegistrationKind.GATEWAY_ANDROID_BRIDGE,
        RegistrationKind.RUNTIME_ANDROID_HOST,
        RegistrationKind.RUNTIME_DISPATCH_BINDING,
        RegistrationKind.GOVERNANCE_RELEASE_GATE,
    }
)

_DOMAIN_GROUPS: Dict[str, tuple[RegistrationKind, ...]] = {
    "device": (
        RegistrationKind.DEVICE_CANONICAL,
        RegistrationKind.DEVICE_INDEX,
        RegistrationKind.DEVICE_ANDROID_ADMISSION,
        RegistrationKind.DEVICE_ANDROID_STATE,
    ),
    "capability": (
        RegistrationKind.CAPABILITY_REGISTRY,
        RegistrationKind.CAPABILITY_BUS,
        RegistrationKind.CAPABILITY_ANDROID_REPORT,
        RegistrationKind.CAPABILITY_RESOLVER,
    ),
    "session": (
        RegistrationKind.SESSION_ATTACHED_RUNTIME,
        RegistrationKind.SESSION_ANDROID_PARTICIPANT,
        RegistrationKind.SESSION_CANONICAL_AXIS,
    ),
    "gateway": (
        RegistrationKind.GATEWAY_WEBSOCKET,
        RegistrationKind.GATEWAY_ANDROID_BRIDGE,
        RegistrationKind.GATEWAY_DEVICE_ROUTER,
    ),
    "runtime": (
        RegistrationKind.RUNTIME_SUBJECT,
        RegistrationKind.RUNTIME_ANDROID_HOST,
        RegistrationKind.RUNTIME_DISPATCH_BINDING,
    ),
    "governance": (
        RegistrationKind.GOVERNANCE_UNIFIED,
        RegistrationKind.GOVERNANCE_RELEASE_GATE,
    ),
}


class SurfaceStatus(str, Enum):
    ready = "ready"
    degraded = "degraded"
    blocked = "blocked"
    pending = "pending"
    not_applicable = "not_applicable"


@dataclass
class RegistrationKindState:
    kind: str
    display_name: str
    path_tier: str
    canonical_module: str
    status: SurfaceStatus
    evidence_summary: str
    optional: bool = False
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "display_name": self.display_name,
            "path_tier": self.path_tier,
            "canonical_module": self.canonical_module,
            "status": self.status.value,
            "optional": self.optional,
            "evidence_summary": self.evidence_summary,
            "evidence": dict(self.evidence),
        }


@dataclass
class RegistrationDomainState:
    domain_id: str
    display_name: str
    status: SurfaceStatus
    minimal_viable: bool
    diagnosis: str
    ready_kinds: List[str] = field(default_factory=list)
    pending_kinds: List[str] = field(default_factory=list)
    blocked_kinds: List[str] = field(default_factory=list)
    degraded_kinds: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "display_name": self.display_name,
            "status": self.status.value,
            "minimal_viable": self.minimal_viable,
            "diagnosis": self.diagnosis,
            "ready_kinds": list(self.ready_kinds),
            "pending_kinds": list(self.pending_kinds),
            "blocked_kinds": list(self.blocked_kinds),
            "degraded_kinds": list(self.degraded_kinds),
            "evidence": dict(self.evidence),
        }


@dataclass
class AcceptanceCheckpoint:
    checkpoint_id: str
    display_name: str
    status: SurfaceStatus
    blocking: bool
    summary: str
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "display_name": self.display_name,
            "status": self.status.value,
            "blocking": self.blocking,
            "summary": self.summary,
            "evidence": dict(self.evidence),
        }


@dataclass
class OperationalChainState:
    main_chain_available: bool = False
    cross_device_available: bool = False
    compat_only_available: bool = False
    degraded: bool = False
    recovery_active: bool = False
    active_path: str = "blocked"
    success_quality: str = "blocked"
    diagnosis: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "main_chain_available": self.main_chain_available,
            "cross_device_available": self.cross_device_available,
            "compat_only_available": self.compat_only_available,
            "degraded": self.degraded,
            "recovery_active": self.recovery_active,
            "active_path": self.active_path,
            "success_quality": self.success_quality,
            "diagnosis": list(self.diagnosis),
        }


@dataclass
class OperationalReadinessReport:
    generated_at: float
    authority: str
    contract_version: str
    path_authority: str
    path_contract_version: str
    system_identity: str
    validation: Dict[str, Any]
    registration_progress: Dict[str, Any]
    registration_kinds: List[RegistrationKindState]
    registration_domains: List[RegistrationDomainState]
    chain_state: OperationalChainState
    clone_to_use_acceptance: Dict[str, Any]
    android_v2_minimum_standard: Dict[str, Any]
    runtime_readiness: Dict[str, Any]
    system_acceptance: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "authority": self.authority,
            "contract_version": self.contract_version,
            "path_authority": self.path_authority,
            "path_contract_version": self.path_contract_version,
            "system_identity": self.system_identity,
            "validation": dict(self.validation),
            "registration_progress": dict(self.registration_progress),
            "registration_kinds": [item.to_dict() for item in self.registration_kinds],
            "registration_domains": [item.to_dict() for item in self.registration_domains],
            "chain_state": self.chain_state.to_dict(),
            "clone_to_use_acceptance": dict(self.clone_to_use_acceptance),
            "android_v2_minimum_standard": dict(self.android_v2_minimum_standard),
            "runtime_readiness": dict(self.runtime_readiness),
            "system_acceptance": dict(self.system_acceptance),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def collect_app_route_paths(app: Any) -> Set[str]:
    """Return route paths registered on a FastAPI/Starlette app."""
    router = getattr(app, "router", None)
    routes = getattr(router, "routes", None)
    if routes is None:
        return set()
    paths: Set[str] = set()
    for route in routes:
        path = getattr(route, "path", None)
        if isinstance(path, str) and path:
            paths.add(path)
    return paths


def _module_available(module_path: str) -> bool:
    try:
        return importlib.util.find_spec(module_path) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _collect_device_evidence() -> Dict[str, Any]:
    evidence: Dict[str, Any] = {
        "known_device_count": 0,
        "android_device_count": 0,
        "android_device_ids": [],
        "cross_device_ready_device_ids": [],
    }
    try:
        from core.unified.device_manager import get_unified_device_manager

        udm = get_unified_device_manager()
        devices = udm.list_devices()
        android_ids: List[str] = []
        for device in devices:
            device_id = str(getattr(device, "device_id", "") or "")
            if not device_id:
                continue
            device_type = str(getattr(device, "device_type", "") or "").lower()
            if "android" in device_type:
                android_ids.append(device_id)
        evidence["known_device_count"] = len(devices)
        evidence["android_device_count"] = len(android_ids)
        evidence["android_device_ids"] = android_ids
    except Exception as exc:  # noqa: BLE001
        evidence["device_inventory_error"] = str(exc)

    try:
        from core.device_readiness import get_cross_device_ready_devices

        readiness = get_cross_device_ready_devices()
        ready_ids = [item.device_id for item in readiness]
        evidence["cross_device_ready_device_ids"] = ready_ids
    except Exception as exc:  # noqa: BLE001
        evidence["cross_device_readiness_error"] = str(exc)
    return evidence


def _collect_android_evidence() -> Dict[str, Any]:
    evidence: Dict[str, Any] = {
        "snapshot_count": 0,
        "snapshot_device_ids": [],
        "capability_semantics_count": 0,
        "capability_visible_count": 0,
        "degraded_capability_device_count": 0,
        "execution_event_count": 0,
        "terminal_execution_event_count": 0,
        "ecosystem_summary": {},
    }
    try:
        from core.android_device_state_store import (
            get_device_capability_report_semantics,
            get_device_ecosystem_summary,
            list_device_state_snapshots,
            list_recent_execution_events,
        )

        snapshots = list_device_state_snapshots()
        evidence["snapshot_count"] = len(snapshots)
        evidence["snapshot_device_ids"] = [snap.device_id for snap in snapshots]
        degraded_count = 0
        capability_visible_count = 0
        capability_semantics_count = 0
        for snap in snapshots:
            semantics = get_device_capability_report_semantics(snap.device_id)
            if semantics:
                capability_semantics_count += 1
                if (
                    semantics.get("cross_device_eligibility") is True
                    or semantics.get("goal_execution_eligibility") is True
                ):
                    capability_visible_count += 1
                if (
                    semantics.get("degraded_mode") is True
                    or semantics.get("mode_readiness_state")
                    in {"degraded", "blocked", "transitioning"}
                    or semantics.get("canonical_gate_metadata_state")
                    not in (None, "complete")
                ):
                    degraded_count += 1
            elif getattr(snap, "degraded_reasons", None):
                degraded_count += 1
        evidence["capability_semantics_count"] = capability_semantics_count
        evidence["capability_visible_count"] = capability_visible_count
        evidence["degraded_capability_device_count"] = degraded_count
        events = list_recent_execution_events(limit=200)
        evidence["execution_event_count"] = len(events)
        evidence["terminal_execution_event_count"] = sum(
            1
            for event in events
            if getattr(event, "phase", None)
            in {"completed", "failed", "stagnation", "gate_decision"}
        )
        evidence["ecosystem_summary"] = get_device_ecosystem_summary()
    except Exception as exc:  # noqa: BLE001
        evidence["android_state_error"] = str(exc)
    return evidence


def _collect_session_evidence() -> Dict[str, Any]:
    evidence: Dict[str, Any] = {
        "active_session_count": 0,
        "total_session_count": 0,
        "replaced_session_count": 0,
        "detached_session_count": 0,
        "invalidated_session_count": 0,
        "participant_total_count": 0,
        "participant_active_count": 0,
        "participant_terminal_count": 0,
        "participant_terminal_success_count": 0,
        "task_initiated": False,
        "result_closure_established": False,
        "recovery_active": False,
        "participant_phases": [],
    }
    try:
        from core.attached_runtime_session_registry import build_registry_snapshot

        registry_snapshot = build_registry_snapshot()
        evidence["active_session_count"] = registry_snapshot.active_count
        evidence["total_session_count"] = registry_snapshot.total_count
        evidence["replaced_session_count"] = registry_snapshot.replaced_count
        evidence["detached_session_count"] = registry_snapshot.detached_count
        evidence["invalidated_session_count"] = registry_snapshot.invalidated_count
    except Exception as exc:  # noqa: BLE001
        evidence["attached_session_error"] = str(exc)

    try:
        from core.android_participant_session_state import participant_session_snapshot

        snapshot = participant_session_snapshot()
        phases = [record.phase.value for record in snapshot.records]
        evidence["participant_total_count"] = snapshot.total_count
        evidence["participant_active_count"] = snapshot.active_count
        evidence["participant_terminal_count"] = snapshot.terminal_count
        evidence["participant_terminal_success_count"] = sum(
            1 for record in snapshot.records if record.phase.value == "terminal_success"
        )
        evidence["participant_phases"] = phases
        evidence["task_initiated"] = any(phase != "pre_dispatch" for phase in phases)
        evidence["result_closure_established"] = snapshot.terminal_count > 0
        evidence["recovery_active"] = any(phase == "reconciling" for phase in phases)
    except Exception as exc:  # noqa: BLE001
        evidence["participant_session_error"] = str(exc)

    evidence["recovery_active"] = evidence["recovery_active"] or any(
        evidence.get(key, 0) > 0
        for key in (
            "replaced_session_count",
            "detached_session_count",
            "invalidated_session_count",
        )
    )
    return evidence


def _load_runtime_readiness() -> Dict[str, Any]:
    try:
        from core.runtime_readiness_matrix import get_readiness_matrix

        matrix = get_readiness_matrix().to_dict()
        return {
            "available": True,
            "verdict": matrix.get("verdict", "unknown"),
            "blocking": bool(matrix.get("blocked", False)),
            "summary": matrix.get("summary", ""),
            "matrix": matrix,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "verdict": "unknown",
            "blocking": False,
            "summary": f"runtime_readiness_unavailable: {exc}",
            "matrix": {},
        }


def _load_system_acceptance() -> Dict[str, Any]:
    try:
        from core.system_final_acceptance_verdict import evaluate_system_acceptance

        report = evaluate_system_acceptance()
        payload = report.to_dict()
        return {
            "available": True,
            "verdict": payload.get("verdict", "acceptance_unknown_insufficient_evidence"),
            "summary": payload.get("summary", ""),
            "report": payload,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "verdict": "acceptance_unknown_insufficient_evidence",
            "summary": f"system_acceptance_unavailable: {exc}",
            "report": {},
        }


def _dynamic_kind_state(
    kind: RegistrationKind,
    *,
    runtime_readiness: Dict[str, Any],
    device_evidence: Dict[str, Any],
    android_evidence: Dict[str, Any],
    session_evidence: Dict[str, Any],
) -> tuple[SurfaceStatus, str, Dict[str, Any]]:
    android_attached = (
        device_evidence.get("android_device_count", 0) > 0
        or android_evidence.get("snapshot_count", 0) > 0
        or session_evidence.get("participant_total_count", 0) > 0
    )

    if kind == RegistrationKind.DEVICE_ANDROID_ADMISSION:
        count = device_evidence.get("android_device_count", 0)
        if count > 0:
            return SurfaceStatus.ready, f"{count} Android device(s) admitted into V2.", {
                "android_device_ids": device_evidence.get("android_device_ids", [])
            }
        return SurfaceStatus.pending, "Android↔V2 admission path is present but not yet exercised.", {}

    if kind == RegistrationKind.DEVICE_ANDROID_STATE:
        count = android_evidence.get("snapshot_count", 0)
        if count > 0:
            return SurfaceStatus.ready, f"{count} Android device snapshot(s) mirrored on V2.", {
                "snapshot_device_ids": android_evidence.get("snapshot_device_ids", [])
            }
        return SurfaceStatus.pending, "Android state store is available but no live snapshot is recorded yet.", {}

    if kind == RegistrationKind.CAPABILITY_ANDROID_REPORT:
        visible = android_evidence.get("capability_visible_count", 0)
        degraded = android_evidence.get("degraded_capability_device_count", 0)
        if visible > 0 and degraded == 0:
            return SurfaceStatus.ready, "Android capability report is visible and canonical.", {
                "capability_visible_count": visible
            }
        if visible > 0:
            return SurfaceStatus.degraded, "Android capability is visible but degraded/downgraded.", {
                "capability_visible_count": visible,
                "degraded_capability_device_count": degraded,
            }
        if android_attached:
            return (
                SurfaceStatus.pending,
                "Android device is attached but no accepted capability report is visible yet.",
                {},
            )
        return SurfaceStatus.not_applicable, "Cross-device capability path not yet exercised.", {}

    if kind == RegistrationKind.SESSION_ATTACHED_RUNTIME:
        total = session_evidence.get("total_session_count", 0)
        active = session_evidence.get("active_session_count", 0)
        if total > 0:
            status = SurfaceStatus.ready if active > 0 else SurfaceStatus.degraded
            summary = f"Attached runtime registry recorded {total} session(s), active={active}."
            return status, summary, {
                "active_session_count": active,
                "total_session_count": total,
            }
        return (
            SurfaceStatus.pending,
            "Session registry is available but no attached runtime session has been recorded yet.",
            {},
        )

    if kind == RegistrationKind.SESSION_ANDROID_PARTICIPANT:
        total = session_evidence.get("participant_total_count", 0)
        terminal = session_evidence.get("participant_terminal_count", 0)
        if terminal > 0:
            return SurfaceStatus.ready, f"Android participant lifecycle reached closure for {terminal} session(s).", {
                "participant_total_count": total,
                "participant_terminal_count": terminal,
            }
        if total > 0:
            return SurfaceStatus.degraded, "Android participant lifecycle is active but not yet closed.", {
                "participant_total_count": total,
                "participant_phases": session_evidence.get("participant_phases", []),
            }
        if android_attached:
            return (
                SurfaceStatus.pending,
                "Android device is attached but participant-session truth has not been exercised yet.",
                {},
            )
        return SurfaceStatus.not_applicable, "Android participant lifecycle not yet engaged.", {}

    if kind == RegistrationKind.GATEWAY_ANDROID_BRIDGE:
        if android_attached:
            return SurfaceStatus.ready, "Gateway Android bridge is exercised by live Android traffic.", {}
        return SurfaceStatus.pending, "Gateway Android bridge is present but not yet exercised.", {}

    if kind == RegistrationKind.RUNTIME_ANDROID_HOST:
        if session_evidence.get("task_initiated"):
            return SurfaceStatus.ready, "Android runtime host is engaged in delegated task flow.", {}
        if android_attached:
            return SurfaceStatus.pending, "Android runtime host is available but no delegated task has started yet.", {}
        return SurfaceStatus.not_applicable, "Android runtime host path not yet engaged.", {}

    if kind == RegistrationKind.RUNTIME_DISPATCH_BINDING:
        if session_evidence.get("task_initiated"):
            return SurfaceStatus.ready, "Dispatch binding has participated in delegated task initiation.", {}
        if android_attached:
            return SurfaceStatus.pending, "Dispatch binding is available but no delegated dispatch is observed yet.", {}
        return SurfaceStatus.not_applicable, "Dispatch binding path not yet exercised.", {}

    if kind == RegistrationKind.GOVERNANCE_RELEASE_GATE:
        verdict = runtime_readiness.get("verdict")
        if verdict == "ready":
            return SurfaceStatus.ready, "Runtime readiness matrix reports READY.", {
                "runtime_readiness_verdict": verdict
            }
        if verdict in {"degraded", "unknown"}:
            return SurfaceStatus.degraded, f"Runtime readiness matrix verdict={verdict}.", {
                "runtime_readiness_verdict": verdict
            }
        return SurfaceStatus.blocked, f"Runtime readiness matrix verdict={verdict}.", {
            "runtime_readiness_verdict": verdict
        }

    return SurfaceStatus.ready, "Canonical module is present.", {}


def _build_registration_kind_states(
    path: OperationalRegistrationPath,
    *,
    runtime_readiness: Dict[str, Any],
    device_evidence: Dict[str, Any],
    android_evidence: Dict[str, Any],
    session_evidence: Dict[str, Any],
) -> List[RegistrationKindState]:
    items: List[RegistrationKindState] = []
    for item in path.registration_kinds:
        if not _module_available(item.canonical_module):
            status = SurfaceStatus.blocked
            summary = f"Canonical module missing: {item.canonical_module}"
            evidence = {"canonical_module": item.canonical_module}
        elif item.kind in _DYNAMIC_KIND_STATUS:
            status, summary, evidence = _dynamic_kind_state(
                item.kind,
                runtime_readiness=runtime_readiness,
                device_evidence=device_evidence,
                android_evidence=android_evidence,
                session_evidence=session_evidence,
            )
        else:
            status = SurfaceStatus.ready
            summary = "Canonical module present and registration layer is structurally available."
            evidence = {"canonical_module": item.canonical_module}

        items.append(
            RegistrationKindState(
                kind=item.kind.value,
                display_name=item.display_name,
                path_tier=item.path_tier.value,
                canonical_module=item.canonical_module,
                status=status,
                evidence_summary=summary,
                optional=item.optional,
                evidence=evidence,
            )
        )
    return items


def _build_domain_states(kind_states: Sequence[RegistrationKindState]) -> List[RegistrationDomainState]:
    by_kind = {state.kind: state for state in kind_states}
    result: List[RegistrationDomainState] = []
    for domain_id, kinds in _DOMAIN_GROUPS.items():
        states = [by_kind[kind.value] for kind in kinds if kind.value in by_kind]
        blocked = [item.kind for item in states if item.status == SurfaceStatus.blocked]
        degraded = [item.kind for item in states if item.status == SurfaceStatus.degraded]
        pending = [item.kind for item in states if item.status == SurfaceStatus.pending]
        ready = [item.kind for item in states if item.status == SurfaceStatus.ready]
        if blocked:
            status = SurfaceStatus.blocked
            diagnosis = f"Blocked by missing/unusable layers: {', '.join(blocked)}."
        elif degraded:
            status = SurfaceStatus.degraded
            diagnosis = f"Layer is available but degraded: {', '.join(degraded)}."
        elif pending:
            status = SurfaceStatus.pending
            diagnosis = f"Layer is structurally present but not yet fully exercised: {', '.join(pending)}."
        else:
            status = SurfaceStatus.ready
            diagnosis = "All layers in this domain are currently ready."
        result.append(
            RegistrationDomainState(
                domain_id=domain_id,
                display_name=domain_id.capitalize(),
                status=status,
                minimal_viable=status in {SurfaceStatus.ready, SurfaceStatus.degraded},
                diagnosis=diagnosis,
                ready_kinds=ready,
                pending_kinds=pending,
                blocked_kinds=blocked,
                degraded_kinds=degraded,
                evidence={
                    "kind_count": len(states),
                    "ready_count": len(ready),
                    "pending_count": len(pending),
                    "blocked_count": len(blocked),
                    "degraded_count": len(degraded),
                },
            )
        )
    return result


def _build_registration_progress(
    path: OperationalRegistrationPath,
    *,
    validation: OnboardingValidation,
    kind_states: Sequence[RegistrationKindState],
) -> Dict[str, Any]:
    status_counts = {status.value: 0 for status in SurfaceStatus}
    for item in kind_states:
        status_counts[item.status.value] = status_counts.get(item.status.value, 0) + 1

    tier_map = {
        PathTier.MAIN_CHAIN.value: [
            state.kind for state in kind_states if state.path_tier == PathTier.MAIN_CHAIN.value
        ],
        PathTier.CROSS_DEVICE.value: [
            state.kind for state in kind_states if state.path_tier == PathTier.CROSS_DEVICE.value
        ],
        "compat_family": [
            state.kind
            for state in kind_states
            if state.path_tier in {PathTier.COMPAT.value, PathTier.FALLBACK.value, PathTier.RECOVERY.value}
        ],
    }
    return {
        "overall_validation_status": validation.overall_status.value,
        "summary": validation.summary,
        "total_registration_kinds": len(kind_states),
        "status_counts": status_counts,
        "tier_map": tier_map,
        "ready_registration_kinds": [item.kind for item in kind_states if item.status == SurfaceStatus.ready],
        "blocked_registration_kinds": [item.kind for item in kind_states if item.status == SurfaceStatus.blocked],
        "pending_registration_kinds": [item.kind for item in kind_states if item.status == SurfaceStatus.pending],
        "degraded_registration_kinds": [item.kind for item in kind_states if item.status == SurfaceStatus.degraded],
        "onboarding_step_count": len(path.onboarding_steps),
        "registration_path_authority": OPERATIONAL_REGISTRATION_PATH_AUTHORITY,
        "registration_path_contract_version": OPERATIONAL_REGISTRATION_PATH_CONTRACT_VERSION,
    }


def _build_chain_state(
    path: OperationalRegistrationPath,
    *,
    validation: OnboardingValidation,
    kind_states: Sequence[RegistrationKindState],
    route_paths: Set[str],
    runtime_readiness: Dict[str, Any],
    device_evidence: Dict[str, Any],
    android_evidence: Dict[str, Any],
    session_evidence: Dict[str, Any],
) -> OperationalChainState:
    by_kind = {state.kind: state for state in kind_states}
    required_main_chain = [
        by_kind[kind.value]
        for kind in path.main_chain_kinds
        if kind.value in by_kind
    ]
    main_chain_blocked = any(item.status == SurfaceStatus.blocked for item in required_main_chain)
    api_missing = sorted(required for required in _REQUIRED_API_PATHS if required not in route_paths)
    main_chain_available = (
        validation.overall_status != ValidationStatus.FAIL
        and not main_chain_blocked
        and runtime_readiness.get("verdict") != "blocked"
        and not api_missing
    )
    android_attached = (
        device_evidence.get("android_device_count", 0) > 0
        or android_evidence.get("snapshot_count", 0) > 0
        or session_evidence.get("participant_total_count", 0) > 0
    )
    cross_device_available = (
        android_attached
        and android_evidence.get("capability_visible_count", 0) > 0
        and session_evidence.get("active_session_count", 0) > 0
        and session_evidence.get("task_initiated", False)
    )
    compat_only_available = (
        not main_chain_available
        and any(
            state.path_tier in {PathTier.COMPAT.value, PathTier.FALLBACK.value, PathTier.RECOVERY.value}
            and state.status != SurfaceStatus.blocked
            for state in kind_states
        )
    )
    degraded = (
        validation.overall_status == ValidationStatus.WARN
        or runtime_readiness.get("verdict") in {"degraded", "unknown"}
        or android_evidence.get("degraded_capability_device_count", 0) > 0
    )
    recovery_active = bool(session_evidence.get("recovery_active"))
    diagnosis: List[str] = []
    if api_missing:
        diagnosis.append(f"Missing required API surfaces: {', '.join(api_missing)}.")
    if validation.overall_status == ValidationStatus.FAIL:
        diagnosis.append("Registration prerequisites are failing.")
    elif validation.overall_status == ValidationStatus.WARN:
        diagnosis.append("Registration prerequisites only pass with warnings.")
    if runtime_readiness.get("verdict") not in {None, "ready"}:
        diagnosis.append(f"Runtime readiness verdict={runtime_readiness.get('verdict')}.")
    if android_attached and not cross_device_available:
        diagnosis.append("Android is attached but cross-device minimum viable chain is incomplete.")
    if android_evidence.get("degraded_capability_device_count", 0) > 0:
        diagnosis.append("Android capability/device-state truth is degraded.")
    if recovery_active:
        diagnosis.append("Runtime currently shows recovery/reconciliation activity.")

    if not main_chain_available:
        active_path = "compat" if compat_only_available else "blocked"
        success_quality = "compat" if compat_only_available else "blocked"
    elif recovery_active:
        active_path = "recovery"
        success_quality = "recovery"
    elif degraded:
        active_path = "cross_device" if cross_device_available else "main_chain"
        success_quality = "degraded"
    elif cross_device_available:
        active_path = "cross_device"
        success_quality = "canonical_cross_device"
    else:
        active_path = "main_chain"
        success_quality = "canonical_main_chain"

    return OperationalChainState(
        main_chain_available=main_chain_available,
        cross_device_available=cross_device_available,
        compat_only_available=compat_only_available,
        degraded=degraded,
        recovery_active=recovery_active,
        active_path=active_path,
        success_quality=success_quality,
        diagnosis=diagnosis,
    )


def _checkpoint_payload(
    checkpoints: Sequence[AcceptanceCheckpoint],
    chain_state: OperationalChainState,
) -> Dict[str, Any]:
    blocking_failures = [
        cp.checkpoint_id for cp in checkpoints if cp.blocking and cp.status == SurfaceStatus.blocked
    ]
    degraded = [cp.checkpoint_id for cp in checkpoints if cp.status == SurfaceStatus.degraded]
    pending = [cp.checkpoint_id for cp in checkpoints if cp.status == SurfaceStatus.pending]
    canonical_success = (
        not blocking_failures
        and not degraded
        and not pending
        and chain_state.success_quality.startswith("canonical")
    )
    degraded_success = not blocking_failures and not canonical_success and chain_state.main_chain_available
    return {
        "checkpoints": [cp.to_dict() for cp in checkpoints],
        "canonical_success": canonical_success,
        "degraded_success": degraded_success,
        "ready_for_use": canonical_success or degraded_success,
        "blocking_failure_count": len(blocking_failures),
        "degraded_checkpoint_count": len(degraded),
        "pending_checkpoint_count": len(pending),
        "blocking_failure_ids": blocking_failures,
        "degraded_checkpoint_ids": degraded,
        "pending_checkpoint_ids": pending,
    }


def _build_acceptance_surface(
    *,
    validation: OnboardingValidation,
    route_paths: Set[str],
    chain_state: OperationalChainState,
    device_evidence: Dict[str, Any],
    android_evidence: Dict[str, Any],
    session_evidence: Dict[str, Any],
) -> Dict[str, Any]:
    api_missing = sorted(required for required in _REQUIRED_API_PATHS if required not in route_paths)
    android_engaged = (
        device_evidence.get("android_device_count", 0) > 0
        or android_evidence.get("snapshot_count", 0) > 0
        or session_evidence.get("participant_total_count", 0) > 0
        or session_evidence.get("active_session_count", 0) > 0
    )
    checkpoints: List[AcceptanceCheckpoint] = []

    if validation.overall_status == ValidationStatus.FAIL:
        prerequisite_status = SurfaceStatus.blocked
    elif validation.overall_status == ValidationStatus.WARN:
        prerequisite_status = SurfaceStatus.degraded
    else:
        prerequisite_status = SurfaceStatus.ready
    checkpoints.append(
        AcceptanceCheckpoint(
            checkpoint_id="prerequisites",
            display_name="Prerequisite validation",
            status=prerequisite_status,
            blocking=True,
            summary=validation.summary,
            evidence={
                "failed_checks": [item.name for item in validation.failed_checks],
                "warned_checks": [item.name for item in validation.warned_checks],
            },
        )
    )

    checkpoints.append(
        AcceptanceCheckpoint(
            checkpoint_id="backend_started",
            display_name="Backend acceptance surface",
            status=SurfaceStatus.ready if route_paths else SurfaceStatus.pending,
            blocking=True,
            summary=(
                "Operational readiness endpoint is reachable, so backend startup succeeded."
                if route_paths
                else "Report built without a live request context."
            ),
            evidence={"observed_route_count": len(route_paths)},
        )
    )

    checkpoints.append(
        AcceptanceCheckpoint(
            checkpoint_id="core_api_surface",
            display_name="Health / chat / runtime projection reachable",
            status=SurfaceStatus.ready if not api_missing else SurfaceStatus.blocked,
            blocking=True,
            summary=(
                "Required health/chat/runtime/projection surfaces are registered."
                if not api_missing
                else f"Missing required routes: {', '.join(api_missing)}."
            ),
            evidence={
                "required_routes": list(_REQUIRED_API_PATHS),
                "missing_routes": api_missing,
            },
        )
    )

    if not android_engaged:
        android_status = SurfaceStatus.not_applicable
        android_summary = (
            "Cross-device path has not been exercised yet; "
            "Android attachment is optional for current run."
        )
    elif device_evidence.get("android_device_count", 0) > 0:
        android_status = SurfaceStatus.ready
        android_summary = "Android device is admitted on the V2 side."
    else:
        android_status = SurfaceStatus.pending
        android_summary = "Cross-device evidence exists but Android admission is not yet fully visible."
    checkpoints.append(
        AcceptanceCheckpoint(
            checkpoint_id="android_admission",
            display_name="Android device attached on V2 side",
            status=android_status,
            blocking=False,
            summary=android_summary,
            evidence={
                "android_device_ids": device_evidence.get("android_device_ids", []),
                "snapshot_device_ids": android_evidence.get("snapshot_device_ids", []),
            },
        )
    )

    if not android_engaged:
        capability_status = SurfaceStatus.not_applicable
        capability_summary = "Android capability validation skipped because cross-device path is not engaged."
    elif android_evidence.get("capability_visible_count", 0) > 0 and android_evidence.get(
        "degraded_capability_device_count", 0
    ) == 0:
        capability_status = SurfaceStatus.ready
        capability_summary = "Android capability report is visible and canonical."
    elif android_evidence.get("capability_visible_count", 0) > 0:
        capability_status = SurfaceStatus.degraded
        capability_summary = "Android capability is visible but degraded/downgraded."
    else:
        capability_status = SurfaceStatus.pending
        capability_summary = "Android device is attached but capability visibility is not yet canonical."
    checkpoints.append(
        AcceptanceCheckpoint(
            checkpoint_id="android_capability",
            display_name="Android capability visible on V2 side",
            status=capability_status,
            blocking=False,
            summary=capability_summary,
            evidence={
                "capability_visible_count": android_evidence.get("capability_visible_count", 0),
                "degraded_capability_device_count": android_evidence.get("degraded_capability_device_count", 0),
            },
        )
    )

    if not android_engaged:
        task_status = SurfaceStatus.not_applicable
        task_summary = "Delegated task initiation not applicable without Android participation."
    elif session_evidence.get("task_initiated"):
        task_status = SurfaceStatus.ready
        task_summary = "Delegated task initiation is observed in participant/session truth."
    else:
        task_status = SurfaceStatus.pending
        task_summary = "Android attachment exists but task initiation has not been observed yet."
    checkpoints.append(
        AcceptanceCheckpoint(
            checkpoint_id="task_initiation",
            display_name="Task initiation / delegated runtime binding",
            status=task_status,
            blocking=False,
            summary=task_summary,
            evidence={
                "active_session_count": session_evidence.get("active_session_count", 0),
                "participant_phases": session_evidence.get("participant_phases", []),
            },
        )
    )

    if not android_engaged:
        closure_status = SurfaceStatus.not_applicable
        closure_summary = "Result closure path not applicable without Android participation."
    elif session_evidence.get("result_closure_established"):
        closure_status = SurfaceStatus.ready
        closure_summary = "Result return / reconciliation / closure is observed in participant truth."
    elif session_evidence.get("task_initiated"):
        closure_status = SurfaceStatus.degraded
        closure_summary = "Delegated task started but closure is not yet canonical."
    else:
        closure_status = SurfaceStatus.pending
        closure_summary = "Closure cannot be assessed before task initiation."
    checkpoints.append(
        AcceptanceCheckpoint(
            checkpoint_id="result_closure",
            display_name="Result return / reconciliation / closure",
            status=closure_status,
            blocking=False,
            summary=closure_summary,
            evidence={
                "participant_terminal_count": session_evidence.get("participant_terminal_count", 0),
                "participant_terminal_success_count": session_evidence.get(
                    "participant_terminal_success_count", 0
                ),
                "terminal_execution_event_count": android_evidence.get("terminal_execution_event_count", 0),
            },
        )
    )

    quality_status = (
        SurfaceStatus.ready
        if chain_state.success_quality.startswith("canonical")
        else SurfaceStatus.degraded
        if chain_state.main_chain_available
        else SurfaceStatus.blocked
    )
    checkpoints.append(
        AcceptanceCheckpoint(
            checkpoint_id="success_quality",
            display_name="Canonical vs degraded success quality",
            status=quality_status,
            blocking=True,
            summary=f"Current success quality={chain_state.success_quality}, active_path={chain_state.active_path}.",
            evidence=chain_state.to_dict(),
        )
    )

    payload = _checkpoint_payload(checkpoints, chain_state)
    payload["summary"] = (
        "Clone-to-use acceptance chain reached canonical success."
        if payload["canonical_success"]
        else "Clone-to-use acceptance chain is usable but degraded."
        if payload["degraded_success"]
        else "Clone-to-use acceptance chain is not yet complete."
    )
    return payload


def _build_android_standard(
    *,
    device_evidence: Dict[str, Any],
    android_evidence: Dict[str, Any],
    session_evidence: Dict[str, Any],
    chain_state: OperationalChainState,
) -> Dict[str, Any]:
    conditions = [
        {
            "condition_id": "android_registration_entrypoint",
            "label": "Android registration entrypoint",
            "module": "galaxy_gateway.android.handlers.registration",
            "structural_present": _module_available("galaxy_gateway.android.handlers.registration"),
            "current_signal": device_evidence.get("android_device_count", 0) > 0,
        },
        {
            "condition_id": "gateway_transport",
            "label": "Gateway transport + Android bridge",
            "module": "galaxy_gateway.routes.websocket + galaxy_gateway.android.bridge",
            "structural_present": _module_available("galaxy_gateway.routes.websocket")
            and _module_available("galaxy_gateway.android.bridge"),
            "current_signal": bool(device_evidence.get("android_device_count", 0)),
        },
        {
            "condition_id": "capability_device_state_chain",
            "label": "Android capability report + device state mirror",
            "module": "core.android_device_state_store",
            "structural_present": _module_available("core.android_device_state_store"),
            "current_signal": android_evidence.get("capability_visible_count", 0) > 0
            and android_evidence.get("snapshot_count", 0) > 0,
        },
        {
            "condition_id": "session_continuity",
            "label": "Attached runtime session continuity",
            "module": "core.attached_runtime_session_registry",
            "structural_present": _module_available("core.attached_runtime_session_registry"),
            "current_signal": session_evidence.get("active_session_count", 0) > 0,
        },
        {
            "condition_id": "participant_session_state",
            "label": "Android participant session state",
            "module": "core.android_participant_session_state",
            "structural_present": _module_available("core.android_participant_session_state"),
            "current_signal": session_evidence.get("participant_total_count", 0) > 0,
        },
        {
            "condition_id": "runtime_binding",
            "label": "Runtime host + dispatch binding",
            "module": "core.android_runtime_host + core.android_runtime_dispatch_binding",
            "structural_present": _module_available("core.android_runtime_host")
            and _module_available("core.android_runtime_dispatch_binding"),
            "current_signal": session_evidence.get("task_initiated", False),
        },
        {
            "condition_id": "governance_acceptance",
            "label": "Center-side governance and acceptance authority",
            "module": "core.unified_execution_governance",
            "structural_present": _module_available("core.unified_execution_governance"),
            "current_signal": chain_state.main_chain_available,
        },
    ]

    remaining_gaps = [
        condition["condition_id"]
        for condition in conditions
        if not condition["structural_present"] or not condition["current_signal"]
    ]
    return {
        "android_registration_entrypoint": "galaxy_gateway.android.handlers.registration",
        "cross_device_enabled_minimum": {
            "gateway_transport": "galaxy_gateway.routes.websocket",
            "android_bridge": "galaxy_gateway.android.bridge",
            "device_state_store": "core.android_device_state_store",
            "session_continuity": "core.attached_runtime_session_registry",
            "participant_session_state": "core.android_participant_session_state",
            "runtime_host": "core.android_runtime_host",
            "dispatch_binding": "core.android_runtime_dispatch_binding",
            "governance_authority": "core.unified_execution_governance",
        },
        "android_originated_initiation_recognition": {
            "recognized_by": [
                "core.android_participant_session_state",
                "core.attached_runtime_session_registry",
                "core.android_runtime_host",
                "core.unified_execution_governance",
            ],
            "currently_observed": session_evidence.get("participant_total_count", 0) > 0
            or android_evidence.get("execution_event_count", 0) > 0,
        },
        "minimum_viable_chain_conditions": conditions,
        "minimum_viable_chain_ready": len(remaining_gaps) == 0,
        "current_observation": {
            "android_device_count": device_evidence.get("android_device_count", 0),
            "capability_visible_count": android_evidence.get("capability_visible_count", 0),
            "active_session_count": session_evidence.get("active_session_count", 0),
            "participant_total_count": session_evidence.get("participant_total_count", 0),
            "result_closure_established": session_evidence.get("result_closure_established", False),
            "success_quality": chain_state.success_quality,
        },
        "remaining_gaps": remaining_gaps,
        "dual_repo_anchor_note": (
            "Android is the distributed runtime participant; V2 remains the center-side "
            "governance, orchestration, truth convergence, and acceptance authority."
        ),
    }


def build_operational_readiness_report(
    *,
    route_paths: Optional[Iterable[str]] = None,
) -> OperationalReadinessReport:
    """Build the unified registration/readiness/acceptance report."""
    path = get_operational_registration_path()
    validation = path.validation or validate_registration_prerequisites()
    live_route_paths = set(route_paths or [])
    device_evidence = _collect_device_evidence()
    android_evidence = _collect_android_evidence()
    session_evidence = _collect_session_evidence()
    runtime_readiness = _load_runtime_readiness()
    system_acceptance = _load_system_acceptance()

    kind_states = _build_registration_kind_states(
        path,
        runtime_readiness=runtime_readiness,
        device_evidence=device_evidence,
        android_evidence=android_evidence,
        session_evidence=session_evidence,
    )
    domains = _build_domain_states(kind_states)
    chain_state = _build_chain_state(
        path,
        validation=validation,
        kind_states=kind_states,
        route_paths=live_route_paths,
        runtime_readiness=runtime_readiness,
        device_evidence=device_evidence,
        android_evidence=android_evidence,
        session_evidence=session_evidence,
    )
    acceptance = _build_acceptance_surface(
        validation=validation,
        route_paths=live_route_paths,
        chain_state=chain_state,
        device_evidence=device_evidence,
        android_evidence=android_evidence,
        session_evidence=session_evidence,
    )
    android_standard = _build_android_standard(
        device_evidence=device_evidence,
        android_evidence=android_evidence,
        session_evidence=session_evidence,
        chain_state=chain_state,
    )
    progress = _build_registration_progress(
        path,
        validation=validation,
        kind_states=kind_states,
    )

    return OperationalReadinessReport(
        generated_at=time.time(),
        authority=OPERATIONAL_READINESS_SURFACE_AUTHORITY,
        contract_version=OPERATIONAL_READINESS_SURFACE_CONTRACT_VERSION,
        path_authority=OPERATIONAL_REGISTRATION_PATH_AUTHORITY,
        path_contract_version=OPERATIONAL_REGISTRATION_PATH_CONTRACT_VERSION,
        system_identity=path.system_identity,
        validation=validation.to_dict(),
        registration_progress=progress,
        registration_kinds=kind_states,
        registration_domains=domains,
        chain_state=chain_state,
        clone_to_use_acceptance=acceptance,
        android_v2_minimum_standard=android_standard,
        runtime_readiness=runtime_readiness,
        system_acceptance=system_acceptance,
    )
