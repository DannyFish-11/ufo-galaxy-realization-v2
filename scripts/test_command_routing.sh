#!/bin/bash
# ============================================================
# Galaxy - 命令路由集成测试脚本
# ============================================================
#
# 用法: bash scripts/test_command_routing.sh [BASE_URL]
#
# 默认 BASE_URL: http://localhost:8099
#
# 测试内容:
#   1. 系统健康检查
#   2. 同步命令分发
#   3. 异步命令分发 + 查询
#   4. 并行命令分发
#   5. AI 意图解析
#   6. 对话记忆
#   7. 智能推荐
#   8. 监控仪表盘
#   9. 性能指标
#  10. 命令路由统计
# ============================================================

set -e

BASE_URL="${1:-http://localhost:8099}"
PASS=0
FAIL=0

# 颜色
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_test() {
    echo -e "${BLUE}[TEST]${NC} $1"
}

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    PASS=$((PASS + 1))
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    FAIL=$((FAIL + 1))
}

log_info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

# 检查 curl 是否可用
if ! command -v curl &> /dev/null; then
    echo "Error: curl is required"
    exit 1
fi

# 检查 jq 是否可用
HAS_JQ=false
if command -v jq &> /dev/null; then
    HAS_JQ=true
fi

echo "============================================"
echo "  Galaxy 命令路由集成测试"
echo "  Base URL: $BASE_URL"
echo "============================================"
echo ""

# ============================================
# 1. 系统健康检查
# ============================================
log_test "1. 系统健康检查"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/v1/system/health" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    log_pass "系统健康 (HTTP $HTTP_CODE)"
else
    log_fail "系统不可达 (HTTP $HTTP_CODE) - 请确保服务已启动"
    echo ""
    echo "提示: 请先启动 Galaxy 服务"
    echo "  python unified_launcher.py"
    echo ""
    exit 1
fi

# ============================================
# 2. 同步命令分发
# ============================================
log_test "2. 同步命令分发"

RESPONSE=$(curl -s -X POST "$BASE_URL/api/v1/command" \
    -H "Content-Type: application/json" \
    -d '{
        "source": "test_script",
        "targets": ["system"],
        "command": "status",
        "params": {},
        "mode": "sync",
        "timeout": 10
    }' 2>/dev/null || echo '{"error": "failed"}')

if echo "$RESPONSE" | grep -q "request_id"; then
    if $HAS_JQ; then
        REQ_ID=$(echo "$RESPONSE" | jq -r '.request_id')
        STATUS=$(echo "$RESPONSE" | jq -r '.status')
        log_pass "同步命令: request_id=$REQ_ID, status=$STATUS"
    else
        log_pass "同步命令分发成功"
    fi
else
    log_fail "同步命令分发失败: $RESPONSE"
fi

# ============================================
# 3. 异步命令分发 + 查询
# ============================================
log_test "3. 异步命令分发 + 状态查询"

RESPONSE=$(curl -s -X POST "$BASE_URL/api/v1/command" \
    -H "Content-Type: application/json" \
    -d '{
        "source": "test_script",
        "targets": ["system"],
        "command": "health_check",
        "params": {},
        "mode": "async",
        "timeout": 10,
        "notify_ws": true
    }' 2>/dev/null || echo '{"error": "failed"}')

if echo "$RESPONSE" | grep -q "request_id"; then
    if $HAS_JQ; then
        REQ_ID=$(echo "$RESPONSE" | jq -r '.request_id')
        log_info "异步命令 request_id=$REQ_ID"

        # 等待一下再查询
        sleep 1

        QUERY_RESPONSE=$(curl -s "$BASE_URL/api/v1/command/$REQ_ID" 2>/dev/null || echo '{"error": "failed"}')
        if echo "$QUERY_RESPONSE" | grep -q "request_id"; then
            STATUS=$(echo "$QUERY_RESPONSE" | jq -r '.status')
            log_pass "异步查询: request_id=$REQ_ID, status=$STATUS"
        else
            log_fail "异步状态查询失败"
        fi
    else
        log_pass "异步命令分发成功"
    fi
else
    log_fail "异步命令分发失败: $RESPONSE"
fi

# ============================================
# 4. 并行命令分发
# ============================================
log_test "4. 并行命令分发 (多目标)"

RESPONSE=$(curl -s -X POST "$BASE_URL/api/v1/command" \
    -H "Content-Type: application/json" \
    -d '{
        "source": "test_script",
        "targets": ["system", "system"],
        "command": "ping",
        "params": {},
        "mode": "parallel",
        "timeout": 5
    }' 2>/dev/null || echo '{"error": "failed"}')

if echo "$RESPONSE" | grep -q "request_id"; then
    if $HAS_JQ; then
        LATENCY=$(echo "$RESPONSE" | jq -r '.total_latency_ms')
        log_pass "并行命令: latency=${LATENCY}ms"
    else
        log_pass "并行命令分发成功"
    fi
else
    log_fail "并行命令分发失败"
fi

# ============================================
# 5. AI 意图解析
# ============================================
log_test "5. AI 意图解析"

RESPONSE=$(curl -s -X POST "$BASE_URL/api/v1/ai/intent" \
    -H "Content-Type: application/json" \
    -d '{
        "text": "帮我查看所有待办任务",
        "session_id": "test_session"
    }' 2>/dev/null || echo '{"error": "failed"}')

if echo "$RESPONSE" | grep -q "intent"; then
    if $HAS_JQ; then
        INTENT=$(echo "$RESPONSE" | jq -r '.intent')
        CONFIDENCE=$(echo "$RESPONSE" | jq -r '.confidence')
        log_pass "意图解析: intent=$INTENT, confidence=$CONFIDENCE"
    else
        log_pass "AI 意图解析成功"
    fi
else
    log_fail "AI 意图解析失败"
fi

# ============================================
# 6. 对话记忆
# ============================================
log_test "6. 对话记忆"

# 添加对话轮次
curl -s -X POST "$BASE_URL/api/v1/ai/conversation" \
    -H "Content-Type: application/json" \
    -d '{
        "session_id": "test_session",
        "role": "user",
        "content": "查看系统状态"
    }' > /dev/null 2>&1

RESPONSE=$(curl -s "$BASE_URL/api/v1/ai/conversation/test_session" 2>/dev/null || echo '{"error": "failed"}')

if echo "$RESPONSE" | grep -q "context"; then
    if $HAS_JQ; then
        TURNS=$(echo "$RESPONSE" | jq '.context | length')
        log_pass "对话记忆: $TURNS 轮对话"
    else
        log_pass "对话记忆正常"
    fi
else
    log_fail "对话记忆查询失败"
fi

# ============================================
# 7. 智能推荐
# ============================================
log_test "7. 智能推荐"

RESPONSE=$(curl -s "$BASE_URL/api/v1/ai/recommendations/test_session" 2>/dev/null || echo '{"error": "failed"}')

if echo "$RESPONSE" | grep -q "recommendations"; then
    if $HAS_JQ; then
        COUNT=$(echo "$RESPONSE" | jq '.recommendations | length')
        log_pass "智能推荐: $COUNT 条推荐"
    else
        log_pass "智能推荐正常"
    fi
else
    log_fail "智能推荐失败"
fi

# ============================================
# 8. 监控仪表盘
# ============================================
log_test "8. 监控仪表盘"

RESPONSE=$(curl -s "$BASE_URL/api/v1/monitoring/dashboard" 2>/dev/null || echo '{"error": "failed"}')

if echo "$RESPONSE" | grep -q "health"; then
    if $HAS_JQ; then
        OVERALL=$(echo "$RESPONSE" | jq -r '.health.overall')
        log_pass "监控仪表盘: overall=$OVERALL"
    else
        log_pass "监控仪表盘正常"
    fi
else
    log_fail "监控仪表盘失败"
fi

# ============================================
# 9. 性能指标
# ============================================
log_test "9. 性能指标"

RESPONSE=$(curl -s "$BASE_URL/api/v1/monitoring/performance" 2>/dev/null || echo '{"error": "failed"}')

if echo "$RESPONSE" | grep -q "uptime_seconds"; then
    if $HAS_JQ; then
        QPS=$(echo "$RESPONSE" | jq -r '.global.qps')
        P99=$(echo "$RESPONSE" | jq -r '.global.p99_latency_ms')
        log_pass "性能指标: QPS=$QPS, P99=${P99}ms"
    else
        log_pass "性能指标正常"
    fi
else
    log_fail "性能指标查询失败"
fi

# ============================================
# 10. 命令路由统计
# ============================================
log_test "10. 命令路由统计"

RESPONSE=$(curl -s "$BASE_URL/api/v1/command" 2>/dev/null || echo '{"error": "failed"}')

if echo "$RESPONSE" | grep -q "total_dispatched"; then
    if $HAS_JQ; then
        DISPATCHED=$(echo "$RESPONSE" | jq -r '.total_dispatched')
        log_pass "命令路由统计: 已分发 $DISPATCHED 条命令"
    else
        log_pass "命令路由统计正常"
    fi
else
    log_fail "命令路由统计失败"
fi

# ============================================
# 清理: 删除测试会话
# ============================================
curl -s -X DELETE "$BASE_URL/api/v1/ai/conversation/test_session" > /dev/null 2>&1

# ============================================
# 测试结果汇总
# ============================================
echo ""
echo "============================================"
echo "  测试结果汇总"
echo "============================================"
echo -e "  ${GREEN}通过: $PASS${NC}"
echo -e "  ${RED}失败: $FAIL${NC}"
TOTAL=$((PASS + FAIL))
echo "  总计: $TOTAL"
echo "============================================"

if [ $FAIL -gt 0 ]; then
    exit 1
fi
