#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.architecture_diagnostics — Architecture Diagnostics and Validation
========================================================================

PR-10 — Architecture Diagnostics and Validation Layer
PR-10 (Consolidation) — Added projection and canonical/legacy label checks.

Provides a lightweight, additive diagnostics and validation layer that
inspects and validates the intended architectural structure established
across PR-1 through PR-9.

The module answers questions like:
- Is the authority chain present and ordered as expected?
- Is the entry surface *not* claiming runtime-shell authority?
- Is ``DesktopPresenceRuntime`` above ``OpenClawd`` in the chain?
- Is ``OpenClawd`` above ``AgentKernel``?
- Is the execution substrate distinct from the orchestration layer?
- Are remote-execution mode and authority metadata mutually coherent?
- Is projection metadata coherent with the outward-truth policy?
- Are canonical and legacy labels mutually exclusive across all layers?

Design goals
------------
* **Additive and non-breaking** — diagnostics never alter execution logic.
* **Self-contained** — no network I/O; no live component instantiation.
* **Test-friendly** — helpers that accept plain dicts from existing
  response/metadata objects; no special instrumentation required in callers.
* **Structured output** — :class:`DiagnosticsReport` is a Pydantic model so
  results are serialisable to JSON.

Main API
--------
:func:`run_architecture_diagnostics`
    High-level entry point: runs all checks and returns a
    :class:`DiagnosticsReport`.

:func:`validate_authority_chain`
    Assert the authority chain is present and ordered outer → inner.

:func:`validate_layer_boundaries`
    Assert that no layer claims an authority that belongs to a different layer.

:func:`validate_remote_execution_coherence`
    Assert that remote-execution mode and authority metadata are mutually
    coherent when both are present in the same response/metadata dict.

:class:`ArchitectureDiagnostics`
    Stateful helper that accumulates findings and builds the report.

Usage (in tests)::

    from core.architecture_diagnostics import (
        run_architecture_diagnostics,
        validate_authority_chain,
        validate_layer_boundaries,
        validate_remote_execution_coherence,
        DiagnosticsReport,
    )

    # Build a representative flow snapshot from real or mock response dicts
    snapshot = {
        "runtime_shell": {
            "authority_metadata": {
                "layer_role": "runtime_shell_authority",
                "canonical_module": "core.desktop_presence_runtime",
            }
        },
        "subject_core": {
            "metadata": {"authority_role": "subject_decision_authority"}
        },
        "cognition_layer": {
            "authority_role": "cognition_planning_layer"
        },
        "execution_substrate": {
            "execution_substrate_role": "execution_substrate"
        },
    }
    report = run_architecture_diagnostics(snapshot)
    assert report.overall_valid
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger("Galaxy.ArchDiagnostics")

__all__ = [
    # Core data types
    "DiagnosticSeverity",
    "DiagnosticFinding",
    "DiagnosticsReport",
    # Validation helpers
    "validate_authority_chain",
    "validate_layer_boundaries",
    "validate_remote_execution_coherence",
    # High-level entry point
    "run_architecture_diagnostics",
    # Snapshot builder
    "build_diagnostics_snapshot_from_layers",
    # Stateful helper class
    "ArchitectureDiagnostics",
]


# ---------------------------------------------------------------------------
# Severity / Finding / Report models
# ---------------------------------------------------------------------------


class DiagnosticSeverity(str, Enum):
    """Severity level of a single diagnostic finding."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DiagnosticFinding(BaseModel):
    """A single diagnostic finding emitted by one invariant check.

    Attributes
    ----------
    code:
        Short machine-readable code identifying the invariant checked.
        Examples: ``"AUTHORITY_CHAIN_ORDERED"``, ``"LAYER_BOUNDARY_VIOLATION"``.
    severity:
        :class:`DiagnosticSeverity` of this finding.
    message:
        Human-readable description of the finding.
    detail:
        Optional additional context (e.g. conflicting values found).
    """

    code: str = Field(description="Short invariant check identifier.")
    severity: DiagnosticSeverity = Field(description="Severity level.")
    message: str = Field(description="Human-readable description.")
    detail: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional extra context."
    )

    model_config = {"use_enum_values": True}


class DiagnosticsReport(BaseModel):
    """Aggregated result of an architecture diagnostics run.

    Attributes
    ----------
    overall_valid:
        ``True`` when no ERROR-severity findings are present.
    findings:
        All findings produced during the run (info, warnings, errors).
    error_count:
        Number of ERROR findings.
    warning_count:
        Number of WARNING findings.
    info_count:
        Number of INFO findings.
    checks_run:
        Names of the invariant checks that were executed.
    """

    overall_valid: bool = Field(
        description="True when there are no ERROR-severity findings."
    )
    findings: List[DiagnosticFinding] = Field(default_factory=list)
    error_count: int = Field(default=0)
    warning_count: int = Field(default=0)
    info_count: int = Field(default=0)
    checks_run: List[str] = Field(default_factory=list)

    model_config = {"use_enum_values": True}

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "overall_valid": self.overall_valid,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "checks_run": list(self.checks_run),
            "findings": [
                {
                    "code": f.code,
                    "severity": f.severity,
                    "message": f.message,
                    **({"detail": f.detail} if f.detail else {}),
                }
                for f in self.findings
            ],
        }


# ---------------------------------------------------------------------------
# Canonical ordering reference
# ---------------------------------------------------------------------------

# The expected role order from outermost to innermost layer.
# An ENTRY_SURFACE that claims RUNTIME_SHELL_AUTHORITY would be a violation.
# A COGNITION_PLANNING_LAYER that calls out to RUNTIME_SHELL_AUTHORITY would
# invert the expected hierarchy.
_ROLE_ORDER: Dict[str, int] = {
    "entry_surface": 0,
    "runtime_shell_authority": 1,
    "subject_decision_authority": 2,
    "cognition_planning_layer": 3,
    "execution_substrate": 4,
    "orchestration_layer": 5,
    "compatibility_adapter": 6,
    "unknown": 99,
}

# Roles that should NOT be claimed by the entry/adapter surface
_AUTHORITY_ROLES = {
    "runtime_shell_authority",
    "subject_decision_authority",
    "cognition_planning_layer",
    "execution_substrate",
    "orchestration_layer",
}

# Expected role for each canonical layer key in the diagnostics snapshot dict
_LAYER_EXPECTED_ROLES: Dict[str, str] = {
    "runtime_shell": "runtime_shell_authority",
    "subject_core": "subject_decision_authority",
    "cognition_layer": "cognition_planning_layer",
    "execution_substrate": "execution_substrate",
    "orchestration_layer": "orchestration_layer",
}


# ---------------------------------------------------------------------------
# ArchitectureDiagnostics — stateful helper
# ---------------------------------------------------------------------------


class ArchitectureDiagnostics:
    """Accumulates diagnostic findings and builds a :class:`DiagnosticsReport`.

    This class is intentionally stateful so that multiple independent checks
    can add findings before a final report is produced.  It is not a singleton
    and is meant to be instantiated per diagnostics run.

    Parameters
    ----------
    snapshot:
        A dict (or ``None``) representing the architectural state to
        validate.  See :func:`run_architecture_diagnostics` for the
        expected shape.
    """

    def __init__(self, snapshot: Optional[Dict[str, Any]] = None) -> None:
        self._snapshot: Dict[str, Any] = snapshot or {}
        self._findings: List[DiagnosticFinding] = []
        self._checks_run: List[str] = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _add(
        self,
        code: str,
        severity: DiagnosticSeverity,
        message: str,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._findings.append(
            DiagnosticFinding(code=code, severity=severity, message=message, detail=detail)
        )

    def _info(self, code: str, message: str, detail: Optional[Dict[str, Any]] = None) -> None:
        self._add(code, DiagnosticSeverity.INFO, message, detail)

    def _warn(self, code: str, message: str, detail: Optional[Dict[str, Any]] = None) -> None:
        self._add(code, DiagnosticSeverity.WARNING, message, detail)

    def _error(self, code: str, message: str, detail: Optional[Dict[str, Any]] = None) -> None:
        self._add(code, DiagnosticSeverity.ERROR, message, detail)

    @staticmethod
    def _get_role(layer_data: Any) -> Optional[str]:
        """Extract the authority role string from a layer data dict."""
        if not isinstance(layer_data, dict):
            return None
        # Check common locations where role is stored
        # 1. authority_metadata.layer_role  (DesktopPresenceRuntime shape)
        auth_meta = layer_data.get("authority_metadata")
        if isinstance(auth_meta, dict):
            role = auth_meta.get("layer_role")
            if role:
                return str(role)
        # 2. metadata.authority_role  (OpenClawd shape)
        metadata = layer_data.get("metadata")
        if isinstance(metadata, dict):
            role = metadata.get("authority_role")
            if role:
                return str(role)
        # 3. authority_role  (KernelResponse / top-level shape)
        role = layer_data.get("authority_role")
        if role:
            return str(role)
        # 4. execution_substrate_role  (CommandRouter shape)
        role = layer_data.get("execution_substrate_role")
        if role:
            return str(role)
        return None

    # ------------------------------------------------------------------
    # Individual invariant checks
    # ------------------------------------------------------------------

    def check_entry_surface_not_authority(self) -> None:
        """ENTRY_SURFACE must not claim a runtime authority role."""
        check = "ENTRY_SURFACE_NOT_AUTHORITY"
        self._checks_run.append(check)
        entry = self._snapshot.get("entry_surface")
        if entry is None:
            self._info(check, "entry_surface layer not present in snapshot — skipping check.")
            return
        role = self._get_role(entry)
        if role and role in _AUTHORITY_ROLES:
            self._error(
                check,
                f"Entry surface is claiming authority role '{role}'; "
                "the entry surface must not hold subject-core authority.",
                {"found_role": role},
            )
        else:
            self._info(
                check,
                "Entry surface does not claim a runtime authority role — OK.",
                {"found_role": role},
            )

    def check_runtime_shell_above_subject_core(self) -> None:
        """RUNTIME_SHELL_AUTHORITY must be above SUBJECT_DECISION_AUTHORITY."""
        check = "RUNTIME_SHELL_ABOVE_SUBJECT_CORE"
        self._checks_run.append(check)
        shell_data = self._snapshot.get("runtime_shell")
        core_data = self._snapshot.get("subject_core")
        if shell_data is None or core_data is None:
            self._info(
                check,
                "runtime_shell or subject_core not present in snapshot — skipping check.",
            )
            return
        shell_role = self._get_role(shell_data)
        core_role = self._get_role(core_data)
        shell_ord = _ROLE_ORDER.get(shell_role or "unknown", 99)
        core_ord = _ROLE_ORDER.get(core_role or "unknown", 99)
        if shell_role == "runtime_shell_authority" and core_role == "subject_decision_authority":
            if shell_ord < core_ord:
                self._info(
                    check,
                    "runtime_shell_authority is correctly above subject_decision_authority.",
                )
            else:
                self._error(
                    check,
                    "runtime_shell_authority must be above (outer to) subject_decision_authority.",
                    {"shell_role": shell_role, "core_role": core_role},
                )
        else:
            if shell_role != "runtime_shell_authority":
                self._warn(
                    check,
                    f"runtime_shell layer reports unexpected role '{shell_role}'; "
                    "expected 'runtime_shell_authority'.",
                    {"found_role": shell_role},
                )
            if core_role != "subject_decision_authority":
                self._warn(
                    check,
                    f"subject_core layer reports unexpected role '{core_role}'; "
                    "expected 'subject_decision_authority'.",
                    {"found_role": core_role},
                )

    def check_openclawd_is_subject_decision_core(self) -> None:
        """OpenClawd must hold the SUBJECT_DECISION_AUTHORITY role."""
        check = "OPENCLAWD_IS_SUBJECT_DECISION_CORE"
        self._checks_run.append(check)
        core_data = self._snapshot.get("subject_core")
        if core_data is None:
            self._info(check, "subject_core not present in snapshot — skipping check.")
            return
        role = self._get_role(core_data)
        if role == "subject_decision_authority":
            canonical_module = None
            auth_meta = core_data.get("authority_metadata")
            if isinstance(auth_meta, dict):
                canonical_module = auth_meta.get("canonical_module")
            metadata = core_data.get("metadata")
            if canonical_module is None and isinstance(metadata, dict):
                canonical_module = metadata.get("canonical_module")
            if canonical_module and "openclawd" not in canonical_module:
                self._warn(
                    check,
                    f"subject_core claims subject_decision_authority but canonical_module "
                    f"'{canonical_module}' does not match 'core.openclawd'.",
                    {"canonical_module": canonical_module},
                )
            else:
                self._info(
                    check,
                    "OpenClawd (subject_core) correctly holds subject_decision_authority.",
                )
        else:
            self._error(
                check,
                f"subject_core layer role is '{role}'; expected 'subject_decision_authority'.",
                {"found_role": role},
            )

    def check_agent_kernel_is_cognition_layer(self) -> None:
        """AgentKernel must hold the COGNITION_PLANNING_LAYER role."""
        check = "AGENT_KERNEL_IS_COGNITION_LAYER"
        self._checks_run.append(check)
        kernel_data = self._snapshot.get("cognition_layer")
        if kernel_data is None:
            self._info(check, "cognition_layer not present in snapshot — skipping check.")
            return
        role = self._get_role(kernel_data)
        if role == "cognition_planning_layer":
            self._info(
                check,
                "AgentKernel (cognition_layer) correctly holds cognition_planning_layer.",
            )
        else:
            self._error(
                check,
                f"cognition_layer role is '{role}'; expected 'cognition_planning_layer'.",
                {"found_role": role},
            )

    def check_subject_core_above_cognition_layer(self) -> None:
        """SUBJECT_DECISION_AUTHORITY must be above COGNITION_PLANNING_LAYER."""
        check = "SUBJECT_CORE_ABOVE_COGNITION_LAYER"
        self._checks_run.append(check)
        core_data = self._snapshot.get("subject_core")
        kernel_data = self._snapshot.get("cognition_layer")
        if core_data is None or kernel_data is None:
            self._info(
                check,
                "subject_core or cognition_layer not present — skipping check.",
            )
            return
        core_role = self._get_role(core_data)
        kernel_role = self._get_role(kernel_data)
        core_ord = _ROLE_ORDER.get(core_role or "unknown", 99)
        kernel_ord = _ROLE_ORDER.get(kernel_role or "unknown", 99)
        if core_ord < kernel_ord:
            self._info(
                check,
                "subject_decision_authority is correctly above cognition_planning_layer.",
            )
        else:
            self._error(
                check,
                "subject_decision_authority must be above cognition_planning_layer in the chain.",
                {"core_role": core_role, "kernel_role": kernel_role},
            )

    def check_substrate_distinct_from_orchestration(self) -> None:
        """Execution substrate and orchestration layer must hold distinct roles."""
        check = "SUBSTRATE_DISTINCT_FROM_ORCHESTRATION"
        self._checks_run.append(check)
        substrate_data = self._snapshot.get("execution_substrate")
        orchestration_data = self._snapshot.get("orchestration_layer")
        if substrate_data is None and orchestration_data is None:
            self._info(check, "Neither execution_substrate nor orchestration_layer in snapshot.")
            return
        substrate_role = self._get_role(substrate_data) if substrate_data else None
        orchestration_role = self._get_role(orchestration_data) if orchestration_data else None
        if substrate_role is not None and orchestration_role is not None:
            if substrate_role == orchestration_role:
                self._error(
                    check,
                    f"execution_substrate and orchestration_layer both report role "
                    f"'{substrate_role}'; they must be distinct.",
                    {"substrate_role": substrate_role, "orchestration_role": orchestration_role},
                )
            else:
                self._info(
                    check,
                    "Execution substrate and orchestration layer hold distinct roles — OK.",
                    {"substrate_role": substrate_role, "orchestration_role": orchestration_role},
                )
        elif substrate_data:
            if substrate_role == "execution_substrate":
                self._info(
                    check,
                    "execution_substrate correctly holds execution_substrate role.",
                )
            elif substrate_role is not None:
                self._warn(
                    check,
                    f"execution_substrate role is '{substrate_role}'; expected 'execution_substrate'.",
                    {"found_role": substrate_role},
                )

    def check_remote_execution_coherence(self) -> None:
        """Remote execution mode and authority metadata must be coherent."""
        check = "REMOTE_EXECUTION_COHERENCE"
        self._checks_run.append(check)
        substrate_data = self._snapshot.get("execution_substrate") or {}
        remote_mode = substrate_data.get("remote_execution_mode")
        substrate_role = self._get_role(substrate_data)
        if remote_mode is None:
            self._info(
                check,
                "No remote_execution_mode in execution_substrate snapshot — check skipped.",
            )
            return
        valid_modes = {"agent_runtime", "command_only"}
        if remote_mode not in valid_modes:
            self._error(
                check,
                f"remote_execution_mode '{remote_mode}' is not a valid value; "
                f"expected one of {sorted(valid_modes)}.",
                {"found_mode": remote_mode, "valid_modes": sorted(valid_modes)},
            )
            return
        if substrate_role and substrate_role != "execution_substrate":
            self._warn(
                check,
                f"execution_substrate has remote_execution_mode='{remote_mode}' but "
                f"its authority role is '{substrate_role}' rather than 'execution_substrate'.",
                {"remote_mode": remote_mode, "substrate_role": substrate_role},
            )
        else:
            self._info(
                check,
                f"remote_execution_mode='{remote_mode}' is coherent with substrate role.",
                {"remote_mode": remote_mode},
            )

    def check_authority_chain_complete(self) -> None:
        """Validate that the essential layers of the authority chain are present."""
        check = "AUTHORITY_CHAIN_COMPLETE"
        self._checks_run.append(check)
        required_keys = ["runtime_shell", "subject_core"]
        missing = [k for k in required_keys if k not in self._snapshot]
        if missing:
            self._warn(
                check,
                f"Authority chain snapshot is missing essential layers: {missing}.",
                {"missing_layers": missing},
            )
        else:
            self._info(check, "Essential authority chain layers present in snapshot.")
        # Also validate ordering for whatever is present
        ordered_keys = [
            "runtime_shell",
            "subject_core",
            "cognition_layer",
            "execution_substrate",
        ]
        seen_order: List[Tuple[str, int]] = []
        for key in ordered_keys:
            layer_data = self._snapshot.get(key)
            if layer_data is None:
                continue
            role = self._get_role(layer_data)
            ord_val = _ROLE_ORDER.get(role or "unknown", 99)
            seen_order.append((key, ord_val))
        violations: List[str] = []
        for i in range(len(seen_order) - 1):
            k1, o1 = seen_order[i]
            k2, o2 = seen_order[i + 1]
            if o1 >= o2:
                violations.append(f"{k1}(ord={o1}) should be outer to {k2}(ord={o2})")
        if violations:
            self._error(
                check,
                "Authority chain ordering violation detected.",
                {"violations": violations},
            )
        elif seen_order:
            self._info(check, "Authority chain is correctly ordered outer → inner.")

    # ------------------------------------------------------------------
    # Build report
    # ------------------------------------------------------------------

    def check_projection_metadata_coherent(self) -> None:
        """Projection metadata must be coherent with the outward-truth policy.

        PR-010 consolidation check: the snapshot may carry a
        ``"projection"`` key whose value is a metadata dict describing the
        outward-facing projection surface.  If present, it must not carry a
        legacy role label and should not declare ``is_outward_truth=False``.
        """
        check = "PROJECTION_METADATA_COHERENT"
        self._checks_run.append(check)
        proj = self._snapshot.get("projection")
        if proj is None:
            self._info(check, "No projection key in snapshot — check skipped.")
            return

        if not isinstance(proj, dict):
            self._warn(check, "projection snapshot is not a dict — check skipped.")
            return

        _LEGACY_LABELS = {
            "legacy_ui",
            "legacy_shell",
            "legacy_compatibility",
            "compatibility_fallback",
            "deprecated",
            "LEGACY_UI",
            "LEGACY_SHELL",
            "LEGACY_COMPATIBILITY",
            "DEPRECATED",
        }
        role = proj.get("role") or proj.get("surface_role", "")
        is_outward_truth = proj.get("is_outward_truth", None)

        if is_outward_truth is False:
            self._error(
                check,
                "Projection snapshot explicitly declares is_outward_truth=False, "
                "which violates the projection-only outward-truth policy.",
                {"is_outward_truth": False},
            )
        elif role and role in _LEGACY_LABELS:
            self._error(
                check,
                f"Projection snapshot carries legacy role label '{role}'. "
                "Projection surfaces must not be labeled as legacy.",
                {"role": role},
            )
        else:
            self._info(
                check,
                "Projection metadata is coherent with the outward-truth policy.",
                {"role": role, "is_outward_truth": is_outward_truth},
            )

    def check_canonical_legacy_labels_consistent(self) -> None:
        """No snapshot layer should carry contradictory canonical and legacy labels.

        PR-010 consolidation check: iterates over all top-level layers in the
        snapshot and flags any that carry both a canonical-authority label and
        a legacy-boundary label simultaneously.
        """
        check = "CANONICAL_LEGACY_LABELS_CONSISTENT"
        self._checks_run.append(check)

        _CANONICAL_LABELS = {
            "runtime_shell_authority",
            "subject_decision_authority",
            "cognition_planning_layer",
            "execution_substrate",
            "orchestration_coordinator",
            "projection_driven",
        }
        _LEGACY_LABELS = {
            "legacy_ui",
            "legacy_shell",
            "legacy_compatibility",
            "compatibility_fallback",
            "deprecated",
            "LEGACY_UI",
            "LEGACY_SHELL",
            "LEGACY_COMPATIBILITY",
            "DEPRECATED",
        }

        violations: List[str] = []
        for layer_key, layer_data in self._snapshot.items():
            if not isinstance(layer_data, dict):
                continue
            role = self._get_role(layer_data)
            if role is None:
                continue
            is_canonical = role in _CANONICAL_LABELS
            is_legacy = role in _LEGACY_LABELS
            if is_canonical and is_legacy:
                violations.append(
                    f"layer '{layer_key}' has role '{role}' which is both canonical and legacy"
                )

        if violations:
            self._error(
                check,
                "Some snapshot layers carry contradictory canonical+legacy labels.",
                {"violations": violations},
            )
        else:
            self._info(
                check,
                "All snapshot layers have consistent canonical-vs-legacy labeling.",
            )

    def run_all_checks(self) -> "ArchitectureDiagnostics":
        """Run all built-in invariant checks and return ``self``."""
        self.check_entry_surface_not_authority()
        self.check_runtime_shell_above_subject_core()
        self.check_openclawd_is_subject_decision_core()
        self.check_agent_kernel_is_cognition_layer()
        self.check_subject_core_above_cognition_layer()
        self.check_substrate_distinct_from_orchestration()
        self.check_remote_execution_coherence()
        self.check_authority_chain_complete()
        self.check_projection_metadata_coherent()
        self.check_canonical_legacy_labels_consistent()
        return self

    def build_report(self) -> DiagnosticsReport:
        """Assemble and return the :class:`DiagnosticsReport`."""
        errors = sum(
            1 for f in self._findings if f.severity == DiagnosticSeverity.ERROR.value
        )
        warnings = sum(
            1 for f in self._findings if f.severity == DiagnosticSeverity.WARNING.value
        )
        infos = sum(
            1 for f in self._findings if f.severity == DiagnosticSeverity.INFO.value
        )
        report = DiagnosticsReport(
            overall_valid=(errors == 0),
            findings=list(self._findings),
            error_count=errors,
            warning_count=warnings,
            info_count=infos,
            checks_run=list(self._checks_run),
        )
        if errors > 0:
            logger.warning(
                "Architecture diagnostics: %d error(s) found — overall_valid=False",
                errors,
            )
        else:
            logger.debug(
                "Architecture diagnostics: all checks passed — overall_valid=True",
            )
        return report


# ---------------------------------------------------------------------------
# Standalone validation helpers
# ---------------------------------------------------------------------------


def validate_authority_chain(
    snapshot: Dict[str, Any],
) -> DiagnosticsReport:
    """Validate that the authority chain is present and correctly ordered.

    This is a convenience wrapper that runs only the ordering-related checks.

    Parameters
    ----------
    snapshot:
        A dict with optional keys ``"runtime_shell"``, ``"subject_core"``,
        ``"cognition_layer"``, ``"execution_substrate"``.  Each value should
        be a response/metadata dict from the corresponding layer.

    Returns
    -------
    DiagnosticsReport
        Report with ``overall_valid=True`` when the chain is correctly ordered.
    """
    diag = ArchitectureDiagnostics(snapshot)
    diag.check_runtime_shell_above_subject_core()
    diag.check_subject_core_above_cognition_layer()
    diag.check_authority_chain_complete()
    return diag.build_report()


def validate_layer_boundaries(
    snapshot: Dict[str, Any],
) -> DiagnosticsReport:
    """Validate that each layer claims only the authority appropriate to it.

    Parameters
    ----------
    snapshot:
        A dict with optional keys ``"entry_surface"``, ``"runtime_shell"``,
        ``"subject_core"``, ``"cognition_layer"``, ``"execution_substrate"``,
        ``"orchestration_layer"``.

    Returns
    -------
    DiagnosticsReport
        Report with ``overall_valid=True`` when no layer-boundary violations
        are found.
    """
    diag = ArchitectureDiagnostics(snapshot)
    diag.check_entry_surface_not_authority()
    diag.check_openclawd_is_subject_decision_core()
    diag.check_agent_kernel_is_cognition_layer()
    diag.check_substrate_distinct_from_orchestration()
    return diag.build_report()


def validate_remote_execution_coherence(
    snapshot: Dict[str, Any],
) -> DiagnosticsReport:
    """Validate that remote-execution mode metadata is coherent.

    Parameters
    ----------
    snapshot:
        A dict with an optional ``"execution_substrate"`` key whose value
        is a response dict from :meth:`CommandRouter.route_envelope`.

    Returns
    -------
    DiagnosticsReport
        Report with ``overall_valid=True`` when remote execution metadata is
        coherent.
    """
    diag = ArchitectureDiagnostics(snapshot)
    diag.check_remote_execution_coherence()
    return diag.build_report()


def run_architecture_diagnostics(
    snapshot: Optional[Dict[str, Any]] = None,
) -> DiagnosticsReport:
    """Run all architecture invariant checks and return a structured report.

    This is the main entry point for obtaining a comprehensive diagnostics
    report.  It is safe to call from tests, CI, or logging hooks — it never
    raises and never modifies state.

    Parameters
    ----------
    snapshot:
        Optional dict capturing architectural metadata from the current
        runtime stack.  Expected keys (all optional):

        * ``"entry_surface"`` — metadata dict from the entry adapter
          (e.g. chat route).  Should NOT claim a runtime authority role.
        * ``"runtime_shell"`` — response/metadata dict from
          :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`.
          Typically carries an ``"authority_metadata"`` sub-dict.
        * ``"subject_core"`` — response dict from
          :class:`~core.openclawd.OpenClawd`.  Carries
          ``metadata["authority_role"]``.
        * ``"cognition_layer"`` — :class:`~core.agent.kernel.KernelResponse`
          ``.to_api_dict()`` output.  Carries ``"authority_role"``.
        * ``"execution_substrate"`` — result dict from
          :class:`~core.command_router.CommandRouter`.  Carries
          ``"execution_substrate_role"`` and optionally
          ``"remote_execution_mode"``.
        * ``"orchestration_layer"`` — metadata dict from
          :class:`~core.swarm_coordinator.SwarmCoordinator` or similar.

    Returns
    -------
    DiagnosticsReport
        Structured report.  ``report.overall_valid`` is ``True`` when no
        ERROR-severity findings were produced.
    """
    diag = ArchitectureDiagnostics(snapshot or {})
    diag.run_all_checks()
    return diag.build_report()


def build_diagnostics_snapshot_from_layers(
    *layer_results: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a diagnostics snapshot dict from one or more layer response dicts.

    Each *layer_result* dict is expected to carry an ``"arch_layer_id"`` key
    (set by PR-10 hooks in the runtime modules) identifying which layer it
    represents.  Dicts without ``"arch_layer_id"`` are silently ignored.

    This helper makes it easy to collect responses from multiple components
    and pass them directly to :func:`run_architecture_diagnostics`.

    Parameters
    ----------
    *layer_results:
        Response/result dicts from :meth:`DesktopPresenceRuntime.handle_request`,
        :meth:`OpenClawd.process`, :meth:`KernelResponse.to_api_dict`,
        :meth:`CommandRouter.route_envelope`, etc.

    Returns
    -------
    Dict[str, Any]
        Snapshot dict suitable for :func:`run_architecture_diagnostics`.

    Example
    -------
    ::

        snapshot = build_diagnostics_snapshot_from_layers(
            runtime_result,   # has arch_layer_id="runtime_shell"
            openclawd_result, # has arch_layer_id="subject_core"
            kernel_dict,      # has arch_layer_id="cognition_layer"
            router_result,    # has arch_layer_id="execution_substrate"
        )
        report = run_architecture_diagnostics(snapshot)
    """
    snap: Dict[str, Any] = {}
    for layer_result in layer_results:
        if not isinstance(layer_result, dict):
            continue
        layer_id = layer_result.get("arch_layer_id")
        if layer_id and isinstance(layer_id, str):
            snap[layer_id] = layer_result
    return snap
