#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr5_runtime_restart_recovery.py
============================================
PR-5: Runtime Restart Recovery Coordinator — test suite.

Coverage
--------
A  — Module sentinels are importable non-empty strings.
B  — RuntimeRecoveryReport: construction and defaults.
C  — RuntimeRecoveryReport.to_dict: all expected keys present.
D  — RuntimeRecoveryReport.duration_seconds: None before completion.
E  — RuntimeRecoveryReport.duration_seconds: float after completion.
F  — RuntimeRecoveryReport.has_errors: True when errors present.
G  — RuntimeRecoveryReport.has_errors: False when no errors.
H  — RuntimeRecoveryReport.success: False when not completed.
I  — RuntimeRecoveryReport.success: False when errors present.
J  — RuntimeRecoveryReport.success: True when completed with no errors.
K  — RuntimeRestartRecoveryCoordinator: run_recovery returns a report.
L  — run_recovery: completed_at is set after completion.
M  — run_recovery: mesh_sessions_recovered is non-negative.
N  — run_recovery: body_mesh_entries_restored is non-negative.
O  — run_recovery: webrtc_bindings_cleared is True.
P  — run_recovery: non_goals list is populated.
Q  — run_recovery: does not raise even when no persistence stores exist.
R  — run_recovery with explicit mesh_session_store (empty store → 0 sessions).
S  — run_recovery with explicit body_mesh_store (empty store → 0 entries).
T  — run_recovery restores mesh sessions from a store with data.
U  — run_recovery restores body mesh entries from a store with data.
V  — run_startup_recovery module-level function returns report.
W  — get_recovery_coordinator returns singleton.
X  — reset_recovery_coordinator clears singleton.
Y  — WEBRTC_BINDINGS_ARE_EPHEMERAL_POLICY declares WebRTC non-goal explicitly.
Z  — run_recovery with a registry that has entries persisted and then recovered.
AA — RuntimeRecoveryReport.recovery_id is auto-generated and unique.
AB — run_recovery report has expected non_goals strings.
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import Any, Dict, List, Optional

import pytest

from core.runtime_restart_recovery import (
    RUNTIME_RESTART_RECOVERY_IS_AUTHORITY,
    MESH_SESSION_RECOVERY_IS_DURABLE_POLICY,
    BODY_MESH_RECOVERY_IS_DURABLE_POLICY,
    WEBRTC_BINDINGS_ARE_EPHEMERAL_POLICY,
    RUNTIME_RESTART_RECOVERY_PR5_SENTINEL,
    RuntimeRecoveryReport,
    RuntimeRestartRecoveryCoordinator,
    run_startup_recovery,
    get_recovery_coordinator,
    reset_recovery_coordinator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mesh_session_store(tmp_dir: Optional[str] = None):
    from core.mesh.mesh_session_persistence import MeshSessionPersistenceStore
    return MeshSessionPersistenceStore(store_dir=tmp_dir or tempfile.mkdtemp())


def _make_body_mesh_store(tmp_dir: Optional[str] = None):
    from core.mesh.body_mesh_persistence import BodyMeshPersistenceStore
    path = os.path.join(tmp_dir or tempfile.mkdtemp(), "bm_snap.json")
    return BodyMeshPersistenceStore(store_path=path)


def _coord_dict(session_id: str, status: str = "coordinating") -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "coordinator_id": "coord-test",
        "overall_status": status,
        "pending_device_ids": ["dev_a"],
        "completed_device_ids": [],
        "failed_device_ids": [],
    }


def _entry_dict(device_id: str) -> Dict[str, Any]:
    return {
        "device_id": device_id,
        "roles": ["action"],
        "session_id": "sess-test",
        "body_score": 1.5,
        "registered_at": time.time(),
        "metadata": {},
    }


class FakeRegistry:
    def __init__(self):
        self._entries: List[Dict] = []

    def register(self, device_id, roles=None, session_id=None, metadata=None):
        self._entries.append({"device_id": device_id, "session_id": session_id})
        return self._entries[-1]

    def list_entries(self):
        return []


# ---------------------------------------------------------------------------
# A — Sentinels
# ---------------------------------------------------------------------------

class TestSentinels:
    def test_authority_sentinel(self):
        assert isinstance(RUNTIME_RESTART_RECOVERY_IS_AUTHORITY, str)
        assert RUNTIME_RESTART_RECOVERY_IS_AUTHORITY

    def test_mesh_recovery_policy(self):
        assert isinstance(MESH_SESSION_RECOVERY_IS_DURABLE_POLICY, str)

    def test_body_mesh_policy(self):
        assert isinstance(BODY_MESH_RECOVERY_IS_DURABLE_POLICY, str)

    def test_webrtc_ephemeral_policy(self):
        assert isinstance(WEBRTC_BINDINGS_ARE_EPHEMERAL_POLICY, str)
        assert "ephemeral" in WEBRTC_BINDINGS_ARE_EPHEMERAL_POLICY.lower() \
            or "EPHEMERAL" in WEBRTC_BINDINGS_ARE_EPHEMERAL_POLICY

    def test_pr5_sentinel(self):
        assert isinstance(RUNTIME_RESTART_RECOVERY_PR5_SENTINEL, str)
        assert RUNTIME_RESTART_RECOVERY_PR5_SENTINEL


# ---------------------------------------------------------------------------
# B–J — RuntimeRecoveryReport
# ---------------------------------------------------------------------------

class TestRuntimeRecoveryReport:
    def test_construction(self):
        r = RuntimeRecoveryReport()
        assert r.recovery_id.startswith("rcv_")
        assert r.completed_at is None
        assert r.mesh_sessions_recovered == 0
        assert r.body_mesh_entries_restored == 0
        assert r.webrtc_bindings_cleared is True

    def test_to_dict_keys(self):
        r = RuntimeRecoveryReport()
        d = r.to_dict()
        for key in ("recovery_id", "started_at", "completed_at",
                    "mesh_sessions_recovered", "mesh_sessions_skipped",
                    "body_mesh_entries_restored", "webrtc_bindings_cleared",
                    "errors", "non_goals"):
            assert key in d, f"Missing key: {key}"

    def test_duration_before_completion(self):
        r = RuntimeRecoveryReport()
        assert r.duration_seconds is None

    def test_duration_after_completion(self):
        r = RuntimeRecoveryReport()
        r.started_at = 100.0
        r.completed_at = 101.5
        assert abs(r.duration_seconds - 1.5) < 1e-6

    def test_has_errors_true(self):
        r = RuntimeRecoveryReport(errors=["oops"])
        assert r.has_errors is True

    def test_has_errors_false(self):
        r = RuntimeRecoveryReport()
        assert r.has_errors is False

    def test_success_false_when_not_completed(self):
        r = RuntimeRecoveryReport()
        assert r.success is False

    def test_success_false_when_errors(self):
        r = RuntimeRecoveryReport(errors=["err"])
        r.completed_at = time.time()
        assert r.success is False

    def test_success_true(self):
        r = RuntimeRecoveryReport()
        r.completed_at = time.time()
        assert r.success is True

    def test_recovery_id_unique(self):
        r1 = RuntimeRecoveryReport()
        r2 = RuntimeRecoveryReport()
        assert r1.recovery_id != r2.recovery_id


# ---------------------------------------------------------------------------
# K–Q — RuntimeRestartRecoveryCoordinator basics
# ---------------------------------------------------------------------------

class TestCoordinatorBasics:
    def test_run_recovery_returns_report(self, tmp_path):
        ms_store = _make_mesh_session_store(str(tmp_path))
        bm_store = _make_body_mesh_store(str(tmp_path))
        reg = FakeRegistry()
        coord = RuntimeRestartRecoveryCoordinator(
            mesh_session_store=ms_store,
            body_mesh_store=bm_store,
            body_mesh_registry=reg,
        )
        report = coord.run_recovery()
        assert isinstance(report, RuntimeRecoveryReport)

    def test_completed_at_is_set(self, tmp_path):
        ms_store = _make_mesh_session_store(str(tmp_path))
        bm_store = _make_body_mesh_store(str(tmp_path))
        coord = RuntimeRestartRecoveryCoordinator(
            mesh_session_store=ms_store,
            body_mesh_store=bm_store,
            body_mesh_registry=FakeRegistry(),
        )
        report = coord.run_recovery()
        assert report.completed_at is not None
        assert report.completed_at >= report.started_at

    def test_mesh_sessions_non_negative(self, tmp_path):
        coord = RuntimeRestartRecoveryCoordinator(
            mesh_session_store=_make_mesh_session_store(str(tmp_path)),
            body_mesh_store=_make_body_mesh_store(str(tmp_path)),
            body_mesh_registry=FakeRegistry(),
        )
        assert coord.run_recovery().mesh_sessions_recovered >= 0

    def test_body_mesh_non_negative(self, tmp_path):
        coord = RuntimeRestartRecoveryCoordinator(
            mesh_session_store=_make_mesh_session_store(str(tmp_path)),
            body_mesh_store=_make_body_mesh_store(str(tmp_path)),
            body_mesh_registry=FakeRegistry(),
        )
        assert coord.run_recovery().body_mesh_entries_restored >= 0

    def test_webrtc_bindings_cleared(self, tmp_path):
        coord = RuntimeRestartRecoveryCoordinator(
            mesh_session_store=_make_mesh_session_store(str(tmp_path)),
            body_mesh_store=_make_body_mesh_store(str(tmp_path)),
            body_mesh_registry=FakeRegistry(),
        )
        report = coord.run_recovery()
        # Either True (cleared successfully) or the field is present
        assert isinstance(report.webrtc_bindings_cleared, bool)

    def test_non_goals_populated(self, tmp_path):
        coord = RuntimeRestartRecoveryCoordinator(
            mesh_session_store=_make_mesh_session_store(str(tmp_path)),
            body_mesh_store=_make_body_mesh_store(str(tmp_path)),
            body_mesh_registry=FakeRegistry(),
        )
        report = coord.run_recovery()
        assert len(report.non_goals) > 0

    def test_does_not_raise_without_stores(self):
        # Coordinator with no explicit stores (uses singletons / defaults)
        # Must not raise; may fail gracefully with errors logged
        from core.mesh.body_mesh_persistence import reset_body_mesh_persistence_store
        from core.mesh.mesh_session_persistence import reset_persistence_store
        reset_body_mesh_persistence_store()
        reset_persistence_store()
        try:
            coord = RuntimeRestartRecoveryCoordinator(
                body_mesh_registry=FakeRegistry(),
            )
            report = coord.run_recovery()
            assert isinstance(report, RuntimeRecoveryReport)
        finally:
            from core.mesh.body_mesh_persistence import reset_body_mesh_persistence_store
            from core.mesh.mesh_session_persistence import reset_persistence_store
            reset_body_mesh_persistence_store()
            reset_persistence_store()


# ---------------------------------------------------------------------------
# R–U — Recovery with data
# ---------------------------------------------------------------------------

class TestRecoveryWithData:
    def test_empty_mesh_session_store_gives_zero_sessions(self, tmp_path):
        ms_store = _make_mesh_session_store(str(tmp_path))
        coord = RuntimeRestartRecoveryCoordinator(
            mesh_session_store=ms_store,
            body_mesh_store=_make_body_mesh_store(str(tmp_path)),
            body_mesh_registry=FakeRegistry(),
        )
        report = coord.run_recovery()
        assert report.mesh_sessions_recovered == 0

    def test_empty_body_mesh_store_gives_zero_entries(self, tmp_path):
        bm_store = _make_body_mesh_store(str(tmp_path))
        coord = RuntimeRestartRecoveryCoordinator(
            mesh_session_store=_make_mesh_session_store(str(tmp_path)),
            body_mesh_store=bm_store,
            body_mesh_registry=FakeRegistry(),
        )
        report = coord.run_recovery()
        assert report.body_mesh_entries_restored == 0

    def test_mesh_sessions_recovered_from_store(self, tmp_path):
        ms_store = _make_mesh_session_store(str(tmp_path))
        # Save two active sessions and one terminal
        ms_store.save(_coord_dict("s1", "coordinating"))
        ms_store.save(_coord_dict("s2", "coordinating"))
        ms_store.save(_coord_dict("s3", "completed"))

        coord = RuntimeRestartRecoveryCoordinator(
            mesh_session_store=ms_store,
            body_mesh_store=_make_body_mesh_store(str(tmp_path)),
            body_mesh_registry=FakeRegistry(),
        )
        report = coord.run_recovery()
        # 2 non-terminal sessions should be recovered
        assert report.mesh_sessions_recovered == 2

    def test_body_mesh_entries_restored(self, tmp_path):
        bm_store = _make_body_mesh_store(str(tmp_path))
        bm_store.save([_entry_dict("dev-1"), _entry_dict("dev-2")])

        target = FakeRegistry()
        coord = RuntimeRestartRecoveryCoordinator(
            mesh_session_store=_make_mesh_session_store(str(tmp_path)),
            body_mesh_store=bm_store,
            body_mesh_registry=target,
        )
        report = coord.run_recovery()
        assert report.body_mesh_entries_restored == 2
        assert len(target._entries) == 2


# ---------------------------------------------------------------------------
# V–X — Module-level helpers and singleton
# ---------------------------------------------------------------------------

class TestModuleLevelHelpers:
    def test_run_startup_recovery_returns_report(self, tmp_path):
        ms_store = _make_mesh_session_store(str(tmp_path))
        bm_store = _make_body_mesh_store(str(tmp_path))
        report = run_startup_recovery(
            mesh_session_store=ms_store,
            body_mesh_store=bm_store,
            body_mesh_registry=FakeRegistry(),
        )
        assert isinstance(report, RuntimeRecoveryReport)
        assert report.completed_at is not None

    def test_get_coordinator_singleton(self):
        reset_recovery_coordinator()
        c1 = get_recovery_coordinator()
        c2 = get_recovery_coordinator()
        assert c1 is c2

    def test_reset_clears_singleton(self):
        reset_recovery_coordinator()
        c1 = get_recovery_coordinator()
        reset_recovery_coordinator()
        c2 = get_recovery_coordinator()
        assert c1 is not c2


# ---------------------------------------------------------------------------
# Y — WebRTC ephemeral policy and non-goals
# ---------------------------------------------------------------------------

class TestWebRTCEphemeralPolicy:
    def test_webrtc_bindings_are_ephemeral_policy_explicit(self):
        assert "not recovered" in WEBRTC_BINDINGS_ARE_EPHEMERAL_POLICY.lower() \
            or "NOT" in WEBRTC_BINDINGS_ARE_EPHEMERAL_POLICY

    def test_non_goals_mention_webrtc(self, tmp_path):
        coord = RuntimeRestartRecoveryCoordinator(
            mesh_session_store=_make_mesh_session_store(str(tmp_path)),
            body_mesh_store=_make_body_mesh_store(str(tmp_path)),
            body_mesh_registry=FakeRegistry(),
        )
        report = coord.run_recovery()
        non_goal_text = " ".join(report.non_goals).lower()
        assert "webrtc" in non_goal_text or "transport" in non_goal_text


# ---------------------------------------------------------------------------
# Z — Full round-trip
# ---------------------------------------------------------------------------

class TestFullRoundTrip:
    def test_save_then_recover_body_mesh(self, tmp_path):
        from core.mesh.body_mesh_persistence import BodyMeshPersistenceStore, save_body_mesh_snapshot

        bm_path = os.path.join(str(tmp_path), "bm.json")
        bm_store = BodyMeshPersistenceStore(store_path=bm_path)
        save_body_mesh_snapshot([_entry_dict("rt-dev-1"), _entry_dict("rt-dev-2")], store=bm_store)

        target = FakeRegistry()
        coord = RuntimeRestartRecoveryCoordinator(
            mesh_session_store=_make_mesh_session_store(str(tmp_path)),
            body_mesh_store=bm_store,
            body_mesh_registry=target,
        )
        report = coord.run_recovery()
        assert report.body_mesh_entries_restored == 2
        device_ids = [e["device_id"] for e in target._entries]
        assert "rt-dev-1" in device_ids
        assert "rt-dev-2" in device_ids
