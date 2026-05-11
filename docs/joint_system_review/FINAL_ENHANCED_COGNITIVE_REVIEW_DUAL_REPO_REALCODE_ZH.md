# 基于PR993的双仓中心分布式系统最终增强审查与真实问题继续收口

## 0. 先重审再下刀（本轮方法）
- 本轮不沿用旧口径，先按双仓真实代码重审系统本体、主链、角色边界，再决定是否修代码。
- 代码锚点：
  - V2：`core/openclawd.py`、`core/command_router.py`、`core/unified_execution_governance.py`、`core/closed_loop_governance_consolidation.py`、`galaxy_gateway/android/handlers/*.py`
  - Android（双仓联审锚点）：`GalaxyConnectionService`、`DelegatedRuntimeAcceptanceEvaluator`、`UnifiedTruthReconciliationSurface`、`AndroidCrossRepoRegressionRuntimeHooks`
- 本轮新增收口只针对重审后仍真实存在的问题：**closure 结果层未硬区分 canonical 与 fallback/compat/degraded 成功语义**。

## 1. 基于 PR993 的系统本体再定义
PR993 的关键意义不是“补模块”，而是把双仓从“中心派发 + 端侧执行”提升到可审计的**中心分布式系统骨架**：
- 中心（V2）保持 authority（路径裁决、真相裁决、闭环裁决）；
- 端侧（Android）不是被动脚本终端，而是具备运行时发起信号、接管接受/拒绝、局部自治判断与恢复参与能力；
- 双仓通过统一 lifecycle/reconciliation/closure 语义形成可验证主链。

## 2. 为什么它是中心分布式系统，而不是简单中心-执行端模型
它不是“单向派发流水线”，而是“中心 authority + 端侧主动参与”的协同闭环：
1. V2 决定执行路径（`local/cross_device/hybrid/none`）与最终 truth；
2. Android 在运行时持续产出 capability/lifecycle/diagnosis/recovery/takeover 证据；
3. 中心侧做 reconciliation 与成熟闭环判定（`system_completion_ready` 与 `stage==completion` 分离）。

结论：**中心明确，但分布式参与是实在存在的，不是装饰。**

## 3. V2 authority 与 Android 发起/接管/局部自治边界
### V2（authority）
- 路径裁决：`OpenClawd._determine_execution_path`
- 派发权威：`CommandRouter.route_envelope`
- 执行治理与终态真相：`unified_execution_governance`
- 系统级闭环裁决：`closed_loop_governance_consolidation`

### Android（主动参与方，不是纯执行壳）
- 本地执行与运行时信号发起：`GalaxyConnectionService`
- 接管接受/拒绝与所有权收敛参与：`DelegatedRuntimeAcceptanceEvaluator` + `takeover_response`
- 局部真相归并与端侧幂等：`UnifiedTruthReconciliationSurface`
- Recovery/diagnostics/mesh 证据面参与：`AndroidCrossRepoRegressionRuntimeHooks`

> 纠正：把 Android 简化为“单纯执行延伸节点”是不准确的；准确口径是“中心 authority 下的分布式主动参与节点”。

## 4. 主链重新解释（升级版）
1. V2 认知与路径裁决：`OpenClawd`
2. 跨设备派发：`CommandRouter` → gateway WS
3. Android 运行时执行与判定：ConnectionService/AcceptanceEvaluator
4. 双向上报与信号入链：`goal_execution_result` / `task_lifecycle` / `reconciliation_signal`
5. V2 统一治理与真相归并：`unified_execution_governance`
6. 全环闭合与成熟判定：`closed_loop_governance_consolidation`

升级点：主链不再是“中心派发—端侧执行—中心收口”的线性叙述，而是**中心裁决 + 端侧主动信号 + 中心治理归并**的闭环主链。

## 5. cross-device 打开后的系统能力边界
- 打开后，Android 可承担更完整系统能力：执行、状态发起、接管参与、恢复参与、诊断证据参与。
- 但边界依然明确：最终 authority（truth/closure/release gate）在 V2，不在端侧。

## 6. 之前认知里不准确的地方（本轮已纠正）
1. “Android 只是执行端”——不准确，遗漏了发起/接管/局部自治参与。
2. “系统只是中心-执行端模型”——不准确，忽略了分布式 runtime 证据协同。
3. “completion 即成熟闭环”——不准确，真实代码已拆分 completion 与 mature readiness。

## 7. 本轮重审后仍真实残留的问题与代码收口
### 仍真实存在的问题
- 结果层虽有 readiness gap，但**canonical success 与 fallback/compat/degraded success 缺少硬标签与硬阻断语义**，上层仍可能误读“成功”。

### 本轮已完成的真实收口
- 在 `core/closed_loop_governance_consolidation.py` 增加闭环路径质量硬标签：
  - `canonical_path_used`
  - `fallback_path_used`
  - `compat_path_used`
  - `degraded_path_used`
  - `closure_authority_quality`
  - `mature_closure_blockers`
- 将 `fallback/compat/degraded` 直接纳入成熟闭环 gap：
  - `fallback_path_used`
  - `compat_path_used`
  - `degraded_path_used`
- 回归补强：`tests/test_pr18_system_completion_readiness.py`
  - fallback 语义路径不可判为 mature
  - uplink-only compat 路径显式标记且不可判为 mature

## 8. PR993 与后续 PR（#1102/#1103/#1107/#1108/#1109）的关系
- PR993：系统认知与治理骨架跃迁点（从原型/半闭环表述走向中心分布式系统表述）。
- 后续 PR：在 PR993 骨架上持续做“语义硬化 + 回归补洞 +闭环门禁强化”。
- 本轮定位：在前述基础上继续把“成功语义”做硬区分，避免 fallback/compat/degraded 冒充 canonical mature success。

## 一句话最终结论
**这套双仓系统已经是“中心 authority 明确、Android 具备主动参与能力”的中心分布式系统骨架；本轮进一步把 closure 结果层的 canonical 与 fallback/compat/degraded 成功语义做了硬区分，系统认知与代码门禁口径保持一致。**
