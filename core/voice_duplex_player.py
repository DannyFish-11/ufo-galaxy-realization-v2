"""core.voice_duplex_player — 双工下行的播放器（本机扬声器）

从 ``core/voice_duplex_session.py`` 拆出来的：那个文件在文件大小门禁的基线上，按仓库的规矩
拆分、不抬基线 —— 它前两次涨到基线边上也是这么做的（``voice_duplex_capability.py``、
``voice_duplex_adapters.py``）。播放器管的是本机的输出设备，和会话协议那半边本来就是两件事。

原模块做再导出（``from core.voice_duplex_session import PcmPlayer`` 照旧能用），仓内既有的
import 一行都不用改。
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

# 与拆出之前同一个 logger 名：日志里的来源不因为搬了文件而变。
logger = logging.getLogger("Galaxy.VoiceDuplex")


def float_from_pcm16(data: bytes) -> Any:
    """16-bit PCM 字节 → float32 [-1,1](下行播放/分析用)。"""
    import numpy as np

    if not data:
        return np.zeros(0, dtype=np.float32)
    return (np.frombuffer(data, dtype="<i2").astype(np.float32) / 32767.0).astype(np.float32)


#: 下行播放缓冲上限(秒)。满了丢**最旧**的:过期音频没有价值,而让 play() 等待
#: 会把事件循环连带上行一起卡住。
_PLAYER_BUFFER_SEC = 2.0

#: ducking 的增益爬坡时长(毫秒)。瞬间切换会有爆音,50ms 是听感上"干净且够快"的常用值。
_DUCK_RAMP_MS = 50.0


class PcmPlayer:
    """下行原始 PCM 的播放器(回调驱动,``play()`` 绝不阻塞)。

    为什么不能用 ``OutputStream.write()``
    -------------------------------------
    双工下行是**连续的 PCM 流**,不是一个个音频文件,所以现有 TTS 引擎那套
    ``_play_audio(path)`` 用不上 —— 为每个 20ms 的音频块写一个临时文件再播,延迟和
    IO 开销都不可接受。

    但直接用 ``stream.write()`` 也不行:按 sounddevice 的契约它**会阻塞**到所有帧都写进
    设备缓冲为止。而 ``play()`` 是从 ``_duplex_downlink`` 里调的,跑在事件循环上 ——
    一阻塞,同一个循环上的**上行**也跟着停。那就等于用一个"实时"播放器把双工性质亲手
    毁掉:模型说话时用户的声音传不上去,退化成半双工。

    所以改成**回调驱动**:``sounddevice`` 的音频线程主动来取,``play()`` 只是往一个有界
    环形缓冲里追加,纯内存操作、不等待任何人。这也是音频输出的标准做法。

    没有 sounddevice / 没有输出设备时**如实不可用**并记一次 WARNING,不静默假装在播 ——
    "以为在说话其实一点声音都没有"是最难排查的一类症状。
    """

    def __init__(self, sample_rate: int = 16000) -> None:
        self.sample_rate = int(sample_rate)
        self._stream: Any = None
        self._unavailable_reason = ""
        self._lock = threading.Lock()
        self._buf: Any = None  # numpy 1-D 待播样本
        self._np: Any = None
        self.blocks_played = 0
        self.blocks_dropped = 0
        self.samples_underrun = 0  # 缓冲空、只能输出静音的样本数(可听为卡顿)
        # ── ducking(压音)──
        self._gain = 1.0  # 当前增益
        self._target_gain = 1.0  # 目标增益
        self.duck_events = 0

    @property
    def _max_samples(self) -> int:
        return int(_PLAYER_BUFFER_SEC * self.sample_rate)

    @property
    def _ramp_samples(self) -> int:
        """增益爬坡长度(样本)。**不能瞬间切换** —— 幅度突变在听感上是"啪"的一声爆音。"""
        return max(1, int(self.sample_rate * _DUCK_RAMP_MS / 1000.0))

    # ── ducking ───────────────────────────────────────────────────────────

    def duck(self, gain: Optional[float] = None) -> None:
        """压低音量(不停止播放)。用户开口时用,比整段掐断温和得多。"""
        from core.voice_duplex_session import duck_gain  # 惰性：本模块被那边在顶层再导出

        g = duck_gain() if gain is None else float(gain)
        with self._lock:
            if self._target_gain != g:
                self.duck_events += 1
            self._target_gain = max(0.0, min(1.0, g))

    def unduck(self) -> None:
        """恢复原音量。"""
        with self._lock:
            self._target_gain = 1.0

    @property
    def ducked(self) -> bool:
        with self._lock:
            return self._target_gain < 1.0

    def start(self) -> bool:
        if self._stream is not None:
            return True
        try:
            import numpy as np
            import sounddevice as sd

            self._np = np
            self._buf = np.zeros(0, dtype=np.float32)

            def _cb(outdata, frames, _time_info, status) -> None:  # noqa: ANN001
                # 音频线程:只调 _fill(取数 + 增益 + 补静音),绝不做 IO / 日志 / 加重锁
                if status:
                    pass
                self._fill(outdata, frames)

            self._stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                callback=_cb,
            )
            self._stream.start()
            logger.info("双工下行播放器已启动(回调驱动, sr=%d)", self.sample_rate)
            return True
        except Exception as exc:  # noqa: BLE001
            self._unavailable_reason = str(exc)
            logger.warning("双工下行播放器不可用(模型的回复将听不到): %s", exc)
            self._stream = None
            return False

    def _fill(self, outdata: Any, frames: int) -> None:
        """填一个输出块:取数 → 施加增益爬坡 → 不足补静音。

        抽成方法(而不是留在 ``start()`` 的闭包里)是为了**让测试驱动真正的这段代码**。
        本环境没有音频设备,若把逻辑埋在只有 ``sd.OutputStream`` 才会调用的闭包里,测试
        就只能另写一份等价实现去测 —— 那测的是副本不是本体,两边一旦漂移就完全测不出来。
        """
        np = self._np
        with self._lock:
            have = min(frames, self._buf.size)
            if have:
                outdata[:have, 0] = self._buf[:have]
                self._buf = self._buf[have:]
            if have < frames:
                outdata[have:, 0] = 0.0
                self.samples_underrun += frames - have

            # 增益爬坡:本块最多向目标靠拢 frames/ramp_n,再在块内线性插值。
            # 一步切到目标会产生幅度突变,听感上就是"啪"的一声爆音。
            g0 = self._gain
            delta = self._target_gain - g0
            max_delta = frames / self._ramp_samples
            g1 = self._target_gain if abs(delta) <= max_delta else g0 + (max_delta if delta > 0 else -max_delta)
            if have and not (g0 == 1.0 and g1 == 1.0):
                outdata[:have, 0] *= np.linspace(g0, g1, have, endpoint=False, dtype=np.float32)
            self._gain = g1

    def play(self, pcm16: bytes) -> bool:
        """把一块 PCM 追加到播放缓冲。**不阻塞**、永不抛出。"""
        if not pcm16:
            return False
        if self._stream is None or self._np is None:
            self.blocks_dropped += 1
            return False
        try:
            np = self._np
            samples = float_from_pcm16(pcm16)
            with self._lock:
                self._buf = np.concatenate((self._buf, samples))
                # 有界:生产快于消费时丢最旧的,而不是让 play() 等下去
                extra = self._buf.size - self._max_samples
                if extra > 0:
                    self._buf = self._buf[extra:]
                    self.blocks_dropped += 1
            self.blocks_played += 1
            return True
        except Exception as exc:  # noqa: BLE001
            self.blocks_dropped += 1
            logger.debug("双工下行入缓冲失败(丢弃本块): %s", exc)
            return False

    def flush(self) -> None:
        """丢掉还没播的那一截，播放器本身不停。

        人按「停」时用：服务端那边已经 ``interrupt()`` 了，但本地缓冲里还攒着
        最多 ``_PLAYER_BUFFER_SEC`` 秒已经下行的声音 —— 不清掉的话，它会在"停了"
        之后接着把这半句念完。
        """
        with self._lock:
            if self._np is not None:
                self._buf = self._np.zeros(0, dtype=self._np.float32)

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        with self._lock:
            if self._np is not None:
                self._buf = self._np.zeros(0, dtype=self._np.float32)
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("关闭双工播放器失败(忽略): %s", exc)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            buffered = int(self._buf.size) if self._buf is not None else 0
            gain = round(self._gain, 4)
            target = round(self._target_gain, 4)
        return {
            "available": self._stream is not None,
            "unavailable_reason": self._unavailable_reason or None,
            "blocks_played": self.blocks_played,
            "blocks_dropped": self.blocks_dropped,
            "buffered_samples": buffered,
            "samples_underrun": self.samples_underrun,
            # ducking 的实时状态:压音是"听得见但不明显"的行为,不摊出来就无从判断
            # "到底压了没有""是不是忘了恢复"
            "gain": gain,
            "target_gain": target,
            "ducked": target < 1.0,
            "duck_events": self.duck_events,
        }
