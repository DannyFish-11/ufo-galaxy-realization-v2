"""core/multimodal/system_audio_ingest.py —— 系统播放声(回环)采集。

采的是什么、为什么必须单独采
----------------------------
麦克风回答"用户说了什么"。这里回答的是另一个问题:**用户此刻在听什么** —— 视频、
网课、游戏、会议里正在播的声音。两者语义完全不同,所以在
``DesktopPerceptionStore`` 里也是分槽的。

这条通路无法用现有的麦克风链路替代,也无法从浏览器侧拿到:

- ``getUserMedia`` 只给输入设备(麦克风),拿不到系统输出。
- ``getDisplayMedia`` 在 Chrome/Windows 上可以带 tab/系统音,但只覆盖被共享的那个
  来源,要用户每次手动授权选窗口,且 Firefox/Safari 支持残缺 —— 做不成"常驻感知"。
- 用麦克风"隔空听扬声器"不是替代:信号被房间噪声和音量设置污染,而且这样采回来的
  声音会和用户自己说的话混在同一路,再也分不开(反自激励门存在的原因正是这个)。

所以这件事只能在**电脑端本机**做。这是能力差异,不是性能优化 —— 换句话说,不做
原生/本机采集就根本没有这一路数据。

用 Python 做,不需要 C++ 层
--------------------------
Windows 上 WASAPI 支持 loopback:把一个**输出**设备当作输入流打开,采到的就是它正在
播的声音。

**官方 sounddevice 做不到这件事。** 这里以前写的是"``sd.WasapiSettings(loopback=True)``
直接暴露了这个能力" —— 不对:官方 sounddevice 的 ``WasapiSettings`` 从来只有
``exclusive / auto_convert / explicit_sample_format``(到 0.5.6 都是),没有 ``loopback``。
真机上的症状是 ``WasapiSettings.__init__() got an unexpected keyword argument 'loopback'``,
这条链路在 Windows 上**从来没通过**。

所以 Windows 走 **PyAudioWPatch**(PyAudio 的分支,专门补了 WASAPI 回环;模块名是
``pyaudiowpatch``,不和已装的 PyAudio 冲突)。万一装的是带 ``loopback`` 参数的
sounddevice 分支,也照样能用 —— 判据是"``WasapiSettings`` 真的认这个参数",不是
"有这个类"。

Linux 上 PulseAudio/PipeWire 把每个输出设备的 ``.monitor`` 源直接列成普通输入设备,
按名字挑出来即可。macOS 没有系统级回环(需 BlackHole 等虚拟声卡),故不支持。

优雅降级(与 ``audio_ingest.py`` 同一约定)
-----------------------------------------
``sounddevice`` 缺失、平台不支持、Windows 上没有能做回环的后端、找不到回环设备 ——
全部返回结构化的"不可用 + 原因",不抛异常、不影响任何主流程。原因是**明确文字**而
不是静默 False:这条链路一旦不通,症状是"模型不知道你在看什么",不给原因根本没法排查。
"""

from __future__ import annotations

import inspect
import logging
import platform
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.SystemAudioIngest")

#: Linux 上 PulseAudio/PipeWire 的回环源名字里必带的记号
_LINUX_MONITOR_MARKERS = ("monitor of", ".monitor", "monitor")

#: 不可用原因(结构化,便于路由/诊断面板直接展示)
REASON_OK = "ok"
REASON_NO_SOUNDDEVICE = "sounddevice_not_installed"
REASON_UNSUPPORTED_OS = "unsupported_os"
REASON_NO_WASAPI_SUPPORT = "no_wasapi_loopback_backend"
REASON_NO_WASAPI_HOSTAPI = "no_wasapi_hostapi"
REASON_NO_LOOPBACK_DEVICE = "no_loopback_device_found"
REASON_QUERY_FAILED = "device_query_failed"


@dataclass
class LoopbackTarget:
    """一个可用的回环采集目标。"""

    device: int
    name: str
    channels: int
    #: 是否需要 WASAPI 回环(Windows 专用)
    needs_wasapi_loopback: bool
    hostapi_name: str = ""
    #: 用哪个库打开:``sounddevice``(Linux monitor 源 / 带 loopback 参数的分支)或
    #: ``pyaudiowpatch``(Windows 常规情况)
    backend: str = "sounddevice"
    #: 设备原生采样率。WASAPI 共享模式只能按它打开,再在这边降到目标采样率。
    native_rate: int = 0

    def describe(self) -> str:
        mode = "WASAPI loopback" if self.needs_wasapi_loopback else "monitor source"
        via = f", via {self.backend}" if self.backend != "sounddevice" else ""
        return f"{self.name} [index={self.device}, ch={self.channels}, {mode}{via}]"


def sounddevice_can_wasapi_loopback(sd: Any) -> bool:
    """这版 sounddevice 的 ``WasapiSettings`` 是不是**真的认** ``loopback`` 参数。

    以前的判据是 ``hasattr(sd, "WasapiSettings")`` —— 官方版本都有这个类,但都不认这个
    参数,于是探测说"可用",真打开时 TypeError。判据必须落在要用的那个参数上。
    """
    ws = getattr(sd, "WasapiSettings", None)
    if ws is None:
        return False
    try:
        return "loopback" in inspect.signature(ws).parameters
    except (TypeError, ValueError):
        return False


def pyaudiowpatch_loopback_target() -> Tuple[Optional["LoopbackTarget"], str]:
    """用 PyAudioWPatch 找默认播放设备的回环端。没装 / 找不到都如实返回原因。"""
    try:
        import pyaudiowpatch as pyaudio
    except Exception:  # noqa: BLE001 — 没装是预期情形
        return None, REASON_NO_WASAPI_SUPPORT
    p = pyaudio.PyAudio()
    try:
        dev = p.get_default_wasapi_loopback()
    except Exception as exc:  # noqa: BLE001 — 没有默认播放设备 / WASAPI 不可用
        logger.debug("PyAudioWPatch 找不到默认回环设备: %s", exc)
        return None, REASON_NO_LOOPBACK_DEVICE
    finally:
        p.terminate()
    ch = int(dev.get("maxInputChannels", 0) or 0)
    if ch <= 0:
        return None, REASON_NO_LOOPBACK_DEVICE
    return (
        LoopbackTarget(
            device=int(dev["index"]),
            name=str(dev.get("name", "loopback")),
            channels=min(2, ch),
            needs_wasapi_loopback=True,
            hostapi_name="Windows WASAPI",
            backend="pyaudiowpatch",
            native_rate=int(float(dev.get("defaultSampleRate", 0) or 0)),
        ),
        REASON_OK,
    )


# ── 设备解析:抽成纯函数,可用假设备表完整单测 ────────────────────────────────


def _hostapi_name(hostapis: List[Dict[str, Any]], idx: Any) -> str:
    try:
        return str(hostapis[int(idx)].get("name", ""))
    except (IndexError, TypeError, ValueError):
        return ""


def resolve_loopback_target(
    devices: List[Dict[str, Any]],
    hostapis: List[Dict[str, Any]],
    *,
    os_name: str,
    has_wasapi_settings: bool,
) -> Tuple[Optional[LoopbackTarget], str]:
    """从设备表里挑出回环采集目标。返回 ``(target, reason)``。

    纯函数:只吃设备表,不碰音频栈。``sounddevice`` 的 ``query_devices()`` /
    ``query_hostapis()`` 返回的就是这两张表,所以真实行为可以用假表完整覆盖 ——
    这一层的判断逻辑不必等到有 Windows 机器才能验证。
    """
    system = (os_name or "").lower()

    if system == "windows":
        if not has_wasapi_settings:
            # PortAudio 支持,但 sounddevice 太老没有暴露 WasapiSettings
            return None, REASON_NO_WASAPI_SUPPORT
        wasapi_idx = [i for i, h in enumerate(hostapis) if "wasapi" in str(h.get("name", "")).lower()]
        if not wasapi_idx:
            return None, REASON_NO_WASAPI_HOSTAPI
        # WASAPI loopback 要打开的是【输出】设备(max_output_channels > 0)。
        # 优先该 hostapi 的默认输出设备 —— 那才是用户真正在听的那一个。
        preferred: List[int] = []
        for i in wasapi_idx:
            default_out = hostapis[i].get("default_output_device")
            if isinstance(default_out, int) and default_out >= 0:
                preferred.append(default_out)
        ordered = preferred + [
            idx
            for idx, dev in enumerate(devices)
            if idx not in preferred
            and int(dev.get("hostapi", -1)) in wasapi_idx
            and int(dev.get("max_output_channels", 0) or 0) > 0
        ]
        for idx in ordered:
            try:
                dev = devices[idx]
            except IndexError:
                continue
            if int(dev.get("hostapi", -1)) not in wasapi_idx:
                continue
            ch = int(dev.get("max_output_channels", 0) or 0)
            if ch <= 0:
                continue
            return (
                LoopbackTarget(
                    device=idx,
                    name=str(dev.get("name", f"device-{idx}")),
                    # 回环流的通道数取输出设备的通道数(通常 2);下游会降混成单声道
                    channels=min(2, ch),
                    needs_wasapi_loopback=True,
                    hostapi_name=_hostapi_name(hostapis, dev.get("hostapi")),
                ),
                REASON_OK,
            )
        return None, REASON_NO_LOOPBACK_DEVICE

    if system == "linux":
        # PulseAudio/PipeWire 把输出设备的 monitor 源列成普通输入设备
        for idx, dev in enumerate(devices):
            name = str(dev.get("name", ""))
            ch = int(dev.get("max_input_channels", 0) or 0)
            if ch <= 0:
                continue
            if any(mark in name.lower() for mark in _LINUX_MONITOR_MARKERS):
                return (
                    LoopbackTarget(
                        device=idx,
                        name=name,
                        channels=min(2, ch),
                        needs_wasapi_loopback=False,
                        hostapi_name=_hostapi_name(hostapis, dev.get("hostapi")),
                    ),
                    REASON_OK,
                )
        return None, REASON_NO_LOOPBACK_DEVICE

    # macOS 没有系统级回环(需 BlackHole 之类虚拟声卡),其它平台同样不支持。
    return None, REASON_UNSUPPORTED_OS


def choose_loopback_target(
    sd: Any,
    devices: List[Dict[str, Any]],
    hostapis: List[Dict[str, Any]],
    *,
    os_name: str,
) -> Tuple[Optional[LoopbackTarget], str]:
    """探测(``probe``)和真采集(采集服务)共用的**唯一**选目标入口。

    以前两边各算一遍,判据还不一样(一边 ``hasattr``),于是探测说可用、真开流就崩。
    sounddevice 这条路走不通只是因为"它不认 loopback 参数"时,换 PyAudioWPatch。
    """
    target, reason = resolve_loopback_target(
        devices,
        hostapis,
        os_name=os_name,
        has_wasapi_settings=sounddevice_can_wasapi_loopback(sd),
    )
    if target is None and reason == REASON_NO_WASAPI_SUPPORT:
        target, reason = pyaudiowpatch_loopback_target()
    return target, reason


def _reason_text(reason: str) -> str:
    """把结构化原因翻成可直接给人看的一句话(含修复动作)。"""
    return {
        REASON_OK: "可用",
        REASON_NO_SOUNDDEVICE: "未安装 sounddevice —— 运行: pip install sounddevice",
        REASON_UNSUPPORTED_OS: (
            "当前系统没有系统级回环采集:Windows 走 WASAPI loopback、"
            "Linux 走 PulseAudio/PipeWire 的 .monitor 源;macOS 需装 BlackHole 之类虚拟声卡"
        ),
        REASON_NO_WASAPI_SUPPORT: (
            "Windows 上抓系统播放声要装 PyAudioWPatch(官方 sounddevice 没有 WASAPI 回环,"
            "升级它也没用)—— 运行: pip install PyAudioWPatch"
        ),
        REASON_NO_WASAPI_HOSTAPI: "PortAudio 未编出 WASAPI 后端,无法做回环采集",
        REASON_NO_LOOPBACK_DEVICE: (
            "找不到回环设备。Windows:确认有默认播放设备;"
            "Linux:确认 PulseAudio/PipeWire 在跑(pactl list sources short 应能看到 .monitor)"
        ),
        REASON_QUERY_FAILED: "查询音频设备失败(音频栈异常)",
    }.get(reason, reason)


def probe() -> Dict[str, Any]:
    """探测本机能否做系统播放声采集。永不抛出。

    返回 ``{available, reason, reason_text, target, os}``。这是给
    ``/api/perception/desktop/system_audio/probe`` 和诊断面板用的**唯一**判断入口 ——
    调用方不要自己去猜平台。
    """
    os_name = platform.system()
    try:
        import sounddevice as sd
    except Exception as exc:  # noqa: BLE001 — 缺包是预期情形,不是错误
        logger.debug("sounddevice 不可用,系统播放声采集关闭: %s", exc)
        return {
            "available": False,
            "reason": REASON_NO_SOUNDDEVICE,
            "reason_text": _reason_text(REASON_NO_SOUNDDEVICE),
            "target": None,
            "os": os_name,
        }

    try:
        devices = [dict(d) for d in sd.query_devices()]
        hostapis = [dict(h) for h in sd.query_hostapis()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("查询音频设备失败,系统播放声采集不可用: %s", exc)
        return {
            "available": False,
            "reason": REASON_QUERY_FAILED,
            "reason_text": f"{_reason_text(REASON_QUERY_FAILED)}: {exc}",
            "target": None,
            "os": os_name,
        }

    target, reason = choose_loopback_target(sd, devices, hostapis, os_name=os_name)
    if target is None:
        # WARNING 而非 debug:这条链路不通的症状是"模型不知道你在看什么",
        # 在 debug 级别下用户永远查不到原因。
        logger.warning("系统播放声采集不可用(%s):%s", reason, _reason_text(reason))
    else:
        logger.info("系统播放声采集目标:%s", target.describe())
    return {
        "available": target is not None,
        "reason": reason,
        "reason_text": _reason_text(reason),
        "target": target.describe() if target else None,
        "os": os_name,
    }


def open_loopback_stream(
    target: LoopbackTarget,
    *,
    sample_rate: int = 16000,
    blocksize: int = 0,
    callback: Any = None,
) -> Any:
    """按目标打开回环输入流。返回**未启动**的流(有 ``start/stop/close``);失败抛原始异常。

    回调签名一律是 sounddevice 的 ``callback(indata, frames, time_info, status)``,
    ``indata`` 形状 ``(frames, channels)``、float32、采样率 ``sample_rate`` —— 不管底下
    是哪个库,调用方看到的都一样。

    刻意**不**吞异常:调用方(采集循环)才知道该重试、该降级还是该放弃,在这里静默
    吞掉只会变成"流没开起来但谁也不知道"。
    """
    if target.backend == "pyaudiowpatch":
        return _PyAudioWPatchLoopbackStream(target, sample_rate=sample_rate, blocksize=blocksize, callback=callback)

    import sounddevice as sd

    extra = None
    if target.needs_wasapi_loopback:
        extra = sd.WasapiSettings(loopback=True)
    return sd.InputStream(
        samplerate=sample_rate,
        channels=target.channels,
        dtype="float32",
        blocksize=blocksize,
        device=target.device,
        callback=callback,
        extra_settings=extra,
    )


class _Resampler:
    """逐块、带状态的单声道降采样(块边界连续,不会每块一个咔哒)。

    WASAPI 共享模式只能按设备原生采样率(一般 48000 / 44100)开流,下游 AEC 和感知库要
    ``sample_rate``(16000)。整数倍(48000→16000)按组求平均 —— 顺带做了最粗的低通;
    非整数倍(44100→16000)线性插值,跨块保留相位。
    """

    def __init__(self, src_rate: int, dst_rate: int) -> None:
        import numpy as np

        self._np = np
        self.src = int(src_rate)
        self.dst = int(dst_rate)
        self._carry = np.zeros(0, dtype=np.float32)
        self._pos = 0.0  # 下一个输出样本在 (carry + 新块) 里的位置

    def __call__(self, mono: Any) -> Any:
        np = self._np
        x = np.asarray(mono, dtype=np.float32).reshape(-1)
        if self.src == self.dst or self.src <= 0:
            return x
        buf = np.concatenate([self._carry, x]) if self._carry.size else x
        if self.src % self.dst == 0:
            k = self.src // self.dst
            n = (buf.size // k) * k
            self._carry = buf[n:].copy()
            return buf[:n].reshape(-1, k).mean(axis=1).astype(np.float32)
        step = self.src / self.dst
        if buf.size < 2:
            self._carry = buf.copy()
            return np.zeros(0, dtype=np.float32)
        idx = np.arange(self._pos, buf.size - 1, step)
        out = np.interp(idx, np.arange(buf.size), buf).astype(np.float32)
        nxt = (idx[-1] + step) if idx.size else self._pos
        # 留最后一个样本给下一块做插值左端点
        self._carry = buf[-1:].copy()
        self._pos = nxt - (buf.size - 1)
        return out


class _PyAudioWPatchLoopbackStream:
    """把 PyAudioWPatch 的回环流包成和 ``sd.InputStream`` 一样用的样子。

    只暴露采集服务用到的 ``start / stop / close``。原生采样率开流、在回调里降混 + 降采样,
    再按 sounddevice 的回调签名交给调用方。
    """

    def __init__(self, target: LoopbackTarget, *, sample_rate: int, blocksize: int, callback: Any) -> None:
        import numpy as np
        import pyaudiowpatch as pyaudio

        self._np = np
        self._pa_mod = pyaudio
        self._channels = int(target.channels)
        rate = int(target.native_rate) or int(sample_rate)
        self._resample = _Resampler(rate, sample_rate)
        self._user_cb = callback
        self._pa = pyaudio.PyAudio()
        try:
            self._stream = self._pa.open(
                format=pyaudio.paFloat32,
                channels=self._channels,
                rate=rate,
                input=True,
                input_device_index=int(target.device),
                frames_per_buffer=int(blocksize) if blocksize else pyaudio.paFramesPerBufferUnspecified,
                stream_callback=self._on_data,
                start=False,
            )
        except Exception:
            self._pa.terminate()
            raise

    def _on_data(self, in_data: Any, frame_count: int, time_info: Any, status: Any) -> Any:
        np = self._np
        try:
            block = np.frombuffer(in_data, dtype=np.float32)
            if self._channels > 1:
                block = block.reshape(-1, self._channels).mean(axis=1)
            mono = self._resample(block)
            if mono.size and self._user_cb is not None:
                self._user_cb(mono.reshape(-1, 1), int(mono.size), time_info, status)
        except Exception as exc:  # noqa: BLE001 — 抛进 PortAudio 回调线程会把流弄死
            logger.debug("PyAudioWPatch 回环块处理失败(丢弃本块): %s", exc)
        return (None, self._pa_mod.paContinue)

    def start(self) -> None:
        self._stream.start_stream()

    def stop(self) -> None:
        self._stream.stop_stream()

    def close(self) -> None:
        try:
            self._stream.close()
        finally:
            self._pa.terminate()


def downmix_to_mono(block: Any) -> Any:
    """把多声道回环数据降混成单声道(ASR/模型都只要单声道)。

    ``block`` 形状为 ``(frames, channels)``;单声道时原样压平。
    """
    import numpy as np

    arr = np.asarray(block)
    if arr.ndim == 1:
        return arr
    if arr.shape[1] == 1:
        return arr[:, 0]
    return arr.mean(axis=1)
