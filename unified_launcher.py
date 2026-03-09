#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy - 统一启动器
======================

融合性整合所有模块的统一入口：
1. 核心服务层（Device Agent、设备状态、UFO 集成）
2. 节点系统（108+ 节点）
3. L4 增强模块（感知、推理、学习、执行）
4. Web UI 和 API 服务

作者：Manus AI
日期：2026-02-06
版本：2.0
"""

import os
import sys
import json
import time
import signal
import asyncio
import logging
import argparse
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
from datetime import datetime

# 设置项目根目录
PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))
from nodes.common.cors_config import get_cors_origins

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("Galaxy")


# ============================================================================
# 终端颜色和打印工具
# ============================================================================

class Colors:
    """终端颜色"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'


def print_banner():
    """打印启动横幅"""
    banner = f"""
{Colors.CYAN}{Colors.BOLD}
    ╔═══════════════════════════════════════════════════════════════════╗
    ║                                                                   ║
    ║     ██╗   ██╗███████╗ ██████╗      ██████╗  █████╗ ██╗      ██╗  ║
    ║     ██║   ██║██╔════╝██╔═══██╗    ██╔════╝ ██╔══██╗██║      ██║  ║
    ║     ██║   ██║█████╗  ██║   ██║    ██║  ███╗███████║██║      ██║  ║
    ║     ██║   ██║██╔══╝  ██║   ██║    ██║   ██║██╔══██║██║      ██║  ║
    ║     ╚██████╔╝██║     ╚██████╔╝    ╚██████╔╝██║  ██║███████╗ ██║  ║
    ║      ╚═════╝ ╚═╝      ╚═════╝      ╚═════╝ ╚═╝  ╚═╝╚══════╝ ╚═╝  ║
    ║                                                                   ║
    ║                  L4 级自主性智能系统 v2.0                         ║
    ║                     统一融合版                                    ║
    ║                                                                   ║
    ╚═══════════════════════════════════════════════════════════════════╝
{Colors.ENDC}
    """
    print(banner)


def print_status(message: str, status: str = "info"):
    """打印状态信息"""
    icons = {
        "info": f"{Colors.BLUE}ℹ️ ",
        "success": f"{Colors.GREEN}✅",
        "warning": f"{Colors.YELLOW}⚠️ ",
        "error": f"{Colors.RED}❌",
        "loading": f"{Colors.CYAN}⏳",
        "step": f"{Colors.CYAN}▶ ",
    }
    icon = icons.get(status, icons["info"])
    print(f"{icon} {message}{Colors.ENDC}")


def print_section(title: str):
    """打印章节标题"""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'═' * 60}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.CYAN}  {title}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'═' * 60}{Colors.ENDC}\n")


# ============================================================================
# 系统状态枚举
# ============================================================================

class SystemState(Enum):
    """系统状态"""
    INITIALIZING = auto()
    LOADING_CONFIG = auto()
    STARTING_CORE = auto()
    STARTING_NODES = auto()
    STARTING_L4 = auto()
    STARTING_UI = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()
    ERROR = auto()


class ServiceType(Enum):
    """服务类型"""
    CORE = "core"           # 核心服务
    NODE = "node"           # 节点
    L4 = "l4"               # L4 增强
    API = "api"             # API 服务
    UI = "ui"               # UI 服务


# ============================================================================
# 配置管理
# ============================================================================

@dataclass
class SystemConfig:
    """系统配置"""
    # API 配置
    openai_api_key: str = ""
    gemini_api_key: str = ""
    openrouter_api_key: str = ""
    xai_api_key: str = ""
    deepseek_api_key: str = ""
    anthropic_api_key: str = ""
    
    # 数据库配置
    database_url: str = ""
    redis_url: str = ""
    qdrant_url: str = ""
    
    # 服务配置（默认值从 PortConfig 读取，回退到硬编码值）
    host: str = "0.0.0.0"
    web_ui_port: int = 8080
    device_api_port: int = 8766
    ufo_api_port: int = 8767

    def __post_init__(self):
        """从 PortConfig 加载端口默认值（如果可用）"""
        try:
            from core.port_config import get_service_port
            if self.web_ui_port == 8080:
                self.web_ui_port = get_service_port("dashboard_backend")
            if self.device_api_port == 8766:
                self.device_api_port = get_service_port("device_api")
            if self.ufo_api_port == 8767:
                self.ufo_api_port = get_service_port("ufo_api")
        except Exception:
            pass
    
    # 启动选项
    enable_l4: bool = True
    enable_nodes: bool = True
    enable_web_ui: bool = True
    enable_device_api: bool = True
    minimal_mode: bool = False
    
    @classmethod
    def load_from_env(cls) -> 'SystemConfig':
        """从环境变量加载配置"""
        config = cls()
        
        # 加载 .env 文件
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        os.environ[key.strip()] = value.strip()
        else:
            logger.warning(
                ".env file not found. Copy .env.example to .env and configure: "
                "cp .env.example .env"
            )
        
        # 从环境变量读取
        config.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
        config.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
        config.openrouter_api_key = os.environ.get("OPENROUTER_API_KEY", "")
        config.xai_api_key = os.environ.get("XAI_API_KEY", "")
        config.deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        config.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        config.database_url = os.environ.get("DATABASE_URL", "")
        config.redis_url = os.environ.get("REDIS_URL", "")
        config.qdrant_url = os.environ.get("QDRANT_URL", "")
        
        return config
    
    def _get_tailscale_ip(self) -> Optional[str]:
        """获取 Tailscale IPv4 地址"""
        try:
            import shutil
            tailscale_bin = shutil.which("tailscale")
            if not tailscale_bin:
                return None
            
            result = subprocess.run(
                [tailscale_bin, "ip", "-4"], 
                capture_output=True, 
                text=True, 
                timeout=1
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def has_llm_api(self) -> bool:
        """检查是否有可用的 LLM API"""
        return any([
            self.openai_api_key,
            self.gemini_api_key,
            self.openrouter_api_key,
            self.xai_api_key,
            self.deepseek_api_key,
            self.anthropic_api_key,
        ])
    
    def get_status_dict(self) -> Dict[str, Any]:
        """获取状态字典"""
        return {
            "llm_apis": {
                "openai": bool(self.openai_api_key),
                "gemini": bool(self.gemini_api_key),
                "openrouter": bool(self.openrouter_api_key),
                "xai": bool(self.xai_api_key),
                "deepseek": bool(self.deepseek_api_key),
                "anthropic": bool(self.anthropic_api_key),
            },
            "database": {
                "postgresql": bool(self.database_url),
                "redis": bool(self.redis_url),
                "qdrant": bool(self.qdrant_url),
            },
            "services": {
                "web_ui": self.enable_web_ui,
                "device_api": self.enable_device_api,
                "l4_enabled": self.enable_l4,
            },
            "network": {
                "tailscale_ip": self._get_tailscale_ip()
            }
        }


# ============================================================================
# 服务管理器
# ============================================================================

@dataclass
class ServiceInfo:
    """服务信息"""
    name: str
    service_type: ServiceType
    status: str = "stopped"
    port: Optional[int] = None
    process: Optional[subprocess.Popen] = None
    start_time: Optional[datetime] = None
    error: Optional[str] = None


class ServiceManager:
    """服务管理器 - 统一管理所有服务"""
    
    def __init__(self, config: SystemConfig):
        self.config = config
        self.services: Dict[str, ServiceInfo] = {}
        self.state = SystemState.INITIALIZING
        
    def register_service(self, name: str, service_type: ServiceType, port: Optional[int] = None):
        """注册服务"""
        self.services[name] = ServiceInfo(
            name=name,
            service_type=service_type,
            port=port
        )
        
    async def start_service(self, name: str, command: List[str], cwd: Optional[Path] = None) -> bool:
        """启动服务"""
        if name not in self.services:
            logger.error(f"服务未注册: {name}")
            return False
            
        service = self.services[name]
        
        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd) if cwd else str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
            )
            
            service.process = process
            service.status = "running"
            service.start_time = datetime.now()
            service.error = None
            
            logger.info(f"服务已启动: {name}")
            return True
            
        except Exception as e:
            service.status = "error"
            service.error = str(e)
            logger.error(f"启动服务失败 {name}: {e}")
            return False
            
    def stop_service(self, name: str) -> bool:
        """停止服务"""
        if name not in self.services:
            return False
            
        service = self.services[name]
        
        if service.process:
            try:
                service.process.terminate()
                service.process.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                service.process.kill()
            service.process = None
            
        service.status = "stopped"
        return True
        
    def stop_all(self):
        """停止所有服务"""
        for name in list(self.services.keys()):
            self.stop_service(name)
            
    def get_status(self) -> Dict[str, Any]:
        """获取所有服务状态"""
        return {
            name: {
                "type": service.service_type.value,
                "status": service.status,
                "port": service.port,
                "uptime": (datetime.now() - service.start_time).total_seconds() if service.start_time else 0,
                "error": service.error
            }
            for name, service in self.services.items()
        }


# ============================================================================
# 核心服务启动器
# ============================================================================

class CoreServiceLauncher:
    """核心服务启动器"""
    
    def __init__(self, service_manager: ServiceManager, config: SystemConfig):
        self.service_manager = service_manager
        self.config = config
        
    async def start_device_agent_manager(self) -> bool:
        """启动 Device Agent 管理器"""
        self.service_manager.register_service(
            "device_agent_manager",
            ServiceType.CORE
        )
        
        # 直接导入并初始化
        try:
            from core.device_agent_manager import DeviceAgentManager
            manager = DeviceAgentManager()
            await manager.initialize()
            logger.info("Device Agent 管理器已初始化")
            self.service_manager.services["device_agent_manager"].status = "running"
            return True
        except Exception as e:
            logger.error(f"Device Agent 管理器启动失败: {e}")
            return False
            
    async def start_device_status_api(self) -> bool:
        """启动设备状态 API"""
        self.service_manager.register_service(
            "device_status_api",
            ServiceType.API,
            port=self.config.device_api_port
        )
        
        # 作为子进程启动
        return await self.service_manager.start_service(
            "device_status_api",
            [sys.executable, "-m", "uvicorn", "core.device_status_api:app", 
             "--host", "0.0.0.0", "--port", str(self.config.device_api_port),
             "--log-level", "warning"]
        )
        
    async def start_microsoft_ufo_integration(self) -> bool:
        """启动微软 UFO 集成"""
        self.service_manager.register_service(
            "microsoft_ufo_integration",
            ServiceType.CORE
        )
        
        try:
            from core.microsoft_ufo_integration import GalaxyIntegrationService
            integration = GalaxyIntegrationService()
            result = await integration.initialize()
            # initialize 返回 bool，转换为 dict
            result = {"success": result, "message": "Galaxy Integration initialized" if result else "Galaxy Integration failed"}
            
            if result.get("success"):
                logger.info("微软 UFO 集成已初始化")
                self.service_manager.services["microsoft_ufo_integration"].status = "running"
                return True
            else:
                logger.warning(f"微软 UFO 集成部分可用: {result.get('message')}")
                self.service_manager.services["microsoft_ufo_integration"].status = "partial"
                return True
        except Exception as e:
            logger.error(f"微软 UFO 集成启动失败: {e}")
            return False
            
    async def start_all(self) -> Dict[str, bool]:
        """启动所有核心服务"""
        results = {}
        
        print_status("启动 Device Agent 管理器...", "step")
        results["device_agent_manager"] = await self.start_device_agent_manager()
        
        if self.config.enable_device_api:
            print_status("启动设备状态 API...", "step")
            results["device_status_api"] = await self.start_device_status_api()
            
        print_status("启动微软 UFO 集成...", "step")
        results["microsoft_ufo_integration"] = await self.start_microsoft_ufo_integration()
        
        return results


# ============================================================================
# 节点系统启动器
# ============================================================================

class NodeSystemLauncher:
    """节点系统启动器"""
    
    def __init__(self, service_manager: ServiceManager, config: SystemConfig):
        self.service_manager = service_manager
        self.config = config
        self.nodes_dir = PROJECT_ROOT / "nodes"
        self.node_configs = self._load_node_configs()
        
    def _load_node_configs(self) -> Dict[str, Any]:
        """加载节点配置"""
        config_file = PROJECT_ROOT / "node_dependencies.json"
        if config_file.exists():
            with open(config_file, 'r') as f:
                return json.load(f)
        return {}
        
    def get_core_nodes(self) -> List[str]:
        """获取核心节点列表"""
        core_nodes = []
        for name, config in self.node_configs.items():
            if config.get("group") == "core":
                core_nodes.append(name)
        return sorted(core_nodes, key=lambda x: self.node_configs.get(x, {}).get("priority", 99))
        
    def get_all_nodes(self) -> List[str]:
        """获取所有节点列表"""
        if not self.nodes_dir.exists():
            return []
        return sorted([
            d.name for d in self.nodes_dir.iterdir()
            if d.is_dir() and (d / "main.py").exists()
        ])
        
    async def start_node(self, node_name: str) -> bool:
        """启动单个节点"""
        node_dir = self.nodes_dir / node_name
        main_py = node_dir / "main.py"
        
        if not main_py.exists():
            return False
            
        self.service_manager.register_service(node_name, ServiceType.NODE)
        
        return await self.service_manager.start_service(
            node_name,
            [sys.executable, str(main_py)],
            cwd=node_dir
        )
        
    async def start_nodes(self, nodes: List[str], parallel: bool = True) -> Dict[str, bool]:
        """启动多个节点"""
        results = {}
        
        if parallel:
            tasks = [self.start_node(node) for node in nodes]
            results_list = await asyncio.gather(*tasks, return_exceptions=True)
            for node, result in zip(nodes, results_list):
                results[node] = result is True
        else:
            for node in nodes:
                results[node] = await self.start_node(node)
                await asyncio.sleep(0.05)
                
        return results
        
    async def start_all(self, minimal: bool = False) -> Dict[str, bool]:
        """启动所有节点"""
        if minimal:
            nodes = self.get_core_nodes()[:10]
        else:
            nodes = self.get_core_nodes()
            
        if not nodes:
            logger.warning("未找到核心节点配置")
            return {}
            
        print_status(f"启动 {len(nodes)} 个核心节点...", "step")
        return await self.start_nodes(nodes, parallel=True)


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
        """启动 Web UI 和完整 API 服务"""
        try:
            from fastapi import FastAPI
            from fastapi.responses import HTMLResponse, JSONResponse
            from fastapi.middleware.cors import CORSMiddleware
            import uvicorn
            
            self.app = FastAPI(
                title="Galaxy",
                description="L4 级自主性智能系统",
                version="2.0"
            )
            
            from nodes.common.cors_config import get_cors_origins
            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=get_cors_origins(),
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"]
            )
            
            # === 引导核心子系统（缓存 + 监控 + 性能中间件 + 命令路由 + AI） ===
            try:
                from core.startup import bootstrap_subsystems
                bootstrap_results = await bootstrap_subsystems(self.app, self.config)

                ok = sum(1 for v in bootstrap_results.values() if v.get("status") == "ok")
                total = len(bootstrap_results)
                logger.info(f"核心子系统: {ok}/{total} 正常")
                for name, info in bootstrap_results.items():
                    status_icon = "OK" if info.get("status") == "ok" else "DEGRADED"
                    logger.info(f"  [{status_icon}] {name}: {info}")
            except Exception as e:
                logger.warning(f"核心子系统引导失败（系统仍可运行）: {e}")

            # === 集成完整 API 路由 ===
            try:
                from core.api_routes import create_api_routes, create_websocket_routes

                # 注册 REST API 路由
                api_router = create_api_routes(
                    service_manager=self.service_manager,
                    config=self.config
                )
                self.app.include_router(api_router)
                logger.info("完整 API 路由已加载")

                # 注册 WebSocket 端点
                create_websocket_routes(
                    self.app,
                    service_manager=self.service_manager
                )
                logger.info("WebSocket 端点已加载")

            except ImportError as e:
                logger.warning(f"API 路由模块加载失败，使用基础路由: {e}")

            # === 健康检查路由 ===
            try:
                from core.health_check import create_health_routes
                health_router, health_checker = create_health_routes(
                    service_manager=self.service_manager,
                    config=self.config
                )
                self.app.include_router(health_router)
                logger.info("健康检查路由已加载")
            except ImportError as e:
                logger.warning(f"健康检查模块加载失败: {e}")
            
            # === 静态文件挂载 (API Manager) ===
            from fastapi.staticfiles import StaticFiles
            from fastapi.responses import FileResponse
            
            # 尝试查找正确的静态文件目录
            base_static_dir = PROJECT_ROOT / "static" / "api-manager"
            static_dir = base_static_dir
            
            # 检查是否在 public 子目录下 (适配当前目录结构)
            if (base_static_dir / "public").exists():
                static_dir = base_static_dir / "public"
            
            if static_dir.exists() and (static_dir / "assets").exists():
                # 挂载静态资源
                self.app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")
                
                # API Manager 入口
                @self.app.get("/api-manager", response_class=HTMLResponse)
                async def api_manager_index():
                    index_path = static_dir / "index.html"
                    if index_path.exists():
                        return FileResponse(str(index_path))
                    return JSONResponse({"error": "index.html not found"}, status_code=404)
                
                logger.info(f"API Manager 已挂载: {static_dir}")
            else:
                logger.warning(f"API Manager 静态文件未找到: {static_dir}")

            # === 基础路由（始终可用）===
            @self.app.get("/", response_class=HTMLResponse)
            async def index():
                return self._get_dashboard_html()
                
            @self.app.get("/api/status")
            async def status():
                return JSONResponse({
                    "status": "running",
                    "version": "2.0",
                    "state": self.service_manager.state.name,
                    "services": self.service_manager.get_status(),
                    "config": self.config.get_status_dict()
                })
                
            @self.app.get("/api/services")
            async def services():
                return JSONResponse(self.service_manager.get_status())
            
            @self.app.get("/api/health")
            async def health():
                return {"status": "healthy"}
                
            config = uvicorn.Config(
                self.app,
                host=self.config.host,
                port=self.config.web_ui_port,
                log_level="warning"
            )
            server = uvicorn.Server(config)
            logger.info(f"API 服务启动: http://{self.config.host}:{self.config.web_ui_port}")
            logger.info(f"API 文档: http://localhost:{self.config.web_ui_port}/docs")
            await server.serve()
            
        except ImportError as e:
            logger.error(f"Web UI 依赖未安装: {e}")
            
    def _get_dashboard_html(self) -> str:
        """获取仪表板 HTML — 从 dashboard/frontend/public/ 读取

        优先加载独立 Dashboard 的 index.html（Dynamic Island 设计），
        如果不存在则返回最小化的系统状态页面。
        """
        # 优先使用独立 Dashboard
        dashboard_paths = [
            PROJECT_ROOT / "dashboard" / "frontend" / "public" / "index.html",
            PROJECT_ROOT / "dashboard" / "frontend" / "public" / "index_v2.html",
        ]
        for path in dashboard_paths:
            if path.exists():
                try:
                    return path.read_text(encoding="utf-8")
                except Exception as exc:
                    logger.warning("读取 Dashboard HTML 失败: %s", exc)

        # 回退：从 fallback.html 读取最小化系统状态页面
        fallback_path = PROJECT_ROOT / "dashboard" / "frontend" / "public" / "fallback.html"
        if fallback_path.exists():
            try:
                return fallback_path.read_text(encoding="utf-8")
            except Exception as exc:
                logger.warning("读取 fallback.html 失败: %s", exc)
        return "<html><body><h1>Galaxy System</h1><p>Dashboard unavailable.</p></body></html>"


# NOTE: 495行内联HTML已提取到 dashboard/frontend/public/fallback.html
_REMOVED_HTML_PLACEHOLDER = "extracted"  # noqa: F841

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
        
    async def start(self):
        """启动系统"""
        print_banner()
        
        # 1. 加载配置
        print_section("配置检查")
        self.service_manager.state = SystemState.LOADING_CONFIG
        
        if self.config.has_llm_api():
            print_status("检测到 LLM API 配置", "success")
        else:
            print_status("未检测到 LLM API，将使用模拟模式", "warning")
            
        status = self.config.get_status_dict()
        llm_count = sum(1 for v in status["llm_apis"].values() if v)
        print_status(f"已配置 {llm_count} 个 LLM API", "info")
        
        # ===== 集成：报告能力和连接管理器状态 =====
        if self.capability_manager:
            cap_stats = self.capability_manager.get_stats()
            print_status(f"能力管理器: {cap_stats['total_capabilities']} 个能力已加载", "info")
        
        if self.connection_manager:
            conn_stats = self.connection_manager.get_stats()
            print_status(f"连接管理器: {conn_stats['total_connections']} 个连接已注册", "info")
        
        # 2. 并行启动服务
        print_section("服务启动")
        self.service_manager.state = SystemState.STARTING_CORE
        
        # 定义启动任务
        tasks = []
        
        # 核心服务任务
        async def start_core():
            print_status("正在启动核心服务...", "loading")
            results = await self.core_launcher.start_all()
            success = sum(1 for v in results.values() if v)
            print_status(f"核心服务: {success}/{len(results)} 已启动", 
                        "success" if success == len(results) else "warning")
            return results

        tasks.append(start_core())

        # 节点系统任务
        if self.config.enable_nodes:
            async def start_nodes():
                print_status("正在启动节点系统...", "loading")
                self.service_manager.state = SystemState.STARTING_NODES
                results = await self.node_launcher.start_all(minimal=self.config.minimal_mode)
                success = sum(1 for v in results.values() if v)
                print_status(f"节点: {success}/{len(results)} 已启动", 
                            "success" if success > 0 else "warning")
                return results
            tasks.append(start_nodes())

        # L4 模块任务
        if self.config.enable_l4:
            async def start_l4():
                print_status("正在初始化 L4 模块...", "loading")
                self.service_manager.state = SystemState.STARTING_L4
                results = await self.l4_launcher.start_all()
                success = sum(1 for v in results.values() if v)
                print_status(f"L4 模块: {success}/{len(results)} 已初始化", 
                            "success" if success == len(results) else "warning")
                return results
            tasks.append(start_l4())

        # 并行执行所有启动任务
        await asyncio.gather(*tasks)
        
        # 5. 启动 Web UI
        if self.config.enable_web_ui:
            print_section("Web UI")
            self.service_manager.state = SystemState.STARTING_UI
            print_status(f"Web UI 启动中: http://localhost:{self.config.web_ui_port}", "info")
            
        # 系统就绪
        self.service_manager.state = SystemState.RUNNING
        self.running = True
        
        print_section("系统就绪")
        print_status("Galaxy 统一系统已启动！", "success")
        print_status(f"控制面板: http://localhost:{self.config.web_ui_port}", "info")
        if self.config.enable_device_api:
            print_status(f"设备 API: http://localhost:{self.config.device_api_port}", "info")
        print_status("按 Ctrl+C 停止系统", "info")
        
        # 启动 Web UI（阻塞）
        if self.config.enable_web_ui:
            await self.web_ui.start()
        else:
            while self.running:
                await asyncio.sleep(1)
                
    def stop(self):
        """停止系统（优雅关闭所有子系统）"""
        print()
        print_status("正在停止系统...", "loading")
        self.service_manager.state = SystemState.STOPPING
        self.running = False

        # 优雅关闭核心子系统（事件桥 → 监控 → 缓存）
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在已运行的 loop 中安排关闭任务
                asyncio.ensure_future(self._async_shutdown())
            else:
                loop.run_until_complete(self._async_shutdown())
        except Exception as e:
            logger.warning(f"异步关闭失败: {e}")

        self.service_manager.stop_all()
        self.service_manager.state = SystemState.STOPPED
        print_status("系统已停止", "success")

    async def _async_shutdown(self):
        """异步关闭核心子系统"""
        try:
            from core.startup import shutdown_subsystems
            await shutdown_subsystems()
        except Exception as e:
            logger.warning(f"子系统关闭异常: {e}")
        
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


# ============================================================================
# 主函数
# ============================================================================

async def _run_check_only(galaxy: 'UFOGalaxyUnified'):
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


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="Galaxy - L4 级自主性智能系统（统一融合版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python unified_launcher.py              # 默认启动（完整模式）
    python unified_launcher.py --minimal    # 最小启动
    python unified_launcher.py --no-l4      # 不启动 L4 模块
    python unified_launcher.py --status     # 查看状态
        """
    )
    parser.add_argument("--minimal", "-m", action="store_true", help="最小启动模式")
    parser.add_argument("--no-ui", action="store_true", help="不启动 Web UI")
    parser.add_argument("--no-l4", action="store_true", help="不启动 L4 增强模块")
    parser.add_argument("--no-nodes", action="store_true", help="不启动节点系统")
    parser.add_argument("--status", action="store_true", help="查看系统状态")
    parser.add_argument("--check-only", action="store_true", help="仅检查依赖和配置，不启动服务")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址 (默认: 0.0.0.0)")
    parser.add_argument("--port", "-p", type=int, default=8080, help="Web UI 端口")
    
    args = parser.parse_args()
    
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

    # 设置信号处理
    def signal_handler(sig, frame):
        galaxy.stop()
        sys.exit(0)
        
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 启动系统
    try:
        asyncio.run(galaxy.start())
    except KeyboardInterrupt:
        galaxy.stop()


if __name__ == "__main__":
    main()
