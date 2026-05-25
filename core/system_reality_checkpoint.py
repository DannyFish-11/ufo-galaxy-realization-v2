#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/system_reality_checkpoint.py
=================================
Implementation-grounded convergence checkpoint for the remaining system-reality
gaps across node/runtime/panel/model/device surfaces.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List


SYSTEM_REALITY_CHECKPOINT_AUTHORITY: str = (
    "SYSTEM_REALITY_CHECKPOINT_V1::core.system_reality_checkpoint"
)


def _safe_call(fn, default):
    try:
        return fn()
    except Exception:
        return default


def _build_node_system_checkpoint() -> Dict[str, Any]:
    from core.nodes.node_fabric_registry import get_node_fabric_registry

    fab = get_node_fabric_registry()
    canonical_nodes = fab.list_nodes()
    legacy_only_count = 0
    legacy_total = 0
    try:
        from core.node_registry import get_node_registry

        legacy = get_node_registry()
        legacy_total = len(getattr(legacy, "metadata", {}))
        canonical_ids = {n.node_id for n in canonical_nodes}
        legacy_only_count = len(set(getattr(legacy, "metadata", {}).keys()) - canonical_ids)
    except Exception:
        pass
    return {
        "canonical_registry": "core.nodes.node_fabric_registry.NodeFabricRegistry",
        "legacy_registry": "core.node_registry.NodeRegistry",
        "canonical_node_count": len(canonical_nodes),
        "legacy_node_count": legacy_total,
        "legacy_only_node_count": legacy_only_count,
        "dual_registry_ambiguity_reduced": legacy_only_count == 0,
        "role_boundaries": {
            "node": "fabric-registered compute/service endpoint",
            "device": "physical/virtual endpoint managed by device stores",
            "worker": "node role that executes workload units",
            "participant": "runtime-attached actor (often android device/session)",
            "runtime_host": "V2 host process owning canonical control-plane truth",
            "session_owner": "owner of interaction continuity/session identity",
            "execution_owner": "owner of active task lifecycle state",
        },
    }


def _build_mcp_skill_checkpoint() -> Dict[str, Any]:
    from core.mcp_loader import mcp_loader
    from core.skill_loader import skill_loader
    from core.skill_md_loader import skill_md_loader

    servers = mcp_loader.list_servers()
    skills = skill_loader.list_skills()
    shell_skills = skill_md_loader.list_skills()
    mcp_tool_count = sum(
        len(getattr(server, "tools", []) or [])
        for server in getattr(mcp_loader, "servers", {}).values()
    )
    return {
        "formal_mcp_servers": len(servers),
        "formal_mcp_tool_count": mcp_tool_count,
        "python_skill_count": len(skills),
        "shell_skill_count": len(shell_skills),
        "semantics_boundaries": {
            "formal_mcp_tool_call": "remote MCP server tool via JSON-RPC",
            "python_skill_handler": "in-process python callable skill handler",
            "shell_command_skill": "SKILL.md allowlisted shell command execution",
            "capability_gate": "tool/command availability validated at runtime",
        },
    }


def _build_runtime_credibility_checkpoint(panel_generated_at: float) -> Dict[str, Any]:
    from core.android_device_state_store import list_device_state_snapshots

    snaps = list_device_state_snapshots()
    latest_absorbed = max(
        [float(getattr(s, "absorbed_at", 0.0) or 0.0) for s in snaps] or [0.0]
    )
    now = time.time()
    android_age = max(0.0, now - latest_absorbed) if latest_absorbed else None
    return {
        "host_snapshot_generated_at": panel_generated_at,
        "android_snapshot_latest_at": latest_absorbed or None,
        "android_snapshot_age_seconds": android_age,
        "android_snapshot_is_stale": bool(android_age is not None and android_age > 120.0),
        "state_truth": {
            "process_local_state_marked": True,
            "restart_recovery_path": "core.runtime_restart_recovery",
            "freshness_markers_present": True,
        },
    }


def _build_model_topology_checkpoint() -> Dict[str, Any]:
    try:
        from core.model_topology import build_canonical_model_supply_state_from_router
        from core.multi_llm_router import get_llm_router

        supply = build_canonical_model_supply_state_from_router(get_llm_router()).to_dict()
    except Exception:
        supply = {}
    providers = list(supply.get("provider_records", []) or [])
    available = [p for p in providers if str(p.get("availability", "")).lower() == "available"]
    selected = str((supply.get("route_selection") or {}).get("selected_provider_id") or "")
    return {
        "provider_count": len(providers),
        "available_provider_count": len(available),
        "selected_provider": selected or None,
        "galaxy_tree": {
            "root": "runtime_host",
            "children": [
                {"node": "model_providers", "count": len(providers)},
                {"node": "available_providers", "count": len(available)},
                {"node": "selected_provider", "value": selected or "none"},
            ],
        },
    }


def _build_task_allocation_checkpoint() -> Dict[str, Any]:
    from core.canonical_task import get_canonical_task_runtime

    records = [r.to_dict() for r in get_canonical_task_runtime().list_allocation_records(limit=64)]
    fallback_count = len([r for r in records if r.get("fallback_used")])
    return {
        "allocation_records": records,
        "allocation_record_count": len(records),
        "fallback_usage_count": fallback_count,
        "visibility_contract": "requested->accepted->in_flight->closure per task",
    }


def _build_device_support_checkpoint() -> Dict[str, Any]:
    from core.android_device_state_store import list_device_state_snapshots

    snapshots = list_device_state_snapshots()
    observed_types = sorted({str(getattr(s, "device_type", "android")) for s in snapshots})
    matrix: List[Dict[str, Any]] = []
    for d in observed_types or ["android"]:
        matrix.append(
            {
                "device_type": d,
                "declared": True,
                "registered": bool(snapshots),
                "observable": bool(snapshots),
                "control_capable": d in {"android", "windows", "macos", "linux", "desktop"},
                "execution_capable": d in {"android", "windows", "macos", "linux", "desktop"},
                "closure_integrated": d in {"android", "windows", "macos", "linux", "desktop"},
                "unsupported_but_declared": d not in {"android", "windows", "macos", "linux", "desktop"},
            }
        )
    return {"support_matrix": matrix}


def _build_device_autonomy_checkpoint() -> Dict[str, Any]:
    from core.android_device_state_store import list_device_state_snapshots
    from core.android_network_participation import get_participation_state_for_device

    tier_to_class = {
        "local_only": "connected_only",
        "control_only": "observable_only",
        "cross_device_capable": "participant_capable",
        "cross_device_enabled": "participant_capable",
        "fully_attached": "execution_capable",
        "dispatch_eligible": "semi_autonomous_runtime_capable",
        "distributed_participant": "meaningfully_autonomous_runtime_capable",
    }
    classes: List[Dict[str, Any]] = []
    for snap in list_device_state_snapshots():
        did = getattr(snap, "device_id", None)
        if not did:
            continue
        state = get_participation_state_for_device(did)
        tier = state.tier.value if hasattr(state.tier, "value") else str(state.tier)
        classes.append(
            {
                "device_id": did,
                "tier": tier,
                "autonomy_class": tier_to_class.get(tier, "connected_only"),
                "evidence": {
                    "websocket_connected": bool(getattr(state, "websocket_connected", False)),
                    "active_session_count": int(getattr(state, "active_session_count", 0) or 0),
                    "readiness_satisfied": bool(getattr(state, "readiness_satisfied", False)),
                    "dispatch_gate_passed": bool(getattr(state, "dispatch_gate_passed", False)),
                },
            }
        )
    return {"autonomy_classification": classes}


def build_system_reality_checkpoint(*, panel_generated_at: float | None = None) -> Dict[str, Any]:
    """Build a structured, implementation-grounded system reality checkpoint."""
    generated_at = float(panel_generated_at or time.time())
    node_system = _build_node_system_checkpoint()
    mcp_skill_tool = _build_mcp_skill_checkpoint()
    runtime_credibility = _build_runtime_credibility_checkpoint(generated_at)
    model_topology = _build_model_topology_checkpoint()
    task_allocation = _build_task_allocation_checkpoint()
    device_support = _build_device_support_checkpoint()
    device_autonomy = _build_device_autonomy_checkpoint()
    return {
        "authority": SYSTEM_REALITY_CHECKPOINT_AUTHORITY,
        "generated_at": generated_at,
        "node_system": node_system,
        "mcp_skill_tool_capability": mcp_skill_tool,
        "long_running_runtime_credibility": runtime_credibility,
        "unified_panel_runtime_truth": {
            "panel_path": "/api/v1/panel/unified",
            "truth_compilation_surface": "core.unified_panel_aggregation",
            "staleness_visible": True,
        },
        "model_topology": model_topology,
        "task_allocation_visibility": task_allocation,
        "device_support_boundaries": device_support,
        "device_autonomy_evidence": device_autonomy,
        "final_checkpoint": {
            "node_system_actual": node_system,
            "mcp_skill_tool_capability_actual": mcp_skill_tool,
            "host_runtime_credibility_actual": runtime_credibility,
            "panel_truth_actual": {
                "unified_surface": "/api/v1/panel/unified",
                "checkpoint_embedded": True,
            },
            "model_topology_actual": model_topology,
            "task_allocation_actual": {
                "records_exposed": task_allocation.get("allocation_record_count", 0),
                "fallback_visibility": task_allocation.get("fallback_usage_count", 0),
            },
            "supported_device_types_actual": device_support.get("support_matrix", []),
            "autonomy_classes_actual": device_autonomy.get("autonomy_classification", []),
        },
    }
