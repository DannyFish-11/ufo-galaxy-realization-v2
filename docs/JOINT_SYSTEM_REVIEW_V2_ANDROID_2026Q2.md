# 双仓联合系统深度审查报告
## ufo-galaxy-realization-v2 × ufo-galaxy-android — 2026 Q2

> **审查方法**：直接基于两仓主分支当前真实代码、测试文件、CI workflow 作出判断。
> 不依赖 docs 目录中的既有审查文档。中文为主，结论强约束、直接。

---

## 一、双仓系统本质判断

**这两个仓库共同构成什么？**

基于代码事实：

- **V2（ufo-galaxy-realization-v2）是控制平面 / 编排权威**
  - `main.py:SYSTEM_ORCHESTRATOR` 是官方启动入口，7阶段带阶段前置检查
  - `galaxy_gateway/app.py` → FastAPI 应用，暴露 REST + WebSocket 端点
  - `DeviceRouter`（`galaxy_gateway/device_router.py`）是任务路由权威
  - `core/task_graph.py` + `core/task_graph_runtime.py` 是任务编排核心
  - V2 **不**是简单的代理，有独立的 LLM routing、session truth、capability gate

- **Android（ufo-galaxy-android）是持久执行参与者 / 本地能力承载端**
  - `GalaxyConnectionService.kt`（145KB）是设备侧主服务，常驻后台
  - `GalaxyWebSocketClient.kt`（67KB）是出站连接到 V2 的 WebSocket 客户端
  - Android 侧有 `DelegatedRuntimeAcceptanceEvaluator.kt` — 任务接受评估，但不是编排权威
  - Android 侧的 `LoopController.kt`（46KB）负责步骤级执行循环
  - Android **没有**独立的任务调度决策权，接受 V2 下发的 task_assign

**结论**：是一个中心式（V2 为控制平面）+ 端侧执行（Android 为执行参与者）的系统，不是对等 mesh。

---

## 二、双仓真实主链路径（canonical main path）

### 完整主链（runtime-live，代码可追踪）

```
[V2 启动]
main.py:_run_orchestrator_preflight()      # 7阶段前置检查
  → unified_launcher.py                    # 下级 launcher
      → galaxy_gateway/app.py              # FastAPI 应用挂载
          → galaxy_gateway/routes/websocket.py
              → /ws/device/{device_id}     # 唯一 canonical 接入点 (AIP v3)
                  → _handle_android_ws()
                      → normalise_to_v3_dict()        # galaxy_gateway/protocol/compat.py
                      → android_bridge.handle_message()

[V2 处理 Android 注册]
android_bridge → handlers/registration.py:handle_device_register()
  → UDM 设备注册 + Body Mesh 角色推导

[V2 接收请求并调度]
DeviceRouter.route_task()                  # galaxy_gateway/device_router.py
  → routing/policy.py:analyze_command()
  → routing/device_selection.py:select_devices()
      Step 0: target_device_validator 可接受性预过滤
      Step 1: exec_mode（GatewayCapabilityRegistry）
      Step 2: capability_routing_gate.filter_by_required_capabilities()  [硬门控，PR-3]
      Step 3: autonomous_filter
      Step 4: DevicePoolManager.select_device()
  → routing/dispatch.py:dispatch_to_websocket()
      → build_aip_message(device_id, task_id, trace_id, command)  [AIP v3.0]
      → WebSocket send

[Android 接收并执行]
GalaxyWebSocketClient.onMessage()          # OkHttp WebSocket 回调
  → GalaxyConnectionService.handleTaskAssign()
      → DelegatedRuntimeAcceptanceEvaluator.evaluate()   # 任务接受决策
      → executeLocalTaskAssign()
          → AccessibilityScreenshotProvider.captureJpeg()
          → (若本地AI可用) MobileVlmPlanner.plan()        # HTTP → 127.0.0.1:8080
          → (若本地AI可用) SeeClickGroundingEngine.ground() # HTTP → 127.0.0.1:8081
          → AccessibilityActionExecutor.execute()         # Accessibility API
      → sendTaskResult()   # 回传 V2 (type=task_result)

[V2 接收结果]
handlers/task_lifecycle.py:handle_task_result()
  → _signal_guard_accept()   # 512-slot in-memory 去重
  → store_task_result()      # openclawd_memory_backflow
  → reconcile_inbound_message()  # android_execution_signal_reconciler
  → task Future resolved     # task_envelope_lifecycle_registry
```

### 路径分类

| 路径/模块 | 分类 |
|---|---|
| `/ws/device/{device_id}` | **runtime-live 主链** |
| `android_bridge` → handler 链 | **runtime-live 主链** |
| `device_selection` → `dispatch` | **runtime-live 主链** |
| `task_envelope_lifecycle_registry` | **runtime-live 主链**（futures 不跨重启） |
| `task_graph_runtime.py` | **quasi-mainline**（图执行，非单步dispatch） |
| `multi_device_truth_convergence.py` | **quasi-mainline** |
| `/ws/android/{device_id}` | **compat**（委托到 canonical 处理链） |
| `/ws/ufo3/{device_id}` | **legacy-disabled**（默认不激活） |
| `/ws/webrtc/{device_id}` | **media-only，非设备主链** |
| `gateway_nats_adapter.py` | **additive，非默认启用** |
| `WebRTC` (V2 + Android) | **structural-only**（代码存在，非主链） |
| Tailscale（Android） | **additive，非默认** |
| Mesh federation | **structural-only** |

---

## 三、六层结构分析

### Layer 1：交互层

**V2 侧（成熟度：高）**
- WebSocket canonical ingress `/ws/device/{device_id}` + compat 路径完整
- REST API（chat、devices、tasks、sessions、health、llm）完整挂载
- AIP v3 协议规范化层（`galaxy_gateway/protocol/compat.py:normalise_to_v3_dict()`）
- compat 路径（`/ws/android/*`）均委托到 canonical 处理链，不是独立实现
- 判断：**V2 交互层真实主链已成立，compat 路径受控**

**Android 侧（成熟度：中）**
- `GalaxyWebSocketClient.kt`（OkHttp）：主动出站连接 V2，带重连逻辑
- `GalaxyConnectionService.kt`：常驻后台服务，处理连接生命周期
- `FloatingWindowService.kt`：悬浮窗 UI（非主链，可选）
- `VoiceRecognitionService.kt`：语音识别（additive）
- 判断：**Android 交互层基本成立，WebSocket 出站主链可运行**

**双方对称性**：V2 侧功能丰富度远高于 Android 侧（REST + WS vs 纯 WS 出站）。合理，因为 V2 是控制平面。

---

### Layer 2：上下文感知层

**V2 侧（成熟度：中，仅 Windows）**
- `OpenClawd.process()` 中：`PerceptionFrame`（Windows 连续感知）+ `MultimodalBus.ingest()`（请求绑定多模态融合）
- `ContinuumOrchestrator`：意图 → state_continuum（tri_state_phase + runtime_domain）
- 问题：这一层完全是 Windows 桌面感知（音频、视频、系统信号），不向 Android 侧传递
- 判断：**V2 上下文感知层在 Windows 侧结构完整，但双仓共享不成立**

**Android 侧（成熟度：低）**
- `AccessibilityScreenshotProvider.kt`：截图（基础感知）
- 无等价的 context frame、continuum 或 multimodal bus 层
- Android 的"感知"结果（截图）通过 task execution 流程隐式传递，不是独立的 context 层
- 判断：**Android 上下文感知层基本不存在，仅靠截图作为输入**

**双方对称性**：严重不对称。V2 有完整的 Windows-native context 架构，Android 侧无等价物。这是设计选择（V2 感知 + Android 执行），但意味着 Android 的任务规划质量依赖 V2 下发的 goal，而非 Android 自主感知。

---

### Layer 3：记忆层

**V2 侧（成熟度：中，部分持久）**

| 组件 | 持久性 | 状态 |
|---|---|---|
| `session_manager.py` | ✅ JSON 文件（`data/sessions.json`） | 跨重启持久 |
| `durable_result_idempotency.py` | ✅ 文件级（原子 write-then-rename） | 跨重启持久 |
| `canonical_session_truth.py` | ⚠️ ring-buffer（in-memory）+ 可选 `DurableAuditStore` | 默认仅内存 |
| `task_envelope_lifecycle_registry.py` | ❌ in-memory futures | 重启后丢失 |
| `openclawd_memory_backflow.py` | ⚠️ 写入 OpenClawd，持久性取决于其存储实现 | 条件持久 |

**核心缺口**：`task_envelope_lifecycle_registry` 中 in-flight task futures 重启后丢失。这意味着 V2 重启后，正在进行中的任务无法自动恢复。`canonical_session_truth` 的 ring-buffer 默认不持久，虽有 `DurableAuditStore` 接口，但是否默认挂载取决于部署配置，代码中没有强制激活。

**Android 侧（成熟度：低）**
- `AndroidSessionContribution.kt`（10KB）：session 贡献记录，但持久性不明
- `OfflineTaskQueue.kt`（10KB）：离线任务队列（network 目录），结构存在
- `DurableSessionContinuityRecord.kt`（10KB）：可能有 durable session 跟踪
- 无类似 V2 `session_manager.py` 的独立持久 session 存储
- 判断：**Android 记忆层基本依赖 V2，自身仅有结构性组件，持久性不明**

**双方对称性**：V2 有明确的 JSON 持久化路径，Android 侧没有等价的独立持久记忆层。这是设计意图（Android 是执行端不是记忆权威），但意味着 Android 断连后 V2 丢失 in-flight context。

---

### Layer 4：任务编排层

**V2 侧（成熟度：高，有明确主链）**
- `core/task_graph.py` + `core/task_graph_runtime.py`：任务图定义和运行时
- `core/task_envelope_lifecycle_registry.py`：统一 task lifecycle 注册（替换旧的 ad-hoc dicts）
- `galaxy_gateway/device_router.py:DeviceRouter`：路由权威，四步选择 + dispatch
- `routing/policy.py`：命令分析和路由策略
- `routing/device_selection.py`：设备选择（含 PR-3 capability 硬门控）
- `routing/dispatch.py`：构建 AIP v3 消息并发送
- 判断：**V2 任务编排层是真实系统中枢，主链清晰且有测试覆盖**

**Android 侧（成熟度：中）**
- `DelegatedRuntimeAcceptanceEvaluator.kt`（33KB）：接受决策（多维度评估）
- `LoopController.kt`（46KB）：步骤级执行循环，驱动 plan → ground → execute 循环
- Android 的"编排"是执行侧的编排（步骤顺序、重试、错误恢复），不是跨设备的任务分配
- 判断：**Android 任务编排层作为执行侧编排已成立，但不是全局编排权威**

---

### Layer 5：系统执行层

**V2 侧（成熟度：中，执行依赖 Android 或 Windows）**
- 本地执行（Windows）：`DecisionExecutor`（`core/` 下）+ `WindowsExecutionArbiter` → 依赖 Windows 环境
- 跨设备执行：`dispatch.py` → Android 执行 → `task_result` 回流
- V2 自身不"执行"GUI 操作，它是编排者；Windows 本地执行仅在 Windows 部署时有效
- 判断：**V2 执行层高度依赖下游（Android 执行或 Windows 本地）**

**Android 侧（成熟度：中，本地 AI 默认不可用）**
- `AccessibilityActionExecutor.kt`：真实 Accessibility API 操作（tap/scroll/type）→ **已成立**
- `AccessibilityScreenshotProvider.kt`：截图捕获 → **已成立**
- `MobileVlmPlanner.kt` → HTTP `127.0.0.1:8080`（外部 llama.cpp/MLC-LLM 服务器）：
  - **不是 APK 内置推理**，是 HTTP 客户端
  - `loadModel()` 实际调用 `warmupWithResult()` → ping `/health` endpoint
  - 服务器不存在时立即返回 `WarmupResult.failure`
  - `NoOpPlannerService` 是安全默认实现（返回 error，不推理）
  - **结论：本地 AI 默认不可用，需要独立部署外部推理服务器 + 下载模型权重**
- `SeeClickGroundingEngine.kt` → HTTP `127.0.0.1:8081`：同样依赖外部服务器
- `ModelAssetManager.kt`：需要验证本地模型文件（`verifyAll()`），文件不存在则 start() 返回 Failure
- `LocalInferenceRuntimeManager.kt`：完整的生命周期管理（Stopped/Starting/Running/Degraded/Failed/SafeMode），架构设计良好，但默认 Stopped
- 判断：**Android 基础执行链（截图 + Accessibility）已成立；本地 AI 路径代码完整但默认不可用**

---

### Layer 6：外部能力层

**V2 侧**
- `core/multi_llm_router.py`（`core/llm/router.py` 封装）：云 LLM 路由，支持多 provider → **主链可运行**
- `core/rag_memory.py`：RAG 记忆查询 → **additive**
- `core/api_market.py`：API 市场 → **additive**
- MCP bridge（`mcp_bridge/`）：工具扩展 → **additive**

**Android 侧**
- MobileVLM V2-1.7B（通过 `MobileVlmPlanner`）：**代码完整，默认不可用**
- SeeClick grounding（通过 `SeeClickGroundingEngine`）：**代码完整，默认不可用**
- `TailscaleAdapter.kt`（5.9KB）：Tailscale VPN 适配 → **additive**
- `webrtc/` 目录：WebRTC 支持 → **structural-only**

---

## 四、AHE 四层平台治理分析

### AHE Layer 1：接入适配层

**评价：双仓最成熟的层，已达到准生产级别**

代码证据：
- V2 `normalise_to_v3_dict()`（`galaxy_gateway/protocol/compat.py`）：统一 AIP v1/v2/v3 归一化
- `/ws/device/{device_id}` canonical ingress 明确标注，compat 路径明确标注并委托
- Android `GalaxyWebSocketClient.kt` 实现了 AIP v3 握手（`sendHandshake()` → `device_register`）
- `ingress_classifier.py`（V2）：入站消息类型分类
- 多协议路径（`/ws/android/`、`/ws/`、`/ws/ufo3/`）有明确分类和状态（compat/deprecated/disabled）

**与 AHE 标准对比**：接近 AHE 的多协议适配层，但目前仅有 WebSocket/HTTP，无 MQTT/CoAP/gRPC 适配（系统设计选择，可接受）。

### AHE Layer 2：编排管理层

**评价：V2 侧已形成真实 orchestrator，但 lifecycle 持久性不完整**

代码证据：
- `DeviceRouter`：设备路由权威（四步过滤）→ 真实运行时组件
- `TaskEnvelopeLifecycleRegistry`：统一 task 生命周期注册，替换旧 ad-hoc dicts
- `task_graph_runtime.py`：任务图执行
- 缺口：task futures 不跨重启，图执行和单步 dispatch 的协调边界不完全清晰

**与 AHE 标准对比**：接近 AHE 的任务调度和依赖管理，但缺少可视化编排界面和版本控制语义。

### AHE Layer 3：协同决策层

**评价：局部雏形，主要是 capability selection，多智能体协同尚不成立**

代码证据：
- `capability_routing_gate.py`（V2）：capability 硬门控 → 已在 device_selection 中连接
- `DevicePoolManager`：设备池选择 → 基础成立
- Android `DelegatedRuntimeAcceptanceEvaluator.kt`（33KB）：多维度接受决策 → 代码完整
- `DelegatedRuntimeStrategyEvaluator.kt`（32KB）、`DelegatedRuntimeGovernanceEvaluator.kt` → 大量代码，但是否 runtime-enforced 需要进一步验证

**与 AHE 标准对比**：当前系统的"协同决策"主要是 capability-based routing 和任务接受决策，不是多智能体冲突消解或强化学习调度。距离 AHE 协同决策层理想还很远。

### AHE Layer 4：观测治理层

**评价：基础 CI 已建立，但以 advisory 为主，无 emulator 级别验证**

代码证据：
- V2 `.github/workflows/dual_repo_integration.yml`：5 个 job（transport harness、protocol regression、Android CI baseline、composite gate、contract drift guard）→ **协议层双仓验证已接入 CI**
- V2 `.github/workflows/ci.yml`：常规 Python 测试
- V2 `.github/workflows/guardrails.yml`：架构守卫
- Android `.github/workflows/android-ci.yml`：`./gradlew :app:test` + `assembleDebug` + `lintDebug` → **无 emulator 测试**
- `core/architecture_diagnostics.py`、`core/architecture_invariants.py`、`core/architecture_live_status.py`：架构状态诊断（这些本身是否 CI 强制？需检查）

**缺口**：
- 无 emulator smoke test（Android 侧，即使 `android-ci.yml` 已存在）
- 无真机/模拟器级别的 task_assign → execute → result 完整回路测试
- 部分治理模块的检查是 advisory（会报告但不 fail CI）

---

## 五、已真实成立的部分（代码证据导向）

以下是确实已经闭合、不只是"概念结构"的部分：

### ✅ 传输闭环
- V2 WebSocket（`/ws/device/{device_id}`）→ Android 注册 → V2 确认：代码路径完整可追踪
- AIP v3 协议规范化（`normalise_to_v3_dict()`）：已在 canonical handler 调用
- `dual_repo_integration.yml:transport-harness` job 通过真实 FastAPI TestClient 验证该路径

### ✅ 协议回归测试
- `tests/integration/test_v2_android_protocol_regression.py`：reconnect、offline queue、duplicate result、handoff signal、session identity continuity 均有回归用例
- `tests/integration/test_android_ci_baseline.py`：inbound types 稳定性、handler coverage 审计
- `.github/workflows/dual_repo_integration.yml`：这些测试已接入 CI

### ✅ 能力门控（capability gate）
- `core/capability_routing_gate.py`：硬门控，不是 advisory
- `routing/device_selection.py:select_devices()` Step 2 已连接该 gate
- 若 `required_capabilities` 不满足，设备被排除出选择池（不是软警告）

### ✅ 结果去重（跨重启）
- `core/durable_result_idempotency.py`：文件级 JSON，原子 write-then-rename
- 512-slot 上限防止无限增长
- 已是真实持久化，不依赖进程内存

### ✅ Android 基础执行链
- `AccessibilityActionExecutor.kt` + `AccessibilityScreenshotProvider.kt`：已实现
- `GalaxyConnectionService.handleTaskAssign()` → 本地执行路径已完整
- `sendTaskResult()` 回传 V2：路径完整

### ✅ Android 最小 CI 基线
- `android-ci.yml`：build + unit test + lint 已接入，不再是零 CI

### ✅ V2 session 持久化（基础）
- `session_manager.py` JSON 持久化已有效
- `durable_result_idempotency.py` 已有效

---

## 六、当前关键缺口（阻止系统进一步成熟）

### 🔴 P0：V2 in-flight task lifecycle 不跨重启
**代码证据**：`core/task_envelope_lifecycle_registry.py` 使用 `asyncio.Future`，注释明确指出这是 in-memory 替换了旧 ad-hoc dicts。V2 重启后，所有 pending futures 丢失，没有持久化路径。

**影响**：V2 重启后，Android 正在执行的任务的结果无法被 V2 关联回原始请求。

### 🔴 P0：Android 本地 AI 默认不可用
**代码证据**：
- `MobileVlmPlanner.kt:loadModel()` → `warmupWithResult()` → ping `http://127.0.0.1:8080/health`
- 如果该端点不可达，立即返回 `WarmupResult.failure(HEALTH_CHECK, ...)`
- `NoOpPlannerService` 是默认实现（`loadModel()` 返回 `false`，`plan()` 返回 error）
- `ModelAssetManager.kt:verifyAll()` 需要本地模型文件存在且校验通过
- 要让本地 AI 工作，需要：① 下载 MobileVLM V2-1.7B GGUF 权重 → ② 在设备上运行 llama.cpp/MLC-LLM 服务器 → ③ 服务器在 `127.0.0.1:8080` 上监听

这不是"代码有了但需要配置"，而是需要独立的运行时基础设施，远超正常 APK 安装范围。

**影响**：Android 侧"智能规划"能力实际上默认不存在，执行退化到直接接受 V2 下发的 action 列表（若有）或依赖其他路径。

### 🔴 P0：canonical session truth 跨重启不保证
**代码证据**：`core/canonical_session_truth.py` 使用 `deque`（ring buffer）作为 runtime 存储。`DurableAuditStore` 接口存在（`set_audit_store()` 方法），但：
- 没有默认激活的 durable store 实例
- `get_canonical_session_truth_runtime()` 直接返回纯 in-memory 的 runtime
- PR-B2 提到了 durable audit，但是可选附加，不是默认行为

**影响**：session truth（"这个 session 的权威执行结果是什么"）重启后丢失，影响 continuity 和 operator 观测。

### 🟡 P1：Android E2E 协议验证不存在
**代码证据**：Android `.github/workflows/android-ci.yml` 仅运行：
```yaml
./gradlew :app:test          # JVM unit tests only
assembleDebug                # APK build
lintDebug                    # lint
```
没有 emulator 启动，没有真实 WebSocket 连接 V2 mock 的测试，没有 task_assign → execute → result 的完整回路测试。

**影响**：Android 协议正确性只能靠 V2 侧的 `test_android_ci_baseline.py`（从 V2 角度守护 inbound types），Android 自身的执行链无自动验证。

### 🟡 P1：V2 restart 后 recovery 不完整
**代码证据**：`core/runtime_restart_recovery.py` 明确记录"Non-goals"：
- **In-flight task queues** 是 intentionally ephemeral（重启后需要 task source 重放）
- **Device heartbeat state** 设备重连后重新注册（可接受）
- WebRTC transport bindings 重启后丢失（可接受）
但 in-flight task 的"需要 task source 重放"在实际系统中意味着什么？没有看到 V2 侧有 task replay/resubmit 机制。

### 🟡 P1：capability gate 默认强制但降级行为需关注
**代码证据**：`core/capability_routing_gate.py` 有 `INSUFFICIENT_DATA` verdict，当 capability 信息无法确定时。在 `device_selection.py` 中，`INSUFFICIENT_DATA` 时的处理行为需要验证是否真正 blocking。

### 🟡 P1：WebRTC / mesh / federation 仅结构存在
**代码证据**：
- V2 `galaxy_gateway/webrtc_proxy.py`：WebRTC 信令代理
- Android `webrtc/` 目录：WebRTC 支持代码
- V2 `core/mesh/`：mesh session 相关
- 这些路径均不在 `dual_repo_integration.yml` 的测试范围内，没有被 CI 覆盖
- 对应的"mesh" session 恢复虽在 `runtime_restart_recovery.py` 中提到，但 WebRTC 本身是 transport-layer，与 mesh session 逻辑分离

---

## 七、V2 与 Android 双侧成熟度对比

| 维度 | V2 成熟度 | Android 成熟度 | 对称性 |
|---|---|---|---|
| 传输接入层 | 🟢 主链成立 | 🟢 主链成立 | 对称 |
| 协议规范化 | 🟢 AIP v3 归一化已成立 | 🟢 AIP v3 对齐 | 对称 |
| 任务编排 | 🟢 DeviceRouter + TaskGraph | 🟡 执行侧 LoopController | 不对称（设计意图） |
| Session 持久化 | 🟡 JSON持久 + 部分 in-memory | 🔴 基本无独立持久层 | 不对称 |
| 结果去重 | 🟢 文件级 durable | 🟡 512-slot in-memory guard | 不对称 |
| 本地 AI 推理 | 🔴 V2 无本地推理 | 🔴 代码完整但默认不可用 | 双方均不可用 |
| CI 覆盖 | 🟢 多层 CI（协议/传输/架构） | 🟡 build/test/lint，无 emulator | 不对称 |
| Restart 恢复 | 🟡 mesh恢复，in-flight task丢失 | 🟡 WS重连，state recovery部分 | 相似缺口 |
| Context 感知 | 🟡 Windows-only continuum | 🔴 仅截图 | 不对称 |
| 观测/治理 | 🟡 CI守护 + advisory模块 | 🟡 基础CI | 弱对称 |

---

## 八、系统阶段最终判断

**判断：主链可运行期（进入系统整合期早期）**

**支撑理由（基于代码证据，不是文档）**：

**已达到的：**
1. V2 ↔ Android 传输闭环真实可运行（代码路径完整 + CI 验证）
2. 协议层有自动化回归测试（reconnect/duplicate/handoff）
3. DeviceRouter + capability gate 是真实运行时路径（非仅结构）
4. Android 基础执行链已成立（截图 + Accessibility）
5. 结果去重已 file-backed（跨重启）
6. session 基本持久化已有效

**尚未达到的（阻止"系统整合期完成"的标准）：**
1. in-flight task lifecycle 不跨重启（控制平面可靠性核心缺口）
2. Android 本地 AI 默认不可用（执行能力的天花板限制）
3. Android E2E 自动化测试不存在（Android 执行链无自验能力）
4. canonical session truth 跨重启不持久（truth 权威性缺口）

**为什么不是"系统整合期"：**  
系统整合期需要双侧主链都有完整测试覆盖，关键 runtime truth 有持久保证，restart recovery 覆盖主要场景。当前 Android 侧 E2E 缺失、V2 in-flight task 不持久、本地 AI 默认不存在，这三点阻止了整合期的判断。

**为什么不是"骨架期"：**  
骨架期意味着只有接口/结构，没有真实执行闭合。当前系统传输闭环已成立，协议有回归验证，Android Accessibility 执行链已成立，这些已经超过骨架期。

---

## 九、对后续修复型 PR 的建议优先级

| 优先级 | 修复方向 | 代码落点 |
|---|---|---|
| P0 | V2 in-flight task lifecycle 持久化 | `core/task_envelope_lifecycle_registry.py` + 持久化后端 |
| P0 | canonical session truth 默认激活 durable audit | `core/canonical_session_truth.py:get_canonical_session_truth_runtime()` |
| P0 | 诚实标注 Android 本地 AI 为 non-default，明确激活路径 | `LocalInferenceRuntimeManager` + 文档 |
| P1 | Android E2E 协议测试（emulator 或 mock WS server） | `.github/workflows/android-ci.yml` |
| P1 | V2 restart 后 in-flight task replay/resubmit 机制 | `core/runtime_restart_recovery.py` + task retry |
| P2 | WebRTC/mesh 在 CI 中的最小可验证状态声明 | `dual_repo_integration.yml` |
| P2 | Android session/result 持久化边界明确化 | `AndroidSessionContribution.kt` |

---

## 十、本审查的方法说明与限制

**方法：**
- 直接阅读 V2 和 Android 仓主分支代码，路径追踪
- 以 CI workflow 和测试文件作为"已真实成立"的证据
- 以代码的实际执行路径（constructor、runtime、inject）判断是否 runtime-live

**限制：**
- Android 仓 `GalaxyConnectionService.kt`（145KB）和 `RuntimeController.kt`（152KB）、`StabilizationBaseline.kt`（108KB）等超大文件只阅读了接口和关键片段，未全文阅读
- Android 的 `DelegatedRuntime*` 系列文件（大量，每个 20-40KB）runtime 连接路径未逐一追踪
- 本审查**不**基于既有 docs 目录文档；如果代码与既有文档有矛盾，以本审查的代码判断为准

---

*审查时间：2026-04-26*  
*审查范围：V2 主分支（sha: 当前 HEAD），Android 主分支（sha: 58f56d6c）*
