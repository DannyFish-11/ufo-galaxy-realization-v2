# 双仓正式认知审查基线（V2 + Android，中文）

> 审查对象：
> - `DannyFish-11/ufo-galaxy-realization-v2`
> - `DannyFish-11/ufo-galaxy-android`
>
> 产物定位: 当前阶段**可直接合并**的正式认知审查基线。
>
> 证据方法：只使用双仓真实代码入口、真实运行链、真实协议链与真实控制/投影面作为证据；旧文档、旧 PR 描述、命名想象均不作为证据。

---

## 0. 审查结论（先给正式判断）

本轮正式认知审查结论如下：

1. **这套系统的真实本体是“中心治理核 + 分布式执行/感知/显现网络”的中心分布式 AI 系统。**
2. **不能把它退回成“PC + Android 客户端”的普通多客户端产品认知。**
3. `ufo-galaxy-realization-v2` 当前掌握中心治理权威：接入、注册、身份/会话、配置读取、路由/调度、任务真值链、operator/control plane、结果汇聚、投影/观察面。
4. Android 不是被动终端，而是**强运行时节点**：具备持久 WS 链路、本地执行流水线、本地执行模式门控、goal/parallel/takeover 消费、离线队列与重连恢复。
5. 当前系统同时存在两条主链：
   - **本地链路主链**
   - **跨设备链路主链**
   两者并存，而不是“本地只是降级兜底”。
6. 三态正式收束只采用：
   - **静态**
   - **阈限态**
   - **显现态**
   其唯一权威实现是 `core/desktop_presence_runtime.py` 中的 `TriState(SILENT/LIMINAL/MANIFEST)`。
7. 其他相近状态源必须严格降格：
   - `core.current_state_backbone_audit.ClosureState(established/partial/open)` = **工程闭合态**
   - `core.continuum.tri_state_phase` = **内部协议态**
   - 其他面板/投影/派生状态 = **近似态**

---

## 1. 系统本体：为什么这是中心分布式 AI 系统，而不是普通多客户端产品

### 1.1 真实代码显示 V2 不是“后端接口盒子”，而是中心治理核

V2 侧不是单纯给多个前端提供 API；它集中掌握以下系统中心能力：

- **接入/网关入口**：`galaxy_gateway/routes/websocket.py`
- **设备注册与身份/附接治理**：`galaxy_gateway/android/handlers/registration.py`
- **路由与任务分发**：`core/command_router.py`、`galaxy_gateway/device_router.py`
- **源侧调度/执行模式选择**：`core/runtime/source_dispatch_orchestrator.py`
- **能力调度与本地/跨设备决策**：`core/capability_orchestrator.py`
- **结果汇聚**：`core/unified_result_ingress.py`
- **任务真值链**：`core/task_result_canonical_truth_chain.py`
- **配置权威读取栈**：`core/unified_config.py`
- **operator/control plane**：`core/operator_surface.py`、`core/routes/operator.py`
- **运行时投影 / 观察面**：`core/routes/projection.py`

这类结构不符合“多个客户端访问同一个普通后端”的产品模型，而符合“中心节点对全系统进行治理、分发、归并与投影”的中心分布式系统模型。

### 1.2 真实代码显示 Android 不是“客户端 UI”，而是被治理的强运行时节点

Android 侧真实代码锚点：

- `app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt`
- `app/src/main/java/com/ufo/galaxy/service/GalaxyConnectionService.kt`
- `app/src/main/java/com/ufo/galaxy/agent/AutonomousExecutionPipeline.kt`
- `app/src/main/java/com/ufo/galaxy/runtime/LocalExecutionModeGate.kt`
- `app/src/main/java/com/ufo/galaxy/runtime/RuntimeController.kt`

这些代码表明 Android 具备：

- 持久 WS 会话、握手、重连、离线队列、重放约束；
- `task_assign` / `goal_execution` / `parallel_subtask` / `takeover_request` 等运行时消息消费；
- 本地执行流水线与本地执行模式门控；
- mesh 参与消息（join/result/leave）；
- 本地状态同步与自治执行姿态控制。

因此 Android 的角色不是“展示客户端”，而是同一 AI 身体网络中的**执行面 + 感知面 + 运行时载体**。

### 1.3 为什么不能退回“PC + Android 客户端”认知

如果把这套系统退回成“PC + Android 客户端”，会直接遮蔽以下真实结构：

1. **V2 掌握会话/身份/附接/注册/路由/真值/投影的中心治理权。**
2. **Android 不是被动视图，而是可以执行、自治、重连恢复、参与并行子任务的运行节点。**
3. **桌面也不只是 UI，它承接 operator/status/projection/desktop presence，是 AI 的一个显现载体。**
4. **系统主链不是单一 UI 请求链，而是中心治理核与多个运行节点之间的分布式编排链。**

因此，正式基线认知必须收束为：

> **中心治理核 + 分布式执行/感知/显现网络**

而不能回退为普通多客户端框架。

---

## 2. 中心权威：V2 当前已经掌握哪些中心治理能力

| 治理能力 | 真实代码锚点 | 当前判断 |
|---|---|---|
| 调度 | `core/runtime/source_dispatch_orchestrator.py`, `core/capability_orchestrator.py` | V2 负责本地/远端/分阶段 dispatch 选择 |
| 路由 | `core/command_router.py`, `galaxy_gateway/device_router.py` | V2 是命令与设备路由中心 |
| 配置 | `core/unified_config.py`, `core.config_store`, `core.config_service` | 配置读取与优先级由中心侧统一掌握 |
| 任务真值 | `core/task_result_canonical_truth_chain.py` | V2 维护 canonical must-run truth chain |
| operator 聚合 | `core/operator_surface.py`, `core/routes/operator.py` | V2 汇聚 operator 可见运行时真相 |
| 设备接入 | `galaxy_gateway/android/handlers/registration.py` | 注册、附接、参与层级、capability assimilation 都在 V2 落地 |
| gateway | `galaxy_gateway/routes/websocket.py` | `/ws/device/{device_id}` 是 canonical ingress |
| 结果汇聚 | `core/unified_result_ingress.py` | Android / delegated / task result 汇入统一入口 |
| 投影 / 观察面 | `core/routes/projection.py`, `windows_client/status_board_v2/device_surface.py` | runtime-truth / desktop-status-board 由 V2 编译并对外暴露 |

### 2.1 调度与路由

`core/runtime/source_dispatch_orchestrator.py` 直接说明自己是 **canonical source-side execution orchestration layer**，负责决定：

- 本地执行
- 远端 handoff
- mesh-aware staged dispatch

`core/command_router.py` 与 `galaxy_gateway/device_router.py` 共同构成中心命令与设备路由主链，因此“任务由中心发起、中心判断、中心派发”是成立的。

### 2.2 配置与启动权威

`core/unified_config.py` 明确写出：

- 自己只是 **compatibility facade**
- 权威配置栈是 `config_schema → config_store → config_service → config_preflight → config_hot_reload`
- `unified_launcher.py` 是 canonical startup orchestration entrypoint

这说明配置权威也在中心侧，而不是散落在各客户端。

### 2.3 任务真值、结果汇聚与操作面

`core/unified_result_ingress.py` 负责统一吸纳结果，并在内部调用四步真值链；  
`core/task_result_canonical_truth_chain.py` 明确 `run_task_result_truth_chain()` 是 canonical must-run truth chain；  
`core/operator_surface.py` 明确自己是 operator 可见 runtime state 的 authoritative convergence point；  
`core/routes/operator.py` 进一步把该 operator surface 暴露为 canonical operator control plane。

这意味着：

- 任务的“完成”不是设备自己说了算；
- 结果要经过中心汇聚与真值处理；
- operator 面看到的系统态也是中心编译后的统一投影。

---

## 3. 设备定位：Android / 桌面 / 平板 / 其他设备到底是什么

### 3.1 Android / 桌面 / 平板 / 其他设备不是“只是客户端”

正式定位如下：

- **Android / 平板 / 其他移动设备**：AI 身体网络中的**执行面 / 感知面 / 被委托运行时节点**
- **桌面**：AI 身体网络中的**显现面 / operator 观察面 / 控制承接面**
- **V2**：系统唯一**中心治理核**

### 3.2 Android 是强运行时节点，而不是被动终端

依据：

- `GalaxyWebSocketClient.kt`：`sendHandshake`、`sendJson`、`scheduleReconnect`、offline queue、cross-device gate
- `GalaxyConnectionService.kt`：处理 `task_assign`、`goal_execution`、`parallel_subtask`、`takeover_request`
- `AutonomousExecutionPipeline.kt`：本地目标执行与并行子任务执行入口
- `LocalExecutionModeGate.kt`：Android 本地执行模式的 single, machine-verifiable authority
- `RuntimeController.kt`：运行时姿态与执行控制

结论：

> Android 是强运行时节点，不是被动终端。

### 3.3 桌面为什么不只是 UI，而是 AI 的显现载体

桌面侧真实锚点：

- `core/desktop_presence_runtime.py`
- `windows_client/status_board_v2/device_surface.py`
- `static/operator-console/index.html`
- `core/routes/projection.py`

其中：

- `core/desktop_presence_runtime.py` 定义了主体三态与显现生命周期；
- `windows_client/status_board_v2/device_surface.py` 明确是 **READ-ONLY surface**，展示设备/执行/参与/基础真值；
- `static/operator-console/index.html` 是操作台壳层；
- `core/routes/projection.py` 负责把中心 runtime truth 编译成桌面可消费载荷。

所以桌面不是普通 UI 客户端，而是同一 AI 身体网络的**显现面与观察承接面**。  
但同时也要诚实：当前桌面壳层仍偏“状态板 + 操作台壳”，尚未成为完整强交互桌面助手。

---

## 4. 链路梳理：本地链路与跨设备链路如何并存

### 4.1 本地链路主链

本地链路主链不是幻觉，真实代码可落为：

1. Android 进入本地执行姿态  
   - `LocalExecutionModeGate.kt`
   - `RuntimeController.kt`
2. Android 消费本地目标/任务  
   - `GalaxyConnectionService.kt`
   - `AutonomousExecutionPipeline.kt`
3. 结果通过 Android 本地执行流水线生成  
4. 必要时再由 `GalaxyWebSocketClient.kt` 上送中心

结论：**本地链路主链真实存在。**

### 4.2 跨设备链路主链

跨设备链路主链可落为：

1. 设备通过 `/ws/device/{device_id}` 接入  
   - `galaxy_gateway/routes/websocket.py`
2. 注册、附接、参与与 capability assimilation  
   - `galaxy_gateway/android/handlers/registration.py`
3. 中心调度与路由  
   - `core/runtime/source_dispatch_orchestrator.py`
   - `core/command_router.py`
   - `galaxy_gateway/device_router.py`
4. Android 运行时消费委托任务  
   - `GalaxyConnectionService.kt`
   - `AutonomousExecutionPipeline.kt`
5. 结果回流到中心  
   - `core/unified_result_ingress.py`
   - `core/task_result_canonical_truth_chain.py`
6. 中心向 operator / status board / projection 输出观察面  
   - `core/routes/projection.py`

结论：**跨设备链路主链也真实存在。**

### 4.3 两条主链如何并存

它们的关系不是“二选一”，而是：

- 本地链路保证单节点独立完成能力；
- 跨设备链路保证中心可治理、可委托、可回流、可投影；
- Android 同时具备本地执行与被中心委托两种运行姿态；
- 中心并不抹掉设备自治，而是对设备自治进行治理、委托与汇聚。

### 4.4 当前闭环判断

- **已形成真实主链**
  - WS 接入
  - 注册与附接
  - 跨设备委托
  - 结果回流
  - runtime-truth / desktop-status-board 投影
- **部分闭环**
  - 多设备并发协作
  - mesh 真实网络下的稳定协同验收
  - 失败恢复与自动重派

---

## 5. 三态认知收束：唯一权威实现与非权威近似态

### 5.1 唯一权威实现

真实三态唯一权威实现：

- 文件：`core/desktop_presence_runtime.py`
- 枚举：`TriState`
- 代码值：
  - `TriState.SILENT`
  - `TriState.LIMINAL`
  - `TriState.MANIFEST`

正式中文收束为：

| 正式中文名 | 代码值 | 权威来源 |
|---|---|---|
| 静态 | `SILENT` | `core/desktop_presence_runtime.py` |
| 阈限态 | `LIMINAL` | `core/desktop_presence_runtime.py` |
| 显现态 | `MANIFEST` | `core/desktop_presence_runtime.py` |

### 5.2 为什么这里必须收束为“显现态”

`MANIFEST` 对应的是主体主动外显、输出、控制与执行显化阶段。  
因此本基线将其正式中文名收束为 **显现态**。此前近义表述（例如“呈现态”）不再作为三态正式命名。

### 5.3 其他相近状态源为何不是真三态

1. `core.current_state_backbone_audit.ClosureState(established/partial/open)`  
   - 作用：链路闭合度判断  
   - 定性：**工程闭合态**

2. `core.continuum.tri_state_phase`  
   - 作用：内部认知/执行相位协议  
   - 定性：**内部协议态**

3. 各类面板字段、投影摘要、设备 lifecycle 衍生态  
   - 作用：运行时局部可见状态  
   - 定性：**近似态**

正式边界：

> 只有 `core/desktop_presence_runtime.py` 的 `TriState` 是这次 PR 的三态唯一权威实现。  
> 其他状态源不得再包装成真正三态。

---

## 6. WS / Mesh / NATS / 多设备结构：主链、overlay、fallback、可选层

### 6.1 WS 在真实系统中的位置

`galaxy_gateway/routes/websocket.py` 已将 `/ws/device/{device_id}` 标成 canonical device ingress。  
`GalaxyWebSocketClient.kt` 负责握手、发送、重连、离线队列回放。

因此：

- **WS = 当前双仓主链**
- 是 V2 ↔ Android 真实运行链的主 transport

### 6.2 Mesh 在真实系统中的位置

`core/mesh_coordinator.py` 明确写出：

- direct WS = primary
- relay = fallback
- ws fallback = fallback path

因此：

- **Mesh = 建立在当前主链之上的协作 overlay**
- 它是多设备协作与直连/中继选择骨架
- 但它不是当前双仓唯一主链

### 6.3 NATS 在真实系统中的位置

`core/nats_bus.py` 明确写出：

- 通过 `GALAXY_NATS_URL` 配置
- 未配置或未安装 `nats-py` 时进入 **no-op mode**

因此：

- **NATS = 可选层**
- 不是当前双仓必须成立的唯一 transport 前提
- 也不是当前 Android ↔ V2 主链

### 6.4 正式分层判断

- **主链**：WS
- **overlay**：Mesh
- **fallback**：Mesh 内 relay / ws fallback
- **可选层**：NATS

---

## 7. Android 本地能力：是否具备真实本地执行链路与本地推理/执行能力

### 7.1 结论

**Android 具备真实本地执行链路。**

### 7.2 代码依据

- `LocalExecutionModeGate.kt`：本地执行模式权威门控
- `RuntimeController.kt`：本地运行姿态与控制
- `AutonomousExecutionPipeline.kt`：goal / parallel 执行流水线
- `GalaxyConnectionService.kt`：任务入口处理与 continuity / governance gate
- `GalaxyWebSocketClient.kt`：结果/事件上送、断线缓存与恢复

### 7.3 Android 与中心治理核的关系

关系不是“中心 = 一切，Android = 被动终端”，而是：

- **中心治理核**：负责接入、身份、参与资格、任务委托、真值链、投影与 operator/control plane
- **Android 运行时节点**：负责本地执行、感知接入、被委托执行、局部自治与事件/结果回传

### 7.4 Android 在什么情况下自治，什么情况下被中心委托

- **自治场景**
  - 本地执行模式成立
  - Android 直接进入本地执行流水线
  - 网络抖动/重连期间仍可持有离线队列与局部运行态

- **中心委托场景**
  - 设备已完成 WS 接入、注册、附接、participation/readiness 条件
  - V2 通过 command/router/orchestrator 选择该设备为执行节点
  - Android 通过 `GalaxyConnectionService.kt` 消费 `task_assign` / `goal_execution` / `parallel_subtask`

结论：

> Android 是可自治、也可被中心委托的强运行时节点。

---

## 8. 当前成熟度：真实主链、部分闭合、弱证据、假闭环、缺失

### 8.1 已形成真实主链的部分

- WS canonical ingress
- 设备注册 / 附接 / 身份与会话连续性
- 中心路由与跨设备委托
- Android 执行消费
- 统一结果汇聚
- task_result canonical truth chain
- runtime-truth / desktop-status-board / operator surface

### 8.2 部分闭合的部分

- 多设备协作分工
- mesh 直连/中继真实运行下的一致验收
- 自动恢复 / 自动重派
- 中心统一计划层
- operator 的完整故障闭环控制能力

### 8.3 弱证据部分

- “多个设备共同完成一个目标”的稳定产品级证据
- 多模态输入统一编排到同一任务计划的强证据
- 中心智能体的统一可解释决策输出

### 8.4 假闭环部分

- 有 mesh / NATS 代码 ≠ 多设备生产级协作已经闭环
- 有 status board / operator-console ≠ 完整桌面壳与运维控制面已经闭环
- 有 coordinator / router ≠ 完整中心智能体已经闭环

### 8.5 缺失部分

- 单一统一计划器
- 统一设备能力语义匹配层
- 多设备并发任务拆分与稳定验收链
- 完整 desktop shell
- 强类型 TypeScript 全栈 operator 主界面
- 多模态统一规划-执行-验收-回流机制

---

## 9. 全系统真实问题（按结构域）

| 结构域 | 当前真实问题 | 关键代码锚点 |
|---|---|---|
| 状态语义 | 三态、工程闭合态、内部协议态仍容易被混用 | `core/desktop_presence_runtime.py`, `core/current_state_backbone_audit.py` |
| 执行策略 | 仍缺统一计划层，很多地方仍以工程分支代替策略 | `core/runtime/source_dispatch_orchestrator.py`, `core/capability_orchestrator.py` |
| 中心智能体 | 已有中心协调基础设施，但完整中心智能体未闭合 | `core/command_router.py`, `core/agent_factory.py`, `core/rag_memory.py` |
| 真值链 / 结果链 / 验收链 | 统一结果入口已形成，但多路径强一致验收仍需继续加固 | `core/unified_result_ingress.py`, `core/task_result_canonical_truth_chain.py` |
| 网络层 / transport | WS 主链成立；mesh 与 relay/fallback 仍需更多真实运行证据；NATS 仍为可选层 | `galaxy_gateway/routes/websocket.py`, `core/mesh_coordinator.py`, `core/nats_bus.py` |
| operator / control plane | operator surface 已成形，但完整故障闭环控制台仍未完成 | `core/operator_surface.py`, `core/routes/operator.py`, `static/operator-console/index.html` |
| 产品壳层 / desktop shell | status board 与 operator-console 还不是完整 desktop shell | `windows_client/status_board_v2/device_surface.py`, `static/operator-console/index.html` |
| 多模态 | 多模态输入输出与统一计划/验收尚未完整闭环 | `core/desktop_presence_runtime.py`, Android 运行时执行与感知代码 |
| 测试 / 回归 / 活体验证 | 双仓联合活体验收与多设备真实网络回归仍需继续强化 | 现有 `tests/` + Android 侧运行链，尚缺更硬的联合活体验证门 |

---

## 10. 本 PR 作为正式基线的硬约束

本 PR 合并后，当前阶段正式认知基线必须保持以下不回退约束：

1. 系统本体必须保持为**中心分布式 AI 系统**。
2. 不得回退成“普通多客户端产品框架”。
3. 必须承认**本地链路**与**跨设备链路**并存。
4. 三态正式命名只采用：
   - 静态
   - 阈限态
   - 显现态
5. 三态唯一权威实现只能指向 `core/desktop_presence_runtime.py::TriState`。
6. `ClosureState`、`tri_state_phase` 及其他近似状态源不得再被包装成真正三态。
7. Android 必须维持“强运行时节点”定位，而不是被动终端定位。
8. 桌面必须维持“显现载体 / 观察承接面”定位，而不是单纯 UI 客户端定位。

---

## 11. 最终正式表述

> **Galaxy 当前真实系统本体不是“PC + Android 客户端”，而是以 V2 为中心治理核、以 Android/桌面/平板等设备为执行面/感知面/交互面/显现面的中心分布式 AI 系统。**
>
> **当前主链已经形成：WS 接入、注册附接、中心路由、Android 执行、结果回流、任务真值链、operator/projection 观察面。**
>
> **当前尚未完全闭合的，是统一计划层、多设备稳定协作验收、完整 desktop shell、强类型全栈 operator 面与统一多模态闭环。**
