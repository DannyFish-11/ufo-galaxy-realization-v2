@echo off
chcp 65001 >nul
title Galaxy - L4 Autonomous Intelligence System
color 0B

:: ── ANSI / VT100 support detection ──────────────────────────────────────
set "ANSI_OK=0"
for /f "tokens=4-5 delims=. " %%i in ('ver') do (
    if %%i geq 10 set "ANSI_OK=1"
)
if "%ANSI_OK%"=="1" (
    powershell -NoProfile -Command ^
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

:: ══════════════════════════════════════════════════════════════
:: NOTICE: installer/start_galaxy.bat — LEGACY INSTALLER SCRIPT
:: This script previously started services individually by invoking:
::   galaxy_main_loop_l4.py  (retired — now managed by unified_launcher.py)
::   windows_client/main.py  (retired — legacy F12 sidebar client)
::   dashboard/app.py        (retired — superseded by unified web UI)
::
:: All modes now delegate to the authoritative startup path:
::   python unified_launcher.py
:: or the top-level wrapper:
::   start.bat  (in the repository root)
:: ══════════════════════════════════════════════════════════════

:: 启动模式选择
echo ╔══════════════════════════════════════════════════════════╗
echo ║                    请选择启动模式                        ║
echo ╠══════════════════════════════════════════════════════════╣
echo ║  [1]  完整模式  - 启动所有服务（推荐）                   ║
echo ║  [2]  最小模式  - 仅启动核心服务                         ║
echo ║  [3]  开发模式  - 启动带调试信息                         ║
echo ║  [4]  客户端    - [已停用，见下方说明]                   ║
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
echo   [>>] 权威入口: unified_launcher.py
echo.
python unified_launcher.py
goto end

:lite_mode
echo.
echo   [>>] 最小模式                       启动中...
echo   [>>] 权威入口: unified_launcher.py --minimal
echo.
python unified_launcher.py --minimal
goto end

:dev_mode
echo.
echo   [>>] 开发模式                       启动中...
set DEBUG=1
set LOG_LEVEL=DEBUG
echo   [>>] 权威入口: unified_launcher.py
echo.
python unified_launcher.py
goto end

:client_mode
echo.
echo   [X]  Windows 客户端独立模式已停用
echo.
echo        windows_client/main.py (旧 F12 侧边栏客户端) 已退役。
echo        windows_client/client.py 已硬禁用 (会抛出 RuntimeError)。
echo.
echo        当前 Windows 方向:
echo          DesktopPresenceRuntime + windows_client/status_board_v2/
echo.
echo        如需启动完整系统，请选择选项 [1] 或直接运行:
echo          python unified_launcher.py
echo        或顶层包装器:
echo          ..\start.bat
echo.
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
