#!/usr/bin/env python3
"""
Galaxy - 统一启动入口 (完整版)
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
        self.version = "2.1.2"
        self.node_id = os.getenv("UFO_NODE_ID", "master")
        
        # 端口配置
        self.http_port = int(os.getenv("WEB_UI_PORT", "8080"))
        self.websocket_port = int(os.getenv("WEBSOCKET_PORT", "8765"))
        
        # 守护进程配置
        self.auto_start = os.getenv("AUTO_START", "true").lower() == "true"
        self.auto_restart = os.getenv("AUTO_RESTART", "true").lower() == "true"
        self.health_check = os.getenv("HEALTH_CHECK", "true").lower() == "true"
        self.max_restarts = int(os.getenv("MAX_RESTARTS", "5"))

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
        
    def start_service(self, name: str, command: List[str]) -> bool:
        """启动服务"""
        try:
            logger.info(f"启动服务: {name}")
            
            process = subprocess.Popen(
                command,
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
    
    def stop_all(self):
        """停止所有服务"""
        for name, process in list(self.processes.items()):
            try:
                process.terminate()
                process.wait(timeout=5)
            except:
                process.kill()
            logger.info(f"  ✅ {name} 已停止")

# ============================================================================
# Galaxy 主系统
# ============================================================================

class Galaxy:
    """Galaxy 主系统"""
    
    def __init__(self):
        self.settings = GalaxySettings()
        self.service_manager = ServiceManager(self.settings)
        self.running = False
        
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        logger.info(f"收到信号 {signum}，正在关闭...")
        self.stop()
        sys.exit(0)
    
    def print_banner(self):
        """打印横幅"""
        print(f"""
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
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
""")
    
    def start(self, mode: str = "full"):
        """启动系统"""
        self.print_banner()
        
        logger.info("=" * 60)
        logger.info("Galaxy 系统启动")
        logger.info("=" * 60)
        logger.info(f"模式: {mode}")
        logger.info(f"HTTP 端口: {self.settings.http_port}")
        logger.info("")
        
        self.service_manager.start_time = datetime.now()
        self.running = True
        
        # 启动主应用 (整合所有服务)
        self.service_manager.start_service(
            "galaxy",
            [sys.executable, "-m", "uvicorn",
             "galaxy_gateway.main_app:app",
             "--host", "0.0.0.0",
             "--port", str(self.settings.http_port)]
        )
        
        # 主循环
        self._main_loop()
    
    def _main_loop(self):
        """主循环"""
        logger.info("")
        logger.info("=" * 60)
        logger.info("Galaxy 系统已启动")
        logger.info("=" * 60)
        logger.info("")
        logger.info(f"控制面板: http://localhost:{self.settings.http_port}")
        logger.info(f"配置中心: http://localhost:{self.settings.http_port}/config")
        logger.info(f"设备管理: http://localhost:{self.settings.http_port}/devices")
        logger.info(f"记忆中心: http://localhost:{self.settings.http_port}/memory")
        logger.info(f"AI 路由:  http://localhost:{self.settings.http_port}/router")
        logger.info(f"API 文档: http://localhost:{self.settings.http_port}/docs")
        logger.info("")
        logger.info("按 Ctrl+C 停止系统")
        logger.info("")
        
        try:
            while self.running:
                time.sleep(10)
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
    parser.add_argument("--mode", "-m", default="full", help="启动模式")
    parser.add_argument("--port", "-p", type=int, default=None, help="HTTP 端口")
    parser.add_argument("--version", "-v", action="store_true", help="显示版本")
    
    args = parser.parse_args()
    
    if args.version:
        print(f"Galaxy v{GalaxySettings().version}")
        return
    
    if args.port:
        os.environ["WEB_UI_PORT"] = str(args.port)
    
    galaxy = Galaxy()
    galaxy.start(mode=args.mode)

if __name__ == "__main__":
    main()
