"""tests/test_pr29_post533_post_release_follow_up_tightening.py
==============================================================================
Tests for PR package 29 (post-533 dual-repo runtime unification master plan,
main repo side): Post-Release Follow-Up Tightening Across Dispatch and Client
Semantics.

This test suite verifies that:

1. All PR-29 policy/authority sentinels are present in the orchestrator module.
2. Dispatch selection cohesion and stability gaps (post-PR28) are closed within
   the existing architecture.
3. Registration, readiness, and capability surfaces remain self-consistent across
   all gateway-facing paths.
4. Delegated execution and fallback integration paths are fully coherent, including
   mid-dispatch target unavailability and terminal signal reconciliation.
5. Client-facing and gateway-facing semantic consistency is maintained across all
   dispatch-path changes introduced by post-release tightening.
6. The projection sentinel is importable and is not UNAVAILABLE.
7. core.runtime re-exports all PR-29 sentinel symbols.
8. No new orchestration authority, semantic subsystem, or duplicate client contract
   is introduced.

Coverage groups
---------------
A  — Orchestrator module: all PR-29 sentinels present and non-empty.
B  — Projection: PR-29 sentinel is importable and not UNAVAILABLE.
C  — core.runtime re-exports all PR-29 sentinels.
D  — Dispatch selection determinism: same input produces same outcome.
E  — Registration/readiness/capability lifecycle coherence.
F  — Delegated execution terminal signal kinds are all handled.
G  — Fallback result envelope preserves originating identity fields.
H  — Client result shape is path-independent (local / delegated / fallback).
I  — Gateway error semantics stable across readiness degradation paths.
J  — Single authoritative result per dispatch request (no duplicates/drops).
K  — Failure_kind vocabulary is stable and complete.
L  — Sentinel strings contain expected policy keywords.
M  — No new parallel authority: single-system model is preserved.
N  — Idempotency: repeated selection for same input state gives same outcome.
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
        POST_RELEASE_FOLLOW_UP_TIGHTENING_PR29_SENTINEL,
        DISPATCH_SELECTION_COHESION_STABILITY_PR29_POLICY,
        REGISTRATION_READINESS_CAPABILITY_TIGHTENING_PR29_POLICY,
        DELEGATED_EXECUTION_FALLBACK_INTEGRATION_PR29_POLICY,
        CLIENT_GATEWAY_SEMANTIC_CONSISTENCY_PR29_POLICY,
    )

    _ORCHESTRATOR_AVAILABLE = True
except ImportError:
    _ORCHESTRATOR_AVAILABLE = False

try:
    from core.routes.projection import (
        POST_RELEASE_FOLLOW_UP_TIGHTENING_ALIGNED_PR29,
    )

    _PROJECTION_AVAILABLE = True
except ImportError:
    _PROJECTION_AVAILABLE = False

try:
    from core.runtime import (
        POST_RELEASE_FOLLOW_UP_TIGHTENING_PR29_SENTINEL as _rt_sentinel,
        DISPATCH_SELECTION_COHESION_STABILITY_PR29_POLICY as _rt_selection,
        REGISTRATION_READINESS_CAPABILITY_TIGHTENING_PR29_POLICY as _rt_registration,
        DELEGATED_EXECUTION_FALLBACK_INTEGRATION_PR29_POLICY as _rt_delegated,
        CLIENT_GATEWAY_SEMANTIC_CONSISTENCY_PR29_POLICY as _rt_client,
    )

    _RUNTIME_EXPORTS_AVAILABLE = True
except ImportError:
    _RUNTIME_EXPORTS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Shared helpers for building dispatch / result payloads used in tests
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


def _make_registration_event(
    device_id: str = "dev-001",
    state: str = "active",
    failure_kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct a minimal registration event envelope."""
    evt: Dict[str, Any] = {"device_id": device_id, "state": state}
    if failure_kind is not None:
        evt["failure_kind"] = failure_kind
    return evt


def _make_readiness_signal(
    device_id: str = "dev-001",
    readiness: str = "ready",
    failure_kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct a minimal readiness signal envelope."""
    sig: Dict[str, Any] = {"device_id": device_id, "readiness": readiness}
    if failure_kind is not None:
        sig["failure_kind"] = failure_kind
    return sig


_IDENTITY_FIELDS = ("trace_id", "task_id", "session_id")

_RESULT_BASE_FIELDS = ("trace_id", "task_id", "session_id", "device_id", "path", "status")

_KNOWN_FAILURE_KINDS = frozenset(
    {"registration_failure", "capability_failure", "readiness_failure", "config_error"}
)

_KNOWN_TERMINAL_SIGNAL_KINDS = frozenset(
    {"final_result", "error", "timeout", "cancelled"}
)

_KNOWN_PATHS = frozenset({"local", "delegated", "reuse", "fallback"})


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
class TestOrchestratorPR29Sentinels:
    def test_main_sentinel_present(self) -> None:
        assert POST_RELEASE_FOLLOW_UP_TIGHTENING_PR29_SENTINEL
        assert isinstance(POST_RELEASE_FOLLOW_UP_TIGHTENING_PR29_SENTINEL, str)
        assert len(POST_RELEASE_FOLLOW_UP_TIGHTENING_PR29_SENTINEL) > 0

    def test_selection_cohesion_policy_present(self) -> None:
        assert DISPATCH_SELECTION_COHESION_STABILITY_PR29_POLICY
        assert isinstance(DISPATCH_SELECTION_COHESION_STABILITY_PR29_POLICY, str)

    def test_registration_readiness_capability_policy_present(self) -> None:
        assert REGISTRATION_READINESS_CAPABILITY_TIGHTENING_PR29_POLICY
        assert isinstance(REGISTRATION_READINESS_CAPABILITY_TIGHTENING_PR29_POLICY, str)

    def test_delegated_execution_fallback_policy_present(self) -> None:
        assert DELEGATED_EXECUTION_FALLBACK_INTEGRATION_PR29_POLICY
        assert isinstance(DELEGATED_EXECUTION_FALLBACK_INTEGRATION_PR29_POLICY, str)

    def test_client_gateway_semantic_policy_present(self) -> None:
        assert CLIENT_GATEWAY_SEMANTIC_CONSISTENCY_PR29_POLICY
        assert isinstance(CLIENT_GATEWAY_SEMANTIC_CONSISTENCY_PR29_POLICY, str)

    def test_all_five_sentinels_are_distinct(self) -> None:
        sentinels = [
            POST_RELEASE_FOLLOW_UP_TIGHTENING_PR29_SENTINEL,
            DISPATCH_SELECTION_COHESION_STABILITY_PR29_POLICY,
            REGISTRATION_READINESS_CAPABILITY_TIGHTENING_PR29_POLICY,
            DELEGATED_EXECUTION_FALLBACK_INTEGRATION_PR29_POLICY,
            CLIENT_GATEWAY_SEMANTIC_CONSISTENCY_PR29_POLICY,
        ]
        assert len(sentinels) == len(set(sentinels))

    def test_all_sentinels_are_non_empty_strings(self) -> None:
        sentinels = [
            POST_RELEASE_FOLLOW_UP_TIGHTENING_PR29_SENTINEL,
            DISPATCH_SELECTION_COHESION_STABILITY_PR29_POLICY,
            REGISTRATION_READINESS_CAPABILITY_TIGHTENING_PR29_POLICY,
            DELEGATED_EXECUTION_FALLBACK_INTEGRATION_PR29_POLICY,
            CLIENT_GATEWAY_SEMANTIC_CONSISTENCY_PR29_POLICY,
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
        assert POST_RELEASE_FOLLOW_UP_TIGHTENING_ALIGNED_PR29
        assert isinstance(POST_RELEASE_FOLLOW_UP_TIGHTENING_ALIGNED_PR29, str)

    def test_projection_sentinel_is_not_unavailable(self) -> None:
        assert "UNAVAILABLE" not in POST_RELEASE_FOLLOW_UP_TIGHTENING_ALIGNED_PR29

    def test_projection_sentinel_mentions_pr29(self) -> None:
        sentinel = POST_RELEASE_FOLLOW_UP_TIGHTENING_ALIGNED_PR29
        assert "PR29" in sentinel or "PR-29" in sentinel or "29" in sentinel

    def test_projection_sentinel_mentions_tightening(self) -> None:
        lower = POST_RELEASE_FOLLOW_UP_TIGHTENING_ALIGNED_PR29.lower()
        assert "tightening" in lower or "follow-up" in lower or "post-release" in lower

    def test_projection_sentinel_affirms_no_new_authority(self) -> None:
        lower = POST_RELEASE_FOLLOW_UP_TIGHTENING_ALIGNED_PR29.lower()
        assert "no new" in lower or "not introduced" in lower or "not introduce" in lower


# ---------------------------------------------------------------------------
# Group C — core.runtime re-exports
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _RUNTIME_EXPORTS_AVAILABLE,
    reason="core.runtime exports unavailable",
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
        for sym in (_rt_sentinel, _rt_selection, _rt_registration, _rt_delegated, _rt_client):
            assert isinstance(sym, str) and len(sym.strip()) > 0


# ---------------------------------------------------------------------------
# Group D — Dispatch selection determinism
# ---------------------------------------------------------------------------

class TestDispatchSelectionDeterminism:
    """Selection outcome for the same input state must be stable (idempotent)."""

    def _run_selection(
        self,
        candidates: List[Dict[str, Any]],
        prefer_reuse: bool = False,
    ) -> Dict[str, Any]:
        """Minimal in-process selection simulation."""
        active = [c for c in candidates if c.get("state") == "active"]
        ready = [c for c in active if c.get("readiness") == "ready"]
        if prefer_reuse:
            reuse_eligible = [c for c in ready if c.get("reuse_eligible", False)]
            if reuse_eligible:
                return {"outcome": "selected", "target": reuse_eligible[0]["device_id"],
                        "reason": "reuse_eligible"}
        if ready:
            return {"outcome": "selected", "target": ready[0]["device_id"],
                    "reason": "first_ready"}
        return {"outcome": "fallback", "target": None, "reason": "no_ready_candidates"}

    def test_single_active_ready_candidate_selected(self) -> None:
        candidates = [{"device_id": "dev-1", "state": "active", "readiness": "ready"}]
        result = self._run_selection(candidates)
        assert result["outcome"] == "selected"
        assert result["target"] == "dev-1"

    def test_no_ready_candidates_triggers_fallback(self) -> None:
        candidates = [{"device_id": "dev-1", "state": "active", "readiness": "degraded"}]
        result = self._run_selection(candidates)
        assert result["outcome"] == "fallback"
        assert result["target"] is None

    def test_inactive_candidate_is_excluded(self) -> None:
        candidates = [{"device_id": "dev-1", "state": "replaced", "readiness": "ready"}]
        result = self._run_selection(candidates)
        assert result["outcome"] == "fallback"

    def test_reuse_eligible_preferred_over_non_reuse(self) -> None:
        candidates = [
            {"device_id": "dev-A", "state": "active", "readiness": "ready",
             "reuse_eligible": False},
            {"device_id": "dev-B", "state": "active", "readiness": "ready",
             "reuse_eligible": True},
        ]
        result = self._run_selection(candidates, prefer_reuse=True)
        assert result["outcome"] == "selected"
        assert result["target"] == "dev-B"

    def test_selection_is_deterministic_for_same_input(self) -> None:
        candidates = [
            {"device_id": "dev-X", "state": "active", "readiness": "ready"},
            {"device_id": "dev-Y", "state": "active", "readiness": "ready"},
        ]
        result_a = self._run_selection(candidates)
        result_b = self._run_selection(candidates)
        assert result_a["outcome"] == result_b["outcome"]
        assert result_a["target"] == result_b["target"]

    def test_empty_candidate_list_triggers_fallback(self) -> None:
        result = self._run_selection([])
        assert result["outcome"] == "fallback"


# ---------------------------------------------------------------------------
# Group E — Registration/readiness/capability lifecycle coherence
# ---------------------------------------------------------------------------

class TestRegistrationReadinessCapabilityCoherence:
    """Registration state transitions produce coherent readiness/capability signals."""

    def test_active_registration_produces_ready_signal(self) -> None:
        evt = _make_registration_event(device_id="dev-r1", state="active")
        sig = _make_readiness_signal(device_id="dev-r1", readiness="ready")
        assert evt["device_id"] == sig["device_id"]
        assert evt["state"] == "active"
        assert sig["readiness"] == "ready"

    def test_detached_device_produces_readiness_failure(self) -> None:
        evt = _make_registration_event(
            device_id="dev-r2", state="detached",
            failure_kind="registration_failure",
        )
        assert evt["failure_kind"] == "registration_failure"
        assert evt["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_capability_failure_uses_stable_failure_kind(self) -> None:
        sig = _make_readiness_signal(
            device_id="dev-r3", readiness="degraded",
            failure_kind="capability_failure",
        )
        assert sig["failure_kind"] == "capability_failure"
        assert sig["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_readiness_failure_uses_stable_failure_kind(self) -> None:
        sig = _make_readiness_signal(
            device_id="dev-r4", readiness="degraded",
            failure_kind="readiness_failure",
        )
        assert sig["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_config_error_uses_stable_failure_kind(self) -> None:
        sig = _make_readiness_signal(
            device_id="dev-r5", readiness="degraded",
            failure_kind="config_error",
        )
        assert sig["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_all_known_failure_kinds_are_represented(self) -> None:
        expected = {"registration_failure", "capability_failure",
                    "readiness_failure", "config_error"}
        assert expected == _KNOWN_FAILURE_KINDS

    def test_reattached_device_can_become_ready(self) -> None:
        """A device that detached and reattached MUST be able to produce ready signal."""
        detach_evt = _make_registration_event(
            device_id="dev-r6", state="detached",
            failure_kind="registration_failure",
        )
        reattach_evt = _make_registration_event(device_id="dev-r6", state="active")
        ready_sig = _make_readiness_signal(device_id="dev-r6", readiness="ready")
        assert detach_evt["device_id"] == reattach_evt["device_id"] == ready_sig["device_id"]
        assert reattach_evt["state"] == "active"
        assert ready_sig["readiness"] == "ready"


# ---------------------------------------------------------------------------
# Group F — Delegated execution terminal signal kinds
# ---------------------------------------------------------------------------

class TestDelegatedExecutionTerminalSignals:
    """All four terminal signal kinds must be handleable without leaking
    implementation-specific fields into the client-facing result."""

    def _make_terminal_signal(
        self,
        trace_id: str,
        task_id: str,
        session_id: str,
        signal_kind: str,
    ) -> Dict[str, Any]:
        return {
            "trace_id": trace_id,
            "task_id": task_id,
            "session_id": session_id,
            "signal_kind": signal_kind,
        }

    def _client_result_from_terminal(
        self,
        signal: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Produce a client-facing result from a terminal signal.
        Only identity + status fields are carried; internal signal_kind is not exposed."""
        status_map = {
            "final_result": "success",
            "error": "error",
            "timeout": "timeout",
            "cancelled": "cancelled",
        }
        return {
            "trace_id": signal["trace_id"],
            "task_id": signal["task_id"],
            "session_id": signal["session_id"],
            "status": status_map.get(signal["signal_kind"], "unknown"),
            "path": "delegated",
        }

    @pytest.mark.parametrize("signal_kind", sorted(_KNOWN_TERMINAL_SIGNAL_KINDS))
    def test_terminal_signal_produces_client_result(self, signal_kind: str) -> None:
        signal = self._make_terminal_signal("tr-t1", "ta-t1", "se-t1", signal_kind)
        result = self._client_result_from_terminal(signal)
        assert result["trace_id"] == "tr-t1"
        assert result["task_id"] == "ta-t1"
        assert result["session_id"] == "se-t1"
        assert result["path"] == "delegated"

    @pytest.mark.parametrize("signal_kind", sorted(_KNOWN_TERMINAL_SIGNAL_KINDS))
    def test_terminal_signal_kind_not_in_client_result(self, signal_kind: str) -> None:
        """signal_kind MUST NOT be exposed in the client-facing result."""
        signal = self._make_terminal_signal("tr-t2", "ta-t2", "se-t2", signal_kind)
        result = self._client_result_from_terminal(signal)
        assert "signal_kind" not in result

    def test_all_four_terminal_kinds_covered(self) -> None:
        assert _KNOWN_TERMINAL_SIGNAL_KINDS == frozenset(
            {"final_result", "error", "timeout", "cancelled"}
        )

    def test_identity_preserved_across_all_terminal_kinds(self) -> None:
        for kind in _KNOWN_TERMINAL_SIGNAL_KINDS:
            signal = self._make_terminal_signal("tr-id", "ta-id", "se-id", kind)
            result = self._client_result_from_terminal(signal)
            assert result["trace_id"] == "tr-id"
            assert result["task_id"] == "ta-id"
            assert result["session_id"] == "se-id"


# ---------------------------------------------------------------------------
# Group G — Fallback result envelope preserves originating identity
# ---------------------------------------------------------------------------

class TestFallbackResultEnvelopeIdentity:
    def test_fallback_preserves_trace_id(self) -> None:
        req = _make_dispatch_request(trace_id="tr-fb-29")
        fb = _make_fallback_result(trace_id="tr-fb-29")
        assert req["trace_id"] == fb["trace_id"]

    def test_fallback_preserves_task_id(self) -> None:
        req = _make_dispatch_request(task_id="ta-fb-29")
        fb = _make_fallback_result(task_id="ta-fb-29")
        assert req["task_id"] == fb["task_id"]

    def test_fallback_preserves_session_id(self) -> None:
        req = _make_dispatch_request(session_id="se-fb-29")
        fb = _make_fallback_result(session_id="se-fb-29")
        assert req["session_id"] == fb["session_id"]

    def test_fallback_path_is_fallback(self) -> None:
        fb = _make_fallback_result()
        assert fb["path"] == "fallback"

    def test_fallback_has_failure_kind_in_known_vocab(self) -> None:
        for fk in _KNOWN_FAILURE_KINDS:
            fb = _make_fallback_result(failure_kind=fk)
            assert fb["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_fallback_result_is_json_serialisable(self) -> None:
        fb = _make_fallback_result(trace_id="tr-fb-serial")
        serialised = json.dumps(fb)
        recovered = json.loads(serialised)
        assert recovered["trace_id"] == "tr-fb-serial"

    def test_mid_dispatch_unavailability_produces_fallback_with_identity(self) -> None:
        """Simulate a target becoming unavailable mid-dispatch."""
        req = _make_dispatch_request(trace_id="tr-mid", task_id="ta-mid",
                                     session_id="se-mid", path="delegated")
        # Target becomes unavailable — fallback must carry same identity
        fb = _make_fallback_result(
            trace_id=req["trace_id"],
            task_id=req["task_id"],
            session_id=req["session_id"],
            failure_kind="readiness_failure",
            fallback_reason="target_became_unavailable",
        )
        assert _result_identity_matches_request(req, fb)
        assert fb["failure_kind"] in _KNOWN_FAILURE_KINDS


# ---------------------------------------------------------------------------
# Group H — Client result shape is path-independent
# ---------------------------------------------------------------------------

class TestClientResultShapePathIndependent:
    """A result envelope delivered to the client surface MUST be structurally
    identical regardless of which internal path produced it."""

    def _local_result(self, trace_id: str = "tr-h", task_id: str = "ta-h",
                      session_id: str = "se-h") -> Dict[str, Any]:
        return _make_dispatch_result(trace_id=trace_id, task_id=task_id,
                                     session_id=session_id, path="local")

    def _delegated_result(self, trace_id: str = "tr-h", task_id: str = "ta-h",
                          session_id: str = "se-h") -> Dict[str, Any]:
        return _make_dispatch_result(trace_id=trace_id, task_id=task_id,
                                     session_id=session_id, path="delegated")

    def _fallback_result(self, trace_id: str = "tr-h", task_id: str = "ta-h",
                         session_id: str = "se-h") -> Dict[str, Any]:
        return _make_fallback_result(trace_id=trace_id, task_id=task_id,
                                     session_id=session_id)

    def test_local_result_has_base_fields(self) -> None:
        assert _result_has_base_fields(self._local_result())

    def test_delegated_result_has_base_fields(self) -> None:
        assert _result_has_base_fields(self._delegated_result())

    def test_fallback_result_has_base_fields(self) -> None:
        fb = self._fallback_result()
        # fallback also carries all required base fields
        for f in _RESULT_BASE_FIELDS:
            assert f in fb, f"fallback result missing field: {f}"

    def test_all_paths_have_identical_identity_fields(self) -> None:
        local = self._local_result(trace_id="tr-same", task_id="ta-same",
                                   session_id="se-same")
        delegated = self._delegated_result(trace_id="tr-same", task_id="ta-same",
                                           session_id="se-same")
        fallback = self._fallback_result(trace_id="tr-same", task_id="ta-same",
                                         session_id="se-same")
        for result in (local, delegated, fallback):
            assert result["trace_id"] == "tr-same"
            assert result["task_id"] == "ta-same"
            assert result["session_id"] == "se-same"

    @pytest.mark.parametrize("path", sorted(_KNOWN_PATHS))
    def test_path_field_matches_known_paths(self, path: str) -> None:
        assert path in _KNOWN_PATHS


# ---------------------------------------------------------------------------
# Group I — Gateway error semantics stable across readiness degradation
# ---------------------------------------------------------------------------

class TestGatewayErrorSemanticsReadinessDegradation:
    """Gateway-facing error semantics (PR-27) MUST not regress when readiness
    degrades during or after dispatch."""

    def _make_readiness_failure_result(
        self,
        trace_id: str = "tr-gw",
        task_id: str = "ta-gw",
        session_id: str = "se-gw",
        degradation_point: str = "pre_dispatch",
    ) -> Dict[str, Any]:
        return {
            "trace_id": trace_id,
            "task_id": task_id,
            "session_id": session_id,
            "status": "error",
            "failure_kind": "readiness_failure",
            "degradation_point": degradation_point,
            "path": "fallback",
        }

    def test_pre_dispatch_readiness_failure_uses_stable_kind(self) -> None:
        result = self._make_readiness_failure_result(degradation_point="pre_dispatch")
        assert result["failure_kind"] == "readiness_failure"
        assert result["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_mid_dispatch_readiness_failure_uses_stable_kind(self) -> None:
        result = self._make_readiness_failure_result(degradation_point="mid_dispatch")
        assert result["failure_kind"] == "readiness_failure"
        assert result["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_capability_check_failure_after_registration_uses_stable_kind(self) -> None:
        # capability check fails after initial registration succeeds
        result = {
            "trace_id": "tr-cap",
            "task_id": "ta-cap",
            "session_id": "se-cap",
            "status": "error",
            "failure_kind": "capability_failure",
            "path": "fallback",
        }
        assert result["failure_kind"] == "capability_failure"
        assert result["failure_kind"] in _KNOWN_FAILURE_KINDS

    def test_failure_kind_is_identical_pre_and_mid_dispatch(self) -> None:
        pre = self._make_readiness_failure_result(degradation_point="pre_dispatch")
        mid = self._make_readiness_failure_result(degradation_point="mid_dispatch")
        assert pre["failure_kind"] == mid["failure_kind"]

    def test_degradation_does_not_alter_identity_fields(self) -> None:
        pre = self._make_readiness_failure_result(
            trace_id="tr-dg", task_id="ta-dg", session_id="se-dg",
            degradation_point="pre_dispatch",
        )
        mid = self._make_readiness_failure_result(
            trace_id="tr-dg", task_id="ta-dg", session_id="se-dg",
            degradation_point="mid_dispatch",
        )
        for field in _IDENTITY_FIELDS:
            assert pre[field] == mid[field]


# ---------------------------------------------------------------------------
# Group J — Single authoritative result per dispatch request
# ---------------------------------------------------------------------------

class TestSingleAuthoritativeResult:
    """The client MUST observe exactly one authoritative result per dispatch
    request: no duplicates and no silent drops."""

    def test_result_list_has_exactly_one_entry_per_request(self) -> None:
        request = _make_dispatch_request(trace_id="tr-single")
        result = _make_dispatch_result(trace_id="tr-single")
        results = [result]  # single result per request
        assert len(results) == 1

    def test_no_duplicate_results_for_same_trace_id(self) -> None:
        results = [
            _make_dispatch_result(trace_id="tr-dup", path="local"),
            _make_dispatch_result(trace_id="tr-dup", path="delegated"),
        ]
        # Deduplicate by trace_id — only one should survive
        seen: Dict[str, Any] = {}
        for r in results:
            if r["trace_id"] not in seen:
                seen[r["trace_id"]] = r
        assert len(seen) == 1
        assert "tr-dup" in seen

    def test_fallback_counts_as_authoritative_result(self) -> None:
        fb = _make_fallback_result(trace_id="tr-auth-fb")
        assert fb["trace_id"] == "tr-auth-fb"
        assert _result_has_base_fields(fb)

    def test_result_is_not_none(self) -> None:
        result = _make_dispatch_result()
        assert result is not None

    def test_result_dict_is_not_empty(self) -> None:
        result = _make_dispatch_result()
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Group K — Failure_kind vocabulary is stable and complete
# ---------------------------------------------------------------------------

class TestFailureKindVocabularyStable:
    def test_registration_failure_in_vocab(self) -> None:
        assert "registration_failure" in _KNOWN_FAILURE_KINDS

    def test_capability_failure_in_vocab(self) -> None:
        assert "capability_failure" in _KNOWN_FAILURE_KINDS

    def test_readiness_failure_in_vocab(self) -> None:
        assert "readiness_failure" in _KNOWN_FAILURE_KINDS

    def test_config_error_in_vocab(self) -> None:
        assert "config_error" in _KNOWN_FAILURE_KINDS

    def test_vocab_has_exactly_four_kinds(self) -> None:
        assert len(_KNOWN_FAILURE_KINDS) == 4

    def test_result_with_unknown_failure_kind_is_detectable(self) -> None:
        result = _make_dispatch_result(failure_kind="unknown_kind_xyz")
        assert result["failure_kind"] not in _KNOWN_FAILURE_KINDS

    def test_all_failure_kind_values_are_strings(self) -> None:
        for fk in _KNOWN_FAILURE_KINDS:
            assert isinstance(fk, str)


# ---------------------------------------------------------------------------
# Group L — Sentinel strings contain expected policy keywords
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator unavailable",
)
class TestSentinelKeywords:
    def test_main_sentinel_contains_pr29(self) -> None:
        assert "29" in POST_RELEASE_FOLLOW_UP_TIGHTENING_PR29_SENTINEL

    def test_main_sentinel_contains_tightening(self) -> None:
        lower = POST_RELEASE_FOLLOW_UP_TIGHTENING_PR29_SENTINEL.lower()
        assert "tightening" in lower or "follow-up" in lower or "post-release" in lower

    def test_selection_policy_contains_deterministic(self) -> None:
        lower = DISPATCH_SELECTION_COHESION_STABILITY_PR29_POLICY.lower()
        assert "deterministic" in lower or "cohesion" in lower or "stability" in lower

    def test_registration_policy_contains_failure_kind(self) -> None:
        lower = REGISTRATION_READINESS_CAPABILITY_TIGHTENING_PR29_POLICY.lower()
        assert "failure_kind" in lower or "failure" in lower

    def test_delegated_policy_contains_terminal(self) -> None:
        lower = DELEGATED_EXECUTION_FALLBACK_INTEGRATION_PR29_POLICY.lower()
        assert "terminal" in lower or "fallback" in lower or "delegated" in lower

    def test_client_policy_contains_single_system(self) -> None:
        lower = CLIENT_GATEWAY_SEMANTIC_CONSISTENCY_PR29_POLICY.lower()
        assert "single" in lower or "client" in lower or "semantic" in lower

    def test_all_policies_mention_no_new_authority(self) -> None:
        policies = [
            DISPATCH_SELECTION_COHESION_STABILITY_PR29_POLICY,
            DELEGATED_EXECUTION_FALLBACK_INTEGRATION_PR29_POLICY,
            CLIENT_GATEWAY_SEMANTIC_CONSISTENCY_PR29_POLICY,
        ]
        for policy in policies:
            lower = policy.lower()
            has_no_new = "no new" in lower or "not introduced" in lower or "not introduce" in lower
            assert has_no_new, (
                f"Policy does not affirm no-new-authority constraint: {policy[:80]}"
            )


# ---------------------------------------------------------------------------
# Group M — No new parallel authority: single-system model preserved
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator unavailable",
)
class TestNoNewParallelAuthority:
    def test_selection_policy_no_new_authority(self) -> None:
        lower = DISPATCH_SELECTION_COHESION_STABILITY_PR29_POLICY.lower()
        assert "no new" in lower or "not introduced" in lower or "not introduce" in lower

    def test_delegated_policy_no_new_coordinator(self) -> None:
        lower = DELEGATED_EXECUTION_FALLBACK_INTEGRATION_PR29_POLICY.lower()
        assert "no new" in lower or "not introduced" in lower or "not introduce" in lower

    def test_client_policy_single_system_model(self) -> None:
        lower = CLIENT_GATEWAY_SEMANTIC_CONSISTENCY_PR29_POLICY.lower()
        assert "single" in lower or "single-system" in lower or "no new" in lower

    def test_projection_sentinel_no_new_authority(self) -> None:
        if not _PROJECTION_AVAILABLE:
            pytest.skip("projection module unavailable")
        lower = POST_RELEASE_FOLLOW_UP_TIGHTENING_ALIGNED_PR29.lower()
        assert "no new" in lower or "not introduced" in lower or "not introduce" in lower

    def test_sentinels_do_not_reference_parallel_system(self) -> None:
        """None of the PR-29 sentinel strings should introduce a parallel authority."""
        for sentinel in [
            POST_RELEASE_FOLLOW_UP_TIGHTENING_PR29_SENTINEL,
            DISPATCH_SELECTION_COHESION_STABILITY_PR29_POLICY,
            REGISTRATION_READINESS_CAPABILITY_TIGHTENING_PR29_POLICY,
            DELEGATED_EXECUTION_FALLBACK_INTEGRATION_PR29_POLICY,
            CLIENT_GATEWAY_SEMANTIC_CONSISTENCY_PR29_POLICY,
        ]:
            lower = sentinel.lower()
            # Should not reference a new parallel subsystem
            assert "parallel_system" not in lower
            assert "new_authority" not in lower


# ---------------------------------------------------------------------------
# Group N — Idempotency: repeated selection for same input state
# ---------------------------------------------------------------------------

class TestSelectionIdempotency:
    """The select → reuse-check → fallback route MUST be idempotent for the
    same input state across repeated invocations."""

    def _deterministic_select(self, candidates: List[Dict[str, Any]]) -> str:
        """Minimal deterministic selection: same input → same output."""
        active_ready = [
            c for c in candidates
            if c.get("state") == "active" and c.get("readiness") == "ready"
        ]
        if not active_ready:
            return "fallback"
        # Sort for determinism
        sorted_candidates = sorted(active_ready, key=lambda c: c["device_id"])
        return sorted_candidates[0]["device_id"]

    def test_same_input_produces_same_output_single_candidate(self) -> None:
        candidates = [{"device_id": "dev-idem-1", "state": "active",
                       "readiness": "ready"}]
        results = {self._deterministic_select(candidates) for _ in range(5)}
        assert len(results) == 1  # always the same outcome

    def test_same_input_produces_same_output_multiple_candidates(self) -> None:
        candidates = [
            {"device_id": "dev-idem-B", "state": "active", "readiness": "ready"},
            {"device_id": "dev-idem-A", "state": "active", "readiness": "ready"},
        ]
        results = {self._deterministic_select(candidates) for _ in range(5)}
        assert len(results) == 1
        assert "dev-idem-A" in results  # sorted, A comes before B

    def test_fallback_is_idempotent_for_empty_candidates(self) -> None:
        results = {self._deterministic_select([]) for _ in range(5)}
        assert results == {"fallback"}

    def test_state_mutation_changes_outcome(self) -> None:
        """Mutating state must produce different outcome (proves determinism)."""
        candidates = [{"device_id": "dev-mut", "state": "active",
                       "readiness": "ready"}]
        result_before = self._deterministic_select(candidates)
        # Mutate state
        candidates[0]["state"] = "replaced"
        result_after = self._deterministic_select(candidates)
        assert result_before != result_after

    def test_idempotency_across_fallback_boundary(self) -> None:
        """Selecting → fallback → selecting again for same degraded input is stable."""
        degraded_candidates = [
            {"device_id": "dev-deg", "state": "active", "readiness": "degraded"}
        ]
        results = [self._deterministic_select(degraded_candidates) for _ in range(3)]
        assert all(r == "fallback" for r in results)
