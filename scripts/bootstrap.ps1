# scripts/bootstrap.ps1 — Galaxy 一键初始化 (Windows PowerShell 包装器)
# 实际逻辑在跨平台的 scripts/bootstrap.py 中，这里仅转发参数。
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = (Get-Command python -ErrorAction SilentlyContinue) ?? (Get-Command python3 -ErrorAction SilentlyContinue)
if (-not $py) {
    Write-Error "未找到 python/python3，请先安装 Python 3.10+"
    exit 1
}
& $py.Path (Join-Path $here "bootstrap.py") @args
