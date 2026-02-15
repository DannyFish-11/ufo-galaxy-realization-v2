@echo off
REM Galaxy - 快速启动脚本
REM 双击运行即可启动 Galaxy

chcp 65001 > nul
echo.
echo ╔═══════════════════════════════════════════════════════════════╗
echo ║                    Galaxy 启动中...                          ║
echo ╚═══════════════════════════════════════════════════════════════╝
echo.

cd /d "%~dp0"
cd ..

REM 检查虚拟环境
if not exist "venv" (
    echo ❌ 未找到虚拟环境，请先运行 install.bat 安装
    pause
    exit /b 1
)

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 检查 .env
if not exist ".env" (
    echo ⚠️  未找到 .env 文件，正在创建...
    copy .env.example .env > nul
    echo ✅ 已创建 .env 文件，请配置你的 API Key
)

echo 启动 Galaxy...
echo.
echo 访问地址:
echo   控制面板: http://localhost:8080
echo   配置中心: http://localhost:8080/config
echo   API 文档: http://localhost:8080/docs
echo.
echo 按 Ctrl+C 停止服务
echo.

REM 启动主服务
python run_galaxy.py

pause
