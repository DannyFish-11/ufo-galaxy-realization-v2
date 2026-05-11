# 基于双仓完整真实代码的最终增强认知审查（中文）

## 1. 审查方法与证据边界
- 仅采用真实代码与测试：V2 本仓源码；Android 仓通过 GitHub 代码检索与文件抓取（提交锚点 `bfddd285a0116efd999ad0a866258a5de8a73f4f`）。
- 核心锚点：
  - V2：`core/openclawd.py::_determine_execution_path`、`core/command_router.py`、`core/unified_execution_governance.py`、`core/closed_loop_governance_consolidation.py`、`galaxy_gateway/android/handlers/{registration,goal_execution,task_lifecycle}.py`、`core/orchestration_authority/legacy_paths.py`、`tests/integration/test_pr13a_dual_runtime_cross_repo_regression.py`。
  - Android：`app/src/main/java/com/ufo/galaxy/service/GalaxyConnectionService.kt`、`.../runtime/AndroidCrossRepoRegressionRuntimeHooks.kt`、`.../runtime/UnifiedTruthReconciliationSurface.kt`、`.../data/AppSettings.kt`、`.../runtime/Pr11BAndroidCrossRepoRegressionRuntimeHooksTest.kt`。
- 证据边界：未在本仓直接执行 Android 构建/实机长稳回归；该部分结论按代码可证范围给出，并显式标注“证据不足”。

## 2. 系统本体最终判断
- 这套系统不是 PoC，也不是成熟分布式智能系统；当前最准确定位：**中心治理骨架已成型的半闭环双仓系统**。
- 依据：
  - 主链阶段被显式定义并可审计：`activation → execution → observation → reconciliation → completion`（`core/closed_loop_governance_consolidation.py`）。
  - 中心侧把“到 completion”与“成熟闭环”拆开（`system_completion_ready/level/gap_types`）。
  - Android 侧已把 `LOCAL_RUNTIME/DIAGNOSTICS/RECOVERY/TAKEOVER/MESH` 纳入 dual-repo regression hooks（`AndroidCrossRepoRegressionRuntimeHooks.kt`）。
- 统一结论：系统“能跑 + 能裁决 + 能审计”的骨架已成立，但“复杂场景下稳定成熟闭环”尚未成立。

## 3. 双仓真实职责划分
- V2（中心治理）：
  - 执行路径裁决与分流：`OpenClawd._determine_execution_path`。
  - 跨设备派发权威：`CommandRouter.route_envelope`（并在 `legacy_paths.py` 标记其它入口为 compat/legacy）。
  - 终态真相与对账：`record_result_uplink/record_state_uplink/get_uplink_truth_state/notify_execution_completed`。
  - 系统级闭环成熟判定：`query_closed_loop_governance_state` + completion readiness 分类。
- Android（设备执行）：
  - 网关入站执行与回传总入口：`GalaxyConnectionService`。
  - 本地运行、诊断、恢复、接管、mesh 等事实信号产出：`AndroidCrossRepoRegressionRuntimeHooks`。
  - 端侧统一真相归并：`UnifiedTruthReconciliationSurface`（epoch gating、terminal idempotency、authoritative mutation）。
- 已成立协作：任务下发、结果上行、中心 reconciliation、审计字段联动。
- 未完全成立协作：跨设备复杂故障的长期稳定性证明与端到端实机门禁（证据不足）。

## 4. 主链 / 旁路 / compat / fallback / degraded 全景拆解
- Canonical 主链：
  1) `OpenClawd._determine_execution_path` 决定 `local/cross_device/hybrid/none`；
  2) 跨设备进入 `CommandRouter.route_envelope`；
  3) Android 入站由 `GalaxyConnectionService` 处理；
  4) 回传进入 `goal_execution.py` / `task_lifecycle.py`；
  5) 中心在 `unified_execution_governance.py` 做 uplink 合并与 reconciliation；
  6) `closed_loop_governance_consolidation.py` 给出 stage/coherence/readiness。
- 旁路：`route_command`、旧 routes、旧 orchestrator path 等被登记为 `LEGACY_COMPATIBILITY`（`legacy_paths.py`）。
- fallback/degraded：
  - `legacy_paths.py` 明确 `CrossDeviceCoordinator`、`send_to_device()` 等兼容回退仍存在；
  - NodeRegistry/ProxyRelay/MeshCoordinator 路径被标注为 degraded fallback；
  - Android `AppSettings` 仍保留 takeover fallback 相关开关。
- 容易出现“伪闭环”的点：
  - uplink-only terminal（已被收紧，但仍可能被局部演示误读为系统闭环）；
  - compat fallback 成功被误当 canonical 成功；
  - 单设备 replay 成功被误当跨设备稳态能力。

## 5. 本地链路真实闭合情况
- 已闭合：
  - V2 本地执行分流与回传归并路径完整；
  - `task_lifecycle.py` 存在 idempotency signal guard、canonical status map、错误计数可观测；
  - `goal_execution.py` 在入口先过统一治理 gate（拒绝冲突/不合格执行）。
- 未闭合点：
  - 本地成功到系统成熟闭环之间仍受 completion readiness 缺口约束（如缺 uplink、reconciliation 未 fully accepted、runtime health 非 stable）。

## 6. 跨设备链路真实闭合情况
- 已成立：
  - 注册与连续性主路径明确：`device_register` 是 canonical reconnect path（`registration.py`）；
  - Android `GalaxyConnectionService` 是入站消息 canonical dispatcher；
  - V2 `test_pr13a_dual_runtime_cross_repo_regression.py` 已验证 replay 后 closure/audit/readiness/diagnosis 基本闭合。
- 尚未成立：
  - 跨设备长期抖动、重放洪峰、多设备并发冲突下的持续稳定门禁证据不足；
  - Android compat/legacy 影响到 V2 compat gate 的端到端可追踪证据仍不完整（证据不足）。

## 7. 状态 / 协议 / 契约统一性问题
- 已统一部分：
  - 协议骨架：`message_id/correlation_id/type/device_id/timestamp/payload`（`aip_v3.py`）。
  - 终态与对账语义：`reconciliation_status` 显式区分 `accepted`、`accepted_partial_observation`、`uplink_terminal_observation_requires_reconciliation`、`uplink_only_observation` 等。
  - 中心决策可解释性：`decision_causality` 暴露 `android_originated_canonical_diagnosis`、`ownership_transfer_proof_*`、`cross_repo_truth_*`。
- 仍有不统一风险：
  - 同名字段在“可观测状态”与“可裁决状态”间仍可能被上层误用（例如把 snapshot readiness 当作成熟闭环 readiness）；
  - compat/fallback 路径仍在，导致同名成功语义存在“canonical 成功 vs fallback 成功”的解释分叉。

## 8. 复杂故障场景矩阵
| 场景 | 代码级约束现状 | 结论 |
|---|---|---|
| delayed | registration reconnect continuity + replay；reconciliation active statuses 覆盖 delayed conflict | **部分覆盖** |
| conflicting | `_classify_uplink_terminal_confirmation` + conflict reconciliation status | **覆盖** |
| partial | `accepted_partial_observation` + partial_success 合并规则 | **覆盖** |
| degraded | runtime truth degraded / proof degraded 字段链路完整 | **覆盖** |
| interrupted/timeout | lifecycle terminal phase + timeout outcome 显式建模 | **覆盖** |
| retried/replayed | lifecycle 含 retrying/replayed；有 replay 证据回放测试 | **部分覆盖** |
| recovered | Android hooks + recovery truth diagnosis；中心侧可见 | **部分覆盖** |
| fallback | legacy_paths 明确 fallback 仍活跃 | **可控但未清退** |
| duplicate | task_lifecycle signal guard、terminal idempotency（Android reducer） | **覆盖** |
| stale | stale runtime truth 降级策略明确 | **覆盖** |

判定：复杂场景不是空白，但“覆盖”与“成熟闭环可证明”仍有距离，关键缺口在跨设备长稳证据。

## 9. 完成度统一评分与依据
评分逻辑（固定）：主链闭合 40 + 异常约束 25 + 双仓自动化证据 20 + 长稳实机证据 15。

- 双仓整体：**67/100**（30 + 18 + 13 + 6）
- 本地链路：**80/100**（35 + 20 + 15 + 10）
- 跨设备链路：**60/100**（25 + 15 + 12 + 8）
- 系统语义成立度：**64/100**（28 + 16 + 12 + 8）

统一口径：当前系统是“可运行半闭环 + 中心治理收紧完成”，不是“成熟统一闭环系统”。

## 10. 距离成熟系统的结构性差距
- P0 级结构差距（不补齐不能称真实成熟闭环）：
  1) canonical 与 fallback 路径仍并存，且尚未完成严格退场；
  2) 跨设备长稳门禁不足（持续重连/冲突/恢复/重复上报下的稳定证明缺失）。
- P1 级结构差距：
  1) 双仓状态语义虽可映射，但“可观测语义→裁决语义”仍有解释缝隙；
  2) compat 影响链路在端到端可追踪性上仍有证据缺口。
- P2 级增强：
  1) 统一趋势化成熟度面板（非一次性分数）；
  2) 将 cross_repo_truth 与 completion readiness 做持续漂移监控。

## 11. P0 / P1 / P2（执行化）
- **P0**：
  - 把 fallback 成功从“可运行”升级为“受限可观测”，并在发布门禁中禁止 fallback 冒充 canonical。  
  - 建立双仓长期回归门禁（多设备、重连、冲突、恢复、重复、stale）。
- **P1**：
  - 统一 Android/V2 状态词典到同一可机读契约（尤其 readiness/reconciliation/ownership 终态）。
  - 补全 compat influence 从 Android 识别到 V2 阻断的端到端证据链。
- **P2**：
  - 增加系统级成熟度趋势指标与回归漂移报警。

## 12. 最终一句话结论
**双仓当前真实状态是“中心治理已收紧的半闭环系统骨架”：主链已成立、伪闭环风险被显式压制，但跨设备长稳证明与 fallback 退场未完成，因此还不能称为成熟一整套 AI 分布式闭环系统。**
