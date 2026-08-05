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

   两处后来实测补上的关键细节:

   - **增益上涨要封顶**。漏判一块 → 近端能量被算进路径增益 → 门槛抬高 → 更难触发,
     是条正反馈自毒化通路。实测安静的近端(比回声只高一点)会被它一路拖成永不触发。
     路径增益物理上变化很慢,突跳几乎一定是人开口了,所以封顶。封顶后同一条信号上
     0 块 → 5/9/12 块,而无近端时仍然零误报。
   - **要有滞后保持**。真实双讲连续,能量判据只抓得住峰 —— 一段连续近端语音里 50 块
     只有 7 块被判双讲,其余 43 块照旧自适应、照旧狠削。所有"双讲时退让"的参数因此
     几乎没有杠杆(实测只值 0.05~0.15 dB)。铺满整段之后那些参数才真正起作用。

4. **残余回声抑制(RES / NLP)** —— 第二级。线性滤波原理上只能消掉"参考信号的线性
   变换";扬声器过载削波、外壳与桌面振动、功放谐波失真带来的**非线性**回声，无论
   滤波器怎么收敛都消不掉。实测表现是 ERLE 明明有二十几 dB，AI 一大声说话麦克风里
   还是能听见它自己。

   这一级用频域维纳后置滤波，残余功率靠**自适应泄漏系数**估计(``leak = E[|Err|²]
   / E[|Y|²]``，只在远端单讲时更新 —— 与 DTD 冻结自适应同一个道理)。**双讲时退让**:
   用户正在说话的那一刻狠削就是削用户。退让由增益下限分档 + DTD 滞后保持共同承担,
   实测各值 0.69 dB 与 1.05 dB。近端保护的**大头**其实是维纳增益本身 ——
   近端主导的频点上增益本来就≈1。
   配合时间/频率平滑压音乐噪声，并用静默期跟踪到的本底整形出舒适噪声填回被压掉的
   部分(压成绝对零会是一段死寂，而且下游 VAD 会因电平突变误判边界)。

   ``stats()`` 把两级**分开**报:``erle_db`` 是线性级、``total_erle_db`` 是串起来的
   总量、``res_gain_db`` 是这一级自己的贡献、``leak_db`` 直接读出"非线性回声有多重"。
   合成一个数就分不出"线性级不行"和"非线性残余重"，而这两者的处置完全不同。

不做什么(说明白)
------------------
- **不做去噪 / 自动增益**。那是另外两件事,混在一个模块里只会让每件都做不好。
- 残余抑制是**统计**方法,不是完美对消:重非线性下仍会有可闻残余。文本层的
  ``voice_echo_guard`` 继续为这部分兜底 —— 三层(线性对消 → 残余抑制 → 文本归属)
  是互补的,不是重复的。
- 时钟漂移只靠周期性整体时延重估来跟,不做重采样级的精细同步。漂移剧烈时效果会退化,
  ``stats()`` 里的 ``erle_db`` 会如实反映出来。

降级永远安全:参考信号缺失、长度异常、numpy 不可用 —— 一律**原样返回麦克风信号**,
绝不因为 AEC 失灵而让上行通路断掉。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Optional

logger = logging.getLogger("Galaxy.AEC")

#: 数值下限,防除零
_EPS = 1e-10


# 统一走 core.config_flags —— 这里原先是 5 份逐字相同的本地 _flag 副本,
# 其中一个真 bug(空值把开关打开)因此要修 5 遍。详见该模块 docstring。
from core.config_flags import flag as _flag  # noqa: E402  (保留 _flag 名字以免动全部调用点)
from core.config_flags import num as _num  # noqa: E402

# _num 原为本地副本(两处,措辞略有差异)。它本来就正确处理了「空值视同未设置」,
# 而同文件的 _flag 漏了这一步 —— 那正是「空值把开关打开」那个 bug 的来源。一并收敛。


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
    dtd_hangover_blocks  检出双讲后**继续按双讲处理**多少块。真实双讲是连续的，
                      而能量判据只抓得住峰:实测一段连续近端语音里 50 块只有 7 块被
                      判为双讲。没有滞后保持时，其余 43 块照旧自适应(把近端往权重里
                      学)、照旧狠削(削用户)，而所有"双讲时退让"的参数都只作用在那
                      7 块上 —— 调它们几乎没有杠杆(实测 0.05~0.15 dB)。滞后保持把
                      退让铺满整段，退让参数才真正起作用。
    ref_silence_rms   参考信号 RMS 低于此值即认为"扬声器没在放",跳过处理与自适应。
    power_smooth      频点功率的滑动平滑系数(越大越平滑、步长越稳)。
    gain_track_decay  路径增益上界的衰减系数(越接近 1 记得越久)。
    gain_rise_cap     路径增益**每块最多上涨**的倍数。回声路径增益由房间+扬声器+麦克风
                      决定，物理上变化很慢;突然跳高几乎一定是近端开口了。不封顶的话
                      DTD 漏判一次 → 近端能量被算进路径增益 → 门槛抬高 → 更难触发，
                      是条正反馈自毒化通路。
    res_enabled       是否启用残余回声抑制(RES/NLP)。
    res_over          过减因子:残余回声功率估计乘这个数再扣。>1 换更狠的抑制,
                      代价是近端语音也被多削一点。
    res_floor_db      远端单讲时的增益下限(dB)。不设下限会把残余压成"绝对安静",
                      听感是一段死寂,反而比留一点底噪更难受。
    res_dt_floor_db   **双讲**时的增益下限(dB)，比远端单讲宽松。
                      注意:实测下来这一项的杠杆很小(单独改它只值 0.05 dB)——
                      近端主导的频点上维纳增益本来就≈1，下限根本不咬。留着是兜底。
    res_smooth        增益的时间平滑系数(抑制"音乐噪声")。
    res_leak_smooth   泄漏系数(残余/回声估计 的功率比)的滑动平滑系数。
    comfort_noise     被抑制掉的部分是否填入极低电平的整形噪声(消除呼吸感)。
    """

    sample_rate: int = 16000
    tail_ms: float = 128.0
    mu: float = 0.35
    max_delay_ms: float = 400.0
    delay_recheck_blocks: int = 50
    dtd_margin_db: float = 6.0
    dtd_after_blocks: int = 4
    dtd_hangover_blocks: int = 12
    ref_silence_rms: float = 1e-4
    power_smooth: float = 0.9
    gain_track_decay: float = 0.999
    gain_rise_cap: float = 1.02
    res_enabled: bool = True
    res_over: float = 1.5
    res_floor_db: float = -18.0
    res_dt_floor_db: float = -3.0
    res_smooth: float = 0.6
    res_leak_smooth: float = 0.95
    comfort_noise: bool = True

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
            dtd_hangover_blocks=int(_num("GALAXY_AEC_DTD_HANGOVER", 12.0, lo=0.0, hi=200.0)),
            res_enabled=_flag("GALAXY_AEC_RES", "1"),
            res_over=_num("GALAXY_AEC_RES_OVER", 1.5, lo=1.0, hi=8.0),
            res_floor_db=_num("GALAXY_AEC_RES_FLOOR_DB", -18.0, lo=-60.0, hi=0.0),
            res_dt_floor_db=_num("GALAXY_AEC_RES_DT_FLOOR_DB", -3.0, lo=-30.0, hi=0.0),
            comfort_noise=_flag("GALAXY_AEC_COMFORT_NOISE", "1"),
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
    #: 线性滤波之后、残余抑制之后的**总**回声抑制量。两级串起来才是用户实际听到的效果。
    total_erle_db: float = 0.0
    #: 残余抑制这一级自己贡献了多少 dB（total - linear）。
    res_gain_db: float = 0.0
    #: 泄漏系数(残余功率 / 回声估计功率)的当前估计，dB。线性级消不掉多少，
    #: 这个数就有多高 —— 它是"非线性回声有多严重"的直接读数。
    leak_db: float = 0.0
    res_active: bool = False
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
            "total_erle_db": round(self.total_erle_db, 2),
            "res_gain_db": round(self.res_gain_db, 2),
            "leak_db": round(self.leak_db, 2),
            "res_active": self.res_active,
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
        self._dtd_hold = 0  # 双讲滞后保持剩余块数(见 dtd_hangover_blocks)
        # ── 残余回声抑制(RES)状态 ──
        self._leak: Any = None  # (bins,) 每频点泄漏系数:残余功率 / 回声估计功率
        self._res_g: Any = None  # (bins,) 上一块的增益(时间平滑用)
        self._cn_pow: Any = None  # (bins,) 舒适噪声的整形功率(跟踪静默期本底)
        self._erle_tot_num = 0.0  # 总 ERLE 的滑动累积(麦克风能量)
        self._erle_tot_den = 0.0  # 总 ERLE 的滑动累积(RES 之后的残差能量)
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
        # 泄漏系数从 0 起：一开始假设"线性级消得干净"，实测到多少残余就抬多少。
        # 反过来(从 1 起)会在滤波器还没收敛时就狠削，把用户的第一句话吃掉。
        self._leak = np.zeros(bins, dtype=np.float64)
        self._res_g = np.ones(bins, dtype=np.float64)
        self._cn_pow = np.zeros(bins, dtype=np.float64)
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
            double_talk_now = bool(dtd_active and ratio > margin * (self._gain_est + _EPS))
            # 滞后保持:检出一次就按双讲再处理若干块。真实双讲连续，能量判据只抓得住峰,
            # 不保持的话大半段仍在自适应(把近端学进权重)、仍在狠削(削用户)。
            if double_talk_now:
                self._dtd_hold = self.config.dtd_hangover_blocks
            elif self._dtd_hold > 0:
                self._dtd_hold -= 1
            double_talk = bool(double_talk_now or self._dtd_hold > 0)
            if not double_talk:
                # 只在"确信没有近端语音"时更新增益估计,否则近端语音会把上界抬高、
                # 让 DTD 自己失灵(经典的自我毒化)。带衰减以便跟上路径变化。
                #
                # 但"确信"本身会漏:近端只比回声高 3~5 dB 时判不出双讲,那一块就会走到
                # 这里,把近端能量算进路径增益 —— 门槛随之抬高，下一块更判不出。实测
                # (合成双讲信号)漏判会一路把 DTD 拖成永不触发。所以上涨要封顶:路径增益
                # 物理上变化很慢，突跳几乎一定是人开口了。起步阶段(DTD 本来就没启用)
                # 仍自由获取，否则从 0 起永远涨不上来。
                if self._blocks <= self.config.dtd_after_blocks or self._gain_est <= _EPS:
                    self._gain_est = max(ratio, self._gain_est)
                else:
                    capped = min(ratio, self._gain_est * self.config.gain_rise_cap)
                    self._gain_est = max(capped, self._gain_est * self.config.gain_track_decay)

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

            # ── 第二级:残余回声抑制(RES/NLP)──────────────────────────────
            out = self._suppress_residual(err, y_hat, double_talk)

            # 总 ERLE:两级串起来才是用户实际听到的效果。与线性级分开记 —— 合成一个数
            # 就分不出"线性级不行"和"非线性残余重"，而这两者的处置完全不同。
            self._erle_tot_num = 0.95 * self._erle_tot_num + float(np.dot(mic, mic))
            self._erle_tot_den = 0.95 * self._erle_tot_den + float(np.dot(out, out))
            if self._erle_tot_den > _EPS:
                self.stats.total_erle_db = 10.0 * float(np.log10((self._erle_tot_num + _EPS) / self._erle_tot_den))
            self.stats.res_gain_db = self.stats.total_erle_db - self.stats.erle_db

            self.stats.blocks_processed += 1
            self.stats.delay_samples = self._delay
            self.stats.extra["delay_ms"] = 1000.0 * self._delay / max(1, self.config.sample_rate)
            self.stats.converged = self.stats.erle_db > 6.0

        return out.astype(np.float32) if getattr(mic_in, "dtype", None) == np.float32 else out

    # ── 第二级:残余回声抑制 ────────────────────────────────────────────

    def _suppress_residual(self, err: Any, y_hat: Any, double_talk: bool) -> Any:
        """把线性级消不掉的**残余回声**再压一层(频域维纳后置滤波)。调用方须持锁。

        为什么必须有这一级
        ------------------
        线性自适应滤波原理上只能消掉"参考信号的线性变换"。而真实回声路径里有一堆
        非线性成分:扬声器过载削波、外壳与桌面振动、廉价功放的谐波失真。这些无论
        滤波器怎么收敛都消不掉 —— 实测表现是 ERLE 明明有二十几 dB，可 AI 一大声说话
        麦克风里还是能听见它自己。之前这一级是缺的(模块 docstring 里写着"不做")，
        兜底全压在文本层的 ``voice_echo_guard`` 上，而那一层只能事后丢弃转写结果，
        救不了被污染的波形本身。

        怎么估残余
        ----------
        用**自适应泄漏系数**：残余里有多少是回声，不靠猜，靠测。
        ``leak[k] = E[|Err[k]|²] / E[|Y[k]|²]``，只在**远端单讲**(没有双讲)时更新 ——
        那种时刻麦克风里除了回声没有别的，比值就是真实泄漏。双讲时冻结，否则用户的
        语音会被算进"残余"，把泄漏估计抬高，接着就去狠削用户 —— 与 DTD 冻结自适应
        是同一个道理。

        增益
        ----
        维纳式：``G = (|Err|² - over·leak·|Y|²) / |Err|²``，夹在 ``[floor, 1]``。

        - ``over`` 过减因子换更狠的抑制;
        - **下限分两档**：远端单讲时可以狠(默认 −18 dB)，双讲时必须宽松(默认 −3 dB)。
          这一条是整个 RES 里最要紧的一行 —— 用户正在说话的那一刻狠削，就是削用户。
        - 时间平滑 + 频率平滑，抑制"音乐噪声"(逐帧逐点乱跳的增益听起来像水泡音)。

        帧结构
        ------
        复用线性级同一套 overlap-save 框架(前 N 个零 + 本块残差，FFT 2N，取后 N)，
        不另起一套分帧。代价是频域乘性增益会引入少量循环卷积混叠；靠**频率平滑**把
        等效冲激响应压短来缓解 —— 这是有意的取舍，不是疏漏。

        舒适噪声
        --------
        被压下去的频点若填成绝对零，听感是一段"死寂"，比留一点底噪更难受，而且下游
        VAD 会因为电平突变而误判边界。这里用静默期跟踪到的本底功率整形出极低电平的
        随机相位噪声填回去。
        """
        np = self._np
        cfg = self.config
        if not cfg.res_enabled:
            self.stats.res_active = False
            return err

        n = self._n
        E = np.fft.rfft(np.concatenate((np.zeros(n), err)), self._m)
        Y = np.fft.rfft(np.concatenate((np.zeros(n), y_hat)), self._m)
        pe = (np.abs(E) ** 2) + _EPS
        py = (np.abs(Y) ** 2) + _EPS

        # 泄漏系数只在远端单讲时更新（理由见 docstring）
        if not double_talk:
            a = cfg.res_leak_smooth
            self._leak = a * self._leak + (1.0 - a) * np.clip(pe / py, 0.0, 4.0)
            # 静默段的本底功率 —— 舒适噪声的整形来源
            self._cn_pow = (
                np.minimum(
                    0.98 * self._cn_pow + 0.02 * pe,
                    np.maximum(self._cn_pow, pe),
                )
                if self._cn_pow.any()
                else pe.copy()
            )

        # 双讲时的退让由**增益下限**与**滞后保持**承担，两者都是量出来有效的
        # （下限 0.69 dB、滞后保持 1.05 dB）。曾经还加过一个"双讲专属过减因子"，
        # 实测在默认值下只值 0.10 dB —— 一个能改变结果 0.1 dB 的旋钮是噪音，
        # 留着等于宣称有一个并不存在的控制，已删。
        residual_pow = cfg.res_over * self._leak * py
        g = (pe - residual_pow) / pe
        floor_db = cfg.res_dt_floor_db if double_talk else cfg.res_floor_db
        g = np.clip(g, 10.0 ** (floor_db / 20.0), 1.0)

        # 频率平滑（3 点）+ 时间平滑：都是为了压住音乐噪声
        if g.size >= 3:
            g = np.concatenate(([g[0]], (g[:-2] + g[1:-1] + g[2:]) / 3.0, [g[-1]]))
        s = cfg.res_smooth
        self._res_g = s * self._res_g + (1.0 - s) * g
        g = self._res_g

        Eo = E * g
        if cfg.comfort_noise:
            # 被压掉多少，就用同等整形的低电平噪声补回去多少（随机相位，幅度取本底）
            fill = np.sqrt(np.maximum(0.0, (1.0 - g**2) * np.minimum(self._cn_pow, pe))) * 0.35
            phase = np.exp(1j * np.random.uniform(0.0, 2.0 * np.pi, size=Eo.shape))
            Eo = Eo + fill * phase

        out = np.fft.irfft(Eo, self._m)[n:]
        if out.size != err.size:  # 理论上不会;真发生了宁可返回线性级结果
            self.stats.res_active = False
            return err
        self.stats.res_active = True
        self.stats.leak_db = 10.0 * float(np.log10(float(np.mean(self._leak)) + _EPS))
        return out

    # ── 观测 / 复位 ──────────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return self.stats.to_dict()

    def reset(self) -> None:
        """清空滤波器与参考历史(换设备 / 换会话时用)。

        这里原先清的是 ``self._w``(小写)—— 那是**旧时域 NLMS 实现**的权重变量名，
        换成频域(PBFDAF)之后权重叫 ``self._W``(大写)。Python 区分大小写，于是这行
        只是凭空造了个没人读的属性，**真正的滤波器一次都没被清过**：换了设备/换了
        房间之后，上一处的冲激响应仍留在权重里，AEC 要么消错要么把回声放大，而
        ``reset()`` 看起来是调用过的。RES 的泄漏系数与舒适噪声本底同理，一并清。
        """
        with self._lock:
            if self._np is not None:
                np = self._np
                self._ref_buf = np.zeros(self._ref_len, dtype=np.float64)
                if self._n:
                    bins = self._m // 2 + 1
                    self._W = np.zeros((self._parts, bins), dtype=np.complex128)
                    self._Xh = np.zeros((self._parts, bins), dtype=np.complex128)
                    self._pow = np.zeros(bins, dtype=np.float64)
                    self._leak = np.zeros(bins, dtype=np.float64)
                    self._res_g = np.ones(bins, dtype=np.float64)
                    self._cn_pow = np.zeros(bins, dtype=np.float64)
            self._pow_init = False
            self._gain_est = 0.0
            self._dtd_hold = 0
            self._blocks = 0
            self._delay = 0
            self._delay_locked = False
            self._erle_num = 0.0
            self._erle_den = 0.0
            self._erle_tot_num = 0.0
            self._erle_tot_den = 0.0
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
