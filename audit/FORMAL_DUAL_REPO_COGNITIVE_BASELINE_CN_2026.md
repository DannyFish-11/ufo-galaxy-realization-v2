# 双仓正式认知审查基线（V2 + Android，2026）

> 适用范围：`DannyFish-11/ufo-galaxy-realization-v2` + `DannyFish-11/ufo-galaxy-android`
>
> 证据规则：本基线只以两仓真实代码为证据来源。V2 证据直接来自本仓文件；Android 证据来自 `ufo-galaxy-android` 对应源码文件路径。  
> 不使用旧审计文档、旧 PR 描述、命名想象或目标口号替代代码事实。

---

## 0. 审查结论先行

当前双仓系统的真实本体应定义为：

**中心治理核 + 分布式执行/感知/交互/呈现网络的中心分布式 AI 系统。**

它**不能退回**成“PC + Android 客户端”的普通多客户端产品理解，原因不是命名，而是代码里已经同时存在：

1. **中心治理核**：V2 持有调度、路由、配置、接入、任务真值、结果归并、投影面等中心权威；
2. **本地链路**：Windows 主机可直接作为执行体运行本地任务，而不是只做控制台；
3. **跨设备链路**：V2 通过网关将任务委托给 Android，Android 作为强运行时节点回传结果与真值；
4. **设备网络语义**：Android/桌面/平板/其他节点在代码里是执行面、感知面、交互面、呈现面的可组合载体，而不是统一降级成“被动客户端”。

---

## 1. 系统本体：为什么它是中心分布式 AI 系统

### 1.1 不能退回普通多客户端框架

| 代码事实 | 结论 |
|---|---|
| `core/openclawd.py` 的 `OpenClawd.process()` 负责 ingest → continuum → branch → manifest | 中心侧不是 UI 壳，而是认知与执行分派核 |
| `core/desktop_presence_runtime.py` 的 `DesktopPresenceRuntime` 声明自己拥有 tri-state 生命周期、本地感知入口与 Windows 呈现壳 | 桌面端不是“前端”，而是 AI 主体的显现载体 |
| `core/local_execution_chain.py` 与 `core/cross_device_execution_chain.py` 明确声明本地链和跨设备链都是 first-class canonical runtime chains | 系统天然就是双主链，而不是“中心端 UI + 移动端客户端” |
| `galaxy_gateway/routes/websocket.py` 把 `/ws/device/{device_id}` 定义为 sole canonical device ingress | 设备接入是被纳入中心治理的运行时网络，不是松散客户端登录 |
| Android 的 `GalaxyConnectionService.kt`、`RuntimeController.kt`、`GalaxyWebSocketClient.kt`、`LocalExecutionModeGate.kt` 共同定义了运行时生命周期、模式门控、委托执行与真值上送 | Android 是参与系统治理语义的强运行时节点，而不是被动终端 |

### 1.2 当前真实本体

按照真实代码，当前本体更准确地应表述为：

> **V2 作为中心治理核，持有任务理解、执行路径选择、设备接入、任务真值、结果归并与投影观察面；Android/桌面/平板等设备作为分布式执行、感知、交互、呈现节点接入同一主体网络。**

这一定义保留了中心权威，也保留了分布式执行网络，符合代码事实，不会把系统矮化为普通多客户端产品。

---

## 2. V2 当前掌握的中心权威

| 权威域 | 当前权威实现 | 代码锚点 |
|---|---|---|
| 调度 / 执行路径选择 | `OpenClawd.process()` 在 branch 阶段决定 local / cross_device / hybrid | `core/openclawd.py` |
| 路由 | `CommandRouter.route_envelope()` 是内部统一主入口；跨设备任务不得绕过它 | `core/command_router.py`, `core/cross_device_execution_chain.py` |
| 配置 | `UnifiedConfig` 作为兼容 facade，但配置读取仍汇总到 runtime/config.json、runtime/secrets.env、env、config.json | `core/unified_config.py`, `core/config_store.py`, `core/config_service.py` |
| 任务真值 | task result 必须经过 canonical truth chain 与 acceptance gate | `core/task_result_canonical_truth_chain.py`, `core/unified_result_ingress.py` |
| operator 聚合 | operator 证据与运行态被汇总到统一观测面 | `core/operator_execution_observability_surface.py`, `core/routes/projection.py` |
| 设备接入 | 设备注册、身份边界、附着运行态、能力同化都在注册链上完成 | `galaxy_gateway/android/handlers/registration.py` |
| gateway | `/ws/device/{device_id}` 是唯一 canonical ingress，其他路径都是 compat / deprecated / debug | `galaxy_gateway/routes/websocket.py` |
| 结果汇聚 | 统一结果摄取、Android truth stamp、evidence gate、completion linkage | `core/unified_result_ingress.py` |
| 投影 / 观察面 | runtime-truth、desktop-status-board、acceptance/cross-repo surfaces 统一从 projection 对外暴露 | `core/routes/projection.py`, `windows_client/status_board_v2/device_surface.py` |

### 2.1 结论

V2 当前已经不是单一“调度器”。它至少是：

- **中心调度核**
- **中心路由核**
- **中心真值核**
- **中心接入核**
- **中心观察/投影核**

但它**还不是完整闭合的中心智能体**：统一多设备规划、失败恢复策略、操作者可读决策理由、任务级重放与验收链仍未完全闭合。

---

## 3. Android / 桌面 / 平板 / 其他设备在代码里到底是什么

### 3.1 Android 不是普通客户端

Android 侧至少具备以下强运行时能力：

- **会话与上行主干**：`GalaxyWebSocketClient.kt`
- **运行时生命周期权威**：`RuntimeController.kt`
- **入站任务处理与委托执行**：`GalaxyConnectionService.kt`
- **本地推理能力**：`planner/LlamaCppPlannerService.kt`
- **本地 grounding 能力**：`grounding/NcnnGroundingService.kt`
- **本地执行循环**：`local/LocalLoopExecutor.kt`
- **模式自治边界**：`runtime/LocalExecutionModeGate.kt`

因此 Android 在真实代码里是：

> **AI 身体网络中的执行面 + 感知面 + 交互面节点，并且在 `local_only` / 本地推理条件下具备局部自治能力。**

### 3.2 桌面不是普通 UI

`DesktopPresenceRuntime` 明确声明它拥有：

- tri-state 生命周期；
- native multimodal ingress；
- Windows desktop presentation shell；
- 对 `OpenClawd` 的外层承载。

所以桌面不是普通 UI，而是：

> **AI 主体在 Windows 上的显现载体。**

### 3.3 平板 / 其他设备的定位

虽然当前主证据集中在 Android，但 `galaxy_gateway/android/handlers/registration.py` 会把设备能力映射到 `PERCEPTION / ACTION / PRESENCE` 等角色，说明系统在结构上把设备看成**能力面节点**，不是死板的“某端前端、某端后端”。

结论上可表述为：

- Android / 平板：偏执行面、感知面、交互面；
- Windows 桌面：偏中心显现面、操作面、部分本地执行面；
- 其他接入节点：按 capability 被吸纳进同一 AI 身体网络。

---

## 4. 本地链路与跨设备链路

### 4.1 本地链路主链

本地主链以 Windows 为主：

`DesktopPresenceRuntime.handle_request()`  
→ `OpenClawd.process()`  
→ `_determine_execution_path()` 选中 local  
→ `CommandRouter.route_envelope()`  
→ 本地 executor / capability / skill / MCP  
→ `LocalExecutionResult`  
→ `OpenClawd` feedback  

代码锚点：

- `core/desktop_presence_runtime.py`
- `core/openclawd.py`
- `core/local_execution_chain.py`
- `core/command_router.py`

### 4.2 跨设备链路主链

跨设备主链以 V2→Android 为主：

`OpenClawd.process()`  
→ `_determine_execution_path()` 选中 cross_device  
→ `CommandRouter.route_envelope()`  
→ `TaskEnvelope` / gateway substrate  
→ `/ws/device/{device_id}`  
→ Android `GalaxyConnectionService.kt` / `AutonomousExecutionPipeline.kt`  
→ `GalaxyWebSocketClient.kt` 回传结果  
→ `core/unified_result_ingress.py`  
→ `core/task_result_canonical_truth_chain.py` / acceptance  
→ `core/routes/projection.py`

### 4.3 两条链路如何并存

`core/local_execution_chain.py` 与 `core/cross_device_execution_chain.py` 都直接把自己定义为 **canonical chain**，并且都强调顶层权威是 `OpenClawd` + `CommandRouter`。  
这说明并存关系不是“主链 + 附属链”，而是：

> **同一主体核下的两条并行一级执行主链。**

### 4.4 当前闭环状态

- **已形成真实主链**
  - Windows 本地执行链；
  - V2 ↔ Android WebSocket 注册 / 任务下发 / 结果回流；
  - result → truth chain → projection 的主回流；
- **部分闭合**
  - mesh overlay 的 direct / relay / ws fallback；
  - Android acceptance evidence 与 V2 evidence gate 的联合验收；
  - 多设备参与态与 operator 观察面；
- **未完全闭合**
  - 多设备对同一目标的稳定协同执行；
  - 自动恢复、替代设备、统一验收与回放；
  - 产品级统一操作面。

---

## 5. 三态必须收束为唯一认知

### 5.1 唯一权威三态

当前唯一适合作为“静态 / 阈限态 / 显现态”权威实现的是：

**`core/desktop_presence_runtime.py` 的 `TriState`**

- `SILENT` → 静态
- `LIMINAL` → 阈限态
- `MANIFEST` → 显现态

该文件还明确说明：

- 这是 **subject lifecycle**；
- `DesktopPresenceRuntime` 是 **sole driver**；
- 其他状态族不能与之混用。

### 5.2 不是“真正三态”的相近状态源

以下状态源必须和真正三态区分：

| 状态源 | 分类 | 为什么不是真正三态 |
|---|---|---|
| `tri_state_phase` / continuum posture | **内部协议态** | 它是 OpenClawd 内部状态协议，不是主体总生命周期 |
| `ClosureState(established / partial / open)` | **工程闭合态** | 它描述工程完成度，不描述主体存在状态 |
| `DORMANT / ISLAND / SIDESHEET / FULLAGENT` | **近似态 / 壳层态** | 它描述 UI clothing / shell expansion，不描述主体正在做什么 |
| Android `ExecutionModeState`（`inactive / local_only / cross_device_active / ...`） | **工程运行态** | 它描述 Android 参与模式与治理门控，不是系统主体三态 |

### 5.3 基线要求

今后任何认知文档如果把上述内部协议态、工程闭合态或 UI 壳层态重新包装成“真正三态”，都应视为对当前基线的回退。

---

## 6. WebSocket / Mesh / NATS / 多设备结构

### 6.1 WebSocket 在真实系统中的位置

`galaxy_gateway/routes/websocket.py` 已明确：

- `/ws/device/{device_id}` 是 **sole canonical device ingress**；
- Android `GalaxyWebSocketClient.kt` 是 **sole cross-device uplink and session transport backbone**。

因此：

> **WebSocket 是当前双仓主链 transport。**

### 6.2 Mesh 在真实系统中的位置

`core/mesh_coordinator.py` 明确：

- `MESH_TRANSPORT_ROLE = "MESH::OVERLAY_ENRICHMENT_ONLY"`；
- 直连依赖 peer、LAN、`_p2p_send`；
- 失败后可退到 relay / ws。

`core/routes/hybrid.py` 又把 `_p2p_send`、`_relay_send`、`_ws_send` 真实接上。

因此：

> **Mesh 是 overlay，不是主链；direct path 是增强层，relay / ws 是回退层。**

### 6.3 NATS 在真实系统中的位置

`core/nats_bus.py` 明确：

- `GALAXY_NATS_URL` 控制是否启用；
- 无 URL 或无依赖时进入 **no-op mode**；
- 它是 distributed carrier / fabric layer。

因此：

> **NATS 是可选层，不是当前 V2↔Android 主链的必要前提。**

### 6.4 多设备结构结论

- **主链**：WebSocket
- **overlay**：Mesh
- **fallback**：mesh 内部 relay / ws 回退
- **可选层**：NATS

这四者不能再混说成“都是 transport 主链”。

---

## 7. Android 本地能力与自治边界

### 7.1 Android 是否具备真实本地执行链路

具备。直接代码证据包括：

- `planner/LlamaCppPlannerService.kt` 通过 JNI 调 `nativeLoadModel` / `nativeCompletion`
- `grounding/NcnnGroundingService.kt` 通过 JNI 调 `nativeLoadModel` / `nativeGround`
- `local/LocalLoopExecutor.kt` 提供 canonical local execution core
- `app/build.gradle` 声明 `com.github.ggerganov:llama.cpp:b4833` 与 `com.github.nihui:ncnn-android-vulkan:20240410`

### 7.2 Android 是否具备本地推理 / 本地执行能力

具备，且不是假桩：

- 本地 planner：llama.cpp
- 本地 grounding：NCNN / SeeClick
- 本地执行：`LocalGoalExecutor` / `LocalLoopExecutor`

### 7.3 Android 与中心治理核的关系

- 当 `LocalExecutionModeGate.ExecutionModeState` 处于 `LOCAL_ONLY`：Android 活着，但不接受中心派发；
- 当处于 `CROSS_DEVICE_ACTIVE` / `CROSS_DEVICE_DEGRADED`：Android 接入 V2 治理，成为可委托运行时；
- `RuntimeController.kt` 是 cross-device collaboration runtime 的 sole lifecycle authority；
- `GalaxyConnectionService.kt` 负责入站任务处理与结果发送；
- `GalaxyWebSocketClient.kt` 负责注册、心跳、结果 uplink、离线重放。

### 7.4 什么时候自治，什么时候被中心委托

| 场景 | Android 角色 |
|---|---|
| `LOCAL_ONLY` / 本地模式 | 自治执行节点 |
| `CROSS_DEVICE_ACTIVE` / `CROSS_DEVICE_DEGRADED` | 被中心委托的执行节点，同时保留本地运行时能力 |
| 中心任务到达时 | `GalaxyConnectionService.kt` → `AutonomousExecutionPipeline.kt` 处理委托执行 |

结论：

> **Android 不是始终自治，也不是始终被动；它是带自治能力、但可被中心纳入治理的强运行时节点。**

---

## 8. 当前成熟度：诚实分层

### 8.1 已形成真实主链的部分

- V2 本地链：`DesktopPresenceRuntime` + `OpenClawd` + `CommandRouter` + local execution chain
- V2→Android 主链：canonical WebSocket ingress、registration、dispatch、result backflow
- 结果真值链：`task_result_canonical_truth_chain` + `unified_result_ingress`
- 观察面：`core/routes/projection.py` + `windows_client/status_board_v2`

### 8.2 部分闭合的部分

- Android acceptance evidence 与 cross-repo acceptance chain
- Mesh direct / relay / ws fallback
- 多设备 participation / lifecycle projection
- operator evidence aggregation

### 8.3 弱证据部分

- 多设备同目标协同执行的稳定主路径
- 平板作为独立强运行时节点的现成证据
- 完整多模态产品壳层（语音 / 摄像头 / GUI 呈现统一闭合）

### 8.4 假闭环部分

- 有 NATS 代码 ≠ 当前双仓主链依赖 NATS
- 有 DORMANT / ISLAND / SIDESHEET / FULLAGENT ≠ 真正三态已经换定义
- 有 status board / operator-console ≠ 完整 operator control plane 已完成
- 有 mesh 组件 ≠ 多设备协作在真实网络里已经产品级闭合

### 8.5 缺失部分

- 统一中心智能体策略层
- 任务级真值链 / 结果链 / 验收链的一致可回放闭合
- 多设备协作恢复与替补策略
- 产品级桌面壳、全栈 operator 面、多模态统一交互面
- 足够强的双仓活体验证与回归矩阵

---

## 9. 全系统真实问题清单

### 9.1 状态语义

- 真正三态、内部协议态、工程闭合态、壳层态并存，极易被重新混写；
- Android execution mode state 与中心 tri-state 之间仍需长期保持语义边界。

### 9.2 执行策略

- 中心对 local / cross_device / hybrid 的策略理由仍不够可见；
- 多设备协作策略、替代策略、失败恢复策略尚未形成统一策略层。

### 9.3 中心智能体

- 当前是中心治理核，不是完整闭合的中心智能体；
- 缺少统一规划、重规划、恢复、解释、长期记忆闭环。

### 9.4 真值链 / 结果链 / 验收链

- 虽已有 canonical truth chain 与 evidence gate，但任务级端到端验收仍偏碎片化；
- cross-repo acceptance chain 仍更像诊断快照，而非全面活体验证闭环。

### 9.5 网络层 / transport

- WebSocket 是主链，但 mesh 直连仍受 LAN / NAT 条件限制；
- NATS 是可选层，部署时容易被误当成默认必要主链。

### 9.6 operator / control plane

- status board 偏观察，不等于可操作控制面；
- `static/operator-console/` 仍是轻量静态壳，不是完整全栈 operator 平面。

### 9.7 产品壳层 / desktop shell

- 桌面已具备显现壳语义，但完整产品壳仍未闭合；
- `DORMANT / ISLAND / SIDESHEET / FULLAGENT` 仍主要停留在壳层状态机，不足以代表完整用户体验。

### 9.8 多模态

- V2 有 multimodal ingress 语义，Android 有截图 / 感知 / grounding / 动作链；
- 但跨仓统一多模态产品体验、操作者可见性与验收仍不足。

### 9.9 测试 / 回归 / 活体验证

- 当前更强的是结构真值测试与文档约束；
- 双仓真实活体回归、复杂网络条件、长期稳定性、设备编队协作验证仍不足。

---

## 10. 作为正式基线的收束结论

1. **系统本体**：当前必须认定为中心分布式 AI 系统，而不是普通多客户端产品。
2. **中心权威**：V2 当前已掌握调度、路由、配置、任务真值、设备接入、gateway、结果汇聚、投影/观察面等中心治理权威。
3. **设备定位**：Android / 桌面 / 平板 / 其他设备应被理解为 AI 身体网络中的执行面、感知面、交互面、呈现面节点。
4. **双链路**：本地链路与跨设备链路都是一级主链，必须并存理解。
5. **唯一三态**：静态 / 阈限态 / 显现态只对应 `TriState.SILENT / LIMINAL / MANIFEST`；其他状态源不得重新包装成真正三态。
6. **传输层定位**：WebSocket 是主链，Mesh 是 overlay，NATS 是可选层。
7. **成熟度判断**：主链已成立，但完整中心智能体、多设备协同、全栈 operator/control plane、活体验证仍未闭合。

这份基线的作用，不是夸大系统，也不是把系统降级为普通多端产品，而是把双仓当前真实代码所证明的系统本体稳定收束下来。
