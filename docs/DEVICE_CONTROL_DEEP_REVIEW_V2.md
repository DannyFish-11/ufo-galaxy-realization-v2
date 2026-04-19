# Galaxy 设备控制面深度系统补强审查报告 V2

> **基于：** PR #715 母版审查 + 本轮代码事实补强审查
>
> **审查范围：** 全代码库（`core/`、`galaxy_gateway/`、`contracts/`、`nodes/`、`tests/`）
>
> **目标：** 把 #715 中所有 ❓/⚠️ 未确认项全部基于真实代码钉死，并补全 SSOT 读路径图、节点 Authority 模型、任意设备操纵全网能力分解表、Mesh 五层分解。
>
> **格式：** 中文、可直接复制粘贴、适合长期回灌。

---

## 一、补强审查现实摘要

本次补强审查基于以下关键模块的逐文件核查：

| 模块 | 角色 | 确认状态 |
|------|------|---------|
| `core/unified/device_manager.py` | UDM — 设备状态 SSOT | ✅ 已确认 |
| `core/unified/connection_manager.py` | UCM — 连接/可路由 Authority | ✅ 已确认 |
| `galaxy_gateway/android/handlers/registration.py` | Android 注册入口 | ✅ 全文核查 |
| `galaxy_gateway/android_bridge.py` | Android 连接适配器 | ✅ 全文核查 |
| `core/capability_assimilation.py` | 能力汇聚层 | ✅ 已确认（含 Gap）|
| `contracts/handoff_envelope_v2.py` | Handoff 合同 | ✅ 已确认 |
| `core/attached_runtime_session.py` | 附着 Runtime 会话 | ✅ 已确认 |
| `contracts/registered_runtime_device.py` | Android 设备合同 | ✅ 已确认 |
| `contracts/dispatch_continuity.py` | Continuity Context 合同 | ✅ 已确认（含 Gap）|
| `core/mesh/body_mesh_registry.py` | Mesh 注册表 | ✅ 已确认（含 Gap）|
| `core/runtime/source_dispatch_orchestrator.py` | 源调度编排层 | ✅ 已确认（有限生产接入）|
| `core/routes/devices.py` | 设备 REST 路由 | ✅ 已确认 |
| `core/device_readiness.py` | 设备就绪判断 | ✅ 已确认 |
| `docs/MULTI_DEVICE_RUNTIME_MATURITY.md` | Mesh 成熟度评估 | ✅ 已比对 |

**核心结论预告（详见第七节）：**

> 系统当前处于 **"SSOT 已建立、部分已进入决策路径、但尚未成为统一决策源"** 的过渡态。
> 设备节点当前是 **"有限自主权的远端执行终端"**，而非真正的"协作节点"或"全网操纵入口"。
> "任意设备操纵全网"能力综合完成度约 **15–20%**（比 PR #715 的 10–15% 略高，因为部分 Authority 模型已明确化）。

---

## 二、未确认项逐条核定表

### 核定项 1：`CapabilityAssimilationLayer.assimilate_device()` 是否在 Android 注册链中被真实触发

**核定结论：❌ 已确认不成立（Android WebSocket 注册链中未触发）/ ✅ 部分成立（REST 注册链已触发）**

**证据：**

- `galaxy_gateway/android/handlers/registration.py` 的 `handle_device_register()` 调用链：
  1. `bridge._write_registration_to_udm(device_id, message)` → 写 UDM SSOT ✅
  2. `bridge._sync_device_router_session(...)` → 同步 DeviceRouter ✅
  3. `emit_device_lifecycle_event(...)` → 发射生命周期事件 ✅
  4. `create_durable_session() + activate_durable_session()` → 创建 Mesh 会话 ✅
  5. **`assimilate_device()` 或任何 `CapabilityAssimilationLayer` 调用：❌ 不存在**

- 对比 REST 注册链 `core/routes/devices.py` 的 `/api/v1/devices/register`：
  - 调用了 `_sync_device_to_capability_registry(device_info)` → 同步能力到 CapabilityRegistry ✅
  - 但此处调用的是 `CapabilityRegistry`（内部工具注册表），而非 `CapabilityAssimilationLayer.assimilate_device()`

- `docs/FOLLOWUP_IMPLEMENTATION_ROADMAP.md` 明确标记为 **Gap CROSS-004**：
  > "Android `device_capabilities` message received by V2 but not confirmed forwarded to `CapabilityAssimilationLayer.assimilate_device()`"

**结论：Android WebSocket 注册路径中 `assimilate_device()` 未触发，这是已知但未修复的 Gap。Android 设备注册后不会自动进入能力路由平面，无法通过 `query_routable_executors()` 被发现。**

---

### 核定项 2：Android 侧是否原生消费 `HandoffEnvelopeV2`

**核定结论：❌ 已确认不成立（Android 不原生消费 HandoffEnvelopeV2，以 task_assign 语义近似消费）**

**证据：**

- `contracts/handoff_envelope_v2.py` 是 V2 仓库内的合同层类型，`HandoffEnvelopeV2` 是 Python Pydantic 模型。

- Android 客户端通过 WebSocket JSON 消息通信，Android 端（独立仓库）没有引入 `handoff_envelope_v2.py`。

- `handle_goal_execution()` 处理来自 Android 的 `goal_execution` 消息后，返回 `MessageBuilder.task_assign(...)` —— **V2 将目标执行下发语义翻译成 `task_assign` 消息发给 Android，而非 `HandoffEnvelopeV2`。**

- `docs/ugcp/CROSS_REPO_HOMOMORPHIC_MAPPING_V1.md` 明确：
  > `SourceDispatchOrchestrator` 没有 Android 直接等价物；Android 是 dispatch *target*，不是 dispatch orchestrator。

- `HandoffEnvelopeV2` 中的 `from_legacy_handoff_contract()` 和 `from_bridge_inputs()` 是 V2 仓库内的适配器，用于在 V2 内部生成 envelope，**不是 Android 侧可直接解析的消息格式**。

**结论：Android 通过 `task_assign` 消息消费来自 V2 的 dispatch 语义（包括 goal_execution 结果）。HandoffEnvelopeV2 是 V2 侧的编排合同，未下推到 Android Wire Protocol。**

---

### 核定项 3：`goal_result` 是否真实存在、真实发送、真实消费，以及其与 `task_result` 的关系

**核定结论：✅ 部分成立（goal_result 以 `GOAL_EXECUTION_RESULT` 消息类型真实存在并被消费，与 `task_result` 并行但语义层级不同）**

**证据：**

- `galaxy_gateway/android/handlers/goal_execution.py` 中存在 `handle_goal_execution_result()` 处理函数：
  - 接收 `GOAL_EXECUTION_RESULT` 类型消息（Android → V2）
  - 写入 `TaskMemory`（`store_task_result()`）
  - 触发 `runtime.on_goal_execution_result()` OpenClawd 反馈
  - 通过 PR-13 路径调用 `reconcile_inbound_message()` 进行执行信号对齐

- `handle_task_result()` 在 `task_lifecycle.py` 中处理 `task_result` 类型消息：
  - 完成等待的 Future（`bridge._pending_responses`）
  - 更新设备状态
  - 调用 `_try_reconcile(message)`

**两者的关系：**

| 维度 | `task_result` | `goal_execution_result` |
|------|--------------|------------------------|
| 触发场景 | 单个 task 执行完成 | 高层 goal 执行完成（可包含多步）|
| Future 解除 | ✅ 直接解除 pending_responses | ❌ 不直接解除 Future |
| 内存回流 | 通过 `_try_reconcile` | 通过 `store_task_result` |
| 反馈路径 | 无直接 OpenClawd 反馈 | ✅ 触发 `on_goal_execution_result` |
| PR-13 对齐 | ✅ | ✅ |

**结论：`goal_execution_result` 真实存在并被消费。它不是 `task_result` 的别名，而是语义上更高层的结果回传，针对高层目标执行（goal_execution）而非单步任务（task）。两者并行共存于系统中。**

---

### 核定项 4：`runtime_attachment_session_id` 是否在双仓之间被真实创建、传递、消费、恢复

**核定结论：⚠️ 部分成立（V2 侧真实创建和恢复；Android 侧未收到该 ID；双边传递未闭环）**

**证据（V2 侧）：**

- `core/attached_runtime_session.py` 的 `attach_runtime_session()` 接受 `runtime_attachment_session_id` 参数并写入 `AttachedRuntimeSessionRecord`
- `galaxy_gateway/android_bridge.py` 的 `reconnect_device()` 调用 `reconnect_session()` 恢复已有 session record
- V2 侧的 session 在断线重连后确实被恢复（`AttachedRuntimeSessionRuntime.replace_latest_for_device(updated)`）

**证据（Android 侧 / 双边传递）：**

- `handle_device_register()` 的注册 ACK（`MessageBuilder.device_register_ack(..., session_id=str(uuid.uuid4()), ...)`）返回的 `session_id` 是**随机生成的 UUID**，**不是** V2 侧 `attach_runtime_session()` 返回的 `runtime_attachment_session_id`
- 没有发现 Android 客户端保存并在后续消息中回传 `runtime_attachment_session_id` 的机制
- Android 的 `reconnect` 是 WebSocket 层面的重连，V2 侧通过 `device_id` 查找并恢复 session，而非通过 Android 回传 session_id

**结论：`runtime_attachment_session_id` 在 V2 单边真实存在、维护并在断线重连时恢复。但它未被传递到 Android 端，Android 无法主动携带该 ID 进行关联。双边传递未闭环 —— 这是一个单边运行的会话跟踪机制。**

---

### 核定项 5：Android 注册/重连时是否上报 `source_runtime_posture`

**核定结论：✅ 已确认成立（Android 可上报，V2 正确读取）**

**证据：**

- `contracts/registered_runtime_device.py` 的 `from_android_registration()` 中：
  ```python
  raw_posture = data.get("source_runtime_posture", "")
  if raw_posture == "join_runtime":
      _posture = "join_runtime"
  else:
      _posture = "control_only"
  ```

- `tests/test_pr5_android_runtime_host_main.py` 包含 `_android_payload()` 默认带 `"source_runtime_posture": "join_runtime"` 的标准载荷

- `contracts/source_posture_contract.py` 定义了稳定的合同字段，注释明确：
  > "Give the Android repo a clear, dependency-free contract module to adopt in a subsequent PR without pulling in `core/` internals."

**边界条件：**
- 若 Android 不传 `source_runtime_posture`（旧版 App）→ V2 默认 `control_only`
- 若传未知值 → 回退 `control_only`
- `is_runtime_host` 为 True 的条件：`source_runtime_posture == "join_runtime"` 或 `app_version` 存在（任一即可）

**结论：Android 设备在注册消息中可以上报 `source_runtime_posture`，V2 正确读取并设置 `is_runtime_host` 标记。这是已合同化且已生产化的功能。**

---

### 核定项 6：continuity token / `DispatchContinuityContext` 是否在重连路径中真实重关联

**核定结论：❌ 已确认不成立（DispatchContinuityContext 合同存在但重连路径未真实重关联）**

**证据：**

- `contracts/dispatch_continuity.py` 定义了 `DispatchContinuityContext`，带有 `prior_dispatch_id`、`prior_session_id`、`prior_mesh_session_id` 等字段，并有策略标注：
  > "DispatchContinuityContext is designed to survive reconnect/handoff scenarios."

- `galaxy_gateway/android_bridge.py` 的 `reconnect_device()` 执行步骤：
  1. 恢复 WebSocket 连接引用
  2. `_patch_reconnect_to_udm(device_id)` → 更新 UDM 状态
  3. `reconnect_session()` → 恢复 `AttachedRuntimeSessionRecord`（以 `device_id` 为 key）
  4. 恢复 `MeshSession`（`restore_durable_session()`）
  5. 发射 `reconnect` 生命周期事件

- **重连流程中没有任何代码查询或重关联 `DispatchContinuityContext`**

- `SourceDispatchResult` 有 `continuity_context` 字段，但它在重连时不被读取

**结论：`DispatchContinuityContext` 是一个设计完备的合同，已被加入到 `SourceDispatchResult` 等结构中，但在真实的 Android 断线重连流程里没有消费者去读取和重关联它。它目前是"合同先行，运行层未跟上"的状态。**

---

### 核定项 7：`MeshMembership` / `BodyMeshRegistry` 是否在任何生产路径中自动或半自动写入

**核定结论：⚠️ 部分成立（半自动写入：Android 注册时创建 MeshSession，但 BodyMeshRegistry.register() 不被自动调用）**

**证据：**

- `handle_device_register()` 在注册成功后调用：
  ```python
  _mesh_session = build_mesh_session(source_device_id=device_id, ...)
  _record = create_durable_session(_mesh_session, ...)
  activate_durable_session(_record.session_id)
  ```
  → **MeshSession 被自动创建并激活** ✅

- `docs/MULTI_DEVICE_RUNTIME_MATURITY.md` 明确指出 `body_mesh_registry` 的 Gap：
  > "`register()` and `unregister()` are not wired to UDM device lifecycle events — the registry must be manually populated; no automatic sync with device connect/disconnect"

- `BodyMeshRegistry.register()` 没有在 `handle_device_register()` 中被调用

- `MeshParticipationSummary` 可以通过 `_aggregate_from_mesh_membership()` 从 `BodyMeshRegistry` 读取成员信息，但如果 `BodyMeshRegistry` 为空（未手动填充），则此路径返回空

**结论：Android 注册时会自动创建 `MeshSession`（通过 `MeshSessionLifecycleCoordinator`），但 `BodyMeshRegistry` 不会被自动写入。Body Mesh 成员仍需手动管理，设备节点无法自动进入 Mesh 候选池。**

---

### 核定项 8：`SourceDispatchOrchestrator` 是否真实进入 Android fan-out / remote 路径

**核定结论：⚠️ 部分成立（条件触发进入生产路径；单设备 Android 直接路径不经过它）**

**证据：**

- `core/openclawd.py` 的 `_delegate_multi_device_orchestration()` 中：
  ```python
  # PR-D: Source Dispatch Orchestrator production wiring.
  # When a mesh session with 2+ active participants is available, route
  # through the canonical source dispatch orchestration layer first.
  try:
      from core.runtime.source_dispatch_orchestrator import (
          _try_mesh_session,
          orchestrate_source_runtime_dispatch,
      )
  ```
  → **`orchestrate_source_runtime_dispatch` 在有 2+ 活跃参与者的 mesh session 时触发** ✅

- `tests/test_prd_source_dispatch_orchestrator_production_wiring.py` 验证了这一调用关系

- 标准 Android 单设备任务执行路径：`OpenClawd.process()` → `_dispatch_goal_execution()` 或 `_dispatch_tool_call()` → `CommandRouter` → `DeviceRouter` → Android WebSocket。**此路径完全绕过 `SourceDispatchOrchestrator`**

- `SourceDispatchOrchestrator.consume_android_behavioral_result()` 文档注释明确：
  > "full behavioral result integration is deferred to a later PR"

**结论：`SourceDispatchOrchestrator` 已进入生产代码（通过 `_delegate_multi_device_orchestration`），但触发条件苛刻（需要 2+ mesh 参与者）。常规 Android 单设备路径不经过它。它目前是"有条件生产接入"而非"主路径必经组件"。**

---

## 三、SSOT 真实读路径图

### 3.1 写路径（已确认，#715 已清晰）

```
Android WebSocket 注册
  └─► handle_device_register()
        └─► bridge._write_registration_to_udm()     → UDM ✅ SSOT

REST 注册 POST /api/v1/devices/register
  └─► get_unified_device_manager().register_device_from_dict()  → UDM ✅ SSOT

DeviceRegistry.register() / DeviceRouter.register_device()
  └─► 先写 UDM，成功后更新本地缓存                  → UDM ✅ SSOT

DeviceAgentManager.register_device()
  └─► _unified().register_device()                  → UDM ✅ SSOT

UCM：连接/可路由状态
  └─► 写 UCM（WebSocket 注册、连接建立）             → UCM ✅ SSOT
```

### 3.2 读路径（本次新增核查）

#### 已真实读 UDM 的路径 ✅

| 路径 | 模块 | 读取内容 |
|------|------|---------|
| `GET /api/v1/devices` | `core/routes/devices.py` | UDM 优先，`registered_devices` 补充遗留 |
| `GET /api/v1/devices/{id}` | `core/routes/devices.py` | UDM 优先读取 |
| `GET /api/v1/devices/{id}/telemetry` | `core/routes/devices.py` | UDM 先检查存在性 |
| `GET /api/v1/devices/discover` | `core/routes/devices.py` | UDM `list_devices()` |
| `device_readiness.get_device_readiness_summary()` | `core/device_readiness.py` | UDM + UCM 双读 |
| `truth_integration_layer` | `core/truth_integration_layer.py` | 读 UDM + UCM + compat_cache |
| heartbeat/delete 检查 | `core/routes/devices.py` | UDM 存在性检查 |

#### 已真实读 UCM 的路径 ✅

| 路径 | 模块 | 读取内容 |
|------|------|---------|
| `device_readiness.get_connection_summary()` | `core/device_readiness.py` | UCM 连接状态、可路由性 |
| `connection_manager.send_to_device()` | `core/routes/_shared.py` | UCM 委托发送 |
| 设备在线判断 | `core/routes/devices.py` | `connection_manager.active_devices` |

#### 仍读局部缓存/兼容层的路径 ⚠️

| 路径 | 模块 | 读取来源 | 说明 |
|------|------|---------|------|
| DeviceRouter 本地路由 | `galaxy_gateway/device_router.py` | `self.devices`（本地 dict）| DeviceRouter 的本地 session 缓存，不是 UDM |
| AndroidBridge 设备查找 | `galaxy_gateway/android_bridge.py` | `self._devices`（本地 dict）| 传输层 session 缓存 |
| registered_devices 兜底 | `core/routes/devices.py` | `registered_devices` dict | 遗留兼容缓存 |
| Node_71 设备注册 | `nodes/Node_71_MultiDeviceCoordination/` | 本地协调注册表 | 明确标注 deprecated，不写 UDM |

#### 尚未完成"以 SSOT 为中心"的决策路径 ❌

| 决策路径 | 问题 |
|---------|------|
| CapabilityAssimilation 查询（能力路由） | Android 注册后不自动写入 CapabilityAssimilationLayer，无法通过 `query_routable_executors()` 发现 Android 设备 |
| BodyMeshRegistry 成员池 | 不自动同步 UDM/UCM 设备生命周期事件，mesh 候选池需手动维护 |
| SourceDispatchOrchestrator 目标选择 | 目前仅当 mesh session 有 2+ 参与者时才读取 mesh context；单设备路径不读 SSOT |
| MeshSession 参与者集合 | 从 BodyMeshRegistry 派生，而 BodyMeshRegistry 未自动同步 |
| DeviceRoleAllocator | 不读取 UDM 能力数据进行智能分配 |

### 3.3 当前 SSOT 地位判断

> **结论：系统当前处于"SSOT 已建立但尚未成为统一决策源"与"SSOT 已进入大多数关键决策路径"之间的过渡态，偏向前者。**
>
> - **写路径**：UDM/UCM SSOT 已基本统一，所有主注册链均写 SSOT ✅
> - **读路径**：API 层、可达性判断、遥测层已读 SSOT；但能力路由、Mesh 参与者池、调度目标选择尚未以 SSOT 为统一决策源 ⚠️
> - **核心阻塞**：CapabilityAssimilationLayer 未被自动写入（Gap CROSS-004）是最影响能力路由决策质量的单点缺口

---

## 四、节点 Authority 模型现实图

### 4.1 Authority 分类体系

以下对每类 Authority 基于代码判断当前持有者：

#### 1. Execution Authority（执行权）

| 持有者 | 范围 | 代码证据 |
|--------|------|---------|
| **V2 中心** | 完整执行权 | `OpenClawd._run_execution()`，`DesktopPresenceRuntime`，`AgentKernel` |
| **设备节点** | 本地执行权（有限）| Android 设备执行 `task_assign` 中的 tool，`goal_execution` 中的本地步骤 |
| **设备节点** | 无全局执行权 | 设备不能自主发起新的全局任务流 |

> **判断：设备节点拥有受限本地执行权，不拥有全局执行决策权。**

#### 2. Initiation Authority（发起权）

| 持有者 | 范围 | 代码证据 |
|--------|------|---------|
| **V2 中心** | 完整发起权 | `OpenClawd.process()` 是所有任务的主入口 |
| **设备节点** | 可发起 `goal_execution` | Android → V2 的 `goal_execution` 消息，V2 处理后下发 task_assign |
| **设备节点** | 无直接 orchestration 发起权 | `goal_execution` 最终仍由 V2 处理和决策，Android 不能直接调度其他设备 |

> **判断：设备节点拥有受限发起权（可发起目标请求），但实际 orchestration 决策仍在 V2 中心。**

#### 3. Routing Authority（路由权）

| 持有者 | 范围 | 代码证据 |
|--------|------|---------|
| **V2 中心** | 完整路由权 | `CommandRouter`，`DeviceRouter`，`SourceDispatchOrchestrator` |
| **设备节点** | 无路由权 | Android 无法路由任务到其他设备 |
| **gateway layer** | 网关路由 | `RoutingOrchestrator`，`galaxy_gateway/routing/router.py` |

> **判断：路由权完全在 V2 中心。设备节点是路由目标，不是路由决策者。**

#### 4. Session Authority（会话权）

| 持有者 | 范围 | 代码证据 |
|--------|------|---------|
| **V2 中心** | 会话创建/管理权 | `AttachedRuntimeSessionRuntime`，`MeshSessionLifecycleCoordinator` |
| **设备节点** | 无会话创建权 | 注册 ACK 中的 session_id 由 V2 随机生成，Android 无法主动创建 session |
| **设备节点** | 有限会话参与权 | Android 可以"参与"一个 V2 创建的 session（通过 `join_runtime` posture）|

> **判断：会话权在 V2 中心。设备节点是会话参与者，不是会话发起者。**

#### 5. Operator Authority（操纵权）

| 持有者 | 范围 | 代码证据 |
|--------|------|---------|
| **V2 中心** | 完整操纵权 | 任务发起、停止、重试、优先级调整均在 V2 |
| **设备节点** | 无操纵权 | Android 无法操纵其他设备的任务 |
| **定义层面** | 部分合同存在 | `coordination_role` 字段在 `HandoffEnvelopeV2` 中定义了 `source_controller` 等角色，但未行为化 |

> **判断：操纵权完全在 V2 中心。合同层定义了设备可能的 operator 角色，但未行为化。**

#### 6. Mesh / Coordination Authority（Mesh 协调权）

| 持有者 | 范围 | 代码证据 |
|--------|------|---------|
| **V2 中心** | 完整 mesh 协调权 | `SourceDispatchOrchestrator`（条件触发），`SwarmCoordinator`，`MeshSessionLifecycleCoordinator` |
| **设备节点** | 无 mesh 协调权 | 设备不能发起或控制 mesh session |
| **设备节点** | 有限被动参与 | 可以成为 `MeshSession.participants`（通过 `join_runtime` posture），但无法驱动 mesh 状态机 |

> **判断：Mesh 协调权完全在 V2 中心。设备节点是 mesh 的被动成员候选，不是 mesh 的主动协调者。**

#### 7. Policy / Governance Authority（策略/治理权）

| 持有者 | 范围 | 代码证据 |
|--------|------|---------|
| **V2 中心** | 完整策略权 | `NodeInvocationGovernance`，`NodeGovernanceRuntime`，`GovernancePolicy` |
| **设备节点** | 无策略权 | Android 无 governance 路径 |
| **合同层** | 部分定义 | `core/authority_boundary_classification.py` 定义了各层的 authority，设备层无 governance 权 |

> **判断：策略/治理权完全在 V2 中心。设备无任何 governance 参与。**

### 4.2 节点 Authority 综合评级

| Authority 类型 | V2 中心持有 | 设备节点持有 | 设备节点部分持有 | 仅定义未行为化 | 完全不存在 |
|--------------|-----------|------------|--------------|------------|---------|
| Execution | ✅ 完整 | ✅（受限本地）| — | — | — |
| Initiation | ✅ 完整 | — | ✅（目标请求）| — | — |
| Routing | ✅ 完整 | — | — | — | ❌ 设备侧 |
| Session | ✅ 完整 | — | ✅（参与权）| — | — |
| Operator | ✅ 完整 | — | — | ✅（合同层有定义）| — |
| Mesh/Coordination | ✅ 完整 | — | ✅（被动成员）| — | — |
| Policy/Governance | ✅ 完整 | — | — | — | ❌ 设备侧 |

### 4.3 设备节点 Authority 最终定性

> **当前设备节点是：有受限本地执行权 + 受限发起权（目标请求）的"远端执行终端"。**
>
> 它不是"具备部分自主权的协作节点"，更不是"全网操纵入口"。
>
> 它未来可以升级为"更完整的协作节点"，但需要：
> - Routing Authority 下放（让设备可以路由任务给其他设备）
> - Session Authority 下放（让设备可以发起 session）
> - Mesh Authority 行为化（让设备成为真正的 mesh 协调参与者，而非仅被动成员）

---

## 五、"任意设备操纵全网"能力分解表

> **定义："任意设备操纵全网"** = 网络中的任意设备节点可以作为入口，发起、调度、控制、协调整个分布式智能体网络中的任意操作。

| # | 能力条件 | 当前状态 | 完成度 | 核心证据 |
|---|---------|---------|--------|---------|
| 1 | 设备节点可发起新的全局操作请求 | ⚠️ 部分 | 30% | Android 可发 `goal_execution`，但 V2 中心仍是决策者；Android 无法直接调度其他设备 |
| 2 | 设备节点可附着到统一 runtime / session | ⚠️ 部分 | 40% | `attach_runtime_session()` V2 侧已建立；`join_runtime` posture 已合同化；但双边 session_id 传递未闭环 |
| 3 | 设备节点具备 continuity / reconnect 恢复能力 | ⚠️ 部分 | 35% | V2 侧 session 在重连时恢复（`reconnect_session()`）；`DispatchContinuityContext` 合同完整；但 Android 侧无 continuity 消费者 |
| 4 | 设备节点可以读取或通过中心间接读取网络真值 | ❌ 不成立 | 5% | Android 仅能读取 V2 下发的任务结果；无查询 UDM/UCM/网络拓扑的接口 |
| 5 | 设备节点可以触发跨设备 dispatch / orchestration | ❌ 不成立 | 5% | Android 发起的 `goal_execution` 由 V2 中心处理；Android 无法直接触发跨设备 dispatch |
| 6 | 设备节点可以成为 mesh participant / candidate | ⚠️ 部分 | 25% | `MeshSession` 创建机制存在（注册时自动创建）；`join_runtime` posture 机制存在；但 `BodyMeshRegistry` 不自动写入；mesh 候选池未自动更新 |
| 7 | 设备节点的 handoff / takeover 语义可闭环 | ⚠️ 部分 | 20% | `HandoffEnvelopeV2` 合同完整；V2 侧 `target_takeover.py` 存在（PR-34）；Android 以 `task_assign` 语义近似消费；完整 Android 侧 handoff 闭环未验证 |
| 8 | 设备节点有足够的 identity / policy / routing authority | ❌ 不成立 | 5% | 设备节点无 routing authority；无 policy authority；identity 在 V2 侧管理（UDM），设备侧无自持 |
| 9 | 多平台节点在合同层上可统一纳入 | ✅ 部分成立 | 50% | `RegisteredRuntimeDevice`、`HandoffEnvelopeV2`、`SourcePostureContract` 等合同层支持多平台；但运行层仅 Android 真实接入 |

### 5.1 能力综合完成度评估

**综合完成度：约 18%（比 PR #715 的 10–15% 略高）**

提升原因：
- 确认了 `source_runtime_posture` 在 Android 注册时真实上报（+贡献条件 2/3）
- 确认了 `goal_execution_result` 真实存在（+贡献条件 1）
- 确认了 `SourceDispatchOrchestrator` 有条件进入生产路径（+贡献条件 5）

### 5.2 当前最核心的阻塞点

1. **Android 缺乏 Routing Authority** — 设备无法路由任务给其他设备，"任意设备操纵全网"的"操纵"语义无法成立
2. **CapabilityAssimilationLayer 未自动写入** — Android 设备不在能力路由平面，无法被其他设备的 capability-based routing 发现
3. **BodyMeshRegistry 不自动填充** — mesh 候选池需手动维护，自动多设备协同不可达
4. **DispatchContinuityContext 无消费者** — 断线重连后 dispatch 上下文无法恢复关联，continuity 语义名存实亡
5. **runtime_attachment_session_id 单边运行** — Android 侧不保存/回传 session ID，跨 V2 和 Android 的会话关联无法闭环

---

## 六、Mesh / Multi-Device 五层分解表

| 层级 | 内容 | 当前状态 | 代码证据 |
|------|------|---------|---------|
| **Layer 1：合同族（contract family）** | `MeshSession`、`MeshMembership`、`MeshSessionCoordinator`、`MeshSubtaskAssignment`、`DispatchContinuityContext`、`HandoffEnvelopeV2`、`RegisteredRuntimeDevice` | ✅ **基本完整** | `contracts/` 目录下多个合同模块，结构完备 |
| **Layer 2：注册/持久化层（registry / persistence surface）** | `BodyMeshRegistry`、`MeshSessionLifecycleCoordinator`、`AttachedRuntimeSessionRuntime`、`MeshSessionPersistenceStore` | ⚠️ **部分存在** | 注册表存在但不自动填充；持久化层合同化（`docs/DURABLE_RUNTIME_SESSION_SNAPSHOT.md`）但实现未验证 |
| **Layer 3：运行引擎（runtime engine）** | `MeshSession` 状态机、Barrier 协调引擎、动态角色再分配引擎、`CrossRuntimeResultMerge` 引擎 | ❌ **基本不存在** | `MULTI_DEVICE_RUNTIME_MATURITY.md` 明确：`MeshSession` 状态转换无 engine，Barrier 协调无 engine，结果合并合同存在但 engine 不存在 |
| **Layer 4：dispatch authority 接入** | `SourceDispatchOrchestrator` 作为 dispatch 决策者，能力路由读 Mesh 候选池，formation_resolver 动态更新 | ⚠️ **有限接入** | `SourceDispatchOrchestrator` 条件触发（2+ mesh 参与者）；`formation_resolver` 静态派生（每次 dispatch 重算）；`CapabilityAssimilationLayer` 未写入 Android 设备 |
| **Layer 5："任意设备操纵全网"的协作底盘** | 任意设备可成为 orchestration 入口；设备具备 routing/session authority；跨设备 continuity 完整闭环 | ❌ **完全不成立** | 见能力分解表第 5 节，设备无 routing authority，continuity 单边，Mesh engine 缺失 |

### 6.1 五层详细评估

#### Layer 1：合同族（✅ 基本完整）
- 已存在且质量高：`MeshSession`、`MeshMembership`、`HandoffEnvelopeV2`、`DispatchContinuityContext`、`RegisteredRuntimeDevice`、`SourcePostureContract`
- 合同层已为多平台统一预留字段（`coordination_role`、`source_runtime_posture`、`runtime_attachment_session_id` 等）
- 唯一缺口：`MeshBarrierPosture` 和 `MeshMergePolicy` 的语义在合同中已定义但部分字段未有生产消费者

#### Layer 2：注册/持久化层（⚠️ 部分存在）
- `BodyMeshRegistry`：✅ 运行时存在，⚠️ 不自动同步 UDM 生命周期
- `MeshSessionLifecycleCoordinator`：✅ 注册触发自动创建 session，✅ 重连时恢复 session
- `AttachedRuntimeSessionRuntime`：✅ 单边（V2）真实运行，⚠️ Android 侧未双边对齐
- `MeshSessionPersistenceStore`：✅ 合同化（`core/mesh/mesh_session_persistence.py`），⚠️ 跨进程重启持久化未验证

#### Layer 3：运行引擎（❌ 基本不存在）
- `MeshSession` 状态机（`FORMING → ACTIVE → COMPLETING → DONE`）：❌ 无 engine 驱动状态转换
- Barrier 协调引擎：❌ 不存在
- 动态角色再分配：❌ 不存在（`formation_resolver` 仅静态派生，不动态重平衡）
- `CrossRuntimeResultMerge` 引擎：❌ 合同存在但无 engine

#### Layer 4：dispatch authority 接入（⚠️ 有限接入）
- `SourceDispatchOrchestrator` 条件进入生产路径 ✅（限 2+ mesh 参与者时）
- `formation_resolver` 在 `DeviceRouter._dispatch_cross_device_task()` 中调用 ✅
- `CapabilityAssimilationLayer` 未被 Android 注册写入 ❌ → 能力路由决策基础数据缺失
- 结论：dispatch authority 部分接入，但依赖 Mesh 层和 Capability 层的数据质量

#### Layer 5：协作底盘（❌ 完全不成立）
- 设备无 routing authority ❌
- 设备无 session 发起权 ❌
- Continuity 单边运行 ❌
- Mesh engine 缺失 ❌
- **总评：当前 Mesh/Multi-Device 只到了 Layer 2 的部分，距离 Layer 5 还差 3 个完整层级**

---

## 七、结论修正版

### 7.1 系统总体判断（对比 PR #715）

| 维度 | PR #715 判断 | 本次修正判断 |
|------|------------|------------|
| SSOT 建立状态 | 已建立，UDM/UCM 是权威 | ✅ 确认，写路径基本统一 |
| SSOT 读路径 | "较清晰" | ⚠️ API/可达性层已读 SSOT；能力路由/Mesh 候选池尚未以 SSOT 为统一决策源 |
| CapabilityAssimilation | ❓ 未确认 | ❌ Android 注册链未触发（Gap CROSS-004 未修复）|
| HandoffEnvelopeV2 on Android | ❓ 未确认 | ❌ Android 不原生消费，以 task_assign 近似 |
| goal_result | ❓ 未确认 | ✅ 以 `GOAL_EXECUTION_RESULT` 真实存在，与 task_result 并行共存 |
| runtime_attachment_session_id | ❓ 未确认 | ⚠️ V2 单边真实运行，Android 侧未双边对齐 |
| source_runtime_posture | ❓ 未确认 | ✅ Android 已上报，V2 正确读取 |
| DispatchContinuityContext | ❓ 未确认 | ❌ 合同完整，重连路径无消费者 |
| MeshMembership/BodyMeshRegistry | ❓ 未确认 | ⚠️ MeshSession 自动创建，BodyMeshRegistry 不自动填充 |
| SourceDispatchOrchestrator | ❓ 未确认 | ⚠️ 条件触发进入生产，单设备路径绕过 |
| "任意设备操纵全网"能力 | 10–15% | 18%（边际提升）|
| 节点 Authority | 未拆分 | 设备节点是"有受限执行权+受限发起权的远端执行终端" |

### 7.2 系统级最终认知（升级版）

> **我们已经明确知道：**
>
> **哪些设备事实进入了真实决策链：**
> - 设备注册事实（UDM/UCM）已进入 API 层、可达性判断、遥测层的决策链 ✅
> - 设备能力事实（CapabilityAssimilationLayer）**尚未**进入 Android 设备的能力路由决策链 ❌
> - 设备 Mesh 成员事实（BodyMeshRegistry）**尚未**自动进入 Mesh 候选池 ⚠️
>
> **节点今天到底拥有什么 authority：**
> - 受限本地执行权（可执行 V2 下发的任务）
> - 受限发起权（可发起目标请求，但 V2 中心仍是最终决策者）
> - 被动 session 参与权（可附着到 V2 创建的 session，需 join_runtime posture）
> - **无** routing authority、operator authority、governance authority
>
> **系统距离"任意设备操纵全网的中心协调式分布智能体网络"还差哪几步：**
> 1. **CapabilityAssimilationLayer 自动写入**（Android 注册 → 能力路由平面，Gap CROSS-004）
> 2. **BodyMeshRegistry 自动同步**（设备注册 → Mesh 候选池自动更新）
> 3. **DispatchContinuityContext 重连消费者**（断线重连后 dispatch 上下文恢复关联）
> 4. **Mesh 运行引擎**（MeshSession 状态机、Barrier 协调、结果合并）
> 5. **设备节点 Routing Authority 下放**（让设备可以路由任务给其他设备）
> 6. **runtime_attachment_session_id 双边传递**（Android 保存并回传 session_id）

---

## 八、补强后的系统级 PR 规划

以下按优先级排列，基于本次补强审查的缺口定位：

### P0：能力路由基础 Gap 修复

**PR-D4-FIX：Android 注册链接入 CapabilityAssimilationLayer**
- 目标：修复 Gap CROSS-004
- 工作：在 `handle_device_register()` 或 `_write_registration_to_udm()` 之后，调用 `assimilate_device(device_id, capabilities=caps_list, ...)`
- 验证：注册后 `query_routable_executors()` 可发现 Android 设备
- 影响：解锁 capability-based routing 对 Android 的覆盖

### P0：Mesh 候选池自动化

**PR-MESH-AUTO-SYNC：BodyMeshRegistry 自动同步 UDM 生命周期事件**
- 目标：设备注册/断线时自动写入/移除 BodyMeshRegistry
- 工作：在 UDM write-through 路径或 android_bridge 注册后调用 `get_body_mesh_registry().register(device_id, ...)`
- 影响：解锁 Mesh 候选池自动化，让 `SourceDispatchOrchestrator` 有真实的候选池可选

### P1：Continuity 重连消费者

**PR-CONTINUITY-RECONNECT：DispatchContinuityContext 在重连路径中重关联**
- 目标：断线重连时恢复 dispatch 上下文
- 工作：在 `reconnect_device()` 中查询并携带 `DispatchContinuityContext`，写入恢复的 session record
- 影响：真正实现断线 continuity 语义

### P1：runtime_attachment_session_id 双边对齐

**PR-SESSION-BILATERAL：注册 ACK 携带 runtime_attachment_session_id**
- 目标：Android 收到并保存 V2 生成的 runtime_attachment_session_id
- 工作：在 `device_register_ack` 中包含 `runtime_attachment_session_id`；Android 客户端在后续消息中回传
- 影响：实现 session 双边关联闭环

### P2：Mesh 运行引擎（阶段一）

**PR-MESH-ENGINE-V1：MeshSession 状态机最小 MVP**
- 目标：驱动 `FORMING → ACTIVE → COMPLETING → DONE` 状态转换
- 工作：创建 `MeshSessionEngine`，订阅 device lifecycle 事件驱动状态机
- 影响：Layer 3 从"不存在"升级到"最小可用"

### P3：设备节点发起权扩展

**PR-DEVICE-INITIATION：Android 设备直接触发跨设备 dispatch**
- 目标：让 Android 的 `goal_execution` 可以携带目标设备列表，V2 据此 fan-out
- 工作：扩展 `handle_goal_execution()` 以支持 multi-device target dispatch
- 影响：设备节点 Initiation Authority 从"受限"升级到"受监管的完整发起权"

### P3：HandoffEnvelopeV2 Android Wire Protocol 下推

**PR-HANDOFF-ANDROID-WIRE：HandoffEnvelopeV2 → Android JSON 协议适配**
- 目标：Android 可以直接解析/消费 HandoffEnvelopeV2 的 JSON 表示
- 工作：在 Android 协议文档中定义 HandoffEnvelopeV2 wire 格式；V2 使用 `HandoffEnvelopeV2.model_dump()` 替代 `task_assign` 下发
- 影响：handoff 语义从"task_assign 近似"升级到"语义完整的 handoff"

---

## 九、可直接复制续聊版摘要（补强版）

```
=== Galaxy 设备控制面补强审查 V2 — 系统级最终认知 ===

一、SSOT 状态
- UDM（UnifiedDeviceManager）：设备状态 SSOT ✅ 写路径基本统一
- UCM（UnifiedConnectionManager）：连接/可路由 Authority ✅
- 读路径：API层/可达性/遥测已读 SSOT ✅；能力路由/Mesh候选池尚未以SSOT为统一决策源 ⚠️
- 总判断：过渡态，偏向"SSOT已建立但尚未成为统一决策源"

二、8个未确认项核定结果
1. CapabilityAssimilation in Android 注册链：❌ 未触发（Gap CROSS-004 未修复）
2. Android 原生消费 HandoffEnvelopeV2：❌ 不成立（以 task_assign 语义近似消费）
3. goal_result 真实存在：✅ 以 GOAL_EXECUTION_RESULT 存在，与 task_result 并行
4. runtime_attachment_session_id 双边传递：⚠️ V2 单边真实，Android 侧未对齐
5. Android 上报 source_runtime_posture：✅ 已成立，V2 正确读取
6. DispatchContinuityContext 重连重关联：❌ 合同存在，重连路径无消费者
7. MeshMembership/BodyMeshRegistry 自动写入：⚠️ MeshSession 自动创建，BodyMeshRegistry 不自动填充
8. SourceDispatchOrchestrator 进入生产路径：⚠️ 条件触发（2+参与者），单设备路径绕过

三、节点 Authority 最终定性
- 设备节点是："有受限本地执行权 + 受限发起权（目标请求）的远端执行终端"
- 拥有：受限执行权，受限发起权，被动 session 参与权
- 无：routing authority，operator authority，governance authority，mesh协调权

四、"任意设备操纵全网"综合完成度：约 18%
- 最核心阻塞：CapabilityAssimilation 未自动写入、BodyMeshRegistry 不自动填充、
  DispatchContinuityContext 无消费者、Mesh 运行引擎不存在、设备无 routing authority

五、Mesh/Multi-Device 五层分解
- Layer 1（合同族）：✅ 基本完整
- Layer 2（注册/持久化）：⚠️ 部分存在（不自动同步）
- Layer 3（运行引擎）：❌ 基本不存在
- Layer 4（dispatch authority 接入）：⚠️ 有限接入（条件触发）
- Layer 5（任意设备操纵全网底盘）：❌ 完全不成立
- 当前只到了 Layer 2 的部分

六、最高优先级 PR（P0）
1. Android 注册链接入 CapabilityAssimilationLayer（Gap CROSS-004）
2. BodyMeshRegistry 自动同步 UDM 生命周期事件

=== 以上内容可直接回灌续聊，无需重复解释 ===
```

---

*文档生成时间：2026-04-19*
*审查基于：galaxy_gateway/、core/、contracts/、docs/、tests/ 目录下全部相关模块*
*本文档不替代 PR #715，而是在其基础上补强所有 ❓/⚠️ 未确认项*
