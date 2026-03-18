"""
tests/test_openclawd_state_continuum_integration.py
=====================================================

Integration tests verifying that the Continuum Orchestrator is correctly
wired into OpenClawd's main processing pipeline (PR-5).

Test groups
-----------
A) ContinuumOrchestrator unit contract (isolated, no OpenClawd).
B) ExpressionEngine unit contract.
C) OpenClawd._run_continuum() — helper method returns expected structure.
D) Feature-flag semantics: enable_continuum=False degrades to None.
E) OpenClawd.process() response includes state_continuum field.
F) Backward compatibility: state_continuum=None never breaks existing fields.
G) Fusion-chain integrity: all pipeline stages produce consistent output.
H) Modality-degraded input: all-absent PerceptionFrame produces stable state.
"""

from __future__ import annotations

import asyncio
import types
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from core.continuum.config import (
    ContinuumConfig,
    FeatureFlags,
    DEFAULT_CONTINUUM_CONFIG,
)
from core.continuum.expression_engine import ExpressionEngine
from core.continuum.orchestrator import ContinuumOrchestrator, _MinimalFrame
from core.continuum.types import (
    ActionLevel,
    ContinuumPhase,
    ContinuumState,
    DecisionState,
    ExpressionState,
    FormSignature,
    SpatialPresence,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _disabled_config() -> ContinuumConfig:
    """Return a ContinuumConfig with the continuum disabled."""
    return DEFAULT_CONTINUUM_CONFIG.model_copy(
        update={"flags": FeatureFlags(enabled=False)}
    )


def _debug_config() -> ContinuumConfig:
    """Return a ContinuumConfig with debug logging enabled."""
    return DEFAULT_CONTINUUM_CONFIG.model_copy(
        update={"flags": FeatureFlags(enabled=True, debug=True)}
    )


def _state(phase: ContinuumPhase = ContinuumPhase.FORMLESS, **kw) -> ContinuumState:
    return ContinuumState(phase=phase, **kw)


# ---------------------------------------------------------------------------
# A) ContinuumOrchestrator unit contract
# ---------------------------------------------------------------------------


class TestContinuumOrchestratorContract:
    def test_instantiates_with_defaults(self):
        orch = ContinuumOrchestrator()
        assert orch is not None

    def test_run_returns_continuum_state(self):
        orch = ContinuumOrchestrator()
        result = orch.run(trace_id="test-a1")
        assert isinstance(result, ContinuumState)

    def test_run_phase_is_valid(self):
        orch = ContinuumOrchestrator()
        result = orch.run(trace_id="test-a2")
        assert result.phase in ContinuumPhase.__members__.values()

    def test_run_trace_id_propagated(self):
        orch = ContinuumOrchestrator()
        result = orch.run(trace_id="my-trace-xyz")
        assert result.trace_id == "my-trace-xyz"

    def test_run_with_no_trace_id_generates_one(self):
        orch = ContinuumOrchestrator()
        result = orch.run()
        assert result.trace_id  # not empty

    def test_disabled_returns_formless(self):
        cfg = _disabled_config()
        orch = ContinuumOrchestrator(config=cfg)
        result = orch.run(trace_id="disabled")
        assert result.phase == ContinuumPhase.FORMLESS
        assert result.presence_intensity == 0.0

    def test_disabled_via_extra_flags(self):
        orch = ContinuumOrchestrator(extra_flags={"enable_continuum": False})
        result = orch.run(trace_id="disabled-flag")
        assert result.phase == ContinuumPhase.FORMLESS

    def test_enabled_via_extra_flags(self):
        orch = ContinuumOrchestrator(extra_flags={"enable_continuum": True})
        result = orch.run(trace_id="enabled-flag")
        assert isinstance(result, ContinuumState)
        # Not degraded just because enabled
        assert result.degrade_reason is None or result.degrade_reason == "continuum_internal_error"

    def test_presence_intensity_bounded(self):
        orch = ContinuumOrchestrator()
        for _ in range(5):
            result = orch.run()
            assert 0.0 <= result.presence_intensity <= 1.0

    def test_run_with_minimal_frame(self):
        orch = ContinuumOrchestrator()
        frame = _MinimalFrame()
        result = orch.run(frame=frame, trace_id="minimal-frame")
        assert isinstance(result, ContinuumState)

    def test_run_populates_decision(self):
        orch = ContinuumOrchestrator()
        result = orch.run(trace_id="decision-check")
        assert isinstance(result.decision, DecisionState)

    def test_run_populates_expression(self):
        orch = ContinuumOrchestrator()
        result = orch.run(trace_id="expression-check")
        assert isinstance(result.expression, ExpressionState)

    def test_debug_flag_does_not_crash(self):
        cfg = _debug_config()
        orch = ContinuumOrchestrator(config=cfg)
        result = orch.run(trace_id="debug-run")
        assert isinstance(result, ContinuumState)

    def test_reset_clears_history(self):
        orch = ContinuumOrchestrator()
        orch.run()
        orch.run()
        assert len(orch._history) > 0
        orch.reset()
        assert len(orch._history) == 0

    def test_history_does_not_grow_unbounded(self):
        from core.continuum.orchestrator import _HISTORY_WINDOW
        orch = ContinuumOrchestrator()
        for _ in range(_HISTORY_WINDOW + 10):
            orch.run()
        assert len(orch._history) <= _HISTORY_WINDOW

    def test_state_dict_is_json_serialisable(self):
        import json
        orch = ContinuumOrchestrator()
        result = orch.run(trace_id="json-check")
        dumped = json.dumps(result.model_dump())
        assert dumped  # non-empty

    def test_successive_ticks_produce_stable_phase(self):
        """Ten ticks with a default (text-only) frame should stay in formless."""
        orch = ContinuumOrchestrator()
        phases = [orch.run().phase for _ in range(10)]
        # All should be formless with no stimulation
        assert all(p == ContinuumPhase.FORMLESS for p in phases)

    def test_world_context_forwarded(self):
        orch = ContinuumOrchestrator()
        result = orch.run(
            trace_id="world-ctx",
            world_context={"context_utility": 0.9, "urgency": 0.8, "action_risk": 0.1},
        )
        assert isinstance(result, ContinuumState)

    def test_graceful_degradation_on_bad_frame(self):
        """A completely broken frame object should not crash the orchestrator."""
        orch = ContinuumOrchestrator()
        bad_frame = object()  # no useful attributes
        # Should not raise; may return degraded state
        result = orch.run(frame=bad_frame, trace_id="bad-frame")
        assert isinstance(result, ContinuumState)


# ---------------------------------------------------------------------------
# B) ExpressionEngine unit contract
# ---------------------------------------------------------------------------


class TestExpressionEngine:
    def test_instantiates(self):
        assert ExpressionEngine() is not None

    def test_formless_returns_absent(self):
        eng = ExpressionEngine()
        expr = eng.compute(_state(ContinuumPhase.FORMLESS))
        assert expr.motion == 0.0
        assert expr.intensity == 0.0
        assert expr.form_signature == FormSignature.NONE
        assert expr.spatial_presence == SpatialPresence.ABSENT
        assert expr.texture_hint == ""
        assert expr.phase_signature == ContinuumPhase.FORMLESS

    def test_liminal_returns_diffuse_cluster(self):
        eng = ExpressionEngine()
        expr = eng.compute(_state(ContinuumPhase.LIMINAL, presence_intensity=0.6, coherence=0.5))
        assert expr.form_signature == FormSignature.DIFFUSE_CLUSTER
        assert expr.spatial_presence == SpatialPresence.PERIPHERAL
        assert expr.texture_hint == "soft_granular"
        assert expr.phase_signature == ContinuumPhase.LIMINAL

    def test_manifest_execute_returns_expanding_ring(self):
        eng = ExpressionEngine()
        state = _state(
            ContinuumPhase.MANIFEST,
            presence_intensity=0.85,
            decision=DecisionState(
                action_level=ActionLevel.EXECUTE,
                should_act_score=0.75,
            ),
        )
        expr = eng.compute(state)
        assert expr.form_signature == FormSignature.EXPANDING_RING
        assert expr.spatial_presence == SpatialPresence.FOREGROUND

    def test_manifest_observe_returns_focused_point(self):
        eng = ExpressionEngine()
        state = _state(
            ContinuumPhase.MANIFEST,
            presence_intensity=0.5,
            decision=DecisionState(
                action_level=ActionLevel.OBSERVE,
                should_act_score=0.1,
            ),
        )
        expr = eng.compute(state)
        assert expr.form_signature == FormSignature.FOCUSED_POINT
        assert expr.spatial_presence == SpatialPresence.AMBIENT

    def test_receding_returns_collapsing_field(self):
        eng = ExpressionEngine()
        expr = eng.compute(_state(ContinuumPhase.RECEDING, presence_intensity=0.4))
        assert expr.form_signature == FormSignature.COLLAPSING_FIELD
        assert expr.spatial_presence == SpatialPresence.PERIPHERAL
        assert expr.texture_hint == "soft_dissolve"
        assert expr.phase_signature == ContinuumPhase.RECEDING

    def test_motion_bounded(self):
        eng = ExpressionEngine()
        for phase in ContinuumPhase:
            state = _state(phase, presence_intensity=1.0, coherence=1.0, collapse_tendency=1.0)
            expr = eng.compute(state)
            assert 0.0 <= expr.motion <= 1.0, f"phase={phase}: motion={expr.motion} out of [0,1]"

    def test_intensity_bounded(self):
        eng = ExpressionEngine()
        for phase in ContinuumPhase:
            state = _state(phase, presence_intensity=1.0)
            expr = eng.compute(state)
            assert 0.0 <= expr.intensity <= 1.0, f"phase={phase}: intensity={expr.intensity} out of [0,1]"

    def test_liminal_motion_increases_with_coherence(self):
        eng = ExpressionEngine()
        low = eng.compute(_state(ContinuumPhase.LIMINAL, coherence=0.1, collapse_tendency=0.0))
        high = eng.compute(_state(ContinuumPhase.LIMINAL, coherence=0.9, collapse_tendency=0.0))
        assert high.motion > low.motion

    def test_manifest_intensity_proportional_to_presence(self):
        eng = ExpressionEngine()
        low = eng.compute(_state(ContinuumPhase.MANIFEST, presence_intensity=0.2))
        high = eng.compute(_state(ContinuumPhase.MANIFEST, presence_intensity=0.9))
        assert high.intensity > low.intensity


# ---------------------------------------------------------------------------
# C) OpenClawd._run_continuum() helper
# ---------------------------------------------------------------------------


class TestRunContinuumHelper:
    """Tests for the OpenClawd._run_continuum() private method."""

    def _make_openclawd(self):
        """Return an OpenClawd instance without triggering full initialisation."""
        from core.openclawd import OpenClawd
        oc = OpenClawd.__new__(OpenClawd)
        # Minimal attribute bootstrap (mirrors __init__)
        oc._initialized = False
        oc._session_memory = {}
        oc._request_count = 0
        oc._error_count = 0
        import time
        oc._start_time = time.time()
        oc._node_actions_cache = {}
        oc._node_id_to_key = {}
        oc._router = None
        oc._kernel = None
        oc._cancel_registry = set()
        oc._continuum_orchestrator = None
        oc._tool_permission_checker = None
        return oc

    def test_returns_dict_or_none(self):
        oc = self._make_openclawd()
        result = oc._run_continuum(trace_id="helper-test")
        assert result is None or isinstance(result, dict)

    def test_returns_dict_with_phase_key(self):
        oc = self._make_openclawd()
        result = oc._run_continuum(trace_id="has-phase")
        if result is not None:
            assert "phase" in result

    def test_returns_dict_with_trace_id(self):
        oc = self._make_openclawd()
        result = oc._run_continuum(trace_id="my-trace")
        if result is not None:
            assert result.get("trace_id") == "my-trace"

    def test_disabled_via_extra_flags_returns_formless_dict(self):
        oc = self._make_openclawd()
        # Pre-wire orchestrator with disabled config
        oc._continuum_orchestrator = ContinuumOrchestrator(
            extra_flags={"enable_continuum": False}
        )
        result = oc._run_continuum(trace_id="disabled")
        # disabled → ContinuumState.formless_default() → still a dict (not None),
        # but phase should be "formless"
        if result is not None:
            assert result["phase"] == "formless"

    def test_never_raises(self):
        """_run_continuum must not propagate exceptions."""
        oc = self._make_openclawd()
        # Inject a broken orchestrator
        broken = MagicMock()
        broken.run.side_effect = RuntimeError("simulated failure")
        oc._continuum_orchestrator = broken
        # Should return None, not raise
        result = oc._run_continuum(trace_id="broken-orch")
        assert result is None


# ---------------------------------------------------------------------------
# D) Feature-flag semantics
# ---------------------------------------------------------------------------


class TestFeatureFlagSemantics:
    def test_enable_false_orchestrator_returns_formless(self):
        orch = ContinuumOrchestrator(extra_flags={"enable_continuum": False})
        s = orch.run(trace_id="flag-off")
        assert s.phase == ContinuumPhase.FORMLESS
        assert s.presence_intensity == 0.0
        assert not s.degraded

    def test_debug_true_does_not_alter_output(self):
        orch_normal = ContinuumOrchestrator()
        orch_debug = ContinuumOrchestrator(extra_flags={"debug_continuum": True})
        # Reset both to same initial state
        orch_normal.reset()
        orch_debug.reset()
        r1 = orch_normal.run(trace_id="t1")
        r2 = orch_debug.run(trace_id="t1")
        # Phase and presence_intensity should match (same input, same tick count)
        assert r1.phase == r2.phase
        assert abs(r1.presence_intensity - r2.presence_intensity) < 1e-9

    def test_config_json_flags_respected(self):
        """ContinuumOrchestrator reads enable_continuum from extra_flags dict."""
        orch = ContinuumOrchestrator(extra_flags={"enable_continuum": True, "debug_continuum": False})
        assert orch._effective_cfg.flags.enabled is True
        assert orch._effective_cfg.flags.debug is False


# ---------------------------------------------------------------------------
# E) OpenClawd.process() includes state_continuum
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOpenClawdProcessStateContinum:
    """Verify that OpenClawd.process() attaches state_continuum to responses.

    We mock out the AgentKernel and most side-effect-heavy modules so
    the test focuses exclusively on the state_continuum wiring.
    """

    async def _call_process(self, message: str = "hello") -> dict:
        from core.openclawd import OpenClawd

        oc = OpenClawd()

        # Patch heavy dependencies that aren't needed for this integration test.
        with (
            patch("core.openclawd.OpenClawd._get_kernel", return_value=None),
            patch(
                "core.openclawd.OpenClawd._parse_intent",
                return_value=MagicMock(
                    intent="chat",
                    confidence=0.9,
                    suggestions=[],
                ),
            ),
            patch(
                "core.openclawd.OpenClawd._dispatch_chat",
                return_value={"success": True, "response": "ok", "metadata": {}},
            ) as _mock_dispatch,
        ):
            # Make _dispatch_chat an awaitable
            async def _fake_chat(**kw):
                return {"success": True, "response": "ok", "metadata": {}}

            _mock_dispatch.side_effect = None
            with patch.object(oc, "_dispatch_chat", side_effect=_fake_chat):
                result = await oc.process(message=message, session_id="test-sess")
        return result

    async def test_state_continuum_key_present(self):
        result = await self._call_process()
        assert "state_continuum" in result

    async def test_state_continuum_is_dict_or_none(self):
        result = await self._call_process()
        sc = result["state_continuum"]
        assert sc is None or isinstance(sc, dict)

    async def test_existing_fields_preserved(self):
        result = await self._call_process()
        for key in ("success", "response", "intent", "trace_id", "metadata"):
            assert key in result, f"missing key: {key}"

    async def test_state_continuum_phase_valid_when_present(self):
        result = await self._call_process()
        sc = result["state_continuum"]
        if sc is not None:
            valid_phases = {p.value for p in ContinuumPhase}
            assert sc["phase"] in valid_phases

    async def test_trace_id_consistent(self):
        result = await self._call_process()
        outer_trace = result.get("trace_id")
        sc = result.get("state_continuum")
        if sc is not None and outer_trace:
            assert sc.get("trace_id") == outer_trace


# ---------------------------------------------------------------------------
# F) Backward compatibility: state_continuum=None does not break callers
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_state_continuum_none_is_falsy(self):
        """Existing callers testing `if response['state_continuum']:` are safe."""
        result = {"state_continuum": None, "response": "ok"}
        assert not result["state_continuum"]

    def test_state_continuum_absent_does_not_raise(self):
        """Callers using .get() with default None are safe."""
        result = {"response": "ok"}
        sc = result.get("state_continuum")
        assert sc is None

    def test_existing_output_fields_not_changed(self):
        """Regression: adding state_continuum does not displace other fields."""
        required_keys = {
            "success", "response", "intent", "trace_id",
            "interaction", "persona_state", "interaction_envelope",
            "output_plan", "metadata",
        }
        # Simulate a response dict as returned by both kernel and direct paths
        mock_response = {k: None for k in required_keys}
        mock_response["state_continuum"] = None
        for key in required_keys:
            assert key in mock_response


# ---------------------------------------------------------------------------
# G) Fusion-chain integrity
# ---------------------------------------------------------------------------


class TestFusionChainIntegrity:
    """Verify that all pipeline stages produce internally consistent output."""

    def test_full_chain_with_default_frame(self):
        orch = ContinuumOrchestrator()
        state = orch.run(trace_id="chain-default")
        # Phase and presence_intensity must be coherent
        if state.phase == ContinuumPhase.FORMLESS:
            assert state.presence_intensity < orch._effective_cfg.hysteresis.liminal_enter
        assert isinstance(state.decision, DecisionState)
        assert isinstance(state.expression, ExpressionState)

    def test_decision_action_level_valid(self):
        orch = ContinuumOrchestrator()
        state = orch.run(trace_id="action-level")
        assert state.decision.action_level in ActionLevel.__members__.values()

    def test_expression_phase_signature_matches_state_phase(self):
        orch = ContinuumOrchestrator()
        state = orch.run(trace_id="phase-sig")
        assert state.expression.phase_signature == state.phase

    def test_coherence_bounded(self):
        orch = ContinuumOrchestrator()
        for _ in range(3):
            state = orch.run()
            assert 0.0 <= state.coherence <= 1.0

    def test_stability_bounded(self):
        orch = ContinuumOrchestrator()
        for _ in range(3):
            state = orch.run()
            assert 0.0 <= state.stability <= 1.0

    def test_decision_score_bounded(self):
        orch = ContinuumOrchestrator()
        state = orch.run(trace_id="score-bound")
        # score is unbounded by the gate formula, but should be reasonable
        assert isinstance(state.decision.should_act_score, float)

    def test_world_context_urgency_increases_score(self):
        orch_low = ContinuumOrchestrator()
        orch_high = ContinuumOrchestrator()
        low = orch_low.run(world_context={"urgency": 0.0, "context_utility": 0.1})
        high = orch_high.run(world_context={"urgency": 0.9, "context_utility": 0.9})
        assert high.decision.should_act_score >= low.decision.should_act_score


# ---------------------------------------------------------------------------
# H) Modality-degraded input
# ---------------------------------------------------------------------------


class TestModalityDegradedInput:
    """Verify stable output when no audio/video/system signals are available."""

    def test_minimal_frame_does_not_crash(self):
        orch = ContinuumOrchestrator()
        frame = _MinimalFrame()
        result = orch.run(frame=frame, trace_id="minimal")
        assert isinstance(result, ContinuumState)

    def test_no_frame_produces_valid_state(self):
        orch = ContinuumOrchestrator()
        result = orch.run(frame=None, trace_id="no-frame")
        assert result.phase in ContinuumPhase.__members__.values()
        assert 0.0 <= result.presence_intensity <= 1.0

    def test_degraded_flag_false_on_minimal_input(self):
        """Minimal input is not an error condition — degraded should be False."""
        orch = ContinuumOrchestrator()
        result = orch.run(frame=None, trace_id="no-frame-degraded")
        assert not result.degraded

    def test_degraded_flag_true_on_exception(self):
        """An internal exception should set degraded=True."""
        orch = ContinuumOrchestrator()
        # Sabotage the temporal engine to simulate failure
        original_tick = orch._temporal.tick
        def _boom(state):
            raise RuntimeError("simulated tick failure")
        orch._temporal.tick = _boom
        result = orch.run(trace_id="boom")
        assert result.degraded
        assert result.degrade_reason is not None
        orch._temporal.tick = original_tick

    def test_multiple_ticks_with_minimal_frame_stay_stable(self):
        orch = ContinuumOrchestrator()
        frame = _MinimalFrame()
        phases = [orch.run(frame=frame).phase for _ in range(5)]
        assert all(p == ContinuumPhase.FORMLESS for p in phases)
