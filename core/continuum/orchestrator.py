"""
core.continuum.orchestrator — Continuum Orchestrator
=====================================================

Runs the full continuum evaluation loop for a single request or
autonomous tick:

    perception → human_field → state_fusion → liminal_field
    → temporal_engine → decision_gate → expression_engine → return_engine

The orchestrator wires together all sub-engines in the correct order,
threads signals through, applies the return engine result, and emits
a single :class:`~core.continuum.types.ContinuumState` snapshot.

Graceful degradation
--------------------
If the continuum is disabled via ``config.flags.enabled = False``, or if
any internal stage raises an unexpected exception, the orchestrator returns
a static formless :class:`~core.continuum.types.ContinuumState` with
``degraded=True`` rather than propagating the error.

Perception input
----------------
Callers may supply a
:class:`~core.multimodal.perception_frame.PerceptionFrame` sourced from the
multimodal ingress bus.  When none is provided the orchestrator constructs a
minimal default frame (all modalities absent/missing) so that the pipeline
can still execute in a text-only environment.

Feature flags
-------------
The ``enable_continuum`` and ``debug_continuum`` keys in ``config.json``
(or equivalent runtime config dict) are respected.  Set
``enable_continuum = false`` to bypass continuum entirely; set
``debug_continuum = true`` to emit verbose per-stage log entries.

Usage::

    from core.continuum.orchestrator import ContinuumOrchestrator

    orch = ContinuumOrchestrator()
    state = orch.run(trace_id="abc123")
    print(state.phase, state.presence_intensity)

    # With a PerceptionFrame from the multimodal ingress bus:
    from core.multimodal.ingress_bus import MultimodalIngressBus
    bus = MultimodalIngressBus()
    frame = bus.build_frame()
    state = orch.run(frame=frame, trace_id="abc123", elapsed_ms=200)
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, List, Optional

from core.continuum.config import ContinuumConfig, DEFAULT_CONTINUUM_CONFIG
from core.continuum.decision_gate import DecisionGate
from core.continuum.expression_engine import ExpressionEngine
from core.continuum.human_field import HumanFieldInferrer, InteractionRhythm
from core.continuum.liminal_field import LiminalFieldEngine
from core.continuum.metrics import get_continuum_metrics
from core.continuum.return_engine import ReturnEngine
from core.continuum.state_fusion import StateFusion
from core.continuum.temporal_engine import TemporalEngine
from core.continuum.types import (
    ActionLevel,
    ContinuumPhase,
    ContinuumState,
    DecisionState,
    HumanFieldState,
    UnifiedState,
)

logger = logging.getLogger("Galaxy.Continuum.Orchestrator")

# Maximum UnifiedState history entries retained between ticks.
_HISTORY_WINDOW: int = 20


class ContinuumOrchestrator:
    """Runs the full continuum evaluation loop.

    The orchestrator is **stateful** across calls: the
    :class:`~core.continuum.temporal_engine.TemporalEngine` accumulates
    EMA-smoothed signals and dwell-guard timers between ticks.  All other
    sub-engines are stateless.

    Thread-safety: Not thread-safe.  Serialise concurrent access externally.

    Args:
        config:      Master continuum configuration.  Defaults to
                     :data:`~core.continuum.config.DEFAULT_CONTINUUM_CONFIG`.
        extra_flags: Optional dict with ``enable_continuum`` /
                     ``debug_continuum`` boolean overrides (mirrors the
                     ``config.json`` top-level keys).  These take precedence
                     over ``config.flags``.
    """

    def __init__(
        self,
        config: ContinuumConfig = DEFAULT_CONTINUUM_CONFIG,
        extra_flags: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._cfg = config
        self._extra_flags = extra_flags or {}

        # Apply top-level config.json overrides to FeatureFlags.
        _flags = config.flags
        _flag_map = {
            "enable_continuum": "enabled",
            "debug_continuum": "debug",
            "enable_perception": "enable_perception",
            "enable_human_field": "enable_human_field",
            "enable_liminal_field": "enable_liminal_field",
            "enable_decision_gate": "enable_decision_gate",
            "continuum_max_tick_ms": "max_tick_ms",
            "continuum_sampling_rate": "sampling_rate",
        }
        _updates: Dict[str, Any] = {}
        for ext_key, flag_attr in _flag_map.items():
            if ext_key in self._extra_flags:
                _updates[flag_attr] = self._extra_flags[ext_key]
        if _updates:
            _flags = _flags.model_copy(update=_updates)
        effective_cfg = config.model_copy(update={"flags": _flags})
        self._effective_cfg = effective_cfg

        # Sub-engine instances
        self._inferrer = HumanFieldInferrer(effective_cfg)
        self._fusion = StateFusion(effective_cfg)
        self._liminal = LiminalFieldEngine(effective_cfg)
        self._temporal = TemporalEngine(effective_cfg)
        self._decision_gate = DecisionGate(effective_cfg)
        self._expression = ExpressionEngine(effective_cfg)
        self._return_engine = ReturnEngine(effective_cfg)

        # Rolling history of UnifiedState snapshots (newest last).
        self._history: List[UnifiedState] = []

        # Last successfully computed state; used when a tick is sampled-out.
        self._last_state: Optional[ContinuumState] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        frame: Optional[Any] = None,
        *,
        trace_id: Optional[str] = None,
        elapsed_ms: Optional[float] = None,
        rhythm: Optional[InteractionRhythm] = None,
        world_context: Optional[Dict[str, Any]] = None,
    ) -> ContinuumState:
        """Execute one full continuum evaluation cycle.

        Args:
            frame:         Optional :class:`~core.multimodal.perception_frame.PerceptionFrame`
                           sourced from the multimodal ingress bus.  When
                           ``None``, a minimal default frame is constructed.
            trace_id:      Correlation ID propagated from the calling request.
                           Written into :attr:`~core.continuum.types.ContinuumState.trace_id`.
            elapsed_ms:    Milliseconds since the previous tick/request, used
                           by the return engine to detect timeouts.  When
                           ``None``, defaults to ``0``.
            rhythm:        Optional :class:`~core.continuum.human_field.InteractionRhythm`
                           summary forwarded to the human-field inferrer.
            world_context: Optional world/context dict forwarded to state
                           fusion.  Recognised keys: ``context_utility``,
                           ``urgency``, ``action_risk``, ``uncertainty``.

        Returns:
            A :class:`~core.continuum.types.ContinuumState` snapshot.
            If the continuum is disabled or an unrecoverable error occurs,
            the snapshot has ``degraded=True`` and
            ``phase=ContinuumPhase.FORMLESS``.
        """
        if not self._effective_cfg.flags.enabled:
            return ContinuumState.formless_default()

        flags = self._effective_cfg.flags
        metrics = get_continuum_metrics()

        # ------------------------------------------------------------------
        # Sampling guardrail: skip tick based on sampling_rate.
        # ------------------------------------------------------------------
        if flags.sampling_rate < 1.0:
            if random.random() >= flags.sampling_rate:
                fallback = self._last_state if self._last_state is not None else ContinuumState.formless_default()
                metrics.record_tick(
                    phase=fallback.phase.value,
                    elapsed_ms=0.0,
                    skipped=True,
                )
                if flags.debug:
                    logger.debug(
                        "Continuum tick SKIPPED (sampling) | trace=%s sampling_rate=%.3f",
                        trace_id,
                        flags.sampling_rate,
                    )
                return fallback

        t_start = time.monotonic()

        try:
            result = self._run_pipeline(
                frame=frame,
                trace_id=trace_id,
                elapsed_ms=elapsed_ms or 0.0,
                rhythm=rhythm,
                world_context=world_context,
            )
        except Exception as exc:
            logger.error(
                "ContinuumOrchestrator.run failed (trace_id=%s): %s",
                trace_id,
                exc,
                exc_info=True,
            )
            elapsed_ms_tick = (time.monotonic() - t_start) * 1_000
            metrics.record_tick(
                phase="formless",
                elapsed_ms=elapsed_ms_tick,
                degraded=True,
            )
            return ContinuumState(
                phase=ContinuumPhase.FORMLESS,
                presence_intensity=0.0,
                degraded=True,
                degrade_reason="continuum_internal_error",
                trace_id=trace_id or ContinuumState.__fields__["trace_id"].default_factory(),
                metadata={"error": str(exc)},
            )

        elapsed_ms_tick = (time.monotonic() - t_start) * 1_000

        # ------------------------------------------------------------------
        # Time-budget guardrail: degrade if tick exceeded max_tick_ms.
        # ------------------------------------------------------------------
        budget_exceeded = False
        if flags.max_tick_ms > 0.0 and elapsed_ms_tick > flags.max_tick_ms:
            logger.warning(
                "Continuum tick budget exceeded | trace=%s elapsed_ms=%.1f max_ms=%.1f — degrading to formless",
                trace_id,
                elapsed_ms_tick,
                flags.max_tick_ms,
            )
            budget_exceeded = True
            degraded_result = ContinuumState.degraded_fallback("tick_budget_exceeded")
            if trace_id:
                degraded_result = degraded_result.model_copy(update={"trace_id": trace_id})
            metrics.record_tick(
                phase="formless",
                elapsed_ms=elapsed_ms_tick,
                degraded=True,
                budget_exceeded=True,
            )
            return degraded_result

        # ------------------------------------------------------------------
        # Structured debug logging.
        # ------------------------------------------------------------------
        if flags.debug:
            logger.debug(
                "Continuum tick | trace=%s phase=%s intensity=%.3f "
                "coherence=%.3f action=%s degraded=%s elapsed_ms=%.2f",
                trace_id,
                result.phase.value,
                result.presence_intensity,
                result.coherence,
                result.decision.action_level.value,
                result.degraded,
                elapsed_ms_tick,
            )

        metrics.record_tick(
            phase=result.phase.value,
            elapsed_ms=elapsed_ms_tick,
            degraded=result.degraded,
            budget_exceeded=budget_exceeded,
        )
        self._last_state = result
        return result

    def reset(self) -> None:
        """Reset all stateful sub-engines to the pristine formless state.

        Useful between isolated tests or when a session ends.
        """
        self._temporal.reset()
        self._history.clear()
        self._last_state = None

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    def _run_pipeline(
        self,
        frame: Optional[Any],
        trace_id: Optional[str],
        elapsed_ms: float,
        rhythm: Optional[InteractionRhythm],
        world_context: Optional[Dict[str, Any]],
    ) -> ContinuumState:
        """Execute the ordered pipeline stages and return a ContinuumState."""
        flags = self._effective_cfg.flags
        metrics = get_continuum_metrics()
        debug = flags.debug

        # Stage 1 – Perception: obtain or construct a PerceptionFrame.
        _t = time.monotonic()
        if flags.enable_perception:
            resolved_frame = self._resolve_frame(frame)
        else:
            resolved_frame = self._resolve_frame(None)  # always use minimal default
        _stage_ms = (time.monotonic() - _t) * 1_000
        metrics.record_stage("perception", _stage_ms, skipped=not flags.enable_perception)
        if debug:
            logger.debug(
                "Continuum stage perception | trace=%s skipped=%s elapsed_ms=%.2f",
                trace_id, not flags.enable_perception, _stage_ms,
            )

        # Stage 2 – Human Field: infer HumanFieldState from perception.
        _t = time.monotonic()
        if flags.enable_human_field:
            human_state = self._inferrer.infer(resolved_frame, rhythm=rhythm)
        else:
            human_state = HumanFieldState()
        _stage_ms = (time.monotonic() - _t) * 1_000
        metrics.record_stage("human_field", _stage_ms, skipped=not flags.enable_human_field)
        if debug:
            logger.debug(
                "Continuum stage human_field | trace=%s skipped=%s attention=%.3f intent=%.3f elapsed_ms=%.2f",
                trace_id, not flags.enable_human_field,
                human_state.attention, human_state.intent_probability, _stage_ms,
            )

        # Stage 3 – State Fusion: merge human state + world context + history.
        history_window = self._history[-5:]
        _t = time.monotonic()
        unified_state = self._fusion.fuse(
            human_state,
            world=world_context,
            history=history_window or None,
        )
        _stage_ms = (time.monotonic() - _t) * 1_000
        metrics.record_stage("state_fusion", _stage_ms)
        if debug:
            logger.debug(
                "Continuum stage state_fusion | trace=%s phase_candidate=%s confidence=%.3f elapsed_ms=%.2f",
                trace_id, unified_state.phase_candidate.value,
                unified_state.candidate_confidence, _stage_ms,
            )

        # Stage 4 – Liminal Field: compute metrics and enrich unified state.
        _t = time.monotonic()
        if flags.enable_liminal_field:
            liminal_metrics = self._liminal.compute(unified_state, history=history_window or None)
            unified_state = self._liminal.enrich_unified(unified_state, liminal_metrics)
        _stage_ms = (time.monotonic() - _t) * 1_000
        metrics.record_stage("liminal_field", _stage_ms, skipped=not flags.enable_liminal_field)
        if debug:
            logger.debug(
                "Continuum stage liminal_field | trace=%s skipped=%s elapsed_ms=%.2f",
                trace_id, not flags.enable_liminal_field, _stage_ms,
            )

        # Stage 5 – Temporal Engine: produce stable ContinuumState.
        _t = time.monotonic()
        continuum_state = self._temporal.tick(unified_state)
        _stage_ms = (time.monotonic() - _t) * 1_000
        metrics.record_stage("temporal_engine", _stage_ms)
        if debug:
            logger.debug(
                "Continuum stage temporal_engine | trace=%s phase=%s intensity=%.3f elapsed_ms=%.2f",
                trace_id, continuum_state.phase.value,
                continuum_state.presence_intensity, _stage_ms,
            )

        # Stage 6 – Decision Gate: evaluate whether / how strongly to act.
        _t = time.monotonic()
        if flags.enable_decision_gate:
            decision_state = self._decision_gate.evaluate(unified_state)
        else:
            decision_state = DecisionState(action_level=ActionLevel.OBSERVE)
        _stage_ms = (time.monotonic() - _t) * 1_000
        metrics.record_stage("decision_gate", _stage_ms, skipped=not flags.enable_decision_gate)
        if debug:
            logger.debug(
                "Continuum stage decision_gate | trace=%s skipped=%s action=%s score=%.3f elapsed_ms=%.2f",
                trace_id, not flags.enable_decision_gate,
                decision_state.action_level.value, decision_state.should_act_score, _stage_ms,
            )
        continuum_state = continuum_state.model_copy(
            update={"decision": decision_state}
        )

        # Stage 7 – Expression Engine: derive abstract expression parameters.
        _t = time.monotonic()
        expression_state = self._expression.compute(continuum_state)
        _stage_ms = (time.monotonic() - _t) * 1_000
        metrics.record_stage("expression_engine", _stage_ms)
        if debug:
            logger.debug(
                "Continuum stage expression_engine | trace=%s form=%s spatial=%s elapsed_ms=%.2f",
                trace_id, expression_state.form_signature.value,
                expression_state.spatial_presence.value, _stage_ms,
            )
        continuum_state = continuum_state.model_copy(
            update={"expression": expression_state}
        )

        # Stage 8 – Return Engine: decide whether to retreat toward formless.
        _t = time.monotonic()
        return_result = self._return_engine.evaluate(
            continuum_state,
            elapsed_ms=elapsed_ms,
            decision_score=decision_state.should_act_score,
        )
        _stage_ms = (time.monotonic() - _t) * 1_000
        metrics.record_stage("return_engine", _stage_ms)
        if return_result.should_return and return_result.next_phase is not None:
            if debug:
                logger.debug(
                    "Continuum return_engine triggered | trace=%s reason=%s next_phase=%s elapsed_ms=%.2f",
                    trace_id,
                    getattr(return_result, "reason", ""),
                    return_result.next_phase.value,
                    _stage_ms,
                )
            continuum_state = continuum_state.model_copy(
                update={"phase": return_result.next_phase}
            )

        # Attach the caller-supplied trace_id (overrides the auto-generated one).
        if trace_id:
            continuum_state = continuum_state.model_copy(
                update={"trace_id": trace_id}
            )

        # Update rolling history.
        self._history.append(unified_state)
        if len(self._history) > _HISTORY_WINDOW:
            self._history.pop(0)

        return continuum_state

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_frame(frame: Optional[Any]) -> Any:
        """Return *frame* unchanged, or construct a minimal default frame.

        A minimal default ``PerceptionFrame`` has all modalities absent/missing
        and safe-fallback quality flags.  The human-field inferrer handles
        this gracefully, producing conservative mid-range values.
        """
        if frame is not None:
            return frame

        try:
            from core.multimodal.perception_frame import PerceptionFrame
            return PerceptionFrame()
        except Exception:
            # If the perception_frame module is not available (e.g. minimal
            # test environment), return a sentinel object with the minimum
            # interface used by HumanFieldInferrer.
            return _MinimalFrame()


# ---------------------------------------------------------------------------
# Minimal fallback frame (used when core.multimodal is unavailable)
# ---------------------------------------------------------------------------


class _MinimalFrame:
    """Sentinel frame for environments where core.multimodal is not installed.

    HumanFieldInferrer accesses ``frame.audio``, ``frame.video``,
    ``frame.system``, ``frame.audio_quality.is_usable``,
    ``frame.video_quality.is_usable``, ``frame.system_quality.is_usable``,
    and ``frame.wall_clock``.
    """

    class _FakeQuality:
        is_usable: bool = False
        confidence: float = 0.0

    audio: Optional[Any] = None
    video: Optional[Any] = None
    system: Optional[Any] = None
    audio_quality: _FakeQuality = _FakeQuality()
    video_quality: _FakeQuality = _FakeQuality()
    system_quality: _FakeQuality = _FakeQuality()
    wall_clock: float = 0.0

    def __init__(self) -> None:
        import time as _t
        self.wall_clock = _t.time()
