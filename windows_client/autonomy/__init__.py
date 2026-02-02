"""
Windows 自主操纵模块

提供 Windows 系统的 UI 自动化和输入模拟功能
"""

from .ui_automation import UIAutomationWrapper, UIElement
from .input_simulator import InputSimulator
from .autonomy_manager import WindowsAutonomyManager

__all__ = [
    'UIAutomationWrapper',
    'UIElement',
    'InputSimulator',
    'WindowsAutonomyManager'
]
