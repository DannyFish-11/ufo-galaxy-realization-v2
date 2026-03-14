#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_phase5_self_healing.py
===================================

Phase 5 PR1 — Multi-device self-healing and circuit-breaker tests.

Covers:
  A) DeviceHealthRegistry — unit tests for circuit-breaker transitions,
     quarantine behaviour, and health-score calculation.
  B) DeviceScoringEngine  — health score incorporated into ranking;
     QUARANTINED / CIRCUIT_OPEN statuses disqualify devices.
  C) CommandRouter        — retry routing on simulated device failure;
     audit events emitted correctly (TASK_RETRY_SCHEDULED, etc.).
  D) Audit ledger         — new Phase 5 event types present and usable.
  E) Device Health API    — smoke tests for /health and /unquarantine routes.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ===========================================================================
# A) DeviceHealthRegistry — circuit breaker transitions + quarantine
# ===========================================================================

class TestCircuitBreakerTransitions:
    """Unit tests for the circuit-breaker state machine."""

    def _make_registry(self, **kwargs):
        from core.control_plane.device_health_registry import DeviceHealthRegistry
        return DeviceHealthRegistry(**kwargs)

    def test_starts_closed(self):
        reg = self._make_registry()
        assert reg.is_eligible("dev1")
        state = reg.get_state("dev1")
        assert state is None  # unknown device → optimistically eligible

    def test_closed_to_open_after_threshold(self):
        from core.control_plane.device_health_registry import CircuitState
        reg = self._make_registry(circuit_failure_threshold=3)
        for _ in range(3):
            reg.record_failure("dev1", error="timeout")
        state = reg.get_state("dev1")
        assert state.circuit_state == CircuitState.OPEN
        assert not reg.is_eligible("dev1")

    def test_below_threshold_stays_closed(self):
        from core.control_plane.device_health_registry import CircuitState
        reg = self._make_registry(circuit_failure_threshold=5)
        for _ in range(4):
            reg.record_failure("dev1")
        state = reg.get_state("dev1")
        assert state.circuit_state == CircuitState.CLOSED
        assert reg.is_eligible("dev1")

    def test_open_transitions_to_half_open_after_cooldown(self):
        from core.control_plane.device_health_registry import CircuitState
        reg = self._make_registry(circuit_failure_threshold=2, circuit_cooldown_seconds=0.05)
        reg.record_failure("dev1")
        reg.record_failure("dev1")
        assert not reg.is_eligible("dev1")

        # Wait for cooldown
        time.sleep(0.1)
        # is_eligible triggers HALF_OPEN check
        result = reg.is_eligible("dev1")
        state = reg.get_state("dev1")
        assert state.circuit_state == CircuitState.HALF_OPEN
        assert result  # HALF_OPEN allows probe requests

    def test_half_open_to_closed_on_success(self):
        from core.control_plane.device_health_registry import CircuitState
        reg = self._make_registry(circuit_failure_threshold=2, circuit_cooldown_seconds=0.05)
        reg.record_failure("dev1")
        reg.record_failure("dev1")
        time.sleep(0.1)
        reg.is_eligible("dev1")  # transition to HALF_OPEN

        reg.record_success("dev1")
        state = reg.get_state("dev1")
        assert state.circuit_state == CircuitState.CLOSED
        assert reg.is_eligible("dev1")

    def test_half_open_to_open_on_failure(self):
        from core.control_plane.device_health_registry import CircuitState
        reg = self._make_registry(circuit_failure_threshold=2, circuit_cooldown_seconds=0.05)
        reg.record_failure("dev1")
        reg.record_failure("dev1")
        time.sleep(0.1)
        reg.is_eligible("dev1")  # transition to HALF_OPEN

        reg.record_failure("dev1")
        state = reg.get_state("dev1")
        assert state.circuit_state == CircuitState.OPEN
        assert not reg.is_eligible("dev1")

    def test_success_resets_consecutive_failures(self):
        from core.control_plane.device_health_registry import CircuitState
        reg = self._make_registry(circuit_failure_threshold=5)
        for _ in range(3):
            reg.record_failure("dev1")
        reg.record_success("dev1")
        state = reg.get_state("dev1")
        assert state.consecutive_failures == 0
        assert state.circuit_state == CircuitState.CLOSED

    def test_circuit_open_event_emitted(self):
        events = []

        def _cb(event_name, device_id, **kw):
            events.append(event_name)

        reg = self._make_registry(circuit_failure_threshold=2)
        reg.set_event_callback(_cb)
        reg.record_failure("dev1")
        reg.record_failure("dev1")
        assert "DEVICE_CIRCUIT_OPEN" in events

    def test_circuit_closed_event_emitted(self):
        events = []

        def _cb(event_name, device_id, **kw):
            events.append(event_name)

        reg = self._make_registry(circuit_failure_threshold=2, circuit_cooldown_seconds=0.05)
        reg.set_event_callback(_cb)
        reg.record_failure("dev1")
        reg.record_failure("dev1")
        time.sleep(0.1)
        reg.is_eligible("dev1")  # HALF_OPEN
        reg.record_success("dev1")
        assert "DEVICE_CIRCUIT_CLOSED" in events

    def test_half_open_event_emitted(self):
        events = []

        def _cb(event_name, device_id, **kw):
            events.append(event_name)

        reg = self._make_registry(circuit_failure_threshold=2, circuit_cooldown_seconds=0.05)
        reg.set_event_callback(_cb)
        reg.record_failure("dev1")
        reg.record_failure("dev1")
        time.sleep(0.1)
        reg.is_eligible("dev1")
        assert "DEVICE_CIRCUIT_HALF_OPEN" in events


class TestQuarantineBehaviour:
    """Unit tests for device quarantine logic."""

    def _make_registry(self, **kwargs):
        from core.control_plane.device_health_registry import DeviceHealthRegistry
        return DeviceHealthRegistry(**kwargs)

    def test_quarantine_triggered_after_window_threshold(self):
        reg = self._make_registry(quarantine_threshold=5, quarantine_window_seconds=60.0)
        for _ in range(5):
            reg.record_failure("dev1")
        state = reg.get_state("dev1")
        assert state.quarantined
        assert not reg.is_eligible("dev1")

    def test_quarantine_not_triggered_below_threshold(self):
        reg = self._make_registry(quarantine_threshold=5, quarantine_window_seconds=60.0)
        for _ in range(4):
            reg.record_failure("dev1")
        state = reg.get_state("dev1")
        assert not state.quarantined

    def test_unquarantine_restores_eligibility(self):
        reg = self._make_registry(quarantine_threshold=3)
        for _ in range(3):
            reg.record_failure("dev1")
        assert not reg.is_eligible("dev1")

        was_q = reg.unquarantine("dev1")
        assert was_q
        assert reg.is_eligible("dev1")

    def test_unquarantine_returns_false_when_not_quarantined(self):
        reg = self._make_registry()
        reg.record_heartbeat("dev1")
        was_q = reg.unquarantine("dev1")
        assert not was_q

    def test_unquarantine_resets_circuit_state(self):
        from core.control_plane.device_health_registry import CircuitState
        reg = self._make_registry(quarantine_threshold=3, circuit_failure_threshold=3)
        for _ in range(3):
            reg.record_failure("dev1")
        reg.unquarantine("dev1")
        state = reg.get_state("dev1")
        assert state.circuit_state == CircuitState.CLOSED
        assert state.consecutive_failures == 0


class TestHealthScore:
    """Verify health score is in [0, 100] and responds to latency/error signals."""

    def _make_registry(self):
        from core.control_plane.device_health_registry import DeviceHealthRegistry
        return DeviceHealthRegistry()

    def test_perfect_health_on_fresh_device(self):
        reg = self._make_registry()
        reg.record_heartbeat("dev1", latency_ms=0.0)
        state = reg.get_state("dev1")
        assert state.health_score == pytest.approx(100.0, abs=1.0)

    def test_high_latency_lowers_health_score(self):
        reg = self._make_registry()
        reg.record_heartbeat("dev1", latency_ms=0.0)
        reg.record_heartbeat("dev2", latency_ms=1900.0)
        s1 = reg.get_state("dev1")
        s2 = reg.get_state("dev2")
        assert s1.health_score > s2.health_score

    def test_failures_lower_health_score(self):
        reg = self._make_registry()
        reg.record_heartbeat("dev1")
        reg.record_failure("dev1")
        reg.record_failure("dev1")
        state = reg.get_state("dev1")
        assert state.health_score < 100.0

    def test_health_score_bounded(self):
        reg = self._make_registry()
        for _ in range(5):
            reg.record_failure("dev1")
        state = reg.get_state("dev1")
        assert 0.0 <= state.health_score <= 100.0


# ===========================================================================
# B) DeviceScoringEngine — health integration
# ===========================================================================

class TestScoringWithHealth:
    """Verify that the scoring engine incorporates health and rejects
    QUARANTINED / CIRCUIT_OPEN devices."""

    def _engine(self):
        from core.control_plane.smart_scheduler import DeviceScoringEngine
        return DeviceScoringEngine()

    def _device(self, device_id="d1", status="online", health=100.0):
        from core.control_plane.smart_scheduler import DeviceScoreInput, SandboxLevel
        return DeviceScoreInput(
            device_id=device_id,
            status=status,
            ping_latency_ms=10.0,
            load_pct=10.0,
            sandbox_level=SandboxLevel.NONE,
            capabilities=["screen"],
            health_score=health,
        )

    def test_quarantined_device_ineligible(self):
        from core.control_plane.smart_scheduler import DeviceStatus
        eng = self._engine()
        d = self._device(status=DeviceStatus.QUARANTINED)
        score = eng.score_device(d)
        assert not score.eligible
        assert score.disqualify_reason is not None

    def test_circuit_open_device_ineligible(self):
        from core.control_plane.smart_scheduler import DeviceStatus
        eng = self._engine()
        d = self._device(status=DeviceStatus.CIRCUIT_OPEN)
        score = eng.score_device(d)
        assert not score.eligible

    def test_healthy_device_scores_higher_than_unhealthy(self):
        eng = self._engine()
        healthy = self._device("good", health=100.0)
        unhealthy = self._device("bad", health=10.0)
        s_good = eng.score_device(healthy)
        s_bad = eng.score_device(unhealthy)
        assert s_good.total > s_bad.total

    def test_health_score_normalised_in_result(self):
        eng = self._engine()
        d = self._device(health=80.0)
        score = eng.score_device(d)
        assert score.health_score == pytest.approx(0.8, abs=0.01)

    def test_select_best_prefers_healthier_device(self):
        eng = self._engine()
        good = self._device("good", health=100.0)
        bad = self._device("bad", health=20.0)
        best = eng.select_best_device([bad, good])
        assert best is not None
        assert best.device_id == "good"


# ===========================================================================
# C) CommandRouter — retry routing on simulated device failure
# ===========================================================================

class TestCommandRouterRetry:
    """Integration tests for retry-routing when a device fails."""

    def _router(self):
        from core.command_router import CommandRouter
        return CommandRouter()

    def _candidate(self, device_id, health=100.0):
        from core.control_plane.smart_scheduler import DeviceScoreInput, SandboxLevel
        return DeviceScoreInput(
            device_id=device_id,
            ping_latency_ms=10.0,
            load_pct=5.0,
            sandbox_level=SandboxLevel.NONE,
            capabilities=["screen"],
            health_score=health,
        )

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_device(self):
        """When device_1 fails, the router retries on device_2 and succeeds."""
        router = self._router()
        calls = []

        async def executor(device_id, command, payload):
            calls.append(device_id)
            if device_id == "dev1":
                raise ConnectionError("dev1 disconnected")
            return {"ok": True}

        router.set_executor(executor)

        candidates = [self._candidate("dev1"), self._candidate("dev2")]
        result = await router.route_command(
            device_id="dev1",
            command="ping",
            payload={},
            command_id="cmd1",
            task_id="task1",
            timeout=5.0,
            retry_candidates=candidates,
            max_retries=2,
        )
        assert result["success"]
        assert "dev2" in calls

    @pytest.mark.asyncio
    async def test_no_retry_without_candidates(self):
        """Without retry_candidates, failure is returned immediately."""
        router = self._router()

        async def executor(device_id, command, payload):
            raise ConnectionError("disconnected")

        router.set_executor(executor)
        result = await router.route_command(
            device_id="dev1",
            command="ping",
            payload={},
            command_id="cmd1",
            task_id="task1",
            timeout=5.0,
        )
        assert not result["success"]

    @pytest.mark.asyncio
    async def test_retry_respects_max_retries(self):
        """Even with many candidates, retries stop at max_retries."""
        router = self._router()
        attempted = []

        async def executor(device_id, command, payload):
            attempted.append(device_id)
            raise ConnectionError("always fails")

        router.set_executor(executor)
        candidates = [self._candidate(f"dev{i}") for i in range(5)]
        result = await router.route_command(
            device_id="dev0",
            command="ping",
            payload={},
            command_id="cmd1",
            task_id="task1",
            timeout=5.0,
            retry_candidates=candidates,
            max_retries=2,
        )
        assert not result["success"]
        # original attempt + at most max_retries attempts
        assert len(attempted) <= 3

    @pytest.mark.asyncio
    async def test_retry_emits_audit_events(self):
        """TASK_RETRY_SCHEDULED and TASK_RETRY_SUCCEEDED are emitted."""
        from core.control_plane.audit_ledger import AuditLedger, EventType
        from core.control_plane._globals import get_audit_ledger

        # Use a fresh ledger so we can inspect events cleanly
        fresh_ledger = AuditLedger()

        router = self._router()

        async def executor(device_id, command, payload):
            if device_id == "dev1":
                raise ConnectionError("dev1 disconnected")
            return {"ok": True}

        router.set_executor(executor)
        candidates = [self._candidate("dev1"), self._candidate("dev2")]

        with patch(
            "core.control_plane._globals._audit_ledger", fresh_ledger
        ):
            result = await router.route_command(
                device_id="dev1",
                command="ping",
                payload={},
                command_id="cmd_audit",
                task_id="task_audit",
                timeout=5.0,
                retry_candidates=candidates,
                max_retries=2,
            )

        assert result["success"]
        scheduled = fresh_ledger.query(event_type=EventType.TASK_RETRY_SCHEDULED)
        succeeded = fresh_ledger.query(event_type=EventType.TASK_RETRY_SUCCEEDED)
        assert len(scheduled) >= 1
        assert len(succeeded) >= 1

    @pytest.mark.asyncio
    async def test_all_retries_fail_emits_task_retry_failed(self):
        """TASK_RETRY_FAILED is emitted when all retries are exhausted."""
        from core.control_plane.audit_ledger import AuditLedger, EventType

        fresh_ledger = AuditLedger()
        router = self._router()

        async def executor(device_id, command, payload):
            raise ConnectionError("always fails")

        router.set_executor(executor)
        candidates = [self._candidate("dev1"), self._candidate("dev2")]

        with patch(
            "core.control_plane._globals._audit_ledger", fresh_ledger
        ):
            result = await router.route_command(
                device_id="dev1",
                command="ping",
                payload={},
                command_id="cmd_fail",
                task_id="task_fail",
                timeout=5.0,
                retry_candidates=candidates,
                max_retries=1,
            )

        assert not result["success"]
        failed = fresh_ledger.query(event_type=EventType.TASK_RETRY_FAILED)
        assert len(failed) >= 1

    @pytest.mark.asyncio
    async def test_quarantined_device_skipped_in_retry(self):
        """A quarantined device is not tried even when listed as a candidate."""
        from core.control_plane.device_health_registry import DeviceHealthRegistry

        fresh_reg = DeviceHealthRegistry(quarantine_threshold=1)
        fresh_reg.record_failure("dev2")  # quarantine dev2 immediately

        router = self._router()
        attempted = []

        async def executor(device_id, command, payload):
            attempted.append(device_id)
            if device_id == "dev1":
                raise ConnectionError("dev1 failed")
            return {"ok": True}

        router.set_executor(executor)
        candidates = [self._candidate("dev1"), self._candidate("dev2"), self._candidate("dev3")]

        with patch("core.control_plane._globals._health_registry", fresh_reg):
            result = await router.route_command(
                device_id="dev1",
                command="ping",
                payload={},
                command_id="cmd_q",
                task_id="task_q",
                timeout=5.0,
                retry_candidates=candidates,
                max_retries=2,
            )

        assert result["success"]
        assert "dev2" not in attempted
        assert "dev3" in attempted


# ===========================================================================
# D) Audit ledger — Phase 5 event types
# ===========================================================================

class TestPhase5EventTypes:
    """Verify that all new Phase 5 event types exist and can be appended."""

    def test_new_event_types_exist(self):
        from core.control_plane.audit_ledger import EventType
        assert hasattr(EventType, "DEVICE_HEALTH_CHANGED")
        assert hasattr(EventType, "DEVICE_CIRCUIT_OPEN")
        assert hasattr(EventType, "DEVICE_CIRCUIT_HALF_OPEN")
        assert hasattr(EventType, "DEVICE_CIRCUIT_CLOSED")
        assert hasattr(EventType, "TASK_RETRY_SCHEDULED")
        assert hasattr(EventType, "TASK_RETRY_SUCCEEDED")
        assert hasattr(EventType, "TASK_RETRY_FAILED")

    def test_all_new_types_appendable_to_ledger(self):
        from core.control_plane.audit_ledger import AuditLedger, EventType

        ledger = AuditLedger()
        new_types = [
            EventType.DEVICE_HEALTH_CHANGED,
            EventType.DEVICE_CIRCUIT_OPEN,
            EventType.DEVICE_CIRCUIT_HALF_OPEN,
            EventType.DEVICE_CIRCUIT_CLOSED,
            EventType.TASK_RETRY_SCHEDULED,
            EventType.TASK_RETRY_SUCCEEDED,
            EventType.TASK_RETRY_FAILED,
        ]
        for et in new_types:
            eid = ledger.append(et, device_id="dev1", task_id="t1")
            assert eid is not None

        assert len(ledger) == len(new_types)

    def test_health_events_round_trip_via_query(self):
        from core.control_plane.audit_ledger import AuditLedger, EventType

        ledger = AuditLedger()
        ledger.append(EventType.DEVICE_CIRCUIT_OPEN, device_id="dev1")
        ledger.append(EventType.DEVICE_CIRCUIT_CLOSED, device_id="dev1")

        open_events = ledger.query(event_type=EventType.DEVICE_CIRCUIT_OPEN)
        closed_events = ledger.query(event_type=EventType.DEVICE_CIRCUIT_CLOSED)
        assert len(open_events) == 1
        assert len(closed_events) == 1

    def test_globals_wires_circuit_events_to_ledger(self):
        """The get_health_registry() singleton should emit DEVICE_CIRCUIT_OPEN
        into the audit ledger when a device trips the breaker."""
        from core.control_plane.audit_ledger import AuditLedger, EventType
        import core.control_plane._globals as _g

        # Isolate with fresh singletons
        old_hr = _g._health_registry
        old_al = _g._audit_ledger
        _g._health_registry = None
        _g._audit_ledger = None
        try:
            reg = _g.get_health_registry()
            # trigger 5 failures to open circuit
            for _ in range(5):
                reg.record_failure("devX")
            ledger = _g.get_audit_ledger()
            events = ledger.query(event_type=EventType.DEVICE_CIRCUIT_OPEN)
            assert len(events) >= 1
        finally:
            _g._health_registry = old_hr
            _g._audit_ledger = old_al


# ===========================================================================
# E) Device Health API — smoke tests
# ===========================================================================

class TestDeviceHealthAPI:
    """Basic route smoke tests using FastAPI TestClient."""

    def _app(self):
        from fastapi import FastAPI
        from core.routes.device_health import router
        app = FastAPI()
        app.include_router(router)
        return app

    def test_list_health_returns_list(self):
        from fastapi.testclient import TestClient
        import core.control_plane._globals as _g

        old_hr = _g._health_registry
        _g._health_registry = None
        try:
            reg = _g.get_health_registry()
            reg.record_heartbeat("api_dev", latency_ms=50.0)

            client = TestClient(self._app())
            resp = client.get("/api/v1/devices/health")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            ids = [d["device_id"] for d in data]
            assert "api_dev" in ids
        finally:
            _g._health_registry = old_hr

    def test_get_health_for_specific_device(self):
        from fastapi.testclient import TestClient
        import core.control_plane._globals as _g

        old_hr = _g._health_registry
        _g._health_registry = None
        try:
            reg = _g.get_health_registry()
            reg.record_heartbeat("mydev", latency_ms=100.0)

            client = TestClient(self._app())
            resp = client.get("/api/v1/devices/mydev/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["device_id"] == "mydev"
            assert "circuit_state" in data
            assert "health_score" in data
        finally:
            _g._health_registry = old_hr

    def test_get_health_404_for_unknown_device(self):
        from fastapi.testclient import TestClient
        import core.control_plane._globals as _g

        old_hr = _g._health_registry
        _g._health_registry = None
        try:
            client = TestClient(self._app())
            resp = client.get("/api/v1/devices/ghost_device/health")
            assert resp.status_code == 404
        finally:
            _g._health_registry = old_hr

    def test_unquarantine_device(self):
        from fastapi.testclient import TestClient
        import core.control_plane._globals as _g

        old_hr = _g._health_registry
        old_al = _g._audit_ledger
        _g._health_registry = None
        _g._audit_ledger = None
        try:
            reg = _g.get_health_registry()
            # quarantine by repeated failures
            for _ in range(10):
                reg.record_failure("qdev")
            assert not reg.is_eligible("qdev")

            client = TestClient(self._app())
            resp = client.post("/api/v1/devices/qdev/unquarantine")
            assert resp.status_code == 200
            data = resp.json()
            assert data["was_quarantined"] is True
            assert reg.is_eligible("qdev")
        finally:
            _g._health_registry = old_hr
            _g._audit_ledger = old_al

    def test_unquarantine_non_quarantined_device_is_noop(self):
        from fastapi.testclient import TestClient
        import core.control_plane._globals as _g

        old_hr = _g._health_registry
        old_al = _g._audit_ledger
        _g._health_registry = None
        _g._audit_ledger = None
        try:
            reg = _g.get_health_registry()
            reg.record_heartbeat("healthy_dev")

            client = TestClient(self._app())
            resp = client.post("/api/v1/devices/healthy_dev/unquarantine")
            assert resp.status_code == 200
            data = resp.json()
            assert data["was_quarantined"] is False
        finally:
            _g._health_registry = old_hr
            _g._audit_ledger = old_al
