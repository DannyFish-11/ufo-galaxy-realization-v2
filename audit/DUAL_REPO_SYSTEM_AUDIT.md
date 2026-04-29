# Galaxy 双仓系统完整真实代码审查报告

> **审查范围**: `ufo-galaxy-realization-v2`（中心仓）× `ufo-galaxy-android`（Android 仓）  
> **审查方法**: 基于真实代码路径溯源，非文档摘抄  
> **审查日期**: 2026-04-29  
> **审查状态**: 初版，覆盖所有主链路

---

## 0. 审查结论速查

| 维度 | 完成度 | 关键评语 |
|------|--------|---------|
| 中心 Runtime（启动/路由/服务） | **60%** | 启动链已闭环，但 UDM/UCM 等核心模块多数是 best-effort，非强制 |
| Android 本地执行链路 | **55%** | EdgeExecutor 已能执行任务，AutonomousExecutionPipeline 存在但与中心 AI 的完整联动待确认 |
| 中心 ↔ Android 连接层 | **75%** | WebSocket 双向收发协议完整，handshake/heartbeat/compat 路径清晰 |
| 任务调度（中心 → Android） | **65%** | task_assign/goal_execution 派送完整，返回路径有 truth chain；但 dispatch 决策本身靠 DeviceRouter，后者依赖 UDM 状态，UDM 是否稳定存疑 |
| 离线/重连/同步链路 | **70%** | OfflineTaskQueue 完整，session authority bounding 已实现，reconnect 分类（continuity_resume vs new_attachment）已实现 |
| Truth/Governance 链路 | **45%** | 4 步 canonical truth chain 代码存在，但 3/4 步是 best-effort（try/except 静默降级），is_truth_chain_complete 实际不强制 |
| Acceptance/Final Review | **20%** | 代码中看到 CanonicalCompletionIngress 但 final acceptance 层无真实 verdict mechanism |
| 端到端可用性 | **45%** | 核心链路能跑，但"稳定完整地跑通一个任务从发出到验收关闭"的完整闭环有多处软性 gap |

---

## 1. 系统整体架构画像

### 1.1 这套系统是什么

**Galaxy-Nexus** 是一个以 Python 中心仓为"大脑"、Android 设备为"手脚"的 L4 级分布式多设备智能体系统。

设计目标：用户用自然语言下令 → 中心仓理解意图 → 分解任务 → 调度到合适设备执行 → 收集执行结果 → 验收 → 记忆回流。

实际现状：连接层和消息层已完整，任务派送链路基本通，truth/acceptance 层仍以 best-effort 为主。

### 1.2 中心仓主要组件（`ufo-galaxy-realization-v2`）

| 组件类别 | 文件路径 | 真实职责 |
|---------|---------|---------|
| **系统入口 / 编排** | `main.py` → `core/system_orchestrator.py` → `unified_launcher.py` | 7 阶段启动序列（LOAD_CONFIG→RESOLVE_MODE→ENV_CHECKS→BACKGROUND→RUNTIME→DESKTOP→READINESS_SUMMARY），完成后委托 unified_launcher 做异步全服务启动 |
| **Gateway 服务** | `galaxy_gateway/app.py` + `galaxy_gateway/gateway_service.py` | FastAPI 应用，WebSocket 路由注册，HTTP API，依赖注入 |
| **WebSocket 入口 (规范)** | `galaxy_gateway/routes/websocket.py` `/ws/device/{device_id}` | CANONICAL 设备入口，AIP v3 协议，通过 android_bridge |
| **Android 桥接层** | `galaxy_gateway/android_bridge.py` | Transport/session adapter。负责协议翻译、连接句柄缓存、消息路由分发到各 handler。**不持有 dispatch 权威** |
| **注册 Handler** | `galaxy_gateway/android/handlers/registration.py` | device_register → 写 UDM(SSOT) → 更新本地缓存 → 创建 mesh session → attach_runtime_session → register body mesh roles |
| **任务生命周期 Handler** | `galaxy_gateway/android/handlers/task_lifecycle.py` | task_result（4 步 truth chain + durable idempotency guard + memory backflow） |
| **任务派送 Handler** | `galaxy_gateway/android/handlers/task_submit.py` | task_execute/task_submit（中心 → Android 派送） |
| **Goal 执行 Handler** | `galaxy_gateway/android/handlers/goal_execution.py` | goal_execution / parallel_subtask / goal_execution_result |
| **Core API** | `core/api_routes.py` → `core/routes/*.py` | REST 聚合路由（devices/tasks/system/ai/chat/nodes/command/health/federation 等 30+ 域）。`/ws/device/{device_id}` 在此为 **COMPAT** 路径 |
| **设备状态 SSOT** | `core/unified/device_manager.py` → `UnifiedDeviceManager` | 设备注册/心跳/断线状态的 canonical 写入权威 |
| **连接状态管理** | `core/unified/connection_manager.py` → `UnifiedConnectionManager` | 连接态（ONLINE/OFFLINE）管理 |
| **Runtime Session** | `core/attached_runtime_session.py` + `core/attached_runtime_session_registry.py` | 设备附着 runtime session 的 attach/reconnect/classify（continuity_resume vs new_attachment） |
| **Truth Chain** | `core/task_result_canonical_truth_chain.py` | 4 步 must-run truth chain：truth_ingress → reconcile → authority_state_update → canonical_completion_linkage |
| **真值入口** | `core/android_participant_truth_ingress.py` | 把 Android 结果信号映射为 V2 canonical 状态 |
| **执行信号协调** | `core/android_execution_signal_reconciler.py` | 对齐 host-side execution tracker |
| **任务规范模型** | `core/canonical_task.py` + `core/canonical_task_dispatch_chain.py` | CanonicalTask 生命周期、canonical task dispatch |
| **完成入口** | `core/canonical_completion_ingress.py` | 完成事件通知，解除 awaiter 阻塞 |
| **DeviceRouter** | `galaxy_gateway/device_router.py` | 任务派送路由决策，管理 task_events，解除 dispatch_to_websocket 等待 |
| **记忆回流** | `core/openclawd_memory_backflow.py` | 将 task_result 存回 OpenClawd 记忆系统 |
| **Durable 幂等** | `core/durable_result_idempotency.py` | 跨重启任务结果去重 |
| **Mesh Registry** | `core/mesh/body_mesh_registry.py` | 设备 mesh 角色（PERCEPTION/ACTION/PRESENCE）注册 |
| **桥接器 Compat 路径** | `core/routes/compat.py` | 旧 HTTP 设备路由兼容层 |
| **AI 意图** | `core/agent/kernel.py` + `core/ai_intent.py` | AI 意图解析和任务规划 |

### 1.3 Android 仓主要组件（`ufo-galaxy-android`）

| 组件类别 | 文件路径 | 真实职责 |
|---------|---------|---------|
| **主服务** | `service/GalaxyConnectionService.kt` (147KB!) | Android 前台服务。管理 WS 客户端、消息收发路由、task_assign 处理、goal_execution 处理、能力上报 |
| **WebSocket 传输层** | `network/GalaxyWebSocketClient.kt` (67KB) | OkHttp WS 客户端。指数退避重连（1s→30s）、handshake、heartbeat(30s)、离线队列集成 |
| **离线任务队列** | `network/OfflineTaskQueue.kt` | 断线时缓冲 task_result/goal_result。FIFO，最大 50 条，SharedPreferences 持久化，session authority bounding |
| **网络诊断** | `network/NetworkDiagnostics.kt` | 网络状态检查 |
| **Tailscale 适配** | `network/TailscaleAdapter.kt` | 私有网络路由适配 |
| **本地执行核心** | `agent/EdgeExecutor.kt` (16KB) | 核心本地任务执行引擎 |
| **Agent Runtime 桥** | `agent/AgentRuntimeBridge.kt` (27KB) | task_assign 的 eligible path：当 AgentRuntime 可用时委托，否则 fallback 到 EdgeExecutor |
| **自主执行管道** | `agent/AutonomousExecutionPipeline.kt` (27KB) | goal_execution 处理管道 |
| **Delegated 接管执行** | `agent/DelegatedTakeoverExecutor.kt` (20KB) | 处理 takeover_request，执行完后回传 goal_result |
| **Delegated Runtime Unit** | `agent/DelegatedRuntimeUnit.kt` (17KB) | delegated 执行单元 |
| **Handoff V2 信封** | `agent/HandoffEnvelopeV2.kt` (11KB) | V2 handoff 信封模型和验证 |
| **Handoff 合约验证** | `agent/HandoffContractValidator.kt` (10KB) | 验证 handoff 合约完整性 |
| **Handoff 合约** | `agent/DelegatedHandoffContract.kt` (16KB) | delegated handoff 合约数据模型 |
| **接管资格评估** | `agent/TakeoverEligibilityAssessor.kt` (7KB) | 判断设备是否满足接管条件 |
| **取消注册** | `agent/TaskCancelRegistry.kt` | 任务取消记录 |
| **浮动窗口服务** | `service/EnhancedFloatingService.kt` (37KB) | 浮动 UI 控件（用于可见的自动化操作） |
| **基础浮动窗口** | `service/FloatingWindowService.kt` (9KB) | 基础浮动窗口 |
| **可访问性执行** | `service/AccessibilityActionExecutor.kt` | 通过无障碍 API 执行 UI 操作 |
| **截图提供器** | `service/AccessibilityScreenshotProvider.kt` | 截图 |
| **就绪检查** | `service/ReadinessChecker.kt` (6KB) | 设备就绪检查（权限、服务状态） |
| **开机接收器** | `service/BootReceiver.kt` | 开机自启动 |
| **应用程序** | `UFOGalaxyApplication.kt` (31KB) | Application 入口，AutonomousExecutionPipeline 单例 |
| **协议定义** | `protocol/AipMessage.kt` + `protocol/MsgType.kt` 等 | AIP v3 消息模型，与中心仓 `galaxy_gateway/protocol/aip_v3.py` 对齐 |
| **OCR** | `grounding/*.kt` | 屏幕内容理解（OCR/视觉定位）|
| **WebRTC** | `webrtc/*.kt` | WebRTC 媒体通道（视频/截图流） |

---

## 2. 真实入口与链路溯源

### 2.1 中心仓所有真实 WebSocket 路径

| 路径 | 分类 | 实际处理 | 
|-----|-----|---------|
| `/ws/device/{device_id}` @ `galaxy_gateway` | **[CANONICAL]** | `_handle_android_ws()` → `android_bridge.handle_message()` → AIP v3 协议路由 |
| `/ws/android/{device_id}` @ `galaxy_gateway` | **[COMPAT]** | 同上，为老版 Android 客户端保留 |
| `/ws/android` @ `galaxy_gateway` | **[COMPAT]** | 同上，fallback compat |
| `/ws/ufo3/{device_id}` @ `galaxy_gateway` | **[LEGACY-DISABLED]** | 默认拒绝，`GALAXY_ENABLE_LEGACY_PROTOCOLS=true` 才开启 |
| `/ws/webrtc/{device_id}` @ `galaxy_gateway` | **[MEDIA]** | WebRTC 信令代理，转发到 Node_95 |
| `/ws/{device_id}` @ `galaxy_gateway` | **[DEPRECATED]** | 通用 fallback，WebSocketManager 接管，**不走 android_bridge** |
| `/ws` @ `galaxy_gateway` | **[DEBUG]** | 自动分配 ID，**不走 android_bridge** |
| `/ws/device/{device_id}` @ `core/api_routes.py` | **[COMPAT]** | 旧版 core-direct 客户端兼容路径 |
| `/ws/status` @ `core/api_routes.py` | 状态推送 | SSE/WS 状态广播 |

> **注意**: `/ws/{device_id}` 和 `/ws` 走的是 `WebSocketManager.handle_connection()`，**不进 AIP v3 协议处理管道**，这是一个 truth gap。

### 2.2 Android 上报到中心的消息类型（真实代码追溯）

下列消息类型来自 `GalaxyWebSocketClient.kt` 和 `GalaxyConnectionService.kt` 的实际 `sendJson()` 调用：

| 消息 type | 发出时机 | 中心侧 Handler | 
|----------|---------|--------------|
| `device_register` | WS 连接建立时（`onOpen`/`sendHandshake`） | `registration.handle_device_register()` → UDM + mesh session + runtime session |
| `capability_report` | WS 连接建立时 | `capability_report.handle_capability_report()` |
| `heartbeat` | 每 30 秒定时 | `heartbeat.handle_heartbeat()` → UDM heartbeat |
| `device_status` | 设备状态变化时 | `heartbeat.handle_device_status()` |
| `task_result` | EdgeExecutor 或 AgentRuntimeBridge 完成 task_assign 后 | `task_lifecycle.handle_task_result()` → 4 步 truth chain |
| `goal_result` | AutonomousExecutionPipeline 完成 goal_execution 后 | `goal_execution.handle_goal_execution_result()` |
| `task_progress` | 执行过程中进度更新 | `task_lifecycle.handle_task_progress()` |
| `task_cancel` | 用户取消或超时 | `task_lifecycle.handle_task_cancel()` |
| `command_result` | 命令级别结果 | `task_lifecycle.handle_command_result()` |
| `task_end` | 任务最终结束 | `task_lifecycle.handle_task_end()` |
| `agent_status` | Agent 状态变化 | `heartbeat.handle_agent_status()` |
| `agent_ping` | Agent ping | `heartbeat.handle_agent_ping()` |
| `diagnostics` | 诊断信息 | `diagnostics.handle_diagnostics_payload()` |
| `file_transfer` | 文件传输 | `file_transfer.handle_file_transfer()` |
| `peer_announce` | Mesh peer 上线 | `peer_exchange.handle_peer_announce()` |
| `peer_exchange` | Mesh peer 能力交换 | `peer_exchange.handle_peer_exchange()` |
| `mesh_topology` | Mesh 拓扑更新 | `mesh_topology.handle_mesh_topology()` |
| `reconciliation_signal` | 协调信号 | `reconciliation_signal.handle_reconciliation_signal()` |
| `delegated_execution_signal` | delegated 执行信号 | `delegated_signal.handle_delegated_execution_signal()` |
| `handoff_v2_result` | V2 handoff 完成 | `handoff_v2_result.handle_handoff_v2_result()` |
| `takeover_response` | 接管完成 | `takeover_response.handle_takeover_response()` |
| `vision_request` | 视觉请求 | `vision.handle_vision_request()` |

### 2.3 中心下发到 Android 的消息类型

| 消息 type | 下发时机 | Android 侧处理 |
|----------|---------|--------------|
| `task_assign` | 中心调度任务到设备 | `GalaxyConnectionService.handleTaskAssign()` → AgentRuntimeBridge（eligible）或 EdgeExecutor（fallback）|
| `goal_execution` | 目标级执行 | `GalaxyConnectionService.handleGoalExecution()` → `AutonomousExecutionPipeline` |
| `parallel_subtask` | 并行子任务 | `GalaxyConnectionService.handleParallelSubtask()` |
| `task_cancel` | 取消任务 | 触发任务取消流程 |
| `handoff_envelope_v2` | V2 handoff 信封 | `GalaxyWebSocketClient.Listener.onHandoffEnvelopeV2()` |
| `takeover_request` | 接管请求 | `GalaxyConnectionService.handleTakeoverRequest()` → `TakeoverEligibilityAssessor` |
| `device_register_ack` | 注册确认 | 客户端确认注册成功 |
| `reconnect_ack` | 重连确认 | 客户端处理 continuity_outcome |
| `ack` | 通用确认 | 静默确认 |

---

## 3. 跨仓联动关系深度分析

### 3.1 设备注册链（真实代码路径）

```
Android: GalaxyWebSocketClient.onOpen()
  → sendHandshake() [device_register msg: device_id, platform, capabilities(bitmask), model, os_version,
                     sdk_version, screen_size, app_version, runtime_attachment_session_id,
                     durable_session_id, session_continuity_epoch]
  
  ↓ WS → /ws/device/{device_id} [CANONICAL gateway path]
  
Center: galaxy_gateway/routes/websocket.py → _handle_android_ws()
  → android_bridge.handle_message()
  → android/handlers/registration.handle_device_register()
    → bridge._write_registration_to_udm()        [写 UDM SSOT - try/except，非强制]
    → bridge._devices[device_id] = AndroidDevice  [本地缓存更新]
    → bridge._sync_device_router_session()         [DeviceRouter session 同步]
    → emit_device_lifecycle_event("attach")        [可观测性，try/except]
    → build_mesh_session() + create_durable_session() + activate_durable_session()  [Mesh，try/except]
    → attach_runtime_session()                     [Runtime session，try/except]
    → attached_runtime_session_registry.register_session()  [注册表，try/except]
    → body_mesh_registry.register(roles)           [Body Mesh，try/except]
    → mesh_auto_enrollment.notify_device_registered()  [自动入组，try/except]
    → 返回 device_register_ack [含 runtime_attachment_session_id echo]
```

**闭环评估**: 连接层完整闭环。但注意 UDM 写入之后的所有步骤（7 个 try/except 块）**全部是静默降级**——即便 UDM 写入成功，后续 mesh/session/registry 步骤任何一步失败，注册都视为成功。这意味着设备可以在 attached_runtime_session_registry 中不存在的情况下被认为已注册。

### 3.2 任务执行链（真实代码路径）

```
Center: DeviceRouter.dispatch_to_websocket(device_id, task_id, payload)
  → android_bridge.send_message() / send_task()
  → android/handlers/task_submit.handle_task_execute()
  → WS message [task_assign: task_id, payload, route_mode, capability, trace_id]

Android: GalaxyConnectionService.handleTaskAssign(taskId, payloadJson, traceId)
  → 判断 AgentRuntimeBridge.isEligible()
    [true]  → AgentRuntimeBridge.handoff(payload)
               → （内部处理，结果回传）
    [false] → executeLocally(payload)  [via EdgeExecutor]
               → EdgeExecutor.execute(actions)
               → UI actions via AccessibilityService / Shell 等
  → sendTaskResult(taskId, status, result, traceId)
    → GalaxyWebSocketClient.sendJson(task_result_envelope)

  ↓ [若 WS 断线]
  → OfflineTaskQueue.enqueue("task_result", json, sessionTag=durableSessionId)
  
  [重连后]
  → offlineQueue.discardForDifferentSession(currentDurableSessionId)  [清除过期 session 的消息]
  → offlineQueue.drainAll()
  → 逐条 sendJson() 回传

Center: galaxy_gateway/android/handlers/task_lifecycle.handle_task_result()
  → check_result_idempotency(task_id)      [跨重启去重，durable store]
  → record_result_idempotency(task_id)
  → run_task_result_truth_chain(message)   [4 步 truth chain]
    step1: ingest_android_participant_truth_message()  [try/except]
    step2: reconcile_inbound_message()                  [try/except]
    step3: canonical_task.update_lifecycle()            [try/except]
    step4: canonical_completion_ingress.notify()        [try/except]
  → bridge._pending_responses[task_id].set_result()  [解除 Future 等待]
  → device_router.handle_task_result(task_id, result)  [解除 task_events wait]
  → store_task_result() [OpenClawd 记忆回流]
```

**闭环评估**: 核心路径完整，但有关键 gap：truth chain 4 步全部是 try/except 静默降级。即便某步失败，handler 继续，`is_truth_chain_complete` 会是 False 但只打 warning，不阻断。

### 3.3 Goal 执行链（真实代码路径）

```
Center → Android: goal_execution msg [task_id, goal, steps, trace_id]

Android: GalaxyConnectionService.handleGoalExecution()
  → AutonomousExecutionPipeline.handleGoalExecution(payload)
    → （内部多步骤执行，通过 grounding/OCR/LLM 驱动）
  → sendGoalResult(taskId, status, result, traceId)
    → GalaxyWebSocketClient.sendJson(goal_result_envelope)

Center: galaxy_gateway/android/handlers/goal_execution.handle_goal_execution_result()
  → 更新设备状态
  → memory backflow
  （注意：goal_result 没有完整的 4 步 truth chain，只有部分 ingress）
```

**闭环评估**: 部分闭环。goal_result 没有与 task_result 同等的 truth chain 处理。

### 3.4 重连与离线恢复链（真实代码路径）

```
Android: GalaxyWebSocketClient
  onFailure / onClosing:
    → isConnected = false
    → scheduleReconnect()  [指数退避: 1s→2s→4s→8s→16s→30s + 最多1s jitter, max 10次]
  
  onOpen [重连成功]:
    → 发 device_register (或 device_reconnect) [含 runtime_attachment_session_id]
    → offlineQueue.discardForDifferentSession(currentDurableSessionId)  [清过期 session 消息]
    → offlineQueue.drainAll()  [FIFO 回放 task_result/goal_result]
    → 逐条 sendJson()

Center: registration.handle_device_reconnect()
  → classify_reconnect_outcome(device_id, runtime_attachment_session_id)
    → "continuity_resume": reconnect_session() [保留 stable runtime_session_id]
    → "new_attachment":    register_session()  [新建 attachment]
  → 返回 reconnect_ack [含 continuity_outcome]
```

**闭环评估**: 这一块实现是整个系统里最完整的。session continuity 有明确的 resume vs new_attachment 分类，offline queue 有 session authority bounding（防止跨 session 的 stale 消息被重放），持久化支持跨进程重启。

### 3.5 Handoff V2 / Takeover 链

```
Center → Android: handoff_envelope_v2 [takeover_id, goal, context]

Android: GalaxyConnectionService
  → TakeoverEligibilityAssessor.assess()
  [eligible] → DelegatedTakeoverExecutor.execute()
               → (执行接管目标)
               → sendGoalResult(takeover_id, "success", ...)
  [not eligible] → 发 capability_limitation 信号 + degrade reply

Center: android/handlers/takeover_response.handle_takeover_response()
       android/handlers/handoff_v2_result.handle_handoff_v2_result()
  → android_delegated_runtime_lifecycle_coordinator
```

**闭环评估**: 代码存在，协议对齐，但 DelegatedTakeoverExecutor 内部的实际执行深度（是否能真的接管一个完整的 app/goal）需要更深入的本地执行能力验证。

---

## 4. 本地执行链路分析

### 4.1 EdgeExecutor (Android) 能执行什么

从 `agent/EdgeExecutor.kt` 中追溯：EdgeExecutor 接受 `TaskAssignPayload`，执行 actions 列表。支持的 action 类型包括：
- GUI 操作（触摸、点击、滚动、文字输入）
- Accessibility Service 驱动的 UI 操作
- Shell 命令（有限）
- 截图
- OCR 文字识别（通过 grounding 模块）

EdgeExecutor 的状态枚举：`STATUS_SUCCESS`, `STATUS_ERROR`, `STATUS_CANCELLED`, `STATUS_TIMEOUT`。

**局限**:
1. EdgeExecutor 本质上是一个"命令解释器"，不是 LLM 驱动的自主执行器。更高层的自主规划靠 AgentRuntimeBridge/AutonomousExecutionPipeline。
2. AgentRuntimeBridge.isEligible() 的判断逻辑决定了哪些任务走 LLM 规划路径，这一逻辑是否完整不在本次代码追溯范围内。

### 4.2 AutonomousExecutionPipeline（goal_execution）

从 `agent/AutonomousExecutionPipeline.kt` (27KB) 文件大小和调用链来看：
- 由 `UFOGalaxyApplication` 初始化单例
- `GalaxyConnectionService` 收到 `goal_execution` 时调用 `handleGoalExecution(payload)`
- 内部涉及 inference/grounding/OCR
- 结果通过 `sendGoalResult()` 回传

**局限**:
1. AutonomousExecutionPipeline 内部是否依赖本地 LLM（`inference/` 模块）还是总是需要联网调用中心侧 AI，从代码外部不完全清楚。
2. GalaxyConnectionService 中 capability_report 的 `local_model_inference` 标志只在 "both components up" 时才报告 true，说明本地推理是条件性可用的。

---

## 5. Truth / Governance / Acceptance 链路分析

### 5.1 Truth Chain 实际代码分析

**`core/task_result_canonical_truth_chain.py`** 的 `run_task_result_truth_chain()`:

```python
# Step 1: truth_ingress
try:
    outcome1 = ingest_android_participant_truth_message(...)  # best-effort
except:
    # 静默降级，步骤标记为 False

# Step 2: reconcile  
try:
    outcome2 = reconcile_inbound_message(...)  # best-effort
except:
    # 静默降级

# Step 3: authority_state_update
try:
    canonical_task.update_lifecycle(...)  # best-effort
except:
    # 静默降级

# Step 4: completion_linkage
try:
    canonical_completion_ingress.notify(...)  # best-effort
except:
    # 静默降级

return TruthChainOutcome(is_truth_chain_complete = all_four_steps_ran)
```

`is_truth_chain_complete = False` 时，`handle_task_result()` 只打一条 WARNING 日志，**不阻断、不拒绝**。

**结论**: truth chain 是"名义上强制、实际上 best-effort"。是否真正关闭了 truth 循环取决于所有依赖模块是否可用。

### 5.2 Governance 层

从代码追溯：
- `core/agent_governance/` 子包存在（agent_role.py, dispatch_summary.py, handoff_policy.py, ownership_summary.py, responsibility_graph.py）
- `config/governance_policy.json` 存在
- `core/routes/governance.py` 路由存在

但从 task_result 的实际处理路径来看，governance 层**没有被 task_result 处理链路调用**。governance 更像是一个独立的策略/配置层，而不是一个在任务执行中主动 enforce 的 verdict 层。

### 5.3 Acceptance / Final Review

- `core/canonical_completion_ingress.py` - 完成通知机制，解除 awaiter
- `core/routes/approvals.py` - HITL（Human-in-the-loop）审批路由
- `core/routes/audit.py` - 审计日志路由

**实际 Acceptance 链路**:
1. task_result 到达 → truth chain（best-effort）→ completion_ingress.notify()
2. completion_ingress 解除任何等待 Future/Event
3. **没有看到"最终验收 verdict"机制** — 没有一个显式的 "accepted/rejected" 状态转变

**结论**: acceptance 层是"completion = accepted"的 optimistic assumption，没有显式的 verdict gate。

---

## 6. 关键 Gap 清单（按影响优先级排序）

### Gap 1: Truth Chain 步骤均为 best-effort，无强制阻断 [HIGH]
- **位置**: `core/task_result_canonical_truth_chain.py`
- **现象**: 4 步 truth chain 全部 try/except 包裹，任何步骤失败不阻断流程
- **影响**: `is_truth_chain_complete = False` 只是一个 warning，不影响后续处理
- **对比**: task_result 在 compat 路径（`core/api_routes.py`）还是用的旧 PR-886 逻辑

### Gap 2: Compat WS 路径 (`/ws/device` @ core/api_routes.py) vs Canonical Gateway 路径
- **位置**: `core/api_routes.py` 中的 `/ws/device/{device_id}` handler
- **现象**: compat 路径的 task_result 处理与 gateway canonical handler 分离
- **影响**: 旧版 Android 客户端连接 compat 路径时，truth chain 调用行为可能不一致

### Gap 3: Device 注册后续步骤（Mesh/Session/Registry）全是 try/except [MEDIUM]
- **位置**: `galaxy_gateway/android/handlers/registration.py`
- **现象**: UDM 写入后的 7 个步骤全部 try/except 静默降级
- **影响**: 设备注册成功但可能在 runtime_session_registry、body_mesh_registry 中不存在
- **后果**: 下游依赖这些 registry 的调度决策可能出错

### Gap 4: goal_result 没有完整 truth chain [MEDIUM]
- **位置**: `galaxy_gateway/android/handlers/goal_execution.py`
- **现象**: goal_execution_result 处理没有 run_task_result_truth_chain
- **影响**: goal_result 的 truth/governance 处理比 task_result 弱

### Gap 5: AutonomousExecutionPipeline 与中心 AI 联动的完整性未确认 [MEDIUM]
- **位置**: `agent/AutonomousExecutionPipeline.kt` + `agent/inference/`
- **现象**: 本地推理能力条件性可用（本地 LLM 需要两个组件都 up）
- **影响**: goal_execution 在某些设备状态下可能 fallback 到仅靠中心 AI，此时延迟很高

### Gap 6: `/ws/{device_id}` 和 `/ws` 路径不走 AIP v3 协议管道 [LOW-MEDIUM]
- **位置**: `galaxy_gateway/routes/websocket.py`
- **现象**: 这两个 path 走 WebSocketManager 不走 android_bridge
- **影响**: 通过这两个路径连接的设备不会触发 UDM 注册、truth chain 等

### Gap 7: Final Acceptance / Verdict 机制缺失 [MEDIUM]
- **位置**: 整个系统
- **现象**: task 完成 = accepted（optimistic），无明确的 verdict gate
- **影响**: 如果任务结果是 false positive（Android 报告 success 但实际未完成），系统无法发现

### Gap 8: Offline Queue 回放时中心侧无幂等 ACK 机制 [LOW]
- **位置**: `core/durable_result_idempotency.py` vs `network/OfflineTaskQueue.kt`
- **现象**: Android 回放后 WS 消息无中心侧 replay-ack 确认，重连多次可能触发多次 drainAll
- **影响**: 理论上可能存在重放，但 durable_result_idempotency 在中心侧有去重保护

---

## 7. 完成度评估（基于真实代码）

### 7.1 完整闭环（已可用）

| 链路 | 评语 |
|-----|-----|
| WebSocket 连接层（设备注册 + 心跳 + 断线检测） | ✅ 完整闭环 |
| 离线队列 + 重连回放 + session authority bounding | ✅ 完整闭环（Android 侧设计周全） |
| 重连 continuity 分类（resume vs new_attachment） | ✅ 完整闭环 |
| AIP v3 消息协议对齐（Android ↔ Center） | ✅ 完整闭环（20+ 消息类型均有 handler） |
| task_assign 派送 → task_result 回收 基本路径 | ✅ 完整闭环（路径通） |
| Durable 幂等去重（task_result） | ✅ 完整闭环 |

### 7.2 部分闭环（主路径通但有明确 gap）

| 链路 | 评语 |
|-----|-----|
| Truth Chain（4 步 best-effort） | ⚠️ 路径存在但非强制 |
| 设备注册后续（Mesh/Session/Registry） | ⚠️ 注册入口通，后续步骤全 try/except |
| task_assign → EdgeExecutor 本地执行 | ⚠️ 路径通，但执行能力依赖 Accessibility 权限和本地状态 |
| Goal 执行（AutonomousExecutionPipeline） | ⚠️ 结构存在，但本地 LLM 是条件性可用的 |
| UDM 设备状态 SSOT | ⚠️ 写入路径存在，但 UDM 本身是否有完整的生命周期实现待确认 |
| DeviceRouter 调度决策 | ⚠️ 路径存在，但调度决策依赖 UDM 状态，间接受前述 gap 影响 |
| Handoff V2 / Takeover | ⚠️ 协议对齐，本地执行能力待验证 |

### 7.3 名义存在但未闭环（代码有但关键环节缺失）

| 链路 | 评语 |
|-----|-----|
| Final Acceptance / Verdict | ❌ completion_ingress 存在，但无明确 verdict gate |
| Governance 主动 enforce | ❌ governance_policy.json + governance routes 存在，但不在任务执行链路中 enforce |
| Goal result truth chain | ❌ goal_result 没有完整 4 步 truth chain |
| P2P Mesh 任务协同 | ❌ mesh_topology/peer_exchange 代码存在，但实际 P2P 协同调度路径未追溯到完整闭环 |
| Federation（多中心实例） | ❌ federation routes 存在，实际跨实例任务调度未确认 |

### 7.4 明显未完成

| 链路 | 评语 |
|-----|-----|
| 完整系统端到端集成测试 | ❌ tests/ 目录中存在大量单元测试，但缺少真实 E2E 链路测试 |
| LLM 驱动的本地 AutonomousExecutionPipeline 完整性 | ❌ 本地推理条件性可用，未在所有设备上验证 |
| WebRTC 媒体通道与任务执行的集成 | ❌ WebRTC 路径存在（`/ws/webrtc/`），与主任务链路未集成 |

---

## 8. 模块职责矩阵

```
                    中心仓              Android 仓
────────────────────────────────────────────────────────
连接/传输        gateway/routes/websocket  network/GalaxyWebSocketClient
                 android_bridge (AIP v3)   (OkHttp WS, handshake, heartbeat)

设备注册         handlers/registration      (sendHandshake)
                 UDM (SSOT)

离线队列         (durable idempotency)      network/OfflineTaskQueue
                                            (enqueue/drain/discardForDifferentSession)

重连/连续性      handlers/registration      GalaxyWebSocketClient
                 (classify_reconnect)       (scheduleReconnect, send device_reconnect)
                 attached_runtime_session_registry

任务调度         DeviceRouter               (被动接收)
                 canonical_task_dispatch_chain

本地执行          (不涉及)                  agent/EdgeExecutor
                                            agent/AgentRuntimeBridge

自主执行         (AI 规划/意图)              agent/AutonomousExecutionPipeline
                 core/agent/kernel          (handleGoalExecution)

真值更新         task_result_canonical_truth_chain   (上报结果)
                 android_participant_truth_ingress
                 android_execution_signal_reconciler

完成通知         canonical_completion_ingress        (sendTaskResult/sendGoalResult)
                 device_router.handle_task_result

记忆回流         core/openclawd_memory_backflow      (结果源)

治理/策略        core/agent_governance/              (无主动 enforce)
                 config/governance_policy.json

可观测性         runtime_observability_sink          observability/GalaxyLogger
                 Prometheus + Grafana
```

---

## 9. 接下来最值得修的优先级列表

以下优先级基于"影响整套系统能完整使用"的判断，不是简单按代码质量排序：

### P0: 让一个真实任务完整走通

**当前问题**: truth chain 是 best-effort，task 完成可能不等于 truth 关闭。

**修法**:
1. `core/task_result_canonical_truth_chain.py` 中将 Step3（authority_state_update）和 Step4（completion_linkage）改为 hard fail — 如果这两步失败，应该 retry 或标记 unresolved，而不是静默降级
2. `handle_task_result` 中：`is_truth_chain_complete = False` 时应触发 retry 或 dead-letter，而不是只打 warning

### P1: 设备注册确保 Runtime Session 真正落地

**当前问题**: UDM 写入后的 7 个注册副作用全部 try/except，可能导致 runtime_session_registry 缺失。

**修法**:
1. `registration.handle_device_register()` 中将 `attach_runtime_session` 和 `attached_runtime_session_registry.register_session()` 升级为 **必须成功** 的步骤（或至少在失败时拒绝注册）
2. 对 UDM 写入失败加告警+断路器，而不是仅 logger.warning

### P2: goal_result 补充 truth chain

**当前问题**: goal_result 的 truth 处理比 task_result 弱。

**修法**:
1. `handlers/goal_execution.handle_goal_execution_result()` 也调用 `run_task_result_truth_chain`（或专门的 goal_result_truth_chain）

### P3: Acceptance / Verdict 机制

**当前问题**: 无明确 final acceptance verdict，task completion = accepted。

**修法**:
1. 引入 `task_acceptance_ledger` — 记录每个 task 的 verdict（accepted/rejected/pending_review）
2. `CanonicalCompletionIngress` 改为驱动一个明确的 acceptance verdict，而不是仅仅解除等待

### P4: 集成测试 / 链路冒烟测试

**当前问题**: 没有真实的端到端链路测试，只有单元级别的 mock 测试。

**修法**:
1. 添加 `tests/integration/test_e2e_task_lifecycle.py`
2. 使用真实的 FastAPI WebSocket 测试客户端模拟 Android 全流程（register → receive task_assign → send task_result → verify truth chain closed）

### P5: AutonomousExecutionPipeline 条件性降级处理

**当前问题**: 本地 LLM 不可用时 goal_execution 的降级路径不明确。

**修法**:
1. `GalaxyConnectionService.handleGoalExecution()` 中明确处理 "本地 LLM 不可用" 时的 fallback（向中心请求 LLM 推理，或明确报告 capability_unavailable）

---

## 附录 A: 关键文件索引

### 中心仓 (ufo-galaxy-realization-v2)

| 文件 | 行数/大小 | 核心作用 |
|-----|---------|---------|
| `main.py` | 159行 | 系统编排入口 |
| `galaxy_gateway/routes/websocket.py` | 257行 | WebSocket 路由（CANONICAL + COMPAT） |
| `galaxy_gateway/android_bridge.py` | ~400行 | Android 桥接层（transport adapter） |
| `galaxy_gateway/android/handlers/registration.py` | 447行 | 设备注册处理 |
| `galaxy_gateway/android/handlers/task_lifecycle.py` | 553行 | 任务结果处理（最核心） |
| `galaxy_gateway/protocol/aip_v3.py` | 协议定义 | AIP v3 协议 SSOT |
| `core/api_routes.py` | ~300行+ | Core API 聚合（含 compat WS） |
| `core/task_result_canonical_truth_chain.py` | ~80行头 | 4 步 truth chain |
| `core/durable_result_idempotency.py` | - | 跨重启幂等去重 |
| `core/attached_runtime_session_registry.py` | - | Runtime session 注册表 |
| `core/unified/device_manager.py` | - | 设备状态 SSOT |
| `core/openclawd_memory_backflow.py` | - | 任务结果记忆回流 |

### Android 仓 (ufo-galaxy-android)

| 文件 | 大小 | 核心作用 |
|-----|-----|---------|
| `service/GalaxyConnectionService.kt` | 147KB | 核心服务（任务接收+执行+回传） |
| `network/GalaxyWebSocketClient.kt` | 67KB | WS 传输层 |
| `network/OfflineTaskQueue.kt` | 10KB | 离线队列 |
| `agent/EdgeExecutor.kt` | 16KB | 本地任务执行 |
| `agent/AgentRuntimeBridge.kt` | 27KB | Agent 运行时桥接 |
| `agent/AutonomousExecutionPipeline.kt` | 27KB | 自主执行管道 |
| `agent/DelegatedTakeoverExecutor.kt` | 20KB | 接管执行 |
| `service/EnhancedFloatingService.kt` | 37KB | 浮动 UI（可视化操作） |
| `UFOGalaxyApplication.kt` | 31KB | 应用入口+单例管理 |

---

## 附录 B: 跨仓协议字段使用情况

| 字段名 | Android 发出 | 中心侧使用方式 | 真实 Authority |
|-------|------------|-------------|--------------|
| `device_id` | ✅ register/heartbeat/task_result | ✅ 所有路径主键 | Android 生成 UUID |
| `runtime_attachment_session_id` | ✅ register/reconnect/task_result | ✅ continuity_resume 分类依据 | Android 生成，中心 echo 确认 |
| `durable_session_id` | ✅ register | ⚠️ 接收但 V2 是否持久存储待确认 | Android 生成 |
| `session_continuity_epoch` | ✅ register | ⚠️ 接收但 V2 使用情况待确认 | Android 维护 |
| `capabilities` (bitmask) | ✅ register | ✅ 转换为 DeviceCapability list 存 UDM | Android 上报 |
| `status` (task result) | ✅ task_result: success/failed/error/cancelled | ✅ truth chain step1 中 authoritative 使用 | Android 本地评定 |
| `task_id` | ✅ task_result | ✅ Future 完成/truth chain 关联 | 中心分配，Android echo |
| `trace_id` | ✅ task_result | ✅ 日志追踪，truth chain context | 中心分配，Android echo |
| `route_mode` | ✅ heartbeat/task_result | ✅ 用于 memory backflow 分类 | Android 设置 |
| `latency_ms` | ✅ goal_result | ⚠️ 日志记录，不驱动 truth | Android 测量 |
| `model` / `os_version` | ✅ register | ✅ UDM metadata | Android 上报 |
| `local_model_inference` | ✅ capability_report | ⚠️ 接收，不确定是否驱动调度决策 | Android 条件性上报 |

---

*本文档基于 2026-04-29 对两仓最新提交的真实代码追溯。所有结论均有明确代码路径依据。*
