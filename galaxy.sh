#!/bin/bash
#
# Galaxy - 统一启动脚本 (完整版)
# 支持 7×24 后台运行、开机自启动、交互界面
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
    echo "║   Galaxy - L4 级自主性智能系统                                ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# 检查虚拟环境
check_venv() {
    if [ ! -d "venv" ]; then
        echo -e "${YELLOW}虚拟环境不存在，请先运行 ./install.sh${NC}"
        exit 1
    fi
}

# 启动服务
start_service() {
    check_venv
    
    # 检查是否已经运行
    if [ -f "galaxy.pid" ]; then
        PID=$(cat galaxy.pid)
        if ps -p $PID > /dev/null 2>&1; then
            echo -e "${GREEN}✓${NC} Galaxy 已在运行 (PID: $PID)"
            return 0
        fi
    fi
    
    echo -e "${BLUE}启动 Galaxy...${NC}"
    
    # 激活虚拟环境
    source venv/bin/activate
    
    # 后台启动
    nohup python galaxy.py --mode daemon > logs/galaxy.log 2>&1 &
    echo $! > galaxy.pid
    
    sleep 2
    
    if ps -p $(cat galaxy.pid) > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Galaxy 已启动 (PID: $(cat galaxy.pid))"
        echo ""
        echo "访问地址:"
        echo "  配置中心: http://localhost:8080/config"
        echo "  设备管理: http://localhost:8080/devices"
        echo "  交互界面: 按 F12 键唤醒"
    else
        echo -e "${RED}✗${NC} Galaxy 启动失败，请查看日志: logs/galaxy.log"
        return 1
    fi
}

# 停止服务
stop_service() {
    echo -e "${YELLOW}停止 Galaxy...${NC}"
    
    if [ -f "galaxy.pid" ]; then
        PID=$(cat galaxy.pid)
        if ps -p $PID > /dev/null 2>&1; then
            kill $PID 2>/dev/null || true
            sleep 1
            if ps -p $PID > /dev/null 2>&1; then
                kill -9 $PID 2>/dev/null || true
            fi
            echo -e "${GREEN}✓${NC} Galaxy 已停止"
        else
            echo -e "${YELLOW}!${NC} Galaxy 未在运行"
        fi
        rm -f galaxy.pid
    else
        echo -e "${YELLOW}!${NC} 未找到 PID 文件"
    fi
    
    # 同时停止交互界面
    pkill -f "start_interactive.py" 2>/dev/null || true
}

# 查看状态
show_status() {
    print_banner
    
    echo "系统状态:"
    echo ""
    
    # 检查主服务
    if [ -f "galaxy.pid" ]; then
        PID=$(cat galaxy.pid)
        if ps -p $PID > /dev/null 2>&1; then
            echo -e "  主服务: ${GREEN}运行中${NC} (PID: $PID)"
        else
            echo -e "  主服务: ${RED}已停止${NC}"
        fi
    else
        echo -e "  主服务: ${YELLOW}未运行${NC}"
    fi
    
    # 检查交互界面
    if pgrep -f "start_interactive.py" > /dev/null 2>&1; then
        echo -e "  交互界面: ${GREEN}运行中${NC}"
    else
        echo -e "  交互界面: ${YELLOW}未运行${NC}"
    fi
    
    echo ""
    echo "访问地址:"
    echo "  配置中心: http://localhost:8080/config"
    echo "  设备管理: http://localhost:8080/devices"
    echo "  API 文档: http://localhost:8080/docs"
    echo ""
    echo "交互方式:"
    echo "  按 F12 键唤醒交互界面"
    echo ""
}

# 启动交互界面
start_ui() {
    check_venv
    
    # 检查是否已经运行
    if pgrep -f "start_interactive.py" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} 交互界面已在运行"
        return 0
    fi
    
    echo -e "${BLUE}启动交互界面...${NC}"
    
    source venv/bin/activate
    
    # 后台启动交互界面
    nohup python start_interactive.py > logs/ui.log 2>&1 &
    
    sleep 1
    
    echo -e "${GREEN}✓${NC} 交互界面已启动"
    echo ""
    echo "按 F12 键唤醒/隐藏界面"
}

# 查看日志
show_logs() {
    if [ -f "logs/galaxy.log" ]; then
        tail -f logs/galaxy.log
    else
        echo "日志文件不存在"
    fi
}

# 显示帮助
show_help() {
    print_banner
    echo "用法: ./galaxy.sh {命令}"
    echo ""
    echo "命令:"
    echo "  start       - 启动 Galaxy (后台运行)"
    echo "  stop        - 停止 Galaxy"
    echo "  restart     - 重启 Galaxy"
    echo "  status      - 查看状态"
    echo "  ui          - 启动交互界面"
    echo "  logs        - 查看日志"
    echo "  config      - 打开配置界面"
    echo "  install     - 运行安装程序"
    echo ""
    echo "示例:"
    echo "  ./galaxy.sh start    # 启动服务"
    echo "  ./galaxy.sh status   # 查看状态"
    echo "  ./galaxy.sh ui       # 启动交互界面"
    echo ""
}

# 打开配置界面
open_config() {
    echo "打开配置界面..."
    
    # 检查服务是否运行
    if ! curl -s http://localhost:8080/config > /dev/null 2>&1; then
        echo "服务未运行，正在启动..."
        start_service
        sleep 3
    fi
    
    # 打开浏览器
    if command -v xdg-open &> /dev/null; then
        xdg-open http://localhost:8080/config
    elif command -v open &> /dev/null; then
        open http://localhost:8080/config
    else
        echo "请手动打开: http://localhost:8080/config"
    fi
}

# 主函数
main() {
    local command=${1:-"help"}
    
    case $command in
        start)
            start_service
            ;;
        stop)
            stop_service
            ;;
        restart)
            stop_service
            sleep 2
            start_service
            ;;
        status)
            show_status
            ;;
        ui)
            start_ui
            ;;
        logs)
            show_logs
            ;;
        config)
            open_config
            ;;
        install)
            if [ -f "install.sh" ]; then
                ./install.sh
            else
                echo "install.sh 不存在"
            fi
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            echo "未知命令: $command"
            show_help
            exit 1
            ;;
    esac
}

main "$@"
