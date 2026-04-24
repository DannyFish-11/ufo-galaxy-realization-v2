# 双仓职责边界审查

> 审查依据：逐模块代码阅读，不以文档为主。
> 重点区分：哪些状态/判断在 V2，哪些执行/事件在 Android，哪些是双端共持但职责不同。

---

## 1. V2 中心侧独占职责

### 1.1 Canonical 状态持有与权威判断

V2 是所有 canonical 状态的最终持有者。

| 模块 | 持有的权威状态 |
|------|--------------|
| `delegated_flow_entity.py` | 每个 delegated flow 的生命周期 phase（waiting/dispatching/running/suspended/completed/failed） |
| `delegated_runtime_execution_tracker.py` | 每个 dispatched 任务的跟踪记录（in-flight 状态） |
| `attached_runtime_session_registry.py` | 已附加的 Android runtime session 注册表 |
| `delegated_runtime_handoff_contract.py` | handoff contract 定义（目标设备、trace 参数、超时等） |
| `android_runtime_dispatch_binding.py` | dispatch binding 记录（binding_id → session_id + device_id + contract_id + tracker_id） |
| `flow_level_truth_ownership.py` | flow 级别的真值权威归属（V2 是最终仲裁者） |

### 1.2 跨端信号接收与规范化

V2 拥有所有从 Android 入站信号的规范化层：

| 模块 | 接收信号类型 |
|------|------------|
| `android_execution_signal_reconciler.py` | 旧格式 task_result/task_end/goal_execution_result 信号 |
| `android_delegated_signal_ingress.py` | 新格式 delegated_execution_signal（有 signal_id/emission_seq） |
| `android_participant_truth_ingress.py` | Android session snapshot/readiness/task_phase/runtime_state |
| `android_handoff_v2_response_ingress.py` | handoff_ack / handoff_result / handoff_failure |

### 1.3 发布门控与治理决策（单向持有）

以下模块的**最终决策权完全在 V2**，Android 侧只提供评估输入：

| 模块 | 决策类型 |
|------|---------|
| `delegated_flow_readiness_gate.py` | 五维度就绪汇总 → 是否可发布的统一判断 |
| `delegated_flow_acceptance_gate.py` | 毕业验收判断 → 是否 graduation 的最终裁决 |
| `delegated_flow_post_graduation_governance.py` | 持续合规监控 → 毕业后是否发生回归 |
| `delegated_flow_program_strategy.py` | 程序级演进评估 → 长期路线风险和方向 |
| `compat_legacy_path_blocking_canonicalization.py` | compat 影响阻断决策 → canonical path 保护 |

### 1.4 Operator/Audit 界面（V2 独占）

V2 持有面向 operator 的所有投影和 audit trail：

- `flow_level_operator_surface.py`：delegated flow + Android execution phase 的 canonical projection
- `replay_audit_persistence.py`：audit 事件的持久化
- `replay_foundation.py`：replay 基础设施
- `operator_override.py`：operator 手动覆盖

---

## 2. Android 端侧独占职责

### 2.1 本地执行（对 V2 透明）

Android 在本地执行层面是独立的。以下是 V2 无法直接访问或替代的 Android 本地能力：

| 模块 | 本地职责 |
|------|---------|
| `AutonomousExecutionPipeline.kt` | 自主执行管线：接收 task/goal_execution → 本地 LLM/工具调用 → 生成结果 |
| `EdgeExecutor.kt` | 边缘执行器：处理 UI 自动化、accessibility service 操作 |
| `LocalGoalExecutor.kt` | 本地 goal 执行逻辑 |
| `LocalInferenceRuntimeManager.kt` | 本地推理运行时（on-device LLM 管理） |

### 2.2 本地 Transport 控制（对 V2 不可见）

| 模块 | 本地职责 |
|------|---------|
| `GalaxyWebSocketClient.kt` | 连接管理、重连策略、心跳、离线队列；V2 侧看到的只是消息 |
| `OfflineTaskQueue.kt` | 离线时的任务结果缓冲（V2 侧不感知此层） |
| `TailscaleAdapter.kt` | 网络层适配 |
| `RuntimeController.kt` | 整个 Android runtime 的生命周期总控 |

### 2.3 本地真值维护（Android local-authoritative）

| 模块 | 本地真值内容 |
|------|------------|
| `AndroidLocalTruthOwnershipCoordinator.kt` | 维护 Android 本地执行真值，决定哪些真值是 local-only，哪些需上报 V2 |
| `AndroidParticipantRuntimeTruth.kt` | 参与者级别的本地 runtime 真值快照 |
| `LocalTruthEmitDecision.kt` | 决策：本地真值是否应该触发向 V2 的 canonical 状态更新 |

### 2.4 Android 独有 lifecycle 感知

| 模块 | 职责 |
|------|------|
| `AndroidAppLifecycleTransition.kt` | App 前/后台生命周期切换对 runtime 的影响 |
| `AppLifecycleParticipantBoundary.kt` | lifecycle 边界对参与者行为的约束 |
| `MediaTransportLifecycleBridge.kt` | 媒体传输与 App lifecycle 的绑定 |

---

## 3. 双端共持但职责不同

### 3.1 Readiness / Acceptance / Governance / Strategy 评估

这是最重要的双端共持但职责不同的维度。

| 维度 | V2 侧 | Android 侧 | 职责差异 |
|------|-------|-----------|---------|
| Readiness | `DelegatedFlowReadinessGate`（五维度汇总门控） | `DelegatedRuntimeReadinessEvaluator`（生成 `DeviceReadinessArtifact`） | V2 是最终门控，Android 是评估贡献者 |
| Acceptance | `DelegatedFlowAcceptanceGate`（graduation 最终裁决） | `DelegatedRuntimeAcceptanceEvaluator`（生成 `DeviceAcceptanceArtifact`） | 同上 |
| Governance | `DelegatedFlowPostGraduationGovernance`（持续合规） | `DelegatedRuntimePostGraduationGovernanceEvaluator`（生成 `DeviceGovernanceArtifact`） | 同上 |
| Strategy | `DelegatedFlowProgramStrategy`（演进策略） | `DelegatedRuntimeStrategyEvaluator`（生成 `DeviceStrategyArtifact`） | 同上 |

**关键差异**：V2 侧的 evaluator 是做**最终 verdict**（release/block/escalate），Android 侧的 evaluator 是做**本地视角的维度评估**并生成 artifact 上报。两者不是对称替代，是垂直分工。

### 3.2 Truth Ownership

| 层面 | V2 侧 | Android 侧 |
|------|-------|-----------|
| Flow 级别权威 | `FlowLevelTruthOwnership`（持有 canonical flow truth） | - |
| 本地执行权威 | 通过 reconciliation 更新 canonical 状态 | `AndroidLocalTruthOwnershipCoordinator`（持有本地权威） |
| 上报决策 | 等待入站信号 | `LocalTruthEmitDecision`（决定何时上报） |

**关键理解**：Android 对"本地执行的当前状态"拥有 local authority，V2 对"canonical flow truth"拥有 canonical authority。真值上报时，Android 是 source，V2 做 reconciliation。

### 3.3 Compat/Legacy 阻断

| 层面 | V2 侧 | Android 侧 |
|------|-------|-----------|
| 阻断决策 | `CompatLegacyPathBlockingCanonicalization`（阻断门控，authority） | `AndroidCompatLegacyBlockingParticipant`（参与者，贡献 compat influence 分类） |
| 退役注册 | `LegacyDispatchRegistry`、`LegacyPurgeRegistry` | `LongTailCompatibilityRegistry`（本地 long-tail compat 类型注册） |
| Retirement fence | `CompatSurfaceRetirement` | `CompatibilityRetirementFence`、`CompatibilitySurfaceRetirementRegistry` |

**关键差异**：V2 侧是阻断决策主体，Android 侧是 compat 状态上报方和本地 compat surface 注册方。

### 3.4 Continuity / Recovery

| 层面 | V2 侧 | Android 侧 |
|------|-------|-----------|
| 决策入口 | `FlowContinuityCoordinator`（统一 continuity 决策） | `AndroidContinuityIntegration`（本地 continuity 集成） |
| 持久化 | `DelegatedFlowPersistence`、`ReplayFoundation` | `DurableSessionContinuityRecord`、`DelegatedFlowContinuityRecord` |
| 恢复记录 | `RuntimeRestartRecovery` | `ContinuityRecoveryContext`、`RecoveryActivationCheckpoint` |

### 3.5 Result Convergence

| 层面 | V2 侧 | Android 侧 |
|------|-------|-----------|
| 聚合协调 | `FlowAwareResultConvergence`（并行结果聚合，duplicate 抑制） | `AndroidFlowAwareResultConvergenceParticipant`（本地结果贡献者） |
| Cross-runtime merge | `CrossRuntimeResultMerge`（contracts/ 层） | `FlowAwareResultConvergenceDecision`（本地收敛决策） |

---

## 4. 哪些模块表现出跨仓 contract

以下模块在代码结构上明确体现了跨仓 contract（两侧都有对应实现）：

| Contract 名称 | V2 侧 | Android 侧 | 状态 |
|-------------|-------|-----------|------|
| AIP v3 消息协议 | gateway 侧 MsgType 处理 | `AipModels.kt` MsgType enum | ✅ 完整对齐 |
| delegated_execution_signal 格式 | `android_delegated_signal_ingress.py` envelope | `DelegatedExecutionSignal.kt` | ✅ 完整对齐 |
| HandoffEnvelopeV2 格式 | `contracts/handoff_envelope_v2.py` | `HandoffEnvelopeV2.kt` | ✅ 完整对齐 |
| source_runtime_posture | `android_runtime_host.py` 分类逻辑 | `SourceRuntimePosture.kt` | ✅ 完整对齐 |
| Takeover contract | `delegated_runtime_handoff_contract.py` | `DelegatedHandoffContract.kt`、`TakeoverEnvelope.kt` | ✅ 基本对齐 |
| Readiness/Acceptance artifact | `DelegatedFlowReadinessGate` 读取维度信号 | `DeviceReadinessArtifact.kt`、`DelegatedRuntimeReadinessEvaluator` 生成 | ⚠️ 结构对齐，但推送路径待确认 |
| Governance artifact | `DelegatedFlowPostGraduationGovernance` | `DeviceGovernanceArtifact.kt` | ⚠️ 同上 |
| Truth reconciliation | `android_participant_truth_ingress.py` | `AndroidLocalTruthOwnershipCoordinator`、`LocalTruthEmitDecision` | ⚠️ 入站处理器存在，主动 push 路径待确认 |
| Cross-repo consistency gate | `cross_repo_consistency_gates.py` | `CrossRepoConsistencyGate.kt` | ⚠️ 双侧有实现，但运行时调用集成点未验证 |
