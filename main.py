#!/usr/bin/env python3
"""
UFO Galaxy - 主启动入口
========================
一键启动整个 UFO Galaxy 系统。

功能：
1. 自动检测和加载配置
2. 自动安装缺失的依赖
3. 智能启动节点系统
4. 提供 Web UI 界面
5. 支持命令行参数

使用方法：
    python main.py              # 默认启动
    python main.py --setup      # 运行配置向导
    python main.py --minimal    # 最小启动（仅核心节点）
    python main.py --ui         # 启动 Web UI
    python main.py --status     # 查看系统状态
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
logger = logging.getLogger("UFO-Galaxy")


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


def print_banner():
    """打印启动横幅"""
    banner = f"""
{Colors.CYAN}{Colors.BOLD}
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║     ██╗   ██╗███████╗ ██████╗                            ║
    ║     ██║   ██║██╔════╝██╔═══██╗                           ║
    ║     ██║   ██║█████╗  ██║   ██║                           ║
    ║     ██║   ██║██╔══╝  ██║   ██║                           ║
    ║     ╚██████╔╝██║     ╚██████╔╝                           ║
    ║      ╚═════╝ ╚═╝      ╚═════╝                            ║
    ║                                                           ║
    ║      ██████╗  █████╗ ██╗      █████╗ ██╗  ██╗██╗   ██╗  ║
    ║     ██╔════╝ ██╔══██╗██║     ██╔══██╗╚██╗██╔╝╚██╗ ██╔╝  ║
    ║     ██║  ███╗███████║██║     ███████║ ╚███╔╝  ╚████╔╝   ║
    ║     ██║   ██║██╔══██║██║     ██╔══██║ ██╔██╗   ╚██╔╝    ║
    ║     ╚██████╔╝██║  ██║███████╗██║  ██║██╔╝ ██╗   ██║     ║
    ║      ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝     ║
    ║                                                           ║
    ║              L4 级自主性智能系统 v1.0                     ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
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
    }
    icon = icons.get(status, icons["info"])
    print(f"{icon} {message}{Colors.ENDC}")


class ConfigManager:
    """配置管理器"""
    
    def __init__(self):
        self.env_file = PROJECT_ROOT / ".env"
        self.config: Dict[str, str] = {}
        self.required_apis = ["OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "XAI_API_KEY"]
        
    def load(self) -> bool:
        """加载配置"""
        # 1. 从 .env 文件加载
        if self.env_file.exists():
            with open(self.env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        self.config[key.strip()] = value.strip()
                        os.environ[key.strip()] = value.strip()
                        
        # 2. 从环境变量补充
        for key in self.required_apis:
            if key not in self.config:
                env_value = os.environ.get(key)
                if env_value:
                    self.config[key] = env_value
                    
        return self.validate()
        
    def validate(self) -> bool:
        """验证配置"""
        # 检查是否至少有一个 LLM API
        has_llm = any(
            self.config.get(key) 
            for key in self.required_apis
        )
        return has_llm
        
    def get_status(self) -> Dict[str, Any]:
        """获取配置状态"""
        return {
            "llm_apis": {
                key: bool(self.config.get(key))
                for key in self.required_apis
            },
            "database": {
                "postgresql": bool(self.config.get("DATABASE_URL")),
                "redis": bool(self.config.get("REDIS_URL")),
                "qdrant": bool(self.config.get("QDRANT_URL")),
            },
            "services": {
                "github": bool(self.config.get("GITHUB_TOKEN")),
                "weather": bool(self.config.get("OPENWEATHERMAP_API_KEY")),
                "search": bool(self.config.get("BRAVE_API_KEY")),
            }
        }


class DependencyManager:
    """依赖管理器"""
    
    REQUIRED_PACKAGES = [
        "aiohttp",
        "fastapi",
        "uvicorn",
        "pydantic",
        "python-dotenv",
        "psutil",
        "httpx",
    ]
    
    @classmethod
    def check_and_install(cls) -> bool:
        """检查并安装依赖"""
        missing = []
        
        for package in cls.REQUIRED_PACKAGES:
            try:
                __import__(package.replace("-", "_"))
            except ImportError:
                missing.append(package)
                
        if missing:
            print_status(f"安装缺失的依赖: {', '.join(missing)}", "loading")
            try:
                subprocess.check_call([
                    sys.executable, "-m", "pip", "install", 
                    "--quiet", "--disable-pip-version-check"
                ] + missing)
                print_status("依赖安装完成", "success")
                return True
            except subprocess.CalledProcessError:
                print_status("依赖安装失败，请手动运行: pip install -r requirements.txt", "error")
                return False
        return True


class NodeManager:
    """节点管理器"""
    
    def __init__(self):
        self.nodes_dir = PROJECT_ROOT / "nodes"
        self.running_nodes: Dict[str, subprocess.Popen] = {}
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
            
        try:
            process = subprocess.Popen(
                [sys.executable, str(main_py)],
                cwd=str(node_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
            )
            self.running_nodes[node_name] = process
            return True
        except Exception as e:
            logger.error(f"启动节点 {node_name} 失败: {e}")
            return False
            
    async def start_nodes(self, nodes: List[str], parallel: bool = False) -> Dict[str, bool]:
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
                await asyncio.sleep(0.1)  # 短暂延迟
                
        return results
        
    def stop_all(self):
        """停止所有节点"""
        for name, process in self.running_nodes.items():
            try:
                process.terminate()
                process.wait(timeout=5)
            except:
                process.kill()
        self.running_nodes.clear()
        
    def get_status(self) -> Dict[str, str]:
        """获取节点状态"""
        status = {}
        for name, process in self.running_nodes.items():
            if process.poll() is None:
                status[name] = "running"
            else:
                status[name] = "stopped"
        return status


class WebUIServer:
    """Web UI 服务器"""
    
    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self.host = host
        self.port = port
        self.app = None
        
    async def start(self):
        """启动 Web UI"""
        try:
            from fastapi import FastAPI, HTTPException
            from fastapi.responses import HTMLResponse, JSONResponse
            from fastapi.staticfiles import StaticFiles
            import uvicorn
            
            self.app = FastAPI(title="UFO Galaxy", version="1.0")
            
            @self.app.get("/", response_class=HTMLResponse)
            async def index():
                return self._get_dashboard_html()
                
            @self.app.get("/api/status")
            async def status():
                return JSONResponse({
                    "status": "running",
                    "version": "1.0",
                    "nodes": node_manager.get_status() if 'node_manager' in globals() else {}
                })
                
            config = uvicorn.Config(
                self.app, 
                host=self.host, 
                port=self.port, 
                log_level="warning"
            )
            server = uvicorn.Server(config)
            await server.serve()
            
        except ImportError:
            print_status("Web UI 依赖未安装，跳过 Web UI", "warning")
            
    def _get_dashboard_html(self) -> str:
        """获取仪表板 HTML"""
        return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UFO Galaxy - 控制面板</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            color: #fff;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .header {
            text-align: center;
            padding: 40px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .header h1 {
            font-size: 3rem;
            background: linear-gradient(90deg, #00d4ff, #7b2cbf);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-top: 30px;
        }
        .status-card {
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            padding: 24px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .status-card h3 {
            color: #00d4ff;
            margin-bottom: 16px;
        }
        .status-item {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 8px;
        }
        .status-dot.active { background: #00ff88; }
        .status-dot.inactive { background: #ff4444; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🌌 UFO Galaxy</h1>
            <p>L4 级自主性智能系统</p>
        </div>
        <div class="status-grid">
            <div class="status-card">
                <h3>系统状态</h3>
                <div class="status-item">
                    <span><span class="status-dot active"></span>系统运行中</span>
                    <span id="uptime">--</span>
                </div>
            </div>
            <div class="status-card">
                <h3>API 状态</h3>
                <div id="api-status">加载中...</div>
            </div>
            <div class="status-card">
                <h3>节点状态</h3>
                <div id="node-status">加载中...</div>
            </div>
        </div>
    </div>
    <script>
        async function updateStatus() {
            try {
                const resp = await fetch('/api/status');
                const data = await resp.json();
                document.getElementById('api-status').innerHTML = 
                    '<div class="status-item"><span class="status-dot active"></span>已连接</div>';
            } catch (e) {
                console.error(e);
            }
        }
        updateStatus();
        setInterval(updateStatus, 5000);
    </script>
</body>
</html>
        """


class UFOGalaxy:
    """UFO Galaxy 主系统"""
    
    def __init__(self):
        self.config_manager = ConfigManager()
        self.node_manager = NodeManager()
        self.web_ui: Optional[WebUIServer] = None
        self.running = False
        
    async def start(self, minimal: bool = False, with_ui: bool = True):
        """启动系统"""
        print_banner()
        
        # 1. 检查依赖
        print_status("检查依赖...", "loading")
        if not DependencyManager.check_and_install():
            return False
            
        # 2. 加载配置
        print_status("加载配置...", "loading")
        if not self.config_manager.load():
            print_status("未检测到有效的 API 配置", "warning")
            print_status("运行 'python setup_wizard.py' 进行配置", "info")
            # 继续运行，使用模拟模式
            
        # 显示配置状态
        status = self.config_manager.get_status()
        llm_count = sum(1 for v in status["llm_apis"].values() if v)
        print_status(f"检测到 {llm_count} 个 LLM API", "success" if llm_count > 0 else "warning")
        
        # 3. 启动节点
        print_status("启动节点系统...", "loading")
        if minimal:
            nodes = self.node_manager.get_core_nodes()[:5]  # 只启动前5个核心节点
        else:
            nodes = self.node_manager.get_core_nodes()
            
        if nodes:
            results = await self.node_manager.start_nodes(nodes)
            success_count = sum(1 for v in results.values() if v)
            print_status(f"已启动 {success_count}/{len(nodes)} 个节点", "success")
        else:
            print_status("未找到节点配置，跳过节点启动", "warning")
            
        # 4. 启动 Web UI
        if with_ui:
            print_status("启动 Web UI...", "loading")
            self.web_ui = WebUIServer()
            print_status(f"Web UI 已启动: http://localhost:8080", "success")
            
        self.running = True
        print()
        print_status("=" * 50, "info")
        print_status("UFO Galaxy 系统已启动！", "success")
        print_status("=" * 50, "info")
        print()
        print_status("访问 http://localhost:8080 查看控制面板", "info")
        print_status("按 Ctrl+C 停止系统", "info")
        
        # 保持运行
        if with_ui and self.web_ui:
            await self.web_ui.start()
        else:
            while self.running:
                await asyncio.sleep(1)
                
    def stop(self):
        """停止系统"""
        print()
        print_status("正在停止系统...", "loading")
        self.running = False
        self.node_manager.stop_all()
        print_status("系统已停止", "success")
        
    def show_status(self):
        """显示系统状态"""
        print_banner()
        
        # 配置状态
        self.config_manager.load()
        status = self.config_manager.get_status()
        
        print(f"\n{Colors.BOLD}=== API 配置状态 ==={Colors.ENDC}")
        for api, configured in status["llm_apis"].items():
            icon = "✅" if configured else "❌"
            print(f"  {icon} {api}")
            
        print(f"\n{Colors.BOLD}=== 数据库状态 ==={Colors.ENDC}")
        for db, configured in status["database"].items():
            icon = "✅" if configured else "❌"
            print(f"  {icon} {db}")
            
        print(f"\n{Colors.BOLD}=== 节点统计 ==={Colors.ENDC}")
        all_nodes = self.node_manager.get_all_nodes()
        core_nodes = self.node_manager.get_core_nodes()
        print(f"  总节点数: {len(all_nodes)}")
        print(f"  核心节点: {len(core_nodes)}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="UFO Galaxy - L4 级自主性智能系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python main.py              # 默认启动
    python main.py --setup      # 运行配置向导
    python main.py --minimal    # 最小启动
    python main.py --status     # 查看状态
        """
    )
    parser.add_argument("--setup", "-s", action="store_true", help="运行配置向导")
    parser.add_argument("--minimal", "-m", action="store_true", help="最小启动（仅核心节点）")
    parser.add_argument("--no-ui", action="store_true", help="不启动 Web UI")
    parser.add_argument("--status", action="store_true", help="查看系统状态")
    parser.add_argument("--port", "-p", type=int, default=8080, help="Web UI 端口")
    
    args = parser.parse_args()
    
    # 运行配置向导
    if args.setup:
        from setup_wizard import SetupWizard
        wizard = SetupWizard()
        wizard.run_interactive_setup()
        return
        
    # 创建系统实例
    galaxy = UFOGalaxy()
    
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
        asyncio.run(galaxy.start(
            minimal=args.minimal,
            with_ui=not args.no_ui
        ))
    except KeyboardInterrupt:
        galaxy.stop()


if __name__ == "__main__":
    main()
