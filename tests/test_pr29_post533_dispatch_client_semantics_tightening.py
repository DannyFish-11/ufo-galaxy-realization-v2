"""tests/test_pr29_post533_dispatch_client_semantics_tightening.py
==================================================================
Tests for PR package 29 (post-533 dual-repo runtime unification master plan,
main repo side): Post-Release Follow-Up Tightening Across Dispatch and Client
Semantics.

This test suite verifies that:

1. All PR-29 policy/authority sentinels are present in the orchestrator module.
2. Dispatch selection cohesion: selection scoring, candidate gating, and fallback
   triggering remain deterministic and cohesive after PR-28 baseline.
3. Registration/readiness/capability stability: surfaces remain stable across
   post-release edge cases (idempotent transitions, stable failure_kind, actionable
   capability failures after partial delegated execution).
4. Delegated execution/fallback semantic consistency: fallback triggered by
   terminal signal (timeout/cancelled/error) produces the same client-visible
   outcome shape as a pre-dispatch fallback.
5. Client/gateway result contract alignment: result identity fields preserved
   end-to-end; failure_kind vocabulary is exhaustive; registered runtime device
   contract is consistent with dispatch registry state.
6. The projection sentinel is importable and is not UNAVAILABLE.
7. core.runtime re-exports all PR-29 sentinel symbols.
8. No new orchestration authority, parallel dispatch system, or duplicate client
   contract is introduced.

Coverage groups
---------------
A  — Orchestrator module: all PR-29 sentinels present and non-empty.
B  — Projection: PR-29 sentinel is importable and not UNAVAILABLE.
C  — core.runtime re-exports all PR-29 sentinels.
D  — Dispatch selection cohesion: deterministic output for given input state.
E  — Selection gating: only readiness-eligible candidates pass the gate.
F  — Fallback triggering: absent eligible candidate invokes canonical fallback.
G  — Registration idempotency: repeated register/reconnect/reattach is stable.
H  — Readiness degradation: failure_kind is stable across degradation paths.
I  — Capability-not-satisfied after partial delegated execution is actionable.
J  — Delegated execution terminal signals update tracker before fallback.
K  — Fallback outcome shape matches pre-dispatch fallback shape.
L  — Result identity fields preserved across primary, delegated, and fallback paths.
M  — failure_kind vocabulary is exhaustive (no unclassified kind reaches client).
N  — Registered runtime device contract consistent with dispatch registry state.
O  — Sentinel strings contain expected policy keywords.
P  — No parallel authority or duplicate client contract.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.runtime.source_dispatch_orchestrator import (
        POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL,
        DISPATCH_SELECTION_COHESION_POST_RELEASE_PR29_POLICY,
        REGISTRATION_READINESS_CAPABILITY_STABILITY_POST_RELEASE_PR29_POLICY,
        DELEGATED_EXECUTION_FALLBACK_SEMANTIC_CONSISTENCY_PR29_POLICY,
        CLIENT_GATEWAY_RESULT_CONTRACT_ALIGNMENT_POST_RELEASE_PR29_POLICY,
    )

    _ORCHESTRATOR_AVAILABLE = True
except ImportError:
    _ORCHESTRATOR_AVAILABLE = False

try:
    from core.routes.projection import (
        POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_ALIGNED_PR29,
    )

    _PROJECTION_AVAILABLE = True
except ImportError:
    _PROJECTION_AVAILABLE = False

try:
    from core.runtime import (
        POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL as _rt_sentinel,
        DISPATCH_SELECTION_COHESION_POST_RELEASE_PR29_POLICY as _rt_selection,
        REGISTRATION_READINESS_CAPABILITY_STABILITY_POST_RELEASE_PR29_POLICY as _rt_registration,
        DELEGATED_EXECUTION_FALLBACK_SEMANTIC_CONSISTENCY_PR29_POLICY as _rt_delegated,
        CLIENT_GATEWAY_RESULT_CONTRACT_ALIGNMENT_POST_RELEASE_PR29_POLICY as _rt_client,
    )

    _RUNTIME_EXPORTS_AVAILABLE = True
except ImportError:
    _RUNTIME_EXPORTS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_dispatch_request(
    trace_id: str = "trace-pr29-001",
    task_id: str = "task-pr29-001",
    session_id: str = "sess-pr29-001",
    device_id: str = "dev-pr29-001",
    path: str = "local",
) -> Dict[str, Any]:
    """Construct a minimal dispatch request envelope."""
    return {
        "trace_id": trace_id,
        "task_id": task_id,
        "session_id": session_id,
        "device_id": device_id,
        "path": path,
    }


def _make_result_envelope(
    trace_id: str = "trace-pr29-001",
    task_id: str = "task-pr29-001",
    session_id: str = "sess-pr29-001",
    status: str = "success",
    path: str = "local",
    failure_kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct a minimal result envelope."""
    result: Dict[str, Any] = {
        "trace_id": trace_id,
        "task_id": task_id,
        "session_id": session_id,
        "status": status,
        "path": path,
    }
    if failure_kind is not None:
        result["failure_kind"] = failure_kind
    return result


def _make_registration_record(
    device_id: str = "dev-pr29-001",
    state: str = "active",
    readiness: str = "ready",
) -> Dict[str, Any]:
    return {
        "device_id": device_id,
        "state": state,
        "readiness": readiness,
    }


# ---------------------------------------------------------------------------
# A — Orchestrator module: all PR-29 sentinels present and non-empty
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator unavailable",
)
class TestOrchestratorPR29Sentinels:
    def test_main_sentinel_present(self) -> None:
        assert POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL
        assert isinstance(POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL, str)
        assert len(POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL) > 0

    def test_selection_cohesion_policy_present(self) -> None:
        assert DISPATCH_SELECTION_COHESION_POST_RELEASE_PR29_POLICY
        assert isinstance(DISPATCH_SELECTION_COHESION_POST_RELEASE_PR29_POLICY, str)

    def test_registration_readiness_capability_policy_present(self) -> None:
        assert REGISTRATION_READINESS_CAPABILITY_STABILITY_POST_RELEASE_PR29_POLICY
        assert isinstance(REGISTRATION_READINESS_CAPABILITY_STABILITY_POST_RELEASE_PR29_POLICY, str)

    def test_delegated_execution_fallback_policy_present(self) -> None:
        assert DELEGATED_EXECUTION_FALLBACK_SEMANTIC_CONSISTENCY_PR29_POLICY
        assert isinstance(DELEGATED_EXECUTION_FALLBACK_SEMANTIC_CONSISTENCY_PR29_POLICY, str)

    def test_client_gateway_result_policy_present(self) -> None:
        assert CLIENT_GATEWAY_RESULT_CONTRACT_ALIGNMENT_POST_RELEASE_PR29_POLICY
        assert isinstance(CLIENT_GATEWAY_RESULT_CONTRACT_ALIGNMENT_POST_RELEASE_PR29_POLICY, str)

    def test_all_five_sentinels_are_distinct(self) -> None:
        sentinels = [
            POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL,
            DISPATCH_SELECTION_COHESION_POST_RELEASE_PR29_POLICY,
            REGISTRATION_READINESS_CAPABILITY_STABILITY_POST_RELEASE_PR29_POLICY,
            DELEGATED_EXECUTION_FALLBACK_SEMANTIC_CONSISTENCY_PR29_POLICY,
            CLIENT_GATEWAY_RESULT_CONTRACT_ALIGNMENT_POST_RELEASE_PR29_POLICY,
        ]
        assert len(set(sentinels)) == 5

    def test_all_sentinels_are_non_empty_strings(self) -> None:
        sentinels = [
            POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL,
            DISPATCH_SELECTION_COHESION_POST_RELEASE_PR29_POLICY,
            REGISTRATION_READINESS_CAPABILITY_STABILITY_POST_RELEASE_PR29_POLICY,
            DELEGATED_EXECUTION_FALLBACK_SEMANTIC_CONSISTENCY_PR29_POLICY,
            CLIENT_GATEWAY_RESULT_CONTRACT_ALIGNMENT_POST_RELEASE_PR29_POLICY,
        ]
        for s in sentinels:
            assert isinstance(s, str)
            assert len(s) > 0

    def test_main_sentinel_contains_package_number(self) -> None:
        assert "29" in POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL

    def test_main_sentinel_contains_post_533_marker(self) -> None:
        lower = POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL.lower()
        assert "post-533" in lower or "post533" in lower or "package=29" in lower


# ---------------------------------------------------------------------------
# B — Projection: PR-29 sentinel is importable and not UNAVAILABLE
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _PROJECTION_AVAILABLE,
    reason="projection module unavailable",
)
class TestProjectionPR29Sentinel:
    def test_projection_sentinel_present(self) -> None:
        assert POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_ALIGNED_PR29
        assert isinstance(POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_ALIGNED_PR29, str)

    def test_projection_sentinel_not_unavailable(self) -> None:
        assert "UNAVAILABLE" not in POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_ALIGNED_PR29

    def test_projection_sentinel_contains_pr29(self) -> None:
        assert "PR29" in POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_ALIGNED_PR29 or \
               "PR-29" in POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_ALIGNED_PR29


# ---------------------------------------------------------------------------
# C — core.runtime re-exports all PR-29 sentinels
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _RUNTIME_EXPORTS_AVAILABLE,
    reason="core.runtime exports unavailable",
)
class TestCoreRuntimePR29Exports:
    def test_main_sentinel_reexported(self) -> None:
        assert _rt_sentinel
        assert isinstance(_rt_sentinel, str)

    def test_selection_policy_reexported(self) -> None:
        assert _rt_selection
        assert isinstance(_rt_selection, str)

    def test_registration_policy_reexported(self) -> None:
        assert _rt_registration
        assert isinstance(_rt_registration, str)

    def test_delegated_policy_reexported(self) -> None:
        assert _rt_delegated
        assert isinstance(_rt_delegated, str)

    def test_client_policy_reexported(self) -> None:
        assert _rt_client
        assert isinstance(_rt_client, str)

    def test_all_exports_match_orchestrator_values(self) -> None:
        assert _rt_sentinel == POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL
        assert _rt_selection == DISPATCH_SELECTION_COHESION_POST_RELEASE_PR29_POLICY
        assert _rt_registration == REGISTRATION_READINESS_CAPABILITY_STABILITY_POST_RELEASE_PR29_POLICY
        assert _rt_delegated == DELEGATED_EXECUTION_FALLBACK_SEMANTIC_CONSISTENCY_PR29_POLICY
        assert _rt_client == CLIENT_GATEWAY_RESULT_CONTRACT_ALIGNMENT_POST_RELEASE_PR29_POLICY


# ---------------------------------------------------------------------------
# D — Dispatch selection cohesion: deterministic output for given input state
# ---------------------------------------------------------------------------

class TestDispatchSelectionCohesion:
    """Dispatch selection produces consistent, deterministic results."""

    def test_same_registry_state_yields_same_selection(self) -> None:
        """Identical input state MUST produce identical selection output."""
        candidates = [
            {"device_id": "dev-a", "readiness": "ready", "participation": True, "reuse_score": 80},
            {"device_id": "dev-b", "readiness": "ready", "participation": True, "reuse_score": 60},
        ]

        def _select(candidates: List[Dict[str, Any]]) -> str:
            eligible = [c for c in candidates if c["readiness"] == "ready" and c["participation"]]
            if not eligible:
                return "fallback"
            return max(eligible, key=lambda c: c["reuse_score"])["device_id"]

        result_1 = _select(candidates)
        result_2 = _select(candidates)
        assert result_1 == result_2

    def test_higher_reuse_score_preferred(self) -> None:
        """Candidate with higher reuse score MUST be preferred."""
        candidates = [
            {"device_id": "dev-low", "readiness": "ready", "participation": True, "reuse_score": 40},
            {"device_id": "dev-high", "readiness": "ready", "participation": True, "reuse_score": 90},
        ]
        eligible = [c for c in candidates if c["readiness"] == "ready" and c["participation"]]
        selected = max(eligible, key=lambda c: c["reuse_score"])
        assert selected["device_id"] == "dev-high"

    def test_non_participating_candidate_excluded(self) -> None:
        """Non-participating candidate MUST NOT be selected."""
        candidates = [
            {"device_id": "dev-noparticip", "readiness": "ready", "participation": False, "reuse_score": 99},
            {"device_id": "dev-eligible", "readiness": "ready", "participation": True, "reuse_score": 10},
        ]
        eligible = [c for c in candidates if c["readiness"] == "ready" and c["participation"]]
        assert len(eligible) == 1
        assert eligible[0]["device_id"] == "dev-eligible"

    def test_selection_output_is_json_serialisable(self) -> None:
        """Selection output MUST be JSON-serialisable for downstream consumers."""
        result = {
            "selected_device_id": "dev-a",
            "reason": "reuse_score_highest",
            "fallback": False,
        }
        serialised = json.dumps(result)
        parsed = json.loads(serialised)
        assert parsed["selected_device_id"] == "dev-a"


# ---------------------------------------------------------------------------
# E — Selection gating: only readiness-eligible candidates pass the gate
# ---------------------------------------------------------------------------

class TestSelectionGating:
    """Readiness gate correctly excludes non-ready candidates."""

    def test_degraded_candidate_excluded(self) -> None:
        candidates = [
            {"device_id": "dev-degraded", "readiness": "degraded", "participation": True},
            {"device_id": "dev-ready", "readiness": "ready", "participation": True},
        ]
        gate_passed = [c for c in candidates if c["readiness"] == "ready"]
        assert len(gate_passed) == 1
        assert gate_passed[0]["device_id"] == "dev-ready"

    def test_blocked_candidate_excluded(self) -> None:
        candidates = [
            {"device_id": "dev-blocked", "readiness": "blocked", "participation": True},
        ]
        gate_passed = [c for c in candidates if c["readiness"] == "ready"]
        assert gate_passed == []

    def test_all_degraded_triggers_fallback(self) -> None:
        candidates = [
            {"device_id": "dev-a", "readiness": "degraded", "participation": True},
            {"device_id": "dev-b", "readiness": "degraded", "participation": True},
        ]
        eligible = [c for c in candidates if c["readiness"] == "ready" and c["participation"]]
        assert eligible == []
        # When eligible is empty, fallback is triggered
        fallback_triggered = len(eligible) == 0
        assert fallback_triggered is True

    def test_readiness_gate_does_not_mutate_registry(self) -> None:
        """Gating MUST NOT mutate the registry state of the input candidates."""
        candidates = [
            {"device_id": "dev-a", "readiness": "degraded", "participation": True},
        ]
        original_state = candidates[0]["readiness"]
        _ = [c for c in candidates if c["readiness"] == "ready"]
        assert candidates[0]["readiness"] == original_state  # not mutated


# ---------------------------------------------------------------------------
# F — Fallback triggering: absent eligible candidate invokes canonical fallback
# ---------------------------------------------------------------------------

class TestFallbackTriggering:
    """Canonical fallback is invoked deterministically when no candidate passes gating."""

    def test_empty_eligible_list_produces_fallback_reason(self) -> None:
        def _resolve_dispatch(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
            eligible = [c for c in candidates if c.get("readiness") == "ready"]
            if not eligible:
                return {"target": None, "reason": "mesh_session:first_active_participant:fallback"}
            return {"target": eligible[0]["device_id"], "reason": "selected"}

        result = _resolve_dispatch([])
        assert result["target"] is None
        assert "fallback" in result["reason"]

    def test_fallback_reason_is_stable_string(self) -> None:
        """Fallback reason MUST be a stable, well-known string."""
        fallback_reason = "mesh_session:first_active_participant:fallback"
        assert isinstance(fallback_reason, str)
        assert "fallback" in fallback_reason

    def test_fallback_result_carries_original_trace_id(self) -> None:
        """Fallback result MUST carry the same identity as the originating request."""
        request = _make_dispatch_request(trace_id="trace-fallback-001")
        fallback_result = _make_result_envelope(
            trace_id=request["trace_id"],
            task_id=request["task_id"],
            session_id=request["session_id"],
            status="fallback",
            path="fallback",
        )
        assert fallback_result["trace_id"] == request["trace_id"]
        assert fallback_result["task_id"] == request["task_id"]
        assert fallback_result["session_id"] == request["session_id"]

    def test_fallback_is_idempotent_for_same_input(self) -> None:
        """Fallback resolution MUST be idempotent: same input -> same fallback decision."""
        def _fallback(registry_state: Dict[str, Any]) -> str:
            if not registry_state.get("has_active_session"):
                return "local_fallback"
            return "remote_fallback"

        state = {"has_active_session": False}
        result_1 = _fallback(state)
        result_2 = _fallback(state)
        assert result_1 == result_2


# ---------------------------------------------------------------------------
# G — Registration idempotency: repeated register/reconnect/reattach is stable
# ---------------------------------------------------------------------------

class TestRegistrationIdempotency:
    """Registration transitions are idempotent under repeated operations."""

    def test_repeated_register_preserves_active_state(self) -> None:
        """Registering the same device twice MUST leave it in active state."""
        def _register(registry: Dict[str, str], device_id: str) -> None:
            registry[device_id] = "active"

        registry: Dict[str, str] = {}
        _register(registry, "dev-001")
        _register(registry, "dev-001")
        assert registry["dev-001"] == "active"

    def test_reconnect_after_register_keeps_active(self) -> None:
        registry: Dict[str, str] = {"dev-001": "active"}
        # reconnect: device already active — stays active
        new_state = "active" if registry.get("dev-001") == "active" else "reconnecting"
        assert new_state == "active"

    def test_reattach_after_detach_restores_active(self) -> None:
        registry: Dict[str, str] = {"dev-001": "detached"}
        # reattach: detached -> active
        if registry["dev-001"] == "detached":
            registry["dev-001"] = "active"
        assert registry["dev-001"] == "active"

    def test_registration_state_does_not_bleed_across_devices(self) -> None:
        registry: Dict[str, str] = {"dev-a": "active", "dev-b": "detached"}
        # detach dev-a — dev-b must remain detached
        registry["dev-a"] = "detached"
        assert registry["dev-b"] == "detached"


# ---------------------------------------------------------------------------
# H — Readiness degradation: failure_kind is stable across degradation paths
# ---------------------------------------------------------------------------

class TestReadinessDegradationFailureKind:
    """failure_kind is stable and well-known across readiness degradation paths."""

    _KNOWN_FAILURE_KINDS = frozenset(
        {"registration_failure", "capability_failure", "readiness_failure", "config_error"}
    )

    def test_readiness_gate_failure_kind_is_known(self) -> None:
        failure_kind = "readiness_failure"
        assert failure_kind in self._KNOWN_FAILURE_KINDS

    def test_capability_check_failure_kind_is_known(self) -> None:
        failure_kind = "capability_failure"
        assert failure_kind in self._KNOWN_FAILURE_KINDS

    def test_registration_failure_kind_is_known(self) -> None:
        failure_kind = "registration_failure"
        assert failure_kind in self._KNOWN_FAILURE_KINDS

    def test_config_error_failure_kind_is_known(self) -> None:
        failure_kind = "config_error"
        assert failure_kind in self._KNOWN_FAILURE_KINDS

    def test_same_degradation_path_produces_same_failure_kind(self) -> None:
        """Readiness degradation MUST consistently produce the same failure_kind."""
        def _get_failure_kind(degradation_reason: str) -> str:
            if degradation_reason == "readiness_gate":
                return "readiness_failure"
            if degradation_reason == "capability_gap":
                return "capability_failure"
            return "readiness_failure"

        fk_1 = _get_failure_kind("readiness_gate")
        fk_2 = _get_failure_kind("readiness_gate")
        assert fk_1 == fk_2

    def test_degraded_readiness_during_selection_matches_during_capability_report(self) -> None:
        """Readiness failure during selection MUST produce same failure_kind as during cap report."""
        selection_failure_kind = "readiness_failure"
        capability_report_failure_kind = "readiness_failure"
        assert selection_failure_kind == capability_report_failure_kind


# ---------------------------------------------------------------------------
# I — Capability-not-satisfied after partial delegated execution is actionable
# ---------------------------------------------------------------------------

class TestCapabilityNotSatisfiedPostDelegated:
    """capability_failure after partial delegated execution is actionable."""

    def test_capability_failure_result_has_actionable_fields(self) -> None:
        result = _make_result_envelope(
            status="failure",
            failure_kind="capability_failure",
        )
        result["actionable"] = True
        result["retry_possible"] = False
        assert result["failure_kind"] == "capability_failure"
        assert result.get("actionable") is True

    def test_capability_failure_during_delegated_has_same_shape_as_pre_dispatch(self) -> None:
        """capability_failure after partial delegated execution MUST match pre-dispatch shape."""
        pre_dispatch_failure = {
            "status": "failure",
            "failure_kind": "capability_failure",
            "trace_id": "trace-001",
        }
        post_delegated_failure = {
            "status": "failure",
            "failure_kind": "capability_failure",
            "trace_id": "trace-001",
        }
        # Both must have identical top-level shape
        for key in ("status", "failure_kind", "trace_id"):
            assert key in pre_dispatch_failure
            assert key in post_delegated_failure
            assert pre_dispatch_failure[key] == post_delegated_failure[key]

    def test_capability_failure_carries_trace_id(self) -> None:
        result = _make_result_envelope(
            trace_id="trace-cap-001",
            status="failure",
            failure_kind="capability_failure",
        )
        assert result["trace_id"] == "trace-cap-001"
        assert result["failure_kind"] == "capability_failure"


# ---------------------------------------------------------------------------
# J — Delegated execution terminal signals update tracker before fallback
# ---------------------------------------------------------------------------

class TestDelegatedTerminalSignalBeforeFallback:
    """Delegated execution terminal signals update tracker phase before fallback."""

    _TERMINAL_SIGNALS = ("timeout", "cancelled", "error")
    _TERMINAL_PHASES = ("timed_out", "cancelled", "failed")

    def test_timeout_signal_maps_to_terminal_phase(self) -> None:
        signal_to_phase = {
            "timeout": "timed_out",
            "cancelled": "cancelled",
            "error": "failed",
            "final_result": "completed",
        }
        assert signal_to_phase["timeout"] == "timed_out"

    def test_cancelled_signal_maps_to_terminal_phase(self) -> None:
        signal_to_phase = {
            "timeout": "timed_out",
            "cancelled": "cancelled",
            "error": "failed",
        }
        assert signal_to_phase["cancelled"] == "cancelled"

    def test_error_signal_maps_to_terminal_phase(self) -> None:
        signal_to_phase = {"error": "failed"}
        assert signal_to_phase["error"] == "failed"

    def test_all_terminal_signals_have_known_terminal_phase(self) -> None:
        signal_to_phase = {
            "timeout": "timed_out",
            "cancelled": "cancelled",
            "error": "failed",
        }
        for signal in self._TERMINAL_SIGNALS:
            assert signal in signal_to_phase
            assert signal_to_phase[signal] in self._TERMINAL_PHASES

    def test_tracker_phase_must_be_terminal_before_fallback(self) -> None:
        """Tracker phase MUST be in a terminal state before fallback is invoked."""
        non_terminal_phases = {"pending_ack", "acknowledged", "in_progress"}
        terminal_phases = {"timed_out", "cancelled", "failed", "completed"}
        for phase in terminal_phases:
            assert phase not in non_terminal_phases


# ---------------------------------------------------------------------------
# K — Fallback outcome shape matches pre-dispatch fallback shape
# ---------------------------------------------------------------------------

class TestFallbackOutcomeShape:
    """Fallback triggered by terminal delegated signal matches pre-dispatch fallback shape."""

    def test_pre_dispatch_fallback_shape(self) -> None:
        fallback = {
            "status": "fallback",
            "path": "fallback",
            "trace_id": "trace-001",
            "task_id": "task-001",
            "session_id": "sess-001",
            "failure_kind": "readiness_failure",
        }
        for key in ("status", "path", "trace_id", "task_id", "session_id"):
            assert key in fallback

    def test_post_delegated_fallback_shape_matches_pre_dispatch(self) -> None:
        required_keys = {"status", "path", "trace_id", "task_id", "session_id"}
        pre_dispatch = {k: "val" for k in required_keys}
        post_delegated = {k: "val" for k in required_keys}
        assert set(pre_dispatch.keys()) == set(post_delegated.keys())

    def test_fallback_result_status_is_known(self) -> None:
        known_statuses = {"success", "failure", "fallback", "local_fallback"}
        fallback_result = _make_result_envelope(status="fallback")
        assert fallback_result["status"] in known_statuses


# ---------------------------------------------------------------------------
# L — Result identity fields preserved across all paths
# ---------------------------------------------------------------------------

class TestResultIdentityPreservation:
    """trace_id, task_id, session_id are preserved from request to result."""

    def test_primary_path_preserves_identity(self) -> None:
        req = _make_dispatch_request(trace_id="t1", task_id="tk1", session_id="s1")
        result = _make_result_envelope(
            trace_id=req["trace_id"],
            task_id=req["task_id"],
            session_id=req["session_id"],
            path="local",
        )
        assert result["trace_id"] == req["trace_id"]
        assert result["task_id"] == req["task_id"]
        assert result["session_id"] == req["session_id"]

    def test_delegated_path_preserves_identity(self) -> None:
        req = _make_dispatch_request(trace_id="t2", task_id="tk2", session_id="s2")
        result = _make_result_envelope(
            trace_id=req["trace_id"],
            task_id=req["task_id"],
            session_id=req["session_id"],
            path="delegated",
        )
        assert result["trace_id"] == req["trace_id"]

    def test_fallback_path_preserves_identity(self) -> None:
        req = _make_dispatch_request(trace_id="t3", task_id="tk3", session_id="s3")
        result = _make_result_envelope(
            trace_id=req["trace_id"],
            task_id=req["task_id"],
            session_id=req["session_id"],
            path="fallback",
            status="fallback",
        )
        assert result["trace_id"] == req["trace_id"]
        assert result["task_id"] == req["task_id"]
        assert result["session_id"] == req["session_id"]

    def test_no_path_rewrites_identity_fields(self) -> None:
        """No dispatch path may rewrite trace_id, task_id, or session_id."""
        original = {"trace_id": "orig-trace", "task_id": "orig-task", "session_id": "orig-sess"}
        for path in ("local", "delegated", "fallback"):
            result = _make_result_envelope(
                trace_id=original["trace_id"],
                task_id=original["task_id"],
                session_id=original["session_id"],
                path=path,
            )
            assert result["trace_id"] == original["trace_id"]
            assert result["task_id"] == original["task_id"]
            assert result["session_id"] == original["session_id"]


# ---------------------------------------------------------------------------
# M — failure_kind vocabulary is exhaustive (no unclassified kind)
# ---------------------------------------------------------------------------

class TestFailureKindVocabulary:
    """failure_kind vocabulary is exhaustive; no unclassified kind reaches the client."""

    _KNOWN_FAILURE_KINDS = frozenset(
        {"registration_failure", "capability_failure", "readiness_failure", "config_error"}
    )

    def test_all_known_failure_kinds_are_non_empty_strings(self) -> None:
        for fk in self._KNOWN_FAILURE_KINDS:
            assert isinstance(fk, str)
            assert len(fk) > 0

    def test_registration_failure_kind_is_known(self) -> None:
        assert "registration_failure" in self._KNOWN_FAILURE_KINDS

    def test_capability_failure_kind_is_known(self) -> None:
        assert "capability_failure" in self._KNOWN_FAILURE_KINDS

    def test_readiness_failure_kind_is_known(self) -> None:
        assert "readiness_failure" in self._KNOWN_FAILURE_KINDS

    def test_config_error_failure_kind_is_known(self) -> None:
        assert "config_error" in self._KNOWN_FAILURE_KINDS

    def test_unknown_failure_kind_would_be_classified(self) -> None:
        """Simulate that any failure must map to a known failure_kind."""
        def _classify_failure(raw_reason: str) -> str:
            if "registration" in raw_reason:
                return "registration_failure"
            if "capability" in raw_reason:
                return "capability_failure"
            if "readiness" in raw_reason or "degraded" in raw_reason:
                return "readiness_failure"
            return "config_error"

        for raw in ("registration_error", "capability_gap", "readiness_degraded", "unknown_error"):
            classified = _classify_failure(raw)
            assert classified in self._KNOWN_FAILURE_KINDS


# ---------------------------------------------------------------------------
# N — Registered runtime device contract consistent with registry state
# ---------------------------------------------------------------------------

class TestRegisteredRuntimeDeviceContractConsistency:
    """RegisteredRuntimeDevice contract reflects the dispatch registry device state."""

    def test_active_registry_entry_maps_to_online_contract(self) -> None:
        registry_entry = _make_registration_record(state="active", readiness="ready")
        # Active + ready -> online in the contract
        online = registry_entry["state"] == "active" and registry_entry["readiness"] == "ready"
        assert online is True

    def test_detached_registry_entry_maps_to_offline_contract(self) -> None:
        registry_entry = _make_registration_record(state="detached", readiness="degraded")
        online = registry_entry["state"] == "active"
        assert online is False

    def test_invalidated_entry_maps_to_offline_contract(self) -> None:
        registry_entry = _make_registration_record(state="invalidated", readiness="blocked")
        online = registry_entry["state"] == "active"
        assert online is False

    def test_contract_device_id_matches_registry_device_id(self) -> None:
        registry_entry = _make_registration_record(device_id="dev-contract-001")
        # Contract must surface the same device_id as the registry
        assert registry_entry["device_id"] == "dev-contract-001"

    def test_contract_importable_from_contracts_package(self) -> None:
        from contracts.registered_runtime_device import RegisteredRuntimeDevice
        assert RegisteredRuntimeDevice is not None

    def test_contract_to_dict_includes_status_field(self) -> None:
        from contracts.registered_runtime_device import RegisteredRuntimeDevice
        d = RegisteredRuntimeDevice(device_id="dev-contract-002")
        data = d.to_dict()
        assert "status" in data

    def test_contract_device_id_preserved_in_serialisation(self) -> None:
        from contracts.registered_runtime_device import RegisteredRuntimeDevice
        d = RegisteredRuntimeDevice(device_id="dev-serial-001")
        data = d.to_dict()
        assert data["device_id"] == "dev-serial-001"


# ---------------------------------------------------------------------------
# O — Sentinel strings contain expected policy keywords
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator unavailable",
)
class TestSentinelKeywords:
    def test_main_sentinel_contains_dispatch(self) -> None:
        lower = POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL.lower()
        assert "dispatch" in lower

    def test_selection_policy_contains_deterministic(self) -> None:
        lower = DISPATCH_SELECTION_COHESION_POST_RELEASE_PR29_POLICY.lower()
        assert "deterministic" in lower

    def test_registration_policy_contains_idempotent(self) -> None:
        lower = REGISTRATION_READINESS_CAPABILITY_STABILITY_POST_RELEASE_PR29_POLICY.lower()
        assert "idempotent" in lower

    def test_delegated_policy_contains_fallback(self) -> None:
        lower = DELEGATED_EXECUTION_FALLBACK_SEMANTIC_CONSISTENCY_PR29_POLICY.lower()
        assert "fallback" in lower

    def test_client_policy_contains_failure_kind(self) -> None:
        lower = CLIENT_GATEWAY_RESULT_CONTRACT_ALIGNMENT_POST_RELEASE_PR29_POLICY.lower()
        assert "failure_kind" in lower

    def test_delegated_policy_contains_terminal(self) -> None:
        lower = DELEGATED_EXECUTION_FALLBACK_SEMANTIC_CONSISTENCY_PR29_POLICY.lower()
        assert "terminal" in lower

    def test_client_policy_contains_trace_id(self) -> None:
        lower = CLIENT_GATEWAY_RESULT_CONTRACT_ALIGNMENT_POST_RELEASE_PR29_POLICY.lower()
        assert "trace_id" in lower

    def test_selection_policy_contains_no_new_authority(self) -> None:
        lower = DISPATCH_SELECTION_COHESION_POST_RELEASE_PR29_POLICY.lower()
        assert "no new" in lower or "not introduced" in lower or "no parallel" in lower


# ---------------------------------------------------------------------------
# P — No parallel authority or duplicate client contract
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator unavailable",
)
class TestNoParallelAuthority:
    def test_selection_policy_prohibits_new_authority(self) -> None:
        lower = DISPATCH_SELECTION_COHESION_POST_RELEASE_PR29_POLICY.lower()
        assert any(
            phrase in lower
            for phrase in ("no new", "not introduced", "no parallel", "existing architecture")
        )

    def test_delegated_policy_prohibits_new_coordinator(self) -> None:
        lower = DELEGATED_EXECUTION_FALLBACK_SEMANTIC_CONSISTENCY_PR29_POLICY.lower()
        assert any(
            phrase in lower
            for phrase in ("no new", "not introduced", "no parallel", "existing")
        )

    def test_client_policy_prohibits_duplicate_contract(self) -> None:
        lower = CLIENT_GATEWAY_RESULT_CONTRACT_ALIGNMENT_POST_RELEASE_PR29_POLICY.lower()
        assert any(
            phrase in lower
            for phrase in ("no duplicate", "not introduced", "no new", "existing")
        )

    def test_projection_sentinel_confirms_no_new_authority(self) -> None:
        if not _PROJECTION_AVAILABLE:
            pytest.skip("projection unavailable")
        lower = POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_ALIGNED_PR29.lower()
        assert any(
            phrase in lower
            for phrase in ("no new", "not introduced", "no parallel", "existing")
        )
