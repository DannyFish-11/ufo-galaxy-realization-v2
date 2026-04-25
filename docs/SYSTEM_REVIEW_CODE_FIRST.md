# Galaxy-Nexus 系统级代码优先认知审查

> **审查原则**：结论必须回到真实代码。文档仅作"线索"，不作证据。  
> **审查范围**：`main.py`、`unified_launcher.py`、`core/openclawd.py`、`core/galaxy_main_loop_l4_enhanced.py`、`core/multi_llm_router.py`、`core/unified/llm_router.py`、`core/device_communication.py`、`galaxy_gateway/websocket_handler.py`、`galaxy_gateway/android_bridge.py`、`core/android_execution_signal_reconciler.py`、`core/android_v2_continuity_contract.py`、`config.json`  
> **审查日期**：2026-04-25

---

## 一、系统定义——它现在到底是什么

### 1.1 整体形态判断

基于代码实证，本系统是：

**请求驱动编排系统，附带可选自治循环增强层。**

- **主干路径**是 API 驱动的（FastAPI/uvicorn，端口 9000），请求进入 `core/api_routes.py`，路由至 `OpenClawd.process()`，决策后分支执行（local / cross_device / hybrid / none）。这一路径在任何配置下都存在且是核心。
- **L4 自治循环**（`GalaxyMainLoopL4` in `core/galaxy_main_loop_l4_enhanced.py`）是可选增强，受 `config.enable_l4` 开关控制，在 `unified_launcher.py::L4EnhancementLauncher.start_all()` 中条件启动。它维护自己的 `_goal_queue`，独立于主 API 路径。**L4 循环不是主运行路径。**
- NATS 总线存在（`core/nats_bus.py`），但 `unified_launcher.py` 明确注明："if `GALAXY_NATS_URL` is unset the bus operates in no-op mode and the system starts in single-machine mode"——NATS 是可选的调度通道，不是系统运行的前提。

### 1.2 V2 是不是绝对中心 authority

**是，V2 是唯一编排权威。**

代码证据：
- `core/android_v2_continuity_contract.py` 中明确写明两条策略常量：
  - `ANDROID_IS_DURABLE_PARTICIPANT_NOT_ORCHESTRATION_AUTHORITY_POLICY`
  - `V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY`
- `core/device_registry.py` 的 `_REGISTRY_ROLE` 明确：UDM（UnifiedDeviceManager）才是设备写入 SSOT，DeviceRegistry 只是索引/缓存层。
- `galaxy_gateway/android_bridge.py` 注释明确：`AndroidBridge` 不持有独立 presence authority，presence authority 在 UDM + UCM。

### 1.3 Android 在系统中的角色

Android 的真实角色是 **"第一类运行时宿主参与者"（First-Class Runtime Participant）**，而非第二权威中心：

- `core/android_runtime_host.py` 定义 `AndroidRuntimeHostRole`，分类依据是 `source_runtime_posture` 字段（`join_runtime` / `control_only`）——这说明 Android 是否成为 runtime host 取决于注册时的"表态"，而不是默认即是。
- Android 有 `FULL_RUNTIME_HOST` 和 `CONTROL_ONLY` 两个可能角色，但在 V2 中它始终是被调度的下游节点（执行委托方），而非编排层（调度发起方）。

---

## 二、默认主运行链核查

### 2.1 启动链

```
python main.py
  └─ main.py::main()
       ├─ Phase 1-7: core/system_orchestrator.py::SystemOrchestrator.run_startup_sequence()
       │     (7 个阶段：LOAD_CONFIG → RESOLVE_MODE → ENV_CHECKS → BACKGROUND_SUBSYSTEMS
       │                → RUNTIME_SUBJECT → DESKTOP_SURFACE → READINESS_SUMMARY)
       │     异常视为 non-fatal，继续向下
       └─ subprocess.call([python, unified_launcher.py, ...args])
             └─ unified_launcher.py::GalaxyUnified.start()
                  ├─ CoreServiceLauncher.start_all()       # NATS, Redis, etc.
                  ├─ NodeSystemLauncher.start_all()         # 节点系统（可选）
                  ├─ L4EnhancementLauncher.start_all()      # L4 模块（config.enable_l4=True 时）
                  └─ UnifiedWebUI.start()                   # FastAPI/uvicorn on port 9000
```

**关键事实**：`SystemOrchestrator.run_startup_sequence()` 中的 7 个阶段，每个阶段的异常都被 catch 为 "non-fatal"，系统会以 "DEGRADED" 状态继续启动。这意味着预飞检查不是硬阻断——实际能否正常运行取决于 `unified_launcher` 的真实依赖加载情况。

### 2.2 GalaxyUnified.start() 是主链还是外层包装

**结论：GalaxyUnified 是实际的异步服务编排层，是主链的核心执行者。**

- 它创建 FastAPI app → 加载 `core/api_routes.py`（唯一权威 API 层）→ 启动 uvicorn
- 所有用户请求最终通过此 FastAPI 实例处理
- `unified_launcher.py` 在文档上被定义为 "subordinate launcher component"，但代码层面它是异步服务真正落地运行的地方，`main.py` 只做了一次 `subprocess.call` 把控制权完整交给它

### 2.3 OpenClawd 在默认链路中的位置

`OpenClawd` 是**主体决策核心**，在请求-响应主链路上：

```
FastAPI POST /api/chat (or /api/v1/agent/chat)
  └─ core/api_routes.py → 路由到 chat endpoint
       └─ OpenClawd.process(message, ...)
            ├─ Stage 1: _run_multimodal_ingest()
            ├─ Stage 2: _run_continuum() → ContinuumOrchestrator.run()
            ├─ Stage 3: _determine_execution_path() → "local"|"cross_device"|"hybrid"|"none"
            └─ Stage 4: 根据 execution_path 分支
                 ├─ _delegate_local_manifestation()     → DecisionExecutor
                 ├─ _delegate_single_remote()           → CommandRouter → gateway
                 ├─ _delegate_multi_device_orchestration()
                 └─ none: 直接返回响应
```

`OpenClawd` 内部调用 LLM 的路径（见 `_get_router()`）：
```
OpenClawd._get_router()
  └─ core/unified/llm_router.py::UnifiedLLMRouter (进程级单例)
       └─ 委托 core/multi_llm_router.py::MultiLLMRouter (实际路由)
```

### 2.4 L4 组件的真实地位

`GalaxyMainLoopL4` / `GalaxyMainLoopL4Enhanced` **不在默认主链上**：

- 它们在 `L4EnhancementLauncher.start_all()` 中被初始化为独立对象，各自持有 `_goal_queue`
- `run_cycle()` 里通过 `_goal_queue.get_nowait()` 取目标——没有目标时直接跳过（返回空循环）
- L4 循环与主 API 请求路径是并行的两条通道，不是同一条主干
- 现有 L4 组件依赖 `enhancements/` 下的模块（`EnvironmentScanner`、`GoalDecomposer`、`AutonomousPlanner` 等），每个模块失败时 try/except 均降级为 `None`，`_PERCEPTION_AVAILABLE=False` 等标志说明运行时 L4 实际能力取决于可选依赖的安装状态

---

## 三、跨设备主链核查

### 3.1 Android 注册 / 会话建立

**有实现，且有规范：**

- `galaxy_gateway/websocket_handler.py` → `galaxy_gateway/android/handlers/registration.py::handle_device_register()`
- 强制 AIP v3+ 格式（`version >= 3.0`）；trace_id / route_mode 缺失时自动注入
- 注册时调用 UDM 写入 canonical device 状态，DeviceRegistry 维护本地索引
- 会话建立后写入 `AttachedRuntimeSessionRegistry`（`core/attached_runtime_session_registry.py`）

### 3.2 V2 → Android 任务分发 spine

**有 canonical path，但中间层复杂：**

```
OpenClawd._delegate_single_remote()
  └─ CommandRouter → gateway / cross_device_execution_chain.py
       └─ galaxy_gateway/android_bridge.py::AndroidBridge.send_task()
            └─ WebSocket 发送 AIP v3 command 帧 → Android 端
```

- `AndroidBridge` 是 translation adapter（不是 dispatch authority）
- 实际的 dispatch authority 在 `galaxy_gateway/device_router.py`（DeviceRouter）
- `core/android_runtime_dispatch_binding.py` 做 dispatch 绑定记录
- `core/delegated_runtime_execution_tracker.py` 跟踪执行状态

### 3.3 Android → V2 结果回流

**存在 canonical reconciler，但连接完整性需要核查：**

`core/android_execution_signal_reconciler.py` 是规范化结果回流的核心：
- 定义 `AndroidSignalKind`（ack/progress/partial_result/final_result/error/timeout/cancelled）
- `extract_signal_envelope()` 从 inbound 消息提取身份字段
- `reconcile_android_execution_signal()` 更新 `DelegatedExecutionTrackingRecord`
- `reconcile_inbound_message()` 是 gateway handler 的便捷入口

**调用验证**：`galaxy_gateway/android/handlers/task_lifecycle.py` 顶层已经 import 并在 handler 函数内调用了 `reconcile_inbound_message()`——top-level import，有 ImportError graceful fallback，import 成功后每个 task result/end/progress handler 都会调用它。`galaxy_gateway/android/handlers/goal_execution.py` 同样 import 了此函数。

**已证实**：`handle_task_result()` → `reconcile_inbound_message()` → `reconcile_android_execution_signal()` → tracker 更新。这条回流链路在代码层面是**已闭合**的。

### 3.4 continuity / reconnect / recovery

**有 contract 定义，但运行时闭合程度为"半闭合"：**

- `core/android_v2_continuity_contract.py` 定义了 7 类场景的 policy sentinels（attach / reconnect / re-attach / V2-restart / stale-identity / duplicate / partial-result）
- `core/attached_runtime_session_registry.py` 存储 session 记录
- `core/attached_runtime_reuse_binding.py` + `core/attached_runtime_reuse_dispatch.py` 处理会话复用
- **V2 restart 后 in-flight task 恢复**：policy 有定义，但依赖 task 持久化后端（是否真正写 disk/DB 需要验证 `core/task_lifecycle_persistence.py`）

### 3.5 跨设备闭环评估

| 链路节点 | 代码存在 | 主链接入 | 实际生效闭环 |
|---------|---------|---------|------------|
| Android 注册/心跳 | ✅ | ✅ | ✅ 已闭合 |
| V2→Android 命令下发 | ✅ | ✅ | 🟡 需 gateway 启动 |
| Android 结果回流（基础） | ✅ | ✅ | ✅ 已闭合（handler 调用 reconciler 已验证）|
| ACK/PROGRESS 跟踪 | ✅ | ✅ | ✅ task_lifecycle.py 全覆盖调用 |
| continuity/reconnect | ✅ | 🟡 | 🟡 policy 存在，运行时闭合有条件 |
| V2 重启后 task 恢复 | 🟡 | 🟡 | ❌ 依赖持久化后端未确认 |
| 编排续链（结果触发下一步） | 🟡 | ❌ | ❌ 结果回流到 tracker，但不自动续链编排 |

**跨设备主链最关键硬缺口**：

结果回流到 `DelegatedExecutionTrackingRecord` 后，V2 编排层**不会自动续链**——"状态回写"发生了，但"编排续链"（例如根据 Android 完成信号触发下一个计划步骤）没有看到对应的事件驱动连接。这意味着系统目前达到的是"状态回写"而非"事件驱动闭环编排"。

---

## 四、模型供给主链核查

### 4.1 默认模型配置

`config.json` 第 6 行：`"default_llm_model": "gpt-4o"`

这是 UI 层/兼容层的后备值。实际运行时，`MultiLLMRouter._discover_providers()` 读取的是环境变量或 Dashboard 配置（优先级：Dashboard config > CredentialVault > ENV var）。

### 4.2 LLM 路由层级关系（真实调用链）

```
OpenClawd._get_router()
  └─ core/unified/llm_router.py::get_unified_llm_router()  → UnifiedLLMRouter（进程级单例）
       └─ UnifiedLLMRouter._backend = MultiLLMRouter()
            └─ 实际 HTTP 调用由各 ProviderAdapter 执行（OpenAIAdapter / AnthropicAdapter / ...）

core/llm_manager.py::LLMManager  ← Legacy 层，委派到 UnifiedLLMRouter
```

**关系明确**：
- `UnifiedLLMRouter`（`core/unified/llm_router.py`）= 策略门面，加载 `config/llm_routing_policy.yaml`，提供强类型接口，做遥测
- `MultiLLMRouter`（`core/multi_llm_router.py`）= 实际路由逻辑，发现 providers，执行 failover
- `LLMManager`（`core/llm_manager.py`）= Legacy 委派层，内部 call `get_unified_llm_router()`
- 三者**不是并行权威**，是明确的层叠委派关系

### 4.3 各 backend 的真实接入状态

| Provider | 接入类型 | 默认启用 | 备注 |
|---------|---------|---------|------|
| OpenAI | API（云端）| 有 key 即启用 | `OPENAI_API_KEY` 环境变量 |
| Anthropic | API（云端）| 有 key 即启用 | `ANTHROPIC_API_KEY` |
| Google Gemini | API（云端）| 有 key 即启用 | via OpenAI-compatible endpoint |
| DeepSeek | API（云端）| 有 key 即启用 | `DEEPSEEK_API_KEY` |
| xAI Grok | API（云端）| 有 key 即启用 | `XAI_API_KEY` |
| Ollama | 本地 | 有 `OLLAMA_URL` 即启用 | 仅注册 `llama3/mistral/codellama`；`supports_tools=False` |
| OneAPI | API 代理 | 有 key + URL 即启用 | OpenAI-compatible proxy |
| Android VLM | ❌ | ❌ | 无发现路径 |
| 本地多模态模型 | ❌ | ❌ | 无发现路径 |

**Ollama 真实状态**：
- 代码中 `_discover_providers()` 里 Ollama 是最后一个 provider，只注册了 3 个模型（llama3/mistral/codellama）
- `TaskType.GENERAL` 路由优先级为 `["openai", "anthropic", "deepseek", "google"]`，Ollama **不在这个列表里**
- `PROVIDER_MODEL_MAP` 中 Ollama 只有 `TaskType.GENERAL: "llama3"` 一个条目
- **结论**：Ollama 是注册的 provider，**但只有在所有其他 provider 都不可用且任务类型为 GENERAL 时才会被选中**——实际运行时几乎不会成为主 backend

### 4.4 是否存在统一策略层被绕过的问题

`UnifiedLLMRouter` 加载 `config/llm_routing_policy.yaml`，若文件不存在则"返回空策略，routing policy disabled"（`_load_routing_policy()` 第 48-50 行），路由退回到 `MultiLLMRouter` 的内置 `TASK_ROUTING_PREFERENCES`。这是一个合理的降级设计，不构成"绕过"。

更需要关注的是：如果代码中有模块**直接 import `MultiLLMRouter` 而不经过 `UnifiedLLMRouter`**，那统一策略层会被绕过。从 `LLMManager._backend` 的暴露方式来看，这是潜在路径。

### 4.5 模型供给系统定性

**结论：架构混合，运行时偏 API-first。**

- 架构上：Ollama（本地）路径存在，OneAPI（代理）路径存在，12 个云端 provider 路径存在
- 运行时：哪个 provider 被选中完全取决于哪个 API key 被配置——没有 key 的 provider 不会被发现。在未配置任何 key 的情况下，`MultiLLMRouter` 的 `providers` 字典为空，系统将无法调用任何 LLM
- 本地模型（Ollama）虽然有路径，但路由优先级最低，且不支持 tool calling（`supports_tools=False`）——这意味着依赖 function calling 的 agent 路径无法使用本地模型
- Android VLM 没有接入路径

---

## 五、已证实 / 半闭合 / 未成立 三类判断

### ✅ 已证实（代码明确，主链存在）

1. **V2 是唯一编排权威**——`android_v2_continuity_contract.py` policy 常量 + UDM 架构设计
2. **主启动链**：`main.py` → `SystemOrchestrator` → `unified_launcher.py` → `GalaxyUnified` → FastAPI
3. **OpenClawd 是主请求-响应核心**——四阶段处理流（ingest/continuum/branch/manifest）
4. **LLM 路由委派链**：`OpenClawd` → `UnifiedLLMRouter` → `MultiLLMRouter` → ProviderAdapter（无竞争权威）
5. **Android 注册/心跳协议**——AIP v3 WebSocket，有 canonical handler，有 UDM 写入
6. **跨设备命令下发基础路径**——`AndroidBridge.send_task()` → WebSocket AIP v3 command frame
7. **结果回流的 canonical reconciler 已接入**——`task_lifecycle.py` 中每个 task result/end handler 都调用 `reconcile_inbound_message()`，tracker 更新链路已闭合

### 🟡 半闭合（结构存在，但运行时闭合有条件）

1. **handler 实际调用 reconciler 的连接**——已验证：`task_lifecycle.py` 中 `handle_task_result()` 等已调用 `reconcile_inbound_message()`，调用链闭合。待验证的是 reconciler 找不到 tracking record 时（`was_updated=False`）的行为是否被上层感知并处理。
2. **continuity/reconnect 运行时闭合**——policy 和 session registry 存在，但 V2 重启后 in-flight task 恢复依赖持久化后端（`task_lifecycle_persistence.py` 是否真正有效写盘尚未验证）
3. **L4 循环的增强能力**——依赖 `enhancements/` 下的可选模块，运行时实际能力取决于安装；`_PERCEPTION_AVAILABLE`、`_GOAL_DECOMPOSER_AVAILABLE` 等均默认 `False`
4. **NATS 多节点调度**——no-op 模式下为单机运行，跨节点能力需要 `GALAXY_NATS_URL` 配置

### ❌ 未成立（无对应实现路径或关键链路断开）

1. **事件驱动编排续链**——Android 执行完成后，V2 编排层不会自动接续下一个编排步骤（结果回流到 tracker，但无下游触发器）
2. **Android VLM 模型路径**——`MultiLLMRouter` 无任何 Android 设备 VLM 接入逻辑
3. **本地多模态模型为默认选项**——Ollama 路由优先级最低，且不支持 tool calling，实际运行中几乎不会成为活跃 backend
4. **L4 循环作为主运行路径**——L4 是可选增强层，不是 canonical main runtime

---

## 六、关键问题按优先级排序

### P0：最高优先级——直接影响系统可运行性

**P0-1：跨设备编排续链缺口**  
代码文件：`core/android_execution_signal_reconciler.py` + `core/delegated_runtime_execution_tracker.py`  
问题：`reconcile_android_execution_signal()` 成功更新 tracker，但没有下游事件触发编排续链。系统只能做"状态记录"，无法做"完成驱动编排"。

**P0-2（降级为 P1）：reconciler 找不到 tracking record 时的静默降级**  
代码文件：`galaxy_gateway/android/handlers/task_lifecycle.py` + `core/android_execution_signal_reconciler.py`  
**已验证**：handler 确实调用了 `reconcile_inbound_message()`。但 reconciler 在找不到 matching tracking record 时返回 `was_updated=False, reject_reason=...`，上层 handler 对此结果是否有任何告警/重试/升级处理？若无，则正常运行时的 miss（V2 重启后 task record 丢失场景）会静默失败。

### P1：高优先级——影响系统完整性

**P1-1：无 API key 时系统无法完成任何 LLM 调用**  
代码文件：`core/multi_llm_router.py::_discover_providers()`  
问题：`providers` 字典动态发现，无 key 无 provider，系统不会报错但所有 LLM 调用会静默失败。无本地模型 fallback（Ollama 需要 OLLAMA_URL）。

**P1-2：V2 重启后 in-flight task 恢复依赖持久化未验证**  
代码文件：`core/task_lifecycle_persistence.py`  
问题：`android_v2_continuity_contract.py` 的 policy 要求 V2 能接受 Android 上传的 recovered task 结果，但这依赖 task record 从 disk/DB 恢复，此后端实现的有效性未验证。

**P1-3：L4 模块在未安装 enhancements 依赖时降级为空运行**  
代码文件：`core/galaxy_main_loop_l4_enhanced.py`  
问题：`_PERCEPTION_AVAILABLE=False`、`_GOAL_DECOMPOSER_AVAILABLE=False` 等均为 `False` 时，`run_cycle()` 中 `goal = await self._perceive_goal()` 仅读队列，若无外部提交目标，L4 主循环空转，不产生实际增强效果。

### P2：中优先级——影响系统成熟度

**P2-1：`SystemOrchestrator` 预飞检查不阻断**  
代码文件：`main.py::_run_orchestrator_preflight()`  
问题：所有 phase 异常均被 catch 并继续，系统即使在严重配置错误下也会以 "DEGRADED" 状态继续启动，运营层难以区分"启动成功"和"降级启动"。

**P2-2：Ollama 本地模型路由优先级过低 + 不支持 tool calling**  
代码文件：`core/multi_llm_router.py::TASK_ROUTING_PREFERENCES` + `PROVIDER_MODEL_MAP`  
问题：本地模型实际上无法参与主要执行路径（function calling 依赖），"混合本地+云端"模型供给在实践中退化为纯云端。

---

## 七、系统成熟度评估

| 维度 | 评级 | 说明 |
|------|------|------|
| 架构成熟度 | ★★★★☆ | 层次清晰，职责边界明确，有 canonical path，降级设计合理 |
| 运行主链成熟度 | ★★★☆☆ | API → OpenClawd → execution 主链可运行；但缺少跨 phase 的强一致保证 |
| 跨设备整合成熟度 | ★★★☆☆ | 下发路径可用；回流 reconciler 已验证接入；续链编排未实现是主缺口 |
| 模型供给成熟度 | ★★★☆☆ | 多 provider 架构完整；运行时依赖 API key 配置；本地模型路径存在但实际优先级极低 |
| **整体阶段** | **主链可运行，跨设备半闭合** | 单机 API-driven 路径成熟；跨设备事件驱动闭环未达成 |

---

## 八、一句总评

**Galaxy-Nexus 是一个架构设计清晰、层次划分明确的请求驱动编排系统：单机主链（API → OpenClawd → LLM → 执行）完整可运行；跨设备回流链路已验证闭合（Android 结果通过 reconciler 正确更新 tracker），但有一个关键的最后一公里缺口——tracker 更新后没有下游事件触发 V2 编排续链，系统停在"状态回写"层面而未达到"完成驱动编排续链"；模型供给架构混合但运行时偏 API-first，本地模型路径存在却因路由优先级和 tool calling 不支持而实际上不参与主干执行。**

---

*审查者注：以上结论均以实际代码（函数签名、配置读取路径、路由逻辑、handler 结构）为一次判断依据，不以现有 docs/*.md 文档为主要证据。handler → reconciler 连接已通过 `grep -r "reconcile_inbound_message" galaxy_gateway/` 直接验证。标记为"🟡半闭合"的项目（continuity/reconnect、V2重启恢复）仍需对 `task_lifecycle_persistence.py` 的实际持久化后端做进一步验证。*
