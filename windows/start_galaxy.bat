@echo off
REM Galaxy - Windows 自启动脚本
REM 将此文件放入启动文件夹: shell:startup

cd /d "%~dp0"
cd ..

echo Starting Galaxy...

REM 激活虚拟环境并启动
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

REM 启动 Galaxy 托盘程序
start "" pythonw "%~dp0galaxy_tray.py"

REM 等待 3 秒后启动主服务
timeout /t 3 /nobreak > nul

REM 启动主服务（后台运行）
start /b pythonw run_galaxy.py --mode daemon

echo Galaxy started!
exit
