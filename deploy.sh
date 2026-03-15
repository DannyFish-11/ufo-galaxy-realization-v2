#!/bin/bash
# ============================================================
# Galaxy — Production Deployment Script
# ============================================================

set -euo pipefail

# ── Colors ──
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
ok()      { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()     { echo -e "${RED}[ERROR]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COMPOSE_FILE="docker-compose.production.yml"

# ── Pre-flight checks ──
preflight() {
    info "Pre-flight checks..."

    # Docker
    if ! command -v docker &>/dev/null; then
        err "Docker not installed. Install: https://docs.docker.com/get-docker/"
        exit 1
    fi

    # Docker Compose (v2 plugin or standalone)
    if docker compose version &>/dev/null; then
        COMPOSE_CMD="docker compose"
    elif command -v docker-compose &>/dev/null; then
        COMPOSE_CMD="docker-compose"
    else
        err "Docker Compose not found."
        exit 1
    fi

    # Python (for local mode)
    if command -v python3 &>/dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &>/dev/null; then
        PYTHON_CMD="python"
    else
        PYTHON_CMD=""
    fi

    ok "Docker: $(docker --version | head -c 60)"
    ok "Compose: $COMPOSE_CMD"
}

# ── Environment setup ──
setup_env() {
    if [ ! -f ".env" ]; then
        if [ -f ".env.example" ]; then
            cp .env.example .env
            warn "Created .env from .env.example — edit it with your API keys:"
            warn "  nano $SCRIPT_DIR/.env"
            exit 1
        else
            err ".env.example not found"
            exit 1
        fi
    fi
    ok ".env loaded"
}

# ── Create directories ──
setup_dirs() {
    mkdir -p data logs config
    ok "Directories ready"
}

# ── Deploy with Docker Compose ──
deploy_docker() {
    local target="${1:-all}"

    preflight
    setup_env
    setup_dirs

    case "$target" in
        all)
            info "Deploying full stack..."
            $COMPOSE_CMD -f "$COMPOSE_FILE" up -d --build
            ;;
        galaxy)
            info "Deploying Galaxy core only..."
            $COMPOSE_CMD -f "$COMPOSE_FILE" up -d --build galaxy
            ;;
        monitoring)
            info "Deploying monitoring stack..."
            $COMPOSE_CMD -f "$COMPOSE_FILE" up -d prometheus grafana fluent-bit
            ;;
        gateway)
            info "Deploying gateway..."
            $COMPOSE_CMD -f "$COMPOSE_FILE" up -d --build gateway
            ;;
    esac

    ok "Deployment complete"
    sleep 3
    health_check
}

# ── Local mode (no Docker) ──
deploy_local() {
    info "Starting Galaxy in local mode (no Docker)..."

    if [ -z "${PYTHON_CMD:-}" ]; then
        preflight
        if [ -z "${PYTHON_CMD:-}" ]; then
            err "Python3 not found"
            exit 1
        fi
    fi

    # Check venv
    if [ ! -d "venv" ]; then
        info "Creating virtual environment..."
        $PYTHON_CMD -m venv venv
    fi

    source venv/bin/activate 2>/dev/null || . venv/bin/activate

    info "Installing dependencies..."
    pip install -q -r requirements.txt

    info "Starting Galaxy on port ${GALAXY_PORT:-9000}..."
    $PYTHON_CMD unified_launcher.py --host 0.0.0.0 --port "${GALAXY_PORT:-9000}"
}

# ── Health check ──
health_check() {
    info "Health check..."

    # In local (non-Docker) mode, unified_launcher is the single process serving
    # both the Galaxy API and gateway on port 9000. Checking both "galaxy" and
    # "gateway" on the same port is intentional: they are the same endpoint.
    local services=("galaxy:9000" "gateway:9000")
    for svc in "${services[@]}"; do
        local name="${svc%%:*}"
        local port="${svc##*:}"
        if curl -sf "http://localhost:$port/health" &>/dev/null || \
           curl -sf "http://localhost:$port/health/live" &>/dev/null; then
            ok "$name (port $port) — healthy"
        else
            warn "$name (port $port) — not responding (may still be starting)"
        fi
    done

    # Prometheus
    if curl -sf "http://localhost:9090/-/healthy" &>/dev/null; then
        ok "Prometheus (port 9090) — healthy"
    fi

    # Grafana
    if curl -sf "http://localhost:3000/api/health" &>/dev/null; then
        ok "Grafana (port 3000) — healthy"
    fi
}

# ── Status ──
show_status() {
    preflight
    $COMPOSE_CMD -f "$COMPOSE_FILE" ps
}

# ── Logs ──
show_logs() {
    preflight
    $COMPOSE_CMD -f "$COMPOSE_FILE" logs -f --tail=100 "${1:-galaxy}"
}

# ── Stop ──
stop() {
    preflight
    info "Stopping services..."
    $COMPOSE_CMD -f "$COMPOSE_FILE" down
    ok "All services stopped"
}

# ── Systemd install ──
install_systemd() {
    if [ "$(id -u)" -ne 0 ]; then
        err "Run with sudo for systemd installation"
        exit 1
    fi

    local INSTALL_DIR="${1:-/opt/galaxy}"
    info "Installing systemd service (install dir: $INSTALL_DIR)..."

    # Create system user
    if ! id -u galaxy &>/dev/null; then
        useradd -r -m -s /bin/bash galaxy
        ok "Created system user: galaxy"
    fi

    # Copy files
    mkdir -p "$INSTALL_DIR"
    rsync -a --exclude='.git' --exclude='venv' --exclude='__pycache__' \
        "$SCRIPT_DIR/" "$INSTALL_DIR/"
    chown -R galaxy:galaxy "$INSTALL_DIR"

    # Generate service file
    cat > /etc/systemd/system/galaxy.service <<SVCEOF
[Unit]
Description=Galaxy L4 Autonomous Intelligence System
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=galaxy
Group=galaxy
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$INSTALL_DIR/.env
Environment=PYTHONPATH=$INSTALL_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 $INSTALL_DIR/unified_launcher.py --host 0.0.0.0 --port 9000
ExecReload=/bin/kill -HUP \$MAINPID
Restart=always
RestartSec=10
WatchdogSec=120

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$INSTALL_DIR/data $INSTALL_DIR/logs

StandardOutput=journal
StandardError=journal
SyslogIdentifier=galaxy

[Install]
WantedBy=multi-user.target
SVCEOF

    systemctl daemon-reload
    systemctl enable galaxy
    ok "Systemd service installed. Start with: systemctl start galaxy"
}

# ── Print access info ──
access_info() {
    echo ""
    echo -e "${CYAN}============================================================${NC}"
    echo -e "${CYAN}  Galaxy — Service Endpoints${NC}"
    echo -e "${CYAN}============================================================${NC}"
    echo ""
    echo -e "  ${GREEN}Galaxy API:${NC}      http://localhost:9000"
    echo -e "  ${GREEN}Gateway:${NC}         http://localhost:9000  (primary client entry)"
    echo -e "  ${GREEN}Dashboard:${NC}       http://localhost:9000  (served by Galaxy)"
    echo -e "  ${GREEN}Prometheus:${NC}      http://localhost:9090"
    echo -e "  ${GREEN}Grafana:${NC}         http://localhost:3000"
    echo ""
    echo -e "  ${BLUE}Health:${NC}          curl http://localhost:9000/health/live"
    echo -e "  ${BLUE}Logs:${NC}            ./deploy.sh logs [service]"
    echo -e "  ${BLUE}Status:${NC}          ./deploy.sh status"
    echo ""
}

# ── Help ──
show_help() {
    echo "Galaxy Deployment Script"
    echo ""
    echo "Usage: ./deploy.sh <command> [options]"
    echo ""
    echo "Docker commands:"
    echo "  up [target]       Deploy services (all|galaxy|monitoring|gateway)"
    echo "  stop              Stop all services"
    echo "  status            Show service status"
    echo "  logs [service]    Follow service logs (default: galaxy)"
    echo "  health            Run health checks"
    echo "  info              Show access endpoints"
    echo ""
    echo "Local commands:"
    echo "  local             Run Galaxy locally (no Docker)"
    echo ""
    echo "System commands:"
    echo "  install [dir]     Install as systemd service (requires sudo)"
    echo ""
    echo "Examples:"
    echo "  ./deploy.sh up                # Deploy full stack"
    echo "  ./deploy.sh up galaxy         # Deploy Galaxy only"
    echo "  ./deploy.sh local             # Run locally"
    echo "  sudo ./deploy.sh install      # Install as systemd service"
}

# ── Main ──
case "${1:-help}" in
    up|deploy|all)   deploy_docker "${2:-all}" && access_info ;;
    local)           deploy_local ;;
    stop|down)       stop ;;
    status|ps)       show_status ;;
    logs)            show_logs "${2:-}" ;;
    health)          preflight; health_check ;;
    info)            access_info ;;
    install)         install_systemd "${2:-/opt/galaxy}" ;;
    help|--help|-h)  show_help ;;
    *)               err "Unknown command: $1"; show_help; exit 1 ;;
esac
