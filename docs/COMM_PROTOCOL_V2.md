# Galaxy 通信协议 V2 — M2 统一事件 Schema

## 概述

M2 统一事件协议定义了跨设备、跨组件之间的标准化语义事件格式。  
所有涉及状态、任务、情绪、动作、感知的事件均通过此协议交换，  
确保系统内每个组件对"发生了什么"拥有一致的理解。

> M2 事件层与旧有 `EventBus`（`UIGalaxyEvent`）**并行运行**，不破坏任何现有订阅。  
> 旧事件仍照常发布；新代码在关键路径额外发布 M2 事件。

---

## 统一字段定义

每个 M2 事件对象包含以下顶层字段：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `event_id` | string (UUID) | ✅ | 全局唯一事件标识符 |
| `event_type` | string (enum) | ✅ | 事件类型，见最小集枚举 |
| `timestamp` | string (ISO 8601 UTC) | ✅ | 事件产生时刻 |
| `source` | object | ✅ | 事件来源描述 |
| `source.device_id` | string | ✅ | 来源设备 ID（可为逻辑节点名，如 `"gateway"`） |
| `source.node` | string | ❌ | 可选，组件/服务名称（如 `"event_bridge"`, `"message_handler"`） |
| `source.version` | string | ❌ | 可选，组件版本 |
| `payload` | object | ✅ | 事件具体数据，因 `event_type` 而异 |
| `trace` | object | ❌ | 可选，分布式追踪上下文 |
| `trace.task_id` | string | ❌ | 关联任务 ID |
| `trace.span_id` | string | ❌ | Span ID（用于链路追踪） |

---

## 事件最小集（event_type 枚举）

| 事件类型 | 触发场景 |
|----------|----------|
| `agent.state` | Agent 状态变更（idle / running / error / shutdown） |
| `agent.emotion` | Agent 情绪/情感状态更新 |
| `task.lifecycle` | 任务生命周期变更（created / running / completed / failed / cancelled） |
| `skill.invoke` | 技能/工具被调用 |
| `perception.update` | 感知数据更新（屏幕内容、传感器数据等） |
| `action.command` | 动作命令发出（对设备的实际操控指令） |
| `device.presence` | 设备上线/离线/注册/注销 |

---

## 各事件 payload 示例

### `agent.state`

```json
{
  "event_id": "3f2a1b4c-0000-0000-0000-000000000001",
  "event_type": "agent.state",
  "timestamp": "2026-03-16T10:00:00.000Z",
  "source": {
    "device_id": "node_master",
    "node": "agent_core"
  },
  "payload": {
    "agent_id": "agent_001",
    "state": "running",
    "previous_state": "idle",
    "reason": "task_received"
  },
  "trace": {
    "task_id": "task_abc123",
    "span_id": "span_001"
  }
}
```

### `agent.emotion`

```json
{
  "event_id": "3f2a1b4c-0000-0000-0000-000000000002",
  "event_type": "agent.emotion",
  "timestamp": "2026-03-16T10:00:01.000Z",
  "source": {
    "device_id": "node_master",
    "node": "emotion_engine"
  },
  "payload": {
    "agent_id": "agent_001",
    "emotion": "focused",
    "valence": 0.8,
    "arousal": 0.6,
    "confidence": 0.9
  }
}
```

### `task.lifecycle`

```json
{
  "event_id": "3f2a1b4c-0000-0000-0000-000000000003",
  "event_type": "task.lifecycle",
  "timestamp": "2026-03-16T10:00:02.000Z",
  "source": {
    "device_id": "gateway",
    "node": "message_handler"
  },
  "payload": {
    "task_id": "task_abc123",
    "status": "running",
    "previous_status": "created",
    "task_type": "screen_click",
    "target_device": "android_device_01",
    "progress": 0.0
  },
  "trace": {
    "task_id": "task_abc123",
    "span_id": "span_002"
  }
}
```

### `skill.invoke`

```json
{
  "event_id": "3f2a1b4c-0000-0000-0000-000000000004",
  "event_type": "skill.invoke",
  "timestamp": "2026-03-16T10:00:03.000Z",
  "source": {
    "device_id": "node_master",
    "node": "skill_loader"
  },
  "payload": {
    "skill_name": "web_search",
    "skill_version": "1.0.0",
    "args": {
      "query": "Galaxy AI system"
    },
    "invocation_id": "inv_001"
  },
  "trace": {
    "task_id": "task_abc123",
    "span_id": "span_003"
  }
}
```

### `perception.update`

```json
{
  "event_id": "3f2a1b4c-0000-0000-0000-000000000005",
  "event_type": "perception.update",
  "timestamp": "2026-03-16T10:00:04.000Z",
  "source": {
    "device_id": "android_device_01",
    "node": "vision_sampler"
  },
  "payload": {
    "perception_type": "screen",
    "content_hash": "sha256:abcdef1234567890",
    "width": 1080,
    "height": 2340,
    "active_app": "com.example.app",
    "element_count": 42
  },
  "trace": {
    "task_id": "task_abc123"
  }
}
```

### `action.command`

```json
{
  "event_id": "3f2a1b4c-0000-0000-0000-000000000006",
  "event_type": "action.command",
  "timestamp": "2026-03-16T10:00:05.000Z",
  "source": {
    "device_id": "gateway",
    "node": "device_router"
  },
  "payload": {
    "command_id": "cmd_001",
    "command_type": "tap",
    "target_device": "android_device_01",
    "args": {
      "x": 540,
      "y": 960
    },
    "priority": 5
  },
  "trace": {
    "task_id": "task_abc123",
    "span_id": "span_004"
  }
}
```

### `device.presence`

```json
{
  "event_id": "3f2a1b4c-0000-0000-0000-000000000007",
  "event_type": "device.presence",
  "timestamp": "2026-03-16T10:00:06.000Z",
  "source": {
    "device_id": "gateway",
    "node": "device_registry"
  },
  "payload": {
    "device_id": "android_device_01",
    "device_type": "android",
    "presence": "online",
    "previous_presence": "offline",
    "capabilities": ["screen", "touch", "camera"]
  }
}
```

---

## 与旧协议的关系

```
旧有 EventBus (UIGalaxyEvent)          M2 事件层
─────────────────────────────         ──────────────────────
EventType.TASK_COMPLETED      ──▶     task.lifecycle (status=completed)
EventType.DEVICE_CONNECTED    ──▶     device.presence (presence=online)
EventType.DEVICE_REGISTERED   ──▶     device.presence (presence=registered)
EventType.ACTION_EXECUTION_*  ──▶     action.command
EventType.COMMAND_RESULT      ──▶     task.lifecycle
```

M2 事件通过 `integration.event_bus.publish_m2_event()` 发布。  
旧 EventBus 发布路径不受影响。

---

## 扩展指南

添加新事件类型时：
1. 在 `contracts/event_schema.json` 的 `event_type.enum` 中追加新类型
2. 在本文档添加对应 payload 示例
3. 在 `tests/test_event_schema.py` 添加验证用例
