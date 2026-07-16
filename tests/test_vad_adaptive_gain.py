"""tests/test_vad_adaptive_gain.py
====================================
自适应噪声门限 VAD:真机反馈"收到音频但 VAD 从未判定为说话"——低增益麦克风的
真实语音 RMS 低于固定阈值 0.01,永远进不了"说话"分支。本测试证明:
 - 低增益语音(< 0.01 固定阈值,但显著高于噪声底)现在能触发说话;
 - 稳定的低电平底噪【不会】误触发;
 - 纯静音仍判非说话(不因自适应而误判);
 - GALAXY_VAD_* 环境变量能调节灵敏度。
不依赖真实麦克风(直接喂 numpy PCM)。
"""

from __future__ import annotations

import numpy as np

from core.multimodal.vad import VADConfig, VoiceActivityDetector


def _chunk(amp: float, n: int = 1600) -> np.ndarray:
    """恒定幅度块:RMS == amp(便于精确控制"能量")。"""
    return np.ones(n, dtype=np.float32) * amp


def test_low_gain_speech_below_fixed_threshold_now_triggers():
    # 低增益麦克风:底噪 RMS≈0.0008,语音 RMS≈0.006(< 0.01 固定阈值 → 旧 VAD 漏判)。
    vad = VoiceActivityDetector(config=VADConfig(min_speech_frames=1))
    for _ in range(10):
        vad.process_frame(_chunk(0.0008))  # 建立噪声底
    state = vad.process_frame(_chunk(0.006))
    assert state.is_speaking  # 自适应门限救回低增益语音


def test_steady_low_noise_does_not_trigger():
    # 稳定低电平底噪不应被判为说话(能量未显著高于噪声底)。
    vad = VoiceActivityDetector(config=VADConfig(min_speech_frames=1))
    triggered = False
    for _ in range(40):
        st = vad.process_frame(_chunk(0.0015))
        triggered = triggered or st.is_speaking
    assert not triggered


def test_pure_silence_still_not_speaking():
    vad = VoiceActivityDetector(config=VADConfig(min_speech_frames=1))
    for _ in range(30):
        st = vad.process_frame(np.zeros(1600, dtype=np.float32))
        assert not st.is_speaking


def test_loud_speech_still_triggers_via_fast_path():
    # 响亮语音仍走固定阈值快路径(与既有行为一致)。
    vad = VoiceActivityDetector(config=VADConfig(min_speech_frames=1))
    state = vad.process_frame(_chunk(0.3))
    assert state.is_speaking


def test_adaptive_can_be_disabled_via_config():
    # 关掉自适应 → 退回纯固定阈值:低增益语音重新漏判(证明是自适应在起作用)。
    vad = VoiceActivityDetector(config=VADConfig(min_speech_frames=1, adaptive=False))
    for _ in range(10):
        vad.process_frame(_chunk(0.0008))
    state = vad.process_frame(_chunk(0.006))
    assert not state.is_speaking


def test_env_override_min_floor(monkeypatch):
    # 抬高绝对下限到 0.05 → 低增益语音(0.006)被挡住,证明 env 生效(config=None 路径)。
    monkeypatch.setenv("GALAXY_VAD_MIN_FLOOR", "0.05")
    monkeypatch.setenv("GALAXY_VAD_MIN_SPEECH_FRAMES", "1")
    vad = VoiceActivityDetector()  # config=None → from_env
    for _ in range(10):
        vad.process_frame(_chunk(0.0008))
    state = vad.process_frame(_chunk(0.006))
    assert not state.is_speaking


def test_env_adaptive_off(monkeypatch):
    monkeypatch.setenv("GALAXY_VAD_ADAPTIVE", "false")
    cfg = VADConfig.from_env()
    assert cfg.adaptive is False
