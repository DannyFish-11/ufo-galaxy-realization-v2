"""
Windows Client UI 模块

提供侧边栏界面和其他 UI 组件
"""

try:
    from .sidebar_ui import SidebarUI
except ImportError:
    SidebarUI = None

__all__ = ['SidebarUI']
