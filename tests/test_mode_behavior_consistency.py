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
    semantics = model["participation_semantics"]
    assert semantics["execution_participating"] is True
    assert semantics["operability_participating"] is False
    assert semantics["mode_semantics"]["local_mode_active"] is True


def test_unified_mode_model_cross_device_keeps_delegated_execution() -> None:
    model = build_unified_mode_model(
        selected_runtime="android_delegated",
        selected_device="android-cross-1",
        participation_tier="dispatch_eligible",
        device_mode="cross_device",
    )

    assert model["execution_location"] == "android_delegated"
    assert model["governance_state"] == "delegated_execution"
    semantics = model["participation_semantics"]
    assert semantics["operability_participating"] is True
    assert semantics["mode_semantics"]["delegated_execution_active"] is True


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
    semantics = payload["unified_mode_model"]["participation_semantics"]
    assert semantics["mode_semantics"]["local_mode_active"] is True


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
    semantics = payload["unified_mode_model"]["participation_semantics"]
    assert semantics["takeover_visible"] is True
    assert semantics["mode_semantics"]["takeover_active"] is True


# ---------------------------------------------------------------------------
# PR-9：fully_attached 语义对齐 —— operability_participating 修复
# ---------------------------------------------------------------------------


def test_fully_attached_is_operability_participating() -> None:
    """fully_attached 层级应视为可操作参与（dispatch 逻辑可选中该设备）。"""
    model = build_unified_mode_model(
        selected_runtime="android_delegated",
        selected_device="android-fa-1",
        participation_tier="fully_attached",
        device_mode="cross_device",
    )

    semantics = model["participation_semantics"]
    # fully_attached 在结构上已可被 dispatch 选中 → operability_participating 必须为 True
    assert semantics["operability_participating"] is True
    # 但模式门控尚未全部通过 → dispatch_gate_passed 必须为 False
    assert semantics["dispatch_gate_passed"] is False
    # tier_participating 也应为 True
    assert semantics["tier_participating"] is True


def test_dispatch_eligible_has_both_operability_and_gate_passed() -> None:
    """dispatch_eligible 层级应同时满足 operability_participating 与 dispatch_gate_passed。"""
    model = build_unified_mode_model(
        selected_runtime="android_delegated",
        selected_device="android-de-1",
        participation_tier="dispatch_eligible",
        device_mode="cross_device",
    )

    semantics = model["participation_semantics"]
    assert semantics["operability_participating"] is True
    assert semantics["dispatch_gate_passed"] is True


def test_distributed_participant_has_both_operability_and_gate_passed() -> None:
    """distributed_participant 层级应同时满足 operability_participating 与 dispatch_gate_passed。"""
    model = build_unified_mode_model(
        selected_runtime="android_delegated",
        selected_device="android-dp-1",
        participation_tier="distributed_participant",
        device_mode="cross_device",
    )

    semantics = model["participation_semantics"]
    assert semantics["operability_participating"] is True
    assert semantics["dispatch_gate_passed"] is True
    assert semantics["distributed_participating"] is True


def test_session_attached_tiers_are_not_operability_participating() -> None:
    """control_only / cross_device_capable 层级均不应视为可操作参与。"""
    for tier in ("control_only", "cross_device_capable"):
        model = build_unified_mode_model(
            selected_runtime="android_delegated",
            selected_device="android-sa-1",
            participation_tier=tier,
            device_mode="cross_device",
        )
        semantics = model["participation_semantics"]
        assert semantics["operability_participating"] is False, (
            f"tier={tier!r} 不应为 operability_participating=True"
        )
        assert semantics["dispatch_gate_passed"] is False, (
            f"tier={tier!r} 不应为 dispatch_gate_passed=True"
        )


def test_fully_attached_dispatch_gap_is_explicit_in_summary() -> None:
    """participation_semantics 摘要应明确暴露 dispatch_gate_passed 字段。"""
    model = build_unified_mode_model(
        selected_runtime="android_delegated",
        selected_device="android-fa-2",
        participation_tier="fully_attached",
        device_mode="cross_device",
    )

    semantics = model["participation_semantics"]
    assert "dispatch_gate_passed" in semantics
    summary_zh: str = semantics["participating_summary_zh"]
    summary_en: str = semantics["participating_summary_en"]
    assert "dispatch_gate_passed" in summary_en
    assert "派发门控通过" in summary_zh

