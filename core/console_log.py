"""控制台日志的两条规矩:**不在事件循环里写**;**警告只进日志文件**(``-v`` 才上屏)。

所有者 Windows 真机启动日志(照片)::

    19:17:50 | WARNING | 事件循环被卡住 13.8 秒 —— 卡在 main.py:382 emit ← core\\performance.py:562 …

卡住事件循环 13.8 秒的,是**往控制台写一行日志**。Windows 控制台在被选中文字(QuickEdit:
在窗口里点一下就进入选择)时会把所有写入挂起,直到按 Esc / 回车 —— 而日志一直是在事件循环那根
线程里同步写的,于是整个后端跟着停住:面板的请求、感知帧、语音全部排队。

1. **写控制台挪到一根专门的线程**(``QueueHandler`` → ``QueueListener``):事件循环只把记录放进
   队列就走。控制台被挂起,挂起的只是那根线程;日志文件照写不误。
2. **控制台只上结论和错误**。启动时每一项的成败启动器自己已经打了一行(✓ / ⚠ / ✗,见
   ``launcher/services.py`` 的 ``_emit``),中间夹着的 ``WARNING`` 是过程诊断 —— 卡顿位置、慢请求、
   下载源探测、某个模型这次没拉下来…… 所有者:「其他东西好了以后都是打对勾,说明这些东西本身
   都该隐藏」。它们一个字不少地进 ``logs/lumiv.log``;``python main.py -v``(``GALAXY_VERBOSE``)
   时照旧上屏。``ERROR`` 及以上永远上屏。
"""

from __future__ import annotations

import atexit
import logging
import logging.handlers
import os
import queue
import sys
from typing import List

__all__ = ["ConsoleGate", "off_the_loop"]

_listeners: List[logging.handlers.QueueListener] = []


class ConsoleGate(logging.Filter):
    """挂在控制台 handler 上:``ERROR`` 及以上放行;``WARNING`` 只在 ``-v`` 时放行。

    每条记录现读 ``GALAXY_VERBOSE`` —— 日志配置在解析命令行之前就装好了,``-v`` 是之后才知道的。
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 — logging 的接口名
        if record.levelno >= logging.ERROR:
            return True
        return bool(os.environ.get("GALAXY_VERBOSE"))


class _QueueHandler(logging.handlers.QueueHandler):
    """解释器正在退出时(还有对象的 ``__del__`` 在记日志,比如没关的 aiohttp 会话),``prepare`` 里的
    ``copy`` 已经不能用 —— 那一刻不再打一整段「--- Logging error ---」栈。"""

    def handleError(self, record: logging.LogRecord) -> None:
        if sys.meta_path is None:
            return
        super().handleError(record)


def off_the_loop(*handlers: logging.Handler) -> logging.Handler:
    """把这些 handler 挪到一根专门的线程上写;返回挂到 logger 上的那个(只往队列里放)。

    进程退出时把队列里剩下的写完(``atexit``)。
    """
    q: "queue.SimpleQueue[logging.LogRecord]" = queue.SimpleQueue()
    listener = logging.handlers.QueueListener(q, *handlers, respect_handler_level=True)
    listener.start()
    _listeners.append(listener)
    atexit.register(listener.stop)
    qh = _QueueHandler(q)
    # 放进队列前只把消息(连同异常栈)拼好;时间、级别那一套由各 handler 自己的格式加。
    qh.setFormatter(logging.Formatter("%(message)s"))
    return qh
