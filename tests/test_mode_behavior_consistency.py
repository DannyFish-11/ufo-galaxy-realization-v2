from __future__ import annotations

from core.runtime_decision_reasoning import overlay_runtime_decision_reasoning_block
from core.v2_unified_mode_model import build_unified_mode_model


def test_unified_mode_model_local_mode_overrides_delegated_runtime_to_android_local() -> None:
    model = build_unified_mode_model(
        selected_runtime="android_delegated",
        selected_device="android-local-1",
        participation_tier="local_only",
        device_mode="local",
    )

    assert model["execution_location"] == "android_local"
    assert model["governance_state"] == "local_autonomy"


def test_unified_mode_model_cross_device_keeps_delegated_execution() -> None:
    model = build_unified_mode_model(
        selected_runtime="android_delegated",
        selected_device="android-cross-1",
        participation_tier="dispatch_eligible",
        device_mode="cross_device",
    )

    assert model["execution_location"] == "android_delegated"
    assert model["governance_state"] == "delegated_execution"


def test_runtime_decision_reasoning_local_mode_uses_android_local_runtime() -> None:
    payload = overlay_runtime_decision_reasoning_block(
        None,
        selected_device="android-local-2",
        mode_state="local",
        android_truth_block={
            "device_id": "android-local-2",
            "device_mode": "local",
            "participation_tier": "local_only",
            "mode_readiness_state": "ready",
        },
    )

    assert payload["selected_runtime"] == "android_local"
    assert payload["unified_mode_model"]["execution_location"] == "android_local"
    assert payload["unified_mode_model"]["governance_state"] == "local_autonomy"


def test_runtime_decision_reasoning_takeover_updates_governance_state() -> None:
    payload = overlay_runtime_decision_reasoning_block(
        None,
        selected_device="android-cross-2",
        mode_state="cross_device",
        android_truth_block={
            "device_id": "android-cross-2",
            "device_mode": "cross_device",
            "participation_tier": "dispatch_eligible",
            "mode_readiness_state": "ready",
        },
        governance_state={
            "devices": [
                {
                    "device_id": "android-cross-2",
                    "takeover_active": True,
                }
            ]
        },
    )

    assert payload["selected_runtime"] == "android_delegated"
    assert payload["unified_mode_model"]["governance_state"] == "takeover_active"
