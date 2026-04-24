# 02 本地链路 / 跨设备链路联合审查

## 概述

本文从代码层面梳理系统的四条主要执行路径，以及跨路径的协调、recovery、replay 机制。

---

## 链路一：V2 本地执行链路

### 路径重建

```
用户/API 请求
  → galaxy_gateway/routes/ (REST/WebSocket ingress)
  → galaxy_gateway/device_router.py :: DeviceRouter.route_task()
      ↓ source_execution_eligibility 检查
  → 决策：本地执行
  → core/local_execution_chain.py :: LocalExecutionChain
  → core/local_agent_runtime.py :: LocalAgentRuntime.run_manifest()
      ↓ AgentManifest (task description)
  → Thought/Action/Observation loop (REACT / SEQUENTIAL / AUTONOMOUS)
  → 结果回流 OpenClawd → projection / audit / memory backflow
```

### 代码证据

`core/cross_device_execution_chain.py`：
```python
"""
Both chains are canonical, parallel, and explicitly defined.
    LOCAL EXECUTION CHAIN      (core/local_execution_chain.py)
    CROSS-DEVICE EXECUTION CHAIN
"""
```

`core/local_agent_runtime.py`：
```python
"""
执行模式:
1. REACT: LLM 驱动的 ReAct Loop (需要 LLM API)
2. SEQUENTIAL: 按顺序执行预定义动作列表 (无需 LLM)
3. AUTONOMOUS: 先发现本地 MCP 工具, 再自主规划执行
"""
```

### 链路状态

**真实闭环**：入口（API/WebSocket）→ DeviceRouter → LocalExecutionChain → LocalAgentRuntime → 结果回流有完整路径

---

## 链路二：Android 本地执行链路

### 路径重建

```
用户在 Android 应用输入自然语言指令
  → 通过 UI 触发 LoopController.execute(instruction)
      ↓ 检查 isRemoteTaskActive（如果远程任务活跃则拒绝）
  → Phase 0: ensureModels() 确认 MobileVLM 模型文件存在
  → Phase 1: captureScreenshot() 截取当前界面
  → Phase 2: LocalPlanner.plan(screenshot, instruction) → ActionSequence
      ↓ MobileVLM 推理
  → Phase 3: ExecutorBridge.execute(action) → AccessibilityService 执行
  → Phase 4: captureScreenshot() 截取动作后界面
  → Phase 5: PostActionObserver 观察界面变化
  → Phase 6: StagnationDetector 检测重复/卡死
  → 循环直到：task_complete / max_steps / timeout / stagnation / cancelled_by_remote
  → LoopResult 上报（通过 GalaxyConnectionService 发送 goal_execution_result / task_result）
```

### 代码证据

`android/.../loop/LoopController.kt`：

```kotlin
suspend fun execute(instruction: String): LoopResult = withContext(Dispatchers.IO) {
    val sessionId = UUID.randomUUID().toString()
    // Block new local sessions while a remote (Gateway) task is active.
    if (isRemoteTaskActive) {
        return@withContext LoopResult(..., stopReason = STOP_BLOCKED_BY_REMOTE, ...)
    }
    // Phase 0: ensure local model files are present
    ensureModels(sessionId)
    // Phase 1: initial screenshot
    val initialCapture = captureScreenshot(sessionId)
    ...
}
```

### 链路状态

**真实闭环**：`LoopController.execute()` 是完整的 perception-reasoning-action-observation 闭环，且结果通过 `GalaxyConnectionService` 上报给 V2。

---

## 链路三：V2 跨设备 delegation/handoff 链路（下行）

### 路径重建

```
V2 决定跨设备执行（DeviceRouter.route_task() 选择 Android 设备）
  → canonical_handoff_path.py 构建 HandoffContract
      source_runtime_posture / coordination_role resolved
  → galaxy_gateway/device_router.py :: DeviceRouter.route_task()
  → galaxy_gateway/agent_bridge.py :: AgentBridge.handoff(contract)
  → 通过 WebSocket 发送 AIP v3 消息：
      type: "task_assign" / "goal_execution" / "handoff_dispatch" / "handoff_envelope_v2"
  → Android 侧 GalaxyWebSocketClient 收到消息
  → GalaxyConnectionService 消息处理器路由：
      task_assign → onRemoteTaskStarted() → DelegatedTakeoverExecutor.execute()
      handoff_envelope_v2 → HandoffEnvelopeV2 解析 → DelegatedRuntimeUnit 执行
```

### 代码证据

`v2/core/canonical_handoff_path.py`：
```python
"""
Canonical path (MAIN repo side)
    ingress (REST / WebSocket)
        ↓  source_runtime_posture resolved at boundary
    galaxy_gateway/routes/chat.py
        ↓
    galaxy_gateway/device_router.py :: DeviceRouter.route_task()
        ↓
    galaxy_gateway/agent_bridge.py :: AgentBridge.handoff(contract)
        ├─ POST /handoff  (remote runtime endpoint)
        └─ local_fallback → galaxy_gateway/cross_device_coordinator.py
"""
```

`android/.../runtime/RuntimeController.kt`：
```kotlin
/**
 * Sole lifecycle authority for the cross-device collaboration runtime.
 * - onRemoteTaskStarted: called when task_assign / goal_execution arrives;
 *   cancels any running local LoopController session.
 * - onRemoteTaskFinished: called when device has sent back task_result /
 *   goal_result; clears LoopController.isRemoteTaskActive.
 */
```

`android/.../protocol/AipModels.kt` 中 `MsgType` 包含：
```kotlin
TAKEOVER_REQUEST("takeover_request"),       // V2 → Android: 要求 takeover
HANDOFF_ENVELOPE_V2("handoff_envelope_v2"), // V2 → Android: HandoffEnvelopeV2
```

### 链路状态

**基础路径真实闭环**：task_assign/goal_execution 下行链路完整，Android 接收后执行并上报 task_result/goal_execution_result。

**handoff_envelope_v2 路径半闭环**：V2 可以发送 HANDOFF_ENVELOPE_V2（Android 有 handler），但 Android 的回复 HANDOFF_ENVELOPE_V2_RESULT 在 V2 侧没有 gateway handler（断层，见第五章）。

---

## 链路四：Android 执行结果上报 → V2 reconciliation 链路（上行）

### 路径重建

```
Android 执行完成（LoopController / DelegatedRuntimeUnit / DelegatedTakeoverExecutor）
  → GalaxyConnectionService 构建 AIP v3 消息：
      type: "goal_execution_result" / "task_result" / "delegated_execution_signal"
      payload: 包含 task_id, session_id, contract_id, signal_kind, result
  → WebSocket 上行发送到 V2 gateway
  → V2 galaxy_gateway/android_bridge.py 消息路由：
      goal_execution_result → handle_goal_execution_result
      task_result → handle_task_result (task_lifecycle.py)
      delegated_execution_signal → handle_delegated_execution_signal (PR-16)
  → 对于 delegated_execution_signal：
      core/android_delegated_signal_ingress.py::ingest_delegated_execution_signal()
        → 提取 DelegatedExecutionSignalEnvelope
        → 调用 core/android_execution_signal_reconciler.py::reconcile_android_execution_signal()
          → 更新 DelegatedRuntimeExecutionTracker 状态
          → 返回 AndroidSignalReconcileOutcome
      → 如果是 result-kind signal：
          → core/runtime/source_dispatch_orchestrator.py::consume_android_behavioral_result()
```

### 代码证据

`v2/galaxy_gateway/android_bridge.py` handler 注册（已验证）：
```python
self._message_handlers[MessageType.GOAL_EXECUTION_RESULT] = _wrap(handle_goal_execution_result)
self._message_handlers[MessageType.TASK_RESULT] = _wrap(handle_task_result)
self._message_handlers[MessageType.DELEGATED_EXECUTION_SIGNAL] = _wrap(
    handle_delegated_execution_signal
)
```

`v2/galaxy_gateway/android/handlers/delegated_signal.py`：
```python
"""
Canonical gateway handler for Android delegated execution signals.
1. Calls ingest_delegated_execution_signal()
2. Logs the reconciliation outcome
3. PR-5A: For result-kind signals, forwards to
   SourceDispatchOrchestrator.consume_android_behavioral_result()
4. Returns ACK response.
"""
```

### 链路状态

**真实闭环**：delegated_execution_signal 上行完整，经过 ingress → reconciler → tracker 更新。task_result / goal_execution_result 上行也有对应 handler。

---

## Recovery / Reconnect / Replay 链路

### V2 侧 recovery

`v2/core/runtime_restart_recovery.py` — runtime restart 恢复
`v2/core/flow_continuity_coordinator.py` — 流连续性协调（PR-3V2）
`v2/core/delegated_flow_recovery_coordinator.py` — 委托流恢复协调

### Android 侧 recovery

`android/.../runtime/AndroidContinuityIntegration.kt` — Android 连续性集成
`android/.../runtime/AndroidLifecycleRecoveryContract.kt` — lifecycle 恢复合约
`android/.../runtime/ReconnectRecoveryState.kt` — 重连恢复状态
`android/.../runtime/DurableSessionContinuityRecord.kt` — 持久化 session 连续性记录
`android/.../runtime/RecoveryActivationCheckpoint.kt` — 恢复激活检查点

`android/.../runtime/RuntimeController.kt` 中有完整 reconnect 逻辑：
```kotlin
/**
 * connectIfEnabled: Called on service restart or activity resume.
 * Syncs the WS client with persisted AppSettings.crossDeviceEnabled
 * and triggers best-effort reconnect.
 */
```

### 双仓 recovery 协调状态

**已有骨架**：两端均有 recovery/continuity 相关组件，且 Android 侧 `DurableSessionContinuityRecord` 与 V2 侧 `attached_runtime_session_registry.py` 有对应关系。

**半闭环**：Android 端的 recovery artifact（ReadinessEvaluator 产出）无法通过 wire 传递到 V2（ReconciliationSignal wire 层缺失，见第五章断层 1）。

---

## 跨路径协调机制总结

| 协调点 | Android 侧代码 | V2 侧代码 | 当前状态 |
|--------|--------------|----------|----------|
| 本地 vs 远程优先级切换 | `RuntimeController.cancelForRemoteTask()` | gateway 发送 task_assign | 真实闭环 |
| 跨设备 takeover 接受评估 | `TakeoverEligibilityAssessor.kt` | `delegated_target_selection_policy.py` | 骨架存在 |
| 执行结果上报 | `GalaxyConnectionService` 发送 goal_execution_result | `handle_goal_execution_result` 接收 | 真实闭环 |
| Delegated signal 上报 | `DelegatedExecutionSignalSink.kt` 发送 | `handle_delegated_execution_signal` 接收 | 真实闭环 |
| HandoffEnvelopeV2 结果上报 | `MsgType.HANDOFF_ENVELOPE_V2_RESULT` 发送 | 无对应 gateway handler | **断层** |
| Readiness artifact 传递 | `ReconciliationSignal.kt` 数据模型存在 | 无对应 wire MessageType | **断层** |
| Recovery 状态同步 | `DurableSessionContinuityRecord.kt` | `attached_runtime_session_registry.py` | 半闭环 |
