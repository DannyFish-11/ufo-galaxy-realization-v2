# PR993 + PR1041~1043 双仓统一联合审查（V2 + Android）

> 类型：单 PR、双仓一体化联合审查交付物（中文）  
> 审查对象：`DannyFish-11/ufo-galaxy-realization-v2` + `DannyFish-11/ufo-galaxy-android`  
> V2 基线：`061633fbaa6a7c1743baa57ffcf656e01226014f`  
> Android 基线：`894fde816a46899830e8985e8d6ee06d236ab126`（GitHub API 返回的仓库默认分支提交 ref，审查时点）  
> 审查时点：`2026-05-10`  
> 方法：只以真实代码/真实 handler/真实状态路径/真实测试为证据；不以命名相似或文档叙事替代实现证据。

---

## 1) 双仓系统本质与角色边界（联合视角）

### 系统本质（非简化 server-client）
- 该系统是**中心化治理的分布式网络系统**：V2 是中心治理核，Android 是可本地执行、可接管参与、可跨设备参与的运行时节点，而非被动客户端。
- 关键代码锚点：
  - V2 侧治理与权威边界：`core/android_v2_continuity_contract.py`、`core/unified_execution_governance.py`、`core/unified_governance_semantics.py`
  - Android 侧运行时节点语义：`app/src/main/java/com/ufo/galaxy/runtime/RuntimeController.kt`、`.../network/GalaxyWebSocketClient.kt`、`.../runtime/AndroidMeshParticipationContract.kt`

### 角色与权威边界
- **治理权威（governance authority）**：V2（路由、准入、优先级、canonical decision）
- **规范真值权威（canonical truth authority）**：V2（终态与冲突裁决）
- **运行时局部真值（runtime local truth authority）**：Android 负责本机任务执行事实与本机连续性事实上报
- **证明权威（proof authority）**：当前主要由 V2/Android 各自回归测试提供；真实跨仓运行态证明不足
- **接管权威边界**：
  - V2：接管准入/优先级/冲突裁决（`core/unified_execution_governance.py`）
  - Android：接管执行与失败回落信号发射（`RuntimeController.notifyTakeoverFailed(...)`、`DelegatedTakeoverExecutor.kt`）

### local-link / cross-device-link / producer-consumer
- **Android local-link**：`LocalGoalExecutor`、`LocalCollaborationAgent.handleParallelSubtask(...)` 本地执行与并行子任务执行
- **Android→V2 cross-device uplink（producer→consumer）**：
  - producer: `GalaxyWebSocketClient.sendHandshake()` 发送 `device_register`/`capability_report`
  - producer: `RuntimeController.emitReconciliationSignal(...)` 发送 reconciliation
  - consumer: `galaxy_gateway/android/handlers/*`（registration/capability_report/reconciliation_signal/device_state_snapshot/handoff_v2_result）
- **其他设备节点语义**：在 V2 上统一按设备/会话治理，不是 Android 特例（`attached_runtime_session_registry`、`device_router`）

---

## 2) 按定义逐项联合审查（PR993 + PR1041~1043）

> 说明：仓内无 `PR1041/1042/1043` 字面标签。此处按已合并语义主题进行“定义域映射审查”，并显式区分定义层/实现层/证明层/跨仓运行层。
>
> 这三个编号来自本次 issue 的外部审查基线要求（任务定义层），并非仓内源码中的内建标签。

| 定义域 | 定义层期望 | V2 实现 | Android 实现 | 联合完成级别 | 结论 |
|---|---|---|---|---|---|
| PR993 基线（中心分布式系统认知） | V2 为中心治理核，Android 为主动运行节点 | `android_v2_continuity_contract`、`unified_execution_governance` | `RuntimeController`、`GalaxyWebSocketClient`、`AutonomousExecutionPipeline` | **回归证明存在**（结构+主链+大量测试）；**非真实跨仓运行证据** | **部分满足** |
| PR1041 映射：执行生命周期/真值对账/连续性 | admission→lifecycle→uplink→reconciliation→terminal 可核验 | `record_execution_lifecycle_event`、`record_result_uplink`、`get_uplink_truth_state`、`closed_loop_governance_consolidation` | `ReconciliationSignal`、`recordDelegatedTaskAccepted/publishTaskResult/...` | **主链存在 + 回归证明存在** | **部分满足**（跨仓真实运行证明不足） |
| PR1042 映射：mesh 参与语义与证明质量降级 | 不能把结构当 runtime-proven；proof quality 要影响治理 | `build_mesh_runtime_state`、`resolve_governance_path_decision(mesh_proof_quality)` | `AndroidMeshParticipationContract` 明确 PARTIAL/DEFERRED 与 deferred scope | **主链存在 + 回归证明存在** | **部分满足**（full mesh runtime 仍受限） |
| PR1043 映射：接管/恢复/审计权威闭环 | takeover 参与、冲突裁决、恢复、审计链闭环 | `unified_execution_governance` takeover 优先级/阻断；`execution_governance_audit_authority` | `DelegatedTakeoverExecutor`、`RuntimeController.notifyTakeoverFailed`、reconnect 后 truth snapshot | **主链存在 + 回归证明存在** | **部分满足**（恢复后 ownership transfer 的跨仓实机证据不足） |

### 四层判定（总览）
- **定义层**：存在且清晰。
- **实现层**：双仓均有大量真实实现，不是空壳。
- **证明层**：以本仓 Python 测试 + Android JVM 测试为主，强度较高但偏“仓内”。
- **运行态跨仓权威层**：缺少稳定真实设备/真实双仓运行回归证明，尚不能判为 canonical-proven。

---

## 3) 双仓联合 canonical path 全链路追踪

### A. 能力生产 → 上行 → V2 摄取 → 规范化 → 治理门控
1. **Android 生产**：`GalaxyWebSocketClient.sendHandshake()` 发送 `device_register` + `capability_report`（含 `cross_device_enabled`、host metadata）
2. **V2 摄取**：`registration.handle_device_register`、`capability_report.handle_capability_report`
3. **V2 规范化**：`absorb_capability_report_semantics(...)` + `CapabilityAuthority.upsert_contract(...)`
4. **V2 治理门控**：`unified_execution_governance` + `android_mode_gate_policy` + `unified_governance_semantics`

### B. 执行生命周期 → V2 执行运行态 → 决策因果
1. **Android 执行信号**：`RuntimeController.recordDelegatedTaskAccepted/publishTaskResult/publishTaskCancelled/...`
2. **V2 生命周期与上行记录**：`record_execution_lifecycle_event`、`record_result_uplink`、`record_state_uplink`
3. **V2 运行态真值**：`get_uplink_truth_state` 产出 canonical/reported outcome 与 reconciliation 状态
4. **治理决策因果**：`build_unified_governance_state` 的 `decision_causality`（含 `proof_input_diagnosis`）

### C. 连续性 / 重连 / 恢复
1. **Android**：`GalaxyWebSocketClient.flushOfflineQueue()`，按 durable session 清理 stale replay
2. **Android**：`RuntimeController` 重连后发 `runtimeTruthSnapshot`
3. **V2**：`registration` 的 canonical reconnect path + pending buffer replay
4. **V2**：`android_v2_continuity_contract` / session registry 做 continuity classification

### D. delegated takeover → 真值裁决 → ownership resumed transfer
1. **V2 决策与优先级**：`unified_execution_governance`（takeover_request 优先并阻断低优先级）
2. **Android 执行与失败回落**：`DelegatedTakeoverExecutor` + `RuntimeController.notifyTakeoverFailed`
3. **V2 真值裁决**：`get_uplink_truth_state` + `execution_governance_audit_authority.verify_governance_authority_integrity`
4. **恢复后转移**：存在结构与测试，但跨仓实机“恢复后 resumed ownership transfer”证据不足

### E. mesh 参与 / readiness / proof quality → V2 mesh runtime state → 治理影响
1. **Android 参与语义**：`AndroidMeshParticipationContract.evaluate(...)` 输出 PARTIAL/DEFERRED、`fullMeshRuntimeExecutable`
2. **V2 mesh 运行态**：`build_mesh_runtime_state` 输出 `proof_quality` + `governance_readiness_impact`
3. **V2 治理约束**：`resolve_governance_path_decision(..., mesh_proof_quality=...)` 在非 live proof 时降级/阻断

### F. 诊断 / 可观测 / 审计面
- **V2 API 面**：`/api/v1/operator/devices/ecosystem`、`/api/v1/operator/devices/execution-events`、panel/operator 路由
- **V2 审计面**：`closed_loop_governance_consolidation`、`execution_governance_audit_authority`
- **Android 运行日志/信号面**：`GalaxyLogger` + reconciliation signal emission

---

## 4) 联合问题全量审计（按你要求的风险族）

1. **能力漂移（capability drift）**：Android 本地能力与 V2 canonical capability 仍可能漂移（尤其 reconnect/replay 边界）。
2. **schema 漂移（schema drift）**：AIP v3 双侧维护，虽有 contract tests，但仍依赖双仓同步纪律。
3. **执行运行态真值漂移**：Android 本地活跃任务状态与 V2 canonical terminal outcome 在异常断连场景仍有时序风险。
4. **弱证明被过度陈述**：存在“runtime-level/e2e”命名测试，但多数仍为 stub/simulator 驱动，不等于实机双仓回归。
5. **fake E2E 被误当 true E2E**：V2 的 `AndroidRuntimeSimulator/Stub`、Android 的 pure-JVM fake collaborators 都不是跨仓实机。
6. **Android local truth vs V2 canonical truth 分歧**：定义上 V2 胜出，但实机高并发/长期运行下证据不足。
7. **resumed ownership transfer 证明薄弱**：takeover 中断、恢复后 ownership 连续转移缺少跨仓实机回归闭环。
8. **mesh runtime_closed 实达性不足**：Android 合同已明示 `fullMeshRuntimeExecutable=false` 条件，V2 会降级，但“full close”未实证。
9. **可观测/审计不对称**：V2 审计链更强，Android 侧仍以本地日志/单仓测试为主，跨仓统一审计证据面不足。
10. **定义措辞可能高于当前联合兑现**：若把“结构可行”写成“跨仓 runtime 已证”，会超出现实。

---

## 5) Fake E2E vs True E2E 分类（真实证明边界）

| 类别 | 样本 | 实际证明了什么 | 没证明什么 |
|---|---|---|---|
| V2-only 单元/集成 | `tests/test_pr13_closed_loop_governance_consolidation.py`、`tests/test_pr14_governance_audit_authority.py` | V2 治理与审计链逻辑稳定 | 不证明 Android 真机行为 |
| Android-only 本地测试 | `app/src/test/java/com/ufo/galaxy/e2e/E2EContractTest.kt` | Android 本地执行与协议对象契约 | 不证明 V2 真实摄取/裁决 |
| V2 协议模拟（stub/simulator） | `tests/integration/test_android_runtime_e2e.py`、`test_android_runtime_state_snapshot_e2e.py` | V2 真实 handler + store 路径可被模拟 Android 激活 | 不是 Kotlin 进程/真机端到端 |
| cross-repo mock proof | `tests/integration/test_v2_android_protocol_regression.py`（`MagicMock/AsyncMock`） | 协议回归、断连重连语义在 V2 侧可回归 | 非真实双仓运行闭环 |
| true cross-repo runtime regression | 当前未看到可复现实机双仓 CI 证据 | — | 仍是核心缺口 |

补充证据：
- V2 工作流注释已明确 Android 仓还需独立 `./gradlew assembleDebug / testDebugUnitTest / emulator smoke` 才能形成完整双仓 CI 闭环（`.github/workflows/dual_repo_integration.yml`）。

---

## 6) 主要问题分级 + 归属 + 解决范围

| 问题 | 代码锚点（V2 / Android） | 类型 | 严重度 | 影响 | 根因归属 | 解决范围 |
|---|---|---|---|---|---|---|
| 缺少真实双仓运行回归基线 | V2: `tests/integration/test_android_runtime_e2e.py`（simulator）；Android: `E2EContractTest.kt`（pure JVM fake） | Proof Gap | High | 影响“是否真实达成定义”的最终判定 | Dual | 双仓都要改 |
| runtime truth 时序冲突风险 | V2: `get_uplink_truth_state`; Android: `RuntimeController` 多信号发射 | Core Runtime Gap | High | 断连/恢复场景可能出现判定滞后或冲突 | Dual | 双仓都要改 |
| resumed ownership transfer 证据不足 | V2 takeover治理 + audit；Android takeover fallback/recovery | Definition Fulfillment Gap | High | 接管语义仅到“可实现+回归”，未到“实机权威闭环” | Dual | 双仓都要改 |
| mesh full runtime 仍 constrained | V2 `mesh_proof_quality` 降级门控；Android `AndroidMeshParticipationContract` deferred scope | Runtime Gap | Medium-High | 无法宣称 full mesh runtime closed | Dual | 双仓都要改 |
| 观测面不对称 | V2 operator/audit surfaces 强；Android 统一外显证据弱 | Observability Gap | Medium | 双仓联合排障和发布门禁可信度下降 | Dual | 双仓都要改 |
| schema/version 漂移风险 | V2 `aip_v3.py` + bridge handlers；Android MsgType/ReconciliationSignal | Governance Gap | Medium | 版本迭代时易出现隐式不兼容 | Dual | 双仓都要改 |
| Android 本地能力与 V2 能力真值持续对齐不足 | V2 capability authority + device_state_store；Android metadata/capability emission | Runtime Gap | Medium | 路由/准入判定可能偏差 | Dual | 双仓都要改 |

---

## 7) 双仓一体化后续 PR 路线图（可执行）

### PR-A：真实双仓运行回归最小闭环
- **范围**：Both
- **目标问题**：真 E2E 缺失、证明级不足
- **落点**：
  - V2：新增仅接收真实 Android 运行回传的回归验收门
  - Android：CI 接入 `assembleDebug`、`testDebugUnitTest`、最小 emulator smoke
- **依赖顺序**：首要
- **验收标准**：至少 1 条真实 `register→capability→dispatch→result→truth` 跨仓 CI 绿灯
- **验收标准**：至少 3 条真实跨仓 CI 场景（主链成功、断连恢复、takeover 失败回落）全部绿灯
- **推进效果**：从“回归证明存在”推进到“跨仓运行证据开始成立”

### PR-B：takeover + recovery ownership transfer 实机证据
- **范围**：Both
- **目标问题**：resumed ownership transfer 证明薄弱
- **落点**：
  - V2：补充 takeover/recovery 审计对账断言
  - Android：补充 takeover 中断/恢复/failed->resumed 信号链一致性
- **依赖顺序**：在 PR-A 后
- **验收标准**：接管中断后恢复路径在双仓 CI 可稳定复现并由 V2 审计链判定一致
- **推进效果**：把接管语义从“结构+本地回归”推进到“跨仓可证”

### PR-C：mesh 参与从 PARTIAL 到可量化提升
- **范围**：Both
- **目标问题**：mesh runtime constrained
- **落点**：
  - Android：补齐 deferred capability（或明确不可达并持续降级）
  - V2：mesh_proof_quality 与 readiness gate 联动升级
- **依赖顺序**：PR-B 后
- **验收标准**：mesh_proof_quality 至少在指定场景达到 live 且不回退为 stale/missing
- **推进效果**：减少“结构存在但 runtime 不可达”区间

### PR-D：双仓统一证据面与发布门禁
- **范围**：Both
- **目标问题**：观测不对称、证据门禁碎片化
- **落点**：统一 cross-repo audit artifact schema + gate
- **依赖顺序**：PR-A/B/C 后
- **验收标准**：单次发布可产出双仓联合证据包（运行证据+审计证据+契约一致性）
- **推进效果**：形成可持续“定义兑现”机制，而非一次性审查

---

## 8) 最终中文决策结论

1. **这两个仓合起来的真实系统**是“V2 中心治理 + Android 主动运行节点 + 其他设备节点参与”的中心化分布式网络系统，不是简化 server-client。  
2. **当前真实完成度**：已超出纯结构阶段，主链与大量回归证明存在；但尚未达到“跨仓运行态 canonical-proven”。  
3. **对 PR993 / PR1041~1043 的满足度**：整体为**部分满足**（定义层和实现层较强；证明层偏仓内；跨仓实机权威证据不足）。  
4. **由真实代码支撑的结论**：
   - V2 治理/裁决权威明确且实现充分；
   - Android 具本地执行、接管参与、跨设备参与能力；
   - mesh proof quality 与治理降级机制真实存在。  
5. **仅属结构或本地证明、尚不足以宣称完成的结论**：
   - true cross-repo runtime regression（实机）
   - resumed ownership transfer 的跨仓实证
   - full mesh runtime closed
6. **最高优先级真实缺口**：先补“真实双仓运行回归闭环（PR-A）”，再补“接管恢复权威闭环（PR-B）”。没有这两项，任何“已完全兑现定义”的说法都不严谨。
