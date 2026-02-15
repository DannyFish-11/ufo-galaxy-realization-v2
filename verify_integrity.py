#!/usr/bin/env python3
"""
Galaxy - 最终完整性检查
确保所有组件正确整合
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

# 颜色定义
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_header(title):
    """打印标题"""
    print(f"\n{Colors.CYAN}{'='*60}{Colors.END}")
    print(f"{Colors.CYAN}{Colors.BOLD}{title}{Colors.END}")
    print(f"{Colors.CYAN}{'='*60}{Colors.END}\n")

def check(name, condition, detail=""):
    """检查条件"""
    if condition:
        print(f"  {Colors.GREEN}✅{Colors.END} {name}")
        if detail:
            print(f"      {detail}")
        return True
    else:
        print(f"  {Colors.RED}❌{Colors.END} {name}")
        if detail:
            print(f"      {Colors.YELLOW}{detail}{Colors.END}")
        return False

def main():
    """主函数"""
    project_root = Path(__file__).parent
    os.chdir(project_root)
    
    print_header("Galaxy v2.1.6 完整性检查")
    
    results = {
        "passed": 0,
        "failed": 0,
        "total": 0,
        "timestamp": datetime.now().isoformat()
    }
    
    # 1. 核心文件
    print(f"{Colors.YELLOW}[1] 核心文件{Colors.END}")
    core_files = [
        ("main.py", "主启动入口"),
        ("start.py", "一键启动脚本"),
        ("run_galaxy.py", "运行脚本"),
        ("requirements.txt", "依赖列表"),
        (".env.example", "配置模板"),
        (".gitignore", "Git 忽略规则"),
        ("VERSION.json", "版本信息"),
        ("README.md", "说明文档"),
    ]
    
    for file, desc in core_files:
        results["total"] += 1
        if check(file, Path(file).exists(), desc):
            results["passed"] += 1
        else:
            results["failed"] += 1
    
    # 2. 核心模块
    print(f"\n{Colors.YELLOW}[2] 核心模块{Colors.END}")
    core_modules = [
        ("core/__init__.py", "核心模块初始化"),
        ("core/memory.py", "记忆系统"),
        ("core/ai_router.py", "AI 智能路由"),
        ("core/llm_router.py", "LLM 路由"),
        ("core/api_key_manager.py", "API Key 管理"),
        ("core/node_registry.py", "节点注册"),
    ]
    
    for file, desc in core_modules:
        results["total"] += 1
        if check(file, Path(file).exists(), desc):
            results["passed"] += 1
        else:
            results["failed"] += 1
    
    # 3. 服务模块
    print(f"\n{Colors.YELLOW}[3] 服务模块{Colors.END}")
    service_modules = [
        ("galaxy_gateway/__init__.py", "服务模块初始化"),
        ("galaxy_gateway/main_app.py", "主应用"),
        ("galaxy_gateway/config_service.py", "配置服务"),
        ("galaxy_gateway/memory_service.py", "记忆服务"),
        ("galaxy_gateway/router_service.py", "路由服务"),
        ("galaxy_gateway/api_keys_service.py", "API Key 服务"),
        ("galaxy_gateway/device_manager_service.py", "设备管理服务"),
    ]
    
    for file, desc in service_modules:
        results["total"] += 1
        if check(file, Path(file).exists(), desc):
            results["passed"] += 1
        else:
            results["failed"] += 1
    
    # 4. 界面文件
    print(f"\n{Colors.YELLOW}[4] 界面文件{Colors.END}")
    ui_files = [
        ("dashboard.html", "控制面板"),
        ("config.html", "配置中心"),
        ("device_manager.html", "设备管理"),
        ("memory.html", "记忆中心"),
        ("router.html", "AI 路由"),
        ("api_keys.html", "API Key 管理"),
    ]
    
    for file, desc in ui_files:
        results["total"] += 1
        path = Path(f"galaxy_gateway/static/{file}")
        if check(file, path.exists(), desc):
            results["passed"] += 1
        else:
            results["failed"] += 1
    
    # 5. Windows 支持
    print(f"\n{Colors.YELLOW}[5] Windows 支持{Colors.END}")
    windows_files = [
        ("windows/install.bat", "安装脚本"),
        ("windows/quick_start.bat", "快速启动"),
        ("windows/start_galaxy.bat", "托盘启动"),
        ("windows/galaxy_tray.py", "托盘程序"),
        ("windows/README.md", "Windows 说明"),
    ]
    
    for file, desc in windows_files:
        results["total"] += 1
        if check(file, Path(file).exists(), desc):
            results["passed"] += 1
        else:
            results["failed"] += 1
    
    # 6. 配置目录
    print(f"\n{Colors.YELLOW}[6] 配置目录{Colors.END}")
    config_dirs = [
        ("config", "配置目录"),
        ("data", "数据目录"),
        ("data/memory", "记忆数据"),
        ("data/api_keys", "API Key 数据"),
        ("logs", "日志目录"),
    ]
    
    for dir_name, desc in config_dirs:
        results["total"] += 1
        if check(dir_name, Path(dir_name).exists(), desc):
            results["passed"] += 1
        else:
            results["failed"] += 1
    
    # 7. Python 导入测试
    print(f"\n{Colors.YELLOW}[7] Python 导入测试{Colors.END}")
    sys.path.insert(0, str(project_root))
    
    import_tests = [
        ("core.memory", "MemoryManager"),
        ("core.ai_router", "AIRouter"),
        ("core.llm_router", "LLMRouter"),
        ("core.api_key_manager", "APIKeyManager"),
        ("galaxy_gateway.main_app", "app"),
    ]
    
    for module, attr in import_tests:
        results["total"] += 1
        try:
            mod = __import__(module, fromlist=[attr])
            getattr(mod, attr)
            check(f"{module}.{attr}", True)
            results["passed"] += 1
        except Exception as e:
            check(f"{module}.{attr}", False, str(e))
            results["failed"] += 1
    
    # 8. 版本信息
    print(f"\n{Colors.YELLOW}[8] 版本信息{Colors.END}")
    version_file = Path("VERSION.json")
    if version_file.exists():
        with open(version_file, 'r') as f:
            version_info = json.load(f)
        print(f"  版本: {version_info.get('version', 'unknown')}")
        print(f"  名称: {version_info.get('name', 'unknown')}")
        print(f"  核心模块: {version_info.get('components', {}).get('core_modules', 0)}")
        print(f"  服务模块: {version_info.get('components', {}).get('service_modules', 0)}")
        print(f"  界面文件: {version_info.get('components', {}).get('ui_pages', 0)}")
        print(f"  功能节点: {version_info.get('components', {}).get('nodes', 0)}")
    
    # 总结
    print_header("检查结果")
    
    pass_rate = (results["passed"] / results["total"] * 100) if results["total"] > 0 else 0
    
    print(f"  通过: {Colors.GREEN}{results['passed']}{Colors.END}")
    print(f"  失败: {Colors.RED}{results['failed']}{Colors.END}")
    print(f"  总计: {results['total']}")
    print(f"  通过率: {pass_rate:.1f}%")
    
    if results["failed"] == 0:
        print(f"\n{Colors.GREEN}{Colors.BOLD}✅ 系统完整性检查通过！{Colors.END}")
        print(f"\n启动方式:")
        print(f"  Linux/macOS: python start.py")
        print(f"  Windows:     双击 windows\\quick_start.bat")
        print(f"\n访问地址:")
        print(f"  控制面板: http://localhost:8080")
        print(f"  配置中心: http://localhost:8080/config")
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}❌ 发现 {results['failed']} 个问题{Colors.END}")
        print(f"\n请运行安装脚本修复:")
        print(f"  Linux/macOS: ./install.sh")
        print(f"  Windows:     双击 windows\\install.bat")
    
    print()
    
    return results["failed"]

if __name__ == "__main__":
    sys.exit(main())
