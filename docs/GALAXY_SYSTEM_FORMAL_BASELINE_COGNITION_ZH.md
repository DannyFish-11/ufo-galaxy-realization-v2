# Galaxy 双仓系统正式基线认知文档

> **文档性质**：本文件是 Galaxy 双仓系统（`ufo-galaxy-realization-v2` + `ufo-galaxy-android`）当前阶段的**正式基线认知声明**。
>
> **有效性规则**：除非两个仓库的真实实现代码发生实质性变化，本文件所建立的系统本体定性、角色划分与阶段判断均应作为后续一切说明、审查与规划的**默认起点**。局部细节可在此基础上进行修正与浮动，但不得以非代码依据（旧文档、设计叙述、历史审计）推翻整体方向。
>
> **唯一信息来源**：当前两个仓库的真实实现代码。不采信任何历史 Markdown 审计、设计文档、PR 描述或愿景叙述作为证据。
>
> **撰写时间**：2026-05-04

---

## 目录

1. [文档定位与正式基线声明](#1-文档定位与正式基线声明)
2. [整套系统当前本体定性](#2-整套系统当前本体定性)
3. [V2 当前角色与中心权威](#3-v2-当前角色与中心权威)
4. [Android / 桌面 / 平板 / 其他设备的当前真实定位](#4-android--桌面--平板--其他设备的当前真实定位)
5. [为什么这套系统的本体是整个网络而不是某个端](#5-为什么这套系统的本体是整个网络而不是某个端)
6. [为什么当前已经越过 PoC 阶段](#6-为什么当前已经越过-poc-阶段)
7. [当前剩余工作的真实主轴](#7-当前剩余工作的真实主轴)
8. [后续推进应坚持的方向](#8-后续推进应坚持的方向)

---

## 1. 文档定位与正式基线声明

本文件是 Galaxy 双仓联合系统截至当前的**正式基线认知文档**。

它的作用是：

- 建立一个基于真实代码、经过系统化阅读后形成的完整认知。
- 使所有后续参与者（开发者、审查者、规划者）在理解本系统时有一个**明确、稳定的共同起点**。
- 消除由旧文档、设计愿景叙述、非代码层面描述所造成的认知噪音与漂移。
- 为后续的局部修正、补丁记录提供一个清晰的基准底座。

**本文件的基线地位**：

除非以下任一条件成立，否则本文件的整体定性不应被推翻：

1. `ufo-galaxy-realization-v2` 或 `ufo-galaxy-android` 中的实现代码发生了实质性的结构变化（例如中心权威被拆分、执行链被重构、关键组件被移除）。
2. 经过新一轮完整的代码阅读，产生了有明确代码引用支撑的更准确判断。

**不构成推翻依据的情形**：

- 旧版文档中的描述与本文件不一致。
- 设计讨论或 PR 描述中有不同措辞。
- 主观认为"系统不应该这样理解"但无代码支撑。

---

## 2. 整套系统当前本体定性

### 2.1 这套系统不是一个传统软件产品

Galaxy 不是以下任何一种：

- 一款电脑 AI 桌面应用（带手机控制附件）。
- 一款手机 AI 应用（以 PC 为辅助端）。
- 一个传统的"中控 + 多客户端"产品形态。
- 一套普通的远程控制或自动化工具集。

**代码证据**：`core/device_types.py` 中 `DeviceType` 枚举不区分"主端"与"从端"，而是平等地定义了 `ANDROID`、`WINDOWS`、`MACOS`、`IOS`、`LINUX`、`DRONE`、`ROBOT`、`CAMERA`、`SENSOR`、`ACTUATOR`、`IOT` 等类型。注册 API（`core/device_registry.py: DeviceRegistry.register()`）对所有设备类型均一视同仁，能力通过 `capabilities` 列表字段动态声明。

### 2.2 这套系统是什么

**当前准确定性**：Galaxy 是一套**以 V2 为中心治理内核的分布式 AI 体系统**。

其系统形态由以下三个层次共同构成：

| 层次 | 内容 | 代码锚点 |
|------|------|---------|
| **中心治理内核** | V2（`ufo-galaxy-realization-v2`）：负责调度决策、路由权威、能力网络、任务真相、状态投影 | `core/command_router.py`, `core/openclawd.py`, `core/capability_routing_gate.py` |
| **运行时节点层** | Android（`ufo-galaxy-android`）及其他接入设备：负责执行、感知、本地 AI、结果回传 | `galaxy_gateway/android/`, `galaxy_gateway/android_bridge.py` |
| **协议与网关层** | AIP v3 统一协议 + WebSocket 传输层：节点与中心的通信基础 | `galaxy_gateway/protocol/aip_v3.py`, `galaxy_gateway/routes/websocket.py` |

### 2.3 整体结构示意

```
外部触发 / 用户输入
        │
        ▼
DesktopPresenceRuntime（外壳层 — 三态生命周期: SILENT → LIMINAL → MANIFEST）
        │
        ▼
OpenClawd（认知内核 — 摄入 → 意图 → 执行路径决策 → 落地）
        │
        ├─── LOCAL  ──────────────► DecisionExecutor（本机 Windows 直接执行）
        │
        ├─── CROSS_DEVICE ────────► CommandRouter → GatewayLayer → 远端节点
        │
        └─── HYBRID ──────────────► 本机 + 跨设备同时执行
                                         │
                           ┌─────────────┴─────────────┐
                           ▼                           ▼
                    Android 节点                其他节点
                    （执行 / 感知 / 本地 AI）    （VLM、WebRTC 等）
```

**代码证据**：
- 执行路径决策：`core/openclawd.py: OpenClawd._determine_execution_path()`（支持 `local` / `cross_device` / `hybrid` / `none` 四路，已由 `core/schemas/unified_control_plan.py: ExecutionPath` 固化为枚举类型）。
- 本地执行：`core/execution/decision_executor.py: DecisionExecutor`（文件头部注释明确说明其为"subject's local manifestation layer"）。
- 跨设备执行：`core/command_router.py: CommandRouter.route_envelope()`（文件头部注释明确说明其为"cross-device liminal domain expansion layer"）。

---

## 3. V2 当前角色与中心权威

V2 是当前整套系统的**唯一中心治理权威**。这不是一个设计目标，而是当前代码实现的现实。

### 3.1 V2 掌握的中心权威清单

| 权威维度 | 具体实现 | 代码锚点 |
|---------|---------|---------|
| **调度决策权威** | `OpenClawd._determine_execution_path()` 决定每一次执行走本地、跨设备还是 hybrid 路径 | `core/openclawd.py` |
| **路由权威** | `CommandRouter.route_envelope()` 是唯一跨设备路由入口，其文件注释明确声明自身为"sole cross-device routing authority" | `core/command_router.py` |
| **能力网络权威** | `CapabilityRoutingGate`（`core/capability_routing_gate.py`）对目标设备施加能力门控；`DevicePoolManager` 已集成 `CapabilityResolver` 进行调度决策 | `core/capability_routing_gate.py`, `core/device_pool_manager.py` |
| **任务真相权威** | 任务生命周期的真值状态由 V2 侧维护，Android 侧执行结果须回传至 V2 合并 | `galaxy_gateway/android/handlers/task_lifecycle.py` |
| **配置权威** | 所有运行时配置由 V2 侧 `ConfigService` 管理，Android 不持有全局配置权 | `core/config_service.py` |
| **Operator 聚合权威** | `OperatorSurface`（`core/operator_surface.py`）聚合所有运行时维度；`/api/v1/operator/snapshot` 等端点已在 `core/routes/operator.py` 中完整实现 | `core/operator_surface.py`, `core/routes/operator.py` |
| **设备准入权威** | `handle_device_register`（`galaxy_gateway/android/handlers/registration.py`）控制 Android 节点的注册准入，触发 `CapabilityAssimilationLayer` 与 `BodyMeshRegistry` 的录入 | `galaxy_gateway/android/handlers/registration.py` |
| **网关权威** | `AndroidBridge`（`galaxy_gateway/android_bridge.py`）是 Android 节点连接 V2 的唯一入口，持有完整分发表与消息路由逻辑 | `galaxy_gateway/android_bridge.py` |

### 3.2 V2 不是什么

明确区分 V2 的真实边界：

- V2 **不是一个孤立的本机 AI 桌面应用**，它是整套网络的中心治理节点。
- V2 **不是一个 UI 壳**，其核心是调度、路由、协议网关、状态投影等后端系统。
- V2 的"桌面 UI"（`system_integration/state_machine_ui_integration.py` 中的 DORMANT / ISLAND / SIDESHEET / FULLAGENT 四状态）是 AI 系统在本机的**一个表现面**，而不是系统本身。

### 3.3 V2 对外暴露的 Operator API（当前已实现）

以下端点均已在 `core/routes/operator.py` 中完整实现，不是占位符：

- `GET /api/v1/readiness` — 系统 readiness 状态
- `GET /api/v1/operator/snapshot` — 完整 operator 快照
- `GET /api/v1/operator/flows` / `GET /api/v1/operator/flows/{flow_id}` — flow 级别状态
- `GET /api/v1/operator/llm` — LLM 路由状态
- `GET /api/v1/operator/nats` — NATS 消息总线状态
- `GET /api/v1/operator/heartbeat` — heartbeat 状态
- `GET /api/v1/ports` — 端口状态
- `GET /api/v1/operator/devices/ecosystem` — 设备生态投影

---

## 4. Android / 桌面 / 平板 / 其他设备的当前真实定位

### 4.1 核心定性转变

这套系统中，Android、桌面、平板及其他各类设备**不应被理解为"客户端"**。

正确定性是：它们是这套分布式 AI 体系统的**承载体 / 执行面 / 感知面 / 交互面 / 表现面**。

这一定性不是隐喻，而是直接对应代码实现：

| 能力维度 | 对应代码实现 |
|---------|---------|
| 设备注册与能力宣告 | `handle_device_register` → `CapabilityAssimilationLayer` → `BodyMeshRegistry` |
| 委托执行承接 | `DELEGATED_EXECUTION_SIGNAL` → `android_delegated_signal_ingress` |
| 本地 AI 推理 | Android 侧 `LocalAIRuntime`（`ufo-galaxy-android` 仓库）|
| 本地执行 loop | Android 侧 `AutonomousExecutionPipeline`（`ufo-galaxy-android` 仓库）|
| 结果回传 | `HANDOFF_ACK` / `HANDOFF_RESULT` / `HANDOFF_FAILURE` / `HANDOFF_ENVELOPE_V2_RESULT` |
| 网格角色分配 | `BodyMeshRegistry.register()` 根据设备能力位掩码分配角色 |
| 重连与离线队列 | Android 侧离线缓存 + 重连后回放机制 |

### 4.2 Android 当前是什么

Android 是整套系统中**能力最强的现存运行时节点**，已具备以下能力：

**连接与注册层：**
- 通过 WebSocket 连接 V2 网关（`/ws/device/{device_id}`）
- 注册时触发 `CapabilityAssimilationLayer` 使路由系统立即感知该设备
- 注册时自动写入 `BodyMeshRegistry`，获得网格角色

**能力宣告层：**
- 通过 `CAPABILITY_REPORT` 消息上报支持的操作类型（tap、swipe、screenshot、input_text 等）
- V2 侧 `handle_capability_report` 将其写入 `CapabilityAuthority`，使能力路由门可见

**执行参与层：**
- 接收 `TASK_ASSIGN` / `HANDOFF_ENVELOPE_V2` 等任务分发消息并执行
- 通过 `TASK_RESULT` / `HANDOFF_ENVELOPE_V2_RESULT` 回传执行结果
- 通过 `DELEGATED_EXECUTION_SIGNAL` 上报委托执行信号
- 通过 `RECONCILIATION_SIGNAL` 推送状态协调信号

**自治执行层：**
- 本地 AI 推理（无需 V2 实时参与）
- 本地感知 → 规划 → 执行完整 loop（`AutonomousExecutionPipeline`）
- 离线执行队列 + 重连后回放
- fallback 与 degradation 机制

**Android 当前不掌握的权威：**

Android 不持有以下中心权威（这是当前代码现实，不是缺陷判断）：

- 执行路径调度决策权（由 V2 的 `OpenClawd._determine_execution_path()` 持有）
- 跨节点路由权（由 `CommandRouter` 持有）
- 全局配置权（由 V2 的 `ConfigService` 持有）
- Operator 聚合观察权（由 V2 的 `OperatorSurface` 持有）
- 任务生命周期全局真相（由 V2 持有，Android 持有的是 execution-local truth）

### 4.3 桌面（Windows）当前是什么

桌面不是"装了 AI 的客户端"，它是 AI 系统在本地的**一个表现载体**。

**代码证据**：`core/execution/decision_executor.py` 文件头部注释明确说明 `DecisionExecutor` 是"subject's local manifestation layer on Windows"——这说明桌面是"主体（subject）在 Windows 上的直接表达"，而不是一个独立应用。

桌面 UI 的四状态（`system_integration/state_machine_ui_integration.py` 与 `system_integration/hardware_trigger.py`）：

- `DORMANT`：AI 主体处于静默状态
- `ISLAND`：AI 主体处于轻量感知 / 动态岛形态
- `SIDESHEET`：AI 主体展开至侧边栏形态
- `FULLAGENT`：AI 主体进入完整 Agent 展开状态

这四个状态不是"UI 窗口状态"，而是 **AI 主体在这一个表现面上的当前呈现形态**。

### 4.4 其他设备（平板、IoT、无人机、机器人等）

`core/device_types.py: DeviceType` 枚举包含：

```python
ANDROID, IOS, WINDOWS, MACOS, LINUX, BROWSER, CLOUD,
DRONE, PRINTER_3D, ROBOT, CAMERA, SENSOR, ACTUATOR, DISPLAY, SPEAKER, IOT, ...
```

设备注册 API（`core/device_registry.py: DeviceRegistry.register()`）对所有类型均开放，不区分优先级与特殊地位。`BodyMeshRegistry`（`core/mesh/body_mesh_registry.py`）将所有注册设备纳入网格并分配角色，用于任务调度与能力匹配。

这意味着：平板、IoT 设备、无人机、机器人等，**在协议与架构层面与 Android 持同等地位**，均可成为这套 AI 体系统的承载节点。

---

## 5. 为什么这套系统的本体是整个网络而不是某个端

### 5.1 关键判断

> 这套系统的**真实本体是 V2 与所有接入节点共同构成的整个协作网络**，不是任何单一端点。

任何将本系统本体理解为"一个 PC 应用"或"一个 Android App"的表述，均是对当前代码现实的误读。

### 5.2 代码层面的直接证据

**证据一：设备注册是网络准入，而不是客户端配对**

`DeviceRegistry.register()` 为所有设备类型提供统一的注册 API，注册后设备进入 `BodyMeshRegistry` 并获得网格角色。注册逻辑不分"主端"与"从端"，每个注册节点都是网络的一个组成部分。

**证据二：BodyMeshRegistry 明确建模了"网格"概念**

`core/mesh/body_mesh_registry.py: BodyMeshRegistry` 的文档注释中明确描述其建模的是"Body Mesh"（体网格）。其 `compute_assignment()` 方法为会话计算 primary/secondary body 分配，`get_by_role()` 方法按角色跨节点检索。这是一个网格模型，不是主从模型。

**证据三：执行路径可以是混合的**

`OpenClawd._determine_execution_path()` 支持 `hybrid` 路径，即本机与远端设备同时执行。这在架构上确认了"主体的执行可以同时跨越多个物理端"——这只有在本体是网络而不是单端的情况下才成立。

**证据四：HybridOrchestrationContinuityRegistry 建模跨端持续编排**

`core/hybrid_orchestration_continuity.py: HybridOrchestrationContinuityRegistry` 管理跨端执行的生命周期（包括 `transition()`、`list_non_terminal()` 等方法），直接体现了系统将跨端执行视为一个统一编排对象，而不是两个独立任务的叠加。

**证据五：能力查询跨越所有接入节点**

`core/capability_routing_gate.py: filter_by_required_capabilities()` 对传入的整个设备序列进行能力过滤，`DevicePoolManager.select_device()` 调用 `query_routable_executors()` 从全体接入节点中查询可执行者。能力查询的范围是整个网络，不是单端。

### 5.3 系统本体是网络，但有中心

明确区分：

- 本体是整个网络 ≠ 对等网格（peer mesh）。
- 整个网络有清晰的中心治理节点（V2），有明确的调度权威与任务真相持有者。
- 正确表述：**带中心治理的分布式 AI 体网络**。

---

## 6. 为什么当前已经越过 PoC 阶段

### 6.1 核心判断

> 当前系统**已经越过概念验证（PoC）阶段**，进入中后期整合巩固阶段。

这一判断基于以下代码现实：中心内核与运行时节点均已实质性成型，核心执行链路已经真实打通。

### 6.2 已成型的中心内核子系统

| 子系统 | 完成状态 | 代码锚点 |
|--------|---------|---------|
| AIP v3 统一协议（60+ 消息类型） | 已实现 | `galaxy_gateway/protocol/aip_v3.py` |
| Android WebSocket 网关 + 14 个专用处理器 | 已实现 | `galaxy_gateway/android_bridge.py`, `galaxy_gateway/android/handlers/` |
| 跨设备路由权威（CommandRouter） | 已实现 | `core/command_router.py` |
| 能力路由门（CapabilityRoutingGate） | 已实现 | `core/capability_routing_gate.py` |
| 执行路径四分支决策（OpenClawd） | 已实现 | `core/openclawd.py` |
| 能力录入（CapabilityAssimilationLayer） | 已实现 | `galaxy_gateway/android/handlers/registration.py` |
| 设备网格建模（BodyMeshRegistry） | 已实现，含持久化与自动恢复 | `core/mesh/body_mesh_registry.py` |
| Operator API 层（全端点） | 已实现 | `core/routes/operator.py` |
| Android 设备状态存储 | 已实现 | `core/android_device_state_store.py` |
| Hybrid 编排持续管理 | 已实现 | `core/hybrid_orchestration_continuity.py` |

### 6.3 已真实打通的核心执行链路

**Android 注册链**（已验证，有集成测试覆盖）：
```
handle_device_register
    → UDM upsert
    → DeviceRouter session sync
    → attach_runtime_session
    → CapabilityAssimilationLayer
    → BodyMeshRegistry.register()
```

**能力上报链**（已验证）：
```
handle_capability_report
    → CapabilityAuthority.upsert_contract()
    → 路由系统可见
    → BodyMeshRegistry 角色更新
```

**委托执行信号链**（已实现）：
```
DELEGATED_EXECUTION_SIGNAL
    → android_delegated_signal_ingress
    → OperatorSurface / FlowLevelOperatorSurface
```

**HandoffV2 结果回传链**（已实现）：
```
HANDOFF_ACK / HANDOFF_RESULT / HANDOFF_FAILURE / HANDOFF_ENVELOPE_V2_RESULT
    → V2 侧合并 → 任务真相更新
```

**代码层面的 PoC 判定标准**：PoC 阶段的特征是"能跑通单个演示路径、但核心子系统是桩件"。当前系统的中心内核子系统（路由、能力网络、网关、注册、Operator API）均已有真实实现，核心执行链路均已连通并有测试覆盖，因此当前阶段已经超越 PoC。

---

## 7. 当前剩余工作的真实主轴

### 7.1 核心判断

当前剩余工作的主轴**不是补足基础能力的缺失**，而是在已有基础能力之上完成**四个方向的最终收口**。

### 7.2 四个收口主轴

#### 主轴一：统一入口收口

**当前状态**：系统有多个入口（chat API、gateway WebSocket、launcher、desktop UI、Android WebSocket），但没有一个**统一的、能覆盖所有节点与所有维度的入口层**。

**代码证据**：`OpenClawd.process()` 接受 `entry_mode` 参数，说明当前入口层对"从哪里进来"仍有感知依赖，未完全统一为无差别的统一入口。

**收口目标**：任何设备、任何通道的接入都走同一套完整的入口规则，无差别地进入中心调度链。

#### 主轴二：统一状态透明度收口

**当前状态**：V2 侧已有完整的 `android_device_state_store`（`core/android_device_state_store.py`），`absorb_device_state_snapshot()` 与 `absorb_device_execution_event()` 接口也已实现。但 Android→V2 的运行时状态投影通道（`DEVICE_STATE_SNAPSHOT`、`DEVICE_EXECUTION_EVENT` 消息的 wire ingress 路径）尚未完整接通。

**实际影响**：V2 的设备生态端点（`GET /api/v1/operator/devices/ecosystem`）当前对 Android 运行时状态的了解仍主要停留在"注册态 / 能力态"层面，而不是完整的"运行态"（实时执行状态、当前任务状态、实时资源状况等）。

**收口目标**：Android 节点的完整运行时状态能够稳定投影到 V2 中心，并通过 Operator API 可查。

#### 主轴三：统一编排收口

**当前状态**：`CommandRouter.route_envelope()` 是跨设备路由的主入口，`HybridExecutionPolicy`（`core/hybrid_execution_policy.py`）定义了 hybrid 执行模式策略，`HybridOrchestrationContinuityRegistry` 管理跨端编排生命周期。但多设备并发编排、跨端任务拆分与聚合、multi-device session 协调等能力尚未形成完整的统一编排闭环。

**收口目标**：任意组合的多设备任务可以通过统一的编排层进行调度、监控与结果聚合，不依赖手动路由。

#### 主轴四：统一表现面收口

**当前状态**：各类 Operator API 已成型，但将这些 API 聚合为一个完整可用的**统一控制台 UI** 尚未完成。桌面 UI（`system_integration/state_machine_ui_integration.py`）实现了四状态生命周期，但作为"整套 AI 网络的统一表现面"仍有差距——Android 运行时状态、多设备生态状态、跨端任务进度等均未完整投影至可见界面层。

**收口目标**：存在一个统一的表现面，能够清晰展示整套 AI 网络的当前状态（包括所有接入节点的运行态、任务进度、能力分布等），并支持统一的操作入口。

### 7.3 剩余工作的精确描述

| 主轴 | 当前状态 | 收口方向 |
|------|---------|---------|
| 统一入口 | 多入口并存，entry_mode 仍有差异化路径 | 全通道无差别接入统一入口链 |
| 统一状态透明度 | 存储与接口已有，wire 通道未完整接通 | Android 运行态完整投影至 V2 |
| 统一编排 | 单设备路由完整，多设备并发编排未闭环 | 完整多设备任务编排闭环 |
| 统一表现面 | API 完整，UI 控制台未成型 | 整套 AI 网络统一可视化控制台 |

---

## 8. 后续推进应坚持的方向

### 8.1 核心方向声明

> 后续所有的推进工作，都应**沿着"统一 AI 体网络"的方向向前走**，而不是退化为传统的"多客户端产品"思维。

### 8.2 应坚守的方向

**方向一：所有设备都是 AI 体的承载面，不是"客户端"**

任何新增设备类型的设计，都应基于"这是 AI 主体在这类设备上的表现面"这一前提，而不是"这是一个需要接入中心 AI 的客户端应用"。区别在于：前者从主体出发，后者从客户端出发。代码中已有的 `BodyMeshRegistry`、`DeviceType` 枚举、能力录入机制，都是支持前者的基础设施。

**方向二：中心权威必须持续清晰，不应弱化**

V2 的中心治理权威（调度、路由、能力网络、任务真相、状态投影）是当前系统正确运转的基础。后续工作应在保持中心权威清晰的前提下，逐步提升各节点的能力宣告能力与状态投影完整度，而不是通过分散权威来"赋能"各端。

**方向三：Android 应升级为更完整的运行时参与者，而不是维持现有通道**

当前 Android 已经是强运行时节点，但其运行态对 V2 仍不透明。后续应将 Android 的实时执行状态、本地 AI 状态、离线队列状态等完整投影至 V2，使 V2 能够基于完整信息进行调度决策，而不是仅凭注册态与能力态进行判断。

**方向四：统一表现面应体现整套网络，而不仅是单台设备**

桌面 UI 四状态是一个好的方向——它将桌面定性为 AI 主体的一个表现面，而不是一个独立应用。后续的统一表现面应将这一逻辑推广到整套网络，使任意表现面上都能看到整个 AI 体网络的完整状态，而不是仅看到本端的状态。

**方向五：新的能力节点应通过已有注册机制接入，不应绕开**

`DeviceRegistry.register()`、`CapabilityAssimilationLayer`、`BodyMeshRegistry` 已经构成一套完整的节点接入机制。后续所有新类型节点（平板、IoT、无人机、机器人等）的接入，都应走这条已有路径，而不是通过特殊化路径绕开中心能力网络。

### 8.3 应避免的方向

- **不应退化为"PC 主控 + 手机从属"的产品思维**：这是对当前代码架构的降级理解，会导致设计决策与代码现实背离。
- **不应将控制台 UI 理解为系统核心**：UI 是表现面，不是本体。系统的本体是中心内核 + 运行时节点 + 协议网络。
- **不应在没有代码支撑的情况下宣称"任何设备都可以接管系统"**：当前代码明确区分了执行责任与治理权威，任何节点都可以承担执行，但治理权威仍在 V2。
- **不应将剩余工作理解为"从头做起"**：当前系统的基础能力已经很强，剩余工作是收口，不是重建。

---

## 附录：本文核心结论速查

| 结论 | 代码依据 |
|------|---------|
| 系统是带中心治理的分布式 AI 体网络 | `core/device_types.py`（通用设备枚举）+ `core/mesh/body_mesh_registry.py`（体网格）+ `core/command_router.py`（中心路由） |
| V2 是唯一中心治理权威 | `core/openclawd.py`（调度决策）+ `core/command_router.py`（路由）+ `core/routes/operator.py`（Operator API） |
| Android 是强运行时节点，不是被动终端 | `galaxy_gateway/android/handlers/`（14 个处理器）+ Android 仓库 `AutonomousExecutionPipeline`、`LocalAIRuntime` |
| 桌面是 AI 主体的本机表现面，不是独立应用 | `core/execution/decision_executor.py`（"subject's local manifestation layer"）+ `system_integration/state_machine_ui_integration.py`（四状态） |
| 系统已越过 PoC 阶段 | 核心子系统均已实现 + 主要执行链已打通 + 集成测试覆盖 |
| 剩余工作主轴是四个收口而非基础能力缺失 | `core/android_device_state_store.py`（存储已有，wire 通道未完整）+ `core/routes/operator.py`（API 已有，UI 控制台未成型） |
| 后续方向：统一 AI 体网络，不是多客户端产品 | `core/device_registry.py`（统一注册）+ `core/mesh/body_mesh_registry.py`（网格模型） |
