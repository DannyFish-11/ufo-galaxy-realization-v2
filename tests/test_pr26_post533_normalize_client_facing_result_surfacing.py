"""tests/test_pr26_post533_normalize_client_facing_result_surfacing.py
=======================================================================
Tests for PR package 26 (post-533 dual-repo runtime unification master plan,
main repo side): Normalize Client-Facing Result Surfacing.

This test suite verifies that:

1. All PR-26 policy/authority sentinels are present in the orchestrator module.
2. The client-facing result contract (SourceDispatchResult) is structurally
   invariant across local, remote_handoff, fallback_local, staged_mesh, and
   blocked execution paths.
3. Result semantics (success, mode, errors, decision_reason) are coherent
   regardless of which internal execution path produced the outcome.
4. Result identity fields (result_id, dispatch_id, trace_id, task_id) are
   stable and consistently populated across all paths.
5. No path-specific result contract drift — to_dict() yields the same
   top-level field set for every execution path.
6. The projection sentinel is importable and is not UNAVAILABLE.
7. core.runtime re-exports all PR-26 sentinel symbols.

Coverage groups
---------------
A  — Orchestrator module: all PR-26 sentinels present.
B  — Projection: PR-26 sentinel is importable and not UNAVAILABLE.
C  — core.runtime re-exports all PR-26 sentinels.
D  — Result contract invariance: local path result has required fields.
E  — Result contract invariance: remote_handoff result has required fields.
F  — Result contract invariance: fallback_local result has required fields.
G  — Result contract invariance: blocked result has required fields.
H  — Result semantics: local success has success=True, non-empty decision_reason.
I  — Result semantics: remote success has success=True, mode=remote_handoff.
J  — Result semantics: fallback_local has success reflects executor outcome,
     effective mode=fallback_local, errors non-empty.
K  — Result semantics: blocked has success=False, errors non-empty.
L  — Result identity: result_id is unique per result (UUID4).
M  — Result identity: dispatch_id, trace_id, task_id propagated.
N  — No path drift: to_dict() top-level keys are identical across paths.
O  — Serialisation: every path produces JSON-serialisable to_dict().
P  — Sentinel strings are non-empty and contain policy keywords.
Q  — Regression: failure_dispatch_result carries same surface contract.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.runtime.source_dispatch_orchestrator import (
        CLIENT_FACING_RESULT_SURFACING_NORMALIZED_PR26_SENTINEL,
        RESULT_CONTRACT_IS_INVARIANT_ACROSS_DISPATCH_PATHS_PR26_POLICY,
        RESULT_SEMANTICS_ARE_COHERENT_REGARDLESS_OF_PATH_PR26_POLICY,
        RESULT_IDENTITY_IS_STABLE_ACROSS_EXECUTION_PATHS_PR26_POLICY,
        NO_PATH_SPECIFIC_RESULT_CONTRACT_DRIFT_PR26_POLICY,
        orchestrate_source_runtime_dispatch,
        select_dispatch_mode,
        build_source_dispatch_plan,
    )

    _ORCHESTRATOR_AVAILABLE = True
except ImportError:
    _ORCHESTRATOR_AVAILABLE = False

try:
    from contracts.source_dispatch import (
        SourceDispatchMode,
        SourceDispatchResult,
        build_source_dispatch_result,
        failure_dispatch_result,
    )

    _CONTRACTS_AVAILABLE = True
except ImportError:
    _CONTRACTS_AVAILABLE = False

try:
    from core.routes.projection import CLIENT_FACING_RESULT_SURFACING_NORMALIZED_ALIGNED_PR26

    _PROJECTION_AVAILABLE = True
except ImportError:
    _PROJECTION_AVAILABLE = False

try:
    from core.runtime import (
        CLIENT_FACING_RESULT_SURFACING_NORMALIZED_PR26_SENTINEL as _rt_sentinel,
        RESULT_CONTRACT_IS_INVARIANT_ACROSS_DISPATCH_PATHS_PR26_POLICY as _rt_contract,
        RESULT_SEMANTICS_ARE_COHERENT_REGARDLESS_OF_PATH_PR26_POLICY as _rt_semantics,
        RESULT_IDENTITY_IS_STABLE_ACROSS_EXECUTION_PATHS_PR26_POLICY as _rt_identity,
        NO_PATH_SPECIFIC_RESULT_CONTRACT_DRIFT_PR26_POLICY as _rt_no_drift,
    )

    _RUNTIME_EXPORTS_AVAILABLE = True
except ImportError:
    _RUNTIME_EXPORTS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Required fields that every SourceDispatchResult.to_dict() MUST carry
# ---------------------------------------------------------------------------

_REQUIRED_RESULT_FIELDS = {
    "result_id",
    "dispatch_id",
    "trace_id",
    "task_id",
    "session_id",
    "source_device_id",
    "source_runtime_id",
    "mode",
    "selected_target",
    "success",
    "result",
    "errors",
    "decision_reason",
    "timestamp",
    "metadata",
}


# ---------------------------------------------------------------------------
# A — Orchestrator module: all PR-26 sentinels present
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ORCHESTRATOR_AVAILABLE, reason="orchestrator module unavailable")
class TestOrchestatorPR26Sentinels:
    def test_main_sentinel_present(self):
        assert CLIENT_FACING_RESULT_SURFACING_NORMALIZED_PR26_SENTINEL
        assert "PR26" in CLIENT_FACING_RESULT_SURFACING_NORMALIZED_PR26_SENTINEL
        assert "result" in CLIENT_FACING_RESULT_SURFACING_NORMALIZED_PR26_SENTINEL.lower()

    def test_contract_invariant_policy_present(self):
        assert RESULT_CONTRACT_IS_INVARIANT_ACROSS_DISPATCH_PATHS_PR26_POLICY
        assert "PR26" in RESULT_CONTRACT_IS_INVARIANT_ACROSS_DISPATCH_PATHS_PR26_POLICY

    def test_semantics_policy_present(self):
        assert RESULT_SEMANTICS_ARE_COHERENT_REGARDLESS_OF_PATH_PR26_POLICY
        assert "PR26" in RESULT_SEMANTICS_ARE_COHERENT_REGARDLESS_OF_PATH_PR26_POLICY

    def test_identity_policy_present(self):
        assert RESULT_IDENTITY_IS_STABLE_ACROSS_EXECUTION_PATHS_PR26_POLICY
        assert "PR26" in RESULT_IDENTITY_IS_STABLE_ACROSS_EXECUTION_PATHS_PR26_POLICY

    def test_no_drift_policy_present(self):
        assert NO_PATH_SPECIFIC_RESULT_CONTRACT_DRIFT_PR26_POLICY
        assert "PR26" in NO_PATH_SPECIFIC_RESULT_CONTRACT_DRIFT_PR26_POLICY

    def test_all_five_sentinels_non_empty(self):
        sentinels = [
            CLIENT_FACING_RESULT_SURFACING_NORMALIZED_PR26_SENTINEL,
            RESULT_CONTRACT_IS_INVARIANT_ACROSS_DISPATCH_PATHS_PR26_POLICY,
            RESULT_SEMANTICS_ARE_COHERENT_REGARDLESS_OF_PATH_PR26_POLICY,
            RESULT_IDENTITY_IS_STABLE_ACROSS_EXECUTION_PATHS_PR26_POLICY,
            NO_PATH_SPECIFIC_RESULT_CONTRACT_DRIFT_PR26_POLICY,
        ]
        for s in sentinels:
            assert isinstance(s, str)
            assert len(s) > 10


# ---------------------------------------------------------------------------
# B — Projection: PR-26 sentinel is importable and not UNAVAILABLE
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _PROJECTION_AVAILABLE, reason="projection module unavailable")
class TestProjectionPR26Sentinel:
    def test_sentinel_not_unavailable(self):
        assert "UNAVAILABLE" not in CLIENT_FACING_RESULT_SURFACING_NORMALIZED_ALIGNED_PR26

    def test_sentinel_contains_pr26_marker(self):
        assert "PR26" in CLIENT_FACING_RESULT_SURFACING_NORMALIZED_ALIGNED_PR26

    def test_sentinel_contains_result_keyword(self):
        assert "result" in CLIENT_FACING_RESULT_SURFACING_NORMALIZED_ALIGNED_PR26.lower()

    def test_sentinel_mentions_paths(self):
        s = CLIENT_FACING_RESULT_SURFACING_NORMALIZED_ALIGNED_PR26.lower()
        # Must mention at least one of the execution paths
        assert any(path in s for path in ("local", "remote", "fallback", "delegated", "blocked"))


# ---------------------------------------------------------------------------
# C — core.runtime re-exports all PR-26 sentinels
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _RUNTIME_EXPORTS_AVAILABLE, reason="core.runtime re-exports unavailable")
class TestCoreRuntimePR26Exports:
    def test_main_sentinel_exported(self):
        assert _rt_sentinel
        assert "PR26" in _rt_sentinel

    def test_contract_policy_exported(self):
        assert _rt_contract
        assert "PR26" in _rt_contract

    def test_semantics_policy_exported(self):
        assert _rt_semantics
        assert "PR26" in _rt_semantics

    def test_identity_policy_exported(self):
        assert _rt_identity
        assert "PR26" in _rt_identity

    def test_no_drift_policy_exported(self):
        assert _rt_no_drift
        assert "PR26" in _rt_no_drift

    def test_all_match_orchestrator(self):
        """Re-exported symbols must be identical to orchestrator originals."""
        assert _rt_sentinel == CLIENT_FACING_RESULT_SURFACING_NORMALIZED_PR26_SENTINEL
        assert _rt_contract == RESULT_CONTRACT_IS_INVARIANT_ACROSS_DISPATCH_PATHS_PR26_POLICY
        assert _rt_semantics == RESULT_SEMANTICS_ARE_COHERENT_REGARDLESS_OF_PATH_PR26_POLICY
        assert _rt_identity == RESULT_IDENTITY_IS_STABLE_ACROSS_EXECUTION_PATHS_PR26_POLICY
        assert _rt_no_drift == NO_PATH_SPECIFIC_RESULT_CONTRACT_DRIFT_PR26_POLICY


# ---------------------------------------------------------------------------
# D–G — Result contract invariance: required fields present across all paths
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _CONTRACTS_AVAILABLE, reason="contracts unavailable")
class TestResultContractInvariance:
    """Verify that SourceDispatchResult.to_dict() carries all required fields
    regardless of the execution path mode."""

    def _build(self, mode: "SourceDispatchMode", **kwargs: Any) -> Dict[str, Any]:
        r = build_source_dispatch_result(
            dispatch_id=str(uuid.uuid4()),
            trace_id="trace-pr26",
            task_id="task-pr26",
            session_id="sess-pr26",
            mode=mode,
            success=kwargs.pop("success", True),
            errors=kwargs.pop("errors", []),
            decision_reason=kwargs.pop("decision_reason", f"{mode.value}:test"),
            **kwargs,
        )
        return r.to_dict()

    # D — local path
    def test_local_result_has_required_fields(self):
        d = self._build(SourceDispatchMode.local)
        for field in _REQUIRED_RESULT_FIELDS:
            assert field in d, f"Missing field '{field}' in local result"

    # E — remote_handoff path
    def test_remote_handoff_result_has_required_fields(self):
        d = self._build(SourceDispatchMode.remote_handoff)
        for field in _REQUIRED_RESULT_FIELDS:
            assert field in d, f"Missing field '{field}' in remote_handoff result"

    # F — fallback_local path
    def test_fallback_local_result_has_required_fields(self):
        d = self._build(
            SourceDispatchMode.fallback_local,
            success=False,
            errors=["remote_handoff_failed:test"],
            decision_reason="remote_handoff_failed:fallback_local",
        )
        for field in _REQUIRED_RESULT_FIELDS:
            assert field in d, f"Missing field '{field}' in fallback_local result"

    # G — blocked path
    def test_blocked_result_has_required_fields(self):
        d = self._build(
            SourceDispatchMode.blocked,
            success=False,
            errors=["dispatch_blocked_by_policy"],
            decision_reason="dispatch_blocked_by_policy",
        )
        for field in _REQUIRED_RESULT_FIELDS:
            assert field in d, f"Missing field '{field}' in blocked result"

    # staged_mesh path also carries required fields
    def test_staged_mesh_result_has_required_fields(self):
        d = self._build(SourceDispatchMode.staged_mesh)
        for field in _REQUIRED_RESULT_FIELDS:
            assert field in d, f"Missing field '{field}' in staged_mesh result"


# ---------------------------------------------------------------------------
# H–K — Result semantics coherence across paths
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _CONTRACTS_AVAILABLE, reason="contracts unavailable")
class TestResultSemantics:
    """Verify that success/mode/errors/decision_reason semantics are coherent."""

    # H — local success semantics
    def test_local_success_semantics(self):
        r = build_source_dispatch_result(
            trace_id="tr-1",
            task_id="t-1",
            mode=SourceDispatchMode.local,
            success=True,
            decision_reason="local_execution:success",
        )
        assert r.success is True
        assert r.mode == SourceDispatchMode.local
        assert r.decision_reason is not None
        assert len(r.decision_reason) > 0
        assert r.errors == []

    # I — remote_handoff success semantics
    def test_remote_handoff_success_semantics(self):
        r = build_source_dispatch_result(
            trace_id="tr-2",
            task_id="t-2",
            mode=SourceDispatchMode.remote_handoff,
            success=True,
            decision_reason="remote_handoff:success",
        )
        assert r.success is True
        assert r.mode == SourceDispatchMode.remote_handoff
        assert r.decision_reason == "remote_handoff:success"

    # J — fallback_local semantics
    def test_fallback_local_semantics(self):
        r = build_source_dispatch_result(
            trace_id="tr-3",
            task_id="t-3",
            mode=SourceDispatchMode.fallback_local,
            success=False,
            errors=["remote_handoff_failed:bridge_unreachable"],
            decision_reason="remote_handoff_failed:fallback_local",
        )
        assert r.mode == SourceDispatchMode.fallback_local
        assert len(r.errors) > 0
        assert "remote_handoff_failed" in r.errors[0]
        assert r.decision_reason is not None
        assert "fallback_local" in r.decision_reason

    # K — blocked semantics
    def test_blocked_semantics(self):
        r = build_source_dispatch_result(
            trace_id="tr-4",
            task_id="t-4",
            mode=SourceDispatchMode.blocked,
            success=False,
            errors=["dispatch_blocked_by_policy"],
            decision_reason="dispatch_blocked_by_policy",
        )
        assert r.success is False
        assert r.mode == SourceDispatchMode.blocked
        assert len(r.errors) > 0
        assert r.decision_reason is not None

    def test_decision_reason_always_identifies_path(self):
        """decision_reason must not be None in any path."""
        paths_and_reasons = [
            (SourceDispatchMode.local, "local_execution:success"),
            (SourceDispatchMode.remote_handoff, "remote_handoff:success"),
            (SourceDispatchMode.fallback_local, "remote_handoff_failed:fallback_local"),
            (SourceDispatchMode.blocked, "dispatch_blocked_by_policy"),
            (SourceDispatchMode.staged_mesh, "staged_mesh:plan_prepared"),
        ]
        for mode, reason in paths_and_reasons:
            r = build_source_dispatch_result(
                mode=mode,
                success=(mode not in (SourceDispatchMode.blocked,)),
                errors=([] if mode != SourceDispatchMode.blocked else ["blocked"]),
                decision_reason=reason,
            )
            assert r.decision_reason is not None, f"decision_reason None for mode={mode}"
            assert len(r.decision_reason) > 0, f"decision_reason empty for mode={mode}"


# ---------------------------------------------------------------------------
# L–M — Result identity stability across paths
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _CONTRACTS_AVAILABLE, reason="contracts unavailable")
class TestResultIdentity:
    """Verify that result_id, dispatch_id, trace_id, task_id are stable."""

    # L — result_id is unique per result
    def test_result_id_is_unique(self):
        r1 = build_source_dispatch_result(mode=SourceDispatchMode.local, success=True)
        r2 = build_source_dispatch_result(mode=SourceDispatchMode.local, success=True)
        assert r1.result_id != r2.result_id

    def test_result_id_is_uuid4_format(self):
        r = build_source_dispatch_result(mode=SourceDispatchMode.local, success=True)
        # Should not raise
        parsed = uuid.UUID(r.result_id, version=4)
        assert str(parsed) == r.result_id

    # M — identity fields propagated
    def test_trace_id_propagated_local(self):
        r = build_source_dispatch_result(
            trace_id="trace-abc",
            mode=SourceDispatchMode.local,
            success=True,
        )
        assert r.trace_id == "trace-abc"

    def test_task_id_propagated_remote(self):
        r = build_source_dispatch_result(
            task_id="task-xyz",
            mode=SourceDispatchMode.remote_handoff,
            success=True,
        )
        assert r.task_id == "task-xyz"

    def test_dispatch_id_propagated(self):
        did = str(uuid.uuid4())
        r = build_source_dispatch_result(
            dispatch_id=did,
            mode=SourceDispatchMode.fallback_local,
            success=False,
            errors=["remote_failed"],
            decision_reason="fallback",
        )
        assert r.dispatch_id == did

    def test_identity_in_failure_dispatch_result(self):
        """failure_dispatch_result also carries identity fields."""
        r = failure_dispatch_result(
            trace_id="tr-fail",
            task_id="t-fail",
            mode=SourceDispatchMode.unknown,
            reason="test_failure",
        )
        assert r.trace_id == "tr-fail"
        assert r.task_id == "t-fail"
        assert r.result_id  # must be non-empty UUID

    def test_identity_consistent_across_all_paths(self):
        """All paths propagate the same trace_id and task_id."""
        tid = "task-common"
        trid = "trace-common"
        modes = [
            SourceDispatchMode.local,
            SourceDispatchMode.remote_handoff,
            SourceDispatchMode.fallback_local,
            SourceDispatchMode.blocked,
            SourceDispatchMode.staged_mesh,
        ]
        for mode in modes:
            r = build_source_dispatch_result(
                trace_id=trid,
                task_id=tid,
                mode=mode,
                success=(mode not in (SourceDispatchMode.blocked,)),
                errors=([] if mode != SourceDispatchMode.blocked else ["blocked"]),
                decision_reason=f"{mode.value}:test",
            )
            assert r.trace_id == trid, f"trace_id mismatch for mode={mode}"
            assert r.task_id == tid, f"task_id mismatch for mode={mode}"


# ---------------------------------------------------------------------------
# N — No path drift: to_dict() top-level keys identical across paths
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _CONTRACTS_AVAILABLE, reason="contracts unavailable")
class TestNoDriftAcrossPaths:
    """Verify that to_dict() top-level keys are consistent across all paths."""

    def _result_keys(self, mode: "SourceDispatchMode") -> frozenset:
        r = build_source_dispatch_result(
            trace_id="tr",
            task_id="t",
            mode=mode,
            success=(mode not in (SourceDispatchMode.blocked,)),
            errors=([] if mode != SourceDispatchMode.blocked else ["blocked"]),
            decision_reason=f"{mode.value}:test",
        )
        return frozenset(r.to_dict().keys())

    def test_local_and_remote_have_same_keys(self):
        local_keys = self._result_keys(SourceDispatchMode.local)
        remote_keys = self._result_keys(SourceDispatchMode.remote_handoff)
        assert local_keys == remote_keys, (
            f"Key drift: local={local_keys - remote_keys} remote={remote_keys - local_keys}"
        )

    def test_local_and_fallback_local_have_same_keys(self):
        local_keys = self._result_keys(SourceDispatchMode.local)
        fallback_keys = self._result_keys(SourceDispatchMode.fallback_local)
        assert local_keys == fallback_keys

    def test_local_and_blocked_have_same_keys(self):
        local_keys = self._result_keys(SourceDispatchMode.local)
        blocked_keys = self._result_keys(SourceDispatchMode.blocked)
        assert local_keys == blocked_keys

    def test_all_five_paths_have_same_keys(self):
        all_key_sets = [
            self._result_keys(m)
            for m in [
                SourceDispatchMode.local,
                SourceDispatchMode.remote_handoff,
                SourceDispatchMode.fallback_local,
                SourceDispatchMode.blocked,
                SourceDispatchMode.staged_mesh,
            ]
        ]
        reference = all_key_sets[0]
        for ks in all_key_sets[1:]:
            assert ks == reference, f"Key drift detected: {ks.symmetric_difference(reference)}"

    def test_failure_dispatch_result_keys_match(self):
        """failure_dispatch_result must also expose the same field set."""
        normal_keys = self._result_keys(SourceDispatchMode.local)
        failure_r = failure_dispatch_result(
            trace_id="tr",
            task_id="t",
            mode=SourceDispatchMode.unknown,
            reason="test",
        )
        failure_keys = frozenset(failure_r.to_dict().keys())
        assert normal_keys == failure_keys


# ---------------------------------------------------------------------------
# O — Serialisation: every path produces JSON-serialisable to_dict()
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _CONTRACTS_AVAILABLE, reason="contracts unavailable")
class TestResultSerialisation:
    """Verify JSON-serialisability across all execution paths."""

    def _serialise_path(self, mode: "SourceDispatchMode") -> str:
        r = build_source_dispatch_result(
            trace_id="tr-serial",
            task_id="t-serial",
            mode=mode,
            success=(mode not in (SourceDispatchMode.blocked,)),
            errors=([] if mode != SourceDispatchMode.blocked else ["blocked"]),
            decision_reason=f"{mode.value}:serialisation_test",
        )
        return json.dumps(r.to_dict())

    def test_local_json_serialisable(self):
        s = self._serialise_path(SourceDispatchMode.local)
        assert isinstance(s, str)
        d = json.loads(s)
        assert d["mode"] == "local"

    def test_remote_handoff_json_serialisable(self):
        s = self._serialise_path(SourceDispatchMode.remote_handoff)
        d = json.loads(s)
        assert d["mode"] == "remote_handoff"

    def test_fallback_local_json_serialisable(self):
        s = self._serialise_path(SourceDispatchMode.fallback_local)
        d = json.loads(s)
        assert d["mode"] == "fallback_local"

    def test_blocked_json_serialisable(self):
        s = self._serialise_path(SourceDispatchMode.blocked)
        d = json.loads(s)
        assert d["mode"] == "blocked"

    def test_staged_mesh_json_serialisable(self):
        s = self._serialise_path(SourceDispatchMode.staged_mesh)
        d = json.loads(s)
        assert d["mode"] == "staged_mesh"

    def test_to_json_round_trip(self):
        r = build_source_dispatch_result(
            trace_id="tr-rtrip",
            task_id="t-rtrip",
            mode=SourceDispatchMode.local,
            success=True,
            decision_reason="local_execution:success",
        )
        json_str = r.to_json()
        d = json.loads(json_str)
        assert d["trace_id"] == "tr-rtrip"
        assert d["task_id"] == "t-rtrip"
        assert d["success"] is True


# ---------------------------------------------------------------------------
# P — Sentinel strings contain policy keywords
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ORCHESTRATOR_AVAILABLE, reason="orchestrator module unavailable")
class TestSentinelContent:
    """Verify sentinel strings contain expected policy keywords."""

    def test_main_sentinel_contains_package_marker(self):
        assert "package=26" in CLIENT_FACING_RESULT_SURFACING_NORMALIZED_PR26_SENTINEL

    def test_contract_policy_mentions_invariant(self):
        s = RESULT_CONTRACT_IS_INVARIANT_ACROSS_DISPATCH_PATHS_PR26_POLICY.lower()
        assert "invariant" in s or "identical" in s

    def test_semantics_policy_mentions_coherent(self):
        s = RESULT_SEMANTICS_ARE_COHERENT_REGARDLESS_OF_PATH_PR26_POLICY.lower()
        assert "coherent" in s or "semantics" in s

    def test_identity_policy_mentions_stable(self):
        s = RESULT_IDENTITY_IS_STABLE_ACROSS_EXECUTION_PATHS_PR26_POLICY.lower()
        assert "stable" in s or "identity" in s

    def test_no_drift_policy_mentions_drift(self):
        s = NO_PATH_SPECIFIC_RESULT_CONTRACT_DRIFT_PR26_POLICY.lower()
        assert "drift" in s

    def test_contract_policy_mentions_all_paths(self):
        s = RESULT_CONTRACT_IS_INVARIANT_ACROSS_DISPATCH_PATHS_PR26_POLICY.lower()
        assert "local" in s
        assert "remote" in s or "handoff" in s
        assert "fallback" in s

    def test_no_drift_policy_mentions_to_dict(self):
        s = NO_PATH_SPECIFIC_RESULT_CONTRACT_DRIFT_PR26_POLICY.lower()
        assert "to_dict" in s


# ---------------------------------------------------------------------------
# Q — Regression: failure_dispatch_result carries same surface contract
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _CONTRACTS_AVAILABLE, reason="contracts unavailable")
class TestFailureDispatchResultRegression:
    """failure_dispatch_result is the error-path builder; it must still expose
    the canonical SourceDispatchResult contract."""

    def test_failure_result_type(self):
        r = failure_dispatch_result(
            trace_id="tr",
            task_id="t",
            mode=SourceDispatchMode.unknown,
            reason="orchestration_error:test",
        )
        assert isinstance(r, SourceDispatchResult)

    def test_failure_result_success_is_false(self):
        r = failure_dispatch_result(
            mode=SourceDispatchMode.unknown,
            reason="test",
        )
        assert r.success is False

    def test_failure_result_has_required_fields(self):
        r = failure_dispatch_result(
            trace_id="tr",
            task_id="t",
            mode=SourceDispatchMode.unknown,
            reason="test",
        )
        d = r.to_dict()
        for field in _REQUIRED_RESULT_FIELDS:
            assert field in d, f"failure_dispatch_result missing field '{field}'"

    def test_failure_result_json_serialisable(self):
        r = failure_dispatch_result(
            trace_id="tr",
            task_id="t",
            mode=SourceDispatchMode.unknown,
            reason="test_failure",
        )
        json_str = r.to_json()
        d = json.loads(json_str)
        assert d["success"] is False
        assert d["trace_id"] == "tr"

    def test_failure_result_errors_non_empty(self):
        r = failure_dispatch_result(
            mode=SourceDispatchMode.unknown,
            reason="orchestration_error:some_exc",
        )
        assert len(r.errors) > 0

    def test_failure_result_decision_reason_set(self):
        r = failure_dispatch_result(
            mode=SourceDispatchMode.unknown,
            reason="orchestration_error:exc",
        )
        assert r.decision_reason is not None
        assert len(r.decision_reason) > 0


# ---------------------------------------------------------------------------
# Integration: orchestrate_source_runtime_dispatch returns same contract
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _CONTRACTS_AVAILABLE),
    reason="orchestrator or contracts unavailable",
)
class TestOrchestrateResultContract:
    """Verify that orchestrate_source_runtime_dispatch always returns a
    SourceDispatchResult with the canonical contract, regardless of path."""

    def _run(self, **kwargs: Any) -> "SourceDispatchResult":
        return orchestrate_source_runtime_dispatch(
            trace_id=kwargs.pop("trace_id", "trace-integ"),
            task_id=kwargs.pop("task_id", "task-integ"),
            session_id=kwargs.pop("session_id", "sess-integ"),
            task=kwargs.pop("task", {"tool_name": "test", "args": {}}),
            **kwargs,
        )

    def test_local_path_result_type(self):
        with patch(
            "core.runtime.source_dispatch_orchestrator._try_run_local_execution",
            return_value={"success": True, "output": "ok"},
        ), patch(
            "core.runtime.source_dispatch_orchestrator.select_dispatch_mode",
            return_value=SourceDispatchMode.local,
        ):
            r = self._run(force_local=True)
        assert isinstance(r, SourceDispatchResult)

    def test_local_path_has_required_fields(self):
        with patch(
            "core.runtime.source_dispatch_orchestrator._try_run_local_execution",
            return_value={"success": True, "output": "ok"},
        ), patch(
            "core.runtime.source_dispatch_orchestrator.select_dispatch_mode",
            return_value=SourceDispatchMode.local,
        ):
            r = self._run(force_local=True)
        d = r.to_dict()
        for field in _REQUIRED_RESULT_FIELDS:
            assert field in d, f"Missing field '{field}' in local orchestration result"

    def test_local_path_result_json_serialisable(self):
        with patch(
            "core.runtime.source_dispatch_orchestrator._try_run_local_execution",
            return_value={"success": False, "skipped_reason": "openclawd_unavailable"},
        ), patch(
            "core.runtime.source_dispatch_orchestrator.select_dispatch_mode",
            return_value=SourceDispatchMode.local,
        ):
            r = self._run(force_local=True)
        json_str = r.to_json()
        d = json.loads(json_str)
        assert isinstance(d, dict)
        assert "success" in d

    def test_blocked_path_result_type(self):
        with patch(
            "core.runtime.source_dispatch_orchestrator.select_dispatch_mode",
            return_value=SourceDispatchMode.blocked,
        ):
            r = self._run(source_runtime_posture="control_only")
        assert isinstance(r, SourceDispatchResult)
        assert r.success is False

    def test_blocked_path_has_required_fields(self):
        with patch(
            "core.runtime.source_dispatch_orchestrator.select_dispatch_mode",
            return_value=SourceDispatchMode.blocked,
        ):
            r = self._run(source_runtime_posture="control_only")
        d = r.to_dict()
        for field in _REQUIRED_RESULT_FIELDS:
            assert field in d

    def test_all_paths_have_same_to_dict_keys(self):
        """Local and blocked paths must produce identical top-level field sets."""
        with patch(
            "core.runtime.source_dispatch_orchestrator._try_run_local_execution",
            return_value={"success": True},
        ), patch(
            "core.runtime.source_dispatch_orchestrator.select_dispatch_mode",
            return_value=SourceDispatchMode.local,
        ):
            local_r = self._run(force_local=True)

        with patch(
            "core.runtime.source_dispatch_orchestrator.select_dispatch_mode",
            return_value=SourceDispatchMode.blocked,
        ):
            blocked_r = self._run()

        local_keys = frozenset(local_r.to_dict().keys())
        blocked_keys = frozenset(blocked_r.to_dict().keys())
        assert local_keys == blocked_keys, (
            f"Key drift: local={local_keys - blocked_keys} blocked={blocked_keys - local_keys}"
        )
