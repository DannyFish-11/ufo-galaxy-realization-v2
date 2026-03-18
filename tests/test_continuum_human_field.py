"""
tests/test_continuum_human_field.py
====================================

Unit tests for core.continuum.human_field.

Test groups
-----------
  A) InteractionRhythm dataclass defaults and fields.
  B) HumanFieldInferrer construction.
  C) infer() with no modalities → graceful defaults.
  D) infer() with audio only.
  E) infer() with video only.
  F) infer() with system only.
  G) infer() with all modalities.
  H) infer() with InteractionRhythm.
  I) speaking flag propagation.
  J) Output value bounds [0, 1] for all field combinations.
  K) interruption_sensitivity logic.
  L) fatigue derivation.
"""

from __future__ import annotations

import pytest

from core.continuum.config import ContinuumConfig, DEFAULT_CONTINUUM_CONFIG
from core.continuum.human_field import HumanFieldInferrer, InteractionRhythm
from core.continuum.types import HumanFieldState
from core.multimodal.audio_features import AudioState
from core.multimodal.perception_frame import PerceptionFrame, SystemSignals
from core.multimodal.signal_quality import SignalQuality
from core.multimodal.video_features import VideoState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _audio(
    *,
    energy: float = 0.0,
    speaking_ratio: float = 0.0,
    pause_density: float = 0.0,
    noise_level: float = 0.0,
    is_speaking: bool = False,
) -> AudioState:
    return AudioState(
        energy=energy,
        speaking_ratio=speaking_ratio,
        pause_density=pause_density,
        noise_level=noise_level,
        is_speaking=is_speaking,
    )


def _video(
    *,
    motion_level: float = 0.0,
    face_presence: float | None = None,
    scene_change_rate: float = 0.0,
) -> VideoState:
    return VideoState(
        motion_level=motion_level,
        face_presence=face_presence,
        scene_change_rate=scene_change_rate,
    )


def _system(screen_activity: float = 0.0) -> SystemSignals:
    return SystemSignals(screen_activity=screen_activity)


def _frame(
    *,
    audio: AudioState | None = None,
    video: VideoState | None = None,
    system: SystemSignals | None = None,
) -> PerceptionFrame:
    """Build a PerceptionFrame with optional modalities marked OK."""
    return PerceptionFrame(
        audio=audio,
        audio_quality=SignalQuality.ok() if audio is not None else SignalQuality.missing(),
        video=video,
        video_quality=SignalQuality.ok() if video is not None else SignalQuality.missing(),
        system=system,
        system_quality=SignalQuality.ok() if system is not None else SignalQuality.missing(),
    )


# ===========================================================================
# A) InteractionRhythm
# ===========================================================================


class TestInteractionRhythm:
    def test_default_values(self):
        r = InteractionRhythm()
        assert r.input_event_rate == 0.0
        assert r.session_age_s == 0.0
        assert r.idle_duration_s == 0.0
        assert r.recent_burst is False

    def test_custom_construction(self):
        r = InteractionRhythm(
            input_event_rate=0.6,
            session_age_s=300.0,
            idle_duration_s=30.0,
            recent_burst=True,
        )
        assert r.input_event_rate == 0.6
        assert r.session_age_s == 300.0
        assert r.recent_burst is True


# ===========================================================================
# B) HumanFieldInferrer construction
# ===========================================================================


class TestHumanFieldInferrerConstruction:
    def test_default_construction(self):
        inferrer = HumanFieldInferrer()
        assert inferrer is not None

    def test_custom_config(self):
        cfg = ContinuumConfig(ema_alpha=0.5)
        inferrer = HumanFieldInferrer(config=cfg)
        assert inferrer._cfg.ema_alpha == 0.5

    def test_default_config_is_singleton(self):
        inferrer = HumanFieldInferrer()
        assert inferrer._cfg is DEFAULT_CONTINUUM_CONFIG


# ===========================================================================
# C) infer() with no modalities
# ===========================================================================


class TestInferNoModalities:
    def setup_method(self):
        self.inferrer = HumanFieldInferrer()
        self.frame = PerceptionFrame()  # all modalities missing

    def test_returns_human_field_state(self):
        hf = self.inferrer.infer(self.frame)
        assert isinstance(hf, HumanFieldState)

    def test_attention_neutral(self):
        hf = self.inferrer.infer(self.frame)
        assert hf.attention == pytest.approx(0.5)

    def test_focus_level_neutral(self):
        hf = self.inferrer.infer(self.frame)
        assert hf.focus_level == pytest.approx(0.5)

    def test_intent_probability_zero(self):
        hf = self.inferrer.infer(self.frame)
        assert hf.intent_probability == pytest.approx(0.0)

    def test_fatigue_zero(self):
        hf = self.inferrer.infer(self.frame)
        assert hf.fatigue == pytest.approx(0.0)

    def test_speaking_false(self):
        hf = self.inferrer.infer(self.frame)
        assert hf.speaking is False

    def test_motion_level_zero(self):
        hf = self.inferrer.infer(self.frame)
        assert hf.motion_level == pytest.approx(0.0)

    def test_input_rhythm_zero(self):
        hf = self.inferrer.infer(self.frame)
        assert hf.input_rhythm == pytest.approx(0.0)

    def test_all_values_in_bounds(self):
        hf = self.inferrer.infer(self.frame)
        for name in ["attention", "focus_level", "fatigue", "intent_probability",
                     "interruption_sensitivity", "input_rhythm", "motion_level"]:
            v = getattr(hf, name)
            assert 0.0 <= v <= 1.0, f"{name}={v} out of [0, 1]"


# ===========================================================================
# D) infer() with audio only
# ===========================================================================


class TestInferAudioOnly:
    def setup_method(self):
        self.inferrer = HumanFieldInferrer()

    def test_speaking_true_raises_attention(self):
        frame = _frame(audio=_audio(energy=0.8, speaking_ratio=0.7, is_speaking=True))
        hf = self.inferrer.infer(frame)
        assert hf.attention > 0.5

    def test_not_speaking_low_energy_lower_attention(self):
        frame_speak = _frame(audio=_audio(energy=0.8, is_speaking=True))
        frame_quiet = _frame(audio=_audio(energy=0.05, is_speaking=False))
        hf_speak = self.inferrer.infer(frame_speak)
        hf_quiet = self.inferrer.infer(frame_quiet)
        assert hf_speak.attention > hf_quiet.attention

    def test_speaking_flag_propagated(self):
        frame = _frame(audio=_audio(is_speaking=True))
        hf = self.inferrer.infer(frame)
        assert hf.speaking is True

    def test_not_speaking_flag_propagated(self):
        frame = _frame(audio=_audio(is_speaking=False))
        hf = self.inferrer.infer(frame)
        assert hf.speaking is False

    def test_high_energy_speaking_intent(self):
        frame = _frame(audio=_audio(energy=0.9, is_speaking=True))
        hf = self.inferrer.infer(frame)
        assert hf.intent_probability > 0.5

    def test_silent_audio_low_intent(self):
        frame = _frame(audio=_audio(energy=0.0, is_speaking=False))
        hf = self.inferrer.infer(frame)
        assert hf.intent_probability < 0.4

    def test_focused_speech_focus_level(self):
        # High speaking_ratio + low pause_density = focused
        frame = _frame(audio=_audio(speaking_ratio=0.9, pause_density=0.05))
        hf = self.inferrer.infer(frame)
        assert hf.focus_level > 0.5

    def test_fragmented_speech_lower_focus(self):
        frame_focused = _frame(audio=_audio(speaking_ratio=0.9, pause_density=0.05))
        frame_fragmented = _frame(audio=_audio(speaking_ratio=0.5, pause_density=0.9))
        hf_f = self.inferrer.infer(frame_focused)
        hf_fr = self.inferrer.infer(frame_fragmented)
        assert hf_f.focus_level > hf_fr.focus_level


# ===========================================================================
# E) infer() with video only
# ===========================================================================


class TestInferVideoOnly:
    def setup_method(self):
        self.inferrer = HumanFieldInferrer()

    def test_face_present_raises_attention(self):
        frame = _frame(video=_video(face_presence=1.0, motion_level=0.0))
        hf = self.inferrer.infer(frame)
        assert hf.attention > 0.5

    def test_no_face_lower_attention(self):
        frame_face = _frame(video=_video(face_presence=1.0, motion_level=0.0))
        frame_noface = _frame(video=_video(face_presence=0.0, motion_level=0.5))
        hf_face = self.inferrer.infer(frame_face)
        hf_noface = self.inferrer.infer(frame_noface)
        assert hf_face.attention > hf_noface.attention

    def test_motion_level_propagated(self):
        frame = _frame(video=_video(motion_level=0.75))
        hf = self.inferrer.infer(frame)
        assert hf.motion_level == pytest.approx(0.75)

    def test_still_face_higher_focus(self):
        frame_still = _frame(video=_video(motion_level=0.0, face_presence=1.0))
        frame_moving = _frame(video=_video(motion_level=0.9, face_presence=1.0))
        hf_still = self.inferrer.infer(frame_still)
        hf_moving = self.inferrer.infer(frame_moving)
        assert hf_still.focus_level >= hf_moving.focus_level


# ===========================================================================
# F) infer() with system only
# ===========================================================================


class TestInferSystemOnly:
    def setup_method(self):
        self.inferrer = HumanFieldInferrer()

    def test_high_screen_activity_raises_attention(self):
        frame = _frame(system=_system(screen_activity=0.9))
        hf = self.inferrer.infer(frame)
        assert hf.attention > 0.5

    def test_low_screen_activity_lower_attention(self):
        frame_hi = _frame(system=_system(screen_activity=0.9))
        frame_lo = _frame(system=_system(screen_activity=0.1))
        hf_hi = self.inferrer.infer(frame_hi)
        hf_lo = self.inferrer.infer(frame_lo)
        assert hf_hi.attention > hf_lo.attention

    def test_screen_activity_contributes_to_focus(self):
        frame = _frame(system=_system(screen_activity=0.85))
        hf = self.inferrer.infer(frame)
        assert hf.focus_level > 0.5

    def test_input_rhythm_derived_from_screen(self):
        frame = _frame(system=_system(screen_activity=0.8))
        hf = self.inferrer.infer(frame)
        # rhythm = screen_activity * 0.8
        assert hf.input_rhythm == pytest.approx(0.8 * 0.8, abs=1e-6)


# ===========================================================================
# G) infer() with all modalities
# ===========================================================================


class TestInferAllModalities:
    def setup_method(self):
        self.inferrer = HumanFieldInferrer()

    def test_all_high_signals_high_attention(self):
        frame = _frame(
            audio=_audio(energy=0.9, speaking_ratio=0.8, is_speaking=True),
            video=_video(face_presence=1.0, motion_level=0.1),
            system=_system(screen_activity=0.9),
        )
        hf = self.inferrer.infer(frame)
        assert hf.attention > 0.7

    def test_all_high_signals_high_intent(self):
        frame = _frame(
            audio=_audio(energy=0.9, is_speaking=True),
            system=_system(screen_activity=0.9),
        )
        hf = self.inferrer.infer(frame)
        assert hf.intent_probability > 0.6

    def test_all_bounds_multimodal(self):
        frame = _frame(
            audio=_audio(energy=0.5, speaking_ratio=0.6, pause_density=0.3, is_speaking=True),
            video=_video(motion_level=0.3, face_presence=0.8),
            system=_system(screen_activity=0.7),
        )
        hf = self.inferrer.infer(frame)
        for name in ["attention", "focus_level", "fatigue", "intent_probability",
                     "interruption_sensitivity", "input_rhythm", "motion_level"]:
            v = getattr(hf, name)
            assert 0.0 <= v <= 1.0, f"{name}={v} out of [0, 1]"


# ===========================================================================
# H) infer() with InteractionRhythm
# ===========================================================================


class TestInferWithRhythm:
    def setup_method(self):
        self.inferrer = HumanFieldInferrer()

    def test_rhythm_input_rate_propagated(self):
        frame = _frame()
        rhythm = InteractionRhythm(input_event_rate=0.7)
        hf = self.inferrer.infer(frame, rhythm=rhythm)
        assert hf.input_rhythm == pytest.approx(0.7)

    def test_recent_burst_raises_intent(self):
        frame = _frame()
        rhythm_burst = InteractionRhythm(input_event_rate=0.5, recent_burst=True)
        rhythm_no_burst = InteractionRhythm(input_event_rate=0.5, recent_burst=False)
        hf_burst = self.inferrer.infer(frame, rhythm=rhythm_burst)
        hf_no = self.inferrer.infer(frame, rhythm=rhythm_no_burst)
        assert hf_burst.intent_probability > hf_no.intent_probability

    def test_long_session_raises_fatigue(self):
        frame = _frame()
        rhythm_long = InteractionRhythm(session_age_s=7200.0)  # 2 hours
        rhythm_fresh = InteractionRhythm(session_age_s=60.0)
        hf_long = self.inferrer.infer(frame, rhythm=rhythm_long)
        hf_fresh = self.inferrer.infer(frame, rhythm=rhythm_fresh)
        assert hf_long.fatigue > hf_fresh.fatigue

    def test_long_idle_raises_fatigue(self):
        frame = _frame()
        rhythm_idle = InteractionRhythm(idle_duration_s=300.0)  # 5 min
        rhythm_active = InteractionRhythm(idle_duration_s=5.0)
        hf_idle = self.inferrer.infer(frame, rhythm=rhythm_idle)
        hf_active = self.inferrer.infer(frame, rhythm=rhythm_active)
        assert hf_idle.fatigue > hf_active.fatigue

    def test_moderate_rhythm_focus(self):
        """Moderate input rate (≈0.5) gives higher focus than extremes."""
        frame = _frame()
        rhythm_mod = InteractionRhythm(input_event_rate=0.5)
        rhythm_idle = InteractionRhythm(input_event_rate=0.0)
        rhythm_frantic = InteractionRhythm(input_event_rate=1.0)
        hf_mod = self.inferrer.infer(frame, rhythm=rhythm_mod)
        hf_idle = self.inferrer.infer(frame, rhythm=rhythm_idle)
        hf_frantic = self.inferrer.infer(frame, rhythm=rhythm_frantic)
        assert hf_mod.focus_level >= hf_idle.focus_level
        assert hf_mod.focus_level >= hf_frantic.focus_level


# ===========================================================================
# I) speaking flag propagation
# ===========================================================================


class TestSpeakingPropagation:
    def setup_method(self):
        self.inferrer = HumanFieldInferrer()

    def test_speaking_true_when_audio_active(self):
        frame = _frame(audio=_audio(is_speaking=True))
        hf = self.inferrer.infer(frame)
        assert hf.speaking is True

    def test_speaking_false_when_audio_quiet(self):
        frame = _frame(audio=_audio(is_speaking=False))
        hf = self.inferrer.infer(frame)
        assert hf.speaking is False

    def test_speaking_false_when_no_audio(self):
        frame = _frame()
        hf = self.inferrer.infer(frame)
        assert hf.speaking is False

    def test_speaking_false_when_audio_quality_missing(self):
        # Audio present but quality is MISSING → inferrer should treat as absent
        frame = PerceptionFrame(
            audio=_audio(is_speaking=True),
            audio_quality=SignalQuality.missing(),
        )
        hf = self.inferrer.infer(frame)
        assert hf.speaking is False


# ===========================================================================
# J) Output value bounds
# ===========================================================================


class TestOutputBounds:
    """All inferred fields must stay in [0, 1] across a wide range of inputs."""

    def setup_method(self):
        self.inferrer = HumanFieldInferrer()

    @pytest.mark.parametrize("energy,speaking_ratio,pause_density,is_speaking", [
        (0.0, 0.0, 0.0, False),
        (1.0, 1.0, 1.0, True),
        (0.5, 0.5, 0.5, True),
        (0.99, 0.01, 0.99, False),
    ])
    def test_audio_bounds(self, energy, speaking_ratio, pause_density, is_speaking):
        frame = _frame(audio=_audio(
            energy=energy,
            speaking_ratio=speaking_ratio,
            pause_density=pause_density,
            is_speaking=is_speaking,
        ))
        hf = self.inferrer.infer(frame)
        for name in ["attention", "focus_level", "fatigue", "intent_probability",
                     "interruption_sensitivity", "input_rhythm", "motion_level"]:
            v = getattr(hf, name)
            assert 0.0 <= v <= 1.0, f"audio test: {name}={v}"

    @pytest.mark.parametrize("motion,face", [
        (0.0, None),
        (1.0, None),
        (0.5, 0.5),
        (0.0, 1.0),
        (1.0, 0.0),
    ])
    def test_video_bounds(self, motion, face):
        frame = _frame(video=_video(motion_level=motion, face_presence=face))
        hf = self.inferrer.infer(frame)
        for name in ["attention", "focus_level", "interruption_sensitivity"]:
            v = getattr(hf, name)
            assert 0.0 <= v <= 1.0, f"video test: {name}={v}"

    @pytest.mark.parametrize("sa", [0.0, 0.25, 0.5, 0.75, 1.0])
    def test_system_bounds(self, sa):
        frame = _frame(system=_system(screen_activity=sa))
        hf = self.inferrer.infer(frame)
        for name in ["attention", "focus_level", "input_rhythm"]:
            v = getattr(hf, name)
            assert 0.0 <= v <= 1.0, f"system test sa={sa}: {name}={v}"


# ===========================================================================
# K) interruption_sensitivity logic
# ===========================================================================


class TestInterruptionSensitivity:
    def setup_method(self):
        self.inferrer = HumanFieldInferrer()

    def test_speaking_floor(self):
        """Active speech must push interruption_sensitivity ≥ 0.8 and ≤ 1.0."""
        frame = _frame(audio=_audio(is_speaking=True))
        hf = self.inferrer.infer(frame)
        assert hf.interruption_sensitivity >= 0.8
        assert hf.interruption_sensitivity <= 1.0

    def test_high_focus_high_sensitivity(self):
        """Sustained screen activity (high focus) raises sensitivity."""
        frame_hi = _frame(system=_system(screen_activity=0.95))
        frame_lo = _frame(system=_system(screen_activity=0.1))
        hf_hi = self.inferrer.infer(frame_hi)
        hf_lo = self.inferrer.infer(frame_lo)
        assert hf_hi.interruption_sensitivity > hf_lo.interruption_sensitivity

    def test_high_fatigue_boosts_sensitivity(self):
        """High fatigue adds a small sensitivity boost."""
        frame = _frame()
        rhythm_tired = InteractionRhythm(session_age_s=7200.0)
        rhythm_fresh = InteractionRhythm(session_age_s=60.0)
        hf_tired = self.inferrer.infer(frame, rhythm=rhythm_tired)
        hf_fresh = self.inferrer.infer(frame, rhythm=rhythm_fresh)
        assert hf_tired.interruption_sensitivity >= hf_fresh.interruption_sensitivity


# ===========================================================================
# L) fatigue derivation
# ===========================================================================


class TestFatigueDerivation:
    def setup_method(self):
        self.inferrer = HumanFieldInferrer()

    def test_no_evidence_zero_fatigue(self):
        frame = _frame()
        hf = self.inferrer.infer(frame)
        assert hf.fatigue == pytest.approx(0.0)

    def test_two_hour_session_high_fatigue(self):
        frame = _frame()
        rhythm = InteractionRhythm(session_age_s=7200.0)
        hf = self.inferrer.infer(frame, rhythm=rhythm)
        assert hf.fatigue > 0.4

    def test_fresh_session_low_fatigue(self):
        frame = _frame()
        rhythm = InteractionRhythm(session_age_s=30.0)
        hf = self.inferrer.infer(frame, rhythm=rhythm)
        assert hf.fatigue < 0.15

    def test_fatigue_in_bounds(self):
        frame = _frame(audio=_audio(energy=0.0))
        rhythm = InteractionRhythm(session_age_s=14400.0, idle_duration_s=600.0)
        hf = self.inferrer.infer(frame, rhythm=rhythm)
        assert 0.0 <= hf.fatigue <= 1.0
