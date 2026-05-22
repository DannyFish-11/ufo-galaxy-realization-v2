"""tests/test_android_continuity_recovery_state_router.py
===========================================================
PR-4v2-Recovery regression suite — Android continuity recovery-state router
and V2 explicit recovery-state consumption.

Problem statement
-----------------
Android continuity recovery state semantics exist but V2 did not consume them
through explicit canonical routes.  This PR implements a real cross-repo
recovery-state routing model so Android recovery phases are explicitly routed
to V2 canonical handling behaviors rather than remaining as declared-but-
unconsumed metadata.

Acceptance criteria
-------------------
* Each Android recovery-state category maps to the intended V2 route.
* Stale recovery artifacts are rejected outright (no canonical state mutation).
* Reconciliation-required states trigger the reconciliation path signal.
* Advisory recovered-inflight evidence does not produce canonical closure.
* Lost-inflight routes to closure review, not to canonical completion.
* Reconnect-initiated and recovery-in-progress route to mark_recovery_pending.
* Unknown phases are handled conservatively as advisory evidence (degraded).
* Recovery-state handling integrates with android_participant_truth_ingress.
* All policies are observable as importable, non-empty POLICY:: sentinels.

Coverage groups
---------------
A.  Sentinel and policy accessibility — all constants importable and well-formed.
B.  AndroidRecoveryPhase enum — all phases parseable, unknown fallback.
C.  V2RecoveryRoute enum — all routes enumerable.
D.  route_android_recovery_state — explicit phase-to-route mapping.
    D01 reconnect_initiated → mark_recovery_pending
    D02 recovery_in_progress → mark_recovery_pending
    D03 recovered_inflight → accept_advisory_evidence (NOT closure)
    D04 stale_recovery_artifact → reject_stale_artifact
    D05 reconciliation_required → trigger_reconciliation
    D06 lost_inflight → require_closure_review
    D07 unknown → accept_advisory_evidence (degraded)
E.  RecoveryStateRoutingDecision flags.
    E01 stale_recovery_artifact: is_canonical_closure_blocked=True
    E02 reconciliation_required: is_canonical_closure_blocked=True
    E03 lost_inflight: is_canonical_closure_blocked=True
    E04 recovered_inflight: is_advisory_only=True, is_canonical_closure_blocked=False
    E05 mark_recovery_pending: is_advisory_only=False, is_canonical_closure_blocked=False
    E06 unknown: is_degraded=True
F.  extract_recovery_phase_from_payload — field alias extraction.
    F01 "recovery_phase" field
    F02 "recovery_state" field
    F03 "continuity_recovery_phase" field
    F04 nested "recovery_state" sub-dict
    F05 unknown for absent/empty
    F06 unknown for malformed input
G.  route_recovery_state_from_payload — end-to-end convenience wrapper.
    G01 valid phase in payload
    G02 missing phase → unknown route
    G03 raw_phase_str captured correctly
H.  RecoveryStateRoutingDecision serialisation.
    H01 to_dict contains all required keys
    H02 to_json round-trips
    H03 sentinel in to_dict output
I.  Integration with android_participant_truth_ingress.
    I01 recovery_state truth kind is parseable
    I02 stale_recovery_artifact routes to reject (reject_reason set)
    I03 reconciliation_required routes to reconciliation (reject_reason set)
    I04 lost_inflight routes to closure review (reject_reason set)
    I05 recovered_inflight is advisory (local_only=True, no reject_reason)
    I06 reconnect_initiated is advisory pending (local_only=True, no reject_reason)
    I07 recovery_state does NOT affect_canonical_state()
    I08 new policy sentinel importable from ingress module
J.  Cross-invariant: advisory routes do not produce canonical closure.
    J01 recovered_inflight: was_reconciled=False, local_only=True
    J02 advisory route canonical_update does not contain "canonical_closure"
K.  Phase-to-route completeness — every phase maps to a route.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest


# ===========================================================================
# A — Sentinel and policy accessibility
# ===========================================================================


class TestSentinelAndPolicyAccessibility:
    """A01–A10: All sentinels and policy constants importable and well-formed."""

    def test_A01_router_sentinel_importable(self) -> None:
        from core.android_continuity_recovery_state_router import (
            ANDROID_CONTINUITY_RECOVERY_STATE_ROUTER_SENTINEL,
        )
        assert isinstance(ANDROID_CONTINUITY_RECOVERY_STATE_ROUTER_SENTINEL, str)
        assert len(ANDROID_CONTINUITY_RECOVERY_STATE_ROUTER_SENTINEL) > 0
        assert "PR4V2_RECOVERY" in ANDROID_CONTINUITY_RECOVERY_STATE_ROUTER_SENTINEL

    def test_A02_contract_version_importable(self) -> None:
        from core.android_continuity_recovery_state_router import (
            ANDROID_CONTINUITY_RECOVERY_STATE_ROUTER_CONTRACT_VERSION,
        )
        assert isinstance(ANDROID_CONTINUITY_RECOVERY_STATE_ROUTER_CONTRACT_VERSION, str)
        assert "4v2" in ANDROID_CONTINUITY_RECOVERY_STATE_ROUTER_CONTRACT_VERSION.lower()

    def test_A03_stale_artifact_policy_importable(self) -> None:
        from core.android_continuity_recovery_state_router import (
            STALE_RECOVERY_ARTIFACT_MUST_BE_REJECTED_POLICY,
        )
        assert isinstance(STALE_RECOVERY_ARTIFACT_MUST_BE_REJECTED_POLICY, str)
        assert STALE_RECOVERY_ARTIFACT_MUST_BE_REJECTED_POLICY.startswith("POLICY::")

    def test_A04_reconciliation_required_policy_importable(self) -> None:
        from core.android_continuity_recovery_state_router import (
            RECONCILIATION_REQUIRED_MUST_TRIGGER_RECONCILIATION_PATH_POLICY,
        )
        assert isinstance(
            RECONCILIATION_REQUIRED_MUST_TRIGGER_RECONCILIATION_PATH_POLICY, str
        )
        assert RECONCILIATION_REQUIRED_MUST_TRIGGER_RECONCILIATION_PATH_POLICY.startswith(
            "POLICY::"
        )

    def test_A05_lost_inflight_policy_importable(self) -> None:
        from core.android_continuity_recovery_state_router import (
            LOST_INFLIGHT_REQUIRES_RECONCILIATION_OR_CLOSURE_REVIEW_POLICY,
        )
        assert isinstance(
            LOST_INFLIGHT_REQUIRES_RECONCILIATION_OR_CLOSURE_REVIEW_POLICY, str
        )
        assert LOST_INFLIGHT_REQUIRES_RECONCILIATION_OR_CLOSURE_REVIEW_POLICY.startswith(
            "POLICY::"
        )

    def test_A06_recovered_inflight_advisory_policy_importable(self) -> None:
        from core.android_continuity_recovery_state_router import (
            RECOVERED_INFLIGHT_IS_ADVISORY_ONLY_POLICY,
        )
        assert isinstance(RECOVERED_INFLIGHT_IS_ADVISORY_ONLY_POLICY, str)
        assert RECOVERED_INFLIGHT_IS_ADVISORY_ONLY_POLICY.startswith("POLICY::")

    def test_A07_reconnect_initiated_policy_importable(self) -> None:
        from core.android_continuity_recovery_state_router import (
            RECONNECT_INITIATED_IS_NOT_COMPLETION_POLICY,
        )
        assert isinstance(RECONNECT_INITIATED_IS_NOT_COMPLETION_POLICY, str)
        assert RECONNECT_INITIATED_IS_NOT_COMPLETION_POLICY.startswith("POLICY::")

    def test_A08_recovery_in_progress_policy_importable(self) -> None:
        from core.android_continuity_recovery_state_router import (
            RECOVERY_IN_PROGRESS_IS_TRANSIENT_POLICY,
        )
        assert isinstance(RECOVERY_IN_PROGRESS_IS_TRANSIENT_POLICY, str)
        assert RECOVERY_IN_PROGRESS_IS_TRANSIENT_POLICY.startswith("POLICY::")

    def test_A09_unknown_phase_policy_importable(self) -> None:
        from core.android_continuity_recovery_state_router import (
            UNKNOWN_RECOVERY_PHASE_MUST_BE_HANDLED_CONSERVATIVELY_POLICY,
        )
        assert isinstance(
            UNKNOWN_RECOVERY_PHASE_MUST_BE_HANDLED_CONSERVATIVELY_POLICY, str
        )
        assert UNKNOWN_RECOVERY_PHASE_MUST_BE_HANDLED_CONSERVATIVELY_POLICY.startswith(
            "POLICY::"
        )

    def test_A10_all_policies_have_policy_prefix(self) -> None:
        import core.android_continuity_recovery_state_router as mod
        policy_constants = [
            mod.STALE_RECOVERY_ARTIFACT_MUST_BE_REJECTED_POLICY,
            mod.RECONCILIATION_REQUIRED_MUST_TRIGGER_RECONCILIATION_PATH_POLICY,
            mod.LOST_INFLIGHT_REQUIRES_RECONCILIATION_OR_CLOSURE_REVIEW_POLICY,
            mod.RECOVERED_INFLIGHT_IS_ADVISORY_ONLY_POLICY,
            mod.RECONNECT_INITIATED_IS_NOT_COMPLETION_POLICY,
            mod.RECOVERY_IN_PROGRESS_IS_TRANSIENT_POLICY,
            mod.UNKNOWN_RECOVERY_PHASE_MUST_BE_HANDLED_CONSERVATIVELY_POLICY,
        ]
        for p in policy_constants:
            assert p.startswith("POLICY::"), f"Policy missing POLICY:: prefix: {p[:60]}"


# ===========================================================================
# B — AndroidRecoveryPhase enum
# ===========================================================================


class TestAndroidRecoveryPhase:
    """B01–B09: AndroidRecoveryPhase enum coverage."""

    def _phase(self, v: str):
        from core.android_continuity_recovery_state_router import AndroidRecoveryPhase
        return AndroidRecoveryPhase.from_string(v)

    def test_B01_reconnect_initiated(self) -> None:
        from core.android_continuity_recovery_state_router import AndroidRecoveryPhase
        assert self._phase("reconnect_initiated") == AndroidRecoveryPhase.reconnect_initiated

    def test_B02_recovery_in_progress(self) -> None:
        from core.android_continuity_recovery_state_router import AndroidRecoveryPhase
        assert self._phase("recovery_in_progress") == AndroidRecoveryPhase.recovery_in_progress

    def test_B03_recovered_inflight(self) -> None:
        from core.android_continuity_recovery_state_router import AndroidRecoveryPhase
        assert self._phase("recovered_inflight") == AndroidRecoveryPhase.recovered_inflight

    def test_B04_stale_recovery_artifact(self) -> None:
        from core.android_continuity_recovery_state_router import AndroidRecoveryPhase
        assert self._phase("stale_recovery_artifact") == AndroidRecoveryPhase.stale_recovery_artifact

    def test_B05_reconciliation_required(self) -> None:
        from core.android_continuity_recovery_state_router import AndroidRecoveryPhase
        assert self._phase("reconciliation_required") == AndroidRecoveryPhase.reconciliation_required

    def test_B06_lost_inflight(self) -> None:
        from core.android_continuity_recovery_state_router import AndroidRecoveryPhase
        assert self._phase("lost_inflight") == AndroidRecoveryPhase.lost_inflight

    def test_B07_unknown_explicit(self) -> None:
        from core.android_continuity_recovery_state_router import AndroidRecoveryPhase
        assert self._phase("unknown") == AndroidRecoveryPhase.unknown

    def test_B08_unknown_fallback_for_unrecognised(self) -> None:
        from core.android_continuity_recovery_state_router import AndroidRecoveryPhase
        assert self._phase("some_future_phase") == AndroidRecoveryPhase.unknown

    def test_B09_unknown_fallback_for_none(self) -> None:
        from core.android_continuity_recovery_state_router import AndroidRecoveryPhase
        assert self._phase(None) == AndroidRecoveryPhase.unknown  # type: ignore[arg-type]


# ===========================================================================
# C — V2RecoveryRoute enum
# ===========================================================================


class TestV2RecoveryRoute:
    """C01–C05: V2RecoveryRoute enum coverage."""

    def test_C01_all_routes_present(self) -> None:
        from core.android_continuity_recovery_state_router import V2RecoveryRoute
        routes = {r.value for r in V2RecoveryRoute}
        expected = {
            "reject_stale_artifact",
            "trigger_reconciliation",
            "require_closure_review",
            "accept_advisory_evidence",
            "mark_recovery_pending",
        }
        assert expected <= routes

    def test_C02_reject_stale_artifact_route(self) -> None:
        from core.android_continuity_recovery_state_router import V2RecoveryRoute
        assert V2RecoveryRoute("reject_stale_artifact") == V2RecoveryRoute.reject_stale_artifact

    def test_C03_trigger_reconciliation_route(self) -> None:
        from core.android_continuity_recovery_state_router import V2RecoveryRoute
        assert V2RecoveryRoute("trigger_reconciliation") == V2RecoveryRoute.trigger_reconciliation

    def test_C04_require_closure_review_route(self) -> None:
        from core.android_continuity_recovery_state_router import V2RecoveryRoute
        assert V2RecoveryRoute("require_closure_review") == V2RecoveryRoute.require_closure_review

    def test_C05_accept_advisory_evidence_route(self) -> None:
        from core.android_continuity_recovery_state_router import V2RecoveryRoute
        assert V2RecoveryRoute("accept_advisory_evidence") == V2RecoveryRoute.accept_advisory_evidence


# ===========================================================================
# D — route_android_recovery_state: phase-to-route mapping
# ===========================================================================


class TestRouteAndroidRecoveryState:
    """D01–D07: Each phase maps to the expected V2 route."""

    def _route(self, phase_str: str):
        from core.android_continuity_recovery_state_router import (
            AndroidRecoveryPhase,
            route_android_recovery_state,
        )
        phase = AndroidRecoveryPhase.from_string(phase_str)
        return route_android_recovery_state(phase)

    def test_D01_reconnect_initiated_mark_recovery_pending(self) -> None:
        from core.android_continuity_recovery_state_router import V2RecoveryRoute
        decision = self._route("reconnect_initiated")
        assert decision.v2_route == V2RecoveryRoute.mark_recovery_pending

    def test_D02_recovery_in_progress_mark_recovery_pending(self) -> None:
        from core.android_continuity_recovery_state_router import V2RecoveryRoute
        decision = self._route("recovery_in_progress")
        assert decision.v2_route == V2RecoveryRoute.mark_recovery_pending

    def test_D03_recovered_inflight_accept_advisory_not_closure(self) -> None:
        from core.android_continuity_recovery_state_router import V2RecoveryRoute
        decision = self._route("recovered_inflight")
        assert decision.v2_route == V2RecoveryRoute.accept_advisory_evidence
        # Critically: closure is NOT blocked — it remains advisory, but V2 must
        # not interpret this as canonical closure without further adjudication
        assert decision.is_advisory_only is True
        assert decision.is_canonical_closure_blocked is False

    def test_D04_stale_recovery_artifact_reject(self) -> None:
        from core.android_continuity_recovery_state_router import V2RecoveryRoute
        decision = self._route("stale_recovery_artifact")
        assert decision.v2_route == V2RecoveryRoute.reject_stale_artifact

    def test_D05_reconciliation_required_trigger_reconciliation(self) -> None:
        from core.android_continuity_recovery_state_router import V2RecoveryRoute
        decision = self._route("reconciliation_required")
        assert decision.v2_route == V2RecoveryRoute.trigger_reconciliation

    def test_D06_lost_inflight_require_closure_review(self) -> None:
        from core.android_continuity_recovery_state_router import V2RecoveryRoute
        decision = self._route("lost_inflight")
        assert decision.v2_route == V2RecoveryRoute.require_closure_review

    def test_D07_unknown_accept_advisory_degraded(self) -> None:
        from core.android_continuity_recovery_state_router import V2RecoveryRoute
        decision = self._route("unknown")
        assert decision.v2_route == V2RecoveryRoute.accept_advisory_evidence
        assert decision.is_degraded is True


# ===========================================================================
# E — RecoveryStateRoutingDecision flags
# ===========================================================================


class TestRecoveryStateRoutingDecisionFlags:
    """E01–E06: Routing decision flags are set correctly per phase."""

    def _decision(self, phase_str: str):
        from core.android_continuity_recovery_state_router import (
            AndroidRecoveryPhase,
            route_android_recovery_state,
        )
        return route_android_recovery_state(AndroidRecoveryPhase.from_string(phase_str))

    def test_E01_stale_artifact_closure_blocked(self) -> None:
        d = self._decision("stale_recovery_artifact")
        assert d.is_canonical_closure_blocked is True

    def test_E02_reconciliation_required_closure_blocked(self) -> None:
        d = self._decision("reconciliation_required")
        assert d.is_canonical_closure_blocked is True

    def test_E03_lost_inflight_closure_blocked(self) -> None:
        d = self._decision("lost_inflight")
        assert d.is_canonical_closure_blocked is True

    def test_E04_recovered_inflight_advisory_only_not_closure_blocked(self) -> None:
        d = self._decision("recovered_inflight")
        assert d.is_advisory_only is True
        assert d.is_canonical_closure_blocked is False

    def test_E05_mark_recovery_pending_not_advisory_not_closure_blocked(self) -> None:
        d = self._decision("reconnect_initiated")
        assert d.is_advisory_only is False
        assert d.is_canonical_closure_blocked is False

    def test_E06_unknown_is_degraded(self) -> None:
        d = self._decision("unknown")
        assert d.is_degraded is True

    def test_E07_known_phases_not_degraded(self) -> None:
        phases = [
            "reconnect_initiated",
            "recovery_in_progress",
            "recovered_inflight",
            "stale_recovery_artifact",
            "reconciliation_required",
            "lost_inflight",
        ]
        for p in phases:
            d = self._decision(p)
            assert d.is_degraded is False, f"Phase {p!r} should not be degraded"


# ===========================================================================
# F — extract_recovery_phase_from_payload
# ===========================================================================


class TestExtractRecoveryPhaseFromPayload:
    """F01–F06: Phase extraction from raw payload dicts."""

    def _extract(self, payload: Dict[str, Any]):
        from core.android_continuity_recovery_state_router import (
            extract_recovery_phase_from_payload,
        )
        return extract_recovery_phase_from_payload(payload)

    def test_F01_recovery_phase_field(self) -> None:
        from core.android_continuity_recovery_state_router import AndroidRecoveryPhase
        result = self._extract({"recovery_phase": "reconciliation_required"})
        assert result == AndroidRecoveryPhase.reconciliation_required

    def test_F02_recovery_state_field(self) -> None:
        from core.android_continuity_recovery_state_router import AndroidRecoveryPhase
        result = self._extract({"recovery_state": "stale_recovery_artifact"})
        assert result == AndroidRecoveryPhase.stale_recovery_artifact

    def test_F03_continuity_recovery_phase_field(self) -> None:
        from core.android_continuity_recovery_state_router import AndroidRecoveryPhase
        result = self._extract({"continuity_recovery_phase": "recovered_inflight"})
        assert result == AndroidRecoveryPhase.recovered_inflight

    def test_F04_nested_recovery_state_subdict(self) -> None:
        from core.android_continuity_recovery_state_router import AndroidRecoveryPhase
        result = self._extract({
            "recovery_state": {"recovery_phase": "lost_inflight"}
        })
        assert result == AndroidRecoveryPhase.lost_inflight

    def test_F05_unknown_for_absent_phase(self) -> None:
        from core.android_continuity_recovery_state_router import AndroidRecoveryPhase
        result = self._extract({})
        assert result == AndroidRecoveryPhase.unknown

    def test_F06_unknown_for_malformed_input(self) -> None:
        from core.android_continuity_recovery_state_router import AndroidRecoveryPhase
        assert self._extract(None) == AndroidRecoveryPhase.unknown  # type: ignore[arg-type]
        assert self._extract("not_a_dict") == AndroidRecoveryPhase.unknown  # type: ignore[arg-type]
        assert self._extract({"recovery_phase": 123}) == AndroidRecoveryPhase.unknown


# ===========================================================================
# G — route_recovery_state_from_payload
# ===========================================================================


class TestRouteRecoveryStateFromPayload:
    """G01–G03: Convenience wrapper end-to-end."""

    def _route_payload(self, payload: Dict[str, Any], **kwargs):
        from core.android_continuity_recovery_state_router import (
            route_recovery_state_from_payload,
        )
        return route_recovery_state_from_payload(payload, **kwargs)

    def test_G01_valid_phase_in_payload(self) -> None:
        from core.android_continuity_recovery_state_router import (
            AndroidRecoveryPhase,
            V2RecoveryRoute,
        )
        d = self._route_payload(
            {"recovery_phase": "reconciliation_required"},
            device_id="dev-1",
            session_id="sess-1",
        )
        assert d.recovery_phase == AndroidRecoveryPhase.reconciliation_required
        assert d.v2_route == V2RecoveryRoute.trigger_reconciliation
        assert d.device_id == "dev-1"
        assert d.session_id == "sess-1"

    def test_G02_missing_phase_gives_unknown_route(self) -> None:
        from core.android_continuity_recovery_state_router import (
            AndroidRecoveryPhase,
            V2RecoveryRoute,
        )
        d = self._route_payload({})
        assert d.recovery_phase == AndroidRecoveryPhase.unknown
        assert d.v2_route == V2RecoveryRoute.accept_advisory_evidence

    def test_G03_raw_phase_str_captured(self) -> None:
        d = self._route_payload({"recovery_phase": "stale_recovery_artifact"})
        assert d.raw_phase_str == "stale_recovery_artifact"


# ===========================================================================
# H — RecoveryStateRoutingDecision serialisation
# ===========================================================================


class TestRecoveryStateRoutingDecisionSerialisation:
    """H01–H03: to_dict / to_json output correctness."""

    def _make_decision(self, phase_str: str = "reconciliation_required"):
        from core.android_continuity_recovery_state_router import (
            AndroidRecoveryPhase,
            route_android_recovery_state,
        )
        return route_android_recovery_state(
            AndroidRecoveryPhase.from_string(phase_str),
            device_id="dev-42",
            session_id="sess-99",
            task_id="task-7",
        )

    def test_H01_to_dict_required_keys(self) -> None:
        d = self._make_decision().to_dict()
        required_keys = {
            "recovery_phase",
            "v2_route",
            "policy_reference",
            "diagnosis",
            "is_canonical_closure_blocked",
            "is_advisory_only",
            "is_degraded",
            "device_id",
            "session_id",
            "task_id",
            "raw_phase_str",
            "decided_at",
            "_sentinel",
            "_contract_version",
        }
        for key in required_keys:
            assert key in d, f"Missing key: {key!r}"

    def test_H02_to_json_round_trips(self) -> None:
        import json
        decision = self._make_decision("stale_recovery_artifact")
        json_str = decision.to_json()
        parsed = json.loads(json_str)
        assert parsed["recovery_phase"] == "stale_recovery_artifact"
        assert parsed["v2_route"] == "reject_stale_artifact"

    def test_H03_sentinel_in_to_dict(self) -> None:
        from core.android_continuity_recovery_state_router import (
            ANDROID_CONTINUITY_RECOVERY_STATE_ROUTER_SENTINEL,
        )
        d = self._make_decision().to_dict()
        assert d["_sentinel"] == ANDROID_CONTINUITY_RECOVERY_STATE_ROUTER_SENTINEL


# ===========================================================================
# I — Integration with android_participant_truth_ingress
# ===========================================================================


class TestIntegrationWithParticipantTruthIngress:
    """I01–I10: recovery_state truth kind integration."""

    def _make_message(self, recovery_phase: str, **overrides) -> Dict[str, Any]:
        msg: Dict[str, Any] = {
            "type": "recovery_state",
            "truth_kind": "recovery_state",
            "device_id": "dev-ingress-test",
            "session_id": "sess-ingress",
            "task_id": "task-ingress",
            "payload": {
                "recovery_phase": recovery_phase,
                "session_id": "sess-ingress",
                "task_id": "task-ingress",
            },
        }
        msg.update(overrides)
        return msg

    def test_I01_recovery_state_truth_kind_parseable(self) -> None:
        from core.android_participant_truth_ingress import AndroidParticipantTruthKind
        kind = AndroidParticipantTruthKind.from_string("recovery_state")
        assert kind == AndroidParticipantTruthKind.recovery_state

    def test_I02_stale_artifact_routes_to_reject(self) -> None:
        from core.android_participant_truth_ingress import (
            ingest_android_participant_truth_message,
        )
        msg = self._make_message("stale_recovery_artifact")
        outcome = ingest_android_participant_truth_message(msg)
        assert outcome.was_reconciled is False
        assert "stale" in outcome.reject_reason.lower()

    def test_I03_reconciliation_required_routes_to_reconciliation_path(self) -> None:
        from core.android_participant_truth_ingress import (
            ingest_android_participant_truth_message,
        )
        msg = self._make_message("reconciliation_required")
        outcome = ingest_android_participant_truth_message(msg)
        assert outcome.was_reconciled is False
        assert "reconciliation" in outcome.reject_reason.lower()

    def test_I04_lost_inflight_routes_to_closure_review(self) -> None:
        from core.android_participant_truth_ingress import (
            ingest_android_participant_truth_message,
        )
        msg = self._make_message("lost_inflight")
        outcome = ingest_android_participant_truth_message(msg)
        assert outcome.was_reconciled is False
        assert "closure" in outcome.reject_reason.lower() or "lost" in outcome.reject_reason.lower()

    def test_I05_recovered_inflight_is_advisory_local_only(self) -> None:
        from core.android_participant_truth_ingress import (
            ingest_android_participant_truth_message,
        )
        msg = self._make_message("recovered_inflight")
        outcome = ingest_android_participant_truth_message(msg)
        assert outcome.was_reconciled is False
        assert outcome.local_only is True
        assert outcome.reject_reason == ""

    def test_I06_reconnect_initiated_is_advisory_pending(self) -> None:
        from core.android_participant_truth_ingress import (
            ingest_android_participant_truth_message,
        )
        msg = self._make_message("reconnect_initiated")
        outcome = ingest_android_participant_truth_message(msg)
        assert outcome.was_reconciled is False
        assert outcome.local_only is True
        assert outcome.reject_reason == ""

    def test_I07_recovery_state_does_not_affect_canonical_state(self) -> None:
        from core.android_participant_truth_ingress import AndroidParticipantTruthKind
        assert not AndroidParticipantTruthKind.recovery_state.affects_canonical_state()

    def test_I08_new_policy_sentinel_importable_from_ingress(self) -> None:
        from core.android_participant_truth_ingress import (
            RECOVERY_STATE_MUST_BE_EXPLICITLY_ROUTED_POLICY,
        )
        assert isinstance(RECOVERY_STATE_MUST_BE_EXPLICITLY_ROUTED_POLICY, str)
        assert RECOVERY_STATE_MUST_BE_EXPLICITLY_ROUTED_POLICY.startswith("POLICY::")

    def test_I09_outcome_exposes_structured_recovery_routing(self) -> None:
        from core.android_participant_truth_ingress import (
            ingest_android_participant_truth_message,
        )
        msg = self._make_message("reconciliation_required")
        outcome = ingest_android_participant_truth_message(msg)
        assert outcome.recovery_state_routing["recovery_phase"] == "reconciliation_required"
        assert outcome.recovery_state_routing["v2_route"] == "trigger_reconciliation"
        assert outcome.recovery_state_routing["is_canonical_closure_blocked"] is True

    def test_I10_audit_event_includes_recovery_routing_and_policy(self, monkeypatch) -> None:
        import core.android_participant_truth_ingress as ingress

        captured: Dict[str, Any] = {}

        def _capture_event(**kwargs: Any) -> None:
            captured.update(kwargs)

        monkeypatch.setattr(ingress, "_REPLAY_AVAILABLE", True)
        monkeypatch.setattr(ingress, "_emit_runtime_event", _capture_event)

        outcome = ingress.ingest_android_participant_truth_message(
            self._make_message("stale_recovery_artifact")
        )

        assert outcome.replay_event_emitted is True
        assert captured["payload"]["policy"] == (
            ingress.RECOVERY_STATE_MUST_BE_EXPLICITLY_ROUTED_POLICY
        )
        assert captured["payload"]["recovery_state_routing"]["recovery_phase"] == (
            "stale_recovery_artifact"
        )
        assert captured["payload"]["recovery_state_routing"]["v2_route"] == (
            "reject_stale_artifact"
        )


# ===========================================================================
# J — Cross-invariant: advisory routes do not produce canonical closure
# ===========================================================================


class TestAdvisoryRoutesDoNotProduceCanonicalClosure:
    """J01–J02: Advisory evidence must never directly close canonical state."""

    def test_J01_recovered_inflight_was_reconciled_false_local_only(self) -> None:
        from core.android_participant_truth_ingress import (
            ingest_android_participant_truth_message,
        )
        msg = {
            "truth_kind": "recovery_state",
            "device_id": "dev-j01",
            "payload": {
                "recovery_phase": "recovered_inflight",
                "session_id": "sess-j01",
                "task_id": "task-j01",
            },
        }
        outcome = ingest_android_participant_truth_message(msg)
        assert outcome.was_reconciled is False
        assert outcome.local_only is True

    def test_J02_advisory_canonical_update_does_not_claim_closure(self) -> None:
        from core.android_participant_truth_ingress import (
            extract_participant_truth_envelope,
            reconcile_android_participant_truth,
        )
        msg = {
            "truth_kind": "recovery_state",
            "device_id": "dev-j02",
            "payload": {
                "recovery_phase": "recovered_inflight",
                "session_id": "sess-j02",
            },
        }
        env = extract_participant_truth_envelope(msg)
        outcome = reconcile_android_participant_truth(env)
        # canonical_update must not assert canonical closure
        assert "canonical_closure" not in outcome.canonical_update.lower()

    def test_J03_unknown_phase_observability_marks_degraded_route(self) -> None:
        from core.android_participant_truth_ingress import (
            get_last_reconciliation_outcome,
            ingest_android_participant_truth_message,
        )

        ingest_android_participant_truth_message({
            "truth_kind": "recovery_state",
            "device_id": "dev-j03",
            "payload": {
                "recovery_phase": "future_android_phase",
                "session_id": "sess-j03",
            },
        })

        outcome = get_last_reconciliation_outcome()
        assert outcome is not None
        assert outcome["recovery_state_routing"]["recovery_phase"] == "unknown"
        assert outcome["recovery_state_routing"]["is_degraded"] is True


# ===========================================================================
# K — Phase-to-route completeness
# ===========================================================================


class TestPhaseToRouteCompleteness:
    """K01: Every AndroidRecoveryPhase has an explicit V2RecoveryRoute mapping."""

    def test_K01_every_phase_maps_to_route(self) -> None:
        from core.android_continuity_recovery_state_router import (
            AndroidRecoveryPhase,
            route_android_recovery_state,
        )
        for phase in AndroidRecoveryPhase:
            decision = route_android_recovery_state(phase)
            assert decision.v2_route is not None, (
                f"Phase {phase.value!r} produced no v2_route"
            )
            assert decision.policy_reference.startswith("POLICY::"), (
                f"Phase {phase.value!r} policy reference missing POLICY:: prefix"
            )
            assert decision.diagnosis, (
                f"Phase {phase.value!r} produced empty diagnosis"
            )
