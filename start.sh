#!/bin/bash
#
# Galaxy - Bootstrap Launcher Script (Adapter/Launcher Role)
# ===========================================================
#
# This script is a BOOTSTRAP LAUNCHER only — not a subject entrypoint.
# The subject lifecycle is owned by DesktopPresenceRuntime (shell) +
# OpenClawd (core).  This script starts the process environment and
# delegates to unified_launcher.py / main.py.
#
# Galaxy - L4 Autonomous Intelligence System
# 一键启动脚本 (Linux/Mac)
#

set -e

# 颜色定义 (ANSI 支持检测)
if [ -t 1 ] && [ "${TERM:-dumb}" != "dumb" ]; then
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    PURPLE='\033[0;35m'
    PINK='\033[0;95m'
    RED='\033[0;31m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    GREEN=''; YELLOW=''; BLUE=''; CYAN=''; PURPLE=''; PINK=''; RED=''; BOLD=''; NC=''
fi

# 24-bit true-color per-character gradient banner helper
# Anchors: aurora cyan → tech blue → indigo → neon purple → cyber pink
_print_gradient_line() {
    local line="$1"
    local len=${#line}
    local width=60
    printf '\033[1m'
    local i=0
    while [ $i -lt $len ]; do
        local char="${line:$i:1}"
        local t=0
        [ $width -gt 1 ] && t=$(( i * 1000 / (width - 1) ))
        # Inline interpolation across 4 segments (5 anchors)
        local seg=$(( t * 4 / 1000 ))
        [ $seg -ge 4 ] && seg=3
        local frac=$(( t * 4 - seg * 1000 ))
        local r1 g1 b1 r2 g2 b2
        case $seg in
            0) r1=0;   g1=225; b1=253; r2=41;  g2=156; b2=255 ;;
            1) r1=41;  g1=156; b1=255; r2=109; g2=92;  b2=255 ;;
            2) r1=109; g1=92;  b1=255; r2=184; g2=61;  b2=245 ;;
            3) r1=184; g1=61;  b1=245; r2=255; g2=46;  b2=147 ;;
        esac
        local r=$(( r1 + (r2 - r1) * frac / 1000 ))
        local g=$(( g1 + (g2 - g1) * frac / 1000 ))
        local b=$(( b1 + (b2 - b1) * frac / 1000 ))
        printf "\033[38;2;%d;%d;%dm%s" $r $g $b "$char"
        i=$(( i + 1 ))
    done
    printf '\033[0m\n'
}

# 打印横幅 (24-bit true-color 平滑左→右渐变: aurora cyan→cyber pink)
print_banner() {
    echo ""
    if [ -n "$BOLD" ]; then
        _print_gradient_line "╔══════════════════════════════════════════════════════════╗"
        _print_gradient_line "║                                                          ║"
        _print_gradient_line "║   ██████╗  █████╗ ██╗      █████╗ ██╗  ██╗██╗   ██╗    ║"
        _print_gradient_line "║  ██╔════╝ ██╔══██╗██║     ██╔══██╗╚██╗██╔╝╚██╗ ██╔╝    ║"
        _print_gradient_line "║  ██║  ███╗███████║██║     ███████║ ╚███╔╝  ╚████╔╝      ║"
        _print_gradient_line "║  ██║   ██║██╔══██║██║     ██╔══██║ ██╔██╗   ╚██╔╝       ║"
        _print_gradient_line "║  ╚██████╔╝██║  ██║███████╗██║  ██║██╔╝ ██╗   ██║        ║"
        _print_gradient_line "║   ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝        ║"
        _print_gradient_line "║                                                          ║"
        _print_gradient_line "║     L4 Autonomous Intelligence System   v2.3.21          ║"
        _print_gradient_line "║                                                          ║"
        _print_gradient_line "╚══════════════════════════════════════════════════════════╝"
    else
        echo "╔══════════════════════════════════════════════════════════╗"
        echo "║                                                          ║"
        echo "║   ██████╗  █████╗ ██╗      █████╗ ██╗  ██╗██╗   ██╗    ║"
        echo "║  ██╔════╝ ██╔══██╗██║     ██╔══██╗╚██╗██╔╝╚██╗ ██╔╝    ║"
        echo "║  ██║  ███╗███████║██║     ███████║ ╚███╔╝  ╚████╔╝      ║"
        echo "║  ██║   ██║██╔══██║██║     ██╔══██║ ██╔██╗   ╚██╔╝       ║"
        echo "║  ╚██████╔╝██║  ██║███████╗██║  ██║██╔╝ ██╗   ██║        ║"
        echo "║   ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝        ║"
        echo "║                                                          ║"
        echo "║     L4 Autonomous Intelligence System   v2.3.21          ║"
        echo "║                                                          ║"
        echo "╚══════════════════════════════════════════════════════════╝"
    fi
    echo ""
}

# 打印状态行 (对齐格式)
print_status() {
    local status=$1
    local message=$2
    local value=${3:-}
    case $status in
        "success") printf "  ${GREEN}✅  %-28s${NC} %s\n" "$message" "$value" ;;
        "warning") printf "  ${YELLOW}⚠️   %-28s${NC} %s\n" "$message" "$value" ;;
        "error")   printf "  ${RED}❌  %-28s${NC} %s\n"   "$message" "$value" ;;
        "loading") printf "  ${CYAN}⏳  %-28s${NC} %s\n"  "$message" "$value" ;;
        "step")    printf "  ${CYAN}▶   %-28s${NC} %s\n"  "$message" "$value" ;;
        *)         printf "  ${BLUE}ℹ️   %-28s${NC} %s\n"  "$message" "$value" ;;
    esac
}

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

print_banner

# 检查 Python
if ! command -v python3 &> /dev/null; then
    print_status "error" "Python3 未安装" "请先安装 Python 3.9+"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
print_status "success" "Python" "$PYTHON_VERSION"

# 检查 Tailscale
if command -v tailscale &> /dev/null; then
    TS_STATUS=$(tailscale status --json 2>/dev/null || echo "error")
    if [[ "$TS_STATUS" == "error" ]]; then
        print_status "warning" "Tailscale" "已安装但未运行 (建议: sudo tailscale up)"
    else
        TS_IP=$(tailscale ip -4 2>/dev/null)
        print_status "success" "Tailscale" "已就绪 (IP: $TS_IP)"
    fi
else
    print_status "warning" "Tailscale" "未检测到 (建议安装以支持远程访问)"
    print_status "info" "安装命令" "curl -fsSL https://tailscale.com/install.sh | sh"
fi

# 检查是否首次运行
if [ ! -f ".env" ]; then
    echo ""
    print_status "info" "首次运行" "启动配置向导..."
    echo ""
    python3 setup_wizard.py || print_status "warning" "配置向导" "未完成，将使用默认配置"
fi

# 创建虚拟环境
if [ ! -d "venv" ]; then
    print_status "loading" "虚拟环境" "创建中..."
    python3 -m venv venv
fi

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
print_status "loading" "依赖检查" "安装中..."
pip install -q -r requirements.txt || { print_status "error" "依赖安装" "失败"; exit 1; }

# ── 自动启动 NATS（强依赖）──────────────────────────────────────────────────
echo ""
print_status "step" "NATS" "启动中 (必需)..."
NATS_PORT="${GALAXY_NATS_PORT:-4222}"
NATS_URL="${GALAXY_NATS_URL:-nats://localhost:$NATS_PORT}"
export GALAXY_NATS_URL="$NATS_URL"

# Port probe helper: try nc, then bash /dev/tcp, then python3
_port_open() {
    local host="$1" port="$2"
    if command -v nc &>/dev/null; then
        nc -z "$host" "$port" 2>/dev/null
    elif (echo >/dev/tcp/"$host"/"$port") 2>/dev/null; then
        return 0
    elif command -v python3 &>/dev/null; then
        python3 -c "import socket; s=socket.create_connection(('$host',$port),2); s.close()" 2>/dev/null
    else
        return 1
    fi
}

_nats_running=false
if command -v nats-server &>/dev/null; then
    # Check if NATS is already running
    if ! _port_open localhost "$NATS_PORT"; then
        nats-server -p "$NATS_PORT" &
        NATS_PID=$!
        sleep 2
        if _port_open localhost "$NATS_PORT"; then
            print_status "success" "NATS" "已启动 (PID=$NATS_PID, port=$NATS_PORT)"
            _nats_running=true
        else
            print_status "error" "NATS" "启动失败 — 请检查 nats-server 日志"
            print_status "error" "诊断" "运行: bash scripts/health_check.sh"
            exit 1
        fi
    else
        print_status "success" "NATS" "已在运行 (port=$NATS_PORT)"
        _nats_running=true
    fi
elif command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    # Fallback: start NATS via Docker
    if ! _port_open localhost "$NATS_PORT"; then
        docker run -d --name galaxy-nats --rm -p "${NATS_PORT}:4222" nats:latest >/dev/null 2>&1 && {
            sleep 2
            if _port_open localhost "$NATS_PORT"; then
                print_status "success" "NATS" "已通过 Docker 启动 (port=$NATS_PORT)"
                _nats_running=true
            else
                print_status "error" "NATS" "Docker 启动失败"
                print_status "error" "诊断" "运行: bash scripts/health_check.sh"
                exit 1
            fi
        } || {
            print_status "error" "NATS" "Docker 启动失败"
            exit 1
        }
    else
        print_status "success" "NATS" "已在运行 (port=$NATS_PORT)"
        _nats_running=true
    fi
else
    print_status "error" "NATS" "未找到 nats-server 或 docker，无法启动 NATS"
    print_status "error" "安装" "Linux: apt install nats-server  或  brew install nats-server (macOS)"
    print_status "error" "说明" "NATS 是必需的内部调度主线，缺少它系统无法启动"
    exit 1
fi

# 启动系统
echo ""
print_status "step" "Galaxy" "启动中..."
print_status "info" "控制面板" "http://localhost:${WEB_UI_PORT:-8299}"
print_status "info" "API 文档" "http://localhost:${WEB_UI_PORT:-8299}/docs"
print_status "info" "健康检查" "http://localhost:${WEB_UI_PORT:-8299}/api/health"
print_status "info" "NATS" "$NATS_URL (必需)"
echo ""
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
python3 unified_launcher.py "$@"

# 退出
deactivate
