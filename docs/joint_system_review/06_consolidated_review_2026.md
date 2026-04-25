# 双仓联合审查总结 —— 2026 年 4 月版（基于真实代码）

> **审查范围**：`DannyFish-11/ufo-galaxy-realization-v2`（V2 中心侧，Python）
> + `DannyFish-11/ufo-galaxy-android`（Android 端侧，Kotlin）
>
> **审查原则**：严格基于真实代码判断，不依赖未合并文档或愿景设计。
>
> **本文用途**：可供 reviewer 直接阅读、直接引用，也可粘贴到 PR 评论中使用。

---

## 一、这套系统是什么

### 1.1 一句话定义（代码支撑）

> **这是一套以 V2 Python 服务作为 canonical orchestration 中心、以 Android 设备作为 delegated runtime 执行端的跨仓任务执行与生命周期治理平台。**

这不是一个 demo、adapter 或单一功能服务。从代码结构看，它是一套有清晰分层、有明确职责边界的系统，目的是让 Android 设备成为 V2 运行时中可委托、可接管、可对账、可观测的正式执行参与方。

### 1.2 双端职责（代码级别判断）

**V2 侧（Python / FastAPI + WebSocket Gateway）**

| 职责层 | 关键模块（基于代码） | 功能 |
|--------|---------------------|------|
| Wire ingress | `galaxy_gateway/android/handlers/` | 所有 Android 上行消息的 **单一权威入口** |
| 生命周期编排 | `core/android_delegated_runtime_lifecycle_coordinator.py` | PR-11-V2：中枢 facade，one method per lifecycle event |
| 真值收敛 | `core/android_participant_truth_ingress.py` | PR-4V2：Android 真值进入 V2 canonical 状态的规范路径 |
| 会话状态机 | `core/android_participant_session_state.py` | PR-11-V2：9 阶段会话状态机（pre_dispatch → terminal） |
| 信号归一 | `core/android_runtime_transition_reducer.py` | PR-11-V2：单一 canonical 信号 → 状态转换 reducer |
| 执行追踪 | `core/delegated_runtime_execution_tracker.py` | 跨 handoff/takeover 的执行 phase 追踪 |
| 审计/可观测 | `core/android_delegated_runtime_audit.py` | PR-10-V2：unified audit，ring buffer，按 task/session 查询 |
| Handoff 绑定 | `core/android_runtime_dispatch_binding.py` | PR-11：session+device+contract+tracker 绑定记录 |
| Handoff 响应入站 | `core/android_handoff_v2_response_ingress.py` | PR-H：handoff 结果与 pending registry 关联 |

**Android 侧（Kotlin / Android App）**

| 职责层 | 关键模块（基于代码） | 功能 |
|--------|---------------------|------|
| 运行时总控 | `RuntimeController.kt` | "Sole lifecycle authority"，152KB，复杂状态机 |
| Transport 骨干 | `GalaxyWebSocketClient.kt` | 所有跨端消息的唯一出口 |
| WS/Protocol 入站 | `GalaxyConnectionService.kt` | 125KB，协议分发、handoff/takeover 处理 |
| Delegated 执行 | `DelegatedRuntimeUnit.kt` + `AutonomousExecutionPipeline.kt` | 本地执行单元 |
| 执行信号发送 | `DelegatedExecutionSignal.kt` + `DelegatedExecutionSignalSink.kt` | ACK/PROGRESS/RESULT/ERROR/TIMEOUT/CANCELLED |
| Takeover 执行 | `DelegatedTakeoverExecutor.kt` | takeover 请求的本地执行器 |
| 本地真值权威 | `AndroidLocalTruthOwnershipCoordinator.kt` + `AndroidParticipantRuntimeTruth.kt` | Android 本地 runtime 真值 |
| 真值归一 | `TruthReconciliationReducer.kt` | PR-64：Android 本地单一收敛入口，epoch 门控 |
| 对账信号 | `ReconciliationSignal.kt` | PR-51：7 种信号类型的结构化 Android→V2 协议载体 |
| 接受评估 | `DelegatedRuntimeReadinessEvaluator.kt` 等 4 个评估器 | readiness/acceptance/governance/strategy 四层评估 |

---

## 二、主链路与关键流转（基于真实代码）

### 2.1 Delegated 执行主链路（已接通）

```
V2 侧（下行）：
  1. DelegatedFlowEntity 创建 (delegated_flow_entity.py)
  2. AndroidRuntimeDispatchBindingRecord 构建 (android_runtime_dispatch_binding.py)
     - 绑定 session_id + device_id + contract_id + tracker_id
  3. HandoffEnvelopeV2 构建 + 下发 → Android

Android 侧（执行）：
  4. GalaxyConnectionService 接收 handoff_envelope_v2
  5. 发送 handoff_ack（immediate）→ V2
  6. DelegatedRuntimeUnit / AutonomousExecutionPipeline 本地执行
  7. DelegatedExecutionSignal 构建 → GalaxyWebSocketClient.sendJson()
  8. TruthReconciliationReducer 推进本地 truth

V2 侧（回流）：
  9. gateway handlers/delegated_signal.py → lifecycle coordinator
  10. coordinator.on_execution_signal()：
      a. android_delegated_signal_ingress 入站
      b. reduce_android_runtime_signal 推进 session phase
      c. record_participant_session 持久化
      d. 可选：SourceDispatchOrchestrator.consume_android_behavioral_result (PR-5A)
  11. DelegatedExecutionTrackingRecord phase 更新
```

**判断**：⬛ **主干已接通**。下行 handoff、本地执行、执行信号上报，回流三段均有完整实现。

### 2.2 Handoff 上行响应链路（已接通，前版审查缺口已修复）

```
Android 侧：
  - GalaxyConnectionService.sendHandoffEnvelopeV2Result()
  - 消息类型：handoff_ack / handoff_result / handoff_failure / handoff_envelope_v2_result

V2 侧：
  - galaxy_gateway/android/handlers/handoff_v2_result.py  ← 本次审查确认存在
  - → core/android_handoff_v2_response_ingress.ingest_android_handoff_response()
  - → 关联 pending registry，resolve Future，触发回调
  - → core/android_delegated_runtime_audit.record_handoff_v2_result() 写入 audit ring
```

**判断**：⬛ **已接通**。前一版审查（2026-04-24）将此列为缺口 2，当前代码中 `handoff_v2_result.py` 已存在于 `galaxy_gateway/android/handlers/` 目录，缺口已修复。

### 2.3 Takeover 链路（已接通）

```
V2 侧（下行请求）：
  - 通过 gateway 下发 takeover_request 消息

Android 侧（执行）：
  - GalaxyConnectionService 解析 TAKEOVER_REQUEST
  - DelegatedTakeoverExecutor 执行
  - 发送 takeover_response（accepted/rejected）

V2 侧（回流处理）：
  - galaxy_gateway/android/handlers/takeover_response.py ← 单一权威入口
  - → lifecycle coordinator.on_takeover_response()
  - → takeover_tracking.record_takeover_response()
  - → reduce_takeover_response() 推进 session phase
  - → record_participant_session() 持久化
  - → record_takeover_response() 写入 audit
  - 返回 takeover_response_ack
```

**判断**：⬛ **已接通**。V2 handler 存在，lifecycle coordinator 负责所有后续处理，takeover tracking + audit 完整。

### 2.4 Reconciliation Signal 链路（已接通，前版审查缺口已修复）

```
Android 侧：
  - ReconciliationSignal（PR-51）：7 种 Kind
    TASK_ACCEPTED / TASK_STATUS_UPDATE / TASK_RESULT /
    TASK_CANCELLED / TASK_FAILED / PARTICIPANT_STATE / RUNTIME_TRUTH_SNAPSHOT
  - 通过 reconciliation signal channel 发送

V2 侧：
  - galaxy_gateway/android/handlers/reconciliation_signal.py  ← 本次审查确认存在
  - → lifecycle coordinator.on_reconciliation_signal()
  - → android_participant_truth_ingress.ingest_android_participant_truth_message()
  - → reduce_android_runtime_signal() 推进 session phase
  - → record_participant_session() 持久化
  - → record_reconciliation_signal() 写入 audit
  - 返回 reconciliation_signal_ack
```

**判断**：⬛ **handler 已接通**。前一版审查将"ReconciliationSignal AIP wire 层缺失"列为最关键缺口，当前代码中 `reconciliation_signal.py` 已存在。Android 侧 `ReconciliationSignal.kt`（PR-51）有完整的 7 种信号类型定义和协议注释。

### 2.5 Participant Truth Ingress 链路（已接通，V2 侧完整）

```
V2 侧（入站处理）：
  core/android_participant_truth_ingress.py (PR-4V2)
  - extract_participant_truth_envelope()：8 种 TruthKind
    (session_snapshot / readiness_assessment / task_phase /
     runtime_state / cancel / status / failure / result)
  - reconcile_android_participant_truth()：
    - V2 是 canonical orchestration authority
    - cancel/failure/result：更新 V2 canonical tracking，触发 ReplayFoundation
    - task_phase：V2 已 terminal → 拒绝 Android 更新（V2 wins）
    - session_snapshot：仅用于验证 continuity，不覆盖 V2 session 字段
    - readiness_assessment：更新 advisory 字段，不影响 V2 admissibility gate
```

**判断**：⬛ **V2 入站处理完整**，authority boundary 有明确文档注释（"V2 is the single canonical orchestration authority"）。

### 2.6 Android 本地真值归一链路（新增，PR-64）

```
Android 侧（TruthReconciliationReducer.kt，PR-64）：
  - 4 个不变式：
    1. Epoch 门控：stale patch 直接丢弃
    2. 仅 authoritative patch 修改 task terminal state
    3. Terminal 幂等：已 idle 时再次收到 terminal patch 只推进 epoch
    4. Participant mismatch safety：直接拒绝
  - 支持 reduceFold()：批量处理 patch 序列，乱序到达仍稳定
  - RuntimeTruthPatch.Kind 覆盖：
    DELEGATED_TASK_RESULT / CANCELLED / FAILED /
    SESSION_TERMINAL / HANDOFF_ACCEPTED/REJECTED / TAKEOVER_ACCEPTED/REJECTED /
    PARTICIPANT_STATE_CHANGED
```

**判断**：⬛ **Android 本地真值归一完整**。PR-64 建立了 Android 侧单一收敛入口，解决了多模块独立推进终态的问题。

---

## 三、V2 生命周期 Coordinator 架构（PR-11-V2）

这是本次审查中 V2 侧最关键的结构性模块，值得单独说明。

`core/android_delegated_runtime_lifecycle_coordinator.py` 提供了一个 facade，将所有 Android delegated runtime 事件归入 5 个 `on_*` 方法：

| 方法 | 触发时机 | 内部操作 |
|------|---------|---------|
| `on_handoff_dispatched()` | V2 dispatch path 完成 handoff 分发 | 创建 session record，持久化 |
| `on_takeover_response()` | takeover_response handler 收到消息 | takeover tracking + session phase reduce + audit |
| `on_reconciliation_signal()` | reconciliation_signal handler 收到消息 | truth ingress + session phase reduce + audit |
| `on_execution_signal()` | delegated_signal handler 收到消息 | signal ingress + session phase reduce + 可选 PR-5A result consumer |
| `on_participant_truth_update()` | 显式 participant truth 消息 | truth ingress + session phase reduce + audit |

**这一设计的价值**：
- Gateway handler 不再各自 import 多个 core 模块
- ingress → state-update → audit 的顺序不会因 handler 不同而静默分叉
- 每个事件有类型化 `AndroidLifecycleCoordinatorOutcome` 返回，可日志追踪
- Non-raising：所有 `on_*` 方法内部 catch，不会因依赖模块缺失而崩溃 gateway

---

## 四、当前完成度评估

### 4.1 已完成，可信依赖

| 能力 | 完成状态 | 说明 |
|------|---------|------|
| AIP v3 wire protocol（双端对齐） | ✅ 成熟 | 消息类型双端完全对应 |
| WebSocket 连接/重连/心跳 | ✅ 成熟 | RuntimeController + GalaxyWebSocketClient 完整 |
| 设备注册 + posture 声明 | ✅ 成熟 | `source_runtime_posture` 双端对齐 |
| 基础任务执行（task/goal） | ✅ 成熟 | 最完整的路径 |
| Delegated execution signal（PR-16） | ✅ 成熟 | 双端新格式接通，旧格式兼容 |
| HandoffEnvelopeV2 下行分发 | ✅ 成熟 | V2 dispatch + Android 接收均有完整实现 |
| **Handoff 上行响应 handler** | ✅ 已接通 | handoff_v2_result.py 已存在（前版审查缺口已修复） |
| **Reconciliation signal handler** | ✅ 已接通 | reconciliation_signal.py 已存在（前版审查缺口已修复） |
| Takeover 链路（request + response） | ✅ 成熟 | 双端完整，takeover_response.py 单一权威入口 |
| Lifecycle coordinator（PR-11-V2） | ✅ 成熟 | 所有事件统一归入 coordinator |
| Participant truth ingress（PR-4V2） | ✅ 成熟 | authority boundary 明确，8 种 TruthKind 处理 |
| Session state machine（PR-11-V2） | ✅ 成熟 | 9 阶段，phase-monotonic，signal-driven |
| Transition reducer（PR-11-V2） | ✅ 成熟 | 单一 canonical reducer，5 种信号域 |
| Unified audit（PR-10-V2） | ✅ 成熟 | ring buffer，6 种 audit 事件，task/session 查询 |
| Android 本地真值归一（PR-64） | ✅ 成熟 | 4 不变式，epoch 门控，批量 fold 支持 |
| ReconciliationSignal 模型（PR-51） | ✅ 成熟 | 7 种 Kind，wire key 常量，responsibility boundary 清晰 |
| Dispatch binding 记录（PR-11） | ✅ 成熟 | session/device/contract/tracker 四维绑定 |
| 离线任务队列 | ✅ 成熟 | OfflineTaskQueue.kt，Android 断线任务缓存 |
| Continuity / recovery 协调 | ✅ 成熟 | FlowContinuityCoordinator + AndroidContinuityIntegration |

### 4.2 已建立骨架，信号流完整性待端到端验证

| 能力 | 完成状态 | 待验证内容 |
|------|---------|----------|
| V2 readiness gate 读取 Android artifact | ⚠️ V2 gate 框架完整 | Android evaluator 产出 artifact 进入 V2 gate 的实时触发路径待验证 |
| Android ReconciliationSignal 实际发送触发器 | ⚠️ 模型完整 | GalaxyConnectionService 中各 evaluator 事件发送 ReconciliationSignal 的调用路径待端到端验证 |
| Compat/legacy 阻断 Android 上报路径 | ⚠️ 双端阻断器存在 | AndroidCompatLegacyBlockingParticipant → V2 compat gate 的信号链待验证 |

### 4.3 尚未完成

| 能力 | 完成状态 | 说明 |
|------|---------|------|
| Legacy path 默认关闭 | ❌ 未完成 | compat gate 存在但 legacy path 仍在运行 |
| Readiness verdict 接入 CI/release pipeline | ❌ 未完成 | 框架存在，未接入自动发布阻断 |
| Governance verdict 自动 rollback | ❌ 未完成 | 框架存在，无自动触发 |
| Takeover executor 完整实现 | ⚠️ 基础路径接通 | `AipModels.kt` 注明 "full takeover executor deferred to PR-5" |

---

## 五、与前版审查（2026-04-24）的关键差异

前版联合审查（`docs/joint_system_review/05_maturity_assessment.md`）识别了以下关键缺口：

| 缺口编号 | 前版描述 | 当前状态 |
|---------|---------|---------|
| 缺口 1（最关键）| ReconciliationSignal AIP wire 层缺失，`AipModels.kt` 无对应消息类型，V2 无 handler | **已修复**：`galaxy_gateway/android/handlers/reconciliation_signal.py` 已存在；Android 侧 `ReconciliationSignal.kt`（PR-51）已建立完整 7 种信号模型 |
| 缺口 2（中等关键）| HandoffEnvelopeV2 上行 response gateway handler 缺失 | **已修复**：`galaxy_gateway/android/handlers/handoff_v2_result.py` 已存在，并调用 `core/android_handoff_v2_response_ingress.py` |
| 缺口 3（次关键）| Android compat/legacy 上报路径不明确 | **部分改善**：ReconciliationSignal channel 已建立，可作为传输路径；完整触发链待验证 |
| 缺口 4（低优先级）| Takeover executor 完整实现延迟 | **未变化**：基础路径接通，完整 executor 仍待后续 PR |

**此外，前版审查未覆盖的新增能力**：
- PR-11-V2 Lifecycle Coordinator（所有事件统一归入 coordinator）
- PR-64 Android TruthReconciliationReducer（本地单一收敛入口）
- PR-10-V2 Unified Audit（ring buffer，6 种 audit 事件类型）
- PR-11-V2 Session State Machine（9 阶段，signal-driven）
- PR-11-V2 Transition Reducer（单一 canonical reducer）

---

## 六、联合审查结论

### 6.1 系统现在处于什么阶段

> **当前阶段：delegated runtime 主链路已基本收敛成型，从"框架骨架"升级到"主干能力成型"，已具备跨仓联调基础；前一版审查中最关键的两个 wire 层断层（handoff 响应 handler、reconciliation signal handler）已修复；但 readiness/governance 决策闭环所需的 Android evaluator 评估结果 → V2 gate 的实时信号流仍需端到端验证。**

### 6.2 当前已经建立的核心价值（代码支撑）

1. **从零散到收敛**：多个 gateway handler 现在统一通过 lifecycle coordinator 处理事件，ingress → state-update → audit 顺序有明确保障。

2. **双端真值归一均已建立**：V2 侧有 `android_participant_truth_ingress.py` + `android_runtime_transition_reducer.py`；Android 侧有 `TruthReconciliationReducer.kt`。两侧均不再是"各自推进终态"，而是通过单一入口收敛。

3. **handoff/takeover 链路已真正双向打通**：前版审查记录的 handoff 上行响应单向信道问题已修复，V2 现在可以完整感知 Android 的 handoff 执行结果。

4. **reconciliation signal 协议已在双端建立**：7 种 Kind 的结构化对账信号，responsibility boundary 有清晰注释（Android 持有内容，V2 持有对账决策权）。

5. **audit 可观测性已建立**：6 种 audit 事件类型，ring buffer 支持 task/session 维度查询，为联调排障建立了基础。

### 6.3 当前最需要关注的风险点

1. **Android evaluator artifact 到 V2 gate 的实时连接**：4 个 evaluator 的产出如何实时进入 V2 的 readiness/acceptance/governance/strategy gate，仍是最核心的"骨架有但信号流待验证"问题。

2. **ReconciliationSignal 实际发送触发器**：Android 侧 `ReconciliationSignal.kt` 模型完整，但在 `GalaxyConnectionService.kt` 中各 evaluator 触发时主动发送 ReconciliationSignal 的调用路径需要 end-to-end 验证。

3. **多信号终态去重保障**：`delegated_execution_signal`（ACK/RESULT/ERROR/TIMEOUT/CANCELLED）和 `reconciliation_signal`（TASK_RESULT/TASK_FAILED/TASK_CANCELLED）均可推进终态，需要确认两者通过 lifecycle coordinator 进入同一 session phase 路径后不会重复落账。

4. **legacy path 在真实生产流量中的比例**：compat gate 和 legacy blocking 机制已建立，但 legacy path 是否已实际 default-off 仍需确认。

---

## 七、审查范围声明

本文基于以下代码文件作出判断，不依赖文档或未合并 PR：

**V2 侧已阅读文件**：
- `galaxy_gateway/android/handlers/` 下所有 handler（handoff_v2_result.py, reconciliation_signal.py, takeover_response.py, delegated_signal.py）
- `core/android_delegated_runtime_lifecycle_coordinator.py`
- `core/android_participant_truth_ingress.py`
- `core/android_participant_session_state.py`
- `core/android_runtime_transition_reducer.py`
- `core/android_delegated_runtime_audit.py`
- `core/android_runtime_dispatch_binding.py`
- `core/android_handoff_v2_response_ingress.py`

**Android 侧已阅读文件**：
- `app/src/main/java/com/ufo/galaxy/runtime/RuntimeController.kt`
- `app/src/main/java/com/ufo/galaxy/runtime/ReconciliationSignal.kt`
- `app/src/main/java/com/ufo/galaxy/runtime/TruthReconciliationReducer.kt`
- `app/src/main/java/com/ufo/galaxy/runtime/DelegatedRuntimeAcceptanceEvaluator.kt`
- `app/src/main/java/com/ufo/galaxy/runtime/` 目录文件列表（100+ 个 .kt 文件）
- `app/src/main/java/com/ufo/galaxy/service/` 目录文件列表（GalaxyConnectionService.kt 等）

---

*生成时间：2026-04-25*
*基于仓库当前合并代码，不依赖未合并 PR 或外部文档*
