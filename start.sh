#!/bin/bash
#
# UFO Galaxy - L4 级自主性智能系统
# 一键启动脚本 (Linux/Mac)
#

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 打印横幅
print_banner() {
    echo -e "${CYAN}"
    echo "  ╔═══════════════════════════════════════════════════════════╗"
    echo "  ║                                                           ║"
    echo "  ║              UFO Galaxy 启动器                            ║"
    echo "  ║              L4 级自主性智能系统                          ║"
    echo "  ║                                                           ║"
    echo "  ╚═══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# 打印状态
print_status() {
    local status=$1
    local message=$2
    case $status in
        "info")    echo -e "${BLUE}[信息]${NC} $message" ;;
        "success") echo -e "${GREEN}[成功]${NC} $message" ;;
        "warning") echo -e "${YELLOW}[警告]${NC} $message" ;;
        "error")   echo -e "${RED}[错误]${NC} $message" ;;
    esac
}

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

print_banner

# 检查 Python
if ! command -v python3 &> /dev/null; then
    print_status "error" "未检测到 Python3，请先安装 Python 3.9+"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
print_status "info" "检测到 Python $PYTHON_VERSION"

# 检查是否首次运行
if [ ! -f ".env" ]; then
    echo ""
    print_status "info" "首次运行，启动配置向导..."
    echo ""
    python3 setup_wizard.py || print_status "warning" "配置向导未完成，将使用默认配置"
fi

# 创建虚拟环境
if [ ! -d "venv" ]; then
    print_status "info" "创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
print_status "info" "检查依赖..."
pip install -q -r requirements.txt 2>/dev/null || pip install -r requirements.txt

# 启动系统
echo ""
print_status "info" "启动 UFO Galaxy..."
echo ""
python3 main.py "$@"

# 退出
deactivate
