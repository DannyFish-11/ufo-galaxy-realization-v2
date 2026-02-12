# 统一命令协议文档

## 概述

UFO Galaxy 统一命令协议提供了一个标准化的接口，用于向多个设备/节点并行下发命令，支持同步和异步执行模式，并提供统一的结果聚合和追踪机制。

## 核心特性

- ✅ **多目标支持**: 同时向多个设备发送命令
- ✅ **请求追踪**: 每个请求有唯一的 request_id
- ✅ **执行模式**: 支持 sync（同步）和 async（异步）模式
- ✅ **超时控制**: 可配置命令执行超时时间
- ✅ **结果聚合**: 自动聚合多个目标的执行结果
- ✅ **WebSocket 推送**: 异步模式下通过 WebSocket 实时推送结果
- ✅ **鉴权机制**: 支持 API Token 和 Device ID 鉴权

## API 端点

### 1. 提交命令

**端点**: `POST /api/v1/command`

**功能**: 向一个或多个目标设备提交命令执行请求

#### 请求格式

```json
{
  "request_id": "uuid-string（可选，服务端自动生成）",
  "command": "命令名称",
  "targets": ["device_id_1", "device_id_2"],
  "params": {},
  "mode": "sync|async",
  "timeout": 30
}
```

#### 请求字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| request_id | string | 否 | 请求唯一标识符，若不提供则自动生成 UUID |
| command | string | 是 | 命令名称（如：screenshot, click, swipe等）|
| targets | array[string] | 是 | 目标设备 ID 列表，至少包含一个目标 |
| params | object | 否 | 命令参数，根据具体命令而定 |
| mode | string | 否 | 执行模式，可选值: "sync"（默认）或 "async" |
| timeout | integer | 否 | 超时时间（秒），默认 30 秒 |

#### 响应格式

**同步模式 (mode="sync")**:

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "done",
  "created_at": "2026-02-12T10:00:00.000Z",
  "completed_at": "2026-02-12T10:00:05.123Z",
  "results": {
    "device_id_1": {
      "status": "done",
      "output": {
        "message": "Command executed successfully",
        "data": {}
      },
      "error": null,
      "started_at": "2026-02-12T10:00:00.000Z",
      "completed_at": "2026-02-12T10:00:05.100Z"
    },
    "device_id_2": {
      "status": "failed",
      "output": null,
      "error": "Device not connected",
      "started_at": "2026-02-12T10:00:00.000Z",
      "completed_at": "2026-02-12T10:00:00.050Z"
    }
  }
}
```

**异步模式 (mode="async")**:

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "created_at": "2026-02-12T10:00:00.000Z",
  "message": "Command queued for async execution. Use GET /api/v1/command/{request_id}/status to check status."
}
```

#### 响应状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 命令提交成功（sync 模式下表示执行完成）|
| 400 | 请求参数错误 |
| 401 | 未授权（缺少或无效的 Token）|
| 408 | 请求超时 |
| 500 | 服务器内部错误 |

---

### 2. 查询命令状态

**端点**: `GET /api/v1/command/{request_id}/status`

**功能**: 查询异步命令的执行状态和结果

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| request_id | string | 命令请求的唯一标识符 |

#### 响应格式

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "done",
  "created_at": "2026-02-12T10:00:00.000Z",
  "completed_at": "2026-02-12T10:00:05.123Z",
  "results": {
    "device_id_1": {
      "status": "done",
      "output": {
        "message": "Command executed successfully"
      },
      "error": null,
      "started_at": "2026-02-12T10:00:00.000Z",
      "completed_at": "2026-02-12T10:00:05.100Z"
    }
  }
}
```

#### 响应状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 查询成功 |
| 401 | 未授权 |
| 404 | 找不到指定的命令请求 |

---

## 命令状态枚举

| 状态 | 说明 |
|------|------|
| queued | 已入队等待执行 |
| running | 正在执行 |
| done | 执行完成 |
| failed | 执行失败 |

---

## WebSocket 推送

异步模式下，命令执行完成后会通过 WebSocket 推送结果给所有订阅的客户端。

### 推送消息格式

```json
{
  "type": "command_result",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "done",
  "timestamp": "2026-02-12T10:00:05.123Z",
  "results": {
    "device_id_1": {
      "status": "done",
      "output": {},
      "error": null,
      "started_at": "2026-02-12T10:00:00.000Z",
      "completed_at": "2026-02-12T10:00:05.100Z"
    }
  }
}
```

### WebSocket 连接

**端点**: `ws://<host>:<port>/ws/status`

连接后会自动接收系统状态更新和命令执行结果推送。

---

## 鉴权机制

统一命令端点支持两种鉴权方式：

### 1. API Token 鉴权

通过 `Authorization` header 传递 Bearer Token：

```http
Authorization: Bearer <API_TOKEN>
```

Token 从环境变量 `UFO_API_TOKEN` 读取。若环境变量未设置，系统进入开发模式，跳过鉴权。

### 2. Device ID 标识

通过 `X-Device-ID` header 标识发起请求的设备：

```http
X-Device-ID: <device_id>
```

### 鉴权示例

**cURL 示例**:

```bash
curl -X POST http://localhost:8099/api/v1/command \
  -H "Authorization: Bearer your-api-token-here" \
  -H "X-Device-ID: my-device-001" \
  -H "Content-Type: application/json" \
  -d '{
    "command": "screenshot",
    "targets": ["device_1"],
    "params": {"quality": 90},
    "mode": "sync"
  }'
```

**Python 示例**:

```python
import requests

headers = {
    "Authorization": "Bearer your-api-token-here",
    "X-Device-ID": "my-device-001",
    "Content-Type": "application/json"
}

payload = {
    "command": "screenshot",
    "targets": ["device_1"],
    "params": {"quality": 90},
    "mode": "sync"
}

response = requests.post(
    "http://localhost:8099/api/v1/command",
    headers=headers,
    json=payload
)

print(response.json())
```

---

## 错误码说明

| 错误码 | 错误信息 | 说明 |
|--------|----------|------|
| 400 | Invalid mode. Must be 'sync' or 'async' | 执行模式参数错误 |
| 400 | Targets list cannot be empty | 目标列表为空 |
| 400 | Invalid Device ID | Device ID 格式不正确 |
| 401 | Missing Authorization header | 缺少 Authorization header |
| 401 | Invalid Authorization header format | Authorization header 格式错误 |
| 401 | Invalid API token | API Token 无效 |
| 404 | Command not found | 找不到指定的命令请求 |
| 408 | Command execution timeout | 命令执行超时 |
| 500 | Internal server error | 服务器内部错误 |

---

## 完整示例

### 示例 1: 同步执行单个命令

**请求**:

```bash
curl -X POST http://localhost:8099/api/v1/command \
  -H "Content-Type: application/json" \
  -d '{
    "command": "get_status",
    "targets": ["device_001"],
    "mode": "sync",
    "timeout": 10
  }'
```

**响应**:

```json
{
  "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "done",
  "created_at": "2026-02-12T10:30:00.000Z",
  "completed_at": "2026-02-12T10:30:02.345Z",
  "results": {
    "device_001": {
      "status": "done",
      "output": {
        "battery": 85,
        "network": "WiFi",
        "storage": "60%"
      },
      "error": null,
      "started_at": "2026-02-12T10:30:00.000Z",
      "completed_at": "2026-02-12T10:30:02.345Z"
    }
  }
}
```

---

### 示例 2: 异步执行多目标命令

**步骤 1: 提交命令**

```bash
curl -X POST http://localhost:8099/api/v1/command \
  -H "Content-Type: application/json" \
  -d '{
    "command": "screenshot",
    "targets": ["device_001", "device_002", "device_003"],
    "params": {"quality": 80},
    "mode": "async"
  }'
```

**响应**:

```json
{
  "request_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
  "status": "queued",
  "created_at": "2026-02-12T10:35:00.000Z",
  "message": "Command queued for async execution. Use GET /api/v1/command/{request_id}/status to check status."
}
```

**步骤 2: 轮询状态**

```bash
curl http://localhost:8099/api/v1/command/b2c3d4e5-f6a7-8901-bcde-f12345678901/status
```

**响应**:

```json
{
  "request_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
  "status": "done",
  "created_at": "2026-02-12T10:35:00.000Z",
  "completed_at": "2026-02-12T10:35:08.567Z",
  "results": {
    "device_001": {
      "status": "done",
      "output": {
        "screenshot_url": "/screenshots/device_001_20260212.png"
      },
      "error": null,
      "started_at": "2026-02-12T10:35:00.100Z",
      "completed_at": "2026-02-12T10:35:05.200Z"
    },
    "device_002": {
      "status": "done",
      "output": {
        "screenshot_url": "/screenshots/device_002_20260212.png"
      },
      "error": null,
      "started_at": "2026-02-12T10:35:00.150Z",
      "completed_at": "2026-02-12T10:35:06.300Z"
    },
    "device_003": {
      "status": "failed",
      "output": null,
      "error": "Device not connected",
      "started_at": "2026-02-12T10:35:00.200Z",
      "completed_at": "2026-02-12T10:35:00.250Z"
    }
  }
}
```

---

## 与现有端点对比

### 已废弃端点（保持向后兼容）

以下端点已被统一命令端点替代，但保持向后兼容：

- `/api/commands` (galaxy_gateway/app.py)
- `/api/command` (galaxy_gateway/gateway_service_v2.py, main.py)
- `/execute_command` (galaxy_gateway/gateway_service_v4.py)

### 迁移指南

**旧方式 (`/api/command`)**:

```json
{
  "user_input": "Take a screenshot",
  "session_id": "session123"
}
```

**新方式 (`/api/v1/command`)**:

```json
{
  "command": "screenshot",
  "targets": ["device_001"],
  "params": {},
  "mode": "sync"
}
```

---

## 最佳实践

### 1. 使用 request_id 追踪

建议在客户端生成 UUID 作为 request_id，便于端到端追踪：

```python
import uuid
request_id = str(uuid.uuid4())
```

### 2. 选择合适的执行模式

- **sync 模式**: 适用于需要立即获取结果的场景（如表单提交、即时查询）
- **async 模式**: 适用于耗时操作或多目标并行执行（如批量截图、系统巡检）

### 3. 设置合理的超时时间

根据命令类型设置合适的超时：

- 快速命令（如 click、input）: 5-10 秒
- 中等命令（如 screenshot）: 15-30 秒
- 耗时命令（如 install、backup）: 60-300 秒

### 4. 处理部分失败

多目标命令可能部分成功、部分失败。应用应正确处理每个目标的结果状态：

```python
for target, result in response["results"].items():
    if result["status"] == "done":
        print(f"{target}: 成功")
    else:
        print(f"{target}: 失败 - {result['error']}")
```

---

## 技术实现细节

- **并行执行**: 使用 `asyncio.gather()` 实现多目标并行执行
- **超时控制**: 使用 `asyncio.wait_for()` 实现超时控制
- **后台任务**: 异步模式使用 `asyncio.create_task()` 创建后台任务
- **结果存储**: 命令结果存储在内存字典中（生产环境建议使用 Redis）
- **WebSocket 推送**: 使用全局 ConnectionManager 实现结果广播

---

## 常见问题

### Q1: 异步模式下如何获取结果？

有两种方式：

1. **轮询**: 定期调用 `GET /api/v1/command/{request_id}/status` 查询状态
2. **WebSocket**: 连接 `/ws/status` 端点，等待 `command_result` 消息推送

### Q2: 命令结果保存多久？

当前实现将结果存储在内存中，进程重启后会丢失。生产环境建议使用持久化存储（如 Redis）并设置 TTL。

### Q3: 支持哪些命令？

命令名称由具体的设备/节点定义。常见命令包括：

- GUI 操作: `click`, `swipe`, `input`, `scroll`
- 系统操作: `screenshot`, `get_status`, `install`, `uninstall`
- 自定义命令: 根据节点能力定义

### Q4: 如何确保安全？

1. 设置 `UFO_API_TOKEN` 环境变量启用鉴权
2. 使用 HTTPS 加密传输
3. 限制 API 访问 IP 范围
4. 定期轮换 Token

---

## 版本历史

- **v1.0** (2026-02-12): 初始版本
  - 支持多目标命令执行
  - 支持 sync/async 模式
  - 支持 request_id 追踪
  - 支持超时控制
  - 支持 WebSocket 推送
  - 支持 Token 鉴权
