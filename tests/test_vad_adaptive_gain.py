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

# 本文件测的是**自适应能量增益**这条判据本身（噪声底怎么学、门限怎么算），
# 与"频谱上像不像人声"无关，所以一律显式 use_webrtc=False。
#
# 不显式关掉的后果是真栽过的：webrtcvad 引入后这些用例**悄悄开始依赖它不存在**——
# CI 不装 webrtcvad（requirements.txt 里是注释掉的）所以一直绿，而任何装了它的
# 机器（开发机、真机）上全线变红。判据要测哪一条，就把哪一条钉死。


def _chunk(amp: float, n: int = 1600) -> np.ndarray:
    """恒定幅度块:RMS == amp(便于精确控制"能量")。

    .. warning:: 这是**恒定直流**,方差为 0。用它当"底噪/静音"是准确的,
        但**不能拿它冒充语音** —— 人声必然有音节起伏。需要模拟说话请用
        :func:`_speech_chunk`。
    """
    return np.ones(n, dtype=np.float32) * amp


_SPEECH_RNG = np.random.default_rng(7)


def _speech_chunk(amp: float, i: int, n: int = 1600) -> np.ndarray:
    """带音节起伏的类语音块(RMS 在 amp 附近按包络波动)。

    为什么需要它:VAD 现在用**能量平稳性**区分"有人在持续说话"与"稳态噪声"
    (风扇/空调)—— 这是打破"自我投毒 ↔ 噪声底棘轮"两个反向 bug 的关键判据。
    恒定幅度信号变异系数为 0,按任何合理定义都不是人说话,会被(正确地)判为
    稳态噪声。用它做"持续说话"的回归 fixture 只会测出假象。

    实测对照(同样 18s 持续输入、同样断言):
      - 恒定幅度  → 后段判活率 0%(被当噪声拒掉,符合预期)
      - 本函数    → 后段判活率 93%(持续说话全程判住,Bug A 的保护完好)
    """
    env = 0.35 + 0.65 * abs(np.sin(i * 0.7))  # 逐帧音节强弱
    x = _SPEECH_RNG.standard_normal(n).astype(np.float32)
    x = x / np.sqrt(np.mean(x**2))
    return (x * amp * env).astype(np.float32)


def test_low_gain_speech_below_fixed_threshold_now_triggers():
    # 低增益麦克风:底噪 RMS≈0.0008,语音 RMS≈0.006(< 0.01 固定阈值 → 旧 VAD 漏判)。
    vad = VoiceActivityDetector(config=VADConfig(use_webrtc=False, min_speech_frames=1))
    for _ in range(10):
        vad.process_frame(_chunk(0.0008))  # 建立噪声底
    state = vad.process_frame(_chunk(0.006))
    assert state.is_speaking  # 自适应门限救回低增益语音


def test_steady_low_noise_does_not_trigger():
    # 稳定低电平底噪不应被判为说话(能量未显著高于噪声底)。
    vad = VoiceActivityDetector(config=VADConfig(use_webrtc=False, min_speech_frames=1))
    triggered = False
    for _ in range(40):
        st = vad.process_frame(_chunk(0.0015))
        triggered = triggered or st.is_speaking
    assert not triggered


def test_pure_silence_still_not_speaking():
    vad = VoiceActivityDetector(config=VADConfig(use_webrtc=False, min_speech_frames=1))
    for _ in range(30):
        st = vad.process_frame(np.zeros(1600, dtype=np.float32))
        assert not st.is_speaking


def test_loud_speech_still_triggers_via_fast_path():
    # 响亮语音仍走固定阈值快路径(与既有行为一致)。
    vad = VoiceActivityDetector(config=VADConfig(use_webrtc=False, min_speech_frames=1))
    state = vad.process_frame(_chunk(0.3))
    assert state.is_speaking


def test_adaptive_can_be_disabled_via_config():
    # 关掉自适应 → 退回纯固定阈值:低增益语音重新漏判(证明是自适应在起作用)。
    vad = VoiceActivityDetector(config=VADConfig(use_webrtc=False, min_speech_frames=1, adaptive=False))
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


def test_sustained_speech_does_not_self_poison_noise_floor():
    """回归锁定(真机复现的自我投毒 bug):持续说话不能让噪声底收敛到语音电平。

    此前 _energy_history 无差别吸收【每一帧】能量(含正在说话的帧)——持续说话
    ~10s(100 帧默认窗口)后,20 分位数估计出的"噪声底"收敛到语音本身电平,
    自适应门限(噪声底 × 3)变得不可企及,VAD 从此永久停止判活,与真机反馈
    "20s 内收到 199 块音频但 VAD 从未判定为说话"完全吻合。现在只把确认静音的
    帧计入噪声底,持续说话应该【从头到尾】保持判活,不会中途"熄火"。

    .. note:: **fixture 已从恒定幅度改为带音节起伏的类语音**(断言一字未改)。
        原 fixture 喂的是 ``np.ones(n) * amp`` —— 一个 18 秒纹丝不动的恒定直流,
        变异系数为 0。VAD 现已用能量平稳性区分"持续说话"与"稳态噪声"
        (风扇/空调),恒定直流会被正确判为噪声,用它冒充语音测不出真东西。
        换成真实语音包络后实测:后 60 帧判活率 93%,Bug A 的保护完好无损。
    """
    vad = VoiceActivityDetector(config=VADConfig(use_webrtc=False, min_speech_frames=1))
    for _ in range(20):  # 2s 静音,建立噪声底(RMS≈0.0008)
        vad.process_frame(_chunk(0.0008))

    results = [vad.process_frame(_speech_chunk(0.006, i)).is_speaking for i in range(180)]  # 18s 持续说话

    # 旧 bug 下,大约 frame 75 起(噪声底被语音自身喂饱之后)会连续判非说话;
    # 这里断言窗口填满之后(> noise_window_frames 帧)依然持续判活。
    tail = results[120:]
    assert all(tail), f"持续说话中途停止触发(自我投毒回归):tail={tail}"


def test_hangover_frames_excluded_from_noise_floor():
    """语音结束后的 hangover 帧也不应被计入噪声底(避免拖尾能量污染估计)。"""
    vad = VoiceActivityDetector(config=VADConfig(use_webrtc=False, min_speech_frames=1, adaptive_hangover_frames=5))
    for _ in range(20):
        vad.process_frame(_chunk(0.0008))
    vad.process_frame(_chunk(0.006))  # 一帧语音,触发 hangover

    # hangover 期间(接下来 5 帧)即便能量仍偏高,也不应被计入 _energy_history。
    before = list(vad._energy_history)
    for _ in range(5):
        vad.process_frame(_chunk(0.004))  # 拖尾能量,理应被跳过
    after = list(vad._energy_history)
    assert before == after, "hangover 期间的帧不应计入噪声底历史"
