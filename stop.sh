#!/usr/bin/env bash
# stop.sh — Galaxy AI System Stop Script
# ======================================
# Stops all Galaxy processes.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }

info "Stopping Galaxy AI System..."

# Stop from PID files
if [[ -f .backend.pid ]]; then
    kill $(cat .backend.pid) 2>/dev/null && ok "Backend stopped" || true
    rm -f .backend.pid
fi

if [[ -f .frontend.pid ]]; then
    kill $(cat .frontend.pid) 2>/dev/null && ok "Electron stopped" || true
    rm -f .frontend.pid
fi

# Kill any remaining processes
pkill -f "python.*galaxy_gateway" 2>/dev/null && ok "Backend process killed" || true
pkill -f "electron.*galaxy" 2>/dev/null && ok "Electron process killed" || true

ok "All Galaxy processes stopped."
