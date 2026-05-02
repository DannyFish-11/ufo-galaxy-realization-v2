# Android 开启跨设备后能接管整个系统吗？页面/操作面完成度是多少？

> **说明**：本文档基于 `DannyFish-11/ufo-galaxy-realization-v2` 和 `DannyFish-11/ufo-galaxy-android` 两个仓库的**真实源代码**写成，不依赖历史文档或推测。所有结论均可追溯至具体文件和类名。
>
> **日期**：2026  
> **范围**：跨设备能力分析 + 页面/操作面完成度清单

---

## 目录

1. [问题重述](#1-问题重述)
2. [Android 开启跨设备后到底能做什么](#2-android-开启跨设备后到底能做什么)
3. [Android 不能替代什么——当前上限](#3-android-不能替代什么当前上限)
4. [当前页面 / 操作面 / 控制面完成度清单](#4-当前页面--操作面--控制面完成度清单)
5. [现在真实可用的控制体验说明](#5-现在真实可用的控制体验说明)
6. [最终中文结论](#6-最终中文结论)

---

## 1. 问题重述

用户的两个核心问题：

1. **Android 开启跨设备模式后，能接管/操控整个系统吗？如果可以，程度如何？如果不完全可以，当前限制在哪里？**
2. **页面层/操作面/可用控制面的真实当前完成度是什么？现在哪些页面或 API/操作面是真实存在的，哪些是缺失的，完成度到底有多高？**

---

## 2. Android 开启跨设备后到底能做什么

### 2.1 "开启跨设备"在代码里是什么意思

**代码证据：**

- `ufo-galaxy-android/config.properties:17`：
  ```
  cross_device_enabled=false  # 出厂默认为 false
  ```
- `ufo-galaxy-android/app/build.gradle`：
  ```groovy
  buildConfigField "Boolean", "CROSS_DEVICE_ENABLED", "false"  // debug 编译默认
  ```
- `com.ufo.galaxy.network.GalaxyWebSocketClient.kt:569`：
  **当 `CROSS_DEVICE_ENABLED=false` 时，`GalaxyWebSocketClient` 跳过所有 WebSocket 连接尝试。**

- `core/cross_device_integration_reality.py`：
  ```python
  ANDROID_CROSS_DEVICE_DISABLED_BY_DEFAULT: bool = True  # 出厂默认关闭
  ANDROID_DEFAULT_URL_IS_PLACEHOLDER: bool = True        # 默认 URL 是 Tailscale 占位符
  ```

**结论：** "开启跨设备"具体指：
1. 在 Android 设备上打开 `cross_device_enabled` 开关（SharedPreferences 或 Settings 界面）
2. 正确配置服务器地址（默认是 Tailscale 占位 IP，必须手动改成真实地址）
3. 确保 V2 网关在 `8765` 端口可达

### 2.2 开启跨设备后 Android 获得的能力

#### 能力一：作为连接设备节点（Connected Device Node）

**代码：`core/android_runtime_host.py`**

```python
class AndroidRuntimeHostRole(str, Enum):
    FULL_RUNTIME_HOST = "full_runtime_host"     # 完整运行时主机
    PARTIAL_RUNTIME_HOST = "partial_runtime_host"  # 部分运行时主机
    CONNECTED_DEVICE_ONLY = "connected_device_only"  # 仅作为连接设备
    UNCLASSIFIED = "unclassified"
```

Android 连接后会被分类为上述角色之一，取决于注册时的 `source_runtime_posture` 字段：
- `"join_runtime"` → `FULL_RUNTIME_HOST`
- 仅有自治标志但无明确 posture → `PARTIAL_RUNTIME_HOST`
- 其他情况 → `CONNECTED_DEVICE_ONLY`

#### 能力二：作为本地 AI 执行节点（Local AI Execution Node）

**代码：`ufo-galaxy-android`（`NativeInferenceLoader`、`LocalInferenceRuntimeManager`）**

Android 在本地可运行：
- MobileVLM V2-1.7B（通过 llama.cpp，Q4_K 量化，约 900MB）
- SeeClick NCNN（通过 NCNN 推理引擎，约 450MB）

本地推理的就绪条件：
- `NativeInferenceLoader.loadAll()` 成功（`llamaCppAvailable=true` 或 `ncnnAvailable=true`）
- `ReadinessState.modelReady=true`（模型文件下载并校验通过）
- `ReadinessState.accessibilityReady=true`（无障碍服务已授权）
- `LocalLoopReadiness` 通过 `LocalLoopReadinessProvider` 检查

**重要：** 这些就绪状态**仅在 Android 本地可见**，V2 中心侧**目前无法获知**。

#### 能力三：作为跨设备执行参与者（Cross-Device Participant）

**代码：`core/android_delegated_runtime_lifecycle_coordinator.py`、`core/android_participant_session_state.py`**

Android 参与跨设备执行的完整生命周期：
```
pre_dispatch → handoff_dispatched → takeover_pending →
takeover_accepted → execution → reconciling →
terminal_success / terminal_failure / terminal_cancelled
```

V2 通过以下模块协调：
- `AndroidDelegatedRuntimeLifecycleCoordinator`（统一生命周期门面）
- `FlowLevelOperatorSurface`（流级执行投影）
- `AndroidCanonicalExecutionEvent`（标准执行事件）

**Android 执行阶段（AndroidExecutionPhase）：**
```python
# core/flow_level_operator_surface.py
planning | grounding | execution | replan | stagnation | gate_decision | completed | failed
```

这些阶段可由 V2 侧的 `FlowOperatorProjection` 接收，**但前提是 Android 端必须通过 WebSocket 消息正确发射这些事件**（目前管道完整性**尚未完全确认**）。

#### 能力四：WebSocket 协议接入

**代码：`galaxy_gateway/routes/websocket.py`、`core/cross_device_integration_reality.py`**

```python
WS_TRANSPORT_PROTOCOL_ALIGNED: bool = True
CANONICAL_WS_DEVICE_PATH: str = "/ws/device/{device_id}"
CANONICAL_GATEWAY_PORT: int = 8765
AUTH_BEARER_TOKEN_SUPPORTED: bool = True
```

Android 通过 AIP v3.0 协议连接，消息格式：
```json
{
  "version": "3.0",
  "type": "<message_type>",
  "message_id": "<uuid>",
  "device_id": "<device_id>",
  "timestamp": 1234567890000
}
```

已处理的消息类型：
```python
# core/cross_device_integration_reality.py
ANDROID_REPORT_TYPES_NOW_HANDLED = [
    "cancel_result",
    "device_readiness_report",
    "device_governance_report",
    "device_acceptance_report",
    "device_strategy_report",
]
GOAL_RESULT_ALIAS_HANDLED: bool = True
```

#### 能力五：离线任务队列与重连恢复

**代码：`galaxy_gateway/pending_delivery_buffer.py`、`ufo-galaxy-android/GalaxyWebSocketClient.kt`**

```python
PENDING_DELIVERY_BUFFER_PRESENT: bool = True
PENDING_DELIVERY_BUFFER_TTL_S: float = 60.0
PENDING_DELIVERY_BUFFER_MAX_QUEUE_PER_DEVICE: int = 32
DURABLE_PENDING_DELIVERY_BUFFER_PRESENT: bool = True  # 支持 V2 重启后恢复
```

- Android 断线后 V2 侧会缓冲最多 32 条待发送消息（TTL 60 秒）
- Android 端也有 `OfflineTaskQueue` 用于本地离线队列

---

## 3. Android 不能替代什么——当前上限

### 3.1 Android 无法替代 V2 成为中心权威

**代码证据：**

以下组件明确属于 V2 中心，Android 无法替代：

| 组件 | 文件 | 职责 |
|------|------|------|
| `DesktopPresenceRuntime` | `core/desktop_presence_runtime.py` | 主体三态生命周期（SILENT/LIMINAL/MANIFEST）的唯一所有者 |
| `OpenClawd` | `core/openclawd.py` | 认知/执行核心，V2 中心侧 |
| `CanonicalTaskRuntime` | `core/canonical_task.py` | 任务生命周期的真相来源 |
| `MultiLLMRouter` | `core/multi_llm_router.py` | LLM 路由决策，中心侧执行 |
| `OperatorSurface` | `core/operator_surface.py` | 第 10 层操作面，只读投影，仅在 V2 |
| `TaskGraphRuntime` | `core/task_graph_runtime.py` | 任务图运行时 |
| `NetworkTopologyRuntime` | `core/network_topology_runtime.py` | 网络拓扑，中心管理 |
| `CapabilityAssimilationLayer` | `core/capability_assimilation.py` | 能力注册与路由策略 |

**`DesktopPresenceRuntime` 的三态完全中心控制：**

```python
# core/desktop_presence_runtime.py
class TriState(Enum):
    SILENT   = "silent"    # 主体静止
    LIMINAL  = "liminal"   # OpenClawd 认知/执行中
    MANIFEST = "manifest"  # 主体正在产出输出/控制设备
```

Android 无法设置或驱动这个三态——只能被动接收任务、发射执行事件。

### 3.2 Android 无法做到的事

1. **Android 不能主动发起任务**——任务发起权在 V2 侧
2. **Android 不能控制 LLM 路由**——路由决策由 `MultiLLMRouter` 在 V2 中心执行
3. **Android 不能查看或修改 V2 的 TriState**
4. **Android 不能访问 V2 的 OperatorSurface**——没有 Android 侧操作面 API
5. **Android 不能读取 V2 的 ReadinessMatrix**
6. **Android 不能直接控制其他已注册 Android 设备**
7. **Android 不能替代 V2 作为 API 网关**

### 3.3 四种角色的精确区分

| 角色 | 代码依据 | 当前状态 |
|------|---------|---------|
| **Android 作为运行时节点** | `AndroidRuntimeHostRole.FULL_RUNTIME_HOST` | ✅ 架构已实现，注册流程已就绪 |
| **Android 作为本地 AI 执行节点** | `NativeInferenceLoader`、`LocalInferenceRuntimeManager` | ✅ 本地推理链完整，但就绪状态未上报给 V2 |
| **Android 作为跨设备参与者** | `AndroidDelegatedRuntimeLifecycleCoordinator`、`FlowLevelOperatorSurface` | ⚠️ 架构存在，执行事件上报管道尚未完全确认 |
| **Android 作为系统治理替代者** | — | ❌ 完全不存在此能力，设计上也无此意图 |

### 3.4 当前最大上限（代码证据）

```python
# core/cross_device_integration_reality.py
ANDROID_MAX_RECONNECT_ATTEMPTS: int = 10  # 10 次重连失败后永久停止
ANDROID_RECONNECT_STOPS_PERMANENTLY_AT_LIMIT: bool = True
REMOTE_ACCESS_REQUIRES_TAILSCALE_OR_VPNISH: bool = True  # 远程访问需要 VPN
```

- Android 重连失败超过 10 次（约 181 秒）后会永久停止，需手动重启
- V2 没有内置 STUN/TURN 机制，远程使用必须走 Tailscale 或 VPN
- Android 本地状态（模型就绪、推理可用性等）V2 完全看不见

---

## 4. 当前页面 / 操作面 / 控制面完成度清单

### 4.1 已可用（Currently Usable）

| 面 / 接口 | 文件 | 说明 |
|-----------|------|------|
| `GET /api/v1/operator/snapshot` | `core/routes/operator.py` | 返回 `OperatorSnapshot`：活跃任务数、在线设备数、拓扑节点数、能力提供商数 |
| `GET /api/v1/operator/inspect/task/{task_id}` | `core/routes/operator.py` | 单任务深度只读投影 |
| `GET /api/v1/operator/inspect/route/{task_id}` | `core/routes/operator.py` | 单任务路由决策投影 |
| `GET /api/v1/operator/inspect/executor/{node_id}` | `core/routes/operator.py` | 执行节点存在与能力投影 |
| `GET /api/v1/operator/inspect/failure/{task_id}` | `core/routes/operator.py` | 单任务失败域投影 |
| `GET /api/v1/operator/inspect/lineage/{task_id}` | `core/routes/operator.py` | 任务血缘/时间线投影 |
| `GET /api/v1/operator/inspect/recovery/{task_id}` | `core/routes/operator.py` | 任务恢复状态投影 |
| `GET /api/v1/operator/inspect/partial-result/{task_id}` | `core/routes/operator.py` | 混合执行部分结果投影 |
| `GET /api/v1/operator/inspect/audit-evidence/{task_id}` | `core/routes/operator.py` | 任务审计证据覆盖 |
| `GET /api/v1/operator/review/{task_id}` | `core/routes/operator.py` | 端到端事后审查聚合视图 |
| `GET /api/v1/operator/inspect/flow/{flow_id}` | `core/routes/operator.py` | 委托流级投影（含 Android 执行阶段） |
| `GET /api/v1/config` / `POST /api/v1/config` | `core/routes/diagnostics.py` | 配置读写，走 `ConfigService` / `ConfigStore` |
| `GET /api/v1/health` | `core/routes/health.py` | 统一健康检查 |
| `GET /api/v1/monitoring` | `core/routes/monitoring.py` | 监控仪表盘与告警 |
| `GET /api/v1/devices` | `core/routes/devices.py` | 设备注册、列表、发现、注销 |
| `GET /api/v1/tasks` | `core/routes/tasks.py` | 任务管理 |
| `GET /api/v1/projection/runtime` | `core/routes/projection.py` | 运行时状态投影（Windows 状态板使用） |
| Windows 状态板 V2 | `windows_client/status_board_v2/` | 桌面端唯一规范操作面，含配置控制、拓扑视图、设备状态、三态显示 |
| 配置控制面（桌面） | `windows_client/status_board_v2/config_control.py` | 可对 provider 开关、路由策略、Android 推理模式进行写操作 |

### 4.2 部分实现 / 仅内部可见（Partially Implemented / Internal Only）

| 面 / 接口 | 文件 | 说明 | 缺什么 |
|-----------|------|------|--------|
| `ReadinessMatrix` | `core/runtime_readiness_matrix.py` | 完整实现，可编程访问，CI 可用 | 无 REST 端点，操作面无法轮询 |
| `TriState`（SILENT/LIMINAL/MANIFEST） | `core/desktop_presence_runtime.py` | 内部状态存在 | 未序列化进任何 REST 响应 |
| NATS 连接状态 | `core/nats_bus.py` | `is_connected()`、`get_stats()` 可编程访问 | 无 REST 端点，操作面看不到 |
| LLM 提供商运行时健康 | `core/multi_llm_router.py` | `ProviderConfig.status`、`latency_avg_ms`、`error_count` 内部有 | 未进入 `/api/v1/operator`，操作面只能看到配置就绪（有无 key），看不到运行态健康 |
| Heartbeat 状态 | `core/openclawd_heartbeat.py` | `HeartbeatScheduler._cycle_count`、tier 升级历史 | 无 REST 端点 |
| FlowLevelOperatorSurface | `core/flow_level_operator_surface.py` | `inspect_flow()` 已实现，已有 REST 路由 `/api/v1/operator/inspect/flow/{flow_id}` | Android 端执行阶段事件上报管道完整性尚未确认 |
| 端口映射 | `core/port_config.py` + `config/unified_ports.yaml` | 130 个节点端口映射完整 | 无 REST 端点 |
| RoutingDecision 路由决策 | `core/multi_llm_router.py` | 决策数据存在 | 未纳入 `TaskInspection` 或操作面快照 |

### 4.3 架构存在但未 Surface 的内容（Architecturally Present, Not Surfaced）

| 内容 | 位置 | 说明 |
|------|------|------|
| `PortConfig` REST 端点 | 应为 `GET /api/v1/ports` | 数据已有，无路由 |
| Operator Console UI（操作台 GUI） | `core/operator_surface.py` 中有 `OPERATOR_CONSOLE_ROLE` 哨兵 | 角色边界已定义，**无实现**（代码注释明确：role boundaries defined, no implementation） |
| Android → V2 能力通告消息 | `core/device_communication.py` `MessageType` | 缺少专用结构化 "capability_advertisement" 消息类型 |

### 4.4 仍然缺失（Still Missing）

以下内容既无代码实现，也无 REST 端点：

**V2 侧缺失的端点：**

| 缺失端点 | 对应数据源 | 重要性 |
|---------|----------|--------|
| `GET /api/v1/readiness` | `ReadinessMatrix` | 高：发布门控 |
| `GET /api/v1/operator/llm` | `MultiLLMRouter.ProviderConfig` 运行时健康 | 高：实时提供商状态 |
| `GET /api/v1/operator/nats` | `nats_bus.is_connected()` + `get_stats()` | 中：底层传输状态 |
| `GET /api/v1/operator/heartbeat` | `HeartbeatScheduler` | 中：OpenClawd 自检状态 |
| `GET /api/v1/ports` | `PortConfig` 端口映射 | 中：系统端口真相 |
| `TriState` 在 operator snapshot 里 | `DesktopPresenceRuntime._state` | 中：主体当前生命周期阶段 |

**Android → V2 缺失的状态上报：**

| 缺失状态 | Android 侧位置 | 对 V2 的影响 |
|---------|--------------|------------|
| `NativeInferenceLoader` 结果（`llamaCppAvailable`、`ncnnAvailable`） | `UFOGalaxyApplication.onCreate()` 日志 | V2 不知道 Android 设备是否真的能本地推理 |
| `ReadinessState`（`modelReady`、`accessibilityReady`、`overlayReady`） | `UFOGalaxyApplication.readinessState` | V2 无法判断 Android 是否真正准备好接收任务 |
| `LocalLoopReadiness` | `LocalLoopReadinessProvider` | V2 不知道本地 loop 是否就绪 |
| `ModelManifest` 身份（模型 ID、版本、量化、校验和） | `ModelManifest.forKnownModel()` | V2 不知道 Android 设备当前加载的是哪个模型 |
| `CompatibilityResult` | `ModelManifest.checkCompatibility()` | V2 不知道模型与 Android 运行时是否兼容 |
| `LocalLoopConfig` 活跃值 | `UFOGalaxyApplication.localLoopConfig` | V2 不知道设备当前用哪套 loop 参数 |
| `AndroidExecutionPhase` 事件完整管道 | `AndroidCanonicalExecutionEventOwner.kt` | V2 的 `FlowLevelOperatorSurface` 已就绪，但 Android 端 WS 发射管道完整性尚待确认 |
| `StagnationDetector` 事件 | `com.ufo.galaxy.local.StagnationDetector` | V2 看不到设备进入滞后状态 |
| `GroundingFallbackLadder` / `PlannerFallbackLadder` 当前层级 | `com.ufo.galaxy.local.*` | V2 不知道 Android 处于哪层 fallback |
| `OfflineTaskQueue` 深度 | `com.ufo.galaxy.network.OfflineTaskQueue` | V2 不知道设备离线队列积压情况 |
| `RuntimeHealthSnapshot` | `com.ufo.galaxy.runtime.RuntimeHealthSnapshot` | V2 看不到设备运行时健康全貌 |

**核心协议缺口：**

```python
# core/device_communication.py MessageType 里目前有：
# HEARTBEAT、STATUS、EVENT、WAKE_EVENT 等
# 但缺少：
# CAPABILITY_ADVERTISEMENT 或 DEVICE_STATE_SNAPSHOT 类型
```

**V2 侧 MessageType 里没有一个明确的、专用的"Android 能力/就绪状态通告"消息类型。**

---

## 5. 现在真实可用的控制体验说明

### 5.1 从 V2 侧（服务端）可以做什么

**通过 REST API（已可用）：**
- 读取系统运行快照：`GET /api/v1/operator/snapshot`
- 按任务 ID 检查执行状态、路由决策、失败域、血缘关系、恢复状态
- 读取和写入配置（提供商开关、路由策略、Android 推理模式）
- 查看设备列表和注册状态
- 查看任务列表
- 检查 flow 级 Android 执行阶段（若 Android 端事件已上报）

**通过 Windows 状态板 V2（已可用）：**
- 查看三态显示（SILENT/LIMINAL/MANIFEST，基于 `/api/v1/projection/runtime`）
- 查看模型路由拓扑（Native-Multimodal-First 星座拓扑）
- 查看设备在线状态
- 执行受限的配置写操作（提供商开关、路由策略）
  ```
  python -m windows_client.status_board_v2 --apply-toggle openai=true
  python -m windows_client.status_board_v2 --apply-routing-policy prefer
  ```

**当前不可用（通过 API 暂时看不到）：**
- V2 自身的 TriState 实时值（内部有，无端点）
- LLM 提供商运行时健康（内部有，无端点）
- NATS 传输层状态（内部有，无端点）
- ReadinessMatrix 就绪矩阵（有编程访问，无 REST 端点）

### 5.2 从 Android 侧可以做什么

**已可用（开启跨设备后）：**
- 通过 WebSocket AIP v3.0 协议连接 V2 网关
- 接收 V2 下发的任务指令
- 执行本地推理（若模型已下载且就绪）
- 上报任务结果（通过 `goal_result`、`goal_execution_result` 消息）
- 上报心跳保活
- 通过 Settings 界面修改本地配置（loop 参数、推理模式）
- 离线时在本地队列缓存任务，重连后自动 replay

**从 Android 角度目前仍然不可用：**
- Android 无法主动发起任务
- Android 无法查询 V2 的 OperatorSurface
- Android 无法控制其他设备
- Android 无法替代 V2 成为中心权威
- Android 的本地就绪状态（模型、无障碍、推理能力）V2 目前看不到

### 5.3 整体体验定性

**当前的控制体验可以描述为：**

> **API/配置层基本就绪，内部运行状态大量存在但还未完整暴露，Android 侧状态完全不上报给中心，操作台 GUI 还未实现。**

具体来说：
- **不是"操作台已完成"**：没有真正意义上的操作控制台 GUI（`OPERATOR_CONSOLE_ROLE` 哨兵存在但无 UI 实现）
- **不是"API 操作面已完整"**：关键运行态数据（TriState、NATS、LLM 健康、ReadinessMatrix）没有 REST 端点
- **不是"Android 状态透明"**：Android 所有本地状态（模型、推理能力、就绪度、fallback 层级、离线队列）V2 完全看不见
- **但也不是"什么都没有"**：操作面核心结构已完整（`OperatorSurface`、`FlowLevelOperatorSurface`），任务级检查 API 已就绪，配置控制面已可用

---

## 6. 最终中文结论

### 6.1 Android 开启跨设备后能接管整个系统吗？

**不能，而且这不是系统的设计意图。**

代码清楚地表明：
- `DesktopPresenceRuntime`（`core/desktop_presence_runtime.py`）是主体三态（SILENT/LIMINAL/MANIFEST）的**唯一所有者**，Android 无法驱动或替代它
- `OpenClawd`（`core/openclawd.py`）是认知/执行核心，完全在 V2 中心侧
- LLM 路由（`MultiLLMRouter`）、任务真相（`CanonicalTaskRuntime`）、操作面（`OperatorSurface`）均是 V2 中心权威

**Android 能做的，精确来说是：**
- 作为"运行时节点"加入，接收任务并在本地执行
- 作为"本地 AI 执行节点"运行本地推理（MobileVLM、SeeClick）
- 作为"跨设备参与者"上报执行事件给 V2 的投影层

**这是"委托执行参与"，不是"系统接管"。**

### 6.2 当前完成度总结

| 维度 | 完成度 | 说明 |
|------|--------|------|
| V2 任务级操作面 | **存在，未完整暴露** | `OperatorSurface` + `GET /api/v1/operator` 已有；TriState、NATS、LLM 健康、flow 投影部分缺 REST 端点 |
| V2 配置控制面 | **基本完整** | `ConfigService`、`ConfigStore`、`GET/POST /api/v1/config`、Windows 状态板控制已就绪 |
| V2 提供商健康（运行态） | **未暴露** | `ProviderConfig` 状态在内部，无操作面端点 |
| V2 就绪矩阵 | **存在，无 REST 端点** | `ReadinessMatrix` 可编程访问，无 `/api/v1/readiness` |
| Android 运行状态上报 | **完全缺失** | 模型就绪、推理能力、readiness、fallback 等所有 Android 本地状态 V2 均不可见 |
| Android 执行阶段投影 | **架构就绪，管道待确认** | V2 的 `FlowLevelOperatorSurface` 已就绪，Android WS 事件发射管道完整性尚待确认 |
| 操作控制台 GUI | **不存在** | `OPERATOR_CONSOLE_ROLE` 哨兵存在，无任何 UI 实现 |
| Android 能力通告协议 | **缺失** | `MessageType` 中无结构化 capability advertisement 消息类型 |

### 6.3 一句话最终结论

> **Android 开启跨设备后，是一个真实的运行时节点和本地 AI 执行节点——可以接收并执行任务、在本地运行推理——但绝对不是系统的中心权威，无法接管 V2 的治理、路由、任务管理或操作面职责。当前操作面的最大实际问题不是"Android 能不能参与"（可以），而是"系统里大量真实存在的状态——尤其是 Android 本地所有的能力与就绪度——还没有被规范地上报给中心，也没有相应的操作面端点和协议把这些状态完整暴露出来"。**

---

*本文档仅基于源代码写成，所有结论均可追溯至具体文件、类名和常量名。*  
*文档路径：`docs/ANDROID_CROSS_DEVICE_CAPABILITY_CN.md`*
