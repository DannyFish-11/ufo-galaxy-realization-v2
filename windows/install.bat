@echo off
REM Galaxy - Windows 安装脚本
REM 双击运行此脚本安装 Galaxy

chcp 65001 > nul
echo.
echo ╔═══════════════════════════════════════════════════════════════╗
echo ║                                                               ║
echo ║   ██████╗  █████╗ ██╗      █████╗ ██╗  ██╗██╗   ██╗          ║
echo ║   ██╔════╝ ██╔══██╗██║     ██╔══██╗╚██╗██╔╝╚██╗ ██╔╝          ║
echo ║   ██║  ███╗███████║██║     ███████║ ╚███╔╝  ╚████╔╝           ║
echo ║   ██║   ██║██╔══██║██║     ██╔══██║ ██╔██╗   ╚██╔╝            ║
echo ║   ╚██████╔╝██║  ██║███████╗██║  ██║██╔╝ ██╗   ██║             ║
echo ║    ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝             ║
echo ║                                                               ║
echo ║              Galaxy - L4 级自主性智能系统                    ║
echo ║                                                               ║
echo ╚═══════════════════════════════════════════════════════════════╝
echo.

cd /d "%~dp0"
cd ..

echo [1/5] 检查 Python...
python --version > nul 2>&1
if errorlevel 1 (
    echo ❌ 未检测到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo ✅ Python 已安装

echo.
echo [2/5] 创建虚拟环境...
if not exist "venv" (
    python -m venv venv
    echo ✅ 虚拟环境创建成功
) else (
    echo ✅ 虚拟环境已存在
)

echo.
echo [3/5] 安装依赖...
call venv\Scripts\activate.bat
pip install -r requirements.txt -q
pip install pystray pillow -q
echo ✅ 依赖安装完成

echo.
echo [4/5] 配置环境变量...
if not exist ".env" (
    copy .env.example .env > nul
    echo ✅ 已创建 .env 配置文件
    echo ⚠️  请编辑 .env 文件，填入你的 API Key
) else (
    echo ✅ .env 文件已存在
)

echo.
echo [5/5] 配置开机自启动...
call :setup_autostart

echo.
echo ═══════════════════════════════════════════════════════════════
echo                    安装完成！
echo ═══════════════════════════════════════════════════════════════
echo.
echo 启动方式:
echo   1. 双击 windows\start_galaxy.bat 启动
echo   2. 或运行: python run_galaxy.py
echo.
echo 访问地址:
echo   控制面板: http://localhost:8080
echo   配置中心: http://localhost:8080/config
echo   API 文档: http://localhost:8080/docs
echo.
echo 配置文件:
echo   .env - 请填入你的 API Key
echo.
pause
exit /b 0

:setup_autostart
REM 配置开机自启动
set STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set STARTUP_SCRIPT=%~dp0start_galaxy.bat

REM 创建快捷方式
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%STARTUP_FOLDER%\Galaxy.lnk'); $s.TargetPath = '%STARTUP_SCRIPT%'; $s.WorkingDirectory = '%~dp0'; $s.Save()"

echo ✅ 已添加到开机自启动
exit /b 0
