"""
tests/test_android_device_state_store.py
==========================================
Unit tests for core.android_device_state_store.

Tests:
- DeviceStateSnapshot parsing (snake_case and camelCase keys)
- DeviceStateSnapshot.is_local_ai_ready() logic
- DeviceStateSnapshot.readiness_summary()
- DeviceStateSnapshot.to_dict() serialisation
- DeviceExecutionEvent parsing
- DeviceExecutionEvent.to_dict() serialisation
- Store ingress: absorb_device_state_snapshot
- Store ingress: absorb_device_execution_event
- Store queries: get_device_state_snapshot, list_device_state_snapshots
- Store queries: list_recent_execution_events (with filters)
- get_device_ecosystem_summary structure
- Test isolation via reset_android_device_state_store
"""
from __future__ import annotations

import time

import pytest

from core.android_device_state_store import (
    ANDROID_DEVICE_STATE_STORE_AUTHORITY,
    DEVICE_EXECUTION_EVENT_MSG_TYPE,
    DEVICE_STATE_SNAPSHOT_MSG_TYPE,
    DeviceExecutionEvent,
    DeviceStateSnapshot,
    absorb_device_execution_event,
    absorb_device_state_snapshot,
    get_android_device_state_store,
    get_device_ecosystem_summary,
    get_device_state_snapshot,
    list_device_state_snapshots,
    reset_android_device_state_store,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_store():
    """Reset the store singleton before each test."""
    reset_android_device_state_store()
    yield
    reset_android_device_state_store()


# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------


def test_authority_sentinel_present():
    assert "ANDROID_DEVICE_STATE_STORE_V1" in ANDROID_DEVICE_STATE_STORE_AUTHORITY


def test_message_type_constants():
    assert DEVICE_STATE_SNAPSHOT_MSG_TYPE == "device_state_snapshot"
    assert DEVICE_EXECUTION_EVENT_MSG_TYPE == "device_execution_event"


# ---------------------------------------------------------------------------
# DeviceStateSnapshot: parsing — snake_case keys
# ---------------------------------------------------------------------------


def test_parse_state_snapshot_snake_case():
    payload = {
        "llama_cpp_available": True,
        "ncnn_available": False,
        "active_runtime_type": "LLAMA_CPP",
        "model_ready": True,
        "accessibility_ready": True,
        "overlay_ready": True,
        "local_loop_ready": True,
        "model_id": "mobilevlm_v2_7b",
        "runtime_type": "LLAMA_CPP",
        "checksum_ok": True,
        "compatibility_ok": True,
        "quantization": "q4_k_m",
        "model_version": "v2.0",
        "mobilevlm_present": True,
        "mobilevlm_checksum_ok": True,
        "seeclick_present": False,
        "pending_first_download": False,
        "offline_queue_depth": 0,
        "current_fallback_tier": "local_planner",
        "planner_fallback_tier": "local",
        "grounding_fallback_tier": "center",
        "warmup_result": "ok",
        "degraded_reasons": ["no_seeclick"],
    }
    snap = absorb_device_state_snapshot("dev_1", payload)
    assert snap.device_id == "dev_1"
    assert snap.llama_cpp_available is True
    assert snap.ncnn_available is False
    assert snap.active_runtime_type == "LLAMA_CPP"
    assert snap.model_ready is True
    assert snap.accessibility_ready is True
    assert snap.overlay_ready is True
    assert snap.local_loop_ready is True
    assert snap.model_id == "mobilevlm_v2_7b"
    assert snap.runtime_type == "LLAMA_CPP"
    assert snap.checksum_ok is True
    assert snap.compatibility_ok is True
    assert snap.quantization == "q4_k_m"
    assert snap.model_version == "v2.0"
    assert snap.mobilevlm_present is True
    assert snap.mobilevlm_checksum_ok is True
    assert snap.seeclick_present is False
    assert snap.pending_first_download is False
    assert snap.offline_queue_depth == 0
    assert snap.current_fallback_tier == "local_planner"
    assert snap.planner_fallback_tier == "local"
    assert snap.grounding_fallback_tier == "center"
    assert snap.warmup_result == "ok"
    assert snap.degraded_reasons == ["no_seeclick"]


def test_parse_state_snapshot_camelcase_keys():
    """Parser must accept camelCase keys from Android JSON serialisation."""
    payload = {
        "llamaCppAvailable": True,
        "ncnnAvailable": True,
        "activeRuntimeType": "NCNN",
        "modelReady": True,
        "accessibilityReady": False,
        "overlayReady": True,
        "localLoopReady": False,
        "modelId": "mobilevlm_lite",
        "runtimeType": "NCNN",
        "checksumOk": True,
        "compatibilityOk": False,
        "pendingFirstDownload": True,
        "offlineQueueDepth": 5,
        "currentFallbackTier": "center_delegated",
        "warmupResult": "failed",
        "degradedReasons": ["checksum_mismatch"],
    }
    snap = absorb_device_state_snapshot("dev_2", payload)
    assert snap.llama_cpp_available is True
    assert snap.ncnn_available is True
    assert snap.active_runtime_type == "NCNN"
    assert snap.model_ready is True
    assert snap.accessibility_ready is False
    assert snap.local_loop_ready is False
    assert snap.model_id == "mobilevlm_lite"
    assert snap.compatibility_ok is False
    assert snap.pending_first_download is True
    assert snap.offline_queue_depth == 5
    assert snap.current_fallback_tier == "center_delegated"
    assert snap.warmup_result == "failed"
    assert snap.degraded_reasons == ["checksum_mismatch"]


def test_parse_state_snapshot_missing_keys():
    """Parser must handle entirely empty payload without raising."""
    snap = absorb_device_state_snapshot("dev_empty", {})
    assert snap.device_id == "dev_empty"
    assert snap.llama_cpp_available is None
    assert snap.model_ready is None
    assert snap.degraded_reasons == []


# ---------------------------------------------------------------------------
# DeviceStateSnapshot: is_local_ai_ready
# ---------------------------------------------------------------------------


def test_is_local_ai_ready_all_true():
    snap = absorb_device_state_snapshot("d1", {
        "local_loop_ready": True,
        "model_ready": True,
        "llama_cpp_available": True,
    })
    assert snap.is_local_ai_ready() is True


def test_is_local_ai_ready_ncnn_path():
    snap = absorb_device_state_snapshot("d2", {
        "local_loop_ready": True,
        "model_ready": True,
        "llama_cpp_available": False,
        "ncnn_available": True,
    })
    assert snap.is_local_ai_ready() is True


def test_is_local_ai_ready_missing_model():
    snap = absorb_device_state_snapshot("d3", {
        "local_loop_ready": True,
        "model_ready": False,
        "llama_cpp_available": True,
    })
    assert snap.is_local_ai_ready() is False


def test_is_local_ai_ready_no_runtime():
    snap = absorb_device_state_snapshot("d4", {
        "local_loop_ready": True,
        "model_ready": True,
        "llama_cpp_available": False,
        "ncnn_available": False,
    })
    assert snap.is_local_ai_ready() is False


def test_is_local_ai_ready_all_none():
    snap = absorb_device_state_snapshot("d5", {})
    assert snap.is_local_ai_ready() is False


# ---------------------------------------------------------------------------
# DeviceStateSnapshot: readiness_summary
# ---------------------------------------------------------------------------


def test_readiness_summary_fields():
    snap = absorb_device_state_snapshot("d6", {
        "model_ready": True,
        "accessibility_ready": True,
        "overlay_ready": False,
        "local_loop_ready": True,
        "llama_cpp_available": True,
        "pending_first_download": False,
        "degraded_reasons": [],
    })
    summary = snap.readiness_summary()
    assert summary["model_ready"] is True
    assert summary["accessibility_ready"] is True
    assert summary["overlay_ready"] is False
    assert summary["local_loop_ready"] is True
    assert summary["local_ai_ready"] is True
    assert summary["llama_cpp_available"] is True
    assert summary["pending_first_download"] is False
    assert summary["degraded_reasons"] == []


# ---------------------------------------------------------------------------
# DeviceStateSnapshot: to_dict serialisation
# ---------------------------------------------------------------------------


def test_to_dict_contains_required_keys():
    snap = absorb_device_state_snapshot("d7", {"model_ready": True})
    d = snap.to_dict()
    required = [
        "device_id", "absorbed_at", "llama_cpp_available", "ncnn_available",
        "model_ready", "accessibility_ready", "overlay_ready", "local_loop_ready",
        "model_id", "runtime_type", "checksum_ok", "offline_queue_depth",
        "current_fallback_tier", "warmup_result", "degraded_reasons",
    ]
    for key in required:
        assert key in d, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# DeviceExecutionEvent: parsing
# ---------------------------------------------------------------------------


def test_parse_execution_event_snake_case():
    payload = {
        "flow_id": "flow_abc123",
        "task_id": "task_xyz456",
        "phase": "grounding",
        "step_index": 3,
        "is_blocking": False,
        "blocking_reason": "",
        "stagnation_detected": False,
        "fallback_tier": None,
    }
    evt = absorb_device_execution_event("dev_1", payload)
    assert evt.device_id == "dev_1"
    assert evt.flow_id == "flow_abc123"
    assert evt.task_id == "task_xyz456"
    assert evt.phase == "grounding"
    assert evt.step_index == 3
    assert evt.is_blocking is False
    assert evt.stagnation_detected is False


def test_parse_execution_event_camelcase():
    payload = {
        "flowId": "flow_camel",
        "taskId": "task_camel",
        "phase": "stagnation",
        "stepIndex": 7,
        "isBlocking": True,
        "blockingReason": "too_many_retries",
        "stagnationDetected": True,
        "fallbackTier": "center_delegated",
    }
    evt = absorb_device_execution_event("dev_c", payload)
    assert evt.flow_id == "flow_camel"
    assert evt.task_id == "task_camel"
    assert evt.phase == "stagnation"
    assert evt.step_index == 7
    assert evt.is_blocking is True
    assert evt.blocking_reason == "too_many_retries"
    assert evt.stagnation_detected is True
    assert evt.fallback_tier == "center_delegated"


def test_parse_execution_event_defaults():
    evt = absorb_device_execution_event("dev_e", {})
    assert evt.flow_id == ""
    assert evt.phase == "unknown"
    assert evt.step_index == -1
    assert evt.is_blocking is False


def test_execution_event_to_dict():
    evt = absorb_device_execution_event("dev_f", {
        "flow_id": "f1", "phase": "planning", "step_index": 0,
    })
    d = evt.to_dict()
    assert d["device_id"] == "dev_f"
    assert d["flow_id"] == "f1"
    assert d["phase"] == "planning"
    assert d["step_index"] == 0


# ---------------------------------------------------------------------------
# Store queries
# ---------------------------------------------------------------------------


def test_get_device_state_snapshot_after_absorb():
    absorb_device_state_snapshot("q_dev", {"model_ready": True})
    snap = get_device_state_snapshot("q_dev")
    assert snap is not None
    assert snap.device_id == "q_dev"
    assert snap.model_ready is True


def test_get_device_state_snapshot_missing():
    assert get_device_state_snapshot("no_such_device") is None


def test_list_device_state_snapshots_empty():
    snaps = list_device_state_snapshots()
    assert snaps == []


def test_list_device_state_snapshots_multiple():
    absorb_device_state_snapshot("dev_a", {"model_ready": True})
    absorb_device_state_snapshot("dev_b", {"model_ready": False})
    snaps = list_device_state_snapshots()
    ids = {s.device_id for s in snaps}
    assert "dev_a" in ids
    assert "dev_b" in ids


def test_latest_snapshot_replaces_previous():
    absorb_device_state_snapshot("replace_dev", {"model_ready": False})
    absorb_device_state_snapshot("replace_dev", {"model_ready": True})
    snap = get_device_state_snapshot("replace_dev")
    assert snap.model_ready is True


def test_list_recent_execution_events():
    store = get_android_device_state_store()
    absorb_device_execution_event("ev_dev", {"flow_id": "f1", "phase": "planning"})
    absorb_device_execution_event("ev_dev", {"flow_id": "f2", "phase": "grounding"})
    events = store.list_recent_execution_events()
    assert len(events) >= 2


def test_list_recent_execution_events_filter_by_flow():
    store = get_android_device_state_store()
    absorb_device_execution_event("ev_dev2", {"flow_id": "flow_x", "phase": "planning"})
    absorb_device_execution_event("ev_dev2", {"flow_id": "flow_y", "phase": "execution"})
    events = store.list_recent_execution_events(flow_id="flow_x")
    assert all(e.flow_id == "flow_x" for e in events)


def test_list_recent_execution_events_filter_by_device():
    store = get_android_device_state_store()
    absorb_device_execution_event("dev_A", {"flow_id": "f1", "phase": "planning"})
    absorb_device_execution_event("dev_B", {"flow_id": "f2", "phase": "execution"})
    events = store.list_recent_execution_events(device_id="dev_A")
    assert all(e.device_id == "dev_A" for e in events)


# ---------------------------------------------------------------------------
# get_device_ecosystem_summary
# ---------------------------------------------------------------------------


def test_ecosystem_summary_empty():
    summary = get_device_ecosystem_summary()
    assert summary["total_devices_with_snapshot"] == 0
    assert summary["local_ai_ready_count"] == 0
    assert summary["devices"] == []


def test_ecosystem_summary_counts():
    # 2 devices: 1 local-AI-ready, 1 not
    absorb_device_state_snapshot("eco_1", {
        "local_loop_ready": True, "model_ready": True, "llama_cpp_available": True,
    })
    absorb_device_state_snapshot("eco_2", {
        "local_loop_ready": False, "model_ready": False, "llama_cpp_available": False,
    })
    summary = get_device_ecosystem_summary()
    assert summary["total_devices_with_snapshot"] == 2
    assert summary["local_ai_ready_count"] == 1
    assert len(summary["devices"]) == 2


def test_ecosystem_summary_device_shape():
    absorb_device_state_snapshot("shape_dev", {
        "model_ready": True,
        "model_id": "mbvlm",
        "offline_queue_depth": 2,
    })
    summary = get_device_ecosystem_summary()
    device = next(d for d in summary["devices"] if d["device_id"] == "shape_dev")
    assert "readiness" in device
    assert "model" in device
    assert device["model"]["model_id"] == "mbvlm"
    assert device["offline_queue_depth"] == 2


def test_ecosystem_summary_exposes_dispatch_capability_status_split():
    absorb_device_state_snapshot("status_dev", {
        "model_ready": True,
        "local_loop_ready": False,
        "mobilevlm_present": True,
        "mobilevlm_checksum_ok": True,
        "seeclick_present": False,
    })
    summary = get_device_ecosystem_summary()
    device = next(d for d in summary["devices"] if d["device_id"] == "status_dev")
    status = device["dispatch_capability_status"]
    assert "authoritative_scoring_fields" in status
    assert "capability_presence_only_fields" in status
    assert status["authoritative_scoring_fields"]["model_ready"] is True
    assert status["capability_presence_only_fields"]["mobilevlm_present"] is True
    assert "mobilevlm_present" in status["capability_presence_only_field_names"]


def test_ecosystem_pending_first_download_count():
    absorb_device_state_snapshot("pfd_1", {"pending_first_download": True})
    absorb_device_state_snapshot("pfd_2", {"pending_first_download": False})
    summary = get_device_ecosystem_summary()
    assert summary["pending_first_download_count"] == 1


# ---------------------------------------------------------------------------
# Test isolation
# ---------------------------------------------------------------------------


def test_reset_clears_all_state():
    absorb_device_state_snapshot("iso_dev", {"model_ready": True})
    reset_android_device_state_store()
    assert get_device_state_snapshot("iso_dev") is None
    assert list_device_state_snapshots() == []
