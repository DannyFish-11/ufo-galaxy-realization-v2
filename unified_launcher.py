#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy - 统一启动器 (Bootstrap Launcher — Adapter/Launcher Role)
==================================================================

**Unified-Subject Architecture — Bootstrap Launcher Only**
-----------------------------------------------------------
This script is a **bootstrap launcher**.  It initialises the process
environment, starts supporting services, and brings up the HTTP server.
It does NOT have subject-core authority.

The subject lifecycle is owned by:
- :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime` — the
  outer Windows desktop runtime shell (tri-state lifecycle owner).
- :class:`~core.openclawd.OpenClawd` — the inner subject core.

This launcher's role: process bootstrap → service initialisation →
HTTP server startup → yield to the runtime shell for request handling.

融合性整合所有模块的统一入口：
1. 核心服务层（Device Agent、设备状态）
2. 节点系统（108+ 节点）
3. L4 增强模块（感知、推理、学习、执行）
4. Web UI 和 API 服务

作者：Galaxy Team
日期：2026-02-06
版本：2.0
"""

import os
import sys
import json
import time
import signal
import socket
import asyncio
import logging
import argparse
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
from datetime import datetime, timezone

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
# 运行时入口点文件
# ============================================================================

def _write_entrypoint(host: str, port: int) -> None:
    """向 runtime/entrypoint.json 写入当前 API 入口，供客户端读取。

    文件格式::

        {
            "api_base": "http://localhost:8299",
            "written_at": "2026-01-01T00:00:00Z"
        }

    - ``api_base``：客户端应连接的完整 URL 前缀（不含路径）。
    - ``written_at``：ISO-8601 UTC 时间戳，仅用于调试，客户端可忽略。

    每次启动均会覆盖写入；目录不存在时自动创建。
    ``host`` 为 ``0.0.0.0`` / 空字符串时，写入 ``localhost``（客户端可用地址）。
    """
    runtime_dir = PROJECT_ROOT / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    effective_host = "localhost" if host in ("0.0.0.0", "") else host
    payload = {
        "api_base": f"http://{effective_host}:{port}",
        "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    entrypoint_file = runtime_dir / "entrypoint.json"
    entrypoint_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


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
    web_ui_port: int = 8299
    device_api_port: int = 8766
    ufo_api_port: int = 8767

    def __post_init__(self):
        """从 PortConfig 加载端口默认值（如果可用）

        端口来源优先级（高→低）：
          1. 环境变量 GALAXY_UNIFIED_LAUNCHER_PORT / GALAXY_DEVICE_API_PORT / GALAXY_UFO_API_PORT
             （已由 get_service_port() 内部实现，调用后自动享有此优先级）
          2. config/unified_ports.yaml（统一端口事实来源）
          3. 内置硬编码默认值（8299 / 8766 / 8767）

        config.json 中的 web_ui_port 字段仅作 OpenClawd API 端口的 legacy 标记，
        不参与 unified_launcher 自身端口的解析。
        """
        try:
            from core.port_config import get_service_port
            # get_service_port 内部已实现 env-first 优先级，直接使用
            self.web_ui_port = get_service_port("unified_launcher")
            self.device_api_port = get_service_port("device_api")
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
        """从统一配置管理器加载配置（.env / config.json / config/unified_ports.yaml）"""
        instance = cls()

        # 使用 UnifiedConfigManager 统一读取 .env + config.json
        try:
            from core.unified.config_manager import get_unified_config_manager  # noqa: PLC0415
            mgr = get_unified_config_manager()

            # API Keys — 优先使用 UnifiedConfigManager（已合并 .env + config.json）
            def _get_key(unified_key: str, env_key: str) -> str:
                v = mgr.get(unified_key) or mgr.get(unified_key.upper()) or os.environ.get(env_key, "")
                return v or ""

            instance.openai_api_key = _get_key("openai_api_key", "OPENAI_API_KEY")
            instance.gemini_api_key = _get_key("gemini_api_key", "GEMINI_API_KEY")
            instance.openrouter_api_key = _get_key("openrouter_api_key", "OPENROUTER_API_KEY")
            instance.xai_api_key = _get_key("xai_api_key", "XAI_API_KEY")
            instance.deepseek_api_key = _get_key("deepseek_api_key", "DEEPSEEK_API_KEY")
            instance.anthropic_api_key = _get_key("anthropic_api_key", "ANTHROPIC_API_KEY")
            instance.database_url = _get_key("database_url", "DATABASE_URL")
            instance.redis_url = _get_key("redis_url", "REDIS_URL")
            instance.qdrant_url = _get_key("qdrant_url", "QDRANT_URL")

            logger.info(
                "SystemConfig loaded via UnifiedConfigManager",
                extra={"event": "config_loaded", "source": "UnifiedConfigManager"},
            )
        except Exception as exc:
            # 回退：直接读取 .env 和 os.environ
            logger.warning(
                "UnifiedConfigManager not available, falling back to direct .env and environment variable read: %s", exc
            )
            env_file = PROJECT_ROOT / ".env"
            if env_file.exists():
                with open(env_file, 'r', encoding='utf-8') as f:
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
            instance.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
            instance.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
            instance.openrouter_api_key = os.environ.get("OPENROUTER_API_KEY", "")
            instance.xai_api_key = os.environ.get("XAI_API_KEY", "")
            instance.deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY", "")
            instance.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            instance.database_url = os.environ.get("DATABASE_URL", "")
            instance.redis_url = os.environ.get("REDIS_URL", "")
            instance.qdrant_url = os.environ.get("QDRANT_URL", "")

        return instance
    
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
        
    async def start_service(self, name: str, command: List[str], cwd: Optional[Path] = None, extra_env: Optional[Dict[str, str]] = None) -> bool:
        """启动服务"""
        if name not in self.services:
            logger.error(f"服务未注册: {name}")
            return False
            
        service = self.services[name]
        
        try:
            env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
            if extra_env:
                env.update(extra_env)
            process = subprocess.Popen(
                command,
                cwd=str(cwd) if cwd else str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
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
        """加载节点配置

        优先从 node_dependencies.json 的 "nodes" 键读取；
        若文件不存在则回退到 config/node_registry.json。
        两个文件都不存在时记录可观测诊断日志并返回空字典。
        """
        primary = PROJECT_ROOT / "node_dependencies.json"
        fallback = PROJECT_ROOT / "config" / "node_registry.json"

        for cfg_path in (primary, fallback):
            if cfg_path.exists():
                try:
                    with open(cfg_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    # node_dependencies.json 将节点放在 "nodes" 子键下
                    nodes = data.get("nodes", data) if isinstance(data, dict) else {}
                    if nodes:
                        logger.info("节点配置已加载: %s (%d 个节点)", cfg_path, len(nodes))
                        return nodes
                    logger.warning("节点配置文件为空或格式异常: %s", cfg_path)
                except Exception as exc:
                    logger.warning("读取节点配置失败 %s: %s", cfg_path, exc)

        logger.error(
            "未找到节点配置文件。已检查路径: %s, %s。"
            "请确保 node_dependencies.json 存在于项目根目录，"
            "或在 config/node_registry.json 中提供备用配置。",
            primary, fallback,
        )
        return {}

    def get_core_nodes(self) -> List[str]:
        """获取核心节点列表。

        优先使用节点配置中标记 "group": "core" 的节点。
        若无任何节点具有该标记（如 node_registry.json 未设置），则回退为
        按节点目录名称升序排列的前 10 个基础节点（Node_00–Node_09），确保
        系统始终能自动启动最核心的节点而不报告"节点数量为 0"。
        """
        import re as _re
        core_nodes = []
        for name, cfg in self.node_configs.items():
            if isinstance(cfg, dict) and cfg.get("group") == "core":
                core_nodes.append(name)
        if core_nodes:
            return sorted(core_nodes,
                          key=lambda x: self.node_configs.get(x, {}).get("priority", 99))

        # 回退：node_registry 未设置 group 字段时，选取最基础的节点
        all_nodes = self.get_all_nodes()
        if not all_nodes:
            return []
        def _node_key(name: str) -> int:
            m = _re.match(r"Node_0*(\d+)", name)
            return int(m.group(1)) if m else 999
        fundamental = sorted(all_nodes, key=_node_key)[:10]
        logger.info(
            "节点配置中未找到 'group': 'core' 标记，"
            "自动回退为前 10 个基础节点: %s",
            fundamental,
        )
        return fundamental
        
    def get_all_nodes(self) -> List[str]:
        """获取所有节点列表"""
        if not self.nodes_dir.exists():
            return []
        return sorted([
            d.name for d in self.nodes_dir.iterdir()
            if d.is_dir() and (d / "main.py").exists()
        ])
        
    async def start_node(self, node_name: str) -> bool:
        """启动单个节点，传递关键环境变量并轮询健康检查。"""
        import aiohttp
        node_dir = self.nodes_dir / node_name
        main_py = node_dir / "main.py"

        if not main_py.exists():
            logger.warning("节点 %s 缺少 main.py，跳过启动", node_name)
            return False

        # 从节点配置或 port_config 获取端口
        node_cfg = self.node_configs.get(node_name, {})
        port: Optional[int] = node_cfg.get("port") if isinstance(node_cfg, dict) else None
        if port is None:
            try:
                from core.port_config import get_node_port
                port = get_node_port(node_name)
            except Exception:
                port = None

        # 关键环境变量
        state_machine_url = os.environ.get(
            "STATE_MACHINE_URL",
            f"http://127.0.0.1:{self.node_configs.get('Node_00_StateMachine', {}).get('port', 8000)}"
            if isinstance(self.node_configs.get('Node_00_StateMachine'), dict)
            else "http://127.0.0.1:8000",
        )
        extra_env: Dict[str, str] = {
            "NODE_ID": node_name,
            "NODE_NAME": node_name,
            "STATE_MACHINE_URL": state_machine_url,
            "LOG_LEVEL": os.environ.get("LOG_LEVEL", "INFO"),
            "USE_MEMORY_STORE": os.environ.get("USE_MEMORY_STORE", "true"),
            "USE_MOCK_DRIVERS": os.environ.get("USE_MOCK_DRIVERS", "false"),
        }
        if port is not None:
            extra_env["PORT"] = str(port)

        self.service_manager.register_service(node_name, ServiceType.NODE, port)

        ok = await self.service_manager.start_service(
            node_name,
            [sys.executable, str(main_py)],
            cwd=node_dir,
            extra_env=extra_env,
        )
        if not ok:
            logger.error("节点 %s 进程启动失败", node_name)
            return False

        # 健康检查轮询（最多 10 次，每次间隔 1 秒）
        if port is not None:
            health_url = f"http://127.0.0.1:{port}/health"
            for attempt in range(1, 11):
                await asyncio.sleep(1)
                try:
                    async with aiohttp.ClientSession(
                        timeout=aiohttp.ClientTimeout(total=2)
                    ) as session:
                        async with session.get(health_url) as resp:
                            if resp.status < 400:
                                # 解析响应体以识别 degraded/skipped 模式
                                try:
                                    body = await resp.json()
                                    node_status_val = body.get("status", "healthy")
                                except Exception:
                                    node_status_val = "healthy"

                                if node_status_val in ("degraded", "skipped"):
                                    logger.warning(
                                        "节点 %s 以 %s 模式启动 (尝试 %d/10, 端口 %d) — "
                                        "部分功能可能受限，但不影响系统启动",
                                        node_name, node_status_val, attempt, port,
                                    )
                                else:
                                    logger.info(
                                        "节点 %s 健康检查通过 (尝试 %d/10, 端口 %d)",
                                        node_name, attempt, port,
                                    )
                                await self._register_node_with_runtime_registry(node_name, port)
                                return True
                except Exception:
                    pass
                logger.debug("节点 %s 健康检查等待 (尝试 %d/10)", node_name, attempt)

            # 10 次均失败时输出 stderr 辅助排查（非阻塞读取）
            svc = self.service_manager.services.get(node_name)
            if svc and svc.process and svc.process.stderr:
                try:
                    import select as _select
                    if _select.select([svc.process.stderr], [], [], 0.5)[0]:
                        stderr_out = svc.process.stderr.read1(4096)  # type: ignore[attr-defined]
                        if stderr_out:
                            logger.error(
                                "节点 %s 健康检查失败，stderr:\n%s",
                                node_name, stderr_out.decode(errors="replace"),
                            )
                except Exception:
                    pass
            logger.warning(
                "节点 %s 健康检查超时（10 次），视为启动失败", node_name
            )
            return False

        # 无端口信息时降级：进程已启动即认为成功
        logger.info("节点 %s 已启动（无端口，跳过健康检查）", node_name)
        await self._register_node_with_runtime_registry(node_name, port)
        return True

    async def _register_node_with_runtime_registry(self, node_name: str, port: Optional[int]) -> None:
        """向运行时节点注册表注册已启动的节点（失败时静默忽略）。

        注册端点来自 core/api_routes.py（权威 API 层）。
        dashboard/backend 的 /api/v1/nodes/register 已降级为遗留路由，
        由 core.api_routes 的同路径路由覆盖。
        """
        try:
            import aiohttp
            api_host = os.environ.get("GALAXY_API_HOST", "127.0.0.1")
            api_port = self.config.web_ui_port
            url = f"http://{api_host}:{api_port}/api/v1/nodes/register"
            payload = {
                "node_id": node_name,
                "name": node_name,
                "port": port,
                "status": "running",
            }
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=2)
            ) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status < 400:
                        logger.debug("节点 %s 已注册到运行时注册表", node_name)
        except Exception as _exc:
            logger.debug("注册节点 %s 到运行时注册表失败（可忽略）: %s", node_name, _exc)
        
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
        """启动节点集合。

        优先使用 "group": "core" 标记的节点；若为空则自动回退为
        get_all_nodes() 的完整列表（非 minimal 模式）或前 10 个节点
        （minimal 模式），并记录 warning，确保系统始终能够启动而不
        静默返回空字典。

        Args:
            minimal: True 时最多启动前 10 个节点。
        """
        nodes = self.get_core_nodes()

        if not nodes:
            fallback = self.get_all_nodes()
            if fallback:
                logger.warning(
                    "核心节点列表为空（node_dependencies.json 中无 'group': 'core' 标记），"
                    "自动回退为全量节点列表（共 %d 个）。",
                    len(fallback),
                )
                nodes = fallback
            else:
                logger.error(
                    "核心节点与全量节点列表均为空，节点系统将不会启动。"
                    "请确认 nodes/ 目录下存在包含 main.py 的子目录。"
                )
                return {}

        if minimal:
            nodes = nodes[:10]
            logger.info("最小启动模式：将启动前 %d 个节点", len(nodes))

        logger.info("即将启动 %d 个节点: %s", len(nodes), nodes)
        print_status(f"启动 {len(nodes)} 个节点...", "step")
        results = await self.start_nodes(nodes, parallel=True)

        success_nodes = [n for n, ok in results.items() if ok]
        failed_nodes  = [n for n, ok in results.items() if not ok]
        logger.info(
            "节点启动完成: %d 成功 / %d 失败%s",
            len(success_nodes),
            len(failed_nodes),
            f"  失败节点: {failed_nodes}" if failed_nodes else "",
        )
        return results


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
          + desktop status surface）。dashboard/frontend 是 **遗留表层**，不是
          现行主系统表层，仅作过渡期兼容保留。

          1. 以内建 FastAPI 应用为主应用（权威应用）。
             可选：加载 dashboard.backend.main 的遗留路由作为非主路由
             （低优先级，会被步骤 3 中 core.api_routes 的同路径路由覆盖）。
          2. 在其上叠加 core.startup 引导的子系统中间件
          3. 叠加 core.api_routes 作为 **主 API 层**（系统管理、设备、节点、
             监控、观测性、AI、chat 等全部路由）
          4. 添加健康检查路由
          5. 统一在配置端口提供服务

        注意：此启动器 **不应** 定义自己的 inline API 路由。
        如需新增 API 端点，请在 core/routes/ 下对应子模块中添加。
        """
        # dashboard/frontend 是遗留表层，其静态资源不存在属于正常情况，仅 debug 级记录。
        frontend_index = PROJECT_ROOT / "dashboard" / "frontend" / "public" / "index.html"
        frontend_dist = PROJECT_ROOT / "dashboard" / "frontend" / "dist"
        if not frontend_index.exists():
            logger.debug(
                "Legacy dashboard frontend 静态资源未找到: %s（非当前主表层，可忽略）",
                frontend_index,
            )
            if frontend_dist.exists():
                logger.debug("检测到遗留构建产物目录 %s，但缺少 public/index.html", frontend_dist)
        try:
            from fastapi.responses import HTMLResponse, JSONResponse
            import uvicorn

            # === 步骤 1：以内建 FastAPI 应用为主应用（权威 API 基础） ===
            # dashboard/frontend 是遗留表层（PR-8 已降级），不作为主应用基础。
            # 遗留 dashboard 路由将在后续步骤以非主路由形式可选加载，
            # 并会被 core.api_routes 的同路径路由覆盖。
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

            # Optional: load legacy dashboard routes (non-primary, superseded by core.api_routes).
            # dashboard/backend/main.py is a LEGACY UI SURFACE (PR-8).  Any overlapping routes
            # defined there will be superseded by the core.api_routes layer in Step 3.
            try:
                from dashboard.backend import main as _dashboard_backend_module
                _legacy_app = getattr(_dashboard_backend_module, "app", None)
                if _legacy_app is not None:
                    _existing_paths = {getattr(r, "path", None) for r in self.app.routes}
                    for _route in getattr(_legacy_app, "routes", []):
                        if hasattr(_route, "path") and _route.path not in _existing_paths:
                            self.app.routes.append(_route)
                            _existing_paths.add(_route.path)
                    logger.debug(
                        "Legacy dashboard routes imported (non-primary; superseded by core.api_routes)"
                    )
            except Exception as _e:
                logger.debug("Legacy dashboard backend not loaded (expected if removed): %s", _e)

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
            await server.serve()

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
        print_powershell_hint()
        # 标记横幅已打印，防止子进程/模块重复打印
        os.environ["GALAXY_BANNER_PRINTED"] = "1"
        
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

        # ── Phase A: NATS Bus + MasterBrain startup ──────────────────────────
        # NATS is the internal scheduling mainline but is optional: if
        # GALAXY_NATS_URL is unset the bus operates in no-op mode and the
        # system starts in single-machine mode.
        _nats_env_set = bool(os.environ.get("GALAXY_NATS_URL", "").strip())
        nats_url = os.environ.get("GALAXY_NATS_URL", "nats://localhost:4222")
        _is_win = sys.platform.startswith("win")
        _hc_script = r"scripts\health_check.ps1" if _is_win else "scripts/health_check.sh"
        _hc_cmd = f".\\{_hc_script}" if _is_win else f"bash {_hc_script}"

        print_section("NATS 控制面")

        # Friendly hint when GALAXY_NATS_URL is not explicitly configured.
        if not _nats_env_set:
            _lan_ip = _get_lan_ip()
            print_status("GALAXY_NATS_URL 未设置 — 使用本地默认值", "info")
            print_status(f"  默认地址: nats://localhost:4222 (单机开发)", "info")
            if _lan_ip:
                print_status(
                    f"  跨设备提示: 设置 GALAXY_NATS_URL=nats://{_lan_ip}:4222"
                    " 可让其他设备接入",
                    "info",
                )

        def _nats_diag(detail: str) -> None:
            print_status(f"NATS Bus: {detail}", "warning")
            print_status("提示: 启动 NATS 服务 (nats-server -p 4222) 以启用分布式调度", "info")
            print_status(f"  当前 NATS URL: {nats_url}", "info")
            print_status(f"  运行完整诊断: {_hc_cmd}", "info")

        try:
            from core.nats_bus import nats_bus
            conn_result = await nats_bus.connect()
            if conn_result.get("success") and not conn_result.get("noop"):
                print_status(f"NATS Bus: 已连接 ({nats_url})", "success")
            elif conn_result.get("noop"):
                print_status("NATS Bus: 未启用 (no-op 模式，单机运行)", "info")
            else:
                _nats_error_msg = conn_result.get("error", "连接失败，无详细信息")
                _nats_diag(f"连接失败 — {_nats_error_msg}，以降级模式继续启动")
            stats = nats_bus.get_stats()
            logger.info("NATS Bus stats: %s", stats)
        except Exception as _nats_err:
            _nats_diag(f"初始化异常: {_nats_err}，以降级模式继续启动")

        try:
            if os.environ.get("GALAXY_MASTER_BRAIN_ENABLED", "").lower() in ("true", "1"):
                from core.master_brain import get_master_brain
                brain = get_master_brain()
                if brain is not None:
                    start_result = await brain.start()
                    if start_result.get("success"):
                        print_status("MasterBrain: 已启动，订阅已激活", "success")
                    else:
                        print_status("MasterBrain: 启动失败，降级为本地模式", "warning")
            else:
                print_status(
                    "MasterBrain: 未启用 (设置 GALAXY_MASTER_BRAIN_ENABLED=true 以启用)", "info"
                )
        except Exception as _brain_err:
            print_status(f"MasterBrain 初始化异常 (非致命): {_brain_err}", "warning")
        
        # 5. 启动 API 服务
        if self.config.enable_web_ui:
            print_section("API 服务")
            self.service_manager.state = SystemState.STARTING_UI
            print_status(f"API 服务启动中: http://localhost:{self.config.web_ui_port}", "info")
            
        # 系统就绪
        self.service_manager.state = SystemState.RUNNING
        self.running = True

        # 写出运行时入口文件，供 Windows 客户端等自动发现 API 地址
        try:
            _write_entrypoint(self.config.host, self.config.web_ui_port)
        except Exception as _e:
            logger.warning("写入 runtime/entrypoint.json 失败（不影响启动）: %s", _e)

        print_section("系统就绪")
        print_status("Galaxy 统一系统已启动！", "success")
        if self.config.enable_web_ui:
            print_status(f"API 服务 (REST/WS): http://localhost:{self.config.web_ui_port}", "info")
            print_status(f"API 文档: http://localhost:{self.config.web_ui_port}/docs", "info")
        if self.config.enable_device_api:
            print_status(f"设备 API: http://localhost:{self.config.device_api_port}", "info")
        _nats_url_display = os.environ.get("GALAXY_NATS_URL", "nats://localhost:4222 (默认)")
        print_status(f"NATS: {_nats_url_display}", "info")
        print_status("按 Ctrl+C 停止系统", "info")

        # ── 启动后立即执行健康检查 ──────────────────────────────────────────
        print_section("启动后健康检查")
        await self._run_startup_health_check()
        
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

    async def _run_startup_health_check(self):
        """启动后立即执行健康检查；失败时打印详细诊断。"""
        import socket

        base_url = f"http://localhost:{self.config.web_ui_port}"
        node71_url = "http://localhost:8071"
        nats_host = "localhost"
        nats_port = 4222
        all_ok = True

        # 1) Gateway / core health
        try:
            import urllib.request
            with urllib.request.urlopen(f"{base_url}/health", timeout=5) as resp:
                code = resp.getcode()
            print_status(f"Launcher /health: HTTP {code}", "success")
        except Exception as exc:
            print_status(f"Launcher /health: 失败 — {exc}", "error")
            all_ok = False

        # 2) system info
        try:
            with urllib.request.urlopen(f"{base_url}/api/v1/system/info", timeout=5) as resp:
                code = resp.getcode()
            print_status(f"system/info: HTTP {code}", "success")
        except Exception as exc:
            print_status(f"system/info: 失败 — {exc}", "warning")

        # 3) Node_71 health
        try:
            with urllib.request.urlopen(f"{node71_url}/health", timeout=3) as resp:
                code = resp.getcode()
            print_status(f"Node_71 /health: HTTP {code}", "success")
        except Exception as exc:
            print_status(f"Node_71 /health: 不可达 — {exc}", "warning")

        # 4) NATS port 4222 check
        try:
            with socket.create_connection((nats_host, nats_port), timeout=3):
                pass
            print_status(f"NATS port {nats_port}: 已监听", "success")
        except Exception as exc:
            print_status(f"NATS port {nats_port}: 未监听 — {exc}", "error")
            all_ok = False

        # 5) Key port availability
        for port, label in [(self.config.web_ui_port, f"Launcher ({self.config.web_ui_port})"),
                            (8071, "Node_71 (8071)"),
                            (4222, "NATS (4222)")]:
            try:
                with socket.create_connection(("localhost", port), timeout=2):
                    print_status(f"端口 {port} ({label}): 已监听", "success")
            except Exception:
                pass  # already logged individually above

        # 6) Docker container status (best-effort)
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=nats", "--filter", "name=gateway",
                 "--filter", "name=node_71", "--format", "{{.Names}}\t{{.Status}}"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                print_status("Docker 容器状态:", "info")
                for line in result.stdout.strip().splitlines():
                    print(f"    {line}")
        except Exception:
            pass  # Docker not available or not used

        if not all_ok:
            print_section("健康检查诊断")
            _is_win = sys.platform.startswith("win")
            print_status("部分检查项失败，请检查以下内容:", "error")
            print_status("  1. NATS 服务: nats-server -p 4222", "error")
            if _is_win:
                print_status("  2. 端口冲突: netstat -ano | findstr :4222", "error")
                print_status("  3. 运行完整诊断: .\\scripts\\health_check.ps1", "error")
            else:
                print_status("  2. 端口冲突: lsof -i :4222 / lsof -i :8299", "error")
                print_status("  3. 运行完整诊断: bash scripts/health_check.sh", "error")
        else:
            print_status("所有健康检查通过 ✅", "success")

    async def _async_shutdown(self):
        """异步关闭核心子系统"""
        try:
            from core.startup import shutdown_subsystems
            await shutdown_subsystems()
        except Exception as e:
            logger.warning(f"子系统关闭异常: {e}")

        # Disconnect NATS bus gracefully
        try:
            from core.nats_bus import nats_bus
            await nats_bus.disconnect()
        except Exception as e:
            logger.warning(f"NATS Bus 关闭异常: {e}")
        
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


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="Galaxy - L4 级自主性智能系统（统一融合版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
权威启动路径:
    python main.py                          # ← 推荐（委托到 unified_launcher.py）
    python unified_launcher.py              # 等效主入口

已弃用的兼容性包装器（将在未来版本移除）:
    python start_galaxy.py                  # 兼容性包装器，已弃用
    python start_l4.py                      # 兼容性包装器，已弃用（PR6 已冻结）

示例:
    python unified_launcher.py              # 默认启动（完整模式）
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
    parser.add_argument("--port", "-p", type=int, default=8299, help="API 服务端口")
    parser.add_argument(
        "--docker-full",
        action="store_true",
        help="通过 Docker Compose 启动完整节点集（130 个节点 + 基础设施），等效于: "
             "docker compose -f docker-compose.full.yml --profile full up -d",
    )
    
    args = parser.parse_args()

    # ── --docker-full: 通过 Docker Compose 启动全量节点 ──────────────────
    if args.docker_full:
        print_banner()
        os.environ["GALAXY_BANNER_PRINTED"] = "1"
        print_section("Docker 全量节点启动 (--docker-full)")
        compose_file = PROJECT_ROOT / "docker-compose.full.yml"
        if not compose_file.exists():
            print_status_row(
                "docker-compose.full.yml",
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
            print_status_row("查看状态", "docker compose -f docker-compose.full.yml --profile full ps", "info")
            print_status_row("停止服务", "docker compose -f docker-compose.full.yml --profile full down", "info")
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
    
    # 启动系统
    try:
        asyncio.run(galaxy.start())
    except KeyboardInterrupt:
        galaxy.stop()


if __name__ == "__main__":
    main()
