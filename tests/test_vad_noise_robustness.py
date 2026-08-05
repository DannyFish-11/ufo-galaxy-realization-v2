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
    """Bug A(自我投毒)的保护必须完好:持续说话不能中途永久熄火。

    显式 ``use_webrtc=False``:这条钉的是**能量路径**的性质(噪声底不能被持续语音
    自我投毒抬高到不可企及)。而本用例的"语音"是带幅度包络的白噪声 —— 那不是语音,
    webrtcvad 对它的判定在 0.00–1.00 之间剧烈波动(实测 40 帧里 15 帧低于 0.5 阈值,
    单靠它只有约 62% 判活),够不着这里要求的 90%。拿它当"语音"去考频谱分类器,
    考的不是被测的那件事。

    webrtcvad 那条路径由本文件上方两条稳态噪声用例覆盖(它们走默认 use_webrtc=True)。
    """
    det = VoiceActivityDetector(VADConfig(use_webrtc=False, min_speech_frames=1))
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
        # 暖机期(噪声底还没学到):频谱 ∩ 绝对下限。
        det = VoiceActivityDetector(VADConfig(min_speech_frames=1))
        assert det.process_frame(_speech(0.02, 0)).backend == "webrtc+floor"
        # 学到噪声底之后:频谱 ∩ 自适应门限。
        for _ in range(10):
            det.process_frame(_noise(0.0008))
        assert det.process_frame(_speech(0.02, 0)).backend == "webrtc+energy"
        # 关掉电平闸(排障开关):频谱独断。
        loose = VoiceActivityDetector(VADConfig(min_speech_frames=1, webrtc_requires_level=False))
        assert loose.process_frame(_speech(0.02, 0)).backend == "webrtc"

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


# ── 4. 交集判据:webrtcvad 与噪声底必须一起把关 ──────────────────────────
#
# 真机症状「一启用就一直判定有人在说话」的第二处根源(第一处是噪声底棘轮):
# webrtcvad 一旦可用就**独断** is_active,下面那整套噪声底逻辑只维护数据、
# 完全不参与判决。而 webrtcvad 是频谱分类器 —— 宽带稳态噪声(风扇/空调)在
# GMM 眼里跟摩擦音、清音很像,它照判有声。
#
# 这一族此前**在 CI 上从来没跑过**:webrtcvad 在 requirements.txt 里是注释掉的,
# CI 不装它,于是主判据那条路径永远走不到。凡是装了它的机器(开发机、真机)全线
# 复现,CI 一直绿。


pytestmark_needs_webrtc = pytest.mark.skipif(
    VoiceActivityDetector(VADConfig())._webrtc is None,
    reason="本机没有 webrtcvad —— 这一族钉的正是它可用时的行为",
)


@pytestmark_needs_webrtc
def test_webrtc_alone_would_call_steady_noise_speech():
    """先钉住"webrtcvad 单独用确实挡不住稳态噪声" —— 这是交集判据存在的前提。

    如果哪天这条不再成立(webrtcvad 换了实现/参数),交集判据的理由就要重新审视,
    而不是想当然地留着。
    """
    det = VoiceActivityDetector(VADConfig(webrtc_requires_level=False))
    for _ in range(30):
        det.process_frame(_noise(0.05))
    ratio = _run(det, [_noise(0.05) for _ in range(60)])
    assert ratio > 0.9, f"webrtcvad 单独用竟然挡住了稳态噪声({ratio:.0%}) —— 前提变了,请重审交集判据"


@pytestmark_needs_webrtc
def test_intersection_gates_steady_noise_that_webrtc_waves_through():
    """交集判据:webrtcvad 说有声,但电平没超过噪声底 → 不判活。"""
    det = VoiceActivityDetector(VADConfig())  # 默认 webrtc_requires_level=True
    for _ in range(30):
        det.process_frame(_noise(0.05))
    ratio = _run(det, [_noise(0.05) for _ in range(60)])
    assert ratio == 0.0, f"稳态噪声仍被判活 {ratio:.1%} —— 交集判据没生效"


@pytestmark_needs_webrtc
def test_intersection_does_not_gate_speech_over_noise():
    """交集判据不许误伤:噪声之上的真实语音仍要判活。

    自适应门限要求"比环境底噪高约 9.5 dB",这本来就是能量路径一直在用的判据,
    不是交集引入的新严苛条件。
    """
    det = VoiceActivityDetector(VADConfig(min_speech_frames=1))
    for _ in range(30):
        det.process_frame(_noise(0.01))
    frames = [(_noise(0.01) + _speech(0.08, i)).astype(np.float32) for i in range(40)]
    ratio = _run(det, frames)
    assert ratio > 0.8, f"噪声之上的语音被交集判据误伤,判活仅 {ratio:.1%}"


@pytestmark_needs_webrtc
def test_level_gate_waits_for_a_credible_floor():
    """噪声底还没学到时,电平闸不许参与 —— 否则会误杀轻声说话。

    没有噪声底时 ``_energy_is_active`` 只剩固定阈值 0.01 兜底,而按它自己的注释
    那个数"只代表不算安静,不代表肯定是语音"。实测:拿它当电平闸,安静房间里
    RMS 0.01 的轻声会被全部挡掉。
    """
    det = VoiceActivityDetector(VADConfig(min_speech_frames=1))
    for _ in range(20):
        det.process_frame(_noise(0.0008))  # 先有真安静,让噪声底学到低位
    ratio = _run(det, [_speech(0.01, i) for i in range(40)])
    assert ratio > 0.8, f"安静房间里的轻声被挡住了,判活仅 {ratio:.1%}"


# ── 5. 判决依据默认可见:排障不需要先去翻开关 ────────────────────────────


def test_snapshot_carries_the_decision_evidence_by_default():
    """每帧快照必须带出噪声底、生效门限、webrtcvad 比例 —— 无需任何开关。

    真机症状高度依赖现场声学环境,换个时间未必复现得出来。只给一个
    ``is_speaking`` 布尔值,出问题时说不出它凭什么这么判;而这几个数每帧本来
    就在算,此前算完即扔。
    """
    det = VoiceActivityDetector(VADConfig())
    for _ in range(30):
        det.process_frame(_noise(0.05))
    s = det.process_frame(_noise(0.05))

    assert s.noise_floor is not None and s.noise_floor > 0
    assert s.adaptive_threshold is not None
    assert s.adaptive_threshold >= s.noise_floor, "门限不该低于噪声底"
    # 这一帧的完整故事:电平没过门限 → 判静。有了这几个数就说得清。
    assert s.energy < s.adaptive_threshold
    assert s.is_speaking is False


def test_evidence_is_none_while_the_floor_is_not_yet_credible():
    """噪声底不可信时报 ``None``,而不是塞一个假的 0.0。

    那时判据是固定阈值,报一个"噪声底"只会把排障的人带偏。
    """
    det = VoiceActivityDetector(VADConfig())
    s = det.process_frame(_noise(0.05))  # 第一帧,样本还不够
    assert s.noise_floor is None and s.adaptive_threshold is None


def test_snapshot_separates_spectral_reject_from_level_reject():
    """ "频谱说没有" 与 "频谱说有但电平不够" 必须分得出来。

    只看 is_speaking 这两种都是 False,而它们的下一步完全不同:前者调
    webrtc_aggressiveness,后者调 adaptive_speech_mult。
    """
    with _with_fake_webrtc([False]):
        det = VoiceActivityDetector(VADConfig(min_speech_frames=1))
        spectral_reject = det.process_frame(_noise(0.3))
    assert spectral_reject.is_speaking is False
    assert spectral_reject.webrtc_voiced_ratio == 0.0, "频谱拒绝:比例为 0"

    det2 = VoiceActivityDetector(VADConfig())
    for _ in range(30):
        det2.process_frame(_noise(0.05))
    level_reject = det2.process_frame(_noise(0.05))
    assert level_reject.is_speaking is False
    if level_reject.webrtc_voiced_ratio is not None:  # 本机装了 webrtcvad 时
        assert level_reject.webrtc_voiced_ratio > 0.5, "电平拒绝:频谱其实说有声"
    assert level_reject.energy < level_reject.adaptive_threshold


# ── 6. 暖机期:噪声底还没学到时也不能让频谱独断 ────────────────────────


def test_no_false_speech_in_the_warmup_window():
    """开机头几帧不能冒出假的"正在说话"。

    上一版把电平闸整个撤到"噪声底可信之后",于是暖机期只剩 webrtcvad 独断 ——
    实测它把 RMS 0.002 的高斯噪声判成有声(ratio=1.00),开机 ~200ms 内出现一段
    假说话。这是「一启用就一直判定有人在说话」缩短后的残留,不是另一个 bug。
    """
    det = VoiceActivityDetector(VADConfig())
    hits = [det.process_frame(_noise(0.0015)).is_speaking for _ in range(12)]
    assert not any(hits), f"暖机期出现假说话:{hits}"


def test_the_warmup_gate_never_rejects_what_the_steady_state_would_accept():
    """暖机闸必须**弱于**稳态门限,否则会出现"先能说话、后说不了"的反转。

    稳态门限是 ``max(adaptive_min_floor, 噪声底 × 倍数)``,恒 ≥
    ``adaptive_min_floor`` —— 拿后者当暖机闸,这个性质就是构造出来的。
    这条钉住它:换成固定阈值 0.01 之类的数会立刻红。
    """
    cfg = VADConfig()
    det = VoiceActivityDetector(cfg)
    for _ in range(30):
        det.process_frame(_noise(0.0008))
    steady = det.process_frame(_noise(0.0008))
    assert steady.adaptive_threshold is not None
    assert cfg.adaptive_min_floor <= steady.adaptive_threshold


def test_speaking_from_the_very_first_frame_still_works():
    """用户开机就说话(暖机期内)不能被这道闸挡掉。"""
    det = VoiceActivityDetector(VADConfig())
    ratio = _run(det, [_speech(0.05, i) for i in range(20)])
    assert ratio > 0.7, f"开口即说被挡住了,判活仅 {ratio:.1%}"
