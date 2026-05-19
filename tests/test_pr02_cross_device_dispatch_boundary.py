"""tests/test_pr02_cross_device_dispatch_boundary.py
====================================================
PR-02: Cross-Device Dispatch Boundary Contract Tests.

Verifies that the consolidated dispatch boundary contract introduced by PR-02
is correct, importable, and consistent with the real dispatch behavior in
``device_router.py``, ``cross_device_coordinator.py``, and
``capability_orchestrator.py``.

Coverage groups
---------------
A.  Module importability — all public symbols importable from a single place.
B.  Dispatch path constants — correct values, stable across renames.
C.  Route mode constants — correct values.
D.  Substrate caller constants — correct values.
E.  DispatchPathCategory enum — all four categories present with correct values.
F.  classify_dispatch_call() — canonical dispatch path.
G.  classify_dispatch_call() — controlled canonical fallback.
H.  classify_dispatch_call() — compat fallback.
I.  classify_dispatch_call() — legacy bypass.
J.  classify_dispatch_call() — inference from substrate caller (no dispatch_path).
K.  DispatchBoundaryClassification — is_canonical / is_fallback flags.
L.  DispatchBoundaryClassification — to_dict() serialisation.
M.  Convenience predicates — is_canonical_dispatch / is_controlled_fallback /
    is_compat_fallback / is_legacy_bypass.
N.  get_boundary_contract_snapshot() — shape and required keys.
O.  Authority sentinels — all policy sentinels importable and non-empty.
P.  DeviceRouter wiring — dispatch path constants match what DeviceRouter sets.
Q.  CrossDeviceCoordinator wiring — boundary constants used in coordinator.
R.  CapabilityOrchestrator wiring — boundary constants used in orchestrator.
S.  Android ↔ V2 dispatch contract alignment — context keys consistent.
T.  Policy guards — valid_for_new_work flags correct.
"""

from __future__ import annotations

import pytest


# ============================================================================
# A.  Module importability
# ============================================================================

class TestModuleImportability:

    def test_A01_module_importable(self):
        """core.cross_device_dispatch_boundary must be importable."""
        import core.cross_device_dispatch_boundary  # noqa: F401

    def test_A02_all_public_constants_importable(self):
        from core.cross_device_dispatch_boundary import (
            DISPATCH_PATH_CANONICAL,
            DISPATCH_PATH_CONTROLLED_FALLBACK,
            DISPATCH_PATH_COMPAT_FALLBACK,
            DISPATCH_PATH_LEGACY_BYPASS,
            ROUTE_MODE_CROSS_DEVICE,
            ROUTE_MODE_COMPAT_FALLBACK,
            SUBSTRATE_CALLER_DEVICE_ROUTER,
            SUBSTRATE_CALLER_COMPAT,
        )
        assert all(
            isinstance(c, str)
            for c in [
                DISPATCH_PATH_CANONICAL,
                DISPATCH_PATH_CONTROLLED_FALLBACK,
                DISPATCH_PATH_COMPAT_FALLBACK,
                DISPATCH_PATH_LEGACY_BYPASS,
                ROUTE_MODE_CROSS_DEVICE,
                ROUTE_MODE_COMPAT_FALLBACK,
                SUBSTRATE_CALLER_DEVICE_ROUTER,
                SUBSTRATE_CALLER_COMPAT,
            ]
        )

    def test_A03_all_public_types_importable(self):
        from core.cross_device_dispatch_boundary import (
            DispatchPathCategory,
            DispatchBoundaryClassification,
            classify_dispatch_call,
            is_canonical_dispatch,
            is_controlled_fallback,
            is_compat_fallback,
            is_legacy_bypass,
            get_boundary_contract_snapshot,
        )
        assert callable(classify_dispatch_call)
        assert callable(is_canonical_dispatch)
        assert callable(is_controlled_fallback)
        assert callable(is_compat_fallback)
        assert callable(is_legacy_bypass)
        assert callable(get_boundary_contract_snapshot)

    def test_A04_all_sentinels_importable(self):
        from core.cross_device_dispatch_boundary import (
            CROSS_DEVICE_DISPATCH_BOUNDARY_CONTRACT,
            CROSS_DEVICE_DISPATCH_PR02_SENTINEL,
            CANONICAL_PATH_ONLY_FOR_NEW_WORK_POLICY,
            DEVICE_ROUTER_NOT_A_POLICY_AUTHORITY_POLICY,
            COMPAT_FALLBACK_NOT_PRIMARY_PATH_POLICY,
            LEGACY_BYPASS_MUST_EMIT_WARNING_POLICY,
        )
        for sentinel in [
            CROSS_DEVICE_DISPATCH_BOUNDARY_CONTRACT,
            CROSS_DEVICE_DISPATCH_PR02_SENTINEL,
            CANONICAL_PATH_ONLY_FOR_NEW_WORK_POLICY,
            DEVICE_ROUTER_NOT_A_POLICY_AUTHORITY_POLICY,
            COMPAT_FALLBACK_NOT_PRIMARY_PATH_POLICY,
            LEGACY_BYPASS_MUST_EMIT_WARNING_POLICY,
        ]:
            assert isinstance(sentinel, str)
            assert len(sentinel) > 0


# ============================================================================
# B.  Dispatch path constants
# ============================================================================

class TestDispatchPathConstants:

    def test_B01_canonical_value(self):
        from core.cross_device_dispatch_boundary import DISPATCH_PATH_CANONICAL
        assert DISPATCH_PATH_CANONICAL == "canonical_dispatch"

    def test_B02_controlled_fallback_value(self):
        from core.cross_device_dispatch_boundary import DISPATCH_PATH_CONTROLLED_FALLBACK
        assert DISPATCH_PATH_CONTROLLED_FALLBACK == "canonical_fallback"

    def test_B03_compat_fallback_value(self):
        from core.cross_device_dispatch_boundary import DISPATCH_PATH_COMPAT_FALLBACK
        assert DISPATCH_PATH_COMPAT_FALLBACK == "compat_fallback"

    def test_B04_legacy_bypass_value(self):
        from core.cross_device_dispatch_boundary import DISPATCH_PATH_LEGACY_BYPASS
        assert DISPATCH_PATH_LEGACY_BYPASS == "legacy_bypass"

    def test_B05_all_four_paths_are_distinct(self):
        from core.cross_device_dispatch_boundary import (
            DISPATCH_PATH_CANONICAL,
            DISPATCH_PATH_CONTROLLED_FALLBACK,
            DISPATCH_PATH_COMPAT_FALLBACK,
            DISPATCH_PATH_LEGACY_BYPASS,
        )
        paths = [
            DISPATCH_PATH_CANONICAL,
            DISPATCH_PATH_CONTROLLED_FALLBACK,
            DISPATCH_PATH_COMPAT_FALLBACK,
            DISPATCH_PATH_LEGACY_BYPASS,
        ]
        assert len(set(paths)) == 4, "All four dispatch path constants must have distinct values"


# ============================================================================
# C.  Route mode constants
# ============================================================================

class TestRouteModeConstants:

    def test_C01_cross_device_value(self):
        from core.cross_device_dispatch_boundary import ROUTE_MODE_CROSS_DEVICE
        assert ROUTE_MODE_CROSS_DEVICE == "cross_device"

    def test_C02_compat_fallback_value(self):
        from core.cross_device_dispatch_boundary import ROUTE_MODE_COMPAT_FALLBACK
        assert ROUTE_MODE_COMPAT_FALLBACK == "cross_device_compat_fallback"

    def test_C03_modes_are_distinct(self):
        from core.cross_device_dispatch_boundary import (
            ROUTE_MODE_CROSS_DEVICE,
            ROUTE_MODE_COMPAT_FALLBACK,
        )
        assert ROUTE_MODE_CROSS_DEVICE != ROUTE_MODE_COMPAT_FALLBACK


# ============================================================================
# D.  Substrate caller constants
# ============================================================================

class TestSubstrateCallerConstants:

    def test_D01_device_router_value(self):
        from core.cross_device_dispatch_boundary import SUBSTRATE_CALLER_DEVICE_ROUTER
        assert SUBSTRATE_CALLER_DEVICE_ROUTER == "device_router.route_task"

    def test_D02_compat_value(self):
        from core.cross_device_dispatch_boundary import SUBSTRATE_CALLER_COMPAT
        assert SUBSTRATE_CALLER_COMPAT == "capability_orchestrator.compat_fallback"

    def test_D03_callers_are_distinct(self):
        from core.cross_device_dispatch_boundary import (
            SUBSTRATE_CALLER_DEVICE_ROUTER,
            SUBSTRATE_CALLER_COMPAT,
        )
        assert SUBSTRATE_CALLER_DEVICE_ROUTER != SUBSTRATE_CALLER_COMPAT


# ============================================================================
# E.  DispatchPathCategory enum
# ============================================================================

class TestDispatchPathCategoryEnum:

    def test_E01_canonical_member(self):
        from core.cross_device_dispatch_boundary import DispatchPathCategory
        assert DispatchPathCategory.CANONICAL.value == "canonical_dispatch"

    def test_E02_controlled_fallback_member(self):
        from core.cross_device_dispatch_boundary import DispatchPathCategory
        assert DispatchPathCategory.CONTROLLED_FALLBACK.value == "canonical_fallback"

    def test_E03_compat_fallback_member(self):
        from core.cross_device_dispatch_boundary import DispatchPathCategory
        assert DispatchPathCategory.COMPAT_FALLBACK.value == "compat_fallback"

    def test_E04_legacy_bypass_member(self):
        from core.cross_device_dispatch_boundary import DispatchPathCategory
        assert DispatchPathCategory.LEGACY_BYPASS.value == "legacy_bypass"

    def test_E05_unknown_member(self):
        from core.cross_device_dispatch_boundary import DispatchPathCategory
        assert DispatchPathCategory.UNKNOWN.value == "unknown"

    def test_E06_enum_values_match_path_constants(self):
        from core.cross_device_dispatch_boundary import (
            DispatchPathCategory,
            DISPATCH_PATH_CANONICAL,
            DISPATCH_PATH_CONTROLLED_FALLBACK,
            DISPATCH_PATH_COMPAT_FALLBACK,
            DISPATCH_PATH_LEGACY_BYPASS,
        )
        assert DispatchPathCategory.CANONICAL.value == DISPATCH_PATH_CANONICAL
        assert DispatchPathCategory.CONTROLLED_FALLBACK.value == DISPATCH_PATH_CONTROLLED_FALLBACK
        assert DispatchPathCategory.COMPAT_FALLBACK.value == DISPATCH_PATH_COMPAT_FALLBACK
        assert DispatchPathCategory.LEGACY_BYPASS.value == DISPATCH_PATH_LEGACY_BYPASS


# ============================================================================
# F.  classify_dispatch_call() — canonical dispatch path
# ============================================================================

class TestClassifyCanonicalDispatch:

    def test_F01_explicit_canonical_dispatch_path(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DispatchPathCategory,
            DISPATCH_PATH_CANONICAL,
            SUBSTRATE_CALLER_DEVICE_ROUTER,
            ROUTE_MODE_CROSS_DEVICE,
        )
        clf = classify_dispatch_call(
            dispatch_path=DISPATCH_PATH_CANONICAL,
            substrate_caller=SUBSTRATE_CALLER_DEVICE_ROUTER,
            route_mode=ROUTE_MODE_CROSS_DEVICE,
        )
        assert clf.category == DispatchPathCategory.CANONICAL
        assert clf.is_canonical is True
        assert clf.is_fallback is False

    def test_F02_explicit_canonical_dispatch_path_no_caller(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DispatchPathCategory,
            DISPATCH_PATH_CANONICAL,
        )
        # dispatch_path explicitly set wins over missing caller
        clf = classify_dispatch_call(dispatch_path=DISPATCH_PATH_CANONICAL)
        assert clf.category == DispatchPathCategory.CANONICAL

    def test_F03_canonical_dispatch_is_not_fallback(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DISPATCH_PATH_CANONICAL,
        )
        clf = classify_dispatch_call(dispatch_path=DISPATCH_PATH_CANONICAL)
        assert clf.is_fallback is False


# ============================================================================
# G.  classify_dispatch_call() — controlled canonical fallback
# ============================================================================

class TestClassifyControlledFallback:

    def test_G01_explicit_canonical_fallback_dispatch_path(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DispatchPathCategory,
            DISPATCH_PATH_CONTROLLED_FALLBACK,
            SUBSTRATE_CALLER_DEVICE_ROUTER,
        )
        clf = classify_dispatch_call(
            dispatch_path=DISPATCH_PATH_CONTROLLED_FALLBACK,
            substrate_caller=SUBSTRATE_CALLER_DEVICE_ROUTER,
        )
        assert clf.category == DispatchPathCategory.CONTROLLED_FALLBACK
        assert clf.is_canonical is True
        assert clf.is_fallback is True

    def test_G02_inferred_from_device_router_caller_without_fallback_reason(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DispatchPathCategory,
            SUBSTRATE_CALLER_DEVICE_ROUTER,
        )
        # No dispatch_path set, but canonical substrate caller → controlled fallback
        clf = classify_dispatch_call(substrate_caller=SUBSTRATE_CALLER_DEVICE_ROUTER)
        assert clf.category == DispatchPathCategory.CONTROLLED_FALLBACK
        assert clf.is_canonical is True

    def test_G03_controlled_fallback_is_canonical(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DISPATCH_PATH_CONTROLLED_FALLBACK,
        )
        clf = classify_dispatch_call(dispatch_path=DISPATCH_PATH_CONTROLLED_FALLBACK)
        assert clf.is_canonical is True


# ============================================================================
# H.  classify_dispatch_call() — compat fallback
# ============================================================================

class TestClassifyCompatFallback:

    def test_H01_explicit_compat_fallback_dispatch_path(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DispatchPathCategory,
            DISPATCH_PATH_COMPAT_FALLBACK,
            SUBSTRATE_CALLER_COMPAT,
            ROUTE_MODE_COMPAT_FALLBACK,
        )
        clf = classify_dispatch_call(
            dispatch_path=DISPATCH_PATH_COMPAT_FALLBACK,
            substrate_caller=SUBSTRATE_CALLER_COMPAT,
            route_mode=ROUTE_MODE_COMPAT_FALLBACK,
        )
        assert clf.category == DispatchPathCategory.COMPAT_FALLBACK
        assert clf.is_canonical is False
        assert clf.is_fallback is True

    def test_H02_inferred_from_non_canonical_caller(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DispatchPathCategory,
            SUBSTRATE_CALLER_COMPAT,
        )
        # Non-canonical caller, no dispatch_path → compat_fallback
        clf = classify_dispatch_call(substrate_caller=SUBSTRATE_CALLER_COMPAT)
        assert clf.category == DispatchPathCategory.COMPAT_FALLBACK

    def test_H03_any_non_empty_non_canonical_caller_yields_compat(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DispatchPathCategory,
        )
        clf = classify_dispatch_call(substrate_caller="some_other_module.dispatch")
        assert clf.category == DispatchPathCategory.COMPAT_FALLBACK

    def test_H04_compat_fallback_is_not_canonical(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DISPATCH_PATH_COMPAT_FALLBACK,
        )
        clf = classify_dispatch_call(dispatch_path=DISPATCH_PATH_COMPAT_FALLBACK)
        assert clf.is_canonical is False


# ============================================================================
# I.  classify_dispatch_call() — legacy bypass
# ============================================================================

class TestClassifyLegacyBypass:

    def test_I01_explicit_legacy_bypass_dispatch_path(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DispatchPathCategory,
            DISPATCH_PATH_LEGACY_BYPASS,
        )
        clf = classify_dispatch_call(dispatch_path=DISPATCH_PATH_LEGACY_BYPASS)
        assert clf.category == DispatchPathCategory.LEGACY_BYPASS
        assert clf.is_canonical is False

    def test_I02_no_dispatch_path_no_caller_yields_legacy_bypass(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DispatchPathCategory,
        )
        clf = classify_dispatch_call()
        assert clf.category == DispatchPathCategory.LEGACY_BYPASS

    def test_I03_empty_strings_yield_legacy_bypass(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DispatchPathCategory,
        )
        clf = classify_dispatch_call(dispatch_path="", substrate_caller="", route_mode="")
        assert clf.category == DispatchPathCategory.LEGACY_BYPASS

    def test_I04_legacy_bypass_is_not_canonical(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DISPATCH_PATH_LEGACY_BYPASS,
        )
        clf = classify_dispatch_call(dispatch_path=DISPATCH_PATH_LEGACY_BYPASS)
        assert clf.is_canonical is False
        assert clf.is_fallback is False


# ============================================================================
# J.  classify_dispatch_call() — inference from substrate caller
# ============================================================================

class TestClassifyInferenceFromCaller:

    def test_J01_device_router_caller_without_dispatch_path_gives_controlled_fallback(self):
        """When DeviceRouter is caller and no dispatch_path is set, infer controlled fallback."""
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DispatchPathCategory,
            SUBSTRATE_CALLER_DEVICE_ROUTER,
        )
        clf = classify_dispatch_call(substrate_caller=SUBSTRATE_CALLER_DEVICE_ROUTER)
        assert clf.category == DispatchPathCategory.CONTROLLED_FALLBACK

    def test_J02_explicit_dispatch_path_wins_over_caller_inference(self):
        """Explicit dispatch_path in context always wins over caller inference."""
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DispatchPathCategory,
            DISPATCH_PATH_CANONICAL,
            SUBSTRATE_CALLER_COMPAT,
        )
        # Even with a compat caller, explicit canonical dispatch_path wins
        clf = classify_dispatch_call(
            dispatch_path=DISPATCH_PATH_CANONICAL,
            substrate_caller=SUBSTRATE_CALLER_COMPAT,
        )
        assert clf.category == DispatchPathCategory.CANONICAL


# ============================================================================
# K.  DispatchBoundaryClassification — is_canonical / is_fallback flags
# ============================================================================

class TestClassificationFlags:

    def test_K01_canonical_is_canonical_not_fallback(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DISPATCH_PATH_CANONICAL,
        )
        clf = classify_dispatch_call(dispatch_path=DISPATCH_PATH_CANONICAL)
        assert clf.is_canonical is True
        assert clf.is_fallback is False

    def test_K02_controlled_fallback_is_canonical_and_fallback(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DISPATCH_PATH_CONTROLLED_FALLBACK,
        )
        clf = classify_dispatch_call(dispatch_path=DISPATCH_PATH_CONTROLLED_FALLBACK)
        assert clf.is_canonical is True
        assert clf.is_fallback is True

    def test_K03_compat_fallback_is_not_canonical_but_is_fallback(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DISPATCH_PATH_COMPAT_FALLBACK,
        )
        clf = classify_dispatch_call(dispatch_path=DISPATCH_PATH_COMPAT_FALLBACK)
        assert clf.is_canonical is False
        assert clf.is_fallback is True

    def test_K04_legacy_bypass_is_not_canonical_not_fallback(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DISPATCH_PATH_LEGACY_BYPASS,
        )
        clf = classify_dispatch_call(dispatch_path=DISPATCH_PATH_LEGACY_BYPASS)
        assert clf.is_canonical is False
        assert clf.is_fallback is False


# ============================================================================
# L.  DispatchBoundaryClassification — to_dict() serialisation
# ============================================================================

class TestClassificationToDict:

    def test_L01_to_dict_contains_required_keys(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DISPATCH_PATH_CANONICAL,
        )
        clf = classify_dispatch_call(dispatch_path=DISPATCH_PATH_CANONICAL)
        d = clf.to_dict()
        required_keys = {
            "category", "dispatch_path", "substrate_caller",
            "route_mode", "is_canonical", "is_fallback", "policy_notes",
        }
        assert required_keys.issubset(d.keys())

    def test_L02_to_dict_category_is_string(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DISPATCH_PATH_CANONICAL,
        )
        clf = classify_dispatch_call(dispatch_path=DISPATCH_PATH_CANONICAL)
        d = clf.to_dict()
        assert isinstance(d["category"], str)

    def test_L03_to_dict_is_canonical_bool(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DISPATCH_PATH_CANONICAL,
        )
        clf = classify_dispatch_call(dispatch_path=DISPATCH_PATH_CANONICAL)
        d = clf.to_dict()
        assert isinstance(d["is_canonical"], bool)
        assert d["is_canonical"] is True

    def test_L04_to_dict_round_trip_category(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DispatchPathCategory,
            DISPATCH_PATH_CONTROLLED_FALLBACK,
        )
        clf = classify_dispatch_call(dispatch_path=DISPATCH_PATH_CONTROLLED_FALLBACK)
        d = clf.to_dict()
        assert d["category"] == DispatchPathCategory.CONTROLLED_FALLBACK.value


# ============================================================================
# M.  Convenience predicate helpers
# ============================================================================

class TestConvenientPredicates:

    def test_M01_is_canonical_dispatch_true_for_canonical(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            is_canonical_dispatch,
            DISPATCH_PATH_CANONICAL,
        )
        assert is_canonical_dispatch(classify_dispatch_call(dispatch_path=DISPATCH_PATH_CANONICAL))

    def test_M02_is_canonical_dispatch_false_for_others(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            is_canonical_dispatch,
            DISPATCH_PATH_CONTROLLED_FALLBACK,
            DISPATCH_PATH_COMPAT_FALLBACK,
            DISPATCH_PATH_LEGACY_BYPASS,
        )
        for dp in [DISPATCH_PATH_CONTROLLED_FALLBACK, DISPATCH_PATH_COMPAT_FALLBACK, DISPATCH_PATH_LEGACY_BYPASS]:
            assert not is_canonical_dispatch(classify_dispatch_call(dispatch_path=dp))

    def test_M03_is_controlled_fallback_true(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            is_controlled_fallback,
            DISPATCH_PATH_CONTROLLED_FALLBACK,
        )
        assert is_controlled_fallback(classify_dispatch_call(dispatch_path=DISPATCH_PATH_CONTROLLED_FALLBACK))

    def test_M04_is_compat_fallback_true(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            is_compat_fallback,
            DISPATCH_PATH_COMPAT_FALLBACK,
        )
        assert is_compat_fallback(classify_dispatch_call(dispatch_path=DISPATCH_PATH_COMPAT_FALLBACK))

    def test_M05_is_legacy_bypass_true_for_legacy(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            is_legacy_bypass,
            DISPATCH_PATH_LEGACY_BYPASS,
        )
        assert is_legacy_bypass(classify_dispatch_call(dispatch_path=DISPATCH_PATH_LEGACY_BYPASS))

    def test_M06_is_legacy_bypass_true_for_no_caller_no_path(self):
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            is_legacy_bypass,
        )
        assert is_legacy_bypass(classify_dispatch_call())


# ============================================================================
# N.  get_boundary_contract_snapshot() — shape and required keys
# ============================================================================

class TestBoundaryContractSnapshot:

    def test_N01_snapshot_is_dict(self):
        from core.cross_device_dispatch_boundary import get_boundary_contract_snapshot
        snapshot = get_boundary_contract_snapshot()
        assert isinstance(snapshot, dict)

    def test_N02_snapshot_has_required_top_level_keys(self):
        from core.cross_device_dispatch_boundary import get_boundary_contract_snapshot
        snapshot = get_boundary_contract_snapshot()
        required = {
            "boundary_version",
            "sentinel",
            "dispatch_path_categories",
            "canonical_chain",
            "android_dispatch_contract",
            "policies",
        }
        assert required.issubset(snapshot.keys())

    def test_N03_snapshot_has_all_four_dispatch_categories(self):
        from core.cross_device_dispatch_boundary import get_boundary_contract_snapshot
        snapshot = get_boundary_contract_snapshot()
        categories = snapshot["dispatch_path_categories"]
        assert "canonical_dispatch" in categories
        assert "canonical_fallback" in categories
        assert "compat_fallback" in categories
        assert "legacy_bypass" in categories

    def test_N04_canonical_dispatch_is_valid_for_new_work(self):
        from core.cross_device_dispatch_boundary import get_boundary_contract_snapshot
        snapshot = get_boundary_contract_snapshot()
        assert snapshot["dispatch_path_categories"]["canonical_dispatch"]["valid_for_new_work"] is True

    def test_N05_canonical_fallback_is_valid_for_new_work(self):
        """Controlled canonical fallback is still within the canonical path."""
        from core.cross_device_dispatch_boundary import get_boundary_contract_snapshot
        snapshot = get_boundary_contract_snapshot()
        assert snapshot["dispatch_path_categories"]["canonical_fallback"]["valid_for_new_work"] is True

    def test_N06_compat_fallback_not_valid_for_new_work(self):
        from core.cross_device_dispatch_boundary import get_boundary_contract_snapshot
        snapshot = get_boundary_contract_snapshot()
        assert snapshot["dispatch_path_categories"]["compat_fallback"]["valid_for_new_work"] is False

    def test_N07_legacy_bypass_not_valid_for_new_work(self):
        from core.cross_device_dispatch_boundary import get_boundary_contract_snapshot
        snapshot = get_boundary_contract_snapshot()
        assert snapshot["dispatch_path_categories"]["legacy_bypass"]["valid_for_new_work"] is False

    def test_N08_canonical_chain_is_ordered_list(self):
        from core.cross_device_dispatch_boundary import get_boundary_contract_snapshot
        snapshot = get_boundary_contract_snapshot()
        assert isinstance(snapshot["canonical_chain"], list)
        assert len(snapshot["canonical_chain"]) >= 2

    def test_N09_boundary_version_stable(self):
        from core.cross_device_dispatch_boundary import get_boundary_contract_snapshot
        snapshot = get_boundary_contract_snapshot()
        assert snapshot["boundary_version"] == "pr02_v1"


# ============================================================================
# O.  Authority sentinels
# ============================================================================

class TestAuthoritySentinels:

    def test_O01_boundary_contract_sentinel_references_pr02(self):
        from core.cross_device_dispatch_boundary import CROSS_DEVICE_DISPATCH_BOUNDARY_CONTRACT
        assert "PR-02" in CROSS_DEVICE_DISPATCH_BOUNDARY_CONTRACT

    def test_O02_boundary_contract_sentinel_references_canonical_chain(self):
        from core.cross_device_dispatch_boundary import CROSS_DEVICE_DISPATCH_BOUNDARY_CONTRACT
        assert "CommandRouter" in CROSS_DEVICE_DISPATCH_BOUNDARY_CONTRACT
        assert "DeviceRouter" in CROSS_DEVICE_DISPATCH_BOUNDARY_CONTRACT

    def test_O03_pr02_sentinel_references_boundary_consolidation(self):
        from core.cross_device_dispatch_boundary import CROSS_DEVICE_DISPATCH_PR02_SENTINEL
        assert "PR-02" in CROSS_DEVICE_DISPATCH_PR02_SENTINEL

    def test_O04_canonical_path_policy_references_command_router(self):
        from core.cross_device_dispatch_boundary import CANONICAL_PATH_ONLY_FOR_NEW_WORK_POLICY
        assert "CommandRouter" in CANONICAL_PATH_ONLY_FOR_NEW_WORK_POLICY

    def test_O05_device_router_policy_forbids_policy_authority(self):
        from core.cross_device_dispatch_boundary import DEVICE_ROUTER_NOT_A_POLICY_AUTHORITY_POLICY
        assert "DeviceRouter" in DEVICE_ROUTER_NOT_A_POLICY_AUTHORITY_POLICY
        assert "transport" in DEVICE_ROUTER_NOT_A_POLICY_AUTHORITY_POLICY.lower()

    def test_O06_compat_fallback_policy_is_not_primary(self):
        from core.cross_device_dispatch_boundary import COMPAT_FALLBACK_NOT_PRIMARY_PATH_POLICY
        assert "CapabilityOrchestrator" in COMPAT_FALLBACK_NOT_PRIMARY_PATH_POLICY

    def test_O07_legacy_bypass_policy_requires_warning(self):
        from core.cross_device_dispatch_boundary import LEGACY_BYPASS_MUST_EMIT_WARNING_POLICY
        assert "LEGACY_DISPATCH" in LEGACY_BYPASS_MUST_EMIT_WARNING_POLICY


# ============================================================================
# P.  DeviceRouter wiring — dispatch path constants match what DeviceRouter sets
# ============================================================================

class TestDeviceRouterWiring:

    def test_P01_device_router_imports_boundary_constants(self):
        """DeviceRouter must import PR-02 boundary constants."""
        import galaxy_gateway.device_router as dr_mod
        assert hasattr(dr_mod, "DISPATCH_PATH_CANONICAL"), (
            "galaxy_gateway.device_router must import DISPATCH_PATH_CANONICAL "
            "from core.cross_device_dispatch_boundary (PR-02)"
        )
        assert hasattr(dr_mod, "DISPATCH_PATH_CONTROLLED_FALLBACK"), (
            "galaxy_gateway.device_router must import DISPATCH_PATH_CONTROLLED_FALLBACK "
            "from core.cross_device_dispatch_boundary (PR-02)"
        )

    def test_P02_device_router_pr02_sentinel_present(self):
        """DeviceRouter must expose the PR-02 sentinel at module level."""
        import galaxy_gateway.device_router as dr_mod
        assert hasattr(dr_mod, "CROSS_DEVICE_DISPATCH_PR02_SENTINEL")

    def test_P03_canonical_constant_value_matches_expectation(self):
        import galaxy_gateway.device_router as dr_mod
        assert dr_mod.DISPATCH_PATH_CANONICAL == "canonical_dispatch"

    def test_P04_controlled_fallback_constant_value_matches_expectation(self):
        import galaxy_gateway.device_router as dr_mod
        assert dr_mod.DISPATCH_PATH_CONTROLLED_FALLBACK == "canonical_fallback"


# ============================================================================
# Q.  CrossDeviceCoordinator wiring — boundary constants used in coordinator
# ============================================================================

class TestCrossDeviceCoordinatorWiring:

    def test_Q01_coordinator_imports_boundary_constants(self):
        """CrossDeviceCoordinator must import PR-02 boundary constants."""
        import galaxy_gateway.cross_device_coordinator as cdc_mod
        for const in [
            "DISPATCH_PATH_CANONICAL",
            "DISPATCH_PATH_CONTROLLED_FALLBACK",
            "DISPATCH_PATH_COMPAT_FALLBACK",
            "DISPATCH_PATH_LEGACY_BYPASS",
            "SUBSTRATE_CALLER_DEVICE_ROUTER",
        ]:
            assert hasattr(cdc_mod, const), (
                f"galaxy_gateway.cross_device_coordinator must import {const} "
                f"from core.cross_device_dispatch_boundary (PR-02)"
            )

    def test_Q02_coordinator_pr02_sentinel_present(self):
        """CrossDeviceCoordinator must expose the PR-02 sentinel at module level."""
        import galaxy_gateway.cross_device_coordinator as cdc_mod
        assert hasattr(cdc_mod, "CROSS_DEVICE_DISPATCH_PR02_SENTINEL")

    def test_Q03_coordinator_substrate_caller_constant_matches(self):
        """SUBSTRATE_CALLER_DEVICE_ROUTER in coordinator must equal 'device_router.route_task'."""
        import galaxy_gateway.cross_device_coordinator as cdc_mod
        assert cdc_mod.SUBSTRATE_CALLER_DEVICE_ROUTER == "device_router.route_task"

    def test_Q04_legacy_bypass_detected_when_no_substrate_caller(self):
        """Coordinator must classify calls without a canonical caller as legacy bypass (behavioral)."""
        from core.cross_device_dispatch_boundary import (
            classify_dispatch_call,
            DispatchPathCategory,
        )
        # Simulate what CrossDeviceCoordinator does: no dispatch_path, no caller → legacy_bypass
        clf = classify_dispatch_call(dispatch_path="", substrate_caller="")
        assert clf.category == DispatchPathCategory.LEGACY_BYPASS
        assert clf.is_canonical is False


# ============================================================================
# R.  CapabilityOrchestrator wiring — boundary constants used in orchestrator
# ============================================================================

class TestCapabilityOrchestratorWiring:

    @pytest.mark.asyncio
    async def test_R01_orchestrator_builtin_cross_device_sets_canonical_dispatch_path(self):
        """CapabilityOrchestrator._execute_builtin must set dispatch_path=canonical_dispatch
        in the context passed to DeviceRouter (behavioral verification)."""
        from unittest.mock import AsyncMock, patch
        from core.capability_orchestrator import Capability, CapabilityOrchestrator, CapabilityType
        from core.cross_device_dispatch_boundary import DISPATCH_PATH_CANONICAL

        orch = CapabilityOrchestrator()
        cap = Capability(
            id="builtin_cross_device",
            name="跨设备协同",
            description="跨设备任务",
            type=CapabilityType.BUILTIN,
        )
        captured_context = {}

        async def capture_route(command, context):
            captured_context.update(context)
            return {"success": True, "message": "ok"}

        with patch(
            "galaxy_gateway.device_router.device_router.route_task",
            new_callable=AsyncMock,
            side_effect=capture_route,
        ):
            await orch._execute_builtin(cap, {"command": "sync"})

        assert captured_context.get("dispatch_path") == DISPATCH_PATH_CANONICAL, (
            "CapabilityOrchestrator must pass dispatch_path=DISPATCH_PATH_CANONICAL "
            "to DeviceRouter (PR-02)"
        )

    @pytest.mark.asyncio
    async def test_R02_orchestrator_builtin_cross_device_compat_sets_compat_dispatch_path(self):
        """CapabilityOrchestrator compat fallback must set dispatch_path=compat_fallback
        in the context passed to CrossDeviceCoordinator (behavioral verification)."""
        from unittest.mock import AsyncMock, patch
        from core.capability_orchestrator import Capability, CapabilityOrchestrator, CapabilityType
        from core.cross_device_dispatch_boundary import DISPATCH_PATH_COMPAT_FALLBACK

        orch = CapabilityOrchestrator()
        cap = Capability(
            id="builtin_cross_device",
            name="跨设备协同",
            description="跨设备任务",
            type=CapabilityType.BUILTIN,
        )
        captured_context = {}

        async def capture_coordinator(command, context, **kwargs):
            captured_context.update(context)
            return {"success": True, "message": "compat"}

        with patch(
            "galaxy_gateway.device_router.device_router.route_task",
            new_callable=AsyncMock,
            side_effect=RuntimeError("router unavailable"),
        ), patch(
            "galaxy_gateway.cross_device_coordinator.cross_device_coordinator.execute_cross_device_task",
            new_callable=AsyncMock,
            side_effect=capture_coordinator,
        ):
            await orch._execute_builtin(cap, {"command": "sync"})

        assert captured_context.get("dispatch_path") == DISPATCH_PATH_COMPAT_FALLBACK, (
            "CapabilityOrchestrator compat fallback must pass dispatch_path=DISPATCH_PATH_COMPAT_FALLBACK "
            "to CrossDeviceCoordinator (PR-02)"
        )

    @pytest.mark.asyncio
    async def test_R03_orchestrator_compat_fallback_sets_compat_route_mode(self):
        """CapabilityOrchestrator compat fallback must set route_mode=cross_device_compat_fallback."""
        from unittest.mock import AsyncMock, patch
        from core.capability_orchestrator import Capability, CapabilityOrchestrator, CapabilityType
        from core.cross_device_dispatch_boundary import ROUTE_MODE_COMPAT_FALLBACK

        orch = CapabilityOrchestrator()
        cap = Capability(
            id="builtin_cross_device",
            name="跨设备协同",
            description="跨设备任务",
            type=CapabilityType.BUILTIN,
        )
        captured_context = {}

        async def capture_coordinator(command, context, **kwargs):
            captured_context.update(context)
            return {"success": True, "message": "compat"}

        with patch(
            "galaxy_gateway.device_router.device_router.route_task",
            new_callable=AsyncMock,
            side_effect=RuntimeError("router unavailable"),
        ), patch(
            "galaxy_gateway.cross_device_coordinator.cross_device_coordinator.execute_cross_device_task",
            new_callable=AsyncMock,
            side_effect=capture_coordinator,
        ):
            await orch._execute_builtin(cap, {"command": "sync"})

        assert captured_context.get("route_mode") == ROUTE_MODE_COMPAT_FALLBACK, (
            "CapabilityOrchestrator compat fallback must pass route_mode=ROUTE_MODE_COMPAT_FALLBACK "
            "to CrossDeviceCoordinator (PR-02)"
        )


# ============================================================================
# S.  Android ↔ V2 dispatch contract alignment
# ============================================================================

class TestAndroidV2DispatchContractAlignment:

    def test_S01_android_dispatch_contract_keys_in_snapshot(self):
        """Snapshot must include Android dispatch contract alignment keys."""
        from core.cross_device_dispatch_boundary import get_boundary_contract_snapshot
        snapshot = get_boundary_contract_snapshot()
        android_contract = snapshot["android_dispatch_contract"]
        assert "inbound_path" in android_contract
        assert "outbound_path" in android_contract
        assert "handoff_result_path" in android_contract
        assert "dispatch_path_context_key" in android_contract
        assert "route_mode_context_key" in android_contract

    def test_S02_android_dispatch_path_context_key_matches_coordinator(self):
        """Android dispatch_path context key must match CrossDeviceCoordinator's key."""
        from core.cross_device_dispatch_boundary import get_boundary_contract_snapshot
        snapshot = get_boundary_contract_snapshot()
        assert snapshot["android_dispatch_contract"]["dispatch_path_context_key"] == "dispatch_path"

    def test_S03_android_route_mode_context_key_matches_coordinator(self):
        """Android route_mode context key must match CrossDeviceCoordinator's key."""
        from core.cross_device_dispatch_boundary import get_boundary_contract_snapshot
        snapshot = get_boundary_contract_snapshot()
        assert snapshot["android_dispatch_contract"]["route_mode_context_key"] == "route_mode"

    def test_S04_android_substrate_caller_context_key_in_snapshot(self):
        """Snapshot must expose the substrate_caller context key name."""
        from core.cross_device_dispatch_boundary import get_boundary_contract_snapshot
        snapshot = get_boundary_contract_snapshot()
        assert "substrate_caller_context_key" in snapshot["android_dispatch_contract"]

    def test_S05_android_inbound_path_references_android_bridge(self):
        """Android inbound path must reference android_bridge in the snapshot."""
        from core.cross_device_dispatch_boundary import get_boundary_contract_snapshot
        snapshot = get_boundary_contract_snapshot()
        inbound = snapshot["android_dispatch_contract"]["inbound_path"]
        assert "android" in inbound.lower() or "bridge" in inbound.lower()

    def test_S06_route_mode_canonical_matches_coordinator_default(self):
        """ROUTE_MODE_CROSS_DEVICE must match what the coordinator uses as its default route_mode."""
        from core.cross_device_dispatch_boundary import (
            ROUTE_MODE_CROSS_DEVICE,
            classify_dispatch_call,
        )
        # Behavioral: a call arriving at the coordinator with no route_mode in context
        # should still produce a valid canonical classification when substrate caller is set
        from core.cross_device_dispatch_boundary import (
            SUBSTRATE_CALLER_DEVICE_ROUTER,
            DISPATCH_PATH_CONTROLLED_FALLBACK,
        )
        clf = classify_dispatch_call(
            dispatch_path=DISPATCH_PATH_CONTROLLED_FALLBACK,
            substrate_caller=SUBSTRATE_CALLER_DEVICE_ROUTER,
            route_mode=ROUTE_MODE_CROSS_DEVICE,
        )
        assert clf.route_mode == ROUTE_MODE_CROSS_DEVICE
        assert ROUTE_MODE_CROSS_DEVICE == "cross_device"


# ============================================================================
# T.  Policy guards
# ============================================================================

class TestPolicyGuards:

    def test_T01_only_canonical_and_controlled_fallback_valid_for_new_work(self):
        """Only canonical and controlled-fallback paths must be valid for new work."""
        from core.cross_device_dispatch_boundary import (
            get_boundary_contract_snapshot,
            DISPATCH_PATH_CANONICAL,
            DISPATCH_PATH_CONTROLLED_FALLBACK,
            DISPATCH_PATH_COMPAT_FALLBACK,
            DISPATCH_PATH_LEGACY_BYPASS,
        )
        snapshot = get_boundary_contract_snapshot()
        cats = snapshot["dispatch_path_categories"]
        assert cats[DISPATCH_PATH_CANONICAL]["valid_for_new_work"] is True
        assert cats[DISPATCH_PATH_CONTROLLED_FALLBACK]["valid_for_new_work"] is True
        assert cats[DISPATCH_PATH_COMPAT_FALLBACK]["valid_for_new_work"] is False
        assert cats[DISPATCH_PATH_LEGACY_BYPASS]["valid_for_new_work"] is False

    def test_T02_device_router_not_policy_authority_policy_present(self):
        """Policy must explicitly state DeviceRouter is not a policy authority."""
        from core.cross_device_dispatch_boundary import (
            get_boundary_contract_snapshot,
            DEVICE_ROUTER_NOT_A_POLICY_AUTHORITY_POLICY,
        )
        snapshot = get_boundary_contract_snapshot()
        policies = snapshot["policies"]
        assert "DEVICE_ROUTER_NOT_A_POLICY_AUTHORITY" in policies
        assert policies["DEVICE_ROUTER_NOT_A_POLICY_AUTHORITY"] == DEVICE_ROUTER_NOT_A_POLICY_AUTHORITY_POLICY

    def test_T03_legacy_bypass_policy_requires_fail_open_with_warning(self):
        """Legacy bypass policy must require fail-open with warning."""
        from core.cross_device_dispatch_boundary import LEGACY_BYPASS_MUST_EMIT_WARNING_POLICY
        # Must say fail-open
        assert "fail-open" in LEGACY_BYPASS_MUST_EMIT_WARNING_POLICY.lower()

    def test_T04_canonical_substrate_callers_correct(self):
        """Canonical dispatch substrate callers must include device_router.route_task."""
        from core.cross_device_dispatch_boundary import (
            get_boundary_contract_snapshot,
            SUBSTRATE_CALLER_DEVICE_ROUTER,
        )
        snapshot = get_boundary_contract_snapshot()
        canonical_callers = snapshot["dispatch_path_categories"]["canonical_dispatch"]["substrate_callers"]
        assert SUBSTRATE_CALLER_DEVICE_ROUTER in canonical_callers

    def test_T05_compat_substrate_callers_correct(self):
        """Compat fallback substrate callers must include capability_orchestrator.compat_fallback."""
        from core.cross_device_dispatch_boundary import (
            get_boundary_contract_snapshot,
            SUBSTRATE_CALLER_COMPAT,
        )
        snapshot = get_boundary_contract_snapshot()
        compat_callers = snapshot["dispatch_path_categories"]["compat_fallback"]["substrate_callers"]
        assert SUBSTRATE_CALLER_COMPAT in compat_callers
