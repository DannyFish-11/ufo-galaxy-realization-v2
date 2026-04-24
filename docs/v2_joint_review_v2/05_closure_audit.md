# 真实闭环 / 半闭环 / 伪闭环 / 断层清单

> **分类定义**：
> - **真实闭环**：有入口、有传输、有处理、有回流、有状态更新或 verdict 落点，调用链路连续。
> - **半闭环**：链路接通到某层，但关键中间层缺失，无法完整回流或更新状态。
> - **伪闭环**：surface/evaluator/artifact/model 已存在，但真实调用闭环并未形成（评估器产出 artifact，但 artifact 没有通过真实 wire 进入消费层）。
> - **断层**：缺失 protocol message type、handler、route binding、adapter 等关键部件，导致链路中断。

---

## 一、真实闭环（✅）

### 1. AIP v3 基础任务传输闭环
**证据链**：
- `galaxy_gateway/protocol/aip_v3.py` MessageType 双端对齐（V2 Python + Android Kotlin）
- `galaxy_gateway/android_bridge.py` 注册了所有基础消息类型的 handler
- `protocol/AipModels.kt` 与 V2 MessageType 值精确对应

**链路完整性**：
- 入口：V2 发 task_assign / goal_execution
- 传输：WebSocket（GalaxyWebSocketClient）
- 处理：GalaxyConnectionService handler 链
- 回流：task_result / goal_execution_result
- 状态更新：DelegatedExecutionTrackingRuntime 更新追踪记录

**结论**：✅ 真实闭环

---

### 2. delegated_execution_signal 闭环（PR-16）
**证据链**：
- Android 侧：`runtime/DelegatedExecutionSignal.kt` + `DelegatedExecutionSignalSink.kt`
- AIP 消息类型：`AipModels.MsgType.DELEGATED_EXECUTION_SIGNAL`（Android）= `MessageType.DELEGATED_EXECUTION_SIGNAL`（V2）
- V2 handler 注册：`android_bridge.py` 第 654 行：`self._message_handlers[MessageType.DELEGATED_EXECUTION_SIGNAL] = _wrap(handle_delegated_execution_signal)`
- V2 ingress：`core/android_delegated_signal_ingress.py` → `core/android_execution_signal_reconciler.py`
- V2 状态更新：`DelegatedExecutionTrackingRuntime.apply(signal)`

**链路完整性**：
- 入口：Android 任务执行事件（ACK/PROGRESS/RESULT/TIMEOUT/CANCELLED）
- 传输：AIP WebSocket message type="delegated_execution_signal"
- 处理：`ingest_delegated_execution_signal()` → `reconcile_android_execution_signal()`
- 状态更新：tracking record 更新 + SourceDispatchOrchestrator.consume_android_behavioral_result()

**结论**：✅ 真实闭环

---

### 3. goal_execution / goal_execution_result 闭环
**证据链**：
- V2 handler：`galaxy_gateway/android/handlers/goal_execution.py`:`handle_goal_execution`
- Android handler：`service/GalaxyConnectionService.kt`:`handleGoalExecution()`
- 回传：`AipModels.MsgType.GOAL_EXECUTION_RESULT` → V2 `handle_goal_execution_result`

**链路完整性**：完整。  
**结论**：✅ 真实闭环

---

### 4. Android 本地 LoopController 执行闭环
**证据链**：
- `loop/LoopController.kt`：完整 plan→execute→observe 循环
- `_status: MutableStateFlow<LoopStatus>`：状态实时更新
- `LoopResult`：规范化结果容器

**链路完整性**：入口（FloatingWindow）→ 处理（LoopController）→ 状态更新（StateFlow）→ 结果（LoopResult），完整。  
**结论**：✅ 真实闭环（纯 Android 端，无需 V2）

---

### 5. Reconnect Recovery 闭环
**证据链**：
- `runtime/RuntimeController.kt`（PR-33）：`ReconnectRecoveryState` + 指数退避重连
- `network/OfflineTaskQueue.kt`：离线队列
- V2：`core/android_v2_continuity_contract.py` 场景 2
- V2 handler：`galaxy_gateway/android/handlers/registration.py`:`handle_device_register`（重连时重新注册）

**结论**：✅ 真实闭环

---

### 6. HandoffEnvelopeV2 下行链路闭环（V2→Android）
**证据链**：
- V2：`galaxy_gateway/android/message_builder.py`:`build_handoff_dispatch_message()`
- Android：`service/GalaxyConnectionService.kt`:`handleHandoffEnvelopeV2()`
- Android MsgType：`AipModels.MsgType.HANDOFF_ENVELOPE_V2`

**注意**：仅下行闭环，上行回传存在断层（见下方"断层"部分）。  
**结论**：✅ 下行真实闭环（上行半闭环）

---

## 二、半闭环（⚠️）

### 7. HandoffEnvelopeV2 上行回传半闭环
**现状**：
- Android 已实现：`GalaxyConnectionService.sendHandoffEnvelopeV2Result()` 发送 `handoff_envelope_v2_result`
- V2 ingress 已实现：`core/android_handoff_v2_response_ingress.py`:`ingest_android_handoff_response()`
- V2 MessageType 枚举缺失：`galaxy_gateway/protocol/aip_v3.py` 中无 `HANDOFF_ENVELOPE_V2_RESULT`
- V2 handler 未注册：`android_bridge.py` 中无对应 handler

**断层位置**：V2 gateway protocol 层（MessageType 枚举）+ gateway handler 注册层。

**等级判断**：⚠️ 半闭环（Android 发送有实现，V2 ingress 处理有实现，中间 gateway routing 断层）

---

### 8. Android participant truth 上报半闭环
**现状**：
- V2 ingress 已实现：`core/android_participant_truth_ingress.py`
- 但没有明确的触发路径（没有 Android 侧发送 participant truth 消息的代码）
- 只有通过 `delegated_execution_signal` 的兼容路径进入 V2（隐式推断而非显式 truth 上报）

**等级判断**：⚠️ 半闭环

---

### 9. Operator surface 观察半闭环
**现状**：
- V2 有：`core/flow_level_operator_surface.py`、`core/operator_override.py`
- V2 Operator 观察的是 V2 维护的 canonical 状态
- 当 ReconciliationSignal wire 断层存在时，V2 canonical 状态可能滞后于 Android 本地事实

**等级判断**：⚠️ 半闭环（operator 可以观察 V2 侧状态，但无法观察 Android 端的实时 reconciliation 状态）

---

## 三、伪闭环（🔶）

### 10. Readiness/Acceptance/Governance/Strategy 四层评估伪闭环
**现状**：
- Android 四层评估器均已完整实现：
  - `runtime/DelegatedRuntimeReadinessEvaluator.kt` → `runtime/DeviceReadinessArtifact.kt`
  - `runtime/DelegatedRuntimeAcceptanceEvaluator.kt` → `runtime/DeviceAcceptanceArtifact.kt`
  - `runtime/DelegatedRuntimePostGraduationGovernanceEvaluator.kt` → `runtime/DeviceGovernanceArtifact.kt`
  - `runtime/DelegatedRuntimeStrategyEvaluator.kt` → `runtime/DeviceStrategyArtifact.kt`
- V2 四层 gate 也均已实现：
  - `core/delegated_flow_readiness_gate.py`
  - `core/delegated_flow_acceptance_gate.py`
  - `core/delegated_flow_post_graduation_governance.py`
  - `core/delegated_flow_program_strategy.py`
- 但没有从 Android evaluator → artifact → wire 传输 → V2 gate 消费 的完整路径

**代码证据**：`AipModels.kt` 中没有 artifact 上报专用的 MsgType；`GalaxyConnectionService` 中没有定期上报四类 artifact 的代码；V2 gate 没有接收 Android artifact 的 ingress 路径（除了推测性的 `participant_truth` 路径）。

**等级判断**：🔶 伪闭环（双端各有 surface，但真实调用闭环未形成）

---

### 11. ReconciliationSignal 评估体系伪闭环
**现状**：
- `runtime/ReconciliationSignal.kt`（PR-51）：7 种 Kind，完整数据结构
- `runtime/RuntimeController.kt`（PR-52）：`_reconciliationSignals: MutableSharedFlow`
- V2 `core/android_participant_truth_ingress.py`：`AndroidParticipantTruthKind` 对应处理
- 但 ReconciliationSignal **没有对应 MsgType**，无法通过 AIP wire 发出

**等级判断**：🔶 伪闭环（数据结构和消费逻辑均存在，但 wire 协议层缺失，导致闭环未形成）

---

### 12. Cross-repo consistency gate 伪闭环
**现状**：
- V2：`core/cross_repo_consistency_gates.py` 有 6 类 consistency 检查（schema_vocabulary、session_family、execution_enum 等）
- Android：`protocol/CrossRepoConsistencyGate.kt` 有对应设计
- 但 consistency gate 是静态检查工具，不是运行时 wire 路径
- 检查结果没有通过 wire 在双仓之间实时同步

**等级判断**：🔶 伪闭环（检查机制存在，但运行时动态对齐未建立）

---

## 四、断层（❌）

### 13. HANDOFF_ENVELOPE_V2_RESULT gateway routing 断层
**断层类型**：protocol message type 缺失 + gateway handler 未注册

**具体位置**：
1. **`galaxy_gateway/protocol/aip_v3.py` MessageType 枚举**：
   ```python
   # 当前只有：
   HANDOFF_DISPATCH = "handoff_dispatch"
   HANDOFF_ACK = "handoff_ack"
   HANDOFF_RESULT = "handoff_result"
   HANDOFF_FAILURE = "handoff_failure"
   # 缺失：HANDOFF_ENVELOPE_V2_RESULT = "handoff_envelope_v2_result"
   ```

2. **`galaxy_gateway/android_bridge.py` handler 注册表**：
   ```python
   # 没有以下条目：
   # self._message_handlers[MessageType.HANDOFF_ENVELOPE_V2_RESULT] = ...
   ```

3. **`galaxy_gateway/android/handlers/` 目录**：没有 `handoff_v2_result.py` handler 文件

**影响**：Android 发来的 `handoff_envelope_v2_result` 消息在 V2 gateway 层被丢弃（"Unknown message type"）；`core/android_handoff_v2_response_ingress.py` 虽然已实现，但永远不会被调用；HandoffEnvelopeV2 结果成功消费后 V2 无法知道，handoff 链路单向。

---

### 14. ReconciliationSignal AIP wire 协议断层
**断层类型**：protocol message type 缺失 + emission 代码缺失

**具体位置**：
1. **`protocol/AipModels.kt` MsgType 枚举**：
   ```kotlin
   // 最后条目为：
   HANDOFF_ENVELOPE_V2_RESULT("handoff_envelope_v2_result");
   // 缺失：RECONCILIATION_SIGNAL("reconciliation_signal") 或等价条目
   ```

2. **`service/GalaxyConnectionService.kt`**：
   ```kotlin
   // 没有消费 RuntimeController.reconciliationSignals 的代码
   // 没有序列化 ReconciliationSignal 并发送 AIP 消息的代码
   ```

**影响**：Android 的 7 种 ReconciliationSignal（TASK_ACCEPTED / TASK_STATUS_UPDATE / TASK_RESULT / TASK_CANCELLED / TASK_FAILED / PARTICIPANT_STATE / RUNTIME_TRUTH_SNAPSHOT）只在 Android 进程内流转，V2 无法接收；V2 的 `delegated_flow_readiness_gate` 等四层 gate 缺少 Android 侧的 participant state signal 输入，只能依赖 `delegated_execution_signal` 的隐式状态推断。

---

## 五、清单汇总

| # | 名称 | 状态 | 断点位置 |
|---|------|------|---------|
| 1 | AIP v3 基础任务传输 | ✅ 真实闭环 | — |
| 2 | delegated_execution_signal | ✅ 真实闭环 | — |
| 3 | goal_execution / result | ✅ 真实闭环 | — |
| 4 | Android 本地 LoopController | ✅ 真实闭环 | — |
| 5 | Reconnect Recovery | ✅ 真实闭环 | — |
| 6 | HandoffEnvelopeV2 下行 | ✅ 真实闭环 | — |
| 7 | HandoffEnvelopeV2 上行回传 | ⚠️ 半闭环 | V2 MessageType 缺失 + handler 未注册 |
| 8 | Android participant truth 上报 | ⚠️ 半闭环 | 无专用触发路径 |
| 9 | Operator surface 观察 | ⚠️ 半闭环 | Android reconciliation 状态不可见 |
| 10 | 四层评估 artifact 上报 | 🔶 伪闭环 | 无 wire 传输路径 |
| 11 | ReconciliationSignal 体系 | 🔶 伪闭环 | 无 MsgType + 无 emission 代码 |
| 12 | Cross-repo consistency gate | 🔶 伪闭环 | 静态检查，无运行时动态对齐 |
| 13 | HANDOFF_ENVELOPE_V2_RESULT routing | ❌ 断层 | V2 MessageType 枚举 + handler 注册缺失 |
| 14 | ReconciliationSignal wire 协议 | ❌ 断层 | AipModels.kt MsgType 缺失 + GCS emission 缺失 |
