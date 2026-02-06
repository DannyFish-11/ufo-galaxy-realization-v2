#!/usr/bin/env python3
"""
UFO Galaxy - EXE 打包脚本
==========================
使用 PyInstaller 将 UFO Galaxy 打包成独立的 Windows 可执行文件。

功能：
1. 自动安装 PyInstaller
2. 收集所有必要的文件
3. 生成单文件或目录形式的 exe
4. 创建安装程序

使用方法：
    python build_exe.py              # 默认打包（目录形式）
    python build_exe.py --onefile    # 单文件打包
    python build_exe.py --installer  # 创建安装程序
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
from typing import List

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.absolute()

# 打包配置
APP_NAME = "UFO-Galaxy"
APP_VERSION = "1.0.0"
APP_DESCRIPTION = "L4 级自主性智能系统"
APP_AUTHOR = "UFO Galaxy Team"
APP_ICON = PROJECT_ROOT / "assets" / "icon.ico"

# 需要包含的数据文件和目录
DATA_FILES = [
    ("nodes", "nodes"),
    ("enhancements", "enhancements"),
    ("core", "core"),
    ("config", "config"),
    ("fusion", "fusion"),
    ("galaxy_gateway", "galaxy_gateway"),
    ("ui_components", "ui_components"),
    ("system_integration", "system_integration"),
    (".env.example", "."),
    ("requirements.txt", "."),
    ("setup_wizard.py", "."),
    ("node_dependencies.json", "."),
]

# 需要排除的模块
EXCLUDED_MODULES = [
    "tkinter",
    "matplotlib",
    "PIL",
    "cv2",
    "tensorflow",
    "torch",
    "numpy.testing",
]

# 隐藏导入（PyInstaller 可能检测不到的模块）
HIDDEN_IMPORTS = [
    "aiohttp",
    "fastapi",
    "uvicorn",
    "pydantic",
    "httpx",
    "psutil",
    "asyncio",
    "json",
    "logging",
    "pathlib",
    "dataclasses",
    "typing",
    "enum",
]


def print_status(message: str, status: str = "info"):
    """打印状态信息"""
    icons = {
        "info": "ℹ️ ",
        "success": "✅",
        "warning": "⚠️ ",
        "error": "❌",
        "loading": "⏳",
    }
    icon = icons.get(status, icons["info"])
    print(f"{icon} {message}")


def check_pyinstaller() -> bool:
    """检查并安装 PyInstaller"""
    try:
        import PyInstaller
        print_status(f"PyInstaller 版本: {PyInstaller.__version__}", "success")
        return True
    except ImportError:
        print_status("安装 PyInstaller...", "loading")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
            return True
        except subprocess.CalledProcessError:
            print_status("PyInstaller 安装失败", "error")
            return False


def create_icon():
    """创建应用图标"""
    icon_dir = PROJECT_ROOT / "assets"
    icon_dir.mkdir(exist_ok=True)
    
    icon_path = icon_dir / "icon.ico"
    if icon_path.exists():
        return icon_path
        
    # 如果没有图标，创建一个简单的占位图标
    print_status("创建默认图标...", "loading")
    
    try:
        from PIL import Image, ImageDraw, ImageFont
        
        # 创建 256x256 的图标
        size = 256
        img = Image.new('RGBA', (size, size), (26, 26, 46, 255))
        draw = ImageDraw.Draw(img)
        
        # 绘制渐变圆
        for i in range(size // 2, 0, -1):
            alpha = int(255 * (i / (size // 2)))
            color = (0, 212, 255, alpha)
            draw.ellipse([
                size // 2 - i, size // 2 - i,
                size // 2 + i, size // 2 + i
            ], fill=color)
            
        # 添加文字
        try:
            font = ImageFont.truetype("arial.ttf", 80)
        except:
            font = ImageFont.load_default()
            
        draw.text((size // 2, size // 2), "UFO", fill=(255, 255, 255, 255), 
                  font=font, anchor="mm")
        
        # 保存为 ICO
        img.save(icon_path, format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
        print_status(f"图标已创建: {icon_path}", "success")
        return icon_path
        
    except ImportError:
        print_status("无法创建图标（需要 Pillow），将使用默认图标", "warning")
        return None


def generate_spec_file(onefile: bool = False) -> Path:
    """生成 PyInstaller spec 文件"""
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-
# UFO Galaxy PyInstaller Spec File
# 自动生成，请勿手动修改

import os
import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(r'{PROJECT_ROOT}')

# 分析配置
a = Analysis(
    [str(PROJECT_ROOT / 'main.py')],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        {', '.join([f"(str(PROJECT_ROOT / '{src}'), '{dst}')" for src, dst in DATA_FILES])}
    ],
    hiddenimports={HIDDEN_IMPORTS},
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes={EXCLUDED_MODULES},
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

'''
    
    if onefile:
        spec_content += f'''
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='{APP_NAME}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=r'{APP_ICON}' if Path(r'{APP_ICON}').exists() else None,
    version_info={{
        'CompanyName': '{APP_AUTHOR}',
        'FileDescription': '{APP_DESCRIPTION}',
        'FileVersion': '{APP_VERSION}',
        'ProductName': '{APP_NAME}',
        'ProductVersion': '{APP_VERSION}',
    }},
)
'''
    else:
        spec_content += f'''
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
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=r'{APP_ICON}' if Path(r'{APP_ICON}').exists() else None,
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
    
    spec_path = PROJECT_ROOT / f"{APP_NAME}.spec"
    with open(spec_path, 'w', encoding='utf-8') as f:
        f.write(spec_content)
        
    print_status(f"Spec 文件已生成: {spec_path}", "success")
    return spec_path


def build_exe(onefile: bool = False) -> bool:
    """构建 EXE"""
    print_status("=" * 50, "info")
    print_status(f"开始构建 {APP_NAME} v{APP_VERSION}", "info")
    print_status("=" * 50, "info")
    
    # 检查 PyInstaller
    if not check_pyinstaller():
        return False
        
    # 创建图标
    create_icon()
    
    # 生成 spec 文件
    spec_path = generate_spec_file(onefile)
    
    # 清理旧的构建
    build_dir = PROJECT_ROOT / "build"
    dist_dir = PROJECT_ROOT / "dist"
    
    if build_dir.exists():
        print_status("清理旧的构建目录...", "loading")
        shutil.rmtree(build_dir)
        
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
        
    # 运行 PyInstaller
    print_status("运行 PyInstaller...", "loading")
    
    try:
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--clean",
            "--noconfirm",
            str(spec_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print_status("PyInstaller 构建失败", "error")
            print(result.stderr)
            return False
            
    except Exception as e:
        print_status(f"构建失败: {e}", "error")
        return False
        
    # 检查输出
    if onefile:
        exe_path = dist_dir / f"{APP_NAME}.exe"
    else:
        exe_path = dist_dir / APP_NAME / f"{APP_NAME}.exe"
        
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print_status("=" * 50, "info")
        print_status(f"构建成功！", "success")
        print_status(f"输出路径: {exe_path}", "info")
        print_status(f"文件大小: {size_mb:.1f} MB", "info")
        print_status("=" * 50, "info")
        return True
    else:
        print_status("构建完成但未找到输出文件", "error")
        return False


def create_installer():
    """创建安装程序（使用 NSIS 或 Inno Setup）"""
    print_status("创建安装程序...", "loading")
    
    # 生成 Inno Setup 脚本
    iss_content = f'''
; UFO Galaxy Inno Setup Script
; 自动生成

#define MyAppName "{APP_NAME}"
#define MyAppVersion "{APP_VERSION}"
#define MyAppPublisher "{APP_AUTHOR}"
#define MyAppExeName "{APP_NAME}.exe"

[Setup]
AppId={{{{8F3B9A2E-1234-5678-9ABC-DEF012345678}}}}
AppName={{#MyAppName}}
AppVersion={{#MyAppVersion}}
AppPublisher={{#MyAppPublisher}}
DefaultDirName={{autopf}}\\{{#MyAppName}}
DefaultGroupName={{#MyAppName}}
AllowNoIcons=yes
OutputDir={PROJECT_ROOT}\\installer_output
OutputBaseFilename={APP_NAME}-Setup-{APP_VERSION}
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"

[Files]
Source: "{PROJECT_ROOT}\\dist\\{APP_NAME}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{group}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"
Name: "{{autodesktop}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"; Tasks: desktopicon

[Run]
Filename: "{{app}}\\{{#MyAppExeName}}"; Description: "启动 {{#MyAppName}}"; Flags: nowait postinstall skipifsilent
'''
    
    iss_path = PROJECT_ROOT / "installer" / f"{APP_NAME}.iss"
    iss_path.parent.mkdir(exist_ok=True)
    
    with open(iss_path, 'w', encoding='utf-8') as f:
        f.write(iss_content)
        
    print_status(f"Inno Setup 脚本已生成: {iss_path}", "success")
    print_status("请使用 Inno Setup 编译此脚本生成安装程序", "info")
    print_status("下载 Inno Setup: https://jrsoftware.org/isinfo.php", "info")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="UFO Galaxy EXE 打包工具")
    parser.add_argument("--onefile", "-o", action="store_true", help="打包成单个 exe 文件")
    parser.add_argument("--installer", "-i", action="store_true", help="创建安装程序脚本")
    parser.add_argument("--clean", "-c", action="store_true", help="清理构建文件")
    
    args = parser.parse_args()
    
    if args.clean:
        print_status("清理构建文件...", "loading")
        for path in ["build", "dist", f"{APP_NAME}.spec"]:
            full_path = PROJECT_ROOT / path
            if full_path.exists():
                if full_path.is_dir():
                    shutil.rmtree(full_path)
                else:
                    full_path.unlink()
        print_status("清理完成", "success")
        return
        
    # 构建 EXE
    success = build_exe(onefile=args.onefile)
    
    if success and args.installer:
        create_installer()


if __name__ == "__main__":
    main()
