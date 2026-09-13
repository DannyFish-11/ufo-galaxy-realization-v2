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

import re
import sys
import threading
import time
from typing import Dict, List, Optional, TextIO

#: 只有在 ``core.ascii_art`` 导不进来时才用到(见 :func:`_display_width` 的兜底)。
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

#: 转圈的帧。用 ASCII 而不是盲文点阵字符 —— 后者在 Windows 的
#: cp936 / cp1252 控制台上会直接 UnicodeEncodeError,把启动打断。
SPINNER_FRAMES = ("|", "/", "-", "\\")

#: 每帧多久(秒)。
FRAME_INTERVAL = 0.12

STATE_RUNNING = "running"
STATE_OK = "ok"
STATE_WARN = "warn"
STATE_TIMEOUT = "timeout"

#: 终态 → **唯一权威里的状态词**(``core.cli_render._STATUS`` 的键)。
#:
#: 这里刻意只映射到"状态词",图标长什么样、什么颜色由 ``cli_render.glyph()``
#: 说了算 —— 全屏所有打印器共用那一份。此前本模块自带一张 ✓/⚠/⏱ 的表,
#: 且**不着色**:同一屏里于是出现"有色的 ✓"(cli_render)和"白的 ✓"(本模块)
#: 两种对勾。所有者真机上看到的"颜色不统一"就是这个。
#:
#: ``timeout`` 不在那张表里(它是本模块特有的处境),所以单独留在下面。
_STATE_TO_STATUS_WORD = {
    STATE_OK: "ok",
    STATE_WARN: "warn",
}

#: 超时那一格:唯一权威没有这个状态词,本模块自己给形状,但**着色走同一条路**。
_TIMEOUT_GLYPH = "⏱"

#: 编码不支持时的退路(Windows 老控制台)。键是**图标字符**,不是状态词 ——
#: 图标从唯一权威拿回来之后,这里只认最终画出来的那个字符。
_ASCII_GLYPH = {
    "✓": "+",
    "⚠": "!",
    "✗": "x",
    "·": ".",
    "◐": "o",
    _TIMEOUT_GLYPH: "T",
}

#: 收尾时**还停在转圈态**的那一行怎么画。
#:
#: 这不是理论上的分支:``check_environment`` 在 Python 版本不达标时会在任何
#: 探测开始之前就 early-return,五项一个事件都不会有;探测中途抛异常也一样
#: (``finish()`` 在调用方的 ``finally`` 里)。那时候把最后一帧原样定住,屏幕上
#: 留下的是**一个静止的转圈符** —— 看起来"还在跑",实际这一项根本没跑。
#: 说的和现实相反,正是这个仓库最不许出现的那类缺陷,所以单独给它一个形状:
#: 圆点 + 明说没有结论,和 ✓ / ⚠ / ⏱ 三种"有结论"彻底分开。
_UNFINISHED_GLYPH = "·"
#: ``_ASCII_GLYPH["·"]`` 就是它 —— 这里只是给它一个名字,方便判据引用。
_UNFINISHED_ASCII = "."
_UNFINISHED_NOTE = "没有结论(前一步就返回了)"


#: 图标列宽的兜底值 —— 只有在 ``core.ascii_art`` 都导不进来时才会用到。
#: 和那边的 ``ICON_COL`` 同值;两处对不上时以那边为准(见 :func:`_geometry`)。
_ICON_COL_FALLBACK = 2
_INDENT_FALLBACK = 2
_LABEL_COL_FALLBACK = 22


def _geometry() -> tuple:
    """(缩进字符串, 标签列宽) —— 取全仓唯一那份版面几何。

    导不进来(极端裁剪的打包)时退回本模块的兜底值:**画得出来比画得准更要紧**,
    但兜底值和权威值写成同一个数,并由 tests 钉住,免得两处悄悄漂开。
    """
    global _ICON_COL
    try:
        from core.ascii_art import CONTENT_INDENT, ICON_COL, LABEL_COL

        _ICON_COL = ICON_COL
        return " " * CONTENT_INDENT, LABEL_COL
    except Exception:  # noqa: BLE001 —— 画不出来绝不能挡启动
        _ICON_COL = _ICON_COL_FALLBACK
        return " " * _INDENT_FALLBACK, _LABEL_COL_FALLBACK


#: 当前生效的图标列宽。``_geometry()`` 一跑就会被改写成权威值。
_ICON_COL = _ICON_COL_FALLBACK


def _glyph_from_authority(status_word: str) -> str:
    """``core.cli_render.glyph`` 画的那一个 —— 图标形状与颜色都由它说了算。"""
    try:
        from core.cli_render import glyph

        return glyph(status_word)
    except Exception:  # noqa: BLE001
        return {"ok": "✓", "warn": "⚠"}.get(status_word, _UNFINISHED_GLYPH)


def _paint(text: str, status_word: str) -> str:
    """给本模块自有的形状(转圈符 / ⏱ / ·)上色 —— **走权威的同一条上色路**。

    形状是本模块的(权威表里没有转圈符),但"要不要上色、上什么色"不许另起
    一套判断:非 TTY、``NO_COLOR``、Windows 不支持 VT 这些情形,必须和同屏其余
    行同进同退。
    """
    try:
        from core.ascii_art import Colors, ansi_supported

        if not ansi_supported():
            return text
        color = {"ok": Colors.GREEN, "warn": Colors.YELLOW, "doing": Colors.CYAN, "info": Colors.BLUE}.get(status_word)
        return f"{color}{text}{Colors.ENDC}" if color else text
    except Exception:  # noqa: BLE001
        return text


def _dim(text: str) -> str:
    """值列的暗色 —— 与 ``cli_render.phase`` 给值上的那一层同一个。"""
    try:
        from core.ascii_art import Colors, ansi_supported

        return f"{Colors.DIM}{text}{Colors.ENDC}" if ansi_supported() else text
    except Exception:  # noqa: BLE001
        return text


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
        indent: Optional[str] = None,
        label_width: Optional[int] = None,
        show_elapsed: bool = True,
    ) -> None:
        # 版面几何取全仓那**唯一一份**(core.ascii_art):缩进 CONTENT_INDENT、
        # 图标列 ICON_COL、标签列 LABEL_COL,于是值列落在 VALUE_COL。
        #
        # 此前这里写死 indent="    "(4 格)+ label_width=22。真机量出来的结果是:
        # 正式行的图标在**第 2 列**,而本模块的转圈符/对勾在**第 4 列** ——
        # 同一屏两条对勾列。所有者说的"行列不统一"就是这 2 格。
        geo_indent, geo_label = _geometry()
        indent = geo_indent if indent is None else indent
        label_width = geo_label if label_width is None else label_width
        self._stream = stream or sys.stdout
        self._order = [name for name, _label in items]
        self._label = {name: label for name, label in items}
        self._state: Dict[str, str] = {name: STATE_RUNNING for name, _ in items}
        self._value: Dict[str, str] = {name: "" for name, _ in items}
        # 每一项的起跑时刻 —— 转圈那一行要显示"已等 N 秒"。
        #
        # 所有者说"整体的速度和节奏有点奇怪":实测冷启 58s、热启 11s,长的那几段
        # (Phase 1 的 npm install 20s、Phase 2 的 14s)本身是真活,问题在于**看不出
        # 它在干活**。一个只转不走字的圈,和卡死长得一模一样;把秒数走起来,20 秒
        # 就是 20 秒,不是"死了"。
        self._started_at: Dict[str, float] = {}
        self._show_elapsed = show_elapsed
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
        now = time.monotonic()
        with self._lock:
            for name in self._order:
                self._started_at.setdefault(name, now)
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
            return
        # 非 TTY:完成的那些在 update() 里已经各打过一行了,这里补的是**没有
        # 结论**的那几项 —— 日志里只有 4 行而登记了 5 项,少的那一项是谁,
        # 靠数行数去猜不算说清楚。
        with self._lock:
            pending = [n for n in self._order if self._state[n] == STATE_RUNNING]
        for name in pending:
            self._write(self._line(name, final=True) + "\n")

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
            lines = [self._line(name, locked=True, final=final) for name in self._order]
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

    def _line(self, name: str, *, locked: bool = False, final: bool = False) -> str:
        if not locked:
            with self._lock:
                state, value = self._state[name], self._value[name]
        else:
            state, value = self._state[name], self._value[name]
        if state == STATE_RUNNING and final:
            # 收尾了还没有结论 —— 不许再画转圈符(见 _UNFINISHED_GLYPH)。
            icon = _paint(_UNFINISHED_GLYPH, "info")
            value = value or _UNFINISHED_NOTE
        elif state == STATE_RUNNING:
            icon = _paint(SPINNER_FRAMES[self._frame % len(SPINNER_FRAMES)], "doing")
            value = value or self._elapsed_text(name)
        elif state == STATE_TIMEOUT:
            icon = _paint(_TIMEOUT_GLYPH, "warn")
        else:
            word = _STATE_TO_STATUS_WORD.get(state)
            icon = _glyph_from_authority(word) if word else _paint(_UNFINISHED_GLYPH, "info")
        label = self._label[name]
        # 图标按**显示宽度**占 ICON_COL 格(权威里的图标都是 1 格 + 1 格间隔),
        # 这样标签列与正式行同列;padding 要剥掉颜色码再量,否则会把 ANSI 算进列数。
        # 排版逐格照抄 cli_render.phase():缩进 + 图标(占 ICON_COL 格)+ 标签
        # (占 LABEL_COL 格)+ 两格间隔 + 值 ⇒ 值列落在 VALUE_COL,与正式行同列。
        # 少了最后那两格,值列就会比正式行左移 2 —— 对勾对齐了、值又不齐。
        icon = icon + " " * max(1, _ICON_COL - _display_width(icon))
        label = label + " " * max(0, self._label_width - _display_width(label))
        head = f"{self._indent}{icon}{label}"
        # 值也和正式行一样走 DIM —— 不然同一屏里"值"有的暗有的亮。
        return f"{head}  {_dim(value)}" if value else head

    def _elapsed_text(self, name: str) -> str:
        """转圈行右边那句"已等 N 秒"。

        头两秒不显示 —— 秒级就完事的项闪一下反而更乱;真正需要这句话的是那些
        一等十几秒的。
        """
        if not self._show_elapsed:
            return ""
        started = self._started_at.get(name)
        if started is None:
            return ""
        waited = time.monotonic() - started
        return f"已等 {waited:.0f} 秒" if waited >= 2.0 else ""

    def _write(self, text: str) -> None:
        try:
            self._stream.write(text)
            self._stream.flush()
        except UnicodeEncodeError:
            # Windows 老控制台:换 ASCII 图标再来一次。画不出来也绝不能挡启动。
            try:
                fallback = text
                for glyph, ascii_glyph in _ASCII_GLYPH.items():
                    fallback = fallback.replace(glyph, ascii_glyph)
                self._stream.write(fallback.encode("ascii", "replace").decode("ascii"))
                self._stream.flush()
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001 — 画不出来不是启动失败
            pass


def _display_width(text: str) -> int:
    """终端显示宽度 —— 取全仓唯一那份 (``core.ascii_art.display_width``)。

    那一份会先剥掉 ANSI 转义码再量。本模块现在会给图标上色,不剥的话颜色码
    会被算进列数,标签列整体右移 —— 正是"对齐"这件事最容易翻车的地方。
    """
    try:
        from core.ascii_art import display_width

        return display_width(text)
    except Exception:  # noqa: BLE001
        width = 0
        for ch in _ANSI_RE.sub("", text):
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
