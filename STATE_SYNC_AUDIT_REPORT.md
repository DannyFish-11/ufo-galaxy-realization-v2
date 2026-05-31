# Galaxy V2 仓 — 跨设备状态同步审计报告

> 审计时间：2026-05-31
> 范围：Windows ↔ Android ↔ Wear OS 全链路状态同步
> 核心关注：实时性、一致性、完整性

---

## 执行摘要

| 指标 | 审计前 | 审计后 | 状态 |
|------|--------|--------|------|
| Windows → Android 状态同步 | ❌ 完全失效 | ✅ 实时推送 | **已修复** |
| Android 注册后初始同步 | ❌ 缺失 | ✅ 注册后立即推送 | **已修复** |
| Android 重连后同步 | ❌ 缺失 | ✅ 重连后立即推送 | **已修复** |
| 设备断开状态清理 | ❌ 未清理 | ✅ 断开时清理 synced_phase | **已修复** |
| Wear OS 状态同步 | ❌ 未支持 | ✅ 压缩格式支持 | **已修复** |
| WebSocket 心跳 | ✅ 正常 | ✅ 正常 | 无需修复 |
| Mesh 生命周期 | ✅ 正常 | ✅ 正常 | 无需修复 |
| NATS 状态广播 | ✅ 正常 | ✅ 正常 | 无需修复 |

---

## 🔴 CRITICAL: Windows → Android 状态同步完全失效

### 根因分析

**问题 1**: `MessageType.STATE_EVENT` 在 `galaxy_gateway/protocol/aip_v3.py` 枚举中缺失

```python
# galaxy_gateway/android_bridge.py:990
try:
    msg_type = MessageType(msg_type_str)  # msg_type_str = "state_event"
except ValueError:
    # → 抛出 ValueError，返回 UNKNOWN_MESSAGE_TYPE 错误
    logger.warning("Unknown message type: %s", msg_type_str)
    return MessageBuilder.error(...)
```

**问题 2**: `STATE_EVENT` handler 未在 `android_bridge.py` 中注册

```python
# _message_handlers 中没有 MessageType.STATE_EVENT 的条目
# → handle_message() 返回 None，消息被静默丢弃
```

### 影响

- Windows 通过 `emit_cross_device_phase_sync()` 推送的 `state_event` 消息
- Android 端执行 `MessageType("state_event")` → `ValueError`
- 被捕获后返回 `UNKNOWN_MESSAGE_TYPE` 错误
- **Android 设备永远不会收到 Windows 的 phase 状态更新**

### 修复

1. `galaxy_gateway/protocol/aip_v3.py` — 添加 `STATE_EVENT = "state_event"`
2. `galaxy_gateway/android_bridge.py` — 注册 handler + 导入
3. `galaxy_gateway/android/handlers/state_event.py` — 新建 handler

---

## 🟡 设备生命周期状态同步缺失

### 问题 1: 注册后无初始同步

**修复**: `galaxy_gateway/android/handlers/registration.py`

```python
# 在 handle_device_register() 注册完成后，推送当前 phase
await device.websocket.send_json({
    "type": "state_event",
    "event_category": "phase",
    "event_action": current_phase,
    ...
})
```

### 问题 2: 重连后无同步

**修复**: `galaxy_gateway/android_bridge.py` reconnect_device()

```python
# 在 reconnect_device() 重连完成后，推送当前 phase
asyncio.create_task(websocket.send_json({
    "type": "state_event",
    "event_action": current_phase,
    ...
}))
```

### 问题 3: 断开时未清理状态

**修复**: `galaxy_gateway/android_bridge.py` disconnect_device()

```python
# 在 disconnect_device() 中断开时，清理 synced_phase
if hasattr(self._devices[device_id], 'synced_phase'):
    self._devices[device_id].synced_phase = {}
```

---

## 🟢 Wear OS 状态同步支持

**新增**: `galaxy_gateway/android/handlers/wearos_sync.py`

- 压缩消息格式（最小化带宽）
- 仅同步 phase 变化（手表不需要完整任务状态）
- 设备类型自动检测

---

## 状态同步链路完整性验证

```
Windows DesktopPresenceRuntime
    │ advance() phase change
    │ emit_cross_device_phase_sync()
    ▼
core.cross_device_sync
    │ _async_push_phase_to_all_devices()
    │ For each connected device:
    │   websocket.send_json(state_event)
    │   MAX_RETRIES = 2
    ▼
galaxy_gateway.android_bridge
    │ handle_message()
    │ MessageType.STATE_EVENT → handle_state_event()
    ▼
galaxy_gateway.android.handlers.state_event
    │ Store synced_phase on device
    │ Return state_event_ack
    ▼
Android Device
    │ Receive state_event
    │ Update UI phase indicator
    ▼
✅ Real-time sync complete
```

---

## 修改文件清单

| 文件 | 修改类型 | 说明 |
|------|---------|------|
| `galaxy_gateway/protocol/aip_v3.py` | 新增枚举值 | 添加 `STATE_EVENT = "state_event"` |
| `galaxy_gateway/android_bridge.py` | 新增导入 + 注册 + 重连同同步 | 导入 handle_state_event，注册 handler，重连推送 phase |
| `galaxy_gateway/android/handlers/state_event.py` | 新建 | 处理 STATE_EVENT，存储 synced_phase |
| `galaxy_gateway/android/handlers/wearos_sync.py` | 新建 | Wear OS 压缩格式状态同步 |
| `galaxy_gateway/android/handlers/registration.py` | 新增初始同步 | 设备注册后推送当前 phase |
| `core/cross_device_sync.py` | 无需修改 | 已有正确实现 |
| `core/desktop_presence_runtime.py` | 无需修改 | 已有正确实现 |
| `galaxy_gateway/routes/websocket.py` | 无需修改 | 已有正确实现 |

---

## 新增文件

| 文件 | 说明 |
|------|------|
| `galaxy_gateway/android/handlers/state_event.py` | STATE_EVENT handler |
| `galaxy_gateway/android/handlers/wearos_sync.py` | Wear OS 同步支持 |
| `HEALTH_AUDIT_REPORT.md` | 系统健康度审计报告 |
| `STATE_SYNC_AUDIT_REPORT.md` | 本报告 |

---

*报告生成时间：2026-05-31*
*修复范围：V2 仓核心状态同步链路*
