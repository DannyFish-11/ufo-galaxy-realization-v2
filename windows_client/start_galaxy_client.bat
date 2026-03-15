@echo off
setlocal

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

REM 检查依赖是否安装
python -c "import websockets; import pyautogui" >nul 2>nul
if %errorlevel% neq 0 (
    echo [INFO] Installing required packages (websockets, pyautogui)...
    pip install websockets pyautogui
)

REM 启动客户端
echo [INFO] Starting Galaxy Windows Client...
echo [INFO] Connecting to Galaxy Gateway at %GALAXY_GATEWAY_URL%...

python client.py --gateway_url %GALAXY_GATEWAY_URL% --client_id %CLIENT_ID%

endlocal
pause
pause
