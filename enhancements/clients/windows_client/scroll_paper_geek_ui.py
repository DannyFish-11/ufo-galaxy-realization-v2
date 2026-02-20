"""
UFO³ Galaxy - 书法卷轴式极客 UI (简化版)
========================================

所有能力都集成到智能体对话中：
- 用户只需要对话
- 智能体自动调用相应能力
- 不需要切换面板

版本: v2.3.20
"""

import tkinter as tk
from tkinter import scrolledtext
import asyncio
import websockets
import json
import threading
from datetime import datetime
import keyboard
from typing import Optional, List, Dict
import httpx

class ScrollPaperGeekUI:
    """书法卷轴式极客 UI - 简化版"""
    
    def __init__(self, server_url: str = "http://localhost:8080"):
        self.server_url = server_url
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.is_visible = False
        
        # 创建主窗口
        self.root = tk.Tk()
        self.root.title("UFO³ Galaxy")
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', 0.97)
        
        # 窗口尺寸
        self.width = 500
        self.height = self.root.winfo_screenheight()
        screen_width = self.root.winfo_screenwidth()
        self.x_visible = screen_width - self.width
        self.x_hidden = screen_width + 10
        
        # 初始隐藏
        self.root.geometry(f"1x{self.height}+{self.x_hidden}+0")
        
        # 创建 UI
        self._create_ui()
        
        # 注册 F12 键监听
        keyboard.on_press_key('f12', lambda _: self.toggle_panel())
        
        # 绑定 ESC 键
        self.root.bind('<Escape>', lambda e: self.hide_panel())
        
        # 启动状态更新
        self._update_time()
    
    def _create_ui(self):
        """创建 UI - 简化为纯对话界面"""
        # 主容器
        self.main_frame = tk.Frame(self.root, bg='#000000')
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建画布用于绘制背景
        self.canvas = tk.Canvas(self.main_frame, bg='#000000', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # 绘制背景
        self._draw_background()
        
        # 创建卷轴边缘
        self._create_scroll_edge()
        
        # 创建标题栏
        self._create_header()
        
        # 创建对话区域
        self._create_chat_area()
        
        # 创建输入区域
        self._create_input_area()
        
        # 创建状态栏
        self._create_status_bar()
    
    def _draw_background(self):
        """绘制极客风格背景"""
        # 黑白渐变
        for i in range(self.height):
            ratio = i / self.height
            gray = int(20 * ratio)
            color = f'#{gray:02x}{gray:02x}{gray:02x}'
            self.canvas.create_line(0, i, self.width, i, fill=color)
        
        # 几何装饰线条
        self.canvas.create_line(30, 50, self.width-30, 50, fill='#ffffff', width=1)
        self.canvas.create_line(30, self.height-100, self.width-30, self.height-100, fill='#ffffff', width=1)
        
        # 斜线网格
        for i in range(-100, self.width + 100, 60):
            self.canvas.create_line(i, 0, i + 150, 150, fill='#1a1a1a', width=1)
    
    def _create_scroll_edge(self):
        """创建卷轴边缘"""
        self.scroll_edge = tk.Canvas(self.main_frame, width=15, bg='#000000', highlightthickness=0)
        self.scroll_edge.place(x=0, y=0, relheight=1)
        
        for i in range(15):
            alpha = int(255 * (1 - i/15))
            color = f'#{alpha:02x}{alpha:02x}{alpha:02x}'
            self.scroll_edge.create_line(i, 0, i, self.height, fill=color)
    
    def _create_header(self):
        """创建标题栏"""
        self.canvas.create_text(
            self.width // 2, 25,
            text="UFO³ GALAXY",
            font=('Consolas', 18, 'bold'),
            fill='#ffffff'
        )
        
        self.canvas.create_text(
            self.width // 2, 45,
            text="L4 AUTONOMOUS INTELLIGENCE - v2.3.20",
            font=('Consolas', 8),
            fill='#666666'
        )
        
        # 关闭按钮
        close_btn = tk.Button(
            self.root,
            text="×",
            font=('Consolas', 14),
            bg='#000000',
            fg='#ffffff',
            bd=0,
            command=self.hide_panel,
            activebackground='#ff3333',
            width=3
        )
        close_btn.place(x=self.width-35, y=5)
    
    def _create_chat_area(self):
        """创建对话区域"""
        self.chat_frame = tk.Frame(self.root, bg='#0a0a0a')
        self.chat_frame.place(x=20, y=60, width=self.width-40, height=self.height-180)
        
        # 对话历史
        self.chat_history = scrolledtext.ScrolledText(
            self.chat_frame,
            font=('Consolas', 10),
            bg='#0f0f0f',
            fg='#cccccc',
            insertbackground='#ffffff',
            bd=0,
            wrap=tk.WORD,
            state=tk.DISABLED
        )
        self.chat_history.pack(fill=tk.BOTH, expand=True)
        
        # 配置标签样式
        self.chat_history.tag_config('user', foreground='#ffffff', font=('Consolas', 10, 'bold'))
        self.chat_history.tag_config('ai', foreground='#00aaff')
        self.chat_history.tag_config('system', foreground='#666666')
        
        # 添加欢迎消息
        self._append_chat("[AI] 你好！我是 UFO Galaxy 智能体。", 'ai')
        self._append_chat("[AI] 我是 L4 级自主性智能系统。", 'ai')
        self._append_chat("[AI] 你只需要用自然语言与我对话，我会自动理解并执行。", 'ai')
        self._append_chat("[AI] 说 '帮助' 查看可用命令。", 'ai')
    
    def _create_input_area(self):
        """创建输入区域"""
        self.input_frame = tk.Frame(self.root, bg='#0a0a0a')
        self.input_frame.place(x=20, y=self.height-110, width=self.width-40, height=50)
        
        self.chat_input = tk.Entry(
            self.input_frame,
            font=('Consolas', 11),
            bg='#1a1a1a',
            fg='#ffffff',
            insertbackground='#ffffff',
            bd=0
        )
        self.chat_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.chat_input.bind('<Return>', lambda e: self._send_chat())
        
        send_btn = tk.Button(
            self.input_frame,
            text="发送",
            font=('Consolas', 10, 'bold'),
            bg='#ffffff',
            fg='#000000',
            bd=0,
            command=self._send_chat
        )
        send_btn.pack(side=tk.RIGHT)
    
    def _create_status_bar(self):
        """创建状态栏"""
        self.status_frame = tk.Frame(self.root, bg='#000000')
        self.status_frame.place(x=0, y=self.height-50, width=self.width, height=50)
        
        # 状态指示器
        self.status_canvas = tk.Canvas(self.status_frame, width=12, height=12, bg='#000000', highlightthickness=0)
        self.status_canvas.place(x=20, y=10)
        self.status_dot = self.status_canvas.create_oval(2, 2, 10, 10, fill='#00ff00', outline='')
        
        self.status_label = tk.Label(
            self.status_frame,
            text="CONNECTED",
            font=('Consolas', 9),
            bg='#000000',
            fg='#00ff00'
        )
        self.status_label.place(x=38, y=8)
        
        # 时间
        self.time_label = tk.Label(
            self.status_frame,
            text="",
            font=('Consolas', 9),
            bg='#000000',
            fg='#666666'
        )
        self.time_label.place(x=self.width-100, y=8)
        
        # 提示
        hint_label = tk.Label(
            self.status_frame,
            text="F12 唤醒/隐藏 | ESC 隐藏 | 所有能力集成在对话中",
            font=('Consolas', 8),
            bg='#000000',
            fg='#444444'
        )
        hint_label.place(x=20, y=28)
    
    def _append_chat(self, message: str, tag: str = 'system'):
        """添加聊天消息"""
        self.chat_history.config(state=tk.NORMAL)
        self.chat_history.insert(tk.END, f"{message}\n\n", tag)
        self.chat_history.see(tk.END)
        self.chat_history.config(state=tk.DISABLED)
    
    def _send_chat(self):
        """发送聊天消息"""
        message = self.chat_input.get().strip()
        if not message:
            return
        
        self.chat_input.delete(0, tk.END)
        self._append_chat(f"[USER] {message}", 'user')
        
        # 发送到服务器
        threading.Thread(target=self._send_to_server, args=(message,), daemon=True).start()
    
    def _send_to_server(self, message: str):
        """发送消息到服务器"""
        try:
            import httpx
            response = httpx.post(
                f"{self.server_url}/api/v1/chat",
                json={"message": message, "device_id": "windows_client"},
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                ai_response = data.get("response", "已收到指令")
                self.root.after(0, lambda: self._append_chat(f"[AI] {ai_response}", 'ai'))
            else:
                self.root.after(0, lambda: self._append_chat(f"[ERROR] HTTP {response.status_code}", 'system'))
        except Exception as e:
            self.root.after(0, lambda: self._append_chat(f"[ERROR] {str(e)}", 'system'))
    
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
            self._animate_scroll_open()
    
    def hide_panel(self):
        """隐藏面板"""
        if self.is_visible:
            self.is_visible = False
            self._animate_scroll_close()
    
    def _animate_scroll_open(self):
        """卷轴展开动画"""
        steps = 30
        start_width = 1
        end_width = self.width
        start_x = self.x_hidden
        end_x = self.x_visible
        
        def animate(step=0):
            if step < steps:
                progress = step / steps
                eased = 1 - (1 - progress) ** 3
                
                current_width = int(start_width + (end_width - start_width) * eased)
                current_x = int(start_x + (end_x - start_x) * eased)
                
                self.root.geometry(f"{current_width}x{self.height}+{current_x}+0")
                self.root.after(15, lambda: animate(step + 1))
            else:
                self.root.geometry(f"{self.width}x{self.height}+{self.x_visible}+0")
        
        animate()
    
    def _animate_scroll_close(self):
        """卷轴收起动画"""
        steps = 20
        start_width = self.width
        end_width = 1
        start_x = self.x_visible
        end_x = self.x_hidden
        
        def animate(step=0):
            if step < steps:
                progress = step / steps
                eased = progress ** 2
                
                current_width = int(start_width + (end_width - start_width) * eased)
                current_x = int(start_x + (end_x - start_x) * eased)
                
                self.root.geometry(f"{current_width}x{self.height}+{current_x}+0")
                self.root.after(10, lambda: animate(step + 1))
            else:
                self.root.geometry(f"1x{self.height}+{self.x_hidden}+0")
        
        animate()
    
    def _update_time(self):
        """更新时间"""
        self.time_label.config(text=datetime.now().strftime("%H:%M:%S"))
        self.root.after(1000, self._update_time)
    
    def run(self):
        """运行"""
        self.root.mainloop()


if __name__ == "__main__":
    app = ScrollPaperGeekUI()
    app.run()
