#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UFO Galaxy - 统一启动器
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

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("UFO-Galaxy")


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
    
    # 数据库配置
    database_url: str = ""
    redis_url: str = ""
    qdrant_url: str = ""
    
    # 服务配置
    web_ui_port: int = 8080
    device_api_port: int = 8766
    ufo_api_port: int = 8767
    
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
        
        # 从环境变量读取
        config.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
        config.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
        config.openrouter_api_key = os.environ.get("OPENROUTER_API_KEY", "")
        config.xai_api_key = os.environ.get("XAI_API_KEY", "")
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
            self.xai_api_key
        ])
    
    def get_status_dict(self) -> Dict[str, Any]:
        """获取状态字典"""
        return {
            "llm_apis": {
                "openai": bool(self.openai_api_key),
                "gemini": bool(self.gemini_api_key),
                "openrouter": bool(self.openrouter_api_key),
                "xai": bool(self.xai_api_key),
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
            from core.microsoft_ufo_integration import UFOIntegrationService
            integration = UFOIntegrationService()
            result = await integration.initialize()
            # initialize 返回 bool，转换为 dict
            result = {"success": result, "message": "UFO Integration initialized" if result else "UFO Integration failed"}
            
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
                title="UFO Galaxy",
                description="L4 级自主性智能系统",
                version="2.0"
            )
            
            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"]
            )
            
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
            
            # === 初始化缓存 ===
            try:
                from core.cache import get_cache
                redis_url = self.config.redis_url if hasattr(self.config, 'redis_url') else ""
                cache = asyncio.get_event_loop().run_until_complete(get_cache(redis_url))
                logger.info(f"缓存已初始化: {cache.backend_type}")
            except Exception as e:
                logger.warning(f"缓存初始化失败: {e}")
            
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
                host="0.0.0.0",
                port=self.config.web_ui_port,
                log_level="warning"
            )
            server = uvicorn.Server(config)
            logger.info(f"API 服务启动: http://0.0.0.0:{self.config.web_ui_port}")
            logger.info(f"API 文档: http://localhost:{self.config.web_ui_port}/docs")
            await server.serve()
            
        except ImportError as e:
            logger.error(f"Web UI 依赖未安装: {e}")
            
    def _get_dashboard_html(self) -> str:
        """获取仪表板 HTML"""
        return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UFO Galaxy - 全景指挥舱</title>
    <style>
        :root {
            --bg-dark: #0a0a0a;
            --bg-card: rgba(20, 20, 30, 0.6);
            --accent: #00ff88;
            --accent-glow: rgba(0, 255, 136, 0.2);
            --text-main: #e0e0e0;
            --text-dim: #888;
            --border: rgba(255, 255, 255, 0.1);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            background: var(--bg-dark);
            color: var(--text-main);
            min-height: 100vh;
            overflow-x: hidden;
        }
        .container { max-width: 1600px; margin: 0 auto; padding: 20px; }
        
        /* 顶部状态栏 */
        .top-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px 25px;
            background: var(--bg-card);
            border-bottom: 1px solid var(--border);
            backdrop-filter: blur(10px);
            position: sticky;
            top: 0;
            z-index: 100;
        }
        .logo {
            font-size: 1.5rem;
            font-weight: bold;
            background: linear-gradient(90deg, #00d4ff, #00ff88);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .network-info {
            display: flex;
            gap: 20px;
            font-size: 0.9rem;
        }
        .network-badge {
            padding: 4px 12px;
            border-radius: 4px;
            background: rgba(0, 212, 255, 0.1);
            color: #00d4ff;
            border: 1px solid rgba(0, 212, 255, 0.2);
        }

        /* 主网格布局 */
        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(12, 1fr);
            gap: 20px;
            margin-top: 20px;
        }
        
        /* 卡片通用样式 */
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            backdrop-filter: blur(5px);
        }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 10px;
        }
        .card-title { font-size: 1.1rem; color: var(--accent); }

        /* 设备监控区 (占 8 列) */
        .devices-section { grid-column: span 8; }
        .device-list {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
            gap: 15px;
        }
        .device-card {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 15px;
            transition: all 0.3s ease;
        }
        .device-card:hover {
            border-color: var(--accent);
            box-shadow: 0 0 15px var(--accent-glow);
        }
        .device-status {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 10px;
        }
        .status-indicator {
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }
        .online { background: #00ff88; box-shadow: 0 0 8px #00ff88; }
        .offline { background: #ff4444; }
        .device-info p { font-size: 0.85rem; color: var(--text-dim); margin: 4px 0; }
        .wake-btn {
            width: 100%;
            margin-top: 10px;
            padding: 8px;
            background: rgba(0, 255, 136, 0.1);
            border: 1px solid var(--accent);
            color: var(--accent);
            border-radius: 4px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .wake-btn:hover { background: var(--accent); color: #000; }

        /* 系统状态区 (占 4 列) */
        .system-section { grid-column: span 4; display: flex; flex-direction: column; gap: 20px; }
        .stat-row {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        .log-panel {
            height: 300px;
            overflow-y: auto;
            font-family: monospace;
            font-size: 0.8rem;
            color: #aaa;
            background: rgba(0,0,0,0.3);
            padding: 10px;
            border-radius: 4px;
        }
        .log-entry { margin-bottom: 4px; }
        .log-info { color: #00d4ff; }
        .log-warn { color: #ffaa00; }
        .log-error { color: #ff4444; }

    </style>
</head>
<body>
    <div class="top-bar">
        <div class="logo">🌌 UFO Galaxy Command</div>
        <div class="network-info">
            <span class="network-badge" id="tailscale-ip">Tailscale: 检测中...</span>
            <span class="network-badge" id="local-ip">Local: 127.0.0.1</span>
        </div>
    </div>

    <div class="container">
        <div class="dashboard-grid">
            <!-- 设备监控 -->
            <div class="devices-section card">
                <div class="card-header">
                    <div class="card-title">🛸 在线设备矩阵</div>
                    <div class="badge" id="device-count">0 在线</div>
                </div>
                <div class="device-list" id="device-list">
                    <!-- 设备卡片将动态插入这里 -->
                    <div style="text-align:center; color:#666; grid-column:span 3; padding:20px;">
                        等待设备接入...
                    </div>
                </div>
            </div>

            <!-- 系统状态 -->
            <div class="system-section">
                <div class="card">
                    <div class="card-header">
                        <div class="card-title">⚡ 系统负载</div>
                    </div>
                    <div class="stat-row">
                        <span>核心服务</span>
                        <span id="core-status" style="color:#00ff88">运行中</span>
                    </div>
                    <div class="stat-row">
                        <span>节点系统</span>
                        <span id="node-count">0/108 激活</span>
                    </div>
                    <div class="stat-row">
                        <span>API 延迟</span>
                        <span id="api-latency">12ms</span>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header">
                        <div class="card-title">📜 实时日志</div>
                    </div>
                    <div class="log-panel" id="log-panel">
                        <div class="log-entry"><span class="log-info">[INFO]</span> 系统初始化完成</div>
                        <div class="log-entry"><span class="log-info">[INFO]</span> 等待 WebSocket 连接...</div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // 建立 WebSocket 连接
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/status`;
        let ws;

        function connect() {
            ws = new WebSocket(wsUrl);
            
            ws.onopen = () => {
                log('系统连接成功', 'info');
                // 请求初始状态
                fetch('/api/v1/system/status')
                    .then(r => r.json())
                    .then(updateDashboard);
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.type === 'device_connected' || data.type === 'device_disconnected' || data.type === 'device_status_update') {
                    // 刷新设备列表
                    fetch('/api/v1/system/status')
                        .then(r => r.json())
                        .then(updateDashboard);
                    
                    if (data.type === 'device_connected') log(`设备接入: ${data.device_id}`, 'info');
                    if (data.type === 'device_disconnected') log(`设备断开: ${data.device_id}`, 'warn');
                }
            };

            ws.onclose = () => {
                log('连接断开，5秒后重连...', 'error');
                setTimeout(connect, 5000);
            };
        }

        function updateDashboard(data) {
            // 更新 Tailscale IP
            if (data.network && data.network.tailscale_ip) {
                document.getElementById('tailscale-ip').textContent = `Tailscale: ${data.network.tailscale_ip}`;
            }

            // 更新设备列表
            const list = document.getElementById('device-list');
            const devices = data.devices.list || [];
            document.getElementById('device-count').textContent = `${data.devices.online} 在线`;

            if (devices.length === 0) {
                list.innerHTML = '<div style="text-align:center; color:#666; grid-column:span 3; padding:20px;">暂无设备接入</div>';
            } else {
                list.innerHTML = devices.map(d => `
                    <div class="device-card">
                        <div class="device-status">
                            <div class="status-indicator ${d.online ? 'online' : 'offline'}"></div>
                            <strong>${d.device_name || '未知设备'}</strong>
                        </div>
                        <div class="device-info">
                            <p>ID: ${d.device_id.substring(0, 8)}...</p>
                            <p>Type: ${d.device_type}</p>
                            <p>Last Seen: ${new Date(d.last_seen).toLocaleTimeString()}</p>
                        </div>
                        ${d.online ? `<button class="wake-btn" onclick="wakeDevice('${d.device_id}')">⚡ 唤醒 / 交互</button>` : ''}
                    </div>
                `).join('');
            }

            // 更新节点计数
            document.getElementById('node-count').textContent = `${data.nodes.active}/${data.nodes.total} 激活`;
        }

        function log(msg, type='info') {
            const panel = document.getElementById('log-panel');
            const entry = document.createElement('div');
            entry.className = 'log-entry';
            const colorClass = type === 'error' ? 'log-error' : type === 'warn' ? 'log-warn' : 'log-info';
            entry.innerHTML = `<span class="${colorClass}">[${type.toUpperCase()}]</span> ${msg}`;
            panel.prepend(entry);
        }

        async function wakeDevice(deviceId) {
            log(`正在唤醒设备 ${deviceId}...`, 'info');
            try {
                const resp = await fetch('/api/v1/tasks', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        task_type: 'wake_up',
                        device_id: deviceId,
                        payload: { message: "System Wake Up Call" }
                    })
                });
                if (resp.ok) log('唤醒指令已发送', 'info');
                else log('唤醒失败', 'error');
            } catch (e) {
                log(`发送失败: ${e}`, 'error');
            }
        }

        // 启动
        connect();
    </script>
</body>
</html>
        """


# ============================================================================
# UFO Galaxy 统一系统
# ============================================================================

class UFOGalaxyUnified:
    """UFO Galaxy 统一系统"""
    
    def __init__(self):
        self.config = SystemConfig.load_from_env()
        self.service_manager = ServiceManager(self.config)
        self.core_launcher = CoreServiceLauncher(self.service_manager, self.config)
        self.node_launcher = NodeSystemLauncher(self.service_manager, self.config)
        self.l4_launcher = L4EnhancementLauncher(self.service_manager, self.config)
        self.web_ui = UnifiedWebUI(self.service_manager, self.config)
        self.running = False
        
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
        print_status("UFO Galaxy 统一系统已启动！", "success")
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
        """停止系统"""
        print()
        print_status("正在停止系统...", "loading")
        self.service_manager.state = SystemState.STOPPING
        self.running = False
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


# ============================================================================
# 主函数
# ============================================================================

def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="UFO Galaxy - L4 级自主性智能系统（统一融合版）",
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
    parser.add_argument("--port", "-p", type=int, default=8080, help="Web UI 端口")
    
    args = parser.parse_args()
    
    # 创建系统实例
    galaxy = UFOGalaxyUnified()
    
    # 应用命令行参数
    galaxy.config.minimal_mode = args.minimal
    galaxy.config.enable_web_ui = not args.no_ui
    galaxy.config.enable_l4 = not args.no_l4
    galaxy.config.enable_nodes = not args.no_nodes
    galaxy.config.web_ui_port = args.port
    
    # 查看状态
    if args.status:
        galaxy.show_status()
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
