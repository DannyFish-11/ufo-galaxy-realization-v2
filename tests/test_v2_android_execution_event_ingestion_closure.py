"""tests/test_v2_android_execution_event_ingestion_closure.py
==============================================================
PR-2 V2 companion: Android execution-event ingestion, storage, and
flow/operator projection closure — regression tests.

Proves the full V2 receive/store/project/expose path for realistic current
Android ``DEVICE_EXECUTION_EVENT`` payloads on the canonical Android→V2 path.

Test sections
-------------
A.  Realistic camelCase Android execution-event payload is absorbed and all
    fields are stored correctly (including the new ``event_ts`` field).

B.  ``step_index`` / ``stepIndex`` with ``None`` value does not raise —
    parser coerces to ``-1``.

C.  ``event_ts`` is captured from Android-side ``event_ts``, ``eventTs``,
    and ``timestamp`` keys.

D.  ``to_dict()`` exposes ``event_ts`` in the serialised form.

E.  ``_forward_execution_event_to_flow_surface`` writes entity metadata
    keys ``_last_android_execution_event``, ``_last_android_phase``, and
    ``_last_android_event_absorbed_at`` when the flow entity is known.

F.  ``_forward_execution_event_to_flow_surface`` uses ``event_ts`` (not
    ``absorbed_at``) as ``android_ts`` in the forwarded
    ``AndroidCanonicalExecutionEvent``.

G.  ``FlowLevelOperatorSurface._derive_android_execution_phase`` returns the
    correct phase from entity metadata after execution events are absorbed —
    this is the critical Gap 1 fix.

H.  ``FlowLevelOperatorSurface.inspect_flow`` reflects the absorbed Android
    execution phase in ``current_execution_phase`` and populates
    ``last_android_execution_event``.

I.  handler ``handle_device_execution_event`` returns a structured ACK
    with ``status: "absorbed"`` for a realistic full execution-event payload.

J.  ``GET /api/v1/operator/devices/execution-events`` supports optional
    ``flow_id`` and ``device_id`` query params for filtering.

K.  ``GET /api/v1/operator/devices/execution-events`` returns ``event_ts``
    in each event dict.

L.  End-to-end bridge dispatch → store → entity metadata → inspect_flow
    path for a realistic Android execution-event message.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.android_device_state_store import (
    absorb_device_execution_event,
    get_android_device_state_store,
    reset_android_device_state_store,
)
from core.flow_level_operator_surface import (
    AndroidExecutionPhase,
    get_flow_level_operator_surface,
    reset_flow_level_operator_surface,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REALISTIC_SNAKE_PAYLOAD: Dict[str, Any] = {
    "flow_id": "flow_e2e_snake_001",
    "task_id": "task_e2e_snake_001",
    "phase": "grounding",
    "step_index": 3,
    "is_blocking": False,
    "blocking_reason": "",
    "stagnation_detected": False,
    "fallback_tier": "local",
    "event_ts": 1_700_000_100.5,
}

_REALISTIC_CAMEL_PAYLOAD: Dict[str, Any] = {
    "flowId": "flow_e2e_camel_001",
    "taskId": "task_e2e_camel_001",
    "phase": "stagnation",
    "stepIndex": 7,
    "isBlocking": True,
    "blockingReason": "too_many_retries",
    "stagnationDetected": True,
    "fallbackTier": "center_delegated",
    "eventTs": 1_700_000_200.0,
}


def _make_fake_entity(flow_id: str) -> MagicMock:
    """Return a minimal fake DelegatedFlowEntity with a mutable metadata dict."""
    entity = MagicMock()
    entity.identity.delegated_flow_id = flow_id
    entity.phase.value = "active"
    entity.phase.is_active.return_value = True
    entity.metadata = {}
    return entity


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset():
    """Reset singletons before and after each test."""
    reset_android_device_state_store()
    reset_flow_level_operator_surface()
    yield
    reset_android_device_state_store()
    reset_flow_level_operator_surface()


# ---------------------------------------------------------------------------
# A. Realistic snake_case payload parsing
# ---------------------------------------------------------------------------


class TestRealisticPayloadParsing:
    def test_A01_snake_case_all_fields_stored(self):
        evt = absorb_device_execution_event("dev_a01", _REALISTIC_SNAKE_PAYLOAD)
        assert evt.device_id == "dev_a01"
        assert evt.flow_id == "flow_e2e_snake_001"
        assert evt.task_id == "task_e2e_snake_001"
        assert evt.phase == "grounding"
        assert evt.step_index == 3
        assert evt.is_blocking is False
        assert evt.blocking_reason == ""
        assert evt.stagnation_detected is False
        assert evt.fallback_tier == "local"
        assert evt.event_ts == pytest.approx(1_700_000_100.5)

    def test_A02_camel_case_all_fields_stored(self):
        evt = absorb_device_execution_event("dev_a02", _REALISTIC_CAMEL_PAYLOAD)
        assert evt.flow_id == "flow_e2e_camel_001"
        assert evt.task_id == "task_e2e_camel_001"
        assert evt.phase == "stagnation"
        assert evt.step_index == 7
        assert evt.is_blocking is True
        assert evt.blocking_reason == "too_many_retries"
        assert evt.stagnation_detected is True
        assert evt.fallback_tier == "center_delegated"
        assert evt.event_ts == pytest.approx(1_700_000_200.0)

    def test_A03_empty_payload_uses_defaults(self):
        evt = absorb_device_execution_event("dev_a03", {})
        assert evt.flow_id == ""
        assert evt.phase == "unknown"
        assert evt.step_index == -1
        assert evt.is_blocking is False
        assert evt.stagnation_detected is False
        assert evt.event_ts is None

    def test_A04_event_stored_in_ring_buffer(self):
        absorb_device_execution_event("dev_a04", _REALISTIC_SNAKE_PAYLOAD)
        store = get_android_device_state_store()
        events = store.list_recent_execution_events(flow_id="flow_e2e_snake_001")
        assert len(events) >= 1
        assert events[0].phase == "grounding"


# ---------------------------------------------------------------------------
# B. step_index None safety
# ---------------------------------------------------------------------------


class TestStepIndexNoneSafety:
    def test_B01_step_index_key_none_gives_minus_one(self):
        """step_index key present but None must not raise TypeError."""
        payload = {"flow_id": "f1", "phase": "execution", "step_index": None}
        evt = absorb_device_execution_event("dev_b01", payload)
        assert evt.step_index == -1

    def test_B02_step_index_camel_none_gives_minus_one(self):
        payload = {"flowId": "f2", "phase": "planning", "stepIndex": None}
        evt = absorb_device_execution_event("dev_b02", payload)
        assert evt.step_index == -1

    def test_B03_step_index_string_int_coerced(self):
        """step_index supplied as string should be coerced to int."""
        payload = {"flow_id": "f3", "phase": "grounding", "step_index": "5"}
        evt = absorb_device_execution_event("dev_b03", payload)
        assert evt.step_index == 5

    def test_B04_step_index_invalid_string_gives_minus_one(self):
        payload = {"flow_id": "f4", "phase": "grounding", "step_index": "not_a_number"}
        evt = absorb_device_execution_event("dev_b04", payload)
        assert evt.step_index == -1


# ---------------------------------------------------------------------------
# C. event_ts capture from multiple source keys
# ---------------------------------------------------------------------------


class TestEventTsCapture:
    def test_C01_event_ts_snake(self):
        evt = absorb_device_execution_event(
            "dev_c01", {"phase": "execution", "event_ts": 1234567.8}
        )
        assert evt.event_ts == pytest.approx(1234567.8)

    def test_C02_event_ts_camel(self):
        evt = absorb_device_execution_event(
            "dev_c02", {"phase": "execution", "eventTs": 9876543.21}
        )
        assert evt.event_ts == pytest.approx(9876543.21)

    def test_C03_timestamp_key_fallback(self):
        evt = absorb_device_execution_event(
            "dev_c03", {"phase": "planning", "timestamp": 1111111.0}
        )
        assert evt.event_ts == pytest.approx(1111111.0)

    def test_C04_no_ts_key_gives_none(self):
        evt = absorb_device_execution_event("dev_c04", {"phase": "planning"})
        assert evt.event_ts is None

    def test_C05_invalid_ts_gives_none(self):
        evt = absorb_device_execution_event(
            "dev_c05", {"phase": "planning", "event_ts": "not_a_float"}
        )
        assert evt.event_ts is None


# ---------------------------------------------------------------------------
# D. to_dict exposes event_ts
# ---------------------------------------------------------------------------


class TestEventTsInToDict:
    def test_D01_to_dict_has_event_ts_when_set(self):
        evt = absorb_device_execution_event(
            "dev_d01", {"phase": "grounding", "event_ts": 5000.0}
        )
        d = evt.to_dict()
        assert "event_ts" in d
        assert d["event_ts"] == pytest.approx(5000.0)

    def test_D02_to_dict_event_ts_none_when_not_set(self):
        evt = absorb_device_execution_event("dev_d02", {"phase": "planning"})
        d = evt.to_dict()
        assert "event_ts" in d
        assert d["event_ts"] is None

    def test_D03_to_dict_required_fields_present(self):
        evt = absorb_device_execution_event("dev_d03", _REALISTIC_CAMEL_PAYLOAD)
        d = evt.to_dict()
        for key in (
            "device_id", "absorbed_at", "flow_id", "task_id", "phase",
            "step_index", "is_blocking", "blocking_reason",
            "stagnation_detected", "fallback_tier", "event_ts",
        ):
            assert key in d, f"Missing key in to_dict(): {key!r}"


# ---------------------------------------------------------------------------
# E. _forward_execution_event_to_flow_surface writes entity metadata
# ---------------------------------------------------------------------------


class TestForwardWritesEntityMetadata:
    def test_E01_metadata_keys_written_when_entity_known(self):
        """_forward_execution_event_to_flow_surface must write metadata keys."""
        fake_entity = _make_fake_entity("flow_meta_001")

        with patch(
            "core.delegated_flow_entity.get_delegated_flow_entity_runtime"
        ) as mock_rt:
            mock_rt.return_value.get.return_value = fake_entity
            absorb_device_execution_event(
                "dev_e01",
                {
                    "flow_id": "flow_meta_001",
                    "phase": "execution",
                    "step_index": 2,
                    "event_ts": 9000.0,
                },
            )

        assert "_last_android_execution_event" in fake_entity.metadata
        assert "_last_android_phase" in fake_entity.metadata
        assert "_last_android_event_absorbed_at" in fake_entity.metadata
        assert fake_entity.metadata["_last_android_phase"] == "execution"

    def test_E02_metadata_not_written_when_entity_unknown(self):
        """No crash and no metadata when flow entity is not registered."""
        with patch(
            "core.delegated_flow_entity.get_delegated_flow_entity_runtime"
        ) as mock_rt:
            mock_rt.return_value.get.return_value = None
            # Must not raise
            absorb_device_execution_event(
                "dev_e02",
                {"flow_id": "flow_unknown", "phase": "execution"},
            )

    def test_E03_no_error_when_flow_id_empty(self):
        """Events without flow_id are stored but forward path is skipped."""
        # Must not raise even though flow_id is empty
        evt = absorb_device_execution_event(
            "dev_e03",
            {"phase": "planning"},  # no flow_id
        )
        assert evt.flow_id == ""

    def test_E04_ace_dict_has_correct_phase_and_step_index(self):
        fake_entity = _make_fake_entity("flow_meta_004")

        with patch(
            "core.delegated_flow_entity.get_delegated_flow_entity_runtime"
        ) as mock_rt:
            mock_rt.return_value.get.return_value = fake_entity
            absorb_device_execution_event(
                "dev_e04",
                {
                    "flow_id": "flow_meta_004",
                    "phase": "replan",
                    "step_index": 5,
                },
            )

        ace_dict = fake_entity.metadata["_last_android_execution_event"]
        assert isinstance(ace_dict, dict)
        assert ace_dict["phase"] == "replan"
        assert ace_dict["step_index"] == 5


# ---------------------------------------------------------------------------
# F. android_ts uses event_ts, not absorbed_at
# ---------------------------------------------------------------------------


class TestForwardUsesEventTs:
    def test_F01_android_ts_matches_event_ts_when_provided(self):
        fake_entity = _make_fake_entity("flow_f01")

        with patch(
            "core.delegated_flow_entity.get_delegated_flow_entity_runtime"
        ) as mock_rt:
            mock_rt.return_value.get.return_value = fake_entity
            absorb_device_execution_event(
                "dev_f01",
                {"flow_id": "flow_f01", "phase": "grounding", "event_ts": 7777.77},
            )

        ace_dict = fake_entity.metadata["_last_android_execution_event"]
        assert ace_dict.get("android_ts") == pytest.approx(7777.77)

    def test_F02_android_ts_is_none_when_event_ts_absent(self):
        fake_entity = _make_fake_entity("flow_f02")

        with patch(
            "core.delegated_flow_entity.get_delegated_flow_entity_runtime"
        ) as mock_rt:
            mock_rt.return_value.get.return_value = fake_entity
            absorb_device_execution_event(
                "dev_f02",
                {"flow_id": "flow_f02", "phase": "planning"},
            )

        ace_dict = fake_entity.metadata["_last_android_execution_event"]
        # android_ts should be None when no device-side event_ts was present
        assert ace_dict.get("android_ts") is None


# ---------------------------------------------------------------------------
# G. _derive_android_execution_phase reads entity metadata (Gap 1 fix)
# ---------------------------------------------------------------------------


class TestDerivePhaseReadsEntityMetadata:
    def test_G01_phase_derived_from_entity_metadata(self):
        """_derive_android_execution_phase must return the phase from metadata."""
        from core.flow_level_operator_surface import (
            AndroidCanonicalExecutionEvent,
            FlowLevelOperatorSurface,
        )

        ace = AndroidCanonicalExecutionEvent(
            flow_id="flow_g01",
            phase=AndroidExecutionPhase.grounding,
            step_index=2,
            detail="grounding step 2",
            is_blocking=False,
        )

        fake_entity = _make_fake_entity("flow_g01")
        fake_entity.metadata["_last_android_execution_event"] = ace.to_dict()
        fake_entity.metadata["_last_android_phase"] = "grounding"

        with patch(
            "core.delegated_flow_entity.get_delegated_flow_entity_runtime"
        ) as mock_rt:
            mock_rt.return_value.get.return_value = fake_entity
            last_event, phase_str = FlowLevelOperatorSurface._derive_android_execution_phase(
                "flow_g01"
            )

        assert phase_str == AndroidExecutionPhase.grounding.value
        assert last_event is not None
        assert last_event.phase == AndroidExecutionPhase.grounding

    def test_G02_blocking_phase_preserved(self):
        """Blocking phases (stagnation) must be surfaced correctly."""
        from core.flow_level_operator_surface import (
            AndroidCanonicalExecutionEvent,
            FlowLevelOperatorSurface,
        )

        ace = AndroidCanonicalExecutionEvent(
            flow_id="flow_g02",
            phase=AndroidExecutionPhase.stagnation,
            step_index=9,
            is_blocking=True,
            blocking_reason="too_many_retries",
        )

        fake_entity = _make_fake_entity("flow_g02")
        fake_entity.metadata["_last_android_execution_event"] = ace.to_dict()
        fake_entity.metadata["_last_android_phase"] = "stagnation"

        with patch(
            "core.delegated_flow_entity.get_delegated_flow_entity_runtime"
        ) as mock_rt:
            mock_rt.return_value.get.return_value = fake_entity
            last_event, phase_str = FlowLevelOperatorSurface._derive_android_execution_phase(
                "flow_g02"
            )

        assert phase_str == AndroidExecutionPhase.stagnation.value
        assert last_event is not None
        assert last_event.is_blocking is True
        assert last_event.blocking_reason == "too_many_retries"

    def test_G03_unknown_phase_when_no_metadata_and_no_truth_alignment(self):
        """Falls back to unknown when entity has no metadata and no truth records."""
        from core.flow_level_operator_surface import FlowLevelOperatorSurface

        fake_entity = _make_fake_entity("flow_g03")
        # No _last_android_execution_event in metadata

        with patch(
            "core.delegated_flow_entity.get_delegated_flow_entity_runtime"
        ) as mock_rt, patch(
            "core.flow_level_truth_ownership.get_flow_truth_alignment_runtime"
        ) as mock_tar:
            mock_rt.return_value.get.return_value = fake_entity
            mock_tar.return_value.get_by_flow_id.return_value = []
            last_event, phase_str = FlowLevelOperatorSurface._derive_android_execution_phase(
                "flow_g03"
            )

        assert phase_str == AndroidExecutionPhase.unknown.value
        assert last_event is None

    def test_G04_all_phase_values_roundtrip_through_metadata(self):
        """Every AndroidExecutionPhase value must survive entity-metadata roundtrip."""
        from core.flow_level_operator_surface import (
            AndroidCanonicalExecutionEvent,
            FlowLevelOperatorSurface,
        )

        for phase in AndroidExecutionPhase:
            fid = f"flow_g04_{phase.value}"
            ace = AndroidCanonicalExecutionEvent(flow_id=fid, phase=phase)
            fake_entity = _make_fake_entity(fid)
            fake_entity.metadata["_last_android_execution_event"] = ace.to_dict()

            with patch(
                "core.delegated_flow_entity.get_delegated_flow_entity_runtime"
            ) as mock_rt:
                mock_rt.return_value.get.return_value = fake_entity
                _, phase_str = FlowLevelOperatorSurface._derive_android_execution_phase(fid)

            assert phase_str == phase.value, (
                f"Phase {phase.value!r} did not roundtrip through entity metadata"
            )


# ---------------------------------------------------------------------------
# H. inspect_flow reflects absorbed execution phase
# ---------------------------------------------------------------------------


class TestInspectFlowReflectsExecutionPhase:
    def _make_full_entity(self, flow_id: str) -> MagicMock:
        from unittest.mock import MagicMock
        entity = MagicMock()
        entity.identity.delegated_flow_id = flow_id
        entity.identity.flow_lineage_id = "lin_001"
        entity.identity.flow_segment_id = ""
        entity.identity.trace_id = "trace_001"
        entity.identity.flow_kind.value = "task_assign"
        entity.phase.value = "active"
        entity.phase.is_active.return_value = True
        entity.object_mapping.canonical_task_id = "task_001"
        entity.object_mapping.dispatch_record_id = "dr_001"
        entity.object_mapping.contract_id = "con_001"
        entity.object_mapping.binding_id = "bind_001"
        entity.object_mapping.device_id = "dev_001"
        entity.object_mapping.android_flow_id = ""
        entity.created_at = 1_700_000_000.0
        entity.last_updated_at = 1_700_000_100.0
        entity.metadata = {}
        return entity

    def test_H01_inspect_flow_returns_correct_phase_after_event_absorbed(self):
        """inspect_flow must show the correct phase after an execution event is absorbed."""
        from core.flow_level_operator_surface import (
            AndroidCanonicalExecutionEvent,
            FlowLevelOperatorSurface,
        )

        flow_id = "flow_h01"
        ace = AndroidCanonicalExecutionEvent(
            flow_id=flow_id,
            phase=AndroidExecutionPhase.execution,
            step_index=4,
            detail="executing step 4",
        )

        entity = self._make_full_entity(flow_id)
        entity.metadata["_last_android_execution_event"] = ace.to_dict()
        entity.metadata["_last_android_phase"] = "execution"

        surface = FlowLevelOperatorSurface()

        with patch(
            "core.delegated_flow_entity.get_delegated_flow_entity_runtime"
        ) as mock_rt:
            mock_rt.return_value.get.return_value = entity
            with patch.object(surface, "_load_flow_entity", return_value=entity):
                proj = surface.inspect_flow(flow_id)

        assert proj is not None
        assert proj.current_execution_phase == AndroidExecutionPhase.execution.value
        assert proj.last_android_execution_event is not None
        assert proj.last_android_execution_event.phase == AndroidExecutionPhase.execution

    def test_H02_inspect_flow_blocking_reason_set_when_blocking(self):
        """blocking_reason must be propagated to the projection when is_blocking=True."""
        from core.flow_level_operator_surface import (
            AndroidCanonicalExecutionEvent,
            FlowLevelOperatorSurface,
        )

        flow_id = "flow_h02"
        ace = AndroidCanonicalExecutionEvent(
            flow_id=flow_id,
            phase=AndroidExecutionPhase.gate_decision,
            is_blocking=True,
            blocking_reason="policy_gate_alpha",
        )

        entity = self._make_full_entity(flow_id)
        entity.metadata["_last_android_execution_event"] = ace.to_dict()
        entity.metadata["_last_android_phase"] = "gate_decision"

        surface = FlowLevelOperatorSurface()

        with patch(
            "core.delegated_flow_entity.get_delegated_flow_entity_runtime"
        ) as mock_rt:
            mock_rt.return_value.get.return_value = entity
            with patch.object(surface, "_load_flow_entity", return_value=entity):
                proj = surface.inspect_flow(flow_id)

        assert proj is not None
        assert proj.blocking_reason != ""
        assert "policy_gate_alpha" in proj.blocking_reason


# ---------------------------------------------------------------------------
# I. handle_device_execution_event handler — full payload ACK
# ---------------------------------------------------------------------------


class TestHandlerAck:
    def test_I01_realistic_camel_payload_absorbed_and_acked(self):
        """Realistic camelCase Android payload must absorb cleanly and ACK."""
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_execution_event,
        )

        reset_android_device_state_store()
        try:
            message = {
                "type": "device_execution_event",
                "device_id": "dev_i01",
                "message_id": "msg_i01",
                "payload": {
                    "flowId": "flow_i01",
                    "taskId": "task_i01",
                    "phase": "execution",
                    "stepIndex": 2,
                    "isBlocking": False,
                    "eventTs": 1_700_000_300.0,
                },
            }
            bridge = MagicMock()
            ws = MagicMock()
            response = asyncio.run(
                handle_device_execution_event(bridge, ws, message)
            )
            assert response is not None
            assert response["type"] == "device_execution_event_ack"
            assert response["status"] == "absorbed"
            assert response["device_id"] == "dev_i01"
            assert response["correlation_id"] == "msg_i01"

            store = get_android_device_state_store()
            events = store.list_recent_execution_events(device_id="dev_i01")
            assert len(events) >= 1
            assert events[0].phase == "execution"
            assert events[0].event_ts == pytest.approx(1_700_000_300.0)
        finally:
            reset_android_device_state_store()

    def test_I02_stagnation_blocking_payload_absorbed(self):
        """Stagnation / blocking event must be absorbed with blocking fields."""
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_execution_event,
        )

        reset_android_device_state_store()
        try:
            message = {
                "type": "device_execution_event",
                "device_id": "dev_i02",
                "message_id": "msg_i02",
                "payload": {
                    "flow_id": "flow_i02",
                    "phase": "stagnation",
                    "step_index": 5,
                    "is_blocking": True,
                    "blocking_reason": "stagnation_detected_at_step_5",
                    "stagnation_detected": True,
                    "fallback_tier": "center_delegated",
                },
            }
            bridge = MagicMock()
            ws = MagicMock()
            response = asyncio.run(
                handle_device_execution_event(bridge, ws, message)
            )
            assert response["status"] == "absorbed"

            store = get_android_device_state_store()
            events = store.list_recent_execution_events(flow_id="flow_i02")
            assert len(events) >= 1
            e = events[0]
            assert e.is_blocking is True
            assert e.stagnation_detected is True
            assert e.blocking_reason == "stagnation_detected_at_step_5"
            assert e.fallback_tier == "center_delegated"
        finally:
            reset_android_device_state_store()

    def test_I03_step_index_none_does_not_cause_error_status(self):
        """step_index=None must not cause the handler to return error status."""
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_execution_event,
        )

        reset_android_device_state_store()
        try:
            message = {
                "type": "device_execution_event",
                "device_id": "dev_i03",
                "message_id": "msg_i03",
                "payload": {
                    "flow_id": "flow_i03",
                    "phase": "planning",
                    "step_index": None,
                },
            }
            bridge = MagicMock()
            ws = MagicMock()
            response = asyncio.run(
                handle_device_execution_event(bridge, ws, message)
            )
            assert response["status"] == "absorbed"
            store = get_android_device_state_store()
            events = store.list_recent_execution_events(device_id="dev_i03")
            assert events[0].step_index == -1
        finally:
            reset_android_device_state_store()


# ---------------------------------------------------------------------------
# J. execution-events route supports query param filtering
# ---------------------------------------------------------------------------


class TestExecutionEventsRouteFiltering:
    @pytest.fixture
    def _client(self):
        """Build a minimal FastAPI app with the operator router mounted."""
        from core.routes.operator import create_router
        app = FastAPI()
        app.include_router(create_router())
        return TestClient(app)

    def test_J01_no_filter_returns_all_events(self, _client):
        absorb_device_execution_event("dev_j01", {"flow_id": "fj1", "phase": "planning"})
        absorb_device_execution_event("dev_j02", {"flow_id": "fj2", "phase": "execution"})
        r = _client.get("/api/v1/operator/devices/execution-events")
        assert r.status_code == 200
        data = r.json()
        assert data["total_events"] >= 2

    def test_J02_flow_id_filter_narrows_results(self, _client):
        absorb_device_execution_event("dev_j03", {"flow_id": "fj_target", "phase": "grounding"})
        absorb_device_execution_event("dev_j03", {"flow_id": "fj_other", "phase": "planning"})
        r = _client.get("/api/v1/operator/devices/execution-events?flow_id=fj_target")
        assert r.status_code == 200
        data = r.json()
        assert all(e["flow_id"] == "fj_target" for e in data["events"])
        assert data["total_events"] >= 1

    def test_J03_device_id_filter_narrows_results(self, _client):
        absorb_device_execution_event("dev_target", {"flow_id": "fj4", "phase": "execution"})
        absorb_device_execution_event("dev_other", {"flow_id": "fj4", "phase": "execution"})
        r = _client.get("/api/v1/operator/devices/execution-events?device_id=dev_target")
        assert r.status_code == 200
        data = r.json()
        assert all(e["device_id"] == "dev_target" for e in data["events"])

    def test_J04_limit_param_caps_results(self, _client):
        for i in range(10):
            absorb_device_execution_event("dev_j05", {"flow_id": "fj5", "phase": "execution"})
        r = _client.get("/api/v1/operator/devices/execution-events?limit=3")
        assert r.status_code == 200
        data = r.json()
        assert data["total_events"] <= 3

    def test_J05_unknown_flow_id_returns_empty_events(self, _client):
        r = _client.get(
            "/api/v1/operator/devices/execution-events?flow_id=flow_does_not_exist_xyz"
        )
        assert r.status_code == 200
        assert r.json()["total_events"] == 0


# ---------------------------------------------------------------------------
# K. execution-events route returns event_ts in each dict
# ---------------------------------------------------------------------------


class TestExecutionEventsRouteEventTs:
    @pytest.fixture
    def _client(self):
        from core.routes.operator import create_router
        app = FastAPI()
        app.include_router(create_router())
        return TestClient(app)

    def test_K01_event_ts_present_in_response_when_set(self, _client):
        absorb_device_execution_event(
            "dev_k01",
            {"flow_id": "fk1", "phase": "grounding", "event_ts": 1234.56},
        )
        r = _client.get("/api/v1/operator/devices/execution-events?flow_id=fk1")
        assert r.status_code == 200
        events = r.json()["events"]
        assert len(events) >= 1
        assert events[0]["event_ts"] == pytest.approx(1234.56)

    def test_K02_event_ts_none_when_not_provided(self, _client):
        absorb_device_execution_event("dev_k02", {"flow_id": "fk2", "phase": "planning"})
        r = _client.get("/api/v1/operator/devices/execution-events?flow_id=fk2")
        events = r.json()["events"]
        assert "event_ts" in events[0]
        assert events[0]["event_ts"] is None


# ---------------------------------------------------------------------------
# L. End-to-end: bridge → store → entity metadata → derive_phase
# ---------------------------------------------------------------------------


class TestEndToEndBridgeToPhaseProjection:
    def test_L01_full_path_execution_event_projects_to_phase(self):
        """Bridge → store → entity metadata → _derive_android_execution_phase."""
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_execution_event,
        )
        from core.flow_level_operator_surface import FlowLevelOperatorSurface

        flow_id = "flow_l01"
        fake_entity = _make_fake_entity(flow_id)

        reset_android_device_state_store()
        try:
            message = {
                "type": "device_execution_event",
                "device_id": "dev_l01",
                "message_id": "msg_l01",
                "payload": {
                    "flowId": flow_id,
                    "taskId": "task_l01",
                    "phase": "replan",
                    "stepIndex": 3,
                    "isBlocking": False,
                    "eventTs": 9999.0,
                },
            }
            bridge = MagicMock()
            ws = MagicMock()

            with patch(
                "core.delegated_flow_entity.get_delegated_flow_entity_runtime"
            ) as mock_rt:
                mock_rt.return_value.get.return_value = fake_entity
                asyncio.run(handle_device_execution_event(bridge, ws, message))

            # After absorption, entity metadata should carry the phase
            assert fake_entity.metadata.get("_last_android_phase") == "replan"

            # _derive_android_execution_phase must return "replan"
            with patch(
                "core.delegated_flow_entity.get_delegated_flow_entity_runtime"
            ) as mock_flos_rt:
                mock_flos_rt.return_value.get.return_value = fake_entity
                _, phase_str = FlowLevelOperatorSurface._derive_android_execution_phase(flow_id)

            assert phase_str == AndroidExecutionPhase.replan.value

        finally:
            reset_android_device_state_store()

    def test_L02_completed_phase_projects_correctly(self):
        """Completed events must project correctly — terminal phase check."""
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_execution_event,
        )
        from core.flow_level_operator_surface import FlowLevelOperatorSurface

        flow_id = "flow_l02"
        fake_entity = _make_fake_entity(flow_id)

        reset_android_device_state_store()
        try:
            message = {
                "type": "device_execution_event",
                "device_id": "dev_l02",
                "message_id": "msg_l02",
                "payload": {
                    "flow_id": flow_id,
                    "phase": "completed",
                    "step_index": 10,
                },
            }
            bridge = MagicMock()
            ws = MagicMock()

            with patch(
                "core.delegated_flow_entity.get_delegated_flow_entity_runtime"
            ) as mock_rt:
                mock_rt.return_value.get.return_value = fake_entity
                asyncio.run(handle_device_execution_event(bridge, ws, message))

            with patch(
                "core.delegated_flow_entity.get_delegated_flow_entity_runtime"
            ) as mock_flos_rt:
                mock_flos_rt.return_value.get.return_value = fake_entity
                last_event, phase_str = FlowLevelOperatorSurface._derive_android_execution_phase(
                    flow_id
                )

            assert phase_str == AndroidExecutionPhase.completed.value
            assert last_event is not None
            assert last_event.phase.is_terminal() is True

        finally:
            reset_android_device_state_store()
