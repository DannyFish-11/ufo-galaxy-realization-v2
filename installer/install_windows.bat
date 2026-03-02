@echo off
chcp 65001 >nul
title UFO Galaxy - Windows 安装程序
color 0A

echo ╔══════════════════════════════════════════════════════════════╗
echo ║                                                              ║
echo ║              UFO Galaxy L4 - Windows 安装程序                ║
echo ║                                                              ║
echo ║                    版本: 1.0.0                               ║
echo ║                                                              ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

:: 检查管理员权限
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [警告] 建议以管理员身份运行以获得最佳体验
    echo.
)

:: 检查 Python
echo [1/6] 检查 Python 环境...
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo [OK] Python %PYTHON_VERSION% 已安装

:: 检查 Git
echo [2/6] 检查 Git 环境...
git --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [警告] 未检测到 Git，部分功能可能受限
) else (
    echo [OK] Git 已安装
)

:: 创建虚拟环境
echo [3/6] 创建虚拟环境...
if not exist "venv" (
    python -m venv venv
    echo [OK] 虚拟环境已创建
) else (
    echo [OK] 虚拟环境已存在
)

:: 激活虚拟环境并安装依赖
echo [4/6] 安装依赖包...
call venv\Scripts\activate.bat
pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt >nul 2>&1
if %errorLevel% neq 0 (
    echo [警告] 部分依赖安装失败，请手动检查
) else (
    echo [OK] 依赖包已安装
)

:: 复制配置文件
echo [5/6] 配置环境变量...
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo [OK] 配置文件已创建，请编辑 .env 填写 API 密钥
    ) else (
        echo [警告] 未找到配置模板
    )
) else (
    echo [OK] 配置文件已存在
)

:: 创建桌面快捷方式
echo [6/6] 创建启动快捷方式...
set SCRIPT_DIR=%~dp0
set DESKTOP=%USERPROFILE%\Desktop

:: 创建 VBS 脚本来生成快捷方式
echo Set oWS = WScript.CreateObject("WScript.Shell") > CreateShortcut.vbs
echo sLinkFile = "%DESKTOP%\UFO Galaxy.lnk" >> CreateShortcut.vbs
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> CreateShortcut.vbs
echo oLink.TargetPath = "%SCRIPT_DIR%start_ufo_galaxy.bat" >> CreateShortcut.vbs
echo oLink.WorkingDirectory = "%SCRIPT_DIR%" >> CreateShortcut.vbs
echo oLink.Description = "UFO Galaxy L4 自主智能系统" >> CreateShortcut.vbs
echo oLink.Save >> CreateShortcut.vbs
cscript //nologo CreateShortcut.vbs
del CreateShortcut.vbs
echo [OK] 桌面快捷方式已创建

echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║                                                              ║
echo ║                    安装完成！                                ║
echo ║                                                              ║
echo ║  下一步:                                                     ║
echo ║  1. 编辑 .env 文件，填写必要的 API 密钥                      ║
echo ║  2. 双击桌面的 "UFO Galaxy" 快捷方式启动系统                 ║
echo ║  3. 或运行 start_ufo_galaxy.bat 启动                         ║
echo ║                                                              ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.
pause
