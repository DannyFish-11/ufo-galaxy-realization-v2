@echo off
setlocal

REM --- UFO³ Galaxy Windows Client Starter ---

REM 设置 Node 50 的地址
REM 本地连接 (Podman Desktop 端口映射)
set NODE50_URL=ws://localhost:8050

REM 如果需要从外部设备连接，使用 Tailscale IP:
REM set NODE50_URL=ws://100.123.215.126:8050

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
echo [INFO] Starting UFO³ Galaxy Windows Client...
echo [INFO] Connecting to Node 50 at %NODE50_URL%...

python client.py --node50_url %NODE50_URL% --client_id %CLIENT_ID%

endlocal
pause
pause
