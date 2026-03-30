#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools.architecture.architecture_status_report — Architecture Status Reporting
================================================================

PR-14 — Runtime Introspection and Architecture/Execution Status Reporting

Provides a structured, developer-oriented summary of the **architecture
invariants and authority chain** for a given request snapshot.

This module works directly with :mod:`tools.architecture.architecture_diagnostics`
(PR-10) and the authority-contract schemas from PR-9 to produce a single
:class:`ArchitectureStatusReport` that answers:

* Is the authority chain present and ordered correctly?
* Does each layer carry the expected role metadata?
* Are remote-execution mode and authority metadata mutually coherent?
* Is the execution substrate distinct from the orchestration layer?

Design goals
------------
* **Additive and non-breaking** — never alters execution logic.
* **Developer/test-oriented** — structured, serialisable, easy to assert on.
* **Builds on existing diagnostics** — wraps :func:`~tools.architecture.architecture_diagnostics.run_architecture_diagnostics`
  with a friendlier, opinionated summary layer.

Main API
--------
:class:`ArchitectureStatusReport`
    The primary data container.

:func:`build_architecture_status_report`
    Build from a set of layer result dicts or a
    :class:`~core.runtime_introspection.RuntimeIntrospectionSnapshot`.

:func:`architecture_status_from_snapshot`
    Convenience wrapper: build directly from a
    :class:`~core.runtime_introspection.RuntimeIntrospectionSnapshot`.

Usage::

    from tools.architecture.architecture_status_report import build_architecture_status_report

    report = build_architecture_status_report(
        runtime_shell_result=runtime_result,
        subject_core_result=openclawd_result,
        substrate_result=router_result,
    )
    assert report.authority_chain_valid is not False
    print(report.authority_chain_summary)
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ArchitectureStatusReport")

__all__ = [
    "ArchitectureStatusReport",
    "build_architecture_status_report",
    "architecture_status_from_snapshot",
]

# ---------------------------------------------------------------------------
# ArchitectureStatusReport
# ---------------------------------------------------------------------------

_EXPECTED_CHAIN = [
    ("runtime_shell", "runtime_shell_authority"),
    ("subject_core", "subject_decision_authority"),
    ("cognition_layer", "cognition_planning_layer"),
    ("execution_substrate", "execution_substrate"),
]


@dataclasses.dataclass
class ArchitectureStatusReport:
    """Structured summary of architecture invariants and authority chain.

    Attributes
    ----------
    authority_chain_present:
        ``True`` when all expected authority-chain layers were found in the
        snapshot; ``False`` when at least one was missing; ``None`` when the
        check could not be run.
    authority_chain_valid:
        ``True`` when no ERROR-severity diagnostics were produced; ``False``
        when errors were found; ``None`` when diagnostics were unavailable.
    authority_chain_summary:
        List of ``{"layer": ..., "role": ..., "present": bool}`` dicts
        describing each expected authority layer.
    remote_execution_coherent:
        ``True`` when the remote-execution mode and authority metadata are
        mutually coherent; ``None`` when the check was not applicable.
    substrate_distinct_from_orchestration:
        ``True`` when the execution substrate and orchestration layer carry
        distinct roles; ``None`` when the check was not applicable.
    diagnostics_findings:
        List of finding dicts from
        :class:`~tools.architecture.architecture_diagnostics.DiagnosticsReport`.
    overall_valid:
        Aggregate validity flag: ``True`` only when all applicable checks
        passed with no errors.
    notes:
        Human-readable list of notes / explanations for any issues found.
    raw_diagnostics_report:
        The full serialised :class:`~tools.architecture.architecture_diagnostics.DiagnosticsReport`
        dict, when available.
    """

    authority_chain_present: Optional[bool] = None
    authority_chain_valid: Optional[bool] = None
    authority_chain_summary: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    remote_execution_coherent: Optional[bool] = None
    substrate_distinct_from_orchestration: Optional[bool] = None
    diagnostics_findings: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    overall_valid: Optional[bool] = None
    notes: List[str] = dataclasses.field(default_factory=list)
    raw_diagnostics_report: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation.

        Returns
        -------
        Dict[str, Any]
        """
        return {
            "authority_chain_present": self.authority_chain_present,
            "authority_chain_valid": self.authority_chain_valid,
            "authority_chain_summary": self.authority_chain_summary,
            "remote_execution_coherent": self.remote_execution_coherent,
            "substrate_distinct_from_orchestration": self.substrate_distinct_from_orchestration,
            "diagnostics_findings": self.diagnostics_findings,
            "overall_valid": self.overall_valid,
            "notes": self.notes,
            "raw_diagnostics_report": self.raw_diagnostics_report,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"ArchitectureStatusReport("
            f"overall_valid={self.overall_valid!r}, "
            f"authority_chain_valid={self.authority_chain_valid!r}, "
            f"findings={len(self.diagnostics_findings)})"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _check_authority_chain(
    observed: Dict[str, Optional[str]],
) -> tuple[bool, List[Dict[str, Any]], List[str]]:
    """Check which authority-chain layers are present in *observed*.

    Parameters
    ----------
    observed:
        Mapping of layer label → role string (or None if not found).

    Returns
    -------
    Tuple of (all_present, summary_list, notes)
    """
    summary = []
    notes = []
    all_present = True
    for layer_id, expected_role in _EXPECTED_CHAIN:
        actual_role = observed.get(layer_id)
        present = actual_role is not None
        if not present:
            all_present = False
            notes.append(
                f"Layer '{layer_id}' is missing (expected role: '{expected_role}')."
            )
        summary.append({
            "layer": layer_id,
            "expected_role": expected_role,
            "observed_role": actual_role,
            "present": present,
        })
    return all_present, summary, notes


def _gather_observed_roles(
    runtime_shell_result: Optional[Dict[str, Any]],
    subject_core_result: Optional[Dict[str, Any]],
    substrate_result: Optional[Dict[str, Any]],
    orchestration_meta: Optional[Dict[str, Any]],
) -> Dict[str, Optional[str]]:
    """Gather observed authority roles from layer dicts."""
    def _safe(d: Any, *keys: str) -> Optional[str]:
        if not isinstance(d, dict):
            return None
        for k in keys:
            if not isinstance(d, dict):
                return None
            d = d.get(k)
        return d if isinstance(d, str) else None

    shell_role = _safe(runtime_shell_result, "authority_metadata", "layer_role")
    subject_role = _safe(subject_core_result, "metadata", "authority_role")
    # Cognition role may be on subject core metadata
    cognition_role = _safe(subject_core_result, "metadata", "kernel_cognition_role")
    substrate_role = _safe(substrate_result, "execution_substrate_role")
    return {
        "runtime_shell": shell_role,
        "subject_core": subject_role,
        "cognition_layer": cognition_role,
        "execution_substrate": substrate_role,
    }


def _run_diagnostics(
    runtime_shell_result: Optional[Dict[str, Any]],
    subject_core_result: Optional[Dict[str, Any]],
    substrate_result: Optional[Dict[str, Any]],
    orchestration_meta: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Run architecture diagnostics if possible."""
    try:
        from tools.architecture.architecture_diagnostics import (
            build_diagnostics_snapshot_from_layers,
            run_architecture_diagnostics,
        )
        layers = [r for r in [
            runtime_shell_result, subject_core_result,
            substrate_result, orchestration_meta,
        ] if r is not None]
        snap = build_diagnostics_snapshot_from_layers(*layers)
        if not snap:
            return None
        report = run_architecture_diagnostics(snap)
        return report.to_dict()
    except Exception as exc:
        logger.debug("ArchitectureStatusReport: diagnostics skipped: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------


def build_architecture_status_report(
    *,
    runtime_shell_result: Optional[Dict[str, Any]] = None,
    subject_core_result: Optional[Dict[str, Any]] = None,
    substrate_result: Optional[Dict[str, Any]] = None,
    orchestration_meta: Optional[Dict[str, Any]] = None,
) -> ArchitectureStatusReport:
    """Build an :class:`ArchitectureStatusReport` from layer result dicts.

    Each argument is optional.  Pass whatever layer results are available;
    missing layers are noted in the report rather than raising errors.

    Parameters
    ----------
    runtime_shell_result:
        Result dict from :meth:`~core.desktop_presence_runtime.DesktopPresenceRuntime.handle_request`.
    subject_core_result:
        Result dict from :meth:`~core.openclawd.OpenClawd.process`.
    substrate_result:
        Result dict from :meth:`~core.command_router.CommandRouter.route_envelope`.
    orchestration_meta:
        Optional metadata dict from an orchestration layer.

    Returns
    -------
    ArchitectureStatusReport
    """
    report = ArchitectureStatusReport()

    # ── Authority chain check ─────────────────────────────────────────────────
    observed = _gather_observed_roles(
        runtime_shell_result, subject_core_result, substrate_result, orchestration_meta
    )
    chain_present, chain_summary, chain_notes = _check_authority_chain(observed)
    report.authority_chain_present = chain_present
    report.authority_chain_summary = chain_summary
    report.notes.extend(chain_notes)

    # ── Architecture diagnostics ──────────────────────────────────────────────
    diag_dict = _run_diagnostics(
        runtime_shell_result, subject_core_result, substrate_result, orchestration_meta
    )
    if diag_dict:
        report.raw_diagnostics_report = diag_dict
        report.authority_chain_valid = diag_dict.get("overall_valid")
        findings = diag_dict.get("findings", [])
        report.diagnostics_findings = list(findings) if findings else []
        # Extract specific coherence flags from findings
        has_coherence_finding = any(
            "COHERENCE" in str(f.get("code", "")).upper()
            or "remote_execution" in str(f.get("code", "")).lower()
            for f in report.diagnostics_findings
        )
        has_substrate_finding = any(
            "SUBSTRATE" in str(f.get("code", "")).upper()
            or "ORCHESTRATION" in str(f.get("code", "")).upper()
            for f in report.diagnostics_findings
        )
        if not has_coherence_finding:
            report.remote_execution_coherent = True
        if not has_substrate_finding:
            report.substrate_distinct_from_orchestration = True
    else:
        # No diagnostics available — base validity on chain presence only
        report.authority_chain_valid = None

    # ── Aggregate validity ────────────────────────────────────────────────────
    if report.authority_chain_valid is not None:
        report.overall_valid = report.authority_chain_valid
    elif report.authority_chain_present is not None:
        # Diagnostics unavailable; use chain presence as a proxy
        report.overall_valid = report.authority_chain_present
    else:
        report.overall_valid = None

    return report


def architecture_status_from_snapshot(
    snapshot: Any,
) -> ArchitectureStatusReport:
    """Build an :class:`ArchitectureStatusReport` from a
    :class:`~core.runtime_introspection.RuntimeIntrospectionSnapshot`.

    Parameters
    ----------
    snapshot:
        A :class:`~core.runtime_introspection.RuntimeIntrospectionSnapshot`
        instance.

    Returns
    -------
    ArchitectureStatusReport
    """
    # Extract per-layer sub-dicts from raw_metadata if available
    raw = getattr(snapshot, "raw_metadata", {}) or {}

    # Reconstruct minimal layer dicts from the snapshot fields
    shell_result: Optional[Dict[str, Any]] = None
    if snapshot.runtime_shell_authority:
        shell_result = {
            "arch_layer_id": "runtime_shell",
            "authority_metadata": {"layer_role": snapshot.runtime_shell_authority},
        }

    core_result: Optional[Dict[str, Any]] = None
    if snapshot.subject_decision_authority:
        core_result = {
            "arch_layer_id": "subject_core",
            "metadata": {
                "authority_role": snapshot.subject_decision_authority,
                "kernel_cognition_role": snapshot.cognition_layer_role,
            },
        }

    sub_result: Optional[Dict[str, Any]] = None
    if snapshot.execution_substrate_role:
        sub_result = {
            "arch_layer_id": "execution_substrate",
            "execution_substrate_role": snapshot.execution_substrate_role,
        }

    orch_meta: Optional[Dict[str, Any]] = None
    if snapshot.orchestration_role:
        orch_meta = {
            "arch_layer_id": "orchestration_layer",
            "orchestration_role": snapshot.orchestration_role,
        }

    return build_architecture_status_report(
        runtime_shell_result=shell_result,
        subject_core_result=core_result,
        substrate_result=sub_result,
        orchestration_meta=orch_meta,
    )


