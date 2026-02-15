"""
Galaxy - Windows 系统托盘程序
显示在右下角托盘区，实时显示系统状态
"""

import os
import sys
import time
import threading
import subprocess
import webbrowser
from pathlib import Path

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import pystray
    from pystray import MenuItem as Item
    from PIL import Image, ImageDraw
except ImportError:
    print("请安装依赖: pip install pystray pillow")
    sys.exit(1)

import requests

# ============================================================================
# 配置
# ============================================================================

GALAXY_URL = os.getenv("GALAXY_URL", "http://localhost:8080")
CHECK_INTERVAL = 10  # 状态检查间隔（秒）

# ============================================================================
# 托盘图标
# ============================================================================

def create_icon_image(status="running"):
    """创建托盘图标"""
    # 创建 64x64 图标
    size = 64
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # 根据状态选择颜色
    colors = {
        "running": (0, 212, 255),      # 青色 - 运行中
        "warning": (255, 170, 0),      # 黄色 - 部分异常
        "stopped": (255, 85, 85),      # 红色 - 已停止
        "sleeping": (128, 128, 128),   # 灰色 - 待机
    }
    color = colors.get(status, (0, 212, 255))
    
    # 画圆形背景
    margin = 8
    draw.ellipse(
        [margin, margin, size-margin, size-margin],
        fill=color + (255,),
        outline=(255, 255, 255, 100),
        width=2
    )
    
    # 画 G 字母
    center = size // 2
    draw.arc(
        [center-15, center-15, center+15, center+15],
        start=0, end=270,
        fill=(255, 255, 255, 255),
        width=4
    )
    draw.line(
        [(center, center-15), (center, center)],
        fill=(255, 255, 255, 255),
        width=4
    )
    
    return image

# ============================================================================
# 状态检查
# ============================================================================

class GalaxyMonitor:
    """Galaxy 状态监控"""
    
    def __init__(self):
        self.status = "stopped"
        self.nodes_online = 0
        self.nodes_total = 0
        self.last_check = None
        self.running = True
        
    def check_status(self):
        """检查系统状态"""
        try:
            # 检查主服务
            response = requests.get(f"{GALAXY_URL}/api/status", timeout=5)
            if response.status_code == 200:
                data = response.json()
                self.status = data.get("status", "running")
                
                # 获取节点状态
                try:
                    nodes_response = requests.get(f"{GALAXY_URL}/api/nodes/status", timeout=5)
                    if nodes_response.status_code == 200:
                        nodes_data = nodes_response.json()
                        self.nodes_online = nodes_data.get("online", 0)
                        self.nodes_total = nodes_data.get("total", 0)
                except:
                    pass
                    
                self.last_check = time.time()
                return True
            else:
                self.status = "stopped"
                return False
        except:
            self.status = "stopped"
            return False
    
    def get_status_text(self):
        """获取状态文本"""
        if self.status == "running":
            return f"🟢 运行中 ({self.nodes_online}/{self.nodes_total} 节点)"
        elif self.status == "warning":
            return f"🟡 部分异常 ({self.nodes_online}/{self.nodes_total} 节点)"
        elif self.status == "sleeping":
            return "⚪ 待机中"
        else:
            return "🔴 已停止"

# ============================================================================
# 托盘应用
# ============================================================================

class GalaxyTray:
    """Galaxy 托盘应用"""
    
    def __init__(self):
        self.monitor = GalaxyMonitor()
        self.icon = None
        
        # 创建图标
        self.icon_image = create_icon_image("stopped")
        
        # 创建菜单
        self.menu = self._create_menu()
        
    def _create_menu(self):
        """创建菜单"""
        return pystray.Menu(
            Item(lambda: f"Galaxy - {self.monitor.get_status_text()}", None, enabled=False),
            Item(lambda: f"节点: {self.monitor.nodes_online}/{self.monitor.nodes_total}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            Item("打开控制面板", self._open_dashboard),
            Item("打开配置", self._open_config),
            Item("打开 API 文档", self._open_api_docs),
            pystray.Menu.SEPARATOR,
            Item("重启服务", self._restart_service),
            Item("停止服务", self._stop_service),
            pystray.Menu.SEPARATOR,
            Item("开机自启动", self._toggle_autostart, checked=lambda item: self._is_autostart()),
            pystray.Menu.SEPARATOR,
            Item("退出", self._quit),
        )
    
    def _open_dashboard(self, icon, item):
        """打开控制面板"""
        webbrowser.open(f"{GALAXY_URL}/")
    
    def _open_config(self, icon, item):
        """打开配置"""
        webbrowser.open(f"{GALAXY_URL}/config")
    
    def _open_api_docs(self, icon, item):
        """打开 API 文档"""
        webbrowser.open(f"{GALAXY_URL}/docs")
    
    def _restart_service(self, icon, item):
        """重启服务"""
        try:
            # 停止
            subprocess.run(["taskkill", "/F", "/IM", "python.exe"], capture_output=True)
            time.sleep(2)
            # 启动
            subprocess.Popen(
                [sys.executable, str(PROJECT_ROOT / "run_galaxy.py"), "--mode", "daemon"],
                cwd=str(PROJECT_ROOT),
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception as e:
            print(f"重启失败: {e}")
    
    def _stop_service(self, icon, item):
        """停止服务"""
        try:
            subprocess.run(["taskkill", "/F", "/IM", "python.exe"], capture_output=True)
            self.monitor.status = "stopped"
        except Exception as e:
            print(f"停止失败: {e}")
    
    def _is_autostart(self):
        """检查是否开机自启"""
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_READ
            )
            winreg.QueryValueEx(key, "Galaxy")
            winreg.CloseKey(key)
            return True
        except:
            return False
    
    def _toggle_autostart(self, icon, item):
        """切换开机自启"""
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_WRITE
        )
        
        if self._is_autostart():
            # 禁用自启
            winreg.DeleteValue(key, "Galaxy")
        else:
            # 启用自启
            startup_script = str(PROJECT_ROOT / "windows" / "start_galaxy.bat")
            winreg.SetValueEx(key, "Galaxy", 0, winreg.REG_SZ, startup_script)
        
        winreg.CloseKey(key)
    
    def _quit(self, icon, item):
        """退出"""
        self.monitor.running = False
        icon.stop()
    
    def _update_icon(self):
        """更新图标"""
        while self.monitor.running:
            # 检查状态
            self.monitor.check_status()
            
            # 更新图标
            if self.icon:
                self.icon.icon = create_icon_image(self.monitor.status)
                self.icon.title = f"Galaxy - {self.monitor.get_status_text()}"
            
            # 等待
            time.sleep(CHECK_INTERVAL)
    
    def run(self):
        """运行托盘应用"""
        # 创建图标
        self.icon = pystray.Icon(
            "Galaxy",
            self.icon_image,
            "Galaxy - 检查中...",
            self.menu
        )
        
        # 启动状态检查线程
        update_thread = threading.Thread(target=self._update_icon, daemon=True)
        update_thread.start()
        
        # 运行托盘
        self.icon.run()

# ============================================================================
# 主函数
# ============================================================================

def main():
    """主函数"""
    print("Galaxy 托盘程序启动...")
    
    tray = GalaxyTray()
    tray.run()

if __name__ == "__main__":
    main()
