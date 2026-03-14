@echo off
chcp 65001 >nul
title Galaxy - L4 Autonomous Intelligence System

:: ── ANSI / VT100 support detection ──────────────────────────────────────
:: Try to enable Virtual Terminal Processing on Windows 10 1511+
:: If it fails (older Windows or non-interactive shell), fall back to plain.
set "ANSI_OK=0"
for /f "tokens=4-5 delims=. " %%i in ('ver') do (
    if %%i geq 10 set "ANSI_OK=1"
)
if "%ANSI_OK%"=="1" (
    :: Enable VT processing via PowerShell (safe, no permanent change)
    powershell -NoProfile -Command ^
        "$h=[Console]::OutputEncoding;$null=$h;" ^
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;" ^
        "$k=Add-Type -PassThru -Name 'VT' -Namespace '' -MemberDefinition '[DllImport(\"kernel32.dll\")]public static extern bool SetConsoleMode(IntPtr h,uint m);[DllImport(\"kernel32.dll\")]public static extern bool GetConsoleMode(IntPtr h,out uint m);[DllImport(\"kernel32.dll\")]public static extern IntPtr GetStdHandle(int n);';" ^
        "$hdl=$k::GetStdHandle(-11);$m=0;$k::GetConsoleMode($hdl,[ref]$m)|Out-Null;$k::SetConsoleMode($hdl,$m-bor4)|Out-Null" ^
        >nul 2>&1
    if errorlevel 1 set "ANSI_OK=0"
)

if "%ANSI_OK%"=="1" (
    :: Gradient banner: cyan top, green logo rows 1-2, purple rows 3-4, blue rows 5-6, pink bottom
    for /f %%a in ('echo prompt $E ^| cmd') do set "ESC=%%a"
    echo.
    echo %ESC%[1;96m╔══════════════════════════════════════════════════════════╗%ESC%[0m
    echo %ESC%[1;96m║                                                          ║%ESC%[0m
    echo %ESC%[1;92m║   ██████╗  █████╗ ██╗      █████╗ ██╗  ██╗██╗   ██╗    ║%ESC%[0m
    echo %ESC%[1;92m║  ██╔════╝ ██╔══██╗██║     ██╔══██╗╚██╗██╔╝╚██╗ ██╔╝    ║%ESC%[0m
    echo %ESC%[1;35m║  ██║  ███╗███████║██║     ███████║ ╚███╔╝  ╚████╔╝      ║%ESC%[0m
    echo %ESC%[1;35m║  ██║   ██║██╔══██║██║     ██╔══██║ ██╔██╗   ╚██╔╝       ║%ESC%[0m
    echo %ESC%[1;94m║  ╚██████╔╝██║  ██║███████╗██║  ██║██╔╝ ██╗   ██║        ║%ESC%[0m
    echo %ESC%[1;94m║   ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝        ║%ESC%[0m
    echo %ESC%[1;95m║                                                          ║%ESC%[0m
    echo %ESC%[1;95m║     L4 Autonomous Intelligence System   v2.3.21          ║%ESC%[0m
    echo %ESC%[1;95m║                                                          ║%ESC%[0m
    echo %ESC%[1;95m╚══════════════════════════════════════════════════════════╝%ESC%[0m
    echo.
) else (
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
)

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
