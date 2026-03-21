"""
tests/test_pr23_execution_readiness_gate.py
=============================================
Focused tests for PR-23: Execution Readiness Gate.

Coverage
--------
1. ReadinessStatus — enum values are stable strings
2. BlockedBy — enum values are stable strings
3. ReadinessResult
   - construction with defaults
   - construction with all fields
   - serialisation stability (to_dict / to_json round-trip)
   - governance_summary() contains expected keys

4. ExecutionReadinessGate.evaluate()
   (a) Ready path
       - manifest phase + execute action_level → ready
       - full_execute band → ready, no confirmation
   (b) Observe-only path
       - action_level=observe → observe_only
       - action_level=hint   → observe_only
   (c) Blocked path — policy
       - silent phase → policy blocks execute
       - assistive band → blocked
   (d) Blocked path — missing intent
       - no intent_profile and no action_level → missing_intent
   (e) Blocked path — missing target
       - require_target=True, no target_ref → missing_target
   (f) Confirm-required path — HITL / policy
       - bounded_execute band → confirmation required
   (g) Graceful degradation
       - resolver raises → gate degrades gracefully
       - HITL raises → gate degrades gracefully
       - all signals absent → blocked (missing_intent or observe_only)

5. evaluate_readiness() module-level helper
   - delegates to singleton gate
   - produces same result as direct ExecutionReadinessGate().evaluate()

6. reset_readiness_gate() — resets singleton for test isolation

7. Serialisation stability
   - ReadinessResult.to_dict() is JSON-serialisable
   - round-trip: dict → ReadinessResult via model_validate preserves fields

8. Integration with ExecutionIntentProfile (PR-22)
   - gate correctly extracts signals from an ExecutionIntentProfile
   - intent_id is propagated to ReadinessResult

9. OpenClawd._check_readiness() integration
   - returns a ReadinessResult for a valid continuum dict
   - returns None gracefully when gate raises
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from core.execution.readiness_gate import (
    BlockedBy,
    ExecutionReadinessGate,
    ReadinessResult,
    ReadinessStatus,
    evaluate_readiness,
    reset_readiness_gate,
)
from core.execution.intent_profile import (
    ExecutionIntentProfile,
    build_execution_intent_profile,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_MANIFEST_CONTINUUM: Dict[str, Any] = {
    "phase": "manifest",
    "runtime_domain": "local",
    "decision": {
        "action_level": "execute",
        "decision_confidence": 0.9,
    },
    "metadata": {
        "execution_target": "notepad.exe",
        "target_type": "app",
    },
}

# manifest + cross_device → full_execute band → ready (no confirmation)
_MANIFEST_CROSS_DEVICE_CONTINUUM: Dict[str, Any] = {
    "phase": "manifest",
    "runtime_domain": "cross_device",
    "decision": {
        "action_level": "execute",
        "decision_confidence": 0.9,
    },
    "metadata": {
        "execution_target": "notepad.exe",
        "target_type": "app",
    },
}

_SILENT_CONTINUUM: Dict[str, Any] = {
    "phase": "silent",
    "runtime_domain": "local",
    "decision": {
        "action_level": "execute",
        "decision_confidence": 0.5,
    },
}

_LIMINAL_CONTINUUM: Dict[str, Any] = {
    "phase": "liminal",
    "runtime_domain": "local",
    "decision": {
        "action_level": "assist",
        "decision_confidence": 0.6,
    },
}


def _make_gate(**kwargs) -> ExecutionReadinessGate:
    return ExecutionReadinessGate(**kwargs)


def _make_profile(
    action_level: str = "execute",
    target_ref: Optional[str] = "notepad.exe",
    runtime_session_id: Optional[str] = "sess-abc",
    runtime_domain: Optional[str] = "local",
) -> ExecutionIntentProfile:
    return ExecutionIntentProfile(
        action_level=action_level,
        target_ref=target_ref,
        runtime_session_id=runtime_session_id,
        runtime_domain=runtime_domain,
    )


# ---------------------------------------------------------------------------
# 1. ReadinessStatus enum
# ---------------------------------------------------------------------------


class TestReadinessStatus:
    def test_values_are_stable_strings(self):
        assert ReadinessStatus.READY.value == "ready"
        assert ReadinessStatus.CONFIRM_REQUIRED.value == "confirm_required"
        assert ReadinessStatus.BLOCKED.value == "blocked"
        assert ReadinessStatus.OBSERVE_ONLY.value == "observe_only"

    def test_str_subclass(self):
        assert isinstance(ReadinessStatus.READY, str)


# ---------------------------------------------------------------------------
# 2. BlockedBy enum
# ---------------------------------------------------------------------------


class TestBlockedBy:
    def test_values_are_stable_strings(self):
        assert BlockedBy.POLICY.value == "policy"
        assert BlockedBy.HITL.value == "hitl"
        assert BlockedBy.RUNTIME_PHASE.value == "runtime_phase"
        assert BlockedBy.DOMAIN.value == "domain"
        assert BlockedBy.MISSING_TARGET.value == "missing_target"
        assert BlockedBy.MISSING_INTENT.value == "missing_intent"
        assert BlockedBy.ACTION_LEVEL.value == "action_level"
        assert BlockedBy.CONFIRMATION_REQUIRED.value == "confirmation_required"
        assert BlockedBy.NONE.value == "none"

    def test_str_subclass(self):
        assert isinstance(BlockedBy.POLICY, str)


# ---------------------------------------------------------------------------
# 3. ReadinessResult
# ---------------------------------------------------------------------------


class TestReadinessResult:
    def test_defaults_are_conservative(self):
        r = ReadinessResult()
        assert r.ready is False
        assert r.status == ReadinessStatus.BLOCKED.value
        assert r.requires_confirmation is False
        assert r.blocked_by == BlockedBy.NONE.value
        assert r.action_level == "observe"
        assert r.notes == []

    def test_all_fields(self):
        intent_id = str(uuid.uuid4())
        r = ReadinessResult(
            ready=True,
            status=ReadinessStatus.READY.value,
            reason="all gates passed",
            requires_confirmation=False,
            policy_band="full_execute",
            blocked_by=BlockedBy.NONE.value,
            runtime_session_id="sess-123",
            intent_id=intent_id,
            action_level="execute",
            runtime_domain="local",
            notes=["note1"],
        )
        assert r.ready is True
        assert r.policy_band == "full_execute"
        assert r.intent_id == intent_id
        assert r.notes == ["note1"]

    def test_to_dict_is_serialisable(self):
        r = ReadinessResult(
            ready=True,
            status=ReadinessStatus.READY.value,
            reason="ok",
            policy_band="bounded_execute",
        )
        d = r.to_dict()
        # Must be JSON-serialisable without error
        dumped = json.dumps(d)
        loaded = json.loads(dumped)
        assert loaded["ready"] is True
        assert loaded["status"] == "ready"
        assert loaded["policy_band"] == "bounded_execute"

    def test_to_json_round_trip(self):
        r = ReadinessResult(ready=False, status="blocked", reason="test")
        j = r.to_json()
        data = json.loads(j)
        r2 = ReadinessResult.model_validate(data)
        assert r2.ready == r.ready
        assert r2.status == r.status
        assert r2.reason == r.reason

    def test_governance_summary_keys(self):
        r = ReadinessResult(
            ready=True,
            status="ready",
            policy_band="full_execute",
            blocked_by="none",
            action_level="execute",
        )
        summary = r.governance_summary()
        assert "ready" in summary
        assert "status" in summary
        assert "requires_confirmation" in summary
        assert "policy_band" in summary
        assert "blocked_by" in summary
        assert "action_level" in summary
        assert "intent_id" in summary


# ---------------------------------------------------------------------------
# 4a. Gate — ready path
# ---------------------------------------------------------------------------


class TestReadyPath:
    def test_manifest_cross_device_execute_is_ready(self):
        # manifest + cross_device → full_execute band → ready, no confirmation
        gate = _make_gate()
        profile = _make_profile(action_level="execute", runtime_domain="cross_device")
        result = gate.evaluate(profile, state_continuum=_MANIFEST_CROSS_DEVICE_CONTINUUM)
        assert result.ready is True
        assert result.status == ReadinessStatus.READY.value
        assert result.requires_confirmation is False
        assert result.blocked_by == BlockedBy.NONE.value

    def test_manifest_local_execute_is_confirm_required(self):
        # manifest + local → bounded_execute band → confirm_required (policy requires confirmation)
        gate = _make_gate()
        profile = _make_profile(action_level="execute", runtime_domain="local")
        result = gate.evaluate(profile, state_continuum=_MANIFEST_CONTINUUM)
        assert result.ready is True
        assert result.status == ReadinessStatus.CONFIRM_REQUIRED.value
        assert result.requires_confirmation is True

    def test_ready_propagates_intent_id(self):
        profile = _make_profile(action_level="execute", runtime_domain="cross_device")
        gate = _make_gate()
        result = gate.evaluate(profile, state_continuum=_MANIFEST_CROSS_DEVICE_CONTINUUM)
        assert result.intent_id == profile.intent_id

    def test_ready_propagates_session_id(self):
        profile = _make_profile(
            action_level="execute",
            runtime_session_id="sess-xyz",
            runtime_domain="cross_device",
        )
        gate = _make_gate()
        result = gate.evaluate(profile, state_continuum=_MANIFEST_CROSS_DEVICE_CONTINUUM)
        assert result.runtime_session_id == "sess-xyz"

    def test_ready_propagates_policy_band(self):
        gate = _make_gate()
        profile = _make_profile(action_level="execute", runtime_domain="cross_device")
        result = gate.evaluate(profile, state_continuum=_MANIFEST_CROSS_DEVICE_CONTINUUM)
        assert result.policy_band == "full_execute"

    def test_ready_runtime_domain_propagated(self):
        gate = _make_gate()
        profile = _make_profile(action_level="execute", runtime_domain="cross_device")
        result = gate.evaluate(profile, state_continuum=_MANIFEST_CROSS_DEVICE_CONTINUUM)
        assert result.runtime_domain is not None


# ---------------------------------------------------------------------------
# 4b. Gate — observe-only path
# ---------------------------------------------------------------------------


class TestObserveOnlyPath:
    @pytest.mark.parametrize("level", ["observe", "hint"])
    def test_observe_and_hint_are_observe_only(self, level):
        gate = _make_gate()
        result = gate.evaluate(action_level=level)
        assert result.ready is False
        assert result.status == ReadinessStatus.OBSERVE_ONLY.value
        assert result.blocked_by == BlockedBy.ACTION_LEVEL.value

    def test_profile_with_observe_is_observe_only(self):
        profile = _make_profile(action_level="observe")
        gate = _make_gate()
        result = gate.evaluate(profile)
        assert result.status == ReadinessStatus.OBSERVE_ONLY.value

    def test_hint_profile_is_observe_only(self):
        profile = ExecutionIntentProfile(action_level="hint")
        gate = _make_gate()
        result = gate.evaluate(profile)
        assert result.status == ReadinessStatus.OBSERVE_ONLY.value


# ---------------------------------------------------------------------------
# 4c. Gate — blocked by policy
# ---------------------------------------------------------------------------


class TestBlockedByPolicy:
    def test_silent_phase_blocks_execute(self):
        gate = _make_gate()
        profile = _make_profile(action_level="execute")
        result = gate.evaluate(profile, state_continuum=_SILENT_CONTINUUM)
        assert result.ready is False
        assert result.status == ReadinessStatus.BLOCKED.value
        assert result.blocked_by == BlockedBy.POLICY.value

    def test_blocked_result_has_policy_band(self):
        gate = _make_gate()
        profile = _make_profile(action_level="execute")
        result = gate.evaluate(profile, state_continuum=_SILENT_CONTINUUM)
        assert result.policy_band == "observe_only"

    def test_observe_only_policy_band_blocks(self):
        from core.execution_policy import ExecutionPolicy, PolicyBand

        def _fake_resolver(_):
            return ExecutionPolicy(
                policy_band=PolicyBand.OBSERVE_ONLY,
                action_budget=0,
                reason="test_observe_only",
            )

        gate = _make_gate(policy_resolver_fn=_fake_resolver)
        result = gate.evaluate(action_level="execute")
        assert result.ready is False
        assert result.blocked_by == BlockedBy.POLICY.value

    def test_assistive_policy_band_blocks_execute(self):
        from core.execution_policy import ExecutionPolicy, PolicyBand

        def _fake_resolver(_):
            return ExecutionPolicy(
                policy_band=PolicyBand.ASSISTIVE,
                action_budget=0,
                reason="test_assistive",
            )

        gate = _make_gate(policy_resolver_fn=_fake_resolver)
        result = gate.evaluate(action_level="execute")
        assert result.ready is False
        assert result.blocked_by == BlockedBy.POLICY.value


# ---------------------------------------------------------------------------
# 4d. Gate — blocked by missing intent
# ---------------------------------------------------------------------------


class TestBlockedByMissingIntent:
    def test_no_profile_no_action_level_is_missing_intent(self):
        gate = _make_gate()
        result = gate.evaluate()
        assert result.ready is False
        assert result.blocked_by == BlockedBy.MISSING_INTENT.value

    def test_none_profile_none_action_level_is_missing_intent(self):
        gate = _make_gate()
        result = gate.evaluate(None)
        assert result.blocked_by == BlockedBy.MISSING_INTENT.value


# ---------------------------------------------------------------------------
# 4e. Gate — blocked by missing target
# ---------------------------------------------------------------------------


class TestBlockedByMissingTarget:
    def test_require_target_no_target_is_blocked(self):
        gate = _make_gate()
        result = gate.evaluate(
            action_level="execute",
            require_target=True,
        )
        assert result.ready is False
        assert result.blocked_by == BlockedBy.MISSING_TARGET.value

    def test_require_target_with_target_passes(self):
        gate = _make_gate()
        result = gate.evaluate(
            action_level="execute",
            require_target=True,
            target_ref="notepad.exe",
            state_continuum=_MANIFEST_CROSS_DEVICE_CONTINUUM,
        )
        # Should not be blocked by missing_target
        assert result.blocked_by != BlockedBy.MISSING_TARGET.value

    def test_require_target_false_no_target_not_blocked(self):
        gate = _make_gate()
        # require_target=False (default) — missing target is not a block cause
        result = gate.evaluate(
            action_level="execute",
            require_target=False,
            state_continuum=_MANIFEST_CROSS_DEVICE_CONTINUUM,
        )
        assert result.blocked_by != BlockedBy.MISSING_TARGET.value


# ---------------------------------------------------------------------------
# 4f. Gate — confirm-required path
# ---------------------------------------------------------------------------


class TestConfirmRequiredPath:
    def test_policy_requires_confirmation_returns_confirm_required(self):
        from core.execution_policy import ExecutionPolicy, PolicyBand

        def _fake_resolver(_):
            return ExecutionPolicy(
                policy_band=PolicyBand.BOUNDED_EXECUTE,
                risk_budget=0.4,
                action_budget=3,
                fallback_budget=2,
                allowed_executor_levels=["system_api"],
                cross_device_allowed=False,
                requires_confirmation=True,
                reason="bounded_execute requires confirmation",
            )

        gate = _make_gate(policy_resolver_fn=_fake_resolver)
        result = gate.evaluate(action_level="execute")
        assert result.ready is True
        assert result.status == ReadinessStatus.CONFIRM_REQUIRED.value
        assert result.requires_confirmation is True

    def test_hitl_manual_mode_returns_confirm_required(self):
        from core.policy.hitl_policy import HITLPolicy, HITLMode, HITLDecisionOutcome
        from core.execution_policy import ExecutionPolicy, PolicyBand

        hitl = HITLPolicy()
        hitl.mode = HITLMode.MANUAL

        def _fake_resolver(_):
            return ExecutionPolicy(
                policy_band=PolicyBand.FULL_EXECUTE,
                risk_budget=1.0,
                action_budget=-1,
                fallback_budget=3,
                allowed_executor_levels=["system_api", "uia", "gui"],
                cross_device_allowed=True,
                requires_confirmation=False,
                reason="full_execute — no policy confirmation required",
            )

        gate = _make_gate(
            policy_resolver_fn=_fake_resolver,
            hitl_policy_fn=lambda: hitl,
        )
        result = gate.evaluate(action_level="execute")
        assert result.ready is True
        assert result.status == ReadinessStatus.CONFIRM_REQUIRED.value
        assert result.requires_confirmation is True


# ---------------------------------------------------------------------------
# 4g. Gate — graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    def test_policy_resolver_raises_degrades_gracefully(self):
        def _bad_resolver(_):
            raise RuntimeError("resolver_exploded")

        gate = _make_gate(policy_resolver_fn=_bad_resolver)
        # Should not raise; should still produce a valid result
        result = gate.evaluate(action_level="execute")
        assert isinstance(result, ReadinessResult)

    def test_hitl_raises_degrades_gracefully(self):
        def _bad_hitl():
            raise RuntimeError("hitl_exploded")

        gate = _make_gate(hitl_policy_fn=_bad_hitl)
        result = gate.evaluate(action_level="execute", state_continuum=_MANIFEST_CONTINUUM)
        assert isinstance(result, ReadinessResult)

    def test_no_signals_returns_valid_result(self):
        gate = _make_gate()
        result = gate.evaluate()
        assert isinstance(result, ReadinessResult)
        assert result.ready is False  # conservative default

    def test_partial_continuum_does_not_raise(self):
        gate = _make_gate()
        result = gate.evaluate(
            action_level="execute",
            state_continuum={"phase": "manifest"},
        )
        assert isinstance(result, ReadinessResult)

    def test_malformed_continuum_does_not_raise(self):
        gate = _make_gate()
        result = gate.evaluate(
            action_level="execute",
            state_continuum={"phase": None, "runtime_domain": 12345},
        )
        assert isinstance(result, ReadinessResult)


# ---------------------------------------------------------------------------
# 5. evaluate_readiness() module-level helper
# ---------------------------------------------------------------------------


class TestEvaluateReadinessHelper:
    def setup_method(self):
        reset_readiness_gate()

    def test_delegates_to_gate(self):
        reset_readiness_gate()
        result = evaluate_readiness(action_level="observe")
        assert result.status == ReadinessStatus.OBSERVE_ONLY.value

    def test_same_result_as_direct_gate(self):
        reset_readiness_gate()
        profile = _make_profile(action_level="execute", runtime_domain="cross_device")
        direct = ExecutionReadinessGate().evaluate(
            profile, state_continuum=_MANIFEST_CROSS_DEVICE_CONTINUUM
        )
        helper = evaluate_readiness(profile, state_continuum=_MANIFEST_CROSS_DEVICE_CONTINUUM)
        assert direct.status == helper.status
        assert direct.ready == helper.ready
        assert direct.blocked_by == helper.blocked_by

    def test_singleton_is_reused(self):
        reset_readiness_gate()
        # First call: creates the singleton
        r1 = evaluate_readiness(action_level="observe")
        # Second call: reuses the singleton — result should be identical
        r2 = evaluate_readiness(action_level="observe")
        assert r1.status == r2.status
        assert r1.blocked_by == r2.blocked_by


# ---------------------------------------------------------------------------
# 6. reset_readiness_gate()
# ---------------------------------------------------------------------------


class TestResetReadinessGate:
    def test_reset_clears_singleton(self):
        # Call to ensure singleton is created
        evaluate_readiness(action_level="observe")
        # Reset
        reset_readiness_gate()
        # After reset, a new call should produce a valid result (gate is re-created)
        result = evaluate_readiness(action_level="observe")
        assert isinstance(result, ReadinessResult)
        assert result.status == ReadinessStatus.OBSERVE_ONLY.value


# ---------------------------------------------------------------------------
# 7. Serialisation stability
# ---------------------------------------------------------------------------


class TestSerialisationStability:
    def test_to_dict_all_values_json_serialisable(self):
        r = ReadinessResult(
            ready=True,
            status="ready",
            reason="test",
            requires_confirmation=False,
            policy_band="full_execute",
            blocked_by="none",
            runtime_session_id="sess-abc",
            intent_id=str(uuid.uuid4()),
            action_level="execute",
            runtime_domain="local",
            notes=["note-a", "note-b"],
        )
        d = r.to_dict()
        json.dumps(d)  # must not raise

    def test_round_trip_preserves_all_fields(self):
        intent_id = str(uuid.uuid4())
        r = ReadinessResult(
            ready=True,
            status="ready",
            reason="round-trip test",
            requires_confirmation=False,
            policy_band="bounded_execute",
            blocked_by="none",
            runtime_session_id="sess-rt",
            intent_id=intent_id,
            action_level="execute",
            runtime_domain="cross_device",
            notes=["n1"],
        )
        r2 = ReadinessResult.model_validate(r.to_dict())
        assert r2.ready == r.ready
        assert r2.status == r.status
        assert r2.policy_band == r.policy_band
        assert r2.intent_id == r.intent_id
        assert r2.notes == r.notes

    def test_blocked_result_is_serialisable(self):
        r = ReadinessResult(
            ready=False,
            status="blocked",
            reason="policy blocked",
            blocked_by="policy",
            policy_band="observe_only",
        )
        d = r.to_dict()
        assert json.dumps(d)  # must not raise
        assert d["blocked_by"] == "policy"


# ---------------------------------------------------------------------------
# 8. Integration with ExecutionIntentProfile (PR-22)
# ---------------------------------------------------------------------------


class TestIntentProfileIntegration:
    def test_gate_extracts_action_level_from_profile(self):
        profile = ExecutionIntentProfile(action_level="execute", runtime_domain="cross_device")
        gate = _make_gate()
        result = gate.evaluate(profile, state_continuum=_MANIFEST_CROSS_DEVICE_CONTINUUM)
        assert result.action_level == "execute"

    def test_gate_extracts_intent_id_from_profile(self):
        profile = ExecutionIntentProfile(action_level="execute", runtime_domain="cross_device")
        gate = _make_gate()
        result = gate.evaluate(profile, state_continuum=_MANIFEST_CROSS_DEVICE_CONTINUUM)
        assert result.intent_id == profile.intent_id

    def test_gate_extracts_session_id_from_profile(self):
        profile = ExecutionIntentProfile(
            action_level="execute",
            runtime_session_id="test-session",
            runtime_domain="cross_device",
        )
        gate = _make_gate()
        result = gate.evaluate(profile, state_continuum=_MANIFEST_CROSS_DEVICE_CONTINUUM)
        assert result.runtime_session_id == "test-session"

    def test_gate_extracts_domain_from_profile(self):
        profile = ExecutionIntentProfile(
            action_level="execute",
            runtime_domain="cross_device",
        )
        gate = _make_gate()
        result = gate.evaluate(profile, state_continuum=_MANIFEST_CROSS_DEVICE_CONTINUUM)
        assert result.runtime_domain == "cross_device"

    def test_explicit_action_level_overrides_profile(self):
        # Profile says "observe" but explicit action_level="execute" takes precedence
        profile = ExecutionIntentProfile(action_level="observe")
        gate = _make_gate()
        result = gate.evaluate(
            profile,
            action_level="execute",
            state_continuum=_MANIFEST_CROSS_DEVICE_CONTINUUM,
        )
        assert result.action_level == "execute"

    def test_build_execution_intent_profile_integrates_cleanly(self):
        profile = build_execution_intent_profile(
            _MANIFEST_CROSS_DEVICE_CONTINUUM,
            runtime_session_id="sess-001",
            source="openclawd",
        )
        gate = _make_gate()
        result = gate.evaluate(profile, state_continuum=_MANIFEST_CROSS_DEVICE_CONTINUUM)
        assert isinstance(result, ReadinessResult)
        assert result.intent_id == profile.intent_id


# ---------------------------------------------------------------------------
# 9. OpenClawd._check_readiness() integration
# ---------------------------------------------------------------------------


class TestOpenClawdCheckReadiness:
    def _make_openclawd(self):
        """Build a minimal OpenClawd instance for integration testing.

        Imports are done lazily to avoid pulling in the full Galaxy stack.
        """
        try:
            from core.openclawd import OpenClawd
            return OpenClawd.__new__(OpenClawd)
        except Exception:
            return None

    def test_check_readiness_returns_readiness_result(self):
        oc = self._make_openclawd()
        if oc is None:
            pytest.skip("OpenClawd not available")
        profile = _make_profile(action_level="execute")
        result = oc._check_readiness(profile, _MANIFEST_CONTINUUM)
        if result is None:
            pytest.skip("readiness gate unavailable in this environment")
        assert isinstance(result, ReadinessResult)

    def test_check_readiness_returns_none_when_gate_raises(self):
        oc = self._make_openclawd()
        if oc is None:
            pytest.skip("OpenClawd not available")
        with patch(
            "core.execution.readiness_gate.evaluate_readiness",
            side_effect=RuntimeError("gate_exploded"),
        ):
            result = oc._check_readiness(_make_profile(), _MANIFEST_CONTINUUM)
        assert result is None  # graceful None on error

    def test_run_execution_includes_readiness_key(self):
        """_run_execution result dict must contain the 'readiness' key (PR-23)."""
        try:
            from core.openclawd import OpenClawd
            oc = OpenClawd.__new__(OpenClawd)
        except Exception:
            pytest.skip("OpenClawd not available")

        # Patch the decision executor to avoid real execution
        mock_result = MagicMock()
        mock_result.action_taken = "noop"
        mock_result.target = None
        mock_result.success = False
        mock_result.skipped_reason = "noop"
        mock_result.metadata = {}

        mock_executor = MagicMock()
        mock_executor.execute.return_value = mock_result

        oc._get_decision_executor = lambda: mock_executor

        result_dict = oc._run_execution(_MANIFEST_CONTINUUM)
        # The 'readiness' key must be present (may be None if gate unavailable)
        assert "readiness" in result_dict
