#!/usr/bin/env python3
"""
UFO³ Galaxy Windows 客户端启动器
================================

启动方式:
    python run_ui.py

功能:
    - F12 唤醒/隐藏
    - 书法卷轴式展开动画
    - 极客风格 UI

版本: v2.3.19
"""

import sys
import os

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

def check_dependencies():
    """检查依赖"""
    required = ['tkinter', 'keyboard', 'websockets']
    missing = []
    
    for pkg in required:
        if pkg == 'tkinter':
            try:
                import tkinter
            except ImportError:
                missing.append(pkg)
        else:
            try:
                __import__(pkg)
            except ImportError:
                missing.append(pkg)
    
    if missing:
        print(f"缺少依赖: {missing}")
        print("正在安装...")
        import subprocess
        subprocess.run([sys.executable, '-m', 'pip', 'install'] + missing, check=True)

def main():
    """主函数"""
    print("=" * 60)
    print("UFO³ Galaxy Windows 客户端")
    print("=" * 60)
    print()
    print("使用方式:")
    print("  F12 - 唤醒/隐藏面板")
    print("  ESC - 隐藏面板")
    print()
    print("功能:")
    print("  - 对话: 与 AI 智能体对话")
    print("  - 节点: 查看节点状态")
    print("  - 设备: 管理连接设备")
    print("  - Agent: 查看 Agent 状态")
    print()
    print("=" * 60)
    
    check_dependencies()
    
    from scroll_paper_geek_ui import ScrollPaperGeekUI
    
    # 从环境变量获取服务器地址
    server_url = os.environ.get('GALAXY_SERVER', 'ws://localhost:8080/ws')
    
    app = ScrollPaperGeekUI(server_url=server_url)
    app.run()

if __name__ == "__main__":
    main()
