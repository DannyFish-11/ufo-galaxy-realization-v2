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


def _has_sentinel(module_path: str, sentinel_name: str) -> bool:
    """Return True when a sentinel constant can be imported and is truthy."""
    try:
        module = importlib.import_module(module_path)
        return bool(getattr(module, sentinel_name, None))
    except (ImportError, AttributeError) as exc:
        logger.debug("_has_sentinel: unavailable %s.%s: %s", module_path, sentinel_name, exc)
        return False


def build_mesh_runtime_state() -> Dict[str, Any]:
    """Build a compact operator/panel-safe mesh runtime status snapshot.

    This snapshot intentionally distinguishes what is runtime-proven in the
    V2 codebase from what still depends on Android-side authority/runtime
    closure.
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
    recoverable_mesh_sessions = 0

    try:
        from core.mesh.mesh_session_persistence import recover_mesh_sessions

        recoverable_mesh_sessions = len(recover_mesh_sessions())
    except Exception as exc:
        logger.debug("build_mesh_runtime_state: recoverable mesh sessions unavailable: %s", exc)
        recoverable_mesh_sessions = 0

    runtime_proof_count = sum(
        (
            int(has_staged_mesh_dispatch),
            int(has_live_mesh_engine),
            int(has_live_mesh_coordinator),
        )
    )
    status = (
        MESH_RUNTIME_STATUS_PARTIAL
        if runtime_proof_count > 0
        else MESH_RUNTIME_STATUS_CONTRACT_ONLY
    )

    return {
        "status": status,
        "runtime_proof_count": runtime_proof_count,
        "runtime_proofs": {
            "staged_mesh_dispatch_orchestration": has_staged_mesh_dispatch,
            "live_mesh_runtime_engine": has_live_mesh_engine,
            "live_mesh_session_coordinator": has_live_mesh_coordinator,
        },
        "runtime_observability": {
            "recoverable_mesh_session_count": recoverable_mesh_sessions,
        },
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
) -> GovernancePathDecision:
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
        )
        from core.unified_execution_governance import is_takeover_active
    except Exception:
        return {
            "devices": [],
            "local_mode_count": 0,
            "cross_device_mode_count": 0,
            "takeover_active_count": 0,
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
                dispatch_eligible=bool(getattr(readiness, "is_dispatch_eligible", False)),
                takeover_eligible=bool(getattr(readiness, "is_takeover_eligible", False)),
                takeover_active=takeover_active,
            )
            paths[path.value] = decision.to_dict()

        devices.append(
            {
                "device_id": device_id,
                "mode": mode,
                "android_autonomy_scope": _autonomy_scope_for_mode(mode),
                "dispatch_eligible": bool(getattr(readiness, "is_dispatch_eligible", False)),
                "takeover_eligible": bool(getattr(readiness, "is_takeover_eligible", False)),
                "takeover_active": takeover_active,
                "governance_precedence": paths,
                "_source": UNIFIED_GOVERNANCE_SEMANTICS_AUTHORITY,
            }
        )

    return {
        "devices": devices,
        "local_mode_count": local_mode_count,
        "cross_device_mode_count": cross_device_mode_count,
        "takeover_active_count": takeover_active_count,
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
    "MESH_RUNTIME_STATUS_PARTIAL",
    "MESH_RUNTIME_STATUS_CONTRACT_ONLY",
    "MESH_RUNTIME_STATUS_UNAVAILABLE",
    "build_mesh_runtime_state",
    "resolve_governance_path_decision",
    "build_unified_governance_state",
]
