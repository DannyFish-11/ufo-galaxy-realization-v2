# 成熟度系统体检与下一阶段建议

> **审查方法**：按系统能力维度逐层体检，给出有代码证据的成熟度判断，而不是笼统的"骨架期/成熟期"结论。

---

## 1. 成熟度分层体检

### 第一层：基础传输与会话管理（✅ 完整）

| 能力 | 完成状态 | 代码证据 |
|------|---------|---------|
| AIP v3 协议双端对齐 | ✅ 完整 | `galaxy_gateway/protocol/aip_v3.py` + `protocol/AipModels.kt`：所有基础 MsgType 对应 |
| WebSocket 连接/心跳/重连 | ✅ 完整 | `network/GalaxyWebSocketClient.kt` + `core/communication_layer.py` |
| 设备注册 + posture 声明 | ✅ 完整 | `galaxy_gateway/android/handlers/registration.py` + `runtime/RuntimeController.kt` |
| 离线任务队列 | ✅ 完整 | `network/OfflineTaskQueue.kt` |
| Capability 上报 | ✅ 完整 | `galaxy_gateway/android/handlers/capability_report.py` + `capability/` 包 |

**体检结论**：第一层完整，基础传输可信依赖。

---

### 第二层：基础任务执行与结果回传（✅ 完整）

| 能力 | 完成状态 | 代码证据 |
|------|---------|---------|
| task_assign → task_result | ✅ 完整 | `galaxy_gateway/android/handlers/task_lifecycle.py` + `GalaxyConnectionService.handleTaskAssign()` |
| goal_execution → goal_result | ✅ 完整 | `galaxy_gateway/android/handlers/goal_execution.py` + `GalaxyConnectionService.handleGoalExecution()` |
| parallel_subtask → goal_result | ✅ 完整 | 同上 |
| task_cancel → cancel_result | ✅ 完整 | `GalaxyConnectionService.handleTaskCancel()` |
| Android 本地 LoopController | ✅ 完整 | `loop/LoopController.kt`：完整 plan→execute→observe 循环 |
| 执行信号（ACK/PROGRESS/RESULT）回传 | ✅ 完整 | `delegated_execution_signal` 链路 |

**体检结论**：第二层完整，基础执行可信依赖。

---

### 第三层：高级协议与 Canonical Path 骨架（✅ 骨架完整，部分 wire 断层）

| 能力 | 完成状态 | 代码证据 |
|------|---------|---------|
| HandoffEnvelopeV2 下行（V2→Android）| ✅ 完整 | `contracts/handoff_envelope_v2.py` + `GalaxyConnectionService.handleHandoffEnvelopeV2()` |
| HandoffEnvelopeV2 上行（Android→V2）| ⚠️ 半闭环 | Android 发送实现，V2 MessageType 缺失 + handler 未注册 |
| Delegated flow entity + tracker | ✅ 完整 | `core/delegated_flow_entity.py` + `core/delegated_runtime_execution_tracker.py` |
| Handoff contract + dispatch binding | ✅ 完整 | `core/delegated_runtime_handoff_contract.py` + `core/android_runtime_dispatch_binding.py` |
| Attached session registry | ✅ 完整 | `core/attached_runtime_session_registry.py` + `runtime/AttachedRuntimeSession.kt` |
| Android runtime host 分类（PR-5）| ✅ 完整 | `core/android_runtime_host.py` + `SourceRuntimePosture.kt` |
| Continuity coordinator（7 种场景）| ✅ 完整 | `core/android_v2_continuity_contract.py` + `core/flow_continuity_coordinator.py` |
| Result convergence（并行聚合）| ✅ 完整 | `core/flow_aware_result_convergence.py` |
| Compat/legacy blocking gate | ✅ 完整 | `core/compat_legacy_path_blocking_canonicalization.py` |

**体检结论**：第三层骨架完整，HandoffEnvelopeV2 上行回传存在 gateway routing 断层。

---

### 第四层：发布治理框架（⚠️ 框架完整，证据 wire 层断层）

| 能力 | 完成状态 | 代码证据 |
|------|---------|---------|
| V2 Readiness gate（4 层，6 种 verdict）| ✅ 框架完整 | `core/delegated_flow_readiness_gate.py` |
| V2 Acceptance gate（graduation verdict）| ✅ 框架完整 | `core/delegated_flow_acceptance_gate.py` |
| V2 Post-graduation governance（5 种）| ✅ 框架完整 | `core/delegated_flow_post_graduation_governance.py` |
| V2 Program strategy（5 种 risk/on-track）| ✅ 框架完整 | `core/delegated_flow_program_strategy.py` |
| Android Readiness evaluator + artifact | ✅ 完整 | `runtime/DelegatedRuntimeReadinessEvaluator.kt` + `runtime/DeviceReadinessArtifact.kt` |
| Android Acceptance evaluator + artifact | ✅ 完整 | `runtime/DelegatedRuntimeAcceptanceEvaluator.kt` + `runtime/DeviceAcceptanceArtifact.kt` |
| Android Governance evaluator + artifact | ✅ 完整 | `runtime/DelegatedRuntimePostGraduationGovernanceEvaluator.kt` + `runtime/DeviceGovernanceArtifact.kt` |
| Android Strategy evaluator + artifact | ✅ 完整 | `runtime/DelegatedRuntimeStrategyEvaluator.kt` + `runtime/DeviceStrategyArtifact.kt` |
| **Android artifact → wire → V2 gate 消费** | ❌ 断层 | AipModels.kt 无专用 MsgType；V2 gate 无 ingress 路径 |
| **ReconciliationSignal wire 协议** | ❌ 断层 | AipModels.kt 无 reconciliation_signal MsgType |

**体检结论**：第四层框架结构完整，但 Android 侧证据无法通过 wire 进入 V2 gate，导致 gate 实际上只能依赖 `delegated_execution_signal` 隐式推断，而不是 Android 自评估的显式 artifact。

---

### 第五层：分布式自治协作（🔶 骨架存在，自治闭环未完成）

| 能力 | 完成状态 | 代码证据 |
|------|---------|---------|
| Android 本地自治执行（LoopController）| ✅ 完整 | `loop/LoopController.kt`：独立 agent 循环 |
| 本地/跨设备互斥调度 | ✅ 完整 | `cancelForRemoteTask()` / `clearRemoteTaskBlock()` |
| Android 侧 truth + reconciliation 结构 | ✅ 完整 | `runtime/ReconciliationSignal.kt` + `runtime/RuntimeController.kt` |
| V2 canonical orchestration truth | ✅ 完整 | `core/canonical_session_truth.py` |
| 双端 truth 实时对齐（reconciliation wire）| ❌ 断层 | ReconciliationSignal 无 wire；participant truth 无触发路径 |
| Android artifact 对 V2 gate 决策的真实影响 | 🔶 伪闭环 | 评估器产出 artifact，但 artifact 无法传输到 V2 |
| 动态 handoff 双向闭环 | ⚠️ 半闭环 | 下行完整，上行 routing 断层 |

**体检结论**：第五层自治分布式协作骨架已建成，但两个关键 wire 断层阻止了真正的自治闭合：Android truth 无法实时同步到 V2，V2 gate 无法消费 Android 自评估 artifact。

---

## 2. 跨仓 contract 稳定性评估

### 已稳定的 contract（可信依赖）

| Contract | 稳定程度 | 证据 |
|---------|---------|------|
| AIP v3 基础 MessageType 枚举对齐 | ✅ 稳定 | 双端枚举值精确对应，有 cross-repo consistency gate |
| device_register / heartbeat / task_assign / task_result 消息格式 | ✅ 稳定 | 长期使用，无变更记录 |
| HandoffEnvelopeV2 合同（PR-H）| ✅ 稳定 | `contracts/handoff_envelope_v2.py` + Android 对应实现 |
| Delegated execution signal 格式（PR-16）| ✅ 稳定 | 双端均已落地 |
| Android runtime posture 声明格式 | ✅ 稳定 | `SourceRuntimePosture.kt` + V2 `android_runtime_host.py` |
| Session identity（session_id/device_id/contract_id）| ✅ 稳定 | `core/cross_repo_protocol_consistency.py`（PR-4）建立规范 |

### 脆弱或未落地的 contract（不可依赖）

| Contract | 问题描述 |
|---------|---------|
| HANDOFF_ENVELOPE_V2_RESULT 消息格式 | V2 侧 MessageType 未定义，contract 单边存在 |
| ReconciliationSignal wire format | 完全未定义为 AIP 消息，只是 Android 内部数据结构 |
| Android artifact 上报格式 | 无对应 AIP 消息类型，双端 contract 未建立 |
| Participant truth 定期上报格式 | V2 ingress 已实现，但 Android 侧无触发逻辑 |

---

## 3. 哪些方面已具备真实 distributed-agent skeleton

基于代码事实，以下已具备真实 distributed-agent skeleton（不是语义描述，而是有代码支撑）：

1. **Android 是真正的分布式 agent node**：`LoopController` 提供完整本地 agent 执行循环，`RuntimeController` 提供 4 层自评估框架，`GalaxyWebSocketClient` 提供自治重连逻辑——不依赖 V2 的本地自治执行是真实的。

2. **V2 是真正的 canonical orchestration center**：`OpenClawd` 作为 routing authority，`CommandRouter` 作为跨设备路由，`flow_continuity_coordinator` 作为 recovery 决策中心——V2 的编排权威性是真实的。

3. **双向任务执行链路已建立**：task_assign/task_result、goal_execution/goal_result 的完整 request/response 循环是真实可用的。

4. **Continuity 机制已建立**：7 种 continuity 场景（attach/reconnect/process-recreation/V2-restart/stale-identity/duplicate/partial-result）有机器可检查合约，Android 有 ReconnectRecoveryState 实现，V2 有 flow_continuity_coordinator 实现。

---

## 4. 哪些地方仍停留在治理语义或评估语义

1. **四层 gate 治理**：readiness/acceptance/governance/strategy gate 在 V2 侧是完整的治理语义框架，但当前 V2 gate 消费的"Android 侧证据"实际上是从 `delegated_execution_signal` 推断出来的，而不是 Android 侧四层评估器的显式 artifact。治理语义存在，但证据 wire 未打通。

2. **ReconciliationSignal 语义**：`ReconciliationSignal.kt` 定义了完整的 7 种对账信号语义（PR-51），`RuntimeController` 中有完整的 SharedFlow（PR-52），但这些只是 Android 进程内的语义描述，没有真实的 wire 传输。

3. **Cross-repo consistency gate**：双端各有 consistency 检查（`core/cross_repo_consistency_gates.py` + `protocol/CrossRepoConsistencyGate.kt`），但这些是静态 CI 工具，不是运行时的动态语义对齐机制。

---

## 5. 下一阶段最关键的补充方向

### 优先级 1（最高）：补 wire 协议层

**目标**：让 `HANDOFF_ENVELOPE_V2_RESULT` 和 `ReconciliationSignal` 能真实通过 AIP wire 传输。

**具体工作**：

**a. V2 侧补 MessageType**：
```python
# galaxy_gateway/protocol/aip_v3.py MessageType 枚举中补充：
HANDOFF_ENVELOPE_V2 = "handoff_envelope_v2"
HANDOFF_ENVELOPE_V2_RESULT = "handoff_envelope_v2_result"
RECONCILIATION_SIGNAL = "reconciliation_signal"  # 或选择其他命名
```

**b. Android 侧补 MsgType**：
```kotlin
// protocol/AipModels.kt MsgType 枚举中补充：
RECONCILIATION_SIGNAL("reconciliation_signal")
```

---

### 优先级 2（高）：补 ingress routing（V2 gateway handler 层）

**目标**：让 V2 gateway 能正确路由 `handoff_envelope_v2_result` 和 `reconciliation_signal`。

**具体工作**：

**a. 新增 `galaxy_gateway/android/handlers/handoff_v2_result.py`**：
```python
from core.android_handoff_v2_response_ingress import ingest_android_handoff_response

async def handle_handoff_envelope_v2_result(bridge, websocket, message):
    outcome = await ingest_android_handoff_response(message)
    # 更新 AndroidRuntimeDispatchBindingRuntime
    # 推进 delegated_flow_entity phase
    return {"type": "ack", ...}
```

**b. 在 `galaxy_gateway/android_bridge.py` 注册 handler**：
```python
self._message_handlers[MessageType.HANDOFF_ENVELOPE_V2_RESULT] = _wrap(
    handle_handoff_envelope_v2_result
)
```

---

### 优先级 3（高）：补 ReconciliationSignal emission（Android 侧）

**目标**：让 Android 的 `reconciliationSignals` SharedFlow 实际通过 WebSocket 发送到 V2。

**具体工作**：

在 `service/GalaxyConnectionService.kt` 中启动协程收集 `RuntimeController.reconciliationSignals`：
```kotlin
scope.launch {
    runtimeController.reconciliationSignals.collect { signal ->
        wsClient.send(json {
            "type" to MsgType.RECONCILIATION_SIGNAL.value
            "payload" to signal.toWireMap()
        })
    }
}
```

---

### 优先级 4（中）：补 V2 side ReconciliationSignal 消费逻辑

**目标**：V2 gateway 收到 `reconciliation_signal` 后正确路由到 `android_participant_truth_ingress`。

**具体工作**：
- 新增 `galaxy_gateway/android/handlers/reconciliation_signal.py`
- 调用 `core/android_participant_truth_ingress.ingest_android_participant_truth_message()`
- 在 `android_bridge.py` 注册 handler

---

### 优先级 5（中）：补 artifact 上报触发机制

**目标**：Android 四层评估器产出的 artifact 能定期上报到 V2，让 V2 gate 有真实的 Android 侧证据。

**方案**：
- 可以复用 `ReconciliationSignal` 的 `Kind.RUNTIME_TRUTH_SNAPSHOT` 作为 artifact 上报载体
- 或在 `delegated_execution_signal` payload 中附加 artifact summary

---

## 6. 最终成熟度判断

```
┌────────────────────────────────────────────────────────────────────┐
│                    系统成熟度分级（代码级）                          │
├──────────────────────┬─────────────────────────────────────────────┤
│ 第一层：基础传输/会话  │ ✅ 完整，可信依赖                           │
│ 第二层：基础执行/结果  │ ✅ 完整，可信依赖                           │
│ 第三层：canonical 骨架│ ✅ 骨架完整，1处半闭环（handoff上行）        │
│ 第四层：发布治理框架   │ ⚠️ 框架完整，证据 wire 断层（2处断层）       │
│ 第五层：分布式自治     │ 🔶 骨架已建成，自治闭合未完成（2处断层）     │
└──────────────────────┴─────────────────────────────────────────────┘

总判断：
- 不是基础骨架期（前三层均已完整）
- 不是完整自治协作期（第四、五层有 2 处硬断层）
- 当前处于：canonical path 骨架完整 → 正在补充 wire 协议层和 governance 信号闭合 → 真正可信的分布式自治协作

最优先修复：
1. 补 V2 MessageType 枚举（2个条目）
2. 补 V2 gateway handler 注册（2个 handler）
3. 补 Android GalaxyConnectionService ReconciliationSignal emission
以上三步完成后，系统将从"伪闭环/断层"状态提升到"真实闭环"状态。
```
