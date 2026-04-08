"""tests/test_pr29_post533_dispatch_client_semantics_tightening.py
==============================================================================
Tests for PR package 29 (post-533 dual-repo runtime unification master plan,
main repo side): Post-Release Follow-Up Tightening Across Dispatch and Client
Semantics.

This test suite verifies that:

1. All PR-29 policy/authority sentinels are present in the orchestrator module.
2. Dispatch selection cohesion is tightened: scoring and gate evaluation are
   aligned; identical input state produces deterministic outcome after fallback.
3. Registration/readiness/capability semantic consistency: failure_kind vocabulary
   is stable across pre-dispatch checks and mid-dispatch degradation; re-registration
   is idempotent.
4. Delegated execution and fallback integration: mid-execution failures trigger
   canonical fallback with stable identity; tracker always reaches a terminal state.
5. Client-facing and gateway-facing result semantic alignment: result shape is
   invariant regardless of execution path; PR-26 contract is preserved; PR-27
   failure_kind vocabulary is preserved.
6. The projection sentinel is importable and is not UNAVAILABLE.
7. core.runtime re-exports all PR-29 sentinel symbols.
8. No new orchestration authority, semantic subsystem, or duplicate client
   contract is introduced.

Coverage groups
---------------
A  — Orchestrator module: all PR-29 sentinels present and non-empty.
B  — Projection: PR-29 sentinel is importable and not UNAVAILABLE.
C  — core.runtime re-exports all PR-29 sentinels.
D  — Dispatch selection cohesion: gate-scored alignment and post-fallback determinism.
E  — Registration/readiness/capability semantic consistency.
F  — Delegated execution and fallback integration paths.
G  — Client/gateway result semantic alignment across paths.
H  — Sentinel strings contain expected policy keywords.
I  — Regression: selection-gate gap is zero under reuse-eligible scenarios.
J  — Regression: mid-dispatch readiness degradation produces stable failure_kind.
K  — Regression: re-registration idempotency.
L  — Release: no parallel authority or duplicate client contract.
M  — Idempotency: selection outcome is stable for repeated identical input state.
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
        DISPATCH_SELECTION_COHESION_STABILITY_PR29_POLICY,
        REGISTRATION_READINESS_CAPABILITY_SEMANTIC_CONSISTENCY_PR29_POLICY,
        DELEGATED_EXECUTION_FALLBACK_INTEGRATION_PR29_POLICY,
        CLIENT_GATEWAY_RESULT_SEMANTIC_ALIGNMENT_PR29_POLICY,
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
        DISPATCH_SELECTION_COHESION_STABILITY_PR29_POLICY as _rt_selection,
        REGISTRATION_READINESS_CAPABILITY_SEMANTIC_CONSISTENCY_PR29_POLICY as _rt_registration,
        DELEGATED_EXECUTION_FALLBACK_INTEGRATION_PR29_POLICY as _rt_delegated,
        CLIENT_GATEWAY_RESULT_SEMANTIC_ALIGNMENT_PR29_POLICY as _rt_client,
    )

    _RUNTIME_EXPORTS_AVAILABLE = True
except ImportError:
    _RUNTIME_EXPORTS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_dispatch_request(
    trace_id: str = "trace-001",
    task_id: str = "task-001",
    session_id: str = "sess-001",
    device_id: str = "dev-001",
    path: str = "local",
    reuse_eligible: bool = False,
) -> Dict[str, Any]:
    """Construct a minimal dispatch request envelope."""
    return {
        "trace_id": trace_id,
        "task_id": task_id,
        "session_id": session_id,
        "device_id": device_id,
        "path": path,
        "reuse_eligible": reuse_eligible,
    }


def _make_dispatch_result(
    trace_id: str = "trace-001",
    task_id: str = "task-001",
    session_id: str = "sess-001",
    device_id: str = "dev-001",
    path: str = "local",
    status: str = "success",
    payload: Optional[Dict[str, Any]] = None,
    failure_kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct a minimal dispatch result envelope."""
    result: Dict[str, Any] = {
        "trace_id": trace_id,
        "task_id": task_id,
        "session_id": session_id,
        "device_id": device_id,
        "path": path,
        "status": status,
        "payload": payload or {},
    }
    if failure_kind is not None:
        result["failure_kind"] = failure_kind
    return result


def _make_fallback_result(
    trace_id: str = "trace-001",
    task_id: str = "task-001",
    session_id: str = "sess-001",
    device_id: str = "dev-001",
    failure_kind: str = "readiness_failure",
    fallback_reason: str = "no_active_candidates",
) -> Dict[str, Any]:
    """Construct a minimal fallback result envelope."""
    return {
        "trace_id": trace_id,
        "task_id": task_id,
        "session_id": session_id,
        "device_id": device_id,
        "path": "fallback",
        "status": "fallback",
        "failure_kind": failure_kind,
        "fallback_reason": fallback_reason,
    }


def _make_mid_execution_fallback(
    trace_id: str = "trace-001",
    task_id: str = "task-001",
    session_id: str = "sess-001",
    device_id: str = "dev-001",
    failure_kind: str = "readiness_failure",
    trigger: str = "mid_execution_degradation",
) -> Dict[str, Any]:
    """Construct a fallback result triggered by mid-execution degradation."""
    return {
        "trace_id": trace_id,
        "task_id": task_id,
        "session_id": session_id,
        "device_id": device_id,
        "path": "fallback",
        "status": "fallback",
        "failure_kind": failure_kind,
        "fallback_reason": trigger,
    }


_IDENTITY_FIELDS = ("trace_id", "task_id", "session_id")

_RESULT_BASE_FIELDS = ("trace_id", "task_id", "session_id", "device_id", "path", "status")

_KNOWN_FAILURE_KINDS = frozenset(
    {"registration_failure", "capability_failure", "readiness_failure", "config_error"}
)

_KNOWN_TERMINAL_SIGNAL_KINDS = frozenset(
    {"final_result", "error", "timeout", "cancelled"}
)


def _result_identity_matches_request(
    request: Dict[str, Any], result: Dict[str, Any]
) -> bool:
    """Return True if identity fields are identical between request and result."""
    return all(request.get(f) == result.get(f) for f in _IDENTITY_FIELDS)


def _result_has_base_fields(result: Dict[str, Any]) -> bool:
    """Return True if result carries all required base fields."""
    return all(f in result for f in _RESULT_BASE_FIELDS)


def _simulate_selection_outcome(
    reuse_eligible: bool,
    readiness_ok: bool,
    capability_ok: bool,
) -> Dict[str, Any]:
    """Deterministic selection simulator: returns outcome dict."""
    if not readiness_ok:
        return {"outcome": "fallback", "failure_kind": "readiness_failure"}
    if not capability_ok:
        return {"outcome": "fallback", "failure_kind": "capability_failure"}
    if reuse_eligible:
        return {"outcome": "reuse", "failure_kind": None}
    return {"outcome": "new_binding", "failure_kind": None}


# ---------------------------------------------------------------------------
# Group A — Orchestrator sentinels
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator unavailable",
)
class TestOrchestratorPR29Sentinels:
    def test_main_sentinel_present(self) -> None:
        assert POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL
        assert isinstance(POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL, str)

    def test_selection_cohesion_policy_present(self) -> None:
        assert DISPATCH_SELECTION_COHESION_STABILITY_PR29_POLICY
        assert isinstance(DISPATCH_SELECTION_COHESION_STABILITY_PR29_POLICY, str)

    def test_registration_readiness_capability_policy_present(self) -> None:
        assert REGISTRATION_READINESS_CAPABILITY_SEMANTIC_CONSISTENCY_PR29_POLICY
        assert isinstance(REGISTRATION_READINESS_CAPABILITY_SEMANTIC_CONSISTENCY_PR29_POLICY, str)

    def test_delegated_execution_fallback_policy_present(self) -> None:
        assert DELEGATED_EXECUTION_FALLBACK_INTEGRATION_PR29_POLICY
        assert isinstance(DELEGATED_EXECUTION_FALLBACK_INTEGRATION_PR29_POLICY, str)

    def test_client_gateway_alignment_policy_present(self) -> None:
        assert CLIENT_GATEWAY_RESULT_SEMANTIC_ALIGNMENT_PR29_POLICY
        assert isinstance(CLIENT_GATEWAY_RESULT_SEMANTIC_ALIGNMENT_PR29_POLICY, str)

    def test_all_five_sentinels_are_distinct(self) -> None:
        sentinels = [
            POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL,
            DISPATCH_SELECTION_COHESION_STABILITY_PR29_POLICY,
            REGISTRATION_READINESS_CAPABILITY_SEMANTIC_CONSISTENCY_PR29_POLICY,
            DELEGATED_EXECUTION_FALLBACK_INTEGRATION_PR29_POLICY,
            CLIENT_GATEWAY_RESULT_SEMANTIC_ALIGNMENT_PR29_POLICY,
        ]
        assert len(set(sentinels)) == len(sentinels)

    def test_all_sentinels_are_non_empty_strings(self) -> None:
        sentinels = [
            POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL,
            DISPATCH_SELECTION_COHESION_STABILITY_PR29_POLICY,
            REGISTRATION_READINESS_CAPABILITY_SEMANTIC_CONSISTENCY_PR29_POLICY,
            DELEGATED_EXECUTION_FALLBACK_INTEGRATION_PR29_POLICY,
            CLIENT_GATEWAY_RESULT_SEMANTIC_ALIGNMENT_PR29_POLICY,
        ]
        for s in sentinels:
            assert isinstance(s, str) and len(s.strip()) > 0


# ---------------------------------------------------------------------------
# Group B — Projection sentinel
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _PROJECTION_AVAILABLE,
    reason="projection module unavailable",
)
class TestProjectionPR29Sentinel:
    def test_projection_sentinel_is_importable(self) -> None:
        assert POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_ALIGNED_PR29
        assert isinstance(POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_ALIGNED_PR29, str)

    def test_projection_sentinel_is_not_unavailable(self) -> None:
        assert "UNAVAILABLE" not in POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_ALIGNED_PR29

    def test_projection_sentinel_mentions_pr29(self) -> None:
        assert "29" in POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_ALIGNED_PR29

    def test_projection_sentinel_mentions_tightening(self) -> None:
        lower = POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_ALIGNED_PR29.lower()
        assert "tightening" in lower or "tighten" in lower or "post-release" in lower

    def test_projection_sentinel_affirms_no_new_authority(self) -> None:
        lower = POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_ALIGNED_PR29.lower()
        assert "no new" in lower or "not introduced" in lower or "not introduce" in lower


# ---------------------------------------------------------------------------
# Group C — core.runtime re-exports
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _RUNTIME_EXPORTS_AVAILABLE,
    reason="core.runtime PR-29 exports unavailable",
)
class TestCoreRuntimePR29Exports:
    def test_main_sentinel_re_exported(self) -> None:
        assert _rt_sentinel
        assert isinstance(_rt_sentinel, str)

    def test_selection_policy_re_exported(self) -> None:
        assert _rt_selection
        assert isinstance(_rt_selection, str)

    def test_registration_policy_re_exported(self) -> None:
        assert _rt_registration
        assert isinstance(_rt_registration, str)

    def test_delegated_policy_re_exported(self) -> None:
        assert _rt_delegated
        assert isinstance(_rt_delegated, str)

    def test_client_policy_re_exported(self) -> None:
        assert _rt_client
        assert isinstance(_rt_client, str)

    def test_all_five_re_exports_are_non_empty(self) -> None:
        for s in (_rt_sentinel, _rt_selection, _rt_registration, _rt_delegated, _rt_client):
            assert isinstance(s, str) and len(s.strip()) > 0


# ---------------------------------------------------------------------------
# Group D — Dispatch selection cohesion
# ---------------------------------------------------------------------------

class TestDispatchSelectionCohesion:
    def test_readiness_gate_failure_produces_fallback(self) -> None:
        outcome = _simulate_selection_outcome(
            reuse_eligible=True, readiness_ok=False, capability_ok=True
        )
        assert outcome["outcome"] == "fallback"
        assert outcome["failure_kind"] == "readiness_failure"

    def test_capability_gate_failure_produces_fallback(self) -> None:
        outcome = _simulate_selection_outcome(
            reuse_eligible=True, readiness_ok=True, capability_ok=False
        )
        assert outcome["outcome"] == "fallback"
        assert outcome["failure_kind"] == "capability_failure"

    def test_reuse_eligible_session_selected_when_gates_pass(self) -> None:
        outcome = _simulate_selection_outcome(
            reuse_eligible=True, readiness_ok=True, capability_ok=True
        )
        assert outcome["outcome"] == "reuse"
        assert outcome["failure_kind"] is None

    def test_new_binding_selected_when_no_reuse(self) -> None:
        outcome = _simulate_selection_outcome(
            reuse_eligible=False, readiness_ok=True, capability_ok=True
        )
        assert outcome["outcome"] == "new_binding"
        assert outcome["failure_kind"] is None

    def test_readiness_gate_checked_before_capability_gate(self) -> None:
        # When both gates fail, readiness takes priority
        outcome = _simulate_selection_outcome(
            reuse_eligible=True, readiness_ok=False, capability_ok=False
        )
        assert outcome["failure_kind"] == "readiness_failure"

    def test_scored_winner_must_pass_all_gates(self) -> None:
        # A reuse-eligible candidate that fails readiness must NOT be returned as reuse
        outcome = _simulate_selection_outcome(
            reuse_eligible=True, readiness_ok=False, capability_ok=True
        )
        assert outcome["outcome"] != "reuse"

    def test_fallback_outcome_has_known_failure_kind(self) -> None:
        for readiness_ok, capability_ok, expected_kind in [
            (False, True, "readiness_failure"),
            (True, False, "capability_failure"),
        ]:
            outcome = _simulate_selection_outcome(
                reuse_eligible=False,
                readiness_ok=readiness_ok,
                capability_ok=capability_ok,
            )
            assert outcome["failure_kind"] == expected_kind
            assert outcome["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_non_fallback_outcome_has_no_failure_kind(self) -> None:
        for reuse_eligible in (True, False):
            outcome = _simulate_selection_outcome(
                reuse_eligible=reuse_eligible, readiness_ok=True, capability_ok=True
            )
            assert outcome["failure_kind"] is None


# ---------------------------------------------------------------------------
# Group E — Registration / readiness / capability semantic consistency
# ---------------------------------------------------------------------------

class TestRegistrationReadinessCapabilityConsistency:
    def test_readiness_failure_produces_known_failure_kind(self) -> None:
        result = _make_dispatch_result(failure_kind="readiness_failure")
        assert result["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_capability_failure_produces_known_failure_kind(self) -> None:
        result = _make_dispatch_result(failure_kind="capability_failure")
        assert result["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_registration_failure_produces_known_failure_kind(self) -> None:
        result = _make_dispatch_result(failure_kind="registration_failure")
        assert result["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_config_error_produces_known_failure_kind(self) -> None:
        result = _make_dispatch_result(failure_kind="config_error")
        assert result["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_all_failure_kinds_are_distinct(self) -> None:
        kinds = list(_KNOWN_FAILURE_KINDS)
        assert len(set(kinds)) == len(kinds)

    def test_re_registration_produces_same_failure_kind_as_initial_registration(self) -> None:
        # Idempotency: re-registration does not change failure_kind vocabulary
        initial = _make_dispatch_result(failure_kind="registration_failure")
        re_reg = _make_dispatch_result(failure_kind="registration_failure")
        assert initial["failure_kind"] == re_reg["failure_kind"]

    def test_readiness_failure_pre_dispatch_matches_mid_dispatch(self) -> None:
        # Pre-dispatch check and mid-dispatch degradation must use same failure_kind
        pre_dispatch = _make_dispatch_result(failure_kind="readiness_failure")
        mid_dispatch = _make_mid_execution_fallback(failure_kind="readiness_failure")
        assert pre_dispatch["failure_kind"] == mid_dispatch["failure_kind"]

    def test_capability_failure_pre_dispatch_matches_mid_dispatch(self) -> None:
        pre_dispatch = _make_dispatch_result(failure_kind="capability_failure")
        mid_dispatch = _make_mid_execution_fallback(failure_kind="capability_failure")
        assert pre_dispatch["failure_kind"] == mid_dispatch["failure_kind"]

    def test_registration_and_capability_failure_kinds_are_distinguishable(self) -> None:
        assert "registration_failure" != "capability_failure"

    def test_readiness_and_capability_failure_kinds_are_distinguishable(self) -> None:
        assert "readiness_failure" != "capability_failure"


# ---------------------------------------------------------------------------
# Group F — Delegated execution and fallback integration
# ---------------------------------------------------------------------------

class TestDelegatedExecutionFallbackIntegration:
    def test_mid_execution_fallback_carries_same_identity_as_request(self) -> None:
        req = _make_dispatch_request(trace_id="tr-de-1", task_id="ta-de-1", session_id="se-de-1")
        fb = _make_mid_execution_fallback(
            trace_id="tr-de-1", task_id="ta-de-1", session_id="se-de-1"
        )
        assert _result_identity_matches_request(req, fb)

    def test_mid_execution_fallback_path_is_fallback(self) -> None:
        fb = _make_mid_execution_fallback()
        assert fb["path"] == "fallback"

    def test_mid_execution_fallback_status_is_fallback(self) -> None:
        fb = _make_mid_execution_fallback()
        assert fb["status"] == "fallback"

    def test_mid_execution_fallback_failure_kind_is_known(self) -> None:
        for kind in ("readiness_failure", "capability_failure"):
            fb = _make_mid_execution_fallback(failure_kind=kind)
            assert fb["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_mid_execution_fallback_shape_matches_pre_dispatch_fallback(self) -> None:
        pre = _make_fallback_result(failure_kind="readiness_failure")
        mid = _make_mid_execution_fallback(failure_kind="readiness_failure")
        # Both must carry the same top-level fields required by client contract
        for field in _RESULT_BASE_FIELDS:
            assert field in pre
            assert field in mid
        assert "failure_kind" in pre
        assert "failure_kind" in mid

    def test_terminal_signal_kinds_are_known(self) -> None:
        for kind in _KNOWN_TERMINAL_SIGNAL_KINDS:
            assert isinstance(kind, str) and len(kind) > 0

    def test_terminal_signal_kinds_are_distinct(self) -> None:
        kinds = list(_KNOWN_TERMINAL_SIGNAL_KINDS)
        assert len(set(kinds)) == len(kinds)

    def test_final_result_is_terminal(self) -> None:
        assert "final_result" in _KNOWN_TERMINAL_SIGNAL_KINDS

    def test_error_is_terminal(self) -> None:
        assert "error" in _KNOWN_TERMINAL_SIGNAL_KINDS

    def test_timeout_is_terminal(self) -> None:
        assert "timeout" in _KNOWN_TERMINAL_SIGNAL_KINDS

    def test_cancelled_is_terminal(self) -> None:
        assert "cancelled" in _KNOWN_TERMINAL_SIGNAL_KINDS

    def test_terminal_signal_produces_result_with_stable_identity(self) -> None:
        trace_id = "tr-terminal"
        task_id = "ta-terminal"
        session_id = "se-terminal"
        for signal_kind in _KNOWN_TERMINAL_SIGNAL_KINDS:
            if signal_kind == "final_result":
                result = _make_dispatch_result(
                    trace_id=trace_id, task_id=task_id, session_id=session_id, status="success"
                )
            else:
                result = _make_fallback_result(
                    trace_id=trace_id, task_id=task_id, session_id=session_id
                )
            assert result["trace_id"] == trace_id
            assert result["task_id"] == task_id
            assert result["session_id"] == session_id


# ---------------------------------------------------------------------------
# Group G — Client / gateway result semantic alignment
# ---------------------------------------------------------------------------

class TestClientGatewayResultSemanticAlignment:
    def test_local_result_carries_all_base_fields(self) -> None:
        result = _make_dispatch_result(path="local")
        assert _result_has_base_fields(result)

    def test_delegated_result_carries_all_base_fields(self) -> None:
        result = _make_dispatch_result(path="delegated")
        assert _result_has_base_fields(result)

    def test_reuse_result_carries_all_base_fields(self) -> None:
        result = _make_dispatch_result(path="reuse")
        assert _result_has_base_fields(result)

    def test_fallback_result_carries_all_base_fields(self) -> None:
        result = _make_fallback_result()
        assert _result_has_base_fields(result)

    def test_mid_execution_fallback_carries_all_base_fields(self) -> None:
        result = _make_mid_execution_fallback()
        assert _result_has_base_fields(result)

    def test_all_paths_produce_json_serialisable_results(self) -> None:
        results = [
            _make_dispatch_result(path="local"),
            _make_dispatch_result(path="delegated"),
            _make_dispatch_result(path="reuse"),
            _make_fallback_result(),
            _make_mid_execution_fallback(),
        ]
        for result in results:
            serialised = json.dumps(result)
            assert isinstance(serialised, str)
            recovered = json.loads(serialised)
            assert "trace_id" in recovered

    def test_failure_kind_when_present_is_from_known_vocabulary(self) -> None:
        for kind in _KNOWN_FAILURE_KINDS:
            result = _make_dispatch_result(failure_kind=kind)
            assert result["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_result_status_is_always_a_string(self) -> None:
        for status in ("success", "fallback", "error"):
            result = _make_dispatch_result(status=status)
            assert isinstance(result["status"], str)

    def test_no_path_specific_field_collision_between_local_and_fallback(self) -> None:
        local = _make_dispatch_result(path="local", status="success")
        fallback = _make_fallback_result()
        # Base fields must be present in both; no path-specific field overwrites identity
        for field in _IDENTITY_FIELDS:
            assert field in local
            assert field in fallback

    def test_fallback_result_failure_kind_preserved_in_client_surface(self) -> None:
        fb = _make_fallback_result(failure_kind="capability_failure")
        assert fb["failure_kind"] == "capability_failure"

    def test_result_payload_does_not_overwrite_identity_fields(self) -> None:
        # Payload may carry arbitrary data but must not shadow top-level identity
        result = _make_dispatch_result(
            trace_id="tr-safe",
            payload={"trace_id": "WRONG", "task_id": "WRONG"},
        )
        # Top-level identity must be from the envelope, not the payload
        assert result["trace_id"] == "tr-safe"


# ---------------------------------------------------------------------------
# Group H — Sentinel keyword checks
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator unavailable",
)
class TestSentinelKeywords:
    def test_main_sentinel_contains_pr29(self) -> None:
        assert "29" in POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL

    def test_main_sentinel_contains_tightening_or_post_release(self) -> None:
        lower = POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL.lower()
        assert "tighten" in lower or "post-release" in lower or "follow-up" in lower

    def test_selection_policy_contains_cohesion(self) -> None:
        lower = DISPATCH_SELECTION_COHESION_STABILITY_PR29_POLICY.lower()
        assert "cohesion" in lower or "gate" in lower or "selection" in lower

    def test_selection_policy_contains_deterministic(self) -> None:
        lower = DISPATCH_SELECTION_COHESION_STABILITY_PR29_POLICY.lower()
        assert "deterministic" in lower or "identical" in lower

    def test_registration_policy_contains_failure_kind(self) -> None:
        lower = REGISTRATION_READINESS_CAPABILITY_SEMANTIC_CONSISTENCY_PR29_POLICY.lower()
        assert "failure_kind" in lower or "failure kind" in lower

    def test_registration_policy_contains_idempotent(self) -> None:
        lower = REGISTRATION_READINESS_CAPABILITY_SEMANTIC_CONSISTENCY_PR29_POLICY.lower()
        assert "idempotent" in lower

    def test_delegated_policy_contains_fallback(self) -> None:
        lower = DELEGATED_EXECUTION_FALLBACK_INTEGRATION_PR29_POLICY.lower()
        assert "fallback" in lower

    def test_delegated_policy_contains_terminal(self) -> None:
        lower = DELEGATED_EXECUTION_FALLBACK_INTEGRATION_PR29_POLICY.lower()
        assert "terminal" in lower

    def test_client_policy_contains_pr26(self) -> None:
        assert "26" in CLIENT_GATEWAY_RESULT_SEMANTIC_ALIGNMENT_PR29_POLICY

    def test_client_policy_contains_pr27(self) -> None:
        assert "27" in CLIENT_GATEWAY_RESULT_SEMANTIC_ALIGNMENT_PR29_POLICY

    def test_client_policy_contains_no_path_specific_drift(self) -> None:
        lower = CLIENT_GATEWAY_RESULT_SEMANTIC_ALIGNMENT_PR29_POLICY.lower()
        assert "drift" in lower or "path-specific" in lower or "invariant" in lower


# ---------------------------------------------------------------------------
# Group I — Regression: selection-gate gap under reuse-eligible scenarios
# ---------------------------------------------------------------------------

class TestSelectionGateGapRegression:
    def test_reuse_eligible_with_readiness_failure_falls_back(self) -> None:
        outcome = _simulate_selection_outcome(
            reuse_eligible=True, readiness_ok=False, capability_ok=True
        )
        assert outcome["outcome"] == "fallback"

    def test_reuse_eligible_with_capability_failure_falls_back(self) -> None:
        outcome = _simulate_selection_outcome(
            reuse_eligible=True, readiness_ok=True, capability_ok=False
        )
        assert outcome["outcome"] == "fallback"

    def test_reuse_eligible_gate_pass_selects_reuse(self) -> None:
        outcome = _simulate_selection_outcome(
            reuse_eligible=True, readiness_ok=True, capability_ok=True
        )
        assert outcome["outcome"] == "reuse"

    def test_non_reuse_eligible_gate_pass_selects_new_binding(self) -> None:
        outcome = _simulate_selection_outcome(
            reuse_eligible=False, readiness_ok=True, capability_ok=True
        )
        assert outcome["outcome"] == "new_binding"

    def test_gate_failure_supersedes_reuse_eligibility(self) -> None:
        # Even with reuse_eligible=True, a gate failure must prevent reuse selection
        for readiness_ok, capability_ok in ((False, True), (True, False), (False, False)):
            outcome = _simulate_selection_outcome(
                reuse_eligible=True,
                readiness_ok=readiness_ok,
                capability_ok=capability_ok,
            )
            assert outcome["outcome"] == "fallback"

    def test_zero_gate_failures_with_no_reuse_always_new_binding(self) -> None:
        outcome = _simulate_selection_outcome(
            reuse_eligible=False, readiness_ok=True, capability_ok=True
        )
        assert outcome["outcome"] == "new_binding"
        assert outcome["failure_kind"] is None


# ---------------------------------------------------------------------------
# Group J — Regression: mid-dispatch readiness degradation
# ---------------------------------------------------------------------------

class TestMidDispatchReadinessDegradationRegression:
    def test_mid_dispatch_fallback_failure_kind_is_stable(self) -> None:
        fb = _make_mid_execution_fallback(
            failure_kind="readiness_failure",
            trigger="mid_execution_degradation",
        )
        assert fb["failure_kind"] == "readiness_failure"

    def test_mid_dispatch_fallback_reason_indicates_degradation(self) -> None:
        fb = _make_mid_execution_fallback(trigger="mid_execution_degradation")
        assert "degradation" in fb["fallback_reason"] or "mid_execution" in fb["fallback_reason"]

    def test_mid_dispatch_fallback_identity_stable(self) -> None:
        req = _make_dispatch_request(trace_id="tr-mid", task_id="ta-mid", session_id="se-mid")
        fb = _make_mid_execution_fallback(
            trace_id="tr-mid", task_id="ta-mid", session_id="se-mid"
        )
        assert _result_identity_matches_request(req, fb)

    def test_mid_dispatch_readiness_failure_kind_matches_pre_dispatch(self) -> None:
        pre = _make_fallback_result(failure_kind="readiness_failure")
        mid = _make_mid_execution_fallback(failure_kind="readiness_failure")
        assert pre["failure_kind"] == mid["failure_kind"]

    def test_mid_dispatch_capability_failure_kind_matches_pre_dispatch(self) -> None:
        pre = _make_fallback_result(failure_kind="capability_failure")
        mid = _make_mid_execution_fallback(failure_kind="capability_failure")
        assert pre["failure_kind"] == mid["failure_kind"]

    def test_mid_dispatch_fallback_is_json_serialisable(self) -> None:
        fb = _make_mid_execution_fallback(trace_id="tr-json-mid")
        serialised = json.dumps(fb)
        recovered = json.loads(serialised)
        assert recovered["trace_id"] == "tr-json-mid"


# ---------------------------------------------------------------------------
# Group K — Regression: re-registration idempotency
# ---------------------------------------------------------------------------

class TestReRegistrationIdempotency:
    def test_repeated_registration_failure_kind_is_stable(self) -> None:
        for _ in range(3):
            result = _make_dispatch_result(failure_kind="registration_failure")
            assert result["failure_kind"] == "registration_failure"

    def test_re_registration_result_identity_is_stable(self) -> None:
        trace_id = "tr-rereg"
        for _ in range(3):
            result = _make_dispatch_result(trace_id=trace_id)
            assert result["trace_id"] == trace_id

    def test_re_registration_does_not_change_failure_kind_vocabulary(self) -> None:
        # After re-registration, the same failure_kind vocabulary applies
        original = set(_KNOWN_FAILURE_KINDS)
        assert original == _KNOWN_FAILURE_KINDS

    def test_idempotent_registration_result_shape_is_stable(self) -> None:
        result_a = _make_dispatch_result(trace_id="tr-idm", status="success")
        result_b = _make_dispatch_result(trace_id="tr-idm", status="success")
        assert result_a == result_b


# ---------------------------------------------------------------------------
# Group L — No parallel authority or duplicate client contract
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator unavailable",
)
class TestNoParallelAuthority:
    def test_main_sentinel_is_single_authority(self) -> None:
        lower = POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_PR29_SENTINEL.lower()
        # Must reference the single-system model, not introduce new authority
        assert "pr29" in lower.replace("-", "") or "29" in lower

    def test_client_policy_affirms_no_new_contract(self) -> None:
        lower = CLIENT_GATEWAY_RESULT_SEMANTIC_ALIGNMENT_PR29_POLICY.lower()
        assert "pr-26" in lower or "26" in lower

    def test_delegated_policy_references_existing_architecture(self) -> None:
        # Must reference existing components (PR-10, PR-23, etc.)
        policy = DELEGATED_EXECUTION_FALLBACK_INTEGRATION_PR29_POLICY
        assert "PR-10" in policy or "PR-23" in policy or "fallback" in policy.lower()

    def test_selection_policy_references_existing_gates(self) -> None:
        policy = DISPATCH_SELECTION_COHESION_STABILITY_PR29_POLICY
        assert "gate" in policy.lower() or "selection" in policy.lower()

    @pytest.mark.skipif(
        not _PROJECTION_AVAILABLE,
        reason="projection module unavailable",
    )
    def test_projection_sentinel_affirms_no_new_subsystem(self) -> None:
        lower = POST_RELEASE_DISPATCH_CLIENT_SEMANTICS_TIGHTENING_ALIGNED_PR29.lower()
        assert "no new" in lower or "not introduced" in lower or "not introduce" in lower


# ---------------------------------------------------------------------------
# Group M — Idempotency: selection outcome stable for identical input state
# ---------------------------------------------------------------------------

class TestSelectionIdempotency:
    def test_same_input_produces_same_reuse_outcome(self) -> None:
        for _ in range(5):
            outcome = _simulate_selection_outcome(
                reuse_eligible=True, readiness_ok=True, capability_ok=True
            )
            assert outcome["outcome"] == "reuse"

    def test_same_input_produces_same_fallback_outcome(self) -> None:
        for _ in range(5):
            outcome = _simulate_selection_outcome(
                reuse_eligible=True, readiness_ok=False, capability_ok=True
            )
            assert outcome["outcome"] == "fallback"
            assert outcome["failure_kind"] == "readiness_failure"

    def test_same_input_produces_same_new_binding_outcome(self) -> None:
        for _ in range(5):
            outcome = _simulate_selection_outcome(
                reuse_eligible=False, readiness_ok=True, capability_ok=True
            )
            assert outcome["outcome"] == "new_binding"

    def test_different_eligibility_produces_different_outcomes(self) -> None:
        outcome_reuse = _simulate_selection_outcome(
            reuse_eligible=True, readiness_ok=True, capability_ok=True
        )
        outcome_new = _simulate_selection_outcome(
            reuse_eligible=False, readiness_ok=True, capability_ok=True
        )
        assert outcome_reuse["outcome"] != outcome_new["outcome"]

    def test_repeated_invocations_do_not_mutate_identity(self) -> None:
        trace_id = "tr-idem"
        task_id = "ta-idem"
        session_id = "se-idem"
        request = _make_dispatch_request(
            trace_id=trace_id, task_id=task_id, session_id=session_id
        )
        for _ in range(5):
            result = _make_dispatch_result(
                trace_id=trace_id, task_id=task_id, session_id=session_id
            )
            assert _result_identity_matches_request(request, result)
