"""正在做的事,一行一个,做完打勾 —— Phase 0 那种"探测中"的实时列表。

为什么要有它
------------
环境检查是"跑完全部再返回"的:五个外部探测都在跑,而屏幕上只有一行
「正在探测外部工具」。真机上只要有一个探测慢(Windows 的 npm 是 npm.cmd,
起子进程要过 cmd.exe 再被杀软逐个扫),这段就是**一动不动**,看起来像死了。

更要命的是:卡住的时候人不知道**卡在哪一个**上。一行"正在探测"说不出
是 npm 还是 ollama —— 而这两者的下一步完全不同。

所以这里做一件事:把每一项单独列出来,转圈的在跑、打勾的跑完了。
卡住时那一行会一直转,于是"卡住了"变成"卡在 npm 上"。

不是 TTY 的时候
---------------
输出被重定向到文件、或者跑在 CI 里时,光标控制字符会变成一堆垃圾。
所以非 TTY 一律降级成**每完成一项打一行**,不做原地重绘。
这不是"没有进度",是换一种形态 —— 日志里照样看得出走到哪了。
"""

from __future__ import annotations

import sys
import threading
from typing import Dict, List, Optional, TextIO

#: 转圈的帧。用 ASCII 而不是盲文点阵字符 —— 后者在 Windows 的
#: cp936 / cp1252 控制台上会直接 UnicodeEncodeError,把启动打断。
SPINNER_FRAMES = ("|", "/", "-", "\\")

#: 每帧多久(秒)。
FRAME_INTERVAL = 0.12

STATE_RUNNING = "running"
STATE_OK = "ok"
STATE_WARN = "warn"
STATE_TIMEOUT = "timeout"

#: 终态 → 图标。转圈态不在这里 —— 它每帧都在变。
_GLYPH = {
    STATE_OK: "✓",
    STATE_WARN: "⚠",
    STATE_TIMEOUT: "⏱",
}

#: 编码不支持时的退路(Windows 老控制台)。
_ASCII_GLYPH = {
    STATE_OK: "+",
    STATE_WARN: "!",
    STATE_TIMEOUT: "T",
}


def stream_is_tty(stream: Optional[TextIO] = None) -> bool:
    """这条流能不能做原地重绘。拿不准一律当**不能** —— 宁可少画,不可画乱。"""
    s = stream or sys.stdout
    try:
        return bool(s.isatty())
    except Exception:  # noqa: BLE001
        return False


class LiveList:
    """一组"正在做的事",原地刷新。

    线程安全:探测在各自线程里跑完就调 :meth:`update`,而重绘在主线程,
    所以状态字典必须上锁 —— 不锁的话会画出半行。
    """

    def __init__(
        self,
        items: List[tuple],  # [(name, label), ...] 顺序即显示顺序
        *,
        stream: Optional[TextIO] = None,
        indent: str = "    ",
        label_width: int = 22,
    ) -> None:
        self._stream = stream or sys.stdout
        self._order = [name for name, _label in items]
        self._label = {name: label for name, label in items}
        self._state: Dict[str, str] = {name: STATE_RUNNING for name, _ in items}
        self._value: Dict[str, str] = {name: "" for name, _ in items}
        self._lock = threading.Lock()
        self._indent = indent
        self._label_width = label_width
        self._tty = stream_is_tty(self._stream)
        self._drawn = 0  # 已经画了几行(用来知道往上退几行)
        self._frame = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── 对外 ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """开始画。非 TTY 时只打一行开场,不起重绘线程。"""
        if not self._tty:
            return
        self._thread = threading.Thread(target=self._animate, name="live-list", daemon=True)
        self._thread.start()

    def update(self, name: str, state: str, value: str = "") -> None:
        """某一项有结果了。**可以从任意线程调**。"""
        with self._lock:
            if name not in self._state:
                return
            self._state[name] = state
            self._value[name] = value
        if not self._tty:
            # 非 TTY:完成一项打一行,顺序就是完成顺序(而不是登记顺序)——
            # 这在日志里反而更有用:看得出谁慢。
            self._write(self._line(name) + "\n")

    def finish(self) -> None:
        """收尾:停掉动画,把最后一帧定住。重复调用无害。"""
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=1.0)
            self._thread = None
        if self._tty:
            self._redraw(final=True)

    def __enter__(self) -> "LiveList":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.finish()

    # ── 内部 ────────────────────────────────────────────────────────────

    def _animate(self) -> None:
        while not self._stop.is_set():
            self._redraw()
            self._frame += 1
            self._stop.wait(FRAME_INTERVAL)

    def _redraw(self, *, final: bool = False) -> None:
        with self._lock:
            lines = [self._line(name, locked=True) for name in self._order]
        buf = []
        if self._drawn:
            # 退回这一块的开头。\r 到行首,再上移 N-1 行,逐行清掉。
            buf.append("\r")
            buf.append("\x1b[A" * (self._drawn - 1) if self._drawn > 1 else "")
        for i, line in enumerate(lines):
            buf.append("\x1b[2K")  # 清整行 —— 上一帧可能更长
            buf.append(line)
            if i < len(lines) - 1 or final:
                buf.append("\n")
        if not final:
            # 停在最后一行行首,下一帧从这里往回退。
            buf.append("\r")
        self._write("".join(buf))
        self._drawn = len(lines) if not final else 0

    def _line(self, name: str, *, locked: bool = False) -> str:
        if not locked:
            with self._lock:
                state, value = self._state[name], self._value[name]
        else:
            state, value = self._state[name], self._value[name]
        if state == STATE_RUNNING:
            icon = SPINNER_FRAMES[self._frame % len(SPINNER_FRAMES)]
        else:
            icon = _GLYPH.get(state, "·")
        label = self._label[name]
        pad = max(1, self._label_width - _display_width(label))
        return f"{self._indent}{icon} {label}{' ' * pad}{value}"

    def _write(self, text: str) -> None:
        try:
            self._stream.write(text)
            self._stream.flush()
        except UnicodeEncodeError:
            # Windows 老控制台:换 ASCII 图标再来一次。画不出来也绝不能挡启动。
            try:
                fallback = text
                for state, glyph in _GLYPH.items():
                    fallback = fallback.replace(glyph, _ASCII_GLYPH[state])
                self._stream.write(fallback.encode("ascii", "replace").decode("ascii"))
                self._stream.flush()
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001 — 画不出来不是启动失败
            pass


def _display_width(text: str) -> int:
    """中日韩字符占两列,不算进去的话标签列会参差不齐。"""
    width = 0
    for ch in text:
        width += 2 if unicodedata_east_asian_wide(ch) else 1
    return width


def unicodedata_east_asian_wide(ch: str) -> bool:
    import unicodedata

    return unicodedata.east_asian_width(ch) in ("W", "F")


__all__ = [
    "SPINNER_FRAMES",
    "FRAME_INTERVAL",
    "STATE_RUNNING",
    "STATE_OK",
    "STATE_WARN",
    "STATE_TIMEOUT",
    "LiveList",
    "stream_is_tty",
]
