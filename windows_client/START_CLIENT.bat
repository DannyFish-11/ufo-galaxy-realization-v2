@echo off
chcp 65001 >nul
setlocal

echo ========================================
echo    UFO³ Galaxy Windows 客户端
echo ========================================
echo.

echo [1/3] 检查 Python 环境...
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [错误] 未检测到 Python！
    pause
    exit /b 1
)
echo [✓] Python 已安装

echo.
echo [2/3] 安装依赖...
pip install websockets keyboard pillow pyautogui -q
if %errorLevel% equ 0 (
    echo [✓] 依赖已安装
) else (
    echo [警告] 依赖安装可能不完整，但将尝试启动
)

echo.
echo [3/3] 启动客户端...
echo.
echo ========================================
echo    客户端已启动！
echo ========================================
echo.
echo 按 F12 键唤醒/隐藏侧边栏
echo 在侧边栏中输入命令并按回车发送
echo.
echo 示例命令:
echo   - 打印一个警告标志
echo   - 生成一个关于宇宙探索的视频
echo   - 优化从北京到上海的路线
echo.
echo 按 Ctrl+C 停止客户端
echo ========================================
echo.

cd /d "%~dp0"
python client.py

pause
