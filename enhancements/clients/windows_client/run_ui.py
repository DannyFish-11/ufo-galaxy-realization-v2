#!/usr/bin/env python3
"""
Galaxy Windows 客户端启动器
==========================

启动方式:
    python run_ui.py          # 默认：书法卷轴式 UI
    python run_ui.py --minimal # 极简风格 UI

功能:
    - F12 唤醒/隐藏
    - 书法卷轴式展开动画
    - 与 AI 智能体对话
    - UI 自动化控制

版本: v2.3.28
"""

import sys
import os
import argparse

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

def check_dependencies():
    """检查依赖"""
    required = ['keyboard', 'httpx']
    missing = []
    
    for pkg in required:
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
    parser = argparse.ArgumentParser(description='Galaxy Windows 客户端')
    parser.add_argument('--minimal', action='store_true', help='使用极简风格 UI')
    parser.add_argument('--server', type=str, default='http://localhost:8080', help='服务器地址')
    args = parser.parse_args()
    
    print("=" * 60)
    print("Galaxy Windows 客户端 v2.3.28")
    print("=" * 60)
    print()
    print("使用方式:")
    print("  F12 - 唤醒/隐藏面板")
    print("  ESC - 隐藏面板")
    print()
    print("功能:")
    print("  • 对话 - 与 AI 智能体交流")
    print("  • Agent - 智能体状态")
    print("  • 自动化 - UI 自动化控制")
    print()
    print("=" * 60)
    
    check_dependencies()
    
    # 从环境变量获取服务器地址
    server_url = os.environ.get('GALAXY_SERVER', args.server)
    
    if args.minimal:
        # 极简风格 UI
        from client_ui_minimalist import MinimalistSidePanel
        app = MinimalistSidePanel(server_url=server_url.replace('http://', 'ws://') + '/ws')
    else:
        # 书法卷轴式 UI (默认)
        from scroll_paper_geek_ui import ScrollPaperGeekUI
        app = ScrollPaperGeekUI(server_url=server_url)
    
    app.run()

if __name__ == "__main__":
    main()
