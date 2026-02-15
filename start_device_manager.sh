#!/bin/bash
#
# UFO Galaxy - 设备管理界面启动脚本
#

echo "========================================"
echo "  UFO Galaxy 设备管理界面"
echo "========================================"
echo ""

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "错误: Python3 未安装"
    exit 1
fi

# 设置端口
PORT=${1:-8080}

echo "启动设备管理服务..."
echo ""
echo "访问地址: http://localhost:$PORT"
echo "API 文档: http://localhost:$PORT/docs"
echo ""
echo "按 Ctrl+C 停止"
echo ""

# 启动服务
python3 -c "
import sys
sys.path.insert(0, '.')

from galaxy_gateway.device_manager_service import run_server
run_server(port=$PORT)
"
