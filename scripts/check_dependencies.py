#!/usr/bin/env python3
"""
UFO Galaxy - 依赖检查工具
==========================

检查系统运行所需的 Python 包是否已安装。
区分核心依赖（必须安装）和可选依赖（缺失时优雅降级）。

用法:
    python3 scripts/check_dependencies.py
    python3 scripts/check_dependencies.py --install-core
"""

import importlib
import sys
import subprocess
import argparse

# 核心依赖：系统启动必须
CORE_DEPS = {
    "fastapi": "fastapi",
    "pydantic": "pydantic",
    "httpx": "httpx",
    "uvicorn": "uvicorn",
    "starlette": "starlette",
}

# 可选依赖：缺失时优雅降级
OPTIONAL_DEPS = {
    "cryptography": "cryptography",
    "jwt": "PyJWT",
    "redis": "redis",
    "slack_sdk": "slack_sdk",
    "aiohttp": "aiohttp",
    "qdrant_client": "qdrant-client",
    "chromadb": "chromadb",
    "neo4j": "neo4j",
    "pymongo": "pymongo",
    "anthropic": "anthropic",
    "openai": "openai",
    "google.generativeai": "google-generativeai",
    "sentence_transformers": "sentence-transformers",
    "selenium": "selenium",
    "docker": "docker",
    "paramiko": "paramiko",
    "paho.mqtt.client": "paho-mqtt",
    "edge_tts": "edge-tts",
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "pandas": "pandas",
    "sklearn": "scikit-learn",
    "networkx": "networkx",
    "matplotlib": "matplotlib",
    "yaml": "PyYAML",
    "psutil": "psutil",
    "apscheduler": "APScheduler",
    "python_multipart": "python-multipart",
}


def check_dep(module_name: str) -> bool:
    """检查模块是否可导入"""
    try:
        importlib.import_module(module_name)
        return True
    except BaseException:
        return False


def main():
    parser = argparse.ArgumentParser(description="UFO Galaxy 依赖检查工具")
    parser.add_argument("--install-core", action="store_true", help="自动安装缺失的核心依赖")
    args = parser.parse_args()

    print("=" * 60)
    print("UFO Galaxy 依赖检查报告")
    print("=" * 60)

    # 检查核心依赖
    print("\n[核心依赖] (系统启动必须)")
    core_missing = []
    for module_name, pip_name in CORE_DEPS.items():
        ok = check_dep(module_name)
        status = "✅" if ok else "❌"
        print(f"  {status} {module_name} ({pip_name})")
        if not ok:
            core_missing.append(pip_name)

    # 检查可选依赖
    print("\n[可选依赖] (缺失时优雅降级)")
    optional_missing = []
    optional_ok = 0
    for module_name, pip_name in OPTIONAL_DEPS.items():
        ok = check_dep(module_name)
        status = "✅" if ok else "⚠️"
        print(f"  {status} {module_name} ({pip_name})")
        if ok:
            optional_ok += 1
        else:
            optional_missing.append(pip_name)

    # 汇总
    print("\n" + "=" * 60)
    print("汇总:")
    print(f"  核心依赖: {len(CORE_DEPS) - len(core_missing)}/{len(CORE_DEPS)} 已安装")
    print(f"  可选依赖: {optional_ok}/{len(OPTIONAL_DEPS)} 已安装")

    if core_missing:
        print(f"\n⚠️  缺失核心依赖: {', '.join(core_missing)}")
        if args.install_core:
            print("\n正在安装核心依赖...")
            subprocess.check_call([sys.executable, "-m", "pip", "install"] + core_missing)
            print("✅ 核心依赖安装完成")
        else:
            print(f"  运行: pip install {' '.join(core_missing)}")
            print(f"  或者: python3 scripts/check_dependencies.py --install-core")

    if optional_missing:
        print(f"\n📋 缺失可选依赖 ({len(optional_missing)} 个):")
        print(f"  pip install {' '.join(optional_missing[:10])}")
        if len(optional_missing) > 10:
            print(f"  ... 及其他 {len(optional_missing) - 10} 个")

    if not core_missing:
        print("\n✅ 所有核心依赖已就绪，系统可以启动")

    return 1 if core_missing else 0


if __name__ == "__main__":
    sys.exit(main())
