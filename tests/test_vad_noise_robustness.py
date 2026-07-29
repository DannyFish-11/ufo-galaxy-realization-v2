"""VAD 抗噪契约:所有者真机反馈「一启用就一直判定有人在说话」。

实测复现的根因是**噪声底棘轮**:上一轮修"自我投毒"时改成"只把确认静音的帧
计入噪声底",却没想到"活跃"本身可能是误判 —— 于是噪声帧因为被判活而永远不
被计入噪声底,门限只能降不能升。安静环境开机、随后风扇/空调起来,门限就永远
停在开机那个极低值,每一帧噪声都被判成说话(实测 198/200 = 99%)。

本文件锁住三件事:
1. 稳态噪声必须能被学进噪声底(棘轮不能再出现);
2. 真实语音(有音节起伏)不能因为这个新判据而被误伤;
3. webrtcvad 在可用时必须是主判据,不可用时优雅回退。
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from core.multimodal.vad import VADConfig, VoiceActivityDetector

_RNG = np.random.default_rng(20260729)
FRAME = 1600  # 100ms @ 16kHz


def _noise(rms: float, n: int = FRAME) -> np.ndarray:
    """指定 RMS 的白噪声(模拟风扇/空调/电流底噪 —— 平稳)。"""
    x = _RNG.standard_normal(n).astype(np.float32)
    return (x / np.sqrt(np.mean(x**2))) * rms


def _speech(rms: float, i: int, n: int = FRAME) -> np.ndarray:
    """带音节起伏的类语音(非平稳 —— 这正是与噪声的区别所在)。"""
    env = 0.35 + 0.65 * abs(np.sin(i * 0.7))
    x = _RNG.standard_normal(n).astype(np.float32)
    return ((x / np.sqrt(np.mean(x**2))) * rms * env).astype(np.float32)


def _run(det: VoiceActivityDetector, frames) -> float:
    """跑完一串帧,返回判为"正在说话"的比例。"""
    hits = [det.process_frame(f).is_speaking for f in frames]
    return sum(hits) / len(hits) if hits else 0.0


# ── 1. 棘轮:噪声底必须能升上去 ────────────────────────────────────────


@pytest.mark.parametrize("noise_rms", [0.006, 0.02, 0.05])
def test_noise_starting_after_quiet_boot_stops_false_firing(noise_rms):
    """安静开机 → 噪声起来。这是所有者真机场景。

    修复前:门限锁死在开机时的极低值,误判率 99%。
    修复后:稳态判据把噪声学进噪声底,门限升上去 → 稳定后不再误判。
    """
    det = VoiceActivityDetector(VADConfig())
    for _ in range(30):  # 3s 安静
        det.process_frame(_noise(0.0008))

    # 前 5s 是判定期(需要 stationary_probe_frames 帧才能断定是稳态噪声)
    _run(det, [_noise(noise_rms) for _ in range(50)])
    # 之后 15s 必须安静下来
    settled = _run(det, [_noise(noise_rms) for _ in range(150)])

    assert settled == 0.0, f"稳态噪声在判定期后仍误判 {settled:.1%}(噪声底棘轮回归)"


def test_noise_floor_actually_rises():
    """直接检查噪声底本身升上去了 —— 而不只是看外部行为。"""
    det = VoiceActivityDetector(VADConfig())
    for _ in range(30):
        det.process_frame(_noise(0.0008))
    floor_quiet = float(np.percentile(det._energy_history, 20))

    for _ in range(120):
        det.process_frame(_noise(0.02))
    floor_noisy = float(np.percentile(det._energy_history, 20))

    assert floor_noisy > floor_quiet * 5, f"噪声底没有随环境升上去:{floor_quiet:.5f} → {floor_noisy:.5f}"


def test_loud_steady_noise_is_not_waved_through_by_fixed_threshold():
    """固定阈值 0.01 曾是 OR 快路径,让 RMS 0.05 的房间噪声无条件判活。

    0.01 RMS 只代表"不算安静",不代表"肯定是人声"。噪声底可信时它必须让位。
    """
    det = VoiceActivityDetector(VADConfig())
    for _ in range(30):
        det.process_frame(_noise(0.05))  # 一直就很吵
    ratio = _run(det, [_noise(0.05) for _ in range(60)])
    assert ratio == 0.0, f"响度高于固定阈值的稳态噪声被判活 {ratio:.1%}"


# ── 2. 不能误伤真实语音 ────────────────────────────────────────────────


def test_speech_over_noisy_background_still_detected():
    """吵环境里说话必须还判得出来 —— 抗噪不能变成变聋。"""
    det = VoiceActivityDetector(VADConfig(min_speech_frames=1))
    for _ in range(60):  # 先让它学会这个房间的底噪
        det.process_frame(_noise(0.01))
    ratio = _run(det, [_speech(0.08, i) + _noise(0.01) for i in range(60)])
    assert ratio > 0.7, f"吵环境下的说话判活率仅 {ratio:.1%}"


def test_sustained_real_speech_never_permanently_stops():
    """Bug A(自我投毒)的保护必须完好:持续说话不能中途永久熄火。"""
    det = VoiceActivityDetector(VADConfig(min_speech_frames=1))
    for _ in range(20):
        det.process_frame(_noise(0.0008))
    hits = [det.process_frame(_speech(0.006, i)).is_speaking for i in range(180)]
    tail = hits[120:]
    assert sum(tail) / len(tail) > 0.9, f"持续说话后段判活率仅 {sum(tail)/len(tail):.1%}"


def test_digital_silence_never_fires():
    det = VoiceActivityDetector(VADConfig(min_speech_frames=1))
    assert _run(det, [np.zeros(FRAME, dtype=np.float32) for _ in range(40)]) == 0.0


# ── 3. webrtcvad:可用即主判据,不可用则优雅回退 ────────────────────────


class _FakeVad:
    """替身:按预设序列回答 is_speech。"""

    def __init__(self, answers):
        self._answers = list(answers)
        self.calls = 0

    def is_speech(self, chunk: bytes, rate: int) -> bool:  # noqa: D401
        self.calls += 1
        return self._answers[(self.calls - 1) % len(self._answers)]


def _with_fake_webrtc(answers):
    fake_mod = type("m", (), {"Vad": staticmethod(lambda a: _FakeVad(answers))})
    return patch.dict("sys.modules", {"webrtcvad": fake_mod})


def test_webrtc_is_authoritative_when_available():
    """webrtcvad 说"不是语音"时,即便能量很高也不该判活。

    这正是它的价值:能量法分不出"响"和"像人声",频谱判据分得出。
    """
    with _with_fake_webrtc([False]):
        det = VoiceActivityDetector(VADConfig(min_speech_frames=1))
        assert det._webrtc is not None, "webrtcvad 可用时必须被启用"
        ratio = _run(det, [_noise(0.3) for _ in range(20)])  # 很响的稳态噪声
    assert ratio == 0.0, "webrtcvad 判非语音时不应判活"


def test_webrtc_positive_drives_detection():
    with _with_fake_webrtc([True]):
        det = VoiceActivityDetector(VADConfig(min_speech_frames=1))
        ratio = _run(det, [_speech(0.02, i) for i in range(20)])
    assert ratio > 0.9


def test_backend_is_reported_honestly():
    """VADState.backend 必须如实说明本帧用的是哪条判据,便于真机排障。"""
    with _with_fake_webrtc([True]):
        det = VoiceActivityDetector(VADConfig(min_speech_frames=1))
        assert det.process_frame(_speech(0.02, 0)).backend == "webrtc"

    det2 = VoiceActivityDetector(VADConfig(use_webrtc=False, min_speech_frames=1))
    assert det2.process_frame(_speech(0.02, 0)).backend == "energy"


def test_missing_webrtcvad_falls_back_without_crashing():
    """缺包必须优雅回退到能量法,不能让整条音频链路崩掉。"""
    import builtins

    real_import = builtins.__import__

    def _no_webrtc(name, *a, **kw):
        if name == "webrtcvad":
            raise ImportError("no module named webrtcvad")
        return real_import(name, *a, **kw)

    with patch.object(builtins, "__import__", side_effect=_no_webrtc):
        det = VoiceActivityDetector(VADConfig(min_speech_frames=1))
    assert det._webrtc is None
    assert det.process_frame(_speech(0.02, 0)).backend == "energy"


def test_unsupported_sample_rate_falls_back():
    """webrtcvad 只吃 8/16/32/48 kHz;其它采样率必须回退而不是硬塞。"""
    det = VoiceActivityDetector(VADConfig(), sample_rate=44100)
    assert det._webrtc is None
    assert det.process_frame(_speech(0.02, 0)).backend == "energy"


def test_env_switch_can_disable_webrtc(monkeypatch):
    monkeypatch.setenv("GALAXY_VAD_USE_WEBRTC", "false")
    assert VADConfig.from_env().use_webrtc is False
