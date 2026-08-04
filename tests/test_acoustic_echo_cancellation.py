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


# ===========================================================================
# 第二级：残余回声抑制（RES / NLP）
# ===========================================================================
#
# 线性自适应滤波原理上只能消掉"参考信号的线性变换"。扬声器过载削波、外壳振动、
# 功放谐波失真带来的**非线性**回声，无论滤波器怎么收敛都消不掉 —— 这一级就是
# 为它们准备的。判据一律是**实测抑制量**，不是"代码跑到了这一行"。


def _res_farend(nblocks: int, n: int, sr: int, seed: int = 7):
    """有色（语音状）远端信号。每次调用**独立定种** —— 共享 RNG 会让 on/off 两次
    比的不是同一条信号，那样测出来的增益是假的（这个坑真的踩过）。"""
    import numpy as np

    rng = np.random.default_rng(seed)
    x = rng.standard_normal(nblocks * n)
    x = np.convolve(x, np.array([1.0, -0.9, 0.5, -0.2]))[: nblocks * n]
    env = 0.5 + 0.5 * np.sin(2 * np.pi * np.arange(x.size) / (sr * 0.7))
    return 0.35 * x * env


def _res_room(x, nonlinear: bool):
    """回声路径：线性冲激响应 +（可选）功放软削波 + 扬声器硬限幅。"""
    import numpy as np

    h = np.zeros(400)
    h[5], h[40], h[120], h[300] = 0.6, -0.3, 0.15, -0.05
    drive = np.clip(np.tanh(2.6 * x) / 2.6, -0.22, 0.22) if nonlinear else x
    return np.convolve(drive, h)[: x.size]


def _res_run(nonlinear: bool, res_on: bool, nblocks: int = 260, near=None):
    import numpy as np

    from core.multimodal.acoustic_echo_canceller import AcousticEchoCanceller, AECConfig

    np.random.seed(1234)  # 舒适噪声用全局 RNG，固定住才可复现
    sr, n = 16000, 256
    aec = AcousticEchoCanceller(AECConfig(sample_rate=sr, res_enabled=res_on))
    x = _res_farend(nblocks, n, sr)
    mic = _res_room(x, nonlinear) + (near if near is not None else 0.0)
    outs = []
    for i in range(nblocks):
        s = slice(i * n, (i + 1) * n)
        aec.push_reference(x[s])
        outs.append(np.asarray(aec.process(mic[s])))
    return aec, np.concatenate(outs), mic


def _res_erle(mic, out, lo: float = 0.5) -> float:
    import numpy as np

    i = int(len(mic) * lo)
    return 10.0 * float(np.log10((np.dot(mic[i:], mic[i:]) + 1e-12) / (np.dot(out[i:], out[i:]) + 1e-12)))


def test_res_buys_real_suppression_on_a_nonlinear_echo_path() -> None:
    """非线性回声路径上，RES 必须换来**可观测**的额外抑制（这正是它存在的理由）。"""
    a_off, o_off, mic = _res_run(True, False)
    a_on, o_on, mic2 = _res_run(True, True)
    import numpy as np

    assert np.allclose(mic, mic2), "两次输入不一致，比较无意义"
    gain = _res_erle(mic, o_on) - _res_erle(mic, o_off)
    assert gain > 6.0, f"RES 在非线性路径上只多消了 {gain:.2f} dB —— 等于没做"


def test_res_does_not_disturb_the_linear_stage() -> None:
    """RES 是**后置**滤波：线性级的 ERLE 必须逐位不受影响。"""
    a_off, _, _ = _res_run(True, False)
    a_on, _, _ = _res_run(True, True)
    assert (
        abs(a_off.stats.erle_db - a_on.stats.erle_db) < 1e-9
    ), f"RES 影响了线性级：{a_off.stats.erle_db} vs {a_on.stats.erle_db}"


def test_stats_report_the_two_stages_separately() -> None:
    """两级要分开报：合成一个数就分不出「线性级不行」和「非线性残余重」。"""
    aec, _, _ = _res_run(True, True)
    s = aec.snapshot()
    assert s["res_active"] is True
    assert s["total_erle_db"] > s["erle_db"], "总抑制没有高于线性级 —— RES 没起作用"
    assert abs(s["res_gain_db"] - (s["total_erle_db"] - s["erle_db"])) < 0.05
    assert s["leak_db"] > -60.0, "泄漏系数没被估计出来"


def _broadband_near(nb: int, n: int):
    """宽带、语音状的近端信号 —— 真实人声是宽带的。

    用窄带正弦当近端会把这条判据测虚：维纳增益在"近端主导的频点"上本来就≈1，
    窄带信号只占少数频点，于是下限设成多狠几乎都不影响结果。必须用宽带。
    """
    import numpy as np

    seg = slice(int(nb * n * 0.6), int(nb * n * 0.85))
    length = seg.stop - seg.start
    r = np.random.default_rng(99)
    sig = np.convolve(r.standard_normal(length), np.array([1.0, -0.85, 0.4]))[:length]
    sig = 0.3 * sig / np.sqrt(np.mean(sig**2)) * 0.3
    near = np.zeros(nb * n)
    near[seg] = sig
    return near, seg, sig


def _res_run_cfg(nb: int, near, **overrides):
    """跑一遍，允许覆盖 AEC 配置（用于对比不同双讲策略）。"""
    import numpy as np

    from core.multimodal.acoustic_echo_canceller import AcousticEchoCanceller, AECConfig

    np.random.seed(1234)
    sr, n = 16000, 256
    cfg = AECConfig(sample_rate=sr, res_enabled=True)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    aec = AcousticEchoCanceller(cfg)
    x = _res_farend(nb, n, sr)
    mic = _res_room(x, True) + near
    outs = []
    for i in range(nb):
        s = slice(i * n, (i + 1) * n)
        aec.push_reference(x[s])
        outs.append(np.asarray(aec.process(mic[s])))
    return aec, np.concatenate(outs)


def test_double_talk_uses_a_gentler_floor_than_far_end_only() -> None:
    """双讲时的宽松下限必须**买到**可测量的近端保留 —— 否则那个分档等于没写。

    判据是直接对比：同一条宽带近端信号下，「双讲放宽」必须比「双讲照样狠削」
    留住更多近端能量。实测约 +2 dB —— 不大，但真实：近端保护的**大头**其实是
    维纳增益本身（近端主导的频点上增益本来就≈1），这个分档是补上剩下那一块。
    """
    import numpy as np

    nb, n = 260, 256
    near, seg, sig = _broadband_near(nb, n)
    # 只变**一个**变量：下限。上一版同时变了下限和过减因子，于是去掉下限分支后
    # 仍然靠过减因子的差异通过 —— 那是条假钉，反向验证没红才发现。
    _, o_relax = _res_run_cfg(nb, near, res_dt_floor_db=-3.0)
    _, o_harsh = _res_run_cfg(nb, near, res_dt_floor_db=-18.0)
    keep_relax = float(np.dot(o_relax[seg], o_relax[seg]))
    keep_harsh = float(np.dot(o_harsh[seg], o_harsh[seg]))
    gain_db = 10.0 * np.log10((keep_relax + 1e-12) / (keep_harsh + 1e-12))
    assert gain_db > 0.4, f"双讲放宽只多留住 {gain_db:.2f} dB 近端 —— 这个分档没起作用"


def test_res_costs_little_near_end_speech_during_double_talk() -> None:
    """双讲时 RES 整体上只能少量削近端 —— 用户正说着话，狠削就是削用户。"""
    import numpy as np

    nb, n = 260, 256
    near, seg, _ = _broadband_near(nb, n)
    _, o_off, _ = _res_run(True, False, nb, near)
    _, o_on, _ = _res_run(True, True, nb, near)
    keep_off = float(np.dot(o_off[seg], o_off[seg]))
    keep_on = float(np.dot(o_on[seg], o_on[seg]))
    cost_db = 10.0 * np.log10((keep_on + 1e-12) / (keep_off + 1e-12))
    assert cost_db > -4.0, f"双讲时 RES 把近端削掉了 {-cost_db:.2f} dB"


def test_res_can_be_turned_off() -> None:
    """对照组：关掉 RES 时它必须真的不参与（否则上面几条测的不是 RES）。"""
    aec, _, _ = _res_run(True, False)
    s = aec.snapshot()
    assert s["res_active"] is False
    assert abs(s["total_erle_db"] - s["erle_db"]) < 1e-9


# ===========================================================================
# reset() 必须真的复位
# ===========================================================================


def test_reset_actually_clears_the_frequency_domain_filter() -> None:
    """``reset()`` 原先清的是 ``self._w``（小写）—— 旧时域 NLMS 的权重名。

    换成频域之后权重叫 ``self._W``（大写），Python 区分大小写，于是那行只是凭空
    造了个没人读的属性，**真正的滤波器一次都没被清过**：换设备/换房间之后上一处的
    冲激响应仍留在权重里，而 ``reset()`` 看起来是调用过的。
    """
    import numpy as np

    aec, _, _ = _res_run(True, True, 120)
    assert float(np.abs(aec._W).sum()) > 0.0, "滤波器压根没学到东西，这条判据无意义"
    aec.reset()
    assert float(np.abs(aec._W).sum()) == 0.0, "reset() 没有清掉频域滤波器权重"
    assert float(aec._leak.sum()) == 0.0, "reset() 没有清掉 RES 的泄漏系数"
    assert aec._gain_est == 0.0 and aec._blocks == 0 and aec._delay_locked is False


# ===========================================================================
# 双讲检测：路径增益的上涨要封顶（防正反馈自毒化）
# ===========================================================================


def test_dtd_detects_double_talk_instead_of_poisoning_itself() -> None:
    """DTD 漏判时会走 ``not double_talk`` 分支去**更新**路径增益，把近端能量算进去
    → 门槛抬高 → 更难触发。实测这条正反馈会把 DTD 拖成永不触发。

    判别区间在**安静的近端**：近端只比回声高一点点时，不封顶实测一块都检不出
    （幅度 0.1 / 0.15 / 0.2 全是 0），封顶后是 5 / 9 / 12 块。用大嗓门近端（0.3+）
    测这条会测虚 —— 那里封不封顶都检得出。"""
    import numpy as np

    nb, n = 200, 256
    seg = slice(int(nb * n * 0.6), int(nb * n * 0.85))
    t = np.arange(seg.stop - seg.start) / 16000.0
    near = np.zeros(nb * n)
    near[seg] = 0.15 * np.sin(2 * np.pi * 220 * t)  # 安静的近端 —— 判别区间
    aec, _ = _res_run_cfg(nb, near)
    assert aec.stats.blocks_double_talk > 0, "安静的近端一次都没检出双讲 —— DTD 已被自毒化"


def test_dtd_does_not_false_alarm_without_near_end_speech() -> None:
    """对照组：没有近端语音时不得误报双讲，否则滤波器永远不自适应。"""
    aec, _, _ = _res_run(True, True, 200)
    assert aec.stats.blocks_double_talk == 0, f"无近端却报了 {aec.stats.blocks_double_talk} 块双讲"
    assert aec.stats.blocks_adapted > 100, "自适应被误判的双讲冻住了"


def test_dtd_hangover_covers_the_whole_double_talk_stretch() -> None:
    """滞后保持必须把「双讲」铺满整段近端语音，而不是只盖住能量峰。

    真实双讲是连续的，能量判据只抓得住峰：实测一段连续近端里 50 块只有 7 块被判
    双讲，其余 43 块照旧自适应（把近端学进权重）、照旧狠削（削用户）。所有
    「双讲时退让」的参数因此几乎没有杠杆。判据是**覆盖块数**与**近端保留**两条一起看。
    """
    import numpy as np

    nb, n = 260, 256
    near, seg, _ = _broadband_near(nb, n)
    a_hold, o_hold = _res_run_cfg(nb, near, dtd_hangover_blocks=12)
    a_none, o_none = _res_run_cfg(nb, near, dtd_hangover_blocks=0)
    assert (
        a_hold.stats.blocks_double_talk > 2 * a_none.stats.blocks_double_talk
    ), f"滞后保持没有扩大覆盖: {a_none.stats.blocks_double_talk} → {a_hold.stats.blocks_double_talk}"
    keep_hold = float(np.dot(o_hold[seg], o_hold[seg]))
    keep_none = float(np.dot(o_none[seg], o_none[seg]))
    gain_db = 10.0 * np.log10((keep_hold + 1e-12) / (keep_none + 1e-12))
    assert gain_db > 0.5, f"滞后保持没有换来近端保留（只有 {gain_db:.2f} dB）"


def test_dtd_hangover_does_not_freeze_adaptation_without_near_end() -> None:
    """对照组：没有近端时滞后保持不得被触发，否则滤波器永远学不动。"""
    aec, _ = _res_run_cfg(200, 0.0)
    assert aec.stats.blocks_double_talk == 0
    assert aec.stats.blocks_adapted > 100, "无近端却冻住了自适应"
