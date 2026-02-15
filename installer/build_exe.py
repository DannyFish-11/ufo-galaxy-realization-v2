#!/usr/bin/env python3
"""
UFO Galaxy - Windows EXE 打包脚本
使用 PyInstaller 将项目打包为可执行文件
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
BUILD_DIR = PROJECT_ROOT / "build"
DIST_DIR = PROJECT_ROOT / "dist"
INSTALLER_DIR = PROJECT_ROOT / "installer"

# 打包配置
APP_NAME = "UFO_Galaxy"
APP_VERSION = "1.0.0"
APP_ICON = INSTALLER_DIR / "icon.ico"

def check_dependencies():
    """检查打包依赖"""
    print("[1/5] 检查打包依赖...")
    
    try:
        import PyInstaller
        print(f"  ✓ PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("  ✗ PyInstaller 未安装，正在安装...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
        print("  ✓ PyInstaller 已安装")

def clean_build():
    """清理构建目录"""
    print("[2/5] 清理构建目录...")
    
    for dir_path in [BUILD_DIR, DIST_DIR]:
        if dir_path.exists():
            shutil.rmtree(dir_path)
            print(f"  ✓ 已清理 {dir_path}")
    
    print("  ✓ 清理完成")

def create_spec_file():
    """创建 PyInstaller spec 文件"""
    print("[3/5] 创建打包配置...")
    
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-
# UFO Galaxy PyInstaller Spec File

import os
import sys

block_cipher = None

# 收集所有 Python 文件
def collect_data_files():
    data_files = []
    
    # 节点目录
    nodes_dir = os.path.join(SPECPATH, '..', 'nodes')
    if os.path.exists(nodes_dir):
        for node in os.listdir(nodes_dir):
            node_path = os.path.join(nodes_dir, node)
            if os.path.isdir(node_path):
                data_files.append((node_path, os.path.join('nodes', node)))
    
    # 配置文件
    config_files = [
        ('.env.example', '.'),
        ('config', 'config'),
        ('enhancements', 'enhancements'),
        ('galaxy_gateway', 'galaxy_gateway'),
        ('ui_components', 'ui_components'),
        ('system_integration', 'system_integration'),
    ]
    
    for src, dst in config_files:
        src_path = os.path.join(SPECPATH, '..', src)
        if os.path.exists(src_path):
            data_files.append((src_path, dst))
    
    return data_files

a = Analysis(
    [os.path.join(SPECPATH, '..', 'windows_client', 'main.py')],
    pathex=[os.path.join(SPECPATH, '..')],
    binaries=[],
    datas=collect_data_files(),
    hiddenimports=[
        'fastapi',
        'uvicorn',
        'pydantic',
        'httpx',
        'aiohttp',
        'websockets',
        'PyQt5',
        'PyQt5.QtWidgets',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
    ],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='{APP_NAME}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(SPECPATH, 'icon.ico') if os.path.exists(os.path.join(SPECPATH, 'icon.ico')) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='{APP_NAME}',
)
'''
    
    spec_path = INSTALLER_DIR / f"{APP_NAME}.spec"
    with open(spec_path, 'w', encoding='utf-8') as f:
        f.write(spec_content)
    
    print(f"  ✓ 已创建 {spec_path}")
    return spec_path

def build_exe(spec_path):
    """执行打包"""
    print("[4/5] 执行打包...")
    
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        str(spec_path)
    ]
    
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    
    if result.returncode == 0:
        print("  ✓ 打包成功")
        return True
    else:
        print("  ✗ 打包失败")
        return False

def create_installer_package():
    """创建安装包"""
    print("[5/5] 创建安装包...")
    
    # 复制启动脚本和安装脚本
    dist_app_dir = DIST_DIR / APP_NAME
    
    if dist_app_dir.exists():
        # 复制安装脚本
        shutil.copy(INSTALLER_DIR / "install_windows.bat", dist_app_dir)
        shutil.copy(INSTALLER_DIR / "start_ufo_galaxy.bat", dist_app_dir)
        
        # 复制配置模板
        env_example = PROJECT_ROOT / ".env.example"
        if env_example.exists():
            shutil.copy(env_example, dist_app_dir)
        
        # 复制 README
        readme = PROJECT_ROOT / "README.md"
        if readme.exists():
            shutil.copy(readme, dist_app_dir)
        
        # 创建 ZIP 包
        zip_name = f"{APP_NAME}_v{APP_VERSION}_Windows"
        shutil.make_archive(
            str(DIST_DIR / zip_name),
            'zip',
            str(DIST_DIR),
            APP_NAME
        )
        
        print(f"  ✓ 安装包已创建: {DIST_DIR / zip_name}.zip")
        return True
    else:
        print("  ✗ 未找到打包输出目录")
        return False

def main():
    """主函数"""
    print("=" * 60)
    print(f"  UFO Galaxy Windows EXE 打包工具 v{APP_VERSION}")
    print("=" * 60)
    print()
    
    # 切换到项目根目录
    os.chdir(PROJECT_ROOT)
    
    # 执行打包流程
    check_dependencies()
    clean_build()
    spec_path = create_spec_file()
    
    if build_exe(spec_path):
        create_installer_package()
        print()
        print("=" * 60)
        print("  打包完成！")
        print(f"  输出目录: {DIST_DIR}")
        print("=" * 60)
    else:
        print()
        print("打包失败，请检查错误信息")
        sys.exit(1)

if __name__ == "__main__":
    main()
