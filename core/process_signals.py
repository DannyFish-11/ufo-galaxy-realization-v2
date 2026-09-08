"""进程级信号(SIGINT / SIGTERM)的**归属登记** —— 一处权威。

为什么需要这个登记
------------------
``loop.add_signal_handler(sig, cb)`` 是**覆盖**语义:后注册的把先注册的顶掉,
而且不报错、不留痕。仓库里曾经有两处各自注册:

* ``launcher/gateway.install_signal_handlers`` —— 顶层入口 ``main.py`` 用它挂
  真正的停机(清理 + **取消主协程**);
* ``core/startup.bootstrap_subsystems`` —— 它在 ``main.py`` 启动过程中被调用,
  于是**后**注册,把上面那个顶掉了,而它自己的处理器只 ``await
  shutdown_subsystems()``,**不结束事件循环**。

真跑实测的后果:``timeout --signal=TERM 150 python main.py`` 打进来,日志里只有
一条 zeroconf 注销告警(子系统被关了),而主协程 ``watch_processes()`` 的
``while True`` 照常转,进程 300 秒后仍在,只有 SIGKILL 收得掉。对应到桌面上
就是"托盘退出没反应 / 任务管理器结束不了"。

登记的规矩
----------
谁先 claim 谁是权威;后来者 claim 不到就**不注册**,并把这件事记下来(降级留痕)。
顶层入口最先跑,所以天然拿到归属;``bootstrap_subsystems`` 被单独使用(没有
顶层入口)时仍然拿得到,行为一个字没变。
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger("Galaxy.Signals")

#: 归属者的名字 —— 只在这里定义,两边 import 同一个常量,不各写各的字符串。
SIGNAL_OWNER_LAUNCHER = "launcher(顶层入口 main.py)"
SIGNAL_OWNER_CORE_STARTUP = "core.startup.bootstrap_subsystems"

_lock = threading.Lock()
_owner: Optional[str] = None


def claim_process_signals(owner: str) -> bool:
    """认领进程级信号的归属。

    Returns:
        True  —— 认领成功,调用方可以去装信号处理器;
        False —— 已经有人是权威了,调用方**不许**再装(装了就是把人家顶掉)。
    """
    global _owner
    with _lock:
        if _owner is None:
            _owner = owner
            logger.debug("进程级信号归属: %s", owner)
            return True
        if _owner == owner:
            return True  # 幂等:同一个所有者重复认领不算冲突
        logger.info(
            "跳过注册 SIGTERM/SIGINT:进程级信号已归 %s 所有,%s 不再重复注册"
            "(重复注册会把对方的处理器顶掉,而且不会报错)。",
            _owner,
            owner,
        )
        return False


def process_signals_owner() -> Optional[str]:
    """当前归属者;没人认领过则 None。"""
    with _lock:
        return _owner


def release_process_signals(owner: str) -> bool:
    """交还归属(只有当前归属者能交还)。收尾路径用,失败不抛。"""
    global _owner
    with _lock:
        if _owner == owner:
            _owner = None
            return True
        return False


__all__ = [
    "SIGNAL_OWNER_CORE_STARTUP",
    "SIGNAL_OWNER_LAUNCHER",
    "claim_process_signals",
    "process_signals_owner",
    "release_process_signals",
]
