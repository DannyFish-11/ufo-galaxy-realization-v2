# 双仓联合代码审查索引

> 审查范围：`DannyFish-11/ufo-galaxy-realization-v2`（V2 中心侧，Python）
> + `DannyFish-11/ufo-galaxy-android`（Android 端侧，Kotlin）
>
> 审查依据：基于两个仓库的真实代码，不以文档为主要依据。

---

## 文件清单

| 文件 | 日期 | 内容 |
|------|------|------|
| [NEXT_STAGE_DUAL_REPO_FOLLOW_THROUGH_CONVERGENCE_2026-05.md](./NEXT_STAGE_DUAL_REPO_FOLLOW_THROUGH_CONVERGENCE_2026-05.md) | 2026-05-14 | **🆕 下一阶段双仓收口基线（推荐优先阅读）**：明确 V2 待办、Android 待办、跨仓闭环依赖图与实操可用性阻塞，并记录本次 V2 侧 board/operator 收口延续实现 |
| [DUAL_REPO_CLOSURE_GOVERNANCE_OPERABILITY_AUDIT_2026-05.md](./DUAL_REPO_CLOSURE_GOVERNANCE_OPERABILITY_AUDIT_2026-05.md) | 2026-05-14 | **🆕 本次 PR 基线（推荐优先阅读）**：系统可用性审查、三态真实性审查、闭环治理传播审查、operator board 同源解释，基于真实代码探针，诚实分离已完成/本次补强/仍需 Android 跟进 |
| [V2_DUAL_REPO_INTEGRITY_LINKAGE_BASELINE_2026-05.md](./V2_DUAL_REPO_INTEGRITY_LINKAGE_BASELINE_2026-05.md) | 2026-05-13 | **基于 993P2 的 V2 双仓完整性联动与关键缺口补强基线**：用真实代码回答系统身份、双仓职责、主链路、完成度、跨仓矛盾，并给出已落地的 V2 侧完整性修复 |
| [ANDROID_LOCAL_TO_DISTRIBUTED_PARTICIPATION_AUDIT_2026-05.md](./ANDROID_LOCAL_TO_DISTRIBUTED_PARTICIPATION_AUDIT_2026-05.md) | 2026-05-12 | **Follow-up 审计基线**：回答 Android 从 local-only 到跨设备/分布式参与的真实代码条件与缺口 |
| [PRE_IMPLEMENTATION_DUAL_REPO_EXECUTION_BASELINE_2026-05.md](./PRE_IMPLEMENTATION_DUAL_REPO_EXECUTION_BASELINE_2026-05.md) | 2026-05-12 | **预实施基线文档**：严格区分真实运行路径、推断关系与契约/审计层 |
| [DEEP_JOINT_REVIEW_2026.md](./DEEP_JOINT_REVIEW_2026.md) | 2026-04-26 | **深度联合审查主文档**（8 主题全覆盖，含问题全集与 workstream 优先级）|
| [01_system_positioning.md](./01_system_positioning.md) | 2026-04-24 | 系统整体定位：从真实代码反推系统是什么 |
| [02_responsibility_boundary.md](./02_responsibility_boundary.md) | 2026-04-24 | 双仓职责边界：V2 与 Android 各自负责什么 |
| [03_key_flows.md](./03_key_flows.md) | 2026-04-24 | 主链路与关键流转：代码层面的执行路径梳理 |
| [04_cross_repo_contract.md](./04_cross_repo_contract.md) | 2026-04-24 | 双仓 contract/signal 闭环：真实接通 vs 骨架声明 |
| [05_maturity_assessment.md](./05_maturity_assessment.md) | 2026-04-24 | 成熟度与缺口：当前阶段判断与下一步方向 |

---

> **推荐阅读顺序**：先读 `NEXT_STAGE_DUAL_REPO_FOLLOW_THROUGH_CONVERGENCE_2026-05.md`（本次 PR 的下一阶段双仓收口责任与依赖图），再读 `DUAL_REPO_CLOSURE_GOVERNANCE_OPERABILITY_AUDIT_2026-05.md`（可用性与闭环治理审查基线），再读 `V2_DUAL_REPO_INTEGRITY_LINKAGE_BASELINE_2026-05.md` 了解 993P2 缺口补强背景，最后用 `DEEP_JOINT_REVIEW_2026.md` 与 `PRE_IMPLEMENTATION_DUAL_REPO_EXECUTION_BASELINE_2026-05.md` 追补细节。

---

## 快速结论（可直接复制使用）

### 这个系统是什么

> **一套以 Android 设备作为 delegated runtime 执行端、以 V2 Python 服务作为 canonical orchestration 中心的跨端任务执行与治理平台。**
>
> 系统围绕"delegated canonical path"进行结构化建设：V2 负责决策、调度、真值对齐、结果收敛、发布治理；Android 负责本地执行、信号上报、接受 handoff、参与 readiness/acceptance/governance 评估。

### 当前真实状态一句话

> **双端 transport contract 已接通，基础执行信号闭环基本完成，readiness/acceptance/governance/strategy 骨架已在双端对齐建立，但评估引擎与中心侧决策之间的实时连接信号流仍是最关键的未闭合点。**

---

## 关键代码坐标速查

### V2 侧关键模块（core/ 目录）

| 模块 | PR 编号 | 功能 |
|------|---------|------|
| `android_runtime_host.py` | PR-5 | Android 设备 runtime-host 角色分类 |
| `flow_continuity_coordinator.py` | PR-3 | 统一 continuity/replay 决策入口 |
| `flow_level_truth_ownership.py` | PR-5V2 | flow 级别真值权威模型 |
| `flow_aware_result_convergence.py` | PR-6V2 | flow 感知的结果收敛协调器 |
| `flow_level_operator_surface.py` | PR-7V2 | delegated flow 的 operator 投影 |
| `compat_legacy_path_blocking_canonicalization.py` | PR-8 | compat/legacy 阻断 canonical 化层 |
| `delegated_flow_readiness_gate.py` | PR-9V2 | 发布就绪门控 |
| `delegated_flow_acceptance_gate.py` | PR-10V2 | 毕业验收门控 |
| `delegated_flow_post_graduation_governance.py` | PR-11V2 | 毕业后持续合规治理 |
| `delegated_flow_program_strategy.py` | PR-12V2 | 程序级演进策略控制 |
| `android_execution_signal_reconciler.py` | PR-13 | 入站 Android 信号规范化对账 |
| `android_delegated_signal_ingress.py` | PR-16 | delegated_execution_signal 规范入站 |
| `android_participant_truth_ingress.py` | PR-4V2 | Android 参与者真值入站和对账 |
| `android_handoff_v2_response_ingress.py` | PR-H | handoff_envelope_v2 响应入站 |
| `android_runtime_dispatch_binding.py` | PR-11 | 派遣绑定记录（session/device/contract/tracker） |

### Android 侧关键模块（com.ufo.galaxy 包）

| 模块 | 包路径 | 功能 |
|------|--------|------|
| `GalaxyWebSocketClient.kt` | network/ | 唯一跨端上行 transport，连接 V2 gateway |
| `AipModels.kt` | protocol/ | AIP v3 消息类型全集，镜像 V2 |
| `DelegatedRuntimeUnit.kt` | agent/ | delegated runtime 执行单元 |
| `DelegatedHandoffContract.kt` | agent/ | handoff contract 管理 |
| `DelegatedTakeoverExecutor.kt` | agent/ | takeover 执行器 |
| `AutonomousExecutionPipeline.kt` | agent/ | 自主执行管线 |
| `RuntimeController.kt` | runtime/ | 运行时生命周期总控（152KB，最重要） |
| `DelegatedExecutionSignal.kt` | runtime/ | delegated 执行信号结构定义 |
| `DelegatedRuntimeReadinessEvaluator.kt` | runtime/ | Readiness 维度评估器 |
| `DelegatedRuntimeAcceptanceEvaluator.kt` | runtime/ | Acceptance 维度评估器 |
| `DelegatedRuntimePostGraduationGovernanceEvaluator.kt` | runtime/ | 毕业后 Governance 评估器 |
| `DelegatedRuntimeStrategyEvaluator.kt` | runtime/ | Strategy 演进评估器 |
| `AndroidLocalTruthOwnershipCoordinator.kt` | runtime/ | 本地真值权威协调器 |
| `AndroidFlowAwareResultConvergenceParticipant.kt` | runtime/ | 结果收敛参与者 |
| `AndroidCompatLegacyBlockingParticipant.kt` | runtime/ | compat/legacy 阻断参与者 |
| `CrossRepoConsistencyGate.kt` | protocol/ | 跨仓一致性门控 |
| `CanonicalDispatchChain.kt` | runtime/ | canonical 派遣链 |
| `StabilizationBaseline.kt` | runtime/ | 稳定化基线（102KB） |
