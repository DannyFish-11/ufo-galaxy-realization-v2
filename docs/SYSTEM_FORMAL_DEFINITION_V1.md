# 双仓系统正式定义 v1

> **适用仓库：** `DannyFish-11/ufo-galaxy-realization-v2`（V2）、`DannyFish-11/ufo-galaxy-android`（Android）  
> **文档性质：** 架构定义冻结。不是宣传稿，不是新框架。基于真实已有代码、真实热路径、真实中心治理链路与真实 Android 联动链路，对系统定义、术语边界与生命周期语义做最小必要固化，为后续所有 PR 和双仓协同提供统一语言基础。

---

## 1. 正式系统定义

> **中心 canonical 治理 + 有界相对主体 runtime 的分布式 AI 执行架构。**

本系统**不是**：

- 中心 + 被动设备端（Android 不是 passive execution endpoint 或 UI shell）
- 平行双中心（Android 不持有 global truth finalization 或 global dispatch authority）

本系统**是**：

- V2 是 **canonical governance / truth convergence / dispatch arbitration / closure authority 的唯一中心**。
- Android 是 **bounded relative subject runtime**：具有本地 lifecycle、local continuity、local execution judgment、local AI system consumption、local visible surfaces，但**不拥有**全局 truth finalization 与全局 dispatch authority。

---

## 2. 系统两侧角色定义

### 2.1 V2 — canonical governance center

V2 持有以下权威，代码锚点如下：

| 权威域 | 代码锚点 |
|---|---|
| 跨设备分派仲裁 / dispatch arbitration | `core/command_router.py` (`CommandRouter.route_envelope`) |
| 运行时真值汇聚 / runtime truth convergence | `core/unified_runtime_truth_ingress.py` (`RUNTIME_TRUTH_INGRESS_AUTHORITY`) |
| 结果摄取与 truth chain | `core/unified_result_ingress.py` (`UnifiedResultIngress`) |
| 连续性合法性仲裁 | `core/unified_continuity_legality_authority.py` (`UnifiedContinuityLegalityAuthority`) |
| Android participant truth 归并 | `core/android_participant_truth_ingress.py` (`ingest_android_participant_truth_message`) |
| Operator 观察面 / control plane | `core/operator_surface.py` (`OperatorSurface`), `core/routes/operator.py` |
| 任务真值链 / task canonical truth | `core/task_result_canonical_truth_chain.py` |
| 合约闭合声明 | `core/contract_closure.py` (`INTERNAL_CONTRACT_CLOSURE_AUTHORITY`) |
| 分布式真值归属 | `core/distributed_truth_ownership_convergence.py` |
| Canonical dispatch slot 仲裁 | `core/canonical_dispatch_slot_authority.py` (`CanonicalDispatchSlotAuthority`) |

**结论**：V2 是 canonical governance / truth convergence / dispatch arbitration / closure authority 的唯一中心。这不是命名主张，而是代码实证。

### 2.2 Android — bounded relative subject runtime

Android 不是被动执行终端，也不是平行 canonical center。Android 是 **bounded relative subject runtime**，具有以下本地权威，但其边界被 V2 canonical 约束：

| 本地权威 / 能力 | 代码锚点（Android 仓） | 边界说明 |
|---|---|---|
| 本地 lifecycle 管理 | `RuntimeController.kt` | 本地生命周期由 Android 自主维持；但全局 session 由 V2 canonical session truth 最终 |
| 本地 AI system consumption | `LlamaCppPlannerService.kt`, `NcnnGroundingService.kt`, `LocalLoopExecutor.kt` | 本地 AI 消费与推理；结果需上行 V2 canonical 验收 |
| 本地 execution mode 判定 | `LocalExecutionModeGate.kt` | 本地模式门控；mode policy 来自 V2 canonical policy |
| 本地 continuity/recovery | `AndroidContinuityIntegration.kt`, `OfflineTaskQueue.kt` | 本地连续性由 Android 维持；跨设备 continuity legality 由 V2 `unified_continuity_legality_authority` 仲裁 |
| V2 transport 接入 | `GalaxyConnectionService.kt`, `GalaxyWebSocketClient.kt` | 必须通过 `galaxy_gateway/routes/websocket.py` 接入 V2 canonical ingress |
| 自治执行管道 | `AutonomousExecutionPipeline.kt` | 本地执行自主；结果必须经 `android_participant_truth_ingress.py` 上行 |
| 本地可见面 / local UI visible surface | Android native UI, diagnostics | 只消费 bounded local outputs，不持有 V2 canonical truth |

**bounded 的含义**：Android 的本地权威受以下约束限定：
1. Android 的 participant truth 上行必须经过 `core/android_participant_truth_ingress.py`，不得绕过。
2. Android 的 execution result 上行必须经过 `core/unified_runtime_truth_ingress.py` 进入 V2 canonical truth chain。
3. Android 不得对 V2 canonical session truth、task terminal state 或 dispatch arbitration 做最终 finalization。
4. Android 本地持有的 truth 是 local-authoritative execution evidence，不是 global canonical truth。

---

## 3. 热路径与主链链路

### 3.1 V2 中心治理主链（真实热路径）

```
TaskEnvelope 入口
  → CommandRouter.route_envelope()         [core/command_router.py]
  → SourceDispatchOrchestrator             [core/runtime/source_dispatch_orchestrator.py]
  → Android participant truth ingress      [core/android_participant_truth_ingress.py]
  → UnifiedRuntimeTruthIngress             [core/unified_runtime_truth_ingress.py]
  → UnifiedContinuityLegalityAuthority     [core/unified_continuity_legality_authority.py]
  → UnifiedResultIngress                   [core/unified_result_ingress.py]
  → TaskResultCanonicalTruthChain          [core/task_result_canonical_truth_chain.py]
  → OperatorSurface / ProjectionLayer      [core/operator_surface.py, core/routes/projection.py]
```

此主链是 V2 canonical center 的 truth convergence / dispatch / closure 主路径。所有 Android 上行信号最终都汇入此链。

### 3.2 Android bounded subject runtime 联动链路（真实热路径）

```
Android 本地执行
  → AutonomousExecutionPipeline.kt
  → LocalLoopExecutor.kt / LlamaCppPlannerService.kt
  → GalaxyConnectionService.kt / GalaxyWebSocketClient.kt
  → V2 /ws/device/{device_id}  [galaxy_gateway/routes/websocket.py]
  → android_participant_truth_ingress.py 或 unified_runtime_truth_ingress.py
  → V2 canonical truth chain
```

### 3.3 Operator control plane 链路

```
Operator action
  → core/routes/operator.py  (POST 端点)
  → OperatorSurface.execute_operator_action()
  → canonical runtime / dispatch / truth 链路
  → Operator read projection (GET 端点，只消费 canonical outputs)
```

---

## 4. 核心语义声明

### 4.1 Verdict / truth / closure / continuity 语义

| 概念 | 语义 | canonical 模块 |
|---|---|---|
| **verdict** | 对一项 dispatch / continuity / closure 行为的最终裁定，由 canonical authority 出具，不可被 subject 单方面覆盖 | `canonical_dispatch_slot_authority.py`, `unified_continuity_legality_authority.py` |
| **truth** | 系统中被 canonical governance center（V2）认可的状态事实；区分 authority_truth（决定谁运行谁有权）、acceptance_closure_truth（lifecycle 门控与闭合证据）、outward_projection_truth（只读投影） | `distributed_truth_ownership_convergence.py` |
| **closure** | 一次 task / session / flow 的最终终态确认，由 V2 canonical truth chain 完成，Android / participant 只能上行 evidence，不能单方面宣布 closure | `unified_result_ingress.py`, `task_result_canonical_truth_chain.py` |
| **continuity** | session / task 跨越连接断续的合法延续权，由 `unified_continuity_legality_authority.py` 统一仲裁；Android 本地 continuity handling 只在本地有效，跨设备 continuity 合法性须经 V2 gate | `unified_continuity_legality_authority.py`, `android_v2_continuity_contract.py` |

### 4.2 Android 是 bounded relative subject runtime 的核心含义

1. **bounded**：Android 的本地权威有明确边界，不扩展到全局 canonical truth 或 dispatch arbitration。
2. **relative subject**：Android 在自己的 local execution 上下文中是主体（自主判断、自主执行、本地可见），而非被动接收者。
3. **runtime**：Android 是真实运行时，持有 local lifecycle、local AI execution、local continuity，不是 UI 壳或配置终端。

---

## 5. 明确禁止的漂移方向

以下方向**不允许**在后续 PR 中出现：

1. 把 Android 重新降格为 passive execution endpoint 或 UI 壳。
2. 把 Android 抬升为持有 global truth finalization 或 global dispatch authority 的平行 canonical center。
3. 新造平行 unified platform facade、超级 coordinator 或新的抽象噪音文档体系。
4. operator / projection / product-facing 层被抬高为新的 authority center。
5. 绕过 `core/unified_runtime_truth_ingress.py`、`core/android_participant_truth_ingress.py`、`core/unified_result_ingress.py` 直接写入 canonical state。

---

## 6. 本文档的约束力

本文档由 `tests/test_task1_formal_system_definition.py` 机器约束，确保以下关键术语与代码锚点不被后续 PR 静默删除：

- 核心术语：`bounded relative subject runtime`、`canonical governance`、`truth convergence`、`dispatch arbitration`、`closure authority`
- 代码锚点：`core/command_router.py`、`core/unified_runtime_truth_ingress.py`、`core/unified_result_ingress.py`、`core/unified_continuity_legality_authority.py`、`core/android_participant_truth_ingress.py`、`core/operator_surface.py`、`core/routes/operator.py`

---

## 7. 后续 PR 语言基础

本文档为以下后续工作提供统一语言基础：

- dispatch / continuity / truth / contract 整改：使用 §3.1 热路径与 §4.1 语义
- Android 主体性整改：使用 §2.2 边界定义与 bounded 约束
- Operator governance plane 整改：使用 §3.3 链路定义
- Multi-subject closure / reconciliation 整改：使用 §4.1 closure 语义
- 所有 PR 的 subject/participant/target/center 措辞：使用 §8（见 `docs/DUAL_REPO_UNIFIED_GLOSSARY_V1.md`）

---

## 参见

- `docs/DUAL_REPO_UNIFIED_GLOSSARY_V1.md` — 双仓统一术语表
- `docs/ugcp/UGCP_CONSTITUTION_V1.md` — UGCP 宪法（控制语言冻结）
- `docs/ugcp/UGCP_CANONICAL_AUTHORITY_CHAIN_V1.md` — 权威链规范
- `core/distributed_truth_ownership_convergence.py` — 分布式真值归属
- `core/contract_closure.py` — 合约闭合权威
