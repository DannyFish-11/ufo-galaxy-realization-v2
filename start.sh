#!/usr/bin/env bash
# start.sh — Galaxy AI System One-Click Launcher
# ==============================================
# Starts the Galaxy backend + Electron frontend.
# Run: ./start.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERR]${NC}   $*"; }

# ── Check virtual environment ──
if [[ ! -d ".venv" ]]; then
    err "Virtual environment not found. Run ./install.sh first."
    exit 1
fi

source .venv/bin/activate

# ── Check .env ──
if [[ ! -f ".env" ]]; then
    warn ".env not found — creating with defaults"
    ./install.sh
fi

# ── Print banner ──
echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║   Galaxy AI System — Starting            ║"
echo "  ║   中心式多相对主体分布式AI系统            ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# ── Start backend ──
info "Starting Galaxy backend..."

# Check if already running
if pgrep -f "python.*galaxy_gateway" > /dev/null 2>&1; then
    warn "Galaxy backend already running"
else
    python3 -m galaxy_gateway.main &
    BACKEND_PID=$!
    sleep 2
    if kill -0 $BACKEND_PID 2>/dev/null; then
        ok "Backend started (PID: $BACKEND_PID)"
        echo $BACKEND_PID > .backend.pid
    else
        err "Backend failed to start"
        exit 1
    fi
fi

# ── Start Electron (if available) ──
if [[ -d "electron" ]] && command -v npm &>/dev/null; then
    info "Starting Electron frontend..."
    cd electron
    if [[ ! -d "node_modules" ]]; then
        warn "Electron dependencies not installed. Run: cd electron && npm install"
    else
        npm start &
        FRONTEND_PID=$!
        cd "$SCRIPT_DIR"
        sleep 3
        if kill -0 $FRONTEND_PID 2>/dev/null; then
            ok "Electron started (PID: $FRONTEND_PID)"
            echo $FRONTEND_PID > .frontend.pid
        else
            warn "Electron failed to start (check electron/npm start manually)"
        fi
    fi
else
    warn "Electron frontend not available — backend-only mode"
fi

echo ""
ok "Galaxy AI System is running!"
echo ""
echo "  📡 Backend: http://localhost:8765"
echo "  📱 WebSocket: ws://localhost:8765/ws"
echo "  📊 API Docs: http://localhost:8765/docs"
echo ""
echo "  🛑 Stop: ./stop.sh"
echo ""
