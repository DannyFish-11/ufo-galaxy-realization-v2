#!/bin/bash

# UFO³ Galaxy Gateway v2.0 启动脚本

echo "======================================================================"
echo "UFO³ Galaxy Gateway v2.0"
echo "======================================================================"

# 设置环境变量
export LLM_PROVIDER="${LLM_PROVIDER:-ollama}"
export LLM_API_BASE="${LLM_API_BASE:-http://localhost:11434}"
export LLM_API_KEY="${LLM_API_KEY:-}"

# 检查 Python 版本
python3 --version

# 安装依赖（如果需要）
echo "检查依赖..."
pip3 list | grep -q fastapi || pip3 install fastapi uvicorn aiohttp websockets

# 启动 Ollama（如果使用本地 LLM）
if [ "$LLM_PROVIDER" = "ollama" ]; then
    echo "检查 Ollama 服务..."
    if ! pgrep -x "ollama" > /dev/null; then
        echo "启动 Ollama..."
        ollama serve &
        sleep 3
    fi
    
    # 检查模型是否已下载
    echo "检查 Qwen2.5 模型..."
    ollama list | grep -q "qwen2.5:7b" || {
        echo "下载 Qwen2.5 模型..."
        ollama pull qwen2.5:7b
    }
fi

# 启动 Gateway
echo "======================================================================"
echo "启动 Galaxy Gateway v2.0..."
echo "======================================================================"
echo "LLM 提供商: $LLM_PROVIDER"
echo "LLM API 地址: $LLM_API_BASE"
echo "======================================================================"

python3 gateway_service_v2.py
