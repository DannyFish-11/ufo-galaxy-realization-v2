"""Phase 0 结构上不许无限卡,而且必须说出卡在哪一个。

所有者反馈的原话:「就卡在零步骤上了,剩下啥都没反应,半天也不出来」。

上一版为什么会卡
----------------
``check_environment`` 用 ``ThreadPoolExecutor`` + 裸 ``f.result()``:

* ``result()`` **没有超时** —— 一个探测挂住,整个 Phase 0 停在那里;
* ``with`` 块退出时 ``shutdown(wait=True)`` 会 **join 全部工作线程** ——
  卡一个就全卡;
* 线程池的线程是**非守护**的,解释器退出时还要 join 它们 ——
  于是连 Ctrl+C 之后的收尾都能被拖住。

而每个探测**自己**的 ``subprocess.run(timeout=)`` 救不了这些:它只管自己起的
那个子进程,管不了 ``shutil.which()``。Windows 的 PATH 里只要有一个掉线的
网络盘,每次 PATH 查找都会干等到 SMB 自己超时。

这一片钉三条:总耗时有上界、并发没丢、卡住的那一项自己报出来。
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

import launcher.env_check as ec


def _events():
    seen = []
    return seen, (lambda name, state, detail: seen.append((name, state, detail)))


class TestItAlwaysComesBack:
    def test_a_probe_that_never_returns_does_not_block_phase_0(self, monkeypatch):
        """核心那一条:一个探测永不返回,check_environment 照样得回来。"""
        monkeypatch.setitem(ec.PROBE_DEADLINE_S, "npm", 1.0)
        seen, on_event = _events()

        t0 = time.monotonic()
        with patch.object(ec, "_probe_npm", lambda: time.sleep(9999)):
            report = ec.check_environment(on_event=on_event)
        elapsed = time.monotonic() - t0

        assert report is not None
        assert elapsed < 30, f"卡了 {elapsed:.1f}s —— 上界没生效"
        assert ("npm", ec.PROBE_TIMEOUT, "1s 没有回应") in seen

    def test_the_timed_out_probe_reports_the_honest_fallback(self, monkeypatch):
        """超时不能变成"探到了个空值" —— 那样下游会以为查过且确实没有。"""
        monkeypatch.setitem(ec.PROBE_DEADLINE_S, "npm", 1.0)
        with patch.object(ec, "_probe_npm", lambda: time.sleep(9999)):
            report = ec.check_environment()
        assert report.npm_installed is False

    def test_a_probe_that_raises_does_not_take_down_startup(self):
        def boom():
            raise RuntimeError("探测自己炸了")

        with patch.object(ec, "_probe_node", boom):
            report = ec.check_environment()
        assert report.node_installed is False

    def test_probe_threads_are_daemons(self):
        """非守护线程会让解释器退出时 join 它们 —— 一个卡住的探测能拖住整个收尾。"""
        import inspect

        src = inspect.getsource(ec._start_probe)
        assert "daemon=True" in src

    def test_nothing_joins_a_stuck_probe(self):
        """``with ThreadPoolExecutor`` 会 join 全部线程,卡一个就全卡。
        这条盯住那个写法没有回来。"""
        import inspect

        # 只看**代码行**:注释里提到 ThreadPoolExecutor 是在说明"原来那个写法
        # 为什么不行",那是记录,不是在用它。(这个坑我在别处踩过三次了。)
        code = [ln for ln in inspect.getsource(ec.check_environment).splitlines() if not ln.lstrip().startswith("#")]
        joined = "\n".join(code)
        assert "ThreadPoolExecutor" not in joined
        assert ".join(" not in joined

    def test_every_probe_has_a_deadline(self):
        for name in ("pip", "npm", "node", "ollama", "electron"):
            assert ec.PROBE_DEADLINE_S.get(name, 0) > 0, f"{name} 没有上界"

    def test_an_unregistered_probe_still_gets_a_bound(self):
        """表里漏一个键不能等于"这一项没有上界"。"""
        seen, on_event = _events()
        value, ok = ec._run_with_deadline("没登记过的", lambda: "拿到了", "兜底", on_event)
        assert (value, ok) == ("拿到了", True)


class TestConcurrencyIsNotLost:
    def test_probes_run_at_the_same_time(self):
        """上一版把串行改成并发(43s → 15s)。加上界的时候不能把它改回串行 ——
        我第一版就改回去了,总耗时立刻从 1s 变成 20s。"""
        delay = 0.6

        def slow(value):
            def _fn():
                time.sleep(delay)
                return value

            return _fn

        t0 = time.monotonic()
        with patch.multiple(
            ec,
            _probe_pip=slow((True, "1")),
            _probe_npm=slow((True, "2", "/npm")),
            _probe_node=slow((True, "3")),
            _probe_ollama=slow((True, True, [])),
        ):
            ec.check_environment()
        elapsed = time.monotonic() - t0
        # 串行会是 4×delay;并发是 ~1×delay。留足余量,只钉"没有累加"。
        assert elapsed < delay * 2.5, f"耗时 {elapsed:.2f}s,像是串行跑的"

    def test_the_deadline_is_measured_from_a_shared_start(self):
        """上界按**这一批共同的**起跑时刻算 —— 按各自调用时刻算就又变回串行。"""
        import inspect

        src = inspect.getsource(ec._collect_probe)
        assert "started_at" in src


class TestItSaysWhichOneIsStuck:
    def test_each_probe_announces_its_start(self):
        seen, on_event = _events()
        ec.check_environment(on_event=on_event)
        started = {name for name, state, _ in seen if state == ec.PROBE_START}
        assert started == {"pip", "npm", "node", "ollama", "electron"}

    def test_each_probe_announces_its_end(self):
        seen, on_event = _events()
        ec.check_environment(on_event=on_event)
        ended = {name for name, state, _ in seen if state in (ec.PROBE_DONE, ec.PROBE_TIMEOUT)}
        assert ended == {"pip", "npm", "node", "ollama", "electron"}

    def test_the_timeout_event_says_how_long_it_waited(self):
        seen, on_event = _events()
        with patch.dict(ec.PROBE_DEADLINE_S, {"ollama": 1.0}):
            with patch.object(ec, "_probe_ollama", lambda: time.sleep(9999)):
                ec.check_environment(on_event=on_event)
        detail = [d for n, s, d in seen if n == "ollama" and s == ec.PROBE_TIMEOUT][0]
        assert "1s" in detail

    def test_every_probe_has_a_screen_label(self):
        """没有标签的话屏幕上会显示键名(node / ollama),而不是人话。"""
        for name in ec.PROBE_DEADLINE_S:
            assert ec.PROBE_LABEL.get(name), f"{name} 没有显示名"

    def test_no_callback_means_no_crash(self):
        """不给回调时行为要和以前一模一样 —— 这个函数仍然不打印任何东西。"""
        report = ec.check_environment()
        assert report.python_ok is True


class TestTheLiveListItself:
    def test_a_pipe_gets_no_cursor_control(self):
        """输出被重定向时,光标控制符会变成一堆垃圾。"""
        import io

        from launcher.live_list import STATE_OK, LiveList

        buf = io.StringIO()
        lst = LiveList([("a", "甲"), ("b", "乙")], stream=buf)
        lst.start()
        lst.update("a", STATE_OK, "好了")
        lst.finish()
        assert "\x1b" not in buf.getvalue()

    def test_a_pipe_still_shows_what_finished(self):
        """非 TTY 不是"没有进度",是换一种形态 —— 日志里照样看得出走到哪了。"""
        import io

        from launcher.live_list import STATE_OK, LiveList

        buf = io.StringIO()
        lst = LiveList([("a", "甲")], stream=buf)
        lst.start()
        lst.update("a", STATE_OK, "24.0")
        lst.finish()
        assert "甲" in buf.getvalue()
        assert "24.0" in buf.getvalue()

    def test_spinner_frames_are_ascii(self):
        """盲文点阵那类字符在 Windows 的 cp936 / cp1252 控制台上会直接
        UnicodeEncodeError,把启动打断。"""
        from launcher.live_list import SPINNER_FRAMES

        for frame in SPINNER_FRAMES:
            frame.encode("ascii")  # 编不了就是这条红

    def test_cjk_labels_line_up(self):
        """中文占两列。不算进去的话标签列会参差不齐。"""
        from launcher.live_list import _display_width

        assert _display_width("Electron 依赖") == _display_width("Electron ") + 4

    def test_an_unknown_item_is_ignored_not_crashed(self):
        import io

        from launcher.live_list import STATE_OK, LiveList

        buf = io.StringIO()
        lst = LiveList([("a", "甲")], stream=buf)
        lst.update("不存在的", STATE_OK, "x")  # 不许抛

    def test_finish_is_idempotent(self):
        import io

        from launcher.live_list import LiveList

        lst = LiveList([("a", "甲")], stream=io.StringIO())
        lst.start()
        lst.finish()
        lst.finish()  # 再调一次不许抛

    def test_a_broken_stream_does_not_stop_startup(self):
        """画不出来不是启动失败。"""

        class Exploding:
            def isatty(self):
                return False

            def write(self, _text):
                raise OSError("管道断了")

            def flush(self):
                pass

        from launcher.live_list import STATE_OK, LiveList

        lst = LiveList([("a", "甲")], stream=Exploding())
        lst.start()
        lst.update("a", STATE_OK, "x")
        lst.finish()


class TestNotProbedIsNotNotInstalled:
    """所有者真机:"第一次启动 ollama 没有准确识别上,第二次才认上。"

    查出来的不是"探测偶尔失手",是**失手之后说了假话**:探测超过墙钟上界时拿到
    的是兜底值 ``(False, False, [])``,而它渲染出来就是 ``未安装`` —— 屏幕上说
    "你没装",事实是"这次没查完"。第一次冷启(缓存冷、杀软逐个扫、ollama 服务
    刚起)最容易超,第二次全热就认上了,现象完全对得上。

    另外补了一条更硬的路:直接问 Ollama 自己的 HTTP 口。它不查 PATH、不起子进程,
    正好绕开首启那两个弱点。
    """

    def test_a_timed_out_probe_does_not_say_not_installed(self, monkeypatch):
        import time as _t

        import launcher.env_check as ec

        monkeypatch.setitem(ec.PROBE_DEADLINE_S, "ollama", 0.3)
        monkeypatch.setattr(ec, "_probe_ollama", lambda: (_t.sleep(5), (True, True, ["qwen3:8b"]))[1])

        report = ec.check_environment()
        assert "ollama" in report.probes_timed_out
        line = next(s for s in report.to_steps() if s.name == "Ollama")
        assert "未安装" not in line.value, f"没等到被说成了没装:{line.value}"
        assert "没查完" in line.value, line.value

    def test_a_real_absence_still_says_not_installed(self):
        """反过来也要成立 —— 真没装就得说没装,不能一律推给"没查完"。"""
        import launcher.env_check as ec

        report = ec.EnvReport("3.11.0", True, "python3", True, ollama_installed=False, ollama_running=False)
        line = next(s for s in report.to_steps() if s.name == "Ollama")
        assert line.value == "未安装", line.value

    def test_the_step_carries_the_timeout_as_machine_evidence(self):
        """人读的那句话之外,还要留一个机器读得到的旗标。"""
        import launcher.env_check as ec

        report = ec.EnvReport("3.11.0", True, "python3", True, probes_timed_out=["ollama"])
        line = next(s for s in report.to_steps() if s.name == "Ollama")
        assert line.detail.get("timed_out") is True

    def test_the_http_route_is_tried_before_spawning_anything(self, monkeypatch):
        """HTTP 答上来了就不该再去 which / 起子进程 —— 那两步正是首启的弱点。"""
        import launcher.env_check as ec

        monkeypatch.setattr(ec, "_probe_ollama_over_http", lambda: (True, True, ["qwen3:8b"]))

        def _must_not_run(*_a, **_k):
            raise AssertionError("HTTP 已经给出结论了,不该再起子进程")

        monkeypatch.setattr(ec.shutil, "which", _must_not_run)
        assert ec._probe_ollama() == (True, True, ["qwen3:8b"])

    def test_http_saying_nothing_is_not_http_saying_no(self):
        """连不上只说明"这条路没问到",不是"没装" —— 必须接着走命令行那条。"""
        import launcher.env_check as ec

        assert ec._probe_ollama_over_http() is None or isinstance(ec._probe_ollama_over_http(), tuple)

    def test_it_honours_ollamas_own_host_variable(self, monkeypatch):
        """地址读 Ollama 自己的 OLLAMA_HOST 约定,不另立一份。"""
        import launcher.env_check as ec

        monkeypatch.setenv("OLLAMA_HOST", "10.0.0.5:11434")
        assert ec._ollama_api_base() == "http://10.0.0.5:11434"
        monkeypatch.setenv("OLLAMA_HOST", "https://box.local:443")
        assert ec._ollama_api_base() == "https://box.local:443"
        monkeypatch.delenv("OLLAMA_HOST")
        assert ec.OLLAMA_DEFAULT_HOST in ec._ollama_api_base()


class TestOneColumnOneColour:
    """实时列表和正式行必须是**同一套**图标、同一条列、同一种颜色。

    所有者真机反馈:"对勾颜色不统一、行列不统一"。量出来的事实是 ——
    正式行(cli_render.phase)图标在第 2 列、有色;实时列表在第 4 列、无色。
    同一屏两条对勾列、两种对勾。

    这一组判据比对的是**画出来的字符串**,不是"两边都 import 了同一个常量"
    —— 后者能过而屏幕照样错位(比如自己又加了缩进)。
    """

    _ICONS = "✓⚠✗·◐|/-\\⏱"

    def _rendered(self, colour: bool):
        """(实时列表的两行, 正式行的两行) —— 都在同一个着色前提下画。"""
        import contextlib
        import io as _io

        import core.ascii_art as aa
        import core.cli_render as cr
        from launcher.live_list import STATE_OK, STATE_TIMEOUT, LiveList

        old_aa, old_cr = aa.ansi_supported, cr.ansi_supported
        aa.ansi_supported = lambda: colour
        cr.ansi_supported = lambda: colour
        try:

            class _Tty(_io.StringIO):
                def isatty(self):
                    return True

            lst = LiveList([("a", "pip"), ("b", "Electron 依赖")], stream=_Tty())
            lst.update("a", STATE_OK, "24.0")
            lst.update("b", STATE_TIMEOUT, "10s 没有回应")
            live = [lst._line("a"), lst._line("b")]

            formal = []
            for name, value, status in (("Python", "3.11.15", "ok"), (".env 覆盖度", "45/193 项", "warn")):
                cap = _io.StringIO()
                with contextlib.redirect_stdout(cap):
                    cr.phase(name, value, status)
                formal.append(cap.getvalue().rstrip("\n"))
            return live, formal
        finally:
            aa.ansi_supported, cr.ansi_supported = old_aa, old_cr

    def _icon_column(self, line: str) -> int:
        from core.ascii_art import display_width

        import re as _re

        plain = _re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line)
        idx = next(i for i, ch in enumerate(plain) if ch in self._ICONS)
        return display_width(plain[:idx])

    def _value_column(self, line: str):
        import re as _re

        from core.ascii_art import display_width

        plain = _re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line).rstrip()
        m = _re.search(r"\S.*?\s{2,}(\S)", plain)
        return display_width(plain[: m.start(1)]) if m else None

    def test_the_icon_sits_in_the_same_column(self):
        live, formal = self._rendered(colour=False)
        cols = {self._icon_column(x) for x in live + formal}
        assert len(cols) == 1, f"同一屏出现了多条对勾列:{sorted(cols)}"

    def test_the_icon_column_is_the_repo_wide_one(self):
        """不是"两边碰巧一样",而是**都等于全仓那一份几何**。"""
        from core.ascii_art import CONTENT_INDENT

        live, formal = self._rendered(colour=False)
        for line in live + formal:
            assert self._icon_column(line) == CONTENT_INDENT

    def test_the_value_sits_in_the_same_column(self):
        from core.ascii_art import VALUE_COL

        live, formal = self._rendered(colour=False)
        for line in live + formal:
            assert self._value_column(line) == VALUE_COL, repr(line)

    def test_the_same_state_gets_the_same_colour(self):
        """✓ 对 ✓、⚠ 对 ⚠:颜色码必须逐个相同。"""
        import re as _re

        live, formal = self._rendered(colour=True)
        codes = lambda s: _re.findall(r"\x1b\[([0-9;]*)m", s)  # noqa: E731
        assert codes(live[0]) == codes(formal[0]), f"✓ 行:{codes(live[0])} vs {codes(formal[0])}"
        assert codes(live[1]) == codes(formal[1]), f"警告行:{codes(live[1])} vs {codes(formal[1])}"

    def test_no_colour_means_no_colour_on_both(self):
        """降级也要一起降 —— 不许一半带色一半不带。"""
        live, formal = self._rendered(colour=False)
        for line in live + formal:
            assert "\x1b[" not in line, repr(line)

    def test_the_spinner_is_the_doing_colour(self):
        """转圈符用的是权威表里 ``doing`` 那一格的颜色,不是自己挑的。"""
        import re as _re

        import core.ascii_art as aa
        import core.cli_render as cr
        from core.cli_render import _STATUS  # noqa: PLC2701

        import io as _io

        from launcher.live_list import LiveList

        old_aa, old_cr = aa.ansi_supported, cr.ansi_supported
        aa.ansi_supported = lambda: True
        cr.ansi_supported = lambda: True
        try:

            class _Tty(_io.StringIO):
                def isatty(self):
                    return True

            line = LiveList([("a", "pip")], stream=_Tty())._line("a")
        finally:
            aa.ansi_supported, cr.ansi_supported = old_aa, old_cr
        want = _STATUS["doing"][1].lstrip("\x1b[").rstrip("m")
        assert _re.findall(r"\x1b\[([0-9;]*)m", line)[0] == want


class TestNoVerdictDoesNotLookLikeProgress:
    """收尾时还没有结论的那一行,不许留一个"静止的转圈符"。

    这不是理论分支:``check_environment`` 在 Python 版本不达标时会在任何探测
    开始**之前**就 early-return —— 五项一个事件都没有;探测中途抛异常也一样
    (``finish()`` 在 main.py 的 ``finally`` 里)。那时候把最后一帧原样定住,
    屏幕上留下的是 ``| pip`` ``/ npm`` 这样的东西:看起来"还在跑",实际这一项
    根本没跑。说的和现实相反,是这个仓库最不许出现的那类缺陷。
    """

    def _finish_without_any_verdict(self, tty: bool):
        import io as _io

        from launcher.live_list import LiveList

        class _Stream(_io.StringIO):
            def isatty(self):
                return tty

        buf = _Stream()
        lst = LiveList([("pip", "pip"), ("npm", "npm")], stream=buf)
        lst.start()
        lst.finish()
        return buf.getvalue()

    def test_a_pipe_says_it_has_no_verdict(self):
        out = self._finish_without_any_verdict(tty=False)
        # 两项都得被说出来 —— 少的那一项是谁,不能靠数行数去猜。
        assert out.count("没有结论") == 2, out
        assert "pip" in out and "npm" in out

    def test_a_tty_does_not_freeze_a_spinner(self):
        from launcher.live_list import SPINNER_FRAMES

        out = self._finish_without_any_verdict(tty=True)
        # 只看最后一帧(final 那一次重绘)。前面的动画帧里当然有转圈符。
        final = out[out.rindex("\x1b[2K") :] if "\x1b[2K" in out else out
        for frame in SPINNER_FRAMES:
            assert frame not in final, f"收尾那一帧里还留着转圈符 {frame!r}: {final!r}"
        assert "没有结论" in final

    def test_no_verdict_is_not_dressed_up_as_a_result(self):
        """没有结论必须和 ✓ / ⚠ / ⏱ 三种"有结论"彻底分开 —— 空 ≠ 未知。"""
        from core.cli_render import _STATUS  # noqa: PLC2701 — 图标的唯一权威
        from launcher.live_list import _TIMEOUT_GLYPH  # noqa: PLC2701

        out = self._finish_without_any_verdict(tty=False)
        verdict_glyphs = {g for g, _color in _STATUS.values() if g != "·"} | {_TIMEOUT_GLYPH}
        for glyph in verdict_glyphs:
            assert glyph not in out, f"没有结论的行画成了 {glyph!r}:{out!r}"

    def test_the_note_survives_an_ascii_only_console(self):
        """Windows 老控制台编不了圆点。编不出来也绝不能挡启动,而且不许静默变成 ✓。"""
        import io as _io

        from launcher.live_list import _UNFINISHED_ASCII, LiveList  # noqa: PLC2701

        class _Ascii(_io.StringIO):
            def isatty(self):
                return False

            def write(self, text):  # 模拟 cp1252:非 ASCII 直接抛
                text.encode("ascii")
                return super().write(text)

        buf = _Ascii()
        lst = LiveList([("pip", "pip")], stream=buf)
        lst.start()
        lst.finish()
        out = buf.getvalue()
        assert _UNFINISHED_ASCII in out, out
        assert "pip" in out


class TestItIsActuallyWiredIntoPhase0:
    def test_main_builds_the_live_list(self):
        """构造得出来 ≠ 用上了。"""
        src = open("main.py", encoding="utf-8").read()
        assert "LiveList" in src
        assert "on_event=" in src

    def test_main_finishes_it_in_a_finally(self):
        """探测抛异常时不收尾的话,重绘线程会一直转,把后面的结论行一帧帧冲掉。"""
        src = open("main.py", encoding="utf-8").read()
        head = src[src.index("正在探测外部工具") :]
        block = head[: head.index("for step in report.to_steps()")]
        assert "finally:" in block
        assert "finish()" in block
