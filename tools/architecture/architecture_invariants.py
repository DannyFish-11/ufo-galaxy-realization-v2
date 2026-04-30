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
import importlib
import logging
from enum import Enum
from pathlib import Path
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
    # Terminal regression guards (PR-10)
    "TerminalRegressionReport",
    "check_v4_not_universal_per_request_gate",
    "check_v6_not_in_hot_request_path",
    "check_l1_l2_l3_in_router_authority",
    "check_completion_truth_is_enforced",
    "check_canonical_declarations_consistent",
    "run_terminal_regression_guards",
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


# ===========================================================================
# PR-10 Terminal Architecture Regression Guards
# ===========================================================================
#
# These five checks detect the key invalid architecture regressions that must
# not be reintroduced after the PR-1–PR-9 alignment sequence.  Each check is
# a pure function operating on importable modules and/or source-file content;
# none alters any runtime state.
#
# Regression categories guarded:
#   1. V4 reclassified as a universal per-request gate.
#   2. V6 inserted into hot request paths.
#   3. L1/L2/L3 detached from the router-level authority (UnifiedLLMRouter).
#   4. Canonical completion truth backbone weakened into optional soft signaling.
#   5. Repository-level architecture declarations contradict the final model.


@dataclasses.dataclass
class TerminalRegressionReport:
    """Aggregated result of all terminal architecture regression guard checks.

    Attributes
    ----------
    findings:
        All :class:`InvariantFinding` objects produced by the five guards.
    checks_run:
        Ordered list of check-name strings that were executed.
    overall_pass:
        ``True`` when no ERROR-severity findings were produced.
    error_count:
        Number of ERROR-severity findings.
    warning_count:
        Number of WARNING-severity findings.
    """

    findings: List[InvariantFinding] = dataclasses.field(default_factory=list)
    checks_run: List[str] = dataclasses.field(default_factory=list)
    overall_pass: bool = True
    error_count: int = 0
    warning_count: int = 0

    def __post_init__(self) -> None:
        self._recompute()

    def _recompute(self) -> None:
        self.error_count = sum(
            1 for f in self.findings if f.severity == InvariantSeverity.ERROR.value
        )
        self.warning_count = sum(
            1 for f in self.findings if f.severity == InvariantSeverity.WARNING.value
        )
        self.overall_pass = self.error_count == 0

    def add(self, finding: InvariantFinding) -> None:
        self.findings.append(finding)
        self._recompute()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_pass": self.overall_pass,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "checks_run": list(self.checks_run),
            "findings": [f.to_dict() for f in self.findings],
        }


# ---------------------------------------------------------------------------
# Guard 1 — V4 must NOT be a universal per-request gate
# ---------------------------------------------------------------------------

#: Source files whose content must NOT import unified_orchestration_spine at
#: the per-request dispatch level.  These are the canonical hot-path modules.
_V4_HOT_PATH_FILES: Tuple[str, ...] = (
    "core/command_router.py",
    "core/execution_spine.py",
    "core/openclawd.py",
)

#: Token whose presence in a hot-path file signals a V4 gate regression.
_V4_IMPORT_TOKEN: str = "unified_orchestration_spine"


def check_v4_not_universal_per_request_gate(
    project_root: Optional[Path] = None,
) -> List[InvariantFinding]:
    """Detect the V4-as-universal-per-request-gate regression.

    Two complementary checks are run:

    1. **Sentinel check** — ``core.unified_orchestration_spine`` must be
       importable and must carry ``V4_IS_NOT_PER_REQUEST_GATE_POLICY``
       containing the "NOT" keyword, confirming that the module itself still
       declares the correct scope.

    2. **Hot-path isolation check** — the canonical per-request hot-path
       source files (``core/command_router.py``, ``core/execution_spine.py``,
       ``core/openclawd.py``) must not import
       ``unified_orchestration_spine``.  An import there would indicate that
       V4 has been wired as a synchronous gate on every per-request call.

    Parameters
    ----------
    project_root:
        Root path of the repository.  Defaults to the directory three levels
        above this file (``<repo>/``).

    Returns
    -------
    List[InvariantFinding]
        Empty list on success; ERROR findings for each regression detected.
    """
    check = "V4_NOT_UNIVERSAL_PER_REQUEST_GATE"
    findings: List[InvariantFinding] = []
    root = project_root or Path(__file__).parent.parent.parent

    # 1. Sentinel check.
    try:
        spine = importlib.import_module("core.unified_orchestration_spine")
        policy = getattr(spine, "V4_IS_NOT_PER_REQUEST_GATE_POLICY", None)
        if policy is None:
            findings.append(
                _err(
                    check,
                    "core.unified_orchestration_spine is missing "
                    "V4_IS_NOT_PER_REQUEST_GATE_POLICY sentinel.  "
                    "This sentinel is the machine-checkable declaration that V4 "
                    "is NOT the universal per-request gate.",
                    {"module": "core.unified_orchestration_spine",
                     "missing_attr": "V4_IS_NOT_PER_REQUEST_GATE_POLICY"},
                )
            )
        elif "NOT" not in str(policy) and "not" not in str(policy).lower():
            findings.append(
                _err(
                    check,
                    "V4_IS_NOT_PER_REQUEST_GATE_POLICY does not contain the "
                    "required 'NOT' keyword.  The policy must explicitly state "
                    "that V4 is NOT the per-request gate.",
                    {"policy_value": str(policy)[:120]},
                )
            )
        else:
            findings.append(
                _info(
                    check,
                    "V4_IS_NOT_PER_REQUEST_GATE_POLICY sentinel is present and "
                    "correctly contains NOT language.",
                )
            )
    except ImportError as exc:
        findings.append(
            _err(
                check,
                f"core.unified_orchestration_spine is not importable: {exc}.  "
                "The V4 spine module must be present for the scope guard to work.",
                {"import_error": str(exc)},
            )
        )

    # 2. Hot-path isolation check.
    for rel_path in _V4_HOT_PATH_FILES:
        fpath = root / rel_path
        if not fpath.exists():
            findings.append(
                _info(check, f"Hot-path file '{rel_path}' not found — skipping isolation check.")
            )
            continue
        content = fpath.read_text(encoding="utf-8", errors="replace")
        if _V4_IMPORT_TOKEN in content:
            # Allow import only if it is in a comment or in a non-request scope.
            # A simple heuristic: flag if it appears in an import statement line.
            import_lines = [
                line.strip() for line in content.splitlines()
                if _V4_IMPORT_TOKEN in line and line.strip().startswith(("import ", "from "))
            ]
            if import_lines:
                findings.append(
                    _err(
                        check,
                        f"Hot-path file '{rel_path}' imports "
                        f"'{_V4_IMPORT_TOKEN}'.  V4 must not be wired into the "
                        "per-request dispatch path — this is the V4-as-universal-gate "
                        "regression.",
                        {"file": rel_path, "import_lines": import_lines[:3]},
                    )
                )
            else:
                findings.append(
                    _info(
                        check,
                        f"Hot-path file '{rel_path}': '{_V4_IMPORT_TOKEN}' appears "
                        "only in non-import context (e.g. comment/docstring) — "
                        "isolation check passes.",
                    )
                )
        else:
            findings.append(
                _info(
                    check,
                    f"Hot-path file '{rel_path}' does not import "
                    f"'{_V4_IMPORT_TOKEN}' — V4 hot-path isolation confirmed.",
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Guard 2 — V6 must NOT be in hot request paths
# ---------------------------------------------------------------------------

#: Tokens whose presence inside a per-request dispatch method signals a V6
#: hot-path insertion regression.
_V6_HOT_PATH_TOKENS: Tuple[str, ...] = (
    "center_authority_boundary",
    "evaluate_center_authority_boundary",
    "assert_center_authority_intact",
    "release_blocking_gate",
)

#: Per-request method names to scan for V6 token intrusion.
_V6_SCANNED_METHODS: Tuple[str, ...] = (
    "def process(",
    "def route_envelope(",
)

#: How many characters to scan inside each method body.
_METHOD_SCAN_WINDOW: int = 3000


def check_v6_not_in_hot_request_path(
    project_root: Optional[Path] = None,
) -> List[InvariantFinding]:
    """Detect the V6-in-hot-path regression.

    V6 (``core.release_blocking_gate`` / ``core.center_authority_boundary``)
    is the startup / readiness / health / release integrity boundary layer.
    It must NOT appear inside synchronous per-request dispatch methods such as
    ``OpenClawd.process()`` or ``CommandRouter.route_envelope()``.

    The check scans the first :data:`_METHOD_SCAN_WINDOW` characters of each
    listed method for any of the V6 tokens.

    Parameters
    ----------
    project_root:
        Root path of the repository.

    Returns
    -------
    List[InvariantFinding]
        ERROR findings for each V6-in-hot-path regression detected.
    """
    check = "V6_NOT_IN_HOT_REQUEST_PATH"
    findings: List[InvariantFinding] = []
    root = project_root or Path(__file__).parent.parent.parent

    scanned_files = {
        "core/openclawd.py": ("def process(",),
        "core/command_router.py": ("def route_envelope(",),
    }

    for rel_path, method_sigs in scanned_files.items():
        fpath = root / rel_path
        if not fpath.exists():
            findings.append(
                _info(check, f"File '{rel_path}' not found — skipping V6 hot-path scan.")
            )
            continue

        content = fpath.read_text(encoding="utf-8", errors="replace")

        for method_sig in method_sigs:
            method_idx = content.find(method_sig)
            if method_idx == -1:
                findings.append(
                    _info(
                        check,
                        f"Method '{method_sig.strip()}' not found in '{rel_path}' — skipping.",
                    )
                )
                continue

            method_body = content[method_idx: method_idx + _METHOD_SCAN_WINDOW]
            violated_tokens = [t for t in _V6_HOT_PATH_TOKENS if t in method_body]

            if violated_tokens:
                findings.append(
                    _err(
                        check,
                        f"'{rel_path}' method '{method_sig.strip()}' contains V6 "
                        f"boundary token(s) {violated_tokens!r}.  "
                        "V6 (release_blocking_gate / center_authority_boundary) must "
                        "not be called inside per-request dispatch methods — this is "
                        "the V6-in-hot-path regression.",
                        {
                            "file": rel_path,
                            "method": method_sig.strip(),
                            "violated_tokens": violated_tokens,
                        },
                    )
                )
            else:
                findings.append(
                    _info(
                        check,
                        f"'{rel_path}' method '{method_sig.strip()}': no V6 tokens "
                        "detected — V6 hot-path exclusion confirmed.",
                    )
                )

    return findings


# ---------------------------------------------------------------------------
# Guard 3 — L1/L2/L3 must remain in the router-level authority
# ---------------------------------------------------------------------------


def check_l1_l2_l3_in_router_authority() -> List[InvariantFinding]:
    """Detect the L1/L2/L3-detached-from-router regression.

    L1 (:class:`~core.llm.route_authority.LLMRouteAuthority`),
    L2 (:class:`~core.llm.supply_authority.LLMSupplyAuthority`), and
    L3 (:class:`~core.llm.context_authority.CognitiveContextAuthority`) must
    be fused into :class:`~core.unified.llm_router.UnifiedLLMRouter` via the
    ``_l1_authority``, ``_l2_authority``, and ``_l3_authority`` instance
    attributes.

    If ``UnifiedLLMRouter`` no longer initialises these attributes the
    cognitive authority layer is effectively detached from the router —
    the L1/L2/L3-shadow-stack regression.

    Returns
    -------
    List[InvariantFinding]
        ERROR findings for each missing integration point detected.
    """
    check = "L1_L2_L3_IN_ROUTER_AUTHORITY"
    findings: List[InvariantFinding] = []

    # Check that each authority sentinel is importable.
    sentinel_checks: Tuple[Tuple[str, str], ...] = (
        ("core.llm.route_authority", "LLM_ROUTE_AUTHORITY"),
        ("core.llm.supply_authority", "LLM_SUPPLY_AUTHORITY"),
        ("core.llm.context_authority", "LLM_CONTEXT_AUTHORITY"),
    )
    for mod_path, sentinel_name in sentinel_checks:
        try:
            mod = importlib.import_module(mod_path)
            sentinel = getattr(mod, sentinel_name, None)
            if sentinel is None:
                findings.append(
                    _err(
                        check,
                        f"{mod_path} is missing sentinel '{sentinel_name}'.  "
                        "The authority module must declare its canonical sentinel "
                        "for the router integration guard to be meaningful.",
                        {"module": mod_path, "missing_attr": sentinel_name},
                    )
                )
            else:
                findings.append(
                    _info(check, f"{mod_path}.{sentinel_name} is present — authority module intact.")
                )
        except ImportError as exc:
            findings.append(
                _err(
                    check,
                    f"{mod_path} is not importable: {exc}.  "
                    "All three L1/L2/L3 authority modules must be importable for "
                    "the router-level cognitive authority to function.",
                    {"module": mod_path, "import_error": str(exc)},
                )
            )

    # Check that UnifiedLLMRouter initialises the three authority attributes.
    # Strategy: if the module file exists on disk (i.e., the integration is
    # present in the repository), but cannot be imported due to missing
    # optional runtime dependencies (e.g. pydantic, aiohttp), that is an
    # environment issue — not an architecture regression.  Downgrade to
    # WARNING.  Only emit an ERROR if the router source file itself is
    # absent (i.e., the integration was removed from the repository).
    _llm_router_src_path = Path(__file__).parent.parent.parent / "core" / "unified" / "llm_router.py"
    _router_file_exists = _llm_router_src_path.exists()

    if not _router_file_exists:
        findings.append(
            _err(
                check,
                "core/unified/llm_router.py does not exist in the repository.  "
                "The unified LLM router source file is required for L1/L2/L3 "
                "authority fusion — its absence is the L1/L2/L3-detached-from-router "
                "regression.",
                {"missing_file": "core/unified/llm_router.py"},
            )
        )
    else:
        try:
            llm_router_mod = importlib.import_module("core.unified.llm_router")
            router_cls = getattr(llm_router_mod, "UnifiedLLMRouter", None)
            if router_cls is None:
                findings.append(
                    _err(
                        check,
                        "core.unified.llm_router does not expose UnifiedLLMRouter.  "
                        "The router class is required for L1/L2/L3 fusion.",
                        {"module": "core.unified.llm_router", "missing_attr": "UnifiedLLMRouter"},
                    )
                )
            else:
                # Inspect the __init__ source for the authority attribute assignments.
                import inspect
                try:
                    init_src = inspect.getsource(router_cls.__init__)
                except (OSError, TypeError):
                    init_src = ""

                for attr in ("_l1_authority", "_l2_authority", "_l3_authority"):
                    if attr in init_src or hasattr(router_cls, attr):
                        findings.append(
                            _info(check, f"UnifiedLLMRouter declares '{attr}' — L1/L2/L3 integration present.")
                        )
                    else:
                        findings.append(
                            _err(
                                check,
                                f"UnifiedLLMRouter.__init__ does not initialise '{attr}'.  "
                                "This attribute is required for the L1/L2/L3 cognitive "
                                "authority to be fused into the router — its absence is "
                                "the L1/L2/L3-detached-from-router regression.",
                                {"missing_attr": attr},
                            )
                        )
        except ImportError as exc:
            # The source file exists but the module cannot be imported due to
            # missing optional dependencies.  Treat as WARNING (environment
            # issue), not ERROR (architecture regression).
            findings.append(
                _warn(
                    check,
                    f"core.unified.llm_router exists on disk but is not importable "
                    f"in this environment ({exc}).  "
                    "This is likely an optional dependency gap (e.g. pydantic) rather "
                    "than an architecture regression.  "
                    "Falling back to source-level attribute scan.",
                    {"module": "core.unified.llm_router", "import_error": str(exc)},
                )
            )
            # Fall back to source-level scan for the three authority attributes.
            src = _llm_router_src_path.read_text(encoding="utf-8", errors="replace")
            for attr in ("_l1_authority", "_l2_authority", "_l3_authority"):
                if attr in src:
                    findings.append(
                        _info(
                            check,
                            f"Source scan: '{attr}' found in llm_router.py — "
                            "L1/L2/L3 integration present at source level.",
                        )
                    )
                else:
                    findings.append(
                        _err(
                            check,
                            f"Source scan: '{attr}' NOT found in llm_router.py.  "
                            "This attribute is required for L1/L2/L3 fusion — "
                            "its absence in source is the detached-from-router regression.",
                            {"missing_attr": attr, "source_scan": True},
                        )
                    )

    return findings


# ---------------------------------------------------------------------------
# Guard 4 — Canonical completion truth must be enforced, not optional
# ---------------------------------------------------------------------------


def check_completion_truth_is_enforced() -> List[InvariantFinding]:
    """Detect the completion-truth-weakened-to-optional-signaling regression.

    The canonical completion truth backbone is implemented by
    ``core.task_result_canonical_truth_chain``.  Its
    ``TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY`` sentinel declares that the
    four truth-chain steps are mandatory for every ``task_result`` message.

    If the sentinel is absent, renamed, or its text no longer contains the
    word "MUST", the completion truth contract has been weakened — the
    optional-soft-signaling regression.

    Returns
    -------
    List[InvariantFinding]
        ERROR findings for each weakening of the completion truth contract.
    """
    check = "COMPLETION_TRUTH_ENFORCED_NOT_OPTIONAL"
    findings: List[InvariantFinding] = []

    try:
        trtc = importlib.import_module("core.task_result_canonical_truth_chain")
    except ImportError as exc:
        findings.append(
            _err(
                check,
                f"core.task_result_canonical_truth_chain is not importable: {exc}.  "
                "The canonical truth chain module must be present for the completion "
                "truth backbone to be enforced.",
                {"import_error": str(exc)},
            )
        )
        return findings

    # Check the must-run policy sentinel.
    policy = getattr(trtc, "TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY", None)
    if policy is None:
        findings.append(
            _err(
                check,
                "core.task_result_canonical_truth_chain is missing "
                "TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY sentinel.  "
                "This sentinel is the machine-checkable declaration that the "
                "completion truth chain is mandatory.",
                {"missing_attr": "TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY"},
            )
        )
    else:
        policy_str = str(policy)
        if "MUST" not in policy_str and "must" not in policy_str.lower():
            findings.append(
                _err(
                    check,
                    "TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY does not contain the "
                    "required 'MUST' keyword.  The policy must explicitly declare "
                    "the truth chain as mandatory (not optional).",
                    {"policy_excerpt": policy_str[:120]},
                )
            )
        else:
            findings.append(
                _info(
                    check,
                    "TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY is present and contains "
                    "mandatory 'MUST' language — completion truth enforcement confirmed.",
                )
            )

    # Check run_task_result_truth_chain is callable (not removed/stubbed).
    runner = getattr(trtc, "run_task_result_truth_chain", None)
    if runner is None or not callable(runner):
        findings.append(
            _err(
                check,
                "core.task_result_canonical_truth_chain.run_task_result_truth_chain "
                "is missing or not callable.  The entry point for the mandatory "
                "truth chain must remain callable.",
                {"missing_callable": "run_task_result_truth_chain"},
            )
        )
    else:
        findings.append(
            _info(check, "run_task_result_truth_chain is present and callable.")
        )

    # Check the optional enrichment policy to confirm it does NOT override the
    # mandatory steps (it must exist and must not claim the chain is optional).
    optional_policy = getattr(trtc, "TRUTH_CHAIN_OPTIONAL_ENRICHMENT_POLICY", None)
    if optional_policy is not None:
        opt_str = str(optional_policy)
        # The optional enrichment policy must not claim the truth chain itself
        # is optional — only enrichment steps (memory backflow etc.) are optional.
        if "chain" in opt_str.lower() and "optional" in opt_str.lower():
            # This is acceptable only if it refers to enrichment, not the chain.
            # Heuristic: flag if it says "truth chain is optional" but not "enrichment".
            if "enrichment" not in opt_str.lower():
                findings.append(
                    _err(
                        check,
                        "TRUTH_CHAIN_OPTIONAL_ENRICHMENT_POLICY appears to describe the "
                        "truth chain itself as optional, not merely enrichment steps.  "
                        "The canonical truth chain steps (ingress, reconcile, "
                        "authority_update, completion_linkage) are mandatory.",
                        {"policy_excerpt": opt_str[:120]},
                    )
                )
            else:
                findings.append(
                    _info(
                        check,
                        "TRUTH_CHAIN_OPTIONAL_ENRICHMENT_POLICY correctly scopes "
                        "optionality to enrichment steps only.",
                    )
                )

    return findings


# ---------------------------------------------------------------------------
# Guard 5 — Repository-level architecture declarations must be consistent
# ---------------------------------------------------------------------------


def check_canonical_declarations_consistent(
    layer_snapshots: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[InvariantFinding]:
    """Detect contradictory repository-level architecture declarations.

    Runs :func:`check_canonical_layer_model_consistent` (which delegates to
    :mod:`core.canonical_layer_model`) and additionally verifies that the
    terminal regression guard sentinel introduced by PR-10 is present in the
    module, confirming the module itself has not been silently downgraded.

    Parameters
    ----------
    layer_snapshots:
        Optional layer snapshots to validate.  Pass ``None`` to check only
        the registry self-consistency.

    Returns
    -------
    List[InvariantFinding]
        ERROR findings for each inconsistency or missing anchor sentinel.
    """
    check = "CANONICAL_DECLARATIONS_CONSISTENT"
    findings: List[InvariantFinding] = []

    # Delegate to the existing layer model check.
    for finding in check_canonical_layer_model_consistent(layer_snapshots):
        # Re-tag so the check name is the terminal-guard name.
        findings.append(
            InvariantFinding(
                check=check,
                severity=finding.severity,
                message=finding.message,
                detail=finding.detail,
            )
        )

    # Verify the PR-10 terminal regression anchor sentinel is present.
    try:
        clm = importlib.import_module("core.canonical_layer_model")
        anchor = getattr(clm, "TERMINAL_ARCHITECTURE_REGRESSION_GUARD_SENTINEL", None)
        if anchor is None:
            findings.append(
                _err(
                    check,
                    "core.canonical_layer_model is missing "
                    "TERMINAL_ARCHITECTURE_REGRESSION_GUARD_SENTINEL.  "
                    "This sentinel anchors the terminal regression guard series; "
                    "its absence means the terminal hardening PR-10 has been "
                    "reverted or partially undone.",
                    {"missing_attr": "TERMINAL_ARCHITECTURE_REGRESSION_GUARD_SENTINEL"},
                )
            )
        else:
            findings.append(
                _info(
                    check,
                    "TERMINAL_ARCHITECTURE_REGRESSION_GUARD_SENTINEL is present — "
                    "PR-10 terminal architecture anchor confirmed.",
                )
            )
    except ImportError as exc:
        findings.append(
            _err(
                check,
                f"core.canonical_layer_model is not importable: {exc}.",
                {"import_error": str(exc)},
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Aggregate entry point — run all five terminal regression guards
# ---------------------------------------------------------------------------


def run_terminal_regression_guards(
    project_root: Optional[Path] = None,
    layer_snapshots: Optional[Sequence[Dict[str, Any]]] = None,
) -> TerminalRegressionReport:
    """Run all five terminal architecture regression guards.

    This is the single entry point for PR-10 regression protection.  It
    executes the five named guards in order and returns an aggregated
    :class:`TerminalRegressionReport`.

    The five guards are:

    1. **V4_NOT_UNIVERSAL_PER_REQUEST_GATE** — V4 must not be wired as a
       synchronous gate on every per-request call.
    2. **V6_NOT_IN_HOT_REQUEST_PATH** — V6 boundary checks must not appear
       inside ``OpenClawd.process()`` or ``CommandRouter.route_envelope()``.
    3. **L1_L2_L3_IN_ROUTER_AUTHORITY** — L1/L2/L3 authority must remain
       integrated into ``UnifiedLLMRouter``.
    4. **COMPLETION_TRUTH_ENFORCED_NOT_OPTIONAL** — the canonical completion
       truth chain must not be weakened to optional soft signaling.
    5. **CANONICAL_DECLARATIONS_CONSISTENT** — repository-level architecture
       declarations must not contradict the final integrated layer model.

    Parameters
    ----------
    project_root:
        Root path of the repository.  Defaults to the directory three levels
        above this file.
    layer_snapshots:
        Optional layer snapshots to validate in guard 5.

    Returns
    -------
    TerminalRegressionReport
        Aggregated report.  ``report.overall_pass`` is ``True`` when all five
        guards produce zero ERROR-severity findings.
    """
    report = TerminalRegressionReport()

    _guard_calls: Tuple[Tuple[str, Any], ...] = (
        (
            "V4_NOT_UNIVERSAL_PER_REQUEST_GATE",
            lambda: check_v4_not_universal_per_request_gate(project_root),
        ),
        (
            "V6_NOT_IN_HOT_REQUEST_PATH",
            lambda: check_v6_not_in_hot_request_path(project_root),
        ),
        (
            "L1_L2_L3_IN_ROUTER_AUTHORITY",
            lambda: check_l1_l2_l3_in_router_authority(),
        ),
        (
            "COMPLETION_TRUTH_ENFORCED_NOT_OPTIONAL",
            lambda: check_completion_truth_is_enforced(),
        ),
        (
            "CANONICAL_DECLARATIONS_CONSISTENT",
            lambda: check_canonical_declarations_consistent(layer_snapshots),
        ),
    )

    for guard_name, guard_fn in _guard_calls:
        report.checks_run.append(guard_name)
        try:
            for finding in guard_fn():
                report.add(finding)
        except Exception as exc:  # pragma: no cover — guard must not crash the runner
            report.add(
                _err(
                    guard_name,
                    f"Guard '{guard_name}' raised an unexpected exception: {exc}.  "
                    "Guards must not raise exceptions; an exception here means the "
                    "guard itself is broken.",
                    {"exception": str(exc)},
                )
            )

    if report.overall_pass:
        logger.debug(
            "Terminal regression guards: all five guards passed (errors=0, warnings=%d)",
            report.warning_count,
        )
    else:
        logger.warning(
            "Terminal regression guards: %d error(s) detected — overall_pass=False",
            report.error_count,
        )

    return report
