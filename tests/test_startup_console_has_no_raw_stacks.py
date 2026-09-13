"""启动屏幕上不许出现"红栈紧跟绿勾"。

全新克隆真跑逮到的(不在所有者报的那批里,是跑出来的):

    07:57:26 | ERROR | nats: encountered error
    Traceback (most recent call last):
      ... 二十多行 ...
    ConnectionRefusedError: [Errno 111] Connection refused
      ✓ 消息总线                nats://localhost:4222

NATS 确实连上了 —— 那段栈是 nats-py 在**重连期**打的,它自己后来重试成功。
但屏幕上是"一大段红栈 + 一个绿勾",读的人完全没法判断到底成没成。

这类"库内部的重试过程"不是给人看的结论:每条总线/服务的成败,启动器自己已经
有一行如实的判定。所以把它们从控制台摘掉,一个字不少地照旧写进 logs/lumiv.log。

判据守两件事:
1. 表里那些 logger 不冒泡到根(= 不进控制台),但**必须**挂着落盘 handler ——
   只做前一半就是把证据扔了,那比吵还糟;
2. 我们自己的 logger 不许进这张表 —— 我们的结论就该上控制台。
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _table() -> tuple:
    """从 main.py 里读那张表,不 import main(它会拉起半个后端)。"""
    src = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "_THIRD_PARTY_FILE_ONLY_LOGGERS":
                    return tuple(ast.literal_eval(node.value))
    raise AssertionError("main.py 里找不到 _THIRD_PARTY_FILE_ONLY_LOGGERS")


class TestTheTableItself:
    def test_the_table_exists_and_is_not_empty(self):
        assert _table(), "表是空的 —— 那这段代码什么也没做"

    def test_nats_is_in_it(self):
        """这一条就是真跑里那段栈的来源。"""
        assert "nats" in _table()

    def test_our_own_loggers_are_not_silenced(self):
        """Galaxy 自己的结论必须上控制台 —— 别把自己也摘掉了。"""
        for name in _table():
            assert not name.startswith("Galaxy"), f"把自己的 logger 摘下了控制台:{name}"
            assert name != "root" and name != "", f"整个根 logger 都摘了:{name!r}"


class TestQuietDoesNotMeanLost:
    """降噪不等于丢证据 —— 这是本仓库"降级必须留痕"的同一条规矩。"""

    def test_each_one_keeps_a_file_handler_and_stops_propagating(self):
        """照 main.py 的写法实际配一遍,验两件事都做到了。"""
        table = _table()
        file_handler = logging.NullHandler()  # 站位:验的是"挂上了",不是写进了哪
        try:
            for name in table:
                lg = logging.getLogger(name)
                lg.propagate = False
                lg.addHandler(file_handler)

            for name in table:
                lg = logging.getLogger(name)
                assert lg.propagate is False, f"{name} 还在往根 logger 冒泡 —— 控制台照旧会打"
                assert file_handler in lg.handlers, f"{name} 没挂落盘 handler —— 证据丢了"
        finally:
            for name in table:
                lg = logging.getLogger(name)
                lg.removeHandler(file_handler)
                lg.propagate = True

    def test_main_attaches_the_handler_not_just_kills_propagation(self):
        """只关 propagate、不挂 handler,就是把日志扔了。这一条守的是配对出现。

        看的是那个 for 循环的循环体:两句都得在。
        """
        src = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
        start = src.index("for _noisy in _THIRD_PARTY_FILE_ONLY_LOGGERS:")
        body = src[start : start + 400]
        assert "propagate = False" in body, body
        assert "addHandler(handler)" in body, body


class TestItActuallyLandsWhereWeSay:
    """不看源码,直接按 main.py 的写法配一遍日志,然后**真打一条**看它落在哪。

    结构性判据(propagate/handler 挂没挂)能过而屏幕照旧乱 —— 比如控制台
    handler 挂在了别处。所以这里验的是最终结果:同一条带完整栈的 ERROR,
    控制台上不许有,文件里必须有,而我们自己的结论必须照旧上控制台。
    """

    def _run(self, tmp_path):
        import logging as _lg
        from logging.handlers import RotatingFileHandler

        logfile = tmp_path / "lumiv.log"
        file_h = RotatingFileHandler(str(logfile), encoding="utf-8")
        console_buf = __import__("io").StringIO()
        console_h = _lg.StreamHandler(console_buf)
        console_h.setLevel(_lg.WARNING)  # 与 main.py 一致:控制台只要 WARNING 以上

        root = _lg.getLogger()
        saved = list(root.handlers)
        saved_levels = {n: (_lg.getLogger(n).propagate, list(_lg.getLogger(n).handlers)) for n in _table()}
        try:
            for h in list(root.handlers):
                root.removeHandler(h)
            _lg.basicConfig(
                level=_lg.INFO, format="%(levelname)s|%(message)s", handlers=[file_h, console_h], force=True
            )
            # main.py 里那个循环,逐字同形
            for name in _table():
                lg = _lg.getLogger(name)
                lg.propagate = False
                lg.addHandler(file_h)

            try:
                raise ConnectionRefusedError(111, "Connection refused")
            except ConnectionRefusedError:
                _lg.getLogger("nats").error("nats: encountered error", exc_info=True)
            _lg.getLogger("Galaxy").warning("这一行是我们自己的结论")

            file_h.flush()
            return console_buf.getvalue(), logfile.read_text(encoding="utf-8")
        finally:
            for h in list(root.handlers):
                root.removeHandler(h)
            for h in saved:
                root.addHandler(h)
            for name, (prop, handlers) in saved_levels.items():
                lg = _lg.getLogger(name)
                lg.propagate = prop
                lg.handlers = handlers
            file_h.close()

    def test_the_stack_does_not_reach_the_console(self, tmp_path):
        console, _disk = self._run(tmp_path)
        assert "Traceback" not in console, console[:400]
        assert "ConnectionRefusedError" not in console, console[:400]

    def test_the_stack_is_still_on_disk(self, tmp_path):
        """降噪不等于丢证据。"""
        _console, disk = self._run(tmp_path)
        assert "Traceback" in disk, disk[:400]
        assert "ConnectionRefusedError" in disk, disk[:400]

    def test_our_own_conclusion_still_reaches_the_console(self, tmp_path):
        """把库摘掉的同时不许把自己也摘掉 —— 反向那一半。"""
        console, _disk = self._run(tmp_path)
        assert "这一行是我们自己的结论" in console, console[:400]
