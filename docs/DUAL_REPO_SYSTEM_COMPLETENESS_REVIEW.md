# 双仓系统完成度审查总览

> **文档类型**：Reviewer-facing 系统完成度评审 artifact  
> **覆盖范围**：`DannyFish-11/ufo-galaxy-realization-v2`（V2 控制平面）+ `DannyFish-11/ufo-galaxy-android`（Android 执行参与者）  
> **审查基准**：基于真实代码引用，不基于愿景或设计文档。  
> **代码锚点**：`core/dual_repo_system_completeness_review.py`（机器可验证版本）  
> **配套测试**：`tests/test_dual_repo_system_completeness_review.py`

---

## 快速导航

1. [这套系统是什么](#1-这套系统是什么)
2. [架构角色边界](#2-架构角色边界)
3. [五维完成度评审](#3-五维完成度评审)
4. [详细维度说明](#4-详细维度说明)
5. [Evidence Gap 列表（诚实）](#5-evidence-gap-列表诚实)
6. [Deferred / Accepted Limitation 列表](#6-deferred--accepted-limitation-列表)
7. [关键代码引用索引](#7-关键代码引用索引)
8. [距离 Fully Operational 还差什么](#8-距离-fully-operational-还差什么)

---

## 1. 这套系统是什么

Galaxy 是一套**分布式智能 Agent 系统**，采用双仓架构：

| 仓库 | 角色 | 代码锚点 |
|------|------|---------|
| `ufo-galaxy-realization-v2`（V2） | 控制平面：canonical 路由、能力调度、任务编排、truth/projection、发布治理、readiness/acceptance verdict | `core/command_router.py`, `core/capability_routing_gate.py`, `core/system_final_acceptance_verdict.py` |
| `ufo-galaxy-android`（Android） | 持久执行参与者：本地 GUI/传感器/网络执行、结果上传、mesh session 参与、handoff 执行 | Android `DelegatedRuntimeReceiver`, `GalaxyWebSocketClient`, `InputRouter` |

### 关键设计原则

- **V2 是唯一路由权威**：`CommandRouter.route_envelope()` 是唯一跨设备派发入口
- **Android 是能力 bearer**：Android 宣告能力并在本地执行，不做路由决策
- **AIP v3 是 wire protocol**：`galaxy_gateway/protocol/aip_v3.py` 定义跨端消息协议
- **Delegated flow 是核心路径**：当任务需要 Android 执行时，走 delegated canonical path

### 架构图（简化）

```text
用户请求
    │
    ▼
V2: openclawd → command_router → capability_routing_gate
    │
    ├── 本地执行 (local_agent_runtime)
    │
    └── 委托执行 (delegated_flow)
            │
            ▼
        galaxy_gateway ──── AIP v3 ────► Android GalaxyWebSocketClient
                                              │
                                    Android InputRouter / DelegatedRuntimeReceiver
                                              │
                                    Android 执行 → result → sendJson
                                              │
            ◄──── AIP v3 ────────────────────┘
            │
V2: android_delegated_signal_ingress → result_convergence → operator_surface
```

---

## 2. 架构角色边界

### V2 侧已建立的核心体系（代码 + evidence surface 级别）

| 体系 | 关键模块 | 状态 |
|------|---------|------|
| 系统级 acceptance verdict | `core/system_final_acceptance_verdict.py`（PR-17V2） | ✅ 可导入，可评估 |
| 双仓 reality audit | `core/dual_repo_system_reality_audit.py`（PR-537） | ✅ 可导入，可运行 |
| Readiness/governance 证据面 | `core/v2_readiness_governance_evidence_surface.py`（PR-6V2） | ✅ 可导入 |
| 统一发布治理 taxonomy | `core/release_governance_taxonomy.py`（PR-8） | ✅ 可导入，术语完整 |
| Android 证据摄取 | `core/android_participant_evidence_ingress.py` | ✅ 可导入，JSON 合约完整 |
| Delegated flow 决策历史 | `core/delegated_flow_decision_history.py`（PR-V2-4DH） | ✅ 可导入，结构完整 |
| Recovery truth surface | `core/recovery_truth_surface.py`（PR-5-TRUTH） | ✅ 可导入，6 维 truth atom |
| 系统认知地图 | `core/dual_repo_system_map.py` | ✅ 可导入 |

### Android 侧已建立的核心体系（从 V2 代码视角）

| 体系 | 已知代码实体 | V2 侧对应 |
|------|------------|---------|
| Delegated runtime 评估器 | `DelegatedRuntimeReadinessEvaluator`, `DelegatedRuntimeAcceptanceEvaluator`, `DelegatedRuntimePostGraduationGovernanceEvaluator`, `DelegatedRuntimeStrategyEvaluator` | `core/android_evaluator_artifact_ingress.py` |
| AIP v3 transport | `GalaxyWebSocketClient`, `AipModels.kt` MsgType enum | `galaxy_gateway/protocol/aip_v3.py` |
| 参与者生命周期 | `DelegatedRuntimeReceiver`, participant session state | `core/android_participant_session_state.py` |
| 离线任务队列 | `OfflineTaskQueue` | `core/android_participant_evidence_ingress.py`（通过 evidence）|
| Reconciliation signal（DTO 层） | `ReconciliationSignal.kt`（PR-51） | **尚无对应 gateway handler**（见 Gap #1）|

---

## 3. 五维完成度评审

> 机器可验证版本见：`core/dual_repo_system_completeness_review.py`  
> 每个维度的具体含义在模块 docstring 中有完整说明。

| 维度 | 标签 | 说明 |
|------|------|------|
| **架构 / 结构成熟度** | ✅ `structure_only → complete` | 模块可导入，边界清晰，文档完整，但 runtime 闭环需单独评估 |
| **Runtime 闭合成熟度** | ⚠️ `evidence_gap` | 结构完整，但 delegated flow 从未在此环境端到端运行过；deferred 边界已诚实记录 |
| **跨仓证据成熟度** | ⚠️ `evidence_gap` | V2 摄取模块存在，但 ReconciliationSignal wire 层缺失，Android 证据无法通过 live 路径到达 V2 |
| **治理 / 发布 Readiness 成熟度** | ⚠️ `evidence_gap` | 框架完整，但 release gate 处于 advisory 非阻断模式，未接入 CI/CD pipeline |
| **真实设备 / 多设备闭合成熟度** | ⏳ `deferred` | 多设备协调结构存在，但无真实设备证据 artifact，无 CI 自动化，多设备同时重连 ordering 已明确 deferred |

### 系统级综合判断

**当前系统总体处于：`partial_closure_gaps_present`（部分闭合，存在 evidence gap）**

- **不是** `fully_closed`：有多个 evidence gap（wire 层、enforcement、real-device CI）
- **不是** `structural_only`：超过 2 个维度已超出纯结构层
- **不是** `critical_evidence_gaps`：核心路径（架构 + 基础执行）已实质完成
- **是** `partial_closure_gaps_present`：大多数维度有实质实现，但有明确未闭合点

---

## 4. 详细维度说明

### 4.1 架构 / 结构成熟度

**代码证据：**
- `core/system_final_acceptance_verdict.py`：五维 acceptance 聚合，PR-17V2
- `core/dual_repo_system_reality_audit.py`：代码驱动的 5 维双仓 reality audit，PR-537
- `core/v2_readiness_governance_evidence_surface.py`：可审查的 evidence 面，PR-6V2
- `core/release_governance_taxonomy.py`：统一 taxonomy，PR-8（blocking vs advisory, deferred vs evidence_gap 等术语全部定义）
- `core/dual_repo_system_map.py`：系统认知地图，区分 RUNTIME_CRITICAL / SEMI_EXECUTABLE / DECLARATIVE
- 5 份 joint system review 文档（`docs/joint_system_review/`）

**诚实说明：** 这一维度的"complete"特指代码结构层面。架构层已明确建立，边界清晰，reviewer 可以通过 `core/dual_repo_system_map.py` 理解每个模块的 semantic type（是 runtime critical 还是 declarative only）。

### 4.2 Runtime 闭合成熟度

**已有：**
- `core/flow_continuity_coordinator.py`：7 种 continuity 场景
- `core/delegated_flow_recovery_coordinator.py`：recovery 协调
- `core/recovery_durability_closure_validator.py`：PR-5V2 recovery 闭合验证
- `core/recovery_truth_surface.py`：6 维 truth atom，区分 v2_internal / participant_reconnect / task_continuity / authority_state_alignment
- `core/delegated_flow_decision_history.py`：决策历史结构完整

**Evidence Gap（诚实）：**
- `HistoryEvidenceStatus = no_history_yet`：在全新环境中，delegated flow 从未被端到端运行过，`runtime_closure_established = False`
- 结构完整 ≠ 运行时闭合；"代码存在"≠"曾经运行"

**Deferred（已诚实记录在 `recovery_truth_surface`）：**
- Android offline queue replay ordering authority
- Ephemeral transport binding after reconnect
- Multi-device simultaneous reconnect ordering authority

### 4.3 跨仓证据成熟度

**已有：**
- `core/android_participant_evidence_ingress.py`：文件合约机制，支持 Android 证据 JSON artifact 摄取
- `core/android_participant_truth_ingress.py`：truth signal ingress
- `core/android_evaluator_artifact_ingress.py`：evaluator artifact ingress
- `core/android_handoff_v2_response_ingress.py`：handoff response ingress（V2 侧）

**Critical Evidence Gaps（代码验证，见 `docs/joint_system_review/04_cross_repo_contract.md §2.3`）：**

**Gap #1：ReconciliationSignal AIP wire 层缺失（最关键）**

```text
Android ReconciliationSignal.kt (PR-51) 内部 DTO 存在
DelegatedRuntimeReadinessEvaluator 设计意图：通过 reconciliation signal channel 转发
但 AipModels.kt 的 MsgType enum 无 reconciliation_signal 条目
→ ReconciliationSignal 未被序列化到 AIP v3 wire 格式
→ Android readiness/acceptance/governance/strategy artifact 无法到达 V2
→ V2 的 readiness/governance verdict 缺少 Android 端维度输入
```

**Gap #2：HandoffEnvelopeV2 response gateway handler 缺失（高优先级）**

```text
Android 有 handoff_envelope_v2_result MsgType 和 HandoffEnvelopeV2ResultPayload
V2 有 core/android_handoff_v2_response_ingress.py
但 galaxy_gateway/android/handlers/ 无 handoff_response.py
android_bridge.py 无 handle_handoff_response import
→ Android handoff result 到达 V2 后进入 else 分支（未处理）
→ handoff 链路是单向信道
```

### 4.4 治理 / 发布 Readiness 成熟度

**已有（框架层面）：**
- `core/delegated_flow_readiness_gate.py`：5 维 readiness gate（PR-9V2）
- `core/delegated_flow_acceptance_gate.py`：graduation verdict（PR-10V2）
- `core/delegated_flow_post_graduation_governance.py`：持续治理（PR-11V2）
- `core/distributed_release_gate_skeleton.py`：release gate 骨架（PR-7V2）
- `core/governance_validation_gate.py`：governance validation
- `core/release_blocking_gate.py`：阻断门控

**Evidence Gaps（诚实）：**
- `distributed_release_gate_skeleton.is_enforcing = False`：当前处于 advisory/非阻断模式，不会真正阻断发布
- Release gate 未接入 CI/CD pipeline：governance verdict 不会自动阻止 release
- Android 侧 governance artifact 因 wire 层缺失无法进入 V2 gate（见 Gap #1）

**术语统一状态：**
- `release_governance_taxonomy`（PR-8）已统一定义 blocking vs advisory, evidence_gap vs deferred vs unresolved 等核心术语
- 各个 gate 模块在 import 层面与 taxonomy 对齐

### 4.5 真实设备 / 多设备闭合成熟度

**已有（结构层）：**
- `core/multi_device_coordination_authority.py`
- `core/multi_device_truth_convergence.py`
- `core/multi_device_runtime_harness.py`
- `core/cross_device_execution_chain.py`
- `core/attached_runtime_recovery_readiness.py`
- `core/android_participant_evidence_ingress.py`（文件合约支持 real-device evidence 摄取）

**Deferred / Evidence Gaps：**
- 无真实 Android 设备证据 artifact（`ANDROID_PARTICIPANT_EVIDENCE_PATH` 未设置或文件不存在）
- 无 CI 自动化覆盖 real-device 场景
- 多设备同时重连 ordering authority：明确 deferred（`recovery_truth_surface.deferred_boundaries`）

---

## 5. Evidence Gap 列表（诚实）

> 以下为代码验证的 gap，不是设计意图的不足，而是当前代码中确实存在的断层。

### Gap #1（Critical）：ReconciliationSignal AIP wire 层缺失

- **影响维度**：cross_repo_evidence, governance_release_readiness
- **代码验证**：`docs/joint_system_review/04_cross_repo_contract.md §2.3`
- **具体断层**：`AipModels.kt` MsgType enum 无 `reconciliation_signal` 条目
- **后果**：V2 readiness/governance verdict 缺少 Android 端维度；Android DeviceReadinessArtifact 等无法到达 V2

### Gap #2（High）：HandoffEnvelopeV2 response gateway handler 缺失

- **影响维度**：cross_repo_evidence, runtime_closure
- **代码验证**：`docs/joint_system_review/04_cross_repo_contract.md §1.2`
- **具体断层**：`galaxy_gateway/android/handlers/` 无 `handoff_response.py`；`android_bridge.py` 无对应 import
- **后果**：handoff 链路是单向信道（V2 发出但不接收反馈）

### Gap #3（Medium）：Release gate 处于 advisory 非阻断模式

- **影响维度**：governance_release_readiness
- **代码验证**：`core/distributed_release_gate_skeleton.py` `is_enforcing` 属性
- **具体断层**：`evaluate_distributed_release_gate()` 返回 `is_enforcing = False`
- **后果**：governance verdict 不会自动阻止 release

### Gap #4（Medium）：Delegated flow 从未被端到端运行过

- **影响维度**：runtime_closure
- **代码验证**：`core/delegated_flow_decision_history.py` HistoryEvidenceStatus
- **具体断层**：在全新环境中 `runtime_closure_established = False`，`evidence_status = no_history_yet`
- **后果**：无法证明 delegated canonical path 在 runtime 层面确实工作

### Gap #5（Medium）：无真实设备 CI 自动化

- **影响维度**：real_device_multi_device
- **代码验证**：`ANDROID_PARTICIPANT_EVIDENCE_PATH` 在 CI 中未设置
- **具体断层**：real-device 场景无 automated CI 覆盖
- **后果**：多设备 / 真实设备结论无自动化验证支持

---

## 6. Deferred / Accepted Limitation 列表

> 这些是已经被诚实承认的延迟项，不是 failure，但也不是 complete。

| 条目 | 来源 | 说明 |
|------|------|------|
| Android offline queue replay ordering authority | `core/recovery_truth_surface.py` `deferred_boundaries` | Android 离线队列重放顺序权威：已 deferred |
| Ephemeral transport binding after reconnect | `core/recovery_truth_surface.py` `deferred_boundaries` | 重连后 transport 绑定：已 deferred |
| Multi-device simultaneous reconnect ordering | `core/recovery_truth_surface.py` `deferred_boundaries` | 多设备同时重连顺序权威：已 deferred |
| Real-device CI automation | `core/android_participant_evidence_ingress.py` 文件合约已就绪，CI pipeline 未建立 | 文件合约可以桥接，但 CI 层待完成 |
| Legacy path default-off enforcement | `docs/joint_system_review/05_maturity_assessment.md §4` | 依赖信号流完整建立后 |
| Auto-rollback on governance violation | `core/delegated_flow_post_graduation_governance.py` 框架存在 | 自动触发器未连接 |
| Takeover executor full implementation | `AipModels.kt` KDoc "full takeover executor deferred to PR-5" | Android 侧延迟 |

---

## 7. 关键代码引用索引

> Reviewer 可以通过这些入口深入理解系统各层。

### V2 侧系统级 surfaces

| 模块 | 作用 | PR |
|------|------|-----|
| `core/system_final_acceptance_verdict.py` | 五维系统级 acceptance verdict 聚合 | PR-17V2 |
| `core/dual_repo_system_reality_audit.py` | 代码驱动的 5 维 reality audit | PR-537 |
| `core/v2_readiness_governance_evidence_surface.py` | 可审查的 readiness/governance 证据面 | PR-6V2 |
| `core/release_governance_taxonomy.py` | 统一发布治理术语 taxonomy | PR-8 |
| `core/dual_repo_system_map.py` | 双仓系统认知地图 | - |
| `core/dual_repo_system_completeness_review.py` | 本 PR 新增：可导出的完成度审查 artifact | PR-REVIEW |

### V2 侧核心路径

| 模块 | 作用 |
|------|------|
| `core/command_router.py` | 唯一跨设备派发入口 |
| `core/capability_routing_gate.py` | 能力路由门控 |
| `core/delegated_flow_readiness_gate.py` | Delegated 路径 readiness 门控（PR-9V2）|
| `core/delegated_flow_acceptance_gate.py` | Acceptance graduation 门控（PR-10V2）|
| `core/delegated_flow_decision_history.py` | 决策历史 + runtime closure 评估（PR-V2-4DH）|
| `core/recovery_truth_surface.py` | 结构化 recovery truth atoms（PR-5-TRUTH）|
| `core/android_participant_evidence_ingress.py` | Android 证据 JSON 合约摄取 |

### V2 侧 Android 信号摄取

| 模块 | 处理信号 |
|------|---------|
| `core/android_delegated_signal_ingress.py` | `delegated_execution_signal` |
| `core/android_execution_signal_reconciler.py` | `task_result`, `task_end`, `goal_execution_result`, `error` |
| `core/android_handoff_v2_response_ingress.py` | `handoff_ack`, `handoff_result`, `handoff_failure` |
| `core/android_participant_truth_ingress.py` | `session_snapshot`, `readiness_assessment`, `task_phase`, `runtime_state` |

### 跨仓 contract 文档

| 文档 | 内容 |
|------|------|
| `docs/joint_system_review/04_cross_repo_contract.md` | 双仓 contract/signal 闭环审查（含已验证 gap）|
| `docs/joint_system_review/05_maturity_assessment.md` | 成熟度分层评估（含成熟度总表）|
| `docs/CROSS_REPO_SIGNAL_CLOSURE_VALIDATION_MATRIX.md` | 跨仓信号闭合验证矩阵 |
| `docs/ANDROID_V2_JOINT_CONTINUITY_CONTRACT.md` | Android-V2 联合连续性合约 |

### 关键测试文件

| 测试 | 覆盖 |
|------|------|
| `tests/test_pr17_v2_system_final_acceptance_verdict.py` | System acceptance verdict 完整测试（52 个测试点）|
| `tests/test_pr537_dual_repo_system_reality_audit.py` | Dual-repo reality audit 测试 |
| `tests/test_dual_repo_system_map.py` | 系统认知地图不变式测试 |
| `tests/test_dual_repo_system_completeness_review.py` | 本 PR 新增：完成度审查 artifact 测试 |

---

## 8. 距离 Fully Operational 还差什么

按优先级排序：

### 必须完成（blocking）

1. **建立 ReconciliationSignal AIP wire 层**（最高优先级）
   - 在 `AipModels.kt` 新增 `MsgType.RECONCILIATION_SIGNAL`
   - 新建 `ReconciliationSignalPayload` data class
   - 在 `RuntimeController.kt` 实现发送路径
   - 在 V2 新增 `galaxy_gateway/android/handlers/reconciliation_signal.py`
   - 在 `android_participant_truth_ingress.py` 处理 `PARTICIPANT_STATE` kind

2. **挂接 HandoffEnvelopeV2 response gateway handler**
   - 在 V2 新增 `galaxy_gateway/android/handlers/handoff_response.py`
   - 在 `android_bridge.py` 注册 handler
   - 确保调用 `core/android_handoff_v2_response_ingress.py`

3. **将 release gate 接入 CI/CD pipeline**
   - `distributed_release_gate_skeleton` 的 `is_enforcing` 改为 True 或接入 CI 触发器
   - governance verdict 可自动阻止不合规的 release

4. **端到端运行 delegated flow 一次**（以证明 runtime closure）
   - `delegated_flow_decision_history` 记录到 `observed_and_closed` 状态
   - `runtime_closure_established = True`

### 建议完成（advisory）

5. **建立真实设备 CI 自动化**
   - 设置 `ANDROID_PARTICIPANT_EVIDENCE_PATH` 在 CI 中指向真实设备证据文件
   - 建立 multi-device e2e 测试 job

6. **完成 deferred 边界中的 offline queue replay ordering**
   - 从 `deferred` 升级到有明确 authority 规则的实现

### 已经是 accepted limitation（不影响 release 判断的前提下）

- 多设备同时重连 ordering：已明确 deferred，不是 blocking
- Legacy path default-off：依赖以上 blocking 项完成后推进
- Auto-rollback on governance violation：中期目标

---

## 附录：系统当前完成度一句话总结

> **这套系统已建立了完整的 delegated canonical path 骨架、双端治理评估框架、统一 taxonomy，以及完整的 evidence surface 体系。基础执行链路在架构层已经真实存在，recovery/readiness/acceptance/governance 框架均已可导入和评估。核心未闭合点是：跨仓证据的 wire 层传输（ReconciliationSignal AIP 消息类型缺失）、release gate 仍处于 advisory 非阻断模式、delegated flow 从未被端到端运行过、无真实设备 CI 自动化。这套系统目前处于"框架闭合、关键 wire 层待打通"阶段，诚实评估为 `partial_closure_gaps_present`。**
