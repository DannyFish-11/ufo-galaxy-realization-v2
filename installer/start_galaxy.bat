@echo off
chcp 65001 >nul
title Galaxy - L4 Autonomous Intelligence System
color 0B

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

:: 切换到脚本所在目录
cd /d "%~dp0.."

:: 检查虚拟环境
if not exist "venv\Scripts\activate.bat" (
    echo   [X]  虚拟环境                       不存在，请先运行 install_windows.bat
    pause
    exit /b 1
)

:: 激活虚拟环境
call venv\Scripts\activate.bat

:: 检查配置文件
if not exist ".env" (
    echo   [!]  配置文件                       .env 不存在
    echo   [i]  提示                           请复制 .env.example 为 .env 并填写 API 密钥
    pause
    exit /b 1
)

:: 启动模式选择
echo ╔══════════════════════════════════════════════════════════╗
echo ║                    请选择启动模式                        ║
echo ╠══════════════════════════════════════════════════════════╣
echo ║  [1]  完整模式  - 启动所有服务（推荐）                   ║
echo ║  [2]  轻量模式  - 仅启动核心服务                         ║
echo ║  [3]  开发模式  - 启动带调试信息                         ║
echo ║  [4]  客户端    - 仅启动 Windows 客户端                  ║
echo ║  [5]  退出                                               ║
echo ╚══════════════════════════════════════════════════════════╝
echo.
set /p choice="请输入选项 [1-5]: "

if "%choice%"=="1" goto full_mode
if "%choice%"=="2" goto lite_mode
if "%choice%"=="3" goto dev_mode
if "%choice%"=="4" goto client_mode
if "%choice%"=="5" exit /b 0
goto invalid

:full_mode
echo.
echo   [>>] 完整模式                       启动中...
echo   [1/4] Galaxy Gateway               启动中...
start /b python galaxy_gateway/main.py
timeout /t 2 >nul
echo   [2/4] L4 主循环                    启动中...
start /b python galaxy_main_loop_l4.py
timeout /t 2 >nul
echo   [3/4] Windows 客户端               启动中...
start /b python windows_client/main.py
timeout /t 2 >nul
echo   [4/4] Dashboard                    启动中...
start /b python dashboard/app.py
echo.
echo   [OK] 所有服务                       已启动
echo   [i]  提示                           按 Ctrl+C 停止所有服务
echo.
goto wait

:lite_mode
echo.
echo   [>>] 轻量模式                       启动中...
echo   [1/2] Galaxy Gateway               启动中...
start /b python galaxy_gateway/main.py
timeout /t 2 >nul
echo   [2/2] Windows 客户端               启动中...
start /b python windows_client/main.py
echo.
echo   [OK] 核心服务                       已启动
goto wait

:dev_mode
echo.
echo   [>>] 开发模式                       启动中...
set DEBUG=1
set LOG_LEVEL=DEBUG
echo   [1/3] Galaxy Gateway (调试)        启动中...
start cmd /k "python galaxy_gateway/main.py"
timeout /t 2 >nul
echo   [2/3] L4 主循环 (调试)             启动中...
start cmd /k "python galaxy_main_loop_l4.py"
timeout /t 2 >nul
echo   [3/3] Windows 客户端 (调试)        启动中...
start cmd /k "python windows_client/main.py"
echo.
echo   [OK] 开发模式                       已启动（各服务在独立窗口）
goto end

:client_mode
echo.
echo   [>>] 客户端模式                     启动中...
python windows_client/main.py
goto end

:invalid
echo   [X]  无效选项                       请重新选择
pause
goto start

:wait
echo 按任意键停止所有服务...
pause >nul
taskkill /f /im python.exe >nul 2>&1
echo   [OK] 所有服务                       已停止

:end
echo.
echo 感谢使用 Galaxy！
pause
