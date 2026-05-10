"""tests/test_pr5_execution_runtime_truth_binding.py
=====================================================
PR-5 Regression suite — Android execution lifecycle truth binding.

Validates that V2 execution runtime snapshots and decision causality reflect
Android-remote truth quality rather than only V2-local bookkeeping, and that
missing or inconsistent Android lifecycle evidence causes diagnosable
degradation.

Acceptance criteria (from PR-5 problem statement):
- V2 runtime snapshots reflect Android truth quality (not only V2 local tracking).
- decision_causality includes android_lifecycle_truth_quality and related fields.
- Missing Android lifecycle evidence → missing_remote quality + degraded flag.
- Stale Android lifecycle evidence → stale_remote quality + degraded flag.
- Conflicting state (V2 active but Android terminal, or inverse) → conflicting_remote.
- No active V2 executions + no Android events → v2_local_only (clean idle).
- V2 active + recent Android active events → android_remote_confirmed.

Coverage groups:
  A — AndroidExecutionLifecycleTruthQuality enum completeness and sentinel
  B — _classify_android_execution_lifecycle_truth_quality: all quality branches
  C — get_execution_lifecycle_truth_binding: end-to-end binding construction
  D — get_execution_runtime_snapshot: per-device truth binding fields present
  E — decision_causality carries android_lifecycle_truth_quality via
      build_unified_governance_state
  F — governance impact mapping correctness
  G — boundary / edge cases (None values, missing store data)
  H — degraded qualities cause diagnosable governance impact
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from core.unified_execution_governance import (
    ANDROID_EXECUTION_LIFECYCLE_TRUTH_POLICY,
    ANDROID_EXECUTION_LIFECYCLE_TRUTH_STALE_AFTER_SECONDS,
    EXECUTION_LIFECYCLE_TRUTH_BINDING_CONTRACT_VERSION,
    EXECUTION_LIFECYCLE_TRUTH_BINDING_SENTINEL,
    AndroidExecutionLifecycleTruthQuality,
    ExecutionLifecycleTruthBinding,
    ExecutionType,
    _classify_android_execution_lifecycle_truth_quality,
    _clear_execution_governance_runtime_state,
    evaluate_execution_governance,
    get_execution_lifecycle_truth_binding,
    get_execution_runtime_snapshot,
)
from core.unified_governance_semantics import (
    GovernancePath,
    build_unified_governance_state,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_device_snapshot(
    *,
    offline_queue_depth: int = 0,
    current_fallback_tier: Optional[str] = None,
    is_local_ai_ready: bool = False,
    runtime_health_snapshot: Optional[Dict[str, Any]] = None,
) -> Any:
    """Return a minimal fake DeviceStateSnapshot."""
    ns = SimpleNamespace(
        offline_queue_depth=offline_queue_depth,
        current_fallback_tier=current_fallback_tier,
        runtime_health_snapshot=runtime_health_snapshot or {"status": "stable"},
    )
    ns.is_local_ai_ready = lambda: is_local_ai_ready
    return ns


def _make_execution_event(
    *,
    phase: str,
    device_id: str = "dev-test",
    flow_id: str = "flow-1",
    absorbed_at: float = 1_000_000.0,
) -> Any:
    return SimpleNamespace(
        phase=phase,
        device_id=device_id,
        flow_id=flow_id,
        absorbed_at=absorbed_at,
    )


def _empty_capability_semantics() -> Dict[str, Any]:
    return {}


# ---------------------------------------------------------------------------
# Group A — AndroidExecutionLifecycleTruthQuality enum and sentinel
# ---------------------------------------------------------------------------


class TestGroupA_EnumAndSentinel:
    """Verify enum completeness and module sentinel presence."""

    def test_all_five_quality_values_present(self) -> None:
        values = {q.value for q in AndroidExecutionLifecycleTruthQuality}
        assert "v2_local_only" in values
        assert "android_remote_confirmed" in values
        assert "stale_remote" in values
        assert "missing_remote" in values
        assert "conflicting_remote" in values

    def test_quality_enum_is_string_enum(self) -> None:
        assert isinstance(AndroidExecutionLifecycleTruthQuality.v2_local_only, str)
        assert AndroidExecutionLifecycleTruthQuality.android_remote_confirmed == "android_remote_confirmed"

    def test_sentinel_is_present_and_stable(self) -> None:
        assert "PR5_V2" in EXECUTION_LIFECYCLE_TRUTH_BINDING_SENTINEL

    def test_contract_version_is_stable(self) -> None:
        assert EXECUTION_LIFECYCLE_TRUTH_BINDING_CONTRACT_VERSION.startswith("5.")

    def test_stale_threshold_positive(self) -> None:
        assert ANDROID_EXECUTION_LIFECYCLE_TRUTH_STALE_AFTER_SECONDS > 0

    def test_policy_string_present(self) -> None:
        assert "missing_remote" in ANDROID_EXECUTION_LIFECYCLE_TRUTH_POLICY
        assert "conflicting_remote" in ANDROID_EXECUTION_LIFECYCLE_TRUTH_POLICY
        assert "android_remote_confirmed" in ANDROID_EXECUTION_LIFECYCLE_TRUTH_POLICY


# ---------------------------------------------------------------------------
# Group B — _classify_android_execution_lifecycle_truth_quality
# ---------------------------------------------------------------------------


class TestGroupB_ClassifyQuality:
    """Unit tests for the internal classification function."""

    def test_idle_no_events_returns_v2_local_only(self) -> None:
        quality, reason = _classify_android_execution_lifecycle_truth_quality(
            active_execution_count=0,
            latest_execution_event_phase=None,
            latest_execution_event_age_s=None,
        )
        assert quality == AndroidExecutionLifecycleTruthQuality.v2_local_only.value
        assert reason

    def test_active_no_events_returns_missing_remote(self) -> None:
        quality, reason = _classify_android_execution_lifecycle_truth_quality(
            active_execution_count=1,
            latest_execution_event_phase=None,
            latest_execution_event_age_s=None,
        )
        assert quality == AndroidExecutionLifecycleTruthQuality.missing_remote.value
        assert "no_android" in reason or "missing" in reason or "evidence" in reason

    def test_active_with_recent_android_active_returns_confirmed(self) -> None:
        quality, reason = _classify_android_execution_lifecycle_truth_quality(
            active_execution_count=2,
            latest_execution_event_phase="execution",
            latest_execution_event_age_s=5.0,
        )
        assert quality == AndroidExecutionLifecycleTruthQuality.android_remote_confirmed.value
        assert "age=" in reason or "active" in reason.lower()

    def test_active_with_old_android_event_returns_stale_remote(self) -> None:
        stale_age = ANDROID_EXECUTION_LIFECYCLE_TRUTH_STALE_AFTER_SECONDS + 30
        quality, reason = _classify_android_execution_lifecycle_truth_quality(
            active_execution_count=1,
            latest_execution_event_phase="execution",
            latest_execution_event_age_s=stale_age,
        )
        assert quality == AndroidExecutionLifecycleTruthQuality.stale_remote.value
        assert "stale" in reason.lower() or "exceeds" in reason.lower()

    def test_v2_active_android_terminal_returns_conflicting(self) -> None:
        quality, reason = _classify_android_execution_lifecycle_truth_quality(
            active_execution_count=1,
            latest_execution_event_phase="completed",
            latest_execution_event_age_s=10.0,
        )
        assert quality == AndroidExecutionLifecycleTruthQuality.conflicting_remote.value
        assert "terminal" in reason.lower() or "completed" in reason.lower()

    def test_v2_idle_android_active_returns_conflicting(self) -> None:
        quality, reason = _classify_android_execution_lifecycle_truth_quality(
            active_execution_count=0,
            latest_execution_event_phase="planning",
            latest_execution_event_age_s=5.0,
        )
        assert quality == AndroidExecutionLifecycleTruthQuality.conflicting_remote.value
        assert "active" in reason.lower() or "planning" in reason.lower()

    def test_active_with_stale_age_missing_age_returns_stale(self) -> None:
        # Android has an active phase but age is unknown.
        quality, reason = _classify_android_execution_lifecycle_truth_quality(
            active_execution_count=1,
            latest_execution_event_phase="grounding",
            latest_execution_event_age_s=None,
        )
        assert quality == AndroidExecutionLifecycleTruthQuality.stale_remote.value

    def test_v2_idle_android_terminal_returns_v2_local_only(self) -> None:
        quality, reason = _classify_android_execution_lifecycle_truth_quality(
            active_execution_count=0,
            latest_execution_event_phase="completed",
            latest_execution_event_age_s=30.0,
        )
        assert quality == AndroidExecutionLifecycleTruthQuality.v2_local_only.value

    def test_active_android_failed_is_conflicting(self) -> None:
        quality, _ = _classify_android_execution_lifecycle_truth_quality(
            active_execution_count=1,
            latest_execution_event_phase="failed",
            latest_execution_event_age_s=2.0,
        )
        assert quality == AndroidExecutionLifecycleTruthQuality.conflicting_remote.value

    def test_multiple_active_executions_confirmed(self) -> None:
        quality, _ = _classify_android_execution_lifecycle_truth_quality(
            active_execution_count=3,
            latest_execution_event_phase="replan",
            latest_execution_event_age_s=1.0,
        )
        assert quality == AndroidExecutionLifecycleTruthQuality.android_remote_confirmed.value

    @pytest.mark.parametrize(
        "phase",
        ["planning", "grounding", "execution", "replan", "running", "admitted"],
    )
    def test_all_active_phases_yield_confirmed_when_fresh(self, phase: str) -> None:
        quality, _ = _classify_android_execution_lifecycle_truth_quality(
            active_execution_count=1,
            latest_execution_event_phase=phase,
            latest_execution_event_age_s=1.0,
        )
        assert quality == AndroidExecutionLifecycleTruthQuality.android_remote_confirmed.value

    @pytest.mark.parametrize(
        "phase",
        ["completed", "succeeded", "failed", "cancelled", "canceled", "error", "timed_out"],
    )
    def test_all_terminal_phases_with_v2_active_yield_conflicting(self, phase: str) -> None:
        quality, _ = _classify_android_execution_lifecycle_truth_quality(
            active_execution_count=1,
            latest_execution_event_phase=phase,
            latest_execution_event_age_s=1.0,
        )
        assert quality == AndroidExecutionLifecycleTruthQuality.conflicting_remote.value


# ---------------------------------------------------------------------------
# Group C — get_execution_lifecycle_truth_binding
# ---------------------------------------------------------------------------


class TestGroupC_TruthBinding:
    """Tests for the public get_execution_lifecycle_truth_binding API."""

    def setup_method(self) -> None:
        _clear_execution_governance_runtime_state()

    def teardown_method(self) -> None:
        _clear_execution_governance_runtime_state()

    def test_returns_ExecutionLifecycleTruthBinding_instance(self) -> None:
        with (
            patch(
                "core.unified_execution_governance.get_device_state_snapshot",
                return_value=None,
            ) if False else patch("builtins.bool", bool),
        ):
            binding = get_execution_lifecycle_truth_binding("dev-X")
        assert isinstance(binding, ExecutionLifecycleTruthBinding)

    def test_idle_device_no_android_store_returns_v2_local_only(self) -> None:
        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": None,
                "latest_execution_event_age_s": None,
            },
        ):
            binding = get_execution_lifecycle_truth_binding("dev-idle")
        assert (
            binding.android_lifecycle_truth_quality
            == AndroidExecutionLifecycleTruthQuality.v2_local_only
        )
        assert not binding.android_lifecycle_truth_degraded
        assert binding.android_lifecycle_truth_governance_impact == "none"

    def test_missing_remote_when_v2_active_no_android(self) -> None:
        # Register a live execution
        evaluate_execution_governance(
            ExecutionType.goal_execution,
            "dev-active",
            register_if_accepted=False,
            skip_conflict_check=True,
        )
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-active", ExecutionType.goal_execution, "exec-1")

        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": None,
                "latest_execution_event_age_s": None,
            },
        ):
            binding = get_execution_lifecycle_truth_binding("dev-active")

        assert (
            binding.android_lifecycle_truth_quality
            == AndroidExecutionLifecycleTruthQuality.missing_remote
        )
        assert binding.android_lifecycle_truth_degraded
        assert binding.android_lifecycle_truth_governance_impact == "degraded"

    def test_stale_remote_when_v2_active_android_event_old(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-stale", ExecutionType.goal_execution, "exec-2")

        stale_age = ANDROID_EXECUTION_LIFECYCLE_TRUTH_STALE_AFTER_SECONDS + 60
        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": "execution",
                "latest_execution_event_age_s": stale_age,
            },
        ):
            binding = get_execution_lifecycle_truth_binding("dev-stale")

        assert (
            binding.android_lifecycle_truth_quality
            == AndroidExecutionLifecycleTruthQuality.stale_remote
        )
        assert binding.android_lifecycle_truth_degraded
        assert binding.android_lifecycle_truth_governance_impact == "degraded"

    def test_conflicting_remote_v2_active_android_terminal(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-conflict", ExecutionType.goal_execution, "exec-3")

        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": "completed",
                "latest_execution_event_age_s": 5.0,
            },
        ):
            binding = get_execution_lifecycle_truth_binding("dev-conflict")

        assert (
            binding.android_lifecycle_truth_quality
            == AndroidExecutionLifecycleTruthQuality.conflicting_remote
        )
        assert binding.android_lifecycle_truth_degraded
        assert binding.android_lifecycle_truth_governance_impact == "blocked"

    def test_confirmed_when_v2_active_android_active_fresh(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-ok", ExecutionType.goal_execution, "exec-4")

        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": "execution",
                "latest_execution_event_age_s": 3.0,
            },
        ):
            binding = get_execution_lifecycle_truth_binding("dev-ok")

        assert (
            binding.android_lifecycle_truth_quality
            == AndroidExecutionLifecycleTruthQuality.android_remote_confirmed
        )
        assert not binding.android_lifecycle_truth_degraded
        assert binding.android_lifecycle_truth_governance_impact == "none"

    def test_to_dict_contains_required_keys(self) -> None:
        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": None,
                "latest_execution_event_age_s": None,
            },
        ):
            binding = get_execution_lifecycle_truth_binding("dev-dict")

        d = binding.to_dict()
        assert "device_id" in d
        assert "android_lifecycle_truth_quality" in d
        assert "android_lifecycle_truth_reason" in d
        assert "android_lifecycle_truth_degraded" in d
        assert "android_lifecycle_truth_governance_impact" in d
        assert "active_execution_count" in d
        assert "latest_android_event_phase" in d
        assert "latest_android_event_age_s" in d
        assert "assessed_at" in d
        assert "_policy" in d
        assert "_contract_version" in d

    def test_never_raises_on_internal_error(self) -> None:
        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            side_effect=RuntimeError("boom"),
        ):
            binding = get_execution_lifecycle_truth_binding("dev-error")
        # Should return a safe fallback binding without raising.
        assert isinstance(binding, ExecutionLifecycleTruthBinding)
        assert (
            binding.android_lifecycle_truth_quality
            == AndroidExecutionLifecycleTruthQuality.v2_local_only
        )


# ---------------------------------------------------------------------------
# Group D — get_execution_runtime_snapshot includes truth binding fields
# ---------------------------------------------------------------------------


class TestGroupD_RuntimeSnapshotFields:
    """Verify that get_execution_runtime_snapshot embeds truth binding per device."""

    def setup_method(self) -> None:
        _clear_execution_governance_runtime_state()

    def teardown_method(self) -> None:
        _clear_execution_governance_runtime_state()

    def _snapshot_for_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        snapshot = get_execution_runtime_snapshot(device_ids=[device_id])
        devices = snapshot.get("devices", [])
        return next((d for d in devices if d.get("device_id") == device_id), None)

    def test_snapshot_device_has_truth_quality_field(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-snap", ExecutionType.goal_execution, "e1")

        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": None,
                "latest_execution_event_age_s": None,
            },
        ):
            device = self._snapshot_for_device("dev-snap")

        assert device is not None
        assert "android_lifecycle_truth_quality" in device
        assert "android_lifecycle_truth_reason" in device
        assert "android_lifecycle_truth_degraded" in device
        assert "android_lifecycle_truth_governance_impact" in device

    def test_snapshot_missing_remote_when_no_android_events(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-miss", ExecutionType.goal_execution, "e2")

        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": None,
                "latest_execution_event_age_s": None,
            },
        ):
            device = self._snapshot_for_device("dev-miss")

        assert device is not None
        assert device["android_lifecycle_truth_quality"] == "missing_remote"
        assert device["android_lifecycle_truth_degraded"] is True
        assert device["android_lifecycle_truth_governance_impact"] == "degraded"

    def test_snapshot_confirmed_when_android_active_fresh(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-conf", ExecutionType.goal_execution, "e3")

        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": "grounding",
                "latest_execution_event_age_s": 2.0,
            },
        ):
            device = self._snapshot_for_device("dev-conf")

        assert device is not None
        assert device["android_lifecycle_truth_quality"] == "android_remote_confirmed"
        assert device["android_lifecycle_truth_degraded"] is False
        assert device["android_lifecycle_truth_governance_impact"] == "none"

    def test_snapshot_conflicting_v2_active_android_terminal(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-cfl", ExecutionType.goal_execution, "e4")

        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": "failed",
                "latest_execution_event_age_s": 3.0,
            },
        ):
            device = self._snapshot_for_device("dev-cfl")

        assert device is not None
        assert device["android_lifecycle_truth_quality"] == "conflicting_remote"
        assert device["android_lifecycle_truth_degraded"] is True
        assert device["android_lifecycle_truth_governance_impact"] == "blocked"

    def test_snapshot_stale_remote_old_android_event(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-stl", ExecutionType.goal_execution, "e5")

        old_age = ANDROID_EXECUTION_LIFECYCLE_TRUTH_STALE_AFTER_SECONDS + 120
        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": "execution",
                "latest_execution_event_age_s": old_age,
            },
        ):
            device = self._snapshot_for_device("dev-stl")

        assert device is not None
        assert device["android_lifecycle_truth_quality"] == "stale_remote"
        assert device["android_lifecycle_truth_degraded"] is True

    def test_snapshot_source_field_present(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-src", ExecutionType.goal_execution, "e6")

        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": None,
                "latest_execution_event_age_s": None,
            },
        ):
            device = self._snapshot_for_device("dev-src")

        assert device is not None
        # The _source field must still be present (no regression).
        assert "_source" in device


# ---------------------------------------------------------------------------
# Group E — decision_causality carries truth quality via build_unified_governance_state
# ---------------------------------------------------------------------------


class TestGroupE_DecisionCausality:
    """Verify that decision_causality in build_unified_governance_state includes
    android_lifecycle_truth_quality and related fields."""

    def setup_method(self) -> None:
        _clear_execution_governance_runtime_state()

    def teardown_method(self) -> None:
        _clear_execution_governance_runtime_state()

    def _get_causality_for_device(
        self,
        device_id: str,
        path: GovernancePath = GovernancePath.local_planning,
    ) -> Optional[Dict[str, Any]]:
        state = build_unified_governance_state(device_ids=[device_id])
        devices = state.get("devices", [])
        for dev in devices:
            if dev.get("device_id") == device_id:
                governance = dev.get("governance_precedence", {})
                path_data = governance.get(path.value, {})
                return path_data.get("decision_causality")
        return None

    def _patch_android_store(
        self,
        *,
        phase: Optional[str] = None,
        age_s: Optional[float] = None,
    ):
        return patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": phase,
                "latest_execution_event_age_s": age_s,
                "offline_queue_depth": 0,
                "current_fallback_tier": None,
                "local_inference_available": False,
                "android_reported_mode": None,
                "android_reported_mode_state": None,
                "android_reported_mode_readiness_state": None,
                "android_reported_cross_device_eligibility": None,
                "android_reported_goal_execution_eligibility": None,
                "android_reported_parallel_execution_eligibility": None,
                "android_reported_local_intelligence_status": None,
                "android_reported_local_inference_ready": None,
                "android_reported_local_inference_available": None,
                "android_semantics_contract_state": "missing",
                "android_semantics_contract_complete": False,
                "android_semantics_missing_keys": [],
                "android_semantics_malformed_keys": [],
                "android_semantics_unknown_keys": [],
                "android_semantics_conflicts": [],
                "android_semantics_downgraded_reasons": [],
                "android_semantics_governance_readiness_impact": "block",
                "android_semantics_contract_diagnosis": None,
                "android_semantics_absorbed_at": 0.0,
                "android_semantics_reported_at": None,
                "android_semantics_age_s": None,
                "android_semantics_freshness_threshold_s": 120.0,
                "android_semantics_freshness_state": "unknown",
                "android_semantics_freshness_reason": "no_android_runtime_truth",
                "android_runtime_truth_authority": "unknown",
                "android_runtime_truth_usable": False,
                "runtime_health_status": "unknown",
                "execution_busy": False,
                "snapshot_reconciliation_status": "unavailable",
                "snapshot_reconciliation_reason": "no_snapshot_reconciliation_data",
                "snapshot_conflict": False,
                "snapshot_ordering_basis": "none",
                "snapshot_last_updated_at": 0.0,
                "snapshot_reconciliation_applied": False,
                "execution_busy_window_seconds": 60.0,
            },
        )

    def test_decision_causality_has_truth_quality_field(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-dc1", ExecutionType.goal_execution, "ex1")

        with self._patch_android_store(phase=None, age_s=None):
            causality = self._get_causality_for_device("dev-dc1")

        assert causality is not None
        assert "android_lifecycle_truth_quality" in causality

    def test_decision_causality_has_truth_degraded_field(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-dc2", ExecutionType.goal_execution, "ex2")

        with self._patch_android_store(phase=None, age_s=None):
            causality = self._get_causality_for_device("dev-dc2")

        assert causality is not None
        assert "android_lifecycle_truth_degraded" in causality

    def test_decision_causality_has_governance_impact_field(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-dc3", ExecutionType.goal_execution, "ex3")

        with self._patch_android_store(phase=None, age_s=None):
            causality = self._get_causality_for_device("dev-dc3")

        assert causality is not None
        assert "android_lifecycle_truth_governance_impact" in causality

    def test_decision_causality_missing_remote_is_diagnosable(self) -> None:
        """Missing Android evidence must be diagnosable in decision_causality."""
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-diag1", ExecutionType.goal_execution, "ex4")

        with self._patch_android_store(phase=None, age_s=None):
            causality = self._get_causality_for_device("dev-diag1")

        assert causality is not None
        assert causality["android_lifecycle_truth_quality"] == "missing_remote"
        assert causality["android_lifecycle_truth_degraded"] is True
        assert causality["android_lifecycle_truth_governance_impact"] == "degraded"

    def test_decision_causality_conflicting_remote_is_diagnosable(self) -> None:
        """Conflicting Android evidence must be diagnosable in decision_causality."""
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-diag2", ExecutionType.goal_execution, "ex5")

        with self._patch_android_store(phase="completed", age_s=3.0):
            causality = self._get_causality_for_device("dev-diag2")

        assert causality is not None
        assert causality["android_lifecycle_truth_quality"] == "conflicting_remote"
        assert causality["android_lifecycle_truth_degraded"] is True
        assert causality["android_lifecycle_truth_governance_impact"] == "blocked"

    def test_decision_causality_confirmed_when_android_active_fresh(self) -> None:
        """android_remote_confirmed must appear in causality when Android is fresh."""
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-diag3", ExecutionType.goal_execution, "ex6")

        with self._patch_android_store(phase="execution", age_s=5.0):
            causality = self._get_causality_for_device("dev-diag3")

        assert causality is not None
        assert causality["android_lifecycle_truth_quality"] == "android_remote_confirmed"
        assert causality["android_lifecycle_truth_degraded"] is False
        assert causality["android_lifecycle_truth_governance_impact"] == "none"

    def test_decision_causality_includes_truth_reason_string(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-diag4", ExecutionType.goal_execution, "ex7")

        with self._patch_android_store(phase=None, age_s=None):
            causality = self._get_causality_for_device("dev-diag4")

        assert causality is not None
        # truth_reason must be a non-empty string
        reason = causality.get("android_lifecycle_truth_reason")
        assert isinstance(reason, str)
        assert len(reason) > 0


# ---------------------------------------------------------------------------
# Group F — governance impact mapping correctness
# ---------------------------------------------------------------------------


class TestGroupF_GovernanceImpactMapping:
    """Verify that the governance impact mapping is correct for all quality values."""

    def test_v2_local_only_impact_none(self) -> None:
        from core.unified_execution_governance import _ANDROID_LIFECYCLE_TRUTH_GOVERNANCE_IMPACT
        impact = _ANDROID_LIFECYCLE_TRUTH_GOVERNANCE_IMPACT[
            AndroidExecutionLifecycleTruthQuality.v2_local_only
        ]
        assert impact == "none"

    def test_android_remote_confirmed_impact_none(self) -> None:
        from core.unified_execution_governance import _ANDROID_LIFECYCLE_TRUTH_GOVERNANCE_IMPACT
        impact = _ANDROID_LIFECYCLE_TRUTH_GOVERNANCE_IMPACT[
            AndroidExecutionLifecycleTruthQuality.android_remote_confirmed
        ]
        assert impact == "none"

    def test_stale_remote_impact_degraded(self) -> None:
        from core.unified_execution_governance import _ANDROID_LIFECYCLE_TRUTH_GOVERNANCE_IMPACT
        impact = _ANDROID_LIFECYCLE_TRUTH_GOVERNANCE_IMPACT[
            AndroidExecutionLifecycleTruthQuality.stale_remote
        ]
        assert impact == "degraded"

    def test_missing_remote_impact_degraded(self) -> None:
        from core.unified_execution_governance import _ANDROID_LIFECYCLE_TRUTH_GOVERNANCE_IMPACT
        impact = _ANDROID_LIFECYCLE_TRUTH_GOVERNANCE_IMPACT[
            AndroidExecutionLifecycleTruthQuality.missing_remote
        ]
        assert impact == "degraded"

    def test_conflicting_remote_impact_blocked(self) -> None:
        from core.unified_execution_governance import _ANDROID_LIFECYCLE_TRUTH_GOVERNANCE_IMPACT
        impact = _ANDROID_LIFECYCLE_TRUTH_GOVERNANCE_IMPACT[
            AndroidExecutionLifecycleTruthQuality.conflicting_remote
        ]
        assert impact == "blocked"

    def test_all_qualities_have_mapping(self) -> None:
        from core.unified_execution_governance import _ANDROID_LIFECYCLE_TRUTH_GOVERNANCE_IMPACT
        for quality in AndroidExecutionLifecycleTruthQuality:
            assert quality in _ANDROID_LIFECYCLE_TRUTH_GOVERNANCE_IMPACT, (
                f"Missing impact mapping for {quality}"
            )

    def test_degraded_quality_set_contains_correct_members(self) -> None:
        from core.unified_execution_governance import _ANDROID_LIFECYCLE_TRUTH_DEGRADED_QUALITIES
        assert AndroidExecutionLifecycleTruthQuality.missing_remote in _ANDROID_LIFECYCLE_TRUTH_DEGRADED_QUALITIES
        assert AndroidExecutionLifecycleTruthQuality.stale_remote in _ANDROID_LIFECYCLE_TRUTH_DEGRADED_QUALITIES
        assert AndroidExecutionLifecycleTruthQuality.conflicting_remote in _ANDROID_LIFECYCLE_TRUTH_DEGRADED_QUALITIES
        assert AndroidExecutionLifecycleTruthQuality.v2_local_only not in _ANDROID_LIFECYCLE_TRUTH_DEGRADED_QUALITIES
        assert AndroidExecutionLifecycleTruthQuality.android_remote_confirmed not in _ANDROID_LIFECYCLE_TRUTH_DEGRADED_QUALITIES


# ---------------------------------------------------------------------------
# Group G — boundary / edge cases
# ---------------------------------------------------------------------------


class TestGroupG_BoundaryAndEdgeCases:
    """Edge cases for the classification function and binding API."""

    def setup_method(self) -> None:
        _clear_execution_governance_runtime_state()

    def teardown_method(self) -> None:
        _clear_execution_governance_runtime_state()

    def test_exactly_at_stale_threshold_is_confirmed(self) -> None:
        # Age exactly equal to threshold → confirmed (strictly greater than triggers stale)
        quality, _ = _classify_android_execution_lifecycle_truth_quality(
            active_execution_count=1,
            latest_execution_event_phase="execution",
            latest_execution_event_age_s=ANDROID_EXECUTION_LIFECYCLE_TRUTH_STALE_AFTER_SECONDS,
        )
        assert quality == AndroidExecutionLifecycleTruthQuality.android_remote_confirmed.value

    def test_just_below_stale_threshold_is_confirmed(self) -> None:
        # Age just below threshold → confirmed
        quality, _ = _classify_android_execution_lifecycle_truth_quality(
            active_execution_count=1,
            latest_execution_event_phase="execution",
            latest_execution_event_age_s=ANDROID_EXECUTION_LIFECYCLE_TRUTH_STALE_AFTER_SECONDS - 0.1,
        )
        assert quality == AndroidExecutionLifecycleTruthQuality.android_remote_confirmed.value

    def test_zero_active_count_is_idle(self) -> None:
        quality, _ = _classify_android_execution_lifecycle_truth_quality(
            active_execution_count=0,
            latest_execution_event_phase=None,
            latest_execution_event_age_s=None,
        )
        assert quality == AndroidExecutionLifecycleTruthQuality.v2_local_only.value

    def test_binding_active_count_matches_actual(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-cnt", ExecutionType.goal_execution, "ea")
        _register_active_execution("dev-cnt", ExecutionType.parallel_subtask, "eb")

        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": "execution",
                "latest_execution_event_age_s": 1.0,
            },
        ):
            binding = get_execution_lifecycle_truth_binding("dev-cnt")

        assert binding.active_execution_count == 2

    def test_binding_latest_phase_propagated(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-ph", ExecutionType.goal_execution, "ec")

        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": "grounding",
                "latest_execution_event_age_s": 5.0,
            },
        ):
            binding = get_execution_lifecycle_truth_binding("dev-ph")

        assert binding.latest_android_event_phase == "grounding"
        assert binding.latest_android_event_age_s == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Group H — degraded qualities cause diagnosable governance impact
# ---------------------------------------------------------------------------


class TestGroupH_DegradedQualityDiagnosability:
    """Verify that degraded truth quality is diagnosable through the full path."""

    def setup_method(self) -> None:
        _clear_execution_governance_runtime_state()

    def teardown_method(self) -> None:
        _clear_execution_governance_runtime_state()

    def test_missing_remote_marked_degraded_in_binding(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-h1", ExecutionType.goal_execution, "hx1")

        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": None,
                "latest_execution_event_age_s": None,
            },
        ):
            binding = get_execution_lifecycle_truth_binding("dev-h1")

        assert binding.android_lifecycle_truth_degraded is True
        assert binding.android_lifecycle_truth_quality != AndroidExecutionLifecycleTruthQuality.android_remote_confirmed

    def test_stale_remote_governance_impact_is_degraded_not_blocked(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-h2", ExecutionType.goal_execution, "hx2")

        old_age = ANDROID_EXECUTION_LIFECYCLE_TRUTH_STALE_AFTER_SECONDS + 200
        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": "execution",
                "latest_execution_event_age_s": old_age,
            },
        ):
            binding = get_execution_lifecycle_truth_binding("dev-h2")

        assert binding.android_lifecycle_truth_governance_impact == "degraded"
        assert binding.android_lifecycle_truth_governance_impact != "blocked"

    def test_conflicting_remote_governance_impact_is_blocked(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-h3", ExecutionType.goal_execution, "hx3")

        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": "succeeded",
                "latest_execution_event_age_s": 2.0,
            },
        ):
            binding = get_execution_lifecycle_truth_binding("dev-h3")

        assert binding.android_lifecycle_truth_governance_impact == "blocked"

    def test_non_degraded_qualities_have_none_impact(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-h4", ExecutionType.goal_execution, "hx4")

        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": "execution",
                "latest_execution_event_age_s": 1.0,
            },
        ):
            binding = get_execution_lifecycle_truth_binding("dev-h4")

        assert not binding.android_lifecycle_truth_degraded
        assert binding.android_lifecycle_truth_governance_impact == "none"

    def test_missing_remote_reason_is_non_empty_string(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-h5", ExecutionType.goal_execution, "hx5")

        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": None,
                "latest_execution_event_age_s": None,
            },
        ):
            binding = get_execution_lifecycle_truth_binding("dev-h5")

        assert isinstance(binding.android_lifecycle_truth_reason, str)
        assert len(binding.android_lifecycle_truth_reason) > 0

    def test_conflicting_remote_reason_names_the_conflict(self) -> None:
        from core.unified_execution_governance import _register_active_execution
        _register_active_execution("dev-h6", ExecutionType.goal_execution, "hx6")

        with patch(
            "core.unified_execution_governance._get_android_runtime_pressure_snapshot",
            return_value={
                "latest_execution_event_phase": "failed",
                "latest_execution_event_age_s": 1.0,
            },
        ):
            binding = get_execution_lifecycle_truth_binding("dev-h6")

        # The reason must mention the conflict.
        reason = binding.android_lifecycle_truth_reason
        assert "terminal" in reason.lower() or "failed" in reason.lower() or "conflict" in reason.lower()
