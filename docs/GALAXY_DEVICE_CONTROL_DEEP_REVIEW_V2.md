# Galaxy 设备控制面深度系统审查补强报告 V2

> **基于 PR #715 的系统认知升级**
> 版本：V2 补强版 | 状态：代码事实已核定
> 可直接复制粘贴长期回灌

---

## 一、补强审查现实摘要

本次审查在 PR #715 母版基础上，对八个关键未确认项逐条基于真实代码核定，并系统补充了「谁在真实读取 SSOT 做决策」、「节点 Authority 模型」、「任意设备操纵全网能力分解」以及「Mesh 五层分解」四个核心维度。

**最核心结论升级**：

- PR #715 结论"设备控制面骨架已成"——**保持正确**
- 更精确的系统级判断为：
  > **UDM/UCM 写入层已成为 SSOT，但 SSOT 尚未成为统一决策源。系统处于"写入已收口、读取路径仍多元混合"的过渡态。节点今天是远端执行终端，具备向协作节点升级的合同基础，但 runtime authority 层实质上仍集中在中心。**

---

## 二、未确认项逐条核定表

### ① CapabilityAssimilationLayer.assimilate_device() 是否在 Android 注册链中被真实触发

**核定结论：已确认不成立**

- `assimilate_device()` 函数在 `core/capability_assimilation.py` 中定义完整，设计用于将设备作为 `NodeParticipantKind.DEVICE` 接入能力同化层。
- 经查三条注册路径：
  - `galaxy_gateway/android_bridge.py`：`_handle_device_register()` 调用 `UDM.register_device()` + `_sync_device_router_session()`，**不调用** `assimilate_device()`。
  - `core/routes/devices.py`（REST 路径）：调用 `get_unified_device_manager().register_device_from_dict()`，再调用 `_sync_device_to_capability_registry()`（写 CapabilityRegistry），**不调用** `assimilate_device()`。
  - `core/device_agent_manager.py`（DAM 路径）：调用 `_unified().register_device()`，**不调用** `assimilate_device()`。
- `docs/DUAL_REPO_UNRESOLVED_AUDIT.md` 明确标注："CapabilityAssimilationLayer.assimilate_device() [CROSS-004: not confirmed as automatic]"。
- 实际生产调用点仅存在于 `core/network_topology_runtime.py`（网络拓扑投影路径），**不在注册链**。
- **系统影响**：设备注册后，其能力进入了 CapabilityRegistry（通过 `_sync_device_to_capability_registry`），但**未进入** CapabilityAssimilationLayer 的能力图/任务图/网络图投影。意味着设备不会自动成为 `CapabilityGraphSelection` 的候选节点。

---

### ② Android 是否原生消费 HandoffEnvelopeV2

**核定结论：已确认不成立（仅通过 task_assign 语义近似消费）**

- `contracts/handoff_envelope_v2.py` 中 `HandoffEnvelopeV2` 合同定义完整，含 `source_runtime_posture`、`dispatch_contract_metadata`、`session_context` 等完整字段。
- `galaxy_gateway/agent_bridge.py` 在执行 handoff 时：
  - 调用 `from_legacy_handoff_contract()` 构建 `HandoffEnvelopeV2`。
  - 将其 `.to_compact_summary()` 作为 `handoff_envelope_v2` 字段附加到结果中。
  - **最终发送给 Android 的是 `task_assign` 格式消息**，不是 HandoffEnvelopeV2 原始结构。
- `galaxy_gateway/android/handlers/` 目录下的所有处理器均处理 `task_assign`、`goal_execution`、`task_result`、`parallel_subtask` 等类型，**无任何处理器直接解析 HandoffEnvelopeV2 结构**。
- Android 客户端目录（`android_client/`）中无任何 HandoffEnvelopeV2 引用。
- **系统影响**：handoff 的语义在网关侧被降维为 task_assign，Android 无法区分普通任务分发与正式 handoff，`dispatch_contract_metadata`、`takeover_policy`、`return_contract` 等高级合同字段对 Android 不可见。

---

### ③ goal_result 是否真实存在并与 task_result 对齐

**核定结论：部分成立（goal_execution_result 存在，但独立 goal_result 消息类型不存在）**

- `galaxy_gateway/android/handlers/goal_execution.py` 中存在 `handle_goal_execution_result()` 处理函数，处理 `goal_execution_result` 类型消息。
- 此处理器调用 `_reconcile_goal_result`（即 `core.android_execution_signal_reconciler.reconcile_inbound_message`）进行结果协调。
- 任务完成后，结果通过 `task_result` 路径（`handle_task_result()`）统一汇聚，完成 Future resolve 和 UDM 状态更新。
- **无独立的 `goal_result` 消息类型**；goal 执行完成信号通过两条路径之一回流：
  - `goal_execution_result`（高层 goal 完成，含 reconcile 调用）
  - `task_result`（底层 task 完成，是大多数现有 Android 实现实际走的路径）
- `contracts/source_dispatch.py::SourceDispatchResult` 中有 `dispatch_id`、`task_id`、`mode` 等字段，是 source side 的分发结果合同，与 Android 的 task_result 语义对齐但不等同。
- **系统影响**：goal 完成信号与 task 完成信号在 Android 侧语义重叠，导致中心侧无法区分"目标完成"与"单步任务完成"，影响 multi-step goal 的精确追踪。

---

### ④ runtime_attachment_session_id 是否在双仓之间被真实创建、传递、消费、恢复

**核定结论：部分成立（中心侧创建完整，Android 侧传递单边）**

- `core/attached_runtime_session.py` 中 `attach_runtime_session()` 函数完整实现：
  - 中心侧创建 `AttachedRuntimeSessionRecord`，含 `runtime_attachment_session_id`（若未提供则使用 `session_id`）。
  - 支持 idempotent re-attach（重连时更新而非重复创建）。
- **传递方向分析**：
  - 中心 → Android：`task_assign` 消息包含 `session_id` 和 `runtime_session_id`，Android 可消费这些字段用于关联。
  - Android → 中心：`task_result` 消息携带 `task_id`，中心通过 `task_id` 反向关联 session，但 Android 不显式发送 `runtime_attachment_session_id` 字符串。
- **恢复路径**：`android_bridge.py` 的 `_mark_reconnected()` 调用 `_patch_runtime_state_to_udm()`（更新 UDM 状态），**未调用** `attach_runtime_session()` 进行 runtime attachment 恢复。
- **系统影响**：双边真正语义上的 attachment session 只在中心侧成立；Android 侧的"session"感知通过 session_id 字段传递，但不构成完整的双向 attachment。重连后 attachment session 不会自动恢复。

---

### ⑤ Android 注册/重连时是否上报 source_runtime_posture

**核定结论：部分成立（合同已接受，Android 实际是否上报取决于 App 实现）**

- `contracts/registered_runtime_device.py::from_android_registration()` 完整支持从注册 payload 中提取 `source_runtime_posture` 字段：
  - 值为 `"join_runtime"` → `is_runtime_host=True`，解锁 runtime 附着能力
  - 值为 `"control_only"` 或未提供 → 默认 `control_only`
  - 即使未提供，若 `app_version` 存在，仍标记 `is_runtime_host=True`（因安装了 Galaxy App 即视为 runtime 主机）
- `core/android_runtime_host.py` 的分类逻辑依赖此字段
- Android App 的实际注册 payload 在 `android_client/` 中仅有 README，无实现代码可验
- **结论**：中心侧合同已完整支持该字段；生产环境是否上报取决于 Android App 实现（本仓库无法核定 Android App 侧实现）

---

### ⑥ continuity token / DispatchContinuityContext 是否在重连路径中真实重关联

**核定结论：已确认不成立（合同存在，重连路径未接入）**

- `contracts/dispatch_continuity.py::DispatchContinuityContext` 合同完整，含以下关键字段：
  - `prior_dispatch_id`、`prior_session_id`、`prior_mesh_session_id`
  - `prior_task_id`、`prior_trace_id`、`originating_device_id`
  - `resume_attempt_count`（追踪重试次数）
  - `is_resumable()` 方法
- 策略常量 `CONTINUITY_CONTEXT_SURVIVES_RECONNECT_POLICY` 明确说明此合同"设计为在重连/handoff 后继续存活"。
- **但重连路径实际执行的操作**：
  - `android_bridge.py::_mark_reconnected()` → `_patch_runtime_state_to_udm()` → 更新 UDM 的 `status=ONLINE`、`last_heartbeat`
  - **不创建** `DispatchContinuityContext`
  - **不查询** 现有 continuity context 进行恢复
  - **不调用** `attach_runtime_session()` 进行 attachment 恢复
- 重连后系统等待 Android 发新 `device_register` 或 `heartbeat`，无 continuity-aware 的智能恢复。
- **系统影响**：断线重连后无法将当前 session 与前序 dispatch 上下文关联，每次重连等同于新建 session，multi-step goal 状态无法续接。

---

### ⑦ MeshMembership / BodyMeshRegistry 是否在任何生产路径中自动或半自动写入

**核定结论：已确认不成立（读路径存在，写路径不在生产链中）**

- `core/mesh/body_mesh_registry.py::BodyMeshRegistry` 实现完整，含 `register()`、`compute_assignment()`、`get_mesh_memberships()` 等方法。
- **读路径**（生产中确认存在）：
  - `core/runtime/source_dispatch_orchestrator.py` 读取 BodyMeshRegistry 用于 mesh session 查询
  - `core/runtime/target_takeover.py` 读取 BodyMeshRegistry 用于 takeover 决策
  - `core/routes/projection.py` 读取用于 API 投影
  - `core/presence/presence_projection.py` 读取用于 presence 投影
- **写路径**（生产中无自动化）：
  - 三条设备注册路径（AndroidBridge、REST、DAM）**均不调用** `BodyMeshRegistry.register()`
  - `contracts/mesh_membership.py` 文档示例中有手动调用，仅为文档演示
  - 生产环境中 `BodyMeshRegistry.register()` 未被任何非测试、非工具代码自动触发
- **系统影响**：任何设备注册后，它不会自动成为 Mesh 成员。Mesh membership 需要显式的外部调用来建立，但当前无触发机制。

---

### ⑧ SourceDispatchOrchestrator 是否真实进入 Android fan-out / remote 路径

**核定结论：部分成立（orchestrator 已存在且部分路径接入，但 Android 主 fan-out 路径绕过它）**

- `core/runtime/source_dispatch_orchestrator.py` 实现完整（约 2700 行），含 `select_dispatch_mode()`、`select_dispatch_target()`、`build_source_dispatch_plan()`、`orchestrate_source_runtime_dispatch()` 等核心函数。
- **已接入的路径**：
  - `core/routes/projection.py`：API 层读取 `build_source_dispatch_plan()` 用于投影 dispatch 状态
  - `core/runtime/__init__.py`：re-export 为公开 API
  - `SourceDispatchOrchestrator.consume_android_behavioral_result()`：可消费 Android 执行结果并发送到 observability sink
- **主 Android fan-out 路径（绕过）**：
  - `galaxy_gateway/android_bridge.py::_fan_out_task_assign()`：直接通过 UCM 查询可用设备，发送 `task_assign` 消息，**不经过** `SourceDispatchOrchestrator`
  - `galaxy_gateway/android/handlers/goal_execution.py`：直接通过 UCM 查询 connected 设备并 fan-out
  - `core/openclawd.py::_dispatch_goal_execution()`：通过 gateway device_router 路由到设备，**不经过** orchestrator
- **系统影响**：系统存在两条并行的 Android dispatch 路径，`SourceDispatchOrchestrator` 是"应该走的规范路径"，但实际 runtime 走的是"直接 UCM + task_assign"的旁路。dispatch 决策质量（mode 选择、target 选择、continuity 感知）在生产中未被 orchestrator 保障。

---

## 三、SSOT 真实读路径图

### 已确认读 UDM 的路径

| 路径 | 读取方式 | 读取目的 |
|------|----------|----------|
| `core/device_readiness.py::get_device_readiness()` | `get_unified_device_manager()` | 设备已注册、在线状态判断 |
| `galaxy_gateway/device_router.py` | `get_unified_device_manager()` | 路由前查询设备存在性 |
| `galaxy_gateway/android_bridge.py::_patch_runtime_state_to_udm()` | `udm.upsert_device_state()` | 写回（双向：写-读结合） |
| `core/routes/devices.py` | `get_unified_device_manager()` | REST 注册、列表、状态查询 |
| `core/truth_integration_layer.py` | `get_unified_device_manager()` | canonical device truth 组装 |

### 已确认读 UCM 的路径

| 路径 | 读取方式 | 读取目的 |
|------|----------|----------|
| `core/device_readiness.py::get_connection_summary()` | `ucm.get_connection()` | 连接状态、可路由判断 |
| `galaxy_gateway/android_bridge.py::_fan_out_task_assign()` | `get_unified_connection_manager()` | fan-out 前查询 connected devices |
| `galaxy_gateway/android/handlers/goal_execution.py` | `get_unified_connection_manager()` | goal fan-out 前查询 connected devices |
| `core/routes/_shared.py::RouteConnectionPool` | `_unified()` | 连接池（UCM 门面） |

### 仍读 compat cache / local pool 的路径

| 路径 | 读取来源 | 问题 |
|------|----------|------|
| `galaxy_gateway/android_bridge.py::self._devices` | 本地 `_devices` dict | 独立于 UDM 的 transport/session cache，文档明确标注"非 SSOT" |
| `galaxy_gateway/device_router.py::self._devices` | DeviceRouter 内部设备 dict | 需通过 `_sync_device_router_session()` 与 UDM 同步，有延迟 |
| `core/routes/_shared.py::registered_devices` | compat cache | 明确标注为兼容层，应逐步废弃 |

### 读 projection / compiled truth 的路径

| 路径 | 读取来源 |
|------|----------|
| `core/routes/projection.py` | MultiDeviceRuntimeProjection、BodyMeshRegistry、FormationSummary 等多层投影合并 |
| `core/presence/presence_projection.py` | BodyMeshRegistry + TruthIntegrationLayer 投影 |
| `dashboard/backend/main.py` | BodyMeshRegistry 读取 mesh 成员用于 dashboard 展示 |

### SSOT 读路径总判断

> **系统当前是"SSOT 已建立但尚未成为统一决策源"，处于向"SSOT 已进入大多数关键决策路径"演进的过渡态。**

具体证据：
- **写入已收口**：三条注册路径（AndroidBridge / REST / DAM）均以 UDM 写入为 SSOT，失败则回滚。
- **读取仍多元**：关键 dispatch 路径（`_fan_out_task_assign`、`_dispatch_goal_execution`）读取 UCM 连接状态，但对 UDM 的设备能力/状态不做充分利用。
- **capability-based routing 缺失**：没有任何 dispatch 路径在选择设备时基于 CapabilityAssimilationLayer 的能力图做决策；fan-out 仅基于"是否 connected"。
- **mesh 读路径存在但写路径缺失**：BodyMeshRegistry 被多处读取，但没有自动写入，导致读到的始终是空或手动写入的内容。

---

## 四、节点 Authority 模型现实图

### Authority 类型定义与现实状态

| Authority 类型 | 含义 | V2 中心拥有 | 设备节点拥有 | 评注 |
|---------------|------|-------------|--------------|------|
| **Execution Authority** | 可执行具体任务/工具调用 | ✅ 完全 | ✅ 完全 | Android 设备收到 task_assign 后本地执行，具备完整执行权 |
| **Initiation Authority** | 可发起新的全局操作请求 | ✅ 完全 | ⚡ 极弱 | Android 可通过 `task_submit`/`goal_execution` 上行，但中心决定是否响应；Android 不能直接发起跨设备操作 |
| **Routing Authority** | 可决定任务发往哪个设备 | ✅ 完全 | ❌ 无 | 路由决策在 `device_router` 和 `android_bridge` 中，设备无路由能力 |
| **Session Authority** | 可创建/管理/恢复 session | ✅ 完全 | ⚡ 极弱 | 设备携带 session_id 但不能创建 AttachedRuntimeSession；中心持有 session 权威 |
| **Operator Authority** | 可发起跨设备 orchestration | ✅ 完全 | ❌ 无 | SourceDispatchOrchestrator 仅在中心；设备不能触发多设备 fan-out |
| **Mesh / Coordination Authority** | 可参与或触发 mesh formation | ✅ 合同定义 | ❌ 无 | MeshMembership 合同存在但无自动写入；设备不能自主加入 mesh |
| **Policy / Governance Authority** | 可决定 handoff/takeover 策略 | ✅ 完全 | ❌ 无 | HandoffPolicy、takeover_policy 均在中心侧定义；Android 接受指令，不参与策略制定 |

### 节点现实身份判断

> **当前设备节点是"远端执行终端"，具备向"具有部分自主权的协作节点"升级的合同基础（合同已定义），但在当前 runtime 实现中，设备节点几乎所有 authority 均不成立。**

具体说明：
- 设备节点今天可以做的：接收 task_assign → 本地执行 → 发回 task_result
- 设备节点今天不能做的：主动触发多设备协作、影响路由决策、创建/恢复 session、加入 mesh

---

## 五、"任意设备操纵全网"能力分解表

> 定义：任意设备操纵全网 = 任一网络内设备可作为操纵入口，发起和协调全网其他设备参与的智能体操作

| 能力条件 | 是否成立 | 证据 | 阻塞原因 |
|---------|---------|------|---------|
| 1. 设备节点可发起新的全局操作请求 | ⚡ 单边弱成立 | Android 可发 `goal_execution`/`task_submit`，中心接收 | 中心决定是否转发给其他设备；Android 不能直接触发跨设备操作 |
| 2. 设备节点可附着到统一 runtime / session | ⚡ 合同成立 / runtime 不完整 | `attach_runtime_session()` 存在，`AttachedRuntimeSessionRecord` 完整 | 需要 `join_runtime` posture 且中心主动调用；Android 无法自主触发附着 |
| 3. 设备节点具备 continuity / reconnect 恢复能力 | ❌ 不成立 | `DispatchContinuityContext` 合同存在 | 重连路径不调用 continuity context 恢复；每次重连等同于新建 session |
| 4. 设备节点可以读取或间接读取网络真值 | ❌ 不成立 | UDM/UCM 是中心私有单例 | 设备无任何 API 可查询其他设备的 UDM 状态或网络拓扑 |
| 5. 设备节点可以触发跨设备 dispatch / orchestration | ❌ 不成立 | `SourceDispatchOrchestrator` 仅在中心 | 设备不能主动触发 fan-out；即使发起 goal，中心决定是否分发给多设备 |
| 6. 设备节点可以成为 mesh participant / candidate | ⚡ 合同成立 / runtime 不完整 | `MeshMembership`/`BodyMeshRegistry` 合同完整 | 无自动 mesh 写入；注册成功不等于加入 mesh |
| 7. 设备节点的 handoff / takeover 语义可闭环 | ⚡ 单边成立 | `HandoffEnvelopeV2` 合同完整，center → Android 方向有实现 | Android 收到的是 task_assign 而非 HandoffEnvelopeV2；Android → Android handoff 无直接路径 |
| 8. 设备节点有足够的 identity / policy / routing authority | ❌ 不成立 | 设备有 device_id 和 capabilities，但无 routing/policy authority | 所有路由和策略决策均在中心；设备仅有执行权 |
| 9. 多平台节点（Android / Windows / 平板 / future）在合同层可统一纳入 | ✅ 合同成立 | `RegisteredRuntimeDevice`/`UnifiedDevice` 合同支持多平台 | runtime 实现仍主要针对 Android；Windows client 通过桌面 UI 接入，不走相同 device 注册链 |

**总体评估**：

- **完全成立（1 项）**：#9 多平台合同统一纳入
- **合同成立 / runtime 不完整（2 项）**：#2 runtime 附着、#6 mesh 参与
- **单边弱成立（2 项）**：#1 操作发起、#7 handoff 闭环
- **不成立（4 项）**：#3 continuity/重连、#4 读取网络真值、#5 跨设备 dispatch、#8 identity/policy authority

**当前"任意设备操纵全网"完成度：约 15-20%（合同层 ~60%，runtime 层 ~15%）**

> **核心阻塞点**：①无设备侧 dispatch authority ②无 continuity/reconnect 闭环 ③mesh 无自动写入 ④设备无法读取网络真值

---

## 六、Mesh / Multi-Device 五层分解表

| 层次 | 内容 | 当前状态 | 详细评注 |
|------|------|----------|---------|
| **L1. Contract Family 合同层** | MeshMembership、BodyMeshRegistry、MeshSession、BodyAssignment、CrossDevicePolicy、HandoffEnvelopeV2、SourceDispatchPlan 等合同是否完整 | ✅ **完整** | 合同定义全面、类型安全、有完整文档和测试。MeshMembership 支持 role/authority/routing_intent；HandoffEnvelopeV2 含 source_runtime_posture/dispatch_contract_metadata 等高级字段 |
| **L2. Registry / Persistence Surface** | BodyMeshRegistry、AttachedRuntimeSessionRuntime（ring buffer）、TruthIntegrationLayer 等 persistence 面是否存在 | ⚡ **存在但需手动写入** | BodyMeshRegistry 是内存单例，可持久化快照；AttachedRuntimeSessionRuntime 是 128 条 ring buffer；**均无自动写入机制**，需要显式 API 调用 |
| **L3. Runtime Engine** | 多设备 runtime 是否存在并能主动驱动 formation、assignment、coordination | ❌ **不存在** | `SourceDispatchOrchestrator` 存在但是 source-side 调度层，非 mesh runtime engine；无 mesh session 协调器的生产实现；`staged_mesh` dispatch path 在 `DispatchPathKind` 中定义但无对应的 runtime 执行器 |
| **L4. Dispatch Authority 接入** | Mesh formation 是否真正影响 dispatch 决策 | ❌ **未接入** | 主 fan-out 路径（`_fan_out_task_assign`）直接读 UCM connected devices，不读 BodyMeshRegistry 成员；dispatch 决策与 mesh membership 解耦 |
| **L5. 任意设备操纵全网协作底盘** | 是否已具备支撑"任意节点作为入口触发全网协作"的完整底盘 | ❌ **不具备** | 底盘缺失的核心：①设备侧无 dispatch authority ②mesh 无 runtime engine ③continuity 无重连恢复 ④设备无法读取网络真值 |

**Mesh 当前到达层次**：**L1 合同层完整 + L2 registry 存在但需手动写入**，未进入 L3 及以上。

---

## 七、结论修正版

### 从 PR #715 到 V2 的认知升级

| 维度 | PR #715 结论 | V2 补强结论 |
|------|-------------|------------|
| 设备注册 SSOT | UDM 是写入权威 | ✅ 保持正确，三条路径均收口到 UDM |
| CapabilityAssimilation | 未确认 | **已确认不成立**：注册链不触发 |
| HandoffEnvelopeV2 Android | 未确认 | **已确认不成立**：Android 收 task_assign，非 HEV2 |
| goal_result | 未确认 | **部分成立**：goal_execution_result 存在，无独立 goal_result |
| runtime_attachment_session | 未确认 | **部分成立**：中心侧完整，Android 侧单边 |
| source_runtime_posture | 未确认 | **部分成立**：合同接受，Android App 实现未可验 |
| continuity token 重连 | 未确认 | **已确认不成立**：重连路径不接入 continuity |
| MeshMembership 生产写入 | 未确认 | **已确认不成立**：无自动写入，仅有读路径 |
| SourceDispatchOrchestrator | 未确认 | **部分成立**：已存在但主 Android 路径绕过 |
| SSOT 读路径 | 未深查 | **过渡态**：写入已收口，关键 dispatch 决策路径仍多元 |
| 节点 Authority | 未展开 | **设备是远端执行终端**，无 routing/session/mesh/policy authority |
| 任意设备操纵全网 | 10-15% | **约 15-20%**（合同层 ~60%，runtime 层 ~15%） |
| Mesh 层次 | contract 完整、registry 存在、runtime 缺失 | **L1 完整，L2 手动，L3-L5 不存在** |

### 系统级最终判断

> **Galaxy 设备控制面处于"高质量 SSOT 骨架已成、但控制面权威尚未真正驱动决策层"的阶段。系统距离"任意设备操纵全网的中心协调式分布智能体网络"还差：①设备侧 dispatch authority 建立、②Mesh runtime engine 实现、③continuity/reconnect 闭环、④capability-based routing 接入 SSOT 这四个关键步骤。**

---

## 八、补强后的系统级 PR 规划

### 第一优先级：打通 SSOT → 决策链

| PR 编号 | 标题 | 核心内容 |
|---------|------|---------|
| PR-A1 | CapabilityAssimilation 接入注册链 | 在三条注册路径中调用 `assimilate_device()`，使设备成为 capability selection 候选 |
| PR-A2 | Capability-based routing 接入 dispatch | `_fan_out_task_assign` 和 `_dispatch_goal_execution` 改为读取 CapabilityAssimilationLayer 做 target 选择 |
| PR-A3 | BodyMeshRegistry 自动写入 | 设备注册/连接后自动调用 `BodyMeshRegistry.register()`，使 mesh read paths 有真实数据 |

### 第二优先级：建立 Continuity / Session 闭环

| PR 编号 | 标题 | 核心内容 |
|---------|------|---------|
| PR-B1 | Reconnect 触发 continuity context 恢复 | 在 `_mark_reconnected()` 中创建/更新 `DispatchContinuityContext` |
| PR-B2 | Android 重连后 AttachedRuntimeSession 恢复 | 在 reconnect 路径中调用 `attach_runtime_session()` 进行 re-attach |
| PR-B3 | goal_result 独立语义 | 建立独立的 goal completion 信号路径，与 task_result 区分 |

### 第三优先级：建立 Mesh Runtime Engine

| PR 编号 | 标题 | 核心内容 |
|---------|------|---------|
| PR-C1 | SourceDispatchOrchestrator 接入主 fan-out 路径 | 将 `_fan_out_task_assign` 的路由决策移入 orchestrator |
| PR-C2 | Mesh Formation Runtime | 实现 `staged_mesh` dispatch path 的 runtime executor |
| PR-C3 | Android HandoffEnvelopeV2 原生消费 | Android 侧增加对 HEV2 结构的直接解析，而非仅通过 task_assign 降维消费 |

### 第四优先级：设备侧 Authority 升级

| PR 编号 | 标题 | 核心内容 |
|---------|------|---------|
| PR-D1 | 设备发起跨设备操作 API | 建立 Android 可发起的"委托中心执行跨设备操作"的受控 API |
| PR-D2 | 网络真值只读 API | 为设备提供只读的网络拓扑/设备列表查询 API |

---

## 九、可直接复制续聊版摘要（补强版）

```
# Galaxy 设备控制面补强审查 V2 — 核心结论速查

## SSOT 现状
- UDM = 设备身份/状态写入权威（三条注册路径均收口）✅
- UCM = 连接/可路由权威（主 fan-out 路径读取）✅
- CapabilityAssimilationLayer = 能力图权威（已定义，注册链未接入）⚠️
- BodyMeshRegistry = mesh 成员 read surface（已存在，无自动写入）⚠️
- SSOT 判断：写入已收口，关键 dispatch 决策路径仍多元混合 → 过渡态

## 八大未确认项核定
1. CapabilityAssimilation 接入注册链 → ❌ 已确认不成立
2. Android 原生消费 HandoffEnvelopeV2 → ❌ 不成立（仅 task_assign 语义）
3. goal_result 独立存在 → ⚡ 部分成立（goal_execution_result 存在，无独立 goal_result）
4. runtime_attachment_session_id 双边 → ⚡ 部分成立（中心侧完整，Android 侧单边）
5. Android 上报 source_runtime_posture → ⚡ 部分成立（合同接受，App 实现未可验）
6. continuity token 重连恢复 → ❌ 已确认不成立（重连路径未接入）
7. MeshMembership 生产自动写入 → ❌ 已确认不成立（无自动写入）
8. SourceDispatchOrchestrator 进入 Android 路径 → ⚡ 部分成立（主路径绕过）

## 节点 Authority 现实
- 执行权（Execution）：✅ 设备完全拥有
- 发起权（Initiation）：⚡ 极弱（仅可上行 goal，中心决定转发）
- 路由权（Routing）：❌ 设备无
- Session 权：❌ 设备无（中心持有）
- Operator 权：❌ 设备无（SDO 仅在中心）
- Mesh/Coordination 权：❌ 设备无（合同定义但 runtime 未行为化）
- Policy/Governance 权：❌ 设备无

## 节点身份：远端执行终端（具备协作节点升级的合同基础，runtime 层尚未行为化）

## 任意设备操纵全网完成度：约 15-20%
- 合同层 ~60% ✅
- Runtime 层 ~15% ❌
- 核心阻塞：①无设备侧 dispatch authority ②无 mesh runtime engine ③无 continuity 重连 ④无网络真值读取

## Mesh 当前层次：L1（合同层）完整 + L2（registry）存在但需手动写入
- L3（runtime engine）❌ 不存在
- L4（dispatch authority 接入）❌ 未接入
- L5（任意设备操纵全网底盘）❌ 不具备

## 下一步最高优先级
1. CapabilityAssimilation 接入注册链（PR-A1）
2. BodyMeshRegistry 自动写入（PR-A3）
3. Reconnect 触发 continuity context 恢复（PR-B1）
4. SourceDispatchOrchestrator 接入主 fan-out 路径（PR-C1）
```

---

*本报告基于真实代码核定，所有结论均有具体文件路径和代码行为支撑。适合长期回灌作为系统认知基准文档。*
