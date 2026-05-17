from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_builtin_cross_device_prefers_canonical_device_router_path():
    from core.capability_orchestrator import Capability, CapabilityOrchestrator, CapabilityType

    orch = CapabilityOrchestrator()
    cap = Capability(
        id="builtin_cross_device",
        name="跨设备协同",
        description="跨设备任务",
        type=CapabilityType.BUILTIN,
    )

    with patch(
        "galaxy_gateway.device_router.device_router.route_task",
        new_callable=AsyncMock,
    ) as mock_route, patch(
        "galaxy_gateway.cross_device_coordinator.cross_device_coordinator.execute_cross_device_task",
        new_callable=AsyncMock,
    ) as mock_legacy:
        mock_route.return_value = {"success": True, "message": "ok", "via": "device_router"}
        result = await orch._execute_builtin(cap, {"message": "sync", "device_id": "android-1"})

    mock_route.assert_awaited_once()
    command, context = mock_route.await_args.args
    assert command == "sync"
    assert context["route_mode"] == "cross_device"
    assert context["source_device_id"] == "android-1"
    mock_legacy.assert_not_awaited()
    assert result["success"] is True
    assert result["data"]["via"] == "device_router"


@pytest.mark.asyncio
async def test_builtin_cross_device_keeps_compatibility_fallback_explicit():
    from core.capability_orchestrator import Capability, CapabilityOrchestrator, CapabilityType

    orch = CapabilityOrchestrator()
    cap = Capability(
        id="builtin_cross_device",
        name="跨设备协同",
        description="跨设备任务",
        type=CapabilityType.BUILTIN,
    )

    with patch(
        "galaxy_gateway.device_router.device_router.route_task",
        new_callable=AsyncMock,
    ) as mock_route, patch(
        "galaxy_gateway.cross_device_coordinator.cross_device_coordinator.execute_cross_device_task",
        new_callable=AsyncMock,
    ) as mock_legacy:
        mock_route.side_effect = RuntimeError("router unavailable")
        mock_legacy.return_value = {"success": True, "message": "compat"}
        result = await orch._execute_builtin(cap, {"command": "sync", "device_id": "android-2"})

    mock_route.assert_awaited_once()
    mock_legacy.assert_awaited_once()
    legacy_args, legacy_kwargs = mock_legacy.await_args
    assert legacy_args[0] == "sync"
    assert legacy_args[1]["route_mode"] == "cross_device_compat_fallback"
    assert legacy_args[1]["_compat_legacy_bypass"] == "capability_orchestrator.builtin_cross_device"
    assert legacy_kwargs["_substrate_caller"] == "capability_orchestrator.compat_fallback"
    assert result["success"] is True
    assert result["reply"] == "compat"
