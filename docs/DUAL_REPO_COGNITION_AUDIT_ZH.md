# 双仓联合认知审查（中文版）——基于当前真实代码

> **文档类型**：代码驱动型双仓系统认知审查  
> **审查范围**：`DannyFish-11/ufo-galaxy-realization-v2`（V2 控制平面）
> ＋ `DannyFish-11/ufo-galaxy-android`（Android 执行参与者）  
> **唯一信息来源**：当前代码文件（`core/`、`galaxy_gateway/`、`contracts/`、`system_integration/`）  
> **不依据**：任何历史 Markdown 审计、设计文档、PR 描述或愿景说明  
> **语言**：中文  

---

## 目录

1. [整套双仓系统当前本体说明](#1-整套双仓系统当前本体说明)
2. [已经真实成立的能力与链路](#2-已经真实成立的能力与链路)
3. [目前仅部分成立或部分暴露的部分](#3-目前仅部分成立或部分暴露的部分)
4. [当前仍未完成的关键缺口](#4-当前仍未完成的关键缺口)
5. [对整套系统现阶段最准确的中文定性](#5-对整套系统现阶段最准确的中文定性)

---

## 1. 整套双仓系统当前本体说明

### 1.1 这套系统是什么

Galaxy 是一套**基于双仓架构的分布式 AI Agent 系统**，核心分工如下：

| 仓库 | 角色 | 代码位置 |
|------|------|---------|
| `ufo-galaxy-realization-v2`（V2） | 中心控制平面：协议网关、路由权威、Operator 检查面、能力调度、任务编排、状态投影 | `galaxy_gateway/`, `core/`, `system_integration/` |
| `ufo-galaxy-android`（Android） | 持久执行参与者：本地 GUI 执行、传感器、本地 AI 推理、跨设备任务承接 | `galaxy_gateway/android/`（V2 侧 Android 适配层）|

**当前仓库关系的核心事实：**
- V2 包含 Android 的网关适配层（`galaxy_gateway/android/`），是 Android 连接到系统的唯一入口
- Android 仓库（`ufo-galaxy-android`）的代码不在 V2 本地，但 V2 侧已建立完整的适配协议和处理器
- 双仓通信基于 **AIP v3 协议**（`galaxy_gateway/protocol/aip_v3.py`），WebSocket 为主要传输层

### 1.2 V2 当前是什么

V2 目前是一个**功能相当完整的分布式 Agent 控制平面**，已有以下核心子系统：

**协议层：**
- `galaxy_gateway/protocol/aip_v3.py`：统一 AIP v3 协议，定义 60+ 消息类型
- `galaxy_gateway/protocol/compat.py`：向后兼容解析器
- `galaxy_gateway/protocol/ingress_classifier.py`：消息入向分类器

**网关层：**
- `galaxy_gateway/android_bridge.py`：Android WebSocket 消息处理中心，含完整分发表
- `galaxy_gateway/routes/websocket.py`：设备 WebSocket 规范入口（`/ws/device/{device_id}`）
- `galaxy_gateway/android/handlers/`：14 个专用处理器模块（注册、心跳、任务、能力、信号等）

**控制/调度层：**
- `core/command_router.py`：唯一跨设备路由权威
- `core/capability_routing_gate.py`：能力路由门
- `core/device_pool_manager.py`：设备池调度（已与 CapabilityResolver 集成）
- `core/operator_surface.py`：统一 Operator Surface，聚合所有运行时维度

**Operator API 层（全部已实现）：**
- `core/routes/operator.py`：所有 operator 端点的实际处理器

**状态存储层：**
- `core/android_device_state_store.py`：Android→V2 控制面状态存储
- `core/operator_surface.py`：统一运行时状态聚合
- `core/flow_level_operator_surface.py`：委托流级别状态投影

### 1.3 Android 端当前是什么（从 V2 侧代码视角）

从 V2 侧代码可观察到 Android 端的以下能力：

**连接能力：**
- 通过 WebSocket 连接 V2 网关（`/ws/device/{device_id}` 路径）
- 注册时发送 `DEVICE_REGISTER` 消息，包含设备 ID、能力声明等

**能力上报：**
- 发送 `CAPABILITY_REPORT` 消息上报支持的操作列表
- V2 侧 `handle_capability_report` 将其写入 `CapabilityAuthority`，使路由可感知该设备

**执行参与：**
- 接收 `TASK_ASSIGN` / `HANDOFF_ENVELOPE_V2` 等任务分发消息
- 执行后通过 `TASK_RESULT` / `HANDOFF_ENVELOPE_V2_RESULT` 回传结果
- 通过 `DELEGATED_EXECUTION_SIGNAL` 上报委托执行信号
- 通过 `RECONCILIATION_SIGNAL` 推送状态协调信号

**治理报告：**
- 发送 `DEVICE_READINESS_REPORT`、`DEVICE_GOVERNANCE_REPORT`、`DEVICE_ACCEPTANCE_REPORT`、`DEVICE_STRATEGY_REPORT`（V2 侧接收并 ACK，但目前路由到 generic_forward 而非结构化摄取）

### 1.4 双仓真实运行时关系

```
用户/外部请求
    │
    ▼
V2: openclawd → CommandRouter → CapabilityRoutingGate
    │
    ├── 本地执行路径（local_agent_runtime 等）
    │
    └── 委托执行路径（DelegatedFlow）
            │
            ▼
        galaxy_gateway (AndroidBridge) ──── AIP v3 WebSocket ────► Android
                                                                        │
                                                              Android 执行 (GUI/AI/传感器)
                                                                        │
            ◄──── AIP v3 (TASK_RESULT / HANDOFF_ENVELOPE_V2_RESULT) ───┘
            │
V2: android_delegated_signal_ingress → OperatorSurface / FlowLevelOperatorSurface
```

**中心与节点的真实关系：**
- V2 是**调度权威、路由权威、Operator 聚合权威**
- Android 是**能力宣告者 + 执行承载者**，不做调度决策
- 连接生命周期由 V2 侧 AndroidBridge 管理
- Android 通过能力上报（`CAPABILITY_REPORT`）使自己对路由系统可见

---

## 2. 已经真实成立的能力与链路

以下能力和链路基于代码可验证，已有对应实现。

### 2.1 已实现的完整运行时链路

**Android 设备注册链路** ✅
- 代码路径：`handle_device_register` → UDM upsert → DeviceRouter session sync → `attach_runtime_session` → `CapabilityAssimilationLayer`
- 包含注册完整度追踪：`_device_registration_gaps` 记录失败步骤
- 代码锚点：`galaxy_gateway/android/handlers/registration.py`

**Android 能力上报链路** ✅
- 代码路径：`handle_capability_report` → `CapabilityAuthority.upsert_contract()` → 路由系统可见
- V2 侧立即投影到 canonical gateway capability resolver
- 代码锚点：`galaxy_gateway/android/handlers/capability_report.py`

**委托执行信号链路** ✅
- Android 发送 `DELEGATED_EXECUTION_SIGNAL`
- V2 侧 `handle_delegated_execution_signal` 处理
- 进入 `core/android_delegated_signal_ingress.py` 摄取
- 代码锚点：`galaxy_gateway/android/handlers/delegated_signal.py`

**HandoffV2 结果回传链路** ✅
- Android 发送 `HANDOFF_ACK` / `HANDOFF_RESULT` / `HANDOFF_FAILURE` / `HANDOFF_ENVELOPE_V2_RESULT`
- V2 侧 `handle_handoff_v2_result` 统一处理
- 进入 `core/android_handoff_v2_response_ingress.ingest_android_handoff_response()`
- 代码锚点：`galaxy_gateway/android/handlers/handoff_v2_result.py`

**Reconciliation Signal 链路** ✅
- Android 发送 `RECONCILIATION_SIGNAL`
- V2 侧 `handle_reconciliation_signal` 处理
- 代码锚点：`galaxy_gateway/android/handlers/reconciliation_signal.py`

**Takeover 协议** ✅
- V2 发送 `TAKEOVER_REQUEST` → Android 回应 `TAKEOVER_RESPONSE`
- V2 侧 `handle_takeover_response` 处理
- 代码锚点：`galaxy_gateway/android/handlers/takeover_response.py`

### 2.2 已实现的 Operator/控制面端点

所有以下端点在 `core/routes/operator.py` 中均有实际实现（非 stub/mock）：

| 端点 | 后端数据源 | 状态 |
|------|-----------|------|
| `GET /api/v1/readiness` | `core.runtime_readiness_matrix.get_readiness_matrix()` | ✅ 已实现 |
| `GET /api/v1/operator/snapshot` | `OperatorSurface.operator_snapshot()` | ✅ 已实现 |
| `GET /api/v1/operator/flows` | `FlowLevelOperatorSurface` + `DelegatedFlowEntityRuntime` | ✅ 已实现 |
| `GET /api/v1/operator/flows/{flow_id}` | 同上 + inspect_flow() | ✅ 已实现 |
| `GET /api/v1/operator/llm` | `LLMManager` / `MultiLLMRouter.get_status()` | ✅ 已实现 |
| `GET /api/v1/operator/nats` | `nats_bus.is_connected()` + `get_stats()` | ✅ 已实现 |
| `GET /api/v1/operator/heartbeat` | `openclawd_heartbeat.get_heartbeat_scheduler()` | ✅ 已实现 |
| `GET /api/v1/ports` | `PortConfig` | ✅ 已实现 |
| `GET /api/v1/operator/devices/ecosystem` | `android_device_state_store.get_device_ecosystem_summary()` | ✅ 已实现 |
| `GET /api/v1/operator/inspect/task/{task_id}` | `OperatorSurface.inspect_task()` | ✅ 已实现 |
| `GET /api/v1/operator/inspect/route/{task_id}` | `OperatorSurface.inspect_route()` | ✅ 已实现 |
| `GET /api/v1/operator/inspect/executor/{node_id}` | `OperatorSurface.inspect_executor()` | ✅ 已实现 |
| `GET /api/v1/operator/inspect/failure/{task_id}` | `OperatorSurface.inspect_failure_domain()` | ✅ 已实现 |
| `GET /api/v1/operator/inspect/lineage/{task_id}` | `OperatorSurface.inspect_lineage()` | ✅ 已实现 |
| `GET /api/v1/operator/inspect/recovery/{task_id}` | `OperatorSurface.inspect_recovery()` | ✅ 已实现 |
| `GET /api/v1/operator/inspect/flow/{flow_id}` | `FlowLevelOperatorSurface.inspect_flow()` | ✅ 已实现 |
| `GET /api/v1/operator/review/{task_id}` | `OperatorSurface.end_to_end_review()` | ✅ 已实现 |

### 2.3 已实现的 Android 设备状态接收能力（V2 侧）

`core/android_device_state_store.py` 已实现：
- `absorb_device_state_snapshot(device_id, payload)` ✅
- `absorb_device_execution_event(device_id, payload)` ✅
- `get_device_state_snapshot(device_id)` ✅
- `list_device_state_snapshots()` ✅
- `get_device_ecosystem_summary()` ✅

测试验证：29 个测试全部通过（`tests/test_android_device_state_store.py`）。

### 2.4 已实现的能力体系

- `core/agent/capability_registry.py`：写入权威（CapabilityRegistry）
- `core/unified/capability_resolver.py`：读取权威（CapabilityResolver）
- `core/unified/capability_authority.py`：CapabilityAuthority 统一写入入口
- 路由系统（`core/device_pool_manager.py`）已与 CapabilityResolver 集成

### 2.5 Android 可以真实做到的事

基于 V2 侧代码，Android 端当前可真实参与：
1. 连接注册并宣告自身能力
2. 承接委托任务（delegated flow 路径）
3. 执行 GUI/传感器/文件/系统等操作并回传结果
4. 发送执行阶段信号（DELEGATED_EXECUTION_SIGNAL）
5. 推送状态协调信号（RECONCILIATION_SIGNAL）
6. 参与 Takeover 协议
7. 上报治理生命周期报告（Readiness/Governance/Acceptance/Strategy）

---

## 3. 目前仅部分成立或部分暴露的部分

以下能力在代码中"已存在结构"，但尚未形成完整的端到端闭环。

### 3.1 DEVICE_STATE_SNAPSHOT / DEVICE_EXECUTION_EVENT wire 路径

**已有的部分：**
- V2 侧 `android_device_state_store.py` 完整实现了 `absorb_device_state_snapshot()` 和 `absorb_device_execution_event()`
- Operator 端点 `GET /api/v1/operator/devices/ecosystem` 已从该 store 读取数据
- 字符串常量已定义：
  - `DEVICE_STATE_SNAPSHOT_MSG_TYPE = "device_state_snapshot"`
  - `DEVICE_EXECUTION_EVENT_MSG_TYPE = "device_execution_event"`

**尚未打通的部分：**
- `DEVICE_STATE_SNAPSHOT` 和 `DEVICE_EXECUTION_EVENT` **不在** `galaxy_gateway/protocol/aip_v3.py` 的 `MessageType` 枚举中
- `galaxy_gateway/android_bridge.py` 的消息分发表中**没有**这两种消息类型的处理器
- 后果：即使 Android 端发来 `device_state_snapshot` 消息，也会被路由到 `handle_unregistered`（catch-all）而非进入 `absorb_device_state_snapshot()`
- **结论**：V2 侧的"接收"基础设施已就位，但 wire-level 入向路径未接通

### 3.2 DEVICE_READINESS_REPORT 等治理报告的实质摄取

**已有的部分：**
- `DEVICE_READINESS_REPORT`、`DEVICE_GOVERNANCE_REPORT`、`DEVICE_ACCEPTANCE_REPORT`、`DEVICE_STRATEGY_REPORT` 已在 `MessageType` 枚举中注册
- android_bridge 分发表中已有处理器（for 循环批量注册）

**未打通的部分：**
- 这些消息类型的处理器是 `handle_generic_forward`（通用转发/日志记录）
- **未接入** `android_device_state_store.absorb_device_state_snapshot()` 或类似结构化摄取路径
- Android 治理状态（readiness/governance/acceptance）无法从 `/api/v1/operator/devices/ecosystem` 端点读取，该端点只能返回通过 `absorb_device_state_snapshot()` 注入的数据

### 3.3 FlowLevelOperatorSurface 的 Android 执行阶段填充

**已有的部分：**
- `core/flow_level_operator_surface.py` 已实现完整的 `FlowOperatorProjection`，包括 `current_execution_phase`、`blocking_reason`、`recovery_status` 等字段
- `absorb_device_execution_event()` 已在 store 中实现

**未打通的部分：**
- 从 `android_device_state_store` 到 `FlowLevelOperatorSurface` 的填充路径依赖 `absorb_device_execution_event()` 被实际调用
- 由于没有 wire-level handler，`DEVICE_EXECUTION_EVENT` 消息目前无法进入 flow projection

### 3.4 多设备 mesh 状态

**已有的部分：**
- `PEER_ANNOUNCE`、`PEER_EXCHANGE`、`MESH_TOPOLOGY` 消息类型均已注册且有处理器
- `handle_peer_announce`、`handle_peer_exchange`、`handle_mesh_topology` 均存在

**未充分暴露的部分：**
- 没有 `GET /api/v1/operator/topology` 或类似端点将 mesh 拓扑状态完整暴露给 operator
- 多设备同时在线时的聚合视图只能通过 `/api/v1/operator/snapshot` 部分获取

### 3.5 桌面端 UI 控制台

**已有的部分：**
- `enhancements/clients/windows_client/run_ui.py`：启动入口存在
- `enhancements/clients/windows_client/ufo_ui_automation_bridge.py`：UI 自动化桥接存在
- `system_integration/state_machine_ui_integration.py`：UI shell 状态机已定义（DORMANT/ISLAND/SIDESHEET/FULLAGENT 等状态）
- `system_integration/hardware_trigger.py`：硬件触发器已实现

**未完成的部分：**
- 没有完整的统一 operator console UI（scroll_paper_geek_ui.py 在本次代码审查中未找到）
- 没有面向多设备生态系统的完整可视化控制台界面

---

## 4. 当前仍未完成的关键缺口

以下是当前代码中确认存在的、对"系统作为真正统一多设备生态"感知有实质影响的缺口：

### 4.1 DEVICE_STATE_SNAPSHOT 消息类型未在协议层注册 ❌

**现状：**
- `aip_v3.py` `MessageType` 枚举中无 `DEVICE_STATE_SNAPSHOT`
- `android_bridge.py` 分发表无此消息的处理器

**影响：**
- Android 无法通过标准 AIP v3 协议向 V2 发送设备状态快照
- Operator 的 `GET /api/v1/operator/devices/ecosystem` 端点在没有手动注入数据时将返回空集合
- 控制面无法获得设备的 native runtime 可用性（llamaCpp/NCNN）、readiness 状态、模型身份等信息

**缺口大小**：高影响——这是"Android→V2 控制面状态投影"链路的根本断点

### 4.2 DEVICE_EXECUTION_EVENT 消息类型未在协议层注册 ❌

**现状：**同上，`MessageType` 枚举中无 `DEVICE_EXECUTION_EVENT`，分发表无处理器

**影响：**
- 即使 Android 在执行委托任务期间发送执行事件，V2 flow projection 也无法接收
- `FlowLevelOperatorSurface` 的 `current_execution_phase` 等字段在真实运行时始终为空
- Operator 无法观察跨设备执行的实时状态

**缺口大小**：高影响——这是"Android 执行事件→V2 flow projection 闭环"的根本断点

### 4.3 Android 治理报告未进行结构化摄取 ⚠️

**现状：**`DEVICE_READINESS_REPORT` 等 4 种报告消息路由到 `handle_generic_forward`（只记日志）

**影响：**
- Android 的 readiness 状态（无障碍服务就绪、overlay 就绪、model 就绪等）无法通过 V2 控制面查询
- 只能通过日志间接观察，无法结构化访问

**缺口大小**：中等影响——报告不丢失，但无法作为结构化控制面数据使用

### 4.4 统一操作控制台 UI 未完成 ⚠️

**现状：**`enhancements/clients/windows_client/` 只有基础桥接文件，无完整 UI

**影响：**
- 即使所有 operator REST 端点都已完整，也没有统一的可视化控制台来展示多设备生态状态
- 需要直接调用 REST API 才能查看系统状态

**缺口大小**：中等影响——功能链路完整，但缺少操作界面层

### 4.5 Android 本地 AI 状态投影未打通 ⚠️

**背景：** Android 端有本地 AI 推理能力（llamaCpp、NCNN），但当前 V2 无法感知其运行状态

**现状：**
- `android_device_state_store.py` 的 `DeviceStateSnapshot` 已有 `llama_cpp_available`、`ncnn_available`、`active_runtime_type`、`model_id`、`model_checksum_valid` 等字段
- 但由于 wire 路径（4.1）未打通，这些字段在实际运行时始终为空

**影响：**
- V2 不知道 Android 是否处于本地 AI 就绪状态
- 无法基于 Android 本地 AI 能力做出路由决策

**缺口大小**：中等影响（依赖 4.1 修复）

---

## 5. 对整套系统现阶段最准确的中文定性

### 5.1 这是什么系统

**Galaxy 现阶段是一套架构成熟、核心控制面完备、但 Android→V2 状态投影链路尚未全面打通的分布式 AI Agent 系统。**

更具体地：
- V2 控制平面已是**真正功能完整的控制平面**：协议完整、路由完整、Operator API 完整、能力调度完整
- Android 作为执行参与者的**基础能力已真实成立**：注册、能力上报、任务承接与回传、执行信号上报均有完整代码路径
- 但"Android 作为受控节点向 V2 完整暴露自身运行时状态"这一链路**尚未完全打通**：缺少 DEVICE_STATE_SNAPSHOT / DEVICE_EXECUTION_EVENT 的 wire-level 入向路径

### 5.2 当前成熟度级别

| 层次 | 成熟度 | 说明 |
|------|--------|------|
| 协议层（AIP v3） | **高** | 60+ 消息类型定义完整，兼容层存在 |
| Android 基础连接 | **高** | 注册、心跳、能力上报、基本任务生命周期均已完整 |
| Operator API 端点 | **高** | 所有端点均有实际实现，均连接到真实运行时数据源 |
| 委托执行链路 | **中高** | V2→Android 任务分发完整，Android→V2 结果回传完整 |
| Android→V2 状态投影 | **低中** | V2 侧存储 API 已就位，但 wire-level 入向路径缺失 |
| 跨设备 Operator 可见性 | **中** | OperatorSurface 结构完整，但 Android 实时状态填充依赖未打通的 wire 路径 |
| 桌面 UI 控制台 | **低** | 只有基础桥接，无完整可视化界面 |

### 5.3 已经实质成立的能力

1. V2 可以通过 WebSocket 管理多个 Android 设备的连接生命周期
2. Android 可以注册并宣告能力，V2 的路由系统立即可以感知该设备
3. V2 可以向 Android 分发委托任务（delegated flow），Android 可以执行并回传结果
4. V2 的 Operator API 已经完整暴露了 V2 中心的所有运行时状态
5. V2 侧的 android_device_state_store 已经准备好接收和存储 Android 设备快照

### 5.4 尚未完全闭合的部分

1. Android 向 V2 发送设备状态快照（DEVICE_STATE_SNAPSHOT）的 wire 路径：**未打通**
2. Android 向 V2 发送执行事件（DEVICE_EXECUTION_EVENT）使 flow projection 更新：**未打通**
3. Android 治理报告（readiness/governance 等）进入结构化 V2 存储：**未打通**（只记日志）
4. 统一多设备操作控制台 UI：**未完成**

### 5.5 如何正确理解这套双仓系统的现阶段

**正确认识应该是：**

> Galaxy 现在已经是一套**架构完整、协议完整、控制面完整**的分布式 Agent 系统。  
> V2 中心的 Operator 控制面已经具备了完整的自检能力（readiness、流、LLM、NATS、设备生态等端点均真实可用）。  
> Android 作为执行节点的基础参与能力（注册、能力上报、任务承接、结果回传）已经成立。  
>
> 但系统目前尚未实现"Android 运行时状态对 V2 完全透明"这一控制面完整度的最后一段：  
> Android 设备的本地 AI 状态、readiness 状态、模型身份、执行阶段等信息，  
> 在当前代码中无法通过标准 AIP v3 协议传输到 V2 控制面。  
>
> 因此，如果问"Android 能不能通过跨设备模式接管整套系统"——  
> **答案是：Android 可以作为强执行参与者参与整套系统，但 V2 中心始终是唯一的路由权威和 Operator 聚合权威；目前的信息流是"V2 指挥 Android 执行"，而非"Android 接管 V2 中心"。**
>
> 如果问"当前页面/操作面完成度"——  
> **答案是：REST API Operator 端点层已经完整，但可视化 UI 控制台仍未做完；底层能力远高于界面完成度。**

---

## 附录：关键代码锚点索引

| 组件 | 文件 | 说明 |
|------|------|------|
| AIP v3 协议 | `galaxy_gateway/protocol/aip_v3.py` | 所有消息类型定义 |
| Android 桥接 | `galaxy_gateway/android_bridge.py` | 消息分发中心 |
| Operator API | `core/routes/operator.py` | 所有 operator 端点 |
| Android 状态存储 | `core/android_device_state_store.py` | 设备状态快照存储 |
| Operator Surface | `core/operator_surface.py` | 统一运行时状态 |
| Flow Operator | `core/flow_level_operator_surface.py` | 委托流状态投影 |
| 能力权威 | `core/unified/capability_authority.py` | 能力写入权威 |
| 能力解析 | `core/unified/capability_resolver.py` | 能力读取权威 |
| Readiness Matrix | `core/runtime_readiness_matrix.py` | 发布就绪矩阵 |
| NATS 总线 | `core/nats_bus.py` | 分布式消息载体 |
| 路由权威 | `core/command_router.py` | 唯一跨设备路由权威 |

---

*本文档基于对 `ufo-galaxy-realization-v2` 当前代码的直接读取，不引用任何历史审计文档或设计规格说明。文档中的所有陈述均可追溯到上表中的具体代码文件。*
