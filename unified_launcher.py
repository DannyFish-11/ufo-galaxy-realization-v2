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
            except:
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
        """启动 Web UI"""
        try:
            from fastapi import FastAPI, HTTPException
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
                
            config = uvicorn.Config(
                self.app,
                host="0.0.0.0",
                port=self.config.web_ui_port,
                log_level="warning"
            )
            server = uvicorn.Server(config)
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
    <title>UFO Galaxy - 统一控制面板</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 50%, #16213e 100%);
            min-height: 100vh;
            color: #fff;
        }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        .header {
            text-align: center;
            padding: 40px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .header h1 {
            font-size: 3rem;
            background: linear-gradient(90deg, #00d4ff, #7b2cbf, #ff6b6b);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            animation: gradient 3s ease infinite;
        }
        @keyframes gradient {
            0%, 100% { filter: hue-rotate(0deg); }
            50% { filter: hue-rotate(30deg); }
        }
        .header p { color: #888; margin-top: 10px; }
        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 20px;
            margin-top: 30px;
        }
        .status-card {
            background: rgba(255,255,255,0.03);
            border-radius: 16px;
            padding: 24px;
            border: 1px solid rgba(255,255,255,0.08);
            backdrop-filter: blur(10px);
        }
        .status-card h3 {
            color: #00d4ff;
            margin-bottom: 16px;
            font-size: 1.1rem;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .status-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        .status-item:last-child { border-bottom: none; }
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 8px;
        }
        .status-dot.active { background: #00ff88; box-shadow: 0 0 10px #00ff88; }
        .status-dot.partial { background: #ffaa00; box-shadow: 0 0 10px #ffaa00; }
        .status-dot.inactive { background: #ff4444; }
        .status-dot.disabled { background: #444; }
        .badge {
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 500;
        }
        .badge.running { background: rgba(0,255,136,0.2); color: #00ff88; }
        .badge.stopped { background: rgba(255,68,68,0.2); color: #ff4444; }
        .badge.partial { background: rgba(255,170,0,0.2); color: #ffaa00; }
        .section-title {
            font-size: 0.85rem;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin: 20px 0 10px;
        }
        #refresh-time { color: #666; font-size: 0.8rem; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🌌 UFO Galaxy</h1>
            <p>L4 级自主性智能系统 - 统一融合版 v2.0</p>
        </div>
        <div class="status-grid">
            <div class="status-card">
                <h3>🔧 核心服务</h3>
                <div id="core-services">加载中...</div>
            </div>
            <div class="status-card">
                <h3>🧠 L4 增强模块</h3>
                <div id="l4-modules">加载中...</div>
            </div>
            <div class="status-card">
                <h3>🔌 API 配置</h3>
                <div id="api-status">加载中...</div>
            </div>
            <div class="status-card">
                <h3>📦 节点状态</h3>
                <div id="node-status">加载中...</div>
            </div>
        </div>
        <p id="refresh-time" style="text-align: center; margin-top: 20px;"></p>
    </div>
    <script>
        async function updateStatus() {
            try {
                const resp = await fetch('/api/status');
                const data = await resp.json();
                
                // 核心服务
                let coreHtml = '';
                const coreServices = ['device_agent_manager', 'device_status_api', 'microsoft_ufo_integration'];
                for (const name of coreServices) {
                    const service = data.services[name] || {status: 'stopped'};
                    const dotClass = service.status === 'running' ? 'active' : 
                                    service.status === 'partial' ? 'partial' : 'inactive';
                    const badgeClass = service.status === 'running' ? 'running' : 
                                      service.status === 'partial' ? 'partial' : 'stopped';
                    coreHtml += `<div class="status-item">
                        <span><span class="status-dot ${dotClass}"></span>${name}</span>
                        <span class="badge ${badgeClass}">${service.status}</span>
                    </div>`;
                }
                document.getElementById('core-services').innerHTML = coreHtml;
                
                // API 状态
                let apiHtml = '';
                for (const [name, configured] of Object.entries(data.config.llm_apis)) {
                    const dotClass = configured ? 'active' : 'disabled';
                    apiHtml += `<div class="status-item">
                        <span><span class="status-dot ${dotClass}"></span>${name.toUpperCase()}</span>
                        <span>${configured ? '✓' : '—'}</span>
                    </div>`;
                }
                document.getElementById('api-status').innerHTML = apiHtml;
                
                // 节点状态
                const nodeServices = Object.entries(data.services).filter(([k, v]) => v.type === 'node');
                const runningNodes = nodeServices.filter(([k, v]) => v.status === 'running').length;
                document.getElementById('node-status').innerHTML = `
                    <div class="status-item">
                        <span><span class="status-dot active"></span>运行中节点</span>
                        <span>${runningNodes}</span>
                    </div>
                    <div class="status-item">
                        <span><span class="status-dot disabled"></span>总节点数</span>
                        <span>${nodeServices.length}</span>
                    </div>
                `;
                
                // L4 模块
                document.getElementById('l4-modules').innerHTML = `
                    <div class="status-item">
                        <span><span class="status-dot active"></span>感知模块</span>
                        <span class="badge running">active</span>
                    </div>
                    <div class="status-item">
                        <span><span class="status-dot active"></span>推理模块</span>
                        <span class="badge running">active</span>
                    </div>
                    <div class="status-item">
                        <span><span class="status-dot active"></span>学习模块</span>
                        <span class="badge running">active</span>
                    </div>
                    <div class="status-item">
                        <span><span class="status-dot active"></span>执行模块</span>
                        <span class="badge running">active</span>
                    </div>
                `;
                
                document.getElementById('refresh-time').textContent = 
                    '最后更新: ' + new Date().toLocaleTimeString();
            } catch (e) {
                console.error(e);
            }
        }
        updateStatus();
        setInterval(updateStatus, 3000);
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
        
        # 2. 启动核心服务
        print_section("核心服务")
        self.service_manager.state = SystemState.STARTING_CORE
        
        core_results = await self.core_launcher.start_all()
        core_success = sum(1 for v in core_results.values() if v)
        print_status(f"核心服务: {core_success}/{len(core_results)} 已启动", 
                    "success" if core_success == len(core_results) else "warning")
        
        # 3. 启动节点系统
        if self.config.enable_nodes:
            print_section("节点系统")
            self.service_manager.state = SystemState.STARTING_NODES
            
            node_results = await self.node_launcher.start_all(minimal=self.config.minimal_mode)
            node_success = sum(1 for v in node_results.values() if v)
            print_status(f"节点: {node_success}/{len(node_results)} 已启动", 
                        "success" if node_success > 0 else "warning")
        
        # 4. 启动 L4 增强模块
        if self.config.enable_l4:
            print_section("L4 增强模块")
            self.service_manager.state = SystemState.STARTING_L4
            
            l4_results = await self.l4_launcher.start_all()
            l4_success = sum(1 for v in l4_results.values() if v)
            print_status(f"L4 模块: {l4_success}/{len(l4_results)} 已初始化", 
                        "success" if l4_success == len(l4_results) else "warning")
        
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
