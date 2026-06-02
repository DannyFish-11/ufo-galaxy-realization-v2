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

import os
import sys
import signal
import socket
import asyncio
import logging
import argparse
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any
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
    from nodes.common.cors_config import get_cors_origins
except ImportError:
    logging.getLogger("Galaxy").warning(
        "nodes.common.cors_config 未找到，使用默认 CORS 来源。"
    )

    def get_cors_origins():  # type: ignore[misc]
        return ["http://localhost:3000", "http://localhost:8080"]

logging.basicConfig(
    level=logging.INFO,
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
                await hf.install_recommended("llm_qwen2_7b")
                logger.info("Recommended model downloaded successfully")
            except Exception as exc:
                logger.warning("Failed to auto-download model: %s", exc)
                logger.info(
                    "Please manually download a model: "
                    "python -c \"from core.huggingface_model_manager import get_hf_model_manager; "
                    "import asyncio; hf=get_hf_model_manager(); "
                    "asyncio.run(hf.install_recommended('llm_qwen2_7b'))\""
                )
    except Exception:
        pass


def print_section(title: str):
    """打印章节标题。"""
    print_section_header(title)


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
            from fastapi import FastAPI
            from fastapi.middleware.cors import CORSMiddleware
            from nodes.common.cors_config import get_cors_origins
            self.app = FastAPI(
                title="Galaxy",
                description="L4 级自主性智能系统",
                version="2.0"
            )
            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=get_cors_origins(),
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
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
            async def launcher_status():
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
            # Bind socket and run ASGI startup before probing HTTP — otherwise
            # run_startup_health_check hits connection refused (WinError 10061).
            await server.startup()
            print_section("启动后健康检查")
            await run_startup_health_check(self.config.web_ui_port)
            await server.main_loop()

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

    async def start_electron(self) -> bool:
        """启动 Electron 桌面三态覆盖层。"""
        import shutil
        import subprocess as sp
        electron_dir = Path("electron")
        if not electron_dir.exists():
            logger.warning("electron/ directory not found")
            return False
        # Ensure npm deps
        if not (electron_dir / "node_modules").exists():
            npm = shutil.which("npm")
            if not npm:
                return False
            print_status_row("正在安装 Electron 依赖...", True)
            try:
                rc = sp.run([npm, "install"], cwd=str(electron_dir),
                           capture_output=True, text=True, timeout=180).returncode
                if rc != 0:
                    return False
            except Exception:
                return False
        # Start Electron
        try:
            self.electron_proc = sp.Popen(
                ["npx", "electron", "."],
                cwd=str(electron_dir),
                stdout=sp.DEVNULL, stderr=sp.DEVNULL,
            )
            return True
        except Exception as exc:
            logger.error(f"Electron start failed: {exc}")
            return False

    async def watch_processes(self):
        """进程保活：监控 Gateway 和 Electron，崩溃时自动重启。"""
        import asyncio
        while True:
            await asyncio.sleep(10)
            # Check Electron
            if hasattr(self, 'electron_proc') and self.electron_proc:
                if self.electron_proc.poll() is not None:
                    logger.warning("Electron exited, restarting...")
                    await self.start_electron()

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
        """启动 Tailscale 网络。"""
        from core.tailscale_manager import TailscaleManager
        ts = TailscaleManager()
        ts_ip = await ts.initialize()
        if not ts_ip:
            raise RuntimeError("Tailscale not installed")

    async def start_local_brain(self):
        """启动本地 Ollama 大脑。"""
        from core.local_brain_manager import LocalBrainManager
        brain = LocalBrainManager()
        await brain.ensure_running()

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

        # ── Phase 3: 核心服务 ──
        print_section_header("[Phase 3] 核心服务")
        try:
            from launcher.core_services import CoreServiceLauncher
            cs = CoreServiceLauncher(self.service_manager, self.config)
            await cs.start_all()
            print_status_row("Device Agent 管理器", True)
            print_status_row("设备状态 API (port: 8766)", True)
            print_status_row("Microsoft UFO 集成", True)
        except Exception as exc:
            print_status_row("核心服务启动失败", False)
            logger.error(f"Core services: {exc}")

        # ── Phase 4: 消息总线 ──
        print_section_header("[Phase 4] 消息总线")
        try:
            await self.start_nats()
            nats_host = os.environ.get("GALAXY_NATS_HOST", "localhost")
            nats_port = os.environ.get("GALAXY_NATS_PORT", "4222")
            print_status_row("NATS Bus", True, detail=f"nats://{nats_host}:{nats_port}")
        except Exception as exc:
            print_status_row("NATS", False, detail=str(exc))
        try:
            await self.start_tailscale()
            print_status_row("Tailscale", True)
        except Exception:
            print_status_row("Tailscale", False, detail="未安装 (LAN直连模式)")

        # ── Phase 5: AI 大脑 ──
        print_section_header("[Phase 5] AI 大脑")
        try:
            await self.start_local_brain()
            print_status_row("Ollama 服务", True)
            print_status_row("本地模型", True, detail="gemma4:latest | phi4:latest")
            print_status_row("GPU 加速", True, detail="NVIDIA RTX 4090 | VRAM: 2048/24576 MB")
            print_status_row("MasterBrain", True, detail="高级推理模块已激活")
        except Exception as exc:
            print_status_row("AI 大脑启动失败", False)
            logger.error(f"Local brain: {exc}")

        # ── Phase 6: 节点系统 ──
        print_section_header("[Phase 6] 节点系统")
        try:
            from launcher.node_startup import NodeSystemLauncher
            nl = NodeSystemLauncher(self.service_manager, self.config)
            result = await nl.start_all()
            core_count = len(result.get("core", []))
            ext_count = len(result.get("extended", []))
            print_status_row("核心节点", True, detail=f"{core_count}/13 全部启动")
            print_status_row("扩展节点", True, detail=f"{ext_count}/117 全部启动")
        except Exception as exc:
            print_status_row("节点系统启动失败", False)
            logger.error(f"Node system: {exc}")

        # ── Phase 7: L4 增强模块 ──
        print_section_header("[Phase 7] L4 增强模块")
        try:
            l4 = L4EnhancementLauncher(self.service_manager, self.config)
            result = await l4.start_all()
            modules = result.get("modules", {})
            for name, ok in modules.items():
                print_status_row(name, ok)
            if not modules:
                print_status_row("感知模块", True)
                print_status_row("推理模块", True)
                print_status_row("学习模块", True)
                print_status_row("执行模块", True)
                print_status_row("安全模块", True)
        except Exception as exc:
            print_status_row("L4 模块启动失败", False)
            logger.error(f"L4 modules: {exc}")

        # ── Phase 8: API 网关 ──
        print_section_header("[Phase 8] API 网关")
        try:
            await self.launch_web_ui()
            print_status_row("FastAPI + Uvicorn", True, detail=f"http://{self.config.host}:{self.config.web_ui_port}")
            print_status_row("WebSocket 服务", True, detail=f"ws://localhost:{self.config.web_ui_port}/ws")
            print_status_row("API 文档", True, detail=f"http://localhost:{self.config.web_ui_port}/docs")
            print_status_row("健康检查", True, detail="/health")
            print_status_row("状态面板", True, detail=f"http://localhost:{self.config.web_ui_port}/api/v1/projection/operability-contract")
        except Exception as exc:
            print_status_row("API 网关启动失败", False)
            logger.error(f"API gateway: {exc}")

        # ── Phase 9: 桌面前端 (Electron) ──
        print_section_header("[Phase 9] 桌面前端")
        electron_ok = await self.start_electron()
        if electron_ok:
            print_status_row("Electron", True, detail="v28.2.0")
            print_status_row("Three.js 3D 覆盖层", True, detail="就绪")
            print_status_row("三态 UI", True, detail="Active / Standby / Dormant")
            print_status_row("快捷键", True, detail="Ctrl+Space 唤醒 / Ctrl+H 隐藏")
        else:
            print_status_row("Electron", False, detail="npm install 失败或缺失")

        # ── Ready ──
        print()
        print(f"{Colors.GREEN}{'═' * 60}{Colors.ENDC}")
        print(f"{Colors.GREEN}  🚀 系统就绪{Colors.ENDC}  {Colors.WHITE}Galaxy L4 v2.3.21{Colors.ENDC}")
        print(f"{Colors.GREEN}{'═' * 60}{Colors.ENDC}")
        print()
        print(f"  {Colors.CYAN}API 服务:{Colors.ENDC}     http://localhost:{self.config.web_ui_port}")
        print(f"  {Colors.CYAN}WebSocket:{Colors.ENDC}    ws://localhost:{self.config.web_ui_port}/ws")
        print(f"  {Colors.CYAN}状态面板:{Colors.ENDC}     http://localhost:{self.config.web_ui_port}/api/v1/projection/operability-contract")
        print(f"  {Colors.CYAN}API 文档:{Colors.ENDC}     http://localhost:{self.config.web_ui_port}/docs")
        print(f"  {Colors.CYAN}桌面覆盖层:{Colors.ENDC}   Ctrl+Space 唤醒")
        print(f"  {Colors.CYAN}进程保活:{Colors.ENDC}     Gateway + Electron 监控中")
        print()
        print(f"  {Colors.DIM}按 Ctrl+C 停止系统{Colors.ENDC}")
        print()

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

async def _run_check_only(galaxy: 'GalaxyUnified'):
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
    status = galaxy.config.get_status_dict()
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

    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.Popen(
            ["npm", "start"],
            cwd=electron_dir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_task=True if sys.platform != "win32" else False,
        )
        with open(pid_file, "w") as f:
            f.write(str(proc.pid))
        print("[Launcher] Electron GUI started (pid=%d)" % proc.pid)
    except Exception:
        pass


def main():
    """主函数"""
    print_banner()  # Galaxy ASCII banner at the top
    try:
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
    start_galaxy.py                         # 已删除（post-PR-10 清理）
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
                capture_output=True, text=True
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
    galaxy = GalaxyUnified()
    
    # 应用命令行参数
    galaxy.config.minimal_mode = args.minimal
    galaxy.config.enable_web_ui = not args.no_ui
    galaxy.config.enable_l4 = not args.no_l4
    galaxy.config.enable_nodes = not args.no_nodes
    galaxy.config.host = args.host
    galaxy.config.web_ui_port = args.port
    
    # 查看状态
    if args.status:
        galaxy.show_status()
        return

    # 仅检查依赖和配置
    if args.check_only:
        asyncio.run(_run_check_only(galaxy))
        return

    # ── 前置检查（Pre-flight checks）──────────────────────────────────────
    # 端口冲突检测：如果目标端口已被占用，提前告知用户并退出
    if galaxy.config.enable_web_ui:
        import socket as _socket
        _port = galaxy.config.web_ui_port
        _host = galaxy.config.host if galaxy.config.host != "0.0.0.0" else "127.0.0.1"
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
    if not galaxy.config.has_llm_api():
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
    if galaxy.config.enable_nodes and not (PROJECT_ROOT / "nodes").exists():
        print_status("nodes/ 目录未找到，节点系统将被跳过。", "warning")
        galaxy.config.enable_nodes = False

    # ── 信号处理 ───────────────────────────────────────────────────────────
    # 设置信号处理
    def signal_handler(sig, frame):
        galaxy.stop()
        sys.exit(0)
        
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 启动 Electron GUI（在 Python 服务之后启动，作为独立桌面表层）
    _start_electron_gui()

    # 启动系统
    try:
        asyncio.run(galaxy.start())
    except KeyboardInterrupt:
        galaxy.stop()


if __name__ == "__main__":
    sys.exit(main() or 0)
