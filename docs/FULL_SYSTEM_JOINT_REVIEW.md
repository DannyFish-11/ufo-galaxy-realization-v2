# 全系统联合审查报告：ufo-galaxy-realization-v2 + ufo-galaxy-android

> **审查性质**：以 V2 为权威中心，以 Android 为运行时参与者，基于两个仓库的真实代码、测试、
> 配置和集成路径，对完整双仓产品系统进行中文联合审查。  
> **主仓库**：`DannyFish-11/ufo-galaxy-realization-v2`  
> **伴随仓库**：`DannyFish-11/ufo-galaxy-android`（Android APK，独立仓库，本文结合
> `android_client/README.md`、`docs/ANDROID_PROTOCOL_ALIGNMENT.md` 和
> `galaxy_gateway/android_bridge.py` 等已集成内容进行分析）  
> **生成时间**：2026-04-25

---

## 目录

1. [系统完整认识：两仓合为一体的完整形态](#一系统完整认识)
2. [全链路运行分析：启动链、握手链、执行链](#二全链路运行分析)
3. [常驻存活审计：整套系统是否能持续存活](#三常驻存活审计)
4. [大模型供给架构审查：API-first、本地模型、混合能力](#四大模型供给架构审查)
5. [结论分层：已验证 / 结构存在 / 缺口阻塞](#五结论分层)
6. [最终系统判断](#六最终系统判断)

---

## 一、系统完整认识

### 1.1 两仓的系统定位

| 维度 | V2（`ufo-galaxy-realization-v2`）| Android（`ufo-galaxy-android`） |
|------|----------------------------------|---------------------------------|
| **角色** | 规范权威中心（Canonical Authority）| 运行时参与者（Runtime Participant）|
| **部署位置** | 用户 PC / 服务器（Python 进程） | 用户 Android 设备（Kotlin APK） |
| **进入点** | `python main.py` | Android App 前台启动 |
| **核心能力** | 编排、治理、模型路由、记忆、规划、证据沉淀 | GUI 控制、屏幕采集、传感器、辅助功能、本地状态 |
| **协议角色** | WebSocket 服务端（AIP v3.0） | WebSocket 客户端（AIP v3.0） |
| **真相权威** | V2 持有 `AttachedSessionRegistry`，是系统真相的最终裁判 | Android 上报 artifact/signal/result，受 V2 治理 |

两个仓库合起来的系统形态是：

> 一个以 PC 端 V2 为神经中枢、以 Android 设备为感知与执行延伸的**跨设备自主智能系统**。  
> V2 负责推理、规划、编排和治理；Android 负责捕获真实物理世界的多模态输入，  
> 并在 V2 指令下执行真实设备的 UI 操作和系统命令。

---

### 1.2 两仓的权责划分

```
┌──────────────────────────────────────────────────────────────────────────────┐
│   用户目标 / 自然语言输入                                                      │
└──────────────────────────┬───────────────────────────────────────────────────┘
                           │
            ┌──────────────▼───────────────────┐
            │   V2 — Canonical Authority         │
            │   main.py → unified_launcher.py    │
            │   DesktopPresenceRuntime           │
            │   OpenClawd（subject core）         │
            │   GalaxyMainLoopL4Enhanced（L4循环）│
            │   galaxy_gateway（API + 路由层）    │
            │   AttachedSessionRegistry（真相）   │
            │   MasterBrain（任务感知与派发）      │
            └──────────────┬───────────────────┘
                           │  AIP v3.0 WebSocket
                           │  ws://<host>:8765/ws/android
                           │  ws://<host>:8765/ws/device/{device_id}
            ┌──────────────▼───────────────────┐
            │   Android — Runtime Participant    │
            │   WebSocket 客户端（Kotlin）        │
            │   AccessibilityService（无障碍）    │
            │   ScreenCapture（屏幕采集）         │
            │   AgentMessageHandler.kt           │
            │   本地持久化 / 离线重放              │
            └──────────────────────────────────┘
```

---

## 二、全链路运行分析

### 2.1 V2 启动链（已由代码验证）

```
1. python main.py
   └─ 权威入口声明（validates runtime authority）
   └─ 调用 unified_launcher.py

2. unified_launcher.py → GalaxyUnified.start()
   ├─ CoreServiceLauncher     — 核心服务启动
   ├─ NodeSystemLauncher      — 节点系统启动
   ├─ L4EnhancementLauncher   — L4 增强模块启动
   ├─ MasterBrain             — 主脑初始化
   └─ UnifiedWebUI            — FastAPI + uvicorn HTTP/WS 服务

3. galaxy_gateway/bootstrap/lifecycle.py → lifespan()
   ├─ SessionRoaming + WakeEventBus + WakeRouter 初始化
   ├─ MasterBrain.start() （NATS 消息订阅、任务分发）
   └─ AndroidBridge 初始化（WebSocket 服务端就绪）

4. core/startup.py → bootstrap_subsystems()
   ├─ 子系统 1-14 按序初始化（含节点发现、世界模型、NATS 总线等）
   └─ runtime/entrypoint.json 写出（客户端自动发现用）

5. 系统就绪：
   POST /api/v1/chat           — 主聊天入口
   GET  /api/v1/projection/*   — 运行时状态投影
   ws://<host>:8765/ws/android — Android 连接端点
```

**代码位置**：`main.py`, `unified_launcher.py`, `galaxy_gateway/bootstrap/lifecycle.py`,
`core/startup.py`, `launcher/`

---

### 2.2 Android 参与者激活链（结构有证据，端侧代码在独立仓库）

```
1. Android App 启动
   └─ 初始化 WebSocketClient（Kotlin）
   └─ 连接至 ws://<host>:8765/ws/android（AIP v3.0）

2. 设备注册（Client → Server）
   └─ 发送 device_register 消息（含 device_id, capabilities, runtime_attachment_session_id）

3. V2 端 AndroidBridge 处理注册
   ├─ galaxy_gateway/android/handlers/registration.py
   │   └─ handle_device_registration()
   │       └─ core/attached_runtime_session_registry.py
   │           └─ register_session()  → AttachedSessionRegistryEntry
   └─ 回复 device_register_ack

4. 能力协商
   └─ 上报 capabilities（gui_control, voice_input, accessibility, screen, camera 等）
   └─ V2 记录设备能力，后续任务按能力路由

5. Android 进入 ACTIVE 状态，可接受：
   - ui_tree_request / action_execute / action_sequence_execute
   - screen_capture / screen_stream_start
   - gui_click / gui_swipe / gui_input 等 GUI 操作
   - app_start / app_stop / system_command
```

**V2 端有完整接收代码**；Android 端 Kotlin 实现在独立仓库
`DannyFish-11/ufo-galaxy-android`（`AgentMessageHandler.kt` 等）。

---

### 2.3 跨仓交互流：输入、执行、结果回流

```
V2 发出任务指令
  └─ AndroidBridge._send_to_device()
       └─ AIP v3.0 WebSocket → Android 端

Android 执行
  ├─ AccessibilityService 执行 UI 操作
  ├─ ScreenCapture 截图
  └─ 上报 task_result / command_result / gui_screen_content

V2 吸收结果
  └─ galaxy_gateway/android/handlers/ 各 handler 解析
  └─ core/android_participant_truth_ingress.py — truth ingress（PR-4V2）
  └─ AttachedSessionRegistry 记录
  └─ MasterBrain 感知结果，驱动下一轮编排

屏幕内容 → VLM 分析链
  └─ gui_screen_content / screen_stream_data
  └─ Node_113_AndroidVLM（Android GUI 理解 VLM 节点）
  └─ 结果回流 V2 编排层
```

**已证实的闭环部分**：注册 → ACK → 任务分发 → 结果回流 → truth ingress → 注册表更新。  
**结构存在但未完全验证的部分**：端到端自动化任务从 V2 意图到 Android 执行再回到 V2 决策的完整闭环。

---

### 2.4 重连与连续性链路（已有专项代码）

V2 端对 Android 的断线重连有完整的分类处理逻辑（`handle_device_reconnect()`）：

| 场景 | V2 处理结果 |
|------|------------|
| Android 传输层断线重连，携带相同 `runtime_attachment_session_id` | `continuity_resume`：保留原有会话，仅更新 WebSocket 句柄 |
| Android 重连，ID 不匹配或不存在 | `new_attachment`：创建新会话 |
| 旧客户端不携带 ID | 向后兼容：按 `continuity_resume` 处理 |

代码位置：`galaxy_gateway/android/handlers/registration.py`,
`core/attached_runtime_session_registry.py`,
`galaxy_gateway/android_bridge.py`

---

## 三、常驻存活审计

### 3.1 V2 自身的长运行能力

| 机制 | 实现位置 | 状态 |
|------|---------|------|
| 事件循环永不退出（uvicorn + asyncio） | `unified_launcher.py` / FastAPI lifespan | ✅ 已实现 |
| L4 主循环（`GalaxyMainLoopL4Enhanced._main_loop()`） | `core/galaxy_main_loop_l4_enhanced.py` | ✅ 已实现 |
| 心跳调度器（`HeartbeatScheduler._loop()`） | `core/openclawd_heartbeat.py` | ✅ 已实现 |
| 自愈引擎（`SelfHealingEngine.start()`） | `nodes/Node_112_SelfHealing/main.py` | ✅ 已实现 |
| 节点健康监控循环（`HealthMonitor.monitor_loop()`） | `health_monitor.py` | ✅ 已实现 |
| 设备心跳超时检测（`_heartbeat_loop()`） | `core/device_communication.py` | ✅ 已实现 |
| NATS 消息总线（持续订阅） | `core/nats_bus.py`（条件启用） | ⚠️ 需配置 NATS |
| 信号处理（SIGTERM/SIGINT 优雅关闭） | `launcher/shutdown.py` | ✅ 已实现 |

**结论**：V2 本身是一个设计上的真长运行进程，只要机器不关机、进程不被手动停止，
V2 有充分的循环和守护机制保持自身存活。

---

### 3.2 Android 作为持久参与者的存活能力

| 机制 | 协议定义位置 | 状态 |
|------|------------|------|
| AIP v3.0 heartbeat（Client→Server） | `docs/ANDROID_PROTOCOL_ALIGNMENT.md` | ✅ 协议已定义 |
| `heartbeat_ack`（Server→Client） | 同上 | ✅ 协议已定义 |
| V2 端超时检测 + 设备下线标记 | `core/unified/connection_manager.py` | ✅ 已实现 |
| V2 端 reconnect 处理（分类重连） | `galaxy_gateway/android/handlers/registration.py` | ✅ 已实现 |
| Android 端自动重连逻辑 | 在 `DannyFish-11/ufo-galaxy-android` 独立仓库 | ⚠️ 需查 Android 端代码 |
| Android 端离线本地持久化 | 在 Android 独立仓库（协议层有 offline_sync 消息类型） | ⚠️ 协议有，端侧实现待验证 |

**全系统层面的关键问题**：  
V2 的 reconnect 接受逻辑已经完整，但"Android 设备端能否在网络抖动后自动重连、
重连后 runtime_attachment_session_id 是否正确恢复"，取决于 Android 仓库中
`WebSocketClient.kt` 的具体实现。V2 侧已为此准备好对应的 `continuity_resume` 路径，
但**全系统闭环的证据需要两侧代码同时满足**，目前 V2 侧已满足，Android 侧待确认。

---

### 3.3 全系统连续存活的综合判断

```
全系统连续存活 = V2 进程持续运行 AND Android 参与者持续可达

V2 进程持续运行：✅ 有充足循环 + 自愈 + 信号处理保障
Android 持续可达：⚠️ 协议层设计完整，端侧自动重连逻辑待独立仓库确认
```

**不阻塞日常使用的场景**：Android 保持在线，V2 持续运行 → 系统可持续存活。  
**仍有不确定性的场景**：Android 网络断线后的自动重连、Android App 被系统回收后的恢复，
以及 V2 进程崩溃重启后 Android 的重新附着——这些需要 Android 仓库的具体代码审查才能确认。

---

## 四、大模型供给架构审查

### 4.1 当前主要推理路径

**核心配置**（`config.json`）：

```json
{
  "default_llm_model": "gpt-4o"
}
```

**默认运行时就是以 OpenAI API 为主的 API-first 系统。**

`.env.example` 中配置的 API provider 列表：

| Provider | 环境变量 | 多模态 |
|----------|---------|--------|
| OpenAI | `OPENAI_API_KEY` | ✅（GPT-4o, GPT-5.4 等） |
| Anthropic | `ANTHROPIC_API_KEY` | ✅（Claude 系列） |
| Google | `GEMINI_API_KEY` / `GOOGLE_API_KEY` | ✅（Gemini 系列） |
| DeepSeek | `DEEPSEEK_API_KEY` | ⚠️ 主要文本 |
| OpenRouter | `OPENROUTER_API_KEY` | 取决于路由模型 |
| Mistral | `MISTRAL_API_KEY` | ⚠️ 主要文本 |
| Moonshot | `MOONSHOT_API_KEY` | ⚠️ 主要文本 |
| Groq | `GROQ_API_KEY` | ⚠️ 主要文本 |
| OneAPI 统一接入 | `ONEAPI_BASE_URL`（默认 `http://localhost:3000/v1`） | 取决于后端 |

`dashboard/backend/main.py` 的 `/api/v1/llm/providers` 端点同样列出了
OpenAI、Anthropic、Google 三大原生多模态 API provider，并明确标注 `"multimodal": true`。

**结论 A：当前系统是 API-first，以外部云端多模态 API（主要是 OpenAI gpt-4o 系列）
为核心推理后端。多模态能力主要来自外部原生多模态 API，而非本地模型。**

---

### 4.2 本地模型支持的真实层次

#### Node_79_LocalLLM — Ollama 集成（最完整的本地模型路径）

**文件**：`nodes/Node_79_LocalLLM/main.py`

| 能力 | 状态 |
|------|------|
| Ollama 客户端（`OllamaClient`） | ✅ 完整实现 |
| 模型管理（拉取/删除/列表） | ✅ 有 REST API |
| 同步推理 / 流式推理 | ✅ 已实现 |
| Function Calling（工具调用） | ✅ 已实现 |
| 按任务类型自动选模型 | ✅ 已实现（`select_model_by_task()`） |
| OpenAI 兼容 API（`/v1/models`, `/v1/chat/completions`） | ✅ 已实现 |
| 云端 fallback（本地失败时调用 Node_01 / OneAPI） | ✅ 有条件实现（`FALLBACK_ENABLED=true`） |
| 默认模型 | `qwen2.5:7b-instruct-q4_K_M`（通过 `DEFAULT_MODEL` 环境变量） |
| 默认 Ollama 地址 | `http://localhost:11434`（通过 `OLLAMA_URL` 环境变量） |

**这是系统中唯一有完整运行闭环的本地模型路径。**  
前提条件：用户本机已安装并运行 Ollama，并已拉取至少一个模型。

#### 其他与本地/多模态相关的节点

| 节点 | 能力 | 本地推理状态 |
|------|------|------------|
| `Node_55_MultiModal` | HuggingFace Transformers（文本+图像） | ✅ 本地推理（需 torch/transformers） |
| `Node_90_MultimodalVision` | 视觉处理 | 待查具体实现 |
| `Node_91_MultimodalAgent` | 多模态 Agent（含 MCP 接口） | 混合，路由至外部 |
| `Node_98_MultimodalFusion` | 多模态融合嵌入 | 内部调用 OpenAI API |
| `Node_113_AndroidVLM` | Android GUI 截图 VLM 理解 | 调用外部 VLM API |

**Node_55_MultiModal 是系统中另一条本地多模态推理路径**（通过 HuggingFace Transformers
加载本地模型），但其主要能力依赖 `transformers`/`torch`/`Pillow` 运行时环境，
在降级模式（transformers 未安装）下功能不可用。

#### 本地模型支持层次总结

```
Layer 1: Android 设备端本地推理
  → 无。Android 参与者角色是 UI 控制和传感器采集，不承担本地推理。

Layer 2: V2 主机本地模型（Ollama）
  → ✅ Node_79_LocalLLM 有完整 Ollama 集成，含 fallback 机制。
     但 Node_79_LocalLLM 是一个独立节点服务，V2 核心编排链路
     是否实际路由到它，取决于配置和运行时调用图。

Layer 3: V2 主机本地多模态（HuggingFace）
  → ✅ Node_55_MultiModal 有本地 HuggingFace 推理能力，但依赖
     transformers/torch 安装。

Layer 4: LAN/私有服务接入
  → ✅ OneAPI 统一接入层（ONEAPI_BASE_URL），可对接任何兼容 API 的
     自托管模型服务（包括 vLLM, llama.cpp, Xinference 等）。
     Node_79_LocalLLM 的 fallback 也指向 OneAPI 端口。

Layer 5: 本地多模态推理（VLM on-device）
  → ⚠️ Node_113_AndroidVLM 目前调用外部 VLM API，非本地推理。
     Node_90_MultimodalVision 具体实现待进一步确认。
```

---

### 4.3 多模态能力与部署位置的关系

```
多模态输入采集（Android 侧）：
  Android 截图 → AIP WebSocket → V2 galaxy_gateway → Node_113_AndroidVLM
  Android 摄像头/麦克风 → AIP → V2（协议有定义，实现待确认）
  MultimodalBus（V2 侧）接收并融合各路多模态输入

多模态推理执行（推理位置）：
  主路径 → 外部原生多模态 API（OpenAI GPT-4o, Gemini, Claude 等）
  备用路径 → Node_55_MultiModal（本地 HuggingFace，需本地 GPU/CPU 资源）
  Android GUI 理解 → Node_113_AndroidVLM（目前调用外部 VLM API）

结论：
  多模态输入采集 = Android 负责
  多模态推理 = 主要外部 API，本地备用路径存在但非主链路
```

---

### 4.4 统一 provider 抽象与路由能力

系统中存在多个层面的 provider 抽象：

| 抽象层 | 位置 | 状态 |
|--------|------|------|
| `ModelProvider` enum（OpenAI/Anthropic/DeepSeek/Google/Ollama） | `core/opencode_engine.py` | ✅ 枚举存在 |
| `LLMClient`（支持 ollama/openai 等多 provider） | `galaxy_gateway/enhanced_nlu_v2.py` | ✅ 实现存在 |
| `BaseLLMClient` / `LocalLLMClient` | `enhancements/coding/llm_code_generator.py` | ✅ 本地客户端实现 |
| `OllamaClient` + OpenAI 兼容层 | `nodes/Node_79_LocalLLM/main.py` | ✅ 完整实现 |
| OneAPI 统一接入（`ONEAPI_BASE_URL`） | `.env.example` | ✅ 配置层支持 |
| 主编排层（OpenClawd）的模型路由策略 | `core/openclawd.py`（未在本次搜索中完整展开） | ⚠️ 需进一步确认主链路路由逻辑 |
| Fallback 机制（本地 → 云端） | `nodes/Node_79_LocalLLM/main.py` | ✅ 有实现 |

**现状**：各子系统和节点层面有多个 provider 抽象，节点级别的切换（Ollama vs API）是可配置的。
但 V2 核心编排链路（`OpenClawd`）对本地模型的实际路由情况需要进一步确认，以判断
"灵活切换 API + 本地模型"在主编排路径上是否真正闭环。

---

## 五、结论分层

### A 类：已由真实代码/测试/集成路径证实

1. **V2 启动链完整**：`main.py` → `unified_launcher.py` → FastAPI + uvicorn + 子系统 bootstrap，
   代码完整，有专项测试覆盖。

2. **Android 设备注册 + 重连协议完整**（V2 侧）：`handle_device_registration()`、
   `handle_device_reconnect()`、`AttachedSessionRegistry`、`continuity_resume` 分类，
   代码和单元测试均存在（`tests/test_prl_android_v2_joint_continuity.py` 等）。

3. **AIP v3.0 消息协议完整定义**：完整的消息类型矩阵，双向消息映射，协议文档
   `docs/ANDROID_PROTOCOL_ALIGNMENT.md` 已详细记录。

4. **V2 长运行机制存在**：L4 主循环、心跳调度器、自愈引擎、健康监控循环均有代码实现，
   形成多层守护。

5. **本地 LLM（Ollama）路径在节点层完整**：`Node_79_LocalLLM` 有完整实现，含
   模型管理、推理、流式、工具调用、OpenAI 兼容 API，以及云端 fallback。

6. **多 API provider 支持**：`.env.example` 和 `dashboard/backend/main.py` 均显示系统
   支持 OpenAI、Anthropic、Google、DeepSeek、OpenRouter 等多个外部 API provider。

7. **多模态输入融合层存在**：`core/perception/multimodal_bus.py` 有接收并融合图像、
   音频、屏幕、传感器输入的完整框架。

8. **OneAPI 统一接入层配置**：`ONEAPI_BASE_URL` 环境变量已预置，Node_79 的 fallback
   也指向 OneAPI 端口，为接入私有部署/自托管模型提供了接入层。

---

### B 类：结构存在，但尚未构成完整可操作闭环

1. **V2 核心编排链路对本地模型的实际路由**：`Node_79_LocalLLM` 存在，
   但 `OpenClawd` 的主推理路径是否已实际路由到 Node_79，需要主链路调用图的进一步确认。
   目前配置的 `default_llm_model` 是 `gpt-4o`，说明主路径仍以外部 API 为主。

2. **Android 端自动重连与会话恢复**：V2 侧的 reconnect 逻辑已完整，但 Android 端
   Kotlin 代码（`WebSocketClient.kt` 中的自动重连策略、退避算法、离线队列）在独立仓库，
   未在本次审查范围内直接验证。协议和接收侧已就绪，发起侧待确认。

3. **端到端自动化任务的完整双仓闭环**：协议定义了 `task_submit → task_assign →
   task_result` 这条完整链路，V2 侧有发送和接收代码，但从"V2 意图产生"到
   "Android 执行完成"再到"V2 决策消费结果"的完整端到端集成测试，
   需要独立仓库 Android 代码配合才能全面验证。

4. **多模态本地推理路径（Node_55）的主链路集成**：`Node_55_MultiModal` 有本地
   HuggingFace 推理能力，但是否在主任务路径中被实际调用，需要确认编排层调用图。
   降级模式（transformers 未安装）下功能不可用，生产环境依赖实际安装验证。

5. **Android 音频/摄像头多模态输入的完整链路**：协议中有音频/媒体消息类型定义，
   `MultimodalBus` 有接收框架，但从 Android 端捕获到 V2 VLM 处理的完整链路
   在当前代码中未完整展示端到端路径。

6. **Android 离线本地持久化与离线重放**：协议层定义了 `offline_sync`、`data_sync`
   等消息类型，但端侧的离线队列实现、重放逻辑需要 Android 仓库代码确认。

---

### C 类：缺失、不清晰或阻塞整套系统灵活化的关键问题

1. **主编排层（OpenClawd）对本地模型的真实路由尚未可见**：要实现"灵活使用本地模型
   + 各种 API"，必须在主编排层有统一的 provider 路由策略（能力评分、任务类型匹配、
   cost/latency 标签、fallback 策略等）。当前可见的抽象分散在各子系统和节点中，
   尚无明确的"主编排路由策略模块"。

2. **Android 设备端本地模型推理：不存在**。Android 的角色是 UI 控制和传感器采集，
   不进行本地 LLM/VLM 推理。"设备端本地跑大模型"这一能力在本系统架构中不适用。

3. **本地多模态 VLM 闭环不完整**：Android VLM 理解（`Node_113_AndroidVLM`）调用的是
   外部 VLM API，而非本地 VLM。如果目标是"本地多模态推理"，需要在 Node_113 级别
   接入本地 VLM（如 llava/qwen-vl 通过 Ollama 或 vLLM），目前这条本地路径不存在。

4. **全系统存活的 Android 侧证据缺口**：系统是否"真正一直活着"，取决于 Android App
   在手机端的存活策略（前台服务、电池优化白名单、屏幕常亮、网络重连）。这些由
   Android 独立仓库决定，当前 V2 无法单方面保证全系统的 Android 侧存活。

5. **缺乏全系统层面的集成测试**：现有测试（`tests/` 目录）主要覆盖 V2 侧协议、
   注册、reconnect 等单元逻辑，缺乏真实的双仓端到端集成测试
   （即模拟真实 Android 客户端全程参与的系统级测试）。

---

## 六、最终系统判断

### 6.1 这两个仓库合起来，是否已形成一套完整可操作的产品系统？

**结论：基本成立，但有条件。**

> 在 Android 设备在线、V2 进程运行、API Key 配置正确的前提下，
> 这两个仓库合起来已能形成一套可用的跨设备智能系统：
> 用户可以向 V2 发送指令，V2 协调 Android 完成设备操作，结果回流 V2。
> 主链路的代码是真实存在的，不是仅有抽象。

**有条件的地方**：  
Android 端的具体实现（自动重连、离线持久化、长期存活策略）需要独立仓库代码的进一步确认。
目前系统级闭环的 V2 侧已完整，Android 侧部分有协议保障但端侧实现需核查。

---

### 6.2 系统是否有真实的从启动到活跃使用的链路？

**结论：有，V2 侧主链路清晰可执行。**

```
python main.py
→ bootstrap（14 个子系统）
→ FastAPI + uvicorn 就绪（/api/v1/chat 等入口可用）
→ Android 通过 AIP v3.0 连接注册
→ 系统进入活跃运行状态
```

---

### 6.3 系统能否持续存活？

**结论：V2 侧具备充分的常驻保障；全系统存活依赖 Android 侧的端侧持久化实现。**

- V2：多层循环 + 自愈 + 健康监控 → ✅ 真长运行能力
- Android：协议层有心跳，V2 侧 reconnect 完整，端侧自动重连待验证 → ⚠️ 有条件

---

### 6.4 当前系统的模型供给性质

```
主要性质：API-first，原生多模态 API 主导
  - 默认模型：gpt-4o（OpenAI）
  - 多模态推理：主要依赖外部云端多模态 API（GPT-4o, Gemini, Claude 等）

本地模型能力：节点层存在，主链路路由待确认
  - Node_79_LocalLLM：完整 Ollama 集成（文本，含 fallback）✅
  - Node_55_MultiModal：本地 HuggingFace（文本+图像，降级可能）✅
  - OneAPI 统一接入：LAN/私有服务接入层 ✅
  - Android 端本地推理：不适用（架构设计上不承担推理）❌

混合能力：架构预留，主路径未闭合
  - provider 抽象分散在多个子系统中，有基础结构
  - 主编排层（OpenClawd）是否已统一路由本地与 API，需进一步确认
  - 目前更准确描述是：API-first，本地节点存在，混合路由尚在架构层
```

---

### 6.5 要实现"灵活使用本地大模型 + 各种 API"，最关键的缺口是什么？

按优先级排序：

1. **【最高优先级】主编排层（OpenClawd）统一 provider 路由策略**  
   需要一个能在 gpt-4o / Ollama / oneAPI 后端之间按策略动态切换的路由层，
   而不是当前分散在各节点中的局部抽象。

2. **本地 VLM 闭环**  
   当前 Android VLM 理解依赖外部 API。如需本地多模态能力，需接入
   Ollama 的 llava/qwen-vl 等本地 VLM，打通 Node_113 的本地路径。

3. **Android 端存活策略确认**  
   需要确认 `DannyFish-11/ufo-galaxy-android` 中的
   `WebSocketClient.kt` 是否实现了自动重连、退避、前台服务常驻等保活机制。

4. **全系统端到端集成测试**  
   需要一套同时运行真实 Android 客户端（或模拟器）和 V2 的集成测试，
   覆盖注册 → 任务 → 结果 → 重连 → 状态恢复的全链路，才能对全系统做出
   "可操作闭环"的高置信度判断。

---

### 6.6 一句话总结

> 两个仓库合起来已是一套有真实主链路的跨设备智能产品系统，
> **当前性质是 API-first + 原生多模态 API 主导**，本地 Ollama 节点存在但不在主链路，
> 混合架构有基础结构但路由策略尚未在主编排层闭合；
> 全系统常驻存活的 V2 侧已充分，Android 侧保活需独立仓库代码确认；
> 下一步最关键的是在主编排层打通统一的 API + 本地模型路由策略，
> 以及确认 Android 端的持久连接保障能力。

---

*本报告基于 `ufo-galaxy-realization-v2` 仓库真实代码（2026-04-25 快照）和
`docs/ANDROID_PROTOCOL_ALIGNMENT.md`、`android_client/README.md`、
`galaxy_gateway/android_bridge.py` 等 V2 侧已集成的 Android 接口文档进行分析。
Android 端 Kotlin 源码（`DannyFish-11/ufo-galaxy-android`）部分结论需结合该仓库
代码进一步验证。*
