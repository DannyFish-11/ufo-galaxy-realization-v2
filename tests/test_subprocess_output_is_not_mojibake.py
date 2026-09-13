"""子进程输出的解码只有一套规矩 —— 否则中文 Windows 上就是乱码。

真机复现(所有者):"克隆在下面的时候依然有字符串乱码"。

根因不是某一处写错,是**一类**:``subprocess.run(..., text=True)`` 不写
``encoding=`` 时,Python 用 ``locale.getpreferredencoding(False)``。

- 开发机(Linux/macOS)那是 UTF-8,正好蒙对,所以本地永远看不出来;
- 中文 Windows 那是 **cp936(GBK)**,而 npm / node / docker / podman / git
  的输出是 **UTF-8** —— 用 GBK 解 UTF-8 的字节,屏幕上就是一段花的。

第一次扫仓库时这个形状有 **11 处**。挨个改完不算完:不立门的话,下一个
``subprocess.run(..., text=True)`` 又会带回来。所以这里守的是**类**,不是那 11 处。

判据分两条:
1. 开了文本模式(``text=True`` / ``universal_newlines=True``)就必须写
   ``encoding=`` —— 不许把这件事交给 locale 去猜;
2. 拿字节自己 ``.decode()`` 的,要么显式给编码,要么走 ``core.proc_text``
   那个唯一的解码器(它会先严格试 UTF-8,再退控制台代码页,并说出用了哪种)。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

#: 扫这些目录 —— 启动链与桌面侧,也就是屏幕上会显示子进程输出的那些。
_SCANNED = ("launcher", "core", "windows_service", "galaxy_gateway")

_PROC_CALLS = {"run", "Popen", "check_output", "call", "check_call"}
_PROC_MODULES = {"subprocess", "sp", "_sp"}


def _python_files() -> List[Path]:
    files: List[Path] = [REPO_ROOT / "main.py"]
    for name in _SCANNED:
        root = REPO_ROOT / name
        if root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
    return [f for f in files if f.exists()]


def _is_subprocess_call(node: ast.Call) -> bool:
    func = node.func
    name = getattr(func, "attr", None) or getattr(func, "id", None)
    if name not in _PROC_CALLS:
        return False
    owner = getattr(func, "value", None)
    mod = getattr(owner, "id", "") or getattr(owner, "attr", "")
    return mod in _PROC_MODULES


def _text_mode_without_encoding() -> List[Tuple[str, int]]:
    bad: List[Tuple[str, int]] = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_subprocess_call(node):
                continue
            kwargs = {kw.arg for kw in node.keywords if kw.arg}
            texty = ("text" in kwargs) or ("universal_newlines" in kwargs)
            if texty and "encoding" not in kwargs:
                bad.append((str(path.relative_to(REPO_ROOT)), node.lineno))
    return bad


def _bare_decode_on_process_bytes() -> List[Tuple[str, int]]:
    """``subprocess.check_output(...).decode()`` 这种:不给编码就是在猜。

    只认**直接挂在子进程调用上**的 ``.decode()`` —— 变量绕一手的抓不到,但那
    一类由上面那条(文本模式)覆盖,两条合起来堵住的是同一件事。
    """
    bad: List[Tuple[str, int]] = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "decode"):
                continue
            if not (isinstance(func.value, ast.Call) and _is_subprocess_call(func.value)):
                continue
            # 位置参数第一个就是编码;关键字 encoding= 也算。
            if node.args or any(kw.arg == "encoding" for kw in node.keywords):
                continue
            bad.append((str(path.relative_to(REPO_ROOT)), node.lineno))
    return bad


class TestTextModeAlwaysNamesItsEncoding:
    def test_no_subprocess_text_mode_without_encoding(self):
        bad = _text_mode_without_encoding()
        assert not bad, (
            "以下 subprocess 调用开了文本模式却没写 encoding —— 中文 Windows 上会用 "
            "cp936 去解 UTF-8 的输出,屏幕上就是乱码。\n"
            '改法:补 encoding="utf-8", errors="replace"(或改用 core.proc_text.run_text)。\n'
            + "\n".join(f"  {p}:{ln}" for p, ln in bad)
        )

    def test_no_bare_decode_on_subprocess_bytes(self):
        bad = _bare_decode_on_process_bytes()
        assert not bad, (
            "以下地方直接对子进程的字节 .decode() 却没说按什么编码 —— 这是在猜。\n"
            "改法:走 core.proc_text.decode_output(),它先严格试 UTF-8、再退控制台代码页,"
            "并把用了哪一种一起返回。\n" + "\n".join(f"  {p}:{ln}" for p, ln in bad)
        )


class TestTheDecoderItself:
    def test_utf8_is_tried_first_and_named(self):
        from core.proc_text import decode_output

        text, enc = decode_output("北京 npm ✓".encode("utf-8"))
        assert text == "北京 npm ✓"
        assert enc == "utf-8"

    def test_a_gbk_payload_does_not_come_back_as_mojibake(self):
        """老工具按 cp936 吐字节时,不许硬按 UTF-8 解出一堆替换符。"""
        import core.proc_text as pt

        data = "启动失败".encode("cp936")
        old = pt.console_encoding
        pt.console_encoding = lambda: "cp936"
        try:
            text, enc = pt.decode_output(data)
        finally:
            pt.console_encoding = old
        assert text == "启动失败", text
        assert enc == "cp936"

    def test_undecodable_bytes_degrade_but_say_so(self):
        """两条路都不成时可以有替换符,但必须**留痕** —— 不许假装解开了。"""
        import core.proc_text as pt

        old = pt.console_encoding
        pt.console_encoding = lambda: "ascii"
        try:
            text, enc = pt.decode_output(b"\xff\xfe\x00bad")
        finally:
            pt.console_encoding = old
        assert enc.endswith("+replace"), enc
        assert text  # 不抛、也不是空

    def test_empty_is_not_unknown(self):
        from core.proc_text import decode_output

        text, enc = decode_output(b"")
        assert text == ""
        assert enc == "utf-8"

    def test_run_text_cannot_forget_the_encoding(self):
        """``run_text`` 存在的意义就是"漏不掉" —— 直接验它传下去的参数。"""
        import core.proc_text as pt

        seen = {}

        def _fake_run(cmd, **kwargs):
            seen.update(kwargs)
            return None

        old = pt.subprocess.run
        pt.subprocess.run = _fake_run
        try:
            pt.run_text(["echo", "hi"])
        finally:
            pt.subprocess.run = old
        assert seen.get("encoding") == "utf-8"
        assert seen.get("errors") == "replace"
        assert seen.get("text") is True

    def test_caller_can_still_override(self):
        import core.proc_text as pt

        seen = {}

        def _fake_run(cmd, **kwargs):
            seen.update(kwargs)
            return None

        old = pt.subprocess.run
        pt.subprocess.run = _fake_run
        try:
            pt.run_text(["echo", "hi"], encoding="cp936", capture_output=False)
        finally:
            pt.subprocess.run = old
        assert seen.get("encoding") == "cp936"
        assert seen.get("capture_output") is False

    def test_console_encoding_never_returns_none(self):
        """调用方要的是"退一步用什么",不是"知不知道" —— 这里必须给得出名字。"""
        from core.proc_text import console_encoding

        enc = console_encoding()
        assert isinstance(enc, str) and enc
        "".encode(enc)  # 编码名必须是真能用的
