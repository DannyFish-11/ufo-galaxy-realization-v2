#!/bin/bash
#
# Galaxy - 一键安装脚本
# 克隆后运行此脚本，自动完成所有配置，包括开机自启动
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
    echo "║   Galaxy - 一键安装                                          ║"
    echo "║   安装后自动 7×24 运行，开机自启动                            ║"
    echo "║                                                               ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# 检测操作系统
detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        OS="linux"
        if command -v apt-get &> /dev/null; then
            DISTRO="debian"
        elif command -v yum &> /dev/null; then
            DISTRO="redhat"
        elif command -v pacman &> /dev/null; then
            DISTRO="arch"
        else
            DISTRO="unknown"
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        OS="macos"
    elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]]; then
        OS="windows"
    else
        OS="unknown"
    fi
    
    echo -e "${GREEN}✓${NC} 检测到系统: $OS ${DISTRO:-}"
}

# 检查 Python
check_python() {
    echo ""
    echo -e "${BLUE}=== 检查 Python ===${NC}"
    
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}✗ Python3 未安装${NC}"
        echo ""
        echo "请先安装 Python 3.10 或更高版本:"
        echo "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
        echo "  macOS: brew install python3"
        echo "  Windows: 从 python.org 下载安装"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
    echo -e "${GREEN}✓${NC} Python 版本: $PYTHON_VERSION"
}

# 创建虚拟环境
create_venv() {
    echo ""
    echo -e "${BLUE}=== 创建虚拟环境 ===${NC}"
    
    if [ -d "venv" ]; then
        echo -e "${GREEN}✓${NC} 虚拟环境已存在"
    else
        python3 -m venv venv
        echo -e "${GREEN}✓${NC} 虚拟环境已创建"
    fi
    
    # 激活虚拟环境
    source venv/bin/activate
    echo -e "${GREEN}✓${NC} 虚拟环境已激活"
}

# 安装依赖
install_deps() {
    echo ""
    echo -e "${BLUE}=== 安装依赖 ===${NC}"
    echo "这可能需要几分钟..."
    
    pip install --upgrade pip -q
    pip install -r requirements.txt -q 2>/dev/null || pip install -r requirements.txt
    
    echo -e "${GREEN}✓${NC} 依赖安装完成"
}

# 创建配置文件
create_config() {
    echo ""
    echo -e "${BLUE}=== 创建配置文件 ===${NC}"
    
    if [ ! -f ".env" ]; then
        cp .env.example .env
        echo -e "${GREEN}✓${NC} .env 文件已创建"
    else
        echo -e "${GREEN}✓${NC} .env 文件已存在"
    fi
    
    # 创建必要目录
    mkdir -p logs data config cache
    
    echo -e "${GREEN}✓${NC} 必要目录已创建"
}

# 配置 API Key
config_api_key() {
    echo ""
    echo -e "${BLUE}=== 配置 API Key ===${NC}"
    echo ""
    echo "请选择要配置的 API Key:"
    echo "  1) OpenAI (推荐)"
    echo "  2) DeepSeek (性价比高)"
    echo "  3) Anthropic"
    echo "  4) Google Gemini"
    echo "  5) 跳过 (稍后配置)"
    echo ""
    read -p "请选择 [1-5]: " choice
    
    case $choice in
        1)
            read -p "请输入 OpenAI API Key: " api_key
            if [ -n "$api_key" ]; then
                sed -i "s|OPENAI_API_KEY=.*|OPENAI_API_KEY=$api_key|" .env 2>/dev/null || \
                echo "OPENAI_API_KEY=$api_key" >> .env
                echo -e "${GREEN}✓${NC} OpenAI API Key 已配置"
            fi
            ;;
        2)
            read -p "请输入 DeepSeek API Key: " api_key
            if [ -n "$api_key" ]; then
                sed -i "s|DEEPSEEK_API_KEY=.*|DEEPSEEK_API_KEY=$api_key|" .env 2>/dev/null || \
                echo "DEEPSEEK_API_KEY=$api_key" >> .env
                echo -e "${GREEN}✓${NC} DeepSeek API Key 已配置"
            fi
            ;;
        3)
            read -p "请输入 Anthropic API Key: " api_key
            if [ -n "$api_key" ]; then
                sed -i "s|ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=$api_key|" .env 2>/dev/null || \
                echo "ANTHROPIC_API_KEY=$api_key" >> .env
                echo -e "${GREEN}✓${NC} Anthropic API Key 已配置"
            fi
            ;;
        4)
            read -p "请输入 Google Gemini API Key: " api_key
            if [ -n "$api_key" ]; then
                sed -i "s|GEMINI_API_KEY=.*|GEMINI_API_KEY=$api_key|" .env 2>/dev/null || \
                echo "GEMINI_API_KEY=$api_key" >> .env
                echo -e "${GREEN}✓${NC} Google Gemini API Key 已配置"
            fi
            ;;
        5)
            echo -e "${YELLOW}!${NC} 跳过 API Key 配置"
            echo "  稍后请编辑 .env 文件配置 API Key"
            ;;
        *)
            echo -e "${YELLOW}!${NC} 无效选择，跳过"
            ;;
    esac
}

# 设置开机自启动 - Linux
setup_autostart_linux() {
    echo ""
    echo -e "${BLUE}=== 设置开机自启动 (Linux) ===${NC}"
    
    # 创建 systemd 服务
    SERVICE_FILE="/tmp/galaxy.service"
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Galaxy L4 AI System
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=$SCRIPT_DIR/venv/bin/python $SCRIPT_DIR/galaxy.py --mode daemon
Restart=always
RestartSec=10
Environment=PATH=$SCRIPT_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
EOF
    
    echo "需要 sudo 权限安装系统服务..."
    sudo cp "$SERVICE_FILE" /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable galaxy
    sudo systemctl start galaxy
    
    echo -e "${GREEN}✓${NC} 开机自启动已设置"
    echo -e "${GREEN}✓${NC} Galaxy 服务已启动"
}

# 设置开机自启动 - macOS
setup_autostart_macos() {
    echo ""
    echo -e "${BLUE}=== 设置开机自启动 (macOS) ===${NC}"
    
    PLIST_FILE="$HOME/Library/LaunchAgents/com.galaxy.plist"
    
    cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.galaxy</string>
    <key>ProgramArguments</key>
    <array>
        <string>$SCRIPT_DIR/venv/bin/python</string>
        <string>$SCRIPT_DIR/galaxy.py</string>
        <string>--mode</string>
        <string>daemon</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$SCRIPT_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$SCRIPT_DIR/logs/galaxy.log</string>
    <key>StandardErrorPath</key>
    <string>$SCRIPT_DIR/logs/galaxy.log</string>
</dict>
</plist>
EOF
    
    launchctl load "$PLIST_FILE" 2>/dev/null || true
    
    echo -e "${GREEN}✓${NC} 开机自启动已设置"
    echo -e "${GREEN}✓${NC} Galaxy 服务已启动"
}

# 设置开机自启动 - Windows
setup_autostart_windows() {
    echo ""
    echo -e "${BLUE}=== 设置开机自启动 (Windows) ===${NC}"
    
    # 创建启动脚本
    STARTUP_SCRIPT="$SCRIPT_DIR/start_galaxy.bat"
    cat > "$STARTUP_SCRIPT" << 'EOF'
@echo off
cd /d "%~dp0"
call venv\Scripts\activate
python galaxy.py --mode daemon
EOF
    
    # 创建 VBS 脚本（隐藏窗口运行）
    VBS_SCRIPT="$SCRIPT_DIR/start_galaxy_hidden.vbs"
    cat > "$VBS_SCRIPT" << EOF
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run chr(34) & "$STARTUP_SCRIPT" & chr(34), 0
Set WshShell = Nothing
EOF
    
    # 复制到启动文件夹
    STARTUP_FOLDER="$APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
    cp "$VBS_SCRIPT" "$STARTUP_FOLDER\Galaxy.vbs"
    
    # 立即启动
    cscript //nologo "$VBS_SCRIPT" &
    
    echo -e "${GREEN}✓${NC} 开机自启动已设置"
    echo -e "${GREEN}✓${NC} Galaxy 服务已启动"
}

# 设置开机自启动
setup_autostart() {
    echo ""
    echo -e "${BLUE}=== 设置开机自启动 ===${NC}"
    echo ""
    echo "是否设置开机自启动？(推荐)"
    echo "  设置后，每次开机 Galaxy 会自动在后台运行"
    echo ""
    read -p "设置开机自启动? [Y/n]: " choice
    
    if [[ "$choice" == "n" ]] || [[ "$choice" == "N" ]]; then
        echo -e "${YELLOW}!${NC} 跳过开机自启动设置"
        return
    fi
    
    case $OS in
        linux)
            setup_autostart_linux
            ;;
        macos)
            setup_autostart_macos
            ;;
        windows)
            setup_autostart_windows
            ;;
        *)
            echo -e "${YELLOW}!${NC} 不支持的系统，请手动设置"
            ;;
    esac
}

# 启动服务
start_service() {
    echo ""
    echo -e "${BLUE}=== 启动 Galaxy ===${NC}"
    
    # 检查是否已经运行
    if [ -f "galaxy.pid" ]; then
        PID=$(cat galaxy.pid)
        if ps -p $PID > /dev/null 2>&1; then
            echo -e "${GREEN}✓${NC} Galaxy 已在运行 (PID: $PID)"
            return
        fi
    fi
    
    # 后台启动
    nohup venv/bin/python galaxy.py --mode daemon > logs/galaxy.log 2>&1 &
    echo $! > galaxy.pid
    
    sleep 2
    
    if ps -p $(cat galaxy.pid) > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Galaxy 已启动 (PID: $(cat galaxy.pid))"
    else
        echo -e "${RED}✗${NC} Galaxy 启动失败，请查看日志: logs/galaxy.log"
    fi
}

# 显示完成信息
show_complete() {
    echo ""
    echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                                                               ║${NC}"
    echo -e "${GREEN}║   ✓ Galaxy 安装完成！                                        ║${NC}"
    echo -e "${GREEN}║                                                               ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "Galaxy 现在正在后台运行，并且已设置开机自启动。"
    echo ""
    echo "访问地址:"
    echo "  配置中心: http://localhost:8080/config"
    echo "  设备管理: http://localhost:8080/devices"
    echo "  API 文档: http://localhost:8080/docs"
    echo ""
    echo "交互方式:"
    echo "  按 F12 键唤醒交互界面"
    echo ""
    echo "管理命令:"
    echo "  查看状态: ./galaxy.sh status"
    echo "  查看日志: tail -f logs/galaxy.log"
    echo "  停止服务: ./galaxy.sh stop"
    echo "  重启服务: ./galaxy.sh restart"
    echo ""
    echo "Galaxy 将在每次开机时自动启动，7×24 小时运行。"
    echo ""
}

# 主函数
main() {
    print_banner
    detect_os
    check_python
    create_venv
    install_deps
    create_config
    config_api_key
    setup_autostart
    start_service
    show_complete
}

main "$@"
