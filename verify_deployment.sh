#!/bin/bash
#
# Galaxy - 完整部署验证脚本
# 模拟用户克隆后的部署流程
#

set -e

echo "========================================"
echo "Galaxy 部署验证测试"
echo "========================================"
echo ""

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 测试计数
PASS=0
FAIL=0

# 测试函数
test_step() {
    local name=$1
    local command=$2
    
    echo -n "测试: $name ... "
    
    if eval "$command" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
        ((PASS++))
        return 0
    else
        echo -e "${RED}✗${NC}"
        ((FAIL++))
        return 1
    fi
}

echo "=== 1. 检查 Python ==="
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version 2>&1)
    echo -e "${GREEN}✓${NC} $PYTHON_VERSION"
    ((PASS++))
else
    echo -e "${RED}✗${NC} Python3 未安装"
    ((FAIL++))
    exit 1
fi
echo ""

echo "=== 2. 检查必要文件 ==="
test_step "requirements.txt" "[ -f requirements.txt ]"
test_step ".env.example" "[ -f .env.example ]"
test_step "galaxy.py" "[ -f galaxy.py ]"
test_step "galaxy.sh" "[ -f galaxy.sh ]"
test_step "main.py" "[ -f main.py ]"
echo ""

echo "=== 3. 创建虚拟环境 ==="
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "${GREEN}✓${NC} 虚拟环境已创建"
else
    echo -e "${GREEN}✓${NC} 虚拟环境已存在"
fi
((PASS++))
echo ""

echo "=== 4. 激活虚拟环境 ==="
source venv/bin/activate
echo -e "${GREEN}✓${NC} 虚拟环境已激活"
((PASS++))
echo ""

echo "=== 5. 安装依赖 ==="
echo "安装核心依赖 (这可能需要几分钟)..."
pip install --upgrade pip -q
pip install -r requirements.txt -q 2>/dev/null || pip install -r requirements.txt
echo -e "${GREEN}✓${NC} 依赖安装完成"
((PASS++))
echo ""

echo "=== 6. 测试核心模块导入 ==="
python3 << 'PYTEST'
import sys
sys.path.insert(0, '.')

errors = 0

# 核心模块
modules = [
    "fastapi",
    "uvicorn", 
    "pydantic",
    "openai",
    "websockets",
    "httpx",
    "aiohttp",
    "redis",
    "qdrant_client",
]

for m in modules:
    try:
        __import__(m)
        print(f"  ✅ {m}")
    except ImportError as e:
        print(f"  ❌ {m}: {e}")
        errors += 1

sys.exit(errors)
PYTEST

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} 所有核心模块导入成功"
    ((PASS++))
else
    echo -e "${RED}✗${NC} 部分模块导入失败"
    ((FAIL++))
fi
echo ""

echo "=== 7. 测试 Galaxy 模块 ==="
python3 << 'PYTEST'
import sys
sys.path.insert(0, '.')

errors = 0

# Galaxy 模块
try:
    from core.node_registry import NodeRegistry
    print("  ✅ core.node_registry")
except Exception as e:
    print(f"  ❌ core.node_registry: {e}")
    errors += 1

try:
    from core.safe_eval import SafeEval
    print("  ✅ core.safe_eval")
except Exception as e:
    print(f"  ❌ core.safe_eval: {e}")
    errors += 1

try:
    from core.secure_config import SecureConfig
    print("  ✅ core.secure_config")
except Exception as e:
    print(f"  ❌ core.secure_config: {e}")
    errors += 1

try:
    from core.llm_router import LLMRouter
    print("  ✅ core.llm_router")
except Exception as e:
    print(f"  ❌ core.llm_router: {e}")
    errors += 1

try:
    from galaxy_gateway.config_service import GalaxyConfig
    print("  ✅ galaxy_gateway.config_service")
except Exception as e:
    print(f"  ❌ galaxy_gateway.config_service: {e}")
    errors += 1

sys.exit(errors)
PYTEST

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} 所有 Galaxy 模块导入成功"
    ((PASS++))
else
    echo -e "${RED}✗${NC} 部分 Galaxy 模块导入失败"
    ((FAIL++))
fi
echo ""

echo "=== 8. 创建配置文件 ==="
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo -e "${GREEN}✓${NC} .env 文件已创建"
else
    echo -e "${GREEN}✓${NC} .env 文件已存在"
fi
((PASS++))

# 创建必要目录
mkdir -p logs data config cache
echo -e "${GREEN}✓${NC} 必要目录已创建"
((PASS++))
echo ""

echo "=== 9. 测试启动 (快速检查) ==="
# 快速测试 - 只检查是否能导入主模块
python3 -c "
import sys
sys.path.insert(0, '.')
from galaxy import Galaxy
print('  ✅ Galaxy 主模块可以导入')
" 2>&1

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Galaxy 可以启动"
    ((PASS++))
else
    echo -e "${RED}✗${NC} Galaxy 启动测试失败"
    ((FAIL++))
fi
echo ""

echo "========================================"
echo "部署验证结果"
echo "========================================"
echo ""
echo -e "通过: ${GREEN}$PASS${NC}"
echo -e "失败: ${RED}$FAIL${NC}"
echo ""

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}✓ 所有测试通过！系统可以部署使用。${NC}"
    echo ""
    echo "下一步操作:"
    echo "  1. 编辑 .env 文件配置 API Key"
    echo "     nano .env"
    echo ""
    echo "  2. 启动系统"
    echo "     ./galaxy.sh start"
    echo ""
    echo "  3. 访问配置界面"
    echo "     http://localhost:8080/config"
    exit 0
else
    echo -e "${RED}✗ 部分测试失败，请检查错误信息。${NC}"
    exit 1
fi
