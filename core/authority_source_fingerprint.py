"""
Authority source fingerprint helpers for outward/operator/panel/projection surfaces.

This module only annotates source provenance. It must never become a new
authority layer or mutate canonical truth.
"""

from __future__ import annotations

from typing import Any, Dict

AUTHORITY_SOURCE_FINGERPRINT_SCHEMA_VERSION = "1.0"

SOURCE_KIND_CANONICAL_TRUTH = "canonical_truth"
SOURCE_KIND_COMPILED_OUTWARD_TRUTH = "compiled_outward_truth"
SOURCE_KIND_RUNTIME_VISIBLE_STATE = "runtime_visible_state"
SOURCE_KIND_DIAGNOSTICS_VISIBLE_STATE = "diagnostics_visible_state"
SOURCE_KIND_OPERATOR_DERIVED_SURFACE = "operator_derived_surface"


def build_authority_source_fingerprint(
    *,
    surface_path: str,
    primary_source_kind: str,
    source_roles: Dict[str, str],
    source_freshness: Dict[str, Any] | None = None,
    observation_basis: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a machine-readable source fingerprint for one API surface."""
    role_map = {
        SOURCE_KIND_CANONICAL_TRUTH: "none",
        SOURCE_KIND_COMPILED_OUTWARD_TRUTH: "none",
        SOURCE_KIND_RUNTIME_VISIBLE_STATE: "none",
        SOURCE_KIND_DIAGNOSTICS_VISIBLE_STATE: "none",
        SOURCE_KIND_OPERATOR_DERIVED_SURFACE: "none",
    }
    role_map.update(source_roles or {})
    fingerprint: Dict[str, Any] = {
        "schema_version": AUTHORITY_SOURCE_FINGERPRINT_SCHEMA_VERSION,
        "surface_path": surface_path,
        "primary_source_kind": primary_source_kind,
        "source_roles": role_map,
        "consumption_only": True,
        "acts_as_authority_layer": False,
    }
    if source_freshness:
        fingerprint["source_freshness"] = dict(source_freshness)
    if observation_basis:
        fingerprint["observation_basis"] = dict(observation_basis)
    return fingerprint
