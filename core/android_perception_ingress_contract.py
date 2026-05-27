"""Android perception ingress contract for V2 multimodal authority.

Defines a machine-verifiable contract that distinguishes:

1) one-shot Android vision requests (request-bound multimodal context), and
2) canonical Android multimodal participation (continuous participation intent).

V2 remains the multimodal authority in both cases.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

ANDROID_PERCEPTION_INGRESS_CONTRACT_SENTINEL: str = (
    "ANDROID_PERCEPTION_INGRESS_CONTRACT::v1 present"
)
ANDROID_PERCEPTION_CANONICAL_PROTOCOL: str = "ANDROID_PERCEPTION_INGRESS_PROTOCOL_V1"
ANDROID_PERCEPTION_CANONICAL_HANDLER: str = (
    "galaxy_gateway.android.handlers.vision.handle_vision_request"
)
ANDROID_PERCEPTION_CANONICAL_RUNTIME_ENTRY: str = (
    "core.desktop_presence_runtime.DesktopPresenceRuntime.handle_request"
)
ANDROID_PERCEPTION_TRUTH_CLOSURE_FIELD: str = (
    "ingress_carrier_context.android_perception_ingress_route"
)

V2_MULTIMODAL_AUTHORITY: str = "v2_multimodal_main_host"
ANDROID_VISION_CARRIER_SOURCE: str = "android_vision"

ANDROID_PERCEPTION_ONE_SHOT: str = "one_shot_request_bound"
ANDROID_PERCEPTION_CANONICAL: str = "canonical_multimodal_participation"

ANDROID_PERCEPTION_ROUTE_REQUEST_BOUND: str = "request_bound_multimodal_context"
ANDROID_PERCEPTION_ROUTE_INGRESS_BUS: str = "multimodal_ingress_bus"

ANDROID_PERCEPTION_PARTICIPATION_KEY: str = "android_perception_participation"
ANDROID_CANONICAL_OPT_IN_KEY: str = "android_canonical_multimodal_participation"


def _is_multimodal_ingest_enabled() -> bool:
    """Return whether shell-level MultimodalIngressBus is enabled by config."""
    try:
        from core.unified_config import config as _cfg

        return bool(_cfg.get("enable_multimodal_ingest", False))
    except Exception:
        return False


def _extract_mm_metadata(multimodal_context: Optional[Any]) -> Dict[str, Any]:
    if multimodal_context is None:
        return {}
    metadata = getattr(multimodal_context, "metadata", None)
    if isinstance(metadata, dict):
        return metadata
    return {}


def build_android_perception_payload_contract(
    *,
    device_id: str,
    mode: str,
    task_id: str,
    participation: str = ANDROID_PERCEPTION_ONE_SHOT,
) -> Dict[str, Any]:
    """Build canonical Android perception payload contract metadata."""
    participation_value = (
        participation
        if participation in {ANDROID_PERCEPTION_ONE_SHOT, ANDROID_PERCEPTION_CANONICAL}
        else ANDROID_PERCEPTION_ONE_SHOT
    )
    return {
        "schema_version": 1,
        "canonical_protocol": ANDROID_PERCEPTION_CANONICAL_PROTOCOL,
        "canonical_handler": ANDROID_PERCEPTION_CANONICAL_HANDLER,
        "canonical_runtime_entry": ANDROID_PERCEPTION_CANONICAL_RUNTIME_ENTRY,
        "canonical_truth_closure_field": ANDROID_PERCEPTION_TRUTH_CLOSURE_FIELD,
        "carrier": ANDROID_VISION_CARRIER_SOURCE,
        "capture_type": "screenshot",
        "device_id": device_id,
        "mode": mode,
        "task_id": task_id,
        "participation": participation_value,
        "default_ingress_route": ANDROID_PERCEPTION_ROUTE_REQUEST_BOUND,
        "canonical_requires_ingress_bus": True,
        "canonical_opt_in_key": ANDROID_CANONICAL_OPT_IN_KEY,
        "multimodal_authority": V2_MULTIMODAL_AUTHORITY,
    }


def build_android_perception_ingress_context(
    *,
    source: str,
    multimodal_context: Optional[Any],
) -> Dict[str, Any]:
    """Build Android perception ingress context fields for DPR result stamping."""
    if source != ANDROID_VISION_CARRIER_SOURCE:
        return {}

    metadata = _extract_mm_metadata(multimodal_context)
    participation = metadata.get(ANDROID_PERCEPTION_PARTICIPATION_KEY, "")
    canonical_requested = (
        participation == ANDROID_PERCEPTION_CANONICAL
        or metadata.get(ANDROID_CANONICAL_OPT_IN_KEY) is True
    )
    effective_participation = (
        ANDROID_PERCEPTION_CANONICAL
        if canonical_requested
        else ANDROID_PERCEPTION_ONE_SHOT
    )

    ingest_enabled = _is_multimodal_ingest_enabled()
    can_enter_ingress_bus = canonical_requested and ingest_enabled
    route = (
        ANDROID_PERCEPTION_ROUTE_INGRESS_BUS
        if can_enter_ingress_bus
        else ANDROID_PERCEPTION_ROUTE_REQUEST_BOUND
    )

    if canonical_requested and ingest_enabled:
        condition = "canonical_requested_and_ingest_enabled"
    elif canonical_requested:
        condition = "canonical_requested_but_ingest_disabled"
    else:
        condition = "default_one_shot_request_bound"

    return {
        "android_perception_canonical_protocol": ANDROID_PERCEPTION_CANONICAL_PROTOCOL,
        "android_perception_canonical_handler": ANDROID_PERCEPTION_CANONICAL_HANDLER,
        "android_perception_canonical_runtime_entry": ANDROID_PERCEPTION_CANONICAL_RUNTIME_ENTRY,
        "android_perception_truth_closure_field": ANDROID_PERCEPTION_TRUTH_CLOSURE_FIELD,
        "multimodal_authority": V2_MULTIMODAL_AUTHORITY,
        "android_perception_participation": effective_participation,
        "android_perception_ingress_route": route,
        "android_perception_can_enter_ingress_bus": bool(can_enter_ingress_bus),
        "android_perception_ingress_condition": condition,
    }
