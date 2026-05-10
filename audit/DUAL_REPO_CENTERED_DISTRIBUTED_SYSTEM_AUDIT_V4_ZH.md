# 双仓中心化分布式系统统一认知审计报告 V4（中文）

**审计仓库范围**：
- `DannyFish-11/ufo-galaxy-realization-v2`（V2，中心治理端）
- `DannyFish-11/ufo-galaxy-android`（Android，分布式运行参与节点）

**定义基线**：PR #993（已合并）、PR #1041（已合并）、PR #1042（已合并）、PR #1043（已合并）

**本文档性质**：双仓联合认知审计与路线图交付物。不是 V2 局部审计附带 Android 备注，而是以真实双仓代码为第一审计面的统一系统审计报告。

> **方法论声明**：所有陈述必须来自两仓可核实的真实代码锚点。不以历史设计文档、PR 叙事、路线图散文为事实证据。未经代码证实的主张一律标记为推断或待验证。

---

## 第一节：双仓定义域审计（对照 PR #993 / #1041 / #1042 / #1043 定义）

### 1.1 定义域 D1 — 中心治理权威（Center Governance Authority）

**已合并定义要求（来自 PR #993、#1041、#1042）**：
- V2 是唯一中心治理权威，持有调度、路由、能力网络、任务真相、配置、operator 汇聚、设备准入、gateway 8 个治理维度。
- PR #1042 要求治理语义绑定到真实 runtime 状态，而不是结构性并行投影。
- PR #1041 要求完成度以机器可读 scorecard 表达，总完成度已输出 77.3%，阶段判定 `mid_stage_consolidation`。

**V2 侧审计**：
- `core/unified_execution_governance.py`：定义 `ExecutionType`（goal/parallel/takeover/delegated）、`ExecutionPriority`、`CancellationReason`、`RollbackPolicy`、`TimeoutPolicy`；提供 `evaluate_execution_governance()`、`get_execution_runtime_snapshot()` 接口。PR #1042 新增 `get_execution_runtime_snapshot()` 使治理语义与真实运行快照强绑定。✅ 存在。
- `core/unified_governance_semantics.py`：`build_unified_governance_state()` 包含 `execution_runtime_state`、`per-device runtime_execution_state`、`decision_causality`（含 `active_execution_count`、`highest_priority_execution_type`、`blocked_execution_types`）。PR #1042 已将决策因果绑定到真实执行生命周期状态。✅ 存在。
- `core/android_mode_gate_policy.py`：Android 模式门治理（local/cross_device 模式下的 policy）。✅ 存在。
- `core/routes/operator.py`（路由 `/api/v1/operator/action`）：operator 汇聚面。✅ 存在。
- `core/routes/panel.py`（路由 `/api/v1/panel/unified`）：panel 状态面。✅ 存在。
- `core/unified_panel_aggregation.py`：PR #1042 确保 `mesh_runtime_state` 严格来源于 `governance_state.mesh_runtime_state`，消除旧并行快照漂移风险。✅ 存在。
- `core/execution_governance_audit_authority.py`：PR-14-V2 加入 `GovernanceAuditStage`（admission→lifecycle→uplink_observation→reconciliation→terminal）、`build_governance_authority_evidence()`、`verify_governance_authority_integrity()`、`get_governance_audit_summary()`。✅ 存在。
- `core/closed_loop_governance_consolidation.py`：PR-13-V2 加入 `ClosedLoopStage` 枚举和闭环治理审计 API。✅ 存在。

**Android 侧审计**：
- Android 不持有中心治理权威。它是受治理约束的参与者，通过 `AppSettings` 实施本地模式门，通过 `GalaxyWebSocketClient` 接收治理下发命令。
- Android 端 `AppSettings` 中维护本地 `cross_device_enabled` 等 flag，与 V2 `android_mode_gate_policy` 对应，但本地门和 V2 门之间尚无强同步协议。⚠️ 存在漂移风险。

**跨仓联合行为审计**：
- V2 已形成可机读的治理中心——`evaluate_execution_governance()` 统一判定三类执行的接受条件、优先级、互斥关系。
- Android 侧执行通过 gateway 进入 V2 治理面，V2 治理结果通过 `task_router.py`、`device_router.py` 下发。
- **跨仓漂移风险**：Android 本地 `AppSettings` 门与 V2 `android_mode_gate_policy` 之间无实时同步确认协议，可能出现 V2 允许但 Android 本地拒绝（或反之）的场景。

**完成度判定**：
| 指标 | 状态 |
|------|------|
| V2 中心治理架构 | 结构存在 + 主链路成立 + 有回归测试 |
| 跨仓治理绑定 | 主链路存在，但跨仓门一致性证明不足 |
| 整体判定 | **部分满足**（V2 侧充分，跨仓同步门仍有缺口） |

---

### 1.2 定义域 D2 — Android 运行参与节点（Android Runtime Node）

**已合并定义要求（来自 PR #993、#1041）**：
- Android 不是被动客户端。它是运行参与者、本地执行节点、可接管参与者、跨设备参与者。
- 本地执行链：`LoopController.step()` → perceive → plan → ground → act。
- 能力汇报、状态上报、接管响应等均属参与者职责。
- Android 在 mesh 中的角色是本地执行节点，而非全局协调 authority。

**Android 侧审计（来自 V2 侧代码引用与 Android 仓内已确认模块）**：
- `GalaxyConnectionService`：持久运行时宿主（后台 Service），维护长连接。✅
- `GalaxyWebSocketClient`：唯一 WebSocket 传输类，管理连接生命周期与协议收发。✅
- `CommandDispatcher`：本地能力分发器，接收 V2 下发命令并路由到本地 executor。✅
- `AccessibilityActionExecutor`：GUI 交互主链路（Accessibility API）。✅
- `AccessibilityScreenshotProvider`：视觉感知（截图）。✅
- `LlamaCppPlannerService`（真实 JNI 调用，llama.cpp b4833）：本地 AI 规划（待模型下载后可用）。✅（V3 审计已确认 gradle 依赖存在）
- `NcnnGroundingService`（真实 JNI 调用，ncnn-android-vulkan）：本地 Grounding（SeeClick）。✅
- `LoopController`：本地 step-level 执行循环（约 46KB）。✅
- `OfflineTaskQueue`：离线队列，网络弹性。✅
- `TailscaleAdapter`：替代网络路径。✅
- `AutonomousExecutionPipeline`：本地自治执行管线。✅
- `LocalCollaborationAgent`：mesh 协作参与接口。✅
- `AndroidMeshParticipationContract`：mesh 参与契约（PR-08 Android 侧）。✅

**V2 侧对应 Android 节点的接收链**：
- `galaxy_gateway/android/handlers/registration.py`：设备注册 handler。✅
- `galaxy_gateway/android/handlers/capability_report.py`：能力汇报 handler。✅
- `galaxy_gateway/android/handlers/goal_execution.py`：目标执行信号 handler。✅
- `galaxy_gateway/android/handlers/takeover_response.py`：接管响应 handler（PR-11-V2 重构后，完全委托给 `_get_lifecycle_coordinator().on_takeover_response()`）。✅
- `galaxy_gateway/android/handlers/handoff_v2_result.py`：HandoffV2 结果上传 handler。✅
- `galaxy_gateway/android/handlers/reconciliation_signal.py`：协调信号 handler。✅
- `galaxy_gateway/android/handlers/device_state_snapshot.py`：设备状态快照 handler。✅

**跨仓联合行为审计**：
- Android → V2 的四条确认 E2E 路径（注册、能力汇报、委托执行信号、HandoffV2 结果上传）在 V2 侧均有对应 handler。
- 本地 AI 执行链（llama.cpp + NCNN）在 Android 侧已具结构，但需首次运行下载模型（~1.65 GB），属于运营前置条件，非代码缺口。
- `takeover_response` handler 已在 PR-11-V2 中统一委托给生命周期协调器，消除了之前多个模块分散调用的风险。

**完成度判定**：
| 指标 | 状态 |
|------|------|
| Android 本地执行链结构 | 结构存在 + 主链路成立 |
| Android 本地 AI（llama.cpp/NCNN） | 结构成立，运营前置条件（模型下载）待满足 |
| V2 侧 Android 接收链 | 主链路存在 + handler 完整 |
| 跨仓 E2E 运行闭环证明 | 结构路径已接通，但缺乏真实双进程/双运行时的回归测试 |
| 整体判定 | **部分满足**（结构充分，运行级 E2E 证明不足） |

---

### 1.3 定义域 D3 — 执行生命周期与治理绑定（Execution Lifecycle Governance Binding）

**已合并定义要求（来自 PR #1042、#1043）**：
- 治理语义必须与真实 runtime 状态强绑定，不能只是结构性并行投影。
- `decision_causality` 必须包含真实执行生命周期状态字段。
- panel 的 `mesh_runtime_state` 必须严格对齐 canonical governance truth，不能从旧并行快照读取。

**V2 侧审计**：
- `core/unified_execution_governance.py` 的 `get_execution_runtime_snapshot()` 提供：每设备活跃执行列表、最高优先级活跃类型、策略阻塞的执行类型、聚合计数。✅ PR #1042 已引入。
- `core/unified_governance_semantics.py` 的 `build_unified_governance_state()` 现已包含：
  - 顶层 `execution_runtime_state`
  - 每设备 `runtime_execution_state`
  - 每路径 `decision_causality`（含 `active_execution_count`、`highest_priority_execution_type`、`blocked_execution_types`）
  - ✅ PR #1042 已更新。
- `core/unified_panel_aggregation.py`：`mesh_runtime_state` 严格从 `governance_state.mesh_runtime_state` 读取，无漂移。✅ PR #1042 已修复。
- `core/android_delegated_runtime_lifecycle_coordinator.py`（PR-11-V2）：统一生命周期协调器 facade，每个生命周期事件有一个 `on_*` 入口，保证 ingress→state-update→audit 顺序不漂移。✅

**Android 侧审计**：
- Android 的执行生命周期信号通过 `GalaxyWebSocketClient` 上报 V2。
- `reconciliation_signal`、`execution_signal`、`takeover_response` 均已被 V2 的 lifecycle coordinator 处理。
- Android 自身无执行治理状态机——治理权威完全在 V2 侧。这是正确的设计，符合定义。

**跨仓联合行为审计**：
- V2 执行治理快照（`get_execution_runtime_snapshot()`）已被治理语义层消费，并投影到 panel/operator 面——这条主链已在 PR #1042 中接通。
- 仍缺乏：跨仓真实 runtime 状态的自动回归验证（V2 侧 mock + Android 侧 stub 的端到端闭环测试）。

**完成度判定**：
| 指标 | 状态 |
|------|------|
| V2 执行治理与 runtime 状态绑定 | 主链路存在 + 有回归测试（PR #1042） |
| lifecycle coordinator 统一 facade | 主链路存在（PR-11-V2） |
| 跨仓执行生命周期 E2E 回归 | 仅结构/V2-stub，缺真实双进程证明 |
| 整体判定 | **部分满足**（V2 内部充分，跨仓 E2E 证明弱） |

---

### 1.4 定义域 D4 — Mesh 运行时中心闭合（Mesh Runtime Center Closure）

**已合并定义要求（来自 PR #1043）**：
- PR #1043 引入 `MeshRuntimeCenterStatus`（10 态状态机）、`MESH_RUNTIME_CENTER_VALID_TRANSITIONS`（强制转移表）、`MeshRuntimeCenterState`、`evaluate_center_runtime_status()`。
- 明确区分 `participation_ready`（参与者已注册）与 `runtime_closed`（完整协调周期已完成）。
- 116 个测试覆盖 18 个测试组（A–R）。

**V2 侧审计**：
- `core/mesh/mesh_runtime_center_state.py`：10 态状态机 enum、强制转移表、`MeshParticipantCenterEligibility`（eligible/ready/degraded/constrained/ineligible/offline）、`evaluate_center_runtime_status()`、`build_mesh_runtime_center_state()`、5 个 policy sentinel。✅ 已引入（PR #1043）。
- `core/unified_governance_semantics.py` 的 `build_mesh_runtime_state()` 现接受 `coordinator_state` 参数，包含 `center_runtime_state`（完整状态机输出）和 `mesh_runtime_center_state_machine`（在 `runtime_proofs` 中）。✅
- `core/mesh/live_mesh_runtime_engine.py`：live mesh 引擎（dispatch 执行后将 mesh 状态提升到 `runtime_proven`）。✅
- `core/mesh/body_mesh_registry.py`：mesh 角色注册。✅
- `core/mesh/mesh_session_coordinator.py`：mesh 会话协调器（`MeshSessionCoordinatorState`）。✅
- `core/mesh/mesh_session_lifecycle.py`：会话生命周期。✅
- `core/mesh/mesh_auto_enrollment.py`：自动注册。✅
- Mesh proof quality（live/stale/structurally_inferred/missing）在 `build_mesh_runtime_state()` 已输出，`MESH_RUNTIME_PROOF_STALE_AFTER_SECONDS=300.0` 秒后判定为 stale。✅

**Android 侧审计**：
- `AndroidMeshParticipationContract`（Android 端）：明确约定 Android 是 mesh 的参与节点，非全局协调 authority。
- `LocalCollaborationAgent`：参与式协作接口。
- Android 端无 mesh 状态机——mesh 全局状态机权威在 V2，Android 只上报参与状态。
- Android 端的 `mesh_topology` handler 存在于 `galaxy_gateway/android/handlers/mesh_topology.py`（V2 侧）。

**跨仓联合行为审计**：
- V2 中心 mesh 状态机已在 PR #1043 中形成——这是 mesh 主链的重大进展。
- 但 `participation_ready ≠ runtime_closed` 的区分仅在 V2 中心侧可验证，Android 侧的完整 barrier 协调（参与者全部到达 barrier 并完成 merge）尚无跨仓闭环证据。
- `mesh_runtime_state` 的 `runtime_proven` 状态只有在 live mesh 引擎驱动真实执行后才能置位——目前仅有 V2 内部路径可激活，尚无真实 Android 参与时的回归证据。

**完成度判定**：
| 指标 | 状态 |
|------|------|
| V2 中心 mesh 状态机 | 结构存在 + 回归测试存在（PR #1043，116 测试） |
| participation_ready ≠ runtime_closed 合同 | 已在 V2 侧强制执行 |
| Android 参与式 mesh | 结构/契约存在，无运行级跨仓闭环证据 |
| full mesh runtime（含 barrier）跨仓闭合 | **未满足**（deferred，Android contract 明示） |
| 整体判定 | **部分满足**（V2 中心侧充分，跨仓 runtime_closed 仍 deferred） |

---

### 1.5 定义域 D5 — 接管语义（Takeover / Delegated Ownership Transfer）

**已合并定义要求（来自 PR #993、#1041）**：
- Android 是可接管参与者（takeover-capable participant）。
- 接管不是单纯的 server-client callback，而是中心化分布网络模型的一部分。
- 接管治理应包括优先级、互斥、回滚、生命周期完整跟踪。

**V2 侧审计**：
- `core/unified_execution_governance.py`：`takeover_request` 是 `ExecutionType` 之一，优先级 `PRIORITY_1_TAKEOVER`（最高），阻塞 `goal_execution` 和 `parallel_subtask`，`failure_semantic=notify_and_retry`，`rollback_on_cancel=notify_only`，`rollback_on_failure=best_effort_undo`。✅
- `galaxy_gateway/android/handlers/takeover_response.py`（PR-11-V2 重构）：
  - 通过 `_resolve_session_id_for_takeover_response()` 解析 session_id（允许从 `attached_runtime_session_registry` 补全）。
  - 完全委托给 `_get_lifecycle_coordinator().on_takeover_response()`。
  - tracking、session reduction、audit 均由 lifecycle coordinator 统一处理，消除了 PR-11 之前的分散调用。✅
- `core/takeover_tracking.py`：接管状态跟踪。✅
- `core/android_delegated_runtime_lifecycle_coordinator.py`：`on_takeover_response()` 方法。✅
- `core/attached_runtime_session_registry.py`：session 注册表（包含 `lookup_session_by_device()`，用于补全 takeover 的 session_id）。✅
- `core/attached_runtime_recovery_readiness.py`：恢复就绪性评估。✅
- `core/android_runtime_transition_reducer.py`：Android 运行状态转换减少器。✅

**Android 侧审计**：
- Android 接收 `takeover_request` 后，`CommandDispatcher` 路由到接管处理路径，并通过 `GalaxyWebSocketClient` 发回 `takeover_response`。
- Android 端的接管接受/拒绝逻辑在 `AppSettings` 门控下。
- 接管后 Android 本地执行循环（`LoopController`）应暂停或由 V2 指令驱动——这一协调逻辑的跨仓闭合证据不足。

**跨仓联合行为审计**：
- V2 侧接管治理链已在 PR-11-V2 完整闭合：`takeover_response` handler → lifecycle coordinator → tracking/session/audit。
- Android 端发送 `takeover_response` 的逻辑存在，但缺乏跨仓恢复场景（resumed ownership transfer）的回归测试——即 Android 接受接管后断连重连的 ownership transfer 证明是弱的。
- `attached_runtime_session_registry` 的 `lookup_session_by_device()` 确保即使 session_id 丢失也能从注册表补全，但这仍是 V2 单侧的补救机制，Android 侧未必能感知到此补全。

**完成度判定**：
| 指标 | 状态 |
|------|------|
| V2 接管治理链 | 主链路存在 + 生命周期协调器已统一（PR-11-V2） |
| V2 接管优先级/互斥/回滚 | 已在 unified_execution_governance 中定义 |
| 跨仓接管响应处理 | 主路径存在，但 resumed ownership transfer 证明弱 |
| 整体判定 | **部分满足**（V2 侧充分，跨仓接管恢复场景证明不足） |

---

### 1.6 定义域 D6 — 连续性 / 重连 / 恢复（Continuity / Reconnect / Recovery）

**已合并定义要求（来自 PR #993、#1041）**：
- Android 应支持离线队列、断线重连、状态恢复。
- V2 应有 `HybridOrchestrationContinuityRegistry`、reconnect 协调、hybrid continuity 闭合。

**V2 侧审计**：
- `core/android_v2_continuity_contract.py`：V2-Android 连续性契约。✅
- `core/attached_runtime_reuse_binding.py`：attached runtime 复用绑定。✅
- `core/attached_runtime_reuse_dispatch.py`：attached runtime 复用调度。✅
- `core/attached_runtime_recovery_readiness.py`：恢复就绪性评估。✅
- `core/attached_runtime_session_registry.py`：session 注册表（含 `lookup_session_by_device()`）。✅
- `tests/test_pr6_hybrid_continuity_closure.py`：hybrid 连续性闭合测试。✅
- `tests/test_prf_dispatch_continuity_recovery_context.py`：dispatch 连续性恢复上下文测试。✅
- `tests/integration/test_v2_android_protocol_regression.py`：V2-Android 协议回归测试。✅

**Android 侧审计**：
- `OfflineTaskQueue`：离线队列，网络弹性机制。✅
- `GalaxyWebSocketClient`：管理连接生命周期（含断连重连逻辑）。✅
- `TailscaleAdapter`：替代网络路径（VPN 备用）。✅

**跨仓联合行为审计**：
- V2 侧的 reconnect 和 session reuse 机制已有测试覆盖。
- Android 侧的 `OfflineTaskQueue` 和 reconnect 在 Android 单侧已验证。
- 跨仓 reconnect 场景（Android 断连 → V2 状态保持 → Android 重连 → 状态恢复）缺少真实双进程回归证据。

**完成度判定**：
| 指标 | 状态 |
|------|------|
| V2 连续性/恢复机制 | 主链路存在 + 有回归测试 |
| Android 离线/重连机制 | 结构存在 |
| 跨仓断连-重连 E2E 回归 | **不足**（仅 stub/mock，非真实双进程） |
| 整体判定 | **部分满足** |

---

### 1.7 定义域 D7 — 可观测性 / 诊断 / 审计面（Observability / Diagnostics）

**已合并定义要求（来自 PR #993、#1041、#1042）**：
- V2 应有 operator/panel 统一可观测面。
- 治理状态、mesh 状态、执行快照应通过标准接口可查询。
- Android 侧的状态透明度是已知未闭合项（PR #993 明确提出：store 存在，wire path 不完整）。

**V2 侧审计**：
- `/api/v1/operator/action`（`core/routes/operator.py`）：operator 汇聚面。✅
- `/api/v1/panel/unified`（`core/routes/panel.py`）：panel 统一状态面。✅
- `core/unified_panel_aggregation.py`：panel 数据汇聚，`mesh_runtime_state` 严格对齐 canonical。✅（PR #1042）
- `core/operator_surface.py`：operator surface。✅
- `core/architecture_diagnostics.py`：架构诊断。✅
- `core/architecture_live_status.py`：架构实时状态。✅
- `core/audit_event_semantics.py`：审计事件语义。✅
- `core/execution_governance_audit_authority.py`（PR-14-V2）：治理审计权威，覆盖 5 个审计阶段。✅
- `classify_canonical_proof_input_diagnosis()`：Android proof 输入分类（complete/stale/conflicting/malformed/partial/missing）。✅
- `galaxy_gateway/android/handlers/diagnostics.py`：Android 诊断 handler。✅

**Android 侧审计**：
- Android 的可观测性面仍然薄弱。状态上报通过 `device_state_snapshot` handler 进入 V2，但 Android 侧的自主诊断面（可查询自身 AI 推理状态、本地循环状态、本地能力状态）尚无证据表明已完整对外暴露。
- Android 端仅有基础 log 和 WebSocket 状态报告，无结构化的 operator-consumable 诊断接口。

**跨仓联合行为审计**：
- V2 侧已有强可观测面（panel/operator/audit），但这些面主要反映 V2 视角的 Android 状态，不是 Android 自主上报的结构化诊断。
- 观测非对称性：V2 侧观测面丰富，Android 侧观测面弱——这是已知风险。

**完成度判定**：
| 指标 | 状态 |
|------|------|
| V2 可观测面（panel/operator/audit） | 充分，主链路成立 + 回归测试 |
| Android 状态透明度 | **不足**（store 存在，wire path 不完整） |
| 跨仓观测对称性 | **弱**（V2 侧强，Android 侧弱） |
| 整体判定 | **部分满足** |

---

### 1.8 定义域 D8 — Capability 网络 / 就绪性 / Policy（Capability Network）

**已合并定义要求（来自 PR #993、#1041）**：
- V2 是 capability 网络的中心治理权威。
- Android 本地能力状态与 V2 capability truth 之间存在潜在漂移风险。
- capability drift 的治理机制是已知未闭合项。

**V2 侧审计**：
- `core/canonical_capability_status.py`：规范能力状态。✅
- `core/canonical_capability_scheduling_basis.py`：规范能力调度基准。✅
- `core/admissibility_policy_convergence.py`：准入策略收敛。✅
- `core/admissibility_chain.py`：准入链。✅
- `core/android_participant_evidence_ingress.py`：Android 参与者证据入口。✅
- `core/android_result_normalizer.py`：Android 结果归一化器。✅
- `core/android_participant_session_state.py`：Android 参与者会话状态。✅
- `core/canonical_cross_repo_evidence_pipeline.py`：跨仓证据管线。✅

**Android 侧审计**：
- Android 通过 `capability_report` handler 向 V2 汇报本地能力，但 V2 消费 capability 后如何将 canonical 结果反馈给 Android（使 Android 本地状态与 V2 truth 保持对齐）的闭合机制证据不足。
- Android 端本地能力管理（如 llama.cpp 是否加载成功、NCNN 是否可用）与 V2 capability truth 之间缺乏稳定的双向同步协议。

**完成度判定**：
| 指标 | 状态 |
|------|------|
| V2 capability 中心治理 | 结构存在 + 主链路成立 |
| capability 汇报路径（Android → V2） | 主路径存在 |
| capability truth 反馈（V2 → Android） | **不足**（无稳定双向同步协议） |
| capability drift 治理 | **不足**（未形成稳定 gate） |
| 整体判定 | **部分满足** |

---

## 第二节：双仓统一系统本质（Two-Repo Unified System Nature）

### 2.1 系统本质定性

**基于真实双仓代码，这套系统的本质是：**

> **以 V2 为中心治理核的中心化分布式智能网络（Center-Governed Distributed Intelligent Network）**

这不是客户端-服务器产品，也不是手机控制台，更不是传统多端应用。它的本质结构是：

- **中心**（V2）持有：调度权威、路由权威、capability truth 权威、任务真相权威、配置权威、operator 汇聚权威、设备准入权威、gateway 传输权威。
- **分布式节点**（Android + 其他设备）持有：本地执行权力、本地感知能力、本地 AI 推理能力、参与式协作能力、多模态发射能力。
- **网络**（两仓的协议交互层）持有：执行生命周期传导、状态上报、治理指令下发、连续性保证。

### 2.2 V2 的角色

V2（`ufo-galaxy-realization-v2`）是中心治理节点，职责锚点：

| 职责 | 核心代码 |
|------|----------|
| 认知核心/执行分支 | `core/openclawd.py` |
| 外部呈现/三态生命周期 | `core/desktop_presence_runtime.py` |
| 统一执行治理 | `core/unified_execution_governance.py` |
| 统一治理语义 | `core/unified_governance_semantics.py` |
| Android 模式门治理 | `core/android_mode_gate_policy.py` |
| 生命周期协调器（Android） | `core/android_delegated_runtime_lifecycle_coordinator.py` |
| Mesh 中心状态机 | `core/mesh/mesh_runtime_center_state.py` |
| Capability 中心治理 | `core/canonical_capability_status.py` |
| 设备注册 SSOT | `core/device_registry.py` |
| Operator/Panel 可观测面 | `core/routes/operator.py`、`core/routes/panel.py` |
| 治理审计权威 | `core/execution_governance_audit_authority.py` |
| 闭环治理收口 | `core/closed_loop_governance_consolidation.py` |

### 2.3 Android 的角色

Android（`ufo-galaxy-android`）是分布式运行参与节点，职责锚点：

| 职责 | 核心代码（Android 仓） |
|------|----------------------|
| 持久运行时宿主 | `GalaxyConnectionService` |
| WebSocket 传输客户端 | `GalaxyWebSocketClient` |
| 命令分发器 | `CommandDispatcher` |
| 本地 GUI 执行 | `AccessibilityActionExecutor` |
| 本地视觉感知 | `AccessibilityScreenshotProvider` |
| 本地 AI 规划（非默认） | `LlamaCppPlannerService`（llama.cpp JNI） |
| 本地 Grounding（非默认） | `NcnnGroundingService`（NCNN JNI） |
| 本地执行循环 | `LoopController`（step-level） |
| 本地自治管线 | `AutonomousExecutionPipeline` |
| 离线队列 | `OfflineTaskQueue` |
| Mesh 参与合同 | `AndroidMeshParticipationContract` |
| 本地协作参与 | `LocalCollaborationAgent` |

**Android 不是**：
- 中心治理权威（❌）
- Mesh 全局协调器（❌）
- Capability truth SSOT（❌）
- 配置权威（❌）

**Android 是**：
- 运行参与者（✅）
- 本地执行节点（✅）
- 可接管参与者（takeover-capable participant）（✅）
- 跨设备参与者（cross-device participant）（✅）
- 多模态感知/发射节点（✅）

### 2.4 其他参与设备的角色

桌面设备（`core/desktop_presence_runtime.py`）、平板、IoT 等设备作为节点，具有：
- **本地链语义**（local-link semantics）：设备本地的执行、感知、显化能力，在本地协作路径（local mode）下可独立运行。
- **跨设备链语义**（cross-device semantics）：通过 V2 的 `CommandRouter`、`device_router.py`、`galaxy_gateway` 传输层，实现跨物理端的能力调用与协作。
- V2 的 `BodyMeshRegistry` 为所有设备节点管理 mesh 角色（`body_mesh_registry.py`）。
- `device_registry.py` 是设备身份和在线状态的 SSOT，所有节点均向其注册。

### 2.5 本地链语义 vs 跨设备链语义

| 语义 | V2 侧锚点 | Android 侧锚点 |
|------|----------|--------------|
| 本地链（local-link） | `local_execution` ExecutionType、local planning path | `LoopController`、`LlamaCppPlannerService`（本地推理） |
| 跨设备链（cross-device） | `cross_device_execution_chain.py`、`CommandRouter`、`galaxy_gateway/device_router.py` | `GalaxyWebSocketClient`、`CommandDispatcher`（接收 V2 下发） |
| 混合执行（hybrid） | `hybrid` execution path、`HybridOrchestrationContinuityRegistry` | Android 参与式协作（`LocalCollaborationAgent`） |

### 2.6 治理权威边界

| 权威类型 | 归属 |
|---------|------|
| 调度/路由权威 | V2（`CommandRouter`） |
| 任务真相权威 | V2（`unified_execution_governance`） |
| Capability truth 权威 | V2（`canonical_capability_status`） |
| Runtime truth 权威 | V2（`get_uplink_truth_state()`） |
| 接管权威（发起） | V2（`takeover_request` 下发） |
| 接管执行权威（接受/拒绝） | Android（`takeover_response`，在本地门控下） |
| 本地执行权力（autonomy） | Android（`AutonomousExecutionPipeline`，受 mode gate 约束） |
| Mesh 状态机权威 | V2（`mesh_runtime_center_state.py`） |
| Mesh 参与投票权 | Android（`AndroidMeshParticipationContract`） |
| 证明权威（proof authority） | V2（`execution_governance_audit_authority.py`，`classify_canonical_proof_input_diagnosis()`） |

---

## 第三节：双仓 Canonical 路径完整追踪

### 3.1 能力生产与消费路径

```
Android 侧（生产）                    V2 侧（消费）
──────────────────                    ───────────────
GalaxyConnectionService (注册)
  → GalaxyWebSocketClient
    → [WebSocket] →→→→→→→→→→→→→→→→ galaxy_gateway/android/handlers/registration.py
                                          → core/device_registry.py (SSOT 准入)
                                          → core/unified/device_manager.py

AccessibilityScreenshotProvider (感知)
LlamaCppPlannerService (本地规划)
  ──── 本地执行链 ────────────────→ galaxy_gateway/android/handlers/capability_report.py
                                          → core/canonical_capability_status.py
                                          → core/android_participant_evidence_ingress.py
                                          → core/canonical_cross_repo_evidence_pipeline.py
```

### 3.2 执行生命周期与治理绑定路径

```
V2 侧（治理发起）                     Android 侧（执行参与）
─────────────────                     ─────────────────────
core/openclawd.py (意图→决策)
  → core/unified_execution_governance.py (evaluate_execution_governance)
    → core/command_router.py (唯一路由权威)
      → galaxy_gateway/device_router.py (传输到 Android)
        → [WebSocket] →→→→→→→→→→→→→ CommandDispatcher
                                           → AccessibilityActionExecutor (GUI 执行)
                                           → LoopController (step 循环)

Android 执行结果上报：
LoopController (step 完成)
  → GalaxyWebSocketClient
    → [WebSocket] →→→→→→→→→→→→→→→ galaxy_gateway/android/handlers/goal_execution.py
                                          → core/android_delegated_runtime_lifecycle_coordinator.py
                                            → core/android_delegated_signal_ingress.py
                                            → core/unified_execution_governance.py (状态更新)
                                            → core/audit_event_semantics.py
```

### 3.3 连续性 / 重连 / 恢复路径

```
Android 侧（断连场景）                V2 侧（状态保持）
───────────────────                   ─────────────────
GalaxyWebSocketClient (断连检测)
  → OfflineTaskQueue (任务入队)
  → [重连] →→→→→→→→→→→→→→→→→→→→ core/attached_runtime_session_registry.py
                                          → lookup_session_by_device()
                                          → core/attached_runtime_reuse_binding.py
                                          → core/attached_runtime_recovery_readiness.py
                                          → core/android_v2_continuity_contract.py
                                    [恢复后] → 继续执行或重放
```

### 3.4 接管 / Ownership Transfer 路径

```
V2 侧（接管发起）                     Android 侧（接管响应）
─────────────────                     ─────────────────────
core/unified_execution_governance.py (takeover_request 决策)
  → core/command_router.py
    → galaxy_gateway/device_router.py
      → [WebSocket] →→→→→→→→→→→→→ CommandDispatcher (takeover_request 处理)
                                         → AppSettings 门控判断
                                         → GalaxyWebSocketClient (发回 takeover_response)
                                           →→→→→→→→→→→→→→→→→→→→ galaxy_gateway/android/handlers/takeover_response.py
                                                                       → _resolve_session_id_for_takeover_response()
                                                                       → _get_lifecycle_coordinator().on_takeover_response()
                                                                         → core/takeover_tracking.py
                                                                         → core/android_runtime_transition_reducer.py
                                                                         → core/attached_runtime_session_registry.py
                                                                         → core/audit_event_semantics.py
```

### 3.5 Mesh 参与 / 证明质量 / 就绪性影响路径

```
Android 侧（Mesh 参与）               V2 侧（Mesh 中心）
───────────────────                   ─────────────────
AndroidMeshParticipationContract (参与声明)
  → LocalCollaborationAgent (协作参与)
    → [WebSocket] →→→→→→→→→→→→→→ galaxy_gateway/android/handlers/mesh_topology.py
                                         → core/mesh/body_mesh_registry.py (角色注册)
                                         → core/mesh/mesh_session_coordinator.py
                                           → core/mesh/mesh_runtime_center_state.py
                                             evaluate_center_runtime_status()
                                             → MeshRuntimeCenterStatus 状态机转换
                                             → is_participation_ready (注册已到达)
                                             → is_runtime_closed (完整协调周期)

V2 中心 Mesh 证明质量：
core/unified_governance_semantics.py build_mesh_runtime_state()
  → proof_quality: live/stale/structurally_inferred/missing
  → proof_quality_reason
  → governance_readiness_impact
  → center_runtime_state (完整状态机输出)

→ resolve_governance_path_decision()
  → [cross_device 模式下 mesh_proof_quality 非 live 时阻塞 multimodal_participation]
```

### 3.6 诊断 / 可观测性 / 审计路径

```
V2 侧（审计面）
────────────────
core/execution_governance_audit_authority.py
  → build_governance_authority_evidence()
  → verify_governance_authority_integrity()
  → get_governance_audit_summary()
  → GovernanceAuditStage: admission→lifecycle→uplink_observation→reconciliation→terminal

core/closed_loop_governance_consolidation.py
  → query_closed_loop_governance_state()
  → assert_closed_loop_invariants()
  → get_closed_loop_audit_record()
  → ClosedLoopStage: activation→execution→observation→reconciliation→completion

Panel/Operator 面：
/api/v1/panel/unified → core/unified_panel_aggregation.py
  → mesh_runtime_state (严格来自 canonical governance)
  → execution_runtime_state (来自 get_execution_runtime_snapshot())

/api/v1/operator/action → core/routes/operator.py

Android 侧 proof 分类：
classify_canonical_proof_input_diagnosis() → complete/stale/conflicting/malformed/partial/missing
_detect_android_semantics_conflicts() → 4 种语义冲突类型

Android 诊断 handler：
galaxy_gateway/android/handlers/diagnostics.py (Android 端诊断信号入口)
```

---

## 第四节：双仓综合问题审计（含跨仓 mismatch 与 drift 风险）

### Issue-01：Capability Drift（能力漂移）

| 字段 | 内容 |
|------|------|
| 代码锚点（V2） | `core/canonical_capability_status.py`、`core/android_participant_evidence_ingress.py` |
| 代码锚点（Android） | `capability_report handler`（通过 WebSocket 上报），本地能力状态（`AppSettings`） |
| 问题类型 | 跨仓状态漂移（capability drift） |
| 严重度 | **高** |
| 影响 | V2 基于 Android 汇报的 capability 做治理决策，但 Android 本地实际能力（如 llama.cpp 是否可用）可能与 V2 记录不同步，导致 V2 做出错误的执行路径决策 |
| 根因归属 | **双仓**（缺乏双向能力同步协议） |
| 解决需要 | 双仓变更（V2 需要能力验证 gate，Android 需要本地能力状态主动汇报协议） |

### Issue-02：Schema Drift（协议模式漂移）

| 字段 | 内容 |
|------|------|
| 代码锚点（V2） | `contracts/handoff_envelope_v2.py`、`core/cross_device_execution_chain.py` |
| 代码锚点（Android） | `AipModels.kt`（103KB，完整 AIP 协议类型定义） |
| 问题类型 | 协议模式漂移（schema drift） |
| 严重度 | **高** |
| 影响 | V2 侧协议模式（Python dataclass）与 Android 侧 AIP 协议模式（Kotlin data class）可能在迭代中出现字段不一致，导致解析失败或静默数据丢失 |
| 根因归属 | **双仓**（无跨仓协议 schema 一致性门控机制） |
| 解决需要 | 双仓变更（共享 schema 定义或持续集成中的协议一致性验证） |

### Issue-03：Execution Runtime Truth Drift（执行运行时真相漂移）

| 字段 | 内容 |
|------|------|
| 代码锚点（V2） | `core/unified_execution_governance.py`（`get_uplink_truth_state()`） |
| 代码锚点（Android） | `LoopController`（本地执行状态），`GalaxyWebSocketClient`（状态上报） |
| 问题类型 | 执行运行时真相漂移 |
| 严重度 | **高** |
| 影响 | Android 本地执行进度（LoopController 的 step 状态）与 V2 规范执行真相之间可能出现不一致——Android 本地认为任务正在执行，但 V2 已将其标记为失败或超时 |
| 根因归属 | **双仓**（状态上报频率和 V2 治理决策之间无强同步协议） |
| 解决需要 | 双仓变更 |

### Issue-04：弱/偏/陈旧/缺失 Proof 高估（Proof Overstatement）

| 字段 | 内容 |
|------|------|
| 代码锚点（V2） | `core/unified_governance_semantics.py`（`MESH_RUNTIME_PROOF_STALE_AFTER_SECONDS=300.0`），`classify_canonical_proof_input_diagnosis()` |
| 代码锚点（Android） | `AndroidMeshParticipationContract`（明示 deferred capability） |
| 问题类型 | Proof 高估（proof overstatement） |
| 严重度 | **中** |
| 影响 | 系统级审查文档容易将"结构存在"误述为"运行级已证明"，导致外部观察者高估系统实际就绪程度 |
| 根因归属 | **V2**（V2 侧是 proof authority，需更严格区分 structurally_inferred 和 runtime_proven） |
| 解决需要 | V2 变更（改善 proof quality 分级的自动化报告） |

### Issue-05：Fake E2E 问题（假 E2E）

| 字段 | 内容 |
|------|------|
| 代码锚点（V2） | `tests/integration/test_v2_android_protocol_regression.py`、`tests/test_pr4v2_android_participant_truth_ingress.py` |
| 代码锚点（Android） | `Pr8AndroidMeshParticipationContractTest.kt` |
| 问题类型 | 假 E2E（Fake E2E） |
| 严重度 | **高** |
| 影响 | 当前 "E2E" 测试实际上是 V2 单侧 mock/stub 测试，不是真正的双进程/双运行时回归测试，无法证明真实 Android → V2 的完整执行链 |
| 根因归属 | **双仓**（缺乏真实跨进程/跨运行时测试基础设施） |
| 解决需要 | 双仓变更（建立真实双运行时回归测试框架） |

### Issue-06：Android 本地真相 vs V2 规范真相分歧（Local Truth vs Canonical Truth）

| 字段 | 内容 |
|------|------|
| 代码锚点（V2） | `core/unified_execution_governance.py`（canonical truth），`core/android_device_state_store.py` |
| 代码锚点（Android） | `LoopController`（本地步骤状态），`AppSettings`（本地配置） |
| 问题类型 | 本地真相 vs 规范真相分歧 |
| 严重度 | **高** |
| 影响 | Android 本地状态机可能与 V2 规范状态机产生分歧，无明确的 conflict resolution 协议 |
| 根因归属 | **双仓**（分歧解决协议未定义） |
| 解决需要 | 双仓变更 |

### Issue-07：恢复后 Ownership Transfer Proof 弱（Resumed Ownership Transfer）

| 字段 | 内容 |
|------|------|
| 代码锚点（V2） | `galaxy_gateway/android/handlers/takeover_response.py`（`_resolve_session_id_for_takeover_response()`），`core/attached_runtime_recovery_readiness.py` |
| 代码锚点（Android） | `GalaxyWebSocketClient`（断连重连），`OfflineTaskQueue` |
| 问题类型 | 恢复后接管所有权转移证明弱 |
| 严重度 | **中** |
| 影响 | Android 接受接管后断连重连的场景中，V2 虽通过注册表补全 session_id，但 Android 侧重连后的 ownership 状态是否正确恢复（接管仍有效 vs 需要重新 takeover_request）无回归证据 |
| 根因归属 | **双仓** |
| 解决需要 | 双仓变更 |

### Issue-08：Mesh runtime_closed 真实不可达性（Mesh runtime_closed Real Unreachability）

| 字段 | 内容 |
|------|------|
| 代码锚点（V2） | `core/mesh/mesh_runtime_center_state.py`（`runtime_closed` 终止态），`core/mesh/live_mesh_runtime_engine.py` |
| 代码锚点（Android） | `AndroidMeshParticipationContract`（deferred 声明） |
| 问题类型 | Mesh 运行时终态真实不可达 |
| 严重度 | **高** |
| 影响 | `runtime_closed` 态在 V2 状态机中已定义，但实际上从未通过真实 Android 参与的完整 barrier 协调周期触发过——该状态目前只可通过 V2 内部 mock 触发，非真实跨仓 runtime |
| 根因归属 | **双仓** |
| 解决需要 | 双仓变更（实现真实跨仓 barrier 协调周期） |

### Issue-09：可观测性 / 审计非对称性（Observability Asymmetry）

| 字段 | 内容 |
|------|------|
| 代码锚点（V2） | `core/execution_governance_audit_authority.py`、`/api/v1/panel/unified`、`/api/v1/operator/action` |
| 代码锚点（Android） | `galaxy_gateway/android/handlers/diagnostics.py`（V2 侧接收），Android 端无结构化诊断暴露接口 |
| 问题类型 | 可观测性非对称（observability asymmetry） |
| 严重度 | **中** |
| 影响 | V2 侧观测面丰富，但 Android 侧无 operator-consumable 诊断接口，难以在运营时诊断 Android 本地 AI 推理状态、本地循环状态 |
| 根因归属 | **Android**（主要），V2（需增加 Android 状态透明度消费路径） |
| 解决需要 | 双仓变更 |

### Issue-10：定义用词高估实际联合代码满足程度（Definition Wording Overstatement）

| 字段 | 内容 |
|------|------|
| 代码锚点（V2） | `docs/JOINT_DUAL_REPO_COGNITION_CLOSURE_BASELINE_ZH.md`、`core/joint_dual_repo_cognition_closure_review.py` |
| 代码锚点（Android） | — |
| 问题类型 | 定义用词高估 |
| 严重度 | **低** |
| 影响 | 现有 PR 叙事将若干"结构存在"的项描述为"已闭合"或"已成立"，与实际跨仓 runtime 证据不符，可能误导后续工程判断 |
| 根因归属 | **V2**（作为 proof authority 应更严格区分） |
| 解决需要 | V2 变更 |

---

## 第五节：Fake E2E vs True E2E 分类（双仓测试分类审计）

### 分类说明

| 类别 | 定义 | 证明什么 | 不证明什么 |
|------|------|----------|-----------|
| **V2-only 单元测试** | 纯 V2 侧 Python，无 Android mock | V2 内部逻辑正确性 | 跨仓协议一致性、Android 真实行为 |
| **Android-only 本地测试** | Android 仓内 Kotlin JUnit/Espresso | Android 本地逻辑正确性 | V2 侧消费行为、跨仓协议 |
| **V2 协议模拟（stub Android）** | V2 侧使用 mock/stub 模拟 Android 消息 | V2 接收 handler 逻辑 | Android 真实发送行为、真实协议序列化 |
| **跨仓 mock 证明** | 双侧均用 mock，验证协议契约 | 协议 schema 一致性（结构层） | 真实运行时行为、网络异常处理 |
| **真实跨仓双进程/双运行时回归** | V2 进程 + Android 真实 APK（或真实 JVM+native），无 mock | 真实 E2E 链路 | — |

### 当前测试分类结果

| 测试文件 | 分类 | 证明 | 不证明 |
|---------|------|------|--------|
| `tests/test_pr11_governance_closure_verification.py`（36 tests） | V2-only 单元 | V2 生命周期协调器内部逻辑 | 跨仓真实行为 |
| `tests/test_pr14_governance_audit_authority.py`（41 tests，A–E 组） | V2-only 单元 | 治理审计权威链 V2 内部正确性 | Android 真实审计 |
| `tests/test_pr03_mesh_runtime_center_closure.py`（116 tests，A–R 组） | V2-only 单元 | V2 中心 mesh 状态机转换正确性 | 真实 Android mesh 参与 |
| `tests/test_pr8v2_mesh_proof_degradation_semantics.py`（33 tests，A–E 组） | V2-only 单元 | proof quality 降级语义 | 真实 mesh 证明质量测量 |
| `tests/test_pr13_closed_loop_governance_consolidation.py` | V2-only 单元 | 闭环治理审计 V2 内部 | 跨仓闭环 |
| `tests/test_android_mode_switch_integration.py` | V2 协议模拟（stub Android） | V2 接收 Android 模式切换消息的处理逻辑 | Android 真实模式切换行为 |
| `tests/test_android_device_state_store.py` | V2 协议模拟（stub Android） | V2 侧设备状态存储逻辑 | Android 真实状态上报 |
| `tests/test_pr4v2_android_participant_truth_ingress.py` | V2 协议模拟（stub Android） | V2 侧 participant truth ingress | Android 真实 truth 信号 |
| `tests/integration/test_v2_android_protocol_regression.py` | **跨仓 mock 证明**（非真实双运行时） | 协议 schema 契约级正确性 | 真实 Android 运行时行为、网络层 |
| `Pr8AndroidMeshParticipationContractTest.kt`（Android 仓） | Android-only 本地测试 | Android mesh 参与契约本地逻辑 | V2 侧 mesh 消费行为 |
| `tests/test_pr6_hybrid_continuity_closure.py` | V2 协议模拟（stub Android） | V2 侧 hybrid continuity 处理 | 真实 Android 断连重连 |
| `tests/test_prf_dispatch_continuity_recovery_context.py` | V2 协议模拟（stub Android） | V2 dispatch continuity 恢复上下文 | Android 真实 recovery |

**结论**：目前不存在**真实跨仓双进程/双运行时回归测试**——所有"E2E"测试均为 V2 单侧或 mock 证明，无法证明真实 Android runtime → V2 的完整链路。

---

## 第六节：问题列表（含分类、严重度、双仓归属）

| # | 问题 | 类型 | 严重度 | 影响 | 根因归属 | 解决范围 |
|---|------|------|--------|------|----------|---------|
| P1 | Capability drift（能力漂移） | 跨仓状态漂移 | 高 | 错误执行路径决策 | 双仓 | 双仓 |
| P2 | Schema drift（协议模式漂移） | 跨仓协议不一致 | 高 | 解析失败或静默数据丢失 | 双仓 | 双仓 |
| P3 | Execution runtime truth drift | 跨仓状态漂移 | 高 | V2/Android 执行状态分歧 | 双仓 | 双仓 |
| P4 | Proof overstatement（证明高估） | Proof 质量问题 | 中 | 系统就绪度被高估 | V2 | V2 |
| P5 | Fake E2E（假 E2E 问题） | 测试证明弱 | 高 | 无法证明真实跨仓链路 | 双仓 | 双仓 |
| P6 | Android local truth vs V2 canonical truth | 真相分歧 | 高 | 无 conflict resolution 协议 | 双仓 | 双仓 |
| P7 | Resumed ownership transfer proof弱 | 接管恢复场景 | 中 | 重连后 ownership 状态不确定 | 双仓 | 双仓 |
| P8 | Mesh runtime_closed 真实不可达 | Mesh 闭合 | 高 | runtime_closed 态实际无法从真实 Android 参与触发 | 双仓 | 双仓 |
| P9 | Observability asymmetry（可观测性非对称） | 诊断缺口 | 中 | Android 本地 AI 状态不可观测 | Android 主/V2 次 | 双仓 |
| P10 | Definition wording overstatement（定义高估） | 证明质量问题 | 低 | 误导工程判断 | V2 | V2 |
| P11 | Android AppSettings vs V2 mode gate 同步缺失 | 治理缺口 | 高 | 本地门和 V2 门可能不一致 | 双仓 | 双仓 |
| P12 | multimodal 运行级 E2E 证据不足 | 运行级缺口 | 中 | 多模态链无跨仓真实证明 | 双仓 | 双仓 |

---

## 第七节：集成双仓 PR 路线图（双仓感知，明确 V2 / Android / 双仓范围）

### PR-ROADMAP-01：跨仓协议 Schema 一致性门控

| 字段 | 内容 |
|------|------|
| 仓库范围 | **双仓**（V2 + Android） |
| 解决问题 | P2（Schema drift） |
| 关键落地区域 | V2: `contracts/handoff_envelope_v2.py`、CI 校验脚本；Android: `AipModels.kt`、CI JSON schema 对比 |
| 依赖 | 无前置依赖 |
| 接受标准 | V2 和 Android 的核心消息类型字段在 CI 中自动比对；schema 不一致时阻断 PR 合并 |
| 推进意义 | 消除最高优先级跨仓静默 drift 风险 |

### PR-ROADMAP-02：Android AppSettings 门与 V2 mode gate 双向同步协议

| 字段 | 内容 |
|------|------|
| 仓库范围 | **双仓** |
| 解决问题 | P1（Capability drift）、P11（门控同步缺失）、P6（local truth vs canonical truth） |
| 关键落地区域 | V2: `core/android_mode_gate_policy.py`、新增门控同步验证 API；Android: `AppSettings`、新增门控状态上报消息 |
| 依赖 | PR-ROADMAP-01 完成后 |
| 接受标准 | Android `cross_device_enabled` 等关键 flag 变化时，V2 侧自动感知并更新 mode gate 状态；无需人工重启 |
| 推进意义 | 消除本地门/中心门分歧风险，建立治理一致性基础 |

### PR-ROADMAP-03：Android 结构化诊断接口（可观测性对称化）

| 字段 | 内容 |
|------|------|
| 仓库范围 | **双仓**（Android 主，V2 次） |
| 解决问题 | P9（Observability asymmetry） |
| 关键落地区域 | Android: 新增结构化诊断上报接口（AI 推理状态、LoopController 状态、本地能力状态）；V2: `galaxy_gateway/android/handlers/diagnostics.py` 扩展消费路径 |
| 依赖 | PR-ROADMAP-01 完成后 |
| 接受标准 | V2 侧 `/api/v1/panel/unified` 能展示 Android 本地 AI 推理状态（llama.cpp/NCNN 是否可用、最后推理时间戳）；可在 operator 面查询 |
| 推进意义 | 运营时 Android 侧 AI 状态可观测，关键可调试性提升 |

### PR-ROADMAP-04：Capability 双向同步协议（消除 capability drift）

| 字段 | 内容 |
|------|------|
| 仓库范围 | **双仓** |
| 解决问题 | P1（Capability drift） |
| 关键落地区域 | V2: `core/canonical_capability_status.py`、新增 capability acknowledgment 下发；Android: 接收 capability_ack 并更新本地状态 |
| 依赖 | PR-ROADMAP-01、PR-ROADMAP-02 完成后 |
| 接受标准 | Android 汇报能力变化后，V2 回发 capability_ack，Android 本地记录 V2 canonical 状态；V2 侧能力状态与 Android 本地状态差异 < 1 个心跳周期 |
| 推进意义 | 消除 capability drift，V2 治理决策可靠性提升 |

### PR-ROADMAP-05：真实跨仓双运行时回归测试框架

| 字段 | 内容 |
|------|------|
| 仓库范围 | **双仓** |
| 解决问题 | P5（Fake E2E）、P8（Mesh runtime_closed 不可达） |
| 关键落地区域 | V2: `tests/integration/` 新增真实双进程测试基础设施（V2 进程 + Android emulator/真实设备 JVM）；Android: 新增集成测试 runner |
| 依赖 | PR-ROADMAP-01、PR-ROADMAP-02 完成后 |
| 接受标准 | 至少一条 Android → V2 → Android 的真实全链路回归测试（注册→能力汇报→任务执行→结果上报）可通过 CI；`runtime_closed` 状态可在真实 Android 参与后被触发 |
| 推进意义 | 将测试证明质量从"结构/mock 层"升级到"真实运行时层"，解除最大 proof 债务 |

### PR-ROADMAP-06：Execution Runtime Truth 一致性协议（消除 execution drift）

| 字段 | 内容 |
|------|------|
| 仓库范围 | **双仓** |
| 解决问题 | P3（Execution runtime truth drift）、P6（local truth vs canonical truth） |
| 关键落地区域 | V2: `core/unified_execution_governance.py` 新增 execution state reconciliation API；Android: `LoopController` 新增周期性状态上报（heartbeat with step progress） |
| 依赖 | PR-ROADMAP-01、PR-ROADMAP-02 完成后 |
| 接受标准 | Android step 执行状态差异在 V2 侧可被检测到，超过阈值时触发 reconciliation 流程；无静默分歧状态 |
| 推进意义 | 解决执行状态最高严重度双仓漂移风险 |

### PR-ROADMAP-07：Resumed Ownership Transfer 完整回归闭合

| 字段 | 内容 |
|------|------|
| 仓库范围 | **双仓** |
| 解决问题 | P7（Resumed ownership transfer proof 弱） |
| 关键落地区域 | V2: `core/attached_runtime_recovery_readiness.py`、`core/android_v2_continuity_contract.py`，新增断连重连接管恢复场景回归测试；Android: 断连重连后 ownership 状态恢复逻辑 |
| 依赖 | PR-ROADMAP-05 完成后（真实双运行时测试基础设施） |
| 接受标准 | Android 接受接管后断连，重连后 V2 侧 ownership 状态正确恢复（接管仍有效 vs 需重新发起）的回归测试可通过 |
| 推进意义 | 关键安全/治理语义：接管场景的连续性保证 |

### PR-ROADMAP-08：Proof Quality 自动化报告与门控

| 字段 | 内容 |
|------|------|
| 仓库范围 | **V2** |
| 解决问题 | P4（Proof overstatement）、P10（Definition wording overstatement） |
| 关键落地区域 | V2: `core/execution_governance_audit_authority.py`、`core/joint_dual_repo_cognition_closure_review.py`，新增 proof quality 自动化报告与门控（区分 structurally_inferred / V2-only-proven / cross-repo-canonical-proven） |
| 依赖 | 无前置依赖（可与其他 PR 并行） |
| 接受标准 | 每个系统级命题自动输出 proof quality 分级；scorecard 中 "cross-repo-canonical-proven" 项需真实跨仓回归支持才可标记 |
| 推进意义 | 消除审计结论和系统实际状态的系统性高估 |

---

## 第八节：最终中文决策结论

### 8.1 两仓联合系统真正是什么

基于真实代码证据（V2 Python 源码 + Android Kotlin 源码），这套系统是：

> **一套以 `ufo-galaxy-realization-v2` 为中心治理核的中心化分布式智能网络系统。**

- V2 持有全部治理权威（调度/路由/任务真相/capability truth/配置/设备准入/gateway/operator 汇聚）。
- Android 是强运行参与节点（本地执行/本地 AI/可接管参与/跨设备参与/多模态感知发射）。
- 两仓通过 WebSocket + AIP 协议构成中心化分布式智能网络，共同承载一个 AI 主体的认知-执行-感知-显化循环。
- 其他设备（桌面/平板/IoT）通过相同 gateway 以相同参与者语义接入。
- 这不是传统意义上的服务器-客户端产品，而是每个设备节点（包括 Android）都是网络"身体"的一部分。

### 8.2 当前真实完成度

| 维度 | 完成度判定 |
|------|-----------|
| V2 中心治理权威（调度/路由/任务真相/配置） | **充分**（主链路成立 + 回归测试） |
| V2 执行治理与 runtime 绑定（PR #1042） | **充分**（decision_causality 已绑定真实 runtime 状态） |
| V2 Mesh 中心状态机（PR #1043） | **充分**（10 态状态机 + 116 测试） |
| V2 生命周期协调器（PR-11-V2） | **充分**（统一 facade，消除多处分散调用） |
| V2 审计权威链（PR-14-V2） | **充分**（5 阶段审计路径 + 回归测试） |
| Android 本地执行链（LoopController + GUI） | **结构充分**（需模型下载才可 AI 推理） |
| Android 本地 AI（llama.cpp + NCNN） | **结构充分**，运营前置条件（~1.65GB 模型下载） |
| 跨仓 E2E 执行链（真实双进程） | **不足**（仅 mock/stub 证明） |
| Mesh runtime_closed（真实跨仓 barrier 闭合） | **不足**（deferred，Android 参与 barrier 从未真实触发） |
| Capability drift 治理 | **不足**（无双向同步协议） |
| Schema drift 门控 | **不足**（无跨仓协议一致性 CI 门控） |
| 可观测性对称（Android 侧结构化诊断） | **不足** |

**综合判定**：系统已越过 PoC 阶段，处于 **mid-stage consolidation（中期收敛阶段）**，加权完成度约 77%（PR #1041 scorecard 输出）。V2 内部治理充分，跨仓运行级闭合是主要剩余债务。

### 8.3 是否真正满足 PR #993 / #1041 / #1042 / #1043 定义

| 定义要求 | 满足状态 |
|---------|---------|
| PR #993：V2 是唯一中心治理权威 | ✅ **已满足**（代码充分支持） |
| PR #993：Android 是强运行节点，非被动客户端 | ✅ **已满足**（代码充分支持） |
| PR #993：剩余工作是收口而非 capability gap | ✅ **已满足**（系统已越过 PoC） |
| PR #1041：完成度机器可读 scorecard | ✅ **已满足**（`joint_dual_repo_cognition_closure_review.py`） |
| PR #1041：分阶段完成度判定 | ✅ **已满足**（`mid_stage_consolidation` 已输出） |
| PR #1042：治理语义绑定真实 runtime 状态 | ✅ **已满足**（`decision_causality` 绑定 `get_execution_runtime_snapshot()`） |
| PR #1042：panel `mesh_runtime_state` 严格对齐 canonical | ✅ **已满足** |
| PR #1043：`participation_ready ≠ runtime_closed` 合同 | ✅ **V2 内部已满足**，⚠️ 跨仓 runtime_closed 真实触发 deferred |
| PR #1043：mesh 状态机强制转移表 | ✅ **V2 内部已满足** |
| 跨仓 E2E 真实闭合 | ❌ **未满足**（最大剩余债务） |
| capability drift 消除 | ❌ **未满足** |
| schema drift 门控 | ❌ **未满足** |
| 可观测性对称化 | ❌ **部分满足** |

### 8.4 哪些主张有真实代码支持

✅ **有真实代码支持**：
- V2 是唯一中心治理权威（8 个治理维度均有代码锚点）
- Android 是可接管的强运行参与节点（handlers/lifecycle coordinator/注册表完整）
- V2 execution governance 与 runtime 状态强绑定（PR #1042 引入 `get_execution_runtime_snapshot()`）
- V2 mesh 中心状态机已形成（PR #1043 的 10 态状态机 + 116 测试）
- V2 lifecycle coordinator 统一 facade 已形成（PR-11-V2）
- V2 治理审计权威链已形成（PR-14-V2）
- proof quality 分级已在治理语义层输出（live/stale/structurally_inferred/missing）
- Android 本地 AI 结构（llama.cpp + NCNN）已存在（V3 审计确认 gradle 依赖）

### 8.5 哪些主张仅有结构性或 V2 单侧证明

⚠️ **仅结构性或 V2 单侧**：
- "跨仓 E2E 闭合"——实际仅有 V2 侧 mock/stub
- "mesh full runtime closed"——`runtime_closed` 态真实触发 deferred
- "Android local truth 与 V2 canonical truth 对齐"——无双向同步协议
- "resumed ownership transfer 正确性"——无跨仓回归测试
- "capability drift 消除"——无双向能力同步协议
- "schema drift 已门控"——无跨仓协议 CI 验证

### 8.6 最重要的联合系统剩余缺口

按影响优先级排列：

1. **跨仓协议 Schema drift 门控**（P2）——高风险，无 CI 门控，任何协议字段变更都可能无声破坏
2. **真实 E2E 双运行时回归测试框架**（P5）——所有"E2E"声明均基于 mock，无法证明真实链路
3. **Execution runtime truth drift**（P3）——Android/V2 执行状态分歧无 conflict resolution 协议
4. **Mesh runtime_closed 真实可达**（P8）——barrier 协调从未在真实 Android 参与下触发
5. **Capability drift 治理**（P1、P4）——能力状态单向上报，无回传确认
6. **可观测性对称化**（P9）——Android 本地 AI 状态对 V2 operator 不透明

---

*本文档由 V2 仓库双仓审计系统生成，版本 V4，以 PR #993、#1041、#1042、#1043 合并定义为基线。本文档可随两仓代码变化更新，所有结论应以真实代码为最终权威。*

*文档路径：`audit/DUAL_REPO_CENTERED_DISTRIBUTED_SYSTEM_AUDIT_V4_ZH.md`*
*对应 contract：`core/dual_repo_centered_system_audit_contract.py`*
*对应测试：`tests/test_dual_repo_centered_system_audit.py`*
