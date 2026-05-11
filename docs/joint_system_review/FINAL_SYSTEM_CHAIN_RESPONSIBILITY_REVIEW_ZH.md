# 基于双仓完整真实代码的最终主链与系统职责全景审查

**审查范围**：`DannyFish-11/ufo-galaxy-realization-v2`（V2）＋ `DannyFish-11/ufo-galaxy-android`（Android）  
**证据基线**：V2 本仓源码；Android 侧通过 V2 仓内联合审计模块（`core/pr993_dual_repo_reevaluation.py`、`core/cross_device_integration_reality.py`、`core/center_distributed_agent_system_review.py`、`core/operational_enablement_audit.py`）获取锚点，Android commit ref `ee2ea2f3563357d386422b5b45654a9a2ba3f797`。  
**风格**：每条判断均以真实模块/函数/字段/枚举为锚，无抽象概括。

---

## 1. 系统本体：双仓系统到底在干什么

这套系统的真实定位不是"AI 助手"，也不是普通 IoT 控制器。准确描述：

> **一个以 V2 为中心治理权威、以 Android 设备为执行节点、通过 WebSocket 双向协作完成跨设备任务调度与闭环审计的分布式执行系统骨架。**

### V2 在干什么

V2 是**中心侧**：

- 接收用户意图 → `OpenClawd.process()`（`core/openclawd.py`）内完成认知与执行路径裁决
- 决定任务去哪里执行：本地 Windows、跨设备 Android、还是两者同时（hybrid）
- 通过 `galaxy_gateway` 持续保有对所有已注册 Android 设备的 WebSocket 连接
- 接收 Android 上报的执行结果，进行**中心侧真相裁决与闭环判定**
- 记录并审计整个任务生命周期：创建→运行→结果上行→对账→闭环

V2 不是被动转发者，是**唯一治理权威**（`UNIFIED_EXECUTION_GOVERNANCE_AUTHORITY`，`core/unified_execution_governance.py:153`）。

### Android 在干什么

Android 是**端侧执行节点**：

- 开机即启动 `GalaxyConnectionService`（145KB 后台 Service），通过 `BootReceiver.kt` 实现开机自启
- `GalaxyWebSocketClient.kt` 连接 `ws://{host}:{port}/ws/device/{device_id}`（URL 来自 `AppSettings.effectiveGatewayWsUrl()`，`AppSettings.kt:212–230`）
- 连上后发送 `device_register` + `capability_report`，将设备能力上报给 V2
- 收到 V2 下发的任务后，本地执行：`AccessibilityActionExecutor`（真实 Accessibility API 操作）、`LoopController`（46KB 规划循环）、`CommandDispatcher`
- 执行结果通过 `goal_execution_result` / `task_lifecycle` 消息回传 V2
- 接管模式：`DelegatedRuntimeAcceptanceEvaluator` 本地判定是否接受 V2 下发的接管请求

### 双仓为什么要这样协作

V2 独立运行时只能控制 Windows 本机（System API）。当需要操作 Android 设备（触摸、截图、本地 AI 推理）时，必须经由网关将任务委派给 Android 端执行，结果再回传中心。  
Android 本身没有独立调度中心，所有任务的源头权威、执行记录、闭环判定都在 V2。

### 系统当前阶段定位

| 维度 | 判断 |
|------|------|
| 是否是 PoC | 否。主链代码真实，治理框架成型 |
| 是否是成熟分布式 AI 系统 | 否。跨设备复杂故障稳定性证明不足，本地推理默认未激活 |
| 准确定位 | **中心治理骨架已成型的半闭环双仓系统** |

---

## 2. V2 中心侧主链全景

```
用户输入
   │
   ▼
OpenClawd.process()                          [core/openclawd.py]
   │
   ├─ Stage 1: 感知摄取 (PerceptionFrame + multimodal_context)
   │
   ├─ Stage 2: Continuum 认知 (ContinuumOrchestrator → intent → state_continuum)
   │
   ├─ Stage 3: 执行路径裁决 _determine_execution_path()
   │              local | cross_device | hybrid | none
   │
   └─ Stage 4: Manifestation
         │
         ├─ local  → DecisionExecutor + WindowsExecutionArbiter    [core/decision_executor.py]
         │                                                          [core/windows_execution_arbiter.py]
         │
         └─ cross_device / hybrid
               │
               └─ CommandRouter.route_envelope(TaskEnvelope)        [core/command_router.py]
                     │
                     └─ galaxy_gateway WebSocket → Android
```

### 任务执行治理

```
ExecutionType 优先级（core/unified_execution_governance.py）
  takeover_request > parallel_subtask > goal_execution

evaluate_execution_governance(execution_type, device_id, ...)
  → ExecutionGovernanceVerdict(accepted, rejection_reason, ...)

is_takeover_active(device_id)  →  活跃 takeover 期间阻塞低优先级任务
```

### 跨设备结果回收主链（四步 truth chain）

```
Android 发出 goal_execution_result
   │
   ▼
galaxy_gateway/android/handlers/goal_execution.py::handle_goal_execution_result
   │
   ▼
UnifiedResultIngress.process(NormalizedResultEvent)              [core/unified_result_ingress.py]
   │
   ├─ Step 1: truth_ingress  → ingest_android_participant_truth_message  [core/android_participant_truth_ingress.py]
   ├─ Step 2: reconcile      → reconcile_inbound_message                 [core/android_execution_signal_reconciler.py]
   ├─ Step 3: lifecycle      → CanonicalTaskRuntime.update_lifecycle      [core/canonical_task.py]
   └─ Step 4: completion     → CanonicalCompletionIngress.notify(envelope) [core/canonical_completion_ingress.py]
               └─ 仅当 notify 返回 True 时 completion_notified=True, is_fully_closed=True
```

注：Step 1–3 失败抛 `TruthChainFailure`（强失败可见）；Step 4 失败不阻断闭环（避免通知失败影响结果真相）。

### 闭环阶段追踪

```python
# core/closed_loop_governance_consolidation.py
ClosedLoopStage: activation → execution → observation → reconciliation → completion

query_closed_loop_governance_state(execution_id, device_id)
  → ClosedLoopGovernanceView
      .stage                         # 当前所处阶段
      .reconciliation_status         # 对账状态
      .reconciliation_conflict       # 是否存在冲突
      .system_completion_ready       # 系统级成熟闭环是否就绪（非同于 stage==completion）
      .system_completion_level       # 闭环成熟等级
      .system_completion_gap_types   # 若未就绪，具体缺口类型
```

`system_completion_ready` 与 `stage==completion` 被显式拆开：到达 completion stage 不等于成熟闭环。这是主动防止伪闭环被高估的核心设计。

### 中心侧审计

```python
# core/execution_governance_audit_authority.py
get_governance_audit_summary(execution_id, device_id)
  → 包含 canonical_truth_* + cross_repo_truth_* 字段
     provenance / trust_level / freshness / confirmation_or_inference
```

---

## 3. Android 端侧主链全景

```
设备开机
   │
   ▼
BootReceiver.kt → 启动 GalaxyConnectionService（后台 Service，persistent）
   │
   ▼
GalaxyWebSocketClient.kt
   ├─ 构造 URL: AppSettings.effectiveGatewayWsUrl()   [AppSettings.kt:212-230]
   ├─ 连接 ws://{host}:{port}/ws/device/{device_id}
   ├─ Authorization: Bearer {token} (当 gatewayToken 配置时)
   └─ 重连: 指数退避 [1,2,4,8,16,30]s + jitter, MAX=10次
              (core/cross_device_integration_reality.py::ANDROID_MAX_RECONNECT_ATTEMPTS=10)
   │
   ▼
连接成功 → 发送 device_register + capability_report
   │
   ▼
V2 下发任务
   │
   ▼
GalaxyConnectionService.executeLocalTaskAssign()
   ├─ DelegatedRuntimeAcceptanceEvaluator（33KB）→ 本地判断是否接受任务
   ├─ LoopController（46KB）→ plan→ground→execute 规划循环
   ├─ AccessibilityActionExecutor → 真实 Accessibility API (tap/scroll/type)
   ├─ AccessibilityScreenshotProvider → 真实 JPEG 截图（感知输入）
   └─ CommandDispatcher → 本地能力分发
   │
   ▼
执行完成 → 发送 goal_execution_result / task_lifecycle 回 V2
   │
   ▼
[可选] 接管模式（Takeover）:
   V2 发出接管请求
   → Android DelegatedRuntimeAcceptanceEvaluator 决定 accept/reject
   → 发送 takeover_response
   → V2 core/takeover_tracking.py 记录
   → core/ownership_transfer_proof_quality.py 分类
       OwnershipTransferProofClass: confirmed_strong（唯一过关）
                                   | degraded_partial | degraded_stale
                                   | degraded_conflicting | incomplete
```

### Android 本地推理（非默认激活）

```
MobileVlmPlanner.kt   → HTTP 客户端 → llama.cpp/MLC-LLM @ 127.0.0.1:8080
SeeClickGroundingEngine.kt → HTTP 客户端 → grounding server @ 127.0.0.1:8081
LocalInferenceRuntimeManager.kt → 状态机: Stopped/Starting/Running/Degraded/Failed/SafeMode
```

代码真实，架构成立，但**默认激活的是 NoOpPlannerService**。非默认激活不等于不存在，但不能作为"当前系统主链能力"的依据。

---

## 4. 双仓交互主链全景

```
V2 gateway 启动
  galaxy_gateway/routes/websocket.py: 注册 /ws/device/{device_id}

Android 设备连接 → V2 处理 device_register
  galaxy_gateway/android/handlers/registration.py::handle_device_register
    → attached_runtime_session_registry.py: 创建/续接 session
    → classify_reconnect_outcome(): new_attachment | session_resume | ...
    → _schedule_pending_delivery_replay_on_canonical_reconnect(): 重放离线任务

V2 下发任务
  CommandRouter.route_envelope(TaskEnvelope)
    → galaxy_gateway WebSocket → Android

Android 执行并上报
  goal_execution_result / task_lifecycle → V2
  galaxy_gateway/android/handlers/goal_execution.py::handle_goal_execution_result
    → UnifiedResultIngress (四步 truth chain)

Takeover 协议
  V2 → handoff 合同 → Android
  AndroidDelegatedRuntimeLifecycleCoordinator.on_handoff_dispatched()    [core/android_delegated_runtime_lifecycle_coordinator.py]
  Android 接受/拒绝 → takeover_response
  AndroidDelegatedRuntimeLifecycleCoordinator.on_takeover_response()
    → takeover_tracking.adjudicate_takeover_ownership_convergence()
    → TakeoverOwnershipConvergenceVerdict → ownership_transfer_proof_quality

对账信号
  Android → reconciliation_signal → V2
  AndroidDelegatedRuntimeLifecycleCoordinator.on_reconciliation_signal()
    → android_participant_truth_ingress
    → android_execution_signal_reconciler
    → 审计记录

诊断信号
  Android → device_state_snapshot → V2
  android_device_state_store.py::absorb_state_snapshot()
  android_evidence_integration_pipeline.py: 能力真相质量分类
    classify_canonical_proof_input_diagnosis(): complete | stale | conflicting | malformed | unknown | downgraded | partial | missing
    仅 'complete' 是过关分类 (CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY)
```

---

## 5. 本地链路全景（Windows 侧）

```
DesktopPresenceRuntime（外壳）
  └─ tri-state lifecycle: silent / liminal / manifest
  └─ liminal 阶段 → 调用 OpenClawd.process()

OpenClawd（内核）
  └─ _determine_execution_path() → "local"
  └─ _delegate_local_manifestation()
       ├─ DecisionExecutor        [core/decision_executor.py]
       ├─ WindowsExecutionArbiter [core/windows_execution_arbiter.py]
       ├─ 本地 Skill 执行         [core/skill_loader.py]
       └─ System API (文件/状态/网络/代码)

task_lifecycle.py::mark_running / mark_done / mark_failed
  → M2 task.lifecycle 事件 (event_bus) + StateEventBus (PR-8)

CanonicalTaskRuntime.update_lifecycle()  [core/canonical_task.py]
  → 终态: done | failed | cancelled
```

本地链路主链已能闭合。`system_completion_ready` 门控防止局部成功被误认为成熟闭环。

---

## 6. 跨设备链路全景

```
Entry: OpenClawd._determine_execution_path() → "cross_device"

dispatch flow:
  CommandRouter.route_envelope(TaskEnvelope)
    ├─ ACL 检查
    ├─ lifecycle management (TaskEnvelope 状态跟踪)
    ├─ NATS / WebSocket dispatch
    └─ timeout / retry

parallel_subtask (fan-out):
  handle_parallel_subtask()  [galaxy_gateway/android/handlers/goal_execution.py]
    → unified_dispatch_readiness_gate (逐设备就绪检查)
    → 并行 dispatch 到多设备
    → ParallelResultAggregator 收集结果

result uplink:
  handle_goal_execution_result → UnifiedResultIngress (四步 truth chain)

governance:
  evaluate_execution_governance(execution_type="goal_execution", device_id)
    → ExecutionGovernanceVerdict(accepted, rejection_reason)

closed loop:
  query_closed_loop_governance_state → ClosedLoopGovernanceView
    .system_completion_ready = True  ← 仅当所有阶段通过且无冲突

重连续接:
  Android MAX_RECONNECT=10次 → 永久停止重连（无监督重启机制）
  V2 设备心跳: 60s stale / 120s purge + 90s 后台清理任务
  重连后: _schedule_pending_delivery_replay_on_canonical_reconnect
           OfflineTaskQueue replay（Android 侧）
```

**跨设备链路现状**：主链可运行，但复杂故障场景（延迟/冲突/部分完成/断线重连中途）的稳定性证明仅在单元测试层面，缺乏真机长稳证据。

---

## 7. compat / fallback / degraded / legacy / recovery 全景

### 7.1 Legacy 路径（已正式围栏）

| 路径 | 状态 | 围栏位置 |
|------|------|---------|
| `route_command()` | LEGACY_COMPATIBILITY，compat shim | `core/orchestration_authority/legacy_paths.py:239-245` |
| `galaxy_gateway.orchestrator.task_orchestrator` | LEGACY_ORCHESTRATOR_NODE | `legacy_paths.py:159` |
| Node_110_SmartOrchestrator | LEGACY_ORCHESTRATOR_NODE | `legacy_paths.py` |
| Node_81_Orchestrator | LEGACY_ORCHESTRATOR_NODE | `legacy_paths.py` |
| `tasks` route | thin compat adapter，非 canonical dispatch | `legacy_paths.py:257-258` |
| `routing_decision` top-level key | deprecated compat shim | `legacy_paths.py:287-289` |
| `perception_state` key | compat only，不得新增消费者 | `legacy_paths.py:271-274` |

`is_legacy_path()` / `emit_legacy_guardrail()` 是机器可检查的围栏 API。代码仍存在但被标记，不得作为新代码的入口。

### 7.2 AIP 协议 compat 层

```
galaxy_gateway/protocol/compat.py
  → LEGACY_TYPE_MAP: 映射 v1.0/v2.0 客户端发来的旧消息类型别名
  → 'goal_result' → 'goal_execution_result'（已修复，GOAL_RESULT_ALIAS_HANDLED=True）
  → 规范化后进入标准 handler 链
```

目的：保持对旧版 Android 客户端的向后兼容，不扩散到主链逻辑中。

### 7.3 跨设备降级路径

```
cross_device_coordinator.py  [galaxy_gateway/cross_device_coordinator.py]
  NodeRegistry / ProxyRelay / MeshCoordinator 路径
  → 被标注为 degraded fallback，非 canonical 路由
  → CommandRouter.route_envelope 是 canonical substrate
```

### 7.4 Android 配置激活屏障（最常见的"伪降级"）

```python
# core/cross_device_integration_reality.py
ANDROID_CROSS_DEVICE_DISABLED_BY_DEFAULT = True   # config.properties: cross_device_enabled=false
ANDROID_DEFAULT_URL_IS_PLACEHOLDER = True          # config.properties: ws://100.x.x.x:8765
ANDROID_RECONNECT_STOPS_PERMANENTLY_AT_LIMIT = True  # MAX_RECONNECT_ATTEMPTS=10

# core/operational_enablement_audit.py
ANDROID_CROSS_DEVICE_DEFAULT = False  # 出厂默认禁用，需要手动开启
```

这是最隐蔽的"降级"：全新部署的 Android 设备默认不参与跨设备协作，不是因为代码不在，而是默认配置禁止。

### 7.5 Recovery 路径（`core/v2_android_recovery_continuity_hardening.py`）

```python
classify_session_reuse()
  → new_attachment | session_resume | id_collision | ambiguous

classify_evidence_ingress()
  → real_android_originated | replay_queue_drained | locally_synthesised | degraded | absent

assess_recovery_closure_quality()
  → full_convergence | partial_convergence | degraded_recovery | no_recovery

interpret_replay_sequence()
  → convergence_eligible | stale_dropped | gap_exposed
```

`degraded_recovery` 和 `no_recovery` 是合法终态，必须向上层透出，不能被视为"成功"。

### 7.6 Takeover Proof 降级路径

```python
# core/ownership_transfer_proof_quality.py
OwnershipTransferProofClass:
  confirmed_strong      # 唯一过关：真相闭合
  degraded_partial      # 证据结构不完整
  degraded_stale        # 证据超时（OWNERSHIP_STALE_EVIDENCE_THRESHOLD_SECONDS）
  degraded_conflicting  # 存在 accepted+rejected 矛盾证据
  degraded_unresolved   # 无法裁决
  incomplete            # 证据缺失

# 唯一允许闭环的是 confirmed_strong
```

### 7.7 能力真相降级路径

```python
# core/unified_execution_governance.py:156-170
CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY = [
  'complete',     # 唯一过关
  'stale',        # 不过关
  'conflicting',  # 不过关
  'malformed',    # 不过关
  'unknown',      # 不过关
  'downgraded',   # 不过关
  'partial',      # 不过关
  'missing',      # 不过关
]
```

任何非 `complete` 的能力真相会把 capability_truth 维度拉到 DEGRADED。

### 7.8 本地推理默认旁路

Android 本地推理（MobileVlmPlanner / SeeClickGroundingEngine）的默认 planner 是 `NoOpPlannerService`。本地推理是架构上已成立的旁路，但不是系统当前的主链实际能力。

---

## 8. 关键模块职责图谱

### V2 中心侧模块

| 模块 | 职责 | 主链/旁路 |
|------|------|---------|
| `core/openclawd.py` | 认知核心 + 执行路径裁决 (`_determine_execution_path`) | **主链必要** |
| `core/command_router.py` | 跨设备执行 substrate（ACL/lifecycle/NATS/WS dispatch） | **主链必要** |
| `galaxy_gateway/app.py` | FastAPI 应用 + WebSocket 路由注册 | **主链必要** |
| `galaxy_gateway/android/handlers/` | 各消息类型协议处理（registration/goal_execution/task_lifecycle/takeover_response/reconciliation_signal/delegated_signal/capability_report/diagnostics） | **主链必要** |
| `core/unified_execution_governance.py` | 执行类型策略、优先级、冲突裁决、uplink truth 合并 | **主链必要** |
| `core/unified_result_ingress.py` | 结果入口（所有来源统一入口，four-step truth chain） | **主链必要** |
| `core/task_result_canonical_truth_chain.py` | 四步 truth chain 封装（must-run 步骤）| **主链必要** |
| `core/closed_loop_governance_consolidation.py` | 全环视图：阶段+对账+成熟闭环判定 | **主链必要** |
| `core/canonical_completion_ingress.py` | completion 通知（notify → 解阻等待 Future） | **主链必要** |
| `core/android_delegated_runtime_lifecycle_coordinator.py` | Android 生命周期事件统一门面 | **主链必要** |
| `core/android_execution_signal_reconciler.py` | Android 执行信号唯一对账入口 | **主链必要** |
| `core/android_device_state_store.py` | Android 设备状态存储（snapshot/capability/execution events） | **主链必要** |
| `core/attached_runtime_session_registry.py` | session 注册/续接/分类 | **主链必要** |
| `core/takeover_tracking.py` | Takeover 记录 + ownership convergence 裁决 | **主链** |
| `core/ownership_transfer_proof_quality.py` | Takeover 证明质量分类（confirmed_strong 是唯一过关） | **主链** |
| `core/android_evidence_integration_pipeline.py` | 多维度 Android 证据质量评估 | **主链** |
| `core/execution_governance_audit_authority.py` | 可审计 audit summary（canonical_truth_* + cross_repo_truth_*） | **审计/增强** |
| `core/v2_android_recovery_continuity_hardening.py` | recovery 分类（session_reuse/evidence_ingress/closure_quality/replay） | **recovery 增强** |
| `core/orchestration_authority/legacy_paths.py` | legacy/compat 路径注册与围栏 | **兼容围栏** |
| `galaxy_gateway/protocol/compat.py` | AIP 协议老版本 type alias 归一化 | **兼容层** |
| `galaxy_gateway/cross_device_coordinator.py` | NodeRegistry/ProxyRelay/MeshCoordinator（degraded fallback） | **旁路 fallback** |
| `core/swarm_coordinator.py` | 多设备 fan-out 编排（orchestration 层，决定哪些设备） | **主链扩展** |

### Android 端侧模块

| 模块 | 职责 | 主链/旁路 |
|------|------|---------|
| `GalaxyConnectionService.kt` | 持久后台 Service，设备端运行时宿主 | **主链必要** |
| `GalaxyWebSocketClient.kt` | WebSocket 传输 + 重连 | **主链必要** |
| `BootReceiver.kt` | 开机自启动 Connection Service | **主链必要** |
| `AppSettings.kt` | 配置权威（SharedPreferences，覆盖 build config） | **主链必要** |
| `AccessibilityActionExecutor.kt` | 真实 Accessibility API 操作（tap/scroll/type） | **主链必要** |
| `AccessibilityScreenshotProvider.kt` | 真实 JPEG 截图（感知输入） | **主链** |
| `LoopController.kt` | plan→ground→execute 本地规划循环（46KB） | **主链** |
| `CommandDispatcher.kt` | 本地能力分发 | **主链** |
| `DelegatedRuntimeAcceptanceEvaluator.kt` | 本地任务接受决策（33KB，主动判定） | **主链** |
| `OfflineTaskQueue.kt` | 离线任务队列 + 重放（recovery） | **recovery 旁路** |
| `TailscaleAdapter.kt` | Tailscale VPN 作为备用网络路径 | **网络旁路** |
| `AndroidCrossRepoRegressionRuntimeHooks.kt` | 双仓回归 hooks（LOCAL_RUNTIME/DIAGNOSTICS/RECOVERY/TAKEOVER/MESH） | **回归/测试面** |
| `UnifiedTruthReconciliationSurface.kt` | epoch gating + terminal idempotency + authoritative mutation | **主链** |
| `LocalInferenceRuntimeManager.kt` | 本地推理生命周期管理（Stopped/Starting/Running/Degraded/Failed/SafeMode） | **非默认旁路** |
| `MobileVlmPlanner.kt` | 本地 LLM HTTP 客户端（→ llama.cpp/MLC-LLM） | **非默认旁路** |
| `SeeClickGroundingEngine.kt` | Grounding HTTP 客户端（→ grounding server） | **非默认旁路** |
| `NetworkSettingsScreen.kt` | 设置 UI（运行时修改 URL/port/token） | **配置 UI** |
| `RemoteConfigFetcher.kt` | 从 V2 GET /api/v1/config 自动填充配置 | **配置辅助** |

---

## 9. 哪些已经真正成立，哪些只是旁路或兜底

### 已真正成立（代码＋测试双锚点）

1. **传输协议对齐**：Android 连 `/ws/device/{device_id}`（`CANONICAL_WS_DEVICE_PATH`，`cross_device_integration_reality.py:CANONICAL_WS_DEVICE_PATH`），V2 接受，AIP v3 compat 层归一化旧版 type alias。

2. **注册流程**：Android 开机 → `BootReceiver` → `GalaxyConnectionService` → `GalaxyWebSocketClient` → `device_register` + `capability_report` → V2 `handle_device_register` → `attached_runtime_session_registry`。

3. **执行路径裁决**：`OpenClawd._determine_execution_path()` 精确返回 `local | cross_device | hybrid | none`，`cross_device_dispatched` flag 控制实际路径判断（不是靠 entry_mode 猜测）。

4. **四步 truth chain**：`task_result_canonical_truth_chain.run_task_result_truth_chain()` 是 must-run，Step 1-3 失败显式抛 `TruthChainFailure`，Step 4 软失败。

5. **execution_type 优先级与互斥**：takeover 活跃期间 `is_takeover_active()` 阻塞低优先级任务，`evaluate_execution_governance()` 永不抛异常。

6. **闭环阶段追踪**：`ClosedLoopStage` 单调递进，`query_closed_loop_governance_state()` 一次调用获取全环视图，`system_completion_ready` 与 `stage==completion` 显式分离。

7. **接管证明质量分类**：`OwnershipTransferProofClass` 6 值枚举，`confirmed_strong` 唯一过关，stale 检测用 `OWNERSHIP_STALE_EVIDENCE_THRESHOLD_SECONDS`。

8. **Legacy 路径围栏**：`is_legacy_path()` / `emit_legacy_guardrail()` 机器可查，`legacy_paths.py` 是单一注册表。

9. **Android 本地执行能力**：`AccessibilityActionExecutor`（真实 Accessibility API）+ `LoopController`（真实规划循环）均有实现，不是空架子。

10. **能力真相质量门控**：8-class `CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY`，仅 `complete` 过关，其余触发 DEGRADED。

### 只是旁路、兜底、或架构存在但非当前主链实际能力

| 项目 | 实际情况 |
|------|---------|
| **Android 跨设备默认激活** | `cross_device_enabled=false`（出厂默认），需手动开启 |
| **Android 默认 URL** | `ws://100.x.x.x:8765`（Tailscale 占位符），需手动替换 |
| **Android 重连自愈** | MAX_RECONNECT_ATTEMPTS=10 后永久停止，无监督重启机制 |
| **Android 本地推理** | 代码真实，但默认是 `NoOpPlannerService`；需外部 llama.cpp/MLC-LLM 服务 |
| **OfflineTaskQueue replay** | Recovery 旁路，正常场景不激活 |
| **MeshCoordinator 路径** | degraded fallback，非 canonical 路由 |
| **AIP v1.0/v2.0 compat** | 协议兼容层，非主链，不得新增消费者 |
| **`route_command()` shim** | LEGACY_COMPATIBILITY，不得作为新代码入口 |
| **`degraded_recovery`** | 合法终态，不等于"失败"，但也不等于"成功" |

---

## 10. 真正残留的问题是什么

### 结构性缺口（非次级问题）

**P0：Android 默认不参与跨设备**  
`cross_device_enabled=false` + `ws://100.x.x.x:8765` 占位符 URL = 全新部署的 Android 设备不会连接 V2。这不是 bug，是出厂配置。但它意味着"跨设备链路"在零配置场景下完全不存在。  
代码锚点：`cross_device_integration_reality.py:ANDROID_CROSS_DEVICE_DISABLED_BY_DEFAULT` / `ANDROID_DEFAULT_URL_IS_PLACEHOLDER`

**P0：Android 重连上限后永久失效**  
10 次重连失败（约 181 秒总延迟）后 `GalaxyWebSocketClient` 永久停止，无监督重启机制。V2 也无服务侧唤醒 Android 端的机制。  
代码锚点：`cross_device_integration_reality.py:ANDROID_RECONNECT_STOPS_PERMANENTLY_AT_LIMIT`

**P1：跨设备复杂故障场景无真机 CI 门禁**  
delayed / conflicting / partial / interrupted / recovered 等场景在 `v2_android_recovery_continuity_hardening.py` 中有分类框架，在 `tests/test_pr7a_v2_continuity_reconnect_recovery.py`（77 个测试）中有单元覆盖，但无真机端到端长稳 CI 门禁。分类对了不等于行为对了。

**P1：compat 路径成功可能被误读为 canonical 成功**  
`route_command()` shim、AIP v1.0 compat 映射等路径在请求处理成功时不会在响应里注明"这是 compat 路径成功"。上层如果不检查 `execution_path` / `delegation_point` 字段，可能把 compat 成功误当 canonical 成功。

**P2：Android 本地推理默认不激活**  
"Android 本地 AI 推理"作为系统卖点之一，当前默认是 `NoOpPlannerService`。架构成立，但实际用户体验中不存在。需要显式部署外部推理服务。  
代码锚点：`center_distributed_agent_system_review.py:local_inference_capability_default_active=False`

**P2：`system_completion_ready` 缺口类型覆盖**  
`system_completion_gap_types` 枚举了可能的缺口（`loop_not_in_completion_stage` / `uplink_terminal_missing` / `reconciliation_conflict_present` / `reconciliation_not_fully_accepted`），但不包含"Android 端无真实执行回执、只有 uplink 观测"这个场景的专属 gap_type。uplink-only terminal 已被收紧（#1102/#1103），但没有独立的 gap_type 标识，使得这类伪闭环在 gap_types 层面仍不可区分。

### 哪些不应该再被误判为核心问题

- **Legacy 路径的存在**：已围栏，`is_legacy_path()` 可检查，不是核心漏洞
- **`degraded_recovery` 出现**：是合法设计终态，不是 bug
- **本地链路不完整**：本地链路（Windows 侧）主链已闭合，不是问题
- **协议消息类型覆盖不全**：已修复（`ANDROID_GOVERNANCE_REPORT_TYPES_HANDLED=True`，`GOAL_RESULT_ALIAS_HANDLED=True`）

---

## 11. 一句话最终结论

> V2 中心治理主链（认知裁决→跨设备派发→四步 truth chain→闭环阶段追踪→成熟闭环门控）已结构成型且代码真实可审计；Android 执行节点的连接、注册、本地执行、结果上报主链同样真实；**但系统整体离"开箱即用的成熟分布式 AI 执行系统"还差两个结构台阶：一是 Android 默认配置禁用跨设备、二是跨设备复杂故障场景缺乏真机长稳门禁——这两点不解决，主链再严谨也只能在受控环境下成立。**
