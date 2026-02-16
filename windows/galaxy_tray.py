"""
Galaxy - Windows 系统托盘程序
一键启动，后台运行，托盘管理
"""

import os
import sys
import time
import signal
import subprocess
import threading
import webbrowser
from pathlib import Path

# 设置项目路径
PROJECT_ROOT = Path(__file__).parent.parent
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

# 配置
PORT = 8080
PID_FILE = PROJECT_ROOT / "galaxy.pid"
LOG_FILE = PROJECT_ROOT / "logs" / "galaxy.log"

def check_port():
    """检查端口"""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('localhost', PORT))
    sock.close()
    return result == 0

def get_pid():
    """获取 PID"""
    if PID_FILE.exists():
        try:
            return int(PID_FILE.read_text().strip())
        except:
            pass
    return None

def is_running():
    """检查是否运行"""
    pid = get_pid()
    if pid:
        try:
            os.kill(pid, 0)
            return True
        except:
            pass
    return check_port()

def start_service():
    """启动服务"""
    if is_running():
        return True
    
    # 启动脚本
    start_script = f'''
import sys
import os
sys.path.insert(0, "{PROJECT_ROOT}")
os.chdir("{PROJECT_ROOT}")

from galaxy_gateway.main_app import app
import uvicorn

uvicorn.run(app, host="0.0.0.0", port={PORT}, log_level="warning")
'''
    
    # 确保日志目录存在
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
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
    for _ in range(30):
        time.sleep(0.5)
        if check_port():
            return True
    
    return False

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
        except:
            pass
        PID_FILE.unlink(missing_ok=True)

def run_tray():
    """运行托盘"""
    try:
        import pystray
        from pystray import MenuItem as Item
        from PIL import Image, ImageDraw
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "pystray", "pillow"], capture_output=True)
        import pystray
        from pystray import MenuItem as Item
        from PIL import Image, ImageDraw
    
    def create_icon():
        """创建图标"""
        size = 64
        image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # 根据状态选择颜色
        color = (0, 212, 255) if is_running() else (255, 85, 85)
        
        # 画圆形
        draw.ellipse([8, 8, 56, 56], fill=color + (255,), outline=(255, 255, 255, 100), width=2)
        
        # 画 G
        center = 32
        draw.arc([center-15, center-15, center+15, center+15], 0, 270, fill=(255, 255, 255, 255), width=4)
        draw.line([(center, center-15), (center, center)], fill=(255, 255, 255, 255), width=4)
        
        return image
    
    def update_icon(icon):
        """更新图标"""
        icon.icon = create_icon()
        icon.title = f"Galaxy - {'运行中' if is_running() else '已停止'}"
    
    def on_open(icon, item):
        """打开界面"""
        webbrowser.open(f"http://localhost:{PORT}")
    
    def on_start(icon, item):
        """启动"""
        start_service()
        time.sleep(1)
        update_icon(icon)
    
    def on_stop(icon, item):
        """停止"""
        stop_service()
        time.sleep(1)
        update_icon(icon)
    
    def on_restart(icon, item):
        """重启"""
        stop_service()
        time.sleep(2)
        start_service()
        time.sleep(1)
        update_icon(icon)
    
    def on_exit(icon, item):
        """退出"""
        icon.stop()
    
    def setup(icon):
        """初始化"""
        # 自动启动服务
        if not is_running():
            start_service()
            time.sleep(1)
        update_icon(icon)
        
        # 自动打开浏览器
        webbrowser.open(f"http://localhost:{PORT}")
        
        # 定时更新图标
        def update_loop():
            while True:
                time.sleep(5)
                update_icon(icon)
        
        threading.Thread(target=update_loop, daemon=True).start()
    
    # 创建菜单
    menu = pystray.Menu(
        Item(lambda: f"Galaxy - {'运行中' if is_running() else '已停止'}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        Item("打开界面", on_open),
        Item("启动服务", on_start, visible=lambda item: not is_running()),
        Item("停止服务", on_stop, visible=lambda item: is_running()),
        Item("重启服务", on_restart),
        pystray.Menu.SEPARATOR,
        Item("退出", on_exit),
    )
    
    # 创建图标
    icon = pystray.Icon("Galaxy", create_icon(), "Galaxy", menu)
    
    # 运行
    icon.run(setup=setup)

if __name__ == "__main__":
    print("Galaxy 系统托盘启动中...")
    run_tray()
