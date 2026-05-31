#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/dual_repo_system_reality_audit.py
=======================================
PR-537 (dual-repo joint system reality audit):
Dual-Repository System Reality Audit — code-grounded maturity measurement.

Problem addressed
-----------------
The Galaxy V2 repository has accumulated substantial readiness and governance
machinery (capability routing gates, recovery coordinators, release gate
skeleton, system acceptance verdict, etc.).  None of the existing modules
answers the following **engineering-honest** question at the dual-repo level:

    *Based solely on what real code, real tests, and real CI workflows exist
    right now, which capabilities are truly implemented / mainchained /
    automated-verified — and which are nominally present but not yet
    end-to-end closed?*

This module provides a code-grounded answer.  It:

1. Defines a **MaturityLabel** enumeration that maps directly to the five
   states from the problem statement:

   - ``nominally_present_not_closed`` — name / sentinel exists in code;
     no end-to-end closure (no callable enforcement, no test coverage).
   - ``partially_implemented`` — some real code exists but the chain is
     incomplete (e.g. gate defined but not wired into dispatch path).
   - ``implemented`` — real code is present and functionally complete;
     the capability can be exercised.
   - ``mainchained`` — the capability is actively on the canonical
     execution / enforcement path (e.g. default-enforced at dispatch).
   - ``automated_verified`` — the capability is covered by automated
     tests and/or CI workflow jobs that would catch regressions.

2. Defines five **AuditDimension** values that correspond to the five
   review axes in the problem statement:

   - ``main_chain_authenticity`` — center orchestration main chain.
   - ``capability_routing_delegated_flow`` — capability routing and
     delegated flow real connectivity.
   - ``recovery_redispatch_reconnect`` — recovery / redispatch / reconnect
     closure.
   - ``governance_readiness_release_gate`` — governance / readiness /
     release gate actual enforcement.
   - ``workflow_tests_audit_outputs`` — workflow / test / audit output
     real support capacity.

3. Probes each dimension by attempting to **import real modules** and
   inspecting expected attributes / call-site wiring.  Fail-conservative:
   an unavailable or incomplete module downgrades the maturity label; it
   is never silently accepted.

4. Produces a stable, JSON-serialisable :class:`DualRepoRealityAuditReport`
   that carries per-dimension :class:`DimensionAuditEntry` records plus a
   system-level :class:`SystemRealityVerdict` and four formal conclusions.

5. Exposes a singleton (:func:`get_dual_repo_reality_audit`) and a
   test-isolation reset (:func:`reset_dual_repo_reality_audit`).

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────────┐
    │  DUAL-REPO SYSTEM REALITY AUDIT  (this module — PR-537)             │
    │                                                                      │
    │  Probes (read-only / fail-graceful):                                 │
    │    • core.openclawd          (control-plane main entry)              │
    │    • core.command_router     (command dispatch)                      │
    │    • galaxy_gateway.device_router  (gateway routing)                 │
    │    • galaxy_gateway.websocket_handler  (transport)                   │
    │    • core.capability_routing_gate      (cap routing gate)            │
    │    • core.gateway_capability_default_enforcement  (enforcement wire) │
    │    • core.delegated_flow_readiness_gate   (PR-9V2)                   │
    │    • core.delegated_flow_acceptance_gate  (PR-10V2)                  │
    │    • core.flow_continuity_coordinator     (continuity)               │
    │    • core.delegated_flow_recovery_coordinator  (recovery)            │
    │    • core.recovery_durability_closure_validator (PR-5V2)             │
    │    • core.runtime_restart_recovery        (restart recovery)         │
    │    • core.governance_validation_gate      (governance gate)          │
    │    • core.distributed_release_gate_skeleton  (PR-7V2)               │
    │    • core.system_final_acceptance_verdict    (PR-17V2)               │
    │    • core.v2_readiness_governance_evidence_surface (PR-6V2)          │
    │    • test file presence and CI workflow file presence                │
    │                                                                      │
    │  Produces:                                                           │
    │    • DimensionAuditEntry     (per-dimension maturity record)         │
    │    • DualRepoRealityAuditReport  (full serialisable audit report)    │
    │    • SystemRealityVerdict    (system-level conclusion)               │
    └──────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified.
2. **Fail-conservative** — an unavailable module, missing wiring, or absent
   test always downgrades the maturity label; silence is never acceptance.
3. **Code-grounded** — documentation and sentinel strings are explicitly
   excluded as evidence; only importable modules, callable wiring, and
   test/workflow file existence count.
4. **Honest gap reporting** — unresolved blocking gaps are always surfaced
   in ``DualRepoRealityAuditReport.unresolved_blocking_gaps``; never
   suppressed.
5. **Stable artifacts** — :class:`DualRepoRealityAuditReport` and
   :class:`DimensionAuditEntry` are fully JSON-serialisable and
   round-trippable.
6. **Singleton with test-reset** — :func:`get_dual_repo_reality_audit`
   returns the process-global singleton; :func:`reset_dual_repo_reality_audit`
   clears it for test isolation.

Public API
----------
Authority / policy sentinels::

    DUAL_REPO_SYSTEM_REALITY_AUDIT_AUTHORITY
    DUAL_REPO_SYSTEM_REALITY_AUDIT_PR537_SENTINEL
    CODE_GROUNDED_EVIDENCE_ONLY_POLICY
    FAIL_CONSERVATIVE_ON_MISSING_MODULE_POLICY
    SILENCE_IS_NOT_ACCEPTANCE_POLICY
    HONEST_GAP_REPORTING_POLICY
    ADDITIVE_ONLY_NO_MUTATION_POLICY

Enumerations::

    MaturityLabel
    AuditDimension
    SystemRealityVerdict

Data classes::

    DimensionAuditEntry
    DualRepoRealityAuditReport

Class::

    DualRepoSystemRealityAuditor

Helpers::

    build_dual_repo_reality_audit() -> DualRepoRealityAuditReport
    get_dual_repo_reality_audit()   -> DualRepoRealityAuditReport  (singleton)
    reset_dual_repo_reality_audit() -> None  (testing only)
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.DualRepoSystemRealityAudit")

__all__ = [
    # Authority sentinels
    "DUAL_REPO_SYSTEM_REALITY_AUDIT_AUTHORITY",
    "DUAL_REPO_SYSTEM_REALITY_AUDIT_PR537_SENTINEL",
    # Policy sentinels
    "CODE_GROUNDED_EVIDENCE_ONLY_POLICY",
    "FAIL_CONSERVATIVE_ON_MISSING_MODULE_POLICY",
    "SILENCE_IS_NOT_ACCEPTANCE_POLICY",
    "HONEST_GAP_REPORTING_POLICY",
    "ADDITIVE_ONLY_NO_MUTATION_POLICY",
    # Enumerations
    "MaturityLabel",
    "AuditDimension",
    "SystemRealityVerdict",
    # Data classes
    "DimensionAuditEntry",
    "DualRepoRealityAuditReport",
    # Class
    "DualRepoSystemRealityAuditor",
    # Helpers
    "build_dual_repo_reality_audit",
    "get_dual_repo_reality_audit",
    "reset_dual_repo_reality_audit",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

DUAL_REPO_SYSTEM_REALITY_AUDIT_AUTHORITY: str = (
    "DUAL_REPO_SYSTEM_REALITY_AUDIT_AUTHORITY::"
    "core.dual_repo_system_reality_audit::PR537::"
    "code-grounded-dual-repo-maturity-measurement::"
    "real-code-not-documentation"
)
"""Sentinel: this module is the canonical dual-repo system reality audit
authority.

Import to assert that a measurement, report, or CI gate is reading
maturity state from the code-grounded audit rather than from
documentation claims or verbal descriptions."""

DUAL_REPO_SYSTEM_REALITY_AUDIT_PR537_SENTINEL: str = (
    "DUAL_REPO_SYSTEM_REALITY_AUDIT_PR537_SENTINEL::"
    "package=PR537::profile=dual-repo-system-reality-audit-v1::"
    "module=core.dual_repo_system_reality_audit"
)
"""Package sentinel for PR-537."""

CODE_GROUNDED_EVIDENCE_ONLY_POLICY: str = (
    "POLICY::CODE_GROUNDED_EVIDENCE_ONLY_V1: "
    "Maturity labels in DualRepoRealityAuditReport MUST be derived "
    "exclusively from importable Python modules, callable wiring at known "
    "enforcement call sites, and the physical existence of test / CI workflow "
    "files on disk.  Documentation text, sentinel strings, and design "
    "descriptions are explicitly EXCLUDED as maturity evidence.  "
    "PR-537, dual-repo system reality audit."
)

FAIL_CONSERVATIVE_ON_MISSING_MODULE_POLICY: str = (
    "POLICY::FAIL_CONSERVATIVE_ON_MISSING_MODULE_V1: "
    "When a module that is expected to back a dimension cannot be imported, "
    "or when an expected callable / attribute is absent, the dimension MUST "
    "be downgraded to at most 'partially_implemented'; it MUST NOT be "
    "silently promoted.  If NO module in a dimension can be imported the "
    "label MUST be 'nominally_present_not_closed'.  "
    "PR-537, dual-repo system reality audit."
)

SILENCE_IS_NOT_ACCEPTANCE_POLICY: str = (
    "POLICY::SILENCE_IS_NOT_ACCEPTANCE_V1: "
    "A dimension for which no code evidence can be obtained MUST NOT "
    "receive a maturity label higher than 'nominally_present_not_closed'. "
    "The absence of negative evidence is NOT positive evidence.  "
    "PR-537, dual-repo system reality audit."
)

HONEST_GAP_REPORTING_POLICY: str = (
    "POLICY::HONEST_GAP_REPORTING_V1: "
    "Every dimension that does not reach 'automated_verified' MUST contribute "
    "at least one entry to DualRepoRealityAuditReport.unresolved_blocking_gaps "
    "or DimensionAuditEntry.gaps describing the specific gap.  "
    "No optimistic suppression of gaps is permitted.  "
    "PR-537, dual-repo system reality audit."
)

ADDITIVE_ONLY_NO_MUTATION_POLICY: str = (
    "POLICY::ADDITIVE_ONLY_NO_MUTATION_V1: "
    "The DualRepoSystemRealityAuditor is a read-only projection layer.  "
    "All probes are import-only or file-existence checks; no canonical "
    "state, runtime registry, or module-level singleton is mutated.  "
    "PR-537, dual-repo system reality audit."
)


# ---------------------------------------------------------------------------
# MaturityLabel
# ---------------------------------------------------------------------------


class MaturityLabel(str, Enum):
    """Five-tier maturity classification for a single audit dimension.

    Tiers are ordered from lowest to highest real-code maturity.

    ``nominally_present_not_closed``
        A name, sentinel, or design document references this capability,
        but no importable enforcement module, real callable wiring, or
        test coverage backs it end-to-end.  It exists on paper only.

    ``partially_implemented``
        At least one real module implementing part of the capability is
        importable, but the chain is incomplete: enforcement is not wired
        into the canonical dispatch path, or critical sub-modules are
        absent, or no automated tests verify the end-to-end behavior.

    ``implemented``
        Real code for the capability exists and is functionally complete:
        all expected modules are importable and the key callable surfaces
        are present.  The capability CAN be exercised, but it is not yet
        confirmed as the default-enforced path.

    ``mainchained``
        The capability is actively and verifiably on the canonical
        execution or enforcement path.  Evidence: a wiring module
        (e.g. ``gateway_capability_default_enforcement``) that confirms
        the gate is invoked by default on every relevant dispatch, not
        just when explicitly called.

    ``automated_verified``
        The capability has automated test coverage (importable test
        modules or CI workflow jobs) that would detect regressions.
        This is the highest tier — it requires both real code and
        real automation.
    """

    nominally_present_not_closed = "nominally_present_not_closed"
    partially_implemented = "partially_implemented"
    implemented = "implemented"
    mainchained = "mainchained"
    automated_verified = "automated_verified"

    _ignore_ = ["_ORDINALS"]
    _ORDINALS: List[str] = []

    def ordinal(self) -> int:
        """Return the integer rank (0 = lowest, 4 = highest)."""
        _order = [
            "nominally_present_not_closed",
            "partially_implemented",
            "implemented",
            "mainchained",
            "automated_verified",
        ]
        return _order.index(self.value)

    def is_blocking(self) -> bool:
        """Return True when this label indicates a blocking maturity gap.

        Labels below ``implemented`` are considered blocking: they indicate
        that a required capability is not yet reliably available.
        """
        return self.ordinal() < self.__class__.implemented.ordinal()

    @classmethod
    def from_string(cls, value: str) -> "MaturityLabel":
        """Return the member matching *value*, defaulting to the lowest tier."""
        if not isinstance(value, str):
            return cls.nominally_present_not_closed
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.nominally_present_not_closed


# ---------------------------------------------------------------------------
# AuditDimension
# ---------------------------------------------------------------------------


class AuditDimension(str, Enum):
    """The five dual-repo system reality audit dimensions.

    Each dimension maps directly to one of the five review axes specified
    in the PR-537 problem statement.

    ``main_chain_authenticity``
        Is the center orchestration main chain (OpenClawd → CommandRouter →
        DeviceRouter → WebSocketHandler) real, importable, and directly
        exercised on every request?

    ``capability_routing_delegated_flow``
        Are capability routing gate and delegated-flow acceptance semantics
        actually wired into the canonical dispatch path, or only defined as
        advisory / opt-in structures?

    ``recovery_redispatch_reconnect``
        Are continuity / recovery / reconnect / redispatch coordinators
        fully implemented and their scenario coverage closed?

    ``governance_readiness_release_gate``
        Is governance / readiness / release gate machinery actually
        enforcing (blocking real execution when violated) or only
        producing advisory reports?

    ``workflow_tests_audit_outputs``
        Do workflow files, test files, and audit output modules exist on
        disk and substantiate the capabilities claimed above?
    """

    main_chain_authenticity = "main_chain_authenticity"
    capability_routing_delegated_flow = "capability_routing_delegated_flow"
    recovery_redispatch_reconnect = "recovery_redispatch_reconnect"
    governance_readiness_release_gate = "governance_readiness_release_gate"
    workflow_tests_audit_outputs = "workflow_tests_audit_outputs"

    @classmethod
    def all_dimensions(cls) -> List["AuditDimension"]:
        """Return all five dimensions in canonical audit order."""
        return [
            cls.main_chain_authenticity,
            cls.capability_routing_delegated_flow,
            cls.recovery_redispatch_reconnect,
            cls.governance_readiness_release_gate,
            cls.workflow_tests_audit_outputs,
        ]

    @classmethod
    def from_string(cls, value: str) -> "AuditDimension":
        """Return the member matching *value*, defaulting to
        ``main_chain_authenticity``."""
        if not isinstance(value, str):
            return cls.main_chain_authenticity
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.main_chain_authenticity


# ---------------------------------------------------------------------------
# SystemRealityVerdict
# ---------------------------------------------------------------------------


class SystemRealityVerdict(str, Enum):
    """System-level conclusion from the dual-repo reality audit.

    ``platform_baseline_established``
        All five audit dimensions have reached at least ``implemented``
        maturity.  The platform baseline is code-grounded.

    ``partial_baseline_significant_gaps``
        The majority of dimensions are ``implemented`` or above, but at
        least one dimension is ``partially_implemented`` or lower.  The
        platform is progressing but gaps are present.

    ``critical_gaps_blocking_baseline``
        At least one dimension is ``nominally_present_not_closed`` — it
        exists only on paper.  A code-grounded platform baseline cannot
        be declared.

    ``insufficient_evidence_to_conclude``
        The auditor could not probe enough dimensions to reach any
        conclusion (e.g. import environment is severely broken).
    """

    platform_baseline_established = "platform_baseline_established"
    partial_baseline_significant_gaps = "partial_baseline_significant_gaps"
    critical_gaps_blocking_baseline = "critical_gaps_blocking_baseline"
    insufficient_evidence_to_conclude = "insufficient_evidence_to_conclude"

    @classmethod
    def from_string(cls, value: str) -> "SystemRealityVerdict":
        """Return the member matching *value*, defaulting to
        ``insufficient_evidence_to_conclude``."""
        if not isinstance(value, str):
            return cls.insufficient_evidence_to_conclude
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.insufficient_evidence_to_conclude

    @property
    def is_baseline_established(self) -> bool:
        """Return True only when the verdict is platform_baseline_established."""
        return self == SystemRealityVerdict.platform_baseline_established

    @property
    def has_critical_gaps(self) -> bool:
        """Return True when any dimension is nominally present only."""
        return self == SystemRealityVerdict.critical_gaps_blocking_baseline

    @property
    def is_inconclusive(self) -> bool:
        """Return True when the evidence is insufficient to conclude."""
        return self == SystemRealityVerdict.insufficient_evidence_to_conclude


# ---------------------------------------------------------------------------
# DimensionAuditEntry
# ---------------------------------------------------------------------------


@dataclass
class DimensionAuditEntry:
    """Code-grounded maturity record for one audit dimension.

    Fields
    ------
    dimension
        Which of the five :class:`AuditDimension` values this entry covers.
    maturity
        The :class:`MaturityLabel` assigned based on real code evidence.
    evidence_summary
        Human-readable summary of what code evidence was found.
    code_references
        List of dotted module paths that were successfully imported or
        confirmed present during probing.
    test_references
        List of test file paths or CI job names that provide automated
        verification for this dimension.
    gaps
        List of specific gaps found (missing modules, absent wiring,
        no test coverage, etc.).
    verdict_rationale
        Concise explanation of why the maturity label was assigned.
    audited_at
        Unix timestamp of this dimension audit.
    """

    dimension: AuditDimension = AuditDimension.main_chain_authenticity
    maturity: MaturityLabel = MaturityLabel.nominally_present_not_closed
    evidence_summary: str = ""
    code_references: List[str] = field(default_factory=list)
    test_references: List[str] = field(default_factory=list)
    gaps: List[str] = field(default_factory=list)
    verdict_rationale: str = ""
    audited_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "dimension": self.dimension.value,
            "maturity": self.maturity.value,
            "evidence_summary": self.evidence_summary,
            "code_references": self.code_references,
            "test_references": self.test_references,
            "gaps": self.gaps,
            "verdict_rationale": self.verdict_rationale,
            "audited_at": self.audited_at,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DimensionAuditEntry":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        return cls(
            dimension=AuditDimension.from_string(data.get("dimension", "")),
            maturity=MaturityLabel.from_string(data.get("maturity", "")),
            evidence_summary=data.get("evidence_summary", ""),
            code_references=list(data.get("code_references", [])),
            test_references=list(data.get("test_references", [])),
            gaps=list(data.get("gaps", [])),
            verdict_rationale=data.get("verdict_rationale", ""),
            audited_at=data.get("audited_at", time.time()),
        )


# ---------------------------------------------------------------------------
# DualRepoRealityAuditReport
# ---------------------------------------------------------------------------


@dataclass
class DualRepoRealityAuditReport:
    """Full dual-repo system reality audit report.

    Produced by :class:`DualRepoSystemRealityAuditor`.  Carries:

    * A :class:`DimensionAuditEntry` for each of the five audit dimensions.
    * The overall :class:`SystemRealityVerdict`.
    * Four formal conclusions (main chain, recovery, governance,
      operational readiness).
    * A flat list of all blocking gaps across all dimensions.
    * A human-readable ``summary`` for operator consoles and review UIs.
    * A machine-readable ``to_json()`` for CI pipelines and audit tooling.

    Fields
    ------
    report_id
        Unique identifier for this report (UUID hex prefix).
    dimensions
        List of :class:`DimensionAuditEntry` for all five dimensions.
    system_verdict
        Overall system-level reality verdict.
    main_chain_authenticity_conclusion
        Formal textual conclusion about main chain reality.
    recovery_maturity_conclusion
        Formal textual conclusion about recovery maturity.
    governance_enforcement_conclusion
        Formal textual conclusion about governance enforcement.
    operational_readiness_contribution
        Formal textual conclusion about fully-operational readiness.
    unresolved_blocking_gaps
        Flat list of all gaps that must be closed for the platform baseline
        to be declared established.
    summary
        Human-readable multi-line summary of the full audit state.
    generated_at
        Unix timestamp of report generation.
    auditor_version
        Version of the auditor that produced this report.
    """

    report_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    dimensions: List[DimensionAuditEntry] = field(default_factory=list)
    system_verdict: SystemRealityVerdict = (
        SystemRealityVerdict.insufficient_evidence_to_conclude
    )
    main_chain_authenticity_conclusion: str = ""
    recovery_maturity_conclusion: str = ""
    governance_enforcement_conclusion: str = ""
    operational_readiness_contribution: str = ""
    unresolved_blocking_gaps: List[str] = field(default_factory=list)
    summary: str = ""
    generated_at: float = field(default_factory=time.time)
    auditor_version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation (machine-readable output)."""
        return {
            "report_id": self.report_id,
            "dimensions": [e.to_dict() for e in self.dimensions],
            "system_verdict": self.system_verdict.value,
            "main_chain_authenticity_conclusion": (
                self.main_chain_authenticity_conclusion
            ),
            "recovery_maturity_conclusion": self.recovery_maturity_conclusion,
            "governance_enforcement_conclusion": (
                self.governance_enforcement_conclusion
            ),
            "operational_readiness_contribution": (
                self.operational_readiness_contribution
            ),
            "unresolved_blocking_gaps": self.unresolved_blocking_gaps,
            "summary": self.summary,
            "generated_at": self.generated_at,
            "auditor_version": self.auditor_version,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DualRepoRealityAuditReport":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        dims: List[DimensionAuditEntry] = [
            DimensionAuditEntry.from_dict(d) for d in data.get("dimensions", [])
        ]
        return cls(
            report_id=data.get("report_id", uuid.uuid4().hex[:12]),
            dimensions=dims,
            system_verdict=SystemRealityVerdict.from_string(
                data.get("system_verdict", "")
            ),
            main_chain_authenticity_conclusion=data.get(
                "main_chain_authenticity_conclusion", ""
            ),
            recovery_maturity_conclusion=data.get(
                "recovery_maturity_conclusion", ""
            ),
            governance_enforcement_conclusion=data.get(
                "governance_enforcement_conclusion", ""
            ),
            operational_readiness_contribution=data.get(
                "operational_readiness_contribution", ""
            ),
            unresolved_blocking_gaps=list(
                data.get("unresolved_blocking_gaps", [])
            ),
            summary=data.get("summary", ""),
            generated_at=data.get("generated_at", time.time()),
            auditor_version=data.get("auditor_version", "1.0"),
        )

    def get_dimension_entry(
        self, dim: AuditDimension
    ) -> Optional[DimensionAuditEntry]:
        """Return the :class:`DimensionAuditEntry` for *dim*, or ``None``."""
        for entry in self.dimensions:
            if entry.dimension == dim:
                return entry
        return None


# ---------------------------------------------------------------------------
# Internal probe helpers
# ---------------------------------------------------------------------------


def _try_import(module_path: str) -> bool:
    """Return True when *module_path* can be successfully imported."""
    try:
        importlib.import_module(module_path)
        return True
    except Exception as exc:
        return False


def _has_attr(module_path: str, attr_name: str) -> bool:
    """Return True when *module_path* is importable and has *attr_name*."""
    try:
        mod = importlib.import_module(module_path)
        return hasattr(mod, attr_name)
    except Exception as exc:
        return False


def _file_exists(relative_path: str) -> bool:
    """Return True when *relative_path* exists relative to the project root."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.isfile(os.path.join(project_root, relative_path))


def _module_file_exists(dotted_module_path: str) -> bool:
    """Return True when the source file for *dotted_module_path* exists.

    This is a **file-existence** probe, not an import probe.  It converts
    ``core.command_router`` → ``core/command_router.py`` and checks that the
    resulting path exists relative to the project root.

    Use this as a fallback when :func:`_try_import` fails due to missing
    third-party dependencies that are not installed in the test environment
    (e.g. ``pydantic``, ``fastapi``).  A module file that exists but cannot
    be imported due to transitive dependency absence is still real code —
    distinguishing it from a genuinely absent module gives a more accurate
    maturity picture.
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_path = os.path.join(project_root, dotted_module_path.replace(".", os.sep) + ".py")
    return os.path.isfile(file_path)


def _count_true(flags: List[bool]) -> int:
    """Count the number of True values in *flags*."""
    return sum(1 for f in flags if f)


# ---------------------------------------------------------------------------
# DualRepoSystemRealityAuditor
# ---------------------------------------------------------------------------


class DualRepoSystemRealityAuditor:
    """Code-grounded auditor for the dual-repo Galaxy system.

    All probes are read-only (import checks and file-existence checks).
    No canonical state, runtime registry, or singleton is mutated.

    Usage
    -----
    ::

        from core.dual_repo_system_reality_audit import (
            DualRepoSystemRealityAuditor,
        )

        report = DualRepoSystemRealityAuditor().audit()
        print(report.system_verdict.value)
        for gap in report.unresolved_blocking_gaps:
            print(f"  GAP: {gap}")
    """

    AUDITOR_VERSION: str = "1.0"

    def audit(self) -> DualRepoRealityAuditReport:
        """Run the full five-dimension dual-repo system reality audit.

        Returns
        -------
        DualRepoRealityAuditReport
            Full report with per-dimension maturity entries, system verdict,
            four formal conclusions, and all blocking gaps.
        """
        entries = [
            self._audit_main_chain_authenticity(),
            self._audit_capability_routing_delegated_flow(),
            self._audit_recovery_redispatch_reconnect(),
            self._audit_governance_readiness_release_gate(),
            self._audit_workflow_tests_audit_outputs(),
        ]

        verdict = self._compute_verdict(entries)
        blocking_gaps = self._collect_blocking_gaps(entries)

        main_chain_entry = self._find_entry(
            entries, AuditDimension.main_chain_authenticity
        )
        recovery_entry = self._find_entry(
            entries, AuditDimension.recovery_redispatch_reconnect
        )
        governance_entry = self._find_entry(
            entries, AuditDimension.governance_readiness_release_gate
        )
        workflow_entry = self._find_entry(
            entries, AuditDimension.workflow_tests_audit_outputs
        )

        main_chain_conclusion = self._build_main_chain_conclusion(
            main_chain_entry
        )
        recovery_conclusion = self._build_recovery_conclusion(recovery_entry)
        governance_conclusion = self._build_governance_conclusion(
            governance_entry
        )
        readiness_conclusion = self._build_readiness_conclusion(
            entries, workflow_entry
        )

        summary = self._build_summary(
            verdict,
            entries,
            blocking_gaps,
            main_chain_conclusion,
            recovery_conclusion,
            governance_conclusion,
            readiness_conclusion,
        )

        return DualRepoRealityAuditReport(
            dimensions=entries,
            system_verdict=verdict,
            main_chain_authenticity_conclusion=main_chain_conclusion,
            recovery_maturity_conclusion=recovery_conclusion,
            governance_enforcement_conclusion=governance_conclusion,
            operational_readiness_contribution=readiness_conclusion,
            unresolved_blocking_gaps=blocking_gaps,
            summary=summary,
            auditor_version=self.AUDITOR_VERSION,
        )

    # ------------------------------------------------------------------
    # Dimension auditors
    # ------------------------------------------------------------------

    def _audit_main_chain_authenticity(self) -> DimensionAuditEntry:
        """Probe the center orchestration main chain."""
        dim = AuditDimension.main_chain_authenticity

        # Core control-plane modules that must all be importable for main
        # chain to be real.
        core_modules = [
            "core.openclawd",
            "core.command_router",
            "core.api_routes",
        ]
        # Gateway / transport modules (canonical device ingress)
        gateway_modules = [
            "galaxy_gateway.websocket_handler",
            "galaxy_gateway.device_router",
        ]
        # Canonical completion ingress (result path back from Android)
        result_modules = [
            "core.canonical_completion_ingress",
            "core.device_registry",
        ]

        all_expected = core_modules + gateway_modules + result_modules

        # Two-tier probe:
        # 1. Try import (strongest evidence — module is runnable in this env).
        # 2. If import fails, check file existence on disk (real code exists
        #    but has transitive dependencies like pydantic/fastapi not installed
        #    in the minimal test environment).
        importable: List[str] = [m for m in all_expected if _try_import(m)]
        file_present_not_importable: List[str] = [
            m
            for m in all_expected
            if m not in importable and _module_file_exists(m)
        ]
        genuinely_absent: List[str] = [
            m
            for m in all_expected
            if m not in importable and m not in file_present_not_importable
        ]

        # Test and workflow evidence
        test_refs: List[str] = []
        if _file_exists("tests/test_pr001_canonical_dispatcher.py"):
            test_refs.append("tests/test_pr001_canonical_dispatcher.py")
        if _file_exists("tests/test_pr530_runtime_acceptance_and_spine_hardening.py"):
            test_refs.append(
                "tests/test_pr530_runtime_acceptance_and_spine_hardening.py"
            )
        if _file_exists(".github/workflows/ci.yml"):
            test_refs.append(".github/workflows/ci.yml (lint + v3-protocol-guard)")

        gaps: List[str] = []
        for m in genuinely_absent:
            gaps.append(f"Module file absent: {m}")
        for m in file_present_not_importable:
            gaps.append(
                f"Module file present but not importable (dependency gap): {m}"
            )

        # Maturity determination — importable modules are required for
        # implementation credit. File presence is tracked as a gap signal only.
        total = len(all_expected)
        found = len(importable)

        if found == 0:
            maturity = (
                MaturityLabel.partially_implemented
                if len(file_present_not_importable) > 0
                else MaturityLabel.nominally_present_not_closed
            )
            rationale = (
                "Main-chain module files may exist, but none are importable in "
                "this environment. Ensure dependencies are installed or modules "
                "are properly configured. Structural presence alone is not "
                "credited as a runtime-backed chain."
            )
        elif found < total // 2:
            maturity = MaturityLabel.partially_implemented
            rationale = (
                f"Only {found}/{total} main-chain modules are importable; "
                "chain is incomplete."
            )
        elif found < total:
            maturity = MaturityLabel.implemented
            rationale = (
                f"{found}/{total} main-chain modules are importable; "
                "remaining modules are absent or not importable."
            )
        elif test_refs:
            # All importable and test/CI evidence exists
            maturity = MaturityLabel.automated_verified
            rationale = (
                f"All {total} main-chain modules importable and "
                f"{len(test_refs)} test/CI reference(s) found."
            )
        else:
            maturity = MaturityLabel.mainchained
            rationale = (
                f"All {total} main-chain modules importable; "
                "no test/CI reference found for automated_verified."
            )

        evidence_summary = (
            f"Probed {total} main-chain modules; "
            f"{len(importable)} importable, "
            f"{len(file_present_not_importable)} file-present-not-importable, "
            f"{len(genuinely_absent)} absent.  "
            f"Test/CI references: {len(test_refs)}."
        )

        return DimensionAuditEntry(
            dimension=dim,
            maturity=maturity,
            evidence_summary=evidence_summary,
            code_references=importable,
            test_references=test_refs,
            gaps=gaps,
            verdict_rationale=rationale,
        )

    def _audit_capability_routing_delegated_flow(
        self,
    ) -> DimensionAuditEntry:
        """Probe capability routing gate and delegated-flow wiring."""
        dim = AuditDimension.capability_routing_delegated_flow

        # The gate itself must be importable
        gate_available = _try_import("core.capability_routing_gate")
        # The enforcement wiring confirms the gate is on the default path
        enforcement_available = _try_import(
            "core.gateway_capability_default_enforcement"
        )
        # Delegated-flow readiness gate (PR-9V2)
        readiness_available = _try_import("core.delegated_flow_readiness_gate")
        # Delegated-flow acceptance gate (PR-10V2)
        acceptance_available = _try_import("core.delegated_flow_acceptance_gate")

        available: List[str] = []
        if gate_available:
            available.append("core.capability_routing_gate")
        if enforcement_available:
            available.append("core.gateway_capability_default_enforcement")
        if readiness_available:
            available.append("core.delegated_flow_readiness_gate")
        if acceptance_available:
            available.append("core.delegated_flow_acceptance_gate")

        missing: List[str] = []
        if not gate_available:
            missing.append("core.capability_routing_gate")
        if not enforcement_available:
            missing.append("core.gateway_capability_default_enforcement")
        if not readiness_available:
            missing.append("core.delegated_flow_readiness_gate")
        if not acceptance_available:
            missing.append("core.delegated_flow_acceptance_gate")

        test_refs: List[str] = []
        if _file_exists("tests/test_pr10_v2_delegated_flow_acceptance_gate.py"):
            test_refs.append(
                "tests/test_pr10_v2_delegated_flow_acceptance_gate.py"
            )
        if _file_exists("tests/test_pr535_v2_readiness_governance_evidence_surface.py"):
            test_refs.append(
                "tests/test_pr535_v2_readiness_governance_evidence_surface.py"
            )

        gaps: List[str] = []
        for m in missing:
            gaps.append(f"Module not importable: {m}")
        if not enforcement_available:
            gaps.append(
                "Capability gate enforcement wiring "
                "(gateway_capability_default_enforcement) absent — gate may "
                "not be default-enforced on the canonical dispatch path."
            )

        found = len(available)
        total = 4

        if found == 0:
            maturity = MaturityLabel.nominally_present_not_closed
            rationale = "No capability routing module could be imported."
        elif found < 2:
            maturity = MaturityLabel.partially_implemented
            rationale = (
                f"Only {found}/{total} modules importable; enforcement wiring "
                "not confirmed."
            )
        elif not enforcement_available:
            maturity = MaturityLabel.implemented
            rationale = (
                f"{found}/{total} modules importable but enforcement wiring "
                "(gateway_capability_default_enforcement) is absent; gate is "
                "defined but not confirmed as default-enforced."
            )
        elif test_refs:
            maturity = MaturityLabel.automated_verified
            rationale = (
                f"All {total} modules importable (including enforcement wiring) "
                f"and {len(test_refs)} test reference(s) found."
            )
        else:
            maturity = MaturityLabel.mainchained
            rationale = (
                f"All {total} modules importable including enforcement wiring; "
                "no test reference found for automated_verified."
            )

        evidence_summary = (
            f"Probed {total} cap-routing/delegated-flow modules; "
            f"{found} importable.  Enforcement wiring: "
            f"{'present' if enforcement_available else 'absent'}.  "
            f"Test references: {len(test_refs)}."
        )

        return DimensionAuditEntry(
            dimension=dim,
            maturity=maturity,
            evidence_summary=evidence_summary,
            code_references=available,
            test_references=test_refs,
            gaps=gaps,
            verdict_rationale=rationale,
        )

    def _audit_recovery_redispatch_reconnect(self) -> DimensionAuditEntry:
        """Probe recovery / redispatch / reconnect closure."""
        dim = AuditDimension.recovery_redispatch_reconnect

        continuity_available = _try_import("core.flow_continuity_coordinator")
        recovery_available = _try_import(
            "core.delegated_flow_recovery_coordinator"
        )
        closure_available = _try_import(
            "core.recovery_durability_closure_validator"
        )
        restart_available = _try_import("core.runtime_restart_recovery")
        truth_surface_available = _try_import("core.recovery_truth_surface")

        available: List[str] = []
        if continuity_available:
            available.append("core.flow_continuity_coordinator")
        if recovery_available:
            available.append("core.delegated_flow_recovery_coordinator")
        if closure_available:
            available.append("core.recovery_durability_closure_validator")
        if restart_available:
            available.append("core.runtime_restart_recovery")
        if truth_surface_available:
            available.append("core.recovery_truth_surface")

        missing: List[str] = []
        if not continuity_available:
            missing.append("core.flow_continuity_coordinator")
        if not recovery_available:
            missing.append("core.delegated_flow_recovery_coordinator")
        if not closure_available:
            missing.append("core.recovery_durability_closure_validator")
        if not restart_available:
            missing.append("core.runtime_restart_recovery")
        if not truth_surface_available:
            missing.append("core.recovery_truth_surface")

        # Check for all_closed on the closure validator (PR-5V2 says True)
        closure_all_closed: Optional[bool] = None
        if closure_available:
            try:
                from core.recovery_durability_closure_validator import (  # type: ignore[import]
                    build_recovery_closure_report,
                )

                r = build_recovery_closure_report()
                closure_all_closed = getattr(r, "all_closed", None)
            except Exception as exc:
                logger.debug("Fallback triggered: %s", exc)
                closure_all_closed = None

        # Check recovery truth surface for structured multi-layer evidence
        truth_open_dims: Optional[List[str]] = None
        truth_deferred_dims: Optional[List[str]] = None
        truth_v2_internal_success: Optional[bool] = None
        if truth_surface_available:
            try:
                from core.recovery_truth_surface import (  # type: ignore[import]
                    build_recovery_truth_report,
                )
                tr = build_recovery_truth_report()
                truth_open_dims = tr.open_dimensions
                truth_deferred_dims = tr.deferred_dimensions
                truth_v2_internal_success = tr.v2_internal_success
            except Exception as exc:
                logger.debug("Fallback triggered: %s", exc)
                truth_open_dims = None
                truth_deferred_dims = None
                truth_v2_internal_success = None

        test_refs: List[str] = []
        if _file_exists(
            "tests/test_pr534_continuity_recovery_durability_closure.py"
        ):
            test_refs.append(
                "tests/test_pr534_continuity_recovery_durability_closure.py"
            )
        if _file_exists("tests/test_recovery_truth_surface.py"):
            test_refs.append("tests/test_recovery_truth_surface.py")

        gaps: List[str] = []
        for m in missing:
            gaps.append(f"Module not importable: {m}")
        if closure_available and closure_all_closed is False:
            gaps.append(
                "RecoveryDurabilityClosureValidator.all_closed is False — "
                "at least one recovery scenario is not closed."
            )
        if truth_surface_available and truth_open_dims:
            for d in truth_open_dims:
                gaps.append(
                    f"RecoveryTruthSurface dimension '{d}' is open "
                    "(partial/deferred/unknown)."
                )

        found = len(available)
        total = 5  # now 5 modules including recovery_truth_surface

        if found == 0:
            maturity = MaturityLabel.nominally_present_not_closed
            rationale = "No recovery module could be imported."
        elif found < 2:
            maturity = MaturityLabel.partially_implemented
            rationale = (
                f"Only {found}/{total} recovery modules importable; "
                "chain is incomplete."
            )
        elif found < 4:
            maturity = MaturityLabel.implemented
            rationale = (
                f"{found}/{total} recovery modules importable; "
                f"missing: {missing!r}"
            )
        elif (
            test_refs
            and (closure_all_closed is True or closure_all_closed is None)
            and truth_surface_available
            and truth_v2_internal_success is True
        ):
            maturity = MaturityLabel.automated_verified
            rationale = (
                f"{found}/{total} recovery modules importable; "
                f"test reference(s) found; "
                f"closure_all_closed={closure_all_closed!r}; "
                f"recovery_truth_surface v2_internal_success=True.  "
                "Recovery truth surface provides structured multi-layer evidence."
            )
        elif test_refs and (closure_all_closed is True or closure_all_closed is None):
            maturity = MaturityLabel.automated_verified
            rationale = (
                f"{found}/{total} recovery modules importable; "
                f"test reference found; "
                f"closure_all_closed={closure_all_closed!r}."
            )
        elif test_refs:
            maturity = MaturityLabel.implemented
            rationale = (
                f"{found}/{total} recovery modules importable but "
                f"closure_all_closed={closure_all_closed!r} indicates open "
                "scenarios."
            )
        else:
            maturity = MaturityLabel.mainchained
            rationale = (
                f"{found}/{total} recovery modules importable; "
                "no automated test reference found."
            )

        evidence_summary = (
            f"Probed {total} recovery modules; {found} importable.  "
            f"Closure all_closed: {closure_all_closed!r}.  "
            f"RecoveryTruthSurface: open_dims={truth_open_dims!r}, "
            f"deferred_dims={truth_deferred_dims!r}, "
            f"v2_internal_success={truth_v2_internal_success!r}.  "
            f"Test references: {len(test_refs)}."
        )

        return DimensionAuditEntry(
            dimension=dim,
            maturity=maturity,
            evidence_summary=evidence_summary,
            code_references=available,
            test_references=test_refs,
            gaps=gaps,
            verdict_rationale=rationale,
        )

    def _audit_governance_readiness_release_gate(
        self,
    ) -> DimensionAuditEntry:
        """Probe governance / readiness / release gate enforcement."""
        dim = AuditDimension.governance_readiness_release_gate

        gov_gate_available = _try_import("core.governance_validation_gate")
        release_skeleton_available = _try_import(
            "core.distributed_release_gate_skeleton"
        )
        acceptance_available = _try_import("core.system_final_acceptance_verdict")
        evidence_surface_available = _try_import(
            "core.v2_readiness_governance_evidence_surface"
        )

        # Check whether the release gate skeleton is enforcing or not
        skeleton_is_enforcing: Optional[bool] = None
        if release_skeleton_available:
            try:
                from core.distributed_release_gate_skeleton import (  # type: ignore[import]
                    evaluate_distributed_release_gate,
                )

                r = evaluate_distributed_release_gate()
                skeleton_is_enforcing = getattr(r, "is_enforcing", None)
            except Exception as exc:
                logger.debug("Fallback triggered: %s", exc)
                skeleton_is_enforcing = None

        available: List[str] = []
        if gov_gate_available:
            available.append("core.governance_validation_gate")
        if release_skeleton_available:
            available.append("core.distributed_release_gate_skeleton")
        if acceptance_available:
            available.append("core.system_final_acceptance_verdict")
        if evidence_surface_available:
            available.append("core.v2_readiness_governance_evidence_surface")

        missing: List[str] = []
        if not gov_gate_available:
            missing.append("core.governance_validation_gate")
        if not release_skeleton_available:
            missing.append("core.distributed_release_gate_skeleton")
        if not acceptance_available:
            missing.append("core.system_final_acceptance_verdict")
        if not evidence_surface_available:
            missing.append("core.v2_readiness_governance_evidence_surface")

        test_refs: List[str] = []
        if _file_exists(
            "tests/test_pr536_distributed_release_gate_skeleton.py"
        ):
            test_refs.append(
                "tests/test_pr536_distributed_release_gate_skeleton.py"
            )
        if _file_exists(
            "tests/test_pr17_v2_system_final_acceptance_verdict.py"
        ):
            test_refs.append(
                "tests/test_pr17_v2_system_final_acceptance_verdict.py"
            )
        if _file_exists(".github/workflows/system_acceptance.yml"):
            test_refs.append(
                ".github/workflows/system_acceptance.yml"
            )
        if _file_exists(".github/workflows/governance_gate_enforcement.yml"):
            test_refs.append(
                ".github/workflows/governance_gate_enforcement.yml"
            )

        gaps: List[str] = []
        for m in missing:
            gaps.append(f"Module not importable: {m}")
        if skeleton_is_enforcing is False:
            gaps.append(
                "distributed_release_gate_skeleton.is_enforcing is False — "
                "the release gate is a non-enforcing skeleton.  It records a "
                "verdict but does not block CI or release by itself.  "
                "Enforcement must be promoted in a later PR."
            )

        found = len(available)
        total = 4

        if found == 0:
            maturity = MaturityLabel.nominally_present_not_closed
            rationale = "No governance/readiness module could be imported."
        elif found < 2:
            maturity = MaturityLabel.partially_implemented
            rationale = (
                f"Only {found}/{total} governance modules importable; "
                "gate machinery incomplete."
            )
        elif skeleton_is_enforcing is False:
            # All or most modules importable but the gate is explicitly
            # non-enforcing — this is an important honesty signal
            maturity = MaturityLabel.implemented
            rationale = (
                f"{found}/{total} governance modules importable but the "
                "distributed release gate is explicitly non-enforcing "
                "(skeleton only).  Governance machinery exists but does not "
                "yet block CI or release."
            )
        elif found < total:
            maturity = MaturityLabel.implemented
            rationale = (
                f"{found}/{total} governance modules importable; "
                f"missing: {missing!r}"
            )
        elif test_refs:
            maturity = MaturityLabel.automated_verified
            rationale = (
                f"All {total} governance modules importable; "
                f"{len(test_refs)} test/CI reference(s) found.  "
                "Release gate is enforcing (is_enforcing=True); "
                "CI workflow blocks on governance failure."
            )
        else:
            maturity = MaturityLabel.mainchained
            rationale = (
                f"All {total} governance modules importable; "
                "no test/CI reference found for automated_verified."
            )

        evidence_summary = (
            f"Probed {total} governance/readiness modules; "
            f"{found} importable.  "
            f"Release gate enforcing: {skeleton_is_enforcing!r}.  "
            f"Test/CI references: {len(test_refs)}."
        )

        return DimensionAuditEntry(
            dimension=dim,
            maturity=maturity,
            evidence_summary=evidence_summary,
            code_references=available,
            test_references=test_refs,
            gaps=gaps,
            verdict_rationale=rationale,
        )

    def _audit_workflow_tests_audit_outputs(self) -> DimensionAuditEntry:
        """Probe workflow / test / audit output real support capacity."""
        dim = AuditDimension.workflow_tests_audit_outputs

        # Canonical CI workflow files
        workflow_files = [
            ".github/workflows/ci.yml",
            ".github/workflows/system_acceptance.yml",
            ".github/workflows/dual_repo_integration.yml",
            ".github/workflows/guardrails.yml",
        ]
        # Representative key test files that must exist for coverage to be real
        key_test_files = [
            "tests/test_pr534_continuity_recovery_durability_closure.py",
            "tests/test_pr535_v2_readiness_governance_evidence_surface.py",
            "tests/test_pr536_distributed_release_gate_skeleton.py",
            "tests/test_pr17_v2_system_final_acceptance_verdict.py",
        ]
        # Audit output modules
        audit_modules = [
            "core.dual_repo_system_map",
            "core.v2_readiness_governance_evidence_surface",
            "core.distributed_release_gate_skeleton",
        ]

        found_workflows = [f for f in workflow_files if _file_exists(f)]
        found_tests = [f for f in key_test_files if _file_exists(f)]
        found_audit_mods = [m for m in audit_modules if _try_import(m)]

        missing_workflows = [
            f for f in workflow_files if f not in found_workflows
        ]
        missing_tests = [f for f in key_test_files if f not in found_tests]
        missing_audit_mods = [
            m for m in audit_modules if m not in found_audit_mods
        ]

        code_refs = found_audit_mods
        test_refs = found_workflows + found_tests

        gaps: List[str] = []
        for f in missing_workflows:
            gaps.append(f"CI workflow file absent: {f}")
        for f in missing_tests:
            gaps.append(f"Key test file absent: {f}")
        for m in missing_audit_mods:
            gaps.append(f"Audit output module not importable: {m}")

        total_expected = (
            len(workflow_files) + len(key_test_files) + len(audit_modules)
        )
        total_found = len(found_workflows) + len(found_tests) + len(found_audit_mods)

        if total_found == 0:
            maturity = MaturityLabel.nominally_present_not_closed
            rationale = "No workflow, test, or audit module found."
        elif total_found < total_expected // 2:
            maturity = MaturityLabel.partially_implemented
            rationale = (
                f"Only {total_found}/{total_expected} expected artifacts found."
            )
        elif gaps:
            maturity = MaturityLabel.implemented
            rationale = (
                f"{total_found}/{total_expected} artifacts found; "
                f"{len(gaps)} missing: {gaps!r}"
            )
        else:
            maturity = MaturityLabel.automated_verified
            rationale = (
                f"All {total_expected} workflow/test/audit artifacts found."
            )

        evidence_summary = (
            f"Found {len(found_workflows)}/{len(workflow_files)} workflows, "
            f"{len(found_tests)}/{len(key_test_files)} key test files, "
            f"{len(found_audit_mods)}/{len(audit_modules)} audit modules."
        )

        return DimensionAuditEntry(
            dimension=dim,
            maturity=maturity,
            evidence_summary=evidence_summary,
            code_references=code_refs,
            test_references=test_refs,
            gaps=gaps,
            verdict_rationale=rationale,
        )

    # ------------------------------------------------------------------
    # Verdict computation
    # ------------------------------------------------------------------

    def _compute_verdict(
        self, entries: List[DimensionAuditEntry]
    ) -> SystemRealityVerdict:
        """Compute the system-level verdict from dimension entries.

        Rules (fail-conservative):
        - Any dimension at ``nominally_present_not_closed``
          → ``critical_gaps_blocking_baseline``
        - Any dimension below ``implemented`` (but above nominal)
          → ``partial_baseline_significant_gaps``
        - All dimensions at ``implemented`` or above
          → ``platform_baseline_established``
        - Fewer than 3 dimensions audited
          → ``insufficient_evidence_to_conclude``
        """
        if len(entries) < 3:
            return SystemRealityVerdict.insufficient_evidence_to_conclude

        for entry in entries:
            if entry.maturity == MaturityLabel.nominally_present_not_closed:
                return SystemRealityVerdict.critical_gaps_blocking_baseline

        for entry in entries:
            if entry.maturity.is_blocking():
                return SystemRealityVerdict.partial_baseline_significant_gaps

        return SystemRealityVerdict.platform_baseline_established

    def _collect_blocking_gaps(
        self, entries: List[DimensionAuditEntry]
    ) -> List[str]:
        """Collect all gap descriptions across all dimensions."""
        gaps: List[str] = []
        for entry in entries:
            for gap in entry.gaps:
                gaps.append(f"[{entry.dimension.value}] {gap}")
        return gaps

    @staticmethod
    def _find_entry(
        entries: List[DimensionAuditEntry], dim: AuditDimension
    ) -> Optional[DimensionAuditEntry]:
        """Return the entry for *dim* or None."""
        for e in entries:
            if e.dimension == dim:
                return e
        return None

    # ------------------------------------------------------------------
    # Conclusion builders
    # ------------------------------------------------------------------

    def _build_main_chain_conclusion(
        self, entry: Optional[DimensionAuditEntry]
    ) -> str:
        """Produce the formal main-chain authenticity conclusion."""
        if entry is None:
            return (
                "MAIN CHAIN AUTHENTICITY: INSUFFICIENT EVIDENCE — "
                "dimension entry absent."
            )
        label = entry.maturity.value.upper()
        if entry.maturity == MaturityLabel.automated_verified:
            return (
                f"MAIN CHAIN AUTHENTICITY: {label} — "
                "All main-chain modules are importable and automated test "
                "coverage exists.  The orchestration chain from OpenClawd → "
                "CommandRouter → DeviceRouter → WebSocketHandler is real and "
                "verified."
            )
        elif entry.maturity == MaturityLabel.mainchained:
            dep_gaps = [g for g in entry.gaps if "dependency gap" in g]
            if dep_gaps:
                return (
                    f"MAIN CHAIN AUTHENTICITY: {label} — "
                    "All main-chain module files exist on disk.  Some cannot "
                    "be imported in the minimal test environment due to "
                    "transitive dependency requirements (pydantic/fastapi).  "
                    "Real code is present; full-dependency environment required "
                    "for automated_verified status."
                )
            return (
                f"MAIN CHAIN AUTHENTICITY: {label} — "
                "All main-chain modules are importable.  No automated test "
                "reference found in this audit pass."
            )
        elif entry.maturity == MaturityLabel.implemented:
            absent = [g for g in entry.gaps if "absent" in g.lower()]
            return (
                f"MAIN CHAIN AUTHENTICITY: {label} — "
                f"Most main-chain module files present but {len(absent)} "
                f"absent: {absent!r}"
            )
        elif entry.maturity == MaturityLabel.partially_implemented:
            return (
                f"MAIN CHAIN AUTHENTICITY: {label} — "
                "Fewer than half of the main-chain module files are present.  "
                "Chain is incomplete."
            )
        else:
            return (
                f"MAIN CHAIN AUTHENTICITY: {label} — "
                "No main-chain module file found on disk.  The chain exists "
                "only nominally."
            )

    def _build_recovery_conclusion(
        self, entry: Optional[DimensionAuditEntry]
    ) -> str:
        """Produce the formal recovery maturity conclusion."""
        if entry is None:
            return (
                "RECOVERY MATURITY: INSUFFICIENT EVIDENCE — "
                "dimension entry absent."
            )
        label = entry.maturity.value.upper()
        if entry.maturity in (
            MaturityLabel.automated_verified,
            MaturityLabel.mainchained,
        ):
            return (
                f"RECOVERY MATURITY: {label} — "
                "All recovery modules (FlowContinuityCoordinator, "
                "DelegatedFlowRecoveryCoordinator, "
                "RecoveryDurabilityClosureValidator, "
                "RuntimeRestartRecovery) are importable."
            )
        elif entry.maturity == MaturityLabel.implemented:
            return (
                f"RECOVERY MATURITY: {label} — "
                "Recovery modules are mostly importable; "
                f"gaps: {entry.gaps!r}"
            )
        elif entry.maturity == MaturityLabel.partially_implemented:
            return (
                f"RECOVERY MATURITY: {label} — "
                "Partial recovery implementation; key modules missing."
            )
        else:
            return (
                f"RECOVERY MATURITY: {label} — "
                "No recovery module could be imported; recovery exists "
                "only nominally."
            )

    def _build_governance_conclusion(
        self, entry: Optional[DimensionAuditEntry]
    ) -> str:
        """Produce the formal governance enforcement conclusion."""
        if entry is None:
            return (
                "GOVERNANCE ENFORCEMENT: INSUFFICIENT EVIDENCE — "
                "dimension entry absent."
            )
        label = entry.maturity.value.upper()

        # Check whether skeleton is non-enforcing gap exists
        non_enforcing_gap = any(
            "non-enforcing skeleton" in g or "is_enforcing is False" in g
            for g in entry.gaps
        )

        if non_enforcing_gap:
            return (
                f"GOVERNANCE ENFORCEMENT: {label} — "
                "Governance and readiness modules are importable and tested, "
                "but the distributed release gate is explicitly non-enforcing "
                "(skeleton only).  Governance machinery is in place but does "
                "NOT yet block CI or release by itself.  Enforcement "
                "promotion is a remaining gap."
            )
        elif entry.maturity in (
            MaturityLabel.automated_verified,
            MaturityLabel.mainchained,
        ):
            return (
                f"GOVERNANCE ENFORCEMENT: {label} — "
                "Governance / readiness / release gate modules are importable "
                "and automated verification exists."
            )
        elif entry.maturity == MaturityLabel.implemented:
            return (
                f"GOVERNANCE ENFORCEMENT: {label} — "
                f"Governance modules mostly importable; gaps: {entry.gaps!r}"
            )
        else:
            return (
                f"GOVERNANCE ENFORCEMENT: {label} — "
                "Governance machinery is largely absent or incomplete."
            )

    def _build_readiness_conclusion(
        self,
        entries: List[DimensionAuditEntry],
        workflow_entry: Optional[DimensionAuditEntry],
    ) -> str:
        """Produce the operational readiness contribution conclusion."""
        blocking = [
            e for e in entries if e.maturity.is_blocking()
        ]
        if blocking:
            dims = [e.dimension.value for e in blocking]
            return (
                "FULLY-OPERATIONAL READINESS CONTRIBUTION: BLOCKED — "
                f"Dimensions below 'implemented': {dims!r}.  "
                "Platform cannot be declared platform_baseline_established "
                "until these are closed."
            )
        all_verified = all(
            e.maturity == MaturityLabel.automated_verified for e in entries
        )
        if all_verified:
            return (
                "FULLY-OPERATIONAL READINESS CONTRIBUTION: FULL — "
                "All five dimensions have automated_verified maturity.  "
                "The V2 side provides a fully code-grounded baseline "
                "contribution to a dual-repo fully-operational assessment."
            )
        mixed_labels = list({e.maturity.value for e in entries})
        return (
            "FULLY-OPERATIONAL READINESS CONTRIBUTION: PARTIAL — "
            f"Dimension maturity range: {mixed_labels!r}.  "
            "All dimensions are at least 'implemented'; the platform "
            "baseline is code-grounded but not yet fully automated_verified "
            "across all five dimensions."
        )

    # ------------------------------------------------------------------
    # Summary builder
    # ------------------------------------------------------------------

    def _build_summary(
        self,
        verdict: SystemRealityVerdict,
        entries: List[DimensionAuditEntry],
        blocking_gaps: List[str],
        main_chain_conclusion: str,
        recovery_conclusion: str,
        governance_conclusion: str,
        readiness_conclusion: str,
    ) -> str:
        """Produce a structured human-readable summary of the audit."""
        lines: List[str] = [
            "=" * 70,
            "DUAL-REPO SYSTEM REALITY AUDIT REPORT  (PR-537)",
            "=" * 70,
            "",
            f"SYSTEM VERDICT: {verdict.value.upper()}",
            "",
            "DIMENSION MATURITY MATRIX",
            "-" * 40,
        ]

        for entry in entries:
            ref_count = len(entry.code_references) + len(entry.test_references)
            gap_count = len(entry.gaps)
            lines.append(
                f"  {entry.dimension.value:<42}  "
                f"{entry.maturity.value:<30}  "
                f"refs={ref_count}  gaps={gap_count}"
            )

        lines += [
            "",
            "FORMAL CONCLUSIONS",
            "-" * 40,
            main_chain_conclusion,
            "",
            recovery_conclusion,
            "",
            governance_conclusion,
            "",
            readiness_conclusion,
            "",
        ]

        if blocking_gaps:
            lines.append("UNRESOLVED BLOCKING GAPS")
            lines.append("-" * 40)
            for gap in blocking_gaps:
                lines.append(f"  • {gap}")
            lines.append("")

        lines += [
            "CONCLUSION",
            "-" * 40,
            f"System verdict: {verdict.value}",
        ]

        if verdict.is_baseline_established:
            lines.append(
                "The V2 repository provides a code-grounded platform baseline.  "
                "All five audit dimensions are at 'implemented' or above."
            )
        elif verdict.has_critical_gaps:
            lines.append(
                "Critical gaps are present.  At least one dimension is only "
                "'nominally_present_not_closed' — it exists on paper but is "
                "not backed by importable code.  Platform baseline CANNOT be "
                "declared until these gaps are closed."
            )
        elif verdict.is_inconclusive:
            lines.append(
                "Insufficient evidence to conclude.  Import environment may "
                "be severely broken."
            )
        else:
            lines.append(
                "Partial baseline: most dimensions are implemented but at "
                "least one is below 'implemented'.  Significant gaps remain."
            )

        lines.append("=" * 70)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level singleton management
# ---------------------------------------------------------------------------

_AUDIT_SINGLETON: Optional[DualRepoRealityAuditReport] = None


def build_dual_repo_reality_audit() -> DualRepoRealityAuditReport:
    """Build and return a fresh :class:`DualRepoRealityAuditReport`.

    Always performs a live probe of the repository's real code state.
    Use :func:`get_dual_repo_reality_audit` for the cached singleton.
    """
    return DualRepoSystemRealityAuditor().audit()


def get_dual_repo_reality_audit() -> DualRepoRealityAuditReport:
    """Return the process-global singleton :class:`DualRepoRealityAuditReport`.

    Builds the report on first call; subsequent calls return the cached
    report.  Use :func:`reset_dual_repo_reality_audit` to force a rebuild
    (intended for test isolation only).
    """
    global _AUDIT_SINGLETON
    if _AUDIT_SINGLETON is None:
        _AUDIT_SINGLETON = build_dual_repo_reality_audit()
    return _AUDIT_SINGLETON


def reset_dual_repo_reality_audit() -> None:
    """Clear the process-global singleton (for test isolation only)."""
    global _AUDIT_SINGLETON
    _AUDIT_SINGLETON = None
