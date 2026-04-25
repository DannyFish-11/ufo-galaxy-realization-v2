# 双仓联合代码审查索引

> 审查范围：`DannyFish-11/ufo-galaxy-realization-v2`（V2 中心侧，Python）
> + `DannyFish-11/ufo-galaxy-android`（Android 端侧，Kotlin）
>
> 审查依据：基于两个仓库的真实代码，不以文档为主要依据。
>
> 生成日期：2026-04-24

---

## 文件清单

| 文件 | 内容 |
|------|------|
| [01_system_positioning.md](./01_system_positioning.md) | 系统整体定位：从真实代码反推系统是什么 |
| [02_responsibility_boundary.md](./02_responsibility_boundary.md) | 双仓职责边界：V2 与 Android 各自负责什么 |
| [03_key_flows.md](./03_key_flows.md) | 主链路与关键流转：代码层面的执行路径梳理 |
| [04_cross_repo_contract.md](./04_cross_repo_contract.md) | 双仓 contract/signal 闭环：真实接通 vs 骨架声明 |
| [05_maturity_assessment.md](./05_maturity_assessment.md) | 成熟度与缺口：当前阶段判断与下一步方向（2026-04-24 版本） |
| [**06_consolidated_review_2026.md**](./06_consolidated_review_2026.md) | **2026-04-25 联合审查总结（最新版，含前版缺口修复状态确认）** |

---

## 快速结论（可直接复制使用）

### 这个系统是什么

> **一套以 Android 设备作为 delegated runtime 执行端、以 V2 Python 服务作为 canonical orchestration 中心的跨端任务执行与生命周期治理平台。**
>
> 系统围绕"delegated canonical path"进行结构化建设：V2 负责决策、调度、真值对齐、结果收敛、发布治理；Android 负责本地执行、信号上报、接受 handoff、参与 readiness/acceptance/governance 评估。

### 当前真实状态一句话（2026-04-25 更新）

> **delegated runtime 主链路已基本收敛成型（handoff 上行响应 handler + reconciliation signal handler 均已接通，PR-64 Android 本地真值归一已建立，PR-11-V2 lifecycle coordinator 已统一所有事件处理）；前版审查两大关键缺口已修复；readiness/governance 四层决策所需的 Android evaluator artifact → V2 gate 实时连接信号流仍是最关键待验证点。**

> 详见：[06_consolidated_review_2026.md](./06_consolidated_review_2026.md)（2026-04-25 最新版联合审查总结）

---

## 关键代码坐标速查

### V2 侧关键模块（core/ 目录）

| 模块 | PR 编号 | 功能 |
|------|---------|------|
| `android_delegated_runtime_lifecycle_coordinator.py` | PR-11-V2 | **中枢 facade，统一所有 Android lifecycle 事件处理** |
| `android_participant_truth_ingress.py` | PR-4V2 | Android 参与者真值入站和对账 |
| `android_participant_session_state.py` | PR-11-V2 | **9 阶段会话状态机（pre_dispatch → terminal）** |
| `android_runtime_transition_reducer.py` | PR-11-V2 | **单一 canonical 信号 → 状态转换 reducer** |
| `android_delegated_runtime_audit.py` | PR-10-V2 | **unified audit，ring buffer，按 task/session 查询** |
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
| `**ReconciliationSignal.kt**` | runtime/ | **PR-51：7 种信号类型，Android→V2 对账协议载体** |
| `**TruthReconciliationReducer.kt**` | runtime/ | **PR-64：Android 本地单一收敛入口，epoch 门控** |
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
