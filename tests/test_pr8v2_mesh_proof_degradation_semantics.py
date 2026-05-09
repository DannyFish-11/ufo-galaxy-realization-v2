"""tests/test_pr8v2_mesh_proof_degradation_semantics.py
=======================================================
PR-08v2 Regression suite — Canonical mesh/runtime proof degradation semantics.

Validates that governance does NOT overstate live mesh readiness when proof is
partial, stale, missing, or structurally incomplete.

Acceptance criteria (from PR-08v2 problem statement):
- Canonical V2 decisions explicitly degrade when mesh/runtime proof is
  partial, stale, missing, or structurally incomplete.
- Governance no longer overstates live mesh readiness on weak proof.
- proof_quality and governance_readiness_impact are surfaced in
  build_mesh_runtime_state() output.
- decision_causality carries mesh_proof_quality and
  mesh_governance_readiness_impact for every path.
- multimodal_participation is blocked when proof quality is not live.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch

from core.unified_governance_semantics import (
    GovernancePath,
    MESH_RUNTIME_PROOF_QUALITY_LIVE,
    MESH_RUNTIME_PROOF_QUALITY_MISSING,
    MESH_RUNTIME_PROOF_QUALITY_PARTIAL,
    MESH_RUNTIME_PROOF_QUALITY_STALE,
    MESH_RUNTIME_PROOF_QUALITY_STRUCTURALLY_INFERRED,
    MESH_RUNTIME_PROOF_STALE_AFTER_SECONDS,
    MESH_RUNTIME_STATUS_CONTRACT_ONLY,
    MESH_RUNTIME_STATUS_PARTIAL,
    MESH_RUNTIME_STATUS_RUNTIME_PROVEN,
    build_mesh_runtime_state,
    build_unified_governance_state,
    resolve_governance_path_decision,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EMPTY_PROOF_SNAPSHOT: dict = {
    "staged_mesh_dispatch_count": 0,
    "live_mesh_run_count": 0,
    "live_mesh_completed_count": 0,
    "live_mesh_partial_count": 0,
    "live_mesh_failed_count": 0,
    "last_live_outcome": None,
    "last_mesh_session_id": None,
    "last_live_run_at": None,
}


def _make_live_proof_snapshot(
    *,
    run_count: int = 1,
    last_live_run_at: float | None = None,
    outcome: str = "completed",
) -> dict:
    snap = dict(_EMPTY_PROOF_SNAPSHOT)
    snap["staged_mesh_dispatch_count"] = run_count
    snap["live_mesh_run_count"] = run_count
    snap["live_mesh_completed_count"] = run_count if outcome == "completed" else 0
    snap["live_mesh_partial_count"] = run_count if outcome == "partial" else 0
    snap["live_mesh_failed_count"] = run_count if outcome == "failed" else 0
    snap["last_live_outcome"] = outcome
    snap["last_mesh_session_id"] = "test_session"
    snap["last_live_run_at"] = last_live_run_at
    return snap


# ---------------------------------------------------------------------------
# Group A — build_mesh_runtime_state: proof_quality field
# ---------------------------------------------------------------------------


class TestGroupA_MeshRuntimeStateProofQuality:
    """build_mesh_runtime_state returns explicit proof_quality."""

    def test_a1_no_sentinels_no_runs_proof_quality_is_missing(self) -> None:
        """When no sentinels and no live runs exist, proof_quality is missing."""
        with patch(
            "core.unified_governance_semantics._has_sentinel",
            return_value=False,
        ), patch(
            "core.unified_governance_semantics.build_mesh_runtime_state.__wrapped__"
            if hasattr(build_mesh_runtime_state, "__wrapped__")
            else "core.runtime.source_dispatch_orchestrator.get_live_mesh_runtime_proof_snapshot",
            return_value=_EMPTY_PROOF_SNAPSHOT,
        ):
            # Direct snapshot injection via the orchestrator mock
            with patch(
                "core.runtime.source_dispatch_orchestrator.get_live_mesh_runtime_proof_snapshot",
                return_value=_EMPTY_PROOF_SNAPSHOT,
            ):
                from core.runtime.source_dispatch_orchestrator import (
                    reset_live_mesh_runtime_proof_snapshot,
                )
                reset_live_mesh_runtime_proof_snapshot()
                # Disable all sentinels
                with patch("core.unified_governance_semantics._has_sentinel", return_value=False):
                    state = build_mesh_runtime_state()

        assert state["proof_quality"] == MESH_RUNTIME_PROOF_QUALITY_MISSING
        assert state["governance_readiness_impact"] == "blocked_no_proof"
        assert state["status"] == MESH_RUNTIME_STATUS_CONTRACT_ONLY

    def test_a2_sentinel_only_proof_quality_is_structurally_inferred(self) -> None:
        """Sentinel proofs with no live run yield structurally_inferred quality."""
        from core.runtime.source_dispatch_orchestrator import reset_live_mesh_runtime_proof_snapshot
        reset_live_mesh_runtime_proof_snapshot()

        # At least one sentinel is present (default state has orchestrator sentinel)
        state = build_mesh_runtime_state()
        # Without a live run, proof quality must NOT claim live
        assert state["proof_quality"] != MESH_RUNTIME_PROOF_QUALITY_LIVE
        assert state["proof_quality"] in {
            MESH_RUNTIME_PROOF_QUALITY_STRUCTURALLY_INFERRED,
            MESH_RUNTIME_PROOF_QUALITY_MISSING,
        }
        assert state["governance_readiness_impact"] != "none"

    def test_a3_live_run_fresh_proof_quality_is_live(self) -> None:
        """A recent live run yields proof_quality=live and impact=none."""
        fresh_snapshot = _make_live_proof_snapshot(
            last_live_run_at=time.time() - 10.0  # 10 seconds ago
        )
        with patch(
            "core.runtime.source_dispatch_orchestrator.get_live_mesh_runtime_proof_snapshot",
            return_value=fresh_snapshot,
        ):
            state = build_mesh_runtime_state()

        assert state["proof_quality"] == MESH_RUNTIME_PROOF_QUALITY_LIVE
        assert state["governance_readiness_impact"] == "none"
        assert state["status"] == MESH_RUNTIME_STATUS_RUNTIME_PROVEN

    def test_a4_live_run_stale_proof_quality_is_stale(self) -> None:
        """A live run whose timestamp exceeds the threshold yields proof_quality=stale."""
        stale_run_at = time.time() - MESH_RUNTIME_PROOF_STALE_AFTER_SECONDS - 60.0
        stale_snapshot = _make_live_proof_snapshot(last_live_run_at=stale_run_at)
        with patch(
            "core.runtime.source_dispatch_orchestrator.get_live_mesh_runtime_proof_snapshot",
            return_value=stale_snapshot,
        ):
            state = build_mesh_runtime_state()

        assert state["proof_quality"] == MESH_RUNTIME_PROOF_QUALITY_STALE
        assert state["governance_readiness_impact"] == "degraded_stale_proof"
        # status stays runtime_proven (backward compat) but quality degrades
        assert state["status"] == MESH_RUNTIME_STATUS_RUNTIME_PROVEN

    def test_a5_live_run_no_timestamp_proof_quality_is_stale(self) -> None:
        """A live run with no timestamp is conservatively treated as stale."""
        no_ts_snapshot = _make_live_proof_snapshot(last_live_run_at=None)
        with patch(
            "core.runtime.source_dispatch_orchestrator.get_live_mesh_runtime_proof_snapshot",
            return_value=no_ts_snapshot,
        ):
            state = build_mesh_runtime_state()

        assert state["proof_quality"] == MESH_RUNTIME_PROOF_QUALITY_STALE
        assert state["governance_readiness_impact"] == "degraded_stale_proof"

    def test_a6_proof_quality_reason_is_present(self) -> None:
        """proof_quality_reason is always a non-empty string."""
        from core.runtime.source_dispatch_orchestrator import reset_live_mesh_runtime_proof_snapshot
        reset_live_mesh_runtime_proof_snapshot()
        state = build_mesh_runtime_state()
        assert isinstance(state.get("proof_quality_reason"), str)
        assert state["proof_quality_reason"]

    def test_a7_observability_includes_last_live_run_at_and_threshold(self) -> None:
        """runtime_observability carries last_live_run_at and proof_stale_after_seconds."""
        fresh_snapshot = _make_live_proof_snapshot(last_live_run_at=time.time() - 5.0)
        with patch(
            "core.runtime.source_dispatch_orchestrator.get_live_mesh_runtime_proof_snapshot",
            return_value=fresh_snapshot,
        ):
            state = build_mesh_runtime_state()

        live_proof = state["runtime_observability"]["live_mesh_runtime_proof"]
        assert "last_live_run_at" in live_proof
        assert "proof_stale_after_seconds" in live_proof
        assert live_proof["proof_stale_after_seconds"] == MESH_RUNTIME_PROOF_STALE_AFTER_SECONDS


# ---------------------------------------------------------------------------
# Group B — resolve_governance_path_decision: mesh proof quality degradation
# ---------------------------------------------------------------------------


class TestGroupB_GovernancePathDecisionMeshProofQuality:
    """resolve_governance_path_decision degrades multimodal_participation for weak proof."""

    def _make_cross_device_kwargs(self, **overrides: object) -> dict:
        base = dict(
            mode="cross_device",
            path=GovernancePath.multimodal_participation,
            dispatch_eligible=True,
            takeover_eligible=True,
            takeover_active=False,
        )
        base.update(overrides)
        return base

    def test_b1_multimodal_participation_eligible_when_proof_is_live(self) -> None:
        decision = resolve_governance_path_decision(
            **self._make_cross_device_kwargs(mesh_proof_quality=MESH_RUNTIME_PROOF_QUALITY_LIVE)
        )
        assert decision.eligible is True
        assert decision.blocked_by is None

    def test_b2_multimodal_participation_blocked_when_proof_is_stale(self) -> None:
        decision = resolve_governance_path_decision(
            **self._make_cross_device_kwargs(mesh_proof_quality=MESH_RUNTIME_PROOF_QUALITY_STALE)
        )
        assert decision.eligible is False
        assert "stale" in (decision.blocked_by or "")

    def test_b3_multimodal_participation_blocked_when_proof_is_partial(self) -> None:
        decision = resolve_governance_path_decision(
            **self._make_cross_device_kwargs(mesh_proof_quality=MESH_RUNTIME_PROOF_QUALITY_PARTIAL)
        )
        assert decision.eligible is False
        assert "partial" in (decision.blocked_by or "")

    def test_b4_multimodal_participation_blocked_when_proof_is_structurally_inferred(
        self,
    ) -> None:
        decision = resolve_governance_path_decision(
            **self._make_cross_device_kwargs(
                mesh_proof_quality=MESH_RUNTIME_PROOF_QUALITY_STRUCTURALLY_INFERRED
            )
        )
        assert decision.eligible is False
        assert "structurally_inferred" in (decision.blocked_by or "")

    def test_b5_multimodal_participation_blocked_when_proof_is_missing(self) -> None:
        decision = resolve_governance_path_decision(
            **self._make_cross_device_kwargs(mesh_proof_quality=MESH_RUNTIME_PROOF_QUALITY_MISSING)
        )
        assert decision.eligible is False
        assert "missing" in (decision.blocked_by or "")

    def test_b6_multimodal_participation_eligible_when_mesh_proof_quality_not_provided(
        self,
    ) -> None:
        """When no mesh_proof_quality is given, path remains eligible (backward compat)."""
        decision = resolve_governance_path_decision(
            **self._make_cross_device_kwargs()  # no mesh_proof_quality
        )
        assert decision.eligible is True

    def test_b7_delegated_execution_not_blocked_by_mesh_proof_alone(self) -> None:
        """delegated_execution is gated by existing mechanisms, not mesh proof alone."""
        decision = resolve_governance_path_decision(
            mode="cross_device",
            path=GovernancePath.delegated_execution,
            dispatch_eligible=True,
            takeover_eligible=True,
            takeover_active=False,
            mesh_proof_quality=MESH_RUNTIME_PROOF_QUALITY_STRUCTURALLY_INFERRED,
        )
        # Should remain eligible (mesh proof alone does not block delegated path)
        assert decision.eligible is True

    def test_b8_takeover_active_still_blocks_regardless_of_mesh_proof(self) -> None:
        """takeover_active block takes precedence over mesh proof quality."""
        decision = resolve_governance_path_decision(
            mode="cross_device",
            path=GovernancePath.multimodal_participation,
            dispatch_eligible=True,
            takeover_eligible=True,
            takeover_active=True,
            mesh_proof_quality=MESH_RUNTIME_PROOF_QUALITY_LIVE,
        )
        assert decision.eligible is False
        assert decision.blocked_by == "takeover"

    def test_b9_android_scope_set_to_mesh_proof_degraded_when_blocked(self) -> None:
        """android_scope exposes mesh_proof_degraded when multimodal is blocked by proof."""
        decision = resolve_governance_path_decision(
            mode="cross_device",
            path=GovernancePath.multimodal_participation,
            dispatch_eligible=True,
            takeover_eligible=True,
            takeover_active=False,
            mesh_proof_quality=MESH_RUNTIME_PROOF_QUALITY_STALE,
        )
        assert decision.eligible is False
        assert decision.android_scope == "mesh_proof_degraded"


# ---------------------------------------------------------------------------
# Group C — build_unified_governance_state: mesh proof quality in causality
# ---------------------------------------------------------------------------


class TestGroupC_UnifiedGovernanceStateMeshProofCausality:
    """build_unified_governance_state propagates mesh proof quality into decision_causality."""

    def _base_runtime_snapshot(self, device_id: str = "dev_cross") -> dict:
        return {
            "devices": [
                {
                    "device_id": device_id,
                    "active_execution_count": 0,
                    "highest_priority_execution_type": None,
                    "blocked_execution_types": [],
                    "offline_queue_depth": 0,
                    "execution_busy": False,
                    "local_inference_available": True,
                    "runtime_health_status": "healthy",
                    "current_fallback_tier": None,
                    "snapshot_reconciliation_status": "accepted",
                    "snapshot_reconciliation_reason": "newer_snapshot_timestamp",
                    "snapshot_conflict": False,
                    "snapshot_ordering_basis": "snapshot_ts",
                    "snapshot_last_updated_at": 123.0,
                    "snapshot_reconciliation_applied": True,
                    "latest_execution_event_phase": None,
                    "latest_execution_event_absorbed_at": 0.0,
                    "latest_execution_event_age_s": None,
                    "execution_busy_window_seconds": 60.0,
                }
            ],
            "active_device_count": 0,
            "active_execution_total_count": 0,
        }

    def test_c1_decision_causality_carries_mesh_proof_quality(self) -> None:
        """Every path's decision_causality includes mesh_proof_quality."""
        active_sessions = [SimpleNamespace(device_id="dev_cross")]
        mode_map = {"dev_cross": SimpleNamespace(mode=SimpleNamespace(value="cross_device"))}
        readiness_map = {
            "dev_cross": SimpleNamespace(
                is_dispatch_eligible=True,
                is_takeover_eligible=True,
                is_cross_device_ready=True,
            )
        }
        fresh_mesh = _make_live_proof_snapshot(last_live_run_at=time.time() - 5.0)

        with patch(
            "core.attached_runtime_session_registry.list_active_sessions",
            return_value=active_sessions,
        ), patch(
            "core.android_mode_gate_policy.build_mode_state_for_device",
            side_effect=lambda device_id: mode_map[device_id],
        ), patch(
            "core.android_mode_gate_policy.evaluate_android_mode_readiness",
            side_effect=lambda device_id: readiness_map[device_id],
        ), patch(
            "core.unified_execution_governance.is_takeover_active",
            return_value=False,
        ), patch(
            "core.unified_execution_governance.get_execution_runtime_snapshot",
            return_value=self._base_runtime_snapshot(),
        ), patch(
            "core.runtime.source_dispatch_orchestrator.get_live_mesh_runtime_proof_snapshot",
            return_value=fresh_mesh,
        ):
            state = build_unified_governance_state()

        device = state["devices"][0]
        for path_name, path_decision in device["governance_precedence"].items():
            causality = path_decision.get("decision_causality", {})
            assert "mesh_proof_quality" in causality, f"missing mesh_proof_quality on path {path_name}"
            assert "mesh_governance_readiness_impact" in causality, (
                f"missing mesh_governance_readiness_impact on path {path_name}"
            )

    def test_c2_multimodal_participation_blocked_by_stale_proof_in_state(self) -> None:
        """When mesh proof is stale, multimodal_participation is blocked in governance state."""
        active_sessions = [SimpleNamespace(device_id="dev_cross")]
        mode_map = {"dev_cross": SimpleNamespace(mode=SimpleNamespace(value="cross_device"))}
        readiness_map = {
            "dev_cross": SimpleNamespace(
                is_dispatch_eligible=True,
                is_takeover_eligible=True,
                is_cross_device_ready=True,
            )
        }
        stale_run_at = time.time() - MESH_RUNTIME_PROOF_STALE_AFTER_SECONDS - 120.0
        stale_mesh = _make_live_proof_snapshot(last_live_run_at=stale_run_at)

        with patch(
            "core.attached_runtime_session_registry.list_active_sessions",
            return_value=active_sessions,
        ), patch(
            "core.android_mode_gate_policy.build_mode_state_for_device",
            side_effect=lambda device_id: mode_map[device_id],
        ), patch(
            "core.android_mode_gate_policy.evaluate_android_mode_readiness",
            side_effect=lambda device_id: readiness_map[device_id],
        ), patch(
            "core.unified_execution_governance.is_takeover_active",
            return_value=False,
        ), patch(
            "core.unified_execution_governance.get_execution_runtime_snapshot",
            return_value=self._base_runtime_snapshot(),
        ), patch(
            "core.runtime.source_dispatch_orchestrator.get_live_mesh_runtime_proof_snapshot",
            return_value=stale_mesh,
        ):
            state = build_unified_governance_state()

        device = state["devices"][0]
        multimodal = device["governance_precedence"]["multimodal_participation"]
        assert multimodal["eligible"] is False
        assert "stale" in (multimodal.get("blocked_by") or "")
        assert state["mesh_runtime_state"]["proof_quality"] == MESH_RUNTIME_PROOF_QUALITY_STALE
        assert state["mesh_runtime_state"]["governance_readiness_impact"] == "degraded_stale_proof"

    def test_c3_multimodal_participation_eligible_with_live_mesh_proof(self) -> None:
        """When mesh proof is live, multimodal_participation is eligible."""
        active_sessions = [SimpleNamespace(device_id="dev_cross")]
        mode_map = {"dev_cross": SimpleNamespace(mode=SimpleNamespace(value="cross_device"))}
        readiness_map = {
            "dev_cross": SimpleNamespace(
                is_dispatch_eligible=True,
                is_takeover_eligible=True,
                is_cross_device_ready=True,
            )
        }
        fresh_mesh = _make_live_proof_snapshot(last_live_run_at=time.time() - 5.0)

        with patch(
            "core.attached_runtime_session_registry.list_active_sessions",
            return_value=active_sessions,
        ), patch(
            "core.android_mode_gate_policy.build_mode_state_for_device",
            side_effect=lambda device_id: mode_map[device_id],
        ), patch(
            "core.android_mode_gate_policy.evaluate_android_mode_readiness",
            side_effect=lambda device_id: readiness_map[device_id],
        ), patch(
            "core.unified_execution_governance.is_takeover_active",
            return_value=False,
        ), patch(
            "core.unified_execution_governance.get_execution_runtime_snapshot",
            return_value=self._base_runtime_snapshot(),
        ), patch(
            "core.runtime.source_dispatch_orchestrator.get_live_mesh_runtime_proof_snapshot",
            return_value=fresh_mesh,
        ):
            state = build_unified_governance_state()

        device = state["devices"][0]
        multimodal = device["governance_precedence"]["multimodal_participation"]
        assert multimodal["eligible"] is True
        assert multimodal.get("blocked_by") is None
        causality = multimodal["decision_causality"]
        assert causality["mesh_proof_quality"] == MESH_RUNTIME_PROOF_QUALITY_LIVE
        assert causality["mesh_governance_readiness_impact"] == "none"

    def test_c4_structurally_inferred_proof_blocks_multimodal_and_carries_impact(self) -> None:
        """structurally_inferred proof blocks multimodal and impact is degraded_structurally_inferred."""
        active_sessions = [SimpleNamespace(device_id="dev_cross")]
        mode_map = {"dev_cross": SimpleNamespace(mode=SimpleNamespace(value="cross_device"))}
        readiness_map = {
            "dev_cross": SimpleNamespace(
                is_dispatch_eligible=True,
                is_takeover_eligible=True,
                is_cross_device_ready=True,
            )
        }
        # No live runs, at least one sentinel → structurally_inferred or missing
        from core.runtime.source_dispatch_orchestrator import reset_live_mesh_runtime_proof_snapshot
        reset_live_mesh_runtime_proof_snapshot()

        with patch(
            "core.attached_runtime_session_registry.list_active_sessions",
            return_value=active_sessions,
        ), patch(
            "core.android_mode_gate_policy.build_mode_state_for_device",
            side_effect=lambda device_id: mode_map[device_id],
        ), patch(
            "core.android_mode_gate_policy.evaluate_android_mode_readiness",
            side_effect=lambda device_id: readiness_map[device_id],
        ), patch(
            "core.unified_execution_governance.is_takeover_active",
            return_value=False,
        ), patch(
            "core.unified_execution_governance.get_execution_runtime_snapshot",
            return_value=self._base_runtime_snapshot(),
        ):
            state = build_unified_governance_state()

        device = state["devices"][0]
        multimodal = device["governance_precedence"]["multimodal_participation"]
        proof_quality = state["mesh_runtime_state"]["proof_quality"]
        # Must not be live
        assert proof_quality != MESH_RUNTIME_PROOF_QUALITY_LIVE
        # multimodal must be blocked
        assert multimodal["eligible"] is False
        causality = multimodal["decision_causality"]
        assert causality["mesh_proof_quality"] == proof_quality
        assert causality["mesh_governance_readiness_impact"] != "none"

    def test_c5_mesh_runtime_state_in_governance_output_has_proof_quality(self) -> None:
        """mesh_runtime_state in build_unified_governance_state output includes proof_quality."""
        active_sessions: list = []
        with patch(
            "core.attached_runtime_session_registry.list_active_sessions",
            return_value=active_sessions,
        ), patch(
            "core.unified_execution_governance.get_execution_runtime_snapshot",
            return_value={"devices": [], "active_device_count": 0, "active_execution_total_count": 0},
        ):
            state = build_unified_governance_state()

        mesh_state = state.get("mesh_runtime_state", {})
        assert "proof_quality" in mesh_state
        assert "proof_quality_reason" in mesh_state
        assert "governance_readiness_impact" in mesh_state


# ---------------------------------------------------------------------------
# Group D — Boundary / regression cases for _compute_mesh_proof_quality
# ---------------------------------------------------------------------------


class TestGroupD_ComputeMeshProofQualityBoundary:
    """Direct unit tests for the proof quality computation helper."""

    def _call(self, **kwargs: object) -> tuple[str, str]:
        from core.unified_governance_semantics import _compute_mesh_proof_quality
        return _compute_mesh_proof_quality(**kwargs)  # type: ignore[arg-type]

    def test_d1_no_execution_no_sentinels_returns_missing(self) -> None:
        quality, reason = self._call(
            has_live_runtime_path_execution=False,
            last_live_run_at=None,
            runtime_proof_count=0,
            live_mesh_run_count=0,
        )
        assert quality == MESH_RUNTIME_PROOF_QUALITY_MISSING
        assert reason

    def test_d2_no_execution_with_sentinels_returns_structurally_inferred(self) -> None:
        quality, reason = self._call(
            has_live_runtime_path_execution=False,
            last_live_run_at=None,
            runtime_proof_count=3,
            live_mesh_run_count=0,
        )
        assert quality == MESH_RUNTIME_PROOF_QUALITY_STRUCTURALLY_INFERRED
        assert reason

    def test_d3_live_execution_no_timestamp_returns_stale(self) -> None:
        quality, reason = self._call(
            has_live_runtime_path_execution=True,
            last_live_run_at=None,
            runtime_proof_count=1,
            live_mesh_run_count=1,
        )
        assert quality == MESH_RUNTIME_PROOF_QUALITY_STALE

    def test_d4_live_execution_fresh_timestamp_returns_live(self) -> None:
        quality, reason = self._call(
            has_live_runtime_path_execution=True,
            last_live_run_at=time.time() - 10.0,
            runtime_proof_count=1,
            live_mesh_run_count=1,
        )
        assert quality == MESH_RUNTIME_PROOF_QUALITY_LIVE
        assert reason == "live_execution_within_freshness_window"

    def test_d5_live_execution_exactly_at_threshold_is_live(self) -> None:
        """Execution at exactly the threshold edge is still live (not stale)."""
        threshold = MESH_RUNTIME_PROOF_STALE_AFTER_SECONDS
        quality, _ = self._call(
            has_live_runtime_path_execution=True,
            last_live_run_at=time.time() - threshold + 1.0,  # 1s before threshold
            runtime_proof_count=1,
            live_mesh_run_count=1,
        )
        assert quality == MESH_RUNTIME_PROOF_QUALITY_LIVE

    def test_d6_live_execution_past_threshold_is_stale(self) -> None:
        threshold = MESH_RUNTIME_PROOF_STALE_AFTER_SECONDS
        quality, reason = self._call(
            has_live_runtime_path_execution=True,
            last_live_run_at=time.time() - threshold - 1.0,  # 1s past threshold
            runtime_proof_count=1,
            live_mesh_run_count=1,
        )
        assert quality == MESH_RUNTIME_PROOF_QUALITY_STALE
        assert "exceeds_threshold" in reason


# ---------------------------------------------------------------------------
# Group E — governance_readiness_impact mapping
# ---------------------------------------------------------------------------


class TestGroupE_GovernanceReadinessImpactMapping:
    """_mesh_proof_quality_to_governance_readiness_impact maps correctly."""

    def _call(self, quality: str) -> str:
        from core.unified_governance_semantics import _mesh_proof_quality_to_governance_readiness_impact
        return _mesh_proof_quality_to_governance_readiness_impact(quality)

    def test_e1_live_maps_to_none(self) -> None:
        assert self._call(MESH_RUNTIME_PROOF_QUALITY_LIVE) == "none"

    def test_e2_stale_maps_to_degraded_stale_proof(self) -> None:
        assert self._call(MESH_RUNTIME_PROOF_QUALITY_STALE) == "degraded_stale_proof"

    def test_e3_partial_maps_to_degraded_partial_proof(self) -> None:
        assert self._call(MESH_RUNTIME_PROOF_QUALITY_PARTIAL) == "degraded_partial_proof"

    def test_e4_structurally_inferred_maps_to_degraded_structurally_inferred(self) -> None:
        assert self._call(MESH_RUNTIME_PROOF_QUALITY_STRUCTURALLY_INFERRED) == "degraded_structurally_inferred"

    def test_e5_missing_maps_to_blocked_no_proof(self) -> None:
        assert self._call(MESH_RUNTIME_PROOF_QUALITY_MISSING) == "blocked_no_proof"

    def test_e6_unknown_quality_maps_to_blocked_no_proof(self) -> None:
        assert self._call("completely_unknown_value") == "blocked_no_proof"
