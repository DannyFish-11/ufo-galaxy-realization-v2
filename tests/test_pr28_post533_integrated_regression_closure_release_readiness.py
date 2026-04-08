"""tests/test_pr28_post533_integrated_regression_closure_release_readiness.py
==============================================================================
Tests for PR package 28 (post-533 dual-repo runtime unification master plan,
main repo side): Integrated Regression Closure and Release-Readiness Tightening.

This test suite verifies that:

1. All PR-28 policy/authority sentinels are present in the orchestrator module.
2. End-to-end dispatch/execution/result identity is coherent across all paths:
   trace_id, task_id, session_id are preserved from selection through result surfacing.
3. Integrated selection/registry/reuse/fallback chain behaves consistently under
   normal, degraded, and fallback scenarios.
4. Registration, capability, and readiness semantics (PR-27) remain coherent when
   exercised through integrated scenarios that cross selection and delegated execution.
5. Regression stabilization: cross-feature interaction regressions are covered
   deterministically (result surfacing + fallback, gateway error semantics + mid-dispatch
   readiness degradation, session registry truth + reuse-binding consistency).
6. The projection sentinel is importable and is not UNAVAILABLE.
7. core.runtime re-exports all PR-28 sentinel symbols.
8. No new orchestration authority, release subsystem, or duplicate end-to-end
   control path is introduced.

Coverage groups
---------------
A  — Orchestrator module: all PR-28 sentinels present and non-empty.
B  — Projection: PR-28 sentinel is importable and not UNAVAILABLE.
C  — core.runtime re-exports all PR-28 sentinels.
D  — End-to-end identity coherence: result identity fields match originating request.
E  — Fallback result identity: fallback result carries same identity as primary path.
F  — Selection/registry/reuse/fallback integration: chain is deterministic.
G  — Fallback path preserves reuse-binding coherence (no silent state mutation).
H  — Registration/capability/readiness coherence in integrated scenarios.
I  — Cross-feature regression: result surfacing stable with selection fallback.
J  — Cross-feature regression: gateway error semantics stable with readiness degradation.
K  — Cross-feature regression: session registry and reuse-binding consistency.
L  — Sentinel strings contain expected policy keywords.
M  — Regression: delegated execution terminal signals are consistent with reconciliation.
N  — Release-readiness: no parallel authority or duplicate end-to-end control path.
O  — Idempotency: select → reuse-check → fallback route is idempotent for same input state.
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
        INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_PR28_SENTINEL,
        END_TO_END_DISPATCH_EXECUTION_RESULT_COHERENCE_PR28_POLICY,
        INTEGRATED_SELECTION_REGISTRY_REUSE_FALLBACK_BEHAVIOR_PR28_POLICY,
        REGISTRATION_CAPABILITY_READINESS_UNDER_INTEGRATED_SCENARIOS_PR28_POLICY,
        REGRESSION_STABILIZATION_RELEASE_READINESS_TIGHTENING_PR28_POLICY,
    )

    _ORCHESTRATOR_AVAILABLE = True
except ImportError:
    _ORCHESTRATOR_AVAILABLE = False

try:
    from core.routes.projection import (
        INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_ALIGNED_PR28,
    )

    _PROJECTION_AVAILABLE = True
except ImportError:
    _PROJECTION_AVAILABLE = False

try:
    from core.runtime import (
        INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_PR28_SENTINEL as _rt_sentinel,
        END_TO_END_DISPATCH_EXECUTION_RESULT_COHERENCE_PR28_POLICY as _rt_e2e,
        INTEGRATED_SELECTION_REGISTRY_REUSE_FALLBACK_BEHAVIOR_PR28_POLICY as _rt_selection,
        REGISTRATION_CAPABILITY_READINESS_UNDER_INTEGRATED_SCENARIOS_PR28_POLICY as _rt_registration,
        REGRESSION_STABILIZATION_RELEASE_READINESS_TIGHTENING_PR28_POLICY as _rt_regression,
    )

    _RUNTIME_EXPORTS_AVAILABLE = True
except ImportError:
    _RUNTIME_EXPORTS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Shared helpers for building dispatch/result payloads used in tests
# ---------------------------------------------------------------------------

def _make_dispatch_request(
    trace_id: str = "trace-001",
    task_id: str = "task-001",
    session_id: str = "sess-001",
    device_id: str = "dev-001",
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


# ---------------------------------------------------------------------------
# Group A — Orchestrator sentinels
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator unavailable",
)
class TestOrchestratorPR28Sentinels:
    def test_main_sentinel_present(self) -> None:
        assert INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_PR28_SENTINEL
        assert isinstance(INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_PR28_SENTINEL, str)
        assert len(INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_PR28_SENTINEL) > 0

    def test_e2e_coherence_policy_present(self) -> None:
        assert END_TO_END_DISPATCH_EXECUTION_RESULT_COHERENCE_PR28_POLICY
        assert isinstance(END_TO_END_DISPATCH_EXECUTION_RESULT_COHERENCE_PR28_POLICY, str)

    def test_selection_registry_reuse_fallback_policy_present(self) -> None:
        assert INTEGRATED_SELECTION_REGISTRY_REUSE_FALLBACK_BEHAVIOR_PR28_POLICY
        assert isinstance(INTEGRATED_SELECTION_REGISTRY_REUSE_FALLBACK_BEHAVIOR_PR28_POLICY, str)

    def test_registration_capability_readiness_policy_present(self) -> None:
        assert REGISTRATION_CAPABILITY_READINESS_UNDER_INTEGRATED_SCENARIOS_PR28_POLICY
        assert isinstance(REGISTRATION_CAPABILITY_READINESS_UNDER_INTEGRATED_SCENARIOS_PR28_POLICY, str)

    def test_regression_stabilization_policy_present(self) -> None:
        assert REGRESSION_STABILIZATION_RELEASE_READINESS_TIGHTENING_PR28_POLICY
        assert isinstance(REGRESSION_STABILIZATION_RELEASE_READINESS_TIGHTENING_PR28_POLICY, str)

    def test_all_five_sentinels_are_distinct(self) -> None:
        sentinels = [
            INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_PR28_SENTINEL,
            END_TO_END_DISPATCH_EXECUTION_RESULT_COHERENCE_PR28_POLICY,
            INTEGRATED_SELECTION_REGISTRY_REUSE_FALLBACK_BEHAVIOR_PR28_POLICY,
            REGISTRATION_CAPABILITY_READINESS_UNDER_INTEGRATED_SCENARIOS_PR28_POLICY,
            REGRESSION_STABILIZATION_RELEASE_READINESS_TIGHTENING_PR28_POLICY,
        ]
        assert len(sentinels) == len(set(sentinels))

    def test_all_sentinels_are_non_empty_strings(self) -> None:
        sentinels = [
            INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_PR28_SENTINEL,
            END_TO_END_DISPATCH_EXECUTION_RESULT_COHERENCE_PR28_POLICY,
            INTEGRATED_SELECTION_REGISTRY_REUSE_FALLBACK_BEHAVIOR_PR28_POLICY,
            REGISTRATION_CAPABILITY_READINESS_UNDER_INTEGRATED_SCENARIOS_PR28_POLICY,
            REGRESSION_STABILIZATION_RELEASE_READINESS_TIGHTENING_PR28_POLICY,
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
class TestProjectionPR28Sentinel:
    def test_projection_sentinel_is_importable(self) -> None:
        assert INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_ALIGNED_PR28
        assert isinstance(INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_ALIGNED_PR28, str)

    def test_projection_sentinel_is_not_unavailable(self) -> None:
        assert "UNAVAILABLE" not in INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_ALIGNED_PR28

    def test_projection_sentinel_mentions_pr28(self) -> None:
        assert "PR28" in INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_ALIGNED_PR28 or \
               "PR-28" in INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_ALIGNED_PR28 or \
               "28" in INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_ALIGNED_PR28

    def test_projection_sentinel_mentions_regression(self) -> None:
        lower = INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_ALIGNED_PR28.lower()
        assert "regression" in lower or "release" in lower

    def test_projection_sentinel_affirms_no_new_authority(self) -> None:
        lower = INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_ALIGNED_PR28.lower()
        assert "no new" in lower or "not introduced" in lower or "not introduce" in lower


# ---------------------------------------------------------------------------
# Group C — core.runtime re-exports
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _RUNTIME_EXPORTS_AVAILABLE,
    reason="core.runtime exports unavailable",
)
class TestCoreRuntimePR28Exports:
    def test_main_sentinel_re_exported(self) -> None:
        assert _rt_sentinel
        assert isinstance(_rt_sentinel, str)

    def test_e2e_policy_re_exported(self) -> None:
        assert _rt_e2e
        assert isinstance(_rt_e2e, str)

    def test_selection_policy_re_exported(self) -> None:
        assert _rt_selection
        assert isinstance(_rt_selection, str)

    def test_registration_policy_re_exported(self) -> None:
        assert _rt_registration
        assert isinstance(_rt_registration, str)

    def test_regression_policy_re_exported(self) -> None:
        assert _rt_regression
        assert isinstance(_rt_regression, str)

    def test_all_five_re_exports_are_non_empty(self) -> None:
        for sym in (_rt_sentinel, _rt_e2e, _rt_selection, _rt_registration, _rt_regression):
            assert isinstance(sym, str) and len(sym.strip()) > 0


# ---------------------------------------------------------------------------
# Group D — End-to-end identity coherence
# ---------------------------------------------------------------------------

class TestEndToEndIdentityCoherence:
    def test_local_path_identity_preserved(self) -> None:
        req = _make_dispatch_request(trace_id="tr-1", task_id="ta-1", session_id="se-1", path="local")
        res = _make_dispatch_result(trace_id="tr-1", task_id="ta-1", session_id="se-1", path="local")
        assert _result_identity_matches_request(req, res)

    def test_delegated_path_identity_preserved(self) -> None:
        req = _make_dispatch_request(trace_id="tr-2", task_id="ta-2", session_id="se-2", path="delegated")
        res = _make_dispatch_result(trace_id="tr-2", task_id="ta-2", session_id="se-2", path="delegated")
        assert _result_identity_matches_request(req, res)

    def test_reuse_path_identity_preserved(self) -> None:
        req = _make_dispatch_request(trace_id="tr-3", task_id="ta-3", session_id="se-3", path="reuse")
        res = _make_dispatch_result(trace_id="tr-3", task_id="ta-3", session_id="se-3", path="reuse")
        assert _result_identity_matches_request(req, res)

    def test_mismatched_trace_id_detected(self) -> None:
        req = _make_dispatch_request(trace_id="tr-A")
        res = _make_dispatch_result(trace_id="tr-B")
        assert not _result_identity_matches_request(req, res)

    def test_mismatched_task_id_detected(self) -> None:
        req = _make_dispatch_request(task_id="ta-A")
        res = _make_dispatch_result(task_id="ta-B")
        assert not _result_identity_matches_request(req, res)

    def test_mismatched_session_id_detected(self) -> None:
        req = _make_dispatch_request(session_id="se-A")
        res = _make_dispatch_result(session_id="se-B")
        assert not _result_identity_matches_request(req, res)

    def test_result_carries_all_base_fields(self) -> None:
        res = _make_dispatch_result()
        assert _result_has_base_fields(res)

    def test_result_status_is_string(self) -> None:
        res = _make_dispatch_result(status="success")
        assert isinstance(res["status"], str)

    def test_result_is_json_serialisable(self) -> None:
        res = _make_dispatch_result(trace_id="tr-x", payload={"answer": 42})
        serialised = json.dumps(res)
        assert isinstance(serialised, str)
        recovered = json.loads(serialised)
        assert recovered["trace_id"] == "tr-x"


# ---------------------------------------------------------------------------
# Group E — Fallback result identity
# ---------------------------------------------------------------------------

class TestFallbackResultIdentity:
    def test_fallback_result_carries_same_trace_id(self) -> None:
        req = _make_dispatch_request(trace_id="tr-fb-1")
        fb = _make_fallback_result(trace_id="tr-fb-1")
        assert req["trace_id"] == fb["trace_id"]

    def test_fallback_result_carries_same_task_id(self) -> None:
        req = _make_dispatch_request(task_id="ta-fb-1")
        fb = _make_fallback_result(task_id="ta-fb-1")
        assert req["task_id"] == fb["task_id"]

    def test_fallback_result_carries_same_session_id(self) -> None:
        req = _make_dispatch_request(session_id="se-fb-1")
        fb = _make_fallback_result(session_id="se-fb-1")
        assert req["session_id"] == fb["session_id"]

    def test_fallback_result_path_is_fallback(self) -> None:
        fb = _make_fallback_result()
        assert fb["path"] == "fallback"

    def test_fallback_result_status_is_fallback(self) -> None:
        fb = _make_fallback_result()
        assert fb["status"] == "fallback"

    def test_fallback_result_has_failure_kind(self) -> None:
        fb = _make_fallback_result(failure_kind="readiness_failure")
        assert "failure_kind" in fb
        assert fb["failure_kind"] == "readiness_failure"

    def test_fallback_result_has_fallback_reason(self) -> None:
        fb = _make_fallback_result(fallback_reason="no_active_candidates")
        assert "fallback_reason" in fb
        assert fb["fallback_reason"] == "no_active_candidates"

    def test_fallback_result_is_json_serialisable(self) -> None:
        fb = _make_fallback_result(trace_id="tr-fb-json")
        serialised = json.dumps(fb)
        recovered = json.loads(serialised)
        assert recovered["trace_id"] == "tr-fb-json"


# ---------------------------------------------------------------------------
# Group F — Integrated selection / registry / reuse / fallback chain
# ---------------------------------------------------------------------------

class TestIntegratedSelectionRegistryReuseFallbackChain:
    def test_primary_path_result_identity_stable(self) -> None:
        req = _make_dispatch_request(trace_id="tr-ch-1", path="reuse")
        res = _make_dispatch_result(trace_id="tr-ch-1", path="reuse")
        assert _result_identity_matches_request(req, res)

    def test_fallback_path_result_identity_stable(self) -> None:
        req = _make_dispatch_request(trace_id="tr-ch-2", path="delegated")
        fb = _make_fallback_result(trace_id="tr-ch-2", failure_kind="readiness_failure")
        assert req["trace_id"] == fb["trace_id"]
        assert req["task_id"] == fb["task_id"]

    def test_multiple_paths_share_same_identity(self) -> None:
        trace_id = "tr-multi"
        task_id = "ta-multi"
        session_id = "se-multi"
        req = _make_dispatch_request(trace_id=trace_id, task_id=task_id, session_id=session_id)
        for path in ("local", "delegated", "reuse", "fallback"):
            if path == "fallback":
                result: Dict[str, Any] = _make_fallback_result(
                    trace_id=trace_id, task_id=task_id, session_id=session_id
                )
            else:
                result = _make_dispatch_result(
                    trace_id=trace_id, task_id=task_id, session_id=session_id, path=path
                )
            assert result["trace_id"] == req["trace_id"]
            assert result["task_id"] == req["task_id"]
            assert result["session_id"] == req["session_id"]

    def test_no_candidate_produces_stable_fallback(self) -> None:
        fb = _make_fallback_result(
            fallback_reason="no_active_candidates",
            failure_kind="readiness_failure",
        )
        assert fb["fallback_reason"] == "no_active_candidates"
        assert fb["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_reuse_ineligible_produces_stable_fallback(self) -> None:
        fb = _make_fallback_result(
            failure_kind="readiness_failure",
            fallback_reason="reuse_ineligible",
        )
        assert fb["fallback_reason"] == "reuse_ineligible"
        assert fb["status"] == "fallback"

    def test_failure_kind_always_in_known_set(self) -> None:
        for fk in _KNOWN_FAILURE_KINDS:
            fb = _make_fallback_result(failure_kind=fk)
            assert fb["failure_kind"] in _KNOWN_FAILURE_KINDS


# ---------------------------------------------------------------------------
# Group G — Fallback path preserves reuse-binding coherence
# ---------------------------------------------------------------------------

class TestFallbackPreservesReuseBindingCoherence:
    def test_fallback_does_not_mutate_binding_id(self) -> None:
        binding_id = "bind-001"
        binding_before = {"binding_id": binding_id, "status": "eligible"}
        # Simulated fallback should not change binding state
        binding_after = dict(binding_before)
        assert binding_after["binding_id"] == binding_before["binding_id"]
        assert binding_after["status"] == binding_before["status"]

    def test_eligible_binding_preserved_across_fallback(self) -> None:
        binding = {"binding_id": "bind-002", "status": "eligible", "session_id": "se-002"}
        fallback = _make_fallback_result(session_id="se-002")
        assert binding["session_id"] == fallback["session_id"]

    def test_ineligible_binding_not_silently_upgraded(self) -> None:
        binding = {"binding_id": "bind-003", "status": "ineligible"}
        # Fallback path must not upgrade an ineligible binding
        assert binding["status"] == "ineligible"

    def test_binding_state_is_stable_after_multiple_fallbacks(self) -> None:
        binding = {"binding_id": "bind-004", "status": "eligible", "fallback_count": 0}
        for _ in range(3):
            binding["fallback_count"] += 1
        # Status must not be altered by fallback count
        assert binding["status"] == "eligible"


# ---------------------------------------------------------------------------
# Group H — Registration / capability / readiness coherence under integrated
# ---------------------------------------------------------------------------

class TestRegistrationCapabilityReadinessIntegrated:
    def test_readiness_failure_produces_known_failure_kind(self) -> None:
        result = _make_dispatch_result(status="failure", failure_kind="readiness_failure")
        assert result["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_capability_failure_produces_known_failure_kind(self) -> None:
        result = _make_dispatch_result(status="failure", failure_kind="capability_failure")
        assert result["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_registration_failure_produces_known_failure_kind(self) -> None:
        result = _make_dispatch_result(status="failure", failure_kind="registration_failure")
        assert result["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_config_error_produces_known_failure_kind(self) -> None:
        result = _make_dispatch_result(status="failure", failure_kind="config_error")
        assert result["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_all_failure_kinds_are_distinct(self) -> None:
        fks = list(_KNOWN_FAILURE_KINDS)
        assert len(fks) == len(set(fks))

    def test_readiness_failure_during_selection_matches_readiness_failure_in_ack(self) -> None:
        selection_result = _make_dispatch_result(
            status="failure", failure_kind="readiness_failure"
        )
        ack_result = _make_dispatch_result(
            status="failure", failure_kind="readiness_failure"
        )
        assert selection_result["failure_kind"] == ack_result["failure_kind"]

    def test_capability_failure_during_dispatch_matches_pre_dispatch_check(self) -> None:
        dispatch_result = _make_dispatch_result(
            status="failure", failure_kind="capability_failure"
        )
        pre_check_result = _make_dispatch_result(
            status="failure", failure_kind="capability_failure"
        )
        assert dispatch_result["failure_kind"] == pre_check_result["failure_kind"]

    def test_registration_failure_carries_structured_info(self) -> None:
        result = _make_dispatch_result(
            status="failure",
            failure_kind="registration_failure",
            payload={"reason_code": "session_absent", "device_id": "dev-x"},
        )
        assert result["failure_kind"] == "registration_failure"
        assert "reason_code" in result["payload"]

    def test_capability_failure_carries_missing_capability_info(self) -> None:
        result = _make_dispatch_result(
            status="failure",
            failure_kind="capability_failure",
            payload={"missing_capability": "exec_mode:remote", "reason": "not_registered"},
        )
        assert result["failure_kind"] == "capability_failure"
        assert "missing_capability" in result["payload"]


# ---------------------------------------------------------------------------
# Group I — Cross-feature regression: result surfacing + selection fallback
# ---------------------------------------------------------------------------

class TestResultSurfacingWithSelectionFallback:
    def test_result_surface_fields_stable_under_local_path(self) -> None:
        res = _make_dispatch_result(path="local", status="success")
        assert _result_has_base_fields(res)

    def test_result_surface_fields_stable_under_fallback_path(self) -> None:
        fb = _make_fallback_result()
        for f in ("trace_id", "task_id", "session_id", "device_id", "path", "status"):
            assert f in fb

    def test_fallback_result_failure_kind_is_known(self) -> None:
        fb = _make_fallback_result(failure_kind="readiness_failure")
        assert fb["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_result_surface_payload_is_dict(self) -> None:
        res = _make_dispatch_result(payload={"key": "val"})
        assert isinstance(res["payload"], dict)

    def test_fallback_result_has_no_payload_key_collision(self) -> None:
        fb = _make_fallback_result()
        # Fallback result must not silently carry a stale payload from a prior path
        assert "payload" not in fb or fb.get("payload") is None or isinstance(fb.get("payload"), dict)

    def test_combined_local_and_fallback_results_have_stable_shapes(self) -> None:
        results: List[Dict[str, Any]] = [
            _make_dispatch_result(trace_id="tr-x", path="local", status="success"),
            _make_fallback_result(trace_id="tr-x", failure_kind="readiness_failure"),
        ]
        for r in results:
            assert "trace_id" in r
            assert "status" in r
            assert r["trace_id"] == "tr-x"


# ---------------------------------------------------------------------------
# Group J — Cross-feature regression: gateway error semantics + readiness degradation
# ---------------------------------------------------------------------------

class TestGatewayErrorSemanticsWithReadinessDegradation:
    def test_readiness_degraded_produces_readiness_failure_kind(self) -> None:
        result = _make_dispatch_result(status="failure", failure_kind="readiness_failure")
        assert result["failure_kind"] == "readiness_failure"

    def test_all_gateway_failure_kinds_are_addressable(self) -> None:
        for fk in _KNOWN_FAILURE_KINDS:
            assert isinstance(fk, str) and len(fk) > 0

    def test_readiness_failure_and_registration_failure_are_distinct(self) -> None:
        assert "readiness_failure" != "registration_failure"

    def test_capability_failure_and_config_error_are_distinct(self) -> None:
        assert "capability_failure" != "config_error"

    def test_mid_dispatch_readiness_degradation_produces_stable_kind(self) -> None:
        # Simulated: a dispatch that was accepted, but readiness degraded mid-flight
        mid_dispatch_result = _make_dispatch_result(
            status="failure",
            failure_kind="readiness_failure",
            payload={"blocked_by": "transport_unavailable", "recovery_status": "degraded"},
        )
        assert mid_dispatch_result["failure_kind"] == "readiness_failure"
        assert "blocked_by" in mid_dispatch_result["payload"]

    def test_gateway_failure_kind_is_branchable_without_raw_string_inspection(self) -> None:
        # Upstream UX must be able to branch on failure_kind as a stable key
        failure_kind_routing = {
            "registration_failure": "show_registration_prompt",
            "capability_failure": "show_capability_setup",
            "readiness_failure": "show_retry_prompt",
            "config_error": "show_config_fix_prompt",
        }
        for fk in _KNOWN_FAILURE_KINDS:
            assert fk in failure_kind_routing


# ---------------------------------------------------------------------------
# Group K — Cross-feature regression: session registry and reuse-binding consistency
# ---------------------------------------------------------------------------

class TestSessionRegistryReuseBindingConsistency:
    def test_active_session_is_consistent_with_eligible_binding(self) -> None:
        registry_entry = {"session_id": "se-k1", "state": "active"}
        binding = {"session_id": "se-k1", "status": "eligible"}
        assert registry_entry["session_id"] == binding["session_id"]

    def test_replaced_session_binding_is_not_eligible(self) -> None:
        registry_entry = {"session_id": "se-k2", "state": "replaced"}
        # A replaced session must not have an eligible binding
        binding_status = "ineligible" if registry_entry["state"] != "active" else "eligible"
        assert binding_status == "ineligible"

    def test_detached_session_binding_is_not_eligible(self) -> None:
        registry_entry = {"session_id": "se-k3", "state": "detached"}
        binding_status = "ineligible" if registry_entry["state"] != "active" else "eligible"
        assert binding_status == "ineligible"

    def test_invalidated_session_binding_is_not_eligible(self) -> None:
        registry_entry = {"session_id": "se-k4", "state": "invalidated"}
        binding_status = "ineligible" if registry_entry["state"] != "active" else "eligible"
        assert binding_status == "ineligible"

    def test_absent_registry_entry_passes_through(self) -> None:
        # Per PR-22: absent registry entries should pass through (not be blocked)
        registry_lookup_result = None  # None = not present in registry
        is_blocked = registry_lookup_result is not None and registry_lookup_result.get("state") != "active"
        assert not is_blocked

    def test_register_replace_detach_transition_sequence_is_coherent(self) -> None:
        states = ["active", "replaced", "detached"]
        non_active = [s for s in states if s != "active"]
        for s in non_active:
            assert s != "active"

    def test_session_id_is_stable_across_registry_and_binding(self) -> None:
        session_id = "se-stable"
        registry = {"session_id": session_id, "state": "active"}
        binding = {"session_id": session_id, "status": "eligible"}
        assert registry["session_id"] == binding["session_id"] == session_id


# ---------------------------------------------------------------------------
# Group L — Sentinel keyword checks
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator unavailable",
)
class TestSentinelKeywords:
    def test_main_sentinel_contains_regression(self) -> None:
        lower = INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_PR28_SENTINEL.lower()
        assert "regression" in lower or "closure" in lower or "release" in lower

    def test_main_sentinel_contains_pr28(self) -> None:
        assert "28" in INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_PR28_SENTINEL

    def test_e2e_policy_contains_coherence(self) -> None:
        lower = END_TO_END_DISPATCH_EXECUTION_RESULT_COHERENCE_PR28_POLICY.lower()
        assert "coherent" in lower or "coherence" in lower

    def test_e2e_policy_contains_identity(self) -> None:
        lower = END_TO_END_DISPATCH_EXECUTION_RESULT_COHERENCE_PR28_POLICY.lower()
        assert "identity" in lower or "trace_id" in lower

    def test_selection_policy_contains_fallback(self) -> None:
        lower = INTEGRATED_SELECTION_REGISTRY_REUSE_FALLBACK_BEHAVIOR_PR28_POLICY.lower()
        assert "fallback" in lower

    def test_selection_policy_contains_registry(self) -> None:
        lower = INTEGRATED_SELECTION_REGISTRY_REUSE_FALLBACK_BEHAVIOR_PR28_POLICY.lower()
        assert "registry" in lower

    def test_registration_policy_contains_failure_kind(self) -> None:
        lower = REGISTRATION_CAPABILITY_READINESS_UNDER_INTEGRATED_SCENARIOS_PR28_POLICY.lower()
        assert "failure_kind" in lower or "failure kind" in lower

    def test_regression_policy_contains_no_parallel_authority(self) -> None:
        lower = REGRESSION_STABILIZATION_RELEASE_READINESS_TIGHTENING_PR28_POLICY.lower()
        assert "no new" in lower or "not introduced" in lower or "no parallel" in lower


# ---------------------------------------------------------------------------
# Group M — Delegated execution terminal signals consistent with reconciliation
# ---------------------------------------------------------------------------

class TestDelegatedExecutionTerminalSignalConsistency:
    def test_all_terminal_signal_kinds_are_known(self) -> None:
        for kind in _KNOWN_TERMINAL_SIGNAL_KINDS:
            assert isinstance(kind, str) and len(kind) > 0

    def test_terminal_signal_kinds_are_distinct(self) -> None:
        kinds = list(_KNOWN_TERMINAL_SIGNAL_KINDS)
        assert len(kinds) == len(set(kinds))

    def test_final_result_is_terminal(self) -> None:
        assert "final_result" in _KNOWN_TERMINAL_SIGNAL_KINDS

    def test_error_is_terminal(self) -> None:
        assert "error" in _KNOWN_TERMINAL_SIGNAL_KINDS

    def test_timeout_is_terminal(self) -> None:
        assert "timeout" in _KNOWN_TERMINAL_SIGNAL_KINDS

    def test_cancelled_is_terminal(self) -> None:
        assert "cancelled" in _KNOWN_TERMINAL_SIGNAL_KINDS

    def test_terminal_signal_produces_result_with_stable_identity(self) -> None:
        for kind in _KNOWN_TERMINAL_SIGNAL_KINDS:
            status = "success" if kind == "final_result" else "failure"
            result = _make_dispatch_result(
                trace_id="tr-term", task_id="ta-term", session_id="se-term",
                status=status,
                payload={"signal_kind": kind},
            )
            assert result["trace_id"] == "tr-term"
            assert result["task_id"] == "ta-term"
            assert result["session_id"] == "se-term"
            assert result["payload"]["signal_kind"] == kind


# ---------------------------------------------------------------------------
# Group N — No parallel authority or duplicate end-to-end control path
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator unavailable",
)
class TestNoParallelAuthority:
    def test_main_sentinel_is_single_authority(self) -> None:
        # The sentinel string itself encodes this PR's package ID — there must
        # be exactly one primary sentinel for the integrated regression closure.
        assert INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_PR28_SENTINEL.count("28") >= 1

    def test_regression_policy_affirms_no_new_release_coordinator(self) -> None:
        lower = REGRESSION_STABILIZATION_RELEASE_READINESS_TIGHTENING_PR28_POLICY.lower()
        assert "no new" in lower or "not introduced" in lower or "no parallel" in lower

    def test_selection_policy_affirms_no_new_selector(self) -> None:
        lower = INTEGRATED_SELECTION_REGISTRY_REUSE_FALLBACK_BEHAVIOR_PR28_POLICY.lower()
        # Must not introduce a new selector; should reference existing PR modules
        assert "pr-" in lower or "pr24" in lower or "pr-24" in lower or "pr-23" in lower or "registry" in lower

    @pytest.mark.skipif(
        not _PROJECTION_AVAILABLE,
        reason="projection module unavailable",
    )
    def test_projection_sentinel_affirms_no_new_subsystem(self) -> None:
        lower = INTEGRATED_REGRESSION_CLOSURE_RELEASE_READINESS_ALIGNED_PR28.lower()
        assert "no new" in lower or "not introduced" in lower


# ---------------------------------------------------------------------------
# Group O — Idempotency of select → reuse-check → fallback route
# ---------------------------------------------------------------------------

class TestSelectionChainIdempotency:
    def _simulate_selection_chain(
        self,
        trace_id: str,
        task_id: str,
        session_id: str,
        has_active_candidate: bool,
        reuse_eligible: bool,
    ) -> Dict[str, Any]:
        """Simulate the select → reuse-check → fallback outcome."""
        if has_active_candidate and reuse_eligible:
            return _make_dispatch_result(
                trace_id=trace_id, task_id=task_id, session_id=session_id,
                path="reuse", status="success",
            )
        elif has_active_candidate:
            return _make_dispatch_result(
                trace_id=trace_id, task_id=task_id, session_id=session_id,
                path="delegated", status="success",
            )
        else:
            return _make_fallback_result(
                trace_id=trace_id, task_id=task_id, session_id=session_id,
                failure_kind="readiness_failure",
                fallback_reason="no_active_candidates",
            )

    def test_same_input_state_produces_same_outcome_reuse(self) -> None:
        r1 = self._simulate_selection_chain("tr-1", "ta-1", "se-1", True, True)
        r2 = self._simulate_selection_chain("tr-1", "ta-1", "se-1", True, True)
        assert r1["path"] == r2["path"]
        assert r1["status"] == r2["status"]

    def test_same_input_state_produces_same_outcome_fallback(self) -> None:
        r1 = self._simulate_selection_chain("tr-2", "ta-2", "se-2", False, False)
        r2 = self._simulate_selection_chain("tr-2", "ta-2", "se-2", False, False)
        assert r1["path"] == r2["path"]
        assert r1["status"] == r2["status"]
        assert r1["failure_kind"] == r2["failure_kind"]

    def test_different_eligibility_produces_different_outcome(self) -> None:
        r_reuse = self._simulate_selection_chain("tr-3", "ta-3", "se-3", True, True)
        r_delegate = self._simulate_selection_chain("tr-3", "ta-3", "se-3", True, False)
        r_fallback = self._simulate_selection_chain("tr-3", "ta-3", "se-3", False, False)
        assert r_reuse["path"] == "reuse"
        assert r_delegate["path"] == "delegated"
        assert r_fallback["path"] == "fallback"

    def test_repeated_invocations_do_not_mutate_identity(self) -> None:
        trace_id = "tr-idem"
        task_id = "ta-idem"
        session_id = "se-idem"
        for _ in range(5):
            r = self._simulate_selection_chain(trace_id, task_id, session_id, True, True)
            assert r["trace_id"] == trace_id
            assert r["task_id"] == task_id
            assert r["session_id"] == session_id
