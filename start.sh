#!/bin/bash
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

# 打印横幅 (渐变: cyan→green→purple→blue→pink)
print_banner() {
    echo ""
    echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}${BOLD}║                                                          ║${NC}"
    echo -e "${GREEN}${BOLD}║   ██████╗  █████╗ ██╗      █████╗ ██╗  ██╗██╗   ██╗    ║${NC}"
    echo -e "${GREEN}${BOLD}║  ██╔════╝ ██╔══██╗██║     ██╔══██╗╚██╗██╔╝╚██╗ ██╔╝    ║${NC}"
    echo -e "${PURPLE}${BOLD}║  ██║  ███╗███████║██║     ███████║ ╚███╔╝  ╚████╔╝      ║${NC}"
    echo -e "${PURPLE}${BOLD}║  ██║   ██║██╔══██║██║     ██╔══██║ ██╔██╗   ╚██╔╝       ║${NC}"
    echo -e "${BLUE}${BOLD}║  ╚██████╔╝██║  ██║███████╗██║  ██║██╔╝ ██╗   ██║        ║${NC}"
    echo -e "${BLUE}${BOLD}║   ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝        ║${NC}"
    echo -e "${PINK}${BOLD}║                                                          ║${NC}"
    echo -e "${PINK}${BOLD}║     L4 Autonomous Intelligence System   v2.3.21          ║${NC}"
    echo -e "${PINK}${BOLD}║                                                          ║${NC}"
    echo -e "${PINK}${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
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

# 启动系统
echo ""
print_status "step" "Galaxy" "启动中..."
print_status "info" "控制面板" "http://localhost:${WEB_UI_PORT:-8085}"
print_status "info" "API 文档" "http://localhost:${WEB_UI_PORT:-8085}/docs"
print_status "info" "健康检查" "http://localhost:${WEB_UI_PORT:-8085}/api/health"
echo ""
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
python3 unified_launcher.py "$@"

# 退出
deactivate
