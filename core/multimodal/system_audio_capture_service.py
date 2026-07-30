"""core/multimodal/system_audio_capture_service.py —— 系统播放声回环采集循环。

它把一路回环采集同时喂给**两个**下游,这两个下游的用途完全不同:

1. **AEC 的参考信号**(``core/multimodal/acoustic_echo_canceller.py``)—— 回声消除
   必须知道"扬声器此刻在放什么"才能从麦克风信号里把它减掉。这是逐块、低延迟的。
2. **感知库的系统声槽位**(``core/perception/desktop_perception_store.py``)—— 让模型
   知道"用户此刻在听什么"。这是每隔几秒攒一段、编码成 WAV base64 再送进去的。

为什么两个下游共用一路采集:回环流是**独占性**资源(同一个输出设备开两条 loopback 流
在 WASAPI 上会互相干扰),而且重复采集纯属浪费。所以采集只做一次,分发在本模块内完成。

为什么本机采集而不是等电脑端壳来 POST
--------------------------------------
``/api/perception/desktop/system_audio`` 那条路由是给 Electron 壳用的,壳不在本仓库里。
但 AEC 的参考信号**不能**走 HTTP:它要求与麦克风块在同一时间尺度上对齐(毫秒级),
绕一趟 HTTP + base64 编解码根本没法用。所以本模块在**服务端进程内**直接采集 ——
这也顺带让整条链路不依赖任何外部壳:装了 sounddevice 的机器上,AEC 与"用户在听什么"
两件事都能自己跑起来。

隐私
----
系统播放声比麦克风更敏感(等于把用户正在听的一切完整送出去)。因此:

* 送进感知库走的是 ``update_system_audio()``,那条路**已经在隐私闸门后面** ——
  暂停期间写入口直接拒收。
* 隐私暂停期间**连采集本身都停**(见 ``_privacy_paused``):不只是"采了不用",而是
  不往任何缓冲里放。AEC 参考信号也一并断掉 —— 代价是暂停期间没有回声消除,但暂停期间
  本来就不该有音频进上行通路。
* **跨越隐私边界的待送缓冲一律作废**(见 ``_drop_buffer_if_privacy_changed``)。光靠
  "下一块到来时看见 paused 再清"是不够的,实测过的真实泄露路径:采了几秒 → 用户按暂停
  (``pause()`` 只清感知库自己的缓存,碰不到本服务的待送缓冲)→ 用户恢复 → 下一块到来时
  ``paused`` 已经是 False,那段**暂停之前**攒的音频就被原样送进了感知库。改用感知库的
  ``epoch`` 世代号判断,"暂停过"这件事在恢复之后依然可见。

降级永远安全:探测不可用 → ``start()`` 如实返回 False 并说明原因,绝不抛出、绝不
影响麦克风链路。
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.SystemAudioCapture")

#: 攒多少秒的系统声才编码一段送进感知库(太频繁纯属浪费 CPU 与带宽)
_DEFAULT_SNAPSHOT_SEC = 3.0

#: 内部 PCM 缓冲的硬上限(秒)。防止感知库不可用时缓冲无界增长。
_MAX_BUFFER_SEC = 12.0

_BACKGROUND_TASKS: set = set()


def _flag(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "off")


def enabled() -> bool:
    """回环采集是否启用(默认开启)。"""
    return _flag("GALAXY_SYSTEM_AUDIO_CAPTURE", "1")


def feed_perception_enabled() -> bool:
    """是否把系统声送进感知库(默认开启;设 0 则只做 AEC 参考信号)。

    分成两个开关是因为两件事的隐私含量不同:AEC 参考信号只在进程内做减法、不出网、
    不进任何上下文;送进感知库则意味着这段音频会**进模型上下文**。想只要回声消除、
    不想让模型听见自己在放什么的用户,应该能只关后者。
    """
    return _flag("GALAXY_SYSTEM_AUDIO_TO_PERCEPTION", "1")


def pcm_to_wav_base64(pcm: Any, sample_rate: int) -> str:
    """把 float32/float64 单声道 PCM 编码成 16-bit WAV 的 base64。

    用 WAV 而不是 webm/opus:标准库 ``wave`` 就能写,不引入编码器依赖;体积换来的是
    零依赖与确定性。感知库那一侧只关心 mime 与 base64,不在意具体容器。
    """
    import numpy as np

    arr = np.asarray(pcm, dtype=np.float64).reshape(-1)
    if arr.size == 0:
        return ""
    # 限幅后转 16-bit;不做自动增益(那会改变"用户听到的相对音量"这一信息)
    clipped = np.clip(arr, -1.0, 1.0)
    ints = (clipped * 32767.0).astype("<i2")

    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(ints.tobytes())
    return base64.b64encode(buf.getvalue()).decode("ascii")


class SystemAudioCaptureService:
    """回环采集循环:一路采集,分发给 AEC 参考信号与感知库系统声槽位。

    用法::

        svc = SystemAudioCaptureService(sample_rate=16000)
        ok = await svc.start()          # False = 本机不支持,原因见 svc.status()
        ...
        await svc.stop()
    """

    def __init__(self, sample_rate: int = 16000, snapshot_sec: Optional[float] = None) -> None:
        self.sample_rate = int(sample_rate)
        self.snapshot_sec = float(snapshot_sec if snapshot_sec is not None else _DEFAULT_SNAPSHOT_SEC)
        self._lock = threading.Lock()
        self._stream: Any = None
        self._running = False
        self._unavailable_reason = ""
        self._target_desc = ""
        # 攒给感知库的 PCM 片段(逐块 append,定时编码)
        self._pcm: List[Any] = []
        self._pcm_samples = 0
        # 初始化成"现在"而不是 0.0:留 0.0 的话 (time.time() - 0) 恒大于任何 snapshot_sec,
        # 于是**第一块**永远立刻触发一次快照,无视配置的间隔。生产路径上 start() 会重设
        # 它所以看不出来,但这条隐含依赖很脆 —— 任何不经 start() 直接喂块的调用方
        # (含测试)都会撞上,而且症状是"间隔配置好像没生效"。
        self._last_snapshot_ts = time.time()
        # 观测
        self.blocks_captured = 0
        self.blocks_dropped_paused = 0
        self.snapshots_pushed = 0
        self.ref_pushed = 0
        self.buffers_dropped_epoch = 0
        #: 上次见到的隐私世代号。初始化成当前值,避免首块就误丢一次空缓冲。
        self._epoch = self._privacy_epoch()

    # ── 生命周期 ──────────────────────────────────────────────────────────

    async def start(self) -> bool:
        """启动回环采集。返回是否真的起来了;不可用时如实返回 False 并记录原因。"""
        if not enabled():
            self._unavailable_reason = "disabled_by_env"
            logger.info("系统播放声采集被 GALAXY_SYSTEM_AUDIO_CAPTURE=0 关闭")
            return False
        with self._lock:
            if self._running:
                return True
        try:
            from core.multimodal.system_audio_ingest import (
                open_loopback_stream,
                probe,
                resolve_loopback_target,
            )
        except Exception as exc:  # noqa: BLE001
            self._unavailable_reason = f"import_failed: {exc}"
            logger.warning("系统播放声采集模块不可用: %s", exc)
            return False

        info = probe()
        if not info.get("available"):
            self._unavailable_reason = str(info.get("reason") or "unavailable")
            # WARNING 而非 debug:这条链路不通意味着**没有回声消除**,用户会听到
            # "AI 老是打断自己"之类的症状,必须能从日志里查到根因。
            logger.warning(
                "系统播放声采集不可用 → AEC 没有参考信号,回声消除将不生效。原因:%s",
                info.get("reason_text") or self._unavailable_reason,
            )
            return False

        try:
            import sounddevice as sd  # noqa: F401

            from core.multimodal.system_audio_ingest import downmix_to_mono

            devices = [dict(d) for d in sd.query_devices()]
            hostapis = [dict(h) for h in sd.query_hostapis()]
            import platform

            target, reason = resolve_loopback_target(
                devices,
                hostapis,
                os_name=platform.system(),
                has_wasapi_settings=hasattr(sd, "WasapiSettings"),
            )
            if target is None:
                self._unavailable_reason = reason
                logger.warning("系统播放声采集目标解析失败: %s", reason)
                return False
            self._target_desc = target.describe()

            def _cb(indata, frames, time_info, status) -> None:  # noqa: ANN001
                if status:
                    logger.debug("回环采集 status: %s", status)
                try:
                    self._on_block(downmix_to_mono(indata))
                except Exception as exc:  # noqa: BLE001 — 回调里绝不能抛
                    logger.debug("回环采集块处理失败(丢弃本块): %s", exc)

            stream = open_loopback_stream(target, sample_rate=self.sample_rate, callback=_cb)
            stream.start()
        except Exception as exc:  # noqa: BLE001
            self._unavailable_reason = f"open_failed: {exc}"
            logger.warning("回环采集流打开失败,AEC 将没有参考信号: %s", exc)
            return False

        with self._lock:
            self._stream = stream
            self._running = True
            self._last_snapshot_ts = time.time()
        logger.info("系统播放声采集已启动:%s", self._target_desc)
        return True

    async def stop(self) -> None:
        """停止采集并清空缓冲。幂等、永不抛出。"""
        with self._lock:
            stream, self._stream = self._stream, None
            self._running = False
            self._pcm = []
            self._pcm_samples = 0
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("关闭回环采集流失败(忽略): %s", exc)
            logger.info("系统播放声采集已停止")

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    # ── 采集回调 ──────────────────────────────────────────────────────────

    @staticmethod
    def _privacy_paused() -> bool:
        """隐私是否处于暂停。取不到就当**没暂停**吗?不 —— 取不到当暂停。

        这里刻意 fail-closed,与本仓库其它地方的 fail-open 相反:判断不了隐私状态时
        继续采集系统声,是在拿用户正在听的全部内容赌一个未知状态。宁可少采一段。
        """
        try:
            from core.perception.desktop_perception_store import (
                get_desktop_perception_store,
            )

            return bool(get_desktop_perception_store().paused)
        except Exception as exc:  # noqa: BLE001
            logger.debug("读取隐私状态失败,按【已暂停】处理(fail-closed): %s", exc)
            return True

    @staticmethod
    def _privacy_epoch() -> int:
        """感知库的 pause/resume 世代号。取不到返回 -1(会被当作"变了"→丢缓冲)。"""
        try:
            from core.perception.desktop_perception_store import (
                get_desktop_perception_store,
            )

            return int(get_desktop_perception_store().epoch)
        except Exception as exc:  # noqa: BLE001
            logger.debug("读取隐私世代号失败,按【已变化】处理: %s", exc)
            return -1

    def _drop_buffer_if_privacy_changed(self) -> bool:
        """隐私世代变过就丢掉待送缓冲。返回是否丢弃了。

        为什么光靠"下一块到来时看见 paused 再清"不够 —— 实测过的真实泄露路径:
        采了几秒 → 用户按暂停(``pause()`` 只清感知库自己的缓存,**碰不到**本服务的
        待送缓冲)→ 用户恢复 → 下一块到来时 ``paused`` 已经是 False,于是那段
        **暂停之前**攒的音频被原样编码送进感知库。若暂停期间回环流本就没有新块
        (比如扬声器静音),连"看见 paused"的机会都没有。

        改用世代号:``epoch`` 在每次 pause/resume 都自增,所以"暂停过"这件事即便在
        恢复之后也依然可见 —— 这正是 ``epoch`` 当初为 ambient 帧差指纹设计的用途,
        同一个机制在这里同样适用。
        """
        now_epoch = self._privacy_epoch()
        with self._lock:
            if now_epoch == self._epoch:
                return False
            had = self._pcm_samples > 0
            self._epoch = now_epoch
            self._pcm = []
            self._pcm_samples = 0
            if had:
                self.buffers_dropped_epoch += 1
        if had:
            logger.info("隐私世代变化(epoch=%s),已丢弃待送的系统声缓冲", now_epoch)
        return had

    def _on_block(self, mono: Any) -> None:
        """每个回环块:先隐私闸门,再喂 AEC 参考,再攒给感知库。"""
        # 跨越过隐私边界的缓冲一律作废(理由见 _drop_buffer_if_privacy_changed)
        self._drop_buffer_if_privacy_changed()

        if self._privacy_paused():
            with self._lock:
                self.blocks_dropped_paused += 1
                # 暂停期间连缓冲都清掉,不留"恢复后一次性送出暂停期间内容"的口子
                self._pcm = []
                self._pcm_samples = 0
            return

        with self._lock:
            self.blocks_captured += 1

        # 1) AEC 参考信号 —— 逐块、低延迟,这是回声消除的命脉
        try:
            from core.multimodal.acoustic_echo_canceller import get_echo_canceller

            get_echo_canceller(self.sample_rate).push_reference(mono)
            with self._lock:
                self.ref_pushed += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("推送 AEC 参考信号失败(本块跳过): %s", exc)

        # 2) 攒给感知库,定时编码送出
        if not feed_perception_enabled():
            return
        try:
            import numpy as np

            with self._lock:
                self._pcm.append(np.asarray(mono, dtype=np.float32).copy())
                self._pcm_samples += int(np.asarray(mono).size)
                # 硬上界:感知库不可用时不能让缓冲无界增长
                max_samples = int(_MAX_BUFFER_SEC * self.sample_rate)
                while self._pcm_samples > max_samples and self._pcm:
                    dropped = self._pcm.pop(0)
                    self._pcm_samples -= int(np.asarray(dropped).size)
                due = (time.time() - self._last_snapshot_ts) >= self.snapshot_sec
                if not due or self._pcm_samples <= 0:
                    return
                chunks = self._pcm
                self._pcm = []
                self._pcm_samples = 0
                self._last_snapshot_ts = time.time()
            self._push_snapshot(np.concatenate(chunks))
        except Exception as exc:  # noqa: BLE001
            logger.debug("系统声快照攒帧失败: %s", exc)

    def _push_snapshot(self, pcm: Any) -> None:
        """把一段系统声编码成 WAV base64 送进感知库。永不抛出。"""
        try:
            b64 = pcm_to_wav_base64(pcm, self.sample_rate)
            if not b64:
                return
            from core.perception.desktop_perception_store import (
                get_desktop_perception_store,
            )

            get_desktop_perception_store().update_system_audio(b64, mime="audio/wav")
            with self._lock:
                self.snapshots_pushed += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("送入感知库系统声槽位失败: %s", exc)

    # ── 观测 ──────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "enabled": enabled(),
                "feeds_perception": feed_perception_enabled(),
                "target": self._target_desc or None,
                "unavailable_reason": self._unavailable_reason or None,
                "sample_rate": self.sample_rate,
                "snapshot_sec": self.snapshot_sec,
                "blocks_captured": self.blocks_captured,
                "blocks_dropped_paused": self.blocks_dropped_paused,
                "ref_pushed": self.ref_pushed,
                "snapshots_pushed": self.snapshots_pushed,
                "buffered_samples": self._pcm_samples,
                "buffers_dropped_epoch": self.buffers_dropped_epoch,
                "privacy_epoch": self._epoch,
            }


# ── 进程级单例 ───────────────────────────────────────────────────────────────

_svc: Optional[SystemAudioCaptureService] = None
_svc_lock = threading.Lock()


def get_system_audio_capture(sample_rate: int = 16000) -> SystemAudioCaptureService:
    global _svc
    with _svc_lock:
        if _svc is None or _svc.sample_rate != sample_rate:
            _svc = SystemAudioCaptureService(sample_rate=sample_rate)
        return _svc


def reset_system_audio_capture() -> None:
    """重置单例(测试用)。"""
    global _svc
    with _svc_lock:
        _svc = None


def ensure_started(sample_rate: int = 16000) -> None:
    """在**已有事件循环**的上下文里确保回环采集已启动(fire-and-forget)。

    供麦克风采集链路调用:AEC 需要参考信号,而参考信号来自这里。做成"顺手确保"
    而不是要求调用方显式编排,是为了避免出现"AEC 装上了但没人喂参考信号"这种
    写了没接的状态 —— 那种状态下 AEC 会永远走 reference_silent 旁通,而且毫无声响。
    """
    try:
        svc = get_system_audio_capture(sample_rate)
        if svc.running:
            return
        loop = asyncio.get_running_loop()
        task = loop.create_task(svc.start())
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
    except RuntimeError:
        logger.debug("没有运行中的事件循环,跳过回环采集自启(麦克风链路仍正常)")
    except Exception as exc:  # noqa: BLE001
        logger.debug("回环采集自启失败(不影响麦克风链路): %s", exc)
