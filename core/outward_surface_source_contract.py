"""
Outward surface source inventory and contract assertions.

This module defines the expected source discipline for high-value outward
surfaces so mixed-source fallback cannot silently drift without tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from core.authority_source_fingerprint import (
    SOURCE_KIND_CANONICAL_TRUTH,
    SOURCE_KIND_COMPILED_OUTWARD_TRUTH,
    SOURCE_KIND_DIAGNOSTICS_VISIBLE_STATE,
    SOURCE_KIND_OPERATOR_DERIVED_SURFACE,
    SOURCE_KIND_RUNTIME_VISIBLE_STATE,
)


@dataclass(frozen=True)
class OutwardSurfaceSourceContract:
    surface_id: str
    surface_path: str
    preferred_source_path: Optional[str]
    preferred_primary_source_kind: str
    allowed_fallback_source_kinds: Tuple[str, ...]
    mixed_source_allowed: bool
    mixed_source_allowed_when: str
    required_mixed_evidence_fields: Tuple[str, ...] = ()
    required_mixed_fingerprint_basis_fields: Tuple[str, ...] = ()


OUTWARD_SURFACE_SOURCE_CONTRACTS: Dict[str, OutwardSurfaceSourceContract] = {
    "panel_unified": OutwardSurfaceSourceContract(
        surface_id="panel_unified",
        surface_path="/api/v1/panel/unified",
        preferred_source_path="core.outward_runtime_truth.compile_outward_truth",
        preferred_primary_source_kind=SOURCE_KIND_COMPILED_OUTWARD_TRUTH,
        allowed_fallback_source_kinds=(SOURCE_KIND_RUNTIME_VISIBLE_STATE,),
        mixed_source_allowed=True,
        mixed_source_allowed_when=(
            "compile_outward_truth unavailable or compiled truth reports incomplete surfacing"
        ),
        required_mixed_evidence_fields=("assembly_mode", "mixed_source", "fallback_used", "fallback_reason"),
        required_mixed_fingerprint_basis_fields=("truth_compilation_primary_path", "mixed_source"),
    ),
    "desktop_status_board_projection": OutwardSurfaceSourceContract(
        surface_id="desktop_status_board_projection",
        surface_path="/api/v1/projection/desktop-status-board",
        preferred_source_path="core.outward_runtime_truth.compile_outward_truth",
        preferred_primary_source_kind=SOURCE_KIND_COMPILED_OUTWARD_TRUTH,
        allowed_fallback_source_kinds=(SOURCE_KIND_COMPILED_OUTWARD_TRUTH,),
        mixed_source_allowed=True,
        mixed_source_allowed_when=(
            "outward truth compile path unavailable and projection/runtime data is used as fallback"
        ),
        required_mixed_evidence_fields=("assembly_mode", "mixed_source", "fallback_used", "fallback_reason"),
        required_mixed_fingerprint_basis_fields=(
            "truth_compilation_primary_path",
            "truth_compilation_assembly_mode",
            "mixed_source",
        ),
    ),
    "operator_devices_ecosystem": OutwardSurfaceSourceContract(
        surface_id="operator_devices_ecosystem",
        surface_path="/api/v1/operator/devices/ecosystem",
        preferred_source_path="core.android_device_state_store.get_device_ecosystem_summary",
        preferred_primary_source_kind=SOURCE_KIND_RUNTIME_VISIBLE_STATE,
        allowed_fallback_source_kinds=(SOURCE_KIND_DIAGNOSTICS_VISIBLE_STATE,),
        mixed_source_allowed=False,
        mixed_source_allowed_when="mixed-source assembly is not permitted for this runtime-visible diagnostics surface",
    ),
}


def get_outward_surface_source_contract(surface_id: str) -> OutwardSurfaceSourceContract:
    return OUTWARD_SURFACE_SOURCE_CONTRACTS[surface_id]


def assert_outward_surface_source_contract(
    surface_id: str,
    *,
    truth_compilation_evidence: Optional[Mapping[str, Any]] = None,
    authority_source_fingerprint: Optional[Mapping[str, Any]] = None,
) -> None:
    """
    Assert one outward surface payload obeys the inventory contract.
    """
    contract = get_outward_surface_source_contract(surface_id)

    if authority_source_fingerprint is not None:
        fp = dict(authority_source_fingerprint)
        assert fp.get("surface_path") == contract.surface_path
        assert fp.get("consumption_only") is True
        assert fp.get("acts_as_authority_layer") is False

        primary_kind = fp.get("primary_source_kind")
        allowed_kinds = {contract.preferred_primary_source_kind, *contract.allowed_fallback_source_kinds}
        assert primary_kind in allowed_kinds

        source_roles = fp.get("source_roles") or {}
        if primary_kind in {SOURCE_KIND_RUNTIME_VISIBLE_STATE, SOURCE_KIND_DIAGNOSTICS_VISIBLE_STATE}:
            assert source_roles.get(SOURCE_KIND_CANONICAL_TRUTH) != "primary"
            assert source_roles.get(SOURCE_KIND_COMPILED_OUTWARD_TRUTH) != "primary"

    if truth_compilation_evidence is None:
        return

    evidence = dict(truth_compilation_evidence)
    if contract.preferred_source_path:
        assert evidence.get("primary_path") == contract.preferred_source_path

    mixed_source = bool(evidence.get("mixed_source", False))
    fallback_used = bool(evidence.get("fallback_used", False))
    if mixed_source or fallback_used:
        assert contract.mixed_source_allowed, contract.mixed_source_allowed_when
        for field in contract.required_mixed_evidence_fields:
            assert evidence.get(field) not in (None, "")

        if authority_source_fingerprint is not None:
            basis = (authority_source_fingerprint.get("observation_basis") or {})
            for field in contract.required_mixed_fingerprint_basis_fields:
                assert basis.get(field) not in (None, "")
    else:
        assert evidence.get("assembly_mode") == "compiled_outward_truth_primary"
