#!/usr/bin/env python3
"""
Galaxy - 群智能系统启动入口
==========================
一键启动，自动后台运行，系统托盘管理

Galaxy 是一个有机的整体，不是一堆独立的服务
"""

import os
import sys
import time
import json
import signal
import subprocess
import threading
import webbrowser
from pathlib import Path
from datetime import datetime

# 设置项目路径
PROJECT_ROOT = Path(__file__).parent.absolute()
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

# ============================================================================
# 配置
# ============================================================================

VERSION = "2.1.9"
PORT = 8080
PID_FILE = PROJECT_ROOT / "galaxy.pid"
LOG_FILE = PROJECT_ROOT / "logs" / "galaxy.log"

# ============================================================================
# 工具函数
# ============================================================================

def print_banner():
    """打印横幅"""
    print()
    print("=" * 60)
    print("   ██████╗  █████╗ ██╗      █████╗ ██╗  ██╗██╗   ██╗")
    print("   ██╔════╝ ██╔══██╗██║     ██╔══██╗╚██╗██╔╝╚██╗ ██╔╝")
    print("   ██║  ███╗███████║██║     ███████║ ╚███╔╝  ╚████╔╝ ")
    print("   ██║   ██║██╔══██║██║     ██╔══██║ ██╔██╗   ╚██╔╝  ")
    print("   ╚██████╔╝██║  ██║███████╗██║  ██║██╔╝ ██╗   ██║   ")
    print("    ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ")
    print()
    print(f"   Galaxy - L4 级群智能系统 v{VERSION}")
    print("   一个有机的整体，不是一堆独立的服务")
    print("=" * 60)
    print()

def log(message):
    """打印日志"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

def check_dependencies():
    """检查依赖"""
    log("检查依赖...")
    
    required = ["fastapi", "uvicorn", "pydantic", "httpx"]
    missing = []
    
    for pkg in required:
        try:
            __import__(pkg)
            log(f"  ✅ {pkg}")
        except ImportError:
            log(f"  ❌ {pkg} 未安装")
            missing.append(pkg)
    
    if missing:
        log(f"\n正在安装缺失的依赖: {missing}")
        subprocess.run([sys.executable, "-m", "pip", "install"] + missing, capture_output=True)
        log("依赖安装完成")
    
    return True

def ensure_directories():
    """确保目录存在"""
    dirs = ["config", "data/memory", "data/api_keys", "logs"]
    for d in dirs:
        (PROJECT_ROOT / d).mkdir(parents=True, exist_ok=True)

def check_port():
    """检查端口是否被占用"""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('localhost', PORT))
    sock.close()
    return result == 0

def get_pid():
    """获取运行中的 PID"""
    if PID_FILE.exists():
        try:
            return int(PID_FILE.read_text().strip())
        except:
            return None
    return None

def is_running():
    """检查服务是否在运行"""
    pid = get_pid()
    if pid:
        try:
            os.kill(pid, 0)
            return True
        except:
            pass
    return check_port()

def stop_service():
    """停止服务"""
    pid = get_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(2)
            try:
                os.kill(pid, signal.SIGKILL)
            except:
                pass
            log("服务已停止")
        except:
            pass
        PID_FILE.unlink(missing_ok=True)

def start_service():
    """启动服务"""
    if is_running():
        log("服务已在运行中")
        return True
    
    log("启动 Galaxy 群智能系统...")
    
    # 创建启动脚本
    start_script = f'''
import sys
import os
sys.path.insert(0, "{PROJECT_ROOT}")
os.chdir("{PROJECT_ROOT}")

# 初始化群智能核心
from core.swarm_core import get_swarm_core
core = get_swarm_core()
print(f"群智能核心已初始化: {{core.name}} v{{core.version}}")
print(f"可用能力: {{len(core.capability_pool.capabilities)}} 个")

# 启动服务
from galaxy_gateway.main_app import app
import uvicorn

uvicorn.run(app, host="0.0.0.0", port={PORT}, log_level="warning")
'''
    
    # 后台启动
    process = subprocess.Popen(
        [sys.executable, "-c", start_script],
        stdout=open(LOG_FILE, 'a'),
        stderr=subprocess.STDOUT,
        cwd=str(PROJECT_ROOT)
    )
    
    # 保存 PID
    PID_FILE.write_text(str(process.pid))
    
    # 等待启动
    for i in range(30):
        time.sleep(0.5)
        if check_port():
            log(f"服务已启动 (PID: {process.pid})")
            return True
    
    log("服务启动超时")
    return False

def open_browser():
    """打开浏览器"""
    time.sleep(1)
    webbrowser.open(f"http://localhost:{PORT}")

# ============================================================================
# 系统托盘
# ============================================================================

def run_tray():
    """运行系统托盘"""
    try:
        import pystray
        from pystray import MenuItem as Item
        from PIL import Image, ImageDraw
    except ImportError:
        log("安装托盘依赖...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pystray", "pillow"], capture_output=True)
        import pystray
        from pystray import MenuItem as Item
        from PIL import Image, ImageDraw
    
    def create_icon():
        """创建图标"""
        size = 64
        image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # 画圆形
        draw.ellipse([8, 8, 56, 56], fill=(0, 212, 255, 255), outline=(255, 255, 255, 100), width=2)
        
        # 画 G
        center = 32
        draw.arc([center-15, center-15, center+15, center+15], 0, 270, fill=(255, 255, 255, 255), width=4)
        draw.line([(center, center-15), (center, center)], fill=(255, 255, 255, 255), width=4)
        
        return image
    
    def get_status():
        """获取状态"""
        return "运行中" if is_running() else "已停止"
    
    def on_open(icon, item):
        """打开界面"""
        webbrowser.open(f"http://localhost:{PORT}")
    
    def on_capabilities(icon, item):
        """打开能力中心"""
        webbrowser.open(f"http://localhost:{PORT}/capabilities")
    
    def on_start(icon, item):
        """启动服务"""
        start_service()
    
    def on_stop(icon, item):
        """停止服务"""
        stop_service()
    
    def on_restart(icon, item):
        """重启服务"""
        stop_service()
        time.sleep(1)
        start_service()
    
    def on_exit(icon, item):
        """退出"""
        icon.stop()
    
    # 创建菜单
    menu = pystray.Menu(
        Item(lambda: f"Galaxy - {get_status()}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        Item("打开界面", on_open),
        Item("能力中心", on_capabilities),
        pystray.Menu.SEPARATOR,
        Item("启动服务", on_start, visible=lambda item: not is_running()),
        Item("停止服务", on_stop, visible=lambda item: is_running()),
        Item("重启服务", on_restart),
        pystray.Menu.SEPARATOR,
        Item("退出", on_exit),
    )
    
    # 创建图标
    icon = pystray.Icon("Galaxy", create_icon(), "Galaxy", menu)
    
    log("系统托盘已启动")
    log(f"访问地址: http://localhost:{PORT}")
    log("右键托盘图标可管理服务")
    
    # 运行托盘
    icon.run()

# ============================================================================
# 主函数
# ============================================================================

def main():
    """主函数"""
    print_banner()
    
    # 确保目录
    ensure_directories()
    
    # 检查依赖
    check_dependencies()
    
    # 检查是否已运行
    if is_running():
        log("服务已在运行中")
    else:
        # 启动服务
        if not start_service():
            log("服务启动失败")
            return 1
    
    # 打开浏览器
    log("正在打开浏览器...")
    threading.Thread(target=open_browser, daemon=True).start()
    
    # 运行系统托盘
    run_tray()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
