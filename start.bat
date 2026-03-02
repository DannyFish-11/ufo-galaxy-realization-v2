@echo off
chcp 65001 >nul
title UFO Galaxy - L4 级自主性智能系统

echo.
echo  ╔═══════════════════════════════════════════════════════════╗
echo  ║                                                           ║
echo  ║              UFO Galaxy 启动器                            ║
echo  ║              L4 级自主性智能系统                          ║
echo  ║                                                           ║
echo  ╚═══════════════════════════════════════════════════════════╝
echo.

:: 检查 Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.9+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 检查 Python 版本
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [信息] 检测到 Python %PYVER%

:: 检查是否首次运行
if not exist ".env" (
    echo.
    echo [提示] 首次运行，启动配置向导...
    echo.
    python setup_wizard.py
    if %errorlevel% neq 0 (
        echo [警告] 配置向导未完成，将使用默认配置
    )
)

:: 安装依赖
if not exist "venv" (
    echo.
    echo [信息] 创建虚拟环境...
    python -m venv venv
)

:: 激活虚拟环境
call venv\Scripts\activate.bat

:: 安装依赖
echo [信息] 检查依赖...
pip install -q -r requirements.txt 2>nul

:: 启动系统
echo.
echo [信息] 启动 UFO Galaxy...
echo.
python main.py %*

:: 退出
deactivate
pause
