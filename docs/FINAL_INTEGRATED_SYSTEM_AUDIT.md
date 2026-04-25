# Galaxy 系统最终整合审查报告

> **文件定位**：本文为最终整合型审查产物，综合吸收前多轮系统审查结论，并通过直接代码验证做出新的纠偏和判断。
>
> **证据基准**：以真实代码、调用链、模块接口为第一证据，文档结论为辅助参考。
>
> **覆盖范围**：主仓库 `DannyFish-11/ufo-galaxy-realization-v2`（V2 控制平面），Android 仓库 `DannyFish-11/ufo-galaxy-android` 作为上下文验证。
>
> **时间节点**：2026-04-25，已覆盖所有已合入 PR（含 PR-533 之后的 V2 side 与 Android side 对齐包）。

---

## 目录

1. [系统最终定义](#1-系统最终定义)
2. [默认主运行链真实结构](#2-默认主运行链真实结构)
3. [L4 的真实定位（纠偏）](#3-l4-的真实定位纠偏)
4. [跨设备主链的真实闭环程度](#4-跨设备主链的真实闭环程度)
5. [模型供给架构的真实状态](#5-模型供给架构的真实状态)
6. [当前成熟度与完成度最终判断](#6-当前成熟度与完成度最终判断)
7. [P0 / P1 / P2 真实问题分级](#7-p0--p1--p2-真实问题分级)
8. [必须完整解决的 Closure 条件](#8-必须完整解决的-closure-条件)
9. [一句总评](#9-一句总评)

---

## 1. 系统最终定义

### 这套系统现在到底是什么

Galaxy 是一个**中心权威型分布式智能代理系统**，不是 P2P mesh，也不是普通聊天机器人。

具体结构：

| 层级 | 仓库 | 角色 |
|------|------|------|
| **V2 控制平面**（中心权威） | `ufo-galaxy-realization-v2` | 编排决策、能力调度、任务分发、真相维护、治理 |
| **Android 设备运行时**（受控执行节点） | `ufo-galaxy-android` | 本地 GUI/传感器/网络执行、结果上报、受控参与 |
| **节点网络**（能力扩展层，V2 侧） | V2 仓库内 `/nodes` 目录 | 130+ 专属能力节点（VLM、WebRTC、RAG、代码等） |

**关键定性**：

- Android 是 V2 的**受控执行延伸节点**，不是对等 peer
- V2 的 `OpenClawd` 是唯一的意图决策权威（`MODEL_ROLE_POLICY: PRIMARY = "primary"`）
- Mesh 层（`core/mesh_coordinator.py`）是覆盖在星型拓扑之上的 overlay 优化层，`MESH_ORCHESTRATION_EXCLUDED: bool = True` 明确声明 mesh 不是独立编排权威
- 所谓 "mesh" 场景下，编排权威仍在 V2，mesh 只优化传输路径

代码证据：
```python
# core/model_role_policy.py
class ModelRole(str, Enum):
    PRIMARY      = "primary"       # OpenClawd — sole decision authority
    ORCHESTRATOR = "orchestrator"  # E2E / Gateway — plan scheduling only
    EXECUTOR     = "executor"      # HybridExecutor / WindowsArbiter — action dispatch
    TRANSPORT    = "transport"     # WebSocket / relay — message delivery

# core/mesh_coordinator.py
MESH_TRANSPORT_ROLE: str = "MESH::OVERLAY_ENRICHMENT_ONLY"
MESH_ORCHESTRATION_EXCLUDED: bool = True
```

---

## 2. 默认主运行链真实结构

### 已验证的实际主运行链

```
用户/客户端请求
    │
    ▼
main.py  ← 唯一合法启动入口（SYSTEM_ORCHESTRATOR_AUTHORITY 哨兵）
    │  Phase 1-7: 配置加载 → 模式解析 → 环境检查 → 后台子系统 → 运行时 → 桌面层 → 就绪汇总
    ▼
SystemOrchestrator  (core/system_orchestrator.py)
    │
    ▼
unified_launcher.py  ← 从属启动器（非竞争性入口，PR-2 明确降级）
    │  服务编排：NATS、Redis、L4 模块、OpenClawd、FastAPI、Desktop 层
    ▼
DesktopPresenceRuntime (shell)
    └─ LIMINAL phase 内调用 OpenClawd.process()
          ▼
       OpenClawd (subject core) — core/openclawd.py
          Stage 1: 感知摄入（PerceptionFrame + multimodal_context）
          Stage 2: 连续认知（ContinuumOrchestrator → state_continuum）
          Stage 3: 执行路径分支 (_determine_execution_path)
              ├─ "local"        → DecisionExecutor → WindowsExecutionArbiter
              ├─ "cross_device" → CommandRouter.route_envelope()
              ├─ "hybrid"       → 两路并行
              └─ "none"         → 仅响应，不执行
          Stage 4: 执行（Manifest）
                ▼
             CommandRouter.route_envelope()  ← 唯一跨设备分发权威
                ▼
             galaxy_gateway/DeviceRouter.route_task()  ← 唯一传输调度权威
                ▼
             dispatch_to_websocket()  ← 终端 send+wait（asyncio.Event 机制）
                ▼
             Android 设备 / 远端节点
```

**关键收口**：

- `core/canonical_execution_chain.py` 明确声明了这条链，且以哨兵字符串形式记录了每个环节
- `core/command_router.py` 的 `route_envelope()` 是唯一合法的跨设备分发入口，所有其他调用路径（e2e_orchestrator、hybrid_executor 等）均标记为 adapter/facade
- `galaxy_gateway/routing/dispatch.py::dispatch_to_websocket()` 通过 `asyncio.wait_for(event.wait(), timeout=30s)` 实现同步等待 Android 响应

代码证据：
```python
# galaxy_gateway/routing/dispatch.py — 终端 send+wait 模式
# timeout 默认值 30.0 秒（send_command_to_device 调用时传入，可配置）
event = asyncio.Event()
task_events[task_id] = event
await asyncio.wait_for(event.wait(), timeout=timeout)  # 默认 30s
result = task_results.pop(task_id)
```

---

## 3. L4 的真实定位（纠偏）

### 先前理解的误区

之前的审查中，"L4 主循环"曾被理解为整套系统的核心主运行链。这需要明确纠偏。

### 代码实际情况

1. **`galaxy_main_loop_l4.py` 是一个 tombstone re-export 文件**

```python
# galaxy_main_loop_l4.py — 第 1 行注释即明确
"""
galaxy_main_loop_l4 — retired root module (re-export tombstone)
The authoritative startup chain remains main.py → unified_launcher.py.
The L4 runtime is managed through unified_launcher.py.
"""
from core.galaxy_main_loop_l4_enhanced import ...
```

2. **L4 是 unified_launcher.py 管理的增强模块，不是主运行链**

`L4EnhancementLauncher`（在 `unified_launcher.py` 中）负责启动 L4 模块。L4 是一套**自主认知增强循环**（感知 → 目标分解 → 规划 → 执行 → 监控 → 学习），作为后台增强运行，而非处理用户请求的主链。

3. **L4 组件均以"可选降级"方式加载**

```python
# core/galaxy_main_loop_l4_enhanced.py — 每个组件都 try/except
try:
    from enhancements.perception.environment_scanner import EnvironmentScanner
    _PERCEPTION_AVAILABLE = True
except ImportError as _e:
    _logger.warning(f"感知模块不可用: {_e}")
    EnvironmentScanner = None
    _PERCEPTION_AVAILABLE = False
```

### 修正后的定位

| 误解 | 实际情况 |
|------|---------|
| L4 是系统的核心主循环 | L4 是自主增强循环，主运行链是 `main.py → OpenClawd → CommandRouter` |
| L4 激活 = 系统进入 L4 级 | L4 在 `unified_launcher.py` 后台启动，是增强层，不代表整体成熟度 |
| L4 文件存在 = 主链通过 L4 | 根文件是 re-export tombstone，主链从未通过 L4 |

**结论**：系统以"L4"为名并不意味着整体运行在真正的 L4 自主水平。命名做了比实际更大的承诺。

---

## 4. 跨设备主链的真实闭环程度

### 已确认关闭的历史缺口

以下问题**已通过代码验证关闭**（前几轮审查标记但已修复）：

| 历史缺口 | 关闭证据 |
|---------|---------|
| HandoffEnvelopeV2 无上行 response handler | `galaxy_gateway/android/handlers/handoff_v2_result.py` 已存在并在 `android_bridge.py` 注册 |
| ReconciliationSignal AIP wire 层缺失 | `galaxy_gateway/protocol/aip_v3.py: RECONCILIATION_SIGNAL = "reconciliation_signal"` 已加入；`android/handlers/reconciliation_signal.py` 已注册 |
| DelegatedExecutionSignal 未处理 | `android_delegated_signal_ingress.py` + `android_execution_signal_reconciler.py` 完整链路 |
| MeshSession 无驱动 engine | `core/mesh/live_mesh_runtime_engine.py`（PR-J）+ `mesh_session_progression_driver.py` 已建立 |
| CommandRouter capability graph advisory-only | 哨兵 `CAPABILITY_GRAPH_SELECTION_ENFORCED` 声明 GAP-512-004 已关闭 |

### 仍然存在的实质性缺口

#### 缺口 A：HandoffV2 result 回调与 dispatch Event 断连（代码已验证）

**问题**：`handle_handoff_v2_result` 处理 Android 的 `handoff_result`/`handoff_ack`/`handoff_failure` 时，调用 `ingest_android_handoff_response()` 更新 `HandoffV2ResponseRuntime` 的回调注册表，但**不调用** `DeviceRouter.handle_task_result()`。因此依赖 `dispatch_to_websocket()` 中 `task_events[task_id].set()` 来完成等待的调用方会超时（30 秒后）。

```python
# galaxy_gateway/android/handlers/handoff_v2_result.py — 只调用 ingest，不通知 DeviceRouter
if _ingest_handoff_response is not None:
    outcome = _ingest_handoff_response(message)
    # 此处无 device_router.handle_task_result(task_id, result) 调用
    # 因此 dispatch_to_websocket 中等待的 task_events[task_id] 不会被 set，
    # 调用方将在 timeout 后（默认 30s）回退，而不是获得真实 handoff 结果
```

**受影响的路径**：通过 `DeviceRouter.send_command_to_device()` → `dispatch_to_websocket()` 发送 handoff_dispatch 消息后等待 `handoff_result` 响应的所有调用方。

**影响**：跨设备 handoff 路径的同步结果等待会超时回退，而不是获得真实的 Android 执行结果。

#### 缺口 B：Capability graph 目标验证为警告而非阻断（代码已验证）

虽然哨兵宣称 GAP-512-004 已关闭，但实际执行语义是：

```python
# core/command_router.py 哨兵字符串（注意措辞）
"Unconfirmed targets emit structured warnings; routing falls back gracefully "
"if the layer is unavailable."
```

能力图中未确认的目标仍能收到任务，只记录 warning。这意味着**能力调度仍不具有强约束力**——路由不会因为目标缺少必要能力而被阻断。

#### 缺口 C：Android 能力声明未真正进入编排调度（代码已验证）

Android 设备在注册时通过 AIP `device_registration` 上报 capabilities。`CapabilityAssimilationLayer.assimilate_device()` 将其摄入能力图。但 `CommandRouter.route_envelope()` 中的目标选择逻辑：

1. 首先检查 `envelope.targets` 中已有的目标（如果有则直接使用）
2. 只在没有显式目标时才查询能力图选择器

这意味着大多数跨设备调用（由 `OpenClawd.send_gateway_command()` 显式指定 `device_id`）**绕过了能力图匹配**，而不是基于能力选择最优目标。

#### 缺口 D：Staged mesh 路径未连接到 LiveMeshRuntimeEngine（代码已验证）

`CommandRouter` 的 `staged_mesh` 分支在 `_obs_mode = "staged_mesh"` 处标记了路径，但 `LiveMeshRuntimeEngine`（`core/mesh/live_mesh_runtime_engine.py`）和 `MeshSessionProgressionDriver` 是独立实现的，没有在 `CommandRouter` 的 `staged_mesh` 分支中被调用。

```python
# core/command_router.py — staged_mesh 仅作为观测模式标记
_obs_mode = "staged_mesh"
# 无 LiveMeshRuntimeEngine 调用
```

---

## 5. 模型供给架构的真实状态

### 供给链路（已验证）

```
OpenClawd.process()
    │
    ▼  (多种调用路径)
core/unified/llm_router.py — UnifiedLLMRouter (单例门面)
    │  策略驱动路由 (config/llm_routing_policy.yaml)
    │  遥测：成功率、延迟、fallback 率、成本
    ▼
core/multi_llm_router.py — MultiLLMRouter (实际路由引擎)
    │  支持提供商：OpenAI / Claude / Gemini / DeepSeek / Ollama
    ▼
OllamaAdapter (本地模型适配器，已实现)
    │  POST {base_url}/api/chat
```

### 积极发现

- **Ollama 本地模型在 provider pool 中**：`OllamaAdapter` 已实现，`TaskType.GENERAL → "llama3"` 的映射存在
- **统一路由策略层存在**：`core/unified/llm_router.py` 支持 YAML 策略文件配置
- **LLMManager 已作为 legacy 委派层**：旧的 `core/llm_manager.py` 委派到 `UnifiedLLMRouter`，迁移路径清晰

### 仍然存在的问题

#### 问题 1：OpenClawd 不一定通过 UnifiedLLMRouter 路由所有调用

`core/openclawd.py` 中，LLM 调用路径有多条：
- 主路径通过 `router.chat()` 调用（第 6486 行：`response = await router.chat(...)`）
- 此处的 `router` 来自局部变量，不一定保证是 `UnifiedLLMRouter` 实例

缺少一个在进程启动时强制所有 LLM 调用必须通过 `UnifiedLLMRouter` 的机制。

#### 问题 2：本地 VLM 未进入主路由链

Ollama 在 `multi_llm_router.py` 中仅映射到 `TaskType.GENERAL`，不覆盖视觉多模态场景。VLM 节点（如 `nodes/` 下的 vision 节点）通过节点网络调用，而不是通过统一 LLM 路由策略。本地 VLM 在能力上存在但不在统一模型策略的调度覆盖范围内。

---

## 6. 当前成熟度与完成度最终判断

### 系统处于哪个阶段

> **结论：主链可运行阶段 → 系统整合期过渡**，具体位于整合期初期。

不是：
- ❌ 纯架构骨架期（主链 skeleton 已完整）
- ❌ 主链未可运行（本地链路和基础跨设备链路均可运行）
- ❌ pre-production（整合层有实质性未闭合点）
- ❌ 完整成熟系统（P0/P1 级未闭合点阻止了这一判断）

是：
- ✅ 主链骨架完整（execution chain、capability assimilation、session truth 骨架均有代码）
- ✅ 基础跨设备操作可运行（command_only 路径正常）
- ✅ 信号处理层基本完整（handoff、reconciliation、delegated_signal 均有处理器）
- ⚠️ 整合层有实质性缺口（handoff result dispatch event 断连、capability 强约束缺失）
- ⚠️ 治理层框架完整但信号流未完全打通

### 各维度评估

| 维度 | 级别 | 说明 |
|------|------|------|
| 主链执行能力 | ✅ 可运行 | `main.py → OpenClawd → CommandRouter → dispatch_to_websocket` 完整 |
| 跨设备基础操作 | ✅ 可运行 | `command_only` 路径通过 asyncio.Event 等待机制完整 |
| 跨设备 handoff 结果闭环 | ⚠️ 有缺口 | `handoff_result` → `dispatch_to_websocket` Event 未连通 |
| 能力调度强约束 | ⚠️ 软执行 | 未确认目标 warning-only，不阻断路由 |
| 模型供给统一性 | ⚠️ 部分统一 | UnifiedLLMRouter 存在但不保证所有 LLM 调用必经此路 |
| Mesh 多设备协调 | ⚠️ 框架完整但未接入 | LiveMeshRuntimeEngine 存在但未在 staged_mesh 分支调用 |
| 治理/发布门控 | ⚠️ 框架完整但未接 CI | release_gate.py 存在但 CI pipeline 未与 governance verdict 对接 |
| L4 自主循环 | ⚠️ 增强模块 | L4 是后台增强，不是主运行链，组件均按需加载且可选降级 |
| WebRTC 任务集成 | ⚠️ 绑定框架完整 | `webrtc_task_lifecycle.py` 有 binding/teardown 但 live session 依赖实际 WebRTC 子系统 |
| 遗留路径清理 | ⚠️ 框架清理中 | compat 守卫存在但 legacy 路径仍在使用 |

---

## 7. P0 / P1 / P2 真实问题分级

### P0：必须完整解决，否则系统无法真正闭环

#### P0-1：HandoffV2 结果未能驱动编排续链

**问题**：`handle_handoff_v2_result` 更新了 `HandoffV2ResponseRuntime` 的回调注册，但没有通知 `DeviceRouter` 的 `task_events`。依赖 `dispatch_to_websocket` 等待机制的调用方将超时，而不是获得真实的 Android handoff 执行结果。

**代码证据**：
- `galaxy_gateway/android/handlers/handoff_v2_result.py` — 无 `device_router.handle_task_result()` 调用
- `galaxy_gateway/routing/dispatch.py:dispatch_to_websocket()` — 等待 `task_events[task_id]` Event

**影响**：整个跨设备 handoff 路径（agent_runtime 模式）的结果返回依赖超时，而不是真实结果驱动。这使跨设备 handoff 成为事实上的单向信道。

**Closure 条件**：`handle_handoff_v2_result` 必须在成功 ingest 后调用 `DeviceRouter.handle_task_result(task_id, result)`，将 handoff 结果回流到 `task_events` 通知机制中；或者在 `dispatch_to_websocket` 旁边建立平行的 `handoff_dispatch_await` 机制，明确区分 command_only 和 handoff 两种等待模式。

#### P0-2：Android 能力声明未有效进入编排选择决策

**问题**：Android 在注册时上报 capabilities（如 `touch`, `screen`, `camera`），`CapabilityAssimilationLayer` 摄入了这些能力。但 `OpenClawd.send_gateway_command()` 在构造 `TaskEnvelope` 时已显式指定 `device_id`，导致 `CommandRouter` 直接使用指定目标，绕过能力图匹配。

**代码证据**：
```python
# core/openclawd.py:send_gateway_command() — 已知 device_id 被直接传入 targets，
# required_capabilities 在此路径中未被设置（None 或空），导致能力图匹配被跳过
envelope = TaskEnvelope(
    ...
    targets=[device_id],       # 显式目标 → CommandRouter 优先使用，不查能力图
    # required_capabilities 未传入，默认为 None，命令路径中不触发能力匹配逻辑
)
```

**影响**：系统实际上是设备 ID 硬编码调度，而不是基于能力的智能调度。能力图在注册层面是完整的，但在调度决策层面被绕过。

**Closure 条件**：必须形成 "Android capability → capability graph → CommandRouter 真实能力匹配 → 最优目标选择" 的闭环，即让 `OpenClawd` 在发起跨设备调度时优先表达 `required_capabilities`，由 `CommandRouter` 基于能力图做目标选择，而不是总是显式传入已知 device_id。

---

### P1：影响系统整体一致性与可持续性

#### P1-1：能力调度强约束缺失（warning-only 路由）

**问题**：`CAPABILITY_GRAPH_SELECTION_ENFORCED` 哨兵虽宣称关闭 GAP-512-004，但实际语义是"unconfirmed targets emit structured warnings"——警告而非阻断。能力不匹配的目标仍可执行任务。

**影响**：系统无法保证任务只被具备对应能力的设备执行，能力调度的可靠性没有强保证。

**Closure 条件**：将 `required_capabilities` 不匹配从 warning 升级为可配置的 blocking（至少在非 degraded 模式下），并建立回退策略（capability mismatch → fallback to local 或 reject with reason）。

#### P1-2：多真相面未完全收敛

**问题**：系统存在三个共存的真相面：
- `TruthIntegrationLayer`（`core/truth_integration_layer.py`）
- `CanonicalSessionTruthRuntime`（`core/canonical_session_truth.py`）
- `MultiDeviceRuntimeProjection`（`contracts/multi_device_runtime_projection.py`）

虽然有 `truth_projection_boundary.py` 和 `truth_integration_layer.py` 试图整合，但没有单一不可绕过的真相写入路径。Android 状态更新可以通过多条独立路径到达 V2，而不经过统一的真相整合层。

**Closure 条件**：所有设备状态更新（来自 Android reconciliation、task result、heartbeat）必须收口到同一个真相摄入入口，消除并发真相写入路径。

#### P1-3：Staged mesh 路径与 LiveMeshRuntimeEngine 未连接

**问题**：`LiveMeshRuntimeEngine`（PR-J）和 `MeshSessionProgressionDriver` 已实现，但 `CommandRouter` 的 `staged_mesh` 分支仅记录观测模式，未调用这些引擎。多设备协调在分发层仍未利用真实的 mesh 引擎能力。

**Closure 条件**：`CommandRouter` 的 `staged_mesh` 路径必须实例化并驱动 `LiveMeshRuntimeEngine`，形成真正的多设备协调执行，而不只是并行分发。

#### P1-4：统一模型路由策略未成为不可绕过的唯一入口

**问题**：`UnifiedLLMRouter` 存在且 `LLMManager` 委派到它，但 `OpenClawd` 内部的 LLM 调用路径没有进程级强制约束。部分调用可能直接使用非 `UnifiedLLMRouter` 的模型接口。

**Closure 条件**：必须让 `UnifiedLLMRouter`（`core/unified/llm_router.py`）成为进程内唯一合法的 LLM 调用入口，所有其他调用路径（包括 `multi_llm_router` 直接调用）都必须通过它，并建立测试验证这一不变量。

---

### P2：影响系统上限与产品完成度

#### P2-1：本地 VLM 未进入统一模型路由策略

**问题**：Ollama 仅映射到 `TaskType.GENERAL`，不覆盖视觉任务。本地 VLM 节点（vision 节点）通过节点网络独立调用，不经过统一 LLM 路由策略，使得本地视觉能力无法被主编排层统一管理。

**Closure 条件**：将 `TaskType.VISION`/`TaskType.MULTIMODAL` 映射到本地 VLM provider，并通过 `llm_routing_policy.yaml` 实现可配置的本地优先路由策略。

#### P2-2：WebRTC 与任务生命周期未形成端到端闭环

**问题**：`core/webrtc_task_lifecycle.py` 提供了 `WebRTCTaskBinding` 绑定框架和 transport state → lifecycle action 分类逻辑，但：
- 系统没有在任务创建时自动建立 WebRTC 绑定的机制
- `teardown_binding_on_task_terminal` 的触发是主动调用，没有自动与 `CanonicalTask` 生命周期钩子集成

**Closure 条件**：WebRTC 绑定的创建/销毁必须与 `CanonicalTask` 生命周期事件自动集成，而不是由调用方手动管理。

#### P2-3：CI 流水线未与治理 verdict 对接

**问题**：`core/unified/release_gate.py` 存在，chaos 测试中使用了它，但没有证据表明 CI/CD 流水线在构建/发布时会：
- 检查 `delegated_flow_readiness_gate.py` 的 readiness verdict
- 以 governance verdict 阻止发布
- 跨 Android/V2 双仓做 E2E 验证

**Closure 条件**：CI pipeline 必须在 gate 步骤中执行 readiness/governance verdict 检查，任何 `NOT_READY` 或 `VIOLATION` 级别的 verdict 必须阻止发布。

---

## 8. 必须完整解决的 Closure 条件

以下是使系统从"主链可运行"升级为"完整成熟系统"所必须完整解决的事项，不是补一半：

### 闭环条件 1：Android handoff 结果必须真正驱动 V2 编排续链

**不是**：给 `handoff_v2_result.py` 加一行日志  
**必须是**：`handoff_result`/`handoff_failure` 到达 V2 时，V2 的等待机制（`dispatch_to_websocket` 的 `task_events` 或替代等待机制）被正确触发，OpenClawd 能拿到真实的 Android 执行结果而不是超时回退值，并且此结果能驱动后续的 state_continuum 更新

### 闭环条件 2：Android capability 必须进入编排决策的真实路径

**不是**：capability bus 注册了 Android 能力就算完成  
**必须是**：当 V2 发起跨设备任务时，如果任务有 `required_capabilities`，必须通过能力图真实匹配到最优 Android 设备，而不是由 OpenClawd 显式指定已知 device_id 绕过能力图，且当没有匹配设备时能够产生有意义的降级决策

### 闭环条件 3：统一模型路由策略必须成为不可绕过的单一入口

**不是**：`UnifiedLLMRouter` 类存在就算完成  
**必须是**：进程内所有 LLM 调用（无论来自 OpenClawd、节点、工具），都必须通过 `UnifiedLLMRouter` 执行，且有测试验证无绕过路径，cost tracking 和 fallback 策略对所有调用方一致生效

### 闭环条件 4：治理 verdict 必须连接到 CI/release 阻断

**不是**：`release_gate.py` 和 `readiness_gate.py` 框架存在就算完成  
**必须是**：双仓（V2 + Android）的 readiness/governance 评估结果能被 CI pipeline 读取，`NOT_READY` 和 `VIOLATION` verdict 能阻止 merge 或 release，且存在跨仓 E2E 验证用例

---

## 9. 一句总评

> **这套系统已完成从"分散模块"到"有骨架的中心分布式系统"的关键跃迁——主链可运行、信号框架完整、架构定义清晰；但在"骨架"和"真正闭环的成熟系统"之间，还有四个不可回避的结构性断层：handoff 结果未驱动续链、能力调度被显式 device_id 绕过、统一模型路由未成为强约束入口、治理 verdict 未接入 CI——这四点不解决，系统就还停留在"看起来完整"而不是"运行完整"的状态。**
