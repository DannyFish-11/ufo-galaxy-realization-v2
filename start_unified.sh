#!/bin/bash
#
# Galaxy - 统一启动脚本 v2.0
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
# 颜色定义 (ANSI 支持检测)
# ============================================================================

if [ -t 1 ] && [ "${TERM:-dumb}" != "dumb" ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    MAGENTA='\033[0;35m'
    PURPLE='\033[0;35m'
    PINK='\033[0;95m'
    WHITE='\033[1;37m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; BLUE=''; CYAN=''; MAGENTA=''; PURPLE=''; PINK=''
    WHITE=''; BOLD=''; NC=''
fi

# ============================================================================
# 工具函数
# ============================================================================

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

log_info() {
    printf "  ${BLUE}ℹ️   %-28s${NC} %s\n" "$1" "${2:-}"
}

log_success() {
    printf "  ${GREEN}✅  %-28s${NC} %s\n" "$1" "${2:-}"
}

log_warning() {
    printf "  ${YELLOW}⚠️   %-28s${NC} %s\n" "$1" "${2:-}"
}

log_error() {
    printf "  ${RED}❌  %-28s${NC} %s\n" "$1" "${2:-}"
}

log_step() {
    printf "  ${CYAN}▶   %-28s${NC} %s\n" "$1" "${2:-}"
}

log_section() {
    local sep
    sep=$(printf '═%.0s' {1..60})
    echo -e "\n${BOLD}${CYAN}${sep}${NC}"
    echo -e "${BOLD}${CYAN}  ▶  $1${NC}"
    echo -e "${BOLD}${CYAN}${sep}${NC}\n"
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

    # 创建虚拟环境（如果不存在）
    if [ ! -d "venv" ]; then
        log_step "创建虚拟环境..."
        $PYTHON_CMD -m venv venv || {
            log_error "虚拟环境创建失败"
            exit 1
        }
        log_success "虚拟环境已创建 ✓"
    fi

    # 激活虚拟环境
    source venv/bin/activate 2>/dev/null || . venv/bin/activate
    # 更新 PYTHON_CMD 为虚拟环境中的 python
    PYTHON_CMD="python"

    # 快速检查核心依赖
    MISSING_CORE=false
    for pkg in aiohttp fastapi uvicorn pydantic; do
        if ! $PYTHON_CMD -c "import $pkg" 2>/dev/null; then
            MISSING_CORE=true
            break
        fi
    done

    # 如果核心依赖缺失，执行完整安装
    if [ "$MISSING_CORE" = true ] && [ -f "requirements.txt" ]; then
        log_warning "缺失核心依赖，执行完整安装..."
        log_step "安装依赖（首次运行可能需要几分钟）..."
        $PYTHON_CMD -m pip install --quiet -r requirements.txt || {
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
    
    log_section "系统状态"
    
    # Python 版本
    if command -v python3 &> /dev/null; then
        log_success "Python" "$(python3 --version 2>&1 | cut -d' ' -f2)"
    else
        log_error "Python" "未安装"
    fi
    
    # 配置状态
    if [ -f ".env" ]; then
        log_success "配置文件" "已存在"
        
        # 检查各个 API
        for api in OPENAI_API_KEY GEMINI_API_KEY OPENROUTER_API_KEY XAI_API_KEY; do
            if grep -qE "^${api}=.+" .env 2>/dev/null; then
                log_success "$api" "已配置"
            else
                log_warning "$api" "未配置"
            fi
        done
    else
        log_warning "配置文件" "不存在"
    fi
    
    # 节点统计
    if [ -d "nodes" ]; then
        NODE_COUNT=$(ls -d nodes/Node_*/ 2>/dev/null | wc -l)
        log_success "节点数量" "$NODE_COUNT"
    fi
    
    log_section "核心模块"
    
    for module in "core/node_registry.py" "core/node_protocol.py" "core/device_agent_manager.py" "core/microsoft_ufo_integration.py"; do
        if [ -f "$module" ]; then
            log_success "$(basename $module)" "✓"
        else
            log_error "$(basename $module)" "✗"
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
            echo "Galaxy 统一启动脚本 v2.0"
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
    log_step "启动 Galaxy 统一系统..."
    echo ""

    # 传递所有参数给 Python
    export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
    $PYTHON_CMD unified_launcher.py "$@"
}

# 运行主函数
main "$@"
