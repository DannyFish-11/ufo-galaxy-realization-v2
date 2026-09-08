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
