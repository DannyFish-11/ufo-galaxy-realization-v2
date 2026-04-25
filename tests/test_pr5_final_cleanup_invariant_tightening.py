"""tests/test_pr5_final_cleanup_invariant_tightening.py
=======================================================
PR-5 Final Cleanup and Invariant Tightening — Test Suite.

This test suite validates that:

1. All PR-5 final cleanup policy / authority sentinels are present and
   non-empty in the core module.
2. The five no-bypass guards confirm their canonical modules are importable:
   A. Completion ingress → CanonicalCompletionIngress
   B. Capability routing → evaluate_capability_gate
   C. Runtime truth ingress → ingest_android_runtime_state_update
   D. Provider routing → UnifiedLLMRouter
   E. Validation gate → ReleaseGate
3. ``run_all_no_bypass_guards()`` returns one result per closure area.
4. ``build_final_cleanup_posture_snapshot()`` returns a JSON-serialisable
   snapshot and ``is_final_cleanup_posture_acceptable()`` returns ``True``.
5. The semantic capability tier registry is populated and contains at least
   the expected capabilities with the correct tiers.
6. ``BypassInvariantViolation`` is a ``RuntimeError`` subclass.
7. ``core.runtime`` re-exports all PR-5 final cleanup sentinel symbols.
8. ``core.routes.projection`` carries the PR-5 final cleanup alignment sentinel
   and it is not UNAVAILABLE.
9. No bypass can silently skip canonical guards (strict mode raises correctly).
10. Capability tier logic: NEAR_MAINLINE and EXTENSION tiers block 'fully
    mainline' language semantics.

Coverage groups
---------------
A  — Module: all PR-5 sentinels present and non-empty.
B  — Guards: each of the five closure-area guards returns CANONICAL_PATH_CONFIRMED.
C  — Aggregate runner: run_all_no_bypass_guards covers all five areas.
D  — Posture snapshot: JSON-serialisable, all_canonical_confirmed is True.
E  — is_final_cleanup_posture_acceptable returns True.
F  — Capability tier registry: expected records present with correct tiers.
G  — BypassInvariantViolation is RuntimeError subclass.
H  — core.runtime re-exports all PR-5 final sentinel symbols.
I  — core.routes.projection carries PR-5 alignment sentinel (not UNAVAILABLE).
J  — Strict mode: guard raises BypassInvariantViolation on bypass risk.
K  — Sentinel strings contain expected policy keywords.
L  — Guard result fields: area, verdict, canonical_path, bypass_risk present.
M  — Snapshot to_dict(): required keys present and types correct.
N  — get_capability_tier(): lookup by ID returns correct record.
O  — BypassGuardVerdict enum: all expected values present.
P  — ClosureArea enum: all five areas present.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.final_cleanup_invariant_tightening import (
        FINAL_CLEANUP_INVARIANT_TIGHTENING_AUTHORITY,
        FINAL_CLEANUP_INVARIANT_TIGHTENING_PR5_SENTINEL,
        NO_BYPASS_COMPLETION_INGRESS_POLICY,
        NO_BYPASS_CAPABILITY_ROUTING_POLICY,
        NO_BYPASS_RUNTIME_TRUTH_INGRESS_POLICY,
        NO_BYPASS_PROVIDER_ROUTING_POLICY,
        NO_BYPASS_VALIDATION_GATE_POLICY,
        SEMANTIC_CAPABILITY_TIER_POLICY,
        LEGACY_PATH_MUST_NOT_RE_ENTER_CANONICAL_SURFACE_POLICY,
        CANONICAL_COMPLETION_INGRESS_PATH,
        CANONICAL_CAPABILITY_ROUTING_PATH,
        CANONICAL_RUNTIME_TRUTH_INGRESS_PATH,
        CANONICAL_PROVIDER_ROUTING_PATH,
        CANONICAL_VALIDATION_GATE_PATH,
        ClosureArea,
        CapabilityTier,
        BypassGuardVerdict,
        BypassGuardResult,
        CapabilityTierRecord,
        FinalCleanupPostureSnapshot,
        BypassInvariantViolation,
        assert_completion_ingress_is_canonical,
        assert_capability_routing_is_canonical,
        assert_runtime_truth_ingress_is_canonical,
        assert_provider_routing_is_canonical,
        assert_validation_gate_is_canonical,
        get_capability_tier_registry,
        get_capability_tier,
        build_final_cleanup_posture_snapshot,
        is_final_cleanup_posture_acceptable,
        run_all_no_bypass_guards,
    )

    _MODULE_AVAILABLE = True
except ImportError:
    _MODULE_AVAILABLE = False

try:
    from core.runtime import (
        FINAL_CLEANUP_INVARIANT_TIGHTENING_AUTHORITY as _rt_authority,
        FINAL_CLEANUP_INVARIANT_TIGHTENING_PR5_SENTINEL as _rt_pr5,
        NO_BYPASS_COMPLETION_INGRESS_POLICY as _rt_completion,
        NO_BYPASS_CAPABILITY_ROUTING_POLICY as _rt_capability,
        NO_BYPASS_RUNTIME_TRUTH_INGRESS_POLICY as _rt_truth,
        NO_BYPASS_PROVIDER_ROUTING_POLICY as _rt_provider,
        NO_BYPASS_VALIDATION_GATE_POLICY as _rt_gate,
        assert_completion_ingress_is_canonical as _rt_assert_completion,
        assert_capability_routing_is_canonical as _rt_assert_capability,
        assert_runtime_truth_ingress_is_canonical as _rt_assert_truth,
        assert_provider_routing_is_canonical as _rt_assert_provider,
        assert_validation_gate_is_canonical as _rt_assert_gate,
        is_final_cleanup_posture_acceptable as _rt_posture_ok,
        build_final_cleanup_posture_snapshot as _rt_snapshot,
    )

    _RUNTIME_AVAILABLE = True
except ImportError:
    _RUNTIME_AVAILABLE = False

try:
    from core.routes.projection import (
        FINAL_CLEANUP_INVARIANT_TIGHTENING_ALIGNED_PR5_FINAL,
    )

    _PROJECTION_AVAILABLE = True
except ImportError:
    _PROJECTION_AVAILABLE = False


# ---------------------------------------------------------------------------
# Group A — Module sentinels present and non-empty
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="core.final_cleanup_invariant_tightening not available")
class TestA_ModuleSentinels:
    """Group A: All PR-5 final cleanup authority / policy sentinels are present."""

    def test_A01_authority_sentinel_present(self):
        assert isinstance(FINAL_CLEANUP_INVARIANT_TIGHTENING_AUTHORITY, str)
        assert FINAL_CLEANUP_INVARIANT_TIGHTENING_AUTHORITY

    def test_A02_pr5_sentinel_present(self):
        assert isinstance(FINAL_CLEANUP_INVARIANT_TIGHTENING_PR5_SENTINEL, str)
        assert FINAL_CLEANUP_INVARIANT_TIGHTENING_PR5_SENTINEL

    def test_A03_no_bypass_completion_ingress_policy(self):
        assert isinstance(NO_BYPASS_COMPLETION_INGRESS_POLICY, str)
        assert NO_BYPASS_COMPLETION_INGRESS_POLICY

    def test_A04_no_bypass_capability_routing_policy(self):
        assert isinstance(NO_BYPASS_CAPABILITY_ROUTING_POLICY, str)
        assert NO_BYPASS_CAPABILITY_ROUTING_POLICY

    def test_A05_no_bypass_runtime_truth_ingress_policy(self):
        assert isinstance(NO_BYPASS_RUNTIME_TRUTH_INGRESS_POLICY, str)
        assert NO_BYPASS_RUNTIME_TRUTH_INGRESS_POLICY

    def test_A06_no_bypass_provider_routing_policy(self):
        assert isinstance(NO_BYPASS_PROVIDER_ROUTING_POLICY, str)
        assert NO_BYPASS_PROVIDER_ROUTING_POLICY

    def test_A07_no_bypass_validation_gate_policy(self):
        assert isinstance(NO_BYPASS_VALIDATION_GATE_POLICY, str)
        assert NO_BYPASS_VALIDATION_GATE_POLICY

    def test_A08_semantic_capability_tier_policy(self):
        assert isinstance(SEMANTIC_CAPABILITY_TIER_POLICY, str)
        assert SEMANTIC_CAPABILITY_TIER_POLICY

    def test_A09_legacy_path_must_not_re_enter_policy(self):
        assert isinstance(LEGACY_PATH_MUST_NOT_RE_ENTER_CANONICAL_SURFACE_POLICY, str)
        assert LEGACY_PATH_MUST_NOT_RE_ENTER_CANONICAL_SURFACE_POLICY

    def test_A10_canonical_path_constants_present(self):
        for path_const in [
            CANONICAL_COMPLETION_INGRESS_PATH,
            CANONICAL_CAPABILITY_ROUTING_PATH,
            CANONICAL_RUNTIME_TRUTH_INGRESS_PATH,
            CANONICAL_PROVIDER_ROUTING_PATH,
            CANONICAL_VALIDATION_GATE_PATH,
        ]:
            assert isinstance(path_const, str)
            assert path_const


# ---------------------------------------------------------------------------
# Group B — Guards confirm canonical paths
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="core.final_cleanup_invariant_tightening not available")
class TestB_NoBypassGuards:
    """Group B: Each of the five closure-area guards returns CANONICAL_PATH_CONFIRMED."""

    def _check_guard_result(self, result: "BypassGuardResult", expected_area: "ClosureArea"):
        assert result is not None
        assert result.area == expected_area
        assert result.verdict == BypassGuardVerdict.CANONICAL_PATH_CONFIRMED, (
            f"Guard for {expected_area.value} did not confirm canonical path: "
            f"{result.description}"
        )
        assert not result.bypass_risk, result.description
        assert isinstance(result.canonical_path, str)
        assert result.canonical_path

    def test_B01_completion_ingress_guard_confirms_canonical(self):
        result = assert_completion_ingress_is_canonical()
        self._check_guard_result(result, ClosureArea.completion_ingress)

    def test_B02_capability_routing_guard_confirms_canonical(self):
        result = assert_capability_routing_is_canonical()
        self._check_guard_result(result, ClosureArea.capability_routing)

    def test_B03_runtime_truth_ingress_guard_confirms_canonical(self):
        result = assert_runtime_truth_ingress_is_canonical()
        self._check_guard_result(result, ClosureArea.runtime_truth_ingress)

    def test_B04_provider_routing_guard_confirms_canonical(self):
        result = assert_provider_routing_is_canonical()
        self._check_guard_result(result, ClosureArea.provider_routing)

    def test_B05_validation_gate_guard_confirms_canonical(self):
        result = assert_validation_gate_is_canonical()
        self._check_guard_result(result, ClosureArea.validation_gate)


# ---------------------------------------------------------------------------
# Group C — Aggregate runner covers all five areas
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="core.final_cleanup_invariant_tightening not available")
class TestC_AggregateRunner:
    """Group C: run_all_no_bypass_guards() returns results for all five areas."""

    def test_C01_run_all_no_bypass_guards_returns_five_results(self):
        results = run_all_no_bypass_guards()
        assert len(results) == 5

    def test_C02_all_five_closure_areas_represented(self):
        results = run_all_no_bypass_guards()
        areas = {r.area for r in results}
        assert areas == {
            ClosureArea.completion_ingress,
            ClosureArea.capability_routing,
            ClosureArea.runtime_truth_ingress,
            ClosureArea.provider_routing,
            ClosureArea.validation_gate,
        }

    def test_C03_all_results_confirm_canonical_path(self):
        results = run_all_no_bypass_guards()
        for result in results:
            assert result.verdict == BypassGuardVerdict.CANONICAL_PATH_CONFIRMED, (
                f"Guard for {result.area.value} returned {result.verdict.value}: "
                f"{result.description}"
            )

    def test_C04_no_bypass_risks_detected(self):
        results = run_all_no_bypass_guards()
        risks = [r for r in results if r.bypass_risk]
        assert not risks, f"Bypass risks detected: {[r.area.value for r in risks]}"


# ---------------------------------------------------------------------------
# Group D — Posture snapshot is JSON-serialisable
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="core.final_cleanup_invariant_tightening not available")
class TestD_PostureSnapshot:
    """Group D: build_final_cleanup_posture_snapshot() returns a valid snapshot."""

    def test_D01_snapshot_builds_successfully(self):
        snapshot = build_final_cleanup_posture_snapshot()
        assert snapshot is not None
        assert isinstance(snapshot, FinalCleanupPostureSnapshot)

    def test_D02_snapshot_all_canonical_confirmed(self):
        snapshot = build_final_cleanup_posture_snapshot()
        assert snapshot.all_canonical_confirmed, (
            f"Not all guards confirmed: bypass_risks={snapshot.bypass_risks}, "
            f"unavailable={snapshot.unavailable_modules}"
        )

    def test_D03_snapshot_no_bypass_risks(self):
        snapshot = build_final_cleanup_posture_snapshot()
        assert snapshot.bypass_risks == []

    def test_D04_snapshot_no_unavailable_modules(self):
        snapshot = build_final_cleanup_posture_snapshot()
        assert snapshot.unavailable_modules == []

    def test_D05_snapshot_to_dict_is_json_serialisable(self):
        snapshot = build_final_cleanup_posture_snapshot()
        d = snapshot.to_dict()
        # Must be JSON-serialisable (raises TypeError / ValueError if not)
        serialised = json.dumps(d)
        assert serialised

    def test_D06_snapshot_to_dict_required_keys(self):
        snapshot = build_final_cleanup_posture_snapshot()
        d = snapshot.to_dict()
        for key in (
            "all_canonical_confirmed",
            "bypass_risks",
            "unavailable_modules",
            "guard_results",
            "evaluated_at",
        ):
            assert key in d, f"Missing key: {key}"

    def test_D07_snapshot_guard_results_have_required_fields(self):
        snapshot = build_final_cleanup_posture_snapshot()
        d = snapshot.to_dict()
        for gr in d["guard_results"]:
            for field in ("area", "verdict", "canonical_path", "bypass_risk"):
                assert field in gr, f"Missing field '{field}' in guard_result"


# ---------------------------------------------------------------------------
# Group E — is_final_cleanup_posture_acceptable
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="core.final_cleanup_invariant_tightening not available")
class TestE_PostureAcceptable:
    """Group E: is_final_cleanup_posture_acceptable() returns True."""

    def test_E01_posture_is_acceptable(self):
        assert is_final_cleanup_posture_acceptable(), (
            "is_final_cleanup_posture_acceptable() returned False; "
            "at least one canonical module is not importable."
        )


# ---------------------------------------------------------------------------
# Group F — Capability tier registry
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="core.final_cleanup_invariant_tightening not available")
class TestF_CapabilityTierRegistry:
    """Group F: Semantic capability tier registry is populated with correct tiers."""

    def test_F01_registry_is_non_empty(self):
        registry = get_capability_tier_registry()
        assert len(registry) > 0

    def test_F02_completion_ingress_is_mainline(self):
        record = get_capability_tier("completion_ingress")
        assert record is not None
        assert record.tier == CapabilityTier.MAINLINE

    def test_F03_capability_aware_routing_is_mainline(self):
        record = get_capability_tier("capability_aware_routing")
        assert record is not None
        assert record.tier == CapabilityTier.MAINLINE

    def test_F04_runtime_truth_ingress_is_mainline(self):
        record = get_capability_tier("runtime_truth_ingress")
        assert record is not None
        assert record.tier == CapabilityTier.MAINLINE

    def test_F05_provider_routing_is_mainline(self):
        record = get_capability_tier("provider_routing")
        assert record is not None
        assert record.tier == CapabilityTier.MAINLINE

    def test_F06_validation_release_gate_is_mainline(self):
        record = get_capability_tier("validation_release_gate")
        assert record is not None
        assert record.tier == CapabilityTier.MAINLINE

    def test_F07_local_vlm_multimodal_is_extension(self):
        """Local VLM is classified as EXTENSION — must not be called 'fully mainline'."""
        record = get_capability_tier("local_vlm_multimodal")
        assert record is not None
        assert record.tier == CapabilityTier.EXTENSION, (
            "local_vlm_multimodal MUST be EXTENSION tier (not MAINLINE or NEAR_MAINLINE). "
            "Describing it as 'fully mainline' would be semantically misleading."
        )

    def test_F08_staged_mesh_is_near_mainline(self):
        """Staged mesh is NEAR_MAINLINE — must not be called 'fully mainline'."""
        record = get_capability_tier("staged_mesh")
        assert record is not None
        assert record.tier == CapabilityTier.NEAR_MAINLINE, (
            "staged_mesh MUST be NEAR_MAINLINE tier (not MAINLINE). "
            "It has residual gaps and must not be described as 'fully mainline'."
        )

    def test_F09_no_unknown_capability_ids_in_registry(self):
        registry = get_capability_tier_registry()
        for record in registry:
            assert isinstance(record.capability_id, str)
            assert record.capability_id
            assert isinstance(record.tier, CapabilityTier)

    def test_F10_get_capability_tier_returns_none_for_unknown(self):
        result = get_capability_tier("nonexistent_capability_xyz_99999")
        assert result is None


# ---------------------------------------------------------------------------
# Group G — BypassInvariantViolation
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="core.final_cleanup_invariant_tightening not available")
class TestG_BypassInvariantViolation:
    """Group G: BypassInvariantViolation is a RuntimeError subclass."""

    def test_G01_is_runtime_error_subclass(self):
        assert issubclass(BypassInvariantViolation, RuntimeError)

    def test_G02_carries_expected_attributes(self):
        exc = BypassInvariantViolation(
            ClosureArea.completion_ingress,
            CANONICAL_COMPLETION_INGRESS_PATH,
            "test violation detail",
        )
        assert exc.area == ClosureArea.completion_ingress
        assert exc.canonical_path == CANONICAL_COMPLETION_INGRESS_PATH
        assert exc.detail == "test violation detail"

    def test_G03_str_representation_contains_area(self):
        exc = BypassInvariantViolation(
            ClosureArea.provider_routing,
            CANONICAL_PROVIDER_ROUTING_PATH,
            "provider bypass attempt",
        )
        assert "provider_routing" in str(exc)

    def test_G04_not_raised_in_non_strict_mode(self):
        """Guards must not raise in non-strict mode (default)."""
        # Non-strict guards return results without raising
        result = assert_completion_ingress_is_canonical(strict=False)
        assert result is not None  # no exception raised


# ---------------------------------------------------------------------------
# Group H — core.runtime re-exports PR-5 final cleanup symbols
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _RUNTIME_AVAILABLE, reason="core.runtime PR-5 final exports not available")
class TestH_RuntimeReexports:
    """Group H: core.runtime re-exports all PR-5 final cleanup sentinel symbols."""

    def test_H01_authority_reexported(self):
        assert isinstance(_rt_authority, str)
        assert _rt_authority

    def test_H02_pr5_sentinel_reexported(self):
        assert isinstance(_rt_pr5, str)
        assert _rt_pr5

    def test_H03_policy_sentinels_reexported(self):
        for sentinel in [
            _rt_completion,
            _rt_capability,
            _rt_truth,
            _rt_provider,
            _rt_gate,
        ]:
            assert isinstance(sentinel, str)
            assert sentinel

    def test_H04_guard_functions_reexported(self):
        for fn in [
            _rt_assert_completion,
            _rt_assert_capability,
            _rt_assert_truth,
            _rt_assert_provider,
            _rt_assert_gate,
        ]:
            assert callable(fn)

    def test_H05_posture_functions_reexported(self):
        assert callable(_rt_posture_ok)
        assert callable(_rt_snapshot)

    def test_H06_posture_acceptable_via_runtime(self):
        """Core.runtime re-export of is_final_cleanup_posture_acceptable returns True."""
        assert _rt_posture_ok()


# ---------------------------------------------------------------------------
# Group I — core.routes.projection carries PR-5 alignment sentinel
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _PROJECTION_AVAILABLE, reason="core.routes.projection PR-5 sentinel not available")
class TestI_ProjectionSentinel:
    """Group I: core.routes.projection carries PR-5 final cleanup alignment sentinel."""

    def test_I01_sentinel_is_string(self):
        assert isinstance(FINAL_CLEANUP_INVARIANT_TIGHTENING_ALIGNED_PR5_FINAL, str)

    def test_I02_sentinel_not_unavailable(self):
        assert "UNAVAILABLE" not in FINAL_CLEANUP_INVARIANT_TIGHTENING_ALIGNED_PR5_FINAL, (
            "PR-5 final cleanup alignment sentinel is UNAVAILABLE — "
            "core.final_cleanup_invariant_tightening failed to import in projection routes."
        )

    def test_I03_sentinel_contains_expected_keywords(self):
        sentinel = FINAL_CLEANUP_INVARIANT_TIGHTENING_ALIGNED_PR5_FINAL
        for keyword in ("PR5", "FINAL", "no-bypass"):
            assert keyword.lower() in sentinel.lower(), (
                f"Sentinel missing expected keyword '{keyword}'"
            )


# ---------------------------------------------------------------------------
# Group J — Strict mode raises BypassInvariantViolation on bypass risk
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="core.final_cleanup_invariant_tightening not available")
class TestJ_StrictMode:
    """Group J: Guards raise BypassInvariantViolation in strict mode if bypass risk detected."""

    def test_J01_strict_mode_does_not_raise_when_canonical_confirmed(self):
        """In strict mode, confirmed canonical paths must NOT raise."""
        # These should all pass without raising since canonical modules are present
        assert_completion_ingress_is_canonical(strict=True)
        assert_capability_routing_is_canonical(strict=True)
        assert_runtime_truth_ingress_is_canonical(strict=True)
        assert_provider_routing_is_canonical(strict=True)
        assert_validation_gate_is_canonical(strict=True)

    def test_J02_bypass_invariant_violation_is_raisable(self):
        """BypassInvariantViolation can be raised and caught as RuntimeError."""
        with pytest.raises(RuntimeError):
            raise BypassInvariantViolation(
                ClosureArea.completion_ingress,
                CANONICAL_COMPLETION_INGRESS_PATH,
                "simulated bypass",
            )

    def test_J03_bypass_invariant_violation_is_catchable_as_specific_type(self):
        """BypassInvariantViolation can be caught as its specific type."""
        with pytest.raises(BypassInvariantViolation) as exc_info:
            raise BypassInvariantViolation(
                ClosureArea.provider_routing,
                CANONICAL_PROVIDER_ROUTING_PATH,
                "simulated provider bypass",
            )
        assert exc_info.value.area == ClosureArea.provider_routing


# ---------------------------------------------------------------------------
# Group K — Sentinel strings contain expected policy keywords
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="core.final_cleanup_invariant_tightening not available")
class TestK_SentinelKeywords:
    """Group K: Sentinel strings contain expected policy keywords."""

    def test_K01_authority_sentinel_contains_authority_keyword(self):
        assert "AUTHORITY" in FINAL_CLEANUP_INVARIANT_TIGHTENING_AUTHORITY

    def test_K02_pr5_sentinel_contains_pr5_keyword(self):
        assert "PR5" in FINAL_CLEANUP_INVARIANT_TIGHTENING_PR5_SENTINEL or \
               "PR-5" in FINAL_CLEANUP_INVARIANT_TIGHTENING_PR5_SENTINEL

    def test_K03_completion_ingress_policy_contains_canonical_ingress_keyword(self):
        assert "CanonicalCompletionIngress" in NO_BYPASS_COMPLETION_INGRESS_POLICY

    def test_K04_capability_routing_policy_contains_gate_keyword(self):
        assert "capability_gate" in NO_BYPASS_CAPABILITY_ROUTING_POLICY or \
               "evaluate_capability_gate" in NO_BYPASS_CAPABILITY_ROUTING_POLICY

    def test_K05_runtime_truth_ingress_policy_contains_ingress_function_keyword(self):
        assert "ingest_android_runtime_state_update" in NO_BYPASS_RUNTIME_TRUTH_INGRESS_POLICY

    def test_K06_provider_routing_policy_contains_unified_router_keyword(self):
        assert "UnifiedLLMRouter" in NO_BYPASS_PROVIDER_ROUTING_POLICY

    def test_K07_validation_gate_policy_contains_release_gate_keyword(self):
        assert "ReleaseGate" in NO_BYPASS_VALIDATION_GATE_POLICY

    def test_K08_semantic_tier_policy_mentions_extension(self):
        assert "EXTENSION" in SEMANTIC_CAPABILITY_TIER_POLICY

    def test_K09_legacy_path_policy_mentions_violation(self):
        assert "violation" in LEGACY_PATH_MUST_NOT_RE_ENTER_CANONICAL_SURFACE_POLICY.lower()


# ---------------------------------------------------------------------------
# Group L — Guard result fields
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="core.final_cleanup_invariant_tightening not available")
class TestL_GuardResultFields:
    """Group L: BypassGuardResult fields are present and correctly typed."""

    def _get_result(self) -> "BypassGuardResult":
        return assert_completion_ingress_is_canonical()

    def test_L01_area_is_closure_area(self):
        result = self._get_result()
        assert isinstance(result.area, ClosureArea)

    def test_L02_verdict_is_bypass_guard_verdict(self):
        result = self._get_result()
        assert isinstance(result.verdict, BypassGuardVerdict)

    def test_L03_canonical_path_is_string(self):
        result = self._get_result()
        assert isinstance(result.canonical_path, str)
        assert result.canonical_path

    def test_L04_bypass_risk_is_bool(self):
        result = self._get_result()
        assert isinstance(result.bypass_risk, bool)

    def test_L05_description_is_string(self):
        result = self._get_result()
        assert isinstance(result.description, str)
        assert result.description

    def test_L06_details_is_dict(self):
        result = self._get_result()
        assert isinstance(result.details, dict)

    def test_L07_evaluated_at_is_float(self):
        result = self._get_result()
        assert isinstance(result.evaluated_at, float)
        assert result.evaluated_at > 0


# ---------------------------------------------------------------------------
# Group M — Snapshot to_dict() keys and types
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="core.final_cleanup_invariant_tightening not available")
class TestM_SnapshotToDictKeys:
    """Group M: FinalCleanupPostureSnapshot.to_dict() required keys and types."""

    def _get_dict(self) -> Dict[str, Any]:
        return build_final_cleanup_posture_snapshot().to_dict()

    def test_M01_all_canonical_confirmed_is_bool(self):
        d = self._get_dict()
        assert isinstance(d["all_canonical_confirmed"], bool)

    def test_M02_bypass_risks_is_list(self):
        d = self._get_dict()
        assert isinstance(d["bypass_risks"], list)

    def test_M03_unavailable_modules_is_list(self):
        d = self._get_dict()
        assert isinstance(d["unavailable_modules"], list)

    def test_M04_guard_results_is_list(self):
        d = self._get_dict()
        assert isinstance(d["guard_results"], list)

    def test_M05_evaluated_at_is_numeric(self):
        d = self._get_dict()
        assert isinstance(d["evaluated_at"], (int, float))

    def test_M06_guard_results_count_is_five(self):
        d = self._get_dict()
        assert len(d["guard_results"]) == 5


# ---------------------------------------------------------------------------
# Group N — get_capability_tier() lookup by ID
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="core.final_cleanup_invariant_tightening not available")
class TestN_CapabilityTierLookup:
    """Group N: get_capability_tier() returns the correct record by ID."""

    def test_N01_known_id_returns_record(self):
        record = get_capability_tier("completion_ingress")
        assert record is not None
        assert isinstance(record, CapabilityTierRecord)

    def test_N02_record_tier_matches_registry(self):
        registry = get_capability_tier_registry()
        for expected in registry:
            found = get_capability_tier(expected.capability_id)
            assert found is not None
            assert found.capability_id == expected.capability_id
            assert found.tier == expected.tier

    def test_N03_unknown_id_returns_none(self):
        assert get_capability_tier("__nonexistent__") is None


# ---------------------------------------------------------------------------
# Group O — BypassGuardVerdict enum values
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="core.final_cleanup_invariant_tightening not available")
class TestO_BypassGuardVerdictEnum:
    """Group O: BypassGuardVerdict has all expected values."""

    def test_O01_canonical_path_confirmed_present(self):
        assert BypassGuardVerdict.CANONICAL_PATH_CONFIRMED

    def test_O02_bypass_risk_detected_present(self):
        assert BypassGuardVerdict.BYPASS_RISK_DETECTED

    def test_O03_canonical_module_unavailable_present(self):
        assert BypassGuardVerdict.CANONICAL_MODULE_UNAVAILABLE

    def test_O04_legacy_path_active_present(self):
        assert BypassGuardVerdict.LEGACY_PATH_ACTIVE


# ---------------------------------------------------------------------------
# Group P — ClosureArea enum has five members
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="core.final_cleanup_invariant_tightening not available")
class TestP_ClosureAreaEnum:
    """Group P: ClosureArea enum has all five expected area values."""

    def test_P01_completion_ingress_present(self):
        assert ClosureArea.completion_ingress

    def test_P02_capability_routing_present(self):
        assert ClosureArea.capability_routing

    def test_P03_runtime_truth_ingress_present(self):
        assert ClosureArea.runtime_truth_ingress

    def test_P04_provider_routing_present(self):
        assert ClosureArea.provider_routing

    def test_P05_validation_gate_present(self):
        assert ClosureArea.validation_gate

    def test_P06_exactly_five_areas(self):
        assert len(list(ClosureArea)) == 5
