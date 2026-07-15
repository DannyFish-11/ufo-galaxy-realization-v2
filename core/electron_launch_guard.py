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

import logging
import os

_LOCK_FILENAME = ".electron.pid"
_logger = logging.getLogger(__name__)


def _log(msg: str) -> None:
    """打印一条【必须对用户可见】的进度信息。

    Windows 自动装 MSVC / 注入链接器 PATH / 回退提示都是一次性的关键交互步骤,
    可能耗时数分钟。控制台常把 logger 级别设在 WARNING,单纯 logger.info 会被
    吞掉(真机复现:自动安装像个黑盒,用户啥也看不到)。故这里【始终 print】保证
    可见,同时照常写一份到日志文件。"""
    try:
        _logger.info(msg)
    except Exception:
        pass
    try:
        print(msg, flush=True)
    except Exception:
        pass


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
      link.exe not found" 崩溃。这里提前检出，并【默认自动用 winget 拉取最新版
      VS Build Tools 的 C++ 工作负载】装上（含 MSVC 链接器）；装成功则返回 None
      让构建继续，装失败/无 winget 才返回安装提示、回退 Electron。
      自动安装可用 GALAXY_TAURI_AUTO_INSTALL_MSVC=0 关掉。
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


def _prepend_path(d: str) -> None:
    """把目录 d 前插进本进程 PATH（去重），使随后 fork 的 cargo 子进程能继承到。"""
    if not d:
        return
    cur = os.environ.get("PATH", "")
    if d not in cur.split(os.pathsep):
        os.environ["PATH"] = d + os.pathsep + cur if cur else d


def _link_on_path_is_msvc(shutil) -> bool:
    """PATH 上是否有【确为 MSVC】的编译器/链接器。

    只认 cl.exe:它是 MSVC 独有的编译器名(GNU/其他工具链没有),在 PATH 上即可
    确定处于 MSVC 开发环境(如 x64 Native Tools 命令行)。
    【不】单凭 link.exe 判定 —— 真机踩过:PATH 上可能有非 MSVC 的 link.exe(某些
    工具链/GnuWin 也叫 link),它会让预检假阳性、放行构建、编译数分钟后才在链接
    阶段崩。link.exe 的真伪改由 _windows_msvc_linker_dir 在磁盘上核实。"""
    return bool(shutil.which("cl.exe"))


def _windows_msvc_linker_dir(subprocess):
    """返回一个【磁盘上真实存在 link.exe】的 MSVC 工具链 bin 目录;找不到返回 None。

    经 VS 官方定位器 vswhere.exe 找到装了 VC.Tools 组件的 VS/Build Tools 安装路径,
    再在其下 glob ``VC\\Tools\\MSVC\\<ver>\\bin\\Host<arch>\\<tgt>\\link.exe``。
    关键:仅"组件已注册"不算数(残缺/损坏安装会注册组件却没真正落地二进制,正是
    这次真机假阳性的根因)—— 必须磁盘上真有 link.exe 才认。返回其所在目录,供调用
    方注入 PATH 让 cargo/rustc 一定找得到。"""
    import glob as _glob

    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vswhere = os.path.join(program_files_x86, "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if not os.path.isfile(vswhere):
        return None
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
    except Exception:
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    install = out.stdout.strip().splitlines()[0].strip()
    pattern = os.path.join(install, "VC", "Tools", "MSVC", "*", "bin", "Host*", "*", "link.exe")
    hits = _glob.glob(pattern)
    if not hits:
        return None
    hits.sort()  # 版本号目录名字符串排序,末尾 ≈ 最新工具集
    return os.path.dirname(hits[-1])


def _windows_msvc_present(shutil, subprocess):
    """True 当 MSVC C++ 链接器【确实可用】——PATH 上有 cl.exe(必是 MSVC),或
    磁盘上 vswhere 定位到的 VS 安装里真有 link.exe 二进制。故意不轻信裸 link.exe
    或"组件已注册",避免放行后编译半天才在链接崩。"""
    return _link_on_path_is_msvc(shutil) or _windows_msvc_linker_dir(subprocess) is not None


def _windows_try_install_msvc(shutil, subprocess):
    """用 winget 自动安装【最新版】VS Build Tools 的 C++ 工作负载（含 MSVC 链接器）。

    需要 winget（Win10 1809+/Win11 自带），且通常需要管理员提权（可能弹 UAC）。
    刻意不捕获子进程输出 —— 让 winget/VS 引导器的下载进度直接透传到控制台，
    用户能看到实时进度。任何异常/失败都吞掉；是否真的装上由调用方用
    _windows_msvc_present() 复检为准。
    """
    winget = shutil.which("winget")
    if not winget:
        _log("无 winget，无法自动安装 MSVC 生成工具 → 回退 Electron。")
        return
    _log(
        "检测到缺 MSVC C++ 生成工具，正在用 winget 自动安装最新版 VS Build Tools 的 "
        "C++ 工作负载（首次下载数 GB、约需数分钟，可能弹出 UAC 提权）…"
    )
    # --override 会整体替换 VS 引导器参数，故需带全静默安装所需的全部开关。
    # 不指定具体版本 → winget 拉当前最新的 2022 BuildTools（自带适配当下的 MSVC 工具集）。
    cmd = [
        winget,
        "install",
        "--id",
        "Microsoft.VisualStudio.2022.BuildTools",
        "-e",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--override",
        "--quiet --wait --norestart --nocache " "--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended",
    ]
    try:
        rc = subprocess.run(cmd, timeout=3600).returncode
        _log(f"winget 安装 VS Build Tools 结束（退出码 {rc}）。")
    except Exception as e:  # noqa: BLE001 —— 自动安装尽力而为，失败即回退
        _log(f"自动安装 MSVC 生成工具失败（{e!r}）→ 回退 Electron。")


def _windows_msvc_hint(shutil, subprocess):
    """Windows：确保 Rust msvc target 所需的 MSVC C++ 链接器就位。

    就位（或成功自动装上）返回 None 让构建继续；否则返回一句可直接执行的安装
    提示，供上层打印后回退 Electron。默认会在缺失时先用 winget 自动拉取最新版
    VS Build Tools 装上，可用 GALAXY_TAURI_AUTO_INSTALL_MSVC=0 关掉。

    关键:当链接器已装在磁盘上但不在当前 PATH(最常见——用户从普通终端而非
    "x64 Native Tools" 命令行启动)时,把它的 bin 目录注入 PATH,让随后的 cargo
    子进程一定找得到 link.exe,而不是编译数分钟后才崩。
    """
    # cl.exe 已在 PATH(处于 MSVC 开发环境)→ 直接就位
    if _link_on_path_is_msvc(shutil):
        return None
    # 磁盘上有真实 MSVC 链接器但不在 PATH → 注入 PATH,构建即可继续
    bindir = _windows_msvc_linker_dir(subprocess)
    if bindir:
        _prepend_path(bindir)
        _log(f"检测到 MSVC 链接器于 {bindir}，已注入本次构建的 PATH → 继续构建 Tauri。")
        return None

    # 默认自动安装（用户要求：让它自己去装、直接拉最新适配版）
    if os.environ.get("GALAXY_TAURI_AUTO_INSTALL_MSVC", "1").strip().lower() not in ("0", "false", "no"):
        _windows_try_install_msvc(shutil, subprocess)
        if _link_on_path_is_msvc(shutil):
            _log("MSVC C++ 生成工具已就位 → 继续构建 Tauri。")
            return None
        bindir = _windows_msvc_linker_dir(subprocess)
        if bindir:
            _prepend_path(bindir)
            _log(f"MSVC 安装完成，链接器于 {bindir}，已注入 PATH → 继续构建 Tauri。")
            return None
        _log("自动安装后仍未探测到 MSVC 链接器 → 回退 Electron（详见下方手动安装提示）。")

    winget = (
        "  winget install --id Microsoft.VisualStudio.2022.BuildTools -e "
        "--accept-package-agreements --accept-source-agreements "
        '--override "--quiet --wait --norestart '
        '--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"'
    )
    return (
        "缺 MSVC C++ 生成工具（Rust 的 msvc target 需要 link.exe），且自动安装未成功，"
        "无法构建 Tauri。\n"
        "手动装 VS Build Tools 的 C++ 工作负载后重试（会自动回退 Electron）：\n"
        + winget
        + "\n或手动下载：https://visualstudio.microsoft.com/visual-cpp-build-tools/"
    )
