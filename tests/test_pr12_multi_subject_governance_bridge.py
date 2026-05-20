#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_bridge_sentinel_and_takeover_continuation():
    from core.multi_subject_truth_convergence_bridge import (
        MULTI_SUBJECT_TRUTH_CONVERGENCE_BRIDGE_AUTHORITY,
        build_multi_subject_truth_bridge,
    )

    assert "CANONICAL_GOVERNANCE_V1" in MULTI_SUBJECT_TRUTH_CONVERGENCE_BRIDGE_AUTHORITY

    formation = {
        "primary_execution_device_id": "dev-primary",
        "members": [
            {"device_id": "dev-primary", "role": "primary_execution_device"},
            {"device_id": "dev-fallback", "role": "fallback_device"},
            {"device_id": "dev-assistant", "role": "support_device"},
        ],
    }
    results = [
        {"device_id": "dev-primary", "success": False, "error": "device offline"},
        {"device_id": "dev-fallback", "success": True},
        {"device_id": "dev-assistant", "success": True},
    ]

    with patch(
        "core.multi_subject_truth_convergence_bridge._derive_signal",
        return_value={
            "readiness": "ready",
            "posture": "join_runtime",
            "busy": False,
            "orchestration_eligible": True,
            "reasons": [],
        },
    ):
        bridge = build_multi_subject_truth_bridge(
            formation=formation,
            participant_results=results,
            source_device_id="dev-primary",
        )

    assert bridge["participant_roles"]["dev-fallback"] == "takeover_candidate"
    assert bridge["failure_isolation"]["lost"] == ["dev-primary"]
    assert bridge["closure"]["completion_state"] == "takeover_continuation"


@pytest.mark.asyncio
async def test_device_router_attaches_truth_bridge_for_partial_cross_device():
    from galaxy_gateway.device_router import DeviceRouter

    router = DeviceRouter()
    devices = []
    for did in ["dev-a", "dev-b"]:
        d = MagicMock()
        d.device_id = did
        devices.append(d)

    async def _fake_dispatch(_task, device):
        if device.device_id == "dev-a":
            return {"success": True, "device_id": "dev-a"}
        return {"success": False, "device_id": "dev-b", "error": "device offline"}

    router.dispatch_task = _fake_dispatch
    task = {
        "task_id": "task-pr12-router",
        "trace_id": "trace-pr12-router",
        "source_device_id": "dev-source",
        "source_runtime_posture": "join_runtime",
    }

    with patch(
        "core.multi_subject_truth_convergence_bridge._derive_signal",
        return_value={
            "readiness": "ready",
            "posture": "join_runtime",
            "busy": False,
            "orchestration_eligible": True,
            "reasons": [],
        },
    ):
        result = await router._dispatch_cross_device_task(task, devices, _substrate_caller="test")

    assert "truth_convergence_bridge" in result
    assert result["completion_state"] in {
        "degraded_completion",
        "partial_success",
        "takeover_continuation",
    }
    assert "participant_roles" in result
    assert "failure_isolation" in result


@pytest.mark.asyncio
async def test_cross_device_coordinator_attaches_truth_bridge():
    from galaxy_gateway.cross_device_coordinator import CrossDeviceCoordinator

    coordinator = CrossDeviceCoordinator()

    async def _fake_generic(_command, _context):
        return {"success": True, "message": "ok"}

    coordinator._execute_generic_cross_device_task = _fake_generic
    context = {
        "task_id": "task-pr12-coordinator",
        "trace_id": "trace-pr12-coordinator",
        "source_device_id": "dev-source",
        "target_device_ids": ["dev-target"],
        "device_id": "dev-target",
        "source_runtime_posture": "join_runtime",
    }

    with patch(
        "core.multi_subject_truth_convergence_bridge._derive_signal",
        return_value={
            "readiness": "ready",
            "posture": "join_runtime",
            "busy": False,
            "orchestration_eligible": True,
            "reasons": [],
        },
    ):
        result = await coordinator.execute_cross_device_task("share clipboard", context, _substrate_caller="test")

    assert result.get("completion_state") in {
        "success",
        "takeover_continuation",
        "degraded_completion",
    }
    assert "truth_convergence_bridge" in result
    assert "participant_roles" in result
