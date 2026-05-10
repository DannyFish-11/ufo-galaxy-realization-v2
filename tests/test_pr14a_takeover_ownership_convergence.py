"""PR-14A: Takeover ownership convergence adjudication regression coverage."""

from __future__ import annotations

import uuid

import pytest

try:
    from core.android_delegated_runtime_lifecycle_coordinator import (
        get_lifecycle_coordinator,
        reset_lifecycle_coordinator,
    )
    from core.android_participant_session_state import reset_participant_session_runtime
    from core.takeover_tracking import (
        adjudicate_takeover_ownership_convergence,
        record_takeover_response,
        reset_takeover_tracking_runtime,
    )

    _AVAILABLE = True
except ImportError:  # pragma: no cover
    _AVAILABLE = False


def _uid() -> str:
    return str(uuid.uuid4())


@pytest.mark.skipif(not _AVAILABLE, reason="takeover ownership convergence modules unavailable")
class TestTakeoverOwnershipConvergence:
    def setup_method(self):
        reset_takeover_tracking_runtime()
        reset_participant_session_runtime()
        reset_lifecycle_coordinator()

    def test_A01_accepted_takeover_converges_to_delegated_completion(self):
        takeover_id = _uid()
        record_takeover_response(
            takeover_id=takeover_id,
            device_id="dev-A01",
            session_id="sess-A01",
            accepted=True,
        )

        verdict = adjudicate_takeover_ownership_convergence(
            takeover_id=takeover_id,
            device_id="dev-A01",
            session_id="sess-A01",
        )
        assert verdict.ownership_state.value == "delegated_takeover_confirmed"
        assert verdict.evidence_quality.value == "strong"
        assert verdict.is_converged is True
        assert verdict.degraded is False

    def test_A02_rejected_takeover_converges_to_resumed_v2_ownership(self):
        takeover_id = _uid()
        record_takeover_response(
            takeover_id=takeover_id,
            device_id="dev-A02",
            session_id="sess-A02",
            accepted=False,
        )

        verdict = adjudicate_takeover_ownership_convergence(
            takeover_id=takeover_id,
            device_id="dev-A02",
            session_id="sess-A02",
        )
        assert verdict.ownership_state.value == "resumed_v2_ownership_confirmed"
        assert verdict.evidence_quality.value == "strong"
        assert verdict.is_converged is True
        assert verdict.degraded is False

    def test_A03_missing_evidence_degrades_to_incomplete(self):
        verdict = adjudicate_takeover_ownership_convergence(
            takeover_id="",
            device_id="dev-A03",
            session_id="sess-A03",
        )
        assert verdict.ownership_state.value == "degraded_incomplete_evidence"
        assert verdict.degraded is True
        assert "missing_takeover_id" in verdict.diagnosis
        assert "missing_takeover_record" in verdict.diagnosis

    def test_A04_none_takeover_id_degrades_to_incomplete(self):
        verdict = adjudicate_takeover_ownership_convergence(
            takeover_id=None,
            device_id="dev-A04",
            session_id="sess-A04",
        )
        assert verdict.ownership_state.value == "degraded_incomplete_evidence"
        assert "missing_takeover_id" in verdict.diagnosis

    def test_A05_missing_session_id_is_reported_explicitly(self):
        takeover_id = _uid()
        record_takeover_response(
            takeover_id=takeover_id,
            device_id="dev-A05",
            session_id="sess-A05",
            accepted=True,
        )
        verdict = adjudicate_takeover_ownership_convergence(
            takeover_id=takeover_id,
            device_id="dev-A05",
            session_id="",
        )
        assert verdict.ownership_state.value == "degraded_incomplete_evidence"
        assert "missing_session_id" in verdict.diagnosis
        assert "missing_device_id" not in verdict.diagnosis

    def test_A06_missing_device_id_is_reported_explicitly(self):
        takeover_id = _uid()
        record_takeover_response(
            takeover_id=takeover_id,
            device_id="dev-A06",
            session_id="sess-A06",
            accepted=True,
        )
        verdict = adjudicate_takeover_ownership_convergence(
            takeover_id=takeover_id,
            device_id="",
            session_id="sess-A06",
        )
        assert verdict.ownership_state.value == "degraded_incomplete_evidence"
        assert "missing_device_id" in verdict.diagnosis
        assert "missing_session_id" not in verdict.diagnosis

    def test_A07_conflicting_decisions_degrade_to_conflict_state(self):
        takeover_id = _uid()
        record_takeover_response(
            takeover_id=takeover_id,
            device_id="dev-A07",
            session_id="sess-A07",
            accepted=True,
        )
        record_takeover_response(
            takeover_id=takeover_id,
            device_id="dev-A07",
            session_id="sess-A07",
            accepted=False,
        )

        verdict = adjudicate_takeover_ownership_convergence(
            takeover_id=takeover_id,
            device_id="dev-A07",
            session_id="sess-A07",
        )
        assert verdict.ownership_state.value == "degraded_conflicting_evidence"
        assert verdict.evidence_quality.value == "conflicting"
        assert verdict.is_converged is False
        assert verdict.degraded is True
        assert "conflicting_takeover_decisions" in verdict.diagnosis

    def test_A08_lifecycle_coordinator_surfaces_convergence_diagnostics(self):
        coordinator = get_lifecycle_coordinator()
        session_id = _uid()
        takeover_id = _uid()

        coordinator.on_handoff_dispatched(session_id=session_id, device_id="dev-A08")
        coordinator.on_takeover_requested(
            session_id=session_id,
            takeover_id=takeover_id,
            device_id="dev-A08",
        )
        coordinator.on_takeover_response(
            session_id=session_id,
            takeover_id=takeover_id,
            device_id="dev-A08",
            accepted=True,
        )
        first_verdict = adjudicate_takeover_ownership_convergence(
            takeover_id=takeover_id,
            device_id="dev-A08",
            session_id=session_id,
        )
        assert first_verdict.ownership_state.value == "delegated_takeover_confirmed"
        outcome = coordinator.on_takeover_response(
            session_id=session_id,
            takeover_id=takeover_id,
            device_id="dev-A08",
            accepted=False,
        )

        diag = outcome.extra.get("ownership_convergence", {})
        assert diag.get("ownership_state") == "degraded_conflicting_evidence"
        assert diag.get("evidence_quality") == "conflicting"
        assert diag.get("degraded") is True
        assert "conflicting_takeover_decisions" in diag.get("diagnosis", [])
