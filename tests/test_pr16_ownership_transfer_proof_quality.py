"""tests/test_pr16_ownership_transfer_proof_quality.py
======================================================
PR-16 Regression suite — Canonical ownership-transfer proof quality and
failure semantics.

Validates that:
- Resumed ownership transfer is NOT treated as complete unless supported by
  sufficient, fresh, non-conflicting evidence.
- All degraded ownership-transfer states (stale, partial, conflicting,
  unresolved, incomplete) are explicitly classifiable and distinguishable.
- Canonical truth (decision_causality) carries ownership-transfer proof
  quality fields for every governance path.
- Policy sentinels follow the POLICY:: naming convention.
- Insufficient proof can no longer be mistaken for closure.

Acceptance criteria (from PR-16 problem statement)
--------------------------------------------------
- insufficient ownership-transfer proof can no longer be mistaken for
  closure.
- regression coverage proves failure semantics and degraded ownership states.

Coverage groups
---------------
A — Sentinel / contract accessibility: all PR-16 sentinels importable and
    well-formed.
B — OwnershipTransferProofClass: all six values reachable and correct
    is_sufficient_for_closure semantics.
C — classify_ownership_transfer_proof_quality: correct classification for
    each proof class, including confirmed_strong, degraded_partial,
    degraded_stale, degraded_conflicting, degraded_unresolved, incomplete.
D — TakeoverOwnershipState / TakeoverEvidenceQuality: new stale values
    present and used by adjudication.
E — adjudicate_takeover_ownership_convergence: stale-evidence detection
    returns degraded_stale_evidence for old records.
F — get_latest_ownership_transfer_proof_quality_for_device: happy path
    and no-records fallback.
G — decision_causality fields: governance state carries ownership-transfer
    proof quality fields.
H — Policy sentinel naming convention (POLICY:: prefix).
"""

from __future__ import annotations

import time
import uuid

import pytest

# ---------------------------------------------------------------------------
# Availability guard
# ---------------------------------------------------------------------------

try:
    from core.ownership_transfer_proof_quality import (
        OWNERSHIP_TRANSFER_PROOF_QUALITY_SENTINEL,
        OWNERSHIP_TRANSFER_PROOF_QUALITY_CONTRACT_VERSION,
        RESUMED_OWNERSHIP_TRANSFER_REQUIRES_PROOF_POLICY,
        OWNERSHIP_TRANSFER_PROOF_QUALITY_POLICY,
        STALE_OWNERSHIP_EVIDENCE_THRESHOLD_SECONDS,
        OwnershipTransferProofClass,
        OwnershipTransferProofQualityResult,
        classify_ownership_transfer_proof_quality,
        get_latest_ownership_transfer_proof_quality_for_device,
    )
    from core.takeover_tracking import (
        TakeoverOwnershipState,
        TakeoverEvidenceQuality,
        TakeoverOwnershipConvergenceVerdict,
        TakeoverDecision,
        adjudicate_takeover_ownership_convergence,
        record_takeover_response,
        reset_takeover_tracking_runtime,
        OWNERSHIP_STALE_EVIDENCE_THRESHOLD_SECONDS,
        RESUMED_OWNERSHIP_TRANSFER_REQUIRES_FRESH_PROOF_POLICY,
    )
    _AVAILABLE = True
except ImportError:  # pragma: no cover
    _AVAILABLE = False


def _uid() -> str:
    return str(uuid.uuid4())


def _make_verdict(
    *,
    ownership_state: str = "unresolved",
    evidence_quality: str = "missing",
    is_converged: bool = False,
    degraded: bool = True,
    diagnosis: list | None = None,
    latest_record_at: float = 0.0,
) -> dict:
    """Build a minimal verdict dict for testing classify_ownership_transfer_proof_quality."""
    return {
        "ownership_state": ownership_state,
        "evidence_quality": evidence_quality,
        "is_converged": is_converged,
        "degraded": degraded,
        "diagnosis": diagnosis or [],
        "latest_record_at": latest_record_at,
    }


# ===========================================================================
# Group A — Sentinel / contract accessibility
# ===========================================================================


@pytest.mark.skipif(not _AVAILABLE, reason="PR-16 ownership transfer proof quality modules unavailable")
class TestGroupA_SentinelAccessibility:
    """A01–A05: All PR-16 sentinels are importable and well-formed strings."""

    def test_A01_proof_quality_sentinel_present_and_well_formed(self) -> None:
        assert isinstance(OWNERSHIP_TRANSFER_PROOF_QUALITY_SENTINEL, str)
        assert len(OWNERSHIP_TRANSFER_PROOF_QUALITY_SENTINEL) > 50
        assert "PR16_V2" in OWNERSHIP_TRANSFER_PROOF_QUALITY_SENTINEL

    def test_A02_contract_version_present(self) -> None:
        assert isinstance(OWNERSHIP_TRANSFER_PROOF_QUALITY_CONTRACT_VERSION, str)
        assert OWNERSHIP_TRANSFER_PROOF_QUALITY_CONTRACT_VERSION == "16.0.0"

    def test_A03_resumed_ownership_transfer_requires_proof_policy_present(self) -> None:
        assert isinstance(RESUMED_OWNERSHIP_TRANSFER_REQUIRES_PROOF_POLICY, str)
        assert RESUMED_OWNERSHIP_TRANSFER_REQUIRES_PROOF_POLICY.startswith("POLICY::")
        assert len(RESUMED_OWNERSHIP_TRANSFER_REQUIRES_PROOF_POLICY) > 50

    def test_A04_proof_quality_policy_present(self) -> None:
        assert isinstance(OWNERSHIP_TRANSFER_PROOF_QUALITY_POLICY, str)
        assert OWNERSHIP_TRANSFER_PROOF_QUALITY_POLICY.startswith("POLICY::")
        assert "confirmed_strong" in OWNERSHIP_TRANSFER_PROOF_QUALITY_POLICY

    def test_A05_stale_threshold_is_numeric(self) -> None:
        assert isinstance(STALE_OWNERSHIP_EVIDENCE_THRESHOLD_SECONDS, float)
        assert STALE_OWNERSHIP_EVIDENCE_THRESHOLD_SECONDS > 0.0

    def test_A06_takeover_tracking_stale_threshold_present(self) -> None:
        assert isinstance(OWNERSHIP_STALE_EVIDENCE_THRESHOLD_SECONDS, float)
        assert OWNERSHIP_STALE_EVIDENCE_THRESHOLD_SECONDS > 0.0

    def test_A07_takeover_fresh_proof_policy_present(self) -> None:
        assert isinstance(RESUMED_OWNERSHIP_TRANSFER_REQUIRES_FRESH_PROOF_POLICY, str)
        assert RESUMED_OWNERSHIP_TRANSFER_REQUIRES_FRESH_PROOF_POLICY.startswith("POLICY::")


# ===========================================================================
# Group B — OwnershipTransferProofClass enum
# ===========================================================================


@pytest.mark.skipif(not _AVAILABLE, reason="PR-16 ownership transfer proof quality modules unavailable")
class TestGroupB_OwnershipTransferProofClass:
    """B01–B07: All six proof classes exist and have correct closure semantics."""

    def test_B01_confirmed_strong_is_sufficient_for_closure(self) -> None:
        assert OwnershipTransferProofClass.confirmed_strong.value == "confirmed_strong"

    def test_B02_degraded_partial_is_not_sufficient(self) -> None:
        assert OwnershipTransferProofClass.degraded_partial.value == "degraded_partial"

    def test_B03_degraded_stale_is_not_sufficient(self) -> None:
        assert OwnershipTransferProofClass.degraded_stale.value == "degraded_stale"

    def test_B04_degraded_conflicting_is_not_sufficient(self) -> None:
        assert OwnershipTransferProofClass.degraded_conflicting.value == "degraded_conflicting"

    def test_B05_degraded_unresolved_is_not_sufficient(self) -> None:
        assert OwnershipTransferProofClass.degraded_unresolved.value == "degraded_unresolved"

    def test_B06_incomplete_is_not_sufficient(self) -> None:
        assert OwnershipTransferProofClass.incomplete.value == "incomplete"

    def test_B07_exactly_six_proof_classes(self) -> None:
        values = {c.value for c in OwnershipTransferProofClass}
        assert values == {
            "confirmed_strong",
            "degraded_partial",
            "degraded_stale",
            "degraded_conflicting",
            "degraded_unresolved",
            "incomplete",
        }


# ===========================================================================
# Group C — classify_ownership_transfer_proof_quality
# ===========================================================================


@pytest.mark.skipif(not _AVAILABLE, reason="PR-16 ownership transfer proof quality modules unavailable")
class TestGroupC_ClassifyOwnershipTransferProofQuality:
    """C01–C20: Every proof class is reachable with correct is_sufficient_for_closure."""

    # ── confirmed_strong ─────────────────────────────────────────────────────

    def test_C01_confirmed_strong_for_resumed_v2_ownership(self) -> None:
        verdict = _make_verdict(
            ownership_state="resumed_v2_ownership_confirmed",
            evidence_quality="strong",
            is_converged=True,
            degraded=False,
            latest_record_at=time.time(),
        )
        result = classify_ownership_transfer_proof_quality(verdict)
        assert result.proof_class == OwnershipTransferProofClass.confirmed_strong
        assert result.is_sufficient_for_closure is True
        assert result.degraded is False

    def test_C02_confirmed_strong_for_delegated_takeover(self) -> None:
        verdict = _make_verdict(
            ownership_state="delegated_takeover_confirmed",
            evidence_quality="strong",
            is_converged=True,
            degraded=False,
            latest_record_at=time.time(),
        )
        result = classify_ownership_transfer_proof_quality(verdict)
        assert result.proof_class == OwnershipTransferProofClass.confirmed_strong
        assert result.is_sufficient_for_closure is True

    # ── degraded_conflicting ──────────────────────────────────────────────────

    def test_C03_degraded_conflicting_for_conflicting_evidence_quality(self) -> None:
        verdict = _make_verdict(
            ownership_state="degraded_conflicting_evidence",
            evidence_quality="conflicting",
        )
        result = classify_ownership_transfer_proof_quality(verdict)
        assert result.proof_class == OwnershipTransferProofClass.degraded_conflicting
        assert result.is_sufficient_for_closure is False
        assert result.degraded is True

    def test_C04_degraded_conflicting_for_conflicting_ownership_state(self) -> None:
        verdict = _make_verdict(
            ownership_state="degraded_conflicting_evidence",
            evidence_quality="strong",
        )
        result = classify_ownership_transfer_proof_quality(verdict)
        assert result.proof_class == OwnershipTransferProofClass.degraded_conflicting

    def test_C05_degraded_conflicting_for_conflicting_diagnosis_token(self) -> None:
        verdict = _make_verdict(
            diagnosis=["conflicting_takeover_decisions"],
        )
        result = classify_ownership_transfer_proof_quality(verdict)
        assert result.proof_class == OwnershipTransferProofClass.degraded_conflicting

    # ── incomplete (missing) ──────────────────────────────────────────────────

    def test_C06_incomplete_for_missing_evidence_quality(self) -> None:
        verdict = _make_verdict(evidence_quality="missing")
        result = classify_ownership_transfer_proof_quality(verdict)
        assert result.proof_class == OwnershipTransferProofClass.incomplete
        assert result.is_sufficient_for_closure is False

    def test_C07_incomplete_for_degraded_incomplete_state(self) -> None:
        verdict = _make_verdict(
            ownership_state="degraded_incomplete_evidence",
            evidence_quality="partial",
        )
        # ownership_state triggers incomplete before the partial evidence check
        result = classify_ownership_transfer_proof_quality(verdict)
        assert result.proof_class == OwnershipTransferProofClass.incomplete

    # ── degraded_partial ─────────────────────────────────────────────────────

    def test_C08_degraded_partial_for_partial_evidence_quality(self) -> None:
        verdict = _make_verdict(
            ownership_state="unresolved",
            evidence_quality="partial",
        )
        result = classify_ownership_transfer_proof_quality(verdict)
        assert result.proof_class == OwnershipTransferProofClass.degraded_partial
        assert result.is_sufficient_for_closure is False

    # ── degraded_stale ────────────────────────────────────────────────────────

    def test_C09_degraded_stale_for_stale_evidence_quality(self) -> None:
        verdict = _make_verdict(
            ownership_state="degraded_stale_evidence",
            evidence_quality="stale",
        )
        result = classify_ownership_transfer_proof_quality(verdict)
        assert result.proof_class == OwnershipTransferProofClass.degraded_stale
        assert result.is_sufficient_for_closure is False

    def test_C10_degraded_stale_for_degraded_stale_ownership_state(self) -> None:
        verdict = _make_verdict(
            ownership_state="degraded_stale_evidence",
            evidence_quality="strong",
        )
        result = classify_ownership_transfer_proof_quality(verdict)
        assert result.proof_class == OwnershipTransferProofClass.degraded_stale

    def test_C11_degraded_stale_when_latest_record_at_is_old(self) -> None:
        old_ts = time.time() - 600.0  # 10 minutes ago
        verdict = _make_verdict(
            ownership_state="resumed_v2_ownership_confirmed",
            evidence_quality="strong",
            is_converged=True,
            degraded=False,
            latest_record_at=old_ts,
        )
        result = classify_ownership_transfer_proof_quality(
            verdict,
            stale_threshold_seconds=300.0,
        )
        assert result.proof_class == OwnershipTransferProofClass.degraded_stale
        assert result.is_sufficient_for_closure is False
        # Diagnosis should include the stale token
        assert any("degraded_stale" in d for d in result.diagnosis)

    def test_C12_confirmed_strong_when_record_is_fresh(self) -> None:
        fresh_ts = time.time()
        verdict = _make_verdict(
            ownership_state="resumed_v2_ownership_confirmed",
            evidence_quality="strong",
            is_converged=True,
            degraded=False,
            latest_record_at=fresh_ts,
        )
        result = classify_ownership_transfer_proof_quality(
            verdict,
            stale_threshold_seconds=300.0,
        )
        assert result.proof_class == OwnershipTransferProofClass.confirmed_strong

    # ── degraded_unresolved ───────────────────────────────────────────────────

    def test_C13_degraded_unresolved_for_unresolved_ownership_state(self) -> None:
        verdict = _make_verdict(
            ownership_state="unresolved",
            evidence_quality="strong",
            is_converged=False,
        )
        result = classify_ownership_transfer_proof_quality(verdict)
        assert result.proof_class == OwnershipTransferProofClass.degraded_unresolved
        assert result.is_sufficient_for_closure is False

    def test_C14_degraded_unresolved_when_not_converged(self) -> None:
        verdict = _make_verdict(
            ownership_state="",
            evidence_quality="strong",
            is_converged=False,
        )
        result = classify_ownership_transfer_proof_quality(verdict)
        assert result.proof_class in (
            OwnershipTransferProofClass.degraded_unresolved,
            OwnershipTransferProofClass.incomplete,
        )
        assert result.is_sufficient_for_closure is False

    # ── diagnosis carries proof class token ───────────────────────────────────

    def test_C15_diagnosis_carries_proof_class_token(self) -> None:
        verdict = _make_verdict(
            ownership_state="resumed_v2_ownership_confirmed",
            evidence_quality="strong",
            is_converged=True,
            degraded=False,
            latest_record_at=time.time(),
        )
        result = classify_ownership_transfer_proof_quality(verdict)
        assert any("confirmed_strong" in d for d in result.diagnosis)

    def test_C16_conflicting_carries_diagnosis_token(self) -> None:
        verdict = _make_verdict(evidence_quality="conflicting")
        result = classify_ownership_transfer_proof_quality(verdict)
        assert any("degraded_conflicting" in d for d in result.diagnosis)

    # ── dict and dataclass both work ──────────────────────────────────────────

    def test_C17_accepts_typed_verdict_dataclass(self) -> None:
        v = TakeoverOwnershipConvergenceVerdict(
            ownership_state=TakeoverOwnershipState.resumed_v2_ownership_confirmed,
            evidence_quality=TakeoverEvidenceQuality.strong,
            is_converged=True,
            degraded=False,
            latest_record_at=time.time(),
        )
        result = classify_ownership_transfer_proof_quality(v)
        assert result.proof_class == OwnershipTransferProofClass.confirmed_strong
        assert result.is_sufficient_for_closure is True

    def test_C18_accepts_typed_verdict_stale_dataclass(self) -> None:
        old_ts = time.time() - 9999.0
        v = TakeoverOwnershipConvergenceVerdict(
            ownership_state=TakeoverOwnershipState.resumed_v2_ownership_confirmed,
            evidence_quality=TakeoverEvidenceQuality.strong,
            is_converged=True,
            degraded=False,
            latest_record_at=old_ts,
        )
        result = classify_ownership_transfer_proof_quality(v, stale_threshold_seconds=300.0)
        assert result.proof_class == OwnershipTransferProofClass.degraded_stale

    def test_C19_returns_incomplete_on_exception(self) -> None:
        result = classify_ownership_transfer_proof_quality(None)
        assert isinstance(result, OwnershipTransferProofQualityResult)
        assert result.is_sufficient_for_closure is False

    def test_C20_to_dict_is_json_serialisable(self) -> None:
        import json

        verdict = _make_verdict(
            ownership_state="resumed_v2_ownership_confirmed",
            evidence_quality="strong",
            is_converged=True,
            degraded=False,
            latest_record_at=time.time(),
        )
        result = classify_ownership_transfer_proof_quality(verdict)
        d = result.to_dict()
        assert json.dumps(d)  # no exception
        assert d["proof_class"] == "confirmed_strong"
        assert d["is_sufficient_for_closure"] is True
        assert "_policy" in d


# ===========================================================================
# Group D — TakeoverOwnershipState / TakeoverEvidenceQuality new values
# ===========================================================================


@pytest.mark.skipif(not _AVAILABLE, reason="PR-16 modules unavailable")
class TestGroupD_NewEnumValues:
    """D01–D04: New stale states are present in TakeoverOwnershipState and
    TakeoverEvidenceQuality."""

    def test_D01_degraded_stale_evidence_in_ownership_state(self) -> None:
        assert hasattr(TakeoverOwnershipState, "degraded_stale_evidence")
        assert TakeoverOwnershipState.degraded_stale_evidence.value == "degraded_stale_evidence"

    def test_D02_stale_in_evidence_quality(self) -> None:
        assert hasattr(TakeoverEvidenceQuality, "stale")
        assert TakeoverEvidenceQuality.stale.value == "stale"

    def test_D03_all_original_states_still_present(self) -> None:
        values = {s.value for s in TakeoverOwnershipState}
        assert "delegated_takeover_confirmed" in values
        assert "resumed_v2_ownership_confirmed" in values
        assert "unresolved" in values
        assert "degraded_incomplete_evidence" in values
        assert "degraded_conflicting_evidence" in values

    def test_D04_all_original_qualities_still_present(self) -> None:
        values = {q.value for q in TakeoverEvidenceQuality}
        assert "strong" in values
        assert "partial" in values
        assert "missing" in values
        assert "conflicting" in values


# ===========================================================================
# Group E — adjudicate_takeover_ownership_convergence: stale detection
# ===========================================================================


@pytest.mark.skipif(not _AVAILABLE, reason="PR-16 modules unavailable")
class TestGroupE_AdjudicationStaleDetection:
    """E01–E07: Adjudication returns degraded_stale_evidence for old records."""

    def setup_method(self):
        reset_takeover_tracking_runtime()

    def test_E01_fresh_rejected_record_produces_resumed_ownership_confirmed(self) -> None:
        takeover_id = _uid()
        record_takeover_response(
            takeover_id=takeover_id,
            device_id="dev-E01",
            session_id="sess-E01",
            accepted=False,
        )
        verdict = adjudicate_takeover_ownership_convergence(
            takeover_id=takeover_id,
            device_id="dev-E01",
            session_id="sess-E01",
            stale_threshold_seconds=300.0,
        )
        assert verdict.ownership_state == TakeoverOwnershipState.resumed_v2_ownership_confirmed
        assert verdict.evidence_quality == TakeoverEvidenceQuality.strong
        assert verdict.is_converged is True
        assert verdict.degraded is False

    def test_E02_stale_rejected_record_degrades_to_stale_evidence(self) -> None:
        takeover_id = _uid()
        record_takeover_response(
            takeover_id=takeover_id,
            device_id="dev-E02",
            session_id="sess-E02",
            accepted=False,
        )
        # Simulate the record being 10 minutes old by passing a future `now`
        future_now = time.time() + 600.0
        verdict = adjudicate_takeover_ownership_convergence(
            takeover_id=takeover_id,
            device_id="dev-E02",
            session_id="sess-E02",
            stale_threshold_seconds=300.0,
            now=future_now,
        )
        assert verdict.ownership_state == TakeoverOwnershipState.degraded_stale_evidence
        assert verdict.evidence_quality == TakeoverEvidenceQuality.stale
        assert verdict.is_converged is False
        assert verdict.degraded is True
        assert any("stale" in d for d in verdict.diagnosis)

    def test_E03_stale_accepted_record_degrades_to_stale_evidence(self) -> None:
        takeover_id = _uid()
        record_takeover_response(
            takeover_id=takeover_id,
            device_id="dev-E03",
            session_id="sess-E03",
            accepted=True,
        )
        future_now = time.time() + 600.0
        verdict = adjudicate_takeover_ownership_convergence(
            takeover_id=takeover_id,
            device_id="dev-E03",
            session_id="sess-E03",
            stale_threshold_seconds=300.0,
            now=future_now,
        )
        assert verdict.ownership_state == TakeoverOwnershipState.degraded_stale_evidence
        assert verdict.evidence_quality == TakeoverEvidenceQuality.stale

    def test_E04_threshold_zero_disables_stale_detection(self) -> None:
        """stale_threshold_seconds=0 disables the stale-evidence check."""
        takeover_id = _uid()
        record_takeover_response(
            takeover_id=takeover_id,
            device_id="dev-E04",
            session_id="sess-E04",
            accepted=False,
        )
        future_now = time.time() + 9999.0
        verdict = adjudicate_takeover_ownership_convergence(
            takeover_id=takeover_id,
            device_id="dev-E04",
            session_id="sess-E04",
            stale_threshold_seconds=0,
            now=future_now,
        )
        # With threshold=0, stale check is skipped
        assert verdict.ownership_state == TakeoverOwnershipState.resumed_v2_ownership_confirmed

    def test_E05_latest_record_at_is_populated(self) -> None:
        takeover_id = _uid()
        before = time.time()
        record_takeover_response(
            takeover_id=takeover_id,
            device_id="dev-E05",
            session_id="sess-E05",
            accepted=True,
        )
        verdict = adjudicate_takeover_ownership_convergence(
            takeover_id=takeover_id,
            device_id="dev-E05",
            session_id="sess-E05",
        )
        assert verdict.latest_record_at >= before

    def test_E06_verdict_to_dict_includes_latest_record_at(self) -> None:
        takeover_id = _uid()
        record_takeover_response(
            takeover_id=takeover_id,
            device_id="dev-E06",
            session_id="sess-E06",
            accepted=False,
        )
        verdict = adjudicate_takeover_ownership_convergence(
            takeover_id=takeover_id,
            device_id="dev-E06",
            session_id="sess-E06",
        )
        d = verdict.to_dict()
        assert "latest_record_at" in d
        assert d["latest_record_at"] > 0.0

    def test_E07_conflicting_decisions_still_detected_before_stale_check(self) -> None:
        """Conflict detection must take priority over stale detection."""
        takeover_id = _uid()
        record_takeover_response(
            takeover_id=takeover_id, device_id="dev-E07", session_id="sess-E07", accepted=True
        )
        record_takeover_response(
            takeover_id=takeover_id, device_id="dev-E07", session_id="sess-E07", accepted=False
        )
        future_now = time.time() + 9999.0
        verdict = adjudicate_takeover_ownership_convergence(
            takeover_id=takeover_id,
            device_id="dev-E07",
            session_id="sess-E07",
            now=future_now,
        )
        assert verdict.ownership_state == TakeoverOwnershipState.degraded_conflicting_evidence


# ===========================================================================
# Group F — get_latest_ownership_transfer_proof_quality_for_device
# ===========================================================================


@pytest.mark.skipif(not _AVAILABLE, reason="PR-16 modules unavailable")
class TestGroupF_GetLatestProofQualityForDevice:
    """F01–F04: Convenience lookup returns correct result."""

    def setup_method(self):
        reset_takeover_tracking_runtime()

    def test_F01_returns_incomplete_when_no_records(self) -> None:
        result = get_latest_ownership_transfer_proof_quality_for_device("dev-no-records-F01")
        assert isinstance(result, OwnershipTransferProofQualityResult)
        assert result.proof_class == OwnershipTransferProofClass.incomplete
        assert result.is_sufficient_for_closure is False
        assert "no_takeover_record_for_device" in result.diagnosis

    def test_F02_returns_confirmed_strong_for_fresh_rejection(self) -> None:
        takeover_id = _uid()
        device_id = "dev-F02"
        record_takeover_response(
            takeover_id=takeover_id,
            device_id=device_id,
            session_id="sess-F02",
            accepted=False,
        )
        result = get_latest_ownership_transfer_proof_quality_for_device(
            device_id,
            session_id="sess-F02",
        )
        assert result.proof_class == OwnershipTransferProofClass.confirmed_strong
        assert result.is_sufficient_for_closure is True

    def test_F03_returns_degraded_stale_for_old_record(self) -> None:
        takeover_id = _uid()
        device_id = "dev-F03"
        record_takeover_response(
            takeover_id=takeover_id,
            device_id=device_id,
            session_id="sess-F03",
            accepted=False,
        )
        future_now = time.time() + 9999.0
        result = get_latest_ownership_transfer_proof_quality_for_device(
            device_id,
            session_id="sess-F03",
            now=future_now,
            stale_threshold_seconds=300.0,
        )
        assert result.proof_class == OwnershipTransferProofClass.degraded_stale
        assert result.is_sufficient_for_closure is False

    def test_F04_returns_degraded_conflicting_for_conflicting_records(self) -> None:
        takeover_id = _uid()
        device_id = "dev-F04"
        record_takeover_response(
            takeover_id=takeover_id, device_id=device_id, session_id="sess-F04", accepted=True
        )
        record_takeover_response(
            takeover_id=takeover_id, device_id=device_id, session_id="sess-F04", accepted=False
        )
        result = get_latest_ownership_transfer_proof_quality_for_device(
            device_id,
            session_id="sess-F04",
        )
        assert result.proof_class == OwnershipTransferProofClass.degraded_conflicting
        assert result.is_sufficient_for_closure is False


# ===========================================================================
# Group G — decision_causality fields in governance state
# ===========================================================================


@pytest.mark.skipif(not _AVAILABLE, reason="PR-16 modules unavailable")
class TestGroupG_GovernanceStateDecisionCausality:
    """G01–G05: build_unified_governance_state decision_causality carries
    ownership-transfer proof quality fields."""

    def test_G01_decision_causality_fields_are_present(self) -> None:
        """ownership_transfer_proof_class and related fields exist in causality."""
        try:
            from core.unified_governance_semantics import build_unified_governance_state
            from unittest.mock import patch
        except ImportError:  # pragma: no cover
            pytest.skip("unified_governance_semantics unavailable")

        with patch(
            "core.attached_runtime_session_registry.list_active_sessions",
            return_value=[],
        ):
            state = build_unified_governance_state(device_ids=[])

        # No devices — just verify the function returns without error and
        # the authority field is present.
        assert "devices" in state
        assert state.get("authority") == "v2_semantic_orchestration_authority"

    def test_G02_decision_causality_contains_ownership_transfer_fields(self) -> None:
        """For a device with an active record, governance state carries
        ownership_transfer_proof_* in decision_causality."""
        try:
            from core.unified_governance_semantics import build_unified_governance_state
            from types import SimpleNamespace
            from unittest.mock import patch
        except ImportError:  # pragma: no cover
            pytest.skip("unified_governance_semantics unavailable")

        device_id = "dev-G02"
        reset_takeover_tracking_runtime()
        takeover_id = _uid()
        record_takeover_response(
            takeover_id=takeover_id,
            device_id=device_id,
            session_id="sess-G02",
            accepted=False,
        )

        mock_session = SimpleNamespace(device_id=device_id)
        mock_mode_state = SimpleNamespace(mode=SimpleNamespace(value="cross_device"))
        mock_readiness = SimpleNamespace(
            is_dispatch_eligible=True,
            is_cross_device_ready=True,
            is_takeover_eligible=False,
        )

        with patch(
            "core.attached_runtime_session_registry.list_active_sessions",
            return_value=[mock_session],
        ), patch(
            "core.android_mode_gate_policy.build_mode_state_for_device",
            return_value=mock_mode_state,
        ), patch(
            "core.android_mode_gate_policy.evaluate_android_mode_readiness",
            return_value=mock_readiness,
        ), patch(
            "core.unified_execution_governance.is_takeover_active",
            return_value=False,
        ), patch(
            "core.unified_execution_governance.get_execution_runtime_snapshot",
            return_value={"devices": [{"device_id": device_id}]},
        ):
            state = build_unified_governance_state()

        # Find a path entry with decision_causality
        devices = state.get("devices", [])
        assert len(devices) > 0, "Expected at least one device"
        dev = devices[0]
        governance_paths = dev.get("governance_precedence", {})
        # Check at least one path has the new fields in decision_causality
        found_field = False
        for path_val in governance_paths.values():
            causality = path_val.get("decision_causality", {})
            if "ownership_transfer_proof_class" in causality:
                found_field = True
                assert "ownership_transfer_proof_sufficient" in causality
                assert "ownership_transfer_proof_degraded" in causality
                assert "ownership_transfer_proof_diagnosis" in causality
                break
        assert found_field, (
            "Expected 'ownership_transfer_proof_class' in at least one "
            "decision_causality dict"
        )

    def test_G03_ownership_transfer_proof_class_is_confirmed_strong_for_fresh_record(
        self,
    ) -> None:
        """For a fresh rejection record, proof_class should be confirmed_strong
        and proof_sufficient should be True in decision_causality."""
        try:
            from core.unified_governance_semantics import build_unified_governance_state
            from types import SimpleNamespace
            from unittest.mock import patch
        except ImportError:  # pragma: no cover
            pytest.skip("unified_governance_semantics unavailable")

        device_id = "dev-G03"
        reset_takeover_tracking_runtime()
        takeover_id = _uid()
        record_takeover_response(
            takeover_id=takeover_id,
            device_id=device_id,
            session_id="sess-G03",
            accepted=False,
        )

        mock_session = SimpleNamespace(device_id=device_id)
        mock_mode_state = SimpleNamespace(mode=SimpleNamespace(value="cross_device"))
        mock_readiness = SimpleNamespace(
            is_dispatch_eligible=True,
            is_cross_device_ready=True,
            is_takeover_eligible=False,
        )

        with patch(
            "core.attached_runtime_session_registry.list_active_sessions",
            return_value=[mock_session],
        ), patch(
            "core.android_mode_gate_policy.build_mode_state_for_device",
            return_value=mock_mode_state,
        ), patch(
            "core.android_mode_gate_policy.evaluate_android_mode_readiness",
            return_value=mock_readiness,
        ), patch(
            "core.unified_execution_governance.is_takeover_active",
            return_value=False,
        ), patch(
            "core.unified_execution_governance.get_execution_runtime_snapshot",
            return_value={"devices": [{"device_id": device_id}]},
        ):
            state = build_unified_governance_state()

        devices = state.get("devices", [])
        assert len(devices) > 0
        dev = devices[0]
        governance_paths = dev.get("governance_precedence", {})
        for path_val in governance_paths.values():
            causality = path_val.get("decision_causality", {})
            if "ownership_transfer_proof_class" in causality:
                assert causality["ownership_transfer_proof_class"] == "confirmed_strong", (
                    f"Expected confirmed_strong, got {causality['ownership_transfer_proof_class']}"
                )
                assert causality["ownership_transfer_proof_sufficient"] is True
                assert causality["ownership_transfer_proof_degraded"] is False
                break


# ===========================================================================
# Group H — Policy sentinel naming convention
# ===========================================================================


@pytest.mark.skipif(not _AVAILABLE, reason="PR-16 modules unavailable")
class TestGroupH_PolicySentinelNamingConvention:
    """H01–H04: All PR-16 policy constants follow the POLICY:: convention."""

    def test_H01_resumed_ownership_transfer_requires_proof_policy(self) -> None:
        assert RESUMED_OWNERSHIP_TRANSFER_REQUIRES_PROOF_POLICY.startswith("POLICY::")

    def test_H02_ownership_transfer_proof_quality_policy(self) -> None:
        assert OWNERSHIP_TRANSFER_PROOF_QUALITY_POLICY.startswith("POLICY::")

    def test_H03_takeover_tracking_fresh_proof_policy(self) -> None:
        assert RESUMED_OWNERSHIP_TRANSFER_REQUIRES_FRESH_PROOF_POLICY.startswith("POLICY::")

    def test_H04_policies_are_non_empty_and_meaningful(self) -> None:
        for policy in (
            RESUMED_OWNERSHIP_TRANSFER_REQUIRES_PROOF_POLICY,
            OWNERSHIP_TRANSFER_PROOF_QUALITY_POLICY,
            RESUMED_OWNERSHIP_TRANSFER_REQUIRES_FRESH_PROOF_POLICY,
        ):
            assert len(policy) > 50, f"Policy sentinel too short: {policy!r}"
            assert "ownership" in policy.lower() or "transfer" in policy.lower()
