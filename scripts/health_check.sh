#!/usr/bin/env bash
# Galaxy Health Check — Linux / macOS
# Usage: bash scripts/health_check.sh
#
# Environment variables (all optional, defaults shown):
#   GALAXY_API_BASE   — Galaxy unified launcher URL  (default: http://localhost:8299)
#   GALAXY_NODE71_URL — Node_71 URL                  (default: http://localhost:8071)
#   GALAXY_NATS_HOST  — NATS host                    (default: localhost)
#   GALAXY_NATS_PORT  — NATS port                    (default: 4222)
#   GALAXY_NATS_URL   — Full NATS URL (overrides host/port)

set -euo pipefail

# ── Color helpers ────────────────────────────────────────────────────────────
if [ -t 1 ] && [ "${TERM:-dumb}" != "dumb" ]; then
    GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'
    CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; CYAN=''; BOLD=''; NC=''
fi

ok()   { printf "  ${GREEN}✅  %-38s${NC} %s\n" "$1" "${2:-}"; }
fail() { printf "  ${RED}❌  %-38s${NC} %s\n" "$1" "${2:-}"; FAILED=1; }
warn() { printf "  ${YELLOW}⚠️   %-38s${NC} %s\n" "$1" "${2:-}"; }
info() { printf "  ${CYAN}ℹ️   %-38s${NC} %s\n" "$1" "${2:-}"; }
hdr()  { echo ""; printf "${BOLD}${CYAN}── %s ──────────────────────────────────────${NC}\n" "$1"; }

FAILED=0

# ── Configuration ────────────────────────────────────────────────────────────
# unified_launcher 默认端口为 8299（非旧版 9000）
BASE_URL="${GALAXY_API_BASE:-http://localhost:8299}"
NODE71_URL="${GALAXY_NODE71_URL:-http://localhost:8071}"
NATS_HOST="${GALAXY_NATS_HOST:-localhost}"
NATS_PORT="${GALAXY_NATS_PORT:-4222}"
NATS_URL="${GALAXY_NATS_URL:-nats://${NATS_HOST}:${NATS_PORT}}"
NATS_ENV_SET="${GALAXY_NATS_URL:-}"

# ── Banner ───────────────────────────────────────────────────────────────────
echo ""
printf "${BOLD}== Galaxy Health Check ==${NC}\n"
info "Launcher URL"    "$BASE_URL"
info "Node_71"         "$NODE71_URL"
info "NATS"            "$NATS_URL"
echo ""

# ── NATS 默认策略提示 ─────────────────────────────────────────────────────────
if [ -z "$NATS_ENV_SET" ]; then
    LAN_IP=$(python3 -c "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(('8.8.8.8',80)); print(s.getsockname()[0]); s.close()" 2>/dev/null || true)
    warn "GALAXY_NATS_URL" "未设置 — 默认使用 nats://localhost:4222 (单机开发模式)"
    if [ -n "$LAN_IP" ]; then
        info "跨设备提示" "设置 GALAXY_NATS_URL=nats://${LAN_IP}:4222 可让局域网设备接入"
    fi
    echo ""
fi

# ── Port probe helper ────────────────────────────────────────────────────────
_port_open() {
    local host="$1" port="$2"
    if command -v nc &>/dev/null; then
        nc -z "$host" "$port" 2>/dev/null
    elif (echo >/dev/tcp/"$host"/"$port") 2>/dev/null; then
        return 0
    elif command -v python3 &>/dev/null; then
        python3 -c "import socket; socket.create_connection(('$host',$port),2).close()" 2>/dev/null
    else
        return 1
    fi
}

# ── 1. NATS port (required) ──────────────────────────────────────────────────
hdr "NATS (必需)"
if _port_open "$NATS_HOST" "$NATS_PORT"; then
    ok "NATS port ${NATS_PORT}" "监听中"
else
    fail "NATS port ${NATS_PORT}" "未监听 — 请启动 NATS: nats-server -p ${NATS_PORT}"
fi

# ── 2. Key ports ─────────────────────────────────────────────────────────────
hdr "关键端口"
for PORT_LABEL in "8299:UnifiedLauncher" "8071:Node_71" "4222:NATS"; do
    PORT="${PORT_LABEL%%:*}"
    LABEL="${PORT_LABEL##*:}"
    if _port_open localhost "$PORT"; then
        ok "端口 ${PORT} (${LABEL})" "已监听"
    else
        warn "端口 ${PORT} (${LABEL})" "未监听"
    fi
done

# ── 3. Gateway / Core health ─────────────────────────────────────────────────
hdr "Unified Launcher / Core"
_http_check() {
    local url="$1" label="$2"
    local code
    if command -v curl &>/dev/null; then
        code=$(curl -o /dev/null -s -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || echo "000")
    elif command -v wget &>/dev/null; then
        code=$(wget -q --timeout=5 --server-response -O /dev/null "$url" 2>&1 | awk '/HTTP\//{print $2}' | tail -1)
        code="${code:-000}"
    elif command -v python3 &>/dev/null; then
        code=$(python3 -c "
import urllib.request, sys
try:
    r=urllib.request.urlopen('$url', timeout=5)
    print(r.getcode())
except Exception as e:
    c=getattr(getattr(e,'code',None),'real',None) or getattr(e,'code',None)
    print(c if c else '000')
" 2>/dev/null || echo "000")
    else
        warn "$label" "无法检查 — 需要 curl、wget 或 python3"
        return
    fi
    if [[ "$code" =~ ^2 ]]; then
        ok "$label" "HTTP $code"
    else
        fail "$label" "HTTP $code (expected 2xx)"
    fi
}

_http_check "${BASE_URL}/health"                         "GET /health"
_http_check "${BASE_URL}/api/v1/system/info"             "GET /api/v1/system/info"
_http_check "${BASE_URL}/api/v1/observability/live-status" "GET /api/v1/observability/live-status" 2>/dev/null || warn "GET /api/v1/observability/live-status" "endpoint may not exist"

# NATS status via API
if command -v curl &>/dev/null; then
    NATS_API=$(curl -o /dev/null -s -w "%{http_code}" --max-time 5 "${BASE_URL}/health/nats" 2>/dev/null || echo "000")
    if [[ "$NATS_API" =~ ^2 ]]; then
        ok "GET /health/nats" "HTTP $NATS_API"
        # Show NATS status detail
        NATS_BODY=$(curl -s --max-time 5 "${BASE_URL}/health/nats" 2>/dev/null || echo "{}")
        NATS_STATUS=$(echo "$NATS_BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unknown")
        if [ "$NATS_STATUS" = "connected" ]; then
            ok "NATS status" "connected (mainline active)"
        else
            fail "NATS status" "$NATS_STATUS — NATS is required but not connected"
        fi
    else
        warn "GET /health/nats" "HTTP $NATS_API"
    fi
fi

# ── 4. Node_71 health ────────────────────────────────────────────────────────
hdr "Node_71 (多设备协调主线)"
_http_check "${NODE71_URL}/health" "GET Node_71 /health"

# ── 5. Docker containers (best-effort) ──────────────────────────────────────
if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    hdr "Docker 容器状态"
    CONTAINERS=$(docker ps --filter "name=nats" \
                            --filter "name=gateway" \
                            --filter "name=node_71" \
                            --filter "name=galaxy" \
                            --format "{{.Names}}\t{{.Status}}" 2>/dev/null || true)
    if [ -n "$CONTAINERS" ]; then
        while IFS=$'\t' read -r name status; do
            if echo "$status" | grep -q "^Up"; then
                ok "$name" "$status"
            else
                warn "$name" "$status"
            fi
        done <<< "$CONTAINERS"
    else
        info "Docker 容器" "未发现相关容器"
    fi
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
if [ "$FAILED" -eq 0 ]; then
    printf "${GREEN}${BOLD}✅  所有检查通过${NC}\n"
    echo ""
    exit 0
else
    printf "${RED}${BOLD}❌  部分检查失败，请查看上方诊断信息${NC}\n"
    echo ""
    printf "${YELLOW}常见修复方法:${NC}\n"
    echo "  1. 启动 NATS:       nats-server -p 4222"
    echo "  2. 安装 NATS:       Linux: apt install nats-server"
    echo "                      macOS: brew install nats-server"
    echo "  3. Docker 启动 NATS: docker run -d --rm -p 4222:4222 nats:latest"
    echo "  4. 检查端口占用:    lsof -i :4222 | lsof -i :8299"
    echo "  5. 完整部署指南:    docs/DEPLOYMENT_COMPLETE.md"
    echo "  6. 故障排查手册:    docs/TROUBLESHOOTING.md"
    echo ""
    exit 1
fi
