"""
Windows Client 主程序

整合侧边栏 UI 和自主操纵功能
"""

import sys
import logging
import json
from typing import Dict, Any
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QThread, pyqtSignal

from ui.sidebar_ui import SidebarUI
from autonomy.autonomy_manager import WindowsAutonomyManager

logger = logging.getLogger(__name__)


class CommandProcessor(QThread):
    """命令处理线程"""
    
    # 信号
    response_ready = pyqtSignal(str)
    
    def __init__(self, autonomy_manager: WindowsAutonomyManager):
        super().__init__()
        self.autonomy_manager = autonomy_manager
        self.command = None
    
    def set_command(self, command: str):
        """设置要处理的命令"""
        self.command = command
    
    def run(self):
        """处理命令"""
        if not self.command:
            return
        
        try:
            # 解析命令
            result = self._process_command(self.command)
            
            # 发送响应
            self.response_ready.emit(result)
        except Exception as e:
            logger.error(f"处理命令失败: {e}")
            self.response_ready.emit(f"错误: {str(e)}")
    
    def _process_command(self, command: str) -> str:
        """
        处理命令
        
        Args:
            command: 用户命令
            
        Returns:
            str: 处理结果
        """
        command_lower = command.lower()
        
        # 简单的命令解析
        if "截图" in command_lower or "screenshot" in command_lower:
            return self._handle_screenshot()
        elif "剪贴板" in command_lower or "clipboard" in command_lower:
            return self._handle_clipboard()
        elif "打开" in command_lower or "open" in command_lower:
            return self._handle_open(command)
        elif "点击" in command_lower or "click" in command_lower:
            return self._handle_click(command)
        elif "输入" in command_lower or "type" in command_lower:
            return self._handle_type(command)
        elif "屏幕" in command_lower or "screen" in command_lower:
            return self._handle_screen_state()
        else:
            return f"收到命令: {command}\n\n这是一个示例响应。实际功能需要与 Galaxy Gateway 集成。"
    
    def _handle_screenshot(self) -> str:
        """处理截图命令"""
        # TODO: 实现截图功能
        return "截图功能开发中..."
    
    def _handle_clipboard(self) -> str:
        """处理剪贴板命令"""
        try:
            from PyQt5.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            text = clipboard.text()
            if text:
                return f"剪贴板内容:\n{text}"
            else:
                return "剪贴板为空"
        except Exception as e:
            return f"读取剪贴板失败: {e}"
    
    def _handle_open(self, command: str) -> str:
        """处理打开应用命令"""
        # 提取应用名称
        if "记事本" in command or "notepad" in command.lower():
            app_name = "notepad"
        elif "计算器" in command or "calculator" in command.lower():
            app_name = "calc"
        else:
            return "无法识别要打开的应用"
        
        # 执行打开操作
        task = {
            'name': f'打开 {app_name}',
            'actions': [
                {
                    'type': 'press_keys',
                    'params': {'keys': ['win', 'r']}
                },
                {
                    'type': 'type',
                    'params': {'text': app_name}
                },
                {
                    'type': 'press_key',
                    'params': {'key': 'enter'}
                }
            ]
        }
        
        result = self.autonomy_manager.execute_task(task)
        if result['success']:
            return f"成功打开 {app_name}"
        else:
            return f"打开 {app_name} 失败: {result.get('error')}"
    
    def _handle_click(self, command: str) -> str:
        """处理点击命令"""
        # TODO: 解析点击位置或元素名称
        return "点击功能需要更详细的参数"
    
    def _handle_type(self, command: str) -> str:
        """处理输入命令"""
        # 提取要输入的文本
        # 简单实现：提取 "输入" 或 "type" 后面的内容
        if "输入" in command:
            text = command.split("输入", 1)[1].strip()
        elif "type" in command.lower():
            text = command.lower().split("type", 1)[1].strip()
        else:
            return "无法识别要输入的文本"
        
        # 执行输入操作
        action = {
            'type': 'type',
            'params': {'text': text}
        }
        
        result = self.autonomy_manager.execute_action(action)
        if result['success']:
            return f"成功输入: {text}"
        else:
            return f"输入失败: {result.get('error')}"
    
    def _handle_screen_state(self) -> str:
        """处理获取屏幕状态命令"""
        state = self.autonomy_manager.get_screen_state()
        if state['success']:
            window_name = state.get('window_name', 'Unknown')
            return f"当前窗口: {window_name}\n\nUI 树已获取（详细信息省略）"
        else:
            return f"获取屏幕状态失败: {state.get('error')}"


class WindowsClient:
    """Windows Client 主类"""
    
    def __init__(self):
        """初始化 Windows Client"""
        # 初始化自主操纵管理器
        self.autonomy_manager = WindowsAutonomyManager()
        
        # 初始化命令处理器
        self.command_processor = CommandProcessor(self.autonomy_manager)
        self.command_processor.response_ready.connect(self._on_response)
        
        # 初始化 UI
        self.ui = SidebarUI(on_command=self._on_command)
        
        logger.info("Windows Client 初始化成功")
    
    def _on_command(self, command: str):
        """处理用户命令"""
        logger.info(f"收到命令: {command}")
        
        # 显示处理中状态
        self.ui.add_message("系统", "正在处理...")
        self.ui.update_status("处理中", "#ffff00")
        
        # 在后台线程中处理命令
        self.command_processor.set_command(command)
        self.command_processor.start()
    
    def _on_response(self, response: str):
        """处理响应"""
        logger.info(f"收到响应: {response[:100]}...")
        
        # 显示响应
        self.ui.add_message("系统", response)
        self.ui.update_status("在线", "#00ff00")
    
    def run(self):
        """运行 Windows Client"""
        self.ui.show_sidebar()
        logger.info("Windows Client 启动")


def main():
    """主函数"""
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        # 创建应用
        app = QApplication(sys.argv)
        
        # 创建 Windows Client
        client = WindowsClient()
        client.run()
        
        # 运行应用
        sys.exit(app.exec_())
    except Exception as e:
        logger.error(f"Windows Client 启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
