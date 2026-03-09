"""
Galaxy 主循环 — 已合并到 galaxy_main_loop_l4.py
=================================================

L4 版本是此模块的超集，包含全部功能。
保留此文件仅为向后兼容。

使用方法:
    from galaxy_main_loop_l4 import GalaxyMainLoopL4
"""

# 向后兼容：从 L4 版本导出
from galaxy_main_loop_l4 import GalaxyMainLoopL4 as GalaxyMainLoop  # noqa: F401

__all__ = ["GalaxyMainLoop"]
