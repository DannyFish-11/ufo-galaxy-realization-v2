# 05 真实闭环 / 半闭环 / 伪闭环 / 断层清单

## 判断标准

- **真实闭环**：有入口、有传输、有处理、有回流、有状态更新或 verdict 落点，代码链路可连续追踪
- **半闭环**：链路接到某层但未能继续进入另一关键层，某个关键步骤的实现存在但未被接通
- **伪闭环**：surface / evaluator / artifact / model 已存在，但真实调用闭环并未形成
- **断层**：缺失 protocol、message type、handler、route、registry、binding、adapter 等关键部件

---

## ✅ 真实闭环列表

### 1. Android 本地 agent 执行闭环

**入口**：`LoopController.execute(instruction)`
**传输**：本地（无需网络）
**处理**：LocalPlanner → ExecutorBridge → AccessibilityService
**回流**：LoopResult → GalaxyConnectionService 上报 goal_execution_result
**状态更新**：V2 侧 handle_goal_execution_result 接收，task_lifecycle.py 更新状态

**代码证据**：
- `android/.../loop/LoopController.kt` execute() 完整实现
- `v2/galaxy_gateway/android_bridge.py` 注册了 GOAL_EXECUTION_RESULT handler
- `v2/galaxy_gateway/android/handlers/task_lifecycle.py` 处理并 reconcile

---

### 2. 跨设备任务分配 → Android 执行 → goal_execution_result 回收

**入口**：V2 发送 `goal_execution` / `task_assign` (AIP v3)
**传输**：WebSocket (AIP v3)
**处理**：Android `RuntimeController.onRemoteTaskStarted()` → `DelegatedTakeoverExecutor.execute()`
**回流**：Android 发送 `goal_execution_result` / `task_result`
**状态更新**：V2 侧 reconcile_inbound_message → DelegatedRuntimeExecutionTracker 更新

**代码证据**：
- `v2/galaxy_gateway/android_bridge.py` 注册了 GOAL_EXECUTION_RESULT、TASK_RESULT handler
- `android/.../runtime/RuntimeController.kt` 完整的 onRemoteTaskStarted/Finished 实现
- `v2/core/android_execution_signal_reconciler.py` reconcile_inbound_message 实现完整

---

### 3. Delegated Execution Signal 专用上报闭环（PR-16）

**入口**：Android `DelegatedExecutionSignalSink` 发送 `delegated_execution_signal`
**传输**：WebSocket (AIP v3 MessageType.DELEGATED_EXECUTION_SIGNAL)
**处理**：`ingest_delegated_execution_signal()` → `reconcile_android_execution_signal()`
**状态更新**：DelegatedRuntimeExecutionTracker 精确状态更新
**下游**：result-kind signal → `SourceDispatchOrchestrator.consume_android_behavioral_result()`

**代码证据**：
- `v2/galaxy_gateway/android_bridge.py` 第 654 行注册了 DELEGATED_EXECUTION_SIGNAL handler
- `v2/galaxy_gateway/android/handlers/delegated_signal.py` 完整实现
- `v2/core/android_delegated_signal_ingress.py` 完整的 ingress → reconcile 链路

---

### 4. 设备注册 → capability 上报闭环

**入口**：Android 发送 `device_register` + `capability_report`
**传输**：WebSocket
**处理**：`handle_device_register` → `_write_registration_to_udm()` → UnifiedDeviceManager
**状态更新**：设备注册表、UDM 更新

**代码证据**：
- `v2/galaxy_gateway/android_bridge.py` `_write_registration_to_udm()` 实现
- `v2/galaxy_gateway/android/handlers/registration.py` 注册 handler
- `v2/galaxy_gateway/android/handlers/capability_report.py` capability handler

---

### 5. Heartbeat 保活闭环

**入口**：Android 定时发送 `heartbeat`
**传输**：WebSocket
**处理**：`handle_heartbeat` → 更新设备最后活跃时间
**回流**：`heartbeat_ack` 返回 Android

**代码证据**：
- `v2/galaxy_gateway/android/handlers/heartbeat.py` 完整实现

---

## ⚡ 半闭环列表

### 1. HandoffEnvelopeV2 链路（下行完整，上行断层）

**已接通**：V2 → Android `handoff_envelope_v2` 下行传输完整
**已接通**：Android 侧 `GalaxyConnectionService` 有专用 stateful handler（PR-H promoted）
**已存在但未接通**：Android 发送 `handoff_envelope_v2_result`（MsgType 中已定义）
**断点**：V2 `galaxy_gateway/android_bridge.py` 中 HANDOFF_ENVELOPE_V2_RESULT 无注册 handler
**断点**：`core/android_handoff_v2_response_ingress.py` 存在且完整，但无 gateway 调用它的路径

**判定**：半闭环（下行已通，上行未接通）

---

### 2. Recovery / Session Continuity 链路

**已接通**：Android 重连后发送 device_register → V2 识别设备，重建 session
**已存在**：Android `DurableSessionContinuityRecord.kt` 保存本地 continuity 快照
**已存在**：V2 `attached_runtime_session_registry.py` 维护 session 记录
**未接通**：两端的 continuity state 没有正式同步协议，Recovery 依赖重新注册而非精确 continuity 数据传递

**判定**：半闭环（基础 reconnect 闭环，但精确 continuity state 未同步）

---

### 3. Takeover Response 链路

**已接通**：V2 发送 `takeover_request` → Android 收到并评估（TakeoverEligibilityAssessor）
**已存在**：Android `MsgType.TAKEOVER_RESPONSE` 定义，TakeoverEnvelope 数据模型完整
**断点**：V2 `galaxy_gateway/android_bridge.py` 中 TAKEOVER_RESPONSE 无注册专用 handler
**部分接通**：takeover 结果通过 task_result / goal_execution_result 间接上报（非专用 TAKEOVER_RESPONSE handler）

**判定**：半闭环（通过 task_result 间接闭环，但专用 TAKEOVER_RESPONSE handler 缺失）

---

### 4. Mesh session 链路

**已接通**：MESH_TOPOLOGY / PEER_EXCHANGE handler 已注册
**已存在**：Android `runtime/StagedMeshExecutionTarget.kt`, `StagedMeshParticipationResult.kt`
**未接通**：mesh session 内部的 coordinator → participant 闭环尚未完整（MESH_RESULT 未见专用 handler）

**判定**：半闭环（协议存在，部分 handler 已接通，mesh 执行结果闭环未完成）

---

## 🔴 伪闭环列表

### 1. Android Readiness/Governance/Strategy/Acceptance 评估 → V2 Readiness Gate

**已存在（Android 端）**：
- `DelegatedRuntimeReadinessEvaluator.kt`
- `DelegatedRuntimeGovernanceEvaluator.kt`
- `DelegatedRuntimeStrategyEvaluator.kt`
- `DelegatedRuntimeAcceptanceEvaluator.kt`
- `ReconciliationSignal.kt`（数据模型完整）
- `DeviceReadinessArtifact.kt`, `DeviceGovernanceArtifact.kt`, `DeviceStrategyArtifact.kt`, `DeviceAcceptanceArtifact.kt`

**已存在（V2 端）**：
- `core/delegated_flow_readiness_gate.py`（5 维度评估框架）
- `core/delegated_flow_acceptance_gate.py`
- `core/delegated_flow_post_graduation_governance.py`
- `core/delegated_flow_program_strategy.py`

**断点**：Android 侧 `AipModels.kt` 的 `MsgType` 枚举中，**没有** `reconciliation_signal` 或等价 message type。ReconciliationSignal 数据模型存在，但无法通过 AIP v3 wire 传输到 V2。

**断点**：V2 侧 `galaxy_gateway/protocol/aip_v3.py` 的 `MessageType` 枚举中，**也没有** `reconciliation_signal`。

**结论**：Android 的 readiness/governance/strategy/acceptance artifact 产生机制存在（四层 Evaluator 均有实现骨架），但无法经由 wire 到达 V2 的 readiness gate。V2 的 readiness gate 做不到真正消费 Android 端产生的评估结论。

**判定**：**伪闭环** — surface 语义已建立，但跨端的真实调用闭环未形成

---

### 2. Hybrid execution（hybrid_execute / hybrid_result / hybrid_degrade）

**已存在（Android 端）**：
- `MsgType.HYBRID_EXECUTE` (downlink, minimal-compat)
- `MsgType.HYBRID_RESULT` (uplink, model available)
- `MsgType.HYBRID_DEGRADE` (uplink, model available)

**已存在（V2 端）**：
- `core/hybrid_executor.py`
- `core/hybrid_execution_policy.py`

**断点**：V2 `android_bridge.py` 中 HYBRID_EXECUTE 没有注册 handler，HYBRID_RESULT 没有注册 handler。Android 侧注释写 `@status minimal-compat — logged; degrade/reject reply sent`。

**判定**：**伪闭环** — 协议类型和模型定义存在，但真实执行链路未接通

---

### 3. RAG query 链路（rag_query / rag_result）

**已存在（Android 端）**：`MsgType.RAG_QUERY` (minimal-compat), `MsgType.RAG_RESULT` (model available)
**已存在（V2 端）**：`core/rag_memory.py`
**断点**：`minimal-compat — logged; empty result returned; full RAG pipeline TODO`

**判定**：**伪闭环**

---

## ❌ 断层清单

### 断层 1：HANDOFF_ENVELOPE_V2_RESULT gateway handler 缺失

**证据**：
```python
# v2/galaxy_gateway/android_bridge.py 全部 handler 注册中
# 未见 MessageType.HANDOFF_RESULT / MessageType.HANDOFF_ACK / MessageType.HANDOFF_FAILURE 的注册
# 注意：V2 的 MessageType 枚举有 HANDOFF_DISPATCH/ACK/RESULT/FAILURE
# Android 的 MsgType 枚举有 HANDOFF_ENVELOPE_V2_RESULT
# 两者命名不完全对应，且 V2 侧均未注册 handler
```

**已存在但游离**：`v2/core/android_handoff_v2_response_ingress.py` 完整实现，但无 gateway handler 调用它。

**影响**：handoff_envelope_v2 是单向链路，V2 不知道 Android 的执行结果，造成"发出去就消失"的黑洞状态。

---

### 断层 2：ReconciliationSignal AIP wire 层缺失

**证据**：
- `android/.../runtime/ReconciliationSignal.kt`：数据模型存在
- `android/AipModels.kt`：`MsgType` 最后一个条目是 `HANDOFF_ENVELOPE_V2_RESULT`，无 `reconciliation_signal`
- `v2/galaxy_gateway/protocol/aip_v3.py`：`MessageType` 中无 `reconciliation_signal`

**影响**：Android 端四层评估器（ReadinessEvaluator/GovernanceEvaluator/StrategyEvaluator/AcceptanceEvaluator）产生的评估 artifact 无法通过 wire 传递到 V2。V2 的 readiness gate 无法真正感知 Android 端的 readiness 状态，只能依赖间接推断（如设备注册信息、posture 字段）。

---

### 断层 3：TAKEOVER_RESPONSE 专用 handler 缺失

**证据**：
- `android/AipModels.kt` 有 `TAKEOVER_RESPONSE` MsgType
- `android/.../agent/TakeoverEnvelope.kt` 有完整 response 数据模型
- `v2/galaxy_gateway/android_bridge.py` 无 TAKEOVER_RESPONSE handler 注册

**影响**：Takeover response 只能通过 task_result / goal_execution_result 间接表达，失去了 takeover 语义的精确性（无法区分"正常任务完成"和"takeover 明确响应"）。

---

### 断层 4：HANDOFF_ACK / HANDOFF_RESULT / HANDOFF_FAILURE handler 缺失

**证据**：
- `v2/galaxy_gateway/protocol/aip_v3.py` MessageType 中定义了 HANDOFF_ACK / HANDOFF_RESULT / HANDOFF_FAILURE
- `v2/galaxy_gateway/android_bridge.py` 未见这三个 handler 的注册

**影响**：V2 协议层定义了 handoff 生命周期 ack/result/failure 类型，但 gateway 无法处理这些消息，说明 handoff result 链路的完整生命周期管理是缺失的。

---

## 汇总表

| 项目 | 分类 | 关键缺失部件 |
|------|------|------------|
| Android 本地 agent 执行 | ✅ 真实闭环 | — |
| 跨设备 goal_execution → result 回收 | ✅ 真实闭环 | — |
| Delegated execution signal (PR-16) | ✅ 真实闭环 | — |
| 设备注册 / heartbeat | ✅ 真实闭环 | — |
| HandoffEnvelopeV2 上行结果 | ⚡ 半闭环 | gateway handler for HANDOFF_ENVELOPE_V2_RESULT |
| Recovery / continuity state 同步 | ⚡ 半闭环 | continuity state 传递协议 |
| Takeover response | ⚡ 半闭环 | 专用 TAKEOVER_RESPONSE handler |
| Mesh session 执行结果 | ⚡ 半闭环 | MESH_RESULT handler |
| Android readiness → V2 readiness gate | 🔴 伪闭环 | reconciliation_signal wire type |
| Hybrid execution | 🔴 伪闭环 | HYBRID_EXECUTE/RESULT handler |
| RAG query | 🔴 伪闭环 | full RAG pipeline |
| HANDOFF_ENVELOPE_V2_RESULT gateway | ❌ 断层 | gateway handler + routing |
| ReconciliationSignal wire 层 | ❌ 断层 | AIP wire message type |
| TAKEOVER_RESPONSE handler | ❌ 断层 | gateway handler |
| HANDOFF_ACK/RESULT/FAILURE handler | ❌ 断层 | gateway handlers |
