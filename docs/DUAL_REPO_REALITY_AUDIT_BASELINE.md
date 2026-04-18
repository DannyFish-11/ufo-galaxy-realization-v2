# 双仓联动代码现实审查基线

> **定位说明**
>
> 本文档是继 `DUAL_REPO_FULL_REAUDIT.md` / `DUAL_REPO_UNRESOLVED_AUDIT.md` 之后的
> **进一步审查基线**，以"联动双仓代码现实"为核心，更聚焦于：
> - 真实主链活跃程度
> - 关键断点标注
> - 目标态与现实差距
> - 后续工程推进的前置基础
>
> **范围**：
> - `DannyFish-11/ufo-galaxy-realization-v2`（V2，中心控制面）
> - `DannyFish-11/ufo-galaxy-android`（Android，边缘执行体）
>
> **原则**：
> - 只基于当前已合并代码现实，不依赖文档愿景或未合并 PR 叙事。
> - 区分"链路活着"、"结构存在但未活着"、"dead path / 强依赖外部环境"三种状态。
> - 中文为主，中英对照关键术语。
>
> **前置文档**（本文不重复，作为索引）：
> - `docs/DUAL_REPO_FULL_REAUDIT.md` — 七域全量再审查（最新全量基础文档）
> - `docs/DUAL_REPO_GAP_MATRIX.md` — 机器可读 gap 矩阵（40 条 gap，5 HIGH）
> - `docs/MULTI_DEVICE_RUNTIME_MATURITY.md` — 多设备运行时成熟度分类
> - `docs/ANDROID_PROTOCOL_MATURITY_MATRIX.md` — Android 协议长尾成熟度矩阵
> - `docs/UNIFIED_SCHEDULING_AUTHORITY_MAP.md` — 调度/路由权威链路图
> - `docs/FOLLOWUP_IMPLEMENTATION_ROADMAP.md` — 后续优先实现路线图

---

## 目录

1. [系统本体审查（A）](#a-系统本体审查)
2. [双仓主链审查（B）](#b-双仓主链审查)
3. [当前最小可运行形态审查（C）](#c-当前最小可运行形态审查)
4. [成熟度分层审查（D）](#d-成熟度分层审查)
5. [目标态统一整合审查（E）— 现实→目标态差距矩阵](#e-目标态统一整合审查--现实目标态差距矩阵)
6. [最关键现实问题清单（F）](#f-最关键现实问题清单)
7. [后续工程推进建议](#后续工程推进建议)

---

## A. 系统本体审查

### A.1 这套系统现在到底是什么

**一句话定义（基于代码现实）：**

> Galaxy 是一个以 Windows 桌面为核心宿主、以 OpenClawd 为认知执行核、以 Android 设备为边缘执行体、以 130+ Node 节点为工具延伸、以 WebSocket/AIP v3.0 为跨设备传输协议的**中心分布式智能体系统**。

它的现实形态是：
- **中心主脑**：运行于 Windows PC 的 `DesktopPresenceRuntime` + `OpenClawd`，是唯一具有完整认知-执行闭环的主体。
- **边缘执行体**：`ufo-galaxy-android` APK，通过 WebSocket 连接到中心网关，接收任务指派后在设备上执行 UI 操作/传感器采集/屏幕捕捉，并将结果上行。
- **工具节点群**：`nodes/` 目录下的 130+ Node，每个 Node 是一个独立 FastAPI 服务，通过 HTTP 被调用，提供特定能力（OCR、WebRTC、多模态推理、桌面自动化等）。

**它本质上是一个"中心分布式"系统，而不是对等 P2P 分布式系统：**
- 所有 routing decision 都由中心 `CommandRouter` 发起
- Android 不会主动发起跨设备协同，只能接受中心分配
- Node 网络是工具扩展，不参与 mesh 协商

### A.2 为什么它本质上是"中心分布式智能体系统"

从代码结构可以清楚看到中心化权威的技术表现：

```
用户请求
    │
    ▼ DesktopPresenceRuntime（外壳/会话管理/多模态感知）
    │
    ▼ OpenClawd（认知核：ingest → continuum → branch → manifest）
    │
    ▼ CommandRouter.route_envelope()   ← 唯一的跨设备分发权威
    │                                     SOLE CANONICAL CROSS-DEVICE DISPATCHER
    │
    ├─→ [LOCAL]     本地执行链 → AgentKernel → Windows API / 工具节点
    └─→ [REMOTE]    跨设备链  → TaskEnvelope → galaxy_gateway → Android
```

所有"分布"是由中心**主动下发**，没有任何组件可以绕过 `CommandRouter` 发起跨设备 task dispatch。

### A.3 三层关系的真实状态

| 层级 | 代码现实 | 真实关系 |
|------|----------|----------|
| **V2 中心主脑** | `main.py` → `DesktopPresenceRuntime` + `OpenClawd` → `CommandRouter` | 唯一认知-执行权威，认知和路由都在这里 |
| **Android 边缘执行体** | `galaxy_gateway/android_bridge.py` ← WebSocket ← APK | 被动执行体，接受 task_assign，上行 task_result |
| **Node 工具节点群** | `nodes/Node_XX/` → FastAPI → HTTP 调用 | 无状态工具扩展，按需被中心调用，不持有 session |

**三层关系关键特征**：
- V2 → Android：**命令式下发**，有 session 上下文，有心跳保活
- V2 → Node：**无状态 HTTP 调用**，节点不主动参与决策
- Android → V2：**结果上行**（task_result、心跳）和**请求上行**（task_cancel、task_status——但目前后两者未被 CommandRouter 消费，见 PROTO-002）

### A.4 Android 为什么"某种意义上是节点，又同时不是 nodes/Node_xxx 那种节点"

这个问题代码现实给出了清晰答案：

**Android 像节点的地方**：
- 注册到 `UnifiedDeviceManager (UDM)`，与 Node 同样被 `CapabilityAssimilationLayer` 管理
- 可以被 `CommandRouter` 作为目标分配任务
- 有 capability 声明（screen, touch, camera, etc.）

**Android 不是 nodes/Node_xxx 的地方**：
- Node 是**无状态 FastAPI HTTP 服务**，每次调用都是独立请求
- Android 是**有状态 WebSocket 长连接运行时**，有会话、有心跳、有 lifecycle
- Android 有自主感知能力（传感器、摄像头），能主动上行事件
- Android 受 `DesktopPresenceRuntime` 边缘执行语义管辖，Node 不受此管辖
- Android 侧有独立的 `TaskEnvelope` 执行引擎和 UI 自动化层（ADB/VLM），Node 只有 HTTP handler

**结论**：Android 是一个**有状态边缘运行时参与者（stateful edge runtime participant）**，在架构上介于 "pure tool node" 和 "peer agent" 之间，更接近边缘执行体（edge executor）。

---

## B. 双仓主链审查

### B.1 本地执行链（Center Local Path）

**入口**：`OpenClawd.process()` → `_determine_execution_path()` → `"local"` 分支

**权威主路径（canonical path）**：
```
OpenClawd._dispatch_local()
    └─ AgentKernel / DecisionExecutor
         └─ WindowsExecutionArbiter（Windows 平台执行仲裁）
              └─ 工具节点 HTTP 调用（Node_45_DesktopAuto 等）
                   或 MCP 工具调用
```

**关键文件**：
- `core/local_execution_chain.py`
- `core/windows_execution_arbiter.py`
- `core/desktop_presence_runtime.py`

| 字段 | 状态 |
|------|------|
| **实际入口** | `OpenClawd.process()` + `DesktopPresenceRuntime` 驱动 |
| **闭环程度** | ✅ **结构完整** — 本地执行是系统最成熟的路径 |
| **外部依赖** | LLM backend（`OPENAI_API_KEY` / `GEMINI_API_KEY`）；Windows OS（非 Windows 上结构存在但 `WindowsExecutionArbiter` 不可用） |
| **关键断点** | 1. LLM backend 缺失则认知核不可运行 2. 非 Windows 环境下本地执行链部分失效 |

### B.2 中心 → Android 跨设备链（Cross-Device Delegation Path）

**入口**：`CommandRouter.route_envelope()` 判断为 `cross_device` 路径

**权威主路径（canonical path）**：
```
CommandRouter.route_envelope()
    └─ cross_device_candidates.resolve_candidates()（三门准入：readiness/participation/validation）
         └─ formation_resolver.resolve_formation()（静态组型）
              └─ DeviceRouter.route_task()（传输基底层）
                   └─ UnifiedConnectionManager.send_to_device()（WebSocket）
                        └─ galaxy_gateway/android_bridge.py → Android APK
                             └─ 执行结果通过 task_result 上行
                                  └─ TaskGraphRuntime / ReplayFoundation（结果收集）
```

**关键文件**：
- `core/command_router.py`（唯一权威分发入口）
- `galaxy_gateway/device_router.py`（传输基底，含 policy 残留）
- `galaxy_gateway/android_bridge.py`（Android 协议桥接，AIP v3.0）
- `galaxy_gateway/protocol/aip_v3.py`（协议规范）

| 字段 | 状态 |
|------|------|
| **实际入口** | `CommandRouter.route_envelope()` |
| **闭环程度** | ⚠️ **部分闭环** — task_assign/task_result 往返存在，但 task_cancel/task_status 反向传播未实现（PROTO-002 HIGH） |
| **外部依赖** | Android APK 必须在线；AIP v3.0；WebSocket 端口 8765 |
| **关键断点** | 1. Android 未连接则无法执行 2. task_cancel 未传播 → 任务取消语义不可靠 3. `DeviceRouter._analyze_command()` policy 残留（SCHED-003） |

### B.3 中心 → Node 工具链（Node Invocation Path）

**入口**：`OpenClawd` 决定本地执行后，通过 `CapabilityBus` / MCP / HTTP 直接调用

**权威主路径（canonical path）**：
```
OpenClawd [local path]
    └─ CapabilityBus / node_invocation
         └─ HTTP POST → Node_XX:port/endpoint
              └─ Node 执行 → JSON 响应
                   └─ 结果回流 OpenClawd
```

**关键文件**：
- `core/node_invocation.py`
- `core/capability_bus.py`
- `nodes/Node_XX/main.py`（各节点 FastAPI 应用）

| 字段 | 状态 |
|------|------|
| **实际入口** | `node_invocation.py` 或 MCP tool wrapper |
| **闭环程度** | ✅ **单次调用闭环** — HTTP 请求-响应是完整的 |
| **外部依赖** | 各 Node 服务需独立启动；部分 Node 需 API Key（如 Node_98 需 `OPENAI_API_KEY`，Node_90 需 `GEMINI_API_KEY`） |
| **关键断点** | 1. Node 服务未启动则调用失败（无 fallback）2. Node discovery/startup 无 orchestration 闭环（各 Node 独立部署）3. 节点间协作（如 Node_90 调 Node_95）依赖 URL 配置正确 |

### B.4 多模态 / WebRTC / 推流 / 媒体链（Media Path）

**入口**：Android APK WebSocket 发送 `screen_stream_start` 消息 → `galaxy_gateway/webrtc_proxy.py` 转发给 `Node_95_WebRTC_Receiver`

**当前实际结构**：
```
Android APK
    │  ws://GATEWAY_HOST/ws/webrtc/{device_id}
    ▼
galaxy_gateway/webrtc_proxy.py（信令代理）
    │  ws://NODE_95_HOST/signaling/{device_id}
    ▼
Node_95_WebRTC_Receiver（WebRTC 接收节点，端口 8095）
    │  HTTP 帧获取 API
    ▼
Node_90_MultimodalVision（VLM 推理节点，端口 8090）
    │  依赖 GEMINI_API_KEY
    ▼
VLM 推理结果（独立返回，未并入 TaskEnvelope）
```

**关键文件**：
- `galaxy_gateway/webrtc_proxy.py`
- `nodes/Node_95_WebRTC_Receiver/main.py`
- `nodes/Node_90_MultimodalVision/main.py`
- `core/multimodal/webrtc_session.py`
- `core/multimodal/webrtc_session_manager.py`

| 字段 | 状态 |
|------|------|
| **实际入口** | Android 直接发起 WebRTC 信令请求，独立于任务生命周期 |
| **核心 authority** | `webrtc_proxy.py` 作为信令代理（无 canonical task lifecycle authority） |
| **闭环程度** | ❌ **孤立子系统** — WebRTC 信令存在，但与 `TaskEnvelope` / `CommandRouter` 没有任何 lifecycle 绑定 |
| **外部依赖** | `aiortc`、`av`、`opencv-python`；Node_95 独立运行；Gemini API（VLM） |
| **关键断点** | 1. WebRTC session 未被 TaskEnvelope 管理 → task_cancel 不会关闭 WebRTC session 2. 无 task_id 绑定 → 流媒体归属不明 3. Node_90 VLM 结果不回流到 TaskGraphRuntime（WEBRTC-001, WEBRTC-002） |

---

## C. 当前最小可运行形态审查

### C.1 系统最可能成功启动的环境

**最小启动环境**（代码现实）：

```
操作系统：    Windows 10/11（非 Windows 上 DesktopPresenceRuntime 有限可用）
Python：      3.9+
LLM backend： 至少一个（OPENAI_API_KEY 或 GEMINI_API_KEY）
Node 服务：   可选，但大多数实际能力需要至少部分 Node 运行
端口需求：    8765（gateway WebSocket），各 Node 端口（8015, 8045, 8090, 8095 等）
```

**启动命令**：`python main.py`（权威入口，7 阶段 staged bring-up）

### C.2 启动后现实可用的最小能力集

| 能力 | 可用性 | 条件 |
|------|--------|------|
| 对话（无工具调用）| ✅ 可用 | LLM backend 在线 |
| Windows 本地 UI 自动化 | ✅ 可用（Windows only）| Node_45_DesktopAuto 运行 |
| Android 设备连接 | ✅ 可用 | APK 在线，WebSocket 连接到 :8765 |
| Android task_assign/task_result | ✅ 往返可用 | APK 在线 |
| WebRTC 视频流（信令） | ⚠️ 部分可用 | Node_95 运行；信令通路存在但不绑定任务 |
| VLM 图像分析 | ⚠️ 部分可用 | GEMINI_API_KEY + Node_90 运行 |
| 多设备 mesh 会话 | ❌ 不可用 | contract-first，无运行时引擎 |
| 任务取消传播 | ❌ 不可用 | PROTO-002 HIGH gap |

### C.3 系统最可能以什么形态"跑起来"

**现实最小可运行形态**：

> **Windows 本地单设备智能体**：用户在 Windows PC 上启动，通过自然语言发起任务，由 OpenClawd 决策，调用 Windows 本地工具节点（DesktopAuto/OCR/文件系统等）完成操作。

这是系统**实际完整闭环**的唯一可靠形态。

**可选扩展但非必须**：
- 同时连接 Android APK → 中心可向 Android 下发任务并收集结果
- 同时启动部分 Node → 扩展特定工具能力（搜索/代码/多模态等）

### C.4 看起来存在但现在跑不成完整闭环的东西

| 结构/组件 | 现状描述 |
|-----------|----------|
| 多设备 mesh 会话 | `MeshSession` / `MeshSessionCoordinator` 合约完整，但无运行时引擎驱动状态迁移 |
| 任务取消/状态同步 | Android 侧发送 task_cancel，中心 _handle_forward_log 只记录日志，CommandRouter 不消费 |
| WebRTC → 任务生命周期 | WebRTC 信令独立存在，不由 TaskEnvelope 管理，无 task_id 绑定 |
| 动态设备组型 | formation_resolver 只做静态解析，设备断线不会触发重组 |
| session 迁移 | 两套独立实现（galaxy_gateway 和 core/routes），未确认是否收敛到同一引擎 |
| 混合执行（hybrid） | AIP v3 有 HYBRID_EXECUTE 枚举，Android 侧降级使用 HYBRID_DEGRADE，真正 hybrid 未实现 |
| 对等 mesh（P2P） | peer_announce / mesh_topology / peer_exchange 定义在 AIP 协议中，但明确标注为 DEFER |

---

## D. 成熟度分层审查

以代码现实为基准，按五个维度给出成熟度判断：

### D.1 中心主脑成熟度

**成熟度：高（结构完整，执行路径闭环）**

| 组件 | 成熟度 | 说明 |
|------|--------|------|
| `DesktopPresenceRuntime` | ✅ **runtime-complete** | Windows 外壳完整，tri-state lifecycle 可用 |
| `OpenClawd`（认知核） | ✅ **runtime-complete** | ingest→continuum→branch→manifest 完整 |
| `CommandRouter`（分发权威） | ✅ **runtime-complete** | 唯一权威，三门准入链完整 |
| `CapabilityAssimilationLayer` | ✅ **runtime-complete（注册）** | 注册侧完整；dispatch 侧 advisory-only（SCHED-001）|
| `TruthIntegrationLayer` | ⚠️ **partial** | 已接入 canonical path；fallback 路径仍返回 null truth |
| `MultiDeviceRuntimeProjection` | ⚠️ **contract-first（partial）** | 合约稳定；merged_results 填充不完整 |

**关键限制**：DesktopPresenceRuntime 强依赖 Windows，非 Windows 系统上只有 OpenClawd 认知逻辑可用，本地执行链不完整。

### D.2 Android 边缘执行成熟度

**成熟度：中（连接+任务执行闭环；控制反向未闭环）**

| 能力 | 成熟度 | 说明 |
|------|--------|------|
| 设备注册/心跳 | ✅ **runtime-complete** | UDM/UCM 注册完整 |
| task_assign/task_result | ✅ **runtime-complete** | 往返完整 |
| task_cancel/task_status 反向传播 | ❌ **not wired** | android_bridge 收到但 CommandRouter 不消费（PROTO-002 HIGH）|
| session_migrate | ❌ **partial** | AIP v2 binary，需迁移到 AIP v3（PROTO-001 HIGH）|
| AIP v2 binary 类型（0x60/0x61） | ❌ **legacy/transitional** | 需迁移到 AIP v3 JSON（PROTO-005）|
| 能力声明 → CapabilityAssimilationLayer | ❌ **unconfirmed wiring** | device_capabilities 收到，但是否自动进入 CapabilityAssimilation 未确认（CROSS-004）|

### D.3 Node 网络成熟度

**成熟度：中（单节点调用完整；节点发现/编排未闭环）**

| 维度 | 成熟度 | 说明 |
|------|--------|------|
| 单节点 HTTP 调用 | ✅ **runtime-complete** | 请求-响应完整 |
| 节点间协作（Node_90 → Node_95）| ⚠️ **partial** | URL 配置驱动，无 mesh 治理 |
| Node discovery / startup orchestration | ❌ **not implemented** | 各 Node 需手动启动；无自动发现和健康编排 |
| Node 能力注册 → CapabilityAssimilationLayer | ⚠️ **partial** | assimilate_node() 存在，但 dispatch 侧不查询（SCHED-001）|

### D.4 多设备 / Mesh 成熟度

**成熟度：低（合约完整，运行时引擎缺失）**

| 组件 | 成熟度 | 说明 |
|------|--------|------|
| `formation_resolver`（静态组型）| ✅ **runtime-complete（static）** | 静态组型完整；无动态重组 |
| `CommandRouter` 跨设备 fanout | ✅ **runtime-complete** | 并行 fanout 完整 |
| `BodyMeshRegistry` | ⚠️ **partial** | in-memory only；无持久化（MESH-003）|
| `MeshSession` lifecycle | ❌ **contract-first** | 状态机存在；无引擎驱动（MESH-002）|
| `MeshSessionCoordinator` | ❌ **contract-first** | 合约完整；无 live coordinator 引擎（MESH-001 HIGH）|
| 动态 formation 重组 | ❌ **not implemented** | 设备掉线不触发重组（MESH-006）|
| 分阶段 mesh 执行 | ❌ **not implemented** | 仅并行 fanout，无 A→B 依赖执行（MESH-008）|
| mesh 结果 merge 引擎 | ❌ **contract-first** | `CrossRuntimeResultMerge` 合约存在；无执行引擎（MESH-007）|

### D.5 原生多模态 / WebRTC / 推流成熟度

**成熟度：低（信令通路存在；任务生命周期整合缺失）**

| 维度 | 成熟度 | 说明 |
|------|--------|------|
| WebRTC 信令代理 | ✅ **partial** | `webrtc_proxy.py` 信令转发存在 |
| Node_95 视频接收 | ✅ **partial** | 独立节点可运行 |
| WebRTC → TaskEnvelope 绑定 | ❌ **not implemented** | 完全独立，无 task_id 绑定（WEBRTC-001）|
| task_cancel → WebRTC session 关闭 | ❌ **not implemented** | 任务取消不触发 WebRTC session 释放（WEBRTC-001）|
| VLM 结果 → TaskGraphRuntime | ❌ **not implemented** | Node_90 结果独立返回，不回流 task 链（WEBRTC-002）|
| 音频流摄入（AudioIngestService）| ⚠️ **partial** | 本地音频采集存在；跨设备音频链未定义 |
| 推流连续性（transport continuity）| ❌ **not implemented** | 无 `TransportContinuity` 策略实施 |

---

## E. 目标态统一整合审查 / 现实→目标态差距矩阵

### E.1 总体差距矩阵

| 目标维度 | 当前现实 | 还缺什么 | 最关键阻断点 | 收敛优先级 |
|----------|----------|----------|--------------|------------|
| **中心分布式网络拓扑** | CommandRouter 单点分发，静态 formation | 动态 formation 重组；设备健康驱动拓扑变化 | formation_resolver 无动态重组（MESH-006）| 中 |
| **节点治理闭环** | Node 手动启动，HTTP 调用无治理 | Node discovery/startup orchestration；Node 健康监控 | Node 无 orchestration 引擎 | 中 |
| **ATS / readiness / participation / dispatch / mesh 收敛** | 3 门准入（readiness/participation/validation）已实现；能力匹配未接入准入链 | Gate 4：capability verification in admissibility chain；live MeshSession engine | SCHED-001 advisory-only；MESH-001/002 contract-first | 高 |
| **Android 作为真正边缘 runtime participant** | 连接+接收任务+上报结果闭环；取消/状态反向未实现 | task_cancel/task_status canonical handler；session_migrate AIP v3；hybrid execution | PROTO-002（task_cancel）HIGH；PROTO-001（session_migrate）HIGH | 高（优先） |
| **原生多模态智能体** | 本地 Windows 音视频感知（DesktopPresenceRuntime）；Android VLM 调用 Node_90 独立 | WebRTC 绑定 TaskEnvelope；VLM 结果回流 TaskGraphRuntime | WEBRTC-001；WEBRTC-002 | 高 |
| **WebRTC / 推流 / transport continuity 打通** | 信令代理存在（webrtc_proxy.py）；Node_95 独立运行 | task-scoped WebRTC session；task_cancel/complete 触发 session 生命周期 | WEBRTC-001 MEDIUM；无 task lifecycle hook | 中高 |
| **task lifecycle / runtime lifecycle / media lifecycle 统一** | task lifecycle 在 TaskEnvelope+TaskGraphRuntime；runtime lifecycle 在 DesktopPresenceRuntime；media lifecycle 完全独立 | media lifecycle 并入 task lifecycle；runtime/task lifecycle 统一 event bus | WebRTC 孤立子系统（WEBRTC-001）；无统一 lifecycle event bus | 高 |

### E.2 已经有什么（现实可信）

1. ✅ `CommandRouter` 是唯一的跨设备分发权威，三门准入链完整
2. ✅ `CapabilityAssimilationLayer` 统一了 Node 和 Device 的能力注册
3. ✅ `TruthIntegrationLayer` + `RegisteredRuntimeDevice` 是规范的设备真相读取路径
4. ✅ AIP v3.0 协议稳定，`galaxy_gateway/android_bridge.py` 实现完整
5. ✅ Android task_assign/task_result 往返闭环完整
6. ✅ `formation_resolver` 静态组型完整
7. ✅ `MeshSession` / `MeshSessionCoordinator` 合约设计完整（但无运行时引擎）
8. ✅ WebRTC 信令代理通路存在（但未绑定任务生命周期）
9. ✅ 130+ Node 服务结构完整（但需手动启动和配置）

### E.3 还缺什么（按重要性）

**一级缺失（阻断核心运行质量）**：
- ❌ task_cancel/task_status 从 Android → CommandRouter 的 canonical handler
- ❌ MeshSession / MeshSessionCoordinator 的 live runtime 引擎
- ❌ session_migrate AIP v3 统一路径

**二级缺失（影响系统完整性）**：
- ❌ WebRTC → TaskEnvelope 生命周期绑定
- ❌ CapabilityAssimilationLayer 作为 Gate 4 加入准入链
- ❌ Android device_capabilities → CapabilityAssimilationLayer 的自动接入确认
- ❌ formation 动态重组（设备健康驱动）

**三级缺失（影响系统成熟度）**：
- ❌ Node 服务 discovery/startup orchestration 闭环
- ❌ Android local truth → V2 outward truth 对账协议
- ❌ `DeviceRouter._analyze_command()` + `_select_devices()` policy 残留清理
- ❌ hybrid execution 真实实现（当前 Android 侧降级为 HYBRID_DEGRADE）

### E.4 后续最值得优先推进的收敛方向

基于 gap 严重程度和依赖关系，推荐收敛顺序：

```
P0（解除最高危 correctness 问题）
  └─ task_cancel / task_status canonical handler（PROTO-002 HIGH）
     → Android 任务取消语义才可靠

P1（解除 mesh 基础 blocking gap）
  └─ live MeshSession / MeshSessionCoordinator 引擎（MESH-001/002 HIGH）
     → 多设备 mesh 会话才能从 contract-first 进入 runtime-complete

P2（解除跨设备会话协议 blocking gap）
  └─ session_migrate AIP v3 统一路径（PROTO-001 HIGH）
     → session 迁移路径才有可靠实现

P3（WebRTC 并入主链）
  └─ WebRTC → TaskEnvelope task lifecycle 绑定（WEBRTC-001/002）
     → 多模态视觉 task 才能有完整闭环

P4（能力路由收敛）
  └─ CapabilityAssimilationLayer 作为 CommandRouter Gate 4（SCHED-001）
     → 能力路由才从 advisory 变成 enforcement
```

---

## F. 最关键现实问题清单

以下是按优先级排序的高价值问题清单，聚焦于**真正妨碍系统整体跑起来**以及**妨碍目标态统一收敛**的问题：

### F.1 P0 — 任务取消语义不可靠（阻断 Android 运行正确性）

- **问题**：Android 侧发送 `task_cancel`，`android_bridge.py` 只记录日志（`_handle_forward_log`），`CommandRouter` 不消费，任务继续执行。用户以为取消了，实际没有。
- **影响模块**：`galaxy_gateway/android_bridge.py` → `CommandRouter`
- **缺口编号**：PROTO-002 HIGH
- **解决方向**：为 task_cancel/task_status 添加 canonical handler，接入 `CommandRouter` 取消链路

### F.2 P0 — LLM backend 依赖（阻断系统启动）

- **问题**：OpenClawd 认知核依赖 LLM backend（OpenAI / Gemini / 本地 LLM）。无 API Key 则 cognition 不可用，整个系统退化为空壳。
- **影响范围**：全系统
- **现状**：`.env.example` 提供了配置模板，但无 LLM fallback 策略（Node_79_LocalLLM 存在但未确认接入 multi_llm_router 作为 fallback）
- **解决方向**：确认 Node_79_LocalLLM 作为本地 LLM fallback；或至少有明确的"无 LLM 降级策略"

### F.3 P1 — MeshSession 无 live 引擎（阻断多设备 mesh 运行）

- **问题**：多设备 mesh 会话的状态机（FORMING→ACTIVE→COMPLETING→DONE）已在合约中定义，但无任何运行时引擎驱动这些状态转换。屏障同步、角色分配、结果 merge 都是合约声明而非运行时行为。
- **影响模块**：`contracts/mesh_session.py`、`contracts/mesh_session_coordinator.py`
- **缺口编号**：MESH-001 HIGH、MESH-002 HIGH
- **解决方向**：实现 `MeshSessionCoordinator` 运行时引擎，从 `TaskGraphRuntime` 读取事件驱动状态转换

### F.4 P1 — Windows-only 本地执行限制

- **问题**：`DesktopPresenceRuntime` 是 Windows 桌面外壳，Windows 执行仲裁器（`WindowsExecutionArbiter`）和 UI 自动化（Node_45_DesktopAuto / Node_36_UIAWindows）强依赖 Windows。非 Windows 环境下本地执行链严重降级。
- **影响范围**：本地执行链的全部 Windows 特定能力
- **解决方向**：明确"Linux-headless mode"的最小能力集；或将 Node_124_LinuxDesktopAuto 纳入 Linux 执行路径

### F.5 P2 — session_migrate 双路径风险（会话迁移可靠性）

- **问题**：`galaxy_gateway/session_roaming.py` 和 `core/routes/sessions.py` 各自实现了 session 迁移逻辑，但两者是否收敛到同一引擎未确认。如果不收敛，通过不同路径迁移的 session 可能产生 split-brain 状态。
- **影响模块**：`galaxy_gateway/session_roaming.py`、`core/routes/sessions.py`
- **缺口编号**：MESH-005 MEDIUM
- **解决方向**：明确 canonical session migration path；确认 core/routes/sessions.py 委托给 gateway/session_roaming.py

### F.6 P2 — Android capability 自动注入 CapabilityAssimilationLayer 未确认（路由能力盲目）

- **问题**：Android 连接时上报 `device_capabilities`，但是否自动调用 `CapabilityAssimilationLayer.assimilate_device()` 未确认（CROSS-004）。如果未注入，能力路由无法感知 Android 设备的真实能力，可能将需要 VLM 能力的任务分发给无 VLM 能力的设备。
- **影响模块**：`galaxy_gateway/android_bridge.py` → `CapabilityAssimilationLayer`
- **缺口编号**：CROSS-004 LOW（实际影响 MEDIUM）
- **解决方向**：在 `_handle_device_register()` 中确认调用 `assimilate_device()`

### F.7 P2 — Node discovery / startup / orchestration 闭环不足

- **问题**：130+ Node 服务需要手动启动并正确配置 URL。系统没有自动发现、健康检查驱动启动、故障重启的 Node orchestration 层。单个 Node 宕机不会通知 CommandRouter，调用会静默失败。
- **影响范围**：全部 Node 工具链
- **解决方向**：实现 Node health monitoring（docker-compose/systemd 或 Node_67_HealthMonitor 完整接入）

### F.8 P3 — WebRTC 信令仅存在，未真正并入主链

- **问题**：`webrtc_proxy.py` 作为信令代理存在，但：
  1. 没有任何 task type 会触发 WebRTC session 建立
  2. 任务取消不会关闭 WebRTC session
  3. 视频流消费（Node_95/90）结果不回流 TaskGraphRuntime
  意味着所有"需要实时设备视觉输入"的任务实际上无法获得视频输入。
- **缺口编号**：WEBRTC-001, WEBRTC-002 MEDIUM
- **解决方向**：将 WebRTC session 生命周期与 TaskEnvelope 绑定（建立/释放都由 task lifecycle 驱动）

### F.9 P3 — cancel/status/recovery/backflow 等高阶链未闭环

- **问题集合**（均属于"已有结构但未运行"类）：
  - `task_cancel` 反向传播：见 F.1
  - `task_status` 反向传播：同 PROTO-002
  - recovery/resume from checkpoint：`MeshSession` 无持久化，无 checkpoint store
  - backflow / `CrossRuntimeResultMerge`：合约存在，无运行时 merge 引擎（MESH-007）
  - Android local truth → V2 reconciliation：TRUTH-005，无对账协议

### F.10 P3 — DeviceRouter policy 残留（routing 决策分裂风险）

- **问题**：`DeviceRouter._analyze_command()` 和 `_select_devices()` 包含 classification 和 device selection 逻辑，这些逻辑理论上应属于 `CommandRouter` 的职责。存在三条独立的设备选择路径（准入链 / DeviceRouter / ConstellationRuntime DevicePool），在某些边缘情况下可能产生不一致的路由决策。
- **缺口编号**：SCHED-003 LOW
- **解决方向**：将 `_analyze_command()` logic 迁移到 `CommandRouter`；`DeviceRouter` 成为纯传输基底

---

## 后续工程推进建议

本文档可直接作为以下后续实现型 PR 的前置基线：

| PR 类型 | 对应 gap | 前置条件 |
|---------|----------|----------|
| **task_cancel/status canonical handler PR** | PROTO-002 | 本文档 F.1 审查结论 |
| **live MeshSession engine PR** | MESH-001, MESH-002 | 本文档 D.4、E.3 P1 |
| **session_migrate AIP v3 统一 PR** | PROTO-001 | 本文档 F.5 审查结论 |
| **WebRTC → TaskEnvelope lifecycle binding PR** | WEBRTC-001, WEBRTC-002 | 本文档 B.4、D.5 |
| **CapabilityAssimilationLayer Gate 4 PR** | SCHED-001, CROSS-004 | 本文档 E.3 P4 |
| **Node discovery/orchestration PR** | Node 无 orchestration | 本文档 D.3、F.7 |
| **Android truth → V2 reconciliation PR** | TRUTH-005, CROSS-002 | 本文档 D.2、F.9 |

---

*本文档是基于代码现实的可信双仓审查基线，不包含未合并代码的预测或愿景。*
*由审查 PR `建立双仓联动代码现实审查基线并统一目标态认知` 产生，版本日期：2026-04-18。*
