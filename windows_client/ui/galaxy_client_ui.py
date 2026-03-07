"""
Galaxy 客户端 - OPPO 光场设计风格
=======================================

混合模式：F12 唤出侧边栏，可展开为全功能窗口。
包含：对话、Agent 工厂、系统状态、设备控制四个 Tab。

设计灵感：OPPO ColorOS 光场美学
- 流光渐变背景 + 径向光晕
- 磨砂半透明面板
- 圆角 + 柔阴影
- 流体动画
"""

import sys
import json
import logging
import threading
from datetime import datetime
from typing import Optional, Callable, List, Dict

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QScrollArea,
    QStackedWidget, QFrame, QSizePolicy, QGraphicsDropShadowEffect
)
from PyQt5.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, pyqtSignal, QTimer,
    QRect, QSize, QPoint, QThread, pyqtSlot, QParallelAnimationGroup
)
from PyQt5.QtGui import (
    QFont, QPalette, QColor, QLinearGradient, QRadialGradient,
    QPainter, QBrush, QPen, QIcon, QFontDatabase, QPainterPath
)

logger = logging.getLogger(__name__)

# ── 光场色彩方案 ──
COLORS = {
    "bg_dark": "#0a0f1a",
    "bg_panel": "rgba(255, 255, 255, 0.04)",
    "bg_panel_hover": "rgba(255, 255, 255, 0.07)",
    "bg_input": "rgba(255, 255, 255, 0.06)",
    "border": "rgba(255, 255, 255, 0.08)",
    "border_focus": "rgba(124, 92, 252, 0.5)",
    "primary": "#7C5CFC",       # 紫
    "secondary": "#00D4AA",     # 青
    "accent": "#FF6B9D",        # 珊瑚
    "text": "#ffffff",
    "text_dim": "rgba(255, 255, 255, 0.45)",
    "text_muted": "rgba(255, 255, 255, 0.2)",
    "success": "#30d158",
    "error": "#ff453a",
    "warning": "#ffd60a",
}

SIDEBAR_WIDTH = 420
FULL_WIDTH = 940
FULL_HEIGHT = 720


class APIClient:
    """HTTP API 客户端"""

    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
        try:
            import httpx
            self._client = httpx.Client(timeout=15.0)
        except ImportError:
            self._client = None

    def post(self, path: str, data: dict) -> dict:
        if not self._client:
            return {"error": "httpx not installed"}
        try:
            r = self._client.post(f"{self.base_url}{path}", json=data)
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def get(self, path: str) -> dict:
        if not self._client:
            return {"error": "httpx not installed"}
        try:
            r = self._client.get(f"{self.base_url}{path}")
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def delete(self, path: str) -> dict:
        if not self._client:
            return {"error": "httpx not installed"}
        try:
            r = self._client.delete(f"{self.base_url}{path}")
            return r.json()
        except Exception as e:
            return {"error": str(e)}


class AsyncWorker(QThread):
    """后台线程执行 API 调用"""
    finished = pyqtSignal(dict)

    def __init__(self, func, *args):
        super().__init__()
        self._func = func
        self._args = args

    def run(self):
        try:
            result = self._func(*self._args)
            self.finished.emit(result)
        except Exception as e:
            self.finished.emit({"error": str(e)})


class GlassPanel(QFrame):
    """磨砂玻璃面板"""

    def __init__(self, parent=None, radius=16):
        super().__init__(parent)
        self._radius = radius
        self.setStyleSheet(f"""
            QFrame {{
                background: {COLORS['bg_panel']};
                border: 1px solid {COLORS['border']};
                border-radius: {radius}px;
            }}
        """)


class LightFieldBackground(QWidget):
    """光场背景渲染器"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(50)

    def _animate(self):
        self._phase += 0.02
        if self._phase > 6.28:
            self._phase = 0.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # 主背景渐变
        bg = QLinearGradient(0, 0, w, h)
        bg.setColorAt(0.0, QColor(26, 5, 51))     # 深紫
        bg.setColorAt(0.5, QColor(13, 33, 55))     # 深蓝
        bg.setColorAt(1.0, QColor(10, 22, 40))     # 深靛
        painter.fillRect(self.rect(), QBrush(bg))

        # 光晕 1 - 紫色 (缓慢移动)
        import math
        cx1 = w * 0.3 + math.sin(self._phase) * 40
        cy1 = h * 0.4 + math.cos(self._phase * 0.7) * 30
        g1 = QRadialGradient(cx1, cy1, w * 0.35)
        g1.setColorAt(0.0, QColor(124, 92, 252, 25))
        g1.setColorAt(1.0, QColor(124, 92, 252, 0))
        painter.fillRect(self.rect(), QBrush(g1))

        # 光晕 2 - 青色
        cx2 = w * 0.7 + math.cos(self._phase * 0.8) * 35
        cy2 = h * 0.6 + math.sin(self._phase * 0.6) * 25
        g2 = QRadialGradient(cx2, cy2, w * 0.3)
        g2.setColorAt(0.0, QColor(0, 212, 170, 18))
        g2.setColorAt(1.0, QColor(0, 212, 170, 0))
        painter.fillRect(self.rect(), QBrush(g2))

        # 光晕 3 - 珊瑚 (微弱)
        cx3 = w * 0.5 + math.sin(self._phase * 1.2) * 30
        cy3 = h * 0.2 + math.cos(self._phase * 0.9) * 20
        g3 = QRadialGradient(cx3, cy3, w * 0.25)
        g3.setColorAt(0.0, QColor(255, 107, 157, 12))
        g3.setColorAt(1.0, QColor(255, 107, 157, 0))
        painter.fillRect(self.rect(), QBrush(g3))

        painter.end()


class ChatPanel(QWidget):
    """对话面板"""

    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        self._workers = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)

        # 消息区域
        self.messages_area = QTextEdit()
        self.messages_area.setReadOnly(True)
        self.messages_area.setStyleSheet(f"""
            QTextEdit {{
                background: transparent;
                border: none;
                color: {COLORS['text']};
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
                padding: 8px;
            }}
        """)
        self.messages_area.setPlaceholderText("开始对话...")
        layout.addWidget(self.messages_area, 1)

        # 输入区
        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入消息... (Enter 发送)")
        self.input_field.setStyleSheet(f"""
            QLineEdit {{
                background: {COLORS['bg_input']};
                border: 1px solid {COLORS['border']};
                border-radius: 20px;
                padding: 10px 18px;
                color: {COLORS['text']};
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {COLORS['border_focus']};
            }}
        """)
        self.input_field.returnPressed.connect(self._send)
        input_layout.addWidget(self.input_field)

        send_btn = QPushButton("发送")
        send_btn.setFixedSize(64, 40)
        send_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0a84ff, stop:1 {COLORS['primary']});
                border: none;
                border-radius: 20px;
                color: white;
                font-weight: 600;
                font-size: 13px;
            }}
            QPushButton:hover {{ opacity: 0.9; }}
            QPushButton:pressed {{ background: {COLORS['primary']}; }}
        """)
        send_btn.clicked.connect(self._send)
        input_layout.addWidget(send_btn)

        layout.addLayout(input_layout)

    def _send(self):
        text = self.input_field.text().strip()
        if not text:
            return
        self.input_field.clear()
        self._add_message("你", text, COLORS['primary'])

        worker = AsyncWorker(self.api.post, "/api/v1/chat", {"message": text})
        worker.finished.connect(self._on_response)
        self._workers.append(worker)
        worker.start()

    @pyqtSlot(dict)
    def _on_response(self, data):
        response = data.get("response", data.get("error", "无响应"))
        self._add_message("Galaxy", response, COLORS['secondary'])

    def _add_message(self, sender: str, text: str, color: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.messages_area.append(
            f'<div style="margin-bottom: 8px;">'
            f'<span style="color: {color}; font-weight: 600; font-size: 12px;">{sender}</span> '
            f'<span style="color: rgba(255,255,255,0.2); font-size: 10px;">{timestamp}</span>'
            f'<br/>'
            f'<span style="color: rgba(255,255,255,0.85); font-size: 13px;">{text}</span>'
            f'</div>'
        )
        scrollbar = self.messages_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


class AgentFactoryPanel(QWidget):
    """Agent 工厂面板"""

    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        self._workers = []
        self._init_ui()
        QTimer.singleShot(500, self._refresh)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)

        # 统计栏
        stats_frame = QFrame()
        stats_frame.setStyleSheet(f"""
            QFrame {{
                background: {COLORS['bg_panel']};
                border: 1px solid {COLORS['border']};
                border-radius: 14px;
                padding: 12px;
            }}
        """)
        stats_layout = QHBoxLayout(stats_frame)
        self.stat_active = QLabel("0")
        self.stat_total = QLabel("0")
        self.stat_templates = QLabel("6")
        for label, title in [(self.stat_active, "活跃"), (self.stat_total, "总计"), (self.stat_templates, "模板")]:
            col = QVBoxLayout()
            label.setStyleSheet(f"color: {COLORS['primary']}; font-size: 20px; font-weight: 700;")
            label.setAlignment(Qt.AlignCenter)
            col.addWidget(label)
            sub = QLabel(title)
            sub.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
            sub.setAlignment(Qt.AlignCenter)
            col.addWidget(sub)
            stats_layout.addLayout(col)
        layout.addWidget(stats_frame)

        # Agent 列表
        self.agent_list = QTextEdit()
        self.agent_list.setReadOnly(True)
        self.agent_list.setStyleSheet(f"""
            QTextEdit {{
                background: transparent;
                border: none;
                color: {COLORS['text']};
                font-size: 12px;
            }}
        """)
        self.agent_list.setPlaceholderText("暂无 Agent...")
        layout.addWidget(self.agent_list, 1)

        # 操作按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        btn_template = QPushButton("📋 从模板创建")
        btn_template.setStyleSheet(self._btn_style(COLORS['primary']))
        btn_template.clicked.connect(self._create_from_template)
        btn_layout.addWidget(btn_template)

        btn_dynamic = QPushButton("✨ 智能创建")
        btn_dynamic.setStyleSheet(self._btn_style(COLORS['secondary']))
        btn_dynamic.clicked.connect(self._create_dynamic)
        btn_layout.addWidget(btn_dynamic)

        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.setStyleSheet(self._btn_style("#555"))
        btn_refresh.clicked.connect(self._refresh)
        btn_layout.addWidget(btn_refresh)

        layout.addLayout(btn_layout)

    def _btn_style(self, color):
        return f"""
            QPushButton {{
                background: {color};
                border: none;
                border-radius: 12px;
                padding: 10px 16px;
                color: white;
                font-weight: 600;
                font-size: 12px;
            }}
            QPushButton:hover {{ opacity: 0.85; }}
        """

    def _refresh(self):
        worker = AsyncWorker(self.api.get, "/api/v1/agents")
        worker.finished.connect(self._on_agents_loaded)
        self._workers.append(worker)
        worker.start()

    @pyqtSlot(dict)
    def _on_agents_loaded(self, data):
        agents = data.get("agents", [])
        self.stat_total.setText(str(len(agents)))
        active = sum(1 for a in agents if a.get("state") in ("idle", "working", "waiting"))
        self.stat_active.setText(str(active))

        self.agent_list.clear()
        if not agents:
            self.agent_list.setPlaceholderText("暂无 Agent... 点击下方按钮创建")
            return
        for a in agents:
            state_color = COLORS['success'] if a.get('state') == 'working' else COLORS['text_dim']
            self.agent_list.append(
                f'<div style="background: rgba(255,255,255,0.03); border-radius: 10px; padding: 8px; margin-bottom: 6px;">'
                f'<span style="font-weight: 600; color: {COLORS["text"]};">{a.get("name", a.get("id", "?"))}</span> '
                f'<span style="color: {COLORS["text_muted"]}; font-size: 10px;">({a.get("role", "?")})</span><br/>'
                f'<span style="color: {state_color}; font-size: 11px;">● {a.get("state", "?")}</span> '
                f'<span style="color: {COLORS["text_dim"]}; font-size: 10px;">队列: {a.get("queue_length", 0)} | 完成: {a.get("completed", 0)}</span>'
                f'</div>'
            )

    def _create_from_template(self):
        # 默认创建 coordinator
        templates = ["coordinator", "data_analyst", "code_executor", "research", "device_controller", "planner"]
        # 轮换创建不同类型
        import random
        template = random.choice(templates)
        worker = AsyncWorker(self.api.post, "/api/v1/agents/create", {"template": template})
        worker.finished.connect(lambda d: self._on_created(d, template))
        self._workers.append(worker)
        worker.start()

    def _create_dynamic(self):
        worker = AsyncWorker(self.api.post, "/api/v1/agents/create/dynamic", {
            "task_description": "帮我分析当前系统状态并提供优化建议"
        })
        worker.finished.connect(lambda d: self._on_created(d, "dynamic"))
        self._workers.append(worker)
        worker.start()

    @pyqtSlot(dict)
    def _on_created(self, data, source):
        if data.get("success"):
            self._refresh()
        else:
            self.agent_list.append(
                f'<div style="color: {COLORS["error"]}; font-size: 11px;">创建失败: {data.get("error", "未知错误")}</div>'
            )


class StatusPanel(QWidget):
    """系统状态面板"""

    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        self._workers = []
        self._init_ui()
        QTimer.singleShot(500, self._refresh)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)

        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setStyleSheet(f"""
            QTextEdit {{
                background: transparent;
                border: none;
                color: {COLORS['text']};
                font-size: 12px;
            }}
        """)
        layout.addWidget(self.status_text, 1)

        btn_refresh = QPushButton("🔄 刷新状态")
        btn_refresh.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['bg_input']};
                border: 1px solid {COLORS['border']};
                border-radius: 12px;
                padding: 10px;
                color: {COLORS['text']};
                font-size: 12px;
            }}
            QPushButton:hover {{ background: {COLORS['bg_panel_hover']}; }}
        """)
        btn_refresh.clicked.connect(self._refresh)
        layout.addWidget(btn_refresh)

    def _refresh(self):
        w1 = AsyncWorker(self.api.get, "/api/v1/config/status")
        w1.finished.connect(self._on_config)
        self._workers.append(w1)
        w1.start()

        w2 = AsyncWorker(self.api.get, "/api/v1/llm/providers")
        w2.finished.connect(self._on_providers)
        self._workers.append(w2)
        w2.start()

    @pyqtSlot(dict)
    def _on_config(self, data):
        self.status_text.clear()
        self.status_text.append(
            f'<div style="font-size: 14px; font-weight: 600; margin-bottom: 8px; color: {COLORS["primary"]};">📊 系统配置状态</div>'
        )
        for key, val in data.items():
            color = COLORS['success'] if val is True else (COLORS['error'] if val is False else COLORS['text_dim'])
            self.status_text.append(
                f'<div style="padding: 4px 0; font-size: 12px;">'
                f'<span style="color: {COLORS["text_dim"]};">{key}:</span> '
                f'<span style="color: {color};">{val}</span></div>'
            )

    @pyqtSlot(dict)
    def _on_providers(self, data):
        providers = data.get("providers", [])
        if not providers:
            return
        self.status_text.append(
            f'<div style="font-size: 14px; font-weight: 600; margin: 12px 0 8px; color: {COLORS["secondary"]};">🤖 LLM 提供商</div>'
        )
        for p in providers:
            available = p.get("available", False)
            dot_color = COLORS['success'] if available else COLORS['text_muted']
            self.status_text.append(
                f'<div style="padding: 3px 0; font-size: 12px;">'
                f'<span style="color: {dot_color};">●</span> '
                f'<span style="color: {COLORS["text"]};">{p.get("provider", "?")}</span> '
                f'<span style="color: {COLORS["text_dim"]};">({p.get("model", "?")})</span></div>'
            )


class DevicePanel(QWidget):
    """设备控制面板"""

    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        self._workers = []
        self._init_ui()
        QTimer.singleShot(500, self._refresh)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)

        self.device_text = QTextEdit()
        self.device_text.setReadOnly(True)
        self.device_text.setStyleSheet(f"""
            QTextEdit {{
                background: transparent;
                border: none;
                color: {COLORS['text']};
                font-size: 12px;
            }}
        """)
        self.device_text.setPlaceholderText("设备列表将显示在这里...")
        layout.addWidget(self.device_text, 1)

        # 快捷操作
        shortcuts_layout = QHBoxLayout()
        shortcuts_layout.setSpacing(6)
        actions = [("📸 截图", "screenshot"), ("📋 剪贴板", "clipboard"), ("📝 任务列表", "tasks")]
        for label, action in actions:
            btn = QPushButton(label)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {COLORS['bg_input']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 10px;
                    padding: 8px;
                    color: {COLORS['text']};
                    font-size: 11px;
                }}
                QPushButton:hover {{ background: {COLORS['bg_panel_hover']}; }}
            """)
            btn.clicked.connect(lambda checked, a=action: self._quick_action(a))
            shortcuts_layout.addWidget(btn)
        layout.addLayout(shortcuts_layout)

    def _refresh(self):
        worker = AsyncWorker(self.api.get, "/api/v1/devices")
        worker.finished.connect(self._on_devices)
        self._workers.append(worker)
        worker.start()

    @pyqtSlot(dict)
    def _on_devices(self, data):
        devices = data.get("devices", [])
        self.device_text.clear()
        if not devices:
            self.device_text.setPlaceholderText("暂无已注册设备")
            return
        for d in devices:
            online = d.get("online", False)
            dot = COLORS['success'] if online else COLORS['text_muted']
            self.device_text.append(
                f'<div style="background: rgba(255,255,255,0.03); border-radius: 10px; padding: 8px; margin-bottom: 6px;">'
                f'<span style="color: {dot};">●</span> '
                f'<span style="font-weight: 600;">{d.get("device_id", "?")}</span> '
                f'<span style="color: {COLORS["text_dim"]};">({d.get("type", "?")})</span>'
                f'</div>'
            )

    def _quick_action(self, action: str):
        self.device_text.append(
            f'<div style="color: {COLORS["text_dim"]}; font-size: 11px;">执行: {action}...</div>'
        )


class GalaxyClientUI(QWidget):
    """混合模式主窗口 - OPPO 光场设计"""

    command_submitted = pyqtSignal(str)

    def __init__(self, api_base: str = "http://localhost:8080", on_command: Optional[Callable] = None):
        super().__init__()
        self.api = APIClient(api_base)
        self.on_command = on_command
        self.is_sidebar_mode = True
        self.is_visible = False

        if on_command:
            self.command_submitted.connect(on_command)

        self._init_window()
        self._create_ui()
        self._setup_animations()

        logger.info("GalaxyClientUI 初始化完成 (OPPO 光场设计)")

    def _init_window(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        screen = QApplication.primaryScreen().geometry()
        self.screen_width = screen.width()
        self.screen_height = screen.height()

        # 初始位置：屏幕右侧外
        self.setGeometry(
            self.screen_width, 0,
            SIDEBAR_WIDTH, self.screen_height
        )

    def _create_ui(self):
        # 根布局
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        # 光场背景
        self.bg = LightFieldBackground(self)

        # 主容器 (覆盖在背景上)
        self.container = QWidget(self)
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # 标题栏
        self.title_bar = self._create_title_bar()
        container_layout.addWidget(self.title_bar)

        # Tab 栏 (全窗口模式才显示)
        self.tab_bar = self._create_tab_bar()
        self.tab_bar.setVisible(False)
        container_layout.addWidget(self.tab_bar)

        # 内容堆栈
        self.stack = QStackedWidget()
        self.chat_panel = ChatPanel(self.api)
        self.agent_panel = AgentFactoryPanel(self.api)
        self.status_panel = StatusPanel(self.api)
        self.device_panel = DevicePanel(self.api)

        self.stack.addWidget(self.chat_panel)      # index 0
        self.stack.addWidget(self.agent_panel)      # index 1
        self.stack.addWidget(self.status_panel)     # index 2
        self.stack.addWidget(self.device_panel)     # index 3
        container_layout.addWidget(self.stack, 1)

    def _create_title_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(48)
        bar.setStyleSheet(f"""
            QWidget {{
                background: rgba(0, 0, 0, 0.3);
                border-bottom: 1px solid {COLORS['border']};
            }}
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 12, 0)

        # 状态灯
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(f"color: {COLORS['success']}; font-size: 10px;")
        layout.addWidget(self.status_dot)

        # 标题
        title = QLabel("Galaxy")
        title.setStyleSheet(f"""
            color: {COLORS['text']};
            font-size: 14px;
            font-weight: 700;
            font-family: 'Segoe UI', sans-serif;
        """)
        layout.addWidget(title)
        layout.addStretch()

        # 展开/收缩按钮
        self.toggle_btn = QPushButton("⬜")
        self.toggle_btn.setFixedSize(32, 32)
        self.toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {COLORS['text_dim']};
                font-size: 14px;
            }}
            QPushButton:hover {{ color: {COLORS['text']}; }}
        """)
        self.toggle_btn.clicked.connect(self.toggle_mode)
        layout.addWidget(self.toggle_btn)

        # 关闭按钮
        close_btn = QPushButton("×")
        close_btn.setFixedSize(32, 32)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {COLORS['text_dim']};
                font-size: 18px;
            }}
            QPushButton:hover {{ color: {COLORS['error']}; }}
        """)
        close_btn.clicked.connect(self.hide_sidebar)
        layout.addWidget(close_btn)

        return bar

    def _create_tab_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(44)
        bar.setStyleSheet(f"background: rgba(0, 0, 0, 0.15); border-bottom: 1px solid {COLORS['border']};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(4)

        tabs = [("💬 对话", 0), ("🤖 Agent", 1), ("📊 状态", 2), ("🎮 设备", 3)]
        self._tab_buttons = []
        for label, idx in tabs:
            btn = QPushButton(label)
            btn.setStyleSheet(self._tab_style(False))
            btn.clicked.connect(lambda checked, i=idx: self._switch_tab(i))
            layout.addWidget(btn)
            self._tab_buttons.append(btn)

        self._switch_tab(0)
        return bar

    def _tab_style(self, active: bool) -> str:
        if active:
            return f"""
                QPushButton {{
                    background: rgba(255, 255, 255, 0.1);
                    border: none;
                    border-radius: 10px;
                    padding: 6px 14px;
                    color: {COLORS['text']};
                    font-size: 12px;
                    font-weight: 600;
                }}
            """
        return f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 10px;
                padding: 6px 14px;
                color: {COLORS['text_dim']};
                font-size: 12px;
            }}
            QPushButton:hover {{ color: {COLORS['text']}; }}
        """

    def _switch_tab(self, idx):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._tab_buttons):
            btn.setStyleSheet(self._tab_style(i == idx))

    def _setup_animations(self):
        self.slide_anim = QPropertyAnimation(self, b"geometry")
        self.slide_anim.setDuration(350)
        self.slide_anim.setEasingCurve(QEasingCurve.OutQuart)

    def toggle_mode(self):
        """侧边栏 ↔ 全功能窗口"""
        if self.is_sidebar_mode:
            # 展开为全窗口
            self.is_sidebar_mode = False
            self.tab_bar.setVisible(True)
            self.toggle_btn.setText("▬")

            cx = (self.screen_width - FULL_WIDTH) // 2
            cy = (self.screen_height - FULL_HEIGHT) // 2
            self.slide_anim.setStartValue(self.geometry())
            self.slide_anim.setEndValue(QRect(cx, cy, FULL_WIDTH, FULL_HEIGHT))
            self.slide_anim.start()
        else:
            # 收缩为侧边栏
            self.is_sidebar_mode = True
            self.tab_bar.setVisible(False)
            self.toggle_btn.setText("⬜")
            self._switch_tab(0)

            target_x = self.screen_width - SIDEBAR_WIDTH
            self.slide_anim.setStartValue(self.geometry())
            self.slide_anim.setEndValue(QRect(target_x, 0, SIDEBAR_WIDTH, self.screen_height))
            self.slide_anim.start()

    def toggle_visibility(self):
        if self.is_visible:
            self.hide_sidebar()
        else:
            self.show_sidebar()

    def show_sidebar(self):
        if self.is_visible:
            return
        self.show()
        self.is_visible = True

        if self.is_sidebar_mode:
            target_x = self.screen_width - SIDEBAR_WIDTH
            self.slide_anim.setStartValue(QRect(self.screen_width, 0, SIDEBAR_WIDTH, self.screen_height))
            self.slide_anim.setEndValue(QRect(target_x, 0, SIDEBAR_WIDTH, self.screen_height))
        else:
            cx = (self.screen_width - FULL_WIDTH) // 2
            cy = (self.screen_height - FULL_HEIGHT) // 2
            self.slide_anim.setStartValue(QRect(self.screen_width, cy, FULL_WIDTH, FULL_HEIGHT))
            self.slide_anim.setEndValue(QRect(cx, cy, FULL_WIDTH, FULL_HEIGHT))

        self.slide_anim.start()
        self.chat_panel.input_field.setFocus()
        logger.info("Galaxy 客户端显示")

    def hide_sidebar(self):
        if not self.is_visible:
            return
        self.is_visible = False

        target_x = self.screen_width
        self.slide_anim.setStartValue(self.geometry())
        if self.is_sidebar_mode:
            self.slide_anim.setEndValue(QRect(target_x, 0, SIDEBAR_WIDTH, self.screen_height))
        else:
            cy = (self.screen_height - FULL_HEIGHT) // 2
            self.slide_anim.setEndValue(QRect(target_x, cy, FULL_WIDTH, FULL_HEIGHT))
        self.slide_anim.start()

        QTimer.singleShot(400, self.hide)
        logger.info("Galaxy 客户端隐藏")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.bg.setGeometry(0, 0, self.width(), self.height())
        self.container.setGeometry(0, 0, self.width(), self.height())

    def update_status(self, status: str, color: str = None):
        color = color or COLORS['success']
        self.status_dot.setStyleSheet(f"color: {color}; font-size: 10px;")


def main():
    """独立运行测试"""
    logging.basicConfig(level=logging.INFO)
    app = QApplication(sys.argv)

    client = GalaxyClientUI()
    client.show_sidebar()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
