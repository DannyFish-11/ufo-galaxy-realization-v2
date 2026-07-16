#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# PR-WIN-ENCODING: Inherit UTF-8 from main.py; defensive re-config if run standalone.
import sys
if sys.platform == "win32":
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
try:
    from dotenv import dotenv_values as _dotenv_values
    import os as _os
    for _k, _v in (_dotenv_values(
        _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".env")
    ) or {}).items():
        # 值以 # 开头 = dotenv 把「空值+行内注释」整段当值(毒值),视同未配置
        if _v and not _v.lstrip().startswith("#") and _k not in _os.environ:
            _os.environ[_k] = _v
except Exception:
    pass
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

__all__ = [
    "GalaxyUnified",
    "L4EnhancementLauncher",
    "UnifiedWebUI",
    "print_status",
    "main",
]

import os
import sys
import signal
import socket
import asyncio
import logging
import argparse
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime

from entrypoint_role_contract import (
    EntrypointRole,
    UNIFIED_LAUNCHER_ENTRY_ID,
    ensure_entrypoint_role,
)

# 设置项目根目录
PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))
try:
    from nodes.common.cors_config import get_cors_origins, get_cors_methods, get_cors_headers
except ImportError:
    logging.getLogger("Galaxy").warning(
        "nodes.common.cors_config 未找到，使用默认 CORS 来源。"
    )

    def get_cors_origins():  # type: ignore[misc]
        return ["http://localhost:3000", "http://localhost:8080"]

# SECURITY: Only configure logging if no root handlers exist yet.
# Prevents overwriting main.py's logging configuration when this module is imported.
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.WARNING,  # console只显示警告/错误；INFO详情写 logs/lumiv.log
        format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
        datefmt='%H:%M:%S'
    )
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

from core.ascii_art import (
    Colors,
    print_banner,
    print_powershell_hint,
    print_section_header,
    print_status_row,
)


def _color_supported() -> bool:
    """Check if terminal supports color output.

    Respects NO_COLOR environment variable (https://no-color.org/) and
    checks if stdout is a TTY.
    """
    if os.environ.get("NO_COLOR", "").strip():
        return False
    if not sys.stdout.isatty():
        return False
    return True


def _safe_color(color_code: str) -> str:
    """Return color code only if terminal supports colors."""
    return color_code if _color_supported() else ""


def print_status(message: str, status: str = "info"):
    """打印状态信息（单行，无值列）。"""
    print_status_row(message, status=status)


def _url_sentinel_audit() -> Tuple[str, str, str, List[Dict[str, str]]]:
    """收集克隆界面「启动自检」要展示的取证数据(全 best-effort,绝不抛)。

    返回 (代码版本, OLLAMA_URL 环境值 repr, 解析后地址, 哨兵抓到的记录列表)。
    真机排查两大痛点直接摆上界面:1) 镜像新旧一眼可辨(代码版本);2) URL 哨兵
    抓到的缺协议头请求不再只进日志——用户在克隆界面就能看到 URL + 罪魁 file:line。
    """
    version = "unknown"
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%h %cd", "--date=format:%Y-%m-%d %H:%M"],
            capture_output=True, text=True, timeout=3,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        if r.returncode == 0 and r.stdout.strip():
            version = r.stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    env_repr = repr(os.environ.get("OLLAMA_URL"))
    try:
        from core.ollama_endpoint import resolve_ollama_base_url
        resolved = resolve_ollama_base_url()
    except Exception:  # noqa: BLE001
        resolved = "?"
    catches: List[Dict[str, str]] = []
    try:
        from core.ollama_url_sentinel import recent_catches
        catches = recent_catches()
    except Exception:  # noqa: BLE001
        pass
    return version, env_repr, resolved, catches


def _short_culprit(culprit: str) -> str:
    """把罪魁帧 `File "D:\\...\x.py", line N, in fn` 压成 `x.py:N in fn`(界面可读)。"""
    try:
        import re
        m = re.search(r'File "([^"]+)", line (\d+)(?:, in (\S+))?', culprit or "")
        if m:
            # 兼容两种路径分隔符:日志可能来自 Windows(D:\x\y.py)也可能来自 POSIX
            name = re.split(r"[\/]", m.group(1))[-1]
            fn = f" in {m.group(3)}" if m.group(3) else ""
            return f"{name}:{m.group(2)}{fn}"
    except Exception:  # noqa: BLE001
        pass
    return (culprit or "")[:60]


async def _ensure_recommended_model():
    """Ensure at least one recommended model is available (PR-I3)"""
    try:
        from core.huggingface_model_manager import get_hf_model_manager
        hf = get_hf_model_manager()

        local_models = hf.list_local_models()
        if not local_models:
            logger.info("No local models found, downloading recommended model...")
            try:
                await hf.install_recommended("llm_gemma4_e4b")
                logger.info("Recommended model downloaded successfully")
            except Exception as exc:
                logger.warning("Failed to auto-download model: %s", exc)
                logger.info(
                    "Please manually download a model: "
                    "python -c \"from core.huggingface_model_manager import get_hf_model_manager; "
                    "import asyncio; hf=get_hf_model_manager(); "
                    "asyncio.run(hf.install_recommended('llm_gemma4_e4b'))\""
                )
                raise  # 重新抛出，让上层决定是否继续
    except Exception:
        logger.debug("Model auto-download skipped (non-fatal)", exc_info=True)


def print_section(title: str):
    """打印章节标题。"""
    print_section_header(title)


def _try_start_docker_daemon(docker_path: str) -> None:
    """尽力拉起 Docker 守护进程（已安装但未运行时）。永不抛出。

    - Windows: 启动 Docker Desktop.exe（常见安装路径）。
    - macOS:   open -a Docker。
    - Linux:   尝试 systemctl start docker（无 sudo；rootless/已授权时生效）。
    安装 Docker 本身需要管理员权限/重启，无法可靠地静默完成，因此不在此处尝试安装。
    """
    import subprocess as sp
    try:
        if sys.platform == "win32":
            candidates = [
                os.path.join(os.environ.get("ProgramFiles", r"C:\\Program Files"),
                             "Docker", "Docker", "Docker Desktop.exe"),
                os.path.join(os.environ.get("ProgramW6432", r"C:\\Program Files"),
                             "Docker", "Docker", "Docker Desktop.exe"),
            ]
            for exe in candidates:
                if os.path.isfile(exe):
                    sp.Popen([exe], stdout=sp.DEVNULL, stderr=sp.DEVNULL,
                             creationflags=getattr(sp, "CREATE_NO_WINDOW", 0))
                    return
        elif sys.platform == "darwin":
            sp.Popen(["open", "-a", "Docker"], stdout=sp.DEVNULL, stderr=sp.DEVNULL)
            return
        else:
            sp.run(["systemctl", "start", "docker"], stdout=sp.DEVNULL, stderr=sp.DEVNULL, timeout=15)
            return
    except Exception:
        pass


# 引入重构后的子模块
from launcher.bootstrap import SystemConfig, SystemState, print_status as _bs_print_status
from launcher.service_manager import ServiceManager, ServiceInfo
from launcher.core_services import CoreServiceLauncher
from launcher.node_startup import NodeSystemLauncher
from launcher.health_checks import run_startup_health_check
from launcher.shutdown import async_shutdown

# SystemState 兼容别名
if not hasattr(SystemState, "SETUP"):
    SystemState.SETUP = SystemState.LOADING_CONFIG


# ============================================================================
# L4 增强模块启动器
# ============================================================================

class L4EnhancementLauncher:
    """L4 增强模块启动器 —— 按需加载，失败不阻断主流程"""

    def __init__(self, service_manager: ServiceManager, config: SystemConfig):
        self.service_manager = service_manager
        self.config = config
        self.modules: Dict[str, Any] = {}

    async def start_all(self) -> Dict[str, Any]:
        """启动所有已启用的 L4 模块"""
        results = {"modules": {}}

        # 认知进化 (PR-25/26/27)
        if self.config.enable_cognitive_evolution:
            try:
                from core.cognitive.evolution_system import initialize_cognitive_evolution
                initialize_cognitive_evolution()
                results["modules"]["cognitive_evolution"] = True
                logger.info("认知进化系统已启动")
            except Exception as exc:
                results["modules"]["cognitive_evolution"] = False
                logger.warning("认知进化系统启动失败(非致命): %s", exc)

        # 数字孪生引擎
        if self.config.enable_digital_twin:
            try:
                from core.digital_twin_engine import DigitalTwinEngine
                self.modules["digital_twin"] = DigitalTwinEngine()
                await self.modules["digital_twin"].initialize()
                results["modules"]["digital_twin"] = True
                logger.info("数字孪生引擎已启动")
            except Exception as exc:
                results["modules"]["digital_twin"] = False
                logger.warning("数字孪生引擎启动失败(非致命): %s", exc)

        # 健康集成 (Mediapipe)
        if self.config.enable_health:
            try:
                from core.health_integration import HealthAnalyzer
                self.modules["health"] = HealthAnalyzer()
                results["modules"]["health"] = True
                logger.info("健康分析模块已启动")
            except Exception as exc:
                results["modules"]["health"] = False
                logger.warning("健康分析模块启动失败(非致命): %s", exc)

        return results


# ============================================================================
# Web UI / API 网关 —— PR-22: 统一网关设计
# ============================================================================

class UnifiedWebUI:
    """统一 Web UI 网关 (FastAPI + Uvicorn)

    遵循 PR-22 统一网关设计:
    - 只读状态面板  → / (或 /static)
    - 管理 API      → /api/v1/*
    - WebSocket     → /ws
    - 无 /webui 子路径;前端用相对路径
    """

    def __init__(self, config: SystemConfig):
        self.config = config
        self.app: Optional[Any] = None
        self.server: Optional[Any] = None

    def _create_fastapi_app(self):
        """创建 FastAPI 应用"""
        from fastapi import FastAPI, Request
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import JSONResponse, FileResponse
        from fastapi.staticfiles import StaticFiles

        app = FastAPI(
            title="Galaxy API",
            description="Galaxy-Nexus L4 Autonomous System API",
            version="2.1.0",
        )

        # CORS: 安全约束——开发放宽、生产收紧
        origins = get_cors_origins()
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # 静态文件 (只读状态面板)
        static_dir = PROJECT_ROOT / "static"
        if static_dir.exists():
            app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

            @app.get("/")
            async def index():
                index_file = static_dir / "index.html"
                if index_file.exists():
                    return FileResponse(str(index_file))
                return JSONResponse({"status": "ok", "message": "Galaxy API Gateway"})
        else:
            @app.get("/")
            async def root():
                return JSONResponse({"status": "ok", "message": "Galaxy API Gateway"})

        # API 路由
        try:
            from core.api_routes import create_api_routes
            app.include_router(create_api_routes(), prefix="/api/v1")
        except Exception as exc:
            logger.warning("API 路由加载失败(非致命): %s", exc)

        return app

    async def start(self):
        """启动 Web 服务器"""
        import uvicorn
        self.app = self._create_fastapi_app()

        config = uvicorn.Config(
            self.app,
            host=self.config.host,
            port=self.config.web_ui_port,
            log_level="warning",
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        await self.server.serve()

    async def stop(self):
        """停止 Web 服务器"""
        if self.server:
            self.server.should_exit = True


# ============================================================================
# GalaxyUnified — 统一启动协调器 (PR-2 从属角色)
# ============================================================================

class GalaxyUnified:
    """Galaxy 统一启动协调器 —— PR-2 从属组件

    职责范围 (作为从属组件):
    1. 加载配置
    2. 启动后台服务 (NATS, Redis, L4 modules)
    3. 启动核心运行时 (OpenClawd + DesktopPresenceRuntime)
    4. 启动 API 网关 (FastAPI)
    5. 写出 entrypoint.json
    6. 优雅关闭

    此实例**不**执行预检 (Phases 1-7);预检由调用方 ``main.py`` 负责。
    """

    NPM_INSTALL_TIMEOUT = 300  # npm install 超时秒数
    MAX_GPU_CRASHES = 3  # GPU 模式连续崩溃阈值 → 自动切软件渲染
    MAX_SW_CRASHES = 2  # 软件渲染连续崩溃阈值 → 放弃

    def __init__(self):
        self.config = SystemConfig()
        self.service_manager = ServiceManager(self.config)
        self.web_ui = UnifiedWebUI(self.config)
        self.running = False
        self.electron_proc = None
        self._cached_electron_proc = None
        self._electron_log_handle = None
        self._electron_force_software = False
        self._desktop_shell = "electron"
        self._tray = None
        self._voice_loop = None
        self._voice_input_disabled_reason = None
        self._brain = None

    def _build_electron_cmd(self, electron_dir: Path, npm: str) -> list:
        """构建启动 Electron 的命令列表。"""
        if os.name == "nt":
            # Windows: 走 node_modules/.bin/electron.cmd（PR-ABSOLUTE-PATH）
            electron_bin = electron_dir / "node_modules" / ".bin" / "electron.cmd"
            if not electron_bin.exists():
                electron_bin = electron_dir / "node_modules" / ".bin" / "electron"
            main_js = (electron_dir / "main.js").resolve()
            return [str(electron_bin.resolve()), str(main_js)]
        return [npm, "start"]

    def _close_old_electron_log(self) -> None:
        """关闭旧的 electron 日志句柄，防止文件句柄泄漏。"""
        if hasattr(self, '_electron_log_handle') and self._electron_log_handle:
            try:
                self._electron_log_handle.close()
            except Exception:
                pass
            self._electron_log_handle = None

    @staticmethod
    def _rotate_electron_log(log_path: Path, max_bytes: int = 2 * 1024 * 1024) -> None:
        """Electron 日志超限(默认 2MB)时轮转：electron.log → electron.log.1。"""
        try:
            if log_path.exists() and log_path.stat().st_size > max_bytes:
                bak = log_path.with_suffix(".log.1")
                if bak.exists():
                    bak.unlink()
                log_path.rename(bak)
        except OSError:
            pass

    def _setup_electron_env(self, npm: str) -> dict[str, str]:
        """Prepare environment variables for Electron subprocess."""
        env = os.environ.copy()
        env["PATH"] = str(Path(npm).parent) + os.pathsep + env.get("PATH", "")
        # 显式把【真实的网关端口】告诉 Electron，避免它只能猜默认 9000
        env["GALAXY_GATEWAY_PORT"] = str(self.config.web_ui_port)
        env.setdefault("PORT", str(self.config.web_ui_port))
        # GPU 自适应:软件渲染兜底
        if getattr(self, "_electron_force_software", False):
            env["GALAXY_ELECTRON_GPU"] = "0"
        return env

    async def _install_electron_deps(self, electron_dir: Path, npm: str) -> bool:
        """Ensure Electron npm dependencies are installed and intact.

        Returns True if deps are ready, False on failure.
        """
        import subprocess as sp
        from core.electron_launch_guard import electron_package_intact

        try:
            _pkg_intact = electron_package_intact(str(electron_dir))
        except Exception:
            logger.warning("electron_package_intact 检查失败，假设依赖不完整")
            _pkg_intact = False

        if (electron_dir / "node_modules").exists() and _pkg_intact:
            return True

        _reason = ("首次启动：安装 Electron 桌面层依赖"
                   if not (electron_dir / "node_modules").exists()
                   else "检测到 Electron 依赖不完整(疑似上次 npm install 中断)，正在修复安装")
        print_status_row(f"{_reason} (npm install，可能数分钟)…", status="success")

        try:
            _r = sp.run([npm, "install"], cwd=str(electron_dir),
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        timeout=self.NPM_INSTALL_TIMEOUT)
            if _r.returncode != 0:
                # 网络类失败 → 自动用 npmmirror 镜像重试一次
                _err_txt = (_r.stderr or _r.stdout or "")
                _network_fail = any(k in _err_txt for k in (
                    "ETIMEDOUT", "ECONNRESET", "ECONNREFUSED", "EAI_AGAIN",
                    "network", "socket", "TLS", "fetch failed",
                ))
                if _network_fail:
                    logger.warning(
                        "npm install 官方源失败(疑似网络问题),改用 npmmirror 镜像重试…")
                    print_status_row("npm 官方源不可达，改用国内镜像重试…", status="success")
                    _r = sp.run(
                        [npm, "install", "--registry=https://registry.npmmirror.com"],
                        cwd=str(electron_dir), capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=self.NPM_INSTALL_TIMEOUT,
                    )
            if _r.returncode != 0:
                logger.error(
                    "Electron npm install 失败 (rc=%s):\n%s",
                    _r.returncode, (_r.stderr or _r.stdout or "")[-1000:],
                )
                return False
            if not electron_package_intact(str(electron_dir)):
                logger.error(
                    "npm install 完成但 electron 包仍不完整(node_modules/electron/"
                    "cli.js 缺失)。请手动执行: cd electron && rmdir /s /q node_modules "
                    "&& npm install"
                )
                return False
            return True
        except Exception as exc:
            logger.error("Electron npm install 异常: %s", exc)
            return False

    async def start_electron(self) -> bool:
        """启动 Electron 桌面三态覆盖层。"""
        import shutil
        import subprocess as sp
        from core.electron_launch_guard import already_running, write_lock

        # PR-ELECTRON-DEDUP: 与 Phase 6(system_orchestrator)/launch_desktop.py 共享
        # 同一把 .electron.pid 锁——避免那两条路径已经成功拉起桌面壳后,这里又重复
        # 起一个(此前 4 条启动路径里只有一条会写这把锁,其余 3 条互不知情)。
        if already_running():
            logger.info("Electron GUI already running (started by another launch path)")
            return True

        electron_dir = Path("electron")
        if not electron_dir.exists():
            logger.warning("electron/ directory not found")
            return False

        # PR-NPM-FIX: npm must be resolved BEFORE the if block so it's always available
        npm = shutil.which("npm")
        if not npm:
            logger.warning("npm not found in PATH")
            return False

        # Ensure npm deps and package integrity
        if not await self._install_electron_deps(electron_dir, npm):
            return False

        # Start Electron — PR-ABSOLUTE-PATH: use absolute paths on Windows
        try:
            env = self._setup_electron_env(npm)
            cmd = self._build_electron_cmd(electron_dir, npm)

            # Capture Electron stdout/stderr to logs/electron.log so crashes are
            # diagnosable (previously DEVNULL-swallowed → impossible to debug the
            # "exited, restarting" loop / why Ctrl+Space overlay never appears).
            _log_dir = Path("logs")
            _log_dir.mkdir(exist_ok=True)
            self._close_old_electron_log()
            _elog_path = _log_dir / "electron.log"
            self._rotate_electron_log(_elog_path)
            _elog = open(_elog_path, "ab")
            self._electron_log_handle = _elog
            _elog.write(
                f"\n===== electron start {__import__('datetime').datetime.now().isoformat()} "
                f"cmd={cmd} =====\n".encode("utf-8", "replace")
            )
            _elog.flush()
            self.electron_proc = sp.Popen(
                cmd,
                cwd=str(electron_dir.resolve()),
                stdout=_elog, stderr=sp.STDOUT,
                env=env,
            )
            write_lock(self.electron_proc.pid)
            return True
        except Exception as exc:
            logger.error(f"Electron start failed: {exc}")
            return False

    async def start_tauri(self) -> bool:
        """优先启动 Tauri 桌面壳（系统 WebView，不背 Chromium，常驻内存/启动/体积都远小于 Electron）。

        仅当 desktop-tauri 已构建出二进制时启用；未构建则返回 False，由 start_desktop_shell
        回退到 Electron。首启不强行 cargo build（无工具链/编译太慢），交给用户显式构建一次：
        ``cd desktop-tauri/src-tauri && cargo build --release``。env 与 Electron 完全一致。
        """
        import shutil  # noqa: F401  (对齐 start_electron 的导入风格，未来可能用到)
        import subprocess as sp
        from core.electron_launch_guard import already_running, write_lock
        if os.environ.get("GALAXY_DESKTOP_SHELL", "").strip().lower() == "electron":
            return False  # 显式强制 Electron
        if already_running():
            logger.info("桌面壳已由其他启动路径拉起，跳过 Tauri 启动")
            return True
        tdir = Path("desktop-tauri")
        if not tdir.exists():
            return False
        exe = "galaxy-overlay.exe" if os.name == "nt" else "galaxy-overlay"
        candidates = [
            tdir / "src-tauri" / "target" / "release" / exe,
            tdir / "src-tauri" / "target" / "debug" / exe,
        ]
        binp = next((c for c in candidates if c.exists()), None)
        if not binp:
            # A 档：首启自动构建 Tauri 壳。仅当有 cargo 工具链时尝试；GALAXY_TAURI_AUTOBUILD=0 可关。
            import shutil as _shutil
            _optout = os.environ.get("GALAXY_TAURI_AUTOBUILD", "").strip().lower() in (
                "0", "false", "no", "off",
            )
            if _optout:
                logger.info("GALAXY_TAURI_AUTOBUILD=0：跳过 Tauri 自动构建，回退 Electron。")
            elif _shutil.which("cargo") is None:
                logger.info(
                    "未检测到 Rust(cargo)，跳过 Tauri 自动构建 → 回退 Electron。"
                    "装 Rust(https://rustup.rs) 后重启即自动构建并优先用 Tauri。"
                )
            else:
                # 构建前预检系统级依赖（Linux 的 webkit2gtk 等）——缺则给出 apt 命令并跳过，
                # 避免 cargo build 崩得莫名其妙；Rust crate 依赖由 Cargo 自理。
                try:
                    from core.electron_launch_guard import tauri_build_prereqs_hint
                    _hint = tauri_build_prereqs_hint()
                except Exception:
                    _hint = None
                if _hint:
                    logger.info("Tauri 构建系统依赖缺失，跳过自动构建 → 回退 Electron：\n%s", _hint)
                else:
                    logger.info("首次启动：自动构建 Tauri 桌面壳(cargo build --release，首次约需数分钟)，请稍候…")
                    try:
                        _cargo_log = _log_dir / "tauri-build.log"
                        with open(_cargo_log, "w", encoding="utf-8") as _clf:
                            _rc = sp.call(
                                ["cargo", "build", "--release"],
                                cwd=str(tdir / "src-tauri"),
                                stdout=_clf, stderr=sp.STDOUT,
                            )
                        if _rc != 0:
                            logger.warning("Tauri 构建失败，日志见 %s", _cargo_log)
                    except Exception as _bexc:  # noqa: BLE001
                        _rc = -1
                        logger.warning("Tauri 自动构建启动失败：%s", _bexc)
                    if _rc == 0:
                        binp = next((c for c in candidates if c.exists()), None)
                        if binp:
                            logger.info("Tauri 壳构建完成 ✓ 之后每次启动将自动优先用它。")
                    else:
                        logger.warning("Tauri 自动构建失败(cargo rc=%s)，本次回退 Electron。", _rc)
        if not binp:
            logger.info(
                "Tauri 壳不可用 → 回退 Electron。"
                "可手动构建一次：cd desktop-tauri/src-tauri && cargo build --release"
            )
            return False
        try:
            env = os.environ.copy()
            # 与 start_electron 注入同一组 env：端口/IPC/GPU 自适应一致，托盘与 bridge 无需改动。
            env["GALAXY_GATEWAY_PORT"] = str(self.config.web_ui_port)
            env.setdefault("PORT", str(self.config.web_ui_port))
            env.setdefault("GALAXY_IPC_PORT", "9231")
            if getattr(self, "_electron_force_software", False):
                env["GALAXY_ELECTRON_GPU"] = "0"
            _log_dir = Path("logs")
            _log_dir.mkdir(exist_ok=True)
            # 关闭旧的日志句柄，防止文件句柄泄漏
            if hasattr(self, '_electron_log_handle') and self._electron_log_handle:
                try:
                    self._electron_log_handle.close()
                except Exception:
                    pass
            # 复用同一份 logs/electron.log（托盘「三态动画日志」就打开它），便于一处看壳层日志。
            _tlog = open(_log_dir / "electron.log", "ab")
            self._electron_log_handle = _tlog
            _tlog.write(
                f"\n===== tauri start {__import__('datetime').datetime.now().isoformat()} "
                f"bin={binp} =====\n".encode("utf-8", "replace")
            )
            _tlog.flush()
            # proc 仍存进 self.electron_proc，让既有的 watch_processes 保活逻辑直接复用。
            self.electron_proc = sp.Popen(
                [str(binp.resolve())],
                cwd=str(tdir.resolve()),
                stdout=_tlog, stderr=sp.STDOUT,
                env=env,
            )
            write_lock(self.electron_proc.pid)
            self._desktop_shell = "tauri"
            return True
        except Exception as exc:
            logger.error("Tauri 壳启动失败，回退 Electron: %s", exc)
            return False

    async def start_desktop_shell(self) -> bool:
        """统一桌面壳入口：优先 Tauri（轻量），未构建/失败则回退 Electron。"""
        try:
            if await self.start_tauri():
                return True
            logger.info("Tauri 桌面壳不可用，回退到 Electron")
        except Exception as _exc:
            logger.warning("Tauri 启动失败: %s，回退到 Electron", _exc)
        self._desktop_shell = "electron"
        return await self.start_electron()

    async def _try_start_tray(self) -> bool:
        """Internal helper: attempt to start the system tray icon."""
        from windows_service.tray_icon import start_tray_in_thread
        tray = await asyncio.to_thread(start_tray_in_thread)
        if tray is not None:
            self._tray = tray
            logger.info("系统托盘已启动")
            return True
        logger.warning("系统托盘返回 None，可能缺少依赖")
        return False

    async def start_system_tray(self) -> bool:
        """启动系统托盘（右下角），与 Electron 解耦、常驻于本启动器进程。

        以前托盘由 Electron `spawn('python -m windows_service.tray_icon')` 拉起，
        Electron 崩溃/重启就把托盘也带没了。现在在 Python 启动器自身进程的后台线程里
        启动（start_tray_in_thread 内部 run_detached），后端存活期间托盘一直在。
        缺 pystray/Pillow 时优雅降级（非致命）。
        """
        try:
            return await self._try_start_tray()
        except ImportError:
            logger.debug("系统托盘依赖未安装 (windows_service.tray_icon)")
            return False
        except Exception as exc:
            logger.warning("系统托盘启动失败(非致命): %s", exc)
            return False

    async def watch_processes(self):
        """进程保活 + GPU 自适应：监控 Electron，崩溃时自动重启。

        按机器实际情况自适应渲染模式（无需用户手动判断有没有 GPU）：
        - 默认 GPU（硬件加速）模式启动；
        - 若 GPU 模式 60s 内崩溃 >= MAX_GPU 次（常见于笔记本双显卡/驱动不支持透明窗口
          GPU 合成）→ 自动切换为软件渲染重试；
        - 若软件渲染也 60s 内崩溃 >= MAX_SW 次 → 停止自动重启并给出指引。
        Electron 的 stdout/stderr 写入 logs/electron.log（含 *-process-gone 崩溃原因）。
        """
        import asyncio
        import time
        restarts: list[float] = []   # 最近 60s 窗口内的重启时间戳
        max_gpu_crashes = self.MAX_GPU_CRASHES  # GPU 模式连续崩溃达此数 → 切软件渲染
        max_sw_crashes = self.MAX_SW_CRASHES    # 软件渲染也崩到此数 → 放弃
        gave_up = False
        if not hasattr(self, "_electron_force_software"):
            self._electron_force_software = False
        while True:
            await asyncio.sleep(5)
            proc = getattr(self, '_cached_electron_proc', None) or getattr(self, 'electron_proc', None)
            self._cached_electron_proc = proc
            if not proc or proc.poll() is None or gave_up:
                continue              # 未启动 / 仍在运行 / 已放弃
            now = time.time()
            restarts = [t for t in restarts if now - t < 60]

            # GPU 模式反复崩溃 → 自动降级为软件渲染（自适应核心）
            if (not self._electron_force_software) and len(restarts) >= max_gpu_crashes:
                self._electron_force_software = True
                restarts = []
                logger.warning(
                    "Electron GPU 模式 60s 内崩溃 %d 次，自动切换为软件渲染重试"
                    "（你的显卡/驱动可能不支持透明窗口 GPU 合成；详情见 logs/electron.log）…",
                    max_gpu_crashes,
                )
                await self.start_desktop_shell()
                continue

            # 软件渲染也反复崩溃 → 放弃
            if self._electron_force_software and len(restarts) >= max_sw_crashes:
                gave_up = True
                logger.error(
                    "Electron 在 GPU 与软件渲染下均反复崩溃，已停止自动重启。"
                    "崩溃详情见 logs/electron.log；后端与 API 仍在 "
                    "http://localhost:%d 正常运行（Ctrl+Alt+Space 覆盖层暂不可用）。",
                    self.config.web_ui_port,
                )
                continue

            restarts.append(now)
            _mode = "软件渲染" if self._electron_force_software else "GPU"
            logger.warning(
                "Electron 已退出，重启中（%s 模式，60s 内第 %d 次；详情见 logs/electron.log）…",
                _mode, len(restarts),
            )
            await self.start_desktop_shell()

    async def setup(self):
        """加载配置并初始化服务管理器。"""
        self.service_manager.state = SystemState.LOADING_CONFIG

    async def start_nats(self):
        """启动 NATS 消息总线。"""
        from core.nats_server import EmbeddedNATSServer
        from core.nats_bus import get_nats_bus
        nats_url = os.environ.get("GALAXY_NATS_URL")
        if not nats_url:
            server = EmbeddedNATSServer()
            if await server.start():
                return
        bus = get_nats_bus()
        await bus.connect()

    async def start_tailscale(self):
        """启动 Tailscale 网络。返回真实 Tailscale IP（供显示）。"""
        from core.tailscale_manager import TailscaleManager
        ts = TailscaleManager()
        # 冷启动时网关常先于 Tailscale 就绪 → 首次 entrypoint.json 里没有 tailscale 地址。
        # 注册回调：Tailscale IP 出现/变化时重写 entrypoint.json，把 mesh 地址补进去，
        # 让手机/手表尽快发现网关、异地秒连（不必等下次启动）。
        try:
            ts.on_state_change(lambda _action, _details: self._write_entrypoint_json())
        except Exception:  # noqa: BLE001
            pass
        ts_ip = await ts.initialize()
        if not ts_ip:
            raise RuntimeError("Tailscale not installed")
        return ts_ip

    async def start_local_brain(self):
        """启动本地 Ollama 大脑。"""
        from core.local_brain_manager import LocalBrainManager
        self._brain = LocalBrainManager()
        await self._brain.ensure_running()

    async def start_voice_interaction(self) -> bool:
        """启动语音交互闭环：听麦克风 → ASR → 主回路(驱动三态 + 出回复) → TTS 朗读。

        这是"对它说话它会回应、且三态随对话变化"的关键——此前 VoiceLoop 从未被拉起,
        所以唤醒后说话毫无反应。现在把它接到 DesktopPresenceRuntime.handle_request:
        说话 → LIMINAL(思考动画) → 出回复 → MANIFEST(表达动画) → 朗读 → SILENT。

        缺语音依赖(faster-whisper / edge-tts / sounddevice)时优雅降级,不影响其余启动。
        GALAXY_VOICE=0 可关闭。
        """
        if os.environ.get("GALAXY_VOICE", "1").strip().lower() in ("0", "false", "no", "off"):
            self._voice_input_disabled_reason = "GALAXY_VOICE=0(已手动关闭)"
            return False
        # 麦克风采集依赖 sounddevice/PortAudio。它不就位时 AudioCaptureService.start()
        # 会【静默跳过】、mic 永不打开,而此前本函数照样 return True → 摘要谎报"语音交互
        # 已开启"(所有者反馈"对它说话没反应、不知为何")。这里显式探测并如实报因。
        try:
            from core.multimodal.audio_ingest import _SOUNDDEVICE_AVAILABLE as _sd_ok
        except Exception:
            _sd_ok = False
        if not _sd_ok:
            self._voice_input_disabled_reason = (
                "麦克风采集不可用:sounddevice/PortAudio 未就绪 —— 对它说话不会有反应。"
                "Linux 装 libportaudio2 portaudio19-dev;Windows 试 "
                "pip install --force-reinstall sounddevice"
            )
            logger.warning(
                "\n%s\n⚠️  语音输入未启用:麦克风采集依赖 sounddevice/PortAudio 未就绪。\n    %s\n%s",
                "=" * 66,
                self._voice_input_disabled_reason,
                "=" * 66,
            )
            return False
        try:
            from core.voice_loop import VoiceLoop

            class _VoiceGalaxyAdapter:
                """把 ASR 文本接进主回路:process(text) → handle_request(驱动三态 + 返回回复)。"""
                async def process(self, text: str, source: str = "voice"):
                    try:
                        from core.desktop_presence_runtime import get_desktop_presence_runtime
                        rt = get_desktop_presence_runtime()
                        return await rt.handle_request(
                            message=text, source=source,
                            session_id="voice", user_id="voice", entry_mode="local",
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("语音→主回路处理失败: %s", exc)
                        return {"response": ""}

            self._voice_loop = VoiceLoop(
                _VoiceGalaxyAdapter(),
                model_size=os.environ.get("GALAXY_WHISPER_MODEL", "base"),
                speak_responses=False,  # 朗读由 handle_request 经 speech_output 集中处理,避免双声
            )
            await self._voice_loop.start()
            return True
        except ImportError as exc:  # noqa: BLE001
            # 语音输入静默失效最常见的原因。醒目告知 + 给可直接照做的命令,
            # 而不是淹没在启动日志里的一行 warning(所有者反馈"对它说话没反应、不知为何")。
            self._voice_input_disabled_reason = f"缺 ASR 依赖({exc});运行 pip install faster-whisper 后重启"
            logger.warning(
                "\n%s\n⚠️  语音输入未启用 —— 对它说话不会有反应。\n"
                "    缺 ASR 依赖:%s\n"
                "    装上后重启即开启(麦克风/TTS 通常已随默认依赖装好):\n"
                "        pip install faster-whisper\n%s",
                "=" * 66,
                exc,
                "=" * 66,
            )
            return False
        except Exception as exc:  # noqa: BLE001
            _exc_s = str(exc)
            if any(k in _exc_s for k in ("Hub", "locate the files", "snapshot folder", "internet")):
                self._voice_input_disabled_reason = f"Whisper 模型下载失败(检查网络/代理):{exc}"
                logger.warning("语音交互未启动(Whisper 模型下载失败，检查网络或设置代理): %s", exc)
            else:
                self._voice_input_disabled_reason = f"运行时错误:{exc}"
                logger.warning("语音交互未启动(运行时错误，GALAXY_VOICE=0 可关闭): %s", exc)
            return False

    async def select_and_start_brain(self):
        """Phase 5：先选主脑（硬件推荐 + 手动选，放第 5 步而非开头），
        再确保 Ollama 服务本身真的起来了，最后才后台拉取模型。

        修复:之前 background_pull() 在 start_local_brain() 之前就立即触发——
        它开的后台线程第一件事就是探测 Ollama 是否可达，那时 Ollama 服务本身
        可能压根还没起来(尤其 Windows 首次冷启动，GPU/驱动探测、杀毒软件扫描
        exe 都会拖慢 ollama serve 绑定 11434 端口的时间)。start_local_brain()
        内部(LocalBrainManager._ensure_ollama_running)已经有专门等 Ollama
        就绪的重试逻辑(最长约 40 秒)，但 background_pull() 走的是完全独立的
        一次性尝试、连不上就直接判定失败退出，不会重试、也不会等 Ollama
        追上来——真机反馈"不管是重新启动还是手动重试，模型拉取都失败"，
        根因就是这个顺序颠倒的竞态:每次启动都在 Ollama 真正就绪前就已经
        打完这一枪、后台线程退出，直到下次重启又原样重演同一个竞态，
        看起来像是"怎么修都没用"。这里把 start_local_brain() 挪到
        background_pull() 之前，确保后台拉取真正开始时 Ollama 已确认可达。
        """
        import asyncio as _asyncio
        chosen = ""
        # 选择主脑：交互 input 放线程，避免阻塞事件循环。env(OLLAMA_MODEL)/已保存优先，
        # 否则按硬件推荐 + 让用户手动选（见 core.model_selection）。
        try:
            from core import model_selection as ms
            chosen = await _asyncio.to_thread(ms.resolve_main_brain, True) or ""
            if chosen and chosen.strip():
                # 证据链：把主脑选型（最终模型 + 硬件 + 候选 + 推荐理由）落进启动会话，
                # 以后能回答「这次为什么选了它、是按什么硬件推荐的」。best-effort。
                try:
                    from core.session_manager import get_session_manager
                    _max_mb, _has_gpu, _hw = ms.get_compute_summary()
                    _rec = ms.recommend(_max_mb, _has_gpu)
                    sm = get_session_manager()
                    await sm.ensure_session("session_system_boot", user_id="system")
                    sm.record_model_selection(
                        "session_system_boot", chosen,
                        reason=("环境/已保存指定" if chosen != _rec
                                else "按实际硬件推荐"),
                        hardware=_hw,
                        candidates=[t for t, _ in ms.list_models()],
                        source="resolve_main_brain",
                    )
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("主脑选择跳过(非致命): %s", exc)

        # 启动本地大脑（LocalBrainManager 读 OLLAMA_MODEL 作主脑，确认 Ollama
        # 服务本身已就绪）—— 必须先于下面的后台拉取执行。
        await self.start_local_brain()

        if chosen:
            from core import model_selection as ms
            ms.background_pull(chosen)  # 本地缺失则后台 ollama pull（Ollama 此时已确认可达）

    async def launch_web_ui(self):
        """启动 Web UI / API 网关。"""
        await self.web_ui.start()

    def _write_entrypoint_json(self):
        """写出 entrypoint.json 供客户端发现。"""
        try:
            _write_entrypoint(self.config.host, self.config.web_ui_port)
        except Exception as _e:
            logger.warning("写入 runtime/entrypoint.json 失败（不影响启动）: %s", _e)

    async def start(self):
        """启动 Galaxy 后端 — 板块式输出。"""
        await self.setup()
        self.service_manager = ServiceManager(self.config)

        # ── 启动阶段渲染（clig.dev：默认每阶段折叠一行，-v 展开逐项明细）──
        from core import cli_render as r
        verbose = bool(getattr(self, "_verbose", False))
        port = self.config.web_ui_port
        host = self.config.host
        phases_state: List[Tuple[str, str, Optional[str]]] = []  # (阶段名, 状态, 专属修复建议) → 末尾总结卡用

        def _emit(name: str, value: str, status: str,
                  details: Optional[List[Tuple[str, str, str]]] = None,
                  hint: Optional[str] = None) -> None:
            """记录并渲染一个阶段：默认折叠成一行；-v 时打印小标题 + 逐项明细。

            hint: 若该阶段最终判定为降级/失败，末尾总结卡"降级"行要展示的
            该项【专属】修复建议（而非把所有降级项共用一句通用提示——那样会
            出现"AI 大脑需要重新拉模型/配 Key，却被告知装 Docker 后重跑即恢复"
            这种文不对题的情况）。不传则总结卡显示该项名称、不附带建议。
            """
            phases_state.append((name, status, hint))
            # 计时:每次 _emit 是某阶段收尾,记录距上一次 _emit 的耗时归到该阶段名下
            # (隐蔽:只进 logs/lumiv.log + 面板诊断;GALAXY_PHASE_TIMING=0 可关)。
            try:
                from core.startup_timing import mark as _phase_mark
                _phase_mark(name)
            except Exception:  # noqa: BLE001
                pass
            if verbose:
                r.section(name)
                for label, val, st in (details or [(name, value, status)]):
                    r.detail(label, val, st)
            else:
                r.phase(name, value, status)

        if not verbose:
            print()  # banner 与折叠阶段行之间留一行呼吸

        # 立启动计时基准:此后每个 _emit(阶段收尾)的 mark 就能量出该阶段耗时。
        try:
            from core.startup_timing import mark_reset as _phase_mark_reset
            _phase_mark_reset()
        except Exception:  # noqa: BLE001
            pass

        # ── 核心服务 ──
        try:
            from launcher.core_services import CoreServiceLauncher
            cs = CoreServiceLauncher(self.service_manager, self.config)
            results = await cs.start_all()
            _r = results if isinstance(results, dict) else {}
            items = [
                ("Device Agent 管理器", _r.get("device_agent_manager", False)),
                ("设备状态 API :8766", _r.get("device_status_api", False)),
                ("Microsoft UFO 集成", _r.get("microsoft_ufo_integration", False)),
            ]
            up = sum(1 for _, v in items if v)
            st = "ok" if up == len(items) else ("warn" if up else "fail")
            _emit("核心服务", f"{up}/{len(items)} 就绪", st,
                  details=[(n, "就绪" if v else "未就绪", "ok" if v else "warn") for n, v in items])
        except Exception as exc:
            _emit("核心服务", "启动失败", "fail")
            logger.error(f"Core services: {exc}")

        # ── 基础设施 (Docker / Podman，自动拉起；依赖它的节点才能起来) ──
        try:
            d_status, d_value, d_note = await self.ensure_docker_infra()
        except Exception as exc:
            d_status, d_value, d_note = "warn", "基础设施启动异常（非致命）", ""
            logger.warning("ensure_docker_infra failed: %s", exc)
        # 标签反映实际选中的运行时(Docker / Podman);resolve_runtime 已把选择写入
        # GALAXY_CONTAINER_RUNTIME,未选到则统一显示 "容器"。
        _rt = os.environ.get("GALAXY_CONTAINER_RUNTIME", "").strip().capitalize() or "容器"
        d_details = [(f"{_rt} 基础设施", d_value, d_status)]
        if d_note:
            d_details.append(("下一步", d_note, "info"))
        _emit(f"基础设施 · {_rt}", d_value, d_status, details=d_details,
              hint="装 Docker/Podman 后重跑即恢复" if d_status != "ok" else None)

        # ── 消息总线 ──
        bus_details: List[Tuple[str, str, str]] = []
        try:
            await self.start_nats()
            nats_host = os.environ.get("GALAXY_NATS_HOST", "localhost")
            nats_port = os.environ.get("GALAXY_NATS_PORT", "4222")
            bus_details.append(("NATS Bus", f"nats://{nats_host}:{nats_port}", "ok"))
            nats_ok, bus_value = True, f"nats://{nats_host}:{nats_port}"
        except Exception as exc:
            bus_details.append(("NATS Bus", f"{exc}", "warn"))
            nats_ok, bus_value = False, "NATS 未就绪"
        try:
            ts_ip = await self.start_tailscale()
            bus_details.append(("Tailscale", ts_ip or "已连接", "ok"))
            # PR-PEER-RELAY: 显示对等中继态（本机已宣告 / 各 peer 经哪条中继）。
            try:
                from core.tailscale_manager import TailscaleManager
                _rs = TailscaleManager().get_relay_status()
                if _rs.get("advertise_relay_enabled"):
                    _via = _rs.get("self_relay")
                    bus_details.append((
                        "对等中继",
                        ("已宣告（本机充当私有中继）" if not _via else f"经 {_via}"),
                        "ok",
                    ))
            except Exception:
                pass
        except Exception:
            bus_details.append(("Tailscale", "未安装 (LAN 直连模式)", "warn"))
        _emit("消息总线", bus_value, "ok" if nats_ok else "warn", details=bus_details)

        # ── AI 大脑（含主脑模型选择）──
        try:
            await self.select_and_start_brain()
            brain = getattr(self, "_brain", None)
            # 全部为真实运行时数据（非硬编码）：
            healthy = bool(brain and getattr(brain, "_healthy", False))
            bm = (getattr(brain, "brain_model", None) or os.environ.get("OLLAMA_MODEL", "") or "未选择")
            avail = list(getattr(brain, "available_models", []) or [])
            shown = (", ".join(avail[:6]) + (f" 等 {len(avail)} 个" if len(avail) > 6 else "")) if avail else "（无 / 后台下载中）"
            hp = getattr(brain, "_hardware_profile", None)
            if hp and getattr(hp, "has_gpu", False):
                hw = f"GPU {getattr(hp, 'gpu_name', '?') or '?'} | 显存 {getattr(hp, 'vram_mb', 0)} MB"
            else:
                hw = "CPU 模式（无独显，软件推理）"

            # 关键修复:_healthy 只代表"Ollama 服务本身可达",不代表"选中的这个模型
            # 真的装好了"——真机复现过:服务健康但 gemma4:e2b 从未拉取成功,这里却照样
            # 打 ✓、显示"就绪",用户看着一片绿实际上一句话都问不出来(每次调用都
            # 404)。ai_brain_readiness() 额外核实选中模型是否真的在已安装列表里。
            st, model_installed, model_status_label = ai_brain_readiness(bm, avail, healthy)
            ai_brain_phase_idx = len(phases_state)
            _emit("AI 大脑", f"{bm}  ·  {hw}" + ("" if model_installed else "  ⚠ 模型未就绪"), st,
                  hint=(None if model_installed else model_status_label), details=[
                ("Ollama 推理服务", "就绪" if healthy else "未就绪（检查 ollama 是否运行）",
                 "ok" if healthy else "fail"),
                ("AI 主脑模型", f"{bm} — {model_status_label}", "ok" if model_installed else "warn"),
                ("已安装模型", shown, "ok" if avail else "warn"),
                ("硬件", hw, "ok"),
            ])
        except Exception as exc:
            ai_brain_phase_idx = len(phases_state)
            _emit("AI 大脑", "启动失败", "fail")
            logger.error(f"Local brain: {exc}")

        # ── 启动自检 · URL 哨兵(审查结果直接摆上克隆界面,不用翻日志)──
        # 关键信息放在折叠行里(默认可见);-v 展开逐条明细 + 取证值(代码版本/
        # 环境变量/解析后地址)。抓到告警时进末尾总结卡并附操作建议。
        try:
            _ver, _env_repr, _resolved, _catches = _url_sentinel_audit()
            _audit_details: List[Tuple[str, str, str]] = [
                ("代码版本", _ver, "ok" if _ver != "unknown" else "warn"),
                ("OLLAMA_URL(env)", _env_repr, "ok"),
                ("解析后地址", _resolved, "ok"),
            ]
            if _catches:
                for _c in _catches[:5]:
                    _audit_details.append((
                        "缺协议头请求",
                        f"url={_c.get('url', '')!r} ← {_short_culprit(_c.get('culprit', ''))}",
                        "fail",
                    ))
                _first = _catches[0]
                _emit(
                    "启动自检 · URL哨兵",
                    f"⚠ 抓到 {len(_catches)} 条缺协议头请求 · 首条 "
                    f"url={_first.get('url', '')!r} ← {_short_culprit(_first.get('culprit', ''))}",
                    "warn",
                    details=_audit_details,
                    hint="把「启动自检 · URL哨兵」这行(含 url 与 file:line)复制/截图发回即可精确定位",
                )
            else:
                _emit("启动自检 · URL哨兵", f"零告警 · 代码版本 {_ver} · Ollama {_resolved}",
                      "ok", details=_audit_details)
        except Exception as exc:
            logger.debug("URL 哨兵自检展示失败(非致命): %s", exc)

        # ── 节点系统 ──
        try:
            from launcher.node_startup import NodeSystemLauncher
            nl = NodeSystemLauncher(self.service_manager, self.config)
            result = await nl.start_all()
            # 真实计数：start_all 返回 {node_name: ok}。就绪数/尝试总数，不再写死 /13 /117。
            total = len(result) if isinstance(result, dict) else 0
            ready = sum(1 for v in result.values() if v) if isinstance(result, dict) else 0
            st = "ok" if (ready > 0 or total == 0) else "warn"
            details = ([(n, "就绪" if v else "未就绪", "ok" if v else "warn") for n, v in result.items()]
                       if isinstance(result, dict) and result else None)
            _emit("节点系统", f"{ready}/{total} 就绪", st, details=details)
        except Exception as exc:
            _emit("节点系统", "启动失败", "fail")
            logger.error(f"Node system: {exc}")

        # ── L4 增强模块（后台增强层、可选）──
        try:
            l4 = L4EnhancementLauncher(self.service_manager, self.config)
            result = await l4.start_all()
            _mods = result.get("modules", {}) if isinstance(result, dict) else {}
            modules = _mods if isinstance(_mods, dict) else {}
            if modules:
                up = sum(1 for ok in modules.values() if ok)
                st = "ok" if up == len(modules) else "warn"
                _emit("L4 增强模块", f"{up}/{len(modules)} 就绪", st,
                      details=[(n, "就绪" if ok else "未就绪", "ok" if ok else "warn")
                               for n, ok in modules.items()])
            else:
                # 无逐模块明细时不假装全绿；按整体结果如实显示。
                started = bool(result)
                _emit("L4 增强模块",
                      "后台增强层已就绪" if started else "未启用（可选）",
                      "ok" if started else "warn")
        except Exception as exc:
            _emit("L4 增强模块", "启动失败", "fail")
            logger.error(f"L4 modules: {exc}")

        # ── API 网关 ──
        try:
            await self.launch_web_ui()
            _emit("API 网关", f"http://localhost:{port}", "ok", details=[
                ("FastAPI + Uvicorn", f"http://{host}:{port}", "ok"),
                ("WebSocket", f"ws://localhost:{port}/ws", "ok"),
                ("API 文档", f"http://localhost:{port}/docs", "ok"),
                ("健康检查", "/health", "ok"),
                ("状态面板", f"http://localhost:{port}/api/v1/projection/operability-contract", "ok"),
            ])
        except Exception as exc:
            _emit("API 网关", "启动失败", "fail")
            logger.error(f"API gateway: {exc}")

        # ── 桌面前端 (三态覆盖层：优先 Tauri，未构建则回退 Electron) ──
        electron_ok = await self.start_desktop_shell()
        shell = getattr(self, "_desktop_shell", "electron")
        shell_name = "Tauri（系统 WebView，轻量）" if shell == "tauri" else "Electron"
        if electron_ok:
            _emit("桌面前端 · 三态覆盖层", f"已启动（暖金边缘氛围光） · {shell_name}", "ok", details=[
                ("壳层", shell_name, "ok"),
                ("三态覆盖层", "已启动", "ok"),
                ("第一态", "暖金边缘氛围光（待机即显示）", "ok"),
                ("三态切换", "AI 实际活动驱动 silent → liminal → manifest", "ok"),
                ("快捷键", "Ctrl+Alt+Space 唤醒 / Ctrl+Alt+H 隐藏", "ok"),
            ])
        else:
            _emit("桌面前端 · 三态覆盖层", "未启动 — 后端/API 仍完全可用", "warn")
            logger.warning(
                "Electron 三态覆盖层未启动（缺 Node.js 或 electron 依赖安装失败）。"
                "后端与 API 已就绪 http://localhost:%d ；"
                "如需桌面覆盖层：安装 Node.js≥18 后在 electron/ 执行 `npm install`。",
                self.config.web_ui_port,
            )

        # ── 系统托盘（独立于 Electron，常驻）──
        # 托盘原先仅由 Electron 进程 spawn；Electron 在部分机器上崩溃/重启会让右下角
        # 托盘图标随之消失。改由 Python 启动器在自身进程的后台线程启动，与 Electron
        # 解耦 —— 后端在，托盘就在。
        tray_ok = await self.start_system_tray()
        _emit("系统托盘", "右下角常驻" if tray_ok else "不可用 (pip install pystray Pillow)",
              "ok" if tray_ok else "warn")

        # ── 远程桌面兜底(VNC)：默认关；GALAXY_REMOTE_DESKTOP=1 才自动开（仅 Tailscale 私网内）──
        try:
            from core.remote_desktop import maybe_autostart as _rd_autostart
            _rd_autostart()
        except Exception as _exc:  # noqa: BLE001
            logger.debug("远程桌面兜底自动开启跳过(非致命): %s", _exc)

        # ── 语音交互闭环：听 → 识别 → 主回路(驱动三态 + 回复) → 朗读 ──
        # 这是"对它说话它会回应、三态随对话变化"的关键(此前 VoiceLoop 从未启动)。
        voice_ok = await self.start_voice_interaction()
        _voice_reason = getattr(self, "_voice_input_disabled_reason", None)
        _emit(
            "语音交互",
            ("已开启 · 直接对它说话即可（三态随对话变化）" if voice_ok
             else f"未启用：{_voice_reason or '详见上方日志'}"),
            "ok" if voice_ok else "warn",
        )

        # ── AI 大脑状态复核（总结卡打印前）──
        # 真机复现过:"AI 大脑"这一行的状态是在 select_and_start_brain() 刚返回
        # 那一刻算出来、写死进 phases_state 的——但 background_pull() 是故意
        # 不阻塞启动的后台线程，此时很可能还没跑完(甚至 Ollama 服务本身当时都
        # 还在冷启动、没来得及在 _ensure_ollama_running() 的等待窗口内响应)。
        # 等到节点系统、L4 模块、Electron、托盘、语音这些阶段都跑完、真正要打
        # 总结卡的这一刻，Ollama 大概率已经起来、模型也大概率已经拉好了，但
        # 总结卡的"降级"栏之前一直用的是那个过时快照，导致用户看到"AI 大脑 →
        # 未安装(拉取失败/未完成)"，实际上模型已经真的装好可用——这是过期状态
        # 展示的问题，不是模型真的没装好。这里在打印总结卡前重新探测一次真实
        # 状态，好转了就更新对应条目，不去猜、不主观放宽判定标准。
        if 'ai_brain_phase_idx' in locals() and 0 <= ai_brain_phase_idx < len(phases_state):
            await _recheck_ai_brain_phase(getattr(self, "_brain", None), phases_state, ai_brain_phase_idx)

        # ── 总结卡：状态 + 关键入口 + 降级项 + 下一步 ──
        ok_n = sum(1 for _, s, _h in phases_state if s == "ok")
        # 每个降级项各带自己的专属修复建议，而不是所有降级项共用一句"装后重跑即恢复"——
        # 那句话只对 Docker 这类"装个东西重跑就好"的场景成立;AI 大脑之类的降级
        # (模型没拉好/没配 Key)配的建议完全不同，共用会文不对题、误导用户。
        degraded_items = [(n, h) for n, s, h in phases_state if s in ("warn", "fail")]
        r.summary_card(
            title="Galaxy L4 · v2.3.21",
            state_ok=ok_n,
            state_degraded=len(degraded_items),
            rows=[
                ("面板", f"http://localhost:{port}"),
                ("文档", f"http://localhost:{port}/docs"),
                ("唤醒", "Ctrl+Alt+Space    隐藏 Ctrl+Alt+H"),
                ("日志", "托盘 →「三态动画日志」"),
            ],
            degraded=degraded_items or None,
            hints=[("停止", "Ctrl+C"), ("详细", "python main.py -v")],
        )

        # Write entrypoint.json
        self._write_entrypoint_json()

        # Start process watchdog
        await self.watch_processes()
                
    def stop(self):
        """停止系统（优雅关闭所有子系统）"""
        print()
        print_status("正在停止系统...", "loading")
        self.service_manager.state = SystemState.STOPPING
        self.running = False

        # 优雅关闭核心子系统（事件桥 → 监控 → 缓存）
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            # 在运行中的事件循环内（如 async 上下文调用 stop）
            asyncio.ensure_future(async_shutdown())
        else:
            # 没有运行中的事件循环，创建新 loop 执行异步关闭
            try:
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                new_loop.run_until_complete(async_shutdown())
                new_loop.close()
            except Exception as e:
                logger.warning(f"异步关闭失败: {e}")

        # 关闭认知进化系统（PR-25/26/27）
        try:
            from core.cognitive.evolution_system import shutdown_cognitive_evolution
            shutdown_cognitive_evolution()
        except Exception:
            pass

        self.service_manager.stop_all()
        self.service_manager.state = SystemState.STOPPED
        print_status("系统已停止", "success")

    def show_status(self):
        """显示系统状态"""
        print_banner()
        
        print_section("配置状态")
        status = self.config.get_status_dict()
        
        _bold = _safe_color(getattr(Colors, "BOLD", "\033[1m"))
        _end = _safe_color(getattr(Colors, "ENDC", "\033[0m"))
        print(f"\n{_bold}LLM API:{_end}")
        for api, configured in status["llm_apis"].items():
            icon = "✓" if configured else "✗"
            print(f"  {icon} {api.upper()}")

        print(f"\n{_bold}数据库:{_end}")
        for db, configured in status["database"].items():
            icon = "✓" if configured else "✗"
            print(f"  {icon} {db}")
            
        print_section("节点统计")
        all_nodes = self.node_launcher.get_all_nodes()
        core_nodes = self.node_launcher.get_core_nodes()
        print(f"  总节点数: {len(all_nodes)}")
        print(f"  核心节点: {len(core_nodes)}")

        print_section("双仓推进进度（真实代码审计）")
        try:
            from core.dual_repo_progress_report import build_dual_repo_progress_report

            report = build_dual_repo_progress_report(force_rebuild=True)
            summary = report.get("summary_zh") or ""
            if summary:
                print(f"  摘要: {summary}")
            completion = report.get("system_completion_status") or {}
            if isinstance(completion, dict):
                closure_pct = completion.get("system_closure_pct")
                blocking = completion.get("blocking_gap_count")
                verdict = completion.get("completeness_verdict")
                if closure_pct is not None:
                    print(f"  系统收口度: {closure_pct:.2f}%  completeness={verdict}  阻塞项={blocking}")
            review = report.get("complete_joint_system_review") or {}
            if isinstance(review, dict) and review.get("stage"):
                weighted = review.get("weighted_completion_pct")
                weighted_display = "unknown"
                if isinstance(weighted, (int, float)):
                    weighted_display = f"{weighted:.2f}%"
                print(
                    "  联合审查: "
                    f"stage={review.get('stage')} "
                    f"weighted={weighted_display} "
                    f"android_ref={review.get('android_audited_ref')}"
                )
            plan = report.get("closure_phase_execution_plan") or {}
            if isinstance(plan, dict) and plan.get("next_prs"):
                next_prs = list(plan.get("next_prs") or [])[:5]
                if next_prs:
                    print(f"  下一步建议 PR: {', '.join(next_prs)}")
        except Exception as e:
            print_status(f"双仓推进进度不可用: {e}", "warning")


# ============================================================================
# 主函数
# ============================================================================

async def _run_check_only(lumiv: 'GalaxyUnified'):
    """仅检查依赖和配置，输出完整系统状态表，不启动服务"""
    print_banner()
    print_section("系统检查模式 (--check-only)")

    # 1. 依赖检查
    print_section("依赖检查")
    try:
        from scripts.check_dependencies import CORE_DEPS, OPTIONAL_DEPS, check_dep as check_dependency
        missing_core = []
        missing_optional = []
        for dep in CORE_DEPS:
            if not check_dependency(dep):
                missing_core.append(dep)
        for dep in OPTIONAL_DEPS:
            if not check_dependency(dep):
                missing_optional.append(dep)
        print_status(f"核心依赖: {len(CORE_DEPS) - len(missing_core)}/{len(CORE_DEPS)} 已安装",
                     "success" if not missing_core else "error")
        if missing_core:
            for d in missing_core:
                print_status(f"  缺失: {d}", "error")
        print_status(f"可选依赖: {len(OPTIONAL_DEPS) - len(missing_optional)}/{len(OPTIONAL_DEPS)} 已安装",
                     "success" if not missing_optional else "warning")
        if missing_optional:
            for d in missing_optional:
                print_status(f"  缺失: {d}", "warning")
    except Exception as e:
        print_status(f"依赖检查脚本加载失败: {e}", "error")

    # 2. 配置检查
    print_section("配置检查")
    status = lumiv.config.get_status_dict()
    llm_count = sum(1 for v in status["llm_apis"].values() if v)
    print_status(f"LLM API: {llm_count} 个已配置", "success" if llm_count > 0 else "warning")

    # 3. 核心模块导入检查
    print_section("核心模块导入")
    core_modules = [
        "core.startup", "core.agent_factory", "core.multi_llm_router",
        "core.node_registry", "core.node_discovery", "core.monitoring",
        "core.health_check", "core.cache", "core.error_framework",
        "core.event_bridge", "core.command_router", "core.concurrency_manager",
        "core.config_hot_reload", "core.digital_twin_engine",
        "core.health_integration", "core.api_routes",
    ]
    ok_count = 0
    for mod_name in core_modules:
        try:
            __import__(mod_name)
            ok_count += 1
        except BaseException as e:
            print_status(f"  {mod_name}: {type(e).__name__}: {e}", "error")
    print_status(f"核心模块: {ok_count}/{len(core_modules)} 可导入",
                 "success" if ok_count == len(core_modules) else "warning")

    # 4. 节点导入检查
    print_section("节点导入检查")
    nodes_dir = PROJECT_ROOT / "nodes"
    loaded = 0
    failed = 0
    failed_names = []
    if nodes_dir.exists():
        for node_dir in sorted(nodes_dir.iterdir()):
            main_py = node_dir / "main.py"
            if not main_py.exists():
                continue
            mod_path = f"nodes.{node_dir.name}.main"
            try:
                __import__(mod_path)
                loaded += 1
            except BaseException as e:
                failed += 1
                failed_names.append((node_dir.name, f"{type(e).__name__}: {str(e)[:80]}"))
    print_status(f"节点: {loaded}/{loaded + failed} 可导入",
                 "success" if failed == 0 else "warning")
    if failed_names:
        for name, err in failed_names:
            print_status(f"  {name}: {err}", "warning")

    # 汇总
    print_section("检查完成")
    has_core_issues = bool(missing_core) if 'missing_core' in locals() else False
    all_ok = (not has_core_issues) and ok_count == len(core_modules)
    if all_ok:
        print_status("系统就绪，可以启动", "success")
    else:
        print_status("存在问题，请检查上方输出", "warning")
    sys.stdout.flush()


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
    loop = None
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
        except Exception:
            pass  # 非关键组件,允许失败

        try:
            loop.run_until_complete(lumiv.start())
        except KeyboardInterrupt:
            print()
            print_status("正在停止系统...", "loading")
            lumiv.stop()
            print_status("系统已停止", "success")

    except KeyboardInterrupt:
        pass  # Already handled above


def _graceful_shutdown():
    """Handle graceful shutdown signals."""
    print_status("收到停止信号,正在优雅关闭...", "loading")
    try:
        import asyncio
        asyncio.get_event_loop().stop()
    except Exception:
        pass


def main():
    """CLI entry point for standalone launch (subordinate role — PR-2)."""
    parser = argparse.ArgumentParser(description="Galaxy Unified Launcher (subordinate)")
    parser.add_argument("--check-only", action="store_true",
                        help="Check dependencies and configuration without starting services")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose output")
    args = parser.parse_args()

    if args.verbose:
        os.environ["GALAXY_VERBOSE"] = "1"

    if args.check_only:
        lumiv = GalaxyUnified()
        asyncio.run(_run_check_only(lumiv))
        return 0

    # Normal startup path: run the full bring-up
    lumiv = GalaxyUnified()
    try:
        asyncio.run(lumiv.start())
    except KeyboardInterrupt:
        print()
        print_status("正在停止系统...", "loading")
        lumiv.stop()
        print_status("系统已停止", "success")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
