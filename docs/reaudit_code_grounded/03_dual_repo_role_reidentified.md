# 03 — 双仓角色重识别

> **审查方法**：不预设"V2 判断、Android 执行"。从代码中真实识别两端各自的 runtime / manager / orchestrator / controller / evidence / policy 能力，以及哪些判断由哪侧主导。

---

## 一、V2 侧能力识别

### 1.1 Orchestration / Routing 能力

| 模块 | 代码文件 | 能力描述 |
|------|---------|---------|
| 中央调度编排器 | `core/runtime/source_dispatch_orchestrator.py` | 任务分发决策主入口，根据 posture/policy 选择 local/android_bridge/remote_handoff |
| 系统编排器 | `core/system_orchestrator.py` | 系统级 orchestration 入口 |
| 能力编排器 | `core/capability_orchestrator.py` | 基于能力图谱的编排 |
| E2E 编排器 | `core/e2e_orchestrator.py` | 端到端编排 |
| 设备编排器 | `core/device_orchestrator.py` | 设备层编排 |
| Task Graph Runtime | `core/task_graph_runtime.py` | 任务图运行时 |
| Canonical Dispatch Chain | `core/canonical_task_dispatch_chain.py` | canonical 分发链 |

### 1.2 Runtime 能力

| 模块 | 代码文件 | 能力描述 |
|------|---------|---------|
| 本地 Agent Runtime | `core/local_agent_runtime.py` | V2 自身作为 device-side 执行沙盒（三模式 loop） |
| 主循环 L4 增强 | `core/galaxy_main_loop_l4_enhanced.py` | 系统主 runtime loop |
| Constellation Runtime | `core/constellation_runtime.py` | 节点星群 runtime |
| Attached Runtime Session | `core/attached_runtime_session.py` + `_registry.py` | 附加 runtime 会话管理 |
| Attached Runtime Recovery | `core/attached_runtime_recovery_readiness.py` | 附加 runtime 恢复就绪 |
| Android Runtime Host | `core/android_runtime_host.py` | 识别 Android 是否是 full/partial runtime host |
| Android Runtime Dispatch Binding | `core/android_runtime_dispatch_binding.py` | Android runtime 分发绑定 |

### 1.3 Truth / State Authority 能力

| 模块 | 代码文件 | 能力描述 |
|------|---------|---------|
| Flow Level Truth Ownership | `core/flow_level_truth_ownership.py` | Flow 级别真值权威模型 |
| Canonical Session Truth | `core/canonical_session_truth.py` | canonical 会话真值 |
| Truth Source Lock | `core/truth_source_lock.py` | 真值源锁定 |
| Truth Integration Layer | `core/truth_integration_layer.py` | 真值集成层 |
| Truth Conflict Enforcement | `core/truth_conflict_enforcement.py` | 真值冲突执行 |
| Android Participant Truth Ingress | `core/android_participant_truth_ingress.py` | Android 真值进入 V2 canonical 状态的入口 |

### 1.4 Governance / Readiness Gate 能力

| 模块 | 代码文件 | 能力描述 |
|------|---------|---------|
| Delegated Flow Readiness Gate | `core/delegated_flow_readiness_gate.py` | 就绪验收门控 |
| Delegated Flow Acceptance Gate | `core/delegated_flow_acceptance_gate.py` | 毕业验收门控 |
| Delegated Flow Post Graduation Governance | `core/delegated_flow_post_graduation_governance.py` | 持续合规治理 |
| Delegated Flow Program Strategy | `core/delegated_flow_program_strategy.py` | 演进策略 |
| Delegated Flow Recovery Coordinator | `core/delegated_flow_recovery_coordinator.py` | 恢复协调 |

### 1.5 Replay / Recovery / Continuity 能力

| 模块 | 代码文件 | 能力描述 |
|------|---------|---------|
| Flow Continuity Coordinator | `core/flow_continuity_coordinator.py` | continuity 事件统一决策入口 |
| Replay Foundation | `core/replay_foundation.py` | replay 基础层 |
| Replay Audit Persistence | `core/replay_audit_persistence.py` | replay 审计持久化 |
| Runtime Restart Recovery | `core/runtime_restart_recovery.py` | runtime 重启恢复 |

---

## 二、Android 侧能力识别

### 2.1 Agent Runtime 能力（独立本地能力）

| 模块 | 代码文件 | 能力描述 |
|------|---------|---------|
| 自主执行管线 | `agent/AutonomousExecutionPipeline.kt` | 完整自主 agent 执行管线，不依赖 V2 |
| 本地目标执行器 | `agent/LocalGoalExecutor.kt` | 本地 goal 执行，不依赖 V2 |
| 本地协作 agent | `agent/LocalCollaborationAgent.kt` | 本地协作语义 |
| 边缘执行器 | `agent/EdgeExecutor.kt` | 边缘节点执行能力 |
| Agent Runtime Bridge | `agent/AgentRuntimeBridge.kt` | 将任务与本地 agent runtime 绑定 |
| 本地循环执行器 | `local/LocalLoopExecutor.kt` | 本地 ReAct-style agent loop |
| 规划降级梯 | `local/PlannerFallbackLadder.kt` | 多级本地规划降级 |
| grounding 降级梯 | `local/GroundingFallbackLadder.kt` | 多级本地 grounding 降级 |
| 停滞检测器 | `local/StagnationDetector.kt` | 检测 loop 停滞并自处理 |

### 2.2 Delegated Runtime 能力（可与 V2 协同）

| 模块 | 代码文件 | 能力描述 |
|------|---------|---------|
| 委托 Runtime 单元 | `agent/DelegatedRuntimeUnit.kt` | 接收 V2 handoff 后的完整执行单元 |
| 委托接管执行器 | `agent/DelegatedTakeoverExecutor.kt` | takeover 场景主动接管执行 |
| 接管资格评估器 | `agent/TakeoverEligibilityAssessor.kt` | **本地**判断是否具备接管资格 |
| 委托 handoff 合约 | `agent/DelegatedHandoffContract.kt` | Android 侧持有 handoff 合约语义 |
| HandoffContractValidator | `agent/HandoffContractValidator.kt` | **本地**验证 handoff 合约合规性 |
| HandoffEnvelopeV2 | `agent/HandoffEnvelopeV2.kt` | HandoffEnvelopeV2 消费与处理 |
| DelegatedRuntimeReceiver | `agent/DelegatedRuntimeReceiver.kt` | 委托 runtime 消息接收器 |

### 2.3 Evidence / Policy 能力（Android 本地自评估）

这些是 Android 侧独立的评估层（代码确认存在于 Android 仓库）：

| 评估器 | Artifact | 说明 |
|-------|---------|------|
| `DelegatedRuntimeReadinessEvaluator.kt` | `DeviceReadinessArtifact.kt` | 本地 readiness 评估，产出 artifact |
| `DelegatedRuntimeAcceptanceEvaluator.kt` | `DeviceAcceptanceArtifact.kt` | 本地 acceptance 评估，产出 artifact |
| `DelegatedRuntimePostGraduationGovernanceEvaluator.kt` | `DeviceGovernanceArtifact.kt` | 本地 governance 评估，产出 artifact |
| `DelegatedRuntimeStrategyEvaluator.kt` | `DeviceStrategyArtifact.kt` | 本地 strategy 评估，产出 artifact |

**⚠️ 关键发现**：这四层评估器在 Android 本地**产出 artifact**，但由于 AipModels.kt MsgType 枚举缺少 `reconciliation_signal` 类型，这些 artifact **无法通过 wire 到达 V2 readiness gate**。即：Android 本地具备评估能力（半个闭环），但 V2 侧的 gate 无法消费 Android 的评估结果（另半个断层）。

### 2.4 Transport / Recovery 能力

| 模块 | 代码文件 | 能力描述 |
|------|---------|---------|
| WebSocket 客户端 | `network/GalaxyWebSocketClient.kt` | 所有跨端消息的统一出口，有重连策略 |
| 离线任务队列 | `network/OfflineTaskQueue.kt` | 离线期间任务缓存，重连后回放 |
| 任务取消注册表 | `agent/TaskCancelRegistry.kt` | 本地维护取消状态 |

---

## 三、哪些判断是中心侧（V2）主导

| 判断类型 | 代码证据 | 位置 |
|---------|---------|------|
| 分发路由决策 | `SourceDispatchOrchestrator._determine_dispatch_mode()` | V2 |
| Canonical handoff 合约权威 | `DelegatedRuntimeHandoffContract.py` | V2 |
| Flow 级别真值仲裁 | `FlowLevelTruthOwnership.py` | V2 |
| Delegated flow 四层 gate（readiness/acceptance/governance/strategy）| V2 `core/delegated_flow_*.py` | V2 |
| Legacy path 阻断（compat canonicalization） | `CompatLegacyPathBlockingCanonicalization.py` | V2 |
| Replay/audit 持久化 | `ReplayAuditPersistence.py` | V2 |
| Continuity 协调入口 | `FlowContinuityCoordinator.py` | V2 |

---

## 四、哪些判断是设备侧（Android）本地完成

| 判断类型 | 代码证据 | 位置 |
|---------|---------|------|
| Takeover 资格评估 | `TakeoverEligibilityAssessor.kt` | Android 本地 |
| Handoff 合约合规验证 | `HandoffContractValidator.kt` | Android 本地 |
| 本地 loop readiness 判断 | `LocalLoopReadiness.kt` | Android 本地 |
| Readiness/Acceptance/Governance/Strategy artifact 生成 | 四层评估器 | Android 本地 |
| 本地 goal 是否执行的规划决策 | `PlannerFallbackLadder.kt` | Android 本地 |
| 停滞检测与恢复 | `StagnationDetector.kt` | Android 本地 |
| 离线任务缓存策略 | `OfflineTaskQueue.kt` | Android 本地 |
| source_runtime_posture 声明 | payload 字段 | Android 本地写入 |

---

## 五、双端对等存在但落点不同的能力

| 能力语义 | V2 侧 | Android 侧 | 落点差异 |
|---------|-------|-----------|---------|
| Agent loop（ReAct） | `LocalAgentRuntime._execute_react()` | `LocalLoopExecutor.kt` | 均本地执行，但 V2 侧是"V2 节点本地"，Android 侧是"设备节点本地" |
| Readiness 评估 | `DelegatedFlowReadinessGate.py`（gate 层） | `DelegatedRuntimeReadinessEvaluator.kt`（artifact 层）| V2 做 gate 决策，Android 做本地 artifact；中间缺 wire |
| Handoff 合约 | `DelegatedRuntimeHandoffContract.py`（合约权威） | `DelegatedHandoffContract.kt`（本地消费）| V2 是合约权威，Android 是合约消费者 |
| Takeover 能力 | `core/runtime/target_takeover.py`（V2 侧 takeover 协调）| `DelegatedTakeoverExecutor.kt`（Android 实际接管执行）| 协调在 V2，执行在 Android |
| Recovery/reconnect | `FlowContinuityCoordinator.py` | `OfflineTaskQueue.kt` + GalaxyWebSocketClient 重连 | 协调决策在 V2，transport 恢复在 Android |

---

## 六、体现 agent-like autonomy 的模块

**Android 侧（最明显的 agent 自治特征）：**
1. `AutonomousExecutionPipeline.kt` — 全自主执行管线
2. `LocalGoalExecutor.kt` — 本地独立 goal 执行
3. `TakeoverEligibilityAssessor.kt` — 本地自主判断接管资格
4. `PlannerFallbackLadder.kt` — 本地多级降级规划
5. `StagnationDetector.kt` — 本地检测并处理停滞
6. `OfflineTaskQueue.kt` — 离线自主缓存与回放

**V2 侧（agent 自治特征）：**
1. `LocalAgentRuntime.py` — V2 节点本地 agent loop
2. `galaxy_main_loop_l4_enhanced.py` — 自驱动主 runtime loop
3. `HealingEngine.py` — 自愈能力
4. `ProactiveSensingEngine.py` — 主动感知

**综合结论**：两端均具备 agent-like autonomy，不是单纯的 server/client 或 master/worker 关系。
