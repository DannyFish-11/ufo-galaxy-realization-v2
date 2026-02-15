#!/usr/bin/env python3
"""
Galaxy - 统一启动入口
整合所有系统组件，提供一键启动
"""

import os
import sys
import asyncio
import logging
import argparse
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import json

# 设置项目路径
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("Galaxy")

# ============================================================================
# 系统配置
# ============================================================================

class GalaxySettings:
    """Galaxy 系统设置"""
    
    def __init__(self):
        # 基本信息
        self.name = os.getenv("GALAXY_NAME", "Galaxy")
        self.version = "2.0.9"
        self.node_id = os.getenv("UFO_NODE_ID", "master")
        self.node_role = os.getenv("UFO_NODE_ROLE", "coordinator")
        
        # 端口配置
        self.http_port = int(os.getenv("WEB_UI_PORT", "8080"))
        self.websocket_port = int(os.getenv("WEBSOCKET_PORT", "8765"))
        self.api_port = int(os.getenv("API_PORT", "8000"))
        
        # 环境配置
        self.environment = os.getenv("ENVIRONMENT", "production")
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self.debug = os.getenv("DEBUG", "false").lower() == "true"
        
        # 守护进程配置
        self.auto_start = os.getenv("AUTO_START", "true").lower() == "true"
        self.auto_restart = os.getenv("AUTO_RESTART", "true").lower() == "true"
        self.health_check = os.getenv("HEALTH_CHECK", "true").lower() == "true"
        self.max_restarts = int(os.getenv("MAX_RESTARTS", "5"))
        
        # LLM 路由配置
        self.llm_priority1_provider = os.getenv("LLM_PRIORITY1_PROVIDER", "openai")
        self.llm_priority1_model = os.getenv("LLM_PRIORITY1_MODEL", "gpt-4o")
        self.llm_priority2_provider = os.getenv("LLM_PRIORITY2_PROVIDER", "deepseek")
        self.llm_priority2_model = os.getenv("LLM_PRIORITY2_MODEL", "deepseek-chat")
        self.llm_priority3_provider = os.getenv("LLM_PRIORITY3_PROVIDER", "groq")
        self.llm_priority3_model = os.getenv("LLM_PRIORITY3_MODEL", "llama-3.1-70b-versatile")
        
        # 数据库配置
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        self.qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")

# ============================================================================
# 服务管理器
# ============================================================================

class ServiceManager:
    """服务管理器"""
    
    def __init__(self, settings: GalaxySettings):
        self.settings = settings
        self.processes: Dict[str, subprocess.Popen] = {}
        self.running = False
        self.restart_count = 0
        self.start_time = None
        
    def start_service(self, name: str, command: List[str], cwd: str = None) -> bool:
        """启动服务"""
        try:
            logger.info(f"启动服务: {name}")
            logger.info(f"  命令: {' '.join(command)}")
            
            process = subprocess.Popen(
                command,
                cwd=cwd or str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            self.processes[name] = process
            logger.info(f"  ✅ {name} 已启动 (PID: {process.pid})")
            return True
            
        except Exception as e:
            logger.error(f"  ❌ {name} 启动失败: {e}")
            return False
    
    def stop_service(self, name: str) -> bool:
        """停止服务"""
        if name not in self.processes:
            return True
            
        try:
            process = self.processes[name]
            process.terminate()
            
            # 等待进程结束
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            
            del self.processes[name]
            logger.info(f"  ✅ {name} 已停止")
            return True
            
        except Exception as e:
            logger.error(f"  ❌ {name} 停止失败: {e}")
            return False
    
    def stop_all(self):
        """停止所有服务"""
        logger.info("停止所有服务...")
        for name in list(self.processes.keys()):
            self.stop_service(name)
    
    def check_health(self) -> Dict[str, Any]:
        """健康检查"""
        status = {
            "timestamp": datetime.now().isoformat(),
            "uptime": str(datetime.now() - self.start_time) if self.start_time else "0:00:00",
            "services": {}
        }
        
        for name, process in self.processes.items():
            poll = process.poll()
            status["services"][name] = {
                "running": poll is None,
                "pid": process.pid,
                "exit_code": poll
            }
        
        return status

# ============================================================================
# Galaxy 主系统
# ============================================================================

class Galaxy:
    """Galaxy 主系统"""
    
    def __init__(self):
        self.settings = GalaxySettings()
        self.service_manager = ServiceManager(self.settings)
        self.running = False
        
        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """信号处理"""
        logger.info(f"收到信号 {signum}，正在关闭...")
        self.stop()
        sys.exit(0)
    
    def print_banner(self):
        """打印横幅"""
        banner = f"""
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║   ██████╗  █████╗  ██████╗ ██████╗ ███████╗                  ║
║   ██╔══██╗██╔══██╗██╔════╝██╔═══██╗██╔════╝                  ║
║   ██║  ██║███████║██║     ██║   ██║███████╗                  ║
║   ██║  ██║██╔══██║██║     ██║   ██║╚════██║                  ║
║   ██████╔╝██║  ██║╚██████╗╚██████╔╝███████║                  ║
║   ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝                  ║
║                                                               ║
║   Galaxy - L4 级自主性智能系统                                ║
║   版本: {self.settings.version}                                          ║
║   节点: {self.settings.node_id}                                           ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
"""
        print(banner)
    
    def start(self, mode: str = "full"):
        """启动系统"""
        self.print_banner()
        
        logger.info("=" * 60)
        logger.info("Galaxy 系统启动")
        logger.info("=" * 60)
        logger.info(f"模式: {mode}")
        logger.info(f"节点 ID: {self.settings.node_id}")
        logger.info(f"HTTP 端口: {self.settings.http_port}")
        logger.info(f"WebSocket 端口: {self.settings.websocket_port}")
        logger.info("")
        
        self.service_manager.start_time = datetime.now()
        self.running = True
        
        # 根据模式启动不同服务
        if mode == "minimal":
            self._start_minimal()
        elif mode == "daemon":
            self._start_daemon()
        else:
            self._start_full()
        
        # 启动主循环
        self._main_loop()
    
    def _start_minimal(self):
        """最小模式启动"""
        logger.info("启动最小模式...")
        
        # 启动核心服务
        self.service_manager.start_service(
            "gateway",
            [sys.executable, "-m", "uvicorn", 
             "galaxy_gateway.config_service:app",
             "--host", "0.0.0.0",
             "--port", str(self.settings.http_port)]
        )
    
    def _start_full(self):
        """完整模式启动"""
        logger.info("启动完整模式...")
        
        # 1. 启动配置服务
        self.service_manager.start_service(
            "config",
            [sys.executable, "-m", "uvicorn",
             "galaxy_gateway.config_service:app",
             "--host", "0.0.0.0",
             "--port", str(self.settings.http_port)]
        )
        
        time.sleep(1)  # 等待配置服务启动
        
        # 2. 启动主服务
        self.service_manager.start_service(
            "main",
            [sys.executable, "main.py", "--minimal"]
        )
        
        # 3. 启动节点发现
        self.service_manager.start_service(
            "discovery",
            [sys.executable, "-c",
             f"from core.node_discovery import get_node_discovery; "
             f"import asyncio; "
             f"asyncio.run(get_node_discovery('{self.settings.node_id}').start())"]
        )
    
    def _start_daemon(self):
        """守护进程模式启动"""
        logger.info("启动守护进程模式...")
        
        # 启动完整服务
        self._start_full()
        
        # 启动健康检查
        if self.settings.health_check:
            logger.info("健康检查已启用")
    
    def _main_loop(self):
        """主循环"""
        logger.info("")
        logger.info("=" * 60)
        logger.info("Galaxy 系统已启动")
        logger.info("=" * 60)
        logger.info("")
        logger.info(f"配置中心: http://localhost:{self.settings.http_port}/config")
        logger.info(f"设备管理: http://localhost:{self.settings.http_port}/devices")
        logger.info(f"API 文档: http://localhost:{self.settings.http_port}/docs")
        logger.info("")
        logger.info("按 Ctrl+C 停止系统")
        logger.info("")
        
        try:
            while self.running:
                # 健康检查
                if self.settings.health_check:
                    health = self.service_manager.check_health()
                    
                    # 检查是否有服务崩溃
                    for name, status in health["services"].items():
                        if not status["running"]:
                            logger.warning(f"服务 {name} 已停止 (退出码: {status['exit_code']})")
                            
                            # 自动重启
                            if self.settings.auto_restart and self.service_manager.restart_count < self.settings.max_restarts:
                                logger.info(f"正在重启 {name}...")
                                self.service_manager.restart_count += 1
                                
                time.sleep(10)  # 每 10 秒检查一次
                
        except KeyboardInterrupt:
            logger.info("收到中断信号")
        finally:
            self.stop()
    
    def stop(self):
        """停止系统"""
        logger.info("")
        logger.info("=" * 60)
        logger.info("Galaxy 系统关闭")
        logger.info("=" * 60)
        
        self.running = False
        self.service_manager.stop_all()
        
        logger.info("系统已关闭")

# ============================================================================
# 主函数
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Galaxy - L4 级自主性智能系统")
    
    parser.add_argument("--mode", "-m", 
                        choices=["full", "minimal", "daemon"],
                        default="full",
                        help="启动模式: full(完整), minimal(最小), daemon(守护)")
    
    parser.add_argument("--port", "-p",
                        type=int,
                        default=None,
                        help="HTTP 端口")
    
    parser.add_argument("--node-id",
                        default=None,
                        help="节点 ID")
    
    parser.add_argument("--version", "-v",
                        action="store_true",
                        help="显示版本")
    
    args = parser.parse_args()
    
    if args.version:
        print(f"Galaxy v{GalaxySettings().version}")
        return
    
    # 设置环境变量
    if args.port:
        os.environ["WEB_UI_PORT"] = str(args.port)
    if args.node_id:
        os.environ["UFO_NODE_ID"] = args.node_id
    
    # 启动系统
    galaxy = Galaxy()
    galaxy.start(mode=args.mode)

if __name__ == "__main__":
    main()
