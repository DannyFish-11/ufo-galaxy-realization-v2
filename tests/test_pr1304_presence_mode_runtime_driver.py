from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_runtime_propagates_presence_runtime_hint_into_openclawd_main_path():
    from core.desktop_presence_runtime import DesktopPresenceRuntime
    from core.desktop_presence_system import DesktopPresenceMode

    runtime = DesktopPresenceRuntime()
    runtime._presence_state_machine.simulate_elapsed_time_for_testing(1.0)
    runtime._presence_state_machine._MIN_MODE_HOLD_MS[DesktopPresenceMode.LIMINAL] = 0
    captured = {}

    async def _mock_process(**kwargs):
        captured.update(kwargs)
        return {"success": True, "response": "ok", "metadata": {}}

    with patch("core.openclawd.get_openclawd") as mock_get:
        clawd = MagicMock()
        clawd.process = AsyncMock(side_effect=_mock_process)
        mock_get.return_value = clawd

        result = await runtime.handle_request(message="inspect desktop", source="chat")

    hint = captured["presence_runtime_hint"]
    assert captured["presence_mode"] == "manifest"
    assert hint["presence_mode"] == "manifest"
    assert hint["previous_presence_mode"] == "liminal"
    assert hint["presence_mode_changed"] is True
    assert hint["presence_transition_reason"] == "execution_path_confirmed_and_running"
    assert result["metadata"]["presence_mode"] == "manifest"
    assert result["metadata"]["presence_runtime_hint"]["presence_mode"] == "manifest"


def test_presence_mode_changes_route_bias_and_context_strategy_without_ingress_signals():
    from core.openclawd import OpenClawd

    class _FakeRouter:
        def __init__(self):
            self.calls = []

        def route_multimodal_first(self, *, active_modalities, task_type, complexity_score):
            self.calls.append(
                {
                    "active_modalities": list(active_modalities),
                    "task_type": task_type,
                    "complexity_score": complexity_score,
                }
            )
            return SimpleNamespace(provider="fake", model="fake-mm", reason="tier=1 native")

    oc = OpenClawd.__new__(OpenClawd)
    router = _FakeRouter()
    oc._get_router = MagicMock(return_value=router)
    fake_multi_llm_router = SimpleNamespace(TaskType=SimpleNamespace(GENERAL="GENERAL"))

    with patch.dict(sys.modules, {"core.multi_llm_router": fake_multi_llm_router}):
        static_route = oc._select_multimodal_route(
            canonical_perception={"requires_native_multimodal": True, "active_modalities": ["screen"]},
            desktop_native_ingress_backbone={"modalities": {}},
            presence_mode="static",
            presence_runtime_hint={
                "presence_mode": "static",
                "previous_presence_mode": "static",
                "presence_mode_changed": False,
                "presence_transition_reason": "mode_stable",
            },
        )
        manifest_route = oc._select_multimodal_route(
            canonical_perception={"requires_native_multimodal": True, "active_modalities": ["screen"]},
            desktop_native_ingress_backbone={"modalities": {}},
            presence_mode="manifest",
            presence_runtime_hint={
                "presence_mode": "manifest",
                "previous_presence_mode": "liminal",
                "presence_mode_changed": True,
                "presence_transition_reason": "execution_path_confirmed_and_running",
            },
        )

    _, static_perception = OpenClawd._apply_multimodal_context_strategy(
        kernel_message="inspect desktop",
        canonical_perception={"active_modalities": ["screen"]},
        multimodal_route_decision=static_route,
    )
    manifest_message, manifest_perception = OpenClawd._apply_multimodal_context_strategy(
        kernel_message="inspect desktop",
        canonical_perception={"active_modalities": ["screen"]},
        multimodal_route_decision=manifest_route,
    )

    assert static_route["route_bias"] == "presence_static_conservative"
    assert static_route["route_tier"] == "presence_static_background"
    assert manifest_route["route_bias"] == "presence_manifest_ready"
    assert manifest_route["route_tier"] == "presence_manifest_priority_transition"
    assert router.calls[0]["complexity_score"] == 0.35
    assert router.calls[1]["complexity_score"] == 0.8
    assert static_perception["multimodal_context_strategy"]["execution_readiness"] == "deferred"
    assert manifest_perception["multimodal_context_strategy"]["execution_readiness"] == "high"
    assert "presence_transition=liminal_to_manifest" in manifest_message


def test_presence_transition_signal_is_consumed_by_context_strategy():
    from core.openclawd import OpenClawd

    route = {
        "route_bias": "presence_manifest_ready",
        "route_tier": "presence_manifest_priority_transition",
        "context_strategy_hint": {
            "screen_context_priority": "normal",
            "foreground_context_priority": "normal",
            "continuous_stream_assisted": False,
            "sampling_intensity": "focused",
            "fusion_strategy": "execution_aligned_fusion",
            "execution_readiness": "high",
            "presence_mode": "manifest",
            "previous_presence_mode": "liminal",
            "presence_mode_changed": True,
            "presence_transition_reason": "execution_path_confirmed_and_running",
        },
    }

    kernel_message, canonical_perception = OpenClawd._apply_multimodal_context_strategy(
        kernel_message="inspect desktop",
        canonical_perception={"active_modalities": ["screen"]},
        multimodal_route_decision=route,
    )

    assert canonical_perception["multimodal_context_strategy"]["presence_mode_changed"] is True
    assert (
        canonical_perception["multimodal_context_strategy"]["presence_transition_reason"]
        == "execution_path_confirmed_and_running"
    )
    assert "execution_readiness=high" in kernel_message
    assert "presence_transition=liminal_to_manifest" in kernel_message
