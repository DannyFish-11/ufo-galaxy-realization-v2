#!/usr/bin/env python3
"""
Galaxy - 系统完整性检查脚本
检查所有组件是否正确安装和配置
"""

import os
import sys
from pathlib import Path

# 颜色定义
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    END = '\033[0m'

def check(name, condition):
    """检查条件并打印结果"""
    if condition:
        print(f"  {Colors.GREEN}✅{Colors.END} {name}")
        return True
    else:
        print(f"  {Colors.RED}❌{Colors.END} {name}")
        return False

def main():
    print(f"\n{Colors.CYAN}{'='*60}{Colors.END}")
    print(f"{Colors.CYAN}Galaxy 系统完整性检查{Colors.END}")
    print(f"{Colors.CYAN}{'='*60}{Colors.END}\n")
    
    project_root = Path(__file__).parent
    os.chdir(project_root)
    
    errors = 0
    
    # 1. 核心文件
    print(f"\n{Colors.YELLOW}[1] 核心文件{Colors.END}")
    for file in ["main.py", "run_galaxy.py", "galaxy.py", "requirements.txt", ".env.example", "README.md"]:
        if not check(file, Path(file).exists()):
            errors += 1
    
    # 2. 核心模块
    print(f"\n{Colors.YELLOW}[2] 核心模块{Colors.END}")
    for file in ["core/__init__.py", "core/memory.py", "core/ai_router.py", "core/llm_router.py", "core/api_key_manager.py"]:
        if not check(file, Path(file).exists()):
            errors += 1
    
    # 3. 服务模块
    print(f"\n{Colors.YELLOW}[3] 服务模块{Colors.END}")
    for file in ["galaxy_gateway/__init__.py", "galaxy_gateway/main_app.py", "galaxy_gateway/config_service.py", "galaxy_gateway/memory_service.py", "galaxy_gateway/router_service.py", "galaxy_gateway/api_keys_service.py"]:
        if not check(file, Path(file).exists()):
            errors += 1
    
    # 4. 界面文件
    print(f"\n{Colors.YELLOW}[4] 界面文件{Colors.END}")
    for file in ["dashboard.html", "config.html", "device_manager.html", "memory.html", "router.html", "api_keys.html"]:
        if not check(file, Path(f"galaxy_gateway/static/{file}").exists()):
            errors += 1
    
    # 5. Windows 文件
    print(f"\n{Colors.YELLOW}[5] Windows 支持{Colors.END}")
    for file in ["install.bat", "quick_start.bat", "start_galaxy.bat", "galaxy_tray.py"]:
        if not check(file, Path(f"windows/{file}").exists()):
            errors += 1
    
    # 6. Python 依赖
    print(f"\n{Colors.YELLOW}[6] Python 依赖{Colors.END}")
    try:
        import fastapi
        check("fastapi", True)
    except ImportError:
        check("fastapi", False)
        errors += 1
    
    try:
        import uvicorn
        check("uvicorn", True)
    except ImportError:
        check("uvicorn", False)
        errors += 1
    
    try:
        import pydantic
        check("pydantic", True)
    except ImportError:
        check("pydantic", False)
        errors += 1
    
    # 7. 配置文件
    print(f"\n{Colors.YELLOW}[7] 配置文件{Colors.END}")
    if Path(".env").exists():
        check(".env (已配置)", True)
    else:
        check(".env (需要从 .env.example 复制)", False)
        print(f"    {Colors.YELLOW}提示: cp .env.example .env{Colors.END}")
    
    # 总结
    print(f"\n{Colors.CYAN}{'='*60}{Colors.END}")
    if errors == 0:
        print(f"{Colors.GREEN}✅ 系统完整性检查通过！{Colors.END}")
        print(f"\n启动方式:")
        print(f"  Linux/macOS: ./galaxy.sh start")
        print(f"  Windows:     双击 windows/quick_start.bat")
        print(f"\n访问地址:")
        print(f"  控制面板: http://localhost:8080")
        print(f"  配置中心: http://localhost:8080/config")
    else:
        print(f"{Colors.RED}❌ 发现 {errors} 个问题{Colors.END}")
        print(f"\n请运行安装脚本修复:")
        print(f"  Linux/macOS: ./install.sh")
        print(f"  Windows:     双击 windows/install.bat")
    print(f"{Colors.CYAN}{'='*60}{Colors.END}\n")
    
    return errors

if __name__ == "__main__":
    sys.exit(main())
