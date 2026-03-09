# Android Integration Protocol (AIP) v3.0 对齐文档

本文档描述 `ufo-galaxy-realization-v2`（服务端）与独立仓库 `DannyFish-11/ufo-galaxy-android`（Android APK）之间的通信协议规范。

> **最终标准（单一事实来源）**
>
> * **协议格式**：AIP v3.0（`galaxy_gateway/protocol/aip_v3.py`）
> * **WebSocket 主通道**：`/ws/device/{device_id}`（`galaxy_gateway/app.py`）
> * **REST 设备 API**：`/api/v1/devices/*`（`core/routes/devices.py`）
>
> 所有 incoming 消息无论原始版本（AIP/1.0、AIP/2.0、AIP/3.0）均经由 compat 层
> 规范化为 v3 标准字段后再交内部处理；服务端下发消息也统一使用 v3 格式。

---

## 目录

1. [完整 AIP v3.0 消息类型列表](#1-完整-aip-v30-消息类型列表)
2. [服务端 ↔ 客户端消息映射表](#2-服务端--客户端消息映射表)
3. [协议兼容层（Compat Layer）](#3-协议兼容层compat-layer)
4. [设备数据流与注册架构](#4-设备数据流与注册架构)
5. [标准端点一览](#5-标准端点一览)
6. [Node_113_AndroidVLM API 端点及调用链路](#6-node_113_androidvlm-api-端点及调用链路)
7. [Node_15_OCR UI 分析模式](#7-node_15_ocr-ui-分析模式)
8. [能力注册系统（OpenClaw 风格）](#8-能力注册系统openclaw-风格)

---

## 1. 完整 AIP v3.0 消息类型列表

### 设备管理

| 消息类型 | 方向 | 说明 |
|----------|------|------|
| `device_register` | Client → Server | 设备注册 |
| `device_register_ack` | Server → Client | 注册确认 |
| `device_unregister` | Client → Server | 设备注销 |
| `heartbeat` | Client → Server | 心跳保活 |
| `heartbeat_ack` | Server → Client | 心跳确认 |
| `device_status` | Client → Server | 设备状态上报 |
| `device_capabilities` | Client → Server | 设备能力上报 |

### 任务调度

| 消息类型 | 方向 | 说明 |
|----------|------|------|
| `task_submit` | Client → Server | 请求执行任务 |
| `task_assign` | Server → Client | 服务端分配任务 |
| `task_status` | Client ↔ Server | 任务状态查询/上报 |
| `task_result` | Client → Server | 任务执行结果 |
| `task_cancel` | Client ↔ Server | 取消任务 |
| `task_progress` | Client → Server | 任务进度上报 |
| `task_end` | Server → Client | 任务结束通知 |

### Agent 控制（与 AgentMessageHandler.kt 对齐）

| 消息类型 | 方向 | 说明 |
|----------|------|------|
| `agent_ping` | Client → Server | Agent 心跳探测 |
| `agent_config_update` | Server → Client | Agent 配置更新 |
| `agent_restart` | Server → Client | Agent 重启指令 |

### UI 树操作（与 AgentMessageHandler.kt 对齐）

| 消息类型 | 方向 | 说明 |
|----------|------|------|
| `ui_tree_request` | Server → Client | 请求 UI 树结构 |
| `action_execute` | Server → Client | 执行单个 UI 操作 |
| `action_sequence_execute` | Server → Client | 执行 UI 操作序列 |

### 应用/系统控制（与 AgentMessageHandler.kt 对齐）

| 消息类型 | 方向 | 说明 |
|----------|------|------|
| `app_start` | Server → Client | 启动应用 |
| `app_stop` | Server → Client | 停止应用 |
| `system_command` | Server → Client | 系统命令 |

### GUI 操作

| 消息类型 | 方向 | 说明 |
|----------|------|------|
| `gui_click` | Server → Client | 点击操作 |
| `gui_swipe` | Server → Client | 滑动操作 |
| `gui_input` | Server → Client | 文字输入 |
| `gui_scroll` | Server → Client | 滚动操作 |
| `gui_screenshot` | Server → Client | 截图请求 |
| `gui_element_query` | Server → Client | 元素查询 |
| `gui_element_wait` | Server → Client | 等待元素 |
| `gui_screen_content` | Client → Server | 屏幕内容上报 |

### 屏幕/媒体

| 消息类型 | 方向 | 说明 |
|----------|------|------|
| `screen_capture` | Server → Client | 屏幕截图 |
| `screen_stream_start` | Server → Client | 开始屏幕流 |
| `screen_stream_stop` | Server → Client | 停止屏幕流 |
| `screen_stream_data` | Client → Server | 屏幕流数据 |

### 命令执行

| 消息类型 | 方向 | 说明 |
|----------|------|------|
| `command` | Server → Client | 通用命令 |
| `command_result` | Client → Server | 命令结果 |
| `command_batch` | Server → Client | 批量命令 |

### 能力/诊断上报

| 消息类型 | 方向 | 说明 |
|----------|------|------|
| `capability_report` | Client → Server | 设备能力详细上报 |
| `capability_report_ack` | Server → Client | 能力上报确认 |
| `diagnostics_payload` | Client → Server | 设备诊断数据上报 |
| `diagnostics_payload_ack` | Server → Client | 诊断上报确认 |

### 视觉请求

| 消息类型 | 方向 | 说明 |
|----------|------|------|
| `vision_request` | Server → Client | 请求视觉分析 |
| `vision_result` | Client → Server | 视觉分析结果 |

### 错误处理

| 消息类型 | 方向 | 说明 |
|----------|------|------|
| `error` | Client ↔ Server | 错误通知 |
| `error_recovery` | Server → Client | 错误恢复指令 |

---

## 2. 服务端 ↔ 客户端消息映射表

### android_bridge.py（服务端）↔ AgentWebSocket.kt / AgentMessageHandler.kt（客户端）

| 服务端 `MessageType` 枚举值 | 客户端 Kotlin 对应 | 处理器方法 |
|-----------------------------|-------------------|------------|
| `DEVICE_REGISTER` | `AgentMessageHandler: device_register` | `_handle_device_register` |
| `DEVICE_HEARTBEAT` | `AgentWebSocket: heartbeat` | `_handle_heartbeat` |
| `TASK_SUBMIT` | `AgentMessageHandler: task_execute` | `_handle_task_execute` |
| `TASK_CANCEL` | `AgentMessageHandler: task_cancel` | `_handle_forward_log` |
| `TASK_STATUS` | `AgentMessageHandler: task_status_query` | `_handle_forward_log` |
| `TASK_RESULT` | `AgentMessageHandler: task_result` | `_handle_task_result` |
| `AGENT_PING` | `AgentMessageHandler: agent_ping` | `_handle_agent_ping` |
| `AGENT_CONFIG_UPDATE` | `AgentMessageHandler: agent_config_update` | `_handle_forward_log` |
| `AGENT_RESTART` | `AgentMessageHandler: agent_restart` | `_handle_forward_log` |
| `UI_TREE_REQUEST` | `AgentMessageHandler: ui_tree_request` | `_handle_forward_log` |
| `ACTION_EXECUTE` | `AgentMessageHandler: action_execute` | `_handle_forward_log` |
| `ACTION_SEQUENCE_EXECUTE` | `AgentMessageHandler: action_sequence_execute` | `_handle_forward_log` |
| `APP_START` | `AgentMessageHandler: app_start` | `_handle_forward_log` |
| `APP_STOP` | `AgentMessageHandler: app_stop` | `_handle_stop` |
| `SYSTEM_COMMAND` | `AgentMessageHandler: system_command` | `_handle_forward_log` |
| `GUI_CLICK` | `AIPMessageV3: gui_click` | — （服务端发送）|
| `GUI_SWIPE` | `AIPMessageV3: gui_swipe` | — （服务端发送）|
| `GUI_INPUT` | `AIPMessageV3: gui_input` | — （服务端发送）|
| `GUI_SCREENSHOT` | `AIPMessageV3: gui_screenshot` | — （服务端发送）|
| `ERROR` | `AIPMessageV3: error` | `_handle_error` |

---

## 3. 协议兼容层（Compat Layer）

**文件**：`galaxy_gateway/protocol/compat.py`

服务端接受来自 Android 客户端的多套历史消息格式，兼容层在内部统一转换为 AIP v3 标准字段，**内部处理模块只使用 v3 标准字段**。

### 版本检测规则

版本检测使用 **前缀匹配**（`str.startswith`）而非精确匹配，允许未来的小版本号（如 `"3.1"`）自动归入对应主版本：

| 原始 `version` 字段 | 判定版本 |
|---------------------|---------|
| 不存在 / 以 `"1"` 开头 | AIP/1.0 |
| 以 `"2"` 开头 | AIP/2.0 |
| 以 `"3"` 开头 | AIP/3.0 |

### Legacy `type` 字符串映射（AIP/1.0）

| Legacy type | 规范化 MessageType |
|-------------|-------------------|
| `register` / `agent_register` / `device_register` / `registration` | `device_register` |
| `heartbeat` / `agent_heartbeat` / `device_heartbeat` | `heartbeat` |
| `task_execute` | `task_submit` |
| `command_result` | `task_result` |
| `status_update` / `update_status` | `device_status` |

### 处理流程

```
Android APK (任意版本)
    │  发送 JSON (AIP/1.0 or 2.0 or 3.0)
    ▼
galaxy_gateway/transport/websocket_server.py
    │  parse_message_compat(raw_json)
    ▼
galaxy_gateway/protocol/compat.py
    │  版本检测 → normalise_v1 / normalise_v2 / passthrough_v3
    ▼
AIPMessage (v3 标准对象)
    │
    ▼
MessageHandler / DeviceManager (只处理 v3 字段)
```

### AIP v3 消息标准格式

```json
{
  "version": "3.0",
  "message_id": "<uuid>",
  "correlation_id": "<uuid>（可选，用于请求/响应关联）",
  "type": "<MessageType 枚举值>",
  "device_id": "<device_id>",
  "device_type": "<DeviceType 枚举值>（可选）",
  "timestamp": "<ISO 8601 UTC>",
  "task_id": "<uuid>（可选）",
  "task_status": "pending|running|completed|failed|cancelled（可选）",
  "commands": [{"command_id": "<uuid>", "tool_name": "screenshot", "parameters": {}}],
  "results": [{"command_id": "<uuid>", "status": "success|failure", "result": {}}],
  "payload": {},
  "error": "<错误信息（可选）>"
}
```

---

## 4. 设备数据流与注册架构

系统有两个独立的服务入口，各自维护独立的运行时设备状态；两者均使用同一套 AIP v3 协议。

```
┌────────────────────────────────────────────────────────┐
│               Android APK（客户端）                     │
└──────────┬──────────────────────────┬──────────────────┘
           │ WebSocket                │ REST HTTP
           │                          │
           ▼                          ▼
┌──────────────────────┐   ┌──────────────────────────────┐
│  galaxy_gateway/     │   │  core/api_routes.py          │
│  app.py (port 8765)  │   │  (port 8000)                 │
│                      │   │                              │
│  /ws/device/{id}  ◄──┘   │  POST   /api/v1/devices/     │
│  /ws/android         │   │         register             │
│  /ws/status (bcast.) │   │  GET    /api/v1/devices      │
│                      │   │  GET    /api/v1/devices/     │
│  parse_message_compat│   │         discover             │
│  ↓                   │   │  POST   /api/v1/devices/     │
│  DeviceManager       │   │         {id}/heartbeat       │
│  (handlers/)         │   │  POST   /api/v1/devices/     │
│                      │   │         status               │
│                      │   │  DELETE /api/v1/devices/{id} │
└──────────────────────┘   └──────────────────────────────┘
           │                          │
           └──────────┬───────────────┘
                      ▼
              AIP v3 内部处理
              （统一协议标准）
```

> **device_id 规范**：客户端自行生成唯一 `device_id`（推荐 UUID）并在注册时提交；
> 服务端以此为键维护设备状态，不会生成新的 ID。两个服务入口使用相同的 `device_id` 键空间。

---

## 5. 标准端点一览

### WebSocket 端点

| 端点 | 说明 |
|------|------|
| `ws://<host>:8765/ws/device/{device_id}` | **主通道**（推荐）：注册成功后的设备专属通道 |
| `ws://<host>:8765/ws/android` | 初始连接端点：设备注册及通用消息通道 |
| `ws://<host>:8765/ws/status` | 状态广播推送（只读订阅） |
| `ws://<host>:8765/ws/ufo3/{device_id}` | 向后兼容路径（等同于主通道） |

### REST API 端点（`/api/v1/devices/*`）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/devices/register` | 注册设备，返回 `server_version: "3.0.0"` |
| `GET` | `/api/v1/devices` | 列出所有设备 |
| `GET` | `/api/v1/devices/discover` | 按类型/能力/状态发现设备（支持 query 参数） |
| `GET` | `/api/v1/devices/{device_id}` | 获取单个设备详情 |
| `POST` | `/api/v1/devices/{device_id}/heartbeat` | REST 心跳（WebSocket 心跳更优） |
| `POST` | `/api/v1/devices/status` | 批量状态更新 |
| `DELETE` | `/api/v1/devices/{device_id}` | 注销设备（从注册表移除） |

### 向后兼容 REST 端点（旧 Android 客户端）

| 方法 | 路径 | 映射到 |
|------|------|--------|
| `POST` | `/api/devices/register` | `/api/v1/devices/register` |
| `GET` | `/api/devices/list` | `/api/v1/devices` |
| `POST` | `/api/devices/heartbeat` | `/api/v1/devices/{id}/heartbeat` |
| `POST` | `/api/devices/unregister` | 标记设备 offline |

---

## 6. Node_113_AndroidVLM API 端点及调用链路

`Node_113_AndroidVLM` 负责对 Android 设备屏幕进行 VLM 分析，运行在 `http://localhost:8113`（默认）。

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/analyze` | POST | 分析 Android 屏幕截图 |
| `/find_element` | POST | 智能查找 UI 元素 |
| `/suggest_action` | POST | 生成操作建议 |

### 调用链路

```
Android APK (ufo-galaxy-android)
    │  WebSocket (AIP v3.0)  →  /ws/device/{device_id}
    ▼
galaxy_gateway/android_bridge.py   ← 桥接层（AIP v3）
    │  HTTP POST /capture_screen
    ▼
Node_113_AndroidVLM (android_vlm_engine.py)
    │  HTTP POST /analyze
    ▼
Node_90_MultimodalVision            ← VLM 分析（Gemini/Qwen）
```

### 关键环境变量

```bash
# android_vlm_engine.py
ANDROID_AGENT_URL=http://<android_device_ip>:8033  # Android 设备代理地址（桥接层）
NODE_90_MULTIMODAL_VISION_URL=http://localhost:8090
VLM_PROVIDER=auto   # auto | gemini | qwen
```

---

## 7. Node_15_OCR UI 分析模式

Node_15_OCR 提供 Android UI 截图的文字识别能力，支持以下模式：

| 模式 | 说明 |
|------|------|
| `full_page` | 整页 OCR，返回所有文字 |
| `element_detect` | 检测 UI 元素边界框 |
| `text_region` | 指定区域 OCR |
| `table_extract` | 表格内容提取 |

---

## 8. 能力注册系统（OpenClaw 风格）

Android 设备注册时自动上报设备能力（`DeviceCapability` 位标志），服务端据此分配适合的任务。

### Android 设备默认能力

```python
DeviceCapability.NETWORK | DeviceCapability.STORAGE | DeviceCapability.COMPUTE |
DeviceCapability.GUI_READ | DeviceCapability.GUI_WRITE | DeviceCapability.GUI_SCREENSHOT |
DeviceCapability.INPUT_TOUCH | DeviceCapability.INPUT_VOICE |
DeviceCapability.SENSOR_GPS | DeviceCapability.SENSOR_CAMERA |
DeviceCapability.SENSOR_MIC | DeviceCapability.SENSOR_MOTION |
DeviceCapability.SYSTEM_NOTIFICATION |
DeviceCapability.COMM_BLUETOOTH | DeviceCapability.COMM_NFC | DeviceCapability.COMM_WIFI_DIRECT
```

### 能力与任务类型映射

| 能力标志 | 对应任务类型 |
|----------|------------|
| `GUI_SCREENSHOT` | 屏幕截图、VLM 分析 |
| `GUI_WRITE` | UI 自动化操作 |
| `INPUT_TOUCH` | 点击/滑动/手势 |
| `SENSOR_CAMERA` | 拍照、OCR |
| `SYSTEM_SHELL` | 系统命令执行 |

---

*最后更新：2026-03-07*
