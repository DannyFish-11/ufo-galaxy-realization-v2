# 05 — 闭环分类：真实闭环 / 半闭环 / 伪闭环 / 断层

> **审查方法**：仅基于代码入口→路由注册→handler 存在→被调用→结果返回 这一完整调用链来分类，不依赖命名或文档声称。

---

## 分类标准

| 分类 | 判断标准 |
|------|---------|
| ✅ 真实闭环 | 代码中可从入口追到出口，handler 已注册，被真实调用，返回路径存在 |
| ⚠️ 半闭环 | 一侧存在真实处理，另一侧缺 signal 或 route；或一方向成立另一方向断层 |
| 🔶 伪闭环 | 命名、artifact、文档、surface 都存在，但真实链路未接通（如 handler 存在但未注册，或类型定义但无调用）|
| ❌ 断层 | 关键 protocol / route / ingress / egress / handler 缺失，链路物理不通 |

---

## 一、真实闭环（✅）

### 1. 设备注册链

- **入口**：Android `GalaxyWebSocketClient` 发送 `DEVICE_REGISTER`
- **处理**：V2 `handle_device_register()`（注册至 `_devices`）
- **响应**：`DEVICE_REGISTER_ACK` → Android 更新连接状态
- **代码证据**：`android_bridge.py` line 610: `self._message_handlers[MessageType.DEVICE_REGISTER] = _wrap(handle_device_register)`

---

### 2. 基础任务执行链（TASK_ASSIGN / TASK_RESULT）

- **入口**：V2 `assign_task()` → `TASK_ASSIGN` → Android
- **处理**：Android `DelegatedRuntimeUnit.kt` 执行，发送 `TASK_RESULT`
- **响应**：V2 `handle_task_result()`（android_bridge.py line 612）
- **代码证据**：handler 注册确认，两端 handler 文件存在

---

### 3. Delegated Execution Signal 链

- **入口**：Android `DelegatedExecutionSignal.kt` → `DELEGATED_EXECUTION_SIGNAL` → V2
- **处理**：V2 `handle_delegated_execution_signal()`（android_bridge.py line 654 确认注册）
- **继续**：→ `ingest_delegated_execution_signal()` → `consume_android_behavioral_result()`
- **代码证据**：完整调用链可追踪

---

### 4. Goal 执行链（GOAL_EXECUTION / GOAL_EXECUTION_RESULT）

- **入口**：V2 → `GOAL_EXECUTION` → Android
- **处理**：Android `GoalExecutionPipeline.kt` → `GOAL_EXECUTION_RESULT` → V2
- **接收**：V2 `handle_goal_execution_result()`（android_bridge.py line 622 确认注册）
- **代码证据**：handler 注册确认

---

### 5. 心跳链（HEARTBEAT / HEARTBEAT_ACK）

- **入口**：Android → `heartbeat` → V2
- **处理**：V2 `handle_heartbeat()` → `heartbeat_ack` → Android
- **代码证据**：android_bridge.py line 611 确认注册

---

### 6. Android 本地 agent loop

- **入口**：`LocalLoopExecutor.kt`
- **执行**：`PlannerFallbackLadder` + `GroundingFallbackLadder` + `PostActionObserver` + `StagnationDetector`
- **完成**：本地状态更新，无需 V2
- **代码证据**：所有模块文件存在，构成完整本地 loop

---

### 7. Android 本地 Goal 执行

- **入口**：`LocalGoalExecutor.kt`
- **执行**：本地完整执行
- **代码证据**：文件存在，有完整实现（4.4KB）

---

### 8. V2 本地 agent 执行（local_agent_runtime）

- **入口**：`SourceDispatchOrchestrator._try_run_local_execution()`
- **执行**：`LocalAgentRuntime.execute()`（三模式：Sequential/ReAct/Autonomous）
- **代码证据**：`local_agent_runtime.py` 有完整 402 行实现，调用链可追踪

---

### 9. 设备能力上报链（CAPABILITY_REPORT）

- **代码证据**：`android_bridge.py` 中 `handle_capability_report` 已注册

---

### 10. Peer 网格消息链（PEER_ANNOUNCE / PEER_EXCHANGE / MESH_TOPOLOGY）

- **代码证据**：`android_bridge.py` 中对应 handler 已注册（peer_exchange.py / mesh_topology.py）

---

## 二、半闭环（⚠️）

### 1. HandoffEnvelopeV2 链（下行成立，上行断层）

- **下行（V2→Android）**：✅ 成立
  - V2 构建 HandoffEnvelopeV2 → `HANDOFF_DISPATCH` → Android
  - Android `AipModels.kt` 定义了 `HANDOFF_ENVELOPE_V2` 类型，有 handler
- **上行（Android→V2）**：❌ 断层
  - Android 发送 `HANDOFF_ENVELOPE_V2_RESULT` → V2 gateway
  - `android_bridge.py` handler 注册表**无** `HANDOFF_ENVELOPE_V2_RESULT`
  - `core/android_handoff_v2_response_ingress.py` 存在但未被路由层接入
- **结论**：⚠️ 半闭环，handoff 是单向的

---

### 2. Android Participant Truth 链

- **V2 ingress 存在**：`core/android_participant_truth_ingress.py` 有实质实现
- **Android 侧发送**：无专用 MsgType，发送路径不明确
- **结论**：⚠️ 半闭环，V2 接收能力存在但 Android 侧发送链路未确认

---

### 3. Continuity 协调链

- **V2 侧**：✅ `FlowContinuityCoordinator.py` 完整
- **Android 侧**：`OfflineTaskQueue.kt` 确认存在；`AndroidContinuityIntegration.kt` 在 V2 侧有引用
- **Wire 集成**：⚠️ 部分通过 `DELEGATED_EXECUTION_SIGNAL` 传达，但 continuity 专用信号未确认
- **结论**：⚠️ 半闭环

---

### 4. Readiness/Acceptance/Governance/Strategy 四层评估链（各自本地成立，跨端未接通）

- **Android 本地**：✅ 四层评估器 + 四层 artifact 本地生成
- **V2 四层 gate**：✅ 对应 gate 文件存在
- **跨端 wire**：❌ `AipModels.kt` MsgType 无 `reconciliation_signal`，artifact 无法传输
- **结论**：⚠️ 半闭环（两端各自本地成立，跨端协作断层）

---

## 三、伪闭环（🔶）

### 1. AIP RELAY/FORWARD/REPLY 链

- **命名存在**：`AipModels.kt` 有 `MsgType.RELAY_REQUEST / RELAY_FORWARD / RELAY_REPLY`
- **实际状态**：`AipModels.kt` 注释明确：`minimal-compat — logged only`
- **链路情况**：无真实处理链路
- **结论**：🔶 伪闭环

---

### 2. SESSION_MIGRATE 链

- **命名存在**：`MessageType.SESSION_MIGRATE / SESSION_MIGRATE_ACK` 均有定义
- **实际状态**：`AipModels.kt` 注释：`degrade/reject reply; full migration TODO`
- **结论**：🔶 伪闭环

---

### 3. RAG_QUERY / CODE_EXECUTE 链

- **命名存在**：`MessageType.RAG_QUERY / RAG_RESULT / CODE_EXECUTE / CODE_RESULT`
- **实际状态**：`AipModels.kt` 注释：`sandbox TODO`
- **结论**：🔶 伪闭环

---

### 4. HYBRID_EXECUTE 链

- **命名存在**：`MessageType.HYBRID_EXECUTE / HYBRID_RESULT / HYBRID_DEGRADE`
- **实际状态**：`minimal-compat stub`
- **结论**：🔶 伪闭环

---

## 四、断层（❌）

### 1. HandoffEnvelopeV2 返回路由断层

- **缺失内容**：`galaxy_gateway/android/handlers/` 中无 `handoff_envelope_v2_result.py` handler
- **影响**：Android 返回的 handoff 结果在 V2 gateway 层被丢弃，V2 永远不知道 handoff 执行结果
- **已有的但未接通**：`core/android_handoff_v2_response_ingress.py` 存在完整 ingress 逻辑，但 `android_bridge.py` 未路由到它
- **代码证据**：搜索 `android_bridge.py` 中 handler 注册表，无 `HANDOFF_ENVELOPE_V2_RESULT` 条目

---

### 2. ReconciliationSignal wire 协议断层

- **缺失内容**：`AipModels.kt` MsgType 枚举最后一个条目是 `HANDOFF_ENVELOPE_V2_RESULT`，无 `reconciliation_signal` 或等价类型
- **影响**：Android 四层评估器（readiness/acceptance/governance/strategy）产出的 artifact 无法通过 wire 传到 V2 readiness gate
- **代码证据**：grep MsgType 枚举全部条目，确认无 reconciliation 相关类型
- **已有的但未接通**：V2 侧有 `android_execution_signal_reconciler.py`，Android 侧有四层评估器，但 wire 类型缺失导致链路物理不通

---

## 五、分类汇总

| 分类 | 条目数 | 关键条目 |
|------|--------|---------|
| ✅ 真实闭环 | 10 | 设备注册、任务执行、goal 执行、delegated signal、心跳、本地 loop 等 |
| ⚠️ 半闭环 | 4 | HandoffEnvelopeV2 返回、truth、continuity、四层评估跨端 |
| 🔶 伪闭环 | 4 | RELAY/FORWARD/REPLY、SESSION_MIGRATE、RAG/CODE、HYBRID |
| ❌ 断层 | 2 | HandoffEnvelopeV2 返回路由、ReconciliationSignal wire 协议 |
