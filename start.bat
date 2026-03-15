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
    :: 24-bit true-color gradient banner via PowerShell per-character interpolation
    powershell -NoProfile -Command ^
        "$a=@(@(0,225,253),@(41,156,255),@(109,92,255),@(184,61,245),@(255,46,147));" ^
        "function gi($t){$n=$a.Count-1;$s=[math]::Min([int]($t*$n),$n-1);" ^
        "$f=$t*$n-$s;$c1=$a[$s];$c2=$a[$s+1];" ^
        "@([int]($c1[0]+($c2[0]-$c1[0])*$f),[int]($c1[1]+($c2[1]-$c1[1])*$f),[int]($c1[2]+($c2[2]-$c1[2])*$f))}" ^
        "function gl($l){$w=60;$e=[char]27;$o='';" ^
        "for($i=0;$i-lt$l.Length;$i++){$t=if($w-gt1){$i/($w-1)}else{0};" ^
        "$c=gi $t;$o+=[string]$e+'[1;38;2;'+$c[0]+';'+$c[1]+';'+$c[2]+'m'+[string]$l[$i]};" ^
        "Write-Host ($o+[string]$e+'[0m')}" ^
        "$lines='╔══════════════════════════════════════════════════════════╗'," ^
        "'║                                                          ║'," ^
        "'║   ██████╗  █████╗ ██╗      █████╗ ██╗  ██╗██╗   ██╗    ║'," ^
        "'║  ██╔════╝ ██╔══██╗██║     ██╔══██╗╚██╗██╔╝╚██╗ ██╔╝    ║'," ^
        "'║  ██║  ███╗███████║██║     ███████║ ╚███╔╝  ╚████╔╝      ║'," ^
        "'║  ██║   ██║██╔══██║██║     ██╔══██║ ██╔██╗   ╚██╔╝       ║'," ^
        "'║  ╚██████╔╝██║  ██║███████╗██║  ██║██╔╝ ██╗   ██║        ║'," ^
        "'║   ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝        ║'," ^
        "'║                                                          ║'," ^
        "'║     L4 Autonomous Intelligence System   v2.3.21          ║'," ^
        "'║                                                          ║'," ^
        "'╚══════════════════════════════════════════════════════════╝';" ^
        "Write-Host '';$lines|ForEach-Object{gl $_};Write-Host ''"
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

:: ── 自动启动 NATS（强依赖）────────────────────────────────────────────────
echo.
echo   [>>] NATS                          启动中 (必需)...

if not defined GALAXY_NATS_URL set "GALAXY_NATS_URL=nats://localhost:4222"

:: Check if NATS port is already open
powershell -NoProfile -Command "try { $t=New-Object Net.Sockets.TcpClient; $t.Connect('localhost',4222); $t.Close(); exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 (
    echo   [OK] NATS                          已在运行 (port=4222)
    goto nats_ready
)

:: Try to start nats-server if available
where nats-server >nul 2>&1
if %errorlevel%==0 (
    start /B nats-server -p 4222
    timeout /t 3 /nobreak >nul
    powershell -NoProfile -Command "try { $t=New-Object Net.Sockets.TcpClient; $t.Connect('localhost',4222); $t.Close(); exit 0 } catch { exit 1 }" >nul 2>&1
    if %errorlevel%==0 (
        echo   [OK] NATS                          已启动 (port=4222)
        goto nats_ready
    )
    echo   [X]  NATS                          nats-server 启动失败
    echo        诊断: 运行 scripts\health_check.ps1
    deactivate
    pause
    exit /b 1
)

:: Try Docker fallback
where docker >nul 2>&1
if %errorlevel%==0 (
    docker info >nul 2>&1
    if %errorlevel%==0 (
        docker run -d --name galaxy-nats --rm -p 4222:4222 nats:latest >nul 2>&1
        timeout /t 3 /nobreak >nul
        powershell -NoProfile -Command "try { $t=New-Object Net.Sockets.TcpClient; $t.Connect('localhost',4222); $t.Close(); exit 0 } catch { exit 1 }" >nul 2>&1
        if %errorlevel%==0 (
            echo   [OK] NATS                          已通过 Docker 启动 (port=4222)
            goto nats_ready
        )
        echo   [X]  NATS                          Docker 启动失败
        deactivate
        pause
        exit /b 1
    )
)

echo   [X]  NATS                          未找到 nats-server 或 Docker
echo        下载 nats-server: https://github.com/nats-io/nats-server/releases
echo        说明: NATS 是必需的内部调度主线，缺少它系统无法启动
deactivate
pause
exit /b 1

:nats_ready

:: 启动系统
echo.
echo   [>>] Galaxy                        启动中...
echo   [i]  NATS                          %GALAXY_NATS_URL% (必需)
echo.
python unified_launcher.py %*

:: 退出
deactivate
pause
