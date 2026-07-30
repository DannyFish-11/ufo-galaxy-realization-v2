"""core/multimodal/acoustic_echo_canceller.py —— 声学回声消除(AEC)。

这一层解决什么
--------------
``core/voice_echo_guard.py`` 在**文本层**解决了归属问题:一段转写到底是"用户说的"
还是"AI 自己的回声"。但它挡不住更前面的损害 —— 麦克风信号里始终混着扬声器放出去的
声音,于是:

- VAD 在 AI 朗读期间一直判"有人在说话",整段音频被白白攒起来送去转写;
- ASR 拿到的是"用户语音 + AI 语音"的混合波形,即便用户真的开口,转写质量也被污染;
- 真正的"边说边听"根本无从谈起 —— 上行通路里永远有下行信号。

AEC 在**信号层**把扬声器正在播的内容从麦克风信号里减掉。它需要一路"参考信号"
(far-end / 远端信号),也就是扬声器实际在播的波形 —— 那正是
``core/multimodal/system_audio_ingest.py`` 采集的系统播放声回环。两者是配套的:
没有回环采集就没有参考信号,AEC 无从实现。

算法:分区频域自适应滤波(PBFDAF)
----------------------------------
1. **整体时延估计**(``_estimate_delay``)—— 麦克风与回环是**两条独立的流**,采集
   起点不同、缓冲深度不同,两者之间有一个未知的整体偏移。先用能量归一化互相关找出
   这个偏移,把参考信号对齐到麦克风时间轴上。不对齐的话自适应滤波器要用大量抽头去
   "表示这段延迟",收敛慢且效果差。时延会周期性重估,以跟上两条流之间的缓慢时钟漂移。

2. **分区频域自适应滤波** —— 滤波器按块长切成 K 个分区,每个分区在频域各持一组权重;
   用 overlap-save 做线性卷积(FFT 长度 2N,取后 N 个样本为有效输出)。

   **为什么不是时域 NLMS。** 最初的实现就是时域块状 NLMS,实测在本场景下收敛慢到
   不可用:合成线性回声路径上,跑满 2000 块(≈200 秒音频)才到 12 dB ERLE。原因是
   语音类信号强相关,LMS 的收敛速度受输入自相关矩阵的**特征值扩散**支配,有色输入下
   极差 —— 这是算法选择错误,不是调参问题。频域做法给**每个频点各自按该频点的功率
   归一化**,等效于把输入去相关,各频段收敛速度趋于一致。同一条合成测试路径上:
   时域 2000 块才 12 dB,频域 120 块(12 秒)即 **27 dB**
   (见 ``tests/test_acoustic_echo_cancellation.py``)。

   实现上有两处细节必须做对,否则同样跑飞 —— 两处都是实测踩出来的:

   - **频点功率估计要用首块实测值初始化**,不能从全零平滑上来:从 0 起平滑时首块的
     功率只有真实值的 ``1-power_smooth``(默认 10%),步长因此放大 10 倍,开头几块直接
     过冲,实测 ERLE 冲到 −20 dB(等于 AEC 把回声放大了)。
   - **步长要再除分区数 K**:功率估计是所有分区之和,而 K 个分区各自都按这个步长更新
     一次,不除就等于把有效步长放大 K 倍;不除时 ``mu`` 稍大即发散,而且改 ``tail_ms``
     会顺带把稳定性改掉。

3. **双讲检测(DTD)** —— 用户和 AI 同时说话时**必须冻结自适应**。否则滤波器会试图
   把用户的声音也"解释"成回声,权重被带跑偏,结果是既消不掉回声、又把用户的语音
   削掉一块。

   判据**不能**是"麦克风能量是否超出回声估计":滤波器没收敛时回声估计≈0,于是那个
   条件恒成立,DTD 把一切判成双讲 → 永不自适应 → 永不收敛,死锁。最初的实现正是踩了
   这个坑(120 块里只有 8 块真的更新了权重)。

   改成跟踪**回声路径增益**:回声只由参考信号产生,所以"麦克风 RMS / 参考 RMS"这个比值
   在只有回声时是稳定的(就是路径增益);近端语音叠上来会让比值显著跳高。增益估计用
   带衰减的滑动上界跟踪,与滤波器收敛程度**无关**,因此不存在死锁。

不做什么(说明白)
------------------
- **不做非线性处理**(NLP / 残余回声抑制)。扬声器过载削波、外壳振动带来的非线性回声
  是线性滤波器原理上消不掉的,残余回声仍会存在。文本层的 ``voice_echo_guard`` 正是为
  这部分残余兜底 —— 两层是互补的,不是重复的。
- **不做去噪 / 自动增益**。那是另外两件事,混在一个模块里只会让每件都做不好。
- 时钟漂移只靠周期性整体时延重估来跟,不做重采样级的精细同步。漂移剧烈时效果会退化,
  ``stats()`` 里的 ``erle_db`` 会如实反映出来。

降级永远安全:参考信号缺失、长度异常、numpy 不可用 —— 一律**原样返回麦克风信号**,
绝不因为 AEC 失灵而让上行通路断掉。
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Optional

logger = logging.getLogger("Galaxy.AEC")

#: 数值下限,防除零
_EPS = 1e-10


def _flag(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "off")


def _num(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("%s=%r 不是合法数值,已退回默认 %s", name, raw, default)
        return default


def enabled() -> bool:
    """AEC 是否启用(默认开启)。"""
    return _flag("GALAXY_AEC", "1")


@dataclass
class AECConfig:
    """AEC 参数。

    Attributes
    ----------
    sample_rate       采样率(Hz)。麦克风与参考信号必须同采样率。
    tail_ms           滤波器覆盖的回声尾长(毫秒)。要盖住房间混响。整体时延由时延估计
                      单独处理,不占用抽头。
    mu                频域步长(0~1)。每个频点已按自身功率归一化,故这里是相对步长。
    max_delay_ms      整体时延搜索上限(毫秒)。
    delay_recheck_blocks  每多少块重估一次整体时延(跟时钟漂移)。
    dtd_margin_db     麦克风/参考 能量比超出已跟踪的路径增益多少 dB 才判双讲。
    dtd_after_blocks  前多少块不启用双讲检测(给路径增益估计一点起步样本)。
    ref_silence_rms   参考信号 RMS 低于此值即认为"扬声器没在放",跳过处理与自适应。
    power_smooth      频点功率的滑动平滑系数(越大越平滑、步长越稳)。
    gain_track_decay  路径增益上界的衰减系数(越接近 1 记得越久)。
    """

    sample_rate: int = 16000
    tail_ms: float = 128.0
    mu: float = 0.35
    max_delay_ms: float = 400.0
    delay_recheck_blocks: int = 50
    dtd_margin_db: float = 6.0
    dtd_after_blocks: int = 4
    ref_silence_rms: float = 1e-4
    power_smooth: float = 0.9
    gain_track_decay: float = 0.999

    @property
    def taps(self) -> int:
        return max(64, int(self.sample_rate * self.tail_ms / 1000.0))

    @property
    def max_delay_samples(self) -> int:
        return max(0, int(self.sample_rate * self.max_delay_ms / 1000.0))

    @classmethod
    def from_env(cls, sample_rate: int = 16000) -> "AECConfig":
        return cls(
            sample_rate=sample_rate,
            tail_ms=_num("GALAXY_AEC_TAIL_MS", 128.0),
            mu=_num("GALAXY_AEC_MU", 0.35),
            max_delay_ms=_num("GALAXY_AEC_MAX_DELAY_MS", 400.0),
            dtd_margin_db=_num("GALAXY_AEC_DTD_MARGIN_DB", 6.0),
        )


@dataclass
class AECStats:
    """可观测状态。``erle_db`` 是判断 AEC 是否真的在起作用的唯一硬指标。"""

    blocks_processed: int = 0
    blocks_bypassed: int = 0
    blocks_adapted: int = 0
    blocks_double_talk: int = 0
    delay_samples: int = 0
    erle_db: float = 0.0
    converged: bool = False
    last_bypass_reason: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "blocks_processed": self.blocks_processed,
            "blocks_bypassed": self.blocks_bypassed,
            "blocks_adapted": self.blocks_adapted,
            "blocks_double_talk": self.blocks_double_talk,
            "delay_samples": self.delay_samples,
            "delay_ms": round(self.extra.get("delay_ms", 0.0), 1),
            "erle_db": round(self.erle_db, 2),
            "converged": self.converged,
            "last_bypass_reason": self.last_bypass_reason,
        }


class AcousticEchoCanceller:
    """分区频域自适应(PBFDAF)声学回声消除器。

    用法::

        aec = AcousticEchoCanceller()
        aec.push_reference(loopback_block)       # 扬声器正在播的(远端)
        clean = aec.process(mic_block)           # 去回声后的近端信号

    线程安全:参考信号来自回环采集线程,麦克风块来自采集回调线程,两者并发,故全部
    状态由一把锁守护。

    ``process()`` 永不抛出:任何异常都记日志并**原样返回麦克风信号**。上行语音通路
    不能因为 AEC 出问题就断掉 —— 那比留着回声严重得多。
    """

    def __init__(self, config: Optional[AECConfig] = None) -> None:
        self.config = config or AECConfig()
        self._lock = threading.RLock()
        self.stats = AECStats()
        self._np: Any = None
        self._ref_buf: Any = None  # 参考信号历史(numpy 1-D)
        self._ref_len = 0
        self._blocks = 0
        self._delay = 0
        self._delay_locked = False
        self._erle_num = 0.0  # ERLE 的滑动累积(麦克风能量)
        self._erle_den = 0.0  # ERLE 的滑动累积(残差能量)
        # ── 频域滤波器状态(块长在首次 process() 时按实际输入锁定)──
        self._n = 0  # 块长 N
        self._m = 0  # FFT 长度 = 2N
        self._parts = 0  # 分区数 K
        self._W: Any = None  # (K, M//2+1) 复数权重
        self._Xh: Any = None  # (K, M//2+1) 最近 K 个参考窗的频谱
        self._pow: Any = None  # (M//2+1,) 频点功率滑动估计
        self._gain_est = 0.0  # 回声路径增益上界估计(DTD 用,与收敛无关)
        self._init_numpy()

    # ── 初始化 ────────────────────────────────────────────────────────────

    def _init_numpy(self) -> None:
        try:
            import numpy as np
        except Exception as exc:  # noqa: BLE001 — 没有 numpy 就整体旁通
            logger.warning("numpy 不可用,AEC 关闭(麦克风信号原样通过): %s", exc)
            return
        self._np = np
        # 参考历史要够长:抽头 + 最大时延 + 一整秒余量
        self._ref_len = self.config.taps + self.config.max_delay_samples + self.config.sample_rate
        self._ref_buf = np.zeros(self._ref_len, dtype=np.float64)

    def _init_filter(self, n: int) -> None:
        """按实际块长 N 建立频域滤波器。调用方必须已持有锁。

        块长取**首次实际到来的块**的长度而不是配置值:采集链路的块长由
        ``chunk_duration_ms`` 与设备实际给的帧数共同决定,写死会导致每块都走
        "长度不符→旁通",AEC 等于没接。块长变化时重建并记一条日志。
        """
        np = self._np
        self._n = int(n)
        self._m = 2 * self._n
        self._parts = max(1, -(-self.config.taps // self._n))  # ceil
        bins = self._m // 2 + 1
        self._W = np.zeros((self._parts, bins), dtype=np.complex128)
        self._Xh = np.zeros((self._parts, bins), dtype=np.complex128)
        self._pow = np.zeros(bins, dtype=np.float64)
        self._pow_init = False
        logger.info(
            "AEC 滤波器就绪:块长=%d 样本 FFT=%d 分区=%d(尾长≈%.0fms)",
            self._n,
            self._m,
            self._parts,
            1000.0 * self._parts * self._n / max(1, self.config.sample_rate),
        )

    @property
    def available(self) -> bool:
        return self._np is not None

    # ── 参考信号(远端 / 扬声器正在播的)────────────────────────────────

    def push_reference(self, ref: Any) -> None:
        """喂入一块参考信号(扬声器正在播的波形)。降级安全,永不抛出。"""
        if self._np is None:
            return
        try:
            np = self._np
            arr = np.asarray(ref, dtype=np.float64).reshape(-1)
            if arr.size == 0:
                return
            with self._lock:
                if arr.size >= self._ref_len:
                    self._ref_buf[:] = arr[-self._ref_len :]
                else:
                    self._ref_buf = np.roll(self._ref_buf, -arr.size)
                    self._ref_buf[-arr.size :] = arr
        except Exception as exc:  # noqa: BLE001
            logger.debug("push_reference 失败(本块参考信号丢弃): %s", exc)

    # ── 时延估计 ──────────────────────────────────────────────────────────

    def _estimate_delay(self, mic: Any) -> int:
        """用能量归一化互相关估计麦克风相对参考信号的整体时延(样本数)。

        返回"参考信号要往后取多少样本才与麦克风对齐"。找不到可信峰值时返回当前值。
        """
        np = self._np
        search = self.config.max_delay_samples
        if search <= 0:
            return 0
        # 取参考历史的尾部作为搜索区间;mic 作为模板
        n = mic.size
        span = min(self._ref_buf.size, search + n)
        seg = self._ref_buf[-span:]
        if seg.size < n + 1:
            return self._delay
        # 归一化互相关:去均值 + 除以能量,避免被幅度差主导
        m = mic - mic.mean()
        m_norm = float(np.sqrt(np.dot(m, m))) + _EPS
        corr = np.correlate(seg, m, mode="valid")  # 长度 = span - n + 1
        if corr.size == 0:
            return self._delay
        # 逐 lag 的参考能量,用于归一化(累积和求滑动窗口能量)
        sq = np.concatenate(([0.0], np.cumsum(seg * seg)))
        win_energy = sq[n:] - sq[: sq.size - n]  # 长度 = span - n + 1
        denom = np.sqrt(np.maximum(win_energy, 0.0)) * m_norm + _EPS
        ncc = np.abs(corr) / denom
        best = int(np.argmax(ncc))
        peak = float(ncc[best])
        # 峰值太弱说明这块里没有可辨认的回声(比如扬声器没在放),不动时延
        if peak < 0.2:
            return self._delay
        # best 是 seg 内的起点;换算成"距参考历史末端的偏移"
        delay = (seg.size - n) - best
        return int(max(0, min(delay, search)))

    # ── 主处理 ────────────────────────────────────────────────────────────

    def process(self, mic: Any) -> Any:
        """对一块麦克风信号做回声消除,返回去回声后的信号。

        永不抛出:任何问题都原样返回输入。
        """
        if self._np is None or not enabled():
            with self._lock:
                self.stats.blocks_bypassed += 1
                self.stats.last_bypass_reason = "disabled" if self._np is not None else "no_numpy"
            return mic
        try:
            return self._process_inner(mic)
        except Exception as exc:  # noqa: BLE001 — 上行通路绝不能因 AEC 断掉
            logger.warning("AEC 处理失败,本块麦克风信号原样通过: %s", exc, exc_info=True)
            with self._lock:
                self.stats.blocks_bypassed += 1
                self.stats.last_bypass_reason = "error"
            return mic

    def _process_inner(self, mic_in: Any) -> Any:
        np = self._np
        mic = np.asarray(mic_in, dtype=np.float64).reshape(-1)
        n = mic.size
        if n == 0:
            return mic_in

        with self._lock:
            # 块长按首次实际到来的块锁定(理由见 _init_filter)
            if self._n != n:
                if self._n != 0:
                    logger.info("AEC 块长变化 %s → %s,重建滤波器", self._n, n)
                self._init_filter(n)
            taps = self._parts * self._n

            # 参考信号安静 → 扬声器没在放 → 没有回声可消。也不能在这种情况下自适应:
            # 那等于让滤波器去拟合噪声,把已经收敛的权重带跑偏。
            ref_tail = self._ref_buf[-(n + taps) :]
            ref_rms = float(np.sqrt(np.mean(ref_tail * ref_tail)))
            if ref_rms < self.config.ref_silence_rms:
                self.stats.blocks_bypassed += 1
                self.stats.last_bypass_reason = "reference_silent"
                return mic_in

            self._blocks += 1

            # 整体时延:首次必估;之后周期性重估以跟时钟漂移
            if not self._delay_locked or (self._blocks % max(1, self.config.delay_recheck_blocks) == 0):
                est = self._estimate_delay(mic)
                if est != self._delay:
                    logger.debug("AEC 时延更新: %s → %s 样本", self._delay, est)
                self._delay = est
                self._delay_locked = True

            # 取出与本块麦克风对齐的参考窗:overlap-save 要 2N 个样本(前 N 个是上一块的
            # 尾巴,用来提供跨块的卷积历史),末端回退 delay 个样本做对齐。
            end = self._ref_buf.size - self._delay
            start = end - self._m
            if start < 0 or end <= 0:
                self.stats.blocks_bypassed += 1
                self.stats.last_bypass_reason = "reference_too_short"
                return mic_in
            x_win = self._ref_buf[start:end]

            # 新参考窗入历史(最近的排在索引 0)
            X = np.fft.rfft(x_win, self._m)
            self._Xh = np.roll(self._Xh, 1, axis=0)
            self._Xh[0] = X

            # 回声估计:各分区频域相乘后求和,irfft 取后 N 个样本(前 N 个是循环卷积
            # 的绕回部分,overlap-save 按定义丢弃)。
            Y = (self._W * self._Xh).sum(axis=0)
            y_hat = np.fft.irfft(Y, self._m)[self._n :]
            if y_hat.size != n:  # 理论上不会发生;真发生了宁可旁通也不返回错长度的块
                self.stats.blocks_bypassed += 1
                self.stats.last_bypass_reason = "length_mismatch"
                return mic_in
            err = mic - y_hat

            # ── 双讲检测:跟踪回声路径增益,与滤波器收敛程度无关(见模块 docstring)──
            mic_rms = float(np.sqrt(np.dot(mic, mic) / n))
            ratio = mic_rms / (ref_rms + _EPS)
            dtd_active = self._blocks > self.config.dtd_after_blocks
            margin = 10.0 ** (self.config.dtd_margin_db / 20.0)  # 幅度比 → 20·log10
            double_talk = bool(dtd_active and ratio > margin * (self._gain_est + _EPS))
            if not double_talk:
                # 只在"确信没有近端语音"时更新增益估计,否则近端语音会把上界抬高、
                # 让 DTD 自己失灵(经典的自我毒化)。带衰减以便跟上路径变化。
                self._gain_est = max(ratio, self._gain_est * self.config.gain_track_decay)

            if double_talk:
                self.stats.blocks_double_talk += 1
            else:
                # 频域自适应:每个频点按自身功率归一化 —— 这正是相对时域 NLMS 的关键
                # 改进(输入去相关,各频段收敛速度趋于一致)。
                E = np.fft.rfft(np.concatenate((np.zeros(self._n), err)), self._m)
                p = (np.abs(self._Xh) ** 2).sum(axis=0)
                a = self.config.power_smooth
                if not self._pow_init:
                    # 功率估计必须用【首块实测值】初始化,不能从全零平滑上来:
                    # 从 0 起平滑时首块的 _pow 只有真实功率的 (1-a) = 10%,步长
                    # 因此放大 10 倍,前几块直接过冲 —— 实测表现为开头一段 ERLE
                    # 冲到 −20 dB(AEC 把回声放大了),之后才慢慢拉回来。
                    self._pow = p.copy()
                    self._pow_init = True
                else:
                    self._pow = a * self._pow + (1.0 - a) * p
                # 再除分区数:_pow 是【所有分区功率之和】,而每个分区各自都要按这个
                # 步长更新一次,K 个分区同时走等于把有效步长放大 K 倍。除掉之后 mu 的
                # 含义与尾长(分区数)解耦 —— 改 tail_ms 不会顺带把稳定性改掉。
                step = self.config.mu / (self._parts * (self._pow + _EPS))
                self._W += step * np.conj(self._Xh) * E
                self.stats.blocks_adapted += 1

            # ── ERLE(回声抑制量,dB)—— AEC 是否真在起作用的唯一硬指标 ──
            self._erle_num = 0.95 * self._erle_num + float(np.dot(mic, mic))
            self._erle_den = 0.95 * self._erle_den + float(np.dot(err, err))
            if self._erle_den > _EPS:
                self.stats.erle_db = 10.0 * float(np.log10((self._erle_num + _EPS) / self._erle_den))
            self.stats.blocks_processed += 1
            self.stats.delay_samples = self._delay
            self.stats.extra["delay_ms"] = 1000.0 * self._delay / max(1, self.config.sample_rate)
            self.stats.converged = self.stats.erle_db > 6.0
            out = err

        return out.astype(np.float32) if getattr(mic_in, "dtype", None) == np.float32 else out

    # ── 观测 / 复位 ──────────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return self.stats.to_dict()

    def reset(self) -> None:
        """清空滤波器与参考历史(换设备 / 换会话时用)。"""
        with self._lock:
            if self._np is not None:
                self._w = self._np.zeros(self.config.taps, dtype=self._np.float64)
                self._ref_buf = self._np.zeros(self._ref_len, dtype=self._np.float64)
            self._blocks = 0
            self._delay = 0
            self._delay_locked = False
            self._erle_num = 0.0
            self._erle_den = 0.0
            self.stats = AECStats()


# ── 进程级单例(麦克风采集链路用)────────────────────────────────────────

_aec: Optional[AcousticEchoCanceller] = None
_aec_lock = threading.Lock()
_BACKGROUND_REFS: Optional[Deque] = None  # 占位:保持与其它模块一致的导入形状


def get_echo_canceller(sample_rate: int = 16000) -> AcousticEchoCanceller:
    """返回进程级 AEC 单例。采样率变化时重建(滤波器长度与采样率绑定)。"""
    global _aec
    with _aec_lock:
        if _aec is None or _aec.config.sample_rate != sample_rate:
            _aec = AcousticEchoCanceller(AECConfig.from_env(sample_rate=sample_rate))
        return _aec


def reset_echo_canceller() -> None:
    """重置单例(测试用)。"""
    global _aec
    with _aec_lock:
        _aec = None
