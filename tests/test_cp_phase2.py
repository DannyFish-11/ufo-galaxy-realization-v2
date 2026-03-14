"""
tests/test_cp_phase2.py
=======================

Control Plane Phase 2 integration tests.

Covers:
  A) Audit ledger captures events across the full chain and export works.
  B) Scheduler chooses the expected device when multiple candidates are available.
  C) SecurityInterceptor blocks a high-risk command until approval; resumes on ACK.
  D) Route smoke tests for /api/v1/audit/* and /api/v1/approvals/*.
"""

from __future__ import annotations

import asyncio
import pytest


# ===========================================================================
# A) Audit ledger – event sourcing
# ===========================================================================

class TestAuditLedgerIntegration:
    """Verify that audit events flow into the shared ledger and export works."""

    def test_emit_and_query_by_trace_id(self):
        """Events appended with the same trace_id are retrievable together."""
        from core.control_plane.audit_ledger import AuditLedger, EventType, Severity

        ledger = AuditLedger()
        trace_id = "trace_test_abc"

        eid1 = ledger.append(
            EventType.TASK_CREATED,
            trace_id=trace_id, task_id="task_1", source="test",
        )
        eid2 = ledger.append(
            EventType.TASK_STARTED,
            trace_id=trace_id, task_id="task_1", source="test",
            parent_ids=[eid1],
        )
        eid3 = ledger.append(
            EventType.TASK_COMPLETED,
            trace_id=trace_id, task_id="task_1", source="test",
            parent_ids=[eid2],
        )

        events = ledger.query(trace_id=trace_id)
        assert len(events) == 3
        ids = {e.event_id for e in events}
        assert eid1 in ids and eid2 in ids and eid3 in ids

    def test_full_chain_event_types(self):
        """All six chain stages can be appended: Intent→Plan→Tool→Dispatch→Exec→Result."""
        from core.control_plane.audit_ledger import AuditLedger, EventType

        ledger = AuditLedger()
        tid = "trace_chain"

        chain_types = [
            EventType.TASK_CREATED,       # Intent
            EventType.TASK_STARTED,       # Plan
            EventType.TASK_DISPATCHED,    # Dispatch / Tool Call
            EventType.AGENT_DISPATCHED,   # Device Exec
            EventType.TASK_COMPLETED,     # Result
        ]
        prev_id = None
        for et in chain_types:
            eid = ledger.append(
                et,
                trace_id=tid,
                task_id="task_chain",
                parent_ids=[prev_id] if prev_id else [],
            )
            prev_id = eid

        events = ledger.query(trace_id=tid)
        assert len(events) == len(chain_types)
        recorded_types = [e.event_type for e in events]
        for et in chain_types:
            assert et in recorded_types

    def test_export_as_json(self):
        """events_to_json produces a valid JSON array."""
        import json
        from core.control_plane.audit_ledger import AuditLedger, EventType, events_to_json

        ledger = AuditLedger()
        ledger.append(EventType.TASK_CREATED, trace_id="t1", task_id="task_j")
        ledger.append(EventType.TASK_COMPLETED, trace_id="t1", task_id="task_j")

        events = ledger.query(trace_id="t1")
        json_str = events_to_json(events)
        parsed = json.loads(json_str)
        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0]["event_type"] == "task_created"

    def test_export_as_dag(self):
        """events_to_dag returns a valid adjacency list."""
        from core.control_plane.audit_ledger import AuditLedger, EventType, events_to_dag

        ledger = AuditLedger()
        eid1 = ledger.append(EventType.TASK_CREATED, trace_id="t2")
        eid2 = ledger.append(EventType.TASK_COMPLETED, trace_id="t2", parent_ids=[eid1])

        events = ledger.query(trace_id="t2")
        dag = events_to_dag(events)
        assert eid1 in dag
        assert eid2 in dag
        assert dag[eid1] == []           # root event has no parents
        assert dag[eid2] == [eid1]       # second event points to root

    def test_snapshot(self):
        """Ledger snapshot captures all events."""
        from core.control_plane.audit_ledger import AuditLedger, EventType

        ledger = AuditLedger()
        for _ in range(5):
            ledger.append(EventType.TASK_CREATED)

        snap = ledger.snapshot()
        assert snap.event_count == 5
        assert len(snap.events) == 5


# ===========================================================================
# B) Smart scheduler – device selection
# ===========================================================================

class TestSmartSchedulerIntegration:
    """Verify that DeviceScoringEngine selects the expected device."""

    def _make_engine(self):
        from core.control_plane.smart_scheduler import DeviceScoringEngine
        return DeviceScoringEngine()

    def _make_device(self, device_id, *, status="online", ping=50.0, load=10.0, caps=None):
        from core.control_plane.smart_scheduler import DeviceScoreInput, SandboxLevel
        return DeviceScoreInput(
            device_id=device_id,
            status=status,
            ping_latency_ms=ping,
            load_pct=load,
            sandbox_level=SandboxLevel.NONE,
            capabilities=caps or [],
        )

    def test_selects_best_device_by_score(self):
        """Higher-score device (lower load/latency) is preferred."""
        engine = self._make_engine()
        fast = self._make_device("fast_device", ping=10.0, load=5.0)
        slow = self._make_device("slow_device", ping=800.0, load=80.0)

        best = engine.select_best_device([slow, fast])
        assert best is not None
        assert best.device_id == "fast_device"

    def test_filters_by_required_capabilities(self):
        """Only devices with required capabilities are eligible."""
        engine = self._make_engine()

        capable = self._make_device("capable", caps=["screen", "touch", "keyboard"])
        incapable = self._make_device("incapable", caps=["camera"])

        best = engine.select_best_device([capable, incapable], required_capabilities=["screen", "keyboard"])
        assert best is not None
        assert best.device_id == "capable"

    def test_no_eligible_device_returns_none(self):
        """Returns None when no device meets capability requirements."""
        engine = self._make_engine()
        d = self._make_device("dev1", caps=["camera"])
        best = engine.select_best_device([d], required_capabilities=["screen"])
        assert best is None

    def test_offline_device_excluded(self):
        """Offline devices are never selected."""
        engine = self._make_engine()
        online = self._make_device("online_dev", status="online", ping=100.0)
        offline = self._make_device("offline_dev", status="offline", ping=1.0)

        best = engine.select_best_device([online, offline])
        assert best is not None
        assert best.device_id == "online_dev"

    def test_rank_devices_order(self):
        """rank_devices returns devices sorted highest score first."""
        engine = self._make_engine()
        devices = [
            self._make_device("d1", ping=200.0, load=50.0),
            self._make_device("d2", ping=10.0, load=5.0),
            self._make_device("d3", ping=100.0, load=20.0),
        ]
        ranked = engine.rank_devices(devices)
        assert ranked[0].device_id == "d2"   # best score

    def test_multiple_candidates_all_eligible(self):
        """When all devices are eligible, the best-scored one is returned."""
        engine = self._make_engine()
        devices = [
            self._make_device("dev_a", ping=50.0, load=40.0, caps=["screen"]),
            self._make_device("dev_b", ping=30.0, load=20.0, caps=["screen"]),
            self._make_device("dev_c", ping=80.0, load=60.0, caps=["screen"]),
        ]
        best = engine.select_best_device(devices, required_capabilities=["screen"])
        assert best is not None
        assert best.device_id == "dev_b"


# ===========================================================================
# C) Security Interceptor – HITL gate
# ===========================================================================

class TestSecurityInterceptorIntegration:
    """Verify async suspend/resume and timeout/deny behaviour."""

    @pytest.mark.asyncio
    async def test_approval_resumes_on_ack(self):
        """require_approval() resumes once the operator ACKs."""
        from core.control_plane.security_interceptor import (
            ApprovalRegistry, SecurityInterceptor, RiskLevel,
        )

        registry = ApprovalRegistry()
        interceptor = SecurityInterceptor(registry=registry, default_timeout=5.0)

        result_holder: list = []

        async def _task():
            token = await interceptor.require_approval(
                action="delete_data",
                task_id="task_hitl_1",
                risk_level=RiskLevel.HIGH,
                requestor="test",
            )
            result_holder.append(token)

        task_coro = asyncio.create_task(_task())
        await asyncio.sleep(0.05)   # let require_approval register

        pending = registry.list_pending()
        assert len(pending) == 1
        req = pending[0]

        # Operator approves
        registry.ack(req.request_id, req.ack_token, operator="test_op")
        await task_coro

        assert len(result_holder) == 1
        assert result_holder[0] == req.ack_token

    @pytest.mark.asyncio
    async def test_approval_denied_raises_error(self):
        """require_approval() raises ApprovalDeniedError when denied."""
        from core.control_plane.security_interceptor import (
            ApprovalRegistry, SecurityInterceptor, RiskLevel, ApprovalDeniedError,
        )

        registry = ApprovalRegistry()
        interceptor = SecurityInterceptor(registry=registry, default_timeout=5.0)

        denied_flag: list = []

        async def _task():
            try:
                await interceptor.require_approval(
                    action="factory_reset",
                    task_id="task_hitl_deny",
                    risk_level=RiskLevel.CRITICAL,
                    requestor="test",
                )
            except ApprovalDeniedError:
                denied_flag.append(True)

        task_coro = asyncio.create_task(_task())
        await asyncio.sleep(0.05)

        pending = registry.list_pending()
        assert len(pending) == 1
        registry.deny(pending[0].request_id, reason="Not allowed")
        await task_coro

        assert denied_flag == [True]

    @pytest.mark.asyncio
    async def test_approval_timeout_raises_error(self):
        """require_approval() raises ApprovalTimeoutError after timeout."""
        from core.control_plane.security_interceptor import (
            ApprovalRegistry, SecurityInterceptor, RiskLevel, ApprovalTimeoutError,
        )

        registry = ApprovalRegistry()
        interceptor = SecurityInterceptor(registry=registry, default_timeout=0.1)

        timed_out: list = []

        async def _task():
            try:
                await interceptor.require_approval(
                    action="shutdown",
                    task_id="task_hitl_timeout",
                    risk_level=RiskLevel.HIGH,
                    requestor="test",
                )
            except ApprovalTimeoutError as e:
                timed_out.append(e.request_id)

        await asyncio.gather(_task())
        assert len(timed_out) == 1

    @pytest.mark.asyncio
    async def test_bypass_auto_approves(self):
        """bypass() auto-approves without waiting."""
        from core.control_plane.security_interceptor import (
            ApprovalRegistry, SecurityInterceptor, RiskLevel,
        )

        registry = ApprovalRegistry()
        interceptor = SecurityInterceptor(registry=registry)

        token = await interceptor.bypass(
            action="heartbeat_update",
            task_id="task_bypass",
            risk_level=RiskLevel.LOW,
        )
        assert isinstance(token, str)
        assert len(token) > 0


# ===========================================================================
# D) Route smoke tests
# ===========================================================================

class TestAuditRoutes:
    """Smoke tests for /api/v1/audit/* using TestClient."""

    def _get_app(self):
        """Build a minimal FastAPI app with only the audit router."""
        from fastapi import FastAPI
        from core.routes.audit import create_router
        app = FastAPI()
        app.include_router(create_router())
        return app

    def test_list_events_empty(self):
        """GET /api/v1/audit/traces returns 200 with empty list when ledger is empty."""
        from fastapi.testclient import TestClient
        # Use a fresh ledger for this test
        import core.control_plane._globals as g
        orig = g._audit_ledger
        g._audit_ledger = None  # reset singleton
        try:
            app = self._get_app()
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get("/api/v1/audit/traces?limit=10")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["count"] == 0
        finally:
            g._audit_ledger = orig

    def test_get_trace_json(self):
        """GET /api/v1/audit/traces/{trace_id} returns events for that trace."""
        from fastapi.testclient import TestClient
        import core.control_plane._globals as g
        from core.control_plane.audit_ledger import AuditLedger, EventType

        ledger = AuditLedger()
        ledger.append(EventType.TASK_CREATED, trace_id="trace_route_test", task_id="t1")
        orig = g._audit_ledger
        g._audit_ledger = ledger
        try:
            app = self._get_app()
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get("/api/v1/audit/traces/trace_route_test")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["count"] == 1
        finally:
            g._audit_ledger = orig

    def test_get_trace_dag(self):
        """GET /api/v1/audit/traces/{trace_id}/dag returns adjacency list."""
        from fastapi.testclient import TestClient
        import core.control_plane._globals as g
        from core.control_plane.audit_ledger import AuditLedger, EventType

        ledger = AuditLedger()
        eid1 = ledger.append(EventType.TASK_CREATED, trace_id="trace_dag_test")
        ledger.append(EventType.TASK_COMPLETED, trace_id="trace_dag_test", parent_ids=[eid1])
        orig = g._audit_ledger
        g._audit_ledger = ledger
        try:
            app = self._get_app()
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get("/api/v1/audit/traces/trace_dag_test/dag")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["node_count"] == 2
            assert eid1 in data["dag"]
        finally:
            g._audit_ledger = orig

    def test_trace_not_found(self):
        """GET /api/v1/audit/traces/nonexistent returns 404."""
        from fastapi.testclient import TestClient
        import core.control_plane._globals as g
        from core.control_plane.audit_ledger import AuditLedger

        orig = g._audit_ledger
        g._audit_ledger = AuditLedger()
        try:
            app = self._get_app()
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get("/api/v1/audit/traces/nonexistent_trace")
            assert resp.status_code == 404
        finally:
            g._audit_ledger = orig


class TestApprovalRoutes:
    """Smoke tests for /api/v1/approvals/* using TestClient."""

    def _setup(self):
        """Build a minimal FastAPI app with approvals router and a fresh registry."""
        from fastapi import FastAPI
        from core.routes.approvals import create_router
        import core.control_plane._globals as g
        from core.control_plane.security_interceptor import ApprovalRegistry

        registry = ApprovalRegistry()
        orig_registry = g._approval_registry
        orig_interceptor = g._security_interceptor
        g._approval_registry = registry
        g._security_interceptor = None  # reset so it picks up new registry

        app = FastAPI()
        app.include_router(create_router())
        return app, registry, (orig_registry, orig_interceptor)

    def _teardown(self, orig):
        import core.control_plane._globals as g
        g._approval_registry, g._security_interceptor = orig

    def test_list_approvals_empty(self):
        """GET /api/v1/approvals returns empty list initially."""
        from fastapi.testclient import TestClient

        app, registry, orig = self._setup()
        try:
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get("/api/v1/approvals")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["count"] == 0
        finally:
            self._teardown(orig)

    def test_approve_via_api(self):
        """POST /api/v1/approvals/{id} with valid token returns approved."""
        from fastapi.testclient import TestClient
        from core.control_plane.security_interceptor import ApprovalRequest, RiskLevel

        app, registry, orig = self._setup()
        try:
            # Register a request manually
            req = ApprovalRequest(
                action="delete_test",
                task_id="task_route_test",
                risk_level=RiskLevel.HIGH,
                requestor="test",
            )
            registry._register(req)

            client = TestClient(app, raise_server_exceptions=True)

            # Approve it
            resp = client.post(
                f"/api/v1/approvals/{req.request_id}",
                json={"action": "approve", "token": req.ack_token, "operator": "tester"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["result"] == "approved"
        finally:
            self._teardown(orig)

    def test_deny_via_api(self):
        """POST /api/v1/approvals/{id} with action=deny returns denied."""
        from fastapi.testclient import TestClient
        from core.control_plane.security_interceptor import ApprovalRequest, RiskLevel

        app, registry, orig = self._setup()
        try:
            req = ApprovalRequest(
                action="format_disk",
                task_id="task_deny_test",
                risk_level=RiskLevel.CRITICAL,
                requestor="test",
            )
            registry._register(req)

            client = TestClient(app, raise_server_exceptions=True)
            resp = client.post(
                f"/api/v1/approvals/{req.request_id}",
                json={"action": "deny", "reason": "Not allowed"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["result"] == "denied"
        finally:
            self._teardown(orig)

    def test_approve_invalid_token_rejected(self):
        """POST with wrong token returns 400."""
        from fastapi.testclient import TestClient
        from core.control_plane.security_interceptor import ApprovalRequest, RiskLevel

        app, registry, orig = self._setup()
        try:
            req = ApprovalRequest(
                action="rm_rf",
                task_id="task_bad_token",
                risk_level=RiskLevel.HIGH,
                requestor="test",
            )
            registry._register(req)

            client = TestClient(app, raise_server_exceptions=True)
            resp = client.post(
                f"/api/v1/approvals/{req.request_id}",
                json={"action": "approve", "token": "wrong_token"},
            )
            assert resp.status_code == 400
        finally:
            self._teardown(orig)

    def test_get_nonexistent_approval_404(self):
        """GET /api/v1/approvals/unknown returns 404."""
        from fastapi.testclient import TestClient

        app, registry, orig = self._setup()
        try:
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get("/api/v1/approvals/nonexistent_id")
            assert resp.status_code == 404
        finally:
            self._teardown(orig)
