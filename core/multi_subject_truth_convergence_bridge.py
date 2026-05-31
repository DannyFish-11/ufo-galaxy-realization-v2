#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/multi_subject_truth_convergence_bridge.py
==============================================

Minimal canonical governance bridge for multi-subject cross-device execution.

This module converts formation/readiness/participation/result signals into a
single participant-governance snapshot that dispatch/coordination paths can
attach to result payloads and canonical result surfaces.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

MULTI_SUBJECT_TRUTH_CONVERGENCE_BRIDGE_AUTHORITY = (
    "MULTI_SUBJECT_TRUTH_CONVERGENCE_BRIDGE::CANONICAL_GOVERNANCE_V1: "
    "Bridges formation/readiness/participation/result signals into a unified "
    "participant role + failure isolation + closure snapshot."
)

_LOSS_TOKENS = ("offline", "lost", "disconnect", "unreachable", "not connected")
_DEGRADED_TOKENS = ("degraded", "busy", "timeout", "retry")

try:
    from contracts.participant_lifecycle_schema import (
        ParticipantLifecycleState as _PLS,
        ParticipantRole as _PR,
        ParticipantTransitionTrigger as _PTT,
        PARTICIPANT_STATE_TRANSITIONS as _PL_TRANSITIONS,
    )
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _PLS = None
    _PR = None
    _PTT = None
    _PL_TRANSITIONS = []


def _enum_value(value: Any, fallback: str = "") -> str:
    return str(getattr(value, "value", value) or fallback)


ROLE_PRIMARY = _enum_value(getattr(_PR, "PRIMARY", None), "primary")
ROLE_ASSISTANT = _enum_value(getattr(_PR, "ASSISTANT", None), "assistant")
ROLE_FALLBACK = _enum_value(getattr(_PR, "FALLBACK", None), "fallback")
ROLE_SUSPENDED = _enum_value(getattr(_PR, "SUSPENDED", None), "suspended")
ROLE_TAKEOVER_CANDIDATE = _enum_value(
    getattr(_PR, "TAKEOVER_CANDIDATE", None), "takeover_candidate"
)
ROLE_DEGRADED = _enum_value(getattr(_PR, "DEGRADED", None), "degraded")

STATE_ATTACHED = _enum_value(getattr(_PLS, "ATTACHED", None), "attached")
STATE_EXECUTING = _enum_value(getattr(_PLS, "EXECUTING", None), "executing")
STATE_RESULT_ACCEPTED = _enum_value(
    getattr(_PLS, "RESULT_ACCEPTED", None), "result_accepted"
)
STATE_SUSPENDED = _enum_value(
    getattr(_PLS, "SUSPENDED_STATE", None), "suspended_state"
)
STATE_TAKEOVER_CANDIDATE = _enum_value(
    getattr(_PLS, "TAKEOVER_CANDIDATE_STATE", None), "takeover_candidate_state"
)
STATE_DEGRADED = _enum_value(getattr(_PLS, "DEGRADED_STATE", None), "degraded_state")
STATE_RECOVERING = _enum_value(getattr(_PLS, "RECOVERING", None), "recovering")
STATE_DETACHED = _enum_value(getattr(_PLS, "DETACHED", None), "detached")
STATE_TERMINAL = _enum_value(getattr(_PLS, "TERMINAL", None), "terminal")
STATE_WAITING_RESULT = _enum_value(
    getattr(_PLS, "WAITING_RESULT", None), "waiting_result"
)

TR_ATTACH_SUCCESS = _enum_value(getattr(_PTT, "ATTACH_SUCCESS", None), "attach_success")
TR_EXECUTION_STARTED = _enum_value(
    getattr(_PTT, "EXECUTION_STARTED", None), "execution_started"
)
TR_RESULT_ACCEPTED = _enum_value(
    getattr(_PTT, "RESULT_ACCEPTED_BY_CENTER", None),
    "result_accepted_by_center",
)
TR_SUSPENSION_ORDERED = _enum_value(
    getattr(_PTT, "SUSPENSION_ORDERED", None), "suspension_ordered"
)
TR_TAKEOVER_NOMINATED = _enum_value(
    getattr(_PTT, "TAKEOVER_CANDIDATE_NOMINATED", None),
    "takeover_candidate_nominated",
)
TR_CAPABILITY_DEGRADED = _enum_value(
    getattr(_PTT, "CAPABILITY_DEGRADED", None), "capability_degraded"
)
TR_RECOVERY_COMPLETED = _enum_value(
    getattr(_PTT, "RECOVERY_COMPLETED", None), "recovery_completed"
)
TR_RECOVERY_INITIATED = _enum_value(
    getattr(_PTT, "RECOVERY_INITIATED", None), "recovery_initiated"
)
TR_TRANSPORT_DISCONNECTED = _enum_value(
    getattr(_PTT, "TRANSPORT_DISCONNECTED", None), "transport_disconnected"
)
TR_TERMINAL_LOSS = _enum_value(getattr(_PTT, "TERMINAL_LOSS", None), "terminal_loss")


def _find_transition_implications(
    *,
    from_state: str,
    to_state: str,
    trigger: str,
) -> Dict[str, str]:
    for transition in _PL_TRANSITIONS:
        if (
            _enum_value(getattr(transition, "from_state", None)) == from_state
            and _enum_value(getattr(transition, "to_state", None)) == to_state
            and _enum_value(getattr(transition, "trigger", None)) == trigger
        ):
            return {
                "truth_implication": str(
                    getattr(transition, "truth_implication", "") or ""
                ),
                "closure_implication": str(
                    getattr(transition, "closure_implication", "") or ""
                ),
            }
    return {"truth_implication": "", "closure_implication": ""}


def _build_lifecycle_projection(
    *,
    role: str,
    state: str,
    signal: Dict[str, Any],
    has_result: bool,
    result_success: bool,
    is_recovery: bool,
) -> Dict[str, Any]:
    from_state = STATE_ATTACHED
    lifecycle_state = STATE_ATTACHED
    trigger = TR_ATTACH_SUCCESS
    dispatch_eligible = True
    dispatch_reason = "participant_attached"

    if role == ROLE_SUSPENDED or state == "suspended":
        lifecycle_state = STATE_SUSPENDED
        trigger = TR_SUSPENSION_ORDERED
        dispatch_eligible = False
        dispatch_reason = "participant_suspended"
    elif state == "lost":
        from_state = STATE_EXECUTING if bool(signal.get("busy", False)) else STATE_ATTACHED
        lifecycle_state = STATE_DETACHED
        trigger = TR_TRANSPORT_DISCONNECTED
        dispatch_eligible = False
        dispatch_reason = "participant_lost"
    elif state == "failed":
        from_state = STATE_RECOVERING
        lifecycle_state = STATE_TERMINAL
        trigger = TR_TERMINAL_LOSS
        dispatch_eligible = False
        dispatch_reason = "participant_terminal_loss"
    elif state == "degraded":
        from_state = STATE_EXECUTING
        lifecycle_state = STATE_DEGRADED
        trigger = TR_CAPABILITY_DEGRADED
        dispatch_reason = "participant_degraded"
    elif is_recovery and state in {"ready", "degraded"} and result_success:
        from_state = STATE_RECOVERING
        lifecycle_state = STATE_ATTACHED
        trigger = TR_RECOVERY_COMPLETED
        dispatch_reason = "participant_recovery_completed"
    elif is_recovery and state in {"ready", "degraded"}:
        from_state = STATE_DETACHED
        lifecycle_state = STATE_RECOVERING
        trigger = TR_RECOVERY_INITIATED
        dispatch_eligible = False
        dispatch_reason = "participant_recovering"
    elif has_result and result_success:
        from_state = STATE_WAITING_RESULT
        lifecycle_state = STATE_RESULT_ACCEPTED
        trigger = TR_RESULT_ACCEPTED
        dispatch_reason = "result_accepted_by_center"
    elif bool(signal.get("busy", False)):
        from_state = "dispatched"
        lifecycle_state = STATE_EXECUTING
        trigger = TR_EXECUTION_STARTED
        dispatch_reason = "participant_busy_executing"

    implications = _find_transition_implications(
        from_state=from_state,
        to_state=lifecycle_state,
        trigger=trigger,
    )
    closure_blocking = lifecycle_state in {
        STATE_DETACHED,
        STATE_RECOVERING,
        STATE_EXECUTING,
        STATE_SUSPENDED,
    }
    return {
        "state": lifecycle_state,
        "trigger": trigger,
        "from_state": from_state,
        "dispatch_eligible": dispatch_eligible,
        "dispatch_reason": dispatch_reason,
        "truth_implication": implications["truth_implication"],
        "closure_implication": implications["closure_implication"],
        "closure_blocking": closure_blocking,
    }


def _derive_signal(device_id: str) -> Dict[str, Any]:
    signal: Dict[str, Any] = {
        "readiness": "unknown",
        "posture": "unknown",
        "busy": False,
        "orchestration_eligible": None,
        "reasons": [],
    }

    try:
        from core.device_participation import get_device_participation

        ps = get_device_participation(device_id)
        signal["orchestration_eligible"] = bool(getattr(ps, "orchestration_eligible", False))
        roles = list(getattr(ps, "roles", []) or [])
        signal["posture"] = str(getattr(ps, "routing_intent", "") or getattr(ps, "participant_tier", "") or "unknown")
        signal["busy"] = "busy" in roles
        signal["reasons"].extend([str(r) for r in (getattr(ps, "reasons", []) or [])])
        if signal["orchestration_eligible"]:
            signal["readiness"] = "ready"
        else:
            signal["readiness"] = "suspended"
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

    try:
        from core.device_readiness import get_device_readiness

        rs = get_device_readiness(device_id)
        online = bool(getattr(rs, "online", False))
        routable = bool(getattr(rs, "routable", False))
        signal["busy"] = signal["busy"] or ("busy" in " ".join(getattr(rs, "reasons", []) or []).lower())
        if not online or not routable:
            signal["readiness"] = "lost"
            signal["reasons"].append("device_not_online_or_routable")
        elif signal["readiness"] == "unknown":
            signal["readiness"] = "ready"
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

    return signal


def _classify_participant_result(result: Any) -> str:
    if not isinstance(result, dict):
        return "failed"
    if bool(result.get("success", False)):
        return "ready"
    text = f"{result.get('error', '')} {result.get('message', '')}".lower()
    if any(token in text for token in _LOSS_TOKENS):
        return "lost"
    if any(token in text for token in _DEGRADED_TOKENS):
        return "degraded"
    return "failed"


def _base_role_from_formation(member: Dict[str, Any], primary_device_id: str) -> str:
    role = str(member.get("role", "") or "")
    device_id = str(member.get("device_id", "") or "")
    if role == "fallback_device":
        return ROLE_FALLBACK
    if role == "primary_execution_device" or (device_id and device_id == primary_device_id):
        return ROLE_PRIMARY
    if role in {"support_device", "relay_device", "merge_owner_device", "source_device"}:
        return ROLE_ASSISTANT
    return ROLE_ASSISTANT


def build_multi_subject_truth_bridge(
    *,
    formation: Optional[Dict[str, Any]] = None,
    participant_results: Optional[List[Any]] = None,
    source_device_id: str = "",
    recovery_device_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build a minimal participant governance + truth convergence snapshot.

    Parameters
    ----------
    formation:
        Formation dict containing ``primary_execution_device_id`` and
        ``members`` list.
    participant_results:
        List of per-device result dicts.
    source_device_id:
        Device ID of the originating source.
    recovery_device_ids:
        Optional list of device IDs that are re-joining after a prior
        failure or suspension.  These are flagged in participant entries
        and influence the ``completion_state`` classification.
    """
    formation = formation or {}
    participant_results = participant_results or []
    recovery_ids = set(recovery_device_ids or [])

    members = formation.get("members") if isinstance(formation, dict) else None
    if not isinstance(members, list):
        members = []
    primary_device_id = str((formation or {}).get("primary_execution_device_id", "") or "")

    result_by_device: Dict[str, Dict[str, Any]] = {}
    for item in participant_results:
        if isinstance(item, dict):
            device_id = str(item.get("device_id", "") or "")
            if device_id:
                result_by_device[device_id] = item

    participants: List[Dict[str, Any]] = []
    role_lifecycle_events: List[Dict[str, Any]] = []
    for member in members:
        if not isinstance(member, dict):
            continue
        device_id = str(member.get("device_id", "") or "")
        if not device_id:
            continue
        signal = _derive_signal(device_id)
        _participant_result = result_by_device.get(device_id)
        if _participant_result is None:
            _sig_readiness = str(signal.get("readiness", "") or "")
            if _sig_readiness in {"ready", "degraded", "lost", "suspended"}:
                state = _sig_readiness
            else:
                state = "degraded"
        else:
            state = _classify_participant_result(_participant_result)
        role = _base_role_from_formation(member, primary_device_id)
        if signal.get("orchestration_eligible") is False:
            role = ROLE_SUSPENDED
            state = "suspended"
        elif signal.get("readiness") == "lost" and state == "ready":
            state = "lost"
        if state == "degraded" and role not in {ROLE_SUSPENDED, ROLE_TAKEOVER_CANDIDATE}:
            if role != ROLE_DEGRADED:
                role_lifecycle_events.append(
                    {
                        "device_id": device_id,
                        "event": "demotion",
                        "from_role": role,
                        "to_role": ROLE_DEGRADED,
                        "reason": "participant_degraded",
                    }
                )
            role = ROLE_DEGRADED

        _has_result = _participant_result is not None
        _result_success = bool((_participant_result or {}).get("success", False))
        lifecycle = _build_lifecycle_projection(
            role=role,
            state=state,
            signal=signal,
            has_result=_has_result,
            result_success=_result_success,
            is_recovery=device_id in recovery_ids,
        )

        participants.append(
            {
                "device_id": device_id,
                "role": role,
                "state": state,
                "formation_role": str(member.get("role", "") or "unassigned"),
                "signal": signal,
                "is_source": bool(source_device_id and source_device_id == device_id),
                "is_recovery": device_id in recovery_ids,
                "role_display": "degraded_participant" if role == ROLE_DEGRADED else role,
                "lifecycle_state": lifecycle["state"],
                "lifecycle_trigger": lifecycle["trigger"],
                "lifecycle_from_state": lifecycle["from_state"],
                "dispatch_eligible": lifecycle["dispatch_eligible"],
                "dispatch_implication": lifecycle["dispatch_reason"],
                "truth_implication": lifecycle["truth_implication"],
                "closure_implication": lifecycle["closure_implication"],
                "closure_blocking": lifecycle["closure_blocking"],
            }
        )

    primary = next((p for p in participants if p["role"] == ROLE_PRIMARY), None)
    takeover_candidate: Optional[str] = None
    if primary and primary.get("state") in {"lost", "failed", "suspended", "degraded"}:
        if primary["role"] == ROLE_PRIMARY and primary.get("state") in {"lost", "failed", "degraded"}:
            primary["role"] = ROLE_DEGRADED
            primary["role_display"] = "degraded_participant"
            role_lifecycle_events.append(
                {
                    "device_id": primary["device_id"],
                    "event": "demotion",
                    "from_role": ROLE_PRIMARY,
                    "to_role": ROLE_DEGRADED,
                    "reason": f"primary_{primary.get('state')}",
                }
            )
        for candidate in participants:
            if candidate["device_id"] == primary["device_id"]:
                continue
            if candidate["role"] in {ROLE_FALLBACK, ROLE_ASSISTANT} and candidate["state"] in {"ready", "degraded"}:
                _from_role = candidate["role"]
                candidate["role"] = ROLE_TAKEOVER_CANDIDATE
                candidate["role_display"] = "takeover_candidate"
                candidate["lifecycle_state"] = STATE_TAKEOVER_CANDIDATE
                candidate["lifecycle_trigger"] = TR_TAKEOVER_NOMINATED
                candidate["lifecycle_from_state"] = STATE_ATTACHED
                candidate["dispatch_eligible"] = True
                candidate["dispatch_implication"] = "takeover_candidate_prequalified"
                _implications = _find_transition_implications(
                    from_state=STATE_ATTACHED,
                    to_state=STATE_TAKEOVER_CANDIDATE,
                    trigger=TR_TAKEOVER_NOMINATED,
                )
                candidate["truth_implication"] = _implications["truth_implication"]
                candidate["closure_implication"] = _implications["closure_implication"]
                candidate["closure_blocking"] = False
                takeover_candidate = candidate["device_id"]
                role_lifecycle_events.append(
                    {
                        "device_id": candidate["device_id"],
                        "event": "promotion",
                        "from_role": _from_role,
                        "to_role": ROLE_TAKEOVER_CANDIDATE,
                        "reason": "primary_unavailable_takeover_required",
                    }
                )
                break

    success_count = sum(1 for p in participants if p["state"] == "ready")
    degraded_count = sum(1 for p in participants if p["state"] == "degraded")
    lost_count = sum(1 for p in participants if p["state"] == "lost")
    failed_count = sum(1 for p in participants if p["state"] == "failed")
    suspended_count = sum(1 for p in participants if p["state"] == "suspended")

    # Check recovery-path completion: at least one recovering device succeeded.
    recovery_succeeded = any(
        p["state"] == "ready" and p.get("is_recovery", False) for p in participants
    )

    if recovery_succeeded and success_count > 0:
        completion_state = "recovery_completion"
    elif participants and success_count == len(participants):
        completion_state = "success"
    elif takeover_candidate and success_count > 0:
        completion_state = "takeover_continuation"
    elif success_count > 0 and (lost_count > 0 or degraded_count > 0):
        completion_state = "degraded_completion"
    elif success_count > 0:
        completion_state = "partial_success"
    else:
        completion_state = "failed"

    # reconcile_required: set when the closure is ambiguous.
    _reconcile_required = (
        (completion_state == "failed" and lost_count > 0 and not takeover_candidate)
        or (completion_state == "failed" and degraded_count > 0)
        or (recovery_succeeded and not recovery_ids)
    )

    closure = {
        "completion_state": completion_state,
        "terminal": completion_state in {
            "success",
            "partial_success",
            "degraded_completion",
            "takeover_continuation",
            "recovery_completion",
            "failed",
        },
        "requires_review": completion_state != "success",
        "reconcile_required": _reconcile_required,
        "canonical_truth_status": "converged" if participants else "partial",
    }
    _dispatch_blocked = [
        p["device_id"] for p in participants if not bool(p.get("dispatch_eligible", False))
    ]

    return {
        "authority": MULTI_SUBJECT_TRUTH_CONVERGENCE_BRIDGE_AUTHORITY,
        "participants": participants,
        "participant_roles": {p["device_id"]: p["role"] for p in participants},
        "participant_lifecycle_machine": {
            "version": "v1",
            "schema_anchor": "contracts.participant_lifecycle_schema",
            "dispatch_blocked_participants": _dispatch_blocked,
            "role_lifecycle_events": role_lifecycle_events,
        },
        "role_lifecycle": {
            "events": role_lifecycle_events,
        },
        "failure_isolation": {
            "lost": [p["device_id"] for p in participants if p["state"] == "lost"],
            "degraded": [p["device_id"] for p in participants if p["state"] == "degraded"],
            "failed": [p["device_id"] for p in participants if p["state"] == "failed"],
            "suspended": [p["device_id"] for p in participants if p["state"] == "suspended"],
            "takeover_candidate": takeover_candidate,
        },
        "counts": {
            "participants": len(participants),
            "success": success_count,
            "degraded": degraded_count,
            "lost": lost_count,
            "failed": failed_count,
            "suspended": suspended_count,
        },
        "closure": closure,
    }
