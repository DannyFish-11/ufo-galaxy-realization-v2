from unittest.mock import patch

from core.android_perception_ingress_contract import (
    ANDROID_PERCEPTION_CANONICAL,
    ANDROID_PERCEPTION_CANONICAL_HANDLER,
    ANDROID_PERCEPTION_CANONICAL_PROTOCOL,
    ANDROID_PERCEPTION_CANONICAL_RUNTIME_ENTRY,
    ANDROID_PERCEPTION_INGRESS_CONTRACT_SENTINEL,
    ANDROID_PERCEPTION_ONE_SHOT,
    ANDROID_PERCEPTION_ROUTE_INGRESS_BUS,
    ANDROID_PERCEPTION_ROUTE_REQUEST_BOUND,
    ANDROID_PERCEPTION_TRUTH_CLOSURE_FIELD,
    ANDROID_VISION_CARRIER_SOURCE,
    build_android_perception_ingress_context,
    build_android_perception_payload_contract,
)
from core.schemas.multimodal import MultiModalContext


def test_contract_sentinel_present():
    assert ANDROID_PERCEPTION_INGRESS_CONTRACT_SENTINEL


def test_payload_contract_defaults_to_one_shot_request_bound():
    payload = build_android_perception_payload_contract(
        device_id="android-01",
        mode="full",
        task_id="task-1",
    )
    assert payload["carrier"] == ANDROID_VISION_CARRIER_SOURCE
    assert payload["participation"] == ANDROID_PERCEPTION_ONE_SHOT
    assert payload["default_ingress_route"] == ANDROID_PERCEPTION_ROUTE_REQUEST_BOUND
    assert payload["canonical_protocol"] == ANDROID_PERCEPTION_CANONICAL_PROTOCOL
    assert payload["canonical_handler"] == ANDROID_PERCEPTION_CANONICAL_HANDLER
    assert payload["canonical_runtime_entry"] == ANDROID_PERCEPTION_CANONICAL_RUNTIME_ENTRY
    assert payload["canonical_truth_closure_field"] == ANDROID_PERCEPTION_TRUTH_CLOSURE_FIELD


def test_ingress_context_for_canonical_participation_respects_ingest_gate():
    mm_context = MultiModalContext(
        metadata={"android_perception_participation": ANDROID_PERCEPTION_CANONICAL}
    )

    with patch(
        "core.android_perception_ingress_contract._is_multimodal_ingest_enabled",
        return_value=False,
    ):
        disabled_ctx = build_android_perception_ingress_context(
            source="android_vision",
            multimodal_context=mm_context,
        )
    assert (
        disabled_ctx["android_perception_ingress_route"]
        == ANDROID_PERCEPTION_ROUTE_REQUEST_BOUND
    )

    with patch(
        "core.android_perception_ingress_contract._is_multimodal_ingest_enabled",
        return_value=True,
    ):
        enabled_ctx = build_android_perception_ingress_context(
            source="android_vision",
            multimodal_context=mm_context,
        )
    assert (
        enabled_ctx["android_perception_ingress_route"]
        == ANDROID_PERCEPTION_ROUTE_INGRESS_BUS
    )
    assert (
        enabled_ctx["android_perception_canonical_protocol"]
        == ANDROID_PERCEPTION_CANONICAL_PROTOCOL
    )
    assert (
        enabled_ctx["android_perception_canonical_handler"]
        == ANDROID_PERCEPTION_CANONICAL_HANDLER
    )
