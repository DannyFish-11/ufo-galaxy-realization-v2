# 双仓 Ownership / Runtime / Orchestration 角色图谱

> **审查方法**：从代码模块归属、类型定义、函数权威性判断 ownership；不以设计意图为依据。
> **单端独占**：只有一侧有相关代码或类型定义。
> **双端共持**：两侧各有对应模块，需要协调。
> **动态转移**：ownership 在运行时根据条件转移。

---

## 1. Runtime Ownership（运行时所有权）

| 维度 | V2 侧代码证据 | Android 侧代码证据 | ownership 判断 |
|------|-------------|------------------|--------------|
| **本地 agent runtime（V2）** | `core/local_execution_chain.py`：`OpenClawd` + `CommandRouter` + local executors | ——（不适用） | **V2 单端独占** |
| **本地 agent runtime（Android）** | ——（不适用） | `loop/LoopController.kt`：完整 think→act→observe 循环 | **Android 单端独占** |
| **跨设备 runtime 编排** | `core/cross_device_execution_chain.py`：OpenClawd 是 routing authority | `service/GalaxyConnectionService.kt`：Android 接受 task_assign，本地执行或 handoff | **V2 主导，Android 执行** |
| **会话 runtime 权威** | `core/attached_runtime_session_registry.py`：V2 持有 session registry | `runtime/AttachedRuntimeSession.kt`：Android 持有本地 session 镜像 | **V2 为 canonical 权威，Android 为本地镜像** |
| **本地模型推理 runtime** | ——（V2 有 LLM，但通过 OpenAI API） | `runtime/LocalInferenceRuntimeManager.kt`：本地推理管理 | **Android 单端独占** |

---

## 2. Orchestration Ownership（编排所有权）

| 维度 | V2 侧代码证据 | Android 侧代码证据 | ownership 判断 |
|------|-------------|------------------|--------------|
| **全局任务编排** | `core/system_orchestrator.py`：canonical staged bring-up | ——（不适用） | **V2 单端独占** |
| **Delegated flow 编排** | `core/delegated_flow_entity.py`：flow 生命周期权威 | `runtime/DelegatedActivationRecord.kt`：激活记录（非编排） | **V2 单端独占** |
| **本地任务编排（Android）** | ——（不适用） | `loop/LoopController.kt`：本地 plan→execute 循环 | **Android 单端独占** |
| **跨设备路由决策** | `core/openclawd.py`：routing authority | `service/GalaxyConnectionService.kt`：本地路由判断（cross-device ON/OFF）| **动态转移**：V2 决定跨设备委托；Android 决定本地 vs 接受委托 |
| **Formation 编排** | `core/device_formation/`：formation runtime | `runtime/FormationParticipationRebalancer.kt`：参与者再平衡 | **双端共持** |

---

## 3. Evidence Ownership（证据所有权）

| 证据类型 | V2 侧代码证据 | Android 侧代码证据 | ownership 判断 |
|---------|-------------|------------------|--------------|
| **执行信号证据** | `core/android_execution_signal_reconciler.py`：接收并对账 | `runtime/DelegatedExecutionSignal.kt` + `DelegatedExecutionSignalSink.kt`：生成 | **Android 生成，V2 对账** |
| **本地执行真值** | `core/android_participant_truth_ingress.py`：ingress 入口 | `runtime/AndroidLocalTruthOwnershipCoordinator.kt` + `AndroidParticipantRuntimeTruth.kt`：持有 | **Android 独占（本地 truth 权威）** |
| **Readiness artifact** | `core/delegated_flow_readiness_gate.py`：消费 readiness 证据 | `runtime/DeviceReadinessArtifact.kt` + `DelegatedRuntimeReadinessEvaluator.kt`：生成 | **Android 生成，V2 消费**（当前 wire 层断层） |
| **Acceptance artifact** | `core/delegated_flow_acceptance_gate.py`：消费 | `runtime/DeviceAcceptanceArtifact.kt` + `DelegatedRuntimeAcceptanceEvaluator.kt`：生成 | **Android 生成，V2 消费**（当前 wire 层断层） |
| **Governance artifact** | `core/delegated_flow_post_graduation_governance.py`：消费 | `runtime/DeviceGovernanceArtifact.kt` + `DelegatedRuntimeGovernanceDimension.kt`：生成 | **Android 生成，V2 消费**（当前 wire 层断层） |
| **Strategy artifact** | `core/delegated_flow_program_strategy.py`：消费 | `runtime/DeviceStrategyArtifact.kt` + `DelegatedRuntimeStrategyEvaluator.kt`：生成 | **Android 生成，V2 消费**（当前 wire 层断层） |
| **Replay 证据** | `core/replay_foundation.py` + `core/replay_audit_persistence.py`：持有 | `runtime/EmittedSignalLedger.kt`：记录已发送信号 | **双端各持本侧证据** |

---

## 4. Truth Ownership（真值所有权）

| 真值类型 | 持有方 | 代码证据 | ownership 判断 |
|---------|--------|---------|--------------|
| **全局 canonical session truth** | V2 | `core/canonical_session_truth.py` | **V2 单端独占** |
| **任务 flow 真值** | V2 | `core/delegated_flow_entity.py`、`core/flow_level_truth_ownership.py` | **V2 单端独占** |
| **Android 本地执行真值** | Android | `runtime/AndroidLocalTruthOwnershipCoordinator.kt`、`runtime/AndroidParticipantRuntimeTruth.kt` | **Android 单端独占** |
| **设备注册真值** | V2 | `core/device_registry.py`、UDM（Unified Device Model） | **V2 单端独占** |
| **实时执行跟踪真值** | V2（canonical）+ Android（本地镜像） | V2：`core/delegated_runtime_execution_tracker.py`；Android：`runtime/DelegatedExecutionTracker.kt` | **双端共持，V2 为最终权威** |

**重要说明**：Android `android_v2_continuity_contract.py` 明确写道：
> "Android is the durable participant runtime — it runs delegated tasks and reports truth about execution on the device. It is NOT the canonical orchestration authority. V2 remains the single canonical orchestration authority."

这是 truth ownership 边界的代码级声明。

---

## 5. Result Convergence Ownership（结果收敛所有权）

| 收敛类型 | 持有方 | 代码证据 | ownership 判断 |
|---------|--------|---------|--------------|
| **并行任务结果聚合** | V2 | `core/flow_aware_result_convergence.py`：flow 感知并行聚合 | **V2 单端独占** |
| **跨设备结果归并** | V2 | `core/goal_result_aggregator.py`：多节点结果聚合 | **V2 单端独占** |
| **本地结果规范化** | 各自 | V2：`LocalExecutionResult`；Android：`LoopResult` | **各端独占本地** |
| **Handoff V2 result 收敛** | V2（ingress 已实现，routing 未接通）| `core/android_handoff_v2_response_ingress.py`：ingress 入口 | **V2**（断层待修复） |

---

## 6. Recovery Ownership（恢复所有权）

| 恢复场景 | 责任方 | 代码证据 | ownership 判断 |
|---------|--------|---------|--------------|
| **Android WS 重连** | Android | `runtime/RuntimeController.kt`（PR-33）：ReconnectRecoveryState | **Android 独占** |
| **Android 进程重建后 re-attach** | 双端协作 | Android：`runtime/ProcessRecreatedReattachHint.kt`；V2：`core/android_v2_continuity_contract.py` 场景3 | **双端共持** |
| **V2 重启后 in-flight 任务恢复** | V2 主导 | V2：`core/android_v2_continuity_contract.py` 场景4；Android：re-attach 后呈现结果 | **V2 主导，Android 辅助** |
| **离线任务队列** | Android | `network/OfflineTaskQueue.kt` | **Android 独占** |
| **Continuity coordinator** | V2 | `core/flow_continuity_coordinator.py` | **V2 独占** |
| **Session recovery** | V2 | `core/runtime_restart_recovery.py` | **V2 独占** |

---

## 7. Compat / Fallback Ownership（兼容/降级所有权）

| 类型 | 持有方 | 代码证据 | ownership 判断 |
|------|--------|---------|--------------|
| **Legacy path 阻断** | V2 | `core/compat_legacy_path_blocking_canonicalization.py` | **V2 单端独占** |
| **Compat surface 退休** | V2 | `core/compat_surface_retirement.py`、`core/long_tail_compat_surface.py` | **V2 单端独占** |
| **Android compat 降级** | Android | `runtime/CompatibilitySurfaceRetirementRegistry.kt`、`runtime/LongTailCompatibilityRegistry.kt` | **Android 单端独占** |
| **跨设备降级到本地执行** | Android | `service/GalaxyConnectionService.kt`：handoff 失败 → `executeLocalTaskAssign()` | **Android 独占（执行降级决策）** |
| **Compat 阻断权威** | V2 | `core/compat_fallback_authority_guard.py` | **V2 单端独占** |

---

## 8. Governance / Strategy Ownership（治理/策略所有权）

| 维度 | V2 侧代码证据 | Android 侧代码证据 | ownership 判断 |
|------|-------------|------------------|--------------|
| **Readiness gate（发布就绪判断）** | `core/delegated_flow_readiness_gate.py`：最终 verdict | `runtime/DelegatedRuntimeReadinessEvaluator.kt`：生成 readiness artifact | **双端共持（Android 生成证据，V2 做决策）** |
| **Acceptance gate（毕业验收）** | `core/delegated_flow_acceptance_gate.py`：graduation verdict | `runtime/DelegatedRuntimeAcceptanceEvaluator.kt`：生成 acceptance artifact | **双端共持（Android 生成证据，V2 做决策）** |
| **Post-graduation governance** | `core/delegated_flow_post_graduation_governance.py`：合规检查 | `runtime/DelegatedRuntimeGovernanceDimension.kt`：维度定义 | **V2 主导** |
| **Program strategy** | `core/delegated_flow_program_strategy.py`：演进策略 | `runtime/DelegatedRuntimeStrategyEvaluator.kt`：本地策略评估 | **双端共持** |
| **Node governance** | `core/node_governance_runtime.py`：节点治理 runtime | ——（不适用） | **V2 单端独占** |

---

## 9. 角色图谱总结

```
┌──────────────────────────────────────────────────────────────────────┐
│                    双仓角色分布图（代码级）                           │
├───────────────────────────┬──────────────────────────────────────────┤
│           V2               │              Android                     │
├───────────────────────────┼──────────────────────────────────────────┤
│ ✅ 全局编排权威             │ ✅ 本地 agent runtime（LoopController）   │
│ ✅ Canonical session truth │ ✅ 本地执行真值权威                       │
│ ✅ Task flow truth          │ ✅ 执行信号生成（DelegatedExecutionSignal）│
│ ✅ 结果聚合/收敛            │ ✅ Readiness/Acceptance/Governance 证据   │
│ ✅ Recovery coordinator    │ ✅ 重连/离线队列/进程恢复                 │
│ ✅ Compat/legacy 阻断      │ ✅ 本地 compat 降级                       │
│ ✅ Governance/strategy gate│ ✅ 本地 strategy 评估                     │
│ ✅ Operator surface        │ ✅ 四层 artifact 生成                     │
│ ✅ Replay/audit 记录       │ ✅ 本地 EmittedSignalLedger               │
├───────────────────────────┼──────────────────────────────────────────┤
│ 共持：会话 runtime、Formation、实时执行追踪真值、跨仓 contract       │
│ 动态转移：跨设备路由决策（V2 决策委托，Android 决策是否接受）        │
└──────────────────────────────────────────────────────────────────────┘
```

**核心结论**：没有任何维度是单纯"一端判断另一端执行"的。V2 是 canonical 权威层，Android 是自治执行层，两者通过协议和信号协同，而不是简单的主从关系。
