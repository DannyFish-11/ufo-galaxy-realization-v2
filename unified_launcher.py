#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy - 统一启动器 (Subordinate Launcher Component — PR-2)
===========================================================

**Subordinate Launcher Role — NOT a top-level startup authority**
------------------------------------------------------------------
This script is a **subordinate launcher component**.  It is invoked by
``main.py`` (the canonical system orchestrator) **after** the orchestrator's
staged pre-flight sequence (Phases 1–7) completes successfully.

``main.py`` runs the full 7-phase pre-flight first.  Once pre-flight reports
system readiness, ``main.py`` delegates to this file for the full async
service bring-up (background subsystems, runtime subject, desktop surface).

``main.py`` is the authoritative startup entrypoint.  Running
``python main.py`` is the official way to start Galaxy-Nexus.

This file must NOT be treated as a competing top-level startup contract.

Responsibilities (as a subordinate component)
---------------------------------------------
1. Full async bring-up of background services (NATS, Redis, L4 modules)
2. Launch of the core runtime (OpenClawd + DesktopPresenceRuntime)
3. Start of the unified API gateway (FastAPI / uvicorn)
4. Write ``runtime/entrypoint.json`` for client discovery
5. Graceful shutdown handling

Subject lifecycle authority
---------------------------
- :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime` — outer shell
- :class:`~core.openclawd.OpenClawd` — subject core

Internal structure
------------------
Launcher responsibilities are split across focused ``launcher/`` sub-modules:

- ``launcher.bootstrap``        — enums, SystemConfig, entrypoint writer, display helpers
- ``launcher.service_manager``  — ServiceInfo, ServiceManager
- ``launcher.core_services``    — CoreServiceLauncher
- ``launcher.node_startup``     — NodeSystemLauncher
- ``launcher.health_checks``    — run_startup_health_check
- ``launcher.shutdown``         — async_shutdown

This file retains the service orchestration surface:
- ``L4EnhancementLauncher``  — L4 module startup
- ``UnifiedWebUI``           — HTTP server assembly (FastAPI + uvicorn)
- ``GalaxyUnified``          — service bring-up coordinator (Phase 4–6 delegate)
- ``_run_check_only`` / ``main`` — CLI entry-points (for direct invocation)

作者：Galaxy Team
日期：2026-02-06
版本：2.1 (demoted to subordinate role — PR-2)
"""
# 生产修复(真 bug,文档字符串失位):win32 编码块与 dotenv 预载块曾被插到
# 模块文档字符串之前,使其不再是 module docstring(ast.get_docstring/__doc__
# 均为 None),PR-2 的"从属启动器"角色声明随之从模块元数据中消失。现将
# 文档字符串移回文件头部(可执行序言之前),恢复其 docstring 身份。
# PR-WIN-ENCODING: Inherit UTF-8 from main.py; defensive re-config if run standalone.
import sys


def _configure_windows_console() -> None:
    """Windows 控制台 UTF-8。正常路径由 main.py 先做好(同进程),这里只在本
    文件被单独当脚本运行时兜底 —— 见下方 ``__name__`` 守卫。

    以前这段是无条件模块级代码,于是 ``import unified_launcher`` 会重写调用方
    的 sys.stdout/sys.stderr 并改写进程环境变量。import 不该有这种越权副作用。
    """
    if sys.platform != "win32":
        return
    try:
        import io
        if hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
            )
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
            )
        import os
        os.environ["PYTHONIOENCODING"] = "utf-8:replace"
    except Exception:
        pass

# PR-DOTENV: 与上面的 UTF-8 设置同一模式——继承 main.py 已加载的 .env(正常路径
# 是 main.py 直接调用本文件的 GalaxyUnified,同进程共享 os.environ);若本文件被
# 单独运行(python unified_launcher.py，绕过 main.py)，这里防御性地自己再加载
# 一遍，确保任何 provider API Key 都能从 .env 正确进入 os.environ。
# 与 main.py 同一关键约束:只加载【非空】值——设置面板自动生成的 .env 会把全部
# schema 键写成 KEY=(空值),空字符串进入 os.environ 会把代码默认值顶掉(真机
# 复现:OLLAMA_URL="" 导致拿空 URL ping Ollama、明明在跑却判"未响应")。
# 不覆盖已存在的真实 shell/系统环境变量。
def _load_env_files_into_environ() -> None:
    """与 main.py::load_env_files_into_environ 同一套纪律的防御性加载。

    **只在本文件被当作脚本直接运行时调用**(见下方 ``__name__`` 守卫)。正常
    路径是 main.py 先加载好 .env 再 ``from unified_launcher import GalaxyUnified``
    (同进程共享 os.environ),此时这里什么都不用做。

    以前这段是无条件的模块级代码,于是"import 一下 unified_launcher"就把本机
    .env 灌满整个进程 —— 与 main.py 那处同一个坑:测试里任何一次 import 都会
    污染后续全部用例(MEMORY_DB_PATH 指向容器路径、各家 API_KEY 凭空出现),
    而 CI 上没有 .env 所以永远看不到,只砸本机开发者。上面那段注释写的本来就
    是"若本文件被单独运行,防御性地自己再加载一遍",代码只是没照着写。

    加载纪律三条(都是真机复现过的坑):只加载【非空】值(空字符串会顶掉代码
    默认值,真机症状:OLLAMA_URL="" → 拿空 URL ping Ollama、明明在跑却判
    "未响应");值以 # 开头视同未配置(dotenv 会把「空值+行内注释」整段当值);
    不覆盖已存在键(shell 显式导出最高,secrets.env 先于 .env 先到先得)。
    """
    try:
        import os as _os

        from dotenv import dotenv_values as _dotenv_values

        _root = _os.path.dirname(_os.path.abspath(__file__))
        for _env_file in ("runtime/secrets.env", ".env"):
            for _k, _v in (_dotenv_values(_os.path.join(_root, _env_file)) or {}).items():
                if _v and not _v.lstrip().startswith("#") and _k not in _os.environ:
                    _os.environ[_k] = _v
    except Exception:
        pass


# ── 单独运行时的进程级配置(正常路径由 main.py 完成,同进程共享) ──────────
if __name__ == "__main__":
    _configure_windows_console()
    _load_env_files_into_environ()

import argparse
import asyncio
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

from entrypoint_role_contract import (
    UNIFIED_LAUNCHER_ENTRY_ID,
    EntrypointRole,
    ensure_entrypoint_role,
)

# 设置项目根目录
PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))
try:
    from nodes.common.cors_config import get_cors_origins  # noqa: F401  (兼容旧 import)
except ImportError:
    logging.getLogger("Galaxy").warning(
        "nodes.common.cors_config 未找到，使用默认 CORS 来源。"
    )

    def get_cors_origins():  # type: ignore[misc]
        return ["http://localhost:3000", "http://localhost:8080"]

logging.basicConfig(
    level=logging.WARNING,  # console只显示警告/错误；INFO详情写 logs/lumiv.log
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%H:%M:%S'
)
# 修 logging 双写(与 main.py 同一处理,兜住 unified_launcher 被单独作为入口的
# 场景):huggingface_hub 自带一个裸 StreamHandler 且不关 propagate,同一条日志
# 会经"它自己的 handler + 根 logger 控制台 handler"打两遍;关掉冒泡即只打一遍。
logging.getLogger("huggingface_hub").propagate = False
logger = logging.getLogger("Galaxy")

# 静默 URL 哨兵(见 core/ollama_url_sentinel):只观测不干预,缺协议头请求 URL 一出现
# 就记精确调用栈;平时零输出、零行为影响,装不上也静默兜底。桌面壳走 unified_launcher
# 入口时同样武装,不依赖 main.py 是否被导入。
try:
    from core.ollama_url_sentinel import install as _install_url_sentinel
    _install_url_sentinel()
except Exception:  # noqa: BLE001
    pass


# ============================================================================
# 终端颜色和打印工具 — 从 core/ascii_art 导入规范实现
# ============================================================================

from core.ascii_art import print_banner, print_status_row

# 这几个名字并不属于服务编排，而是 launcher 包里更早就有的模块。老调用点习惯从
# unified_launcher 拿（因为它当初 re-export 了），并存期内继续透出去。
from launcher.bootstrap import (  # noqa: F401,E402
    ServiceType,
    SystemConfig,
    SystemState,
)
from launcher.core_services import CoreServiceLauncher  # noqa: F401,E402
from launcher.node_startup import NodeSystemLauncher  # noqa: F401,E402
from launcher.service_manager import ServiceManager  # noqa: F401,E402

# =============================================================================
# 服务编排已搬到 launcher/services.py —— 本文件只剩 CLI 外壳
# =============================================================================
#
# 统一启动器的目标是"所有启动器收敛到 main.py 一个入口,各自真实有效的要素保留、
# 本体删掉"。服务编排(GalaxyUnified 及其模块级助手,共 1954 行)已【原样搬迁】
# 到 launcher/services.py —— 是移动,不是重写:里面密布真机故障攒出来的判据
# (NATS 三态降级、主脑选择与拉取的时序、端口可绑定探测、URL 哨兵、弱网重试……),
# 手抄必丢。
#
# 本文件在步骤 8 与其余三个启动器本体一起删除。在那之前它保持可用,因为 main.py
# 与六个测试文件仍按老路径 import。
from launcher.services import (  # noqa: F401,E402  (re-export,供既有 import 继续可用)
    _CLOUD_LLM_KEY_ENV_VARS,
    _PORT_PROBE_HOST,
    GalaxyUnified,
    L4EnhancementLauncher,
    UnifiedWebUI,
    _get_lan_ip,
    _model_tag_root,
    _probe_port_bindable,
    _recheck_ai_brain_phase,
    _run_check_only,
    _short_culprit,
    _try_start_docker_daemon,
    _url_sentinel_audit,
    ai_brain_readiness,
    print_section,
    print_status,
)


def _start_electron_gui():
    """Launch Electron three-state GUI if available.

    PR-ELECTRON-DEDUP: shares the same .electron.pid lock (core.electron_launch_guard)
    as Phase 6 (system_orchestrator) and GalaxyUnified.start_electron() — whichever
    launch path runs first wins the lock, the rest skip launching a second instance.
    """
    import os
    import subprocess
    import sys

    from core.electron_launch_guard import already_running, resolve_gateway_port, write_lock

    if os.environ.get("GALAXY_SKIP_ELECTRON", "").lower() in ("1", "true", "yes"):
        return

    project_root = os.path.dirname(os.path.abspath(__file__))
    electron_dir = os.path.join(project_root, "electron")

    if not os.path.isdir(electron_dir):
        return
    if not os.path.isdir(os.path.join(electron_dir, "node_modules")):
        return
    # electron 包不完整(中断安装残局)时不要拉起——必然以 MODULE_NOT_FOUND 崩溃;
    # 交给 GalaxyUnified.start_electron() 的修复安装路径处理。
    from core.electron_launch_guard import electron_package_intact
    if not electron_package_intact(electron_dir):
        print("[Launcher] electron 依赖不完整(疑似 npm install 中断)，跳过此路径,由主启动路径修复")
        return

    if already_running():
        print("[Launcher] Electron already running (started by another launch path)")
        return

    # PR-ABSOLUTE-PATH: use shutil.which to find npm — works even when not in PATH
    import shutil
    npm_path = shutil.which("npm")
    if not npm_path:
        print("[Launcher] npm not found — skip Electron")
        return
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
        # 之前这里完全没有注入网关端口——若用户用 --port 覆盖了默认 9000,这条路径
        # "赢"下 Electron 单实例锁时,面板/感知帧会 fetch 到错误端口且静默失败。
        env["GALAXY_GATEWAY_PORT"] = str(resolve_gateway_port())
        env.setdefault("PORT", env["GALAXY_GATEWAY_PORT"])
        # Windows: use CREATE_NEW_PROCESS_GROUP for detached Electron
        popen_kwargs = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        proc = subprocess.Popen(
            [npm_path, "start"],
            cwd=electron_dir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **popen_kwargs,
        )
        write_lock(proc.pid)
        print("[Launcher] Electron GUI started (pid=%d)" % proc.pid)
    except Exception:
        pass


def main():
    """主函数"""
    print_banner()  # Galaxy ASCII banner at the top
    # PR-UVLOOP-WIN: uvloop is Linux/macOS only — skip on Windows to avoid startup delay
    if sys.platform != "win32":
        try:
            import uvloop  # Linux/macOS only；缺失或导入失败时静默跳过
            uvloop.install()
        except Exception:
            pass
    if not ensure_entrypoint_role(UNIFIED_LAUNCHER_ENTRY_ID, EntrypointRole.SUB_ENTRY):
        logger.error(
            "Entrypoint role contract violation: unified_launcher does not have SUB_ENTRY role."
        )
        return 1

    parser = argparse.ArgumentParser(
        description="Galaxy - L4 级自主性智能系统（统一融合版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
权威启动路径 (PR-2):
    python main.py                          # ← 官方入口（系统 Orchestrator）
    python unified_launcher.py              # 从属组件（直接调用，高级用途）

已删除的兼容性包装器（不可再使用）:
    start_lumiv.py                         # 已删除（post-PR-10 清理）
    start_l4.py                             # 已删除（post-PR-10 清理）

示例:
    python main.py                          # 默认启动（推荐）
    python unified_launcher.py              # 直接调用从属启动器（完整模式）
    python unified_launcher.py --minimal    # 最小启动
    python unified_launcher.py --no-l4      # 不启动 L4 模块
    python unified_launcher.py --status     # 查看状态
    python unified_launcher.py --docker-full # 通过 Docker Compose 启动全量节点（130 个）
        """
    )
    parser.add_argument("--minimal", "-m", action="store_true", help="最小启动模式")
    parser.add_argument("--no-ui", action="store_true", help="不启动 API 服务")
    parser.add_argument("--no-l4", action="store_true", help="不启动 L4 增强模块")
    parser.add_argument("--no-nodes", action="store_true", help="不启动节点系统")
    parser.add_argument("--status", action="store_true", help="查看系统状态")
    parser.add_argument("--check-only", action="store_true", help="仅检查依赖和配置，不启动服务")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址 (默认: 0.0.0.0)")
    parser.add_argument("--port", "-p", type=int, default=9000, help="API 服务端口")
    parser.add_argument(
        "--docker-full",
        action="store_true",
        help="通过 Docker Compose 启动完整节点集（130 个节点 + 基础设施），等效于: "
             "docker compose -f deploy/compose/full.yml --profile full up -d",
    )
    
    args = parser.parse_args()

    # ── --docker-full: 通过 Docker Compose 启动全量节点 ──────────────────
    if args.docker_full:
        print_banner()
        os.environ["GALAXY_BANNER_PRINTED"] = "1"
        print_section("Docker 全量节点启动 (--docker-full)")
        compose_file = PROJECT_ROOT / "deploy" / "compose" / "full.yml"
        if not compose_file.exists():
            print_status_row(
                "deploy/compose/full.yml",
                "文件不存在，请确认仓库完整",
                "error",
            )
            sys.exit(1)
        # 检测 docker/docker compose 是否可用
        _docker_available = False
        try:
            _result = subprocess.run(
                ["docker", "compose", "version"],
                capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            _docker_available = _result.returncode == 0
        except FileNotFoundError:
            pass
        if not _docker_available:
            print_status_row(
                "Docker",
                "未安装或未运行，请先安装 Docker Desktop / Docker Engine",
                "error",
            )
            print_status_row(
                "安装文档",
                "https://docs.docker.com/get-docker/",
                "info",
            )
            sys.exit(1)

        cmd = [
            "docker", "compose",
            "-f", str(compose_file),
            "--profile", "full",
            "up", "-d",
        ]
        print_status_row("命令", " ".join(cmd), "step")
        print_status_row("状态", "启动中，请稍候...", "loading")
        try:
            ret = subprocess.call(cmd)
        except KeyboardInterrupt:
            ret = 130
        if ret == 0:
            print_status_row("Docker 全量节点", "已在后台启动", "success")
            print_status_row("查看状态", "docker compose -f deploy/compose/full.yml --profile full ps", "info")
            print_status_row("停止服务", "docker compose -f deploy/compose/full.yml --profile full down", "info")
        else:
            print_status_row("Docker Compose", f"退出码 {ret}，请检查上方输出", "error")
            sys.exit(ret)
        return

    # 创建系统实例
    lumiv = GalaxyUnified()
    
    # 应用命令行参数
    lumiv.config.minimal_mode = args.minimal
    lumiv.config.enable_web_ui = not args.no_ui
    lumiv.config.enable_l4 = not args.no_l4
    lumiv.config.enable_nodes = not args.no_nodes
    lumiv.config.host = args.host
    lumiv.config.web_ui_port = args.port
    
    # 查看状态
    if args.status:
        lumiv.show_status()
        return

    # 仅检查依赖和配置
    if args.check_only:
        asyncio.run(_run_check_only(lumiv))
        return

    # ── 前置检查（Pre-flight checks）──────────────────────────────────────
    # 端口冲突检测：如果目标端口已被占用，提前告知用户并退出
    if lumiv.config.enable_web_ui:
        import socket as _socket
        _port = lumiv.config.web_ui_port
        _host = lumiv.config.host if lumiv.config.host != "0.0.0.0" else "127.0.0.1"
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as _s:
            _s.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
            try:
                _s.bind((_host, _port))
            except OSError:
                print_status(
                    f"端口 {_port} 已被占用！请先停止占用该端口的进程，"
                    f"或使用 --port 指定其他端口（如 --port 9001）。",
                    "error"
                )
                sys.exit(1)

    # 配置缺失检测：没有 LLM API Key 时给出明确提示
    if not lumiv.config.has_llm_api():
        env_file = PROJECT_ROOT / ".env"
        if not env_file.exists():
            print_status(
                ".env 文件不存在！请执行: cp .env.example .env "
                "并在 .env 中配置至少一个 LLM API Key（如 OPENAI_API_KEY）。",
                "warning"
            )
        else:
            print_status(
                "未检测到有效的 LLM API Key。"
                "请在 .env 中配置至少一个 Key（OPENAI_API_KEY、ANTHROPIC_API_KEY 等），"
                "否则聊天和 AI 功能将不可用。",
                "warning"
            )

    # 节点目录检测
    if lumiv.config.enable_nodes and not (PROJECT_ROOT / "nodes").exists():
        print_status("nodes/ 目录未找到，节点系统将被跳过。", "warning")
        lumiv.config.enable_nodes = False

    # ── 信号处理 ───────────────────────────────────────────────────────────
    # SECURITY: Use asyncio.add_signal_handler for async-safe signal handling.
    # signal.signal() is unsafe in async contexts because it can interrupt
    # the event loop at arbitrary points, causing coroutine state corruption.
    def _graceful_shutdown() -> None:
        lumiv.stop()

    # 启动 Electron GUI（在 Python 服务之后启动，作为独立桌面表层）
    _start_electron_gui()

    # 高性能事件循环(Windows: winloop / 其它: uvloop);须在 new_event_loop 之前
    # 装策略。内置子进程探针,失败自动还原默认(宁慢勿哑)。
    try:
        from core.fast_loop import install_fast_loop
        install_fast_loop()
    except Exception:  # noqa: BLE001
        pass

    # 启动系统 — register async signal handlers inside the running loop
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # loop.add_signal_handler 在 Windows(ProactorEventLoop)上 NotImplementedError;
        # 这个异常不被外层 except KeyboardInterrupt 捕获 → 启动器直接崩。
        # 回退到 signal.signal(Windows 上 SIGINT/SIGTERM 可用)。
        for _sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(_sig, _graceful_shutdown)
            except (NotImplementedError, RuntimeError):
                try:
                    signal.signal(_sig, lambda *_a: _graceful_shutdown())
                except (ValueError, OSError):
                    pass  # 非主线程等场景无法注册,忽略
        # 桌面覆盖层事件桥：订阅三态事件并推送到 Electron / WebSocket 客户端。
        # 必须在此入口路径显式启动，否则唤醒事件无法到达前端覆盖层与面板。
        try:
            from core.lumiv_websocket_bridge import GalaxyPresenceBridge
            loop.run_until_complete(GalaxyPresenceBridge.get_instance().start())
        except Exception as _bridge_exc:  # noqa: BLE001 — 非阻塞
            logger.warning("GalaxyPresenceBridge 启动失败（非阻塞）: %s", _bridge_exc)
        loop.run_until_complete(lumiv.start())
    except KeyboardInterrupt:
        lumiv.stop()
    finally:
        try:
            loop.remove_signal_handler(signal.SIGINT)
            loop.remove_signal_handler(signal.SIGTERM)
            loop.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main() or 0)
