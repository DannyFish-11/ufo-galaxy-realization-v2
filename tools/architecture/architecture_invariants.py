#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools.architecture.architecture_invariants — Shared Architectural Constants and Cross-Cutting Invariants
===========================================================================================

PR-10 (Consolidation) — Unify architecture invariants after PR-001 through PR-009.

This module is the **single source of truth** for the canonical terminology,
labels, and cross-cutting invariant helpers used across architecture
diagnostics, completion scorecards, projection metadata, capability
registries, and legacy-path reporting.

## Why this module exists

After PR-001 through PR-009 a stable architecture story exists, but the
supporting vocabulary has grown organically across multiple modules.  This
module:

1. Centralises the canonical string labels used in authority-chain metadata,
   canonical/legacy boundary markers, and projection-truth markers so that
   diagnostics, scorecards, and interface contracts can all reference the
   same constants rather than repeating string literals.

2. Exposes lightweight, **pure-function** cross-cutting invariant checks that
   operate on plain dicts returned by the existing module APIs.  These
   functions complement (but do not replace) the per-module checks already
   present in :mod:`tools.architecture.architecture_diagnostics` and
   :mod:`tools.architecture.architecture_truth_guards`.

3. Provides :func:`run_consolidation_invariants` as a single entry point that
   aggregates all cross-cutting checks into one :class:`ConsolidationReport`.

## Canonical authority chain

The post-PR-009 canonical authority chain is::

    DesktopPresenceRuntime   (runtime_shell_authority)
          │
          ▼
    OpenClawd                (subject_decision_authority)
          │
          ▼
    AgentKernel              (cognition_planning_layer)
          │
          ▼
    CommandRouter            (execution_substrate)

## Canonical vs legacy boundary policy

* ``canonical`` — primary, architectural, enforced path.
* ``legacy_compatibility`` / ``compatibility_fallback`` — permitted for
  backward compatibility only; not the primary architecture.
* ``deprecated`` — actively replaced; kept for migration only.

## Projection outward-truth policy

``projection`` is the **sole outward-facing truth** for system status.
UI surfaces must consume projection output; they must not maintain
parallel state or reconstruct truth independently.

Main API
--------
:data:`CANONICAL_AUTHORITY_LABELS`
    Frozenset of valid canonical authority-role string labels.

:data:`LEGACY_BOUNDARY_LABELS`
    Frozenset of valid legacy/compatibility boundary labels.

:data:`AUTHORITY_CHAIN`
    Ordered tuple of ``(layer_key, expected_authority_label)`` pairs
    representing the canonical chain from outer to inner.

:func:`check_authority_labels_consistent`
    Verify that a metadata dict uses only known authority labels.

:func:`check_canonical_legacy_markers_uniform`
    Verify that canonical/legacy markers in a metadata collection are
    internally consistent (no surface claims both).

:func:`check_projection_is_outward_truth`
    Verify that projection metadata does not conflict with the
    outward-truth policy.

:func:`check_addon_contract_metadata_uniform`
    Verify that installable addon/package contract metadata has the
    expected fields across a registry snapshot.

:func:`run_consolidation_invariants`
    Run all cross-cutting checks and return a :class:`ConsolidationReport`.

Usage::

    from tools.architecture.architecture_invariants import (
        CANONICAL_AUTHORITY_LABELS,
        LEGACY_BOUNDARY_LABELS,
        AUTHORITY_CHAIN,
        run_consolidation_invariants,
    )

    report = run_consolidation_invariants(
        authority_metadata={"role": "subject_decision_authority"},
        surface_metadata=[
            {"surface_id": "dashboard.backend.main", "role": "legacy_ui"},
            {"surface_id": "windows_client.status_board_v2", "role": "projection_driven"},
        ],
        projection_metadata={"is_outward_truth": True, "source": "projection"},
        addon_registry_snapshot=[
            {"addon_id": "my_skill", "contract_type": "skill_package", "version": "1.0.0"},
        ],
    )
    assert report.overall_consistent
"""

from __future__ import annotations

import dataclasses
import logging
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

logger = logging.getLogger("Galaxy.ArchInvariants")

__all__ = [
    # Constants
    "CANONICAL_AUTHORITY_LABELS",
    "LEGACY_BOUNDARY_LABELS",
    "PROJECTION_TRUTH_MARKERS",
    "AUTHORITY_CHAIN",
    "CANONICAL_ADDON_CONTRACT_TYPES",
    # Data types
    "InvariantSeverity",
    "InvariantFinding",
    "ConsolidationReport",
    # Individual checks
    "check_authority_labels_consistent",
    "check_canonical_legacy_markers_uniform",
    "check_projection_is_outward_truth",
    "check_addon_contract_metadata_uniform",
    "check_canonical_layer_model_consistent",
    # Aggregate entry point
    "run_consolidation_invariants",
]

# ---------------------------------------------------------------------------
# Canonical constant sets
# ---------------------------------------------------------------------------

#: The set of valid canonical authority-role string labels used across the
#: authority-chain metadata in the Galaxy architecture.
#:
#: These labels are stable serialisation-safe strings that appear in:
#: - ``authority_metadata["layer_role"]`` (DesktopPresenceRuntime)
#: - ``metadata["authority_role"]`` (OpenClawd)
#: - ``authority_role`` field (AgentKernel / KernelResponse)
#: - ``execution_substrate_role`` (CommandRouter)
CANONICAL_AUTHORITY_LABELS: FrozenSet[str] = frozenset(
    {
        "runtime_shell_authority",
        "subject_decision_authority",
        "cognition_planning_layer",
        "execution_substrate",
        "orchestration_coordinator",  # permitted auxiliary role
        "orchestration_layer",  # orchestration layer auxiliary role
    }
)

#: The set of valid legacy / compatibility boundary labels.  Any surface or
#: path that carries one of these labels is NOT the primary architecture path.
LEGACY_BOUNDARY_LABELS: FrozenSet[str] = frozenset(
    {
        "legacy_ui",
        "legacy_shell",
        "legacy_compatibility",
        "compatibility_fallback",
        "deprecated",
        "LEGACY_UI",
        "LEGACY_SHELL",
        "LEGACY_COMPATIBILITY",
        "COMPATIBILITY_ONLY",
        "DEPRECATED",
    }
)

#: Labels that identify a surface or datum as the canonical outward truth
#: for projection/status.
PROJECTION_TRUTH_MARKERS: FrozenSet[str] = frozenset(
    {
        "projection_driven",
        "PROJECTION_DRIVEN",
        "outward_truth",
        "canonical_outward_status",
    }
)

#: Ordered canonical authority chain as ``(snapshot_key, expected_role_label)``
#: pairs from outer (highest authority) to inner (lowest authority).
AUTHORITY_CHAIN: Tuple[Tuple[str, str], ...] = (
    ("runtime_shell", "runtime_shell_authority"),
    ("subject_core", "subject_decision_authority"),
    ("cognition_layer", "cognition_planning_layer"),
    ("execution_substrate", "execution_substrate"),
)

#: Known canonical addon/package contract types for MCP and Skill installs.
CANONICAL_ADDON_CONTRACT_TYPES: FrozenSet[str] = frozenset(
    {
        "mcp_addon",
        "skill_package",
        "mcp_server",
        "skill_md",
    }
)

#: Required metadata fields for a well-formed addon/package registry entry.
_REQUIRED_ADDON_FIELDS: Tuple[str, ...] = ("addon_id", "contract_type", "version")

# ---------------------------------------------------------------------------
# Finding data types
# ---------------------------------------------------------------------------


class InvariantSeverity(str, Enum):
    """Severity level for a :class:`InvariantFinding`."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclasses.dataclass(frozen=True)
class InvariantFinding:
    """A single finding produced by a cross-cutting invariant check."""

    check: str
    """Short identifier for the check that produced this finding."""

    severity: str
    """String value from :class:`InvariantSeverity`."""

    message: str
    """Human-readable description of the finding."""

    detail: Dict[str, Any] = dataclasses.field(default_factory=dict)
    """Optional structured detail for tooling / test assertions."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "message": self.message,
            "detail": self.detail,
        }


@dataclasses.dataclass
class ConsolidationReport:
    """Aggregated result of all cross-cutting consolidation invariant checks."""

    findings: List[InvariantFinding] = dataclasses.field(default_factory=list)
    checks_run: List[str] = dataclasses.field(default_factory=list)
    overall_consistent: bool = True

    # computed lazily in __post_init__
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0

    def __post_init__(self) -> None:
        self._recompute()

    def _recompute(self) -> None:
        self.error_count = sum(
            1 for f in self.findings if f.severity == InvariantSeverity.ERROR.value
        )
        self.warning_count = sum(
            1 for f in self.findings if f.severity == InvariantSeverity.WARNING.value
        )
        self.info_count = sum(
            1 for f in self.findings if f.severity == InvariantSeverity.INFO.value
        )
        self.overall_consistent = self.error_count == 0

    def add(self, finding: InvariantFinding) -> None:
        self.findings.append(finding)
        self._recompute()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_consistent": self.overall_consistent,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "checks_run": list(self.checks_run),
            "findings": [f.to_dict() for f in self.findings],
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make(
    check: str,
    severity: InvariantSeverity,
    message: str,
    detail: Optional[Dict[str, Any]] = None,
) -> InvariantFinding:
    return InvariantFinding(
        check=check,
        severity=severity.value,
        message=message,
        detail=detail or {},
    )


def _err(check: str, message: str, detail: Optional[Dict[str, Any]] = None) -> InvariantFinding:
    return _make(check, InvariantSeverity.ERROR, message, detail)


def _warn(check: str, message: str, detail: Optional[Dict[str, Any]] = None) -> InvariantFinding:
    return _make(check, InvariantSeverity.WARNING, message, detail)


def _info(check: str, message: str, detail: Optional[Dict[str, Any]] = None) -> InvariantFinding:
    return _make(check, InvariantSeverity.INFO, message, detail)


# ---------------------------------------------------------------------------
# Individual invariant checks
# ---------------------------------------------------------------------------


def check_authority_labels_consistent(
    authority_metadata: Dict[str, Any],
) -> List[InvariantFinding]:
    """Check that authority labels in *authority_metadata* use the canonical vocabulary.

    Scans all string values (recursively, one level deep) for any value that
    looks like an authority-role label (ends with ``_authority`` or ``_layer``
    or ``_substrate``) and verifies that it appears in
    :data:`CANONICAL_AUTHORITY_LABELS`.

    Parameters
    ----------
    authority_metadata:
        A flat or one-level-nested dict of authority metadata, typically from
        a diagnostic snapshot or an API response payload.

    Returns
    -------
    List[InvariantFinding]
        Empty list when all labels are consistent; one ERROR per unknown label.
    """
    check = "AUTHORITY_LABELS_CONSISTENT"
    findings: List[InvariantFinding] = []

    def _scan(d: Any, path: str) -> None:
        if isinstance(d, dict):
            for k, v in d.items():
                _scan(v, f"{path}.{k}")
        elif isinstance(d, str):
            _looks_like_role = any(
                d.endswith(suffix)
                for suffix in (
                    "_authority",
                    "_layer",
                    "_substrate",
                    "_coordinator",
                    "_shell",
                )
            )
            if _looks_like_role and d not in CANONICAL_AUTHORITY_LABELS:
                findings.append(
                    _err(
                        check,
                        f"Unknown authority label '{d}' at path '{path}'. "
                        f"Expected one of: {sorted(CANONICAL_AUTHORITY_LABELS)}.",
                        {"label": d, "path": path},
                    )
                )

    _scan(authority_metadata, "root")

    if not findings:
        findings.append(
            _info(check, "All authority labels are consistent with canonical vocabulary.")
        )

    return findings


def check_canonical_legacy_markers_uniform(
    surface_metadata: Sequence[Dict[str, Any]],
    *,
    role_key: str = "role",
    surface_id_key: str = "surface_id",
) -> List[InvariantFinding]:
    """Check that canonical/legacy markers across a collection of surfaces are uniform.

    A surface that carries both a canonical-authority label AND a legacy label
    is flagged as an error (inconsistent dual-labeling).  A surface that carries
    neither is flagged as a warning.

    Parameters
    ----------
    surface_metadata:
        A sequence of dicts, each representing a UI surface, module, or
        diagnostic entry.  Each dict should have a ``role`` field (or the
        key named by *role_key*) and an optional identifier field.
    role_key:
        Dict key to look up the role label.  Defaults to ``"role"``.
    surface_id_key:
        Dict key to use as a human-readable surface identifier.  Defaults to
        ``"surface_id"``.

    Returns
    -------
    List[InvariantFinding]
        Findings for each inconsistency detected.
    """
    check = "CANONICAL_LEGACY_MARKERS_UNIFORM"
    findings: List[InvariantFinding] = []

    for entry in surface_metadata:
        role = entry.get(role_key, "")
        sid = entry.get(surface_id_key, str(entry))

        is_canonical = role in CANONICAL_AUTHORITY_LABELS or role in PROJECTION_TRUTH_MARKERS
        is_legacy = role in LEGACY_BOUNDARY_LABELS

        if is_canonical and is_legacy:
            findings.append(
                _err(
                    check,
                    f"Surface '{sid}' carries both a canonical and a legacy role label: '{role}'.",
                    {"surface_id": sid, "role": role},
                )
            )
        elif not is_canonical and not is_legacy:
            findings.append(
                _warn(
                    check,
                    f"Surface '{sid}' has role '{role}' which is neither a known "
                    "canonical nor a known legacy label.",
                    {"surface_id": sid, "role": role},
                )
            )
        else:
            findings.append(
                _info(
                    check,
                    f"Surface '{sid}' correctly labeled as "
                    f"{'canonical' if is_canonical else 'legacy'} (role='{role}').",
                    {"surface_id": sid, "role": role},
                )
            )

    if not surface_metadata:
        findings.append(_info(check, "No surfaces to check — trivially uniform."))

    return findings


def check_projection_is_outward_truth(
    projection_metadata: Dict[str, Any],
) -> List[InvariantFinding]:
    """Check that projection metadata is consistent with the outward-truth policy.

    The policy states: projection is the **sole** outward-facing truth for
    system status.  Any metadata dict that represents a projection surface
    must carry a recognised projection-truth marker and must NOT claim a
    legacy role.

    Parameters
    ----------
    projection_metadata:
        A dict describing a projection surface or status-projection response.
        Expected to carry keys such as ``"is_outward_truth"``, ``"source"``,
        ``"role"``, or ``"surface_role"``.

    Returns
    -------
    List[InvariantFinding]
        Findings for each policy violation detected.
    """
    check = "PROJECTION_OUTWARD_TRUTH"
    findings: List[InvariantFinding] = []

    role = projection_metadata.get("role") or projection_metadata.get("surface_role", "")
    source = projection_metadata.get("source", "")
    is_outward_truth = projection_metadata.get("is_outward_truth", None)

    # If is_outward_truth is explicitly False, that is a policy violation for
    # a surface that claims to be projection.
    if is_outward_truth is False:
        findings.append(
            _err(
                check,
                "Projection surface explicitly declares is_outward_truth=False, "
                "which violates the projection-only outward-truth policy.",
                {"is_outward_truth": False},
            )
        )

    # If the surface carries a legacy role, flag it.
    if role and role in LEGACY_BOUNDARY_LABELS:
        findings.append(
            _err(
                check,
                f"Projection metadata carries a legacy role label '{role}'. "
                "Projection surfaces must not be labeled as legacy.",
                {"role": role},
            )
        )

    # Warn if neither a known canonical source marker nor an outward-truth marker.
    canonical_source = source in {"projection", "runtime_projection", "desktop_status_projection"}
    has_truth_marker = role in PROJECTION_TRUTH_MARKERS
    if not canonical_source and not has_truth_marker and is_outward_truth is not True:
        findings.append(
            _warn(
                check,
                "Projection metadata does not carry a recognised canonical source or "
                "outward-truth marker.  Expected source in "
                "{'projection', 'runtime_projection', 'desktop_status_projection'} or "
                f"role in {sorted(PROJECTION_TRUTH_MARKERS)}.",
                {"source": source, "role": role},
            )
        )
    elif not findings:
        findings.append(
            _info(
                check,
                "Projection metadata is consistent with the outward-truth policy.",
                {"source": source, "role": role},
            )
        )

    return findings


def check_addon_contract_metadata_uniform(
    addon_registry_snapshot: Sequence[Dict[str, Any]],
) -> List[InvariantFinding]:
    """Check that installable addon/package contract metadata is well-formed.

    Each entry in *addon_registry_snapshot* must carry the required fields
    (:data:`_REQUIRED_ADDON_FIELDS`) and a ``contract_type`` that appears in
    :data:`CANONICAL_ADDON_CONTRACT_TYPES`.

    Parameters
    ----------
    addon_registry_snapshot:
        A sequence of dicts, each representing a registered addon/package
        contract entry.

    Returns
    -------
    List[InvariantFinding]
        Findings for each malformed or unrecognised entry.
    """
    check = "ADDON_CONTRACT_METADATA_UNIFORM"
    findings: List[InvariantFinding] = []

    for i, entry in enumerate(addon_registry_snapshot):
        addon_id = entry.get("addon_id", f"<entry[{i}]>")

        # Check required fields.
        for field in _REQUIRED_ADDON_FIELDS:
            if field not in entry:
                findings.append(
                    _err(
                        check,
                        f"Addon entry '{addon_id}' is missing required field '{field}'.",
                        {"addon_id": addon_id, "missing_field": field},
                    )
                )

        # Check contract_type is known.
        contract_type = entry.get("contract_type")
        if contract_type is not None and contract_type not in CANONICAL_ADDON_CONTRACT_TYPES:
            findings.append(
                _warn(
                    check,
                    f"Addon entry '{addon_id}' has contract_type='{contract_type}' "
                    f"which is not in the canonical set: {sorted(CANONICAL_ADDON_CONTRACT_TYPES)}.",
                    {"addon_id": addon_id, "contract_type": contract_type},
                )
            )
        elif contract_type is not None:
            findings.append(
                _info(
                    check,
                    f"Addon entry '{addon_id}' has valid contract_type='{contract_type}'.",
                    {"addon_id": addon_id, "contract_type": contract_type},
                )
            )

    if not addon_registry_snapshot:
        findings.append(_info(check, "No addon entries to check — trivially uniform."))

    return findings


def check_canonical_layer_model_consistent(
    layer_snapshots: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[InvariantFinding]:
    """Check that the canonical layer model is internally consistent.

    Delegates to :mod:`core.canonical_layer_model` to validate:

    1. All five canonical layers are declared in the registry.
    2. Each layer's hot-path and startup-only flags match the canonical model.
    3. V4 (multi-step orchestration spine) is NOT declared as a per-request gate.
    4. V6 (startup/release integrity) is NOT declared as a per-request gate.
    5. L1/L2/L3 (router cognitive authority) is NOT declared as a detached
       shadow stack.
    6. Completion truth backbone is NOT declared as optional signaling.

    Parameters
    ----------
    layer_snapshots:
        Optional sequence of layer snapshot dicts to validate.  Each must
        carry a ``layer_key`` field.  When ``None`` the check validates
        only the registry internal consistency.

    Returns
    -------
    List[InvariantFinding]
        Findings translated from the underlying
        :class:`~core.canonical_layer_model.LayerModelReport`.
    """
    check = "CANONICAL_LAYER_MODEL_CONSISTENT"
    findings: List[InvariantFinding] = []

    try:
        from core.canonical_layer_model import run_layer_model_invariants
    except ImportError as exc:
        findings.append(
            _err(
                check,
                f"core.canonical_layer_model is not importable: {exc}.  "
                "The canonical layer model must be present for architecture "
                "invariants to be checkable.",
                {"import_error": str(exc)},
            )
        )
        return findings

    snapshots_list = list(layer_snapshots) if layer_snapshots is not None else None
    report = run_layer_model_invariants(snapshots_list)

    for lf in report.findings:
        if lf.severity == "error":
            findings.append(_err(check, lf.message, lf.detail))
        elif lf.severity == "warning":
            findings.append(_warn(check, lf.message, lf.detail))
        else:
            findings.append(_info(check, lf.message, lf.detail))

    if not findings:
        findings.append(
            _info(check, "Canonical layer model is internally consistent.")
        )

    return findings


# ---------------------------------------------------------------------------
# Aggregate entry point
# ---------------------------------------------------------------------------


def run_consolidation_invariants(
    authority_metadata: Optional[Dict[str, Any]] = None,
    surface_metadata: Optional[Sequence[Dict[str, Any]]] = None,
    projection_metadata: Optional[Dict[str, Any]] = None,
    addon_registry_snapshot: Optional[Sequence[Dict[str, Any]]] = None,
    layer_snapshots: Optional[Sequence[Dict[str, Any]]] = None,
) -> ConsolidationReport:
    """Run all cross-cutting consolidation invariant checks.

    This is the main entry point for obtaining a :class:`ConsolidationReport`
    that covers all five categories of cross-cutting invariants:

    1. Authority label consistency
    2. Canonical vs legacy marker uniformity
    3. Projection outward-truth compliance
    4. Addon contract metadata uniformity
    5. Canonical layer model consistency (PR-9)

    Parameters
    ----------
    authority_metadata:
        Dict of authority metadata to check for label consistency.  Pass
        ``None`` to skip the authority-label check.
    surface_metadata:
        Sequence of surface metadata dicts to check for canonical/legacy
        marker uniformity.  Pass ``None`` or empty to skip.
    projection_metadata:
        Dict describing a projection surface.  Pass ``None`` to skip.
    addon_registry_snapshot:
        Sequence of addon/package registry entries.  Pass ``None`` to skip.
    layer_snapshots:
        Optional sequence of layer snapshot dicts for the canonical layer
        model check.  Pass ``None`` to run only the registry self-consistency
        check (added in PR-9).

    Returns
    -------
    ConsolidationReport
        Aggregated report.  ``report.overall_consistent`` is ``True`` when no
        ERROR-severity findings were produced.
    """
    report = ConsolidationReport()

    if authority_metadata is not None:
        check_name = "AUTHORITY_LABELS_CONSISTENT"
        report.checks_run.append(check_name)
        for finding in check_authority_labels_consistent(authority_metadata):
            report.add(finding)

    if surface_metadata is not None:
        check_name = "CANONICAL_LEGACY_MARKERS_UNIFORM"
        report.checks_run.append(check_name)
        for finding in check_canonical_legacy_markers_uniform(surface_metadata):
            report.add(finding)

    if projection_metadata is not None:
        check_name = "PROJECTION_OUTWARD_TRUTH"
        report.checks_run.append(check_name)
        for finding in check_projection_is_outward_truth(projection_metadata):
            report.add(finding)

    if addon_registry_snapshot is not None:
        check_name = "ADDON_CONTRACT_METADATA_UNIFORM"
        report.checks_run.append(check_name)
        for finding in check_addon_contract_metadata_uniform(addon_registry_snapshot):
            report.add(finding)

    # PR-9: canonical layer model check — always run.
    check_name = "CANONICAL_LAYER_MODEL_CONSISTENT"
    report.checks_run.append(check_name)
    for finding in check_canonical_layer_model_consistent(layer_snapshots):
        report.add(finding)

    # Log summary.
    if report.overall_consistent:
        logger.debug(
            "Architecture consolidation invariants: all checks passed (errors=0, "
            "warnings=%d, infos=%d)",
            report.warning_count,
            report.info_count,
        )
    else:
        logger.warning(
            "Architecture consolidation invariants: %d error(s) found — "
            "overall_consistent=False",
            report.error_count,
        )

    return report
