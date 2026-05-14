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
V2_UNIFIED_STATE_CONTRACT_VERSION: str = "1.3.0"

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
    # lifecycle_stage classifies this decision into the operational lifecycle:
    # observation | admission | readiness | eligibility | execution | closure | conditions
    lifecycle_stage: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
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
        if self.lifecycle_stage is not None:
            result["lifecycle_stage"] = self.lifecycle_stage
        return result


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
    participation_evidence: Optional[Dict[str, Any]] = None,
) -> V2UnifiedStateContract:
    route_paths_set = set(route_paths or [])
    runtime_readiness = dict(runtime_readiness or {})
    device_evidence = dict(device_evidence or {})
    android_evidence = dict(android_evidence or {})
    session_evidence = dict(session_evidence or {})
    system_acceptance = dict(system_acceptance or {})
    participation_evidence = dict(participation_evidence or {})

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

    # --- PR-1 / SSOT: Derive unified Android network participation tier ---
    # Prefer caller-supplied participation_evidence (already in SSOT format).
    # When not supplied, build from SSOT block if a device_id is available.
    # Final fallback: inline derivation from scattered evidence signals.
    _participation_tier_str = "local_only"
    _participation_blocking: List[str] = []
    _participation_notes: List[str] = []
    _participation_source = "authoritative_unavailable_inline_derivation"
    _participation_transition_history: List[Dict[str, Any]] = list(
        participation_evidence.get("transition_history", [])
    )
    _participation_last_signal = participation_evidence.get("last_signal")
    _participation_prior_tier = participation_evidence.get("prior_tier")
    try:
        if participation_evidence:
            # Caller supplied pre-computed participation evidence (already SSOT-normalised)
            _participation_tier_str = participation_evidence.get("tier", "local_only")
            _participation_blocking = list(participation_evidence.get("blocking_reasons", []))
            _participation_notes = list(participation_evidence.get("tier_derivation_notes", []))
            _participation_source = participation_evidence.get("source", "participation_evidence")
        else:
            android_device_ids = list(device_evidence.get("android_device_ids") or [])
            # SSOT path: consume one authoritative Android participant at a
            # time (primary-first) for this contract projection.
            target_device_id = str(android_device_ids[0]) if android_device_ids else ""
            if target_device_id:
                from core.v2_android_truth_ssot import build_v2_android_truth_block  # noqa: PLC0415

                truth_block = build_v2_android_truth_block(target_device_id, include_history_limit=10)
                _participation_tier_str = truth_block.participation_tier
                _participation_blocking = list(truth_block.participation_blocking_reasons)
                _participation_notes = list(truth_block.participation_tier_notes)
                _participation_source = "core.v2_android_truth_ssot"
                _participation_transition_history = list(truth_block.participation_transition_history)
                _participation_last_signal = truth_block.participation_last_signal
                _participation_prior_tier = truth_block.participation_prior_tier
            else:
                # Conservative fallback when no Android device identity is available.
                from core.android_network_participation import (  # noqa: PLC0415
                    derive_android_network_participation_tier,
                    get_participation_state_for_device,
                )
                _pe_websocket = android_attached
                _pe_reg_ack = android_attached
                _pe_fully_attached = (
                    android_attached
                    and device_evidence.get("registration_fully_attached", False)
                )
                _pe_gaps = list(device_evidence.get("registration_gaps", []))
                _pe_capability_visible = capability_visible
                _pe_session_count = session_evidence.get("active_session_count", 0)
                _pe_posture = session_evidence.get("session_posture", "")
                _pe_cross_device_enabled = (
                    capability_visible
                    and session_evidence.get("active_session_count", 0) > 0
                )
                _pe_readiness = (
                    capability_visible
                    and _pe_session_count > 0
                    and _pe_posture == "join_runtime"
                )
                _pe_dispatch = cross_device_available and _pe_readiness
                _pe_execution = task_initiated and not result_closure_established

                _tier, _participation_blocking, _participation_notes = (
                    derive_android_network_participation_tier(
                        websocket_connected=_pe_websocket,
                        registration_ack_success=_pe_reg_ack,
                        registration_fully_attached=_pe_fully_attached,
                        registration_gaps=_pe_gaps,
                        capability_visible=_pe_capability_visible,
                        active_session_count=_pe_session_count,
                        session_posture=_pe_posture,
                        cross_device_enabled=_pe_cross_device_enabled,
                        readiness_satisfied=_pe_readiness,
                        dispatch_gate_passed=_pe_dispatch,
                        execution_active=_pe_execution,
                    )
                )
                _participation_tier_str = _tier.value
                _participation_source = "inline_derivation_missing_device_identity"
    except Exception as _pe_exc:
        logger.debug(
            "build_v2_unified_state_contract: participation tier derivation failed: %s",
            _pe_exc,
        )
        _participation_tier_str = "local_only"
        _participation_blocking = [f"derivation_error: {_pe_exc}"]

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
        "android_network_participation_tier": _participation_tier_str,
    }

    # gateway_bridge_presence: is the Android gateway/bridge connection present and serving
    gateway_bridge_present = (
        android_attached
        and (
            device_evidence.get("android_device_count", 0) > 0
            or android_evidence.get("snapshot_count", 0) > 0
        )
    )
    gateway_bridge_degraded = gateway_bridge_present and capability_degraded

    # runtime_host_dispatch_binding: is the dispatch binding to the Android runtime active
    dispatch_bound = task_initiated and android_attached and main_chain_available
    dispatch_available = android_attached and main_chain_available and not task_initiated

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
            lifecycle_stage="observation",
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
            lifecycle_stage="observation",
        ),
        "gateway_bridge_presence": ContractDecision(
            decision_id="gateway_bridge_presence",
            label="Gateway / bridge presence",
            state=(
                "not_applicable"
                if not android_attached
                else (
                    "degraded"
                    if gateway_bridge_degraded
                    else "present" if gateway_bridge_present else "absent"
                )
            ),
            summary=(
                "Gateway/bridge presence is not applicable without Android context."
                if not android_attached
                else (
                    "Android gateway/bridge is present but reporting degraded capability."
                    if gateway_bridge_degraded
                    else (
                        "Android gateway/bridge connection is confirmed present."
                        if gateway_bridge_present
                        else "Android context exists but gateway/bridge connection is not confirmed."
                    )
                )
            ),
            sources=_base_sources(
                "core.android_device_state_store",
                "galaxy_gateway.android.handlers.capability_report",
            ),
            reasons=[
                f"android_attached={android_attached}",
                f"gateway_bridge_present={gateway_bridge_present}",
                f"gateway_bridge_degraded={gateway_bridge_degraded}",
            ],
            evidence={
                "android_device_count": device_evidence.get("android_device_count", 0),
                "snapshot_count": android_evidence.get("snapshot_count", 0),
                "capability_degraded": capability_degraded,
            },
            observable=android_attached or gateway_bridge_present,
            acceptable=not android_attached or gateway_bridge_present,
            active=gateway_bridge_present,
            lifecycle_stage="observation",
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
            lifecycle_stage="admission",
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
            lifecycle_stage="admission",
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
            lifecycle_stage="admission",
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
            lifecycle_stage="readiness",
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
            lifecycle_stage="readiness",
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
            lifecycle_stage="readiness",
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
            lifecycle_stage="readiness",
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
            lifecycle_stage="readiness",
        ),
        "participant_device_session_dependencies": ContractDecision(
            decision_id="participant_device_session_dependencies",
            label="Participant / device / session dependencies",
            state=(
                "not_applicable"
                if not android_attached
                else (
                    "satisfied"
                    if cross_device_available
                    else "partial" if capability_visible or session_evidence.get("active_session_count", 0) > 0
                    else "waiting_dependency"
                )
            ),
            summary=(
                "Participant/device/session dependencies are not applicable without Android context."
                if not android_attached
                else (
                    "All participant/device/session dependencies are satisfied."
                    if cross_device_available
                    else (
                        "Some dependencies are present but the full dependency set is not yet satisfied."
                        if capability_visible or session_evidence.get("active_session_count", 0) > 0
                        else "Participant/device/session dependencies are all still waiting."
                    )
                )
            ),
            sources=_base_sources(
                "core.android_participant_session_state",
                "core.attached_runtime_session_registry",
                "core.android_device_state_store",
            ),
            reasons=[
                f"android_attached={android_attached}",
                f"android_device_count={device_evidence.get('android_device_count', 0)}",
                f"capability_visible={capability_visible}",
                f"active_session_count={session_evidence.get('active_session_count', 0)}",
                f"participant_total_count={session_evidence.get('participant_total_count', 0)}",
            ],
            evidence={
                "android_device_count": device_evidence.get("android_device_count", 0),
                "capability_visible_count": android_evidence.get("capability_visible_count", 0),
                "active_session_count": session_evidence.get("active_session_count", 0),
                "participant_total_count": session_evidence.get("participant_total_count", 0),
                "cross_device_available": cross_device_available,
            },
            observable=android_attached,
            acceptable=not android_attached or cross_device_available,
            active=cross_device_available,
            lifecycle_stage="readiness",
        ),
        "runtime_host_dispatch_binding": ContractDecision(
            decision_id="runtime_host_dispatch_binding",
            label="Runtime host / dispatch binding",
            state=(
                "not_applicable"
                if not android_attached
                else (
                    "active"
                    if dispatch_bound
                    else "available" if dispatch_available else "unavailable"
                )
            ),
            summary=(
                "Runtime host/dispatch binding is not applicable without Android context."
                if not android_attached
                else (
                    "Dispatch binding is active — task is executing via the runtime host."
                    if dispatch_bound
                    else (
                        "Dispatch binding is available and ready to accept task assignment."
                        if dispatch_available
                        else "Dispatch binding is unavailable (main chain not ready or Android not attached)."
                    )
                )
            ),
            sources=_base_sources(
                "core.android_runtime_host",
                "core.android_runtime_dispatch_binding",
            ),
            reasons=[
                f"android_attached={android_attached}",
                f"main_chain_available={main_chain_available}",
                f"task_initiated={task_initiated}",
            ],
            evidence={
                "dispatch_bound": dispatch_bound,
                "dispatch_available": dispatch_available,
                "task_initiated": task_initiated,
            },
            observable=android_attached,
            acceptable=not android_attached or main_chain_available,
            eligible=dispatch_available or dispatch_bound,
            active=dispatch_bound,
            lifecycle_stage="eligibility",
        ),
        "android_network_participation": ContractDecision(
            decision_id="android_network_participation",
            label="Android network participation tier (PR-1)",
            state=_participation_tier_str,
            summary=(
                "Android device is a confirmed active participant in the "
                "center-distributed runtime network."
                if _participation_tier_str == "distributed_participant"
                else (
                    "Android device is eligible for dispatch to the distributed network."
                    if _participation_tier_str == "dispatch_eligible"
                    else (
                        "Android device is fully attached and structurally ready for dispatch."
                        if _participation_tier_str == "fully_attached"
                        else (
                            "Android device has cross-device execution enabled but readiness "
                            "or session conditions are not yet satisfied."
                            if _participation_tier_str == "cross_device_enabled"
                            else (
                                "Android device is registered with full attachment but "
                                "cross-device gate is off."
                                if _participation_tier_str == "cross_device_capable"
                                else (
                                    "Android device is connected but restricted to "
                                    "control-only mode."
                                    if _participation_tier_str == "control_only"
                                    else "Android device has no active connection to the "
                                    "distributed network."
                                )
                            )
                        )
                    )
                )
            ),
            sources=_base_sources(
                "core.android_network_participation",
                "core.android_device_state_store",
                "core.attached_runtime_session_registry",
                "core.android_mode_gate_policy",
            ),
            reasons=list(_participation_blocking),
            evidence={
                "tier": _participation_tier_str,
                "blocking_reasons": list(_participation_blocking),
                "derivation_notes": list(_participation_notes),
                "source": _participation_source,
                "transition_history": list(_participation_transition_history),
                "last_signal": _participation_last_signal,
                "prior_tier": _participation_prior_tier,
                "android_attached": android_attached,
                "cross_device_available": cross_device_available,
                "capability_visible": capability_visible,
                "active_session_count": session_evidence.get("active_session_count", 0),
            },
            observable=android_attached,
            acceptable=_participation_tier_str in {
                "fully_attached", "dispatch_eligible", "distributed_participant"
            },
            eligible=_participation_tier_str in {"dispatch_eligible", "distributed_participant"},
            active=_participation_tier_str == "distributed_participant",
            lifecycle_stage="observation",
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
            lifecycle_stage="admission",
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
            lifecycle_stage="admission",
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
            lifecycle_stage="eligibility",
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

    closure_quality_state = {
        "task_execution_visibility": ContractDecision(
            decision_id="task_execution_visibility",
            label="Task execution visibility",
            state=(
                "not_applicable"
                if not android_attached
                else (
                    "complete"
                    if result_closure_established
                    else "active" if task_initiated else "idle"
                )
            ),
            summary=(
                "Task execution visibility is not applicable without Android context."
                if not android_attached
                else (
                    "Task execution is complete — result closure has been established."
                    if result_closure_established
                    else (
                        "Task execution is currently active."
                        if task_initiated
                        else "No task execution is currently active."
                    )
                )
            ),
            sources=_base_sources(
                "core.android_participant_session_state",
                "core.unified_result_ingress",
                "core.attached_runtime_session_registry",
            ),
            reasons=[
                f"task_initiated={task_initiated}",
                f"result_closure_established={result_closure_established}",
                f"active_session_count={session_evidence.get('active_session_count', 0)}",
            ],
            evidence={
                "task_initiated": task_initiated,
                "result_closure_established": result_closure_established,
                "active_session_count": session_evidence.get("active_session_count", 0),
                "participant_total_count": session_evidence.get("participant_total_count", 0),
            },
            observable=task_initiated or result_closure_established,
            active=task_initiated and not result_closure_established,
            complete=result_closure_established,
            lifecycle_stage="execution",
        ),
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
            lifecycle_stage="closure",
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
            lifecycle_stage="closure",
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
            lifecycle_stage="closure",
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
            lifecycle_stage="conditions",
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
            lifecycle_stage="conditions",
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
            lifecycle_stage="conditions",
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
            "(validation_status=%s, android_device_count=%s, runtime_verdict=%s). "
            "Contract will include error stub in lifecycle_hardening field; "
            "the rest of the contract remains usable but lifecycle gating is unavailable.",
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
