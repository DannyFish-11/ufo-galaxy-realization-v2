#!/bin/bash
#
# Galaxy - 统一启动脚本
# 一键启动完整的 Galaxy 系统
#

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 打印横幅
print_banner() {
    echo -e "${CYAN}"
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║                                                               ║"
    echo "║   ██████╗  █████╗  ██████╗ ██████╗ ███████╗                  ║"
    echo "║   ██╔══██╗██╔══██╗██╔════╝██╔═══██╗██╔════╝                  ║"
    echo "║   ██║  ██║███████║██║     ██║   ██║███████╗                  ║"
    echo "║   ██║  ██║██╔══██║██║     ██║   ██║╚════██║                  ║"
    echo "║   ██████╔╝██║  ██║╚██████╗╚██████╔╝███████║                  ║"
    echo "║   ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝                  ║"
    echo "║                                                               ║"
    echo "║   Galaxy - L4 级自主性智能系统                                ║"
    echo "║                                                               ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# 检查 Python
check_python() {
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}错误: Python3 未安装${NC}"
        echo "请安装 Python 3.10 或更高版本"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
    echo -e "${GREEN}✓${NC} Python 版本: $PYTHON_VERSION"
}

# 检查虚拟环境
check_venv() {
    if [ ! -d "venv" ]; then
        echo -e "${YELLOW}创建虚拟环境...${NC}"
        python3 -m venv venv
    fi
    
    # 激活虚拟环境
    source venv/bin/activate
    echo -e "${GREEN}✓${NC} 虚拟环境已激活"
}

# 安装依赖
install_deps() {
    echo -e "${YELLOW}检查依赖...${NC}"
    
    if [ -f "requirements.txt" ]; then
        pip install -q -r requirements.txt 2>/dev/null || pip install -r requirements.txt
        echo -e "${GREEN}✓${NC} 依赖已安装"
    fi
}

# 检查配置
check_config() {
    if [ ! -f ".env" ]; then
        if [ -f ".env.example" ]; then
            echo -e "${YELLOW}创建配置文件...${NC}"
            cp .env.example .env
            echo -e "${GREEN}✓${NC} .env 文件已创建"
            echo -e "${YELLOW}请编辑 .env 文件配置 API Key${NC}"
        fi
    else
        echo -e "${GREEN}✓${NC} 配置文件已存在"
    fi
    
    # 创建必要的目录
    mkdir -p logs data config cache
}

# 启动系统
start_system() {
    local mode=${1:-"full"}
    
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  启动 Galaxy 系统 (${mode} 模式)${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    
    # 设置环境变量
    export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
    
    # 启动
    python3 galaxy.py --mode "$mode"
}

# 后台运行
start_daemon() {
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  启动 Galaxy 守护进程${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    
    # 检查是否已在运行
    if [ -f "galaxy.pid" ]; then
        PID=$(cat galaxy.pid)
        if ps -p $PID > /dev/null 2>&1; then
            echo -e "${YELLOW}Galaxy 已在运行 (PID: $PID)${NC}"
            return
        fi
    fi
    
    # 后台启动
    nohup python3 galaxy.py --mode daemon > logs/galaxy.log 2>&1 &
    echo $! > galaxy.pid
    
    echo -e "${GREEN}✓${NC} Galaxy 已启动 (PID: $(cat galaxy.pid))"
    echo ""
    echo "日志文件: logs/galaxy.log"
    echo "停止命令: ./galaxy.sh stop"
}

# 停止系统
stop_system() {
    echo ""
    echo -e "${YELLOW}停止 Galaxy 系统...${NC}"
    
    if [ -f "galaxy.pid" ]; then
        PID=$(cat galaxy.pid)
        if ps -p $PID > /dev/null 2>&1; then
            kill $PID
            echo -e "${GREEN}✓${NC} Galaxy 已停止 (PID: $PID)"
        fi
        rm galaxy.pid
    else
        echo -e "${YELLOW}未找到运行中的 Galaxy${NC}"
    fi
}

# 查看状态
show_status() {
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  Galaxy 系统状态${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    
    if [ -f "galaxy.pid" ]; then
        PID=$(cat galaxy.pid)
        if ps -p $PID > /dev/null 2>&1; then
            echo -e "状态: ${GREEN}运行中${NC}"
            echo "PID: $PID"
            echo ""
            
            # 显示端口
            echo "服务地址:"
            echo "  配置中心: http://localhost:8080/config"
            echo "  设备管理: http://localhost:8080/devices"
            echo "  API 文档: http://localhost:8080/docs"
        else
            echo -e "状态: ${RED}已停止${NC}"
            rm galaxy.pid
        fi
    else
        echo -e "状态: ${YELLOW}未运行${NC}"
    fi
}

# 主函数
main() {
    local command=${1:-"start"}
    local mode=${2:-"full"}
    
    case $command in
        start)
            print_banner
            check_python
            check_venv
            install_deps
            check_config
            start_system "$mode"
            ;;
        daemon)
            print_banner
            check_python
            check_venv
            install_deps
            check_config
            start_daemon
            ;;
        stop)
            stop_system
            ;;
        restart)
            stop_system
            sleep 2
            print_banner
            check_python
            check_venv
            start_daemon
            ;;
        status)
            show_status
            ;;
        config)
            print_banner
            check_python
            check_venv
            install_deps
            check_config
            echo ""
            echo "启动配置服务..."
            python3 -c "from galaxy_gateway.config_service import run_server; run_server()"
            ;;
        *)
            echo "用法: $0 {start|daemon|stop|restart|status|config} [mode]"
            echo ""
            echo "命令:"
            echo "  start     - 前台启动 (默认)"
            echo "  daemon    - 后台启动 (7x24 运行)"
            echo "  stop      - 停止系统"
            echo "  restart   - 重启系统"
            echo "  status    - 查看状态"
            echo "  config    - 仅启动配置服务"
            echo ""
            echo "模式:"
            echo "  full      - 完整模式 (默认)"
            echo "  minimal   - 最小模式"
            ;;
    esac
}

main "$@"
