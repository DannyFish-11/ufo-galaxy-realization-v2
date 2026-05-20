from __future__ import annotations

import json
from pathlib import Path

from core.bounded_subject_platform_boundary import (
    PlatformBoundaryAxis,
    build_platform_boundary_snapshot,
    build_quasi_platform_runtime_assertion_report,
)
from core.final_acceptance_surface_boundary import build_final_acceptance_surface_boundary


OUTPUT_MD_PATH = Path("docs/FORMAL_SYSTEM_BOUNDARY_OUTPUT_V1.md")
SUMMARY_PATH = Path("docs/FORMAL_SYSTEM_BOUNDARY_SUMMARY_V1.json")
SCHEMA_PATH = Path("docs/FORMAL_SYSTEM_BOUNDARY_SUMMARY_SCHEMA_V1.json")


def _load_json(path: Path) -> dict:
    assert path.exists(), f"missing file: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_pr19_output_files_exist() -> None:
    assert OUTPUT_MD_PATH.exists()
    assert SUMMARY_PATH.exists()
    assert SCHEMA_PATH.exists()


def test_output_doc_declares_quasi_platform_not_fully_mature_and_no_parallel_android_center() -> None:
    content = OUTPUT_MD_PATH.read_text(encoding="utf-8")
    assert "稳定准平台态" in content
    assert "fully mature distributed platform" in content
    assert "Android 不是平行 canonical center" in content


def test_summary_pins_five_required_boundaries() -> None:
    summary = _load_json(SUMMARY_PATH)
    boundaries = summary["boundaries"]
    assert set(boundaries.keys()) == {
        "canonical_center_boundary",
        "bounded_subject_boundary",
        "participant_governance_boundary",
        "observability_diagnostics_evidence_boundary",
        "outward_consumption_boundary",
    }


def test_summary_pins_required_system_and_governance_flags() -> None:
    summary = _load_json(SUMMARY_PATH)
    assert summary["system_definition"]["stable_quasi_platform_state"] is True
    assert summary["system_definition"]["fully_mature_distributed_platform"] is False
    assert summary["android_v2_alignment"]["android_is_parallel_center"] is False
    assert summary["android_v2_alignment"]["android_has_global_truth_finalization"] is False
    assert summary["android_v2_alignment"]["android_has_global_dispatch_authority"] is False
    assert summary["narrative_guardrails"]["no_parallel_center_claim"] is True
    assert summary["narrative_guardrails"]["no_outward_authority_layer_claim"] is True
    assert summary["narrative_guardrails"]["no_fully_mature_platform_claim"] is True


def test_summary_references_runtime_assertion_anchors() -> None:
    summary = _load_json(SUMMARY_PATH)
    anchors = set(summary["runtime_assertion_anchors"])
    assert "core.center_authority_boundary.assert_center_authority_intact" in anchors
    assert "core.bounded_subject_platform_boundary.assert_quasi_platform_state_intact" in anchors
    assert "core.bounded_subject_platform_boundary.build_quasi_platform_runtime_assertion_report" in anchors
    assert "core.final_acceptance_surface_boundary.build_final_acceptance_surface_boundary" in anchors


def test_summary_is_consistent_with_runtime_boundary_snapshot_axes() -> None:
    summary = _load_json(SUMMARY_PATH)
    runtime_axes = {axis.axis for axis in build_platform_boundary_snapshot().axes}
    assert runtime_axes == {
        PlatformBoundaryAxis.CANONICAL_CENTER,
        PlatformBoundaryAxis.BOUNDED_SUBJECT,
        PlatformBoundaryAxis.PARTICIPANT_GOVERNANCE,
        PlatformBoundaryAxis.OBSERVABILITY_EVIDENCE,
        PlatformBoundaryAxis.OUTWARD_CONSUMPTION,
    }
    assert "canonical_center_boundary" in summary["boundaries"]
    assert "bounded_subject_boundary" in summary["boundaries"]
    assert "participant_governance_boundary" in summary["boundaries"]
    assert "observability_diagnostics_evidence_boundary" in summary["boundaries"]
    assert "outward_consumption_boundary" in summary["boundaries"]


def test_outward_contract_summary_matches_runtime_assertion_flags() -> None:
    summary = _load_json(SUMMARY_PATH)
    report = build_quasi_platform_runtime_assertion_report()
    flags = report["final_acceptance_boundary_flags"]
    outward_summary = summary["outward_contract_summary"]
    assert report["intact"] is True
    assert flags["no_parallel_final_integration_framework"] is True
    assert flags["outward_surfaces_consume_canonical_outputs_only"] is True
    assert outward_summary["no_parallel_final_integration_framework"] is True
    assert outward_summary["canonical_outputs_only"] is True
    assert outward_summary["consumption_only"] is True
    assert outward_summary["no_authority_reassembly"] is True


def test_direct_final_acceptance_boundary_remains_consumption_only() -> None:
    boundary = build_final_acceptance_surface_boundary(
        surface="pr19_formal_boundary_output",
        consumer_role="contract_regression",
        canonical_backend_contract="core.v2_unified_state_contract.build_control_plane_surface_contract",
        product_surface="/internal/pr19/formal-boundary-output",
    )
    assert boundary["no_authority_reassembly"] is True
    assert boundary["no_parallel_final_integration_framework"] is True
    assert boundary["outward_surfaces_consume_canonical_outputs_only"] is True


def test_schema_pins_core_const_constraints() -> None:
    schema = _load_json(SCHEMA_PATH)
    props = schema["properties"]
    assert props["version"]["const"] == "v1"
    assert props["system_definition"]["properties"]["stable_quasi_platform_state"]["const"] is True
    assert props["system_definition"]["properties"]["fully_mature_distributed_platform"]["const"] is False
    assert props["android_v2_alignment"]["properties"]["android_is_parallel_center"]["const"] is False
    assert props["android_v2_alignment"]["properties"]["android_has_global_truth_finalization"]["const"] is False
    assert props["android_v2_alignment"]["properties"]["android_has_global_dispatch_authority"]["const"] is False


def test_summary_and_schema_boundary_keys_are_identical() -> None:
    summary = _load_json(SUMMARY_PATH)
    schema = _load_json(SCHEMA_PATH)
    summary_keys = set(summary["boundaries"].keys())
    schema_keys = set(schema["properties"]["boundaries"]["required"])
    assert summary_keys == schema_keys
