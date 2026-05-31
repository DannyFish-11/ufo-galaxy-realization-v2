#!/bin/bash

# Galaxy Gateway v2.0 启动脚本

echo "======================================================================"
echo "Galaxy Gateway v2.0"
echo "======================================================================"

# 设置环境变量
export LLM_PROVIDER="${LLM_PROVIDER:-ollama}"
export LLM_API_BASE="${LLM_API_BASE:-http://localhost:11434}"
export LLM_API_KEY="${LLM_API_KEY:-}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-gemma4:latest}"  # PR-GEMMA4: Google 本地多模态模型

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
    
    # PR-GEMMA4: 检查 Google Gemma 4 模型（本地多模态，E4B 适合普通电脑）
    echo "检查 Google Gemma 4 模型 ($OLLAMA_MODEL)..."
    ollama list | grep -q "$OLLAMA_MODEL" || {
        echo "下载 $OLLAMA_MODEL ..."
        ollama pull "$OLLAMA_MODEL"
    }
fi

# 启动 Gateway
echo "======================================================================"
echo "启动 Galaxy Gateway v2.0..."
echo "======================================================================"
echo "LLM 提供商: $LLM_PROVIDER"
echo "OLLAMA 模型: $OLLAMA_MODEL"
echo "LLM API 地址: $LLM_API_BASE"
echo "===========