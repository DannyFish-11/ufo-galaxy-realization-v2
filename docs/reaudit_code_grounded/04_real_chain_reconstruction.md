# 04 — 真实主链路重建

> **审查方法**：从代码入口函数追踪，不预设方向，重新分类五类主链路，并标注每条链路的真实接通程度。

---

## 一、Request / Delegation / Handoff / Execution 主链

### 1.1 V2 → Android 任务分发链（真实闭环）

```
[入口] SourceDispatchOrchestrator.dispatch(task_envelope)
  → _determine_dispatch_mode():
      source_runtime_posture="join_runtime" / target_device_id 存在
      → SourceDispatchMode.android_bridge_dispatch
  → _try_android_bridge_dispatch(target_device_id, task)
      → android_bridge.AndroidBridge.assign_task()
      → WebSocket: TASK_ASSIGN → Android
  [Android 侧]
  → AgentRuntimeBridge.kt 接收
  → DelegatedRuntimeUnit.kt 执行
  → WebSocket: TASK_RESULT / DELEGATED_EXECUTION_SIGNAL → V2
  [V2 侧]
  → handle_task_result() / handle_delegated_execution_signal()
  → SourceDispatchOrchestrator.consume_android_behavioral_result()
```

**链路状态**：✅ **真实接通**

---

### 1.2 HandoffEnvelopeV2 分发链（半接通）

```
[入口] DelegatedRuntimeHandoffContract.py → 构建 HandoffEnvelopeV2
  → WebSocket: HANDOFF_DISPATCH → Android
  [Android 侧]
  → AipModels.kt: HANDOFF_ENVELOPE_V2("handoff_envelope_v2") 已定义
  → DelegatedHandoffContract.kt / DelegatedRuntimeUnit.kt 处理
  → WebSocket: HANDOFF_ENVELOPE_V2_RESULT → V2
  [V2 侧]
  → ❌ android_bridge.py 未注册 HANDOFF_ENVELOPE_V2_RESULT handler
  → core/android_handoff_v2_response_ingress.py: 存在，但从未被路由层调用
```

**链路状态**：⚠️ **半接通**（下行接通，上行断层）

---

### 1.3 Goal 执行链（真实闭环）

```
[任意入口] handle_goal_execution() / Android LocalGoalExecutor.kt
  V2 发起:
    → WebSocket: GOAL_EXECUTION → Android
    → GoalExecutionPipeline.kt
    → WebSocket: GOAL_EXECUTION_RESULT → V2
    → handle_goal_execution_result()
  Android 本地发起:
    → LocalGoalExecutor.kt → 本地执行 → 本地结果（无需 V2 参与）
```

**链路状态**：✅ **跨设备链路真实接通；本地链路也真实接通**

---

## 二、Result / Reconciliation / Convergence 主链

### 2.1 Delegated Execution Signal 结果收敛链（真实闭环）

```
[Android 执行中/完成]
  → DelegatedExecutionSignal.kt 构建信号
    (phase: ACK / PROGRESS / RESULT / TIMEOUT / CANCELLED)
  → GalaxyWebSocketClient.kt
  → WebSocket: DELEGATED_EXECUTION_SIGNAL → V2
  [V2]
  → handle_delegated_execution_signal()（android_bridge.py line 654 确认注册）
  → ingest_delegated_execution_signal()
  → android_execution_signal_reconciler.py 处理
  → SourceDispatchOrchestrator.consume_android_behavioral_result()
  → 触发 replay 事件（android_terminal_signal）
```

**链路状态**：✅ **真实接通**

---

### 2.2 Android Participant Truth 收敛链（部分接通）

```
[V2]
  → core/android_participant_truth_ingress.py:
    ingest_android_participant_truth(message)
  [Android]
  → （需要从 Android 发送 truth 消息）
  → 当前无专用 MsgType 承载 participant truth 消息
```

**链路状态**：⚠️ **V2 侧 ingress 存在，Android 侧无专用 wire 类型送达**

---

### 2.3 Reconciliation Signal 收敛链（断层）

```
[Android 侧]
  → DelegatedRuntimeReadinessEvaluator.kt → DeviceReadinessArtifact.kt
  → DelegatedRuntimeAcceptanceEvaluator.kt → DeviceAcceptanceArtifact.kt
  → DelegatedRuntimePostGraduationGovernanceEvaluator.kt → DeviceGovernanceArtifact.kt
  → DelegatedRuntimeStrategyEvaluator.kt → DeviceStrategyArtifact.kt
  → ❌ AipModels.kt MsgType 枚举无 reconciliation_signal 类型
  → 无法通过 wire 到达 V2
  [V2 侧]
  → core/android_execution_signal_reconciler.py: 存在
  → delegated_flow_readiness_gate.py: 存在
  → ❌ 无法收到 Android 侧的 readiness/acceptance/governance/strategy artifact
```

**链路状态**：❌ **断层**（Android 本地评估存在，V2 gate 存在，中间 wire 缺失）

---

## 三、Replay / Reconnect / Recovery / Continuity 主链

### 3.1 离线任务缓存与重放链（Android 侧真实闭环，跨端部分接通）

```
[Android 侧，连接断开]
  → OfflineTaskQueue.kt: 缓存任务
  → GalaxyWebSocketClient.kt: 重连策略（指数退避）
  [连接恢复后]
  → OfflineTaskQueue 中缓存任务重新发送
  [V2 侧]
  → 接收重发任务（如果 V2 侧允许幂等处理）
  → FlowContinuityCoordinator.py: continuity 事件协调
```

**链路状态**：✅ Android 本地部分真实接通；跨端 reconnect 语义接通（WebSocket 重连）

---

### 3.2 V2 侧 Replay/Audit 链（V2 本地真实闭环）

```
[V2 侧]
  → replay_foundation.py: 提供 replay 事件基础
  → replay_audit_persistence.py: 持久化 replay 事件
  → flow_level_operator_surface.py: operator 可观测
  → runtime_restart_recovery.py: 重启恢复
```

**链路状态**：✅ **V2 本地真实接通**

---

### 3.3 Continuity 协调链（V2 主导，双端参与）

```
[V2]
  → flow_continuity_coordinator.py:
    on_continuity_event()（会话注册、执行跟踪、持久化恢复）
  [Android]
  → android_v2_continuity_contract.py: Android-V2 联合 continuity 合约（V2 侧）
  → AndroidContinuityIntegration.kt: Android 侧参与（具体实现待确认）
```

**链路状态**：⚠️ **V2 侧完整，Android 侧参与模块存在但 wire 集成程度待验证**

---

## 四、Operator / Audit / Inspect / Reporting 主链

### 4.1 V2 Operator Surface 链（V2 本地真实闭环）

```
[V2]
  → flow_level_operator_surface.py: operator 界面
  → replay_audit_persistence.py: 审计日志
  → runtime_decision_observability.py: 决策可观测
  → execution_observability/: 执行可观测模块组
```

**链路状态**：✅ **V2 侧真实接通**

---

### 4.2 Android 侧观测上报链（部分接通）

```
[Android 侧]
  → observability/ 目录: 本地可观测模块
  → DelegatedExecutionSignal.kt: 执行信号上报
  → RuntimeObservabilityMetadata（具体实现在 Android runtime 目录）
  → GalaxyWebSocketClient: 发送到 V2
  [V2 侧]
  → handle_delegated_execution_signal: 消费信号
```

**链路状态**：✅ **通过 DelegatedExecutionSignal 链路已接通**；但 readiness/governance artifact 仍未接通

---

## 五、Compat / Fallback / Legacy / Blocking 主链

### 5.1 Compat Legacy Path Blocking（V2 侧真实，Android 侧对应）

```
[V2 侧]
  → compat_legacy_path_blocking_canonicalization.py: compat 影响进入 canonical 决策前的唯一阻断门
  → center_side_compat_closure.py: 中心侧 compat 收口
  → compat_fallback_authority_guard.py: fallback 权威守卫
  → legacy_purge_registry.py: legacy 注销注册表
[Android 侧]
  → AndroidCompatLegacyBlockingParticipant（V2 侧有对应引用）
```

**链路状态**：✅ **V2 侧完整；Android 侧 compat blocking 参与者在 V2 侧有注册引用**

---

### 5.2 Grounding/Planner Fallback Ladder（Android 侧真实闭环）

```
[Android 侧]
  → PlannerFallbackLadder.kt: 规划失败时的多级降级
  → GroundingFallbackLadder.kt: grounding 失败时的多级降级
  → 本地完成，不依赖 V2
```

**链路状态**：✅ **Android 本地真实接通**

---

## 六、Readiness / Acceptance / Governance / Strategy 是否真实进入运行链

**纠偏回答（基于代码）**：

这四层在两端的当前状态是：

| 层 | V2 侧 | Android 侧 | 跨端 wire | 结论 |
|----|-------|-----------|----------|------|
| Readiness | `delegated_flow_readiness_gate.py`（gate，真实）| `DelegatedRuntimeReadinessEvaluator.kt`（artifact，真实）| ❌ 无 reconciliation_signal wire | ⚠️ 各自存在，未跨端闭合 |
| Acceptance | `delegated_flow_acceptance_gate.py`（gate，真实）| `DelegatedRuntimeAcceptanceEvaluator.kt`（artifact，真实）| ❌ 无 wire | ⚠️ 各自存在，未跨端闭合 |
| Governance | `delegated_flow_post_graduation_governance.py`（gate，真实）| `DelegatedRuntimePostGraduationGovernanceEvaluator.kt`（artifact，真实）| ❌ 无 wire | ⚠️ 各自存在，未跨端闭合 |
| Strategy | `delegated_flow_program_strategy.py`（gate，真实）| `DelegatedRuntimeStrategyEvaluator.kt`（artifact，真实）| ❌ 无 wire | ⚠️ 各自存在，未跨端闭合 |

**结论**：
- 这四层**不是"仍停留在 artifact / surface / evaluator 层"** — 两端都有真实实现
- 但**跨端闭环确实未接通** — 因为 Android MsgType 枚举缺少 `reconciliation_signal`，导致 Android 的评估结果无法通过 wire 到达 V2 的 gate 层
- 因此当前这四层处于"**两端各自本地成立，跨端协作断层**"的状态
