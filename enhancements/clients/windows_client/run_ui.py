#!/usr/bin/env python3
"""
Galaxy 主 UI 启动器
==================

F12 唤醒的对话界面

启动: python run_ui.py

版本: v2.3.27
"""

import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

def main():
    print("=" * 50)
    print("Galaxy 主 UI")
    print("=" * 50)
    print()
    print("F12 - 唤醒/隐藏对话面板")
    print("ESC - 隐藏面板")
    print()
    print("提示: 先启动 Dashboard")
    print("  python main.py")
    print()
    print("=" * 50)
    
    # 检查依赖
    try:
        import keyboard
    except ImportError:
        print("安装依赖: pip install keyboard httpx")
        import subprocess
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'keyboard', 'httpx'], check=True)
    
    from galaxy_client import GalaxyChatUI
    
    server_url = os.environ.get('GALAXY_SERVER', 'http://localhost:8080')
    app = GalaxyChatUI(server_url=server_url)
    app.run()

if __name__ == "__main__":
    main()
