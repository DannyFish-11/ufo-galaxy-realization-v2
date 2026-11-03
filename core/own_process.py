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

#: 请它退之后最多等多久(秒),再强停
GRACE_S = 10.0


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


__all__ = ["GRACE_S", "stop_own_process"]
