"""停机要安静:真跑 Ctrl+C 之后,控制台上还冒出一段「--- Logging error ---」栈和一条 aiohttp 的
ERROR「Unclosed client session」。

* 在场桥共享的 IPC HTTP 会话一直没人关 —— 停机时由 ``shutdown_subsystems`` 关掉;
* 解释器退出阶段还有对象的 ``__del__`` 在记日志,日志队列的 ``prepare`` 那时已经不能 ``copy`` ——
  那一刻不再打一整段栈。
"""

from __future__ import annotations

import asyncio
import inspect
import io
import logging
import sys


def test_the_bridge_closes_its_shared_ipc_session():
    from core.lumiv_websocket_bridge import GalaxyPresenceBridge as B

    async def run():
        session = B._ipc_session()
        assert not session.closed
        await B.close_ipc_session()
        assert session.closed and B._ipc_http_session is None
        await B.close_ipc_session()  # 再关一次无害

    asyncio.run(run())


def test_shutdown_subsystems_closes_it():
    import core.startup as st

    assert "GalaxyPresenceBridge.close_ipc_session()" in inspect.getsource(st.shutdown_subsystems)


def test_logging_during_interpreter_exit_does_not_dump_a_traceback(monkeypatch):
    import queue

    from core import console_log

    handler = console_log._QueueHandler(queue.SimpleQueue())
    record = logging.LogRecord("x", logging.ERROR, __file__, 1, "late", None, None)
    err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    saved = sys.meta_path
    sys.meta_path = None
    try:
        handler.handleError(record)
    finally:
        sys.meta_path = saved
    assert err.getvalue() == ""


def test_nodes_are_stopped_together_not_one_after_another():
    """真跑停机:事件循环卡在 ``stop_service`` 的 ``wait`` 上 2.6 秒 —— 各节点逐个 terminate + 等,
    停机时间是各自之和。现在一起 terminate、一起等。"""
    import subprocess
    import sys
    import time

    from launcher.bootstrap import ServiceType
    from launcher.service_manager import ServiceInfo, ServiceManager

    slow_exit = (
        "import signal, sys, time\n"
        "signal.signal(signal.SIGTERM, lambda *a: (time.sleep(1.0), sys.exit(0)))\n"
        "print('up', flush=True)\n"
        "time.sleep(30)\n"
    )
    mgr = ServiceManager.__new__(ServiceManager)
    mgr.services = {}
    for i in range(3):
        proc = subprocess.Popen([sys.executable, "-c", slow_exit], stdout=subprocess.PIPE, text=True)
        assert proc.stdout.readline().strip() == "up"
        info = ServiceInfo(name=f"node{i}", service_type=ServiceType.NODE)
        info.process = proc
        info.status = "running"
        mgr.services[info.name] = info
    procs = [s.process for s in mgr.services.values()]
    t0 = time.monotonic()
    mgr.stop_all()
    took = time.monotonic() - t0
    assert all(p.poll() is not None for p in procs)
    assert all(s.status == "stopped" and s.process is None for s in mgr.services.values())
    assert took < 2.5, f"三个各要 1 秒才退的节点停了 {took:.1f} 秒 —— 还在一个一个等"
