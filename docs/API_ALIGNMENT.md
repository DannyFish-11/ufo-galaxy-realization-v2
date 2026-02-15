# UFO Galaxy - 两端接口颗粒度对齐文档

## 概述

本文档定义了服务端（ufo-galaxy-realization）和 Android 端（ufo-galaxy-android）之间的接口规范，确保两端颗粒度完全对齐。

## 1. 通信协议对齐

### 1.1 消息格式

**服务端** (`core/node_protocol.py`) 和 **Android 端** (`protocol/NodeProtocol.kt`) 使用相同的消息格式：

```json
{
    "header": {
        "message_id": "uuid-string",
        "message_type": "request|response|event|stream_*|ping|pong",
        "timestamp": 1707235200.123,
        "source_node": "node_id",
        "target_node": "node_id",
        "correlation_id": "uuid-string|null",
        "priority": 0|1|2|3,
        "ttl": 30
    },
    "action": "action_name",
    "payload": {},
    "metadata": {}
}
```

### 1.2 消息类型

| 类型 | 服务端 | Android 端 | 说明 |
|------|--------|------------|------|
| REQUEST | MessageType.REQUEST | MessageType.REQUEST | 请求消息 |
| RESPONSE | MessageType.RESPONSE | MessageType.RESPONSE | 响应消息 |
| EVENT | MessageType.EVENT | MessageType.EVENT | 事件通知 |
| BROADCAST | MessageType.BROADCAST | MessageType.BROADCAST | 广播消息 |
| STREAM_START | MessageType.STREAM_START | MessageType.STREAM_START | 流开始 |
| STREAM_DATA | MessageType.STREAM_DATA | MessageType.STREAM_DATA | 流数据 |
| STREAM_END | MessageType.STREAM_END | MessageType.STREAM_END | 流结束 |
| PING | MessageType.PING | MessageType.PING | 心跳请求 |
| PONG | MessageType.PONG | MessageType.PONG | 心跳响应 |

### 1.3 优先级

| 优先级 | 值 | 说明 |
|--------|-----|------|
| LOW | 0 | 低优先级 |
| NORMAL | 1 | 普通优先级（默认） |
| HIGH | 2 | 高优先级 |
| CRITICAL | 3 | 紧急优先级 |

## 2. API 接口对齐

### 2.1 设备注册 API

**端点**: `POST /api/devices/register`

**请求**:
```json
{
    "device_id": "android_samsung_s21_abc12345",
    "device_type": "android",
    "device_name": "Samsung Galaxy S21",
    "capabilities": ["camera", "microphone", "bluetooth", "nfc"],
    "nodes": {
        "total": 5,
        "nodes": {
            "00": {"name": "StateMachine", "status": "ready"},
            "04": {"name": "ToolRouter", "status": "ready"}
        }
    }
}
```

**响应**:
```json
{
    "success": true,
    "device_id": "android_samsung_s21_abc12345",
    "session_id": "session-uuid",
    "server_time": 1707235200123
}
```

### 2.2 设备状态 API

**端点**: `GET /api/devices/{device_id}/status`

**响应**:
```json
{
    "device_id": "android_samsung_s21_abc12345",
    "status": "online",
    "last_seen": 1707235200123,
    "capabilities": {
        "camera": {"status": "available", "in_use": false},
        "microphone": {"status": "available", "in_use": false},
        "bluetooth": {"status": "enabled", "connected_devices": 2},
        "nfc": {"status": "enabled"},
        "wifi": {"status": "connected", "ssid": "HomeNetwork"},
        "battery": {"level": 85, "charging": false}
    }
}
```

### 2.3 任务执行 API

**端点**: `POST /api/devices/{device_id}/execute`

**请求**:
```json
{
    "task": "打开相机并拍照",
    "context": {
        "priority": "high",
        "timeout": 30
    }
}
```

**响应**:
```json
{
    "success": true,
    "task_id": "task-uuid",
    "result": {
        "action": "camera_capture",
        "status": "completed",
        "data": {
            "image_path": "/storage/emulated/0/DCIM/capture_001.jpg"
        }
    }
}
```

## 3. WebSocket 通信对齐

### 3.1 连接端点

- **服务端**: `ws://{server}:{port}/ws`
- **Android 端**: 连接到服务端 WebSocket

### 3.2 心跳机制

- 间隔: 30 秒
- 超时: 90 秒（3 次心跳未响应）

**Ping 消息**:
```json
{
    "type": "ping",
    "timestamp": 1707235200123
}
```

**Pong 响应**:
```json
{
    "type": "pong",
    "timestamp": 1707235200456
}
```

### 3.3 状态同步

Android 端每 10 秒向服务端同步设备状态：

```json
{
    "type": "status_update",
    "data": {
        "device_id": "android_samsung_s21_abc12345",
        "initialized": true,
        "connected": true,
        "registered": true,
        "nodes": {...},
        "device_status": {...},
        "timestamp": 1707235200123
    }
}
```

## 4. 节点系统对齐

### 4.1 节点 ID 规范

| ID 范围 | 类别 | 说明 |
|---------|------|------|
| 00-09 | 核心节点 | 状态机、路由、协调 |
| 10-19 | 外部服务 | API、GitHub、搜索 |
| 20-29 | 数据处理 | 文件、数据库、缓存 |
| 30-39 | 系统控制 | ADB、Shell、UI 自动化 |
| 40-49 | 通信协议 | MQTT、BLE、串口 |
| 50-59 | AI 模型 | LLM、视觉、语音 |
| 60-69 | 媒体处理 | 图像、视频、音频 |
| 70-79 | 高级功能 | 学习、推理、规划 |

### 4.2 Android 端实现的节点

| 节点 ID | 名称 | 服务端对应 | 状态 |
|---------|------|------------|------|
| 00 | StateMachine | Node_00_StateMachine | ✅ 已实现 |
| 04 | ToolRouter | Node_04_ToolRouter | ✅ 已实现 |
| 33 | ADBSelf | Node_33_ADBSelf | ✅ 已实现 |
| 41 | MQTT | Node_41_MQTT | ✅ 已实现 |
| 58 | ModelRouter | Node_58_ModelRouter | ✅ 已实现 |

## 5. 配置对齐

### 5.1 服务端配置 (.env)

```env
# 服务器配置
SERVER_HOST=0.0.0.0
SERVER_PORT=8765
DEVICE_API_PORT=8766
WS_PORT=8765

# 设备管理
DEVICE_HEARTBEAT_INTERVAL=30
DEVICE_TIMEOUT=90
STATUS_SYNC_INTERVAL=10
```

### 5.2 Android 端配置 (GalaxyConfig)

```kotlin
// 服务器配置
KEY_SERVER_URL = "server_url"
KEY_DEVICE_API_PORT = "device_api_port"  // 默认 8766
KEY_WS_RECONNECT_INTERVAL = "ws_reconnect_interval"  // 默认 5000ms
KEY_STATUS_SYNC_INTERVAL = "status_sync_interval"  // 默认 10000ms
```

## 6. 错误码对齐

| 错误码 | 说明 | 处理方式 |
|--------|------|----------|
| 1001 | 设备未注册 | 重新注册 |
| 1002 | 认证失败 | 检查凭证 |
| 2001 | 节点不可用 | 等待或跳过 |
| 2002 | 任务超时 | 重试或取消 |
| 3001 | 网络错误 | 自动重连 |
| 3002 | 服务器不可达 | 显示离线状态 |

## 7. 版本兼容性

| 服务端版本 | Android 端版本 | 兼容性 |
|------------|----------------|--------|
| 2.0.x | 2.0.x | ✅ 完全兼容 |
| 2.0.x | 1.x | ⚠️ 部分兼容 |
| 1.x | 2.0.x | ❌ 不兼容 |

## 8. 测试验证

### 8.1 连接测试

```bash
# 服务端启动
./start_unified.sh

# 测试 WebSocket 连接
wscat -c ws://localhost:8765/ws
```

### 8.2 API 测试

```bash
# 测试设备注册
curl -X POST http://localhost:8766/api/devices/register \
  -H "Content-Type: application/json" \
  -d '{"device_id": "test_device", "device_type": "android"}'

# 测试设备状态
curl http://localhost:8766/api/devices/test_device/status
```

---

**文档版本**: 2.0.0  
**最后更新**: 2026-02-06  
**作者**: Manus AI
