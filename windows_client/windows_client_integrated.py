"""
UFO Galaxy Windows客户端 - UI与L4集成版
极简主义设计风格，集成L4主循环
"""

import sys
import asyncio
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

# PyQt6 导入
try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QTextEdit, QLineEdit, QPushButton, QLabel, QProgressBar,
        QListWidget, QListWidgetItem, QFrame, QScrollArea, QSplitter
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
    from PyQt6.QtGui import QFont, QColor, QPalette, QIcon
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False
    logging.warning("PyQt6 不可用，Windows客户端将无法运行")

# 导入L4主循环
sys.path.insert(0, '/mnt/okcomputer/output/ufo_galaxy_integration')
from core.galaxy_main_loop_l4_enhanced import get_galaxy_loop, GalaxyMainLoopL4Enhanced
from integration.event_bus import (
    EventBus, EventType, UIGalaxyEvent, 
    event_bus, ui_progress_callback
)


# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WindowsClient")


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    DECOMPOSING = "decomposing"
    PLANNING = "planning"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class UITask:
    """UI任务数据类"""
    task_id: str
    description: str
    status: TaskStatus
    subtasks: List[Dict] = None
    actions: List[Dict] = None
    progress: float = 0.0
    created_at: datetime = None
    
    def __post_init__(self):
        if self.subtasks is None:
            self.subtasks = []
        if self.actions is None:
            self.actions = []
        if self.created_at is None:
            self.created_at = datetime.now()


class L4WorkerThread(QThread):
    """
    L4主循环工作线程
    在后台运行L4主循环
    """
    status_update = pyqtSignal(dict)
    task_completed = pyqtSignal(str, bool, dict)
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__()
        self.config = config or {}
        self.loop: Optional[GalaxyMainLoopL4Enhanced] = None
        self._running = False
    
    def run(self):
        """运行L4主循环"""
        self._running = True
        
        try:
            # 创建新的事件循环
            asyncio.set_event_loop(asyncio.new_event_loop())
            
            # 获取L4主循环实例
            self.loop = get_galaxy_loop(self.config)
            
            # 启动L4主循环
            asyncio.get_event_loop().run_until_complete(self.loop.start())
            
        except Exception as e:
            logger.error(f"L4工作线程错误: {e}")
    
    def submit_goal(self, goal_description: str) -> str:
        """提交目标到L4主循环"""
        if self.loop:
            return self.loop.receive_goal(goal_description)
        return ""
    
    def get_status(self) -> Dict[str, Any]:
        """获取L4状态"""
        if self.loop:
            return self.loop.get_status()
        return {"running": False}
    
    def stop(self):
        """停止L4主循环"""
        if self.loop:
            asyncio.create_task(self.loop.stop())
        self._running = False


class MinimalistWindow(QMainWindow):
    """
    UFO Galaxy Windows客户端主窗口
    极简主义设计风格
    """
    
    def __init__(self):
        super().__init__()
        
        self.tasks: Dict[str, UITask] = {}
        self.l4_thread: Optional[L4WorkerThread] = None
        
        # 设置窗口
        self.setWindowTitle("UFO Galaxy - AI Assistant")
        self.setMinimumSize(900, 700)
        
        # 设置深色主题
        self._setup_dark_theme()
        
        # 初始化UI
        self._init_ui()
        
        # 启动L4工作线程
        self._start_l4_thread()
        
        # 订阅事件
        self._subscribe_events()
        
        # 设置定时器更新状态
        self._setup_status_timer()
    
    def _setup_dark_theme(self):
        """设置深色主题"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1a1a2e;
            }
            QWidget {
                background-color: #1a1a2e;
                color: #eee;
                font-family: 'Segoe UI', Arial;
            }
            QLineEdit {
                background-color: #16213e;
                border: 2px solid #0f3460;
                border-radius: 20px;
                padding: 12px 20px;
                color: #fff;
                font-size: 14px;
            }
            QLineEdit:focus {
                border-color: #e94560;
            }
            QPushButton {
                background-color: #e94560;
                border: none;
                border-radius: 20px;
                padding: 12px 24px;
                color: #fff;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ff6b6b;
            }
            QPushButton:pressed {
                background-color: #c73e54;
            }
            QTextEdit {
                background-color: #16213e;
                border: 1px solid #0f3460;
                border-radius: 10px;
                padding: 10px;
                color: #ddd;
            }
            QListWidget {
                background-color: #16213e;
                border: 1px solid #0f3460;
                border-radius: 10px;
            }
            QListWidget::item {
                padding: 10px;
                border-bottom: 1px solid #0f3460;
            }
            QListWidget::item:selected {
                background-color: #0f3460;
            }
            QProgressBar {
                border: none;
                border-radius: 5px;
                background-color: #16213e;
                height: 8px;
            }
            QProgressBar::chunk {
                background-color: #e94560;
                border-radius: 5px;
            }
            QLabel {
                color: #aaa;
            }
            QLabel#title {
                color: #fff;
                font-size: 24px;
                font-weight: bold;
            }
            QLabel#status {
                color: #4ecca3;
                font-size: 12px;
            }
        """)
    
    def _init_ui(self):
        """初始化UI组件"""
        # 中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(20)
        
        # 标题
        title_label = QLabel("UFO Galaxy")
        title_label.setObjectName("title")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)
        
        # 状态标签
        self.status_label = QLabel("● 系统就绪")
        self.status_label.setObjectName("status")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.status_label)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #0f3460;")
        line.setFixedHeight(1)
        main_layout.addWidget(line)
        
        # 分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧：任务列表
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        tasks_header = QLabel("任务列表")
        tasks_header.setStyleSheet("font-size: 16px; font-weight: bold; color: #fff;")
        left_layout.addWidget(tasks_header)
        
        self.tasks_list = QListWidget()
        self.tasks_list.itemClicked.connect(self._on_task_selected)
        left_layout.addWidget(self.tasks_list)
        
        splitter.addWidget(left_panel)
        
        # 右侧：任务详情和输出
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # 任务详情
        details_header = QLabel("任务详情")
        details_header.setStyleSheet("font-size: 16px; font-weight: bold; color: #fff;")
        right_layout.addWidget(details_header)
        
        self.task_details = QTextEdit()
        self.task_details.setReadOnly(True)
        self.task_details.setMaximumHeight(150)
        right_layout.addWidget(self.task_details)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        right_layout.addWidget(self.progress_bar)
        
        # 输出日志
        output_header = QLabel("执行日志")
        output_header.setStyleSheet("font-size: 16px; font-weight: bold; color: #fff;")
        right_layout.addWidget(output_header)
        
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        right_layout.addWidget(self.output_text)
        
        splitter.addWidget(right_panel)
        splitter.setSizes([300, 600])
        
        main_layout.addWidget(splitter)
        
        # 输入区域
        input_layout = QHBoxLayout()
        
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入指令或问题...")
        self.input_field.returnPressed.connect(self._on_command_submitted)
        input_layout.addWidget(self.input_field)
        
        self.send_button = QPushButton("发送")
        self.send_button.clicked.connect(self._on_command_submitted)
        input_layout.addWidget(self.send_button)
        
        main_layout.addLayout(input_layout)
        
        # 底部按钮
        button_layout = QHBoxLayout()
        
        self.clear_button = QPushButton("清空")
        self.clear_button.clicked.connect(self._clear_output)
        button_layout.addWidget(self.clear_button)
        
        button_layout.addStretch()
        
        self.status_button = QPushButton("查看状态")
        self.status_button.clicked.connect(self._show_status)
        button_layout.addWidget(self.status_button)
        
        main_layout.addLayout(button_layout)
    
    def _start_l4_thread(self):
        """启动L4工作线程"""
        config = {
            "cycle_interval": 2.0,
            "auto_scan_interval": 300.0
        }
        
        self.l4_thread = L4WorkerThread(config)
        self.l4_thread.start()
        
        logger.info("L4工作线程已启动")
        self._append_output("系统初始化完成，L4自主性智能已就绪\n")
    
    def _subscribe_events(self):
        """订阅事件总线事件"""
        # 使用Qt的信号槽机制需要在主线程中处理
        # 这里我们使用定时器轮询事件历史
        pass
    
    def _setup_status_timer(self):
        """设置状态更新定时器"""
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(1000)  # 每秒更新一次
    
    def _update_status(self):
        """更新状态显示"""
        if self.l4_thread:
            status = self.l4_thread.get_status()
            
            if status.get("running"):
                state = status.get("state", "IDLE")
                cycle_count = status.get("cycle_count", 0)
                self.status_label.setText(f"● 运行中 | 状态: {state} | 周期: {cycle_count}")
            else:
                self.status_label.setText("● 已停止")
    
    def _on_command_submitted(self):
        """
        命令提交回调（UI → L4 集成点）
        当用户输入命令并提交时调用
        """
        command = self.input_field.text().strip()
        if not command:
            return
        
        # 清空输入框
        self.input_field.clear()
        
        # 显示用户输入
        self._append_output(f"> {command}\n")
        
        # 解析用户意图
        intent = self._parse_user_intent(command)
        
        # 提交到L4主循环
        if self.l4_thread:
            goal_id = self.l4_thread.submit_goal(command)
            
            # 创建UI任务
            task = UITask(
                task_id=goal_id,
                description=command,
                status=TaskStatus.PENDING
            )
            self.tasks[goal_id] = task
            
            # 更新任务列表
            self._update_tasks_list()
            
            self._append_output(f"[系统] 目标已提交 [{goal_id[:8]}...]\n")
            logger.info(f"用户提交命令: {command}, 目标ID: {goal_id}")
        else:
            self._append_output("[错误] L4主循环未启动\n")
    
    def _parse_user_intent(self, command: str) -> Dict[str, Any]:
        """
        解析用户意图
        
        Args:
            command: 用户输入的命令
            
        Returns:
            解析后的意图字典
        """
        intent = {
            "raw_command": command,
            "intent_type": "unknown",
            "entities": [],
            "confidence": 0.0
        }
        
        # 简单的意图识别规则
        command_lower = command.lower()
        
        if any(word in command_lower for word in ["搜索", "查找", "search", "find"]):
            intent["intent_type"] = "search"
            intent["confidence"] = 0.8
        elif any(word in command_lower for word in ["打开", "启动", "open", "start"]):
            intent["intent_type"] = "open_application"
            intent["confidence"] = 0.8
        elif any(word in command_lower for word in ["创建", "新建", "create", "new"]):
            intent["intent_type"] = "create"
            intent["confidence"] = 0.7
        elif any(word in command_lower for word in ["删除", "移除", "delete", "remove"]):
            intent["intent_type"] = "delete"
            intent["confidence"] = 0.7
        elif any(word in command_lower for word in ["查询", "询问", "query", "ask"]):
            intent["intent_type"] = "query"
            intent["confidence"] = 0.75
        else:
            intent["intent_type"] = "general_task"
            intent["confidence"] = 0.5
        
        # 提取实体（简化实现）
        words = command.split()
        intent["entities"] = words[1:] if len(words) > 1 else []
        
        return intent
    
    def _on_task_selected(self, item: QListWidgetItem):
        """任务选择回调"""
        task_id = item.data(Qt.ItemDataRole.UserRole)
        if task_id and task_id in self.tasks:
            task = self.tasks[task_id]
            self._show_task_details(task)
    
    def _show_task_details(self, task: UITask):
        """显示任务详情"""
        details = f"""
任务ID: {task.task_id[:16]}...
描述: {task.description}
状态: {task.status.value}
进度: {task.progress * 100:.1f}%
创建时间: {task.created_at.strftime('%Y-%m-%d %H:%M:%S')}

子任务数: {len(task.subtasks)}
动作数: {len(task.actions)}
"""
        self.task_details.setText(details)
        
        # 更新进度条
        self.progress_bar.setValue(int(task.progress * 100))
        self.progress_bar.setVisible(task.status == TaskStatus.EXECUTING)
    
    def _update_tasks_list(self):
        """更新任务列表显示"""
        self.tasks_list.clear()
        
        for task_id, task in self.tasks.items():
            item = QListWidgetItem()
            
            # 状态图标
            status_icon = {
                TaskStatus.PENDING: "⏳",
                TaskStatus.DECOMPOSING: "🔍",
                TaskStatus.PLANNING: "📋",
                TaskStatus.EXECUTING: "⚙️",
                TaskStatus.COMPLETED: "✅",
                TaskStatus.ERROR: "❌"
            }.get(task.status, "❓")
            
            item.setText(f"{status_icon} {task.description[:40]}...")
            item.setData(Qt.ItemDataRole.UserRole, task_id)
            
            self.tasks_list.addItem(item)
    
    def _append_output(self, text: str):
        """追加输出文本"""
        self.output_text.append(text)
        # 滚动到底部
        scrollbar = self.output_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _clear_output(self):
        """清空输出"""
        self.output_text.clear()
    
    def _show_status(self):
        """显示系统状态"""
        if self.l4_thread:
            status = self.l4_thread.get_status()
            status_text = f"""
系统状态:
- 运行状态: {'运行中' if status.get('running') else '已停止'}
- 当前状态: {status.get('state', 'Unknown')}
- 周期计数: {status.get('cycle_count', 0)}
- 任务历史: {status.get('task_history_count', 0)}
- 待处理目标: {status.get('pending_goals_count', 0)}
- 当前目标: {status.get('current_goal', 'None')}
"""
            self._append_output(status_text)
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        # 停止L4工作线程
        if self.l4_thread:
            self.l4_thread.stop()
            self.l4_thread.wait(5000)
        
        event.accept()


def main():
    """Windows客户端主入口"""
    if not PYQT_AVAILABLE:
        print("错误: PyQt6 未安装，无法启动Windows客户端")
        print("请运行: pip install PyQt6")
        return
    
    app = QApplication(sys.argv)
    
    # 设置应用级字体
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    
    # 创建主窗口
    window = MinimalistWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
