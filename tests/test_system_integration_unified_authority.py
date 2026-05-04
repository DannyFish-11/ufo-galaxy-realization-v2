from __future__ import annotations

import pytest


def _reset_capability_state() -> None:
    from core.agent.capability_registry import CapabilityRegistry
    from core.system_integration import SystemIntegration
    from core.unified.capability_resolver import reset_capability_resolver

    reg = CapabilityRegistry.get_instance()
    reg._items.clear()
    reg._validation_errors.clear()
    reset_capability_resolver()
    SystemIntegration._instance = None


@pytest.mark.asyncio
async def test_system_integration_registers_into_canonical_registry_and_discovers_through_resolver():
    from core.agent.capability_registry import CapabilityRegistry
    from core.system_integration import CapabilityType, SystemIntegration

    _reset_capability_state()
    system = SystemIntegration.get_instance()

    async def _handler(**params):
        return {"ok": True, "params": params}

    system.register_capability(
        id="builtin_test",
        name="unified_test_cap",
        type=CapabilityType.BUILTIN,
        description="Unified test capability",
        handler=_handler,
        parameters={"type": "object", "properties": {"value": {"type": "string"}}},
    )

    registry_item = CapabilityRegistry.get_instance().get("unified_test_cap")
    discovered = await system.discover_capability("unified_test_cap")
    executed = await system.execute("unified_test_cap", value="hello")

    assert registry_item is not None
    assert discovered is not None
    assert discovered.name == "unified_test_cap"
    assert executed["ok"] is True
    assert executed["params"]["value"] == "hello"

