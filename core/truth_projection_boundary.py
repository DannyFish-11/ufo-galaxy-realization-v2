#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/truth_projection_boundary.py
=================================
PR-7 (two-repository convergence plan): explicit Truth vs Projection boundary.

This module is the canonical authority for classifying cross-plane surfaces as:
- canonical truth owners
- projection/read-model surfaces
- synchronization/mapping layers
- compatibility-only surfaces

The goal is additive and low-risk: make ownership explicit so convenience
registries/projections do not drift into lifecycle authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

TRUTH_PROJECTION_BOUNDARY_IS_AUTHORITY: str = (
    "TRUTH_PROJECTION_BOUNDARY_IS_AUTHORITY_V1: "
    "core.truth_projection_boundary is the canonical authority that classifies "
    "participant/device/session/capability/execution surfaces into truth-owner, "
    "projection/read-model, synchronization-mapping, and compatibility-only roles."
)

TRUTH_PROJECTION_BOUNDARY_PR7_SENTINEL: str = (
    "TRUTH_PROJECTION_BOUNDARY_PR7_SENTINEL_V1: "
    "PR-7 truth-vs-projection boundary is explicitly classified across "
    "participant/device/session/capability/execution planes."
)

PROJECTIONS_ARE_NOT_LIFECYCLE_OWNERS_POLICY: str = (
    "PROJECTIONS_ARE_NOT_LIFECYCLE_OWNERS_POLICY_V1: projection/read-model "
    "surfaces are read-only views and must not become lifecycle owners."
)

COMPAT_REGISTRIES_ARE_NOT_AUTHORITY_POLICY: str = (
    "COMPAT_REGISTRIES_ARE_NOT_AUTHORITY_POLICY_V1: compatibility registries "
    "or caches are preserved for operations and migration, but are not canonical truth."
)

SYNC_LAYERS_MUST_NOT_SELF_PROMOTE_POLICY: str = (
    "SYNC_LAYERS_MUST_NOT_SELF_PROMOTE_POLICY_V1: mapping/synchronization layers "
    "translate between truth and projections; they must not self-promote to authority."
)


class AuthorityPlane(str, Enum):
    PARTICIPANT = "participant"
    DEVICE = "device"
    SESSION = "session"
    CAPABILITY = "capability"
    EXECUTION = "execution"


class BoundaryRole(str, Enum):
    CANONICAL_TRUTH = "canonical_truth"
    PROJECTION_READ_MODEL = "projection_read_model"
    SYNCHRONIZATION_MAPPING = "synchronization_mapping"
    COMPATIBILITY_SURFACE = "compatibility_surface"


@dataclass(frozen=True)
class TruthProjectionBoundaryEntry:
    surface_id: str
    plane: AuthorityPlane
    role: BoundaryRole
    module_path: str
    lifecycle_owner: bool
    canonical_truth_source: Optional[str]
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "surface_id": self.surface_id,
            "plane": self.plane.value,
            "role": self.role.value,
            "module_path": self.module_path,
            "lifecycle_owner": self.lifecycle_owner,
            "canonical_truth_source": self.canonical_truth_source,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class PlaneBoundaryContract:
    """Explicit boundary contract for a single authority plane."""

    plane: AuthorityPlane
    responsibility_summary: str
    canonical_truth_surface_ids: Tuple[str, ...]
    projection_surface_ids: Tuple[str, ...]
    synchronization_surface_ids: Tuple[str, ...]
    compatibility_surface_ids: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plane": self.plane.value,
            "responsibility_summary": self.responsibility_summary,
            "canonical_truth_surface_ids": list(self.canonical_truth_surface_ids),
            "projection_surface_ids": list(self.projection_surface_ids),
            "synchronization_surface_ids": list(self.synchronization_surface_ids),
            "compatibility_surface_ids": list(self.compatibility_surface_ids),
        }


_PLANE_RESPONSIBILITY_SUMMARY: Dict[AuthorityPlane, str] = {
    AuthorityPlane.PARTICIPANT: (
        "Participant plane defines runtime actor identity truth, while participant readiness "
        "and tiering remain projection/mapping outputs."
    ),
    AuthorityPlane.DEVICE: (
        "Device plane owns mutable device lifecycle/registration truth; registry compatibility "
        "indexes and read contracts remain non-authoritative."
    ),
    AuthorityPlane.SESSION: (
        "Session plane owns active runtime-attachment and session-lifecycle truth; multi-device "
        "views are read models and reuse binders are synchronization only."
    ),
    AuthorityPlane.CAPABILITY: (
        "Capability plane owns canonical capability inventory truth; resolver views and compatibility "
        "facades must not claim authority."
    ),
    AuthorityPlane.EXECUTION: (
        "Execution plane owns execution lifecycle and authority chain truth; observability and dispatch "
        "selection remain explanatory or mapping layers."
    ),
}


def build_truth_projection_boundary_catalog() -> List[TruthProjectionBoundaryEntry]:
    return [
        TruthProjectionBoundaryEntry(
            surface_id="participant_identity_normalization",
            plane=AuthorityPlane.PARTICIPANT,
            role=BoundaryRole.CANONICAL_TRUTH,
            module_path="core.schemas.ugcp.shared.normalize_runtime_participant_id",
            lifecycle_owner=True,
            canonical_truth_source=None,
            rationale="Canonical participant identity normalization contract.",
        ),
        TruthProjectionBoundaryEntry(
            surface_id="participant_readiness_projection",
            plane=AuthorityPlane.PARTICIPANT,
            role=BoundaryRole.PROJECTION_READ_MODEL,
            module_path="core.device_participation.ParticipationSummary",
            lifecycle_owner=False,
            canonical_truth_source="participant_identity_normalization",
            rationale="Participant/readiness enrichment summary is projection only.",
        ),
        TruthProjectionBoundaryEntry(
            surface_id="participant_tier_mapping",
            plane=AuthorityPlane.PARTICIPANT,
            role=BoundaryRole.SYNCHRONIZATION_MAPPING,
            module_path="core.schemas.ugcp.shared.derive_participant_tier",
            lifecycle_owner=False,
            canonical_truth_source="participant_identity_normalization",
            rationale="Tier derivation maps participant facts into scheduling semantics.",
        ),
        TruthProjectionBoundaryEntry(
            surface_id="unified_device_manager",
            plane=AuthorityPlane.DEVICE,
            role=BoundaryRole.CANONICAL_TRUTH,
            module_path="core.unified.device_manager.UnifiedDeviceManager",
            lifecycle_owner=True,
            canonical_truth_source=None,
            rationale="Device registration/mutable state write SSOT.",
        ),
        TruthProjectionBoundaryEntry(
            surface_id="registered_runtime_device_projection",
            plane=AuthorityPlane.DEVICE,
            role=BoundaryRole.PROJECTION_READ_MODEL,
            module_path="contracts.registered_runtime_device.RegisteredRuntimeDevice",
            lifecycle_owner=False,
            canonical_truth_source="unified_device_manager",
            rationale="Single-device read contract projection.",
        ),
        TruthProjectionBoundaryEntry(
            surface_id="device_registry_compat_index",
            plane=AuthorityPlane.DEVICE,
            role=BoundaryRole.COMPATIBILITY_SURFACE,
            module_path="core.device_registry.DeviceRegistry",
            lifecycle_owner=False,
            canonical_truth_source="unified_device_manager",
            rationale="Compatibility indexing/discovery facade over canonical device truth.",
        ),
        TruthProjectionBoundaryEntry(
            surface_id="attached_runtime_session_registry",
            plane=AuthorityPlane.SESSION,
            role=BoundaryRole.CANONICAL_TRUTH,
            module_path="core.attached_runtime_session_registry.AttachedSessionRegistry",
            lifecycle_owner=True,
            canonical_truth_source=None,
            rationale="Authoritative active attached-runtime session lifecycle state.",
        ),
        TruthProjectionBoundaryEntry(
            surface_id="canonical_session_truth",
            plane=AuthorityPlane.SESSION,
            role=BoundaryRole.CANONICAL_TRUTH,
            module_path="core.canonical_session_truth.record_session_truth",
            lifecycle_owner=True,
            canonical_truth_source=None,
            rationale="Authoritative runtime-session result truth recording.",
        ),
        TruthProjectionBoundaryEntry(
            surface_id="multi_device_runtime_projection",
            plane=AuthorityPlane.SESSION,
            role=BoundaryRole.PROJECTION_READ_MODEL,
            module_path="contracts.multi_device_runtime_projection.MultiDeviceRuntimeProjection",
            lifecycle_owner=False,
            canonical_truth_source="attached_runtime_session_registry",
            rationale="Top-level read model over device/runtime/session state.",
        ),
        TruthProjectionBoundaryEntry(
            surface_id="attached_runtime_reuse_mapping",
            plane=AuthorityPlane.SESSION,
            role=BoundaryRole.SYNCHRONIZATION_MAPPING,
            module_path="core.attached_runtime_reuse_binding.resolve_reuse_dispatch_surface",
            lifecycle_owner=False,
            canonical_truth_source="attached_runtime_session_registry",
            rationale="Reuse mapping layer must consult canonical active-session truth.",
        ),
        TruthProjectionBoundaryEntry(
            surface_id="capability_registry",
            plane=AuthorityPlane.CAPABILITY,
            role=BoundaryRole.CANONICAL_TRUTH,
            module_path="core.agent.capability_registry.CapabilityRegistry",
            lifecycle_owner=True,
            canonical_truth_source=None,
            rationale="Canonical in-process capability inventory authority.",
        ),
        TruthProjectionBoundaryEntry(
            surface_id="capability_resolver_projection",
            plane=AuthorityPlane.CAPABILITY,
            role=BoundaryRole.PROJECTION_READ_MODEL,
            module_path="core.unified.capability_resolver.CapabilityResolver",
            lifecycle_owner=False,
            canonical_truth_source="capability_registry",
            rationale="Validated consumer-facing capability read model.",
        ),
        TruthProjectionBoundaryEntry(
            surface_id="capability_manager_compat",
            plane=AuthorityPlane.CAPABILITY,
            role=BoundaryRole.COMPATIBILITY_SURFACE,
            module_path="core.capability_manager.CapabilityManager",
            lifecycle_owner=False,
            canonical_truth_source="capability_registry",
            rationale="Legacy capability facade bridged into canonical registry.",
        ),
        TruthProjectionBoundaryEntry(
            surface_id="device_capability_sync_mapping",
            plane=AuthorityPlane.CAPABILITY,
            role=BoundaryRole.SYNCHRONIZATION_MAPPING,
            module_path="core.routes.devices._sync_device_to_capability_registry",
            lifecycle_owner=False,
            canonical_truth_source="capability_registry",
            rationale="Registration sync maps device facts into capability catalog.",
        ),
        TruthProjectionBoundaryEntry(
            surface_id="canonical_execution_chain",
            plane=AuthorityPlane.EXECUTION,
            role=BoundaryRole.CANONICAL_TRUTH,
            module_path="core.canonical_execution_chain",
            lifecycle_owner=True,
            canonical_truth_source=None,
            rationale="Declares single canonical execution authority chain.",
        ),
        TruthProjectionBoundaryEntry(
            surface_id="task_envelope_lifecycle_registry",
            plane=AuthorityPlane.EXECUTION,
            role=BoundaryRole.CANONICAL_TRUTH,
            module_path="core.task_envelope_lifecycle_registry.TaskEnvelopeLifecycleRegistry",
            lifecycle_owner=True,
            canonical_truth_source=None,
            rationale="Authoritative in-flight envelope lifecycle ownership.",
        ),
        TruthProjectionBoundaryEntry(
            surface_id="runtime_decision_observability_projection",
            plane=AuthorityPlane.EXECUTION,
            role=BoundaryRole.PROJECTION_READ_MODEL,
            module_path="core.runtime_decision_observability.build_runtime_decision_explanation",
            lifecycle_owner=False,
            canonical_truth_source="canonical_execution_chain",
            rationale="Decision observability is explanatory projection, not authority.",
        ),
        TruthProjectionBoundaryEntry(
            surface_id="dispatch_target_selection_mapping",
            plane=AuthorityPlane.EXECUTION,
            role=BoundaryRole.SYNCHRONIZATION_MAPPING,
            module_path="core.runtime.source_dispatch_orchestrator.select_dispatch_target",
            lifecycle_owner=False,
            canonical_truth_source="canonical_execution_chain",
            rationale="Selection combines readiness/registry/session truths without owning them.",
        ),
    ]


def classify_surface_boundary(surface_ref: str) -> str:
    normalised = (surface_ref or "").strip()
    if not normalised:
        return "unknown"
    for entry in build_truth_projection_boundary_catalog():
        if normalised == entry.surface_id or normalised == entry.module_path:
            return entry.role.value
    return "unknown"


def build_plane_boundary_contracts() -> List[PlaneBoundaryContract]:
    entries = build_truth_projection_boundary_catalog()
    contracts = [_build_plane_boundary_contract(plane, entries) for plane in AuthorityPlane]
    return contracts


def get_plane_boundary_contract(
    plane: AuthorityPlane,
    entries: Optional[List[TruthProjectionBoundaryEntry]] = None,
) -> PlaneBoundaryContract:
    catalog_entries = entries if entries is not None else build_truth_projection_boundary_catalog()
    return _build_plane_boundary_contract(plane, catalog_entries)


def _build_plane_boundary_contract(
    plane: AuthorityPlane,
    entries: List[TruthProjectionBoundaryEntry],
) -> PlaneBoundaryContract:
    plane_entries = [entry for entry in entries if entry.plane is plane]
    if not plane_entries:
        raise ValueError(f"No boundary entries found for plane: {plane.value}")
    return PlaneBoundaryContract(
        plane=plane,
        responsibility_summary=_PLANE_RESPONSIBILITY_SUMMARY[plane],
        canonical_truth_surface_ids=tuple(
            entry.surface_id for entry in plane_entries if entry.role is BoundaryRole.CANONICAL_TRUTH
        ),
        projection_surface_ids=tuple(
            entry.surface_id for entry in plane_entries if entry.role is BoundaryRole.PROJECTION_READ_MODEL
        ),
        synchronization_surface_ids=tuple(
            entry.surface_id for entry in plane_entries if entry.role is BoundaryRole.SYNCHRONIZATION_MAPPING
        ),
        compatibility_surface_ids=tuple(
            entry.surface_id for entry in plane_entries if entry.role is BoundaryRole.COMPATIBILITY_SURFACE
        ),
    )


def get_plane_entries(plane: AuthorityPlane) -> List[TruthProjectionBoundaryEntry]:
    return [e for e in build_truth_projection_boundary_catalog() if e.plane == plane]


def find_non_canonical_lifecycle_owners() -> List[TruthProjectionBoundaryEntry]:
    return [
        e
        for e in build_truth_projection_boundary_catalog()
        if e.lifecycle_owner and e.role is not BoundaryRole.CANONICAL_TRUTH
    ]


def build_truth_projection_boundary_snapshot() -> Dict[str, Any]:
    entries = build_truth_projection_boundary_catalog()
    violations = find_non_canonical_lifecycle_owners()
    by_plane: Dict[str, Dict[str, int]] = {}
    for plane in AuthorityPlane:
        plane_entries = [e for e in entries if e.plane is plane]
        by_plane[plane.value] = {
            "canonical_truth": sum(1 for e in plane_entries if e.role is BoundaryRole.CANONICAL_TRUTH),
            "projection_read_model": sum(1 for e in plane_entries if e.role is BoundaryRole.PROJECTION_READ_MODEL),
            "synchronization_mapping": sum(1 for e in plane_entries if e.role is BoundaryRole.SYNCHRONIZATION_MAPPING),
            "compatibility_surface": sum(1 for e in plane_entries if e.role is BoundaryRole.COMPATIBILITY_SURFACE),
        }

    return {
        "authority": TRUTH_PROJECTION_BOUNDARY_IS_AUTHORITY,
        "sentinel": TRUTH_PROJECTION_BOUNDARY_PR7_SENTINEL,
        "policies": [
            PROJECTIONS_ARE_NOT_LIFECYCLE_OWNERS_POLICY,
            COMPAT_REGISTRIES_ARE_NOT_AUTHORITY_POLICY,
            SYNC_LAYERS_MUST_NOT_SELF_PROMOTE_POLICY,
        ],
        "total_surfaces": len(entries),
        "planes": by_plane,
        "plane_boundary_contracts": [contract.to_dict() for contract in build_plane_boundary_contracts()],
        "non_canonical_lifecycle_owner_violations": [e.to_dict() for e in violations],
    }
