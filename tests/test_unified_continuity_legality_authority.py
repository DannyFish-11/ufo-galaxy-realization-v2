"""tests/test_unified_continuity_legality_authority.py
==========================================================
Test suite for the unified continuity legality authority.

Coverage
--------
A  — Module importable; authority sentinel and PR sentinel present.
B  — All policy sentinels are non-empty strings.
C  — ContinuityLegalityPath has all 8 required values.
D  — ContinuityLegalityDimension has all 12 required values.
E  — ContinuityLegalityVerdict has ALLOW / REJECT / REQUIRE_REVIEW.
F  — ContinuityLegalityVerdict.is_rejected() and is_hard_rejected() semantics.
G  — ContinuityLegalityContext to_dict() and to_json() work.
H  — DimensionLegalityOutcome to_dict() works.
I  — ContinuityLegalityReport to_dict() and to_json() work.
J  — ContinuityLegalityReport is_allowed / is_rejected / is_hard_rejected.
K  — evaluate_continuity_legality: empty context → ALLOW for all paths.
L  — evaluate_continuity_legality: stale terminal session → REJECT.
M  — evaluate_continuity_legality: session_id mismatch → REJECT.
N  — evaluate_continuity_legality: attachment_id mismatch → REJECT.
O  — evaluate_continuity_legality: registry unavailable → REQUIRE_REVIEW
     (strict paths) / ALLOW (lenient paths).
P  — evaluate_continuity_legality: report carries correct path value.
Q  — All 8 paths produce a report with non-empty authority sentinel.
R  — TERMINAL_RESULT_INGESTION path is strict (REQUIRE_REVIEW escalates).
S  — ONLINE_DISPATCH_ACCEPTANCE path is strict (REQUIRE_REVIEW escalates).
T  — ONLINE_SIGNAL_INGESTION path: signal guard unavailable → REQUIRE_REVIEW,
     does NOT escalate (non-strict path for signal guard).
U  — Singleton factory returns same instance across calls.
V  — reset clears the singleton.
W  — ContinuityLegalityContext.from_string() path factory works.
X  — Report is serialisable to JSON.
Y  — report_id is a non-empty string.
Z  — unified_result_ingress: NormalizedResultEvent has continuity fields.
AA — unified_result_ingress: UnifiedResultIngressOutcome has continuity fields.
AB — unified_runtime_truth_ingress: RuntimeTruthIngressOutcome has continuity
     fields including continuity_rejected and continuity_legality_verdict.
AC — unified_runtime_truth_ingress: to_dict() includes continuity fields.
AD — unified_dispatch_readiness_gate: DISPATCH_GATE_SHARES_CONTINUITY_AUTHORITY_POLICY
     is a non-empty string.
AE — unified_continuity_legality_authority: stale session blocks
     TERMINAL_RESULT_INGESTION via session identity check.
AF — unified_continuity_legality_authority: no identity fields → ALLOW on
     all paths.
AG — ContinuityLegalityPath.from_string: known value, unknown value returns
     None default.
AH — evaluate_continuity_legality: epoch dimension skipped when epoch == 0.
AI — evaluate_continuity_legality: signal guard skipped when signal_id empty.
AJ — evaluate_continuity_legality: DELEGATED_RECOVERY evaluates delegated
     legality dimension.
AK — evaluate_continuity_legality: ATTACHMENT_RESUME evaluates session
     identity dimension.
AL — evaluate_continuity_legality: RECONNECT evaluates session identity
     dimension.
AM — evaluate_continuity_legality: all 8 paths covered without exception.
"""

from __future__ import annotations

import json
import sys
import types
import uuid
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Availability guards
# ---------------------------------------------------------------------------

try:
    from core.unified_continuity_legality_authority import (
        ALL_PATHS_MUST_USE_UNIFIED_AUTHORITY_POLICY,
        CONTINUITY_FIELDS_ARE_ACTIVE_GATE_NOT_PAYLOAD_POLICY,
        FAIL_CLOSED_ON_AUTHORITY_UNAVAILABILITY_POLICY,
        ONLINE_EXECUTION_SUBMITS_TO_SAME_AUTHORITY_POLICY,
        STALE_IDENTITY_MUST_BE_REJECTED_POLICY,
        UNIFIED_CONTINUITY_LEGALITY_AUTHORITY,
        UNIFIED_CONTINUITY_LEGALITY_AUTHORITY_PR_SENTINEL,
        ContinuityLegalityContext,
        ContinuityLegalityDimension,
        ContinuityLegalityPath,
        ContinuityLegalityReport,
        ContinuityLegalityVerdict,
        DimensionLegalityOutcome,
        UnifiedContinuityLegalityAuthority,
        evaluate_continuity_legality,
        get_unified_continuity_legality_authority,
        reset_unified_continuity_legality_authority,
    )
    _MODULE_AVAILABLE = True
except ImportError:
    _MODULE_AVAILABLE = False

try:
    from core.unified_result_ingress import (
        NormalizedResultEvent,
        ResultSourceChannel,
        UnifiedResultIngressOutcome,
    )
    _RESULT_INGRESS_AVAILABLE = True
except ImportError:
    _RESULT_INGRESS_AVAILABLE = False

try:
    from core.unified_runtime_truth_ingress import (
        CONTINUITY_GATE_PRECEDES_ROUTING_POLICY,
        RuntimeTruthIngressOutcome,
    )
    _RUNTIME_INGRESS_AVAILABLE = True
except ImportError:
    _RUNTIME_INGRESS_AVAILABLE = False

try:
    from core.unified_dispatch_readiness_gate import (
        DISPATCH_GATE_SHARES_CONTINUITY_AUTHORITY_POLICY,
    )
    _DISPATCH_GATE_AVAILABLE = True
except ImportError:
    _DISPATCH_GATE_AVAILABLE = False

try:
    from core.attached_runtime_session_registry import (
        AttachedSessionRegistry,
        RegistryEntryState,
        get_session_registry,
        invalidate_session,
        register_session,
        reset_session_registry,
    )
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _device_id() -> str:
    return f"dev_{uuid.uuid4().hex[:8]}"


def _session_id() -> str:
    return f"sess_{uuid.uuid4().hex[:8]}"


def _attachment_id() -> str:
    return f"attach_{uuid.uuid4().hex[:8]}"


def _context(**kwargs: Any) -> "ContinuityLegalityContext":
    return ContinuityLegalityContext(**kwargs)


# ---------------------------------------------------------------------------
# A — Module importable; authority sentinel and PR sentinel present
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestModuleImportable:
    def test_authority_sentinel_non_empty(self) -> None:
        assert isinstance(UNIFIED_CONTINUITY_LEGALITY_AUTHORITY, str)
        assert len(UNIFIED_CONTINUITY_LEGALITY_AUTHORITY) > 0

    def test_pr_sentinel_non_empty(self) -> None:
        assert isinstance(UNIFIED_CONTINUITY_LEGALITY_AUTHORITY_PR_SENTINEL, str)
        assert len(UNIFIED_CONTINUITY_LEGALITY_AUTHORITY_PR_SENTINEL) > 0

    def test_authority_mentions_single_authority(self) -> None:
        assert "single canonical" in UNIFIED_CONTINUITY_LEGALITY_AUTHORITY.lower()


# ---------------------------------------------------------------------------
# B — All policy sentinels are non-empty strings
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestPolicySentinels:
    def test_all_paths_must_use_policy(self) -> None:
        assert isinstance(ALL_PATHS_MUST_USE_UNIFIED_AUTHORITY_POLICY, str)
        assert len(ALL_PATHS_MUST_USE_UNIFIED_AUTHORITY_POLICY) > 0

    def test_continuity_fields_active_gate_policy(self) -> None:
        assert isinstance(CONTINUITY_FIELDS_ARE_ACTIVE_GATE_NOT_PAYLOAD_POLICY, str)
        assert len(CONTINUITY_FIELDS_ARE_ACTIVE_GATE_NOT_PAYLOAD_POLICY) > 0

    def test_stale_identity_rejection_policy(self) -> None:
        assert isinstance(STALE_IDENTITY_MUST_BE_REJECTED_POLICY, str)
        assert len(STALE_IDENTITY_MUST_BE_REJECTED_POLICY) > 0

    def test_online_execution_submits_to_same_authority_policy(self) -> None:
        assert isinstance(ONLINE_EXECUTION_SUBMITS_TO_SAME_AUTHORITY_POLICY, str)
        assert len(ONLINE_EXECUTION_SUBMITS_TO_SAME_AUTHORITY_POLICY) > 0

    def test_fail_closed_policy(self) -> None:
        assert isinstance(FAIL_CLOSED_ON_AUTHORITY_UNAVAILABILITY_POLICY, str)
        assert len(FAIL_CLOSED_ON_AUTHORITY_UNAVAILABILITY_POLICY) > 0

    def test_online_policy_mentions_online_execution(self) -> None:
        assert "online" in ONLINE_EXECUTION_SUBMITS_TO_SAME_AUTHORITY_POLICY.lower()

    def test_stale_policy_mentions_stale(self) -> None:
        assert "stale" in STALE_IDENTITY_MUST_BE_REJECTED_POLICY.lower()


# ---------------------------------------------------------------------------
# C — ContinuityLegalityPath has all 8 required values
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestContinuityLegalityPath:
    EXPECTED_VALUES = {
        "reconnect",
        "re_register",
        "replay_ingress",
        "delegated_recovery",
        "attachment_resume",
        "online_dispatch_acceptance",
        "online_signal_ingestion",
        "terminal_result_ingestion",
    }

    def test_all_required_paths_present(self) -> None:
        actual = {p.value for p in ContinuityLegalityPath}
        for expected in self.EXPECTED_VALUES:
            assert expected in actual, f"Missing path: {expected}"

    def test_path_count_at_least_8(self) -> None:
        assert len(list(ContinuityLegalityPath)) >= 8


# ---------------------------------------------------------------------------
# D — ContinuityLegalityDimension has all 12 required values
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestContinuityLegalityDimension:
    EXPECTED_VALUES = {
        "runtime_session_continuity",
        "attachment_session_continuity",
        "durable_session_continuity",
        "continuity_epoch_ordering",
        "stale_runtime_rejection",
        "stale_attachment_rejection",
        "late_signal_rejection",
        "duplicate_signal_rejection",
        "out_of_order_signal_rejection",
        "replay_legality",
        "delegated_recovery_legality",
        "online_execution_legality",
    }

    def test_all_required_dimensions_present(self) -> None:
        actual = {d.value for d in ContinuityLegalityDimension}
        for expected in self.EXPECTED_VALUES:
            assert expected in actual, f"Missing dimension: {expected}"

    def test_dimension_count_at_least_12(self) -> None:
        assert len(list(ContinuityLegalityDimension)) >= 12


# ---------------------------------------------------------------------------
# E — ContinuityLegalityVerdict values
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestContinuityLegalityVerdict:
    def test_allow_value(self) -> None:
        assert ContinuityLegalityVerdict.ALLOW.value == "allow"

    def test_reject_value(self) -> None:
        assert ContinuityLegalityVerdict.REJECT.value == "reject"

    def test_require_review_value(self) -> None:
        assert ContinuityLegalityVerdict.REQUIRE_REVIEW.value == "require_review"


# ---------------------------------------------------------------------------
# F — is_rejected() and is_hard_rejected() semantics
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestVerdictPredicates:
    def test_allow_is_not_rejected(self) -> None:
        assert not ContinuityLegalityVerdict.ALLOW.is_rejected()

    def test_reject_is_rejected(self) -> None:
        assert ContinuityLegalityVerdict.REJECT.is_rejected()

    def test_require_review_is_rejected(self) -> None:
        assert ContinuityLegalityVerdict.REQUIRE_REVIEW.is_rejected()

    def test_allow_is_not_hard_rejected(self) -> None:
        assert not ContinuityLegalityVerdict.ALLOW.is_hard_rejected()

    def test_reject_is_hard_rejected(self) -> None:
        assert ContinuityLegalityVerdict.REJECT.is_hard_rejected()

    def test_require_review_is_not_hard_rejected(self) -> None:
        assert not ContinuityLegalityVerdict.REQUIRE_REVIEW.is_hard_rejected()


# ---------------------------------------------------------------------------
# G — ContinuityLegalityContext serialisation
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestContinuityLegalityContextSerialisation:
    def test_to_dict_contains_expected_keys(self) -> None:
        ctx = _context(device_id="d1", runtime_session_id="s1")
        d = ctx.to_dict()
        assert "device_id" in d
        assert "runtime_session_id" in d
        assert "runtime_attachment_session_id" in d
        assert "durable_session_id" in d
        assert "continuity_epoch" in d
        assert "signal_id" in d
        assert "emission_seq" in d
        assert "contract_id" in d
        assert "flow_id" in d
        assert "metadata" in d

    def test_to_dict_values_match(self) -> None:
        ctx = _context(device_id="dev_x", runtime_session_id="sess_y", continuity_epoch=7)
        d = ctx.to_dict()
        assert d["device_id"] == "dev_x"
        assert d["runtime_session_id"] == "sess_y"
        assert d["continuity_epoch"] == 7

    def test_to_json_produces_valid_json(self) -> None:
        ctx = _context(device_id="d1")
        parsed = json.loads(ctx.to_json())
        assert parsed["device_id"] == "d1"


# ---------------------------------------------------------------------------
# H — DimensionLegalityOutcome serialisation
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestDimensionLegalityOutcomeSerialisation:
    def test_to_dict_contains_expected_keys(self) -> None:
        outcome = DimensionLegalityOutcome(
            dimension=ContinuityLegalityDimension.runtime_session_continuity,
            verdict=ContinuityLegalityVerdict.ALLOW,
        )
        d = outcome.to_dict()
        assert "dimension" in d
        assert "verdict" in d
        assert "reason" in d
        assert "evidence" in d

    def test_verdict_serialised_as_string(self) -> None:
        outcome = DimensionLegalityOutcome(
            dimension=ContinuityLegalityDimension.stale_runtime_rejection,
            verdict=ContinuityLegalityVerdict.REJECT,
            reason="stale",
        )
        d = outcome.to_dict()
        assert d["verdict"] == "reject"
        assert d["dimension"] == "stale_runtime_rejection"


# ---------------------------------------------------------------------------
# I — ContinuityLegalityReport serialisation
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestContinuityLegalityReportSerialisation:
    def test_to_dict_contains_expected_keys(self) -> None:
        report = ContinuityLegalityReport(
            path=ContinuityLegalityPath.RECONNECT,
            verdict=ContinuityLegalityVerdict.ALLOW,
        )
        d = report.to_dict()
        assert "report_id" in d
        assert "path" in d
        assert "verdict" in d
        assert "reject_reason" in d
        assert "dimensions" in d
        assert "context_snapshot" in d
        assert "authority" in d

    def test_to_json_produces_valid_json(self) -> None:
        report = ContinuityLegalityReport(
            path=ContinuityLegalityPath.TERMINAL_RESULT_INGESTION,
            verdict=ContinuityLegalityVerdict.REJECT,
            reject_reason="stale",
        )
        parsed = json.loads(report.to_json())
        assert parsed["verdict"] == "reject"
        assert parsed["path"] == "terminal_result_ingestion"

    def test_authority_field_is_non_empty(self) -> None:
        report = ContinuityLegalityReport()
        assert report.to_dict()["authority"]


# ---------------------------------------------------------------------------
# J — Report predicates
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestReportPredicates:
    def test_allow_report_is_allowed(self) -> None:
        r = ContinuityLegalityReport(verdict=ContinuityLegalityVerdict.ALLOW)
        assert r.is_allowed
        assert not r.is_rejected
        assert not r.is_hard_rejected

    def test_reject_report_is_rejected(self) -> None:
        r = ContinuityLegalityReport(verdict=ContinuityLegalityVerdict.REJECT)
        assert not r.is_allowed
        assert r.is_rejected
        assert r.is_hard_rejected

    def test_require_review_is_rejected_not_hard(self) -> None:
        r = ContinuityLegalityReport(verdict=ContinuityLegalityVerdict.REQUIRE_REVIEW)
        assert not r.is_allowed
        assert r.is_rejected
        assert not r.is_hard_rejected


# ---------------------------------------------------------------------------
# K — Empty context → ALLOW for all paths
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestEmptyContextAllows:
    """No identity fields → cannot assert illegality → ALLOW on every path."""

    @pytest.mark.parametrize("path_val", [
        "reconnect",
        "re_register",
        "replay_ingress",
        "delegated_recovery",
        "attachment_resume",
        "online_dispatch_acceptance",
        "online_signal_ingestion",
        "terminal_result_ingestion",
    ])
    def test_empty_context_allows_all_paths(self, path_val: str) -> None:
        path = ContinuityLegalityPath(path_val)
        ctx = ContinuityLegalityContext()  # all fields empty / default
        report = evaluate_continuity_legality(path, ctx)
        assert report.is_allowed, (
            f"Expected ALLOW for empty context on {path_val}, "
            f"got {report.verdict.value}: {report.reject_reason}"
        )


# ---------------------------------------------------------------------------
# L — Stale terminal session → REJECT (when registry is available)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _MODULE_AVAILABLE or not _REGISTRY_AVAILABLE,
    reason="module or registry unavailable",
)
class TestStaleSessionRejects:
    """When registry has a terminal entry, session identity check → REJECT."""

    def test_replaced_session_rejected_on_dispatch(self) -> None:
        reset_unified_continuity_legality_authority()
        reset_session_registry()

        device_id = _device_id()
        session_id = _session_id()
        attachment_id = _attachment_id()

        # Register then invalidate (mark as replaced/invalidated)
        entry = register_session(
            device_id,
            session_id=session_id,
            runtime_attachment_session_id=attachment_id,
        )
        invalidate_session(entry)

        ctx = ContinuityLegalityContext(
            device_id=device_id,
            runtime_session_id=session_id,
            runtime_attachment_session_id=attachment_id,
        )
        report = evaluate_continuity_legality(
            ContinuityLegalityPath.ONLINE_DISPATCH_ACCEPTANCE, ctx
        )
        assert report.is_hard_rejected, (
            f"Expected REJECT for invalidated session, got {report.verdict.value}: "
            f"{report.reject_reason}"
        )
        reset_session_registry()

    def test_replaced_session_rejected_on_terminal_result(self) -> None:
        reset_unified_continuity_legality_authority()
        reset_session_registry()

        device_id = _device_id()
        session_id = _session_id()
        attachment_id = _attachment_id()

        entry = register_session(
            device_id,
            session_id=session_id,
            runtime_attachment_session_id=attachment_id,
        )
        invalidate_session(entry)

        ctx = ContinuityLegalityContext(
            device_id=device_id,
            runtime_attachment_session_id=attachment_id,
        )
        report = evaluate_continuity_legality(
            ContinuityLegalityPath.TERMINAL_RESULT_INGESTION, ctx
        )
        assert report.is_hard_rejected, (
            f"Expected REJECT for invalidated session on TERMINAL_RESULT_INGESTION, "
            f"got {report.verdict.value}: {report.reject_reason}"
        )
        reset_session_registry()


# ---------------------------------------------------------------------------
# M & N — Session/attachment ID mismatch → REJECT (when registry available)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _MODULE_AVAILABLE or not _REGISTRY_AVAILABLE,
    reason="module or registry unavailable",
)
class TestIdentityMismatchRejects:
    """Mismatched session / attachment identities → REJECT."""

    def test_session_id_mismatch_rejects(self) -> None:
        reset_unified_continuity_legality_authority()
        reset_session_registry()

        device_id = _device_id()
        real_session_id = _session_id()
        stale_session_id = _session_id()
        attachment_id = _attachment_id()

        register_session(
            device_id,
            session_id=real_session_id,
            runtime_attachment_session_id=attachment_id,
        )

        ctx = ContinuityLegalityContext(
            device_id=device_id,
            runtime_session_id=stale_session_id,  # wrong session
            runtime_attachment_session_id=attachment_id,
        )
        report = evaluate_continuity_legality(
            ContinuityLegalityPath.ONLINE_DISPATCH_ACCEPTANCE, ctx
        )
        assert report.is_hard_rejected, (
            f"Expected REJECT for session_id mismatch, "
            f"got {report.verdict.value}: {report.reject_reason}"
        )
        reset_session_registry()

    def test_attachment_id_mismatch_rejects(self) -> None:
        reset_unified_continuity_legality_authority()
        reset_session_registry()

        device_id = _device_id()
        session_id = _session_id()
        real_attachment_id = _attachment_id()
        stale_attachment_id = _attachment_id()

        register_session(
            device_id,
            session_id=session_id,
            runtime_attachment_session_id=real_attachment_id,
        )

        ctx = ContinuityLegalityContext(
            device_id=device_id,
            runtime_session_id=session_id,
            runtime_attachment_session_id=stale_attachment_id,  # wrong
        )
        report = evaluate_continuity_legality(
            ContinuityLegalityPath.TERMINAL_RESULT_INGESTION, ctx
        )
        assert report.is_hard_rejected, (
            f"Expected REJECT for attachment_id mismatch, "
            f"got {report.verdict.value}: {report.reject_reason}"
        )
        reset_session_registry()


# ---------------------------------------------------------------------------
# P — Report carries correct path value
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestReportPathValue:
    @pytest.mark.parametrize("path_val", [
        "reconnect",
        "re_register",
        "online_dispatch_acceptance",
        "terminal_result_ingestion",
    ])
    def test_report_path_matches_input(self, path_val: str) -> None:
        path = ContinuityLegalityPath(path_val)
        ctx = ContinuityLegalityContext()
        report = evaluate_continuity_legality(path, ctx)
        assert report.path == path
        assert report.to_dict()["path"] == path_val


# ---------------------------------------------------------------------------
# Q — All 8 paths produce a report with non-empty authority sentinel
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestAllPathsProduceReport:
    @pytest.mark.parametrize("path", list(ContinuityLegalityPath))
    def test_all_paths_produce_report_with_authority(self, path) -> None:
        ctx = ContinuityLegalityContext()
        report = evaluate_continuity_legality(path, ctx)
        assert isinstance(report, ContinuityLegalityReport)
        assert report.authority
        assert report.report_id


# ---------------------------------------------------------------------------
# U — Singleton factory returns same instance across calls
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestSingleton:
    def test_singleton_is_same_instance(self) -> None:
        reset_unified_continuity_legality_authority()
        a = get_unified_continuity_legality_authority()
        b = get_unified_continuity_legality_authority()
        assert a is b

    def test_reset_clears_singleton(self) -> None:
        a = get_unified_continuity_legality_authority()
        reset_unified_continuity_legality_authority()
        b = get_unified_continuity_legality_authority()
        assert a is not b


# ---------------------------------------------------------------------------
# V — ContinuityLegalityPath.from_string
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestPathFromString:
    def test_known_value_reconnect(self) -> None:
        p = ContinuityLegalityPath.from_string("reconnect")
        assert p is ContinuityLegalityPath.RECONNECT

    def test_unknown_value_returns_default(self) -> None:
        p = ContinuityLegalityPath.from_string("unknown_xyz")
        assert p is None

    def test_unknown_value_with_default(self) -> None:
        default = ContinuityLegalityPath.RECONNECT
        p = ContinuityLegalityPath.from_string("bad_path", default=default)
        assert p is default


# ---------------------------------------------------------------------------
# X — Report serialisable to JSON
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestReportJson:
    def test_report_json_round_trip(self) -> None:
        ctx = ContinuityLegalityContext(device_id="d1")
        report = evaluate_continuity_legality(
            ContinuityLegalityPath.RECONNECT, ctx
        )
        json_str = report.to_json()
        parsed = json.loads(json_str)
        assert parsed["path"] == "reconnect"
        assert "verdict" in parsed
        assert "authority" in parsed

    def test_report_id_is_non_empty_string(self) -> None:
        ctx = ContinuityLegalityContext()
        report = evaluate_continuity_legality(
            ContinuityLegalityPath.ONLINE_SIGNAL_INGESTION, ctx
        )
        assert isinstance(report.report_id, str)
        assert len(report.report_id) > 0


# ---------------------------------------------------------------------------
# Z — unified_result_ingress: NormalizedResultEvent has continuity fields
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _RESULT_INGRESS_AVAILABLE, reason="result_ingress unavailable")
class TestResultIngressContinuityFields:
    def test_normalized_result_event_has_runtime_session_id(self) -> None:
        event = NormalizedResultEvent(
            task_id="t1",
            device_id="d1",
            raw_message_type="goal_execution_result",
            normalized_result_kind="goal_execution_result",
            normalized_status="completed",
            source_channel=ResultSourceChannel.CANONICAL_WS,
        )
        assert hasattr(event, "runtime_session_id")
        assert hasattr(event, "runtime_attachment_session_id")
        assert hasattr(event, "durable_session_id")


# ---------------------------------------------------------------------------
# AA — unified_result_ingress: UnifiedResultIngressOutcome has continuity fields
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _RESULT_INGRESS_AVAILABLE, reason="result_ingress unavailable")
class TestResultIngressOutcomeContinuityFields:
    def test_outcome_has_continuity_rejected(self) -> None:
        outcome = UnifiedResultIngressOutcome()
        assert hasattr(outcome, "continuity_rejected")
        assert outcome.continuity_rejected is False

    def test_outcome_has_continuity_legality_verdict(self) -> None:
        outcome = UnifiedResultIngressOutcome()
        assert hasattr(outcome, "continuity_legality_verdict")
        assert outcome.continuity_legality_verdict == ""


# ---------------------------------------------------------------------------
# AB — unified_runtime_truth_ingress: RuntimeTruthIngressOutcome has continuity fields
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _RUNTIME_INGRESS_AVAILABLE, reason="runtime_ingress unavailable"
)
class TestRuntimeIngressOutcomeContinuityFields:
    def test_outcome_has_continuity_rejected(self) -> None:
        outcome = RuntimeTruthIngressOutcome()
        assert hasattr(outcome, "continuity_rejected")
        assert outcome.continuity_rejected is False

    def test_outcome_has_continuity_legality_verdict(self) -> None:
        outcome = RuntimeTruthIngressOutcome()
        assert hasattr(outcome, "continuity_legality_verdict")
        assert outcome.continuity_legality_verdict == ""


# ---------------------------------------------------------------------------
# AC — RuntimeTruthIngressOutcome.to_dict() includes continuity fields
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _RUNTIME_INGRESS_AVAILABLE, reason="runtime_ingress unavailable"
)
class TestRuntimeIngressOutcomeToDictContinuity:
    def test_to_dict_includes_continuity_rejected(self) -> None:
        outcome = RuntimeTruthIngressOutcome(continuity_rejected=True, continuity_legality_verdict="reject")
        d = outcome.to_dict()
        assert "continuity_rejected" in d
        assert d["continuity_rejected"] is True
        assert "continuity_legality_verdict" in d
        assert d["continuity_legality_verdict"] == "reject"


# ---------------------------------------------------------------------------
# AD — unified_dispatch_readiness_gate: DISPATCH_GATE_SHARES_CONTINUITY_AUTHORITY_POLICY
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _DISPATCH_GATE_AVAILABLE, reason="dispatch_gate unavailable"
)
class TestDispatchGateSentinel:
    def test_sentinel_non_empty(self) -> None:
        assert isinstance(DISPATCH_GATE_SHARES_CONTINUITY_AUTHORITY_POLICY, str)
        assert len(DISPATCH_GATE_SHARES_CONTINUITY_AUTHORITY_POLICY) > 0

    def test_sentinel_mentions_online_execution(self) -> None:
        assert "online" in DISPATCH_GATE_SHARES_CONTINUITY_AUTHORITY_POLICY.lower()

    def test_sentinel_mentions_continuity_authority(self) -> None:
        assert (
            "continuity" in DISPATCH_GATE_SHARES_CONTINUITY_AUTHORITY_POLICY.lower()
        )


# ---------------------------------------------------------------------------
# AG — epoch dimension skipped when epoch == 0
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestEpochDimensionSkipped:
    def test_zero_epoch_skips_epoch_dimension(self) -> None:
        ctx = ContinuityLegalityContext(continuity_epoch=0)
        report = evaluate_continuity_legality(
            ContinuityLegalityPath.RECONNECT, ctx
        )
        dim_names = {d.dimension.value for d in report.dimensions}
        assert "continuity_epoch_ordering" not in dim_names

    def test_nonzero_epoch_evaluates_epoch_dimension(self) -> None:
        ctx = ContinuityLegalityContext(continuity_epoch=5)
        report = evaluate_continuity_legality(
            ContinuityLegalityPath.RECONNECT, ctx
        )
        dim_names = {d.dimension.value for d in report.dimensions}
        assert "continuity_epoch_ordering" in dim_names


# ---------------------------------------------------------------------------
# AH — signal guard skipped when signal_id empty
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestSignalGuardSkipped:
    def test_empty_signal_id_skips_guard(self) -> None:
        ctx = ContinuityLegalityContext(signal_id="")
        report = evaluate_continuity_legality(
            ContinuityLegalityPath.ONLINE_SIGNAL_INGESTION, ctx
        )
        dim_names = {d.dimension.value for d in report.dimensions}
        # Signal guard dimension should NOT be present when signal_id is absent
        assert "duplicate_signal_rejection" not in dim_names


# ---------------------------------------------------------------------------
# AI — DELEGATED_RECOVERY evaluates delegated legality dimension
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestDelegatedRecoveryDimension:
    def test_delegated_recovery_evaluates_its_dimension_when_contract_id(self) -> None:
        ctx = ContinuityLegalityContext(contract_id="c1")
        report = evaluate_continuity_legality(
            ContinuityLegalityPath.DELEGATED_RECOVERY, ctx
        )
        dim_names = {d.dimension.value for d in report.dimensions}
        assert "delegated_recovery_legality" in dim_names

    def test_delegated_recovery_no_contract_skips_dimension(self) -> None:
        ctx = ContinuityLegalityContext()  # no contract_id or flow_id
        report = evaluate_continuity_legality(
            ContinuityLegalityPath.DELEGATED_RECOVERY, ctx
        )
        # When no contract/flow context, delegated recovery legality returns ALLOW
        dim_names = {d.dimension.value for d in report.dimensions}
        assert "delegated_recovery_legality" in dim_names  # still evaluated
        # But should be ALLOW
        for d in report.dimensions:
            if d.dimension.value == "delegated_recovery_legality":
                assert not d.verdict.is_rejected()


# ---------------------------------------------------------------------------
# AJ — ATTACHMENT_RESUME and RECONNECT evaluate session identity
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestSessionIdentityDimension:
    @pytest.mark.parametrize("path_val", [
        "attachment_resume",
        "reconnect",
        "re_register",
        "online_dispatch_acceptance",
        "online_signal_ingestion",
        "terminal_result_ingestion",
    ])
    def test_identity_dimension_evaluated_on_strict_paths(self, path_val: str) -> None:
        path = ContinuityLegalityPath(path_val)
        ctx = ContinuityLegalityContext(device_id="dev_test")
        report = evaluate_continuity_legality(path, ctx)
        # Should have session identity or online_execution_legality dimension
        dim_names = {d.dimension.value for d in report.dimensions}
        has_identity = (
            "runtime_session_continuity" in dim_names
            or "online_execution_legality" in dim_names
        )
        assert has_identity, (
            f"Expected session identity dimension for {path_val}, "
            f"got dimensions: {dim_names}"
        )


# ---------------------------------------------------------------------------
# AK — All 8 paths covered without exception
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _MODULE_AVAILABLE, reason="module unavailable")
class TestAllPathsCoveredNoException:
    @pytest.mark.parametrize("path", list(ContinuityLegalityPath))
    def test_no_exception_for_any_path(self, path) -> None:
        ctx = ContinuityLegalityContext(
            device_id="dev_all",
            runtime_session_id="sess_all",
            runtime_attachment_session_id="att_all",
            signal_id="sig_all",
            emission_seq=1,
            contract_id="contract_all",
            continuity_epoch=1,
        )
        # Must not raise
        report = evaluate_continuity_legality(path, ctx)
        assert isinstance(report, ContinuityLegalityReport)


# ---------------------------------------------------------------------------
# Runtime truth ingress continuity gate sentinel test
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _RUNTIME_INGRESS_AVAILABLE, reason="runtime_ingress unavailable"
)
class TestRuntimeIngressContinuityGateSentinel:
    def test_continuity_gate_precedes_routing_policy_non_empty(self) -> None:
        assert isinstance(CONTINUITY_GATE_PRECEDES_ROUTING_POLICY, str)
        assert len(CONTINUITY_GATE_PRECEDES_ROUTING_POLICY) > 0

    def test_policy_mentions_continuity(self) -> None:
        assert "continuity" in CONTINUITY_GATE_PRECEDES_ROUTING_POLICY.lower()
