"""core/proc_text.py — 子进程输出怎么变成字符串。**全仓唯一一处**。

为什么要有这个模块
------------------
所有者真机反馈:"克隆在下面的时候依然有字符串乱码"。

根因是一类而不是一处。``subprocess.run(..., text=True)`` **不写 ``encoding=``**
时,Python 用的是 ``locale.getpreferredencoding(False)``:

- Linux / macOS：通常是 UTF-8，正好蒙对，所以本地怎么跑都看不出问题；
- 中文 Windows：是 **cp936(GBK)**。而 npm / node / docker / podman / git 这些
  工具的输出是 **UTF-8**。用 GBK 去解 UTF-8 的字节 —— 屏幕上就是乱码。

于是同一份代码在开发机上干干净净，在所有者的 Windows 上一段一段花屏。扫下来
仓库里有 11 处是这个形状(见 ``tests/test_subprocess_output_is_not_mojibake.py``
里的那道门)，所以这里给它一个**唯一的出口**，并用门禁挡住新的。

为什么不是"统一写 encoding='utf-8'"就完事
------------------------------------------
因为那样会从"猜 GBK"变成"猜 UTF-8"——大多数时候对，但 Windows 上仍有一批**老
工具**按控制台的 OEM 代码页输出(``chcp`` 那个数)。所以这里不猜:

1. 先按 UTF-8 严格解码。成了就是 UTF-8，没有任何猜测成分；
2. 不成，再按控制台代码页(拿不到就用 locale)解，并**记下用的是哪一种**；
3. 都不成，UTF-8 + ``errors="replace"`` 兜底 —— 宁可有几个替换符，也不能抛。

调用方拿到的是 ``(文本, 用了哪种编码)``。用了哪种是**事实**，不是装饰:
排查乱码时第一个要问的就是它。
"""

from __future__ import annotations

import locale
import os
import subprocess
from typing import Any, Optional, Sequence, Tuple

__all__ = [
    "console_encoding",
    "decode_output",
    "run_text",
    "TEXT_KWARGS",
]

#: 第一顺位。npm / node / docker / podman / git 都是它。
_PRIMARY = "utf-8"


def console_encoding() -> str:
    """这台机器上"控制台那一套"的编码名。

    Windows 上问的是控制台**输出**代码页(``GetConsoleOutputCP``)——那正是老工具
    往管道里写字节时用的那一套。问不到、或者不是 Windows，就退回 locale。

    注意这里绝不返回 ``None``:调用方要的是"退一步用什么"，而不是"知不知道"。
    """
    if os.name == "nt":
        try:
            import ctypes

            cp = int(ctypes.windll.kernel32.GetConsoleOutputCP())  # type: ignore[attr-defined]
            if cp > 0:
                return f"cp{cp}"
        except Exception:  # noqa: BLE001 —— 问不到就往下退,不是错误
            pass
    return locale.getpreferredencoding(False) or _PRIMARY


def decode_output(data: Optional[bytes]) -> Tuple[str, str]:
    """把子进程的字节变成字符串。

    Returns:
        ``(文本, 用的编码名)``。编码名里的 ``"utf-8+replace"`` 表示**两条路都没
        严格解成**，文本里可能有替换符 —— 这是"降级留痕"，不是细节。
    """
    if not data:
        return "", _PRIMARY
    try:
        return data.decode(_PRIMARY), _PRIMARY
    except UnicodeDecodeError:
        pass
    fallback = console_encoding()
    if fallback.lower().replace("_", "-") not in ("utf-8", "utf8"):
        try:
            return data.decode(fallback), fallback
        except (UnicodeDecodeError, LookupError):
            pass
    return data.decode(_PRIMARY, errors="replace"), f"{_PRIMARY}+replace"


#: 想继续用 ``text=True`` 的调用点,把这个展开进去就不会再漏 ``encoding``。
#:
#: 用 ``errors="replace"`` 而不是默认的 ``strict``:一个解不开的字节不该让
#: 整条启动链抛异常 —— 那是"为了显示好看而炸掉功能"。
TEXT_KWARGS = {"text": True, "encoding": _PRIMARY, "errors": "replace"}


def run_text(
    cmd: Sequence[str] | str,
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    """``subprocess.run`` 的文本版 —— **编码这件事这里说了算**。

    和直接调 ``subprocess.run(..., text=True)`` 的区别只有一个:不会漏掉
    ``encoding``。其余参数原样透传。

    ``capture_output`` 默认开着:这个函数存在的意义就是**拿输出**,而拿输出
    才会遇到解码。不想拿的调用点本来也不需要它。
    """
    kwargs.setdefault("capture_output", True)
    for key, value in TEXT_KWARGS.items():
        kwargs.setdefault(key, value)
    return subprocess.run(cmd, **kwargs)  # noqa: S603 —— 命令由调用方给,这里只管解码
