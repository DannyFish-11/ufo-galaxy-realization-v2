from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _reset_capability_plane() -> None:
    from core.agent.capability_registry import CapabilityRegistry
    from core.capability_runtime.capability_registry_runtime import CapabilityRuntimeRegistry
    from core.unified.capability_authority import CapabilityAuthority
    from core.unified.capability_resolver import reset_capability_resolver
    from galaxy_gateway.capability_registry import GatewayCapabilityRegistry

    reg = CapabilityRegistry.get_instance()
    reg._items.clear()
    reg._validation_errors.clear()
    reset_capability_resolver()
    with CapabilityRuntimeRegistry._instance_lock:
        CapabilityRuntimeRegistry._instance = None
    with CapabilityAuthority._instance_lock:
        CapabilityAuthority._instance = None
    GatewayCapabilityRegistry._instance = None


def test_capability_authority_unifies_contract_and_runtime_truth() -> None:
    from core.capability_runtime.capability_state import CapabilityAvailability
    from core.unified.capability_authority import CapabilityAuthority
    from core.unified.capability_contract import CapabilityContract, CapabilitySource
    from core.unified.capability_resolver import get_capability_resolver

    _reset_capability_plane()
    authority = CapabilityAuthority.get_instance()
    authority.upsert_contract(
        CapabilityContract(
            name="skill__authority_demo",
            description="Authority demo skill",
            source=CapabilitySource.SKILL,
            source_id="authority_demo",
            parameters={"type": "object", "properties": {}},
            tags=["demo"],
        ),
        mutation_source="test",
        publication_source="test",
        lifecycle_event="capability_registered",
    )
    authority.update_runtime(
        "skill__authority_demo",
        availability=CapabilityAvailability.DEGRADED.value,
        preferred_device_ids=["device-01"],
        metadata={"health": "degraded", "participant_kind": "skill_runtime"},
        mutation_source="test",
        lifecycle_event="capability_runtime_updated",
    )

    record = get_capability_resolver().resolve_record("skill__authority_demo")

    assert record is not None
    assert record.availability == CapabilityAvailability.DEGRADED.value
    assert record.preferred_device_ids == ["device-01"]
    assert "capability_authority" in record.authority_lineage
    assert record.mutation_source == "test"


def test_runtime_registry_updates_canonical_record_projection() -> None:
    from core.capability_runtime.capability_registry_runtime import CapabilityRuntimeRegistry
    from core.capability_runtime.capability_state import CapabilityAvailability, CapabilityRuntimeState
    from core.unified.capability_authority import CapabilityAuthority
    from core.unified.capability_contract import CapabilityContract, CapabilitySource
    from core.unified.capability_resolver import get_capability_resolver

    _reset_capability_plane()
    CapabilityAuthority.get_instance().upsert_contract(
        CapabilityContract(
            name="mcp__srv__tool",
            description="Runtime bridged tool",
            source=CapabilitySource.MCP,
            source_id="srv",
            parameters={"type": "object", "properties": {}},
        ),
        mutation_source="test",
        publication_source="test",
    )

    CapabilityRuntimeRegistry.get_instance().register(
        CapabilityRuntimeState(
            name="mcp__srv__tool",
            availability=CapabilityAvailability.DEGRADED,
            device_bindings=["srv"],
            preferred_device_ids=["srv"],
            reliability_flags={"health": "degraded"},
            metadata={"participant_kind": "mcp_runtime"},
        )
    )

    contract = get_capability_resolver().resolve("mcp__srv__tool")
    record = get_capability_resolver().resolve_record("mcp__srv__tool")

    assert contract is not None
    assert record is not None
    assert contract.metadata["runtime_state"]["availability"] == CapabilityAvailability.DEGRADED.value
    assert record.availability == CapabilityAvailability.DEGRADED.value
    assert record.device_bindings == ["srv"]


def test_gateway_registry_projects_same_unified_capability_plane() -> None:
    from galaxy_gateway.capability_registry import GatewayCapabilityRegistry
    from core.unified.capability_resolver import get_capability_resolver

    _reset_capability_plane()
    GatewayCapabilityRegistry().upsert(
        "android-01",
        "tap",
        {"exec_mode": "local", "version": "3.0", "tags": ["ui"]},
    )

    record = get_capability_resolver().resolve_record("gateway__android-01__tap")

    assert record is not None
    assert record.provider_id == "android-01"
    assert record.exec_mode == "local"
    assert record.device_bindings == ["android-01"]
    assert record.version == "3.0"
