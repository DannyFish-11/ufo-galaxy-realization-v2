#!/bin/bash
#
# UFO Galaxy V2 - 快速启动脚本
#

set -e

# 颜色定义
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
echo "  UFO Galaxy V2 - 启动中..."
echo -e "${NC}"

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "虚拟环境不存在，请先运行 ./deploy.sh"
    exit 1
fi

# 激活虚拟环境
source venv/bin/activate

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo "配置文件不存在，请先运行 ./deploy.sh"
    exit 1
fi

# 设置环境变量
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

# 启动系统
echo -e "${GREEN}启动 UFO Galaxy V2...${NC}"
echo ""
echo "控制面板: http://localhost:8080"
echo "API 文档: http://localhost:8080/docs"
echo "健康检查: http://localhost:8080/health"
echo ""
echo "按 Ctrl+C 停止"
echo ""

# 启动主程序
python3 main.py "$@"

# 退出虚拟环境
deactivate
