#!/bin/bash
# ============================================================
# UFO Galaxy System - Deployment Script
# 一键部署脚本
# ============================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印函数
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查 Docker 是否安装
check_docker() {
    print_info "检查 Docker 环境..."
    if ! command -v docker &> /dev/null; then
        print_error "Docker 未安装，请先安装 Docker"
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        print_error "Docker Compose 未安装，请先安装 Docker Compose"
        exit 1
    fi
    
    print_success "Docker 环境检查通过"
}

# 检查 .env 文件
check_env() {
    print_info "检查环境配置文件..."
    if [ ! -f ".env" ]; then
        print_warning ".env 文件不存在，从 .env.example 创建..."
        cp .env.example .env
        print_warning "请编辑 .env 文件，填入你的 API Keys 后再运行此脚本"
        print_info "使用命令: nano .env 或 vim .env"
        exit 1
    fi
    print_success ".env 文件已存在"
}

# 创建必要目录
create_directories() {
    print_info "创建必要目录..."
    mkdir -p monitoring/grafana/dashboards
    mkdir -p monitoring/grafana/datasources
    mkdir -p data/neo4j
    mkdir -p data/qdrant
    mkdir -p data/minio
    mkdir -p data/redis
    mkdir -p data/ollama
    mkdir -p logs
    print_success "目录创建完成"
}

# 部署核心服务
deploy_core() {
    print_info "部署核心服务 (Neo4j, Qdrant, MinIO, Redis)..."
    docker-compose up -d neo4j qdrant minio redis
    print_success "核心服务部署完成"
}

# 部署监控服务
deploy_monitoring() {
    print_info "部署监控服务 (Prometheus, Grafana, Jaeger)..."
    docker-compose up -d prometheus grafana jaeger
    print_success "监控服务部署完成"
}

# 部署本地模型
deploy_ollama() {
    print_info "部署 Ollama 本地模型服务..."
    docker-compose up -d ollama
    print_success "Ollama 部署完成"
    
    print_info "正在拉取常用模型 (llama3.2, qwen2.5)..."
    sleep 5
    docker exec ufo-ollama ollama pull llama3.2 || print_warning "llama3.2 拉取失败"
    docker exec ufo-ollama ollama pull qwen2.5 || print_warning "qwen2.5 拉取失败"
    print_success "模型拉取完成"
}

# 部署 TURN 服务器
deploy_turn() {
    print_info "部署 TURN 服务器..."
    
    # 获取外部 IP
    EXTERNAL_IP=$(curl -s ifconfig.me 2>/dev/null || echo "127.0.0.1")
    print_info "检测到外部 IP: $EXTERNAL_IP"
    
    # 更新 .env 文件
    if grep -q "EXTERNAL_IP=" .env; then
        sed -i "s/EXTERNAL_IP=.*/EXTERNAL_IP=$EXTERNAL_IP/" .env
    fi
    
    docker-compose up -d turn
    print_success "TURN 服务器部署完成"
}

# 部署所有服务
deploy_all() {
    print_info "部署所有服务..."
    docker-compose up -d
    print_success "所有服务部署完成"
}

# 检查服务健康状态
check_health() {
    print_info "检查服务健康状态..."
    
    # 等待服务启动
    sleep 5
    
    # 检查 Neo4j
    if curl -s http://localhost:7474 > /dev/null 2>&1; then
        print_success "Neo4j 运行正常 (http://localhost:7474)"
    else
        print_warning "Neo4j 可能还在启动中..."
    fi
    
    # 检查 Qdrant
    if curl -s http://localhost:6333/healthz > /dev/null 2>&1; then
        print_success "Qdrant 运行正常 (http://localhost:6333)"
    else
        print_warning "Qdrant 可能还在启动中..."
    fi
    
    # 检查 MinIO
    if curl -s http://localhost:9000/minio/health/live > /dev/null 2>&1; then
        print_success "MinIO 运行正常 (http://localhost:9000)"
        print_info "MinIO Console: http://localhost:9001"
    else
        print_warning "MinIO 可能还在启动中..."
    fi
    
    # 检查 Redis
    if docker exec ufo-redis redis-cli ping > /dev/null 2>&1; then
        print_success "Redis 运行正常"
    else
        print_warning "Redis 可能还在启动中..."
    fi
    
    # 检查 Grafana
    if curl -s http://localhost:3000 > /dev/null 2>&1; then
        print_success "Grafana 运行正常 (http://localhost:3000)"
        print_info "默认账号: admin / admin123"
    else
        print_warning "Grafana 可能还在启动中..."
    fi
    
    # 检查 Prometheus
    if curl -s http://localhost:9090 > /dev/null 2>&1; then
        print_success "Prometheus 运行正常 (http://localhost:9090)"
    else
        print_warning "Prometheus 可能还在启动中..."
    fi
}

# 显示服务状态
show_status() {
    print_info "当前服务状态:"
    docker-compose ps
}

# 显示访问信息
show_access_info() {
    echo ""
    echo "============================================================"
    echo -e "${GREEN}UFO Galaxy 服务访问信息${NC}"
    echo "============================================================"
    echo ""
    echo -e "${BLUE}数据库服务:${NC}"
    echo "  Neo4j Browser:    http://localhost:7474"
    echo "  Neo4j Bolt:       bolt://localhost:7687"
    echo "  Qdrant REST API:  http://localhost:6333"
    echo "  Qdrant gRPC:      localhost:6334"
    echo "  MinIO API:        http://localhost:9000"
    echo "  MinIO Console:    http://localhost:9001"
    echo "  Redis:            localhost:6379"
    echo ""
    echo -e "${BLUE}监控服务:${NC}"
    echo "  Grafana:          http://localhost:3000  (admin/admin123)"
    echo "  Prometheus:       http://localhost:9090"
    echo "  Jaeger UI:        http://localhost:16686"
    echo ""
    echo -e "${BLUE}本地模型服务:${NC}"
    echo "  Ollama:           http://localhost:11434"
    echo ""
    echo -e "${BLUE}WebRTC:${NC}"
    echo "  TURN Server:      turn://localhost:3478"
    echo ""
    echo "============================================================"
}

# 停止所有服务
stop_all() {
    print_info "停止所有服务..."
    docker-compose down
    print_success "所有服务已停止"
}

# 清理数据
cleanup() {
    print_warning "这将删除所有数据卷！"
    read -p "确定要继续吗? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker-compose down -v
        rm -rf data/
        print_success "数据已清理"
    else
        print_info "取消清理"
    fi
}

# 显示帮助
show_help() {
    echo "UFO Galaxy 部署脚本"
    echo ""
    echo "用法: ./deploy.sh [命令]"
    echo ""
    echo "命令:"
    echo "  all         部署所有服务"
    echo "  core        仅部署核心服务 (数据库)"
    echo "  monitoring  仅部署监控服务"
    echo "  ollama      部署 Ollama 本地模型"
    echo "  turn        部署 TURN 服务器"
    echo "  status      显示服务状态"
    echo "  health      检查服务健康状态"
    echo "  stop        停止所有服务"
    echo "  cleanup     清理所有数据和卷"
    echo "  help        显示帮助信息"
    echo ""
    echo "示例:"
    echo "  ./deploy.sh all        # 部署所有服务"
    echo "  ./deploy.sh core       # 仅部署数据库"
    echo "  ./deploy.sh status     # 查看状态"
}

# 主函数
main() {
    echo "============================================================"
    echo "  UFO Galaxy System - Deployment Script"
    echo "============================================================"
    echo ""
    
    # 检查命令
    case "${1:-all}" in
        all)
            check_docker
            check_env
            create_directories
            deploy_all
            check_health
            show_access_info
            ;;
        core)
            check_docker
            check_env
            create_directories
            deploy_core
            check_health
            ;;
        monitoring)
            check_docker
            check_env
            deploy_monitoring
            check_health
            ;;
        ollama)
            check_docker
            deploy_ollama
            ;;
        turn)
            check_docker
            check_env
            deploy_turn
            ;;
        status)
            show_status
            ;;
        health)
            check_health
            ;;
        stop)
            stop_all
            ;;
        cleanup)
            cleanup
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "未知命令: $1"
            show_help
            exit 1
            ;;
    esac
}

# 运行主函数
main "$@"
