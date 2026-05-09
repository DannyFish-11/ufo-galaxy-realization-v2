"""core/unified_governance_semantics.py
========================================
Unified governance semantics between V2 authority and Android autonomy.

This module defines one stable contract that expresses:

1. Android autonomy scope differences between local vs cross-device mode.
2. Unified authority precedence across local planning, local grounding,
   local execution, delegated execution, takeover, and multimodal participation.
3. A panel/operator-consumable governance state snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import importlib
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

UNIFIED_GOVERNANCE_SEMANTICS_AUTHORITY: str = (
    "UNIFIED_GOVERNANCE_SEMANTICS_V1: "
    "core.unified_governance_semantics is the canonical governance contract for "
    "V2 authority vs Android autonomy across local/cross-device mode and "
    "execution participation precedence."
)

UNIFIED_GOVERNANCE_SEMANTICS_CONTRACT_VERSION: str = "1.0.0"
MESH_RUNTIME_STATUS_POLICY: str = (
    "MESH_RUNTIME_STATUS_POLICY_V1: "
    "multi-device mesh runtime status must be surfaced as explicit "
    "partial/runtime/deferred facts instead of implicit structural claims."
)
MESH_RUNTIME_STATUS_RUNTIME_PROVEN: str = "runtime_proven"
MESH_RUNTIME_STATUS_PARTIAL: str = "partial"
MESH_RUNTIME_STATUS_CONTRACT_ONLY: str = "contract_only"
MESH_RUNTIME_STATUS_UNAVAILABLE: str = "unavailable"


class GovernancePath(str, Enum):
    local_planning = "local_planning"
    local_grounding = "local_grounding"
    local_execution = "local_execution"
    delegated_execution = "delegated_execution"
    takeover = "takeover"
    multimodal_participation = "multimodal_participation"


@dataclass
class GovernancePathDecision:
    path: GovernancePath
    precedence_rank: int
    authority_owner: str
    android_scope: str
    eligible: bool
    blocked_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path.value,
            "precedence_rank": self.precedence_rank,
            "authority_owner": self.authority_owner,
            "android_scope": self.android_scope,
            "eligible": self.eligible,
            "blocked_by": self.blocked_by,
        }


def _autonomy_scope_for_mode(mode: str) -> str:
    if mode == "local":
        return "local_autonomy"
    if mode == "cross_device":
        return "subordinate_participation"
    if mode == "transitioning":
        return "transition_limited"
    return "unknown"


def _rank_for_path(path: GovernancePath) -> int:
    rank_map = {
        GovernancePath.takeover: 1,
        GovernancePath.delegated_execution: 2,
        GovernancePath.local_execution: 3,
        GovernancePath.local_grounding: 4,
        GovernancePath.local_planning: 5,
        GovernancePath.multimodal_participation: 6,
    }
    return rank_map[path]


def _snapshot_continuity_state(
    *,
    status: Optional[str],
    conflict: bool,
) -> str:
    """Classify reconciliation facts into a stable continuity state bucket."""
    normalized_status = str(status or "").strip().lower()
    if conflict or normalized_status == "conflict_center_truth_retained":
        return "conflict_retained"
    if normalized_status in {
        "stale_rejected",
        "out_of_order_rejected",
        "reconnect_delayed_rejected",
        "duplicate_ignored",
    }:
        return "rejected"
    if normalized_status == "accepted":
        return "accepted"
    return "unavailable"


def _has_sentinel(module_path: str, sentinel_name: str) -> bool:
    """Return True when a sentinel constant can be imported and is truthy."""
    try:
        module = importlib.import_module(module_path)
        return bool(getattr(module, sentinel_name, None))
    except (ImportError, AttributeError) as exc:
        logger.debug("_has_sentinel: unavailable %s.%s: %s", module_path, sentinel_name, exc)
        return False


def build_mesh_runtime_state(
    coordinator_state: Any = None,
) -> Dict[str, Any]:
    """Build a compact operator/panel-safe mesh runtime status snapshot.

    This snapshot distinguishes what is runtime-proven in the V2 codebase from
    what still depends on Android-side authority/runtime closure.

    As of PR-03, this function also integrates the center-side mesh runtime
    state machine (via :mod:`core.mesh.mesh_runtime_center_state`) so that the
    snapshot expresses a real center-side runtime contract rather than only a
    sentinel-presence projection.

    Parameters
    ----------
    coordinator_state:
        Optional coordinator state to pass to the center state machine for
        real state derivation.  If ``None``, falls back to sentinel-based
        presence checks.
    """
    has_staged_mesh_dispatch = _has_sentinel(
        "core.runtime.source_dispatch_orchestrator",
        "LIVE_MESH_RUNTIME_ENGINE_ORCHESTRATOR_PR_J_SENTINEL",
    )
    has_live_mesh_engine = _has_sentinel(
        "core.mesh.live_mesh_runtime_engine",
        "LIVE_MESH_RUNTIME_ENGINE_PR_J_SENTINEL",
    )
    has_live_mesh_coordinator = _has_sentinel(
        "core.mesh.live_mesh_session_coordinator",
        "LIVE_MESH_SESSION_COORDINATOR_PR_J_SENTINEL",
    )
    has_center_state_machine = _has_sentinel(
        "core.mesh.mesh_runtime_center_state",
        "MESH_RUNTIME_CENTER_STATE_PR03_SENTINEL",
    )
    recoverable_mesh_sessions = 0
    live_runtime_proof_snapshot: Dict[str, Any] = {}
    live_runtime_dispatch_count = 0
    live_runtime_run_count = 0

    try:
        from core.mesh.mesh_session_persistence import recover_mesh_sessions

        recoverable_mesh_sessions = len(recover_mesh_sessions())
    except Exception as exc:
        logger.debug("build_mesh_runtime_state: recoverable mesh sessions unavailable: %s", exc)
        recoverable_mesh_sessions = 0

    try:
        from core.runtime.source_dispatch_orchestrator import (
            get_live_mesh_runtime_proof_snapshot,
        )

        live_runtime_proof_snapshot = get_live_mesh_runtime_proof_snapshot()
    except Exception as exc:
        logger.debug("build_mesh_runtime_state: live runtime proof snapshot unavailable: %s", exc)
        live_runtime_proof_snapshot = {}

    live_runtime_dispatch_count = int(
        live_runtime_proof_snapshot.get("staged_mesh_dispatch_count", 0) or 0
    )
    live_runtime_run_count = int(
        live_runtime_proof_snapshot.get("live_mesh_run_count", 0) or 0
    )
    has_live_runtime_path_execution = live_runtime_run_count > 0

    runtime_proof_count = sum(
        (
            int(has_staged_mesh_dispatch),
            int(has_live_mesh_engine),
            int(has_live_mesh_coordinator),
            int(has_center_state_machine),
            int(has_live_runtime_path_execution),
        )
    )
    if has_live_runtime_path_execution:
        status = MESH_RUNTIME_STATUS_RUNTIME_PROVEN
    elif runtime_proof_count > 0:
        status = MESH_RUNTIME_STATUS_PARTIAL
    else:
        status = MESH_RUNTIME_STATUS_CONTRACT_ONLY

    # Build center-side state machine snapshot (PR-03)
    center_state_snapshot: Dict[str, Any] = {}
    try:
        from core.mesh.mesh_runtime_center_state import build_mesh_runtime_center_state

        center_state_snapshot = build_mesh_runtime_center_state(coordinator_state)
    except Exception as exc:
        logger.debug("build_mesh_runtime_state: center state machine unavailable: %s", exc)
        center_state_snapshot = {
            "status": MESH_RUNTIME_STATUS_UNAVAILABLE,
            "errors": [f"center_state_machine_unavailable:{exc}"],
        }

    return {
        "status": status,
        "runtime_proof_count": runtime_proof_count,
        "runtime_proofs": {
            "staged_mesh_dispatch_orchestration": has_staged_mesh_dispatch,
            "live_mesh_runtime_engine": has_live_mesh_engine,
            "live_mesh_session_coordinator": has_live_mesh_coordinator,
            "mesh_runtime_center_state_machine": has_center_state_machine,
            "live_mesh_runtime_path_execution": has_live_runtime_path_execution,
        },
        "runtime_observability": {
            "recoverable_mesh_session_count": recoverable_mesh_sessions,
            "live_mesh_runtime_proof": {
                "staged_mesh_dispatch_count": live_runtime_dispatch_count,
                "live_mesh_run_count": live_runtime_run_count,
                "live_mesh_completed_count": int(
                    live_runtime_proof_snapshot.get("live_mesh_completed_count", 0) or 0
                ),
                "live_mesh_partial_count": int(
                    live_runtime_proof_snapshot.get("live_mesh_partial_count", 0) or 0
                ),
                "live_mesh_failed_count": int(
                    live_runtime_proof_snapshot.get("live_mesh_failed_count", 0) or 0
                ),
                "last_live_outcome": live_runtime_proof_snapshot.get("last_live_outcome"),
                "last_mesh_session_id": live_runtime_proof_snapshot.get("last_mesh_session_id"),
            },
        },
        "center_runtime_state": center_state_snapshot,
        "runtime_relationships": [
            {
                "link": "dispatch_to_delegation",
                "source": "SourceDispatchOrchestrator(staged_mesh)",
                "target": "Android delegated execution(goal_execution/parallel_subtask)",
                "status": "v2_dispatch_proven_android_execution_external",
            },
            {
                "link": "delegation_to_parallel_subtask",
                "source": "delegated execution envelope",
                "target": "parallel_subtask handling path",
                "status": "message_path_proven",
            },
            {
                "link": "parallel_subtask_to_local_collaboration_agent",
                "source": "parallel_subtask",
                "target": "Android LocalCollaborationAgent",
                "status": "android_repo_authority_external_to_v2_runtime",
            },
        ],
        "deferred_or_constrained": [
            "cross-repo authority contract closure (V2<->Android) remains required",
            "multi-Android-device live mesh closure remains constrained without Android-side runtime proof",
        ],
        "_policy": MESH_RUNTIME_STATUS_POLICY,
        "_source": UNIFIED_GOVERNANCE_SEMANTICS_AUTHORITY,
    }


def resolve_governance_path_decision(
    *,
    mode: str,
    path: GovernancePath,
    dispatch_eligible: bool,
    takeover_eligible: bool,
    takeover_active: bool,
    highest_priority_execution_type: Optional[str] = None,
    blocked_execution_types: Optional[List[str]] = None,
    canonical_execution_gate_decision: str = "allow",
) -> GovernancePathDecision:
    _blocked_execution_types: List[str] = []
    for value in blocked_execution_types or []:
        normalized_value = str(value).strip()
        if normalized_value:
            _blocked_execution_types.append(normalized_value)
    blocked_execution_types = _blocked_execution_types
    highest_priority_execution_type = str(highest_priority_execution_type or "").strip()
    canonical_execution_gate_decision = str(canonical_execution_gate_decision or "allow").strip().lower()
    if takeover_active and path != GovernancePath.takeover:
        return GovernancePathDecision(
            path=path,
            precedence_rank=_rank_for_path(path),
            authority_owner="v2_authority",
            android_scope="blocked_by_takeover",
            eligible=False,
            blocked_by="takeover",
        )

    if mode == "local":
        if path in (
            GovernancePath.local_planning,
            GovernancePath.local_grounding,
            GovernancePath.local_execution,
        ):
            return GovernancePathDecision(
                path=path,
                precedence_rank=_rank_for_path(path),
                authority_owner="android_local_autonomy",
                android_scope="autonomous",
                eligible=True,
            )
        if path == GovernancePath.multimodal_participation:
            return GovernancePathDecision(
                path=path,
                precedence_rank=_rank_for_path(path),
                authority_owner="v2_authority",
                android_scope="participatory_signal",
                eligible=True,
            )
        return GovernancePathDecision(
            path=path,
            precedence_rank=_rank_for_path(path),
            authority_owner="v2_authority",
            android_scope="not_allowed_in_local_mode",
            eligible=False,
            blocked_by="local_mode_boundary",
        )

    if mode == "cross_device":
        if path == GovernancePath.takeover:
            return GovernancePathDecision(
                path=path,
                precedence_rank=_rank_for_path(path),
                authority_owner="v2_authority",
                android_scope="subordinate_target",
                eligible=bool(takeover_eligible),
                blocked_by=None if takeover_eligible else "takeover_gate",
            )
        if path == GovernancePath.delegated_execution:
            if "goal_execution" in blocked_execution_types:
                return GovernancePathDecision(
                    path=path,
                    precedence_rank=_rank_for_path(path),
                    authority_owner="v2_authority",
                    android_scope="blocked_by_execution_runtime",
                    eligible=False,
                    blocked_by="execution_runtime_blocked:goal_execution",
                )
            if canonical_execution_gate_decision == "defer":
                return GovernancePathDecision(
                    path=path,
                    precedence_rank=_rank_for_path(path),
                    authority_owner="v2_authority",
                    android_scope="deferred_by_canonical_execution_gate",
                    eligible=False,
                    blocked_by="canonical_execution_gate:defer",
                )
            if canonical_execution_gate_decision == "deny":
                return GovernancePathDecision(
                    path=path,
                    precedence_rank=_rank_for_path(path),
                    authority_owner="v2_authority",
                    android_scope="blocked_by_canonical_execution_gate",
                    eligible=False,
                    blocked_by="canonical_execution_gate:deny",
                )
            return GovernancePathDecision(
                path=path,
                precedence_rank=_rank_for_path(path),
                authority_owner="v2_authority",
                android_scope="subordinate_executor",
                eligible=bool(dispatch_eligible),
                blocked_by=None if dispatch_eligible else "dispatch_gate",
            )
        if path in (
            GovernancePath.local_planning,
            GovernancePath.local_grounding,
            GovernancePath.local_execution,
        ):
            if highest_priority_execution_type == "takeover_request":
                return GovernancePathDecision(
                    path=path,
                    precedence_rank=_rank_for_path(path),
                    authority_owner="v2_authority",
                    android_scope="blocked_by_takeover_runtime_priority",
                    eligible=False,
                    blocked_by="execution_runtime_priority:takeover_request",
                )
            return GovernancePathDecision(
                path=path,
                precedence_rank=_rank_for_path(path),
                authority_owner="v2_authority",
                android_scope="bounded_local_participation",
                eligible=True,
            )
        return GovernancePathDecision(
            path=path,
            precedence_rank=_rank_for_path(path),
            authority_owner="v2_authority",
            android_scope="participatory_signal",
            eligible=True,
        )

    return GovernancePathDecision(
        path=path,
        precedence_rank=_rank_for_path(path),
        authority_owner="v2_authority",
        android_scope="unknown_mode",
        eligible=False,
        blocked_by="unknown_mode",
    )


def build_unified_governance_state(
    device_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    try:
        from core.attached_runtime_session_registry import list_active_sessions
        from core.android_mode_gate_policy import (
            build_mode_state_for_device,
            evaluate_android_mode_readiness,
            resolve_android_execution_gate_decision,
        )
        from core.unified_execution_governance import (
            get_execution_runtime_snapshot,
            is_takeover_active,
        )
    except Exception:
        return {
            "devices": [],
            "local_mode_count": 0,
            "cross_device_mode_count": 0,
            "takeover_active_count": 0,
            "execution_runtime_state": {
                "devices": [],
                "active_device_count": 0,
                "active_execution_total_count": 0,
                "_source": UNIFIED_GOVERNANCE_SEMANTICS_AUTHORITY,
            },
            "mesh_runtime_state": {
                "status": MESH_RUNTIME_STATUS_UNAVAILABLE,
                "runtime_proof_count": 0,
                "runtime_relationships": [],
                "deferred_or_constrained": ["governance dependencies unavailable"],
                "_policy": MESH_RUNTIME_STATUS_POLICY,
                "_source": UNIFIED_GOVERNANCE_SEMANTICS_AUTHORITY,
            },
            "_source": UNIFIED_GOVERNANCE_SEMANTICS_AUTHORITY,
            "_contract_version": UNIFIED_GOVERNANCE_SEMANTICS_CONTRACT_VERSION,
        }

    if device_ids is None:
        try:
            device_ids = [e.device_id for e in list_active_sessions()]
        except Exception:
            device_ids = []
    # Deduplicate while preserving the previously collected session order.
    device_ids = list(dict.fromkeys(device_ids or []))
    execution_runtime_state = get_execution_runtime_snapshot(device_ids=device_ids)
    runtime_by_device = {
        entry["device_id"]: entry
        for entry in execution_runtime_state.get("devices", [])
        if isinstance(entry.get("device_id"), str) and entry.get("device_id")
    }

    devices: List[Dict[str, Any]] = []
    local_mode_count = 0
    cross_device_mode_count = 0
    takeover_active_count = 0

    for device_id in list(device_ids):
        try:
            mode_state = build_mode_state_for_device(device_id)
            readiness = evaluate_android_mode_readiness(device_id)
            takeover_active = is_takeover_active(device_id)
        except Exception:
            continue

        mode = getattr(mode_state.mode, "value", str(mode_state.mode))
        dispatch_eligible = bool(getattr(readiness, "is_dispatch_eligible", False))
        takeover_eligible = bool(getattr(readiness, "is_takeover_eligible", False))
        runtime_state_for_device = dict(runtime_by_device.get(device_id, {}))
        canonical_gate = resolve_android_execution_gate_decision(
            policy_eligible=dispatch_eligible,
            readiness_ready=bool(getattr(readiness, "is_cross_device_ready", False)),
            execution_busy=bool(runtime_state_for_device.get("execution_busy", False)),
            local_inference_available=bool(
                runtime_state_for_device.get("local_inference_available", False)
            ),
            fallback_tier=runtime_state_for_device.get("current_fallback_tier"),
        )
        if mode == "local":
            local_mode_count += 1
        elif mode == "cross_device":
            cross_device_mode_count += 1

        if takeover_active:
            takeover_active_count += 1

        paths: Dict[str, Dict[str, Any]] = {}
        for path in GovernancePath:
            decision = resolve_governance_path_decision(
                mode=mode,
                path=path,
                dispatch_eligible=dispatch_eligible,
                takeover_eligible=takeover_eligible,
                takeover_active=takeover_active,
                highest_priority_execution_type=runtime_state_for_device.get(
                    "highest_priority_execution_type"
                ),
                blocked_execution_types=list(
                    runtime_state_for_device.get("blocked_execution_types", [])
                ),
                canonical_execution_gate_decision=canonical_gate.decision,
            )
            decision_dict = decision.to_dict()
            decision_dict["decision_causality"] = {
                "mode": mode,
                "dispatch_eligible": dispatch_eligible,
                "takeover_eligible": takeover_eligible,
                "takeover_active": takeover_active,
                "active_execution_count": int(
                    runtime_state_for_device.get("active_execution_count", 0)
                ),
                "highest_priority_execution_type": runtime_state_for_device.get(
                    "highest_priority_execution_type"
                ),
                "blocked_execution_types": list(
                    runtime_state_for_device.get("blocked_execution_types", [])
                ),
                "offline_queue_depth": int(
                    runtime_state_for_device.get("offline_queue_depth", 0) or 0
                ),
                "execution_busy": bool(
                    runtime_state_for_device.get("execution_busy", False)
                ),
                "local_inference_available": bool(
                    runtime_state_for_device.get("local_inference_available", False)
                ),
                "android_reported_mode": runtime_state_for_device.get(
                    "android_reported_mode"
                ),
                "android_reported_mode_state": runtime_state_for_device.get(
                    "android_reported_mode_state"
                ),
                "android_reported_mode_readiness_state": runtime_state_for_device.get(
                    "android_reported_mode_readiness_state"
                ),
                "android_reported_cross_device_eligibility": runtime_state_for_device.get(
                    "android_reported_cross_device_eligibility"
                ),
                "android_reported_goal_execution_eligibility": runtime_state_for_device.get(
                    "android_reported_goal_execution_eligibility"
                ),
                "android_reported_parallel_execution_eligibility": runtime_state_for_device.get(
                    "android_reported_parallel_execution_eligibility"
                ),
                "android_reported_local_intelligence_status": runtime_state_for_device.get(
                    "android_reported_local_intelligence_status"
                ),
                "android_reported_local_inference_ready": runtime_state_for_device.get(
                    "android_reported_local_inference_ready"
                ),
                "android_reported_local_inference_available": runtime_state_for_device.get(
                    "android_reported_local_inference_available"
                ),
                "android_semantics_contract_state": runtime_state_for_device.get(
                    "android_semantics_contract_state"
                ),
                "android_semantics_contract_complete": bool(
                    runtime_state_for_device.get("android_semantics_contract_complete", False)
                ),
                "android_semantics_missing_keys": list(
                    runtime_state_for_device.get("android_semantics_missing_keys", [])
                ),
                "android_semantics_malformed_keys": list(
                    runtime_state_for_device.get("android_semantics_malformed_keys", [])
                ),
                "android_semantics_absorbed_at": float(
                    runtime_state_for_device.get("android_semantics_absorbed_at", 0.0)
                ),
                "android_semantics_reported_at": (
                    float(runtime_state_for_device.get("android_semantics_reported_at"))
                    if runtime_state_for_device.get("android_semantics_reported_at") is not None
                    else None
                ),
                "android_semantics_age_s": (
                    float(runtime_state_for_device.get("android_semantics_age_s"))
                    if runtime_state_for_device.get("android_semantics_age_s") is not None
                    else None
                ),
                "android_semantics_freshness_threshold_s": float(
                    runtime_state_for_device.get("android_semantics_freshness_threshold_s", 0.0)
                    or 0.0
                ),
                "android_semantics_freshness_state": runtime_state_for_device.get(
                    "android_semantics_freshness_state"
                ),
                "android_semantics_freshness_reason": runtime_state_for_device.get(
                    "android_semantics_freshness_reason"
                ),
                "android_runtime_truth_authority": runtime_state_for_device.get(
                    "android_runtime_truth_authority"
                ),
                "android_runtime_truth_usable": bool(
                    runtime_state_for_device.get("android_runtime_truth_usable", False)
                ),
                "runtime_health_status": runtime_state_for_device.get(
                    "runtime_health_status"
                ),
                "current_fallback_tier": runtime_state_for_device.get(
                    "current_fallback_tier"
                ),
                "canonical_execution_gate_decision": canonical_gate.decision,
                "canonical_execution_gate_reasons": list(canonical_gate.reasons),
                "capability_ready": canonical_gate.capability_ready,
                "snapshot_reconciliation_status": runtime_state_for_device.get(
                    "snapshot_reconciliation_status"
                ),
                "snapshot_reconciliation_reason": runtime_state_for_device.get(
                    "snapshot_reconciliation_reason"
                ),
                "snapshot_conflict": bool(
                    runtime_state_for_device.get("snapshot_conflict", False)
                ),
                "snapshot_ordering_basis": runtime_state_for_device.get(
                    "snapshot_ordering_basis"
                ),
                "snapshot_last_updated_at": float(
                    runtime_state_for_device.get("snapshot_last_updated_at", 0.0) or 0.0
                ),
                "snapshot_reconciliation_applied": bool(
                    runtime_state_for_device.get("snapshot_reconciliation_applied", False)
                ),
                "snapshot_continuity_state": _snapshot_continuity_state(
                    status=runtime_state_for_device.get("snapshot_reconciliation_status"),
                    conflict=bool(runtime_state_for_device.get("snapshot_conflict", False)),
                ),
                "latest_execution_event_phase": runtime_state_for_device.get(
                    "latest_execution_event_phase"
                ),
                "latest_execution_event_absorbed_at": float(
                    runtime_state_for_device.get("latest_execution_event_absorbed_at", 0.0)
                    or 0.0
                ),
                "latest_execution_event_age_s": (
                    float(runtime_state_for_device.get("latest_execution_event_age_s"))
                    if runtime_state_for_device.get("latest_execution_event_age_s") is not None
                    else None
                ),
                "execution_busy_window_seconds": float(
                    runtime_state_for_device.get("execution_busy_window_seconds", 60.0)
                    or 60.0
                ),
            }
            paths[path.value] = decision_dict

        devices.append(
            {
                "device_id": device_id,
                "mode": mode,
                "android_autonomy_scope": _autonomy_scope_for_mode(mode),
                "dispatch_eligible": dispatch_eligible,
                "takeover_eligible": takeover_eligible,
                "takeover_active": takeover_active,
                "runtime_execution_state": runtime_state_for_device,
                "governance_precedence": paths,
                "_source": UNIFIED_GOVERNANCE_SEMANTICS_AUTHORITY,
            }
        )

    return {
        "devices": devices,
        "local_mode_count": local_mode_count,
        "cross_device_mode_count": cross_device_mode_count,
        "takeover_active_count": takeover_active_count,
        "execution_runtime_state": execution_runtime_state,
        "mesh_runtime_state": build_mesh_runtime_state(),
        "authority": "v2_semantic_orchestration_authority",
        "_source": UNIFIED_GOVERNANCE_SEMANTICS_AUTHORITY,
        "_contract_version": UNIFIED_GOVERNANCE_SEMANTICS_CONTRACT_VERSION,
    }


__all__ = [
    "UNIFIED_GOVERNANCE_SEMANTICS_AUTHORITY",
    "UNIFIED_GOVERNANCE_SEMANTICS_CONTRACT_VERSION",
    "GovernancePath",
    "GovernancePathDecision",
    "MESH_RUNTIME_STATUS_POLICY",
    "MESH_RUNTIME_STATUS_RUNTIME_PROVEN",
    "MESH_RUNTIME_STATUS_PARTIAL",
    "MESH_RUNTIME_STATUS_CONTRACT_ONLY",
    "MESH_RUNTIME_STATUS_UNAVAILABLE",
    "build_mesh_runtime_state",
    "resolve_governance_path_decision",
    "build_unified_governance_state",
]
