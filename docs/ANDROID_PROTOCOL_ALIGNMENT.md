# Android Integration Protocol (AIP) v3.0 对齐文档

本文档描述 `ufo-galaxy-realization-v2`（服务端）与独立仓库 `DannyFish-11/ufo-galaxy-android`（Android APK）之间的通信协议规范。

> **最终标准（单一事实来源）**
>
> * **协议格式**：AIP v3.0（`galaxy_gateway/protocol/aip_v3.py`）
> * **WebSocket 主通道**：`/ws/device/{device_id}`（`galaxy_gateway/app.py`）
> * **REST 设备 API**：`/api/v1/devices/*`（`core/routes/devices.py`）
>
> **⚠️ 强制要求（Round 2 / AIP v3 enforcement）：**
>
> * 所有连接和消息必须携带 `"version": "3.0"`（或更高版本）。  
>   缺失或低于 3.0 的消息将被 **直接拒绝**：WebSocket 连接收到 `code=4000` 关闭帧；HTTP 请求收到 400 响应。
> * 每条消息必须携带 `trace_id`（UUID）和 `route_mode`（`"cross_device"` 或 `"local"`）。  
>   若缺失，服务端会自动注入默认值并记录结构化日志；客户端应尽量主动携带以保持可追踪性。
>
> 服务端下发消息统一使用 v3 格式；响应中会透传请求携带的 trace_id 和 route_mode。

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
9. [Android↔Server 完整集成说明](#9-androidserver-完整集成说明)
10. [JSON Schema 参考与 v3 Payload 示例](#10-json-schema-参考与-v3-payload-示例)

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

## 9. Android↔Server 完整集成说明

本节描述从 Android 设备连接到自然语言命令执行的完整闭环路径。

### 9.1 官方 WebSocket 入口（唯一权威来源）

| 路径 | 说明 | 推荐度 |
|------|------|--------|
| `ws://<host>:8765/ws/device/{device_id}` | **主通道**（推荐）：设备注册后的专属通道 | ✅ 推荐 |
| `ws://<host>:8765/ws/android` | 初始连接端点：自动分配设备 ID | ✅ 支持 |
| `ws://<host>:8765/ws/ufo3/{device_id}` | 向后兼容路径（等同于主通道） | ⚠️ 兼容 |

> **Android 客户端应统一使用主通道 `/ws/device/{device_id}`。**
> 以上所有路径均路由到 `galaxy_gateway/app.py` 中同一个 `WebSocketManager.handle_connection()` 处理器。

### 9.2 AIP v3.0 必填字段

每条消息（无论方向）必须包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `version` | `string` | 协议版本，固定为 `"3.0"` |
| `type` | `string` | 消息类型（见第 1 节完整列表） |
| `message_id` | `string` | 消息唯一 ID（UUID） |
| `device_id` | `string` | 发送方设备 ID |
| `timestamp` | `integer` | 毫秒级 Unix 时间戳 |

**缺少 `type` 或 `device_id` 时，服务端返回 `error` 消息（`error_code: MISSING_REQUIRED_FIELDS`）。**  
缺少 `version`、`timestamp`、`message_id` 时，服务端自动补全（向后兼容旧客户端）。

### 9.3 Legacy AIP/1.0 兼容映射

`galaxy_gateway/android_bridge.py` 的 `handle_message()` 通过
`galaxy_gateway/protocol/compat.py` 自动规范化旧协议消息：

| AIP/1.0 type 字段 | 规范化为（AIP v3.0） |
|-------------------|---------------------|
| `register` / `agent_register` / `registration` | `device_register` |
| `heartbeat` / `agent_heartbeat` | `heartbeat` |
| `task_execute` | `task_submit` |
| `command_result` | `task_result` |
| `status_update` / `update_status` | `device_status` |

规范化时同时自动补全 `version: "3.0"`、`timestamp`、`message_id`（如缺失）。

### 9.4 能力同步到 LLM（capability → CapabilityRegistry → tool schema）

```
Android 设备
  │
  ├─ device_register  ──────────► AndroidBridge._handle_device_register()
  │                                └─ 设备存入 AndroidBridge._devices
  │
  └─ capability_report ─────────► AndroidBridge._handle_capability_report()
                                   ├─ 更新 device.supported_actions
                                   └─ CapabilityRegistry.register(CapabilityItem)
                                        能力名: gateway__<device_id>__<action>
                                        来源:   source="gateway"
                                             │
                                             ▼
                                      ExecutionPlanner.prepare()
                                        ├─ CapabilityRegistry.refresh()
                                        └─ to_tool_schemas() → LLM function calling
```

**能力命名规则**（稳定、可预测，适用于 LLM tool schema）：

```
gateway__<device_id>__<action_name>
```

示例：
- `gateway__pixel9-001__screenshot`
- `gateway__pixel9-001__tap`
- `gateway__pixel9-001__swipe`

### 9.5 自然语言 → 设备执行完整链路

```
用户输入 (自然语言)
  │
  ▼
POST /api/v1/chat
  │
  ▼
OpenClawd.handle_request()
  │
  ▼
ExecutionPlanner.prepare()
  ├─ CapabilityRegistry.refresh()   ← 拉取最新设备能力
  └─ to_tool_schemas()              ← 注入 LLM function calling
  │
  ▼
LLM 推理 → tool_call: { "name": "gateway__<id>__screenshot", "arguments": {...} }
  │
  ▼
OpenClawd._dispatch_tool_call()
  │
  ▼
send_gateway_command(device_id, command, payload)
  │
  ▼
CommandRouter.route_command()
  │
  ▼
AndroidBridge.assign_task(device_id, task_id, task_type, payload)
  │
  ▼
WebSocket push → Android 设备执行
  │
  ▼
task_result → AndroidBridge._handle_task_result() → 返回结果
```

### 9.6 Android 仓库需要的适配说明（PR Notes）

本 PR 仅修改服务端（`ufo-galaxy-realization-v2`）。Android 仓库（`ufo-galaxy-android`）
如需完整对接，应确认以下内容（无需在本 PR 内修改）：

1. **统一使用 AIPMessageBuilder**，并确保发送完整 v3 字段：
   `version: "3.0"`、`message_id`（UUID）、`timestamp`（毫秒）、`device_id`、`type`。

2. **连接路径**：统一配置为 `ws://<host>:8765/ws/device/{device_id}`。

3. **capability_report 消息**在设备连接后立即发送，`supported_actions` 列表应枚举
   设备实际支持的操作名称（如 `["screenshot", "tap", "swipe", "input_text"]`）。

4. **task_result 回执**：任务执行完毕后及时发送 `task_result`，包含 `task_id`
   和 `status` 字段，使服务端可解析并通知 LLM。

---

## 10. JSON Schema 参考与 v3 Payload 示例

> **权威性声明（PR-S5）**：AIP v3.0 是 Galaxy 协议的**唯一事实来源**。
> 本节 JSON Schema 文件是对 `galaxy_gateway/protocol/aip_v3.py` 中 Pydantic
> 模型的正式机器可读描述。传统（legacy）客户端发送的 AIP/1.x、AIP/2.x 消息，
> 由 `galaxy_gateway/protocol/compat.py` 自动转换为 v3 后再进入业务逻辑。

### 10.1 Schema 文件索引

所有 JSON Schema 文件位于 `galaxy_gateway/protocol/schemas/`：

| 文件 | 消息类型 | 说明 |
|------|---------|------|
| `aip_envelope.schema.json` | (所有) | v3 消息通用信封，包含所有共享字段 |
| `device_register.schema.json` | `device_register` | 设备注册（Client → Server） |
| `heartbeat.schema.json` | `heartbeat` | 心跳保活（Client → Server） |
| `capability_report.schema.json` | `capability_report` | 能力上报（Client → Server） |
| `task_assign.schema.json` | `task_assign` | 任务分配（Server → Client） |
| `command_result.schema.json` | `command_result` | 命令结果（Client → Server） |

### 10.2 v3 必填字段（全消息类型通用）

每条 AIP v3 消息**必须**包含以下三个字段：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `version` | `string` | 模式 `^3\.`，如 `"3.0"` | 协议版本，compat 层将旧版自动升级 |
| `type` | `string` | `MessageType` 枚举值之一 | 消息类型鉴别符 |
| `device_id` | `string` | 非空 | 发送方设备唯一标识 |

`capability_report` 还额外要求（v3 新增强制要求）：

| 字段 | 类型 | 约束 |
|------|------|------|
| `platform` | `string` | `"android"` / `"ios"` / `"windows"` / … |
| `supported_actions` | `string[]` | 至少包含 1 个元素 |

### 10.3 v3 Payload 示例

#### device_register

```json
{
  "version": "3.0",
  "type": "device_register",
  "device_id": "android-abc123",
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-01-01T00:00:00Z",
  "trace_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "route_mode": "cross_device",
  "device_type": "android_phone",
  "platform": "android",
  "name": "My Phone",
  "model": "Pixel 7",
  "os_version": "Android 14",
  "sdk_version": 34,
  "capabilities": 1023
}
```

#### heartbeat

```json
{
  "version": "3.0",
  "type": "heartbeat",
  "device_id": "android-abc123",
  "message_id": "550e8400-e29b-41d4-a716-446655440001",
  "timestamp": "2026-01-01T00:01:00Z",
  "trace_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c9",
  "route_mode": "cross_device"
}
```

#### capability_report（v3 强制要求 platform + supported_actions）

```json
{
  "version": "3.0",
  "type": "capability_report",
  "device_id": "android-abc123",
  "platform": "android",
  "supported_actions": ["tap", "swipe", "screenshot", "long_press", "input_text"],
  "capability_version": "1.0",
  "message_id": "550e8400-e29b-41d4-a716-446655440002",
  "timestamp": "2026-01-01T00:02:00Z",
  "trace_id": "6ba7b810-9dad-11d1-80b4-00c04fd430ca",
  "route_mode": "cross_device",
  "capability_schemas": [
    {
      "action": "tap",
      "params": {
        "type": "object",
        "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
        "required": ["x", "y"]
      },
      "exec_mode": "remote",
      "tags": ["ui", "touch"]
    }
  ]
}
```

#### task_assign（Server → Client）

```json
{
  "version": "3.0",
  "type": "task_assign",
  "device_id": "android-abc123",
  "task_id": "task-550e8400",
  "task_type": "ui_automation",
  "payload": {"action": "tap", "x": 540, "y": 960},
  "priority": 5,
  "timeout": 30,
  "message_id": "550e8400-e29b-41d4-a716-446655440003",
  "timestamp": "2026-01-01T00:03:00Z",
  "trace_id": "6ba7b810-9dad-11d1-80b4-00c04fd430cb",
  "route_mode": "cross_device"
}
```

#### command_result（Client → Server）

```json
{
  "version": "3.0",
  "type": "command_result",
  "device_id": "android-abc123",
  "task_id": "task-550e8400",
  "task_status": "completed",
  "results": [
    {
      "command_id": "cmd-001",
      "status": "success",
      "result": {"screenshot_path": "/sdcard/screenshots/shot001.png"},
      "execution_time": 0.45
    }
  ],
  "message_id": "550e8400-e29b-41d4-a716-446655440004",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440003",
  "timestamp": "2026-01-01T00:03:01Z",
  "trace_id": "6ba7b810-9dad-11d1-80b4-00c04fd430cb",
  "route_mode": "cross_device"
}
```

### 10.4 Legacy → v3 自动转换路径

`compat.py` 在消息到达任何业务处理器**之前**完成自动升级，业务代码始终只看到 v3 `AIPMessage`：

```
Android APK（任意 AIP 版本）
    │  发送 JSON（AIP/1.0 或 2.0 或 3.0）
    ▼
galaxy_gateway/protocol/compat.parse_message_compat()
    ├─ AIP/1.0（type 别名映射 + version 升级到 "3.0"）
    │     "register"        → "device_register"
    │     "agent_heartbeat" → "heartbeat"
    │     "task_execute"    → "task_submit"
    │     "command_result"  → "task_result"  ← 旧版 type 字面值，映射到 v3 task_result
    │     "response"        → "command_result"  ← v2 transport alias，映射到 v3 command_result
    │     "status_update"   → "device_status"
    │
    │  注：上表中的 "command_result" 是 **AIP/1.0 的 type 字段值**，会被规范化为
    │  v3 的 "task_result"（任务结果汇报）。而 v3 协议本身也有独立的 "command_result"
    │  类型（命令级执行结果），两者含义不同——这是 AIP/1.x→v3 迁移中的历史遗留命名差异。
    ├─ AIP/2.0（仅将 version 字段升级到 "3.0"）
    └─ AIP/3.0（直接传递，不修改）
    │
    │  inject_trace_metadata()  ← 自动注入 trace_id / route_mode（如缺失）
    │
    ▼
AIPMessage（v3 Pydantic 对象）
    │
    ▼
业务处理器（android_bridge / device_communication 等）
```

> **注意**：`platform`、`supported_actions`、`capability_version` 等业务字段
> **不会** 由 compat 层自动补充，发送 `capability_report` 的客户端必须主动包含这些字段。

### 10.5 Schema 验证测试

运行以下命令验证所有 schema 文件加载正常、示例数据通过验证：

```bash
python -m pytest tests/test_v3_schemas.py -v
```

测试覆盖：

* 每个 schema 文件是合法 JSON 且加载无误
* 每个 schema 内嵌 `examples` 通过验证（正向测试）
* 缺少 `version`、`device_id`、`platform`、`supported_actions` 等必填字段时验证拒绝（负向测试）
* `version: "2.0"` 被拒绝（AIP/2.x 须先经 compat 转换再到达 handler）

---

*最后更新：2026-03-16*
