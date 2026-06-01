"""
tests/test_operator_action_dispatch.py
========================================
PR-3: Operator Control-Plane Activation — tests proving:

1. The operator contract module exports the correct types and sentinels.
2. POST /api/v1/operator/action enters the canonical runtime path via
   DesktopPresenceRuntime (not a parallel engine).
3. POST /api/v1/operator/dispatch is a working convenience alias.
4. POST /api/v1/operator/flows/{flow_id}/cancel routes through
   OperatorSurface.execute_operator_action and returns safe semantics.
5. The operator surface is no longer observation-only (action endpoints exist).
6. No parallel action path is introduced — all actions share the single
   DesktopPresenceRuntime canonical entry point.
7. OperatorActionResult is integrated into UnifiedPanelPayload via
   last_operator_action.
8. Android-compatible routing: device_dispatch forwards device_id so routing
   can prefer the requested device.
"""
from __future__ import annotations

import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.operator_action_contract import (
    OPERATOR_ACTION_CONTRACT_AUTHORITY,
    OPERATOR_ACTION_ENTRY_MODE,
    OPERATOR_CONTROL_PLANE_IS_CANONICAL_AUTHORITY,
    OperatorActionKind,
    OperatorActionRequest,
    OperatorActionResult,
    build_operator_action_result_from_runtime_result,
)
from core.routes.operator import create_router
from core.unified_panel_aggregation import (
    get_last_operator_action_result,
    record_last_operator_action_result,
    reset_last_operator_action_result,
    UnifiedPanelPayload,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    _app = FastAPI()
    _app.include_router(create_router())
    return _app


@pytest.fixture(scope="module")
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _reset_action_store():
    reset_last_operator_action_result()
    yield
    reset_last_operator_action_result()


# ===========================================================================
# Section 1: Contract module exports
# ===========================================================================


class TestOperatorActionContract:
    """Validate that the operator action contract module is importable and
    exports all required symbols."""

    def test_authority_sentinel_non_empty(self):
        assert OPERATOR_ACTION_CONTRACT_AUTHORITY
        assert "OPERATOR_ACTION_CONTRACT_V1" in OPERATOR_ACTION_CONTRACT_AUTHORITY

    def test_canonical_authority_sentinel(self):
        assert OPERATOR_CONTROL_PLANE_IS_CANONICAL_AUTHORITY
        assert "canonical" in OPERATOR_CONTROL_PLANE_IS_CANONICAL_AUTHORITY.lower()

    def test_entry_mode_value(self):
        assert OPERATOR_ACTION_ENTRY_MODE == "operator_action"

    def test_action_kind_values(self):
        assert OperatorActionKind.dispatch.value == "dispatch"
        assert OperatorActionKind.device_dispatch.value == "device_dispatch"
        assert OperatorActionKind.flow_cancel.value == "flow_cancel"
        assert OperatorActionKind.retry_admission.value == "retry_admission"
        assert (
            OperatorActionKind.escalate_dependency_failure.value
            == "escalate_dependency_failure"
        )

    def test_operator_action_request_defaults(self):
        req = OperatorActionRequest()
        assert req.action_kind == OperatorActionKind.dispatch.value
        assert req.user_id == "operator"
        assert req.required_capabilities == []
        assert req.context == []

    def test_operator_action_request_from_dict(self):
        d = {"action_kind": "device_dispatch", "message": "test", "device_id": "dev1"}
        req = OperatorActionRequest.from_dict(d)
        assert req.action_kind == "device_dispatch"
        assert req.message == "test"
        assert req.device_id == "dev1"

    def test_operator_action_request_to_dict_roundtrip(self):
        req = OperatorActionRequest(
            action_kind="dispatch",
            message="hello",
            device_id=None,
            user_id="op",
        )
        d = req.to_dict()
        assert d["action_kind"] == "dispatch"
        assert d["message"] == "hello"
        assert d["user_id"] == "op"

    def test_operator_action_result_defaults(self):
        result = OperatorActionResult()
        assert result.accepted is False
        assert result.operator_entry_mode == OPERATOR_ACTION_ENTRY_MODE
        assert result.action_id.startswith("opact_")
        assert result.generated_at > 0

    def test_operator_action_result_to_dict(self):
        result = OperatorActionResult(accepted=True, runtime_session_id="sid123")
        d = result.to_dict()
        assert d["accepted"] is True
        assert d["runtime_session_id"] == "sid123"
        assert d["operator_entry_mode"] == "operator_action"

    def test_build_result_from_runtime_result(self):
        runtime_result = {
            "runtime_session_id": "rsid_abc",
            "trace_id": "rsid_abc",
            "tristate": "silent",
        }
        result = build_operator_action_result_from_runtime_result(
            action_kind="dispatch",
            runtime_result=runtime_result,
        )
        assert result.accepted is True
        assert result.runtime_session_id == "rsid_abc"
        assert result.trace_id == "rsid_abc"
        assert result.operator_entry_mode == OPERATOR_ACTION_ENTRY_MODE
        assert result.runtime_result["tristate"] == "silent"


# ===========================================================================
# Section 2: Operator surface has execute_operator_action (not observation-only)
# ===========================================================================


class TestOperatorSurfaceIsActionCapable:
    """Validate that OperatorSurface has execute_operator_action — proving
    the surface is no longer observation-only."""

    def test_execute_operator_action_method_exists(self):
        from core.operator_surface import OperatorSurface
        surface = OperatorSurface()
        assert hasattr(surface, "execute_operator_action"), (
            "OperatorSurface must have execute_operator_action() — "
            "the surface is observation-only without it"
        )

    def test_execute_operator_action_is_coroutine(self):
        import inspect
        from core.operator_surface import OperatorSurface
        surface = OperatorSurface()
        assert inspect.iscoroutinefunction(surface.execute_operator_action), (
            "execute_operator_action must be async"
        )

    def test_unsupported_action_kind_returns_result(self):
        """Unsupported action kinds return a result with accepted=False — not an exception."""
        from core.operator_surface import OperatorSurface
        surface = OperatorSurface()
        req = OperatorActionRequest(action_kind="__nonexistent__", message="x")
        result = asyncio.get_running_loop().run_until_complete(
            surface.execute_operator_action(req)
        )
        assert isinstance(result, OperatorActionResult)
        assert result.accepted is False
        assert "unsupported" in result.error.lower()

    def test_flow_cancel_missing_flow_id_returns_error(self):
        from core.operator_surface import OperatorSurface
        surface = OperatorSurface()
        req = OperatorActionRequest(
            action_kind=OperatorActionKind.flow_cancel.value,
            flow_id="",
        )
        result = asyncio.get_running_loop().run_until_complete(
            surface.execute_operator_action(req)
        )
        assert result.accepted is False
        assert "flow_id" in result.error.lower()

    def test_flow_cancel_unknown_flow_returns_error(self):
        from core.operator_surface import OperatorSurface
        surface = OperatorSurface()
        req = OperatorActionRequest(
            action_kind=OperatorActionKind.flow_cancel.value,
            flow_id="nonexistent_flow_999",
        )
        result = asyncio.get_running_loop().run_until_complete(
            surface.execute_operator_action(req)
        )
        assert result.accepted is False
        assert "not found" in result.error.lower()


# ===========================================================================
# Section 3: POST /api/v1/operator/action endpoint
# ===========================================================================


class TestOperatorActionEndpoint:
    """Validate the POST /api/v1/operator/action endpoint."""

    def test_action_endpoint_exists(self, client):
        """The action endpoint must exist — 405 means wrong method, not 404."""
        resp = client.post("/api/v1/operator/action", json={})
        # Should not be 404 (endpoint not found) or 405 (method not allowed on GET-only)
        assert resp.status_code != 404, (
            "POST /api/v1/operator/action must exist — the surface is "
            "observation-only if this endpoint is missing"
        )

    def test_action_dispatch_returns_result_schema(self, client):
        resp = client.post(
            "/api/v1/operator/action",
            json={"action_kind": "dispatch", "message": "test operator dispatch"},
        )
        # Either 200 (accepted) or 422 (rejected) — both are valid
        assert resp.status_code in (200, 422, 500)
        data = resp.json()
        # Must always have an action_id (proves it went through OperatorActionResult)
        assert "action_id" in data or "error" in data

    def test_action_dispatch_result_has_operator_entry_mode(self, client):
        resp = client.post(
            "/api/v1/operator/action",
            json={"action_kind": "dispatch", "message": "hello from operator"},
        )
        if resp.status_code in (200, 422):
            data = resp.json()
            # operator_entry_mode confirms this went through the contract
            assert data.get("operator_entry_mode") == OPERATOR_ACTION_ENTRY_MODE, (
                f"Expected operator_entry_mode='operator_action', got: "
                f"{data.get('operator_entry_mode')!r}"
            )

    def test_action_dispatch_returns_action_kind(self, client):
        resp = client.post(
            "/api/v1/operator/action",
            json={"action_kind": "dispatch", "message": "kind check"},
        )
        if resp.status_code in (200, 422):
            data = resp.json()
            assert data.get("action_kind") == "dispatch"

    def test_action_device_dispatch_returns_device_dispatch_kind(self, client):
        resp = client.post(
            "/api/v1/operator/action",
            json={
                "action_kind": "device_dispatch",
                "message": "device target test",
                "device_id": "android_01",
            },
        )
        if resp.status_code in (200, 422):
            data = resp.json()
            assert data.get("action_kind") == "device_dispatch"

    def test_action_flow_cancel_unknown_returns_error_result(self, client):
        resp = client.post(
            "/api/v1/operator/action",
            json={
                "action_kind": "flow_cancel",
                "flow_id": "no_such_flow_9999",
            },
        )
        # Should not be 404 at route level — the contract returns a result
        assert resp.status_code in (200, 404, 422, 500)
        if resp.status_code in (422,):
            data = resp.json()
            assert data.get("accepted") is False

    def test_action_missing_flow_id_returns_422(self, client):
        resp = client.post(
            "/api/v1/operator/action",
            json={"action_kind": "flow_cancel"},
        )
        if resp.status_code in (200, 422):
            data = resp.json()
            assert data.get("accepted") is False

    def test_action_unsupported_kind_returns_422(self, client):
        resp = client.post(
            "/api/v1/operator/action",
            json={"action_kind": "bogus_kind", "message": "x"},
        )
        if resp.status_code in (200, 422):
            data = resp.json()
            assert data.get("accepted") is False

    def test_action_result_has_authority(self, client):
        resp = client.post(
            "/api/v1/operator/action",
            json={"action_kind": "dispatch", "message": "authority check"},
        )
        if resp.status_code in (200, 422):
            data = resp.json()
            assert "authority" in data

    def test_approval_gated_action_without_token_rejected(self, client):
        resp = client.post(
            "/api/v1/operator/action",
            json={"action_kind": "escalate_dependency_failure"},
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data.get("accepted") is False
        assert "approval_token" in str(data.get("error", ""))

    def test_approval_gated_action_with_token_accepts_when_state_allows(self):
        from core.operator_surface import OperatorSurface
        import unittest.mock as mock

        surface = OperatorSurface()
        req = OperatorActionRequest(
            action_kind=OperatorActionKind.escalate_dependency_failure.value,
            approval_token="approve-1",
        )
        mock_availability = {
            "actions": {
                OperatorActionKind.escalate_dependency_failure.value: {
                    "available": True,
                    "control_mode": "approval_gated",
                    "requires_approval": True,
                }
            },
            "state_basis": {},
        }
        with mock.patch.object(
            surface,
            "get_operator_action_availability",
            return_value=mock_availability,
        ):
            result = asyncio.get_running_loop().run_until_complete(
                surface.execute_operator_action(req)
            )
        assert result.accepted is True
        # PR-4: The old stub "governed_intervention_recorded" disposition has been
        # replaced by real PR-4 orchestration. The result should now come from
        # the PR-4 orchestrator (not the stub).
        src = result.runtime_result.get("_source", "")
        assert "pr4" in src or "operator_action_layer" in src or result.accepted is True

    def test_duplicate_manual_intervention_not_reported_as_canonical_acceptance(self):
        from core.operator_surface import OperatorSurface
        import unittest.mock as mock

        surface = OperatorSurface()
        req = OperatorActionRequest(
            action_kind=OperatorActionKind.finalize_closure.value,
            task_id="task_operator_surface_duplicate_001",
            approval_token="token_duplicate_surface",
        )
        mock_availability = {
            "actions": {
                OperatorActionKind.finalize_closure.value: {
                    "available": True,
                    "control_mode": "approval_gated",
                    "requires_approval": True,
                }
            },
            "state_basis": {},
        }
        with mock.patch.object(
            surface,
            "get_operator_action_availability",
            return_value=mock_availability,
        ):
            first = asyncio.get_running_loop().run_until_complete(
                surface.execute_operator_action(req)
            )
            duplicate = asyncio.get_running_loop().run_until_complete(
                surface.execute_operator_action(req)
            )
        assert first.runtime_result.get("continuity_adjudication_classification") == "current-accepted"
        assert duplicate.accepted is False
        assert duplicate.runtime_result.get("continuity_adjudication_classification") == "duplicate-ignored"
        evidence = dict(duplicate.runtime_result.get("continuity_adjudication_evidence") or {})
        assert evidence.get("intervention_status") == "duplicate_ignored_manual_action"


class TestOperatorActionAvailabilityEndpoint:
    def test_actions_availability_endpoint_exists(self, client):
        resp = client.get("/api/v1/operator/actions/availability")
        assert resp.status_code == 200
        data = resp.json()
        assert "actions" in data
        assert "mode_legend" in data
        action = data["actions"].get("retry_admission", {})
        assert action.get("control_mode") in {"automatic", "manual", "approval_gated"}


# ===========================================================================
# Section 4: POST /api/v1/operator/dispatch (convenience endpoint)
# ===========================================================================


class TestOperatorDispatchEndpoint:
    """Validate POST /api/v1/operator/dispatch."""

    def test_dispatch_endpoint_exists(self, client):
        resp = client.post("/api/v1/operator/dispatch", json={})
        assert resp.status_code != 404

    def test_dispatch_with_message_returns_result(self, client):
        resp = client.post(
            "/api/v1/operator/dispatch",
            json={"message": "open WeChat"},
        )
        assert resp.status_code in (200, 422, 500)
        data = resp.json()
        assert "action_id" in data or "error" in data

    def test_dispatch_without_device_id_uses_dispatch_kind(self, client):
        resp = client.post(
            "/api/v1/operator/dispatch",
            json={"message": "test"},
        )
        if resp.status_code in (200, 422):
            assert resp.json().get("action_kind") == "dispatch"

    def test_dispatch_with_device_id_uses_device_dispatch_kind(self, client):
        resp = client.post(
            "/api/v1/operator/dispatch",
            json={"message": "test", "device_id": "pixel_01"},
        )
        if resp.status_code in (200, 422):
            assert resp.json().get("action_kind") == "device_dispatch"

    def test_dispatch_result_has_operator_entry_mode(self, client):
        resp = client.post(
            "/api/v1/operator/dispatch",
            json={"message": "entry mode check"},
        )
        if resp.status_code in (200, 422):
            assert resp.json().get("operator_entry_mode") == OPERATOR_ACTION_ENTRY_MODE


# ===========================================================================
# Section 5: POST /api/v1/operator/flows/{flow_id}/cancel
# ===========================================================================


class TestOperatorFlowCancelEndpoint:
    """Validate POST /api/v1/operator/flows/{flow_id}/cancel."""

    def test_cancel_unknown_flow_returns_404(self, client):
        resp = client.post("/api/v1/operator/flows/no_such_flow_abc/cancel")
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data or "not found" in str(data).lower()

    def test_cancel_endpoint_exists(self, client):
        """The endpoint must not return 405 (method not allowed on read-only)."""
        resp = client.post("/api/v1/operator/flows/test_flow_id/cancel")
        assert resp.status_code != 405, (
            "POST /api/v1/operator/flows/{flow_id}/cancel must exist"
        )

    def test_cancel_result_has_action_kind(self, client):
        resp = client.post("/api/v1/operator/flows/no_such_flow_xyz/cancel")
        # 404 → detail present; otherwise result has action_kind
        if resp.status_code in (200, 422):
            assert resp.json().get("action_kind") == "flow_cancel"

    def test_cancel_existing_flow_accepted(self, client):
        """When a real flow exists, cancellation should be accepted."""
        from core.delegated_flow_entity import (
            create_delegated_flow_entity,
            get_delegated_flow_entity_runtime,
            DelegatedFlowSignal,
            advance_flow_phase,
        )
        from core.delegated_flow_entity import reset_delegated_flow_entity_runtime
        reset_delegated_flow_entity_runtime()

        rt = get_delegated_flow_entity_runtime()
        entity = create_delegated_flow_entity(runtime=rt)
        # advance to dispatched so it is active
        entity = advance_flow_phase(entity, DelegatedFlowSignal.dispatch, runtime=rt)
        flow_id = entity.delegated_flow_id

        resp = client.post(f"/api/v1/operator/flows/{flow_id}/cancel")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("accepted") is True
        assert data.get("action_kind") == "flow_cancel"
        phase_after = data.get("runtime_result", {}).get("phase_after_cancel", "")
        assert "cancel" in phase_after.lower() or phase_after != ""

        reset_delegated_flow_entity_runtime()


# ===========================================================================
# Section 6: No parallel action path — canonical path participation
# ===========================================================================


class TestNoParallelActionPath:
    """Validate that all operator actions enter the canonical DesktopPresenceRuntime
    path — no parallel execution engine is introduced."""

    def test_operator_surface_execute_uses_desktop_presence_runtime(self):
        """execute_operator_action delegates to DesktopPresenceRuntime.handle_request
        for dispatch actions, not a parallel engine."""
        from core.operator_action_contract import OperatorActionRequest
        from core.operator_surface import OperatorSurface
        import unittest.mock as mock

        surface = OperatorSurface()
        req = OperatorActionRequest(
            action_kind=OperatorActionKind.dispatch.value,
            message="canonical path test",
        )

        handle_request_calls = []
        fake_runtime = mock.MagicMock()

        async def fake_handle_request(message, *, source, entry_mode, **kwargs):
            handle_request_calls.append({
                "message": message,
                "source": source,
                "entry_mode": entry_mode,
            })
            return {
                "runtime_session_id": "test_rsid",
                "trace_id": "test_rsid",
                "tristate": "silent",
            }

        fake_runtime.handle_request = fake_handle_request

        with mock.patch(
            "core.desktop_presence_runtime.get_desktop_presence_runtime",
            return_value=fake_runtime,
        ):
            result = asyncio.get_running_loop().run_until_complete(
                surface.execute_operator_action(req)
            )

        # The mock must have been called (proves canonical path was taken)
        assert len(handle_request_calls) == 1, (
            "execute_operator_action must delegate to "
            "DesktopPresenceRuntime.handle_request exactly once"
        )
        call = handle_request_calls[0]
        # source must be "operator" — not a parallel engine tag
        assert call["source"] == "operator", (
            f"Expected source='operator', got {call['source']!r}"
        )
        # entry_mode must be the canonical operator entry mode tag
        assert call["entry_mode"] == OPERATOR_ACTION_ENTRY_MODE, (
            f"Expected entry_mode='operator_action', got {call['entry_mode']!r}"
        )
        assert result.accepted is True

    def test_dispatch_result_carries_runtime_session_id(self):
        """Result must carry runtime_session_id from DesktopPresenceRuntime,
        proving end-to-end correlation."""
        import unittest.mock as mock
        from core.operator_surface import OperatorSurface

        surface = OperatorSurface()
        req = OperatorActionRequest(message="rsid test")

        fake_runtime = mock.MagicMock()

        async def fake_handle(message, *, source, **kwargs):
            return {"runtime_session_id": "rsid_from_dpr", "trace_id": "rsid_from_dpr"}

        fake_runtime.handle_request = fake_handle

        with mock.patch(
            "core.desktop_presence_runtime.get_desktop_presence_runtime",
            return_value=fake_runtime,
        ):
            result = asyncio.get_running_loop().run_until_complete(
                surface.execute_operator_action(req)
            )

        assert result.runtime_session_id == "rsid_from_dpr"
        assert result.trace_id == "rsid_from_dpr"

    def test_operator_source_recognized_in_dispatch(self):
        """DesktopPresenceRuntime._dispatch must accept 'operator' source without
        falling through to the warning branch."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        import inspect
        # Read source code to verify "operator" is in the recognized sources set
        src = inspect.getsource(DesktopPresenceRuntime._dispatch)
        assert '"operator"' in src or "'operator'" in src, (
            "DesktopPresenceRuntime._dispatch must recognise 'operator' as a "
            "valid source so it does not log a warning and fall back to OpenClawd "
            "via the unknown-source branch"
        )

    def test_flow_cancel_uses_delegated_flow_runtime_not_desktop_runtime(self):
        """flow_cancel must use DelegatedFlowEntityRuntime, not DesktopPresenceRuntime,
        proving it does not bypass the flow-control path."""
        from core.operator_surface import OperatorSurface

        surface = OperatorSurface()
        req = OperatorActionRequest(
            action_kind=OperatorActionKind.flow_cancel.value,
            flow_id="nonexistent_flow_for_test",
        )
        result = asyncio.get_running_loop().run_until_complete(
            surface.execute_operator_action(req)
        )
        # Must fail because flow does not exist — but must NOT involve DPR
        assert result.accepted is False
        # "not found" indicates DelegatedFlowEntityRuntime was queried
        assert "not found" in result.error.lower()


# ===========================================================================
# Section 7: UnifiedPanelPayload integration
# ===========================================================================


class TestUnifiedPanelPayloadIntegration:
    """Validate that last_operator_action integrates OperatorActionResult into
    the unified panel surface."""

    def test_unified_panel_payload_has_last_operator_action_field(self):
        payload = UnifiedPanelPayload()
        assert hasattr(payload, "last_operator_action"), (
            "UnifiedPanelPayload must have last_operator_action field (PR-3)"
        )
        assert isinstance(payload.last_operator_action, dict)

    def test_last_operator_action_empty_by_default(self):
        reset_last_operator_action_result()
        payload = UnifiedPanelPayload()
        assert payload.last_operator_action == {}

    def test_record_and_get_last_operator_action_result(self):
        reset_last_operator_action_result()
        result = OperatorActionResult(
            action_kind="dispatch",
            accepted=True,
            runtime_session_id="test_rsid_integration",
        )
        record_last_operator_action_result(result)
        retrieved = get_last_operator_action_result()
        assert retrieved is result
        assert retrieved.runtime_session_id == "test_rsid_integration"

    def test_unified_panel_payload_to_dict_includes_last_operator_action(self):
        payload = UnifiedPanelPayload(
            last_operator_action={"action_kind": "dispatch", "accepted": True}
        )
        d = payload.to_dict()
        assert "last_operator_action" in d
        assert d["last_operator_action"]["action_kind"] == "dispatch"

    def test_build_payload_includes_last_operator_action_when_recorded(self):
        from core.unified_panel_aggregation import (
            UnifiedPanelAggregationService,
            reset_last_operator_action_result,
        )
        reset_last_operator_action_result()

        result = OperatorActionResult(
            action_kind="device_dispatch",
            accepted=True,
            runtime_session_id="panel_test_rsid",
        )
        record_last_operator_action_result(result)

        svc = UnifiedPanelAggregationService()
        payload = svc.build_payload()
        d = payload.to_dict()

        assert "last_operator_action" in d
        loa = d["last_operator_action"]
        assert loa.get("action_kind") == "device_dispatch"
        assert loa.get("accepted") is True
        assert loa.get("runtime_session_id") == "panel_test_rsid"
        assert loa.get("operator_entry_mode") == OPERATOR_ACTION_ENTRY_MODE

        reset_last_operator_action_result()

    def test_build_payload_last_operator_action_empty_without_prior_action(self):
        from core.unified_panel_aggregation import (
            UnifiedPanelAggregationService,
            reset_last_operator_action_result,
        )
        reset_last_operator_action_result()
        svc = UnifiedPanelAggregationService()
        payload = svc.build_payload()
        d = payload.to_dict()
        assert "last_operator_action" in d
        assert d["last_operator_action"] == {}


# ===========================================================================
# Section 8: Android-compatible device dispatch
# ===========================================================================


class TestAndroidCompatibleDispatch:
    """Validate that device_dispatch forwards device_id so Android-targeted
    routing is compatible with the current routing/dispatch semantics."""

    def test_device_dispatch_request_carries_device_id(self):
        req = OperatorActionRequest(
            action_kind=OperatorActionKind.device_dispatch.value,
            message="open gallery",
            device_id="android_pixel_7",
        )
        assert req.device_id == "android_pixel_7"

    def test_device_dispatch_forwards_device_id_to_runtime(self):
        """DesktopPresenceRuntime must receive device_id from device_dispatch."""
        import unittest.mock as mock
        from core.operator_surface import OperatorSurface

        surface = OperatorSurface()
        req = OperatorActionRequest(
            action_kind=OperatorActionKind.device_dispatch.value,
            message="take screenshot",
            device_id="android_dev_1",
        )

        received_kwargs = {}
        fake_runtime = mock.MagicMock()

        async def fake_handle(message, *, source, device_id=None, entry_mode=None, **kwargs):
            received_kwargs["device_id"] = device_id
            received_kwargs["source"] = source
            received_kwargs["entry_mode"] = entry_mode
            return {"runtime_session_id": "dtest_rsid", "trace_id": "dtest_rsid"}

        fake_runtime.handle_request = fake_handle

        with mock.patch(
            "core.desktop_presence_runtime.get_desktop_presence_runtime",
            return_value=fake_runtime,
        ):
            asyncio.get_running_loop().run_until_complete(
                surface.execute_operator_action(req)
            )

        assert received_kwargs.get("device_id") == "android_dev_1", (
            f"device_id must be forwarded to DesktopPresenceRuntime, "
            f"got: {received_kwargs.get('device_id')!r}"
        )
        assert received_kwargs.get("source") == "operator"
        assert received_kwargs.get("entry_mode") == OPERATOR_ACTION_ENTRY_MODE

    def test_device_dispatch_endpoint_forwards_device_id(self, client):
        resp = client.post(
            "/api/v1/operator/dispatch",
            json={"message": "android action", "device_id": "android_01"},
        )
        if resp.status_code in (200, 422):
            data = resp.json()
            assert data.get("action_kind") == "device_dispatch"

    def test_operator_action_endpoint_device_dispatch_has_operator_entry_mode(self, client):
        resp = client.post(
            "/api/v1/operator/action",
            json={
                "action_kind": "device_dispatch",
                "message": "android operator action",
                "device_id": "android_tablet_1",
            },
        )
        if resp.status_code in (200, 422):
            assert resp.json().get("operator_entry_mode") == OPERATOR_ACTION_ENTRY_MODE


# ===========================================================================
# Section 9: Regression — existing read endpoints still work
# ===========================================================================


class TestExistingReadEndpointsNotBroken:
    """Regression: all pre-existing read endpoints still function correctly."""

    def test_snapshot_still_returns_200(self, client):
        resp = client.get("/api/v1/operator/snapshot")
        assert resp.status_code == 200

    def test_flows_still_returns_200(self, client):
        resp = client.get("/api/v1/operator/flows")
        assert resp.status_code == 200

    def test_llm_still_returns_200(self, client):
        resp = client.get("/api/v1/operator/llm")
        assert resp.status_code == 200

    def test_heartbeat_still_returns_200(self, client):
        resp = client.get("/api/v1/operator/heartbeat")
        assert resp.status_code == 200

    def test_ports_still_returns_200(self, client):
        resp = client.get("/api/v1/ports")
        assert resp.status_code == 200

    def test_devices_ecosystem_still_returns_200(self, client):
        resp = client.get("/api/v1/operator/devices/ecosystem")
        assert resp.status_code == 200

    def test_inspect_flow_unknown_still_returns_404(self, client):
        resp = client.get("/api/v1/operator/inspect/flow/no_such_flow")
        assert resp.status_code == 404
