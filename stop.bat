@echo off
chcp 65001 >nul
title Galaxy AI System Stop
setlocal EnableDelayedExpansion

:: stop.bat — Galaxy AI System Stop Script (Windows)
:: ================================================
:: stop.sh 的 Windows 对应物。此前仓库只有 start.bat 而没有 stop.bat ——
:: Windows 用户起得来、停不掉（B16）。
::
:: 与 stop.sh 同样做 **PID 归属校验**：PID 文件可能是上次运行留下的陈旧文件，
:: 而该 PID 早已被系统回收并分配给别的进程。不校验就直接 taskkill，等于在杀
:: 一个无关进程。这里用 WMIC/CIM 读出该 PID 的完整命令行，确认包含本仓库路径
:: 后才终止。

cd /d "%~dp0"
set "REPO_DIR=%CD%"

echo [i] Stopping Galaxy AI System...

call :StopByPidFile ".backend.pid"  "Backend"
call :StopByPidFile ".frontend.pid" "Electron"

:: ---------------------------------------------------------------------------
:: 兜底：清掉 PID 文件没覆盖到的残留进程
:: ---------------------------------------------------------------------------
:: 只杀命令行里带本仓库路径的 python，避免误杀别的项目 / 别的 Galaxy 克隆。
call :KillByCommandLine "python.exe" "%REPO_DIR%" "Backend"
call :KillByCommandLine "electron.exe" "%REPO_DIR%" "Electron"

echo [OK] All Galaxy processes stopped.
endlocal
exit /b 0


:: ===========================================================================
:StopByPidFile
::   %~1 PID 文件名   %~2 人类可读名
:: ===========================================================================
set "PIDFILE=%~1"
set "LABEL=%~2"
if not exist "%PIDFILE%" exit /b 0

set "PID="
for /f "usebackq delims=" %%p in ("%PIDFILE%") do set "PID=%%p"

:: 只保留数字，防止 PID 文件被写脏
for /f "delims=0123456789" %%x in ("!PID!") do (
    echo [!] %LABEL%: PID 文件内容不是纯数字，跳过并清理
    del /f /q "%PIDFILE%" >nul 2>&1
    exit /b 0
)
if "!PID!"=="" (
    del /f /q "%PIDFILE%" >nul 2>&1
    exit /b 0
)

:: 进程还在吗
tasklist /fi "PID eq !PID!" 2>nul | find "!PID!" >nul
if errorlevel 1 (
    echo [i] %LABEL%: PID !PID! 已不存在（陈旧 PID 文件），仅清理文件
    del /f /q "%PIDFILE%" >nul 2>&1
    exit /b 0
)

:: 归属校验：这个 PID 现在跑的确实是本仓库的东西吗？
set "OWNED="
for /f "usebackq skip=1 delims=" %%c in (`wmic process where "ProcessId=!PID!" get CommandLine 2^>nul`) do (
    set "CMDLINE=%%c"
    if defined CMDLINE (
        echo !CMDLINE! | find /i "%REPO_DIR%" >nul && set "OWNED=1"
    )
)

if not defined OWNED (
    echo [!] %LABEL%: PID !PID! 不属于本仓库（PID 已被复用），拒绝终止
    del /f /q "%PIDFILE%" >nul 2>&1
    exit /b 0
)

taskkill /PID !PID! /T /F >nul 2>&1
if errorlevel 1 (
    echo [!] %LABEL%: 终止 PID !PID! 失败
) else (
    echo [OK] %LABEL% stopped ^(pid !PID!^)
)
del /f /q "%PIDFILE%" >nul 2>&1
exit /b 0


:: ===========================================================================
:KillByCommandLine
::   %~1 映像名   %~2 命令行里必须出现的特征串   %~3 人类可读名
:: ===========================================================================
set "IMAGE=%~1"
set "NEEDLE=%~2"
set "LABEL=%~3"

:: 逐个 PID 单独查命令行，而不是用 `get ProcessId,CommandLine /format:csv` ——
:: wmic 的 CSV 列序在不同 Windows 版本上并不稳定（首列是 Node，且 CommandLine
:: 自身含逗号会把列切碎），按列取值容易拿错。多一次查询换取确定性。
for /f "usebackq skip=1 delims=" %%p in (`wmic process where "Name='%IMAGE%'" get ProcessId 2^>nul`) do (
    set "P=%%p"
    set "P=!P: =!"
    if not "!P!"=="" (
        set "CL="
        for /f "usebackq skip=1 delims=" %%c in (`wmic process where "ProcessId=!P!" get CommandLine 2^>nul`) do (
            if not defined CL set "CL=%%c"
        )
        if defined CL (
            echo !CL! | find /i "%NEEDLE%" >nul
            if not errorlevel 1 (
                taskkill /PID !P! /T /F >nul 2>&1
                if not errorlevel 1 echo [OK] %LABEL% process killed ^(pid !P!^)
            )
        )
    )
)
exit /b 0
