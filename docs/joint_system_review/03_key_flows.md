# 主链路与关键流转审查

> 审查依据：逐模块代码阅读，梳理各链路的实际代码落点。
> 重点区分：哪些链路代码完整，哪些链路只有 artifact/evaluator surface，哪些链路依赖另一仓库 signal 才完整。

---

## 1. Delegated Flow 主执行链

### 链路描述
V2 发起 delegated task → Android 接受并执行 → 信号回流 V2 → V2 推进 canonical phase。

### 代码落点

```
V2 侧：
  1. DelegatedFlowEntity 创建 (delegated_flow_entity.py)
  2. DelegatedRuntimeHandoffContract 构建 (delegated_runtime_handoff_contract.py)
  3. AndroidRuntimeDispatchBindingRecord 创建 (android_runtime_dispatch_binding.py)
     ↓ 将 session_id + device_id + contract_id + tracker_id 绑定到一条记录
  4. HandoffEnvelopeV2 构建 (contracts/handoff_envelope_v2.py)
  5. gateway 发送 handoff_dispatch 消息 → Android

Android 侧：
  6. GalaxyWebSocketClient 接收 handoff_envelope_v2 消息
  7. DelegatedRuntimeReceiver 接收 dispatched 任务
  8. DelegatedHandoffContract 验证 (HandoffContractValidator.kt)
  9. DelegatedRuntimeUnit 创建执行单元
  10. AutonomousExecutionPipeline 执行本地任务
  11. DelegatedExecutionSignal 构建（ACK/PROGRESS/RESULT）
  12. GalaxyWebSocketClient.sendJson() 上报 delegated_execution_signal

V2 侧（回流）：
  13. android_delegated_signal_ingress.ingest_delegated_execution_signal() 接收
  14. android_execution_signal_reconciler.reconcile_android_execution_signal() 对账
  15. DelegatedExecutionTrackingRecord phase 推进
  16. DelegatedFlowEntity phase 更新
```

### 链路完整性判断

**✅ 已在代码中完整（下行链路：V2 → Android）**：
- V2 侧：模块 1-5 均有完整实现
- Android 侧：模块 6-12 均有完整实现；`AipModels.kt` 对 `handoff_envelope_v2` 状态注明 "pr-h — promoted; dedicated stateful handler in GalaxyConnectionService"

**❌ 已确认缺口（上行链路：Android → V2 handoff 响应）**：
通过检查 `galaxy_gateway/android/handlers/` 目录，确认其中**没有** `handoff_ack`、`handoff_result`、`handoff_failure` 的专用 handler 文件。虽然 V2 侧有 `core/android_handoff_v2_response_ingress.py` 处理模块，但它尚未被 gateway 路由层挂接。Android 发出的 `handoff_envelope_v2_result` 消息（在 `AipModels.kt` 中定义）在 V2 gateway 中找不到对应的路由 handler。这是一个**已确认的断层**：
- V2 的 `android_handoff_v2_response_ingress.py` 入站处理器存在但未被 gateway 调用
- `galaxy_gateway/websocket_handler.py` 的 dispatch table 仅覆盖 `DEVICE_REGISTER`、`DEVICE_HEARTBEAT`、`TASK_RESULT`、`COMMAND_RESULT`、`COMMAND`、`DEVICE_STATUS`、`WAKE_EVENT` 七种类型，其他类型由 `android_bridge.py` 的分发器处理
- `android_bridge.py` 中导入了 `handle_delegated_execution_signal` 但未见 `handle_handoff_response`

---

## 2. Truth Ownership / Alignment 链路

### 链路描述
Android 本地执行真值 → 上报 V2 → V2 做 canonical reconciliation → canonical flow truth 更新。

### 代码落点

```
Android 侧（产生真值）：
  1. AutonomousExecutionPipeline / EdgeExecutor 执行产生真值
  2. AndroidLocalTruthOwnershipCoordinator 持有本地权威
  3. LocalTruthEmitDecision.kt 决策：是否触发上报
  4. AndroidParticipantRuntimeTruth.kt 构建 snapshot
  5. 通过 GalaxyWebSocketClient 上报（session_snapshot / readiness_assessment / task_phase 等消息）

V2 侧（接收并对账）：
  6. android_participant_truth_ingress.extract_participant_truth_envelope() 提取信封
  7. android_participant_truth_ingress.reconcile_android_participant_truth() 对账
     → 解析 AndroidParticipantTruthKind（8种：session_snapshot/readiness/task_phase/runtime_state/cancel/status/failure/result）
     → 查找 DelegatedExecutionTrackingRuntime 和 AttachedSessionRegistry
     → 更新 canonical 状态，触发 ReplayFoundation 终态事件
  8. FlowLevelTruthOwnership 持有 canonical flow truth
```

### 链路完整性判断

**✅ V2 侧入站处理完整**：
- V2 `android_participant_truth_ingress.py` 中 8 种 truth kind 处理逻辑完整
- V2 gateway `android_bridge.py` 中的 `handle_response` → 触发 `reconcile_inbound_message` → 路由至 `android_participant_truth_ingress`

**✅ Android 侧状态上报机制已建立**：
- `ReconciliationSignal.kt`（PR-51）定义了 Android→V2 的 7 种 signal kind，包括 `PARTICIPANT_STATE`（状态变化，含 readiness）和 `RUNTIME_TRUTH_SNAPSHOT`（完整真值快照）
- `DelegatedRuntimeReadinessEvaluator` 文档注明：artifacts "forwarded via reconciliation signal channel"（RuntimeController 负责推送）

**❌ 已确认断层（ReconciliationSignal 的 AIP 消息类型映射缺失）**：
- `AipModels.kt` 的 `MsgType` enum 中**没有** `reconciliation_signal` 或 `participant_state` 消息类型
- `ReconciliationSignal.kt` 是 Android 内部数据结构，其 wire key 常量（`KEY_KIND = "reconciliation_signal_kind"`）定义在类中，但无对应的 AIP message type 封装
- 推断：readiness artifact 可能通过 `PARTICIPANT_STATE` kind 作为 `task_result` payload 附带字段上报，但这个路径在代码中未能找到明确的序列化和发送代码
- 这是一个**已确认的结构性断层**：`ReconciliationSignal` 作为 Android 内部 DTO 存在，但其 wire 格式传输路径尚未完整建立

---

## 3. Result Convergence 链路

### 链路描述
Android 执行结果 → 上报 V2 → V2 并行聚合（可能多个 Android 节点）→ 最终 canonical result。

### 代码落点

```
Android 侧：
  1. 执行完成 → DelegatedExecutionSignal (RESULT, success/failure)
  2. AndroidFlowAwareResultConvergenceParticipant.kt：本地结果贡献
  3. FlowAwareResultConvergenceDecision.kt：本地收敛决策
  4. GalaxyWebSocketClient 上报 delegated_execution_signal + (旧路径) goal_execution_result

V2 侧：
  5. android_delegated_signal_ingress 接收新格式 RESULT 信号
  6. android_execution_signal_reconciler 对账，调用 apply_result()
  7. FlowAwareResultConvergence.coordinate_parallel_result_aggregation()
     → 支持 duplicate 抑制、并行聚合、flow 感知
  8. GoalResultAggregator / CrossRuntimeResultMerge（contracts/）
```

### 链路完整性判断

**✅ delegated_execution_signal 链路完整接通（已代码验证）**：
通过检查 V2 gateway 代码，确认完整路由路径：
1. Android → `GalaxyWebSocketClient.sendJson()` → V2 WebSocket
2. V2 `android_bridge.py` 第 94 行：`from galaxy_gateway.android.handlers.delegated_signal import handle_delegated_execution_signal`
3. `galaxy_gateway/android/handlers/delegated_signal.py` 调用 `core.android_delegated_signal_ingress.ingest_delegated_execution_signal()`
4. 结果转发至 `SourceDispatchOrchestrator.consume_android_behavioral_result()`

**⚠️ 旧格式路径残留**：
- 旧 `goal_execution_result` / `task_result` 路径通过 `android_execution_signal_reconciler.py` 中的 compat 推断处理
- 两条路径并存（新旧），Android 当前哪条路径为默认路径需在 `RuntimeController.kt` 中确认

---

## 4. Replay / Reconnect / Recovery / Continuity 链路

### 链路描述
Android 断连/重连/V2 重启 → continuity 决策 → 历史任务恢复 → 执行继续。

### 代码落点

```
Android 侧（断连处理）：
  1. GalaxyWebSocketClient 指数退避重连（1s→2s→4s→8s→16s→30s + jitter）
  2. OfflineTaskQueue：断连期间缓冲 task_result/goal_result
  3. 重连时自动 flush offline queue
  4. AndroidContinuityIntegration.kt：重连时的 continuity 集成
  5. DurableSessionContinuityRecord.kt：持久化 session continuity 记录
  6. RecoveryActivationCheckpoint.kt：恢复激活检查点

V2 侧（重连处理）：
  7. FlowContinuityCoordinator 统一决策入口
     → ContinuityDecision: new_attachment / stale_duplicate / reconnect / v2_restart_recovery 等 7 种
  8. AttachedRuntimeSessionRegistry：维护 session 存活和重连状态
  9. DelegatedFlowPersistence：持久化 flow 状态供 V2 重启恢复
  10. ReplayFoundation：terminal state event 持久化
  11. RuntimeRestartRecovery：V2 重启后恢复 in-flight 任务
```

### 链路完整性判断

**✅ 已在代码中完整**：
- Android 侧重连 + 离线队列 + flush 逻辑完整
- V2 侧 FlowContinuityCoordinator 覆盖所有 7 种 continuity 场景

**⚠️ 双端协调待验证**：
- Android 侧 `AndroidContinuityIntegration.kt` 与 V2 `FlowContinuityCoordinator` 之间的具体协调消息（即 Android 如何告知 V2 它是在做 reconnect 而非首次 attach）
- V2 重启时，已断开的 Android session 的 re-attach 流程是否有完整的 session 状态恢复

---

## 5. Operator Inspect / Audit / Reporting 链路

### 链路描述
V2 持续聚合 operator 可见的 delegated flow 投影；operator 可以查看、覆盖、触发 replay。

### 代码落点

```
V2 侧（主要在中心侧）：
  1. FlowLevelOperatorSurface：canonical operator 投影，包含 delegated flow 快照 + Android execution phase
  2. ReplayAuditPersistence：audit 事件持久化
  3. ReplayFoundation：replay 基础设施（terminal state 触发 replay 路径）
  4. OperatorOverride：手动覆盖接口
  5. DelegatedFlowReadinessGate / AcceptanceGate：生成 report，operator 可查看
  6. ExecutionStatusReport：执行状态报告

Android 侧（贡献 artifacts）：
  7. DeviceReadinessArtifact / DeviceAcceptanceArtifact / DeviceGovernanceArtifact：评估结果上报
  8. RuntimeObservabilityMetadata.kt：Android 侧 observability 元数据
  9. EmittedSignalLedger.kt：已发出信号台账（用于 audit/replay）
```

### 链路完整性判断

**✅ V2 侧完整**：operator 投影、audit 持久化、replay 基础设施均在代码中有实质实现。

**⚠️ Android artifacts 上报路径弱**：
- `DeviceReadinessArtifact` 等评估结果在 Android 侧有生成逻辑，但**推送到 V2 的具体消息类型和 gateway 接收路径不明确**（AipModels.kt 中没有专门的 readiness_artifact 消息类型）

---

## 6. Compat / Legacy Influence / Blocking 链路

### 链路描述
旧路径尝试影响 canonical 决策 → V2 compat 门控阻断 → artifact 记录 → operator 可查看。

### 代码落点

```
Android 侧（识别 compat 状态）：
  1. LongTailCompatibilityRegistry.kt：本地注册已知 long-tail compat 类型
  2. AndroidCompatLegacyBlockingParticipant.kt：识别本地 compat/legacy 影响
  3. CompatibilityRetirementFence.kt：retirement fence 本地维护
  4. CompatibilitySurfaceRetirementRegistry.kt：retirement 注册表

V2 侧（阻断决策）：
  5. CompatLegacyPathBlockingCanonicalization：
     → 5 种决策: canonical_path_confirmed / allow_for_observation_only / block_due_to_legacy_dispatch / block_due_to_compat_truth_influence / quarantine_due_to_ambiguous_contract
  6. CompatFallbackAuthorityGuard：fallback authority 守卫
  7. LegacyDispatchRegistry / LegacyPurgeRegistry：legacy dispatch 注册和清除
  8. CompatSurfaceRetirement：表面层退役
  9. CompatLegacyBlockingRecord artifact 生成 → 进入 operator surface
```

### 链路完整性判断

**✅ V2 侧完整**：compat 阻断决策逻辑完整，5 种决策覆盖所有场景。

**⚠️ Android → V2 的 compat influence 上报路径**：
- Android 识别出 compat/legacy 影响后，如何将这一信息传递给 V2 compat 门控（具体走哪种 AIP 消息类型）未在代码中找到明确路径
- 可能通过 `AndroidCompatLegacyBlockingParticipant` 生成 event 再经 reconciler 处理，但链路细节需进一步验证

---

## 7. Readiness / Acceptance / Governance / Strategy 链路

### 链路描述
双端评估器各自评估 → artifacts 汇聚到 V2 门控 → V2 生成最终 verdict。

### 代码落点

```
Android 侧（评估并生成 artifact）：
  DelegatedRuntimeReadinessEvaluator → DeviceReadinessArtifact
  DelegatedRuntimeAcceptanceEvaluator → DeviceAcceptanceArtifact
  DelegatedRuntimePostGraduationGovernanceEvaluator → DeviceGovernanceArtifact
  DelegatedRuntimeStrategyEvaluator → DeviceStrategyArtifact

V2 侧（聚合并裁决）：
  DelegatedFlowReadinessGate (读取 5 个维度 signal)
  → readiness_compliant / not_ready_due_to_* 等 verdict

  DelegatedFlowAcceptanceGate
  → graduation_accepted / graduation_rejected_due_to_* 等 verdict

  DelegatedFlowPostGraduationGovernance
  → governance_compliant / governance_violation_due_to_* 等 verdict

  DelegatedFlowProgramStrategy
  → strategy_on_track / strategy_risk_due_to_* 等 verdict
```

### 链路完整性判断

**⚠️ 框架双端对齐，实时信号流存在已确认断层**：

这是当前系统最重要的未完全闭合链路，通过代码验证：

1. **推送机制已设计**：`DelegatedRuntimeReadinessEvaluator.INTEGRATION_RUNTIME_CONTROLLER` 注明 "readiness artifacts forwarded via reconciliation signal channel"，表明设计意图是通过 `ReconciliationSignal.Kind.PARTICIPANT_STATE` 由 `RuntimeController` 转发
2. **AIP 消息类型断层（已确认）**：`AipModels.kt` 的 `MsgType` enum 中**不包含** `reconciliation_signal` 或 `participant_state` 消息类型，`ReconciliationSignal.kt` 是 Android 内部 DTO，其 wire key (`reconciliation_signal_kind`) 无对应 AIP 封装，说明 **ReconciliationSignal 的 AIP 传输层尚未建立**
3. **V2 gate 维度输入来源**：`delegated_flow_readiness_gate.py` 读取内部五维度模块，这些模块通过 `android_participant_truth_ingress.py` 的 `readiness_assessment` truth kind 获得 Android 输入，但该 truth kind 的 AIP 消息 mapping 同样依赖 `ReconciliationSignal` 路径，形成循环依赖

**✅ 结构已对齐**：
- 双端评估器维度对齐（readiness/acceptance/governance/strategy 四层）
- V2 gate 的 verdict 类型完整
- Android artifact 结构完整
- `ReconciliationSignal.Kind.PARTICIPANT_STATE` 语义明确（设计意图清晰）
