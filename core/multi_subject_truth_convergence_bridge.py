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
    except Exception:
        pass

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
    except Exception:
        pass

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
        return "fallback"
    if role == "primary_execution_device" or (device_id and device_id == primary_device_id):
        return "primary"
    if role in {"support_device", "relay_device", "merge_owner_device", "source_device"}:
        return "assistant"
    return "assistant"


def build_multi_subject_truth_bridge(
    *,
    formation: Optional[Dict[str, Any]] = None,
    participant_results: Optional[List[Any]] = None,
    source_device_id: str = "",
) -> Dict[str, Any]:
    """Build a minimal participant governance + truth convergence snapshot."""
    formation = formation or {}
    participant_results = participant_results or []

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
            role = "suspended"
            state = "suspended"
        elif signal.get("readiness") == "lost" and state == "ready":
            state = "lost"

        participants.append(
            {
                "device_id": device_id,
                "role": role,
                "state": state,
                "formation_role": str(member.get("role", "") or "unassigned"),
                "signal": signal,
                "is_source": bool(source_device_id and source_device_id == device_id),
            }
        )

    primary = next((p for p in participants if p["role"] == "primary"), None)
    takeover_candidate: Optional[str] = None
    if primary and primary.get("state") in {"lost", "failed", "suspended", "degraded"}:
        for candidate in participants:
            if candidate["device_id"] == primary["device_id"]:
                continue
            if candidate["role"] in {"fallback", "assistant"} and candidate["state"] in {"ready", "degraded"}:
                candidate["role"] = "takeover_candidate"
                takeover_candidate = candidate["device_id"]
                break

    success_count = sum(1 for p in participants if p["state"] == "ready")
    degraded_count = sum(1 for p in participants if p["state"] == "degraded")
    lost_count = sum(1 for p in participants if p["state"] == "lost")
    failed_count = sum(1 for p in participants if p["state"] == "failed")
    suspended_count = sum(1 for p in participants if p["state"] == "suspended")

    if participants and success_count == len(participants):
        completion_state = "success"
    elif takeover_candidate and success_count > 0:
        completion_state = "takeover_continuation"
    elif success_count > 0 and (lost_count > 0 or degraded_count > 0):
        completion_state = "degraded_completion"
    elif success_count > 0:
        completion_state = "partial_success"
    else:
        completion_state = "failed"

    closure = {
        "completion_state": completion_state,
        "terminal": completion_state in {
            "success",
            "partial_success",
            "degraded_completion",
            "takeover_continuation",
            "failed",
        },
        "requires_review": completion_state != "success",
        "canonical_truth_status": "converged" if participants else "partial",
    }

    return {
        "authority": MULTI_SUBJECT_TRUTH_CONVERGENCE_BRIDGE_AUTHORITY,
        "participants": participants,
        "participant_roles": {p["device_id"]: p["role"] for p in participants},
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
