# Galaxy 系统完整认知最终中文说明 · 2026

> **审查方法论**：本文件完全基于对两个代码仓库当前源码的直接阅读，不依赖任何历史审查文档、设计文档或旧结论作为证据。所有判断均追溯到具体文件、类名、函数名和常量名。
>
> **审查仓库**：
> - `DannyFish-11/ufo-galaxy-realization-v2`（V2 中心节点 — Python）
> - `DannyFish-11/ufo-galaxy-android`（Android 分布式节点 — Kotlin）
>
> **审查日期**：2026-05-02

---

## 目录

1. [系统本体的最终中文解释](#section-1)
2. [多设备 / 双向 / 多向协作现实说明](#section-2)
3. [Android 当前真实地位说明](#section-3)
4. [操作面板应如何理解的系统层说明](#section-4)
5. [当前未完成项清单](#section-5)
6. [对未来设备生态扩展能力的准确说明](#section-6)
7. [最终中文结论与定性](#section-7)

---

<a name="section-1"></a>
## 第一节：系统本体的最终中文解释

### 1.1 这套系统究竟是什么

从代码定义来看，Galaxy 系统的本质是一个**中心治理型分布式智能体系统**。

这套系统不是一个单机 AI 助手，也不是一个简单的"电脑控制手机"的单向遥控系统。它的架构是：

```
中心节点 (V2 / OpenClawd + DesktopPresenceRuntime)
    │
    ├── 本地执行链  (LOCAL EXECUTION CHAIN)
    │       → 在本机 Windows 上直接执行 (DecisionExecutor, WindowsExecutionArbiter)
    │
    └── 跨设备执行链  (CROSS-DEVICE EXECUTION CHAIN)
            → 通过网关将任务分发到远端设备 (Android、其他节点)
            → 设备反馈执行结果 → 中心收到后合并、评估、继续决策
```

**代码证据**（`core/desktop_presence_runtime.py` 文件头部注释）：
```
DesktopPresenceRuntime (outer shell / Windows clothing)
    └─ owns: session, tri-state lifecycle, native multimodal ingress
    └─ invokes OpenClawd inside liminal
          └─ OpenClawd: ingest → continuum → branch → manifest
                ├─ LOCAL EXECUTION CHAIN   (core/local_execution_chain.py)
                └─ CROSS-DEVICE EXECUTION CHAIN  (core/cross_device_execution_chain.py)
```

### 1.2 V2 究竟是什么

V2 是**整套分布式系统的中心治理节点**，是用 Python/FastAPI 构建的后端服务。

V2 不是一个独立完整的"主体"，而是由两层构成一个统一主体：

**外壳层 — DesktopPresenceRuntime**（`core/desktop_presence_runtime.py`）：
- 拥有 `runtime_session_id`（整个请求生命周期的稳定关联 ID）
- 驱动主体三态生命周期：`SILENT → LIMINAL → MANIFEST → SILENT`
- 拥有连续感知入口（`MultimodalIngressBus`，负责持续的主机环境感知）
- 是外部请求的入口点（chat、gateway、launcher 等只是适配器）

**内核层 — OpenClawd**（`core/openclawd.py`）：
- 在 LIMINAL 阶段被 DesktopPresenceRuntime 调用
- 阶段 1：信息摄入（PerceptionFrame 持续感知 + multimodal_context 请求级多模态融合）
- 阶段 2：认知处理（ContinuumOrchestrator — intent → state_continuum）
- 阶段 3：执行路径决策（`_determine_execution_path`）：
  - `local` → 本机 Windows 执行
  - `cross_device` → 跨设备分发（网关 → 远端设备）
  - `hybrid` → 本机和跨设备同时执行
  - `none` → 仅回复，不执行
- 阶段 4：执行（DecisionExecutor 本地 / CommandRouter 跨设备）

**代码证据**（`core/openclawd.py` 文件头部注释）：
```python
# 设计原则:
#   1. 单例模式 — 全局唯一主体核心
#   2. 懒加载 — 所有模块按需导入，避免循环依赖
#   3. 容错降级 — 任何模块不可用时自动降级
#   4. 统一响应 — 所有方法返回标准 dict 格式，携带 state_continuum /
#                 execution_path / runtime_domain / runtime_session_id
```

### 1.3 OpenClawd 是什么

OpenClawd 是整套系统的**认知与执行核心**（subject core），不是一个外挂模块或并行主体。

关键特性：
- 是**唯一**拥有路由权威的实体 —— 只有 OpenClawd 决定某个请求走本地执行还是跨设备分发
- 在 DesktopPresenceRuntime 的 LIMINAL 阶段内运行，不能绕过
- 拥有 LLM 路由（`MultiLLMRouter`）、多模态融合（`MultimodalBus`）、认知连续（`ContinuumOrchestrator`）
- 通过 `CommandRouter` 将跨设备任务封装为 `TaskEnvelope`/`CommandEnvelope` 后发到网关

### 1.4 DesktopPresenceRuntime 是什么

DesktopPresenceRuntime 是**主体在 Windows 桌面上的运行时外壳**（runtime shell）。

关键特性：
- 拥有主体的**三态生命周期**（TriState：SILENT/LIMINAL/MANIFEST）
- 生成每次请求的 `runtime_session_id`（关联 ID，传递到所有下游模块）
- 拥有连续主机感知（`MultimodalIngressBus` → `PerceptionFrame` 对象）
- 不是主体本身，是主体在桌面上的"外衣"

注意：三态生命周期与以下两个状态系统**不是同一件事**：
- Continuum 姿态（`tri_state_phase` + `runtime_domain`）— 由 OpenClawd 内部 ContinuumOrchestrator 管理
- UI 外壳状态（DORMANT / ISLAND / SIDESHEET / FULLAGENT）— 桌面呈现模式，在 `system_integration/` 中管理

### 1.5 Android 是什么

Android 不是一个单纯的受控终端，而是系统中**真实的分布式运行时节点**（distributed runtime node）。

Android 侧（`ufo-galaxy-android`，Kotlin）真实承担：
- WebSocket 实时双向通信（`GalaxyWebSocketClient`）
- 本地感知（截屏 → PerceptionFrame）
- 本地规划（`LlamaCppPlannerService` → MobileVLM V2-1.7B JNI 推理）
- 本地基础（`NcnnGroundingService` → SeeClick NCNN JNI 推理）
- 本地 GUI 自动化执行（无障碍服务）
- 完整本地循环（`LocalLoopExecutor`：perceive → plan → ground → act）
- 离线任务队列（`OfflineTaskQueue`）
- 断线重连（`GalaxyWebSocketClient` reconnect logic）
- 降级梯队（`PlannerFallbackLadder`、`GroundingFallbackLadder`）

### 1.6 为什么这不是单向"电脑控制手机"系统

单向遥控系统的特征是：主控端发指令 → 被控端执行 → 返回结果。

Galaxy 系统的实际架构有本质不同：

1. **Android 有自己的本地认知循环**：当 `inference_mode=local` 时，Android 可以独立执行 perceive → plan → ground → act，不需要每一步都请求 V2 中心
2. **V2 中心可以向 Android 查询能力**：通过设备注册（`DeviceRegistry`）和能力协商（`CapabilityRegistry`）决定哪些设备适合执行哪些任务
3. **Android 向 V2 反馈执行事件**：`AndroidCanonicalExecutionEventOwner.kt` 负责将执行阶段事件（规划中/落地中/执行中/停滞检测/门控决策等）上报到 V2
4. **中心和端侧有互相触发能力**：V2 的 hybrid 执行路径可以同时启动本地和跨设备两条执行链
5. **Android 有远程回传托管能力**：`FallbackConfig.enableRemoteHandoff`（默认关闭，但接口存在）允许 Android 本地失败时将任务上报中心接管

所以，更准确的描述是：

> **这是一个以 V2/OpenClawd 为中心治理权威的多设备能力编排系统。中心是调度权威，但 Android 端是真实具备独立认知执行能力的运行时节点，两者之间存在结构性双向信息流。**

---

<a name="section-2"></a>
## 第二节：多设备 / 双向 / 多向协作现实说明

### 2.1 已经真实存在的多设备参与能力

以下内容均来自代码实现，不是设计意图：

**V2 侧已有的多设备基础设施**（`core/device_registry.py`、`core/device_communication.py`）：
- `DeviceRegistry`：设备注册、索引、发现（按能力 tag 查询设备）
- `DeviceCommunication`：统一通信层，支持 WebSocket / HTTP Long Polling / MQTT / ADB
- `MessageType` 枚举：COMMAND / RESPONSE / ACK / HEARTBEAT / STATUS / EVENT / ERROR / STREAM_* / WAKE_EVENT / SESSION_MIGRATE / SESSION_RESTORE
- `device_registry.get_devices_by_tag(tag)` — 按能力查找设备
- `device_registry.negotiate_capability(device_id, capability)` — 能力协商

**V2 侧已有的跨设备执行链**（`core/cross_device_execution_chain.py`）：
- `OpenClawd` → `CommandRouter` → `TaskEnvelope` → 网关 → 设备 → `ResultEnvelope` → 反馈
- 跨设备执行与本地执行是**同等级别的两条规范执行链**，任意一条都是 first-class

**V2 侧已有的 Android 执行面**（`core/flow_level_operator_surface.py`）：
- `AndroidExecutionPhase` 枚举：planning / grounding / execution / replan / stagnation / gate_decision / takeover / collaboration / completed / failed / unknown
- `FlowOperatorProjection`：中心侧对 Android 委派执行流的规范化投影视图
- `AndroidCanonicalExecutionEvent`：V2 侧接收 Android 执行事件的数据结构

**Android 侧已有的双向通信能力**（`GalaxyWebSocketClient.kt`）：
- 建立和维持 WS 连接到 V2 网关
- 接收 V2 下发的任务指令（TaskEnvelope）
- 上报执行事件和结果到 V2

### 2.2 "多入口"、"多参与者"、"跨设备执行"、"双运行时"的代码现实

**多入口**（Multiple Entry Points）
- V2 侧：`/api/v1/chat`（对话）、`/api/v1/agent`（Agent 调度）、`/api/v1/command`（命令路由）、`/api/v1/ai`（AI 意图理解）
- Android 侧：本地 GUI 触发、WS 收到任务触发、本地 loop 自主触发
- 所有入口最终都汇聚到 OpenClawd 的执行决策中心

**多参与者**（Multiple Participants）
- V2/OpenClawd — 认知权威和调度权威
- Android 设备 — 执行节点，注册到设备注册表，上报能力
- Galaxy Gateway — 传输基础设施，不做规划决策
- NATS 总线（`core/nats_bus.py`）— 工作节点心跳和注册的消息中间件

**跨设备执行**（Cross-Device Execution）
代码证据（`core/cross_device_execution_chain.py`）：
```
OpenClawd (路由权威)
    └─ CommandRouter (唯一跨设备路由器)
          └─ TaskEnvelope / CommandEnvelope (可序列化任务合约)
                └─ Gateway substrate (执行管道，不做规划)
                      └─ Worker / Device / Node (执行者)
                            └─ ResultEnvelope (归一化结果)
                                  └─ OpenClawd 反馈 → 投影 / 审计 / 记忆回流
```

**双运行时**（Dual Runtime）
当前的双运行时是 V2 中心运行时 + Android 本地运行时：
- `center` 模式：Android 的规划和落地都交给 V2 侧（`AndroidVLMService`）处理，Android 只负责执行和反馈
- `local` 模式：Android 本地自己做 plan（`LlamaCppPlannerService`）和 ground（`NcnnGroundingService`），V2 作为结果接收方
- `hybrid` 模式：两者协同（接口已有，Android 侧 `FallbackConfig.enableRemoteHandoff` 控制）

### 2.3 已经是双向或多向的部分

以下是**代码层面已经实现的双向/多向流**：

| 方向 | 内容 | 代码证据 |
|------|------|----------|
| V2 → Android | 任务下发（TaskEnvelope） | `CommandRouter` → WS → Android |
| Android → V2 | 执行结果上报（ResultEnvelope） | `GalaxyWebSocketClient.sendResult()` |
| Android → V2 | 心跳保活 | `GalaxyWebSocketClient` heartbeat |
| Android → V2 | 设备注册（startup） | `RuntimeController` → WS register message |
| V2 → Android | 配置推送（startup） | `RemoteConfigFetcher.fetchConfig()` from `/api/v1/config` |
| Android → V2 | 执行事件上报 | `AndroidCanonicalExecutionEventOwner.kt`（WS 消息管道，见 Gap 说明） |

### 2.4 当前仍是中心权威而非完全对等的部分

以下是**仍由 V2 中心单向权威决定**的部分，Android 节点不能绕过或覆盖：

- **调度决策**：哪个设备执行哪个任务 — 由 OpenClawd `_determine_execution_path` 决定
- **路由策略**：跨设备 vs 本地 vs 混合 — 由 OpenClawd 决定
- **LLM 路由**：使用哪个 AI 提供商和模型 — 由 `MultiLLMRouter` 决定
- **任务生命周期权威**：`CanonicalTaskRuntime`（V2 侧）是任务生命周期的真相来源
- **配置权威**：`ConfigService`（V2 侧 `core/config_schema.py`）定义 `android.inference_mode` 的合法值，Android 通过 `RemoteConfigFetcher` 在启动时拉取

**正确理解**：这套系统的分布式不是完全去中心化的对等网络，而是**中心治理式分布式**——中心持有调度权威，端侧持有执行能力，端侧自治程度由中心设定的配置决定。

---

<a name="section-3"></a>
## 第三节：Android 当前真实地位说明

### 3.1 Android 是真实的运行时节点

旧的负面判断（"Android 本地 AI 没有真正接上"）已经被最新代码推翻。当前现实是：

**本地推理库已进入构建**（`app/build.gradle`）：
```gradle
// llama.cpp Android JNI bindings — MobileVLM GGUF 推理 (libllama.so)
implementation 'com.github.ggerganov:llama.cpp:b4833'

// NCNN Android 推理库 — SeeClick 落地 (libncnn.so)
implementation 'com.github.nihui:ncnn-android-vulkan:20240410'
```

**真实 JNI 实现（非 stub）**（`planner/LlamaCppPlannerService.kt`，`grounding/NcnnGroundingService.kt`）：
```kotlin
// LlamaCppPlannerService — 真实 JNI，映射 libllama.so 中的 C 符号
private external fun nativeLoadModel(path: String, threads: Int): Long
private external fun nativeCompletion(handle: Long, prompt: String, ...): String?

// NcnnGroundingService — 真实 JNI，映射 libncnn.so 中的 C 符号
private external fun nativeLoadModel(paramPath: String, binPath: String): Long
private external fun nativeGround(handle: Long, screenshotBase64: String, ...): FloatArray?
```

**应用启动时真实接入**（`UFOGalaxyApplication.kt`）：
```kotlin
// 加载原生库
NativeInferenceLoader.loadAll()

// 根据库可用性决定 planner 实现
plannerService = if (NativeInferenceLoader.isLlamaCppAvailable()) {
    LlamaCppPlannerService(modelPath = modelAssetManager.mobileVlmPath, ...)
} else {
    DegradedPlannerService.forState(...)  // 降级，不是崩溃
}

// 根据库可用性决定 grounder 实现
groundingService = if (NativeInferenceLoader.isNcnnAvailable()) {
    NcnnGroundingService(modelParamPath = modelAssetManager.seeClickParamPath, ...)
} else {
    DegradedGroundingService.forState(...)  // 降级，不是崩溃
}
```

### 3.2 本地循环已真实闭环

当前本地循环（`LocalLoopExecutor`）的执行路径：

```
perceive（截屏 → PerceptionFrame）
    │
    ↓
plan（LlamaCppPlannerService → MobileVLM V2-1.7B-Q4_K JNI → PlanResult）
    │
    ↓
ground（NcnnGroundingService → SeeClick NCNN JNI → GroundingResult {x, y, confidence}）
    │
    ↓
act（无障碍服务执行点击/滑动/输入等 GUI 自动化操作）
    │
    ↓
（下一步或结束）
```

**StagnationDetector** 负责检测循环卡住（同一状态重复出现），**PlannerFallbackLadder** 和 **GroundingFallbackLadder** 提供多级降级路径。

### 3.3 center 模式 vs local 模式 vs hybrid 模式

| 模式 | 配置 | Android 侧行为 | V2 侧行为 |
|------|------|--------------|---------|
| `center` | `android.inference_mode=center`（默认） | Android 截屏 → 上传 V2 → V2 做规划和落地 → 下发动作 | V2 承担所有 AI 推理（通过 `AndroidVLMService`） |
| `local` | `android.inference_mode=local` | Android 本地做 plan + ground + act，V2 只接收结果 | V2 作为观察者和结果接收方 |
| `hybrid` | `android.inference_mode=hybrid` | 本地先尝试，失败后远程回传（`FallbackConfig.enableRemoteHandoff`） | V2 作为本地失败时的托管接管方 |

**重要**：默认模式是 `center`。`local` 和 `hybrid` 需要 operator 明确配置。

### 3.4 Android 真实能做什么（当前代码状态）

**已经真实可用的能力**：
- ✅ WebSocket 双向通信（含离线队列和重连）
- ✅ 截屏感知
- ✅ 无障碍服务 GUI 自动化执行
- ✅ 本地推理运行时（llama.cpp + NCNN，已进 APK 构建）
- ✅ 本地规划（LlamaCppPlannerService，真实 JNI，非 stub）
- ✅ 本地落地（NcnnGroundingService，真实 JNI，非 stub）
- ✅ 完整本地循环（perceive → plan → ground → act）
- ✅ 降级梯队（PlannerFallbackLadder / GroundingFallbackLadder）
- ✅ 离线任务队列（`OfflineTaskQueue`，断线时缓存，重连后回放）
- ✅ 模型下载和校验（`ModelDownloader`，MobileVLM SHA-256 已硬编码）

**还需要首次运行准备的内容**：
- ⚠️ MobileVLM 模型下载（~900 MB，HuggingFace，SHA-256 预置已有）
- ⚠️ SeeClick NCNN 模型下载（~450 MB，首次下载后计算并持久化 checksum）
- ⚠️ Operator 需明确将 `android.inference_mode` 切换为 `local` 才会走本地推理路径
- ⚠️ 设备需有足够存储空间（MobileVLM: ~950 MB，SeeClick: ~450 MB）

### 3.5 模型完整性状态

| 模型 | Hash 状态 | 执行策略 |
|------|----------|---------|
| MobileVLM V2-1.7B GGUF | ✅ 硬编码预置：`MOBILEVLM_SHA256 = "15d4bd09..."` | 每次下载后强制校验 |
| SeeClick NCNN param | ⚠️ 首次下载后计算并持久化到 `.checksums.json` | 首次无预置 hash；之后校验 |
| SeeClick NCNN weights | ⚠️ 同上 | 同上 |

---

<a name="section-4"></a>
## 第四节：操作面板应如何理解的系统层说明

### 4.1 操作面板不是单机状态板

错误的理解方式：
> "操作面板就是显示 V2 这台电脑现在是否在跑、哪个 API key 有没有配好的状态板"

正确的理解方式：
> "操作面板是整个 Galaxy 中心治理型分布式智能体系统的全生态视图，呈现中心节点 + 所有参与设备节点的统一当前状态和任务流图"

原因来自代码设计本身：
1. `core/operator_surface.py` 中的 `OperatorSnapshot` 已经包含：`active_tasks`（活跃任务）、`online_devices`（在线设备）、`topology_node_count`（拓扑节点数）、`capability_providers`（能力提供者）—— 这不是单机指标
2. `core/flow_level_operator_surface.py` 中的 `FlowOperatorProjection` 专门跟踪**委派给 Android 的执行流**的阶段状态 —— 这是跨设备的
3. `DeviceRegistry` 和 `CapabilityRegistry` 本身就是多设备感知的基础设施

### 4.2 操作面板应包含的四个功能面

基于实际代码中已存在的数据结构和 API，操作面板应当包含以下四个层面：

---

#### 面板 A：配置 / 设置面（Config/Setup Panel）

**数据真相来源**：V2 侧（`core/config_schema.py`，`core/config_service.py`，`runtime/config.json`，`runtime/secrets.env`）

**核心展示内容**：

| 展示项 | 来源代码 | 读写接口 |
|--------|---------|---------|
| LLM 提供商开关（openai/anthropic/gemini/deepseek/groq/openrouter/oneapi） | `CONFIG_KEYS` in `core/config_schema.py` | `GET/POST /api/v1/config` |
| 每个提供商的 API Key 是否已配置（has_key，不显示值） | `ConfigValidationResult.provider_statuses` from `ConfigService.validate()` | `ConfigService.set_secret()` |
| Android 推理模式（center / local / hybrid） | `android.inference_mode` in `VALID_ANDROID_INFERENCE_MODES` | `POST /api/v1/config` |
| 多模态策略（strict / prefer / allow_fallback） | `routing.native_multimodal_policy` in `VALID_NATIVE_MM_POLICIES` | `POST /api/v1/config` |
| 网关 URL / Android 网关 URL / NATS URL / ATS URL | `network.*` in `CONFIG_KEYS` | `POST /api/v1/config` |
| 功能标志（enable_continuum, enable_task_dag, enable_desktop_presence_runtime 等） | `config.json` 中各 enable_* 标志 | 文件编辑 + 重启 |

**特殊语义**（来自 `core/config_schema.py`）：
- 修改 `android.inference_mode` 需要重新连接 Android（`requires-reconnect`）
- 修改 `enable_continuum` / `enable_desktop_presence_runtime` 需要重启 V2（`requires-restart`）
- 修改 `BuildConfig.GALAXY_SERVER_URL` 需要重新构建 APK（`requires-android-rebuild`）

---

#### 面板 B：运行时监控面（Runtime Monitoring Panel）

**数据真相来源**：V2 中心侧（运行时投影）+ Android 侧（必须通过 WS 上报）

**核心展示内容**：

| 展示项 | 来源代码 | 当前接口 |
|--------|---------|---------|
| 主体三态（SILENT/LIMINAL/MANIFEST） | `DesktopPresenceRuntime._state` → `TriState` enum | ⚠️ 未暴露，需新增 |
| NATS 连接状态（is_connected / get_stats） | `core/nats_bus.py` → `NATS_FABRIC_CARRIER_AUTHORITY` | ⚠️ 未暴露，需新增 |
| 心跳周期（is_enabled / _cycle_count / 当前 tier） | `core/openclawd_heartbeat.py` → `HeartbeatScheduler` | ⚠️ 未暴露，需新增 |
| 在线设备列表（presence_state / is_ready / last_seen / capability_tags） | `DevicePresenceSummary` in `core/operator_surface.py` | `GET /api/v1/operator` |
| 活跃任务列表（TaskInspection） | `OperatorSnapshot.active_tasks` | `GET /api/v1/operator` |
| 每个 LLM 提供商健康状态（HEALTHY/DEGRADED/DOWN / latency_avg_ms / error_count） | `ProviderConfig.status` in `core/multi_llm_router.py` | ⚠️ 未暴露，需新增 |
| Android 就绪状态（modelReady / accessibilityReady / overlayReady） | `ReadinessState` in Android `UFOGalaxyApplication` | ⚠️ Android 未上报到 V2 |
| Android 本地推理库状态（llamaCppAvailable / ncnnAvailable） | `NativeInferenceLoader` 结果 | ⚠️ Android 未上报到 V2 |

---

#### 面板 C：执行控制面（Execution Control Panel）

**数据真相来源**：V2（任务级）+ V2+Android 联合（委派执行流级）

**核心展示内容**：

| 展示项 | 来源代码 | 当前接口 |
|--------|---------|---------|
| 当前 Android 执行阶段（planning/grounding/execution/stagnation/gate_decision...） | `AndroidExecutionPhase` in `core/flow_level_operator_surface.py` | ⚠️ 无 REST 端点 |
| 活跃委派流详情（FlowOperatorProjection） | `FlowLevelOperatorSurface.inspect_flow()` | ⚠️ 无 REST 端点，需 `GET /api/v1/operator/flows/{id}` |
| 路由决策（transport_strategy / effective_path / admissibility_verdict） | `RouteInspection` in `core/operator_surface.py` | `GET /api/v1/operator` |
| 失败域和重试（failure_domain / retry_count / fallback_triggered） | `FailureDomainInspection` in `core/operator_surface.py` | `GET /api/v1/operator` |
| 任务谱系（ancestor_chain / children / retry_chain / timeline） | `LineageInspection` in `core/operator_surface.py` | `GET /api/v1/operator` |
| 恢复状态（is_recovered / recovery_disposition / current_owner） | `RecoveryInspection` in `core/operator_surface.py` | `GET /api/v1/operator` |
| Android 降级梯队当前层级（PlannerFallbackLadder / GroundingFallbackLadder） | Android `com.ufo.galaxy.local.*` | ⚠️ Android 未上报到 V2 |
| 离线队列深度（OfflineTaskQueue 当前积压数） | Android `com.ufo.galaxy.network.OfflineTaskQueue` | ⚠️ Android 未上报到 V2 |

---

#### 面板 D：模型 / 运行时就绪状态面（Model & Runtime Readiness Panel）

**数据真相来源**：Android 侧（模型状态）+ V2 侧（就绪矩阵）

**核心展示内容**：

| 展示项 | 来源代码 | 当前接口 |
|--------|---------|---------|
| V2 就绪矩阵（ReadinessMatrix：transport/execution/capability/protocol/continuity 各维度） | `ReadinessMatrix` in `core/runtime_readiness_matrix.py` | ⚠️ 无 REST 端点，需 `GET /api/v1/readiness` |
| Android 模型状态（MobileVLM 是否已下载 / SHA-256 是否通过校验） | `ModelManifest` + `ModelAssetManager` in Android | ⚠️ Android 未上报到 V2 |
| SeeClick 模型状态（param + bin 是否已下载 / checksum 是否完成） | `ModelManifest.forKnownModel(MODEL_ID_SEECLICK)` | ⚠️ Android 未上报到 V2 |
| 本地循环是否就绪（LocalLoopReadiness） | `LocalLoopReadinessProvider` in Android | ⚠️ Android 未上报到 V2 |
| 模型兼容性（CompatibilityResult：Compatible/Incompatible/Unknown） | `ModelManifest.checkCompatibility()` in Android | ⚠️ Android 未上报到 V2 |
| 每个 LLM 提供商的配置就绪状态（enabled + has_key） | `ProviderStatus` from `ConfigService.validate()` | `GET /api/v1/config` |
| 端口映射（PortConfig，130 节点） | `PortConfig` + `config/unified_ports.yaml` | ⚠️ 无 REST 端点 |

### 4.3 四个面板与代码真相来源的对应关系总结

```
面板 A（配置/设置）
    └─ 真相来源：V2 → core/config_schema.py + core/config_service.py
    └─ 接口：GET/POST /api/v1/config（已存在）

面板 B（运行时监控）
    ├─ V2 侧 → core/operator_surface.py（GET /api/v1/operator，部分已暴露）
    ├─ V2 侧 → core/nats_bus.py, core/openclawd_heartbeat.py（未暴露）
    └─ Android 侧 → ReadinessState, NativeInferenceLoader（未上报到 V2）

面板 C（执行控制）
    ├─ V2 侧 → core/operator_surface.py（GET /api/v1/operator，部分已暴露）
    └─ V2+Android → core/flow_level_operator_surface.py（架构已有，REST 端点未定义）

面板 D（模型/运行时就绪）
    ├─ V2 侧 → core/runtime_readiness_matrix.py（无 REST 端点）
    └─ Android 侧 → ModelManifest, LocalLoopReadiness（未上报到 V2）
```

---

<a name="section-5"></a>
## 第五节：当前未完成项清单

### 5.1 已经实质性完成的部分

以下内容已经在代码层面真实存在且完整：

| 内容 | 代码证据 |
|------|---------|
| V2 中心认知核心（OpenClawd + DesktopPresenceRuntime 完整链路） | `core/openclawd.py`、`core/desktop_presence_runtime.py` |
| 跨设备执行链（TaskEnvelope → Gateway → Android → ResultEnvelope → 反馈） | `core/cross_device_execution_chain.py` |
| 本地执行链（DecisionExecutor → Windows API 执行） | `core/local_execution_chain.py` |
| LLM 多提供商路由（openai/anthropic/gemini/deepseek/groq/openrouter/oneapi） | `core/multi_llm_router.py` |
| 设备注册和能力协商基础设施 | `core/device_registry.py`、`core/capability_registry.py` |
| 操作面投影数据结构（OperatorSnapshot、TaskInspection 等所有 inspect_* 方法） | `core/operator_surface.py` |
| 委派执行流投影数据结构（FlowOperatorProjection、AndroidExecutionPhase） | `core/flow_level_operator_surface.py` |
| 配置服务（ConfigService、ConfigStore、ConfigSchema） | `core/config_schema.py`、`core/config_service.py` |
| 就绪矩阵（ReadinessMatrix、ReadinessDimension） | `core/runtime_readiness_matrix.py` |
| Android 本地推理库接入（llama.cpp + NCNN 进入 APK 构建） | `app/build.gradle` |
| Android 真实 JNI 实现（LlamaCppPlannerService + NcnnGroundingService） | `planner/LlamaCppPlannerService.kt`、`grounding/NcnnGroundingService.kt` |
| Android 应用启动时真实接线（UFOGalaxyApplication.onCreate() 完整接线） | `UFOGalaxyApplication.kt` |
| Android 本地完整循环（perceive → plan → ground → act，含降级和重连） | `LocalLoopExecutor.kt`、`PlannerFallbackLadder.kt`、`GroundingFallbackLadder.kt` |
| Android 模型下载和 SHA-256 校验（MobileVLM 硬编码 hash） | `model/ModelAssetManager.kt`、`model/ModelDownloader.kt` |
| Android WebSocket 双向通信（含离线队列和断线重连） | `network/GalaxyWebSocketClient.kt`、`network/OfflineTaskQueue.kt` |

### 5.2 V2 侧还未完全收口的 operator 面问题

以下条目来自对 `core/api_routes.py` 和 `core/operator_surface.py` 的实际检查：

| Gap 编号 | 问题描述 | 代码证据 | 优先级 |
|---------|---------|---------|--------|
| M-V2-01 | 主体三态（SILENT/LIMINAL/MANIFEST）不在任何 REST 响应中 | `DesktopPresenceRuntime._state` 存在但未序列化到 API | 高 |
| M-V2-02 | NATS 连接状态（is_connected/get_stats）没有专属 REST 端点 | `nats_bus.py` 方法存在，无路由 | 高 |
| M-V2-03 | 每个 LLM 提供商的运行时健康（status/latency/errors）未暴露到 operator API | `ProviderConfig.status/latency_avg_ms/error_count` 在 `MultiLLMRouter` 中，未进入 `GET /api/v1/operator` 响应 | 高 |
| M-V2-04 | ReadinessMatrix 无 REST 端点 | `ReadinessMatrix.to_dict()` 存在，无 `/api/v1/readiness` 路由 | 高 |
| M-V2-05 | HeartbeatScheduler 状态不可观测 | `_cycle_count`、tier 升级历史不在任何端点 | 中 |
| M-V2-06 | FlowLevelOperatorSurface.inspect_flow() 无 REST 端点 | 投影方法存在，无 `/api/v1/operator/flows/{flow_id}` 路由 | 高 |
| M-V2-07 | PortConfig 端口映射无 REST 端点 | `PortConfig.list_node_ports()` 存在，无路由（130 节点映射） | 低 |
| M-V2-08 | RoutingDecision 未包含在 TaskInspection 中 | LLM 路由决策（provider/model/reason/alternatives）不在操作面投影中 | 中 |

**缺少的端点清单**（基于现有模块推断必要路由）：
- `GET /api/v1/readiness` → `ReadinessMatrix.to_dict()`
- `GET /api/v1/operator/flows` → `FlowLevelOperatorSurface` 活跃流列表
- `GET /api/v1/operator/flows/{flow_id}` → `FlowOperatorProjection`
- `GET /api/v1/operator/llm` → `ProviderConfig` 运行时健康列表
- `GET /api/v1/operator/nats` → NATS 连接状态
- `GET /api/v1/operator/heartbeat` → HeartbeatScheduler 周期状态
- `GET /api/v1/ports` → PortConfig 节点端口映射

### 5.3 Android 侧还未上报到 V2 的状态

以下条目来自对 `UFOGalaxyApplication.kt`、`GalaxyWebSocketClient.kt` 和 `core/device_communication.py` 的检查：

| Gap 编号 | 未上报内容 | Android 代码位置 | V2 侧准备情况 |
|---------|----------|----------------|-------------|
| M-AN-01 | NativeInferenceLoader 结果（llamaCppAvailable / ncnnAvailable） | `UFOGalaxyApplication.onCreate()` 日志 | V2 有 `FlowLevelOperatorSurface` 但无法接收此状态 |
| M-AN-02 | ReadinessState（modelReady / accessibilityReady / overlayReady） | `UFOGalaxyApplication.readinessState` | V2 未收到结构化上报 |
| M-AN-03 | LocalLoopReadiness（本地循环是否就绪） | `LocalLoopReadinessProvider` | V2 无法查询 |
| M-AN-04 | 模型清单（modelId / modelVersion / checksum / runtimeType） | `ModelManifest.forKnownModel()` | V2 不知道 Android 在用哪个模型 |
| M-AN-05 | CompatibilityResult（模型与 runtime 兼容性） | `ModelManifest.checkCompatibility()` | V2 无法知道兼容性状态 |
| M-AN-06 | LocalLoopConfig 活跃值（maxSteps / stepTimeoutMs / fallback flags） | `UFOGalaxyApplication.localLoopConfig` | V2 无法检查 Android 用的 loop 配置 |
| M-AN-07 | AndroidExecutionPhase 作为完整的 V2 可读信号 | `AndroidCanonicalExecutionEventOwner.kt` 存在，WS 消息管道未确认完整 | V2 侧 `FlowLevelOperatorSurface` 已准备好接收 |
| M-AN-08 | StagnationDetector 事件 | `com.ufo.galaxy.local.StagnationDetector` | 未以规范事件形式上报 V2 |
| M-AN-09 | 降级梯队当前层级（Planner / Grounding fallback tier） | `PlannerFallbackLadder`、`GroundingFallbackLadder` | V2 无法看到 Android 在哪一级降级上 |
| M-AN-10 | OfflineTaskQueue 队列深度 | `com.ufo.galaxy.network.OfflineTaskQueue` | V2 不知道 Android 积压了多少任务 |
| M-AN-11 | RuntimeHealthSnapshot | `com.ufo.galaxy.runtime.RuntimeHealthSnapshot` | V2 未接收 |

### 5.4 协议层面的结构性 Gap

**能力通告消息类型缺失**（`core/device_communication.py` → `MessageType` 枚举）：

当前 `MessageType` 中存在 `HEARTBEAT`（心跳）、`WAKE_EVENT`（唤醒事件）等，但没有专门的**能力通告**（capability advertisement）消息类型来传输：
- Android 就绪状态（ReadinessState）
- 模型清单（ModelManifest identity）
- 本地推理库可用性（NativeInferenceLoader result）
- 本地循环就绪（LocalLoopReadiness）
- 运行时健康快照（RuntimeHealthSnapshot）

这是目前 Android → V2 状态同步的最核心协议层 gap，也是 operator 面板要想展示 Android 真实状态的最根本前置条件。

### 5.5 配置同步的部分完成状态

| 同步方向 | 内容 | 当前状态 |
|---------|------|---------|
| V2 → Android | 网关 URL | ✅ `RemoteConfigFetcher` 在 Android 启动时从 `/api/v1/config` 拉取 |
| V2 → Android | `android.inference_mode` | ⚠️ V2 有 `CONFIG_KEYS` 定义，但 Android 没有对应的强类型枚举；`CROSS_DEVICE_ENABLED` BuildConfig 标志部分映射 |
| V2 → Android | Planner 参数（max_tokens 等） | ✅ BuildConfig 编译时常量 + AppSettings 运行时值，`LocalLoopConfig.from(settings)` |
| Android → V2 | 当前实际使用的网关 URL | ⚠️ V2 无法验证 Android 实际在用哪个 URL |
| Android → V2 | 本地 inference_mode 是否真正激活 | ⚠️ V2 只能推断，无法确认 |

### 5.6 操作员体验还未完成的收口

| 问题 | 影响 |
|------|------|
| 没有统一的 operator console UI | 技术人员可操作，但没有真正的一站式控制台 |
| 没有 Android 本地模型下载进度和状态的 GUI | 首次配置 `local` 模式对非技术人员来说是盲操作 |
| 没有首次配置向导（gateway URL / API key / inference mode 一体化设置） | 上手成本高，容易配错 |
| 多设备状态和任务链没有统一可视化 | Operator 无法一眼看清系统全局状态 |

---

<a name="section-6"></a>
## 第六节：对未来设备生态扩展能力的准确说明

### 6.1 系统架构哲学不是 Android 专属的

从代码可以直接看到，这套系统在设计上考虑了多类设备。

**`core/device_types.py` 中的 `DeviceType` 枚举**（这是单一真相来源）：
```python
class DeviceType(str, Enum):
    # ── 平台类型 ──
    ANDROID = "android"
    IOS = "ios"
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"
    BROWSER = "browser"
    CLOUD = "cloud"
    # ── 专用设备类型 ──
    DRONE = "drone"           # 无人机
    PRINTER_3D = "printer_3d" # 3D 打印机
    ROBOT = "robot"           # 机器人
    CAMERA = "camera"
    SENSOR = "sensor"
    ACTUATOR = "actuator"
    DISPLAY = "display"
    SPEAKER = "speaker"
    IOT = "iot"
    EMBEDDED = "embedded"
    # ── 通信/接口类设备 ──
    AUDIO = "audio"
    SERIAL = "serial"
    BLE = "ble"
```

这不是未来可能性的列表，而是**当前代码中已经定义的设备类型体系**。

### 6.2 通用抽象基础设施

以下是已经写入代码的通用（设备无关）基础设施：

**设备注册与发现**（`core/device_registry.py`）：
- `DeviceRegistry.register(device_id, device_type, name, capabilities)` — 接受任意设备类型和能力列表
- `DeviceRegistry.get_devices_by_tag(tag)` — 按能力 tag 查询所有满足的设备（设备无关）
- `DeviceRegistry.negotiate_capability(device_id, capability)` — 能力协商（设备无关）
- 设备信息结构（device_id, device_type, name, status, capabilities, last_seen）对任意设备类型通用

**能力注册与匹配**（`core/capability_registry.py`）：
- `DeviceCapabilitySummary` — 任意设备的序列化能力摘要
- `device_matches_capabilities(device_id, required_capabilities)` — 检查任意设备是否满足能力需求
- `get_devices_matching_capabilities(required_capabilities)` — 从所有注册设备中找到满足需求的设备列表

**消息协议**（`core/device_communication.py`，`galaxy_gateway/protocol/aip_v3.py`）：
- `MessageType` 枚举中的 COMMAND / RESPONSE / ACK / HEARTBEAT / WAKE_EVENT 等 — 协议层与设备类型无关
- `AIPDeviceType` 在 AIP v3.0 协议中定义了 30+ 设备子类型（见 `DeviceType` 的注释引用）
- `DevicePlatform` 枚举用于路由决策，设备无关

**跨设备执行链**（`core/cross_device_execution_chain.py`）：
- `TaskEnvelope` / `CommandEnvelope` / `ResultEnvelope` — 任意远端设备执行任务的通用合约
- `CommandRouter` — 路由到任意注册设备节点，不是 Android 专用
- Gateway substrate 是执行管道，不包含任何 Android 特定逻辑

**设备策略**（`core/device_policy.py`，`core/cross_device_policy/`）：
- 设备分派策略、能力路由策略 — 按注册设备的能力标签决定，设备类型无关

### 6.3 哪些部分会需要设备特定的 runtime adapter

以下内容是 **Android 特定的**，扩展到其他设备类型时需要新写对应适配器：

| Android 特定部分 | 用途 | 其他设备需要的对应物 |
|----------------|------|-----------------|
| `LlamaCppPlannerService.kt` | 本地 MobileVLM 推理 | 其他设备需要自己的本地规划 runtime（如有需要） |
| `NcnnGroundingService.kt` | SeeClick NCNN 落地 | 其他设备需要自己的感知-动作映射（如机器人需要运动规划而非点击坐标） |
| `LocalLoopExecutor.kt` | perceive → plan → ground → act 本地循环 | 其他设备需要自己的本地自主循环逻辑 |
| `AccessibilityService.kt`（无障碍服务） | GUI 自动化执行 | 其他设备需要自己的执行接口（如串口控制、ROS 话题发布等） |
| `ModelDownloader.kt` / `ModelAssetManager.kt` | 模型下载和管理 | 其他设备需要自己的模型/固件管理 |
| `GalaxyWebSocketClient.kt` 中的 Android 特定注册逻辑 | 设备注册和能力通告 | 其他设备需要实现对应的 WS/MQTT/HTTP 客户端和注册消息 |

**V2 侧需要的通用接入新增**（当前仅 Android 有的）：
- `core/android_runtime_host.py` — Android 运行时宿主
- `core/android_v2_continuity_contract.py` — Android-V2 连续性合约
- 类比扩展：`core/drone_runtime_host.py`、`core/robot_runtime_host.py` 等未来可以按同样模式添加

### 6.4 扩展到其他设备类型的准确理解

**正确的理解**：
> "Galaxy 的通用注册、能力协商、消息协议、跨设备执行链等基础设施已经是设备无关的。扩展到新设备类型需要两件事：(1) 在新设备端写一个 runtime adapter，实现 WS/MQTT/HTTP 通信客户端和能力注册消息；(2) 在 V2 侧（如有必要）添加对应的 runtime host 模块。核心架构不需要大改。"

**错误的夸大**：
> "现在就可以直接把无人机或机器人接进来，没有任何额外工作"

**错误的低估**：
> "系统是 Android 专属的，扩展到其他设备类型需要完全重写"

---

<a name="section-7"></a>
## 第七节：最终中文结论与定性

### 7.1 对整套系统的最终定性

基于对两个仓库当前源码的完整阅读，这套 Galaxy 系统可以被准确定性为：

# **一个真实成立的、中心治理型分布式智能体系统**

它的具体内涵是：

1. **中心节点（V2）是真实的**：`DesktopPresenceRuntime` + `OpenClawd` 构成统一主体，本地执行链和跨设备执行链均为规范第一类执行路径，不是概念稿。

2. **Android 是真实的分布式运行时节点**：拥有完整的本地认知循环（perceive → plan → ground → act），本地推理库（llama.cpp + NCNN）已进入 APK 构建，真实 JNI 实现已接线，不是 stub，不是单纯的被动执行终端。

3. **这不是单向遥控系统**：Android 端有自主执行能力，两侧之间存在双向信息流，中心既是调度权威也是结果接收方。

4. **当前最大剩余问题已不是底层架构缺失**：而是 operator 面的收口和 Android → V2 状态同步协议的补全。核心运行时链路已真实成立，剩余的是让操作员能真正"看见"和"管理"这个系统所需要的 surface 层。

### 7.2 三句话精确摘要

**关于系统本体**：
> V2（OpenClawd + DesktopPresenceRuntime）和 Android 共同构成一个真实可运行的中心治理型分布式智能体系统，两者各自有真实的执行能力，中心持有调度权威，Android 端可以本地自治执行。

**关于 Android 当前状态**：
> Android 本地 AI 推理已经真正接上（llama.cpp + NCNN，真实 JNI），可以走完整的 perceive → plan → ground → act 本地循环；默认配置是 center 模式，切换到 local 模式需要 operator 配置并完成首次模型下载（~1.65 GB）。

**关于当前最大剩余问题**：
> 系统底层架构已经真实成立，当前最大未完成项是 operator 操作面：需要把 V2 侧内部已有的运行时状态（TriState、NATS 状态、LLM 健康、就绪矩阵、流投影）暴露为 REST 端点，以及建立 Android → V2 的能力通告协议来同步 Android 侧的模型状态、就绪状态和执行阶段信号。

### 7.3 操作员最需要知道的三件事

1. **系统已经可以真跑了**：只要配好 gateway URL、API key（center 模式），或配好并下载本地模型（local 模式），系统可以正常运行任务。

2. **Android 本地 AI 能力已存在，但不是默认开启的**：你需要把 `android.inference_mode` 设为 `local`，并完成 Android 侧的模型下载，本地 AI 才会真正生效。

3. **操作面板还不完整，现阶段要用 API 直接查**：`GET /api/v1/operator` 已可以查到活跃任务和在线设备；LLM 健康、Android 侧状态、就绪矩阵等还需要通过计划中的新端点或直接读代码来查。

---

## 附录：代码与结论对照表

| 结论 | 代码证据 |
|------|---------|
| OpenClawd 是主体内核，不是外挂模块 | `core/openclawd.py`：`_determine_execution_path`、`ContinuumOrchestrator`、统一主体架构注释 |
| DesktopPresenceRuntime 是主体外壳 | `core/desktop_presence_runtime.py`：TriState 枚举、session 拥有权、连续感知入口 |
| Android 是真实分布式运行时节点 | `app/build.gradle`：llama.cpp + NCNN 依赖；`LlamaCppPlannerService.kt`：`external fun nativeLoadModel/nativeCompletion`；`UFOGalaxyApplication.kt`：真实接线 |
| 系统支持多种执行路径 | `core/openclawd.py`：`execution_path` = local / cross_device / hybrid / none |
| 设备注册是通用的，不是 Android 专属 | `core/device_registry.py`：通用 `register(device_id, device_type, ...)` API |
| DeviceType 枚举包含无人机/机器人等 | `core/device_types.py`：DRONE / ROBOT / PRINTER_3D / SENSOR / ACTUATOR / IOT 等 |
| 操作面投影层已存在但未完全暴露 | `core/operator_surface.py`：`OperatorSurface`、`OperatorSnapshot`；`core/flow_level_operator_surface.py`：`FlowLevelOperatorSurface`、`FlowOperatorProjection` |
| Android 状态未上报到 V2 | `core/device_communication.py`：`MessageType` 枚举中无 capability advertisement 类型；Android `UFOGalaxyApplication.readinessState` 未发送给 V2 |
| MobileVLM SHA-256 已硬编码 | `model/ModelAssetManager.kt`：`MOBILEVLM_SHA256 = "15d4bd09..."` |
| SeeClick checksum 首次下载后计算 | `model/ModelAssetManager.kt`：`SEECLICK_SHA256 = null`、`.checksums.json` 持久化 |

---

*本文件所有结论均直接来源于两个仓库的当前源码。不依赖任何历史审查文档、设计文档或旧结论。*

*Galaxy System · 双仓联合认知审查 · 2026-05-02*
