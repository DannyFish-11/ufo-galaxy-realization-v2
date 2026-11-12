"""core/own_process.py —— 停我们自己拉起的进程:按 PID 与它自己的进程组,不按命令行里的一个词。

第 10 轮查到:停本地主脑时跑 ``pkill -f ollama``(Windows 上 ``taskkill /IM ollama.exe``),命令行里**任何地方**带
ollama 的进程都被杀 —— 人自己开的 Ollama、打开着 ollama.log 的编辑器、命令行里带着某个 ``test_*ollama*.py`` 的测试进程。
拉起时记下 ``Popen``,停的时候只停它(连同它拉起的子进程)。
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from typing import Any, Dict

#: 请它退之后最多等多久(秒),再强停
GRACE_S = 10.0

#: 拉起时带上:让它自成一组(POSIX 新会话、Windows 新进程组),停的时候连它拉起的子进程一起停,停组也不会停到别人
OWN_GROUP_KW: Dict[str, Any] = (
    {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    if sys.platform == "win32"
    else {"start_new_session": True}
)


def stop_own_process(proc: "subprocess.Popen") -> None:
    """停一个我们自己拉起的进程(连同它拉起的子进程):先请它退,``GRACE_S`` 秒不退再强停。阻塞:在工作线程里调。

    POSIX 上拉起时要 ``start_new_session=True`` —— 那样它的进程组就是它自己,停组不会停到别人。
    """
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=GRACE_S)
        return
    import signal

    own_group = os.getpgid(proc.pid) == proc.pid
    try:
        os.killpg(proc.pid, signal.SIGTERM) if own_group else proc.terminate()
    except (ProcessLookupError, PermissionError):
        return
    try:
        proc.wait(timeout=GRACE_S)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL) if own_group else proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=GRACE_S)  # 强停之后也要收:不收就留一个僵尸进程


def stop_and_close(proc: "subprocess.Popen", *, read_s: float = 1.0) -> str:
    """停掉(连同它拉起的子进程)、收掉、关上它的管道;返回它 stderr 里读得到的那一段(已经自己退了的进程才读)。
    阻塞:在工作线程里调。

    读 stderr 有期限:它拉起的孙子进程可能还攥着管道,EOF 永远不来(``core/skill_md_loader.py`` 撞过)。
    曾经的写法是起来了、没接上就撒手不管:进程后来自己退了,没人 wait,变成僵尸(第 18 轮全接口扫描后数到 8 个
    ``npm exec`` 僵尸,``core/mcp_loader.py``)。
    """
    err: Any = b""
    if proc.poll() is not None and proc.stderr is not None:
        with contextlib.suppress(Exception):
            _out, err = proc.communicate(timeout=read_s)
    stop_own_process(proc)
    for pipe in (proc.stdin, proc.stdout, proc.stderr):
        if pipe is not None:
            with contextlib.suppress(Exception):
                pipe.close()
    text = err.decode("utf-8", "replace") if isinstance(err, bytes) else str(err or "")
    return text[:4000]


__all__ = ["GRACE_S", "OWN_GROUP_KW", "stop_and_close", "stop_own_process"]
