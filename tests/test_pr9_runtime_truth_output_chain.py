#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_pr9_runtime_truth_output_chain.py
=================================================
PR-9 (realization-v2 convergence plan): runtime-truth to outward-truth
compilation and output chain tests.

Coverage
--------
A.  Module importable; authority and PR-9 sentinel are non-empty strings.
B.  All four policy sentinels are non-empty strings with expected keywords.
C.  TruthOutputStage enum has exactly three members:
    INTERNAL_COMPILER, OUTWARD_ASSEMBLER, PROJECTION_SURFACE.
D.  build_output_chain_catalog() returns exactly 3 records in stage-index order.
E.  Stage 1 record: correct module, function, output_type, may_call_stages.
F.  Stage 2 record: correct module, function, output_type, may_call_stages.
G.  Stage 3 record: correct module, function, output_type, may_call_stages.
H.  find_stage_ordering_violations() returns an empty list (chain is clean).
I.  classify_output_stage() returns correct stage values for known surfaces.
J.  classify_output_stage() returns "unknown" for unrecognised surface.
K.  get_stage_record() returns the correct record for each stage.
L.  get_stage_record() raises KeyError for an invalid stage value.
M.  build_output_chain_snapshot() returns an OutputChainSnapshot.
N.  Snapshot has 3 stages, 4 policies, chain_is_clean=True, ordering_violations=[].
O.  Snapshot.to_dict() includes expected top-level keys.
P.  Each ChainStageRecord.to_dict() includes all required keys.
Q.  No stage may_call_stages includes its own or a downstream index.
R.  Every stage has a non-empty governance_constraint string.
S.  Every stage has at least one known_surface_id.
T.  Stage 1 known_surface_ids include the canonical compiler module path.
U.  Stage 2 known_surface_ids include the canonical outward assembler module path.
V.  Stage 3 known_surface_ids include the canonical projection route surface.
W.  Projection alignment sentinel importable and not UNAVAILABLE (fastapi guard).
X.  Sentinel strings contain expected keywords.
"""

from __future__ import annotations

import importlib.util
from typing import Any, Dict, List

import pytest

from core.runtime_truth_output_chain import (
    NO_REPEATED_STAGE_COMPILATION_WITHIN_REQUEST_POLICY,
    OUTWARD_ASSEMBLER_IS_SOLE_OUTPUT_AUTHORITY_POLICY,
    RUNTIME_TRUTH_OUTPUT_CHAIN_IS_AUTHORITY,
    RUNTIME_TRUTH_OUTPUT_CHAIN_PR9_SENTINEL,
    STAGE_ORDERING_IS_UNIDIRECTIONAL_POLICY,
    STAGE_ROLE_INFLATION_IS_PROHIBITED_POLICY,
    ChainStageRecord,
    OutputChainSnapshot,
    TruthOutputStage,
    build_output_chain_catalog,
    build_output_chain_snapshot,
    classify_output_stage,
    find_stage_ordering_violations,
    get_stage_record,
)

_HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None


# ---------------------------------------------------------------------------
# A. Module importable; authority and sentinel non-empty
# ---------------------------------------------------------------------------


def test_authority_sentinel_non_empty() -> None:
    assert isinstance(RUNTIME_TRUTH_OUTPUT_CHAIN_IS_AUTHORITY, str)
    assert RUNTIME_TRUTH_OUTPUT_CHAIN_IS_AUTHORITY


def test_pr9_sentinel_non_empty() -> None:
    assert isinstance(RUNTIME_TRUTH_OUTPUT_CHAIN_PR9_SENTINEL, str)
    assert RUNTIME_TRUTH_OUTPUT_CHAIN_PR9_SENTINEL


# ---------------------------------------------------------------------------
# B. All four policy sentinels non-empty with expected keywords
# ---------------------------------------------------------------------------


def test_stage_ordering_policy_present() -> None:
    assert "STAGE_ORDERING_IS_UNIDIRECTIONAL" in STAGE_ORDERING_IS_UNIDIRECTIONAL_POLICY
    assert STAGE_ORDERING_IS_UNIDIRECTIONAL_POLICY


def test_outward_assembler_policy_present() -> None:
    assert "OUTWARD_ASSEMBLER_IS_SOLE_OUTPUT_AUTHORITY" in OUTWARD_ASSEMBLER_IS_SOLE_OUTPUT_AUTHORITY_POLICY
    assert "compile_outward_truth" in OUTWARD_ASSEMBLER_IS_SOLE_OUTPUT_AUTHORITY_POLICY


def test_no_repeated_compilation_policy_present() -> None:
    assert "NO_REPEATED_STAGE_COMPILATION_WITHIN_REQUEST" in NO_REPEATED_STAGE_COMPILATION_WITHIN_REQUEST_POLICY
    assert "compile_runtime_truth" in NO_REPEATED_STAGE_COMPILATION_WITHIN_REQUEST_POLICY


def test_stage_role_inflation_policy_present() -> None:
    assert "STAGE_ROLE_INFLATION_IS_PROHIBITED" in STAGE_ROLE_INFLATION_IS_PROHIBITED_POLICY
    assert "Stage 1" in STAGE_ROLE_INFLATION_IS_PROHIBITED_POLICY
    assert "Stage 2" in STAGE_ROLE_INFLATION_IS_PROHIBITED_POLICY
    assert "Stage 3" in STAGE_ROLE_INFLATION_IS_PROHIBITED_POLICY


# ---------------------------------------------------------------------------
# C. TruthOutputStage enum has exactly three members
# ---------------------------------------------------------------------------


def test_truth_output_stage_has_three_members() -> None:
    stages = list(TruthOutputStage)
    assert len(stages) == 3


def test_truth_output_stage_members_are_correct() -> None:
    assert TruthOutputStage.INTERNAL_COMPILER.value == "internal_compiler"
    assert TruthOutputStage.OUTWARD_ASSEMBLER.value == "outward_assembler"
    assert TruthOutputStage.PROJECTION_SURFACE.value == "projection_surface"


# ---------------------------------------------------------------------------
# D. build_output_chain_catalog() returns 3 records ordered by stage_index
# ---------------------------------------------------------------------------


def test_catalog_returns_three_records() -> None:
    catalog = build_output_chain_catalog()
    assert len(catalog) == 3


def test_catalog_is_ordered_by_stage_index() -> None:
    catalog = build_output_chain_catalog()
    indices = [r.stage_index for r in catalog]
    assert indices == sorted(indices)
    assert indices == [1, 2, 3]


def test_catalog_stages_are_distinct() -> None:
    catalog = build_output_chain_catalog()
    stages = [r.stage for r in catalog]
    assert len(set(stages)) == 3


# ---------------------------------------------------------------------------
# E. Stage 1 record correctness
# ---------------------------------------------------------------------------


def test_stage1_module_and_function() -> None:
    record = get_stage_record(TruthOutputStage.INTERNAL_COMPILER)
    assert record.primary_module == "core.projection.runtime_truth_compiler"
    assert record.primary_function == "compile_runtime_truth"


def test_stage1_output_type() -> None:
    record = get_stage_record(TruthOutputStage.INTERNAL_COMPILER)
    assert record.output_type == "RuntimeTruthSnapshot"


def test_stage1_may_call_stages_is_empty() -> None:
    record = get_stage_record(TruthOutputStage.INTERNAL_COMPILER)
    assert record.may_call_stages == ()


def test_stage1_stage_index_is_one() -> None:
    record = get_stage_record(TruthOutputStage.INTERNAL_COMPILER)
    assert record.stage_index == 1


# ---------------------------------------------------------------------------
# F. Stage 2 record correctness
# ---------------------------------------------------------------------------


def test_stage2_module_and_function() -> None:
    record = get_stage_record(TruthOutputStage.OUTWARD_ASSEMBLER)
    assert record.primary_module == "core.outward_runtime_truth"
    assert record.primary_function == "compile_outward_truth"


def test_stage2_output_type() -> None:
    record = get_stage_record(TruthOutputStage.OUTWARD_ASSEMBLER)
    assert record.output_type == "OutwardRuntimeTruthSnapshot"


def test_stage2_may_call_stages_is_stage1_only() -> None:
    record = get_stage_record(TruthOutputStage.OUTWARD_ASSEMBLER)
    assert record.may_call_stages == (1,)


def test_stage2_stage_index_is_two() -> None:
    record = get_stage_record(TruthOutputStage.OUTWARD_ASSEMBLER)
    assert record.stage_index == 2


# ---------------------------------------------------------------------------
# G. Stage 3 record correctness
# ---------------------------------------------------------------------------


def test_stage3_module_and_function() -> None:
    record = get_stage_record(TruthOutputStage.PROJECTION_SURFACE)
    assert record.primary_module == "core.routes.projection"
    assert record.primary_function == "_assemble_runtime_truth_payload"


def test_stage3_may_call_stages_is_stage2_only() -> None:
    record = get_stage_record(TruthOutputStage.PROJECTION_SURFACE)
    assert record.may_call_stages == (2,)


def test_stage3_stage_index_is_three() -> None:
    record = get_stage_record(TruthOutputStage.PROJECTION_SURFACE)
    assert record.stage_index == 3


# ---------------------------------------------------------------------------
# H. find_stage_ordering_violations() returns empty list
# ---------------------------------------------------------------------------


def test_no_stage_ordering_violations() -> None:
    violations = find_stage_ordering_violations()
    assert violations == [], f"Unexpected violations: {violations}"


# ---------------------------------------------------------------------------
# I. classify_output_stage() for known surfaces
# ---------------------------------------------------------------------------


def test_classify_runtime_truth_compiler_by_module() -> None:
    result = classify_output_stage("core.projection.runtime_truth_compiler")
    assert result == TruthOutputStage.INTERNAL_COMPILER.value


def test_classify_runtime_truth_compiler_by_surface_id() -> None:
    result = classify_output_stage("runtime_truth_compiler")
    assert result == TruthOutputStage.INTERNAL_COMPILER.value


def test_classify_outward_runtime_truth_by_module() -> None:
    result = classify_output_stage("core.outward_runtime_truth")
    assert result == TruthOutputStage.OUTWARD_ASSEMBLER.value


def test_classify_outward_runtime_truth_by_function() -> None:
    result = classify_output_stage("compile_outward_truth")
    assert result == TruthOutputStage.OUTWARD_ASSEMBLER.value


def test_classify_projection_surface_by_surface_id() -> None:
    result = classify_output_stage("projection_runtime_truth_route")
    assert result == TruthOutputStage.PROJECTION_SURFACE.value


def test_classify_projection_surface_by_endpoint() -> None:
    result = classify_output_stage("GET /api/v1/projection/runtime-truth")
    assert result == TruthOutputStage.PROJECTION_SURFACE.value


# ---------------------------------------------------------------------------
# J. classify_output_stage() returns "unknown" for unrecognised surface
# ---------------------------------------------------------------------------


def test_classify_unknown_surface_returns_unknown() -> None:
    assert classify_output_stage("some_totally_unknown_module") == "unknown"


def test_classify_empty_surface_returns_unknown() -> None:
    assert classify_output_stage("") == "unknown"


def test_classify_whitespace_surface_returns_unknown() -> None:
    assert classify_output_stage("   ") == "unknown"


# ---------------------------------------------------------------------------
# K. get_stage_record() returns correct record
# ---------------------------------------------------------------------------


def test_get_stage_record_stage1() -> None:
    record = get_stage_record(TruthOutputStage.INTERNAL_COMPILER)
    assert record.stage is TruthOutputStage.INTERNAL_COMPILER


def test_get_stage_record_stage2() -> None:
    record = get_stage_record(TruthOutputStage.OUTWARD_ASSEMBLER)
    assert record.stage is TruthOutputStage.OUTWARD_ASSEMBLER


def test_get_stage_record_stage3() -> None:
    record = get_stage_record(TruthOutputStage.PROJECTION_SURFACE)
    assert record.stage is TruthOutputStage.PROJECTION_SURFACE


# ---------------------------------------------------------------------------
# L. get_stage_record() raises KeyError for invalid stage
# ---------------------------------------------------------------------------


def test_get_stage_record_invalid_raises() -> None:
    class InvalidStage:
        pass

    with pytest.raises((KeyError, AttributeError, TypeError)):
        get_stage_record(InvalidStage())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# M. build_output_chain_snapshot() returns an OutputChainSnapshot
# ---------------------------------------------------------------------------


def test_snapshot_is_output_chain_snapshot() -> None:
    snap = build_output_chain_snapshot()
    assert isinstance(snap, OutputChainSnapshot)


# ---------------------------------------------------------------------------
# N. Snapshot content correctness
# ---------------------------------------------------------------------------


def test_snapshot_has_three_stages() -> None:
    snap = build_output_chain_snapshot()
    assert len(snap.stages) == 3


def test_snapshot_has_four_policies() -> None:
    snap = build_output_chain_snapshot()
    assert len(snap.policies) == 4


def test_snapshot_chain_is_clean() -> None:
    snap = build_output_chain_snapshot()
    assert snap.ordering_violations == ()


def test_snapshot_chain_is_clean_flag() -> None:
    snap = build_output_chain_snapshot()
    d = snap.to_dict()
    assert d["chain_is_clean"] is True


def test_snapshot_ordering_violations_empty() -> None:
    snap = build_output_chain_snapshot()
    d = snap.to_dict()
    assert d["ordering_violations"] == []


# ---------------------------------------------------------------------------
# O. Snapshot.to_dict() includes expected top-level keys
# ---------------------------------------------------------------------------


def test_snapshot_to_dict_keys() -> None:
    d = build_output_chain_snapshot().to_dict()
    for key in ("authority", "sentinel", "policies", "stage_count", "stages",
                "ordering_violations", "chain_is_clean"):
        assert key in d, f"Missing key: {key}"


def test_snapshot_to_dict_stage_count_is_three() -> None:
    d = build_output_chain_snapshot().to_dict()
    assert d["stage_count"] == 3


# ---------------------------------------------------------------------------
# P. Each ChainStageRecord.to_dict() includes all required keys
# ---------------------------------------------------------------------------


def test_chain_stage_record_to_dict_has_required_keys() -> None:
    required = {
        "stage", "stage_index", "display_name", "primary_module",
        "primary_function", "output_type", "responsibility_summary",
        "may_call_stages", "known_surface_ids", "governance_constraint",
    }
    for record in build_output_chain_catalog():
        d = record.to_dict()
        for key in required:
            assert key in d, f"Stage {record.stage_index}: missing key {key!r}"


# ---------------------------------------------------------------------------
# Q. No stage may_call_stages includes its own or downstream index
# ---------------------------------------------------------------------------


def test_may_call_stages_only_upstream() -> None:
    for record in build_output_chain_catalog():
        for called in record.may_call_stages:
            assert called < record.stage_index, (
                f"Stage {record.stage_index} ({record.stage.value}) "
                f"lists may_call_stages={record.may_call_stages}, "
                f"but {called} is not strictly upstream."
            )


# ---------------------------------------------------------------------------
# R. Every stage has a non-empty governance_constraint
# ---------------------------------------------------------------------------


def test_every_stage_has_governance_constraint() -> None:
    for record in build_output_chain_catalog():
        assert record.governance_constraint, (
            f"Stage {record.stage_index} has an empty governance_constraint"
        )


# ---------------------------------------------------------------------------
# S. Every stage has at least one known_surface_id
# ---------------------------------------------------------------------------


def test_every_stage_has_known_surface_ids() -> None:
    for record in build_output_chain_catalog():
        assert len(record.known_surface_ids) >= 1, (
            f"Stage {record.stage_index} has no known_surface_ids"
        )


# ---------------------------------------------------------------------------
# T. Stage 1 known_surface_ids include the compiler module path
# ---------------------------------------------------------------------------


def test_stage1_known_surfaces_include_compiler_module() -> None:
    record = get_stage_record(TruthOutputStage.INTERNAL_COMPILER)
    assert "core.projection.runtime_truth_compiler.compile_runtime_truth" in record.known_surface_ids


# ---------------------------------------------------------------------------
# U. Stage 2 known_surface_ids include the outward assembler module path
# ---------------------------------------------------------------------------


def test_stage2_known_surfaces_include_outward_assembler() -> None:
    record = get_stage_record(TruthOutputStage.OUTWARD_ASSEMBLER)
    assert "core.outward_runtime_truth.compile_outward_truth" in record.known_surface_ids


# ---------------------------------------------------------------------------
# V. Stage 3 known_surface_ids include the projection route surface
# ---------------------------------------------------------------------------


def test_stage3_known_surfaces_include_projection_route() -> None:
    record = get_stage_record(TruthOutputStage.PROJECTION_SURFACE)
    assert "core.routes.projection._assemble_runtime_truth_payload" in record.known_surface_ids


# ---------------------------------------------------------------------------
# W. Projection alignment sentinel importable and not UNAVAILABLE (fastapi guard)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_FASTAPI, reason="fastapi not installed")
def test_projection_alignment_sentinel_present() -> None:
    from core.routes import projection

    sentinel = projection.RUNTIME_TRUTH_OUTPUT_CHAIN_ALIGNED_PR9
    assert "RUNTIME_TRUTH_OUTPUT_CHAIN_ALIGNED_PR9" in sentinel
    assert "UNAVAILABLE" not in sentinel


# ---------------------------------------------------------------------------
# X. Sentinel strings contain expected keywords
# ---------------------------------------------------------------------------


def test_authority_sentinel_contains_pr9() -> None:
    assert "PR-9" in RUNTIME_TRUTH_OUTPUT_CHAIN_IS_AUTHORITY


def test_authority_sentinel_contains_chain_keyword() -> None:
    assert "chain" in RUNTIME_TRUTH_OUTPUT_CHAIN_IS_AUTHORITY.lower()


def test_pr9_sentinel_contains_stage_keywords() -> None:
    assert "Stage 1" in RUNTIME_TRUTH_OUTPUT_CHAIN_PR9_SENTINEL
    assert "Stage 2" in RUNTIME_TRUTH_OUTPUT_CHAIN_PR9_SENTINEL
    assert "Stage 3" in RUNTIME_TRUTH_OUTPUT_CHAIN_PR9_SENTINEL


def test_pr9_sentinel_contains_compiler_and_assembler_names() -> None:
    assert "RuntimeTruthCompiler" in RUNTIME_TRUTH_OUTPUT_CHAIN_PR9_SENTINEL
    assert "OutwardRuntimeTruth" in RUNTIME_TRUTH_OUTPUT_CHAIN_PR9_SENTINEL
