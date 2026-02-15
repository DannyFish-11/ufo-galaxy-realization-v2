@echo off
REM UFO³ Galaxy Android 客户端自动配置构建脚本 (Windows 版本)
REM 版本: 1.0
REM 日期: 2026-01-22

echo ========================================
echo    UFO³ Galaxy Android 自动构建
echo ========================================
echo.

REM 获取 Windows PC 的 Tailscale IP
echo 请输入 Windows PC 的 Tailscale IP 地址:
echo (提示: 在命令行中运行 'tailscale status' 查看)
set /p WINDOWS_IP="IP 地址: "

if "%WINDOWS_IP%"=="" (
    echo [错误] IP 地址不能为空
    pause
    exit /b 1
)

echo.
echo 请输入设备 ID (例如: xiaomi-14 或 oppo-tablet):
set /p DEVICE_ID="设备 ID: "

if "%DEVICE_ID%"=="" (
    set DEVICE_ID=android-device
    echo [提示] 使用默认设备 ID: %DEVICE_ID%
)

REM 构建完整的 WebSocket URL
set WS_URL=ws://%WINDOWS_IP%:8050/ws/ufo3/%DEVICE_ID%

echo.
echo 配置信息:
echo   Windows IP: %WINDOWS_IP%
echo   设备 ID: %DEVICE_ID%
echo   WebSocket URL: %WS_URL%
echo.
echo 按任意键继续，或 Ctrl+C 取消...
pause >nul

REM 备份原始文件
set AIPCLIENT_FILE=app\src\main\java\com\ufo\galaxy\client\AIPClient.kt
if not exist "%AIPCLIENT_FILE%.backup" (
    copy "%AIPCLIENT_FILE%" "%AIPCLIENT_FILE%.backup" >nul
    echo [✓] 已备份原始配置文件
)

REM 修改配置
echo [1/3] 正在修改配置...
powershell -Command "(Get-Content '%AIPCLIENT_FILE%') -replace 'private val NODE50_URL = .*', 'private val NODE50_URL = \"%WS_URL%\"' | Set-Content '%AIPCLIENT_FILE%'"
echo [✓] 配置已更新

REM 清理旧的构建
echo.
echo [2/3] 清理旧的构建...
call gradlew.bat clean
echo [✓] 清理完成

REM 构建 APK
echo.
echo [3/3] 正在构建 APK...
echo 这可能需要几分钟，请耐心等待...
call gradlew.bat assembleDebug

REM 查找生成的 APK
set APK_PATH=app\build\outputs\apk\debug\app-debug.apk
if exist "%APK_PATH%" (
    REM 重命名 APK
    for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
    set DATE_STR=%datetime:~0,8%
    set NEW_APK_NAME=UFO3_Galaxy_%DEVICE_ID%_%DATE_STR%.apk
    copy "%APK_PATH%" "%NEW_APK_NAME%" >nul
    
    echo.
    echo ========================================
    echo    构建成功！
    echo ========================================
    echo.
    echo APK 文件: %NEW_APK_NAME%
    for %%A in ("%NEW_APK_NAME%") do echo 文件大小: %%~zA 字节
    echo.
    echo 请将此 APK 传输到您的 Android 设备并安装
    echo.
    echo 传输方法:
    echo   1. 使用 USB 连接设备，然后运行:
    echo      adb install -r "%NEW_APK_NAME%"
    echo.
    echo   2. 或将 APK 文件通过微信/QQ/邮件发送到设备
    echo.
) else (
    echo.
    echo [错误] 构建失败，未找到 APK 文件
    pause
    exit /b 1
)

REM 恢复原始配置（可选）
echo.
set /p RESTORE="是否恢复原始配置文件? (Y/N): "
if /i "%RESTORE%"=="Y" (
    move /y "%AIPCLIENT_FILE%.backup" "%AIPCLIENT_FILE%" >nul
    echo [✓] 已恢复原始配置
) else (
    echo [提示] 原始配置已保存为 %AIPCLIENT_FILE%.backup
)

echo.
echo 按任意键退出...
pause >nul
