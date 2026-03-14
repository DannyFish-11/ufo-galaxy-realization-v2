@echo off
chcp 65001 >nul
title Galaxy - L4 Autonomous Intelligence System

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║                                                          ║
echo ║   ██████╗  █████╗ ██╗      █████╗ ██╗  ██╗██╗   ██╗    ║
echo ║  ██╔════╝ ██╔══██╗██║     ██╔══██╗╚██╗██╔╝╚██╗ ██╔╝    ║
echo ║  ██║  ███╗███████║██║     ███████║ ╚███╔╝  ╚████╔╝      ║
echo ║  ██║   ██║██╔══██║██║     ██╔══██║ ██╔██╗   ╚██╔╝       ║
echo ║  ╚██████╔╝██║  ██║███████╗██║  ██║██╔╝ ██╗   ██║        ║
echo ║   ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝        ║
echo ║                                                          ║
echo ║     L4 Autonomous Intelligence System   v2.3.21          ║
echo ║                                                          ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

:: 检查 Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   [X]  Python                         未检测到，请先安装 Python 3.9+
    echo        下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 检查 Python 版本
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo   [OK] Python                        %PYVER%

:: 检查是否首次运行
if not exist ".env" (
    echo.
    echo   [i]  首次运行                       启动配置向导...
    echo.
    python setup_wizard.py
    if %errorlevel% neq 0 (
        echo   [!]  配置向导                       未完成，将使用默认配置
    )
)

:: 安装依赖
if not exist "venv" (
    echo.
    echo   [>>] 虚拟环境                       创建中...
    python -m venv venv
)

:: 激活虚拟环境
call venv\Scripts\activate.bat

:: 安装依赖
echo   [>>] 依赖检查                       安装中...
pip install -q -r requirements.txt 2>nul

:: 启动系统
echo.
echo   [>>] Galaxy                        启动中...
echo.
python unified_launcher.py %*

:: 退出
deactivate
pause
