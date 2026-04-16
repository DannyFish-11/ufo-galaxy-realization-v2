#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_pr7_canonical_task_dispatch_chain.py
====================================================
Tests for PR-7 (12-PR governance plan, MAIN repo side):
Canonical Task Dispatch and Delegated Execution Chain Definition.

This test suite verifies that:

1.  Module authority sentinels are present and non-empty.
2.  PR-7 sentinel is present and non-empty.
3.  All six policy sentinels are present and non-empty.
4.  DispatchPathKind enum contains all six expected values.
5.  DispatchPathRole enum contains all expected role values.
6.  DispatchResultOwner enum contains all expected owner values.
7.  get_dispatch_path_catalogue() returns exactly six records.
8.  get_dispatch_path_catalogue() returns DispatchChainRecord instances.
9.  Each DispatchChainRecord has non-empty path_kind, role, result_owner.
10. Each DispatchChainRecord has a non-empty primary_module string.
11. Each DispatchChainRecord has a non-empty description string.
12. Each DispatchChainRecord has a non-empty policy_sentinel string.
13. classify_dispatch_path(primary_local) returns the correct record.
14. classify_dispatch_path(remote_handoff) returns the correct record.
15. classify_dispatch_path(fallback_local) returns the correct record.
16. classify_dispatch_path(staged_mesh) returns the correct record.
17. classify_dispatch_path(android_inbound) returns the correct record.
18. classify_dispatch_path(blocked) returns the correct record.
19. is_canonical_path(primary_local) is True.
20. is_canonical_path(remote_handoff) is True.
21. is_canonical_path(fallback_local) is False.
22. is_canonical_path(staged_mesh) is False.
23. is_canonical_path(android_inbound) is False.
24. is_canonical_path(blocked) is False.
25. is_fallback_path(fallback_local) is True.
26. is_fallback_path(primary_local) is False.
27. is_android_inbound_path(android_inbound) is True.
28. is_android_inbound_path(primary_local) is False.
29. get_primary_dispatch_path() returns primary_local record.
30. get_primary_dispatch_path() has role == canonical.
31. build_dispatch_chain_snapshot() returns DispatchChainSnapshot.
32. build_dispatch_chain_snapshot() path_count == 6.
33. build_dispatch_chain_snapshot() canonical_path_count == 2.
34. build_dispatch_chain_snapshot() fallback_path_count == 1.
35. build_dispatch_chain_snapshot() primary_dispatch_path == 'primary_local'.
36. build_dispatch_chain_snapshot() authority sentinel is non-empty.
37. build_dispatch_chain_snapshot().to_dict() is serialisable.
38. DispatchChainRecord.to_dict() produces stable keys.
39. Projection sentinel importable.
40. Projection sentinel is not UNAVAILABLE.
41. android_inbound record references android_delegated_signal_ingress module.
42. android_inbound record has reconciliation_module set.
43. fallback_local record primary_module is source_dispatch_orchestrator.
44. staged_mesh record primary_module is mesh_session_coordinator.
45. blocked record result_owner is governance.

All tests are self-contained (no live servers, no real devices).
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.canonical_task_dispatch_chain import (
        CANONICAL_TASK_DISPATCH_CHAIN_IS_AUTHORITY,
        CANONICAL_TASK_DISPATCH_CHAIN_PR7_SENTINEL,
        DISPATCH_CHAIN_PRIMARY_PATH_IS_LOCAL_POLICY,
        DISPATCH_CHAIN_REMOTE_HANDOFF_BLOCKS_LOCAL_POLICY,
        DISPATCH_CHAIN_FALLBACK_IS_DISTINGUISHABLE_POLICY,
        DISPATCH_CHAIN_ANDROID_INBOUND_IS_SAME_SYSTEM_POLICY,
        DISPATCH_CHAIN_STAGED_MESH_IS_COORDINATION_ONLY_POLICY,
        DISPATCH_CHAIN_BLOCKED_PATH_IS_FINAL_POLICY,
        DispatchPathKind,
        DispatchPathRole,
        DispatchResultOwner,
        DispatchChainRecord,
        DispatchChainSnapshot,
        get_dispatch_path_catalogue,
        classify_dispatch_path,
        is_canonical_path,
        is_fallback_path,
        is_android_inbound_path,
        get_primary_dispatch_path,
        build_dispatch_chain_snapshot,
    )

    _MODULE_AVAILABLE = True
except ImportError:
    _MODULE_AVAILABLE = False

try:
    from core.routes.projection import CANONICAL_TASK_DISPATCH_CHAIN_ALIGNED_PR7

    _PROJECTION_AVAILABLE = True
except ImportError:
    _PROJECTION_AVAILABLE = False

_SKIP_MODULE = pytest.mark.skipif(
    not _MODULE_AVAILABLE, reason="core.canonical_task_dispatch_chain not available"
)
_SKIP_PROJECTION = pytest.mark.skipif(
    not _PROJECTION_AVAILABLE, reason="projection sentinel not available"
)


# ---------------------------------------------------------------------------
# Group A — Authority sentinels
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupA_AuthoritySentinels:
    """Module authority and PR sentinels are present and non-empty."""

    def test_a1_authority_sentinel_present(self):
        assert CANONICAL_TASK_DISPATCH_CHAIN_IS_AUTHORITY

    def test_a2_authority_sentinel_is_string(self):
        assert isinstance(CANONICAL_TASK_DISPATCH_CHAIN_IS_AUTHORITY, str)

    def test_a3_pr7_sentinel_present(self):
        assert CANONICAL_TASK_DISPATCH_CHAIN_PR7_SENTINEL

    def test_a4_pr7_sentinel_is_string(self):
        assert isinstance(CANONICAL_TASK_DISPATCH_CHAIN_PR7_SENTINEL, str)

    def test_a5_sentinel_contains_pr7_keyword(self):
        assert "PR7" in CANONICAL_TASK_DISPATCH_CHAIN_PR7_SENTINEL


# ---------------------------------------------------------------------------
# Group B — Policy sentinels
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupB_PolicySentinels:
    """All six policy sentinels are present, non-empty, and are strings."""

    def test_b1_primary_path_policy_present(self):
        assert DISPATCH_CHAIN_PRIMARY_PATH_IS_LOCAL_POLICY

    def test_b2_remote_handoff_policy_present(self):
        assert DISPATCH_CHAIN_REMOTE_HANDOFF_BLOCKS_LOCAL_POLICY

    def test_b3_fallback_distinguishable_policy_present(self):
        assert DISPATCH_CHAIN_FALLBACK_IS_DISTINGUISHABLE_POLICY

    def test_b4_android_inbound_policy_present(self):
        assert DISPATCH_CHAIN_ANDROID_INBOUND_IS_SAME_SYSTEM_POLICY

    def test_b5_staged_mesh_policy_present(self):
        assert DISPATCH_CHAIN_STAGED_MESH_IS_COORDINATION_ONLY_POLICY

    def test_b6_blocked_path_policy_present(self):
        assert DISPATCH_CHAIN_BLOCKED_PATH_IS_FINAL_POLICY

    def test_b7_all_policies_are_strings(self):
        for sentinel in (
            DISPATCH_CHAIN_PRIMARY_PATH_IS_LOCAL_POLICY,
            DISPATCH_CHAIN_REMOTE_HANDOFF_BLOCKS_LOCAL_POLICY,
            DISPATCH_CHAIN_FALLBACK_IS_DISTINGUISHABLE_POLICY,
            DISPATCH_CHAIN_ANDROID_INBOUND_IS_SAME_SYSTEM_POLICY,
            DISPATCH_CHAIN_STAGED_MESH_IS_COORDINATION_ONLY_POLICY,
            DISPATCH_CHAIN_BLOCKED_PATH_IS_FINAL_POLICY,
        ):
            assert isinstance(sentinel, str)

    def test_b8_all_policies_start_with_dispatch_chain_policy(self):
        for sentinel in (
            DISPATCH_CHAIN_PRIMARY_PATH_IS_LOCAL_POLICY,
            DISPATCH_CHAIN_REMOTE_HANDOFF_BLOCKS_LOCAL_POLICY,
            DISPATCH_CHAIN_FALLBACK_IS_DISTINGUISHABLE_POLICY,
            DISPATCH_CHAIN_ANDROID_INBOUND_IS_SAME_SYSTEM_POLICY,
            DISPATCH_CHAIN_STAGED_MESH_IS_COORDINATION_ONLY_POLICY,
            DISPATCH_CHAIN_BLOCKED_PATH_IS_FINAL_POLICY,
        ):
            assert sentinel.startswith("DISPATCH_CHAIN_POLICY::")


# ---------------------------------------------------------------------------
# Group C — Enum completeness
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupC_EnumCompleteness:
    """All enum variants are present and have expected string values."""

    def test_c1_dispatch_path_kind_has_six_values(self):
        assert len(DispatchPathKind) == 6

    def test_c2_path_kind_primary_local(self):
        assert DispatchPathKind.primary_local.value == "primary_local"

    def test_c3_path_kind_remote_handoff(self):
        assert DispatchPathKind.remote_handoff.value == "remote_handoff"

    def test_c4_path_kind_fallback_local(self):
        assert DispatchPathKind.fallback_local.value == "fallback_local"

    def test_c5_path_kind_staged_mesh(self):
        assert DispatchPathKind.staged_mesh.value == "staged_mesh"

    def test_c6_path_kind_android_inbound(self):
        assert DispatchPathKind.android_inbound.value == "android_inbound"

    def test_c7_path_kind_blocked(self):
        assert DispatchPathKind.blocked.value == "blocked"

    def test_c8_dispatch_path_role_has_five_values(self):
        assert len(DispatchPathRole) == 5

    def test_c9_dispatch_result_owner_has_five_values(self):
        assert len(DispatchResultOwner) == 5

    def test_c10_dispatch_result_owner_source_present(self):
        assert DispatchResultOwner.source.value == "source"

    def test_c11_dispatch_result_owner_target_present(self):
        assert DispatchResultOwner.target.value == "target"

    def test_c12_dispatch_result_owner_reconciled_present(self):
        assert DispatchResultOwner.reconciled.value == "reconciled"

    def test_c13_dispatch_result_owner_coordinator_present(self):
        assert DispatchResultOwner.coordinator.value == "coordinator"

    def test_c14_dispatch_result_owner_governance_present(self):
        assert DispatchResultOwner.governance.value == "governance"


# ---------------------------------------------------------------------------
# Group D — Catalogue completeness
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupD_CatalogueCompleteness:
    """get_dispatch_path_catalogue() returns all six records."""

    def test_d1_catalogue_has_six_records(self):
        catalogue = get_dispatch_path_catalogue()
        assert len(catalogue) == 6

    def test_d2_catalogue_returns_dispatch_chain_records(self):
        for record in get_dispatch_path_catalogue():
            assert isinstance(record, DispatchChainRecord)

    def test_d3_catalogue_covers_all_path_kinds(self):
        kinds = {r.path_kind for r in get_dispatch_path_catalogue()}
        assert kinds == set(DispatchPathKind)

    def test_d4_each_record_has_non_empty_primary_module(self):
        for record in get_dispatch_path_catalogue():
            assert record.primary_module, f"{record.path_kind} has empty primary_module"

    def test_d5_each_record_has_non_empty_description(self):
        for record in get_dispatch_path_catalogue():
            assert record.description, f"{record.path_kind} has empty description"

    def test_d6_each_record_has_non_empty_policy_sentinel(self):
        for record in get_dispatch_path_catalogue():
            assert record.policy_sentinel, f"{record.path_kind} has empty policy_sentinel"

    def test_d7_each_record_has_non_empty_signal_modules_list(self):
        for record in get_dispatch_path_catalogue():
            assert isinstance(record.signal_modules, list)
            assert len(record.signal_modules) > 0, (
                f"{record.path_kind} has empty signal_modules"
            )

    def test_d8_catalogue_returns_new_list_each_call(self):
        c1 = get_dispatch_path_catalogue()
        c2 = get_dispatch_path_catalogue()
        assert c1 is not c2


# ---------------------------------------------------------------------------
# Group E — classify_dispatch_path
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupE_ClassifyDispatchPath:
    """classify_dispatch_path() returns the correct record for each path kind."""

    def test_e1_classify_primary_local(self):
        record = classify_dispatch_path(DispatchPathKind.primary_local)
        assert record.path_kind == DispatchPathKind.primary_local

    def test_e2_classify_remote_handoff(self):
        record = classify_dispatch_path(DispatchPathKind.remote_handoff)
        assert record.path_kind == DispatchPathKind.remote_handoff

    def test_e3_classify_fallback_local(self):
        record = classify_dispatch_path(DispatchPathKind.fallback_local)
        assert record.path_kind == DispatchPathKind.fallback_local

    def test_e4_classify_staged_mesh(self):
        record = classify_dispatch_path(DispatchPathKind.staged_mesh)
        assert record.path_kind == DispatchPathKind.staged_mesh

    def test_e5_classify_android_inbound(self):
        record = classify_dispatch_path(DispatchPathKind.android_inbound)
        assert record.path_kind == DispatchPathKind.android_inbound

    def test_e6_classify_blocked(self):
        record = classify_dispatch_path(DispatchPathKind.blocked)
        assert record.path_kind == DispatchPathKind.blocked


# ---------------------------------------------------------------------------
# Group F — Path classification predicates
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupF_PathPredicates:
    """is_canonical_path, is_fallback_path, is_android_inbound_path."""

    def test_f1_primary_local_is_canonical(self):
        assert is_canonical_path(DispatchPathKind.primary_local) is True

    def test_f2_remote_handoff_is_canonical(self):
        assert is_canonical_path(DispatchPathKind.remote_handoff) is True

    def test_f3_fallback_local_is_not_canonical(self):
        assert is_canonical_path(DispatchPathKind.fallback_local) is False

    def test_f4_staged_mesh_is_not_canonical(self):
        assert is_canonical_path(DispatchPathKind.staged_mesh) is False

    def test_f5_android_inbound_is_not_canonical(self):
        assert is_canonical_path(DispatchPathKind.android_inbound) is False

    def test_f6_blocked_is_not_canonical(self):
        assert is_canonical_path(DispatchPathKind.blocked) is False

    def test_f7_fallback_local_is_fallback(self):
        assert is_fallback_path(DispatchPathKind.fallback_local) is True

    def test_f8_primary_local_is_not_fallback(self):
        assert is_fallback_path(DispatchPathKind.primary_local) is False

    def test_f9_remote_handoff_is_not_fallback(self):
        assert is_fallback_path(DispatchPathKind.remote_handoff) is False

    def test_f10_android_inbound_is_android_inbound(self):
        assert is_android_inbound_path(DispatchPathKind.android_inbound) is True

    def test_f11_primary_local_is_not_android_inbound(self):
        assert is_android_inbound_path(DispatchPathKind.primary_local) is False

    def test_f12_staged_mesh_is_not_android_inbound(self):
        assert is_android_inbound_path(DispatchPathKind.staged_mesh) is False


# ---------------------------------------------------------------------------
# Group G — get_primary_dispatch_path
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupG_PrimaryDispatchPath:
    """get_primary_dispatch_path() returns the primary_local record."""

    def test_g1_returns_dispatch_chain_record(self):
        record = get_primary_dispatch_path()
        assert isinstance(record, DispatchChainRecord)

    def test_g2_path_kind_is_primary_local(self):
        record = get_primary_dispatch_path()
        assert record.path_kind == DispatchPathKind.primary_local

    def test_g3_role_is_canonical(self):
        record = get_primary_dispatch_path()
        assert record.role == DispatchPathRole.canonical

    def test_g4_result_owner_is_source(self):
        record = get_primary_dispatch_path()
        assert record.result_owner == DispatchResultOwner.source

    def test_g5_primary_module_is_openclawd(self):
        record = get_primary_dispatch_path()
        assert "openclawd" in record.primary_module.lower()


# ---------------------------------------------------------------------------
# Group H — build_dispatch_chain_snapshot
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupH_DispatchChainSnapshot:
    """build_dispatch_chain_snapshot() returns a correct DispatchChainSnapshot."""

    def test_h1_returns_dispatch_chain_snapshot(self):
        snapshot = build_dispatch_chain_snapshot()
        assert isinstance(snapshot, DispatchChainSnapshot)

    def test_h2_path_count_is_six(self):
        snapshot = build_dispatch_chain_snapshot()
        assert snapshot.path_count == 6

    def test_h3_canonical_path_count_is_two(self):
        snapshot = build_dispatch_chain_snapshot()
        assert snapshot.canonical_path_count == 2

    def test_h4_fallback_path_count_is_one(self):
        snapshot = build_dispatch_chain_snapshot()
        assert snapshot.fallback_path_count == 1

    def test_h5_primary_dispatch_path_is_primary_local(self):
        snapshot = build_dispatch_chain_snapshot()
        assert snapshot.primary_dispatch_path == "primary_local"

    def test_h6_authority_is_non_empty(self):
        snapshot = build_dispatch_chain_snapshot()
        assert snapshot.authority

    def test_h7_sentinel_is_non_empty(self):
        snapshot = build_dispatch_chain_snapshot()
        assert snapshot.sentinel

    def test_h8_paths_list_has_six_entries(self):
        snapshot = build_dispatch_chain_snapshot()
        assert len(snapshot.paths) == 6

    def test_h9_generated_at_is_positive_float(self):
        snapshot = build_dispatch_chain_snapshot()
        assert isinstance(snapshot.generated_at, float)
        assert snapshot.generated_at > 0

    def test_h10_to_dict_returns_dict(self):
        snapshot = build_dispatch_chain_snapshot()
        d = snapshot.to_dict()
        assert isinstance(d, dict)

    def test_h11_to_dict_has_required_keys(self):
        d = build_dispatch_chain_snapshot().to_dict()
        for key in (
            "generated_at",
            "authority",
            "sentinel",
            "path_count",
            "canonical_path_count",
            "fallback_path_count",
            "paths",
            "primary_dispatch_path",
        ):
            assert key in d, f"Missing key: {key}"

    def test_h12_each_path_entry_has_required_keys(self):
        snapshot = build_dispatch_chain_snapshot()
        for path_dict in snapshot.paths:
            for key in (
                "path_kind",
                "role",
                "result_owner",
                "primary_module",
                "signal_modules",
                "reconciliation_module",
                "description",
                "policy_sentinel",
            ):
                assert key in path_dict, f"Path entry missing key: {key}"


# ---------------------------------------------------------------------------
# Group I — DispatchChainRecord serialisation
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupI_RecordSerialisation:
    """DispatchChainRecord.to_dict() produces stable keys."""

    def test_i1_to_dict_returns_dict(self):
        record = get_primary_dispatch_path()
        d = record.to_dict()
        assert isinstance(d, dict)

    def test_i2_to_dict_has_all_required_keys(self):
        record = get_primary_dispatch_path()
        d = record.to_dict()
        for key in (
            "path_kind",
            "role",
            "result_owner",
            "primary_module",
            "signal_modules",
            "reconciliation_module",
            "description",
            "policy_sentinel",
        ):
            assert key in d

    def test_i3_to_dict_path_kind_is_string(self):
        record = get_primary_dispatch_path()
        d = record.to_dict()
        assert isinstance(d["path_kind"], str)

    def test_i4_to_dict_signal_modules_is_list(self):
        record = get_primary_dispatch_path()
        d = record.to_dict()
        assert isinstance(d["signal_modules"], list)


# ---------------------------------------------------------------------------
# Group J — Android inbound path governance
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupJ_AndroidInboundPathGovernance:
    """Android inbound path is governed correctly inside the execution model."""

    def test_j1_android_inbound_role_is_android_delegated(self):
        record = classify_dispatch_path(DispatchPathKind.android_inbound)
        assert record.role == DispatchPathRole.android_delegated

    def test_j2_android_inbound_result_owner_is_reconciled(self):
        record = classify_dispatch_path(DispatchPathKind.android_inbound)
        assert record.result_owner == DispatchResultOwner.reconciled

    def test_j3_android_inbound_primary_module_contains_delegated_signal_ingress(self):
        record = classify_dispatch_path(DispatchPathKind.android_inbound)
        assert "android_delegated_signal_ingress" in record.primary_module

    def test_j4_android_inbound_has_reconciliation_module(self):
        record = classify_dispatch_path(DispatchPathKind.android_inbound)
        assert record.reconciliation_module is not None
        assert "reconciler" in record.reconciliation_module

    def test_j5_android_inbound_signal_modules_includes_gateway_handler(self):
        record = classify_dispatch_path(DispatchPathKind.android_inbound)
        assert any("galaxy_gateway" in m for m in record.signal_modules)

    def test_j6_android_policy_mentions_same_system(self):
        assert "same" in DISPATCH_CHAIN_ANDROID_INBOUND_IS_SAME_SYSTEM_POLICY.lower()


# ---------------------------------------------------------------------------
# Group K — Specific path governance assertions
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupK_PathGovernanceAssertions:
    """Key governance assertions for each dispatch path."""

    def test_k1_fallback_local_primary_module_is_source_dispatch_orchestrator(self):
        record = classify_dispatch_path(DispatchPathKind.fallback_local)
        assert "source_dispatch_orchestrator" in record.primary_module

    def test_k2_staged_mesh_primary_module_is_mesh_session_coordinator(self):
        record = classify_dispatch_path(DispatchPathKind.staged_mesh)
        assert "mesh_session_coordinator" in record.primary_module

    def test_k3_blocked_result_owner_is_governance(self):
        record = classify_dispatch_path(DispatchPathKind.blocked)
        assert record.result_owner == DispatchResultOwner.governance

    def test_k4_blocked_reconciliation_module_is_none(self):
        record = classify_dispatch_path(DispatchPathKind.blocked)
        assert record.reconciliation_module is None

    def test_k5_remote_handoff_result_owner_is_target(self):
        record = classify_dispatch_path(DispatchPathKind.remote_handoff)
        assert record.result_owner == DispatchResultOwner.target

    def test_k6_remote_handoff_primary_module_is_source_dispatch_orchestrator(self):
        record = classify_dispatch_path(DispatchPathKind.remote_handoff)
        assert "source_dispatch_orchestrator" in record.primary_module

    def test_k7_staged_mesh_result_owner_is_coordinator(self):
        record = classify_dispatch_path(DispatchPathKind.staged_mesh)
        assert record.result_owner == DispatchResultOwner.coordinator

    def test_k8_staged_mesh_has_reconciliation_module(self):
        record = classify_dispatch_path(DispatchPathKind.staged_mesh)
        assert record.reconciliation_module is not None

    def test_k9_fallback_local_result_owner_is_source(self):
        record = classify_dispatch_path(DispatchPathKind.fallback_local)
        assert record.result_owner == DispatchResultOwner.source


# ---------------------------------------------------------------------------
# Group L — Projection sentinel
# ---------------------------------------------------------------------------


@_SKIP_PROJECTION
class TestGroupL_ProjectionSentinel:
    """Projection alignment sentinel is importable and not UNAVAILABLE."""

    def test_l1_projection_sentinel_importable(self):
        assert CANONICAL_TASK_DISPATCH_CHAIN_ALIGNED_PR7 is not None

    def test_l2_projection_sentinel_not_unavailable(self):
        assert "UNAVAILABLE" not in CANONICAL_TASK_DISPATCH_CHAIN_ALIGNED_PR7

    def test_l2b_projection_sentinel_contains_expected_content(self):
        assert "canonical task dispatch chain" in CANONICAL_TASK_DISPATCH_CHAIN_ALIGNED_PR7.lower()

    def test_l3_projection_sentinel_is_string(self):
        assert isinstance(CANONICAL_TASK_DISPATCH_CHAIN_ALIGNED_PR7, str)

    def test_l4_projection_sentinel_contains_pr7(self):
        assert "PR7" in CANONICAL_TASK_DISPATCH_CHAIN_ALIGNED_PR7
