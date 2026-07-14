"""core/startup_timing.py — 启动每阶段计时(隐蔽 · 可关 · 零行为影响)
=================================================================

**它是什么:** 给启动流程的每个阶段量一下耗时,回答"每次加载半天到底卡在哪一段"。
和 URL 哨兵一个路子:

- **隐蔽**:计时只写进 ``logs/lumiv.log``(INFO 级,控制台默认只显示 WARNING+,
  所以不会在终端刷屏),并缓存供面板 DiagnosticsDrawer / 诊断端点展示。平时不打扰。
- **可关**:``GALAXY_PHASE_TIMING=0``(或 false/no/off)即禁用,默认开。
- **零行为影响**:只用 ``time.monotonic()`` 量墙钟,全程 ``try/except`` 兜底,
  计时自身绝不把启动带崩。

两种用法:

    from core.startup_timing import phase, mark, mark_reset

    with phase("Phase 0 环境检查"):      # 上下文管理器:量这段 with 块
        do_env_check()

    mark_reset()                          # 顺序阶段串联:先立基准
    ...do work...; mark("核心服务")       # 记录『距上次 mark 到现在』归到该名下
    ...do work...; mark("网关")           # 依此类推
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from contextlib import contextmanager
from typing import Deque, Dict, List, Optional

logger = logging.getLogger("Galaxy.StartupTiming")

_timings: Deque[Dict[str, object]] = deque(maxlen=60)
_last_mark: Dict[str, Optional[float]] = {"t": None}


def _enabled() -> bool:
    return os.environ.get("GALAXY_PHASE_TIMING", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _record(name: str, seconds: float) -> None:
    try:
        _timings.append(
            {
                "name": str(name)[:60],
                "seconds": round(float(seconds), 3),
                "ts": time.strftime("%H:%M:%S"),
            }
        )
        # INFO → 进 logs/lumiv.log,不上控制台(控制台阈值 WARNING),隐蔽。
        logger.info("[PHASE-TIMING] %-30s %8.2fs", str(name)[:30], seconds)
    except Exception:  # noqa: BLE001
        pass


@contextmanager
def phase(name: str):
    """上下文管理器:量 with 块耗时。禁用时是零开销直通。"""
    if not _enabled():
        yield
        return
    t0 = time.monotonic()
    try:
        yield
    finally:
        try:
            _record(name, time.monotonic() - t0)
        except Exception:  # noqa: BLE001
            pass


def mark_reset() -> None:
    """把"上一次 mark"的基准设为现在(不记录)。顺序阶段计时开始前调用一次。"""
    try:
        _last_mark["t"] = time.monotonic()
    except Exception:  # noqa: BLE001
        pass


def mark(name: str) -> None:
    """记录『距上一次 mark/reset 到现在』的耗时,归到 name 名下。"""
    if not _enabled():
        return
    try:
        now = time.monotonic()
        prev = _last_mark["t"]
        _last_mark["t"] = now
        if prev is not None:
            _record(name, now - prev)
    except Exception:  # noqa: BLE001
        pass


def recent_timings() -> List[Dict[str, object]]:
    """返回本次启动记录的各阶段耗时(按发生顺序),供面板/诊断端点展示。"""
    try:
        return list(_timings)
    except Exception:  # noqa: BLE001
        return []
