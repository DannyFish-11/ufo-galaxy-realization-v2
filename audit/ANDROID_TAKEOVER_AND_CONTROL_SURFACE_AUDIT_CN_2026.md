# Android 跨设备接管能力与控制面完成度审查 · 2026

> **审查方法论**：本文件完全基于对两个代码仓库当前源码的直接读取与代码事实推断，不依赖任何历史审查文件、设计文档或旧结论。所有判断均追溯到具体文件名、类名、函数名和常量名。
>
> **审查仓库**：
> - `DannyFish-11/ufo-galaxy-realization-v2`（V2 中心节点 — Python/FastAPI）
> - `DannyFish-11/ufo-galaxy-android`（Android 运行时节点 — Kotlin）
>
> **审查日期**：2026-05-04
>
> **本文档专门回答两个问题**：
> 1. Android 开启跨设备模式后，到底能不能接管整个系统？
> 2. 当前页面 / 操作面 / 控制面的真实完成度是什么？

---

## 目录

1. [Android 开启跨设备后到底能做到什么](#section-1)
2. [Android 还不能接管什么](#section-2)
3. [V2 目前仍掌握的中心权威清单](#section-3)
4. [当前页面 / 操作面 / 控制面已经具备的部分](#section-4)
5. [当前页面 / 操作面 / 控制面仍未完成的部分](#section-5)
6. [最终中文结论：现在到底算什么程度](#section-6)

---

<a name="section-1"></a>
## 第一节：Android 开启跨设备后到底能做到什么

### 1.1 "开启跨设备"的代码定义

Android 端开启跨设备的入口是 `GalaxyWebSocketClient.kt` 中的 `crossDeviceEnabled` 标志。

**代码证据**（`app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt`）：

```kotlin
// 当 crossDeviceEnabled=false 时，connect() 是空操作，不发 device_register，
// 不建立 WebSocket，所有 sendJson 调用被硬性阻断
if (!crossDeviceEnabled) {
    Log.i(TAG, "[WS:CONNECT] Cross-device disabled (crossDeviceEnabled=false); skipping WS connection")
    return
}

// 所有出站 WS 消息统一受这个开关守护
if (!crossDeviceEnabled) {
    Log.w(TAG, "[WS:BLOCKED] sendJson rejected: cross_device=off ...")
    return false
}
```

也就是说，"开启跨设备"的实质意义是：**让 Android 端建立到 V2 网关的 WebSocket 连接，从而成为 V2 中心治理体系里的一个可调度执行节点。**

### 1.2 开启后 Android 实际获得的能力

以下内容来自代码实现，每一条均有对应文件证据：

---

#### 能力 A：接受 V2 下发的任务并在本机执行

**V2 侧**（`galaxy_gateway/android_bridge.py`）：
- `AndroidBridge` 将 V2 侧的任务翻译为 AIP v3 命令格式并通过 WebSocket 发送给 Android

**Android 侧**（`GalaxyWebSocketClient.kt`）：
- Android 的 WebSocket 监听器接收 V2 下发的 `TaskEnvelope` / AIP v3 消息
- 通过路由 `"cross_device_coordination"` 分支分发给本地执行引擎

**结论**：Android 能在收到 V2 任务后**使用本机资源执行**，执行结果通过 `sendJson(result)` 上报 V2。

---

#### 能力 B：使用本机 AI 模型做完整的本地推理循环

**Android 侧**（`UFOGalaxyApplication.kt`，`planner/LlamaCppPlannerService.kt`，`grounding/NcnnGroundingService.kt`）：

```kotlin
// 真实 JNI 调用，不是 stub
private external fun nativeLoadModel(path: String, threads: Int): Long
private external fun nativeCompletion(handle: Long, prompt: String, ...): String?

// 应用启动时根据库可用性接线
plannerService = if (NativeInferenceLoader.isLlamaCppAvailable()) {
    LlamaCppPlannerService(...)  // libllama.so — MobileVLM V2-1.7B GGUF
} else {
    DegradedPlannerService.forState(...)
}
groundingService = if (NativeInferenceLoader.isNcnnAvailable()) {
    NcnnGroundingService(...)    // libncnn.so — SeeClick NCNN
} else {
    DegradedGroundingService.forState(...)
}
```

`LocalLoopExecutor` 实现了完整的本地感知-规划-落地-执行循环：

```
perceive（截屏 → PerceptionFrame）
    ↓
plan（LlamaCppPlannerService → MobileVLM V2-1.7B-Q4_K JNI → PlanResult）
    ↓
ground（NcnnGroundingService → SeeClick NCNN JNI → GroundingResult {x, y, confidence}）
    ↓
act（无障碍服务 GUI 自动化：点击 / 滑动 / 输入）
```

**结论**：Android 具备在设备端**独立完成感知→推理→执行的完整 AI 工作循环**能力，不依赖 V2 侧的 AI 推理。

---

#### 能力 C：在三种推理模式下工作

配置键 `android.inference_mode` 决定 Android 的执行角色：

| 模式 | Android 行为 | V2 角色 |
|------|------------|--------|
| `center`（默认） | 截图 → 上传 V2 → 等待 V2 规划和落地 → 执行 V2 下发的动作 | V2 承担全部 AI 推理 |
| `local` | Android 本地做 plan + ground + act，自主完成任务 | V2 仅作为任务派发方和结果接收方 |
| `hybrid` | 本地先尝试，本地失败时通过 `FallbackConfig.enableRemoteHandoff` 远程回传给 V2 | V2 作为本地失败时的托管方 |

**代码证据**（`core/config_schema.py`）：
```python
"android.inference_mode": ConfigEntry(
    description="Android 端推理模式",
    valid_values=VALID_ANDROID_INFERENCE_MODES,  # ["center", "local", "hybrid"]
    change_effect="requires-reconnect",
)
```

**结论**：开启跨设备后，Android 在 `local` 模式下可以**完全自主完成任务执行全程**，V2 只作为任务来源和观察方。

---

#### 能力 D：离线积压与断线重连后恢复

**Android 侧**（`network/OfflineTaskQueue.kt`，`GalaxyWebSocketClient.kt`）：

```kotlin
// 断线时将可入队的消息类型放入离线队列
val msgType = tryExtractType(json)
if (msgType != null && msgType in OfflineTaskQueue.QUEUEABLE_TYPES) {
    offlineQueue.enqueue(msgType, json, sessionTag = durableSessionId)
    Log.i(TAG, "[WS:OfflineQueue] Queued offline message type=$msgType ...")
}
// 重连后 flushOfflineQueue() 按 sendJson 路径回放
```

**结论**：Android 能在网络断连期间**缓存任务**，恢复连接后自动回放，保持任务连续性。

---

#### 能力 E：多级降级（不崩溃）

**Android 侧**（`local/PlannerFallbackLadder.kt`，`local/GroundingFallbackLadder.kt`）：

当本地 AI 推理失败或设备资源不足时，Android 有降级梯队：
- 规划降级：本地模型失败 → 降级规划策略（DegradedPlannerService）
- 落地降级：SeeClick NCNN 失败 → 降级落地（坐标估算等）
- 整体降级：本地不可用时 → 向 V2 上报降级状态（如果已实现上报的话）

**结论**：Android 能在部分能力不可用时**优雅降级而不崩溃**，系统鲁棒性有基本保障。

---

#### 能力 F：执行事件上报（结构已有，但通道有限）

**V2 侧**（`core/flow_level_operator_surface.py`）：

V2 已定义 `AndroidExecutionPhase` 枚举：
```python
class AndroidExecutionPhase(str, enum.Enum):
    PLANNING = "planning"
    GROUNDING = "grounding"
    EXECUTION = "execution"
    REPLAN = "replan"
    STAGNATION = "stagnation"
    GATE_DECISION = "gate_decision"
    TAKEOVER = "takeover"
    COLLABORATION = "collaboration"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"
```

V2 也已定义 `AndroidCanonicalExecutionEvent` 数据结构，用于接收 Android 上报的执行阶段事件。

**Android 侧**（`AndroidCanonicalExecutionEventOwner.kt` 在 Android 仓库中存在）：
Android 侧有上报执行事件的代码，但 GalaxyWebSocketClient 当前的标准 sendJson 流程中未见 `device_execution_event` 类型的消息被发出。

**结论**：执行事件上报的**结构和协议已存在于双仓**，但 Android 端当前的 WS 客户端是否完整、稳定地发出结构化执行事件，需要进一步确认。

---

### 1.3 汇总：Android 开启跨设备后真正能做的事

| 能力 | 真实可用 | 代码证据文件 |
|------|---------|------------|
| 建立 WS 连接到 V2 网关 | ✅ 完全可用 | `GalaxyWebSocketClient.kt` |
| 接收 V2 派发的任务并本地执行 | ✅ 完全可用 | `GalaxyWebSocketClient.kt` + `android_bridge.py` |
| center 模式（V2 推理 + Android 执行） | ✅ 完全可用 | `UFOGalaxyApplication.kt`, `android_bridge.py` |
| local 模式（本地完整 AI 循环） | ✅ 完全可用（需模型已下载） | `LocalLoopExecutor.kt`, `LlamaCppPlannerService.kt`, `NcnnGroundingService.kt` |
| hybrid 模式（本地优先 + 远程兜底） | ⚠️ 接口已有，enableRemoteHandoff 默认关闭 | `FallbackConfig.kt` |
| 断线重连和离线任务回放 | ✅ 完全可用 | `OfflineTaskQueue.kt` |
| 多级降级（不崩溃） | ✅ 完全可用 | `PlannerFallbackLadder.kt`, `GroundingFallbackLadder.kt` |
| 向 V2 报告任务结果 | ✅ 完全可用 | `GalaxyWebSocketClient.sendJson(result)` |
| 向 V2 上报结构化设备状态快照 | ❌ Android 侧当前不发送 `device_state_snapshot` | `GalaxyWebSocketClient.kt`（无相关消息） |
| 向 V2 上报结构化执行事件 | ⚠️ 结构已有，执行事件上报链路完整性待确认 | `AndroidCanonicalExecutionEventOwner.kt` |

---

<a name="section-2"></a>
## 第二节：Android 还不能接管什么

### 2.1 Android 不能接管 V2 的调度权威

**代码证据**（`core/openclawd.py`）：

```python
# 只有 OpenClawd 持有执行路径决策权
def _determine_execution_path(self, intent, context):
    # 决定：local / cross_device / hybrid / none
    # Android 节点无法覆盖这个决定
```

V2 侧的 `OpenClawd._determine_execution_path()` 是系统内**唯一的执行路径路由决策者**。Android 作为注册设备，在被 V2 选中并派发任务之前，它无法主动插入自己进入某个任务的执行链。

**结论**：**Android 不能决定自己要执行哪些任务**，这是 V2 决定的。

---

### 2.2 Android 不能接管 V2 的路由权威

**代码证据**（`core/command_router.py`）：

`CommandRouter` 是 V2 侧跨设备路由的唯一权威。当 OpenClawd 决定走跨设备路径后，CommandRouter 负责选择设备、封装 `TaskEnvelope`、发送到网关。Android 端不能绕过 CommandRouter 直接替换路由决策。

**结论**：**Android 不能决定任务走哪条路由**，路由权威在 V2 侧。

---

### 2.3 Android 不能接管 V2 的 LLM 路由权威

**代码证据**（`core/multi_llm_router.py`）：

`MultiLLMRouter` 管理所有 LLM 提供商（openai / anthropic / gemini / deepseek / groq / openrouter / oneapi）的选择和负载均衡。Android 端不参与这个决策——即使在 `local` 模式下，Android 本地使用的是 libllama.so（MobileVLM），与 V2 的 MultiLLMRouter 是完全独立的两套系统。

**结论**：**Android 不能影响 V2 侧的 LLM 路由决策**，两套推理系统各自独立运行。

---

### 2.4 Android 不能接管任务生命周期的真相权威

**代码证据**（`core/canonical_task_runtime.py`，`core/task_store.py`）：

`CanonicalTaskRuntime` 是 V2 侧对所有任务生命周期（created → dispatched → executing → completed / failed / recovered）的权威记录。Android 端不持有、也不能覆盖 V2 侧的任务状态真相。

Android 能做的只是：向 V2 上报执行结果，由 V2 去更新任务状态。

**结论**：**Android 不持有任务状态权威**，任务状态的最终真相在 V2 的 CanonicalTaskRuntime。

---

### 2.5 Android 不能接管配置权威

**代码证据**（`core/config_schema.py`，`core/config_service.py`）：

`ConfigService` 定义了 `android.inference_mode` 的合法值，Android 通过 `RemoteConfigFetcher` 在启动时从 V2 的 `/api/v1/config` 拉取配置。Android 不能主动推送配置更改给 V2。

**结论**：**Android 是配置消费方，不是配置权威**。V2 的 ConfigService 是唯一配置权威。

---

### 2.6 Android 不能发起接管（"takeover" 的真实语义）

这是一个常见的误解点，需要专门澄清。

在本代码库中，"接管/takeover"的含义是：

**V2 向 Android 发送接管请求**，请求 Android 接管某个执行流的执行责任。这不是 Android 接管 V2，而是 V2 授权 Android 执行。

**代码证据**（`galaxy_gateway/android_bridge.py`）：

```python
async def send_takeover_request(
    self,
    device_id: str,
    takeover_id: str,
    *,
    session_id: Optional[str] = None,
    task_context: Optional[Dict[str, Any]] = None,
    ...
) -> Optional[Dict[str, Any]]:
    """V2 calls this to ask Android to accept a takeover.
    Android will reply with a takeover_response uplink (accepted / rejected)."""
```

Android 的响应（`galaxy_gateway/android/handlers/takeover_response.py`）：

```python
# Android 收到 takeover_request 后响应 accepted=true/false
# 整个流程是 V2 主导的，Android 只是响应方
```

**结论**：所谓"接管"是 V2 将某个执行责任委托给 Android，**不是 Android 替换 V2 成为系统中心**。Android 只能接受或拒绝 V2 的委托请求，无法主动发起对系统的接管。

---

<a name="section-3"></a>
## 第三节：V2 目前仍掌握的中心权威清单

以下中心权威全部基于 V2 侧的实际代码，均不受 Android 端配置的影响：

| 权威类型 | 代码实体 | 文件路径 |
|---------|---------|---------|
| **执行路径决策权威** | `OpenClawd._determine_execution_path()` | `core/openclawd.py` |
| **任务路由权威** | `CommandRouter` | `core/command_router.py` |
| **LLM 路由权威** | `MultiLLMRouter` | `core/multi_llm_router.py` |
| **任务生命周期真相权威** | `CanonicalTaskRuntime` | `core/canonical_task_runtime.py` |
| **配置权威** | `ConfigService` + `ConfigStore` | `core/config_service.py`, `core/config_schema.py` |
| **能力协商权威** | `CapabilityRegistry` + `CapabilityResolver` | `core/agent/capability_registry.py`, `core/unified/capability_resolver.py` |
| **设备发现与注册权威** | `DeviceRegistry` / `UnifiedDeviceManager` | `core/device_registry.py` |
| **心跳调度权威** | `HeartbeatScheduler` | `core/openclawd_heartbeat.py` |
| **算子状态投影权威** | `OperatorSurface` | `core/operator_surface.py` |
| **委派执行流投影权威** | `FlowLevelOperatorSurface` | `core/flow_level_operator_surface.py` |
| **就绪矩阵权威** | `ReadinessMatrix` | `core/runtime_readiness_matrix.py` |
| **NATS 消息总线权威** | `nats_bus` | `core/nats_bus.py` |
| **会话生命周期权威** | `DesktopPresenceRuntime` (三态) | `core/desktop_presence_runtime.py` |

**关键架构事实**：上述所有权威均由 V2 进程维护，Android 端没有任何机制可以覆盖或替代这些权威。即使在 `local` 推理模式下，Android 是完全自主执行的，但 V2 仍持有任务的调度权和结果确认权。

---

<a name="section-4"></a>
## 第四节：当前页面 / 操作面 / 控制面已经具备的部分

**重要说明**：相较于前期审查所记录的状态，V2 侧的算子控制面端点已有重大进展。以下所有标注为"✅ 已存在"的端点均基于对 `core/routes/operator.py` 的当前代码直接验证。

### 4.1 V2 REST 控制面端点 — 当前完整清单

**代码证据文件**：`core/routes/operator.py`（已在 `core/api_routes.py` 第 338 行正式注册）

#### 已完全实现的端点

| 端点 | 状态 | 数据来源 | 代码行证据 |
|------|------|---------|----------|
| `GET /api/v1/readiness` | ✅ 已实现 | `ReadinessMatrix.to_dict()` | `operator.py:467–487` |
| `GET /api/v1/operator/snapshot` | ✅ 已实现 | `OperatorSurface.operator_snapshot()` | `operator.py` |
| `GET /api/v1/operator/flows` | ✅ 已实现 | `FlowLevelOperatorSurface` 全量列表 | `operator.py:493–531` |
| `GET /api/v1/operator/flows/{flow_id}` | ✅ 已实现 | `FlowLevelOperatorSurface.inspect_flow()` | `operator.py:537–559` |
| `GET /api/v1/operator/llm` | ✅ 已实现 | `MultiLLMRouter.get_status()` | `operator.py:565–615` |
| `GET /api/v1/operator/nats` | ✅ 已实现 | `nats_bus.is_connected()` + `get_stats()` | `operator.py:621–655` |
| `GET /api/v1/operator/heartbeat` | ✅ 已实现 | `HeartbeatScheduler` 状态 | `operator.py:661–709` |
| `GET /api/v1/ports` | ✅ 已实现 | `PortConfig.list_node_ports()` | `operator.py:715–742` |
| `GET /api/v1/operator/devices/ecosystem` | ✅ 已实现 | `android_device_state_store` 生态摘要 | `operator.py:748–788` |
| `GET /api/v1/operator/devices/ecosystem/{device_id}` | ✅ 已实现 | 单设备快照 | `operator.py:794–814` |
| `GET /api/v1/operator/inspect/task/{task_id}` | ✅ 已实现 | 深度任务投影 | `operator.py` |
| `GET /api/v1/operator/inspect/route/{task_id}` | ✅ 已实现 | 路由决策投影 | `operator.py` |
| `GET /api/v1/operator/inspect/executor/{node_id}` | ✅ 已实现 | 执行器 / 提供商能力投影 | `operator.py` |
| `GET /api/v1/operator/inspect/failure/{task_id}` | ✅ 已实现 | 失败域投影 | `operator.py` |
| `GET /api/v1/operator/inspect/lineage/{task_id}` | ✅ 已实现 | 任务谱系 / 时间线 | `operator.py` |
| `GET /api/v1/operator/inspect/recovery/{task_id}` | ✅ 已实现 | 恢复处置投影 | `operator.py` |
| `GET /api/v1/operator/inspect/partial-result/{task_id}` | ✅ 已实现 | 混合编排部分结果 | `operator.py` |
| `GET /api/v1/operator/inspect/audit-evidence/{task_id}` | ✅ 已实现 | 持久化审计证据覆盖 | `operator.py` |
| `GET /api/v1/operator/review/{task_id}` | ✅ 已实现 | 统一端到端事后审查 | `operator.py` |
| `GET /api/v1/operator/inspect/flow/{flow_id}` | ✅ 已实现 | 委派流规范化投影 | `operator.py:424–461` |
| `GET /api/v1/config` | ✅ 已实现 | `ConfigService.get_config()` | `core/api_routes.py` |
| `POST /api/v1/config` | ✅ 已实现 | `ConfigService.set_config()` | `core/api_routes.py` |

### 4.2 V2 侧已具备的 Android 设备状态接收基础设施

**代码证据文件**：`core/android_device_state_store.py`，`core/device_communication.py`

V2 侧已实现完整的 Android 状态接收和存储体系：

- **`_AndroidDeviceStateStore`** — V2 进程级单例，存储每台设备的最新 `DeviceStateSnapshot`（含 llama_cpp_available、ncnn_available、model_ready、accessibility_ready、overlay_ready、local_loop_ready、model_id、checksum_ok、offline_queue_depth、current_fallback_tier 等字段）
- **`absorb_state_snapshot()`** — 接收并解析 `device_state_snapshot` 消息
- **`absorb_execution_event()`** — 接收 `device_execution_event` 消息，并转发到 `FlowLevelOperatorSurface`

**代码证据**（`core/device_communication.py:633`）：

```python
# V2 侧的消息路由已处理 device_state_snapshot
if msg_type == "device_state_snapshot":
    from core.android_device_state_store import absorb_device_state_snapshot
    absorb_device_state_snapshot(device_id, payload)
```

**结论**：V2 侧的设备状态接收链路**已完整实现**，随时可以接收符合格式的 Android 快照消息。

### 4.3 配置面 — 已完整实现

| 功能 | 状态 | 接口 |
|------|------|------|
| LLM 提供商开关（7个提供商） | ✅ 完整 | `GET/POST /api/v1/config` |
| API Key 配置状态（has_key，不显示值） | ✅ 完整 | `ConfigService.validate()` |
| Android 推理模式（center/local/hybrid） | ✅ 完整 | `POST /api/v1/config` → `android.inference_mode` |
| 网关地址配置 | ✅ 完整 | `POST /api/v1/config` → `network.*` |
| 功能开关（enable_continuum 等） | ✅ 完整（需重启） | `config.json` 编辑 |

---

<a name="section-5"></a>
## 第五节：当前页面 / 操作面 / 控制面仍未完成的部分

### 5.1 最关键缺口：Android 侧不发送设备状态快照

这是当前整个操作面最核心的功能性缺口。

**当前状态**（`app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt`）：

Android 端当前通过 `sendJson()` 发出的消息类型包括：
- `device_register`（连接握手）
- `capability_report`（能力上报）
- `heartbeat`（心跳保活）
- `task_submit` / `task_result` / `goal_result` / `cancel_result`（任务生命周期）

**没有** `device_state_snapshot` 消息类型出现在 GalaxyWebSocketClient.kt 中。

**后果**：
- V2 的 `GET /api/v1/operator/devices/ecosystem` 端点**存在但返回空数据**（没有设备快照）
- V2 无法知道 Android 设备的本地推理库可用性（llamaCppAvailable/ncnnAvailable）
- V2 无法知道 Android 设备的就绪状态（modelReady/accessibilityReady/overlayReady）
- V2 无法知道 Android 设备的离线队列深度或降级梯队状态
- V2 对 Android 设备的了解仍停留在注册时的 capability_report，而不是运行时的实时状态

### 5.2 Android 执行事件上报链路完整性待确认

**当前状态**：

V2 侧已实现：
- `FlowLevelOperatorSurface` — 接收并存储 `AndroidCanonicalExecutionEvent`
- `android_device_state_store.absorb_execution_event()` — 接收 `device_execution_event` 并转发给 Flow 投影层

Android 侧存在 `AndroidCanonicalExecutionEventOwner.kt`，但当前 `GalaxyWebSocketClient.kt` 的标准 sendJson 路径中未明确看到 `device_execution_event` 消息类型的发送。

**后果**：
- `GET /api/v1/operator/flows/{flow_id}` 的 `android_phase` 字段很可能始终是 `"unknown"`（无 Android 上报）
- V2 的 `FlowLevelOperatorSurface` 无法展示 Android 的实时执行阶段（planning/grounding/stagnation 等）

### 5.3 主体三态（TriState）不在算子快照中

**代码证据**（`core/desktop_presence_runtime.py`，`core/operator_surface.py`）：

`DesktopPresenceRuntime` 内部维护 `_state: TriState`（SILENT/LIMINAL/MANIFEST），但当前 `GET /api/v1/operator/snapshot` 的响应中**未包含主体三态字段**。也就是说，算子控制台看不到系统当前的主要认知状态。

### 5.4 没有统一的视觉操作控制台 UI

上述所有 REST 端点均已实现为 API，但**没有与之配套的前端操作控制台界面**。

目前 V2 有两个可视化界面：
- **Windows 桌面 UI**（`enhancements/clients/windows_client/scroll_paper_geek_ui.py`）——主体外壳 UI，DORMANT/ISLAND/SIDESHEET/FULLAGENT 四态切换，不是操作控制台
- **WebUI Dashboard**（`dashboard/backend/main.py`）——配置界面，用于初始化 API Key 和基础配置

目前**没有**一个将算子面板（readiness、flows、LLM 健康、NATS 状态、设备生态）集中呈现的可视化控制台界面。所有算子数据只能通过直接调用 REST 端点来访问。

### 5.5 仍未完成事项汇总表

| 缺口编号 | 描述 | 影响 | 优先级 |
|---------|------|------|--------|
| GAP-AN-01 | Android 不发 `device_state_snapshot` | 设备生态端点返回空数据 | **最高** |
| GAP-AN-02 | Android 执行事件上报链路待确认 | Flow 投影无法观测 Android 执行阶段 | 高 |
| GAP-V2-01 | TriState 不在算子快照中 | 算子无法看到主体当前认知状态 | 高 |
| GAP-UI-01 | 无统一操作控制台 UI | 算子 API 存在但无可视化入口 | 中 |
| GAP-AN-03 | 降级梯队层级未投影到 V2 | V2 不知 Android 当前降级程度 | 中 |
| GAP-AN-04 | 离线队列深度未持续上报 V2 | V2 不知 Android 积压量 | 中 |
| GAP-AN-05 | 本地推理库可用性未实时投影 | V2 无法决策是否走本地路径 | 中 |

---

<a name="section-6"></a>
## 第六节：最终中文结论——现在到底算什么程度

### 6.1 关于"Android 能否接管整个系统"的最终结论

**结论：Android 不能接管 Galaxy 系统，它是系统里的一个有能力的执行节点，而不是治理权威。**

具体来说：

- **Android 可以做的**：在 V2 授权后，自主在设备本地完成感知→规划→落地→执行的完整 AI 任务循环；在 `local` 模式下几乎不需要 V2 参与每一步执行；在断线情况下自主缓存和恢复。
  
- **Android 不能做的**：决定自己执行哪些任务；覆盖 V2 的路由决策；成为 LLM 路由的权威；取代 CanonicalTaskRuntime 作为任务真相来源；修改 V2 的配置。

- **"接管/takeover" 的真实语义**：这是 V2 向 Android 发起的"你来接管这个执行流"的委托请求，不是 Android 接管 V2 系统控制权。

- **如何理解 Android 的实际地位**：Android 是"具有独立认知执行能力的分布式运行时节点"，类比于一个非常有能力的外包执行单元，但合同和授权永远在 V2 中心。

### 6.2 关于"控制面完成度"的最终结论

**结论：V2 端控制面的 REST API 层已基本完整，但功能层有一个核心缺口——Android 侧不上报设备状态快照，导致多设备生态视图无实际数据。**

分层评估：

| 层次 | 完成度 | 说明 |
|------|--------|------|
| V2 配置面 (`GET/POST /api/v1/config`) | **已完整** | 提供商配置、Android 推理模式、网络设置均可读写 |
| V2 就绪矩阵 (`GET /api/v1/readiness`) | **已完整** | ReadinessMatrix 已有 REST 端点，实时反映运行时就绪状态 |
| V2 算子快照 (`GET /api/v1/operator/snapshot`) | **已完整（有小缺口）** | 已暴露任务计数、设备在线情况、拓扑节点数；TriState 未包含 |
| V2 委派流面板 (`GET /api/v1/operator/flows[/{id}]`) | **端点已完整，数据依赖 Android** | V2 侧已实现，但无 Android 执行事件上报则 android_phase=unknown |
| V2 LLM 健康面 (`GET /api/v1/operator/llm`) | **已完整** | 实时 LLM 提供商健康状态可查 |
| V2 NATS 状态面 (`GET /api/v1/operator/nats`) | **已完整** | 连接状态和统计数据可查 |
| V2 心跳状态面 (`GET /api/v1/operator/heartbeat`) | **已完整** | HeartbeatScheduler 状态实时可查 |
| V2 端口映射面 (`GET /api/v1/ports`) | **已完整** | 130+ 节点端口映射可查 |
| **Android 生态状态面** (`GET /api/v1/operator/devices/ecosystem`) | **端点已完整，功能性缺口** | V2 侧完整实现，**Android 侧不发送 device_state_snapshot，实际数据为空** |
| 统一操作控制台 UI | **不存在** | REST API 存在，前端可视化控制台未实现 |

### 6.3 一句话定性

> **当前 Galaxy 系统已处于"控制面 API 结构完整、Android 执行节点能力完整、但 Android→V2 状态投影通道尚未激活"的中期阶段。**
>
> Android 作为执行节点具有完整能力，V2 作为控制中心具有完整权威，双边 REST 控制面 API 已全部实现——但 Android 侧尚未发送 `device_state_snapshot` 消息，这使得多设备生态视图目前处于"有架子、无数据"的状态。系统的核心下一步是激活 Android 侧的状态快照上报，以使已完整的 V2 控制面真正反映 Android 运行时的实际状态。

---

## 附录：关键代码文件索引

| 文件 | 仓库 | 核心作用 |
|------|------|---------|
| `core/openclawd.py` | V2 | 认知与执行决策核心，唯一执行路径路由权威 |
| `core/desktop_presence_runtime.py` | V2 | 主体外壳，三态生命周期，session ID 权威 |
| `core/command_router.py` | V2 | 唯一跨设备任务路由器 |
| `core/multi_llm_router.py` | V2 | LLM 提供商选择和负载均衡 |
| `core/operator_surface.py` | V2 | 算子投影层，所有 inspect_* 方法 |
| `core/flow_level_operator_surface.py` | V2 | 委派执行流投影，AndroidExecutionPhase |
| `core/routes/operator.py` | V2 | 全部算子 REST 端点（readiness/flows/llm/nats 等） |
| `core/android_device_state_store.py` | V2 | Android 状态快照存储（已完整实现） |
| `core/device_communication.py` | V2 | 消息路由，包含 device_state_snapshot 处理（行 633）|
| `core/api_routes.py` | V2 | 主路由注册（算子路由在行 338 注册）|
| `core/canonical_task_runtime.py` | V2 | 任务生命周期真相权威 |
| `core/runtime_readiness_matrix.py` | V2 | 运行时就绪矩阵 |
| `galaxy_gateway/android_bridge.py` | V2 | Android 任务翻译适配器，send_takeover_request |
| `galaxy_gateway/android/handlers/takeover_response.py` | V2 | 接收 Android 对接管请求的响应 |
| `app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt` | Android | WS 连接管理，crossDeviceEnabled 开关，消息收发 |
| `app/src/main/java/com/ufo/galaxy/UFOGalaxyApplication.kt` | Android | 应用入口，NativeInferenceLoader，本地 AI 接线 |
| `app/src/main/java/com/ufo/galaxy/planner/LlamaCppPlannerService.kt` | Android | libllama.so JNI，MobileVLM 规划 |
| `app/src/main/java/com/ufo/galaxy/grounding/NcnnGroundingService.kt` | Android | libncnn.so JNI，SeeClick 落地 |
| `app/src/main/java/com/ufo/galaxy/local/LocalLoopExecutor.kt` | Android | 完整本地感知-规划-落地-执行循环 |
| `app/src/main/java/com/ufo/galaxy/network/OfflineTaskQueue.kt` | Android | 离线任务积压和回放 |
| `app/src/main/java/com/ufo/galaxy/local/PlannerFallbackLadder.kt` | Android | 规划降级梯队 |
| `app/src/main/java/com/ufo/galaxy/local/GroundingFallbackLadder.kt` | Android | 落地降级梯队 |
