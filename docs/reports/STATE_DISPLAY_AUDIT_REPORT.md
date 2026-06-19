# Galaxy V2 仓 — 全设备状态与消息显示方式排查报告

> 审计时间：2026-05-31
> 范围：Windows / Android / Wear OS / Home Assistant / Linux Agent

---

## 一、各设备状态与消息显示方式总览

### 1. Windows 桌面端（Electron + Three.js）

**状态显示方式：全屏 Three.js 3D 渲染**

| 三态 | 视觉表现 | 技术实现 |
|------|---------|---------|
| **SILENT** | 静态透明覆盖层 + 呼吸粒子头像 | `SilentState` 类，Canvas 2D 粒子系统 |
| **LIMINAL** | 透视隧道 + FOV 扭曲 + 液态墨水流 | `LiminalState` 类，自定义 Vertex/Fragment Shader |
| **MANIFEST** | CRT 显示器效果 + 打字机结果展示 | `ManifestState` 类，Three.js + DOM 叠加 |

**状态指示器**：面板底部三个点（StatusDots.tsx）
- ⚫ SILENT — 黑点，暗下去
- ⚪ LIMINAL — 白点 + 脉冲动画（box-shadow 呼吸）
- ⚫ MANIFEST — 灰点 + 稳定发光

**消息接收方式**：
```
WebSocket ws://localhost:8765/ws/desktop-presence
  → handleWebSocketMessage()
  → handleAIPV3StateEvent()  [AIP v3 STATE_EVENT 格式]
  → handlePhaseChange()       [legacy phase_change 格式]
  → enterState(phase)
```

**消息显示方式**：
- Phase 转换 → 全屏 3D 动画切换
- 任务结果 → MANIFEST 状态的 CRT 屏幕打字机效果
- 设备事件 → MANIFEST 短暂闪烁 3 秒后自动回到 SILENT

---

### 2. Android 手机/平板

**状态显示方式**：AIP v3 WebSocket → 原生 UI 渲染

**状态指示器**：与 Windows 相同的三点设计
- 接收 `state_event` 消息后更新 UI
- 通过 `android_bridge.py` 的 `handle_state_event()` 处理

**消息接收方式**：
```
WebSocket (AIP v3)
  → android_bridge.handle_message()
  → MessageType.STATE_EVENT → handle_state_event()
  → 存储 device.synced_phase
  → 返回 state_event_ack
```

**🔴 已修复的问题**：
- `MessageType.STATE_EVENT` 枚举缺失 → 已添加
- STATE_EVENT handler 未注册 → 已注册
- 注册后无初始 phase 推送 → 已添加
- 重连后无 phase 推送 → 已添加
- 断开时 synced_phase 未清理 → 已添加清理

---

### 3. Wear OS 手表

**状态显示方式**：Jetpack Compose for Wear OS

**状态指示器**：表盘风格三点（压缩格式）
- 接收压缩格式的 `state_event` 消息
- 仅同步 phase 变化（不接收完整任务状态）

**消息接收方式**：
```
WebSocket (AIP v3 简化子集)
  → AIPClient.handleMessage()
  → 解析 "state_event" 类型
  → 更新 Phase 状态
  → 触发 UI 重渲染
```

**消息显示方式**：
- 主界面三点指示器实时变化
- Tile 小部件显示当前 phase
- 语音输入结果通过 Toast 显示

---

### 4. Home Assistant

**状态显示方式**：Galaxy 作为 HA 的自定义集成

**状态同步方式**：
```
Galaxy SmartHomeGateway
  → HA WebSocket (state_event)
  → HA 实体状态更新
  → 用户可在 HA 前端查看/控制
```

**消息显示方式**：
- HA 前端显示 Galaxy 实体（sensor.galaxy_phase）
- 自动化可响应 phase 变化
- 语音控制通过 HA Assist

---

### 5. Linux Agent

**状态显示方式**：无 UI，纯命令行

**状态同步方式**：
```
NATS Bus
  → linux_agent 订阅状态主题
  → 命令行日志输出
```

**消息显示方式**：
- 日志文件记录
- 命令行 stdout 输出
- 可通过 SSH 查看实时状态

---

## 二、状态同步链路完整性

### 同步触发点

| 触发场景 | Windows 推送 | Android 接收 | Wear OS 接收 |
|---------|-------------|-------------|-------------|
| Phase 转换 | ✅ `emit_cross_device_phase_sync()` | ✅ `handle_state_event()` | ⚠️ 需客户端适配 |
| 设备注册 | ✅ 注册后推送初始 phase | ✅ 存储 `synced_phase` | ⚠️ 需客户端适配 |
| 设备重连 | ✅ 重连后推送当前 phase | ✅ 更新 `synced_phase` | ⚠️ 需客户端适配 |
| 设备断开 | ✅ — | ✅ 清理 `synced_phase` | ⚠️ 需客户端适配 |

### 事件格式

**Windows → Android（AIP v3 STATE_EVENT）**：
```json
{
  "type": "state_event",
  "event_category": "phase",
  "event_action": "manifest",
  "device_id": "v2_desktop",
  "timestamp": 1700000000000,
  "session_id": "...",
  "trace_id": "...",
  "aip_version": "3.0",
  "payload": {
    "from_phase": "liminal",
    "to_phase": "manifest",
    "source": "desktop_presence_runtime",
    "sync_type": "cross_device_broadcast"
  },
  "phase": "manifest"
}
```

**Android 响应（ACK）**：
```json
{
  "type": "state_event_ack",
  "device_id": "v2_desktop",
  "status": "received",
  "event_category": "phase",
  "event_action": "manifest"
}
```

---

## 三、状态一致性保证

### 1. 心跳机制

```python
# WebSocket 心跳（galaxy_gateway/routes/websocket.py）
{
  "type": "ping",
  "timestamp": 1700000000000
}
# 响应
{
  "type": "pong", 
  "timestamp": 1700000000000
}
```

### 2. 状态重同步

- 设备注册后自动推送当前 phase
- 设备重连后自动推送当前 phase
- 设备断开时清理状态

### 3. 事件总线（StateEventBus）

```python
# core/state_event_bus.py
bus = get_state_event_bus()
bus.subscribe(StateEventType.PHASE_LIMINAL, my_handler)
bus.publish(StateEventType.PHASE_LIMINAL, source="desktop", payload={...})
```

---

## 四、发现的问题与修复

### 🔴 CRITICAL（已修复）

| 问题 | 影响 | 修复 |
|------|------|------|
| MessageType.STATE_EVENT 枚举缺失 | Windows → Android 同步完全失效 | 已添加到 aip_v3.py |
| STATE_EVENT handler 未注册 | 消息被丢弃，返回 UNKNOWN_MESSAGE_TYPE | 已注册 handle_state_event |

### 🟡 缺失（已修复）

| 问题 | 影响 | 修复 |
|------|------|------|
| 注册后无初始 phase 推送 | 新设备不知道当前状态 | registration.py 注册后推送 |
| 重连后无 phase 推送 | 重连设备状态不同步 | reconnect_device() 推送 |
| 断开时未清理 synced_phase | 残留旧状态 | disconnect_device() 清理 |

### ⚠️ 待 Wear OS 客户端适配

- 需要在 AIPClient.kt 中添加 `state_event` 类型解析
- 需要更新 Phase 指示器 UI 组件

---

## 五、新增文件

| 文件 | 说明 |
|------|------|
| `galaxy_gateway/android/handlers/state_event.py` | STATE_EVENT handler |
| `galaxy_gateway/android/handlers/wearos_sync.py` | Wear OS 压缩格式同步 |

---

*报告生成时间：2026-05-31*
