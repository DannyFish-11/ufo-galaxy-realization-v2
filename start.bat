@echo off
chcp 65001 >nul
title Galaxy AI System Launcher

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [X] Python not found. Install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

:: Check/create venv
if not exist ".venv" (
    echo [i] Creating virtual environment...
    python -m venv .venv
)
call .venv\Scripts\activate.bat

:: Check .env
if not exist ".env" (
    echo [i] First run — launching setup wizard...
    python main.py --setup
    exit /b 0
)

:: Delegate to main.py (unified entrypoint)
python main.py %*
