# 系统整体定位审查

> 审查方法：从真实代码结构反推，不以文档为依据。
> 代码来源：`core/`、`galaxy_gateway/`、`contracts/`（V2）；`com.ufo.galaxy.runtime/`、`com.ufo.galaxy.network/`、`com.ufo.galaxy.protocol/`、`com.ufo.galaxy.agent/`（Android）

---

## 1. 系统到底是什么（代码级定义）

### V2 中心侧（Python / FastAPI + WebSocket gateway）

从代码结构反推，V2 是：

1. **执行编排中心**：持有 `delegated_flow_entity.py`（flow 生命周期）、`delegated_runtime_execution_tracker.py`（in-flight 跟踪）、`delegated_runtime_handoff_contract.py`（handoff 合同）。
2. **真值权威仲裁层**：`flow_level_truth_ownership.py` 定义了 flow 级别的真值权威模型；`android_participant_truth_ingress.py` 提供 Android 真值进入 V2 canonical 状态的规范入口。
3. **结果聚合与收敛层**：`flow_aware_result_convergence.py` 提供 flow 感知的并行结果聚合。
4. **compat/legacy 治理门**：`compat_legacy_path_blocking_canonicalization.py` 是所有 compat 影响进入 canonical 决策面前的唯一阻断门控。
5. **发布决策层**：`delegated_flow_readiness_gate.py`（就绪）、`delegated_flow_acceptance_gate.py`（毕业验收）、`delegated_flow_post_graduation_governance.py`（持续合规）、`delegated_flow_program_strategy.py`（演进策略）形成四层发布判断链。
6. **可观测性与 operator 界面**：`flow_level_operator_surface.py`、`replay_audit_persistence.py`、`replay_foundation.py`。
7. **Continuity/Recovery 协调**：`flow_continuity_coordinator.py` 是 continuity 事件的统一决策入口，整合了 session 注册、执行跟踪、持久化恢复等子系统。

**V2 是系统的 canonical orchestration 中心**，持有所有跨端权威状态，是 delegated path 合规性的最终仲裁者。

### Android 端侧（Kotlin / Android App）

从代码结构反推，Android 是：

1. **Delegated runtime 执行端**：`DelegatedRuntimeUnit.kt`（执行单元）、`AutonomousExecutionPipeline.kt`（自主管线）、`EdgeExecutor.kt`（边缘执行器）、`DelegatedTakeoverExecutor.kt`（takeover 执行器）。
2. **信号上报端**：`DelegatedExecutionSignal.kt` + `GalaxyWebSocketClient.kt` 负责将执行生命周期信号（ACK/PROGRESS/RESULT/TIMEOUT/CANCELLED）通过 `delegated_execution_signal` 消息类型上报 V2。
3. **本地真值持有端**：`AndroidLocalTruthOwnershipCoordinator.kt` 在 Android 本地维护执行真值，`AndroidParticipantRuntimeTruth.kt` 持有参与者级别的本地 runtime 真值。
4. **自评估与自报告端**：Android 有自己的 readiness/acceptance/governance/strategy 评估器（`DelegatedRuntimeReadinessEvaluator.kt`、`DelegatedRuntimeAcceptanceEvaluator.kt`、`DelegatedRuntimePostGraduationGovernanceEvaluator.kt`、`DelegatedRuntimeStrategyEvaluator.kt`），会生成 artifact（`DeviceReadinessArtifact.kt`、`DeviceAcceptanceArtifact.kt`、`DeviceGovernanceArtifact.kt`、`DeviceStrategyArtifact.kt`）上报 V2。
5. **Transport backbone**：`GalaxyWebSocketClient.kt` 是所有跨端消息的唯一出口，持有离线队列（`OfflineTaskQueue.kt`）和重连策略。

**Android 是系统的 delegated runtime 端**，负责本地执行、本地真值维护、信号上报，并通过 WebSocket 与 V2 保持持续会话。

---

## 2. delegated path / canonical path 的真实含义

基于代码分析：

- **canonical path**：通过 V2 中心编排、Android 本地执行、信号回传 V2、V2 聚合结果的完整 end-to-end 路径。与之对应的是**旧 legacy path**（直接调用、无 handoff contract、无 execution tracker）。
- **delegated flow**：一个 `DelegatedFlowEntity`（V2 侧）+ 对应 `DelegatedRuntimeUnit`（Android 侧）的绑定执行单元。V2 发起 handoff，Android 接受并执行，执行信号回流 V2 进行 phase 推进。
- **delegated runtime**：Android 作为"first-class runtime host"（`AndroidRuntimeHostRole.FULL_RUNTIME_HOST`）加入 V2 执行织物的状态。与单纯"connected device"区别在于是否有 `source_runtime_posture == "join_runtime"` 的声明。

---

## 3. 系统更像什么（代码语义层面）

| 维度 | 真实代码支撑 | 判断 |
|------|------------|------|
| 执行编排 | `DelegatedFlowEntity`、`CanonicalDispatchChain`、`DelegatedRuntimeUnit` | ✅ 有实质实现 |
| 状态对齐 | `FlowLevelTruthOwnership`、`AndroidLocalTruthOwnershipCoordinator`、`ReconciliationSignal` | ✅ 双端均有实质实现 |
| 任务代理 | `DelegatedTakeoverExecutor`、`TakeoverEligibilityAssessor`、`HandoffEnvelopeV2` | ✅ 基本接通 |
| 运行时治理 | `DelegatedFlowReadinessGate`、`DelegatedFlowAcceptanceGate`、`DelegatedFlowPostGraduationGovernance`、`DelegatedFlowProgramStrategy` | ⚠️ 框架已建，实时信号流是否闭合待验证 |
| Continuity/Recovery | `FlowContinuityCoordinator`、`AndroidContinuityIntegration`、`DelegatedFlowContinuityRecord`、`OfflineTaskQueue` | ✅ 双端均有实质实现 |
| Compat/Legacy 治理 | `CompatLegacyPathBlockingCanonicalization`、`AndroidCompatLegacyBlockingParticipant`、`LongTailCompatibilityRegistry` | ✅ 阻断逻辑双端均有 |
| Operator/Audit 可观测 | `FlowLevelOperatorSurface`、`ReplayAuditPersistence`、`RuntimeObservabilityMetadata` | ⚠️ V2 侧有，Android 侧 observability 以 Artifact 形式存在但集成点不明确 |

**综合判断**：
> 这个系统是一套**以 delegated canonical path 为核心的跨端任务执行与治理平台**，同时具备执行编排、状态对齐、任务代理和运行时治理能力。不是单纯的 demo 或 adapter，而是有清晰架构意图并且已经建立了相当完整的骨架的系统。

---

## 4. 当前系统的真实边界

### 已经明确属于系统范围（代码有实质实现）

- WebSocket 跨端 transport（完整接通）
- AIP v3 消息协议（双端完全对齐）
- 设备注册 + posture 声明（完整接通）
- 基础任务执行（task_submit/task_assign/task_result）（完整接通）
- Goal 执行（goal_execution/goal_execution_result）（完整接通）
- Delegated execution signal 上报（PR-16，双端接通）
- HandoffEnvelopeV2 native 消费（PR-H，双端接通）
- 离线任务队列（Android 侧有 OfflineTaskQueue）
- Session 附加与 continuity 协调（双端有实质实现）
- Readiness/Acceptance/Governance/Strategy 评估框架（双端均有评估器）

### 尚不明确完全闭合（骨架存在但信号流待验证）

- V2 四层发布决策（readiness/acceptance/governance/strategy）与 Android 自评估 artifact 的**实时连接和触发机制**
- Android 侧 governance/strategy evaluator 产出如何主动推送到 V2（只看到评估器存在，未看到 push 路径代码）
- Truth reconciliation 的完整触发链（入站模块存在，但触发时机的 gateway 集成未完整验证）
- Legacy path 在生产代码中的实际 retirement 状态

### 明确不在当前范围（代码注明 minimal-compat 或 TODO）

- RELAY/FORWARD/REPLY（AipModels.kt 注明：minimal-compat — logged only）
- RAG_QUERY/CODE_EXECUTE（AipModels.kt 注明：sandbox TODO）
- SESSION_MIGRATE（AipModels.kt 注明：degrade/reject reply; full migration TODO）
- HYBRID_EXECUTE 完整实现（minimal-compat stub）
