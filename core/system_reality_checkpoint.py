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
    from core.nodes.node_fabric_registry import (
        CANONICAL_RUNTIME_NODE_REGISTRY_AUTHORITY,
        get_node_fabric_registry,
    )

    fab = get_node_fabric_registry()
    canonical_nodes = fab.list_nodes()
    return {
        "canonical_registry": "core.nodes.node_fabric_registry.NodeFabricRegistry",
        "canonical_registry_authority": CANONICAL_RUNTIME_NODE_REGISTRY_AUTHORITY,
        "legacy_registry": "core.node_registry.NodeRegistry (compat facade)",
        "canonical_node_count": len(canonical_nodes),
        "legacy_node_count": 0,
        "legacy_only_node_count": 0,
        "dual_registry_ambiguity_reduced": True,
        "legacy_registry_runtime_authority": False,
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
    skill_wrappers = len(skill_loader.list_as_mcp_tools())
    return {
        "formal_mcp_servers": len(servers),
        "formal_mcp_tool_count": mcp_tool_count,
        "python_skill_count": len(skills),
        "shell_skill_count": len(shell_skills),
        "compat_wrapper_tool_count": skill_wrappers,
        "semantics_boundaries": {
            "formal_mcp_tool_call": "remote MCP server tool via JSON-RPC",
            "python_skill_handler": "in-process python callable skill handler",
            "shell_command_skill": "SKILL.md allowlisted shell command execution",
            "compatibility_wrapper": "skill exposed with MCP-like schema via list_as_mcp_tools()",
            "capability_gate": "tool/command availability validated at runtime",
        },
    }


def _build_runtime_credibility_checkpoint(panel_generated_at: float) -> Dict[str, Any]:
    from core.android_device_state_store import list_device_state_snapshots
    from core.canonical_task import get_canonical_task_runtime
    from core.delegated_runtime_execution_tracker import build_execution_tracking_snapshot

    snaps = list_device_state_snapshots()
    runtime = get_canonical_task_runtime()
    alloc_records = runtime.list_allocation_records(limit=1)
    tracker_snapshot = build_execution_tracking_snapshot()
    allocation_state_path = getattr(runtime, "_allocation_state_path", None)
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
            "process_local_state_marked": False,
            "restart_recovery_path": "core.runtime_restart_recovery",
            "freshness_markers_present": True,
            "allocation_truth_durable_path": allocation_state_path,
            "allocation_truth_recovered": bool(alloc_records),
            "delegated_execution_tracking_durable_path": tracker_snapshot.durable_state_path,
            "delegated_execution_tracking_restored_at": tracker_snapshot.durable_state_last_restored_at,
            "delegated_execution_tracking_recovered_unrevalidated_count": (
                tracker_snapshot.recovered_unrevalidated_count
            ),
            "delegated_execution_tracking_recovered_stale_count": (
                tracker_snapshot.recovered_stale_count
            ),
        },
    }


def _build_model_topology_checkpoint() -> Dict[str, Any]:
    from core.network_topology_runtime import (
        build_grounded_runtime_topology,
        get_network_topology_runtime,
    )

    try:
        from core.model_topology import build_canonical_model_supply_state_from_router
        from core.multi_llm_router import get_llm_router

        supply = build_canonical_model_supply_state_from_router(get_llm_router()).to_dict()
    except Exception:
        supply = {}
    providers = list(supply.get("provider_records", []) or [])
    available = [p for p in providers if str(p.get("availability", "")).lower() == "available"]
    selected = str((supply.get("route_selection") or {}).get("selected_provider_id") or "")
    topology = get_network_topology_runtime().snapshot().to_dict()
    grounded = build_grounded_runtime_topology().to_dict()
    provider_nodes = [
        {
            "id": str(p.get("provider_id") or p.get("id") or ""),
            "availability": str(p.get("availability") or "unknown"),
            "selected": str(p.get("provider_id") or p.get("id") or "") == selected,
        }
        for p in providers
    ]
    return {
        "provider_count": len(providers),
        "available_provider_count": len(available),
        "selected_provider": selected or None,
        "runtime_topology": {
            "runtime_host": grounded.get("runtime_host", "v2_control_plane"),
            "network_topology_nodes": topology.get("total_nodes", 0),
            "network_topology_edges": topology.get("total_edges", 0),
            "provider_nodes": provider_nodes,
            "relations": list(grounded.get("relations") or []),
            "galaxy_tree": dict(grounded.get("galaxy_tree") or {}),
            "grounded_node_count": len(list(grounded.get("nodes") or [])),
        },
    }


def _build_task_allocation_checkpoint() -> Dict[str, Any]:
    from core.canonical_task import TASK_ALLOCATION_TRUTH_AUTHORITY, get_canonical_task_runtime

    records = [r.to_dict() for r in get_canonical_task_runtime().list_allocation_records(limit=64)]
    fallback_count = len([r for r in records if r.get("fallback_used")])
    with_history_count = len([r for r in records if r.get("allocation_history")])
    return {
        "authority": TASK_ALLOCATION_TRUTH_AUTHORITY,
        "allocation_records": records,
        "allocation_record_count": len(records),
        "fallback_usage_count": fallback_count,
        "history_record_count": with_history_count,
        "visibility_contract": (
            "requested->accepted->in_flight->participant_phase->execution_location->closure "
            "with transition history per task"
        ),
    }


def _build_device_support_checkpoint() -> Dict[str, Any]:
    from core.android_device_state_store import list_device_state_snapshots
    from core.device_operational_support import build_device_support_matrix

    snapshots = list_device_state_snapshots()
    observed_types = sorted(
        {
            str(getattr(snapshot, "device_type", "android") or "android").lower()
            for snapshot in snapshots
        }
    )
    return build_device_support_matrix(observed_types=observed_types)


def _build_device_autonomy_checkpoint() -> Dict[str, Any]:
    from core.device_autonomy_evidence import build_device_autonomy_report

    return build_device_autonomy_report()


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
