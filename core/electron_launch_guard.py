"""core/electron_launch_guard.py — 跨启动路径共享的桌面壳去重锁 + 网关端口解析

背景
----
桌面壳(Electron/Tauri)历史上有 4 条互相独立的启动路径:
  1. core/system_orchestrator.py 的 _run_phase_6_desktop_surface（Phase 6，
     在网关甚至还没开始监听端口前就已调用）
  2. unified_launcher.py 的 GalaxyUnified.start_electron() / start_tauri()
  3. unified_launcher.py 模块级 _start_electron_gui()（仅 `python
     unified_launcher.py` 独立运行路径）
  4. launch_desktop.py 的 start_electron_frontend()

只有第 3 条写 .electron.pid 锁,其余三条既不检查也不写入,导致:
- 单次启动可能触发 2~3 次独立的 Electron 子进程创建尝试(重复 npm install/
  npm start),互相不知情。
- 谁先抢到 Electron 自身的 requestSingleInstanceLock() 谁"活下来"——而最先
  发起的往往是不会注入 GALAXY_GATEWAY_PORT 的那几条路径。一旦用户用 --port
  覆盖了网关端口,"赢"下来的 Electron 实例仍然只会连默认 9000,面板/感知帧
  全部 fetch 到错误端口——而 electron/main.js 里这类失败是静默 catch+重试,
  用户看到的现象就是"面板打开了但一直是空数据",且没有任何可见报错。

这里提供所有启动路径都应调用的两个共享原语,替代各自为战的重复实现。
"""

from __future__ import annotations

import os

_LOCK_FILENAME = ".electron.pid"


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def lock_path() -> str:
    return os.path.join(_project_root(), _LOCK_FILENAME)


def resolve_gateway_port() -> int:
    """解析当前网关实际监听端口,供任何要拉起桌面壳的代码路径注入
    GALAXY_GATEWAY_PORT/PORT 环境变量。

    优先级:GALAXY_GATEWAY_PORT env → PORT env → core.port_config 里
    unified_launcher 的端口配置(自身也会先看 GALAXY_UNIFIED_LAUNCHER_PORT env,
    再看 config/unified_ports.yaml)→ 内置默认值 9000。
    """
    for key in ("GALAXY_GATEWAY_PORT", "PORT"):
        v = os.environ.get(key, "").strip()
        if v:
            try:
                return int(v)
            except ValueError:
                pass
    try:
        from core.port_config import get_service_port

        return get_service_port("unified_launcher")
    except Exception:
        return 9000


def already_running() -> bool:
    """检查是否已有另一条启动路径持有存活的桌面壳锁。

    调用方应在做任何"是否要启动"的判断(乃至 npm install 探测)之前先调用这个函数,
    是则直接跳过,避免重复起第二个 Electron/Tauri 子进程。
    死进程留下的陈旧锁会被自动清理。
    """
    path = lock_path()
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            existing_pid = int(f.read().strip())
        os.kill(existing_pid, 0)  # 存活则不抛异常;POSIX/Windows 均可用
        return True
    except (OSError, ValueError):
        try:
            os.remove(path)
        except OSError:
            pass
        return False


def write_lock(pid: int) -> None:
    """子进程成功拉起后写入其 pid,供其余启动路径的 already_running() 探测到。"""
    try:
        with open(lock_path(), "w", encoding="utf-8") as f:
            f.write(str(pid))
    except OSError:
        pass


def electron_package_intact(electron_dir: str) -> bool:
    """检查 electron npm 包是否【完整】——不只是 node_modules 目录存在。

    真机复现(用户重新克隆仓库后):node_modules/.bin/electron.cmd 存根在、
    但 node_modules/electron/cli.js 缺失(npm install 中断/不完整的典型残局)。
    之前所有启动路径都只判断 node_modules 目录是否存在——存在就跳过安装、
    直接拉起 electron.cmd,后者立刻以 "Cannot find module ...electron\\cli.js"
    崩掉;而保活重启逻辑每次重启走的还是同一个"目录存在→跳过安装"判断,
    于是 GPU 模式崩 3 次、软件渲染崩 5 次、最终彻底放弃——期间没有任何一次
    尝试过真正的修复动作(重跑 npm install)。

    这里检查 electron 包的两个关键文件都在,任何一个缺失都视为"需要修复安装"。
    """
    pkg = os.path.join(electron_dir, "node_modules", "electron")
    return os.path.isfile(os.path.join(pkg, "package.json")) and os.path.isfile(os.path.join(pkg, "cli.js"))


def tauri_build_prereqs_hint():
    """Tauri 自动构建的【系统级依赖】预检（Rust crate 依赖由 Cargo 自理，不在此列）。

    依赖齐全返回 None；缺依赖返回一句可直接执行的安装提示，供 launcher 打印后
    跳过构建、回退 Electron —— 避免在缺 WebView 开发库的机器上让 cargo build
    崩得莫名其妙。
    - Linux：Tauri/wry 编译需 webkit2gtk-4.1 / gtk+-3.0 / libsoup-3.0 /
      javascriptcoregtk-4.1 开发库（缺则 build 必失败）。
    - Windows：Rust 的 msvc target 需要 MSVC C++ 链接器（link.exe）。缺它时
      cargo 会先下载 ~280 个 crate（约 11 分钟）才在链接阶段以 "linker
      link.exe not found" 崩溃 —— 这里提前检出并给出 VS Build Tools 安装命令，
      让构建快速失败、干净回退 Electron。
    - macOS：Xcode CLT / WKWebView 随系统，返回 None（构建真失败时 launcher
      已有回退兜底）。
    """
    import shutil
    import subprocess
    import sys as _sys

    if _sys.platform.startswith("win"):
        return _windows_msvc_hint(shutil, subprocess)
    if not _sys.platform.startswith("linux"):
        return None
    apt = (
        "  sudo apt-get install -y libwebkit2gtk-4.1-dev libgtk-3-dev "
        "libsoup-3.0-dev libjavascriptcoregtk-4.1-dev build-essential pkg-config"
    )
    pkgconf = shutil.which("pkg-config")
    if pkgconf is None:
        return "缺 pkg-config 与 WebView 开发库，无法构建 Tauri。Debian/Ubuntu 装：\n" + apt
    missing = []
    for name in ("webkit2gtk-4.1", "gtk+-3.0", "libsoup-3.0", "javascriptcoregtk-4.1"):
        try:
            rc = subprocess.run([pkgconf, "--exists", name]).returncode
        except Exception:
            rc = 1
        if rc != 0:
            missing.append(name)
    if missing:
        return "缺 Tauri 构建所需系统库: " + ", ".join(missing) + "。Debian/Ubuntu 装：\n" + apt
    return None


def _windows_msvc_hint(shutil, subprocess):
    """Windows：检测 Rust msvc target 所需的 MSVC C++ 链接器是否就位。

    齐全返回 None；缺则返回一句可直接执行的安装提示。检测顺序：
      1. PATH 上已有 link.exe / cl.exe（多见于在 "x64 Native Tools" 命令行里
         启动，或 rustup 的 msvc target 已能链接）→ 视为就位。
      2. 否则用 VS 官方定位器 vswhere.exe 查是否已安装含 VC.Tools 组件的
         Visual Studio / Build Tools —— 装了但没进 PATH 时，cargo 通常仍能经由
         vcvars 自行找到链接器，故也视为就位。
      3. 两者皆无 → 判定缺 MSVC 生成工具，回退 Electron 并提示安装。
    """
    # 1) 链接器已在 PATH（native tools 环境或已配置）
    if shutil.which("link.exe") or shutil.which("cl.exe"):
        return None

    # 2) vswhere 探测已安装的 VC.Tools 组件（cargo 可经 vcvars 找到链接器）
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vswhere = os.path.join(program_files_x86, "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if os.path.isfile(vswhere):
        try:
            out = subprocess.run(
                [
                    vswhere,
                    "-latest",
                    "-products",
                    "*",
                    "-requires",
                    "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                    "-property",
                    "installationPath",
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if out.returncode == 0 and out.stdout.strip():
                return None
        except Exception:
            pass

    winget = (
        '  winget install --id Microsoft.VisualStudio.2022.BuildTools -e '
        '--override "--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"'
    )
    return (
        "缺 MSVC C++ 生成工具（Rust 的 msvc target 需要 link.exe），无法构建 Tauri。\n"
        "装 VS Build Tools 的 C++ 工作负载后重试（会自动回退 Electron）：\n"
        + winget
        + "\n或手动下载：https://visualstudio.microsoft.com/visual-cpp-build-tools/"
    )
