# 基于双仓真实代码收敛系统可用性审查、闭环真值治理与操作面同源解释

> **收敛 PR 编号**：PR 1143（继 PR 1140/1141/1142 之后的下一个主要收敛 PR）  
> **认知锚点**：993P2  
> **Android 代码审计参考提交**：`478e3f8f3cd3cb85b5a20999c9fca22a0f44ef8d`  
> **合同版本**：`1.0.0`  
> **权威标志**：`PR_NEXT_CONVERGENCE_CLOSURE_AUDIT::core.pr_next_convergence_closure_audit`

---

## 一、本次 PR 的定位与范围

本次 PR 是继以下三个 PR 之后的下一个主要收敛工件：

- **PR 1140**：建立双仓认知基线，定义主链路、跨仓矛盾结构、V2 侧下一步收敛优先级
- **PR 1141**：以 993P2 为锚点，修复证据门与闭环一致性
- **PR 1142**：把 Android 参与真值正式接入 V2 编排选路评分（`source_dispatch_orchestrator` + `device_selection`）

本次 PR 的定位是：**在 PR 1142 完成"routing 层消费 Android truth"之后，把这个真值进一步传播到 closure / governance / operator / readiness / board 层面，并对系统实际可用性作出诚实的基于真实代码的综合审查。**

本次 PR 必须且已经回答以下六个关键问题（见第二节）。

---

## 二、六个关键问题的诚实回答

### 问题 1：系统是否已达到"可克隆、可运行、可操作、可实用"的程度？

**结论：`partially_operable`（部分可用）**

| 检查点 | 通过？ | 诚实评估 |
|--------|--------|---------|
| 启动入口（main.py / unified_launcher.py）存在 | ✅ | V2 核心服务有明确启动入口 |
| 依赖清单（requirements.txt）存在 | ✅ | 可通过 pip install -r requirements.txt 安装 |
| 环境配置样例（.env.example）存在 | 部分 | API Key 配置可能需要自行获取 |
| /api/v1/health 路由存在 | ✅ | 可快速验证服务是否运行 |
| Android App 可构建 | ⚠️ | 需单独构建 APK，不在 V2 clone-to-run 路径内 |
| Android 本地 NL 模式 | ⚠️ | 代码路径存在，但依赖本地 LLM 权重 + accessibility 权限，非开箱即用 |
| 多设备参与体系 | ✅（语义）/ ⚠️（实用） | 参与体系真实存在，但不是对等 mesh，是中心控制型 |

**阻塞点**：
1. Android APK 需要单独构建（Gradle + APK 安装），不在自动化路径内
2. Android 本地 NL 模式需要设备端本地 LLM 和 accessibility 权限，非默认可用
3. 多设备"分布式"是中心控制型，不是对等 peer-to-peer mesh

**已真实可用**：
- V2 核心服务可 clone 并启动
- API 路由（chat, health, operator, readiness 等）已定义
- Android WS 接入协议已就位
- 设备注册、能力上报、参与 readiness 体系真实存在
- result truth acceptance gate 已运行
- 编排选路已消费 Android 参与真值（PR 1142）

---

### 问题 2：Android 本地自然语言、本地模式、自主/委托/接管路径哪些是真的、哪些只是概念或半联通？

**基于真实代码的回答**：

| 路径 | 状态 | 代码锚点 |
|------|------|---------|
| GalaxyWebSocketClient 接入 V2 | ✅ 真实 | `ufo-galaxy-android/...GalaxyWebSocketClient.kt` |
| AutonomousExecutionPipeline | ✅ 代码存在 | `...AutonomousExecutionPipeline.kt` |
| 本地 LLM / NL 推理 | ⚠️ 依赖设备 LLM 配置，非默认 | `LocalExecutionModeGate.kt` |
| delegated 执行路径 | ✅ 语义+代码存在 | `android_delegated_runtime_lifecycle_coordinator.py` |
| takeover 路径 | ✅ 有门控逻辑 | `android_originated_authority_boundary.py` |
| mesh participation contract | ✅ 存在，但克制表达 | `AndroidMeshParticipationContract.kt` |
| Android continuity identity | ✅ 接通，跨重启证明仍薄 | `DurableParticipantIdentity.kt` |

**诚实结论**：以上路径均有真实代码支撑，但它们的完整端到端可用性依赖：(1) Android App 已安装、已连接；(2) 设备端已配置本地 LLM（对本地 NL 模式而言）；(3) V2 服务已运行且 API Key 配置正确。

---

### 问题 3：多设备注册/加入/能力宣告/参与 readiness 体系是否真实？

**结论：体系真实存在，但是中心控制型，不是对等分布式**

- `AndroidNetworkParticipationTier` 定义 7 个层级（local_only → distributed_participant），设备可从 local_only 逐步升至 distributed_participant
- `android_mode_gate_policy` 含 `evaluate_android_mode_readiness`，对每个设备评估三个门（crossDeviceEnabled / goalExecutionEnabled / parallelExecutionEnabled）
- `android_device_state_store` 维护设备快照，`get_android_participation_evidence` 是 V2 侧消费 Android 参与真值的权威路径
- **不能说成**：P2P mesh 全连通、自主分布式决策网络

---

### 问题 4：operator surface / readiness / board / panel / state projection 与真实 runtime decision causes 的关系

**当前状态**：

| 面 | 消费 Android truth？ | 与决策因果同源？ |
|----|---------------------|--------------|
| UnifiedPanelPayload（operator/panel 面） | **本次 PR 新增**：`android_participation_verdict` 字段 | 部分：tier 可见，但 board routing 尚未完全消费 |
| operator_execution_observability_surface | ✅ 记录 android_device_id + evidence_state | 部分：执行证据可见，但 tier 原因未独立投影 |
| pr4_operator_action_governance | ✅ build_android_directed_action_spec | 部分：有 Android directed action，但 board projection 未纳入 tier |
| operational_readiness_surface | ✅ 消费 android_network_participation | 部分：tier degradation → readiness degradation 门控仍需强化 |
| v2_unified_state_contract | ✅ 含 android_network_participation 投影 | 部分：state_contract 有 participation 字段 |

**本次 PR 补强**：
1. `UnifiedPanelPayload.android_participation_verdict`：panel 面直接可读最高参与层级设备的 tier
2. `CanonicalCompletionIngress.notify_with_android_context()`：closure 时刻携带 tier 上下文
3. `get_board_reasoning_for_closure()`：operator route 的标准化因果解释 API

---

### 问题 5："三态运行呈现"在代码中是否真实存在？

**结论：`PARTIALLY_IN_CODE`（部分在代码中）**

三态概念在代码中以两条独立语义线存在：

**线路 A — 显化层三态（desktop/shell）**：
- `tri_state_phase`（来自 `ContinuumState`）— 来自 `core.continuum.types`
- `presence_tristate`（来自 `OperatorSnapshot`）— 来自 `core.desktop_presence_runtime`
- 这两个字段已通过 `UnifiedPanelAggregationService` 进入 `UnifiedPanelPayload`
- **状态：真实存在，已投影到 panel**

**线路 B — Android 参与层三态**：
- `AndroidNetworkParticipationTier` 7 个层级可以合理聚合为三个语义层：本地独立 / 协作参与 / 分布式节点
- 已进入 V2 编排评分（PR 1142），但在 board/panel 上没有以"三态"名义统一投影
- **状态：tier 真实存在，board 三态聚合视图待补**

**若"三态"指两线路的统一 API**：当前 `unified_tri_state_api_exists = False`，不存在。本次 PR 通过新增 `android_participation_verdict` 字段迈出一步，但完整的双线统一三态 API 仍需后续 PR。

---

### 问题 6：Android truth 进入编排选路之后，是否继续进入 result acceptance / canonical completion / closure / operator explanation / board reasoning？

**传播链路诊断**：

| 层级 | 状态 | 说明 |
|------|------|------|
| 编排选路（routing） | ✅ 完成（PR 1142） | `get_android_participation_evidence` 进入 orchestrator + device_selection |
| result acceptance | ✅ 完成 | `android_proof_class` 进入 `result_truth_acceptance_gate` |
| is_fully_closed 阻断 | ✅ 完成 | quarantine/reject → is_fully_closed=False（防伪闭环） |
| closure 时刻 Android context | ✅ **本次 PR 完成** | `notify_with_android_context()` 新增 |
| panel/board tier 可见 | ✅ **本次 PR 完成** | `android_participation_verdict` 字段新增 |
| operator board routing 消费 | ⚠️ 待跟进 | board route 尚未读取 `android_participation_verdict` |
| Android tier 稳定上送到 V2 | ⚠️ 待 Android 侧 | delegated result 需稳定提供 participation_tier 字段 |

**整体传播层级**：`PARTIALLY_PROPAGATED`（部分传播）

PR 1142 之前：`ROUTING_ONLY`  
PR 1142 之后：result acceptance 已消费，升级为 `PARTIALLY_PROPAGATED`  
本次 PR 之后：closure context + panel 可见，进一步趋向 `FULLY_PROPAGATED`（但 board routing 消费仍待跟进）

---

## 三、本次 PR 在 V2 侧的实质代码变更

### 变更 1：`core/pr_next_convergence_closure_audit.py`（全新文件）

提供四个子审计工件 + 一个 board reasoning API：

- `build_clone_to_run_audit()` — 基于真实代码探针的可用性审计
- `build_three_state_runtime_audit()` — 三态在代码中的真实性审查
- `build_closure_governance_propagation_audit()` — Android truth 传播链路审计
- `build_android_truth_operator_board_audit()` — operator board 可观测性审计
- `get_board_reasoning_for_closure(task_id, tier, verdict, ...)` — operator route 调用的标准化因果解释 API
- `build_convergence_closure_audit()` — 全量审计工件入口

### 变更 2：`core/canonical_completion_ingress.py`

新增 `notify_with_android_context()` 方法：

```python
def notify_with_android_context(
    self,
    envelope: Any,
    android_participation_tier: Optional[str] = None,
    android_device_id: Optional[str] = None,
    acceptance_verdict: Optional[str] = None,
) -> bool:
```

**作用**：closure 事件现在可以携带 Android 参与层级上下文。当调用方知道是哪个 tier 的 Android 节点完成了任务时，可以调用此方法，使 operator 面板可以追溯到具体参与节点。同时向 `operator_execution_observability_surface` 最佳努力写入一条 evidence record。

### 变更 3：`core/unified_panel_aggregation.py`

在 `UnifiedPanelPayload` 中新增 `android_participation_verdict` 字段（`Dict[str, Any]`）：

```json
{
  "device_id": "device-abc",
  "tier": "dispatch_eligible",
  "blocking_reasons": [],
  "tier_derivation_notes": [],
  "connected_device_count": 2,
  "dispatch_eligible_count": 1,
  "distributed_participant_count": 0,
  "_source": "core.android_network_participation"
}
```

**作用**：`UnifiedPanelAggregationService` 在每次构建 payload 时，从 `get_android_participation_evidence` 聚合最高参与层级设备的 tier 信息，使 board 和 panel 消费者无需单独查询即可看到当前 Android 参与状态。

### 变更 4：`core/complete_joint_system_review.py`

- 更新 `REVIEW_PR_TITLE` 为本次 PR 标题
- 更新 `_build_v2_next_convergence_priority()` 为下一步目标方向（board routing 消费 + Android 侧 tier 稳定上送）
- 新增 4 个 `IntegrityRepairAction`：
  - `IRA_ANDROID_CONTEXT_IN_CLOSURE`：closure 携带 Android context（本次已补）
  - `IRA_PANEL_PARTICIPATION_VERDICT`：panel 新增 android_participation_verdict（本次已补）
  - `IRA_CONVERGENCE_AUDIT_MODULE`：新增 board reasoning API（本次已补）

### 变更 5：`tests/test_pr_next_convergence_closure_audit.py`（全新文件）

74 个测试，覆盖：
- 权威标志与合同版本
- 枚举定义
- CloneToRunAudit 可用性审计
- ThreeStateRuntimeAudit 三态审查
- ClosureGovernancePropagationAudit 传播链路审计
- AndroidTruthInOperatorBoardAudit board 可观测性
- get_board_reasoning_for_closure() 因果解释 API
- 整体代码探针完整性检查

---

## 四、三线分离诚实总结

### 已真实工作的部分

1. V2 核心服务（main.py）和所有核心 API 路由已就位
2. Android WS 接入协议（GalaxyWebSocketClient）已就位
3. `result_truth_acceptance_gate`：`android_proof_class` 进入证据质量判定
4. `UnifiedResultIngress`：quarantine/reject 阻断 `is_fully_closed`（防伪闭环）
5. 编排选路：`source_dispatch_orchestrator` + `device_selection` 已消费 `get_android_participation_evidence`（PR 1142）
6. `operational_readiness_surface` + `v2_unified_state_contract` 含 `android_network_participation` 投影
7. `operator_execution_observability_surface` 记录 `android_device_id` + `evidence_state`
8. `pr4_operator_action_governance` 提供 `build_android_directed_action_spec`

### 本次 PR 在 V2 侧补强的部分

1. **`canonical_completion_ingress.notify_with_android_context()`**：closure 事件现在可以携带 Android participation tier 上下文，使 board 知道"哪个 tier 的节点完成了这次任务"
2. **`UnifiedPanelPayload.android_participation_verdict`**：panel 面板直接可读 Android 参与状态，无需单独调用
3. **`get_board_reasoning_for_closure()`**：operator route 的标准化 Android 参与因果解释 API
4. **`pr_next_convergence_closure_audit.py`**：完整的可机读审计工件，覆盖可用性、三态真实性、闭环传播链路、operator board 可观测性

### 仍需 Android 侧跟进的部分

1. **Android 侧 `delegated result` 需稳定提供 `participation_tier` 字段**，才能让 `notify_with_android_context` 收到高置信度的 tier 信息（否则退化为 "unknown"）
2. **Android `LocalExecutionModeGate` tier 评估需在连接时稳定上送**，才能让 readiness degradation 门控更准确
3. **Android mesh participation contract 的 `constrained/deferred` 语义**需在 WS 报文中显式上送，才能让 V2 board 准确解释参与约束原因
4. **board 路由侧**（`/api/v1/operator/board/operable-truth` 等）消费 `android_participation_verdict` 字段仍需 V2 后续 PR + Android 侧配合跟进

---

## 五、下一步 V2 收敛方向

根据本次审计结论，下一步最应该开的 V2 收敛 PR 方向是：

> **从闭环真值同源解释推进到 board routing 完全消费 Android truth 并拉通 Android 侧 tier 上报**

具体目标：
1. board 路由侧（`/api/v1/operator/board/operable-truth`）开始消费 `android_participation_verdict` 字段
2. `pr4_operator_action_governance.build_operator_board_projection()` 把 participation tier 纳入 board projection 输出
3. readiness tier degradation 门控与 Android participation tier 完全联动
4. 等 Android 侧稳定上送 `participation_tier` 后，`notify_with_android_context` 可提供高置信度的 tier 信息

---

## 六、关键代码锚点索引

### V2 侧（`ufo-galaxy-realization-v2`）

| 文件 | 说明 |
|------|------|
| `core/pr_next_convergence_closure_audit.py` | **本次 PR 核心工件**，可用性审计 + 三态审查 + 闭环传播审计 + board reasoning API |
| `core/canonical_completion_ingress.py` | `notify_with_android_context()` 新增 |
| `core/unified_panel_aggregation.py` | `android_participation_verdict` 字段新增 |
| `core/complete_joint_system_review.py` | 整体认知基线（含本次 PR 更新） |
| `core/result_truth_acceptance_gate.py` | Android proof_class → acceptance verdict |
| `core/unified_result_ingress.py` | acceptance verdict → is_fully_closed 控制 |
| `core/runtime/source_dispatch_orchestrator.py` | Android participation evidence → routing score（PR 1142） |
| `galaxy_gateway/routing/device_selection.py` | Android participation evidence → device score（PR 1142） |
| `core/android_network_participation.py` | AndroidNetworkParticipationTier（7 层权威定义） |
| `core/android_device_state_store.py` | `get_android_participation_evidence()` 权威入口 |
| `core/operational_readiness_surface.py` | readiness 消费 android_network_participation |
| `core/v2_unified_state_contract.py` | state_contract 含 android_network_participation |
| `core/operator_execution_observability_surface.py` | 记录 android_device_id + evidence_state |
| `core/pr4_operator_action_governance.py` | build_android_directed_action_spec, build_operator_board_projection |

### Android 侧（`ufo-galaxy-android`）

| 文件 | 说明 |
|------|------|
| `...network/GalaxyWebSocketClient.kt` | V2 WS 接入协议 |
| `...agent/AutonomousExecutionPipeline.kt` | 自主执行管道（本地 NL 路径） |
| `...runtime/AndroidMeshParticipationContract.kt` | mesh 参与契约（克制表达） |
| `...session/DurableParticipantIdentity.kt` | durable identity / continuity |
| `...runtime/LocalExecutionModeGate.kt` | 本地执行模式门控 |

---

*本文档由 `core/pr_next_convergence_closure_audit.py` 对应版本生成，基于真实代码探针，不含文档叙述作为证据。*
