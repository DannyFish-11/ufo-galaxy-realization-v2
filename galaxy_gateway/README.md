# UFO³ Galaxy Gateway - 超级网关

**统一调用 One-API、本地 LLM 和所有节点功能的超级网关**

---

## 🎯 核心功能

Galaxy Gateway 是 UFO³ Galaxy 系统的**统一入口**，提供：

1. ✅ **LLM 统一调用** - 调用所有 LLM（One-API + 本地）
2. ✅ **节点统一调用** - 调用所有 80+ 节点功能
3. ✅ **智能任务路由** - 自动选择最优节点和模型
4. ✅ **批量任务执行** - 一次调用多个节点
5. ✅ **健康监控** - 实时监控所有节点状态

---

## 📊 架构

```
                Galaxy Gateway (端口: 9000)
                        |
    ┌───────────────────┼───────────────────┐
    |                   |                   |
LLM 能力           节点功能            任务编排
    |                   |                   |
┌───┴───┐          ┌────┴────┐         ┌───┴───┐
|       |          |         |         |       |
One-API 本地LLM   80+节点   硬件控制   智能路由
```

---

## 🚀 快速开始

### 1. 安装依赖

```bash
cd galaxy_gateway
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# One-API 地址
export ONE_API_URL="http://localhost:8001"

# 本地 LLM 地址
export LOCAL_LLM_URL="http://localhost:8079"
```

### 3. 启动服务

```bash
python main.py
```

服务将在 **http://localhost:9000** 启动

---

## 📖 API 文档

### LLM 相关接口

#### 1. 聊天接口

```bash
POST /api/llm/chat
```

**请求：**
```json
{
    "messages": [
        {"role": "user", "content": "Hello, world!"}
    ],
    "model": "auto",
    "temperature": 0.7,
    "max_tokens": 2000
}
```

**响应：**
```json
{
    "choices": [
        {
            "message": {
                "role": "assistant",
                "content": "Hello! How can I help you?"
            }
        }
    ]
}
```

---

#### 2. 简单问答

```bash
POST /api/llm/ask
```

**请求：**
```json
{
    "question": "What is Python?",
    "model": "auto"
}
```

**响应：**
```json
{
    "answer": "Python is a high-level programming language..."
}
```

---

#### 3. 代码生成

```bash
POST /api/llm/code
```

**请求：**
```json
{
    "prompt": "Write a function to sort a list",
    "language": "python"
}
```

**响应：**
```json
{
    "code": "def sort_list(lst):\n    return sorted(lst)"
}
```

---

#### 4. 实时搜索

```bash
POST /api/llm/search?question=latest AI news
```

**响应：**
```json
{
    "result": "According to recent reports..."
}
```

---

### 节点相关接口

#### 1. 列出所有节点

```bash
GET /api/node/list
```

**可选参数：**
- `category`: 按类别筛选（core, llm, database, search, etc.）
- `status`: 按状态筛选（online, offline, unknown）

**响应：**
```json
{
    "count": 25,
    "nodes": [
        {
            "node_id": "node_01",
            "name": "One-API",
            "description": "LLM 统一网关",
            "category": "llm",
            "url": "http://localhost:8001",
            "port": 8001,
            "methods": ["chat_completions", "list_models"],
            "status": "online",
            "priority": 10
        }
    ]
}
```

---

#### 2. 获取节点信息

```bash
GET /api/node/{node_id}
```

**示例：**
```bash
GET /api/node/node_79
```

---

#### 3. 检查节点健康

```bash
GET /api/node/{node_id}/health
```

**响应：**
```json
{
    "node_id": "node_79",
    "healthy": true,
    "status": "online"
}
```

---

#### 4. 调用节点方法

```bash
POST /api/node/call
```

**请求：**
```json
{
    "node_id": "node_79",
    "method": "generate",
    "params": {
        "prompt": "Hello, world!",
        "model": "qwen2.5:7b"
    }
}
```

---

### 任务相关接口

#### 1. 智能任务执行

```bash
POST /api/task/execute
```

**请求：**
```json
{
    "task": "帮我查一下北京天气，然后发邮件给张三",
    "auto_route": true
}
```

**功能：**
- 自动分析任务
- 自动选择节点
- 自动执行步骤

---

#### 2. 批量任务执行

```bash
POST /api/task/batch
```

**请求：**
```json
{
    "tasks": [
        {
            "node": "node_26",
            "method": "get_weather",
            "params": {"city": "Beijing"}
        },
        {
            "node": "node_16",
            "method": "send_email",
            "params": {
                "to": "zhangsan@example.com",
                "subject": "天气通知"
            }
        }
    ]
}
```

**响应：**
```json
{
    "total": 2,
    "success": 2,
    "failed": 0,
    "results": [...]
}
```

---

### 统计和监控

#### 获取系统统计

```bash
GET /api/stats
```

**响应：**
```json
{
    "total_nodes": 25,
    "categories": {
        "core": 3,
        "llm": 5,
        "database": 2,
        ...
    },
    "status": {
        "online": 20,
        "offline": 3,
        "unknown": 2
    }
}
```

---

## 💡 使用示例

### Python 客户端

```python
import httpx

# 1. 简单问答
response = httpx.post(
    "http://localhost:9000/api/llm/ask",
    json={"question": "What is AI?"}
)
print(response.json()["answer"])

# 2. 代码生成
response = httpx.post(
    "http://localhost:9000/api/llm/code",
    json={
        "prompt": "Write a binary search function",
        "language": "python"
    }
)
print(response.json()["code"])

# 3. 调用节点
response = httpx.post(
    "http://localhost:9000/api/node/call",
    json={
        "node_id": "node_79",
        "method": "generate",
        "params": {"prompt": "Hello"}
    }
)
print(response.json())

# 4. 批量任务
response = httpx.post(
    "http://localhost:9000/api/task/batch",
    json={
        "tasks": [
            {"node": "node_22", "method": "search", "params": {"query": "AI"}},
            {"node": "node_83", "method": "get_news", "params": {}}
        ]
    }
)
print(response.json())
```

---

### curl 示例

```bash
# 简单问答
curl -X POST http://localhost:9000/api/llm/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is Python?"}'

# 列出所有节点
curl http://localhost:9000/api/node/list

# 调用节点
curl -X POST http://localhost:9000/api/node/call \
  -H "Content-Type: application/json" \
  -d '{
    "node_id": "node_79",
    "method": "generate",
    "params": {"prompt": "Hello"}
  }'
```

---

## 🎯 支持的节点

Galaxy Gateway 默认注册了以下节点：

### 核心系统
- **node_00**: State Machine - 状态机和锁管理
- **node_01**: One-API - LLM 统一网关
- **node_02**: Tasker - 任务调度

### LLM 相关
- **node_79**: Local LLM - 本地大模型
- **node_80**: Memory System - 记忆系统
- **node_81**: Orchestrator - 任务编排器
- **node_85**: Prompt Library - 提示词库

### 数据库
- **node_12**: Postgres - PostgreSQL 数据库
- **node_13**: SQLite - SQLite 数据库

### 搜索
- **node_22**: Brave Search - Brave 搜索
- **node_25**: Google Search - Google 搜索

### 通信
- **node_10**: Slack - Slack 消息
- **node_16**: Email - 邮件发送

### 硬件控制
- **node_33**: ADB - Android 调试桥
- **node_34**: SSH - SSH 远程控制

### 媒体生成
- **node_71**: Media Generation - 媒体生成

### 系统管理
- **node_65**: Logger Central - 日志中心
- **node_67**: Health Monitor - 健康监控
- **node_82**: Network Guard - 网络监控

### 工具类
- **node_83**: News Aggregator - 新闻聚合
- **node_84**: Stock Tracker - 股票追踪

---

## 🔧 配置

### 环境变量

```bash
# One-API 地址（默认: http://localhost:8001）
ONE_API_URL=http://localhost:8001

# 本地 LLM 地址（默认: http://localhost:8079）
LOCAL_LLM_URL=http://localhost:8079

# Gateway 端口（默认: 9000）
GATEWAY_PORT=9000
```

---

## 📊 优势

### 1. 统一入口
- 所有功能通过一个 Gateway 访问
- 简化客户端调用
- 统一认证和鉴权

### 2. 智能路由
- 自动选择最优模型
- 自动选择最优节点
- 自动 Fallback

### 3. 高可用
- 节点健康检查
- 自动故障转移
- 批量任务支持

### 4. 易于扩展
- 动态注册节点
- 插件化架构
- 支持自定义节点

---

## 🚀 下一步

1. 启动 Galaxy Gateway
2. 启动所需的节点（Node 01, Node 79 等）
3. 通过 Gateway 调用所有功能
4. 查看 Dashboard 监控状态

---

**项目仓库:** https://github.com/DannyFish-11/ufo-galaxy  
**端口:** 9000  
**文档:** http://localhost:9000/docs
