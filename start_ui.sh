#!/bin/bash
#
# Galaxy V2 - 交互界面启动脚本
#

echo "========================================"
echo "  Galaxy 交互系统"
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

# 检查依赖
echo "检查依赖..."

# 检查 PyQt5 (可选)
python3 -c "import PyQt5" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✅ PyQt5 已安装"
    UI_STYLE="geek_sidebar"
else
    echo "⚠️  PyQt5 未安装，使用简化 UI"
    UI_STYLE="geek_scroll"
fi

# 检查 keyboard 库 (可选)
python3 -c "import keyboard" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✅ keyboard 库已安装"
else
    echo "⚠️  keyboard 库未安装，热键监听不可用"
    echo "   安装: pip install keyboard"
fi

echo ""
echo "启动交互系统..."
echo ""
echo "UI 风格: $UI_STYLE"
echo "唤醒热键: F12"
echo ""
echo "按 F12 键唤醒/隐藏界面"
echo "按 Ctrl+C 退出"
echo ""

# 启动
python3 start_interactive.py --style $UI_STYLE "$@"
