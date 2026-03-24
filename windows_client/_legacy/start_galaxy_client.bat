@echo off
setlocal

REM ══════════════════════════════════════════════════════════════
REM  LEGACY PATH — windows_client Gateway WebSocket client (RETIRED)
REM  This is the old direct Gateway WebSocket client model.
REM  It is retained for compatibility only and is NOT the active
REM  Windows architecture direction.
REM
REM  Active Windows direction:
REM    DesktopPresenceRuntime (tri-state lifecycle shell) +
REM    windows_client/status_board_v2/ (desktop status surface)
REM
REM  Do not use this script as a primary Windows entry path.
REM ══════════════════════════════════════════════════════════════

REM --- Galaxy Windows Client Starter ---

REM 统一入口：Galaxy Gateway (AIP v3)
REM Node_50 / UFO3 旧通道已禁用；所有通信通过 Gateway /ws/device/{id}

REM Gateway 本地地址
set GALAXY_GATEWAY_URL=ws://localhost:9000

REM 如果需要从外部设备连接，使用 Tailscale IP:
REM set GALAXY_GATEWAY_URL=ws://100.123.215.126:9000

REM 设置客户端 ID
set CLIENT_ID=windows-laptop-udvehlu0

REM 检查 Python 是否安装
python --version >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.10+ and try again.
    pause
    exit /b
)

REM ── RETIRED — do not proceed ─────────────────────────────────────────────
echo.
echo [ERROR] This script invokes windows_client/client.py, which is HARD-DISABLED.
echo         Running it will raise a RuntimeError immediately.
echo.
echo [ACTION] Use the authoritative startup path instead:
echo            python unified_launcher.py
echo          or on Windows:
echo            start.bat
echo.
echo         For Windows device ingress use:
echo            windows_aip_client.py (calls WindowsExecutionArbiter)
echo         See docs/WINDOWS_EXECUTION_PIPELINE.md for the current architecture.
echo.
endlocal
pause
exit /b 1
