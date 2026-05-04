from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.capability_runtime.capability_state import (
    CapabilityAvailability,
    CapabilityRuntimeState,
)

from .capability_contract import CapabilityContract


@dataclass
class UnifiedCapabilityRecord:
    """Canonical one-plane capability record.

    This record is the unified view returned to capability-plane consumers. It
    combines:
    - static contract identity/shape
    - live runtime state
    - lifecycle / authority metadata
    """

    capability_id: str
    canonical_name: str
    source_kind: str
    provider_id: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    returns: Dict[str, Any] = field(default_factory=dict)
    version: str = "1.0.0"
    tags: List[str] = field(default_factory=list)
    execution_surface: str = "unknown"
    participant_kind: str = "unknown"
    exec_mode: str = "both"
    routability: str = "unknown"
    availability: str = CapabilityAvailability.UNKNOWN.value
    health: str = "unknown"
    last_seen: float = 0.0
    degradation_reason: str = ""
    network_reachability: str = "unknown"
    authority_lineage: List[str] = field(default_factory=list)
    publication_source: str = ""
    mutation_source: str = ""
    evidence_source: str = ""
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    policy_flags: List[str] = field(default_factory=list)
    device_bindings: List[str] = field(default_factory=list)
    preferred_device_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    contract: Optional[CapabilityContract] = None
    runtime_state: Optional[CapabilityRuntimeState] = None

    @classmethod
    def from_contract(
        cls,
        contract: CapabilityContract,
        runtime_state: Optional[CapabilityRuntimeState] = None,
    ) -> "UnifiedCapabilityRecord":
        metadata = dict(contract.metadata or {})
        runtime_payload = dict(metadata.get("runtime_state") or {})
        plane_payload = dict(metadata.get("capability_plane") or {})
        provider = dict(metadata.get("capability_provider") or {})
        runtime_state = runtime_state or (
            CapabilityRuntimeState.from_dict(
                {
                    "name": contract.name,
                    "availability": runtime_payload.get(
                        "availability",
                        CapabilityAvailability.AVAILABLE.value
                        if contract.available
                        else CapabilityAvailability.UNKNOWN.value,
                    ),
                    "device_bindings": runtime_payload.get("device_bindings", []),
                    "preferred_device_ids": runtime_payload.get("preferred_device_ids", []),
                    "constraint_flags": runtime_payload.get("constraint_flags", {}),
                    "reliability_flags": runtime_payload.get("reliability_flags", {}),
                    "last_updated": runtime_payload.get("last_updated", contract.created_at),
                    "metadata": runtime_payload.get("metadata", {}),
                }
            )
            if runtime_payload
            else None
        )
        availability = (
            runtime_state.availability.value
            if runtime_state is not None and hasattr(runtime_state.availability, "value")
            else (
                CapabilityAvailability.AVAILABLE.value
                if contract.available
                else CapabilityAvailability.UNKNOWN.value
            )
        )
        reliability_flags = (
            dict(runtime_state.reliability_flags or {}) if runtime_state is not None else {}
        )
        runtime_metadata = dict(runtime_state.metadata or {}) if runtime_state is not None else {}
        return cls(
            capability_id=str(metadata.get("capability_id") or contract.name),
            canonical_name=contract.name,
            source_kind=contract.source.value if hasattr(contract.source, "value") else str(contract.source),
            provider_id=contract.source_id,
            description=contract.description,
            parameters=dict(contract.parameters or {}),
            returns=dict(metadata.get("returns") or {}),
            version=contract.version,
            tags=list(contract.tags or []),
            execution_surface=str(provider.get("execution_surface_type") or "unknown"),
            participant_kind=str(runtime_metadata.get("participant_kind") or metadata.get("participant_kind") or "unknown"),
            exec_mode=str(metadata.get("exec_mode") or "both"),
            routability=str(runtime_metadata.get("routability") or metadata.get("routability") or "unknown"),
            availability=availability,
            health=str(reliability_flags.get("health") or metadata.get("capability_bus_health") or "unknown"),
            last_seen=float(
                runtime_metadata.get("last_seen")
                or runtime_payload.get("last_updated")
                or metadata.get("registered_at")
                or contract.created_at
            ),
            degradation_reason=str(runtime_metadata.get("degradation_reason") or ""),
            network_reachability=str(runtime_metadata.get("network_reachability") or "unknown"),
            authority_lineage=list(metadata.get("authority_lineage") or plane_payload.get("authority_lineage") or []),
            publication_source=str(plane_payload.get("publication_source") or metadata.get("publication_source") or ""),
            mutation_source=str(plane_payload.get("mutation_source") or metadata.get("mutation_source") or ""),
            evidence_source=str(metadata.get("evidence_source") or ""),
            diagnostics=dict(metadata.get("diagnostics") or {}),
            policy_flags=list(metadata.get("policy_flags") or []),
            device_bindings=list(runtime_state.device_bindings if runtime_state is not None else []),
            preferred_device_ids=list(runtime_state.preferred_device_ids if runtime_state is not None else []),
            metadata=metadata,
            contract=contract,
            runtime_state=runtime_state,
        )

    def to_tool_schema(self) -> Dict[str, Any]:
        if self.contract is not None:
            return self.contract.to_tool_schema()
        return {
            "type": "function",
            "function": {
                "name": self.canonical_name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}},
            },
        }

    def is_routable(self) -> bool:
        return self.availability in {
            CapabilityAvailability.AVAILABLE.value,
            CapabilityAvailability.DEGRADED.value,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "canonical_name": self.canonical_name,
            "source_kind": self.source_kind,
            "provider_id": self.provider_id,
            "description": self.description,
            "parameters": dict(self.parameters),
            "returns": dict(self.returns),
            "version": self.version,
            "tags": list(self.tags),
            "execution_surface": self.execution_surface,
            "participant_kind": self.participant_kind,
            "exec_mode": self.exec_mode,
            "routability": self.routability,
            "availability": self.availability,
            "health": self.health,
            "last_seen": self.last_seen or time.time(),
            "degradation_reason": self.degradation_reason,
            "network_reachability": self.network_reachability,
            "authority_lineage": list(self.authority_lineage),
            "publication_source": self.publication_source,
            "mutation_source": self.mutation_source,
            "evidence_source": self.evidence_source,
            "diagnostics": dict(self.diagnostics),
            "policy_flags": list(self.policy_flags),
            "device_bindings": list(self.device_bindings),
            "preferred_device_ids": list(self.preferred_device_ids),
            "metadata": dict(self.metadata),
        }
