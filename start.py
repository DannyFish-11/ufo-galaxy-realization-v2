#!/usr/bin/env python3
"""
Galaxy - 一键启动脚本
=====================
最简单的启动方式，自动处理所有配置
"""

import os
import sys
import subprocess
from pathlib import Path

# 设置项目路径
PROJECT_ROOT = Path(__file__).parent.absolute()
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

def main():
    """主函数"""
    print()
    print("=" * 60)
    print("   Galaxy - L4 级自主性智能系统 v2.1.6")
    print("=" * 60)
    print()
    
    # 检查虚拟环境
    venv_path = PROJECT_ROOT / "venv"
    if not venv_path.exists():
        print("⚠️  虚拟环境不存在，正在创建...")
        subprocess.run([sys.executable, "-m", "venv", str(venv_path)])
        print("✅ 虚拟环境创建完成")
        
        # 安装依赖
        print("📦 正在安装依赖...")
        pip_path = venv_path / "bin" / "pip"
        if sys.platform == "win32":
            pip_path = venv_path / "Scripts" / "pip.exe"
        subprocess.run([str(pip_path), "install", "-r", "requirements.txt"])
        print("✅ 依赖安装完成")
    
    # 检查 .env 文件
    env_path = PROJECT_ROOT / ".env"
    env_example = PROJECT_ROOT / ".env.example"
    if not env_path.exists() and env_example.exists():
        print("📝 正在创建配置文件...")
        import shutil
        shutil.copy(env_example, env_path)
        print("✅ 配置文件已创建，请编辑 .env 填入你的 API Key")
    
    # 创建必要目录
    for dir_name in ["config", "data/memory", "data/api_keys", "logs"]:
        dir_path = PROJECT_ROOT / dir_name
        dir_path.mkdir(parents=True, exist_ok=True)
    
    print()
    print("🚀 启动 Galaxy...")
    print()
    print("访问地址:")
    print("  控制面板: http://localhost:8080")
    print("  配置中心: http://localhost:8080/config")
    print("  API 文档: http://localhost:8080/docs")
    print()
    print("按 Ctrl+C 停止")
    print()
    
    # 启动主应用
    import uvicorn
    from galaxy_gateway.main_app import app
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        log_level="info"
    )

if __name__ == "__main__":
    main()
