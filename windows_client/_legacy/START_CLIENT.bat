@echo off
chcp 65001 >nul 2>&1
setlocal

REM ══════════════════════════════════════════════════════════════
REM  LEGACY PATH — windows_client chat/sidebar client (RETIRED)
REM  This is the old F12-hotkey sidebar/chat client model.
REM  It is retained for compatibility only and is NOT the active
REM  Windows architecture direction.
REM
REM  Active Windows direction:
REM    DesktopPresenceRuntime (tri-state lifecycle shell) +
REM    windows_client/status_board_v2/ (desktop status surface)
REM
REM  Do not use this script as a primary Windows entry path.
REM ══════════════════════════════════════════════════════════════

REM 设置 UTF-8 编码环境（修复中文用户名路径问题）
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo ========================================
echo    Galaxy Windows 客户端
echo ========================================
echo.

echo [1/4] 检查 Python 环境...
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [错误] 未检测到 Python！
    pause
    exit /b 1
)
echo [✓] Python 已安装

echo.
echo [2/4] 检查虚拟环境...
cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
    echo 创建虚拟环境（首次启动，请稍候）...
    python -m venv .venv --copies 2>nul || python -m venv .venv
    echo [✓] 虚拟环境已创建
) else (
    echo [✓] 虚拟环境已存在
)
call .venv\Scripts\activate.bat 2>nul

echo.
echo [3/4] 安装依赖...
pip install websockets keyboard pillow pyautogui -q 2>nul
if %errorLevel% equ 0 (
    echo [✓] 依赖已安装
) else (
    echo [警告] 依赖安装可能不完整，但将尝试启动
)

echo.
echo [ERROR] This script targets windows_client/main.py (the legacy F12 sidebar
echo         client), which is RETIRED and no longer the active Windows direction.
echo.
echo [ACTION] Use the authoritative startup path instead:
echo            start.bat                (Windows bootstrap launcher)
echo          or:
echo            python unified_launcher.py
echo.
echo         Active Windows direction:
echo            DesktopPresenceRuntime + windows_client/status_board_v2/
echo         See docs/WINDOWS_EXECUTION_PIPELINE.md for the current architecture.
echo.
endlocal
pause
exit /b 1
