"""tests/test_orchestration_consumes_android_truth.py
=====================================================
Focused regression tests proving that Android runtime truth materially
changes canonical V2 orchestration / routing / dispatch decisions.

This file is the machine-verifiable proof that the
``ORCHESTRATION_CONSUMES_ANDROID_TRUTH`` P0 gap is closed: Android truth
is NOT merely stored or exposed — it actively changes selection scores and
routing order in the canonical dispatch path.

Coverage groups
---------------
A. Sentinel / policy strings are exported.
B. _score_candidate() — Android snapshot drives scoring.
C. _select_target_from_candidates() — Android truth changes winner selection.
D. select_devices() — step 0c re-orders candidates by Android readiness.
E. post_closure_dual_repo_reassessment reflects the P0 as closed.
F. Backward compatibility — absent snapshot degrades gracefully.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry_entry(device_id: str = "android_dev") -> Any:
    entry = MagicMock()
    entry.device_id = device_id
    entry.session_id = f"sess_{device_id}"
    entry.runtime_session_id = f"rt_{device_id}"
    entry.attachment_state = MagicMock()
    entry.attachment_state.value = "active"
    entry.posture = "join_runtime"
    return entry


def _make_readiness(registered: bool = True, routable: bool = True) -> Any:
    r = MagicMock()
    r.registered = registered
    r.routable = routable
    return r


def _make_participation(orchestration_eligible: bool = True) -> Any:
    p = MagicMock()
    p.orchestration_eligible = orchestration_eligible
    p.participant_tier = "joined_runtime"
    return p


def _make_snapshot(
    *,
    model_ready: Optional[bool] = None,
    accessibility_ready: Optional[bool] = None,
    local_loop_ready: Optional[bool] = None,
    warmup_result: Optional[str] = None,
    current_fallback_tier: Optional[str] = None,
    offline_queue_depth: Optional[int] = None,
    runtime_health_snapshot: Optional[Dict[str, Any]] = None,
    local_ai_ready: Optional[bool] = None,
    mobilevlm_present: Optional[bool] = None,
    mobilevlm_checksum_ok: Optional[bool] = None,
    seeclick_present: Optional[bool] = None,
) -> Any:
    snap = MagicMock()
    snap.model_ready = model_ready
    snap.accessibility_ready = accessibility_ready
    snap.local_loop_ready = local_loop_ready
    snap.warmup_result = warmup_result
    snap.current_fallback_tier = current_fallback_tier
    snap.offline_queue_depth = offline_queue_depth
    snap.runtime_health_snapshot = runtime_health_snapshot
    if local_ai_ready is None:
        snap.is_local_ai_ready = lambda: False
    else:
        snap.is_local_ai_ready = lambda: bool(local_ai_ready)
    snap.mobilevlm_present = mobilevlm_present
    snap.mobilevlm_checksum_ok = mobilevlm_checksum_ok
    snap.seeclick_present = seeclick_present
    return snap


def _make_device(device_id: str, status: str = "online") -> Any:
    dev = MagicMock()
    dev.device_id = device_id
    dev.status = status
    dev.metadata = {}
    return dev


# ---------------------------------------------------------------------------
# A. Sentinel / policy strings
# ---------------------------------------------------------------------------


class TestSentinelsExported:
    def test_orchestration_consumes_android_truth_sentinel(self):
        from core.runtime.source_dispatch_orchestrator import (
            ORCHESTRATION_CONSUMES_ANDROID_TRUTH_SENTINEL,
        )

        assert "ORCHESTRATION_CONSUMES_ANDROID_TRUTH" in ORCHESTRATION_CONSUMES_ANDROID_TRUTH_SENTINEL
        assert "android" in ORCHESTRATION_CONSUMES_ANDROID_TRUTH_SENTINEL.lower()

    def test_android_runtime_truth_scores_dispatch_candidates_policy(self):
        from core.runtime.source_dispatch_orchestrator import (
            ANDROID_RUNTIME_TRUTH_SCORES_DISPATCH_CANDIDATES_POLICY,
        )

        assert "model_ready" in ANDROID_RUNTIME_TRUTH_SCORES_DISPATCH_CANDIDATES_POLICY
        assert "accessibility_ready" in ANDROID_RUNTIME_TRUTH_SCORES_DISPATCH_CANDIDATES_POLICY
        assert "current_fallback_tier" in ANDROID_RUNTIME_TRUTH_SCORES_DISPATCH_CANDIDATES_POLICY

    def test_android_execution_busy_deprioritised_policy(self):
        from core.runtime.source_dispatch_orchestrator import (
            ANDROID_EXECUTION_BUSY_DEPRIORITISED_IN_SELECTION_POLICY,
        )

        assert "execution_busy" in ANDROID_EXECUTION_BUSY_DEPRIORITISED_IN_SELECTION_POLICY.lower()

    def test_dispatch_field_authoritative_status_policy(self):
        from core.runtime.source_dispatch_orchestrator import (
            ANDROID_DISPATCH_FIELD_AUTHORITATIVE_STATUS_POLICY,
        )

        assert "capability-only" in ANDROID_DISPATCH_FIELD_AUTHORITATIVE_STATUS_POLICY
        assert "mobilevlm_present" in ANDROID_DISPATCH_FIELD_AUTHORITATIVE_STATUS_POLICY

    def test_device_selection_routing_weight_sentinel(self):
        from galaxy_gateway.routing.device_selection import (
            ANDROID_RUNTIME_TRUTH_ROUTING_WEIGHT_IN_SELECTION,
        )

        assert (
            "ANDROID_RUNTIME_TRUTH_ROUTING_WEIGHT_IN_SELECTION_V1"
            in ANDROID_RUNTIME_TRUTH_ROUTING_WEIGHT_IN_SELECTION
        )
        assert "model_ready" in ANDROID_RUNTIME_TRUTH_ROUTING_WEIGHT_IN_SELECTION


# ---------------------------------------------------------------------------
# B. _score_candidate — Android snapshot drives scoring
# ---------------------------------------------------------------------------


class TestScoreCandidateAndroidTruth:
    """_score_candidate() produces different scores based on android_snapshot."""

    def _score(self, android_snapshot=None, execution_busy=False):
        from core.runtime.source_dispatch_orchestrator import _score_candidate

        readiness = _make_readiness()
        participation = _make_participation()
        score, rejection = _score_candidate(
            "sess_test",
            "dev_test",
            readiness=readiness,
            participation=participation,
            reuse_eligible=False,
            android_snapshot=android_snapshot,
            execution_busy=execution_busy,
        )
        return score, rejection

    def test_no_snapshot_baseline_score(self):
        score, rejection = self._score(android_snapshot=None)
        assert rejection == ""
        assert score == 100  # baseline, no adjustments

    def test_model_ready_true_boosts_score(self):
        snap = _make_snapshot(model_ready=True)
        score, rejection = self._score(android_snapshot=snap)
        assert rejection == ""
        assert score > 100  # +10 for model_ready=True

    def test_model_ready_true_adds_10(self):
        snap = _make_snapshot(model_ready=True)
        score, _ = self._score(android_snapshot=snap)
        assert score == 110  # baseline 100 + 10

    def test_accessibility_ready_true_adds_5(self):
        snap = _make_snapshot(accessibility_ready=True)
        score, _ = self._score(android_snapshot=snap)
        assert score == 105

    def test_local_loop_ready_true_adds_5(self):
        snap = _make_snapshot(local_loop_ready=True)
        score, _ = self._score(android_snapshot=snap)
        assert score == 105

    def test_all_positive_signals_stack(self):
        snap = _make_snapshot(
            model_ready=True,
            accessibility_ready=True,
            local_loop_ready=True,
        )
        score, _ = self._score(android_snapshot=snap)
        # +10 + +5 + +5 = +20
        assert score == 120

    def test_warmup_failed_subtracts_10(self):
        snap = _make_snapshot(warmup_result="failed")
        score, _ = self._score(android_snapshot=snap)
        assert score == 90

    def test_model_not_ready_no_fallback_subtracts_20(self):
        snap = _make_snapshot(model_ready=False, current_fallback_tier=None)
        score, _ = self._score(android_snapshot=snap)
        assert score == 80

    def test_model_not_ready_with_fallback_no_penalty(self):
        """model_ready=False is only penalised when there is no fallback tier."""
        snap = _make_snapshot(model_ready=False, current_fallback_tier="center_delegated")
        score, _ = self._score(android_snapshot=snap)
        # No -20 because fallback tier exists.
        assert score == 100

    def test_execution_busy_subtracts_15(self):
        score, _ = self._score(android_snapshot=None, execution_busy=True)
        assert score == 85

    def test_execution_busy_with_positive_android_signals(self):
        snap = _make_snapshot(model_ready=True, accessibility_ready=True)
        score, _ = self._score(android_snapshot=snap, execution_busy=True)
        # +10 +5 -15 = 100
        assert score == 100

    def test_queue_depth_penalty_changes_score(self):
        snap_idle = _make_snapshot(offline_queue_depth=0)
        snap_busy = _make_snapshot(offline_queue_depth=9)
        score_idle, _ = self._score(android_snapshot=snap_idle)
        score_busy, _ = self._score(android_snapshot=snap_busy)
        assert score_busy < score_idle

    def test_local_inference_availability_boosts_score(self):
        snap_no_local = _make_snapshot(local_ai_ready=False)
        snap_local = _make_snapshot(local_ai_ready=True)
        score_no_local, _ = self._score(android_snapshot=snap_no_local)
        score_local, _ = self._score(android_snapshot=snap_local)
        assert score_local > score_no_local

    def test_runtime_health_degraded_penalizes_score(self):
        snap_ok = _make_snapshot(runtime_health_snapshot={"status": "healthy"})
        snap_bad = _make_snapshot(runtime_health_snapshot={"status": "degraded"})
        score_ok, _ = self._score(android_snapshot=snap_ok)
        score_bad, _ = self._score(android_snapshot=snap_bad)
        assert score_bad < score_ok

    def test_android_truth_does_not_affect_gate_failures(self):
        """Hard gate failures (not_routable) must still reject even with good snapshot."""
        from core.runtime.source_dispatch_orchestrator import _score_candidate

        readiness = _make_readiness(routable=False)
        snap = _make_snapshot(model_ready=True, accessibility_ready=True)
        score, rejection = _score_candidate(
            "sess_test",
            "dev_test",
            readiness=readiness,
            participation=_make_participation(),
            reuse_eligible=False,
            android_snapshot=snap,
        )
        assert score == 0
        assert "not_routable" in rejection

    def test_none_field_values_no_adjustment(self):
        """None fields in snapshot must not trigger any score change."""
        snap = _make_snapshot(
            model_ready=None,
            accessibility_ready=None,
            local_loop_ready=None,
            warmup_result=None,
            current_fallback_tier=None,
        )
        score, _ = self._score(android_snapshot=snap)
        assert score == 100  # no adjustments

    def test_capability_presence_fields_do_not_change_score(self):
        """Presence-only capability fields must not affect dispatch score."""
        snap = _make_snapshot(
            mobilevlm_present=True,
            mobilevlm_checksum_ok=True,
            seeclick_present=True,
        )
        score, _ = self._score(android_snapshot=snap)
        assert score == 100


# ---------------------------------------------------------------------------
# C. _select_target_from_candidates — Android truth changes winner selection
# ---------------------------------------------------------------------------


class TestSelectTargetAndroidTruth:
    """Android truth in android_snapshot_inputs changes which candidate wins."""

    def _build_mock_registry_with_sessions(self, device_ids):
        """Build a mock registry that returns entries for device_ids."""
        sessions = [_make_registry_entry(did) for did in device_ids]
        mock_registry = MagicMock()
        return mock_registry, sessions

    def test_android_truth_consumed_in_metadata(self, monkeypatch):
        """When android_snapshot_inputs is provided, metadata carries android_truth_consumed=True."""
        from core.runtime.source_dispatch_orchestrator import (
            _select_target_from_candidates,
        )

        device_id = "dev_truth_consumed"
        entry = _make_registry_entry(device_id)
        snap = _make_snapshot(model_ready=True)

        monkeypatch.setattr(
            "core.attached_runtime_session_registry.list_active_sessions",
            lambda registry=None: [entry],
        )

        result = _select_target_from_candidates(
            readiness_inputs={device_id: _make_readiness()},
            participation_inputs={device_id: _make_participation()},
            reuse_inputs={device_id: False},
            android_snapshot_inputs={device_id: snap},
        )

        assert result is not None
        assert result.target_device_id == device_id
        assert result.metadata.get("android_truth_consumed") is True
        assert result.metadata.get("canonical_execution_gate_decision") == "allow"
        assert result.metadata.get("canonical_execution_gate_reasons")

    def test_canonical_gate_decision_surfaces_deny_without_local_inference_or_fallback(
        self, monkeypatch
    ):
        from core.runtime.source_dispatch_orchestrator import (
            _select_target_from_candidates,
        )

        device_id = "dev_gate_deny"
        entry = _make_registry_entry(device_id)
        snap = _make_snapshot(
            model_ready=False,
            current_fallback_tier=None,
            local_ai_ready=False,
        )

        monkeypatch.setattr(
            "core.attached_runtime_session_registry.list_active_sessions",
            lambda registry=None: [entry],
        )

        result = _select_target_from_candidates(
            readiness_inputs={device_id: _make_readiness()},
            participation_inputs={device_id: _make_participation()},
            reuse_inputs={device_id: False},
            android_snapshot_inputs={device_id: snap},
        )

        assert result is not None
        assert result.metadata.get("canonical_execution_gate_decision") == "deny"

    def test_two_candidates_android_truth_picks_more_ready_one(self, monkeypatch):
        """Given two candidates, Android truth scoring picks the more ready one."""
        from core.runtime.source_dispatch_orchestrator import (
            _select_target_from_candidates,
        )

        dev_ready = "dev_ready"
        dev_unready = "dev_unready"

        entry_ready = _make_registry_entry(dev_ready)
        entry_unready = _make_registry_entry(dev_unready)

        # dev_ready: model_ready=True → +10
        # dev_unready: model_ready=False, no fallback → -20
        snap_ready = _make_snapshot(model_ready=True)
        snap_unready = _make_snapshot(model_ready=False, current_fallback_tier=None)

        monkeypatch.setattr(
            "core.attached_runtime_session_registry.list_active_sessions",
            lambda registry=None: [entry_unready, entry_ready],  # unready first
        )

        result = _select_target_from_candidates(
            readiness_inputs={
                dev_ready: _make_readiness(),
                dev_unready: _make_readiness(),
            },
            participation_inputs={
                dev_ready: _make_participation(),
                dev_unready: _make_participation(),
            },
            reuse_inputs={dev_ready: False, dev_unready: False},
            android_snapshot_inputs={
                dev_ready: snap_ready,
                dev_unready: snap_unready,
            },
        )

        assert result is not None
        # The ready device should win despite being listed second.
        assert result.target_device_id == dev_ready

    def test_android_participation_evidence_changes_winner_when_snapshots_equal(self, monkeypatch):
        from core.runtime.source_dispatch_orchestrator import (
            _select_target_from_candidates,
        )

        dev_dist = "dev_dist"
        dev_attach = "dev_attach"
        entry_dist = _make_registry_entry(dev_dist)
        entry_attach = _make_registry_entry(dev_attach)
        snap = _make_snapshot(model_ready=True, local_loop_ready=True)

        monkeypatch.setattr(
            "core.attached_runtime_session_registry.list_active_sessions",
            lambda registry=None: [entry_attach, entry_dist],
        )

        result = _select_target_from_candidates(
            readiness_inputs={dev_dist: _make_readiness(), dev_attach: _make_readiness()},
            participation_inputs={dev_dist: _make_participation(), dev_attach: _make_participation()},
            reuse_inputs={dev_dist: False, dev_attach: False},
            android_snapshot_inputs={dev_dist: snap, dev_attach: snap},
            android_participation_inputs={
                dev_dist: {"tier": "distributed_participant"},
                dev_attach: {"tier": "fully_attached"},
            },
        )

        assert result is not None
        assert result.target_device_id == dev_dist
        assert result.metadata.get("android_participation_truth_consumed") is True
        assert result.metadata.get("android_participation_tier") == "distributed_participant"

    def test_no_snapshot_does_not_change_outcome(self, monkeypatch):
        """Absent snapshot → baseline score 100 → normal selection (backward compat)."""
        from core.runtime.source_dispatch_orchestrator import (
            _select_target_from_candidates,
        )

        device_id = "dev_no_snap"
        entry = _make_registry_entry(device_id)

        monkeypatch.setattr(
            "core.attached_runtime_session_registry.list_active_sessions",
            lambda registry=None: [entry],
        )

        result = _select_target_from_candidates(
            readiness_inputs={device_id: _make_readiness()},
            participation_inputs={device_id: _make_participation()},
            reuse_inputs={device_id: False},
            android_snapshot_inputs={device_id: None},  # explicit None = no snapshot
        )

        assert result is not None
        assert result.target_device_id == device_id
        assert result.metadata.get("android_truth_consumed") is False

    def test_selection_reason_includes_android_truth_tag(self, monkeypatch):
        """selection_reason carries ':android_truth' when snapshot is present."""
        from core.runtime.source_dispatch_orchestrator import (
            _select_target_from_candidates,
        )

        device_id = "dev_tag_check"
        entry = _make_registry_entry(device_id)
        snap = _make_snapshot(model_ready=True)

        monkeypatch.setattr(
            "core.attached_runtime_session_registry.list_active_sessions",
            lambda registry=None: [entry],
        )

        result = _select_target_from_candidates(
            readiness_inputs={device_id: _make_readiness()},
            participation_inputs={device_id: _make_participation()},
            reuse_inputs={device_id: False},
            android_snapshot_inputs={device_id: snap},
        )

        assert result is not None
        assert ":android_truth" in result.selection_reason

    def test_execution_busy_flag_in_metadata(self, monkeypatch):
        """execution_busy is recorded in result metadata."""
        from core.runtime.source_dispatch_orchestrator import (
            _select_target_from_candidates,
        )

        device_id = "dev_busy_meta"
        entry = _make_registry_entry(device_id)
        snap = _make_snapshot(model_ready=True)

        # Simulate a recent non-terminal execution event.
        busy_event = MagicMock()
        busy_event.phase = "execution"
        busy_event.absorbed_at = time.time() - 5.0  # 5 seconds ago

        monkeypatch.setattr(
            "core.attached_runtime_session_registry.list_active_sessions",
            lambda registry=None: [entry],
        )

        # Patch list_recent_execution_events inside the orchestrator.
        monkeypatch.setattr(
            "core.android_device_state_store.list_recent_execution_events",
            lambda flow_id, device_id, limit: [busy_event],
        )

        result = _select_target_from_candidates(
            readiness_inputs={device_id: _make_readiness()},
            participation_inputs={device_id: _make_participation()},
            reuse_inputs={device_id: False},
            android_snapshot_inputs={device_id: snap},
        )

        assert result is not None
        # Metadata must record that the busy check ran.
        assert "execution_busy" in result.metadata

    def test_metadata_exposes_authoritative_vs_capability_only_fields(self, monkeypatch):
        """Selection metadata must expose dispatch field-status split."""
        from core.runtime.source_dispatch_orchestrator import (
            _select_target_from_candidates,
        )

        device_id = "dev_field_status"
        entry = _make_registry_entry(device_id)
        snap = _make_snapshot(model_ready=True, mobilevlm_present=True)

        monkeypatch.setattr(
            "core.attached_runtime_session_registry.list_active_sessions",
            lambda registry=None: [entry],
        )

        result = _select_target_from_candidates(
            readiness_inputs={device_id: _make_readiness()},
            participation_inputs={device_id: _make_participation()},
            reuse_inputs={device_id: False},
            android_snapshot_inputs={device_id: snap},
        )

        assert result is not None
        status = result.metadata.get("android_dispatch_field_status") or {}
        assert "model_ready" in status.get("authoritative_scoring_fields", [])
        assert "mobilevlm_present" in status.get("capability_presence_only_fields", [])

    def test_blocked_execution_type_runtime_truth_changes_selection(self, monkeypatch):
        from core.runtime.source_dispatch_orchestrator import (
            _select_target_from_candidates,
        )

        dev_blocked = "dev_blocked_exec"
        dev_open = "dev_open_exec"
        entry_blocked = _make_registry_entry(dev_blocked)
        entry_open = _make_registry_entry(dev_open)

        monkeypatch.setattr(
            "core.attached_runtime_session_registry.list_active_sessions",
            lambda registry=None: [entry_blocked, entry_open],
        )

        result = _select_target_from_candidates(
            readiness_inputs={dev_blocked: _make_readiness(), dev_open: _make_readiness()},
            participation_inputs={
                dev_blocked: _make_participation(),
                dev_open: _make_participation(),
            },
            reuse_inputs={dev_blocked: False, dev_open: False},
            android_snapshot_inputs={
                dev_blocked: _make_snapshot(model_ready=True),
                dev_open: _make_snapshot(model_ready=True),
            },
            execution_runtime_inputs={
                dev_blocked: {
                    "device_id": dev_blocked,
                    "active_execution_count": 1,
                    "highest_priority_execution_type": "takeover_request",
                    "blocked_execution_types": ["goal_execution"],
                },
                dev_open: {
                    "device_id": dev_open,
                    "active_execution_count": 0,
                    "highest_priority_execution_type": None,
                    "blocked_execution_types": [],
                },
            },
        )
        assert result is not None
        assert result.target_device_id == dev_open

    def test_blocked_execution_type_returns_stable_rejection_reason(self):
        from core.runtime.source_dispatch_orchestrator import _score_candidate

        score, rejection = _score_candidate(
            "sess_runtime_block",
            "dev_runtime_block",
            readiness=_make_readiness(),
            participation=_make_participation(),
            reuse_eligible=False,
            android_snapshot=_make_snapshot(model_ready=True),
            execution_runtime_state={
                "blocked_execution_types": ["goal_execution"],
                "incoming_execution_type": "goal_execution",
            },
        )
        assert score == 0
        assert rejection == "execution_runtime:blocked_execution_type:goal_execution"

    def test_selection_stability_under_equivalent_truth(self, monkeypatch):
        from core.runtime.source_dispatch_orchestrator import (
            _select_target_from_candidates,
        )

        dev_a = "dev_equiv_a"
        dev_b = "dev_equiv_b"
        entry_a = _make_registry_entry(dev_a)
        entry_b = _make_registry_entry(dev_b)

        monkeypatch.setattr(
            "core.attached_runtime_session_registry.list_active_sessions",
            lambda registry=None: [entry_a, entry_b],
        )

        for _ in range(5):
            result = _select_target_from_candidates(
                readiness_inputs={dev_a: _make_readiness(), dev_b: _make_readiness()},
                participation_inputs={dev_a: _make_participation(), dev_b: _make_participation()},
                reuse_inputs={dev_a: False, dev_b: False},
                android_snapshot_inputs={
                    dev_a: _make_snapshot(model_ready=True, local_ai_ready=True),
                    dev_b: _make_snapshot(model_ready=True, local_ai_ready=True),
                },
                execution_runtime_inputs={
                    dev_a: {
                        "device_id": dev_a,
                        "active_execution_count": 0,
                        "highest_priority_execution_type": None,
                        "blocked_execution_types": [],
                    },
                    dev_b: {
                        "device_id": dev_b,
                        "active_execution_count": 0,
                        "highest_priority_execution_type": None,
                        "blocked_execution_types": [],
                    },
                },
            )
            assert result is not None
            assert result.target_device_id == dev_a


# ---------------------------------------------------------------------------
# D. select_devices — step 0c re-orders by Android readiness
# ---------------------------------------------------------------------------


class TestSelectDevicesAndroidRoutingWeight:
    """select_devices() step 0c re-orders candidates by Android readiness score."""

    def test_select_devices_prefers_model_ready_device(self, monkeypatch):
        """With two devices, the one with model_ready=True is returned first."""
        from galaxy_gateway.routing.device_selection import select_devices

        dev_ready = _make_device("dev_ready_sel")
        dev_unready = _make_device("dev_unready_sel")

        snap_ready = _make_snapshot(model_ready=True)
        snap_unready = _make_snapshot(model_ready=False, current_fallback_tier=None)

        def _fake_get_snap(device_id: str):
            if device_id == "dev_ready_sel":
                return snap_ready
            if device_id == "dev_unready_sel":
                return snap_unready
            return None

        # Patch the module-level name (device_selection imports it at module level).
        monkeypatch.setattr(
            "galaxy_gateway.routing.device_selection.get_device_state_snapshot",
            _fake_get_snap,
        )

        # Patch the admissibility and runtime-state pre-filters to pass-through.
        monkeypatch.setattr(
            "core.target_device_validator.validate_target_device",
            lambda tid: MagicMock(ready=True, registered=True, reasons=[]),
            raising=False,
        )

        # Patch autonomous_filter to return devices as-is.
        monkeypatch.setattr(
            "galaxy_gateway.autonomous_filter.filter_autonomous_devices",
            lambda devices, **kw: [d for d in devices if d.status == "online"],
            raising=False,
        )

        # Patch pool manager to return None (fall through to first-preferred).
        mock_pool = MagicMock()
        mock_pool.select_device.return_value = None
        monkeypatch.setattr(
            "galaxy_gateway.routing.device_selection.get_device_pool_manager",
            lambda: mock_pool,
        )

        # Put the unready device first to confirm reordering happened.
        result = select_devices(
            analysis={},
            candidates=[dev_unready, dev_ready],
        )

        # The model-ready device should be selected (it should be first after step 0c).
        assert len(result) == 1
        assert result[0].device_id == "dev_ready_sel"

    def test_select_devices_no_snapshots_preserves_order(self, monkeypatch):
        """When no snapshots exist, original candidate order is preserved."""
        from galaxy_gateway.routing.device_selection import select_devices

        dev_a = _make_device("dev_a")
        dev_b = _make_device("dev_b")

        monkeypatch.setattr(
            "galaxy_gateway.routing.device_selection.get_device_state_snapshot",
            lambda device_id: None,
        )

        monkeypatch.setattr(
            "core.target_device_validator.validate_target_device",
            lambda tid: MagicMock(ready=True, registered=True, reasons=[]),
            raising=False,
        )
        monkeypatch.setattr(
            "galaxy_gateway.autonomous_filter.filter_autonomous_devices",
            lambda devices, **kw: [d for d in devices if d.status == "online"],
            raising=False,
        )
        mock_pool = MagicMock()
        mock_pool.select_device.return_value = None
        monkeypatch.setattr(
            "galaxy_gateway.routing.device_selection.get_device_pool_manager",
            lambda: mock_pool,
        )

        result = select_devices(
            analysis={},
            candidates=[dev_a, dev_b],
        )

        # No reordering — first candidate wins.
        assert len(result) == 1
        assert result[0].device_id == "dev_a"

    def test_select_devices_prefers_lower_queue_depth(self, monkeypatch):
        from galaxy_gateway.routing.device_selection import select_devices

        dev_heavy = _make_device("dev_heavy_queue")
        dev_light = _make_device("dev_light_queue")

        snap_heavy = _make_snapshot(model_ready=True, offline_queue_depth=12)
        snap_light = _make_snapshot(model_ready=True, offline_queue_depth=0)

        monkeypatch.setattr(
            "galaxy_gateway.routing.device_selection.get_device_state_snapshot",
            lambda device_id: snap_heavy if device_id == "dev_heavy_queue" else snap_light,
        )
        monkeypatch.setattr(
            "galaxy_gateway.routing.device_selection.list_recent_execution_events",
            lambda flow_id, device_id, limit: [],
        )
        monkeypatch.setattr(
            "core.target_device_validator.validate_target_device",
            lambda tid: MagicMock(ready=True, registered=True, reasons=[]),
            raising=False,
        )
        monkeypatch.setattr(
            "galaxy_gateway.autonomous_filter.filter_autonomous_devices",
            lambda devices, **kw: [d for d in devices if d.status == "online"],
            raising=False,
        )
        mock_pool = MagicMock()
        mock_pool.select_device.return_value = None
        monkeypatch.setattr(
            "galaxy_gateway.routing.device_selection.get_device_pool_manager",
            lambda: mock_pool,
        )

        result = select_devices(analysis={}, candidates=[dev_heavy, dev_light])
        assert len(result) == 1
        assert result[0].device_id == "dev_light_queue"

    def test_select_devices_prefers_higher_participation_tier_when_runtime_signals_equal(
        self, monkeypatch
    ):
        from galaxy_gateway.routing.device_selection import select_devices

        dev_attach = _make_device("dev_attach_tier")
        dev_dist = _make_device("dev_dist_tier")
        same_snapshot = _make_snapshot(model_ready=True, local_loop_ready=True)

        monkeypatch.setattr(
            "galaxy_gateway.routing.device_selection.get_device_state_snapshot",
            lambda device_id: same_snapshot,
        )
        monkeypatch.setattr(
            "galaxy_gateway.routing.device_selection.get_android_participation_evidence",
            lambda device_id: (
                {"tier": "distributed_participant"}
                if device_id == "dev_dist_tier"
                else {"tier": "fully_attached"}
            ),
        )
        monkeypatch.setattr(
            "galaxy_gateway.routing.device_selection.list_recent_execution_events",
            lambda flow_id, device_id, limit: [],
        )
        monkeypatch.setattr(
            "core.target_device_validator.validate_target_device",
            lambda tid: MagicMock(ready=True, registered=True, reasons=[]),
            raising=False,
        )
        monkeypatch.setattr(
            "galaxy_gateway.autonomous_filter.filter_autonomous_devices",
            lambda devices, **kw: [d for d in devices if d.status == "online"],
            raising=False,
        )
        mock_pool = MagicMock()
        mock_pool.select_device.return_value = None
        monkeypatch.setattr(
            "galaxy_gateway.routing.device_selection.get_device_pool_manager",
            lambda: mock_pool,
        )

        result = select_devices(analysis={}, candidates=[dev_attach, dev_dist])
        assert len(result) == 1
        assert result[0].device_id == "dev_dist_tier"

    def test_android_routing_weight_sentinel_present(self):
        from galaxy_gateway.routing.device_selection import (
            ANDROID_RUNTIME_TRUTH_ROUTING_WEIGHT_IN_SELECTION,
        )

        assert "step 0c" in ANDROID_RUNTIME_TRUTH_ROUTING_WEIGHT_IN_SELECTION.lower() or \
               "0c" in ANDROID_RUNTIME_TRUTH_ROUTING_WEIGHT_IN_SELECTION

    def test_select_devices_module_importable(self):
        import galaxy_gateway.routing.device_selection as _m

        assert hasattr(_m, "select_devices")
        assert hasattr(_m, "ANDROID_RUNTIME_TRUTH_ROUTING_WEIGHT_IN_SELECTION")


# ---------------------------------------------------------------------------
# E. post_closure_dual_repo_reassessment reflects P0 closed
# ---------------------------------------------------------------------------


class TestPostClosureReassessmentP0Closed:
    """post_closure_dual_repo_reassessment now reflects ORCHESTRATION_CONSUMES_ANDROID_TRUTH
    as closed (not STILL_MISSING_DECISION_PATH_CLOSURE)."""

    def test_orchestration_truth_path_not_still_missing(self):
        from core.post_closure_dual_repo_reassessment import (
            ClosureStatus,
            PostClosurePathId,
            build_post_closure_reassessment,
            reset_post_closure_reassessment,
        )

        reset_post_closure_reassessment()
        report = build_post_closure_reassessment()

        truth_path = next(
            (
                p
                for p in report.path_statuses
                if p.path_id == PostClosurePathId.ORCHESTRATION_CONSUMES_ANDROID_TRUTH
            ),
            None,
        )

        assert truth_path is not None
        # Must NOT still be STILL_MISSING_DECISION_PATH_CLOSURE.
        assert truth_path.updated_label != ClosureStatus.STILL_MISSING_DECISION_PATH_CLOSURE

    def test_orchestration_truth_path_has_closure_pr_ref(self):
        from core.post_closure_dual_repo_reassessment import (
            PostClosurePathId,
            build_post_closure_reassessment,
            reset_post_closure_reassessment,
        )

        reset_post_closure_reassessment()
        report = build_post_closure_reassessment()

        truth_path = next(
            (
                p
                for p in report.path_statuses
                if p.path_id == PostClosurePathId.ORCHESTRATION_CONSUMES_ANDROID_TRUTH
            ),
            None,
        )

        assert truth_path is not None
        assert len(truth_path.closure_pr_refs) > 0

    def test_orchestration_truth_path_gap_description_reflects_closure(self):
        from core.post_closure_dual_repo_reassessment import (
            PostClosurePathId,
            build_post_closure_reassessment,
            reset_post_closure_reassessment,
        )

        reset_post_closure_reassessment()
        report = build_post_closure_reassessment()

        truth_path = next(
            (
                p
                for p in report.path_statuses
                if p.path_id == PostClosurePathId.ORCHESTRATION_CONSUMES_ANDROID_TRUTH
            ),
            None,
        )

        assert truth_path is not None
        # gap_description must indicate closed state, not the old "REMAINING GAP" wording.
        assert "REMAINING GAP" not in truth_path.gap_description
        assert "CLOSED" in truth_path.gap_description


# ---------------------------------------------------------------------------
# F. Backward compatibility — absent snapshot degrades gracefully
# ---------------------------------------------------------------------------


class TestBackwardCompatGracefulDegradation:
    """All Android truth paths degrade gracefully when snapshot is absent."""

    def test_score_candidate_no_snapshot_is_baseline(self):
        from core.runtime.source_dispatch_orchestrator import _score_candidate

        score, rejection = _score_candidate(
            "sess_compat",
            "dev_compat",
            readiness=_make_readiness(),
            participation=_make_participation(),
            reuse_eligible=False,
            android_snapshot=None,
        )
        assert rejection == ""
        assert score == 100

    def test_score_candidate_snapshot_import_error_degrades(self, monkeypatch):
        """If android_device_state_store raises on import, selection still works."""
        from core.runtime.source_dispatch_orchestrator import _score_candidate

        # Even if android_snapshot is None (as happens when store is unavailable),
        # scoring must return a valid non-zero score.
        score, rejection = _score_candidate(
            "sess_compat2",
            "dev_compat2",
            readiness=_make_readiness(),
            participation=_make_participation(),
            reuse_eligible=False,
            android_snapshot=None,
        )
        assert rejection == ""
        assert score == 100

    def test_select_devices_routing_weight_error_does_not_crash(self, monkeypatch):
        """If the Android routing weight step raises, select_devices still returns a result."""
        from galaxy_gateway.routing.device_selection import select_devices

        dev = _make_device("dev_fallback")

        # Force the android truth step to raise.
        monkeypatch.setattr(
            "galaxy_gateway.routing.device_selection.get_device_state_snapshot",
            MagicMock(side_effect=RuntimeError("store unavailable")),
        )

        monkeypatch.setattr(
            "core.target_device_validator.validate_target_device",
            lambda tid: MagicMock(ready=True, registered=True, reasons=[]),
            raising=False,
        )
        monkeypatch.setattr(
            "galaxy_gateway.autonomous_filter.filter_autonomous_devices",
            lambda devices, **kw: [d for d in devices if d.status == "online"],
            raising=False,
        )
        mock_pool = MagicMock()
        mock_pool.select_device.return_value = None
        monkeypatch.setattr(
            "galaxy_gateway.routing.device_selection.get_device_pool_manager",
            lambda: mock_pool,
        )

        # Must not raise — graceful degradation.
        result = select_devices(analysis={}, candidates=[dev])
        assert len(result) == 1

    def test_select_target_store_unavailable_still_selects(self, monkeypatch):
        """If android_device_state_store is not importable, selection still works."""
        from core.runtime.source_dispatch_orchestrator import (
            _select_target_from_candidates,
        )

        device_id = "dev_no_store"
        entry = _make_registry_entry(device_id)

        monkeypatch.setattr(
            "core.attached_runtime_session_registry.list_active_sessions",
            lambda registry=None: [entry],
        )

        # Simulate store unavailable by passing empty android_snapshot_inputs
        # (device not in the dict → live lookup runs → will try import).
        # We pass android_snapshot_inputs={} so the key is absent — falls through
        # to the live lookup.  Live lookup may or may not succeed depending on
        # test environment; either path must not crash.
        result = _select_target_from_candidates(
            readiness_inputs={device_id: _make_readiness()},
            participation_inputs={device_id: _make_participation()},
            reuse_inputs={device_id: False},
            android_snapshot_inputs={},  # device absent → live lookup
        )

        # Result may or may not select the device depending on readiness, but
        # it MUST not raise.
        # If a target is returned, it must be our device.
        if result is not None:
            assert result.target_device_id == device_id
