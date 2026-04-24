# 本地链路 / 跨设备链路联合审查

> **审查方法**：沿真实代码调用路径追踪，不依赖文档描述。
> **代码来源**：
> - V2：`core/local_execution_chain.py`、`core/cross_device_execution_chain.py`、`galaxy_gateway/android_bridge.py`、`core/android_handoff_v2_response_ingress.py`、`core/flow_continuity_coordinator.py`
> - Android：`loop/LoopController.kt`、`service/GalaxyConnectionService.kt`、`runtime/RuntimeController.kt`、`network/GalaxyWebSocketClient.kt`

---

## 1. Android 本地发起链路

### 1.1 链路路径（代码重建）

```
用户输入（FloatingWindow/语音/EnhancedFloatingService）
    ↓
GalaxyConnectionService.handleTaskAssign()   [gateway 下发路径]
    OR
FloatingWindowService / EnhancedFloatingService  [本地 UI 发起路径]
    ↓
路由判断（GalaxyConnectionService）:
    if (crossDeviceEnabled && !require_local_agent) {
        → AgentRuntimeBridge.handoff()     [跨设备路径]
    } else {
        → executeLocalTaskAssign()          [本地路径]
    }
    ↓
executeLocalTaskAssign()
    → EdgeExecutor.execute(payload)
    → 结果包装为 task_result 消息
    → GalaxyWebSocketClient.send(task_result)  [回传 V2]
    → RuntimeController.onRemoteTaskFinished()  [解除本地执行互斥]
```

### 1.2 Android 纯本地执行链路（不依赖 V2）

```
用户输入（本地语音/FloatingWindow instruction）
    ↓
LoopController.execute(instruction)
    ↓
Phase 0: ensureModels() → 检查/下载本地模型（ModelAssetManager + ModelDownloader）
    ↓
Phase 1: screenshotProvider.capture() → 截图
    ↓
Phase 2: localPlanner.plan(sessionId, instruction, screenshot) 
         → MobileVLM 推理 → ActionSequence
    ↓
Phase 3: stagnationDetector.check() → 防重复检测
    ↓
Phase 4: executorBridge.executeStep(step)
         → GroundingFallbackLadder (SeeClick)
         → AccessibilityService 执行
    ↓
Phase 5: screenshotProvider.capture() → 后置截图
    ↓
Phase 6: postActionObserver.observe() → 记录观测
    ↓
Phase 7: 检查 cancelRequested → 循环 or 终止
    ↓
LoopResult (status=success/failed/cancelled, stopReason, steps)
```

**状态**：✅ **真实闭环**。入口（用户输入）→ 传输（本地调用）→ 处理（LLM + Accessibility）→ 观测（PostActionObserver）→ 状态更新（LoopStatus StateFlow）均已实现。

### 1.3 互斥机制（本地 vs 远程的共调度）

```kotlin
// 代码证据：LoopController.kt
const val STOP_CANCELLED_BY_REMOTE = "cancelled_by_remote_task"
const val STOP_BLOCKED_BY_REMOTE = "blocked_by_remote_task"

@Volatile var isRemoteTaskActive: Boolean = false
    private set

fun cancelForRemoteTask() {
    cancelRequested = true
    isRemoteTaskActive = true
}
fun clearRemoteTaskBlock() {
    cancelRequested = false
    isRemoteTaskActive = false
}
```

```kotlin
// 代码证据：GalaxyConnectionService.kt
// 远程任务到来时暂停本地执行
loopController.cancelForRemoteTask()

// 远程任务结束后恢复本地执行
RuntimeController.onRemoteTaskFinished()
    → loopController.clearRemoteTaskBlock()
```

**结论**：本地链路和跨设备链路在 Android 侧是同一个 runtime 上的互斥调度，不是两套独立系统。

---

## 2. V2 本地发起链路

### 2.1 链路路径（代码重建）

```python
# 代码证据：core/local_execution_chain.py

OpenClawd (routing authority)
    ↓ route_request(mode=LOCAL_MANIFESTATION)
CommandRouter.route_envelope()
    ↓
Local executor (能力/技能/MCP tool 之一):
    - capability modules     (core/capabilities/)
    - skill packages         (skills/)
    - MCP tools              (core/mcp_loader.py)
    ↓
LocalExecutionResult (规范化结果容器)
    ↓
OpenClawd feedback
    ↓
Projection / Memory backflow (downstream consumers)
```

**状态**：✅ **真实闭环**。V2 本地链路有完整的路由→执行→结果→反馈路径。

### 2.2 V2 系统启动时的 runtime subject 链

```python
# 代码证据：core/system_orchestrator.py
# Phase 5 — RUNTIME_SUBJECT
# Phase 7 — READINESS_SUMMARY
```

V2 自身是一个有 staged 启动合约的 runtime，不只是一个 HTTP 服务，这说明 V2 也有完整的 agent runtime 生命周期。

---

## 3. V2→Android 跨设备链路（下行）

### 3.1 链路路径（代码重建）

```python
# V2 侧（代码证据：core/cross_device_execution_chain.py + contracts/handoff_envelope_v2.py）

OpenClawd (routing authority)
    ↓ route_request(mode=CROSS_DEVICE_MANIFESTATION)
CommandRouter.route_envelope()
    ↓
DelegatedFlowEntity 创建（core/delegated_flow_entity.py）
    ↓
DelegatedRuntimeHandoffContract 生成（core/delegated_runtime_handoff_contract.py）
    ↓
HandoffEnvelopeV2 构建（contracts/handoff_envelope_v2.py）
    ↓
galaxy_gateway/android/message_builder.py:
    build_handoff_dispatch_message(envelope)
    → AIP message: type="handoff_envelope_v2", payload=HandoffEnvelopeV2
    ↓
AndroidBridge.send(ws, message)
    → WebSocket → Android
```

```kotlin
// Android 侧（代码证据：service/GalaxyConnectionService.kt）

onMessage: type = "handoff_envelope_v2"
    ↓
handleHandoffEnvelopeV2(taskId, payloadJson, traceId)
    ↓
1. 解析 HandoffEnvelopeV2 payload
2. loopController.cancelForRemoteTask()     [暂停本地执行]
3. 执行 handoff 任务（EdgeExecutor 或 AutonomousExecutionPipeline）
4. 构建 HandoffEnvelopeV2ResultPayload
5. sendHandoffEnvelopeV2Result()
   → GalaxyWebSocketClient.send(type="handoff_envelope_v2_result", payload=result)
```

**下行链路状态**：✅ **真实闭环**（V2→Android）。

### 3.2 handoff 结果回路（上行）

```kotlin
// Android 侧（代码证据：protocol/AipModels.kt）
HANDOFF_ENVELOPE_V2_RESULT("handoff_envelope_v2_result")
// GalaxyConnectionService 已实现 sendHandoffEnvelopeV2Result()
```

```python
# V2 侧 ingress（代码证据：core/android_handoff_v2_response_ingress.py）
# 文件存在，实现了 ingest_android_handoff_response()
# 但 galaxy_gateway/protocol/aip_v3.py 的 MessageType 枚举
# 没有 HANDOFF_ENVELOPE_V2_RESULT 条目
# android_bridge.py 的 _message_handlers 字典也没有注册对应 handler
```

**上行链路状态**：⚠️ **半闭环**。Android 发送有实现，V2 ingress 处理有实现，但 gateway routing 层未接通（消息类型未注册，handler 未挂接）。

---

## 4. Android→V2 跨设备链路（delegated execution signal 上行）

### 4.1 链路路径（代码重建）

```kotlin
// Android 侧（代码证据：runtime/RuntimeController.kt + service/GalaxyConnectionService.kt）

DelegatedExecutionSignalSink.emit(signal)
    ↓
GalaxyConnectionService 内部收集 RuntimeController.reconciliationSignals
    ↓
发送：type = "delegated_execution_signal"（AipModels.MsgType.DELEGATED_EXECUTION_SIGNAL）
    payload: DelegatedExecutionSignalPayload
```

```python
# V2 侧（代码证据：galaxy_gateway/android/handlers/delegated_signal.py）

handle_delegated_execution_signal(bridge, websocket, message)
    ↓
ingest_delegated_execution_signal(message)  [core/android_delegated_signal_ingress.py]
    ↓
extract_delegated_signal_envelope(message) → DelegatedExecutionSignalEnvelope
    ↓
reconcile_android_execution_signal(envelope) [core/android_execution_signal_reconciler.py]
    ↓
DelegatedExecutionTrackingRuntime.apply(signal)  [更新追踪记录]
    ↓
SourceDispatchOrchestrator.consume_android_behavioral_result()  [PR-5A]
```

**状态**：✅ **真实闭环**。`delegated_execution_signal` 消息类型已在 V2 的 `MessageType` 枚举中定义，handler 已注册，ingress → reconcile → tracker 更新链路完整。

### 4.2 ReconciliationSignal 上行（PR-51/52）

```kotlin
// Android 侧（代码证据：runtime/ReconciliationSignal.kt + RuntimeController.kt）

ReconciliationSignal 数据结构（7种 Kind）
    ↓
RuntimeController._reconciliationSignals SharedFlow
    ↓
??? → 没有对应的 MsgType 定义
```

**状态**：❌ **断层**。`ReconciliationSignal` 数据结构完整，RuntimeController 中有对应 SharedFlow，但 `AipModels.kt` 中没有 `reconciliation_signal` 对应的 `MsgType` 枚举值，GalaxyConnectionService 也没有消费 SharedFlow 并发送到 V2 的逻辑。ReconciliationSignal 当前只在 Android 进程内流转。

---

## 5. Recovery / Reconnect / Replay 介入主链路

### 5.1 Android 侧 reconnect 路径

```kotlin
// 代码证据：runtime/RuntimeController.kt（PR-33）

_reconnectRecoveryState: MutableStateFlow<ReconnectRecoveryState>
// States: IDLE → RECONNECTING → RECOVERED / FAILED

// 重连时：
// 1. GalaxyWebSocketClient 触发 onClosed
// 2. RuntimeController 推进 _reconnectRecoveryState
// 3. 重新 start() → 重新注册 device_register + capability_report
// 4. 重新建立 AttachedRuntimeHostSessionSnapshot
```

```kotlin
// 代码证据：network/OfflineTaskQueue.kt
// 离线期间接收到的任务放入队列
// 重连后 flush 队列
```

**状态**：✅ **真实闭环**。Android 有完整的断线重连 + 队列回放机制。

### 5.2 V2 侧 recovery 路径

```python
# 代码证据：core/android_v2_continuity_contract.py（PR-L）
# 7 种 continuity 场景：
# 1. Android attach（初次注册）
# 2. Android reconnect（传输层重连）
# 3. Android re-attach after process recreation
# 4. V2 restart with in-flight tasks
# 5. Stale participant identity（拒绝过期 identity）
# 6. Duplicate re-entry suppression（幂等）
# 7. Partial result continuity

# 代码证据：core/flow_continuity_coordinator.py
# continuity 事件的统一决策入口
```

**状态**：✅ **真实闭环**。V2 有 7 种 continuity 场景的显式机器可检查合约，continuity coordinator 作为统一决策入口。

### 5.3 Replay / Audit 介入路径

```python
# 代码证据：core/replay_foundation.py + core/replay_audit_persistence.py
# replay foundation：terminal-state events 触发 replay 记录
# replay_audit_persistence：持久化 replay 记录供后续 audit

# 代码证据：core/android_participant_truth_ingress.py
# reconcile_android_participant_truth() 在 terminal-state 时
# 调用 replay_foundation 写入事件记录
```

**状态**：✅ **真实闭环**。Replay 框架已与主执行链路集成，terminal 事件会触发 replay 记录写入。

---

## 6. Operator / Inspect / Audit 路径

```python
# 代码证据：core/flow_level_operator_surface.py
# Operator surface 提供 flow 级别的操作界面

# 代码证据：core/operator_override.py
# Operator 可以 override 系统决策

# 代码证据：core/runtime_introspection.py
# 运行时内省，观察真实执行状态

# 代码证据：core/node_audit.py
# 节点审计
```

**状态**：✅ **骨架完整**。Operator surface、override、introspection、audit 模块均存在。但这些模块的"观察"是基于 V2 侧维护的 canonical 状态，而不是基于 Android 侧的 evidence emission——这意味着当 ReconciliationSignal wire 层不通时，operator 看到的可能是 V2 端的推测状态，而不是 Android 端的事实状态。

---

## 7. 链路完整性汇总

| 链路 | 发起侧 | 执行侧 | 回路 | 状态 |
|------|--------|--------|------|------|
| Android 纯本地链路 | Android UI | Android LoopController | 本地 StateFlow | ✅ 真实闭环 |
| V2 纯本地链路 | OpenClawd | Local executor | OpenClawd feedback | ✅ 真实闭环 |
| V2→Android task_assign | V2 CommandRouter | Android EdgeExecutor | task_result 回传 V2 | ✅ 真实闭环 |
| V2→Android goal_execution | V2 CommandRouter | Android AutonomousExecutionPipeline | goal_execution_result 回传 V2 | ✅ 真实闭环 |
| V2→Android handoff_envelope_v2（下行）| V2 HandoffEnvelopeV2 | Android handleHandoffEnvelopeV2 | HANDOFF_ENVELOPE_V2_RESULT（未被V2接收）| ⚠️ 半闭环 |
| Android delegated_execution_signal | Android signal sink | V2 reconciler | tracking record 更新 | ✅ 真实闭环 |
| Android ReconciliationSignal（PR-51） | Android RuntimeController | ??? | 未发送 wire | ❌ 断层 |
| Android→V2 participant truth | Android（无专用触发器） | V2 ingress（已实现）| 未接通触发路径 | ⚠️ 半闭环 |
| Reconnect / Recovery | Android GalaxyWebSocketClient | V2 continuity coordinator | 7种场景合约已建立 | ✅ 真实闭环 |
| Replay / Audit | V2 terminal-state events | replay_foundation | 持久化记录 | ✅ 真实闭环 |
