"""事件循环被卡住时,说出是**哪段代码**卡的。

所有者 Windows 真机日志里反复出现同一种样子::

    15:26:52 | WARNING | Slow request: GET /api/v1/models/providers took 2996ms
    15:26:52 | WARNING | Slow request: GET /api/v1/results/isolated took 2997ms
    …(十几条同一毫秒完成,各自 3 秒)

一批互不相干的请求同一时刻一起完成 = 事件循环被一件同步的事占住了。慢请求日志只看得到受害者,
看不到凶手 —— 每次都要靠猜(这次猜中的是 Whisper 在事件循环里加载,上一次是麦克风枚举、
拓扑落盘……)。这里直接看:

* 事件循环上每 0.2 秒跳一下心跳(``call_later``,不占任务);
* 一根守护线程盯着心跳,超过 ``STALL_S`` 没跳,就当场取**事件循环那根线程此刻的调用栈**;
* 等心跳恢复,记一行:卡了几秒、卡在仓库里哪几行。同一个位置 10 分钟内只说一次(之后计数)。

只读、不改任何行为;开销是每 0.2 秒一次回调 + 一根睡觉的线程。
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.LoopStall")

#: 心跳间隔。
BEAT_S = 0.2
#: 心跳停了这么久才算「卡住」。
STALL_S = 1.0
#: 同一个位置多久之内只说一次。
REPEAT_S = 600.0

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_started = False
_beat = [0.0]


def where(frame) -> str:
    """这根线程此刻卡在哪:最里面的几层**仓库里的**帧(库代码略过);一层都没有就给最里面那层。"""
    ours: List[str] = []
    innermost = ""
    while frame is not None:
        path = os.path.abspath(frame.f_code.co_filename)
        shown = os.path.relpath(path, _REPO) if path.startswith(_REPO) else os.path.basename(path)
        spot = f"{shown}:{frame.f_lineno} {frame.f_code.co_name}"
        innermost = innermost or spot
        if path.startswith(_REPO) and "site-packages" not in path and os.sep + "external" + os.sep not in path:
            ours.append(spot)
            if len(ours) == 3:
                break
        frame = frame.f_back
    return " ← ".join(ours) if ours else innermost


def _tick(loop: asyncio.AbstractEventLoop) -> None:
    _beat[0] = time.monotonic()
    if not loop.is_closed():
        loop.call_later(BEAT_S, _tick, loop)


def _monitor(loop: asyncio.AbstractEventLoop, loop_thread: int) -> None:
    said: Dict[str, Tuple[float, int]] = {}
    while not loop.is_closed() and loop.is_running():
        time.sleep(BEAT_S)
        stalled_since = _beat[0]
        if time.monotonic() - stalled_since < STALL_S:
            continue
        spot = where(sys._current_frames().get(loop_thread))
        while _beat[0] == stalled_since and not loop.is_closed():
            time.sleep(BEAT_S / 2)
        took = _beat[0] - stalled_since - BEAT_S
        last, quiet = said.get(spot, (0.0, 0))
        now = time.monotonic()
        if now - last < REPEAT_S:
            said[spot] = (last, quiet + 1)
            continue
        more = f"(此前 10 分钟里同一处又卡了 {quiet} 次)" if quiet else ""
        logger.warning("事件循环被卡住 %.1f 秒 —— 卡在 %s%s", took, spot, more)
        said[spot] = (now, 0)


def start(loop: Optional[asyncio.AbstractEventLoop] = None) -> bool:
    """在正在跑的事件循环上开始盯。重复调用无害;没有正在跑的循环就不开。"""
    global _started
    if _started:
        return True
    try:
        loop = loop or asyncio.get_running_loop()
    except RuntimeError:
        return False
    _started = True
    _tick(loop)
    threading.Thread(target=_monitor, args=(loop, threading.get_ident()), name="loop-stall-watch", daemon=True).start()
    return True
