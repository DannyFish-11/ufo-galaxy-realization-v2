"""
UFO³ Galaxy - 书法卷轴式极客 UI
================================

设计理念：
- F12 硬件唤醒
- 从右侧像书法卷轴一样展开
- 极客风格：黑白渐变、几何线条、科技感字体
- 完整功能：对话、节点管理、设备控制、Agent 工厂

作者：UFO Galaxy Team
版本：v2.3.19
"""

import tkinter as tk
from tkinter import ttk, scrolledtext
import asyncio
import websockets
import json
import threading
from datetime import datetime
import keyboard
from typing import Optional, List, Dict
import math

class ScrollPaperGeekUI:
    """书法卷轴式极客 UI"""
    
    def __init__(self, server_url: str = "ws://localhost:8080/ws"):
        self.server_url = server_url
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.is_visible = False
        self.current_tab = "chat"
        
        # 节点和设备数据
        self.nodes: List[Dict] = []
        self.devices: List[Dict] = []
        self.agents: List[Dict] = []
        self.messages: List[Dict] = []
        
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
        
        # 卷轴展开宽度（用于动画）
        self.scroll_width = 0
        self.target_scroll_width = self.width
        
        # 初始隐藏
        self.root.geometry(f"1x{self.height}+{self.x_hidden}+0")
        
        # 创建 UI
        self._create_ui()
        
        # 注册 F12 键监听
        keyboard.on_press_key('f12', lambda _: self.toggle_panel())
        
        # 启动 WebSocket
        threading.Thread(target=self._run_websocket, daemon=True).start()
        
        # 启动状态更新
        self._update_status_loop()
    
    def _create_ui(self):
        """创建 UI"""
        # 主容器
        self.main_frame = tk.Frame(self.root, bg='#000000')
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建画布用于绘制背景
        self.canvas = tk.Canvas(self.main_frame, bg='#000000', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # 绘制背景
        self._draw_background()
        
        # 创建各个面板
        self._create_scroll_edge()  # 卷轴边缘
        self._create_header()       # 标题栏
        self._create_tabs()         # 标签页
        self._create_chat_panel()   # 对话面板
        self._create_nodes_panel()  # 节点面板
        self._create_devices_panel() # 设备面板
        self._create_agents_panel() # Agent 面板
        self._create_status_bar()   # 状态栏
        
        # 默认显示对话面板
        self._show_panel("chat")
    
    def _draw_background(self):
        """绘制极客风格背景"""
        # 黑白渐变
        for i in range(self.height):
            ratio = i / self.height
            gray = int(20 * ratio)
            color = f'#{gray:02x}{gray:02x}{gray:02x}'
            self.canvas.create_line(0, i, self.width, i, fill=color)
        
        # 几何装饰线条
        # 顶部横线
        self.canvas.create_line(30, 50, self.width-30, 50, fill='#ffffff', width=1)
        # 底部横线
        self.canvas.create_line(30, self.height-70, self.width-30, self.height-70, fill='#ffffff', width=1)
        
        # 斜线网格（极客风格）
        for i in range(-100, self.width + 100, 60):
            self.canvas.create_line(i, 0, i + 150, 150, fill='#1a1a1a', width=1)
            self.canvas.create_line(i, self.height, i + 150, self.height - 150, fill='#1a1a1a', width=1)
        
        # 角落装饰
        self.canvas.create_polygon(0, 0, 20, 0, 0, 20, fill='#ffffff', outline='')
        self.canvas.create_polygon(self.width, 0, self.width, 20, self.width-20, 0, fill='#ffffff', outline='')
    
    def _create_scroll_edge(self):
        """创建卷轴边缘效果"""
        # 左侧墨迹边缘
        self.scroll_edge = tk.Canvas(self.main_frame, width=15, bg='#000000', highlightthickness=0)
        self.scroll_edge.place(x=0, y=0, relheight=1)
        
        # 绘制墨迹效果
        for i in range(15):
            alpha = int(255 * (1 - i/15))
            color = f'#{alpha:02x}{alpha:02x}{alpha:02x}'
            self.scroll_edge.create_line(i, 0, i, self.height, fill=color)
    
    def _create_header(self):
        """创建标题栏"""
        # 标题
        self.canvas.create_text(
            self.width // 2, 25,
            text="UFO³ GALAXY",
            font=('Consolas', 20, 'bold'),
            fill='#ffffff'
        )
        
        # 副标题
        self.canvas.create_text(
            self.width // 2, 45,
            text="L4 AUTONOMOUS INTELLIGENCE SYSTEM",
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
            activeforeground='#ffffff',
            width=3
        )
        close_btn.place(x=self.width-35, y=5)
    
    def _create_tabs(self):
        """创建标签页"""
        self.tab_frame = tk.Frame(self.root, bg='#0a0a0a')
        self.tab_frame.place(x=20, y=60, width=self.width-40, height=35)
        
        tabs = [
            ("对话", "chat"),
            ("节点", "nodes"),
            ("设备", "devices"),
            ("Agent", "agents")
        ]
        
        self.tab_buttons = {}
        for i, (text, key) in enumerate(tabs):
            btn = tk.Button(
                self.tab_frame,
                text=text,
                font=('Consolas', 10),
                bg='#1a1a1a',
                fg='#888888',
                bd=0,
                width=10,
                command=lambda k=key: self._show_panel(k)
            )
            btn.place(x=i*110, y=5, width=100, height=25)
            self.tab_buttons[key] = btn
        
        # 默认选中对话
        self.tab_buttons["chat"].config(bg='#ffffff', fg='#000000')
    
    def _create_chat_panel(self):
        """创建对话面板"""
        self.chat_frame = tk.Frame(self.root, bg='#0a0a0a')
        self.chat_frame.place(x=20, y=100, width=self.width-40, height=self.height-200)
        
        # 消息历史
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
        self.chat_history.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # 配置标签样式
        self.chat_history.tag_config('user', foreground='#ffffff', font=('Consolas', 10, 'bold'))
        self.chat_history.tag_config('ai', foreground='#00aaff')
        self.chat_history.tag_config('system', foreground='#666666')
        self.chat_history.tag_config('success', foreground='#00ff00')
        self.chat_history.tag_config('error', foreground='#ff3333')
        
        # 输入区域
        input_frame = tk.Frame(self.chat_frame, bg='#0a0a0a')
        input_frame.pack(fill=tk.X)
        
        self.chat_input = tk.Entry(
            input_frame,
            font=('Consolas', 11),
            bg='#1a1a1a',
            fg='#ffffff',
            insertbackground='#ffffff',
            bd=0
        )
        self.chat_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.chat_input.bind('<Return>', lambda e: self._send_chat())
        
        send_btn = tk.Button(
            input_frame,
            text="发送",
            font=('Consolas', 10, 'bold'),
            bg='#ffffff',
            fg='#000000',
            bd=0,
            command=self._send_chat
        )
        send_btn.pack(side=tk.RIGHT)
        
        # 添加欢迎消息
        self._append_chat("[SYSTEM] UFO³ Galaxy 已启动", 'system')
        self._append_chat("[AI] 你好！我是 UFO Galaxy 智能体。", 'ai')
        self._append_chat("[AI] 我可以帮你控制设备、执行任务、回答问题。", 'ai')
    
    def _create_nodes_panel(self):
        """创建节点面板"""
        self.nodes_frame = tk.Frame(self.root, bg='#0a0a0a')
        self.nodes_frame.place(x=20, y=100, width=self.width-40, height=self.height-200)
        
        # 节点统计
        stats_frame = tk.Frame(self.nodes_frame, bg='#0f0f0f')
        stats_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.nodes_count_label = tk.Label(
            stats_frame,
            text="节点: 0",
            font=('Consolas', 12, 'bold'),
            bg='#0f0f0f',
            fg='#00aaff'
        )
        self.nodes_count_label.pack(side=tk.LEFT, padx=10)
        
        self.nodes_running_label = tk.Label(
            stats_frame,
            text="运行中: 0",
            font=('Consolas', 12),
            bg='#0f0f0f',
            fg='#00ff00'
        )
        self.nodes_running_label.pack(side=tk.LEFT, padx=10)
        
        # 节点列表
        self.nodes_list = scrolledtext.ScrolledText(
            self.nodes_frame,
            font=('Consolas', 9),
            bg='#0f0f0f',
            fg='#cccccc',
            bd=0,
            wrap=tk.WORD,
            state=tk.DISABLED
        )
        self.nodes_list.pack(fill=tk.BOTH, expand=True)
    
    def _create_devices_panel(self):
        """创建设备面板"""
        self.devices_frame = tk.Frame(self.root, bg='#0a0a0a')
        self.devices_frame.place(x=20, y=100, width=self.width-40, height=self.height-200)
        
        # 设备统计
        stats_frame = tk.Frame(self.devices_frame, bg='#0f0f0f')
        stats_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.devices_count_label = tk.Label(
            stats_frame,
            text="设备: 0",
            font=('Consolas', 12, 'bold'),
            bg='#0f0f0f',
            fg='#00aaff'
        )
        self.devices_count_label.pack(side=tk.LEFT, padx=10)
        
        # 设备列表
        self.devices_list = scrolledtext.ScrolledText(
            self.devices_frame,
            font=('Consolas', 9),
            bg='#0f0f0f',
            fg='#cccccc',
            bd=0,
            wrap=tk.WORD,
            state=tk.DISABLED
        )
        self.devices_list.pack(fill=tk.BOTH, expand=True)
    
    def _create_agents_panel(self):
        """创建 Agent 面板"""
        self.agents_frame = tk.Frame(self.root, bg='#0a0a0a')
        self.agents_frame.place(x=20, y=100, width=self.width-40, height=self.height-200)
        
        # Agent 统计
        stats_frame = tk.Frame(self.agents_frame, bg='#0f0f0f')
        stats_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.agents_count_label = tk.Label(
            stats_frame,
            text="Agent: 0",
            font=('Consolas', 12, 'bold'),
            bg='#0f0f0f',
            fg='#00aaff'
        )
        self.agents_count_label.pack(side=tk.LEFT, padx=10)
        
        # Agent 列表
        self.agents_list = scrolledtext.ScrolledText(
            self.agents_frame,
            font=('Consolas', 9),
            bg='#0f0f0f',
            fg='#cccccc',
            bd=0,
            wrap=tk.WORD,
            state=tk.DISABLED
        )
        self.agents_list.pack(fill=tk.BOTH, expand=True)
    
    def _create_status_bar(self):
        """创建状态栏"""
        self.status_frame = tk.Frame(self.root, bg='#000000')
        self.status_frame.place(x=0, y=self.height-50, width=self.width, height=50)
        
        # 连接状态
        self.status_canvas = tk.Canvas(self.status_frame, width=12, height=12, bg='#000000', highlightthickness=0)
        self.status_canvas.place(x=20, y=10)
        self.status_dot = self.status_canvas.create_oval(2, 2, 10, 10, fill='#ff3333', outline='')
        
        self.status_label = tk.Label(
            self.status_frame,
            text="DISCONNECTED",
            font=('Consolas', 9),
            bg='#000000',
            fg='#ff3333'
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
            text="Press F12 to toggle | ESC to hide",
            font=('Consolas', 8),
            bg='#000000',
            fg='#444444'
        )
        hint_label.place(x=20, y=28)
        
        # 绑定 ESC 键
        self.root.bind('<Escape>', lambda e: self.hide_panel())
        
        # 更新时间
        self._update_time()
    
    def _show_panel(self, panel_name: str):
        """显示指定面板"""
        self.current_tab = panel_name
        
        # 更新标签按钮样式
        for key, btn in self.tab_buttons.items():
            if key == panel_name:
                btn.config(bg='#ffffff', fg='#000000')
            else:
                btn.config(bg='#1a1a1a', fg='#888888')
        
        # 隐藏所有面板
        self.chat_frame.place_forget()
        self.nodes_frame.place_forget()
        self.devices_frame.place_forget()
        self.agents_frame.place_forget()
        
        # 显示指定面板
        if panel_name == "chat":
            self.chat_frame.place(x=20, y=100, width=self.width-40, height=self.height-200)
        elif panel_name == "nodes":
            self.nodes_frame.place(x=20, y=100, width=self.width-40, height=self.height-200)
        elif panel_name == "devices":
            self.devices_frame.place(x=20, y=100, width=self.width-40, height=self.height-200)
        elif panel_name == "agents":
            self.agents_frame.place(x=20, y=100, width=self.width-40, height=self.height-200)
    
    def _append_chat(self, message: str, tag: str = 'system'):
        """添加聊天消息"""
        self.chat_history.config(state=tk.NORMAL)
        self.chat_history.insert(tk.END, f"{message}\n", tag)
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
        if self.ws:
            asyncio.run_coroutine_threadsafe(
                self.ws.send(json.dumps({
                    "type": "chat",
                    "content": message,
                    "timestamp": datetime.now().isoformat()
                })),
                self.loop
            )
        else:
            # 模拟响应
            self._append_chat("[AI] 正在处理...", 'ai')
            self.root.after(500, lambda: self._append_chat("[AI] 请确保后端服务正在运行: python main.py", 'system'))
    
    def toggle_panel(self):
        """切换面板"""
        if self.is_visible:
            self.hide_panel()
        else:
            self.show_panel()
    
    def show_panel(self):
        """显示面板 - 书法卷轴展开动画"""
        if not self.is_visible:
            self.is_visible = True
            self._animate_scroll_open()
    
    def hide_panel(self):
        """隐藏面板 - 书法卷轴收起动画"""
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
                # 使用缓动函数实现卷轴效果
                progress = step / steps
                # 缓出效果
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
                # 使用缓动函数
                progress = step / steps
                # 缓入效果
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
    
    def _update_status_loop(self):
        """状态更新循环"""
        # 更新节点数量
        self.nodes_count_label.config(text=f"节点: {len(self.nodes)}")
        running = sum(1 for n in self.nodes if n.get('status') == 'running')
        self.nodes_running_label.config(text=f"运行中: {running}")
        
        # 更新设备数量
        self.devices_count_label.config(text=f"设备: {len(self.devices)}")
        
        # 更新 Agent 数量
        self.agents_count_label.config(text=f"Agent: {len(self.agents)}")
        
        self.root.after(5000, self._update_status_loop)
    
    def _run_websocket(self):
        """运行 WebSocket"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._websocket_handler())
    
    async def _websocket_handler(self):
        """WebSocket 处理"""
        while True:
            try:
                async with websockets.connect(self.server_url) as ws:
                    self.ws = ws
                    self._update_connection_status(True)
                    self._append_chat("[SYSTEM] 已连接到 Galaxy 服务", 'success')
                    
                    async for message in ws:
                        data = json.loads(message)
                        await self._handle_message(data)
            
            except Exception as e:
                self.ws = None
                self._update_connection_status(False)
                await asyncio.sleep(5)
    
    async def _handle_message(self, data: Dict):
        """处理消息"""
        msg_type = data.get("type", "")
        
        if msg_type == "chat_response":
            self._append_chat(f"[AI] {data.get('content', '')}", 'ai')
        elif msg_type == "node_status":
            self.nodes = data.get("nodes", [])
            self._update_nodes_list()
        elif msg_type == "device_status":
            self.devices = data.get("devices", [])
            self._update_devices_list()
        elif msg_type == "agent_status":
            self.agents = data.get("agents", [])
            self._update_agents_list()
    
    def _update_connection_status(self, connected: bool):
        """更新连接状态"""
        if connected:
            self.status_canvas.itemconfig(self.status_dot, fill='#00ff00')
            self.status_label.config(text="CONNECTED", fg='#00ff00')
        else:
            self.status_canvas.itemconfig(self.status_dot, fill='#ff3333')
            self.status_label.config(text="DISCONNECTED", fg='#ff3333')
    
    def _update_nodes_list(self):
        """更新节点列表"""
        self.nodes_list.config(state=tk.NORMAL)
        self.nodes_list.delete(1.0, tk.END)
        for node in self.nodes:
            status = "●" if node.get('status') == 'running' else "○"
            self.nodes_list.insert(tk.END, f"{status} {node.get('id', '')} - {node.get('name', '')}\n")
        self.nodes_list.config(state=tk.DISABLED)
    
    def _update_devices_list(self):
        """更新设备列表"""
        self.devices_list.config(state=tk.NORMAL)
        self.devices_list.delete(1.0, tk.END)
        for device in self.devices:
            self.devices_list.insert(tk.END, f"● {device.get('name', '')} ({device.get('type', '')})\n")
        self.devices_list.config(state=tk.DISABLED)
    
    def _update_agents_list(self):
        """更新 Agent 列表"""
        self.agents_list.config(state=tk.NORMAL)
        self.agents_list.delete(1.0, tk.END)
        for agent in self.agents:
            self.agents_list.insert(tk.END, f"● {agent.get('name', '')} - {agent.get('task', '')}\n")
        self.agents_list.config(state=tk.DISABLED)
    
    def run(self):
        """运行"""
        self.root.mainloop()


if __name__ == "__main__":
    app = ScrollPaperGeekUI()
    app.run()
