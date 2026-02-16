@echo off
REM Galaxy - Windows 一键安装脚本
REM 克隆后运行此脚本，自动完成所有配置，包括开机自启动

chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

echo.
echo ╔═══════════════════════════════════════════════════════════════╗
echo ║                                                               ║
echo ║   ██████╗  █████╗  ██████╗ ██████╗ ███████╗                  ║
echo ║   ██╔══██╗██╔══██╗██╔════╝██╔═══██╗██╔════╝                  ║
echo ║   ██║  ██║███████║██║     ██║   ██║███████╗                  ║
echo ║   ██║  ██║██╔══██║██║     ██║   ██║╚════██║                  ║
echo ║   ██████╔╝██║  ██║╚██████╗╚██████╔╝███████║                  ║
echo ║   ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝                  ║
echo ║                                                               ║
echo ║   Galaxy - Windows 一键安装                                  ║
echo ║   安装后自动 7×24 运行，开机自启动                            ║
echo ║                                                               ║
echo ╚═══════════════════════════════════════════════════════════════╝
echo.

REM 获取脚本所在目录
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM 检查 Python
echo [1/7] 检查 Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] Python 未安装
    echo.
    echo 请先安装 Python 3.10 或更高版本:
    echo   https://www.python.org/downloads/
    echo.
    echo 安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo [OK] Python 版本: %PYTHON_VERSION%
echo.

REM 创建虚拟环境
echo [2/7] 创建虚拟环境...
if exist "venv" (
    echo [OK] 虚拟环境已存在
) else (
    python -m venv venv
    echo [OK] 虚拟环境已创建
)
echo.

REM 激活虚拟环境
echo [3/7] 激活虚拟环境...
call venv\Scripts\activate.bat
echo [OK] 虚拟环境已激活
echo.

REM 安装依赖
echo [4/7] 安装依赖 (这可能需要几分钟)...
python -m pip install --upgrade pip -q
pip install -r requirements.txt -q 2>nul
if errorlevel 1 (
    pip install -r requirements.txt
)
echo [OK] 依赖安装完成
echo.

REM 创建配置文件
echo [5/7] 创建配置文件...
if not exist ".env" (
    copy .env.example .env >nul
    echo [OK] .env 文件已创建
) else (
    echo [OK] .env 文件已存在
)

REM 创建必要目录
if not exist "logs" mkdir logs
if not exist "data" mkdir data
if not exist "config" mkdir config
if not exist "cache" mkdir cache
echo [OK] 必要目录已创建
echo.

REM 配置 API Key
echo [6/7] 配置 API Key...
echo.
echo 请选择要配置的 API Key:
echo   1) OpenAI (推荐)
echo   2) DeepSeek (性价比高)
echo   3) Anthropic
echo   4) Google Gemini
echo   5) 跳过 (稍后配置)
echo.
set /p choice="请选择 [1-5]: "

if "%choice%"=="1" (
    set /p api_key="请输入 OpenAI API Key: "
    if not "!api_key!"=="" (
        echo OPENAI_API_KEY=!api_key!>> .env
        echo [OK] OpenAI API Key 已配置
    )
) else if "%choice%"=="2" (
    set /p api_key="请输入 DeepSeek API Key: "
    if not "!api_key!"=="" (
        echo DEEPSEEK_API_KEY=!api_key!>> .env
        echo [OK] DeepSeek API Key 已配置
    )
) else if "%choice%"=="3" (
    set /p api_key="请输入 Anthropic API Key: "
    if not "!api_key!"=="" (
        echo ANTHROPIC_API_KEY=!api_key!>> .env
        echo [OK] Anthropic API Key 已配置
    )
) else if "%choice%"=="4" (
    set /p api_key="请输入 Google Gemini API Key: "
    if not "!api_key!"=="" (
        echo GEMINI_API_KEY=!api_key!>> .env
        echo [OK] Google Gemini API Key 已配置
    )
) else (
    echo [跳过] 稍后请编辑 .env 文件配置 API Key
)
echo.

REM 设置开机自启动
echo [7/7] 设置开机自启动...
echo.

REM 创建启动脚本
echo @echo off > start_galaxy.bat
echo cd /d "%SCRIPT_DIR%" >> start_galaxy.bat
echo call venv\Scripts\activate.bat >> start_galaxy.bat
echo python galaxy.py --mode daemon >> start_galaxy.bat

REM 创建隐藏窗口启动脚本
echo Set WshShell = CreateObject("WScript.Shell") > start_galaxy_hidden.vbs
echo WshShell.Run chr(34) ^& "%SCRIPT_DIR%start_galaxy.bat" ^& chr(34), 0 >> start_galaxy_hidden.vbs
echo Set WshShell = Nothing >> start_galaxy_hidden.vbs

REM 复制到启动文件夹
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
copy start_galaxy_hidden.vbs "%STARTUP_FOLDER%\Galaxy.vbs" >nul
echo [OK] 开机自启动已设置
echo.

REM 立即启动
echo 启动 Galaxy...
cscript //nologo start_galaxy_hidden.vbs
timeout /t 3 /nobreak >nul
echo [OK] Galaxy 已启动
echo.

REM 显示完成信息
echo.
echo ╔═══════════════════════════════════════════════════════════════╗
echo ║                                                               ║
echo ║   ✓ Galaxy 安装完成！                                        ║
echo ║                                                               ║
echo ╚═══════════════════════════════════════════════════════════════╝
echo.
echo Galaxy 现在正在后台运行，并且已设置开机自启动。
echo.
echo 访问地址:
echo   配置中心: http://localhost:8080/config
echo   设备管理: http://localhost:8080/devices
echo   API 文档: http://localhost:8080/docs
echo.
echo 交互方式:
echo   按 F12 键唤醒交互界面
echo.
echo 管理命令:
echo   查看状态: galaxy.sh status
echo   查看日志: type logs\galaxy.log
echo   停止服务: galaxy.sh stop
echo.
echo Galaxy 将在每次开机时自动启动，7×24 小时运行。
echo.
pause
