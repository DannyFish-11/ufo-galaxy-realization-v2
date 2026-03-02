#!/bin/bash
#
# UFO Galaxy - 统一启动脚本 v2.0
# ================================
# 
# 功能：
# 1. 自动检测环境
# 2. 安装依赖
# 3. 启动统一融合系统
#
# 使用方法：
#   ./start_unified.sh              # 完整启动
#   ./start_unified.sh --minimal    # 最小启动
#   ./start_unified.sh --status     # 查看状态
#   ./start_unified.sh --setup      # 配置向导
#

set -e

# ============================================================================
# 颜色定义
# ============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
WHITE='\033[1;37m'
NC='\033[0m'

# ============================================================================
# 工具函数
# ============================================================================

print_banner() {
    echo -e "${CYAN}"
    echo "  ╔═══════════════════════════════════════════════════════════════════╗"
    echo "  ║                                                                   ║"
    echo "  ║     ██╗   ██╗███████╗ ██████╗      ██████╗  █████╗ ██╗      ██╗  ║"
    echo "  ║     ██║   ██║██╔════╝██╔═══██╗    ██╔════╝ ██╔══██╗██║      ██║  ║"
    echo "  ║     ██║   ██║█████╗  ██║   ██║    ██║  ███╗███████║██║      ██║  ║"
    echo "  ║     ██║   ██║██╔══╝  ██║   ██║    ██║   ██║██╔══██║██║      ██║  ║"
    echo "  ║     ╚██████╔╝██║     ╚██████╔╝    ╚██████╔╝██║  ██║███████╗ ██║  ║"
    echo "  ║      ╚═════╝ ╚═╝      ╚═════╝      ╚═════╝ ╚═╝  ╚═╝╚══════╝ ╚═╝  ║"
    echo "  ║                                                                   ║"
    echo "  ║                  L4 级自主性智能系统 v2.0                         ║"
    echo "  ║                     统一融合版                                    ║"
    echo "  ║                                                                   ║"
    echo "  ╚═══════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${CYAN}▶${NC} $1"
}

# ============================================================================
# 环境检测
# ============================================================================

check_python() {
    log_step "检测 Python 环境..."
    
    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &> /dev/null; then
        PYTHON_CMD="python"
    else
        log_error "未检测到 Python，请先安装 Python 3.9+"
        exit 1
    fi
    
    PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | cut -d' ' -f2)
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)
    
    if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]); then
        log_error "Python 版本过低: $PYTHON_VERSION，需要 3.9+"
        exit 1
    fi
    
    log_success "Python $PYTHON_VERSION ✓"
}

check_dependencies() {
    log_step "检测依赖..."
    
    # 检查核心依赖
    MISSING_DEPS=""
    
    for pkg in aiohttp fastapi uvicorn pydantic; do
        if ! $PYTHON_CMD -c "import $pkg" 2>/dev/null; then
            MISSING_DEPS="$MISSING_DEPS $pkg"
        fi
    done
    
    if [ -n "$MISSING_DEPS" ]; then
        log_warning "缺失依赖:$MISSING_DEPS"
        log_step "安装依赖..."
        $PYTHON_CMD -m pip install --quiet $MISSING_DEPS || {
            log_error "依赖安装失败"
            exit 1
        }
        log_success "依赖安装完成 ✓"
    else
        log_success "依赖完整 ✓"
    fi
}

# ============================================================================
# 配置检测
# ============================================================================

check_config() {
    log_step "检测配置..."
    
    if [ -f ".env" ]; then
        # 检查是否有 API Key
        if grep -qE "^(OPENAI_API_KEY|GEMINI_API_KEY|OPENROUTER_API_KEY|XAI_API_KEY)=.+" .env 2>/dev/null; then
            log_success "API 配置已就绪 ✓"
        else
            log_warning "未检测到 LLM API 配置，将使用模拟模式"
        fi
    else
        log_warning "未找到 .env 配置文件"
        
        if [ "$1" != "--skip-setup" ]; then
            echo ""
            read -p "是否运行配置向导? (y/N) " -n 1 -r
            echo ""
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                $PYTHON_CMD setup_wizard.py
            fi
        fi
    fi
}

# ============================================================================
# 节点检测
# ============================================================================

check_nodes() {
    log_step "检测节点系统..."
    
    if [ -d "nodes" ]; then
        NODE_COUNT=$(ls -d nodes/Node_*/ 2>/dev/null | wc -l)
        log_success "检测到 $NODE_COUNT 个节点 ✓"
    else
        log_warning "未找到节点目录"
    fi
}

# ============================================================================
# 系统状态
# ============================================================================

show_status() {
    print_banner
    
    echo -e "\n${WHITE}=== 系统状态 ===${NC}\n"
    
    # Python 版本
    if command -v python3 &> /dev/null; then
        echo -e "  Python: ${GREEN}$(python3 --version 2>&1 | cut -d' ' -f2)${NC}"
    else
        echo -e "  Python: ${RED}未安装${NC}"
    fi
    
    # 配置状态
    if [ -f ".env" ]; then
        echo -e "  配置文件: ${GREEN}已存在${NC}"
        
        # 检查各个 API
        for api in OPENAI_API_KEY GEMINI_API_KEY OPENROUTER_API_KEY XAI_API_KEY; do
            if grep -qE "^${api}=.+" .env 2>/dev/null; then
                echo -e "    - $api: ${GREEN}已配置${NC}"
            else
                echo -e "    - $api: ${YELLOW}未配置${NC}"
            fi
        done
    else
        echo -e "  配置文件: ${YELLOW}不存在${NC}"
    fi
    
    # 节点统计
    if [ -d "nodes" ]; then
        NODE_COUNT=$(ls -d nodes/Node_*/ 2>/dev/null | wc -l)
        echo -e "  节点数量: ${GREEN}$NODE_COUNT${NC}"
    fi
    
    # 核心模块
    echo -e "\n${WHITE}=== 核心模块 ===${NC}\n"
    
    for module in "core/node_registry.py" "core/node_protocol.py" "core/device_agent_manager.py" "core/microsoft_ufo_integration.py"; do
        if [ -f "$module" ]; then
            echo -e "  $(basename $module): ${GREEN}✓${NC}"
        else
            echo -e "  $(basename $module): ${RED}✗${NC}"
        fi
    done
    
    echo ""
}

# ============================================================================
# 主函数
# ============================================================================

main() {
    # 获取脚本所在目录
    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
    cd "$SCRIPT_DIR"
    
    # 解析参数
    case "$1" in
        --status|-s)
            show_status
            exit 0
            ;;
        --setup)
            print_banner
            $PYTHON_CMD setup_wizard.py
            exit 0
            ;;
        --help|-h)
            echo "UFO Galaxy 统一启动脚本 v2.0"
            echo ""
            echo "用法: $0 [选项]"
            echo ""
            echo "选项:"
            echo "  --status, -s     显示系统状态"
            echo "  --setup          运行配置向导"
            echo "  --minimal, -m    最小启动模式"
            echo "  --no-ui          不启动 Web UI"
            echo "  --no-l4          不启动 L4 模块"
            echo "  --port PORT      指定 Web UI 端口"
            echo "  --help, -h       显示帮助"
            exit 0
            ;;
    esac
    
    # 打印横幅
    print_banner
    
    echo -e "${WHITE}=== 环境检测 ===${NC}\n"
    
    # 环境检测
    check_python
    check_dependencies
    check_config "$@"
    check_nodes
    
    echo -e "\n${WHITE}=== 启动系统 ===${NC}\n"
    
    # 启动统一系统
    log_step "启动 UFO Galaxy 统一系统..."
    echo ""
    
    # 传递所有参数给 Python
    $PYTHON_CMD unified_launcher.py "$@"
}

# 运行主函数
main "$@"
