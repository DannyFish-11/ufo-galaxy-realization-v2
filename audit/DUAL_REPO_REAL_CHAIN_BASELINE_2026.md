# 双仓真实链路认知基线

## ——`ufo-galaxy-realization-v2` × `ufo-galaxy-android` 全链路权威审查基线

**PR 性质**：Dual-Repo Real-Chain Audit / Cognitive Baseline PR  
**生效日期**：2026-05-06  
**审查方法**：仅基于两仓当前 merged 真实代码主链，不以 README、文档口号、自评文件为第一证据  
**后续修复 PR 上位基线**：本文档所有判断为后续实质修复 PR 的权威起点

---

## 目录

1. [系统总定性与统一口径](#1-系统总定性与统一口径)
2. [V2 仓真实骨架](#2-v2-仓真实骨架)
3. [Android 仓真实骨架](#3-android-仓真实骨架)
4. [本地链路 / 跨设备链路 / 多设备链路](#4-本地链路--跨设备链路--多设备链路)
5. [Android 默认本地模式 vs 跨设备模式](#5-android-默认本地模式-vs-跨设备模式)
6. [自然语言链路](#6-自然语言链路)
7. [多模态链路](#7-多模态链路)
8. [全端系统图景](#8-全端系统图景)
9. [当前真正仍需解决的问题清单](#9-当前真正仍需解决的问题清单)
10. [后续实质修复 PR 拆分建议](#10-后续实质修复-pr-拆分建议)

---

## 1. 系统总定性与统一口径

### 1.1 它不是什么

基于两仓真实代码，以下定性**明确不成立**：

| 排除的错误定性 | 代码级证伪依据 |
|---|---|
| 普通多端 App | V2 有 `openclawd.py` 单主体核心、三态生命周期、统一认知场，不是多端 UI 工程 |
| 中心 server + 被动客户端 | Android 有 `AutonomousExecutionPipeline`、`EdgeExecutor`、`LocalGoalExecutor`、`DelegatedTakeoverExecutor`，具备本地真实执行能力，不是被动端 |
| 去中心平权多主体系统 | V2 的 `source_dispatch_orchestrator.py` 持有 dispatch authority；`android_device_state_store.py` 持有 Android 状态真相；`AttachedRuntimeSessionRegistry` 持有 session 真相；所有权威在 V2 |
| 仅有几个 surface 的 UI 工程 | 两仓合计有完整的 runtime 层、protocol 层、execution 层、perception 层、operator 层、session 层 |

### 1.2 它是什么（真实代码定性）

**这套双仓系统是：以 V2/桌面为统一智能体主载体与中心治理核心、以 Android 为设备侧智能体载体的中心分布式智能体系统。**

证明路径（全部来自真实代码主链）：

```
V2 DesktopPresenceRuntime (外层 shell，Windows desktop clothing)
    └─ 持有 runtime_session_id（单一稳定关联 ID）
    └─ 驱动 tri-state 生命周期（SILENT → LIMINAL → MANIFEST）
    └─ 持有 MultimodalIngressBus（连续主机感知）
    └─ 在 LIMINAL 阶段调用 OpenClawd
         └─ OpenClawd (内层主体核心)
               Stage 1: Ingest (PerceptionFrame + multimodal_context)
               Stage 2: Continuum / Liminal 认知
               Stage 3: 执行路径分支 (local / cross_device / hybrid / none)
               Stage 4: Manifest (DecisionExecutor / CommandRouter)
```

```
Android GalaxyConnectionService (Android 设备侧 runtime/service)
    └─ 维持与 V2 gateway 的 WebSocket 连接
    └─ 接收 AIP v3 消息（task_assign / goal_execution / takeover_request 等）
    └─ 路由到本地执行链 or 中心委派执行链
         ├─ 本地链: AutonomousExecutionPipeline → LocalGoalExecutor → EdgeExecutor
         └─ 委派链: DelegatedRuntimeReceiver → DelegatedTakeoverExecutor → AutonomousExecutionPipeline
```

### 1.3 "中心""分布式""智能体"三词的真实代码落地

#### 中心
**中心指 V2 持有以下权威**：

- **主体身份 / 认知核心**：`OpenClawd`（`core/openclawd.py`）- 唯一单例主体核心
- **runtime authority**：`DesktopPresenceRuntime`（`core/desktop_presence_runtime.py`）- 外层 shell，拥有 runtime_session_id 和三态生命周期
- **state truth**：`android_device_state_store`（`core/android_device_state_store.py`）- V2 侧 Android 状态权威存储；`AttachedRuntimeSessionRegistry`（`core/attached_runtime_session_registry.py`）- session 真相权威
- **orchestration authority**：`source_dispatch_orchestrator`（`core/runtime/source_dispatch_orchestrator.py`）- 源侧 dispatch 权威，决策 local / remote handoff / mesh-staged dispatch
- **协议定义**：AIP v3（`galaxy_gateway/protocol/aip_v3.py`）- 所有平台必须遵循的统一协议
- **truth surface**：`UnifiedPanelAggregationService`（`core/unified_panel_aggregation.py`）- 聚合 6 个状态家族的统一面板

#### 分布式
**分布在以下层**：

- **设备载体**：V2（Windows desktop）+ Android（手机/平板）
- **执行分布**：V2 `CommandRouter[REMOTE]` → gateway → Android `AutonomousExecutionPipeline` → `LocalGoalExecutor` → `EdgeExecutor`
- **感知分布**：V2 `MultimodalIngressBus`（连续主机感知）+ Android `AccessibilityScreenshotProvider` + Android local inference（`LocalGroundingService`/`LocalPlannerService`）
- **协作执行**：`parallel_subtask` 消息类型支持跨设备并行子任务
- **多端入口**：`/api/v1/chat`（桌面）、Android NLP 入口（`GoalNormalizer`）、gateway WebSocket 入口

#### 智能体
**"智能体"落在以下真实代码结构上**：

- **统一 runtime**：`DesktopPresenceRuntime` + `OpenClawd` 的两层结构构成 unified subject runtime
- **核心认知/执行核**：`OpenClawd` 持有 `ContinuumOrchestrator`（意图→状态连续体）+ `AgentKernel`（认知子核）
- **统一 session/continuity**：`AttachedRuntimeSessionRegistry`（PR-19）- 持有 durable_session_id + continuity_epoch
- **统一多模态解释链**：`MultimodalBus.ingest`（request-bound fusion）+ `MultimodalIngressBus`（连续感知）
- **统一 action→result→feedback 主链**：V2 `canonical_roundtrip.py` + Android `DelegatedExecutionSignal`（ACK→PROGRESS→RESULT）
- **Android 设备侧智能体结构**：`AgentRuntimeBridge`（本地/跨设备路由）+ `DelegatedTakeoverExecutor`（接管执行）+ `LocalGoalExecutor`（本地目标执行）

---

## 2. V2 仓真实骨架

### 2.1 主体核心层

#### OpenClawd (`core/openclawd.py`)

**真实位置**：内层主体核心（subject core）。  
**不是**：与 DesktopPresenceRuntime 平行的独立主体。

```
职责（来自 docstring 和代码结构）：
    Stage 1: Ingest
        ├─ PerceptionFrame（来自 shell 的连续主机感知）
        └─ multimodal_context（请求绑定的多模态 payload，通过 MultimodalBus.ingest 融合）
    Stage 2: Continuum / Liminal 认知
        └─ ContinuumOrchestrator → intent → state_continuum
    Stage 3: 执行路径分支 (_determine_execution_path)
        ├─ local       → DecisionExecutor（Windows/System API 本地执行）
        ├─ cross_device → CommandRouter[REMOTE] → gateway（跨设备展开）
        ├─ hybrid      → 两个循环同时运行
        └─ none        → 无 manifestation（仅响应）
    Stage 4: Manifest
        └─ DecisionExecutor（本地）/ CommandRouter（跨设备）
```

**state_continuum** 的 `runtime_domain` 字段决定执行路径，`execution_path` 字段暴露在响应中供 shell 记录。

#### DesktopPresenceRuntime (`core/desktop_presence_runtime.py`)

**真实位置**：外层运行时 shell（Windows desktop clothing）。

```
职责：
    - 持有 runtime_session_id（整个请求生命周期的稳定关联 ID）
    - 驱动 tri-state 生命周期（SILENT → LIMINAL → MANIFEST → SILENT）
    - 持有 MultimodalIngressBus（连续主机感知，PerceptionFrame）
    - 在 LIMINAL 阶段调用 OpenClawd.process()，传入 runtime_session_id
    - 记录每次状态迁移的可观测性 hook

三态生命周期（subject lifecycle）：
    SILENT   → 主体静止；MultimodalIngressBus 持续感知
    LIMINAL  → 收到请求；OpenClawd 认知/执行中
    MANIFEST → 主体正在产生输出/控制设备；执行后回到 SILENT
```

**注意区分三个相互独立的状态系统**：
1. Tri-state lifecycle（SILENT/LIMINAL/MANIFEST）→ DesktopPresenceRuntime 拥有
2. Continuum posture（tri_state_phase + runtime_domain）→ ContinuumOrchestrator（OpenClawd 内部）拥有
3. UI shell states（DORMANT/ISLAND/SIDESHEET/FULLAGENT）→ system_integration/ 拥有

### 2.2 入口层（route / ingress）

**权威声明**：`core/api_routes.py` 是唯一权威 REST API 定义（`CANONICAL_API_ROUTES_AUTHORITY`）。

| 路由 | 子模块 | 角色定性 |
|---|---|---|
| `POST /api/v1/chat` | `core/routes/chat.py` | **兼容性适配器表面**（无 subject-core authority）→ DesktopPresenceRuntime |
| `GET /api/v1/operator/*` | `core/routes/operator.py` | **规范 operator 控制面**（PR-510/PR-3）|
| `GET /api/v1/panel/unified` | `core/routes/panel.py` | 统一面板聚合读取端点 |
| `GET /api/v1/existence/surface` | `core/routes/existence.py` | 存在面投影读取端点 |
| `GET /api/v1/operator/devices/ecosystem` | `core/routes/operator.py` | Android 生态状态（来自 android_device_state_store）|
| `WS /ws/device/{device_id}` | `galaxy_gateway/routes/websocket.py` | **规范设备入口**（CANONICAL）|
| `WS /ws/device/{device_id}` in api_routes | `core/api_routes.py` | **兼容路径**（COMPATIBILITY-ONLY，非规范主入口）|

**关键**：`/api/v1/chat` 的权威链：

```
HTTP POST /api/v1/chat
    → core/routes/chat.py（兼容适配器，无 authority）
        → DesktopPresenceRuntime.handle_request(source="chat")
            → TriState: SILENT → LIMINAL → OpenClawd → MANIFEST → SILENT
                → response（含 runtime_session_id, execution_authority）
```

### 2.3 Orchestration / Dispatch 层

#### SourceDispatchOrchestrator (`core/runtime/source_dispatch_orchestrator.py`)

**真实位置**：V2 侧执行编排权威（PR-35）。

```
职责：
    - select_dispatch_mode()   → 给定上下文信号，选择 SourceDispatchMode
    - select_dispatch_target() → 给定 mesh/设备上下文，选择 SourceDispatchTarget
    - build_source_dispatch_plan() → 组装完整 SourceDispatchPlan
    - orchestrate_source_runtime_dispatch() → 端到端：选模式 → 建计划 → 执行（本地路径或远程 handoff）→ 返回 SourceDispatchResult

决策逻辑：
    - 本地执行：调用 OpenClawd._run_execution()
    - 远程 handoff：调用 galaxy_gateway.agent_bridge helpers
    - 支持 PR-34 的 target_takeover.execute_local_takeover()
```

### 2.4 State / Session / Continuity 层

#### AttachedRuntimeSessionRegistry (`core/attached_runtime_session_registry.py`)

**真实位置**：PR-19 引入，Android 附加运行时 session 的规范单一真相权威。

```
职责：
    - 追踪哪些 attached runtime sessions 当前活跃
    - 每个 device_id 最多对应一个 active session
    - 提供 runtime_session_id（注册时生成的稳定 opaque ID，跨 reconnect 不变）
    - 持有 durable_session_id（可跨进程重启的持久 session ID，PR 记忆中已确认）
    - 持有 continuity_epoch（跨重启纪元验证）
    - 状态机：PENDING → ACTIVE → REPLACED / INVALIDATED（合法迁移由 _REGISTRY_TRANSITIONS 控制）
```

#### AndroidDeviceStateStore (`core/android_device_state_store.py`)

**真实位置**：V2 侧 Android→V2 控制面状态投影的规范存储权威。

```
消息类型（通过 AIP v3 WebSocket 入站）：
    DEVICE_STATE_SNAPSHOT → DeviceStateSnapshot（native runtime 可用性、readiness、模型身份、本地循环配置、离线队列深度、fallback 阶梯层级、运行时健康）
    DEVICE_EXECUTION_EVENT → DeviceExecutionEvent（flow_id、task_id、phase、step_index、blocking state）

公开 API：
    absorb_device_state_snapshot(device_id, payload) → None
    absorb_device_execution_event(device_id, payload) → None
    get_device_state_snapshot(device_id) → Optional[DeviceStateSnapshot]
    list_device_state_snapshots() → List[DeviceStateSnapshot]
    get_device_ecosystem_summary() → Dict[str, Any]
    list_recent_execution_events(flow_id, device_id, limit) → List[DeviceExecutionEvent]
```

### 2.5 Panel / Existence / Operator / Roundtrip 层

#### UnifiedPanelAggregationService (`core/unified_panel_aggregation.py`)

**真实位置**：PR-1，统一面板/运行时聚合面（单一规范入口）。

```
聚合的 6 个状态家族：
    1. Operator/控制面投影    ← OperatorSurface（task counts, device presence, topology）
    2. Shell/presence 表现    ← OperatorSnapshot（desktop_shell_state, presence_tristate）
    3. Android runtime/生态  ← android_device_state_store（get_device_ecosystem_summary()）
    4. Continuum/流执行状态   ← build_runtime_projection()（tri_state_phase, runtime_domain）
    5. 执行就绪度             ← runtime_readiness_matrix（readiness_verdict, blocked_dimensions）
    6. 活跃 surface spec      ← SurfaceSelector（当前或默认交互模式的 SurfaceSpec）

暴露于：GET /api/v1/panel/unified
```

**角色定性**：聚合面，不是真相面。所有子域的真相仍由各自的权威 singleton 持有。

#### DesktopExistenceSurface (`core/desktop_existence_surface.py`)

**真实位置**：PR-2，规范存在面（统一 5 个状态家族）。

```
统一的 5 个状态家族：
    1. SubjectLifecycleSnapshot  ← DesktopPresenceRuntime（tri-state：SILENT/LIMINAL/MANIFEST）
    2. ShellClothingSnapshot     ← SystemStateMachine（DORMANT/ISLAND/SIDESHEET/FULLAGENT）
    3. ContinuumPostureSnapshot  ← ContinuumOrchestrator（tri_state_phase + runtime_domain）
    4. CognitiveFieldSnapshot    ← CognitiveFieldEngine（activation, intent_strength, stability）
    5. AndroidPresenceSignals    ← android_device_state_store（DeviceStateSnapshot 清单）

ExistenceProjection（只读裁定）：dormant / background / active / expressing
暴露于：GET /api/v1/existence/surface
```

**角色定性**：只读派生投影，不引入新状态机。

#### OperatorSurface 和 FlowLevelOperatorSurface

```
OperatorSnapshot 含：
    - android_ecosystem（count-level，白名单键，无 per-device 'devices' 列表）
    - active_flow_count（来自 DelegatedFlowEntityRuntime）
    - desktop_shell_state, presence_tristate, manifestation_summary

FlowOperatorProjection：
    - to_dict() 含 '_authority' 键
    - 暴露于 GET /api/v1/operator/flows
```

### 2.6 Gateway / Protocol 层

#### AIP v3 (`galaxy_gateway/protocol/aip_v3.py`)

**真实位置**：系统唯一协议事实来源。所有平台必须遵循。

```
设备类型：AIPDeviceType（android_phone, android_tablet, ..., windows_desktop, ...）
消息类型（MessageType）：
    注册/心跳：device_register, heartbeat, agent_status, device_state_snapshot, device_execution_event
    任务：task_assign, goal_execution, parallel_subtask
    接管：takeover_request, takeover_result
    Handoff：handoff_envelope_v2, handoff_envelope_v2_result
    委派：delegated_execution_signal
    多设备：mesh_topology, peer_exchange, peer_announce

Android 侧 Kotlin 对应：AipMessage, MsgType（通过 com.ufo.galaxy.protocol 包对齐）
```

#### WebSocket Handler (`galaxy_gateway/websocket_handler.py`)

**真实位置**：gateway 层的本地传输状态处理器（PR-10）。

```
职责（传输层）：
    - 接受/关闭 WebSocket 连接（设备 ingress/egress）
    - 强制 AIP v3+ 协议帧（自动注入缺失的 trace_id/route_mode）
    - 将接受的消息标准化为 NormalizedIngressEvent（PR-5）
    - 分发传输类消息（register, heartbeat, status, wake, session_migrate）
    - 将 Android 业务消息委派给 android_bridge（PR-03-V2 委派边界）
    - 将权威在线/可路由状态委托给 UnifiedConnectionManager (UCM)

职责（不包含）：
    - Android 特定业务 dispatch（在 AndroidBridge 中）
    - 全局 readiness truth（在 system_orchestrator 中）
    - entry-mode 决策（在 core/ 编排层中）
    - 编排资格（在 canonical_device_selector 中）
```

#### AndroidBridge (`galaxy_gateway/android_bridge.py`)

**真实位置**：Android-specific action/payload 翻译适配器（PR-S4）。

```
职责（保留）：
    1. 处理 AIP v3 WebSocket 协议的收发与标准化
    2. 将服务端任务翻译为 Android 可执行的 AIP 命令（action/payload translation）
    3. 处理 Android 端返回的结果并触发记忆回流
    4. 维护 WebSocket 连接句柄的传输/会话层本地缓存

职责（已移除，不可误解）：
    ✗ 不持有独立设备 presence 权威（在 UDM + UCM）
    ✗ 不持有独立任务 dispatch 权威（在 DeviceRouter）
```

### 2.7 Multimodal 层

```
V2 多模态入口（两条独立路径）：
    1. 连续主机感知（Continuous host perception）
       → MultimodalIngressBus（owned by DesktopPresenceRuntime shell）
       → PerceptionFrame 对象（音频、视频、系统信号的环境感知上下文）
    
    2. 请求绑定多模态上下文（Request-bound multimodal context）
       → OpenClawd.process() 的 multimodal_context kwarg
       → MultimodalBus.ingest() 产生 fusion_summary（附加到 prompt）

位于：core/multimodal/（ingress_bus.py, perception_frame.py, ingest_runtime.py, webrtc_session.py 等）
```

---

## 3. Android 仓真实骨架

### 3.1 Android 主 Runtime/Service 层

#### GalaxyConnectionService (`service/GalaxyConnectionService.kt`)

**真实位置**：Android 侧最核心的主入口（`class GalaxyConnectionService : Service()`）。

```
角色：Android foreground Service，同时是：
    - Connection hub：维持与 V2 gateway 的 WebSocket（通过 GalaxyWebSocketClient）
    - Message dispatcher：将所有入站 AIP v3 消息分发给对应处理器
    - Agent host：管理本地 takeover state（activeTakeoverId）
    - Model manager：加载/卸载 MobileVLM 和 SeeClick 模型

路由模式常量（来自 AgentRuntimeBridge）：
    ROUTE_MODE_CROSS_DEVICE = "cross_device"
    ROUTE_MODE_LOCAL       = "local"（仅内部，默认路由）

PR-3 规范接管默认值：
    TAKEOVER_DEFAULT_MAX_STEPS = 10
    TAKEOVER_DEFAULT_TIMEOUT_MS = 0L（无超时）

activeTakeoverId（volatile）：当前活跃接管的 takeover_id；
    由 TakeoverEligibilityAssessor 用于阻止并发接管

关键组件：
    - takeoverEligibilityAssessor：接管资格评估器（设备就绪度）
    - delegatedRuntimeReceiver：委派运行时接收门（PR-8）
    - handoffContractValidator：Handoff 合约验证器
    - taskCancelRegistry：任务取消注册表
```

### 3.2 本地执行层

#### AutonomousExecutionPipeline (`agent/AutonomousExecutionPipeline.kt`)

**真实位置**：跨设备运行时的门控执行管道。

```
核心逻辑：
    所有 goal_execution 和 parallel_subtask 的处理都受以下门控：
    
    Gate 1（运行时门）：AppSettings.crossDeviceEnabled == true
        → false → 立即返回 STATUS_DISABLED
    Gate 2（特性门，在 Gate 1 通过后）：
        handleGoalExecution:    AppSettings.goalExecutionEnabled
        handleParallelSubtask:  AppSettings.parallelExecutionEnabled
    Gate 3（策略门）：GoalExecutionPayload.policy_routing_outcome != "rejected"
    Gate 4（posture 门）：SourceRuntimePosture != CONTROL_ONLY

STATUS_DISABLED：网关可区分"设备拒绝"与"设备尝试并失败"
STATUS_TIMEOUT / STATUS_HOLD：用于区分超时和暂时不可用

结论：这两类消息类型由 gateway 通过跨设备 WebSocket 通道专属交付，
      必须不在没有该运行时的情况下独立执行。
```

#### EdgeExecutor (`agent/EdgeExecutor.kt`)

**真实位置**：本地边缘执行器。执行 Android-local 的单步操作（accessibility actions、UI grounding、截图）。

#### LocalGoalExecutor (`agent/LocalGoalExecutor.kt`)

**真实位置**：本地目标执行器，协调 EdgeExecutor 完成多步目标。

### 3.3 接管 / 委派 / 协同层

#### DelegatedTakeoverExecutor (`agent/DelegatedTakeoverExecutor.kt`)

**真实位置**：PR-12/13/15，从接受委派接收到本地接管执行流水线的规范绑定。

```
生命周期（闭合）：
    DelegatedRuntimeReceiver → receipt accepted
        │
        │  DelegatedRuntimeUnit + DelegatedActivationRecord(PENDING)
        ▼
    DelegatedTakeoverExecutor
        ├─ 创建 DelegatedExecutionTracker（PENDING）
        ├─ 发出 ACK 信号（EMISSION_SEQ_ACK）
        ├─ 推进至 ACTIVATING → ACTIVE
        ├─ 发出 PROGRESS 信号（EMISSION_SEQ_PROGRESS）
        ├─ 调用 AutonomousExecutionPipeline（实际执行）
        ├─ 发出 RESULT 信号（EMISSION_SEQ_RESULT，含 ResultKind）
        └─ 返回 ExecutionOutcome（Completed / Failed）

信号类型：DelegatedExecutionSignal.Kind（ACK / PROGRESS / RESULT）
结果类型：ResultKind（COMPLETED / TIMEOUT / CANCELLED / FAILED）
每个信号含：signalId（UUID 幂等键）+ emissionSeq（单调序列位置）

EmittedSignalLedger（PR-18）：每次执行创建，记录所有发出的信号；支持重放。
```

#### AgentRuntimeBridge (`agent/AgentRuntimeBridge.kt`)

**真实位置**：本地/跨设备路由网桥。

```
路由逻辑：
    1. AppSettings.crossDeviceEnabled == false → localResult()（cross_device_off）
    2. request.execMode == EXEC_MODE_LOCAL → localResult()（exec_mode_local）
    3. 否则 → 调用 gateway handoff（跨设备路由）

模式常量：
    EXEC_MODE_LOCAL  = "local"
    EXEC_MODE_REMOTE = "remote"
    EXEC_MODE_BOTH   = "both"
    ROUTE_MODE_CROSS_DEVICE = "cross_device"
    ROUTE_MODE_LOCAL        = "local"
    STATUS_LOCAL = "local"
```

#### DelegatedRuntimeReceiver (`agent/DelegatedRuntimeReceiver.kt`)

**真实位置**：PR-8，委派运行时接收门。在附加 session 下对接受委派工作设置门控（设备就绪度检查）。

#### HandoffContractValidator (`agent/HandoffContractValidator.kt`)

**真实位置**：验证 `HandoffEnvelopeV2` 的合约合法性。

### 3.4 设备能力层

| 组件 | 文件 | 真实角色 |
|---|---|---|
| AccessibilityActionExecutor | `service/AccessibilityActionExecutor.kt` | 通过无障碍服务执行 Android UI 操作 |
| AccessibilityScreenshotProvider | `service/AccessibilityScreenshotProvider.kt` | 通过无障碍服务截图 |
| EnhancedFloatingService | `service/EnhancedFloatingService.kt` | 浮窗/覆盖层 UI（overlay）|
| FloatingWindowService | `service/FloatingWindowService.kt` | 浮窗服务 |
| BootReceiver | `service/BootReceiver.kt` | 开机自启动（foreground service 持久化）|
| HardwareKeyListener | `service/HardwareKeyListener.kt` | 硬件按键拦截 |
| VoiceRecognitionService | `service/VoiceRecognitionService.kt` | 语音识别 |
| ReadinessChecker | `service/ReadinessChecker.kt` | 设备就绪度检查 |

### 3.5 感知 / 视觉 / 多模态相关层

#### 本地推理层（inference/）

| 组件 | 文件 | 真实角色 |
|---|---|---|
| LocalGroundingService | `inference/LocalGroundingService.kt` | 本地 UI 定位（SeeClick/MobileVLM）|
| LocalPlannerService | `inference/LocalPlannerService.kt` | 本地规划（goal → steps）|
| DegradedGroundingService | `inference/DegradedGroundingService.kt` | 降级 fallback 定位 |
| DegradedPlannerService | `inference/DegradedPlannerService.kt` | 降级 fallback 规划 |

**注意**：本地推理（MobileVLM + SeeClick）模型由 `GalaxyConnectionService` 在 `onStart` 时加载（`setModelCapabilities`），在 `onDestroy` 时卸载。

#### NLP 层（nlp/）

| 组件 | 文件 | 真实角色 |
|---|---|---|
| GoalNormalizer | `nlp/GoalNormalizer.kt` | 将 NL 目标规范化为结构化形式 |
| NormalizedGoal | `nlp/NormalizedGoal.kt` | 规范化目标数据类 |
| AppAliasRegistry | `nlp/AppAliasRegistry.kt` | App 名称别名注册表 |

**Android NL 处理**：Android 本地有 NL 目标规范化（`GoalNormalizer`），但最终 LLM 语义由中心 V2 负责。

---

## 4. 本地链路 / 跨设备链路 / 多设备链路

### 4.1 V2 本地链路

```
V2 本地链路（完整）：
    用户输入（桌面 UI / /api/v1/chat）
        → DesktopPresenceRuntime.handle_request(source="chat")
            → SILENT → LIMINAL
            → OpenClawd.process(runtime_session_id)
                → ContinuumOrchestrator（意图 → state_continuum，runtime_domain = "local"）
                → execution_path = "local"
                → DecisionExecutor → WindowsExecutionArbiter → LocalExecutionResult
            → MANIFEST → SILENT
        → UnifiedChatResponse（含 runtime_session_id, execution_path="local"）

备注：LOCAL_EXECUTION_CHAIN 已在 core/local_execution_chain.py 有专项文档
```

### 4.2 Android 默认本地链路

```
Android 本地链路（crossDeviceEnabled = false 时，默认情况）：
    本地触发（UI 交互 / 语音 / 浮窗输入）
        → GalaxyConnectionService（收到本地触发，非 gateway 消息）
        → AgentRuntimeBridge（execMode = LOCAL）→ localResult()
        → LocalGoalExecutor（执行目标）
            → EdgeExecutor（accessibility actions, screenshot, grounding）
                → LocalGroundingService（SeeClick/MobileVLM，local inference）
        → 结果返回本地 UI（不经过 V2 gateway）

注意：当 crossDeviceEnabled = false 时，gateway 发来的 goal_execution / parallel_subtask
      会被 AutonomousExecutionPipeline 直接返回 STATUS_DISABLED，不执行。
```

### 4.3 V2 ↔ Android 跨设备链路

```
跨设备链路（V2 侧）：
    OpenClawd._determine_execution_path() → "cross_device"
        → CommandRouter[REMOTE]
        → TaskEnvelope（含 task_id, trace_id, route_mode="cross_device"）
        → galaxy_gateway（WebSocket handler + AndroidBridge）
        → WebSocket → GalaxyConnectionService（Android 侧）

跨设备链路（Android 侧，crossDeviceEnabled = true）：
    GalaxyConnectionService.onMessage()
        ├─ goal_execution → AutonomousExecutionPipeline.handleGoalExecution()
        │    → LocalGoalExecutor → EdgeExecutor → GoalResultPayload
        │    → GoalResult 通过 WebSocket 回送 V2
        ├─ parallel_subtask → AutonomousExecutionPipeline.handleParallelSubtask()
        │    → LocalCollaborationAgent → LocalGoalExecutor → 结果回送
        └─ takeover_request → handleTakeoverRequest()
             → TakeoverEligibilityAssessor（资格评估）
             → DelegatedRuntimeReceiver（接收门控）
             → DelegatedTakeoverExecutor（生命周期管理 + 信号发射）
             → AutonomousExecutionPipeline（实际执行）
             → DelegatedExecutionSignal（ACK/PROGRESS/RESULT）回送 V2

回流链（Android → V2）：
    GoalResultPayload → WebSocket → galaxy_gateway
        → android_bridge.handle_task_result() → V2 operator surface / flow tracking
        → android_device_state_store（DEVICE_EXECUTION_EVENT 入库）
        → FlowLevelOperatorSurface（执行阶段可观测）
```

**证据**：`core/android_device_state_store.py`（`absorb_device_execution_event`）、`core/flow_level_operator_surface.py`（FlowTruthAlignmentRuntime）、`galaxy_gateway/android/handlers/device_state_snapshot.py`。

### 4.4 多设备链路

**当前真实状态**：

```
已存在的结构：
    - AIP v3 支持 MeshTopologyPayload, PeerExchangePayload, PeerAnnouncePayload
    - Android 侧有 LocalCollaborationAgent（协调 parallel_subtask 执行）
    - V2 侧有 SourceDispatchOrchestrator（staged_mesh + PR-J live runtime 路径）
    - V2 侧有 core/mesh/ 目录（live_mesh_runtime_engine / live_mesh_session_coordinator / persistence）

尚未完全闭合：
    - 双仓 authority contract 仍是关键约束：Android LocalCollaborationAgent 运行权威在 Android 仓，不在 V2 仓内闭合
    - panel/operator/surface 必须明确暴露 mesh_runtime_state（partial/constrained/deferred）而非只依赖结构性代码叙事
    - parallel_subtask 跨两个以上 Android 设备的端到端运行级闭环仍需 Android 侧实机证据

当前收敛结论（基于真实代码）：
    - V2 内：已具备 staged_mesh 调度 + live mesh runtime engine + coordinator 的运行级证据（partial runtime proof）
    - 双仓整体：仍为 partial/constrained；需 Android 侧 authority/runtime 配套证明才能宣称 fully closed

运行关系（runtime relationship）：
    SourceDispatchOrchestrator(staged_mesh)
        -> delegated execution envelope(goal_execution/parallel_subtask)
        -> Android LocalCollaborationAgent（Android 仓 authority）
        -> result 回流 V2 operator/panel/state store
```

---

## 5. Android 默认本地模式 vs 跨设备模式

### 5.1 钉死：Android 默认不是天然接管态

**证据（`AutonomousExecutionPipeline.kt` docstring）**：

> "Both [handleGoalExecution] and [handleParallelSubtask] are **subordinate to the canonical runtime pipeline**: they require [AppSettings.crossDeviceEnabled] to be `true` before any per-feature check is evaluated."

**结论**：
- `crossDeviceEnabled = false`（默认值）→ 所有 gateway 下发的 goal_execution / parallel_subtask / takeover_request **立即返回 STATUS_DISABLED**，不执行
- Android 默认模式下只执行本地触发的 LOCAL 任务
- 没有 `crossDeviceEnabled = true`，Android 就是一个本地智能体载体，不接受来自 V2 的执行委派

### 5.2 Android 默认本地模式的真实链路

```
默认本地模式（crossDeviceEnabled = false）：
    本地输入 → GalaxyConnectionService → AgentRuntimeBridge（EXEC_MODE_LOCAL）
        → localResult() → LocalGoalExecutor → EdgeExecutor
        → 本地完成，不经过 gateway

特殊情况（即使 crossDeviceEnabled = false）：
    - WebSocket 连接仍然维持（心跳、设备状态上报正常运行）
    - DEVICE_STATE_SNAPSHOT / DEVICE_EXECUTION_EVENT 仍然上报给 V2
    - V2 侧 android_device_state_store 仍然接收并存储这些信息
```

### 5.3 跨设备模式开启后发生什么

```
crossDeviceEnabled = true 时：
    1. AutonomousExecutionPipeline 通过 Gate 1
    2. goal_execution 消息流程（若 goalExecutionEnabled = true）：
       收到 GoalExecutionPayload → policy/posture 检查 → LocalGoalExecutor → 结果回送
    3. parallel_subtask 消息流程（若 parallelExecutionEnabled = true）：
       收到并行子任务 → LocalCollaborationAgent → 结果回送
    4. takeover_request 消息流程：
       收到 → TakeoverEligibilityAssessor → DelegatedRuntimeReceiver → DelegatedTakeoverExecutor
```

### 5.4 Agent Runtime 分配/并入手机到底意味着什么

```
"把 agent runtime 分配/并入手机"的真实代码语义：
    1. V2 侧 SourceDispatchOrchestrator 选择目标 Android 设备
    2. V2 通过 CommandRouter[REMOTE] → gateway 发送 goal_execution 或 takeover_request
    3. Android DelegatedRuntimeReceiver 在 delegated_session 的 gate 通过后接受
    4. DelegatedTakeoverExecutor 创建 DelegatedExecutionTracker，管理完整执行生命周期
    5. AutonomousExecutionPipeline 调用 LocalGoalExecutor → EdgeExecutor 实际执行
    6. 结果通过 DelegatedExecutionSignal → WebSocket → V2 回流

这是"并入"的真实代码含义：
    - 不是"Android 成为独立智能体"
    - 不是"Android 脱离 V2 独立决策"
    - 是"V2 将特定任务委派给 Android 本地执行能力，Android 是执行载体，V2 是编排权威"
```

### 5.5 Takeover 在什么条件下成立

```
takeover_request 的完整条件链：
    1. Android crossDeviceEnabled = true（AppSettings gate）
    2. DelegatedRuntimeReceiver 接受（attached session gate）
    3. HandoffContractValidator 验证合约合法性
    4. TakeoverEligibilityAssessor 评估设备就绪度（无当前活跃 takeover）
    5. activeTakeoverId == null（并发保护）
    6. AutonomousExecutionPipeline Gate 通过（goalExecutionEnabled 等特性门）

结论：takeover 是 mode-gated + session-gated + readiness-gated 的
```

### 5.6 Android 本地链路与中心链路的叠合

```
两条链路在 Android 侧是叠合存在的，不是互斥的：
    - 本地链路：持续可用（AccessibilityActionExecutor, EdgeExecutor 等）
    - 跨设备链路：仅在 crossDeviceEnabled = true 时开启
    - 设备状态上报：始终运行（DEVICE_STATE_SNAPSHOT, heartbeat）
    - 两条链路通过 GalaxyConnectionService 统一管理，共享 WebSocket 连接
```

### 5.7 PR-1029 之后还缺哪些更完整的制度化工作

（基于代码主链审查）：

1. **模式状态的运行时可观测性**：`crossDeviceEnabled` 的当前值是否实时反映在 V2 的 operator surface / panel 中？`DeviceStateSnapshot` 中有 `local_loop_config` 字段，但完整的 mode-status 暴露需要确认是否已经闭合。

2. **模式切换的 session 连续性**：从 local 切换到 cross_device 模式时，`AttachedRuntimeSessionRegistry` 的 session 是否正确迁移/注册？

3. **多特性门的统一治理**：`goalExecutionEnabled`、`parallelExecutionEnabled`、`crossDeviceEnabled` 三个门的统一管理策略尚未有独立的 policy 层。

---

## 6. 自然语言链路

### 6.1 V2/桌面本地 NL 入口

```
入口：POST /api/v1/chat（或桌面 UI 直接输入）
    → core/routes/chat.py（兼容适配器）
    → DesktopPresenceRuntime.handle_request(source="chat")
        → OpenClawd.process(text=用户文本, runtime_session_id=...)
            → ContinuumOrchestrator（意图解析 → state_continuum）
            → AgentKernel（认知子核，不直接从路由调用）
            → LLM 调用（通过 MultiLLMRouter）
            → 执行路径决策（local / cross_device / hybrid / none）

NL → action → result → feedback 完整链：
    用户 NL → OpenClawd → LLM response → execution_path 分支
    → local: DecisionExecutor → LocalExecutionResult → 回到 OpenClawd
    → cross_device: CommandRouter[REMOTE] → Android 执行 → GoalResultPayload 回流
    → feedback（memory backflow, session continuity）→ 下一轮对话
```

### 6.2 Android 本地 NL 入口

```
Android 端 NL 处理（本地）：
    本地触发（语音/输入）
        → VoiceRecognitionService（语音识别，如适用）
        → GoalNormalizer（NL goal → NormalizedGoal）
            → AppAliasRegistry（App 名称别名解析）
        → LocalGoalExecutor（执行规范化后的目标）
            → LocalPlannerService（规划 goal → steps）
            → LocalGroundingService（UI grounding）
            → EdgeExecutor（执行 steps）

关键限制：
    - Android 本地 NL 处理（GoalNormalizer）只做结构化，不做 LLM 语义理解
    - 真正的 LLM 语义承载者在 V2（OpenClawd + AgentKernel + MultiLLMRouter）
    - Android 本地 NL 处理属于"goal 规范化"，不属于"语义 LLM 推理"
```

### 6.3 Android 跨设备模式下 NL 请求如何进入中心智能体主链

```
跨设备 NL 路径（crossDeviceEnabled = true）：
    方式 1（推荐）：用户在手机 NL 输入 → 通过 V2 /api/v1/chat（网络请求）
        → V2 OpenClawd 处理语义 → V2 决策跨设备 → Android 执行
    
    方式 2（已存在结构）：用户在手机输入 → 
        GoalNormalizer（规范化）→ GalaxyConnectionService → AIP v3 goal_execution 消息
        → V2 gateway 接收 → V2 android_bridge 处理 → V2 OpenClawd 处理语义？

关键说明：
    方式 2 的语义载体路径（GoalNormalizer 输出 → V2 LLM 语义理解）
    在当前代码中尚未完全闭合审查，这是需要进一步钉死的问题之一（见第 9 节）。
```

### 6.4 Source/Carrier 与最终语义承载者的区分

```
source/carrier：NL 输入发生在哪个设备/入口（手机 / 桌面）
语义承载者：谁做 LLM 语义推理（V2 OpenClawd + AgentKernel + LLM）

当前代码中：
    - 语义权威在 V2（OpenClawd 持有 ContinuumOrchestrator + AgentKernel）
    - Android 有本地 NL 结构化能力（GoalNormalizer），但不做 LLM 推理
    - 不管 NL 从哪个入口进来，最终语义必须经过 V2 LLM 主链
    - Android 本地规划（LocalPlannerService）是本地 task decomposition，不是 LLM semantic reasoning
```

### 6.5 Action/Result/Feedback 如何统一回中心

```
统一回中心的路径（跨设备情况）：
    Android 执行 → GoalResultPayload → WebSocket → galaxy_gateway
        → android_bridge.handle_task_result()
        → V2 android_device_state_store（DEVICE_EXECUTION_EVENT 入库）
        → FlowLevelOperatorSurface（flow tracking）
        → DelegatedFlowEntityRuntime（flow truth）
        → UnifiedPanelAggregationService（面板可见）
        → MemoryBackflow（记忆回流，openclawd_memory_backflow.py）

本地执行情况：
    DecisionExecutor → LocalExecutionResult → OpenClawd feedback → session continuation
```

---

## 7. 多模态链路

### 7.1 当前多模态主宿主

**明确定性**：**当前多模态主宿主在 V2/桌面**。

```
证据来自 core/openclawd.py（注释明确）：
    两条独立多模态输入路径（均在 V2）：
    1. 连续主机感知：MultimodalIngressBus（DesktopPresenceRuntime 拥有）
       → PerceptionFrame（音频/视频/系统信号的 Windows 环境感知）
    2. 请求绑定多模态上下文：multimodal_context kwarg → MultimodalBus.ingest
       → fusion_summary 附加到 prompt

多模态处理层（V2，core/multimodal/）：
    - ingress_bus.py（MultimodalIngressBus）
    - perception_frame.py（PerceptionFrame）
    - ingest_runtime.py（融合运行时）
    - vad.py（语音活动检测）
    - video_ingest.py / audio_ingest.py（视频/音频入口）
    - webrtc_session.py / webrtc_session_manager.py（WebRTC 会话）
    - signal_quality.py（信号质量）
```

### 7.2 Android 视觉/感知/边缘能力在系统中的真实角色

```
Android 视觉/感知能力（已确认在真实代码中存在）：
    - LocalGroundingService：本地 UI grounding（SeeClick/MobileVLM）
    - LocalPlannerService：本地规划
    - AccessibilityScreenshotProvider：截图能力
    - DeviceStateSnapshot.mobilevlm_present / seeclick_present / mobilevlm_checksum_ok
      （在 android_device_state_store 中记录，V2 可查询）

当前系统角色定性：
    - Android 视觉能力（MobileVLM/SeeClick）用于本地 UI grounding（找到要点击的 UI 元素）
    - 这是"本地 UI 感知定位"，不是"多模态语义理解"
    - Android 截图可通过 vision 消息类型（ANDROID_VISION）发送给 V2（galaxy_gateway/android/handlers/vision.py）
    - V2 android_vlm_service.py 处理 Android VLM 请求

android_vision 入口已标准化（来自记忆中已确认的代码）：
    galaxy_gateway/android/handlers/vision.py 
    → 已通过 session_id, user_id, entry_mode 传入 DesktopPresenceRuntime.handle_request()
    → 结果含 ingress_carrier_context stamp
```

### 7.3 多模态统一发生在哪些层

```
多模态统一（V2 侧）：
    层 1：MultimodalIngressBus（连续感知的 PerceptionFrame 汇聚）
    层 2：MultimodalBus.ingest（请求绑定的多模态 context 融合，产生 fusion_summary）
    层 3：OpenClawd（将 PerceptionFrame + multimodal_context 整合进认知阶段）
    层 4：UnifiedPanelAggregation（聚合面上展示 Android presence）

Android 侧感知数据进入 V2 主链的两条路径：
    路径 A（结构化状态）：DEVICE_STATE_SNAPSHOT → android_device_state_store → UnifiedPanelAggregation
    路径 B（视觉请求）：ANDROID_VISION → galaxy_gateway/android/handlers/vision.py → DesktopPresenceRuntime.handle_request()
```

### 7.4 如何避免桌面/Android 双真相

```
避免双真相的架构设计（已在代码中确立）：
    - V2 android_device_state_store 是 V2 侧 Android 状态的单一真相（ANDROID_DEVICE_STATE_STORE_AUTHORITY）
    - AndroidBridge 的 self._devices 不是设备事实来源（移除了 presence authority）
    - 设备事实来源：UDM（UnifiedDeviceManager）+ UCM（UnifiedConnectionManager）
    - OperatorSnapshot.android_ecosystem 只含 count-level 键（无 per-device 'devices' 列表，避免 SSoT 扩散）

尚未完全闭合的双真相风险（见第 9 节问题）：
    - Android local inference 结果（LocalGroundingService 输出）是否有系统级采信机制？
    - Android 视觉感知参与 V2 多模态的制度化仍未完整
```

---

## 8. 全端系统图景

### 8.1 当前真实覆盖的端/载体/层

| 层面 | 覆盖的组件 | 真实状态 |
|---|---|---|
| **runtime** | V2 DesktopPresenceRuntime + OpenClawd | ✅ 真实 live |
| **control plane** | SourceDispatchOrchestrator, OperatorSurface, UnifiedPanelAggregation | ✅ 真实 live |
| **execution plane (local)** | DecisionExecutor, WindowsExecutionArbiter（V2）; LocalGoalExecutor, EdgeExecutor（Android）| ✅ 真实 live |
| **execution plane (cross-device)** | CommandRouter[REMOTE] → gateway → Android AutonomousExecutionPipeline | ✅ 结构存在，需 crossDeviceEnabled=true |
| **perception plane (V2)** | MultimodalIngressBus, PerceptionFrame, audio/video ingest | ✅ 真实 live |
| **perception plane (Android)** | AccessibilityScreenshotProvider, LocalGroundingService (MobileVLM/SeeClick) | ✅ 能力存在，系统级采信部分 |
| **presence plane** | DesktopExistenceSurface（5 状态家族）| ✅ 真实 live（只读投影）|
| **protocol plane** | AIP v3（aip_v3.py 和 Android protocol 包完全对齐）| ✅ 真实 live |
| **session plane** | AttachedRuntimeSessionRegistry（durable_session_id + continuity_epoch）| ✅ 真实 live |
| **state plane** | android_device_state_store（DEVICE_STATE_SNAPSHOT + DEVICE_EXECUTION_EVENT）| ✅ 真实 live |
| **surface plane** | /api/v1/panel/unified, /api/v1/existence/surface, /api/v1/operator/* | ✅ 真实 live |
| **NL/LLM plane** | OpenClawd + AgentKernel + MultiLLMRouter（V2）; GoalNormalizer（Android 本地）| ✅ V2 完整；Android 仅结构化 |
| **multi-device mesh** | AIP v3 mesh 消息类型; SourceDispatchOrchestrator mesh-aware 计划 | ⚠️ declared / partial（Mesh Session Coordinator 推迟）|
| **multi-modal unified** | V2 MultimodalBus + Android ANDROID_VISION 路径 | ⚠️ 路径存在，系统制度化未完整 |
| **Android cross-device runtime** | DelegatedTakeoverExecutor + AutonomousExecutionPipeline | ⚠️ 需 crossDeviceEnabled=true，默认关闭 |

### 8.2 哪些是真实 live 的

✅ **真实 live**（有真实代码+运行路径）：
- V2 主链（DesktopPresenceRuntime → OpenClawd → execution branch）
- AIP v3 协议（双仓完全对齐）
- WebSocket 连接（GalaxyConnectionService ↔ V2 gateway）
- 设备状态上报（DEVICE_STATE_SNAPSHOT, DEVICE_EXECUTION_EVENT）
- V2 operator/panel/existence 控制面
- Android 本地执行能力（EdgeExecutor, LocalGoalExecutor, LocalGroundingService）
- 接管生命周期（DelegatedTakeoverExecutor，mode-gated）
- Session 连续性（AttachedRuntimeSessionRegistry）

### 8.3 哪些是 declared / partial / capability-only

⚠️ **partial / capability-only**（结构存在但未完整制度化或需开启开关）：
- Android 跨设备执行（需 crossDeviceEnabled=true，默认关闭）
- Android 视觉/感知数据进入 V2 多模态主链（路径存在，制度化未完整）
- Android local inference 结果被 V2 authoritative 采信（MobileVLM/SeeClick presence 在 DeviceStateSnapshot 中有字段，但 V2 是否消费作为 authoritative 感知结论尚未完全钉死）
- Multi-device mesh 编排（AIP v3 消息类型存在，Mesh Session Coordinator 推迟到 PR-37）
- Android 本地 NL → V2 LLM 语义主链的完整路径（GoalNormalizer 输出结构化后，进入 V2 LLM 的完整链尚需更多实证）

---

## 9. 当前真正仍需解决的问题清单

以下问题清单**仅基于真实代码主链审查**得出，不含假设性问题：

### P1：Android 默认本地模式 vs 跨设备模式的制度边界未完整闭合

**真实问题**：
- `crossDeviceEnabled` gate 已存在于 `AutonomousExecutionPipeline`，但其值的变化（local↔cross_device 切换）触发的 session 状态迁移在 `AttachedRuntimeSessionRegistry` 中的完整处理路径尚未完全审查
- V2 侧何时认为 Android 处于"跨设备就绪"状态（基于 `DeviceStateSnapshot` 字段）的 readiness 逻辑尚需更强实证
- mode-gate 存在，但跨越 mode 切换的 session 连续性协议未有独立的权威文件

**后续修复方向**：专项 PR 补全 mode-gate ↔ session-registry 的协议一致性证明

### P2：Android 本地 NL 与跨设备 NL 语义未完全澄清

**真实问题**：
- Android `GoalNormalizer` 负责 NL 结构化，但 Android 本地直接触发 LocalGoalExecutor 时，LLM 语义由谁承载？`LocalPlannerService` 是否包含真正的语义理解，还是仅做 rule-based 规划？
- Android 跨设备 NL 请求（用户在手机 NL 输入 → goal_execution 发送给 V2）的完整语义处理路径（GoalNormalizer 输出 → V2 如何做 LLM 语义推理）尚未有 end-to-end 测试证明

**后续修复方向**：`LocalPlannerService` 的语义边界专项文档 + Android→V2 NL e2e 路径测试

### P3：Android 本地能力哪些已被 V2 authoritative 采信，哪些仍只是 capability 存在

**真实问题**：
- `DeviceStateSnapshot` 中有 `mobilevlm_present`/`seeclick_present`/`mobilevlm_checksum_ok` 字段，V2 `SourceDispatchOrchestrator`（`_score_candidate()`）已接受 `android_snapshot` 参数
- 但"V2 确实在 dispatch 决策时消费了 Android local inference 能力"的完整链路（`_score_candidate` → 基于 `mobilevlm_present` 加权 → 实际影响任务分配）尚需端到端代码审查确认

**后续修复方向**：`source_dispatch_orchestrator._score_candidate()` 专项审查，确认 Android local inference capability 在 V2 dispatch 中的实际权重

### P4：Takeover 已 mode-gated，但更广泛的委派/执行/权威策略仍未完整统一

**真实问题**：
- `takeover_request` 已经有完整的 mode-gate + session-gate + readiness-gate 链
- 但 `goal_execution` / `parallel_subtask` 的接受条件（`goalExecutionEnabled`/`parallelExecutionEnabled`）与 `takeover_request` 的接受条件（`TakeoverEligibilityAssessor`）是两套独立的门控，它们之间的一致性保证（例如：如果 Android 系统当前在做 takeover，goal_execution 是否应该被阻止？）尚未有统一的 authority policy

**后续修复方向**：Android 执行类型之间的并发策略文档化（goal_execution vs parallel_subtask vs takeover 的互斥/优先级规则）

### P5：多模态主宿主与 Android 感知参与的统一制度化仍未闭合

**真实问题**：
- V2 多模态主链已确立（MultimodalIngressBus + MultimodalBus.ingest）
- Android `ANDROID_VISION` 路径（`galaxy_gateway/android/handlers/vision.py`）已标准化，但以下未完整：
  - Android 截图何时/如何被提升为 V2 多模态 context 的一部分（而不仅仅是一次性 vision 请求）？
  - Android 连续感知数据（如 accessibility tree 变化）是否有路径汇入 V2 `MultimodalIngressBus`？

**后续修复方向**：Android perception → V2 MultimodalIngressBus 的参与协议专项 PR

### P6：Android 视觉/感知/边缘推理的系统级地位仍未完全清晰

**真实问题**：
- `LocalGroundingService`（SeeClick）和 `LocalPlannerService`（本地规划）是 Android 侧真实存在的能力
- 但这些能力的系统级定性不明：它们是"V2 委派给 Android 的执行子能力"，还是"Android 独立的边缘智能体能力"？
- 如果是"V2 委派的执行子能力"：V2 是否在 dispatch 时显式知道 Android 有这些能力并据此委派任务？（`_score_candidate()` 中的能力加权是否覆盖 grounding capability？）
- 如果是"独立边缘智能体能力"：独立运作时（本地模式，不经过 V2）的能力边界在哪里？

**后续修复方向**：Android edge intelligence 系统级地位的权威声明文档

### P7：跨设备 Runtime 闭环仍缺更强实证

**真实问题**：
- V2 → Android 的完整跨设备 roundtrip（发出任务 → 执行 → 结果回流 → V2 内部状态更新）的代码路径已经存在
- 但专项端到端集成测试（类似 V2 侧已有的 `test_nl_e2e_canonical_path.py`）尚缺一个对应的跨设备 e2e 测试套件
- 现有测试主要覆盖 V2 内部路径和 Android 内部路径，双仓 roundtrip 的机器可验证证明较弱

**后续修复方向**：双仓 cross-device roundtrip e2e 测试套件（模拟 Android 端，验证完整 V2→Android→V2 循环）

### P8：多设备链路仍缺更明确运行级证明

**真实问题**：
- AIP v3 协议层面支持 mesh 多设备（`MeshTopologyPayload`/`PeerExchangePayload`）
- `SourceDispatchOrchestrator` 声明 mesh-aware staged dispatch 支持（但 Mesh Session Coordinator 明确推迟到 PR-37）
- `LocalCollaborationAgent`（Android 侧）支持 parallel_subtask 的本地协调
- 但两个以上设备同时参与任务的完整运行级证明（V2 调度 → 多个 Android 设备同时执行 → 结果汇聚）尚缺

**后续修复方向**：Mesh Session Coordinator 专项 PR（PR-37 计划）

### P9：全端系统图景仍未从结构存在走向运行时闭合

**真实问题**：
- 多个层面（protocol plane, control plane, session plane, state plane）已经闭合
- 但"整套全端系统在运行时统一协同"的闭环验证尚缺：在一个真实会话中，V2 接受 NL 请求 → 决策跨设备 → Android 执行 → 结果回流 → V2 session 更新 → 下一轮对话继续 → 这个完整闭环的运行时证明
- 目前各层独立有测试，但全端 roundtrip 的端到端测试覆盖较弱

**后续修复方向**：全端 roundtrip 集成测试（含 NL → V2 LLM → cross-device dispatch → Android execution → V2 feedback 的完整链）

### P10：统一智能体治理语义仍需继续向下打透

**真实问题**：
- "V2 是中心治理核心，Android 是设备侧智能体载体"这一定性已在代码中有多处体现
- 但"治理"的具体语义（特别是 Android 本地 NL 决策是否需要 V2 审批？Android 独立感知结论是否可不经 V2 直接在本地触发执行？Android 本地模式下 V2 的 authority 边界在哪里？）尚未有一个统一的权威 policy 文件明确

**后续修复方向**：统一智能体治理语义专项文档（定义 V2 的 authority 边界范围 + Android 的 autonomy 边界范围）

---

## 10. 后续实质修复 PR 拆分建议

基于上述 10 个真实问题，建议后续实质修复 PR 按以下维度拆分：

| 优先级 | PR 主题 | 对应问题 | 主要产出 |
|---|---|---|---|
| P1 | Mode-gate ↔ Session-registry 协议一致性闭合 | P1 | mode 切换时的 session 迁移合约 + 测试 |
| P1 | 跨设备 roundtrip e2e 测试套件 | P7 | 机器可验证的双仓 roundtrip 测试 |
| P2 | Android 本地 NL 语义边界澄清 | P2 | LocalPlannerService 语义边界文档 + Android→V2 NL e2e 路径测试 |
| P2 | Android edge intelligence 系统级地位权威声明 | P6 | 系统级地位权威文档 + dispatch ability mapping |
| P3 | Android capability 在 V2 dispatch 中的实际消费审查 | P3, P4 | _score_candidate() + 执行并发策略专项审查 |
| P3 | Android perception → V2 MultimodalIngressBus 参与协议 | P5 | Android 视觉参与多模态链的协议文档 + 实现 |
| P4 | 统一智能体治理语义文档 | P10 | V2 authority + Android autonomy 边界权威声明 |
| P4 | Mesh Session Coordinator 实现（PR-37）| P8, P9 | 多设备 mesh 运行时闭合 |

---

## 附录：关键代码文件快速索引

### V2 仓 (`ufo-galaxy-realization-v2`)

| 文件 | 角色 |
|---|---|
| `core/openclawd.py` | 主体核心（cognition + execution nucleus）|
| `core/desktop_presence_runtime.py` | Runtime shell（outer Windows clothing）|
| `core/api_routes.py` | 唯一权威 REST API 定义 |
| `core/routes/chat.py` | /api/v1/chat 兼容适配器表面 |
| `core/routes/operator.py` | 规范 operator 控制面 |
| `core/routes/panel.py` | 统一面板聚合端点 |
| `core/routes/existence.py` | 存在面投影端点 |
| `core/unified_panel_aggregation.py` | PR-1 统一面板聚合服务 |
| `core/desktop_existence_surface.py` | PR-2 存在面（5 状态家族）|
| `core/android_device_state_store.py` | V2 侧 Android 状态权威存储 |
| `core/attached_runtime_session_registry.py` | PR-19 session 真相权威 |
| `core/runtime/source_dispatch_orchestrator.py` | PR-35 源侧 dispatch 权威 |
| `core/runtime/target_takeover.py` | PR-34 目标侧接管执行 |
| `core/operator_surface.py` | OperatorSurface + OperatorSnapshot |
| `core/flow_level_operator_surface.py` | 流级算子面（Android 执行阶段可见）|
| `galaxy_gateway/protocol/aip_v3.py` | AIP v3 协议单一事实来源 |
| `galaxy_gateway/websocket_handler.py` | gateway 传输层处理器 |
| `galaxy_gateway/android_bridge.py` | Android action/payload 翻译适配器 |
| `galaxy_gateway/android/handlers/vision.py` | Android 视觉 ingress 处理器 |
| `galaxy_gateway/android/handlers/device_state_snapshot.py` | 设备状态快照入库处理器 |

### Android 仓 (`ufo-galaxy-android`)

| 文件 | 角色 |
|---|---|
| `service/GalaxyConnectionService.kt` | Android 主 runtime/connection hub（foreground Service）|
| `agent/AutonomousExecutionPipeline.kt` | 跨设备执行门控管道 |
| `agent/AgentRuntimeBridge.kt` | 本地/跨设备路由网桥 |
| `agent/DelegatedTakeoverExecutor.kt` | 委派接管执行器（PR-12/13/15）|
| `agent/DelegatedRuntimeReceiver.kt` | 委派运行时接收门（PR-8）|
| `agent/EdgeExecutor.kt` | 本地边缘执行器 |
| `agent/LocalGoalExecutor.kt` | 本地目标执行器 |
| `agent/LocalCollaborationAgent.kt` | 并行子任务本地协调器 |
| `agent/HandoffContractValidator.kt` | Handoff 合约验证器 |
| `agent/TakeoverEligibilityAssessor.kt` | 接管资格评估器 |
| `inference/LocalGroundingService.kt` | 本地 UI 定位（SeeClick/MobileVLM）|
| `inference/LocalPlannerService.kt` | 本地规划服务 |
| `nlp/GoalNormalizer.kt` | NL goal 规范化器 |
| `service/AccessibilityActionExecutor.kt` | 无障碍 UI 操作执行器 |
| `service/AccessibilityScreenshotProvider.kt` | 无障碍截图提供者 |
| `service/BootReceiver.kt` | 开机自启动接收器 |
| `service/EnhancedFloatingService.kt` | 浮窗 UI 覆盖层服务 |

---

*本基线文档为后续所有实质修复 PR 的权威起点。任何对本文档判断的修正必须基于真实代码主链，并作为独立 PR 提出，附代码证据。*
