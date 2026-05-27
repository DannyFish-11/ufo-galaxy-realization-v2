from __future__ import annotations

import inspect
import sys
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.android_perception_ingress_contract import (
    ANDROID_PERCEPTION_CANONICAL,
    ANDROID_PERCEPTION_CANONICAL_PROTOCOL,
    ANDROID_PERCEPTION_ROUTE_INGRESS_BUS,
)
from core.desktop_native_multimodal_ingress_contract import (
    DESKTOP_NATIVE_INGRESS_BACKBONE_AUTHORITY,
    DESKTOP_NATIVE_INGRESS_BACKBONE_SENTINEL,
    build_desktop_native_ingress_backbone,
)
from core.schemas.multimodal import MultiModalContext, MultiModalImage
from core.schemas.unified_control_plan import build_unified_control_plan

VALID_1X1_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4////fwAJ+wP+L6YxWQAAAABJRU5ErkJggg=="
)


def test_backbone_contract_sentinel_and_authority_present():
    contract = build_desktop_native_ingress_backbone(
        message="open files and inspect app window",
        source="chat",
        multimodal_context=None,
        context=[],
    )
    assert contract["authority"] == DESKTOP_NATIVE_INGRESS_BACKBONE_AUTHORITY
    assert contract["sentinel"] == DESKTOP_NATIVE_INGRESS_BACKBONE_SENTINEL


def test_backbone_mainline_modalities_and_presence_coupling_defined():
    contract = build_desktop_native_ingress_backbone(
        message="hello",
        source="chat",
        multimodal_context=None,
        context=[],
    )
    tiers = contract["modality_tiers"]
    assert "text" in tiers["mainline_required"]
    assert "image" in tiers["mainline_required"]
    assert "file" in tiers["mainline_required"]
    assert "screen_context" in tiers["mainline_required"]
    assert "foreground_context" in tiers["mainline_required"]
    assert "audio_speech" in tiers["extension_modalities"]

    coupling = contract["presence_mode_coupling"]
    assert set(coupling.keys()) == {"static", "liminal", "manifest"}
    assert "sampling_intensity" in coupling["static"]
    assert "sampling_intensity" in coupling["liminal"]
    assert "sampling_intensity" in coupling["manifest"]

    stream_boundary = contract["stream_boundary"]
    assert "continuous_live_stream_backbone" in stream_boundary
    assert "webrtc_session_manager" in stream_boundary["continuous_live_stream_backbone"]
    assert "realtime_streaming_backbone" in stream_boundary


def test_backbone_detects_first_pass_desktop_modalities():
    mm = MultiModalContext(
        images=[
            MultiModalImage(
                mime="image/png",
                data=VALID_1X1_PNG_BASE64,
                source="screenshot",
            )
        ],
        screen={
            "window_title": "Editor",
            "active_window": {"title": "Editor"},
            "ui_tree": {"root": "Window"},
            "foreground_app": "code",
        },
        metadata={"files": ["/tmp/a.txt"]},
    )
    contract = build_desktop_native_ingress_backbone(
        message="analyze this screen and file",
        source="chat",
        multimodal_context=mm,
        context=[{"attachments": ["/tmp/b.txt"]}],
    )
    mods = contract["modalities"]
    assert mods["text"]["is_present"] is True
    assert mods["image"]["is_present"] is True
    assert mods["file"]["is_present"] is True
    assert mods["screen_context"]["is_present"] is True
    assert mods["foreground_context"]["is_present"] is True
    assert mods["continuous_stream"]["is_present"] is False


def test_backbone_gracefully_handles_malformed_image_payload():
    mm = MultiModalContext(images=[MultiModalImage(mime="image/png", data="not-base64@@@", source="screenshot")])
    contract = build_desktop_native_ingress_backbone(
        message="check malformed image payload handling",
        source="chat",
        multimodal_context=mm,
        context=[],
    )
    assert contract["modalities"]["image"]["is_present"] is True
    assert contract["modalities"]["text"]["is_present"] is True


def test_backbone_detects_continuous_stream_branch_presence():
    contract = build_desktop_native_ingress_backbone(
        message="observe live desktop stream",
        source="chat",
        multimodal_context={"metadata": {"continuous_stream": True}},
        context=[],
    )
    assert contract["modalities"]["continuous_stream"]["is_present"] is True
    assert "mainline_continuous" in contract["modality_tiers"]


def test_android_originated_perception_enters_ingress_backbone_with_canonical_mapping():
    mm = MultiModalContext(
        images=[MultiModalImage(mime="image/png", data=VALID_1X1_PNG_BASE64, source="android_screen")],
        metadata={"android_perception_participation": ANDROID_PERCEPTION_CANONICAL},
    )
    with patch(
        "core.android_perception_ingress_contract._is_multimodal_ingest_enabled",
        return_value=True,
    ):
        contract = build_desktop_native_ingress_backbone(
            message="describe this android screen",
            source="android_vision",
            multimodal_context=mm,
            context=[],
        )
    android_ingress = contract["android_perception_ingress"]
    assert contract["modalities"]["android_perception"]["is_present"] is True
    assert android_ingress["android_perception_canonical_protocol"] == ANDROID_PERCEPTION_CANONICAL_PROTOCOL
    assert android_ingress["android_perception_ingress_route"] == ANDROID_PERCEPTION_ROUTE_INGRESS_BUS


def test_android_originated_nl_and_state_snapshot_enter_canonical_backbone():
    contract = build_desktop_native_ingress_backbone(
        message="帮我在手机上确认支付状态",
        source="android_goal_execution",
        multimodal_context={"metadata": {"android_state_snapshot": {"battery_level": 0.42}}},
        context=[],
        kwargs={
            "device_id": "android-01",
            "session_id": "session-android-01",
            "runtime_session_id": "trace-android-01",
            "entry_mode": "cross_device",
        },
    )
    android_nl = contract["android_nl_ingress"]
    assert contract["modalities"]["android_natural_language"]["is_present"] is True
    assert contract["modalities"]["android_device_context"]["is_present"] is True
    assert contract["modalities"]["android_state_snapshot"]["is_present"] is True
    assert android_nl["android_nl_semantic_authority"] == "v2_openclawd"
    assert android_nl["android_device_context"]["device_id"] == "android-01"
    assert android_nl["android_state_snapshot"]["battery_level"] == 0.42
    assert android_nl["android_mixed_context_present"] is True


def test_backbone_detects_continuous_stream_branch_from_kwargs():
    contract = build_desktop_native_ingress_backbone(
        message="observe live desktop stream",
        source="chat",
        multimodal_context={},
        context=[],
        kwargs={"stream_session_active": True},
    )
    assert contract["modalities"]["continuous_stream"]["is_present"] is True


def test_backbone_treats_falsy_continuous_stream_markers_as_absent():
    contract = build_desktop_native_ingress_backbone(
        message="observe live desktop stream",
        source="chat",
        multimodal_context={"metadata": {"continuous_stream": False}},
        context=[],
        kwargs={"stream_session_active": 0},
    )
    assert contract["modalities"]["continuous_stream"]["is_present"] is False


@pytest.mark.asyncio
async def test_runtime_shell_forwards_backbone_into_openclawd_and_result_metadata():
    from core.desktop_presence_runtime import DesktopPresenceRuntime

    runtime = DesktopPresenceRuntime()
    captured = {}

    async def _mock_process(**kwargs):
        captured.update(kwargs)
        return {"success": True, "response": "ok", "trace_id": "t-1", "metadata": {}}

    mm = MultiModalContext(
        images=[MultiModalImage(mime="image/png", data="abc", source="screenshot")],
        screen={"active_window": {"title": "Editor"}},
        metadata={"files": ["/tmp/x.txt"]},
    )

    with patch("core.openclawd.get_openclawd") as mock_get:
        clawd = MagicMock()
        clawd.process = AsyncMock(side_effect=_mock_process)
        mock_get.return_value = clawd
        result = await runtime.handle_request(
            message="inspect desktop",
            source="chat",
            context=[{"attachments": ["/tmp/y.txt"]}],
            multimodal_context=mm,
        )

    forwarded = captured.get("desktop_native_ingress_backbone")
    assert isinstance(forwarded, dict)
    assert captured.get("presence_mode") in {"manifest", "liminal", "static"}
    assert isinstance(captured.get("stream_runtime_status"), dict)
    assert forwarded["mainline_path"]["runtime_shell"]["entry_method"] == "DesktopPresenceRuntime.handle_request"
    assert "conversation_session_id" in forwarded["mainline_path"]["session_runtime"]
    assert forwarded["mainline_path"]["context_assembly"]["method"] == "OpenClawd.process"
    assert forwarded["mainline_path"]["task_generation"]["authority"] == "OpenClawd"
    assert (
        forwarded["mainline_path"]["execution_planning"]["unified_control_plan_builder"]
        == "OpenClawd._build_unified_control_plan"
    )
    assert "desktop_native_ingress_backbone" in result["metadata"]


def test_openclawd_route_consumes_presence_mode_and_ingress_signals():
    from core.openclawd import OpenClawd

    class _FakeRouter:
        def __init__(self):
            self.seen = {}

        def route_multimodal_first(self, *, active_modalities, task_type, complexity_score):
            self.seen = {
                "active_modalities": list(active_modalities),
                "complexity_score": complexity_score,
            }
            return SimpleNamespace(provider="fake", model="fake-mm", reason="tier=1 native")

    oc = OpenClawd.__new__(OpenClawd)
    router = _FakeRouter()
    oc._get_router = MagicMock(return_value=router)
    fake_multi_llm_router = SimpleNamespace(TaskType=SimpleNamespace(GENERAL="GENERAL"))
    with patch.dict(sys.modules, {"core.multi_llm_router": fake_multi_llm_router}):
        result = oc._select_multimodal_route(
            canonical_perception={"requires_native_multimodal": False, "active_modalities": []},
            desktop_native_ingress_backbone={
                "modalities": {
                    "screen_context": {"is_present": True},
                    "foreground_context": {"is_present": True},
                    "continuous_stream": {"is_present": False},
                }
            },
            presence_mode="manifest",
        )
    assert result["route_type"] == "native_multimodal"
    assert router.seen["complexity_score"] == 0.8
    assert "screen" in router.seen["active_modalities"]
    assert "foreground" in router.seen["active_modalities"]
    assert result["route_bias"] == "desktop_foreground_aware"
    assert result["route_tier"] == "foreground_context_priority"
    assert result["context_strategy_hint"]["screen_context_priority"] == "high"
    assert result["context_strategy_hint"]["foreground_context_priority"] == "high"


def test_openclawd_route_differs_when_stream_and_screen_backbone_present():
    from core.openclawd import OpenClawd

    class _FakeRouter:
        def __init__(self):
            self.calls = []

        def route_multimodal_first(self, *, active_modalities, task_type, complexity_score):
            self.calls.append(
                {
                    "active_modalities": list(active_modalities),
                    "complexity_score": complexity_score,
                    "task_type": task_type,
                }
            )
            return SimpleNamespace(provider="fake", model="fake-mm", reason="tier=1 native")

    oc = OpenClawd.__new__(OpenClawd)
    router = _FakeRouter()
    oc._get_router = MagicMock(return_value=router)
    fake_multi_llm_router = SimpleNamespace(TaskType=SimpleNamespace(GENERAL="GENERAL"))
    with patch.dict(sys.modules, {"core.multi_llm_router": fake_multi_llm_router}):
        baseline = oc._select_multimodal_route(
            canonical_perception={"requires_native_multimodal": False, "active_modalities": []},
            desktop_native_ingress_backbone={"modalities": {}},
            presence_mode="static",
        )
        guided = oc._select_multimodal_route(
            canonical_perception={"requires_native_multimodal": False, "active_modalities": []},
            desktop_native_ingress_backbone={
                "modalities": {
                    "screen_context": {"is_present": True},
                    "foreground_context": {"is_present": False},
                    "continuous_stream": {"is_present": True},
                },
                "presence_mode_coupling": {
                    "manifest": {
                        "sampling_intensity": "focused",
                        "fusion_strategy": "execution_aligned_fusion",
                    }
                },
            },
            presence_mode="manifest",
            stream_runtime_status={"stream_state": "active"},
        )
    assert baseline["route_type"] == "text_only"
    assert guided["route_type"] == "native_multimodal"
    assert guided["route_bias"] == "continuous_stream_aware"
    assert guided["route_tier"] == "continuous_stream_priority"
    assert guided["context_strategy_hint"]["continuous_stream_assisted"] is True
    assert guided["context_strategy_hint"]["screen_context_priority"] == "high"
    assert router.calls[-1]["complexity_score"] == 0.9
    assert router.calls[-1]["active_modalities"] == ["screen", "stream"]


def test_openclawd_route_differs_with_android_perception_ingress_signal():
    from core.openclawd import OpenClawd

    class _FakeRouter:
        def __init__(self):
            self.calls = []

        def route_multimodal_first(self, *, active_modalities, task_type, complexity_score):
            self.calls.append(
                {
                    "active_modalities": list(active_modalities),
                    "complexity_score": complexity_score,
                    "task_type": task_type,
                }
            )
            return SimpleNamespace(provider="fake", model="fake-mm", reason="tier=1 native")

    oc = OpenClawd.__new__(OpenClawd)
    router = _FakeRouter()
    oc._get_router = MagicMock(return_value=router)
    fake_multi_llm_router = SimpleNamespace(TaskType=SimpleNamespace(GENERAL="GENERAL"))
    with patch.dict(sys.modules, {"core.multi_llm_router": fake_multi_llm_router}):
        baseline = oc._select_multimodal_route(
            canonical_perception={"requires_native_multimodal": False, "active_modalities": []},
            desktop_native_ingress_backbone={"modalities": {}},
            presence_mode="static",
        )
        android_guided = oc._select_multimodal_route(
            canonical_perception={"requires_native_multimodal": False, "active_modalities": []},
            desktop_native_ingress_backbone={
                "modalities": {"android_perception": {"is_present": True}},
                "android_perception_ingress": {
                    "android_perception_ingress_route": "multimodal_ingress_bus",
                },
            },
            presence_mode="liminal",
        )
    assert baseline["route_type"] == "text_only"
    assert android_guided["route_type"] == "native_multimodal"
    assert android_guided["route_bias"] == "android_perception_ingress_aware"
    assert android_guided["route_tier"] == "android_perception_ingress_bus_priority"
    assert android_guided["context_strategy_hint"]["android_perception_priority"] == "high"
    assert android_guided["context_strategy_hint"]["android_perception_route"] == "multimodal_ingress_bus"
    assert router.calls[-1]["active_modalities"] == ["screen"]


def test_openclawd_route_degrades_when_continuous_stream_reconnecting():
    from core.openclawd import OpenClawd

    oc = OpenClawd.__new__(OpenClawd)
    oc._get_router = MagicMock()
    result = oc._select_multimodal_route(
        canonical_perception={"requires_native_multimodal": False, "active_modalities": []},
        desktop_native_ingress_backbone={"modalities": {"continuous_stream": {"is_present": True}}},
        stream_runtime_status={"stream_state": "reconnecting"},
    )
    assert result["route_type"] == "text_only"
    assert "discrete_fallback" in result["fallback_reason"]
    oc._get_router.assert_not_called()
    assert result["route_bias"] == "continuous_stream_aware"
    assert result["context_strategy_hint"]["continuous_stream_assisted"] is False


def test_multimodal_ingress_decision_applies_context_strategy_before_augment():
    from core.openclawd import OpenClawd

    oc = OpenClawd.__new__(OpenClawd)
    call_order = []
    route_result = {
        "route_type": "native_multimodal",
        "route_bias": "continuous_stream_aware",
        "route_tier": "continuous_stream_priority",
        "context_strategy_hint": {
            "screen_context_priority": "high",
            "foreground_context_priority": "normal",
            "continuous_stream_assisted": True,
            "sampling_intensity": "focused",
            "fusion_strategy": "execution_aligned_fusion",
        },
    }

    def _fake_select(**kwargs):
        call_order.append(
            ("select", kwargs["desktop_native_ingress_backbone"]["modalities"]["continuous_stream"]["is_present"])
        )
        return dict(route_result)

    def _fake_apply(**kwargs):
        call_order.append(("apply_context", kwargs["multimodal_route_decision"]["route_bias"]))
        return (
            kwargs["kernel_message"] + "\n\n[desktop_context_strategy continuous_stream_assisted=true]",
            {
                **(kwargs["canonical_perception"] or {}),
                "multimodal_context_strategy": dict(kwargs["multimodal_route_decision"]["context_strategy_hint"]),
                "multimodal_route_bias": kwargs["multimodal_route_decision"]["route_bias"],
                "multimodal_route_tier": kwargs["multimodal_route_decision"]["route_tier"],
            },
        )

    def _fake_augment(backbone, *, canonical_perception=None, multimodal_route_decision=None, execution_path=None):
        call_order.append(("augment", multimodal_route_decision["route_bias"]))
        return {
            "route_bias_seen": multimodal_route_decision["route_bias"],
            "context_strategy_seen": canonical_perception["multimodal_context_strategy"]["continuous_stream_assisted"],
        }

    oc._select_multimodal_route = MagicMock(side_effect=_fake_select)
    oc._apply_multimodal_context_strategy = MagicMock(side_effect=_fake_apply)
    oc._augment_desktop_native_ingress_backbone = MagicMock(side_effect=_fake_augment)

    route, kernel_message, canonical_perception, ingress_for_plan = oc._resolve_multimodal_ingress_decision(
        kernel_message="inspect desktop",
        canonical_perception={"requires_native_multimodal": False, "active_modalities": []},
        task_type=None,
        desktop_native_ingress_backbone={
            "modalities": {
                "screen_context": {"is_present": True},
                "continuous_stream": {"is_present": True},
            }
        },
        presence_mode="manifest",
        stream_runtime_status={"stream_state": "active"},
    )

    assert [step for step, *_ in call_order] == ["select", "apply_context", "augment"]
    assert route["route_bias"] == "continuous_stream_aware"
    assert canonical_perception["multimodal_context_strategy"]["continuous_stream_assisted"] is True
    assert "desktop_context_strategy" in kernel_message
    assert ingress_for_plan["route_bias_seen"] == "continuous_stream_aware"
    assert ingress_for_plan["context_strategy_seen"] is True


def test_context_strategy_hint_updates_kernel_message_and_backbone_context_assembly():
    from core.desktop_native_multimodal_ingress_contract import augment_ingress_backbone_for_control_core
    from core.openclawd import OpenClawd

    kernel_message, canonical_perception = OpenClawd._apply_multimodal_context_strategy(
        kernel_message="inspect desktop",
        canonical_perception={"active_modalities": ["screen"]},
        multimodal_route_decision={
            "route_bias": "desktop_foreground_aware",
            "route_tier": "foreground_context_priority",
            "context_strategy_hint": {
                "screen_context_priority": "high",
                "foreground_context_priority": "high",
                "continuous_stream_assisted": False,
                "sampling_intensity": "focused",
                "fusion_strategy": "execution_aligned_fusion",
            },
        },
    )

    augmented = augment_ingress_backbone_for_control_core(
        {"mainline_path": {"context_assembly": {}, "task_generation": {}, "execution_planning": {}}},
        canonical_perception=canonical_perception,
        multimodal_route_decision={
            "route_type": "native_multimodal",
            "route_reason": "tier=1 native",
            "route_bias": "desktop_foreground_aware",
            "route_tier": "foreground_context_priority",
            "context_strategy_hint": canonical_perception["multimodal_context_strategy"],
        },
    )

    assert "desktop_context_strategy" in kernel_message
    assert "foreground_context_priority=high" in kernel_message
    assert canonical_perception["multimodal_route_bias"] == "desktop_foreground_aware"
    assert (
        augmented["mainline_path"]["context_assembly"]["multimodal_context_strategy"]["foreground_context_priority"]
        == "high"
    )
    assert augmented["mainline_path"]["task_generation"]["multimodal_route_bias"] == "desktop_foreground_aware"


def test_android_nl_context_changes_context_strategy_and_execution_planning():
    from core.openclawd import OpenClawd

    oc = OpenClawd.__new__(OpenClawd)
    backbone_base = {
        "mainline_path": {"context_assembly": {}, "task_generation": {}, "execution_planning": {}},
        "modalities": {},
    }
    route, kernel_message, _canonical_perception, ingress_for_plan = oc._resolve_multimodal_ingress_decision(
        kernel_message="执行任务",
        canonical_perception={"requires_native_multimodal": False, "active_modalities": []},
        task_type=None,
        desktop_native_ingress_backbone=deepcopy(backbone_base),
        presence_mode="liminal",
    )
    assert route["route_type"] == "text_only"
    assert "android_nl_priority=high" not in kernel_message
    assert "android_context_plan_mode" not in ingress_for_plan["mainline_path"]["execution_planning"]

    android_backbone = {
        "mainline_path": {"context_assembly": {}, "task_generation": {}, "execution_planning": {}},
        "modalities": {
            "android_natural_language": {"is_present": True},
            "android_device_context": {"is_present": True},
            "android_state_snapshot": {"is_present": True},
        },
        "android_nl_ingress": {
            "android_nl_semantic_authority": "v2_openclawd",
            "android_device_context": {"device_id": "android-01", "session_id": "session-01"},
            "android_state_snapshot": {"network": "wifi"},
        },
    }
    route2, kernel_message2, canonical_perception2, ingress_for_plan2 = oc._resolve_multimodal_ingress_decision(
        kernel_message="执行任务",
        canonical_perception={"requires_native_multimodal": False, "active_modalities": []},
        task_type=None,
        desktop_native_ingress_backbone=android_backbone,
        presence_mode="liminal",
    )
    assert route2["route_type"] == "text_only"
    assert "android_nl_priority=high" in kernel_message2
    assert "android_state_snapshot_present=true" in kernel_message2
    assert canonical_perception2["multimodal_context_strategy"]["android_state_snapshot_present"] is True
    assert (
        ingress_for_plan2["mainline_path"]["execution_planning"]["android_context_plan_mode"]
        == "android_state_aware"
    )
    assert ingress_for_plan2["mainline_path"]["task_generation"]["android_nl_participation"] == "enabled"
    assert (
        ingress_for_plan2["mainline_path"]["context_assembly"]["android_nl_ingress"]["android_nl_semantic_authority"]
        == "v2_openclawd"
    )


def test_visible_action_surface_filter_hides_operator_payload_for_non_operator():
    from core.openclawd import OpenClawd

    payload = {
        "success": False,
        "error": "permission denied",
        "execution_result": {"skipped_reason": "blocked_action"},
        "metadata": {
            "execution_path": "none",
            "runtime_decision_reasoning": {"debug": True},
            "task_truth": {"state": "blocked"},
            "permission_safety_state": {"any_permission_missing": True},
            "mode": "chat_only",
        },
    }
    filtered = OpenClawd._apply_visible_action_surface_filter(
        deepcopy(payload),
        is_operator_request=False,
    )
    assert "runtime_decision_reasoning" not in filtered["metadata"]
    assert "task_truth" not in filtered["metadata"]
    assert "minimal_necessary_explanation" in filtered["metadata"]

    unfiltered = OpenClawd._apply_visible_action_surface_filter(
        deepcopy(payload),
        is_operator_request=True,
    )
    assert "runtime_decision_reasoning" in unfiltered["metadata"]


def test_openclawd_process_signature_accepts_desktop_native_ingress_backbone():
    from core.openclawd import OpenClawd

    sig = inspect.signature(OpenClawd.process)
    assert "desktop_native_ingress_backbone" in sig.parameters


def test_unified_control_plan_carries_desktop_native_ingress_backbone():
    plan = build_unified_control_plan(
        trace_id="trace-dni",
        desktop_native_ingress_backbone={
            "authority": DESKTOP_NATIVE_INGRESS_BACKBONE_AUTHORITY,
            "mainline_path": {"execution_planning": {"resolved_execution_path": "local"}},
        },
    )
    d = plan.to_dict()
    assert "desktop_native_ingress_backbone" in d
    assert d["desktop_native_ingress_backbone"]["authority"] == DESKTOP_NATIVE_INGRESS_BACKBONE_AUTHORITY
