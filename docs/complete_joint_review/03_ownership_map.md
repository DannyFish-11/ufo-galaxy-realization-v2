# 03 双仓 Ownership / Runtime / Orchestration 角色图谱

## 说明

本章对每个关键的 ownership 维度进行细化分析，说明每个维度由哪一端主导、共持还是动态转移。

---

## 1. Runtime Ownership（运行时所有权）

| 维度 | V2 侧 | Android 侧 | 所有权模式 |
|------|-------|-----------|------------|
| **V2 本地 runtime** | `core/local_agent_runtime.py::LocalAgentRuntime` | — | V2 独占 |
| **Android 本地 runtime** | — | `loop/LoopController.kt` | Android 独占 |
| **跨设备 runtime 生命周期** | `galaxy_gateway/android_bridge.py` 管理连接 | `runtime/RuntimeController.kt` 管理连接 | **双端共持**：两端各自管理自己端的 WS 连接状态 |
| **Delegated runtime unit** | 负责发起/追踪 `delegated_runtime_execution_tracker.py` | 负责执行 `agent/DelegatedRuntimeUnit.kt` | **职责分离**：V2 追踪，Android 执行 |
| **Attached session** | `core/attached_runtime_session_registry.py` 维护 session 注册表 | `runtime/AttachedRuntimeSession.kt` 持有本地 session 状态 | **双端共持**：各管一端视图 |

---

## 2. Orchestration Ownership（编排所有权）

| 维度 | V2 侧 | Android 侧 | 所有权模式 |
|------|-------|-----------|------------|
| **全局 routing authority** | `core/openclawd.py` (OpenClawd 唯一路由决策者) | — | **V2 独占** |
| **跨设备任务分配** | `galaxy_gateway/device_router.py::DeviceRouter` | — | **V2 独占** |
| **本地任务调度** | `core/scheduler.py` | `loop/LoopController.kt` | **各端独占本地** |
| **执行 chain 选择** | `core/cross_device_execution_chain.py` / `core/local_execution_chain.py` | `loop/LoopController.execute()` | **各端独占本地** |
| **takeover 发起** | `core/canonical_handoff_path.py` → `AgentBridge.handoff()` | — | **V2 独占** |
| **takeover 接受/拒绝** | — | `agent/TakeoverEligibilityAssessor.kt` | **Android 独占** |

---

## 3. Evidence Ownership（证据所有权）

Evidence = 执行过程中产生的可核查记录（execution signal、log、trace 等）

| 维度 | V2 侧 | Android 侧 | 所有权模式 |
|------|-------|-----------|------------|
| **执行步骤 log** | `core/task_logger.py` | `observability/GalaxyLogger` | **各端独占本地** |
| **Delegated execution signal** | `core/android_execution_signal_reconciler.py` 接收并 reconcile | `runtime/DelegatedExecutionSignalSink.kt` 发射 | **Android 产生，V2 reconcile** |
| **执行状态追踪** | `core/delegated_runtime_execution_tracker.py` 维护 | `runtime/DelegatedExecutionTracker.kt` 维护本地状态 | **双端各维护一份，通过 signal 对齐** |
| **Vision/Screenshot 证据** | `galaxy_gateway/android/handlers/vision.py` 接收 | `agent/EdgeExecutor.kt::ScreenshotProvider` 产生 | **Android 产生，V2 可接收** |

---

## 4. Truth Ownership（真相所有权）

Truth = 系统认定的"权威状态"（哪端持有的状态是最终正确的）

| 维度 | V2 侧 | Android 侧 | 所有权模式 |
|------|-------|-----------|------------|
| **任务最终状态** | `core/flow_level_truth_ownership.py` 持有 flow-level truth | `runtime/AndroidLocalTruthOwnershipCoordinator.kt` 持有本地 truth | **动态**：V2 全局 truth 权威，Android 本地 truth 权威，跨设备执行时 V2 最终裁决 |
| **设备状态** | `core/device_registry.py` 维护全局设备注册表 | `runtime/RuntimeController.kt` 维护自身状态 | **V2 为全局注册中心，Android 自身状态 Android 优先** |
| **Session truth** | `core/canonical_session_truth.py` | `runtime/AttachedRuntimeSession.kt` | **V2 全局 session authority，Android 本地 session 视图** |
| **多设备结果对齐** | `core/multi_device_truth_convergence.py` | — | **V2 独占**（收集多端结果后做 truth convergence） |

---

## 5. Result Convergence Ownership（结果收敛所有权）

Result = 执行完成后的结果对齐（谁来判定最终 result）

| 维度 | V2 侧 | Android 侧 | 所有权模式 |
|------|-------|-----------|------------|
| **单任务 result** | `core/goal_result_aggregator.py` | `agent/GoalExecutionPipeline.kt` 产生 LoopResult | **Android 产生，V2 聚合** |
| **Flow-level result convergence** | `core/flow_aware_result_convergence.py` | `runtime/AndroidFlowAwareResultConvergenceParticipant.kt` | **V2 主导，Android 参与** |
| **Handoff result** | `core/android_handoff_v2_response_ingress.py` 有 ingress 实现 | `protocol/AipModels.kt` 有 HANDOFF_ENVELOPE_V2_RESULT wire type | **路径存在但未接通（断层）** |
| **Reconciliation** | `core/android_execution_signal_reconciler.py` | `runtime/ReconciliationSignal.kt` 数据模型 | **wire 层缺失（断层）** |

---

## 6. Recovery Ownership（恢复所有权）

| 维度 | V2 侧 | Android 侧 | 所有权模式 |
|------|-------|-----------|------------|
| **V2 runtime restart** | `core/runtime_restart_recovery.py` | — | **V2 独占** |
| **Android 重连** | `core/attached_runtime_recovery_readiness.py` 等待 Android 重连 | `runtime/ReconnectRecoveryState.kt` 管理重连状态 | **各端负责自己端** |
| **Flow continuity** | `core/flow_continuity_coordinator.py` | `runtime/AndroidContinuityIntegration.kt` | **双端共持**：两端各有 continuity 模块 |
| **Delegated flow recovery** | `core/delegated_flow_recovery_coordinator.py` | `runtime/AndroidLifecycleRecoveryContract.kt` | **双端共持**：V2 协调，Android 执行恢复 |
| **Session continuity 记录** | `core/attached_runtime_session_registry.py` | `runtime/DurableSessionContinuityRecord.kt` | **双端各维护，尚无同步协议** |

---

## 7. Compat / Fallback Ownership（兼容/降级所有权）

| 维度 | V2 侧 | Android 侧 | 所有权模式 |
|------|-------|-----------|------------|
| **遗留协议兼容** | `galaxy_gateway/protocol/compat.py::parse_message_compat` | `protocol/AipModels.kt::MsgType.LEGACY_TYPE_MAP` | **双端各有 compat 层** |
| **compat surface 退出** | `core/compat_surface_retirement.py` | `runtime/CompatibilitySurfaceRetirementRegistry.kt` | **双端各持有** |
| **Legacy path blocking** | `core/compat_legacy_path_blocking_canonicalization.py` | `runtime/CompatLegacyBlockingDecision.kt` | **双端共持** |
| **执行降级（hybrid_degrade）** | 无专用降级 handler | `protocol/AipModels.kt::HYBRID_DEGRADE` 协议类型存在 | **Android 端降级，V2 无专用处理** |

---

## 8. Governance / Strategy Ownership（治理/策略所有权）

| 维度 | V2 侧 | Android 侧 | 所有权模式 |
|------|-------|-----------|------------|
| **Delegated flow readiness gate** | `core/delegated_flow_readiness_gate.py` 做最终裁决 | `runtime/DelegatedRuntimeReadinessEvaluator.kt` 产生 readiness artifact | **Android 评估，V2 裁决（但 wire 断层导致 V2 无法收到 Android readiness artifact）** |
| **Delegated runtime governance** | `core/delegated_flow_post_graduation_governance.py` | `runtime/DelegatedRuntimeGovernanceEvaluator.kt` | **同上：wire 断层** |
| **Strategy** | `core/delegated_flow_program_strategy.py` | `runtime/DelegatedRuntimeStrategyEvaluator.kt` | **同上：wire 断层** |
| **Acceptance** | `core/delegated_flow_acceptance_gate.py` | `runtime/DelegatedRuntimeAcceptanceEvaluator.kt` | **同上：wire 断层** |
| **Node governance** | `core/node_invocation_governance.py` | — | **V2 独占** |
| **运行时治理** | `core/runtime_governance/` 目录 | `runtime/RuntimeInvariantEnforcer.kt` | **各端独占本地** |

---

## 双仓 Ownership 概要图

```
┌──────────────────────────────────────────────────────────────────┐
│                         V2 (Python)                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ Routing Authority│  │ Truth Authority  │  │ Result Converge │  │
│  │ (OpenClawd)      │  │ (CanonicalSession│  │ (GoalAggregator)│  │
│  │ DeviceRouter     │  │  TruthOwnership) │  │ FlowAwareResult │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│  ┌─────────────────┐  ┌─────────────────┐                        │
│  │ Recovery Coord   │  │ Governance Gate  │                        │
│  │ FlowContinuity   │  │ ReadinessGate    │                        │
│  │ DelegatedRecovery│  │ AcceptanceGate   │                        │
│  └─────────────────┘  └─────────────────┘                        │
└──────────────────────────────────┬───────────────────────────────┘
                                   │ AIP v3 (WebSocket)
                                   │ ← task_assign / goal_execution / handoff
                                   │ → goal_execution_result / delegated_signal
                                   │ (断层：handoff_v2_result / reconciliation_signal)
┌──────────────────────────────────┴───────────────────────────────┐
│                       Android (Kotlin)                            │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ Local Runtime    │  │ Local Truth      │  │ Result Producer │  │
│  │ (LoopController) │  │ (AndroidLocal    │  │ (LoopResult)    │  │
│  │ AutonomousPipel. │  │  TruthOwnership) │  │ GoalExecPipeline│  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ Readiness Eval   │  │ Governance Eval  │  │ Recovery Actor  │  │
│  │ ReadinessEval    │  │ GovernanceEval   │  │ ReconnectState  │  │
│  │ AcceptanceEval   │  │ StrategyEval     │  │ ContinuityInteg │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

**关键判断**：
- Routing / Truth Authority / Result Convergence = **V2 独占或 V2 主导**
- Local Runtime / Local Truth / Readiness Evaluation / Recovery = **Android 独占本地**
- Compat / Legacy Path / Session Continuity = **双端共持，缺跨端同步协议**
- Governance evaluation artifacts 从 Android → V2 的传递 = **wire 断层，当前未闭环**
