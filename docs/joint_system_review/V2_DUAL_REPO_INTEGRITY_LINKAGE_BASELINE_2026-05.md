# 收敛 V2 双仓完整性联动与全系统认知基线（基于真实代码）

> 目标仓：`DannyFish-11/ufo-galaxy-realization-v2`
>
> 联动仓：`DannyFish-11/ufo-galaxy-android`
>
> 机器基线：`core/complete_joint_system_review.py` + `tests/test_complete_joint_system_review.py`
>
> 补充重审：`core/post_closure_dual_repo_reassessment.py` + `tests/test_post_closure_dual_repo_reassessment.py`

## 1. 这到底是一个什么系统

它不是单仓系统，也不是“主程序 + Android 客户端”的简单模型。

按当前真实代码，**它更准确是一个以 V2 为中心治理核、以 Android 为参与执行节点、以统一结果真值与状态投影为收口面的双仓分布式智能系统**：

- **V2** 持有统一入口、执行路径判定、路由/编排、结果真值吸收、治理投影、operator/board/readiness 可见面。
- **Android** 持有设备侧运行时、委托执行、接管执行、本地能力与 continuity identity，并通过 WebSocket 与契约把参与真相回送给 V2。

对应代码锚点：

- V2：`core/unified/entrypoint_router.py`、`core/routes/chat.py`、`core/runtime/source_dispatch_orchestrator.py`、`core/unified_result_ingress.py`
- Android：`app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt`、`app/src/main/java/com/ufo/galaxy/agent/AutonomousExecutionPipeline.kt`

## 2. V2 与 Android 在系统里的真实职责

### V2 真实承担的职责

- 统一首跳与入口治理：`core/unified/entrypoint_router.py`
- 中心执行壳与主认知核承接：`core/routes/chat.py` → `core/desktop_presence_runtime.py` → `core/openclawd.py`
- 路由/编排/分发判定：`core/runtime/source_dispatch_orchestrator.py`、`galaxy_gateway/routing/device_selection.py`
- Android 参与真相消费：`core/android_device_state_store.py`
- 结果 canonical ingestion / closure / memory backflow：`core/unified_result_ingress.py`
- operator / panel / readiness / state contract 投影：`core/unified_panel_aggregation.py`、`core/operator_surface.py`、`core/operational_readiness_surface.py`、`core/v2_unified_state_contract.py`

### Android 真实承担的职责

- 设备侧 transport 与 runtime participation：`GalaxyWebSocketClient.kt`
- 本地自主/委托执行：`AutonomousExecutionPipeline.kt`
- mesh participation 边界与克制表达：`AndroidMeshParticipationContract.kt`
- durable participant identity / continuity：`DurableParticipantIdentity.kt`

## 3. 用户问题如何进入、流动、分发、执行、回流、收口

| 阶段 | 真实链路 | 关键代码 |
|---|---|---|
| 入口 | 用户问题先进入 V2 的统一首跳，而不是直接落到某个聊天 handler 里 | `core/unified/entrypoint_router.py`, `core/routes/chat.py` |
| 进入中心运行壳 | chat 适配层把请求交给 `DesktopPresenceRuntime`，再进入 `OpenClawd` | `core/desktop_presence_runtime.py`, `core/openclawd.py` |
| 路由/分发 | V2 根据 routing / readiness / session / participation truth 判定本地执行还是 Android 参与 | `core/runtime/source_dispatch_orchestrator.py`, `galaxy_gateway/routing/device_selection.py`, `core/android_device_state_store.py` |
| Android 执行 | Android 通过 WebSocket 接入，并在本地执行 delegated/takeover/autonomous 路径 | `GalaxyWebSocketClient.kt`, `AutonomousExecutionPipeline.kt` |
| 回流 | Android 状态和结果回流到 V2 的 device-state / signal / result ingress canonical 链 | `core/android_execution_signal_reconciler.py`, `core/unified_result_ingress.py` |
| 收口 | V2 依据 evidence / acceptance / completion / panel/operator 投影形成最终系统闭环 | `core/execution_evidence_model.py`, `core/result_truth_acceptance_gate.py`, `core/unified_panel_aggregation.py` |

## 4. 当前系统真实完成度到哪里

按 `build_complete_joint_system_review()` 当前输出：

- **阶段判定**：`mid-stage consolidation`
- **平均完成度**：`72.3%`
- **加权完成度**：`72.8%`

这意味着：

- **已经形成闭环/接近闭环的部分**
  - V2 中心治理核与 operator/panel/readiness 投影面已成形
  - Android → V2 状态与结果的 canonical ingestion path 已存在
  - delegated execution / continuity / participation 已不是空语义
- **仍是半联通、半语义、半投影、半治理的部分**
  - Android truth 已可见，但还没有稳定进入所有编排/分发决策分支
  - mesh participation contract 已成立，但 full mesh runtime 不能夸大为已闭合
  - local inference availability / readiness / fallback 等信号，跨仓统一门控仍不稳
  - continuity 已联动，但跨重启/恢复的运行级证明仍薄

## 5. 当前最关键的双仓矛盾/完整性联动缺口

1. **truth 可见，但不等于 truth 可决策**
   - V2 已消费 `android_snapshot`
   - Android 已持续上送状态
   - 但 V2 并未在所有路由/dispatch 分支里稳定使用这些真值

2. **Android 对 mesh 完成度的表达比 V2 表面更克制**
   - Android contract 明确保留 `partial / deferred`
   - 因此不能把“参与式协作”误写成 “full mesh runtime 已闭环”

3. **能力 / readiness / local inference availability 的统一治理还不够硬**
   - 双侧都已有语义
   - 但尚未形成强制同源的决策门控链

4. **continuity identity 已接通，但跨重启恢复证明仍薄**
   - 字段与单次 reconnect 已联动
   - 但完整恢复链仍不是 fully closed

## 6. 现阶段最值得开的 V2 侧完整性联动工作

最值得收口的，不是再写一份大而化之的架构说明，而是：

**让 Android truth 成为 V2 编排、闭环与治理的正式输入，而不是仅停留在可见面。**

直接落点：

- `core/runtime/source_dispatch_orchestrator.py`
- `galaxy_gateway/routing/device_selection.py`
- `core/unified_result_ingress.py`
- `core/operational_readiness_surface.py`
- `core/unified_panel_aggregation.py`

要达到的结果：

1. Android readiness / participation / continuity / fallback truth 真正驱动 V2 路由与分发
2. result acceptance / closure 显式引用跨仓参与与连续性证据
3. operator / board / readiness 面板能反映真实决策原因，而不是只反映表面状态

## 7. 本基线的约束口径

- 不把 V2 写成整个系统
- 不把 Android 写成被动终端
- 不把 transport 已接通误写成 runtime fully closed
- 不把 panel/operator 投影误写成真实决策链已经完全同源

本文件的作用是给 V2 侧 PR 提供**可直接指导实现的双仓完整性联动基线**，而不是提供新的叙事噪音。
