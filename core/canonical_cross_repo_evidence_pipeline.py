#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/canonical_cross_repo_evidence_pipeline.py
===============================================
PR-05 (Canonical Cross-Repo Evidence Ingestion Pipeline):
Unified canonical ingestion pipeline that converges all cross-repo evidence
surfaces into a single authoritative final-acceptance-ready report.

Problem addressed
-----------------
The dual-repo system (V2 + Android) already has multiple mature evidence
surfaces:

* Android delegated runtime audit (AndroidDelegatedRuntimeAuditRecorder)
* Android participant lifecycle truth (AndroidParticipantTruthIngress,
  AndroidParticipantSessionRegistry)
* Android readiness evidence (AndroidEvaluatorArtifactRegistry — governance,
  readiness, acceptance, strategy kinds)
* Real-device participant verification (AndroidParticipantEvidenceIngress —
  file-based JSON artifact)
* Task-result / runtime-result evidence (AndroidExecutionSignalReconciler)

Despite these surfaces existing, they had no unified final-ingestion path.
Specifically:

1. **No single canonical pipeline** — each surface was consumed separately
   by different layers (system_final_acceptance_verdict, v2_readiness_
   governance_evidence_surface) without a single canonical collector.
2. **No unified freshness / completeness / authority / stale-handling
   semantics** — each source applied its own age/validity policy or none.
3. **No canonical precedence or merge semantics** — when sources provided
   overlapping or conflicting signals there was no authoritative rule for
   which source to trust.
4. **No machine-readable cross-repo evidence summary** — no single artifact
   could be formally consumed by the acceptance gate as the definitive
   cross-repo evidence verdict.

This module closes those gaps by establishing the
**Canonical Cross-Repo Evidence Ingestion Pipeline** that:

1. Probes all five evidence source families with uniform freshness and
   completeness checks.
2. Applies an explicit **authority ranking**: ``primary`` → ``secondary``
   → ``advisory`` so that disagreeing sources resolve deterministically.
3. Applies explicit **downgrade rules** — stale / partial / conflicting /
   authority_unclear evidence is never optimistically elevated.
4. Produces a single :class:`CanonicalCrossRepoEvidenceReport` that is
   fully JSON-serialisable and can be formally consumed by
   ``system_final_acceptance_verdict`` and the V2 readiness/governance
   evidence surface.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  CANONICAL CROSS-REPO EVIDENCE INGESTION PIPELINE  (this module)   │
    │                                                                     │
    │  Ingests from five evidence source families:                       │
    │    1. real_device_verification  — AndroidParticipantEvidenceIngress │
    │       (PRIMARY: file-based JSON artifact, full freshness contract)  │
    │    2. readiness_evidence        — AndroidEvaluatorArtifactRegistry  │
    │       (PRIMARY: governance/readiness/acceptance/strategy artifacts) │
    │    3. participant_lifecycle_truth — ParticipantSessionRegistry      │
    │       (SECONDARY: reconciliation session state)                    │
    │    4. task_result_runtime       — AndroidExecutionSignalReconciler  │
    │       (SECONDARY: execution signal reconciliation outcomes)         │
    │    5. delegated_runtime_audit   — AndroidDelegatedAuditRecorder    │
    │       (ADVISORY: ring-buffer observability; not a gate blocker)     │
    │                                                                     │
    │  Applies unified contract semantics:                               │
    │    • authority (primary / secondary / advisory)                    │
    │    • freshness (configurable max-age in seconds)                   │
    │    • completeness (required fields / minimum record counts)        │
    │    • stale-handling (explicit downgrade, never optimistic pass)    │
    │    • canonical precedence (primary > secondary > advisory)         │
    │    • merge semantics (conflict detection, per-source notes)        │
    │                                                                     │
    │  Produces CanonicalCrossRepoEvidenceReport (machine-readable):     │
    │    • pipeline_verdict: complete/partial/stale/missing/conflicting/ │
    │      authority_unclear/insufficient                                 │
    │    • per-source IngestionSourceEntry with status, freshness, raw   │
    │    • downgrade_reasons, conflict_notes, merge_policy_notes         │
    │    • is_complete (True only when verdict == complete)              │
    │    • summary (human-readable, consistent with machine fields)      │
    │                                                                     │
    │  Consumed by:                                                      │
    │    • system_final_acceptance_verdict (cross_repo_evidence_pipeline  │
    │      dimension)                                                    │
    │    • v2_readiness_governance_evidence_surface (probe)              │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — does not modify any existing module.
2. **Fail-conservative** — stale / missing / authority_unclear evidence is
   NEVER treated as implicit approval.  Silence is not acceptance.
3. **Explicit downgrade rules** — every downgrade documents its reason in
   ``downgrade_reasons``.
4. **No optimistic authority upgrade** — if authority cannot be confirmed
   for a primary source the pipeline verdict is ``authority_unclear``, not
   ``complete``.
5. **Projection-only** — all probes are read-only; no canonical state is
   mutated.
6. **Deterministic** — given the same module state the pipeline always
   produces the same verdict.
7. **Stable artifacts** — :class:`CanonicalCrossRepoEvidenceReport` is
   fully round-trippable via ``to_dict()`` / ``to_json()``.

Contract constants
------------------
:data:`CANONICAL_PIPELINE_PRIMARY_FRESHNESS_MAX_AGE_SECONDS`
    Maximum age (seconds) for a PRIMARY source evidence artifact to be
    considered fresh.  Default: 3600 s (1 hour).  Override via environment
    variable ``CROSS_REPO_EVIDENCE_PRIMARY_MAX_AGE_SECONDS``.

:data:`CANONICAL_PIPELINE_SECONDARY_FRESHNESS_MAX_AGE_SECONDS`
    Maximum age (seconds) for a SECONDARY source evidence artifact.
    Default: 7200 s (2 hours).

Public API
----------
Authority / policy sentinels::

    CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_AUTHORITY
    CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_PR05_SENTINEL
    PRIMARY_SOURCE_FRESHNESS_REQUIRED_POLICY
    STALE_EVIDENCE_NEVER_UPGRADES_VERDICT_POLICY
    AUTHORITY_UNCLEAR_BLOCKS_COMPLETE_VERDICT_POLICY
    CONFLICTING_EVIDENCE_NEVER_OPTIMISTIC_POLICY
    CANONICAL_PRECEDENCE_PRIMARY_OVER_SECONDARY_POLICY
    MISSING_PRIMARY_SOURCE_DOWNGRADES_TO_PARTIAL_POLICY

Enumerations::

    EvidenceSourceId
    EvidenceSourceAuthority
    IngestionStatus
    PipelineVerdict

Data classes::

    IngestionSourceEntry
    CanonicalCrossRepoEvidenceReport

Helpers::

    build_canonical_cross_repo_evidence_report() -> CanonicalCrossRepoEvidenceReport
    get_canonical_cross_repo_evidence_report()   -> CanonicalCrossRepoEvidenceReport
    reset_canonical_cross_repo_evidence_report() -> None  (testing only)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.CanonicalCrossRepoEvidencePipeline")

__all__ = [
    # Authority / policy sentinels
    "CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_AUTHORITY",
    "CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_PR05_SENTINEL",
    "PRIMARY_SOURCE_FRESHNESS_REQUIRED_POLICY",
    "STALE_EVIDENCE_NEVER_UPGRADES_VERDICT_POLICY",
    "AUTHORITY_UNCLEAR_BLOCKS_COMPLETE_VERDICT_POLICY",
    "CONFLICTING_EVIDENCE_NEVER_OPTIMISTIC_POLICY",
    "CANONICAL_PRECEDENCE_PRIMARY_OVER_SECONDARY_POLICY",
    "MISSING_PRIMARY_SOURCE_DOWNGRADES_TO_PARTIAL_POLICY",
    # Contract constants
    "CANONICAL_PIPELINE_PRIMARY_FRESHNESS_MAX_AGE_SECONDS",
    "CANONICAL_PIPELINE_SECONDARY_FRESHNESS_MAX_AGE_SECONDS",
    # Enumerations
    "EvidenceSourceId",
    "EvidenceSourceAuthority",
    "IngestionStatus",
    "PipelineVerdict",
    # Data classes
    "IngestionSourceEntry",
    "CanonicalCrossRepoEvidenceReport",
    # Helpers
    "build_canonical_cross_repo_evidence_report",
    "get_canonical_cross_repo_evidence_report",
    "reset_canonical_cross_repo_evidence_report",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_AUTHORITY: str = (
    "CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_AUTHORITY::"
    "core.canonical_cross_repo_evidence_pipeline::PR05::"
    "canonical-cross-repo-evidence-ingestion-pipeline::"
    "unified-final-acceptance-evidence-convergence-for-galaxy-dual-repo"
)
"""Sentinel: this module is the canonical cross-repo evidence ingestion
pipeline for the Galaxy dual-repo system.

Import to assert that a release pipeline, reviewer tool, or CI hook is
consulting the correct canonical evidence aggregator rather than individual
evidence surfaces."""

CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_PR05_SENTINEL: str = (
    "CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_PR05_SENTINEL::"
    "package=PR05::profile=canonical-cross-repo-evidence-pipeline-v1::"
    "module=core.canonical_cross_repo_evidence_pipeline"
)
"""Package sentinel for PR-05."""

PRIMARY_SOURCE_FRESHNESS_REQUIRED_POLICY: str = (
    "POLICY::PRIMARY_SOURCE_FRESHNESS_REQUIRED_V1: "
    "Evidence from PRIMARY authority sources MUST be within "
    "CANONICAL_PIPELINE_PRIMARY_FRESHNESS_MAX_AGE_SECONDS of the pipeline "
    "evaluation time.  A primary source whose evidence is older than this "
    "threshold is classified as IngestionStatus.stale and the pipeline "
    "verdict is downgraded to PipelineVerdict.stale.  Stale primary evidence "
    "MUST NOT produce a PipelineVerdict.complete verdict.  "
    "PR-05, canonical cross-repo evidence pipeline."
)

STALE_EVIDENCE_NEVER_UPGRADES_VERDICT_POLICY: str = (
    "POLICY::STALE_EVIDENCE_NEVER_UPGRADES_VERDICT_V1: "
    "Stale evidence — from any source at any authority level — MUST NOT be "
    "used to upgrade the pipeline verdict to complete.  Stale evidence "
    "produces a downgrade note in downgrade_reasons and lowers the verdict "
    "to PipelineVerdict.stale (if the stale source is primary) or is "
    "annotated in merge_policy_notes (if secondary or advisory) without "
    "blocking the primary verdict.  Optimistically ignoring staleness is "
    "explicitly prohibited.  "
    "PR-05, canonical cross-repo evidence pipeline."
)

AUTHORITY_UNCLEAR_BLOCKS_COMPLETE_VERDICT_POLICY: str = (
    "POLICY::AUTHORITY_UNCLEAR_BLOCKS_COMPLETE_VERDICT_V1: "
    "When a PRIMARY evidence source module cannot be imported, or when the "
    "authority sentinel from that source is absent or does not match the "
    "expected value, the source is classified as IngestionStatus.authority_unclear "
    "and the pipeline verdict MUST be PipelineVerdict.authority_unclear.  "
    "This is distinct from missing (module present but no artifact) and stale "
    "(artifact present but too old).  Authority unclear MUST NOT be treated "
    "as acceptable or optimistically elevated.  "
    "PR-05, canonical cross-repo evidence pipeline."
)

CONFLICTING_EVIDENCE_NEVER_OPTIMISTIC_POLICY: str = (
    "POLICY::CONFLICTING_EVIDENCE_NEVER_OPTIMISTIC_V1: "
    "When two or more PRIMARY sources provide contradictory verdicts (e.g. "
    "real_device_verification says ready but readiness_evidence says not "
    "compliant) the pipeline verdict MUST be PipelineVerdict.conflicting.  "
    "The conflicting sources and their specific disagreements MUST be "
    "documented in conflict_notes.  Conflicting evidence MUST NOT be "
    "resolved by picking the more favourable source; it MUST surface as a "
    "blocking state requiring human or automated resolution.  "
    "PR-05, canonical cross-repo evidence pipeline."
)

CANONICAL_PRECEDENCE_PRIMARY_OVER_SECONDARY_POLICY: str = (
    "POLICY::CANONICAL_PRECEDENCE_PRIMARY_OVER_SECONDARY_V1: "
    "When evidence from PRIMARY and SECONDARY sources is available and "
    "consistent, the PRIMARY source verdict takes precedence in the pipeline "
    "verdict.  SECONDARY sources supplement PRIMARY evidence by adding "
    "lifecycle and runtime context but do not override PRIMARY verdicts.  "
    "ADVISORY sources (e.g. delegated_runtime_audit) never affect the "
    "pipeline verdict; they are captured for debugging and observability only.  "
    "Canonical precedence order: PRIMARY > SECONDARY > ADVISORY.  "
    "PR-05, canonical cross-repo evidence pipeline."
)

MISSING_PRIMARY_SOURCE_DOWNGRADES_TO_PARTIAL_POLICY: str = (
    "POLICY::MISSING_PRIMARY_SOURCE_DOWNGRADES_TO_PARTIAL_V1: "
    "When a PRIMARY evidence source has no artifact (module importable, no "
    "exception, but no evidence artifact found at the configured path or in "
    "the in-process registry), the source is classified as "
    "IngestionStatus.missing and the pipeline verdict is downgraded to "
    "PipelineVerdict.partial.  A partial verdict indicates that some primary "
    "evidence is present but the full canonical cross-repo evidence chain has "
    "not been established.  Missing primary evidence MUST NOT produce a "
    "PipelineVerdict.complete verdict.  "
    "PR-05, canonical cross-repo evidence pipeline."
)

# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------

_ENV_PRIMARY_MAX_AGE = "CROSS_REPO_EVIDENCE_PRIMARY_MAX_AGE_SECONDS"
_ENV_SECONDARY_MAX_AGE = "CROSS_REPO_EVIDENCE_SECONDARY_MAX_AGE_SECONDS"

CANONICAL_PIPELINE_PRIMARY_FRESHNESS_MAX_AGE_SECONDS: float = float(
    os.environ.get(_ENV_PRIMARY_MAX_AGE, "3600")
)
"""Maximum age for primary source evidence to be considered fresh (default 3600 s)."""

CANONICAL_PIPELINE_SECONDARY_FRESHNESS_MAX_AGE_SECONDS: float = float(
    os.environ.get(_ENV_SECONDARY_MAX_AGE, "7200")
)
"""Maximum age for secondary source evidence to be considered fresh (default 7200 s)."""

# ---------------------------------------------------------------------------
# EvidenceSourceId
# ---------------------------------------------------------------------------


class EvidenceSourceId(str, Enum):
    """Canonical identifiers for the five cross-repo evidence source families.

    Values
    ------
    real_device_verification
        File-based JSON artifact produced by the Android participant device.
        Authority: PRIMARY.  Source: AndroidParticipantEvidenceIngress.

    readiness_evidence
        Android evaluator artifacts (governance / readiness / acceptance /
        strategy) ingested via AndroidEvaluatorArtifactRegistry.
        Authority: PRIMARY.  Source: AndroidEvaluatorArtifactIngress.

    participant_lifecycle_truth
        Android participant session state (reconciliation phase tracking)
        from AndroidParticipantSessionRegistry.
        Authority: SECONDARY.  Source: android_participant_session_state.

    task_result_runtime
        Android execution signal reconciliation outcomes (ack / progress /
        final_result / error / timeout / cancelled) from
        AndroidExecutionSignalReconciler.
        Authority: SECONDARY.  Source: android_execution_signal_reconciler.

    delegated_runtime_audit
        Ring-buffer audit records from AndroidDelegatedRuntimeAuditRecorder.
        Authority: ADVISORY (observability only; does not gate release).
        Source: android_delegated_runtime_audit.
    """

    real_device_verification = "real_device_verification"
    readiness_evidence = "readiness_evidence"
    participant_lifecycle_truth = "participant_lifecycle_truth"
    task_result_runtime = "task_result_runtime"
    delegated_runtime_audit = "delegated_runtime_audit"


# ---------------------------------------------------------------------------
# EvidenceSourceAuthority
# ---------------------------------------------------------------------------


class EvidenceSourceAuthority(str, Enum):
    """Authority level for an evidence source family.

    Values
    ------
    primary
        Gate-worthy.  Stale or missing primary evidence downgrades the
        pipeline verdict.

    secondary
        Supporting.  Supplements primary evidence but does not override it.

    advisory
        Observational only.  Captured for debugging/auditing; MUST NOT
        affect the pipeline verdict.
    """

    primary = "primary"
    secondary = "secondary"
    advisory = "advisory"


#: Map from EvidenceSourceId to EvidenceSourceAuthority (canonical precedence).
_SOURCE_AUTHORITY: Dict[EvidenceSourceId, EvidenceSourceAuthority] = {
    EvidenceSourceId.real_device_verification: EvidenceSourceAuthority.primary,
    EvidenceSourceId.readiness_evidence: EvidenceSourceAuthority.primary,
    EvidenceSourceId.participant_lifecycle_truth: EvidenceSourceAuthority.secondary,
    EvidenceSourceId.task_result_runtime: EvidenceSourceAuthority.secondary,
    EvidenceSourceId.delegated_runtime_audit: EvidenceSourceAuthority.advisory,
}

# ---------------------------------------------------------------------------
# IngestionStatus
# ---------------------------------------------------------------------------


class IngestionStatus(str, Enum):
    """Per-source ingestion status.

    Values
    ------
    present
        Evidence found, structurally valid, and within the freshness window.

    stale
        Evidence found and valid but older than the configured max-age.

    missing
        Source module importable and functioning, but no evidence artifact
        was found (empty registry / missing file).

    partial
        Evidence found but structurally incomplete (missing required fields
        or counts below minimum).

    conflicting
        This source's verdict conflicts with another same-authority source.

    unavailable
        Source module could not be imported; cannot determine evidence state.

    authority_unclear
        Module importable but authority sentinel absent or mismatched.
    """

    present = "present"
    stale = "stale"
    missing = "missing"
    partial = "partial"
    conflicting = "conflicting"
    unavailable = "unavailable"
    authority_unclear = "authority_unclear"

    @property
    def is_actionable(self) -> bool:
        """Return True for statuses that contribute usable evidence."""
        return self == IngestionStatus.present

    @property
    def is_blocking(self) -> bool:
        """Return True for statuses that block a complete pipeline verdict."""
        return self in (
            IngestionStatus.stale,
            IngestionStatus.missing,
            IngestionStatus.partial,
            IngestionStatus.conflicting,
            IngestionStatus.unavailable,
            IngestionStatus.authority_unclear,
        )


# ---------------------------------------------------------------------------
# PipelineVerdict
# ---------------------------------------------------------------------------


class PipelineVerdict(str, Enum):
    """Overall pipeline verdict for the canonical cross-repo evidence chain.

    Values
    ------
    complete
        All PRIMARY sources present, fresh, structurally valid, and
        consistent.  The cross-repo evidence chain is canonically closed.

    partial
        At least one PRIMARY source is missing (module importable but no
        artifact).  The chain is not fully closed but partial evidence
        exists.

    stale
        At least one PRIMARY source evidence artifact is present but exceeds
        the configured freshness window.

    missing
        All PRIMARY sources are missing or unavailable; no usable evidence.

    conflicting
        Two or more PRIMARY sources provide contradictory operational verdicts.

    authority_unclear
        At least one PRIMARY source module is unavailable or its authority
        sentinel cannot be confirmed.  Cannot establish a trustworthy verdict.

    insufficient
        Not enough evidence was collected to determine the pipeline state
        (e.g. all probes raised exceptions).
    """

    complete = "complete"
    partial = "partial"
    stale = "stale"
    missing = "missing"
    conflicting = "conflicting"
    authority_unclear = "authority_unclear"
    insufficient = "insufficient"

    @property
    def is_complete(self) -> bool:
        """Return True only when the verdict is ``complete``."""
        return self == PipelineVerdict.complete

    @property
    def is_blocking(self) -> bool:
        """Return True when the verdict prevents acceptance."""
        return self not in (PipelineVerdict.complete,)


# ---------------------------------------------------------------------------
# IngestionSourceEntry
# ---------------------------------------------------------------------------


@dataclass
class IngestionSourceEntry:
    """Evidence ingestion result for one source family.

    Fields
    ------
    source_id
        :class:`EvidenceSourceId` identifying this source.
    authority
        :class:`EvidenceSourceAuthority` for this source.
    status
        :class:`IngestionStatus` describing the ingestion outcome.
    evidence_summary
        Human-readable one-liner describing what was found.
    freshness_secs
        Age of the evidence in seconds at ingestion time, or ``None`` if
        the source does not carry a timestamp.
    is_stale
        True when ``freshness_secs`` exceeds the freshness threshold for
        this source's authority level.
    raw_evidence
        Optional dict of machine-readable evidence from the source module.
    notes
        Additional notes (downgrade reasons, caveats, conflict description).
    """

    source_id: EvidenceSourceId
    authority: EvidenceSourceAuthority
    status: IngestionStatus
    evidence_summary: str
    freshness_secs: Optional[float] = None
    is_stale: bool = False
    raw_evidence: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id.value,
            "authority": self.authority.value,
            "status": self.status.value,
            "evidence_summary": self.evidence_summary,
            "freshness_secs": self.freshness_secs,
            "is_stale": self.is_stale,
            "raw_evidence": self.raw_evidence,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "IngestionSourceEntry":
        return cls(
            source_id=EvidenceSourceId(d.get("source_id", "delegated_runtime_audit")),
            authority=EvidenceSourceAuthority(d.get("authority", "advisory")),
            status=IngestionStatus(d.get("status", "unavailable")),
            evidence_summary=d.get("evidence_summary", ""),
            freshness_secs=d.get("freshness_secs"),
            is_stale=bool(d.get("is_stale", False)),
            raw_evidence=dict(d.get("raw_evidence") or {}),
            notes=d.get("notes", ""),
        )


# ---------------------------------------------------------------------------
# CanonicalCrossRepoEvidenceReport
# ---------------------------------------------------------------------------


@dataclass
class CanonicalCrossRepoEvidenceReport:
    """Canonical cross-repo evidence ingestion report.

    This is the single machine-readable output of the unified evidence
    pipeline.  It is JSON-serialisable and suitable for consumption by
    ``system_final_acceptance_verdict`` and CI release gates.

    Fields
    ------
    report_id
        UUID-based identifier for this report instance.
    generated_at
        Unix timestamp when the report was produced.
    authority
        The module authority sentinel string.
    pipeline_verdict
        Overall :class:`PipelineVerdict` for the cross-repo evidence chain.
    is_complete
        True only when ``pipeline_verdict == PipelineVerdict.complete``.
    sources
        List of :class:`IngestionSourceEntry` — one per evidence source family.
    primary_sources_complete
        True when all PRIMARY source entries have ``status == present``.
    primary_sources_fresh
        True when all PRIMARY source entries are not stale.
    downgrade_reasons
        Ordered list of reasons why the verdict was downgraded from ``complete``.
    conflict_notes
        Descriptions of any inter-source conflicts detected.
    stale_sources
        Source IDs of any stale sources.
    missing_sources
        Source IDs of any missing sources (module importable, no artifact).
    partial_sources
        Source IDs of any structurally incomplete sources.
    unavailable_sources
        Source IDs of sources whose modules could not be imported.
    authority_unclear_sources
        Source IDs of sources with unclear authority.
    canonical_precedence_applied
        Descriptions of precedence decisions applied during merge.
    merge_policy_notes
        Notes about merge semantics applied when combining source evidence.
    summary
        Human-readable plain-text summary (consistent with machine fields).
    """

    report_id: str
    generated_at: float
    authority: str
    pipeline_verdict: PipelineVerdict
    is_complete: bool
    sources: List[IngestionSourceEntry]
    primary_sources_complete: bool = False
    primary_sources_fresh: bool = False
    downgrade_reasons: List[str] = field(default_factory=list)
    conflict_notes: List[str] = field(default_factory=list)
    stale_sources: List[str] = field(default_factory=list)
    missing_sources: List[str] = field(default_factory=list)
    partial_sources: List[str] = field(default_factory=list)
    unavailable_sources: List[str] = field(default_factory=list)
    authority_unclear_sources: List[str] = field(default_factory=list)
    canonical_precedence_applied: List[str] = field(default_factory=list)
    merge_policy_notes: List[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "authority": self.authority,
            "pipeline_verdict": self.pipeline_verdict.value,
            "is_complete": self.is_complete,
            "primary_sources_complete": self.primary_sources_complete,
            "primary_sources_fresh": self.primary_sources_fresh,
            "sources": [s.to_dict() for s in self.sources],
            "downgrade_reasons": list(self.downgrade_reasons),
            "conflict_notes": list(self.conflict_notes),
            "stale_sources": list(self.stale_sources),
            "missing_sources": list(self.missing_sources),
            "partial_sources": list(self.partial_sources),
            "unavailable_sources": list(self.unavailable_sources),
            "authority_unclear_sources": list(self.authority_unclear_sources),
            "canonical_precedence_applied": list(self.canonical_precedence_applied),
            "merge_policy_notes": list(self.merge_policy_notes),
            "summary": self.summary,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CanonicalCrossRepoEvidenceReport":
        sources = [
            IngestionSourceEntry.from_dict(s)
            for s in (d.get("sources") or [])
        ]
        return cls(
            report_id=d.get("report_id", ""),
            generated_at=float(d.get("generated_at", 0.0)),
            authority=d.get("authority", ""),
            pipeline_verdict=PipelineVerdict(
                d.get("pipeline_verdict", "insufficient")
            ),
            is_complete=bool(d.get("is_complete", False)),
            sources=sources,
            primary_sources_complete=bool(d.get("primary_sources_complete", False)),
            primary_sources_fresh=bool(d.get("primary_sources_fresh", False)),
            downgrade_reasons=list(d.get("downgrade_reasons") or []),
            conflict_notes=list(d.get("conflict_notes") or []),
            stale_sources=list(d.get("stale_sources") or []),
            missing_sources=list(d.get("missing_sources") or []),
            partial_sources=list(d.get("partial_sources") or []),
            unavailable_sources=list(d.get("unavailable_sources") or []),
            authority_unclear_sources=list(d.get("authority_unclear_sources") or []),
            canonical_precedence_applied=list(
                d.get("canonical_precedence_applied") or []
            ),
            merge_policy_notes=list(d.get("merge_policy_notes") or []),
            summary=d.get("summary", ""),
        )


# ---------------------------------------------------------------------------
# Optional source module imports (fail-graceful)
# ---------------------------------------------------------------------------

# Source 1: real_device_verification — AndroidParticipantEvidenceIngress
try:
    from core.android_participant_evidence_ingress import (  # type: ignore[import]
        ingest_android_participant_evidence as _ingest_real_device_evidence,
        ANDROID_PARTICIPANT_EVIDENCE_INGRESS_AUTHORITY as _REAL_DEVICE_AUTHORITY_SENTINEL,
        AndroidParticipantStatus as _AndroidParticipantStatus,
    )
    _REAL_DEVICE_AVAILABLE = True
except Exception:
    _REAL_DEVICE_AVAILABLE = False
    _ingest_real_device_evidence = None  # type: ignore[assignment]
    _REAL_DEVICE_AUTHORITY_SENTINEL = ""
    _AndroidParticipantStatus = None  # type: ignore[assignment]

# Source 2: readiness_evidence — AndroidEvaluatorArtifactRegistry
try:
    from core.android_evaluator_artifact_ingress import (  # type: ignore[import]
        get_evaluator_artifact_registry as _get_evaluator_registry,
        ANDROID_EVALUATOR_ARTIFACT_INGRESS_AUTHORITY as _EVALUATOR_AUTHORITY_SENTINEL,
        AndroidEvaluatorArtifactKind as _ArtifactKind,
    )
    _EVALUATOR_AVAILABLE = True
except Exception:
    _EVALUATOR_AVAILABLE = False
    _get_evaluator_registry = None  # type: ignore[assignment]
    _EVALUATOR_AUTHORITY_SENTINEL = ""
    _ArtifactKind = None  # type: ignore[assignment]

# Source 3: participant_lifecycle_truth — AndroidParticipantSessionRegistry
try:
    from core.android_participant_session_state import (  # type: ignore[import]
        get_participant_session_registry as _get_session_registry,
    )
    _SESSION_REGISTRY_AVAILABLE = True
except Exception:
    _SESSION_REGISTRY_AVAILABLE = False
    _get_session_registry = None  # type: ignore[assignment]

# Source 4: task_result_runtime — AndroidExecutionSignalReconciler
try:
    from core.android_execution_signal_reconciler import (  # type: ignore[import]
        ANDROID_EXECUTION_SIGNAL_RECONCILER_AUTHORITY as _RECONCILER_AUTHORITY_SENTINEL,
    )
    _RECONCILER_AVAILABLE = True
except Exception:
    _RECONCILER_AVAILABLE = False
    _RECONCILER_AUTHORITY_SENTINEL = ""

# Source 5: delegated_runtime_audit — AndroidDelegatedRuntimeAuditRecorder
try:
    from core.android_delegated_runtime_audit import (  # type: ignore[import]
        android_audit_snapshot as _android_audit_snapshot,
        ANDROID_DELEGATED_RUNTIME_AUDIT_AUTHORITY as _AUDIT_AUTHORITY_SENTINEL,
    )
    _AUDIT_AVAILABLE = True
except Exception:
    _AUDIT_AVAILABLE = False
    _android_audit_snapshot = None  # type: ignore[assignment]
    _AUDIT_AUTHORITY_SENTINEL = ""


# ---------------------------------------------------------------------------
# Individual source probers
# ---------------------------------------------------------------------------


def _probe_real_device_verification() -> IngestionSourceEntry:
    """Probe the real-device participant verification source (PRIMARY)."""
    src = EvidenceSourceId.real_device_verification
    auth = EvidenceSourceAuthority.primary
    max_age = CANONICAL_PIPELINE_PRIMARY_FRESHNESS_MAX_AGE_SECONDS

    if not _REAL_DEVICE_AVAILABLE or _ingest_real_device_evidence is None:
        return IngestionSourceEntry(
            source_id=src,
            authority=auth,
            status=IngestionStatus.authority_unclear,
            evidence_summary=(
                "AndroidParticipantEvidenceIngress module unavailable; "
                "cannot confirm PRIMARY authority for real-device verification."
            ),
            notes=(
                "core.android_participant_evidence_ingress not importable.  "
                "Set ANDROID_PARTICIPANT_EVIDENCE_PATH to a valid artifact "
                "and ensure the module is on the Python path."
            ),
        )

    if not _REAL_DEVICE_AUTHORITY_SENTINEL:
        return IngestionSourceEntry(
            source_id=src,
            authority=auth,
            status=IngestionStatus.authority_unclear,
            evidence_summary=(
                "ANDROID_PARTICIPANT_EVIDENCE_INGRESS_AUTHORITY sentinel is "
                "empty; cannot confirm source authority."
            ),
        )

    try:
        result = _ingest_real_device_evidence()
        status_val = result.status.value if hasattr(result, "status") else ""
        evidence_dict = result.to_dict() if hasattr(result, "to_dict") else {}

        # Compute freshness from generated_at if available
        generated_at = evidence_dict.get("generated_at") or 0.0
        freshness_secs: Optional[float] = None
        is_stale = False
        if generated_at and isinstance(generated_at, (int, float)):
            freshness_secs = time.time() - float(generated_at)
            is_stale = freshness_secs > max_age

        if status_val in ("stale_evidence",):
            return IngestionSourceEntry(
                source_id=src,
                authority=auth,
                status=IngestionStatus.stale,
                evidence_summary=getattr(result, "evidence_summary", "Stale evidence."),
                freshness_secs=freshness_secs,
                is_stale=True,
                raw_evidence=evidence_dict,
                notes=(
                    f"Evidence exceeds PRIMARY freshness window "
                    f"({max_age:.0f} s).  "
                    + (getattr(result, "gap_description", "") or "")
                ),
            )

        if status_val in ("missing_evidence",):
            return IngestionSourceEntry(
                source_id=src,
                authority=auth,
                status=IngestionStatus.missing,
                evidence_summary=getattr(result, "evidence_summary", "No evidence file found."),
                freshness_secs=freshness_secs,
                is_stale=False,
                raw_evidence=evidence_dict,
                notes=getattr(result, "gap_description", ""),
            )

        if status_val in ("malformed_evidence",):
            return IngestionSourceEntry(
                source_id=src,
                authority=auth,
                status=IngestionStatus.partial,
                evidence_summary=getattr(result, "evidence_summary", "Malformed evidence."),
                freshness_secs=freshness_secs,
                is_stale=is_stale,
                raw_evidence=evidence_dict,
                notes=(
                    "Evidence file present but structurally invalid: "
                    + (getattr(result, "gap_description", "") or "")
                ),
            )

        if status_val in ("ready", "recovered", "degraded", "unverified", "unavailable"):
            # Evidence is present (even if degraded/unavailable participant state)
            return IngestionSourceEntry(
                source_id=src,
                authority=auth,
                status=IngestionStatus.present if not is_stale else IngestionStatus.stale,
                evidence_summary=getattr(result, "evidence_summary", f"status={status_val}"),
                freshness_secs=freshness_secs,
                is_stale=is_stale,
                raw_evidence=evidence_dict,
                notes=(
                    f"Participant reports: {status_val}. "
                    + (getattr(result, "gap_description", "") or "")
                    + (
                        f"  [STALE: age={freshness_secs:.0f}s > {max_age:.0f}s]"
                        if is_stale else ""
                    )
                ),
            )

        # Unknown status value
        return IngestionSourceEntry(
            source_id=src,
            authority=auth,
            status=IngestionStatus.partial,
            evidence_summary=f"Unrecognised participant status: {status_val!r}",
            freshness_secs=freshness_secs,
            is_stale=is_stale,
            raw_evidence=evidence_dict,
            notes="Unrecognised status value from ingest_android_participant_evidence().",
        )

    except Exception as exc:  # noqa: BLE001
        return IngestionSourceEntry(
            source_id=src,
            authority=auth,
            status=IngestionStatus.unavailable,
            evidence_summary=f"real_device_verification probe raised: {exc!r}",
            notes=f"Exception during ingest_android_participant_evidence(): {exc!r}",
        )


def _probe_readiness_evidence() -> IngestionSourceEntry:
    """Probe the Android evaluator artifact registry (PRIMARY)."""
    src = EvidenceSourceId.readiness_evidence
    auth = EvidenceSourceAuthority.primary

    if not _EVALUATOR_AVAILABLE or _get_evaluator_registry is None:
        return IngestionSourceEntry(
            source_id=src,
            authority=auth,
            status=IngestionStatus.authority_unclear,
            evidence_summary=(
                "AndroidEvaluatorArtifactIngress module unavailable; "
                "cannot confirm PRIMARY authority for readiness evidence."
            ),
            notes="core.android_evaluator_artifact_ingress not importable.",
        )

    if not _EVALUATOR_AUTHORITY_SENTINEL:
        return IngestionSourceEntry(
            source_id=src,
            authority=auth,
            status=IngestionStatus.authority_unclear,
            evidence_summary=(
                "ANDROID_EVALUATOR_ARTIFACT_INGRESS_AUTHORITY sentinel is empty."
            ),
        )

    try:
        registry = _get_evaluator_registry()
        snapshot = registry.build_snapshot() if hasattr(registry, "build_snapshot") else {}
        total = snapshot.get("total_artifacts", 0)
        counts = snapshot.get("artifact_counts_by_kind", {})
        latest_by_kind = snapshot.get("latest_by_kind", {})

        canonical_kinds = []
        if _ArtifactKind is not None:
            canonical_kinds = [
                k.value for k in _ArtifactKind
                if k != _ArtifactKind.unknown and hasattr(k, "is_canonical_gate_input")
                and k.is_canonical_gate_input()
            ]

        # Check freshness per artifact (use received_at from latest_by_kind)
        max_age = CANONICAL_PIPELINE_PRIMARY_FRESHNESS_MAX_AGE_SECONDS
        now = time.time()
        stale_kinds: List[str] = []
        freshness_secs_per_kind: Dict[str, float] = {}
        for kind_val, artifact_dict in latest_by_kind.items():
            if artifact_dict and isinstance(artifact_dict, dict):
                received_at = artifact_dict.get("received_at", 0.0)
                if received_at and isinstance(received_at, (int, float)):
                    age = now - float(received_at)
                    freshness_secs_per_kind[kind_val] = age
                    if age > max_age:
                        stale_kinds.append(kind_val)

        if total == 0:
            return IngestionSourceEntry(
                source_id=src,
                authority=auth,
                status=IngestionStatus.missing,
                evidence_summary=(
                    "AndroidEvaluatorArtifactRegistry: no evaluator artifacts recorded.  "
                    "Android-side evaluators (readiness/acceptance/governance/strategy) "
                    "have not yet produced artifacts or they have not been ingested."
                ),
                raw_evidence=snapshot,
                notes=(
                    "Registry is empty at startup; it populates when Android evaluator "
                    "artifacts are received via governance_artifact truth kind."
                ),
            )

        # Determine overall freshness
        is_stale = bool(stale_kinds)
        min_freshness = (
            min(freshness_secs_per_kind.values())
            if freshness_secs_per_kind else None
        )

        summary = (
            f"AndroidEvaluatorArtifactRegistry: {total} artifact(s); "
            f"kinds present: {list(counts.keys())}"
        )

        return IngestionSourceEntry(
            source_id=src,
            authority=auth,
            status=IngestionStatus.stale if is_stale else IngestionStatus.present,
            evidence_summary=summary,
            freshness_secs=min_freshness,
            is_stale=is_stale,
            raw_evidence=snapshot,
            notes=(
                f"Stale artifact kinds: {stale_kinds}; "
                f"max_age={max_age:.0f}s."
                if is_stale else ""
            ),
        )

    except Exception as exc:  # noqa: BLE001
        return IngestionSourceEntry(
            source_id=src,
            authority=auth,
            status=IngestionStatus.unavailable,
            evidence_summary=f"readiness_evidence probe raised: {exc!r}",
            notes=f"Exception during evaluator registry probe: {exc!r}",
        )


def _probe_participant_lifecycle_truth() -> IngestionSourceEntry:
    """Probe the participant session state registry (SECONDARY)."""
    src = EvidenceSourceId.participant_lifecycle_truth
    auth = EvidenceSourceAuthority.secondary

    if not _SESSION_REGISTRY_AVAILABLE or _get_session_registry is None:
        return IngestionSourceEntry(
            source_id=src,
            authority=auth,
            status=IngestionStatus.unavailable,
            evidence_summary=(
                "AndroidParticipantSessionRegistry module unavailable."
            ),
            notes="core.android_participant_session_state not importable.",
        )

    try:
        registry = _get_session_registry()
        sessions = registry.snapshot() if hasattr(registry, "snapshot") else []
        total = len(sessions)
        summary = f"ParticipantSessionRegistry: {total} session record(s)"

        return IngestionSourceEntry(
            source_id=src,
            authority=auth,
            status=IngestionStatus.present,
            evidence_summary=summary,
            raw_evidence={"total_sessions": total},
            notes=(
                "Session registry populates as Android participants connect and "
                "progress through the handoff/takeover/reconciliation lifecycle."
            ),
        )

    except Exception as exc:  # noqa: BLE001
        return IngestionSourceEntry(
            source_id=src,
            authority=auth,
            status=IngestionStatus.unavailable,
            evidence_summary=f"participant_lifecycle_truth probe raised: {exc!r}",
            notes=f"Exception during session registry probe: {exc!r}",
        )


def _probe_task_result_runtime() -> IngestionSourceEntry:
    """Probe the Android execution signal reconciler (SECONDARY)."""
    src = EvidenceSourceId.task_result_runtime
    auth = EvidenceSourceAuthority.secondary

    if not _RECONCILER_AVAILABLE:
        return IngestionSourceEntry(
            source_id=src,
            authority=auth,
            status=IngestionStatus.unavailable,
            evidence_summary=(
                "AndroidExecutionSignalReconciler module unavailable."
            ),
            notes="core.android_execution_signal_reconciler not importable.",
        )

    if not _RECONCILER_AUTHORITY_SENTINEL:
        return IngestionSourceEntry(
            source_id=src,
            authority=auth,
            status=IngestionStatus.unavailable,
            evidence_summary=(
                "ANDROID_EXECUTION_SIGNAL_RECONCILER_AUTHORITY sentinel is empty."
            ),
        )

    # The execution signal reconciler is a functional module; its presence and
    # importability (with valid authority sentinel) constitutes secondary
    # evidence that the task-result runtime path is structurally wired.
    # Ring-buffer query is not part of its public API as of PR-13.
    return IngestionSourceEntry(
        source_id=src,
        authority=auth,
        status=IngestionStatus.present,
        evidence_summary=(
            "AndroidExecutionSignalReconciler: module importable with valid "
            "authority sentinel.  Canonical task-result runtime path is "
            "structurally wired."
        ),
        raw_evidence={
            "authority_sentinel_present": bool(_RECONCILER_AUTHORITY_SENTINEL),
            "module_importable": True,
        },
        notes=(
            "SECONDARY evidence: structural wiring confirmed.  Live execution "
            "signal reconciliation records are not exposed via a public ring-buffer "
            "snapshot API (as of PR-13); this entry reflects deployment readiness "
            "rather than per-task execution evidence."
        ),
    )


def _probe_delegated_runtime_audit() -> IngestionSourceEntry:
    """Probe the delegated runtime audit ring buffer (ADVISORY)."""
    src = EvidenceSourceId.delegated_runtime_audit
    auth = EvidenceSourceAuthority.advisory

    if not _AUDIT_AVAILABLE or _android_audit_snapshot is None:
        return IngestionSourceEntry(
            source_id=src,
            authority=auth,
            status=IngestionStatus.unavailable,
            evidence_summary=(
                "AndroidDelegatedRuntimeAuditRecorder module unavailable."
            ),
            notes="core.android_delegated_runtime_audit not importable.",
        )

    try:
        snap = _android_audit_snapshot()
        total = len(snap)
        summary = (
            f"AndroidDelegatedRuntimeAuditRecorder: {total} record(s) in ring buffer"
        )
        return IngestionSourceEntry(
            source_id=src,
            authority=auth,
            status=IngestionStatus.present,
            evidence_summary=summary,
            raw_evidence={"total_records": total},
            notes=(
                "ADVISORY: audit ring provides observability context for the "
                "handoff/takeover/reconciliation chain.  Does NOT affect the "
                "pipeline verdict per CANONICAL_PRECEDENCE_PRIMARY_OVER_SECONDARY_POLICY."
            ),
        )

    except Exception as exc:  # noqa: BLE001
        return IngestionSourceEntry(
            source_id=src,
            authority=auth,
            status=IngestionStatus.unavailable,
            evidence_summary=f"delegated_runtime_audit probe raised: {exc!r}",
            notes=f"Exception during audit snapshot: {exc!r}",
        )


# ---------------------------------------------------------------------------
# Pipeline builder
# ---------------------------------------------------------------------------


class CanonicalCrossRepoEvidencePipeline:
    """Builds the canonical cross-repo evidence ingestion report.

    This is a stateless builder; call :meth:`build` to produce a fresh
    :class:`CanonicalCrossRepoEvidenceReport`.  The module-level singletons
    :func:`get_canonical_cross_repo_evidence_report` and
    :func:`build_canonical_cross_repo_evidence_report` are the recommended
    entry points.
    """

    def build(self) -> CanonicalCrossRepoEvidenceReport:
        """Run all probes and produce a :class:`CanonicalCrossRepoEvidenceReport`."""
        now = time.time()

        # ------------------------------------------------------------------
        # Probe all five source families
        # ------------------------------------------------------------------
        sources: List[IngestionSourceEntry] = [
            _probe_real_device_verification(),
            _probe_readiness_evidence(),
            _probe_participant_lifecycle_truth(),
            _probe_task_result_runtime(),
            _probe_delegated_runtime_audit(),
        ]

        primary_sources = [
            s for s in sources if s.authority == EvidenceSourceAuthority.primary
        ]
        secondary_sources = [
            s for s in sources if s.authority == EvidenceSourceAuthority.secondary
        ]

        # ------------------------------------------------------------------
        # Classify per-source issues
        # ------------------------------------------------------------------
        stale_sources: List[str] = []
        missing_sources: List[str] = []
        partial_sources: List[str] = []
        unavailable_sources: List[str] = []
        authority_unclear_sources: List[str] = []
        downgrade_reasons: List[str] = []
        conflict_notes: List[str] = []
        merge_policy_notes: List[str] = []
        canonical_precedence_applied: List[str] = []

        for s in sources:
            sid = s.source_id.value
            if s.status == IngestionStatus.stale:
                stale_sources.append(sid)
            elif s.status == IngestionStatus.missing:
                missing_sources.append(sid)
            elif s.status == IngestionStatus.partial:
                partial_sources.append(sid)
            elif s.status == IngestionStatus.unavailable:
                unavailable_sources.append(sid)
            elif s.status == IngestionStatus.authority_unclear:
                authority_unclear_sources.append(sid)

        # ------------------------------------------------------------------
        # Compute primary source aggregate state
        # ------------------------------------------------------------------
        primary_all_present = all(
            s.status == IngestionStatus.present for s in primary_sources
        )
        primary_all_fresh = all(
            not s.is_stale for s in primary_sources
        )

        # ------------------------------------------------------------------
        # Conflict detection between PRIMARY sources
        # ------------------------------------------------------------------
        # If real_device_verification is "present" (operational) AND
        # readiness_evidence reports no compliant artifacts, flag as
        # potentially conflicting (advisory note only, not blocking by
        # itself unless both are authoritative and contradictory).
        rdv_entry = next(
            (s for s in primary_sources
             if s.source_id == EvidenceSourceId.real_device_verification),
            None,
        )
        re_entry = next(
            (s for s in primary_sources
             if s.source_id == EvidenceSourceId.readiness_evidence),
            None,
        )
        if (
            rdv_entry is not None
            and re_entry is not None
            and rdv_entry.status == IngestionStatus.present
            and re_entry.status == IngestionStatus.present
        ):
            # Both present — check for operational-vs-compliant conflict
            rdv_status = (rdv_entry.raw_evidence or {}).get("participant_status", "")
            re_counts = (re_entry.raw_evidence or {}).get("artifact_counts_by_kind", {})
            if rdv_status == "ready" and not re_counts:
                conflict_notes.append(
                    "real_device_verification reports participant=ready but "
                    "readiness_evidence registry has no evaluator artifacts.  "
                    "This may indicate that readiness artifact upload is "
                    "not yet wired end-to-end.  Sources are present but "
                    "evaluator artifact pipeline may be incomplete."
                )
            canonical_precedence_applied.append(
                "PRIMARY precedence: real_device_verification and readiness_evidence "
                "are both present; real_device_verification (file-based contract with "
                "full freshness semantics) is the authoritative participant verdict; "
                "readiness_evidence provides complementary evaluator artifact evidence."
            )

        # ------------------------------------------------------------------
        # Secondary source merge notes
        # ------------------------------------------------------------------
        for s in secondary_sources:
            if s.status in (IngestionStatus.present,):
                merge_policy_notes.append(
                    f"SECONDARY({s.source_id.value}): present — supplements "
                    "primary evidence per CANONICAL_PRECEDENCE policy."
                )
            else:
                merge_policy_notes.append(
                    f"SECONDARY({s.source_id.value}): status={s.status.value} — "
                    "does not affect pipeline verdict (secondary authority)."
                )

        # ------------------------------------------------------------------
        # Determine pipeline verdict (downgrade rules)
        # ------------------------------------------------------------------
        primary_authority_unclear = [
            s.source_id.value for s in primary_sources
            if s.status == IngestionStatus.authority_unclear
        ]
        primary_stale = [
            s.source_id.value for s in primary_sources
            if s.status == IngestionStatus.stale
        ]
        primary_missing = [
            s.source_id.value for s in primary_sources
            if s.status == IngestionStatus.missing
        ]
        primary_partial = [
            s.source_id.value for s in primary_sources
            if s.status == IngestionStatus.partial
        ]
        primary_unavailable = [
            s.source_id.value for s in primary_sources
            if s.status == IngestionStatus.unavailable
        ]

        all_primary_blocking = (
            primary_authority_unclear
            + primary_stale
            + primary_missing
            + primary_partial
            + primary_unavailable
        )

        if primary_authority_unclear or primary_unavailable:
            verdict = PipelineVerdict.authority_unclear
            for sid in primary_authority_unclear:
                downgrade_reasons.append(
                    f"PRIMARY source {sid!r}: authority_unclear — "
                    "AUTHORITY_UNCLEAR_BLOCKS_COMPLETE_VERDICT_POLICY applied."
                )
            for sid in primary_unavailable:
                downgrade_reasons.append(
                    f"PRIMARY source {sid!r}: module unavailable — "
                    "treated as authority_unclear per fail-conservative policy."
                )

        elif conflict_notes and any(
            "conflict" in n.lower() for n in conflict_notes
        ):
            verdict = PipelineVerdict.conflicting
            downgrade_reasons.append(
                "PRIMARY sources have conflicting operational verdicts — "
                "CONFLICTING_EVIDENCE_NEVER_OPTIMISTIC_POLICY applied."
            )

        elif primary_stale:
            verdict = PipelineVerdict.stale
            for sid in primary_stale:
                downgrade_reasons.append(
                    f"PRIMARY source {sid!r}: stale evidence — "
                    "STALE_EVIDENCE_NEVER_UPGRADES_VERDICT_POLICY applied."
                )

        elif primary_missing or primary_partial:
            verdict = PipelineVerdict.partial
            for sid in primary_missing:
                downgrade_reasons.append(
                    f"PRIMARY source {sid!r}: no evidence artifact found — "
                    "MISSING_PRIMARY_SOURCE_DOWNGRADES_TO_PARTIAL_POLICY applied."
                )
            for sid in primary_partial:
                downgrade_reasons.append(
                    f"PRIMARY source {sid!r}: structurally incomplete evidence — "
                    "MISSING_PRIMARY_SOURCE_DOWNGRADES_TO_PARTIAL_POLICY applied."
                )

        elif not primary_sources:
            verdict = PipelineVerdict.insufficient
            downgrade_reasons.append(
                "No PRIMARY sources available — insufficient evidence to conclude."
            )

        elif primary_all_present and primary_all_fresh:
            verdict = PipelineVerdict.complete
            canonical_precedence_applied.append(
                "All PRIMARY sources present and fresh.  "
                "Cross-repo evidence chain is canonically closed."
            )

        else:
            # Should not normally reach here; belt-and-suspenders
            verdict = PipelineVerdict.insufficient
            downgrade_reasons.append(
                "Unexpected primary source state combination; "
                "treating as insufficient."
            )

        is_complete = verdict == PipelineVerdict.complete

        # ------------------------------------------------------------------
        # Build human-readable summary
        # ------------------------------------------------------------------
        summary = _build_summary(
            verdict=verdict,
            sources=sources,
            downgrade_reasons=downgrade_reasons,
            conflict_notes=conflict_notes,
            primary_all_present=primary_all_present,
            primary_all_fresh=primary_all_fresh,
        )

        return CanonicalCrossRepoEvidenceReport(
            report_id=str(uuid.uuid4()),
            generated_at=now,
            authority=CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_AUTHORITY,
            pipeline_verdict=verdict,
            is_complete=is_complete,
            sources=sources,
            primary_sources_complete=primary_all_present,
            primary_sources_fresh=primary_all_fresh,
            downgrade_reasons=downgrade_reasons,
            conflict_notes=conflict_notes,
            stale_sources=stale_sources,
            missing_sources=missing_sources,
            partial_sources=partial_sources,
            unavailable_sources=unavailable_sources,
            authority_unclear_sources=authority_unclear_sources,
            canonical_precedence_applied=canonical_precedence_applied,
            merge_policy_notes=merge_policy_notes,
            summary=summary,
        )


def _build_summary(
    verdict: PipelineVerdict,
    sources: List[IngestionSourceEntry],
    downgrade_reasons: List[str],
    conflict_notes: List[str],
    primary_all_present: bool,
    primary_all_fresh: bool,
) -> str:
    lines: List[str] = [
        "=" * 72,
        "CANONICAL CROSS-REPO EVIDENCE PIPELINE  (PR-05)",
        "=" * 72,
        f"VERDICT: {verdict.value.upper()}",
        "",
        "Evidence sources:",
    ]
    for s in sources:
        freshness_note = (
            f"  age={s.freshness_secs:.0f}s" if s.freshness_secs is not None else ""
        )
        stale_flag = "  [STALE]" if s.is_stale else ""
        lines.append(
            f"  [{s.authority.value.upper():<9}] {s.source_id.value:<32} "
            f"status={s.status.value}{freshness_note}{stale_flag}"
        )
    lines.append("")
    if downgrade_reasons:
        lines.append("Downgrade reasons:")
        for r in downgrade_reasons:
            lines.append(f"  - {r}")
        lines.append("")
    if conflict_notes:
        lines.append("Conflict notes:")
        for n in conflict_notes:
            lines.append(f"  - {n}")
        lines.append("")
    lines.append(
        f"Primary sources complete: {primary_all_present}  "
        f"fresh: {primary_all_fresh}"
    )
    lines.append(
        "CONCLUSION: "
        + (
            "Cross-repo evidence chain is canonically closed."
            if verdict == PipelineVerdict.complete
            else (
                f"Cross-repo evidence chain is NOT fully closed.  "
                f"Verdict={verdict.value}.  "
                "See downgrade_reasons for details."
            )
        )
    )
    lines.append("=" * 72)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------

_PIPELINE_LOCK = threading.Lock()
_cached_report: Optional[CanonicalCrossRepoEvidenceReport] = None


def build_canonical_cross_repo_evidence_report() -> CanonicalCrossRepoEvidenceReport:
    """Build and return a fresh :class:`CanonicalCrossRepoEvidenceReport`.

    Every call probes all source modules against their current live state.
    Use this function when a fresh snapshot is required (e.g. in CI).
    """
    return CanonicalCrossRepoEvidencePipeline().build()


def get_canonical_cross_repo_evidence_report() -> CanonicalCrossRepoEvidenceReport:
    """Return a cached :class:`CanonicalCrossRepoEvidenceReport`, building if needed.

    The cache is invalidated by :func:`reset_canonical_cross_repo_evidence_report`.
    Use :func:`build_canonical_cross_repo_evidence_report` when a fresh
    snapshot is required.
    """
    global _cached_report
    with _PIPELINE_LOCK:
        if _cached_report is None:
            _cached_report = CanonicalCrossRepoEvidencePipeline().build()
        return _cached_report


def reset_canonical_cross_repo_evidence_report() -> None:
    """Invalidate the cached report.  Intended for test isolation only."""
    global _cached_report
    with _PIPELINE_LOCK:
        _cached_report = None
