#!/bin/bash
#
# UFO Galaxy V2 - 一键安装脚本
# 自动安装所有依赖并配置系统
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
    echo "  ║              UFO Galaxy V2 安装程序                       ║"
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

# 检查操作系统
OS=$(uname -s)
print_status "info" "检测到操作系统: $OS"

# 检查 Python
if ! command -v python3 &> /dev/null; then
    print_status "error" "未检测到 Python3"
    print_status "info" "请安装 Python 3.10 或更高版本"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
    print_status "error" "Python 版本过低: $PYTHON_VERSION"
    print_status "info" "需要 Python 3.10 或更高版本"
    exit 1
fi

print_status "success" "Python 版本: $PYTHON_VERSION"

# 检查 pip
if ! command -v pip3 &> /dev/null; then
    print_status "error" "未检测到 pip3"
    exit 1
fi

# 创建虚拟环境
if [ ! -d "venv" ]; then
    print_status "info" "创建虚拟环境..."
    python3 -m venv venv
    print_status "success" "虚拟环境创建完成"
else
    print_status "info" "虚拟环境已存在"
fi

# 激活虚拟环境
print_status "info" "激活虚拟环境..."
source venv/bin/activate

# 升级 pip
print_status "info" "升级 pip..."
pip install --upgrade pip -q

# 安装核心依赖
print_status "info" "安装核心依赖..."
CORE_DEPS=(
    "fastapi>=0.109.0"
    "uvicorn[standard]>=0.27.0"
    "pydantic>=2.5.3"
    "python-dotenv>=1.0.0"
    "python-multipart>=0.0.6"
    "httpx>=0.26.0"
    "aiohttp>=3.9.0"
    "websockets>=11.0"
    "requests>=2.31.0"
)

for dep in "${CORE_DEPS[@]}"; do
    pip install "$dep" -q 2>/dev/null || pip install "$dep"
done
print_status "success" "核心依赖安装完成"

# 安装数据库依赖
print_status "info" "安装数据库依赖..."
DB_DEPS=(
    "sqlalchemy>=2.0.25"
    "aiosqlite>=0.19.0"
    "redis>=4.6.0"
)

for dep in "${DB_DEPS[@]}"; do
    pip install "$dep" -q 2>/dev/null || pip install "$dep"
done
print_status "success" "数据库依赖安装完成"

# 安装 AI 依赖
print_status "info" "安装 AI 依赖..."
AI_DEPS=(
    "openai>=1.0.0"
    "tiktoken>=0.5.0"
)

for dep in "${AI_DEPS[@]}"; do
    pip install "$dep" -q 2>/dev/null || pip install "$dep"
done
print_status "success" "AI 依赖安装完成"

# 安装媒体处理依赖
print_status "info" "安装媒体处理依赖..."
MEDIA_DEPS=(
    "Pillow>=10.2.0"
    "numpy>=1.26.3"
)

for dep in "${MEDIA_DEPS[@]}"; do
    pip install "$dep" -q 2>/dev/null || pip install "$dep"
done
print_status "success" "媒体处理依赖安装完成"

# 安装工具依赖
print_status "info" "安装工具依赖..."
TOOL_DEPS=(
    "pyyaml>=6.0"
    "toml>=0.10.0"
    "python-dateutil>=2.8.0"
    "loguru>=0.7.2"
)

for dep in "${TOOL_DEPS[@]}"; do
    pip install "$dep" -q 2>/dev/null || pip install "$dep"
done
print_status "success" "工具依赖安装完成"

# 创建 .env 文件
if [ ! -f ".env" ]; then
    print_status "info" "创建 .env 配置文件..."
    cp .env.example .env
    print_status "success" ".env 文件已创建"
    print_status "warning" "请编辑 .env 文件配置您的 API Key"
else
    print_status "info" ".env 文件已存在"
fi

# 创建必要的目录
print_status "info" "创建必要的目录..."
mkdir -p logs
mkdir -p data
mkdir -p models
mkdir -p cache

# 验证安装
print_status "info" "验证安装..."
python3 -c "
import sys
sys.path.insert(0, '.')

errors = []
try:
    from fastapi import FastAPI
    print('  ✅ FastAPI')
except ImportError as e:
    errors.append(str(e))
    print('  ❌ FastAPI')

try:
    from uvicorn import run
    print('  ✅ Uvicorn')
except ImportError:
    print('  ❌ Uvicorn')

try:
    from core import NodeRegistry, Message
    print('  ✅ Core Modules')
except ImportError as e:
    errors.append(str(e))
    print('  ❌ Core Modules')

try:
    from nodes.Node_01_OneAPI.main import app
    print('  ✅ Node_01_OneAPI')
except ImportError as e:
    errors.append(str(e))
    print('  ❌ Node_01_OneAPI')

try:
    from nodes.Node_04_Router.main import router
    print('  ✅ Node_04_Router')
except ImportError as e:
    errors.append(str(e))
    print('  ❌ Node_04_Router')

if errors:
    print(f'\n安装存在问题: {len(errors)} 个错误')
    sys.exit(1)
else:
    print('\n所有核心模块验证通过!')
"

if [ $? -eq 0 ]; then
    print_status "success" "安装验证通过"
else
    print_status "warning" "安装验证存在问题，请检查错误信息"
fi

# 完成
echo ""
print_status "success" "================================"
print_status "success" "UFO Galaxy V2 安装完成!"
print_status "success" "================================"
echo ""
print_status "info" "下一步操作:"
echo "  1. 编辑 .env 文件配置 API Key"
echo "  2. 运行 ./start.sh 启动系统"
echo "  3. 访问 http://localhost:8080 查看控制面板"
echo ""

# 退出虚拟环境
deactivate
