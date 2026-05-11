# 基于双仓完整真实代码的最终主链与系统职责全景审查（中文）

> **定位**：本文是针对 `DannyFish-11/ufo-galaxy-realization-v2`（V2 中心仓）与 `DannyFish-11/ufo-galaxy-android`（Android 端仓）的最终全景级系统审查。所有结论以真实代码路径、函数名、模块名为锚点，不含文档噪音，不含含糊抽象。  
> **代码基准**：V2 本仓截至最新合入 PR（覆盖 PR-533 及其后所有收口 PR）；Android 仓以 `bfddd285a0116efd999ad0a866258a5de8a73f4f` 为代码锚点及文档引用。

---

## 目录

1. [系统本体：双仓系统到底在干什么](#1-系统本体双仓系统到底在干什么)
2. [V2 中心侧主链全景](#2-v2-中心侧主链全景)
3. [Android 端侧主链全景](#3-android-端侧主链全景)
4. [双仓交互主链全景](#4-双仓交互主链全景)
5. [本地链路全景](#5-本地链路全景)
6. [跨设备链路全景](#6-跨设备链路全景)
7. [compat / fallback / degraded / legacy / recovery 全景](#7-compat--fallback--degraded--legacy--recovery-全景)
8. [关键模块职责图谱](#8-关键模块职责图谱)
9. [哪些已经真正成立，哪些只是旁路或兜底](#9-哪些已经真正成立哪些只是旁路或兜底)
10. [真正残留的问题是什么](#10-真正残留的问题是什么)
11. [一句话最终结论](#11-一句话最终结论)

---

## 1. 系统本体：双仓系统到底在干什么

### 1.1 系统的真实定位

Galaxy 是一个**中心权威型分布式智能代理执行系统**。中心（V2）是唯一的意图决策权威和真相裁决权威；Android 设备是受控执行延伸节点，不是对等 peer。

这不是聊天机器人，也不是 P2P mesh，更不是传统 RPA 工具。它的本质是：

- **V2 决策哪里执行、执行什么、执行结果算不算数**
- **Android 在本地执行实际 GUI/传感器/网络动作并向 V2 上报**
- **V2 做最终裁决，包括"这个结果算成熟闭环还是只是运行完了"**

代码证据：

```python
# core/model_role_policy.py
class ModelRole(str, Enum):
    PRIMARY      = "primary"       # OpenClawd — 唯一决策权威
    ORCHESTRATOR = "orchestrator"  # E2E / Gateway — 计划调度只
    EXECUTOR     = "executor"      # HybridExecutor / WindowsArbiter — 动作分发
    TRANSPORT    = "transport"     # WebSocket / relay — 消息传输

# core/mesh_coordinator.py
MESH_TRANSPORT_ROLE: str = "MESH::OVERLAY_ENRICHMENT_ONLY"
MESH_ORCHESTRATION_EXCLUDED: bool = True  # mesh 不是编排权威，编排权威永远在 V2
```

### 1.2 双仓分工的本质

| 仓库 | 角色 | 核心职责 |
|------|------|---------|
| V2（`ufo-galaxy-realization-v2`） | 中心控制平面 + 唯一决策权威 | 意图裁决、路径分支、任务派发、真相维护、治理闭环 |
| Android（`ufo-galaxy-android`） | 受控设备执行节点 | 本地 GUI/传感器/网络执行、结果上报、状态维护 |
| V2 内部节点网络（`/nodes`） | 能力扩展层 | 130+ 专属能力节点（VLM、WebRTC、RAG、代码等）|

### 1.3 系统要解决的核心问题

1. **执行 dispatch**：意图进来之后，谁执行？在哪执行？用什么能力？
2. **结果回收**：执行完成后，谁的结果算数？如何确认执行实际发生了？
3. **真相裁决**：当多路证据冲突时（Android 说成功 vs V2 内部记录说失败），谁说了算？
4. **闭环治理**：什么时候可以认定这次执行真正完成、可以关闭？

系统的所有代码复杂度都服务于上面这四件事。

---

## 2. V2 中心侧主链全景

### 2.1 主链入口

```
main.py                                        ← 唯一合法启动入口
    Phase 1-7: 配置 → 模式 → 环境 → 子系统 → 运行时 → 桌面层 → 就绪汇报
        ↓
SystemOrchestrator (core/system_orchestrator.py)
        ↓
DesktopPresenceRuntime (外壳) [shell]
    tri-state lifecycle: silent → liminal → manifest
    multimodal ingress: PerceptionFrame (audio/video/system)
    runtime_session_id 在此处生成，全链路 trace 的根
        ↓ LIMINAL phase 内
OpenClawd (core/openclawd.py) [唯一决策核]
```

**`main.py` 是唯一合法入口**，`unified_launcher.py` 是从属启动器，不竞争权威。

### 2.2 OpenClawd：四阶段主链

`OpenClawd.process()` 是系统的决策核心，执行严格的四阶段流程：

```
Stage 1: Ingest（摄入）
    ├─ MultimodalBus.ingest(multimodal_context) → fusion_summary
    └─ 绑定 trace_id = runtime_session_id

Stage 2: Continuum（连续认知）
    └─ ContinuumOrchestrator.run()
        ├─ 解析意图 (intent)
        ├─ 确定执行类型 (ExecutionType: goal_execution | parallel_subtask | takeover_request | delegated_execution)
        ├─ 确定所需能力 (required_capabilities)
        ├─ 确定运行时域 (runtime_domain: local | cross_device | hybrid)
        └─ 返回 state_continuum dict

Stage 3: Branch（执行路径裁决）
    └─ _determine_execution_path(state_continuum) → execution_path ∈ {local, cross_device, hybrid, none}
        ├─ 检查本地能力是否可用
        ├─ 检查远端设备是否在线
        ├─ 过 unified_execution_governance.evaluate_execution_governance()
        │    ├─ 检查 takeover 互斥（active takeover 阻断低优先级执行）
        │    ├─ 检查 concurrency policy
        │    └─ 返回 ExecutionGovernanceVerdict(accepted=True/False)
        ├─ 若跨设备：过 android_evidence_integration.evaluate_android_evidence_integration()
        │    ├─ Dim 1: capability truth (必须是 "complete")
        │    ├─ Dim 2: lifecycle truth (不能是 missing_remote|stale_remote|conflicting_remote)
        │    ├─ Dim 3: audit authority chain (零 violations)
        │    └─ Dim 4: closed-loop invariants (零 violations)
        └─ 若 ownership transfer：过 get_latest_ownership_transfer_proof_quality_for_device()
             └─ proof_class 必须是 confirmed_strong，否则拒绝闭环

Stage 4: Manifest（执行落地）
    ├─ "local"        → _delegate_local_manifestation()
    │                      └─ DecisionExecutor + WindowsExecutionArbiter
    ├─ "cross_device" → CommandRouter.route_envelope()
    ├─ "hybrid"       → 两路并发（local + cross_device）
    └─ "none"         → 仅响应，不执行（治理拒绝 or 无可用设备）
```

### 2.3 执行治理层：unified_execution_governance

```python
# core/unified_execution_governance.py

# 4 种执行类型，严格优先级排序
class ExecutionType(str, Enum):
    goal_execution      # 优先级最低
    parallel_subtask
    delegated_execution
    takeover_request    # 优先级最高（互斥其他所有类型）

# 8 种 proof-input 质量类，只有 "complete" 通过
CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY = """
POLICY::CANONICAL_PROOF_INPUT_DIAGNOSIS_V1:
complete | stale | conflicting | malformed | unknown | downgraded | partial | missing
Only 'complete' is a passing classification.
"""

# Android 执行生命周期真相质量
class AndroidExecutionLifecycleTruthQuality(str, Enum):
    v2_local_only              # 无 Android 事件
    android_remote_confirmed   # V2 active + Android 事件新鲜且一致  ✓
    stale_remote               # Android 事件太旧  ✗
    missing_remote             # V2 active 但无 Android lifecycle 证据  ✗
    conflicting_remote         # V2 与 Android 矛盾  ✗
```

### 2.4 闭环治理层：closed_loop_governance_consolidation

5 个 canonical 阶段，单向前进，不可回退（I-06 不变量）：

```
activation → execution → observation/uplink → reconciliation → completion
```

关键约束：**到 `completion` 阶段 ≠ 成熟闭环**。

```python
# core/closed_loop_governance_consolidation.py

SYSTEM_COMPLETION_READINESS_POLICY = """
POLICY::SYSTEM_COMPLETION_READINESS_V1:
A closed loop reaching stage=completion is NOT automatically treated as
system-level mature closure. Mature closure requires:
  - center_lifecycle authority present
  - both result AND state uplinks received
  - reconciliation fully accepted (not just in_progress)
  - no reconciliation conflicts
  - runtime health stable
  - zero closed-loop invariant violations
"""

# 完整的 gap_types 列表（任何一个存在 = 非成熟闭环）
gap_types = [
    "loop_not_in_completion_stage",
    "terminal_lifecycle_not_reached",
    "terminal_truth_undetermined",
    "center_lifecycle_authority_missing",
    "missing_result_uplink",
    "missing_state_uplink",
    "reconciliation_conflict_present",
    "reconciliation_not_fully_accepted",
    "runtime_health_not_stable",
    "governance_store_read_error",
]
```

`ClosedLoopGovernanceView` 输出三个字段：
- `system_completion_ready: bool`
- `system_completion_level: str`（"not_closed" | "degraded_closed" | "mature_closed_loop"）
- `system_completion_gap_types: List[str]`

### 2.5 任务结果真相链：task_result_canonical_truth_chain

所有进入终态的结果必须走完 4 步，全部成功才算 `is_truth_chain_complete = True`：

```
Step 1: truth_ingress
    └─ android_participant_truth_ingress.ingest_android_participant_truth_message()

Step 2: reconcile
    └─ android_execution_signal_reconciler.reconcile_inbound_message()

Step 3: authority_state_update
    └─ CanonicalTaskRuntime.update_lifecycle(task_id, "succeeded|failed|timed_out")

Step 4: canonical_completion_linkage
    └─ CanonicalCompletionIngress.notify(envelope) → 解决 Future waiter

TruthChainOutcome.is_truth_chain_complete = (steps 1-4 全部成功)
```

任何一步失败 → `is_truth_chain_complete = False` → 不能认定为完整闭环结果。

---

## 3. Android 端侧主链全景

### 3.1 Android 端的入站处理主链

Android 端通过 WebSocket 与 V2 中心的 `galaxy_gateway` 连接。入站消息分发由 `GalaxyConnectionService`（Android 端）对应 V2 端的 `AndroidBridge` + `galaxy_gateway/android/handlers/` 处理。

**Android → V2 方向（上行，结果上报）：**

```
Android App (GalaxyConnectionService.kt)
    ↓ WebSocket
galaxy_gateway/android_bridge.py (AndroidBridge)
    ↓ 消息类型路由
galaxy_gateway/android/handlers/__init__.py 分发到对应 handler：

handle_device_register()     ← 设备注册（canonical reconnect path）
handle_heartbeat()           ← 心跳保活
handle_task_result()         ← 任务结果上报 → 进入 task_result_canonical_truth_chain
handle_task_progress()       ← 任务进度上报
handle_goal_execution_result() ← goal 执行结果归并
handle_takeover_response()   ← takeover 响应 → 进入 ownership transfer proof chain
handle_reconciliation_signal() ← 端侧主动 reconciliation 信号
handle_delegated_execution_signal() ← delegated execution 信号
handle_diagnostics_payload() ← 端侧诊断上报
handle_capability_report()   ← 能力注册/更新
```

**V2 → Android 方向（下行，任务派发）：**

```
CommandRouter.route_envelope(TaskEnvelope)
    ↓ select_transport_strategy()
    ├─ NATS publish → Android NATS subscriber
    ├─ WebSocket send → Android WebSocket handler
    └─ HTTP relay → Android HTTP endpoint

Android 端接收：
    AgentMessageHandler (Kotlin)
        ├─ _handle_task_execute()    ← 任务执行
        ├─ _handle_forward_log()     ← 动作执行（gui_click/gui_swipe/gui_input）
        └─ _handle_task_assign()     ← 任务分配
```

### 3.2 Android 端侧核心能力模块

基于 V2 仓对 Android 仓的代码引用（文件锚点 `bfddd285a0116efd999ad0a866258a5de8a73f4f`）：

| Android 模块 | 职责 | 对应 V2 接收点 |
|---|---|---|
| `GalaxyConnectionService.kt` | WebSocket 连接总入口、消息分发 | `AndroidBridge.dispatch_message()` |
| `AndroidCrossRepoRegressionRuntimeHooks.kt` | LOCAL_RUNTIME/DIAGNOSTICS/RECOVERY/TAKEOVER/MESH 事实信号 | `android_evidence_integration_pipeline` |
| `UnifiedTruthReconciliationSurface.kt` | 端侧真相归并（epoch gating、terminal idempotency） | `android_participant_truth_ingress` |
| `AppSettings.kt` | 端侧配置（含 takeover fallback 开关） | — |
| `AgentMessageHandler.kt` | 任务分发接收、GUI 动作执行 | `CommandRouter` 下行端 |

Android 端已将 5 类能力域纳入 dual-repo regression hooks：
- `LOCAL_RUNTIME`：本地任务运行
- `DIAGNOSTICS`：本地诊断信息
- `RECOVERY`：断线重连恢复
- `TAKEOVER`：接管控制流程
- `MESH`：mesh overlay 层

### 3.3 Android 端侧的关键不变量

从 `UnifiedTruthReconciliationSurface.kt` 的语义设计看，Android 端维护：
- **Epoch gating**：旧 epoch 的消息不更新新 epoch 的状态
- **Terminal idempotency**：终态一旦写入，不被重复上报覆盖
- **Authoritative mutation**：只有中心授权的操作才能触发状态突变

---

## 4. 双仓交互主链全景

### 4.1 完整交互序列（正常路径）

```
[用户/系统请求]
        │
        ▼
V2: main.py → SystemOrchestrator → DesktopPresenceRuntime
        │ LIMINAL phase
        ▼
V2: OpenClawd.process()
    Stage 1-3: 摄入 → 认知 → 路径裁决 → execution_path = "cross_device"
        │
        ▼
V2: CommandRouter.route_envelope(TaskEnvelope)
    ├─ validate_command_envelope()
    ├─ device selection（explicit device_id 或 DeviceScoringEngine）
    ├─ ACL check（_tool_permission_checker）
    ├─ TaskGraphRuntime.register_task()
    ├─ select_transport_strategy() → NATS > WebSocket > HTTP
    └─ dispatch（record in ReplayFoundation + AuditEventSemantics）
        │
        ▼
[Transport: NATS pub/sub | WebSocket | HTTP relay]
        │
        ▼
Android: GalaxyConnectionService 接收
    → AgentMessageHandler._handle_task_execute()
    → 本地 GUI/传感器/网络执行
    → 生成结果
        │
        ▼
Android: 上报结果
    GalaxyConnectionService → WebSocket → galaxy_gateway/AndroidBridge
        │
        ▼
V2: handle_task_result() | handle_goal_execution_result()
    → run_task_result_truth_chain()
        Step 1: android_participant_truth_ingress.ingest_android_participant_truth_message()
        Step 2: android_execution_signal_reconciler.reconcile_inbound_message()
        Step 3: CanonicalTaskRuntime.update_lifecycle() → 终态
        Step 4: CanonicalCompletionIngress.notify() → 解决 Future
    → TruthChainOutcome.is_truth_chain_complete
        │
        ▼
V2: unified_execution_governance
    → record_result_uplink() + record_state_uplink()
    → get_uplink_truth_state()（确认 result + state 双上行都收到）
    → _classify_uplink_terminal_confirmation()
        │
        ▼
V2: closed_loop_governance_consolidation
    → query_closed_loop_governance_state()
    → ClosedLoopGovernanceView {
        stage: completion,
        system_completion_ready: True/False,
        system_completion_level: "mature_closed_loop" | "degraded_closed" | "not_closed",
        system_completion_gap_types: [...]
      }
        │
        ▼
[系统结果：执行完成 + 闭环状态 + 审计 trail]
```

### 4.2 双仓状态协议契约

协议骨架（`galaxy_gateway/protocol/aip_v3.py`，AIP v3.0）：

```json
{
  "type": "device_register | heartbeat | task_submit | task_result | task_assign | goal_execution | takeover_request | ...",
  "message_id": "UUID",
  "correlation_id": "关联请求 UUID",
  "device_id": "设备标识",
  "timestamp": 1234567890,
  "payload": { ... }
}
```

**reconciliation_status 枚举**（V2 对 Android 上报后的裁决状态）：

| 值 | 含义 |
|---|---|
| `accepted` | 完整接受，闭环成立 |
| `accepted_partial_observation` | 部分接受，观察有遗漏 |
| `uplink_terminal_observation_requires_reconciliation` | 需要进一步 reconciliation |
| `uplink_only_observation` | 仅有 uplink，中心未独立确认（不够） |
| `conflict_detected` | 冲突，阻断闭环 |

**uplink-only 被明确禁止独立触发成熟闭环**（PR-1103 收口）：`uplink_only_observation` 不能升格为 `accepted`，必须等待中心侧独立确认后才可 reconciliation。

---

## 5. 本地链路全景

### 5.1 本地主链（execution_path = "local"）

```
OpenClawd._determine_execution_path() → "local"
    │
    ▼
_delegate_local_manifestation()
    └─ DecisionExecutor + WindowsExecutionArbiter
        ├─ System API（文件系统、进程管理、注册表等）
        ├─ 本地节点能力（/nodes/ 下 130+ 节点）
        └─ 本地 AgentKernel 工具链
    │
    ▼
TaskLifecycleManager
    ├─ mark_running(envelope)
    ├─ mark_done(envelope, result_summary)
    └─ mark_failed(envelope, error)
    │ 每次状态转换均：
    │ ├─ 发 M2 task.lifecycle 事件（event_bus）
    │ ├─ 发 StateEventBus 统一状态事件
    │ └─ 写 TaskMemory（终态）
    │
    ▼
task_result_canonical_truth_chain（本地简化路径）
    Step 3: CanonicalTaskRuntime.update_lifecycle()
    Step 4: CanonicalCompletionIngress.notify()
    │
    ▼
closed_loop_governance_consolidation
    → stage: completion
    → system_completion_ready: True（如果无 gap）
    → system_completion_level: "mature_closed_loop"
```

### 5.2 本地链路的真实完成度

**已成立**：
- 本地执行分流路径完整（`_determine_execution_path` → `_delegate_local_manifestation`）
- TaskLifecycleManager 实现 idempotency signal guard（同一 task_id 不重复处理）
- goal_execution.py 入口先过统一治理 gate（拒绝冲突/不合格执行）
- 本地闭环阶段（activation → execution → observation → reconciliation → completion）可在中心侧全程跟踪

**未成立**：
- 本地成功 ≠ 系统成熟闭环（completion readiness 的 gap_types 同样适用）
- 缺少长期实机稳定性证据（本地路径的 edge case 未全覆盖）

---

## 6. 跨设备链路全景

### 6.1 跨设备主链（execution_path = "cross_device"）

```
[治理 gate 全部通过]
    │
    ▼
CommandRouter.route_envelope(TaskEnvelope)
    │
    ├─ Transport 选择（三级 fallback，见第7节）
    │
    ▼
[设备端执行，结果上报]
    │
    ▼
galaxy_gateway/android/handlers/ 接收上报
    │
    ▼
AndroidDelegatedRuntimeLifecycleCoordinator
    ├─ on_handoff_dispatched()      ← 创建参与者会话记录
    ├─ on_takeover_response()       ← 接管响应 → ownership transfer proof chain
    ├─ on_reconciliation_signal()   ← 端侧 reconciliation
    ├─ on_execution_signal()        ← 执行信号
    └─ on_participant_truth_update() ← 真相更新
    │
    ▼
android_evidence_integration_pipeline
    4 维度门禁：
    ├─ Dim 1: classify_canonical_proof_input_diagnosis() → 必须 "complete"
    ├─ Dim 2: get_execution_lifecycle_truth_binding() → 不能是 stale/missing/conflicting
    ├─ Dim 3: verify_governance_authority_integrity() → 零 violations
    └─ Dim 4: assert_closed_loop_invariants() → 零 violations
    │
    ▼
unified_execution_governance
    → record_result_uplink()
    → record_state_uplink()
    → get_uplink_truth_state()（result + state 双 uplink 确认）
    → _classify_uplink_terminal_confirmation()
    │
    ▼
closed_loop_governance_consolidation
    → 最终 ClosedLoopGovernanceView
```

### 6.2 跨设备链路的真实完成度

**已成立**：
- 注册 & 连续性：`handle_device_register()` 是 canonical reconnect path（`registration.py`）
- 任务下发路径完整：`CommandRouter.route_envelope` → transport → Android
- 结果回收路径完整：Android → `handle_task_result()` → truth chain 4 步
- 中心 reconciliation：uplink truth state + reconciliation status 显式建模
- 证据门禁：4 维度 + 8 proof-input classes + 5 lifecycle truth qualities + 6 ownership proof classes
- 审计 trail：`ReplayFoundation` + `AuditEventSemantics` 每次 dispatch 均记录

**未成立**：
- 跨设备长期抖动下的稳定性证明不足（长稳实机证据缺失）
- 多设备并发冲突场景的持续稳定门禁证据不完整
- Android compat 路径影响到 V2 compat gate 的端到端追踪证据不完整

---

## 7. compat / fallback / degraded / legacy / recovery 全景

### 7.1 Legacy 路径注册表

`core/orchestration_authority/legacy_paths.py` 是 V2 系统所有 legacy/compat 路径的中央登记表。关键路径状态：

| 路径 | 状态 | 说明 |
|---|---|---|
| `core.command_router.CommandRouter.route_command` | `LEGACY_COMPATIBILITY` | route_envelope 的 compat shim |
| `galaxy_gateway.cross_device_coordinator.CrossDeviceCoordinator` | `LEGACY_COMPATIBILITY` | DeviceRouter 内部 fallback coordinator |
| `core.constellation_runtime.send_to_device` | `LEGACY_COMPATIBILITY` | 绕过 DeviceRouter 的旧 dispatch |
| `galaxy_gateway.orchestrator.task_orchestrator` | `LEGACY_COMPATIBILITY` | 旧 orchestrator 路径 |
| 旧 `/ws/device/{device_id}` WebSocket endpoint | `LEGACY_COMPATIBILITY` | 兼容入口，canonical 是 galaxy_gateway WS |
| 旧 `NodeRegistry/ProxyRelay/MeshCoordinator` 路径 | `ACTIVE_DEGRADED` | degraded fallback，标注但仍活跃 |

以 `LegacyPathStatus` 枚举分类：
- `ACTIVE`：正常使用
- `LEGACY_COMPATIBILITY`：compat 保留，有退场意图
- `DEPRECATED`：已弃用，应迁移
- `DELETED`：已删除（`DELETED` 条目保留记录用）

### 7.2 Transport 三级 Fallback

```
CommandRouter.route_envelope()
    └─ select_transport_strategy()
        优先级 1: NATS pub/sub（最优，低延迟）
            失败 →
        优先级 2: WebSocket（次优，长连接）
            失败 →
        优先级 3: HTTP relay（兜底，最高延迟）
            失败 → GatewayError[EXECUTOR_ERROR]
```

每次 transport 选择和 fallback 均记录在 `ReplayFoundation`，可审计。

### 7.3 设备选择 Fallback

```
CommandRouter.route_envelope(device_id=None)
    └─ _select_device_via_scheduler()
        └─ DeviceScoringEngine（control_plane）
            ├─ 有合格设备 → 选择最优设备
            ├─ 无合格设备 → 返回 None
            └─ device_id = None → execution_path = "none"（不执行）
```

若 explicit device_id 能力不匹配：
```
capability_graph 中找替代设备
    ├─ 找到替代 → fallback to 替代设备
    └─ 无替代 → GatewayError[CAPABILITY_MISMATCH]
```

### 7.4 Circuit Breaker（弹性控制）

```
CommandRouter._get_circuit_breaker(target)
    └─ core/resilience/circuit_breaker.py 的 CircuitBreaker
        ├─ 正常 → 通过
        ├─ 半开 → 试探一次
        └─ 断开 → GatewayError 快速失败（不等待超时）

指数退避 + jitter 重试（env 配置控制 max_retries）
```

### 7.5 Android Evidence Degraded 路径

当 Android 证据质量不达标时，进入 degraded 路径（不能参与主链闭环判断）：

| 证据质量 | 结果 |
|---|---|
| `proof_input_class` ≠ `complete` | 4 维度 Dim 1 不通过 → integration not allowed |
| lifecycle truth = `stale_remote` | Dim 2 不通过 → integration not allowed |
| lifecycle truth = `missing_remote` | Dim 2 不通过 → integration not allowed |
| lifecycle truth = `conflicting_remote` | Dim 2 不通过 + conflict flag |
| audit authority violations > 0 | Dim 3 不通过 → integration not allowed |
| closed-loop invariant violations > 0 | Dim 4 不通过 → surface gaps |

degraded 的 Android 证据不会推进 reconciliation，不会贡献 mature closure 判定。

### 7.6 Recovery 链路

`core/v2_android_recovery_continuity_hardening.py`（PR-7A，合约版本 `7a.seq11.0.0`）定义了 recovery 全套分类体系：

```python
# Session reuse 质量
class SessionReuseOutcome(str, Enum):
    # ← resumed_clean / resumed_with_gaps / new_session / rejected

# 已连接运行时真相质量
class AttachedRuntimeTruth(str, Enum):
    # ← confirmed / stale / missing / conflicting

# 证据摄入来源
class EvidenceIngressProvenance(str, Enum):
    # ← canonical_uplink / replay / fallback_fill / fabricated

# Recovery 闭环质量
class RecoveryClosureQuality(str, Enum):
    # ← clean / degraded_partial / failed / unresolved

# 结果交付分类
class ResultDeliveryClassification(str, Enum):
    # ← canonical_direct / canonical_replay / fallback_relay / missing

# Replay item 分类
class ReplayItemClassification(str, Enum):
    # ← authoritative / interpolated / stale / conflicting / fabricated
```

recovery 路径的核心约束：
- `EvidenceIngressProvenance.fabricated` 的证据**绝不**能推进闭环判定
- `ResultDeliveryClassification.missing` 必须触发 gap_type（不能静默忽略）
- `SessionReuseOutcome.rejected` 的会话必须重新注册（不能复用旧状态）

### 7.7 AIP 协议兼容层

```
AIP v1.0 消息（Android 旧端）
    ↓
galaxy_gateway/protocol/compat.py
    └─ 归一化为 AIP v3.0 格式
    ↓
AIP v2.0 消息（legacy binary）
    ↓
galaxy_gateway/legacy/ 处理
    └─ enhancements/multidevice/device_protocol.py::LegacyMessageType
```

**compat 层在网关入口处拦截**，不会污染 V2 内部 canonical 处理逻辑。但 compat 成功 ≠ canonical 成功，必须区分。

### 7.8 "伪闭环"风险点

以下三个场景最容易导致外层观察者误判系统已完成成熟闭环：

1. **uplink-only terminal**：Android 上报结果 → V2 收到 → reconciliation_status = `uplink_only_observation`。外层看到"结果收到了"，但中心未独立确认，不是成熟闭环。已被 PR-1103 明确禁止升格。

2. **compat fallback 成功**：通过 `CrossDeviceCoordinator`（legacy）路径完成了任务，记录为"成功"。但这是 compat 成功，不代表 canonical path 稳定。

3. **单设备 replay 成功**：replay 测试（`ReplayFoundation`）通过，但 replay 场景远比真实跨设备多设备并发场景简单，不能等同于稳态能力。

---

## 8. 关键模块职责图谱

### 8.1 V2 核心模块

| 模块 | 路径 | 职责 | 主链 | 旁路/compat |
|---|---|---|---|---|
| `OpenClawd` | `core/openclawd.py` | 唯一意图裁决核，4阶段执行 | **主链必要** | — |
| `ContinuumOrchestrator` | `core/continuum/` | 意图→状态连续体推进 | **主链必要** | — |
| `CommandRouter` | `core/command_router.py` | 跨设备派发唯一权威基底 | **主链必要** | `route_command` 是 compat |
| `DeviceRouter` | `galaxy_gateway/device_router.py` | 传输调度（纯基底，不做编排） | **主链必要** | `CrossDeviceCoordinator` 是 compat |
| `TaskLifecycleManager` | `core/task_lifecycle.py` | 任务状态机（created→running→done/failed） | **主链必要** | — |
| `UnifiedExecutionGovernance` | `core/unified_execution_governance.py` | 执行治理：类型/优先级/互斥 | **主链必要** | — |
| `AndroidEvidenceIntegrationPipeline` | `core/android_evidence_integration_pipeline.py` | 4维度 Android 证据门禁 | **主链必要** | — |
| `ClosedLoopGovernanceConsolidation` | `core/closed_loop_governance_consolidation.py` | 跨阶段不变量，completion readiness | **主链必要** | — |
| `TaskResultCanonicalTruthChain` | `core/task_result_canonical_truth_chain.py` | 4步真相链完整性 | **主链必要** | — |
| `AndroidDelegatedRuntimeLifecycleCoordinator` | `core/android_delegated_runtime_lifecycle_coordinator.py` | Android 事件编排 facade | **主链必要** | — |
| `CanonicalCompletionIngress` | `core/canonical_completion_ingress.py` | Future 解决，任务闭合 | **主链必要** | — |
| `AndroidExecutionSignalReconciler` | `core/android_execution_signal_reconciler.py` | 信号→追踪器 reconciliation | **主链必要** | — |
| `OwnershipTransferProofQuality` | `core/ownership_transfer_proof_quality.py` | 接管 ownership proof 分级 | **主链必要** | — |
| `V2AndroidRecoveryContinuityHardening` | `core/v2_android_recovery_continuity_hardening.py` | recovery/continuity 质量分级 | **主链辅助** | — |
| `LegacyPathRegistry` | `core/orchestration_authority/legacy_paths.py` | legacy 路径中央登记 | — | **旁路管理** |
| `CompatFallbackAuthorityGuard` | `core/compat_fallback_authority_guard.py` | compat 影响边界 enforcement | — | **旁路管理** |
| `ReplayFoundation` | `core/replay_foundation.py` | 事件 replay 记录 | 审计 | — |
| `AuditEventSemantics` | `core/audit_event_semantics.py` | 审计事件发射 | 审计 | — |
| `DeviceRegistry` | `core/device_registry.py` | 设备发现索引 | — | compat（优先 UDM） |
| `AgentBusFabric` | `core/agent_bus_fabric.py` | transport 策略选择 | **主链** | — |
| `MeshCoordinator` | `core/mesh_coordinator.py` | mesh overlay 优化 | — | **overlay**（非编排权威） |

### 8.2 Android 端核心模块

| 模块 | 路径（Android 仓） | 职责 | 主链 |
|---|---|---|---|
| `GalaxyConnectionService` | `.../service/GalaxyConnectionService.kt` | WebSocket 连接总管，消息分发入口 | **主链必要** |
| `AgentMessageHandler` | `.../agent/AgentMessageHandler.kt` | 下行任务接收，GUI 动作执行 | **主链必要** |
| `UnifiedTruthReconciliationSurface` | `.../runtime/UnifiedTruthReconciliationSurface.kt` | 端侧真相归并（epoch/idempotency/authority） | **主链必要** |
| `AndroidCrossRepoRegressionRuntimeHooks` | `.../runtime/AndroidCrossRepoRegressionRuntimeHooks.kt` | LOCAL_RUNTIME/DIAGNOSTICS/RECOVERY/TAKEOVER/MESH 信号产出 | **主链辅助** |
| `AppSettings` | `.../data/AppSettings.kt` | 端侧配置（含 takeover fallback 开关） | 配置层 |

### 8.3 V2 Gateway 层模块

| 模块 | 职责 | 主链 |
|---|---|---|
| `galaxy_gateway/android_bridge.py` (AndroidBridge) | Android WebSocket 入口，消息路由 | **主链必要** |
| `galaxy_gateway/android/handlers/registration.py` | 设备注册（canonical reconnect path） | **主链必要** |
| `galaxy_gateway/android/handlers/task_lifecycle.py` | 任务结果/进度/取消处理 | **主链必要** |
| `galaxy_gateway/android/handlers/goal_execution.py` | goal execution 结果归并 | **主链必要** |
| `galaxy_gateway/android/handlers/takeover_response.py` | takeover 响应处理 | **主链必要** |
| `galaxy_gateway/android/handlers/reconciliation_signal.py` | 端侧 reconciliation 信号 | **主链必要** |
| `galaxy_gateway/protocol/aip_v3.py` | AIP v3.0 canonical 协议定义 | **主链必要** |
| `galaxy_gateway/protocol/compat.py` | AIP v1/v2 → v3 归一化 | compat 层 |
| `galaxy_gateway/cross_device_coordinator.py` | DeviceRouter 内部 fallback coordinator | **LEGACY_COMPATIBILITY** |
| `galaxy_gateway/device_router.py` | 传输调度（基底层，不做编排） | **主链必要** |

---

## 9. 哪些已经真正成立，哪些只是旁路或兜底

### 9.1 已经真正成立的能力

以下能力有真实代码、有自动化测试、有明确的 canonical 路径：

**V2 中心侧（已成立）：**
- ✅ 唯一决策权威架构（`OpenClawd` 4 阶段主链，`MODEL_ROLE_POLICY` 强制声明）
- ✅ 执行路径 4 分支（local/cross_device/hybrid/none）判定逻辑完整
- ✅ 执行治理 gate（4 种执行类型优先级 + takeover 互斥）
- ✅ Android 证据 4 维度门禁（8 proof-input classes + 5 lifecycle truth qualities）
- ✅ 闭环 5 阶段追踪（activation→execution→observation→reconciliation→completion）
- ✅ 成熟闭环与"运行完"的显式区分（`system_completion_ready` + `gap_types`）
- ✅ 任务结果真相链 4 步完整性检查
- ✅ uplink-only 禁止独立构成成熟闭环（PR-1103 收口）
- ✅ ownership transfer proof 6 级分类（仅 `confirmed_strong` 可闭环）
- ✅ recovery continuity 全套质量分级（PR-7A）
- ✅ legacy 路径中央登记（30+ 条目，状态可机器读）
- ✅ transport 三级 fallback（NATS → WebSocket → HTTP）可审计

**Android 端侧（已成立）：**
- ✅ `GalaxyConnectionService` 作为 canonical WebSocket 入口
- ✅ 5 类能力域纳入 dual-repo regression hooks
- ✅ 端侧真相归并（epoch gating + terminal idempotency + authoritative mutation）
- ✅ AIP v3.0 协议骨架（message_id/correlation_id/type/device_id/timestamp/payload）

**双仓协作（已成立）：**
- ✅ 任务下发 canonical path（`CommandRouter.route_envelope` → transport → Android）
- ✅ 结果回收 canonical path（Android → `handle_task_result` → truth chain → reconciliation）
- ✅ 中心 reconciliation 状态显式建模（5 种 reconciliation_status）
- ✅ decision_causality 可观测（`android_originated_canonical_diagnosis`、`ownership_transfer_proof_*`、`cross_repo_truth_*`）

### 9.2 只是旁路/兜底/compat 的部分

以下部分存在代码，但不属于 canonical 主链，不能作为"系统能力已成立"的证据：

- ❌ `CrossDeviceCoordinator`（LEGACY_COMPATIBILITY）：DeviceRouter 内部 fallback，不是 canonical dispatch
- ❌ `route_command()`（LEGACY_COMPATIBILITY）：`route_envelope()` 的 compat shim，不是主路径
- ❌ `send_to_device()`（LEGACY_COMPATIBILITY）：绕过 DeviceRouter 的旧接口
- ❌ AIP v1.0/v2.0 compat 层成功：`compat.py` 归一化后视为 v3，但旧端本身尚未升级
- ❌ `MeshCoordinator` 路径：`MESH_ORCHESTRATION_EXCLUDED = True`，mesh 不是编排权威
- ❌ `DeviceRegistry`（compat over UDM）：设备发现索引，不是 canonical 能力注册
- ❌ replay 成功 = 稳态能力：`ReplayFoundation` 回放成功是审计能力，不代表实机长稳

### 9.3 完成度评分

评分维度（固定）：主链闭合 40 + 异常约束 25 + 双仓自动化证据 20 + 长稳实机证据 15

| 维度 | 评分 | 说明 |
|---|---|---|
| 双仓整体完成度 | **67/100** | 30+18+13+6 |
| 本地链路完成度 | **80/100** | 35+20+15+10 |
| 跨设备链路完成度 | **60/100** | 25+15+12+8 |
| 系统语义成立度 | **64/100** | 28+16+12+8 |

---

## 10. 真正残留的问题是什么

### 10.1 P0：结构性缺口（不解决无法称成熟系统）

**P0-1：fallback 路径与 canonical 路径尚未严格退场分离**

现象：`CrossDeviceCoordinator`、`route_command()`、`send_to_device()` 等 LEGACY_COMPATIBILITY 路径仍在运行时活跃。当这些路径被触发并成功，外层无法自动区分这是"canonical 成功"还是"compat fallback 成功"。

代码位置：
- `core/orchestration_authority/legacy_paths.py`（30+ 条 LEGACY_COMPATIBILITY 条目）
- `core/compat_fallback_authority_guard.py`（INFL-001 到 INFL-XXX 影响点注册）

缺的东西：在发布门禁中**强制拒绝** fallback 路径的成功冒充 canonical 成功。现在有登记，有边界声明，但没有在结果层面做硬性区分（result tags）。

**P0-2：跨设备长期稳定性证明不足**

现象：多设备并发冲突、持续重连洪峰、大规模 stale 证据恢复场景下，没有端到端长稳实机证据。`test_pr13a_dual_runtime_cross_repo_regression.py` 覆盖了 replay + closure + audit + readiness + diagnosis 基本闭合，但这是单设备 replay，不是真实跨设备多设备并发场景。

缺的东西：双仓长期回归门禁（多设备并发 + 重连 + 冲突 + 恢复 + 重复上报 + stale 混合场景的持续自动化验证）。

### 10.2 P1：次级结构问题（影响系统可信度）

**P1-1：双仓状态词典仍有解释缝隙**

现象：Android 端的 `reconciliation_status`、`lifecycle_status`、`readiness` 等字段和 V2 端的对应字段语义映射不完全一一对应。"可观测语义"与"可裁决语义"之间存在解释分叉（例如：Android 报 `task_done` 但 V2 判定为 `degraded_closed` 而非 `mature_closed_loop`）。

代码位置：`unified_governance_semantics.py` 的 `decision_causality` 已暴露 `android_originated_canonical_diagnosis` 等字段，但双边状态词典未整合为可机器读的统一契约文件。

**P1-2：compat 影响链路端到端追踪证据不完整**

现象：某个 compat 路径（如 AIP v1 → compat.py → v3 归一化）在 Android 端触发，经 V2 端处理，最终是否影响了 canonical gate 的判定，没有端到端可追踪的链路证据。

代码位置：`galaxy_gateway/protocol/compat.py` 有归一化逻辑，但 compat 触发事件未注入 `AuditEventSemantics`（或注入不完整）。

### 10.3 P2：增强项（不影响当前系统成立判断）

- **P2-1**：统一趋势化成熟度面板（非一次性静态分数，而是基于每次执行的滚动成熟度）
- **P2-2**：`cross_repo_truth` 与 `completion readiness` 的持续漂移监控
- **P2-3**：OpenClawd（7971 行）内部拆分（决策核 + 工具注册表 + builder helpers 分离）—— 不影响正确性，影响可维护性

### 10.4 哪些不应该再被反复误判为核心问题

以下是曾经被当作"大问题"但已经解决的，不应再视为残留问题：

- ✅ ~~"uplink-only 可以构成成熟闭环"~~：PR-1103 已明确禁止，有代码，有测试
- ✅ ~~"没有 completion readiness 区分"~~：`ClosedLoopGovernanceView` 已有 `system_completion_ready/level/gap_types`
- ✅ ~~"8 种 proof-input classes 未定义"~~：`CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY` 有完整定义，有 PR-12 回归测试
- ✅ ~~"ownership transfer 无质量分级"~~：PR-16 已有 `OwnershipTransferProofClass` 6 级分类
- ✅ ~~"recovery continuity 无分类"~~：PR-7A 已有完整的 7 类枚举，合约版本 `7a.seq11.0.0`
- ✅ ~~"legacy 路径无注册"~~：30+ 条目已登记在 `legacy_paths.py`

---

## 11. 一句话最终结论

**双仓系统已完成"能跑、能裁决、能审计、能拒绝伪闭环"的中心治理骨架（整体约 67/100），主链代码完整、证据门禁严密、legacy 路径登记在册；但 fallback 路径未从结果层面与 canonical 成功硬性区分、跨设备长期稳定性缺乏实机证明这两个结构性缺口，使它目前仍是"可运行的治理性半闭环系统"，而不是"成熟的分布式智能闭环系统"。**
