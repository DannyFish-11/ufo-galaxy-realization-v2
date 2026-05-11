"""
core/v2_unified_state_contract.py
=================================

Executable unified V2-side state contract that sits beneath the
``core.operational_readiness_surface`` aggregation/reporting layer.

The contract is intentionally read-only and additive:

* it does not create a second truth store
* it identifies the current source fragments for each state domain
* it formalizes how raw signals become derived state, acceptance,
  eligibility, and closure/quality semantics
* it stays explicit that Android symmetry is not yet guaranteed by V2 alone

Lifecycle hardening (PR-lifecycle-hardening)
--------------------------------------------
``build_v2_unified_state_contract`` now populates a ``lifecycle_hardening``
field with the :class:`~core.executable_lifecycle_hardening.ExecutableLifecycleState`
produced by ``core.executable_lifecycle_hardening``.  This makes admission,
task-initiation gating, and result-closure semantics explicit rather than
inferred, and exposes degraded/recovery transitions as first-class lifecycle
stage annotations.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from core.operational_registration_path import (
    OPERATIONAL_REGISTRATION_PATH_AUTHORITY,
    OPERATIONAL_REGISTRATION_PATH_CONTRACT_VERSION,
    OnboardingValidation,
    OperationalRegistrationPath,
    PathTier,
    ValidationStatus,
)

logger = logging.getLogger("Galaxy.V2UnifiedStateContract")

__all__ = [
    "V2_UNIFIED_STATE_CONTRACT_AUTHORITY",
    "V2_UNIFIED_STATE_CONTRACT_VERSION",
    "ContractDecision",
    "V2UnifiedStateContract",
    "build_v2_unified_state_contract",
]


V2_UNIFIED_STATE_CONTRACT_AUTHORITY: str = "core.v2_unified_state_contract::v2-side-executable-state-contract"
V2_UNIFIED_STATE_CONTRACT_VERSION: str = "1.1.0"

_REQUIRED_API_PATHS: tuple[str, ...] = (
    "/api/v1/health",
    "/api/v1/chat",
    "/api/v1/projection/runtime",
    "/api/v1/projection/operational-readiness",
    "/api/v1/projection/clone-to-use-acceptance",
)


@dataclass
class ContractDecision:
    decision_id: str
    label: str
    state: str
    summary: str
    sources: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    observable: bool = False
    acceptable: Optional[bool] = None
    eligible: Optional[bool] = None
    active: Optional[bool] = None
    complete: Optional[bool] = None
    quality: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "label": self.label,
            "state": self.state,
            "summary": self.summary,
            "sources": list(self.sources),
            "reasons": list(self.reasons),
            "evidence": dict(self.evidence),
            "observable": self.observable,
            "acceptable": self.acceptable,
            "eligible": self.eligible,
            "active": self.active,
            "complete": self.complete,
            "quality": self.quality,
        }


@dataclass
class V2UnifiedStateContract:
    authority: str
    contract_version: str
    path_authority: str
    path_contract_version: str
    raw_signals: Dict[str, Any]
    derived_state: Dict[str, ContractDecision]
    acceptance_state: Dict[str, ContractDecision]
    eligibility_state: Dict[str, ContractDecision]
    closure_quality_state: Dict[str, ContractDecision]
    lifecycle_hardening: Optional[Dict[str, Any]] = field(default=None)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "authority": self.authority,
            "contract_version": self.contract_version,
            "path_authority": self.path_authority,
            "path_contract_version": self.path_contract_version,
            "raw_signals": dict(self.raw_signals),
            "derived_state": {key: value.to_dict() for key, value in self.derived_state.items()},
            "acceptance_state": {key: value.to_dict() for key, value in self.acceptance_state.items()},
            "eligibility_state": {key: value.to_dict() for key, value in self.eligibility_state.items()},
            "closure_quality_state": {key: value.to_dict() for key, value in self.closure_quality_state.items()},
        }
        if self.lifecycle_hardening is not None:
            result["lifecycle_hardening"] = self.lifecycle_hardening
        return result

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def _status_value(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _base_sources(*sources: str) -> List[str]:
    seen: Set[str] = set()
    result: List[str] = []
    for source in sources:
        if source and source not in seen:
            seen.add(source)
            result.append(source)
    return result


def build_v2_unified_state_contract(
    *,
    path: OperationalRegistrationPath,
    validation: OnboardingValidation,
    kind_states: Sequence[Any],
    route_paths: Optional[Iterable[str]] = None,
    runtime_readiness: Optional[Dict[str, Any]] = None,
    device_evidence: Optional[Dict[str, Any]] = None,
    android_evidence: Optional[Dict[str, Any]] = None,
    session_evidence: Optional[Dict[str, Any]] = None,
    system_acceptance: Optional[Dict[str, Any]] = None,
    result_ingress_evidence: Optional[Dict[str, Any]] = None,
) -> V2UnifiedStateContract:
    route_paths_set = set(route_paths or [])
    runtime_readiness = dict(runtime_readiness or {})
    device_evidence = dict(device_evidence or {})
    android_evidence = dict(android_evidence or {})
    session_evidence = dict(session_evidence or {})
    system_acceptance = dict(system_acceptance or {})

    by_kind = {getattr(state, "kind", ""): state for state in kind_states}
    main_chain_states = [by_kind[kind.value] for kind in path.main_chain_kinds if kind.value in by_kind]

    api_missing = sorted(required for required in _REQUIRED_API_PATHS if required not in route_paths_set)
    main_chain_blocked = any(_status_value(getattr(item, "status", "")) == "blocked" for item in main_chain_states)
    registration_degraded = any(_status_value(getattr(item, "status", "")) == "degraded" for item in kind_states)
    registration_pending = any(_status_value(getattr(item, "status", "")) == "pending" for item in main_chain_states)

    android_attached = (
        device_evidence.get("android_device_count", 0) > 0
        or android_evidence.get("snapshot_count", 0) > 0
        or session_evidence.get("participant_total_count", 0) > 0
    )
    capability_visible = android_evidence.get("capability_visible_count", 0) > 0
    capability_degraded = android_evidence.get("degraded_capability_device_count", 0) > 0
    runtime_verdict = str(runtime_readiness.get("verdict", "unknown"))
    main_chain_available = (
        validation.overall_status != ValidationStatus.FAIL
        and not main_chain_blocked
        and runtime_verdict != "blocked"
        and not api_missing
    )
    cross_device_available = (
        android_attached
        and capability_visible
        and session_evidence.get("active_session_count", 0) > 0
        and bool(session_evidence.get("task_initiated", False))
    )
    compat_only_available = not main_chain_available and any(
        getattr(state, "path_tier", "")
        in {
            PathTier.COMPAT.value,
            PathTier.FALLBACK.value,
            PathTier.RECOVERY.value,
        }
        and _status_value(getattr(state, "status", "")) != "blocked"
        for state in kind_states
    )
    recovery_active = bool(session_evidence.get("recovery_active"))
    degraded = (
        validation.overall_status == ValidationStatus.WARN
        or runtime_verdict in {"degraded", "unknown"}
        or capability_degraded
    )

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

    task_initiated = bool(session_evidence.get("task_initiated", False))
    result_closure_established = bool(session_evidence.get("result_closure_established", False))
    acceptance_verdict = str(system_acceptance.get("verdict", "acceptance_unknown_insufficient_evidence"))

    raw_signals: Dict[str, Any] = {
        "validation_status": validation.overall_status.value,
        "validation_summary": validation.summary,
        "required_route_count": len(_REQUIRED_API_PATHS),
        "observed_route_count": len(route_paths_set),
        "missing_required_routes": api_missing,
        "runtime_readiness_verdict": runtime_verdict,
        "system_acceptance_verdict": acceptance_verdict,
        "android_attached": android_attached,
        "android_device_count": device_evidence.get("android_device_count", 0),
        "snapshot_count": android_evidence.get("snapshot_count", 0),
        "capability_visible_count": android_evidence.get("capability_visible_count", 0),
        "degraded_capability_device_count": android_evidence.get("degraded_capability_device_count", 0),
        "active_session_count": session_evidence.get("active_session_count", 0),
        "total_session_count": session_evidence.get("total_session_count", 0),
        "participant_total_count": session_evidence.get("participant_total_count", 0),
        "participant_terminal_count": session_evidence.get("participant_terminal_count", 0),
        "task_initiated": task_initiated,
        "result_closure_established": result_closure_established,
        "recovery_active": recovery_active,
    }

    derived_state = {
        "registration_state": ContractDecision(
            decision_id="registration_state",
            label="Registration state",
            state=(
                "blocked"
                if validation.overall_status == ValidationStatus.FAIL or main_chain_blocked
                else (
                    "degraded"
                    if validation.overall_status == ValidationStatus.WARN or registration_degraded
                    else "pending" if registration_pending else "ready"
                )
            ),
            summary=(
                "Registration is blocked by failing prerequisites or blocked main-chain kinds."
                if validation.overall_status == ValidationStatus.FAIL or main_chain_blocked
                else (
                    "Registration is present but includes degraded evidence."
                    if validation.overall_status == ValidationStatus.WARN or registration_degraded
                    else (
                        "Registration layers are present but not fully exercised."
                        if registration_pending
                        else "Registration is structurally ready on the V2 side."
                    )
                )
            ),
            sources=_base_sources(
                "core.operational_registration_path",
                "core.operational_readiness_surface.registration_kind_states",
            ),
            reasons=[
                validation.summary,
                f"main_chain_blocked={main_chain_blocked}",
                f"registration_pending={registration_pending}",
            ],
            evidence={
                "main_chain_blocked": main_chain_blocked,
                "registration_pending": registration_pending,
                "registration_degraded": registration_degraded,
            },
            observable=True,
            acceptable=main_chain_available,
        ),
        "capability_visibility": ContractDecision(
            decision_id="capability_visibility",
            label="Capability visibility",
            state=(
                "not_applicable"
                if not android_attached
                else (
                    "degraded_visible"
                    if capability_visible and capability_degraded
                    else "visible" if capability_visible else "waiting_dependency"
                )
            ),
            summary=(
                "Android capability visibility is not required for the current path."
                if not android_attached
                else (
                    "Android capability is visible but degraded/downgraded."
                    if capability_visible and capability_degraded
                    else (
                        "Android capability visibility is canonical on V2."
                        if capability_visible
                        else "Android is attached but capability visibility is still pending."
                    )
                )
            ),
            sources=_base_sources(
                "core.android_device_state_store",
                "galaxy_gateway.android.handlers.capability_report",
            ),
            reasons=[
                f"android_attached={android_attached}",
                f"capability_visible={capability_visible}",
                f"capability_degraded={capability_degraded}",
            ],
            evidence={
                "capability_visible_count": android_evidence.get("capability_visible_count", 0),
                "degraded_capability_device_count": android_evidence.get("degraded_capability_device_count", 0),
            },
            observable=android_attached or capability_visible,
            acceptable=not android_attached or capability_visible,
        ),
        "operational_readiness": ContractDecision(
            decision_id="operational_readiness",
            label="Operational readiness",
            state=("blocked" if not main_chain_available else "degraded" if degraded or recovery_active else "ready"),
            summary=(
                "Operational readiness is blocked until the main chain and required APIs are available."
                if not main_chain_available
                else (
                    "Operational readiness is usable but not fully canonical."
                    if degraded or recovery_active
                    else "Operational readiness is canonical on the current V2 side."
                )
            ),
            sources=_base_sources(
                "core.runtime_readiness_matrix",
                "core.system_final_acceptance_verdict",
                "core.operational_registration_path",
            ),
            reasons=[
                f"runtime_verdict={runtime_verdict}",
                f"missing_required_routes={api_missing}",
                f"recovery_active={recovery_active}",
            ],
            evidence={
                "main_chain_available": main_chain_available,
                "degraded": degraded,
                "recovery_active": recovery_active,
            },
            observable=True,
            acceptable=main_chain_available,
        ),
        "active_path": ContractDecision(
            decision_id="active_path",
            label="Active path",
            state=active_path,
            summary=f"Current active path is {active_path}.",
            sources=_base_sources(
                "core.operational_registration_path",
                "core.runtime_readiness_matrix",
                "core.attached_runtime_session_registry",
            ),
            reasons=[
                f"main_chain_available={main_chain_available}",
                f"cross_device_available={cross_device_available}",
                f"compat_only_available={compat_only_available}",
            ],
            evidence={
                "main_chain_available": main_chain_available,
                "cross_device_available": cross_device_available,
                "compat_only_available": compat_only_available,
            },
            observable=True,
            acceptable=main_chain_available,
            active=active_path != "blocked",
            quality=success_quality,
        ),
        "compat_only_path": ContractDecision(
            decision_id="compat_only_path",
            label="Compat-only path",
            state=("active" if active_path == "compat" else "available" if compat_only_available else "not_available"),
            summary=(
                "Only the compat path is currently available."
                if active_path == "compat"
                else (
                    "Compat fallback exists but is not the active path."
                    if compat_only_available
                    else "Compat fallback is not currently in use."
                )
            ),
            sources=_base_sources(
                "core.operational_registration_path",
                "core.runtime_readiness_matrix",
            ),
            reasons=[
                f"compat_only_available={compat_only_available}",
                f"active_path={active_path}",
            ],
            evidence={"compat_only_available": compat_only_available},
            observable=compat_only_available or active_path == "compat",
            acceptable=compat_only_available,
            active=active_path == "compat",
        ),
        "degraded_path": ContractDecision(
            decision_id="degraded_path",
            label="Compat/degraded path",
            state="degraded_operation" if degraded else "canonical_operation",
            summary=("Current path is degraded or warning-qualified." if degraded else "Current path is canonical."),
            sources=_base_sources(
                "core.runtime_readiness_matrix",
                "core.android_device_state_store",
                "core.operational_registration_path",
            ),
            reasons=[
                f"validation_status={validation.overall_status.value}",
                f"runtime_verdict={runtime_verdict}",
                f"capability_degraded={capability_degraded}",
            ],
            evidence={"degraded": degraded},
            observable=True,
            acceptable=main_chain_available,
            active=degraded,
        ),
        "recovery_active_state": ContractDecision(
            decision_id="recovery_active_state",
            label="Recovery-active state",
            state="active" if recovery_active else "inactive",
            summary=(
                "Recovery/reconciliation is currently active."
                if recovery_active
                else "Recovery is not currently active."
            ),
            sources=_base_sources(
                "core.attached_runtime_session_registry",
                "core.android_participant_session_state",
            ),
            reasons=[f"recovery_active={recovery_active}"],
            evidence={
                "replaced_session_count": session_evidence.get("replaced_session_count", 0),
                "detached_session_count": session_evidence.get("detached_session_count", 0),
                "invalidated_session_count": session_evidence.get("invalidated_session_count", 0),
            },
            observable=recovery_active,
            active=recovery_active,
        ),
        "main_chain_availability": ContractDecision(
            decision_id="main_chain_availability",
            label="Main-chain availability",
            state="available" if main_chain_available else "blocked",
            summary=(
                "Main chain is currently available." if main_chain_available else "Main chain is currently unavailable."
            ),
            sources=_base_sources(
                "core.operational_registration_path",
                "core.runtime_readiness_matrix",
            ),
            reasons=[
                f"validation_status={validation.overall_status.value}",
                f"runtime_verdict={runtime_verdict}",
                f"missing_required_routes={api_missing}",
            ],
            evidence={"missing_required_routes": api_missing},
            observable=True,
            acceptable=main_chain_available,
            active=main_chain_available,
        ),
        "cross_device_availability": ContractDecision(
            decision_id="cross_device_availability",
            label="Cross-device availability",
            state=(
                "available"
                if cross_device_available
                else "waiting_dependency" if android_attached else "not_applicable"
            ),
            summary=(
                "Cross-device path is available."
                if cross_device_available
                else (
                    "Cross-device path is attached but still waiting on missing dependencies."
                    if android_attached
                    else "Cross-device path is not engaged."
                )
            ),
            sources=_base_sources(
                "core.device_readiness",
                "core.android_device_state_store",
                "core.attached_runtime_session_registry",
            ),
            reasons=[
                f"android_attached={android_attached}",
                f"capability_visible={capability_visible}",
                f"active_session_count={session_evidence.get('active_session_count', 0)}",
                f"task_initiated={task_initiated}",
            ],
            evidence={
                "cross_device_ready_device_ids": device_evidence.get("cross_device_ready_device_ids", []),
                "capability_visible_count": android_evidence.get("capability_visible_count", 0),
                "active_session_count": session_evidence.get("active_session_count", 0),
            },
            observable=android_attached or cross_device_available,
            acceptable=cross_device_available,
            active=cross_device_available,
        ),
        "session_continuity": ContractDecision(
            decision_id="session_continuity",
            label="Session continuity",
            state=(
                "recovery_active"
                if recovery_active
                else (
                    "continuous"
                    if session_evidence.get("active_session_count", 0) > 0
                    else (
                        "incomplete"
                        if session_evidence.get("total_session_count", 0) > 0
                        or session_evidence.get("participant_total_count", 0) > 0
                        else "waiting_dependency" if android_attached else "not_applicable"
                    )
                )
            ),
            summary=(
                "Session continuity is currently in recovery."
                if recovery_active
                else (
                    "Session continuity is active and attached."
                    if session_evidence.get("active_session_count", 0) > 0
                    else (
                        "Session traces exist but continuity is not yet active."
                        if session_evidence.get("total_session_count", 0) > 0
                        or session_evidence.get("participant_total_count", 0) > 0
                        else (
                            "Cross-device session continuity is still waiting on session attachment."
                            if android_attached
                            else "Session continuity is not applicable for the current path."
                        )
                    )
                )
            ),
            sources=_base_sources(
                "core.attached_runtime_session_registry",
                "core.android_participant_session_state",
            ),
            reasons=[
                f"active_session_count={session_evidence.get('active_session_count', 0)}",
                f"participant_total_count={session_evidence.get('participant_total_count', 0)}",
                f"recovery_active={recovery_active}",
            ],
            evidence={
                "active_session_count": session_evidence.get("active_session_count", 0),
                "total_session_count": session_evidence.get("total_session_count", 0),
                "participant_total_count": session_evidence.get("participant_total_count", 0),
            },
            observable=android_attached or session_evidence.get("total_session_count", 0) > 0,
            acceptable=session_evidence.get("active_session_count", 0) > 0,
            active=session_evidence.get("active_session_count", 0) > 0,
        ),
    }

    acceptance_state = {
        "operational_acceptance": ContractDecision(
            decision_id="operational_acceptance",
            label="Operational acceptance state",
            state=(
                "blocked"
                if not main_chain_available
                else "acceptable_degraded" if degraded or acceptance_verdict != "fully_operational" else "acceptable"
            ),
            summary=(
                "System is not yet acceptable for operational use."
                if not main_chain_available
                else (
                    "System is operationally acceptable but still degraded or warning-qualified."
                    if degraded or acceptance_verdict != "fully_operational"
                    else "System is operationally acceptable on canonical V2 terms."
                )
            ),
            sources=_base_sources(
                "core.system_final_acceptance_verdict",
                "core.runtime_readiness_matrix",
                "core.operational_registration_path",
            ),
            reasons=[
                f"system_acceptance_verdict={acceptance_verdict}",
                f"main_chain_available={main_chain_available}",
                f"degraded={degraded}",
            ],
            evidence={"system_acceptance_verdict": acceptance_verdict},
            observable=True,
            acceptable=main_chain_available,
            quality="canonical" if main_chain_available and not degraded else "degraded",
        ),
        "cross_device_acceptance": ContractDecision(
            decision_id="cross_device_acceptance",
            label="Cross-device acceptance state",
            state=(
                "acceptable"
                if cross_device_available
                else "waiting_dependency" if android_attached else "not_applicable"
            ),
            summary=(
                "Cross-device operation is acceptable on current evidence."
                if cross_device_available
                else (
                    "Cross-device evidence exists but the chain is not yet acceptable."
                    if android_attached
                    else "Cross-device acceptance is not required for the current path."
                )
            ),
            sources=_base_sources(
                "core.device_readiness",
                "core.android_device_state_store",
                "core.attached_runtime_session_registry",
            ),
            reasons=[
                f"cross_device_available={cross_device_available}",
                f"android_attached={android_attached}",
            ],
            evidence={
                "active_session_count": session_evidence.get("active_session_count", 0),
                "capability_visible_count": android_evidence.get("capability_visible_count", 0),
            },
            observable=android_attached or cross_device_available,
            acceptable=cross_device_available,
        ),
    }

    eligibility_state = {
        "task_initiation": ContractDecision(
            decision_id="task_initiation",
            label="Task initiation eligibility",
            state=(
                "not_applicable"
                if not android_attached
                else (
                    "blocked"
                    if not main_chain_available
                    else (
                        "eligible"
                        if capability_visible and session_evidence.get("active_session_count", 0) > 0
                        else "waiting_dependency"
                    )
                )
            ),
            summary=(
                "Task initiation is not applicable without Android participation."
                if not android_attached
                else (
                    "Task initiation is blocked until the main chain is available."
                    if not main_chain_available
                    else (
                        "Task initiation is currently eligible."
                        if capability_visible and session_evidence.get("active_session_count", 0) > 0
                        else "Task initiation is waiting on capability visibility or active session continuity."
                    )
                )
            ),
            sources=_base_sources(
                "core.android_device_state_store",
                "core.attached_runtime_session_registry",
                "core.android_runtime_host",
                "core.android_runtime_dispatch_binding",
            ),
            reasons=[
                f"android_attached={android_attached}",
                f"main_chain_available={main_chain_available}",
                f"capability_visible={capability_visible}",
                f"active_session_count={session_evidence.get('active_session_count', 0)}",
            ],
            evidence={
                "capability_visible_count": android_evidence.get("capability_visible_count", 0),
                "active_session_count": session_evidence.get("active_session_count", 0),
                "task_initiated": task_initiated,
            },
            observable=android_attached or task_initiated,
            acceptable=main_chain_available,
            eligible=(
                android_attached
                and main_chain_available
                and capability_visible
                and session_evidence.get("active_session_count", 0) > 0
            ),
            active=task_initiated,
        ),
    }

    if success_quality.startswith("canonical") and acceptance_verdict == "fully_operational":
        verdict_quality = "canonical"
    elif success_quality == "recovery":
        verdict_quality = "recovery"
    elif success_quality == "compat":
        verdict_quality = "compat"
    elif success_quality == "blocked":
        verdict_quality = "blocked"
    else:
        verdict_quality = "degraded"
    waiting_dependency_reasons = []
    if android_attached and not capability_visible:
        waiting_dependency_reasons.append("capability_visibility")
    if android_attached and session_evidence.get("active_session_count", 0) == 0:
        waiting_dependency_reasons.append("active_session")
    if android_attached and not task_initiated:
        waiting_dependency_reasons.append("task_initiation")

    closure_quality_state = {
        "result_closure": ContractDecision(
            decision_id="result_closure",
            label="Result closure state",
            state=(
                "complete"
                if result_closure_established
                else "incomplete" if task_initiated else "waiting_dependency" if android_attached else "not_applicable"
            ),
            summary=(
                "Result closure is established."
                if result_closure_established
                else (
                    "Task initiation has started but result closure is still incomplete."
                    if task_initiated
                    else (
                        "Result closure is waiting on task initiation."
                        if android_attached
                        else "Result closure is not applicable for the current path."
                    )
                )
            ),
            sources=_base_sources(
                "core.android_participant_session_state",
                "core.attached_runtime_session_registry",
                "core.unified_result_ingress",
            ),
            reasons=[
                f"task_initiated={task_initiated}",
                f"result_closure_established={result_closure_established}",
            ],
            evidence={
                "participant_terminal_count": session_evidence.get("participant_terminal_count", 0),
                "participant_terminal_success_count": session_evidence.get("participant_terminal_success_count", 0),
            },
            observable=task_initiated or result_closure_established,
            complete=result_closure_established,
            quality="canonical" if result_closure_established else "incomplete",
        ),
        "success_quality": ContractDecision(
            decision_id="success_quality",
            label="Success quality",
            state=success_quality,
            summary=f"Current success quality is {success_quality}.",
            sources=_base_sources(
                "core.runtime_readiness_matrix",
                "core.system_final_acceptance_verdict",
                "core.android_participant_session_state",
            ),
            reasons=[
                f"active_path={active_path}",
                f"main_chain_available={main_chain_available}",
                f"cross_device_available={cross_device_available}",
            ],
            evidence={
                "active_path": active_path,
                "main_chain_available": main_chain_available,
                "cross_device_available": cross_device_available,
            },
            observable=True,
            acceptable=main_chain_available,
            active=active_path != "blocked",
            quality=success_quality,
        ),
        "verdict_quality": ContractDecision(
            decision_id="verdict_quality",
            label="Verdict quality",
            state=verdict_quality,
            summary=(
                "Verdict quality is canonical."
                if verdict_quality == "canonical"
                else f"Verdict quality is {verdict_quality}."
            ),
            sources=_base_sources(
                "core.system_final_acceptance_verdict",
                "core.runtime_readiness_matrix",
            ),
            reasons=[
                f"system_acceptance_verdict={acceptance_verdict}",
                f"success_quality={success_quality}",
            ],
            evidence={
                "system_acceptance_verdict": acceptance_verdict,
                "success_quality": success_quality,
            },
            observable=True,
            quality=verdict_quality,
        ),
        "blocked_state": ContractDecision(
            decision_id="blocked_state",
            label="Blocked state",
            state="present" if not main_chain_available else "clear",
            summary=(
                "A blocking condition is present."
                if not main_chain_available
                else "No blocking condition is currently present."
            ),
            sources=_base_sources(
                "core.operational_registration_path",
                "core.runtime_readiness_matrix",
            ),
            reasons=[
                f"main_chain_available={main_chain_available}",
                f"runtime_verdict={runtime_verdict}",
                f"missing_required_routes={api_missing}",
            ],
            evidence={
                "main_chain_available": main_chain_available,
                "missing_required_routes": api_missing,
            },
            observable=not main_chain_available,
            acceptable=main_chain_available,
        ),
        "waiting_dependency_state": ContractDecision(
            decision_id="waiting_dependency_state",
            label="Waiting-dependency state",
            state="present" if waiting_dependency_reasons else "clear",
            summary=(
                "One or more dependencies are still missing."
                if waiting_dependency_reasons
                else "No waiting dependency is currently present."
            ),
            sources=_base_sources(
                "core.android_device_state_store",
                "core.attached_runtime_session_registry",
            ),
            reasons=list(waiting_dependency_reasons),
            evidence={"waiting_dependencies": list(waiting_dependency_reasons)},
            observable=bool(waiting_dependency_reasons),
        ),
        "incomplete_state": ContractDecision(
            decision_id="incomplete_state",
            label="Incomplete state",
            state="present" if task_initiated and not result_closure_established else "clear",
            summary=(
                "Execution has started but completion is not yet closed."
                if task_initiated and not result_closure_established
                else "No incomplete closure state is currently present."
            ),
            sources=_base_sources(
                "core.android_participant_session_state",
                "core.unified_result_ingress",
            ),
            reasons=[
                f"task_initiated={task_initiated}",
                f"result_closure_established={result_closure_established}",
            ],
            evidence={
                "task_initiated": task_initiated,
                "result_closure_established": result_closure_established,
            },
            observable=task_initiated and not result_closure_established,
            complete=result_closure_established,
        ),
    }

    # --- Lifecycle hardening ---
    lifecycle_hardening_dict: Optional[Dict[str, Any]] = None
    try:
        from core.executable_lifecycle_hardening import (  # noqa: PLC0415
            build_executable_lifecycle_state,
        )
        lifecycle_state = build_executable_lifecycle_state(
            validation=validation,
            kind_states=kind_states,
            route_paths=route_paths,
            runtime_readiness=runtime_readiness,
            device_evidence=device_evidence,
            android_evidence=android_evidence,
            session_evidence=session_evidence,
            system_acceptance=system_acceptance,
            result_ingress_evidence=result_ingress_evidence,
        )
        lifecycle_hardening_dict = lifecycle_state.to_dict()
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "lifecycle_hardening population failed: %s "
            "(validation_status=%s, android_device_count=%s, runtime_verdict=%s)",
            exc,
            getattr(getattr(validation, "overall_status", None), "value", "unknown"),
            (device_evidence or {}).get("android_device_count", 0),
            (runtime_readiness or {}).get("verdict", "unknown"),
        )
        lifecycle_hardening_dict = {"error": str(exc)}

    return V2UnifiedStateContract(
        authority=V2_UNIFIED_STATE_CONTRACT_AUTHORITY,
        contract_version=V2_UNIFIED_STATE_CONTRACT_VERSION,
        path_authority=OPERATIONAL_REGISTRATION_PATH_AUTHORITY,
        path_contract_version=OPERATIONAL_REGISTRATION_PATH_CONTRACT_VERSION,
        raw_signals=raw_signals,
        derived_state=derived_state,
        acceptance_state=acceptance_state,
        eligibility_state=eligibility_state,
        closure_quality_state=closure_quality_state,
        lifecycle_hardening=lifecycle_hardening_dict,
    )
