#!/bin/bash
#
# Galaxy V2 - 一键部署脚本
# ================================
# 
# 使用方法:
#   chmod +x deploy.sh
#   ./deploy.sh
#

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# 打印横幅
print_banner() {
    echo -e "${CYAN}"
    echo "  ╔═══════════════════════════════════════════════════════════╗"
    echo "  ║                                                           ║"
    echo "  ║              Galaxy V2 一键部署                       ║"
    echo "  ║              L4 级自主性智能系统                          ║"
    echo "  ║                                                           ║"
    echo "  ╚═══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

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

# ============================================
# 步骤 1: 检查 Python
# ============================================
print_status "info" "步骤 1/8: 检查 Python 环境..."

if ! command -v python3 &> /dev/null; then
    print_status "error" "未检测到 Python3，请先安装 Python 3.10+"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
print_status "success" "Python 版本: $PYTHON_VERSION"

# ============================================
# 步骤 2: 创建虚拟环境
# ============================================
print_status "info" "步骤 2/8: 创建虚拟环境..."

if [ ! -d "venv" ]; then
    python3 -m venv venv
    print_status "success" "虚拟环境创建完成"
else
    print_status "info" "虚拟环境已存在"
fi

# 激活虚拟环境
source venv/bin/activate

# ============================================
# 步骤 3: 升级 pip
# ============================================
print_status "info" "步骤 3/8: 升级 pip..."
pip install --upgrade pip -q

# ============================================
# 步骤 4: 安装依赖
# ============================================
print_status "info" "步骤 4/8: 安装依赖..."

if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt -q 2>/dev/null || pip install -r requirements.txt
    print_status "success" "依赖安装完成"
else
    print_status "error" "未找到 requirements.txt"
    exit 1
fi

# ============================================
# 步骤 5: 创建配置文件
# ============================================
print_status "info" "步骤 5/8: 创建配置文件..."

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        print_status "success" ".env 文件已创建"
        print_status "warning" "请编辑 .env 文件配置您的 API Key"
    else
        print_status "error" "未找到 .env.example"
        exit 1
    fi
else
    print_status "info" ".env 文件已存在"
fi

# 创建必要的目录
mkdir -p logs data models cache

# ============================================
# 步骤 6: 验证安装
# ============================================
print_status "info" "步骤 6/8: 验证安装..."

python3 -c "
import sys
sys.path.insert(0, '.')

errors = []

# 测试核心模块
try:
    from core.node_registry import NodeRegistry
    print('  ✅ NodeRegistry')
except Exception as e:
    errors.append(str(e))
    print(f'  ❌ NodeRegistry: {e}')

try:
    from core.node_communication import UniversalCommunicator
    print('  ✅ UniversalCommunicator')
except Exception as e:
    errors.append(str(e))
    print(f'  ❌ UniversalCommunicator: {e}')

try:
    from core.safe_eval import SafeEval
    print('  ✅ SafeEval')
except Exception as e:
    errors.append(str(e))
    print(f'  ❌ SafeEval: {e}')

try:
    from core.secure_config import SecureConfig
    print('  ✅ SecureConfig')
except Exception as e:
    errors.append(str(e))
    print(f'  ❌ SecureConfig: {e}')

try:
    from fastapi import FastAPI
    print('  ✅ FastAPI')
except Exception as e:
    errors.append(str(e))
    print(f'  ❌ FastAPI: {e}')

if errors:
    print(f'\n发现 {len(errors)} 个错误')
    sys.exit(1)
else:
    print('\n所有核心模块验证通过!')
"

if [ $? -ne 0 ]; then
    print_status "error" "验证失败，请检查错误信息"
    exit 1
fi

# ============================================
# 步骤 7: 检查配置
# ============================================
print_status "info" "步骤 7/8: 检查配置..."

# 检查是否配置了 API Key
if grep -q "your-openai-api-key-here" .env 2>/dev/null; then
    print_status "warning" "API Key 尚未配置，请编辑 .env 文件"
    print_status "info" "至少需要配置一个 LLM API Key (OpenAI/DeepSeek/Anthropic)"
else
    print_status "success" "配置文件已就绪"
fi

# ============================================
# 步骤 8: 完成
# ============================================
print_status "info" "步骤 8/8: 部署完成!"

echo ""
print_status "success" "================================"
print_status "success" "Galaxy V2 部署完成!"
print_status "success" "================================"
echo ""
print_status "info" "下一步操作:"
echo "  1. 编辑 .env 文件配置 API Key"
echo "     nano .env"
echo ""
echo "  2. 启动系统"
echo "     source venv/bin/activate"
echo "     python main.py --minimal"
echo ""
echo "  3. 访问控制面板"
echo "     http://localhost:8080"
echo ""

# 退出虚拟环境
deactivate
