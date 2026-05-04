from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _reset_capability_state() -> None:
    from core.agent.capability_registry import CapabilityRegistry
    from core.capability_runtime.capability_registry_runtime import CapabilityRuntimeRegistry
    from core.capability_orchestrator import CapabilityOrchestrator
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
    CapabilityOrchestrator._instance = None
    GatewayCapabilityRegistry._instance = None


def test_gateway_capability_registry_uses_canonical_capability_authority():
    from core.agent.capability_registry import CapabilityRegistry
    from galaxy_gateway.capability_registry import ExecMode, GatewayCapabilityRegistry

    _reset_capability_state()
    gw_reg = GatewayCapabilityRegistry()

    schema = gw_reg.upsert(
        "android-test-01",
        "tap",
        {"exec_mode": "local", "version": "2.0", "tags": ["ui", "touch"]},
    )

    canonical = CapabilityRegistry.get_instance().get("gateway__android-test-01__tap")

    assert canonical is not None
    assert canonical.source == "gateway"
    assert canonical.source_id == "android-test-01"
    assert canonical.metadata["exec_mode"] == ExecMode.LOCAL.value
    assert canonical.metadata["contract_version"] == "2.0"
    assert canonical.metadata["contract_tags"] == ["ui", "touch"]
    assert schema.version == "2.0"


def test_canonical_gateway_capability_projection_reads_from_resolver():
    from galaxy_gateway.capability_registry import GatewayCapabilityRegistry
    from core.unified.gateway_capability_projection import query_gateway_capabilities

    _reset_capability_state()
    GatewayCapabilityRegistry().upsert(
        "android-test-03",
        "screenshot",
        {"exec_mode": "local", "version": "5.0", "tags": ["vision"]},
    )

    schemas = query_gateway_capabilities(
        action="screenshot",
        exec_mode="local",
        device_id="android-test-03",
    )

    assert len(schemas) == 1
    assert schemas[0].device_id == "android-test-03"
    assert schemas[0].action == "screenshot"
    assert schemas[0].exec_mode == "local"
    assert schemas[0].tags == ["vision"]


def test_canonical_gateway_capability_projection_purge_removes_capability():
    from galaxy_gateway.capability_registry import GatewayCapabilityRegistry
    from core.unified.capability_resolver import get_capability_resolver
    from core.unified.gateway_capability_projection import purge_gateway_capabilities_for_device

    _reset_capability_state()
    GatewayCapabilityRegistry().upsert(
        "android-test-04",
        "tap",
        {"exec_mode": "local"},
    )

    removed = purge_gateway_capabilities_for_device("android-test-04")
    record = get_capability_resolver().resolve_record("gateway__android-test-04__tap")

    assert removed == 1
    assert record is None


@pytest.mark.asyncio
async def test_android_capability_report_writes_directly_to_canonical_capability_authority():
    from galaxy_gateway.android.handlers.capability_report import handle_capability_report
    from core.capability_runtime.capability_state import CapabilityAvailability
    from core.unified.capability_resolver import get_capability_resolver

    _reset_capability_state()
    bridge = SimpleNamespace(
        _lock=asyncio.Lock(),
        _devices={
            "android-test-02": SimpleNamespace(
                supported_actions=[],
                last_heartbeat=0.0,
            )
        },
    )

    response = await handle_capability_report(
        bridge,
        websocket=object(),
        message={
            "type": "capability_report",
            "device_id": "android-test-02",
            "platform": "android",
            "version": "4.0",
            "supported_actions": ["tap"],
            "capability_schemas": [
                {
                    "action": "tap",
                    "exec_mode": "local",
                    "tags": ["ui"],
                    "params": {"type": "object", "properties": {"x": {"type": "number"}}},
                    "returns": {"type": "object"},
                }
            ],
        },
    )

    record = get_capability_resolver().resolve_record("gateway__android-test-02__tap")

    assert response["accepted"] is True
    assert record is not None
    assert record.provider_id == "android-test-02"
    assert record.exec_mode == "local"
    assert record.tags == ["ui"]
    assert record.availability == CapabilityAvailability.AVAILABLE.value
    assert record.mutation_source == "android.capability_report"
    assert record.parameters["properties"]["x"]["type"] == "number"
    assert record.returns == {"type": "object"}


@pytest.mark.asyncio
async def test_capability_orchestrator_projects_from_canonical_registry():
    from core.agent.capability_registry import CapabilityRegistry
    from core.capability_orchestrator import CapabilityOrchestrator, CapabilityType
    from core.unified.capability_contract import CapabilityContract, CapabilitySource
    from core.unified.capability_resolver import get_capability_resolver

    _reset_capability_state()

    CapabilityRegistry.get_instance().register(
        CapabilityContract(
            name="skill__canon_projection_skill",
            description="Skill exposed through canonical registry",
            source=CapabilitySource.SKILL,
            source_id="canon_projection_skill",
            parameters={"type": "object", "properties": {}},
            metadata={
                "legacy_capability_id": "skill_canon_projection_skill",
                "legacy_name": "Canonical Projection Skill",
                "priority": 9,
            },
        )
    )
    get_capability_resolver().invalidate_cache()

    orch = CapabilityOrchestrator()
    await orch.initialize()

    caps = orch.list_capabilities()
    cap_ids = {cap["id"] for cap in caps}
    projected = orch.capabilities["skill_canon_projection_skill"]

    assert "skill_canon_projection_skill" in cap_ids
    assert projected.type == CapabilityType.SKILL
    assert projected.source == "canon_projection_skill"
    assert projected.name == "Canonical Projection Skill"
