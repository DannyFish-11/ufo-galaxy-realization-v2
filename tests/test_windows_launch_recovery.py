"""所有者 Windows 真机启动日志(2026-07-28 16:10~16:13)暴露问题的回归测试。

那一次启动的因果链是:

    os.kill(pid, 0) 在 Windows 上其实是 TerminateProcess
      ├─ pid 已失效 → WinError 87 包成 SystemError 逃出 except(OSError, ValueError)
      │                → Phase 6 崩 → "Startup validation failed" CRITICAL
      └─ 陈旧锁被当成"壳还活着" → start_tauri() 早退 True → start_desktop_shell()
                                 短路 → 13 次"重启中"一次都没真的重启

    Electron 单次 /health 探测失败 → spawn 第二套完整后端去抢 9000
      → [Errno 10048] → 网关不可达 → 覆盖层彻底放弃

    崩溃聚合器把一句提到 "CRITICAL" 的**建议文案**当成崩溃锚点
      → 指纹错位 → 同一个崩溃在聚合视图里出现两次

本文件逐条钉死修复后的行为。
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


# ── 1. 桌面壳锁:只读探活,绝不误杀、绝不上抛 ──────────────────────────


@pytest.fixture()
def temp_lock(tmp_path, monkeypatch):
    """把桌面壳锁指到临时文件,避免污染项目根的 .electron.pid。"""
    import core.electron_launch_guard as guard

    lock = tmp_path / ".electron.pid"
    monkeypatch.setattr(guard, "lock_path", lambda: str(lock))
    return lock


def _dead_pid() -> int:
    """拿一个确定已经退出且已被回收的 pid。"""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_pid_alive_reports_self_alive():
    import os as _os

    from core.electron_launch_guard import _pid_alive

    assert _pid_alive(_os.getpid()) is True


def test_pid_alive_reports_dead_pid_dead():
    from core.electron_launch_guard import _pid_alive

    assert _pid_alive(_dead_pid()) is False


def test_pid_alive_rejects_nonpositive_pid():
    """pid<=0 在 POSIX 上是"整个进程组"的意思,绝不能当成普通探活放行。"""
    from core.electron_launch_guard import _pid_alive

    assert _pid_alive(0) is False
    assert _pid_alive(-1) is False


def test_already_running_never_raises_on_garbage_lock(temp_lock):
    """锁文件内容损坏时必须安静返回 False。

    它被 Phase 6 直接调用,一旦上抛就会把整个启动预检判为失败(真机实证:
    SystemError 逃出 except 子句 → Startup validation failed CRITICAL)。
    """
    from core.electron_launch_guard import already_running

    for garbage in ("", "   ", "not-a-pid", "12 34", "9999999999999999999999"):
        temp_lock.write_text(garbage, encoding="utf-8")
        assert already_running() is False


def test_already_running_clears_stale_lock(temp_lock):
    """死进程留下的锁必须被清掉 —— 否则保活重启会永远空转。"""
    from core.electron_launch_guard import already_running

    temp_lock.write_text(str(_dead_pid()), encoding="utf-8")
    assert already_running() is False
    assert not temp_lock.exists(), "陈旧锁必须被清理,否则 start_tauri 会一直早退"


def test_already_running_true_for_live_pid_without_killing_it(temp_lock):
    """活着的壳要被认出来,而且**探完还得活着**。

    旧实现在 Windows 上会把它 TerminateProcess 掉再返回 True。这里用一个真实
    的子进程验证探活是只读的。
    """
    from core.electron_launch_guard import already_running

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        temp_lock.write_text(str(proc.pid), encoding="utf-8")
        assert already_running() is True
        assert proc.poll() is None, "探活绝不允许杀掉被探测的进程"
    finally:
        proc.kill()
        proc.wait()


def test_guard_does_not_use_os_kill_as_windows_liveness_probe():
    """生产代码里不得再出现 `os.kill(pid, 0)` 式的跨平台探活。

    Windows 上它走的是 TerminateProcess —— 这是本次真机故障的总根因。
    POSIX 分支里的 os.kill 是合法的,故只禁止"无平台判断"的用法:
    要求 os.kill 出现处的上下文里有 POSIX 分支标记。
    """
    src = (REPO / "core" / "electron_launch_guard.py").read_text(encoding="utf-8")
    # 只看真正的调用语句(行首就是 os.kill(),排除文档/注释里对它的讨论)
    calls = [(lineno, line) for lineno, line in enumerate(src.splitlines(), 1) if line.strip().startswith("os.kill(")]
    assert calls, "预期 POSIX 分支仍保留 os.kill 探活"
    for lineno, line in calls:
        assert "POSIX" in line, f"electron_launch_guard.py:{lineno} 的 os.kill 缺少 POSIX 限定"


# ── 2. 端口预检 ────────────────────────────────────────────────────────


def test_probe_port_bindable_detects_occupied_port():
    from launcher.services import _probe_port_bindable

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        port = busy.getsockname()[1]
        reason = _probe_port_bindable(port)
        assert reason, "端口已被占用时必须返回失败原因"

    # 占用者关闭后同一端口应重新可绑
    assert _probe_port_bindable(port) == ""


def test_probe_port_detects_wildcard_holder_without_binding_wildcard():
    """别人占着 0.0.0.0:P 时,只探环回口也必须能识别出来。

    这条是"只探环回口"这个设计成立的前提:只要不开 SO_REUSEADDR,通配绑定
    与具体地址绑定在同一端口上互斥,所以环回探测足以覆盖真机那个场景
    (Electron 拉起第二套后端去抢已被占用的 9000)。

    这里的通配 bind 是**刻意**的,也是本用例的全部意义所在——不真的造一个
    uvicorn 那种形态的占用者,就无从验证这个前提,只能靠"我认为"。
    CodeQL 会就此报 py/bind-socket-all-network-interfaces:属实,但已把实际
    暴露面压到零 —— 端口号取 0(临时端口)、**刻意不 listen**(端口占用在
    bind() 时就已成立,不 listen 则永远不可能被任何人连上)、且随 with 立即
    关闭。仅限测试进程内存活数毫秒。
    """
    from launcher.services import _probe_port_bindable

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as wildcard:
        wildcard.bind(("0.0.0.0", 0))  # 模拟 uvicorn 的真实占用形态(见上:不 listen)
        port = wildcard.getsockname()[1]
        assert _probe_port_bindable(port), "通配绑定占着的端口必须被判为不可绑"


def test_probe_port_never_binds_all_interfaces():
    """端口预检自身绝不绑通配地址(CodeQL:Binding a socket to all interfaces)。

    真要防的是"本机已有一个 Galaxy 占着这个端口",环回探测就够;为此开一个
    全网卡绑定既无必要也是真实的攻击面。
    """
    import inspect

    from launcher import services as unified_launcher

    body = inspect.getsource(unified_launcher._probe_port_bindable).split('"""')[-1]
    assert "0.0.0.0" not in body, "端口预检代码体内不应出现通配监听地址"

    # bind 的地址必须来自那个写死为环回口的常量,而不是任何可能为空/通配的变量
    bind_lines = [ln.strip() for ln in body.splitlines() if ".bind(" in ln]
    assert len(bind_lines) == 1, f"预期恰好一处 bind,实际 {bind_lines}"
    assert "_PORT_PROBE_HOST" in bind_lines[0], f"bind 地址应为 _PORT_PROBE_HOST:{bind_lines[0]}"
    assert unified_launcher._PORT_PROBE_HOST == "127.0.0.1"


# ── 3. Electron:端口被占时绝不再拉一套后端 ────────────────────────────


def _main_js() -> str:
    return (REPO / "electron" / "main.js").read_text(encoding="utf-8")


def test_electron_probes_port_before_spawning_backend():
    """spawn 后端之前必须先探端口占用 —— 否则就是真机那次的 10048。"""
    src = _main_js()
    assert "_portOccupied" in src, "缺少端口占用探测"
    # 用真正的 spawn 语句定位,而不是注释里对它的引用
    spawn_at = src.index("path.join(PROJECT_ROOT, 'launch_desktop.py')")
    probe_at = src.index("await _portOccupied()")
    assert probe_at < spawn_at, "端口占用探测必须排在拉起后端之前"


def test_electron_gateway_base_pins_ipv4_loopback():
    """网关绑的是 0.0.0.0(仅 IPv4);客户端用 localhost 可能先解析到 ::1。"""
    src = _main_js()
    assert "const GATEWAY_HOST = '127.0.0.1';" in src
    assert "http://localhost:${GATEWAY_PORT}`;" not in src


def test_electron_creates_window_before_warning_dialog():
    """网关未就绪是可降级状态,不能因为一个没人点的模态框而连壳都不建。"""
    src = _main_js()
    create_at = src.index("createWindow();")
    dialog_at = src.index("title: 'Galaxy 网关未就绪'")
    assert create_at < dialog_at, "createWindow() 必须排在告警模态框之前"


# ── 4. 崩溃聚合器:锚点必须是真的崩溃 ──────────────────────────────────


@pytest.fixture()
def temp_log_root(tmp_path, monkeypatch):
    import importlib

    monkeypatch.setenv("GALAXY_LOG_DIR", str(tmp_path))
    import core.log_paths as lp

    importlib.reload(lp)
    yield tmp_path
    monkeypatch.delenv("GALAXY_LOG_DIR", raising=False)
    importlib.reload(lp)


def test_advice_text_mentioning_critical_is_not_a_crash(temp_log_root):
    """真机原句:预检建议里提到 CRITICAL,被当成了崩溃锚点。"""
    from core.crash_log_aggregator import aggregate_crashes

    (temp_log_root / "gateway.log").write_text(
        "GALAXY_REQUIRE_API_TOKEN=true makes a missing token CRITICAL even with auth off "
        "(staging). Without it, any client can command the API when auth is off.\n"
        "  ✓  All CRITICAL checks passed.\n",
        encoding="utf-8",
    )
    _, count = aggregate_crashes()
    assert count == 0, "建议/汇总文案里的 CRITICAL 不是崩溃"


def test_info_level_lines_are_never_crash_anchors(temp_log_root):
    """INFO 行按定义就不是崩溃记录 —— 含聚合器自己的记账行。"""
    from core.crash_log_aggregator import aggregate_crashes

    (temp_log_root / "lumiv.log").write_text(
        "16:11:59 | INFO | 注册安全规则: 高度限制检查 (critical)\n"
        "16:12:24 | INFO | Crash aggregation: 4 block(s) -> logs\\crashes\\latest.log\n",
        encoding="utf-8",
    )
    _, count = aggregate_crashes()
    assert count == 0


def test_same_crash_in_two_logs_merges_despite_different_context(temp_log_root):
    """同一崩溃分别落在两个日志、前后文不同,聚合视图里只能有一条。

    真机复现:gateway.log 里它前面是一段建议文案、lumiv.log 里前面是别的 INFO,
    旧实现在 gateway.log 那侧锚到了建议文案上,于是同一个崩溃出现了两次。
    """
    from core.crash_log_aggregator import aggregate_crashes

    crash = "16:12:09 | CRITICAL | Startup validation failed: <built-in function kill> returned a result\n"
    (temp_log_root / "gateway.log").write_text(
        "GALAXY_REQUIRE_API_TOKEN=true makes a missing token CRITICAL even with auth off\n" + crash,
        encoding="utf-8",
    )
    (temp_log_root / "lumiv.log").write_text("16:12:08 | WARNING | 别的上下文\n" + crash, encoding="utf-8")

    path, count = aggregate_crashes()
    assert count == 1, "同一崩溃跨来源必须合并为一条"
    body = path.read_text(encoding="utf-8")
    assert "gateway.log" in body and "lumiv.log" in body


def test_single_line_error_block_stops_at_normal_flow(temp_log_root):
    """单行错误不该把后面几十行正常流水一并吞进崩溃块。"""
    from core.crash_log_aggregator import aggregate_crashes

    noise = "".join(f"16:11:5{i % 10} | INFO | 服务已启动: Node_{i:02d}\n" for i in range(30))
    (temp_log_root / "lumiv.log").write_text(
        "16:11:44 | ERROR | nats-server.zip 解压失败: [WinError 183] 当文件已存在时\n" + noise,
        encoding="utf-8",
    )
    path, count = aggregate_crashes()
    assert count == 1
    body = path.read_text(encoding="utf-8")
    assert "WinError 183" in body
    assert "服务已启动" not in body, "崩溃块不应吞入正常流水日志"


def test_traceback_block_keeps_full_stack(temp_log_root):
    """traceback 要完整保留 —— 收窄单行块的同时不能把调用栈砍掉。"""
    from core.crash_log_aggregator import aggregate_crashes

    tb = (
        "Traceback (most recent call last):\n"
        '  File "main.py", line 366, in _run_orchestrator_preflight\n'
        "    summary = orch.run_startup_sequence()\n"
        '  File "core/electron_launch_guard.py", line 95, in already_running\n'
        "    os.kill(existing_pid, 0)\n"
        "SystemError: <built-in function kill> returned a result with an exception set\n"
    )
    (temp_log_root / "gateway.log").write_text(tb, encoding="utf-8")
    path, _ = aggregate_crashes()
    body = path.read_text(encoding="utf-8")
    assert "SystemError" in body, "traceback 末尾的异常类型必须保留"
    assert "already_running" in body


# ── 5. Windows 上 npm 是 npm.cmd:不许用裸 "npm" 起子进程 ────────────────


def test_no_production_path_spawns_bare_npm():
    """所有拉起 npm 的地方都必须先经 ``shutil.which`` 解析成绝对路径。

    根因:Windows 上 npm 实际是 ``npm.cmd``,而 CreateProcess **不套用 PATHEXT**
    —— 传裸 ``"npm"`` 必然 FileNotFoundError。真机上的两条后果:

    - Phase 6 因此报 ``DEGRADED — npm not found``,与同一次启动 Phase 0 的
      ``✓ npm`` 直接打架,给出完全错误的诊断(让用户去装明明装着的 Node.js);
    - Phase 0 那条 ``✓ npm`` **不带版本号**(Node.js 那条有),正是裸调用已经
      抛异常被 except 吞掉的指纹。

    唯一豁免:显式 ``shell=True`` 的调用(shell 会自己套 PATHEXT)。
    """
    offenders: list[str] = []
    for rel in ("main.py", "launch_desktop.py", "unified_launcher.py"):
        _scan_bare_npm(REPO / rel, offenders)
    for sub in ("core", "windows_service"):
        for path in sorted((REPO / sub).rglob("*.py")):
            _scan_bare_npm(path, offenders)
    assert not offenders, "以下位置仍用裸 npm 起子进程:\n" + "\n".join(offenders)


def _scan_bare_npm(path: Path, offenders: list[str]) -> None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for lineno, line in enumerate(lines, 1):
        # 只认"把 npm 当 argv 首元素"的写法(["npm", ...] / ['npm']);
        # shutil.which("npm") 这类解析调用正是我们想要的,不能误判。
        if not re.search(r"""\[\s*["']npm["']\s*[,\]]""", line) or line.strip().startswith("#"):
            continue
        # 取该调用前后若干行判断是否显式 shell=True
        window = "\n".join(lines[max(0, lineno - 4) : lineno + 4])
        if "shell=True" in window:
            continue
        offenders.append(f"{path.relative_to(REPO)}:{lineno}: {line.strip()[:90]}")


def test_orchestrator_phase6_launches_npm_by_resolved_path():
    src = (REPO / "core" / "system_orchestrator.py").read_text(encoding="utf-8")
    assert '[npm_path, "start"]' in src
    assert '["npm", "start"]' not in src


# ── 6. nats-server 安装:已装即复用、覆盖用 os.replace ──────────────────


def test_nats_install_reuses_existing_binary_and_replaces_atomically():
    """真机:exe 已在 ~/.lumiv/bin,每次启动仍白下 30s,末了 WinError 183。"""
    src = (REPO / "core" / "nats_server.py").read_text(encoding="utf-8")
    assert "复用" in src and "跳过下载" in src, "缺少'已安装即复用'的短路"
    assert "os.replace(extracted, nats_exe)" in src, "覆盖必须用 os.replace"
    assert "extracted.rename(nats_exe)" not in src, "Path.rename 在 Windows 上目标已存在必抛 WinError 183"


# ── 6. 就绪横幅指路与托盘实际条目一致 ─────────────────────────────────


def test_ready_banner_points_at_existing_tray_entries():
    # 检查对象搬家了：服务编排(含就绪横幅)已原样搬到 launcher/services.py，
    # unified_launcher.py 只剩 CLI 外壳。读源码的断言要跟着指向新家。
    launcher = (REPO / "launcher" / "services.py").read_text(encoding="utf-8")
    tray = (REPO / "windows_service" / "tray_icon.py").read_text(encoding="utf-8")

    banner_rows = [ln for ln in launcher.splitlines() if '("日志"' in ln or '("崩溃"' in ln]
    assert banner_rows, "就绪横幅应给出日志指路"
    joined = "\n".join(banner_rows)
    assert "三态动画日志" not in joined, "该托盘入口已在日志统一时移除,横幅不能再指向它"

    # 判据改成**通用**的了。
    #
    # 原先这里钉的是两个具体名字(「崩溃日志」「View Logs」必须同时出现在横幅与
    # 托盘源码里)。托盘菜单按所有者要求清空之后那两项不存在了,而这条断言只会说
    # 「找不到 View Logs」,说不出真正的毛病是**横幅在给一条走不通的路**。
    #
    # 现在查的是那件事本身:横幅里每一处「托盘 →「X」」,托盘里都得真有 X。
    # 这样托盘再增减菜单项时,这道门自己就跟得上,不必回来改名字。
    import re as _re

    pointed_at = _re.findall(r"托盘\s*→\s*「([^」]+)」", joined)
    missing = [
        name
        for name in pointed_at
        # 托盘源码里出现这个名字,才算这一项真的在
        if name.split("(")[0].strip() not in tray
    ]
    assert not missing, (
        f"就绪横幅让用户去托盘找这些项,但托盘里没有: {missing} —— " "指路指向一个不存在的入口,比不指路更糟"
    )

    # 反向自证:横幅得**真的给出**日志去处,否则上面那条在「什么都不指」时也绿。
    assert _re.search(r"logs|日志", joined), "横幅没有给出任何日志去处"
