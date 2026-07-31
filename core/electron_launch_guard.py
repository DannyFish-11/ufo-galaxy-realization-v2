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
import re

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
    except Exception as exc:  # noqa: BLE001
        # core.port_config 在本仓库内恒可导入,走到这里是真实读取错误(如
        # config/unified_ports.yaml 损坏)。仍退回内置默认值,但必须留痕:
        # 若网关实际监听的不是 9000,桌面壳会连到一个空端口,而此前毫无线索。
        _logger.warning(
            "网关端口解析失败(%s):退回内置默认值 9000;若网关实际不在 9000,桌面壳将连不上",
            exc,
        )
        return 9000


_STILL_ACTIVE = 259  # Windows GetExitCodeProcess:进程仍在运行时的返回码


def _pid_alive_windows(pid: int) -> bool:
    """Windows 上【只读】判断 pid 是否仍在运行。

    为什么不能用 ``os.kill(pid, 0)``(真机 16:12 那次启动的根因):
    CPython 在 Windows 上的 ``os.kill`` 并不是发信号——除 CTRL_C_EVENT/
    CTRL_BREAK_EVENT 外,它走的是 ``OpenProcess`` + **TerminateProcess(handle, sig)**。
    也就是说 ``os.kill(pid, 0)`` 会把目标进程**以退出码 0 直接杀掉**,而不是探活。
    这一个语义错误在所有者的 Windows 真机上同时炸出两种故障:

    1. pid 已失效 → ``OpenProcess`` 报 ``[WinError 87] 参数错误``,该错误在
       ``os.kill`` 里被包成 **SystemError**(<built-in function kill> returned a
       result with an exception set),而 SystemError 不是 OSError 的子类,
       原来的 ``except (OSError, ValueError)`` 接不住 → 异常一路上抛,
       Phase 6 桌面壳阶段整个崩掉 → "Startup validation failed" CRITICAL、
       系统降级启动。
    2. pid 仍有效 → 刚刚拉起的 Electron 被 TerminateProcess 当场杀掉,
       而函数还返回 True 说"它在跑"。

    正解:``OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`` 拿只读句柄,
    再用 ``GetExitCodeProcess`` 看是否 STILL_ACTIVE。这条路径不会碰进程状态,
    且能正确把"已退出但句柄尚未回收"的僵留 pid 判为**已死**——旧实现在这种
    情况下 OpenProcess 是成功的,于是把死壳误报成活壳(见保活器空转的根因)。

    已知边角:进程若恰好以退出码 259 结束,会与 STILL_ACTIVE 撞值而被判成活着。
    这是 Win32 API 本身的固有歧义;对桌面壳(Electron/npm)而言实际不会发生,
    且即便发生,后果也只是本轮少重启一次,不会像旧实现那样误杀进程。
    """
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # 必须显式声明签名:ctypes 默认按 C int 处理返回值,而 64 位 Windows 上
    # HANDLE 是 64 位——不声明会把句柄**截断**,后续 GetExitCodeProcess/
    # CloseHandle 拿到的是坏句柄(既查不到状态,也漏掉句柄)。
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _pid_alive(pid: int) -> bool:
    """跨平台【只读】探活:活着返回 True。任何不确定一律当作已死(宁可多起一次壳,
    也不要把死锁当活锁——后者会让保活重启彻底空转)。"""
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            return _pid_alive_windows(pid)
        os.kill(pid, 0)  # POSIX 分支:0 号信号确实是标准探活语义
        return True
    except Exception:  # noqa: BLE001
        # 一律吞掉,原因见下。这里绝不能只接 OSError:
        # - Windows: OpenProcess 的错误会被包成 SystemError(非 OSError);
        # - POSIX:  锁文件里若是个超大数字,os.kill 抛的是 **OverflowError**
        #           ("Python int too large to convert to C long")——同样不是
        #           OSError,同样会一路上抛把启动预检判死。
        # 探活失败一律按"已死"处理:大不了多起一次壳,总好过把死锁当活锁。
        return False


def already_running() -> bool:
    """检查是否已有另一条启动路径持有存活的桌面壳锁。

    调用方应在做任何"是否要启动"的判断(乃至 npm install 探测)之前先调用这个函数,
    是则直接跳过,避免重复起第二个 Electron/Tauri 子进程。
    死进程留下的陈旧锁会被自动清理。

    本函数【绝不抛异常】:它被 Phase 6 等启动关键路径直接调用,一旦上抛就会把
    整个启动预检判为失败(真机实证)。任何异常都按"没有存活的壳"处理。
    """
    path = lock_path()
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            existing_pid = int(f.read().strip())
    except (OSError, ValueError):
        clear_lock()
        return False
    if _pid_alive(existing_pid):
        return True
    clear_lock()
    return False


def clear_lock() -> None:
    """删除桌面壳锁。

    保活器在**观察到自己拉起的壳进程已退出**时必须调用它:否则陈旧锁会让
    ``start_tauri()`` 的 ``already_running()`` 早退分支返回 True,
    ``start_desktop_shell()` 随之短路,**根本不会再去拉 Electron**——真机上
    13 条"Electron 已退出,重启中"对应的 electron.log 里只有一个启动标记,
    GPU→软件渲染→basic 三级降级全程空转,就是这么来的。
    """
    try:
        os.remove(lock_path())
    except OSError:
        pass


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

    真机复现第二种残局("依赖残缺后补齐"仍崩溃循环的根因):js 文件都齐了,但
    postinstall 下载的 **运行时二进制**(node_modules/electron/dist/electron.exe,
    由 path.txt 指路)缺失——npm install 中断在下载阶段、或网络被断的典型残局。
    此时 electron.cmd 一启动就打印 "Electron failed to install correctly" 立即退出:
    表现正是"启动后立即退出"的闪退循环,且 GPU/软件渲染怎么切都一样崩(根本没
    走到渲染);更坑的是 electron 包目录已存在时,重跑 npm install 会【跳过
    postinstall】,永远补不回二进制。故完整性必须核到 path.txt 指向的真实二进制。
    """
    pkg = os.path.join(electron_dir, "node_modules", "electron")
    if not (os.path.isfile(os.path.join(pkg, "package.json")) and os.path.isfile(os.path.join(pkg, "cli.js"))):
        return False
    path_txt = os.path.join(pkg, "path.txt")
    if not os.path.isfile(path_txt):
        return False
    try:
        with open(path_txt, encoding="utf-8") as f:
            rel = f.read().strip()
        return bool(rel) and os.path.isfile(os.path.join(pkg, "dist", rel))
    except OSError:
        return False


#: npm 暂存目录的命名形态:``.<包名>-<随机后缀>``,例如
#: ``.decompress-response-HCi3ZryO``。npm 安装时先把包重命名到这种临时目录再落位。
_NPM_STAGING_RE = re.compile(r"^\.[^/\\]+-[A-Za-z0-9_]{6,}$")

#: npm 自己的点开头**正常**条目,绝不能删。
_NPM_KEEP_DOTTED = frozenset({".bin", ".cache", ".package-lock.json", ".modules.yaml", ".yarn-integrity"})


def purge_npm_staging_dirs(node_modules_dir: str) -> int:
    """清掉 npm 中断留下的暂存目录,返回删除个数。

    真机复现:上一次 ``npm install`` 被打断后,``node_modules`` 里会残留形如
    ``.decompress-response-HCi3ZryO`` 的暂存目录。下一次 install 想把同名包
    重命名到**同一个**暂存名时,目标已存在且非空,于是::

        npm error ENOTEMPTY: directory not empty, rename
        '.../node_modules/decompress-response' ->
        '.../node_modules/.decompress-response-HCi3ZryO'

    关键在于**重跑 npm install 修不好它** —— 每次都会撞上同一个残留目录、
    报同一个错。而启动器的"依赖不完整就自动修复安装"逻辑正是靠重跑 install,
    于是陷入"检测到不完整 → 重装 → ENOTEMPTY → 仍不完整"的死循环,
    桌面覆盖层永远起不来。必须先把残留清掉,install 才有可能成功。

    只删**匹配暂存命名形态**的目录,并显式保留 ``.bin`` 等 npm 正常条目 ——
    宁可漏删一个残留(下次再清),也不能误删 ``.bin`` 把整个安装弄坏。
    """
    import shutil as _shutil

    if not os.path.isdir(node_modules_dir):
        return 0

    removed = 0
    for name in os.listdir(node_modules_dir):
        if not name.startswith("."):
            continue
        if name in _NPM_KEEP_DOTTED:
            continue
        if not _NPM_STAGING_RE.match(name):
            continue
        target = os.path.join(node_modules_dir, name)
        if not os.path.isdir(target):
            continue
        try:
            _shutil.rmtree(target)
            removed += 1
            _log(f"已清理 npm 残留暂存目录: {name}")
        except OSError as exc:
            _log(f"清理 npm 残留暂存目录失败(跳过): {name} — {exc}")
    return removed


def is_npm_stale_dir_error(output: str) -> bool:
    """npm 的失败输出是否属于"残留目录挡路"这一类。

    命中时正确的动作是**清残留后重试**,而不是像网络类失败那样换镜像 ——
    换多少个镜像都绕不过本地文件系统里那个挡路的目录。
    """
    if not output:
        return False
    return any(k in output for k in ("ENOTEMPTY", "EEXIST", "directory not empty"))


def repair_electron_binary(electron_dir: str) -> bool:
    """electron 包 js 齐、但运行时二进制缺失时,直接跑包自带的 install.js 补下二进制。

    为什么不能靠 npm install:包目录已存在时 npm 会跳过 postinstall(见
    electron_package_intact 的说明),二进制永远补不回来。install.js 就是 electron
    的 postinstall 脚本,单独跑它即可只补二进制。先官方源,失败再换 npmmirror 镜像
    (国内网络最常见的下载失败因)。返回修复后的完整性检查结果。
    """
    import shutil
    import subprocess

    if electron_package_intact(electron_dir):
        return True
    node = shutil.which("node")
    pkg = os.path.join(electron_dir, "node_modules", "electron")
    install_js = os.path.join(pkg, "install.js")
    if not node or not os.path.isfile(install_js):
        return False
    for mirror in (None, "https://npmmirror.com/mirrors/electron/"):
        env = os.environ.copy()
        if mirror:
            env["ELECTRON_MIRROR"] = mirror
        _log(
            "检测到 Electron 运行时二进制缺失,正在补下载(node electron/install.js"
            + (", npmmirror 镜像" if mirror else "")
            + ",可能数分钟)…"
        )
        try:
            subprocess.run([node, install_js], cwd=pkg, env=env, timeout=900)
        except Exception:  # noqa: BLE001 —— 尽力而为,以复检结果为准
            pass
        if electron_package_intact(electron_dir):
            _log("Electron 二进制补下载成功 ✓")
            return True
    return False


def electron_binary_fix_hint(electron_dir: str = "electron") -> str:
    """自动修复失败时,给用户一条【可直接照抄执行】的修复指令(而不是让用户猜)。"""
    win = os.name == "nt"
    rm = r"rmdir /s /q node_modules\electron" if win else "rm -rf node_modules/electron"
    setm = (
        "set ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/&& "
        if win
        else "ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ "
    )
    return (
        "Electron 运行时二进制缺失/损坏(node_modules/electron/dist 未下载完整),自动修复未成功。\n"
        f"手动修复(任选其一,在 {electron_dir}/ 目录下执行):\n"
        "  1. node node_modules/electron/install.js\n"
        f"  2. 网络受限用镜像: {setm}node node_modules/electron/install.js\n"
        f"  3. 彻底重装该包: {rm} && npm install"
    )


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


def _windows_setup_msvc_build_env(subprocess) -> bool:
    """把【完整的 x64 MSVC 构建环境】(PATH + LIB + INCLUDE + LIBPATH 等)灌进
    os.environ,使随后 fork 的 cargo 子进程能真正链接成功。成功返回 True。

    为什么只注 PATH 不够(真机 LNK1181 根因):link.exe 找得到了,但 ``kernel32.lib``
    这类库属于 **Windows SDK**、不在 MSVC 的 bin 里;链接器靠 ``LIB`` 环境变量才能
    定位 SDK/CRT 的 lib 目录。只把 MSVC bin 塞进 PATH → link.exe 在、但 LIB/INCLUDE
    没设 → "LNK1181: cannot open input file 'kernel32.lib'"。而且按目录名 glob 还可能
    选到 Hostx86\\x86(32 位)的链接器,与 x86_64 target 不匹配。

    正解:经 vswhere 定位 VS 安装 → 运行官方 ``vcvars64.bat`` → 把它设置的整套开发
    环境 dump 回来应用到 os.environ(等价于在『x64 Native Tools 命令行』里构建)。
    先 ``chcp 65001`` 强制 UTF-8 输出,避免中文用户目录路径(如 C:\\Users\\李帅霖)
    被控制台代码页弄乱。
    """
    import shutil as _shutil

    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vswhere = os.path.join(program_files_x86, "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if not os.path.isfile(vswhere):
        return False
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
        return False
    if out.returncode != 0 or not out.stdout.strip():
        return False
    install = out.stdout.strip().splitlines()[0].strip()
    vcvars = os.path.join(install, "VC", "Auxiliary", "Build", "vcvars64.bat")
    if not os.path.isfile(vcvars):
        return False
    try:
        proc = subprocess.run(
            ["cmd", "/c", f'chcp 65001 >nul 2>&1 && call "{vcvars}" >nul 2>&1 && set'],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except Exception as exc:  # noqa: BLE001
        _log(f"加载 vcvars64 环境失败({exc!r})。")
        return False
    if proc.returncode != 0 or not proc.stdout:
        return False
    applied = 0
    for line in proc.stdout.splitlines():
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key:  # cmd 的 "=C:=..." / "=ExitCode=..." 之类伪变量,跳过
            continue
        os.environ[key] = val
        applied += 1
    if _shutil.which("cl.exe"):  # 复检:cl.exe 现应在 PATH → 环境确已就位
        _log(f"已加载 vcvars64 完整构建环境(应用 {applied} 项 env,含 PATH/LIB/INCLUDE)。")
        return True
    return False


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
    "x64 Native Tools" 命令行启动)时,加载完整的 vcvars64 构建环境
    (PATH+LIB+INCLUDE),让随后的 cargo 子进程能真正链接成功——只注 PATH 不够,
    会因缺 LIB 找不到 kernel32.lib(Windows SDK)而 LNK1181 崩。
    """
    # cl.exe 已在 PATH(处于 MSVC 开发环境)→ 直接就位
    if _link_on_path_is_msvc(shutil):
        return None
    # 磁盘上有真实 MSVC → 加载完整 vcvars64 构建环境后继续
    if _windows_msvc_linker_dir(subprocess) is not None:
        if _windows_setup_msvc_build_env(subprocess):
            _log("已加载完整 MSVC(vcvars64)构建环境 → 继续构建 Tauri。")
            return None
        return _vcvars_manual_hint()

    # 默认自动安装（用户要求：让它自己去装、直接拉最新适配版）
    if os.environ.get("GALAXY_TAURI_AUTO_INSTALL_MSVC", "1").strip().lower() not in ("0", "false", "no"):
        _windows_try_install_msvc(shutil, subprocess)
        if _link_on_path_is_msvc(shutil):
            _log("MSVC C++ 生成工具已就位 → 继续构建 Tauri。")
            return None
        if _windows_msvc_linker_dir(subprocess) is not None and _windows_setup_msvc_build_env(subprocess):
            _log("MSVC 安装完成,已加载 vcvars64 构建环境 → 继续构建 Tauri。")
            return None
        _log("自动安装后仍未就位 → 回退 Electron（详见下方手动安装提示）。")

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


def _vcvars_manual_hint() -> str:
    """检测到 MSVC 链接器、但无法自动加载完整 vcvars 环境时的提示(回退 Electron)。"""
    return (
        "检测到 MSVC 链接器,但无法自动加载完整构建环境(vcvars64)——直接构建会因缺 LIB/"
        "INCLUDE 而链接崩(LNK1181: kernel32.lib)。请从开始菜单的\n"
        "『x64 Native Tools Command Prompt for VS 2022』里手动构建一次:\n"
        "  cd desktop-tauri/src-tauri && cargo build --release\n"
        "构建成功后,之后每次启动都会自动优先用 Tauri;本次回退 Electron。"
    )
