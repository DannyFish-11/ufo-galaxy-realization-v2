"""
UFO³ Galaxy Windows 客户端 - 黑白渐变极简极客风格 UI

设计理念：
- 黑白渐变背景
- 极简线条和几何图形
- 科技感的字体和动画
- Fn 键唤起/隐藏

作者：Manus AI
日期：2025-01-20
"""

import tkinter as tk
from tkinter import ttk, scrolledtext
import asyncio
import websockets
import json
import threading
from datetime import datetime
import keyboard
from typing import Optional

class MinimalistSidePanel:
    """黑白渐变极简侧边栏"""
    
    def __init__(self, server_url: str = "ws://localhost:8080"):
        self.server_url = server_url
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.is_visible = False
        
        # 创建主窗口
        self.root = tk.Tk()
        self.root.title("UFO³ Galaxy")
        self.root.overrideredirect(True)  # 无边框
        self.root.attributes('-topmost', True)  # 置顶
        self.root.attributes('-alpha', 0.95)  # 半透明
        
        # 窗口尺寸和位置
        self.width = 400
        self.height = self.root.winfo_screenheight()
        screen_width = self.root.winfo_screenwidth()
        self.x_visible = screen_width - self.width
        self.x_hidden = screen_width
        
        # 初始隐藏
        self.root.geometry(f"{self.width}x{self.height}+{self.x_hidden}+0")
        
        # 创建 UI
        self._create_ui()
        
        # 注册 Fn 键监听
        keyboard.on_press_key('f12', lambda _: self.toggle_panel())  # 使用 F12 代替 Fn
        
        # 启动 WebSocket 连接
        threading.Thread(target=self._run_websocket, daemon=True).start()
    
    def _create_ui(self):
        """创建 UI 组件"""
        # 主容器
        main_frame = tk.Frame(self.root, bg='#000000')
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建渐变背景（使用 Canvas）
        self.canvas = tk.Canvas(main_frame, bg='#000000', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # 绘制黑白渐变背景
        self._draw_gradient_background()
        
        # 顶部：标题栏
        self._create_header()
        
        # 中部：输入区域
        self._create_input_area()
        
        # 底部：消息历史
        self._create_message_area()
        
        # 状态栏
        self._create_status_bar()
    
    def _draw_gradient_background(self):
        """绘制黑白渐变背景"""
        # 从黑色 (#000000) 渐变到深灰 (#1a1a1a)
        for i in range(self.height):
            ratio = i / self.height
            # 计算颜色值
            gray_value = int(26 * ratio)  # 从 0 到 26
            color = f'#{gray_value:02x}{gray_value:02x}{gray_value:02x}'
            self.canvas.create_line(0, i, self.width, i, fill=color)
        
        # 添加几何装饰线条（极客风格）
        # 顶部横线
        self.canvas.create_line(20, 60, self.width-20, 60, fill='#ffffff', width=1)
        # 底部横线
        self.canvas.create_line(20, self.height-80, self.width-20, self.height-80, fill='#ffffff', width=1)
        
        # 添加装饰性的斜线网格
        for i in range(0, self.width, 50):
            self.canvas.create_line(i, 0, i+100, 100, fill='#333333', width=1, dash=(2, 4))
    
    def _create_header(self):
        """创建标题栏"""
        # 标题文字
        header_text = self.canvas.create_text(
            self.width // 2, 30,
            text="UFO³ GALAXY",
            font=('Consolas', 18, 'bold'),
            fill='#ffffff'
        )
        
        # 副标题
        subtitle_text = self.canvas.create_text(
            self.width // 2, 50,
            text="SUPER ENHANCER",
            font=('Consolas', 8),
            fill='#888888'
        )
        
        # 关闭按钮（右上角）
        close_btn = tk.Button(
            self.root,
            text="×",
            font=('Arial', 16),
            bg='#000000',
            fg='#ffffff',
            bd=0,
            command=self.hide_panel,
            activebackground='#ff0000',
            activeforeground='#ffffff'
        )
        close_btn.place(x=self.width-30, y=5, width=25, height=25)
    
    def _create_input_area(self):
        """创建输入区域"""
        # 输入框容器
        input_frame = tk.Frame(self.root, bg='#0a0a0a', bd=0)
        input_frame.place(x=20, y=80, width=self.width-40, height=120)
        
        # 输入提示
        prompt_label = tk.Label(
            input_frame,
            text="> INPUT COMMAND",
            font=('Consolas', 9),
            bg='#0a0a0a',
            fg='#888888',
            anchor='w'
        )
        prompt_label.pack(fill=tk.X, padx=5, pady=(5, 0))
        
        # 输入框
        self.input_text = scrolledtext.ScrolledText(
            input_frame,
            font=('Consolas', 11),
            bg='#1a1a1a',
            fg='#ffffff',
            insertbackground='#ffffff',
            bd=0,
            wrap=tk.WORD,
            height=3
        )
        self.input_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 发送按钮
        send_btn = tk.Button(
            input_frame,
            text="EXECUTE [ENTER]",
            font=('Consolas', 9, 'bold'),
            bg='#ffffff',
            fg='#000000',
            bd=0,
            command=self.send_message,
            activebackground='#cccccc'
        )
        send_btn.pack(fill=tk.X, padx=5, pady=(0, 5))
        
        # 绑定回车键
        self.input_text.bind('<Return>', lambda e: self.send_message() or "break")
    
    def _create_message_area(self):
        """创建消息历史区域"""
        # 消息区域容器
        message_frame = tk.Frame(self.root, bg='#0a0a0a', bd=0)
        message_frame.place(x=20, y=220, width=self.width-40, height=self.height-320)
        
        # 消息历史标签
        history_label = tk.Label(
            message_frame,
            text="> MESSAGE HISTORY",
            font=('Consolas', 9),
            bg='#0a0a0a',
            fg='#888888',
            anchor='w'
        )
        history_label.pack(fill=tk.X, padx=5, pady=(5, 0))
        
        # 消息历史文本框
        self.message_text = scrolledtext.ScrolledText(
            message_frame,
            font=('Consolas', 10),
            bg='#1a1a1a',
            fg='#cccccc',
            bd=0,
            wrap=tk.WORD,
            state=tk.DISABLED
        )
        self.message_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 配置标签样式
        self.message_text.tag_config('user', foreground='#ffffff', font=('Consolas', 10, 'bold'))
        self.message_text.tag_config('system', foreground='#888888', font=('Consolas', 9))
        self.message_text.tag_config('success', foreground='#00ff00')
        self.message_text.tag_config('error', foreground='#ff0000')
    
    def _create_status_bar(self):
        """创建状态栏"""
        # 状态栏容器
        status_frame = tk.Frame(self.root, bg='#000000', bd=0)
        status_frame.place(x=0, y=self.height-60, width=self.width, height=60)
        
        # 连接状态指示器
        self.status_indicator = tk.Canvas(status_frame, width=10, height=10, bg='#000000', highlightthickness=0)
        self.status_indicator.place(x=20, y=15)
        self.status_circle = self.status_indicator.create_oval(2, 2, 8, 8, fill='#ff0000', outline='')
        
        # 状态文字
        self.status_label = tk.Label(
            status_frame,
            text="DISCONNECTED",
            font=('Consolas', 9),
            bg='#000000',
            fg='#888888',
            anchor='w'
        )
        self.status_label.place(x=35, y=12)
        
        # 时间显示
        self.time_label = tk.Label(
            status_frame,
            text="",
            font=('Consolas', 9),
            bg='#000000',
            fg='#888888',
            anchor='e'
        )
        self.time_label.place(x=self.width-120, y=12, width=100)
        
        # 更新时间
        self._update_time()
        
        # 提示文字
        hint_label = tk.Label(
            status_frame,
            text="Press F12 to toggle panel",
            font=('Consolas', 8),
            bg='#000000',
            fg='#555555'
        )
        hint_label.place(x=20, y=35)
    
    def _update_time(self):
        """更新时间显示"""
        current_time = datetime.now().strftime("%H:%M:%S")
        self.time_label.config(text=current_time)
        self.root.after(1000, self._update_time)
    
    def toggle_panel(self):
        """切换面板显示/隐藏"""
        if self.is_visible:
            self.hide_panel()
        else:
            self.show_panel()
    
    def show_panel(self):
        """显示面板"""
        if not self.is_visible:
            self.is_visible = True
            self._animate_slide(self.x_hidden, self.x_visible)
    
    def hide_panel(self):
        """隐藏面板"""
        if self.is_visible:
            self.is_visible = False
            self._animate_slide(self.x_visible, self.x_hidden)
    
    def _animate_slide(self, start_x: int, end_x: int):
        """滑动动画"""
        steps = 20
        delta = (end_x - start_x) / steps
        
        def animate(step=0):
            if step < steps:
                current_x = int(start_x + delta * step)
                self.root.geometry(f"{self.width}x{self.height}+{current_x}+0")
                self.root.after(10, lambda: animate(step + 1))
        
        animate()
    
    def send_message(self):
        """发送消息"""
        message = self.input_text.get("1.0", tk.END).strip()
        if not message:
            return
        
        # 清空输入框
        self.input_text.delete("1.0", tk.END)
        
        # 显示用户消息
        self._append_message(f"[USER] {message}", 'user')
        
        # 发送到服务器
        if self.ws:
            asyncio.run_coroutine_threadsafe(
                self.ws.send(json.dumps({
                    "type": "command",
                    "content": message,
                    "timestamp": datetime.now().isoformat()
                })),
                self.loop
            )
        else:
            self._append_message("[ERROR] Not connected to server", 'error')
    
    def _append_message(self, message: str, tag: str = 'system'):
        """添加消息到历史"""
        self.message_text.config(state=tk.NORMAL)
        self.message_text.insert(tk.END, f"{message}\n", tag)
        self.message_text.see(tk.END)
        self.message_text.config(state=tk.DISABLED)
    
    def _run_websocket(self):
        """运行 WebSocket 连接"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._websocket_handler())
    
    async def _websocket_handler(self):
        """WebSocket 处理器"""
        while True:
            try:
                async with websockets.connect(self.server_url) as ws:
                    self.ws = ws
                    self._update_status(True)
                    self._append_message("[SYSTEM] Connected to Galaxy", 'success')
                    
                    async for message in ws:
                        data = json.loads(message)
                        self._append_message(f"[GALAXY] {data.get('content', '')}", 'system')
            
            except Exception as e:
                self.ws = None
                self._update_status(False)
                self._append_message(f"[ERROR] Connection failed: {e}", 'error')
                await asyncio.sleep(5)
    
    def _update_status(self, connected: bool):
        """更新连接状态"""
        if connected:
            self.status_indicator.itemconfig(self.status_circle, fill='#00ff00')
            self.status_label.config(text="CONNECTED", fg='#00ff00')
        else:
            self.status_indicator.itemconfig(self.status_circle, fill='#ff0000')
            self.status_label.config(text="DISCONNECTED", fg='#ff0000')
    
    def run(self):
        """运行应用"""
        self.root.mainloop()

if __name__ == "__main__":
    app = MinimalistSidePanel()
    app.run()
