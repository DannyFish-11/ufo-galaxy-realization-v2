# V2 完整双仓联合审查报告（V2 主视角·完整系统版）

> **审查目标仓库**  
> 主仓：`DannyFish-11/ufo-galaxy-realization-v2`（简称 V2）  
> 伴随仓：`DannyFish-11/ufo-galaxy-android`（简称 Android）  
>
> **审查基线**  
> 所有结论基于两仓实际代码、测试、配置和文档，不基于愿景或注释中的 TODO。  
> 使用三级标注体系：✅ 代码已验证 | ⚠️ 结构存在但运行闭合待验证 | ❌ 代码层明确缺失或阻断
>
> **本文档回答的核心问题**  
> 1. 这两个仓库目前是否已形成一套真实、完整、可运行的产品系统？  
> 2. 若计算机保持开机且用户不主动停止系统，该系统是否具备让自身持续存活的完整生命周期链？  
> 3. 该系统的模型供给架构究竟是 API 主导、原生多模态 API 主导、真正本地大模型能力，还是混合架构？

---

## 目录

1. [双仓完整系统理解](#1-双仓完整系统理解)  
2. [全链路运行能力评估](#2-全链路运行能力评估)  
3. [模型供给架构深度审查](#3-模型供给架构深度审查)  
4. [常驻存活 / 生命周期持续性审查](#4-常驻存活--生命周期持续性审查)  
5. [分层结论：已验证 / 部分闭合 / 缺失阻断](#5-分层结论已验证--部分闭合--缺失阻断)  
6. [最终判断](#6-最终判断)

---

## 1. 双仓完整系统理解

### 1.1 V2 真实运行时定位（基于代码）

V2 不是一个单体应用，而是以下多个层次的叠加：

#### 1.1.1 权威启动入口

| 文件 | 角色 |
|------|------|
| `main.py` | **系统编排器（System Orchestrator）**，唯一权威启动入口。7 阶段分段启动合同（PR-2）：Config 加载 → 模式解析 → 环境检查 → 后台子系统 → Runtime Subject → 桌面界面 → Readiness 摘要 |
| `unified_launcher.py` | main.py 的从属启动组件，被 Phase 4–6 调用。不与 main.py 竞争入口权威 |
| `start.sh` / `start.bat` | 引导脚本，委托给 `unified_launcher.py` / `main.py` |
| `daemon/galaxy_daemon.py` | `GalaxyDaemon`：24/7 守护进程，管理 `galaxy_main` 和 `health_monitor` 两个子进程 |

#### 1.1.2 核心服务层（bootstrap 阶段依次初始化）

从 `core/startup.py` 的 `bootstrap_subsystems()` 可读取完整初始化顺序（共 12+ 个子系统）：

| 顺序 | 子系统 | 关键代码 |
|------|--------|---------|
| 1 | 缓存层（Redis → 内存降级） | `core/cache.py` |
| 2 | 统一错误处理框架 | `core/error_framework.py` |
| 3 | 并发管理器 | `core/concurrency_manager.py` |
| 4 | 监控系统（健康检查/告警/指标） | `core/monitoring.py` |
| 5 | 性能中间件（压缩/限流/缓存/计时） | `core/performance.py` |
| 6 | 命令路由引擎 | `core/command_router.py` |
| 7 | AI 意图引擎（解析/记忆/推荐） | `core/ai_intent.py` |
| 8 | 向量数据库（Qdrant） | `core/vector_backend.py` |
| 9 | 事件桥接（EventBus → 所有子系统） | `core/event_bridge.py` |
| 10 | 多 LLM 智能路由器 | `core/multi_llm_router.py` |
| 11 | 动态 Agent 工厂 + 分形执行器 | `core/agent_factory.py` + `core/fractal_agent.py` |
| 12 | 统一会话管理 + 全链路编排器 | `core/session_manager.py` + `core/e2e_pipeline.py` |
| 13 | SessionRoaming + WakeEventBus + WakeRouter | `galaxy_gateway/session_roaming.py` 等 |

**评估**：✅ 启动序列完整、有明确降级策略（如 Redis 不可用时降级内存缓存），不是单点脆性启动。

#### 1.1.3 Galaxy Gateway（跨端接入层）

`galaxy_gateway/` 是 Android ↔ V2 的真实接入层，包含：

- `android_bridge.py`：AIP v3 WebSocket 协议处理核心
- `galaxy_gateway/android/handlers/`：13 个专用 handler（registration, heartbeat, task_submit, task_lifecycle, goal_execution, delegated_signal, vision, file_transfer, mesh_topology 等）
- `galaxy_gateway/routes/websocket.py`：注册 `/ws/android/{device_id}`、`/ws/device/{device_id}` 等 WebSocket 端点

**评估**：✅ WebSocket 接入层代码完整，协议已与 Android 端 AipModels.kt 双端对齐。

#### 1.1.4 Canonical Execution Chain（核心执行链）

| 模块 | 职责 |
|------|------|
| `core/delegated_flow_entity.py` | DelegatedFlowEntity：flow 生命周期权威 |
| `core/delegated_runtime_execution_tracker.py` | in-flight 执行追踪 |
| `core/delegated_runtime_handoff_contract.py` | handoff 合同 |
| `core/flow_level_truth_ownership.py` | flow 级 truth 权威模型 |
| `core/android_participant_truth_ingress.py` | Android truth 进入 V2 canonical 状态的规范入口 |
| `core/flow_aware_result_convergence.py` | 并行结果聚合 + duplicate 抑制 |
| `core/flow_continuity_coordinator.py` | continuity 事件统一决策入口（7 种 continuity 场景） |

**评估**：✅ 执行链骨架完整；⚠️ readiness/governance 四层信号流跨端打通情况见第 5 节缺口分析。

#### 1.1.5 Operator Surface & 可观测性

| 模块 | 职责 |
|------|------|
| `core/flow_level_operator_surface.py` | flow 级 operator 界面 |
| `core/replay_audit_persistence.py` + `core/replay_foundation.py` | 审计记录持久化 |
| `core/decision_timeline.py` | 决策时间线 |
| `core/monitoring.py` | 健康检查 + 告警 + 指标 |
| `core/runtime_introspection.py` | 运行时自省 |

**评估**：✅ V2 侧 operator/audit 能力完整；⚠️ Android 端 artifact 推送路径见缺口分析。

---

### 1.2 Android 真实运行时定位（基于代码）

Android 端是一个多层次的 Delegated Runtime，不是简单的"设备控制客户端"。

#### 1.2.1 Android Kotlin 包结构（模块级）

| 包 | 职责 |
|----|------|
| `runtime/` | DelegatedRuntimeUnit、AutonomousExecutionPipeline、EdgeExecutor |
| `network/` | GalaxyWebSocketClient（连接/重连/心跳/离线队列） |
| `protocol/` | AipModels（消息类型定义）、AipMessageV3 |
| `agent/` | 本地 agent 管理 |
| `inference/` | LocalGroundingService（SeeClick 接口）、LocalPlannerService（MobileVLM 接口）|
| `service/` | Android 后台服务 |
| `session/` | 会话管理 |
| `coordination/` | 跨端协调 |
| `memory/` | 本地持久化 |
| `observability/` | 本地可观测 |

#### 1.2.2 核心运行时行为

| 能力 | 实现 | 评估 |
|------|------|------|
| WebSocket 连接 + 指数退避重连（1s→2s→4s→8s→16s→30s + jitter） | `GalaxyWebSocketClient.kt` | ✅ 已验证 |
| OfflineTaskQueue（FIFO，50条上限，24h TTL，SharedPreferences 持久化） | `OfflineTaskQueue.kt` | ✅ 已验证 |
| 重连时自动 flush offline queue | `GalaxyWebSocketClient.kt` 重连路径 | ✅ 已验证 |
| 设备注册 + posture 声明（source_runtime_posture="join_runtime"） | `AipModels.kt` + `registration.py` | ✅ 已验证 |
| AIP v3 消息收发（task_submit/task_result/goal_execution/heartbeat 等）| `GalaxyWebSocketClient.kt` | ✅ 已验证 |
| DelegatedExecutionSignal 执行信号上报 | `DelegatedExecutionSignal.kt` | ✅ 已验证 |
| Readiness/Acceptance/Governance/Strategy 四层 Artifact 评估 | 各 Evaluator.kt 文件 | ✅ 结构完整 |
| 本地 truth 维护 | `AndroidLocalTruthOwnershipCoordinator.kt` | ✅ 已验证 |
| SeeClick 端侧 GUI grounding 接口 | `LocalGroundingService.kt` | ⚠️ 仅接口+NoOp 实现，无具体推理后端 |
| MobileVLM 端侧规划接口 | `LocalPlannerService.kt` | ⚠️ 仅接口+NoOp 实现，无具体推理后端 |

---

### 1.3 双仓集成语义（真实协议层）

两仓通过 **AIP v3（Android Integration Protocol v3.0）** 进行完整双向通信：

```
Android App (Kotlin)
  └─ GalaxyWebSocketClient.kt
       │  WebSocket（AIP v3.0 JSON 消息）
       │  ws://<V2_HOST>:8765/ws/android/{device_id}
       ▼
galaxy_gateway/android_bridge.py （V2 接入桥）
  ├─ handlers/registration.py     → 设备注册/BodyMeshRegistry
  ├─ handlers/task_submit.py      → 任务提交
  ├─ handlers/task_lifecycle.py   → 任务生命周期
  ├─ handlers/goal_execution.py   → Goal 执行
  ├─ handlers/delegated_signal.py → DelegatedExecutionSignal
  ├─ handlers/heartbeat.py        → 心跳
  ├─ handlers/vision.py           → VLM 截图/分析
  └─ ...（共 13 个 handler）
       │  HTTP
       ▼
nodes/Node_113_AndroidVLM  （VLM 分析节点）
  └─ AndroidVLMEngine → Node_90_MultimodalVision → 外部 VLM API
```

**集成协议已双端对齐**：AipModels.kt MsgType enum 与 `galaxy_gateway/protocol/aip_v3.py` MessageType 枚举完全对应。

---

### 1.4 真实启动到活跃使用路径

```
用户执行 python main.py
  ↓  Phase 1-3: 配置加载、模式解析、环境检查
  ↓  Phase 4: bootstrap_subsystems()
     - 缓存层（Redis/内存降级）
     - 监控系统（健康检查注册）
     - LLM 路由器（自动发现 provider）
     - Agent 工厂（恢复历史 Agent）
     - 会话管理器 + E2E Pipeline
     - SessionRoaming + WakeEventBus
  ↓  Phase 5: Runtime Subject 启动（OpenClawd + DesktopPresenceRuntime）
  ↓  Phase 6: Galaxy Gateway（WebSocket 服务器启动，端口 8765）
  ↓  Phase 7: Readiness 摘要输出
  ↓
Android App 启动 → GalaxyWebSocketClient 连接 ws://<V2>:8765/ws/android
  ↓  device_register 消息（含 capabilities、platform）
  ↓  V2 handler/registration.py → BodyMeshRegistry.register()
  ↓  V2 返回 register_ack
  ↓
系统进入活跃状态：
  - Android 定期发送 heartbeat → V2 回复 heartbeat_ack
  - V2 可向 Android 下发 task_assign / goal_execution / handoff_envelope_v2
  - Android 执行后通过 task_result / goal_result / delegated_execution_signal 回传
  - V2 FlowContinuityCoordinator 聚合结果
```

**评估**：✅ 启动到活跃路径真实存在，有代码和集成测试（`tests/integration/websocket/test_aip_v3_ws_contracts.py`）支撑。

---

## 2. 全链路运行能力评估

### 2.1 可构建性

| 维度 | 状态 | 依据 |
|------|------|------|
| V2 Python 依赖 | ✅ 可构建 | `requirements.txt` + `pyproject.toml` 完整；有 `Makefile` 和 `Dockerfile` |
| V2 Docker 化 | ✅ 支持 | `docker-compose.yml` + `Dockerfile*` 多个 |
| Android APK 构建 | ✅ 可构建 | `build_apk.sh` + `gradlew assembleDebug`；`android_client/README.md` 提供完整构建指令 |
| 环境变量/配置 | ✅ 完整 | `.env.example` 覆盖所有 API key 配置；`config.json` 包含完整系统配置 |

### 2.2 可启动性

| 维度 | 状态 | 依据 |
|------|------|------|
| V2 单命令启动 | ✅ 验证 | `python main.py`，7 阶段启动合同，有显式 readiness 摘要 |
| V2 Shell 脚本启动 | ✅ 验证 | `start.sh` / `start.bat` |
| V2 Daemon 模式 | ✅ 验证 | `daemon/galaxy_daemon.py`，含 SIGTERM/SIGHUP/SIGINT 处理 |
| Android App 启动 | ✅ 验证 | `UFOGalaxyApplication.kt` Application 类，含基础 DI/服务初始化 |
| 子系统降级启动 | ✅ 验证 | startup.py 每个子系统有 try/except，失败降级而非崩溃 |

### 2.3 可连接性

| 维度 | 状态 | 依据 |
|------|------|------|
| Android → V2 WebSocket 连接 | ✅ 验证 | WebSocket 端点 + handler 完整，有集成测试覆盖 |
| 设备注册协议 | ✅ 验证 | `test_aip_v3_ws_contracts.py` TestAndroidWSEndpointContracts 全覆盖 |
| 多 LLM Provider 连接 | ✅ 验证（API key 配置后） | `multi_llm_router.py` 自动发现机制 |
| 本地 Ollama 连接 | ✅ 验证（OLLAMA_URL 配置后） | OllamaAdapter 完整实现 |
| NATS 消息总线 | ⚠️ 可选 | `core/nats_bus.py` 有自动 no-op 降级，NATS 不可用时系统继续运行 |

### 2.4 可操作性

| 维度 | 状态 | 依据 |
|------|------|------|
| REST API | ✅ 验证 | `core/api_routes.py` + `galaxy_gateway/api/` 完整 API 路由 |
| WebUI Dashboard | ✅ 验证 | `dashboard/backend/main.py` 后端，提供 API key 配置、MCP 加载等功能 |
| CLI 工具 | ✅ 验证 | `cli/` 目录下完整 CLI |
| 健康检查端点 | ✅ 验证 | `/health` 端点 + `core/health_check.py` |
| Operator 界面 | ✅ 验证（V2 侧） | `core/flow_level_operator_surface.py`、audit persistence |

### 2.5 可测试性

| 维度 | 状态 | 依据 |
|------|------|------|
| 单元测试 | ✅ 存在 | `tests/` 目录完整，有 `pytest.ini` |
| WebSocket 集成测试 | ✅ 存在 | `tests/integration/websocket/test_aip_v3_ws_contracts.py` |
| V2 重启 E2E 恢复测试 | ❌ 缺失 | `docs/COMPLETE_SYSTEM_USABILITY_CLOSURE_PLAN.md` 明确标注 P0 缺失 |
| API ingress replay 覆盖 | ❌ 缺失 | GAP-512-001，同上文档 P1 缺失 |

### 2.6 整体可运行性判断

> **结论**：系统 **可构建、可启动、可连接、基本可操作、具备部分测试覆盖**。  
> 不是仅限 demo 的脚本式系统，而是具备真实服务框架和完整协议的系统。  
> 核心阻塞点在于：readiness/governance 跨端信号流有明确断层（见第 5 节），  
> 以及 V2 restart E2E 恢复测试缺失——这意味着"持续存活"的关键路径尚未有端到端测试验证。

---

## 3. 模型供给架构深度审查

> **这是强制性主要章节。基于真实代码，回答：系统是 API-first、原生多模态 API 主导、支持本地大模型，还是混合架构？**

### 3.1 MultiLLMRouter：核心模型路由层

V2 的模型调用全部经由 `core/multi_llm_router.py` 的 `MultiLLMRouter`。

#### 3.1.1 支持的 Provider 列表（从代码中读取）

```
自动发现优先级：Dashboard > CredentialVault > 环境变量
```

| Provider | 类型 | Adapter | multimodal 标记 | 备注 |
|----------|------|---------|----------------|------|
| openai | 外部 API | OpenAIAdapter | True（gpt-4o 等） | 支持 image input |
| anthropic | 外部 API | AnthropicAdapter | True（claude-3-5-sonnet 等） | 支持 image input |
| google | 外部 API | GeminiAdapter | True（gemini-2.0-flash 等）| 支持 image/audio/video |
| deepseek | 外部 API | DeepSeekAdapter | False | 文本为主 |
| groq | 外部 API | GroqAdapter | False | 主要是速度优化 |
| moonshot | 外部 API | MoonshotAdapter | False（Kimi） | 文本/长文档 |
| qwen | 外部 API（通义千问）| QwenAdapter | False（文本模型） | 代码/中文优化 |
| mistral | 外部 API | MistralAdapter | False | 欧洲模型 |
| perplexity | 外部 API | PerplexityAdapter | False | 搜索增强 |
| xai | 外部 API | XAIAdapter | False（Grok） | - |
| **ollama** | **本地/局域网服务** | **OllamaAdapter** | **False** | **指向 OLLAMA_URL，文本模型** |
| oneapi | 本地/自托管聚合 | OpenAIAdapter（兼容格式）| 取决于实际模型 | 支持自托管 One-API 网关 |

#### 3.1.2 任务类型 → Provider 优先级路由

```python
# core/multi_llm_router.py TASK_ROUTING_PREFERENCES
REASONING:      ["anthropic", "openai", "google", "deepseek", "xai"]
FAST_RESPONSE:  ["deepseek", "groq", "google", "openai", "moonshot"]
CODING:         ["deepseek", "qwen", "anthropic", "openai"]
AGENT_CONTROL:  ["anthropic", "openai", "google", "deepseek"]
```

**关键发现**：Ollama 未出现在任何任务类型的优先级列表中。这意味着即使配置了 OLLAMA_URL，本地 Ollama 模型也不会被自动选中——除非首选 provider 全部不可用，触发 fallback 路径。

#### 3.1.3 多模态路由机制

`CanonicalModelSupplyState`（`core/model_topology/canonical_model_supply_state.py`）是系统级多模态能力的规范表示：

```python
@dataclass(frozen=True)
class NativeMultimodalCapability:
    provider_id: str
    model_id: str
    is_natively_multimodal: bool       # 是否原生支持多模态
    supports_image_input: bool          # 图像 payload（base64/URL）
    supports_audio_input: bool          # 音频 payload
    supports_video_frame_input: bool    # 视频帧序列
    supports_streaming: bool
    supports_tool_use: bool
```

OpenClawd（核心控制器）在感知状态包含图像/音频/视频时，优先选择 `is_natively_multimodal=True` 的 provider/model。

**Ollama 的 multimodal 标记为 False**——本地 Ollama 模型不参与多模态路由。

---

### 3.2 多模态视觉能力层（VLM Pipeline）

多模态视觉理解通过节点链路提供：

```
Node_90_MultimodalVision（核心 VLM 节点）
  ├─ Gemini API（google.genai 直连，GEMINI_API_KEY 配置后）
  └─ Qwen3-VL（通过 OpenRouter API，OPENROUTER_API_KEY 配置后）
       注：OpenRouter 是 API 中间商，Qwen3-VL 运行在 OpenRouter 服务器，不是本地

Node_113_AndroidVLM（Android GUI 理解节点）
  ├─ 调用 Node_90（默认路径）
  ├─ Claude 直连（CLAUDE_API_KEY 配置后，绕过 Node_90）
  └─ GPT-4V 直连（OPENAI_API_KEY 配置后，绕过 Node_90）

Node_98_MultimodalFusion（多模态融合节点）
  └─ OpenAI API（直接调用 gpt-4o 等，OPENAI_API_KEY 配置后）
```

**关键发现**：所谓"Qwen3-VL 支持"实际是通过 **OpenRouter API 远程调用**，不是本地 Qwen3-VL 部署。代码中 `qwen_client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)`，这是一个外部 API 调用，不是本地推理。

---

### 3.3 本地大模型支持评估

#### 3.3.1 V2 侧本地模型支持

| 本地模型形式 | 实现状态 | 说明 |
|------------|---------|------|
| Ollama（用户本机/局域网服务器） | ✅ 接口闭合 | `OllamaAdapter` 完整实现，支持 llama3/mistral/codellama 等文本模型，通过 `OLLAMA_URL` 配置。**运行在用户机器上的 Ollama 服务，不是 V2 进程内推理** |
| OneAPI（自托管模型聚合网关） | ✅ 接口闭合 | 支持用户自托管的 One-API 实例，可接入私有部署的各种模型。**同样是外部服务调用** |
| V2 进程内直接推理 | ❌ 不存在 | V2 代码中无任何推理引擎（llama.cpp、transformers inference loop 等），所有推理均通过 HTTP 调用完成 |
| 本地多模态大模型 | ❌ 不支持 | Ollama multimodal=False，无本地多模态推理路径 |

#### 3.3.2 Android 侧本地模型支持

| 本地模型形式 | 实现状态 | 说明 |
|------------|---------|------|
| SeeClick GUI Grounding（NCNN/MNN 后端，端侧） | ⚠️ **仅接口定义** | `LocalGroundingService.kt` 是 Kotlin interface，默认实现是 `NoOpGroundingService`（返回错误，不运行推理）。无 NCNN/MNN native library，无模型文件加载代码 |
| MobileVLM V2-1.7B 端侧规划（llama.cpp/MLC-LLM）| ⚠️ **仅接口定义** | `LocalPlannerService.kt` 是 Kotlin interface，默认实现是 `NoOpPlannerService`（返回错误）。无 llama.cpp JNI 绑定，无 MLC-LLM 依赖 |
| Android 端直接调用外部 VLM API | ✅ 有代码路径（通过 V2 桥接）| Android 将截图通过 WebSocket 发给 V2 → V2 转发给 Node_113/Node_90 → 外部 VLM API |

**关键发现**：Android 的 `inference/` 包中的两个 `Local*Service.kt` 是**接口声明 + NoOp 安全默认值**，而不是真正运行中的端侧推理实现。这代表了一个架构预留空间，但当前没有真正的端侧推理能力。

---

### 3.4 模型供给架构综合判断

#### 3.4.1 当前实际运行路径

```
用户请求
  ↓
MultiLLMRouter（任务路由）
  ├─ 首选：外部 API（OpenAI / Claude / Gemini / DeepSeek / Groq ...）
  │    └─ 多模态：外部原生多模态 API（GPT-4o / Claude-3.5 / Gemini-2.0-flash）
  ├─ 降级：其他外部 API（按 TASK_ROUTING_PREFERENCES fallback）
  └─ 最终后备：Ollama（如配置 OLLAMA_URL）→ 文本模型，无多模态

VLM/视觉分析请求
  ↓
Node_90 / Node_113 / Node_98
  ├─ Gemini API（主路径）
  ├─ Qwen3-VL via OpenRouter（API 中间商，非本地）
  ├─ Claude API（直连）
  └─ GPT-4V API（直连）
```

#### 3.4.2 关键判断

**Q1: 系统主要是 API-first 吗？**  
✅ **是的，系统是 API-first 架构。** 核心推理能力依赖外部 provider（OpenAI / Claude / Gemini / DeepSeek 等），本地代码负责编排、上下文构造、工具调用、路由、故障转移和治理。

**Q2: 系统主要依赖原生多模态 API 吗？**  
✅ **是的，多模态能力主要来自外部原生多模态 API。** 视觉理解通过 Gemini、GPT-4V、Claude-3.5 等原生多模态 API 实现，OpenRouter 上的 Qwen3-VL 也是远程 API 调用。无本地多模态推理路径。

**Q3: 系统真正支持本地大模型吗？**  
⚠️ **部分支持，但有重要限制：**
- **文本大模型（V2 侧）**：通过 Ollama 适配器支持，但前提是用户在自己的机器上单独部署 Ollama 服务，且 Ollama 在任务路由优先级列表中排在所有外部 API 之后
- **多模态本地模型**：❌ 当前不支持
- **Android 端侧推理**：⚠️ 接口预留但无真正实现（NoOp 默认）
- **V2 进程内推理**：❌ 不存在

**Q4: 系统架构是否支持灵活混合使用本地模型和各种 API？**  
⚠️ **架构预留了混合空间，但当前实操上是 API-dominant：**

支持混合的架构元素：
- MultiLLMRouter 的统一抽象层（可新增任何 provider）
- ProviderConfig 的 `multimodal` 标记（已有明确数据结构）
- OllamaAdapter 完整可用（文本）
- OneAPI 聚合网关支持（可桥接私有部署）
- Android 侧 Local*Service 接口（架构上预留了端侧推理空间）

当前混合能力的阻断项：
- Ollama 不在路由优先级列表中（需手动设置路由策略）
- 无本地多模态 provider（Ollama multimodal=False）
- Android 端侧推理仅有接口，无 NCNN/llama.cpp 实现
- 无 routing policy/配置驱动的 local-first 切换机制

**Q5: 多模态和本地模型的关系是什么？**  
在当前架构中，多模态 = 外部 API，本地 = 文本 Ollama（可选）。两者在当前实现中是分离的：想要多模态就必须用外部 API；想用本地就只能用文本模型。要实现"本地多模态"需要新增真正的本地 VLM 支持（如 llava via Ollama，或部署本地多模态服务），这在当前代码中**没有完整闭环**。

---

### 3.5 实现"灵活运用本地大模型和各种 API"的现有基础与缺口

| 目标能力 | 现有基础 | 缺口 |
|---------|---------|------|
| 统一 provider 抽象 | ✅ MultiLLMRouter + ProviderConfig + BaseProviderAdapter | Ollama 不在路由优先级；无 local-first 策略配置 |
| 文本本地模型（Ollama）| ✅ OllamaAdapter 完整 | 路由优先级未配置；multimodal=False |
| 本地多模态 VLM | ❌ 无 | 需新增本地 VLM provider（如 llava via Ollama，或独立本地 VLM 服务）|
| OneAPI 私有部署桥接 | ✅ OneAPIAdapter | 依赖用户自行部署 One-API 实例 |
| Android 端侧文本推理 | ⚠️ 接口 | 需实现 LocalPlannerService（llama.cpp JNI 绑定）|
| Android 端侧视觉推理 | ⚠️ 接口 | 需实现 LocalGroundingService（NCNN/MNN native lib）|
| 路由策略（local-first/offline-fallback）| ❌ 无 | 需在 MultiLLMRouter 中增加策略层 |
| 多模态能力与 provider 位置的解耦 | ⚠️ 数据结构有，路由逻辑弱 | OpenClawd 偏好 natively_multimodal，但本地多模态 provider 不存在 |

---

## 4. 常驻存活 / 生命周期持续性审查

> **这是另一个强制性主要章节。判断系统是否具备真正持续存活的生命周期链。**

### 4.1 V2 侧生命周期机制

#### 4.1.1 守护进程层（GalaxyDaemon）

`daemon/galaxy_daemon.py` 实现了真正的 24/7 守护进程：

```python
class GalaxyDaemon:
    """Galaxy 24/7 Daemon
    - Automatic restart on failure
    - Health monitoring
    - Resource management
    - Graceful shutdown handling
    """

    config = {
        "health_check_interval": 30,      # 每 30 秒健康检查
        "metrics_collection_interval": 60, # 每 60 秒指标收集
        "max_restarts_per_hour": 10,       # 每小时最多重启 10 次
        "services": {
            "galaxy_main": {
                "command": ["python", "unified_launcher.py"],
                "restart_policy": "always",  # 总是重启
                "max_restarts": 10
            },
            "health_monitor": {
                "command": ["python", "-m", "health_monitor", "--watchdog"],
                "restart_policy": "always",
                "max_restarts": 20
            }
        }
    }
```

- **主循环**：`_main_loop()` 阻塞运行，每秒检查 shutdown_event；每 30s 运行健康检查；每 60s 收集指标
- **信号处理**：SIGTERM/SIGINT → 优雅关闭；SIGHUP → 热重载配置
- **进程监督**：`ProcessManager` 类追踪子进程状态，`should_restart()` 判断是否需要重启
- **资源监控**：CPU/内存/磁盘阈值（90%/95%/90%）超限时告警

**评估**：✅ GalaxyDaemon 是一个真正的守护进程框架，具备进程监督和自动重启能力。

#### 4.1.2 Systemd 集成

`systemd/` 目录存在（从目录结构可见），提供 Linux systemd service 文件，支持系统启动时自动启动 Galaxy、崩溃后自动重启。

**评估**：✅ Systemd service 文件存在，支持操作系统级守护。

#### 4.1.3 OpenClawd 心跳调度器

`core/openclawd_heartbeat.py` 的 `HeartbeatScheduler` 实现了精细的心跳管理：

```python
async def _loop(self) -> None:
    """Main heartbeat loop — sleeps between cycles, wakes on stop signal."""
    while not self._stop_event.is_set():
        try:
            await self._run_cycle()
        except Exception as exc:
            logger.exception("Heartbeat cycle failed: %s", exc)
        # 小步 sleep（5s chunk），保证 stop() 的响应性
        elapsed = 0
        chunk = 5
        while elapsed < self._interval_seconds and not self._stop_event.is_set():
            sleep_time = min(chunk, self._interval_seconds - elapsed)
            await asyncio.sleep(sleep_time)
            elapsed += sleep_time
```

**评估**：✅ 心跳调度器有异常保护（cycle 失败不崩溃），stop 响应及时。

#### 4.1.4 健康监控与节点监督

`health_monitor.py` 的 `HealthMonitor`：

```python
async def monitor_loop(self):
    while True:
        results = await self.check_all()
        for result in results:
            if not result["healthy"]:
                await self.handle_unhealthy_node(result)
        await asyncio.sleep(self.check_interval)  # 默认 30s
```

`core/health_check.py` 的 `HealthChecker` 提供 liveness check（进程存活）和 readiness check（服务就绪）。

`nodes/Node_77_TaskScheduler/main.py` 的调度循环：`_scheduler_loop()` 每 30s 检查 cron 任务，随 FastAPI app 生命周期管理（`startup`/`shutdown` 事件）。

**评估**：✅ 健康监控是常驻循环，不是单次检查。

#### 4.1.5 连接管理与重连

`core/connection_manager.py` 的 `ConnectionManager.reconnect()`：
- 指数退避（initial_retry_delay × backoff_factor ^ retry_count，上限 max_retry_delay）
- 最大重试次数配置

`core/nats_bus.py` 的 NATS 连接：
- `max_reconnect_attempts=-1`（指定 NATS URL 时无限重试）
- `reconnected_cb`/`disconnected_cb` 回调

`core/multimodal/webrtc_session_manager.py` 的 WebRTC 重连：
- 最大重连次数配置（`max_reconnects`）
- 重连失败时触发 transport_state="failed" 事件

**评估**：✅ 各传输层均有重连机制。

#### 4.1.6 状态持久化与恢复

| 持久化维度 | 实现 | 评估 |
|----------|------|------|
| Agent 状态恢复 | `agent_factory.py` 在启动时 "恢复历史 Agent" | ✅ |
| Session 状态 | `core/session_manager.py` + `core/attached_runtime_session_registry.py` | ✅ 结构完整 |
| Replay/Audit 持久化 | `core/replay_audit_persistence.py` + `core/replay_foundation.py` | ✅ |
| Flow Continuity 记录 | `core/delegated_flow_continuity_record.py`（via `FlowContinuityCoordinator`）| ✅ |
| Task 生命周期持久化 | `core/task_lifecycle_persistence.py` | ✅ |
| V2 重启后 E2E 恢复 | ❌ 无端到端测试 | 结构有但整体恢复路径未经完整测试验证 |

### 4.2 Android 侧生命周期机制

#### 4.2.1 连接持续性

`GalaxyWebSocketClient.kt` 实现了完整的重连生命周期：
- **指数退避重连**：1s → 2s → 4s → 8s → 16s → 30s + jitter（防止多设备同时重连）
- **离线任务队列**：`OfflineTaskQueue.kt`，SharedPreferences 持久化（进程重启后队列不丢失）
- **重连时自动 flush**：重连成功后自动上传离线期间缓冲的 task_result/goal_result
- **心跳维持**：定期发送 heartbeat，超时触发重连

**评估**：✅ Android 端重连和离线缓冲机制完整可信。

#### 4.2.2 Android 后台服务

Android 的 `service/` 包存在，包含 Android Service 组件（可在后台持续运行），配合 `UFOGalaxyApplication.kt` 实现应用级生命周期管理。

**评估**：⚠️ 后台 Service 框架存在，但 Android 进程被系统杀死时的恢复语义需要更详细验证（Android 电量管理/Doze 模式影响）。

#### 4.2.3 Continuity 集成

`AndroidContinuityIntegration.kt` + `DurableSessionContinuityRecord.kt` + `RecoveryActivationCheckpoint.kt` 提供了 Android 端的会话持续性框架。

**评估**：✅ 双端 continuity 骨架完整。

### 4.3 V2 侧生命周期监督链完整性判断

```
[用户机器保持开机]
  ↓
Systemd service / GalaxyDaemon（进程监督层）
  ├─ 进程崩溃 → 自动重启 galaxy_main 进程
  └─ 健康检查失败 → 触发重启

galaxy_main（unified_launcher.py / main.py 进程）
  ├─ bootstrap_subsystems()（子系统分别降级，不因单一失败崩溃）
  ├─ OpenClawd heartbeat_scheduler（常驻心跳循环）
  ├─ FastAPI + WebSocket server（常驻服务）
  ├─ health_monitor.monitor_loop()（常驻健康监控）
  ├─ Node_77 scheduler_loop（常驻任务调度）
  └─ NATS bus（可选，无限重连）

Android App
  ├─ GalaxyWebSocketClient（指数退避重连）
  └─ OfflineTaskQueue（持久化离线缓冲）
```

**评估**：

✅ **已验证的常驻存活路径**：
- GalaxyDaemon 守护进程框架（restart_policy="always"）
- Systemd service 集成
- OpenClawd heartbeat 常驻循环
- health_monitor 常驻循环
- 子系统降级（Redis 不可用不崩溃）
- Android 重连 + 离线队列

⚠️ **结构存在但未完整验证的连续性路径**：
- V2 重启后 session/flow 状态完整恢复（结构有，E2E 测试缺失）
- Android 进程被 Android OS 杀死后的恢复（Doze 模式影响未详细评估）

❌ **明确的缺口/阻断项**：
- V2 重启 E2E 恢复测试缺失（P0）
- API ingress replay 覆盖缺失（P1）
- Android 侧 governance/strategy artifact 主动推送路径不明确（影响治理决策准确性）

---

## 5. 分层结论：已验证 / 部分闭合 / 缺失阻断

### 5.1 ✅ 已由代码/测试验证的工作路径

| 能力域 | 具体路径 | 代码根据 |
|--------|---------|---------|
| 传输层 | AIP v3 WebSocket 双向通信 | `test_aip_v3_ws_contracts.py` 全覆盖 |
| 传输层 | 设备注册 / heartbeat | 同上 |
| 传输层 | Android 重连（指数退避）+ 离线队列 | `GalaxyWebSocketClient.kt` + `OfflineTaskQueue.kt` |
| 执行层 | task_submit → task_result 完整链 | handler 代码 + 集成测试 |
| 执行层 | goal_execution → goal_result 完整链 | handler 代码 |
| 执行层 | DelegatedFlowEntity + ExecutionTracker | `delegated_flow_entity.py` |
| 执行层 | HandoffEnvelopeV2 下行发送 | `android_bridge.py` + handler |
| 执行层 | DelegatedExecutionSignal 上报（PR-16）| `delegated_signal.py` handler |
| 模型供给 | 外部 API 路由（OpenAI/Claude/Gemini/DeepSeek/Groq...）| `multi_llm_router.py` |
| 模型供给 | Ollama 本地文本模型接入 | `OllamaAdapter` 完整实现 |
| 多模态 | 外部 VLM API（Gemini/GPT-4V/Claude）调用 | `Node_90`、`Node_113` 代码 |
| 生命周期 | GalaxyDaemon 守护进程框架（restart_policy="always"）| `galaxy_daemon.py` |
| 生命周期 | OpenClawd heartbeat 常驻循环 | `openclawd_heartbeat.py` |
| 生命周期 | 健康监控常驻循环 | `health_monitor.py` |
| 持久化 | OfflineTaskQueue SharedPreferences 持久化 | 文档+代码验证 |
| 持久化 | Replay/audit 持久化 | `replay_audit_persistence.py` |
| 治理 | compat/legacy blocking gate（V2 侧）| `compat_legacy_path_blocking_canonicalization.py` |

### 5.2 ⚠️ 结构存在但运行闭合待完整验证的路径

| 能力域 | 路径 | 说明 |
|--------|------|------|
| 治理 | Readiness/governance 四层信号跨端流转 | ReconciliationSignal AIP wire 层断层（见缺口 1） |
| 治理 | HandoffEnvelopeV2 上行 response gateway | V2 gateway handler 缺失（见缺口 2） |
| 生命周期 | V2 重启后 flow/session 完整恢复 | E2E 测试缺失 |
| 模型供给 | Ollama 在实际任务路由中被触发 | 不在任何 TaskType 的优先级列表，仅最终 fallback |
| 端侧推理 | Android LocalGroundingService/LocalPlannerService | 接口+NoOp 实现，无具体推理后端 |
| 持续性 | Android 在 Doze 模式下的后台存活 | Android OS 能量管理影响未充分评估 |

### 5.3 ❌ 代码层明确缺失的阻断项

| 缺口编号 | 描述 | 影响 |
|---------|------|------|
| GAP-01 | ReconciliationSignal 在 AipModels.kt 中无对应 MsgType | Android 的 readiness/governance artifact 无法传输到 V2，发布决策缺少 Android 维度输入 |
| GAP-02 | HandoffEnvelopeV2 上行 response 在 V2 gateway 无 handler | Handoff 链路单向（V2→Android），Android 的执行结果对 V2 不可见 |
| GAP-03 | V2 重启 E2E 恢复测试完全缺失 | "持续存活"的关键路径缺乏端到端验证 |
| GAP-04 | 本地多模态大模型 provider 完全缺失 | 想用本地模型就不能用多模态；想用多模态就必须用外部 API |
| GAP-05 | Ollama 不在 TASK_ROUTING_PREFERENCES | 配置了 Ollama 后仍然优先使用外部 API，本地优先策略不存在 |
| GAP-06 | Android 端侧推理无具体实现 | LocalGroundingService/LocalPlannerService 是 NoOp，无端侧推理能力 |

---

## 6. 最终判断

### 6.1 这两个仓库是否已形成完整产品系统？

**判断：已形成具有真实骨架的系统，但尚未完全闭合。**

更精确地说：

✅ **已形成**：
- 完整的服务框架（V2 FastAPI + WebSocket 服务器）
- 完整的 Android App（Kotlin）+ AIP v3 双端协议
- 真实可工作的端到端基础执行链（task/goal）
- 完整的多 LLM provider 路由和故障转移
- 守护进程和生命周期监督框架

⚠️ **尚未完全闭合**：
- 跨端治理信号流（readiness/governance artifact 传输）有明确断层
- V2 重启恢复无端到端测试验证
- 端侧推理是架构预留而非实际能力

### 6.2 系统的模型供给架构是什么？

**判断：当前是 API-first + 原生多模态 API-dominant 架构，有文本级本地模型支持（Ollama），无本地多模态路径，有混合架构基础但尚不完整。**

| 判断维度 | 结论 |
|---------|------|
| 主推理路径 | ✅ API-first（OpenAI/Claude/Gemini/DeepSeek/Groq 等外部 provider 主导） |
| 多模态路径 | ✅ 原生多模态 API-dominant（Gemini / GPT-4V / Claude-3.5 原生多模态 API） |
| 文本本地模型 | ✅ 支持（Ollama 适配器完整，但不在路由优先级，需手动触发） |
| 多模态本地模型 | ❌ 不支持（Ollama multimodal=False，无本地 VLM provider）|
| Android 端侧推理 | ⚠️ 架构预留（LocalGroundingService + LocalPlannerService 接口，NoOp 实现）|
| 混合架构基础 | ⚠️ 有统一抽象层（MultiLLMRouter），但缺路由策略和本地多模态支持 |

### 6.3 系统能否在计算机保持开机时持续存活？

**判断：具备持续存活的核心基础设施，但有验证缺口和一个重要限制。**

✅ **持续存活的已验证基础**：
- GalaxyDaemon（restart_policy="always"）
- Systemd service 集成
- health_monitor 常驻循环（30s 间隔）
- OpenClawd heartbeat 常驻循环
- 子系统降级不崩溃

⚠️ **持续存活的未完整验证点**：
- V2 重启后状态恢复（缺 E2E 测试）
- Android Doze 模式下的连接持续性

**结论**：在正常运行条件下（进程不崩溃 / 系统有 Daemon 监督），V2 具备常驻存活的架构支撑，Android 具备重连+离线缓冲保障。但"恢复后状态完整性"这一更高标准尚无完整验证。

### 6.4 要实现"持续存活 + 灵活本地模型和 API 混合使用"，当前最主要的缺口是什么？

按优先级排列：

**P0 — 阻断完整产品闭合的关键缺口：**
1. **ReconciliationSignal AIP wire 层**：在 `AipModels.kt` 增加 `MsgType.RECONCILIATION_SIGNAL`，建立 Android artifact → V2 gate 的传输路径
2. **HandoffEnvelopeV2 response handler**：在 V2 gateway 增加上行 handoff response 处理，打通 handoff 双向链路
3. **V2 重启 E2E 恢复测试**：验证 V2 重启后 flow/session 状态完整恢复能力

**P1 — 阻断"灵活本地+API 混合"的关键缺口：**
4. **本地 VLM provider**：在 MultiLLMRouter 中添加本地多模态 VLM 支持（例如 llava via Ollama，或独立本地 VLM 服务）
5. **路由策略层**：在 MultiLLMRouter 增加 local-first / offline-fallback 策略，让 Ollama 在适当场景被优先触发
6. **Android 端侧推理实现**：为 `LocalPlannerService`/`LocalGroundingService` 提供真正的 llama.cpp/NCNN 推理后端

**P2 — 完善持续存活保障的缺口：**
7. **Android Doze 模式存活**：明确 Android Service 在 Doze/Battery Optimization 下的存活策略
8. **API ingress replay 覆盖**：GAP-512-001

---

## 附录：审查评分矩阵

| 维度 | 成熟度 | 说明 |
|------|--------|------|
| 构建可重现性 | 🟢 90% | requirements.txt + Dockerfile + build_apk.sh 完整 |
| 启动可靠性 | 🟢 85% | 7 阶段启动，子系统降级保护 |
| WebSocket 传输层 | 🟢 90% | AIP v3 双端对齐，有集成测试 |
| 基础执行链（task/goal）| 🟢 90% | 最完整的路径 |
| Delegated canonical path | 🟡 75% | 骨架完整，handoff 上行 response 缺失 |
| 跨端治理信号流 | 🟠 35% | ReconciliationSignal wire 层断层 |
| 多 LLM API 路由 | 🟢 85% | MultiLLMRouter 完整，故障转移完善 |
| 本地文本模型（Ollama）| 🟡 60% | Adapter 完整，但路由优先级不配置 |
| 本地多模态大模型 | 🔴 0% | 不支持 |
| Android 端侧推理 | 🟠 20% | 接口存在，NoOp 默认，无真正实现 |
| 常驻存活基础设施 | 🟡 75% | Daemon/Systemd/心跳/健康监控完整，E2E 恢复测试缺 |
| 状态持久化与恢复 | 🟡 65% | 结构完整，恢复路径测试覆盖弱 |
| Operator/Audit 能力 | 🟡 65% | V2 侧完整，Android artifact 推送路径弱 |
| 整体 default-on 可信运行 | 🟠 40% | 等待治理信号流打通 + 本地模型策略补齐 |

**图例**：🟢 成熟可信（≥80%）｜🟡 基本有效（60%–79%）｜🟠 框架存在但不完整（30%–59%）｜🔴 缺失（0%–29%）

---

*本报告基于两仓截至审查时间点的实际代码，所有结论均有明确代码引用。*  
*审查者可直接使用第 5 节的分层结论表格驱动后续闭合工作。*
