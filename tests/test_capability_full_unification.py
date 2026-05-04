from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _reset_capability_state() -> None:
    from core.agent.capability_registry import CapabilityRegistry
    from core.capability_orchestrator import CapabilityOrchestrator
    from core.unified.capability_resolver import reset_capability_resolver
    from galaxy_gateway.capability_registry import GatewayCapabilityRegistry

    reg = CapabilityRegistry.get_instance()
    reg._items.clear()
    reg._validation_errors.clear()
    reset_capability_resolver()
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
