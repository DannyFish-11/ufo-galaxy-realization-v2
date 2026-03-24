"""
Galaxy 客户端 - OPPO 光场设计风格 · 全能智能体界面
=======================================================

混合模式：F12 唤出侧边栏，可展开为全功能窗口。
包含：对话（全能智能体）、Agent 工厂 + Team、设备控制、系统状态、设置 五个 Tab。

设计灵感：OPPO ColorOS 光场美学
- 流光渐变背景 + 径向光晕
- 磨砂半透明面板
- 圆角 + 柔阴影
- 流体动画

核心理念：
Windows 客户端 = 主战场（类 OpenClaude 的全能智能体）
自然语言 → Agent 调度 → 多模型路由 → 多 Agent 协作 → 跨设备控制 → 本地操控
"""

import sys
from core.port_config import get_service_port
import json
import logging
import html as html_module
from datetime import datetime
from typing import Optional, Callable, List, Dict

try:
    from PyQt5.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout,
        QTextEdit, QLineEdit, QPushButton, QLabel, QScrollArea,
        QStackedWidget, QFrame, QSizePolicy, QGraphicsDropShadowEffect,
        QGraphicsOpacityEffect, QComboBox
    )
    from PyQt5.QtCore import (
        Qt, QPropertyAnimation, QEasingCurve, pyqtSignal, QTimer,
        QRect, QSize, QPoint, QThread, pyqtSlot, QParallelAnimationGroup,
        pyqtProperty, QSequentialAnimationGroup, QAbstractAnimation
    )
    from PyQt5.QtGui import (
        QFont, QPalette, QColor, QLinearGradient, QRadialGradient,
        QPainter, QBrush, QPen, QIcon, QFontDatabase, QPainterPath
    )
except ImportError:
    print("错误: PyQt5 未安装，无法启动 Galaxy 客户端 UI。")
    print("Error: PyQt5 is not installed. Cannot start Galaxy client UI.")
    print("请安装依赖 / Install dependency: pip install PyQt5")
    print("如使用 conda / With conda: conda install pyqt")
    sys.exit(1)

logger = logging.getLogger(__name__)

# ── 光场色彩方案（纯黑/白/灰梯度） ──
COLORS = {
    # 背景层（纯黑 → 深灰梯度）
    "bg_dark": "#000000",
    "bg_medium": "#0a0a0a",
    "bg_panel": "#0f0f0f",
    "bg_panel_hover": "#1a1a1a",
    "bg_input": "#0d0d0d",
    "bg_card": "#111111",
    # 边框（灰度梯度）
    "border": "#1a1a1a",
    "border_hover": "#2a2a2a",
    "border_focus": "#333333",
    # 主色调（纯白 → 灰白 → 中灰）
    "primary": "#ffffff",
    "secondary": "#b0b0b0",
    "accent": "#808080",
    # 文字（白到暗灰梯度）
    "text": "#ffffff",
    "text_secondary": "#b0b0b0",
    "text_dim": "#666666",
    "text_muted": "#404040",
    # 状态色（也用灰度表达）
    "success": "#c0c0c0",
    "error": "#909090",
    "warning": "#a0a0a0",
    "info": "#888888",
    # 光场效果色
    "glow": "#ffffff",
    "glow_dim": "#333333",
}

# ── Audiofier 工业控制层色彩方案 ──
AUDIOFIER = {
    "bg_charcoal":   "#121212",
    "bg_panel":      "#1a1a1a",
    "bg_surface":    "#222222",
    "border":        "#2a2a2a",
    "border_hi":     "#3a3a3a",
    # Layer A — crimson/red family
    "layer_a":       "#B22222",
    "layer_a_hi":    "#DC143C",
    "layer_a_glow":  "rgba(178, 34, 34, 0.35)",
    "layer_a_dim":   "rgba(178, 34, 34, 0.15)",
    # Layer B — cyan/blue family
    "layer_b":       "#00BFFF",
    "layer_b_hi":    "#00CED1",
    "layer_b_glow":  "rgba(0, 191, 255, 0.35)",
    "layer_b_dim":   "rgba(0, 191, 255, 0.15)",
    # Text
    "text":          "#e0e0e0",
    "text_sec":      "#888888",
    "text_dim":      "#444444",
    # LED states
    "led_active":    "#00FF88",
    "led_idle":      "#333333",
    "led_warn":      "#FFA500",
    "led_error":     "#FF3333",
    # Layer idle tints (semi-transparent, for inactive LED state)
    "layer_a_idle":  (178, 34, 34, 40),
    "layer_b_idle":  (0, 100, 140, 40),
}

SIDEBAR_WIDTH = 1280
SIDEBAR_COLLAPSED_WIDTH = 40
FULL_WIDTH = 940
FULL_HEIGHT = 720


def _compute_responsive_sizes(screen_w: int, screen_h: int) -> dict:
    """Compute adaptive UI dimensions based on the primary screen resolution.

    Breakpoints (width):
      < 1280 px  → compact desktop
      1280–1920  → standard / 1080p desktop  (baseline)
      > 1920 px  → large / high-DPI / ultra-wide desktop

    Returns a dict with all size/font/spacing values that the main window
    should use instead of the hard-coded module-level constants.

    Width ratios chosen so the panel leaves a comfortable visible margin:
      compact  – 0.50 of screen width (half-screen overlay on small displays)
      standard – capped at SIDEBAR_WIDTH (1280 px) so it never overflows
      large    – 0.65 of screen width keeps 35 % visible behind the panel
    Full-window ratios follow a similar "leave a margin" principle:
      compact  – 0.80 × 0.82 fills most of a small screen without clipping
      large    – 0.55 × 0.75 avoids an overly stretched window on wide displays
    """
    # ── Sidebar expanded width ─────────────────────────────────────────────
    # Never allow the panel to exceed the physical screen width.
    if screen_w < 1280:
        # ~50 % of screen – leaves half the screen visible on compact desktops
        sidebar_w = max(320, int(screen_w * 0.50))
    elif screen_w <= 1920:
        sidebar_w = min(screen_w - 40, SIDEBAR_WIDTH)   # 1280 or narrower
    else:  # ultra-wide / 4 K
        # ~65 % keeps a comfortable portion of the desktop visible behind it
        sidebar_w = min(1440, int(screen_w * 0.65))

    # ── Full-window dimensions ─────────────────────────────────────────────
    if screen_w < 1280:
        # ~80 % width / ~82 % height – fills most of a small screen comfortably
        full_w = max(700, int(screen_w * 0.80))
        full_h = max(520, int(screen_h * 0.82))
    elif screen_w <= 1920:
        full_w = min(FULL_WIDTH, screen_w - 100)         # 940 or narrower
        full_h = min(FULL_HEIGHT, screen_h - 80)         # 720 or shorter
    else:
        # ~55 % width / ~75 % height – avoids an overly stretched window
        full_w = min(1100, int(screen_w * 0.55))
        full_h = min(800, int(screen_h * 0.75))

    # ── Font sizes ─────────────────────────────────────────────────────────
    if screen_w < 1280:
        font_base, font_title, font_small = 11, 12, 10
    elif screen_w <= 1920:
        font_base, font_title, font_small = 12, 14, 11
    else:
        font_base, font_title, font_small = 13, 15, 12

    # ── Spacing / padding / bar heights ───────────────────────────────────
    if screen_w < 1280:
        padding, spacing, title_h, tab_h = 10, 6, 44, 40
    elif screen_w <= 1920:
        padding, spacing, title_h, tab_h = 12, 8, 48, 44
    else:
        padding, spacing, title_h, tab_h = 16, 10, 52, 48

    return {
        "sidebar_w": sidebar_w,
        "full_w":    full_w,
        "full_h":    full_h,
        "font_base":  font_base,
        "font_title": font_title,
        "font_small": font_small,
        "padding":   padding,
        "spacing":   spacing,
        "title_h":   title_h,
        "tab_h":     tab_h,
    }


class GlowPanel(QFrame):
    """磨砂半透明面板 + 径向光晕效果"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._glow_opacity_value = 0.03
        self._breath_animation = QPropertyAnimation(self, b"glow_opacity")
        self._breath_animation.setDuration(4000)
        self._breath_animation.setStartValue(0.02)
        self._breath_animation.setEndValue(0.06)
        self._breath_animation.setLoopCount(-1)  # infinite
        self._breath_animation.setEasingCurve(QEasingCurve.InOutSine)
        self._breath_animation.start()

    def _get_glow_opacity(self):
        return self._glow_opacity_value

    def _set_glow_opacity(self, value):
        self._glow_opacity_value = value
        self.update()

    glow_opacity = pyqtProperty(float, _get_glow_opacity, _set_glow_opacity)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Draw radial gradient background (center white glow fading to transparent)
        gradient = QRadialGradient(
            self.width() / 2, self.height() / 2,
            max(self.width(), self.height()) / 2
        )
        gradient.setColorAt(0, QColor(255, 255, 255, int(self._glow_opacity_value * 255)))
        gradient.setColorAt(1, QColor(0, 0, 0, 0))
        painter.fillRect(self.rect(), gradient)
        super().paintEvent(event)


class FlowBorderFrame(QFrame):
    """带动态渐变边框的面板，6 秒循环灰度边框色"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._border_phase = 0.0
        self._border_timer = QTimer(self)
        self._border_timer.timeout.connect(self._animate_border)
        self._border_timer.start(50)  # ~20fps

    def _animate_border(self):
        self._border_phase += 0.05 / 6.0 * 2  # full cycle in ~6 seconds
        if self._border_phase > 1.0:
            self._border_phase = 0.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        import math
        # Cycle between gray tones: #1a1a1a -> #333333 -> #1a1a1a
        phase = math.sin(self._border_phase * math.pi * 2)  # -1 to 1
        gray_val = int(0x1a + (0x33 - 0x1a) * (phase + 1) / 2)
        border_color = QColor(gray_val, gray_val, gray_val)

        # Draw rounded rect border
        pen = QPen(border_color, 1.5)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor(COLORS['bg_panel'])))
        path = QPainterPath()
        path.addRoundedRect(1, 1, self.width() - 2, self.height() - 2, 16, 16)
        painter.drawPath(path)
        painter.end()

        # Let children paint on top
        super().paintEvent(event)


# ════════════════════════════════════════════════════════════
# Audiofier 工业控制层组件
# ════════════════════════════════════════════════════════════

class IndustrialKnob(QWidget):
    """Audiofier 风格拟物化旋钮控件.

    使用 QPainter 绘制:
    - 深炭黑圆形底盘 + 多层阴影体积感
    - 环形金属反射渐变
    - 可旋转指示线 (0~270° 范围)
    - Layer A (红) / Layer B (蓝) 色彩编码高亮环

    参数:
        label (str): 旋钮标签文字.
        layer (str): "A" | "B" | None — 决定高亮环颜色.
        value (float): 0.0 ~ 1.0 初始值.
    """
    value_changed = pyqtSignal(float)

    # Sensitivity constants: pixels of drag / wheel units to traverse full 0→1 range.
    _DRAG_SENSITIVITY  = 120.0   # px for full sweep via vertical drag
    _WHEEL_SENSITIVITY = 1200.0  # angleDelta units for full sweep via mouse wheel

    def __init__(self, label: str = "", layer: str = None, value: float = 0.5, parent=None):
        super().__init__(parent)
        self._label = label
        self._layer = layer
        self._value = max(0.0, min(1.0, value))
        self._dragging = False
        self._drag_start_y = 0
        self._drag_start_val = 0.0
        self.setFixedSize(64, 76)
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip(f"{label}: {self._value:.2f}")

    @property
    def value(self) -> float:
        return self._value

    def set_value(self, v: float):
        self._value = max(0.0, min(1.0, v))
        self.setToolTip(f"{self._label}: {self._value:.2f}")
        self.update()
        self.value_changed.emit(self._value)

    def paintEvent(self, event):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # cx/cy = center of the 64×64 drawing area (widget width / 2)
        # r = knob radius (leaves a 4px margin inside the 64px width)
        cx, cy, r = 32, 32, 28

        # 外阴影 (绘在圆形之前) — use symmetric offsets so the shadow is centered
        shadow_grad = QRadialGradient(cx + 3, cy + 3, r + 6)
        shadow_grad.setColorAt(0, QColor(0, 0, 0, 100))
        shadow_grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(shadow_grad))
        p.setPen(Qt.NoPen)
        p.drawEllipse(cx - (r + 3), cy - (r + 3), (r + 3) * 2, (r + 3) * 2)

        # 底盘: 深炭黑 + 金属反射 (conic-gradient 近似)
        metal_grad = QRadialGradient(cx - 8, cy - 8, r * 2)
        metal_grad.setColorAt(0.0, QColor(68, 68, 68))
        metal_grad.setColorAt(0.4, QColor(22, 22, 22))
        metal_grad.setColorAt(1.0, QColor(12, 12, 12))
        p.setBrush(QBrush(metal_grad))
        p.setPen(QPen(QColor(20, 20, 20), 2))
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # 内高光 (左上白色弧线感)
        inner_hi = QRadialGradient(cx - 10, cy - 10, r)
        inner_hi.setColorAt(0.0, QColor(255, 255, 255, 28))
        inner_hi.setColorAt(0.6, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(inner_hi))
        p.setPen(Qt.NoPen)
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # Layer 高亮环
        if self._layer == "A":
            ring_color = QColor(AUDIOFIER["layer_a"])
        elif self._layer == "B":
            ring_color = QColor(AUDIOFIER["layer_b"])
        else:
            ring_color = QColor(80, 80, 80)

        # Arc from -225° to value_angle (-225 + 270*value)
        span_angle = int(270 * self._value)
        p.setBrush(Qt.NoBrush)
        arc_pen = QPen(ring_color, 3)
        arc_pen.setCapStyle(Qt.RoundCap)
        p.setPen(arc_pen)
        # Qt uses 16ths of a degree, CCW from 3-o'clock
        p.drawArc(cx - r - 2, cy - r - 2, (r + 2) * 2, (r + 2) * 2,
                  (-225 + 90) * 16, -span_angle * 16)

        # 指示线
        # angle_deg: offset from Qt's 0° (3 o'clock), CCW; zero position is ~7:30
        angle_deg = -225 + 270 * self._value
        # Convert from Qt coords (0°=3 o'clock, CCW) to math coords (0°=12 o'clock, CW)
        angle_rad = math.radians(angle_deg - 90)
        lx = int(cx + (r - 8) * math.cos(angle_rad))
        ly = int(cy + (r - 8) * math.sin(angle_rad))
        lx2 = int(cx + (r - 2) * math.cos(angle_rad))
        ly2 = int(cy + (r - 2) * math.sin(angle_rad))
        ind_pen = QPen(QColor(230, 230, 230), 2)
        ind_pen.setCapStyle(Qt.RoundCap)
        p.setPen(ind_pen)
        p.drawLine(lx, ly, lx2, ly2)

        # 标签
        if self._label:
            p.setPen(QPen(QColor(AUDIOFIER["text_sec"])))
            font = QFont("Consolas", 8)
            p.setFont(font)
            p.drawText(0, 66, 64, 12, Qt.AlignCenter, self._label)

        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_start_y = event.globalY()
            self._drag_start_val = self._value

    def mouseMoveEvent(self, event):
        if self._dragging:
            delta = (self._drag_start_y - event.globalY()) / self._DRAG_SENSITIVITY
            self.set_value(self._drag_start_val + delta)

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def wheelEvent(self, event):
        delta = event.angleDelta().y() / self._WHEEL_SENSITIVITY
        self.set_value(self._value + delta)


class LedIndicator(QWidget):
    """Audiofier 风格 LED 指示灯.

    小圆形 LED, 支持多种状态色 + 发光 glow 效果.
    状态: "active" | "idle" | "warn" | "error"
    Layer: "A" | "B" | None — 使用 A/B 色彩编码代替默认状态色.
    """

    def __init__(self, label: str = "", state: str = "idle",
                 layer: str = None, size: int = 12, parent=None):
        super().__init__(parent)
        self._label = label
        self._state = state
        self._layer = layer
        self._size = size
        lw = max(size + 4, 60) if label else size + 4
        self.setFixedSize(lw, size + (14 if label else 4))

    def set_state(self, state: str):
        """Change LED state: 'active' | 'idle' | 'warn' | 'error'."""
        self._state = state
        self.update()

    def _led_color(self) -> QColor:
        if self._layer == "A":
            return QColor(AUDIOFIER["layer_a"]) if self._state != "idle" else QColor(*AUDIOFIER["layer_a_idle"])
        if self._layer == "B":
            return QColor(AUDIOFIER["layer_b"]) if self._state != "idle" else QColor(*AUDIOFIER["layer_b_idle"])
        color_map = {
            "active": QColor(AUDIOFIER["led_active"]),
            "idle":   QColor(AUDIOFIER["led_idle"]),
            "warn":   QColor(AUDIOFIER["led_warn"]),
            "error":  QColor(AUDIOFIER["led_error"]),
        }
        return color_map.get(self._state, QColor(AUDIOFIER["led_idle"]))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self._size
        cx, cy = s // 2 + 2, s // 2 + 2
        color = self._led_color()

        # Glow halo (when not idle)
        if self._state != "idle":
            glow = QRadialGradient(cx, cy, s)
            glow_color = QColor(color)
            glow_color.setAlpha(80)
            glow.setColorAt(0, glow_color)
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(glow))
            p.setPen(Qt.NoPen)
            p.drawEllipse(cx - s, cy - s, s * 2, s * 2)

        # LED body
        grad = QRadialGradient(cx - s // 4, cy - s // 4, s // 2)
        hi_color = QColor(color)
        hi_color.setAlpha(255)
        grad.setColorAt(0, hi_color.lighter(160))
        grad.setColorAt(1, hi_color)
        p.setBrush(QBrush(grad))
        p.setPen(QPen(color.darker(150), 1))
        r = s // 2
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # Label
        if self._label:
            p.setPen(QPen(QColor(AUDIOFIER["text_sec"])))
            font = QFont("Consolas", 7)
            p.setFont(font)
            p.drawText(0, s + 4, self.width(), 12, Qt.AlignCenter, self._label)

        p.end()


class APIClient:
    """HTTP API 客户端"""

    def __init__(self, base_url: str = f"http://localhost:{get_service_port('dashboard')}"):
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

        # 主背景渐变（纯黑到深灰）
        bg = QLinearGradient(0, 0, w, h)
        bg.setColorAt(0.0, QColor(0, 0, 0))        # 纯黑
        bg.setColorAt(0.5, QColor(8, 8, 8))         # 极深灰
        bg.setColorAt(1.0, QColor(5, 5, 5))         # 近黑
        painter.fillRect(self.rect(), QBrush(bg))

        # 光晕 1 - 白色微光 (缓慢移动)
        import math
        cx1 = w * 0.3 + math.sin(self._phase) * 40
        cy1 = h * 0.4 + math.cos(self._phase * 0.7) * 30
        g1 = QRadialGradient(cx1, cy1, w * 0.35)
        g1.setColorAt(0.0, QColor(255, 255, 255, 18))
        g1.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(self.rect(), QBrush(g1))

        # 光晕 2 - 灰白
        cx2 = w * 0.7 + math.cos(self._phase * 0.8) * 35
        cy2 = h * 0.6 + math.sin(self._phase * 0.6) * 25
        g2 = QRadialGradient(cx2, cy2, w * 0.3)
        g2.setColorAt(0.0, QColor(200, 200, 200, 12))
        g2.setColorAt(1.0, QColor(200, 200, 200, 0))
        painter.fillRect(self.rect(), QBrush(g2))

        # 光晕 3 - 暗灰 (微弱)
        cx3 = w * 0.5 + math.sin(self._phase * 1.2) * 30
        cy3 = h * 0.2 + math.cos(self._phase * 0.9) * 20
        g3 = QRadialGradient(cx3, cy3, w * 0.25)
        g3.setColorAt(0.0, QColor(150, 150, 150, 8))
        g3.setColorAt(1.0, QColor(150, 150, 150, 0))
        painter.fillRect(self.rect(), QBrush(g3))

        painter.end()


# ════════════════════════════════════════════════════════════
# 通用样式辅助
# ════════════════════════════════════════════════════════════

def _btn_style(color: str) -> str:
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


def _input_style() -> str:
    return f"""
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
    """


def _combo_style() -> str:
    return f"""
        QComboBox {{
            background: {COLORS['bg_input']};
            border: 1px solid {COLORS['border']};
            border-radius: 10px;
            padding: 8px 14px;
            color: {COLORS['text']};
            font-size: 12px;
        }}
        QComboBox::drop-down {{
            border: none;
            width: 24px;
        }}
        QComboBox QAbstractItemView {{
            background: {COLORS['bg_panel']};
            color: {COLORS['text']};
            border: 1px solid {COLORS['border']};
            selection-background-color: {COLORS['accent']};
        }}
    """


def _textarea_style() -> str:
    return f"""
        QTextEdit {{
            background: transparent;
            border: none;
            color: {COLORS['text']};
            font-size: 12px;
            font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
        }}
    """


def _safe(text: str) -> str:
    """HTML 转义"""
    return html_module.escape(str(text))


# ════════════════════════════════════════════════════════════
# Tab 0: ChatPanel — 全能智能体对话
# ════════════════════════════════════════════════════════════

class ChatPanel(QWidget):
    """全能智能体对话面板

    像 OpenClaude 一样：自然语言 → 自动判断模式 → 显示路由/思考/工具/回复全流程。
    维护 conversation_history 实现连续对话。
    """

    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        self._workers: List[AsyncWorker] = []
        self.conversation_history: List[Dict] = []
        self._current_model = ""
        self._current_mode = "chat"
        # 跨设备统一会话支持
        self._session_id = ""
        self._user_id = "windows_user"
        self._device_id = "windows_client"
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)

        # ── 顶部状态栏：模型 + 模式指示 ──
        status_bar = QHBoxLayout()
        status_bar.setSpacing(8)

        self.mode_indicator = QLabel("chat")
        self.mode_indicator.setStyleSheet(f"""
            QLabel {{
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                padding: 3px 10px;
                color: {COLORS['primary']};
                font-size: 11px;
                font-weight: 600;
            }}
        """)
        status_bar.addWidget(self.mode_indicator)

        self.model_indicator = QLabel("awaiting...")
        self.model_indicator.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_dim']};
                font-size: 11px;
            }}
        """)
        status_bar.addWidget(self.model_indicator)
        status_bar.addStretch()

        # 清空对话按钮
        clear_btn = QPushButton("清空")
        clear_btn.setFixedHeight(26)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 2px 10px;
                color: {COLORS['text_dim']};
                font-size: 11px;
            }}
            QPushButton:hover {{ color: {COLORS['text']}; border-color: {COLORS['text_dim']}; }}
        """)
        clear_btn.clicked.connect(self._clear_conversation)
        status_bar.addWidget(clear_btn)

        layout.addLayout(status_bar)

        # ── 消息区域 ──
        self.messages_area = QTextEdit()
        self.messages_area.setReadOnly(True)
        self.messages_area.setStyleSheet(f"""
            QTextEdit {{
                background: transparent;
                border: none;
                color: {COLORS['text']};
                font-size: 13px;
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
                padding: 8px;
            }}
        """)
        self.messages_area.setPlaceholderText(
            "Galaxy 全能智能体 - 输入任何指令或问题\n\n"
            "支持：自然对话 / Agent 任务调度 / 多模型路由\n"
            "       设备控制 / 本地自动化 / Agent Team 协作"
        )
        layout.addWidget(self.messages_area, 1)

        # ── 输入区 ──
        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入消息... (Enter 发送)")
        self.input_field.setStyleSheet(_input_style())
        self.input_field.returnPressed.connect(self._send)
        input_layout.addWidget(self.input_field)

        send_btn = QPushButton("发送")
        send_btn.setFixedSize(64, 40)
        send_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {COLORS['accent']}, stop:1 {COLORS['primary']});
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

    def _clear_conversation(self):
        self.conversation_history.clear()
        self.messages_area.clear()
        self.model_indicator.setText("awaiting...")
        self.mode_indicator.setText("chat")

    def _send(self):
        text = self.input_field.text().strip()
        if not text:
            return
        self.input_field.clear()

        # 添加用户消息到历史
        self.conversation_history.append({"role": "user", "content": text})
        self._render_user_message(text)

        # 显示等待状态
        self._render_thinking()

        # 调用后端（带统一会话支持）
        payload = {
            "message": text,
            "device_id": self._device_id,
            "user_id": self._user_id,
            "session_id": self._session_id,
            "context": self.conversation_history[-10:],
        }
        worker = AsyncWorker(self.api.post, "/api/v1/chat", payload)
        worker.finished.connect(self._on_response)
        self._workers.append(worker)
        worker.start()

    def _render_user_message(self, text: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.messages_area.append(
            f'<div style="margin-bottom: 10px;">'
            f'<span style="color: {COLORS["primary"]}; font-weight: 600; font-size: 12px;">你</span> '
            f'<span style="color: {COLORS["text_muted"]}; font-size: 10px;">{timestamp}</span>'
            f'<br/>'
            f'<span style="color: rgba(255,255,255,0.9); font-size: 13px;">{_safe(text)}</span>'
            f'</div>'
        )
        self._scroll_to_bottom()

    def _render_thinking(self):
        self.messages_area.append(
            f'<div id="thinking" style="color: {COLORS["text_dim"]}; font-size: 11px; margin-bottom: 4px;">'
            f'Galaxy 思考中...</div>'
        )
        self._scroll_to_bottom()

    @pyqtSlot(dict)
    def _on_response(self, data: dict):
        # 移除 "思考中..." 行 — 用简单方法：获取全部 HTML 然后去掉最后的 thinking div
        current_html = self.messages_area.toHtml()
        if 'Galaxy 思考中...' in current_html:
            idx = current_html.rfind('<div id="thinking"')
            if idx == -1:
                idx = current_html.rfind('Galaxy 思考中...')
            if idx > 0:
                # 找到包含 thinking 的段落并移除
                end_idx = current_html.find('</div>', idx)
                if end_idx > 0:
                    current_html = current_html[:idx] + current_html[end_idx + 6:]
                    self.messages_area.setHtml(current_html)

        # 解析响应
        if data.get("error"):
            self._render_error(data["error"])
            return

        # 捕获 session_id（跨设备统一会话）
        if data.get("session_id"):
            self._session_id = data["session_id"]

        # 检查是否是增强响应格式
        mode = data.get("mode", "chat")
        model = data.get("model", "")
        reply = data.get("reply", data.get("response", data.get("error", "无响应")))
        routing = data.get("routing", {})
        agent_steps = data.get("agent_steps", [])
        tool_calls = data.get("tool_calls", [])

        # 更新状态栏
        self._current_mode = mode
        self._current_model = model
        self.mode_indicator.setText(mode)
        if model:
            provider = routing.get("provider", "")
            display_model = f"{provider}:{model}" if provider else model
            self.model_indicator.setText(display_model)

        # 分层渲染响应
        timestamp = datetime.now().strftime("%H:%M:%S")
        parts: List[str] = []

        # 头部：Galaxy 标识
        parts.append(
            f'<div style="margin-bottom: 10px;">'
            f'<span style="color: {COLORS["secondary"]}; font-weight: 600; font-size: 12px;">Galaxy</span> '
            f'<span style="color: {COLORS["text_muted"]}; font-size: 10px;">{timestamp}</span>'
        )

        # 1. 路由信息（紧凑灰色行）
        if routing:
            task_type = routing.get("task_type", "")
            r_provider = routing.get("provider", "")
            r_model = routing.get("model", "")
            reason = routing.get("reason", "")
            alternatives = routing.get("alternatives", [])
            alt_text = f' | 备选: {", ".join(alternatives)}' if alternatives else ""
            parts.append(
                f'<div style="background: rgba(255,255,255,0.03); border-radius: 8px; '
                f'padding: 6px 10px; margin: 4px 0; font-size: 11px;">'
                f'<span style="color: {COLORS["text_dim"]};">[{_safe(task_type)}]</span> '
                f'<span style="color: {COLORS["text_dim"]};">&rarr; {_safe(r_provider)}:{_safe(r_model)}{_safe(alt_text)}</span>'
                f'</div>'
            )

        # 2. Agent 步骤（ReAct 过程展示）
        if agent_steps:
            parts.append(
                f'<div style="background: rgba(255, 255, 255, 0.03); border-left: 2px solid rgba(255, 255, 255, 0.12); '
                f'padding: 6px 10px; margin: 4px 0; border-radius: 0 8px 8px 0;">'
            )
            for step in agent_steps:
                step_type = step.get("type", "")
                content = step.get("content", "")
                tool = step.get("tool", "")
                step_input = step.get("input", {})

                if step_type == "thought":
                    parts.append(
                        f'<div style="font-size: 11px; color: rgba(255,255,255,0.6); margin: 2px 0;">'
                        f'<span style="color: {COLORS["primary"]};">Thought:</span> {_safe(content)}</div>'
                    )
                elif step_type == "action":
                    input_str = json.dumps(step_input, ensure_ascii=False) if step_input else ""
                    parts.append(
                        f'<div style="font-size: 11px; color: rgba(255,255,255,0.6); margin: 2px 0;">'
                        f'<span style="color: {COLORS["warning"]};">Action:</span> '
                        f'{_safe(tool)}({_safe(input_str[:100])})</div>'
                    )
                elif step_type == "observation":
                    display = content[:200] + "..." if len(content) > 200 else content
                    parts.append(
                        f'<div style="font-size: 11px; color: rgba(255,255,255,0.5); margin: 2px 0;">'
                        f'<span style="color: {COLORS["secondary"]};">Obs:</span> {_safe(display)}</div>'
                    )
            parts.append('</div>')

        # 3. 工具调用（紧凑卡片）
        if tool_calls:
            for tc in tool_calls:
                tool_name = tc.get("tool", "?")
                output = tc.get("output", "")
                display_output = output[:150] + "..." if len(str(output)) > 150 else output
                parts.append(
                    f'<div style="background: rgba(200, 200, 200, 0.04); border-radius: 8px; '
                    f'padding: 5px 10px; margin: 3px 0; font-size: 11px;">'
                    f'<span style="color: {COLORS["secondary"]};">Tool:</span> '
                    f'<span style="color: {COLORS["text"]};">{_safe(tool_name)}</span> '
                    f'<span style="color: {COLORS["text_dim"]};">&rarr; {_safe(str(display_output))}</span>'
                    f'</div>'
                )

        # 4. 最终回复（主消息）
        parts.append(
            f'<br/><span style="color: rgba(255,255,255,0.9); font-size: 13px; line-height: 1.5;">'
            f'{_safe(reply)}</span>'
        )
        parts.append('</div>')

        self.messages_area.append(''.join(parts))
        self._scroll_to_bottom()

        # 保存到对话历史
        self.conversation_history.append({"role": "assistant", "content": reply})

    def _render_error(self, error: str):
        self.messages_area.append(
            f'<div style="color: {COLORS["error"]}; font-size: 12px; margin-bottom: 8px;">'
            f'Error: {_safe(error)}</div>'
        )
        self._scroll_to_bottom()

    def handle_structured_response(self, json_str: str):
        """从 CommandProcessor 接收结构化 JSON 响应并渲染"""
        try:
            data = json.loads(json_str)
            self._on_response(data)
        except (json.JSONDecodeError, TypeError):
            # 纯文本响应 fallback
            self._on_response({"response": json_str})

    def _scroll_to_bottom(self):
        scrollbar = self.messages_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


# ════════════════════════════════════════════════════════════
# Tab 1: AgentFactoryPanel — Agent 工厂 + Team 管理
# ════════════════════════════════════════════════════════════

class AgentFactoryPanel(QWidget):
    """Agent 工厂 + Team 协作管理面板

    上半部：Agent 创建（模板/智能），Agent 列表
    下半部：Team 创建（3 策略），Team 列表，Team 执行 + 结果
    """

    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        self._workers: List[AsyncWorker] = []
        self._teams: List[Dict] = []
        self._init_ui()
        QTimer.singleShot(500, self._refresh_all)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)

        # ══ 上半部：单 Agent 管理 ══

        # 统计栏
        stats_frame = QFrame()
        stats_frame.setStyleSheet(f"""
            QFrame {{
                background: {COLORS['bg_panel']};
                border: 1px solid {COLORS['border']};
                border-radius: 14px;
                padding: 10px;
            }}
        """)
        stats_layout = QHBoxLayout(stats_frame)
        stats_layout.setContentsMargins(8, 4, 8, 4)
        self.stat_active = QLabel("0")
        self.stat_total = QLabel("0")
        self.stat_teams = QLabel("0")
        self.stat_twins = QLabel("0")
        for label, title in [(self.stat_active, "活跃"), (self.stat_total, "Agent"), (self.stat_teams, "Team"), (self.stat_twins, "孪生")]:
            col = QVBoxLayout()
            label.setStyleSheet(f"color: {COLORS['primary']}; font-size: 18px; font-weight: 700;")
            label.setAlignment(Qt.AlignCenter)
            col.addWidget(label)
            sub = QLabel(title)
            sub.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 10px;")
            sub.setAlignment(Qt.AlignCenter)
            col.addWidget(sub)
            stats_layout.addLayout(col)
        layout.addWidget(stats_frame)

        # Agent 列表
        self.agent_list = QTextEdit()
        self.agent_list.setReadOnly(True)
        self.agent_list.setStyleSheet(_textarea_style())
        self.agent_list.setPlaceholderText("暂无 Agent...")
        self.agent_list.setMaximumHeight(160)
        layout.addWidget(self.agent_list)

        # Agent 操作按钮
        agent_btn_layout = QHBoxLayout()
        agent_btn_layout.setSpacing(6)

        # 模板选择下拉
        self.template_combo = QComboBox()
        self.template_combo.addItems([
            "coordinator", "data_analyst", "code_executor",
            "research", "device_controller", "planner"
        ])
        self.template_combo.setStyleSheet(_combo_style())
        agent_btn_layout.addWidget(self.template_combo)

        btn_create = QPushButton("创建")
        btn_create.setStyleSheet(_btn_style(COLORS['primary']))
        btn_create.clicked.connect(self._create_from_template)
        agent_btn_layout.addWidget(btn_create)

        btn_dynamic = QPushButton("智能创建")
        btn_dynamic.setStyleSheet(_btn_style(COLORS['secondary']))
        btn_dynamic.clicked.connect(self._create_dynamic)
        agent_btn_layout.addWidget(btn_dynamic)

        layout.addLayout(agent_btn_layout)

        # ══ 分隔 ══
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {COLORS['border']};")
        layout.addWidget(sep)

        # ══ 下半部：Team 管理 ══

        team_header = QLabel("Agent Team 协作")
        team_header.setStyleSheet(f"color: {COLORS['accent']}; font-size: 13px; font-weight: 600;")
        layout.addWidget(team_header)

        # Team 创建区
        team_create_layout = QHBoxLayout()
        team_create_layout.setSpacing(6)

        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(["parallel", "specialized", "swarm"])
        self.strategy_combo.setStyleSheet(_combo_style())
        self.strategy_combo.setToolTip(
            "parallel: Perplexity 风格，同一任务多 LLM 并行\n"
            "specialized: 特种部队，子任务分工\n"
            "swarm: 群体智能，同类 Agent 投票"
        )
        team_create_layout.addWidget(self.strategy_combo)

        self.team_task_input = QLineEdit()
        self.team_task_input.setPlaceholderText("任务提示（可选）")
        self.team_task_input.setStyleSheet(f"""
            QLineEdit {{
                background: {COLORS['bg_input']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
                padding: 8px 12px;
                color: {COLORS['text']};
                font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {COLORS['border_focus']}; }}
        """)
        team_create_layout.addWidget(self.team_task_input, 1)

        btn_create_team = QPushButton("组建 Team")
        btn_create_team.setStyleSheet(_btn_style(COLORS['accent']))
        btn_create_team.clicked.connect(self._create_team)
        team_create_layout.addWidget(btn_create_team)

        layout.addLayout(team_create_layout)

        # Team 执行区
        team_exec_layout = QHBoxLayout()
        team_exec_layout.setSpacing(6)

        self.team_select_combo = QComboBox()
        self.team_select_combo.setStyleSheet(_combo_style())
        self.team_select_combo.setPlaceholderText("选择 Team")
        team_exec_layout.addWidget(self.team_select_combo)

        self.team_exec_input = QLineEdit()
        self.team_exec_input.setPlaceholderText("Team 执行任务...")
        self.team_exec_input.setStyleSheet(f"""
            QLineEdit {{
                background: {COLORS['bg_input']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
                padding: 8px 12px;
                color: {COLORS['text']};
                font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {COLORS['border_focus']}; }}
        """)
        self.team_exec_input.returnPressed.connect(self._execute_team)
        team_exec_layout.addWidget(self.team_exec_input, 1)

        btn_exec_team = QPushButton("执行")
        btn_exec_team.setStyleSheet(_btn_style(COLORS['accent']))
        btn_exec_team.clicked.connect(self._execute_team)
        team_exec_layout.addWidget(btn_exec_team)

        layout.addLayout(team_exec_layout)

        # Team 结果区
        self.team_result_area = QTextEdit()
        self.team_result_area.setReadOnly(True)
        self.team_result_area.setStyleSheet(_textarea_style())
        self.team_result_area.setPlaceholderText("Team 执行结果将显示在这里...")
        layout.addWidget(self.team_result_area, 1)

        # 底部刷新
        btn_refresh = QPushButton("刷新全部")
        btn_refresh.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['bg_input']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
                padding: 8px;
                color: {COLORS['text_dim']};
                font-size: 11px;
            }}
            QPushButton:hover {{ color: {COLORS['text']}; }}
        """)
        btn_refresh.clicked.connect(self._refresh_all)
        layout.addWidget(btn_refresh)

    # ── Agent 操作 ──

    def _refresh_all(self):
        self._refresh_agents()
        self._refresh_teams()
        self._refresh_twins()

    def _refresh_agents(self):
        worker = AsyncWorker(self.api.get, "/api/v1/agents")
        worker.finished.connect(self._on_agents_loaded)
        self._workers.append(worker)
        worker.start()

    def _refresh_teams(self):
        worker = AsyncWorker(self.api.get, "/api/v1/agents/teams")
        worker.finished.connect(self._on_teams_loaded)
        self._workers.append(worker)
        worker.start()

    @pyqtSlot(dict)
    def _on_agents_loaded(self, data: dict):
        agents = data.get("agents", [])
        self.stat_total.setText(str(len(agents)))
        active = sum(1 for a in agents if a.get("state") in ("idle", "working", "waiting"))
        self.stat_active.setText(str(active))

        self.agent_list.clear()
        if not agents:
            self.agent_list.setPlaceholderText("暂无 Agent... 点击按钮创建")
            return
        for a in agents:
            state_color = COLORS['success'] if a.get('state') == 'working' else COLORS['text_dim']
            # 检查是否有孪生体信息（Team 的 to_dict 会包含 twin_status）
            twin_info = ""
            twin_status = a.get("twin_status", {})
            if twin_status:
                t_state = twin_status.get("state", "")
                t_mode = twin_status.get("coupling_mode", "")
                t_div = twin_status.get("divergence", 0)
                twin_color = COLORS['success'] if t_state == "synced" else (
                    COLORS['warning'] if t_state == "diverged" else COLORS['text_muted']
                )
                twin_info = (
                    f'<br/><span style="color: {twin_color}; font-size: 9px;">'
                    f'Twin: {_safe(t_state)} ({_safe(t_mode)}) div={t_div:.2f}</span>'
                )
            self.agent_list.append(
                f'<div style="background: rgba(255,255,255,0.03); border-radius: 10px; padding: 6px; margin-bottom: 4px;">'
                f'<span style="font-weight: 600; color: {COLORS["text"]}; font-size: 12px;">{_safe(a.get("name", a.get("id", "?")))}</span> '
                f'<span style="color: {COLORS["text_muted"]}; font-size: 10px;">({_safe(a.get("role", "?"))})</span>'
                f'<span style="color: {state_color}; font-size: 10px; margin-left: 6px;">● {_safe(a.get("state", "?"))}</span>'
                f'{twin_info}'
                f'</div>'
            )

    @pyqtSlot(dict)
    def _on_teams_loaded(self, data: dict):
        teams = data.get("teams", [])
        self._teams = teams
        self.stat_teams.setText(str(len(teams)))

        # 更新 Team 下拉
        self.team_select_combo.clear()
        for t in teams:
            tid = t.get("team_id", "?")
            strategy = t.get("strategy", "?")
            count = t.get("member_count", 0)
            self.team_select_combo.addItem(f"{tid} ({strategy}, {count}人)", tid)

    def _refresh_twins(self):
        worker = AsyncWorker(self.api.get, "/api/v1/twins")
        worker.finished.connect(self._on_twins_loaded)
        self._workers.append(worker)
        worker.start()

    @pyqtSlot(dict)
    def _on_twins_loaded(self, data: dict):
        twins = data.get("twins", [])
        self.stat_twins.setText(str(len(twins)))

        # 在 Team 结果区显示孪生状态概览
        if twins:
            synced = sum(1 for t in twins if t.get("state") == "synced")
            diverged = sum(1 for t in twins if t.get("state") == "diverged")
            detached = sum(1 for t in twins if t.get("state") == "detached")
            self.team_result_area.append(
                f'<div style="background: rgba(180,180,180,0.04); border-radius: 8px; '
                f'padding: 6px 8px; margin: 4px 0; font-size: 11px;">'
                f'<span style="color: {COLORS["accent"]}; font-weight: 600;">孪生状态:</span> '
                f'<span style="color: {COLORS["success"]};">{synced} synced</span> | '
                f'<span style="color: {COLORS["warning"]};">{diverged} diverged</span> | '
                f'<span style="color: {COLORS["text_dim"]};">{detached} detached</span>'
                f'</div>'
            )

    def _create_from_template(self):
        template = self.template_combo.currentText()
        worker = AsyncWorker(self.api.post, "/api/v1/agents/create", {"template": template})
        worker.finished.connect(lambda d: self._on_agent_created(d))
        self._workers.append(worker)
        worker.start()

    def _create_dynamic(self):
        worker = AsyncWorker(self.api.post, "/api/v1/agents/create/dynamic", {
            "task_description": "帮我分析当前系统状态并提供优化建议"
        })
        worker.finished.connect(lambda d: self._on_agent_created(d))
        self._workers.append(worker)
        worker.start()

    @pyqtSlot(dict)
    def _on_agent_created(self, data: dict):
        if data.get("success") or data.get("agent_id"):
            self._refresh_agents()
        else:
            self.agent_list.append(
                f'<div style="color: {COLORS["error"]}; font-size: 11px;">'
                f'创建失败: {_safe(data.get("error", "未知错误"))}</div>'
            )

    # ── Team 操作 ──

    def _create_team(self):
        strategy = self.strategy_combo.currentText()
        task_hint = self.team_task_input.text().strip()
        payload = {"strategy": strategy}
        if task_hint:
            payload["task_hint"] = task_hint

        self.team_result_area.append(
            f'<div style="color: {COLORS["text_dim"]}; font-size: 11px;">组建 {strategy} Team...</div>'
        )

        worker = AsyncWorker(self.api.post, "/api/v1/agents/team/create", payload)
        worker.finished.connect(self._on_team_created)
        self._workers.append(worker)
        worker.start()

    @pyqtSlot(dict)
    def _on_team_created(self, data: dict):
        if data.get("team_id"):
            tid = data["team_id"]
            strategy = data.get("strategy", "?")
            members = data.get("members", [])
            self.team_result_area.append(
                f'<div style="color: {COLORS["success"]}; font-size: 12px; margin: 4px 0;">'
                f'Team [{_safe(tid)}] 已组建 ({_safe(strategy)}, {len(members)} 成员)</div>'
            )
            for m in members:
                self.team_result_area.append(
                    f'<div style="color: {COLORS["text_dim"]}; font-size: 11px; padding-left: 12px;">'
                    f'- {_safe(m.get("role_in_team", "?"))} | {_safe(m.get("provider", "?"))}:{_safe(m.get("model", "?"))}</div>'
                )
            self._refresh_teams()
        else:
            self.team_result_area.append(
                f'<div style="color: {COLORS["error"]}; font-size: 11px;">'
                f'Team 创建失败: {_safe(data.get("error", "未知错误"))}</div>'
            )

    def _execute_team(self):
        if self.team_select_combo.count() == 0:
            self.team_result_area.append(
                f'<div style="color: {COLORS["warning"]}; font-size: 11px;">请先组建 Team</div>'
            )
            return

        team_id = self.team_select_combo.currentData()
        task = self.team_exec_input.text().strip()
        if not task:
            self.team_result_area.append(
                f'<div style="color: {COLORS["warning"]}; font-size: 11px;">请输入执行任务</div>'
            )
            return

        self.team_exec_input.clear()
        self.team_result_area.append(
            f'<div style="color: {COLORS["text_dim"]}; font-size: 11px; margin-top: 8px;">'
            f'Team [{_safe(team_id)}] 执行: {_safe(task)}...</div>'
        )

        worker = AsyncWorker(
            self.api.post,
            f"/api/v1/agents/team/{team_id}/execute",
            {"task": task}
        )
        worker.finished.connect(self._on_team_executed)
        self._workers.append(worker)
        worker.start()

    @pyqtSlot(dict)
    def _on_team_executed(self, data: dict):
        result = data.get("result", data)

        if result.get("error"):
            self.team_result_area.append(
                f'<div style="color: {COLORS["error"]}; font-size: 11px;">'
                f'执行失败: {_safe(result["error"])}</div>'
            )
            return

        # 展示每个成员的结果
        member_results = result.get("member_results", [])
        for mr in member_results:
            member = mr.get("member", {})
            role = member.get("role_in_team", "?")
            provider = member.get("provider", "?")
            model = member.get("model", "?")
            res_text = mr.get("result", "")
            latency = mr.get("latency_ms", 0)
            display = res_text[:200] + "..." if len(str(res_text)) > 200 else res_text

            self.team_result_area.append(
                f'<div style="background: rgba(255,255,255,0.03); border-radius: 8px; '
                f'padding: 6px 8px; margin: 3px 0;">'
                f'<span style="color: {COLORS["primary"]}; font-size: 11px; font-weight: 600;">'
                f'{_safe(role)}</span> '
                f'<span style="color: {COLORS["text_muted"]}; font-size: 10px;">'
                f'{_safe(provider)}:{_safe(model)} | {latency:.0f}ms</span>'
                f'<br/><span style="color: {COLORS["text_dim"]}; font-size: 11px;">{_safe(str(display))}</span>'
                f'</div>'
            )

        # 综合结果
        synthesized = result.get("synthesized", "")
        total_latency = result.get("total_latency_ms", 0)
        if synthesized:
            self.team_result_area.append(
                f'<div style="background: rgba(200, 200, 200, 0.06); border-radius: 10px; '
                f'padding: 8px 10px; margin: 6px 0; border: 1px solid rgba(200, 200, 200, 0.1);">'
                f'<span style="color: {COLORS["secondary"]}; font-size: 12px; font-weight: 600;">'
                f'综合结果</span> '
                f'<span style="color: {COLORS["text_muted"]}; font-size: 10px;">{total_latency:.0f}ms</span>'
                f'<br/><span style="color: rgba(255,255,255,0.85); font-size: 12px;">'
                f'{_safe(synthesized)}</span>'
                f'</div>'
            )


# ════════════════════════════════════════════════════════════
# Tab 2: DevicePanel — 交互式设备控制
# ════════════════════════════════════════════════════════════

class DevicePanel(QWidget):
    """设备控制面板 — 设备列表 + 命令发送 + 本地快捷操作"""

    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        self._workers: List[AsyncWorker] = []
        self._devices: List[Dict] = []
        self._init_ui()
        QTimer.singleShot(500, self._refresh)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)

        # 设备列表
        header = QLabel("已注册设备")
        header.setStyleSheet(f"color: {COLORS['text']}; font-size: 13px; font-weight: 600;")
        layout.addWidget(header)

        self.device_text = QTextEdit()
        self.device_text.setReadOnly(True)
        self.device_text.setStyleSheet(_textarea_style())
        self.device_text.setPlaceholderText("设备列表将显示在这里...")
        self.device_text.setMaximumHeight(180)
        layout.addWidget(self.device_text)

        # 设备命令发送
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {COLORS['border']};")
        layout.addWidget(sep)

        cmd_header = QLabel("设备命令")
        cmd_header.setStyleSheet(f"color: {COLORS['accent']}; font-size: 13px; font-weight: 600;")
        layout.addWidget(cmd_header)

        # 目标设备选择
        device_row = QHBoxLayout()
        device_row.setSpacing(6)

        self.device_select = QComboBox()
        self.device_select.setStyleSheet(_combo_style())
        self.device_select.setPlaceholderText("选择设备")
        device_row.addWidget(self.device_select)

        btn_refresh = QPushButton("刷新")
        btn_refresh.setStyleSheet(_btn_style(COLORS['accent']))
        btn_refresh.clicked.connect(self._refresh)
        device_row.addWidget(btn_refresh)

        layout.addLayout(device_row)

        # 命令输入
        cmd_input_layout = QHBoxLayout()
        cmd_input_layout.setSpacing(6)

        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("输入设备命令...")
        self.cmd_input.setStyleSheet(f"""
            QLineEdit {{
                background: {COLORS['bg_input']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
                padding: 8px 12px;
                color: {COLORS['text']};
                font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {COLORS['border_focus']}; }}
        """)
        self.cmd_input.returnPressed.connect(self._send_command)
        cmd_input_layout.addWidget(self.cmd_input, 1)

        btn_send = QPushButton("发送")
        btn_send.setStyleSheet(_btn_style(COLORS['primary']))
        btn_send.clicked.connect(self._send_command)
        cmd_input_layout.addWidget(btn_send)

        layout.addLayout(cmd_input_layout)

        # 命令结果
        self.cmd_result = QTextEdit()
        self.cmd_result.setReadOnly(True)
        self.cmd_result.setStyleSheet(_textarea_style())
        self.cmd_result.setPlaceholderText("命令结果...")
        layout.addWidget(self.cmd_result, 1)

        # 本地 Windows 快捷操作
        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background: {COLORS['border']};")
        layout.addWidget(sep2)

        shortcuts_label = QLabel("本地快捷操作")
        shortcuts_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        layout.addWidget(shortcuts_label)

        shortcuts_layout = QHBoxLayout()
        shortcuts_layout.setSpacing(6)
        actions = [
            ("截图", "screenshot"),
            ("剪贴板", "clipboard"),
            ("屏幕状态", "screen_state"),
        ]
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

        # 同时获取设备孪生状态
        twin_worker = AsyncWorker(self.api.get, "/api/v1/device-twins")
        twin_worker.finished.connect(self._on_device_twins)
        self._workers.append(twin_worker)
        twin_worker.start()

    @pyqtSlot(dict)
    def _on_device_twins(self, data: dict):
        """显示设备孪生概览"""
        twins_data = data.get("twins", {})
        if not twins_data or not twins_data.get("total_twins", 0):
            return
        total = twins_data.get("total_twins", 0)
        by_status = twins_data.get("by_status", {})
        by_coupling = twins_data.get("by_coupling", {})
        self.cmd_result.append(
            f'<div style="background: rgba(180,180,180,0.04); border-radius: 8px; '
            f'padding: 6px 8px; margin: 4px 0; font-size: 11px;">'
            f'<span style="color: {COLORS["accent"]}; font-weight: 600;">设备孪生:</span> '
            f'{total} 个 | '
            f'状态: {", ".join(f"{k}:{v}" for k, v in by_status.items())} | '
            f'耦合: {", ".join(f"{k}:{v}" for k, v in by_coupling.items())}'
            f'</div>'
        )

    @pyqtSlot(dict)
    def _on_devices(self, data: dict):
        devices = data.get("devices", [])
        self._devices = devices
        self.device_text.clear()
        self.device_select.clear()

        if not devices:
            self.device_text.setPlaceholderText("暂无已注册设备")
            return

        for d in devices:
            online = d.get("online", False)
            dot = COLORS['success'] if online else COLORS['text_muted']
            did = d.get("device_id", "?")
            dtype = d.get("type", "?")
            # 检查是否有孪生体
            twin_info = ""
            if d.get("twin_id"):
                t_status = d.get("twin_status", "unknown")
                t_mode = d.get("twin_coupling", "unknown")
                twin_color = COLORS['success'] if t_status == "synced" else COLORS['text_dim']
                twin_info = (
                    f'<br/><span style="color: {twin_color}; font-size: 9px;">'
                    f'Twin: {_safe(t_status)} ({_safe(t_mode)})</span>'
                )
            self.device_text.append(
                f'<div style="background: rgba(255,255,255,0.03); border-radius: 10px; '
                f'padding: 8px; margin-bottom: 4px;">'
                f'<span style="color: {dot};">●</span> '
                f'<span style="font-weight: 600;">{_safe(did)}</span> '
                f'<span style="color: {COLORS["text_dim"]};">({_safe(dtype)})</span>'
                f'{twin_info}'
                f'</div>'
            )
            self.device_select.addItem(f"{did} ({dtype})", did)

    def _send_command(self):
        if self.device_select.count() == 0:
            self.cmd_result.append(
                f'<div style="color: {COLORS["warning"]}; font-size: 11px;">暂无设备</div>'
            )
            return

        device_id = self.device_select.currentData()
        command = self.cmd_input.text().strip()
        if not command:
            return

        self.cmd_input.clear()
        self.cmd_result.append(
            f'<div style="color: {COLORS["text_dim"]}; font-size: 11px;">'
            f'[{_safe(device_id)}] &gt; {_safe(command)}</div>'
        )

        worker = AsyncWorker(
            self.api.post,
            f"/api/v1/devices/{device_id}/command",
            {"command": command}
        )
        worker.finished.connect(self._on_command_result)
        self._workers.append(worker)
        worker.start()

    @pyqtSlot(dict)
    def _on_command_result(self, data: dict):
        if data.get("error"):
            self.cmd_result.append(
                f'<div style="color: {COLORS["error"]}; font-size: 11px;">{_safe(data["error"])}</div>'
            )
        else:
            result = data.get("result", data.get("output", json.dumps(data, ensure_ascii=False)))
            self.cmd_result.append(
                f'<div style="color: {COLORS["secondary"]}; font-size: 11px;">{_safe(str(result))}</div>'
            )

    def _quick_action(self, action: str):
        self.cmd_result.append(
            f'<div style="color: {COLORS["text_dim"]}; font-size: 11px;">执行本地操作: {_safe(action)}...</div>'
        )
        # 这些快捷操作通过 signal 通知主窗口，由 CommandProcessor 本地处理
        # 这里只显示状态 — 实际由 WindowsClient._on_command 触发
        if hasattr(self, '_quick_action_callback') and self._quick_action_callback:
            self._quick_action_callback(action)


# ════════════════════════════════════════════════════════════
# Tab 3: StatusPanel — 系统状态
# ════════════════════════════════════════════════════════════

class StatusPanel(QWidget):
    """系统状态面板 — 配置/LLM 提供商/节点健康"""

    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        self._workers: List[AsyncWorker] = []
        self._init_ui()
        QTimer.singleShot(500, self._refresh)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)

        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setStyleSheet(_textarea_style())
        layout.addWidget(self.status_text, 1)

        btn_refresh = QPushButton("刷新状态")
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
        self.status_text.clear()
        self.status_text.append(
            f'<div style="color: {COLORS["text_dim"]}; font-size: 11px;">加载中...</div>'
        )

        w1 = AsyncWorker(self.api.get, "/api/v1/config/status")
        w1.finished.connect(self._on_config)
        self._workers.append(w1)
        w1.start()

        w2 = AsyncWorker(self.api.get, "/api/v1/llm/providers")
        w2.finished.connect(self._on_providers)
        self._workers.append(w2)
        w2.start()

        w3 = AsyncWorker(self.api.get, "/api/v1/config/nodes")
        w3.finished.connect(self._on_nodes)
        self._workers.append(w3)
        w3.start()

        w4 = AsyncWorker(self.api.get, "/api/v1/twins")
        w4.finished.connect(self._on_twin_status)
        self._workers.append(w4)
        w4.start()

        w5 = AsyncWorker(self.api.get, "/api/v1/device-twins")
        w5.finished.connect(self._on_device_twin_status)
        self._workers.append(w5)
        w5.start()

    @pyqtSlot(dict)
    def _on_twin_status(self, data: dict):
        twins = data.get("twins", [])
        if not twins:
            return
        self.status_text.append(
            f'<div style="font-size: 13px; font-weight: 600; margin: 10px 0 6px; '
            f'color: {COLORS["accent"]};">Agent 孪生模型</div>'
        )
        for t in twins:
            state = t.get("state", "?")
            mode = t.get("coupling_mode", "?")
            div = t.get("current_divergence", 0)
            state_color = COLORS['success'] if state == "synced" else (
                COLORS['warning'] if state == "diverged" else COLORS['text_muted']
            )
            self.status_text.append(
                f'<div style="padding: 2px 0; font-size: 11px;">'
                f'<span style="color: {state_color};">●</span> '
                f'<span style="color: {COLORS["text"]};">{_safe(t.get("name", t.get("twin_id", "?")))}</span> '
                f'<span style="color: {COLORS["text_dim"]};">({_safe(mode)} | div={div:.2f})</span></div>'
            )

    @pyqtSlot(dict)
    def _on_device_twin_status(self, data: dict):
        twins_data = data.get("twins", {})
        total = twins_data.get("total_twins", 0)
        if not total:
            return
        by_status = twins_data.get("by_status", {})
        by_coupling = twins_data.get("by_coupling", {})
        self.status_text.append(
            f'<div style="font-size: 13px; font-weight: 600; margin: 10px 0 6px; '
            f'color: {COLORS["accent"]};">设备数字孪生</div>'
        )
        self.status_text.append(
            f'<div style="padding: 2px 0; font-size: 11px;">'
            f'<span style="color: {COLORS["text_dim"]};">总计:</span> '
            f'<span style="color: {COLORS["text"]};">{total}</span></div>'
        )
        for status, count in by_status.items():
            color = COLORS['success'] if status == "synced" else COLORS['text_dim']
            self.status_text.append(
                f'<div style="padding: 1px 0; font-size: 10px;">'
                f'<span style="color: {color};">●</span> {_safe(status)}: {count}</div>'
            )

    @pyqtSlot(dict)
    def _on_config(self, data: dict):
        # 在加载中之后追加
        if "加载中..." in self.status_text.toPlainText():
            self.status_text.clear()

        self.status_text.append(
            f'<div style="font-size: 13px; font-weight: 600; margin-bottom: 6px; '
            f'color: {COLORS["primary"]};">系统配置状态</div>'
        )
        if data.get("error"):
            self.status_text.append(
                f'<div style="color: {COLORS["error"]}; font-size: 11px;">无法获取: {_safe(data["error"])}</div>'
            )
            return
        for key, val in data.items():
            color = COLORS['success'] if val is True else (COLORS['error'] if val is False else COLORS['text_dim'])
            self.status_text.append(
                f'<div style="padding: 2px 0; font-size: 11px;">'
                f'<span style="color: {COLORS["text_dim"]};">{_safe(key)}:</span> '
                f'<span style="color: {color};">{_safe(val)}</span></div>'
            )

    @pyqtSlot(dict)
    def _on_providers(self, data: dict):
        providers = data.get("providers", [])
        if not providers:
            return
        self.status_text.append(
            f'<div style="font-size: 13px; font-weight: 600; margin: 10px 0 6px; '
            f'color: {COLORS["secondary"]};">LLM 提供商</div>'
        )
        for p in providers:
            available = p.get("available", False)
            dot_color = COLORS['success'] if available else COLORS['text_muted']
            self.status_text.append(
                f'<div style="padding: 2px 0; font-size: 11px;">'
                f'<span style="color: {dot_color};">●</span> '
                f'<span style="color: {COLORS["text"]};">{_safe(p.get("provider", "?"))}</span> '
                f'<span style="color: {COLORS["text_dim"]};">({_safe(p.get("model", "?"))})</span></div>'
            )

    @pyqtSlot(dict)
    def _on_nodes(self, data: dict):
        nodes = data.get("nodes", [])
        if not nodes:
            return
        self.status_text.append(
            f'<div style="font-size: 13px; font-weight: 600; margin: 10px 0 6px; '
            f'color: {COLORS["accent"]};">节点状态</div>'
        )
        # 只显示前 20 个节点避免过长
        for n in nodes[:20]:
            nid = n.get("id", "?")
            name = n.get("name", "?")
            status = n.get("status", "unknown")
            dot_color = COLORS['success'] if status == "active" else COLORS['text_muted']
            self.status_text.append(
                f'<div style="padding: 1px 0; font-size: 10px;">'
                f'<span style="color: {dot_color};">●</span> '
                f'<span style="color: {COLORS["text_dim"]};">[{_safe(nid)}]</span> '
                f'<span style="color: {COLORS["text"]};">{_safe(name)}</span></div>'
            )
        if len(nodes) > 20:
            self.status_text.append(
                f'<div style="color: {COLORS["text_muted"]}; font-size: 10px;">...及 {len(nodes) - 20} 个其他节点</div>'
            )


# ════════════════════════════════════════════════════════════
# Tab 4: SettingsPanel — 连接设置
# ════════════════════════════════════════════════════════════

class SettingsPanel(QWidget):
    """连接设置面板 — API 地址、连接检测、MCP 工具状态"""

    settings_changed = pyqtSignal(str, str)  # key, value

    def __init__(self, api: APIClient, parent=None):
        super().__init__(parent)
        self.api = api
        self._workers: List[AsyncWorker] = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(12)

        # ── 后端 API 地址 ──
        api_header = QLabel("后端 API 地址")
        api_header.setStyleSheet(f"color: {COLORS['text']}; font-size: 13px; font-weight: 600;")
        layout.addWidget(api_header)

        api_row = QHBoxLayout()
        api_row.setSpacing(6)

        self.api_url_input = QLineEdit()
        self.api_url_input.setText(self.api.base_url)
        self.api_url_input.setStyleSheet(f"""
            QLineEdit {{
                background: {COLORS['bg_input']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
                padding: 10px 14px;
                color: {COLORS['text']};
                font-size: 12px;
                font-family: monospace;
            }}
            QLineEdit:focus {{ border-color: {COLORS['border_focus']}; }}
        """)
        api_row.addWidget(self.api_url_input, 1)

        btn_save = QPushButton("保存")
        btn_save.setStyleSheet(_btn_style(COLORS['primary']))
        btn_save.clicked.connect(self._save_api_url)
        api_row.addWidget(btn_save)

        layout.addLayout(api_row)

        # ── 连接状态 ──
        conn_header = QLabel("连接状态")
        conn_header.setStyleSheet(f"color: {COLORS['text']}; font-size: 13px; font-weight: 600; margin-top: 8px;")
        layout.addWidget(conn_header)

        self.conn_status = QLabel("未检测")
        self.conn_status.setStyleSheet(f"""
            QLabel {{
                background: {COLORS['bg_panel']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
                padding: 12px;
                color: {COLORS['text_dim']};
                font-size: 12px;
            }}
        """)
        layout.addWidget(self.conn_status)

        btn_test = QPushButton("测试连接")
        btn_test.setStyleSheet(_btn_style(COLORS['secondary']))
        btn_test.clicked.connect(self._test_connection)
        layout.addWidget(btn_test)

        # ── MCP 工具状态 ──
        mcp_header = QLabel("本地 MCP 工具")
        mcp_header.setStyleSheet(f"color: {COLORS['text']}; font-size: 13px; font-weight: 600; margin-top: 8px;")
        layout.addWidget(mcp_header)

        self.mcp_status = QTextEdit()
        self.mcp_status.setReadOnly(True)
        self.mcp_status.setStyleSheet(_textarea_style())
        self.mcp_status.setMaximumHeight(150)
        layout.addWidget(self.mcp_status)

        # MCP 工具列表（9 个 Windows MCP 工具）
        mcp_tools = [
            "get_screen_state", "click", "type", "scroll",
            "press_key", "screenshot", "find_element",
            "get_clipboard", "set_clipboard"
        ]
        for tool in mcp_tools:
            self.mcp_status.append(
                f'<div style="padding: 2px 0; font-size: 11px;">'
                f'<span style="color: {COLORS["text_dim"]};">●</span> '
                f'<span style="color: {COLORS["text"]};">{tool}</span></div>'
            )

        layout.addStretch()

        # ── 版本信息 ──
        version_label = QLabel("Galaxy Windows Client v2.0 - OPPO Light Field Design")
        version_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 10px;")
        version_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(version_label)

    def _save_api_url(self):
        new_url = self.api_url_input.text().strip()
        if new_url:
            self.api.base_url = new_url
            self.settings_changed.emit("api_base_url", new_url)
            self.conn_status.setText(f"已更新: {new_url}")
            self.conn_status.setStyleSheet(f"""
                QLabel {{
                    background: {COLORS['bg_panel']};
                    border: 1px solid rgba(192, 192, 192, 0.3);
                    border-radius: 10px;
                    padding: 12px;
                    color: {COLORS['success']};
                    font-size: 12px;
                }}
            """)

    def _test_connection(self):
        self.conn_status.setText("检测中...")
        self.conn_status.setStyleSheet(f"""
            QLabel {{
                background: {COLORS['bg_panel']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
                padding: 12px;
                color: {COLORS['warning']};
                font-size: 12px;
            }}
        """)

        worker = AsyncWorker(self.api.get, "/api/v1/config/status")
        worker.finished.connect(self._on_connection_test)
        self._workers.append(worker)
        worker.start()

    @pyqtSlot(dict)
    def _on_connection_test(self, data: dict):
        if data.get("error"):
            self.conn_status.setText(f"连接失败: {data['error']}")
            self.conn_status.setStyleSheet(f"""
                QLabel {{
                    background: {COLORS['bg_panel']};
                    border: 1px solid rgba(144, 144, 144, 0.3);
                    border-radius: 10px;
                    padding: 12px;
                    color: {COLORS['error']};
                    font-size: 12px;
                }}
            """)
        else:
            self.conn_status.setText(f"连接成功 - {self.api.base_url}")
            self.conn_status.setStyleSheet(f"""
                QLabel {{
                    background: {COLORS['bg_panel']};
                    border: 1px solid rgba(192, 192, 192, 0.3);
                    border-radius: 10px;
                    padding: 12px;
                    color: {COLORS['success']};
                    font-size: 12px;
                }}
            """)


# ════════════════════════════════════════════════════════════
# ABControlSurface — Audiofier 双层控制台面板
# ════════════════════════════════════════════════════════════

class ABControlSurface(QWidget):
    """Audiofier 风格 A/B 双层控制台面板.

    左半部: Layer A (红系) — Agent 控制旋钮 + LED
    右半部: Layer B (蓝系) — 设备通道旋钮 + LED
    中央:   系统状态 LED 矩阵

    该面板作为独立的可嵌入组件, 放置在 GalaxyClientUI 的 Tab 中.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._knobs: Dict[str, IndustrialKnob] = {}
        self._leds: Dict[str, LedIndicator] = {}
        self._status_leds: Dict[str, LedIndicator] = {}
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(f"""
            QWidget {{
                background: {AUDIOFIER['bg_charcoal']};
                color: {AUDIOFIER['text']};
                font-family: 'Consolas', 'JetBrains Mono', monospace;
            }}
            QLabel {{
                background: transparent;
                color: {AUDIOFIER['text_sec']};
                font-size: 10px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        # ── 标题栏 ──
        title_row = QHBoxLayout()
        title_lbl = QLabel("CONTROL SURFACE")
        title_lbl.setStyleSheet(f"""
            color: {AUDIOFIER['text']};
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 3px;
            background: transparent;
        """)
        title_row.addWidget(title_lbl)
        title_row.addStretch()

        # Master status LED
        self.master_led = LedIndicator("SYS", state="active", size=10)
        title_row.addWidget(self.master_led)
        root.addLayout(title_row)

        # ── 分隔线 ──
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {AUDIOFIER['border']};")
        root.addWidget(sep)

        # ── A/B 双层控制区 ──
        ab_row = QHBoxLayout()
        ab_row.setSpacing(8)
        ab_row.addWidget(self._build_layer("A"), 1)

        # 中央分隔
        center = QFrame()
        center.setFixedWidth(1)
        center.setStyleSheet(f"background: {AUDIOFIER['border']};")
        ab_row.addWidget(center)

        ab_row.addWidget(self._build_layer("B"), 1)
        root.addLayout(ab_row)

        # ── 底部 LED 状态矩阵 ──
        root.addWidget(self._build_led_matrix())

    def _build_layer(self, layer: str) -> QWidget:
        """Build Layer A or Layer B control section."""
        if layer == "A":
            accent      = AUDIOFIER["layer_a"]
            labels      = ["GAIN", "ROUTE", "PRIORITY", "TEMP"]
            section_lbl = "LAYER A  ·  AGENT"
        else:
            accent      = AUDIOFIER["layer_b"]
            labels      = ["LATENCY", "CHAN", "SYNC", "VOL"]
            section_lbl = "LAYER B  ·  DEVICE"

        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background: {AUDIOFIER['bg_panel']};
                border: 1px solid {accent};
                border-radius: 8px;
            }}
        """)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(6)

        # Section header
        hdr = QLabel(section_lbl)
        hdr.setStyleSheet(f"""
            color: {accent};
            font-size: 9px;
            font-weight: 700;
            letter-spacing: 2px;
            background: transparent;
        """)
        lay.addWidget(hdr)

        # Knobs row
        knob_row = QHBoxLayout()
        knob_row.setSpacing(4)
        for i, lbl in enumerate(labels):
            knob = IndustrialKnob(label=lbl, layer=layer, value=0.4 + i * 0.1)
            knob_row.addWidget(knob)
            self._knobs[f"{layer}_{lbl}"] = knob
        lay.addLayout(knob_row)

        # LED row
        led_row = QHBoxLayout()
        led_row.setSpacing(6)
        led_row.addStretch()
        for state_label, state in [("ON", "active"), ("HOLD", "warn"), ("ERR", "error")]:
            led = LedIndicator(state_label, state="idle", layer=layer, size=10)
            led_row.addWidget(led)
            self._leds[f"{layer}_{state_label}"] = led
        # Activate the ON LED for demo
        self._leds[f"{layer}_ON"].set_state("active")
        led_row.addStretch()
        lay.addLayout(led_row)

        return frame

    def _build_led_matrix(self) -> QWidget:
        """Build a small status LED matrix at the bottom."""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background: {AUDIOFIER['bg_surface']};
                border: 1px solid {AUDIOFIER['border']};
                border-radius: 6px;
            }}
        """)
        frame.setFixedHeight(36)
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(8)

        status_lbl = QLabel("STATUS")
        status_lbl.setStyleSheet(
            f"color: {AUDIOFIER['text_dim']}; font-size: 8px; letter-spacing: 2px; background: transparent;"
        )
        lay.addWidget(status_lbl)
        lay.addStretch()

        for name, state in [("CONN", "active"), ("SYNC", "active"), ("PROC", "idle"), ("ERR", "idle")]:
            led = LedIndicator(name, state=state, size=8)
            lay.addWidget(led)
            self._status_leds[name] = led

        return frame

    def update_status_led(self, name: str, state: str):
        """Update a named status LED. name: 'CONN'|'SYNC'|'PROC'|'ERR'."""
        led = self._status_leds.get(name)
        if led:
            led.set_state(state)
            led.update()

    def update_layer_led(self, layer: str, name: str, state: str):
        """Update a layer-specific LED. layer: 'A'|'B', name: 'ON'|'HOLD'|'ERR'."""
        led = self._leds.get(f"{layer}_{name}")
        if led:
            led.set_state(state)
            led.update()


# ════════════════════════════════════════════════════════════
# GalaxyClientUI — 混合模式主窗口
# ════════════════════════════════════════════════════════════

class GalaxyClientUI(QWidget):
    """混合模式主窗口 - OPPO 光场设计 · 全能智能体界面

    5 Tab: 对话 | Agent 工厂 | 设备控制 | 系统状态 | 设置
    侧边栏模式 (420px) ↔ 全窗口模式 (940x720)
    """

    command_submitted = pyqtSignal(str)

    def __init__(self, api_base: str = f"http://localhost:{get_service_port('dashboard')}", on_command: Callable = None):
        super().__init__()
        # Pre-declare stack attributes so the attribute always exists on the object.
        # If _create_ui() raises before setting these, callers will get a clear
        # "NoneType has no attribute …" error rather than an AttributeError for a
        # missing name, making the root cause easier to trace.
        self.stack: Optional[QStackedWidget] = None
        self.stacked_widget: Optional[QStackedWidget] = None  # alias kept for backward compat

        self.api = APIClient(api_base)
        self.on_command = on_command
        self.is_sidebar_mode = True
        self.is_visible = False
        self._sidebar_expanded = False  # calligraphy scroll state
        self._pending_auto_expand = False

        if on_command:
            self.command_submitted.connect(on_command)

        self._init_window()
        self._create_ui()
        self._setup_animations()

        logger.info("GalaxyClientUI 初始化完成 (全能智能体界面)")

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

        # ── Compute responsive layout sizes for this screen ────────────────
        _rs = _compute_responsive_sizes(self.screen_width, self.screen_height)
        self._resp_sidebar_w  = _rs["sidebar_w"]
        self._resp_full_w     = _rs["full_w"]
        self._resp_full_h     = _rs["full_h"]
        self._resp_font_base  = _rs["font_base"]
        self._resp_font_title = _rs["font_title"]
        self._resp_font_small = _rs["font_small"]
        self._resp_padding    = _rs["padding"]
        self._resp_spacing    = _rs["spacing"]
        self._resp_title_h    = _rs["title_h"]
        self._resp_tab_h      = _rs["tab_h"]
        logger.debug(
            "Responsive sizes: sidebar_w=%d full=%dx%d font_base=%d",
            self._resp_sidebar_w, self._resp_full_w, self._resp_full_h,
            self._resp_font_base,
        )

        # 初始位置：屏幕右侧外（collapsed width）
        self.setGeometry(
            self.screen_width, 0,
            SIDEBAR_COLLAPSED_WIDTH, self.screen_height
        )

    def _create_ui(self):
        # 根布局
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        # 光场背景
        self.bg = LightFieldBackground(self)

        # Collapsed frosted strip (visible when sidebar is collapsed)
        self._collapsed_strip = QWidget(self)
        self._collapsed_strip.setFixedWidth(SIDEBAR_COLLAPSED_WIDTH)
        self._collapsed_strip.setStyleSheet(f"""
            QWidget {{
                background: {COLORS['bg_medium']};
                border-left: 1px solid {COLORS['border']};
            }}
        """)
        self._collapsed_strip.setCursor(Qt.PointingHandCursor)
        self._collapsed_strip.mousePressEvent = lambda e: self.toggle_sidebar()

        # Collapsed strip indicator dots
        strip_layout = QVBoxLayout(self._collapsed_strip)
        strip_layout.setContentsMargins(0, 0, 0, 0)
        strip_layout.addStretch()
        for i in range(3):
            dot = QLabel("·")
            dot.setAlignment(Qt.AlignCenter)
            dot.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 16px;")
            strip_layout.addWidget(dot)
        strip_layout.addStretch()

        # 主容器 (覆盖在背景上)
        self.container = QWidget(self)
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # Content opacity effect for fade animation during expand/collapse
        self._content_opacity = QGraphicsOpacityEffect(self.container)
        self._content_opacity.setOpacity(0.0)  # start hidden (collapsed)
        self.container.setGraphicsEffect(self._content_opacity)

        # 标题栏
        self.title_bar = self._create_title_bar()
        container_layout.addWidget(self.title_bar)

        # 内容堆栈 — 5 个 Tab (must be created before tab bar so _switch_tab is safe)
        self.stack = QStackedWidget()
        self.stacked_widget = self.stack  # alias for backward compatibility
        self.chat_panel = ChatPanel(self.api)
        self.agent_panel = AgentFactoryPanel(self.api)
        self.device_panel = DevicePanel(self.api)
        self.status_panel = StatusPanel(self.api)
        self.settings_panel = SettingsPanel(self.api)
        self.control_surface = ABControlSurface()

        self.stack.addWidget(self.chat_panel)       # index 0
        self.stack.addWidget(self.agent_panel)       # index 1
        self.stack.addWidget(self.device_panel)      # index 2
        self.stack.addWidget(self.status_panel)      # index 3
        self.stack.addWidget(self.settings_panel)    # index 4
        self.stack.addWidget(self.control_surface)   # index 5
        logger.debug("QStackedWidget created with %d tabs (stack=%r)", self.stack.count(), self.stack)

        # Tab 栏 (全窗口模式才显示) — created after stack so _switch_tab(0) is safe
        self.tab_bar = self._create_tab_bar()
        self.tab_bar.setVisible(False)
        container_layout.addWidget(self.tab_bar)

        container_layout.addWidget(self.stack, 1)

        # Initialise tab selection now that both stack and tab_bar exist
        self._switch_tab(0)

    def _create_title_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(self._resp_title_h)
        bar.setStyleSheet(f"""
            QWidget {{
                background: rgba(0, 0, 0, 0.3);
                border-bottom: 1px solid {COLORS['border']};
            }}
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(self._resp_padding, 0, 12, 0)

        # 状态灯
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(f"color: {COLORS['success']}; font-size: {self._resp_font_small}px;")
        layout.addWidget(self.status_dot)

        # 标题
        title = QLabel("Galaxy")
        title.setStyleSheet(f"""
            color: {COLORS['text']};
            font-size: {self._resp_font_title}px;
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
                font-size: {self._resp_font_base}px;
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
        bar.setFixedHeight(self._resp_tab_h)
        bar.setStyleSheet(f"background: rgba(0, 0, 0, 0.15); border-bottom: 1px solid {COLORS['border']};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(self._resp_padding, 4, self._resp_padding, 4)
        layout.setSpacing(4)

        tabs = [
            ("对话", 0),
            ("Agent", 1),
            ("设备", 2),
            ("状态", 3),
            ("设置", 4),
            ("控制", 5),
        ]
        self._tab_buttons = []
        for label, idx in tabs:
            btn = QPushButton(label)
            btn.setStyleSheet(self._tab_style(False))
            btn.clicked.connect(lambda checked, i=idx: self._switch_tab(i))
            layout.addWidget(btn)
            self._tab_buttons.append(btn)

        return bar

    def _tab_style(self, active: bool) -> str:
        # _resp_font_base is always set in _init_window() before _create_tab_bar() is called.
        font_size = self._resp_font_base
        if active:
            return f"""
                QPushButton {{
                    background: rgba(255, 255, 255, 0.1);
                    border: none;
                    border-radius: 10px;
                    padding: 6px 14px;
                    color: {COLORS['text']};
                    font-size: {font_size}px;
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
                font-size: {font_size}px;
            }}
            QPushButton:hover {{ color: {COLORS['text']}; }}
        """

    def _switch_tab(self, idx: int):
        if self.stack is None:
            logger.warning("_switch_tab(%d) called before stack is initialized; skipping.", idx)
            return
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._tab_buttons):
            btn.setStyleSheet(self._tab_style(i == idx))

    def _setup_animations(self):
        # Show/hide slide animation (F12 / toggle_visibility)
        self.slide_anim = QPropertyAnimation(self, b"geometry")
        self.slide_anim.setDuration(350)
        self.slide_anim.setEasingCurve(QEasingCurve.OutQuart)

        # --- Scroll-like sidebar expand / collapse group ---
        # Both the geometry change and the opacity fade run in parallel inside
        # a single QParallelAnimationGroup (_sidebar_scroll_group).  This
        # guarantees they start and stop together, preventing the "jitter /
        # bounce-back" that occurred when the two animations were triggered
        # independently (sometimes with a QTimer delay between them).

        # Geometry: 40px ↔ 420px with OutCubic easing (卷轴式 scroll feel)
        self._sidebar_width_anim = QPropertyAnimation(self, b"geometry")
        self._sidebar_width_anim.setDuration(500)
        self._sidebar_width_anim.setEasingCurve(QEasingCurve.OutCubic)

        # Opacity: fade content in/out in sync with the geometry change
        self._content_fade_anim = QPropertyAnimation(self._content_opacity, b"opacity")
        self._content_fade_anim.setDuration(500)
        self._content_fade_anim.setEasingCurve(QEasingCurve.OutCubic)

        # Group that owns both child animations; used as the single unit to
        # start/stop and to query "is an animation in progress?" (debounce guard).
        self._sidebar_scroll_group = QParallelAnimationGroup(self)
        self._sidebar_scroll_group.addAnimation(self._sidebar_width_anim)
        self._sidebar_scroll_group.addAnimation(self._content_fade_anim)

    def _animating(self) -> bool:
        """Animation guard: return True if the sidebar scroll group OR the
        slide animation is still running.  Used to debounce rapid toggles."""
        return (
            self._sidebar_scroll_group.state() == QAbstractAnimation.Running
            or self.slide_anim.state() == QAbstractAnimation.Running
        )

    def toggle_sidebar(self):
        """卷轴式展开 / 收起侧边栏 (Calligraphy-scroll expand / collapse).

        A single QParallelAnimationGroup (_sidebar_scroll_group) drives both
        the geometry change (40 ↔ sidebar_w px) and the opacity fade together,
        so there is never a race between two independently-started animations.
        The debounce guard at the top prevents stacking new runs on top of an
        already-running group, which was the root cause of the previous
        "横跳 / bounce-back" jitter.
        """
        # Debounce guard: ignore new toggles while the scroll group is running.
        if self._animating():
            return

        # Stop any leftover animation before reconfiguring (safety net).
        self._sidebar_scroll_group.stop()

        if self._sidebar_expanded:
            # Collapse: sidebar_w → 40px, fade out content simultaneously.
            self._sidebar_expanded = False
            target_x = self.screen_width - SIDEBAR_COLLAPSED_WIDTH

            self._sidebar_width_anim.setStartValue(self.geometry())
            self._sidebar_width_anim.setEndValue(
                QRect(target_x, 0, SIDEBAR_COLLAPSED_WIDTH, self.screen_height)
            )
            self._content_fade_anim.setStartValue(self._content_opacity.opacity())
            self._content_fade_anim.setEndValue(0.0)

            # Show collapsed strip after the group finishes (500 ms).
            QTimer.singleShot(500, lambda: self._collapsed_strip.setVisible(True))
        else:
            # Expand: 40px → sidebar_w, fade in content — all in one smooth motion.
            self._sidebar_expanded = True
            self._collapsed_strip.setVisible(False)
            target_x = self.screen_width - self._resp_sidebar_w

            self._sidebar_width_anim.setStartValue(self.geometry())
            self._sidebar_width_anim.setEndValue(
                QRect(target_x, 0, self._resp_sidebar_w, self.screen_height)
            )
            self._content_fade_anim.setStartValue(self._content_opacity.opacity())
            self._content_fade_anim.setEndValue(1.0)

            # Set focus after the scroll completes.
            QTimer.singleShot(500, lambda: self.chat_panel.input_field.setFocus())

        # Start the group: geometry and opacity animate in lock-step.
        self._sidebar_scroll_group.start()

    def toggle_mode(self):
        """侧边栏 ↔ 全功能窗口"""
        # Animation guard: ignore toggle while an animation is in progress.
        if self._animating():
            return
        if self.is_sidebar_mode:
            # 展开为全窗口
            self.is_sidebar_mode = False
            self._sidebar_expanded = True
            self._collapsed_strip.setVisible(False)
            self._content_opacity.setOpacity(1.0)
            self.tab_bar.setVisible(True)
            self.toggle_btn.setText("▬")

            cx = (self.screen_width - self._resp_full_w) // 2
            cy = (self.screen_height - self._resp_full_h) // 2
            self.slide_anim.setStartValue(self.geometry())
            self.slide_anim.setEndValue(QRect(cx, cy, self._resp_full_w, self._resp_full_h))
            self.slide_anim.start()
        else:
            # 收缩为侧边栏 (expanded state)
            self.is_sidebar_mode = True
            self._sidebar_expanded = True
            self._collapsed_strip.setVisible(False)
            self.tab_bar.setVisible(False)
            self.toggle_btn.setText("⬜")
            self._switch_tab(0)

            target_x = self.screen_width - self._resp_sidebar_w
            self.slide_anim.setStartValue(self.geometry())
            self.slide_anim.setEndValue(QRect(target_x, 0, self._resp_sidebar_w, self.screen_height))
            self.slide_anim.start()

    def toggle_visibility(self):
        # Animation guard: ignore rapid F12/button presses while animation is running.
        if self._animating():
            return
        if self.is_visible:
            self.hide_sidebar()
        else:
            self.show_sidebar()

    def show_sidebar(self):
        if self.is_visible:
            return
        self.show()
        self.is_visible = True
        self._sidebar_expanded = False  # start collapsed

        if self.is_sidebar_mode:
            # Slide in as collapsed strip first (40px)
            target_x = self.screen_width - SIDEBAR_COLLAPSED_WIDTH
            self.slide_anim.setStartValue(
                QRect(self.screen_width, 0, SIDEBAR_COLLAPSED_WIDTH, self.screen_height)
            )
            self.slide_anim.setEndValue(
                QRect(target_x, 0, SIDEBAR_COLLAPSED_WIDTH, self.screen_height)
            )
            self._collapsed_strip.setVisible(True)
            self._content_opacity.setOpacity(0.0)
            # Auto-expand once the slide-in animation finishes.
            self._pending_auto_expand = True
            # Disconnect first to ensure only one connection exists
            # (Qt raises TypeError when disconnecting a non-connected signal).
            try:
                self.slide_anim.finished.disconnect(self._auto_expand_once)
            except TypeError:
                pass
            self.slide_anim.finished.connect(self._auto_expand_once)
        else:
            cx = (self.screen_width - self._resp_full_w) // 2
            cy = (self.screen_height - self._resp_full_h) // 2
            self.slide_anim.setStartValue(QRect(self.screen_width, cy, self._resp_full_w, self._resp_full_h))
            self.slide_anim.setEndValue(QRect(cx, cy, self._resp_full_w, self._resp_full_h))
            self._content_opacity.setOpacity(1.0)
            self._collapsed_strip.setVisible(False)
            self._sidebar_expanded = True

        self.slide_anim.start()
        if not self.is_sidebar_mode:
            self.chat_panel.input_field.setFocus()
        logger.info("Galaxy 客户端显示")

    def hide_sidebar(self):
        if not self.is_visible:
            return
        self.is_visible = False
        self._sidebar_expanded = False
        self._pending_auto_expand = False  # prevent stale auto-expand

        # Stop any sidebar scroll group that may still be running.
        self._sidebar_scroll_group.stop()

        target_x = self.screen_width
        current_w = self.width()
        self.slide_anim.setStartValue(self.geometry())
        if self.is_sidebar_mode:
            self.slide_anim.setEndValue(QRect(target_x, 0, current_w, self.screen_height))
        else:
            cy = (self.screen_height - self._resp_full_h) // 2
            self.slide_anim.setEndValue(QRect(target_x, cy, self._resp_full_w, self._resp_full_h))
        self.slide_anim.start()

        # Fade out content in sync with the slide-out animation.
        self._content_fade_anim.setStartValue(self._content_opacity.opacity())
        self._content_fade_anim.setEndValue(0.0)
        self._content_fade_anim.start()

        QTimer.singleShot(400, self.hide)
        logger.info("Galaxy 客户端隐藏")

    def _auto_expand_once(self):
        """Called when slide_anim finishes; auto-expands the collapsed strip to full sidebar."""
        # Disconnect immediately so this only fires once per show.
        # Qt raises TypeError when disconnecting a non-connected signal; that is expected here.
        try:
            self.slide_anim.finished.disconnect(self._auto_expand_once)
        except TypeError:
            pass
        if (
            self.is_sidebar_mode
            and self.is_visible
            and self._pending_auto_expand
            and not self._sidebar_expanded
        ):
            self._pending_auto_expand = False
            self.toggle_sidebar()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.bg.setGeometry(0, 0, self.width(), self.height())
        self.container.setGeometry(0, 0, self.width(), self.height())
        self._collapsed_strip.setGeometry(0, 0, SIDEBAR_COLLAPSED_WIDTH, self.height())

    def update_status(self, status: str, color: str = None):
        color = color or COLORS['success']
        self.status_dot.setStyleSheet(f"color: {color}; font-size: 10px;")


def main():
    """独立运行测试 — RETIRED, DO NOT RUN"""
    raise RuntimeError(
        "windows_client/_legacy/ui/galaxy_client_ui.py is a retired legacy "
        "asset and must not be executed.\n"
        "Active Windows direction:\n"
        "  core/desktop_presence_runtime.py  (DesktopPresenceRuntime tri-state shell)\n"
        "  windows_client/status_board_v2/   (projection-driven desktop status surface)\n"
        "See docs/WINDOWS_EXECUTION_PIPELINE.md for the current architecture."
    )


if __name__ == "__main__":
    main()
