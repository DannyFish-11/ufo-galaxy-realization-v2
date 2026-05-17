# 双仓主链、未一体化能力与重复建设风险正式认知总基线（V2 + Android，中文）

> 审查对象：
> - `DannyFish-11/ufo-galaxy-realization-v2`
> - `DannyFish-11/ufo-galaxy-android`
>
> 证据边界：本基线只使用真实代码入口、真实运行链、真实协议链、真实观察面与真实控制面作为证据；旧文档、旧审计、旧 PR 描述、命名想象均不作为证据。

---

## 0. 本次 PR 的正式结论

1. **Galaxy 仍然必须被认知为“中心分布式 AI 系统”，不能退回成“普通多客户端产品”。**
2. **`ufo-galaxy-realization-v2` 仍然是中心治理核**：`core/canonical_execution_chain.py`、`core/openclawd.py`、`core/command_router.py`、`galaxy_gateway/device_router.py`、`core/runtime/source_dispatch_orchestrator.py`、`core/unified_result_ingress.py`、`core/task_result_canonical_truth_chain.py`、`core/operator_surface.py`、`core/routes/operator.py`、`core/routes/projection.py` 共同构成当前中心治理主链。
3. **Android / 桌面 / 其他设备都不是普通客户端**。Android 通过 `app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt`、`app/src/main/java/com/ufo/galaxy/service/GalaxyConnectionService.kt`、`app/src/main/java/com/ufo/galaxy/agent/AutonomousExecutionPipeline.kt`、`app/src/main/java/com/ufo/galaxy/runtime/LocalExecutionModeGate.kt`、`app/src/main/java/com/ufo/galaxy/runtime/RuntimeController.kt` 成为强运行时节点；桌面通过 `core/desktop_presence_runtime.py`、`windows_client/status_board_v2/device_surface.py`、`static/operator-console/index.html`、`desktop_projection/*.py` 成为显现载体与观察承接面。
4. **真主链必须拆成两条并存的一体系统链**：
   - **本地链路主链**：`DesktopPresenceRuntime` / Android `LocalExecutionModeGate.kt` + `RuntimeController.kt` + `AutonomousExecutionPipeline.kt`
   - **跨设备链路主链**：`/ws/device/{device_id}` → registration / participation → `OpenClawd` / `CommandRouter` / `DeviceRouter` → Android 运行时消费 → `UnifiedResultIngress` → `task_result_canonical_truth_chain`
5. **三态唯一权威实现仍然是 `core/desktop_presence_runtime.py::TriState`**，正式中文命名只采用：
   - 静态
   - 阈限态
   - 显现态
6. 其他近似状态源必须继续降格：
   - `core/current_state_backbone_audit.py::ClosureState(established/partial/open)` = **工程闭合态**
   - `core/openclawd.py` 中 `tri_state_phase` = **内部协议态**
   - `system_integration/state_machine_ui_integration.py::DORMANT/ISLAND/SIDESHEET/FULLAGENT` = **壳层 UI 状态**
   - `core/v2_unified_mode_model.py`、`core/v2_unified_state_contract.py`、`core/unified_panel_aggregation.py` 等 = **近似态 / 派生态 / 读侧聚合态**
7. **这次基线的新增重点不是再说“系统是什么”，而是把后续最容易重复造轮子的区域先画清**：哪些是真主链，哪些只是 overlay / fallback / 可选层，哪些能力已经存在但还没真正吸纳进统一主链，哪些修复若不先统一认知会导致重复建设。

---

## 1. 层次 1：系统本体与双仓主链到底是什么

### 1.1 为什么这是真正的中心分布式 AI 系统

`core/canonical_execution_chain.py` 已经把当前单一权威执行链写明为：

`route ingress → core/routes/* → core/openclawd.py → core/command_router.py → galaxy_gateway/device_router.py → device execution`

这意味着 V2 不是普通后端 API 容器，而是掌握以下中心能力的**治理核**：

- 主体认知与执行分支：`core/openclawd.py`
- 每请求权威链定义：`core/canonical_execution_chain.py`
- 源侧调度：`core/runtime/source_dispatch_orchestrator.py`
- 任务路由与 ACL / 生命周期治理：`core/command_router.py`
- 设备 transport / session dispatch：`galaxy_gateway/device_router.py`
- 设备 ingress / registration / participation：`galaxy_gateway/routes/websocket.py`、`galaxy_gateway/android/handlers/registration.py`
- 配置与启动治理：`core/unified_config.py`、`main.py`、`unified_launcher.py`、`core/system_orchestrator.py`
- 结果入口与真值链：`core/unified_result_ingress.py`、`core/task_result_canonical_truth_chain.py`
- operator / control plane / runtime truth：`core/operator_surface.py`、`core/routes/operator.py`、`core/routes/projection.py`

这不是“PC + Android 客户端访问同一个普通后端”的结构，而是**中心治理核 + 分布式执行/感知/显现网络**。

### 1.2 为什么不能退回成普通多客户端产品

如果退回到普通多客户端框架，以下真实代码事实会被抹掉：

1. `core/openclawd.py` 明确是 unified subject core，而不是普通接口层。
2. `core/desktop_presence_runtime.py` 和 `core/openclawd.py` 明确是同一主体的 shell + core，而不是两个平级应用。
3. `galaxy_gateway/routes/websocket.py` 与 `galaxy_gateway/android/handlers/registration.py` 把 Android 纳入 canonical ingress、identity、registration、participation 治理链。
4. `core/unified_result_ingress.py` + `core/task_result_canonical_truth_chain.py` 说明结果不是客户端自说自话，而必须回到中心真值链。
5. `core/operator_surface.py`、`core/routes/projection.py`、`windows_client/status_board_v2/device_surface.py` 说明桌面消费的是中心编译后的 runtime truth / projection，而不是客户端各自拼装真相。

因此，这套系统**不能把它退回成“PC + Android 客户端”的普通多客户端产品认知**。

### 1.3 为什么 V2 是中心治理核

V2 当前的真实中心权威可以直接按模块落点表述：

| 中心能力 | 代码锚点 | 判断 |
| --- | --- | --- |
| 每请求主链权威 | `core/canonical_execution_chain.py` | 真主链定义 |
| 主体认知核 | `core/openclawd.py` | 真主链 |
| 调度 / 分派决策 | `core/runtime/source_dispatch_orchestrator.py` | 真主链 |
| 路由 / 任务生命周期 | `core/command_router.py` | 真主链 |
| 设备 dispatch / transport session | `galaxy_gateway/device_router.py` | 真主链 |
| ingress / registration / participation | `galaxy_gateway/routes/websocket.py`、`galaxy_gateway/android/handlers/registration.py` | 真主链 |
| 配置 / 启动治理 | `core/unified_config.py`、`core/system_orchestrator.py` | 真主链 |
| 结果入口 / 真值链 | `core/unified_result_ingress.py`、`core/task_result_canonical_truth_chain.py` | 真主链 |
| operator 聚合 / 投影观察面 | `core/operator_surface.py`、`core/routes/operator.py`、`core/routes/projection.py` | 真主链 |

### 1.4 为什么 Android / 桌面 / 其他设备不是普通客户端

- **Android**：`GalaxyWebSocketClient.kt`、`GalaxyConnectionService.kt`、`AutonomousExecutionPipeline.kt`、`LocalExecutionModeGate.kt`、`RuntimeController.kt` 显示其具备持久 uplink、本地执行、中心委托执行、模式门控、continuity / takeover / degraded recovery，因此是**执行面 / 感知面 / 被委托运行时节点**。
- **桌面**：`core/desktop_presence_runtime.py`、`windows_client/status_board_v2/device_surface.py`、`static/operator-console/index.html`、`desktop_projection/liminal_space_engine.py`、`desktop_projection/manifest_stage_controller.py` 显示桌面是**显现面 / operator 观察面 / 控制承接面**，但还不是完整产品壳。
- **其他设备 / 平板**：当前主要通过 UDM / registration / participation 进入治理视角，属于可被中心吸纳的运行时节点，不只是普通被动终端。

### 1.5 本地链路和跨设备链路如何并存

#### 本地链路主链

- Windows：`core/desktop_presence_runtime.py` → `core/openclawd.py` → `core/execution/decision_executor.py`
- Android：`LocalExecutionModeGate.kt` → `RuntimeController.kt` → `AutonomousExecutionPipeline.kt` / `LocalLoopExecutor.kt`

结论：本地链路不是“降级兜底幻觉”，而是**一条真实一级链路**。

#### 跨设备链路主链

`galaxy_gateway/routes/websocket.py:/ws/device/{device_id}`  
→ `galaxy_gateway/android/handlers/registration.py`  
→ `core/openclawd.py` / `core/runtime/source_dispatch_orchestrator.py` / `core/command_router.py` / `galaxy_gateway/device_router.py`  
→ Android `GalaxyConnectionService.kt` / `AutonomousExecutionPipeline.kt`  
→ `core/unified_result_ingress.py`  
→ `core/task_result_canonical_truth_chain.py`  
→ `core/routes/projection.py` / `core/operator_surface.py` / `windows_client/status_board_v2/device_surface.py`

结论：跨设备链路也已经是**真实主链**。

### 1.6 多设备协作链路在真实代码里的位置

多设备协作目前不是“默认唯一主链”，而是在主链之上再叠加的编排层：

- `core/swarm_coordinator.py`：位于 `OpenClawd` 上方、`CommandRouter` 之上的 orchestration layer
- `core/unified_orchestration_spine.py`：明确只治理 multi-step / multi-device / delegated / handoff / takeover / hybrid session，不是 universal per-request gate
- `core/mesh_coordinator.py`：overlay / enrichment path，不是 orchestration authority

因此，多设备协作处于**已存在但尚未成为默认统一主链的编排层**。

---

## 2. 层次 2：全仓结构到底怎么分

### 2.1 结构分层总表

| 主题 | 核心入口 | 主要消费者 | 当前地位 |
| --- | --- | --- | --- |
| 状态模型 | `core/desktop_presence_runtime.py`、`core/openclawd.py`、`core/v2_unified_state_contract.py`、`core/current_state_backbone_audit.py` | projection / board / operator / tests | 只有 `TriState` 是主体权威，其余多为内部协议态、工程闭合态或读侧聚合态 |
| 三态 / 阶段 / 层级 / 闭合度 | `TriState`、`tri_state_phase`、`ClosureState`、`SystemState(DORMANT/ISLAND/SIDESHEET/FULLAGENT)`、`core/v2_unified_mode_model.py` | desktop / operator / audit / mode aggregation | 多套并存，必须严格分级 |
| 执行策略 | `core/openclawd.py`、`core/runtime/source_dispatch_orchestrator.py`、`core/command_router.py` | route / dispatch / delegated runtime | 主链存在，但统一计划层未闭合 |
| 任务链 | `core/canonical_execution_chain.py`、`core/task_result_canonical_truth_chain.py` | command router、device router、result ingress | 真主链 |
| 路由 / 调度 / dispatch | `core/runtime/source_dispatch_orchestrator.py`、`core/command_router.py`、`galaxy_gateway/device_router.py` | OpenClawd / gateway / Android | 真主链 |
| 设备接入 / registration / participation | `galaxy_gateway/routes/websocket.py`、`galaxy_gateway/android/handlers/registration.py`、`core/unified/device_manager.py` | gateway / projection / readiness / operator | 真主链，旁边仍有 compat 层 |
| WebSocket / Mesh / relay / NATS | `galaxy_gateway/routes/websocket.py`、`core/transport_hierarchy.py`、`core/mesh_coordinator.py`、`core/nats_bus.py` | device router / mesh / worker domain | WS 主链；Mesh overlay；relay fallback；NATS 可选层 |
| 结果链 / 真值链 / 验收链 | `core/unified_result_ingress.py`、`core/task_result_canonical_truth_chain.py`、`core/routes/projection.py` | projection / operator / acceptance | 主链已形成，验收统一仍需加固 |
| projection / operator / status board | `core/operator_surface.py`、`core/routes/operator.py`、`core/routes/projection.py`、`core/unified_panel_aggregation.py`、`windows_client/status_board_v2/device_surface.py` | operator-console / board / desktop | 消费面丰富，但仍存在多聚合层并存 |
| desktop shell | `core/desktop_presence_runtime.py`、`desktop_projection/*.py`、`static/operator-console/index.html` | Windows 壳 / board / projection | 有显现骨架，但未成完整产品壳 |
| 多模态 | `core/multimodal/ingress_bus.py`、`core/perception/multimodal_bus.py` | Desktop shell / OpenClawd | 已有碎片能力，未完全统一成单一状态真相 |
| Android bridge / uplink | `galaxy_gateway/android_bridge.py`、`GalaxyWebSocketClient.kt`、`GalaxyConnectionService.kt` | gateway / Android runtime | 主链的一部分 |
| 配置系统 | `core/unified_config.py`、`core/system_orchestrator.py` | main / launcher / subsystems | 中心治理侧 |
| 治理 / 控制面 | `core/operator_surface.py`、`core/routes/operator.py`、`static/operator-console/index.html` | operator / board / projection | 已成观察面，但控制闭环不完整 |
| 测试 / 验收 / integration / e2e | `tests/`、`tests/integration/`、`tests/chaos/` | regression / audit / acceptance | 覆盖面广，但活体验证与统一回归门仍需强化 |

### 2.2 真主链、旁路、遗留、半成品、弱连接的判定

#### 真主链

- `core/canonical_execution_chain.py`
- `core/openclawd.py`
- `core/runtime/source_dispatch_orchestrator.py`
- `core/command_router.py`
- `galaxy_gateway/device_router.py`
- `galaxy_gateway/routes/websocket.py`
- `galaxy_gateway/android/handlers/registration.py`
- `core/unified_result_ingress.py`
- `core/task_result_canonical_truth_chain.py`
- `core/operator_surface.py`
- `core/routes/projection.py`

#### 明确被降级为 compat / helper / side-path 的路径

`core/canonical_execution_chain.py` 已显式降级以下模块：

- `core/e2e_orchestrator.py`
- `core/local_execution_chain.py`
- `core/cross_device_execution_chain.py`
- `core/hybrid_executor.py`
- `core/remote_execution_mode_resolver.py`
- `core/repo_coordinator.py`
- `galaxy_gateway/agent_bridge.py`
- `galaxy_gateway/task_router.py`
- `galaxy_gateway/cross_device_coordinator.py`

#### overlay / fallback / 可选层

- `core/mesh_coordinator.py` = overlay
- relay / ws fallback = fallback
- `core/nats_bus.py` + `core/master_brain.py` = worker-domain optional path，不是 Android ↔ V2 默认主链

#### 已被认知 PR 提到但仍未被统一消费的层

- `core/unified_orchestration_spine.py`：多步编排治理，但不是 per-request gate
- `core/unified_panel_aggregation.py`：统一 panel 聚合，但下游消费仍有并行 surface
- `core/current_state_backbone_audit.py`：审计 / board 读侧骨架，不是主体状态写权威
- Android `LocalExecutionModeGate.kt` / `RuntimeController.kt`：状态对称性在 `core/v2_unified_state_contract.py` 中仍被明示为“不保证仅靠 V2 即完成”

---

## 3. 层次 3：哪些能力已经存在，但没真正一体化

本节只给主文摘要；完整清单见：

- `audit/FORMAL_DUAL_REPO_UNINTEGRATED_CAPABILITIES_APPENDIX_CN_2026.md`

### 3.1 已存在但未完全进入统一主链的关键能力

1. **多步编排治理能力已存在，但未统一覆盖全部执行入口**
   - 代码：`core/unified_orchestration_spine.py`、`core/swarm_coordinator.py`
   - 现状：前者治理 multi-step session，后者治理 multi-device orchestration；普通 per-request 仍走 `OpenClawd → CommandRouter`
   - 风险：后续若不先统一边界，极易再造“新的统一调度器”

2. **Android 上行状态能力已存在，但 V2 仍未完全吸收成单一对称真相**
   - 代码：`LocalExecutionModeGate.kt`、`RuntimeController.kt`、`GalaxyConnectionService.kt`、`core/v2_unified_state_contract.py`
   - 现状：Android 自身对 execution mode、continuity、takeover、degraded/recovered 已有强语义；V2 读侧仍显式声明 “Android symmetry is not yet guaranteed by V2 alone”
   - 风险：后续修复 Android/V2 状态时容易再造一层 reducer 或新 contract

3. **transport 层已有 direct / relay / mesh / worker-domain 机制，但默认治理策略仍未完全统一**
   - 代码：`core/transport_hierarchy.py`、`core/mesh_coordinator.py`、`core/nats_bus.py`、`core/master_brain.py`、Android `TailscaleAdapter.kt` / WebRTC 相关路径
   - 现状：WS 是当前主链；Mesh 与 direct P2P 存在；NATS / MasterBrain 存在 worker-domain 路径；Android 还有 Tailscale / WebRTC 侧能力
   - 风险：若后续直接做“统一网络层”，很容易忽视当前主链和已有 optional/overlay 语义

4. **桌面 / operator / board / projection 已有多层壳与聚合，但还没收束成单一产品壳**
   - 代码：`core/operator_surface.py`、`core/unified_panel_aggregation.py`、`core/routes/projection.py`、`windows_client/status_board_v2/device_surface.py`、`desktop_projection/*.py`、`static/operator-console/index.html`
   - 现状：观察面很强，交互壳很散
   - 风险：后续做桌面壳或 operator shell 时容易绕开现有 projection/runtime truth 再造一层 UI 状态

5. **多模态能力已存在双路径，但没有单一统一吸纳面**
   - 代码：`core/multimodal/ingress_bus.py`、`core/perception/multimodal_bus.py`
   - 现状：一个是 continuous host perception，一个是 request-bound fusion
   - 风险：后续做“统一多模态状态”时极易再次平行实现

### 3.2 为什么这些能力现在还没真正一体化

共同原因是：**写路径权威已经部分形成，但读路径、聚合路径、补充协议层、可视化层还存在多个并行语义面**。  
因此，问题不是“能力不存在”，而是“能力已经存在，但未完全吸入统一主链”。

---

## 4. 层次 4：哪些地方最容易重复造轮子

本节只给主文摘要；完整清单见：

- `audit/FORMAL_DUAL_REPO_DUPLICATE_WHEEL_RISK_APPENDIX_CN_2026.md`

### 4.1 高风险区总表

1. **多套状态表达并存**
   - `TriState`
   - `tri_state_phase`
   - `ClosureState`
   - `SystemState(DORMANT/ISLAND/SIDESHEET/FULLAGENT)`
   - `core/v2_unified_mode_model.py`

2. **多套任务 / 编排 / 执行路径并存**
   - `OpenClawd → CommandRouter → DeviceRouter`
   - `core/unified_orchestration_spine.py`
   - `core/swarm_coordinator.py`
   - `core/master_brain.py`
   - `core/system_orchestrator.py`

3. **多套 operator / board / projection / panel surface 并存**
   - `core/operator_surface.py`
   - `core/unified_panel_aggregation.py`
   - `core/routes/projection.py`
   - `windows_client/status_board_v2/device_surface.py`
   - `static/operator-console/index.html`

4. **多套 device / capability authority 旁路仍在树上**
   - `core/unified/device_manager.py` vs `core/device_registry.py` / `core/device_pool_manager.py` / `core/device_status_api.py`
   - `core/agent/capability_registry.py` + `core/unified/capability_resolver.py` vs `core/capability_manager.py`

5. **Android 相关 ingress / reducer / lifecycle / evidence 文件数量过多**
   - `core/android_*.py` 一整组文件
   - 若不先统一角色边界，后续修 Android 吸收链会继续横向增殖

### 4.2 推荐未来统一落点

- 主体状态唯一权威：`core/desktop_presence_runtime.py::TriState`
- per-request 主链：`core/openclawd.py → core/command_router.py → galaxy_gateway/device_router.py`
- multi-step / multi-device 编排：`core/unified_orchestration_spine.py` 与 `core/swarm_coordinator.py` 需要明确边界，而不是再新增调度层
- 设备写权威：`core/unified/device_manager.py`
- 能力写 / 读权威：`core/agent/capability_registry.py` + `core/unified/capability_resolver.py`
- operator / projection：继续以 `core/operator_surface.py` 和 `core/routes/projection.py` 为统一消费落点

---

## 5. 层次 5：在全部代码层面，这套系统到底还缺什么

这不是抽象“缺什么”列表，而是**已有代码基础之上的真实缺口总表**。

| 结构域 | 当前已有代码 | 还缺什么 | 为什么还没形成统一能力 |
| --- | --- | --- | --- |
| 状态语义 | `TriState`、`tri_state_phase`、`ClosureState`、UI shell state、mode model | 单一状态本体与派生态的硬性消费边界 | 多个状态族都存在，但消费边界未完全锁死 |
| 执行策略 | `OpenClawd`、`SourceDispatchOrchestrator`、`CommandRouter`、`UnifiedOrchestrationSpine`、`SwarmCoordinator` | 单一清晰的“何时谁接管”执行策略图 | per-request / multi-step / worker-domain 并存 |
| 中心智能体 | OpenClawd 核已存在 | 更统一的中心计划层与解释层 | 现状更像“主体核 + 多条策略分支”，不是完整单一 planner |
| 真值链 / 结果链 / 验收链 | `UnifiedResultIngress`、`task_result_canonical_truth_chain`、projection acceptance payload | 更统一的跨路径验收闭环 | 多源结果入口虽已统一，但 acceptance 仍偏聚合层 |
| transport / network layer | WS、relay、mesh、NATS、Android direct path | 默认治理策略统一图 | 多种 transport 已存在，但主链/overlay/optional 仍易被误解 |
| operator / control plane | `operator_surface`、`routes/operator`、`routes/projection` | 故障闭环与操作闭环增强 | 当前仍以 read surface 为主 |
| desktop shell / 产品壳层 | `desktop_presence_runtime`、`desktop_projection/*.py`、`operator-console` | 完整 desktop shell | 壳层能力碎片化，尚未统一承接 runtime truth 与 operator control |
| 多模态 | `MultimodalIngressBus`、`MultimodalBus`、Android multimodal/runtime files | 单一规划-执行-验收闭环 | continuous vs request-bound 双路径尚未统一 |
| Android 一体化吸收 | Android 有强运行时、本地执行、takeover、continuity、on-device inference | 更彻底的 V2 吸收与对称状态消费 | `v2_unified_state_contract.py` 已明确状态对称性未完全保证 |
| 测试 / 回归 / 活体验证 | `tests/`、`tests/integration/`、`tests/chaos/` 很多 | 更少文档式回归、更多真正活链路验证 | 现有测试既有真实链路，也有大量认知/审计文档约束 |
| 未统一能力 | 见未一体化附录 | 吸收入统一主链前的边界冻结 | 若不先冻结认知，后续修复会绕开已有能力 |
| 重复建设风险 | 见重复造轮子附录 | 唯一权威落点图 | 当前树上并存实现过多 |

---

## 6. 三态要求：全仓状态模型全集与唯一权威

### 6.1 真实系统级主体三态唯一权威实现

唯一权威实现仍然是：

- `core/desktop_presence_runtime.py::TriState`
- `TriState.SILENT`
- `TriState.LIMINAL`
- `TriState.MANIFEST`

正式中文命名只采用：

- 静态
- 阈限态
- 显现态

### 6.2 Android 侧是否有对等实现

Android 有强对应能力，但**不是主体三态的对等权威实现**：

- `LocalExecutionModeGate.kt` 负责 Android execution mode state/transitions
- `RuntimeController.kt` 负责 Android 运行姿态 / continuity / takeover failure / degraded recovery

它们是 Android 运行时状态权威，不是系统主体三态权威。

### 6.3 全仓其他类似状态模型的分级

| 状态源 | 代码锚点 | 必须定性 |
| --- | --- | --- |
| `TriState(SILENT/LIMINAL/MANIFEST)` | `core/desktop_presence_runtime.py` | **主体三态唯一权威** |
| `tri_state_phase` | `core/openclawd.py` | **内部协议态** |
| `ClosureState(established/partial/open)` | `core/current_state_backbone_audit.py` | **工程闭合态** |
| `DORMANT / ISLAND / SIDESHEET / FULLAGENT` | `system_integration/state_machine_ui_integration.py` | **壳层 UI 状态** |
| `execution_location / participation_layer / governance_state` | `core/v2_unified_mode_model.py` | **运行模式聚合态** |
| `V2UnifiedStateContract` / `UnifiedPanelPayload` / `foundational_system_truth` | `core/v2_unified_state_contract.py`、`core/unified_panel_aggregation.py`、`core/routes/projection.py` | **读侧聚合态 / 近似态 / 派生态** |

结论：**不能再把这些状态包装成新的“正式三态”。**

---

## 7. 双仓主链 / 旁路 / 弱连接 / overlay / fallback

### 7.1 真主链

#### 本地链路主链

- Windows：`DesktopPresenceRuntime.handle_request()` → `OpenClawd.process()` → local execution
- Android：`LocalExecutionModeGate.kt` → `RuntimeController.kt` → `AutonomousExecutionPipeline.kt` / `LocalLoopExecutor.kt`

#### 跨设备链路主链

- `galaxy_gateway/routes/websocket.py`
- `galaxy_gateway/android/handlers/registration.py`
- `core/openclawd.py`
- `core/runtime/source_dispatch_orchestrator.py`
- `core/command_router.py`
- `galaxy_gateway/device_router.py`
- Android `GalaxyConnectionService.kt` / `AutonomousExecutionPipeline.kt`
- `core/unified_result_ingress.py`
- `core/task_result_canonical_truth_chain.py`
- `core/routes/projection.py`

### 7.2 次级链 / 弱连接 / overlay / fallback / 可选层

| 类型 | 代码锚点 | 正式判断 |
| --- | --- | --- |
| Mesh | `core/mesh_coordinator.py` | overlay；不是默认 orchestration authority |
| relay | `core/mesh_coordinator.py`、gateway relay path | fallback |
| ws fallback | `core/mesh_coordinator.py` / hybrid transport path | fallback |
| NATS | `core/nats_bus.py`、`core/master_brain.py` | worker-domain 可选层，不是 Android ↔ V2 默认主链 |
| WebRTC / Tailscale / Android direct path | Android `WebRTC*` / `TailscaleAdapter.kt` | 存在但未吸入 V2 默认治理主链 |

必须避免再产生以下误解：

- 有 mesh 代码 ≠ mesh 已成熟闭环
- 有 NATS / MasterBrain ≠ NATS 已成为双仓默认主链
- 有桌面壳 / projection / board 代码 ≠ 已经完成统一 desktop shell
- 有 `android_*` 吸收模块 ≠ Android 状态已经被 V2 完整对称吸收

---

## 8. 主文档与附录的非回退约束

### 8.1 主文档必须持续覆盖

1. 系统本体
2. 双仓主链 / 旁路 / 弱连接
3. 三态唯一权威
4. 未一体化能力
5. 重复造轮子风险
6. 全系统真实问题总表

### 8.2 附录必须存在并被主文引用

- 未一体化能力附录：`audit/FORMAL_DUAL_REPO_UNINTEGRATED_CAPABILITIES_APPENDIX_CN_2026.md`
- 重复造轮子风险附录：`audit/FORMAL_DUAL_REPO_DUPLICATE_WHEEL_RISK_APPENDIX_CN_2026.md`

### 8.3 不回退约束

本 PR 合并后，后续认知与修复不得回退成以下错误做法：

1. 把系统降回“普通多客户端产品”。
2. 只讲主链，不讲未一体化能力。
3. 只讲缺口，不讲已有重复实现。
4. 只讲认知，不讲具体代码落点。
5. 把 Mesh / NATS / MasterBrain 重新包装成 Android ↔ V2 默认主链。
6. 把 `ClosureState`、`tri_state_phase`、`DORMANT/ISLAND/SIDESHEET/FULLAGENT` 重新包装成主体三态。
7. 在修复前绕开 `OpenClawd → CommandRouter → DeviceRouter`、`UnifiedResultIngress`、`task_result_canonical_truth_chain`、`OperatorSurface / Projection` 等既有主链重新造轮子。

---

## 9. 最终正式表述

> **Galaxy 双仓系统的当前真实本体，仍然只能被认知为“以 V2 为中心治理核、以 Android / 桌面 / 其他设备为执行面 / 感知面 / 显现面 / 控制承接面的中心分布式 AI 系统”。**
>
> **本地链路主链与跨设备链路主链同时存在；WS 是当前双仓主链，Mesh 是 overlay，relay / ws fallback 是 fallback，NATS / MasterBrain 是可选 worker-domain 路径。**
>
> **系统主体三态唯一权威仍然是 `core/desktop_presence_runtime.py::TriState`；其他状态族只能被降格为内部协议态、工程闭合态、壳层态或派生态。**
>
> **后续修复若不先统一“真主链 / 未一体化能力 / 重复造轮子风险”三张图，就极易绕开现有能力再次重复建设。**
