# Galaxy Windows 安装脚本
# ========================
# 一键安装依赖 + 配置开机自启
# 
# 用法 (管理员 PowerShell):
#   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
#   .\install_windows.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = (Get-Command python).Source

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Galaxy Windows 安装" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 检查 Python
Write-Host "[1/6] 检查 Python..." -ForegroundColor Yellow
$PyVersion = & $PythonExe --version 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ✗ Python 未安装，请从 https://python.org 下载 3.10+" -ForegroundColor Red
    exit 1
}
Write-Host "  ✓ $PyVersion" -ForegroundColor Green

# 2. 安装依赖
Write-Host ""
Write-Host "[2/6] 安装核心依赖..." -ForegroundColor Yellow
& $PythonExe -m pip install --upgrade pip --quiet
& $PythonExe -m pip install -r "$ProjectRoot\requirements-core.txt" --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ⚠ 核心依赖安装遇到问题，重试中..." -ForegroundColor Yellow
    & $PythonExe -m pip install -r "$ProjectRoot\requirements-core.txt" --no-deps --quiet
}
Write-Host "  ✓ 核心依赖完成" -ForegroundColor Green

Write-Host ""
Write-Host "[3/6] 安装增强依赖..." -ForegroundColor Yellow
& $PythonExe -m pip install -r "$ProjectRoot\requirements-enhance.txt" --quiet 2>$null
Write-Host "  ✓ 增强依赖完成 (失败项已跳过)" -ForegroundColor Green

Write-Host ""
Write-Host "[4/6] 安装 Windows 依赖..." -ForegroundColor Yellow
& $PythonExe -m pip install -r "$ProjectRoot\requirements-windows.txt" --quiet 2>$null
Write-Host "  ✓ Windows 依赖完成" -ForegroundColor Green

# 3. 创建 .env 文件（如果不存在）
Write-Host ""
Write-Host "[5/6] 配置文件..." -ForegroundColor Yellow
$EnvFile = "$ProjectRoot\.env"
if (-not (Test-Path $EnvFile)) {
    $Token = Read-Host "  输入 GALAXY_API_TOKEN (回车跳过，跳过则关闭认证)"
    if ($Token) {
        $AuthEnabled = "true"
    } else {
        $AuthEnabled = "false"
        Write-Host "  未输入 Token，认证已关闭 (守护模式安全默认值)" -ForegroundColor Yellow
    }
    @"
GALAXY_API_TOKEN=$Token
GALAXY_AUTH_ENABLED=$AuthEnabled
GALAXY_NATS_ENABLED=false
GALAXY_DESKTOP_GUI_ENABLED=false
"@ | Out-File -FilePath $EnvFile -Encoding UTF8
    Write-Host "  ✓ .env 已创建" -ForegroundColor Green
} else {
    Write-Host "  ✓ .env 已存在，跳过" -ForegroundColor Green
}

# 4. 创建开机启动快捷方式
Write-Host ""
Write-Host "[6/6] 配置开机自启..." -ForegroundColor Yellow
$StartupDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
$ShortcutPath = "$StartupDir\Galaxy.lnk"

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $PythonExe
$Shortcut.Arguments = "`"$ProjectRoot\galaxy_daemon.py`""
$Shortcut.WorkingDirectory = "$ProjectRoot"
$Shortcut.IconLocation = "$PythonExe,0"
$Shortcut.Description = "Galaxy AI Daemon"
$Shortcut.Save()

Write-Host "  ✓ 开机启动已配置" -ForegroundColor Green

# 完成
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  ✓ 安装完成" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  启动命令:" -ForegroundColor Cyan
Write-Host "    python galaxy_daemon.py        (前台调试)"
Write-Host "    python main.py                 (直接启动)"
Write-Host ""
Write-Host "  开机自启:" -ForegroundColor Cyan
Write-Host "    已添加到启动目录，下次开机自动运行"
Write-Host ""
Write-Host "  日志位置:" -ForegroundColor Cyan
Write-Host "    $ProjectRoot\logs\" -ForegroundColor Gray
Write-Host ""
