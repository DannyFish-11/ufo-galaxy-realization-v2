"""tests/test_pr34_target_runtime_local_takeover.py
======================================================
Tests for PR-34: Target Runtime Local Takeover Path.

Coverage:
  1.  LocalTakeoverResult — serialisation stability (to_dict/to_json/from_dict).
  2.  LocalTakeoverResult — stable field names.
  3.  LocalTakeoverStatus — all enum values present.
  4.  LocalTakeoverSessionContext — field correctness.
  5.  build_local_takeover_result — convenience factory.
  6.  from_execution_output — adapter from execution path output.
  7.  failure_result — minimal failure builder.
  8.  normalize_handoff_envelope — accepts HandoffEnvelopeV2.
  9.  normalize_handoff_envelope — accepts raw dict.
  10. normalize_handoff_envelope — accepts legacy HandoffContract duck-type.
  11. normalize_handoff_envelope — accepts None.
  12. adopt_handoff_session — extracts fields from envelope.
  13. adopt_handoff_session — creates new session when no existing ID.
  14. adopt_handoff_session — marks adopted when existing session ID supplied.
  15. resolve_or_create_runtime_session — returns existing when supplied.
  16. resolve_or_create_runtime_session — returns envelope session_id.
  17. resolve_or_create_runtime_session — generates UUID when no input.
  18. build_local_takeover_context — assembles state-continuum dict.
  19. execute_local_takeover — end-to-end, executor unavailable (skipped).
  20. execute_local_takeover — with raw dict input.
  21. execute_local_takeover — with None input.
  22. execute_local_takeover — takeover_policy.allow_local_takeover=False → rejected.
  23. TargetTakeoverHandler.handle — returns LocalTakeoverResult.
  24. TargetTakeoverHandler.handle — graceful error handling.
  25. contracts package root re-exports.
  26. core.unified package re-exports.
  27. Projection endpoint — POST /api/v1/runtime/takeover (additive).
  28. to_compact_summary helper.
  29. LocalTakeoverResult.from_dict round-trip.
  30. Graceful handling of partial / missing data.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_envelope(
    trace_id: str = "trace_001",
    task_id: str = "task_001",
    session_id: str = "sess_001",
    allow_local_takeover: bool = True,
) -> Any:
    """Return a real HandoffEnvelopeV2."""
    from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
    return build_handoff_envelope_v2(
        trace_id=trace_id,
        task={"tool_name": "screenshot", "args": {}},
        task_id=task_id,
        session_id=session_id,
        allow_local_takeover=allow_local_takeover,
    )


def _make_legacy_contract(
    trace_id: str = "trace_legacy_001",
    task: dict = None,
    session: dict = None,
) -> Any:
    """Return a mock shaped like galaxy_gateway.agent_bridge.HandoffContract."""
    m = MagicMock()
    m.trace_id = trace_id
    m.task_id = ""
    m.task = task if task is not None else {"tool_name": "click", "args": {}}
    m.capability = "screen"
    m.exec_mode = "both"
    m.route_mode = "direct"
    m.session = session if session is not None else {}
    m.callback_channel = "ws"
    return m


def _make_skipped_exec_output(reason: str = "executor_unavailable") -> dict:
    return {
        "action_taken": "none",
        "success": False,
        "skipped_reason": reason,
    }


def _make_success_exec_output() -> dict:
    return {
        "action_taken": "click",
        "target": "button_ok",
        "success": True,
        "skipped_reason": None,
        "metadata": {},
        "execution_intent": {},
        "execution_trace": {"trace_id": "trace_001", "events": []},
    }


# ---------------------------------------------------------------------------
# 1. LocalTakeoverResult serialisation stability
# ---------------------------------------------------------------------------

class TestSerialisationStability:
    """LocalTakeoverResult serialises and round-trips correctly."""

    def test_to_dict_returns_dict(self):
        from contracts.local_takeover_result import LocalTakeoverResult
        r = LocalTakeoverResult(trace_id="t1", success=True)
        d = r.to_dict()
        assert isinstance(d, dict)

    def test_to_json_is_valid_json(self):
        from contracts.local_takeover_result import LocalTakeoverResult
        r = LocalTakeoverResult(trace_id="t2", success=False)
        j = r.to_json()
        assert isinstance(json.loads(j), dict)

    def test_from_dict_round_trip(self):
        from contracts.local_takeover_result import LocalTakeoverResult, LocalTakeoverStatus
        original = LocalTakeoverResult(
            trace_id="t3",
            task_id="task_rt",
            session_id="sess_rt",
            success=True,
            status=LocalTakeoverStatus.succeeded,
        )
        d = original.to_dict()
        restored = LocalTakeoverResult.from_dict(d)
        assert restored.trace_id == "t3"
        assert restored.task_id == "task_rt"
        assert restored.success is True
        assert restored.status == LocalTakeoverStatus.succeeded

    def test_to_json_indent(self):
        from contracts.local_takeover_result import LocalTakeoverResult
        r = LocalTakeoverResult(trace_id="t4")
        j = r.to_json(indent=2)
        assert "\n" in j


# ---------------------------------------------------------------------------
# 2. Stable field names
# ---------------------------------------------------------------------------

class TestStableFieldNames:
    """All documented fields are present in to_dict() output."""

    REQUIRED_FIELDS = [
        "result_id", "trace_id", "task_id", "session_id", "runtime_session_id",
        "success", "status", "result", "execution_trace", "governance_snapshot",
        "policy_alignment", "session_context", "errors", "reason",
        "timestamp", "metadata",
    ]

    def test_all_fields_present(self):
        from contracts.local_takeover_result import LocalTakeoverResult
        d = LocalTakeoverResult(trace_id="t5").to_dict()
        for field in self.REQUIRED_FIELDS:
            assert field in d, f"Missing field: {field}"

    def test_result_id_is_uuid4(self):
        from contracts.local_takeover_result import LocalTakeoverResult
        r = LocalTakeoverResult()
        uuid.UUID(r.result_id)  # should not raise

    def test_timestamp_is_float(self):
        from contracts.local_takeover_result import LocalTakeoverResult
        r = LocalTakeoverResult()
        assert isinstance(r.timestamp, float)
        assert r.timestamp > 0


# ---------------------------------------------------------------------------
# 3. LocalTakeoverStatus enum values
# ---------------------------------------------------------------------------

class TestLocalTakeoverStatusEnum:
    def test_all_values_present(self):
        from contracts.local_takeover_result import LocalTakeoverStatus
        expected = {"pending", "adopted", "executing", "succeeded", "failed", "blocked", "rejected"}
        actual = {s.value for s in LocalTakeoverStatus}
        assert expected == actual

    def test_status_serialised_as_string(self):
        from contracts.local_takeover_result import LocalTakeoverResult, LocalTakeoverStatus
        r = LocalTakeoverResult(status=LocalTakeoverStatus.succeeded)
        d = r.to_dict()
        assert d["status"] == "succeeded"


# ---------------------------------------------------------------------------
# 4. LocalTakeoverSessionContext
# ---------------------------------------------------------------------------

class TestLocalTakeoverSessionContext:
    def test_fields(self):
        from contracts.local_takeover_result import LocalTakeoverSessionContext
        sc = LocalTakeoverSessionContext(
            session_id="sess_sc",
            runtime_session_id="rt_sc",
            task_id="task_sc",
            trace_id="trace_sc",
            adopted=True,
            mesh_session_id="mesh_sc",
        )
        d = sc.to_dict()
        assert d["session_id"] == "sess_sc"
        assert d["runtime_session_id"] == "rt_sc"
        assert d["task_id"] == "task_sc"
        assert d["trace_id"] == "trace_sc"
        assert d["adopted"] is True
        assert d["mesh_session_id"] == "mesh_sc"

    def test_defaults(self):
        from contracts.local_takeover_result import LocalTakeoverSessionContext
        sc = LocalTakeoverSessionContext()
        assert sc.session_id is None
        assert sc.adopted is False
        assert sc.mesh_session_id is None

    def test_to_dict(self):
        from contracts.local_takeover_result import LocalTakeoverSessionContext
        sc = LocalTakeoverSessionContext(session_id="s1")
        d = sc.to_dict()
        assert isinstance(d, dict)
        assert d["session_id"] == "s1"


# ---------------------------------------------------------------------------
# 5. build_local_takeover_result factory
# ---------------------------------------------------------------------------

class TestBuildLocalTakeoverResult:
    def test_basic_fields(self):
        from contracts.local_takeover_result import build_local_takeover_result, LocalTakeoverStatus
        r = build_local_takeover_result(
            trace_id="bt1",
            task_id="task_bt1",
            success=True,
            status=LocalTakeoverStatus.succeeded,
        )
        assert r.trace_id == "bt1"
        assert r.task_id == "task_bt1"
        assert r.success is True
        assert r.status == LocalTakeoverStatus.succeeded

    def test_errors_list(self):
        from contracts.local_takeover_result import build_local_takeover_result
        r = build_local_takeover_result(errors=["err1", "err2"])
        assert r.errors == ["err1", "err2"]

    def test_metadata_merged(self):
        from contracts.local_takeover_result import build_local_takeover_result
        r = build_local_takeover_result(metadata={"key": "val"})
        assert r.metadata["key"] == "val"

    def test_defaults_safe(self):
        from contracts.local_takeover_result import build_local_takeover_result
        r = build_local_takeover_result()
        assert r.success is False
        assert r.errors == []
        assert r.metadata == {}


# ---------------------------------------------------------------------------
# 6. from_execution_output adapter
# ---------------------------------------------------------------------------

class TestFromExecutionOutput:
    def test_success_output(self):
        from contracts.local_takeover_result import from_execution_output, LocalTakeoverStatus
        out = _make_success_exec_output()
        r = from_execution_output(
            trace_id="feo_t1",
            execution_output=out,
            session_id="sess_feo",
        )
        assert r.success is True
        assert r.status == LocalTakeoverStatus.succeeded
        assert r.result == out
        assert r.execution_trace is not None

    def test_skipped_output(self):
        from contracts.local_takeover_result import from_execution_output, LocalTakeoverStatus
        out = _make_skipped_exec_output("readiness_gate:observe_only:policy")
        r = from_execution_output(trace_id="feo_t2", execution_output=out)
        assert r.success is False
        assert r.status == LocalTakeoverStatus.blocked
        assert "readiness_gate" in r.reason

    def test_error_action_output(self):
        from contracts.local_takeover_result import from_execution_output, LocalTakeoverStatus
        out = {"action_taken": "error", "success": False, "skipped_reason": "boom"}
        r = from_execution_output(trace_id="feo_t3", execution_output=out)
        assert r.status == LocalTakeoverStatus.failed

    def test_none_output(self):
        from contracts.local_takeover_result import from_execution_output
        r = from_execution_output(trace_id="feo_t4", execution_output=None)
        assert r.success is False

    def test_trace_extracted_from_dict(self):
        from contracts.local_takeover_result import from_execution_output
        out = {
            "action_taken": "click",
            "success": True,
            "execution_trace": {"trace_id": "tr_ext", "events": []},
        }
        r = from_execution_output(trace_id="feo_t5", execution_output=out)
        assert r.execution_trace == {"trace_id": "tr_ext", "events": []}

    def test_trace_extracted_from_object_with_to_dict(self):
        from contracts.local_takeover_result import from_execution_output
        mock_trace = MagicMock()
        mock_trace.to_dict.return_value = {"trace_id": "tr_obj"}
        out = {"action_taken": "click", "success": True, "execution_trace": mock_trace}
        r = from_execution_output(trace_id="feo_t6", execution_output=out)
        assert r.execution_trace == {"trace_id": "tr_obj"}


# ---------------------------------------------------------------------------
# 7. failure_result builder
# ---------------------------------------------------------------------------

class TestFailureResult:
    def test_basic(self):
        from contracts.local_takeover_result import failure_result, LocalTakeoverStatus
        r = failure_result(trace_id="fr_t1", reason="test_reason")
        assert r.success is False
        assert r.reason == "test_reason"
        assert r.status == LocalTakeoverStatus.failed

    def test_rejected_status(self):
        from contracts.local_takeover_result import failure_result, LocalTakeoverStatus
        r = failure_result(
            trace_id="fr_t2",
            reason="policy_rejected",
            status=LocalTakeoverStatus.rejected,
        )
        assert r.status == LocalTakeoverStatus.rejected

    def test_errors_forwarded(self):
        from contracts.local_takeover_result import failure_result
        r = failure_result(errors=["err1"])
        assert r.errors == ["err1"]


# ---------------------------------------------------------------------------
# 8–11. normalize_handoff_envelope
# ---------------------------------------------------------------------------

class TestNormalizeHandoffEnvelope:
    def test_accepts_handoff_envelope_v2(self):
        from core.runtime.target_takeover import normalize_handoff_envelope
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        env = _make_envelope()
        result = normalize_handoff_envelope(env)
        assert isinstance(result, HandoffEnvelopeV2)
        assert result is env  # returned unchanged

    def test_accepts_raw_dict(self):
        from core.runtime.target_takeover import normalize_handoff_envelope
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        d = {
            "trace_id": "dict_trace",
            "task_id": "dict_task",
            "session_id": "dict_sess",
            "task": {"tool_name": "click", "args": {}},
        }
        result = normalize_handoff_envelope(d)
        assert isinstance(result, HandoffEnvelopeV2)
        assert result.trace_id == "dict_trace"

    def test_accepts_legacy_duck_type(self):
        from core.runtime.target_takeover import normalize_handoff_envelope
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        legacy = _make_legacy_contract(trace_id="legacy_trace")
        result = normalize_handoff_envelope(legacy)
        assert isinstance(result, HandoffEnvelopeV2)
        assert result.trace_id == "legacy_trace"

    def test_accepts_none(self):
        from core.runtime.target_takeover import normalize_handoff_envelope
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        result = normalize_handoff_envelope(None)
        assert isinstance(result, HandoffEnvelopeV2)

    def test_dict_generates_trace_id_when_missing(self):
        from core.runtime.target_takeover import normalize_handoff_envelope
        result = normalize_handoff_envelope({"task": {}})
        assert result.trace_id  # UUID generated
        uuid.UUID(result.trace_id)


# ---------------------------------------------------------------------------
# 12–14. adopt_handoff_session
# ---------------------------------------------------------------------------

class TestAdoptHandoffSession:
    def test_extracts_ids_from_envelope(self):
        from core.runtime.target_takeover import adopt_handoff_session
        env = _make_envelope(trace_id="ahs_trace", task_id="ahs_task", session_id="ahs_sess")
        sc = adopt_handoff_session(env)
        assert sc.trace_id == "ahs_trace"
        assert sc.task_id == "ahs_task"
        assert sc.session_id == "ahs_sess"

    def test_creates_new_session_when_no_existing(self):
        from core.runtime.target_takeover import adopt_handoff_session
        env = _make_envelope()
        sc = adopt_handoff_session(env)
        assert sc.adopted is False
        assert sc.runtime_session_id  # generated UUID

    def test_adopted_when_existing_supplied(self):
        from core.runtime.target_takeover import adopt_handoff_session
        env = _make_envelope()
        sc = adopt_handoff_session(env, existing_runtime_session_id="existing_rt_sess")
        assert sc.adopted is True
        assert sc.runtime_session_id == "existing_rt_sess"

    def test_none_envelope_safe(self):
        from core.runtime.target_takeover import adopt_handoff_session
        sc = adopt_handoff_session(None)
        assert sc is not None
        assert sc.session_id  # generated

    def test_session_id_generated_when_envelope_has_none(self):
        from core.runtime.target_takeover import adopt_handoff_session
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        env = HandoffEnvelopeV2(trace_id="t1")  # no session_id
        sc = adopt_handoff_session(env)
        assert sc.session_id  # should not be empty


# ---------------------------------------------------------------------------
# 15–17. resolve_or_create_runtime_session
# ---------------------------------------------------------------------------

class TestResolveOrCreateRuntimeSession:
    def test_returns_existing_when_supplied(self):
        from core.runtime.target_takeover import resolve_or_create_runtime_session
        result = resolve_or_create_runtime_session(None, existing_runtime_session_id="my_rt_sess")
        assert result == "my_rt_sess"

    def test_returns_envelope_session_id(self):
        from core.runtime.target_takeover import resolve_or_create_runtime_session
        env = _make_envelope(session_id="env_sess_id")
        result = resolve_or_create_runtime_session(env)
        assert result == "env_sess_id"

    def test_generates_uuid_when_no_input(self):
        from core.runtime.target_takeover import resolve_or_create_runtime_session
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        env = HandoffEnvelopeV2(trace_id="t1")  # no session_id
        result = resolve_or_create_runtime_session(env)
        uuid.UUID(result)  # should not raise


# ---------------------------------------------------------------------------
# 18. build_local_takeover_context
# ---------------------------------------------------------------------------

class TestBuildLocalTakeoverContext:
    def test_returns_dict(self):
        from core.runtime.target_takeover import build_local_takeover_context
        env = _make_envelope(trace_id="ctx_trace", task_id="ctx_task")
        result = build_local_takeover_context(env)
        assert isinstance(result, dict)

    def test_trace_id_forwarded(self):
        from core.runtime.target_takeover import build_local_takeover_context
        env = _make_envelope(trace_id="ctx_trace2")
        result = build_local_takeover_context(env)
        assert result["trace_id"] == "ctx_trace2"

    def test_force_local_execution_set(self):
        from core.runtime.target_takeover import build_local_takeover_context
        env = _make_envelope()
        result = build_local_takeover_context(env)
        assert result["metadata"]["force_local_execution"] is True

    def test_none_envelope_safe(self):
        from core.runtime.target_takeover import build_local_takeover_context
        result = build_local_takeover_context(None)
        assert isinstance(result, dict)
        assert result["task"] == {}

    def test_extra_metadata_merged(self):
        from core.runtime.target_takeover import build_local_takeover_context
        env = _make_envelope()
        result = build_local_takeover_context(env, extra_metadata={"custom_key": "custom_val"})
        assert result["metadata"]["custom_key"] == "custom_val"


# ---------------------------------------------------------------------------
# 19–22. execute_local_takeover end-to-end
# ---------------------------------------------------------------------------

class TestExecuteLocalTakeover:
    def test_returns_local_takeover_result(self):
        from core.runtime.target_takeover import execute_local_takeover
        from contracts.local_takeover_result import LocalTakeoverResult
        env = _make_envelope()
        result = execute_local_takeover(env, capture_governance=False, capture_policy_alignment=False)
        assert isinstance(result, LocalTakeoverResult)

    def test_with_raw_dict(self):
        from core.runtime.target_takeover import execute_local_takeover
        from contracts.local_takeover_result import LocalTakeoverResult
        result = execute_local_takeover(
            {"trace_id": "dict_t1", "task": {}},
            capture_governance=False,
            capture_policy_alignment=False,
        )
        assert isinstance(result, LocalTakeoverResult)
        assert result.trace_id == "dict_t1"

    def test_with_none_input(self):
        from core.runtime.target_takeover import execute_local_takeover
        from contracts.local_takeover_result import LocalTakeoverResult
        result = execute_local_takeover(None, capture_governance=False, capture_policy_alignment=False)
        assert isinstance(result, LocalTakeoverResult)

    def test_policy_rejection(self):
        from core.runtime.target_takeover import execute_local_takeover
        from contracts.local_takeover_result import LocalTakeoverStatus
        env = _make_envelope(allow_local_takeover=False)
        result = execute_local_takeover(env, capture_governance=False, capture_policy_alignment=False)
        assert result.status == LocalTakeoverStatus.rejected
        assert result.success is False

    def test_result_is_serialisable(self):
        from core.runtime.target_takeover import execute_local_takeover
        env = _make_envelope()
        result = execute_local_takeover(env, capture_governance=False, capture_policy_alignment=False)
        d = result.to_dict()
        assert isinstance(d, dict)
        json.dumps(d)  # should not raise

    def test_existing_session_reused(self):
        from core.runtime.target_takeover import execute_local_takeover
        env = _make_envelope()
        result = execute_local_takeover(
            env,
            existing_runtime_session_id="rt_existing",
            capture_governance=False,
            capture_policy_alignment=False,
        )
        assert result.runtime_session_id == "rt_existing"

    def test_trace_id_forwarded(self):
        from core.runtime.target_takeover import execute_local_takeover
        env = _make_envelope(trace_id="fwd_trace_id")
        result = execute_local_takeover(env, capture_governance=False, capture_policy_alignment=False)
        assert result.trace_id == "fwd_trace_id"


# ---------------------------------------------------------------------------
# 23–24. TargetTakeoverHandler
# ---------------------------------------------------------------------------

class TestTargetTakeoverHandler:
    def test_handle_returns_result(self):
        from core.runtime.target_takeover import TargetTakeoverHandler
        from contracts.local_takeover_result import LocalTakeoverResult
        handler = TargetTakeoverHandler()
        env = _make_envelope()
        result = handler.handle(env, capture_governance=False, capture_policy_alignment=False)
        assert isinstance(result, LocalTakeoverResult)

    def test_handle_graceful_on_exception(self):
        """Handler must not raise even if normalisation fails."""
        from core.runtime.target_takeover import TargetTakeoverHandler
        from contracts.local_takeover_result import LocalTakeoverResult

        handler = TargetTakeoverHandler()
        with patch(
            "core.runtime.target_takeover.normalize_handoff_envelope",
            side_effect=RuntimeError("boom"),
        ):
            result = handler.handle({})
        assert isinstance(result, LocalTakeoverResult)
        assert result.success is False

    def test_handle_with_legacy_duck_type(self):
        from core.runtime.target_takeover import TargetTakeoverHandler
        from contracts.local_takeover_result import LocalTakeoverResult
        handler = TargetTakeoverHandler()
        legacy = _make_legacy_contract(trace_id="handler_legacy_trace")
        result = handler.handle(legacy, capture_governance=False, capture_policy_alignment=False)
        assert isinstance(result, LocalTakeoverResult)


# ---------------------------------------------------------------------------
# 25. contracts package root re-exports
# ---------------------------------------------------------------------------

class TestContractsPackageReExports:
    def test_local_takeover_result_importable(self):
        from contracts import LocalTakeoverResult
        assert LocalTakeoverResult is not None

    def test_local_takeover_status_importable(self):
        from contracts import LocalTakeoverStatus
        assert LocalTakeoverStatus is not None

    def test_local_takeover_session_context_importable(self):
        from contracts import LocalTakeoverSessionContext
        assert LocalTakeoverSessionContext is not None

    def test_build_local_takeover_result_importable(self):
        from contracts import build_local_takeover_result
        assert build_local_takeover_result is not None

    def test_takeover_result_from_execution_output_importable(self):
        from contracts import takeover_result_from_execution_output
        assert takeover_result_from_execution_output is not None

    def test_takeover_failure_result_importable(self):
        from contracts import takeover_failure_result
        assert takeover_failure_result is not None


# ---------------------------------------------------------------------------
# 26. core.unified package re-exports
# ---------------------------------------------------------------------------

class TestCoreUnifiedReExports:
    def test_local_takeover_result_importable_from_core_unified(self):
        from core.unified import LocalTakeoverResult
        assert LocalTakeoverResult is not None

    def test_local_takeover_status_importable_from_core_unified(self):
        from core.unified import LocalTakeoverStatus
        assert LocalTakeoverStatus is not None

    def test_local_takeover_session_context_importable_from_core_unified(self):
        from core.unified import LocalTakeoverSessionContext
        assert LocalTakeoverSessionContext is not None

    def test_build_local_takeover_result_importable_from_core_unified(self):
        from core.unified import build_local_takeover_result
        assert build_local_takeover_result is not None


# ---------------------------------------------------------------------------
# 27. Projection endpoint — POST /api/v1/runtime/takeover
# ---------------------------------------------------------------------------

class TestProjectionEndpoint:
    @pytest.mark.asyncio
    async def test_endpoint_returns_valid_result(self):
        """POST /api/v1/runtime/takeover returns a LocalTakeoverResult payload."""
        from core.routes.projection import create_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        router = create_router()
        app.include_router(router)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/runtime/takeover",
                json={
                    "trace_id": "ep_trace",
                    "task_id": "ep_task",
                    "session_id": "ep_sess",
                    "task": {"tool_name": "screenshot", "args": {}},
                },
            )
        assert response.status_code == 200
        payload = response.json()
        assert "success" in payload
        assert "status" in payload
        assert "result_id" in payload
        assert "trace_id" in payload

    @pytest.mark.asyncio
    async def test_endpoint_empty_body_safe(self):
        """Endpoint handles empty/null body gracefully."""
        from core.routes.projection import create_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        router = create_router()
        app.include_router(router)

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/runtime/takeover",
                json={},
            )
        assert response.status_code == 200
        payload = response.json()
        assert "success" in payload

    def test_endpoint_registered_in_router(self):
        """The /api/v1/runtime/takeover POST route is registered."""
        from core.routes.projection import create_router
        router = create_router()
        routes = [r.path for r in router.routes]
        assert "/api/v1/runtime/takeover" in routes


# ---------------------------------------------------------------------------
# 28. to_compact_summary helper
# ---------------------------------------------------------------------------

class TestToCompactSummary:
    def test_returns_dict(self):
        from contracts.local_takeover_result import LocalTakeoverResult
        r = LocalTakeoverResult(trace_id="cs_t1", success=True)
        s = r.to_compact_summary()
        assert isinstance(s, dict)

    def test_expected_keys(self):
        from contracts.local_takeover_result import LocalTakeoverResult
        r = LocalTakeoverResult(trace_id="cs_t2")
        s = r.to_compact_summary()
        for key in ("result_id", "trace_id", "success", "status", "timestamp"):
            assert key in s, f"Missing key: {key}"

    def test_status_is_string(self):
        from contracts.local_takeover_result import LocalTakeoverResult, LocalTakeoverStatus
        r = LocalTakeoverResult(status=LocalTakeoverStatus.blocked)
        s = r.to_compact_summary()
        assert s["status"] == "blocked"

    def test_has_execution_trace_flag(self):
        from contracts.local_takeover_result import LocalTakeoverResult
        r = LocalTakeoverResult(execution_trace={"trace_id": "et1"})
        s = r.to_compact_summary()
        assert s["has_execution_trace"] is True

    def test_has_no_execution_trace_flag(self):
        from contracts.local_takeover_result import LocalTakeoverResult
        r = LocalTakeoverResult()
        s = r.to_compact_summary()
        assert s["has_execution_trace"] is False


# ---------------------------------------------------------------------------
# 29. LocalTakeoverResult.from_dict round-trip
# ---------------------------------------------------------------------------

class TestFromDictRoundTrip:
    def test_full_round_trip(self):
        from contracts.local_takeover_result import (
            LocalTakeoverResult,
            LocalTakeoverStatus,
            LocalTakeoverSessionContext,
        )
        original = LocalTakeoverResult(
            trace_id="rt_trace",
            task_id="rt_task",
            session_id="rt_sess",
            runtime_session_id="rt_rt_sess",
            success=True,
            status=LocalTakeoverStatus.succeeded,
            result={"action_taken": "click", "success": True},
            execution_trace={"trace_id": "rt_et"},
            governance_snapshot={"snapshot_id": "gs1"},
            policy_alignment={"alignment_id": "pa1"},
            session_context=LocalTakeoverSessionContext(session_id="rt_sc"),
            errors=[],
            reason=None,
            metadata={"key": "value"},
        )
        d = original.to_dict()
        restored = LocalTakeoverResult.from_dict(d)
        assert restored.trace_id == "rt_trace"
        assert restored.success is True
        assert restored.status == LocalTakeoverStatus.succeeded
        assert restored.result == {"action_taken": "click", "success": True}
        assert restored.governance_snapshot == {"snapshot_id": "gs1"}

    def test_unknown_fields_tolerated(self):
        from contracts.local_takeover_result import LocalTakeoverResult
        d = {"trace_id": "uf_trace", "success": True, "unknown_field_xyz": "some_value"}
        r = LocalTakeoverResult.from_dict(d)
        assert r.trace_id == "uf_trace"


# ---------------------------------------------------------------------------
# 30. Graceful handling of partial / missing data
# ---------------------------------------------------------------------------

class TestGracefulHandling:
    def test_none_trace_id_allowed(self):
        from contracts.local_takeover_result import LocalTakeoverResult
        r = LocalTakeoverResult(trace_id=None)
        assert r.trace_id is None
        r.to_dict()  # should not raise

    def test_empty_result_allowed(self):
        from contracts.local_takeover_result import LocalTakeoverResult
        r = LocalTakeoverResult(result=None)
        assert r.result is None

    def test_build_factory_safe_on_bad_input(self):
        """build_local_takeover_result should not raise even on unusual input."""
        from contracts.local_takeover_result import build_local_takeover_result
        r = build_local_takeover_result(errors=None, metadata=None)
        assert r.errors == []
        assert r.metadata == {}

    def test_from_execution_output_safe_on_none(self):
        from contracts.local_takeover_result import from_execution_output
        r = from_execution_output(execution_output=None)
        assert isinstance(r.to_dict(), dict)

    def test_adopt_session_safe_on_none_envelope(self):
        from core.runtime.target_takeover import adopt_handoff_session
        sc = adopt_handoff_session(None)
        assert sc is not None

    def test_build_context_safe_on_none_envelope(self):
        from core.runtime.target_takeover import build_local_takeover_context
        ctx = build_local_takeover_context(None)
        assert isinstance(ctx, dict)
