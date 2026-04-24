"""tests/test_pr8v2_android_result_normalizer.py
================================================
Tests for PR-08-V2: Unified Android Result Normalization and Canonical
Reconciliation Entry Point.

Validates:

Group A — Policy sentinels and PR sentinel are present and well-formed.
Group B — AndroidResultCategory enum: all required values, no regressions.
Group C — _MESSAGE_TYPE_TO_CATEGORY: all 9 expected message types are mapped.
Group D — classify_android_result_message: correct category per message type.
Group E — Terminal-state deduplication guard: isolate, commit, hit behaviour.
Group F — AndroidResultNormalizerOutcome: construction, defaults, to_dict(),
           is_accepted().
Group G — normalize_android_result: unknown message type → rejected outcome.
Group H — normalize_android_result: result-only path (task_result →
           participant truth).
Group I — normalize_android_result: result-only path (goal_execution_result →
           participant truth).
Group J — normalize_android_result: signal-only path
           (delegated_execution_signal → delegated signal ingress).
Group K — normalize_android_result: handoff path
           (handoff_result → handoff response ingress).
Group L — normalize_android_result: reconciliation_signal → participant truth.
Group M — normalize_android_result: result + reconciliation_signal dedup —
           second terminal signal for same identity is deduplicated.
Group N — goal_execution.py: _try_ingest_goal_result_truth is present and
           called during handle_goal_execution_result.
Group O — normalize_android_result: missing identity key → no dedup guard hit.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import guards
# ---------------------------------------------------------------------------

try:
    from core.android_result_normalizer import (
        ADDITIVE_NON_DESTRUCTIVE_NORMALIZER_POLICY,
        ANDROID_RESULT_NORMALIZER_AUTHORITY,
        ANDROID_RESULT_NORMALIZER_PR8V2_SENTINEL,
        CATEGORY_BOUNDARY_IS_AUTHORITATIVE_POLICY,
        HANDOFF_RESPONSE_ROUTES_VIA_RESPONSE_INGRESS_POLICY,
        PARTICIPANT_TRUTH_IS_CONVERGENCE_TARGET_POLICY,
        TERMINAL_DEDUP_PREVENTS_DOUBLE_ACCOUNTING_POLICY,
        UNIFIED_NORMALIZATION_ENTRY_POLICY,
        AndroidResultCategory,
        AndroidResultNormalizerOutcome,
        _committed_terminal_identities,
        _extract_identity_key,
        classify_android_result_message,
        normalize_android_result,
        reset_terminal_dedup_guard,
    )

    _MODULE_AVAILABLE = True
except ImportError:
    _MODULE_AVAILABLE = False

_SKIP = pytest.mark.skipif(not _MODULE_AVAILABLE, reason="android_result_normalizer unavailable")

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _msg(
    msg_type: str,
    contract_id: str = "",
    session_id: str = "",
    device_id: str = "device_test",
    message_id: str = "",
) -> Dict[str, Any]:
    """Build a minimal AIP-style message dict."""
    payload: Dict[str, Any] = {}
    if contract_id:
        payload["contract_id"] = contract_id
    if session_id:
        payload["session_id"] = session_id
    return {
        "version": "3.0",
        "type": msg_type,
        "device_id": device_id,
        "message_id": message_id or str(uuid.uuid4()),
        "payload": payload,
    }


def _make_accepted_participant_truth_outcome(contract_id: str = "") -> MagicMock:
    """Return a mock participant truth outcome that was_reconciled=True, terminal."""
    outcome = MagicMock()
    outcome.was_reconciled = True
    outcome.reject_reason = ""
    outcome.canonical_update = "terminal state applied"
    outcome.tracking_record_phase = "completed"
    env = MagicMock()
    truth_kind_mock = MagicMock()
    truth_kind_mock.value = "result"
    env.truth_kind = truth_kind_mock
    env.contract_id = contract_id
    env.session_id = ""
    outcome.envelope = env
    outcome.to_dict = lambda: {"was_reconciled": True}
    return outcome


def _make_accepted_signal_reconcile_outcome(phase_terminal: bool = True) -> MagicMock:
    """Return a mock delegated signal reconcile outcome."""
    outcome = MagicMock()
    outcome.was_updated = True
    outcome.reject_reason = ""
    record = MagicMock()
    phase = MagicMock()
    phase.is_terminal = lambda: phase_terminal
    record.phase = phase
    outcome.record = record
    env = MagicMock()
    env.signal_kind = MagicMock()
    env.signal_kind.value = "result"
    env.contract_id = ""
    outcome.envelope = env
    outcome.to_dict = lambda: {"was_updated": True}
    return outcome


def _make_accepted_handoff_outcome(kind: str = "result") -> MagicMock:
    """Return a mock handoff response outcome."""
    outcome = MagicMock()
    outcome.was_correlated = True
    outcome.reject_reason = ""
    env = MagicMock()
    env.response_kind = kind
    outcome.envelope = env
    outcome.to_dict = lambda: {"was_correlated": True}
    return outcome


# ============================================================================
# Group A — Policy sentinels
# ============================================================================


@_SKIP
class TestGroupA_PolicySentinels:

    def test_A01_pr_sentinel_present(self) -> None:
        assert ANDROID_RESULT_NORMALIZER_PR8V2_SENTINEL
        assert "PR8V2" in ANDROID_RESULT_NORMALIZER_PR8V2_SENTINEL

    def test_A02_authority_present(self) -> None:
        assert ANDROID_RESULT_NORMALIZER_AUTHORITY
        assert "android_result_normalizer" in ANDROID_RESULT_NORMALIZER_AUTHORITY

    def test_A03_unified_normalization_entry_policy(self) -> None:
        assert UNIFIED_NORMALIZATION_ENTRY_POLICY
        assert "normalize_android_result" in UNIFIED_NORMALIZATION_ENTRY_POLICY

    def test_A04_category_boundary_policy(self) -> None:
        assert CATEGORY_BOUNDARY_IS_AUTHORITATIVE_POLICY
        assert "AndroidResultCategory" in CATEGORY_BOUNDARY_IS_AUTHORITATIVE_POLICY

    def test_A05_terminal_dedup_policy(self) -> None:
        assert TERMINAL_DEDUP_PREVENTS_DOUBLE_ACCOUNTING_POLICY
        assert "dedup" in TERMINAL_DEDUP_PREVENTS_DOUBLE_ACCOUNTING_POLICY.lower()

    def test_A06_participant_truth_convergence_policy(self) -> None:
        assert PARTICIPANT_TRUTH_IS_CONVERGENCE_TARGET_POLICY
        policy_lower = PARTICIPANT_TRUTH_IS_CONVERGENCE_TARGET_POLICY.lower()
        assert "participant_truth" in policy_lower or "participant truth" in policy_lower

    def test_A07_handoff_response_routing_policy(self) -> None:
        assert HANDOFF_RESPONSE_ROUTES_VIA_RESPONSE_INGRESS_POLICY
        assert "handoff" in HANDOFF_RESPONSE_ROUTES_VIA_RESPONSE_INGRESS_POLICY.lower()

    def test_A08_additive_non_destructive_policy(self) -> None:
        assert ADDITIVE_NON_DESTRUCTIVE_NORMALIZER_POLICY
        assert "additive" in ADDITIVE_NON_DESTRUCTIVE_NORMALIZER_POLICY.lower()


# ============================================================================
# Group B — AndroidResultCategory enum
# ============================================================================


@_SKIP
class TestGroupB_AndroidResultCategory:

    def test_B01_user_visible_business_result(self) -> None:
        assert AndroidResultCategory.user_visible_business_result.value == "user_visible_business_result"

    def test_B02_runtime_lifecycle_signal(self) -> None:
        assert AndroidResultCategory.runtime_lifecycle_signal.value == "runtime_lifecycle_signal"

    def test_B03_reconciliation_authoritative_update(self) -> None:
        assert AndroidResultCategory.reconciliation_authoritative_update.value == "reconciliation_authoritative_update"

    def test_B04_unknown(self) -> None:
        assert AndroidResultCategory.unknown.value == "unknown"

    def test_B05_all_categories_accessible(self) -> None:
        cats = {c.value for c in AndroidResultCategory}
        assert "user_visible_business_result" in cats
        assert "runtime_lifecycle_signal" in cats
        assert "reconciliation_authoritative_update" in cats
        assert "unknown" in cats


# ============================================================================
# Group C — Message type to category mapping
# ============================================================================


@_SKIP
class TestGroupC_MessageTypeCategoryMapping:

    def test_C01_task_result_is_business_result(self) -> None:
        assert classify_android_result_message({"type": "task_result"}) == \
               AndroidResultCategory.user_visible_business_result

    def test_C02_goal_execution_result_is_business_result(self) -> None:
        assert classify_android_result_message({"type": "goal_execution_result"}) == \
               AndroidResultCategory.user_visible_business_result

    def test_C03_delegated_execution_signal_is_lifecycle(self) -> None:
        assert classify_android_result_message({"type": "delegated_execution_signal"}) == \
               AndroidResultCategory.runtime_lifecycle_signal

    def test_C04_reconciliation_signal_is_authoritative_update(self) -> None:
        assert classify_android_result_message({"type": "reconciliation_signal"}) == \
               AndroidResultCategory.reconciliation_authoritative_update

    def test_C05_handoff_ack_is_authoritative_update(self) -> None:
        assert classify_android_result_message({"type": "handoff_ack"}) == \
               AndroidResultCategory.reconciliation_authoritative_update

    def test_C06_handoff_result_is_authoritative_update(self) -> None:
        assert classify_android_result_message({"type": "handoff_result"}) == \
               AndroidResultCategory.reconciliation_authoritative_update

    def test_C07_handoff_failure_is_authoritative_update(self) -> None:
        assert classify_android_result_message({"type": "handoff_failure"}) == \
               AndroidResultCategory.reconciliation_authoritative_update

    def test_C08_handoff_envelope_v2_result_is_authoritative_update(self) -> None:
        assert classify_android_result_message({"type": "handoff_envelope_v2_result"}) == \
               AndroidResultCategory.reconciliation_authoritative_update

    def test_C09_unknown_type_returns_unknown(self) -> None:
        assert classify_android_result_message({"type": "some_unknown_type"}) == \
               AndroidResultCategory.unknown

    def test_C10_missing_type_returns_unknown(self) -> None:
        assert classify_android_result_message({}) == AndroidResultCategory.unknown


# ============================================================================
# Group D — classify_android_result_message: case handling
# ============================================================================


@_SKIP
class TestGroupD_ClassifyMessage:

    def test_D01_case_sensitive_type_field(self) -> None:
        # Type values are lowercased before lookup; mixed case should match
        assert classify_android_result_message({"type": "TASK_RESULT"}) == \
               AndroidResultCategory.user_visible_business_result

    def test_D02_whitespace_stripped(self) -> None:
        assert classify_android_result_message({"type": " task_result "}) == \
               AndroidResultCategory.user_visible_business_result

    def test_D03_none_type_returns_unknown(self) -> None:
        assert classify_android_result_message({"type": None}) == AndroidResultCategory.unknown


# ============================================================================
# Group E — Terminal-state deduplication guard
# ============================================================================


@_SKIP
class TestGroupE_DedupGuard:

    def setup_method(self) -> None:
        reset_terminal_dedup_guard()

    def test_E01_reset_clears_guard(self) -> None:
        from core.android_result_normalizer import _dedup_commit, _dedup_is_committed
        _dedup_commit("contract:abc", "task_result")
        assert _dedup_is_committed("contract:abc")
        reset_terminal_dedup_guard()
        assert not _dedup_is_committed("contract:abc")

    def test_E02_commit_then_hit(self) -> None:
        from core.android_result_normalizer import _dedup_commit, _dedup_is_committed
        key = "contract:" + str(uuid.uuid4())
        assert not _dedup_is_committed(key)
        _dedup_commit(key, "task_result")
        assert _dedup_is_committed(key)

    def test_E03_empty_key_never_commits(self) -> None:
        from core.android_result_normalizer import _dedup_commit, _dedup_is_committed
        _dedup_commit("", "task_result")
        assert not _dedup_is_committed("")

    def test_E04_extract_identity_key_prefers_contract_id(self) -> None:
        msg = {
            "payload": {"contract_id": "cid-abc", "session_id": "sid-xyz"},
        }
        key = _extract_identity_key(msg)
        assert key == "contract:cid-abc"

    def test_E05_extract_identity_key_falls_back_to_session_id(self) -> None:
        msg = {"payload": {"session_id": "sid-xyz"}}
        key = _extract_identity_key(msg)
        assert key == "session:sid-xyz"

    def test_E06_extract_identity_key_top_level_contract_id(self) -> None:
        msg = {"contract_id": "top-cid", "payload": {}}
        key = _extract_identity_key(msg)
        assert key == "contract:top-cid"

    def test_E07_extract_identity_key_empty_when_no_key(self) -> None:
        key = _extract_identity_key({"type": "task_result"})
        assert key == ""


# ============================================================================
# Group F — AndroidResultNormalizerOutcome
# ============================================================================


@_SKIP
class TestGroupF_Outcome:

    def test_F01_default_construction(self) -> None:
        outcome = AndroidResultNormalizerOutcome()
        assert outcome.message_type == ""
        assert outcome.category == AndroidResultCategory.unknown
        assert outcome.was_normalized is False
        assert outcome.was_deduplicated is False
        assert outcome.reject_reason == ""
        assert outcome.participant_truth_outcome is None
        assert outcome.signal_reconcile_outcome is None
        assert outcome.handoff_response_outcome is None

    def test_F02_is_accepted_true(self) -> None:
        outcome = AndroidResultNormalizerOutcome(
            message_type="task_result",
            was_normalized=True,
            reject_reason="",
        )
        assert outcome.is_accepted() is True

    def test_F03_is_accepted_false_when_not_normalized(self) -> None:
        outcome = AndroidResultNormalizerOutcome(was_normalized=False)
        assert outcome.is_accepted() is False

    def test_F04_is_accepted_false_when_reject_reason(self) -> None:
        outcome = AndroidResultNormalizerOutcome(
            was_normalized=True,
            reject_reason="some_reason",
        )
        assert outcome.is_accepted() is False

    def test_F05_to_dict_contains_expected_keys(self) -> None:
        outcome = AndroidResultNormalizerOutcome(
            message_type="task_result",
            category=AndroidResultCategory.user_visible_business_result,
            was_normalized=True,
        )
        d = outcome.to_dict()
        assert d["message_type"] == "task_result"
        assert d["category"] == "user_visible_business_result"
        assert d["was_normalized"] is True
        assert "was_deduplicated" in d
        assert "reject_reason" in d
        assert "normalizer_envelope_id" in d

    def test_F06_normalizer_envelope_id_is_unique(self) -> None:
        o1 = AndroidResultNormalizerOutcome()
        o2 = AndroidResultNormalizerOutcome()
        assert o1.normalizer_envelope_id != o2.normalizer_envelope_id


# ============================================================================
# Group G — normalize_android_result: unknown type
# ============================================================================


@_SKIP
class TestGroupG_UnknownType:

    def setup_method(self) -> None:
        reset_terminal_dedup_guard()

    def test_G01_unknown_type_returns_rejected_outcome(self) -> None:
        msg = _msg("some_unrecognised_type")
        outcome = normalize_android_result(msg)
        assert outcome.was_normalized is False
        assert outcome.category == AndroidResultCategory.unknown
        assert "unknown_message_type" in outcome.reject_reason

    def test_G02_missing_type_rejected(self) -> None:
        outcome = normalize_android_result({})
        assert outcome.was_normalized is False

    def test_G03_unknown_type_not_deduplicated(self) -> None:
        msg = _msg("some_unrecognised_type")
        outcome = normalize_android_result(msg)
        assert outcome.was_deduplicated is False


# ============================================================================
# Group H — normalize_android_result: result-only path (task_result)
# ============================================================================


@_SKIP
class TestGroupH_TaskResultPath:

    def setup_method(self) -> None:
        reset_terminal_dedup_guard()

    def test_H01_task_result_routes_to_participant_truth(self) -> None:
        """task_result → participant truth ingress is called."""
        msg = _msg("task_result", contract_id="cid-h01")
        mock_outcome = _make_accepted_participant_truth_outcome(contract_id="cid-h01")

        with patch(
            "core.android_result_normalizer._ingest_participant_truth",
            return_value=mock_outcome,
        ):
            outcome = normalize_android_result(msg)

        assert outcome.was_normalized is True
        assert outcome.category == AndroidResultCategory.user_visible_business_result
        assert outcome.participant_truth_outcome is mock_outcome
        assert outcome.signal_reconcile_outcome is None
        assert outcome.handoff_response_outcome is None

    def test_H02_task_result_truth_kind_result_injected(self) -> None:
        """truth_kind='result' must be injected into the enriched message."""
        msg = _msg("task_result", contract_id="cid-h02")
        captured: list = []

        def fake_ingest(m: Dict, **kwargs: Any) -> MagicMock:
            captured.append(m.get("truth_kind"))
            return _make_accepted_participant_truth_outcome()

        with patch("core.android_result_normalizer._ingest_participant_truth", fake_ingest):
            normalize_android_result(msg)

        assert captured and captured[0] == "result"

    def test_H03_task_result_terminal_commits_dedup(self) -> None:
        """A successful terminal task_result commits the identity to the dedup guard."""
        contract_id = "cid-h03-" + uuid.uuid4().hex[:6]
        msg = _msg("task_result", contract_id=contract_id)
        mock_outcome = _make_accepted_participant_truth_outcome(contract_id=contract_id)

        with patch(
            "core.android_result_normalizer._ingest_participant_truth",
            return_value=mock_outcome,
        ):
            outcome = normalize_android_result(msg)

        assert outcome.committed_terminal_identity != ""

    def test_H04_task_result_ingress_unavailable_returns_rejected(self) -> None:
        """When participant truth ingress is unavailable, outcome is rejected."""
        msg = _msg("task_result", contract_id="cid-h04")
        with patch("core.android_result_normalizer._ingest_participant_truth", None):
            outcome = normalize_android_result(msg)
        assert outcome.was_normalized is False
        assert "unavailable" in outcome.reject_reason


# ============================================================================
# Group I — normalize_android_result: result-only path (goal_execution_result)
# ============================================================================


@_SKIP
class TestGroupI_GoalExecutionResultPath:

    def setup_method(self) -> None:
        reset_terminal_dedup_guard()

    def test_I01_goal_execution_result_routes_to_participant_truth(self) -> None:
        msg = _msg("goal_execution_result", contract_id="cid-i01")
        mock_outcome = _make_accepted_participant_truth_outcome(contract_id="cid-i01")

        with patch(
            "core.android_result_normalizer._ingest_participant_truth",
            return_value=mock_outcome,
        ):
            outcome = normalize_android_result(msg)

        assert outcome.was_normalized is True
        assert outcome.category == AndroidResultCategory.user_visible_business_result
        assert outcome.participant_truth_outcome is mock_outcome

    def test_I02_goal_execution_result_injects_result_truth_kind(self) -> None:
        msg = _msg("goal_execution_result", session_id="sid-i02")
        captured: list = []

        def fake_ingest(m: Dict, **kwargs: Any) -> MagicMock:
            captured.append(m.get("truth_kind"))
            return _make_accepted_participant_truth_outcome()

        with patch("core.android_result_normalizer._ingest_participant_truth", fake_ingest):
            normalize_android_result(msg)

        assert captured and captured[0] == "result"


# ============================================================================
# Group J — normalize_android_result: signal-only path
#            (delegated_execution_signal)
# ============================================================================


@_SKIP
class TestGroupJ_DelegatedSignalPath:

    def setup_method(self) -> None:
        reset_terminal_dedup_guard()

    def test_J01_delegated_execution_signal_routes_to_delegated_ingress(self) -> None:
        msg = _msg("delegated_execution_signal", contract_id="cid-j01")
        mock_outcome = _make_accepted_signal_reconcile_outcome(phase_terminal=False)

        with patch(
            "core.android_result_normalizer._ingest_delegated_signal",
            return_value=mock_outcome,
        ):
            outcome = normalize_android_result(msg)

        assert outcome.was_normalized is True
        assert outcome.category == AndroidResultCategory.runtime_lifecycle_signal
        assert outcome.signal_reconcile_outcome is mock_outcome
        assert outcome.participant_truth_outcome is None

    def test_J02_delegated_execution_signal_terminal_commits_dedup(self) -> None:
        contract_id = "cid-j02-" + uuid.uuid4().hex[:6]
        msg = _msg("delegated_execution_signal", contract_id=contract_id)
        mock_outcome = _make_accepted_signal_reconcile_outcome(phase_terminal=True)

        with patch(
            "core.android_result_normalizer._ingest_delegated_signal",
            return_value=mock_outcome,
        ):
            outcome = normalize_android_result(msg)

        assert outcome.committed_terminal_identity != ""

    def test_J03_delegated_signal_ingress_unavailable_rejected(self) -> None:
        msg = _msg("delegated_execution_signal", contract_id="cid-j03")
        with patch("core.android_result_normalizer._ingest_delegated_signal", None):
            outcome = normalize_android_result(msg)
        assert outcome.was_normalized is False
        assert "unavailable" in outcome.reject_reason


# ============================================================================
# Group K — normalize_android_result: handoff response path
# ============================================================================


@_SKIP
class TestGroupK_HandoffResponsePath:

    def setup_method(self) -> None:
        reset_terminal_dedup_guard()

    def test_K01_handoff_result_routes_to_handoff_ingress(self) -> None:
        msg = _msg("handoff_result", contract_id="cid-k01")
        mock_outcome = _make_accepted_handoff_outcome(kind="result")

        with patch(
            "core.android_result_normalizer._ingest_handoff_response",
            return_value=mock_outcome,
        ):
            outcome = normalize_android_result(msg)

        assert outcome.was_normalized is True
        assert outcome.category == AndroidResultCategory.reconciliation_authoritative_update
        assert outcome.handoff_response_outcome is mock_outcome
        assert outcome.participant_truth_outcome is None
        assert outcome.signal_reconcile_outcome is None

    def test_K02_handoff_ack_is_non_terminal(self) -> None:
        """handoff_ack (response_kind='ack') should not commit terminal dedup."""
        contract_id = "cid-k02-" + uuid.uuid4().hex[:6]
        msg = _msg("handoff_ack", contract_id=contract_id)
        mock_outcome = _make_accepted_handoff_outcome(kind="ack")

        with patch(
            "core.android_result_normalizer._ingest_handoff_response",
            return_value=mock_outcome,
        ):
            outcome = normalize_android_result(msg)

        assert outcome.was_normalized is True
        assert outcome.committed_terminal_identity == ""

    def test_K03_handoff_failure_is_terminal(self) -> None:
        contract_id = "cid-k03-" + uuid.uuid4().hex[:6]
        msg = _msg("handoff_failure", contract_id=contract_id)
        mock_outcome = _make_accepted_handoff_outcome(kind="failure")

        with patch(
            "core.android_result_normalizer._ingest_handoff_response",
            return_value=mock_outcome,
        ):
            outcome = normalize_android_result(msg)

        assert outcome.committed_terminal_identity != ""

    def test_K04_handoff_ingress_unavailable_rejected(self) -> None:
        msg = _msg("handoff_result", contract_id="cid-k04")
        with patch("core.android_result_normalizer._ingest_handoff_response", None):
            outcome = normalize_android_result(msg)
        assert outcome.was_normalized is False


# ============================================================================
# Group L — normalize_android_result: reconciliation_signal → participant truth
# ============================================================================


@_SKIP
class TestGroupL_ReconciliationSignalPath:

    def setup_method(self) -> None:
        reset_terminal_dedup_guard()

    def test_L01_reconciliation_signal_routes_to_participant_truth(self) -> None:
        msg = _msg("reconciliation_signal", contract_id="cid-l01")
        mock_outcome = _make_accepted_participant_truth_outcome(contract_id="cid-l01")
        # truth_kind "reconciliation_signal" for the mock
        tk = MagicMock()
        tk.value = "reconciliation_signal"
        mock_outcome.envelope.truth_kind = tk

        with patch(
            "core.android_result_normalizer._ingest_participant_truth",
            return_value=mock_outcome,
        ):
            outcome = normalize_android_result(msg)

        assert outcome.was_normalized is True
        assert outcome.category == AndroidResultCategory.reconciliation_authoritative_update
        assert outcome.participant_truth_outcome is mock_outcome

    def test_L02_reconciliation_signal_ingress_unavailable_rejected(self) -> None:
        msg = _msg("reconciliation_signal", contract_id="cid-l02")
        with patch("core.android_result_normalizer._ingest_participant_truth", None):
            outcome = normalize_android_result(msg)
        assert outcome.was_normalized is False


# ============================================================================
# Group M — result + reconciliation_signal dedup: prevents double terminal update
# ============================================================================


@_SKIP
class TestGroupM_ResultAndReconciliationSignalDedup:
    """Validates AC: when result and reconciliation_signal arrive for the same
    identity, the second terminal signal is deduplicated."""

    def setup_method(self) -> None:
        reset_terminal_dedup_guard()

    def test_M01_task_result_then_reconciliation_signal_deduped(self) -> None:
        """First task_result commits terminal; reconciliation_signal for same
        contract_id is deduplicated."""
        contract_id = "cid-m01-" + uuid.uuid4().hex[:6]
        result_msg = _msg("task_result", contract_id=contract_id)
        recon_msg = _msg("reconciliation_signal", contract_id=contract_id)

        mock_truth_outcome = _make_accepted_participant_truth_outcome(contract_id=contract_id)

        with patch(
            "core.android_result_normalizer._ingest_participant_truth",
            return_value=mock_truth_outcome,
        ):
            # First call: task_result commits terminal
            first_outcome = normalize_android_result(result_msg)
            assert first_outcome.was_normalized is True
            assert first_outcome.was_deduplicated is False

            # Second call: reconciliation_signal for same contract_id — DEDUP
            second_outcome = normalize_android_result(recon_msg)
            assert second_outcome.was_deduplicated is True
            assert second_outcome.was_normalized is False
            assert "terminal_dedup" in second_outcome.reject_reason

    def test_M02_reconciliation_signal_then_task_result_deduped(self) -> None:
        """reconciliation_signal commits terminal; task_result for same contract_id
        is deduplicated."""
        contract_id = "cid-m02-" + uuid.uuid4().hex[:6]
        recon_msg = _msg("reconciliation_signal", contract_id=contract_id)
        result_msg = _msg("task_result", contract_id=contract_id)

        def make_mock_outcome_for_recon(m: Dict, **kwargs: Any) -> MagicMock:
            outcome = _make_accepted_participant_truth_outcome(contract_id=contract_id)
            tk = MagicMock()
            tk.value = "reconciliation_signal"
            outcome.envelope.truth_kind = tk
            return outcome

        def make_mock_outcome_for_result(m: Dict, **kwargs: Any) -> MagicMock:
            return _make_accepted_participant_truth_outcome(contract_id=contract_id)

        with patch(
            "core.android_result_normalizer._ingest_participant_truth",
            side_effect=[
                make_mock_outcome_for_recon(recon_msg),
                make_mock_outcome_for_result(result_msg),
            ],
        ):
            first = normalize_android_result(recon_msg)
            assert first.was_normalized is True
            assert first.was_deduplicated is False

            second = normalize_android_result(result_msg)
            assert second.was_deduplicated is True

    def test_M03_different_contract_ids_not_deduped(self) -> None:
        """Messages for different contract IDs are independent — no cross-dedup."""
        contract_id_a = "cid-m03a-" + uuid.uuid4().hex[:6]
        contract_id_b = "cid-m03b-" + uuid.uuid4().hex[:6]
        msg_a = _msg("task_result", contract_id=contract_id_a)
        msg_b = _msg("task_result", contract_id=contract_id_b)

        mock_outcome_a = _make_accepted_participant_truth_outcome(contract_id=contract_id_a)
        mock_outcome_b = _make_accepted_participant_truth_outcome(contract_id=contract_id_b)

        with patch(
            "core.android_result_normalizer._ingest_participant_truth",
            side_effect=[mock_outcome_a, mock_outcome_b],
        ):
            out_a = normalize_android_result(msg_a)
            out_b = normalize_android_result(msg_b)

        assert out_a.was_normalized is True
        assert out_a.was_deduplicated is False
        assert out_b.was_normalized is True
        assert out_b.was_deduplicated is False

    def test_M04_non_terminal_result_does_not_block_subsequent_terminal(self) -> None:
        """A non-terminal signal does not commit the dedup guard; a later terminal
        signal for the same identity still proceeds."""
        contract_id = "cid-m04-" + uuid.uuid4().hex[:6]
        progress_msg = _msg("delegated_execution_signal", contract_id=contract_id)
        result_msg = _msg("task_result", contract_id=contract_id)

        # delegated_execution_signal with non-terminal outcome
        non_terminal_signal = _make_accepted_signal_reconcile_outcome(phase_terminal=False)
        terminal_truth = _make_accepted_participant_truth_outcome(contract_id=contract_id)

        with patch(
            "core.android_result_normalizer._ingest_delegated_signal",
            return_value=non_terminal_signal,
        ), patch(
            "core.android_result_normalizer._ingest_participant_truth",
            return_value=terminal_truth,
        ):
            prog_out = normalize_android_result(progress_msg)
            result_out = normalize_android_result(result_msg)

        assert prog_out.was_normalized is True
        assert prog_out.committed_terminal_identity == ""
        assert result_out.was_normalized is True
        assert result_out.was_deduplicated is False


# ============================================================================
# Group N — goal_execution.py: _try_ingest_goal_result_truth is present
# ============================================================================


class TestGroupN_GoalExecutionResultTruthIngress:

    def test_N01_try_ingest_goal_result_truth_present(self) -> None:
        """_try_ingest_goal_result_truth must be importable from goal_execution."""
        try:
            from galaxy_gateway.android.handlers.goal_execution import (
                _try_ingest_goal_result_truth,
            )
            assert callable(_try_ingest_goal_result_truth)
        except ImportError:
            pytest.skip("goal_execution handler unavailable")

    def test_N02_ingest_goal_result_truth_binding_importable(self) -> None:
        """_ingest_goal_result_truth module-level binding must exist."""
        try:
            import galaxy_gateway.android.handlers.goal_execution as ge
            assert hasattr(ge, "_ingest_goal_result_truth")
        except ImportError:
            pytest.skip("goal_execution handler unavailable")

    def test_N03_try_ingest_called_on_handle_goal_execution_result(self) -> None:
        """handle_goal_execution_result must call _try_ingest_goal_result_truth."""
        try:
            import inspect
            import galaxy_gateway.android.handlers.goal_execution as ge
            src = inspect.getsource(ge.handle_goal_execution_result)
            assert "_try_ingest_goal_result_truth" in src, (
                "_try_ingest_goal_result_truth not called in handle_goal_execution_result"
            )
        except ImportError:
            pytest.skip("goal_execution handler unavailable")

    def test_N04_try_ingest_goal_result_truth_noop_when_ingress_unavailable(self) -> None:
        """_try_ingest_goal_result_truth must not raise when ingress is None."""
        try:
            import galaxy_gateway.android.handlers.goal_execution as ge
            with patch.object(ge, "_ingest_goal_result_truth", None):
                ge._try_ingest_goal_result_truth({"type": "goal_execution_result"})
        except ImportError:
            pytest.skip("goal_execution handler unavailable")

    def test_N05_try_ingest_injects_result_truth_kind(self) -> None:
        """_try_ingest_goal_result_truth must inject truth_kind='result'."""
        try:
            import galaxy_gateway.android.handlers.goal_execution as ge
        except ImportError:
            pytest.skip("goal_execution handler unavailable")

        captured: list = []

        def fake_ingress(msg: Dict, **kwargs: Any) -> MagicMock:
            captured.append(msg.get("truth_kind"))
            return MagicMock(was_reconciled=False, reject_reason="", envelope=None)

        with patch.object(ge, "_ingest_goal_result_truth", fake_ingress):
            ge._try_ingest_goal_result_truth({"type": "goal_execution_result"})

        assert captured == ["result"]


# ============================================================================
# Group O — normalize_android_result: missing identity key → no dedup
# ============================================================================


@_SKIP
class TestGroupO_MissingIdentityKey:

    def setup_method(self) -> None:
        reset_terminal_dedup_guard()

    def test_O01_no_contract_or_session_id_no_dedup_guard(self) -> None:
        """Messages without identity keys can be normalized but do not trigger dedup."""
        msg = {"type": "task_result", "device_id": "dev-o01", "message_id": str(uuid.uuid4())}
        mock_outcome = _make_accepted_participant_truth_outcome()

        with patch(
            "core.android_result_normalizer._ingest_participant_truth",
            return_value=mock_outcome,
        ):
            outcome = normalize_android_result(msg)

        assert outcome.was_normalized is True
        assert outcome.committed_terminal_identity == ""
        assert outcome.was_deduplicated is False

    def test_O02_no_identity_key_same_message_not_deduped(self) -> None:
        """Without an identity key the dedup guard is never engaged — two calls
        for the same message type (without identity) both proceed."""
        msg_a = {"type": "task_result", "device_id": "dev", "message_id": str(uuid.uuid4())}
        msg_b = {"type": "task_result", "device_id": "dev", "message_id": str(uuid.uuid4())}
        mock = _make_accepted_participant_truth_outcome()

        with patch(
            "core.android_result_normalizer._ingest_participant_truth",
            return_value=mock,
        ):
            out_a = normalize_android_result(msg_a)
            out_b = normalize_android_result(msg_b)

        assert out_a.was_normalized is True
        assert out_b.was_normalized is True
        assert out_b.was_deduplicated is False
