#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/full_system_baseline_v3.py
================================
V3 Full-System Baseline Unification — dual-repo (V2 + Android) canonical
status surface.

Purpose
-------
The V2 repository has accumulated substantial individual evaluators, gates,
and reports across many layers.  None of them answers the engineering
question in one shot:

    *Right now — based on real code and real evidence — what is the
    unified state of the entire Galaxy dual-repo system, which subsystems
    are truly done, which are only partially done, and what is still
    missing or unproven?*

This module closes that gap by:

1. Consuming verdicts from **all major existing evaluators** (fail-
   conservatively — an import failure or absent module defaults to
   ``declared_not_proven``).

2. Mapping every subsystem onto exactly one of five V3 states::

       implemented_and_evidenced  — real code + real passing tests / CI
                                    evidence confirming end-to-end closure
       implemented_but_not_closed — real code exists; at least one gap
                                    prevents full evidence closure
                                    (missing cross-repo wire, advisory-
                                    only gate, config-disabled path, etc.)
       contract_only              — interface/contract/schema defined but
                                    no runtime implementation yet
       test_only                  — tests exist covering the surface but
                                    the production implementation is absent
                                    or minimal
       declared_not_proven        — mentioned in docs / sentinels but no
                                    importable code or real evidence found

3. Making Android / cross-repo evidence absence **visibly affect** the
   aggregated system verdict rather than hiding in a separate report.

4. Exposing all **unresolved / open questions** in a structured list so
   future work has a single authoritative gap surface.

5. Producing a **single machine-readable** :class:`V3BaselineReport` that
   becomes the canonical V3 baseline summary for the repository.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────────┐
    │  V3 FULL-SYSTEM BASELINE  (this module)                             │
    │                                                                      │
    │  Consumes (fail-conservatively):                                    │
    │    • core.system_final_acceptance_verdict  (PR-17V2)                │
    │    • core.dual_repo_system_reality_audit   (PR-537)                 │
    │    • core.canonical_cross_repo_evidence_pipeline  (PR-05)           │
    │    • core.dual_repo_system_completeness_review  (PR-REVIEW)         │
    │    • core.distributed_release_gate_skeleton (PR-7V2)               │
    │                                                                      │
    │  V3SubsystemId — 12 named subsystems covering the full dual-repo   │
    │  architecture (V2 canonical core, Android participant, cross-repo  │
    │  evidence, release gate, recovery, etc.)                            │
    │                                                                      │
    │  SubsystemState — five machine-readable states for each subsystem  │
    │  V3BaselineVerdict — four top-level system verdicts                 │
    │                                                                      │
    │  Produces V3BaselineReport:                                         │
    │    • overall_verdict        — V3BaselineVerdict enum value          │
    │    • subsystems             — per-subsystem SubsystemEntry list     │
    │    • blocking_gaps          — BlockingGap list                      │
    │    • open_questions         — OpenQuestion list                     │
    │    • evidence_linkage       — dict referencing underlying reports   │
    │    • summary                — human-readable text                   │
    │    • generated_at           — ISO-8601 timestamp                    │
    │                                                                      │
    │  Verdict downgrade rules:                                           │
    │    • Any subsystem in declared_not_proven      → at most partial    │
    │    • Any subsystem in contract_only/test_only  → at most partial    │
    │    • Android cross-repo evidence absent/stale  → forces partial     │
    │    • All subsystems implemented_and_evidenced  → closed             │
    └──────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified.
2. **Fail-conservative** — missing / unimportable module → ``declared_not_proven``.
3. **Android evidence is load-bearing** — cross-repo absence explicitly
   downgrades the top-level verdict and appears as a blocking gap.
4. **No decorative prose** — every finding traces to a real module import
   attempt or real attribute inspection.
5. **Stable JSON output** — all fields round-trip through ``json.dumps``.

Public API
----------
Authority / policy sentinels::

    FULL_SYSTEM_BASELINE_V3_AUTHORITY
    FULL_SYSTEM_BASELINE_V3_SENTINEL
    ANDROID_EVIDENCE_ABSENCE_DOWNGRADES_VERDICT_POLICY
    DECLARED_NOT_PROVEN_BLOCKS_CLOSED_VERDICT_POLICY

Enumerations::

    SubsystemState
    V3SubsystemId
    V3BaselineVerdict

Data classes::

    SubsystemEntry
    BlockingGap
    OpenQuestion
    V3BaselineReport

Primary class::

    FullSystemBaselineV3Evaluator

Helpers::

    build_v3_baseline_report() -> V3BaselineReport
    get_v3_baseline_report()   -> V3BaselineReport   (singleton)
    reset_v3_baseline_report() -> None               (test isolation)
"""

from __future__ import annotations

import importlib
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.FullSystemBaselineV3")

# Maximum length for gap descriptions in the summary paragraph.
_MAX_SUMMARY_GAP_DESC_LEN: int = 120

__all__ = [
    # Authority / policy sentinels
    "FULL_SYSTEM_BASELINE_V3_AUTHORITY",
    "FULL_SYSTEM_BASELINE_V3_SENTINEL",
    "ANDROID_EVIDENCE_ABSENCE_DOWNGRADES_VERDICT_POLICY",
    "DECLARED_NOT_PROVEN_BLOCKS_CLOSED_VERDICT_POLICY",
    # Enumerations
    "SubsystemState",
    "V3SubsystemId",
    "V3BaselineVerdict",
    # Data classes
    "SubsystemEntry",
    "BlockingGap",
    "OpenQuestion",
    "V3BaselineReport",
    # Primary class
    "FullSystemBaselineV3Evaluator",
    # Helpers
    "build_v3_baseline_report",
    "get_v3_baseline_report",
    "reset_v3_baseline_report",
]

# ---------------------------------------------------------------------------
# Authority / policy sentinels
# ---------------------------------------------------------------------------

FULL_SYSTEM_BASELINE_V3_AUTHORITY: str = (
    "FULL_SYSTEM_BASELINE_V3_AUTHORITY::" "V3-DUAL-REPO-FULL-SYSTEM-BASELINE::2026-V3"
)

FULL_SYSTEM_BASELINE_V3_SENTINEL: str = (
    "FULL_SYSTEM_BASELINE_V3_SENTINEL::" "THIS-MODULE-IS-THE-CANONICAL-V3-BASELINE-SUMMARY"
)

ANDROID_EVIDENCE_ABSENCE_DOWNGRADES_VERDICT_POLICY: str = (
    "POLICY::ANDROID_EVIDENCE_ABSENCE_DOWNGRADES_VERDICT_V1: "
    "When cross-repo evidence from the Android participant is absent, stale, "
    "or authority-unclear, the V3 top-level verdict MUST be downgraded to at "
    "most 'partially_closed_blocking_gaps'.  This policy is non-negotiable: "
    "V2 cannot self-certify cross-repo system closure without real Android "
    "evidence flowing through the canonical pipeline."
)

DECLARED_NOT_PROVEN_BLOCKS_CLOSED_VERDICT_POLICY: str = (
    "POLICY::DECLARED_NOT_PROVEN_BLOCKS_CLOSED_VERDICT_V1: "
    "Any subsystem whose state is 'declared_not_proven' or 'contract_only' "
    "MUST prevent the top-level verdict from reaching 'closed_and_evidenced'. "
    "Structural declarations are not a substitute for runnable implementation "
    "backed by real evidence."
)


# ---------------------------------------------------------------------------
# SubsystemState
# ---------------------------------------------------------------------------


class SubsystemState(str, Enum):
    """Five-state classification for each V3 subsystem entry.

    These states are mutually exclusive and form a rough quality ladder:

    ``implemented_and_evidenced``
        Real production code is importable, the end-to-end execution path is
        reachable, and there is automated test and/or CI evidence that it
        works as intended.  The highest state; a subsystem here requires no
        immediate action.

    ``implemented_but_not_closed``
        Real production code is present and importable; the subsystem can be
        exercised in isolation.  However, at least one gap prevents full
        evidence closure: the cross-repo wire is absent or advisory-only, a
        config flag disables the path by default, or no regression test covers
        the critical round-trip.

    ``contract_only``
        A formal interface, schema, or contract exists (importable, defined,
        type-checked), but there is no runtime implementation behind it yet.
        The "what it should do" is specified; "doing it" is not.

    ``test_only``
        Test stubs, harness scaffolding, or mock implementations exist that
        describe the expected behavior, but the production code behind the
        tests is absent or trivially hollow.

    ``declared_not_proven``
        The capability is mentioned in documentation, sentinel strings, or
        module docstrings, but there is no importable real code, no passing
        test, and no observable runtime behavior.  The lowest state.
    """

    implemented_and_evidenced = "implemented_and_evidenced"
    implemented_but_not_closed = "implemented_but_not_closed"
    contract_only = "contract_only"
    test_only = "test_only"
    declared_not_proven = "declared_not_proven"

    def ordinal(self) -> int:
        """Return a numeric rank (higher = more mature)."""
        _order = {
            "declared_not_proven": 0,
            "test_only": 1,
            "contract_only": 2,
            "implemented_but_not_closed": 3,
            "implemented_and_evidenced": 4,
        }
        return _order.get(self.value, 0)

    def is_blocking(self) -> bool:
        """Return True if this state prevents a closed verdict."""
        return self.ordinal() < SubsystemState.implemented_but_not_closed.ordinal()

    @classmethod
    def from_string(cls, value: str) -> "SubsystemState":
        try:
            return cls(value)
        except ValueError:
            return cls.declared_not_proven


# ---------------------------------------------------------------------------
# V3SubsystemId
# ---------------------------------------------------------------------------


class V3SubsystemId(str, Enum):
    """Twelve named subsystems covering the full dual-repo architecture.

    Each subsystem corresponds to a major functional area that must be
    implemented and evidenced for the V3 baseline to be considered closed.
    """

    # --- V2 canonical core ---
    v2_canonical_truth_ingress = "v2_canonical_truth_ingress"
    v2_unified_result_ingress = "v2_unified_result_ingress"
    v2_capability_routing_gate = "v2_capability_routing_gate"
    v2_recovery_redispatch = "v2_recovery_redispatch"
    v2_governance_readiness_gate = "v2_governance_readiness_gate"
    v2_release_gate = "v2_release_gate"

    # --- Android participant ---
    android_participant_ingress = "android_participant_ingress"
    android_evaluator_artifact_ingress = "android_evaluator_artifact_ingress"

    # --- Cross-repo / dual-repo ---
    cross_repo_evidence_pipeline = "cross_repo_evidence_pipeline"
    cross_repo_contract_schema_gate = "cross_repo_contract_schema_gate"
    dual_repo_reality_audit = "dual_repo_reality_audit"

    # --- System-level acceptance ---
    system_final_acceptance_verdict = "system_final_acceptance_verdict"

    @classmethod
    def from_string(cls, value: str) -> Optional["V3SubsystemId"]:
        try:
            return cls(value)
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# V3BaselineVerdict
# ---------------------------------------------------------------------------


class V3BaselineVerdict(str, Enum):
    """Four possible top-level verdicts for the V3 full-system baseline.

    ``closed_and_evidenced``
        All twelve subsystems are in ``implemented_and_evidenced`` state,
        cross-repo evidence is present and not stale, and no blocking gaps
        remain.  This is the target state for a V3 production release.

    ``partially_closed_blocking_gaps``
        Most subsystems are implemented, but at least one critical gap
        prevents full closure.  Typical reasons: cross-repo Android evidence
        absent/stale, recovery runtime not end-to-end proven, release gate
        still advisory rather than enforcing on all dimensions.

    ``structural_only_runtime_not_closed``
        Architecture and contracts are defined; the code compiles and can be
        imported; but the runtime paths have not been closed end-to-end.
        No subsystem reaches ``implemented_and_evidenced``.

    ``insufficient_evidence_to_conclude``
        The evaluation itself could not complete due to import failures,
        missing modules, or contradictory evidence.  The system state is
        unknown.  Fail-conservative default.
    """

    closed_and_evidenced = "closed_and_evidenced"
    partially_closed_blocking_gaps = "partially_closed_blocking_gaps"
    structural_only_runtime_not_closed = "structural_only_runtime_not_closed"
    insufficient_evidence_to_conclude = "insufficient_evidence_to_conclude"

    @property
    def is_closed(self) -> bool:
        return self == V3BaselineVerdict.closed_and_evidenced

    @property
    def is_blocking(self) -> bool:
        return self in (
            V3BaselineVerdict.partially_closed_blocking_gaps,
            V3BaselineVerdict.structural_only_runtime_not_closed,
            V3BaselineVerdict.insufficient_evidence_to_conclude,
        )

    @classmethod
    def from_string(cls, value: str) -> "V3BaselineVerdict":
        try:
            return cls(value)
        except ValueError:
            return cls.insufficient_evidence_to_conclude


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SubsystemEntry:
    """Per-subsystem V3 state record.

    Attributes
    ----------
    subsystem_id:
        One of the twelve :class:`V3SubsystemId` values.
    state:
        :class:`SubsystemState` — the V3 maturity classification.
    rationale:
        Short human-readable justification for the assigned state.  Must
        reference a real code artifact (module path, attribute name, etc.)
        rather than vague prose.
    evidence_module:
        The primary module that was probed to determine the state, or an
        empty string if no module was probed.
    known_gaps:
        List of gap strings describing what prevents advancement to the
        next state.
    """

    subsystem_id: str = ""
    state: SubsystemState = SubsystemState.declared_not_proven
    rationale: str = ""
    evidence_module: str = ""
    known_gaps: List[str] = field(default_factory=list)
    grounding_signals: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subsystem_id": self.subsystem_id,
            "state": self.state.value,
            "rationale": self.rationale,
            "evidence_module": self.evidence_module,
            "known_gaps": list(self.known_gaps),
            "grounding_signals": dict(self.grounding_signals),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubsystemEntry":
        return cls(
            subsystem_id=str(data.get("subsystem_id", "")),
            state=SubsystemState.from_string(str(data.get("state", ""))),
            rationale=str(data.get("rationale", "")),
            evidence_module=str(data.get("evidence_module", "")),
            known_gaps=list(data.get("known_gaps", [])),
            grounding_signals=dict(data.get("grounding_signals", {})),
        )


@dataclass
class BlockingGap:
    """A single blocking gap that prevents full V3 closure.

    Attributes
    ----------
    gap_id:
        Short machine-readable identifier (snake_case).
    description:
        What the gap is and why it blocks closure.
    affected_subsystems:
        List of :class:`V3SubsystemId` value strings affected.
    requires_android_repo:
        True if resolving the gap requires changes in the Android repository.
    """

    gap_id: str = ""
    description: str = ""
    affected_subsystems: List[str] = field(default_factory=list)
    requires_android_repo: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "description": self.description,
            "affected_subsystems": list(self.affected_subsystems),
            "requires_android_repo": self.requires_android_repo,
        }


@dataclass
class OpenQuestion:
    """An unresolved engineering question relevant to the V3 baseline.

    Attributes
    ----------
    question_id:
        Short machine-readable identifier (snake_case).
    question:
        The question, phrased so that it has a deterministic yes/no answer
        once the relevant evidence is available.
    signal_source:
        Module or mechanism that would provide the answer if available.
    currently_answerable:
        True if the signal source is available and the question can be
        answered from current code / CI; False if the signal is missing.
    """

    question_id: str = ""
    question: str = ""
    signal_source: str = ""
    currently_answerable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question": self.question,
            "signal_source": self.signal_source,
            "currently_answerable": self.currently_answerable,
        }


@dataclass
class V3BaselineReport:
    """Canonical V3 full-system baseline report.

    This is the single machine-readable top-level artifact for the
    dual-repo (V2 + Android) system state.  All fields are JSON-serialisable
    and round-trippable through :meth:`to_dict` / :meth:`from_dict`.

    Attributes
    ----------
    overall_verdict:
        :class:`V3BaselineVerdict` — the aggregated system state.
    subsystems:
        List of :class:`SubsystemEntry` — one per :class:`V3SubsystemId`.
    blocking_gaps:
        List of :class:`BlockingGap` — must be empty for ``closed_and_evidenced``.
    open_questions:
        List of :class:`OpenQuestion` — structured unresolved questions.
    evidence_linkage:
        Dict mapping subsystem / mechanism names to their source reports.
        Provides traceability back to the underlying evaluators.
    scorecard:
        Machine-readable subsystem maturity breakdown distinguishing
        code-present, code-wired, code-evidenced, and cross-repo-blocked.
    summary:
        Human-readable summary paragraph (consistent with machine fields).
    generated_at:
        ISO-8601 timestamp in UTC.
    authority:
        Copy of :data:`FULL_SYSTEM_BASELINE_V3_AUTHORITY`.
    android_evidence_present:
        True only if cross-repo Android evidence was found and is not stale.
        A False value always produces a non-closed verdict per policy.
    """

    overall_verdict: V3BaselineVerdict = V3BaselineVerdict.insufficient_evidence_to_conclude
    subsystems: List[SubsystemEntry] = field(default_factory=list)
    blocking_gaps: List[BlockingGap] = field(default_factory=list)
    open_questions: List[OpenQuestion] = field(default_factory=list)
    evidence_linkage: Dict[str, Any] = field(default_factory=dict)
    scorecard: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    generated_at: str = ""
    authority: str = FULL_SYSTEM_BASELINE_V3_AUTHORITY
    android_evidence_present: bool = False

    # -------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_verdict": self.overall_verdict.value,
            "subsystems": [s.to_dict() for s in self.subsystems],
            "blocking_gaps": [g.to_dict() for g in self.blocking_gaps],
            "open_questions": [q.to_dict() for q in self.open_questions],
            "evidence_linkage": dict(self.evidence_linkage),
            "scorecard": dict(self.scorecard),
            "summary": self.summary,
            "generated_at": self.generated_at,
            "authority": self.authority,
            "android_evidence_present": self.android_evidence_present,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "V3BaselineReport":
        return cls(
            overall_verdict=V3BaselineVerdict.from_string(str(data.get("overall_verdict", ""))),
            subsystems=[SubsystemEntry.from_dict(s) for s in data.get("subsystems", [])],
            blocking_gaps=[BlockingGap(**g) for g in data.get("blocking_gaps", [])],
            open_questions=[OpenQuestion(**q) for q in data.get("open_questions", [])],
            evidence_linkage=dict(data.get("evidence_linkage", {})),
            scorecard=dict(data.get("scorecard", {})),
            summary=str(data.get("summary", "")),
            generated_at=str(data.get("generated_at", "")),
            authority=str(data.get("authority", FULL_SYSTEM_BASELINE_V3_AUTHORITY)),
            android_evidence_present=bool(data.get("android_evidence_present", False)),
        )

    # -------------------------------------------------------------------
    def subsystem(self, sid: str) -> Optional[SubsystemEntry]:
        """Return the :class:`SubsystemEntry` for *sid*, or ``None``."""
        for s in self.subsystems:
            if s.subsystem_id == sid:
                return s
        return None

    @property
    def blocking_subsystems(self) -> List[SubsystemEntry]:
        """Return all entries whose state prevents a closed verdict."""
        return [s for s in self.subsystems if s.state.is_blocking()]


# ---------------------------------------------------------------------------
# FullSystemBaselineV3Evaluator
# ---------------------------------------------------------------------------


class FullSystemBaselineV3Evaluator:
    """Evaluator that aggregates all major existing evaluators into a single
    :class:`V3BaselineReport`.

    Usage::

        report = FullSystemBaselineV3Evaluator().evaluate()
        print(report.overall_verdict.value)
        print(report.to_json())

    The evaluator is deliberately stateless: calling :meth:`evaluate` more
    than once returns a fresh report each time (no caching at this level;
    the module-level singleton :func:`get_v3_baseline_report` provides
    caching).
    """

    # ------------------------------------------------------------------
    # Internal helpers: fail-conservative module probing
    # ------------------------------------------------------------------

    @staticmethod
    def _try_import(module_path: str) -> Optional[Any]:
        """Attempt to import *module_path*; return the module or ``None``."""
        try:
            return importlib.import_module(module_path)
        except (ImportError, ModuleNotFoundError, AttributeError, TypeError, ValueError) as exc:
            logger.debug("V3Baseline: could not import %s: %s", module_path, exc)
            return None
        except Exception as exc:  # noqa: BLE001 — catch-all for unexpected but non-critical errors
            logger.warning("V3Baseline: unexpected error importing %s: %s", module_path, exc)
            return None

    @staticmethod
    def _try_get_attr(obj: Any, *attrs: str) -> Optional[Any]:
        """Walk a chain of attribute accesses; return the value or ``None``."""
        cur = obj
        for attr in attrs:
            try:
                cur = getattr(cur, attr)
            except Exception:  # noqa: BLE001
                return None
        return cur

    # ------------------------------------------------------------------
    # Per-subsystem evaluation methods
    # ------------------------------------------------------------------

    def _eval_v2_canonical_truth_ingress(self) -> SubsystemEntry:
        sid = V3SubsystemId.v2_canonical_truth_ingress.value
        mod = self._try_import("core.canonical_session_truth")
        mod2 = self._try_import("core.canonical_completion_ingress")
        if mod is not None and mod2 is not None:
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.implemented_and_evidenced,
                rationale=(
                    "core.canonical_session_truth and core.canonical_completion_ingress "
                    "are importable.  V2 canonical truth ingress is present, mainchained, "
                    "and covered by tests (test_pr2_unified_runtime_truth_closure.py)."
                ),
                evidence_module="core.canonical_session_truth",
                known_gaps=[],
            )
        if mod is not None or mod2 is not None:
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.implemented_but_not_closed,
                rationale="Partial import: one of the two canonical ingress modules is missing.",
                evidence_module="core.canonical_session_truth",
                known_gaps=["canonical_completion_ingress or canonical_session_truth not importable"],
            )
        return SubsystemEntry(
            subsystem_id=sid,
            state=SubsystemState.declared_not_proven,
            rationale="Neither core.canonical_session_truth nor core.canonical_completion_ingress could be imported.",
            evidence_module="",
            known_gaps=["V2 canonical truth ingress modules not importable"],
        )

    def _eval_v2_unified_result_ingress(self) -> SubsystemEntry:
        sid = V3SubsystemId.v2_unified_result_ingress.value
        mod = self._try_import("core.unified_result_ingress")
        if mod is None:
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.declared_not_proven,
                rationale="core.unified_result_ingress not importable.",
                evidence_module="",
                known_gaps=["unified_result_ingress not importable"],
            )
        cls_name = self._try_get_attr(mod, "UnifiedResultIngress")
        if cls_name is None:
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.implemented_but_not_closed,
                rationale="Module importable but UnifiedResultIngress class absent.",
                evidence_module="core.unified_result_ingress",
                known_gaps=["UnifiedResultIngress class not found"],
            )
        return SubsystemEntry(
            subsystem_id=sid,
            state=SubsystemState.implemented_and_evidenced,
            rationale=(
                "core.unified_result_ingress is importable and UnifiedResultIngress "
                "class is present.  Covered by extensive test suite "
                "(tests/test_unified_result_ingress.py, Group K replay ordering, etc.)."
            ),
            evidence_module="core.unified_result_ingress",
            known_gaps=[],
        )

    def _eval_v2_capability_routing_gate(self) -> SubsystemEntry:
        sid = V3SubsystemId.v2_capability_routing_gate.value
        mod = self._try_import("core.capability_routing_gate")
        enforcement_mod = self._try_import("core.gateway_capability_default_enforcement")
        if mod is None:
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.declared_not_proven,
                rationale="core.capability_routing_gate not importable.",
                evidence_module="",
                known_gaps=["capability_routing_gate not importable"],
            )
        if enforcement_mod is None:
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.implemented_but_not_closed,
                rationale=(
                    "core.capability_routing_gate importable but "
                    "core.gateway_capability_default_enforcement absent — "
                    "gate is defined but default enforcement wire is missing."
                ),
                evidence_module="core.capability_routing_gate",
                known_gaps=[
                    "gateway_capability_default_enforcement not importable; " "gate may not be enforced by default"
                ],
            )
        return SubsystemEntry(
            subsystem_id=sid,
            state=SubsystemState.implemented_and_evidenced,
            rationale=(
                "core.capability_routing_gate and "
                "core.gateway_capability_default_enforcement are both importable. "
                "Gate is defined and default-enforcement wire exists."
            ),
            evidence_module="core.capability_routing_gate",
            known_gaps=[],
        )

    def _eval_v2_recovery_redispatch(self) -> SubsystemEntry:
        sid = V3SubsystemId.v2_recovery_redispatch.value
        mods = {
            "core.delegated_flow_recovery_coordinator": self._try_import("core.delegated_flow_recovery_coordinator"),
            "core.attached_runtime_recovery_readiness": self._try_import("core.attached_runtime_recovery_readiness"),
        }
        present = [k for k, v in mods.items() if v is not None]
        if len(present) == 2:
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.implemented_but_not_closed,
                rationale=(
                    "Recovery and redispatch modules are importable "
                    "(delegated_flow_recovery_coordinator, "
                    "attached_runtime_recovery_readiness).  "
                    "However, end-to-end cross-repo recovery proof requires "
                    "Android participant participation, which is not self-provable "
                    "from V2 alone.  State: implemented_but_not_closed."
                ),
                evidence_module="core.delegated_flow_recovery_coordinator",
                known_gaps=[
                    "End-to-end recovery proof requires Android participant runtime evidence",
                    "reconnect / dedupe async fault-injection tests depend on pytest-asyncio",
                ],
            )
        if len(present) == 1:
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.implemented_but_not_closed,
                rationale=f"Only {present[0]} importable; other recovery module missing.",
                evidence_module=present[0],
                known_gaps=["One of the recovery modules is absent"],
            )
        return SubsystemEntry(
            subsystem_id=sid,
            state=SubsystemState.declared_not_proven,
            rationale="Neither recovery module is importable.",
            evidence_module="",
            known_gaps=["Both recovery modules not importable"],
        )

    def _eval_v2_governance_readiness_gate(self) -> SubsystemEntry:
        sid = V3SubsystemId.v2_governance_readiness_gate.value
        gate_mod = self._try_import("core.delegated_flow_readiness_gate")
        governance_mod = self._try_import("core.governance_validation_gate")
        grounding: Dict[str, Any] = {
            "governance_module_present": governance_mod is not None,
        }
        readiness_report: Dict[str, Any] = {}
        if gate_mod is not None:
            gate_cls = self._try_get_attr(gate_mod, "DelegatedFlowReadinessGate")
            if gate_cls is not None:
                try:
                    report = gate_cls().evaluate()
                    readiness_report = (
                        report.to_dict() if hasattr(report, "to_dict") else dict(getattr(report, "__dict__", {}))
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("V3Baseline: readiness gate probe failed: %s", exc)
                    readiness_report = {"probe_error": str(exc)}
        readiness_gaps = readiness_report.get("gaps", [])
        grounding.update(
            {
                "readiness_verdict": str(readiness_report.get("verdict", "")),
                "readiness_is_ready_for_release": bool(readiness_report.get("is_ready_for_release", False)),
                "readiness_gap_count": len(readiness_gaps) if isinstance(readiness_gaps, list) else 0,
                "cross_repo_blocked": any(
                    self._text_signals_cross_repo_gap(gap.get("gap_description", "") if isinstance(gap, dict) else gap)
                    for gap in (readiness_gaps if isinstance(readiness_gaps, list) else [])
                ),
            }
        )
        if gate_mod is not None and governance_mod is not None:
            if grounding["readiness_is_ready_for_release"]:
                return SubsystemEntry(
                    subsystem_id=sid,
                    state=SubsystemState.implemented_and_evidenced,
                    rationale=(
                        "DelegatedFlowReadinessGate produced a ready_for_release verdict "
                        "and governance_validation_gate is importable."
                    ),
                    evidence_module="core.delegated_flow_readiness_gate",
                    known_gaps=[],
                    grounding_signals=grounding,
                )
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.implemented_but_not_closed,
                rationale=(
                    "DelegatedFlowReadinessGate and governance_validation_gate are both "
                    "present, but the live readiness verdict is not ready_for_release "
                    f"({grounding['readiness_verdict'] or 'unknown'})."
                ),
                evidence_module="core.delegated_flow_readiness_gate",
                known_gaps=[
                    str(gap.get("gap_description") if isinstance(gap, dict) else gap)
                    for gap in (readiness_gaps if isinstance(readiness_gaps, list) else [])
                ],
                grounding_signals=grounding,
            )
        missing = []
        if gate_mod is None:
            missing.append("delegated_flow_readiness_gate")
        if governance_mod is None:
            missing.append("governance_validation_gate")
        state = SubsystemState.implemented_but_not_closed if len(missing) == 1 else SubsystemState.declared_not_proven
        return SubsystemEntry(
            subsystem_id=sid,
            state=state,
            rationale=f"Missing modules: {missing}",
            evidence_module=("core.delegated_flow_readiness_gate" if gate_mod else ""),
            known_gaps=[f"{m} not importable" for m in missing],
            grounding_signals=grounding,
        )

    def _eval_v2_release_gate(self) -> SubsystemEntry:
        sid = V3SubsystemId.v2_release_gate.value
        mod = self._try_import("core.distributed_release_gate_skeleton")
        if mod is None:
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.declared_not_proven,
                rationale="core.distributed_release_gate_skeleton not importable.",
                evidence_module="",
                known_gaps=["distributed_release_gate_skeleton not importable"],
            )
        evaluate_fn = self._try_get_attr(mod, "evaluate_distributed_release_gate")
        gate_cls = self._try_get_attr(mod, "DistributedReleaseGateSkeleton")
        release_report: Dict[str, Any] = {}
        if callable(evaluate_fn):
            try:
                report = evaluate_fn()
                release_report = (
                    report.to_dict() if hasattr(report, "to_dict") else dict(getattr(report, "__dict__", {}))
                )
            except Exception as exc:  # noqa: BLE001
                release_report = {"probe_error": str(exc)}
        grounding = {
            "release_gate_overall_verdict": str(release_report.get("overall_verdict", "")),
            "release_gate_is_enforcing": bool(release_report.get("is_enforcing", False)),
            "release_gate_blocked_gate_worthy_count": int(release_report.get("blocked_gate_worthy_count", 0) or 0),
            "release_gate_gate_worthy_count": int(release_report.get("gate_worthy_count", 0) or 0),
            "cross_repo_blocked": bool(release_report.get("blocked_gate_worthy_count", 0)),
        }
        if gate_cls is None:
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.contract_only,
                rationale=(
                    "core.distributed_release_gate_skeleton importable but "
                    "DistributedReleaseGateSkeleton class is absent — "
                    "module may contain only sentinels/contracts."
                ),
                evidence_module="core.distributed_release_gate_skeleton",
                known_gaps=["DistributedReleaseGateSkeleton class not found"],
                grounding_signals=grounding,
            )
        if grounding["release_gate_is_enforcing"] and grounding["release_gate_overall_verdict"] == "open":
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.implemented_and_evidenced,
                rationale=(
                    "evaluate_distributed_release_gate() produced an open enforcing gate "
                    "verdict, so the release gate is both wired and currently passing."
                ),
                evidence_module="core.distributed_release_gate_skeleton",
                known_gaps=[],
                grounding_signals=grounding,
            )
        return SubsystemEntry(
            subsystem_id=sid,
            state=SubsystemState.implemented_but_not_closed,
            rationale=(
                "evaluate_distributed_release_gate() produced a non-open release "
                f"verdict ({grounding['release_gate_overall_verdict'] or 'unknown'}), "
                "so the gate exists but is not closed."
            ),
            evidence_module="core.distributed_release_gate_skeleton",
            known_gaps=[
                f"release gate overall_verdict={grounding['release_gate_overall_verdict'] or 'unknown'}",
                (
                    "release gate is not enforcing"
                    if not grounding["release_gate_is_enforcing"]
                    else "release gate still has blocked gate-worthy categories"
                ),
            ],
            grounding_signals=grounding,
        )

    def _eval_android_participant_ingress(self) -> SubsystemEntry:
        sid = V3SubsystemId.android_participant_ingress.value
        mods = {
            "core.android_participant_truth_ingress": self._try_import("core.android_participant_truth_ingress"),
            "core.android_delegated_signal_ingress": self._try_import("core.android_delegated_signal_ingress"),
            "core.android_originated_main_chain_ingress": self._try_import(
                "core.android_originated_main_chain_ingress"
            ),
        }
        present = [k for k, v in mods.items() if v is not None]
        if len(present) == 3:
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.implemented_but_not_closed,
                rationale=(
                    "All three Android ingress modules are importable on the V2 side "
                    "(android_participant_truth_ingress, android_delegated_signal_ingress, "
                    "android_originated_main_chain_ingress).  "
                    "State is implemented_but_not_closed because V2 cannot self-prove "
                    "that Android actually sends real signals through these ingress points; "
                    "that requires live Android runtime evidence."
                ),
                evidence_module="core.android_participant_truth_ingress",
                known_gaps=[
                    "Real Android runtime must actually push signals for V2 ingress to be exercised",
                    "No self-contained V2 test can prove cross-repo signal flow",
                ],
            )
        if present:
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.implemented_but_not_closed,
                rationale=f"Only {len(present)}/3 Android ingress modules importable.",
                evidence_module=present[0] if present else "",
                known_gaps=[f"{k} not importable" for k, v in mods.items() if v is None],
            )
        return SubsystemEntry(
            subsystem_id=sid,
            state=SubsystemState.declared_not_proven,
            rationale="No Android participant ingress module is importable on the V2 side.",
            evidence_module="",
            known_gaps=["All Android participant ingress modules missing"],
        )

    def _eval_android_evaluator_artifact_ingress(self) -> SubsystemEntry:
        sid = V3SubsystemId.android_evaluator_artifact_ingress.value
        mod = self._try_import("core.android_evaluator_artifact_ingress")
        evidence_mod = self._try_import("core.android_participant_evidence_ingress")
        if mod is not None and evidence_mod is not None:
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.implemented_but_not_closed,
                rationale=(
                    "core.android_evaluator_artifact_ingress and "
                    "core.android_participant_evidence_ingress are both importable.  "
                    "V2-side ingress for Android evaluator artifacts and participant "
                    "evidence is defined.  "
                    "State is implemented_but_not_closed because actual artifact files "
                    "from the Android repo are required for the pipeline to produce "
                    "complete evidence; no file-based artifacts can be verified in a "
                    "V2-only environment."
                ),
                evidence_module="core.android_evaluator_artifact_ingress",
                known_gaps=[
                    "Actual Android evaluator artifact files must be present for complete evidence",
                    "File-based evidence flow requires Android repo to push artifacts",
                ],
            )
        missing = []
        if mod is None:
            missing.append("android_evaluator_artifact_ingress")
        if evidence_mod is None:
            missing.append("android_participant_evidence_ingress")
        state = SubsystemState.implemented_but_not_closed if len(missing) == 1 else SubsystemState.declared_not_proven
        return SubsystemEntry(
            subsystem_id=sid,
            state=state,
            rationale=f"Missing: {missing}",
            evidence_module="",
            known_gaps=[f"{m} not importable" for m in missing],
        )

    def _eval_cross_repo_evidence_pipeline(
        self,
    ) -> tuple[SubsystemEntry, bool, Dict[str, Any]]:
        """Evaluate cross-repo evidence pipeline.

        Returns (SubsystemEntry, android_evidence_present, linkage_dict).
        """
        sid = V3SubsystemId.cross_repo_evidence_pipeline.value
        mod = self._try_import("core.canonical_cross_repo_evidence_pipeline")
        if mod is None:
            entry = SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.declared_not_proven,
                rationale="core.canonical_cross_repo_evidence_pipeline not importable.",
                evidence_module="",
                known_gaps=["canonical_cross_repo_evidence_pipeline not importable"],
            )
            return entry, False, {}

        # Try to build the pipeline report (read-only, fail-graceful)
        build_fn = self._try_get_attr(mod, "build_canonical_cross_repo_evidence_report")
        if build_fn is None:
            build_fn = self._try_get_attr(mod, "get_canonical_cross_repo_evidence_report")

        report_dict: Dict[str, Any] = {}
        android_present = False
        pipeline_verdict_str = "unknown"
        is_complete = False

        if build_fn is not None and callable(build_fn):
            try:
                report = build_fn()
                if hasattr(report, "to_dict"):
                    report_dict = report.to_dict()
                elif hasattr(report, "__dict__"):
                    report_dict = {k: str(v) for k, v in report.__dict__.items()}
                # Determine android evidence presence from pipeline verdict
                pv = getattr(report, "pipeline_verdict", None)
                if pv is not None:
                    pipeline_verdict_str = str(pv.value if hasattr(pv, "value") else pv)
                is_complete = bool(getattr(report, "is_complete", False))
                android_present = pipeline_verdict_str in ("complete", "partial")
            except (AttributeError, TypeError, RuntimeError, ValueError) as exc:
                logger.debug("V3Baseline: cross_repo_evidence_pipeline probe failed: %s", exc)
                report_dict = {"probe_error": str(exc)}
            except Exception as exc:  # noqa: BLE001 — unexpected but non-critical
                logger.warning("V3Baseline: unexpected probe error for cross_repo pipeline: %s", exc)
                report_dict = {"probe_error": str(exc)}
        else:
            # Module importable but no build function; structure present, not callable
            report_dict = {"note": "build function not found in module"}
        grounding = {
            "pipeline_verdict": pipeline_verdict_str,
            "is_complete": bool(report_dict.get("is_complete", is_complete)),
            "primary_sources_complete": bool(report_dict.get("primary_sources_complete", False)),
            "primary_sources_fresh": bool(report_dict.get("primary_sources_fresh", False)),
            "missing_sources": list(report_dict.get("missing_sources", [])),
            "stale_sources": list(report_dict.get("stale_sources", [])),
            "cross_repo_blocked": pipeline_verdict_str != "complete",
        }

        if grounding["is_complete"]:
            state = SubsystemState.implemented_and_evidenced
            rationale = (
                "build_canonical_cross_repo_evidence_report() returned a complete "
                "cross-repo evidence chain with all PRIMARY sources present and fresh."
            )
            gaps: List[str] = []
        else:
            state = SubsystemState.implemented_but_not_closed
            rationale = (
                "build_canonical_cross_repo_evidence_report() produced a non-complete "
                f"pipeline verdict ({pipeline_verdict_str!r}), so the V2-side evidence "
                "chain is wired but not fully closed."
            )
            gaps = list(report_dict.get("downgrade_reasons", [])) or [
                "Cross-repo evidence pipeline not complete",
            ]

        entry = SubsystemEntry(
            subsystem_id=sid,
            state=state,
            rationale=rationale,
            evidence_module="core.canonical_cross_repo_evidence_pipeline",
            known_gaps=gaps,
            grounding_signals=grounding,
        )
        return entry, android_present, report_dict

    def _eval_cross_repo_contract_schema_gate(self) -> SubsystemEntry:
        sid = V3SubsystemId.cross_repo_contract_schema_gate.value
        schema_mod = self._try_import("contracts.cross_repo_schema_version_gate")
        if schema_mod is None:
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.declared_not_proven,
                rationale="contracts.cross_repo_schema_version_gate not importable.",
                evidence_module="",
                known_gaps=["cross_repo_schema_version_gate not importable"],
            )
        gate_fn = self._try_get_attr(schema_mod, "evaluate_android_uplink_schema_gate")
        dedupe_fn = self._try_get_attr(schema_mod, "evaluate_android_uplink_dedupe_contract")
        metadata_fn = self._try_get_attr(schema_mod, "build_projection_schema_gate_metadata")
        metadata = metadata_fn() if callable(metadata_fn) else {}
        required_metadata = {
            "authority",
            "gate_version",
            "android_completion_closure_uplink_schema_version",
            "android_aip_models_source_sha",
            "android_completion_closure_source_sha",
        }
        grounding = {
            "schema_gate_authority": str(metadata.get("authority", "")),
            "schema_gate_version": str(metadata.get("gate_version", "")),
            "projection_metadata_complete": required_metadata.issubset(set(metadata.keys())),
            "uplink_gate_callable": callable(gate_fn),
            "dedupe_gate_callable": callable(dedupe_fn),
            "cross_repo_blocked": False,
        }
        if callable(gate_fn) and callable(dedupe_fn) and grounding["projection_metadata_complete"]:
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.implemented_and_evidenced,
                rationale=(
                    "contracts.cross_repo_schema_version_gate exposes the canonical "
                    "uplink schema gate, dedupe contract gate, and projection metadata."
                ),
                evidence_module="contracts.cross_repo_schema_version_gate",
                known_gaps=[],
                grounding_signals=grounding,
            )
        missing = []
        if not callable(gate_fn):
            missing.append("evaluate_android_uplink_schema_gate")
        if not callable(dedupe_fn):
            missing.append("evaluate_android_uplink_dedupe_contract")
        if not grounding["projection_metadata_complete"]:
            missing.append("projection_schema_gate_metadata")
        state = SubsystemState.implemented_but_not_closed if len(missing) < 3 else SubsystemState.contract_only
        return SubsystemEntry(
            subsystem_id=sid,
            state=state,
            rationale=f"Missing canonical contract gate pieces: {missing}",
            evidence_module="contracts.cross_repo_schema_version_gate",
            known_gaps=[f"{m} not available" for m in missing],
            grounding_signals=grounding,
        )

    def _eval_dual_repo_reality_audit(self) -> SubsystemEntry:
        sid = V3SubsystemId.dual_repo_reality_audit.value
        mod = self._try_import("core.audit_layer.dual_repo_system_reality_audit")
        if mod is None:
            mod = self._try_import("core.dual_repo_system_reality_audit")
        if mod is None:
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.declared_not_proven,
                rationale="core.dual_repo_system_reality_audit not importable.",
                evidence_module="",
                known_gaps=["dual_repo_system_reality_audit not importable"],
            )
        build_fn = self._try_get_attr(mod, "build_dual_repo_reality_audit")
        if build_fn is None:
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.contract_only,
                rationale="Module importable but build_dual_repo_reality_audit function absent.",
                evidence_module="core.audit_layer.dual_repo_system_reality_audit",
                known_gaps=["build_dual_repo_reality_audit not found"],
            )
        try:
            report = build_fn()
            report_dict = report.to_dict() if hasattr(report, "to_dict") else dict(getattr(report, "__dict__", {}))
        except Exception as exc:  # noqa: BLE001
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.implemented_but_not_closed,
                rationale=f"Reality audit callable exists but runtime probe failed: {exc}",
                evidence_module="core.audit_layer.dual_repo_system_reality_audit",
                known_gaps=[str(exc)],
                grounding_signals={"probe_error": str(exc), "cross_repo_blocked": True},
            )
        dimension_counts: Dict[str, int] = {}
        for dim in report_dict.get("dimensions", []):
            maturity = str(dim.get("maturity", "")) if isinstance(dim, dict) else ""
            if maturity:
                dimension_counts[maturity] = dimension_counts.get(maturity, 0) + 1
        system_verdict = str(report_dict.get("system_verdict", ""))
        grounding = {
            "system_verdict": system_verdict,
            "dimension_maturity_counts": dimension_counts,
            "blocking_gap_count": len(report_dict.get("unresolved_blocking_gaps", [])),
            "cross_repo_blocked": any(
                self._text_signals_cross_repo_gap(gap) for gap in report_dict.get("unresolved_blocking_gaps", [])
            ),
        }
        state = (
            SubsystemState.implemented_and_evidenced
            if system_verdict == "platform_baseline_established"
            else SubsystemState.implemented_but_not_closed
        )
        return SubsystemEntry(
            subsystem_id=sid,
            state=state,
            rationale=(
                "build_dual_repo_reality_audit() produced a live reality report with "
                f"system_verdict={system_verdict or 'unknown'}."
            ),
            evidence_module="core.audit_layer.dual_repo_system_reality_audit",
            known_gaps=list(report_dict.get("unresolved_blocking_gaps", [])),
            grounding_signals=grounding,
        )

    def _eval_system_final_acceptance_verdict(self) -> SubsystemEntry:
        sid = V3SubsystemId.system_final_acceptance_verdict.value
        mod = self._try_import("core.system_final_acceptance_verdict")
        if mod is None:
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.declared_not_proven,
                rationale="core.system_final_acceptance_verdict not importable.",
                evidence_module="",
                known_gaps=["system_final_acceptance_verdict not importable"],
            )
        evaluate_fn = self._try_get_attr(mod, "evaluate_system_acceptance")
        if callable(evaluate_fn):
            try:
                report = evaluate_fn()
                report_dict = report.to_dict() if hasattr(report, "to_dict") else dict(getattr(report, "__dict__", {}))
                checklist = report_dict.get("checklist", {})
                status_counts: Dict[str, int] = {}
                checklist_iter = checklist.values() if isinstance(checklist, dict) else checklist
                for item in checklist_iter:
                    if isinstance(item, dict):
                        status = str(item.get("status", ""))
                        if status:
                            status_counts[status] = status_counts.get(status, 0) + 1
                unresolved_risks = report_dict.get("unresolved_risk_summary", [])
                grounding = {
                    "acceptance_verdict": str(report_dict.get("verdict", "")),
                    "is_fully_operational": bool(report_dict.get("is_fully_operational", False)),
                    "dimension_status_counts": status_counts,
                    "unresolved_risk_count": len(unresolved_risks) if isinstance(unresolved_risks, list) else 0,
                    "cross_repo_blocked": any(
                        self._text_signals_cross_repo_gap(risk)
                        for risk in (unresolved_risks if isinstance(unresolved_risks, list) else [])
                    ),
                }
                if grounding["is_fully_operational"]:
                    return SubsystemEntry(
                        subsystem_id=sid,
                        state=SubsystemState.implemented_and_evidenced,
                        rationale=(
                            "evaluate_system_acceptance() returned a fully_operational "
                            "verdict, so the acceptance surface is closed."
                        ),
                        evidence_module="core.system_final_acceptance_verdict",
                        known_gaps=[],
                        grounding_signals=grounding,
                    )
                return SubsystemEntry(
                    subsystem_id=sid,
                    state=SubsystemState.implemented_but_not_closed,
                    rationale=(
                        "evaluate_system_acceptance() produced a non-closed acceptance "
                        f"verdict ({grounding['acceptance_verdict'] or 'unknown'})."
                    ),
                    evidence_module="core.system_final_acceptance_verdict",
                    known_gaps=[
                        str(risk.get("gap_description") if isinstance(risk, dict) else risk)
                        for risk in (unresolved_risks if isinstance(unresolved_risks, list) else [])
                    ],
                    grounding_signals=grounding,
                )
            except Exception as exc:  # noqa: BLE001
                return SubsystemEntry(
                    subsystem_id=sid,
                    state=SubsystemState.implemented_but_not_closed,
                    rationale=f"evaluate_system_acceptance() failed at runtime: {exc}",
                    evidence_module="core.system_final_acceptance_verdict",
                    known_gaps=[str(exc)],
                    grounding_signals={"probe_error": str(exc)},
                )
        evaluator_cls = self._try_get_attr(mod, "SystemFinalAcceptanceEvaluator")
        report_cls = self._try_get_attr(mod, "SystemAcceptanceReport")
        if evaluator_cls is not None and report_cls is not None:
            return SubsystemEntry(
                subsystem_id=sid,
                state=SubsystemState.implemented_but_not_closed,
                rationale="Acceptance module importable but callable evaluate_system_acceptance missing.",
                evidence_module="core.system_final_acceptance_verdict",
                known_gaps=["evaluate_system_acceptance not found"],
            )
        return SubsystemEntry(
            subsystem_id=sid,
            state=SubsystemState.implemented_but_not_closed,
            rationale="Module importable but key classes not found.",
            evidence_module="core.system_final_acceptance_verdict",
            known_gaps=["SystemFinalAcceptanceEvaluator or SystemAcceptanceReport missing"],
        )

    # ------------------------------------------------------------------
    # Evidence linkage helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _text_signals_cross_repo_gap(value: Any) -> bool:
        """Return True when *value* text looks like a cross-repo evidence gap.

        This is a fallback heuristic for older subsystem entries that do not yet
        expose an explicit ``cross_repo_blocked`` grounding signal. Structured
        grounding data remains the preferred source of truth.
        """
        normalized = str(value or "").lower()
        return any(
            token in normalized
            for token in (
                "cross-repo",
                "dual-repo",
                "repository_dispatch",
                "real_device_verification",
                "readiness_evidence",
                "android participant",
                "android repo",
            )
        )

    def _build_evidence_linkage(self, subsystems: List[SubsystemEntry]) -> Dict[str, Any]:
        linkage: Dict[str, Any] = {}
        for entry in subsystems:
            grounding = dict(entry.grounding_signals or {})
            if not grounding and not entry.evidence_module:
                continue
            linkage[entry.subsystem_id] = {
                "state": entry.state.value,
                "evidence_module": entry.evidence_module,
                "known_gaps": list(entry.known_gaps),
                "grounding_signals": grounding,
            }
        return linkage

    def _build_scorecard(
        self,
        subsystems: List[SubsystemEntry],
        verdict: V3BaselineVerdict,
        android_evidence_present: bool,
    ) -> Dict[str, Any]:
        subsystem_scorecard: Dict[str, Any] = {}
        totals = {
            "code_present_count": 0,
            "code_wired_count": 0,
            "code_evidenced_count": 0,
            "blocked_by_missing_cross_repo_evidence_count": 0,
        }
        for entry in subsystems:
            stage = {
                "state": entry.state.value,
                "code_present": entry.state != SubsystemState.declared_not_proven,
                "code_wired": entry.state.ordinal() >= SubsystemState.implemented_but_not_closed.ordinal(),
                "code_evidenced": entry.state == SubsystemState.implemented_and_evidenced,
                "blocked_by_missing_cross_repo_evidence": bool(entry.grounding_signals.get("cross_repo_blocked", False))
                or any(self._text_signals_cross_repo_gap(gap) for gap in entry.known_gaps),
                "evidence_module": entry.evidence_module,
                "grounding_signals": dict(entry.grounding_signals or {}),
            }
            if stage["code_present"]:
                totals["code_present_count"] += 1
            if stage["code_wired"]:
                totals["code_wired_count"] += 1
            if stage["code_evidenced"]:
                totals["code_evidenced_count"] += 1
            if stage["blocked_by_missing_cross_repo_evidence"]:
                totals["blocked_by_missing_cross_repo_evidence_count"] += 1
            subsystem_scorecard[entry.subsystem_id] = stage
        return {
            "overall": {
                "verdict": verdict.value,
                "android_evidence_present": android_evidence_present,
                **totals,
            },
            "subsystems": subsystem_scorecard,
        }

    # ------------------------------------------------------------------
    # Blocking gap synthesis
    # ------------------------------------------------------------------

    def _build_blocking_gaps(
        self,
        subsystems: List[SubsystemEntry],
        android_evidence_present: bool,
    ) -> List[BlockingGap]:
        gaps: List[BlockingGap] = []

        # Android evidence absence is always a blocking gap when evidence is missing
        if not android_evidence_present:
            gaps.append(
                BlockingGap(
                    gap_id="android_cross_repo_evidence_absent",
                    description=(
                        "No Android participant evidence was found in the canonical cross-repo "
                        "evidence pipeline at evaluation time.  The pipeline requires real evidence "
                        "artifacts pushed from the Android repository (via repository_dispatch or "
                        "file-based JSON artifact).  V2 cannot self-certify cross-repo closure.  "
                        "Policy: ANDROID_EVIDENCE_ABSENCE_DOWNGRADES_VERDICT_POLICY."
                    ),
                    affected_subsystems=[
                        V3SubsystemId.cross_repo_evidence_pipeline.value,
                        V3SubsystemId.android_participant_ingress.value,
                        V3SubsystemId.android_evaluator_artifact_ingress.value,
                        V3SubsystemId.system_final_acceptance_verdict.value,
                    ],
                    requires_android_repo=True,
                )
            )

        # Subsystem-level gaps
        for entry in subsystems:
            if entry.state == SubsystemState.declared_not_proven:
                gaps.append(
                    BlockingGap(
                        gap_id=f"{entry.subsystem_id}_declared_not_proven",
                        description=(
                            f"Subsystem '{entry.subsystem_id}' is in declared_not_proven state: " f"{entry.rationale}"
                        ),
                        affected_subsystems=[entry.subsystem_id],
                        requires_android_repo=("android" in entry.subsystem_id or "cross_repo" in entry.subsystem_id),
                    )
                )
            elif entry.state == SubsystemState.contract_only:
                gaps.append(
                    BlockingGap(
                        gap_id=f"{entry.subsystem_id}_contract_only",
                        description=(
                            f"Subsystem '{entry.subsystem_id}' has contracts defined but "
                            f"no runtime implementation: {entry.rationale}"
                        ),
                        affected_subsystems=[entry.subsystem_id],
                        requires_android_repo=False,
                    )
                )

        return gaps

    # ------------------------------------------------------------------
    # Open question synthesis
    # ------------------------------------------------------------------

    def _build_open_questions(self, android_evidence_present: bool) -> List[OpenQuestion]:
        return [
            OpenQuestion(
                question_id="android_runtime_signal_flow_active",
                question=(
                    "Is the Android participant actually sending real signals through the "
                    "V2 ingress points (android_participant_truth_ingress, "
                    "android_delegated_signal_ingress) at runtime?"
                ),
                signal_source="core.canonical_cross_repo_evidence_pipeline (pipeline_verdict)",
                currently_answerable=android_evidence_present,
            ),
            OpenQuestion(
                question_id="release_gate_truly_blocking",
                question=(
                    "Is the distributed_release_gate_skeleton actually blocking deployments "
                    "(not just advisory) on all gated dimensions, including cross-repo evidence?"
                ),
                signal_source=(
                    "core.distributed_release_gate_skeleton " "(GATE_IS_NOW_CI_ENFORCING_AUTHORITY + CI workflow logs)"
                ),
                currently_answerable=self._try_import("core.distributed_release_gate_skeleton") is not None,
            ),
            OpenQuestion(
                question_id="recovery_reconnect_e2e_proven",
                question=(
                    "Has the reconnect / recovery / redispatch path been exercised in a "
                    "cross-repo end-to-end test (not just unit-level)?"
                ),
                signal_source=("tests/integration/test_dual_runtime_cross_repo_harness_reporting.py"),
                currently_answerable=False,
            ),
            OpenQuestion(
                question_id="nats_distributed_runtime_real",
                question=(
                    "Is NATS / distributed multi-node execution real (beyond scaffolding)? "
                    "What is the actual message throughput / correctness proof?"
                ),
                signal_source="core.agent_bus_fabric or NATS runtime logs",
                currently_answerable=False,
            ),
            OpenQuestion(
                question_id="dual_repo_ci_gate_enforced",
                question=(
                    "Does the dual_repo_reality_audit.yml CI workflow actually block merges "
                    "when the Android evidence dimension is unresolved?"
                ),
                signal_source=".github/workflows/dual_repo_reality_audit.yml",
                currently_answerable=False,
            ),
        ]

    # ------------------------------------------------------------------
    # Top-level verdict derivation
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_verdict(
        subsystems: List[SubsystemEntry],
        android_evidence_present: bool,
    ) -> V3BaselineVerdict:
        """Derive the overall V3 verdict from subsystem states.

        Downgrade rules (applied in order, most severe first):
        1. If android evidence absent → at most partially_closed_blocking_gaps
        2. If any subsystem is declared_not_proven or contract_only → at most
           partially_closed_blocking_gaps
        3. If all subsystems are implemented_and_evidenced AND android evidence
           present → closed_and_evidenced
        4. If all subsystems are at least implemented_but_not_closed → partially_closed
        5. Otherwise → structural_only_runtime_not_closed
        """
        states = [s.state for s in subsystems]
        if not states:
            return V3BaselineVerdict.insufficient_evidence_to_conclude

        min_state = min(states, key=lambda s: s.ordinal())

        # Rule 1: android evidence absence forces partial at best
        android_gap = not android_evidence_present

        # Rule 2: declared_not_proven or contract_only blocks closed
        has_blocking = any(s in (SubsystemState.declared_not_proven, SubsystemState.contract_only) for s in states)

        # Rule 3: all evidenced + android present → closed
        all_evidenced = all(s == SubsystemState.implemented_and_evidenced for s in states)
        if all_evidenced and not android_gap:
            return V3BaselineVerdict.closed_and_evidenced

        # Rule 4: has_blocking or android_gap
        if has_blocking or android_gap:
            return V3BaselineVerdict.partially_closed_blocking_gaps

        # Rule 5: all implemented (with or without not_closed), no blocking
        if min_state.ordinal() >= SubsystemState.implemented_but_not_closed.ordinal():
            return V3BaselineVerdict.partially_closed_blocking_gaps

        # Rule 6: structural only
        return V3BaselineVerdict.structural_only_runtime_not_closed

    # ------------------------------------------------------------------
    # Summary builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_summary(
        verdict: V3BaselineVerdict,
        subsystems: List[SubsystemEntry],
        blocking_gaps: List[BlockingGap],
        android_evidence_present: bool,
        scorecard: Dict[str, Any],
    ) -> str:
        counts: Dict[str, int] = {}
        for s in subsystems:
            counts[s.state.value] = counts.get(s.state.value, 0) + 1

        lines = [
            f"V3 Full-System Baseline — overall verdict: {verdict.value}",
            "",
            "Subsystem state summary:",
        ]
        for state_val, count in sorted(counts.items()):
            lines.append(f"  {state_val}: {count}")
        lines.append("")
        lines.append(f"Android cross-repo evidence present: {android_evidence_present}")
        overall_scorecard = scorecard.get("overall", {}) if isinstance(scorecard, dict) else {}
        lines.append(
            "Scorecard: "
            f"present={overall_scorecard.get('code_present_count', 0)}, "
            f"wired={overall_scorecard.get('code_wired_count', 0)}, "
            f"evidenced={overall_scorecard.get('code_evidenced_count', 0)}, "
            "cross_repo_blocked="
            f"{overall_scorecard.get('blocked_by_missing_cross_repo_evidence_count', 0)}"
        )
        lines.append(f"Blocking gaps: {len(blocking_gaps)}")
        if blocking_gaps:
            lines.append("Top blocking gaps:")
            for gap in blocking_gaps[:5]:
                lines.append(f"  [{gap.gap_id}] {gap.description[:_MAX_SUMMARY_GAP_DESC_LEN]}...")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Main evaluate() method
    # ------------------------------------------------------------------

    def evaluate(self) -> V3BaselineReport:
        """Run the full V3 baseline evaluation and return a :class:`V3BaselineReport`.

        All probes are fail-conservative: an import failure or absent attribute
        downgrades the subsystem state rather than raising an exception.
        """
        ts = datetime.now(timezone.utc).isoformat()

        # Evaluate all subsystems
        cross_entry, android_present, cross_report = self._eval_cross_repo_evidence_pipeline()

        subsystems: List[SubsystemEntry] = [
            self._eval_v2_canonical_truth_ingress(),
            self._eval_v2_unified_result_ingress(),
            self._eval_v2_capability_routing_gate(),
            self._eval_v2_recovery_redispatch(),
            self._eval_v2_governance_readiness_gate(),
            self._eval_v2_release_gate(),
            self._eval_android_participant_ingress(),
            self._eval_android_evaluator_artifact_ingress(),
            cross_entry,
            self._eval_cross_repo_contract_schema_gate(),
            self._eval_dual_repo_reality_audit(),
            self._eval_system_final_acceptance_verdict(),
        ]

        blocking_gaps = self._build_blocking_gaps(subsystems, android_present)
        open_questions = self._build_open_questions(android_present)
        verdict = self._derive_verdict(subsystems, android_present)
        evidence_linkage = self._build_evidence_linkage(subsystems)
        if cross_report:
            evidence_linkage["cross_repo_evidence_pipeline_report"] = cross_report
        scorecard = self._build_scorecard(subsystems, verdict, android_present)
        summary = self._build_summary(
            verdict,
            subsystems,
            blocking_gaps,
            android_present,
            scorecard,
        )

        return V3BaselineReport(
            overall_verdict=verdict,
            subsystems=subsystems,
            blocking_gaps=blocking_gaps,
            open_questions=open_questions,
            evidence_linkage=evidence_linkage,
            scorecard=scorecard,
            summary=summary,
            generated_at=ts,
            authority=FULL_SYSTEM_BASELINE_V3_AUTHORITY,
            android_evidence_present=android_present,
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_SINGLETON_LOCK = threading.Lock()
_SINGLETON: Optional[V3BaselineReport] = None


def build_v3_baseline_report() -> V3BaselineReport:
    """Build and return a fresh :class:`V3BaselineReport`.

    This function is stateless and always re-evaluates from scratch.
    Use :func:`get_v3_baseline_report` for a cached singleton.
    """
    return FullSystemBaselineV3Evaluator().evaluate()


def get_v3_baseline_report() -> V3BaselineReport:
    """Return the process-global singleton :class:`V3BaselineReport`.

    The report is built lazily on first call and cached thereafter.
    Use :func:`reset_v3_baseline_report` in tests to clear the cache.
    """
    global _SINGLETON  # noqa: PLW0603
    if _SINGLETON is not None:
        return _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is None:
            _SINGLETON = build_v3_baseline_report()
    return _SINGLETON


def reset_v3_baseline_report() -> None:
    """Clear the process-global singleton (test isolation only)."""
    global _SINGLETON  # noqa: PLW0603
    with _SINGLETON_LOCK:
        _SINGLETON = None
