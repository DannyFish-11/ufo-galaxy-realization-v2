# 双仓联合系统认知与综合审查报告

> **审查范围**：  
> `DannyFish-11/ufo-galaxy-realization-v2`（V2，Python，中心侧）  
> `DannyFish-11/ufo-galaxy-android`（Android，Kotlin，执行端侧）  
>
> **审查依据**：基于两个仓库的真实代码（2026-04-25 快照），不以未合并文档为主要依据。  
> **目标**：建立一份联合、完整的系统认知，覆盖所有主要架构层次，而非局部审查。

---

## 一、这套系统是什么

### 1.1 一句话定义

> **Galaxy 双仓系统是一套以 V2 Python 服务为 canonical 编排中心、以 Android 设备为 delegated runtime 执行端的跨端任务生命周期闭环平台。**
>
> 其核心命题是：让 Android 成为 Galaxy/V2 主运行时中的正式 delegated participant，并让跨端任务生命周期的全程状态——调度、授权转移（handoff/takeover）、执行、结果上报、真值对齐、连续性恢复、审计、发布治理——在双仓之间形成完整闭环。

### 1.2 这不是什么

- **不是普通移动端 App + 后端服务组合**：Android 不是消费层，而是具备独立 runtime authority、session 状态、continuity 语义和信号协议的执行参与方。
- **不是简单的 task_submit/task_result 管道**：系统在任务之上叠加了 handoff 协议、takeover 协商、delegated execution signal、reconciliation signal、participant truth ingress 等完整的生命周期语义。
- **不是单端系统**：两仓任意一端都无法独立完成 delegated execution lifecycle，它们互为依赖，通过 AIP v3 wire protocol 形成双向有状态协议。

---

## 二、双仓在系统中的角色

### 2.1 V2 的角色：canonical 编排中心与真值权威

V2（`ufo-galaxy-realization-v2`）不是单一用途服务，而是以下多个层次的叠加：

| 职责层 | 核心代码 | 说明 |
|--------|---------|------|
| **Transport ingress / gateway** | `galaxy_gateway/android/` (handlers × 16) | Android 消息的单一入站点，每个消息类型有专属 handler |
| **Lifecycle authority** | `core/android_delegated_runtime_lifecycle_coordinator.py` (PR-11-V2) | 单一 orchestration facade，所有 lifecycle event 的权威处理入口 |
| **Session state machine** | `core/android_participant_session_state.py` (PR-11-V2) | `pre_dispatch` → `handoff_dispatched` → `takeover_pending` → `execution` → `reconciling` → `terminal` 完整 9 阶段状态机 |
| **Truth reconciliation** | `core/android_participant_truth_ingress.py` (PR-4V2) | Android 本地真值入站并对齐到 V2 canonical 编排状态的权威入口 |
| **Audit / observability** | `core/android_delegated_runtime_audit.py` (PR-10-V2) | 统一审计层，6 种事件类型、按 task_id 可查 |
| **Dispatch binding** | `core/android_runtime_dispatch_binding.py` | session/device/contract/tracker 四维绑定，是"哪个 Android session 在执行哪个任务"的唯一权威答案 |
| **Continuity coordinator** | `core/flow_continuity_coordinator.py` (PR-3-V2) | 统一 continuity decision 入口，覆盖 fresh_attach / continuity_resume / reject_stale / dedupe / partial_result 5 种决策 |
| **Readiness/Acceptance/Governance gate** | `core/delegated_flow_readiness_gate.py` (PR-9V2), `core/delegated_flow_acceptance_gate.py` (PR-10V2), `core/delegated_flow_post_graduation_governance.py` (PR-11V2) | 发布治理框架，6 种 readiness verdict、graduation verdict、5 种 violation/compliant |
| **Memory backflow** | `core/openclawd_memory_backflow.py` (PR-7) | 任务完成后写入 TaskMemory，供后续 LLM 上下文注入 |
| **Compat/legacy blocking** | `core/compat_legacy_path_blocking_canonicalization.py` (PR-8) | 阻断 legacy ingress 路径，强制走 canonical path |

**关键结论**：V2 侧已经形成了完整的"单入口 → 统一协调器 → 状态机 → 审计"的 canonical 架构。每一条 Android 上行消息都有且只有一个 handler，每个 handler 都委托给同一个 lifecycle coordinator，coordinator 在正确的顺序下调用 ingress、state reduction 和 audit。

### 2.2 Android 的角色：自主 runtime 参与方，不是被动接收端

Android（`ufo-galaxy-android`）不是普通移动端壳子，而是具备以下能力的 runtime 参与方：

| 职责层 | 核心代码 | 说明 |
|--------|---------|------|
| **Transport ingress（下行）** | `service/GalaxyConnectionService.kt` (125KB) | WebSocket 连接管理、入站消息分发、handoff envelope 接收、result 上报 |
| **Runtime lifecycle authority** | `runtime/RuntimeController.kt` (149KB) | Android 侧跨端 runtime 的唯一生命周期权威：Idle / Starting / Active / Failed / LocalOnly |
| **Delegated work receipt gate** | `agent/DelegatedRuntimeReceiver.kt` (PR-8 Android) | delegated work 接受的单一授权入口，enforces session 必须 ATTACHED 才能接受工作 |
| **Takeover execution** | `agent/DelegatedTakeoverExecutor.kt` | takeover 执行器，承接 V2 发来的 takeover_request |
| **Handoff contract** | `agent/DelegatedHandoffContract.kt`, `agent/HandoffEnvelopeV2.kt` | handoff 协议的 Android 侧实现，含 contract 验证和 envelope 消费 |
| **Reconciliation signal** | `runtime/ReconciliationSignal.kt` (PR-51) | 7 种信号类型（TASK_ACCEPTED / STATUS_UPDATE / RESULT / CANCELLED / FAILED / PARTICIPANT_STATE / RUNTIME_TRUTH_SNAPSHOT）结构化的 Android→V2 对账通道 |
| **Continuity integration** | `runtime/AndroidContinuityIntegration.kt` (PR-3 Android) | Android 侧统一 continuity 决策入口：FRESH_ATTACH / CONTINUITY_RESUME / PROCESS_RECREATION_REATTACH / TRANSPORT_RECONNECT / RECEIVER_PIPELINE_REBIND |
| **Offline durability** | `network/OfflineTaskQueue.kt` | 断线时缓存 task_result/goal_result，重连后 FIFO drain，最大 50 条，SharedPreferences 持久化（24 小时有效期） |
| **Capability / readiness evaluation** | `runtime/DelegatedRuntimeReadinessEvaluator.kt`, `DelegatedRuntimeAcceptanceEvaluator.kt`, `DelegatedRuntimeGovernanceDimension.kt`, `DelegatedRuntimeStrategyEvaluator.kt` | 四维本地评估器，产出 DeviceReadinessArtifact 等 artifact |
| **Compat/legacy blocking** | `runtime/AndroidCompatLegacyBlockingParticipant.kt` | Android 侧 compat gate，阻断 legacy 上报路径 |
| **Session state** | `runtime/AttachedRuntimeSession.kt` | 附着 session 的 Android 本地表示，ATTACHED / DETACHING / DETACHED 三态 |
| **Memory backflow（trigger）** | `service/GalaxyConnectionService.kt` (注释明确) | task_result 发送后触发 V2 侧 memory backflow |
| **Observability** | `observability/` 包, `runtime/RuntimeObservabilityMetadata.kt` | 运行时可观测性元数据 |

**关键结论**：Android 已经不是被动接收命令的普通客户端。它有自己的 runtime state authority（RuntimeController），有明确的 session 概念（AttachedRuntimeSession），有四维评估器（readiness/acceptance/governance/strategy），有完整的 continuity 语义，有 offline queue。这是一个真正意义上的"端侧 participant runtime"。

---

## 三、系统主链路与层次结构

### 3.1 系统层次图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  V2 侧（ufo-galaxy-realization-v2）                                          │
│                                                                             │
│  ┌─────────────────────────────────┐  ┌──────────────────────────────────┐  │
│  │  Transport / Ingress 层          │  │  Governance / Release Gate 层    │  │
│  │  galaxy_gateway/android/handlers│  │  delegated_flow_readiness_gate   │  │
│  │  · 16 种消息类型，单一入站点      │  │  delegated_flow_acceptance_gate  │  │
│  │  · 每类型 1 个 handler           │  │  delegated_flow_post_graduation_ │  │
│  │  · 委托 → lifecycle coordinator │  │    governance                    │  │
│  └──────────────┬──────────────────┘  └──────────────────────────────────┘  │
│                 │ 委托                                                        │
│  ┌──────────────▼──────────────────┐  ┌──────────────────────────────────┐  │
│  │  Runtime Authority / Lifecycle   │  │  Continuity / Recovery 层        │  │
│  │  android_delegated_runtime_      │  │  flow_continuity_coordinator     │  │
│  │    lifecycle_coordinator (PR-11) │  │  · 5 种 continuity decision      │  │
│  │  · on_handoff_dispatched         │  │  · fresh_attach / resume /       │  │
│  │  · on_takeover_response          │  │    reject_stale / dedupe /       │  │
│  │  · on_reconciliation_signal      │  │    preserve_partial              │  │
│  │  · on_execution_signal           │  └──────────────────────────────────┘  │
│  │  · on_participant_truth_update   │                                         │
│  └──────────────┬──────────────────┘  ┌──────────────────────────────────┐  │
│                 │ 调用                 │  Truth / Reconciliation 层        │  │
│  ┌──────────────▼──────────────────┐  │  android_participant_truth_ingress│  │
│  │  Session State Machine 层        │  │  android_execution_signal_        │  │
│  │  android_participant_session_    │  │    reconciler                    │  │
│  │    state (PR-11)                 │  │  · V2 is canonical authority     │  │
│  │  · 9 阶段状态机                  │  │  · Android truth = device-local  │  │
│  │  · phase-monotonic + signal-     │  └──────────────────────────────────┘  │
│  │    driven + thread-safe          │                                         │
│  └─────────────────────────────────┘  ┌──────────────────────────────────┐  │
│                                        │  Audit / Observability 层         │  │
│  ┌─────────────────────────────────┐  │  android_delegated_runtime_audit  │  │
│  │  Dispatch Binding 层             │  │  · 6 种事件类型                  │  │
│  │  android_runtime_dispatch_       │  │  · task_id 维度可查              │  │
│  │    binding                       │  │  · 与全局 audit 共享 ring buffer │  │
│  │  · session/device/contract/      │  └──────────────────────────────────┘  │
│  │    tracker 四维绑定              │                                         │
│  └─────────────────────────────────┘  ┌──────────────────────────────────┐  │
│                                        │  Memory Backflow 层               │  │
│                                        │  openclawd_memory_backflow (PR-7) │  │
│                                        │  · 写入 TaskMemory                │  │
│                                        │  · 供 LLM 上下文注入              │  │
│                                        └──────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
           ↑↑↑ AIP v3 over WebSocket ↑↑↑          ↓↓↓ AIP v3 over WebSocket ↓↓↓
┌─────────────────────────────────────────────────────────────────────────────┐
│  Android 侧（ufo-galaxy-android）                                            │
│                                                                             │
│  ┌─────────────────────────────────┐  ┌──────────────────────────────────┐  │
│  │  Transport / Ingress 层          │  │  Offline Durability 层           │  │
│  │  GalaxyConnectionService.kt     │  │  OfflineTaskQueue.kt             │  │
│  │  · WebSocket 连接管理            │  │  · FIFO, max 50, 24h 有效期      │  │
│  │  · 入站消息分发                  │  │  · SharedPreferences 持久化      │  │
│  │  · handoff envelope 接收        │  │  · 断线缓存，重连 drain           │  │
│  │  · result 上报 + memory backflow│  └──────────────────────────────────┘  │
│  └──────────────┬──────────────────┘                                         │
│                 │ 路由到                                                       │
│  ┌──────────────▼──────────────────┐  ┌──────────────────────────────────┐  │
│  │  Runtime Authority / Lifecycle   │  │  Continuity / Recovery 层        │  │
│  │  RuntimeController.kt           │  │  AndroidContinuityIntegration.kt │  │
│  │  · Sole lifecycle authority     │  │  · 5 种 AttachIntentKind          │  │
│  │  · RuntimeState: Idle/Starting/ │  │  · FRESH_ATTACH / CONTINUITY_    │  │
│  │    Active/Failed/LocalOnly      │  │    RESUME / PROCESS_RECREATION_ │  │
│  │  · AttachedRuntimeSession 管理  │  │    REATTACH / TRANSPORT_RECONNECT│  │
│  │  · TakeoverFailure 事件          │  │  · 重用 DelegatedFlowContinuity  │  │
│  │  · setupError typed 分类         │  │    Record（持久化）              │  │
│  └──────────────┬──────────────────┘  └──────────────────────────────────┘  │
│                 │                                                              │
│  ┌──────────────▼──────────────────┐  ┌──────────────────────────────────┐  │
│  │  Delegated Work Receipt Gate     │  │  Capability / Readiness Gate 层  │  │
│  │  DelegatedRuntimeReceiver.kt    │  │  DelegatedRuntimeReadinessEval   │  │
│  │  · session 必须 ATTACHED        │  │  DelegatedRuntimeAcceptanceEval  │  │
│  │  · 产出 DelegatedActivationRecord│  │  DelegatedRuntimeGovernanceEval  │  │
│  │  · 三种 RejectionOutcome         │  │  DelegatedRuntimeStrategyEval   │  │
│  └──────────────┬──────────────────┘  │  · 四维评估 artifact              │  │
│                 │                      └──────────────────────────────────┘  │
│  ┌──────────────▼──────────────────┐                                         │
│  │  Execution Layer                 │  ┌──────────────────────────────────┐  │
│  │  DelegatedTakeoverExecutor.kt   │  │  Reconciliation Signal 层         │  │
│  │  AutonomousExecutionPipeline.kt │  │  ReconciliationSignal.kt (PR-51) │  │
│  │  AgentRuntimeBridge.kt          │  │  · 7 种 Kind                     │  │
│  │  EdgeExecutor.kt                │  │  · TASK_ACCEPTED / STATUS_UPDATE  │  │
│  └─────────────────────────────────┘  │    / RESULT / CANCELLED / FAILED │  │
│                                        │    / PARTICIPANT_STATE /          │  │
│                                        │    RUNTIME_TRUTH_SNAPSHOT         │  │
│                                        └──────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 核心执行主链路（端到端流程）

完整的一次 delegated task 执行，跨双仓涉及以下阶段：

#### 阶段 1：Readiness check（V2 发送任务前）
- **V2**：`delegated_flow_readiness_gate` 检查 Android 是否 ready（readiness verdict）
- **Android**：`DelegatedRuntimeReadinessEvaluator` 评估本地 readiness 维度（accessibility、overlay、concurrency 等），产出 `DeviceReadinessArtifact`
- **当前状态**：双端评估器已具备，但 Android artifact 自动推送到 V2 gate 的实时触发路径仍待端到端验证

#### 阶段 2：Handoff dispatch（V2 → Android）
- **V2**：通过 `android_runtime_dispatch_binding` 创建四维绑定（session / device / contract / tracker），发送 `HandoffEnvelopeV2` 下行
- **Android**：`GalaxyConnectionService` 接收 envelope，`DelegatedRuntimeReceiver` 检查 session 是否 ATTACHED，通过则产出 `DelegatedActivationRecord`（状态 PENDING）
- **双端调用 lifecycle coordinator**：V2 调用 `on_handoff_dispatched`，Android session phase 进入 `handoff_dispatched`

#### 阶段 3：Takeover negotiation（双向）
- **V2**：发送 `takeover_request` 下行
- **Android**：`DelegatedRuntimeReceiver` + `TakeoverEligibilityAssessor`（device readiness gate）双重检查，产出 `takeover_response`（accepted / rejected）
- **V2**：`gateway/android/handlers/takeover_response.py` 接收（single authoritative entry-point），调用 `lifecycle_coordinator.on_takeover_response()`，session phase 推进到 `takeover_accepted` 或 `terminal_failure`
- **当前状态**：基础路径已通，但 `DelegatedTakeoverExecutor.kt` 完整 takeover executor 实现仍有部分 deferred（代码注释明确）

#### 阶段 4：Active execution（Android 本地）
- **Android**：`DelegatedTakeoverExecutor` / `AutonomousExecutionPipeline` / `AgentRuntimeBridge` 执行任务
- **Android**：通过 `DelegatedExecutionSignal`（PR-16 格式）上报进度，通过 `ReconciliationSignal`（PR-51 格式，7 种 kind）上报状态变化
- **V2**：`handlers/delegated_signal.py` 和 `handlers/reconciliation_signal.py` 接收，全部委托 lifecycle coordinator

#### 阶段 5：Result / terminal（Android → V2）
- **Android**：上报 `handoff_result` 或 `task_result`，触发 `GalaxyConnectionService` 中的 memory backflow
- **V2**：`handlers/handoff_v2_result.py` 接收（单一权威入站），`android_handoff_v2_response_ingress` 相关 Future 解析，触发 callback，更新 tracking，调用 audit
- **V2**：`android_participant_truth_ingress` 对 terminal event 进行 canonical 对账，写入 ReplayFoundation
- **V2**：`openclawd_memory_backflow` 写入 TaskMemory

#### 阶段 6：Continuity / recovery（断线/重连场景）
- **Android**：`AndroidContinuityIntegration` 评估 attach intent（FRESH / RESUME / PROCESS_RECREATION / TRANSPORT_RECONNECT），`DelegatedFlowContinuityRecord` 持久化恢复上下文，`OfflineTaskQueue` 缓存断线期间的 result
- **V2**：`flow_continuity_coordinator` 产出 `ContinuityDecision`（new_attachment / continuity_resume / reject_stale / dedupe / preserve_partial），驱动 re-dispatch 或状态对齐

---

## 四、系统当前完成度

### 4.1 第一层：基础执行能力（✅ 已成型，可信赖）

| 能力 | 完成状态 | 代码依据 |
|------|---------|---------|
| AIP v3 wire protocol 双端对齐 | ✅ 已成型 | V2: `galaxy_gateway/android/models.py` + Android: `agent/TakeoverEnvelope.kt`（17KB）均实现完整 wire 类型 |
| WebSocket 连接 + 重连 + 心跳 | ✅ 已成型 | Android: `GalaxyConnectionService.kt`（125KB）包含完整 WS 生命周期；V2: `galaxy_gateway/android/bridge.py` |
| 设备注册 + posture 声明 | ✅ 已成型 | Android: `GalaxyConnectionService` 含 registration 逻辑；V2: `handlers/registration.py` |
| 基础任务执行（task_submit → task_result） | ✅ 已成型 | Android: `AgentRuntimeBridge.kt`（27KB），`EdgeExecutor.kt`（16KB）；V2: `handlers/task_submit.py`, `handlers/task_lifecycle.py` |
| Goal 执行（goal_execution → goal_execution_result） | ✅ 已成型 | Android: `GoalExecutionPipeline.kt`（2.5KB），`LocalGoalExecutor.kt`（4.4KB）；V2: `handlers/goal_execution.py` |
| 离线任务队列 | ✅ 已成型 | Android: `OfflineTaskQueue.kt`：50 条 FIFO，SharedPreferences 持久化，24h 有效期，drop-oldest 策略，已实现完整 |

### 4.2 第二层：Delegated canonical path 骨架（✅ 已成型，结构完整）

| 能力 | 完成状态 | 代码依据 |
|------|---------|---------|
| Handoff EnvelopeV2 双端实现 | ✅ 已成型 | Android: `HandoffEnvelopeV2.kt`（11KB）；V2: `handlers/handoff_v2_result.py` + `android_handoff_v2_response_ingress.py` |
| Delegated execution signal（PR-16 格式） | ✅ 已成型 | Android: `runtime/DelegatedExecutionSignal.kt`；V2: `android_delegated_signal_ingress.py` + `handlers/delegated_signal.py` |
| ReconciliationSignal model（PR-51） | ✅ 已成型 | Android: `ReconciliationSignal.kt`（7 种 Kind，wireValue 常量）；V2: `handlers/reconciliation_signal.py` |
| Attached session registry | ✅ 已成型 | V2: `core/attached_runtime_session_registry.py`；Android: `RuntimeController.attachedSession: StateFlow<AttachedRuntimeSession?>` |
| Session state machine（9 阶段） | ✅ 已成型 | V2: `android_participant_session_state.py`（PR-11-V2）：`pre_dispatch` → `terminal_*` 完整状态机，signal-driven，thread-safe |
| Dispatch binding 记录（PR-11） | ✅ 已成型 | V2: `android_runtime_dispatch_binding.py`：session/device/contract/tracker 四维绑定，128 条 ring buffer |
| Lifecycle coordinator facade（PR-11-V2） | ✅ 已成型 | V2: `android_delegated_runtime_lifecycle_coordinator.py`：5 个 `on_*` 方法单一 facade，所有 handler 委托至此 |
| Continuity coordinator（7 种场景） | ✅ 已成型 | V2: `flow_continuity_coordinator.py`（PR-3）；Android: `AndroidContinuityIntegration.kt`（PR-3）双端对齐 |
| Delegated work receipt gate | ✅ 已成型 | Android: `DelegatedRuntimeReceiver.kt`：session ATTACHED 检查 + `DelegatedActivationRecord` 产出，3 种 rejection reason |
| Result convergence（并行聚合 + duplicate 抑制） | ✅ 已成型 | V2: `core/flow_aware_result_convergence.py`；Android: `AndroidFlowAwareResultConvergenceParticipant.kt` |
| Compat/legacy blocking gate | ✅ 已成型 | V2: `core/compat_legacy_path_blocking_canonicalization.py`（PR-8）；Android: `AndroidCompatLegacyBlockingParticipant.kt` |
| Truth reconciliation ingress（PR-4V2） | ✅ 已成型 | V2: `android_participant_truth_ingress.py`：7 种 TruthKind，authority boundary 明确（V2 is canonical, Android is device-local） |
| Unified audit layer（PR-10-V2） | ✅ 已成型 | V2: `android_delegated_runtime_audit.py`：6 种事件类型，512 条 ring buffer，`by task_id` 可查 |
| Memory backflow（PR-7） | ✅ 已成型 | V2: `openclawd_memory_backflow.py`；Android: `GalaxyConnectionService` 中明确 wired |

### 4.3 第三层：Readiness/Governance 信号流（⚠️ 骨架完整，信号链路待 E2E 验证）

| 能力 | 完成状态 | 代码依据 | 待验证内容 |
|------|---------|---------|---------|
| V2 readiness gate 框架 | ✅ 框架完整 | `core/delegated_flow_readiness_gate.py`（PR-9V2）：6 种 verdict | Android artifact 如何实时进入 V2 gate 的触发路径待验证 |
| V2 acceptance gate 框架 | ✅ 框架完整 | `core/delegated_flow_acceptance_gate.py`（PR-10V2）：graduation verdict | 同上 |
| V2 post-graduation governance 框架 | ✅ 框架完整 | `core/delegated_flow_post_graduation_governance.py`（PR-11V2）：5 种 violation/compliant | 框架已在，但自动治理触发链路未接入 CI/release |
| Android 四维评估器 | ✅ 评估器完整 | Android: `DelegatedRuntime{Readiness,Acceptance,Governance,Strategy}Evaluator.kt`：四个评估器完整，artifact 结构清晰 | Evaluator artifact 向 V2 gate 的自动推送触发时机待端到端验证 |
| ReconciliationSignal 发送触发器 | ⚠️ 模型完整 | Android: `ReconciliationSignal.kt`（PR-51）定义完整；`INTEGRATION_RUNTIME_CONTROLLER` 常量指向 evaluator 通过 "reconciliation signal channel" 转发 | `GalaxyConnectionService` 中各 evaluator 事件到 `sendReconciliationSignal()` 的调用链待 E2E 验证 |

### 4.4 第四层：Default-on 可信运行（❌ 尚未完成）

| 能力 | 完成状态 | 说明 |
|------|---------|------|
| Legacy path 默认关闭 | ❌ 未完成 | Compat gate 已存在（双端），但 legacy path 仍在默认运行路径中，default authoritative path 尚未完全单一化 |
| Readiness verdict 接入 CI/release pipeline | ❌ 未完成 | Readiness verdict 框架已在，但尚未进入自动发布阻断链 |
| Governance verdict 自动 rollback | ❌ 未完成 | Rollback 判定框架存在，但尚未形成自动触发闭环 |
| Takeover executor 完整实现 | ⚠️ 基础路径接通 | `DelegatedTakeoverExecutor.kt` 已有协议路径接通，但代码注释明确 "full takeover executor deferred"（部分实现仍为骨架） |
| E2E 联调测试 | ❌ 未完成 | 双端信号链路的端到端自动化测试未见于仓库 |
| 自动治理接入 | ❌ 未完成 | Governance/strategy 框架已在，但治理决策未自动接入发布或 rollback 流程 |

---

## 五、系统结构性成果

### 5.1 Authority boundary 已清晰

从代码文件级别可以验证，V2 已确立了清晰的 authority boundary：

- **V2 是 canonical 编排权威**：所有 Android 上行信号都在 V2 侧通过 `android_participant_truth_ingress.py` 进行 canonical 对账，当 V2 已处于 terminal state 时，Android 的 task_phase 更新会被拒绝（V2 wins）。
- **Android 是 device-local 执行权威**：Android 的 `RuntimeController` 是 Android 侧唯一生命周期权威，不允许其他组件直接调用 WS connect/disconnect 或修改 `crossDeviceEnabled`。
- **Handoff/takeover 协商有明确边界**：`DelegatedRuntimeReceiver` 明确要求 `AttachedRuntimeSession.State.ATTACHED`，确保只有在合法 session 存在时才接受 delegated work。

### 5.2 Authoritative ingress 已建立

每种上行消息类型都有且只有一个 handler（`galaxy_gateway/android/handlers/`），且每个 handler 都是 "single authoritative entry-point"（文档字符串明确写明）：

- `takeover_response.py`：takeover_response 的唯一 handler
- `reconciliation_signal.py`：reconciliation_signal 的唯一 handler  
- `delegated_signal.py`：delegated_execution_signal 的唯一 handler
- `handoff_v2_result.py`：handoff_ack / handoff_result / handoff_failure 的唯一 handler

这解决了之前各 handler 分别导入多个模块、ordering 可能发散的问题。

### 5.3 Session/lifecycle 已收敛

V2 侧的 `android_participant_session_state.py` 提供了 9 阶段的完整会话状态机（`pre_dispatch` → `handoff_dispatched` → `takeover_pending` → `takeover_accepted` → `execution` → `reconciling` → `terminal_success/failure/cancelled`），signal-driven，phase-monotonic，thread-safe。

此前这些状态分散在 tracker、binding、truth outcome 等多个 ring buffer 中，现在有了统一的 session-level state machine。

### 5.4 Android participant 身份已成型

Android 不再是普通 WS 客户端，而是有正式 participant 身份的运行时参与方：

- `AttachedRuntimeSession`（而非单纯 WS 连接）代表 Android 的参与资格
- `DelegatedActivationRecord` 绑定每次 delegated work 的激活状态
- `ReconciliationSignal` 提供 Android 向 V2 主动上报状态的正式通道
- `DelegatedFlowContinuityRecord` 保证 Android 侧跨进程重启的 continuity 持久性

### 5.5 双端 continuity 语义已对齐

V2 的 `flow_continuity_coordinator.py` 和 Android 的 `AndroidContinuityIntegration.kt` 使用相同的 vocabulary（fresh_attach / continuity_resume / process_recreation_reattach / transport_reconnect / receiver_pipeline_rebind），形成了双端对齐的 continuity 语义。

### 5.6 统一审计面已建立

`android_delegated_runtime_audit.py`（PR-10-V2）提供了对 Android delegated runtime 全链路事件的统一 audit 层，6 种事件类型共享同一 ring buffer，支持按 task_id 查询完整审计时间线。

---

## 六、系统结构性风险

### 6.1 【最关键】ReconciliationSignal 实时推送路径尚未端到端验证

**问题**：Android 四维评估器的 artifact（`DeviceReadinessArtifact` 等）通过 `ReconciliationSignal.Kind.PARTICIPANT_STATE` 通道转发到 V2 的说法目前只有注释和常量（`INTEGRATION_RUNTIME_CONTROLLER`），实际 `GalaxyConnectionService` 中各 evaluator 事件触发 `sendReconciliationSignal()` 的调用路径尚无 E2E 验证。

**影响**：V2 gate 依赖 Android 评估器 artifact 作为 readiness 输入，如果这条信号链路不通，V2 无法做出准确的 readiness verdict，整个发布治理框架的输入层就是空的。

**风险等级**：🔴 高。这是 readiness/governance 信号流打通的核心依赖。

### 6.2 Legacy path 尚未默认关闭

**问题**：Compat gate 在双端均已建立（`AndroidCompatLegacyBlockingParticipant.kt` + `core/compat_legacy_path_blocking_canonicalization.py`），但 legacy path 本身仍在运行，默认的 authoritative path 还未完全单一化。

**影响**：可能出现 legacy 和 canonical 两条路径同时处理同一任务的情况，导致状态不一致和 audit trail 分叉。

**风险等级**：🔴 高。这是 default-on 可信运行的直接阻塞项。

### 6.3 Takeover executor 完整实现 deferred

**问题**：`DelegatedTakeoverExecutor.kt` 的协议路径已接通（TakeoverRequestEnvelope 接收、TAKEOVER_RESPONSE 发送、FAILED/TIMEOUT/CANCELLED outcome 处理），但代码明确注明 "full takeover executor deferred"，意味着在某些执行路径上仍是骨架。

**影响**：takeover 是 delegated execution 的核心路径之一；如果 executor 实现不完整，takeover 场景的实际执行可靠性存疑。

**风险等级**：🟠 中-高。

### 6.4 Governance 与 CI/release pipeline 未接入

**问题**：V2 侧 readiness gate / acceptance gate / post-graduation governance 框架均已具备，但这些 verdict 尚未接入任何 CI/CD 或 release pipeline 的自动阻断逻辑。

**影响**：系统可能在 governance verdict 为 "violation" 的情况下继续发布和运行，治理框架形同虚设。

**风险等级**：🟠 中-高。这是"治理实际接入"的关键缺口。

### 6.5 E2E 联调测试覆盖不足

**问题**：两个仓库均有大量单元测试和模块级测试，但针对双仓信号链路的端到端集成测试（如 handoff → takeover → execution → reconciliation → terminal 完整流程）在仓库中未见完整。

**影响**：主链路的关键路径在集成层面只有局部验证，断层风险不易发现。

**风险等级**：🟠 中-高。

### 6.6 `registrationError` 兼容层仍有 active observer 风险

**问题**：`RuntimeController.kt` 中 `registrationError`（String flow）已被标记 `@Deprecated`，并明确说明是 "HIGH_RISK_ACTIVE compatibility surface"。`CompatibilitySurfaceRetirementRegistry` 已记录，但迁移到 `setupError`（typed `CrossDeviceSetupError`）是否完成仍需核查。

**影响**：如果有模块仍在观察 deprecated `registrationError`，设备分类错误恢复行为可能不一致。

**风险等级**：🟡 中。

---

## 七、与前版审查（2026-04-24）的关键差异

前版联合审查（`docs/joint_system_review/05_maturity_assessment.md`，2026-04-24）已识别以下关键缺口。本次审查对这些缺口的当前状态做出更新：

| 前版识别的缺口 | 前版状态 | 本次更新 |
|-------------|---------|---------|
| ReconciliationSignal AIP wire 层缺失 | 最关键缺口 | **模型已建立**：`ReconciliationSignal.kt`（PR-51）已在 Android 侧，V2 侧 `handlers/reconciliation_signal.py` 已在。但 GalaxyConnectionService 中 evaluator 到 sendReconciliationSignal 的触发链仍需端到端验证 |
| AipModels.kt 无 ReconciliationSignal 类型 | 已识别 | 需要直接检查当前 `AipModels.kt` 确认是否已补全 |
| V2 handler 缺失 | 已修复 | `galaxy_gateway/android/handlers/reconciliation_signal.py` 已存在且为 single authoritative entry-point |
| Lifecycle coordinator facade 缺失 | 已修复 | `core/android_delegated_runtime_lifecycle_coordinator.py`（PR-11-V2）已提供完整 facade，所有 5 种 `on_*` 方法 |
| Session state machine 缺失 | 已修复 | `core/android_participant_session_state.py`（PR-11-V2）已提供完整 9 阶段状态机 |

---

## 八、接下来应该进入什么阶段

基于当前代码真实状态，系统已经完成了"canonical path 骨架建设"和"PR 级模块对齐"阶段，下一步应进入：

### 阶段 8.1：ReconciliationSignal 端到端联调验证（最优先）

**目标**：验证 Android evaluator artifact → ReconciliationSignal.PARTICIPANT_STATE → V2 gateway handler → lifecycle coordinator → readiness gate 的完整信号链路

**具体任务**：
1. 在 `GalaxyConnectionService.kt` 中明确 evaluator 事件触发 `sendReconciliationSignal()` 的调用点
2. 写端到端测试验证：evaluator artifact change → signal 发送 → V2 handler 接收 → gate verdict 更新
3. 补全 `AipModels.kt` 中 `ReconciliationSignal` 对应的 wire message type（如未补全）

### 阶段 8.2：Legacy path 切换（high priority）

**目标**：关闭 legacy path，让 canonical path 成为默认且唯一的运行路径

**具体任务**：
1. 审查 `AndroidCompatLegacyBlockingParticipant.kt` gate 是否已在所有 legacy entry point 接入
2. 在 V2 侧 `compat_legacy_path_blocking_canonicalization.py` 中明确 legacy path 的 "kill switch" 机制
3. 激活 blocking，跑完整流程验证 canonical path 接管

### 阶段 8.3：Takeover executor 完整实现收口（medium priority）

**目标**：完成 `DelegatedTakeoverExecutor.kt` 的 deferred 部分，使 takeover scenario 有完整执行语义

**具体任务**：
1. 明确 "full takeover executor deferred to PR-5" 中哪些能力仍待实现
2. 实现并测试 takeover 完整执行路径（包括 FAILED / TIMEOUT / WS_DISCONNECT fallback）

### 阶段 8.4：Governance 接入 CI/release（收口前必做）

**目标**：让 readiness verdict / governance verdict 真正影响发布决策

**具体任务**：
1. 在 CI pipeline 中接入 readiness gate verdict 检查
2. 接入 governance violation → alert / block release 逻辑
3. 建立 release checklist，requirement：readiness = READY_TO_DISPATCH，governance = COMPLIANT

### 阶段 8.5：E2E 联调测试矩阵（与以上并行）

**目标**：建立覆盖主链路的 E2E 测试矩阵

**建议覆盖的测试场景**：
- 正常 handoff → execution → result → memory backflow 完整流程
- Takeover accepted → execution → reconciliation signal → terminal
- Takeover rejected → fallback 路径
- WS 断线 → OfflineTaskQueue 缓存 → 重连 → drain → result 到达
- Process recreation → AndroidContinuityIntegration → PROCESS_RECREATION_REATTACH → context rehydration

---

## 九、审查结论摘要

### 核心成就（5 项最关键）

1. **Authority boundary 已清晰**：V2 = canonical orchestration authority；Android = device-local execution authority。这是双仓系统稳定运行的基础。
2. **Transport ingress 已单一化**：16 种 Android 上行消息类型均有 single authoritative entry-point，统一委托 lifecycle coordinator。
3. **Session lifecycle state machine 已建立**：9 阶段 session state machine（V2 侧 PR-11-V2），signal-driven，phase-monotonic，thread-safe。
4. **Continuity 语义已双端对齐**：V2 和 Android 使用相同 vocabulary，fresh attach / continuity resume / process recreation 等 5 种场景均有对应实现。
5. **统一 audit 面已建立**：6 种事件类型的统一 audit layer，任务维度可查，与全局 audit ring 共享。

### 最关键风险（3 项最需要解决）

1. **ReconciliationSignal 实时推送路径**：评估器 → signal → V2 gate 的 E2E 信号链路尚未端到端验证，这是发布治理框架的输入基础。
2. **Legacy path 尚未默认关闭**：canonical path 骨架已建，但 legacy 仍并存，需完成 kill switch。
3. **Takeover executor 完整实现**：deferred 部分仍待完成，takeover 作为 delegated execution 的核心路径不能只有骨架。

### 当前阶段判断

> **这套系统当前处于"canonical path 骨架收敛完成"阶段，正在过渡到"信号流端到端打通 + legacy 切换 + 治理接入"阶段。**  
>
> 已经不是基础骨架建设期，也还不是 default-on 可信发布期。  
> 最近的里程碑是 PR-11-V2（lifecycle coordinator facade + session state machine），这个 PR 把双端协作的结构性基础做到了 "可以继续在上面建 E2E 验证和治理接入" 的程度。  
>
> 下一个关键里程碑是：**ReconciliationSignal 信号链路 E2E 联调验证通过 + legacy path kill switch 激活**。

---

*本文档基于 2026-04-25 快照的真实代码状态，不依赖未合并文档。*  
*配套仓库：`DannyFish-11/ufo-galaxy-android`（同步参考，无单独 PR）。*
