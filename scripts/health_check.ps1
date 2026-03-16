# Galaxy Health Check — Windows PowerShell
# Usage: .\scripts\health_check.ps1
#
# Environment variables (all optional, defaults shown):
#   GALAXY_API_BASE   — Galaxy unified launcher URL  (default: http://localhost:8299)
#   GALAXY_NODE71_URL — Node_71 URL                  (default: http://localhost:8071)
#   GALAXY_NATS_HOST  — NATS host                    (default: localhost)
#   GALAXY_NATS_PORT  — NATS port                    (default: 4222)
#   GALAXY_NATS_URL   — Full NATS URL (overrides host/port)

$ErrorActionPreference = "Continue"

# ── Configuration ────────────────────────────────────────────────────────────
# unified_launcher 默认端口为 8299（非旧版 9000）
$baseUrl    = if ($env:GALAXY_API_BASE)   { $env:GALAXY_API_BASE }   else { "http://localhost:8299" }
$node71Url  = if ($env:GALAXY_NODE71_URL) { $env:GALAXY_NODE71_URL } else { "http://localhost:8071" }
$natsHost   = if ($env:GALAXY_NATS_HOST)  { $env:GALAXY_NATS_HOST }  else { "localhost" }
$natsPort   = if ($env:GALAXY_NATS_PORT)  { [int]$env:GALAXY_NATS_PORT } else { 4222 }
$natsUrl    = if ($env:GALAXY_NATS_URL)   { $env:GALAXY_NATS_URL }   else { "nats://${natsHost}:${natsPort}" }
$natsEnvSet = [bool]$env:GALAXY_NATS_URL

$failed = $false

# ── LAN IP helper ────────────────────────────────────────────────────────────
function Get-LanIP {
    try {
        $udpClient = New-Object System.Net.Sockets.UdpClient
        $udpClient.Connect("8.8.8.8", 80)
        $ip = ($udpClient.Client.LocalEndPoint).Address.ToString()
        $udpClient.Close()
        return $ip
    } catch { return "" }
}

# ── Helpers ──────────────────────────────────────────────────────────────────
function Write-Ok   { param($label, $detail="") Write-Host ("  [OK] {0,-40} {1}" -f $label, $detail) -ForegroundColor Green }
function Write-Fail { param($label, $detail="") Write-Host ("  [X]  {0,-40} {1}" -f $label, $detail) -ForegroundColor Red; $script:failed = $true }
function Write-Warn { param($label, $detail="") Write-Host ("  [!]  {0,-40} {1}" -f $label, $detail) -ForegroundColor Yellow }
function Write-Info { param($label, $detail="") Write-Host ("  [i]  {0,-40} {1}" -f $label, $detail) -ForegroundColor Cyan }
function Write-Hdr  { param($title) Write-Host ("") ; Write-Host ("-- $title " + ("-" * [Math]::Max(0, 50 - $title.Length))) -ForegroundColor Cyan }

function Test-TcpPort {
    param([string]$HostName, [int]$Port, [int]$TimeoutMs = 2000)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $result = $client.BeginConnect($HostName, $Port, $null, $null)
        $waited = $result.AsyncWaitHandle.WaitOne($TimeoutMs)
        if ($waited) { $client.EndConnect($result); $client.Close(); return $true }
        $client.Close(); return $false
    } catch { return $false }
}

function Invoke-CheckHttp {
    param([string]$Url, [string]$Label)
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        Write-Ok $Label "HTTP $($resp.StatusCode)"
        return $resp
    } catch {
        $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { "ERR" }
        Write-Fail $Label "HTTP $code — $($_.Exception.Message)"
        return $null
    }
}

# ── Banner ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "== Galaxy Health Check (Windows) ==" -ForegroundColor Cyan -NoNewline; Write-Host ""
Write-Info "Launcher URL"   $baseUrl
Write-Info "Node_71"        $node71Url
Write-Info "NATS"           $natsUrl
Write-Host ""

# ── NATS 默认策略提示 ──────────────────────────────────────────────────────────
if (-not $natsEnvSet) {
    $lanIp = Get-LanIP
    Write-Warn "GALAXY_NATS_URL" "未设置 — 默认使用 nats://localhost:4222 (单机开发模式)"
    if ($lanIp) {
        Write-Info "跨设备提示" "设置 `$env:GALAXY_NATS_URL=nats://${lanIp}:4222 可让局域网设备接入"
    }
    Write-Host ""
}

# ── 1. NATS port (required) ──────────────────────────────────────────────────
Write-Hdr "NATS (必需)"
if (Test-TcpPort -HostName $natsHost -Port $natsPort) {
    Write-Ok "NATS port $natsPort" "监听中"
} else {
    Write-Fail "NATS port $natsPort" "未监听 — 启动: nats-server -p $natsPort"
}

# ── 2. Key ports ─────────────────────────────────────────────────────────────
Write-Hdr "关键端口"
@(
    @{Port=8299; Label="UnifiedLauncher"},
    @{Port=8071; Label="Node_71"},
    @{Port=4222; Label="NATS"}
) | ForEach-Object {
    $p = $_.Port; $l = $_.Label
    if (Test-TcpPort -HostName "localhost" -Port $p) {
        Write-Ok "端口 $p ($l)" "已监听"
    } else {
        Write-Warn "端口 $p ($l)" "未监听"
    }
}

# ── 3. Gateway / Core health ─────────────────────────────────────────────────
Write-Hdr "Unified Launcher / Core"
Invoke-CheckHttp "$baseUrl/health"              "GET /health"             | Out-Null
Invoke-CheckHttp "$baseUrl/api/v1/system/info"  "GET /api/v1/system/info" | Out-Null

# /api/v1/observability/live-status (best-effort)
try {
    $resp = Invoke-WebRequest -Uri "$baseUrl/api/v1/observability/live-status" -UseBasicParsing -TimeoutSec 5 -ErrorAction SilentlyContinue
    if ($resp -and $resp.StatusCode -lt 300) {
        Write-Ok "GET /api/v1/observability/live-status" "HTTP $($resp.StatusCode)"
    } else {
        Write-Warn "GET /api/v1/observability/live-status" "not available"
    }
} catch { Write-Warn "GET /api/v1/observability/live-status" "not available" }

# NATS status via API
try {
    $natsResp = Invoke-WebRequest -Uri "$baseUrl/health/nats" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    Write-Ok "GET /health/nats" "HTTP $($natsResp.StatusCode)"
    $natsData = $natsResp.Content | ConvertFrom-Json -ErrorAction SilentlyContinue
    if ($natsData) {
        if ($natsData.status -eq "connected") {
            Write-Ok "NATS status" "connected (mainline active)"
        } else {
            Write-Fail "NATS status" "$($natsData.status) — NATS is required"
        }
    }
} catch {
    Write-Warn "GET /health/nats" "not available"
}

# ── 4. Node_71 health ────────────────────────────────────────────────────────
Write-Hdr "Node_71 (多设备协调主线)"
Invoke-CheckHttp "$node71Url/health" "GET Node_71 /health" | Out-Null

# ── 5. Docker containers (best-effort) ──────────────────────────────────────
$dockerAvail = $null -ne (Get-Command docker -ErrorAction SilentlyContinue)
if ($dockerAvail) {
    try {
        $dockerInfo = docker info 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Hdr "Docker 容器状态"
            $containers = docker ps --filter "name=nats" --filter "name=gateway" --filter "name=node_71" --filter "name=galaxy" --format "{{.Names}}`t{{.Status}}" 2>$null
            if ($containers) {
                $containers -split "`n" | Where-Object { $_ } | ForEach-Object {
                    $parts = $_ -split "`t"
                    $cname = $parts[0]; $cstatus = $parts[1]
                    if ($cstatus -match "^Up") {
                        Write-Ok $cname $cstatus
                    } else {
                        Write-Warn $cname $cstatus
                    }
                }
            } else {
                Write-Info "Docker 容器" "未发现相关容器"
            }
        }
    } catch {
        Write-Info "Docker" "不可用或未运行"
    }
}

# ── Summary ──────────────────────────────────────────────────────────────────
Write-Host ""
if (-not $failed) {
    Write-Host "✅  所有检查通过" -ForegroundColor Green
    Write-Host ""
    exit 0
} else {
    Write-Host "❌  部分检查失败，请查看上方诊断信息" -ForegroundColor Red
    Write-Host ""
    Write-Host "常见修复方法:" -ForegroundColor Yellow
    Write-Host "  1. 启动 NATS:        nats-server -p 4222"
    Write-Host "  2. 下载 nats-server: https://github.com/nats-io/nats-server/releases"
    Write-Host "  3. Docker 启动 NATS: docker run -d --rm -p 4222:4222 nats:latest"
    Write-Host "  4. 检查端口占用:     netstat -ano | findstr :4222"
    Write-Host "  5. 完整部署指南:     docs\DEPLOYMENT_COMPLETE.md"
    Write-Host "  6. 故障排查手册:     docs\TROUBLESHOOTING.md"
    Write-Host ""
    exit 1
}
