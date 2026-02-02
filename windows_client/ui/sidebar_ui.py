"""
Windows Client UI - 侧边栏界面

使用 Fn 键切换的右侧侧边栏界面，极简极客黑白渐变风格
"""

import sys
import logging
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QScrollArea
)
from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QPalette, QColor, QLinearGradient, QPainter, QKeySequence
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class SidebarUI(QWidget):
    """侧边栏 UI 主窗口"""
    
    # 信号
    command_submitted = pyqtSignal(str)  # 用户提交命令
    
    def __init__(self, on_command: Optional[Callable[[str], None]] = None):
        """
        初始化侧边栏 UI
        
        Args:
            on_command: 命令提交回调函数
        """
        super().__init__()
        
        self.on_command = on_command
        self.is_visible = False
        
        # 连接信号
        if on_command:
            self.command_submitted.connect(on_command)
        
        self._init_ui()
        self._setup_animations()
        self._setup_hotkey()
        
        logger.info("侧边栏 UI 初始化成功")
    
    def _init_ui(self):
        """初始化 UI"""
        # 窗口设置
        self.setWindowFlags(
            Qt.FramelessWindowHint |  # 无边框
            Qt.WindowStaysOnTopHint |  # 置顶
            Qt.Tool  # 不显示在任务栏
        )
        self.setAttribute(Qt.WA_TranslucentBackground)  # 透明背景
        
        # 获取屏幕尺寸
        screen = QApplication.primaryScreen().geometry()
        self.screen_width = screen.width()
        self.screen_height = screen.height()
        
        # 设置窗口大小和位置
        self.sidebar_width = 400
        self.setGeometry(
            self.screen_width,  # 初始位置在屏幕右侧外
            0,
            self.sidebar_width,
            self.screen_height
        )
        
        # 设置样式
        self._setup_style()
        
        # 创建布局
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 标题栏
        title_bar = self._create_title_bar()
        main_layout.addWidget(title_bar)
        
        # 内容区域
        content = self._create_content()
        main_layout.addWidget(content, 1)
        
        # 输入区域
        input_area = self._create_input_area()
        main_layout.addWidget(input_area)
        
        self.setLayout(main_layout)
    
    def _setup_style(self):
        """设置样式"""
        self.setStyleSheet("""
            QWidget {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #000000,
                    stop:0.5 #1a1a1a,
                    stop:1 #000000
                );
                color: #ffffff;
                font-family: 'Consolas', 'Monaco', monospace;
            }
            
            QLineEdit, QTextEdit {
                background-color: #0a0a0a;
                border: 1px solid #333333;
                border-radius: 5px;
                padding: 8px;
                color: #ffffff;
                selection-background-color: #ffffff;
                selection-color: #000000;
            }
            
            QLineEdit:focus, QTextEdit:focus {
                border: 1px solid #ffffff;
            }
            
            QPushButton {
                background-color: #1a1a1a;
                border: 1px solid #333333;
                border-radius: 5px;
                padding: 8px 16px;
                color: #ffffff;
            }
            
            QPushButton:hover {
                background-color: #2a2a2a;
                border: 1px solid #ffffff;
            }
            
            QPushButton:pressed {
                background-color: #ffffff;
                color: #000000;
            }
            
            QScrollBar:vertical {
                background: #0a0a0a;
                width: 10px;
                border-radius: 5px;
            }
            
            QScrollBar::handle:vertical {
                background: #333333;
                border-radius: 5px;
            }
            
            QScrollBar::handle:vertical:hover {
                background: #ffffff;
            }
            
            QLabel {
                color: #ffffff;
            }
        """)
    
    def _create_title_bar(self) -> QWidget:
        """创建标题栏"""
        title_bar = QWidget()
        title_bar.setFixedHeight(50)
        title_bar.setStyleSheet("""
            QWidget {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #000000,
                    stop:1 #1a1a1a
                );
                border-bottom: 1px solid #333333;
            }
        """)
        
        layout = QHBoxLayout()
        layout.setContentsMargins(15, 0, 15, 0)
        
        # 标题
        title_label = QLabel("UFO³ Galaxy")
        title_font = QFont("Consolas", 14, QFont.Bold)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        
        layout.addStretch()
        
        # 状态指示器
        self.status_label = QLabel("● 在线")
        self.status_label.setStyleSheet("color: #00ff00;")
        layout.addWidget(self.status_label)
        
        # 关闭按钮
        close_btn = QPushButton("×")
        close_btn.setFixedSize(30, 30)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                color: #ffffff;
                font-size: 20px;
            }
            QPushButton:hover {
                background-color: #ff0000;
            }
        """)
        close_btn.clicked.connect(self.toggle_visibility)
        layout.addWidget(close_btn)
        
        title_bar.setLayout(layout)
        return title_bar
    
    def _create_content(self) -> QWidget:
        """创建内容区域"""
        content = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # 对话历史
        history_label = QLabel("对话历史")
        history_label.setFont(QFont("Consolas", 10, QFont.Bold))
        layout.addWidget(history_label)
        
        self.history_text = QTextEdit()
        self.history_text.setReadOnly(True)
        self.history_text.setPlaceholderText("对话历史将显示在这里...")
        layout.addWidget(self.history_text, 1)
        
        # 快捷操作
        shortcuts_label = QLabel("快捷操作")
        shortcuts_label.setFont(QFont("Consolas", 10, QFont.Bold))
        layout.addWidget(shortcuts_label)
        
        shortcuts_layout = QHBoxLayout()
        
        btn_screenshot = QPushButton("📸 截图")
        btn_screenshot.clicked.connect(lambda: self._quick_action("截图"))
        shortcuts_layout.addWidget(btn_screenshot)
        
        btn_clipboard = QPushButton("📋 剪贴板")
        btn_clipboard.clicked.connect(lambda: self._quick_action("查看剪贴板"))
        shortcuts_layout.addWidget(btn_clipboard)
        
        btn_tasks = QPushButton("📝 任务")
        btn_tasks.clicked.connect(lambda: self._quick_action("查看任务列表"))
        shortcuts_layout.addWidget(btn_tasks)
        
        layout.addLayout(shortcuts_layout)
        
        content.setLayout(layout)
        return content
    
    def _create_input_area(self) -> QWidget:
        """创建输入区域"""
        input_area = QWidget()
        input_area.setFixedHeight(100)
        input_area.setStyleSheet("""
            QWidget {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1a1a1a,
                    stop:1 #000000
                );
                border-top: 1px solid #333333;
            }
        """)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(10)
        
        # 输入框
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入命令或问题... (Enter 发送)")
        self.input_field.returnPressed.connect(self._submit_command)
        layout.addWidget(self.input_field)
        
        # 按钮行
        button_layout = QHBoxLayout()
        
        btn_voice = QPushButton("🎤 语音")
        btn_voice.clicked.connect(self._start_voice_input)
        button_layout.addWidget(btn_voice)
        
        button_layout.addStretch()
        
        btn_send = QPushButton("发送")
        btn_send.clicked.connect(self._submit_command)
        button_layout.addWidget(btn_send)
        
        layout.addLayout(button_layout)
        
        input_area.setLayout(layout)
        return input_area
    
    def _setup_animations(self):
        """设置动画"""
        self.slide_animation = QPropertyAnimation(self, b"geometry")
        self.slide_animation.setDuration(300)
        self.slide_animation.setEasingCurve(QEasingCurve.OutCubic)
    
    def _setup_hotkey(self):
        """设置全局热键（Fn 键）"""
        # 注意：PyQt5 不直接支持 Fn 键，这里使用 F12 作为替代
        # 在实际部署时，可以使用 pynput 或 keyboard 库来监听 Fn 键
        from PyQt5.QtWidgets import QShortcut
        
        shortcut = QShortcut(QKeySequence("F12"), self)
        shortcut.activated.connect(self.toggle_visibility)
        
        logger.info("热键设置完成: F12 (Fn 键的替代)")
    
    def toggle_visibility(self):
        """切换可见性"""
        if self.is_visible:
            self.hide_sidebar()
        else:
            self.show_sidebar()
    
    def show_sidebar(self):
        """显示侧边栏"""
        if self.is_visible:
            return
        
        self.show()
        self.is_visible = True
        
        # 滑入动画
        self.slide_animation.setStartValue(
            self.geometry()
        )
        self.slide_animation.setEndValue(
            self.geometry().adjusted(-self.sidebar_width, 0, 0, 0)
        )
        self.slide_animation.start()
        
        # 聚焦输入框
        self.input_field.setFocus()
        
        logger.info("侧边栏显示")
    
    def hide_sidebar(self):
        """隐藏侧边栏"""
        if not self.is_visible:
            return
        
        self.is_visible = False
        
        # 滑出动画
        self.slide_animation.setStartValue(
            self.geometry()
        )
        self.slide_animation.setEndValue(
            self.geometry().adjusted(self.sidebar_width, 0, 0, 0)
        )
        self.slide_animation.start()
        
        # 动画结束后隐藏窗口
        QTimer.singleShot(300, self.hide)
        
        logger.info("侧边栏隐藏")
    
    def _submit_command(self):
        """提交命令"""
        command = self.input_field.text().strip()
        if not command:
            return
        
        # 添加到历史
        self.add_message("用户", command)
        
        # 清空输入框
        self.input_field.clear()
        
        # 发送信号
        self.command_submitted.emit(command)
        
        logger.info(f"提交命令: {command}")
    
    def _quick_action(self, action: str):
        """快捷操作"""
        self.command_submitted.emit(action)
        logger.info(f"快捷操作: {action}")
    
    def _start_voice_input(self):
        """开始语音输入"""
        self.add_message("系统", "语音输入功能开发中...")
        logger.info("语音输入功能待实现")
    
    def add_message(self, sender: str, message: str):
        """添加消息到历史"""
        timestamp = QTimer().currentTime().toString("hh:mm:ss")
        formatted_message = f"[{timestamp}] {sender}: {message}\n"
        self.history_text.append(formatted_message)
        
        # 滚动到底部
        scrollbar = self.history_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def update_status(self, status: str, color: str = "#00ff00"):
        """更新状态"""
        self.status_label.setText(f"● {status}")
        self.status_label.setStyleSheet(f"color: {color};")


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
