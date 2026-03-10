#!/usr/bin/env python3
"""
Galaxy Windows 客户端启动器（兼容入口）
======================================

此文件已废弃旧版 tkinter UI，统一委托到新版 OPPO 光场 (Light Field) 客户端。

正确入口:
    python windows_client/main.py

此文件仅作为旧路径的兼容跳转。

版本: v3.0.0
"""

import sys
import os

# 添加项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, PROJECT_ROOT)


def main():
    """委托到新版 windows_client/main.py"""
    print("=" * 60)
    print("Galaxy Windows 客户端")
    print("=" * 60)
    print()
    print("已迁移到新版 OPPO 光场 (Light Field) UI")
    print("正在启动 windows_client/main.py ...")
    print()

    try:
        from windows_client.main import main as new_main
        new_main()
    except ImportError as e:
        print(f"无法导入新版客户端: {e}")
        print()
        print("请从项目根目录运行:")
        print("  python windows_client/main.py")
        sys.exit(1)


if __name__ == "__main__":
    main()
