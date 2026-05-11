# 双仓联合认知审查（两层不完整真实情况）

> 审查对象：`DannyFish-11/ufo-galaxy-realization-v2` + `DannyFish-11/ufo-galaxy-android`  
> PR 落仓：`DannyFish-11/ufo-galaxy-realization-v2`  
> 审查原则：仅依据真实代码路径、模块与调用关系；无法严格证明处标注“证据不足”。

---

## 1. 双仓联合审查范围与方法

### 1.1 范围
- V2 仓库（中心侧）：`main.py`、`core/*`、`galaxy_gateway/*`、`tests/integration/*`
- Android 仓库（设备侧）：`app/src/main/java/com/ufo/galaxy/*`（重点看 `network/`、`agent/`、`inference/`、`capability/`）

### 1.2 方法
- 先看入口与职责哨兵（authority sentinel）
- 再看本地链路与跨设备链路的入口、消息、状态、ACK、存储、回放
- 再看测试是否覆盖“跨仓证据回放”
- 仅将“可在代码中定位到的事实”纳入结论

### 1.3 关键证据路径（节选）
- V2：
  - `main.py`
  - `core/system_orchestrator.py`
  - `core/openclawd.py`
  - `core/execution/decision_executor.py`
  - `core/command_router.py`
  - `core/routes/devices.py`
  - `galaxy_gateway/routes/websocket.py`
  - `galaxy_gateway/android_bridge.py`
  - `galaxy_gateway/android/handlers/registration.py`
  - `galaxy_gateway/android/handlers/device_state_snapshot.py`
  - `core/android_device_state_store.py`
  - `core/android_evidence_integration_pipeline.py`
  - `core/canonical_cross_repo_evidence_pipeline.py`
  - `core/unified_governance_semantics.py`
  - `tests/integration/test_pr13a_dual_runtime_cross_repo_regression.py`
- Android：
  - `app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt`
  - `app/src/main/java/com/ufo/galaxy/agent/AutonomousExecutionPipeline.kt`
  - `app/src/main/java/com/ufo/galaxy/agent/DelegatedTakeoverExecutor.kt`
  - `app/src/main/java/com/ufo/galaxy/capability/AndroidCapabilityVector.kt`
  - `app/src/main/java/com/ufo/galaxy/inference/LocalPlannerService.kt`
  - `app/src/main/java/com/ufo/galaxy/inference/LocalGroundingService.kt`

---

## 2. 双仓角色划分

### 2.1 `ufo-galaxy-realization-v2`
- 更接近中心控制面（control plane）。
- 证据：
  - `main.py` + `core/system_orchestrator.py` 明确中心启动权威。
  - `core/api_routes.py`、`core/routes/devices.py` 提供中心设备管理/调度入口。
  - `core/command_router.py`、`core/openclawd.py` 负责本地/跨设备分支与调度骨架。
  - `core/android_evidence_integration_pipeline.py`、`core/canonical_cross_repo_evidence_pipeline.py` 明确中心治理与证据门控。

### 2.2 `ufo-galaxy-android`
- 更接近设备侧 / 执行侧 / 接入侧。
- 证据：
  - `GalaxyWebSocketClient.kt` 负责设备接入、握手、心跳、重连、离线队列回放。
  - `AutonomousExecutionPipeline.kt` 负责 `goal_execution`/`parallel_subtask` 本地执行门控。
  - `DelegatedTakeoverExecutor.kt` 负责 delegated takeover 生命周期 ACK/PROGRESS/RESULT 发射。
  - `AndroidCapabilityVector.kt` 负责设备能力向量与调度元数据导出。

### 2.3 双边共有与单边能力
- 双边都有：协议字段治理、执行状态上报、会话/重连语义、能力门控。
- 主要在 V2：中心编排、统一治理判定、跨仓证据汇聚与审计。
- 主要在 Android：设备运行时执行、设备本地推理接口、设备离线重放。

---

## 3. 总体能力树 / 问题树

| 能力项 | V2 真实实现 | Android 真实实现 | 当前判断 |
|---|---|---|---|
| 中心控制能力 | `main.py`、`core/system_orchestrator.py`、`core/openclawd.py` | 无中心主控 | 已落地（偏强） |
| 分布式设备能力 | `core/routes/devices.py`、`galaxy_gateway/routes/websocket.py` | `GalaxyWebSocketClient.kt`、`AndroidCapabilityVector.kt` | 已落地（中等） |
| 本地链路能力 | `core/execution/decision_executor.py`（Windows本地manifest） | `LocalPlannerService.kt`、`LocalGroundingService.kt` 接口存在 | 半闭环 |
| 跨设备链路能力 | `ws/device/{device_id}` + `android_bridge` + handlers | WebSocket接入、心跳、重连、离线回放 | 半闭环偏强 |
| 协议/消息/状态同步 | `aip_v3.py`、`device_state_snapshot` handler + state_store | `GalaxyWebSocketClient.kt` 上下行消息处理 | 已落地（中等偏强） |
| 任务编排/接管/回退 | `command_router.py`、治理语义模块 | `AutonomousExecutionPipeline.kt`、`DelegatedTakeoverExecutor.kt` | 半闭环 |
| 上下文汇聚与分发 | `unified_governance_semantics.py`、evidence pipeline | 部分字段回传（trace/continuity/policy） | 部分落地 |
| 真实闭环交付能力 | `test_pr13a_dual_runtime_cross_repo_regression.py`（证据回放） | 设备侧执行与信号发射路径存在 | 有闭环样式，但仍不完整 |

---

## 4. 本地链路联合审查（重点）

### 4.1 起点与入口
- V2 本地入口：`core/openclawd.py`（`execution_path=local|hybrid`）→ `core/execution/decision_executor.py`
- Android 本地入口：`AutonomousExecutionPipeline.kt`、`LocalPlannerService.kt`、`LocalGroundingService.kt`

### 4.2 流转关系（真实代码）
- V2：
  - `OpenClawd` 明确 local/cross_device/hybrid 分支。
  - local 分支进入 `DecisionExecutor`，执行受 `enable_system_actions` 与 allowlist 约束。
- Android：
  - `LocalPlannerService` / `LocalGroundingService` 以接口形态存在，但默认 `NoOp*`。
  - `AutonomousExecutionPipeline` 的本地执行前置条件依赖 cross-device runtime gate（`crossDeviceEligibility`）。

### 4.3 是否形成本地闭环
- **V2 本地环（Windows）**：可认为已成形（有分支、有执行器、有策略门控）。
- **Android 纯本地自治链路**：证据显示更多是“接口 + 降级/NoOp兜底”，完整 on-device planner+grounding 生产闭环证据不足。

### 4.4 本地链路结论
- 本地链路完成度：**约 70%（±10%）**
- 当前真实情况：
  - V2 本地 manifest 路径比 Android 纯本地路径更完整。
  - Android 本地推理接口定义完整，但默认实现呈降级/NoOp倾向。
- 关键缺口：
  - Android 本地 planner/grounding 的“默认可用且被主链路稳定消费”的证据不足。
  - 双仓本地链路的一致验收标准未看到统一闭环工件（证据不足）。
- 下一步：
  - 固化 Android 本地推理运行时启停与成功判据，并在 V2 面板侧可观测。
  - 增加双仓本地链路真实设备 E2E 证据产物（非仅 mock/replay）。

---

## 5. 跨设备链路联合审查（重点）

### 5.1 双仓对应模块
- V2：
  - `galaxy_gateway/routes/websocket.py`：`/ws/device/{device_id}` 被声明为 canonical ingress。
  - `galaxy_gateway/android_bridge.py`：Android 消息翻译与桥接。
  - `galaxy_gateway/android/handlers/registration.py`：注册与重连连续性处理。
  - `galaxy_gateway/android/handlers/device_state_snapshot.py`：snapshot/event 吸收并 ACK。
  - `core/android_device_state_store.py`：设备侧状态在 V2 的规范存储。
- Android：
  - `GalaxyWebSocketClient.kt`：connect/heartbeat/reconnect/offline replay、上下行消息处理。
  - `DelegatedTakeoverExecutor.kt`：接管执行 ACK/PROGRESS/RESULT 生命周期信号。
  - `AutonomousExecutionPipeline.kt`：`goal_execution` / `parallel_subtask` 执行门控与回包。

### 5.2 会话、状态同步、上下文迁移、任务接管
- 会话/重连：双方均有明确逻辑（V2 registration handler + Android reconnect/backoff）。
- 状态同步：`device_state_snapshot` 与 `device_execution_event` 已有吸收与 ACK 链路。
- 任务接管：Android 侧有 delegated takeover 执行器，V2 侧有治理语义与审计模块接收面。
- 上下文迁移：有 `session_migrate`、continuity 字段与相关注释/字段，但“跨设备迁移成功判据的端到端强证明”仍偏弱（证据不足）。

### 5.3 跨设备链路结论
- 跨设备链路完成度：**约 58%（±12%）**
- 当前真实情况：**半闭环偏强**（协议与通路完整度较高，端到端“真实持续闭环”证据仍不足）。
- 关键缺口：
  - 真实设备、多阶段迁移/接管/回退的持续回归证据仍不足。
  - 一些路径仍保留 compat/legacy 面，主链路与兼容链路并存带来治理复杂度。
- 下一步：
  - 以 `/ws/device/{device_id}` 为唯一生产口径，压缩兼容路径。
  - 固化跨设备会话迁移 + takeover + recovery 的统一验收工件与阈值。

---

## 6. “两层不完整真实情况”的联合认知判断

### 6.1 为什么是“真实但不完整”
- “真实”：双仓都存在大量可执行代码与测试路径，不是纯 README 架构图。
- “不完整”：多处仍表现为“规范/门控/适配已到位，但最终生产级闭环证据不连续”。

### 6.2 两层定义（基于代码）
1. **中心治理层不完整（V2 侧）**  
   - 已有治理管线与证据汇聚（`android_evidence_integration_pipeline.py`、`canonical_cross_repo_evidence_pipeline.py`），但仍依赖多层兼容与降级路径并存。
2. **设备执行层不完整（Android 侧）**  
   - 已有接入、接管、信号发射与本地推理接口，但本地推理默认实现和跨设备连续交付证据仍非“稳态全闭环”。

### 6.3 叠加影响
- 两层叠加导致系统当前更像“**已形成中心+设备结构的半闭环体系**”，而非“可稳定宣称全链路闭环交付”的成熟态。

---

## 7. 中心分布式智能体语义成立度判断

- 判断：**“已成立但不完整”**（不是仅概念拼接，也未到完全闭环）
- 依据：
  - 中心职责真实存在：启动编排、路由、治理、审计、证据门控。
  - 设备职责真实存在：接入、执行、信号、重连、离线回放。
  - 但跨设备持续交付的统一验收闭环证据仍不足，且兼容路径并存。
- 语义成立度：**约 60%（±10%）**

---

## 8. 双仓真实代码闭环交付矩阵

| 能力项 | V2 侧关键模块 | Android 侧关键模块 | 真实实现 | 调用闭环 | 状态闭环 | 本地链路 | 跨设备链路 | 当前判断 | 风险/缺口 |
|---|---|---|---|---|---|---|---|---|---|
| 设备接入 | `routes/websocket.py`、`android_bridge.py` | `GalaxyWebSocketClient.kt` | 是 | 是 | 中 | 低 | 高 | 半闭环偏强 | 兼容路径并存 |
| 设备注册/心跳 | `handlers/registration.py` | `GalaxyWebSocketClient.kt` | 是 | 是 | 中 | 低 | 高 | 可用 | 连续性验收需加强 |
| 状态快照吸收 | `handlers/device_state_snapshot.py`、`android_device_state_store.py` | `GalaxyWebSocketClient.kt` 上报 | 是 | 是 | 是 | 低 | 中高 | 可观测性较好 | 真实设备长稳态证据不足 |
| 中心治理门控 | `android_evidence_integration_pipeline.py`、`unified_governance_semantics.py` | 提供输入证据 | 是 | 中 | 中高 | 中 | 中 | 已落地 | 仍有降级/兼容复杂度 |
| 跨仓证据汇聚 | `canonical_cross_repo_evidence_pipeline.py` | 证据源输入 | 是 | 中 | 中 | 低 | 中 | 已成形 | 依赖证据新鲜度与质量 |
| 本地执行 | `openclawd.py`、`decision_executor.py` | `LocalPlannerService.kt`、`LocalGroundingService.kt` | 部分 | 中 | 低中 | 中高 | 低 | 半实现 | Android 本地默认能力不足 |
| 接管执行信号 | 治理语义/审计接收面 | `DelegatedTakeoverExecutor.kt` | 是 | 中 | 中 | 低 | 中高 | 半闭环 | 端到端稳定回归证据仍不足 |

---

## 9. 完成度结论（联合视角）

> 说明：本节数值是对第 4/5/7 节完成度判断的统一汇总复述，保持同一口径。

- 双仓整体完成度：**约 62%（±10%）**
- 本地链路完成度：**约 70%（±10%）**
- 跨设备链路完成度：**约 58%（±12%）**
- 中心分布式智能体语义成立度：**约 60%（±10%）**

### 判断依据（简述）
- 加分项：中心编排/路由/治理、设备接入/执行/回放均有真实代码与部分跨仓回放测试。
- 扣分项：兼容路径并存、本地 Android 生产可用闭环证据不足、跨设备迁移/接管/恢复的稳定验收闭环不足。

---

## 10. 下一步必须做的事（P0 / P1 / P2）

### P0（不做就不能称为真实闭环）
1. **双仓统一“跨设备闭环验收工件”**：固定真实设备场景下的 register→dispatch→execution_event→result→audit 证据链。
2. **收敛主链路**：强制以 `/ws/device/{device_id}` 为生产唯一入口，兼容路径仅保留受控窗口。
3. **会话迁移/接管最终判据统一**：V2 与 Android 对 continuity/takeover/recovery 的成功条件字段对齐并自动校验。

### P1（影响体系成立质量）
1. **Android 本地推理默认可用性提升**：减少 NoOp/纯降级路径在生产默认链路中的占比。
2. **V2 治理可观测统一面板**：把证据质量、降级原因、闭环状态做统一聚合视图。
3. **跨仓状态字典对齐**：统一 phase/status/reason 枚举，降低“语义同名异值”风险。

### P2（增强项）
1. 增加跨设备长稳态压测与恢复演练。
2. 增加多设备并发场景下的冲突裁决可视化。
3. 对历史兼容字段做淘汰计划并给出版本窗口。

---

## 证据不足声明（明确列出）

- Android 本地 planner/grounding 在真实设备上长期稳定执行的证据：**证据不足**（本次仅看到接口与降级实现，不足以证明生产稳态）。
- 双仓“跨设备迁移 + 接管 + 回退”在真实网络抖动条件下的持续闭环证明：**证据不足**（现有更多是代码能力与回放类证据）。
