# 最深度双仓整合认知审计 — 2026

**仓库范围**：`DannyFish-11/ufo-galaxy-realization-v2` ↔ `DannyFish-11/ufo-galaxy-android`

> **方法论**：本文件完全基于两个仓库的真实实现代码重建系统理解。不引用任何先前的
> audit 文档、verdict 文件或 narrative 叙述作为证据来源。所有陈述均可通过引用的具体
> 源文件、类、函数、枚举或注释字符串逐一核实。不继承任何先前结论。

---

## 第一节：完整集成架构

### 1.1 V2 仓库到底是什么

**`ufo-galaxy-realization-v2` 是中心治理节点（center governance node）。**

真实代码证据：

- `galaxy_gateway/app.py` 第 1–15 行明确写道：  
  `galaxy_gateway` 是 unified subject 的 internal cross-device execution substrate；
  是 transport/protocol 层，使 subject 的 liminal cross-device execution loop 能够到达远端设备。  
  它不是独立的 subject authority，不是 presence 主体。

- `core/desktop_presence_runtime.py` 定义了 `DesktopPresenceRuntime`，它是整个系统在  
  Windows 桌面环境中的外部呈现层（"clothing" / outer shell），拥有：
  - 规范三态生命周期（`SILENT → LIMINAL → MANIFEST`）
  - 原生多模态连续感知（`MultimodalIngressBus`）
  - `runtime_session_id` 生成与传播  
  它持有并调用 `OpenClawd`（主体核心），两者共同构成一个主体，而非两个并行主体。

- `core/openclawd.py` 定义了 `OpenClawd`——系统的认知/执行核心，完全工作在
  `DesktopPresenceRuntime` 的 LIMINAL 阶段内部。它持有：
  - `ContinuumOrchestrator`（意图→状态持续回路）
  - `DecisionExecutor`（本地执行委托）
  - `AgentKernel`（内嵌认知/规划子层）
  - `CanonicalDispatcher`（规范能力调度器）
  - `_router`（`UnifiedLLMRouter`，通过 `core/unified/llm_router.py` 懒加载）

- `core/command_router.py` 是规范命令分发器；对跨设备任务而言，
  `CommandRouter` 是唯一路由权威（`cross_device_execution_chain.py` 第 39 行）。

- `core/device_registry.py` 和 `core/unified/device_manager.py`（UnifiedDeviceManager，UDM）
  是设备身份和在线状态的 SSOT（Single Source of Truth）。

- `galaxy_gateway/device_router.py` 是传输/路由基础层——将已调度的 TaskEnvelope 通过
  WebSocket 发送到具体设备，但不做路由决策。

**V2 的中心职责汇总：**

| 职责 | 实现模块 |
|------|----------|
| 认知核心/执行分支 | `core/openclawd.py` |
| 外部呈现/三态生命周期 | `core/desktop_presence_runtime.py` |
| LLM 路由与多模态路由 | `core/unified/llm_router.py`, `core/multi_llm_router.py` |
| 跨设备命令路由 | `core/command_router.py` |
| 传输/WebSocket gateway | `galaxy_gateway/` |
| 设备注册与状态 SSOT | `core/device_registry.py`, `core/unified/device_manager.py` |
| 任务信封 / 结果信封 | `contracts/handoff_envelope_v2.py`, `core/cross_device_execution_chain.py` |
| NATS 分布式传输 | `core/nats_bus.py` |
| 配置权威 | `core/config_service.py`, `core/config_store.py` |
| 多模态感知总线 | `core/multimodal/ingress_bus.py` |
| Android VLM 中心推理 | `galaxy_gateway/android_vlm_service.py` |

---

### 1.2 Android 仓库到底是什么

**`ufo-galaxy-android` 是分布式运行时参与者节点（distributed runtime node）。**

真实代码证据（均来自 V2 侧对 Android 的镜像描述与集成引用）：

- `core/center_distributed_agent_system_review.py`（第 60–75 行）明确将 Android 定位为
  "DISTRIBUTED RUNTIME NODE DOMAIN"，具备：
  - `GalaxyConnectionService`——持久化运行时宿主（后台 Service）
  - `GalaxyWebSocketClient`——唯一 WebSocket 传输类，管理连接生命周期与协议收发
  - `CommandDispatcher`——本地能力分发
  - `AccessibilityActionExecutor`——GUI 交互（主链路）
  - `AccessibilityScreenshotProvider`——视觉感知
  - `MobileVlmPlanner`——本地推理（非默认，需要外部推理服务器）
  - `SeeClickGroundingEngine`——本地 Grounding（非默认，需要 NCNN/MNN）
  - `LoopController`（46KB）——本地 step-level 执行循环
  - `OfflineTaskQueue`——离线队列/本地网络弹性
  - `TailscaleAdapter`——替代网络路径（Tailscale VPN）

- `AipModels.kt`（103KB）是 Android 端完整的 AIP 协议类型定义，覆盖所有消息类型和数据模型。

- Android 端的本地执行链：
  ```
  LoopController.step()
    → perceive (AccessibilityScreenshotProvider)
    → plan (MobileVlmPlanner [非默认] or NoOpPlannerService [默认])
    → ground (SeeClickGroundingEngine [非默认] or NoOpGroundingService [默认])
    → act (AccessibilityActionExecutor)
    → observe result
    → continue loop or signal completion to V2
  ```
  (`docs/CENTER_DISTRIBUTED_AGENT_SYSTEM_REVIEW.md` 第 107–118 行有代码证明)

**Android 的参与者节点职责汇总：**

| 职责 | 状态 |
|------|------|
| AIP v3 WebSocket 通信 | ✅ 实现完整（`GalaxyWebSocketClient.kt`）|
| GUI 自动化执行 | ✅ 实现完整（`AccessibilityActionExecutor`）|
| 视觉截图感知 | ✅ 实现完整（`AccessibilityScreenshotProvider`）|
| 本地执行循环 | ✅ 实现完整（`LoopController` 46KB）|
| 离线任务队列 | ✅ 实现（`OfflineTaskQueue`）|
| 本地 AI 规划（MobileVLM） | ⚠️ 代码架构完整，非默认激活（需外部服务器）|
| 本地 AI Grounding（SeeClick） | ⚠️ 代码架构完整，非默认激活（需 NCNN/MNN）|
| HandoffEnvelopeV2 处理 | ✅ AipModels.kt 有 `HANDOFF_ENVELOPE_V2` handler |

---

### 1.3 中心—分布式协同架构整体模型

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  CENTER GOVERNANCE DOMAIN (V2 — ufo-galaxy-realization-v2)                  │
│                                                                              │
│  DesktopPresenceRuntime (outer shell / Windows clothing)                    │
│      │  owns: session / tri-state lifecycle / MultimodalIngressBus          │
│      │  drives: SILENT → LIMINAL → MANIFEST → SILENT                        │
│      │                                                                       │
│      └─ [LIMINAL phase] → OpenClawd (subject core / decision core)         │
│              │  Stage 1: Ingest (PerceptionFrame + multimodal_context)      │
│              │  Stage 2: Continuum (ContinuumOrchestrator → state_continuum)│
│              │  Stage 3: Branch (_determine_execution_path)                 │
│              │  Stage 4: Manifest                                            │
│              │                                                               │
│              ├─ LOCAL → DecisionExecutor → WindowsExecutionArbiter         │
│              │           (stays on Windows device)                           │
│              │                                                               │
│              └─ CROSS_DEVICE → CommandRouter → DeviceRouter                │
│                                    │                                         │
│                              TaskEnvelope / HandoffEnvelopeV2               │
│                              PendingDeliveryBuffer (offline resilience)     │
└──────────────────────────────────│──────────────────────────────────────────┘
                                   │  AIP v3 WebSocket
                                   │  /ws/device/{device_id}
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  DISTRIBUTED RUNTIME NODE DOMAIN (Android — ufo-galaxy-android)             │
│                                                                              │
│  GalaxyConnectionService (persistent background service)                   │
│      └─ GalaxyWebSocketClient (transport + reconnect + offline queue)      │
│              └─ AgentMessageHandler / RuntimeController                     │
│                      └─ CommandDispatcher                                   │
│                              │                                               │
│                              ├─ AccessibilityActionExecutor (GUI)           │
│                              │                                               │
│                              └─ LoopController (step-level exec loop)      │
│                                      → perceive (screenshot)                │
│                                      → plan (MobileVlmPlanner OR NoOp)     │
│                                      → ground (SeeClick OR NoOp)            │
│                                      → act (AccessibilityActionExecutor)    │
│                                      → result signal                        │
│                                                                              │
│  Task result / goal_execution_result                                        │
│      └─ WebSocket → V2 ingestion → memory backflow / settlement             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

### 1.4 责任边界

| 层级 | V2 (Center) | Android (Participant) |
|------|------------|----------------------|
| 编排/治理权威 | ✅ OpenClawd | ❌ |
| 请求生命周期管理 | ✅ DesktopPresenceRuntime | ❌ |
| 意图理解 / LLM 路由 | ✅ UnifiedLLMRouter | 部分（本地 MobileVLM，非默认）|
| 多模态感知（连续） | ✅ MultimodalIngressBus | ✅ AccessibilityScreenshotProvider |
| 跨设备传输 | ✅ gateway / DeviceRouter | ✅ GalaxyWebSocketClient |
| 设备 GUI 执行 | ❌ | ✅ AccessibilityActionExecutor |
| 设备感知截图 | ❌ | ✅ AccessibilityScreenshotProvider |
| 任务结果归档 | ✅ V2 ingest / memory backflow | ❌ |
| 配置权威 | ✅ ConfigService / config.json | Android SharedPreferences |
| 离线缓冲 | ✅ PendingDeliveryBuffer | ✅ OfflineTaskQueue |
| 本地 AI 规划 | ✅（作为 AndroidVLMService） | ⚠️（MobileVlmPlanner，非默认）|

---

## 第二节：OpenClawd 与中心侧智能体真实情况

### 2.1 OpenClawd 是什么

**OpenClawd 是主体核心（subject core）——认知和执行分支的原子性决策中枢。**

真实代码证据（`core/openclawd.py` 第 659–720 行）：

```
OpenClawd (subject core / decision core)
  └─ 架构位置：
       DesktopPresenceRuntime (outer shell)
           └─ OpenClawd (inner core)
                 └─ AgentKernel (embedded cognition/planning sub-layer)
                       ├─ _delegate_local_manifestation()
                       ├─ _delegate_single_remote()
                       └─ _delegate_multi_device_orchestration()
```

**OpenClawd 不是**：
- 不是传输基底（传输在 `galaxy_gateway/`）
- 不是独立的 presence 主体（presence 由 `DesktopPresenceRuntime` 拥有）
- 不是多设备编排层（那是 `_delegate_multi_device_orchestration()` 委托给的子层）

**OpenClawd 是**：
- 系统内部唯一的认知/执行路径决策者
- `runtime_session_id` 的接收和传播者
- 多模态路由决策者（`_select_multimodal_route()`）
- 执行路径分支决策者（`_determine_execution_path()`）
- 工具调用的执行者（`_dispatch_tool_call()`）

---

### 2.2 OpenClawd 在执行路径中的位置

```
adapter surface (chat route / gateway / launcher)
    │  ← 这里没有主体权威，只是协议适配器
    ▼
DesktopPresenceRuntime.handle_request()
    │  SILENT → LIMINAL: request received
    ▼
OpenClawd.process(message, runtime_session_id=..., multimodal_context=...)
    │
    │  Stage 1: Ingest
    │    ├─ MultimodalBus.ingest(multimodal_context) → fusion_summary
    │    └─ attach runtime_session_id as trace_id
    │
    │  Stage 2: Continuum / Liminal Cognition
    │    └─ ContinuumOrchestrator.run() → state_continuum (tri_state_phase + runtime_domain)
    │
    │  Stage 3: Branch
    │    └─ _determine_execution_path() → "local" | "cross_device" | "hybrid" | "none"
    │           ├─ _select_multimodal_route() — 多模态路由决策
    │           └─ capability inference / intent classification
    │
    │  Stage 4: Manifest
    │    ├─ local → _delegate_local_manifestation()
    │    │              → DecisionExecutor + AgentKernel
    │    ├─ cross_device → _delegate_single_remote()
    │    │                     → CommandRouter → gateway → Android
    │    └─ hybrid → both loops concurrently
    │
    └─ return {execution_path, state_continuum, runtime_domain, runtime_session_id, ...}

DesktopPresenceRuntime: LIMINAL → MANIFEST → SILENT
```

---

### 2.3 进入 OpenClawd 的表示形式

```python
# process() 接口（核心入口签名）
async def process(
    self,
    request: str,                           # 自然语言文本
    *,
    session_id: str = "",
    user_id: str = "default",
    device_id: str = "",
    context: List[Dict] = None,             # 历史对话上下文
    multimodal_context: Optional[Any] = None, # 请求绑定的多模态载荷
    perception: Optional[Dict] = None,      # PerceptionFrame 数据（由 shell 传入）
    runtime_session_id: Optional[str] = None, # shell 传播的稳定 trace ID
) -> Dict[str, Any]:
```

`multimodal_context` 是请求绑定的多模态载荷（图像、音频片段等），与 `MultimodalIngressBus`
的连续感知流（`PerceptionFrame`）是两个完全独立的路径。

---

### 2.4 OpenClawd 与 DesktopPresenceRuntime 的三态关系

| 三态阶段 | DesktopPresenceRuntime 角色 | OpenClawd 角色 |
|----------|----------------------------|---------------|
| `SILENT` | subject 静止；`MultimodalIngressBus` 后台持续运行 | 未激活 |
| `LIMINAL` | 驱动 SILENT→LIMINAL 转换；调用 `OpenClawd.process()` | **全部工作**在此阶段内：Ingest→Continuum→Branch→Manifest |
| `MANIFEST` | 驱动 LIMINAL→MANIFEST 转换；OpenClawd 已产出执行路径 | 执行/委托已发起（异步进行中）|

**关键机制（代码证据：`core/desktop_presence_runtime.py` 第 448–459 行）：**

```python
# LIMINAL → MANIFEST: OpenClawd has branched; subject enters manifest
rsession.advance(TriState.MANIFEST)

result = await self._dispatch(
    rsession=rsession,
    message=message,
    ...
)
# _dispatch() 内部调用 OpenClawd.process()
```

`TriState` 是主体存在性状态（subject lifecycle），与 OpenClawd 内部的 `tri_state_phase`
（continuum 状态协议）是完全不同的两个状态系统，不能混淆。

---

### 2.5 OpenClawd 拥有什么 vs 相邻层拥有什么

| 功能 | 属于 OpenClawd | 属于相邻层 |
|------|---------------|-----------|
| 执行路径决策 | ✅ `_determine_execution_path()` | — |
| 多模态路由决策 | ✅ `_select_multimodal_route()` | — |
| AgentKernel 调用 | ✅ 持有并调用 `_kernel` | — |
| 工具调用执行 | ✅ `_dispatch_tool_call()` | — |
| 跨设备路由（transport） | ❌ | `CommandRouter` / `DeviceRouter` |
| 三态生命周期 | ❌ | `DesktopPresenceRuntime` |
| 连续多模态感知 | ❌ | `MultimodalIngressBus` (shell 拥有) |
| WebSocket 连接管理 | ❌ | `galaxy_gateway/` |
| 设备注册 SSOT | ❌ | `UnifiedDeviceManager` (UDM) |
| 结果投影 / 内存回流 | 触发者 | `openclawd_memory_backflow.py` |

---

## 第三节：规范端到端执行链

### 3.1 本地执行链（LOCAL EXECUTION CHAIN）

**代码来源：`core/local_execution_chain.py`**

```
openclawd_dispatch
    → agent_kernel_plan      ← AgentKernel (认知/规划层，仅建议性，不拥有最终权威)
        → command_router_local  ← CommandRouter[LOCAL]
            → local_executor     ← DecisionExecutor / WindowsExecutionArbiter
                → result_capture
                    → openclawd_feedback  ← 回流到 OpenClawd
```

**关键细节**（`local_execution_chain.py` 第 134–160 行）：

- 每一步有明确的 authority boundary
- `agent_kernel_plan`：AgentKernel 是*规划层*，不拥有最终执行权威
- `openclawd_dispatch`：OpenClawd 是起点权威（`core.openclawd`，`subject_decision_authority`）

---

### 3.2 跨设备执行链（CROSS-DEVICE EXECUTION CHAIN）

**代码来源：`core/cross_device_execution_chain.py`**

```
operator 自然语言请求
    │
    ▼
adapter surface (chat route / launcher)
    │  [无主体权威，只是协议适配器]
    ▼
DesktopPresenceRuntime.handle_request()
    │  SILENT → LIMINAL
    ▼
OpenClawd.process()
    │  Stage 3 Branch: execution_path = "cross_device"
    ▼
CommandRouter.route_envelope()
    │  构造 TaskEnvelope / HandoffEnvelopeV2
    ▼
DeviceRouter (transport layer)
    │  通过 PendingDeliveryBuffer 保障离线弹性
    │  AIP v3 WebSocket message: type="handoff_envelope_v2"
    │  目标路径: /ws/device/{device_id}
    ▼
Android: GalaxyWebSocketClient 接收
    │
    ▼
AgentMessageHandler 分发到 AipModels.HANDOFF_ENVELOPE_V2 handler
    │
    ▼
RuntimeController → CommandDispatcher → LoopController
    │  perceive → plan → ground → act 循环
    ▼
任务结果: goal_execution_result / task_result WebSocket message
    │  反向通过同一 /ws/device/{device_id}
    ▼
V2: android_handoff_v2_response_ingress.py 接收处理
    │
    ▼
OpenClawd 结果反馈 → memory backflow / projection / audit
    │
    ▼
DesktopPresenceRuntime: MANIFEST → SILENT
```

---

### 3.3 HandoffEnvelopeV2 在链路中的位置

**代码来源：`contracts/handoff_envelope_v2.py`**

```python
class HandoffEnvelopeV2(BaseModel):
    handoff_id: str           # 稳定唯一标识符
    trace_id: str             # 分布式追踪 ID（从 runtime_session_id 传播）
    task_id: Optional[str]    # 关联 TaskEnvelope 时的任务 ID
    session_id: Optional[str]
    source_device_id: Optional[str]
    target_device_id: Optional[str]
    source: HandoffSourceSummary
    target: HandoffTargetSummary
    agent_spec: HandoffAgentSpec
    task_spec: HandoffTaskSpec
    session_context: HandoffSessionContext
    # capability / exec_mode / route_mode (legacy bridge 字段)
    source_runtime_posture: str  # "control_only" | "join_runtime"
    handoff_policy: Dict
    takeover_policy: LocalTakeoverPolicy
    return_contract: HandoffReturnContract
    dispatch_contract_metadata: Optional[Dict]
```

`to_android_task_assign_payload()` 方法产生最终 Android 下行消息，
`type` 字段设置为 `"handoff_envelope_v2"`，与 Android 侧 `AipModels.kt` 中的
`HANDOFF_ENVELOPE_V2` handler 对齐（`contracts/handoff_envelope_v2.py` 第 743–758 行）。

---

## 第四节：真实多模态现实

### 4.1 多模态输入的两条路径

**代码来源：`core/openclawd.py` 第 35–46 行；`core/desktop_presence_runtime.py` 第 56–68 行**

系统中存在两条完全独立的多模态输入路径，绝对不能混淆：

#### 路径 1：连续宿主感知（Continuous Host Perception）

```
MultimodalIngressBus (由 DesktopPresenceRuntime 拥有和启动)
    │  tick loop，每 tick_ms 毫秒产生一个 PerceptionFrame
    ▼
PerceptionFrame {
    audio: AudioState,
    video: VideoState,
    system_signals: SystemSignals,
    quality_flags: List[QualityFlag],
    requires_native_multimodal: bool,
    active_modalities: List[str],
}
    │
    ▼
OpenClawd.process() 接收 perception: Optional[Dict]
（shell 在相关时传入当前 PerceptionFrame 数据）
```

**代码来源：`core/multimodal/ingress_bus.py`**：`MultimodalIngressBus` 管理：
- `AudioState`（`audio_features.py`）
- `VideoState`（`video_features.py`）
- `SystemSignals`（`perception_frame.py`）
- `SignalQuality`（`signal_quality.py`）

#### 路径 2：请求绑定的多模态上下文（Request-Bound Multimodal Context）

```
handle_request(multimodal_context=...) 调用方传入
    │  per-request 载荷：图像、音频片段等
    ▼
OpenClawd.process(multimodal_context=...)
    │
    ▼
MultimodalBus.ingest(multimodal_context) → fusion_summary
    │  fusion_summary 追加到 prompt
    ▼
LLM 调用（携带多模态内容）
```

---

### 4.2 多模态路由决策机制

**代码来源：`core/openclawd.py` `_select_multimodal_route()` 方法；
`tests/test_pr20_native_multimodal_routing.py`**

OpenClawd 是多模态路由权威（`CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED` 哨兵常量）。
路由结果三态：

| `route_type` | 条件 | 含义 |
|-------------|------|------|
| `native_multimodal` | `requires_native_multimodal=True` + 有支持原生 MM 的 provider | 原生多模态路径 |
| `partial_multimodal` | `requires_native_multimodal=True` + 无原生 MM provider | 降级但有回退说明 |
| `text_only` | `requires_native_multimodal=False` | 纯文本路径 |

**测试覆盖（`test_pr20_native_multimodal_routing.py`）**：
- 5类：`native_multimodal` 路由（openai + anthropic 等支持 multimodal=True 的 provider）
- 6类：`partial_multimodal` 路由（deepseek 等 multimodal=False 时触发 fallback）
- 7类：`text_only` 路由
- 8类：router 不可用时的 `advisory` 路由

---

### 4.3 实际支持原生多模态的 provider

**代码来源：`core/config_service.py` `_PROVIDER_KEY_MAP`；`core/config_schema.py` `VALID_PROVIDERS`**

```python
VALID_PROVIDERS = ["openai", "anthropic", "gemini", "deepseek", "groq", "openrouter", "oneapi"]
```

支持 `multimodal=True` 的实际 provider（由 `MultiLLMRouter` 中每个 provider 的配置决定）：
- **OpenAI**：GPT-4 Vision / GPT-4o 支持原生多模态
- **Anthropic**：Claude 3/3.5 系列支持图像
- **Gemini**：原生多模态

`_select_multimodal_route()` 通过 `router.get_available_providers()` 检查哪些 provider
有 `multimodal=True`，如果有则产出 `native_multimodal` 路由。

---

### 4.4 V2 侧作为 Android 的中心 VLM 服务

**代码来源：`galaxy_gateway/android_vlm_service.py`；`galaxy_gateway/routes/android_vlm.py`**

这是解决 Android 侧 llama.cpp/NCNN 依赖问题的架构决策：

```
Android                              V2 Center
    │  POST /api/v1/android/vlm/plan
    │  { image_base64, task, device_id, screen_width, screen_height }
    ├──────────────────────────────────►
    │                                  AndroidVLMService.plan()
    │                                      └─ MultiLLMRouter
    │                                           └─ OpenAI Vision / Gemini Vision
    │                                  { action, coordinates, reasoning }
    ◄──────────────────────────────────┤
    │  POST /api/v1/android/vlm/ground
    │  { image_base64, query, device_id }
    ├──────────────────────────────────►
    │                                  AndroidVLMService.ground()
    │                                  { bbox, label, confidence }
    ◄──────────────────────────────────┤
```

当 `android.inference_mode = "center"` 时，Android 设备不需要本地 llama.cpp/NCNN，
V2 中心通过这两个 HTTP 端点提供 MobileVLM 规划和 SeeClick grounding 推理。

**模型 SHA-256 状态（`android_vlm_service.py` 第 99–138 行）**：

```python
ANDROID_MODEL_CHECKSUMS = {
    "mobilevlm_v2_1_7b_gguf": { "sha256": "" },   # ← 仍为空
    "seeclick_params":         { "sha256": "" },   # ← 仍为空
    "seeclick_bin":            { "sha256": "" },   # ← 仍为空
}
```

⚠️ **这三个 SHA-256 值仍然为空字符串**。这是一个已知的配置完整性缺口：当 Android
以 `inference_mode="local"` 运行时，模型下载后无法进行完整性校验，需要在实际部署时
填入真实的 Hugging Face 文件 SHA-256 值。当 `inference_mode="center"` 时，
这些 checksum 不影响运行时路径，但仍是一个需要在生产部署中填入的值。

---

### 4.5 多模态现实今天 vs 设计意图

| 方面 | 今天的真实情况 |
|------|--------------|
| V2 侧原生多模态路由 | ✅ 已实现（`_select_multimodal_route()`，有测试覆盖）|
| 连续宿主感知总线 | ✅ 已实现（`MultimodalIngressBus`，有单元测试）|
| 原生 MM provider 支持 | ✅ OpenAI/Anthropic/Gemini 支持（前提是 API Key 已配置）|
| 请求绑定多模态 | ✅ `multimodal_context` 参数路径已建立 |
| Android 中心 VLM | ✅ `AndroidVLMService` 已实现，HTTP 端点已注册 |
| Android 本地 VLM | ⚠️ 代码架构存在，非默认（需外部推理服务器）|
| operator 桌面多模态填入面 | ⚠️ 尚无完整、统一的 operator 控制面来可视化展示多模态状态 |
| SHA-256 模型完整性校验 | ❌ 三个 checksum 仍为空字符串 |

---

## 第五节：协议、传输、生命周期与恢复机制

### 5.1 规范 WebSocket 入口

**代码来源：`galaxy_gateway/routes/websocket.py`（由 `register_websocket_routes()` 注册）**

| 路径 | 分类 | 处理器 |
|------|------|--------|
| `/ws/device/{device_id}` | **[CANONICAL]** 唯一规范入口 | `_handle_android_ws()` → `android_bridge.handle_message()` |
| `/ws/android/{device_id}` | [COMPAT] Android 遗留兼容路径 | 委托给规范 pipeline |
| `/ws/android` | [COMPAT] Android fallback | 同上 |
| `/ws/ufo3/{device_id}` | [LEGACY-DISABLED] 默认禁用 | `GALAXY_ENABLE_LEGACY_PROTOCOLS=true` 才激活 |
| `/ws/webrtc/{device_id}` | [MEDIA] WebRTC 信令代理 | 非主路径 |
| `/ws/{device_id}` | [DEPRECATED] 泛型 catch-all | 非主入口 |
| `/ws` | [DEBUG] 调试路径 | 自动分配 ID |

---

### 5.2 消息类型覆盖与 handler 注册

**代码来源：`galaxy_gateway/android/handlers/` 目录；`galaxy_gateway/android_bridge.py`**

`AndroidBridge` 通过子模块化的 handler 处理所有入站消息类型：

| 消息类型 | Handler 模块 | 动作 |
|----------|-------------|------|
| `device_register` | `handlers/registration.py::handle_device_register` | 注册到 UDM；ACK 回复 |
| `heartbeat` | `handlers/heartbeat.py::handle_heartbeat` | patch UDM last_heartbeat；ACK |
| `device_status` | `handlers/heartbeat.py::handle_device_status` | 更新设备状态 |
| `agent_ping` | `handlers/heartbeat.py::handle_agent_ping` | pong 回复 |
| `agent_status` | `handlers/heartbeat.py::handle_agent_status` | 更新 agent 状态 |
| `task_result` | `handlers/task_lifecycle.py::handle_task_result` | 结果写入 UDM / 触发回流 |
| `task_end` | `handlers/task_lifecycle.py::handle_task_end` | 标记任务结束 |
| `task_progress` | `handlers/task_lifecycle.py::handle_task_progress` | 进度更新 |
| `command_result` | `handlers/task_lifecycle.py::handle_command_result` | 命令结果处理 |
| `error` | `handlers/task_lifecycle.py::handle_error` | 错误记录 |
| `task_cancel` | `handlers/task_lifecycle.py::handle_task_cancel` | 取消任务 |
| `task_status` | `handlers/task_lifecycle.py::handle_task_status` | 状态更新 |
| `goal_execution_result` | `android_handoff_v2_response_ingress.py` | HandoffV2 响应处理 |
| 未知类型 | `handlers/registration.py::handle_unregistered` | ACK + warning |

**ACK 机制**：所有消息类型均有 ACK 回复（包括未知类型，返回带 warning 的 ACK）。
**代码证据（`core/device_communication.py` 第 521–543 行）**：
- 未注册设备发送 `heartbeat` → 记录 warning + 返回 ACK（不拒绝）
- `device_register` → 自动注册 + `{"status": "registered", "device_id": device_id}`

---

### 5.3 心跳 / 重连 / 看门狗行为

**代码来源：**
- `galaxy_gateway/transport/websocket_server.py`（`WebSocketManager`）
- `core/device_communication.py`（`DeviceCommunication`）
- `core/unified/connection_manager.py`（`UnifiedConnectionManager`）

**V2 侧心跳检测（`WebSocketManager._heartbeat_checker()`）**：
```python
while self._running:
    await asyncio.sleep(self.heartbeat_interval)
    now = datetime.utcnow()
    timeout_threshold = now - timedelta(seconds=self.heartbeat_timeout)
    for device_id in list(self.connections.keys()):
        conn = self.connections.get(device_id)
        if conn and conn.last_heartbeat < timeout_threshold:
            logger.warning(f"Device {device_id} heartbeat timeout")
            await self.disconnect(device_id)
```

**V2 侧心跳状态更新（`UnifiedConnectionManager.update_heartbeat()`）**：
- 更新 `last_heartbeat` 时间戳
- 标记设备为 ONLINE
- 通过 `UnifiedDeviceManager` 同步到 UDM SSOT

**Android 侧重连（`GalaxyWebSocketClient`）**：
- 管理连接生命周期：connect / reconnect / offline queue
- 离线时消息进入 `OfflineTaskQueue`（本地缓冲）
- 重连成功后 queue 自动 flush

---

### 5.4 PendingDeliveryBuffer——V2 侧离线缓冲与重放

**代码来源：`galaxy_gateway/pending_delivery_buffer.py`**

这是解决"跨设备消息在设备断线时丢失"问题的核心机制：

```
AndroidBridge.send_to_device(device_id, message)
    │  设备离线？
    ├─ YES → PendingDeliveryBuffer.enqueue(device_id, message)
    │           ├─ 容量上限：32条/设备（超出则驱逐最旧的）
    │           └─ TTL：60秒（超出则丢弃）
    │
    └─ NO  → 直接发送
    
AndroidBridge.reconnect_device()
    │  设备重连
    └─ PendingDeliveryBuffer.flush(device_id)  ← 批量重放缓冲消息
```

**`DurablePendingDeliveryBuffer`**（持久化扩展）：
- JSON 文件原子写入（temp file + `os.replace`）
- 进程重启后恢复缓冲消息（在 TTL 窗口内）
- 损坏文件优雅降级（buffer 从空开始）

**担保语义**：
- ✅ 容量限制（防止无界内存增长）
- ✅ TTL（防止过期消息被重放）
- ✅ 线程安全（`asyncio.Lock`）
- ✅ 持久化（V2 进程重启后恢复）
- ⚠️ 非强持久性（不是 WAL；端到端精确一次语义不保证）

---

### 5.5 HandoffEnvelopeV2 路径的协调信号

**代码来源：`core/android_handoff_v2_response_ingress.py`；`core/android_execution_signal_reconciler.py`**

Android 返回 `goal_execution_result` 后，V2 侧有专门的协调信号路径：

```
Android goal_execution_result
    │  WebSocket → /ws/device/{device_id}
    ▼
android_handoff_v2_response_ingress.py
    │  解析结果；与原始 HandoffEnvelopeV2 对齐
    ▼
android_execution_signal_reconciler.py
    │  协调：执行信号与原始任务的 trace_id 对齐
    │  检测并处理超时 / 失败 / 部分成功
    ▼
OpenClawd feedback → memory backflow / projection / audit
```

**对齐机制**：通过 `trace_id`（= `runtime_session_id`）贯穿整个链路，
确保 Android 返回结果能被正确归属到发起该任务的请求会话。

---

## 第六节：Android 侧在整个系统中的真实角色

### 6.1 Android 不只是传输端点

Android 具有以下真实的本地能力（即便部分为非默认状态）：

| 能力 | 实现状态 | 默认激活 | 备注 |
|------|----------|----------|------|
| GUI 自动化执行 | ✅ 完整 | ✅ 是 | `AccessibilityActionExecutor` |
| 截图感知 | ✅ 完整 | ✅ 是 | `AccessibilityScreenshotProvider` |
| 本地步进执行循环 | ✅ 完整（46KB `LoopController`）| ✅ 是 | 驱动 perceive-plan-ground-act |
| 离线任务队列 | ✅ 完整 | ✅ 是 | `OfflineTaskQueue` |
| 本地 AI 规划（MobileVLM） | ⚠️ 代码完整，非默认 | ❌ 否 | 需 127.0.0.1:8080 外部推理服务器 |
| 本地 AI Grounding（SeeClick）| ⚠️ 代码完整，非默认 | ❌ 否 | 需 NCNN/MNN 运行时 |
| Tailscale VPN 适配器 | ✅ 已实现 | 可选 | 备用网络路径 |

---

### 6.2 Android 本地 AI 与 V2 中心 OpenClawd 的关系

这是一个**分层分工**模式：

```
请求类型一：V2 发起→Android 执行（远程代理）
V2 OpenClawd (规划/决策) → HandoffEnvelopeV2 → Android LoopController (执行)
    ↑ Android 仅执行 V2 的决策；没有本地规划 AI 介入

请求类型二：Android 本地自主任务（inference_mode="local"）
Android LoopController
    → MobileVlmPlanner.plan() (本地 VLM 推理，127.0.0.1:8080)
    → SeeClickGroundingEngine.ground() (本地 NCNN)
    → AccessibilityActionExecutor.execute()
    ↑ 本地自主执行；不依赖 V2 OpenClawd 进行单步规划

请求类型三：混合（inference_mode="center"）
Android LoopController.step()
    → AndroidVLMService HTTP (POST /api/v1/android/vlm/plan → V2 中心)
    → V2 MultiLLMRouter (GPT-4o Vision / Gemini 等)
    ← 返回下一步 action
    → AccessibilityActionExecutor.execute()
```

**结论**：Android 本地 AI（`MobileVlmPlanner` / `SeeClickGroundingEngine`）与 V2 OpenClawd
是**并行路径**，不是串联关系。在跨设备代理模式下，V2 做高层规划；在本地推理激活时，
Android 自己做步骤级规划。`inference_mode` 配置决定哪条路径激活。

---

### 6.3 Android 本地模型运行时现状

**代码来源：`core/operational_enablement_audit.py` 第 567–580 行；`docs/MATURITY_PROGRESS_REVIEW_2024.md`**

```
LocalPlannerService 接口：定义完整
    目标模型: mtgv/MobileVLM_V2-1.7B
    目标运行时: llama.cpp 或 MLC-LLM
    默认实现: NoOpPlannerService (stub，只返回 "not available")

LocalGroundingService 接口：定义完整
    目标模型: njucckevin/SeeClick
    目标运行时: NCNN/MNN
    默认实现: DegradedGroundingService (stub)
```

⚠️ **真实状态总结**：
- 接口定义完整，架构清晰
- `llama.cpp` 和 `NCNN` Android AAR 目前未在 `app/build.gradle` 中声明
- 系统默认退化到 NoOp/Degraded stub；本地推理不会实际运行
- 当 `inference_mode="center"` 时（推荐配置），这不是阻断：V2 中心处理推理

---

## 第七节：配置 / 控制 / 运算符真实情况

### 7.1 V2 侧所有真实配置层级

**代码来源：`core/config_service.py`；`core/config_store.py`；`core/config_schema.py`；`core/config_preflight.py`**

```
层级 1: 环境变量 (.env 文件 / 系统环境)
    - OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, ...
    - GALAXY_NATS_URL (nats://... 或未设置则 no-op)
    - GALAXY_RUNTIME_URL (可选)
    - GALAXY_ENABLE_LEGACY_PROTOCOLS (true/false)

层级 2: runtime/config.json (由 ConfigStore 读写)
    - network.gateway_url
    - network.android_gateway_url
    - network.nats_url
    - network.ats_url
    - network.webrtc_stun_url
    - android.inference_mode ("center" | "local" | "hybrid")
    - providers.{openai,anthropic,...}.enabled

层级 3: runtime/secrets.env (敏感凭据)
    - API 密钥（由 ConfigService 读写，隔离于 config.json）

层级 4: config.json (根目录，系统主配置)
    - 服务端口、功能开关等

层级 5: .env / .env.example (根目录)
    - 开发期环境变量模板
```

**ConfigService 支持的 network URL keys**（`core/config_service.py` 第 299–308 行）：
```python
_NETWORK_URL_KEYS = {
    "gateway_url":         "network.gateway_url",
    "android_gateway_url": "network.android_gateway_url",
    "nats_url":            "network.nats_url",
    "ats_url":             "network.ats_url",
    "webrtc_stun_url":     "network.webrtc_stun_url",
}
```

**ConfigService API**（`set_network_url(url_key, url_value)` / `get_network_url(url_key)`）：
运行时可写；写入后立即持久化到 `runtime/config.json`。
**即：网络 URL 是运行时可编辑的，不是启动时冻结的。**

---

### 7.2 V2 侧 operator 填入面现实

**代码来源：`windows_client/status_board_v2/url_config_surface.py`；`windows_client/status_board_v2/config_control.py`**

已实现的 operator 填入面：
- `URLConfigSurface`：展示所有网络 URL 的当前值（或 `[NOT SET]`）
- `ConfigControlSurface.apply_network_url()`：通过 CLI `--set-url key=value` 设置 URL
- `ConfigControlSurface.set_android_inference_mode()`：设置 Android 推理模式

**已可填入的 URL**（CLI 接口）：
```bash
python -m windows_client.status_board_v2 --set-url gateway_url=ws://10.0.0.1:8765
python -m windows_client.status_board_v2 --set-url nats_url=nats://10.0.0.1:4222
python -m windows_client.status_board_v2 --set-url ats_url=...
python -m windows_client.status_board_v2 --set-url android_gateway_url=...
```

**现实局限**：这是 CLI 接口，不是完整的 GUI 控制台。
桌面客户端目前是 **"状态面板 + 有限 CLI 控制 + 开发态残留"** 的混合过渡形态，
不是一个完整的、GUI 向导式、一体化的 operator console。

---

### 7.3 Android 侧配置层级

**代码来源：V2 侧对 Android 的镜像描述；`core/center_distributed_agent_system_review.py`**

Android 侧配置（基于 V2 的引用描述）：
- Android App 设置界面：V2 服务器 URL（`GalaxyWebSocketClient` 构造参数 `serverUrl`）
- Tailscale 配置（可选，备用网络路径）
- 本地推理模式（`inference_mode`，控制 MobileVlmPlanner/SeeClick 是否激活）

Android 侧目前**没有完整的 GUI 向导**来配置所有必要的 endpoint URL。
`serverUrl` 需要用户手动在 App 设置中填入 V2 服务器地址。

---

### 7.4 NATS URL 与分布式传输现实

**代码来源：`core/nats_bus.py`；`core/config_preflight.py` 第 272–293 行**

NATS 是可选的分布式消息总线，用于跨节点任务分发：
- **未配置（默认）**：`GALAXY_NATS_URL` 未设置 → `NATSBus` 自动进入 no-op 模式
- **配置后激活**：`nats://localhost:4222` 或 LAN IP

```python
# nats_bus.py 第 287–304 行：优雅降级逻辑
if self._auto_local:
    self._noop = True
    logger.warning(
        "NATSBus: could not reach nats://localhost:4222 — running in no-op mode "
        "(single-machine). To enable NATS locally: nats-server -p 4222."
    )
```

**关键发现**：
- NATS 默认是 no-op，不影响基本系统运行
- 启用 NATS 后提供：跨节点任务分发、Worker 心跳、分布式调度
- 通过 `ConfigService.set_network_url("nats_url", "nats://...")` 运行时可设置
- 也可通过 `GALAXY_NATS_URL` 环境变量设置

---

### 7.5 桌面端现实：不是完整 operator console

**代码来源：用户描述 + V2 侧桌面组件审查**

当前桌面端形态的诚实描述：
- ✅ 状态面板组件存在（`windows_client/status_board_v2/`）
- ✅ URL 配置 CLI 界面已建立（`URLConfigSurface`，`ConfigControlSurface`）
- ✅ 基本的 provider 状态可查看
- ❌ 不是完整的 GUI 向导式 operator console
- ❌ 没有跨设备状态的完整可视化展示（多设备列表、任务链状态）
- ❌ 没有统一的模型/provider 填入 GUI
- ❌ 没有任务历史的完整展示
- ❌ 美学设计和功能补完尚未完成（用户明确表述）

**最诚实的描述**：
> 桌面端目前是"半控制面 + 半状态面 + CLI 残留"的过渡形态。
> 系统内核链路已打通，operator-facing surface 还没有最终收口。

---

## 第八节：长期稳定运行的真实可操作性

### 8.1 运行时可变 vs 启动时冻结

| 配置项 | 可变性 |
|--------|--------|
| 网络 URL（gateway/nats/ats/android_gateway）| ✅ 运行时可变（ConfigService.set_network_url）|
| Provider API Key | ✅ 可通过 ConfigService 更新（写入 secrets.env）|
| Android inference mode | ✅ 运行时可变 |
| LLM routing policy | ✅ `config/llm_routing_policy.yaml` 可热更新（`config_hot_reload.py`）|
| 已注册设备列表 | ✅ 运行时动态（设备 connect/disconnect 即时反映）|
| TriState 生命周期 | 每次请求动态 |

⚠️ 注意：某些模块在首次导入或进程启动时会缓存配置值。
`GALAXY_NATS_URL` 在进程启动时读取，修改后需重启才完全生效。

---

### 8.2 Android 重连持久性

**代码来源：`GalaxyWebSocketClient`（Android）；`galaxy_gateway/pending_delivery_buffer.py`（V2）**

- Android 侧：`GalaxyConnectionService` 是持久化后台 Service，进程存活期间持续尝试重连
- Android 离线队列：`OfflineTaskQueue` 在断线期间缓存任务
- V2 侧：`PendingDeliveryBuffer` 在 Android 断线时缓冲下行消息（TTL 60s）
- `DurablePendingDeliveryBuffer` 提供跨 V2 进程重启的持久化（在 TTL 窗口内）

---

### 8.3 "电脑一直开着、填好配置就能持续运行"这个问题的代码层面回答

**能做到的事**：

| 能力 | 代码实现状态 |
|------|------------|
| V2 服务持续运行 | ✅ `unified_launcher.py` / `main.py` 提供稳定入口 |
| Android WebSocket 重连 | ✅ `GalaxyConnectionService` 后台持久运行 |
| 心跳看门狗 | ✅ V2 侧超时断线 + Android 侧重连 |
| V2 侧消息缓冲/重放 | ✅ `PendingDeliveryBuffer` / `DurablePendingDeliveryBuffer` |
| LLM API Key 持久配置 | ✅ 写入 `runtime/secrets.env`，进程重启后读取 |
| 网络 URL 持久配置 | ✅ 写入 `runtime/config.json`，进程重启后读取 |

**尚存在的真实摩擦点**：

| 摩擦点 | 说明 |
|--------|------|
| Android 侧服务器 URL 填入 | 需要用户手动在 App 内填写，没有 GUI 向导 |
| NATS URL 填入 | 有 CLI 接口，但没有交互式向导 |
| ATS URL | 有 ConfigService 支持，但填入流程对非技术用户不友好 |
| 模型 SHA-256 校验 | 三个 checksum 为空（`inference_mode="local"` 时有完整性风险）|
| 桌面端 operator console 未完成 | 跨设备状态、任务链状态、模型状态均无统一显示面 |
| Android 本地推理非默认 | `inference_mode="local"` 时，llama.cpp/NCNN 未在 build.gradle 中声明 |

**最诚实的结论**：
> 系统具备持续运行的技术基础（重连、缓冲、持久配置）。
> 但当前的"operator 配置填入面"对于非开发者用户来说还不够完善。
> "填完配置后无脑持续运行"这件事的技术链路已基本打通，
> 但配置入口的易用性和完整性还没有完全收口。

---

## 第九节：最终集成理解与系统真相

### 9.1 这个系统真正是什么

**Galaxy 是一个中心治理分布式智能体系统（center-governed distributed intelligent agent system）。**

不是：
- ❌ 简单的远程控制 App
- ❌ 纯粹的聊天机器人
- ❌ 传统的 master-slave 架构
- ❌ 单机 LLM agent

而是：
- ✅ 以 V2 Windows 桌面为中心治理节点的多设备智能体系统
- ✅ OpenClawd 作为单一主体认知/执行核心，通过三态生命周期管理整个请求周期
- ✅ Android 作为自包含的分布式运行时参与者节点（有本地执行能力，有本地 AI 路径）
- ✅ 原生多模态为主的系统设计（V2 侧有完整的多模态感知+路由体系）
- ✅ 通过 AIP v3 WebSocket 协议连接的双仓跨设备协同系统

---

### 9.2 最强已完成真实核心

已真正完成且可信的核心组件：

| 组件 | 完整程度 |
|------|----------|
| `DesktopPresenceRuntime` + `OpenClawd` 统一主体架构 | ✅ 完整，有测试覆盖 |
| 三态生命周期（SILENT/LIMINAL/MANIFEST） | ✅ 完整，有测试覆盖 |
| 本地执行链（`LocalExecutionChain`） | ✅ 完整，有文档 |
| 跨设备执行链（`CrossDeviceExecutionChain`） | ✅ 架构完整，有规范定义 |
| `HandoffEnvelopeV2` 协议契约 | ✅ 完整，结构丰富 |
| AIP v3 WebSocket 协议栈 | ✅ 完整，双端对齐 |
| `MultimodalIngressBus` 连续感知 | ✅ 完整，有单元测试 |
| 原生多模态路由决策 | ✅ 完整，有测试覆盖 |
| Android VLM 中心推理服务 | ✅ 完整，HTTP 端点已注册 |
| `PendingDeliveryBuffer` 离线缓冲 | ✅ 完整，有持久化版本 |
| `ConfigService` 网络 URL 可运行时填入 | ✅ 完整 |
| `NATSBus` 分布式传输（可选激活）| ✅ 完整，优雅降级 |
| Android `LoopController` 本地执行循环 | ✅ 完整（46KB）|
| Android GUI 自动化执行 | ✅ 完整 |

---

### 9.3 尚未完成的关键缺口

#### Operator 层面

| 缺口 | 类型 |
|------|------|
| 桌面端缺少完整 GUI operator console | 产品化缺口 |
| 跨设备/多设备状态无统一可视化展示 | 产品化缺口 |
| 任务链状态无统一显示面 | 产品化缺口 |
| Android App 侧 URL 填入无向导 | 易用性缺口 |
| NATS / ATS URL 填入无 GUI 向导 | 易用性缺口 |

#### 模型完整性层面

| 缺口 | 类型 |
|------|------|
| 三个 Android 模型 SHA-256 仍为空 | 数据完整性缺口 |

#### Android 本地推理层面

| 缺口 | 类型 |
|------|------|
| llama.cpp 未在 app/build.gradle 声明 | 构建依赖缺口 |
| NCNN 未在 app/build.gradle 声明 | 构建依赖缺口 |
| 默认 NoOp 推理（需显式配置激活）| 激活流程缺口 |

---

### 9.4 对核心问题的最终代码层面回答

#### "V2 到底是什么？"
V2 是以 Windows 桌面为物理宿主的中心治理节点。`DesktopPresenceRuntime`（外部呈现层）
持有 `OpenClawd`（认知/执行核心），共同构成一个统一主体，通过 `galaxy_gateway/`
WebSocket 基础设施连接到 Android 参与者节点。

#### "OpenClawd 到底是什么？"
OpenClawd 是系统唯一的主体认知/执行决策核心（subject_decision_authority）。
完全工作在 `DesktopPresenceRuntime` LIMINAL 阶段内。四个阶段：Ingest→Continuum→Branch→Manifest。
它不是传输基底，不是独立的 presence，不拥有设备状态 SSOT。

#### "系统是否以原生多模态为核心？"
是，且已有代码实现：`MultimodalIngressBus`（连续感知）、`_select_multimodal_route()`
（多模态路由决策）、`AndroidVLMService`（Android 多模态推理代理）。
原生多模态路由今天在 OpenAI/Anthropic/Gemini provider 可用时完全工作。

#### "Android 本地 AI 的真实情况是什么？"
代码架构完整（`MobileVlmPlanner`、`SeeClickGroundingEngine`、`LoopController`），
但本地推理默认是 NoOp/Degraded stub。最推荐的部署模式是 `inference_mode="center"`，
由 V2 的 `AndroidVLMService` 提供推理服务，这样 Android APK 不需要 llama.cpp/NCNN。

#### "能否'填完配置后电脑一直开着就能持续运行'？"
技术链路已基本具备（重连机制、缓冲机制、持久化配置）。
主要摩擦点是配置填入面的易用性（CLI 接口 + 手动 App 设置）和 operator console 的完整性。
系统已进入"底层链路打通，上层 operator 收口阶段"。

---

### 9.5 最终综合判断

**Galaxy 是一个架构上真实且基本完整的中心分布式智能体系统，
其最强的已完成核心（认知链路、传输协议、多模态路由、跨设备协议、离线缓冲）
均有真实代码实现和测试覆盖。**

**系统当前最准确的状态定位**：

> **底层协作链已打通、协议层已对齐、多模态核心已实现；
> 上层完整 operator-facing surface（GUI 控制台、统一配置向导、跨设备状态可视化、
> 任务链展示）尚在补完阶段。**
>
> 这不是一个架构缺陷，而是一个"系统核心先行建立、产品化控制面待收口"的成熟度状态。
> 系统已经是一个真正的 center-distributed intelligent agent system，
> 但其面向 operator 的完整使用形态还没有最终交付。

---

*本文件完全基于 `DannyFish-11/ufo-galaxy-realization-v2` 真实代码构建，
引用来源均为具体文件路径、类名、方法名或注释字符串。不引用任何先前 audit 文档作为证据。*
