"""Windows 上的系统播放声回环要**真的开得起来**,不是只让探测说"可用"。

真机(Windows,官方 sounddevice 0.5.x)每次启动:

    回环采集流打开失败,AEC 将没有参考信号:
      WasapiSettings.__init__() got an unexpected keyword argument 'loopback'

两层错:

1. 官方 sounddevice 的 ``WasapiSettings`` 从来没有 ``loopback`` 参数(那是某个分支的),
   这条路在官方包上根本走不通 —— 要抓 Windows 的系统播放声得用 PyAudioWPatch。
2. 判据是 ``hasattr(sd, "WasapiSettings")``:官方包都有这个类,于是探测报"可用",
   真开流才 TypeError。判据必须落在要用的那个参数上。

下面用假的 sounddevice / pyaudiowpatch 模块把整条路走一遍:选目标 → 开流 → 回调里
降混 + 降采样 → 采集服务收到块 → 停流时 PyAudio 被 terminate。
"""

from __future__ import annotations

import asyncio
import sys
import types

import numpy as np
import pytest

from core.multimodal import system_audio_ingest as ingest

# ── 假 sounddevice:官方 0.5.x 的 WasapiSettings 签名(没有 loopback)──────────


class _OfficialWasapiSettings:
    def __init__(self, exclusive=False, auto_convert=False, explicit_sample_format=False):
        pass


class _ForkWasapiSettings:
    def __init__(self, exclusive=False, loopback=False):
        pass


WIN_HOSTAPIS = [{"name": "MME", "default_output_device": 0}, {"name": "Windows WASAPI", "default_output_device": 1}]
WIN_DEVICES = [
    {"name": "Speakers (MME)", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2},
    {"name": "Speakers (Realtek) WASAPI", "hostapi": 1, "max_input_channels": 0, "max_output_channels": 2},
]


def _fake_sd(wasapi_cls):
    sd = types.ModuleType("sounddevice")
    sd.WasapiSettings = wasapi_cls
    sd.query_devices = lambda: WIN_DEVICES
    sd.query_hostapis = lambda: WIN_HOSTAPIS

    def _input_stream(**kw):  # 官方包上走到这里就说明又用回了 sounddevice 那条死路
        kw["extra_settings"]  # noqa: B018
        raise AssertionError("不该用 sounddevice 开 Windows 回环")

    sd.InputStream = _input_stream
    return sd


# ── 假 pyaudiowpatch:照它的公开 API 形状 ─────────────────────────────────────


class _FakePAStream:
    def __init__(self, kw):
        self.kw = kw
        self.started = self.stopped = self.closed = False

    def start_stream(self):
        self.started = True

    def stop_stream(self):
        self.stopped = True

    def close(self):
        self.closed = True


def _fake_pyaudiowpatch(native_rate=48000, channels=2, loopback_ok=True):
    mod = types.ModuleType("pyaudiowpatch")
    mod.paFloat32 = 1
    mod.paContinue = 0
    mod.paFramesPerBufferUnspecified = 0
    mod.instances = []

    class PyAudio:
        def __init__(self):
            self.terminated = False
            self.streams = []
            mod.instances.append(self)

        def get_default_wasapi_loopback(self):
            if not loopback_ok:
                raise LookupError("no default output")
            return {
                "index": 9,
                "name": "Speakers (Realtek) [Loopback]",
                "maxInputChannels": channels,
                "defaultSampleRate": float(native_rate),
            }

        def open(self, **kw):
            s = _FakePAStream(kw)
            self.streams.append(s)
            return s

        def terminate(self):
            self.terminated = True

    mod.PyAudio = PyAudio
    return mod


@pytest.fixture
def windows(monkeypatch):
    def _install(wasapi_cls=_OfficialWasapiSettings, pa=None):
        monkeypatch.setattr(ingest.platform, "system", lambda: "Windows")
        monkeypatch.setitem(sys.modules, "sounddevice", _fake_sd(wasapi_cls))
        if pa is None:
            monkeypatch.setitem(sys.modules, "pyaudiowpatch", None)  # import 会 ImportError
        else:
            monkeypatch.setitem(sys.modules, "pyaudiowpatch", pa)
        return pa

    return _install


# ── 判据落在参数上,不是 hasattr ─────────────────────────────────────────────


def test_official_sounddevice_is_not_mistaken_for_loopback_capable():
    assert (
        ingest.sounddevice_can_wasapi_loopback(types.SimpleNamespace(WasapiSettings=_OfficialWasapiSettings)) is False
    )
    assert ingest.sounddevice_can_wasapi_loopback(types.SimpleNamespace(WasapiSettings=_ForkWasapiSettings)) is True
    assert ingest.sounddevice_can_wasapi_loopback(types.SimpleNamespace()) is False


def test_without_pyaudiowpatch_the_probe_says_so_and_names_the_right_fix(windows):
    windows(pa=None)
    info = ingest.probe()
    assert info["available"] is False
    assert info["reason"] == ingest.REASON_NO_WASAPI_SUPPORT
    # 修复动作要是真能修好的那条 —— 不是"升级 sounddevice"(升级了也没有 loopback)
    assert "pip install PyAudioWPatch" in info["reason_text"]
    assert "升级 sounddevice" not in info["reason_text"]


def test_probe_and_capture_service_pick_the_same_pyaudiowpatch_target(windows):
    windows(pa=_fake_pyaudiowpatch())
    info = ingest.probe()
    assert info["available"] is True, info
    assert "via pyaudiowpatch" in info["target"]


def test_no_default_output_device_is_reported_as_such(windows):
    windows(pa=_fake_pyaudiowpatch(loopback_ok=False))
    info = ingest.probe()
    assert info["available"] is False
    assert info["reason"] == ingest.REASON_NO_LOOPBACK_DEVICE


def test_a_fork_that_really_has_loopback_keeps_the_sounddevice_path(windows):
    windows(wasapi_cls=_ForkWasapiSettings, pa=_fake_pyaudiowpatch())
    info = ingest.probe()
    assert info["available"] is True
    assert "via" not in info["target"]


# ── 真采集服务走一遍:开流参数 / 回调换算 / 停流收尾 ─────────────────────────


def test_capture_service_really_opens_the_loopback_and_receives_16k_mono(windows, monkeypatch):
    pa = windows(pa=_fake_pyaudiowpatch(native_rate=48000, channels=2))
    monkeypatch.setenv("GALAXY_SYSTEM_AUDIO_CAPTURE", "1")

    from core.multimodal.system_audio_capture_service import SystemAudioCaptureService

    svc = SystemAudioCaptureService(sample_rate=16000)
    got = []
    monkeypatch.setattr(svc, "_on_block", lambda mono: got.append(np.asarray(mono)))

    assert asyncio.run(svc.start()) is True, svc._unavailable_reason
    inst = pa.instances[-1]
    stream = inst.streams[-1]
    kw = stream.kw
    # WASAPI 共享模式只能按原生采样率开;设备是 PyAudioWPatch 给的那个回环端
    assert kw["rate"] == 48000
    assert kw["input"] is True and kw["input_device_index"] == 9
    assert kw["channels"] == 2 and kw["format"] == pa.paFloat32
    assert stream.started is True

    # 480 帧立体声(左 0.5,右 -0.1)@48k → 160 个单声道样本 @16k,值 = 平均 0.2
    frames = np.tile(np.array([0.5, -0.1], dtype=np.float32), 480)
    ret = kw["stream_callback"](frames.tobytes(), 480, None, 0)
    assert ret == (None, pa.paContinue)
    assert len(got) == 1
    assert got[0].shape == (160,)
    assert np.allclose(got[0], 0.2, atol=1e-6)

    asyncio.run(svc.stop())
    assert stream.stopped and stream.closed
    assert inst.terminated, "PyAudio 实例没 terminate —— 每次重启采集漏一个 PortAudio 句柄"


def test_a_bad_block_does_not_kill_the_stream(windows):
    pa = windows(pa=_fake_pyaudiowpatch())
    target, reason = ingest.choose_loopback_target(
        sys.modules["sounddevice"], WIN_DEVICES, WIN_HOSTAPIS, os_name="Windows"
    )
    assert reason == ingest.REASON_OK

    def _boom(*_a):
        raise RuntimeError("downstream exploded")

    s = ingest.open_loopback_stream(target, callback=_boom)
    cb = pa.instances[-1].streams[-1].kw["stream_callback"]
    # 回调里抛出去会把 PortAudio 的流弄死;必须吞掉并继续
    assert cb(np.zeros(960, dtype=np.float32).tobytes(), 480, None, 0) == (None, pa.paContinue)
    s.close()


# ── 降采样:块边界连续 ──────────────────────────────────────────────────────


@pytest.mark.parametrize("src", [48000, 44100])
def test_resampler_is_continuous_across_blocks(src):
    """同一段信号一次喂完和切成乱七八糟的块喂,结果要一样(否则每块边界一个咔哒,
    AEC 拿到的参考信号和扬声器实际放的对不上)。"""
    t = np.arange(src) / src
    sig = np.sin(2 * np.pi * 440 * t).astype(np.float32)

    whole = ingest._Resampler(src, 16000)(sig)

    r = ingest._Resampler(src, 16000)
    parts, i = [], 0
    for n in [1, 7, 441, 480, 1023, 3, 999] * 200:
        if i >= sig.size:
            break
        parts.append(r(sig[i : i + n]))
        i += n
    chunked = np.concatenate(parts)

    m = min(whole.size, chunked.size)
    assert abs(whole.size - chunked.size) <= 1
    assert abs(m - 16000) <= 1
    assert np.allclose(whole[:m], chunked[:m], atol=1e-5)
