#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_production_recovery_wiring.py
=========================================
Production wiring tests: startup recovery + lifecycle snapshot persistence.

Validates that:
A  — Phase 4 invokes run_startup_recovery() and records startup_recovery in diagnostics.
B  — Phase 4 recovery diagnostics include expected keys.
C  — Phase 4 invokes get_lifecycle_registry().restore_from_snapshot() and records count.
D  — Phase 4 startup_recovery includes inflight_tasks_recovered key.
E  — Phase 4 succeeds (OK or DEGRADED) even when recovery raises an exception.
F  — async_shutdown persists the lifecycle snapshot before other shutdown steps.
G  — async_shutdown logs a warning and continues when persist_lifecycle_snapshot fails.
H  — SYSTEM_ORCHESTRATOR_AUTHORITY and RUNTIME_RESTART_RECOVERY_IS_AUTHORITY are distinct sentinels.
I  — run_startup_sequence produces a startup_recovery key in Phase 4 data.
J  — Phase 4 lifecycle_registry_restored_count is a non-negative integer.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from core.system_orchestrator import SystemOrchestrator, PhaseStatus, StartupPhase


# ---------------------------------------------------------------------------
# A — Phase 4 invokes run_startup_recovery and populates startup_recovery
# ---------------------------------------------------------------------------

class TestPhase4StartsRecovery:
    def test_phase4_invokes_startup_recovery(self, monkeypatch):
        """Phase 4 must call run_startup_recovery() and store results in diagnostics."""
        from core.runtime_restart_recovery import RuntimeRecoveryReport

        mock_report = RuntimeRecoveryReport()
        mock_report.completed_at = mock_report.started_at + 0.01

        called = {}

        def _fake_run_startup_recovery(**kwargs):
            called["invoked"] = True
            return mock_report

        monkeypatch.setattr(
            "core.system_orchestrator.run_startup_recovery",
            _fake_run_startup_recovery,
            raising=False,
        )
        # Patch the import inside the method
        import core.system_orchestrator as _so_mod
        import core.runtime_restart_recovery as _rr_mod
        monkeypatch.setattr(_rr_mod, "run_startup_recovery", _fake_run_startup_recovery)

        orch = SystemOrchestrator()
        result = orch._run_phase_4_background_subsystems()

        assert result.status in (PhaseStatus.OK, PhaseStatus.DEGRADED)
        assert result.data.get("checks", {}).get("startup_recovery_completed") is True
        assert "startup_recovery" in result.data
        assert called.get("invoked") is True


# ---------------------------------------------------------------------------
# B — Phase 4 startup_recovery diagnostics include expected keys
# ---------------------------------------------------------------------------

class TestPhase4RecoveryDiagnosticKeys:
    def test_phase4_recovery_diagnostic_keys(self, monkeypatch):
        """startup_recovery dict in Phase 4 data must include canonical keys."""
        from core.runtime_restart_recovery import RuntimeRecoveryReport

        mock_report = RuntimeRecoveryReport()
        mock_report.completed_at = mock_report.started_at + 0.01
        mock_report.inflight_tasks_recovered = 2
        mock_report.inflight_tasks_resumable = 1
        mock_report.inflight_tasks_replay_only = 1

        import core.runtime_restart_recovery as _rr_mod
        monkeypatch.setattr(_rr_mod, "run_startup_recovery", lambda **kw: mock_report)

        orch = SystemOrchestrator()
        result = orch._run_phase_4_background_subsystems()

        sr = result.data.get("startup_recovery", {})
        for key in (
            "recovery_id",
            "mesh_sessions_recovered",
            "body_mesh_entries_restored",
            "hybrid_executions_interrupted",
            "hybrid_executions_restored",
            "inflight_tasks_recovered",
            "inflight_tasks_resumable",
            "inflight_tasks_replay_only",
            "inflight_tasks_reissuable",
            "inflight_tasks_terminal",
            "has_errors",
            "errors",
        ):
            assert key in sr, f"Missing key in startup_recovery: {key}"

        assert sr["inflight_tasks_recovered"] == 2
        assert sr["inflight_tasks_resumable"] == 1


# ---------------------------------------------------------------------------
# C — Phase 4 calls registry.restore_from_snapshot and records count
# ---------------------------------------------------------------------------

class TestPhase4LifecycleRegistryRestore:
    def test_phase4_restores_lifecycle_registry(self, monkeypatch):
        """Phase 4 must call get_lifecycle_registry().restore_from_snapshot()."""
        mock_registry = MagicMock()
        mock_registry.restore_from_snapshot.return_value = 3

        import core.task_envelope_lifecycle_registry as _lr_mod
        monkeypatch.setattr(_lr_mod, "get_lifecycle_registry", lambda: mock_registry)

        orch = SystemOrchestrator()
        result = orch._run_phase_4_background_subsystems()

        mock_registry.restore_from_snapshot.assert_called_once()
        assert result.data.get("checks", {}).get("lifecycle_registry_restored") is True
        assert result.data.get("lifecycle_registry_restored_count") == 3


# ---------------------------------------------------------------------------
# D — inflight_tasks_recovered is recorded in startup_recovery
# ---------------------------------------------------------------------------

class TestPhase4InFlightTaskCount:
    def test_inflight_tasks_recovered_recorded(self, monkeypatch):
        """inflight_tasks_recovered in startup_recovery must reflect recovery report."""
        from core.runtime_restart_recovery import RuntimeRecoveryReport

        mock_report = RuntimeRecoveryReport()
        mock_report.completed_at = mock_report.started_at + 0.01
        mock_report.inflight_tasks_recovered = 5
        mock_report.inflight_tasks_terminal = 2

        import core.runtime_restart_recovery as _rr_mod
        monkeypatch.setattr(_rr_mod, "run_startup_recovery", lambda **kw: mock_report)

        orch = SystemOrchestrator()
        result = orch._run_phase_4_background_subsystems()

        sr = result.data.get("startup_recovery", {})
        assert sr["inflight_tasks_recovered"] == 5
        assert sr["inflight_tasks_terminal"] == 2


# ---------------------------------------------------------------------------
# E — Phase 4 survives recovery exception (non-fatal)
# ---------------------------------------------------------------------------

class TestPhase4RecoveryNonFatal:
    def test_phase4_ok_when_recovery_raises(self, monkeypatch):
        """Phase 4 must not hard-fail when run_startup_recovery() raises."""
        def _raise_error(**kwargs):
            raise RuntimeError("store unavailable")

        import core.runtime_restart_recovery as _rr_mod
        monkeypatch.setattr(_rr_mod, "run_startup_recovery", _raise_error)

        orch = SystemOrchestrator()
        result = orch._run_phase_4_background_subsystems()

        # Phase must not be FAILED even when recovery raises
        assert result.status != PhaseStatus.FAILED
        assert result.data.get("checks", {}).get("startup_recovery_completed") is False


# ---------------------------------------------------------------------------
# F — async_shutdown persists lifecycle snapshot
# ---------------------------------------------------------------------------

class TestShutdownPersistsLifecycleSnapshot:
    def test_async_shutdown_persists_snapshot(self, monkeypatch):
        """async_shutdown must call persist_lifecycle_snapshot before subsystem teardown."""
        persist_called = {}

        def _fake_persist(store=None):
            persist_called["ok"] = True
            return True

        import core.task_envelope_lifecycle_registry as _lr_mod
        monkeypatch.setattr(_lr_mod, "persist_lifecycle_snapshot", _fake_persist)

        import launcher.shutdown as _sd_mod

        # Patch internal imports used by async_shutdown
        import unittest.mock as _mock
        with _mock.patch.dict("sys.modules", {
            "core.startup": _mock.MagicMock(shutdown_subsystems=lambda: asyncio.sleep(0)),
            "core.nats_bus": _mock.MagicMock(nats_bus=_mock.AsyncMock()),
        }):
            asyncio.run(_sd_mod.async_shutdown())

        assert persist_called.get("ok") is True

    def test_async_shutdown_persist_before_subsystems(self, monkeypatch):
        """persist_lifecycle_snapshot must be called before shutdown_subsystems."""
        call_order = []

        def _fake_persist(store=None):
            call_order.append("persist")
            return True

        import core.task_envelope_lifecycle_registry as _lr_mod
        monkeypatch.setattr(_lr_mod, "persist_lifecycle_snapshot", _fake_persist)

        import launcher.shutdown as _sd_mod
        import unittest.mock as _mock

        async def _fake_shutdown_subsystems():
            call_order.append("subsystems")

        with _mock.patch.dict("sys.modules", {
            "core.startup": _mock.MagicMock(shutdown_subsystems=_fake_shutdown_subsystems),
            "core.nats_bus": _mock.MagicMock(nats_bus=_mock.AsyncMock()),
        }):
            asyncio.run(_sd_mod.async_shutdown())

        assert "persist" in call_order
        assert "subsystems" in call_order
        assert call_order.index("persist") < call_order.index("subsystems")


# ---------------------------------------------------------------------------
# G — async_shutdown continues when persist_lifecycle_snapshot raises
# ---------------------------------------------------------------------------

class TestShutdownPersistFailureNonFatal:
    def test_async_shutdown_continues_when_persist_raises(self, monkeypatch):
        """async_shutdown must continue (not raise) when persist_lifecycle_snapshot fails."""
        def _failing_persist(store=None):
            raise IOError("disk full")

        import core.task_envelope_lifecycle_registry as _lr_mod
        monkeypatch.setattr(_lr_mod, "persist_lifecycle_snapshot", _failing_persist)

        import launcher.shutdown as _sd_mod
        import unittest.mock as _mock

        with _mock.patch.dict("sys.modules", {
            "core.startup": _mock.MagicMock(shutdown_subsystems=lambda: asyncio.sleep(0)),
            "core.nats_bus": _mock.MagicMock(nats_bus=_mock.AsyncMock()),
        }):
            # Must not raise
            asyncio.run(_sd_mod.async_shutdown())


# ---------------------------------------------------------------------------
# H — Distinct sentinels
# ---------------------------------------------------------------------------

class TestDistinctSentinels:
    def test_orchestrator_and_recovery_sentinels_are_distinct(self):
        """SYSTEM_ORCHESTRATOR_AUTHORITY and RUNTIME_RESTART_RECOVERY_IS_AUTHORITY must differ."""
        from core.system_orchestrator import SYSTEM_ORCHESTRATOR_AUTHORITY
        from core.runtime_restart_recovery import RUNTIME_RESTART_RECOVERY_IS_AUTHORITY

        assert SYSTEM_ORCHESTRATOR_AUTHORITY != RUNTIME_RESTART_RECOVERY_IS_AUTHORITY
        assert len(SYSTEM_ORCHESTRATOR_AUTHORITY) > 0
        assert len(RUNTIME_RESTART_RECOVERY_IS_AUTHORITY) > 0


# ---------------------------------------------------------------------------
# I — Full startup sequence Phase 4 data includes startup_recovery
# ---------------------------------------------------------------------------

class TestFullSequenceIncludesRecovery:
    def test_run_startup_sequence_phase4_data_has_startup_recovery(self, monkeypatch):
        """run_startup_sequence must include startup_recovery in Phase 4 data."""
        from core.runtime_restart_recovery import RuntimeRecoveryReport

        mock_report = RuntimeRecoveryReport()
        mock_report.completed_at = mock_report.started_at + 0.01

        import core.runtime_restart_recovery as _rr_mod
        monkeypatch.setattr(_rr_mod, "run_startup_recovery", lambda **kw: mock_report)

        orch = SystemOrchestrator(continue_on_failure=True)
        summary = orch.run_startup_sequence()

        phase4_result = next(
            (r for r in summary.phase_results if r.phase == StartupPhase.BACKGROUND_SUBSYSTEMS),
            None,
        )
        assert phase4_result is not None
        assert "startup_recovery" in phase4_result.data


# ---------------------------------------------------------------------------
# J — lifecycle_registry_restored_count is non-negative
# ---------------------------------------------------------------------------

class TestLifecycleRestoreCountNonNegative:
    def test_lifecycle_registry_restored_count_non_negative(self, monkeypatch):
        """lifecycle_registry_restored_count in Phase 4 data must be >= 0."""
        orch = SystemOrchestrator()
        result = orch._run_phase_4_background_subsystems()

        count = result.data.get("lifecycle_registry_restored_count", -1)
        assert isinstance(count, int)
        assert count >= 0
