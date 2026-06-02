#!/usr/bin/env bash
# start.sh — Galaxy AI System Launcher (Linux/Mac)
# ================================================
# Unified wrapper: delegates everything to main.py

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERR]${NC}   $*"; }

# Check Python
if ! command -v python3 &>/dev/null; then
    err "Python 3 not found. Please install Python 3.10+"
    exit 1
fi

# Check/create venv
if [[ ! -d ".venv" ]]; then
    info "Creating virtual environment (.venv)..."
    python3 -m venv .venv
fi
source .venv/bin/activate

# Check .env
if [[ ! -f ".env" ]]; then
    warn ".env not found — launching setup wizard"
    python main.py --setup
    exit 0
fi

# Delegate to main.py (unified entrypoint)
python main.py "$@"
