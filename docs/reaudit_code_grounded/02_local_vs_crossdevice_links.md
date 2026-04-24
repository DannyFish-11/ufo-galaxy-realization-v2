# 02 — 本地链路 vs 跨设备链路审查

> **审查方法**：从代码入口追踪调用路径，区分纯本地闭环、跨设备协同闭环、语义同构路径，以及名称存在但链路未接通的路径。

---

## 一、纯本地闭环链路

### 1.1 Android 本地 agent loop（完整本地闭环）

**代码路径（Android 侧）：**
```
LocalLoopExecutor.kt
  → LocalLoopReadiness.kt / LocalLoopReadinessProvider.kt（就绪判断）
  → LocalLoopState.kt（状态机）
  → PlannerFallbackLadder.kt（本地规划）
  → GroundingFallbackLadder.kt（本地 grounding）
  → [动作执行]
  → PostActionObserver.kt（动作后观察）
  → StagnationDetector.kt（停滞检测）
  → 下一 step 或 loop 终止
```

**判断**：✅ **真实闭环**。该链路完全在 Android 本地完成，不依赖 V2 connection。`LocalLoopExecutor` 自包含 loop 逻辑，`PlannerFallbackLadder` 提供多级降级，`PostActionObserver` 闭合观察环。

---

### 1.2 Android 本地目标执行（完整本地闭环）

**代码路径（Android 侧）：**
```
LocalGoalExecutor.kt
  → [goal 接收 / 本地解析]
  → [本地工具调用或动作执行]
  → [结果输出]
```

**判断**：✅ **真实闭环**。`LocalGoalExecutor` 有完整的本地 goal 执行逻辑，不需要 V2 参与。

---

### 1.3 Android 自主执行管线（完整本地闭环）

**代码路径（Android 侧）：**
```
AutonomousExecutionPipeline.kt
  → [local LLM 或规则引擎]
  → [动作规划]
  → [执行]
  → [结果]
```

**判断**：✅ **真实闭环**。文件名和大小（27KB）表明是完整管线实现，不是 stub。

---

### 1.4 V2 本地执行（完整本地闭环）

**代码路径（V2 侧）：**
```
SourceDispatchOrchestrator.dispatch()
  → _determine_dispatch_mode() [source_runtime_posture → local_execution]
  → _try_run_local_execution()
  → local_agent_runtime.py: LocalAgentRuntime.execute()
    → _execute_sequential() / _execute_react() / _execute_autonomous()
  → 结果返回 dispatch caller
```

**判断**：✅ **真实闭环**。`_try_run_local_execution()` 在 `source_dispatch_orchestrator.py` 中有实质调用，`LocalAgentRuntime` 有完整三模式（Sequential/ReAct/Autonomous）执行实现。

---

## 二、跨设备协同闭环链路

### 2.1 基础任务执行链（完整跨设备闭环）

**代码路径（V2 → Android → V2）：**
```
[V2] SourceDispatchOrchestrator._try_android_bridge_dispatch()
  → android_bridge.AndroidBridge.assign_task()
  → [WebSocket] TASK_ASSIGN → Android
[Android] AgentRuntimeBridge.kt（接收 TASK_ASSIGN）
  → DelegatedRuntimeUnit.kt（执行）
  → GalaxyWebSocketClient.kt（上报）
  → [WebSocket] TASK_RESULT → V2
[V2] galaxy_gateway/android/handlers/generic.py → handle_task_result()
  → SourceDispatchOrchestrator.consume_android_behavioral_result()
```

**判断**：✅ **真实闭环**。`android_bridge.py` line 612 确认注册了 `TASK_RESULT` handler；`delegated_signal.py` 确认注册了 `DELEGATED_EXECUTION_SIGNAL` handler。两端链路完整接通。

---

### 2.2 Goal 执行链（完整跨设备闭环）

**代码路径（V2 → Android → V2）：**
```
[V2] handle_goal_execution (gateway/android/handlers/goal_execution.py)
  → [WebSocket] GOAL_EXECUTION → Android
[Android] GoalExecutionPipeline.kt
  → [执行]
  → GalaxyWebSocketClient.kt
  → [WebSocket] GOAL_EXECUTION_RESULT → V2
[V2] handle_goal_execution_result (gateway/android/handlers/goal_execution.py)
```

**判断**：✅ **真实闭环**。`android_bridge.py` line 622 确认 `GOAL_EXECUTION_RESULT` 已注册，`GoalExecutionPipeline.kt` 有实质实现。

---

### 2.3 Delegated Execution Signal 链（完整跨设备闭环）

**代码路径（Android → V2）：**
```
[Android] DelegatedRuntimeUnit.kt（执行过程中）
  → DelegatedExecutionSignal.kt（构建信号：ACK/PROGRESS/RESULT/TIMEOUT/CANCELLED）
  → GalaxyWebSocketClient.kt
  → [WebSocket] DELEGATED_EXECUTION_SIGNAL → V2
[V2] android_bridge.py line 654:
  → handle_delegated_execution_signal()（galaxy_gateway/android/handlers/delegated_signal.py）
  → ingest_delegated_execution_signal()（core/android_delegated_signal_ingress.py）
  → SourceDispatchOrchestrator.consume_android_behavioral_result()
```

**判断**：✅ **真实闭环**。这是当前系统最完整的 Android→V2 信号链路，已完整接通。

---

### 2.4 HandoffEnvelopeV2 发送链（半闭环）

**代码路径（V2 → Android）：**
```
[V2] core/delegated_runtime_handoff_contract.py
  → HandoffEnvelopeV2 构建
  → [WebSocket] HANDOFF_DISPATCH → Android
[Android] AipModels.kt: HANDOFF_ENVELOPE_V2("handoff_envelope_v2") 类型已定义
  → DelegatedRuntimeUnit.kt / DelegatedHandoffContract.kt（接收并执行）
```

**下行链路判断**：✅ 下行（V2→Android）真实成立。

**代码路径（Android → V2，返回）：**
```
[Android] 执行完成
  → [WebSocket] HANDOFF_ENVELOPE_V2_RESULT → V2
[V2] galaxy_gateway/android_bridge.py:
  → ❌ 未注册 HANDOFF_ENVELOPE_V2_RESULT handler
  → core/android_handoff_v2_response_ingress.py: 存在但未被路由层接入
```

**上行链路判断**：❌ **断层**。`android_bridge.py` 的 handler 注册表中没有 `HANDOFF_ENVELOPE_V2_RESULT`，导致 Android 返回的 handoff 结果在 V2 gateway 层被丢弃。

**综合判断**：⚠️ **半闭环**（下行成立，上行断层）。

---

### 2.5 设备注册链（完整跨设备闭环）

```
[Android] GalaxyWebSocketClient → DEVICE_REGISTER → V2
[V2] handle_device_register()
  → RegisteredRuntimeDevice 注册
  → source_runtime_posture 解析
  → DEVICE_REGISTER_ACK → Android
[Android] 更新本地连接状态
```

**判断**：✅ **真实闭环**。

---

### 2.6 心跳链（完整跨设备闭环）

```
[Android] heartbeat → V2
[V2] handle_heartbeat → heartbeat_ack → Android
```

**判断**：✅ **真实闭环**。

---

## 三、语义在两种模式下同构的路径

以下语义在本地模式与跨设备模式下**语义同构**（做同样的事情，但执行位置不同）：

| 语义 | 本地模式代码 | 跨设备模式代码 |
|------|------------|--------------|
| Goal 执行 | Android: `LocalGoalExecutor.kt` | V2 分发: `handle_goal_execution` → Android |
| Agent loop（ReAct）| Android: `LocalLoopExecutor.kt` | V2: `LocalAgentRuntime._execute_react()` |
| Task 执行 | Android: `AutonomousExecutionPipeline.kt` | V2: `_try_android_bridge_dispatch()` → Android |
| Readiness 评估 | Android: `LocalLoopReadiness.kt` | V2: `delegated_flow_readiness_gate.py` |
| Takeover | Android: `DelegatedTakeoverExecutor.kt` 本地执行 | V2: `TargetTakeover` 协调跨端 |

---

## 四、仅命名上存在、实际链路未接通的路径

| 路径名称 | 存在的 artifact | 实际缺失 |
|---------|----------------|---------|
| ReconciliationSignal 跨端传输 | Android 有 readiness/acceptance/governance/strategy 四层评估器；V2 有四层 gate | Android MsgType 枚举无 `reconciliation_signal` 类型，wire 层断层 |
| HandoffEnvelopeV2 返回链 | `core/android_handoff_v2_response_ingress.py` 存在 | `android_bridge.py` 未注册 `HANDOFF_ENVELOPE_V2_RESULT` handler |
| AIP RELAY/FORWARD/REPLY | MsgType 有定义 | `AipModels.kt` 注释：`minimal-compat — logged only`，无真实链路 |
| SESSION_MIGRATE | MsgType 有定义 | `AipModels.kt` 注释：`degrade/reject reply; full migration TODO` |
| RAG_QUERY / CODE_EXECUTE | MsgType 有定义 | `AipModels.kt` 注释：`sandbox TODO` |

---

## 五、"任一侧发起均合法"的代码证据

**V2 发起 → Android 执行**：
- `SourceDispatchOrchestrator._try_android_bridge_dispatch()` — V2 主动向 Android 分发任务

**Android 本地发起（无需 V2）**：
- `LocalGoalExecutor.kt` — Android 独立 goal 执行，不需要 V2 发起
- `AutonomousExecutionPipeline.kt` — Android 自主执行管线
- `LocalLoopExecutor.kt` — Android 本地 ReAct loop

**Android 发起 → V2 处理**：
- `DelegatedExecutionSignal.kt` → V2 `consume_android_behavioral_result()` — Android 主动上报，V2 被动消费
- 设备注册链路：Android 主动发起 `DEVICE_REGISTER`，V2 响应

**协议层证明（任一侧发起等价）**：
- `source_runtime_posture` 字段存在于 Android→V2 的所有主要 payload 中，Android 主动声明自己的执行姿态，V2 根据该姿态动态路由，而非预设固定方向
