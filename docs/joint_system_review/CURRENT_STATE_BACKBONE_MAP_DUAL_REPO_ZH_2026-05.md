# 基于双仓真实代码澄清中心分布式 AI 系统现状、主骨架与未闭合点

> **文档编号**：CURRENT_STATE_BACKBONE_MAP_DUAL_REPO_ZH_2026-05  
> **审计范围**：`DannyFish-11/ufo-galaxy-realization-v2`（V2 中心侧）+ `DannyFish-11/ufo-galaxy-android`（Android 端侧）  
> **Android 审计参考提交**：`2857b93be7e8e6ea01e37d9a2af01ff2cae92c5c`  
> **V2 机读骨架模块**：`core/current_state_backbone_audit.py`（本 PR 新增）  
> **前序 PR 锚点**：PR 1140（双仓认知基线）→ PR 1141（993P2 证据门）→ PR 1142（Android truth 进选路）→ PR 1143（可用性审查 + 操作面补强）→ **本 PR**（当前状态主骨架澄清）  
> **诚实要求**：本文档不以文档叙述作为事实依据，所有断言均基于真实代码探针或明确代码锚点。

---

## 执行摘要

本文档的唯一目标是：**基于双仓真实代码，清楚且诚实地描述这套系统当前是什么、能做什么、主链路怎么走、哪些地方已经闭合、哪些地方还没闭合。**

不做推测，不写未来规划，不夸大完成度。

**一句话系统现状**：

> 这套系统是一个**以 V2 Python 服务为中心治理核、以 Android 设备为 delegated runtime 执行节点的中心控制型跨端任务执行与治理平台**。六条主链路（含 Android truth 上送链）骨架已基本就位，Android truth 已从 transport → routing → closure → operator/panel 逐步接通；但本地模式、多设备并发实操、runtime_* 语义在 V2 下游全量同源消费、clone-to-run 开发者路径仍处于半闭合或未闭合状态。整体可用性判断：**`partially_operable`**。

---

## 一、这套系统当前到底是什么？

### 1.1 为什么它更接近"中心控制型分布式 AI 系统"

**代码证据**：

| 中心控制特征 | V2 侧代码锚点 | Android 侧代码锚点 |
|-------------|-------------|-----------------|
| V2 是唯一路由决策方 | `core/runtime/source_dispatch_orchestrator.py` | 无 Android 侧路由决策 |
| V2 是 acceptance/closure 权威 | `core/result_truth_acceptance_gate.py` ; `core/canonical_completion_ingress.py` | Android 上报，V2 判断 |
| V2 管理 participation tier 评分 | `core/android_network_participation.py` | `AndroidMeshParticipationContract.kt`（上报，不决策） |
| Android 设备间无直连协调 | `galaxy_gateway/routing/device_selection.py`（V2 集中选路） | 无 P2P 直连路径 |
| V2 控制 takeover 门控 | `core/android_originated_authority_boundary.py` | Android 接受决策，不主动发起 |

**为什么不是"单仓服务"**：Android 侧持有真实的本地执行能力（`AutonomousExecutionPipeline.kt`）、独立的 readiness 评估（`DelegatedRuntimeReadinessEvaluator.kt`）、acceptance 评估（`DelegatedRuntimeAcceptanceEvaluator.kt`）、execution event 上报（`CanonicalExecutionEvent.kt`）。这些不是简单的"客户端展示层"。

**为什么不是"对等 P2P mesh"**：所有路由、closure、governance 决策均发生在 V2 中心。Android 设备间没有直接通信路径。AndroidMeshParticipationContract.kt 虽定义了 mesh 参与语义，但协调权威在 V2。

### 1.2 V2 当前扮演什么角色

| 职责域 | 代码锚点 | 当前状态 |
|--------|---------|---------|
| **Authority（权威）** | `core/android_originated_authority_boundary.py` | ✅ 已成立 |
| **Routing（路由）** | `core/runtime/source_dispatch_orchestrator.py` ; `galaxy_gateway/routing/device_selection.py` | ✅ 已成立，消费 Android participation truth |
| **Execution 编排** | `core/nl_execution_spine.py` ; `core/canonical_execution_chain.py` | ✅ 已成立 |
| **Result Acceptance** | `core/result_truth_acceptance_gate.py` ; `core/unified_result_ingress.py` | ✅ 已成立 |
| **Closure** | `core/canonical_completion_ingress.py` ; `notify_with_android_context()` | ✅ 已成立 |
| **Continuity** | `core/pr3_session_continuity_authority.py` | ✅ 已成立 |
| **Operator/Audit** | `core/pr4_operator_action_governance.py` ; `core/routes/operator.py` | ✅ 已成立 |
| **Panel/Board 投影** | `core/unified_panel_aggregation.py` ; `core/pr4_operator_action_governance.py` | ✅ 已成立 |
| **Governance/Release gate** | `core/delegated_flow_readiness_gate.py` ; `core/delegated_flow_acceptance_gate.py` | ✅ 已成立 |

### 1.3 Android 当前扮演什么角色

| 职责域 | 代码锚点 | 当前状态 |
|--------|---------|---------|
| **Execution（本地执行）** | `AutonomousExecutionPipeline.kt` ; `GalaxyConnectionService.kt` | ✅ 代码存在，需本地配置 |
| **Result Payload 上报** | `DelegatedExecutionSignal.kt` ; `GalaxyWebSocketClient.kt` | ✅ 已成立 |
| **Readiness 评估** | `DelegatedRuntimeReadinessEvaluator.kt` | ✅ 代码存在 |
| **Acceptance 评估** | `DelegatedRuntimeAcceptanceEvaluator.kt` | ✅ 代码存在 |
| **Governance 评估** | `DelegatedRuntimePostGraduationGovernanceEvaluator.kt` | ✅ 代码存在 |
| **Continuity / Identity** | `DurableParticipantIdentity.kt` ; `AttachedRuntimeSession.kt` | ✅ 已成立，跨重启证明仍薄 |
| **Participation/Mode Truth 上报** | `GalaxyWebSocketClient.kt` ; `GalaxyConnectionService.kt` ; `AipModels.kt` | ✅ 已成立（`participation_tier` + `execution_mode_state` + `cross_device_eligibility` 等字段已进入 capability/snapshot/event/result） |
| **Local NL 推理** | `LocalExecutionModeGate.kt` ; `AutonomousExecutionPipeline.kt` | ⚠️ 半闭合，依赖本地 LLM 权重 |
| **Snapshot / Execution Event** | `CanonicalExecutionEvent.kt` ; `AndroidDelegatedRuntimeAuditSnapshot.kt` | ✅ 已成立 |

---

## 二、当前主链路拆解

### 链路总览

```
请求链 ──────────────────────────────────────────────────────────▶ Android
          用户NL → V2 chat route → NL spine → dispatch orchestrator
                                                     │ device_selection
                                                     ▼
执行链  Android 接收 handoff_envelope_v2 → AutonomousExecutionPipeline
                                               │ 本地执行 / local NL
                                               ▼
Android truth上送链  capability/snapshot/event/result 上送 participation/mode truth
                                                │ GalaxyWebSocketClient + GalaxyConnectionService
                                                ▼
结果回流链  Android → GalaxyWebSocketClient → V2 android_bridge
                                               │ unified_result_ingress
                                               ▼
closure/acceptance链  evidence_model → result_truth_acceptance_gate
                                              │ is_fully_closed
                                              ▼ canonical_completion_ingress
                                              │ notify_with_android_context
                                              ▼
operator/panel投影链  UnifiedPanelPayload → board projection → routes
                       android_participation_verdict  latest_closure_reasoning
```

---

### 2.1 请求链（Request Chain）

| # | 环节 | V2 代码锚点 | Android 代码锚点 | 闭合状态 |
|---|------|------------|----------------|---------|
| 1 | 用户输入 → V2 Chat/API 路由 | `core/routes/chat.py :: POST /api/v1/chat` | — | ✅ 已成立 |
| 2 | NL 执行脊柱（PR-2 v2.2.0.0） | `core/nl_execution_spine.py` | — | ✅ 已成立 |
| 3 | 编排选路 + Android participation 评分 | `core/runtime/source_dispatch_orchestrator.py` ; `galaxy_gateway/routing/device_selection.py` | — | ✅ 已成立（PR 1142） |
| 4 | handoff_envelope_v2 下发给 Android | `core/android_handoff_v2_response_ingress.py` ; `galaxy_gateway/android_bridge` | `GalaxyConnectionService.kt` | ✅ 已成立 |

**请求链整体闭合状态：✅ 已成立**

---

### 2.2 执行链（Execution Chain）

| # | 环节 | V2 代码锚点 | Android 代码锚点 | 闭合状态 |
|---|------|------------|----------------|---------|
| 1 | Android 接收 handoff → 执行管线 | — | `AutonomousExecutionPipeline.kt` ; `GalaxyConnectionService.kt` | ✅ 代码存在 |
| 2 | 本地 LLM / NL 推理（本地模式） | — | `LocalExecutionModeGate.kt` | ⚠️ 半闭合（依赖本地 LLM 配置） |
| 3 | 执行事件上报 | `core/android_execution_signal_reconciler.py` | `CanonicalExecutionEvent.kt` | ✅ 已成立 |
| 4 | Readiness 评估 | `core/android_device_state_store.py :: get_android_participation_evidence` | `DelegatedRuntimeReadinessEvaluator.kt` | ✅ 已成立 |

**执行链整体闭合状态：⚠️ 半闭合**（本地 LLM 路径依赖外部配置）

---

### 2.3 Android Truth 上送链（Android Truth Uplink Chain）

| # | 环节 | V2 代码锚点 | Android 代码锚点 | 闭合状态 |
|---|------|------------|----------------|---------|
| 1 | capability report 上送 participation/mode truth | `galaxy_gateway/android_bridge`（capability ingestion） | `GalaxyWebSocketClient.kt` | ✅ 已成立 |
| 2 | snapshot / execution event 上送 participation_tier + execution_mode_state | `core/android_device_state_store.py` | `GalaxyConnectionService.kt` ; `AipModels.kt` | ✅ 已成立 |
| 3 | goal result 自动补齐运行上下文再上送 | `core/unified_result_ingress.py :: NormalizedResultEvent` | `GalaxyConnectionService.kt :: sendGoalResult` ; `AipModels.kt` | ✅ 已成立 |

**Android truth 上送链整体闭合状态：✅ 已成立**

---

### 2.4 结果回流链（Result Backflow Chain）

| # | 环节 | V2 代码锚点 | Android 代码锚点 | 闭合状态 |
|---|------|------------|----------------|---------|
| 1 | Android → V2 WebSocket 结果上送 | `galaxy_gateway/android_bridge` | `GalaxyWebSocketClient.kt` | ✅ 已成立 |
| 2 | 统一结果入站（5 路汇聚） | `core/unified_result_ingress.py :: ingest_result` | — | ✅ 已成立 |
| 3 | 真值链四步处理 | `core/android_participant_truth_ingress.py` ; `core/android_execution_signal_reconciler.py` ; `core/android_delegated_runtime_lifecycle_coordinator.py` | `DelegatedExecutionSignal.kt` | ✅ 已成立 |
**结果回流链整体闭合状态：✅ 已成立**

---

### 2.5 Closure/Acceptance 链

| # | 环节 | V2 代码锚点 | Android 代码锚点 | 闭合状态 |
|---|------|------------|----------------|---------|
| 1 | 证据质量分类 | `core/execution_evidence_model.py :: classify_execution_evidence` | `DelegatedRuntimeAcceptanceEvaluator.kt` | ✅ 已成立 |
| 2 | acceptance verdict → is_fully_closed 阻断 | `core/result_truth_acceptance_gate.py` ; `core/unified_result_ingress.py :: EVIDENCE_CLOSURE_BLOCKING_VERDICTS` | — | ✅ 已成立（PR 1141） |
| 3 | canonical closure + Android context 携带 | `core/canonical_completion_ingress.py :: notify_with_android_context` | — | ✅ 已成立（PR 1143） |
| 4 | closure 语义写入 operator evidence surface | `core/operator_execution_observability_surface.py :: record_operator_evidence_entry` | — | ✅ 已成立 |

**closure/acceptance 链整体闭合状态：✅ 已成立**

---

### 2.6 Operator/Panel/Board/Desktop/Mobile 投影链

| # | 环节 | V2 代码锚点 | 字段性质 | 闭合状态 |
|---|------|------------|---------|---------|
| 1 | UnifiedPanelPayload android_participation_verdict | `core/unified_panel_aggregation.py` | **runtime truth（V2 聚合）** | ✅ 已成立（PR 1143） |
| 2 | Board projection 消费 + latest_closure_reasoning | `core/pr4_operator_action_governance.py :: build_operator_board_projection` | **runtime truth 推导** | ✅ 已成立（PR4） |
| 3 | GET /api/v1/operator/board/operable-truth | `core/routes/operator.py` | **runtime truth 投影** | ✅ 已成立 |
| 4 | GET /api/v1/projection/desktop-status-board | `core/routes/projection.py` | **runtime truth 投影** | ✅ 已成立 |
| 5 | Desktop presence 三态（tri_state_phase） | `core/desktop_presence_runtime.py` ; `core/continuum` | **runtime truth（显化层）** | ⚠️ 半闭合（两条语义线未统一） |
| 6 | Android participation tier 三态语义 | `core/android_network_participation.py` | **runtime truth（参与层）** | ⚠️ 半闭合（上送已成立，但下游统一强约束解释链未闭合） |
| 7 | Mobile UI 投影（悬浮窗） | — | **projection（依赖 WS 连接）** | ⚠️ 半闭合（WS 中断时失同步） |

**投影链整体闭合状态：⚠️ 半闭合**（三态统一 API 未完成）

#### 字段性质说明

- **runtime truth**：该字段来自 V2 侧真实运行时状态（直接读取 canonical store），是决策的直接因。
- **projection**：该字段是 runtime truth 的映射/投影，可能有延迟或条件依赖。
- **半同源**：字段值基于 runtime truth 派生，但途径涉及推断或合并，并非直接同源。

---

## 三、运行模式地图

### 3.1 本地模式（Local Mode）

- **定义**：Android 设备在无 V2 连接情况下独立处理自然语言请求，通过本地 LLM 完成任务。
- **V2 代码锚点**：`core/android_mode_gate_policy.py :: AndroidDeviceMode.local`
- **Android 代码锚点**：`LocalExecutionModeGate.kt` ; `AutonomousExecutionPipeline.kt`
- **当前闭合状态**：⚠️ **半闭合**
- **成立条件**：设备端配置本地 LLM 权重 + accessibility 服务授权
- **缺口**：本地 LLM 权重不由系统默认提供；本地模式结果不经过 V2 closure 链，缺少 acceptance 闭合记录。

### 3.2 跨设备模式（Cross-Device Mode）

- **定义**：Android 连接 V2 中心，`cross_device_switch` 开启，V2 可向 Android 派遣任务。参与 tier 达到 `cross_device_enabled`。
- **V2 代码锚点**：`core/android_network_participation.py :: AndroidNetworkParticipationTier.cross_device_enabled` ; `galaxy_gateway/cross_device_switch.py`
- **Android 代码锚点**：`GalaxyWebSocketClient.kt` ; `GalaxyConnectionService.kt`
- **当前闭合状态**：✅ **已成立**（协议、门控、选路均已就位）
- **成立条件**：Android APK 已安装并连接 V2 gateway（WS） + V2 cross_device_switch 开启 + Android cross_device_enabled 门控通过
- **缺口**：APK 需单独构建，不在 V2 clone-to-run 自动路径内。

### 3.3 多设备参与（Multi-Device Participation）

- **定义**：多台 Android 设备同时连接 V2，V2 选路时按各设备 participation tier 评分选择执行节点。**中心控制型，非 P2P。**
- **V2 代码锚点**：`core/android_device_state_store.py :: list_device_state_snapshots` ; `galaxy_gateway/routing/device_selection.py`
- **Android 代码锚点**：`AndroidMeshParticipationContract.kt`
- **当前闭合状态**：⚠️ **半闭合**（骨架真实，端到端多设备并发实操未验证）
- **边界**：所有协调通过 V2 中心，Android 设备间无直连通道。

### 3.4 委托执行（Delegated Execution）

- **定义**：V2 通过 `handoff_envelope_v2` 下发具体任务给 Android，Android 执行后通过 `DelegatedExecutionSignal` 回流结果，V2 负责 acceptance 与 closure。
- **V2 代码锚点**：`core/android_handoff_v2_response_ingress.py` ; `core/android_delegated_runtime_lifecycle_coordinator.py`
- **Android 代码锚点**：`DelegatedExecutionSignal.kt` ; `CanonicalDispatchChain.kt`
- **当前闭合状态**：✅ **已成立**（协议双端对齐，execution signal 回流链完整）
- **缺口**：`runtime_constrained/runtime_deferred/local_mode_active` 在 V2 下游仍未形成统一强约束解释链。

### 3.5 接管（Takeover）

- **定义**：V2 通过 `takeover_request` 请求接管 Android 当前执行上下文，或将任务重路由至另一节点。
- **V2 代码锚点**：`core/android_originated_authority_boundary.py :: govern_takeover_boundary` ; `core/android_delegated_runtime_lifecycle_coordinator.py :: govern_takeover_decision`
- **Android 代码锚点**：`AndroidTakeoverOwnershipTransferContract.kt`
- **当前闭合状态**：⚠️ **半闭合**（门控逻辑存在，但跨设备接管端到端路径未全闭合）
- **说明**：authority/proof/continuity 证据降级时自动降为 revalidation（非自动完成）。

### 3.6 分布式参与节点（Distributed Participant）

- **定义**：Android 达到 `dispatch_eligible` / `distributed_participant` tier，V2 可直接向其派遣任务作为独立执行节点，支持并行参与。
- **V2 代码锚点**：`core/android_network_participation.py :: AndroidNetworkParticipationTier.distributed_participant`
- **Android 代码锚点**：`AndroidMeshParticipationContract.kt`
- **当前闭合状态**：⚠️ **半闭合**（tier 定义和评估存在，端到端实操未验证）
- **成立条件**：cross_device_enabled + goal_execution_enabled + parallel_execution_enabled 全部通过，并实际参与多任务并行分发。

### 3.7 模式边界总结

```
本地模式          ←─────────────────────────────────────────┐
（无 V2 连接）                                             Android 侧自主

跨设备模式        ←─ V2 cross_device_switch ON + WS 连接 ─→ V2 可派遣
（connected）         Android tier: cross_device_enabled

多设备参与        ←─ 多台设备注册 + 各自 tier 评分 ─────── 中心选路（非 P2P）
（parallel）

委托执行          ─ V2 handoff_envelope_v2 ──────────────→ Android 执行 + 回流
（delegated）

接管              ─ V2 takeover_request ────────────────→ Android 重路由/让出
（takeover）          authority 门控在 V2 侧

分布式节点        ─ V2 直接派遣 ────────────────────────→ dispatch_eligible+ tier
（distributed）       parallel_execution_enabled 门控
```

---

## 四、呈现面（Operator/Panel/Desktop/Mobile）当前在展示什么

### 4.1 字段性质分类

| 呈现面 | 关键字段 | 字段性质 | 代码锚点 |
|--------|---------|---------|---------|
| **operator panel**（`UnifiedPanelPayload`） | `android_participation_verdict` | **runtime truth（V2 聚合）** | `core/unified_panel_aggregation.py` |
| **operator panel** | `tri_state_phase` / `presence_tristate` | **runtime truth（显化层）** | `core/continuum` ; `core/desktop_presence_runtime.py` |
| **operator panel** | `readiness_verdict` / `blocked_dimensions` | **runtime truth** | `core/runtime_readiness_matrix.py` |
| **operator board**（`/api/v1/operator/board/operable-truth`） | `android_participation_verdict` | **runtime truth 推导** | `core/pr4_operator_action_governance.py` |
| **operator board** | `latest_closure_reasoning` | **runtime truth 推导（因果解释）** | `core/pr4_operator_action_governance.py :: get_board_reasoning_for_closure` |
| **desktop status board**（`/api/v1/projection/desktop-status-board`） | `operational_state_board` | **runtime truth 投影** | `core/routes/projection.py` ; `windows_client/status_board_v2/` |
| **desktop status board** | `source_of_truth_boundaries` | **projection（边界说明）** | `core/routes/projection.py` |
| **observability surface** | `evidence_state` / `android_device_id` | **runtime truth** | `core/operator_execution_observability_surface.py` |
| **mobile UI（悬浮窗）** | 任务结果 / 状态显示 | **projection（依赖 WS 连接）** | `EnhancedFloatingService.kt` ; `GalaxyConnectionService.kt` |

### 4.2 runtime truth vs projection vs 半同源

**Runtime Truth（V2 直接持有）**：
- `android_participation_verdict`（由 `_fill_android_participation_verdict()` 从 device store 实时聚合）
- `tri_state_phase`（V2 continuum 状态机）
- `readiness_verdict`（V2 readiness matrix）
- `evidence_state`（V2 operator observability surface）
- `is_fully_closed`（V2 result ingress 决策）

**Projection（从 runtime truth 映射，可能有延迟）**：
- desktop status board（HTTP 请求时快照）
- mobile 悬浮窗（WS 推送，中断时失同步）
- `latest_closure_reasoning`（在请求时 on-the-fly 构建的因果解释）

**半同源（基于 runtime truth 派生但有推断步骤）**：
- `source_of_truth_boundaries`（描述性字段，来自文档/契约定义，非实时探针）
- Android participation tier 在 board projection 中的展示（取决于 Android 是否稳定上送 tier）

---

## 五、当前 clone/build/use 程度评估

### 5.1 V2 侧

| 阶段 | 状态 | 说明 |
|------|------|------|
| `git clone` | ✅ 可以 | 仓库公开可克隆 |
| `pip install -r requirements.txt` | ✅ 可以 | 依赖清单存在 |
| 配置 `.env`（API Key 等） | ⚠️ 手动 | 需自行获取并配置 |
| `python main.py` 启动服务 | ✅ 可以 | 明确启动入口 |
| `GET /api/v1/health` 验证 | ✅ 可以 | health 路由存在 |
| `POST /api/v1/chat` 发送请求 | ✅ 可以（本地模式） | 需要 LLM API Key |
| 多设备实操（Android 接入） | ⚠️ 需额外步骤 | 见 Android 侧 |

### 5.2 Android 侧

| 阶段 | 状态 | 说明 |
|------|------|------|
| 仓库克隆 | ✅ 可以 | 独立仓库可克隆 |
| Gradle 构建 APK | ⚠️ 需工具链 | 需 Android Studio / Gradle + JDK |
| APK 安装到设备 | ⚠️ 手动 | 需 adb 或手动安装 |
| 配置 V2 服务器地址 | ⚠️ 手动 | `config.properties` 需配置 |
| WS 连接 V2 | ✅ 协议就位 | 网络可达后可连接 |
| 本地 NL 模式 | ⚠️ 非默认 | 需额外配置本地 LLM + accessibility 授权 |
| 跨设备执行 | ✅ 协议就位 | 需 V2 cross_device_switch 开启 |

### 5.3 整体判断

**`partially_operable`（部分可用）**

- **已真实可用**：V2 服务可启动，API 路由已定义，Android WS 接入协议已就位，编排/acceptance/closure 主链是真实的。
- **仍有阻塞**：Android APK 需单独构建；本地 NL 模式需 LLM 权重；多设备实操需多台设备同时在线；API Key 需手动配置。
- **不是** fully ready，**不是** 开箱即用。

---

## 六、当前主骨架三态分离

### 6.1 已成立（Established）

以下骨架点已有真实代码支撑，端到端路径已接通：

1. **V2 中心服务启动入口** — `main.py` / `unified_launcher.py`
2. **WebSocket 双端 transport 协议（AIP v3）** — `GalaxyWebSocketClient.kt` ↔ `galaxy_gateway/android_bridge`
3. **设备注册与能力上报体系** — `core/android_device_state_store.py` ↔ `RuntimeController.kt`
4. **AndroidNetworkParticipationTier 7 层级定义与评估** — `core/android_network_participation.py`
5. **编排选路消费 Android participation truth（PR 1142）** — `source_dispatch_orchestrator` + `device_selection`
6. **统一结果入站链（unified_result_ingress）** — 所有结果信号通过单一入站入口
7. **Android authoritative truth + mode 语义上送** — `GalaxyWebSocketClient.kt` + `GalaxyConnectionService.kt` + `AipModels.kt`
8. **Evidence/acceptance/closure 真值链** — `execution_evidence_model` + `result_truth_acceptance_gate` + `EVIDENCE_CLOSURE_BLOCKING_VERDICTS`
9. **canonical_completion_ingress + notify_with_android_context（PR 1143）** — closure 携带 Android context
10. **Panel android_participation_verdict 字段（PR 1143）** — operator/board 可读最高参与层级
11. **Board projection 消费 verdict + board reasoning（PR4）** — `build_operator_board_projection` + `get_board_reasoning_for_closure`
12. **Session continuity / DurableParticipantIdentity** — PR3 continuity 决策 + Android 持久身份
13. **Handoff_envelope_v2 委托执行协议** — 双端对齐
14. **Operator API 路由集（PR4）** — `/audit` / `/board/operable-truth` / `/pr4/snapshot` / `/android-directed`
15. **跨设备模式（cross_device_enabled tier）** — 协议、门控、选路均就位

### 6.2 半闭合（Partial）

以下骨架点代码骨架存在，但有条件依赖、路径断点或需要双端对齐：

1. **三态统一系统 API** — 显化层 tri_state_phase + Android tier 两条线未统一
2. **Android 本地 NL 模式** — 代码存在，依赖本地 LLM 配置 + accessibility 权限
3. **Android runtime_constrained/runtime_deferred/local_mode_active 在 V2 下游全量消费** — Android 已稳定上送，V2 下游仍以部分消费为主
4. **readiness tier degradation ↔ participation tier 强联动** — 评估存在，联动机制不完整
5. **多设备并发派遣实操** — 骨架真实，端到端多设备并发实操未验证
6. **Takeover 完整端到端路径** — 门控存在，跨设备接管半闭合
7. **Mobile UI 与 V2 runtime truth 实时同源** — WS 中断时失同步
8. **Android App clone-to-build 需单独 Gradle 构建** — 不在 V2 自动路径内

### 6.3 未闭合（Open）

以下骨架点存在已知阻塞，或属于架构选择的诚实说明：

1. **Android 本地 LLM 权重默认可用** — 系统不提供默认权重，用户自行配置
2. **distributed_participant tier 端到端实操验证** — 需所有三门满足 + 多任务并行分发场景
3. **clone-to-run 开发者顺滑路径** — V2 + Android 一体化构建/连接文档或脚本未完成
4. **真正 P2P / 自主对等 mesh runtime** — 架构选择为中心控制型，Android 间无直连（这是设计决定，非待修复的缺口）

---

## 七、本 PR 的代码变化

### 7.1 新增：`core/current_state_backbone_audit.py`

**目的**：提供可机读的当前系统骨架摘要，供 operator/board 消费。

**公开 API**：
- `build_chain_map() -> ChainMap` — 六条链路当前状态地图（含 Android truth 上送链）
- `build_mode_map() -> ModeMap` — 运行模式地图
- `build_backbone_snapshot() -> BackboneSnapshot` — 完整骨架快照（三态分离）
- `build_system_backbone_snapshot() -> dict` — operator/board 消费入口（最简洁摘要）

**设计原则**：
- 所有闭合状态基于 V2 真实代码探针（`importlib.util.find_spec` + 源码 token 检查）
- Android 断言基于已审计提交的明确代码锚点
- 不导入 Android 代码（不可能），仅记录文件路径作为锚点

**与现有模块的关系**：
- 补充 `core/pr_next_convergence_closure_audit.py`（PR 1143），后者聚焦可用性审查+闭环治理传播，本模块聚焦骨架清晰呈现
- 补充 `core/complete_joint_system_review.py`（PR 1140），后者是认知基线，本模块是可机读的运行状态地图
- 为 operator/board 提供单一入口：`build_system_backbone_snapshot()` 可被 `/api/v1/operator/board/operable-truth` 等路由消费

### 7.2 新增：`tests/test_current_state_backbone_audit.py`

覆盖：chain_map / mode_map / backbone_snapshot / build_system_backbone_snapshot 的结构正确性与三态计数验证。

---

## 附录：关键代码坐标速查

### V2 侧（`core/` 目录）

| 模块 | 功能 | 关键 API |
|------|------|---------|
| `android_network_participation.py` | 7 层参与 tier | `derive_android_network_participation_tier` |
| `android_device_state_store.py` | 设备快照 SSOT | `get_android_participation_evidence` |
| `android_mode_gate_policy.py` | 跨设备/本地模式门控 | `evaluate_android_mode_readiness` |
| `runtime/source_dispatch_orchestrator.py` | 编排选路 | `select_dispatch_target` |
| `galaxy_gateway/routing/device_selection.py` | 设备选路评分 | `select_device` |
| `unified_result_ingress.py` | 统一结果入站 | `ingest_result` |
| `execution_evidence_model.py` | 证据质量分类 | `classify_execution_evidence` |
| `result_truth_acceptance_gate.py` | acceptance verdict | `evaluate_result_truth_acceptance` |
| `canonical_completion_ingress.py` | closure + Android context | `notify_with_android_context` |
| `unified_panel_aggregation.py` | 统一 panel 聚合 | `build_unified_panel_payload` |
| `pr4_operator_action_governance.py` | board projection | `build_operator_board_projection` |
| `pr3_session_continuity_authority.py` | session continuity | `govern_takeover_decision` |
| `operational_readiness_surface.py` | readiness 聚合 | `build_operational_readiness_report` |
| `v2_unified_state_contract.py` | 统一状态契约 | `build_v2_unified_state_contract` |
| `operator_execution_observability_surface.py` | 执行可观测性 | `record_operator_evidence_entry` |
| **`current_state_backbone_audit.py`** | **骨架机读摘要（本 PR）** | **`build_system_backbone_snapshot`** |

### Android 侧（`com.ufo.galaxy` 包）

| 文件 | 功能 |
|------|------|
| `network/GalaxyWebSocketClient.kt` | 唯一跨端上行 transport |
| `service/GalaxyConnectionService.kt` | 连接服务（294KB，最重要服务） |
| `agent/AutonomousExecutionPipeline.kt` | 自主执行管线 |
| `runtime/LocalExecutionModeGate.kt` | 本地模式门控 |
| `runtime/DelegatedExecutionSignal.kt` | 委托执行信号结构 |
| `runtime/CanonicalExecutionEvent.kt` | 执行事件定义 |
| `runtime/CanonicalDispatchChain.kt` | canonical 派遣链 |
| `runtime/DelegatedRuntimeReadinessEvaluator.kt` | Readiness 评估 |
| `runtime/DelegatedRuntimeAcceptanceEvaluator.kt` | Acceptance 评估 |
| `runtime/AndroidMeshParticipationContract.kt` | mesh 参与契约 |
| `runtime/RuntimeController.kt` | 运行时生命周期总控（152KB） |
| `session/DurableParticipantIdentity.kt` | 持久参与者身份 |

---

> **文档准确性说明**：本文档所有闭合状态断言均基于真实代码探针或已审计代码锚点。任何后续代码变更导致断言失效时，应以代码为准，文档需同步更新。
