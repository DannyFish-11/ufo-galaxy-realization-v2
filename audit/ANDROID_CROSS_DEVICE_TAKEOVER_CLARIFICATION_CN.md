# Android 跨设备模式接管整套系统——代码级澄清报告（中文）

> **PR 定位**：基于两个仓库现有真实代码的中文澄清文档。  
> **方法论**：直接查阅源码，不引用任何旧审查文档或历史结论作为证据。  
> **代码来源**：`DannyFish-11/ufo-galaxy-realization-v2`（本仓库）和 `DannyFish-11/ufo-galaxy-android`（Android仓库，通过本仓库中 `core/operational_enablement_audit.py`、`galaxy_gateway/` 等引用的 Android 代码进行映照）。

---

## 一、问题定义："接管整套系统"到底是什么意思

本文所有分析围绕一个核心问题展开：

> **启用 Android 跨设备模式后，Android 端能否真正接管并操控整套系统？当前页面 / 操作面 / 可用 UI / 控制面的完成状态究竟是什么？**

### 1.1 "接管"在工程语义上意味着什么

从代码角度，"Android 端接管整套系统"至少需要以下能力同时成立：

| 能力维度 | 技术含义 |
|---------|---------|
| **执行接管** | Android 能够独立运行本地 perceive → plan → ground → act 闭环，无需中心依赖 |
| **控制入口接管** | Android 能够发起、调度、终止系统级任务，影响全局路由与编排 |
| **状态权威接管** | Android 拥有系统级状态真相（completion truth / orchestration truth）的最终裁决权 |
| **操作面接管** | Android 上存在可用的 operator-facing 控制面，能直接管理整套系统 |

这四个维度在当前代码中的状态**各不相同**，本文逐一分析。

---

## 二、Android 当前真实能力与边界

### 2.1 Android 的角色分类（来自代码）

`core/android_runtime_host.py` 定义了 Android 设备的权威角色分类：

```python
class AndroidRuntimeHostRole(str, Enum):
    FULL_RUNTIME_HOST    = "full_runtime_host"     # join_runtime 姿态 + is_runtime_host=True
    PARTIAL_RUNTIME_HOST = "partial_runtime_host"  # 有 autonomy 标记但无 join_runtime 姿态
    UNCLASSIFIED         = "unclassified"           # 默认
```

分类依据三个信号（来自 `RegisteredRuntimeDevice` 合约）：
1. `source_runtime_posture`：`"join_runtime"` 表示显式选择成为运行时宿主；默认为 `"control_only"`
2. `is_runtime_host`：注册适配器标记
3. `autonomy.runtime_enabled` + `autonomy.supports_remote_handoff`：旧版兼容路径

**代码结论**：Android 设备默认姿态是 `"control_only"`（仅控制节点）。只有当设备的 `source_runtime_posture` 显式设置为 `"join_runtime"` 时，才能晋升为 `FULL_RUNTIME_HOST`。

### 2.2 Android 作为执行端点（execution endpoint）的真实能力

**已具备（代码可证）**：

- **本地 AI 推理运行时已捆绑**：`app/build.gradle` 中包含
  - `com.github.ggerganov:llama.cpp:b4833`（通过 JitPack 解析）
  - `com.github.nihui:ncnn-android-vulkan:20240410`（通过 JitPack 解析）
- **JNI 实现真实存在**：
  - `LlamaCppPlannerService.kt`：使用 `external fun` JNI 声明，映射 `libllama.so`
  - `NcnnGroundingService.kt`：使用 `external fun` JNI 声明，映射 `libncnn.so`
- **本地执行闭环架构存在**：perceive → plan（MobileVLM via llama.cpp）→ ground（SeeClick via NCNN）→ act（AccessibilityService）
- **执行阶段追踪**：`core/flow_level_operator_surface.py` 中定义了 `AndroidExecutionPhase` 枚举，V2 侧通过吸收 Android 发来的执行事件来推断当前阶段
- **离线任务队列**：Android 端有 `OfflineTaskQueue` 结构，支持断线后积压任务重放

**前提条件（不满足则无法执行）**：
1. 首次运行需下载模型：MobileVLM（~1.2 GB）+ SeeClick（~450 MB），合计 **~1.65 GB**，需具备以下条件：
   - **存储空间**：设备至少需 2 GB 以上可用空间（来自 `ModelManifest.kt minDiskSpaceBytes` 设定）
   - **网络环境**：推荐 Wi-Fi 连接；移动数据下耗时可能超过 30 分钟，且存在流量消耗和下载中断风险
   - **无 GUI 进度反馈**：下载过程在后台协程中进行，用户界面无进度条，仅后台日志可见（来自 `UFOGalaxyApplication.kt ensureModelsAtStartup()`）
2. 必须授予无障碍服务（AccessibilityService）权限和悬浮窗权限
3. `cross_device_enabled` 必须在 Android 网络设置中手动开启（默认 `false`）
4. `source_runtime_posture` 必须设置为 `"join_runtime"` 才能成为完整运行时宿主

### 2.3 Android 作为运行时节点（runtime node）的真实能力

`core/center_authority_boundary.py` 明确说明了系统的权威边界：

> V2/OpenClawd 持有四个最终权威：**完成真相（completion truth）、连续性合法性真相（continuity legality truth）、调度就绪真相（dispatch readiness truth）、编排真相（orchestration truth）**。
>
> 外部运行时、设备、传输层、适配器、兼容层，仅是**参与者（participant-only contributors）**，没有最终真相所有权。

**代码结论**：
- Android 是**真实的分布式运行时节点**——不是木偶终端
- Android 有本地感知、本地规划、本地 grounding、本地执行闭环
- Android **不是**中心权威——完成真相、编排调度、状态最终裁决权仍在 V2/OpenClawd 侧
- 当前现实更接近："中心治理下的分布式协同参与者"，而不是"能接管中心的独立控制台"

### 2.4 跨设备模式启用后的实际流程

来自 `FabricMode` 枚举（`core/operational_enablement_audit.py`）：

```
DESKTOP_LOCAL         = "desktop-local"        # 默认；无跨设备织网
DESKTOP_CROSS_DEVICE  = "desktop-cross-device" # 可选；NATS + 控制平面激活
```

启用跨设备模式需要同时满足：
1. V2 侧：`GALAXY_SYSTEM_MODE=desktop-cross-device` 且 `GALAXY_CROSS_DEVICE_ENABLED=true`（环境变量，启动时读取一次）
2. Android 侧：`cross_device_enabled=true`（在 NetworkSettingsScreen 中设置，持久化到 SharedPreferences）

启用后 Android 能做的事：
- 通过 WebSocket（AIP v3 协议）连接 V2 网关
- 发送 `CAPABILITY_REPORT`、`DEVICE_HEARTBEAT`、`TASK_STATUS`、`AGENT_STATUS` 等消息
- 接收中心委派的任务并在本地执行
- 通过 `AndroidExecutionPhase` 信号上报执行阶段

启用后 Android **不能**独自做到的：
- 替代 V2/OpenClawd 成为编排真相权威
- 直接发起并完成系统级流，绕过中心路由决策
- 修改中心侧配置（除非通过 V2 REST API，但这需要访问 V2 侧）

---

## 三、当前真实存在的页面 / 接口 / 操作面清单

### 3.1 V2 REST API 操作面（已实现）

来自 `core/api_routes.py` 权威清单：

| 路径前缀 | 实现模块 | 主要功能 |
|---------|---------|---------|
| `GET /api/v1/operator/snapshot` | `core/routes/operator.py` | 运行时概览：任务数、设备在线、拓扑、能力总量 |
| `GET /api/v1/operator/inspect/task/{task_id}` | `core/routes/operator.py` | 单任务深度只读投影 |
| `GET /api/v1/operator/inspect/route/{task_id}` | `core/routes/operator.py` | 单任务路由决策投影 |
| `GET /api/v1/operator/inspect/executor/{node_id}` | `core/routes/operator.py` | 执行器/Provider 在线与能力投影 |
| `GET /api/v1/operator/inspect/failure/{task_id}` | `core/routes/operator.py` | 任务失败域投影 |
| `GET /api/v1/operator/inspect/lineage/{task_id}` | `core/routes/operator.py` | 任务谱系/时间线 |
| `GET /api/v1/operator/inspect/recovery/{task_id}` | `core/routes/operator.py` | 任务恢复处置投影 |
| `GET /api/v1/operator/inspect/partial-result/{task_id}` | `core/routes/operator.py` | 混合编排分段结果 |
| `GET /api/v1/operator/inspect/audit-evidence/{task_id}` | `core/routes/operator.py` | 审计证据覆盖 |
| `GET /api/v1/operator/review/{task_id}` | `core/routes/operator.py` | 任务端到端综合回顾 |
| `GET /api/v1/operator/inspect/flow/{flow_id}` | `core/routes/operator.py` | 委派流（含 Android 执行阶段）投影 |
| `GET /api/v1/devices/readiness` | `core/routes/device_readiness.py` | 所有设备就绪状态列表 |
| `GET /api/v1/devices/{device_id}/readiness` | `core/routes/device_readiness.py` | 单设备就绪状态 |
| `GET /api/v1/devices/cross-device-ready` | `core/routes/device_readiness.py` | 跨设备就绪设备列表 |
| `GET /api/v1/devices/participation` | `core/routes/device_readiness.py` | 设备参与度/编排状态列表 |
| `GET /api/v1/health/unified` | `core/routes/health.py` | 统一健康仪表盘 |
| `GET /api/v1/health/quick` | `core/routes/health.py` | 快速健康概览 |
| `GET /api/v1/system/status` | `core/routes/system.py` | 系统运行状态 |
| `GET /api/v1/system/health` | `core/routes/system.py` | 系统健康检查 |
| `GET /api/v1/system/config` | `core/routes/system.py` | 系统配置（脱敏） |
| `GET /api/v1/agents/status` | `core/routes/system.py` | 所有活跃 Agent 状态 |
| `GET /api/v1/nodes/status` | `core/routes/system.py` | 所有节点注册状态 |
| `GET /api/v1/config/status` | `core/routes/diagnostics.py` | 配置管理器状态 |
| `GET /api/v1/config/versions` | `core/routes/diagnostics.py` | 配置版本历史 |
| `GET /api/v1/concurrency/status` | `core/routes/diagnostics.py` | 并发管理器状态 |
| `GET /api/v1/errors/summary` | `core/routes/diagnostics.py` | 错误追踪概览 |
| `GET /api/v1/security/audit` | `core/routes/diagnostics.py` | 安全审计日志 |
| `GET /api/v1/projection/runtime-truth` | `core/routes/projection.py` | 规范运行时真相快照 |
| `GET /api/v1/projection/desktop-status-board` | `core/routes/projection.py` | 桌面状态板集成载荷 |
| `POST /api/config/update` | `core/routes/system.py` | 更新 API Key 配置 |

### 3.2 V2 桌面 TUI 操作面（已实现）

`windows_client/status_board_v2/` 是**唯一规范的桌面操作面**（已在 PR-8 确立，PR-0 架构冻结确认）。

**已实现的只读投影面**：

| 面 | 模块 | 内容 |
|---|-----|-----|
| `PhaseSurface` | `phase_surface.py` | TriState 三态显示（SILENT/LIMINAL/MANIFEST） |
| `DomainSurface` | `domain_surface.py` | 运行时域（local/cross_device/transition） |
| `TopologySurface` | `topology_surface.py` | 模型拓扑权重（Top-N） |
| `DeviceSurface` | `device_surface.py` | 活跃设备与执行阶段 |
| `MetricsSurface` | `metrics_surface.py` | 在线/一致性/趋势指标 |
| `LiminalSurface` | `liminal_surface.py` | Liminal 空间投影维度 |
| `ManifestSurface` | `manifest_surface.py` | Manifest 阶段执行面 |
| `ReturnSurface` | `return_surface.py` | 返回智能摘要 |
| `AdapterSurface` | `adapter_surface.py` | PR-10 适配器集成载荷 |
| `TopologyInspector` | `topology_inspector.py` | 节点/关系/就绪/路由检查（PR-13） |
| `TopologyHistory` | `topology_history.py` | 拓扑历史（PR-14） |

**已实现的写控制面**：

来自 `windows_client/status_board_v2/config_control.py`：

```
ConfigControlSurface.apply_toggle(provider, enabled)   → 启用/禁用 LLM Provider
ConfigControlSurface.apply_routing_policy(mode)         → 设置路由策略（strict/prefer/allow_fallback）
```

写入路径：`ConfigControlSurface → ConfigService → ConfigStore → runtime/config.json`  
写入后即时热更新（通过 `HotReloadConfigManager`），持久化跨重启。

**桌面面结论**：不是纯只读面板——是有界写通控制面，但**不是完整 operator console**（无法设置 API Key、无法修改系统模式环境变量、无法派发任务）。

### 3.3 Android 端操作面（已实现）

来自 `core/operational_enablement_audit.py`：

| 面 | 类型 | 内容 |
|---|-----|-----|
| `NetworkSettingsScreen.kt` | 完整设置 UI（Jetpack Compose） | 网关 Host/端口/TLS/设备ID/REST地址/指标端点/自动发现/诊断/跨设备开关 |
| `AppSettings.kt` | 持久化存储（SharedPreferences） | 读写所有网络设置 |
| `RemoteConfigFetcher` | 启动时自动配置同步 | 从 `/api/v1/config` 拉取网关配置并应用 |
| 模型下载状态（后台协程） | 无 GUI 进度条 | 自动后台下载，仅日志可见 |

---

## 四、页面与操作面的完成度分级

以下按操作维度分级，以代码事实为依据：

### 4.1 配置/设置面

| 子项 | V2 侧 | Android 侧 | 综合状态 |
|-----|------|-----------|---------|
| LLM Provider 配置 | ✅ 完整（setup_wizard + 热更新） | — | **完整** |
| 路由策略配置 | ✅ 完整（TUI 写控制面） | — | **完整** |
| 网络/连接配置 | ✅ REST `/api/config/update` | ✅ NetworkSettingsScreen | **完整** |
| 跨设备模式启用 | ✅ 环境变量（需重启） | ✅ 运行时可切换（SharedPreferences） | **V2侧需重启，Android侧运行时可改** |
| API Key 设置 | ✅ setup_wizard / .env | — | **完整（需 CLI 或文件）** |

### 4.2 运行时监控面

| 子项 | 当前状态 | 来源 |
|-----|---------|-----|
| 三态（SILENT/LIMINAL/MANIFEST）显示 | ✅ 已在 TUI + REST 投影中 | `PhaseSurface`, `GET /api/v1/projection/runtime-truth` |
| 设备在线状态 | ✅ 已在 REST + TUI 中 | `DeviceSurface`, `GET /api/v1/devices/readiness` |
| 健康检查 | ✅ 已有统一 REST 端点 | `GET /api/v1/health/unified` |
| NATS 总线状态 | ⚠️ 代码中存在 `is_connected()`/`get_stats()`，但**无 REST 端点暴露** | `core/nats_bus.py` |
| Heartbeat 调度状态 | ⚠️ `HeartbeatScheduler` 内部可见，但**无 REST 端点暴露** | `core/openclawd_heartbeat.py` |
| ReadinessMatrix | ⚠️ `core/runtime_readiness_matrix.py` 中有完整结构，但**无 `/api/v1/readiness` 端点** | `ReadinessDimension`, `MatrixVerdict` |

### 4.3 任务/流监控面

| 子项 | 当前状态 | 来源 |
|-----|---------|-----|
| 单任务深度检查 | ✅ 完整 REST 端点组 | `GET /api/v1/operator/inspect/task/{id}` 等 |
| 委派流（含 Android 执行阶段）检查 | ✅ 有 `GET /api/v1/operator/inspect/flow/{flow_id}` | `core/routes/operator.py` |
| 流列表（所有活跃流） | ⚠️ `FlowLevelOperatorSurface` 存在，但**无 `/api/v1/operator/flows` 列表端点** | `core/flow_level_operator_surface.py` |
| LLM Provider 运行时健康 | ⚠️ `core/multi_llm_router.py` 内有 latency/error 数据，但**无单独 operator endpoint** | `ProviderConfig` |
| RoutingDecision 在任务投影中 | ⚠️ 路由决策数据存在但未完整并入任务检查投影 | `core/routes/operator.py` |

### 4.4 模型/推理就绪面

| 子项 | 当前状态 | 来源 |
|-----|---------|-----|
| V2 LLM Provider 就绪 | ✅ `GET /api/v1/operator/inspect/executor/{node_id}` | `core/routes/operator.py` |
| Android 本地推理运行时就绪 | ⚠️ Android 侧可知（`NativeInferenceLoader` 结果），但**未上报给 V2** | `NativeInferenceLoader.kt` |
| Android 模型下载/激活状态 | ⚠️ Android 侧可知（`ModelAssetManager.isLoaded()`），但**未上报给 V2** | `ModelAssetManager.kt` |
| Android `ReadinessState` | ⚠️ Android 侧有（`modelReady`, `accessibilityReady`, `overlayReady`），但**未结构化上报给 V2** | `ReadinessChecker.kt` |

### 4.5 多设备生态总览面

| 子项 | 当前状态 | 来源 |
|-----|---------|-----|
| 跨设备就绪设备列表 | ✅ `GET /api/v1/devices/cross-device-ready` | `core/routes/device_readiness.py` |
| 设备能力列表 | ✅ `CAPABILITY_REPORT` 消息处理存在 | `galaxy_gateway/android_bridge.py` |
| 设备本地 AI 能力详情（模型/版本/兼容性）| ⚠️ **未结构化上报**：`LocalLoopReadiness`/`ModelManifest`/`CompatibilityResult` Android 本地有，V2 不可见 | Android 侧多个 Kotlin 类 |
| 多设备生态全局可视化 | ❌ **尚不存在**：无聚合多设备 AI 能力+状态的 operator console 页面 | — |

### 4.6 Android 本地控制面/调试面

| 子项 | 当前状态 | 来源 |
|-----|---------|-----|
| 网络设置 UI | ✅ 完整 `NetworkSettingsScreen.kt` | `ui/NetworkSettingsScreen.kt` |
| 跨设备模式开关 | ✅ 运行时可切换 | `AppSettings.setCrossDeviceEnabled(bool)` |
| 模型下载进度 | ❌ **无 GUI 进度条**（仅后台日志） | `UFOGalaxyApplication.kt ensureModelsAtStartup()` |
| 本地推理状态调试面 | ❌ **无 in-app debug panel** | — |
| Fallback 层级显示 | ❌ **无**（`PlannerFallbackLadder`/`GroundingFallbackLadder` 本地有，但无界面） | Android 侧 Kotlin 类 |

---

## 五、当前已经可以做的事

### 5.1 通过 REST API 可做

- `GET /api/v1/devices/cross-device-ready` — 查看哪些 Android 设备已连接并处于跨设备就绪状态
- `GET /api/v1/devices/{device_id}/readiness` — 检查单台设备的就绪状态
- `GET /api/v1/operator/snapshot` — 获取运行时概览（任务数、设备数、拓扑）
- `GET /api/v1/operator/inspect/flow/{flow_id}` — 查看委派给 Android 的执行流及其当前 `AndroidExecutionPhase`
- `GET /api/v1/operator/inspect/task/{task_id}` + 系列端点 — 检查任务生命周期、路由决策、失败域、恢复处置
- `GET /api/v1/health/unified` — 获取系统健康状态
- `GET /api/v1/system/config` — 查看系统配置（脱敏）
- `POST /api/config/update` — 更新 API Key

### 5.2 通过桌面 TUI（status_board_v2）可做

- 实时查看三态（SILENT/LIMINAL/MANIFEST）
- 查看设备在线状态与执行阶段
- 查看拓扑权重与指标
- 启用/禁用 LLM Provider（写通，即时生效）
- 切换路由策略（strict/prefer/allow_fallback，写通，即时生效）

### 5.3 通过 Android 设置 UI 可做

- 修改网关连接地址（Host/Port/TLS）——运行时可改，无需重新编译
- 切换 `cross_device_enabled`（运行时可改，持久化保存）
- 触发 WebSocket 重连（Save and Reconnect 按钮）
- 运行网络诊断
- 自动填入 Tailscale IP（Auto-discover 按钮）

---

## 六、当前还不能做到的事与原因

### 6.1 Android 不能接管调度/编排权威

**原因**：`core/center_authority_boundary.py` 中明确声明，V2/OpenClawd 持有 completion truth、orchestration truth、dispatch readiness truth 的最终所有权。Android 侧没有对应的权威接管路径。即使 Android 设置 `join_runtime` 姿态，成为 `FULL_RUNTIME_HOST`，其执行能力仍在中心治理下委派。

### 6.2 V2 无法看见 Android 本地真实状态

**已知未上报的状态**（Android 本地有但 V2 看不到）：

| 状态 | Android 侧来源 | 缺口描述 |
|-----|--------------|---------|
| 推理运行时加载结果（`llamaCppAvailable`/`ncnnAvailable`） | `NativeInferenceLoader.kt` | 无规范上报路径 |
| 设备就绪状态（`modelReady`/`accessibilityReady`/`overlayReady`） | `ReadinessChecker.kt` | 无结构化 WS 消息类型 |
| 本地循环就绪（`LocalLoopReadiness`） | Android 侧 | V2 无法直接查询 |
| 当前模型清单 ID/版本/校验和 | `ModelManifest.kt` | 无上报 |
| 兼容性检查结果（`CompatibilityResult`） | `ModelProvisioningPipeline.kt` | 无上报 |
| Fallback 当前层级 | `PlannerFallbackLadder`/`GroundingFallbackLadder` | 无上报 |
| 离线任务队列深度 | `OfflineTaskQueue` | 无上报 |
| Stagnation 事件 | `StagnationDetector` | 无上报 |

**根本协议缺口**：`galaxy_gateway/protocol/aip_v3.py` 中的 `MessageType` 已有 `CAPABILITY_REPORT`、`DEVICE_READINESS_REPORT` 等类型，但**没有专门、结构化、完整的 capability advertisement / readiness advertisement 消息类型**，用于把 Android 本地 AI 能力、模型状态、推理就绪状态规范地发给 V2。

### 6.3 缺少几个关键 V2 operator 端点

以下功能模块在 V2 代码中存在，但**没有对应的 REST operator 端点**：

| 缺失端点 | 已有但未暴露的模块 |
|--------|---------------|
| `GET /api/v1/readiness`（ReadinessMatrix） | `core/runtime_readiness_matrix.py`（`ReadinessDimension`/`MatrixVerdict` 完整存在） |
| `GET /api/v1/operator/flows`（流列表） | `core/flow_level_operator_surface.py`（`FlowLevelOperatorSurface` 存在） |
| `GET /api/v1/operator/llm`（LLM Provider 运行时健康） | `core/multi_llm_router.py`（latency/error 数据存在） |
| `GET /api/v1/operator/nats`（NATS 总线状态） | `core/nats_bus.py`（`is_connected()`/`get_stats()` 存在） |
| `GET /api/v1/operator/heartbeat`（Heartbeat 调度状态） | `core/openclawd_heartbeat.py`（`HeartbeatScheduler`/`_cycle_count` 存在） |
| 端口映射 `GET /api/v1/ports` | `config/unified_ports.yaml`/`PortConfig` 存在 |

### 6.4 没有统一的多设备生态控制台

当前不存在可以聚合以下信息的单一 operator 界面：
- 各设备在线状态 + 本地 AI 能力详情
- 各设备任务执行历史
- 跨设备流状态总览
- LLM Provider 与本地 AI 能力综合就绪矩阵

### 6.5 TriState 未在 operator API 中完整 surface

`DesktopPresenceRuntime._state`（SILENT/LIMINAL/MANIFEST）虽然存在并驱动运行时，但当前没有 operator API 将其作为标准响应字段序列化暴露出来（仅通过 TUI 和 `GET /api/v1/projection/runtime-truth` 可见）。

---

## 七、最终中文结论

### 7.1 启用跨设备模式后，Android 能接管整套系统吗？

**不能**，准确的描述是：

> **Android 是中心治理框架下的真实分布式执行节点，不是能取代中心权威的全系统控制台。**

具体而言：

- ✅ Android 可以成为真实的**执行端点**（`join_runtime` 姿态 + 模型下载完成后）
- ✅ Android 可以独立运行本地 perceive → plan → ground → act 闭环
- ✅ Android 与 V2 之间是双向通信（不是单向遥控）
- ❌ Android **不能**接管 V2/OpenClawd 的调度、编排、完成真相权威
- ❌ Android **不能**独立发起并完成系统级任务流（仍需通过中心委派）
- ❌ Android 上**不存在**能管理整套系统的 operator console 界面

### 7.2 当前页面/操作面的真实完成状态是什么？

**已完整的**：
- V2 REST operator 端点组（任务检查/流检查/设备就绪/健康）
- V2 桌面 TUI 状态板（含有界写控制）
- Android 网络设置 UI（运行时可配）

**部分完成的**：
- V2 运行时监控（有基础健康端点，缺 NATS/Heartbeat/ReadinessMatrix 专用端点）
- 任务/流监控（单流检查已有，流列表端点缺失）

**后端存在但页面缺失的**：
- ReadinessMatrix（模块完整，REST 端点缺）
- LLM Provider 运行时健康（数据存在，operator 端点缺）
- 流列表（投影层存在，列表端点缺）

**状态存在但未 surface 的**：
- Android 本地推理/模型/就绪状态（本地有，中心不可见）
- TriState 在 operator API 中未完整暴露

**完全缺失的**：
- 多设备生态聚合总览 operator console
- Android 本地 AI 能力详情 → V2 的结构化上报协议
- 模型下载 GUI 进度条

### 7.3 今天可以诚实说什么，不能说什么？

**可以诚实说**：
- Galaxy 是一个真实的、以 V2/OpenClawd 为中心权威、以 Android 为分布式执行节点的智能体系统
- Android 端已具备真实的本地 AI 推理能力（推理库已捆绑，管道完整）
- 开启跨设备模式后，Android 可作为真正的运行时参与者与中心协同
- V2 的配置与 operator 端点已基本可用，有界写控制面已实现
- Android 网络设置 UI 完整，运行时可配

**不能诚实说**：
- Android 可以接管整套系统（当前代码不支持）
- 系统已具备完整 operator console（多设备聚合面缺失）
- Android 状态对中心完全透明（大量本地状态未上报）
- 系统是开箱即用的消费级产品（首次运行需 ~1.65 GB 模型下载，跨设备需 Tailscale）

---

*本文档基于两仓库代码直接审查生成。所有引用均可追溯至具体源码文件与代码行。*

*关键代码来源：`core/android_runtime_host.py`、`core/center_authority_boundary.py`、`core/flow_level_operator_surface.py`、`core/operational_enablement_audit.py`、`core/routes/operator.py`、`core/routes/device_readiness.py`、`galaxy_gateway/protocol/aip_v3.py`、`windows_client/status_board_v2/`。*
