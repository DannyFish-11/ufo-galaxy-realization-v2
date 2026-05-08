# 双仓（V2 + Android）完整认知审查与治理收口基线（中文）

> 目标仓：`DannyFish-11/ufo-galaxy-realization-v2`
>
> 联动仓：`DannyFish-11/ufo-galaxy-android`
>
> 方法：仅以当前真实代码为证据；PR 叙事（含 PR993）不作为事实来源。

## 1) 方法与可校验治理表达

本次收口不是“纯文档总结”，同时新增了可机读审查 contract：

- `core/joint_dual_repo_cognition_closure_review.py`
  - 输出 8 个系统命题的结构化审查结论（判定 + 收口边界 + 双仓代码锚点）
- `tests/test_joint_dual_repo_cognition_closure_review.py`
  - 机器校验：8 命题齐全、边界一致、mesh 命题必须显式 constrained

## 2) 八个系统级命题审查结论（基于真实代码）

| 命题 | 判定 | 边界 | 说明 |
|---|---|---|---|
| P1 V2 是否形成唯一中心治理核 | 已成立 | fully_closed | V2 侧统一执行治理/模式门/统一治理语义已集中定义 |
| P2 Android 是否为强 runtime node | 部分成立 | partial | Android 已具本地执行与协作参与能力，但非 mesh 全局协调 authority |
| P3 双仓 execution governance 是否统一语义 | 部分成立 | constrained | V2 统一治理已落地，Android 侧有参与 contract；跨仓运行态一致性仍受约束 |
| P4 multimodal main chain 是否运行级闭合 | 部分成立 | constrained | Android 发射 + V2 ingress 语义链明确；全链路运行闭环证据仍需补强 |
| P5 capability authority/readiness/policy 是否稳定中心治理 | 部分成立 | partial | V2 中心治理已成型，但 Android 本地能力状态与 V2 truth 仍可能漂移 |
| P6 mesh collaboration / multi-device runtime 是否 fully close | 部分成立 | constrained | V2 已显式输出 mesh_runtime_state，Android 已给出参与 contract；full mesh 仍 deferred |
| P7 autonomy boundary 是否清晰 | 已成立 | fully_closed | V2 authority 与 Android 受限自治边界已在 governance + NL contract 中明确 |
| P8 剩余主轴是否集中在 ingress/state/orchestration/manifestation closure | 已成立 | fully_closed | 剩余问题已收敛为收口类工程，不应再夸大为架构未形成 |

## 3) 双仓关键代码锚点（抽样）

### V2 侧

- 中心治理核
  - `core/unified_execution_governance.py`
  - `core/unified_governance_semantics.py`
  - `core/android_mode_gate_policy.py`
- ingress / 语义链
  - `galaxy_gateway/android/handlers/goal_execution.py`
  - `core/desktop_presence_runtime.py`
  - `core/android_nl_semantic_chain_contract.py`
- state transparency / panel
  - `core/routes/panel.py` (`/api/v1/panel/unified`)
  - `core/unified_panel_aggregation.py`
  - `core/operator_surface.py`
  - `core/routes/operator.py` (`/api/v1/operator/action`)

### Android 侧

- runtime node / 本地自治执行
  - `app/src/main/java/com/ufo/galaxy/agent/AutonomousExecutionPipeline.kt`
  - `app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt`
- mesh participation contract
  - `app/src/main/java/com/ufo/galaxy/agent/LocalCollaborationAgent.kt`
  - `app/src/main/java/com/ufo/galaxy/runtime/AndroidMeshParticipationContract.kt`
  - `app/src/test/java/com/ufo/galaxy/runtime/Pr8AndroidMeshParticipationContractTest.kt`

## 4) 明确 constrained / partial / deferred 边界

- **mesh full runtime closure**：仍 constrained（Android contract 已明示 deferred capability）
- **cross-repo execution governance 一致性**：当前主要依赖 V2 治理 + Android contract，运行态一致性仍需跨仓持续验证
- **multimodal 主链闭环**：carrier/authority 语义清晰，但运行级全链路证据仍非 fully closed
- **capability truth 漂移风险**：Android 本地能力开关与 V2 capability truth 仍存在持续对齐需求

## 5) 不夸大结论（治理口径）

- 不再把 Android 叙述为“被动终端”
- 不把 mesh 结构存在误写成 full runtime close
- 不把 cross-repo contract 存在误写成跨仓运行态 fully proved

---

本文件与 `core/joint_dual_repo_cognition_closure_review.py`、`tests/test_joint_dual_repo_cognition_closure_review.py` 共同构成当前阶段默认认知与治理收口基线。
