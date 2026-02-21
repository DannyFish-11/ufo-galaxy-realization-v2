"""
Galaxy - 星系风格极客 UI
=======================

Windows 客户端主 UI
F12 唤醒/隐藏

版本: v2.3.23
"""

import tkinter as tk
from tkinter import scrolledtext
import threading
from datetime import datetime
import keyboard
from typing import Optional
import httpx
import math
import random


class GalaxyGeekUI:
    """星系风格极客 UI"""
    
    def __init__(self, server_url: str = "http://localhost:8080"):
        self.server_url = server_url
        self.is_visible = False
        
        # 创建主窗口
        self.root = tk.Tk()
        self.root.title("Galaxy")
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', 0.97)
        
        # 窗口尺寸
        self.width = 500
        self.height = self.root.winfo_screenheight()
        screen_width = self.root.winfo_screenwidth()
        self.x_visible = screen_width - self.width - 20
        self.x_hidden = screen_width + 10
        
        # 初始隐藏
        self.root.geometry(f"1x{self.height}+{self.x_hidden}+0")
        
        # 颜色配置 - 星系风格
        self.colors = {
            'bg': '#000000',
            'panel': '#0a0a1a',
            'border': '#1a1a3a',
            'accent_cyan': '#00d4ff',
            'accent_purple': '#7b2fff',
            'accent_pink': '#ff006e',
            'text': '#ffffff',
            'text_dim': '#666666',
            'user_bg': '#0a1a2a',
            'ai_bg': '#1a0a2a',
        }
        
        # 创建 UI
        self._create_ui()
        
        # 注册 F12 键监听
        keyboard.on_press_key('f12', lambda _: self.toggle_panel())
        
        # 绑定 ESC 键
        self.root.bind('<Escape>', lambda e: self.hide_panel())
        
        # 启动动画
        self._start_animations()
        
        # 启动状态更新
        self._update_time()
    
    def _create_ui(self):
        """创建 UI"""
        # 主容器
        self.main_frame = tk.Frame(self.root, bg=self.colors['bg'])
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建画布 (用于绘制星系效果)
        self.canvas = tk.Canvas(
            self.main_frame, 
            bg=self.colors['bg'], 
            highlightthickness=0
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # 绘制星系背景
        self._draw_galaxy_background()
        
        # 创建标题栏
        self._create_header()
        
        # 创建对话区域
        self._create_chat_area()
        
        # 创建输入区域
        self._create_input_area()
        
        # 创建状态栏
        self._create_status_bar()
    
    def _draw_galaxy_background(self):
        """绘制星系背景"""
        width = self.width
        height = self.height
        
        # 绘制星星
        for _ in range(100):
            x = random.randint(0, width)
            y = random.randint(0, height)
            size = random.randint(1, 3)
            opacity = random.randint(100, 255)
            color = f'#{opacity:02x}{opacity:02x}{opacity:02x}'
            
            self.canvas.create_oval(
                x, y, x + size, y + size,
                fill=color, outline=''
            )
        
        # 绘制星云
        for _ in range(3):
            x = random.randint(0, width)
            y = random.randint(0, height)
            size = random.randint(50, 150)
            
            colors = [
                ('#00d4ff', 30),  # 青色
                ('#7b2fff', 25),  # 紫色
                ('#ff006e', 20),  # 粉色
            ]
            
            color, opacity = random.choice(colors)
            
            self.canvas.create_oval(
                x - size, y - size, x + size, y + size,
                fill='', outline=color, width=1
            )
    
    def _create_header(self):
        """创建标题栏"""
        header_frame = tk.Frame(self.canvas, bg=self.colors['panel'])
        
        # 使用 canvas 创建窗口
        self.canvas.create_window(
            0, 0, 
            window=header_frame, 
            anchor='nw', 
            width=self.width,
            height=60
        )
        
        # Logo 和标题
        title_frame = tk.Frame(header_frame, bg=self.colors['panel'])
        title_frame.pack(side=tk.LEFT, padx=15, pady=10)
        
        # Logo 圆形
        logo_canvas = tk.Canvas(
            title_frame, 
            width=40, 
            height=40, 
            bg=self.colors['panel'], 
            highlightthickness=0
        )
        logo_canvas.pack(side=tk.LEFT, padx=(0, 10))
        
        # 绘制渐变圆
        logo_canvas.create_oval(
            5, 5, 35, 35,
            fill=self.colors['accent_cyan'],
            outline=self.colors['accent_purple'],
            width=2
        )
        logo_canvas.create_text(
            20, 20,
            text="G",
            fill='white',
            font=('Orbitron', 14, 'bold')
        )
        
        # 标题
        title_label = tk.Label(
            title_frame,
            text="GALAXY",
            font=('Orbitron', 18, 'bold'),
            fg=self.colors['accent_cyan'],
            bg=self.colors['panel']
        )
        title_label.pack(side=tk.LEFT)
        
        # 版本
        version_label = tk.Label(
            title_frame,
            text="v2.3.23",
            font=('Consolas', 9),
            fg=self.colors['text_dim'],
            bg=self.colors['panel']
        )
        version_label.pack(side=tk.LEFT, padx=(10, 0))
        
        # 状态指示器
        status_frame = tk.Frame(header_frame, bg=self.colors['panel'])
        status_frame.pack(side=tk.RIGHT, padx=15, pady=10)
        
        self.status_label = tk.Label(
            status_frame,
            text="● 运行中",
            font=('Consolas', 10),
            fg='#00ff88',
            bg=self.colors['panel']
        )
        self.status_label.pack()
        
        self.time_label = tk.Label(
            status_frame,
            text="00:00:00",
            font=('Consolas', 9),
            fg=self.colors['text_dim'],
            bg=self.colors['panel']
        )
        self.time_label.pack()
    
    def _create_chat_area(self):
        """创建对话区域"""
        # 对话区域框架
        chat_frame = tk.Frame(self.canvas, bg=self.colors['bg'])
        
        self.canvas.create_window(
            0, 60,
            window=chat_frame,
            anchor='nw',
            width=self.width,
            height=self.height - 180
        )
        
        # 欢迎消息
        welcome_frame = tk.Frame(chat_frame, bg=self.colors['bg'])
        welcome_frame.pack(fill=tk.BOTH, expand=True, pady=50)
        
        welcome_label = tk.Label(
            welcome_frame,
            text="GALAXY",
            font=('Orbitron', 28, 'bold'),
            fg=self.colors['accent_cyan'],
            bg=self.colors['bg']
        )
        welcome_label.pack()
        
        subtitle_label = tk.Label(
            welcome_frame,
            text="L4 级自主性智能系统",
            font=('Microsoft YaHei', 12),
            fg=self.colors['text_dim'],
            bg=self.colors['bg']
        )
        subtitle_label.pack(pady=(5, 0))
        
        hint_label = tk.Label(
            welcome_frame,
            text="星系级智能体，随时为您服务",
            font=('Microsoft YaHei', 10),
            fg=self.colors['text_dim'],
            bg=self.colors['bg']
        )
        hint_label.pack(pady=(20, 0))
        
        # 消息显示区域
        self.messages_frame = tk.Frame(chat_frame, bg=self.colors['bg'])
        self.messages_frame.pack(fill=tk.BOTH, expand=True, padx=15)
        
        # 消息列表
        self.messages = []
    
    def _create_input_area(self):
        """创建输入区域"""
        input_frame = tk.Frame(self.canvas, bg=self.colors['panel'])
        
        self.canvas.create_window(
            0, self.height - 120,
            window=input_frame,
            anchor='nw',
            width=self.width,
            height=80
        )
        
        # 输入框
        self.input_entry = tk.Entry(
            input_frame,
            font=('Microsoft YaHei', 11),
            bg=self.colors['bg'],
            fg=self.colors['text'],
            insertbackground=self.colors['accent_cyan'],
            relief='flat',
            highlightthickness=1,
            highlightcolor=self.colors['accent_cyan'],
            highlightbackground=self.colors['border']
        )
        self.input_entry.pack(fill=tk.X, padx=15, pady=10, ipady=8)
        self.input_entry.bind('<Return>', lambda e: self.send_message())
        
        # 提示
        hint_frame = tk.Frame(input_frame, bg=self.colors['panel'])
        hint_frame.pack(fill=tk.X, padx=15)
        
        hint_label = tk.Label(
            hint_frame,
            text="💡 试试: \"打开微信\" / \"截图\" / \"控制手机\"",
            font=('Microsoft YaHei', 9),
            fg=self.colors['text_dim'],
            bg=self.colors['panel']
        )
        hint_label.pack(side=tk.LEFT)
    
    def _create_status_bar(self):
        """创建状态栏"""
        status_frame = tk.Frame(self.canvas, bg=self.colors['panel'])
        
        self.canvas.create_window(
            0, self.height - 40,
            window=status_frame,
            anchor='nw',
            width=self.width,
            height=40
        )
        
        # 节点状态
        nodes_label = tk.Label(
            status_frame,
            text="● 节点: 108",
            font=('Consolas', 9),
            fg=self.colors['accent_cyan'],
            bg=self.colors['panel']
        )
        nodes_label.pack(side=tk.LEFT, padx=15, pady=10)
        
        # 设备状态
        self.devices_label = tk.Label(
            status_frame,
            text="● 设备: 0",
            font=('Consolas', 9),
            fg=self.colors['accent_purple'],
            bg=self.colors['panel']
        )
        self.devices_label.pack(side=tk.LEFT, padx=10, pady=10)
        
        # Agent 状态
        self.agents_label = tk.Label(
            status_frame,
            text="● Agent: 0",
            font=('Consolas', 9),
            fg=self.colors['accent_pink'],
            bg=self.colors['panel']
        )
        self.agents_label.pack(side=tk.LEFT, padx=10, pady=10)
    
    def _start_animations(self):
        """启动动画"""
        pass
    
    def _update_time(self):
        """更新时间"""
        now = datetime.now()
        self.time_label.config(text=now.strftime('%H:%M:%S'))
        self.root.after(1000, self._update_time)
    
    def toggle_panel(self):
        """切换面板显示/隐藏"""
        if self.is_visible:
            self.hide_panel()
        else:
            self.show_panel()
    
    def show_panel(self):
        """显示面板"""
        self.is_visible = True
        
        # 动画展开
        for i in range(10):
            x = self.x_hidden - (self.x_hidden - self.x_visible) * (i + 1) / 10
            self.root.geometry(f"{self.width}x{self.height}+{int(x)}+0")
            self.root.update()
            self.root.after(10)
        
        self.root.geometry(f"{self.width}x{self.height}+{self.x_visible}+0")
        self.input_entry.focus()
    
    def hide_panel(self):
        """隐藏面板"""
        self.is_visible = False
        
        # 动画收起
        for i in range(10):
            x = self.x_visible + (self.x_hidden - self.x_visible) * (i + 1) / 10
            self.root.geometry(f"{self.width}x{self.height}+{int(x)}+0")
            self.root.update()
            self.root.after(10)
        
        self.root.geometry(f"1x{self.height}+{self.x_hidden}+0")
    
    def send_message(self):
        """发送消息"""
        message = self.input_entry.get().strip()
        if not message:
            return
        
        self.input_entry.delete(0, tk.END)
        
        # 添加用户消息
        self._add_message("user", message)
        
        # 发送到服务器
        threading.Thread(
            target=self._send_to_server,
            args=(message,),
            daemon=True
        ).start()
    
    def _send_to_server(self, message: str):
        """发送消息到服务器"""
        try:
            response = httpx.post(
                f"{self.server_url}/api/v1/chat",
                json={"message": message},
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                self._add_message("ai", data.get("response", "处理完成"))
            else:
                self._add_message("ai", f"❌ 错误: {response.status_code}")
        
        except Exception as e:
            self._add_message("ai", f"❌ 连接失败: {str(e)}")
    
    def _add_message(self, role: str, content: str):
        """添加消息"""
        def _add():
            # 创建消息框架
            msg_frame = tk.Frame(
                self.messages_frame,
                bg=self.colors['user_bg'] if role == 'user' else self.colors['ai_bg']
            )
            msg_frame.pack(fill=tk.X, pady=5)
            
            # 消息内容
            msg_label = tk.Label(
                msg_frame,
                text=content,
                font=('Microsoft YaHei', 10),
                fg=self.colors['text'],
                bg=self.colors['user_bg'] if role == 'user' else self.colors['ai_bg'],
                wraplength=self.width - 60,
                justify='left' if role == 'ai' else 'right'
            )
            msg_label.pack(padx=10, pady=8, anchor='e' if role == 'user' else 'w')
            
            # 滚动到底部
            self.messages_frame.update_idletasks()
        
        self.root.after(0, _add)
    
    def run(self):
        """运行"""
        print()
        print("  ═══════════════════════════════════════")
        print("  🌌 Galaxy Windows 客户端已启动")
        print("  ═══════════════════════════════════════")
        print()
        print("  按 F12 唤醒/隐藏面板")
        print("  按 ESC 隐藏面板")
        print()
        
        self.root.mainloop()


if __name__ == "__main__":
    app = GalaxyGeekUI()
    app.run()
