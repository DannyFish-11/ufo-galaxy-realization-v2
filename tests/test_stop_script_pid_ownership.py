"""
stop.sh 的 PID 归属校验（B16）
==============================

修复前 ``stop.sh`` 是这么停后端的::

    kill $(cat .backend.pid) 2>/dev/null && ok "Backend stopped" || true

PID 文件可能是**上次运行留下的陈旧文件**，而那个 PID 早已被系统回收并分配给
别的进程。直接 kill 就是在杀一个无关进程 —— 在开发机上大概率是别人的编辑器、
构建进程或数据库。

同时那段兜底还有个求值优先级 bug::

    pkill -f A && ok "..." || pkill -f B && ok "..." || true

Shell 从左到右求值为 ``(((A && ok) || B) && ok) || true``：第一条 pkill 成功时
``ok`` 会**打印两次**，而第二条 pkill 的执行条件与直觉相反。

本文件用真实子进程验证修复后的行为，而不是只做文本匹配 —— 关键断言是
「一个与本仓库无关的进程不会被误杀」。

Windows 侧的对应实现是 ``stop.bat``（此前完全缺失，仓库只有 start.bat）；
这里只做静态检查，因为无法在 Linux runner 上执行 batch。
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STOP_SH = PROJECT_ROOT / "stop.sh"
STOP_BAT = PROJECT_ROOT / "stop.bat"

_POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="bash 脚本行为测试仅在 POSIX 跑")


@pytest.fixture
def stop_sandbox(tmp_path):
    """把 stop.sh 复制到临时目录 —— 让 SCRIPT_DIR（归属特征）指向那里，
    这样脚本的兜底 pkill 只会匹配临时路径，绝不会碰到真实仓库里的进程。"""
    shutil.copy(STOP_SH, tmp_path / "stop.sh")
    return tmp_path


def _run_stop(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "stop.sh"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=60,
    )


# ── 语法与结构 ──────────────────────────────────────────────────────────────


def test_stop_sh_is_syntactically_valid():
    r = subprocess.run(["bash", "-n", str(STOP_SH)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"stop.sh 语法错误: {r.stderr}"


def test_stop_bat_exists():
    """Windows 用户此前起得来、停不掉 —— 仓库只有 start.bat。"""
    assert STOP_BAT.is_file(), "缺少 stop.bat（Windows 侧无法停止系统）"


def test_stop_bat_also_verifies_pid_ownership():
    """stop.bat 必须和 stop.sh 一样做归属校验，否则 Windows 侧仍会误杀。"""
    text = STOP_BAT.read_text(encoding="utf-8", errors="replace")
    assert "CommandLine" in text, "stop.bat 未读取进程命令行 —— 无法做归属校验"
    assert "REPO_DIR" in text, "stop.bat 未以仓库路径作为归属特征"


def test_no_ambiguous_and_or_chain_in_stop_sh():
    """确认那条 `A && ok || B && ok || true` 优先级陷阱已经不在。"""
    text = STOP_SH.read_text(encoding="utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue  # 注释里解释这个 bug 是允许的
        if "&&" in stripped and "||" in stripped and "pkill" in stripped:
            pytest.fail(f"stop.sh:{lineno} 仍有 pkill 的 &&/|| 混合链（求值优先级陷阱）: {stripped}")


# ── 行为：陈旧 PID ──────────────────────────────────────────────────────────


@_POSIX_ONLY
def test_stale_pid_file_is_cleaned_not_killed(stop_sandbox):
    """PID 已不存在时应当只清理文件，并且不报错退出。"""
    (stop_sandbox / ".backend.pid").write_text("999999", encoding="utf-8")

    r = _run_stop(stop_sandbox)

    assert r.returncode == 0, f"stop.sh 非零退出: {r.stderr}"
    assert not (stop_sandbox / ".backend.pid").exists(), "陈旧 PID 文件未被清理"


@_POSIX_ONLY
def test_garbage_pid_file_does_not_crash(stop_sandbox):
    """PID 文件被写脏时不应崩溃（set -e 下尤其容易整脚本挂掉）。"""
    (stop_sandbox / ".backend.pid").write_text("not-a-pid\n", encoding="utf-8")

    r = _run_stop(stop_sandbox)

    assert r.returncode == 0, f"脏 PID 文件导致 stop.sh 失败: {r.stderr}"
    assert not (stop_sandbox / ".backend.pid").exists()


# ── 行为：PID 复用（本修复的核心）────────────────────────────────────────────


@_POSIX_ONLY
def test_unrelated_process_is_not_killed_when_pid_is_reused(stop_sandbox):
    """**核心断言**：PID 文件指向一个与本仓库无关的进程时，绝不能杀它。

    修复前这个用例会失败 —— 旧代码不做任何归属判断，见文件头。
    """
    victim = subprocess.Popen(
        ["tail", "-f", "/dev/null"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.3)
        assert victim.poll() is None, "无关进程未能启动，用例前提不成立"

        (stop_sandbox / ".backend.pid").write_text(str(victim.pid), encoding="utf-8")

        r = _run_stop(stop_sandbox)
        assert r.returncode == 0, f"stop.sh 非零退出: {r.stderr}"

        time.sleep(0.3)
        assert victim.poll() is None, "无关进程被误杀 —— PID 归属校验失效。\n" f"stop.sh 输出:\n{r.stdout}\n{r.stderr}"

        combined = r.stdout + r.stderr
        assert (
            "拒绝 kill" in combined or "不属于本仓库" in combined
        ), f"未给出拒绝理由，用户无法判断发生了什么:\n{combined}"
    finally:
        victim.terminate()
        try:
            victim.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover
            victim.kill()


@_POSIX_ONLY
def test_owned_process_is_actually_killed(stop_sandbox):
    """反向验证：确实属于本仓库的进程要被停掉，别为了安全把功能也砍了。

    归属特征是 stop.sh 所在目录，所以让子进程的命令行里带上该路径。
    """
    marker = str(stop_sandbox)
    victim = subprocess.Popen(
        [sys.executable, "-c", f"import time,sys; sys.argv.append({marker!r}); time.sleep(120)", marker],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.3)
        assert victim.poll() is None

        (stop_sandbox / ".backend.pid").write_text(str(victim.pid), encoding="utf-8")

        r = _run_stop(stop_sandbox)
        assert r.returncode == 0, f"stop.sh 非零退出: {r.stderr}"

        for _ in range(20):
            if victim.poll() is not None:
                break
            time.sleep(0.1)

        assert victim.poll() is not None, (
            "属于本仓库的进程没有被停掉 —— 归属校验过严，功能被砍。\n" f"stop.sh 输出:\n{r.stdout}\n{r.stderr}"
        )
    finally:
        if victim.poll() is None:  # pragma: no cover
            victim.kill()
            victim.wait(timeout=5)
