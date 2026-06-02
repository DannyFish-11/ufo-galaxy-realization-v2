# Galaxy Windows 任务计划程序安装
# ===================================
# 替代启动文件夹，更可靠的开机自启
#
# 用法 (管理员 PowerShell):
#   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
#   .\install_taskscheduler.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = (Get-Command python).Source
$TaskName = "GalaxyDaemon"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Galaxy 任务计划程序安装" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. 检查管理员权限
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "  ✗ 需要管理员权限，请右键 PowerShell → 以管理员身份运行" -ForegroundColor Red
    exit 1
}

# 2. 删除旧任务（如果存在）
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "  已删除旧任务" -ForegroundColor Yellow
}

# 3. 删除启动文件夹旧快捷方式（如果存在）
$StartupDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
$OldShortcut = "$StartupDir\Galaxy.lnk"
if (Test-Path $OldShortcut) {
    Remove-Item $OldShortcut
    Write-Host "  已删除启动文件夹旧快捷方式" -ForegroundColor Yellow
}

# 4. 创建任务计划程序任务
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$ProjectRoot\galaxy_daemon.py`"" -WorkingDirectory $ProjectRoot

# 触发器：开机时启动（不管用户是否登录）
$Trigger = New-ScheduledTaskTrigger -AtStartup

# 设置：隐藏窗口，1分钟延迟（等网络就绪），崩溃后重启
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)  # 无限运行

# 主体：系统账户（不需要用户登录就能运行）
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null

Write-Host "  ✓ 任务 '$TaskName' 已创建" -ForegroundColor Green
Write-Host "" 
Write-Host "  任务详情:" -ForegroundColor Cyan
Write-Host "    触发: 开机时 (AtStartup)" -ForegroundColor Gray
Write-Host "    账户: SYSTEM (无需登录)" -ForegroundColor Gray
Write-Host "    崩溃重启: 3次，间隔1分钟" -ForegroundColor Gray
Write-Host "    日志: $ProjectRoot\logs\" -ForegroundColor Gray

# 5. 立即启动测试
Write-Host ""
$start = Read-Host "  是否立即启动测试? (y/n)"
if ($start -eq "y" -or $start -eq "Y") {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "  已启动，等待5秒..." -ForegroundColor Yellow
    Start-Sleep -Seconds 5
    $task = Get-ScheduledTask -TaskName $TaskName
    Write-Host "  状态: $($task.State)" -ForegroundColor $(if ($task.State -eq "Running") { "Green" } else { "Red" })
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  ✓ 安装完成" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  管理命令:" -ForegroundColor Cyan
Write-Host "    查看状态: Get-ScheduledTask -TaskName GalaxyDaemon" -ForegroundColor Gray
Write-Host "    手动启动: Start-ScheduledTask -TaskName GalaxyDaemon" -ForegroundColor Gray
Write-Host "    手动停止: Stop-ScheduledTask -TaskName GalaxyDaemon" -ForegroundColor Gray
Write-Host "    删除任务: Unregister-ScheduledTask -TaskName GalaxyDaemon -Confirm:`$false" -ForegroundColor Gray
Write-Host ""
