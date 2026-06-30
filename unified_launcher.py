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

logging.basicConfig(
    level=logging.WARNING,  # console只显示警告/错误；INFO详情写 logs/lumiv.log
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("Galaxy")


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


def print_status(message: str, status: str = "info"):
    """打印状态信息（单行，无值列）。"""
    print_status_row(message, status=status)


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
    except Exception:
        pass


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
                if os.path.exists(exe):
                    sp.Popen([exe], creationflags=getattr(sp, "DETACHED_PROCESS", 0))
                    return
        elif sys.platform == "darwin":
            sp.Popen(["open", "-a", "Docker"])
        else:
            sp.run(["systemctl", "start", "docker"], capture_output=True, timeout=20)
    except Exception:
        pass


def _get_lan_ip() -> str:
    """Return the host's primary LAN IPv4 address, or empty string if unavailable."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return ""


# ============================================================================
# Launcher sub-module imports
# (Enums, config, service management, core/node/health/shutdown)
# ============================================================================

from launcher.bootstrap import (
    SystemState,
    ServiceType,
    SystemConfig,
    _write_entrypoint,
)
from launcher.service_manager import ServiceInfo, ServiceManager
from launcher.core_services import CoreServiceLauncher
from launcher.node_startup import NodeSystemLauncher
from launcher.health_checks import run_startup_health_check
from launcher.shutdown import async_shutdown


# ============================================================================
# L4 增强模块启动器
# ============================================================================

class L4EnhancementLauncher:
    """L4 增强模块启动器"""
    
    def __init__(self, service_manager: ServiceManager, config: SystemConfig):
        self.service_manager = service_manager
        self.config = config
        self.l4_modules = {}
        
    async def start_all(self) -> Dict[str, bool]:
        """启动所有 L4 增强模块"""
        results = {}
        
        # 感知模块
        print_status("初始化感知模块...", "step")
        try:
            from enhancements.perception.environment_scanner import EnvironmentScanner
            self.l4_modules["environment_scanner"] = EnvironmentScanner()
            results["perception"] = True
        except Exception as e:
            logger.error(f"感知模块初始化失败: {e}")
            results["perception"] = False
            
        # 推理模块
        print_status("初始化推理模块...", "step")
        try:
            from enhancements.reasoning.goal_decomposer import GoalDecomposer
            from enhancements.reasoning.autonomous_planner import AutonomousPlanner
            from enhancements.reasoning.world_model import WorldModel
            self.l4_modules["goal_decomposer"] = GoalDecomposer()
            self.l4_modules["autonomous_planner"] = AutonomousPlanner()
            self.l4_modules["world_model"] = WorldModel()
            results["reasoning"] = True
        except Exception as e:
            logger.error(f"推理模块初始化失败: {e}")
            results["reasoning"] = False
            
        # 学习模块
        print_status("初始化学习模块...", "step")
        try:
            from enhancements.learning.autonomous_learning_engine import AutonomousLearningEngine
            self.l4_modules["learning_engine"] = AutonomousLearningEngine()
            results["learning"] = True
        except Exception as e:
            logger.error(f"学习模块初始化失败: {e}")
            results["learning"] = False
            
        # 执行模块
        print_status("初始化执行模块...", "step")
        try:
            from enhancements.execution.action_executor import ActionExecutor
            self.l4_modules["action_executor"] = ActionExecutor()
            results["execution"] = True
        except Exception as e:
            logger.error(f"执行模块初始化失败: {e}")
            results["execution"] = False
            
        # 安全模块
        print_status("初始化安全模块...", "step")
        try:
            from enhancements.safety.safety_manager import SafetyManager
            self.l4_modules["safety_manager"] = SafetyManager()
            results["safety"] = True
        except Exception as e:
            logger.error(f"安全模块初始化失败: {e}")
            results["safety"] = False
            
        return results


# ============================================================================
# Web UI 服务器
# ============================================================================

class UnifiedWebUI:
    """统一 Web UI 服务器"""
    
    def __init__(self, service_manager: ServiceManager, config: SystemConfig):
        self.service_manager = service_manager
        self.config = config
        self.app = None
        
    async def start(self):
        """启动 Galaxy API 服务（核心运行时 API 层）

        架构说明（API 单一入口原则）：
          core/api_routes.py 是 Galaxy 系统的 **唯一权威 API 定义**。
          所有 REST 路由必须通过 core.api_routes.create_api_routes() 提供。

          当前系统表层方向：桌面三态运行层 + 桌面状态板（desktop tri-state runtime
          + desktop status surface）。dashboard/ 已删除，不再作为运行时表层。

          1. 以内建 FastAPI 应用为主应用（权威应用）。
          2. 在其上叠加 core.startup 引导的子系统中间件
          3. 叠加 core.api_routes 作为 **主 API 层**（系统管理、设备、节点、
             监控、观测性、AI、chat 等全部路由）
          4. 添加健康检查路由
          5. 统一在配置端口提供服务

        注意：此启动器 **不应** 定义自己的 inline API 路由。
        如需新增 API 端点，请在 core/routes/ 下对应子模块中添加。
        """
        try:
            from fastapi.responses import HTMLResponse, JSONResponse
            import uvicorn

            # === 步骤 1：以内建 FastAPI 应用为主应用（权威 API 基础） ===
            from fastapi import FastAPI, Depends
            from fastapi.middleware.cors import CORSMiddleware
            from core.auth import require_auth as _require_auth
            from nodes.common.cors_config import get_cors_origins, get_cors_methods, get_cors_headers
            self.app = FastAPI(
                title="Galaxy",
                description="L4 级自主性智能系统",
                version="2.0"
            )
            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=get_cors_origins(),
                allow_credentials=True,
                allow_methods=get_cors_methods(),
                allow_headers=get_cors_headers(),
            )

            # === 步骤 2：引导核心子系统（缓存 + 监控 + 性能中间件 + 命令路由 + AI） ===
            try:
                from core.startup import bootstrap_subsystems
                bootstrap_results = await bootstrap_subsystems(self.app, self.config)
                ok = sum(1 for v in bootstrap_results.values() if v.get("status") == "ok")
                total = len(bootstrap_results)
                logger.info("核心子系统: %d/%d 正常", ok, total)
                for _name, _info in bootstrap_results.items():
                    _icon = "OK" if _info.get("status") == "ok" else "DEGRADED"
                    logger.info("  [%s] %s: %s", _icon, _name, _info)
            except Exception as e:
                logger.warning("核心子系统引导失败（系统仍可运行）: %s", e)

            # === 步骤 2.5：启动认知进化系统（PR-25/26/27）===
            try:
                from core.cognitive.evolution_system import init_cognitive_evolution
                init_cognitive_evolution()
                logger.info("认知进化系统已初始化")
            except Exception as e:
                logger.warning("认知进化系统初始化失败（非阻塞）: %s", e)

            # === 步骤 3：挂载 core.api_routes 作为主 API 层 ===
            # core/api_routes.py 是 Galaxy 的 **唯一权威 API 入口**。
            # 所有 REST 路由（system、devices、nodes、vision、tasks、chat、
            # ai、monitoring、relay、hybrid、vault、cost、channels、
            # federation、sessions、concurrency、errors、observability 等）
            # 均由 core/routes/ 子模块定义，在此统一挂载。
            # dashboard/backend/main.py 中重叠的路由将被此处覆盖。
            try:
                from core.api_routes import create_api_routes, create_websocket_routes
                api_router = create_api_routes(
                    service_manager=self.service_manager,
                    config=self.config
                )
                self.app.include_router(api_router)
                logger.info("扩展 API 路由已加载（来自 core.api_routes）")

                create_websocket_routes(
                    self.app,
                    service_manager=self.service_manager
                )
                logger.info("WebSocket 端点已加载")
            except ImportError as e:
                logger.warning("API 路由模块加载失败: %s", e)

            # === 步骤 4：健康检查路由 ===
            try:
                from core.health_check import create_health_routes
                health_router, _health_checker = create_health_routes(
                    service_manager=self.service_manager,
                    config=self.config
                )
                self.app.include_router(health_router)
                logger.info("健康检查路由已加载")
            except ImportError as e:
                logger.warning("健康检查模块加载失败: %s", e)

            # === 步骤 5：静态文件挂载 (API Manager) ===
            from fastapi.staticfiles import StaticFiles
            from fastapi.responses import FileResponse

            base_static_dir = PROJECT_ROOT / "static" / "api-manager"
            static_dir = base_static_dir
            if (base_static_dir / "public").exists():
                static_dir = base_static_dir / "public"

            if static_dir.exists() and (static_dir / "assets").exists():
                self.app.mount(
                    "/assets",
                    StaticFiles(directory=str(static_dir / "assets")),
                    name="assets"
                )

                @self.app.get("/api-manager", response_class=HTMLResponse)
                async def api_manager_index():
                    index_path = static_dir / "index.html"
                    if index_path.exists():
                        return FileResponse(str(index_path))
                    return JSONResponse({"error": "index.html not found"}, status_code=404)

                logger.info("API Manager 已挂载: %s", static_dir)
            else:
                logger.warning("API Manager 静态文件未找到: %s", static_dir)

            # === 步骤 5b：Operator Console 静态挂载 ===
            # Serves static/operator-console/index.html at /operator-console.
            # The console is a pure visualization layer over OPERATOR_ROUTES_V1
            # APIs — no parallel truth model is introduced here.
            operator_console_dir = PROJECT_ROOT / "static" / "operator-console"
            operator_console_index = operator_console_dir / "index.html"
            if operator_console_index.exists():
                @self.app.get("/operator-console")
                async def operator_console_index_route():
                    return FileResponse(str(operator_console_index))

                logger.info("Operator Console 已挂载: %s", operator_console_index)
            else:
                logger.warning("Operator Console index.html 未找到: %s", operator_console_index)

            # === 步骤 6：统一启动器专属路由（不覆盖 dashboard 的 / 路由） ===
            @self.app.get("/api/status")
            async def launcher_status(auth: dict = Depends(_require_auth)):
                return JSONResponse({
                    "status": "running",
                    "version": "2.0",
                    "state": self.service_manager.state.name,
                    "services": self.service_manager.get_status(),
                    "config": self.config.get_status_dict(),
                })

            @self.app.get("/api/services")
            async def launcher_services():
                return JSONResponse(self.service_manager.get_status())

            # === 步骤 7：启动 uvicorn ===
            _uvi_config = uvicorn.Config(
                self.app,
                host=self.config.host,
                port=self.config.web_ui_port,
                log_level="warning"
            )
            server = uvicorn.Server(_uvi_config)
            logger.info(
                "Galaxy API 服务启动: http://%s:%d",
                self.config.host, self.config.web_ui_port
            )
            logger.info("API 文档: http://localhost:%d/docs", self.config.web_ui_port)
            # Run uvicorn via the public serve() entrypoint in a background task.
            # serve() correctly loads the config AND initialises self.lifespan;
            # manually calling server.startup() breaks on uvicorn ≥0.30 with
            # "'Server' object has no attribute 'lifespan'" (the gateway then never
            # binds — /api/v1/chat is unreachable even though the banner says ready).
            # We wait on the public ``server.started`` flag so the socket is bound
            # before probing, then let serve()'s main_loop keep running in the
            # background so the launcher proceeds to later phases (Electron / ready
            # banner) instead of blocking here.
            self._server = server
            self._serve_task = asyncio.create_task(server.serve())
            for _ in range(300):  # up to ~30s for bind + ASGI startup
                if server.started or self._serve_task.done():
                    break
                await asyncio.sleep(0.1)
            if self._serve_task.done():
                # serve() exited during startup — re-raise the real error so the
                # caller logs an accurate "API 网关启动失败" cause.
                self._serve_task.result()
            print_section("启动后健康检查")
            await run_startup_health_check(self.config.web_ui_port)

        except ImportError as e:
            logger.error("API 服务依赖未安装: %s", e)

    # Minimal fallback HTML — points to the API docs.
    # dashboard/frontend is a LEGACY UI SURFACE (PR-8) and is not the current primary surface.
    FALLBACK_HTML = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Galaxy</title></head>
<body style="background:#000;color:#fff;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="text-align:center">
<h1>Galaxy</h1>
<p>API docs: <a href="/docs" style="color:#00CED1">/docs</a></p>
<p style="font-size:0.8em;color:#888">Current surface: desktop tri-state runtime + desktop status board</p>
</div></body></html>"""

    def _get_legacy_dashboard_html(self) -> str:
        """读取遗留 dashboard/frontend 的 index.html（LEGACY UI SURFACE）。

        dashboard/frontend 已通过 PR-8 降级为遗留表层，不再是当前主系统表层。
        如果遗留文件不存在（属于正常情况），返回 FALLBACK_HTML。
        """
        dashboard_path = PROJECT_ROOT / "dashboard" / "frontend" / "public" / "index.html"
        if dashboard_path.exists():
            try:
                return dashboard_path.read_text(encoding="utf-8")
            except Exception as exc:
                logger.debug("读取遗留 dashboard HTML 失败（非关键）: %s", exc)

        return self.FALLBACK_HTML


# ============================================================================
# Galaxy 统一系统
# ============================================================================

class GalaxyUnified:
    """Galaxy 统一系统"""
    
    def __init__(self):
        self.config = SystemConfig.load_from_env()
        self.service_manager = ServiceManager(self.config)
        self.core_launcher = CoreServiceLauncher(self.service_manager, self.config)
        self.node_launcher = NodeSystemLauncher(self.service_manager, self.config)
        self.l4_launcher = L4EnhancementLauncher(self.service_manager, self.config)
        self.web_ui = UnifiedWebUI(self.service_manager, self.config)
        self.running = False
        # 详细模式：默认折叠每个阶段为一行；-v / GALAXY_VERBOSE=1 展开逐项明细。
        # main.py 解析到 -v 后会覆写 self._verbose；env 提供无参场景下的兜底。
        self._verbose = os.environ.get("GALAXY_VERBOSE", "").strip().lower() in ("1", "true", "yes", "on")

        # PR-DEVICE-RESOLUTION: LauncherAdapter — unified node contract bridge
        try:
            from launcher.launcher_adapter import LauncherAdapter
            self.launcher_adapter = LauncherAdapter(self.node_launcher)
            logger.info("LauncherAdapter initialised (mode=%s)", self.launcher_adapter.mode.value)
        except Exception as e:
            logger.warning("LauncherAdapter init failed (non-fatal): %s", e)
            self.launcher_adapter = None
        
        # ===== 集成：初始化能力管理器和连接管理器 =====
        try:
            from core.capability_manager import get_capability_manager
            from core.connection_manager import get_connection_manager
            
            self.capability_manager = get_capability_manager()
            self.connection_manager = get_connection_manager()
            logger.info("能力管理器和连接管理器已初始化")
        except Exception as e:
            logger.warning(f"能力管理器初始化失败 (非致命): {e}")
            self.capability_manager = None
            self.connection_manager = None
        
    # -- PR-DEVICE-RESOLUTION: observe-only resolution tracing ----------------

    async def _observe_node_resolutions(self) -> None:
        """Observe-only: record node-to-device mappings before startup.

        Reads the device_node_map.yaml, finds all mappings for nodes that
        are about to be started, and records them to the activation registry.
        This does NOT alter which nodes are started; it only creates an
        audit trail for diagnostics.
        """
        import time
        from core.device_activation_registry import get_registry as get_act_registry
        from core.device_node_resolver import DeviceNodeResolver

        t0 = time.perf_counter()
        registry = get_act_registry()
        resolver = DeviceNodeResolver()
        resolver._ensure_loaded()

        # Get the set of nodes that will be started
        if hasattr(self.node_launcher, 'get_core_nodes'):
            nodes_to_start = set(self.node_launcher.get_core_nodes())
        else:
            nodes_to_start = set()

        # Find all mappings that reference these nodes
        for mapping in resolver._mappings:
            impl = mapping.get("implementation", {})
            node_name = impl.get("node", "")
            if node_name not in nodes_to_start:
                continue

            match = mapping.get("match", {})
            device_type = match.get("device_type")
            transport = match.get("transport")
            capabilities = match.get("capabilities", [])

            # Build a pseudo-ResolvedMapping for recording
            from core.device_node_resolver import (
                CapabilityProfile, NodeImplementation, ResolvedMapping,
            )
            from core.activation_policy import (
                ActivationDecision, ActivationPolicy, ActivationPolicyEngine,
            )

            node_impl = NodeImplementation(
                node=node_name,
                transport=impl.get("transport", "unknown"),
                port=impl.get("port", 0),
                startup=impl.get("startup", "unknown"),
                healthcheck=impl.get("healthcheck", ""),
                note=mapping.get("note", ""),
            )
            caps = CapabilityProfile(
                provides=mapping.get("capabilities", {}).get("provides", []),
                requires=mapping.get("capabilities", {}).get("requires", []),
            )
            resolved = ResolvedMapping(
                match_type=list(match.keys())[0] if match else "unknown",
                match_key=str(list(match.values())[0]) if match else "unknown",
                implementation=node_impl,
                capabilities=caps,
            )

            # Evaluate activation policy for recording
            engine = ActivationPolicyEngine()
            decision = engine.evaluate(
                node_impl,
                ActivationPolicyEngine.TRIGGER_BOOT,
            )

            registry.record_resolution(
                device_type=device_type,
                transport=transport,
                capabilities=capabilities if not device_type and not transport else None,
                result=resolved,
                decision=decision,
                source_event="boot",
                source_module="unified_launcher._observe_node_resolutions",
                duration_ms=(time.perf_counter() - t0) * 1000,
            )

        logger.info(
            "[DeviceResolution] Observed %d node mappings in %.1fms",
            len(nodes_to_start), (time.perf_counter() - t0) * 1000,
        )

    async def ensure_docker_infra(self) -> tuple:
        """后台静默拉起 Docker 基础设施(NATS/Redis/Qdrant/Neo4j/Mongo)，让依赖它们的节点可用。

        尽力而为、不阻塞事件循环、不因失败中断启动：
        - ``GALAXY_AUTO_DOCKER=0/false/off`` → 跳过（默认 ``auto`` = Docker 存在即拉起）。
        - Docker CLI 不存在 → 返回安装指引并跳过（安装 Docker 需管理员/重启，
          无法可靠静默完成，不在此尝试）。
        - Docker 已装但守护未运行 → 尝试启动 Docker Desktop/daemon 并轮询等待。
        - 守护就绪 → ``docker compose up -d`` 指定的基础设施服务（不含 galaxy 应用本身、
          也不含 ollama 以免与本地 Ollama 端口冲突），输出写 ``logs/docker.log``。
          镜像已就绪 → 秒级拉起（本轮节点即可连上）；首次需下载 → 放后台（本轮先跳过
          依赖节点，下次启动即生效）。

        Returns:
            ``(status, value, note)`` —— status ∈ {"ok","warn"}（渲染图标）；value 是右侧
            一行摘要；note 是可选的下一步提示（仅 -v 详细模式展示）。由 ``start()`` 折叠成
            单行渲染。任何分支都非致命。
        """
        import shutil
        import subprocess as sp
        import time as _time

        flag = os.environ.get("GALAXY_AUTO_DOCKER", "auto").strip().lower()
        if flag in ("0", "false", "no", "off"):
            return ("warn", "已禁用 (GALAXY_AUTO_DOCKER=0)", "")

        docker = shutil.which("docker")
        if not docker:
            return ("warn", "未安装 — 依赖基础设施的节点将跳过（不影响桌面）",
                    "启用全部节点：装 Docker 后重跑 — https://docs.docker.com/get-docker/")

        compose_file = PROJECT_ROOT / "docker-compose.yml"
        if not compose_file.exists():
            return ("warn", "docker-compose.yml 缺失 — 跳过 Docker 基础设施", "")

        # 仅基础设施后端；排除 galaxy/galaxy-gateway(应用本身) 与 ollama(避免与本地 Ollama 冲突)。
        services = ["nats", "redis", "qdrant", "neo4j", "mongodb"]

        def _run(cmd, timeout=None):
            return sp.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)

        def _daemon_up() -> bool:
            try:
                return _run([docker, "info"], timeout=15).returncode == 0
            except Exception:
                return False

        def _compose_base():
            try:
                if _run([docker, "compose", "version"], timeout=15).returncode == 0:
                    return [docker, "compose"]
            except Exception:
                pass
            dc = shutil.which("docker-compose")
            return [dc] if dc else None

        def _bring_up():
            if not _daemon_up():
                _try_start_docker_daemon(docker)
                deadline = _time.time() + float(os.environ.get("GALAXY_AUTO_DOCKER_DAEMON_WAIT", "60"))
                while _time.time() < deadline:
                    if _daemon_up():
                        break
                    _time.sleep(3)
                if not _daemon_up():
                    return ("daemon_down", None)
            base = _compose_base()
            if not base:
                return ("no_compose", None)
            log_dir = PROJECT_ROOT / "logs"
            log_dir.mkdir(exist_ok=True)
            logf = open(log_dir / "docker.log", "ab")
            cmd = base + ["-f", str(compose_file), "up", "-d"] + services
            logf.write(f"\n== docker infra up: {cmd} ==\n".encode("utf-8", "replace"))
            logf.flush()
            proc = sp.Popen(cmd, cwd=str(PROJECT_ROOT), stdout=logf, stderr=sp.STDOUT)
            wait_s = float(os.environ.get("GALAXY_AUTO_DOCKER_WAIT", "90"))
            try:
                proc.wait(timeout=wait_s)
                return ("up", proc.returncode)
            except sp.TimeoutExpired:
                return ("pulling", None)  # 首次拉镜像，留后台继续

        status, rc = await asyncio.to_thread(_bring_up)
        if status == "up" and rc == 0:
            return ("ok", "nats / redis / qdrant / neo4j / mongodb 已就绪", "")
        if status == "pulling":
            return ("warn", "首次镜像下载中（后台）",
                    "进度见 logs/docker.log；本轮先跳过依赖节点，下次启动即生效")
        if status == "daemon_down":
            return ("warn", "守护未能自动启动 — 手动启动 Docker Desktop 后重跑", "")
        if status == "no_compose":
            return ("warn", "未找到 docker compose 命令 — 跳过", "")
        return ("warn", f"启动异常 (rc={rc})，详情见 logs/docker.log", "")

    async def start_electron(self) -> bool:
        """启动 Electron 桌面三态覆盖层。"""
        import shutil
        import subprocess as sp
        electron_dir = Path("electron")
        if not electron_dir.exists():
            logger.warning("electron/ directory not found")
            return False
        # PR-NPM-FIX: npm must be resolved BEFORE the if block so it's always available
        npm = shutil.which("npm")
        if not npm:
            logger.warning("npm not found in PATH")
            return False
        # Ensure npm deps
        if not (electron_dir / "node_modules").exists():
            print_status_row("首次启动：安装 Electron 桌面层依赖 (npm install，可能数分钟)…", status="success")
            try:
                _r = sp.run([npm, "install"], cwd=str(electron_dir),
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
                if _r.returncode != 0:
                    logger.error(
                        "Electron npm install 失败 (rc=%s):\n%s",
                        _r.returncode, (_r.stderr or _r.stdout or "")[-1000:],
                    )
                    return False
            except Exception as exc:
                logger.error("Electron npm install 异常: %s", exc)
                return False
        # Start Electron — PR-ABSOLUTE-PATH: use absolute paths on Windows
        try:
            env = os.environ.copy()
            env["PATH"] = str(Path(npm).parent) + os.pathsep + env.get("PATH", "")
            # 显式把【真实的网关端口】告诉 Electron，避免它只能猜默认 9000：若后端实际监听端口
            # 与 9000 不一致（config 覆盖等），main.js 的 GATEWAY_BASE 会指错口子 → 感知帧/配置
            # 等 fetch 全部「fetch failed」。这里把 web_ui_port 同步给 Electron，从根上消除端口错配。
            env["GALAXY_GATEWAY_PORT"] = str(self.config.web_ui_port)
            env.setdefault("PORT", str(self.config.web_ui_port))
            # GPU 自适应：默认让 Electron 走硬件加速（有独显的机器更流畅）。若 watch_processes
            # 检测到 GPU 模式反复崩溃，会置 _electron_force_software=True，这里注入
            # GALAXY_ELECTRON_GPU=0 → main.js 据此 disableHardwareAcceleration（软件渲染兜底）。
            if getattr(self, "_electron_force_software", False):
                env["GALAXY_ELECTRON_GPU"] = "0"
            # Prefer the locally-installed electron binary — robust and avoids the
            # `npm electron .` bug (invalid command) that hit when npx was absent.
            # CRITICAL: use ABSOLUTE paths for both the binary and the app dir.
            # 之前用相对路径 electron\node_modules\.bin\electron.cmd，而 Popen 的 cwd=electron，
            # 系统会按 electron\electron\... 解析 → "The system cannot find the path specified."
            # → Electron 根本起不来、闪退循环。绝对路径彻底消除该 cwd 相对解析歧义。
            app_dir = electron_dir.resolve()
            bin_name = "electron.cmd" if os.name == "nt" else "electron"
            local_electron = (app_dir / "node_modules" / ".bin" / bin_name)
            if local_electron.exists():
                cmd = [str(local_electron), str(app_dir)]
            else:
                npx = shutil.which("npx")
                cmd = ([npx, "electron", str(app_dir)] if npx
                       else [npm, "exec", "--", "electron", str(app_dir)])
            # Capture Electron stdout/stderr to logs/electron.log so crashes are
            # diagnosable (previously DEVNULL-swallowed → impossible to debug the
            # "exited, restarting" loop / why Ctrl+Space overlay never appears).
            _log_dir = Path("logs")
            _log_dir.mkdir(exist_ok=True)
            _elog = open(_log_dir / "electron.log", "ab")
            _elog.write(
                f"\n===== electron start {__import__('datetime').datetime.now().isoformat()} "
                f"cmd={cmd} =====\n".encode("utf-8", "replace")
            )
            _elog.flush()
            self.electron_proc = sp.Popen(
                cmd,
                cwd=str(app_dir),
                stdout=_elog, stderr=sp.STDOUT,
                env=env,
            )
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
        if os.environ.get("GALAXY_DESKTOP_SHELL", "").strip().lower() == "electron":
            return False  # 显式强制 Electron
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
            logger.info(
                "Tauri 壳未构建（desktop-tauri 无二进制），回退 Electron。"
                "构建一次即自动优先用它：cd desktop-tauri/src-tauri && cargo build --release"
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
            # 复用同一份 logs/electron.log（托盘「三态动画日志」就打开它），便于一处看壳层日志。
            _tlog = open(_log_dir / "electron.log", "ab")
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
            self._desktop_shell = "tauri"
            return True
        except Exception as exc:
            logger.error("Tauri 壳启动失败，回退 Electron: %s", exc)
            return False

    async def start_desktop_shell(self) -> bool:
        """统一桌面壳入口：优先 Tauri（轻量），未构建/失败则回退 Electron。"""
        if await self.start_tauri():
            return True
        self._desktop_shell = "electron"
        return await self.start_electron()

    async def start_system_tray(self) -> bool:
        """启动系统托盘（右下角），与 Electron 解耦、常驻于本启动器进程。

        以前托盘由 Electron `spawn('python -m windows_service.tray_icon')` 拉起，
        Electron 崩溃/重启就把托盘也带没了。现在在 Python 启动器自身进程的后台线程里
        启动（start_tray_in_thread 内部 run_detached），后端存活期间托盘一直在。
        缺 pystray/Pillow 时优雅降级（非致命）。
        """
        try:
            from windows_service.tray_icon import start_tray_in_thread
            tray = await asyncio.to_thread(start_tray_in_thread)
            if tray is not None:
                self._tray = tray
                return True
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
        restarts: list = []          # 最近 60s 窗口内的重启时间戳
        MAX_GPU = 3                  # GPU 模式连续崩溃达此数 → 切软件渲染
        MAX_SW = 5                   # 软件渲染也崩到此数 → 放弃
        gave_up = False
        if not hasattr(self, "_electron_force_software"):
            self._electron_force_software = False
        while True:
            await asyncio.sleep(5)
            proc = getattr(self, 'electron_proc', None)
            if not proc or proc.poll() is None or gave_up:
                continue              # 未启动 / 仍在运行 / 已放弃
            now = time.time()
            restarts = [t for t in restarts if now - t < 60]

            # GPU 模式反复崩溃 → 自动降级为软件渲染（自适应核心）
            if (not self._electron_force_software) and len(restarts) >= MAX_GPU:
                self._electron_force_software = True
                restarts = []
                logger.warning(
                    "Electron GPU 模式 60s 内崩溃 %d 次，自动切换为软件渲染重试"
                    "（你的显卡/驱动可能不支持透明窗口 GPU 合成；详情见 logs/electron.log）…",
                    MAX_GPU,
                )
                await self.start_desktop_shell()
                continue

            # 软件渲染也反复崩溃 → 放弃
            if self._electron_force_software and len(restarts) >= MAX_SW:
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
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "语音交互未启动(缺依赖? 装一下: pip install faster-whisper edge-tts sounddevice): %s",
                exc,
            )
            return False

    async def select_and_start_brain(self):
        """Phase 5：先选主脑（硬件推荐 + 手动选，放第 5 步而非开头），再启动本地大脑。"""
        import asyncio as _asyncio
        # 选择主脑：交互 input 放线程，避免阻塞事件循环。env(OLLAMA_MODEL)/已保存优先，
        # 否则按硬件推荐 + 让用户手动选（见 core.model_selection）。
        try:
            from core import model_selection as ms
            chosen = await _asyncio.to_thread(ms.resolve_main_brain, True)
            if chosen:
                ms.background_pull(chosen)  # 本地缺失则后台 ollama pull
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
        # 启动本地大脑（LocalBrainManager 读 OLLAMA_MODEL 作主脑）
        await self.start_local_brain()

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
        phases_state: List[Tuple[str, str]] = []  # (阶段名, 状态) → 末尾总结卡用

        def _emit(name: str, value: str, status: str,
                  details: Optional[List[Tuple[str, str, str]]] = None) -> None:
            """记录并渲染一个阶段：默认折叠成一行；-v 时打印小标题 + 逐项明细。"""
            phases_state.append((name, status))
            if verbose:
                r.section(name)
                for label, val, st in (details or [(name, value, status)]):
                    r.detail(label, val, st)
            else:
                r.phase(name, value, status)

        if not verbose:
            print()  # banner 与折叠阶段行之间留一行呼吸

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

        # ── 基础设施 (Docker，自动拉起；依赖它的节点才能起来) ──
        try:
            d_status, d_value, d_note = await self.ensure_docker_infra()
        except Exception as exc:
            d_status, d_value, d_note = "warn", "基础设施启动异常（非致命）", ""
            logger.warning("ensure_docker_infra failed: %s", exc)
        d_details = [("Docker 基础设施", d_value, d_status)]
        if d_note:
            d_details.append(("下一步", d_note, "info"))
        _emit("基础设施 · Docker", d_value, d_status, details=d_details)

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
            st = "ok" if healthy else "warn"
            _emit("AI 大脑", f"{bm}  ·  {hw}", st, details=[
                ("Ollama 推理服务", "就绪" if healthy else "未就绪（检查 ollama 是否运行）",
                 "ok" if healthy else "fail"),
                ("AI 主脑模型", bm, "ok"),
                ("已安装模型", shown, "ok" if avail else "warn"),
                ("硬件", hw, "ok"),
            ])
        except Exception as exc:
            _emit("AI 大脑", "启动失败", "fail")
            logger.error(f"Local brain: {exc}")

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
        _emit(
            "语音交互",
            ("已开启 · 直接对它说话即可（三态随对话变化）" if voice_ok
             else "未启用 — pip install faster-whisper edge-tts sounddevice 后重启"),
            "ok" if voice_ok else "warn",
        )

        # ── 总结卡：状态 + 关键入口 + 降级项 + 下一步 ──
        ok_n = sum(1 for _, s in phases_state if s == "ok")
        degraded_names = [n for n, s in phases_state if s in ("warn", "fail")]
        r.summary_card(
            title="Galaxy L4 · v2.3.21",
            state_ok=ok_n,
            state_degraded=len(degraded_names),
            rows=[
                ("面板", f"http://localhost:{port}"),
                ("文档", f"http://localhost:{port}/docs"),
                ("唤醒", "Ctrl+Alt+Space    隐藏 Ctrl+Alt+H"),
                ("日志", "托盘 →「三态动画日志」"),
            ],
            degraded=degraded_names or None,
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
            if loop.is_running():
                asyncio.ensure_future(async_shutdown())
            else:
                loop.run_until_complete(async_shutdown())
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
        
        print(f"\n{Colors.BOLD}LLM API:{Colors.ENDC}")
        for api, configured in status["llm_apis"].items():
            icon = "✅" if configured else "❌"
            print(f"  {icon} {api.upper()}")
            
        print(f"\n{Colors.BOLD}数据库:{Colors.ENDC}")
        for db, configured in status["database"].items():
            icon = "✅" if configured else "❌"
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

    PR-ELECTRON-DEDUP: PID file lock prevents duplicate launches when both
    Phase 6 (system_orchestrator) and unified_launcher try to start Electron.
    Phase 6 writes the lock first; this function exits if lock exists + alive.
    """
    import os
    import subprocess
    import sys

    if os.environ.get("GALAXY_SKIP_ELECTRON", "").lower() in ("1", "true", "yes"):
        return

    project_root = os.path.dirname(os.path.abspath(__file__))
    electron_dir = os.path.join(project_root, "electron")

    if not os.path.isdir(electron_dir):
        return
    if not os.path.isdir(os.path.join(electron_dir, "node_modules")):
        return

    # PR-ELECTRON-DEDUP: PID file lock
    pid_file = os.path.join(project_root, ".electron.pid")
    if os.path.exists(pid_file):
        try:
            with open(pid_file) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)  # raises OSError if process is dead
            print("[Launcher] Electron already running (pid=%d)" % pid)
            return
        except (OSError, ValueError):
            os.remove(pid_file)  # stale lock

    # PR-ABSOLUTE-PATH: use shutil.which to find npm — works even when not in PATH
    import shutil
    npm_path = shutil.which("npm")
    if not npm_path:
        print("[Launcher] npm not found — skip Electron")
        return
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
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
        with open(pid_file, "w") as f:
            f.write(str(proc.pid))
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

    # 启动系统 — register async signal handlers inside the running loop
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.add_signal_handler(signal.SIGINT, _graceful_shutdown)
        loop.add_signal_handler(signal.SIGTERM, _graceful_shutdown)
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
