from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch


def _ready_gate_result() -> SimpleNamespace:
    return SimpleNamespace(
        dispatch_ready=True,
        status="ready",
        reason="",
        blocking_notes=[],
        transport_alive=True,
        registered=True,
        registration_gaps=[],
        attachment_state="active",
        runtime_session_id="rt-1",
        runtime_attachment_session_id="att-1",
    )


def test_dispatch_slot_strict_blocks_require_review_continuity() -> None:
    from core.canonical_dispatch_slot_authority import evaluate_canonical_dispatch_slot

    with (
        patch(
            "core.canonical_dispatch_slot_authority._eval_base_readiness_gate",
            return_value=_ready_gate_result(),
        ),
        patch(
            "core.canonical_dispatch_slot_authority._eval_continuity_legality",
            return_value=("require_review", ["continuity unavailable"]),
        ),
    ):
        slot = evaluate_canonical_dispatch_slot(
            "dev-1",
            "cross_device",
            authority_mode="strict",
        )

    assert slot.slot_approved is False
    assert slot.blocking_dimension == "continuity_legality"


def test_dispatch_slot_compat_allows_require_review_continuity() -> None:
    from core.canonical_dispatch_slot_authority import evaluate_canonical_dispatch_slot

    with (
        patch(
            "core.canonical_dispatch_slot_authority._eval_base_readiness_gate",
            return_value=_ready_gate_result(),
        ),
        patch(
            "core.canonical_dispatch_slot_authority._eval_continuity_legality",
            return_value=("require_review", ["continuity unavailable"]),
        ),
        patch(
            "core.canonical_dispatch_slot_authority._eval_execution_mode_eligibility",
            return_value=(True, []),
        ),
        patch(
            "core.canonical_dispatch_slot_authority._eval_occupancy",
            return_value=(True, []),
        ),
        patch(
            "core.canonical_dispatch_slot_authority._eval_policy_allowance",
            return_value=(True, []),
        ),
    ):
        slot = evaluate_canonical_dispatch_slot(
            "dev-1",
            "cross_device",
            authority_mode="compat",
        )

    assert slot.slot_approved is True


def test_unified_result_ingress_blocks_require_review_in_strict_mode_only() -> None:
    from core.unified_result_ingress import (
        NormalizedResultEvent,
        ResultSourceChannel,
        UnifiedResultIngress,
    )

    ingress = UnifiedResultIngress()
    event = NormalizedResultEvent(
        task_id="t1",
        device_id="d1",
        raw_message_type="task_result",
        normalized_result_kind="task_result",
        normalized_status="completed",
        source_channel=ResultSourceChannel.DELEGATED,
        payload={},
    )

    with (
        patch.object(ingress, "_check_continuity_legality", return_value="require_review"),
        patch.object(ingress, "_resolve_continuity_mode", return_value="strict"),
    ):
        strict_outcome = ingress.process(event)
    assert strict_outcome.continuity_rejected is True

    with (
        patch.object(ingress, "_check_continuity_legality", return_value="require_review"),
        patch.object(ingress, "_resolve_continuity_mode", return_value="compat"),
        patch.object(ingress, "_check_idempotency", return_value=True),
    ):
        compat_outcome = ingress.process(event)
    assert compat_outcome.continuity_rejected is False
    assert compat_outcome.was_deduplicated is True


def test_runtime_truth_ingress_require_review_mode_behavior() -> None:
    from core.unified_runtime_truth_ingress import ingest_android_runtime_state_update

    msg = {
        "type": "participant_truth_update",
        "device_id": "d1",
        "canonical_governance_mode": "strict",
    }
    with patch(
        "core.unified_runtime_truth_ingress._check_runtime_ingress_continuity",
        return_value=("require_review", True),
    ):
        strict_outcome = ingest_android_runtime_state_update(msg)
    assert strict_outcome.routed_path == "rejected"
    assert strict_outcome.continuity_rejected is True

    compat_msg = dict(msg)
    compat_msg["canonical_governance_mode"] = "compat"
    fake_sub = SimpleNamespace(was_reconciled=True, reject_reason="")
    with (
        patch(
            "core.unified_runtime_truth_ingress._check_runtime_ingress_continuity",
            return_value=("require_review", False),
        ),
        patch(
            "core.android_participant_truth_ingress.ingest_android_participant_truth_message",
            return_value=fake_sub,
        ),
    ):
        compat_outcome = ingest_android_runtime_state_update(compat_msg)
    assert compat_outcome.routed_path == "participant_truth"
    assert compat_outcome.closure_accepted is False
