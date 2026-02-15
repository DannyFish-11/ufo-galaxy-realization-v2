#!/usr/bin/env python3
"""
Galaxy - 统一启动入口
=====================
一键启动整个 Galaxy 系统

使用方法:
    python main.py              # 默认启动
    python main.py --setup      # 运行配置向导
    python main.py --check      # 系统检查
    python main.py --status     # 查看状态
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
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

# 设置项目根目录
PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("Galaxy")

# ============================================================================
# 版本信息
# ============================================================================

VERSION = "2.1.6"
VERSION_INFO = {
    "version": VERSION,
    "name": "Galaxy",
    "description": "L4 级自主性智能系统",
    "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
}

# ============================================================================
# 配置
# ============================================================================

@dataclass
class GalaxyConfig:
    """Galaxy 配置"""
    # 基本信息
    name: str = "Galaxy"
    version: str = VERSION
    node_id: str = "master"
    node_role: str = "coordinator"
    
    # 端口配置
    http_port: int = 8080
    websocket_port: int = 8765
    
    # 运行模式
    mode: str = "full"  # full, minimal, daemon
    
    # 功能开关
    enable_memory: bool = True
    enable_ai_router: bool = True
    enable_device_manager: bool = True
    enable_api_keys: bool = True

def load_config() -> GalaxyConfig:
    """加载配置"""
    config = GalaxyConfig()
    
    # 从环境变量加载
    config.node_id = os.getenv("GALAXY_NODE_ID", config.node_id)
    config.node_role = os.getenv("GALAXY_NODE_ROLE", config.node_role)
    config.http_port = int(os.getenv("WEB_UI_PORT", str(config.http_port)))
    config.websocket_port = int(os.getenv("WEBSOCKET_PORT", str(config.websocket_port)))
    
    # 从配置文件加载
    config_file = PROJECT_ROOT / "config" / "galaxy.json"
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for key, value in data.items():
                    if hasattr(config, key):
                        setattr(config, key, value)
        except Exception as e:
            logger.warning(f"加载配置文件失败: {e}")
    
    return config

# ============================================================================
# 系统检查
# ============================================================================

def check_system() -> Dict[str, Any]:
    """检查系统完整性"""
    results = {
        "passed": 0,
        "failed": 0,
        "warnings": 0,
        "checks": []
    }
    
    def check(name: str, condition: bool, required: bool = True):
        if condition:
            results["passed"] += 1
            results["checks"].append({"name": name, "status": "pass"})
            print(f"  ✅ {name}")
        else:
            if required:
                results["failed"] += 1
                results["checks"].append({"name": name, "status": "fail"})
                print(f"  ❌ {name}")
            else:
                results["warnings"] += 1
                results["checks"].append({"name": name, "status": "warn"})
                print(f"  ⚠️  {name}")
    
    print("\n系统检查:")
    print("-" * 40)
    
    # 核心文件
    check("main.py", (PROJECT_ROOT / "main.py").exists())
    check("run_galaxy.py", (PROJECT_ROOT / "run_galaxy.py").exists())
    check("requirements.txt", (PROJECT_ROOT / "requirements.txt").exists())
    check(".env.example", (PROJECT_ROOT / ".env.example").exists())
    
    # 核心模块
    check("core/memory.py", (PROJECT_ROOT / "core" / "memory.py").exists())
    check("core/ai_router.py", (PROJECT_ROOT / "core" / "ai_router.py").exists())
    check("core/llm_router.py", (PROJECT_ROOT / "core" / "llm_router.py").exists())
    check("core/api_key_manager.py", (PROJECT_ROOT / "core" / "api_key_manager.py").exists())
    
    # 服务模块
    check("galaxy_gateway/main_app.py", (PROJECT_ROOT / "galaxy_gateway" / "main_app.py").exists())
    check("galaxy_gateway/config_service.py", (PROJECT_ROOT / "galaxy_gateway" / "config_service.py").exists())
    check("galaxy_gateway/memory_service.py", (PROJECT_ROOT / "galaxy_gateway" / "memory_service.py").exists())
    check("galaxy_gateway/router_service.py", (PROJECT_ROOT / "galaxy_gateway" / "router_service.py").exists())
    check("galaxy_gateway/api_keys_service.py", (PROJECT_ROOT / "galaxy_gateway" / "api_keys_service.py").exists())
    
    # 界面文件
    check("dashboard.html", (PROJECT_ROOT / "galaxy_gateway" / "static" / "dashboard.html").exists())
    check("config.html", (PROJECT_ROOT / "galaxy_gateway" / "static" / "config.html").exists())
    check("memory.html", (PROJECT_ROOT / "galaxy_gateway" / "static" / "memory.html").exists())
    check("router.html", (PROJECT_ROOT / "galaxy_gateway" / "static" / "router.html").exists())
    check("api_keys.html", (PROJECT_ROOT / "galaxy_gateway" / "static" / "api_keys.html").exists())
    
    # Python 依赖
    try:
        import fastapi
        check("fastapi", True)
    except ImportError:
        check("fastapi", False)
    
    try:
        import uvicorn
        check("uvicorn", True)
    except ImportError:
        check("uvicorn", False)
    
    try:
        import pydantic
        check("pydantic", True)
    except ImportError:
        check("pydantic", False)
    
    # 配置文件
    check(".env 配置", (PROJECT_ROOT / ".env").exists(), required=False)
    
    print("-" * 40)
    print(f"通过: {results['passed']}, 失败: {results['failed']}, 警告: {results['warnings']}")
    
    return results

# ============================================================================
# 服务管理
# ============================================================================

class GalaxyService:
    """Galaxy 服务管理"""
    
    def __init__(self, config: GalaxyConfig):
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self.running = False
        
        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """信号处理"""
        logger.info(f"收到信号 {signum}，正在关闭...")
        self.stop()
        sys.exit(0)
    
    def start(self):
        """启动服务"""
        logger.info("=" * 60)
        logger.info("Galaxy 系统启动")
        logger.info("=" * 60)
        logger.info(f"版本: {VERSION}")
        logger.info(f"模式: {self.config.mode}")
        logger.info(f"HTTP 端口: {self.config.http_port}")
        logger.info("")
        
        # 启动主应用
        self._start_main_app()
        
        self.running = True
        
        # 显示访问地址
        self._show_urls()
        
        # 主循环
        self._main_loop()
    
    def _start_main_app(self):
        """启动主应用"""
        logger.info("启动主应用...")
        
        # 使用 uvicorn 启动
        import uvicorn
        from galaxy_gateway.main_app import app
        
        # 在后台线程运行
        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=self.config.http_port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        
        # 运行服务器
        asyncio.run(server.serve())
    
    def _show_urls(self):
        """显示访问地址"""
        logger.info("")
        logger.info("=" * 60)
        logger.info("Galaxy 系统已启动")
        logger.info("=" * 60)
        logger.info("")
        logger.info("访问地址:")
        logger.info(f"  控制面板: http://localhost:{self.config.http_port}")
        logger.info(f"  配置中心: http://localhost:{self.config.http_port}/config")
        logger.info(f"  设备管理: http://localhost:{self.config.http_port}/devices")
        logger.info(f"  记忆中心: http://localhost:{self.config.http_port}/memory")
        logger.info(f"  AI 路由:  http://localhost:{self.config.http_port}/router")
        logger.info(f"  API Key:  http://localhost:{self.config.http_port}/api-keys")
        logger.info(f"  API 文档: http://localhost:{self.config.http_port}/docs")
        logger.info("")
        logger.info("按 Ctrl+C 停止系统")
        logger.info("")
    
    def _main_loop(self):
        """主循环"""
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("收到中断信号")
        finally:
            self.stop()
    
    def stop(self):
        """停止服务"""
        logger.info("")
        logger.info("=" * 60)
        logger.info("Galaxy 系统关闭")
        logger.info("=" * 60)
        self.running = False

# ============================================================================
# 主函数
# ============================================================================

def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="Galaxy - L4 级自主性智能系统",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument("--setup", action="store_true", help="运行配置向导")
    parser.add_argument("--check", action="store_true", help="系统检查")
    parser.add_argument("--status", action="store_true", help="查看状态")
    parser.add_argument("--version", "-v", action="store_true", help="显示版本")
    parser.add_argument("--mode", "-m", default="full", choices=["full", "minimal", "daemon"], help="运行模式")
    parser.add_argument("--port", "-p", type=int, help="HTTP 端口")
    
    args = parser.parse_args()
    
    # 显示版本
    if args.version:
        print(f"Galaxy v{VERSION}")
        return
    
    # 系统检查
    if args.check:
        results = check_system()
        if results["failed"] > 0:
            sys.exit(1)
        return
    
    # 加载配置
    config = load_config()
    
    # 应用命令行参数
    if args.port:
        config.http_port = args.port
    if args.mode:
        config.mode = args.mode
    
    # 启动服务
    service = GalaxyService(config)
    service.start()

if __name__ == "__main__":
    main()
