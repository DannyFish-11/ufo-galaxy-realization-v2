# 双仓 Contract / Signal 闭环审查

> 审查依据：逐模块代码阅读，识别双仓之间实际接通的 contract 和 signal。
> 重点区分：真实接通 vs 名字相似但未真正对接 vs 只有一侧声明。

---

## 1. V2 期待 Android 提供的 signal / artifact / event

从 V2 代码中明确可以看到，以下是 V2 已经建立了接收处理器的信号类型：

### 1.1 执行生命周期信号（明确期待）

| 信号名 | V2 处理模块 | 期待内容 |
|--------|------------|---------|
| `delegated_execution_signal` | `android_delegated_signal_ingress.py` | signal_kind(ack/progress/result/timeout/cancelled) + signal_id + emission_seq + 9 个 identity 字段 |
| `task_result` | `android_execution_signal_reconciler.py` | 旧格式：status + task_id + device_id + payload |
| `task_end` | `android_execution_signal_reconciler.py` | 旧格式：execution 结束 |
| `goal_execution_result` | `android_execution_signal_reconciler.py` | goal 执行结果 |
| `error` | `android_execution_signal_reconciler.py` | 错误报告 |

### 1.2 Handoff 响应信号（明确期待）

| 信号名 | V2 处理模块 | 期待内容 |
|--------|------------|---------|
| `handoff_ack` | `android_handoff_v2_response_ingress.py` | 接收确认，handoff_id 关联 |
| `handoff_result` | `android_handoff_v2_response_ingress.py` | 执行成功 + result_summary |
| `handoff_failure` | `android_handoff_v2_response_ingress.py` | 执行失败 + error_detail |
| `handoff_envelope_v2_result` | `android_handoff_v2_response_ingress.py` | HandoffEnvelopeV2 native 消费结果 |

### 1.3 Truth / 参与者状态信号（明确期待）

| 信号名 | V2 处理模块 | 期待内容 |
|--------|------------|---------|
| session_snapshot 类型消息 | `android_participant_truth_ingress.py` | AndroidParticipantTruthKind.session_snapshot |
| readiness_assessment 类型消息 | `android_participant_truth_ingress.py` | AndroidParticipantTruthKind.readiness_assessment |
| task_phase 类型消息 | `android_participant_truth_ingress.py` | AndroidParticipantTruthKind.task_phase |
| runtime_state 类型消息 | `android_participant_truth_ingress.py` | AndroidParticipantTruthKind.runtime_state |

### 1.4 设备注册 / 心跳信号（明确期待）

| 信号名 | V2 处理模块 | 期待内容 |
|--------|------------|---------|
| `device_register` | gateway handler | device_id + platform + supported_actions + capability_schema + source_runtime_posture |
| `capability_report` | gateway handler | 设备能力更新 |
| `heartbeat` | gateway handler | device_id + route_mode + reconnect_attempts |
| `takeover_response` | gateway handler | takeover 接受/拒绝 |

---

## 2. Android 实际提供的 signal / artifact / event

从 Android 代码中明确可以看到，以下信号有实际发送路径：

### 2.1 已实际接通（有 sendJson/emit 代码路径）

| 信号名 | Android 发送模块 | 发送条件 |
|--------|----------------|---------|
| `device_register` | `GalaxyWebSocketClient.sendHandshake()` | WebSocket onOpen 时自动发送 |
| `heartbeat` | `GalaxyWebSocketClient` 定时器 | 每 30 秒 |
| `task_result` | `GalaxyWebSocketClient.sendJson()` via InputRouter | 任务执行完成 |
| `goal_execution_result` | 执行层回调 → sendJson | goal 执行结束 |
| `cancel_result` | 取消流程 → sendJson | 任务取消完成 |
| `delegated_execution_signal` | PR-16，`DelegatedExecutionSignal` + sendJson | delegated 执行各生命周期点 |
| `handoff_ack/result/failure` | `DelegatedRuntimeReceiver` | handoff_envelope_v2 处理结果 |
| `handoff_envelope_v2_result` | 专用 handler | HandoffEnvelopeV2 native 消费结果 |
| `mesh_join/leave/result` | mesh 参与流程 | mesh session 生命周期 |
| `takeover_response` | `DelegatedTakeoverExecutor` | takeover_request 响应 |
| `diagnostics_payload` | 诊断信息 | 任务失败分类（Loop 1/2） |
| `peer_exchange` | PR-35 | peer 能力交换 |
| `peer_announce` ACK | PR-36 | 对 peer_announce 的 ACK |
| `coord_sync` ACK | PR-35 | 对 coord_sync 的 sequence-aware ACK |

### 2.2 有模型但尚无完整发送路径（stub/minimal-compat）

| 信号名 | Android 状态 |
|--------|------------|
| `hybrid_result` | 模型存在，send path 存在，但 hybrid executor 未完整实现 |
| `hybrid_degrade` | 模型存在，send path 存在，但触发条件依赖未完成的 hybrid 执行器 |
| `rag_result` | 模型存在，send path 存在，但 RAG pipeline TODO |
| `code_result` | 模型存在，send path 存在，但 sandbox TODO |

### 2.3 Android 侧有 artifact 生成但上报路径已确认断层

| Artifact | 生成模块 | 上报路径状态 |
|----------|---------|------------|
| `DeviceReadinessArtifact` | `DelegatedRuntimeReadinessEvaluator` | ❌ 设计通过 `ReconciliationSignal.PARTICIPANT_STATE` → `RuntimeController` 转发，但 `AipModels.kt` MsgType enum 中**无对应消息类型**，wire 传输层缺失 |
| `DeviceAcceptanceArtifact` | `DelegatedRuntimeAcceptanceEvaluator` | ❌ 同上 |
| `DeviceGovernanceArtifact` | `DelegatedRuntimePostGraduationGovernanceEvaluator` | ❌ 同上 |
| `DeviceStrategyArtifact` | `DelegatedRuntimeStrategyEvaluator` | ❌ 同上 |

**具体断层原因（代码验证）**：`ReconciliationSignal.kt`（PR-51）定义了完整的 Android→V2 reconciliation signal 内部模型，并在 `DelegatedRuntimeReadinessEvaluator` 中明确声明了"forwarded via reconciliation signal channel"的设计意图，但 `AipModels.kt` 的 `MsgType` enum 在最新代码中**不包含 `reconciliation_signal` 或 `participant_state` 消息类型**，这意味着 `ReconciliationSignal` 尚未被序列化到 AIP v3 wire 格式并通过 `GalaxyWebSocketClient` 发送到 V2。

---

## 3. 哪些地方形成了明确对接（真实闭环）

| Contract 名称 | 闭环状态 | 说明 |
|-------------|---------|------|
| AIP v3 消息协议（MsgType enum 完整对齐） | ✅ 完整闭环 | Android `AipModels.kt` MsgType 与 V2 gateway handler 完全对应 |
| 设备注册（device_register + source_runtime_posture） | ✅ 完整闭环 | Android 发送 → V2 `android_runtime_host.py` 分类处理 |
| 心跳（heartbeat / heartbeat_ack） | ✅ 完整闭环 | 双向有发送和处理代码 |
| 基础任务执行（task_submit/assign/result） | ✅ 完整闭环 | 双端代码完整，是最成熟的路径 |
| Goal 执行（goal_execution/result） | ✅ 完整闭环 | 双端代码完整 |
| Delegated execution signal（新格式） | ✅ 完整闭环 | PR-16 双端接通（已代码验证）：Android → GalaxyWebSocketClient → V2 android_bridge.py（94行 import handle_delegated_execution_signal）→ galaxy_gateway/android/handlers/delegated_signal.py → core/android_delegated_signal_ingress.py → DelegatedExecutionTrackingRecord phase 推进 → SourceDispatchOrchestrator |
| HandoffEnvelopeV2 native 消费（下行） | ✅ 完整闭环 | PR-H 下行接通：V2 发 handoff_envelope_v2 → Android GalaxyConnectionService 接收执行 |
| HandoffEnvelopeV2 native 消费（上行 response） | ❌ 已确认断层 | Android 有 handoff_envelope_v2_result 消息（AipModels.kt），V2 有 android_handoff_v2_response_ingress.py，但 gateway android/handlers/ 中无对应 handler 文件，V2 gateway 路由层未挂接此 handler |
| Takeover request/response 协议 | ✅ 基本接通 | V2 发 takeover_request → Android DelegatedTakeoverExecutor 处理 → 回报 takeover_response；PR-5 注明"full takeover executor deferred"，核心路径已接通 |
| 离线任务队列（offline replay） | ✅ Android 侧完整 | OfflineTaskQueue 缓冲 + 重连 flush；V2 侧接收同上述路径 |
| 指数退避重连策略 | ✅ Android 侧完整 | GalaxyWebSocketClient 有完整重连实现 |
| legacy type 兼容映射 | ✅ 完整对齐 | AipModels.kt LEGACY_TYPE_MAP 与 V2 android_execution_signal_reconciler normalize_android_message_to_signal_kind 对应 |

---

## 4. 名字相似但未真正接通的地方

### 4.1 readiness/acceptance/governance/strategy — "评估存在，AIP 传输层断层"

| 现象 | 细节 |
|------|------|
| Android 有四层评估器和 artifact 结构 | `DelegatedRuntimeReadinessEvaluator` 等生成完整 artifact |
| 设计意图明确 | 评估器代码注明 "forwarded via reconciliation signal channel" + `INTEGRATION_RUNTIME_CONTROLLER` |
| `ReconciliationSignal.kt`（PR-51）已定义结构 | 7 种 signal kind，含 `PARTICIPANT_STATE` 和 `RUNTIME_TRUTH_SNAPSHOT` |
| **AipModels.kt MsgType enum 无对应消息类型（已验证）** | 翻查 `AipModels.kt` 全文，`MsgType` enum 最后一个条目是 `HANDOFF_ENVELOPE_V2`，无 `reconciliation_signal` 类型 |
| **判断**：`ReconciliationSignal` 是完整设计好的内部 DTO，但其 AIP wire 层序列化和发送代码尚未建立 | |

### 4.2 HandoffEnvelopeV2 response — "下行接通，上行 response 断层"

| 现象 | 细节 |
|------|------|
| 下行（V2→Android）已接通 | V2 发 `handoff_envelope_v2`，Android 在 `GalaxyConnectionService` 有专用 handler（AipModels 注明 "pr-h — promoted"） |
| 上行 response（Android→V2）断层（已验证） | `AipModels.kt` 有 `HANDOFF_ENVELOPE_V2_RESULT` 和 `HandoffEnvelopeV2ResultPayload`；`core/android_handoff_v2_response_ingress.py` 有处理器；但 `galaxy_gateway/android/handlers/` 目录中无对应 handler 文件，gateway 路由层未挂接 |
| **判断**：这是一个清晰的单向接通、上行 response 缺失的断层 | |

### 4.3 compat/legacy blocking — "双端都有 participant，但 V2 阻断决策是否基于 Android 信号待确认"

| 现象 | 细节 |
|------|------|
| V2 `CompatLegacyPathBlockingCanonicalization` 有完整的 5 种决策 | 但这些决策基于什么输入不完全明确 |
| Android `AndroidCompatLegacyBlockingParticipant` 标识为 compat 参与者 | 但通过什么消息类型向 V2 上报 compat influence 未找到明确代码 |
| **判断**：双端有 compat 治理骨架，但 Android → V2 的 compat signal 上报路径是弱连接 | |

### 4.3 Cross-repo consistency gate — "存在但未见运行时集成"

| 现象 | 细节 |
|------|------|
| V2 有 `cross_repo_consistency_gates.py` | 定义了跨仓一致性检查 |
| Android 有 `CrossRepoConsistencyGate.kt` | 有 26KB 的实现 |
| **判断**：双端都有实现，但没有找到运行时触发它的入口（可能是 CI/build-time gate，不是 runtime 路径） | |

### 4.4 Truth reconciliation 触发 — "处理器有，触发路径弱"

| 现象 | 细节 |
|------|------|
| V2 `android_participant_truth_ingress.py` 定义了 8 种 truth 类型处理 | 处理逻辑完整 |
| Android `LocalTruthEmitDecision.kt` 有本地真值上报决策 | 决策模块存在 |
| **但**：Android 中什么情况下发出哪种 truth 类型消息，是否有专用消息类型，这一路径在代码中不够清晰 | |

---

## 5. 哪些 readiness / acceptance / governance / strategy 语义仍停留在一侧

| 语义 | V2 侧状态 | Android 侧状态 | 跨仓闭环状态 |
|------|---------|--------------|------------|
| Readiness 最终 verdict | ✅ 有完整门控，产出 6 种 verdict | ⚠️ 有评估器 + artifact，推送路径不明确 | ⚠️ 框架对齐，信号流断层 |
| Acceptance graduation verdict | ✅ 有完整门控，产出 graduation_accepted/rejected | ⚠️ 有评估器 + artifact，推送路径不明确 | ⚠️ 框架对齐，信号流断层 |
| Post-graduation governance | ✅ 有持续监控框架，产出 5 种 violation/compliant | ⚠️ 有评估器 + artifact，推送路径不明确 | ⚠️ 框架对齐，信号流断层 |
| Program strategy evolution | ✅ 有策略评估层，产出 5 种 risk/on-track | ⚠️ 有评估器 + artifact，推送路径不明确 | ⚠️ 框架对齐，信号流断层 |
| Compat/legacy blocking decision | ✅ V2 有完整阻断引擎 | ⚠️ Android 有 compat participant，上报路径弱 | ⚠️ Android→V2 的 compat signal 路径不明确 |
| Truth alignment（基础执行真值） | ✅ 有 reconciliation 处理器 | ✅ 有本地真值 + LocalTruthEmitDecision | ⚠️ 触发路径待验证 |
| Truth alignment（readiness 真值） | ✅ 期待 readiness_assessment 类型 | ⚠️ 有 DeviceReadinessArtifact 但无专用消息类型 | ❌ 断层明显 |

---

## 6. 总结：contract 闭环分级

### 已形成明确闭环（可以放心依赖）
- AIP v3 传输协议（完整对齐）
- 基础任务执行信号（task_submit → task_result）
- Goal 执行信号（goal_execution → goal_execution_result）
- Delegated execution signal（新格式，PR-16）
- HandoffEnvelopeV2 native 消费（PR-H）
- 设备注册 + source_runtime_posture
- 心跳保活
- 离线任务队列

### 部分接通（一侧完整，gateway 挂接缺失）
- HandoffEnvelopeV2 上行 response（android_handoff_v2_response_ingress 存在，但 gateway handler 缺失）
- Takeover execution（协议已接通，takeover executor 标注部分延迟）
- Continuity/recovery（双端均有骨架，协调消息触发时机待验证）

### 骨架对齐但 AIP wire 层断层（需要专门 PR 建立传输路径）
- ReconciliationSignal AIP wire 层（影响所有 readiness/acceptance/governance/strategy artifact 上报）
- Android → V2 compat influence 上报路径（依赖 ReconciliationSignal 解决）
- 双端 cross-repo consistency gate 的运行时集成（CrossRepoConsistencyGate 有实现，但无运行时挂接）
