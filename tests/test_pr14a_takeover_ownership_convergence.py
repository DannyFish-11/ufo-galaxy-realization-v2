"""PR-14A: Takeover ownership convergence adjudication regression coverage."""

from __future__ import annotations

import uuid

import pytest

try:
    from core.android_delegated_runtime_lifecycle_coordinator import (
        get_lifecycle_coordinator,
        reset_lifecycle_coordinator,
    )
    from core.android_participant_session_state import (
        get_participant_session,
        reset_participant_session_runtime,
    )
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

    def test_A09_stale_takeover_response_forces_revalidation_before_acceptance(self):
        coordinator = get_lifecycle_coordinator()
        session_id = _uid()
        takeover_id = _uid()
        coordinator.on_handoff_dispatched(session_id=session_id, device_id="dev-A09")
        coordinator.on_takeover_requested(
            session_id=session_id,
            takeover_id=takeover_id,
            device_id="dev-A09",
        )

        outcome = coordinator.on_takeover_response(
            session_id=session_id,
            takeover_id=takeover_id,
            device_id="dev-A09",
            accepted=True,
            metadata={"is_stale": True},
        )
        assert outcome.extra.get("effective_accepted") is False
        assert outcome.extra.get("takeover_gate_decision") == "force_revalidate_suspend"
        assert "authority_boundary_requires_revalidation" in outcome.extra.get(
            "takeover_gate_reasons", []
        )
        authority = outcome.extra.get("authority_boundary", {})
        assert authority.get("permission_level") == "suggestion_only"
        rec = get_participant_session(session_id)
        assert rec is not None
        assert rec.phase.value == "handoff_dispatched"

    def test_A10_takeover_response_surfaces_session_axis_and_proof_quality(self):
        coordinator = get_lifecycle_coordinator()
        session_id = _uid()
        takeover_id = _uid()
        coordinator.on_handoff_dispatched(session_id=session_id, device_id="dev-A10")
        coordinator.on_takeover_requested(
            session_id=session_id,
            takeover_id=takeover_id,
            device_id="dev-A10",
        )

        outcome = coordinator.on_takeover_response(
            session_id=session_id,
            takeover_id=takeover_id,
            device_id="dev-A10",
            accepted=True,
            metadata={
                "runtime_attachment_session_id": "att-A10",
                "durable_session_id": "dur-A10",
                "recovery_id": "rec-A10",
                "continuity_semantics": "resume",
            },
        )
        axis = outcome.extra.get("session_axis", {})
        assert axis.get("runtime_session_id") == session_id
        assert axis.get("runtime_attachment_session_id") == "att-A10"
        assert axis.get("durable_session_id") == "dur-A10"
        assert axis.get("rebind_recovery_id") == "rec-A10"
        proof = outcome.extra.get("ownership_proof_quality", {})
        assert "proof_class" in proof
        assert "is_sufficient_for_closure" in proof
