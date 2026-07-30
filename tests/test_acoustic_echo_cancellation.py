"""声学回声消除(AEC)的行为测试。

为什么可以在没有麦克风、没有 Windows 机器的环境里严肃地测
------------------------------------------------------------
AEC 的效果有一个**客观的标量指标**:ERLE(Echo Return Loss Enhancement,回声抑制量,
dB)—— 麦克风信号能量与残差能量之比。只要用**已知的**回声路径合成信号,就能算出真值:

    参考信号(远端) → 卷积一个已知的房间冲激响应 → 回声 → 加已知整体时延 → 麦克风信号

于是"AEC 到底消掉了多少回声"不是主观判断,而是一个可以断言的数字。真机上不确定的是
**回声路径长什么样**,而不是**算法对给定路径有没有效**;后者正是这里钉住的东西。

本文件钉的四件事
----------------
1. **纯回声时 ERLE 必须达标。** 这是 AEC 存在的理由。阈值取得比实测水平低一截,
   给数值抖动留余量,但足以在算法退化时立刻失败。
2. **双讲时必须保住用户的语音。** 这条比第 1 条更要紧:一个把回声消得很干净、却把
   用户说的话也削掉的 AEC 是负资产 —— 它会让 ASR 什么也听不清,而症状极难归因。
3. **绝不放大。** 任何情况下都不能出现"残差比麦克风信号还大"(ERLE 显著为负)。
   开发过程中两次实现错误恰好都表现为这个:时域版归一化写错 → −2274 dB;频域版
   功率估计从零平滑 → 开头 −20 dB。所以这条单独立一个用例。
4. **降级永不断链。** 参考信号缺失/安静、块长突变、numpy 缺失 —— 一律原样返回麦克风
   信号。上行语音通路不能因为 AEC 出问题就断掉。
"""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")

from core.multimodal.acoustic_echo_canceller import (  # noqa: E402
    AcousticEchoCanceller,
    AECConfig,
)

SR = 16000
BLK = 1600  # 100ms,与 AudioIngestConfig.chunk_duration_ms 默认值一致
NB = 120  # 12 秒
TRUE_DELAY = 800  # 50ms:两条流之间的整体偏移


# ── 合成信号(确定性:固定种子,所有断言可复现)────────────────────────────


def _rir(seed: int = 7, n: int = 400, decay: float = 60.0):
    """合成房间冲激响应:指数衰减的随机脉冲串,总增益 0.8。"""
    rng = np.random.default_rng(seed)
    h = rng.standard_normal(n) * np.exp(-np.arange(n) / decay)
    return h / (np.abs(h).sum() + 1e-9) * 0.8


def _speechlike(seed: int, n: int, env_period_s: float = 0.7):
    """类语音信号:带限噪声 + 慢变幅度包络。

    刻意用**带限**(相关)信号而不是白噪声:白噪声对自适应滤波器是最容易的输入,
    用它测等于放水。语音的强相关性正是时域 NLMS 收敛不下去的原因。
    """
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n)
    win = np.hanning(64) / np.hanning(64).sum()
    b = np.convolve(x, win, "same")
    env = 0.5 + 0.5 * np.sin(2 * np.pi * np.arange(b.size) / (SR * env_period_s))
    return (b * env).astype(np.float64)


def _erle_db(mic, err) -> float:
    return float(10 * np.log10((mic @ mic + 1e-12) / (err @ err + 1e-12)))


def _run(mic_all, ref, config=None, nb: int = NB):
    """按块喂进 AEC,返回 (拼接后的麦克风信号, 拼接后的残差, aec)。"""
    aec = AcousticEchoCanceller(config or AECConfig(sample_rate=SR))
    mics, errs = [], []
    for i in range(nb):
        aec.push_reference(ref[i * BLK : (i + 1) * BLK])
        m = mic_all[i * BLK : (i + 1) * BLK]
        errs.append(np.asarray(aec.process(m)))
        mics.append(m)
    return np.concatenate(mics), np.concatenate(errs), aec


def _echo_only_scenario():
    """只有回声、没有近端语音。"""
    h = _rir()
    ref = _speechlike(7, NB * BLK)
    echo = np.convolve(ref, h)[: ref.size]
    mic = np.concatenate([np.zeros(TRUE_DELAY), echo])[: ref.size]
    return mic, ref


def _double_talk_scenario(dt_from_block: int = 80):
    """前段纯回声,``dt_from_block`` 块之后叠加近端语音(用户开口)。"""
    mic, ref = _echo_only_scenario()
    near = np.zeros_like(mic)
    tail = mic.size - dt_from_block * BLK
    near[dt_from_block * BLK :] = _speechlike(99, tail, env_period_s=0.4)
    return mic + near, ref, near


# ── 1. 纯回声:ERLE 达标 ────────────────────────────────────────────────────


class TestEchoSuppression:
    def test_converges_to_useful_erle_on_echo_only(self):
        """收敛后的 ERLE 必须达标。实测 ≈27 dB;阈值 18 dB 留足抖动余量。"""
        mic, ref = _echo_only_scenario()
        m, e, aec = _run(mic, ref)
        q = m.size * 3 // 4
        erle = _erle_db(m[q:], e[q:])
        assert erle >= 18.0, f"收敛后 ERLE 仅 {erle:.2f} dB —— AEC 基本没起作用"

    def test_delay_is_estimated_close_to_truth(self):
        """整体时延估计错了,滤波器就得拿抽头去表示延迟,尾长被白白吃掉。"""
        mic, ref = _echo_only_scenario()
        _m, _e, aec = _run(mic, ref)
        est = aec.snapshot()["delay_samples"]
        assert abs(est - TRUE_DELAY) <= 64, f"时延估计 {est} 偏离真值 {TRUE_DELAY} 太多"

    def test_erle_improves_over_time(self):
        """自适应必须真的在收敛 —— 后段要显著好于前段,而不是一条平线。"""
        mic, ref = _echo_only_scenario()
        m, e, _ = _run(mic, ref)
        third = m.size // 3
        early = _erle_db(m[:third], e[:third])
        late = _erle_db(m[2 * third :], e[2 * third :])
        assert late > early + 5.0, f"没有收敛趋势:前段 {early:.1f} dB → 后段 {late:.1f} dB"


# ── 2. 双讲:保住用户语音(比消回声更要紧)──────────────────────────────


class TestDoubleTalkPreservesNearEndSpeech:
    """一个把回声消干净、却把用户的话削掉的 AEC 是负资产:ASR 什么都听不清,而症状
    极难归因到 AEC。所以这一组的断言比 ERLE 那一组更严格。"""

    def test_near_end_speech_survives(self):
        mic, ref, near = _double_talk_scenario()
        _m, e, _aec = _run(mic, ref)
        dt = slice(80 * BLK, None)
        ne, res = near[dt], e[dt]
        corr = float(np.dot(ne, res) / (np.linalg.norm(ne) * np.linalg.norm(res) + 1e-12))
        assert corr > 0.9, f"残差与用户真实语音的相关只有 {corr:.3f} —— 用户的话被削掉了"

    def test_near_end_energy_is_not_eaten(self):
        """残差能量应与近端语音能量相当(±3 dB):既没被当成回声减掉,也没被放大。"""
        mic, ref, near = _double_talk_scenario()
        _m, e, _aec = _run(mic, ref)
        dt = slice(80 * BLK, None)
        ratio = _erle_db(e[dt], near[dt])  # 残差/近端
        assert -3.0 < ratio < 3.0, f"残差与近端能量差 {ratio:+.2f} dB,偏离太多"

    def test_double_talk_is_actually_detected(self):
        """DTD 必须真的开火。一次都不开火说明它形同虚设(而那正是最初实现的反面:
        它反过来把一切都判成双讲、导致永不收敛)。"""
        mic, ref, _near = _double_talk_scenario()
        _m, _e, aec = _run(mic, ref)
        assert aec.snapshot()["blocks_double_talk"] > 0, "DTD 从未开火"

    def test_adaptation_still_happens_outside_double_talk(self):
        """反面防线:DTD 不能把一切都判成双讲。最初的实现里 120 块只有 8 块真的更新过
        权重,于是永远收敛不了 —— 这个用例就是为了让那种退化立刻可见。"""
        mic, ref, _near = _double_talk_scenario()
        _m, _e, aec = _run(mic, ref)
        snap = aec.snapshot()
        assert (
            snap["blocks_adapted"] > snap["blocks_processed"] * 0.5
        ), f"只有 {snap['blocks_adapted']}/{snap['blocks_processed']} 块自适应过 —— DTD 过于激进"


# ── 3. 绝不放大 ────────────────────────────────────────────────────────────


class TestNeverAmplifies:
    """开发过程中两次实现错误都表现为"AEC 把回声放大了":时域版归一化写错到 −2274 dB;
    频域版功率估计从零平滑导致开头 −20 dB。所以单独立一组守住这条底线。"""

    def test_overall_erle_is_not_negative_on_echo_only(self):
        mic, ref = _echo_only_scenario()
        m, e, _ = _run(mic, ref)
        erle = _erle_db(m, e)
        assert erle > 0.0, f"整段 ERLE 为 {erle:.2f} dB —— AEC 净放大了回声"

    def test_no_catastrophic_block(self):
        """逐块检查:任何单块的残差都不该比该块麦克风信号大一个数量级以上。"""
        mic, ref = _echo_only_scenario()
        aec = AcousticEchoCanceller(AECConfig(sample_rate=SR))
        worst = 0.0
        for i in range(NB):
            aec.push_reference(ref[i * BLK : (i + 1) * BLK])
            m = mic[i * BLK : (i + 1) * BLK]
            e = np.asarray(aec.process(m))
            worst = min(worst, _erle_db(m, e))
        assert worst > -10.0, f"最差单块 ERLE 为 {worst:.2f} dB —— 出现过剧烈过冲"

    def test_power_estimate_is_seeded_from_the_first_block(self):
        """守住那处修复本身:功率估计若从全零平滑,首块步长会放大 1/(1-power_smooth) 倍。"""
        mic, ref = _echo_only_scenario()
        aec = AcousticEchoCanceller(AECConfig(sample_rate=SR))
        aec.push_reference(ref[:BLK])
        aec.process(mic[:BLK])
        assert aec._pow_init is True
        assert float(np.max(aec._pow)) > 0.0, "首块之后功率估计仍为零"


# ── 4. 降级永不断链 ────────────────────────────────────────────────────────


class TestGracefulDegradation:
    def test_bypasses_when_reference_is_silent(self):
        """扬声器没在放 → 没有回声可消。此时也**不能**自适应:那等于让滤波器去拟合
        噪声,把已经收敛的权重带跑偏。"""
        aec = AcousticEchoCanceller(AECConfig(sample_rate=SR))
        mic = _speechlike(3, BLK)
        out = aec.process(mic)
        assert np.allclose(np.asarray(out), mic), "参考安静时应原样返回"
        snap = aec.snapshot()
        assert snap["last_bypass_reason"] == "reference_silent"
        assert snap["blocks_adapted"] == 0

    def test_bypasses_when_disabled_by_env(self, monkeypatch):
        monkeypatch.setenv("GALAXY_AEC", "0")
        aec = AcousticEchoCanceller(AECConfig(sample_rate=SR))
        mic = _speechlike(3, BLK)
        aec.push_reference(_speechlike(4, BLK))
        out = aec.process(mic)
        assert np.allclose(np.asarray(out), mic)
        assert aec.snapshot()["last_bypass_reason"] == "disabled"

    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("GALAXY_AEC", raising=False)
        from core.multimodal.acoustic_echo_canceller import enabled

        assert enabled() is True

    def test_output_length_always_matches_input(self):
        """长度不符会让下游 VAD/ASR 拿到错长度的块。宁可旁通也不能返回错长度。"""
        mic, ref = _echo_only_scenario()
        aec = AcousticEchoCanceller(AECConfig(sample_rate=SR))
        for i in range(10):
            aec.push_reference(ref[i * BLK : (i + 1) * BLK])
            block = mic[i * BLK : (i + 1) * BLK]
            assert np.asarray(aec.process(block)).size == block.size

    def test_block_size_change_rebuilds_instead_of_failing(self):
        """块长由设备实际给的帧数决定,可能变。变了要重建,不能每块都"长度不符→旁通"
        —— 那等于 AEC 没接。"""
        mic, ref = _echo_only_scenario()
        aec = AcousticEchoCanceller(AECConfig(sample_rate=SR))
        aec.push_reference(ref[:BLK])
        aec.process(mic[:BLK])
        assert aec._n == BLK
        half = BLK // 2
        aec.push_reference(ref[BLK : BLK + half])
        out = aec.process(mic[BLK : BLK + half])
        assert aec._n == half, "块长变化后应重建滤波器"
        assert np.asarray(out).size == half

    def test_empty_block_is_safe(self):
        aec = AcousticEchoCanceller(AECConfig(sample_rate=SR))
        out = aec.process(np.zeros(0))
        assert np.asarray(out).size == 0

    def test_process_never_raises_on_garbage_reference(self):
        """参考信号来自另一条采集线程,形状不可控。任何异常都必须被吞掉并旁通。"""
        aec = AcousticEchoCanceller(AECConfig(sample_rate=SR))
        aec.push_reference("not an array")  # type: ignore[arg-type]
        aec.push_reference(None)  # type: ignore[arg-type]
        mic = _speechlike(3, BLK)
        assert np.asarray(aec.process(mic)).size == BLK

    def test_internal_error_falls_back_to_raw_mic(self, monkeypatch):
        aec = AcousticEchoCanceller(AECConfig(sample_rate=SR))
        aec.push_reference(_speechlike(4, BLK * 2))
        mic = _speechlike(3, BLK)

        def _boom(*_a, **_k):
            raise RuntimeError("injected")

        monkeypatch.setattr(aec, "_process_inner", _boom)
        out = aec.process(mic)
        assert np.allclose(np.asarray(out), mic), "内部异常时必须原样返回麦克风信号"
        assert aec.snapshot()["last_bypass_reason"] == "error"

    def test_reset_clears_filter_state(self):
        mic, ref = _echo_only_scenario()
        _m, _e, aec = _run(mic, ref, nb=20)
        assert aec.snapshot()["blocks_processed"] > 0
        aec.reset()
        snap = aec.snapshot()
        assert snap["blocks_processed"] == 0
        assert snap["delay_samples"] == 0


class TestSingleton:
    def test_singleton_is_rebuilt_when_sample_rate_changes(self):
        """滤波器长度与采样率绑定,换采样率必须重建,否则尾长语义悄悄变了。"""
        from core.multimodal.acoustic_echo_canceller import (
            get_echo_canceller,
            reset_echo_canceller,
        )

        reset_echo_canceller()
        a = get_echo_canceller(16000)
        assert get_echo_canceller(16000) is a
        b = get_echo_canceller(48000)
        assert b is not a
        assert b.config.sample_rate == 48000
        reset_echo_canceller()
