#!/bin/bash
#
# UFO Galaxy V2 - Docker 快速启动
#

set -e

echo "========================================"
echo "  UFO Galaxy V2 - Docker 部署"
echo "========================================"
echo ""

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "错误: Docker 未安装"
    echo "请先安装 Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

# 检查 Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo "错误: Docker Compose 未安装"
    exit 1
fi

# 创建 .env 文件
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "✅ .env 文件已创建"
    echo "⚠️  请编辑 .env 文件配置 API Key"
fi

# 启动服务
echo "启动 Docker 服务..."
docker-compose up -d

echo ""
echo "========================================"
echo "  服务已启动"
echo "========================================"
echo ""
echo "控制面板: http://localhost:8080"
echo "API 文档: http://localhost:8080/docs"
echo ""
echo "查看日志: docker-compose logs -f"
echo "停止服务: docker-compose down"
echo ""
