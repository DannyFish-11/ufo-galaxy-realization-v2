"""Desktop-native multimodal ingress backbone contract.

Formalises how desktop-native inputs enter and flow through the mainline:
runtime shell → session runtime → context assembly → task generation →
execution planning.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, Mapping, Optional

from core.realtime_streaming_backbone import build_realtime_streaming_backbone_contract

DESKTOP_NATIVE_MULTIMODAL_INGRESS_BACKBONE_AUTHORITY = (
    "DESKTOP_NATIVE_MULTIMODAL_INGRESS_BACKBONE::OPENCLAWD_MAINLINE_AUTHORITY_V1"
)
DESKTOP_NATIVE_MULTIMODAL_INGRESS_BACKBONE_SENTINEL = "DESKTOP_NATIVE_MULTIMODAL_INGRESS_BACKBONE::CONVERGENCE_PASS_V1"
# Backward-compatible aliases for existing imports.
DESKTOP_NATIVE_INGRESS_BACKBONE_AUTHORITY = DESKTOP_NATIVE_MULTIMODAL_INGRESS_BACKBONE_AUTHORITY
DESKTOP_NATIVE_INGRESS_BACKBONE_SENTINEL = DESKTOP_NATIVE_MULTIMODAL_INGRESS_BACKBONE_SENTINEL

MAINLINE_REQUIRED_MODALITIES = (
    "text",
    "image",
    "file",
    "screen_context",
    "foreground_context",
)
EXTENSION_MODALITIES = ("audio_speech", "camera_sensor")
DEGRADABLE_MODALITIES = ("audio_speech", "camera_sensor", "continuous_stream")
CONTINUOUS_MAINLINE_MODALITIES = ("continuous_stream",)
# File-input compatibility keys observed across request/context carriers:
# - files / uploaded_files: explicit upload bundles
# - file_paths / file_input: direct path-centric carrier styles
# - attachments: generic adapter-envelope attachment slot
FILE_INPUT_KEYS = ("files", "file_paths", "attachments", "uploaded_files", "file_input")
FOREGROUND_CONTEXT_KEYS = ("active_window", "ui_tree", "foreground_app", "window_title")


def _as_mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _context_items(context: Optional[Iterable[Any]]) -> Iterable[Dict[str, Any]]:
    for item in context or []:
        if isinstance(item, Mapping):
            yield dict(item)


def _extract_mm(multimodal_context: Optional[Any]) -> Dict[str, Any]:
    if multimodal_context is None:
        return {}
    if hasattr(multimodal_context, "model_dump"):
        try:
            dumped = multimodal_context.model_dump()
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            return {}
    return _as_mapping(multimodal_context)


def _count_file_inputs(
    *,
    context: Optional[Iterable[Any]],
    mm_dict: Dict[str, Any],
    kwargs: Mapping[str, Any],
) -> int:
    count = 0
    metadata = _as_mapping(mm_dict.get("metadata"))
    for key in FILE_INPUT_KEYS:
        value = metadata.get(key)
        if isinstance(value, (list, tuple)):
            count += len(value)
        elif value:
            count += 1

    for key in FILE_INPUT_KEYS:
        value = kwargs.get(key)
        if isinstance(value, (list, tuple)):
            count += len(value)
        elif value:
            count += 1

    for item in _context_items(context):
        for key in FILE_INPUT_KEYS:
            value = item.get(key)
            if isinstance(value, (list, tuple)):
                count += len(value)
            elif value:
                count += 1
    return count


def _extract_screen_context(mm_dict: Dict[str, Any], kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    # Precedence: multimodal_context.screen is canonical; kwargs.screen_context
    # serves as fallback when multimodal_context lacks screen payload.
    screen = _as_mapping(mm_dict.get("screen"))
    if not screen:
        screen = _as_mapping(kwargs.get("screen_context"))
    return screen


def _has_foreground_context(screen_ctx: Dict[str, Any], kwargs: Mapping[str, Any]) -> bool:
    for key in FOREGROUND_CONTEXT_KEYS:
        if screen_ctx.get(key) is not None:
            return True
        if kwargs.get(key) is not None:
            return True
    return False


def _has_continuous_stream(mm_dict: Dict[str, Any], kwargs: Mapping[str, Any]) -> bool:
    """Return True when stream markers indicate active continuous stream ingress.

    The bool() normalization is intentional: explicit falsy markers
    (False/0/"") mean stream-absent and are not treated as unknown.
    """
    metadata = _as_mapping(mm_dict.get("metadata"))
    for key in ("continuous_stream", "stream_session_active", "realtime_stream_active"):
        # Intentional bool() normalization: explicit falsy markers
        # (False/0/"") are treated as stream-absent, not as unknown.
        if bool(metadata.get(key)):
            return True
        if bool(kwargs.get(key)):
            return True
    return False


def _build_android_perception_ingress_snapshot(
    *,
    source: str,
    multimodal_context: Optional[Any],
) -> Dict[str, Any]:
    try:
        from core.android_perception_ingress_contract import (
            ANDROID_VISION_CARRIER_SOURCE,
            build_android_perception_ingress_context,
        )
    except (ImportError, ModuleNotFoundError):
        return {}
    if source != ANDROID_VISION_CARRIER_SOURCE:
        return {}
    snapshot = build_android_perception_ingress_context(
        source=source,
        multimodal_context=multimodal_context,
    )
    return dict(snapshot or {})


def build_desktop_native_ingress_backbone(
    *,
    message: str,
    source: str,
    multimodal_context: Optional[Any],
    context: Optional[Iterable[Any]],
    kwargs: Optional[Mapping[str, Any]] = None,
    conversation_session_id: str = "",
    control_session_id: str = "",
    runtime_attachment_session_id: str = "",
) -> Dict[str, Any]:
    """Build the formal desktop-native ingress backbone contract snapshot."""
    safe_kwargs = dict(kwargs or {})
    mm_dict = _extract_mm(multimodal_context)
    screen_ctx = _extract_screen_context(mm_dict, safe_kwargs)
    file_count = _count_file_inputs(context=context, mm_dict=mm_dict, kwargs=safe_kwargs)
    image_count = len(mm_dict.get("images") or [])
    has_text = bool((message or "").strip())
    has_screen = bool(screen_ctx)
    has_foreground = _has_foreground_context(screen_ctx, safe_kwargs)
    audio_count = len(mm_dict.get("audio") or [])
    has_sensor = bool(mm_dict.get("sensor"))
    has_stream = _has_continuous_stream(mm_dict, safe_kwargs)
    android_perception_ingress = _build_android_perception_ingress_snapshot(
        source=source,
        multimodal_context=multimodal_context,
    )
    has_android_perception = bool(android_perception_ingress)

    modalities = {
        "text": {"is_present": has_text, "count": 1 if has_text else 0, "tier": "mainline_required"},
        "image": {"is_present": image_count > 0, "count": image_count, "tier": "mainline_required"},
        "file": {"is_present": file_count > 0, "count": file_count, "tier": "mainline_required"},
        "screen_context": {"is_present": has_screen, "count": 1 if has_screen else 0, "tier": "mainline_required"},
        "foreground_context": {
            "is_present": has_foreground,
            "count": 1 if has_foreground else 0,
            "tier": "mainline_required",
        },
        "audio_speech": {"is_present": audio_count > 0, "count": audio_count, "tier": "extension"},
        "camera_sensor": {"is_present": has_sensor, "count": 1 if has_sensor else 0, "tier": "extension"},
        "continuous_stream": {
            "is_present": has_stream,
            "count": 1 if has_stream else 0,
            "tier": "mainline_continuous",
        },
        "android_perception": {
            "is_present": has_android_perception,
            "count": 1 if has_android_perception else 0,
            "tier": "extension",
        },
    }

    return {
        "authority": DESKTOP_NATIVE_MULTIMODAL_INGRESS_BACKBONE_AUTHORITY,
        "sentinel": DESKTOP_NATIVE_MULTIMODAL_INGRESS_BACKBONE_SENTINEL,
        "contract_version": 1,
        "carrier_source": source or "chat",
        "android_perception_ingress": android_perception_ingress,
        "modalities": modalities,
        "modality_tiers": {
            "mainline_required": list(MAINLINE_REQUIRED_MODALITIES),
            "mainline_continuous": list(CONTINUOUS_MAINLINE_MODALITIES),
            "extension_modalities": list(EXTENSION_MODALITIES),
            "degradable_modalities": list(DEGRADABLE_MODALITIES),
        },
        "mainline_path": {
            "input": {"entrypoint": "desktop_native_ingress", "carrier_source": source or "chat"},
            "runtime_shell": {
                "module": "core.desktop_presence_runtime",
                "entry_method": "DesktopPresenceRuntime.handle_request",
            },
            "session_runtime": {
                "conversation_session_id": conversation_session_id or "",
                "control_session_id": control_session_id or "",
                "runtime_attachment_session_id": runtime_attachment_session_id or "",
            },
            "context_assembly": {
                "module": "core.openclawd",
                "method": "OpenClawd.process",
                "canonical_perception_contract": "core.perception.canonical_perception_state",
            },
            "task_generation": {"authority": "OpenClawd", "task_event": "task_received"},
            "execution_planning": {
                "plan_builder": "OpenClawd._build_execution_plan",
                "unified_control_plan_builder": "OpenClawd._build_unified_control_plan",
            },
        },
        "presence_mode_coupling": {
            "static": {
                "input_policy": "silently_accept_discrete_inputs",
                "sampling_intensity": "low",
                "fusion_strategy": "minimal_context_staging",
                "action_priority": "deferred",
            },
            "liminal": {
                "input_policy": "accept_inputs_and_amplify_sensing",
                "sampling_intensity": "moderate",
                "fusion_strategy": "contextual_fusion_for_task_readiness",
                "action_priority": "medium",
                "transition_triggers": [
                    "text_intent_detected",
                    "screen_or_foreground_change_detected",
                    "multimodal_input_arrival",
                ],
            },
            "manifest": {
                "input_policy": "inputs_directly_shape_execution_and_results",
                "sampling_intensity": "focused",
                "fusion_strategy": "execution_aligned_fusion",
                "action_priority": "high",
                "transition_triggers": [
                    "execution_path_confirmed",
                    "task_plan_active",
                ],
            },
        },
        "stream_boundary": {
            "discrete_input_backbone": [
                "text",
                "image",
                "file",
                "screen_context",
                "foreground_context",
            ],
            "continuous_live_stream_backbone": [
                "continuous_stream",
                "webrtc_session_manager",
                "multimodal_ingress_bus.perception_frame",
                "perception_source_registry",
            ],
            "integration_policy": "streaming_is_continuous_branch_of_unified_backbone",
            "realtime_streaming_backbone": build_realtime_streaming_backbone_contract(),
        },
    }


def augment_ingress_backbone_for_control_core(
    ingress_backbone: Optional[Dict[str, Any]],
    *,
    canonical_perception: Optional[Dict[str, Any]] = None,
    multimodal_route_decision: Optional[Dict[str, Any]] = None,
    execution_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Attach control-core stage facts to an existing ingress backbone snapshot."""
    if not isinstance(ingress_backbone, dict):
        return None
    enriched = deepcopy(ingress_backbone)
    mainline = _as_mapping(enriched.get("mainline_path"))

    context_assembly = _as_mapping(mainline.get("context_assembly"))
    if isinstance(canonical_perception, dict):
        context_assembly["canonical_perception_active_modalities"] = list(
            canonical_perception.get("active_modalities") or []
        )
        context_assembly["requires_native_multimodal"] = bool(
            canonical_perception.get("requires_native_multimodal", False)
        )
        if isinstance(canonical_perception.get("multimodal_context_strategy"), dict):
            context_assembly["multimodal_context_strategy"] = dict(
                canonical_perception.get("multimodal_context_strategy") or {}
            )
        if canonical_perception.get("multimodal_route_bias"):
            context_assembly["multimodal_route_bias"] = canonical_perception.get("multimodal_route_bias")
        if canonical_perception.get("multimodal_route_tier"):
            context_assembly["multimodal_route_tier"] = canonical_perception.get("multimodal_route_tier")
    mainline["context_assembly"] = context_assembly

    task_generation = _as_mapping(mainline.get("task_generation"))
    if isinstance(multimodal_route_decision, dict):
        task_generation["multimodal_route_type"] = multimodal_route_decision.get("route_type")
        task_generation["multimodal_route_reason"] = multimodal_route_decision.get("route_reason")
        if multimodal_route_decision.get("route_bias"):
            task_generation["multimodal_route_bias"] = multimodal_route_decision.get("route_bias")
        if multimodal_route_decision.get("route_tier"):
            task_generation["multimodal_route_tier"] = multimodal_route_decision.get("route_tier")
        if isinstance(multimodal_route_decision.get("context_strategy_hint"), dict):
            task_generation["multimodal_context_strategy_hint"] = dict(
                multimodal_route_decision.get("context_strategy_hint") or {}
            )
    mainline["task_generation"] = task_generation

    execution_planning = _as_mapping(mainline.get("execution_planning"))
    if execution_path:
        execution_planning["resolved_execution_path"] = execution_path
    mainline["execution_planning"] = execution_planning

    enriched["mainline_path"] = mainline
    return enriched
