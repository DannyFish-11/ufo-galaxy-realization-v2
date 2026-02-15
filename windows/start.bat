@echo off
REM Galaxy - Windows 一键启动
REM 双击运行即可启动完整系统

chcp 65001 > nul
title Galaxy - L4 级自主性智能系统

echo.
echo ============================================================
echo    Galaxy - L4 级自主性智能系统 v2.1.7
echo ============================================================
echo.

cd /d "%~dp0"
cd ..

REM 检查 Python
python --version > nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 检查虚拟环境
if not exist "venv" (
    echo [1/3] 创建虚拟环境...
    python -m venv venv
    echo       完成
) else (
    echo [1/3] 虚拟环境已存在
)

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 检查依赖
echo [2/3] 检查依赖...
pip show fastapi > nul 2>&1
if errorlevel 1 (
    echo       安装依赖中...
    pip install -r requirements.txt -q
    pip install pystray pillow -q
)
echo       完成

REM 检查配置
if not exist ".env" (
    echo [3/3] 创建配置文件...
    copy .env.example .env > nul
    echo       已创建 .env 文件
    echo       请编辑 .env 填入你的 API Key
) else (
    echo [3/3] 配置文件已存在
)

echo.
echo ============================================================
echo    启动 Galaxy...
echo ============================================================
echo.
echo 访问地址:
echo   控制面板: http://localhost:8080
echo   配置中心: http://localhost:8080/config
echo   API 文档: http://localhost:8080/docs
echo.
echo 提示: 关闭此窗口将停止服务
echo       按 Ctrl+C 可停止服务
echo.

REM 启动主程序
python galaxy.py

pause
