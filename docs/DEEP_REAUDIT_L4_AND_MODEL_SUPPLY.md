# Galaxy-Nexus 深度代码级再审查报告
## L4 主循环真实性 & 模型供给架构完整性

> **审查层级**：代码证据优先  
> **基准版本**：`DannyFish-11/ufo-galaxy-realization-v2` 当前主分支  
> **参照文档**：PR #828 `docs/FULL_SYSTEM_JOINT_REVIEW.md`（作为基准，本文独立重新核验）  
> **审查日期**：2026-04-25

---

## 目录

1. [审查前言与方法说明](#1-审查前言与方法说明)
2. [L4 主循环再审查](#2-l4-主循环再审查)
   - 2.1 [真实启动链追踪](#21-真实启动链追踪)
   - 2.2 [L4EnhancementLauncher：初始化组件 vs 运行主循环](#22-l4enhancementlauncher初始化组件-vs-运行主循环)
   - 2.3 [GalaxyMainLoopL4 的真实调用位置](#23-galaxymainloopl4-的真实调用位置)
   - 2.4 [L4 主循环与其他机制的关系](#24-l4-主循环与其他机制的关系)
   - 2.5 [L4 主循环真实性裁定](#25-l4-主循环真实性裁定)
3. [模型供给架构再审查](#3-模型供给架构再审查)
   - 3.1 [主推理路径真实结构（代码链追踪）](#31-主推理路径真实结构代码链追踪)
   - 3.2 [UnifiedLLMRouter 与 MultiLLMRouter 的真实分工](#32-unifiedllmrouter-与-multillmrouter-的真实分工)
   - 3.3 [本地 LLM（Ollama / Node_79）真实接入层级](#33-本地-llmollama--node_79真实接入层级)
   - 3.4 [本地 VLM / Node_113_AndroidVLM 真实状态](#34-本地-vlm--node_113_androidvlm-真实状态)
   - 3.5 [OneAPI 的真实系统层级](#35-oneapi-的真实系统层级)
   - 3.6 [Node_55_MultiModal 的真实状态](#36-node_55_multimodal-的真实状态)
   - 3.7 [模型供给架构裁定](#37-模型供给架构裁定)
4. [完整系统认知更新](#4-完整系统认知更新)
5. [证据分类汇总](#5-证据分类汇总)
6. [结论摘要](#6-结论摘要)

---

## 1. 审查前言与方法说明

本审查不复述已有文档结论，而是**重新回到代码、配置、函数调用链**进行独立核验。

**核心方法**：
- 从 `main.py` 出发，沿真实 `import` 和函数调用链追踪
- 所有结论标注来源文件和关键代码行
- 明确区分四类证据级别：
  - ✅ **代码直接证实**：有明确调用链或测试
  - 🔵 **可较强推定**：调用链可通，但无端到端运行记录
  - ⚠️ **结构存在但未真正接入**：类/模块存在，但默认路径不调用
  - ❌ **文档/命名声称，但代码证据不足**：仅有命名或注释，无对应代码路径

---

## 2. L4 主循环再审查

### 2.1 真实启动链追踪

#### 第一层：`main.py`

```python
# main.py
def _run_orchestrator_preflight() -> bool:
    from core.system_orchestrator import SystemOrchestrator
    orch = SystemOrchestrator(continue_on_failure=False)
    summary = orch.run_startup_sequence()
    ...

def main() -> int:
    ready = _run_orchestrator_preflight()   # Phases 1-7
    # 手交给 unified_launcher.py
    args = [sys.executable, str(launcher_path)] + sys.argv[1:]
    return subprocess.call(args)
```

`main.py` 本身**不直接初始化任何 L4 组件**，它只完成7个 preflight phase（load config / resolve mode / env checks / background hooks / runtime subject hooks / desktop surface hooks / readiness summary），然后以子进程方式调用 `unified_launcher.py`。

#### 第二层：`core/system_orchestrator.py`

```python
# core/system_orchestrator.py (Phase 5 注释)
Runtime subject: DesktopPresenceRuntime → OpenClawd.
# Phase 5 import check:
("core.openclawd", "OpenClawd"),
```

`system_orchestrator.py` 的 Phase 5 仅做**可用性检查**（import check），并不实例化或启动 L4 主循环。**L4 在此层不存在**。

#### 第三层：`unified_launcher.py`

```python
# unified_launcher.py 第 526 行
if self.config.enable_l4:
    async def start_l4():
        ...
        results = await self.l4_launcher.start_all()  # L4EnhancementLauncher
    tasks.append(start_l4())

# 第 883 行（命令行参数）
galaxy.config.enable_l4 = not args.no_l4
```

- `enable_l4` 默认值 = `True`（`launcher/bootstrap.py:147`）
- `--no-l4` flag 可关闭
- 默认启动路径**会**执行 `start_l4()` → `L4EnhancementLauncher.start_all()`

### 2.2 L4EnhancementLauncher：初始化组件 vs 运行主循环

这是本次审查最关键的发现点：

```python
# unified_launcher.py L4EnhancementLauncher.start_all()
async def start_all(self) -> Dict[str, bool]:
    # 感知模块
    self.l4_modules["environment_scanner"] = EnvironmentScanner()
    # 推理模块
    self.l4_modules["goal_decomposer"] = GoalDecomposer()
    self.l4_modules["autonomous_planner"] = AutonomousPlanner()
    self.l4_modules["world_model"] = WorldModel()
    # 学习模块
    self.l4_modules["learning_engine"] = AutonomousLearningEngine()
    # 执行模块
    self.l4_modules["action_executor"] = ActionExecutor()
    # 安全模块
    self.l4_modules["safety_manager"] = SafetyManager()
    return results
```

**关键发现**：`L4EnhancementLauncher.start_all()` 所做的事是**实例化 L4 的各个组件模块**（`EnvironmentScanner`、`GoalDecomposer`、`WorldModel` 等），但它**从不实例化 `GalaxyMainLoopL4` 类，也从不调用 `GalaxyMainLoopL4.start()` 方法**。

换句话说：`unified_launcher.py` 的默认主链路**只初始化了 L4 的子模块，而没有启动 L4 的主循环本身**。

### 2.3 GalaxyMainLoopL4 的真实调用位置

通过代码库全局搜索，`GalaxyMainLoopL4` / `get_galaxy_loop()` 被引用的位置如下：

| 位置 | 调用方式 | 是否在主链路 |
|------|---------|------------|
| `integration/websocket_server.py` | `self.galaxy_loop = get_galaxy_loop(...)` + `asyncio.create_task(self.galaxy_loop.start())` | ⚠️ 仅当 WebSocket 服务器启动时 |
| `integration/websocket_server.py` (第二个类) | `self.galaxy_loop = get_galaxy_loop()` | ⚠️ 同上 |
| `core/galaxy_main_loop_l4_enhanced.py` | 模块自身定义 | - |
| `galaxy_main_loop_l4.py` | tombstone re-export | - |

**结论**：`GalaxyMainLoopL4` 的 `.start()` 方法（即 `_main_loop()` 协程）**只在 `integration/websocket_server.py` 中被调用**，而 `integration/websocket_server.py` 本身**并没有被 `unified_launcher.py` 直接导入或启动**。

```python
# integration/websocket_server.py — 第 375-381 行
self.galaxy_loop = get_galaxy_loop({...})
# 在后台启动 L4 主循环
asyncio.create_task(self.galaxy_loop.start())
```

`unified_launcher.py` 中没有 `from integration import websocket_server` 或等效 import。`websocket_server.py` 是一个独立脚本/服务，不在默认启动链中。

### 2.4 L4 主循环与其他机制的关系

#### 与心跳 / 自愈 / 健康监控的关系

`unified_launcher.py` 主链路启动的是：
- NATS Bus（`core/nats_bus.py`）——可选（`GALAXY_NATS_URL` 未设置时为 no-op 模式）
- MasterBrain（`core/master_brain.py`）
- FastAPI / uvicorn（REST API 和 WebSocket 处理）
- `core/openclawd.py`（主认知/执行核心）

L4 主循环 `_main_loop()` 在 `GalaxyMainLoopL4` 内部自己处理一个感知→分解→规划→执行→学习→反思的**自治循环**，但这个循环**与上述守护机制是并列关系**，而非从属关系——前提是它真的被启动。

#### 与 OpenClawd 的关系

`OpenClawd` 是主认知/执行核心，`GalaxyMainLoopL4` 是一个**具有独立目标队列的自治循环**。二者**不是同一个系统的两个入口**：
- `OpenClawd.process()` 处理用户发来的单次请求（request-bound）
- `GalaxyMainLoopL4._main_loop()` 自主感知环境并生成目标（proactive）

在默认主链路中，`OpenClawd` 是真实激活的，`GalaxyMainLoopL4` 主循环未激活。

#### 关于 `--no-l4` flag 的意义

`--no-l4` 会跳过 `L4EnhancementLauncher.start_all()`，即不初始化 L4 子模块。然而由于 `GalaxyMainLoopL4.start()` 在主链路中本来就不被调用，`--no-l4` 实际控制的是**L4 子模块的初始化**，而不是"是否启动 L4 主循环"（因为主循环本来就没在启动）。

### 2.5 L4 主循环真实性裁定

| 问题 | 裁定 | 证据 |
|------|------|------|
| L4 是否是这套系统真实的主循环？ | **否，不是默认主循环** | `unified_launcher.py` 主链路不调用 `GalaxyMainLoopL4.start()` |
| L4 主循环代码是否完整存在？ | **是，代码完整** | `core/galaxy_main_loop_l4_enhanced.py` 中有完整的感知→执行→学习循环 |
| L4 主循环是否被接入过主运行链？ | **仅在 websocket_server.py 中接入** | `integration/websocket_server.py:381` |
| `enable_l4=True` 的默认配置下，L4 主循环是否运行？ | **不运行** | `L4EnhancementLauncher.start_all()` 只初始化子模块，不调用 `.start()` |
| L4 命名是否被夸大？ | **部分夸大** | 文档说"L4 级自主性智能系统"，但实际运行的是 OpenClawd 请求驱动路径 |

**最终判断**：
- L4 **组件层**（感知、规划、执行子模块）在 `enable_l4=True` 时确实被初始化
- L4 **主循环**（`GalaxyMainLoopL4._main_loop()` 这个自治循环）**不在默认主运行路径**
- L4 概念是真实的架构设计方向，但当前默认启动的系统是以 `OpenClawd` 为主认知核心的**请求驱动**系统，而非以 `GalaxyMainLoopL4` 为中心的**自主感知驱动**系统
- "L4 级"的定位应理解为**目标架构层级**，而不是当前已完全激活的运行模式

---

## 3. 模型供给架构再审查

### 3.1 主推理路径真实结构（代码链追踪）

主推理调用链（代码可直接追踪）：

```
用户请求
  ↓
core/openclawd.py → OpenClawd.process()
  ↓ 懒加载
OpenClawd._get_router()
  ↓
core/multi_llm_router.py → get_llm_router() → MultiLLMRouter 单例
  ↓
MultiLLMRouter.chat()
  ↓ route() → 任务分类 + 复杂度评估 → RoutingDecision
  ↓ 按优先级尝试 adapter.chat()
  ↓
[OpenAI | Anthropic | Google | DeepSeek | Groq | Ollama | OneAPI | ...]
```

同时存在另一条路径（通过 `core/unified/llm_router.py`）：

```
core/unified/llm_router.py → UnifiedLLMRouter 单例（门面）
  ↓ self._backend = MultiLLMRouter
  ↓ 转发给 MultiLLMRouter（相同底层）
```

`core/llm_manager.py` 是遗留兼容层，内部也委派给 `UnifiedLLMRouter`：

```python
# core/llm_manager.py
class LLMManager:
    def _get_router(self) -> Any:
        from core.unified.llm_router import get_unified_llm_router
        return get_unified_llm_router()
```

**关键发现**：三条路径（`LLMManager` / `UnifiedLLMRouter` / 直接 `get_llm_router()`）最终都指向同一个 `MultiLLMRouter` 单例，`core/multi_llm_router.py` 是**唯一真实的路由执行层**。

### 3.2 UnifiedLLMRouter 与 MultiLLMRouter 的真实分工

| 层次 | 模块 | 真实职责 |
|------|------|---------|
| **遗留兼容层** | `core/llm_manager.py::LLMManager` | 仅委派，无路由逻辑 |
| **门面单例层** | `core/unified/llm_router.py::UnifiedLLMRouter` | 加载策略 YAML（`config/llm_routing_policy.yaml`）、遥测、成本预算门控；转发给 MultiLLMRouter |
| **核心路由执行层** | `core/multi_llm_router.py::MultiLLMRouter` | 任务分类、复杂度评估、provider 选择、故障转移、断路器、adapter 调用 |
| **Adapter 层** | `OpenAIAdapter / AnthropicAdapter / GeminiAdapter / OllamaAdapter / ...` | 各 provider 的 HTTP 调用 |

`UnifiedLLMRouter` 增加的价值（Block-6 扩展）：
- 读取 `config/llm_routing_policy.yaml` 的策略驱动路由（优先级列表 + fallback_chain + SLO）
- 路由遥测（成功率、延迟、fallback 率、成本的滑动窗口）
- 成本预算门控（超出预算时降级）

这些功能是**真实实现并接入主链路**的，不是仅存在于文档。`OpenClawd._get_router()` 调用 `core/multi_llm_router.py::get_llm_router()`（绕过 UnifiedLLMRouter 门面），这意味着 UnifiedLLMRouter 的策略层在 OpenClawd 调用路径中**默认不经过**，除非调用方显式使用 `get_unified_llm_router()`。

### 3.3 本地 LLM（Ollama / Node_79）真实接入层级

#### Ollama 在 MultiLLMRouter 中的接入（主链路可用）

```python
# core/multi_llm_router.py 第 828-840 行
ollama_url = self._get_key("ollama")
if not ollama_url:
    ollama_url = os.environ.get("OLLAMA_URL", "")
if ollama_url and not ollama_url.startswith("your-"):
    cfg = ProviderConfig(
        name="ollama", api_key="", base_url=ollama_url,
        models=["llama3", ...], default_model="llama3",
        multimodal=False, env_key="OLLAMA_URL",
    )
    self.providers["ollama"] = cfg
    self.adapters["ollama"] = OllamaAdapter(cfg)
```

**✅ 代码直接证实**：Ollama 被配置为 `MultiLLMRouter` 的一个合法 provider，只要 `OLLAMA_URL` 环境变量或 `config.json` 中 `ollama` 键有值，即**进入主链路的 provider 池**，可被路由决策选中。

#### 路由优先级中的 Ollama 位置

```python
# TASK_ROUTING_PREFERENCES
TaskType.GENERAL: ["openai", "anthropic", "deepseek", "google"],
"ollama": {TaskType.GENERAL: "llama3"},  # 存在但不在 TASK_ROUTING_PREFERENCES 的首选列表
```

Ollama 在任务路由偏好表中**不出现在任何任务类型的首选提供商列表**，仅在 `PROVIDER_MODEL_MAP` 中定义了默认模型。因此：

- **配置了 `OLLAMA_URL`** → Ollama 进入 provider 池 → 可作为 fallback 或通过 `preferred_provider="ollama"` 强制指定
- **未配置 `OLLAMA_URL`** → Ollama 不进入池，主链路完全不涉及本地推理

这是 **⚠️ 结构存在但非默认首选**的情况，但与之前审查说"不在主编排闭环内"的描述有出入——**它实际上已接入主链路路由层**，只是优先级低、需要配置。

#### Node_79_LocalLLM（独立节点服务）

`nodes/Node_79_LocalLLM/` 是一个独立的 FastAPI 服务，提供：
- `/generate` - 本地 Ollama 推理
- `/models` - 模型列表
- `/fallback` to Node_01_OneAPI

这个节点**不是 `MultiLLMRouter` 的 Adapter**，它是独立部署的微服务节点。主链路通过 `MultiLLMRouter` 直接调用 Ollama HTTP API，而不是通过 Node_79 节点。Node_79 代表的是"节点层本地 LLM 服务"，而 MultiLLMRouter 代表的是"主编排层直接 Ollama 集成"——**二者是并行路径**，不是同一路径。

### 3.4 本地 VLM / Node_113_AndroidVLM 真实状态

```python
# nodes/Node_113_AndroidVLM/main.py
try:
    from core.android_vlm_engine import AndroidVLMEngine, SUPPORTED_VLM_PROVIDERS
    HAS_VLM_ENGINE = True
except ImportError:
    HAS_VLM_ENGINE = False
    AndroidVLMEngine = None
```

`Node_113` 是一个独立的 FastAPI 服务，用于 Android GUI 理解（VLM 分析截图、查找 UI 元素、生成操作计划）。它：
- 依赖 `core.android_vlm_engine.AndroidVLMEngine`（内部使用云端 VLM API，如 OpenAI GPT-4V / Gemini）
- **不在 `MultiLLMRouter` provider 池中**，是通过 HTTP 调用的独立节点
- 主要服务于 Android 设备控制场景，不是通用 LLM 推理

状态：**⚠️ 结构完整，但主编排层不直接调用**——`OpenClawd` 通过 `cross_device` 执行路径可间接触达，但不是主推理路径的组成部分。

### 3.5 OneAPI 的真实系统层级

```python
# core/multi_llm_router.py 第 842-858 行（OneAPI fallback 配置）
oneapi_key = self._get_key("oneapi")
if not oneapi_key:
    oneapi_key = os.environ.get("ONEAPI_API_KEY", "")
...
if oneapi_key and ... and oneapi_url:
    cfg = ProviderConfig(
        name="oneapi", api_key=oneapi_key,
        base_url=f"{oneapi_url}/v1",
        models=models, default_model=models[0] if models else "gpt-4o",
    )
    self.providers["oneapi"] = cfg
    self.adapters["oneapi"] = OpenAIAdapter(cfg)  # OneAPI 使用 OpenAI 兼容接口
```

```python
# core/oneapi_system_position.py（架构冻结文件）
"""
OneAPI is *not* a direct/native-multimodal top-layer provider.
It is an external aggregator...
OneAPI is always the **OneAPI Aggregator Horizon** — a lower architectural tier.
"""
```

**✅ 代码直接证实**：
- OneAPI 配置了 key + url 就进入 `MultiLLMRouter` provider 池，作为 `OpenAIAdapter` 接入
- OneAPI 支持动态模型发现（`/v1/models`）+ `config/api_config.json` 预配置模型
- 架构定位：OneAPI 是"聚合器层"，在 `TASK_ROUTING_PREFERENCES` 中不出现，不是默认首选，但可通过 `preferred_provider="oneapi"` 强制使用

之前审查对 OneAPI 的定位（lower-tier aggregator，非直接首选）**基本准确**。

### 3.6 Node_55_MultiModal 的真实状态

```python
# nodes/Node_55_MultiModal/main.py
try:
    from transformers import pipeline as hf_pipeline, AutoTokenizer, AutoModel
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False
```

`Node_55` 依赖 `transformers`、`torch`、`PIL`，这些**不在 `requirements.txt` 的默认安装项中**（需要额外安装）。状态：

- 未安装 transformers → Node 以 `degraded` 模式运行，API 可用但推理不可用
- 安装了 transformers → 可运行 HuggingFace pipeline（text-generation / image-captioning / VQA 等）
- **不接入 `MultiLLMRouter`**，是独立的 HuggingFace 本地推理节点

状态：**⚠️ 结构存在，需额外依赖，不在主链路**。

### 3.7 模型供给架构裁定

| 问题 | 裁定 | 证据 |
|------|------|------|
| 系统是否 API-first？ | **是，默认且主要路径是 API-first** | `MultiLLMRouter` 默认按 `TASK_ROUTING_PREFERENCES` 选 API provider |
| 默认模型是否仍是 gpt-4o？ | **不完全准确** | `openai` provider 的 `default_model="gpt-5.4"`；无 provider 时 fallback `"gpt-4o"` | 
| 本地 LLM（Ollama）是否在主链路？ | **有条件地在主链路** | 配置 `OLLAMA_URL` 后进入 provider 池，可被路由（但非默认首选）|
| 本地 VLM（Node_113）是否在主链路？ | **不在主推理链路** | 是独立节点，仅在 cross-device Android 场景使用 |
| OneAPI 是否被低估？ | **基本准确，无低估** | OneAPI 作为 OpenAI 兼容聚合器，进池后可用，定位准确 |
| UnifiedLLMRouter 的策略路由是否真实？ | **是，但 OpenClawd 直接绕过它** | `OpenClawd._get_router()` 直接调用 `get_llm_router()`（MultiLLMRouter），跳过 UnifiedLLMRouter 门面 |

**最重要发现（此前审查可能漏判的点）**：

1. **Ollama 已接入主链路路由层**：只要配置 `OLLAMA_URL`，Ollama 就是 `MultiLLMRouter` 的一个合法 provider，可作为 fallback 或强制指定。此前说"本地模型不在主编排链路"需要修正为"本地模型（Ollama）在条件满足时确实在主链路中，但不是默认首选"。

2. **UnifiedLLMRouter 的策略层在 OpenClawd 路径中被绕过**：`OpenClawd` 直接使用 `get_llm_router()`（即 `MultiLLMRouter` 单例），不经过 `UnifiedLLMRouter` 的策略/遥测/成本门控层。这意味着策略驱动路由（`llm_routing_policy.yaml`）在主要用户交互路径中不生效，除非调用方主动使用 `get_unified_llm_router()`。

3. **默认模型已从 gpt-4o 更新为 gpt-5.4**：`multi_llm_router.py` 中 `openai` provider 的 `default_model` 已设为 `"gpt-5.4"`，`gpt-4o` 仅作为无 provider 时的兜底 fallback 字符串。

---

## 4. 完整系统认知更新

### 4.1 系统定位是否需要修正？

**维持基本判断，但需细化**：

这套系统**仍应定义为 API-first 中心分布式系统**，这一判断不变。但需补充：

- **L4 方向是真实架构意图**，`GalaxyMainLoopL4` 的代码完整且设计合理，只是尚未进入默认主运行路径
- **本地模型的接入程度比此前审查所描述的更进一步**：Ollama 已在主链路路由层注册，不需要绕过 MultiLLMRouter，只需配置即可生效
- **模型供给统一程度较高**：三条历史路径（LLMManager / UnifiedLLMRouter / 直接 get_llm_router）已统一收敛到 MultiLLMRouter，"provider 路由需要进一步统一"的问题已在代码层基本解决

### 4.2 成熟度评估更新

| 维度 | 之前判断 | 本次代码核查更新 |
|------|---------|----------------|
| L4 主循环 | "L4 路径存在" | **更精确**：L4 子组件初始化，但自治主循环未激活于默认路径；WebSocket 集成路径中存在完整调用 |
| 本地模型接入 | "本地模型不在主编排链路" | **需修正**：Ollama 已在主链路路由层；Node_79 是独立节点服务，与主链路路由是并行路径 |
| 模型路由统一 | "OpenClawd provider 路由需要进一步统一" | **基本已解决**：三条路径统一到 MultiLLMRouter；但 UnifiedLLMRouter 策略层在主路径中被绕过 |
| 默认模型 | "默认 gpt-4o" | **已更新**：`openai` provider default 已改为 `gpt-5.4`，`gpt-4o` 仅兜底 |
| 系统架构阶段 | "架构 ready，pre-production" | **维持**：核心架构确实成熟，但 L4 自治循环仍是"目标态而非当前态" |

### 4.3 关键缺口重新排序

基于本次代码核查，关键缺口按真实优先级重新排序：

1. **L4 自治主循环尚未进入默认启动路径**（最大差距）
   - `L4EnhancementLauncher.start_all()` 只初始化子模块，不启动 `GalaxyMainLoopL4` 主循环
   - 系统实际运行的"自主性"来自 `OpenClawd` 的请求驱动路径，而非 L4 自治循环
   
2. **UnifiedLLMRouter 的策略层在主路径中被绕过**
   - `OpenClawd._get_router()` 直接用 `MultiLLMRouter`，跳过了 `UnifiedLLMRouter` 的 policy/telemetry/cost-budget 层
   - 策略驱动路由（YAML 配置的优先级、SLO、成本门控）在主要用户交互场景中不生效
   
3. **本地模型（Ollama）的默认优先级低**
   - 已接入主链路路由层，但不在 `TASK_ROUTING_PREFERENCES` 任何任务类型的首选列表中
   - 需要显式配置才能被选中

4. **Node_55_MultiModal 的 transformers 依赖未被默认安装**
   - 本地多模态能力依赖额外安装步骤，默认部署下不可用

---

## 5. 证据分类汇总

### 已被代码直接证实

- `main.py` → `unified_launcher.py` 的二进制调用链
- `enable_l4=True` 时 `L4EnhancementLauncher.start_all()` 运行
- `L4EnhancementLauncher.start_all()` 只初始化子组件，不调用 `GalaxyMainLoopL4.start()`
- `OpenClawd._get_router()` 调用 `MultiLLMRouter` 单例
- Ollama 配置后进入 `MultiLLMRouter.providers` 池，可被 `route()` 选中
- OneAPI 配置后作为 `OpenAIAdapter` 进入 provider 池
- `core/llm_manager.py` 完全委派给 `UnifiedLLMRouter`（后者委派给 `MultiLLMRouter`）
- `GalaxyMainLoopL4.start()` 在 `integration/websocket_server.py` 中被调用

### 通过调用链可较强推定

- 若 `OLLAMA_URL` 已配置，Ollama 会出现在 fallback 路由候选中
- 用户通过 WebSocket 提交目标时，L4 主循环可以真实运行（前提是 websocket_server.py 被启动）
- `UnifiedLLMRouter` 的策略层（策略 YAML）在调用 `get_unified_llm_router()` 的路径中确实生效

### 结构存在但未真正接入

- `GalaxyMainLoopL4` 的自治主循环（`_main_loop()`）——结构完整但默认不启动
- `integration/websocket_server.py` 对 L4 的完整集成——代码完整但 `unified_launcher.py` 不导入它
- `UnifiedLLMRouter` 的策略驱动路由——存在但被 `OpenClawd` 的直接调用路径绕过
- Node_55_MultiModal 的本地 HuggingFace 推理——节点存在但需额外依赖

### 文档/命名声称但代码证据不足

- "L4 级自主性智能系统"作为**当前运行态**的定义——代码证据显示 L4 自治循环未激活于默认路径，该定义仅适用于架构目标或 websocket 连接后的状态
- "--no-l4 不启动 L4 增强模块"的描述暗示 `--no-l4` 会关闭一个在运行的 L4 主循环——实际上 L4 主循环本来就没在默认路径中运行

---

## 6. 结论摘要

### L4 主循环

**L4 主循环是真实存在的完整代码，但在默认启动路径中未激活自治运行。**

- `core/galaxy_main_loop_l4_enhanced.py` 中的 `GalaxyMainLoopL4` 类代码完整、逻辑合理，包含感知→分解→规划→执行→学习→反思的完整自治循环
- `unified_launcher.py` 默认路径初始化了 L4 的各子模块，但**没有调用 `GalaxyMainLoopL4.start()`**
- L4 自治循环仅在 `integration/websocket_server.py` 中被调用，这是一个独立路径
- 系统当前默认运行的"主循环"是 `OpenClawd.process()`（请求驱动）+ FastAPI 服务，而非 L4 自治循环
- "L4 级"应理解为架构方向和目标成熟度，而非当前运行模式

### 模型供给架构

**API-first 判断成立，但本地模型（Ollama）的接入程度比之前审查所描述的更深。**

- 主推理路径：`OpenClawd` → `MultiLLMRouter` → 按任务类型选 API provider
- Ollama 已在 `MultiLLMRouter` 主链路路由层注册，配置即可用，不需要绕过主编排层
- OneAPI 同样在主链路路由层，作为 OpenAI 兼容聚合器，定位为 lower-tier fallback
- `UnifiedLLMRouter` 的策略驱动路由（YAML 策略 + 遥测 + 成本门控）是真实实现的，但在 `OpenClawd` 的主路径中被绕过
- Node_79 / Node_113 / Node_55 是独立节点层服务，与主链路路由并行，不是主链路路由的组成部分

### 系统真实成熟度

| 维度 | 评级 | 说明 |
|------|------|------|
| 主链路 API 推理 | **Production-ready** | OpenClawd + MultiLLMRouter 完整可用 |
| L4 自治主循环 | **Alpha / 代码完整未激活** | 代码完整，未进入默认启动路径 |
| 本地模型（Ollama）接入 | **Beta** | 在主链路路由层已注册，需配置，非默认首选 |
| 策略驱动路由 | **Beta（被主路径绕过）** | UnifiedLLMRouter 策略层存在但未在 OpenClawd 路径生效 |
| 跨设备分布式执行 | **Pre-production** | 架构完整，跨仓协作仍需端到端验证 |
| 系统整体阶段 | **Pre-production（主链路部分 Production-ready）** | 核心 API 推理路径稳定，L4 自治模式待激活 |

---

*本文档基于代码直接核查产出，所有结论均有对应文件和代码行支撑。*  
*如有分歧，以代码为准，文档描述为辅助参考。*
