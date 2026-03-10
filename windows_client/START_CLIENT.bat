@echo off
chcp 65001 >nul 2>&1
setlocal

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
echo [4/4] 启动客户端...
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
python main.py

pause
