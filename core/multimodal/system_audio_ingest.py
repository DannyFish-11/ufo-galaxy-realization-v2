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
播的声音。``sounddevice``(PortAudio)通过 ``sd.WasapiSettings(loopback=True)`` 直接
暴露了这个能力,和现有麦克风链路用的是同一个库、同一套 ``InputStream``。
Linux 上 PulseAudio/PipeWire 把每个输出设备的 ``.monitor`` 源直接列成普通输入设备,
按名字挑出来即可。macOS 没有系统级回环(需 BlackHole 等虚拟声卡),故不支持。

优雅降级(与 ``audio_ingest.py`` 同一约定)
-----------------------------------------
``sounddevice`` 缺失、平台不支持、版本太老没有 ``WasapiSettings``、找不到回环设备 ——
全部返回结构化的"不可用 + 原因",不抛异常、不影响任何主流程。原因是**明确文字**而
不是静默 False:这条链路一旦不通,症状是"模型不知道你在看什么",不给原因根本没法排查。
"""

from __future__ import annotations

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
REASON_NO_WASAPI_SUPPORT = "sounddevice_too_old_no_wasapi_settings"
REASON_NO_WASAPI_HOSTAPI = "no_wasapi_hostapi"
REASON_NO_LOOPBACK_DEVICE = "no_loopback_device_found"
REASON_QUERY_FAILED = "device_query_failed"


@dataclass
class LoopbackTarget:
    """一个可用的回环采集目标。"""

    device: int
    name: str
    channels: int
    #: 是否需要 ``extra_settings=sd.WasapiSettings(loopback=True)``(Windows 专用)
    needs_wasapi_loopback: bool
    hostapi_name: str = ""

    def describe(self) -> str:
        mode = "WASAPI loopback" if self.needs_wasapi_loopback else "monitor source"
        return f"{self.name} [index={self.device}, ch={self.channels}, {mode}]"


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


def _reason_text(reason: str) -> str:
    """把结构化原因翻成可直接给人看的一句话(含修复动作)。"""
    return {
        REASON_OK: "可用",
        REASON_NO_SOUNDDEVICE: "未安装 sounddevice —— 运行: pip install sounddevice",
        REASON_UNSUPPORTED_OS: (
            "当前系统没有系统级回环采集:Windows 走 WASAPI loopback、"
            "Linux 走 PulseAudio/PipeWire 的 .monitor 源;macOS 需装 BlackHole 之类虚拟声卡"
        ),
        REASON_NO_WASAPI_SUPPORT: ("sounddevice 版本过旧,没有 WasapiSettings —— 运行: pip install -U sounddevice"),
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

    target, reason = resolve_loopback_target(
        devices,
        hostapis,
        os_name=os_name,
        has_wasapi_settings=hasattr(sd, "WasapiSettings"),
    )
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
    """按目标打开回环输入流。返回未启动的 ``sd.InputStream``;失败抛原始异常。

    刻意**不**吞异常:调用方(采集循环)才知道该重试、该降级还是该放弃,在这里静默
    吞掉只会变成"流没开起来但谁也不知道"。
    """
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
