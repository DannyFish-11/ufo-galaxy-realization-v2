# 双仓底层向上定义审计报告（中文）

> **审计对象**：`DannyFish-11/ufo-galaxy-realization-v2`（V2）+ `DannyFish-11/ufo-galaxy-android`（Android）
>
> **定义基线**：PR 993（已合并）、PR 1041（已合并）、PR 1042（已合并）、PR 1043（已合并）
>
> **审计方法**：自底向上（bottom-up）、定义审计式（definition-audit-style）——以已合并 PR 中的定义和语义要求为标准，逐项审查真实代码是否满足这些定义；拒绝混淆结构存在与主链路成立与运行证明已存在三种层级。
>
> **重要声明**：本文件不依赖 PR 叙事作为事实来源。所有结论须落到真实类/函数/文件/测试代码锚点。

---

## 第一部分：定义层 vs 实现层 vs 证明层 — 区分声明

在阅读以下审查前，必须严格区分以下四个层级：

| 层级 | 含义 | 判断标准 |
|---|---|---|
| **定义层** | 某概念/约束/语义被明确定义 | 有 enum/dataclass/sentinel/function signature |
| **实现层** | 定义被具体实现且主链路可达 | 有实际执行逻辑、条件分支、状态转换 |
| **V2-side 回归证明层** | V2 内部单元/集成测试可验证 | pytest 测试覆盖关键行为，CI 可运行 |
| **跨仓运行时接地证明层** | 真实两进程运行时下的 Kotlin Android 参与行为经过验证 | 需要真实 Kotlin Android APK 连接 V2 并执行可重现操作 |

---

## 一、定义逐项审查（PR 993 / PR 1041~1043）

### 1.1 PR 993 定义域审查

**PR 993 核心定义**：Galaxy 是以 V2 为中心治理核的中心分布式 AI 身体网络；V2 是唯一治理权威；Android 等设备是 AI 身体载体而非客户端；网络本身是真实身体；Android 已是强 runtime node；当前超出 PoC 阶段；剩余工作是收口类工程而非能力缺失。

#### P1：V2 是唯一中心治理权威

| 审查项 | 结论 | 层级 | 代码锚点 |
|---|---|---|---|
| 统一执行治理（goal/parallel/takeover/delegated） | ✅ 成立 | 实现层 | `core/unified_execution_governance.py::ExecutionType`, `evaluate_execution_governance()` |
| 统一治理语义（模式门、dispatch_eligible、路径决策） | ✅ 成立 | 实现层 | `core/unified_governance_semantics.py::resolve_governance_path_decision()` |
| Android 模式门治理 | ✅ 成立 | V2-side 回归证明层 | `core/android_mode_gate_policy.py`, `tests/test_android_mode_switch_integration.py` |
| 中心能力治理 | ✅ 成立 | 实现层 | `core/capability_manager.py`, `core/canonical_capability_status.py` |
| operator 聚合面 | ✅ 成立 | 实现层 | `core/routes/operator.py (/api/v1/operator/action)`, `core/operator_surface.py` |
| 设备准入治理 | ✅ 成立 | 实现层 | `core/device_registry.py`, `galaxy_gateway/android/handlers/registration.py::handle_device_register()` |
| 任务 truth 权威 | ✅ 成立 | 实现层 | `core/canonical_session_truth.py`, `core/unified_execution_governance.py::get_uplink_truth_state()` |
| 调度权威 | ✅ 成立 | 实现层 | `core/scheduler.py`, `core/system_orchestrator.py` |

**P1 总判定：已成立（实现层）。V2-side 回归证明层覆盖关键分支。但跨仓运行时接地证明仍依赖 Python mock 客户端。**

---

#### P2：Android 是强 runtime node（非被动终端）

| 审查项 | 结论 | 层级 | 代码锚点 |
|---|---|---|---|
| 本地自主执行能力 | ✅ 结构定义存在 | 定义层/实现层（Android） | `AutonomousExecutionPipeline.kt`, `EdgeExecutor.kt` |
| 本地目标执行 | ✅ 结构存在 | 定义层（Android） | `LocalGoalExecutor.kt`, `GoalExecutionPipeline.kt` |
| V2-side 消费端（goal_execution ingress） | ✅ 成立 | 实现层 | `galaxy_gateway/android/handlers/goal_execution.py::handle_goal_execution()` |
| 协作参与（mesh participation contract） | ✅ 定义存在 | 定义层（Android） | `LocalCollaborationAgent.kt`, `AndroidMeshParticipationContract.kt`（Android 仓）|
| 离线排队 / replay | ✅ 定义存在 | 定义层（Android） | `DelegatedRuntimeUnit.kt`（含 offline_queue 相关逻辑） |
| WebSocket 运行时连接 | ✅ 成立 | 实现层（Android） | `GalaxyWebSocketClient.kt`（Android 网络目录）|
| 能力上报 → V2 ingress | ✅ 成立 | 实现层 | `handle_capability_report()` → `absorb_capability_report_semantics()` → `CapabilityAuthority` |
| 本地执行结果 uplink → V2 truth | ✅ 成立 | 实现层 | `handle_task_result()` → `run_task_result_truth_chain()` → `unified_execution_governance` |
| **跨仓真实 Kotlin Android 执行的 runtime 证明** | ❌ **缺失** | 跨仓运行时接地证明层 | 所有集成测试使用 Python 模拟客户端；无 Kotlin CI |

**P2 总判定：结构层与 V2 消费端成立；Android 本地实现定义存在；真实 Kotlin Android 节点的 runtime 证明不存在于 V2 CI 中。**

---

#### P3：双仓 execution governance 语义统一

| 审查项 | 结论 | 层级 | 代码锚点 |
|---|---|---|---|
| V2 执行类型枚举（goal/parallel/takeover/delegated） | ✅ 成立 | 实现层 | `core/unified_execution_governance.py::ExecutionType` |
| V2 uplink truth 状态 | ✅ 成立 | V2-side 回归证明层 | `get_uplink_truth_state()`, `tests/test_pr06_execution_governance_hardening.py` |
| Android → V2 执行结果 uplink | ✅ 主链路存在 | 实现层 | `handle_goal_execution_result()` → `_run_task_result_truth_chain()` |
| Android 执行生命周期 → V2 lifecycle event | ✅ 部分 | 实现层（V2 侧） | `record_execution_lifecycle_event()`, `get_execution_lifecycle_history()` |
| **跨仓 execution governance 运行态一致性（真实 Kotlin）** | ❌ **缺失** | 跨仓运行时接地证明层 | 无 V2+Android 双进程运行时下的 lifecycle event 完整序列验证 |
| Android 执行语义漂移检测 | ❌ 弱 | 证明层 | `classify_canonical_proof_input_diagnosis()` 存在，但缺少自动化跨仓漂移告警 |

**P3 总判定：V2 侧治理语义成立；V2↔Android 协议合约存在；但跨仓运行态一致性仍处于 constrained，缺乏跨仓双进程 runtime 验证。**

---

#### P4：超出 PoC 阶段

| 审查项 | 结论 | 代码锚点 |
|---|---|---|
| 中心治理核已成型（不是原型） | ✅ 成立 | `core/unified_execution_governance.py`（5000+ 行）、`core/unified_governance_semantics.py` |
| 多个 handler 在生产主路径上 | ✅ 成立 | `galaxy_gateway/android/handlers/__init__.py`（18 个 handler） |
| operator/panel 面已暴露 | ✅ 成立 | `/api/v1/panel/unified`, `/api/v1/operator/action` |
| Android 端多个核心类已实现 | ✅ 成立 | `AutonomousExecutionPipeline.kt`, `DelegatedTakeoverExecutor.kt` |
| 有系统性测试（非手写验证） | ✅ 成立 | tests/ 目录 752 个测试文件 |

**P4 总判定：超出 PoC 阶段成立。但"中期收敛"判定（PR 1041 的 77.3%）仍准确——非近收口。**

---

#### P5：剩余工作是收口类工程而非能力缺失

| 审查项 | 结论 |
|---|---|
| 统一 ingress 是否仍缺 | ✅ 部分缺：Android capability report 已接通，但 Android state → V2 canonical truth 的漂移治理仍弱 |
| 统一状态透明度是否仍缺 | ✅ 部分缺：`/api/v1/panel/unified` 存在，但跨仓运行态实时对齐仍缺 |
| 统一多设备编排是否仍缺 | ✅ 仍缺：full mesh runtime 协调闭环未完成 |
| 统一显化面是否仍缺 | ✅ 仍缺：carrier/manifestation 语义已定义，但显化链路未完全闭合 |

**P5 总判定：方向正确。但"收口类工程"的表述需要区分：部分缺口实际上是运行级证明缺口，不是简单的工程修复。**

---

### 1.2 PR 1041 定义域审查

**PR 1041 核心定义**：8 域完成度 scorecard（77.3% 加权），8 个系统命题（P1-P8），阶段判定 mid_stage_consolidation，结构化剩余工作。

#### 8 域完成度审查（审查 scorecard 数值与真实代码的一致性）

| 域 | PR 1041 判定 | 真实代码层级分析 | 审计结论 |
|---|---|---|---|
| D1 authority/governance（95%） | 已成立，fully_closed | V2 治理核确实成体系，但部分治理门禁仍靠结构而非 runtime gate | **轻度高估**：实际~88%，缺运行级动态 gate 覆盖 |
| D2 execution runtime（88%） | 执行链结构成立；跨仓运行态需补强 | 主链路存在；真实 Kotlin Android 执行 → V2 runtime state 无完整回归 | **基本准确**：跨仓运行证明缺口是关键 |
| D3 Android runtime node（68%） | 本地执行与协作参与成立；非全局 mesh authority | Android 代码定义存在；但 V2 CI 只能证明 Python 模拟端，非 Kotlin Android | **偏高估**：实际~58%，因 Kotlin 端缺乏 V2 可验证的运行证明 |
| D4 mesh/hybrid/orchestration（62%） | participation contract 已有；full mesh runtime deferred | mesh_runtime_center_state.py 定义存在；但无真实多节点协调运行证据 | **基本准确**；runtime_closed 状态在生产中不可达 |
| D5 multimodal（64%） | 主链语义成立；E2E 证据不足 | 语义链定义存在；运行级端到端（真实 Android multimodal emission → V2 ingress）未证明 | **基本准确** |
| D6 capability/readiness/policy（66%） | 中心治理成立；Android 本地漂移风险在 | V2 CapabilityAuthority 存在；Android 本地 capability toggle 与 V2 truth 无自动对齐 | **基本准确**；漂移风险实际更高 |
| D7 observability/operator/state（95%） | operator/panel/mesh_runtime_state 透明面已形成 | `/api/v1/panel/unified`, `/api/v1/operator/action`, `mesh_runtime_state` 均已暴露 | **基本准确**；但实时性与跨仓接地性仍有缺口 |
| D8 manifestation/carrier semantics（72%） | 语义面存在；跨仓运行级证明待增强 | 语义定义在 V2 侧存在；Android carrier 执行语义未被 V2 CI 验证 | **基本准确** |

**总体 77.3% 判定**：方向基本正确，但部分域因"定义层存在"被误当"实现层成立"，实际整体加权完成度更接近 65-70%。

---

### 1.3 PR 1042 定义域审查

**PR 1042 核心定义**：`get_execution_runtime_snapshot()` 提供规范执行运行时快照；`build_unified_governance_state()` 包含 `execution_runtime_state`；`decision_causality` 字段基于真实 lifecycle state；panel `mesh_runtime_state` 严格对齐规范治理 truth。

| 审查项 | 结论 | 层级 | 代码锚点 |
|---|---|---|---|
| `get_execution_runtime_snapshot()` 已实现 | ✅ 成立 | 实现层 | `core/unified_execution_governance.py` |
| `build_unified_governance_state()` 包含 `execution_runtime_state` | ✅ 成立 | 实现层 | `core/unified_governance_semantics.py:656` |
| `decision_causality` 含 `active_execution_count`, `highest_priority_execution_type`, `blocked_execution_types` | ✅ 成立 | 实现层 | `core/unified_governance_semantics.py`（decision_dict 更新段） |
| panel `mesh_runtime_state` 严格从 `governance_state.mesh_runtime_state` 读取 | ✅ 成立 | 实现层 | `core/unified_panel_aggregation.py` |
| **回归测试覆盖这些绑定** | ✅ 部分 | V2-side 回归证明层 | `tests/test_pr03_mesh_runtime_center_closure.py`（116 tests）、`tests/test_pr06_execution_governance_hardening.py` |
| **真实 Android 执行驱动 execution_runtime_snapshot** | ❌ 缺失 | 跨仓运行时接地证明层 | 快照依赖 `_LIVE_EXECUTION_GOVERNANCE_STATE` 内存字典；无真实 Kotlin Android 驱动的 lifecycle event 序列验证 |

**PR 1042 总判定：V2 侧绑定成立（实现层 + 回归证明层）。但 execution_runtime_state 的实际值在生产中依赖真实 Android 连接驱动 lifecycle event，这一跨仓路径仅有 Python mock 测试覆盖。**

---

### 1.4 PR 1043 定义域审查

**PR 1043 核心定义**：`MeshRuntimeCenterStatus`（10 状态枚举）、`MESH_RUNTIME_CENTER_VALID_TRANSITIONS`（强制转换表）、`participation_ready ≠ runtime_closed` 合约、`evaluate_center_runtime_status()`、`build_mesh_runtime_center_state()`。

| 审查项 | 结论 | 层级 | 代码锚点 |
|---|---|---|---|
| `MeshRuntimeCenterStatus` 10 状态枚举定义 | ✅ 成立 | 定义层 | `core/mesh/mesh_runtime_center_state.py:MeshRuntimeCenterStatus` |
| `MESH_RUNTIME_CENTER_VALID_TRANSITIONS` 强制转换表 | ✅ 成立 | 定义层 | `core/mesh/mesh_runtime_center_state.py:MESH_RUNTIME_CENTER_VALID_TRANSITIONS` |
| `participation_ready ≠ runtime_closed` 合约 | ✅ 成立 | 定义层 + V2-side 回归证明层 | `tests/test_pr03_mesh_runtime_center_closure.py` Group N |
| `evaluate_center_runtime_status()` 实现 | ✅ 成立 | 实现层 | `core/mesh/mesh_runtime_center_state.py:evaluate_center_runtime_status()` |
| `build_mesh_runtime_center_state()` 输出集成到 `build_mesh_runtime_state()` | ✅ 成立 | 实现层 | `core/unified_governance_semantics.py:420`（`center_runtime_state` 字段）|
| **`runtime_closed` 状态在真实系统中可达** | ❌ **不可达** | 跨仓运行时接地证明层 | 需要真实多个 Android 节点完成协调循环；当前无任何真实跨节点 mesh 协调证据 |
| 116 个回归测试（Groups A-R） | ✅ 成立 | V2-side 回归证明层 | `tests/test_pr03_mesh_runtime_center_closure.py`（all tests use mock coordinator） |
| `evaluate_center_runtime_status()` 被主链路调用 | ⚠️ **仅通过 `build_mesh_runtime_center_state()`** | 实现层（仅快照路径） | 在 `unified_governance_semantics.py` 中已集成，但仅作为快照面；非生产调度决策路径 |

**PR 1043 总判定：定义层和 V2-side 回归证明层成立。但 `runtime_closed` 状态在真实系统中不可达（无真实多节点 mesh 协调），且状态机仅用于快照面，未驱动实际调度决策。这是一个关键的定义过度宣称问题。**

---

## 二、联合系统本质分析

### 2.1 系统类型定性

基于真实代码，这个联合系统是：

**以 V2 为治理中心的中心分布式网络系统（Centered Distributed Network System）**

- **不是**：传统 C/S 架构（客户端-服务器）
- **不是**：纯粹的去中心化 mesh
- **是**：V2 保持规范治理权威（canonical/governance/truth center），Android 和其他节点具有本地执行和跨设备参与语义的分布式节点

代码证明：
```
V2 核心治理类：
  core/command_router.py            # 路由权威
  core/unified_execution_governance.py  # 执行治理权威
  core/unified_governance_semantics.py  # 治理语义权威
  core/device_registry.py          # 设备准入权威

Android 分布式节点类：
  AutonomousExecutionPipeline.kt   # 本地自主执行
  DelegatedTakeoverExecutor.kt     # 本地接管执行
  LocalCollaborationAgent.kt       # 本地协作参与
```

### 2.2 角色边界

| 角色 | 权限/能力 | 代码锚点 |
|---|---|---|
| **V2（中心）** | 规范权威、治理权威、runtime truth 权威、证明权威、调度权威、路由权威 | `unified_execution_governance.py`, `command_router.py`, `openclawd.py` |
| **Android（分布式节点）** | 本地执行、本地链路参与、跨设备链路参与、能力生产、结果 uplink、接管参与 | `AutonomousExecutionPipeline.kt`, `DelegatedTakeoverExecutor.kt`, `GalaxyWebSocketClient.kt` |
| **V2 对 Android 的关系** | 不是"服务器控制客户端"；是"治理中心 ↔ 执行节点"的语义关系 | Android 模式门治理（`android_mode_gate_policy.py`）；节点执行治理（`evaluate_execution_governance()`） |

### 2.3 本地链路 + 跨设备链路

| 链路类型 | V2 侧 | Android 侧 | 成立层级 |
|---|---|---|---|
| 本地链路（Android 内部执行） | — | `AutonomousExecutionPipeline.kt`, `LocalGoalExecutor.kt` | 定义层（Android 仓） |
| 跨设备链路（Android→V2 结果 uplink） | `handle_goal_execution_result()`, `run_task_result_truth_chain()` | `GalaxyWebSocketClient.kt` 发送结果 | 实现层 |
| 跨设备链路（V2→Android 指令下发） | `android_bridge.send_to_device()` | WebSocket 接收 | 实现层 |
| 跨设备链路（Android mesh 参与） | `build_mesh_runtime_center_state()` | `LocalCollaborationAgent.kt`, `AndroidMeshParticipationContract.kt` | 定义层（双侧定义存在，无跨仓运行证明）|

### 2.4 接管相关角色边界

| 能力 | V2 侧 | Android 侧 | 成立层级 |
|---|---|---|---|
| 接管请求下发 | 生成 `takeover_request` 并发往 Android | — | 实现层 |
| 接管响应处理 | `handle_takeover_response()` → `_get_lifecycle_coordinator().on_takeover_response()` | `TakeoverEnvelope.kt`, `TakeoverEligibilityAssessor.kt`, `DelegatedTakeoverExecutor.kt` | 实现层（V2）+ 定义层（Android）|
| 接管后 ownership 转移 | `android_delegated_runtime_lifecycle_coordinator.py` | `DelegatedHandoffContract.kt`, `HandoffEnvelopeV2.kt` | 实现层（V2）+ 定义层（Android）|
| **接管后 resumed ownership transfer 的完整验证** | ❌ 弱 | ❌ 弱 | 证明缺口：缺少接管完成 → ownership 回传 → V2 确认的完整端到端测试 |

---

## 三、完整规范路径追踪

### 3.1 Android 能力生产 → uplink → V2 ingestion → 规范化 → gate/治理

```
Android 侧：
  UFOGalaxyApplication.kt（初始化）
  → GalaxyWebSocketClient.kt（WebSocket 连接建立）
  → 发送 capability_report 消息（AIP v3 格式）

V2 侧：
  galaxy_gateway/android/bridge.py（WebSocket 入口）
  → galaxy_gateway/android/handlers/capability_report.py
    → handle_capability_report()
    → _sync_supported_actions_to_capability_authority()
      → core/unified/capability_authority.py::CapabilityAuthority.upsert_contract()
    → core/android_device_state_store.py::absorb_capability_report_semantics()
  → 能力进入 CapabilityAuthority 注册表
  → 治理决策时由 resolve_governance_path_decision() 查询能力状态
```

**层级**：实现层（V2 侧完整）。Android Kotlin 侧的 capability_report 发送逻辑已实现，但 V2 CI 中无 Kotlin Android 驱动的端到端测试。

---

### 3.2 Android 执行生命周期 → V2 执行 runtime state → 决策因果链

```
Android 侧（Kotlin）：
  DelegatedRuntimeReceiver.kt → DelegatedRuntimeUnit.kt（执行开始）
  → GoalExecutionPipeline.kt / AutonomousExecutionPipeline.kt（执行进行中）
  → 发送 goal_execution / goal_execution_result 消息

V2 侧：
  galaxy_gateway/android/handlers/goal_execution.py
    → handle_goal_execution()
      → _evaluate_execution_governance()（ExecutionType.goal_execution）
        → core/unified_execution_governance.py::evaluate_execution_governance()
    → handle_goal_execution_result()
      → _run_task_result_truth_chain()
        → core/task_result_canonical_truth_chain.py::run_task_result_truth_chain()
          → android_participant_truth_ingress：ingest truth
          → android_execution_signal_reconciler：reconcile
          → 记录 ExecutionUplinkRecord
          → notify_execution_completed()
  → get_uplink_truth_state() 可查询 canonical_outcome

决策因果链（PR 1042）：
  build_unified_governance_state()
    → get_execution_runtime_snapshot()（含 active_execution_count 等）
    → 每个路径的 decision_causality 含 active_execution_count, blocked_execution_types
    → panel surface 反映实时 execution runtime state
```

**层级**：实现层（主链路存在）。V2-side 回归证明层（`tests/test_pr06_execution_governance_hardening.py`）覆盖 truth state 字段。跨仓运行时接地证明缺失（所有集成测试使用 Python mock 客户端）。

---

### 3.3 Android 连续性 / 重连 / 恢复 → V2 规范恢复闭合

```
Android 侧（Kotlin）：
  GalaxyWebSocketClient.kt（含重连逻辑）
  → 断连后重新注册 device_register

V2 侧：
  handle_device_register()（registration.py）
    → 查询 device_registry（是否已有记录）
    → HybridOrchestrationContinuityRegistry 重连语义
    → android_v2_continuity_contract.py::AndroidV2ContinuityContract

协议回归：
  tests/integration/test_v2_android_protocol_regression.py::TestReconnectPath
    → test_reconnect_restores_connected_state()（使用 MagicMock WebSocket）
  tests/test_pr6_hybrid_continuity_closure.py（V2 单元测试）
```

**层级**：V2 主链路实现层。重连协议回归测试使用 Python MagicMock（非真实 Kotlin）。`test_separated_process_ws_e2e.py::test_reconnect_reregisters_network_e2e` 使用真实 TCP/WebSocket 但 Python 客户端——比 MagicMock 更真实，但仍非 Kotlin Android。

---

### 3.4 Android 委托接管 → V2 truth 裁定 → resumed ownership transfer

```
Android 侧（Kotlin）：
  TakeoverEligibilityAssessor.kt（评估是否满足接管条件）
  → TakeoverEnvelope.kt（构建接管信封）
  → DelegatedTakeoverExecutor.kt（执行接管后本地操作）
  → HandoffEnvelopeV2.kt / DelegatedHandoffContract.kt（handoff 合约）
  → 发送 takeover_response 消息

V2 侧：
  galaxy_gateway/android/handlers/takeover_response.py
    → _resolve_session_id_for_takeover_response()
    → _get_lifecycle_coordinator().on_takeover_response()
      → core/android_delegated_runtime_lifecycle_coordinator.py
        → takeover_tracking.py：记录接管决策
        → 减少参与者会话阶段
        → 记录统一审计事件
        → 返回 ACK

handoff_v2_result path：
  handle_handoff_v2_result()（handoff_v2_result.py）
    → 处理接管执行结果 uplink
```

**层级**：V2 侧 handler 实现层。Android Kotlin 侧的接管流程已定义。但从"接管成功"到"ownership 完整转移回 V2 并被确认"的完整闭环缺少端到端回归测试。`tests/test_android_takeover_protocol.py` 存在但限于 V2 内部 handler 行为。

---

### 3.5 Android mesh 参与 / 就绪 / 证明质量 → V2 mesh runtime state → 治理就绪影响

```
Android 侧（Kotlin）：
  LocalCollaborationAgent.kt（本地协作代理）
  AndroidMeshParticipationContract.kt（mesh 参与合约）
  → 参与协调会话（Pr8AndroidMeshParticipationContractTest.kt 中有 Kotlin 测试）

V2 侧：
  core/mesh/mesh_runtime_center_state.py
    → evaluate_center_runtime_status(coordinator_state)
    → build_mesh_runtime_center_state(coordinator_state=None)
  → core/unified_governance_semantics.py::build_mesh_runtime_state()
    → 集成 center_runtime_state（PR 1043）
    → 输出 proof_quality（live/stale/structurally_inferred/missing）
    → governance_readiness_impact
  → resolve_governance_path_decision()
    → multimodal_participation 路径在 cross_device 模式下当 mesh_proof_quality 非 live 时被阻塞

关键问题：
  build_mesh_runtime_center_state(coordinator_state=None) 中
  coordinator_state=None 是默认值——无真实 Android mesh 参与时，输出为 pending_participants 状态
  proof_quality 此时为 structurally_inferred 或 missing，而非 live
```

**层级**：V2 侧实现层（状态机定义、快照面集成均成立）。但 proof_quality=live 在生产中需要真实 Android mesh 参与（`last_live_run_at` 时间戳需在 300 秒内）。当前无此证据。

---

### 3.6 Android 诊断 / 可观测性信号 → V2 panel/operator/audit 面

```
Android 侧（Kotlin）：
  app/src/main/java/com/ufo/galaxy/observability/（目录存在）
  → 诊断 payload 通过 WebSocket 发送

V2 侧：
  galaxy_gateway/android/handlers/diagnostics.py::handle_diagnostics_payload()
  core/android_delegated_runtime_audit.py（审计面）
  core/execution_governance_audit_authority.py（PR-14：治理审计权威）
    → build_governance_authority_evidence()
    → verify_governance_authority_integrity()
    → get_governance_audit_summary()
  core/routes/panel.py（/api/v1/panel/unified）
  core/routes/operator.py（/api/v1/operator/action）
```

**层级**：V2 侧审计结构实现层。`handle_diagnostics_payload()` 主路径存在。PR-14 治理审计权威的 41 个测试（Groups A-E）覆盖 V2 内部链。但 Android 诊断 payload → V2 audit surface → operator 可见性的端到端路径缺乏系统性回归。

---

## 四、穷举问题审查

### 问题 1：能力漂移（Capability Drift）

**现象**：Android 本地能力状态（开/关/降级）与 V2 `CapabilityAuthority` 中记录的状态可能分歧。

**代码锚点**：
- V2：`core/canonical_capability_status.py`、`CapabilityAuthority.upsert_contract()`
- Android：`capability/`目录（Android 仓）
- 触发路径：Android capability 变更后，仅在下次 capability_report 上报时才更新 V2

**问题类型**：Governance Gap / Runtime Gap

**严重性**：中

**影响**：V2 的 `resolve_governance_path_decision()` 可能基于过时的能力状态做出错误的 dispatch_eligible 判断，导致被分配了任务的 Android 节点实际上无法执行。

---

### 问题 2：schema 漂移（Schema Drift）

**现象**：Android AIP v3 消息格式与 V2 handler 期望的 schema 之间可能漂移。

**代码锚点**：
- V2：`galaxy_gateway/android/handlers/*.py`（各 handler 直接 `.get()` 字段）
- Android：`protocol/`目录（Android 仓）
- 测试：`tests/integration/test_v2_android_protocol_regression.py`（用 Python 构建的 AIP v3 消息）

**问题类型**：Protocol Gap / Governance Gap

**严重性**：中高

**影响**：Android Kotlin 端修改消息格式后，V2 handler 可能静默失败（`None` 值被当做有效数据处理）。现有测试均用 Python 构建消息，无法捕获真实 Kotlin 端的 schema 变更。

---

### 问题 3：执行 runtime truth 漂移（Execution Runtime Truth Drift）

**现象**：`_LIVE_EXECUTION_GOVERNANCE_STATE` 是 V2 侧的内存字典；当 Android 节点断连后，V2 侧的执行状态不会自动清除或标记为 stale。

**代码锚点**：
- `core/unified_execution_governance.py`（`_LIVE_EXECUTION_GOVERNANCE_STATE` 全局字典）
- `get_uplink_truth_state()`（查询此字典）
- `handle_device_status()` / `handle_heartbeat()`（断连检测路径）

**问题类型**：Core Runtime Gap

**严重性**：高

**影响**：Android 断连后，V2 的 `execution_runtime_state` 可能继续显示"有活跃执行"，导致 `decision_causality` 中的 `active_execution_count` 误导调度决策；panel 显示与真实状态不符。

---

### 问题 4：弱/部分/过时证明被高估（Weak/Partial/Stale Proof Overstated）

**现象**：PR 1041 的 77.3% 整体完成度存在高估，原因是部分域将"定义层存在"记为"实现层成立"。

**具体例子**：
- D3（Android runtime node）：68% 主要基于 V2 侧的 handler 存在，而非真实 Kotlin Android 节点的 V2 CI 证明
- D4（mesh/hybrid）：62% 包含了定义存在的分值，但无 runtime_closed 可达证据
- D8（manifestation/carrier）：72% 包含了语义定义，但无真实跨仓运行证明

**代码锚点**：
- `core/joint_dual_repo_cognition_closure_review.py`（`domain_scores` 计算）
- `tests/test_joint_dual_repo_cognition_closure_review.py`（仅验证 scorecard 结构，不验证真实执行）

**问题类型**：Definition Fulfillment Gap / Proof Gap

**严重性**：中高（影响决策准确性）

---

### 问题 5：Mock E2E 被误认为真实 E2E

**现象**：`test_dual_repo_transport_harness.py`、`test_v2_android_protocol_regression.py` 等文件标题和注释声称是"cross-repo"或"protocol regression"测试，但实际上 Android 侧使用 Python MagicMock 或 Python WebSocket 客户端。

**代码锚点**：
- `tests/integration/test_dual_repo_transport_harness.py`：`from unittest.mock import AsyncMock, MagicMock`；`AndroidProtocolClient` 是 Python 类
- `tests/integration/test_v2_android_protocol_regression.py`：`_make_ws() -> MagicMock`
- `tests/integration/test_separated_process_ws_e2e.py`：使用 Python `websockets` 客户端（非 Kotlin）

**问题类型**：Proof Gap

**严重性**：高（创造虚假安全感）

**影响**：CI 绿色不代表真实 Android Kotlin 行为符合预期；协议兼容性只被 Python 模拟端验证。

---

### 问题 6：Android 本地状态与 V2 规范状态的静默分歧

**现象**：Android 本地有 `AndroidAppLifecycleTransition.kt`、`AndroidRuntimeBridge.kt` 等管理本地状态的类；这些状态变化不会自动同步到 V2，V2 只在收到上行消息时才更新状态。

**代码锚点**：
- Android：`runtime/AndroidAppLifecycleTransition.kt`、`agent/AgentRuntimeBridge.kt`
- V2：`core/android_participant_session_state.py`、`core/android_device_state_store.py`
- 同步触发：仅在 heartbeat、capability_report、goal_execution_result 等上行消息时

**问题类型**：Runtime Gap / Governance Gap

**严重性**：中高

**影响**：Android 内部状态（如执行中/暂停/降级）与 V2 侧记录的状态可能长期不同步；V2 基于过期状态做出的治理决策可能错误。

---

### 问题 7：resumed ownership transfer 证明不足

**现象**：接管流程（takeover）的代码路径存在，但"接管完成 → Android 端执行完毕 → 结果回传 V2 → V2 确认 ownership 转移"的完整闭环缺乏端到端回归证明。

**代码锚点**：
- V2：`handle_takeover_response()` → `lifecycle_coordinator.on_takeover_response()` ✅
- V2：`handle_handoff_v2_result()` ✅（handler 存在）
- 测试：`tests/test_android_takeover_protocol.py`（V2 handler 内部行为）
- 缺失：V2 takeover_request → Android 接管执行 → handoff_v2_result uplink → V2 ownership 确认的完整链路测试

**问题类型**：Proof Gap / Core Runtime Gap

**严重性**：高

**影响**：生产中 takeover 场景的完整性无法保证；DelegatedHandoffContract.kt 是否被正确调用无 V2 可验证证据。

---

### 问题 8：mesh runtime_closed 在真实代码中不可达

**现象**：PR 1043 定义了 `MeshRuntimeCenterStatus.runtime_closed` 状态，并在 116 个测试中验证了状态机逻辑。但在真实生产系统中，到达 `runtime_closed` 需要：(1) 多个 Android 设备连接、(2) 所有参与者完成 barrier 协调、(3) 结果合并完成。当前无任何真实 mesh 协调运行记录。

**代码锚点**：
- `core/mesh/mesh_runtime_center_state.py::MeshRuntimeCenterStatus.runtime_closed`（定义存在）
- `evaluate_center_runtime_status(coordinator_state=None)` → 返回 `MeshRuntimeCenterStatus.pending_participants`
- `tests/test_pr03_mesh_runtime_center_closure.py` Group J：通过 mock coordinator 测试 runtime_closed 路径
- 缺失：真实多节点 Android mesh 协调运行中达到 runtime_closed 的证据

**问题类型**：Core Runtime Gap / Definition Fulfillment Gap

**严重性**：高

**影响**：PR 1043 定义的状态机在生产中无法完整执行；`governance_readiness_impact` 中基于 runtime_closed 的判断永远不会触发真实行为改变。

---

### 问题 9：诊断 / 审计不足（Diagnostics/Audit Insufficiency）

**现象**：`handle_diagnostics_payload()` 存在，PR-14 治理审计权威存在（`execution_governance_audit_authority.py`），但：
1. Android 诊断信号格式与 V2 audit surface 的连接路径缺乏自动化测试
2. 治理决策的可解释性链路（为何做出此决策）在 operator panel 上的呈现不完整
3. `build_governance_authority_evidence()` 的输出未被整合进 `/api/v1/panel/unified` 响应中

**代码锚点**：
- `core/execution_governance_audit_authority.py::build_governance_authority_evidence()`
- `galaxy_gateway/android/handlers/diagnostics.py::handle_diagnostics_payload()`
- `core/routes/panel.py`（`/api/v1/panel/unified`）
- `tests/test_pr14_governance_audit_authority.py`（41 tests，覆盖 V2 内部）

**问题类型**：Observability Gap

**严重性**：中

**影响**：生产故障时无法通过 panel 快速定位 Android 节点的诊断信息；治理决策的可审计性不足。

---

### 问题 10：定义措辞过度宣称真实代码履行

**现象**：PR 993 和 PR 1041 中的部分措辞（如"Android 已是强 runtime node"、"超越 PoC 阶段"）基于"结构/定义存在"推导，而非"runtime 证明"。这些措辞如果不加区分地被后续决策引用，会产生误导。

**具体例子**：
- PR 993："Android 已是强 runtime node，不是被动终端" → 基于 Kotlin 代码存在，而非 V2 可验证的 Kotlin 运行行为
- PR 1041："D7 observability 95%完成" → panel 面存在，但跨仓实时接地性未验证

**问题类型**：Definition Fulfillment Gap

**严重性**：中高（影响后续 PR 计划的优先级判断）

---

## 五、假 E2E vs 真 E2E 分类

| 测试文件 | 类型 | 实际证明了什么 | 不能证明什么 |
|---|---|---|---|
| `tests/test_pr03_mesh_runtime_center_closure.py`（116 tests） | **V2 单元测试** | 状态机逻辑、转换表正确性、各状态路径的 V2 侧代码行为 | 真实 Android mesh 参与；runtime_closed 在真实系统中可达 |
| `tests/test_pr06_execution_governance_hardening.py` | **V2 单元测试** | V2 execution lifecycle、uplink truth state 字段正确性 | 真实 Android 驱动的 lifecycle event 序列 |
| `tests/test_android_mode_switch_integration.py` | **V2 集成（Python stub）** | V2 侧 Android 模式门政策；handler 接受/拒绝模式切换请求 | 真实 Android 发起的模式切换行为 |
| `tests/integration/test_dual_repo_transport_harness.py` | **V2 集成（Python mock 客户端）** | WebSocket 传输层协议格式；handler 调用路径；Python-模拟-Android 侧行为 | 真实 Kotlin Android WebSocket 连接行为；Kotlin 侧的消息格式实现 |
| `tests/integration/test_v2_android_protocol_regression.py` | **协议回归（Python mock）** | V2 handler 对 AIP v3 消息格式的处理鲁棒性；reconnect/offline-queue/duplicate result 路径 | 真实 Kotlin Android 侧的协议实现；真实重连行为 |
| `tests/integration/test_separated_process_ws_e2e.py` | **跨进程 mock 运行时（最接近真实但仍是 Python 客户端）** | 真实 TCP/WebSocket 网络栈；两进程间通信；register→capability→task_assign→task_result 完整链路（Python 客户端） | 真实 Kotlin Android APK 的行为；Kotlin 协程/WebSocket 实现；Android 系统 API 调用 |
| `tests/integration/test_android_runtime_e2e.py` | **V2 集成（AsyncMock）** | V2 侧 runtime 集成逻辑 | 真实 Android runtime 行为 |
| `app/src/test/java/com/ufo/galaxy/runtime/Pr8AndroidMeshParticipationContractTest.kt`（Android 仓） | **Android 单元测试（JVM，非 Kotlin-Instrumented）** | Android 侧 mesh participation contract 的本地 JVM 行为 | V2 ↔ Android 双向 runtime 行为；V2 侧对 Android mesh 状态的感知 |

**核心发现**：
- **所有 V2 CI 测试中，Android 侧均为 Python 实现（MagicMock、AsyncMock 或 Python WebSocket 客户端）**
- **不存在任何真实双进程两语言（Python V2 + Kotlin Android）的端到端测试**
- 最接近真实的是 `test_separated_process_ws_e2e.py`，但其"Android 侧"仍是 Python `websockets` 客户端

---

## 六、问题清单与分类

| # | 问题 | 代码锚点 | 类型 | 严重性 | 影响 |
|---|---|---|---|---|---|
| G1 | mesh_runtime_closed 在生产中不可达 | `mesh_runtime_center_state.py`, `tests/test_pr03_mesh_runtime_center_closure.py` | **Core Runtime Gap** | 🔴 高 | PR 1043 定义的状态机无法被真实系统触发；governance_readiness_impact 永远不会基于 runtime_closed 变化 |
| G2 | 无真实 Kotlin Android 端到端运行证明 | 所有 `tests/integration/` 文件 | **Proof Gap** | 🔴 高 | CI 绿色≠真实 Android 行为符合预期；协议漂移不会被捕获 |
| G3 | resumed ownership transfer 闭环缺失 | `handle_takeover_response()`, `handle_handoff_v2_result()` | **Proof Gap / Core Runtime Gap** | 🔴 高 | 接管场景的完整性无法保证 |
| G4 | 执行 runtime truth 不清除（断连后 stale） | `_LIVE_EXECUTION_GOVERNANCE_STATE`（内存字典） | **Core Runtime Gap** | 🔴 高 | 断连后 active_execution_count 误导调度；panel 显示错误 |
| G5 | capability 漂移无自动检测 | `CapabilityAuthority.upsert_contract()`, Android capability 目录 | **Governance Gap** | 🟡 中高 | V2 基于过时能力状态做 dispatch_eligible 判断 |
| G6 | schema 漂移无跨仓测试 | `galaxy_gateway/android/handlers/*.py`, Android `protocol/` | **Protocol Gap** | 🟡 中高 | Kotlin 侧消息格式变更不会被 V2 CI 捕获 |
| G7 | Android 本地状态与 V2 canonical state 静默分歧 | `android_participant_session_state.py`, Android `runtime/` | **Runtime Gap** | 🟡 中高 | 治理决策基于过期状态 |
| G8 | 完成度评分（77.3%）部分高估 | `joint_dual_repo_cognition_closure_review.py` | **Definition Fulfillment Gap** | 🟡 中 | 影响后续 PR 优先级判断；高估完成度导致忽视关键缺口 |
| G9 | 诊断信号 → audit surface 链路弱 | `handle_diagnostics_payload()`, `execution_governance_audit_authority.py` | **Observability Gap** | 🟡 中 | 故障时无法快速定位 Android 节点问题 |
| G10 | multimodal 主链端到端无运行证明 | `handle_vision_request()`, Android `speech/`, `inference/` | **Proof Gap / Runtime Gap** | 🟡 中 | 多模态链路在生产中的完整性未验证 |
| G11 | mesh participation contract 未与 V2 coordinator 实时集成 | `evaluate_center_runtime_status(coordinator_state=None)` | **Implementation Gap** | 🟡 中 | coordinator_state 默认 None；Android 参与状态不驱动 V2 mesh state 变化 |
| G12 | 定义措辞过度宣称 | PR 993 / PR 1041 叙述 | **Definition Fulfillment Gap** | 🟡 中 | 后续决策可能基于夸大的完成度估计 |

---

## 七、集成 PR 计划（双仓路线图）

### 优先级排序原则
- **必须做**（P0）：影响运行时正确性或生产安全性
- **重要**（P1）：影响系统完整性证明
- **增强**（P2）：提升可观测性和可维护性

---

### PR-A（V2 仓）：执行 runtime truth 生命周期管理（P0）

**目标**：解决 G4 — 断连后执行状态不清除导致的 stale truth

**关键落地区域**：
- `core/unified_execution_governance.py`：添加 `mark_device_executions_stale(device_id)` 函数
- `galaxy_gateway/android/handlers/registration.py`：断连/重连时调用清除逻辑
- `galaxy_gateway/android/bridge.py`：WebSocket 关闭回调中触发 stale 标记

**依赖**：无

**验收标准**：
- 设备断连后 `get_execution_runtime_snapshot()` 中该设备的 `active_execution_count` 变为 0
- V2-side 回归测试覆盖断连→stale→重连→恢复路径

**定义满足度**：PR 1042 定义的 `execution_runtime_state` 从"可能过时"→"接地正确"

---

### PR-B（V2 仓）：协议 schema 守卫与漂移检测（P0）

**目标**：解决 G6 — AIP v3 消息格式漂移无检测机制

**关键落地区域**：
- `galaxy_gateway/android/models.py`：添加 Pydantic schema 验证
- `galaxy_gateway/android/handlers/*.py`：使用 schema 模型而非直接 `.get()` 访问
- `tests/integration/`：基于 schema 的协议合规性测试

**依赖**：无

**验收标准**：
- Android 消息格式变更后，V2 侧产生明确的 schema 验证错误而非静默失败
- schema 模型与 Android `protocol/` 目录中的 Kotlin data class 对齐（需双仓协作）

**定义满足度**：PR 993 定义的"跨仓语义一致性"从弱保证→有 schema gate

---

### PR-C（V2 仓）：接管 ownership transfer 端到端回归（P0）

**目标**：解决 G3 — resumed ownership transfer 闭环缺失

**关键落地区域**：
- `tests/integration/test_takeover_ownership_transfer_e2e.py`（新建）
- 覆盖路径：V2 发 takeover_request → Python mock Android 接受 → 发送 takeover_response → handoff_v2_result → V2 确认 ownership 转移
- `core/android_delegated_runtime_lifecycle_coordinator.py`：补强 on_takeover_response 后的 ownership 状态更新

**依赖**：PR-A（需要正确的 runtime state）

**验收标准**：
- 完整接管链路 V2-side 测试可重现、可回归
- `get_uplink_truth_state()` 在接管完成后正确反映 resumed ownership

**定义满足度**：PR 1041 定义的"takeover/resumed ownership transfer"从"路径存在"→"V2-side 回归证明层"

---

### PR-D（V2 仓）：capability 漂移治理（P1）

**目标**：解决 G5 — Android 本地 capability 与 V2 truth 漂移

**关键落地区域**：
- `core/android_device_state_store.py`：添加 `last_capability_report_at` 时间戳
- `core/unified_governance_semantics.py`：在 `resolve_governance_path_decision()` 中检查 capability staleness
- 添加 capability_staleness_threshold 治理配置

**依赖**：无

**验收标准**：
- capability 上报超时后，`dispatch_eligible` 降为 False
- `decision_causality` 中包含 capability_staleness 原因

**定义满足度**：PR 993 定义的"capability authority"从"静态快照"→"时效性治理"

---

### PR-E（双仓）：真实 Kotlin Android 协议集成测试框架（P1）

**目标**：解决 G2 — 无真实 Kotlin Android 端到端运行证明

**关键落地区域**：
- V2 仓：`tests/integration/kotlin_android/`（新建目录）
- Android 仓：`app/src/androidTest/` 或基于 JVM 的集成测试
- 构建一个可以在 CI 中运行的"V2 server + Kotlin Android test client"双进程测试框架
- 至少覆盖：register、capability_report、goal_execution、task_result、reconnect 五个场景

**依赖**：PR-A、PR-B

**验收标准**：
- 真实 Kotlin 代码（非 Python 模拟）连接 V2 服务器并完成完整 lifecycle
- V2 CI 可验证 Kotlin 客户端行为

**定义满足度**：所有 PR 993~1043 定义中涉及"Android 侧行为"的命题从"跨仓运行时接地证明层缺失"→"部分有跨仓运行时接地证明"

---

### PR-F（V2 仓）：mesh coordinator 实时集成（P1）

**目标**：解决 G11 — `evaluate_center_runtime_status()` 默认 `coordinator_state=None`

**关键落地区域**：
- `core/mesh/mesh_coordinator.py`：暴露实时 coordinator state
- `core/unified_governance_semantics.py::build_mesh_runtime_state()`：从实时 coordinator 获取 state 而非默认 None
- 确保多个 Android 节点连接时，mesh state 真实反映参与状态

**依赖**：PR-E（需要真实 Android 节点参与）

**验收标准**：
- 有 Android 节点参与时，`build_mesh_runtime_center_state()` 返回 `participation_ready` 而非 `pending_participants`
- 有真实完整协调循环时，`runtime_closed` 可达

**定义满足度**：PR 1043 定义的 mesh state machine 从"定义层存在"→"运行时接地"

---

### PR-G（V2 仓）：诊断 → audit surface 整合（P2）

**目标**：解决 G9 — 诊断信号 → audit surface 链路弱

**关键落地区域**：
- `core/routes/panel.py`：将 `build_governance_authority_evidence()` 集成进 `/api/v1/panel/unified` 响应
- `galaxy_gateway/android/handlers/diagnostics.py`：处理后写入统一 audit store
- `core/execution_governance_audit_authority.py`：完善 `get_governance_audit_summary()` 的 panel 输出格式

**依赖**：无

**验收标准**：
- `/api/v1/panel/unified` 响应包含 `governance_audit` 字段
- Android 诊断 payload 被记录并可从 panel 查询

**定义满足度**：PR 993 定义的"operator 聚合面"和 PR 1042 定义的"canonical runtime truth"从弱可观测→有 audit trail

---

## 八、最终中文决策结论

### 系统本质

这套联合系统（V2 + Android）**本质上是以 V2 为中心治理权威的中心分布式网络系统**：
- V2 持有规范权威、调度权威、truth 权威、证明权威
- Android 是具有本地执行能力、跨设备参与语义、接管参与能力的分布式执行节点
- 两者不是传统的客户端-服务器关系；而是中心治理节点与分布式执行节点的关系

这一系统本质定性基于真实代码成立。PR 993 的这一核心定义准确。

---

### 当前真实完成度

| 层级 | 实际完成度（审计后）| 说明 |
|---|---|---|
| 定义层 | ~90% | 主要概念/类/接口均已定义 |
| 实现层（V2 侧） | ~75% | V2 侧主链路实现成熟；部分链路存在 stale state 问题 |
| V2-side 回归证明层 | ~65% | 关键路径有测试；但 takeover 闭环、stale state 等缺测 |
| 跨仓运行时接地证明层 | ~15% | 严重缺失；所有"Android 侧"均为 Python 模拟，无真实 Kotlin 运行时证明 |

**PR 1041 报告的 77.3% 整体完成度是定义层+实现层的综合，在该框架内基本准确；但如果以"跨仓运行时接地证明"为衡量标准，实际完成度约 40-50%。**

---

### 是否真正满足 PR 993 / PR 1041~1043 定义？

| 定义 | 满足程度 | 说明 |
|---|---|---|
| PR 993 系统本质定性 | **满足（定义层/实现层）** | 代码结构证明系统是中心分布式网络系统 |
| PR 993 "Android 是强 runtime node" | **部分满足（定义层/实现层）；跨仓证明层缺失** | Kotlin 代码存在，V2 消费端成立；但无 Kotlin 运行时 V2 CI 证明 |
| PR 1041 77.3% 完成度 | **基本满足（在其方法论框架内）；但跨仓运行时接地层大幅低于预期** | scorecard 方法论本身合理；但未明确区分定义层 vs 运行时接地层 |
| PR 1042 execution_runtime_state binding | **满足（实现层 + V2-side 回归证明层）** | V2 内部绑定成立；跨仓驱动缺失 |
| PR 1043 mesh state machine | **定义层满足；runtime_closed 不可达（跨仓运行时接地层不满足）** | 状态机定义成立；但生产系统中无法触发 runtime_closed |

---

### 哪些部分已被真实代码证明

- ✅ V2 中心治理核（执行治理、治理语义、模式门、operator/panel 面）
- ✅ V2 侧 Android handler 主链路（capability_report → ingestion, goal_execution → truth chain）
- ✅ PR 1042 的 execution_runtime_state 绑定（V2 内部）
- ✅ PR 1043 的 mesh state machine 定义和状态转换逻辑（V2 单元测试覆盖）
- ✅ 重连/断连协议语义（`test_separated_process_ws_e2e.py`，Python 客户端）

### 哪些部分仅为结构性存在或证明不足

- ⚠️ Android 作为"强 runtime node"：Android 代码定义存在，V2 消费端存在；但**无 Kotlin 运行时 V2 CI 证明**
- ⚠️ mesh full runtime 闭合：定义和状态机存在；但 `runtime_closed` **在真实生产系统中不可达**
- ⚠️ resumed ownership transfer：handler 路径存在；但**完整闭环缺乏端到端回归**
- ⚠️ execution runtime truth 的时效性：`_LIVE_EXECUTION_GOVERNANCE_STATE` **断连后不自动清除**
- ⚠️ multimodal 主链：语义定义存在；**真实运行证明缺失**

---

### 顶级优先级真实缺口

1. 🔴 **执行 runtime truth stale 问题**（G4）—— 影响调度正确性，P0
2. 🔴 **无真实 Kotlin Android 端到端证明**（G2）—— 所有"Android 行为"验证依赖 Python 模拟，P0
3. 🔴 **mesh runtime_closed 不可达**（G1）—— PR 1043 的核心承诺未在生产中兑现，P0
4. 🔴 **resumed ownership transfer 闭环缺失**（G3）—— 接管语义不完整，P0
5. 🟡 **capability/schema 漂移无治理**（G5/G6）—— 运行时静默失败风险，P1

---

**总结**：这套双仓联合系统的中心分布式网络性质已成立，V2 的中心治理权威已在代码中落实。但系统当前真实完成度约处于"中期收敛后半段"（非近收口），主要缺口集中在四点：真实 Kotlin Android 运行时证明缺失、mesh runtime_closed 不可达、执行 truth stale 问题、以及接管闭环不完整。上述问题不能被 CI 绿色状态所掩盖——CI 绿色目前只证明了"Python 模拟的 Android 行为"，不证明真实 Kotlin Android 的运行时行为。

---

> 本文件基于 2026-05-10 日对两个仓库真实代码的审计，以 PR 993、PR 1041、PR 1042、PR 1043 的已合并定义为审查标准。文件不依赖任何 PR 叙事或历史设计文档作为事实来源。代码锚点均为截至审计日期的真实存在路径。
