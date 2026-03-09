"""
Windows 主 UI — OPPO 光场 + 极客极简 + 书法卷轴式侧边栏

设计语言:
  - OPPO Light Field: 边缘柔和光晕、呼吸微光、展开时白色光线扫过
  - 极客极简: 黑/白/灰三色渐变、等宽字体、极简留白
  - 书法卷轴交互: 从右侧展开如卷轴滚出、收回如卷轴合拢
    宽度 0→420 + 高度中心→全屏 + 透明度 0→1 并行动画

功能模式:
  对话 | Agent | 孪生 | 设备 | MCP/Skill
"""

import sys
import json
import logging
from typing import Callable, Optional

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QScrollArea,
    QStackedWidget, QFrame, QSizePolicy, QGraphicsOpacityEffect
)
from PyQt5.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, pyqtSignal, pyqtProperty,
    QTimer, QRect, QParallelAnimationGroup, QSequentialAnimationGroup,
    QSize, QPoint
)
from PyQt5.QtGui import (
    QFont, QPalette, QColor, QLinearGradient, QPainter,
    QKeySequence, QBrush, QPen, QRadialGradient
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════
#  色彩常量 — 黑/白/灰三色体系
# ═══════════════════════════════════════════════
class C:
    BG_DEEP   = "#000000"
    BG_MID    = "#0d0d0d"
    BG_CARD   = "#111111"
    BORDER    = "#1e1e1e"
    BORDER_HI = "#333333"
    TEXT      = "#ffffff"
    TEXT_SEC  = "#888888"
    TEXT_DIM  = "#444444"
    ACCENT    = "#ffffff"   # 高亮用纯白
    GLOW      = "rgba(255,255,255,0.06)"


# ═══════════════════════════════════════════════
#  光场绘制组件 — OPPO Light Field
# ═══════════════════════════════════════════════
class LightFieldWidget(QWidget):
    """
    OPPO 光场背景层:
    - 左侧边缘柔和白色光晕
    - 可驱动的扫光动画 (light_pos 0.0→1.0)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._light_pos = 0.0   # 光线扫描位置 0~1
        self._glow_opacity = 0.04  # 左侧光晕强度
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def get_light_pos(self):
        return self._light_pos

    def set_light_pos(self, val):
        self._light_pos = val
        self.update()

    light_pos = pyqtProperty(float, get_light_pos, set_light_pos)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # 左侧边缘光晕
        glow = QRadialGradient(0, h * 0.5, w * 0.4)
        glow.setColorAt(0, QColor(255, 255, 255, int(255 * self._glow_opacity)))
        glow.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(0, 0, w, h, QBrush(glow))

        # 扫光线 — 展开时从左到右扫过一道白色光线
        if 0.01 < self._light_pos < 0.99:
            lx = int(self._light_pos * w)
            grad = QLinearGradient(lx - 30, 0, lx + 30, 0)
            grad.setColorAt(0, QColor(255, 255, 255, 0))
            grad.setColorAt(0.5, QColor(255, 255, 255, 22))
            grad.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillRect(lx - 30, 0, 60, h, QBrush(grad))

        p.end()


# ═══════════════════════════════════════════════
#  模式面板基类
# ═══════════════════════════════════════════════
class ModePanel(QFrame):
    """模式面板基类 — 统一样式"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{ background: transparent; }}
            QLabel {{ color: {C.TEXT}; background: transparent; }}
            QTextEdit {{
                background: {C.BG_CARD}; border: 1px solid {C.BORDER};
                border-radius: 8px; padding: 8px;
                color: {C.TEXT}; selection-background-color: {C.ACCENT}; selection-color: {C.BG_DEEP};
                font-family: 'Consolas', 'JetBrains Mono', monospace; font-size: 12px;
            }}
            QTextEdit:focus {{ border-color: {C.BORDER_HI}; }}
        """)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 8, 12, 8)
        self._layout.setSpacing(8)

        # 标题
        lbl = QLabel(title)
        lbl.setFont(QFont("Consolas", 11, QFont.Bold))
        lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        self._layout.addWidget(lbl)


# ── 对话模式 ──
class ChatPanel(ModePanel):
    command_submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__("对话", parent)

        self.history = QTextEdit()
        self.history.setReadOnly(True)
        self.history.setPlaceholderText("与 Galaxy 智能体对话...")
        self._layout.addWidget(self.history, 1)

        # 输入行
        row = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入命令或问题...")
        self.input_field.setStyleSheet(f"""
            QLineEdit {{
                background: {C.BG_CARD}; border: 1px solid {C.BORDER};
                border-radius: 8px; padding: 8px 12px;
                color: {C.TEXT}; font-family: 'Consolas', monospace; font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {C.ACCENT}; }}
        """)
        self.input_field.returnPressed.connect(self._submit)
        row.addWidget(self.input_field, 1)

        btn = self._make_btn("发送")
        btn.clicked.connect(self._submit)
        row.addWidget(btn)

        self._layout.addLayout(row)

    def _submit(self):
        text = self.input_field.text().strip()
        if not text:
            return
        self.add_message("你", text)
        self.input_field.clear()
        self.command_submitted.emit(text)

    def add_message(self, sender: str, msg: str):
        self.history.append(f"<span style='color:{C.TEXT_SEC};'>[{sender}]</span> {msg}")
        sb = self.history.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _make_btn(self, text):
        btn = QPushButton(text)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.BG_CARD}; border: 1px solid {C.BORDER};
                border-radius: 8px; padding: 8px 16px;
                color: {C.TEXT}; font-family: 'Consolas', monospace; font-size: 12px;
            }}
            QPushButton:hover {{ border-color: {C.ACCENT}; background: {C.BORDER}; }}
            QPushButton:pressed {{ background: {C.ACCENT}; color: {C.BG_DEEP}; }}
        """)
        return btn


# ── Agent 模式 ──
class AgentPanel(ModePanel):
    def __init__(self, parent=None):
        super().__init__("Agent 工厂", parent)
        self.info = QTextEdit()
        self.info.setReadOnly(True)
        self.info.setPlaceholderText("Agent 状态加载中...")
        self._layout.addWidget(self.info, 1)

        row = QHBoxLayout()
        self.refresh_btn = self._make_btn("刷新")
        self.refresh_btn.clicked.connect(lambda: self.load_status())
        row.addWidget(self.refresh_btn)
        row.addStretch()
        self._layout.addLayout(row)

    def load_status(self, data=None):
        if data is None:
            self.info.setPlainText("请连接后端后刷新...")
            return
        lines = [
            f"活跃 Agent: {data.get('total_agents', 0)}",
            f"状态类型:   {len(data.get('by_state', {}))}",
            f"创建模式:   {len(data.get('by_creation_mode', {}))}",
            "",
            "── 模板 ──",
        ]
        for tpl in data.get('templates', []):
            lines.append(f"  {tpl.get('name', '?')}  [{tpl.get('role', '')}]  {tpl.get('description', '')}")
        self.info.setPlainText("\n".join(lines))

    def _make_btn(self, text):
        btn = QPushButton(text)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.BG_CARD}; border: 1px solid {C.BORDER};
                border-radius: 8px; padding: 6px 14px;
                color: {C.TEXT}; font-family: 'Consolas', monospace; font-size: 11px;
            }}
            QPushButton:hover {{ border-color: {C.ACCENT}; }}
            QPushButton:pressed {{ background: {C.ACCENT}; color: {C.BG_DEEP}; }}
        """)
        return btn


# ── 孪生模式 ──
class TwinPanel(ModePanel):
    def __init__(self, parent=None):
        super().__init__("孪生指挥", parent)
        self.info = QTextEdit()
        self.info.setReadOnly(True)
        self.info.setPlaceholderText("数字孪生状态...")
        self._layout.addWidget(self.info, 1)

    def load_status(self, data=None):
        if data is None:
            self.info.setPlainText("暂无孪生体数据")
            return
        lines = [
            f"孪生体: {data.get('total_twins', 0)}",
            "",
        ]
        for tid, twin in data.get('twins', {}).items():
            lines.append(f"  {tid}  [{twin.get('status', '?')}]  设备:{twin.get('device_id', '—')}  耦合:{twin.get('coupling_mode', '—')}")
        self.info.setPlainText("\n".join(lines))


# ── 设备模式 ──
class DevicePanel(ModePanel):
    def __init__(self, parent=None):
        super().__init__("设备联控", parent)
        self.info = QTextEdit()
        self.info.setReadOnly(True)
        self.info.setPlaceholderText("设备列表...")
        self._layout.addWidget(self.info, 1)

    def load_status(self, devices=None):
        if not devices:
            self.info.setPlainText("暂无已注册设备")
            return
        lines = []
        for d in devices:
            name = d.get('name') or d.get('device_name') or d.get('device_id', '?')
            status = d.get('status', 'offline')
            dtype = d.get('device_type') or d.get('type', '—')
            lines.append(f"  {name}  [{status}]  {dtype}")
        self.info.setPlainText("\n".join(lines))


# ── MCP/Skill 模式 ──
class McpSkillPanel(ModePanel):
    def __init__(self, parent=None):
        super().__init__("MCP / Skill", parent)
        self.info = QTextEdit()
        self.info.setReadOnly(True)
        self.info.setPlaceholderText("MCP 服务 & Skill 协议...\n加载中...")
        self._layout.addWidget(self.info, 1)

        # 刷新按钮
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.fetch_from_api)
        self._layout.addWidget(refresh_btn)

        self._api_base = "http://localhost:8080"

    def fetch_from_api(self):
        """从 Dashboard API 获取 MCP/Skill 状态"""
        try:
            import httpx
            client = httpx.Client(timeout=5.0)
            mcp_data = {}
            skill_data = {}
            try:
                resp = client.get(f"{self._api_base}/api/v1/config/mcp-servers")
                if resp.status_code == 200:
                    mcp_data = resp.json()
            except Exception:
                pass
            try:
                resp = client.get(f"{self._api_base}/api/v1/config/skills")
                if resp.status_code == 200:
                    skill_data = resp.json()
            except Exception:
                pass
            client.close()
            self.load_status(mcp_data, skill_data)
        except ImportError:
            self.info.setPlainText("需要安装 httpx: pip install httpx")
        except Exception as e:
            self.info.setPlainText(f"获取状态失败: {e}")

    def load_status(self, mcp_data=None, skill_data=None):
        lines = ["── MCP Server ──"]
        servers = (mcp_data or {}).get('servers', [])
        if servers:
            for srv in servers:
                name = srv.get('name') or srv.get('server_id', '?')
                status = srv.get('status', '?')
                tools_count = len(srv.get('tools', []))
                lines.append(f"  {name}  [{status}]  工具:{tools_count}")
        else:
            lines.append("  (无)")

        lines.append("")
        lines.append("── Skill ──")
        skills = (skill_data or {}).get('skills', [])
        if skills:
            for sk in skills:
                name = sk.get('name') or sk.get('skill_id', '?')
                status = sk.get('status', '?')
                lines.append(f"  {name}  [{status}]")
        else:
            lines.append("  (无)")

        stats = (skill_data or {}).get('stats', {})
        if stats:
            lines.append("")
            lines.append(f"总执行: {stats.get('total_executions', 0)}  错误: {stats.get('total_errors', 0)}")

        self.info.setPlainText("\n".join(lines))


# ═══════════════════════════════════════════════
#  主侧边栏 — 书法卷轴式展收
# ═══════════════════════════════════════════════
class SidebarUI(QWidget):
    """
    UFO³ Galaxy 主 UI 侧边栏

    书法卷轴交互:
      展开 — 宽度 0→420, 高度从中心向上下展开, 透明度 0→1, 光线扫过
      收回 — 反向动画
    """

    command_submitted = pyqtSignal(str)

    SIDEBAR_W = 420
    ANIM_DUR = 450  # ms

    def __init__(self, on_command: Optional[Callable[[str], None]] = None):
        super().__init__()

        self.on_command = on_command
        self.is_visible = False
        self._api_base = "http://localhost:8099"

        if on_command:
            self.command_submitted.connect(on_command)

        self._init_window()
        self._build_ui()
        self._setup_scroll_animation()
        self._setup_hotkey()

        logger.info("SidebarUI 初始化完成 (OPPO 光场 + 书法卷轴)")

    # ── 窗口配置 ──
    def _init_window(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        screen = QApplication.primaryScreen().geometry()
        self._screen_w = screen.width()
        self._screen_h = screen.height()

        # 初始: 屏幕右侧外, 宽度 0, 居中一小条
        mid_y = self._screen_h // 2 - 50
        self.setGeometry(self._screen_w, mid_y, 0, 100)

    # ── 构建 UI ──
    def _build_ui(self):
        # 根布局
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 光场层
        self.light_field = LightFieldWidget(self)

        # 标题栏
        root.addWidget(self._build_title_bar())

        # 模式选择栏
        root.addWidget(self._build_mode_bar())

        # 内容堆叠
        self.stack = QStackedWidget()
        self.chat_panel = ChatPanel()
        self.chat_panel.command_submitted.connect(self._on_chat_submit)
        self.agent_panel = AgentPanel()
        self.twin_panel = TwinPanel()
        self.device_panel = DevicePanel()
        self.mcp_skill_panel = McpSkillPanel()

        self.stack.addWidget(self.chat_panel)    # 0
        self.stack.addWidget(self.agent_panel)   # 1
        self.stack.addWidget(self.twin_panel)    # 2
        self.stack.addWidget(self.device_panel)  # 3
        self.stack.addWidget(self.mcp_skill_panel)  # 4

        root.addWidget(self.stack, 1)

        # 快捷操作栏
        root.addWidget(self._build_shortcuts())

        self._apply_theme()

    def _build_title_bar(self):
        bar = QWidget()
        bar.setFixedHeight(44)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 10, 0)

        title = QLabel("UFO³ Galaxy")
        title.setFont(QFont("Consolas", 13, QFont.Bold))
        lay.addWidget(title)
        lay.addStretch()

        self.status_label = QLabel("● 在线")
        self.status_label.setStyleSheet(f"color: #4ade80; font-size: 11px; background: transparent;")
        lay.addWidget(self.status_label)

        close_btn = QPushButton("×")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none; color: {C.TEXT_SEC}; font-size: 18px; }}
            QPushButton:hover {{ color: #ff4444; }}
        """)
        close_btn.clicked.connect(self.toggle_visibility)
        lay.addWidget(close_btn)

        return bar

    def _build_mode_bar(self):
        bar = QWidget()
        bar.setFixedHeight(36)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 0, 10, 4)
        lay.setSpacing(4)

        self.mode_btns = []
        modes = [("对话", 0), ("Agent", 1), ("孪生", 2), ("设备", 3), ("MCP/Skill", 4)]
        for label, idx in modes:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(idx == 0)
            btn.clicked.connect(lambda checked, i=idx: self._switch_mode(i))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; border: 1px solid transparent;
                    border-radius: 12px; padding: 3px 10px;
                    color: {C.TEXT_SEC}; font-family: 'Consolas', monospace; font-size: 11px;
                }}
                QPushButton:hover {{ color: {C.TEXT}; background: {C.GLOW}; }}
                QPushButton:checked {{
                    color: {C.TEXT}; border-color: {C.BORDER_HI};
                    background: rgba(255,255,255,0.05);
                }}
            """)
            lay.addWidget(btn)
            self.mode_btns.append(btn)

        lay.addStretch()
        return bar

    def _build_shortcuts(self):
        bar = QWidget()
        bar.setFixedHeight(46)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 4, 10, 8)
        lay.setSpacing(6)

        for label, action in [("截图", "截图"), ("剪贴板", "查看剪贴板"), ("任务", "查看任务列表")]:
            btn = QPushButton(label)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {C.BG_CARD}; border: 1px solid {C.BORDER};
                    border-radius: 8px; padding: 5px 12px;
                    color: {C.TEXT_SEC}; font-family: 'Consolas', monospace; font-size: 10px;
                }}
                QPushButton:hover {{ border-color: {C.BORDER_HI}; color: {C.TEXT}; }}
                QPushButton:pressed {{ background: {C.ACCENT}; color: {C.BG_DEEP}; }}
            """)
            btn.clicked.connect(lambda _, a=action: self.command_submitted.emit(a))
            lay.addWidget(btn)

        lay.addStretch()
        return bar

    def _apply_theme(self):
        """全局黑白灰主题"""
        self.setStyleSheet(f"""
            QWidget {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 {C.BG_DEEP}, stop:0.5 {C.BG_MID}, stop:1 {C.BG_DEEP}
                );
                color: {C.TEXT};
                font-family: 'Consolas', 'JetBrains Mono', 'Monaco', monospace;
            }}
            QScrollBar:vertical {{
                background: {C.BG_DEEP}; width: 6px; border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER}; border-radius: 3px; min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {C.BORDER_HI}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

    # ── 模式切换 ──
    def _switch_mode(self, idx):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self.mode_btns):
            btn.setChecked(i == idx)

    # ── 书法卷轴动画 ──
    def _setup_scroll_animation(self):
        """
        展开动画: 宽度 0→420, 高度 center→full, 透明度 0→1
        同时光场扫光 0→1
        """
        # 几何动画 (卷轴展开/收回)
        self.anim_geo = QPropertyAnimation(self, b"geometry")
        self.anim_geo.setDuration(self.ANIM_DUR)
        self.anim_geo.setEasingCurve(QEasingCurve.OutQuart)

        # 透明度动画
        self.anim_opacity = QPropertyAnimation(self, b"windowOpacity")
        self.anim_opacity.setDuration(self.ANIM_DUR)
        self.anim_opacity.setEasingCurve(QEasingCurve.OutCubic)

        # 光线扫过动画
        self.anim_light = QPropertyAnimation(self.light_field, b"light_pos")
        self.anim_light.setDuration(self.ANIM_DUR + 200)
        self.anim_light.setEasingCurve(QEasingCurve.InOutCubic)

        # 并行组
        self.anim_open = QParallelAnimationGroup()
        self.anim_open.addAnimation(self.anim_geo)
        self.anim_open.addAnimation(self.anim_opacity)
        self.anim_open.addAnimation(self.anim_light)

        # 收回用独立组
        self.anim_close_geo = QPropertyAnimation(self, b"geometry")
        self.anim_close_geo.setDuration(int(self.ANIM_DUR * 0.8))
        self.anim_close_geo.setEasingCurve(QEasingCurve.InQuart)

        self.anim_close_opacity = QPropertyAnimation(self, b"windowOpacity")
        self.anim_close_opacity.setDuration(int(self.ANIM_DUR * 0.8))
        self.anim_close_opacity.setEasingCurve(QEasingCurve.InCubic)

        self.anim_close = QParallelAnimationGroup()
        self.anim_close.addAnimation(self.anim_close_geo)
        self.anim_close.addAnimation(self.anim_close_opacity)
        self.anim_close.finished.connect(self.hide)

    def _setup_hotkey(self):
        from PyQt5.QtWidgets import QShortcut
        shortcut = QShortcut(QKeySequence("F12"), self)
        shortcut.activated.connect(self.toggle_visibility)
        logger.info("热键: F12 切换侧边栏")

    # ── 展开/收回 ──
    def toggle_visibility(self):
        if self.is_visible:
            self.hide_sidebar()
        else:
            self.show_sidebar()

    def show_sidebar(self):
        if self.is_visible:
            return

        self.is_visible = True

        # 停止正在运行的动画
        self.anim_open.stop()
        self.anim_close.stop()

        # 起始: 屏幕右侧, 零宽, 垂直居中一小条
        mid_y = self._screen_h // 2 - 50
        start_rect = QRect(self._screen_w, mid_y, 0, 100)

        # 终止: 全高, 宽420, 紧贴右侧
        end_rect = QRect(
            self._screen_w - self.SIDEBAR_W, 0,
            self.SIDEBAR_W, self._screen_h
        )

        # 几何
        self.anim_geo.setStartValue(start_rect)
        self.anim_geo.setEndValue(end_rect)

        # 透明度
        self.setWindowOpacity(0.0)
        self.anim_opacity.setStartValue(0.0)
        self.anim_opacity.setEndValue(1.0)

        # 光线扫过
        self.anim_light.setStartValue(0.0)
        self.anim_light.setEndValue(1.0)

        self.show()
        self.anim_open.start()

        # 展开后聚焦输入
        QTimer.singleShot(self.ANIM_DUR + 50, self._focus_input)
        logger.info("侧边栏展开 (卷轴)")

    def hide_sidebar(self):
        if not self.is_visible:
            return

        self.is_visible = False

        self.anim_open.stop()
        self.anim_close.stop()

        current = self.geometry()
        mid_y = self._screen_h // 2 - 50
        end_rect = QRect(self._screen_w, mid_y, 0, 100)

        self.anim_close_geo.setStartValue(current)
        self.anim_close_geo.setEndValue(end_rect)

        self.anim_close_opacity.setStartValue(self.windowOpacity())
        self.anim_close_opacity.setEndValue(0.0)

        self.anim_close.start()
        logger.info("侧边栏收回 (卷轴)")

    def _focus_input(self):
        if self.stack.currentIndex() == 0:
            self.chat_panel.input_field.setFocus()

    # ── 光场层跟随 ──
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.light_field.setGeometry(0, 0, self.width(), self.height())

    # ── 对话回调 ──
    def _on_chat_submit(self, text):
        self.command_submitted.emit(text)

    # ── 公共接口 ──
    def add_message(self, sender: str, message: str):
        self.chat_panel.add_message(sender, message)

    def update_status(self, status: str, color: str = "#4ade80"):
        self.status_label.setText(f"● {status}")
        self.status_label.setStyleSheet(f"color: {color}; font-size: 11px; background: transparent;")

    def update_agent_status(self, data: dict):
        self.agent_panel.load_status(data)

    def update_twin_status(self, data: dict):
        self.twin_panel.load_status(data)

    def update_device_status(self, devices: list):
        self.device_panel.load_status(devices)

    def update_mcp_skill_status(self, mcp_data: dict = None, skill_data: dict = None):
        self.mcp_skill_panel.load_status(mcp_data, skill_data)


# ═══════════════════════════════════════════════
#  测试入口
# ═══════════════════════════════════════════════
def main():
    """测试主函数"""
    logging.basicConfig(level=logging.INFO)

    app = QApplication(sys.argv)

    def on_command(command: str):
        print(f"收到命令: {command}")
        sidebar.add_message("系统", f"正在处理: {command}")

    sidebar = SidebarUI(on_command=on_command)
    sidebar.show_sidebar()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
