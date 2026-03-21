"""
core/contract_map/contract_introspection.py
=============================================
Read-only helpers for inspecting the cross-plane contract map at runtime.

These functions are intentionally narrow and side-effect-free.  They do not
modify registry state, trigger network activity, or load optional modules.
They are safe to call from API endpoints and diagnostics tooling.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .contract_registry import get_contract_registry
from .plane_kind import PlaneKind
from .message_kind import MessageKind


def get_planes_snapshot() -> Dict[str, Any]:
    """Return a summary of all planes and the message kinds they contain.

    This is the primary payload for ``GET /api/v1/contracts/planes``.

    Returns
    -------
    dict
        ``{
            "planes": {
                "<plane_value>": {
                    "description": "<docstring first line>",
                    "message_kinds": ["<kind_value>", ...]
                },
                ...
            },
            "total_planes": <int>,
            "total_contracts": <int>
        }``
    """
    registry = get_contract_registry()
    planes_map = registry.planes_summary()

    # Enrich with PlaneKind descriptions (first line of docstring)
    plane_descriptions: Dict[str, str] = {
        PlaneKind.device_plane.value: (
            "AIP/WebSocket device-facing flows: registration, heartbeat, "
            "capability reports, task dispatch to/from physical devices."
        ),
        PlaneKind.orchestration_plane.value: (
            "Internal task-envelope contracts: TaskEnvelope lifecycle, "
            "priority, session continuity, and lifecycle state machine."
        ),
        PlaneKind.control_plane.value: (
            "NATS JetStream control/task subjects: task dispatch, result "
            "delivery, worker heartbeat, MCP calls, capability events."
        ),
        PlaneKind.runtime_handoff_plane.value: (
            "Gateway-to-runtime handoff: HandoffContract (agent_bridge), "
            "SwarmAgentManifest (remote swarm dispatch)."
        ),
        PlaneKind.projection_plane.value: (
            "Read-only derived state surfaces: RuntimeProjection, return "
            "intelligence, execution-policy views, merge summaries."
        ),
        PlaneKind.observability_plane.value: (
            "Cross-cutting audit, telemetry, and diagnostic events that do "
            "not belong exclusively to any single functional plane."
        ),
    }

    planes_detail: Dict[str, Any] = {}
    for plane_value, kinds in planes_map.items():
        planes_detail[plane_value] = {
            "description": plane_descriptions.get(plane_value, ""),
            "message_kinds": sorted(kinds),
        }

    # Include any PlaneKind values that have no descriptors yet
    for pk in PlaneKind:
        if pk.value not in planes_detail:
            planes_detail[pk.value] = {
                "description": plane_descriptions.get(pk.value, ""),
                "message_kinds": [],
            }

    return {
        "planes": planes_detail,
        "total_planes": len(PlaneKind),
        "total_contracts": len(registry),
    }


def get_messages_snapshot() -> Dict[str, Any]:
    """Return descriptors for all registered message kinds.

    This is the primary payload for ``GET /api/v1/contracts/messages``.

    Returns
    -------
    dict
        ``{
            "contracts": {
                "<kind_value>": { ...descriptor... },
                ...
            },
            "total_contracts": <int>
        }``
    """
    registry = get_contract_registry()
    return {
        "contracts": registry.snapshot(),
        "total_contracts": len(registry),
    }


def get_descriptor_for_kind(kind: MessageKind) -> Optional[Dict[str, Any]]:
    """Return the descriptor dict for a specific *kind*, or ``None``."""
    registry = get_contract_registry()
    descriptor = registry.get(kind)
    return descriptor.to_dict() if descriptor is not None else None


def get_required_fields_summary() -> List[Dict[str, Any]]:
    """Return a list of required-field summaries for all registered contracts.

    Useful for diagnostics: quickly see what identity fields each contract
    requires without fetching full descriptor metadata.
    """
    registry = get_contract_registry()
    return [d.required_fields_summary() for d in registry.all_descriptors()]


def get_contracts_for_plane(plane: PlaneKind) -> List[Dict[str, Any]]:
    """Return descriptor dicts for all contracts in *plane*."""
    registry = get_contract_registry()
    return [d.to_dict() for d in registry.descriptors_for_plane(plane)]
