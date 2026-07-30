"""回环采集服务 + AEC 接线的行为测试。

本文件的重点是**接线**,不是算法
--------------------------------
AEC 的算法效果由 ``tests/test_acoustic_echo_cancellation.py`` 单独钉。这里钉的是另一件
同样容易出错、而且出错时更难发现的事:**它到底有没有真的接在链路上**。

一个"装配好了但没人调用"的 AEC 的症状是:什么都不报错、日志一片安静、回声照旧存在。
所以这里的核心用例是 ``TestAecIsActuallyWiredIntoTheMicPath`` —— 它走
``AudioIngestPipeline._process_chunk`` 本体,断言**下游回调真的拿到了去回声后的信号**。
只测"AEC 类本身好用"完全测不出接线断掉。

同理,``ensure_started`` 的存在也是为了防这一类问题:AEC 没有参考信号时会一直走
``reference_silent`` 旁通 —— 完全静默地什么也不做。所以麦克风链路启动时要顺手把回环
采集拉起来,而不是指望有人在别处编排好。
"""

from __future__ import annotations

import asyncio
import base64
import io
import wave

import pytest

np = pytest.importorskip("numpy")

SR = 16000
BLK = 1600
NB = 120


def _echo_scenario():
    """已知回声路径:参考信号 → 卷积 RIR → 加 50ms 整体时延 → 麦克风信号。"""
    rng = np.random.default_rng(7)
    h = rng.standard_normal(400) * np.exp(-np.arange(400) / 60.0)
    h = h / (np.abs(h).sum() + 1e-9) * 0.8
    x = rng.standard_normal(NB * BLK)
    win = np.hanning(64) / np.hanning(64).sum()
    ref = np.convolve(x, win, "same") * (0.5 + 0.5 * np.sin(2 * np.pi * np.arange(NB * BLK) / (SR * 0.7)))
    mic = np.concatenate([np.zeros(800), np.convolve(ref, h)[: ref.size]])[: ref.size]
    return mic, ref


def _erle_db(mic, err) -> float:
    return float(10 * np.log10((mic @ mic + 1e-12) / (err @ err + 1e-12)))


@pytest.fixture(autouse=True)
def _clean_singletons():
    from core.multimodal.acoustic_echo_canceller import reset_echo_canceller
    from core.multimodal.system_audio_capture_service import reset_system_audio_capture

    reset_echo_canceller()
    reset_system_audio_capture()
    yield
    reset_echo_canceller()
    reset_system_audio_capture()


# ── 接线:AEC 真的在 VAD 之前生效了吗 ──────────────────────────────────────


class TestAecIsActuallyWiredIntoTheMicPath:
    """走 ``AudioIngestPipeline._process_chunk`` 本体。

    "AEC 类本身好用"和"AEC 接在链路上"是两件事,后者断掉时症状是完全静默的:不报错、
    不打日志、回声照旧。所以必须从链路入口喂进去、从链路出口断言。
    """

    def test_downstream_callbacks_receive_echo_cancelled_audio(self):
        from core.multimodal.acoustic_echo_canceller import get_echo_canceller
        from core.multimodal.audio_ingest import AudioIngestConfig, AudioIngestPipeline

        mic, ref = _echo_scenario()
        aec = get_echo_canceller(SR)
        pipe = AudioIngestPipeline(AudioIngestConfig(sample_rate=SR, chunk_duration_ms=100))
        seen: list = []
        pipe.add_callback(lambda st, q: seen.append(st.samples.copy()))

        async def _go():
            for i in range(NB):
                aec.push_reference(ref[i * BLK : (i + 1) * BLK])
                await pipe._process_chunk(mic[i * BLK : (i + 1) * BLK].astype(np.float32))

        asyncio.run(_go())

        got = np.concatenate(seen)
        q = got.size * 3 // 4
        erle = _erle_db(mic[: got.size][q:], got[q:])
        assert erle > 15.0, f"下游只拿到 {erle:.1f} dB 的抑制 —— AEC 没有真正接在 VAD 之前"

    def test_mic_path_is_unharmed_when_there_is_no_reference(self):
        """没有回环设备的机器上(参考信号恒为空),麦克风信号必须原样通过。

        这是最常见的部署情形(Linux 无 monitor 源、macOS、未装 sounddevice),
        绝不能因为接了 AEC 就把这些机器的语音链路弄坏。
        """
        from core.multimodal.audio_ingest import AudioIngestConfig, AudioIngestPipeline

        mic, _ref = _echo_scenario()
        pipe = AudioIngestPipeline(AudioIngestConfig(sample_rate=SR, chunk_duration_ms=100))
        seen: list = []
        pipe.add_callback(lambda st, q: seen.append(st.samples.copy()))

        async def _go():
            for i in range(10):
                await pipe._process_chunk(mic[i * BLK : (i + 1) * BLK].astype(np.float32))

        asyncio.run(_go())
        got = np.concatenate(seen)
        assert np.allclose(got, mic[: got.size], atol=1e-6), "无参考信号时不该改动麦克风信号"

    def test_aec_failure_does_not_break_the_mic_path(self, monkeypatch):
        """AEC 内部炸了,上行语音通路也必须继续 —— 留着回声远好过彻底聋掉。"""
        import core.multimodal.acoustic_echo_canceller as aec_mod
        from core.multimodal.audio_ingest import AudioIngestConfig, AudioIngestPipeline

        def _boom(*_a, **_k):
            raise RuntimeError("injected")

        monkeypatch.setattr(aec_mod, "get_echo_canceller", _boom)
        mic, _ = _echo_scenario()
        pipe = AudioIngestPipeline(AudioIngestConfig(sample_rate=SR, chunk_duration_ms=100))
        seen: list = []
        pipe.add_callback(lambda st, q: seen.append(st.samples.copy()))
        asyncio.run(pipe._process_chunk(mic[:BLK].astype(np.float32)))
        assert len(seen) == 1
        assert np.allclose(seen[0], mic[:BLK], atol=1e-6)


# ── 回环采集服务 ───────────────────────────────────────────────────────────


class TestWavEncoding:
    def test_roundtrips_as_16bit_mono_wav(self):
        from core.multimodal.system_audio_capture_service import pcm_to_wav_base64

        pcm = (np.sin(2 * np.pi * 440 * np.arange(SR) / SR) * 0.5).astype(np.float32)
        raw = base64.b64decode(pcm_to_wav_base64(pcm, SR))
        with wave.open(io.BytesIO(raw)) as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == SR
            assert wf.getnframes() == SR

    def test_empty_pcm_yields_empty_string(self):
        from core.multimodal.system_audio_capture_service import pcm_to_wav_base64

        assert pcm_to_wav_base64(np.zeros(0), SR) == ""

    def test_clipping_does_not_wrap_around(self):
        """超幅样本必须限幅,不能在转 int16 时溢出翻成反相 —— 那会变成刺耳的爆音,
        而且作为 AEC 参考信号会直接把滤波器带歪。"""
        from core.multimodal.system_audio_capture_service import pcm_to_wav_base64

        pcm = np.array([5.0, -5.0], dtype=np.float32)
        raw = base64.b64decode(pcm_to_wav_base64(pcm, SR))
        with wave.open(io.BytesIO(raw)) as wf:
            vals = np.frombuffer(wf.readframes(2), dtype="<i2")
        assert vals[0] > 0 and vals[1] < 0, f"限幅失效,发生了溢出翻转: {vals}"


class TestCaptureServiceDegradation:
    def test_start_returns_false_with_a_reason_when_unavailable(self):
        """本环境没有 sounddevice。``start()`` 必须如实返回 False 并给出原因,
        不能抛异常、也不能假装启动成功。"""
        from core.multimodal.system_audio_capture_service import (
            SystemAudioCaptureService,
        )

        svc = SystemAudioCaptureService(sample_rate=SR)
        assert asyncio.run(svc.start()) is False
        status = svc.status()
        assert status["running"] is False
        assert status["unavailable_reason"], "不可用时必须给出原因"

    def test_disabled_by_env(self, monkeypatch):
        from core.multimodal.system_audio_capture_service import (
            SystemAudioCaptureService,
        )

        monkeypatch.setenv("GALAXY_SYSTEM_AUDIO_CAPTURE", "0")
        svc = SystemAudioCaptureService(sample_rate=SR)
        assert asyncio.run(svc.start()) is False
        assert svc.status()["unavailable_reason"] == "disabled_by_env"

    def test_enabled_by_default(self, monkeypatch):
        from core.multimodal.system_audio_capture_service import enabled

        monkeypatch.delenv("GALAXY_SYSTEM_AUDIO_CAPTURE", raising=False)
        assert enabled() is True

    def test_stop_is_idempotent_and_never_raises(self):
        from core.multimodal.system_audio_capture_service import (
            SystemAudioCaptureService,
        )

        svc = SystemAudioCaptureService(sample_rate=SR)
        asyncio.run(svc.stop())
        asyncio.run(svc.stop())

    def test_ensure_started_without_event_loop_is_safe(self):
        """同步上下文里调用不能抛 —— 麦克风链路可能在没有事件循环的地方初始化。"""
        from core.multimodal.system_audio_capture_service import ensure_started

        ensure_started(SR)  # 无运行中事件循环,应静默跳过

    def test_singleton_rebuilt_on_sample_rate_change(self):
        from core.multimodal.system_audio_capture_service import (
            get_system_audio_capture,
        )

        a = get_system_audio_capture(16000)
        assert get_system_audio_capture(16000) is a
        b = get_system_audio_capture(48000)
        assert b is not a and b.sample_rate == 48000


class TestBlockFanoutHonoursPrivacyAndBounds:
    """``_on_block`` 是回环采集的分发点。这里直接驱动它 —— 不需要真实音频设备。"""

    def _svc(self):
        from core.multimodal.system_audio_capture_service import (
            SystemAudioCaptureService,
        )

        return SystemAudioCaptureService(sample_rate=SR, snapshot_sec=0.0)

    def test_reference_is_pushed_to_the_aec(self):
        from core.multimodal.acoustic_echo_canceller import get_echo_canceller

        svc = self._svc()
        svc._on_block(np.ones(BLK, dtype=np.float32) * 0.1)
        assert svc.status()["ref_pushed"] == 1
        # 参考真的进了 AEC 的历史缓冲(不是只加了个计数器)
        aec = get_echo_canceller(SR)
        assert float(np.max(np.abs(aec._ref_buf))) > 0.0

    def test_snapshot_reaches_the_perception_store(self):
        from core.perception.desktop_perception_store import (
            get_desktop_perception_store,
        )

        store = get_desktop_perception_store()
        store.resume("test-setup")
        before = store.status()["system_audio_received"]
        svc = self._svc()  # snapshot_sec=0 → 每块都送
        svc._on_block(np.ones(BLK, dtype=np.float32) * 0.1)
        assert store.status()["system_audio_received"] == before + 1
        assert svc.status()["snapshots_pushed"] == 1

    def test_nothing_is_captured_while_privacy_is_paused(self):
        """暂停期间不是"采了不用",而是**连缓冲都不放** —— 否则恢复后会一次性把暂停
        期间的内容送出去,那正是隐私急停要避免的事。"""
        from core.perception.desktop_perception_store import (
            get_desktop_perception_store,
        )

        store = get_desktop_perception_store()
        store.pause("test")
        try:
            svc = self._svc()
            svc._on_block(np.ones(BLK, dtype=np.float32) * 0.1)
            s = svc.status()
            assert s["blocks_dropped_paused"] == 1
            assert s["ref_pushed"] == 0, "暂停期间连 AEC 参考信号也不该推"
            assert s["buffered_samples"] == 0, "暂停期间不该留任何缓冲"
        finally:
            store.resume("test")

    def test_privacy_state_unreadable_is_treated_as_paused(self, monkeypatch):
        """fail-closed:读不到隐私状态时按【已暂停】处理。这里刻意与仓库其它地方的
        fail-open 相反 —— 判断不了就继续采系统声,等于拿用户正在听的全部内容赌一个
        未知状态。"""
        import core.perception.desktop_perception_store as store_mod

        def _boom():
            raise RuntimeError("injected")

        monkeypatch.setattr(store_mod, "get_desktop_perception_store", _boom)
        svc = self._svc()
        svc._on_block(np.ones(BLK, dtype=np.float32) * 0.1)
        assert svc.status()["blocks_dropped_paused"] == 1
        assert svc.status()["ref_pushed"] == 0

    def test_buffer_is_bounded_when_perception_never_drains(self):
        """感知库不可用时缓冲不能无界增长。"""
        from core.multimodal.system_audio_capture_service import (
            _MAX_BUFFER_SEC,
            SystemAudioCaptureService,
        )
        from core.perception.desktop_perception_store import (
            get_desktop_perception_store,
        )

        get_desktop_perception_store().resume("test-setup")
        # snapshot_sec 很大 → 永不触发编码送出,只会一直攒
        svc = SystemAudioCaptureService(sample_rate=SR, snapshot_sec=10**6)
        for _ in range(int(_MAX_BUFFER_SEC * 3)):
            svc._on_block(np.ones(SR, dtype=np.float32) * 0.1)  # 每块 1 秒
        assert svc.status()["buffered_samples"] <= int(_MAX_BUFFER_SEC * SR)

    def test_perception_feed_can_be_disabled_independently(self, monkeypatch):
        """只要回声消除、不想让模型听见系统声 —— 两个开关必须能分开。"""
        from core.perception.desktop_perception_store import (
            get_desktop_perception_store,
        )

        monkeypatch.setenv("GALAXY_SYSTEM_AUDIO_TO_PERCEPTION", "0")
        store = get_desktop_perception_store()
        store.resume("test-setup")
        before = store.status()["system_audio_received"]
        svc = self._svc()
        svc._on_block(np.ones(BLK, dtype=np.float32) * 0.1)
        assert svc.status()["ref_pushed"] == 1, "AEC 参考信号仍应照常推"
        assert store.status()["system_audio_received"] == before, "不该送进感知库"

    def test_block_fanout_never_raises(self):
        svc = self._svc()
        for bad in (None, "garbage", np.zeros(0)):
            svc._on_block(bad)  # type: ignore[arg-type]


class TestBufferNeverCrossesThePrivacyBoundary:
    """实测过的真实泄露:``pause()`` 只清感知库自己的缓存,**碰不到**采集服务的待送缓冲。
    于是"采几秒 → 暂停 → 恢复"之后,那段**暂停之前**攒的音频会被原样送进感知库。
    若暂停期间回环流本就没有新块(扬声器静音),连"看见 paused 再清"的机会都没有。

    修复用感知库的 ``epoch`` 世代号:它在每次 pause/resume 都自增,所以"暂停过"这件事
    在恢复之后依然可见 —— 这正是 ``epoch`` 当初为 ambient 帧差指纹设计的用途。
    """

    def _svc(self, snapshot_sec):
        from core.multimodal.system_audio_capture_service import (
            SystemAudioCaptureService,
        )

        return SystemAudioCaptureService(sample_rate=SR, snapshot_sec=snapshot_sec)

    def test_audio_buffered_before_a_pause_is_not_delivered_after_resume(self):
        from core.perception.desktop_perception_store import (
            get_desktop_perception_store,
        )

        store = get_desktop_perception_store()
        store.resume("test-setup")
        svc = self._svc(snapshot_sec=10**6)  # 永不自动送出,只攒
        block = np.ones(BLK, dtype=np.float32) * 0.1
        for _ in range(5):
            svc._on_block(block)
        assert svc.status()["buffered_samples"] > 0, "前提:暂停前确实攒了音频"

        store.pause("user")
        store.resume("user")

        svc.snapshot_sec = 0.0  # 现在每块都会送
        before = store.status()["system_audio_received"]
        svc._on_block(block)
        after = store.status()["system_audio_received"]

        assert svc.status()["buffers_dropped_epoch"] >= 1, "跨越隐私边界的缓冲没有被丢弃"
        # 送出去的那一段只能是"恢复之后"这一块,不含暂停前的 5 块
        assert after == before + 1
        assert svc.status()["buffered_samples"] == 0

    def test_pause_alone_also_invalidates_the_buffer(self):
        """只暂停、还没恢复时也要作废 —— epoch 已经变了。"""
        from core.perception.desktop_perception_store import (
            get_desktop_perception_store,
        )

        store = get_desktop_perception_store()
        store.resume("test-setup")
        svc = self._svc(snapshot_sec=10**6)
        for _ in range(3):
            svc._on_block(np.ones(BLK, dtype=np.float32) * 0.1)
        store.pause("user")
        try:
            svc._on_block(np.ones(BLK, dtype=np.float32) * 0.1)
            assert svc.status()["buffered_samples"] == 0
            assert svc.status()["buffers_dropped_epoch"] >= 1
        finally:
            store.resume("test")

    def test_no_spurious_drop_on_the_first_block(self):
        """世代号初始化成当前值,首块不该白丢一次(否则每次新建服务都少一段音频)。"""
        from core.perception.desktop_perception_store import (
            get_desktop_perception_store,
        )

        get_desktop_perception_store().resume("test-setup")
        svc = self._svc(snapshot_sec=10**6)
        svc._on_block(np.ones(BLK, dtype=np.float32) * 0.1)
        assert svc.status()["buffers_dropped_epoch"] == 0
        assert svc.status()["buffered_samples"] == BLK

    def test_unreadable_epoch_is_treated_as_changed(self, monkeypatch):
        """读不到世代号时按【已变化】处理(丢缓冲)—— 与 fail-closed 的隐私判定一致。"""
        import core.perception.desktop_perception_store as store_mod
        from core.perception.desktop_perception_store import (
            get_desktop_perception_store,
        )

        get_desktop_perception_store().resume("test-setup")
        svc = self._svc(snapshot_sec=10**6)
        svc._on_block(np.ones(BLK, dtype=np.float32) * 0.1)
        assert svc.status()["buffered_samples"] > 0

        def _boom():
            raise RuntimeError("injected")

        monkeypatch.setattr(store_mod, "get_desktop_perception_store", _boom)
        svc._on_block(np.ones(BLK, dtype=np.float32) * 0.1)
        assert svc.status()["buffered_samples"] == 0
