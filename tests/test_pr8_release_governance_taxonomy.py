#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr8_release_governance_taxonomy.py
==============================================
PR-8: Unified Release / Readiness / Governance / Final-Acceptance Taxonomy.

Test suite for :mod:`core.release_governance_taxonomy` and its integration
with the three existing gate/verdict surfaces:

* :mod:`core.release_blocking_gate`
* :mod:`core.governance_validation_gate`
* :mod:`core.system_final_acceptance_verdict`

Coverage matrix
---------------
Group A — Module-level: sentinels, enums, __all__
  A01. Module importable.
  A02. TAXONOMY_AUTHORITY is a non-empty string containing "taxonomy".
  A03. TAXONOMY_PR8_SENTINEL is a non-empty string containing "PR8".
  A04. All six policy sentinels are non-empty strings.
  A05. __all__ contains all required public names.

Group B — IssueClassification enum
  B01. IssueClassification has exactly 9 members.
  B02. blocking, advisory, skeleton_foundational, unresolved, evidence_gap,
       deferred, accepted_limitation, automated_verified, pass_no_issue present.
  B03. blocking.is_blocking is True.
  B04. unresolved.is_blocking is True.
  B05. advisory.is_blocking is False.
  B06. evidence_gap.is_blocking is False.
  B07. deferred.is_blocking is False.
  B08. accepted_limitation.is_blocking is False.
  B09. skeleton_foundational.is_blocking is False.
  B10. automated_verified.is_positive is True.
  B11. pass_no_issue.is_positive is True.
  B12. advisory.is_advisory_only is True.
  B13. blocking.is_advisory_only is False.
  B14. deferred.is_deferred is True.
  B15. blocking.is_deferred is False.

Group C — OperationalStatus enum
  C01. OperationalStatus has exactly 3 members.
  C02. fully_operational, partially_operational, not_ready present.
  C03. fully_operational.is_ready_for_release is True.
  C04. not_ready.is_ready_for_release is False.
  C05. not_ready.blocks_release is True.
  C06. fully_operational.blocks_release is False.

Group D — TaxonomyEntry data class
  D01. TaxonomyEntry constructs with required fields.
  D02. to_dict() returns all required keys.
  D03. to_dict() must_not_confuse_with is a list of strings.

Group E — TerminologyRegistry
  E01. TerminologyRegistry constructs.
  E02. get(blocking) returns a TaxonomyEntry with is_blocking=True.
  E03. get(advisory) returns a TaxonomyEntry with is_blocking=False.
  E04. is_blocking(blocking) is True.
  E05. is_blocking(advisory) is False.
  E06. blocking_terms() contains blocking and unresolved.
  E07. blocking_terms() does NOT contain advisory or deferred.
  E08. advisory_only_terms() contains advisory.
  E09. advisory_only_terms() does NOT contain blocking or unresolved.
  E10. all_entries() returns 9 items (one per classification).
  E11. summary_lines() returns non-empty list.
  E12. [BLOCKING] tag appears in summary lines for blocking terms.
  E13. [advisory] tag appears in summary lines for non-blocking terms.
  E14. get_terminology_registry() returns singleton.
  E15. reset_terminology_registry() / get_terminology_registry() creates fresh.

Group F — classify_issue() helper
  F01. "blocked" text → IssueClassification.blocking.
  F02. "advisory" text → IssueClassification.advisory.
  F03. "unresolved" text → IssueClassification.unresolved.
  F04. "deferred" text → IssueClassification.deferred.
  F05. "evidence gap" text → IssueClassification.evidence_gap.
  F06. "accepted limitation" text → IssueClassification.accepted_limitation.
  F07. "skeleton" text → IssueClassification.skeleton_foundational.
  F08. "automated verified" text → IssueClassification.automated_verified.
  F09. "fully operational" text → IssueClassification.pass_no_issue.
  F10. Unrecognised text → IssueClassification.unresolved (fail-conservative).
  F11. Empty string → IssueClassification.unresolved.
  F12. Non-string → IssueClassification.unresolved.
  F13. Case insensitive: "BLOCKED" → blocking.

Group G — verdict_to_classification() helper
  G01. "passed" → pass_no_issue.
  G02. "failed" → blocking.
  G03. "unknown" → unresolved.
  G04. "pass" → pass_no_issue.
  G05. "warn" → advisory.
  G06. "fail" → blocking.
  G07. "open" → pass_no_issue.
  G08. "blocked" → blocking.
  G09. "deferred" → deferred.
  G10. "accepted" → automated_verified.
  G11. "pending" → evidence_gap.
  G12. "unresolved" → unresolved.
  G13. "fully_operational" → pass_no_issue.
  G14. "not_fully_operational_critical_risk" → blocking.
  G15. "acceptance_unknown_insufficient_evidence" → unresolved.
  G16. "governance_blocked" → blocking.
  G17. "evidence_surface_unavailable" → advisory.
  G18. Unknown token → unresolved (fail-conservative).

Group H — operational_from_verdict() helper
  H01. "open" → fully_operational.
  H02. "blocked" → not_ready.
  H03. "warn" → partially_operational.
  H04. "deferred" → partially_operational.
  H05. "pending" → partially_operational.
  H06. "failed" → not_ready.
  H07. "unresolved" → not_ready.
  H08. "accepted" → fully_operational.
  H09. Unknown token → not_ready (fail-conservative via unresolved).

Group I — is_blocking_classification() helper
  I01. is_blocking_classification(blocking) is True.
  I02. is_blocking_classification(advisory) is False.
  I03. is_blocking_classification(unresolved) is True.

Group J — CRITICAL: advisory is never mistaken for blocking
  J01. advisory classification does not have is_blocking=True.
  J02. verdict_to_classification("warn") is not blocking.
  J03. verdict_to_classification("evidence_surface_unavailable") not blocking.
  J04. classify_issue("advisory") not blocking.
  J05. classify_issue("observational") not blocking.
  J06. operational_from_verdict("warn") is NOT not_ready.

Group K — CRITICAL: blocking conditions prevent release/readiness upgrade
  K01. verdict_to_classification("blocked").is_blocking is True.
  K02. verdict_to_classification("failed").is_blocking is True.
  K03. operational_from_verdict("blocked").blocks_release is True.
  K04. operational_from_verdict("not_fully_operational_critical_risk").blocks_release.
  K05. TerminologyRegistry.is_blocking for every term in blocking_terms() is True.

Group L — CRITICAL: unresolved / evidence_gap / deferred are distinguishable
  L01. verdict_to_classification("unresolved") != verdict_to_classification("deferred").
  L02. verdict_to_classification("pending") != verdict_to_classification("unresolved").
  L03. verdict_to_classification("deferred") != verdict_to_classification("pending").
  L04. IssueClassification.unresolved != IssueClassification.evidence_gap.
  L05. IssueClassification.evidence_gap != IssueClassification.deferred.
  L06. IssueClassification.deferred != IssueClassification.unresolved.
  L07. unresolved.is_blocking; evidence_gap is NOT blocking; deferred is NOT blocking.

Group M — Integration: release_blocking_gate uses taxonomy
  M01. release_blocking_gate importable.
  M02. GateCriterionResult.to_dict() includes taxonomy_classification when available.
  M03. taxonomy_classification for a PASSED criterion is "pass_no_issue".
  M04. taxonomy_classification for a FAILED criterion is "blocking".
  M05. ReleaseGateDecision.to_dict() includes taxonomy_alignment key.

Group N — Integration: governance_validation_gate uses taxonomy
  N01. governance_validation_gate importable.
  N02. ValidationResult.to_dict() includes taxonomy_classification when available.
  N03. taxonomy_classification for PASS outcome is "pass_no_issue".
  N04. taxonomy_classification for FAIL outcome is "blocking".
  N05. taxonomy_classification for WARN outcome is "advisory".
  N06. ValidationResult.to_dict() includes taxonomy_alignment key.

Group O — Integration: system_final_acceptance_verdict uses taxonomy
  O01. system_final_acceptance_verdict importable.
  O02. SystemAcceptanceReport.to_dict() includes taxonomy_classification when avail.
  O03. taxonomy_classification for fully_operational verdict is "pass_no_issue".
  O04. taxonomy_classification for not_fully_operational_critical_risk is "blocking".
  O05. taxonomy_operational_status for fully_operational is "fully_operational".
  O06. taxonomy_operational_status for not_fully_operational_critical_risk is "not_ready".
  O07. SystemAcceptanceReport.to_dict() includes taxonomy_alignment key.

Group P — Summary/report output terminology consistency
  P01. summary_lines() uses [BLOCKING] and [advisory] tags consistently.
  P02. Every taxonomy entry must_not_confuse_with list is non-empty.
  P03. Every entry's must_not_confuse_with list contains only other terms.
  P04. No entry's must_not_confuse_with includes itself.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Primary module import
# ---------------------------------------------------------------------------

try:
    from core.release_governance_taxonomy import (
        TAXONOMY_AUTHORITY,
        TAXONOMY_PR8_SENTINEL,
        BLOCKING_VS_ADVISORY_BOUNDARY_POLICY,
        SKELETON_VS_FINAL_ACCEPTANCE_BOUNDARY_POLICY,
        EVIDENCE_GAP_VS_DEFERRED_VS_UNRESOLVED_BOUNDARY_POLICY,
        ACCEPTED_LIMITATION_MUST_NOT_SUPPRESS_BLOCKING_POLICY,
        AUTOMATED_VERIFIED_REQUIRES_EXPLICIT_EVIDENCE_POLICY,
        FAIL_CONSERVATIVE_UNKNOWN_IS_UNRESOLVED_POLICY,
        IssueClassification,
        OperationalStatus,
        TaxonomyEntry,
        TerminologyRegistry,
        classify_issue,
        verdict_to_classification,
        operational_from_verdict,
        is_blocking_classification,
        get_terminology_registry,
        reset_terminology_registry,
    )
    _MODULE_AVAILABLE = True
except ImportError as _e:
    _MODULE_AVAILABLE = False
    _import_err_msg = str(_e)

_skip_if_unavailable = pytest.mark.skipif(
    not _MODULE_AVAILABLE,
    reason=f"core.release_governance_taxonomy not importable: {locals().get('_import_err_msg', '')}",
)

# ---------------------------------------------------------------------------
# Integration module imports (graceful)
# ---------------------------------------------------------------------------

try:
    from core.release_blocking_gate import (
        GateCriterionResult,
        ReleaseGateDecision,
        CriterionStatus,
    )
    _RBG_AVAILABLE = True
except ImportError:
    _RBG_AVAILABLE = False

try:
    from core.governance_validation_gate import (
        ValidationResult,
        ValidationOutcome,
        ValidationFailReason,
    )
    _GVG_AVAILABLE = True
except ImportError:
    _GVG_AVAILABLE = False

try:
    from core.system_final_acceptance_verdict import (
        SystemAcceptanceReport,
        SystemAcceptanceVerdict,
        AcceptanceDimensionId,
        AcceptanceChecklistItem,
        DimensionStatus,
    )
    _SFAV_AVAILABLE = True
except ImportError:
    _SFAV_AVAILABLE = False


# ===========================================================================
# Group A — Module-level
# ===========================================================================


class TestModuleLevel:
    @_skip_if_unavailable
    def test_A01_module_importable(self):
        import core.release_governance_taxonomy  # noqa: F401

    @_skip_if_unavailable
    def test_A02_taxonomy_authority_contains_taxonomy(self):
        assert "taxonomy" in TAXONOMY_AUTHORITY.lower()

    @_skip_if_unavailable
    def test_A03_pr8_sentinel_contains_pr8(self):
        assert "PR8" in TAXONOMY_PR8_SENTINEL

    @_skip_if_unavailable
    def test_A04_all_policy_sentinels_non_empty(self):
        for sentinel in [
            BLOCKING_VS_ADVISORY_BOUNDARY_POLICY,
            SKELETON_VS_FINAL_ACCEPTANCE_BOUNDARY_POLICY,
            EVIDENCE_GAP_VS_DEFERRED_VS_UNRESOLVED_BOUNDARY_POLICY,
            ACCEPTED_LIMITATION_MUST_NOT_SUPPRESS_BLOCKING_POLICY,
            AUTOMATED_VERIFIED_REQUIRES_EXPLICIT_EVIDENCE_POLICY,
            FAIL_CONSERVATIVE_UNKNOWN_IS_UNRESOLVED_POLICY,
        ]:
            assert isinstance(sentinel, str) and len(sentinel) > 0

    @_skip_if_unavailable
    def test_A05_all_contains_required_public_names(self):
        import core.release_governance_taxonomy as mod
        required = [
            "TAXONOMY_AUTHORITY",
            "IssueClassification",
            "OperationalStatus",
            "TaxonomyEntry",
            "TerminologyRegistry",
            "classify_issue",
            "verdict_to_classification",
            "operational_from_verdict",
            "is_blocking_classification",
            "get_terminology_registry",
            "reset_terminology_registry",
        ]
        for name in required:
            assert name in mod.__all__, f"{name!r} missing from __all__"


# ===========================================================================
# Group B — IssueClassification
# ===========================================================================


class TestIssueClassification:
    @_skip_if_unavailable
    def test_B01_exactly_9_members(self):
        assert len(list(IssueClassification)) == 9

    @_skip_if_unavailable
    def test_B02_all_required_members_present(self):
        for name in [
            "blocking", "advisory", "skeleton_foundational", "unresolved",
            "evidence_gap", "deferred", "accepted_limitation",
            "automated_verified", "pass_no_issue",
        ]:
            assert hasattr(IssueClassification, name), f"missing: {name}"

    @_skip_if_unavailable
    def test_B03_blocking_is_blocking(self):
        assert IssueClassification.blocking.is_blocking is True

    @_skip_if_unavailable
    def test_B04_unresolved_is_blocking(self):
        assert IssueClassification.unresolved.is_blocking is True

    @_skip_if_unavailable
    def test_B05_advisory_not_blocking(self):
        assert IssueClassification.advisory.is_blocking is False

    @_skip_if_unavailable
    def test_B06_evidence_gap_not_blocking(self):
        assert IssueClassification.evidence_gap.is_blocking is False

    @_skip_if_unavailable
    def test_B07_deferred_not_blocking(self):
        assert IssueClassification.deferred.is_blocking is False

    @_skip_if_unavailable
    def test_B08_accepted_limitation_not_blocking(self):
        assert IssueClassification.accepted_limitation.is_blocking is False

    @_skip_if_unavailable
    def test_B09_skeleton_foundational_not_blocking(self):
        assert IssueClassification.skeleton_foundational.is_blocking is False

    @_skip_if_unavailable
    def test_B10_automated_verified_is_positive(self):
        assert IssueClassification.automated_verified.is_positive is True

    @_skip_if_unavailable
    def test_B11_pass_no_issue_is_positive(self):
        assert IssueClassification.pass_no_issue.is_positive is True

    @_skip_if_unavailable
    def test_B12_advisory_is_advisory_only(self):
        assert IssueClassification.advisory.is_advisory_only is True

    @_skip_if_unavailable
    def test_B13_blocking_not_advisory_only(self):
        assert IssueClassification.blocking.is_advisory_only is False

    @_skip_if_unavailable
    def test_B14_deferred_is_deferred(self):
        assert IssueClassification.deferred.is_deferred is True

    @_skip_if_unavailable
    def test_B15_blocking_not_deferred(self):
        assert IssueClassification.blocking.is_deferred is False


# ===========================================================================
# Group C — OperationalStatus
# ===========================================================================


class TestOperationalStatus:
    @_skip_if_unavailable
    def test_C01_exactly_3_members(self):
        assert len(list(OperationalStatus)) == 3

    @_skip_if_unavailable
    def test_C02_required_members(self):
        for name in ["fully_operational", "partially_operational", "not_ready"]:
            assert hasattr(OperationalStatus, name)

    @_skip_if_unavailable
    def test_C03_fully_operational_ready(self):
        assert OperationalStatus.fully_operational.is_ready_for_release is True

    @_skip_if_unavailable
    def test_C04_not_ready_not_ready(self):
        assert OperationalStatus.not_ready.is_ready_for_release is False

    @_skip_if_unavailable
    def test_C05_not_ready_blocks_release(self):
        assert OperationalStatus.not_ready.blocks_release is True

    @_skip_if_unavailable
    def test_C06_fully_operational_does_not_block(self):
        assert OperationalStatus.fully_operational.blocks_release is False


# ===========================================================================
# Group D — TaxonomyEntry
# ===========================================================================


class TestTaxonomyEntry:
    @_skip_if_unavailable
    def test_D01_constructs(self):
        entry = TaxonomyEntry(
            term=IssueClassification.blocking,
            short_definition="test definition",
            is_blocking=True,
        )
        assert entry.term == IssueClassification.blocking

    @_skip_if_unavailable
    def test_D02_to_dict_has_required_keys(self):
        entry = TaxonomyEntry(
            term=IssueClassification.advisory,
            short_definition="advisory def",
            is_blocking=False,
        )
        d = entry.to_dict()
        for key in ["term", "short_definition", "is_blocking", "surface_examples",
                    "must_not_confuse_with"]:
            assert key in d, f"missing key: {key}"

    @_skip_if_unavailable
    def test_D03_must_not_confuse_with_is_list_of_strings(self):
        entry = TaxonomyEntry(
            term=IssueClassification.blocking,
            short_definition="def",
            is_blocking=True,
            must_not_confuse_with=[IssueClassification.advisory],
        )
        d = entry.to_dict()
        assert isinstance(d["must_not_confuse_with"], list)
        assert all(isinstance(s, str) for s in d["must_not_confuse_with"])


# ===========================================================================
# Group E — TerminologyRegistry
# ===========================================================================


class TestTerminologyRegistry:
    @_skip_if_unavailable
    def test_E01_constructs(self):
        registry = TerminologyRegistry()
        assert registry is not None

    @_skip_if_unavailable
    def test_E02_get_blocking_has_is_blocking_true(self):
        registry = TerminologyRegistry()
        entry = registry.get(IssueClassification.blocking)
        assert entry is not None
        assert entry.is_blocking is True

    @_skip_if_unavailable
    def test_E03_get_advisory_has_is_blocking_false(self):
        registry = TerminologyRegistry()
        entry = registry.get(IssueClassification.advisory)
        assert entry is not None
        assert entry.is_blocking is False

    @_skip_if_unavailable
    def test_E04_is_blocking_blocking_true(self):
        registry = TerminologyRegistry()
        assert registry.is_blocking(IssueClassification.blocking) is True

    @_skip_if_unavailable
    def test_E05_is_blocking_advisory_false(self):
        registry = TerminologyRegistry()
        assert registry.is_blocking(IssueClassification.advisory) is False

    @_skip_if_unavailable
    def test_E06_blocking_terms_contains_blocking_and_unresolved(self):
        registry = TerminologyRegistry()
        bt = registry.blocking_terms()
        assert IssueClassification.blocking in bt
        assert IssueClassification.unresolved in bt

    @_skip_if_unavailable
    def test_E07_blocking_terms_does_not_contain_advisory_or_deferred(self):
        registry = TerminologyRegistry()
        bt = registry.blocking_terms()
        assert IssueClassification.advisory not in bt
        assert IssueClassification.deferred not in bt

    @_skip_if_unavailable
    def test_E08_advisory_only_terms_contains_advisory(self):
        registry = TerminologyRegistry()
        aot = registry.advisory_only_terms()
        assert IssueClassification.advisory in aot

    @_skip_if_unavailable
    def test_E09_advisory_only_terms_no_blocking_or_unresolved(self):
        registry = TerminologyRegistry()
        aot = registry.advisory_only_terms()
        assert IssueClassification.blocking not in aot
        assert IssueClassification.unresolved not in aot

    @_skip_if_unavailable
    def test_E10_all_entries_9_items(self):
        registry = TerminologyRegistry()
        assert len(registry.all_entries()) == 9

    @_skip_if_unavailable
    def test_E11_summary_lines_non_empty(self):
        registry = TerminologyRegistry()
        lines = registry.summary_lines()
        assert len(lines) > 0

    @_skip_if_unavailable
    def test_E12_blocking_tag_in_summary_for_blocking_terms(self):
        registry = TerminologyRegistry()
        lines = registry.summary_lines()
        has_blocking_tag = any("[BLOCKING]" in line for line in lines)
        assert has_blocking_tag

    @_skip_if_unavailable
    def test_E13_advisory_tag_in_summary_for_non_blocking(self):
        registry = TerminologyRegistry()
        lines = registry.summary_lines()
        has_advisory_tag = any("[advisory]" in line for line in lines)
        assert has_advisory_tag

    @_skip_if_unavailable
    def test_E14_get_terminology_registry_singleton(self):
        reset_terminology_registry()
        r1 = get_terminology_registry()
        r2 = get_terminology_registry()
        assert r1 is r2

    @_skip_if_unavailable
    def test_E15_reset_then_get_creates_fresh(self):
        r1 = get_terminology_registry()
        reset_terminology_registry()
        r2 = get_terminology_registry()
        assert r1 is not r2


# ===========================================================================
# Group F — classify_issue()
# ===========================================================================


class TestClassifyIssue:
    @_skip_if_unavailable
    def test_F01_blocked_text(self):
        assert classify_issue("blocked") == IssueClassification.blocking

    @_skip_if_unavailable
    def test_F02_advisory_text(self):
        assert classify_issue("advisory") == IssueClassification.advisory

    @_skip_if_unavailable
    def test_F03_unresolved_text(self):
        assert classify_issue("unresolved signal") == IssueClassification.unresolved

    @_skip_if_unavailable
    def test_F04_deferred_text(self):
        assert classify_issue("deferred evaluation") == IssueClassification.deferred

    @_skip_if_unavailable
    def test_F05_evidence_gap_text(self):
        assert classify_issue("evidence gap exists") == IssueClassification.evidence_gap

    @_skip_if_unavailable
    def test_F06_accepted_limitation_text(self):
        assert classify_issue("accepted limitation") == IssueClassification.accepted_limitation

    @_skip_if_unavailable
    def test_F07_skeleton_text(self):
        assert classify_issue("skeleton readiness") == IssueClassification.skeleton_foundational

    @_skip_if_unavailable
    def test_F08_automated_verified_text(self):
        assert classify_issue("automated verified") == IssueClassification.automated_verified

    @_skip_if_unavailable
    def test_F09_fully_operational_text(self):
        assert classify_issue("fully operational") == IssueClassification.pass_no_issue

    @_skip_if_unavailable
    def test_F10_unrecognised_defaults_to_unresolved(self):
        assert classify_issue("xyzzy completely unknown gibberish") == IssueClassification.unresolved

    @_skip_if_unavailable
    def test_F11_empty_string_returns_unresolved(self):
        assert classify_issue("") == IssueClassification.unresolved

    @_skip_if_unavailable
    def test_F12_non_string_returns_unresolved(self):
        assert classify_issue(None) == IssueClassification.unresolved  # type: ignore[arg-type]

    @_skip_if_unavailable
    def test_F13_case_insensitive(self):
        assert classify_issue("BLOCKED") == IssueClassification.blocking


# ===========================================================================
# Group G — verdict_to_classification()
# ===========================================================================


class TestVerdictToClassification:
    @_skip_if_unavailable
    def test_G01_passed(self):
        assert verdict_to_classification("passed") == IssueClassification.pass_no_issue

    @_skip_if_unavailable
    def test_G02_failed(self):
        assert verdict_to_classification("failed") == IssueClassification.blocking

    @_skip_if_unavailable
    def test_G03_unknown(self):
        assert verdict_to_classification("unknown") == IssueClassification.unresolved

    @_skip_if_unavailable
    def test_G04_pass(self):
        assert verdict_to_classification("pass") == IssueClassification.pass_no_issue

    @_skip_if_unavailable
    def test_G05_warn(self):
        assert verdict_to_classification("warn") == IssueClassification.advisory

    @_skip_if_unavailable
    def test_G06_fail(self):
        assert verdict_to_classification("fail") == IssueClassification.blocking

    @_skip_if_unavailable
    def test_G07_open(self):
        assert verdict_to_classification("open") == IssueClassification.pass_no_issue

    @_skip_if_unavailable
    def test_G08_blocked(self):
        assert verdict_to_classification("blocked") == IssueClassification.blocking

    @_skip_if_unavailable
    def test_G09_deferred(self):
        assert verdict_to_classification("deferred") == IssueClassification.deferred

    @_skip_if_unavailable
    def test_G10_accepted(self):
        assert verdict_to_classification("accepted") == IssueClassification.automated_verified

    @_skip_if_unavailable
    def test_G11_pending(self):
        assert verdict_to_classification("pending") == IssueClassification.evidence_gap

    @_skip_if_unavailable
    def test_G12_unresolved(self):
        assert verdict_to_classification("unresolved") == IssueClassification.unresolved

    @_skip_if_unavailable
    def test_G13_fully_operational(self):
        assert verdict_to_classification("fully_operational") == IssueClassification.pass_no_issue

    @_skip_if_unavailable
    def test_G14_not_fully_operational_critical_risk(self):
        assert verdict_to_classification("not_fully_operational_critical_risk") == IssueClassification.blocking

    @_skip_if_unavailable
    def test_G15_acceptance_unknown_insufficient_evidence(self):
        assert verdict_to_classification("acceptance_unknown_insufficient_evidence") == IssueClassification.unresolved

    @_skip_if_unavailable
    def test_G16_governance_blocked(self):
        assert verdict_to_classification("governance_blocked") == IssueClassification.blocking

    @_skip_if_unavailable
    def test_G17_evidence_surface_unavailable(self):
        assert verdict_to_classification("evidence_surface_unavailable") == IssueClassification.advisory

    @_skip_if_unavailable
    def test_G18_unknown_token_defaults_to_unresolved(self):
        assert verdict_to_classification("xyzzy_unknown_token") == IssueClassification.unresolved


# ===========================================================================
# Group H — operational_from_verdict()
# ===========================================================================


class TestOperationalFromVerdict:
    @_skip_if_unavailable
    def test_H01_open_fully_operational(self):
        assert operational_from_verdict("open") == OperationalStatus.fully_operational

    @_skip_if_unavailable
    def test_H02_blocked_not_ready(self):
        assert operational_from_verdict("blocked") == OperationalStatus.not_ready

    @_skip_if_unavailable
    def test_H03_warn_partially_operational(self):
        assert operational_from_verdict("warn") == OperationalStatus.partially_operational

    @_skip_if_unavailable
    def test_H04_deferred_partially_operational(self):
        assert operational_from_verdict("deferred") == OperationalStatus.partially_operational

    @_skip_if_unavailable
    def test_H05_pending_partially_operational(self):
        assert operational_from_verdict("pending") == OperationalStatus.partially_operational

    @_skip_if_unavailable
    def test_H06_failed_not_ready(self):
        assert operational_from_verdict("failed") == OperationalStatus.not_ready

    @_skip_if_unavailable
    def test_H07_unresolved_not_ready(self):
        assert operational_from_verdict("unresolved") == OperationalStatus.not_ready

    @_skip_if_unavailable
    def test_H08_accepted_fully_operational(self):
        assert operational_from_verdict("accepted") == OperationalStatus.fully_operational

    @_skip_if_unavailable
    def test_H09_unknown_token_not_ready(self):
        assert operational_from_verdict("xyzzy_unknown") == OperationalStatus.not_ready


# ===========================================================================
# Group I — is_blocking_classification()
# ===========================================================================


class TestIsBlockingClassification:
    @_skip_if_unavailable
    def test_I01_blocking_true(self):
        assert is_blocking_classification(IssueClassification.blocking) is True

    @_skip_if_unavailable
    def test_I02_advisory_false(self):
        assert is_blocking_classification(IssueClassification.advisory) is False

    @_skip_if_unavailable
    def test_I03_unresolved_true(self):
        assert is_blocking_classification(IssueClassification.unresolved) is True


# ===========================================================================
# Group J — CRITICAL: advisory is never mistaken for blocking
# ===========================================================================


class TestAdvisoryNeverBlocking:
    @_skip_if_unavailable
    def test_J01_advisory_classification_not_blocking(self):
        assert IssueClassification.advisory.is_blocking is False

    @_skip_if_unavailable
    def test_J02_warn_verdict_not_blocking(self):
        cls = verdict_to_classification("warn")
        assert cls.is_blocking is False

    @_skip_if_unavailable
    def test_J03_evidence_surface_unavailable_not_blocking(self):
        cls = verdict_to_classification("evidence_surface_unavailable")
        assert cls.is_blocking is False

    @_skip_if_unavailable
    def test_J04_classify_advisory_not_blocking(self):
        cls = classify_issue("advisory")
        assert cls.is_blocking is False

    @_skip_if_unavailable
    def test_J05_classify_observational_not_blocking(self):
        cls = classify_issue("observational note")
        assert cls.is_blocking is False

    @_skip_if_unavailable
    def test_J06_operational_warn_not_not_ready(self):
        status = operational_from_verdict("warn")
        assert status != OperationalStatus.not_ready


# ===========================================================================
# Group K — CRITICAL: blocking conditions prevent release
# ===========================================================================


class TestBlockingPreventsRelease:
    @_skip_if_unavailable
    def test_K01_blocked_verdict_is_blocking(self):
        assert verdict_to_classification("blocked").is_blocking is True

    @_skip_if_unavailable
    def test_K02_failed_verdict_is_blocking(self):
        assert verdict_to_classification("failed").is_blocking is True

    @_skip_if_unavailable
    def test_K03_blocked_operational_blocks_release(self):
        assert operational_from_verdict("blocked").blocks_release is True

    @_skip_if_unavailable
    def test_K04_critical_risk_blocks_release(self):
        status = operational_from_verdict("not_fully_operational_critical_risk")
        assert status.blocks_release is True

    @_skip_if_unavailable
    def test_K05_registry_blocking_terms_all_have_is_blocking_true(self):
        registry = TerminologyRegistry()
        for term in registry.blocking_terms():
            assert registry.is_blocking(term), f"{term} should be blocking"


# ===========================================================================
# Group L — CRITICAL: unresolved / evidence_gap / deferred distinguishable
# ===========================================================================


class TestThreeWayDistinction:
    @_skip_if_unavailable
    def test_L01_unresolved_ne_deferred(self):
        assert (
            verdict_to_classification("unresolved")
            != verdict_to_classification("deferred")
        )

    @_skip_if_unavailable
    def test_L02_pending_ne_unresolved(self):
        assert (
            verdict_to_classification("pending")
            != verdict_to_classification("unresolved")
        )

    @_skip_if_unavailable
    def test_L03_deferred_ne_pending(self):
        assert (
            verdict_to_classification("deferred")
            != verdict_to_classification("pending")
        )

    @_skip_if_unavailable
    def test_L04_unresolved_ne_evidence_gap(self):
        assert IssueClassification.unresolved != IssueClassification.evidence_gap

    @_skip_if_unavailable
    def test_L05_evidence_gap_ne_deferred(self):
        assert IssueClassification.evidence_gap != IssueClassification.deferred

    @_skip_if_unavailable
    def test_L06_deferred_ne_unresolved(self):
        assert IssueClassification.deferred != IssueClassification.unresolved

    @_skip_if_unavailable
    def test_L07_blocking_profile_differs_across_three(self):
        assert IssueClassification.unresolved.is_blocking is True
        assert IssueClassification.evidence_gap.is_blocking is False
        assert IssueClassification.deferred.is_blocking is False


# ===========================================================================
# Group M — Integration: release_blocking_gate
# ===========================================================================


@pytest.mark.skipif(not _RBG_AVAILABLE, reason="release_blocking_gate not importable")
@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="taxonomy module not importable")
class TestReleaseBlockingGateIntegration:
    def test_M01_module_importable(self):
        import core.release_blocking_gate  # noqa: F401

    def test_M02_criterion_to_dict_has_taxonomy_classification(self):
        crit = GateCriterionResult(
            criterion_id="test",
            display_name="Test",
            status=CriterionStatus.PASSED,
        )
        d = crit.to_dict()
        # taxonomy_classification present when taxonomy available
        assert "taxonomy_classification" in d

    def test_M03_passed_criterion_taxonomy_is_pass_no_issue(self):
        crit = GateCriterionResult(
            criterion_id="test",
            display_name="Test",
            status=CriterionStatus.PASSED,
        )
        d = crit.to_dict()
        assert d.get("taxonomy_classification") == "pass_no_issue"

    def test_M04_failed_criterion_taxonomy_is_blocking(self):
        crit = GateCriterionResult(
            criterion_id="test",
            display_name="Test",
            status=CriterionStatus.FAILED,
        )
        d = crit.to_dict()
        assert d.get("taxonomy_classification") == "blocking"

    def test_M05_decision_to_dict_has_taxonomy_alignment(self):
        decision = ReleaseGateDecision(
            approved=True,
            failed_criteria=[],
            criteria=[],
        )
        d = decision.to_dict()
        assert "taxonomy_alignment" in d
        assert "PR8" in d["taxonomy_alignment"]


# ===========================================================================
# Group N — Integration: governance_validation_gate
# ===========================================================================


@pytest.mark.skipif(not _GVG_AVAILABLE, reason="governance_validation_gate not importable")
@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="taxonomy module not importable")
class TestGovernanceValidationGateIntegration:
    def _make_result(self, outcome: ValidationOutcome) -> ValidationResult:
        return ValidationResult(
            result_id="test",
            generated_at=0.0,
            outcome=outcome,
        )

    def test_N01_module_importable(self):
        import core.governance_validation_gate  # noqa: F401

    def test_N02_result_to_dict_has_taxonomy_classification(self):
        result = self._make_result(ValidationOutcome.PASS)
        d = result.to_dict()
        assert "taxonomy_classification" in d

    def test_N03_pass_outcome_taxonomy_is_pass_no_issue(self):
        result = self._make_result(ValidationOutcome.PASS)
        d = result.to_dict()
        assert d.get("taxonomy_classification") == "pass_no_issue"

    def test_N04_fail_outcome_taxonomy_is_blocking(self):
        result = self._make_result(ValidationOutcome.FAIL)
        d = result.to_dict()
        assert d.get("taxonomy_classification") == "blocking"

    def test_N05_warn_outcome_taxonomy_is_advisory(self):
        result = self._make_result(ValidationOutcome.WARN)
        d = result.to_dict()
        assert d.get("taxonomy_classification") == "advisory"

    def test_N06_result_to_dict_has_taxonomy_alignment(self):
        result = self._make_result(ValidationOutcome.PASS)
        d = result.to_dict()
        assert "taxonomy_alignment" in d
        assert "PR8" in d["taxonomy_alignment"]


# ===========================================================================
# Group O — Integration: system_final_acceptance_verdict
# ===========================================================================


@pytest.mark.skipif(not _SFAV_AVAILABLE, reason="system_final_acceptance_verdict not importable")
@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="taxonomy module not importable")
class TestSystemFinalAcceptanceVerdictIntegration:
    def _make_report(self, verdict: SystemAcceptanceVerdict) -> SystemAcceptanceReport:
        return SystemAcceptanceReport(
            verdict=verdict,
            is_fully_operational=(verdict == SystemAcceptanceVerdict.fully_operational),
        )

    def test_O01_module_importable(self):
        import core.system_final_acceptance_verdict  # noqa: F401

    def test_O02_report_to_dict_has_taxonomy_classification(self):
        report = self._make_report(SystemAcceptanceVerdict.fully_operational)
        d = report.to_dict()
        assert "taxonomy_classification" in d

    def test_O03_fully_operational_taxonomy_is_pass_no_issue(self):
        report = self._make_report(SystemAcceptanceVerdict.fully_operational)
        d = report.to_dict()
        assert d.get("taxonomy_classification") == "pass_no_issue"

    def test_O04_critical_risk_taxonomy_is_blocking(self):
        report = self._make_report(
            SystemAcceptanceVerdict.not_fully_operational_critical_risk
        )
        d = report.to_dict()
        assert d.get("taxonomy_classification") == "blocking"

    def test_O05_fully_operational_operational_status(self):
        report = self._make_report(SystemAcceptanceVerdict.fully_operational)
        d = report.to_dict()
        assert d.get("taxonomy_operational_status") == "fully_operational"

    def test_O06_critical_risk_operational_status_not_ready(self):
        report = self._make_report(
            SystemAcceptanceVerdict.not_fully_operational_critical_risk
        )
        d = report.to_dict()
        assert d.get("taxonomy_operational_status") == "not_ready"

    def test_O07_report_to_dict_has_taxonomy_alignment(self):
        report = self._make_report(SystemAcceptanceVerdict.fully_operational)
        d = report.to_dict()
        assert "taxonomy_alignment" in d
        assert "PR8" in d["taxonomy_alignment"]


# ===========================================================================
# Group P — Summary/report output terminology consistency
# ===========================================================================


class TestSummaryConsistency:
    @_skip_if_unavailable
    def test_P01_summary_uses_consistent_tags(self):
        registry = TerminologyRegistry()
        lines = registry.summary_lines()
        for line in lines:
            # Every line must have exactly one tag
            has_blocking = "[BLOCKING]" in line
            has_advisory = "[advisory]" in line
            assert has_blocking or has_advisory, f"Line missing tag: {line}"
            assert not (has_blocking and has_advisory), f"Line has both tags: {line}"

    @_skip_if_unavailable
    def test_P02_every_entry_must_not_confuse_with_non_empty(self):
        registry = TerminologyRegistry()
        for entry in registry.all_entries():
            assert len(entry.must_not_confuse_with) > 0, (
                f"Entry {entry.term.value} has empty must_not_confuse_with"
            )

    @_skip_if_unavailable
    def test_P03_must_not_confuse_with_contains_only_valid_terms(self):
        valid_terms = set(IssueClassification)
        registry = TerminologyRegistry()
        for entry in registry.all_entries():
            for term in entry.must_not_confuse_with:
                assert term in valid_terms, (
                    f"{entry.term.value}: invalid must_not_confuse_with term {term}"
                )

    @_skip_if_unavailable
    def test_P04_no_entry_confuses_itself(self):
        registry = TerminologyRegistry()
        for entry in registry.all_entries():
            assert entry.term not in entry.must_not_confuse_with, (
                f"{entry.term.value}: lists itself in must_not_confuse_with"
            )
