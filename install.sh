#!/usr/bin/env bash
# install.sh — Galaxy AI System One-Click Installer
# =================================================
# This script automates the setup from a fresh clone to a runnable state.
# Run: ./install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

GALAXY_HOME="${HOME}/.galaxy"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERR]${NC}   $*"; }

print_banner() {
    echo ""
    echo "  ╔══════════════════════════════════════════╗"
    echo "  ║   Galaxy AI System — Installation        ║"
    echo "  ║   中心式多相对主体分布式AI系统            ║"
    echo "  ╚══════════════════════════════════════════╝"
    echo ""
}

# ── Phase 1: Environment Check ──
check_env() {
    info "Phase 1: Environment Check"

    # Python version
    PYTHON_VERSION=$(python3 --version 2>/dev/null | awk '{print $2}' || echo "")
    if [[ -z "$PYTHON_VERSION" ]]; then
        err "Python 3 not found. Please install Python 3.10+"
        exit 1
    fi
    ok "Python $PYTHON_VERSION"

    # Check Python >= 3.10
    PY_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
    if [[ "$PY_MAJOR" -lt 3 ]] || [[ "$PY_MINOR" -lt 10 ]]; then
        warn "Python $PYTHON_VERSION detected. Python 3.10+ recommended."
    fi

    # Git
    if command -v git &>/dev/null; then
        ok "Git $(git --version | awk '{print $3}')"
    else
        warn "Git not found (optional — needed for auto-update)"
    fi

    # Node.js (for Electron)
    if command -v node &>/dev/null; then
        ok "Node.js $(node --version)"
    else
        warn "Node.js not found — Electron frontend will not be available"
        warn "  Install: https://nodejs.org/"
    fi

    # Ollama (optional but recommended)
    if command -v ollama &>/dev/null; then
        ok "Ollama installed"
        OLLAMA_MODELS=$(ollama list 2>/dev/null | tail -n +2 | wc -l)
        info "  Models available: $OLLAMA_MODELS"
    else
        warn "Ollama not found — local model routing will use API fallback"
        warn "  Install: curl -fsSL https://ollama.com/install.sh | sh"
    fi

    # NATS (optional)
    if command -v nats-server &>/dev/null; then
        ok "NATS server installed"
    else
        warn "NATS server not found — will use built-in embedded server"
        warn "  Install: npm install -g nats-server"
    fi

    echo ""
}

# ── Phase 2: Install Python Dependencies ──
install_deps() {
    info "Phase 2: Installing Python Dependencies"

    if [[ ! -f "requirements.txt" ]]; then
        err "requirements.txt not found — are you in the project root?"
        exit 1
    fi

    # Create virtual environment if not exists
    if [[ ! -d ".venv" ]]; then
        info "Creating Python virtual environment (.venv)"
        python3 -m venv .venv
    fi

    source .venv/bin/activate

    info "Upgrading pip"
    pip install --quiet --upgrade pip

    info "Installing core dependencies (this may take a few minutes)"
    pip install --quiet -r requirements.txt

    ok "Python dependencies installed"

    # Optional: voice wake dependencies
    info "Checking voice wake dependencies (optional)"
    pip install --quiet pvporcupine webrtcvad faster-whisper pyaudio 2>/dev/null && \
        ok "Voice wake dependencies installed" || \
        warn "Voice wake dependencies skipped (microphone support unavailable)"

    echo ""
}

# ── Phase 3: Create .env ──
setup_env() {
    info "Phase 3: Configuration"

    if [[ -f ".env" ]]; then
        ok ".env already exists — skipping"
        echo ""
        return
    fi

    # Auto-detect services
    NATS_URL="nats://localhost:4222"
    OLLAMA_URL="http://localhost:11434"

    # Test NATS connectivity
    if command -v nc &>/dev/null && nc -z localhost 4222 2>/dev/null; then
        ok "NATS detected at localhost:4222"
    else
        warn "NATS not detected — will use embedded server"
        NATS_URL="nats://127.0.0.1:4222"
    fi

    # Test Ollama
    if curl -s "$OLLAMA_URL/api/tags" &>/dev/null; then
        ok "Ollama detected at $OLLAMA_URL"
        MODELS=$(curl -s "$OLLAMA_URL/api/tags" | python3 -c "import sys,json; [print(m['name']) for m in json.load(sys.stdin)['models'][:5]]" 2>/dev/null)
        if [[ -n "$MODELS" ]]; then
            info "  Available models:"
            echo "$MODELS" | sed 's/^/    - /'
        fi
    else
        warn "Ollama not detected — LLM routing will use API fallback"
        OLLAMA_URL=""
    fi

    # Write .env
    cat > .env <<EOF
# Galaxy AI System — Auto-generated Configuration
# Edit as needed after installation

# ── Core ──
GALAXY_ENV=development
GALAXY_LOG_LEVEL=INFO
GALAXY_DATA_DIR=${GALAXY_HOME}

# ── Network ──
GALAXY_HOST=0.0.0.0
GALAXY_PORT=8765
NATS_URL=${NATS_URL}
NATS_ENABLED=true

# ── AI Models ──
OLLAMA_ENABLED=${OLLAMA_URL:+true}${OLLAMA_URL:-false}
OLLAMA_URL=${OLLAMA_URL}
OLLAMA_MODEL=gemma4:4b
OLLAMA_PRIORITY=1

# API fallback (if Ollama unavailable)
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# ── Electron ──
ELECTRON_START=true

# ── Security ──
GALAXY_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
EOF

    ok ".env created with auto-detected defaults"
    info "  Edit .env to customize settings"
    echo ""
}

# ── Phase 4: Create Data Directory ──
setup_data_dir() {
    info "Phase 4: Data Directory"

    mkdir -p "${GALAXY_HOME}"
    mkdir -p "${GALAXY_HOME}/logs"
    mkdir -p "${GALAXY_HOME}/data"
    mkdir -p "${GALAXY_HOME}/nodes_cache"

    ok "Data directory: ${GALAXY_HOME}"
    echo ""
}

# ── Phase 5: Verify ──
verify() {
    info "Phase 5: Verification"

    source .venv/bin/activate

    # Test critical imports
    python3 -c "
from core.schemas.aip_v3 import MsgType, TaskAssignMsg
from core.nats_bus import NATSBus
from core.unified.device_manager import UnifiedDeviceManager
from core.multi_llm_router import MultiLLMRouter
print('  ✅ Core modules import successful')
" 2>/dev/null && ok "Core modules import test passed" || warn "Some imports failed (may need manual config)"

    # Count modules
    MODULE_COUNT=$(find . -name "*.py" -type f | grep -v __pycache__ | grep -v external | grep -v .venv | wc -l)
    NODE_COUNT=$(ls nodes/ 2>/dev/null | wc -l)

    echo ""
    ok "Installation complete!"
    echo ""
    echo "  📊 System Overview:"
    echo "     Python modules: ${MODULE_COUNT}"
    echo "     Device nodes:   ${NODE_COUNT}"
    echo "     Config:         ${GALAXY_HOME}/"
    echo ""
    echo "  🚀 Next step: ./start.sh"
    echo ""
}

# ── Main ──
main() {
    print_banner
    check_env
    install_deps
    setup_env
    setup_data_dir
    verify
}

main "$@"
