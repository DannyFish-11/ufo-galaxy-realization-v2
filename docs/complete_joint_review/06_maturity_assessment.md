# 06 成熟度与下一阶段建议

## 系统体检：各维度成熟度评估

### 维度 1：分布式 Agent Skeleton 完整性

**已具备（真实代码）**：
- V2 端：LocalAgentRuntime（REACT/SEQUENTIAL/AUTONOMOUS 三种执行模式）、LocalExecutionChain、CrossDeviceExecutionChain
- Android 端：LoopController（完整 perception-reasoning-action-observation 循环）、AutonomousExecutionPipeline、EdgeExecutor
- 两端均有 agent runtime，不是单侧 agent

**评级**：★★★★☆ — 分布式 agent skeleton **已真实存在**，两端均有独立 agent 能力

---

### 维度 2：跨仓 Protocol Contract 稳定性

**已稳定**：
- AIP v3 消息格式（`aip_v3.py` MessageType vs `AipModels.kt` MsgType）两端基本对齐
- device_register / heartbeat / task_assign / goal_execution / goal_execution_result / delegated_execution_signal 链路已稳定

**仍脆弱或未落地**：
- `HANDOFF_ENVELOPE_V2_RESULT`：Android 端已定义 MsgType，V2 端 MessageType 枚举不完全对应，gateway 未挂接
- `HANDOFF_ACK/RESULT/FAILURE`：V2 MessageType 有定义，但无 handler，实际是否与 Android 侧对齐不明确
- `ReconciliationSignal`：V2/Android 两端协议均无定义，是真正的 wire contract 空白

**评级**：★★★☆☆ — 核心任务执行 contract 稳定，handoff/reconciliation contract 仍脆弱

---

### 维度 3：本地执行链路完整性

**V2 本地**：LocalAgentRuntime 有完整三种模式，LocalExecutionChain 已标记为 canonical
**Android 本地**：LoopController 完整实现，含 MobileVLM 推理、AccessibilityService 执行、stagnation 检测

**评级**：★★★★☆ — 本地执行链路在两端均**真实存在且完整**

---

### 维度 4：跨设备执行链路完整性

**基础链路**：goal_execution / task_assign → DelegatedTakeoverExecutor → goal_execution_result 完整闭环
**高级链路**：handoff_envelope_v2 下行完整，上行（result）断层

**评级**：★★★☆☆ — 基础跨设备执行真实闭环，HandoffEnvelopeV2 完整链路尚未打通

---

### 维度 5：治理语义（Governance Semantics）落地情况

**已存在的治理结构**：
- Android 端：4 层评估框架（ReadinessEvaluator / GovernanceEvaluator / StrategyEvaluator / AcceptanceEvaluator）
- V2 端：delegated_flow_readiness_gate（5 维度）、acceptance_gate、governance、strategy 模块

**未落地的治理链路**：
- Android 4 层评估器的 artifact 无法传递到 V2（wire 断层）
- V2 的 readiness gate 实际上无法消费 Android readiness artifact
- 当前 readiness gate 评估的是 V2 侧内部状态，不是真正双端联合评估

**评级**：★★☆☆☆ — 治理语义框架已建立，但**跨端治理闭环是伪闭环**，真实联合治理未实现

---

### 维度 6：Recovery / Continuity 完整性

**已有**：两端均有 recovery 相关组件（ReconnectRecoveryState、DurableSessionContinuityRecord、FlowContinuityCoordinator）
**基础 reconnect**：reconnect → re-register → session 重建已实现

**未落地**：
- Android 端的 continuity 快照（DurableSessionContinuityRecord）与 V2 session registry 之间没有正式同步协议
- 跨端 continuity state 传递依赖重新注册，精确度有限

**评级**：★★★☆☆ — 基础恢复功能可用，精确 continuity 同步未完成

---

### 维度 7：Compat / Legacy Path 退出进度

**已退出**：
- `aip_protocol_v2.py` 已通过 raise ImportError 强制退出
- Android `CompatibilitySurfaceRetirementRegistry.kt` 维护待退出列表
- V2 `core/compat_surface_retirement.py` 维护 V2 侧列表

**仍活跃**：
- V2 `android_bridge.py` 的 `_registrationError` SharedFlow 是 HIGH_RISK_ACTIVE 兼容面，`@Deprecated` 但仍存在
- 部分 handler 仍通过 reconcile_inbound_message 兼容路径处理（PR-13）而非 PR-16 的专用路径

**评级**：★★★☆☆ — 退出意图明确，有登记机制，但仍有活跃 compat 面

---

## 成熟度总体评级

```
维度                           成熟度
─────────────────────────────────────────
分布式 Agent Skeleton          ★★★★☆  真实骨架已存在
跨仓 Protocol Contract         ★★★☆☆  核心稳定，边缘脆弱
本地执行链路                   ★★★★☆  两端均完整
跨设备基础执行链路              ★★★☆☆  基础闭环，高级断层
治理语义落地                   ★★☆☆☆  框架存在，跨端未接通
Recovery / Continuity          ★★★☆☆  基础可用，精确同步缺失
Compat 退出进度                ★★★☆☆  进行中，仍有活跃面
─────────────────────────────────────────
总体                           ★★★☆☆  具备真实分布式 agent 骨架
                                        处于可运行但不完整的成熟阶段
```

---

## 与上一版审查的差异总结

| 维度 | PR793 结论 | 本次修订结论 |
|------|-----------|------------|
| 系统定位 | "V2 中心编排 + Android 执行端" | "中心分布式智能体系统，两端都有 agent runtime" |
| Android 角色 | "delegated runtime 执行端" | "独立 agent 节点，有完整 planning+execution+observation 循环" |
| 本地链路 | 提及但不突出 | 明确：两端各有完整本地执行链路 |
| 发起路径 | 隐含"V2 发起才 canonical" | 明确：本地 AND 跨设备发起均合法，Android 的 LoopController 是独立发起入口 |
| 断层识别 | 识别了 ReconciliationSignal 和 handoff handler 缺失 | 补充识别：HANDOFF_ACK/RESULT/FAILURE handler 缺失、TAKEOVER_RESPONSE handler 缺失 |
| 治理成熟度 | "框架建成" | 修正为"伪闭环：framework 存在但 wire 未接通，跨端治理未真实运行" |

---

## 下一阶段工程建议

### 优先级 P0：补 gateway handler 打通已有 ingress 实现

**目标**：让已实现的 `core/android_handoff_v2_response_ingress.py` 真正被调用

**具体操作**：
1. 在 `v2/galaxy_gateway/android/handlers/` 新增 `handoff_v2_result.py` handler
2. 调用 `ingest_android_handoff_response(message)` 
3. 在 `v2/galaxy_gateway/android_bridge.py` 注册该 handler：
   ```python
   self._message_handlers[MessageType.HANDOFF_RESULT] = _wrap(handle_handoff_v2_result)
   ```
4. 确认 V2 `MessageType.HANDOFF_RESULT` 与 Android `MsgType.HANDOFF_ENVELOPE_V2_RESULT` 的值对应关系

**代价**：低风险（additive only，不修改现有代码），直接将已实现 ingress 接入 gateway

---

### 优先级 P1：补 ReconciliationSignal wire type

**目标**：让 Android 4 层评估器的 artifact 能够传递到 V2

**具体操作**：
1. 在 `android/AipModels.kt` 的 `MsgType` 枚举中新增：
   ```kotlin
   RECONCILIATION_SIGNAL("reconciliation_signal")
   ```
2. 在 `v2/galaxy_gateway/protocol/aip_v3.py` 的 `MessageType` 枚举中新增：
   ```python
   RECONCILIATION_SIGNAL = "reconciliation_signal"
   ```
3. 定义 `ReconciliationSignalPayload` 数据模型（两端对齐）
4. Android 端从 `ReconciliationSignal.kt` 现有数据模型构建 payload 并发送
5. V2 端新增 gateway handler，接收并路由到 `delegated_flow_readiness_gate.py`

**代价**：中等（需要两端协同修改，但结构清晰）

---

### 优先级 P2：完善 continuity state 传递协议

**目标**：让 recovery 时两端能精确同步 session continuity 状态

**具体操作**：
1. 定义跨端 `SessionContinuitySnapshot` 消息格式
2. Android 重连时，在 device_register 消息的 payload 中携带 `DurableSessionContinuityRecord` 的关键字段
3. V2 侧 `handle_device_register` 在重连情况下读取并与本地 session registry 对比，决定是否需要 replay

**代价**：中等（需要扩展注册消息格式和 V2 侧 session recovery 逻辑）

---

### 优先级 P3：完善 TAKEOVER_RESPONSE 专用 handler

**目标**：让 takeover 语义精确可追踪

**具体操作**：
1. V2 侧新增 `takeover_response.py` handler
2. 解析 `TakeoverEnvelope` 中的 acceptance / rejection / reason 字段
3. 路由到对应的 takeover result 处理逻辑

**代价**：低（additive only）

---

## 最关键的下一阶段判断

> 如果继续推进，**最关键的是补 gateway handler**，不是补协议或补 evaluator。

原因：
- `core/android_handoff_v2_response_ingress.py` 已有完整实现，缺的只是 gateway handler 调用它
- 补 gateway handler 是 additive only，风险极低，立即可以打通一条重要链路
- 相比之下，补 ReconciliationSignal wire 需要双端协同，补 continuity 需要设计同步协议，工程量更大

**最紧迫的工程动作**：
```
1. 新建 galaxy_gateway/android/handlers/handoff_v2_result.py
2. 在 android_bridge.py 中注册 HANDOFF_RESULT（或等价 MsgType）handler
3. 验证 Android MsgType.HANDOFF_ENVELOPE_V2_RESULT 与 V2 MessageType 的 string 值对应关系
```

这三步完成后，handoff_envelope_v2 完整 round-trip 闭环即可建立。
