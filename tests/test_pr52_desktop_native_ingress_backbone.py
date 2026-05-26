from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.desktop_native_multimodal_ingress_contract import (
    DESKTOP_NATIVE_INGRESS_BACKBONE_AUTHORITY,
    DESKTOP_NATIVE_INGRESS_BACKBONE_SENTINEL,
    build_desktop_native_ingress_backbone,
)
from core.schemas.multimodal import MultiModalContext, MultiModalImage
from core.schemas.unified_control_plan import build_unified_control_plan


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
    assert "future_realtime_stream_extension_points" in stream_boundary
    assert "webrtc_session_manager" in stream_boundary["future_realtime_stream_extension_points"]


def test_backbone_detects_first_pass_desktop_modalities():
    mm = MultiModalContext(
        images=[MultiModalImage(mime="image/png", data="iVBORw0KGgo=", source="screenshot")],
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
    assert forwarded["mainline_path"]["runtime_shell"]["entry_method"] == "DesktopPresenceRuntime.handle_request"
    assert "desktop_native_ingress_backbone" in result["metadata"]


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
