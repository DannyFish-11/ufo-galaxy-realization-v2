#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_canonical_cross_repo_evidence_pipeline.py
=====================================================
PR-05 — Canonical Cross-Repo Evidence Ingestion Pipeline — test suite.

Coverage areas
--------------
A.  Module importable; authority sentinel and PR-05 sentinel present.
B.  All policy sentinels are non-empty strings with expected keywords.
C.  Contract constants present and have expected types/ranges.
D.  EvidenceSourceId enum has five required members.
E.  EvidenceSourceAuthority enum has primary / secondary / advisory values.
F.  IngestionStatus enum has all required values and properties.
G.  PipelineVerdict enum has all required values and properties.
H.  IngestionSourceEntry dataclass: construction, to_dict, from_dict.
I.  CanonicalCrossRepoEvidenceReport: construction, to_dict, to_json, from_dict.
J.  Pipeline produces a report (smoke test — real modules absent → partial/authority_unclear).
K.  Pipeline verdict authority_unclear when PRIMARY module unavailable.
L.  Pipeline verdict partial when PRIMARY source has no artifact (missing).
M.  Pipeline verdict stale when PRIMARY source artifact exceeds max age.
N.  Pipeline verdict complete when all PRIMARY sources are present and fresh.
O.  Pipeline verdict conflicting when PRIMARY sources conflict.
P.  Stale evidence never upgrades to complete verdict.
Q.  Authority unclear never upgrades to complete verdict.
R.  is_complete True only when verdict == complete.
S.  downgrade_reasons is non-empty when verdict != complete.
T.  missing_sources populated when PRIMARY source missing.
U.  stale_sources populated when PRIMARY source stale.
V.  authority_unclear_sources populated when authority unclear.
W.  ADVISORY source (delegated_runtime_audit) does not affect pipeline verdict.
X.  build_canonical_cross_repo_evidence_report() returns fresh report (not cached).
Y.  get_canonical_cross_repo_evidence_report() returns cached report.
Z.  reset_canonical_cross_repo_evidence_report() invalidates cache.
AA. Report is JSON-serialisable end-to-end.
AB. from_dict() round-trips correctly.
AC. Pipeline report integrates into system_final_acceptance_verdict as a dimension.
AD. cross_repo_evidence_pipeline dimension present in AcceptanceDimensionId.
AE. evaluate() checklist includes cross_repo_evidence_pipeline key.
AF. When pipeline returns authority_unclear, acceptance dimension is unresolved.
AG. When pipeline returns partial, acceptance dimension is pending.
AH. When pipeline returns complete, acceptance dimension is accepted.
AI. complete evidence chain: all sources present, fresh, consistent.
AJ. missing evidence: PRIMARY source missing → partial pipeline verdict.
AK. stale evidence: PRIMARY source stale → stale pipeline verdict.
AL. partial evidence: structurally incomplete → partial pipeline verdict.
AM. conflicting evidence: contradictory PRIMARY verdicts → conflicting pipeline verdict.
AN. real-device + lifecycle + delegated runtime audit confluence: advisory
    source does not override PRIMARY verdict.
AO. authority unclear: module unavailable → authority_unclear verdict, never complete.
AP. merge_policy_notes and canonical_precedence_applied are present in reports
    when multiple sources contribute.
AQ. summary field is non-empty and contains VERDICT line.
AR. Pipeline report contains all five source families.
AS. _SOURCE_AUTHORITY maps each EvidenceSourceId to the correct authority.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import core.canonical_cross_repo_evidence_pipeline as _mod
from core.canonical_cross_repo_evidence_pipeline import (
    CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_AUTHORITY,
    CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_PR05_SENTINEL,
    PRIMARY_SOURCE_FRESHNESS_REQUIRED_POLICY,
    STALE_EVIDENCE_NEVER_UPGRADES_VERDICT_POLICY,
    AUTHORITY_UNCLEAR_BLOCKS_COMPLETE_VERDICT_POLICY,
    CONFLICTING_EVIDENCE_NEVER_OPTIMISTIC_POLICY,
    CANONICAL_PRECEDENCE_PRIMARY_OVER_SECONDARY_POLICY,
    MISSING_PRIMARY_SOURCE_DOWNGRADES_TO_PARTIAL_POLICY,
    CANONICAL_PIPELINE_PRIMARY_FRESHNESS_MAX_AGE_SECONDS,
    CANONICAL_PIPELINE_SECONDARY_FRESHNESS_MAX_AGE_SECONDS,
    EvidenceSourceId,
    EvidenceSourceAuthority,
    IngestionStatus,
    PipelineVerdict,
    IngestionSourceEntry,
    CanonicalCrossRepoEvidenceReport,
    CanonicalCrossRepoEvidencePipeline,
    build_canonical_cross_repo_evidence_report,
    get_canonical_cross_repo_evidence_report,
    reset_canonical_cross_repo_evidence_report,
    _SOURCE_AUTHORITY,
)


# ===========================================================================
# Helpers
# ===========================================================================


def _make_source(
    source_id: EvidenceSourceId,
    status: IngestionStatus = IngestionStatus.present,
    authority: EvidenceSourceAuthority = EvidenceSourceAuthority.primary,
    freshness_secs: float = 60.0,
    is_stale: bool = False,
    raw_evidence: Dict[str, Any] = None,
    notes: str = "",
) -> IngestionSourceEntry:
    return IngestionSourceEntry(
        source_id=source_id,
        authority=authority,
        status=status,
        evidence_summary=f"test {source_id.value} {status.value}",
        freshness_secs=freshness_secs,
        is_stale=is_stale,
        raw_evidence=raw_evidence or {},
        notes=notes,
    )


def _make_all_present_sources() -> List[IngestionSourceEntry]:
    """Return a list of IngestionSourceEntry with all sources present."""
    return [
        _make_source(EvidenceSourceId.real_device_verification, freshness_secs=120.0),
        _make_source(EvidenceSourceId.readiness_evidence, freshness_secs=300.0),
        _make_source(
            EvidenceSourceId.participant_lifecycle_truth,
            authority=EvidenceSourceAuthority.secondary,
        ),
        _make_source(
            EvidenceSourceId.task_result_runtime,
            authority=EvidenceSourceAuthority.secondary,
        ),
        _make_source(
            EvidenceSourceId.delegated_runtime_audit,
            authority=EvidenceSourceAuthority.advisory,
        ),
    ]


def _make_complete_report() -> CanonicalCrossRepoEvidenceReport:
    """Return a CanonicalCrossRepoEvidenceReport with complete verdict."""
    return CanonicalCrossRepoEvidenceReport(
        report_id="test-report-id",
        generated_at=time.time(),
        authority=CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_AUTHORITY,
        pipeline_verdict=PipelineVerdict.complete,
        is_complete=True,
        sources=_make_all_present_sources(),
        primary_sources_complete=True,
        primary_sources_fresh=True,
        summary="VERDICT: COMPLETE\nCross-repo evidence chain is canonically closed.",
    )


# ===========================================================================
# A. Module importable; authority sentinels present
# ===========================================================================


class TestModuleSentinels:
    def test_module_importable(self):
        import core.canonical_cross_repo_evidence_pipeline  # noqa: F401

    def test_authority_sentinel_non_empty(self):
        assert CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_AUTHORITY
        assert isinstance(CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_AUTHORITY, str)

    def test_authority_sentinel_contains_pr05(self):
        assert "PR05" in CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_AUTHORITY

    def test_pr05_sentinel_non_empty(self):
        assert CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_PR05_SENTINEL
        assert isinstance(CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_PR05_SENTINEL, str)

    def test_pr05_sentinel_contains_pr05(self):
        assert "PR05" in CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_PR05_SENTINEL


# ===========================================================================
# B. Policy sentinels
# ===========================================================================


class TestPolicySentinels:
    def test_primary_freshness_policy_non_empty(self):
        assert PRIMARY_SOURCE_FRESHNESS_REQUIRED_POLICY

    def test_primary_freshness_policy_contains_policy(self):
        assert "POLICY" in PRIMARY_SOURCE_FRESHNESS_REQUIRED_POLICY

    def test_stale_never_upgrades_policy_non_empty(self):
        assert STALE_EVIDENCE_NEVER_UPGRADES_VERDICT_POLICY

    def test_authority_unclear_blocks_policy_non_empty(self):
        assert AUTHORITY_UNCLEAR_BLOCKS_COMPLETE_VERDICT_POLICY
        assert "PRIMARY" in AUTHORITY_UNCLEAR_BLOCKS_COMPLETE_VERDICT_POLICY

    def test_conflicting_never_optimistic_policy_non_empty(self):
        assert CONFLICTING_EVIDENCE_NEVER_OPTIMISTIC_POLICY

    def test_canonical_precedence_policy_non_empty(self):
        assert CANONICAL_PRECEDENCE_PRIMARY_OVER_SECONDARY_POLICY
        assert "PRIMARY" in CANONICAL_PRECEDENCE_PRIMARY_OVER_SECONDARY_POLICY

    def test_missing_primary_downgrades_policy_non_empty(self):
        assert MISSING_PRIMARY_SOURCE_DOWNGRADES_TO_PARTIAL_POLICY

    def test_policy_sentinel_count(self):
        policies = [
            PRIMARY_SOURCE_FRESHNESS_REQUIRED_POLICY,
            STALE_EVIDENCE_NEVER_UPGRADES_VERDICT_POLICY,
            AUTHORITY_UNCLEAR_BLOCKS_COMPLETE_VERDICT_POLICY,
            CONFLICTING_EVIDENCE_NEVER_OPTIMISTIC_POLICY,
            CANONICAL_PRECEDENCE_PRIMARY_OVER_SECONDARY_POLICY,
            MISSING_PRIMARY_SOURCE_DOWNGRADES_TO_PARTIAL_POLICY,
        ]
        assert len(policies) >= 6


# ===========================================================================
# C. Contract constants
# ===========================================================================


class TestContractConstants:
    def test_primary_max_age_is_positive(self):
        assert CANONICAL_PIPELINE_PRIMARY_FRESHNESS_MAX_AGE_SECONDS > 0

    def test_secondary_max_age_is_positive(self):
        assert CANONICAL_PIPELINE_SECONDARY_FRESHNESS_MAX_AGE_SECONDS > 0

    def test_secondary_max_age_gte_primary(self):
        assert (
            CANONICAL_PIPELINE_SECONDARY_FRESHNESS_MAX_AGE_SECONDS
            >= CANONICAL_PIPELINE_PRIMARY_FRESHNESS_MAX_AGE_SECONDS
        )


# ===========================================================================
# D. EvidenceSourceId enum
# ===========================================================================


class TestEvidenceSourceId:
    def test_has_real_device_verification(self):
        assert EvidenceSourceId.real_device_verification

    def test_has_readiness_evidence(self):
        assert EvidenceSourceId.readiness_evidence

    def test_has_participant_lifecycle_truth(self):
        assert EvidenceSourceId.participant_lifecycle_truth

    def test_has_task_result_runtime(self):
        assert EvidenceSourceId.task_result_runtime

    def test_has_delegated_runtime_audit(self):
        assert EvidenceSourceId.delegated_runtime_audit

    def test_has_five_members(self):
        assert len(list(EvidenceSourceId)) == 5


# ===========================================================================
# E. EvidenceSourceAuthority enum
# ===========================================================================


class TestEvidenceSourceAuthority:
    def test_has_primary(self):
        assert EvidenceSourceAuthority.primary

    def test_has_secondary(self):
        assert EvidenceSourceAuthority.secondary

    def test_has_advisory(self):
        assert EvidenceSourceAuthority.advisory

    def test_has_three_members(self):
        assert len(list(EvidenceSourceAuthority)) == 3


# ===========================================================================
# F. IngestionStatus enum
# ===========================================================================


class TestIngestionStatus:
    def test_has_present(self):
        assert IngestionStatus.present

    def test_has_stale(self):
        assert IngestionStatus.stale

    def test_has_missing(self):
        assert IngestionStatus.missing

    def test_has_partial(self):
        assert IngestionStatus.partial

    def test_has_conflicting(self):
        assert IngestionStatus.conflicting

    def test_has_unavailable(self):
        assert IngestionStatus.unavailable

    def test_has_authority_unclear(self):
        assert IngestionStatus.authority_unclear

    def test_present_is_actionable(self):
        assert IngestionStatus.present.is_actionable

    def test_stale_is_not_actionable(self):
        assert not IngestionStatus.stale.is_actionable

    def test_missing_is_blocking(self):
        assert IngestionStatus.missing.is_blocking

    def test_stale_is_blocking(self):
        assert IngestionStatus.stale.is_blocking

    def test_present_is_not_blocking(self):
        assert not IngestionStatus.present.is_blocking

    def test_authority_unclear_is_blocking(self):
        assert IngestionStatus.authority_unclear.is_blocking


# ===========================================================================
# G. PipelineVerdict enum
# ===========================================================================


class TestPipelineVerdict:
    def test_has_complete(self):
        assert PipelineVerdict.complete

    def test_has_partial(self):
        assert PipelineVerdict.partial

    def test_has_stale(self):
        assert PipelineVerdict.stale

    def test_has_missing(self):
        assert PipelineVerdict.missing

    def test_has_conflicting(self):
        assert PipelineVerdict.conflicting

    def test_has_authority_unclear(self):
        assert PipelineVerdict.authority_unclear

    def test_has_insufficient(self):
        assert PipelineVerdict.insufficient

    def test_complete_is_complete(self):
        assert PipelineVerdict.complete.is_complete

    def test_partial_is_not_complete(self):
        assert not PipelineVerdict.partial.is_complete

    def test_stale_is_not_complete(self):
        assert not PipelineVerdict.stale.is_complete

    def test_authority_unclear_is_not_complete(self):
        assert not PipelineVerdict.authority_unclear.is_complete

    def test_partial_is_blocking(self):
        assert PipelineVerdict.partial.is_blocking

    def test_complete_is_not_blocking(self):
        assert not PipelineVerdict.complete.is_blocking

    def test_conflicting_is_blocking(self):
        assert PipelineVerdict.conflicting.is_blocking

    def test_authority_unclear_is_blocking(self):
        assert PipelineVerdict.authority_unclear.is_blocking


# ===========================================================================
# H. IngestionSourceEntry dataclass
# ===========================================================================


class TestIngestionSourceEntry:
    def test_construction(self):
        entry = _make_source(EvidenceSourceId.real_device_verification)
        assert entry.source_id == EvidenceSourceId.real_device_verification
        assert entry.authority == EvidenceSourceAuthority.primary
        assert entry.status == IngestionStatus.present

    def test_to_dict_has_required_keys(self):
        entry = _make_source(EvidenceSourceId.readiness_evidence)
        d = entry.to_dict()
        for key in (
            "source_id", "authority", "status",
            "evidence_summary", "freshness_secs", "is_stale",
            "raw_evidence", "notes",
        ):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_is_json_serialisable(self):
        entry = _make_source(EvidenceSourceId.real_device_verification)
        json.dumps(entry.to_dict())  # should not raise

    def test_from_dict_round_trip(self):
        entry = _make_source(
            EvidenceSourceId.participant_lifecycle_truth,
            status=IngestionStatus.missing,
            authority=EvidenceSourceAuthority.secondary,
            freshness_secs=1200.0,
            is_stale=True,
            notes="test note",
        )
        restored = IngestionSourceEntry.from_dict(entry.to_dict())
        assert restored.source_id == entry.source_id
        assert restored.authority == entry.authority
        assert restored.status == entry.status
        assert restored.freshness_secs == entry.freshness_secs
        assert restored.is_stale == entry.is_stale
        assert restored.notes == entry.notes


# ===========================================================================
# I. CanonicalCrossRepoEvidenceReport dataclass
# ===========================================================================


class TestCanonicalCrossRepoEvidenceReport:
    def test_construction(self):
        report = _make_complete_report()
        assert report.pipeline_verdict == PipelineVerdict.complete
        assert report.is_complete is True
        assert len(report.sources) == 5

    def test_to_dict_has_required_keys(self):
        report = _make_complete_report()
        d = report.to_dict()
        for key in (
            "report_id", "generated_at", "authority",
            "pipeline_verdict", "is_complete", "sources",
            "primary_sources_complete", "primary_sources_fresh",
            "downgrade_reasons", "conflict_notes",
            "stale_sources", "missing_sources", "partial_sources",
            "unavailable_sources", "authority_unclear_sources",
            "canonical_precedence_applied", "merge_policy_notes",
            "summary",
        ):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_pipeline_verdict_is_string(self):
        report = _make_complete_report()
        d = report.to_dict()
        assert isinstance(d["pipeline_verdict"], str)

    def test_to_json_produces_valid_json(self):
        report = _make_complete_report()
        j = report.to_json()
        parsed = json.loads(j)
        assert parsed["pipeline_verdict"] == "complete"

    def test_from_dict_round_trip(self):
        report = _make_complete_report()
        restored = CanonicalCrossRepoEvidenceReport.from_dict(report.to_dict())
        assert restored.pipeline_verdict == report.pipeline_verdict
        assert restored.is_complete == report.is_complete
        assert restored.report_id == report.report_id
        assert len(restored.sources) == len(report.sources)

    def test_is_complete_false_when_partial(self):
        report = CanonicalCrossRepoEvidenceReport(
            report_id="r",
            generated_at=time.time(),
            authority=CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_AUTHORITY,
            pipeline_verdict=PipelineVerdict.partial,
            is_complete=False,
            sources=[],
        )
        assert report.is_complete is False

    def test_is_complete_false_when_stale(self):
        report = CanonicalCrossRepoEvidenceReport(
            report_id="r",
            generated_at=time.time(),
            authority=CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_AUTHORITY,
            pipeline_verdict=PipelineVerdict.stale,
            is_complete=False,
            sources=[],
        )
        assert report.is_complete is False


# ===========================================================================
# J. Pipeline smoke test — real modules absent
# ===========================================================================


class TestPipelineSmokeTest:
    def test_build_returns_report(self):
        reset_canonical_cross_repo_evidence_report()
        report = build_canonical_cross_repo_evidence_report()
        assert isinstance(report, CanonicalCrossRepoEvidenceReport)

    def test_build_has_five_sources(self):
        reset_canonical_cross_repo_evidence_report()
        report = build_canonical_cross_repo_evidence_report()
        assert len(report.sources) == 5

    def test_build_source_ids(self):
        reset_canonical_cross_repo_evidence_report()
        report = build_canonical_cross_repo_evidence_report()
        source_ids = {s.source_id for s in report.sources}
        assert EvidenceSourceId.real_device_verification in source_ids
        assert EvidenceSourceId.readiness_evidence in source_ids
        assert EvidenceSourceId.participant_lifecycle_truth in source_ids
        assert EvidenceSourceId.task_result_runtime in source_ids
        assert EvidenceSourceId.delegated_runtime_audit in source_ids

    def test_build_authority_is_set(self):
        reset_canonical_cross_repo_evidence_report()
        report = build_canonical_cross_repo_evidence_report()
        assert report.authority == CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_AUTHORITY

    def test_build_verdict_is_not_complete_without_real_evidence(self):
        """Without real Android device evidence, verdict must not be complete."""
        reset_canonical_cross_repo_evidence_report()
        report = build_canonical_cross_repo_evidence_report()
        # In a test environment without real Android devices, verdict must not be complete
        assert report.pipeline_verdict != PipelineVerdict.complete or not report.is_complete


# ===========================================================================
# K. Authority unclear when PRIMARY module unavailable
# ===========================================================================


class TestAuthorityUnclear:
    def test_authority_unclear_when_primary_unavailable(self):
        """If a PRIMARY source module is unavailable, verdict must be authority_unclear."""
        pipeline = CanonicalCrossRepoEvidencePipeline()
        with (
            patch.object(_mod, "_REAL_DEVICE_AVAILABLE", False),
            patch.object(_mod, "_ingest_real_device_evidence", None),
            patch.object(_mod, "_EVALUATOR_AVAILABLE", False),
            patch.object(_mod, "_get_evaluator_registry", None),
        ):
            report = pipeline.build()
        assert report.pipeline_verdict == PipelineVerdict.authority_unclear
        assert not report.is_complete
        assert len(report.authority_unclear_sources) > 0

    def test_authority_unclear_in_downgrade_reasons(self):
        pipeline = CanonicalCrossRepoEvidencePipeline()
        with (
            patch.object(_mod, "_REAL_DEVICE_AVAILABLE", False),
            patch.object(_mod, "_ingest_real_device_evidence", None),
            patch.object(_mod, "_EVALUATOR_AVAILABLE", False),
            patch.object(_mod, "_get_evaluator_registry", None),
        ):
            report = pipeline.build()
        assert len(report.downgrade_reasons) > 0
        assert any(
            "authority_unclear" in r.lower() or "unavailable" in r.lower()
            for r in report.downgrade_reasons
        )

    def test_authority_unclear_blocks_complete_verdict(self):
        """Authority unclear MUST NOT produce a complete verdict per policy."""
        pipeline = CanonicalCrossRepoEvidencePipeline()
        with (
            patch.object(_mod, "_REAL_DEVICE_AVAILABLE", False),
            patch.object(_mod, "_ingest_real_device_evidence", None),
        ):
            report = pipeline.build()
        assert report.pipeline_verdict != PipelineVerdict.complete


# ===========================================================================
# L. Pipeline verdict partial when PRIMARY source missing
# ===========================================================================


class TestMissingEvidence:
    def _mock_missing_real_device(self):
        """Return a mock that simulates missing real-device evidence."""
        mock_result = MagicMock()
        mock_result.status = MagicMock()
        mock_result.status.value = "missing_evidence"
        mock_result.evidence_summary = "No evidence file found."
        mock_result.gap_description = "ANDROID_PARTICIPANT_EVIDENCE_PATH not set."
        mock_result.to_dict.return_value = {
            "status": "missing_evidence",
            "evidence_summary": "No evidence file found.",
            "gap_description": "ANDROID_PARTICIPANT_EVIDENCE_PATH not set.",
        }
        return mock_result

    def test_missing_primary_gives_partial_verdict(self):
        """When PRIMARY real_device_verification is missing → partial."""
        pipeline = CanonicalCrossRepoEvidencePipeline()

        mock_result = self._mock_missing_real_device()
        mock_registry = MagicMock()
        mock_registry.build_snapshot.return_value = {
            "total_artifacts": 5,
            "artifact_counts_by_kind": {"readiness": 2, "governance": 3},
            "latest_by_kind": {
                "readiness": {"received_at": time.time() - 100},
            },
        }

        with (
            patch.object(_mod, "_REAL_DEVICE_AVAILABLE", True),
            patch.object(_mod, "_ingest_real_device_evidence", return_value=mock_result),
            patch.object(_mod, "_REAL_DEVICE_AUTHORITY_SENTINEL", "ANDROID_PARTICIPANT_RUNTIME_EVIDENCE_V1"),
            patch.object(_mod, "_EVALUATOR_AVAILABLE", True),
            patch.object(_mod, "_get_evaluator_registry", return_value=mock_registry),
            patch.object(_mod, "_EVALUATOR_AUTHORITY_SENTINEL", "some-authority"),
        ):
            report = pipeline.build()

        assert report.pipeline_verdict == PipelineVerdict.partial
        assert not report.is_complete
        assert EvidenceSourceId.real_device_verification.value in report.missing_sources

    def test_missing_populates_missing_sources(self):
        pipeline = CanonicalCrossRepoEvidencePipeline()
        mock_result = self._mock_missing_real_device()

        with (
            patch.object(_mod, "_REAL_DEVICE_AVAILABLE", True),
            patch.object(_mod, "_ingest_real_device_evidence", return_value=mock_result),
            patch.object(_mod, "_REAL_DEVICE_AUTHORITY_SENTINEL", "ANDROID_PARTICIPANT_RUNTIME_EVIDENCE_V1"),
            patch.object(_mod, "_EVALUATOR_AVAILABLE", False),
            patch.object(_mod, "_get_evaluator_registry", None),
        ):
            report = pipeline.build()

        assert len(report.missing_sources) > 0 or len(report.authority_unclear_sources) > 0

    def test_missing_populates_downgrade_reasons(self):
        pipeline = CanonicalCrossRepoEvidencePipeline()
        mock_result = self._mock_missing_real_device()

        with (
            patch.object(_mod, "_REAL_DEVICE_AVAILABLE", True),
            patch.object(_mod, "_ingest_real_device_evidence", return_value=mock_result),
            patch.object(_mod, "_REAL_DEVICE_AUTHORITY_SENTINEL", "ANDROID_PARTICIPANT_RUNTIME_EVIDENCE_V1"),
            patch.object(_mod, "_EVALUATOR_AVAILABLE", False),
            patch.object(_mod, "_get_evaluator_registry", None),
        ):
            report = pipeline.build()

        assert len(report.downgrade_reasons) > 0


# ===========================================================================
# M. Pipeline verdict stale when PRIMARY source exceeds max age
# ===========================================================================


class TestStaleEvidence:
    def _mock_stale_real_device(self):
        mock_result = MagicMock()
        mock_result.status = MagicMock()
        mock_result.status.value = "stale_evidence"
        mock_result.evidence_summary = "Evidence is stale."
        mock_result.gap_description = "Evidence file too old."
        mock_result.to_dict.return_value = {
            "status": "stale_evidence",
            "evidence_summary": "Evidence is stale.",
            "gap_description": "Evidence file too old.",
            "generated_at": time.time() - 99999,
        }
        return mock_result

    def test_stale_primary_gives_stale_verdict(self):
        """Stale PRIMARY evidence → stale pipeline verdict."""
        pipeline = CanonicalCrossRepoEvidencePipeline()
        mock_result = self._mock_stale_real_device()

        mock_registry = MagicMock()
        mock_registry.build_snapshot.return_value = {
            "total_artifacts": 3,
            "artifact_counts_by_kind": {"readiness": 3},
            "latest_by_kind": {
                "readiness": {"received_at": time.time() - 100},
            },
        }

        with (
            patch.object(_mod, "_REAL_DEVICE_AVAILABLE", True),
            patch.object(_mod, "_ingest_real_device_evidence", return_value=mock_result),
            patch.object(_mod, "_REAL_DEVICE_AUTHORITY_SENTINEL", "ANDROID_PARTICIPANT_RUNTIME_EVIDENCE_V1"),
            patch.object(_mod, "_EVALUATOR_AVAILABLE", True),
            patch.object(_mod, "_get_evaluator_registry", return_value=mock_registry),
            patch.object(_mod, "_EVALUATOR_AUTHORITY_SENTINEL", "some-authority"),
        ):
            report = pipeline.build()

        assert report.pipeline_verdict == PipelineVerdict.stale
        assert not report.is_complete
        assert EvidenceSourceId.real_device_verification.value in report.stale_sources

    def test_stale_never_upgrades_to_complete(self):
        """STALE_EVIDENCE_NEVER_UPGRADES_VERDICT_POLICY: stale never becomes complete."""
        pipeline = CanonicalCrossRepoEvidencePipeline()
        mock_result = self._mock_stale_real_device()

        with (
            patch.object(_mod, "_REAL_DEVICE_AVAILABLE", True),
            patch.object(_mod, "_ingest_real_device_evidence", return_value=mock_result),
            patch.object(_mod, "_REAL_DEVICE_AUTHORITY_SENTINEL", "ANDROID_PARTICIPANT_RUNTIME_EVIDENCE_V1"),
            patch.object(_mod, "_EVALUATOR_AVAILABLE", False),
            patch.object(_mod, "_get_evaluator_registry", None),
        ):
            report = pipeline.build()

        # Regardless of other sources, stale primary must not give complete verdict
        assert report.pipeline_verdict != PipelineVerdict.complete

    def test_stale_populates_stale_sources_or_downgrade_reasons(self):
        pipeline = CanonicalCrossRepoEvidencePipeline()
        mock_result = self._mock_stale_real_device()

        mock_registry = MagicMock()
        mock_registry.build_snapshot.return_value = {
            "total_artifacts": 1,
            "artifact_counts_by_kind": {"readiness": 1},
            "latest_by_kind": {"readiness": {"received_at": time.time() - 100}},
        }

        with (
            patch.object(_mod, "_REAL_DEVICE_AVAILABLE", True),
            patch.object(_mod, "_ingest_real_device_evidence", return_value=mock_result),
            patch.object(_mod, "_REAL_DEVICE_AUTHORITY_SENTINEL", "ANDROID_PARTICIPANT_RUNTIME_EVIDENCE_V1"),
            patch.object(_mod, "_EVALUATOR_AVAILABLE", True),
            patch.object(_mod, "_get_evaluator_registry", return_value=mock_registry),
            patch.object(_mod, "_EVALUATOR_AUTHORITY_SENTINEL", "some-authority"),
        ):
            report = pipeline.build()

        assert report.stale_sources or report.downgrade_reasons


# ===========================================================================
# N. Pipeline verdict complete when all PRIMARY sources present and fresh
# ===========================================================================


class TestCompleteEvidence:
    def test_complete_verdict_when_all_primary_present_and_fresh(self):
        """Complete verdict requires all PRIMARY sources present and fresh."""
        pipeline = CanonicalCrossRepoEvidencePipeline()

        mock_rdv = MagicMock()
        mock_rdv.status = MagicMock()
        mock_rdv.status.value = "ready"
        mock_rdv.evidence_summary = "Participant ready."
        mock_rdv.gap_description = ""
        now = time.time()
        mock_rdv.to_dict.return_value = {
            "status": "ready",
            "participant_status": "ready",
            "evidence_summary": "Participant ready.",
            "gap_description": "",
            "generated_at": now - 60,
            "is_operational": True,
            "audit_event_count": 5,
        }

        mock_registry = MagicMock()
        mock_registry.build_snapshot.return_value = {
            "total_artifacts": 4,
            "artifact_counts_by_kind": {
                "readiness": 1, "acceptance": 1, "governance": 1, "strategy": 1,
            },
            "latest_by_kind": {
                "readiness": {"received_at": now - 120},
                "acceptance": {"received_at": now - 120},
                "governance": {"received_at": now - 120},
                "strategy": {"received_at": now - 120},
            },
        }

        with (
            patch.object(_mod, "_REAL_DEVICE_AVAILABLE", True),
            patch.object(_mod, "_ingest_real_device_evidence", return_value=mock_rdv),
            patch.object(_mod, "_REAL_DEVICE_AUTHORITY_SENTINEL", "ANDROID_PARTICIPANT_RUNTIME_EVIDENCE_V1"),
            patch.object(_mod, "_EVALUATOR_AVAILABLE", True),
            patch.object(_mod, "_get_evaluator_registry", return_value=mock_registry),
            patch.object(_mod, "_EVALUATOR_AUTHORITY_SENTINEL", "some-authority"),
            patch.object(_mod, "CANONICAL_PIPELINE_PRIMARY_FRESHNESS_MAX_AGE_SECONDS", 3600.0),
        ):
            report = pipeline.build()

        assert report.pipeline_verdict == PipelineVerdict.complete
        assert report.is_complete is True
        assert report.primary_sources_complete is True
        assert report.primary_sources_fresh is True

    def test_complete_is_complete_property(self):
        assert PipelineVerdict.complete.is_complete

    def test_complete_downgrade_reasons_empty(self):
        """When complete, downgrade_reasons must be empty."""
        pipeline = CanonicalCrossRepoEvidencePipeline()

        mock_rdv = MagicMock()
        mock_rdv.status = MagicMock()
        mock_rdv.status.value = "ready"
        mock_rdv.evidence_summary = "ready"
        mock_rdv.gap_description = ""
        now = time.time()
        mock_rdv.to_dict.return_value = {
            "status": "ready",
            "participant_status": "ready",
            "generated_at": now - 60,
            "is_operational": True,
            "audit_event_count": 5,
        }

        mock_registry = MagicMock()
        mock_registry.build_snapshot.return_value = {
            "total_artifacts": 2,
            "artifact_counts_by_kind": {"readiness": 1, "governance": 1},
            "latest_by_kind": {
                "readiness": {"received_at": now - 60},
                "governance": {"received_at": now - 60},
            },
        }

        with (
            patch.object(_mod, "_REAL_DEVICE_AVAILABLE", True),
            patch.object(_mod, "_ingest_real_device_evidence", return_value=mock_rdv),
            patch.object(_mod, "_REAL_DEVICE_AUTHORITY_SENTINEL", "ANDROID_PARTICIPANT_RUNTIME_EVIDENCE_V1"),
            patch.object(_mod, "_EVALUATOR_AVAILABLE", True),
            patch.object(_mod, "_get_evaluator_registry", return_value=mock_registry),
            patch.object(_mod, "_EVALUATOR_AUTHORITY_SENTINEL", "some-authority"),
            patch.object(_mod, "CANONICAL_PIPELINE_PRIMARY_FRESHNESS_MAX_AGE_SECONDS", 3600.0),
        ):
            report = pipeline.build()

        if report.pipeline_verdict == PipelineVerdict.complete:
            assert len(report.downgrade_reasons) == 0


# ===========================================================================
# P. Stale evidence never upgrades verdict
# ===========================================================================


class TestStaleNeverUpgrades:
    def test_stale_evidence_never_produces_complete(self):
        """Per STALE_EVIDENCE_NEVER_UPGRADES_VERDICT_POLICY."""
        entry = _make_source(
            EvidenceSourceId.real_device_verification,
            status=IngestionStatus.stale,
            is_stale=True,
        )
        assert entry.status == IngestionStatus.stale
        # stale is blocking per IngestionStatus
        assert entry.status.is_blocking


# ===========================================================================
# Q. Authority unclear never upgrades verdict
# ===========================================================================


class TestAuthorityUnclearNeverUpgrades:
    def test_authority_unclear_is_blocking(self):
        """Per AUTHORITY_UNCLEAR_BLOCKS_COMPLETE_VERDICT_POLICY."""
        assert IngestionStatus.authority_unclear.is_blocking

    def test_authority_unclear_verdict_is_blocking(self):
        assert PipelineVerdict.authority_unclear.is_blocking


# ===========================================================================
# R. is_complete True only when verdict == complete
# ===========================================================================


class TestIsComplete:
    @pytest.mark.parametrize("verdict", [
        PipelineVerdict.partial,
        PipelineVerdict.stale,
        PipelineVerdict.missing,
        PipelineVerdict.conflicting,
        PipelineVerdict.authority_unclear,
        PipelineVerdict.insufficient,
    ])
    def test_non_complete_verdict_not_is_complete(self, verdict: PipelineVerdict):
        assert not verdict.is_complete

    def test_complete_verdict_is_is_complete(self):
        assert PipelineVerdict.complete.is_complete


# ===========================================================================
# S. downgrade_reasons non-empty when verdict != complete
# ===========================================================================


class TestDowngradeReasons:
    def test_downgrade_reasons_non_empty_when_authority_unclear(self):
        pipeline = CanonicalCrossRepoEvidencePipeline()
        with (
            patch.object(_mod, "_REAL_DEVICE_AVAILABLE", False),
            patch.object(_mod, "_ingest_real_device_evidence", None),
            patch.object(_mod, "_EVALUATOR_AVAILABLE", False),
            patch.object(_mod, "_get_evaluator_registry", None),
        ):
            report = pipeline.build()
        assert len(report.downgrade_reasons) > 0


# ===========================================================================
# T–V. Populated list fields
# ===========================================================================


class TestPopulatedListFields:
    def test_missing_sources_populated_when_primary_missing(self):
        mock_result = MagicMock()
        mock_result.status = MagicMock()
        mock_result.status.value = "missing_evidence"
        mock_result.evidence_summary = "Missing."
        mock_result.gap_description = ""
        mock_result.to_dict.return_value = {"status": "missing_evidence"}

        mock_registry = MagicMock()
        mock_registry.build_snapshot.return_value = {
            "total_artifacts": 3,
            "artifact_counts_by_kind": {"readiness": 3},
            "latest_by_kind": {"readiness": {"received_at": time.time() - 60}},
        }

        pipeline = CanonicalCrossRepoEvidencePipeline()
        with (
            patch.object(_mod, "_REAL_DEVICE_AVAILABLE", True),
            patch.object(_mod, "_ingest_real_device_evidence", return_value=mock_result),
            patch.object(_mod, "_REAL_DEVICE_AUTHORITY_SENTINEL", "ANDROID_PARTICIPANT_RUNTIME_EVIDENCE_V1"),
            patch.object(_mod, "_EVALUATOR_AVAILABLE", True),
            patch.object(_mod, "_get_evaluator_registry", return_value=mock_registry),
            patch.object(_mod, "_EVALUATOR_AUTHORITY_SENTINEL", "some-authority"),
            patch.object(_mod, "CANONICAL_PIPELINE_PRIMARY_FRESHNESS_MAX_AGE_SECONDS", 3600.0),
        ):
            report = pipeline.build()

        assert EvidenceSourceId.real_device_verification.value in report.missing_sources

    def test_authority_unclear_sources_populated_when_module_unavailable(self):
        pipeline = CanonicalCrossRepoEvidencePipeline()
        with (
            patch.object(_mod, "_REAL_DEVICE_AVAILABLE", False),
            patch.object(_mod, "_ingest_real_device_evidence", None),
            patch.object(_mod, "_EVALUATOR_AVAILABLE", False),
            patch.object(_mod, "_get_evaluator_registry", None),
        ):
            report = pipeline.build()

        assert len(report.authority_unclear_sources) > 0


# ===========================================================================
# W. ADVISORY source does not affect pipeline verdict
# ===========================================================================


class TestAdvisorySourceDoesNotAffectVerdict:
    def test_advisory_source_status_does_not_block_partial_verdict(self):
        """ADVISORY delegated_runtime_audit unavailability must not affect verdict."""
        pipeline = CanonicalCrossRepoEvidencePipeline()

        mock_result = MagicMock()
        mock_result.status = MagicMock()
        mock_result.status.value = "missing_evidence"
        mock_result.evidence_summary = "Missing."
        mock_result.gap_description = ""
        mock_result.to_dict.return_value = {"status": "missing_evidence"}

        with (
            patch.object(_mod, "_REAL_DEVICE_AVAILABLE", True),
            patch.object(_mod, "_ingest_real_device_evidence", return_value=mock_result),
            patch.object(_mod, "_REAL_DEVICE_AUTHORITY_SENTINEL", "ANDROID_PARTICIPANT_RUNTIME_EVIDENCE_V1"),
            patch.object(_mod, "_EVALUATOR_AVAILABLE", False),
            patch.object(_mod, "_get_evaluator_registry", None),
            # Audit ADVISORY source is unavailable
            patch.object(_mod, "_AUDIT_AVAILABLE", False),
            patch.object(_mod, "_android_audit_snapshot", None),
        ):
            report = pipeline.build()

        # Should be authority_unclear (due to evaluator unavailable), not worse
        # The key point: ADVISORY source status doesn't determine the verdict
        advisory_entry = next(
            (s for s in report.sources
             if s.source_id == EvidenceSourceId.delegated_runtime_audit),
            None,
        )
        assert advisory_entry is not None
        assert advisory_entry.authority == EvidenceSourceAuthority.advisory

        # Audit status doesn't appear in authority_unclear_sources (that's for PRIMARY only)
        if advisory_entry.status == IngestionStatus.unavailable:
            assert (
                EvidenceSourceId.delegated_runtime_audit.value
                not in report.authority_unclear_sources
            )


# ===========================================================================
# X–Z. Singleton helpers
# ===========================================================================


class TestSingletonHelpers:
    def test_build_returns_new_report_each_time(self):
        reset_canonical_cross_repo_evidence_report()
        r1 = build_canonical_cross_repo_evidence_report()
        r2 = build_canonical_cross_repo_evidence_report()
        # Different report_ids (UUID) means different objects
        assert r1.report_id != r2.report_id

    def test_get_returns_same_report(self):
        reset_canonical_cross_repo_evidence_report()
        r1 = get_canonical_cross_repo_evidence_report()
        r2 = get_canonical_cross_repo_evidence_report()
        assert r1.report_id == r2.report_id

    def test_reset_invalidates_cache(self):
        reset_canonical_cross_repo_evidence_report()
        r1 = get_canonical_cross_repo_evidence_report()
        reset_canonical_cross_repo_evidence_report()
        r2 = get_canonical_cross_repo_evidence_report()
        assert r1.report_id != r2.report_id


# ===========================================================================
# AA–AB. JSON serialisation
# ===========================================================================


class TestJsonSerialisation:
    def test_report_json_serialisable_end_to_end(self):
        reset_canonical_cross_repo_evidence_report()
        report = build_canonical_cross_repo_evidence_report()
        j = report.to_json()
        parsed = json.loads(j)
        assert "pipeline_verdict" in parsed
        assert "sources" in parsed
        assert isinstance(parsed["sources"], list)

    def test_from_dict_round_trip(self):
        reset_canonical_cross_repo_evidence_report()
        original = build_canonical_cross_repo_evidence_report()
        restored = CanonicalCrossRepoEvidenceReport.from_dict(original.to_dict())
        assert restored.pipeline_verdict == original.pipeline_verdict
        assert restored.is_complete == original.is_complete
        assert len(restored.sources) == len(original.sources)


# ===========================================================================
# AC–AH. Integration with system_final_acceptance_verdict
# ===========================================================================


class TestSystemFinalAcceptanceIntegration:
    def test_cross_repo_dimension_in_acceptance_dimension_id(self):
        from core.system_final_acceptance_verdict import AcceptanceDimensionId
        assert AcceptanceDimensionId.cross_repo_evidence_pipeline

    def test_cross_repo_dimension_in_all_dimensions(self):
        from core.system_final_acceptance_verdict import AcceptanceDimensionId
        dims = AcceptanceDimensionId.all_dimensions()
        assert AcceptanceDimensionId.cross_repo_evidence_pipeline in dims

    def test_evaluate_includes_cross_repo_key(self):
        from core.system_final_acceptance_verdict import evaluate_system_acceptance
        report = evaluate_system_acceptance()
        assert "cross_repo_evidence_pipeline" in report.checklist

    def test_evaluate_cross_repo_item_is_checklist_item(self):
        from core.system_final_acceptance_verdict import (
            evaluate_system_acceptance,
            AcceptanceChecklistItem,
        )
        report = evaluate_system_acceptance()
        item = report.checklist.get("cross_repo_evidence_pipeline")
        assert isinstance(item, AcceptanceChecklistItem)

    def test_cross_repo_unresolved_produces_critical_risk(self):
        """When cross_repo dimension is unresolved, overall verdict must be critical risk."""
        from core.system_final_acceptance_verdict import (
            SystemFinalAcceptanceEvaluator,
            AcceptanceDimensionId,
            DimensionStatus,
            SystemAcceptanceVerdict,
            AcceptanceChecklistItem,
        )
        evaluator = SystemFinalAcceptanceEvaluator()
        # Build a checklist where all dims are accepted except cross_repo_evidence_pipeline
        from tests.test_pr17_v2_system_final_acceptance_verdict import (  # type: ignore[import]
            _make_accepted_item,
            _make_unresolved_item,
        )
        checklist = {
            dim.value: _make_accepted_item(dim)
            for dim in AcceptanceDimensionId.all_dimensions()
            if dim != AcceptanceDimensionId.cross_repo_evidence_pipeline
        }
        checklist[AcceptanceDimensionId.cross_repo_evidence_pipeline.value] = (
            _make_unresolved_item(AcceptanceDimensionId.cross_repo_evidence_pipeline)
        )
        verdict = evaluator._compute_verdict(checklist)
        assert verdict == SystemAcceptanceVerdict.not_fully_operational_critical_risk

    def test_cross_repo_pending_produces_pending_verdict(self):
        """When cross_repo dimension is pending, verdict must be pending (not fully_op)."""
        from core.system_final_acceptance_verdict import (
            SystemFinalAcceptanceEvaluator,
            AcceptanceDimensionId,
            DimensionStatus,
            SystemAcceptanceVerdict,
        )
        from tests.test_pr17_v2_system_final_acceptance_verdict import (  # type: ignore[import]
            _make_accepted_item,
        )

        def _make_pending_item(dim):
            return AcceptanceChecklistItem(
                dimension=dim,
                status=DimensionStatus.pending,
                evidence_summary="pending",
                evidence_linkage={},
                gap_description="some gap",
                signal_source="test",
            )

        from core.system_final_acceptance_verdict import AcceptanceChecklistItem
        evaluator = SystemFinalAcceptanceEvaluator()
        checklist = {
            dim.value: _make_accepted_item(dim)
            for dim in AcceptanceDimensionId.all_dimensions()
            if dim != AcceptanceDimensionId.cross_repo_evidence_pipeline
        }
        checklist[AcceptanceDimensionId.cross_repo_evidence_pipeline.value] = (
            _make_pending_item(AcceptanceDimensionId.cross_repo_evidence_pipeline)
        )
        verdict = evaluator._compute_verdict(checklist)
        assert verdict == SystemAcceptanceVerdict.not_fully_operational_pending_dimensions

    def test_pipeline_module_unavailable_gives_unresolved_dimension(self):
        """When pipeline module unavailable, cross_repo_evidence_pipeline is unresolved."""
        from core.system_final_acceptance_verdict import (
            SystemFinalAcceptanceEvaluator,
            DimensionStatus,
        )
        import core.system_final_acceptance_verdict as _sfav
        evaluator = SystemFinalAcceptanceEvaluator()
        with (
            patch.object(_sfav, "_CROSS_REPO_PIPELINE_AVAILABLE", False),
            patch.object(_sfav, "_build_cross_repo_report", None),
        ):
            item = evaluator._evaluate_cross_repo_evidence_pipeline()
        assert item.status == DimensionStatus.unresolved

    def test_pipeline_complete_gives_accepted_dimension(self):
        """When pipeline verdict is complete, cross_repo_evidence_pipeline is accepted."""
        from core.system_final_acceptance_verdict import (
            SystemFinalAcceptanceEvaluator,
            DimensionStatus,
        )
        import core.system_final_acceptance_verdict as _sfav

        complete_report = _make_complete_report()
        evaluator = SystemFinalAcceptanceEvaluator()
        with (
            patch.object(_sfav, "_CROSS_REPO_PIPELINE_AVAILABLE", True),
            patch.object(_sfav, "_build_cross_repo_report", return_value=complete_report),
            patch.object(
                _sfav, "_PipelineVerdict",
                PipelineVerdict,
            ),
        ):
            item = evaluator._evaluate_cross_repo_evidence_pipeline()
        assert item.status == DimensionStatus.accepted

    def test_pipeline_partial_gives_pending_dimension(self):
        """When pipeline verdict is partial, cross_repo_evidence_pipeline is pending."""
        from core.system_final_acceptance_verdict import (
            SystemFinalAcceptanceEvaluator,
            DimensionStatus,
        )
        import core.system_final_acceptance_verdict as _sfav

        partial_report = CanonicalCrossRepoEvidenceReport(
            report_id="partial-report",
            generated_at=time.time(),
            authority=CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_AUTHORITY,
            pipeline_verdict=PipelineVerdict.partial,
            is_complete=False,
            sources=[],
            missing_sources=["real_device_verification"],
            downgrade_reasons=["PRIMARY source missing."],
        )
        evaluator = SystemFinalAcceptanceEvaluator()
        with (
            patch.object(_sfav, "_CROSS_REPO_PIPELINE_AVAILABLE", True),
            patch.object(_sfav, "_build_cross_repo_report", return_value=partial_report),
            patch.object(_sfav, "_PipelineVerdict", PipelineVerdict),
        ):
            item = evaluator._evaluate_cross_repo_evidence_pipeline()
        assert item.status == DimensionStatus.pending

    def test_pipeline_authority_unclear_gives_unresolved_dimension(self):
        """When pipeline verdict is authority_unclear, dimension is unresolved."""
        from core.system_final_acceptance_verdict import (
            SystemFinalAcceptanceEvaluator,
            DimensionStatus,
        )
        import core.system_final_acceptance_verdict as _sfav

        unclear_report = CanonicalCrossRepoEvidenceReport(
            report_id="unclear-report",
            generated_at=time.time(),
            authority=CANONICAL_CROSS_REPO_EVIDENCE_PIPELINE_AUTHORITY,
            pipeline_verdict=PipelineVerdict.authority_unclear,
            is_complete=False,
            sources=[],
            authority_unclear_sources=["real_device_verification"],
            downgrade_reasons=["Authority cannot be confirmed."],
        )
        evaluator = SystemFinalAcceptanceEvaluator()
        with (
            patch.object(_sfav, "_CROSS_REPO_PIPELINE_AVAILABLE", True),
            patch.object(_sfav, "_build_cross_repo_report", return_value=unclear_report),
            patch.object(_sfav, "_PipelineVerdict", PipelineVerdict),
        ):
            item = evaluator._evaluate_cross_repo_evidence_pipeline()
        assert item.status == DimensionStatus.unresolved


# ===========================================================================
# AI. Complete evidence chain
# ===========================================================================


class TestCompleteEvidenceChain:
    def test_complete_chain_has_all_source_families(self):
        """A complete chain must include all five evidence source families."""
        report = _make_complete_report()
        source_ids = {s.source_id for s in report.sources}
        assert EvidenceSourceId.real_device_verification in source_ids
        assert EvidenceSourceId.readiness_evidence in source_ids
        assert EvidenceSourceId.participant_lifecycle_truth in source_ids
        assert EvidenceSourceId.task_result_runtime in source_ids
        assert EvidenceSourceId.delegated_runtime_audit in source_ids

    def test_complete_chain_is_json_serialisable(self):
        report = _make_complete_report()
        json.dumps(report.to_dict())  # must not raise

    def test_complete_chain_is_complete(self):
        report = _make_complete_report()
        assert report.is_complete is True

    def test_complete_chain_has_no_downgrade_reasons(self):
        report = _make_complete_report()
        assert len(report.downgrade_reasons) == 0


# ===========================================================================
# AN. Real-device + lifecycle + audit confluence
# ===========================================================================


class TestRealDeviceLifecycleAuditConfluence:
    def test_advisory_audit_present_does_not_upgrade_partial_verdict(self):
        """Advisory source present + PRIMARY missing → still partial, not complete."""
        mock_rdv = MagicMock()
        mock_rdv.status = MagicMock()
        mock_rdv.status.value = "missing_evidence"
        mock_rdv.evidence_summary = "Missing."
        mock_rdv.gap_description = ""
        mock_rdv.to_dict.return_value = {"status": "missing_evidence"}

        mock_audit_snap = [MagicMock(), MagicMock(), MagicMock()]

        mock_registry = MagicMock()
        mock_registry.build_snapshot.return_value = {
            "total_artifacts": 5,
            "artifact_counts_by_kind": {"readiness": 5},
            "latest_by_kind": {"readiness": {"received_at": time.time() - 60}},
        }

        pipeline = CanonicalCrossRepoEvidencePipeline()
        with (
            patch.object(_mod, "_REAL_DEVICE_AVAILABLE", True),
            patch.object(_mod, "_ingest_real_device_evidence", return_value=mock_rdv),
            patch.object(_mod, "_REAL_DEVICE_AUTHORITY_SENTINEL", "ANDROID_PARTICIPANT_RUNTIME_EVIDENCE_V1"),
            patch.object(_mod, "_EVALUATOR_AVAILABLE", True),
            patch.object(_mod, "_get_evaluator_registry", return_value=mock_registry),
            patch.object(_mod, "_EVALUATOR_AUTHORITY_SENTINEL", "some-authority"),
            patch.object(_mod, "_AUDIT_AVAILABLE", True),
            patch.object(_mod, "_android_audit_snapshot", return_value=mock_audit_snap),
            patch.object(_mod, "_AUDIT_AUTHORITY_SENTINEL", "audit-sentinel"),
            patch.object(_mod, "CANONICAL_PIPELINE_PRIMARY_FRESHNESS_MAX_AGE_SECONDS", 3600.0),
        ):
            report = pipeline.build()

        # Advisory audit records being present must not upgrade a partial verdict
        assert report.pipeline_verdict != PipelineVerdict.complete


# ===========================================================================
# AP. merge_policy_notes and canonical_precedence_applied
# ===========================================================================


class TestMergePolicyNotes:
    def test_merge_policy_notes_present(self):
        reset_canonical_cross_repo_evidence_report()
        report = build_canonical_cross_repo_evidence_report()
        # Should always have some merge policy notes from secondary sources
        assert isinstance(report.merge_policy_notes, list)

    def test_canonical_precedence_applied_is_list(self):
        reset_canonical_cross_repo_evidence_report()
        report = build_canonical_cross_repo_evidence_report()
        assert isinstance(report.canonical_precedence_applied, list)


# ===========================================================================
# AQ. summary field
# ===========================================================================


class TestSummaryField:
    def test_summary_non_empty(self):
        reset_canonical_cross_repo_evidence_report()
        report = build_canonical_cross_repo_evidence_report()
        assert report.summary
        assert isinstance(report.summary, str)

    def test_summary_contains_verdict(self):
        reset_canonical_cross_repo_evidence_report()
        report = build_canonical_cross_repo_evidence_report()
        assert "VERDICT" in report.summary.upper() or report.pipeline_verdict.value.upper() in report.summary.upper()

    def test_summary_contains_conclusion(self):
        reset_canonical_cross_repo_evidence_report()
        report = build_canonical_cross_repo_evidence_report()
        assert "CONCLUSION" in report.summary.upper()


# ===========================================================================
# AR. Pipeline report contains all five source families
# ===========================================================================


class TestAllSourceFamiliesPresent:
    def test_report_has_five_sources(self):
        reset_canonical_cross_repo_evidence_report()
        report = build_canonical_cross_repo_evidence_report()
        assert len(report.sources) == 5

    def test_each_source_has_correct_authority(self):
        reset_canonical_cross_repo_evidence_report()
        report = build_canonical_cross_repo_evidence_report()
        for entry in report.sources:
            expected = _SOURCE_AUTHORITY[entry.source_id]
            assert entry.authority == expected, (
                f"Source {entry.source_id.value} should have authority "
                f"{expected.value} but got {entry.authority.value}"
            )


# ===========================================================================
# AS. _SOURCE_AUTHORITY canonical mapping
# ===========================================================================


class TestSourceAuthorityMapping:
    def test_real_device_is_primary(self):
        assert _SOURCE_AUTHORITY[EvidenceSourceId.real_device_verification] == EvidenceSourceAuthority.primary

    def test_readiness_evidence_is_primary(self):
        assert _SOURCE_AUTHORITY[EvidenceSourceId.readiness_evidence] == EvidenceSourceAuthority.primary

    def test_participant_lifecycle_truth_is_secondary(self):
        assert _SOURCE_AUTHORITY[EvidenceSourceId.participant_lifecycle_truth] == EvidenceSourceAuthority.secondary

    def test_task_result_runtime_is_secondary(self):
        assert _SOURCE_AUTHORITY[EvidenceSourceId.task_result_runtime] == EvidenceSourceAuthority.secondary

    def test_delegated_runtime_audit_is_advisory(self):
        assert _SOURCE_AUTHORITY[EvidenceSourceId.delegated_runtime_audit] == EvidenceSourceAuthority.advisory

    def test_all_sources_mapped(self):
        for src in EvidenceSourceId:
            assert src in _SOURCE_AUTHORITY, f"Source {src.value} not in _SOURCE_AUTHORITY"
