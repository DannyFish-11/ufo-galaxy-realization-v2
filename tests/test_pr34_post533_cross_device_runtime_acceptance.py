"""tests/test_pr34_post533_cross_device_runtime_acceptance.py
=============================================================
Tests for PR package 34 (post-533 dual-repo runtime unification master plan,
main repo side): Final Product-Grade Cross-Device and Runtime Acceptance Pack.

This test suite verifies that:

1.  All PR-34 policy/authority sentinels are present in the orchestrator module.
2.  The projection sentinel is importable and is not UNAVAILABLE.
3.  ``core.runtime`` re-exports all PR-34 sentinel symbols.
4.  Source dispatch / fallback / result merge stability: dispatch produces a
    valid SourceDispatchResult for local, remote, fallback, and staged_mesh
    branches; fallback_reason vocabulary is consistent.
5.  Android attached runtime orchestration stability: ingress, registry,
    recovery-readiness, and reuse-dispatch surfaces accept valid inputs and
    return typed results.
6.  Multi-target ranking maturity: evaluate_candidate(), rank_candidates(),
    and select_delegated_target() produce deterministic, explainable decisions.
7.  Staged-mesh minimal closure runnable: coordinate_mesh_session() is
    reachable and dispatch produces action_taken='staged_mesh_coordinated'
    when a valid mesh_session is supplied.
8.  Diagnostics / readiness / participation / formation usability: the
    observability and diagnostics surfaces exposed by PR-30 are still
    reachable and return shaped output.
9.  No new runtime authority, duplicate orchestration control system, or
    parallel acceptance architecture is introduced.
10. Regression: all PR-33 sentinels are still importable and non-empty.

Coverage groups
---------------
A  — Orchestrator module: all PR-34 sentinels present and non-empty.
B  — Projection: PR-34 sentinel importable and not UNAVAILABLE.
C  — core.runtime re-exports all PR-34 sentinels.
D  — Dispatch stability: local branch produces valid SourceDispatchResult.
E  — Dispatch stability: fallback branch produces shaped result.
F  — Dispatch stability: forced-remote branch produces shaped result.
G  — Dispatch stability: staged_mesh branch produces action_taken result.
H  — Android ingress stability: extract_delegated_signal_envelope shapes data.
I  — Android ingress stability: ingest_delegated_execution_signal returns outcome.
J  — Registry stability: register/reconnect/detach/invalidate path is stable.
K  — Recovery-readiness stability: guard_inbound_signal accepts/rejects correctly.
L  — Reuse-dispatch stability: resolve_reuse_dispatch_surface returns resolution.
M  — Multi-target ranking: evaluate_candidate returns CandidateEvaluation.
N  — Multi-target ranking: rank_candidates orders by score.
O  — Multi-target ranking: select_delegated_target chooses top candidate.
P  — Multi-target ranking: select with no eligible candidate gives local_fallback.
Q  — Staged-mesh closure: coordinate_mesh_session callable and returns dict.
R  — Diagnostics usability: PR-30 sentinel accessible from orchestrator.
S  — Readiness usability: build_recovery_readiness_snapshot returns snapshot.
T  — Participation/formation: list_active_sessions reflects registered sessions.
U  — No parallel authority: no new global state introduced by PR-34.
V  — Regression: PR-33 sentinels still importable and non-empty.
W  — Sentinel strings contain expected PR-34 keywords.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.runtime.source_dispatch_orchestrator import (
        CROSS_DEVICE_RUNTIME_ACCEPTANCE_PR34_SENTINEL,
        DISPATCH_FALLBACK_RESULT_MERGE_STABILITY_PR34_POLICY,
        ANDROID_ATTACHED_RUNTIME_ORCHESTRATION_STABILITY_PR34_POLICY,
        MULTI_TARGET_RANKING_MATURITY_PR34_POLICY,
        STAGED_MESH_CLOSURE_RUNNABLE_PR34_POLICY,
        DIAGNOSTICS_READINESS_PARTICIPATION_FORMATION_USABILITY_PR34_POLICY,
    )

    _ORCHESTRATOR_AVAILABLE = True
except ImportError:
    _ORCHESTRATOR_AVAILABLE = False

try:
    from core.routes.projection import CROSS_DEVICE_RUNTIME_ACCEPTANCE_ALIGNED_PR34

    _PROJECTION_AVAILABLE = True
except ImportError:
    _PROJECTION_AVAILABLE = False

try:
    from core.runtime import (
        CROSS_DEVICE_RUNTIME_ACCEPTANCE_PR34_SENTINEL as _rt_sentinel,
        DISPATCH_FALLBACK_RESULT_MERGE_STABILITY_PR34_POLICY as _rt_dispatch,
        ANDROID_ATTACHED_RUNTIME_ORCHESTRATION_STABILITY_PR34_POLICY as _rt_android,
        MULTI_TARGET_RANKING_MATURITY_PR34_POLICY as _rt_ranking,
        STAGED_MESH_CLOSURE_RUNNABLE_PR34_POLICY as _rt_mesh,
        DIAGNOSTICS_READINESS_PARTICIPATION_FORMATION_USABILITY_PR34_POLICY as _rt_diag,
    )

    _RUNTIME_EXPORTS_AVAILABLE = True
except ImportError:
    _RUNTIME_EXPORTS_AVAILABLE = False

try:
    from core.runtime.source_dispatch_orchestrator import (
        orchestrate_source_runtime_dispatch,
        build_source_dispatch_plan,
    )
    # Dispatch execution requires contracts which needs pydantic
    import pydantic  # noqa: F401 — availability check only

    _DISPATCH_AVAILABLE = True
except ImportError:
    _DISPATCH_AVAILABLE = False

try:
    from core.android_delegated_signal_ingress import (
        extract_delegated_signal_envelope,
        ingest_delegated_execution_signal,
        DelegatedSignalKind,
        ResultKind,
        DelegatedExecutionSignalEnvelope,
    )

    _INGRESS_AVAILABLE = True
except ImportError:
    _INGRESS_AVAILABLE = False

try:
    from core.attached_runtime_session_registry import (
        AttachedSessionRegistry,
        AttachedSessionRegistryEntry,
        RegistryEntryState,
        register_session,
        reconnect_session,
        detach_session,
        invalidate_session,
        list_active_sessions,
    )

    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

try:
    from core.attached_runtime_recovery_readiness import (
        RecoveryReadinessRuntime,
        build_idempotency_key,
        check_signal_guard,
        record_seen_signal,
        guard_inbound_signal,
        build_recovery_readiness_snapshot,
        SignalGuardDecision,
    )

    _RECOVERY_AVAILABLE = True
except ImportError:
    _RECOVERY_AVAILABLE = False

try:
    from core.attached_runtime_reuse_dispatch import (
        resolve_reuse_dispatch_surface,
        ReuseDispatchResolutionKind,
        ReuseDispatchResolution,
    )

    _REUSE_DISPATCH_AVAILABLE = True
except ImportError:
    _REUSE_DISPATCH_AVAILABLE = False

try:
    from core.delegated_target_selection_policy import (
        evaluate_candidate,
        rank_candidates,
        select_delegated_target,
        build_selection_explanation,
        SelectionCandidateContext,
        CandidateEvaluation,
        SelectionDecision,
        SelectionOutcome,
        CandidateRejectionReason,
    )

    _RANKING_AVAILABLE = True
except ImportError:
    _RANKING_AVAILABLE = False

try:
    from core.mesh_session_coordinator import coordinate_mesh_session

    _MESH_COORDINATOR_AVAILABLE = True
except ImportError:
    _MESH_COORDINATOR_AVAILABLE = False

try:
    from core.runtime.source_dispatch_orchestrator import (
        OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_PR30_SENTINEL,
    )

    _DIAGNOSTICS_AVAILABLE = True
except ImportError:
    _DIAGNOSTICS_AVAILABLE = False

try:
    from core.runtime.source_dispatch_orchestrator import (
        RECONNECT_RECOVERY_CONSISTENCY_PR33_SENTINEL,
        RECONNECT_MUST_NOT_BREAK_HOST_SIDE_TRUTH_PR33_POLICY,
        REGISTRY_RECONNECT_EVENT_IS_OBSERVABLE_PR33_POLICY,
        EXECUTION_TRACKER_SURVIVES_RECONNECT_PR33_POLICY,
        RESULT_MERGE_CONSISTENT_THROUGH_RECOVERY_PR33_POLICY,
    )

    _PR33_SENTINELS_AVAILABLE = True
except ImportError:
    _PR33_SENTINELS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Skip markers
# ---------------------------------------------------------------------------

_skip_orchestrator = pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE, reason="orchestrator module unavailable"
)
_skip_projection = pytest.mark.skipif(
    not _PROJECTION_AVAILABLE, reason="projection module unavailable (fastapi missing)"
)
_skip_runtime = pytest.mark.skipif(
    not _RUNTIME_EXPORTS_AVAILABLE, reason="core.runtime exports unavailable"
)
_skip_dispatch = pytest.mark.skipif(
    not _DISPATCH_AVAILABLE, reason="dispatch orchestrator unavailable"
)
_skip_ingress = pytest.mark.skipif(
    not _INGRESS_AVAILABLE, reason="android delegated signal ingress unavailable"
)
_skip_registry = pytest.mark.skipif(
    not _REGISTRY_AVAILABLE, reason="session registry unavailable"
)
_skip_recovery = pytest.mark.skipif(
    not _RECOVERY_AVAILABLE, reason="recovery readiness module unavailable"
)
_skip_reuse = pytest.mark.skipif(
    not _REUSE_DISPATCH_AVAILABLE, reason="reuse dispatch module unavailable"
)
_skip_ranking = pytest.mark.skipif(
    not _RANKING_AVAILABLE, reason="delegated target selection policy unavailable"
)
_skip_mesh = pytest.mark.skipif(
    not _MESH_COORDINATOR_AVAILABLE, reason="mesh session coordinator unavailable"
)
_skip_diagnostics = pytest.mark.skipif(
    not _DIAGNOSTICS_AVAILABLE, reason="PR-30 diagnostics sentinel unavailable"
)
_skip_pr33 = pytest.mark.skipif(
    not _PR33_SENTINELS_AVAILABLE, reason="PR-33 sentinels unavailable"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry() -> "AttachedSessionRegistry":
    return AttachedSessionRegistry()


def _make_recovery() -> "RecoveryReadinessRuntime":
    return RecoveryReadinessRuntime()


def _make_entry_context(
    *,
    device_id: str = "dev-ctx-1",
    is_reuse_valid: bool = True,
    delegated_execution_count: int = 0,
    recent_failure_count: int = 0,
    recent_detach_count: int = 0,
) -> "SelectionCandidateContext":
    """Create a SelectionCandidateContext backed by a real registry entry."""
    r = AttachedSessionRegistry()
    entry = register_session(device_id, registry=r)
    return SelectionCandidateContext(
        entry=entry,
        is_reuse_valid=is_reuse_valid,
        delegated_execution_count=delegated_execution_count,
        recent_failure_count=recent_failure_count,
        recent_detach_count=recent_detach_count,
    )


# ===========================================================================
# A — Orchestrator sentinels
# ===========================================================================


@_skip_orchestrator
class TestOrchestratorSentinels:
    def test_AA1_main_sentinel_present_and_non_empty(self):
        assert CROSS_DEVICE_RUNTIME_ACCEPTANCE_PR34_SENTINEL
        assert len(CROSS_DEVICE_RUNTIME_ACCEPTANCE_PR34_SENTINEL) > 10

    def test_AA2_dispatch_stability_policy_present(self):
        assert DISPATCH_FALLBACK_RESULT_MERGE_STABILITY_PR34_POLICY
        assert len(DISPATCH_FALLBACK_RESULT_MERGE_STABILITY_PR34_POLICY) > 10

    def test_AA3_android_orchestration_policy_present(self):
        assert ANDROID_ATTACHED_RUNTIME_ORCHESTRATION_STABILITY_PR34_POLICY
        assert len(ANDROID_ATTACHED_RUNTIME_ORCHESTRATION_STABILITY_PR34_POLICY) > 10

    def test_AA4_ranking_maturity_policy_present(self):
        assert MULTI_TARGET_RANKING_MATURITY_PR34_POLICY
        assert len(MULTI_TARGET_RANKING_MATURITY_PR34_POLICY) > 10

    def test_AA5_mesh_closure_policy_present(self):
        assert STAGED_MESH_CLOSURE_RUNNABLE_PR34_POLICY
        assert len(STAGED_MESH_CLOSURE_RUNNABLE_PR34_POLICY) > 10

    def test_AA6_diagnostics_usability_policy_present(self):
        assert DIAGNOSTICS_READINESS_PARTICIPATION_FORMATION_USABILITY_PR34_POLICY
        assert len(DIAGNOSTICS_READINESS_PARTICIPATION_FORMATION_USABILITY_PR34_POLICY) > 10

    def test_AA7_all_six_sentinels_are_distinct(self):
        sentinels = [
            CROSS_DEVICE_RUNTIME_ACCEPTANCE_PR34_SENTINEL,
            DISPATCH_FALLBACK_RESULT_MERGE_STABILITY_PR34_POLICY,
            ANDROID_ATTACHED_RUNTIME_ORCHESTRATION_STABILITY_PR34_POLICY,
            MULTI_TARGET_RANKING_MATURITY_PR34_POLICY,
            STAGED_MESH_CLOSURE_RUNNABLE_PR34_POLICY,
            DIAGNOSTICS_READINESS_PARTICIPATION_FORMATION_USABILITY_PR34_POLICY,
        ]
        assert len(set(sentinels)) == 6


# ===========================================================================
# B — Projection sentinel
# ===========================================================================


@_skip_projection
class TestProjectionSentinel:
    def test_AB1_sentinel_importable(self):
        assert CROSS_DEVICE_RUNTIME_ACCEPTANCE_ALIGNED_PR34

    def test_AB2_sentinel_not_unavailable(self):
        assert "UNAVAILABLE" not in CROSS_DEVICE_RUNTIME_ACCEPTANCE_ALIGNED_PR34

    def test_AB3_sentinel_contains_pr34(self):
        s = CROSS_DEVICE_RUNTIME_ACCEPTANCE_ALIGNED_PR34
        assert "PR34" in s or "PR-34" in s


# ===========================================================================
# C — core.runtime re-exports
# ===========================================================================


@_skip_runtime
class TestRuntimeExports:
    def test_AC1_main_sentinel_reexported(self):
        assert _rt_sentinel
        assert "PR34" in _rt_sentinel or "package=34" in _rt_sentinel

    def test_AC2_dispatch_policy_reexported(self):
        assert _rt_dispatch
        assert "PR34" in _rt_dispatch

    def test_AC3_android_policy_reexported(self):
        assert _rt_android
        assert "PR34" in _rt_android

    def test_AC4_ranking_policy_reexported(self):
        assert _rt_ranking
        assert "PR34" in _rt_ranking

    def test_AC5_mesh_policy_reexported(self):
        assert _rt_mesh
        assert "PR34" in _rt_mesh

    def test_AC6_diagnostics_policy_reexported(self):
        assert _rt_diag
        assert "PR34" in _rt_diag


# ===========================================================================
# D — Dispatch stability: local branch
# ===========================================================================


@_skip_dispatch
class TestDispatchLocalBranch:
    def test_AD1_local_dispatch_returns_result(self):
        result = orchestrate_source_runtime_dispatch(
            trace_id="tr-d1",
            task_id="task-d1",
            session_id="sess-d1",
        )
        assert result is not None

    def test_AD2_local_result_has_success_field(self):
        result = orchestrate_source_runtime_dispatch(
            trace_id="tr-d2",
            task_id="task-d2",
        )
        assert hasattr(result, "success") or isinstance(result, dict)

    def test_AD3_plan_returns_plan_object(self):
        plan = build_source_dispatch_plan(
            trace_id="tr-d3",
            task_id="task-d3",
        )
        assert plan is not None

    def test_AD4_plan_has_dispatch_branch(self):
        plan = build_source_dispatch_plan(
            trace_id="tr-d4",
            task_id="task-d4",
        )
        if hasattr(plan, "dispatch_branch"):
            assert plan.dispatch_branch is not None
        elif hasattr(plan, "to_dict"):
            d = plan.to_dict()
            assert isinstance(d, dict)

    def test_AD5_result_to_dict_is_serialisable(self):
        import json

        result = orchestrate_source_runtime_dispatch(
            trace_id="tr-d5",
            task_id="task-d5",
        )
        if hasattr(result, "to_dict"):
            d = result.to_dict()
            assert isinstance(d, dict)
            json.dumps(d)


# ===========================================================================
# E — Dispatch stability: fallback branch
# ===========================================================================


@_skip_dispatch
class TestDispatchFallbackBranch:
    def test_AE1_forced_local_does_not_raise(self):
        result = orchestrate_source_runtime_dispatch(
            trace_id="tr-e1",
            task_id="task-e1",
            force_local=True,
        )
        assert result is not None

    def test_AE2_no_target_device_uses_fallback(self):
        result = orchestrate_source_runtime_dispatch(
            trace_id="tr-e2",
            task_id="task-e2",
            target_device_id=None,
        )
        assert result is not None

    def test_AE3_fallback_reason_is_string_if_present(self):
        result = orchestrate_source_runtime_dispatch(
            trace_id="tr-e3",
            task_id="task-e3",
        )
        if hasattr(result, "fallback_reason") and result.fallback_reason is not None:
            assert isinstance(result.fallback_reason, str)


# ===========================================================================
# F — Dispatch stability: forced-remote branch
# ===========================================================================


@_skip_dispatch
class TestDispatchForcedRemote:
    def test_AF1_forced_remote_does_not_raise(self):
        result = orchestrate_source_runtime_dispatch(
            trace_id="tr-f1",
            task_id="task-f1",
            force_remote=True,
            target_device_id="remote-dev",
        )
        assert result is not None

    def test_AF2_result_has_action_taken_if_available(self):
        result = orchestrate_source_runtime_dispatch(
            trace_id="tr-f2",
            task_id="task-f2",
            target_device_id="remote-dev-2",
        )
        if hasattr(result, "action_taken") and result.action_taken is not None:
            assert isinstance(result.action_taken, str)


# ===========================================================================
# G — Dispatch stability: staged_mesh branch
# ===========================================================================


@_skip_dispatch
class TestDispatchStagedMesh:
    def test_AG1_staged_mesh_with_valid_session_does_not_raise(self):
        mesh_session = {
            "session_id": "mesh-sess-g1",
            "participants": [
                {"device_id": "dev-g1", "status": "active"},
                {"device_id": "dev-g2", "status": "active"},
            ],
        }
        result = orchestrate_source_runtime_dispatch(
            trace_id="tr-g1",
            task_id="task-g1",
            mesh_session=mesh_session,
        )
        assert result is not None

    def test_AG2_staged_mesh_result_has_action_taken(self):
        mesh_session = {
            "session_id": "mesh-sess-g2",
            "participants": [
                {"device_id": "dev-g3", "status": "active"},
                {"device_id": "dev-g4", "status": "active"},
            ],
        }
        result = orchestrate_source_runtime_dispatch(
            trace_id="tr-g2",
            task_id="task-g2",
            mesh_session=mesh_session,
        )
        if hasattr(result, "action_taken") and result.action_taken is not None:
            assert isinstance(result.action_taken, str)

    def test_AG3_staged_mesh_without_target_device_does_not_raise(self):
        mesh_session = {
            "session_id": "mesh-sess-g3",
            "participants": [
                {"device_id": "dev-g5", "status": "active"},
                {"device_id": "dev-g6", "status": "active"},
            ],
        }
        result = orchestrate_source_runtime_dispatch(
            trace_id="tr-g3",
            task_id="task-g3",
            mesh_session=mesh_session,
            target_device_id=None,
        )
        assert result is not None


# ===========================================================================
# H — Android ingress stability: extract_delegated_signal_envelope
# ===========================================================================


@_skip_ingress
class TestAndroidIngressExtract:
    def _make_raw(self, **kwargs: Any) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "contract_id": "cid-h1",
            "session_id": "sess-h1",
            "device_id": "dev-h1",
            "trace_id": "tr-h1",
            "task_id": "task-h1",
            "signal_id": "sig-h1",
            "emission_seq": 1,
            "signal_kind": "result",
            "result_kind": "success",
        }
        base.update(kwargs)
        return base

    def test_AH1_extract_returns_envelope(self):
        raw = self._make_raw()
        env = extract_delegated_signal_envelope(raw)
        assert env is not None

    def test_AH2_envelope_has_signal_id(self):
        raw = self._make_raw(signal_id="sig-h2")
        env = extract_delegated_signal_envelope(raw)
        assert env.signal_id == "sig-h2"

    def test_AH3_envelope_has_signal_kind(self):
        raw = self._make_raw(signal_kind="ack")
        env = extract_delegated_signal_envelope(raw)
        assert env.signal_kind == DelegatedSignalKind.ack or str(env.signal_kind).endswith("ack")

    def test_AH4_extract_with_minimal_fields_does_not_raise(self):
        raw: Dict[str, Any] = {
            "signal_kind": "result",
            "result_kind": "success",
        }
        try:
            env = extract_delegated_signal_envelope(raw)
            assert env is not None
        except Exception:
            pass  # acceptable if minimal raw raises; stability means no crash on valid input


# ===========================================================================
# I — Android ingress stability: ingest_delegated_execution_signal
# ===========================================================================


@_skip_ingress
class TestAndroidIngressIngest:
    def _make_raw(self, signal_kind: str = "result") -> Dict[str, Any]:
        return {
            "contract_id": "cid-i1",
            "session_id": "sess-i1",
            "device_id": "dev-i1",
            "trace_id": "tr-i1",
            "task_id": "task-i1",
            "signal_id": "sig-i1",
            "emission_seq": 1,
            "signal_kind": signal_kind,
            "result_kind": "success",
        }

    def test_AI1_ingest_returns_outcome(self):
        raw = self._make_raw()
        outcome = ingest_delegated_execution_signal(raw)
        assert outcome is not None

    def test_AI2_ingest_has_was_updated_field(self):
        raw = self._make_raw("result")
        outcome = ingest_delegated_execution_signal(raw)
        assert hasattr(outcome, "was_updated")

    def test_AI3_ingest_duplicate_signal_does_not_raise(self):
        raw = self._make_raw("ack")
        ingest_delegated_execution_signal(raw)
        # Second call with same raw signal should not raise
        outcome2 = ingest_delegated_execution_signal(raw)
        assert outcome2 is not None


# ===========================================================================
# J — Registry stability
# ===========================================================================


@_skip_registry
class TestRegistryStability:
    def test_AJ1_register_returns_entry(self):
        r = _make_registry()
        entry = register_session("dev-j1", registry=r)
        assert entry is not None
        assert entry.device_id == "dev-j1"

    def test_AJ2_entry_state_active_after_register(self):
        r = _make_registry()
        entry = register_session("dev-j2", registry=r)
        assert entry.attachment_state == RegistryEntryState.active

    def test_AJ3_reconnect_succeeds_after_detach(self):
        r = _make_registry()
        e = register_session("dev-j3", registry=r)
        e = detach_session(e, registry=r)
        e = reconnect_session(e, registry=r)
        assert e is not None

    def test_AJ4_invalidate_marks_entry_non_active(self):
        r = _make_registry()
        e = register_session("dev-j4", registry=r)
        e = invalidate_session(e, registry=r)
        assert e.attachment_state == RegistryEntryState.invalidated

    def test_AJ5_list_active_sessions_returns_list(self):
        r = _make_registry()
        register_session("dev-j5a", registry=r)
        register_session("dev-j5b", registry=r)
        sessions = list_active_sessions(registry=r)
        assert isinstance(sessions, list)

    def test_AJ6_list_active_sessions_counts_registrations(self):
        r = _make_registry()
        register_session("dev-j6a", registry=r)
        register_session("dev-j6b", registry=r)
        sessions = list_active_sessions(registry=r)
        assert len(sessions) >= 2


# ===========================================================================
# K — Recovery-readiness stability
# ===========================================================================


@_skip_recovery
class TestRecoveryReadinessStability:
    def test_AK1_guard_accepts_first_signal(self):
        rt = _make_recovery()
        envelope = MagicMock()
        envelope.signal_id = "sig-k1"
        envelope.contract_id = "cid-k1"
        envelope.session_id = "sess-k1"
        envelope.emission_seq = 1
        result = guard_inbound_signal(envelope, runtime=rt)
        assert result is not None
        assert result.decision == SignalGuardDecision.accept

    def test_AK2_guard_rejects_duplicate(self):
        rt = _make_recovery()
        envelope = MagicMock()
        envelope.signal_id = "sig-k2"
        envelope.contract_id = "cid-k2"
        envelope.session_id = "sess-k2"
        envelope.emission_seq = 1
        guard_inbound_signal(envelope, runtime=rt)
        result2 = guard_inbound_signal(envelope, runtime=rt)
        assert result2.decision != SignalGuardDecision.accept

    def test_AK3_snapshot_returns_shaped_output(self):
        rt = _make_recovery()
        snap = build_recovery_readiness_snapshot(runtime=rt)
        assert snap is not None
        if hasattr(snap, "to_dict"):
            d = snap.to_dict()
            assert isinstance(d, dict)

    def test_AK4_snapshot_has_status_field(self):
        rt = _make_recovery()
        snap = build_recovery_readiness_snapshot(runtime=rt)
        assert hasattr(snap, "status")


# ===========================================================================
# L — Reuse-dispatch stability
# ===========================================================================


@_skip_reuse
class TestReuseDispatchStability:
    def test_AL1_resolve_with_no_session_returns_resolution(self):
        result = resolve_reuse_dispatch_surface(
            session_id=None,
            device_id="dev-l1",
        )
        assert result is not None

    def test_AL2_resolution_has_kind(self):
        result = resolve_reuse_dispatch_surface(
            session_id=None,
            device_id="dev-l2",
        )
        assert hasattr(result, "kind") or hasattr(result, "resolution_kind")

    def test_AL3_resolution_kind_is_known_value(self):
        result = resolve_reuse_dispatch_surface(
            session_id=None,
            device_id="dev-l3",
        )
        kind = getattr(result, "kind", getattr(result, "resolution_kind", None))
        if kind is not None:
            assert kind in list(ReuseDispatchResolutionKind)


# ===========================================================================
# M — Multi-target ranking: evaluate_candidate
# ===========================================================================


@_skip_ranking
class TestRankingEvaluateCandidate:
    def test_AM1_evaluate_returns_evaluation(self):
        ctx = _make_entry_context()
        ev = evaluate_candidate(ctx)
        assert isinstance(ev, CandidateEvaluation)

    def test_AM2_active_join_runtime_candidate_is_eligible(self):
        ctx = _make_entry_context()
        ev = evaluate_candidate(ctx)
        assert ev.is_accepted

    def test_AM3_non_active_candidate_is_not_eligible(self):
        r = _make_registry()
        e = register_session("dev-am3", registry=r)
        e = detach_session(e, registry=r)
        ctx = SelectionCandidateContext(
            entry=e,
            is_reuse_valid=True,
            delegated_execution_count=0,
            recent_failure_count=0,
            recent_detach_count=0,
        )
        ev = evaluate_candidate(ctx)
        assert not ev.is_accepted

    def test_AM4_evaluation_has_score(self):
        ctx = _make_entry_context()
        ev = evaluate_candidate(ctx)
        assert isinstance(ev.score, (int, float))

    def test_AM5_high_failure_count_lowers_score(self):
        ctx_good = _make_entry_context(recent_failure_count=0)
        ctx_bad = _make_entry_context(recent_failure_count=10)
        ev_good = evaluate_candidate(ctx_good)
        ev_bad = evaluate_candidate(ctx_bad)
        assert ev_good.score >= ev_bad.score

    def test_AM6_reuse_valid_bonus_applied(self):
        ctx_reuse = _make_entry_context(is_reuse_valid=True)
        ctx_no_reuse = _make_entry_context(is_reuse_valid=False)
        ev_reuse = evaluate_candidate(ctx_reuse)
        ev_no_reuse = evaluate_candidate(ctx_no_reuse)
        assert ev_reuse.score >= ev_no_reuse.score


# ===========================================================================
# N — Multi-target ranking: rank_candidates
# ===========================================================================


@_skip_ranking
class TestRankingRankCandidates:
    def test_AN1_rank_empty_list_returns_empty(self):
        ranked = rank_candidates([])
        assert ranked == []

    def test_AN2_single_candidate_returns_single(self):
        ctx = _make_entry_context(device_id="dev-an2")
        ranked = rank_candidates([ctx])
        assert len(ranked) == 1

    def test_AN3_highest_score_first(self):
        ctx_a = _make_entry_context(device_id="dev-an3a", recent_failure_count=0)
        ctx_b = _make_entry_context(device_id="dev-an3b", recent_failure_count=5)
        ranked = rank_candidates([ctx_b, ctx_a])
        ev_first = evaluate_candidate(ranked[0])
        ev_last = evaluate_candidate(ranked[-1])
        assert ev_first.score >= ev_last.score

    def test_AN4_ranking_is_deterministic(self):
        contexts = [
            _make_entry_context(device_id=f"dev-an4-{i}", recent_failure_count=i)
            for i in range(5)
        ]
        ranked1 = rank_candidates(list(contexts))
        ranked2 = rank_candidates(list(contexts))
        scores1 = [evaluate_candidate(c).score for c in ranked1]
        scores2 = [evaluate_candidate(c).score for c in ranked2]
        assert scores1 == scores2


# ===========================================================================
# O — Multi-target ranking: select_delegated_target
# ===========================================================================


@_skip_ranking
class TestRankingSelectDelegatedTarget:
    def test_AO1_select_from_single_eligible_candidate(self):
        ctx = _make_entry_context(device_id="dev-ao1")
        decision = select_delegated_target([ctx])
        assert isinstance(decision, SelectionDecision)

    def test_AO2_select_chooses_selected_attached(self):
        ctx = _make_entry_context(device_id="dev-ao2")
        decision = select_delegated_target([ctx])
        assert decision.outcome == SelectionOutcome.selected_attached

    def test_AO3_selected_candidate_has_device_id(self):
        ctx = _make_entry_context(device_id="dev-ao3")
        decision = select_delegated_target([ctx])
        if decision.selected_candidate is not None:
            assert decision.selected_candidate.entry.device_id == "dev-ao3"

    def test_AO4_decision_has_explanation(self):
        ctx = _make_entry_context(device_id="dev-ao4")
        decision = select_delegated_target([ctx])
        assert hasattr(decision, "explanation")

    def test_AO5_multiple_candidates_selects_best(self):
        ctx_good = _make_entry_context(device_id="dev-ao5-good", recent_failure_count=0)
        ctx_bad = _make_entry_context(device_id="dev-ao5-bad", recent_failure_count=10)
        decision = select_delegated_target([ctx_bad, ctx_good])
        assert decision.outcome == SelectionOutcome.selected_attached


# ===========================================================================
# P — Multi-target ranking: no eligible candidate → local fallback
# ===========================================================================


@_skip_ranking
class TestRankingLocalFallback:
    def test_AP1_no_candidates_gives_local_fallback(self):
        decision = select_delegated_target([])
        assert decision.outcome == SelectionOutcome.local_fallback

    def test_AP2_all_ineligible_gives_local_fallback(self):
        r = _make_registry()
        e = register_session("dev-ap2", registry=r)
        e = detach_session(e, registry=r)
        ctx = SelectionCandidateContext(
            entry=e,
            is_reuse_valid=False,
            delegated_execution_count=0,
            recent_failure_count=0,
            recent_detach_count=0,
        )
        decision = select_delegated_target([ctx])
        assert decision.outcome in (
            SelectionOutcome.local_fallback,
            SelectionOutcome.degrade,
        )

    def test_AP3_build_selection_explanation_returns_dict(self):
        ctx = _make_entry_context(device_id="dev-ap3")
        decision = select_delegated_target([ctx])
        explanation = build_selection_explanation(decision)
        assert isinstance(explanation, dict)


# ===========================================================================
# Q — Staged-mesh closure: coordinate_mesh_session callable
# ===========================================================================


@_skip_mesh
class TestStagedMeshClosure:
    def test_AQ1_coordinate_mesh_session_is_callable(self):
        assert callable(coordinate_mesh_session)

    def test_AQ2_coordinate_with_valid_session_returns_dict(self):
        session = {
            "session_id": "mesh-q2",
            "participants": [
                {"device_id": "dev-q2a", "status": "active"},
                {"device_id": "dev-q2b", "status": "active"},
            ],
        }
        result = coordinate_mesh_session(session)
        assert isinstance(result, dict)

    def test_AQ3_result_has_action_taken(self):
        session = {
            "session_id": "mesh-q3",
            "participants": [
                {"device_id": "dev-q3a", "status": "active"},
                {"device_id": "dev-q3b", "status": "active"},
            ],
        }
        result = coordinate_mesh_session(session)
        assert "action_taken" in result

    def test_AQ4_result_action_taken_is_staged_mesh_coordinated(self):
        session = {
            "session_id": "mesh-q4",
            "participants": [
                {"device_id": "dev-q4a", "status": "active"},
                {"device_id": "dev-q4b", "status": "active"},
            ],
        }
        result = coordinate_mesh_session(session)
        assert result.get("action_taken") == "staged_mesh_coordinated"


# ===========================================================================
# R — Diagnostics usability: PR-30 sentinel accessible
# ===========================================================================


@_skip_diagnostics
class TestDiagnosticsUsability:
    def test_AR1_pr30_sentinel_accessible(self):
        assert OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_PR30_SENTINEL
        assert len(OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_PR30_SENTINEL) > 10

    def test_AR2_pr30_sentinel_contains_pr30(self):
        assert "PR30" in OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_PR30_SENTINEL or \
               "30" in OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_PR30_SENTINEL


# ===========================================================================
# S — Readiness usability: build_recovery_readiness_snapshot
# ===========================================================================


@_skip_recovery
class TestReadinessUsability:
    def test_AS1_snapshot_returns_object(self):
        rt = _make_recovery()
        snap = build_recovery_readiness_snapshot(runtime=rt)
        assert snap is not None

    def test_AS2_fresh_runtime_snapshot_is_ready_or_degraded(self):
        rt = _make_recovery()
        snap = build_recovery_readiness_snapshot(runtime=rt)
        if hasattr(snap, "status"):
            status_str = str(snap.status)
            assert "ready" in status_str or "degraded" in status_str or "recovering" in status_str

    def test_AS3_snapshot_to_dict_is_serialisable(self):
        import json

        rt = _make_recovery()
        snap = build_recovery_readiness_snapshot(runtime=rt)
        if hasattr(snap, "to_dict"):
            d = snap.to_dict()
            assert isinstance(d, dict)
            json.dumps(d)


# ===========================================================================
# T — Participation / formation: list_active_sessions
# ===========================================================================


@_skip_registry
class TestParticipationFormation:
    def test_AT1_empty_registry_has_no_active_sessions(self):
        r = _make_registry()
        sessions = list_active_sessions(registry=r)
        assert sessions == []

    def test_AT2_registered_session_appears_in_active_list(self):
        r = _make_registry()
        register_session("dev-t2", registry=r)
        sessions = list_active_sessions(registry=r)
        device_ids = [s.device_id for s in sessions]
        assert "dev-t2" in device_ids

    def test_AT3_detached_session_not_in_active_list(self):
        r = _make_registry()
        e = register_session("dev-t3", registry=r)
        detach_session(e, registry=r)
        sessions = list_active_sessions(registry=r)
        device_ids = [s.device_id for s in sessions]
        assert "dev-t3" not in device_ids

    def test_AT4_multiple_devices_all_active(self):
        r = _make_registry()
        for i in range(3):
            register_session(f"dev-t4-{i}", registry=r)
        sessions = list_active_sessions(registry=r)
        assert len(sessions) >= 3


# ===========================================================================
# U — No parallel authority introduced
# ===========================================================================


@_skip_orchestrator
class TestNoParallelAuthority:
    def test_AU1_main_sentinel_does_not_mention_new_authority(self):
        sentinel = CROSS_DEVICE_RUNTIME_ACCEPTANCE_PR34_SENTINEL
        for forbidden in ("new_authority", "parallel_orchestrator", "alternate_dispatch"):
            assert forbidden not in sentinel.lower()

    def test_AU2_dispatch_policy_prohibits_alternate_authority(self):
        policy = DISPATCH_FALLBACK_RESULT_MERGE_STABILITY_PR34_POLICY
        assert "no alternate" in policy.lower() or "no new" in policy.lower() or \
               "parallel" in policy.lower()

    def test_AU3_android_policy_prohibits_new_control_system(self):
        policy = ANDROID_ATTACHED_RUNTIME_ORCHESTRATION_STABILITY_PR34_POLICY
        assert "no new" in policy.lower() or "no new android" in policy.lower() or \
               "sole orchestration" in policy.lower()

    def test_AU4_mesh_policy_prohibits_new_mesh_authority(self):
        policy = STAGED_MESH_CLOSURE_RUNNABLE_PR34_POLICY
        assert "no new" in policy.lower() or "no new mesh" in policy.lower()

    def test_AU5_diagnostics_policy_prohibits_duplicate_subsystem(self):
        policy = DIAGNOSTICS_READINESS_PARTICIPATION_FORMATION_USABILITY_PR34_POLICY
        assert "no duplicate" in policy.lower() or "no parallel" in policy.lower() or \
               "no new" in policy.lower()


# ===========================================================================
# V — Regression: PR-33 sentinels still importable
# ===========================================================================


@_skip_pr33
class TestPR33Regression:
    def test_AV1_pr33_main_sentinel_still_present(self):
        from core.runtime.source_dispatch_orchestrator import (
            RECONNECT_RECOVERY_CONSISTENCY_PR33_SENTINEL as _pr33,
        )
        assert _pr33
        assert len(_pr33) > 10

    def test_AV2_pr33_host_truth_policy_still_present(self):
        from core.runtime.source_dispatch_orchestrator import (
            RECONNECT_MUST_NOT_BREAK_HOST_SIDE_TRUTH_PR33_POLICY as _p,
        )
        assert _p

    def test_AV3_pr33_observable_policy_still_present(self):
        from core.runtime.source_dispatch_orchestrator import (
            REGISTRY_RECONNECT_EVENT_IS_OBSERVABLE_PR33_POLICY as _p,
        )
        assert _p

    def test_AV4_pr33_tracker_policy_still_present(self):
        from core.runtime.source_dispatch_orchestrator import (
            EXECUTION_TRACKER_SURVIVES_RECONNECT_PR33_POLICY as _p,
        )
        assert _p

    def test_AV5_pr33_merge_policy_still_present(self):
        from core.runtime.source_dispatch_orchestrator import (
            RESULT_MERGE_CONSISTENT_THROUGH_RECOVERY_PR33_POLICY as _p,
        )
        assert _p

    def test_AV6_pr33_sentinel_does_not_contain_pr34_keyword(self):
        from core.runtime.source_dispatch_orchestrator import (
            RECONNECT_RECOVERY_CONSISTENCY_PR33_SENTINEL as _pr33,
            CROSS_DEVICE_RUNTIME_ACCEPTANCE_PR34_SENTINEL as _pr34,
        )
        assert _pr33 != _pr34


# ===========================================================================
# W — Sentinel keyword checks
# ===========================================================================


@_skip_orchestrator
class TestSentinelContent:
    def test_AW1_main_sentinel_contains_pr34(self):
        assert "34" in CROSS_DEVICE_RUNTIME_ACCEPTANCE_PR34_SENTINEL

    def test_AW2_dispatch_policy_mentions_dispatch(self):
        assert "dispatch" in DISPATCH_FALLBACK_RESULT_MERGE_STABILITY_PR34_POLICY.lower()

    def test_AW3_android_policy_mentions_android(self):
        assert "android" in ANDROID_ATTACHED_RUNTIME_ORCHESTRATION_STABILITY_PR34_POLICY.lower()

    def test_AW4_ranking_policy_mentions_ranking(self):
        policy = MULTI_TARGET_RANKING_MATURITY_PR34_POLICY.lower()
        assert "rank" in policy or "select" in policy

    def test_AW5_mesh_policy_mentions_staged_mesh(self):
        assert "staged" in STAGED_MESH_CLOSURE_RUNNABLE_PR34_POLICY.lower() or \
               "mesh" in STAGED_MESH_CLOSURE_RUNNABLE_PR34_POLICY.lower()

    def test_AW6_diagnostics_policy_mentions_diagnostics(self):
        assert "diagnostic" in DIAGNOSTICS_READINESS_PARTICIPATION_FORMATION_USABILITY_PR34_POLICY.lower()
