# Galaxy - 命令路由协议

## 概述

命令路由引擎是 Galaxy 的核心调度层，负责将用户/AI 的指令分发到目标节点或设备，并聚合执行结果。

融合元气 AI Bot 精髓：
- **极速** - Redis 缓存热命令，P99 < 100ms
- **智能** - AI 意图解析自动映射命令
- **流畅** - WebSocket 实时推送执行进度
- **可靠** - 超时重试 + 熔断降级

---

## 1. REST API

### POST /api/v1/command

分发命令到目标节点/设备。

**请求体：**

```json
{
  "source": "api",
  "targets": ["Node_02_Tasker", "Node_06_Filesystem"],
  "command": "execute",
  "params": {
    "action": "list_tasks",
    "filter": "pending"
  },
  "mode": "parallel",
  "timeout": 30.0,
  "max_retries": 2,
  "notify_ws": true,
  "priority": 5,
  "metadata": {
    "user_id": "user_001"
  }
}
```

**参数说明：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| source | string | 否 | 来源标识: api / ws / scheduler / ai |
| targets | string[] | 是 | 目标节点或设备 ID 列表 |
| command | string | 是 | 命令名称 |
| params | object | 否 | 命令参数 |
| mode | string | 否 | 执行模式: sync / async / parallel / serial |
| timeout | float | 否 | 超时秒数（默认 30） |
| max_retries | int | 否 | 最大重试次数（默认 2） |
| notify_ws | bool | 否 | 是否通过 WebSocket 推送结果（默认 true） |
| priority | int | 否 | 优先级 1-10（1=最高，默认 5） |
| metadata | object | 否 | 自定义元数据 |

**执行模式：**

| 模式 | 行为 |
|------|------|
| `sync` | 等待所有目标返回结果后响应 |
| `async` | 立即返回 `request_id`，后台执行，通过 WebSocket 推送结果 |
| `parallel` | 多目标并行执行，等待全部完成 |
| `serial` | 多目标按顺序执行 |

**响应体：**

```json
{
  "success": true,
  "request_id": "cmd_a1b2c3d4e5f6",
  "status": "success",
  "targets": {
    "Node_02_Tasker": {
      "target": "Node_02_Tasker",
      "status": "success",
      "result": { "tasks": [...] },
      "error": null,
      "latency_ms": 45.23,
      "retries": 0
    },
    "Node_06_Filesystem": {
      "target": "Node_06_Filesystem",
      "status": "success",
      "result": { "files": [...] },
      "error": null,
      "latency_ms": 12.56,
      "retries": 0
    }
  },
  "total_latency_ms": 48.91,
  "created_at": "2026-01-15T10:30:00",
  "completed_at": "2026-01-15T10:30:00"
}
```

**状态码：**

| status | 说明 |
|--------|------|
| `pending` | 等待执行 |
| `dispatching` | 正在分发 |
| `running` | 执行中 |
| `success` | 全部成功 |
| `partial` | 部分成功 |
| `failed` | 全部失败 |
| `timeout` | 超时 |
| `cancelled` | 已取消 |

### GET /api/v1/command/{request_id}

查询命令执行状态和结果。

```bash
curl http://localhost:8099/api/v1/command/cmd_a1b2c3d4e5f6
```

### DELETE /api/v1/command/{request_id}

取消正在执行的命令。

### GET /api/v1/command

获取命令路由引擎统计信息。

---

## 2. WebSocket 协议

### 设备 WebSocket: /ws/device/{device_id}

**发送命令（客户端 → 服务器）：**

```json
{
  "type": "command_dispatch",
  "targets": ["Node_02_Tasker"],
  "command": "execute",
  "params": { "action": "list_tasks" },
  "mode": "sync",
  "timeout": 30.0
}
```

**接收结果（服务器 → 客户端）：**

```json
{
  "type": "command_result",
  "request_id": "cmd_a1b2c3d4e5f6",
  "data": {
    "status": "success",
    "targets": { ... },
    "total_latency_ms": 48.91
  }
}
```

**AI 意图解析（客户端 → 服务器）：**

```json
{
  "type": "ai_intent",
  "text": "帮我查看所有待办任务",
  "request_id": "req_001"
}
```

**意图结果（服务器 → 客户端）：**

```json
{
  "type": "ai_intent_result",
  "request_id": "req_001",
  "intent": "task_manage",
  "command": "task_manage",
  "targets": ["Node_02_Tasker"],
  "confidence": 0.85,
  "suggestions": ["查看所有任务", "创建新任务", "按优先级排序"]
}
```

### 状态 WebSocket: /ws/status

**自动推送事件：**

| type | 说明 |
|------|------|
| `initial_status` | 连接时的系统快照 |
| `device_connected` | 设备上线 |
| `device_disconnected` | 设备离线 |
| `device_status_update` | 设备状态更新 |
| `command_result` | 命令执行结果 |

**客户端可发送：**

| 消息 | 说明 |
|------|------|
| `"ping"` | 心跳，返回 pong |
| `{"type": "subscribe_commands"}` | 确认订阅命令结果 |
| `{"type": "get_metrics"}` | 获取性能指标 |
| `{"type": "get_health"}` | 获取健康状态 |

---

## 3. AI 意图 API

### POST /api/v1/ai/intent

解析自然语言意图。

```json
{
  "text": "帮我整理一下今天的任务",
  "session_id": "session_001",
  "context": {}
}
```

### POST /api/v1/ai/conversation

添加对话轮次到记忆系统。

### GET /api/v1/ai/conversation/{session_id}

获取对话上下文。

### GET /api/v1/ai/recommendations/{session_id}

获取智能推荐。

---

## 4. 监控 API

### GET /api/v1/monitoring/dashboard

完整监控仪表盘（健康 + 告警 + 指标 + 性能）。

### GET /api/v1/monitoring/health

健康检查聚合。

### GET /api/v1/monitoring/alerts

告警列表。

### GET /api/v1/monitoring/metrics

系统指标。

### GET /api/v1/monitoring/performance

性能指标仪表盘（QPS、P50/P99 延迟、错误率）。

---

## 5. 架构流程

```
用户输入
  │
  ▼
┌─────────────────┐
│  AI 意图解析器   │ ← 规则引擎 (< 1ms) + LLM (高精度)
│  IntentParser    │
└────────┬────────┘
         │ ParsedIntent
         ▼
┌─────────────────┐
│  命令路由引擎    │ ← 缓存命中 → Redis (< 5ms)
│  CommandRouter   │
└────────┬────────┘
         │ CommandRequest
         ▼
┌─────────────────┐    ┌──────────┐
│  并行/串行调度   │───▶│ 节点执行  │
│  Dispatcher      │    │ Node_XX  │
└────────┬────────┘    └──────────┘
         │ TargetResult
         ▼
┌─────────────────┐
│  结果聚合器      │
│  Aggregator      │
└────────┬────────┘
         │ CommandResult
         ▼
┌─────────────────┐    ┌──────────┐
│  WebSocket 推送  │───▶│ 前端/App │
│  Notifier        │    │ 实时更新  │
└─────────────────┘    └──────────┘
```

---

## 6. 性能目标

| 指标 | 目标 | 方案 |
|------|------|------|
| 缓存命中延迟 | < 5ms | Redis 缓存热命令 |
| 单节点执行 | < 100ms | 异步执行 + 并发控制 |
| 多节点并行 | < 200ms | asyncio.gather |
| WebSocket 推送 | < 10ms | 非阻塞广播 |
| P99 延迟 | < 500ms | 超时控制 + 熔断器 |
| 可用性 | 99.99% | 重试 + 降级 + 告警 |
