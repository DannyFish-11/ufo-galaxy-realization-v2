"""
Galaxy 主 UI - F12 唤醒的对话界面
==================================

功能:
- F12 唤醒/隐藏
- 与 AI 智能体对话
- 简洁的聊天界面

版本: v2.3.27
"""

import tkinter as tk
from tkinter import scrolledtext
import threading
import os
import sys
from datetime import datetime
from typing import Optional
import httpx

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, PROJECT_ROOT)

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False
    print("警告: keyboard 模块未安装，F12 热键不可用")
    print("安装: pip install keyboard")


class GalaxyChatUI:
    """Galaxy 主 UI - 对话界面"""
    
    def __init__(self, server_url: str = "http://localhost:8080"):
        self.server_url = server_url
        self.is_visible = False
        
        # 创建主窗口
        self.root = tk.Tk()
        self.root.title("Galaxy")
        self.root.overrideredirect(True)  # 无边框
        self.root.attributes('-topmost', True)  # 置顶
        self.root.attributes('-alpha', 0.97)  # 透明度
        
        # 窗口尺寸 - 右侧侧边栏
        self.width = 420
        self.height = min(800, self.root.winfo_screenheight() - 100)
        screen_width = self.root.winfo_screenwidth()
        self.x_visible = screen_width - self.width - 20
        self.x_hidden = screen_width + 10
        
        # 初始隐藏
        self.root.geometry(f"1x{self.height}+{self.x_hidden}+50")
        
        # 创建 UI
        self._create_ui()
        
        # 注册 F12 热键
        if KEYBOARD_AVAILABLE:
            keyboard.on_press_key('f12', lambda _: self.toggle_panel())
        
        # 绑定 ESC 键隐藏
        self.root.bind('<Escape>', lambda e: self.hide_panel())
        
        # 启动时间更新
        self._update_time()
        
        # 连接服务器
        self._check_connection()
    
    def _create_ui(self):
        """创建简洁的对话 UI"""
        # 主容器 - 黑色背景
        self.main_frame = tk.Frame(self.root, bg='#0a0a0a')
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # === 顶部标题栏 ===
        header = tk.Frame(self.main_frame, bg='#0a0a0a', height=50)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        
        # 标题
        title = tk.Label(
            header,
            text="🌌 Galaxy",
            font=('Arial', 16, 'bold'),
            bg='#0a0a0a',
            fg='#00d4ff'
        )
        title.pack(side=tk.LEFT, padx=15, pady=10)
        
        # 时间
        self.time_label = tk.Label(
            header,
            text="00:00:00",
            font=('Consolas', 10),
            bg='#0a0a0a',
            fg='#666666'
        )
        self.time_label.pack(side=tk.RIGHT, padx=15, pady=10)
        
        # 关闭按钮
        close_btn = tk.Button(
            header,
            text="×",
            font=('Arial', 14),
            bg='#0a0a0a',
            fg='#666666',
            bd=0,
            command=self.hide_panel,
            activebackground='#ff4444',
            activeforeground='#ffffff'
        )
        close_btn.pack(side=tk.RIGHT, padx=5, pady=10)
        
        # 分隔线
        sep1 = tk.Frame(self.main_frame, bg='#00d4ff', height=1)
        sep1.pack(fill=tk.X)
        
        # === 对话区域 ===
        chat_frame = tk.Frame(self.main_frame, bg='#0a0a0a')
        chat_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 对话显示
        self.chat_display = scrolledtext.ScrolledText(
            chat_frame,
            bg='#0a0a0a',
            fg='#ffffff',
            font=('Consolas', 11),
            bd=0,
            wrap=tk.WORD,
            state=tk.DISABLED,
            cursor='arrow'
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True)
        
        # 配置标签颜色
        self.chat_display.tag_config('user', foreground='#00d4ff')
        self.chat_display.tag_config('ai', foreground='#a855f7')
        self.chat_display.tag_config('system', foreground='#666666')
        self.chat_display.tag_config('error', foreground='#ff4444')
        
        # === 输入区域 ===
        input_frame = tk.Frame(self.main_frame, bg='#1a1a1a')
        input_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.input_entry = tk.Entry(
            input_frame,
            bg='#1a1a1a',
            fg='#ffffff',
            font=('Consolas', 11),
            bd=0,
            insertbackground='#00d4ff',
            highlightthickness=0
        )
        self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10, pady=10)
        self.input_entry.bind('<Return>', self._send_message)
        
        send_btn = tk.Button(
            input_frame,
            text="发送",
            font=('Arial', 10),
            bg='#00d4ff',
            fg='#000000',
            bd=0,
            padx=15,
            command=self._send_message
        )
        send_btn.pack(side=tk.RIGHT, padx=10, pady=10)
        
        # === 状态栏 ===
        status_frame = tk.Frame(self.main_frame, bg='#0a0a0a', height=30)
        status_frame.pack(fill=tk.X)
        
        self.status_label = tk.Label(
            status_frame,
            text="● 未连接",
            font=('Consolas', 9),
            bg='#0a0a0a',
            fg='#ff4444'
        )
        self.status_label.pack(side=tk.LEFT, padx=15, pady=5)
    
    def _check_connection(self):
        """检查服务器连接"""
        threading.Thread(target=self._ping_server, daemon=True).start()
    
    def _ping_server(self):
        """Ping 服务器"""
        try:
            response = httpx.get(f"{self.server_url}/api/v1/config/status", timeout=3.0)
            if response.status_code == 200:
                self.root.after(0, lambda: self.status_label.config(text="● 已连接", fg='#00ff88'))
                self.root.after(0, lambda: self._append_chat(
                    "已连接到 Galaxy。开始对话吧！", 'system'
                ))
            else:
                self.root.after(0, lambda: self.status_label.config(text=f"● 错误 {response.status_code}", fg='#ff4444'))
        except Exception as e:
            self.root.after(0, lambda: self.status_label.config(text="● 连接失败", fg='#ff4444'))
            self.root.after(0, lambda: self._append_chat(
                f"无法连接服务器。请先启动:\n  python main.py", 'error'
            ))
    
    def _append_chat(self, message: str, tag: str = 'system'):
        """添加消息到对话区"""
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, f"{message}\n\n", tag)
        self.chat_display.see(tk.END)
        self.chat_display.config(state=tk.DISABLED)
    
    def _send_message(self, event=None):
        """发送消息"""
        message = self.input_entry.get().strip()
        if not message:
            return
        
        self.input_entry.delete(0, tk.END)
        self._append_chat(f"👤 {message}", 'user')
        
        threading.Thread(target=self._call_api, args=(message,), daemon=True).start()
    
    def _call_api(self, message: str):
        """调用 API"""
        try:
            response = httpx.post(
                f"{self.server_url}/api/v1/chat",
                json={"message": message},
                timeout=60.0
            )
            
            if response.status_code == 200:
                data = response.json()
                ai_response = data.get("response", "...")
                self.root.after(0, lambda: self._append_chat(f"🤖 {ai_response}", 'ai'))
            else:
                self.root.after(0, lambda: self._append_chat(f"❌ 错误: HTTP {response.status_code}", 'error'))
        except Exception as e:
            self.root.after(0, lambda: self._append_chat(f"❌ 错误: {str(e)}", 'error'))
    
    def toggle_panel(self):
        """切换面板"""
        if self.is_visible:
            self.hide_panel()
        else:
            self.show_panel()
    
    def show_panel(self):
        """显示面板"""
        if not self.is_visible:
            self.is_visible = True
            self._animate_open()
    
    def hide_panel(self):
        """隐藏面板"""
        if self.is_visible:
            self.is_visible = False
            self._animate_close()
    
    def _animate_open(self):
        """展开动画"""
        steps = 20
        start_x = self.x_hidden
        end_x = self.x_visible
        
        def animate(step=0):
            if step < steps:
                progress = step / steps
                eased = 1 - (1 - progress) ** 3
                current_x = int(start_x + (end_x - start_x) * eased)
                self.root.geometry(f"{self.width}x{self.height}+{current_x}+50")
                self.root.after(10, lambda: animate(step + 1))
            else:
                self.root.geometry(f"{self.width}x{self.height}+{self.x_visible}+50")
        
        animate()
    
    def _animate_close(self):
        """收起动画"""
        steps = 15
        start_x = self.x_visible
        end_x = self.x_hidden
        
        def animate(step=0):
            if step < steps:
                progress = step / steps
                current_x = int(start_x + (end_x - start_x) * progress)
                self.root.geometry(f"{self.width}x{self.height}+{current_x}+50")
                self.root.after(8, lambda: animate(step + 1))
            else:
                self.root.geometry(f"1x{self.height}+{self.x_hidden}+50")
        
        animate()
    
    def _update_time(self):
        """更新时间"""
        self.time_label.config(text=datetime.now().strftime("%H:%M:%S"))
        self.root.after(1000, self._update_time)
    
    def run(self):
        """运行"""
        self.root.mainloop()


def main():
    """主函数"""
    print("=" * 50)
    print("Galaxy 主 UI - F12 唤醒")
    print("=" * 50)
    print()
    print("F12 - 唤醒/隐藏")
    print("ESC - 隐藏")
    print()
    print("=" * 50)
    
    server_url = os.environ.get('GALAXY_SERVER', 'http://localhost:8080')
    
    app = GalaxyChatUI(server_url=server_url)
    app.run()


if __name__ == "__main__":
    main()
