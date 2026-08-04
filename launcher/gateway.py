"""launcher/gateway.py — 网关就绪等待与子进程收尾

从 ``launch_desktop.py`` 搬来的两组要素
----------------------------------------
``launch_desktop.py`` 在 ``docs/LAUNCHER_UNIFICATION_PLAN.md`` §2 登记的"真实有效
的要素"里，有两组在全仓**没有第二处实现**，删掉它本体之前必须先有新家：

1. ``gateway_is_ready()`` / ``wait_for_gateway()`` —— **就绪等待语义**。
   桌面壳要等网关真的能应答 ``/health`` 才拉起，否则前端一开就是一片
   ``fetch failed``。``launcher/health_checks.py`` 是**启动完成后跑一次**的探针，
   不是"轮询到就绪"的等待器，两者不能互相替代。

2. ``kill_proc()`` —— **子进程收尾**。先 ``terminate`` 给机会优雅退出，超时再
   ``kill``，最后**关掉日志文件句柄**。最后那步容易被忽略：不关的话 Windows 上
   会留下占用，下一次启动写 ``logs/electron.log`` 直接被拒。

刻意不并进 :mod:`launcher.shutdown`
-----------------------------------
那个模块是 ``async_shutdown()`` —— 整套系统的**异步优雅停机**（NATS、子系统）。
``kill_proc`` 是**同步**地收一个 ``Popen``，被信号处理器直接调用。两者的调用时机、
同步性、失败语义都不同，合并只会让信号处理路径被迫 ``await``。

端口来源
--------
``get_gateway_health_url()`` 走 ``core.electron_launch_guard.resolve_gateway_port()``
—— 与桌面壳解析端口的是**同一处**。这一条不能各写各的：壳按 A 端口连、等待器按
B 端口探，就会出现"等到了但连不上"。
"""

from __future__ import annotations

import logging
import subprocess
import time
import urllib.request
from typing import Any, Optional

logger = logging.getLogger("Galaxy.Gateway")

#: 等待网关就绪的总超时（秒）。取自 ``launch_desktop.GATEWAY_READY_TIMEOUT``。
GATEWAY_READY_TIMEOUT = 90.0

#: 轮询间隔（秒）。取自 ``launch_desktop.HEALTH_CHECK_INTERVAL``。
HEALTH_CHECK_INTERVAL = 1.0

#: 单次探测的超时（秒）。短是刻意的：这是轮询，卡住一次就少一次机会。
PROBE_TIMEOUT = 2.0

GATEWAY_HOST_DEFAULT = "127.0.0.1"


def gateway_health_url(host: Optional[str] = None) -> str:
    """网关健康检查 URL。

    端口经 ``core.electron_launch_guard.resolve_gateway_port()`` 解析 —— 与桌面壳
    用的是同一处。各写各的会出现"等到了但连不上"。
    """
    import os

    h = host or os.getenv("HOST", GATEWAY_HOST_DEFAULT)
    try:
        from core.electron_launch_guard import resolve_gateway_port

        port = resolve_gateway_port()
    except Exception:  # noqa: BLE001
        port = int(os.getenv("PORT", "9000"))
    return f"http://{h}:{port}/health"


def gateway_is_ready(host: Optional[str] = None) -> bool:
    """网关此刻能不能应答 ``/health``。单次探测，不重试。"""
    try:
        with urllib.request.urlopen(gateway_health_url(host), timeout=PROBE_TIMEOUT) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def wait_for_gateway(
    timeout: float = GATEWAY_READY_TIMEOUT,
    *,
    host: Optional[str] = None,
    interval: float = HEALTH_CHECK_INTERVAL,
) -> bool:
    """轮询到网关就绪，或超时。返回是否就绪。

    每 5 次探测打一条"等待中(Ns)" —— 慢机器上首启要几十秒，没有这条日志看着
    就像卡死了。
    """
    start = time.time()
    dots = 0
    while time.time() - start < timeout:
        if gateway_is_ready(host):
            return True
        time.sleep(interval)
        dots += 1
        if dots % 5 == 0:
            logger.info("    ... 等待中 (%ds)", int(time.time() - start))
    return False


def kill_proc(proc: Any, name: str, timeout: float = 5.0) -> None:
    """收掉一个子进程：先给机会优雅退出，超时再强杀，最后**关日志句柄**。

    最后那步不是可有可无的：不关的话 Windows 上会留下文件占用，下一次启动写
    ``logs/electron.log`` 直接被拒 —— 而报错指向的是"日志写不了"，不是"上次没关"。
    """
    if proc is None or proc.poll() is not None:
        return
    logger.info("[%s] 正在停止...", name)
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    finally:
        handle = getattr(proc, "_stdout_handle", None)
        if handle is not None:
            try:
                handle.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# 信号处理：从 unified_launcher.main() 保下来的那套
# ---------------------------------------------------------------------------


def install_signal_handlers(loop: Any, on_shutdown: Any) -> None:
    """在事件循环上注册 SIGINT / SIGTERM 的优雅停机。

    从 ``unified_launcher.main()`` 保下来的。删掉那个入口之前必须先搬 ——
    ``main.py`` 只有 ``except KeyboardInterrupt``，那**只覆盖 SIGINT**，
    ``kill <pid>``（SIGTERM，systemd / 托盘 / 任务管理器走的就是它）会直接终止
    进程，跳过所有清理：子进程不收、``.electron.pid`` 锁不清、NATS 不断开。

    两条真机来的细节，都不能省：

    1. **优先 ``loop.add_signal_handler``**，因为 ``signal.signal()`` 在 async
       上下文里不安全 —— 它能在任意点打断事件循环，损坏协程状态。
    2. **Windows 上必须有回退**。``ProactorEventLoop`` 的 ``add_signal_handler``
       抛 ``NotImplementedError``，而那个异常**不被外层 ``except
       KeyboardInterrupt`` 捕获** → 启动器当场崩。回退到 ``signal.signal``
       （Windows 上 SIGINT/SIGTERM 可用）。非主线程注册不了则静默跳过。
    """
    import signal as _signal

    for sig in (_signal.SIGINT, _signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, on_shutdown)
        except (NotImplementedError, RuntimeError):
            try:
                _signal.signal(sig, lambda *_a: on_shutdown())
            except (ValueError, OSError):
                pass  # 非主线程等场景无法注册，忽略


def remove_signal_handlers(loop: Any) -> None:
    """收尾时摘掉信号处理器。失败不抛 —— 这是清理路径。"""
    import signal as _signal

    for sig in (_signal.SIGINT, _signal.SIGTERM):
        try:
            loop.remove_signal_handler(sig)
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "install_signal_handlers",
    "remove_signal_handlers",
    "GATEWAY_READY_TIMEOUT",
    "HEALTH_CHECK_INTERVAL",
    "PROBE_TIMEOUT",
    "gateway_health_url",
    "gateway_is_ready",
    "wait_for_gateway",
    "kill_proc",
]
