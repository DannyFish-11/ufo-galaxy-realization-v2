# 双仓统一术语表 v1

> **适用仓库：** `DannyFish-11/ufo-galaxy-realization-v2`（V2）、`DannyFish-11/ufo-galaxy-android`（Android）  
> **文档性质：** 术语冻结。为后续所有 PR 的措辞与代码命名提供不漂移的语言基础。  
> **约束测试：** `tests/test_task1_formal_system_definition.py`

---

## 核心术语表

### center（中心）

**定义**：系统中持有 canonical governance / truth convergence / dispatch arbitration / closure authority 的唯一角色。在本双仓系统中，**V2（`ufo-galaxy-realization-v2`）是唯一的 center**。

**包含职责**：
- dispatch arbitration（分派仲裁）
- truth finalization（真值终态确认）
- continuity legality gate（连续性合法性门控）
- closure authority（终态闭合权威）
- operator control plane（操作者控制平面）

**代码锚点**：`core/command_router.py`、`core/unified_runtime_truth_ingress.py`、`core/unified_result_ingress.py`、`core/unified_continuity_legality_authority.py`

**禁止使用**：不允许把 Android 或任何 participant 描述为平行 center 或 co-center。

---

### subject（主体）

**定义**：在系统中具有本地 lifecycle、本地执行判断权与本地可见面的运行时节点。Subject 不等于 passive endpoint，也不等于 canonical authority holder。

**分类**：
- **canonical center subject**：V2，持有全局 canonical authority
- **bounded relative subject**：Android、桌面 DesktopPresenceRuntime 等，具有本地主体性但边界受 canonical center 约束

**代码锚点**（bounded relative subject 示例）：`core/android_runtime_host.py` (`AndroidRuntimeHostRole`)、`RuntimeController.kt`

---

### participant（参与者）

**定义**：在一次 task / flow / session 执行中被 canonical center dispatch 到的可执行节点。Participant 是 subject 在具体执行语境中的角色实例。

**参与者角色**（用于 multi-subject 场景）：
- `primary`：主责执行参与者
- `assistant`：辅助参与者
- `fallback`：降级备选参与者
- `suspended`：当前挂起的参与者
- `takeover_candidate`：可接管的候选参与者
- `degraded`：降级状态的参与者

**代码锚点**：`core/android_participant_truth_ingress.py`、`core/android_participant_session_state.py`

---

### target（目标设备 / 目标节点）

**定义**：dispatch 指向的具体物理设备或逻辑执行节点，是 participant 的设备层对应实体。Target 必须经过 canonical dispatch slot 仲裁才能成为合法 dispatch 目标。

**代码锚点**：`core/canonical_dispatch_slot_authority.py`、`galaxy_gateway/device_router.py`

---

### truth（真值）

**定义**：被 canonical governance center（V2）认可的系统状态事实。Truth 分为三类：

| 分类 | 含义 | 代码锚点 |
|---|---|---|
| `authority_truth` | 决定"谁在运行、谁有权、谁可继续"的运行时决策事实 | `distributed_truth_ownership_convergence.py` |
| `acceptance_closure_readiness_truth` | lifecycle gate、session continuation、task closure 条件是否满足的证据事实 | `canonical_completion_ingress.py`、`attached_runtime_session.py` |
| `outward_projection_operator_truth` | operator / product-facing 只读投影，不得反向影响 authority truth | `core/routes/projection.py`、`core/operator_surface.py` |

**禁止使用**：Android 或 participant 的本地状态不能直接被称为 "canonical truth"，只能称为 "local truth"、"participant truth" 或 "execution evidence"。

---

### dispatch（分派）

**定义**：canonical center 将一项 task / command 路由到一个或多个 subject / participant 执行的过程。Dispatch 必须经过 dispatch arbitration，结果由 canonical truth chain 最终确认。

**代码锚点**：`core/command_router.py`、`core/runtime/source_dispatch_orchestrator.py`、`core/canonical_dispatch_slot_authority.py`

---

### continuity（连续性）

**定义**：session / task / flow 跨越连接断续的合法延续权。Continuity legality 由 V2 `unified_continuity_legality_authority` 统一仲裁。

**分类**：
- **local continuity**：Android 本地管理的离线队列、recovery 等；属于 bounded relative subject 的本地能力，不等于跨设备 continuity 合法性
- **cross-device continuity legality**：跨设备 continuity 的合法性判定，只能由 V2 canonical authority 出具

**代码锚点**：`core/unified_continuity_legality_authority.py`、`core/android_v2_continuity_contract.py`、`OfflineTaskQueue.kt`

---

### closure（终态闭合）

**定义**：一次 task / session / flow 的最终终态确认，由 V2 canonical truth chain 完成。Closure 需要：
1. 所有 participant truth 已上行并经过 truth ingress
2. canonical truth chain 完成 terminal state finalization
3. 无悬挂的 reconcile-required 状态

**代码锚点**：`core/unified_result_ingress.py`、`core/task_result_canonical_truth_chain.py`、`core/canonical_completion_ingress.py`

**禁止使用**：Android 或 participant 不能单方面宣布 closure；只能上行 evidence 供 V2 canonical truth chain 做 closure 决定。

---

### bounded authority（有界权威）

**定义**：Android 等 bounded relative subject 在本地 execution scope 内持有的合法局部权威。Bounded authority 的行使不得扩展到全局 canonical truth finalization 或 global dispatch arbitration。

**bounded 边界由以下约束定义**：
1. 本地 truth 上行必须经过 `core/android_participant_truth_ingress.py`
2. 本地 execution result 必须经过 `core/unified_runtime_truth_ingress.py` 进入 V2 canonical truth chain
3. 本地 lifecycle 变更不得直接写入 V2 canonical session truth

---

## 术语使用规则（所有 PR 必须遵守）

| 规则 | 说明 |
|---|---|
| R1 | Android 的状态应使用"participant truth"或"local truth"，不使用"canonical truth" |
| R2 | Android 不使用"dispatch authority"、"truth finalization authority"、"closure authority" |
| R3 | V2 不使用"passive orchestrator"、"dumb router"或任何削弱其 canonical authority 的措辞 |
| R4 | 新 PR 不得新造 "center"、"platform authority" 角色，除非该角色明确是 V2 的子模块 |
| R5 | outward-facing / operator-facing / product-facing 层只能"消费 canonical outputs"，不能"持有 authority" |
| R6 | multi-subject 场景中的 participant roles 使用 §participant 条目定义的分类，不自造新类别 |

---

## 参见

- `docs/SYSTEM_FORMAL_DEFINITION_V1.md` — 系统正式定义文档
- `docs/ugcp/UGCP_CANONICAL_VOCABULARY_V1.md` — UGCP 规范词汇（控制语言层）
- `core/distributed_truth_ownership_convergence.py` — truth 归属权威
- `core/contract_closure.py` — 合约闭合权威
