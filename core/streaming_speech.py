"""core/streaming_speech.py — 分句流式朗读 + 打断（barge-in）
================================================================

此前"说"是整段批处理：等 LLM 全文生成完 → 合成整段 MP3 → 播放。感知延迟 =
生成时长 + 整段合成时长，且**无法被打断**（播放子进程 await 到结束）。

本模块把"说"改成流式：

  分句 → 逐句合成 → 边合成边按序播放，第一句就绪即开口
  （感知延迟 ≈ 第一句的合成时长，而非整段）

并支持 **barge-in**：用户一开口，``interrupt()`` 立刻掐断当前播放、清空后续
队列，AI 闭嘴回到聆听。

设计为可测：合成/播放/打断都通过注入的可调用对象完成，单测无需真实
edge-tts 或音频设备即可验证分句、顺序、打断语义。
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Awaitable, Callable, List, Optional

logger = logging.getLogger("Galaxy.StreamingSpeech")

# 句末标点（中英）+ 换行 —— 在这些位置切句，便于"说一句合成下一句"。
_SENTENCE_END = "。！？；…!?;\n"
_MIN_CHUNK_CHARS = 6   # 太短的碎片（如单独一个"好。"）并入邻句，避免频繁启停播放器


def split_into_speakable_chunks(text: str, *, min_chars: int = _MIN_CHUNK_CHARS) -> List[str]:
    """把一段文字切成"可朗读的句子块"。

    规则：在句末标点后断开；过短的块并入后一块（除非它是最后一块）；
    折叠多余空白。纯函数、无副作用。
    """
    if not text:
        return []
    # 折叠连续空白（保留一个空格），换行视作句界。
    normalized = text.replace("\r", "\n")
    raw: List[str] = []
    buf = []
    n = len(normalized)
    for i, ch in enumerate(normalized):
        buf.append(ch)
        is_boundary = ch in _SENTENCE_END
        # ASCII 句点单独处理：仅当其后是空白/结尾时才作句界，避免切断小数(3.14)、
        # 缩写(U.S.A.)、域名等。
        if ch == ".":
            nxt = normalized[i + 1] if i + 1 < n else ""
            is_boundary = (nxt == "" or nxt.isspace())
        if is_boundary:
            piece = "".join(buf).strip()
            if piece:
                raw.append(piece)
            buf = []
    tail = "".join(buf).strip()
    if tail:
        raw.append(tail)

    # 合并过短的块到下一块，避免"。"这种独块。
    merged: List[str] = []
    carry = ""
    for piece in raw:
        candidate = (carry + " " + piece).strip() if carry else piece
        if len(candidate.strip(_SENTENCE_END + " ")) < min_chars:
            carry = candidate
        else:
            merged.append(candidate)
            carry = ""
    if carry:
        if merged:
            merged[-1] = (merged[-1] + " " + carry).strip()
        else:
            merged.append(carry)
    return [m for m in (s.strip() for s in merged) if m]


# 合成：文字 → 音频文件路径（或任意可播放句柄）。播放：句柄 → 播完/被打断。
SynthFn = Callable[[str], Awaitable[str]]
PlayFn = Callable[[str], Awaitable[None]]
StopFn = Callable[[], Awaitable[None]]


class StreamingSpeaker:
    """按句流式合成+播放，可被 interrupt() 掐断。

    参数
    ----
    synth:  ``async (text) -> handle`` 合成一句，返回可播放句柄（文件路径等）。
    play:   ``async (handle) -> None`` 播放一句，正常返回=播完。
    stop:   ``async () -> None`` 掐断【当前】播放（barge-in 用；可选）。
    on_speaking: ``(bool) -> None`` 开始/结束说话回调（同步三态覆盖层，可选）。
    """

    def __init__(
        self,
        synth: SynthFn,
        play: PlayFn,
        stop: Optional[StopFn] = None,
        on_speaking: Optional[Callable[[bool], None]] = None,
        discard: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self._synth = synth
        self._play = play
        self._stop = stop
        self._on_speaking = on_speaking
        # discard(handle):清理一个【已合成但不会被播放】的句柄(如临时 mp3)。
        # 正常播放路径由 play 负责删文件;但被 interrupt 打断时,已预取合成、尚未
        # 播放的句柄不会走 play → 若不在这里清掉就会泄漏临时文件(每次打断漏 1~2 个)。
        self._discard = discard
        self._interrupted = False
        self._speaking = False
        self.chunks_spoken = 0

    async def _discard_handle(self, handle: Optional[str]) -> None:
        if handle is None or self._discard is None:
            return
        try:
            res = self._discard(handle)
            if asyncio.iscoroutine(res):
                await res
        except Exception as exc:  # noqa: BLE001
            logger.debug("丢弃未播放句柄失败(非致命): %s", exc)

    @property
    def speaking(self) -> bool:
        return self._speaking

    async def speak(self, text: str) -> None:
        """把整段文字分句、逐句合成并按序播放。中途 interrupt() 即停。

        为降低首字延迟：预取【下一句】的合成与【当前句】的播放并发进行——
        播当前句的同时后台合成下一句，播完立刻接上，几乎无缝。
        """
        chunks = split_into_speakable_chunks(text)
        if not chunks:
            return
        self._interrupted = False
        self._set_speaking(True)
        try:
            # 预取下一句合成，与当前句播放重叠。
            next_synth: Optional[asyncio.Task] = asyncio.ensure_future(self._synth_safe(chunks[0]))
            for i in range(len(chunks)):
                if self._interrupted:
                    break
                handle = await next_synth if next_synth else None
                # 立刻起下一句的合成（与本句播放并发）。
                if i + 1 < len(chunks):
                    next_synth = asyncio.ensure_future(self._synth_safe(chunks[i + 1]))
                else:
                    next_synth = None
                if handle is None:
                    continue
                if self._interrupted:
                    await self._discard_handle(handle)  # 已合成但被打断,不会播 → 清掉
                    break
                try:
                    await self._play(handle)
                    self.chunks_spoken += 1
                except asyncio.CancelledError:
                    await self._discard_handle(handle)
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.debug("流式播放一句失败(跳过): %s", exc)
                    await self._discard_handle(handle)
            # 若已中断，取消在飞的预取合成；若它已合成完(有结果句柄)也一并清掉,
            # 避免泄漏。
            if next_synth is not None:
                next_synth.cancel()
                try:
                    leftover = await next_synth
                    await self._discard_handle(leftover)
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        finally:
            self._set_speaking(False)

    async def _synth_safe(self, text: str) -> Optional[str]:
        try:
            return await self._synth(text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("流式合成一句失败(跳过): %s", exc)
            return None

    async def interrupt(self) -> None:
        """barge-in：掐断当前播放 + 阻止后续句子。"""
        self._interrupted = True
        if self._stop is not None:
            try:
                await self._stop()
            except Exception as exc:  # noqa: BLE001
                logger.debug("打断当前播放失败(非致命): %s", exc)

    def _set_speaking(self, on: bool) -> None:
        self._speaking = on
        if self._on_speaking is not None:
            try:
                self._on_speaking(on)
            except Exception:  # noqa: BLE001
                pass
