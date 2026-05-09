"""tests/test_pr9_canonical_proof_input_diagnosis.py
======================================================
PR-09 Regression suite — Canonical proof-input diagnosis and observability.

Validates that governance diagnosis surfaces missing / partial / malformed /
stale / conflicting Android/runtime proof inputs as **explicit and
distinguishable** canonical explanations rather than collapsing them into
generic outcomes.

Acceptance criteria (from PR-09 problem statement):
- Canonical degraded/conflict states become materially more observable and
  diagnosable.
- Missing / partial / malformed / stale / conflicting semantics are
  distinguishable in canonical diagnostics.
- Regression tests prove explanatory causality is preserved on real canonical
  paths.

Coverage groups:
  A — classify_canonical_proof_input_diagnosis: classification cases
  B — _detect_android_semantics_conflicts: individual conflict pairs
  C — decision_causality carries proof_input_diagnosis via build_unified_governance_state
  D — boundary / edge cases (None values, empty dicts, mixed conditions)
  E — policy sentinel is present and stable
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.unified_execution_governance import (
    CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY,
    _detect_android_semantics_conflicts,
    classify_canonical_proof_input_diagnosis,
)
from core.unified_governance_semantics import (
    GovernancePath,
    build_unified_governance_state,
)

# ---------------------------------------------------------------------------
# Shared snapshot helpers
# ---------------------------------------------------------------------------

_BASE_FRESH_COMPLETE: dict = {
    "android_semantics_contract_state": "complete",
    "android_semantics_contract_complete": True,
    "android_semantics_missing_keys": [],
    "android_semantics_malformed_keys": [],
    "android_semantics_freshness_state": "fresh",
    "android_semantics_freshness_reason": "android_semantics_age_within_threshold",
    "android_runtime_truth_authority": "authoritative",
    "android_runtime_truth_usable": True,
    "android_reported_mode": "cross_device",
    "android_reported_cross_device_eligibility": True,
    "android_reported_goal_execution_eligibility": True,
    "android_reported_local_inference_available": False,
    "android_reported_local_inference_ready": False,
    "android_reported_local_intelligence_status": "unavailable",
}


def _snap(**overrides: object) -> dict:
    """Return a fresh-complete snapshot with any overrides applied."""
    result = dict(_BASE_FRESH_COMPLETE)
    result.update(overrides)
    return result


# ===========================================================================
# Group A — classify_canonical_proof_input_diagnosis: classification cases
# ===========================================================================


class TestGroupA_ClassifyProofInputDiagnosis:
    """All six proof-input classes are reachable and return the right shape."""

    def test_a1_empty_snapshot_yields_missing(self) -> None:
        """No semantics at all → class=missing."""
        result = classify_canonical_proof_input_diagnosis({})
        assert result["proof_input_class"] == "missing"
        assert result["proof_input_conflicts"] == []
        assert len(result["proof_input_degradation_causes"]) >= 1
        assert "_policy" in result

    def test_a2_contract_state_missing_explicit(self) -> None:
        """Explicit contract_state=missing → class=missing."""
        result = classify_canonical_proof_input_diagnosis(
            {"android_semantics_contract_state": "missing"}
        )
        assert result["proof_input_class"] == "missing"

    def test_a3_partial_missing_keys(self) -> None:
        """Missing required keys → class=partial."""
        result = classify_canonical_proof_input_diagnosis(
            _snap(
                android_semantics_contract_state="partial",
                android_semantics_missing_keys=["mode_state", "cross_device_eligibility"],
            )
        )
        assert result["proof_input_class"] == "partial"
        assert result["proof_input_conflicts"] == []
        causes = result["proof_input_degradation_causes"]
        assert any("missing_canonical_gate_metadata_keys" in c for c in causes)

    def test_a4_malformed_keys_present(self) -> None:
        """Malformed required keys → class=malformed."""
        result = classify_canonical_proof_input_diagnosis(
            _snap(
                android_semantics_contract_state="malformed",
                android_semantics_malformed_keys=["mode_state"],
            )
        )
        assert result["proof_input_class"] == "malformed"
        causes = result["proof_input_degradation_causes"]
        assert any("malformed_canonical_gate_metadata_keys" in c for c in causes)

    def test_a5_stale_freshness_state(self) -> None:
        """Semantics older than threshold → class=stale."""
        result = classify_canonical_proof_input_diagnosis(
            _snap(
                android_semantics_freshness_state="stale",
                android_semantics_freshness_reason="android_semantics_age_exceeds_threshold",
                android_runtime_truth_authority="downgraded_to_unknown",
            )
        )
        assert result["proof_input_class"] == "stale"
        causes = result["proof_input_degradation_causes"]
        assert any("android_semantics_stale" in c for c in causes)

    def test_a6_authority_downgraded_yields_stale_even_if_freshness_state_unknown(self) -> None:
        """Authority downgraded → class=stale regardless of freshness_state."""
        result = classify_canonical_proof_input_diagnosis(
            _snap(
                android_semantics_freshness_state="unknown",
                android_runtime_truth_authority="downgraded_to_unknown",
            )
        )
        assert result["proof_input_class"] == "stale"

    def test_a7_conflicting_mode_and_eligibility(self) -> None:
        """mode=cross_device + cross_device_eligibility=False → class=conflicting."""
        result = classify_canonical_proof_input_diagnosis(
            _snap(
                android_reported_mode="cross_device",
                android_reported_cross_device_eligibility=False,
            )
        )
        assert result["proof_input_class"] == "conflicting"
        assert len(result["proof_input_conflicts"]) >= 1
        assert any(
            "mode_cross_device_conflicts_with_cross_device_eligibility_false" in c
            for c in result["proof_input_conflicts"]
        )

    def test_a8_complete_and_conflict_free(self) -> None:
        """All keys present, fresh, no conflicts → class=complete."""
        result = classify_canonical_proof_input_diagnosis(_BASE_FRESH_COMPLETE)
        assert result["proof_input_class"] == "complete"
        assert result["proof_input_conflicts"] == []
        assert result["proof_input_degradation_causes"] == []

    def test_a9_all_six_classes_are_distinguishable(self) -> None:
        """Each class must be a distinct, non-overlapping string value."""
        missing = classify_canonical_proof_input_diagnosis({})
        partial = classify_canonical_proof_input_diagnosis(
            _snap(
                android_semantics_contract_state="partial",
                android_semantics_missing_keys=["mode_state"],
            )
        )
        malformed = classify_canonical_proof_input_diagnosis(
            _snap(
                android_semantics_contract_state="malformed",
                android_semantics_malformed_keys=["mode_state"],
            )
        )
        stale = classify_canonical_proof_input_diagnosis(
            _snap(
                android_semantics_freshness_state="stale",
                android_runtime_truth_authority="downgraded_to_unknown",
            )
        )
        conflicting = classify_canonical_proof_input_diagnosis(
            _snap(
                android_reported_mode="cross_device",
                android_reported_cross_device_eligibility=False,
            )
        )
        complete = classify_canonical_proof_input_diagnosis(_BASE_FRESH_COMPLETE)

        classes = {
            missing["proof_input_class"],
            partial["proof_input_class"],
            malformed["proof_input_class"],
            stale["proof_input_class"],
            conflicting["proof_input_class"],
            complete["proof_input_class"],
        }
        assert len(classes) == 6, f"Expected 6 distinct classes, got: {classes}"

    def test_a10_conflict_takes_priority_over_malformed(self) -> None:
        """Conflicting fields take priority over malformed keys in classification."""
        result = classify_canonical_proof_input_diagnosis(
            _snap(
                android_semantics_contract_state="malformed",
                android_semantics_malformed_keys=["mode_state"],
                android_reported_mode="cross_device",
                android_reported_cross_device_eligibility=False,
            )
        )
        assert result["proof_input_class"] == "conflicting"

    def test_a11_malformed_takes_priority_over_stale(self) -> None:
        """Malformed keys take priority over stale in classification."""
        result = classify_canonical_proof_input_diagnosis(
            _snap(
                android_semantics_contract_state="malformed",
                android_semantics_malformed_keys=["mode_state"],
                android_semantics_freshness_state="stale",
                android_runtime_truth_authority="downgraded_to_unknown",
            )
        )
        assert result["proof_input_class"] == "malformed"

    def test_a12_stale_takes_priority_over_partial(self) -> None:
        """Stale takes priority over partial in classification."""
        result = classify_canonical_proof_input_diagnosis(
            _snap(
                android_semantics_contract_state="partial",
                android_semantics_missing_keys=["mode_state"],
                android_semantics_freshness_state="stale",
                android_runtime_truth_authority="downgraded_to_unknown",
            )
        )
        assert result["proof_input_class"] == "stale"


# ===========================================================================
# Group B — _detect_android_semantics_conflicts: individual conflict pairs
# ===========================================================================


class TestGroupB_DetectAndroidSemanticsConflicts:
    """Each known semantic conflict pair is individually detectable."""

    def test_b1_mode_cross_device_with_eligibility_false(self) -> None:
        """mode=cross_device + cross_device_eligibility=False is flagged."""
        conflicts = _detect_android_semantics_conflicts(
            {
                "android_reported_mode": "cross_device",
                "android_reported_cross_device_eligibility": False,
            }
        )
        assert "mode_cross_device_conflicts_with_cross_device_eligibility_false" in conflicts

    def test_b2_mode_cross_device_with_eligibility_true_is_not_flagged(self) -> None:
        """mode=cross_device + eligibility=True is not a conflict."""
        conflicts = _detect_android_semantics_conflicts(
            {
                "android_reported_mode": "cross_device",
                "android_reported_cross_device_eligibility": True,
            }
        )
        assert not any("mode_cross_device" in c for c in conflicts)

    def test_b3_goal_eligibility_true_without_cross_device_eligibility(self) -> None:
        """goal_execution_eligibility=True + cross_device_eligibility=False is flagged."""
        conflicts = _detect_android_semantics_conflicts(
            {
                "android_reported_goal_execution_eligibility": True,
                "android_reported_cross_device_eligibility": False,
            }
        )
        assert "goal_execution_eligibility_true_conflicts_with_cross_device_eligibility_false" in conflicts

    def test_b4_goal_eligibility_true_with_cross_device_eligibility_true_no_conflict(self) -> None:
        """goal_execution_eligibility=True + cross_device_eligibility=True is fine."""
        conflicts = _detect_android_semantics_conflicts(
            {
                "android_reported_goal_execution_eligibility": True,
                "android_reported_cross_device_eligibility": True,
            }
        )
        assert not any("goal_execution_eligibility" in c for c in conflicts)

    def test_b5_local_inference_available_true_with_status_disabled(self) -> None:
        """local_inference_available=True + local_intelligence_status=disabled is flagged."""
        conflicts = _detect_android_semantics_conflicts(
            {
                "android_reported_local_inference_available": True,
                "android_reported_local_intelligence_status": "disabled",
            }
        )
        assert any("local_inference_available_true_conflicts_with_local_intelligence_status" in c for c in conflicts)

    def test_b6_local_inference_available_true_with_status_unavailable(self) -> None:
        """local_inference_available=True + local_intelligence_status=unavailable is flagged."""
        conflicts = _detect_android_semantics_conflicts(
            {
                "android_reported_local_inference_available": True,
                "android_reported_local_intelligence_status": "unavailable",
            }
        )
        assert any("local_inference_available_true_conflicts_with_local_intelligence_status" in c for c in conflicts)

    def test_b7_local_inference_available_true_with_status_enabled_no_conflict(self) -> None:
        """local_inference_available=True + status=enabled is not a conflict."""
        conflicts = _detect_android_semantics_conflicts(
            {
                "android_reported_local_inference_available": True,
                "android_reported_local_intelligence_status": "enabled",
            }
        )
        assert not any("local_inference_available_true_conflicts" in c for c in conflicts)

    def test_b8_inference_ready_true_but_available_false(self) -> None:
        """local_inference_ready=True + local_inference_available=False is flagged."""
        conflicts = _detect_android_semantics_conflicts(
            {
                "android_reported_local_inference_ready": True,
                "android_reported_local_inference_available": False,
            }
        )
        assert "local_inference_ready_true_conflicts_with_local_inference_available_false" in conflicts

    def test_b9_no_fields_no_conflicts(self) -> None:
        """Empty snapshot yields no conflicts."""
        assert _detect_android_semantics_conflicts({}) == []

    def test_b10_multiple_conflicts_in_one_snapshot(self) -> None:
        """A snapshot with multiple conflicting pairs reports all of them."""
        conflicts = _detect_android_semantics_conflicts(
            {
                "android_reported_mode": "cross_device",
                "android_reported_cross_device_eligibility": False,
                "android_reported_goal_execution_eligibility": True,
                "android_reported_local_inference_available": True,
                "android_reported_local_intelligence_status": "disabled",
            }
        )
        assert len(conflicts) >= 3
        assert "mode_cross_device_conflicts_with_cross_device_eligibility_false" in conflicts
        assert "goal_execution_eligibility_true_conflicts_with_cross_device_eligibility_false" in conflicts
        assert any("local_inference_available_true_conflicts" in c for c in conflicts)

    def test_b11_local_mode_does_not_conflict_with_cross_device_fields(self) -> None:
        """mode=local with cross_device_eligibility=False is not a conflict."""
        conflicts = _detect_android_semantics_conflicts(
            {
                "android_reported_mode": "local",
                "android_reported_cross_device_eligibility": False,
            }
        )
        assert not any("mode_cross_device" in c for c in conflicts)


# ===========================================================================
# Group C — decision_causality carries proof_input_diagnosis
# ===========================================================================


def _make_session(device_id: str) -> SimpleNamespace:
    return SimpleNamespace(device_id=device_id)


def _make_mode_state(mode: str) -> SimpleNamespace:
    return SimpleNamespace(mode=mode)


def _make_readiness(
    *,
    is_dispatch_eligible: bool = True,
    is_takeover_eligible: bool = False,
    is_cross_device_ready: bool = True,
    blocking_gates: list | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        is_dispatch_eligible=is_dispatch_eligible,
        is_takeover_eligible=is_takeover_eligible,
        is_cross_device_ready=is_cross_device_ready,
        blocking_gates=blocking_gates or [],
    )


def _build_runtime_snapshot(device_id: str, runtime_pressure: dict) -> dict:
    return {
        "devices": [
            {
                "device_id": device_id,
                **runtime_pressure,
            }
        ],
        "active_device_count": 0,
        "active_execution_total_count": 0,
    }


class TestGroupC_DecisionCausalityCarriesProofInputDiagnosis:
    """decision_causality must contain proof_input_diagnosis for all paths."""

    def _run_governance_state(
        self,
        device_id: str,
        runtime_pressure: dict,
        *,
        mode: str = "cross_device",
        dispatch_eligible: bool = True,
        cross_device_ready: bool = True,
    ) -> dict:
        active_sessions = [_make_session(device_id)]
        mode_state = _make_mode_state(mode)
        readiness = _make_readiness(
            is_dispatch_eligible=dispatch_eligible,
            is_cross_device_ready=cross_device_ready,
        )
        runtime_snapshot = _build_runtime_snapshot(device_id, runtime_pressure)

        with (
            patch(
                "core.attached_runtime_session_registry.list_active_sessions",
                return_value=active_sessions,
            ),
            patch(
                "core.android_mode_gate_policy.build_mode_state_for_device",
                return_value=mode_state,
            ),
            patch(
                "core.android_mode_gate_policy.evaluate_android_mode_readiness",
                return_value=readiness,
            ),
            patch(
                "core.unified_execution_governance.is_takeover_active",
                return_value=False,
            ),
            patch(
                "core.unified_execution_governance.get_execution_runtime_snapshot",
                return_value=runtime_snapshot,
            ),
        ):
            return build_unified_governance_state([device_id])

    def test_c1_missing_semantics_surfaced_in_causality(self) -> None:
        """Missing Android semantics → proof_input_diagnosis.proof_input_class=missing."""
        state = self._run_governance_state(
            "device-c1",
            {
                "android_semantics_contract_state": "missing",
                "android_semantics_missing_keys": [],
                "android_semantics_malformed_keys": [],
                "android_semantics_freshness_state": "unknown",
                "android_runtime_truth_authority": "unknown",
                "android_reported_mode": None,
                "android_reported_cross_device_eligibility": None,
                "android_reported_goal_execution_eligibility": None,
                "android_reported_local_inference_available": None,
                "android_reported_local_inference_ready": None,
                "android_reported_local_intelligence_status": None,
            },
        )
        device = state["devices"][0]
        for path_name in [p.value for p in GovernancePath]:
            causality = device["governance_precedence"][path_name]["decision_causality"]
            diag = causality["proof_input_diagnosis"]
            assert diag["proof_input_class"] == "missing", (
                f"path={path_name}: expected missing, got {diag['proof_input_class']}"
            )

    def test_c2_partial_semantics_surfaced_in_causality(self) -> None:
        """Partial semantics → proof_input_diagnosis.proof_input_class=partial."""
        state = self._run_governance_state(
            "device-c2",
            {
                "android_semantics_contract_state": "partial",
                "android_semantics_missing_keys": ["mode_state", "cross_device_eligibility"],
                "android_semantics_malformed_keys": [],
                "android_semantics_freshness_state": "fresh",
                "android_runtime_truth_authority": "authoritative",
                "android_reported_mode": None,
                "android_reported_cross_device_eligibility": None,
                "android_reported_goal_execution_eligibility": True,
                "android_reported_local_inference_available": False,
                "android_reported_local_inference_ready": False,
                "android_reported_local_intelligence_status": None,
            },
        )
        device = state["devices"][0]
        for path_name in [p.value for p in GovernancePath]:
            causality = device["governance_precedence"][path_name]["decision_causality"]
            diag = causality["proof_input_diagnosis"]
            assert diag["proof_input_class"] == "partial", (
                f"path={path_name}: expected partial, got {diag['proof_input_class']}"
            )

    def test_c3_malformed_semantics_surfaced_in_causality(self) -> None:
        """Malformed keys → proof_input_diagnosis.proof_input_class=malformed."""
        state = self._run_governance_state(
            "device-c3",
            {
                "android_semantics_contract_state": "malformed",
                "android_semantics_missing_keys": [],
                "android_semantics_malformed_keys": ["mode_state"],
                "android_semantics_freshness_state": "fresh",
                "android_runtime_truth_authority": "authoritative",
                "android_reported_mode": None,
                "android_reported_cross_device_eligibility": None,
                "android_reported_goal_execution_eligibility": None,
                "android_reported_local_inference_available": None,
                "android_reported_local_inference_ready": None,
                "android_reported_local_intelligence_status": None,
            },
        )
        device = state["devices"][0]
        for path_name in [p.value for p in GovernancePath]:
            causality = device["governance_precedence"][path_name]["decision_causality"]
            diag = causality["proof_input_diagnosis"]
            assert diag["proof_input_class"] == "malformed", (
                f"path={path_name}: expected malformed, got {diag['proof_input_class']}"
            )

    def test_c4_stale_semantics_surfaced_in_causality(self) -> None:
        """Stale semantics → proof_input_diagnosis.proof_input_class=stale."""
        state = self._run_governance_state(
            "device-c4",
            {
                "android_semantics_contract_state": "complete",
                "android_semantics_missing_keys": [],
                "android_semantics_malformed_keys": [],
                "android_semantics_freshness_state": "stale",
                "android_semantics_freshness_reason": "android_semantics_age_exceeds_threshold",
                "android_runtime_truth_authority": "downgraded_to_unknown",
                "android_reported_mode": None,
                "android_reported_cross_device_eligibility": None,
                "android_reported_goal_execution_eligibility": None,
                "android_reported_local_inference_available": None,
                "android_reported_local_inference_ready": None,
                "android_reported_local_intelligence_status": None,
            },
        )
        device = state["devices"][0]
        for path_name in [p.value for p in GovernancePath]:
            causality = device["governance_precedence"][path_name]["decision_causality"]
            diag = causality["proof_input_diagnosis"]
            assert diag["proof_input_class"] == "stale", (
                f"path={path_name}: expected stale, got {diag['proof_input_class']}"
            )

    def test_c5_conflicting_semantics_surfaced_in_causality(self) -> None:
        """Semantic conflicts → proof_input_diagnosis.proof_input_class=conflicting."""
        state = self._run_governance_state(
            "device-c5",
            {
                "android_semantics_contract_state": "complete",
                "android_semantics_missing_keys": [],
                "android_semantics_malformed_keys": [],
                "android_semantics_freshness_state": "fresh",
                "android_runtime_truth_authority": "authoritative",
                "android_reported_mode": "cross_device",
                "android_reported_cross_device_eligibility": False,
                "android_reported_goal_execution_eligibility": None,
                "android_reported_local_inference_available": None,
                "android_reported_local_inference_ready": None,
                "android_reported_local_intelligence_status": None,
            },
        )
        device = state["devices"][0]
        for path_name in [p.value for p in GovernancePath]:
            causality = device["governance_precedence"][path_name]["decision_causality"]
            diag = causality["proof_input_diagnosis"]
            assert diag["proof_input_class"] == "conflicting", (
                f"path={path_name}: expected conflicting, got {diag['proof_input_class']}"
            )
            assert len(diag["proof_input_conflicts"]) >= 1

    def test_c6_complete_semantics_surfaced_in_causality(self) -> None:
        """Complete fresh semantics → proof_input_diagnosis.proof_input_class=complete."""
        state = self._run_governance_state(
            "device-c6",
            {
                "android_semantics_contract_state": "complete",
                "android_semantics_missing_keys": [],
                "android_semantics_malformed_keys": [],
                "android_semantics_freshness_state": "fresh",
                "android_semantics_freshness_reason": "android_semantics_age_within_threshold",
                "android_runtime_truth_authority": "authoritative",
                "android_reported_mode": "cross_device",
                "android_reported_cross_device_eligibility": True,
                "android_reported_goal_execution_eligibility": True,
                "android_reported_local_inference_available": False,
                "android_reported_local_inference_ready": False,
                "android_reported_local_intelligence_status": "unavailable",
            },
        )
        device = state["devices"][0]
        for path_name in [p.value for p in GovernancePath]:
            causality = device["governance_precedence"][path_name]["decision_causality"]
            diag = causality["proof_input_diagnosis"]
            assert diag["proof_input_class"] == "complete", (
                f"path={path_name}: expected complete, got {diag['proof_input_class']}"
            )

    def test_c7_proof_input_diagnosis_dict_has_required_keys(self) -> None:
        """proof_input_diagnosis always has the required structural keys."""
        state = self._run_governance_state(
            "device-c7",
            {
                "android_semantics_contract_state": "missing",
                "android_semantics_missing_keys": [],
                "android_semantics_malformed_keys": [],
                "android_semantics_freshness_state": "unknown",
                "android_runtime_truth_authority": "unknown",
                "android_reported_mode": None,
                "android_reported_cross_device_eligibility": None,
                "android_reported_goal_execution_eligibility": None,
                "android_reported_local_inference_available": None,
                "android_reported_local_inference_ready": None,
                "android_reported_local_intelligence_status": None,
            },
        )
        device = state["devices"][0]
        any_path = list(device["governance_precedence"].values())[0]
        diag = any_path["decision_causality"]["proof_input_diagnosis"]
        assert "proof_input_class" in diag
        assert "proof_input_detail" in diag
        assert "proof_input_conflicts" in diag
        assert "proof_input_degradation_causes" in diag
        assert "_policy" in diag
        assert isinstance(diag["proof_input_conflicts"], list)
        assert isinstance(diag["proof_input_degradation_causes"], list)
        assert isinstance(diag["proof_input_detail"], str)


# ===========================================================================
# Group D — boundary / edge cases
# ===========================================================================


class TestGroupD_BoundaryEdgeCases:
    """classify_canonical_proof_input_diagnosis handles degenerate inputs safely."""

    def test_d1_all_none_values(self) -> None:
        """All-None snapshot does not raise and returns a valid class."""
        snapshot = {k: None for k in _BASE_FRESH_COMPLETE}
        result = classify_canonical_proof_input_diagnosis(snapshot)
        assert result["proof_input_class"] in {
            "complete", "stale", "conflicting", "malformed", "partial", "missing"
        }

    def test_d2_malformed_keys_empty_list_with_malformed_state(self) -> None:
        """contract_state=malformed with empty malformed_keys list still yields malformed."""
        result = classify_canonical_proof_input_diagnosis(
            _snap(
                android_semantics_contract_state="malformed",
                android_semantics_malformed_keys=[],
            )
        )
        assert result["proof_input_class"] == "malformed"

    def test_d3_conflicting_with_goal_and_cross_device_eligibility(self) -> None:
        """goal_execution_eligibility=True + cross_device_eligibility=False is conflicting."""
        result = classify_canonical_proof_input_diagnosis(
            _snap(
                android_reported_mode="cross_device",
                android_reported_cross_device_eligibility=False,
                android_reported_goal_execution_eligibility=True,
            )
        )
        assert result["proof_input_class"] == "conflicting"
        assert "goal_execution_eligibility_true_conflicts_with_cross_device_eligibility_false" in result["proof_input_conflicts"]

    def test_d4_inference_ready_true_but_available_false_is_conflicting(self) -> None:
        """local_inference_ready=True + local_inference_available=False is conflicting."""
        result = classify_canonical_proof_input_diagnosis(
            _snap(
                android_reported_mode="cross_device",
                android_reported_cross_device_eligibility=True,
                android_reported_local_inference_ready=True,
                android_reported_local_inference_available=False,
                android_reported_local_intelligence_status="ready",
            )
        )
        assert result["proof_input_class"] == "conflicting"
        assert "local_inference_ready_true_conflicts_with_local_inference_available_false" in result["proof_input_conflicts"]

    def test_d5_freshness_reason_is_preserved_in_stale_detail(self) -> None:
        """Stale diagnosis detail contains the freshness_reason string."""
        reason = "android_semantics_age_exceeds_threshold"
        result = classify_canonical_proof_input_diagnosis(
            _snap(
                android_semantics_freshness_state="stale",
                android_semantics_freshness_reason=reason,
                android_runtime_truth_authority="downgraded_to_unknown",
            )
        )
        assert result["proof_input_class"] == "stale"
        # degradation_causes should embed the reason
        causes_str = " ".join(result["proof_input_degradation_causes"])
        assert reason in causes_str

    def test_d6_missing_keys_are_named_in_partial_detail(self) -> None:
        """Partial diagnosis names the missing keys in detail / causes."""
        missing_keys = ["mode_state", "cross_device_eligibility"]
        result = classify_canonical_proof_input_diagnosis(
            _snap(
                android_semantics_contract_state="partial",
                android_semantics_missing_keys=missing_keys,
            )
        )
        assert result["proof_input_class"] == "partial"
        detail = result["proof_input_detail"]
        assert "mode_state" in detail or any("mode_state" in c for c in result["proof_input_degradation_causes"])

    def test_d7_policy_sentinel_is_always_present(self) -> None:
        """_policy is always set to the canonical policy sentinel."""
        for snap in [
            {},
            _snap(android_semantics_contract_state="missing"),
            _snap(
                android_semantics_contract_state="partial",
                android_semantics_missing_keys=["mode_state"],
            ),
            _BASE_FRESH_COMPLETE,
        ]:
            result = classify_canonical_proof_input_diagnosis(snap)
            assert result["_policy"] == CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY


# ===========================================================================
# Group E — policy sentinel
# ===========================================================================


class TestGroupE_PolicySentinel:
    """CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY sentinel is stable and importable."""

    def test_e1_sentinel_is_importable_from_unified_execution_governance(self) -> None:
        from core.unified_execution_governance import CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY as p
        assert isinstance(p, str)
        assert "CANONICAL_PROOF_INPUT_DIAGNOSIS" in p

    def test_e2_sentinel_is_re_exported_from_unified_governance_semantics(self) -> None:
        from core.unified_governance_semantics import CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY as p
        assert isinstance(p, str)
        assert "CANONICAL_PROOF_INPUT_DIAGNOSIS" in p

    def test_e3_classify_is_re_exported_from_unified_governance_semantics(self) -> None:
        from core.unified_governance_semantics import classify_canonical_proof_input_diagnosis as fn
        result = fn({})
        assert result["proof_input_class"] == "missing"
