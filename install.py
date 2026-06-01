#!/usr/bin/env python3
"""
Galaxy 一键安装脚本
===================
自动检测平台，安装所需依赖，确保启动时依赖都在位。

用法:
    python install.py              # 只装核心
    python install.py --all        # 核心 + 增强 + Windows
    python install.py --core       # 只装核心
    python install.py --enhance    # 核心 + 增强
"""

import argparse
import platform
import subprocess
import sys
from pathlib import Path


def run(cmd: list, desc: str) -> bool:
    """执行命令，返回是否成功。"""
    print(f"  → {desc}...", end=" ", flush=True)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            print("✓")
            return True
        else:
            print(f"✗\n    {result.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print("✗ (超时)")
        return False
    except FileNotFoundError:
        print("✗ (pip 未找到)")
        return False


def install_file(req_file: str, desc: str) -> bool:
    """安装指定的 requirements 文件。"""
    if not Path(req_file).exists():
        print(f"  跳过: {req_file} 不存在")
        return True  # 不阻塞
    return run(
        [sys.executable, "-m", "pip", "install", "-r", req_file, "--quiet"],
        desc,
    )


def main():
    parser = argparse.ArgumentParser(description="Galaxy 依赖安装")
    parser.add_argument("--all", action="store_true", help="安装所有依赖")
    parser.add_argument("--core", action="store_true", help="只安装核心")
    parser.add_argument("--enhance", action="store_true", help="核心+增强")
    args = parser.parse_args()

    is_win = platform.system() == "Windows"

    print("=" * 60)
    print("  Galaxy 依赖安装")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  平台: {platform.system()} {platform.machine()}")
    print("=" * 60)

    # 默认只装核心
    install_core = True
    install_enhance = args.all or args.enhance
    install_windows = args.all and is_win

    if args.core:
        install_enhance = False
        install_windows = False

    results = []

    # 1. 升级 pip
    print("\n[1/4] 升级 pip...")
    results.append(run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "pip", "--quiet"],
        "升级 pip",
    ))

    # 2. 核心依赖
    print("\n[2/4] 安装核心依赖...")
    results.append(install_file("requirements-core.txt", "核心依赖"))

    # 3. 增强依赖
    if install_enhance:
        print("\n[3/4] 安装增强依赖...")
        results.append(install_file("requirements-enhance.txt", "增强依赖"))
    else:
        print("\n[3/4] 增强依赖: 跳过 (--enhance 或 --all 启用)")

    # 4. Windows 依赖
    if install_windows:
        print("\n[4/4] 安装 Windows 依赖...")
        results.append(install_file("requirements-windows.txt", "Windows 依赖"))
    else:
        if is_win and not args.all:
            print("\n[4/4] Windows 依赖: 跳过 (--all 启用)")
        elif not is_win:
            print("\n[4/4] Windows 依赖: 非 Windows 平台，跳过")

    # 总结
    print("\n" + "=" * 60)
    if all(results):
        print("  ✓ 全部安装成功")
        print("\n  启动命令:")
        print("    $env:GALAXY_API_TOKEN=\"your_token\"")
        print("    python main.py")
    else:
        print("  ⚠ 部分安装失败，但核心应该可用")
        print("  如需完整功能，运行: python install.py --all")
    print("=" * 60)


if __name__ == "__main__":
    main()
