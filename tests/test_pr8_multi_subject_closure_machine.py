#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr8_multi_subject_closure_machine.py
================================================
PR-8: Multi-Subject Closure Machine — regression tests.

Covers:
-------
1.  Module sentinels: authority string and PR8 sentinel format.
2.  Policy sentinels: all six policy strings are non-empty and contain
    expected keywords.
3.  ClosureTerminalKind enum: all expected values present; is_terminal,
    is_success_family, is_partial_family, is_failure_family, requires_review.
4.  ReconcileRequiredTrigger enum: all five expected values present.
5.  ParticipantClosureRecord dataclass: construction and to_dict().
6.  ClosureCandidate dataclass: default construction, to_dict(), all fields.
7.  Nominal success path: all participants ready.
8.  Partial success path: some failed, some ready, no lost.
9.  Degraded completion path: some ready, some lost/degraded.
10. Takeover continuation path: primary lost, takeover candidate succeeded.
11. Recovery completion path: recovering device succeeded.
12. Participant lost path: primary lost, no takeover candidate.
13. Full failure path: no participant succeeded.
14. Reconcile trigger — participant_lost_no_takeover.
15. Reconcile trigger — ambiguous_failure_degraded_present.
16. Reconcile trigger — empty_formation_divergence.
17. Reconcile trigger — recovery_completion_unverified.
18. No reconcile on nominal success.
19. Operator/projection consumption gate: get_closure_output() returns
    ClosureCandidate with all required keys.
20. Canonical output type: terminal_kind is ClosureTerminalKind instance.
21. Bridge extension: multi_subject_truth_convergence_bridge now surfaces
    reconcile_required and recovery_completion in closure dict.
22. Bridge is_recovery flag propagation.
23. Empty bridge_snapshot: returns in_progress candidate without raising.
24. Singleton accessor: get_multi_subject_closure_machine() returns same
    instance on repeated calls.
25. Round-trip: build bridge → apply closure machine → to_dict().
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


# ===========================================================================
# 1. Module sentinels
# ===========================================================================


class TestModuleSentinels:
    def test_authority_sentinel_format(self):
        from core.multi_subject_closure_machine import (
            MULTI_SUBJECT_CLOSURE_MACHINE_AUTHORITY,
        )
        assert "MULTI_SUBJECT_CLOSURE_MACHINE" in MULTI_SUBJECT_CLOSURE_MACHINE_AUTHORITY
        assert "CANONICAL_GOVERNANCE_V1" in MULTI_SUBJECT_CLOSURE_MACHINE_AUTHORITY
        assert len(MULTI_SUBJECT_CLOSURE_MACHINE_AUTHORITY) > 40

    def test_pr8_sentinel_format(self):
        from core.multi_subject_closure_machine import (
            MULTI_SUBJECT_CLOSURE_MACHINE_PR8_SENTINEL,
        )
        assert "PR-8" in MULTI_SUBJECT_CLOSURE_MACHINE_PR8_SENTINEL
        assert len(MULTI_SUBJECT_CLOSURE_MACHINE_PR8_SENTINEL) > 20


# ===========================================================================
# 2. Policy sentinels
# ===========================================================================


class TestPolicySentinels:
    def test_v2_closure_authority_policy(self):
        from core.multi_subject_closure_machine import (
            V2_IS_SOLE_CANONICAL_CLOSURE_AUTHORITY_POLICY,
        )
        assert "V2" in V2_IS_SOLE_CANONICAL_CLOSURE_AUTHORITY_POLICY
        assert "sole" in V2_IS_SOLE_CANONICAL_CLOSURE_AUTHORITY_POLICY.lower()

    def test_no_parallel_closure_system_policy(self):
        from core.multi_subject_closure_machine import (
            NO_PARALLEL_CLOSURE_SYSTEM_POLICY,
        )
        assert "parallel" in NO_PARALLEL_CLOSURE_SYSTEM_POLICY.lower()

    def test_participant_local_terminal_not_final_truth_policy(self):
        from core.multi_subject_closure_machine import (
            PARTICIPANT_LOCAL_TERMINAL_NOT_FINAL_TRUTH_POLICY,
        )
        assert "participant" in PARTICIPANT_LOCAL_TERMINAL_NOT_FINAL_TRUTH_POLICY.lower()
        assert "final" in PARTICIPANT_LOCAL_TERMINAL_NOT_FINAL_TRUTH_POLICY.lower()

    def test_operator_must_consume_canonical_closure_output_policy(self):
        from core.multi_subject_closure_machine import (
            OPERATOR_MUST_CONSUME_CANONICAL_CLOSURE_OUTPUT_POLICY,
        )
        assert "operator" in OPERATOR_MUST_CONSUME_CANONICAL_CLOSURE_OUTPUT_POLICY.lower()
        assert "canonical" in OPERATOR_MUST_CONSUME_CANONICAL_CLOSURE_OUTPUT_POLICY.lower()

    def test_reconcile_required_triggers_explicit_policy(self):
        from core.multi_subject_closure_machine import (
            RECONCILE_REQUIRED_TRIGGERS_ARE_EXPLICIT_POLICY,
        )
        assert "reconcile" in RECONCILE_REQUIRED_TRIGGERS_ARE_EXPLICIT_POLICY.lower()
        assert "explicit" in RECONCILE_REQUIRED_TRIGGERS_ARE_EXPLICIT_POLICY.lower()

    def test_degraded_completion_in_main_chain_policy(self):
        from core.multi_subject_closure_machine import (
            DEGRADED_COMPLETION_IS_IN_MAIN_CHAIN_POLICY,
        )
        assert "degraded" in DEGRADED_COMPLETION_IS_IN_MAIN_CHAIN_POLICY.lower()
        assert "main" in DEGRADED_COMPLETION_IS_IN_MAIN_CHAIN_POLICY.lower()


# ===========================================================================
# 3. ClosureTerminalKind enum
# ===========================================================================


class TestClosureTerminalKind:
    def test_all_expected_values_present(self):
        from core.multi_subject_closure_machine import ClosureTerminalKind

        expected = {
            "in_progress",
            "success",
            "degraded_completion",
            "partial_success",
            "takeover_continuation",
            "recovery_completion",
            "participant_lost",
            "failed",
            "reconcile_required",
        }
        actual = {k.value for k in ClosureTerminalKind}
        assert expected == actual

    def test_is_terminal_false_for_in_progress(self):
        from core.multi_subject_closure_machine import ClosureTerminalKind

        assert not ClosureTerminalKind.in_progress.is_terminal

    def test_is_terminal_true_for_all_others(self):
        from core.multi_subject_closure_machine import ClosureTerminalKind

        for kind in ClosureTerminalKind:
            if kind == ClosureTerminalKind.in_progress:
                continue
            assert kind.is_terminal, f"{kind.value} should be terminal"

    def test_success_family(self):
        from core.multi_subject_closure_machine import ClosureTerminalKind

        assert ClosureTerminalKind.success.is_success_family
        assert ClosureTerminalKind.degraded_completion.is_success_family
        assert not ClosureTerminalKind.partial_success.is_success_family

    def test_partial_family(self):
        from core.multi_subject_closure_machine import ClosureTerminalKind

        assert ClosureTerminalKind.partial_success.is_partial_family
        assert ClosureTerminalKind.takeover_continuation.is_partial_family
        assert ClosureTerminalKind.recovery_completion.is_partial_family
        assert not ClosureTerminalKind.success.is_partial_family

    def test_failure_family(self):
        from core.multi_subject_closure_machine import ClosureTerminalKind

        assert ClosureTerminalKind.participant_lost.is_failure_family
        assert ClosureTerminalKind.failed.is_failure_family
        assert not ClosureTerminalKind.success.is_failure_family

    def test_requires_review_for_non_success_terminal(self):
        from core.multi_subject_closure_machine import ClosureTerminalKind

        for kind in ClosureTerminalKind:
            if kind in (ClosureTerminalKind.success, ClosureTerminalKind.in_progress):
                assert not kind.requires_review, f"{kind.value} should not require review"
            else:
                assert kind.requires_review, f"{kind.value} should require review"


# ===========================================================================
# 4. ReconcileRequiredTrigger enum
# ===========================================================================


class TestReconcileRequiredTrigger:
    def test_all_expected_values_present(self):
        from core.multi_subject_closure_machine import ReconcileRequiredTrigger

        expected = {
            "participant_lost_no_takeover",
            "conflicting_participant_signals",
            "empty_formation_divergence",
            "ambiguous_failure_degraded_present",
            "recovery_completion_unverified",
        }
        actual = {t.value for t in ReconcileRequiredTrigger}
        assert expected == actual


# ===========================================================================
# 5. ParticipantClosureRecord
# ===========================================================================


class TestParticipantClosureRecord:
    def test_construction_and_to_dict(self):
        from core.multi_subject_closure_machine import ParticipantClosureRecord

        rec = ParticipantClosureRecord(
            device_id="dev-a",
            role="primary",
            state="ready",
            formation_role="primary_execution_device",
            is_source=True,
            is_recovery=False,
        )
        d = rec.to_dict()
        assert d["device_id"] == "dev-a"
        assert d["role"] == "primary"
        assert d["state"] == "ready"
        assert d["is_source"] is True
        assert d["is_recovery"] is False

    def test_defaults(self):
        from core.multi_subject_closure_machine import ParticipantClosureRecord

        rec = ParticipantClosureRecord(
            device_id="dev-b",
            role="assistant",
            state="degraded",
            formation_role="support_device",
        )
        assert rec.is_source is False
        assert rec.is_recovery is False


# ===========================================================================
# 6. ClosureCandidate dataclass
# ===========================================================================


class TestClosureCandidate:
    def test_default_construction(self):
        from core.multi_subject_closure_machine import (
            ClosureCandidate,
            ClosureTerminalKind,
        )

        c = ClosureCandidate()
        assert c.terminal_kind == ClosureTerminalKind.in_progress
        assert c.is_terminal is False
        assert c.reconcile_required is False
        assert c.reconcile_triggers == []

    def test_to_dict_has_required_keys(self):
        from core.multi_subject_closure_machine import ClosureCandidate

        c = ClosureCandidate()
        d = c.to_dict()
        required = {
            "terminal_kind",
            "is_terminal",
            "reconcile_required",
            "reconcile_triggers",
            "participants",
            "participant_count",
            "success_count",
            "degraded_count",
            "lost_count",
            "failed_count",
            "suspended_count",
            "takeover_candidate_device_id",
            "authority",
            "bridge_completion_state",
        }
        assert required.issubset(d.keys())


# ===========================================================================
# Helpers: build minimal bridge snapshots for test scenarios
# ===========================================================================


def _bridge(
    completion_state: str,
    participants,
    takeover_candidate: str | None = None,
    success=0, degraded=0, lost=0, failed=0, suspended=0,
):
    return {
        "authority": "BRIDGE_AUTHORITY",
        "participants": participants,
        "participant_roles": {p["device_id"]: p["role"] for p in participants},
        "failure_isolation": {
            "lost": [p["device_id"] for p in participants if p["state"] == "lost"],
            "degraded": [p["device_id"] for p in participants if p["state"] == "degraded"],
            "failed": [p["device_id"] for p in participants if p["state"] == "failed"],
            "suspended": [p["device_id"] for p in participants if p["state"] == "suspended"],
            "takeover_candidate": takeover_candidate,
        },
        "counts": {
            "participants": len(participants),
            "success": success,
            "degraded": degraded,
            "lost": lost,
            "failed": failed,
            "suspended": suspended,
        },
        "closure": {
            "completion_state": completion_state,
            "terminal": True,
            "requires_review": completion_state != "success",
            "reconcile_required": False,
            "canonical_truth_status": "converged" if participants else "partial",
        },
    }


def _p(device_id, role, state, is_recovery=False):
    return {
        "device_id": device_id,
        "role": role,
        "state": state,
        "formation_role": "primary_execution_device" if role == "primary" else "support_device",
        "is_source": False,
        "is_recovery": is_recovery,
    }


# ===========================================================================
# 7. Nominal success
# ===========================================================================


class TestNominalSuccess:
    def test_all_participants_success(self):
        from core.multi_subject_closure_machine import (
            ClosureTerminalKind,
            build_closure_candidate,
        )

        snapshot = _bridge(
            "success",
            [_p("dev-a", "primary", "ready"), _p("dev-b", "assistant", "ready")],
            success=2,
        )
        c = build_closure_candidate(snapshot)
        assert c.terminal_kind == ClosureTerminalKind.success
        assert c.is_terminal is True
        assert c.reconcile_required is False
        assert c.success_count == 2

    def test_success_is_not_requires_review(self):
        from core.multi_subject_closure_machine import (
            ClosureTerminalKind,
            build_closure_candidate,
        )

        snapshot = _bridge(
            "success",
            [_p("dev-a", "primary", "ready")],
            success=1,
        )
        c = build_closure_candidate(snapshot)
        assert not c.terminal_kind.requires_review


# ===========================================================================
# 8. Partial success
# ===========================================================================


class TestPartialSuccess:
    def test_some_failed_some_ready(self):
        from core.multi_subject_closure_machine import (
            ClosureTerminalKind,
            build_closure_candidate,
        )

        snapshot = _bridge(
            "partial_success",
            [_p("dev-a", "primary", "ready"), _p("dev-b", "assistant", "failed")],
            success=1, failed=1,
        )
        c = build_closure_candidate(snapshot)
        assert c.terminal_kind == ClosureTerminalKind.partial_success
        assert c.is_terminal is True
        assert c.terminal_kind.requires_review

    def test_partial_success_no_reconcile(self):
        from core.multi_subject_closure_machine import build_closure_candidate

        snapshot = _bridge(
            "partial_success",
            [_p("dev-a", "primary", "ready"), _p("dev-b", "assistant", "failed")],
            success=1, failed=1,
        )
        c = build_closure_candidate(snapshot)
        assert c.reconcile_required is False


# ===========================================================================
# 9. Degraded completion
# ===========================================================================


class TestDegradedCompletion:
    def test_some_ready_some_lost(self):
        from core.multi_subject_closure_machine import (
            ClosureTerminalKind,
            build_closure_candidate,
        )

        snapshot = _bridge(
            "degraded_completion",
            [_p("dev-a", "primary", "ready"), _p("dev-b", "assistant", "lost")],
            success=1, lost=1,
        )
        c = build_closure_candidate(snapshot)
        assert c.terminal_kind == ClosureTerminalKind.degraded_completion
        assert c.is_terminal is True
        # degraded_completion IS in success family per our design
        assert c.terminal_kind.is_success_family

    def test_degraded_completion_is_terminal(self):
        from core.multi_subject_closure_machine import (
            ClosureTerminalKind,
            build_closure_candidate,
        )

        snapshot = _bridge(
            "degraded_completion",
            [_p("dev-a", "primary", "ready"), _p("dev-b", "assistant", "degraded")],
            success=1, degraded=1,
        )
        c = build_closure_candidate(snapshot)
        assert c.is_terminal is True


# ===========================================================================
# 10. Takeover continuation
# ===========================================================================


class TestTakeoverContinuation:
    def test_primary_lost_takeover_candidate_succeeded(self):
        from core.multi_subject_closure_machine import (
            ClosureTerminalKind,
            build_closure_candidate,
        )

        snapshot = _bridge(
            "takeover_continuation",
            [
                _p("dev-primary", "primary", "lost"),
                _p("dev-fallback", "takeover_candidate", "ready"),
            ],
            takeover_candidate="dev-fallback",
            success=1, lost=1,
        )
        c = build_closure_candidate(snapshot)
        assert c.terminal_kind == ClosureTerminalKind.takeover_continuation
        assert c.takeover_candidate_device_id == "dev-fallback"
        assert c.is_terminal is True
        assert c.reconcile_required is False

    def test_takeover_continuation_is_partial_family(self):
        from core.multi_subject_closure_machine import ClosureTerminalKind

        assert ClosureTerminalKind.takeover_continuation.is_partial_family


# ===========================================================================
# 11. Recovery completion
# ===========================================================================


class TestRecoveryCompletion:
    def test_recovering_device_succeeded(self):
        from core.multi_subject_closure_machine import (
            ClosureTerminalKind,
            build_closure_candidate,
        )

        snapshot = _bridge(
            "partial_success",
            [
                _p("dev-primary", "primary", "ready"),
                _p("dev-recovery", "assistant", "ready", is_recovery=True),
            ],
            success=2,
        )
        c = build_closure_candidate(
            snapshot,
            recovery_device_ids=["dev-recovery"],
        )
        assert c.terminal_kind == ClosureTerminalKind.recovery_completion
        assert c.is_terminal is True

    def test_recovery_completion_unverified_trigger_absent_when_recovery_ids_provided(self):
        from core.multi_subject_closure_machine import (
            ReconcileRequiredTrigger,
            build_closure_candidate,
        )

        snapshot = _bridge(
            "partial_success",
            [_p("dev-r", "assistant", "ready", is_recovery=True)],
            success=1,
        )
        c = build_closure_candidate(
            snapshot, recovery_device_ids=["dev-r"]
        )
        assert (
            ReconcileRequiredTrigger.recovery_completion_unverified.value
            not in c.reconcile_triggers
        )


# ===========================================================================
# 12. Participant lost
# ===========================================================================


class TestParticipantLost:
    def test_primary_lost_no_takeover(self):
        from core.multi_subject_closure_machine import (
            ClosureTerminalKind,
            build_closure_candidate,
        )

        snapshot = _bridge(
            "failed",
            [
                _p("dev-primary", "primary", "lost"),
                _p("dev-assistant", "assistant", "failed"),
            ],
            lost=1, failed=1,
        )
        c = build_closure_candidate(snapshot)
        assert c.terminal_kind == ClosureTerminalKind.participant_lost
        assert c.is_terminal is True

    def test_participant_lost_is_failure_family(self):
        from core.multi_subject_closure_machine import ClosureTerminalKind

        assert ClosureTerminalKind.participant_lost.is_failure_family


# ===========================================================================
# 13. Full failure
# ===========================================================================


class TestFullFailure:
    def test_no_participant_succeeded(self):
        from core.multi_subject_closure_machine import (
            ClosureTerminalKind,
            build_closure_candidate,
        )

        snapshot = _bridge(
            "failed",
            [
                _p("dev-a", "primary", "failed"),
                _p("dev-b", "assistant", "failed"),
            ],
            failed=2,
        )
        c = build_closure_candidate(snapshot)
        assert c.terminal_kind == ClosureTerminalKind.failed
        assert c.is_terminal is True
        assert c.success_count == 0


# ===========================================================================
# 14. Reconcile trigger — participant_lost_no_takeover
# ===========================================================================


class TestReconcileTriggerParticipantLost:
    def test_trigger_fires_when_primary_lost_and_no_takeover(self):
        from core.multi_subject_closure_machine import (
            ReconcileRequiredTrigger,
            build_closure_candidate,
        )

        snapshot = _bridge(
            "failed",
            [_p("dev-primary", "primary", "lost")],
            lost=1,
        )
        c = build_closure_candidate(snapshot)
        assert c.reconcile_required is True
        assert (
            ReconcileRequiredTrigger.participant_lost_no_takeover.value
            in c.reconcile_triggers
        )


# ===========================================================================
# 15. Reconcile trigger — ambiguous_failure_degraded_present
# ===========================================================================


class TestReconcileTriggerAmbiguousFailure:
    def test_trigger_fires_when_failed_and_degraded_present(self):
        from core.multi_subject_closure_machine import (
            ReconcileRequiredTrigger,
            build_closure_candidate,
        )

        snapshot = _bridge(
            "failed",
            [
                _p("dev-a", "primary", "failed"),
                _p("dev-b", "assistant", "degraded"),
            ],
            failed=1, degraded=1,
        )
        c = build_closure_candidate(snapshot)
        assert c.reconcile_required is True
        assert (
            ReconcileRequiredTrigger.ambiguous_failure_degraded_present.value
            in c.reconcile_triggers
        )


# ===========================================================================
# 16. Reconcile trigger — empty_formation_divergence
# ===========================================================================


class TestReconcileTriggerEmptyFormation:
    def test_trigger_fires_when_formation_has_members_but_no_participants(self):
        from core.multi_subject_closure_machine import (
            ReconcileRequiredTrigger,
            build_closure_candidate,
        )

        snapshot = _bridge("failed", [], failed=0)
        c = build_closure_candidate(snapshot, formation_member_count=3)
        assert c.reconcile_required is True
        assert (
            ReconcileRequiredTrigger.empty_formation_divergence.value
            in c.reconcile_triggers
        )


# ===========================================================================
# 17. Reconcile trigger — recovery_completion_unverified
# ===========================================================================


class TestReconcileTriggerRecoveryUnverified:
    def test_trigger_fires_when_recovery_ids_absent_but_recovery_state_detected(self):
        from core.multi_subject_closure_machine import (
            ClosureTerminalKind,
            ReconcileRequiredTrigger,
            build_closure_candidate,
        )

        snapshot = _bridge(
            "partial_success",
            [_p("dev-r", "assistant", "ready", is_recovery=True)],
            success=1,
        )
        # Pass NO recovery_device_ids — should fire unverified trigger
        c = build_closure_candidate(snapshot, recovery_device_ids=[])
        assert c.terminal_kind == ClosureTerminalKind.recovery_completion
        assert c.reconcile_required is True
        assert (
            ReconcileRequiredTrigger.recovery_completion_unverified.value
            in c.reconcile_triggers
        )


# ===========================================================================
# 18. No reconcile on nominal success
# ===========================================================================


class TestNoReconcileOnSuccess:
    def test_no_reconcile_on_success(self):
        from core.multi_subject_closure_machine import build_closure_candidate

        snapshot = _bridge(
            "success",
            [_p("dev-a", "primary", "ready"), _p("dev-b", "assistant", "ready")],
            success=2,
        )
        c = build_closure_candidate(snapshot)
        assert c.reconcile_required is False
        assert c.reconcile_triggers == []


# ===========================================================================
# 19. Operator/projection consumption gate
# ===========================================================================


class TestOperatorConsumptionGate:
    def test_get_closure_output_returns_closure_candidate(self):
        from core.multi_subject_closure_machine import (
            ClosureCandidate,
            get_closure_output,
        )

        snapshot = _bridge("success", [_p("dev-a", "primary", "ready")], success=1)
        result = get_closure_output(snapshot)
        assert isinstance(result, ClosureCandidate)

    def test_get_closure_output_has_all_required_keys(self):
        from core.multi_subject_closure_machine import get_closure_output

        snapshot = _bridge("success", [_p("dev-a", "primary", "ready")], success=1)
        d = get_closure_output(snapshot).to_dict()
        required_keys = {
            "terminal_kind",
            "is_terminal",
            "reconcile_required",
            "reconcile_triggers",
            "participants",
            "participant_count",
            "authority",
            "bridge_completion_state",
        }
        assert required_keys.issubset(d.keys())

    def test_get_closure_output_authority_is_machine_authority(self):
        from core.multi_subject_closure_machine import (
            MULTI_SUBJECT_CLOSURE_MACHINE_AUTHORITY,
            get_closure_output,
        )

        snapshot = _bridge("success", [_p("dev-a", "primary", "ready")], success=1)
        c = get_closure_output(snapshot)
        assert c.authority == MULTI_SUBJECT_CLOSURE_MACHINE_AUTHORITY


# ===========================================================================
# 20. Canonical output type is ClosureTerminalKind
# ===========================================================================


class TestCanonicalOutputType:
    def test_terminal_kind_is_enum_instance(self):
        from core.multi_subject_closure_machine import (
            ClosureTerminalKind,
            build_closure_candidate,
        )

        snapshot = _bridge("success", [_p("dev-a", "primary", "ready")], success=1)
        c = build_closure_candidate(snapshot)
        assert isinstance(c.terminal_kind, ClosureTerminalKind)


# ===========================================================================
# 21. Bridge extension: reconcile_required + recovery_completion
# ===========================================================================


class TestBridgeExtension:
    def test_bridge_closure_has_reconcile_required_field(self):
        from core.multi_subject_truth_convergence_bridge import (
            build_multi_subject_truth_bridge,
        )

        with patch(
            "core.multi_subject_truth_convergence_bridge._derive_signal",
            return_value={
                "readiness": "ready",
                "posture": "join_runtime",
                "busy": False,
                "orchestration_eligible": True,
                "reasons": [],
            },
        ):
            snap = build_multi_subject_truth_bridge(
                formation={
                    "primary_execution_device_id": "dev-a",
                    "members": [{"device_id": "dev-a", "role": "primary_execution_device"}],
                },
                participant_results=[{"device_id": "dev-a", "success": True}],
            )
        assert "reconcile_required" in snap["closure"]

    def test_bridge_closure_recovery_completion_state(self):
        from core.multi_subject_truth_convergence_bridge import (
            build_multi_subject_truth_bridge,
        )

        with patch(
            "core.multi_subject_truth_convergence_bridge._derive_signal",
            return_value={
                "readiness": "ready",
                "posture": "join_runtime",
                "busy": False,
                "orchestration_eligible": True,
                "reasons": [],
            },
        ):
            snap = build_multi_subject_truth_bridge(
                formation={
                    "primary_execution_device_id": "dev-primary",
                    "members": [
                        {"device_id": "dev-primary", "role": "primary_execution_device"},
                        {"device_id": "dev-recovery", "role": "support_device"},
                    ],
                },
                participant_results=[
                    {"device_id": "dev-primary", "success": True},
                    {"device_id": "dev-recovery", "success": True},
                ],
                recovery_device_ids=["dev-recovery"],
            )
        assert snap["closure"]["completion_state"] == "recovery_completion"

    def test_bridge_closure_includes_recovery_in_terminal_set(self):
        from core.multi_subject_truth_convergence_bridge import (
            build_multi_subject_truth_bridge,
        )

        with patch(
            "core.multi_subject_truth_convergence_bridge._derive_signal",
            return_value={
                "readiness": "ready",
                "posture": "join_runtime",
                "busy": False,
                "orchestration_eligible": True,
                "reasons": [],
            },
        ):
            snap = build_multi_subject_truth_bridge(
                formation={
                    "primary_execution_device_id": "dev-primary",
                    "members": [
                        {"device_id": "dev-primary", "role": "primary_execution_device"},
                        {"device_id": "dev-recovery", "role": "support_device"},
                    ],
                },
                participant_results=[
                    {"device_id": "dev-primary", "success": True},
                    {"device_id": "dev-recovery", "success": True},
                ],
                recovery_device_ids=["dev-recovery"],
            )
        assert snap["closure"]["terminal"] is True


# ===========================================================================
# 22. Bridge is_recovery flag propagation
# ===========================================================================


class TestBridgeIsRecoveryFlag:
    def test_is_recovery_flag_set_on_recovering_participant(self):
        from core.multi_subject_truth_convergence_bridge import (
            build_multi_subject_truth_bridge,
        )

        with patch(
            "core.multi_subject_truth_convergence_bridge._derive_signal",
            return_value={
                "readiness": "ready",
                "posture": "join_runtime",
                "busy": False,
                "orchestration_eligible": True,
                "reasons": [],
            },
        ):
            snap = build_multi_subject_truth_bridge(
                formation={
                    "primary_execution_device_id": "dev-a",
                    "members": [
                        {"device_id": "dev-a", "role": "primary_execution_device"},
                        {"device_id": "dev-b", "role": "support_device"},
                    ],
                },
                participant_results=[
                    {"device_id": "dev-a", "success": True},
                    {"device_id": "dev-b", "success": True},
                ],
                recovery_device_ids=["dev-b"],
            )
        participants_by_id = {p["device_id"]: p for p in snap["participants"]}
        assert participants_by_id["dev-b"]["is_recovery"] is True
        assert participants_by_id["dev-a"]["is_recovery"] is False


# ===========================================================================
# 22b. Bridge participant lifecycle machine projection
# ===========================================================================


class TestBridgeParticipantLifecycleMachine:
    def test_bridge_participant_contains_lifecycle_projection(self):
        from core.multi_subject_truth_convergence_bridge import (
            build_multi_subject_truth_bridge,
        )

        with patch(
            "core.multi_subject_truth_convergence_bridge._derive_signal",
            return_value={
                "readiness": "ready",
                "posture": "join_runtime",
                "busy": True,
                "orchestration_eligible": True,
                "reasons": [],
            },
        ):
            snap = build_multi_subject_truth_bridge(
                formation={
                    "primary_execution_device_id": "dev-a",
                    "members": [{"device_id": "dev-a", "role": "primary_execution_device"}],
                },
                participant_results=[],
            )
        participant = snap["participants"][0]
        assert participant["lifecycle_state"] == "executing"
        assert participant["lifecycle_trigger"] == "execution_started"
        assert participant["dispatch_eligible"] is True

    def test_bridge_suspended_participant_is_dispatch_ineligible(self):
        from core.multi_subject_truth_convergence_bridge import (
            build_multi_subject_truth_bridge,
        )

        with patch(
            "core.multi_subject_truth_convergence_bridge._derive_signal",
            return_value={
                "readiness": "suspended",
                "posture": "control_only",
                "busy": False,
                "orchestration_eligible": False,
                "reasons": ["manual_suspend"],
            },
        ):
            snap = build_multi_subject_truth_bridge(
                formation={
                    "primary_execution_device_id": "dev-a",
                    "members": [{"device_id": "dev-a", "role": "support_device"}],
                },
                participant_results=[],
            )
        participant = snap["participants"][0]
        assert participant["role"] == "suspended"
        assert participant["lifecycle_state"] == "suspended_state"
        assert participant["dispatch_eligible"] is False
        assert "dev-a" in snap["participant_lifecycle_machine"]["dispatch_blocked_participants"]

    def test_bridge_primary_loss_promotes_takeover_candidate_with_role_event(self):
        from core.multi_subject_truth_convergence_bridge import (
            build_multi_subject_truth_bridge,
        )

        with patch(
            "core.multi_subject_truth_convergence_bridge._derive_signal",
            return_value={
                "readiness": "ready",
                "posture": "join_runtime",
                "busy": False,
                "orchestration_eligible": True,
                "reasons": [],
            },
        ):
            snap = build_multi_subject_truth_bridge(
                formation={
                    "primary_execution_device_id": "dev-primary",
                    "members": [
                        {"device_id": "dev-primary", "role": "primary_execution_device"},
                        {"device_id": "dev-fallback", "role": "fallback_device"},
                    ],
                },
                participant_results=[
                    {"device_id": "dev-primary", "success": False, "error": "device lost"},
                    {"device_id": "dev-fallback", "success": True},
                ],
            )

        participants_by_id = {p["device_id"]: p for p in snap["participants"]}
        assert participants_by_id["dev-primary"]["role"] == "degraded"
        assert participants_by_id["dev-fallback"]["role"] == "takeover_candidate"
        assert participants_by_id["dev-fallback"]["lifecycle_state"] == "takeover_candidate_state"
        assert any(
            event.get("event") == "promotion" and event.get("device_id") == "dev-fallback"
            for event in snap["role_lifecycle"]["events"]
        )


# ===========================================================================
# 23. Empty bridge_snapshot
# ===========================================================================


class TestEmptyBridgeSnapshot:
    def test_empty_dict_returns_in_progress(self):
        from core.multi_subject_closure_machine import (
            ClosureTerminalKind,
            build_closure_candidate,
        )

        c = build_closure_candidate({})
        assert c.terminal_kind == ClosureTerminalKind.in_progress
        assert c.is_terminal is False

    def test_none_input_returns_in_progress(self):
        from core.multi_subject_closure_machine import (
            ClosureTerminalKind,
            build_closure_candidate,
        )

        c = build_closure_candidate(None)  # type: ignore[arg-type]
        assert c.terminal_kind == ClosureTerminalKind.in_progress


# ===========================================================================
# 24. Singleton accessor
# ===========================================================================


class TestSingletonAccessor:
    def test_singleton_returns_same_instance(self):
        from core.multi_subject_closure_machine import (
            MultiSubjectClosureMachine,
            get_multi_subject_closure_machine,
        )

        a = get_multi_subject_closure_machine()
        b = get_multi_subject_closure_machine()
        assert a is b
        assert isinstance(a, MultiSubjectClosureMachine)


# ===========================================================================
# 25. Round-trip: bridge → closure machine → to_dict
# ===========================================================================


class TestRoundTrip:
    def test_bridge_to_closure_machine_round_trip(self):
        from core.multi_subject_closure_machine import (
            ClosureTerminalKind,
            build_closure_candidate,
        )
        from core.multi_subject_truth_convergence_bridge import (
            build_multi_subject_truth_bridge,
        )

        with patch(
            "core.multi_subject_truth_convergence_bridge._derive_signal",
            return_value={
                "readiness": "ready",
                "posture": "join_runtime",
                "busy": False,
                "orchestration_eligible": True,
                "reasons": [],
            },
        ):
            bridge_snap = build_multi_subject_truth_bridge(
                formation={
                    "primary_execution_device_id": "dev-primary",
                    "members": [
                        {"device_id": "dev-primary", "role": "primary_execution_device"},
                        {"device_id": "dev-fallback", "role": "fallback_device"},
                    ],
                },
                participant_results=[
                    {"device_id": "dev-primary", "success": False, "error": "device offline"},
                    {"device_id": "dev-fallback", "success": True},
                ],
            )

        candidate = build_closure_candidate(bridge_snap)
        d = candidate.to_dict()

        assert d["terminal_kind"] == ClosureTerminalKind.takeover_continuation.value
        assert d["is_terminal"] is True
        assert d["takeover_candidate_device_id"] == "dev-fallback"
        assert "MULTI_SUBJECT_CLOSURE_MACHINE" in d["authority"]
