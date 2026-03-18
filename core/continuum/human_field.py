"""
core.continuum.human_field — Human Field Inference Engine
=========================================================

Infers a :class:`HumanFieldState` from a :class:`PerceptionFrame` and
optional :class:`InteractionRhythm` data.

All modalities inside the ``PerceptionFrame`` are optional.  When a
modality is absent or marked non-usable the inferrer degrades gracefully
to conservative mid-range defaults rather than crashing or returning
extreme values.

Signal derivation summary
-------------------------
- ``attention``              — weighted composite of audio energy/speaking,
                               video face-presence, and system screen-activity.
- ``focus_level``            — sustained-engagement proxy: audio speaking
                               consistency, screen-activity, and input rhythm.
- ``fatigue``                — low-activity / long-session proxy; grows with
                               session age and idle time.
- ``intent_probability``     — intent-formation signal: active speech, input
                               bursts, and screen engagement.
- ``interruption_sensitivity`` — derived from focus_level, speaking state,
                               and fatigue.

Usage::

    from core.continuum.human_field import HumanFieldInferrer, InteractionRhythm
    from core.multimodal.perception_frame import PerceptionFrame

    inferrer = HumanFieldInferrer()
    hf = inferrer.infer(frame)

    # With rhythm history:
    rhythm = InteractionRhythm(input_event_rate=0.6, session_age_s=900.0)
    hf = inferrer.infer(frame, rhythm=rhythm)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.continuum.config import ContinuumConfig, DEFAULT_CONTINUUM_CONFIG
from core.continuum.types import HumanFieldState
from core.multimodal.perception_frame import PerceptionFrame


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Return *v* clamped to [*lo*, *hi*]."""
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# Interaction rhythm data
# ---------------------------------------------------------------------------


@dataclass
class InteractionRhythm:
    """Lightweight interaction-history summary for rhythm-based inference.

    Callers are responsible for maintaining and updating this object;
    the inferrer treats it as an immutable snapshot.

    All numeric fields are in [0, 1] unless noted.
    """

    input_event_rate: float = 0.0
    """Normalised input events per second.  0 = idle, 1 = rapid burst."""

    session_age_s: float = 0.0
    """Seconds elapsed since the current task session began (unbounded)."""

    idle_duration_s: float = 0.0
    """Seconds since the last detected input event (unbounded)."""

    recent_burst: bool = False
    """True when input events spiked noticeably in the last few seconds."""


# ---------------------------------------------------------------------------
# Inferrer
# ---------------------------------------------------------------------------


class HumanFieldInferrer:
    """Infers :class:`HumanFieldState` from a :class:`PerceptionFrame`.

    The inferrer is **stateless**: it does not accumulate history across
    calls.  Temporal smoothing is the responsibility of the
    :class:`~core.continuum.temporal_engine.TemporalEngine`.

    Args:
        config: Continuum configuration.  Defaults to
            :data:`~core.continuum.config.DEFAULT_CONTINUUM_CONFIG`.
    """

    def __init__(
        self, config: ContinuumConfig = DEFAULT_CONTINUUM_CONFIG
    ) -> None:
        self._cfg = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def infer(
        self,
        frame: PerceptionFrame,
        rhythm: Optional[InteractionRhythm] = None,
    ) -> HumanFieldState:
        """Derive a :class:`HumanFieldState` snapshot from *frame*.

        Missing or non-usable modalities degrade gracefully: each signal
        falls back to a conservative mid-range value rather than raising.

        Args:
            frame:  Unified multimodal perception frame.
            rhythm: Optional interaction-rhythm summary.  When ``None``,
                    rhythm-dependent fields use neutral defaults.

        Returns:
            Un-smoothed :class:`HumanFieldState` snapshot.  Callers
            should pass the result through the
            :class:`~core.continuum.temporal_engine.TemporalEngine` before
            consuming it in downstream decisions.
        """
        # Extract usable sub-signals (None when modality is absent/degraded).
        audio = frame.audio if frame.audio_quality.is_usable else None
        video = frame.video if frame.video_quality.is_usable else None
        system = frame.system if frame.system_quality.is_usable else None

        speaking: bool = bool(audio.is_speaking) if audio is not None else False
        motion_level: float = _clamp(video.motion_level) if video is not None else 0.0
        input_rhythm: float = self._derive_input_rhythm(system, rhythm)

        attention = self._derive_attention(audio, video, system, speaking)
        focus_level = self._derive_focus_level(
            audio, video, system, rhythm, speaking, motion_level
        )
        fatigue = self._derive_fatigue(audio, system, rhythm, input_rhythm)
        intent_probability = self._derive_intent_probability(
            audio, system, rhythm, speaking, input_rhythm
        )
        interruption_sensitivity = self._derive_interruption_sensitivity(
            focus_level, speaking, fatigue
        )

        return HumanFieldState(
            attention=attention,
            focus_level=focus_level,
            fatigue=fatigue,
            intent_probability=intent_probability,
            interruption_sensitivity=interruption_sensitivity,
            input_rhythm=input_rhythm,
            speaking=speaking,
            motion_level=motion_level,
            timestamp=frame.wall_clock,
        )

    # ------------------------------------------------------------------
    # Per-signal derivation
    # ------------------------------------------------------------------

    def _derive_attention(
        self, audio, video, system, speaking: bool
    ) -> float:
        """Attention = human focus directed at the system.

        Combines voice activity, face presence, and screen engagement.
        Returns 0.5 when no modalities are available.
        """
        scores = []
        weights = []

        if audio is not None:
            # Speaking and high energy both indicate directed attention.
            audio_score = (
                0.5 * float(speaking)
                + 0.3 * _clamp(audio.energy)
                + 0.2 * _clamp(audio.speaking_ratio)
            )
            scores.append(_clamp(audio_score))
            weights.append(1.0)

        if video is not None:
            # Face presence contributes positively; rapid motion suggests
            # the human is physically disengaged.
            face = (
                video.face_presence
                if video.face_presence is not None
                else 0.5
            )
            video_score = _clamp(face - 0.3 * _clamp(video.motion_level) + 0.1)
            scores.append(_clamp(video_score))
            weights.append(0.8)

        if system is not None:
            scores.append(_clamp(system.screen_activity))
            weights.append(0.6)

        if not scores:
            return 0.5  # neutral default when all modalities absent

        total_w = sum(weights)
        return _clamp(
            sum(s * w for s, w in zip(scores, weights)) / total_w
        )

    def _derive_focus_level(
        self, audio, video, system, rhythm, speaking: bool, motion_level: float
    ) -> float:
        """Focus = sustained cognitive engagement on the current task.

        Derived from speaking consistency, screen activity, input rhythm,
        and physical stillness.  Returns 0.5 when all modalities absent.
        """
        factors = []

        if audio is not None:
            # Sustained speaking with few pauses indicates focused discourse.
            audio_focus = _clamp(
                audio.speaking_ratio * (1.0 - audio.pause_density)
            )
            factors.append(audio_focus)

        if system is not None:
            factors.append(_clamp(system.screen_activity))

        if rhythm is not None:
            # Focus peaks at moderate input rhythm; idle or frantic both
            # suggest lower focus depth.
            normalised = _clamp(rhythm.input_event_rate)
            rate_focus = _clamp(1.0 - abs(normalised - 0.5) * 2.0)
            factors.append(rate_focus)

        # Physical stillness slightly boosts focus estimate, but only when
        # video is actually available (otherwise motion_level == 0.0 is just
        # a default, not a meaningful signal).
        if video is not None:
            stillness_contrib = _clamp((1.0 - motion_level) * 0.5 + 0.5)
            factors.append(stillness_contrib)

        if not factors:
            return 0.5

        return _clamp(sum(factors) / len(factors))

    def _derive_fatigue(
        self, audio, system, rhythm, input_rhythm: float
    ) -> float:
        """Fatigue proxy: low activity sustained over time.

        Uses session age, idle duration, low input rhythm, and quiet
        voice as converging evidence.  Returns 0.0 when no evidence.
        """
        signals = []

        if rhythm is not None:
            if rhythm.session_age_s > 0:
                # Fatigue grows over long sessions (2 h ≈ 1.0).
                session_fatigue = _clamp(rhythm.session_age_s / 7200.0)
                signals.append(session_fatigue)

            if rhythm.idle_duration_s > 0:
                # 5 min of idle → fatigue contribution of 0.5.
                idle_contrib = _clamp(rhythm.idle_duration_s / 300.0) * 0.5
                signals.append(idle_contrib)

        # Consistently low input rhythm is a weak fatigue indicator, but only
        # when there is a real context source (not just a 0.0 default from
        # having no modalities at all).
        if input_rhythm < 0.1 and (
            rhythm is not None or audio is not None or system is not None
        ):
            signals.append(0.2)

        if audio is not None:
            # Quiet voice energy is a soft fatigue indicator.
            signals.append(_clamp((1.0 - audio.energy) * 0.3))

        if not signals:
            return 0.0

        return _clamp(sum(signals) / len(signals))

    def _derive_intent_probability(
        self, audio, system, rhythm, speaking: bool, input_rhythm: float
    ) -> float:
        """Intent probability = likelihood an actionable intent is forming.

        Active speech is the strongest single indicator; input bursts and
        screen engagement provide corroborating evidence.
        """
        signals = []

        if audio is not None:
            voice_intent = _clamp(
                0.7 * float(speaking) + 0.3 * _clamp(audio.energy)
            )
            signals.append(voice_intent)

        if rhythm is not None and rhythm.recent_burst:
            signals.append(0.8)

        # Normalised input rate is a direct intent proxy.
        signals.append(_clamp(input_rhythm))

        if system is not None:
            signals.append(_clamp(system.screen_activity * 0.6))

        if not signals:
            return 0.0

        # One strong signal is sufficient; blend max and mean.
        max_sig = max(signals)
        mean_sig = sum(signals) / len(signals)
        return _clamp(0.6 * max_sig + 0.4 * mean_sig)

    def _derive_interruption_sensitivity(
        self, focus_level: float, speaking: bool, fatigue: float
    ) -> float:
        """How disruptive an interruption would be right now.

        High focus and active speech both raise sensitivity.  High fatigue
        provides a moderate boost (overtired users handle interruptions poorly).
        """
        base = focus_level
        if speaking:
            # In-flow speech → maximum sensitivity floor.
            base = max(base, 0.8)
        fatigue_boost = fatigue * 0.3
        return _clamp(base + fatigue_boost)

    def _derive_input_rhythm(self, system, rhythm) -> float:
        """Normalised input event rate [0, 1].

        Prefers explicit rhythm data; falls back to screen_activity proxy.
        """
        if rhythm is not None:
            return _clamp(rhythm.input_event_rate)
        if system is not None:
            return _clamp(system.screen_activity * 0.8)
        return 0.0
