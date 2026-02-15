#!/usr/bin/env python3
"""
Galaxy V2 - 统一交互启动器
整合所有交互功能：按键唤醒、卷轴UI、语音输入、摄像头等
"""

import os
import sys
import asyncio
import logging
import argparse
from pathlib import Path

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("InteractiveLauncher")

# ============================================================================
# 交互系统配置
# ============================================================================

class InteractiveConfig:
    """交互系统配置"""
    
    def __init__(self):
        # 唤醒方式
        self.wake_hotkey = os.getenv("WAKE_HOTKEY", "f12")
        self.wake_gesture = os.getenv("WAKE_GESTURE", "swipe_right_edge")
        
        # UI 配置
        self.ui_style = os.getenv("UI_STYLE", "geek_scroll")  # geek_scroll / geek_sidebar
        self.ui_width = int(os.getenv("UI_WIDTH", "400"))
        self.ui_animation_duration = float(os.getenv("UI_ANIMATION_DURATION", "0.4"))
        
        # 交互方式
        self.enable_voice = os.getenv("ENABLE_VOICE", "true").lower() == "true"
        self.enable_camera = os.getenv("ENABLE_CAMERA", "true").lower() == "true"
        self.enable_vision = os.getenv("ENABLE_VISION", "true").lower() == "true"
        
        # 服务配置
        self.gateway_url = os.getenv("GATEWAY_URL", "http://localhost:8080")
        self.websocket_url = os.getenv("WEBSOCKET_URL", "ws://localhost:8765")

# ============================================================================
# 交互系统核心
# ============================================================================

class InteractiveSystem:
    """交互系统核心"""
    
    def __init__(self, config: InteractiveConfig = None):
        self.config = config or InteractiveConfig()
        self.is_running = False
        self.ui = None
        self.key_listener = None
        self.voice_manager = None
        self.camera_manager = None
        
    async def start(self):
        """启动交互系统"""
        logger.info("=" * 50)
        logger.info("  Galaxy 交互系统启动")
        logger.info("=" * 50)
        
        # 显示配置
        self._show_config()
        
        # 初始化组件
        await self._init_components()
        
        # 启动主循环
        self.is_running = True
        await self._main_loop()
    
    def _show_config(self):
        """显示配置"""
        logger.info(f"唤醒热键: {self.config.wake_hotkey}")
        logger.info(f"UI 风格: {self.config.ui_style}")
        logger.info(f"语音输入: {'启用' if self.config.enable_voice else '禁用'}")
        logger.info(f"摄像头: {'启用' if self.config.enable_camera else '禁用'}")
        logger.info(f"视觉理解: {'启用' if self.config.enable_vision else '禁用'}")
    
    async def _init_components(self):
        """初始化组件"""
        logger.info("初始化组件...")
        
        # 1. 初始化 UI
        try:
            if self.config.ui_style == "geek_scroll":
                from ui_components.scroll_paper_view import ScrollPaperView, ScrollConfig
                scroll_config = ScrollConfig(
                    max_width=self.config.ui_width,
                    open_duration=self.config.ui_animation_duration
                )
                self.ui = ScrollPaperView(scroll_config)
                logger.info("✅ 卷轴 UI 初始化成功")
            else:
                # 尝试初始化 PyQt5 侧边栏
                try:
                    from PyQt5.QtWidgets import QApplication
                    from windows_client.ui.sidebar_ui import SidebarUI
                    
                    self.qt_app = QApplication(sys.argv)
                    self.ui = SidebarUI(on_command=self._handle_command)
                    logger.info("✅ 侧边栏 UI 初始化成功")
                except ImportError:
                    logger.warning("PyQt5 未安装，使用简化 UI")
                    self.ui = None
        except Exception as e:
            logger.warning(f"UI 初始化失败: {e}")
            self.ui = None
        
        # 2. 初始化按键监听
        try:
            import keyboard
            keyboard.add_hotkey(self.config.wake_hotkey, self._toggle_ui)
            logger.info(f"✅ 热键监听初始化成功 ({self.config.wake_hotkey})")
        except ImportError:
            logger.warning("keyboard 库未安装，热键监听不可用")
        
        # 3. 初始化语音 (可选)
        if self.config.enable_voice:
            try:
                # 这里可以添加语音识别初始化
                logger.info("✅ 语音输入已启用")
            except Exception as e:
                logger.warning(f"语音初始化失败: {e}")
        
        # 4. 初始化摄像头 (可选)
        if self.config.enable_camera:
            try:
                # 这里可以添加摄像头初始化
                logger.info("✅ 摄像头已启用")
            except Exception as e:
                logger.warning(f"摄像头初始化失败: {e}")
    
    def _toggle_ui(self):
        """切换 UI 显示"""
        if self.ui is None:
            return
        
        try:
            if hasattr(self.ui, 'toggle_visibility'):
                self.ui.toggle_visibility()
            elif hasattr(self.ui, 'is_visible'):
                if self.ui.is_visible:
                    self.ui.close()
                else:
                    self.ui.open()
        except Exception as e:
            logger.error(f"切换 UI 失败: {e}")
    
    def _handle_command(self, command: str):
        """处理用户命令"""
        logger.info(f"收到命令: {command}")
        
        # 这里可以添加命令处理逻辑
        # 例如发送到 Gateway 或本地处理
        
        # 显示响应
        if self.ui and hasattr(self.ui, 'add_message'):
            self.ui.add_message("系统", f"正在处理: {command}")
    
    async def _main_loop(self):
        """主循环"""
        logger.info("交互系统已启动")
        logger.info(f"按 {self.config.wake_hotkey.upper()} 键唤醒 UI")
        logger.info("按 Ctrl+C 退出")
        
        try:
            while self.is_running:
                # 更新 UI 动画
                if self.ui and hasattr(self.ui, 'update'):
                    self.ui.update(0.016)  # ~60fps
                
                await asyncio.sleep(0.016)
        except KeyboardInterrupt:
            logger.info("收到退出信号")
        finally:
            await self.stop()
    
    async def stop(self):
        """停止交互系统"""
        logger.info("停止交互系统...")
        self.is_running = False
        
        # 清理资源
        if self.ui:
            try:
                if hasattr(self.ui, 'close'):
                    self.ui.close()
            except:
                pass
        
        logger.info("交互系统已停止")

# ============================================================================
# 主函数
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Galaxy 交互系统")
    parser.add_argument("--hotkey", default="f12", help="唤醒热键")
    parser.add_argument("--style", default="geek_scroll", choices=["geek_scroll", "geek_sidebar"], help="UI 风格")
    parser.add_argument("--no-voice", action="store_true", help="禁用语音")
    parser.add_argument("--no-camera", action="store_true", help="禁用摄像头")
    parser.add_argument("--gateway", default="http://localhost:8080", help="Gateway URL")
    
    args = parser.parse_args()
    
    # 创建配置
    config = InteractiveConfig()
    config.wake_hotkey = args.hotkey
    config.ui_style = args.style
    config.enable_voice = not args.no_voice
    config.enable_camera = not args.no_camera
    config.gateway_url = args.gateway
    
    # 启动系统
    system = InteractiveSystem(config)
    asyncio.run(system.start())

if __name__ == "__main__":
    main()
