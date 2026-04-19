# Galaxy 中心协调式分布智能体系统 — 设备控制面深度系统审查母版报告

> **审查范围**：`DannyFish-11/ufo-galaxy-realization-v2`（V2 中心控制面）及其与 Android 客户端（`ufo-galaxy-android`）的双仓行为闭环。  
> **审查重心**：设备控制面 / 注册 / UDM / UCM / SSOT / 节点纳管 / 编排网络准入机制 / runtime attachment / handoff-takeover / mesh-multi-device / truth-observability。  
> **输出定位**：可长期复制粘贴回灌的中文母版文本，不依赖外部截图或补充说明。  
> **生成时间**：2026-04-19

---

## 目录

1. [一、系统现实认知摘要（用人话）](#一系统现实认知摘要用人话)
2. [二、设备控制面 / 注册 / 节点纳管现实架构图](#二设备控制面--注册--节点纳管现实架构图)
3. [三、双仓系统现实架构图谱](#三双仓系统现实架构图谱)
4. [四、多链路全景图](#四多链路全景图)
5. [五、双仓行为闭环对照总表](#五双仓行为闭环对照总表)
6. [六、问题清单（P0 / P1 / P2）](#六问题清单-p0--p1--p2)
7. [七、已有成熟度 / 完成度总表](#七已有成熟度--完成度总表)
8. [八、总体完成度判断](#八总体完成度判断)
9. [九、系统级总 PR 规划（增强版）](#九系统级总-pr-规划增强版)
10. [十、可直接复制续聊版摘要](#十可直接复制续聊版摘要)

---

## 一、系统现实认知摘要（用人话）

### 这套系统真实已经成了什么

Galaxy V2 是一个**架构意图极为完整、设备控制面骨架已定型、但多个关键行为闭环尚未完成**的分布式智能体控制系统。

**已真正成立的层：**

- **单机 AI 助手核心**已完成：OpenClawd 主 runtime、多模态入口、LLM 路由、工具链、命令路由、任务图、结果输出链路均可工作。
- **设备 SSOT 权威层已定型**：`UnifiedDeviceManager`（UDM）是设备状态的唯一权威写入点，`UnifiedConnectionManager`（UCM）是连接/可路由状态的权威层，`galaxy_gateway.ssot` 提供写透 helper。`DeviceRegistry`、`device_pool_manager`、`registered_devices` compat cache 均已明确被降级为兼容层 / 投影层。
- **Android 任务下发链路已接通**：`device_register → heartbeat → task_assign → task_result` 核心 AIP v3 协议已形成真实双边闭环，WebSocket 连接管理、NATS 适配器、AndroidBridge 均可运作。
- **合同体系极为完整**：从 `HandoffEnvelopeV2`、`MeshMembership`、`MeshSession`、`LocalTakeoverResult`、`SourceDispatchPlan`、`MeshSessionCoordinatorState`，到 `AttachedRuntimeSessionRecord`、`DispatchContinuityContext`，合同定义齐全、字段丰富、版本稳定。
- **真值 / 投影 / 可观测层已建立**：`runtime_truth_compiler`、`projection_compiler`、`DesktopStatusBoardIntegrationPayload`、`AuditEventSemantics`、`ReplayFoundation` 构成了可依赖的真值输出链。

**尚未成立 / 存在关键闭环缺口的层：**

- **Attached Runtime Session 未进入注册链**：设备注册成功后，`attach_runtime_session()` **不会被自动触发**。设备从"已注册"到"已附着的运行时协作节点"之间缺失生产调用。
- **Capability Assimilation 未在注册路径确认接通**：Android 发送 `device_capabilities` 后，是否调用了 `CapabilityAssimilationLayer.assimilate_device()` 尚未在生产路径中可靠确认。
- **MeshSession / MeshSessionCoordinator 无运行时驱动引擎**：合同定义完整，但没有持续更新 participant 状态、驱动 barrier 同步、触发 merge 的活跃运行时类。
- **Handoff / Takeover 双向协议未闭环**：`HandoffEnvelopeV2` 是中心侧向 Android 推送的结构，但 Android 侧实际消费路径（以 `HandoffEnvelopeV2` 格式接收并执行本地 takeover）尚未在双仓中原生对接。`execute_local_takeover()` 在 V2 侧存在但无 Android 侧的对称实现被证实。
- **Continuity / recovery token 双边循环未闭合**：`DispatchContinuityContext` 在 V2 侧定义并使用，但是否能在 Android 重连时被重新提交、重关联、恢复执行未形成验证。
- **Multi-device 编排仅在测试/部分接通阶段**：`staged_mesh` 路由模式逻辑已写，但依赖 mesh session 有 2+ 活跃参与者，而 mesh session 在生产路径中通常为空（无 formation → 无 mesh session → 无 staged_mesh 路由）。
- **任意设备操纵全网入口能力未成立**：当前每个节点是"可以连接、可以收发任务"，但不具备"发起跨设备协作 / 接管全网节点 / 获得完整 routing authority"的真实能力。

### 最强链路

`设备注册 → UDM SSOT → task_assign → Android 执行 → task_result 回送 → 结果归档` 这条核心链路是整个系统最成熟、最可靠的生产链路。

### 最薄弱闭环

`设备注册 → attached runtime session 创建 → mesh participant 进入 → 多设备联排 → handoff / takeover → continuity 恢复` 这条"设备变节点变协作者"的链路各环节均存在未行为化的定义层缺口。

### 设备控制面在整个系统中的真实地位

设备控制面（UDM + UCM + DeviceRegistry + CapabilityBus）是**已完成骨架建设但尚未成为运行时编排的真实驱动源**。UDM 是已被确认的 SSOT 写入点，但后续 runtime attachment、mesh 进入、capability-based routing 是否真正读取 UDM 作为决策基础，存在散点漂移风险。

---

## 二、设备控制面 / 注册 / 节点纳管现实架构图

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         设备控制面权威层（SSOT 层）                               │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │  UnifiedDeviceManager（UDM）                                             │   │
│  │  core/unified/device_manager.py                                         │   │
│  │  ── 角色：设备状态唯一权威写入点（SSOT）                                  │   │
│  │  ── 职责：register / unregister / upsert_device_state / heartbeat       │   │
│  │  ── 写入触发 CapabilityBus（自动传播能力）                                │   │
│  │  ── 下游兼容层不得再充当独立事实源                                         │   │
│  └────────────────────────────────┬────────────────────────────────────────┘   │
│                                   │ write-through                               │
│  ┌────────────────────────────────▼────────────────────────────────────────┐   │
│  │  UnifiedConnectionManager（UCM）                                         │   │
│  │  core/unified/connection_manager.py                                      │   │
│  │  ── 角色：连接 / 可路由状态权威层（非设备真值，只管连接句柄）              │   │
│  │  ── 与 UDM 配合：UDM = 设备真值；UCM = 连接真值                          │   │
│  └────────────────────────────────┬────────────────────────────────────────┘   │
│                                   │ write adapter                               │
│  ┌────────────────────────────────▼────────────────────────────────────────┐   │
│  │  galaxy_gateway.ssot                                                    │   │
│  │  galaxy_gateway/ssot.py                                                 │   │
│  │  ── 角色：Gateway 侧向 UDM 的写透 helper                                │   │
│  │  ── 提供：udm_write_register / udm_write_heartbeat / udm_write_upsert  │   │
│  │  ── 明确声明只是写适配器，不是真值权威                                    │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────┐
│                         设备注册入口层                                           │
│                                                                                 │
│  REST 入口：POST /api/v1/devices/register                                       │
│    └→ core/routes/devices.py → get_unified_device_manager().register_device_from_dict()  │
│         └→ 镜像写入 registered_devices compat cache（COMPAT_MIRROR_WRITE）      │
│                                                                                 │
│  WebSocket 入口（Android）：/ws/device/{device_id}                              │
│    └→ galaxy_gateway/websocket_handler.py → AIP v3 parse                       │
│         └→ galaxy_gateway/android/handlers/registration.py                     │
│              └→ galaxy_gateway.ssot.udm_write_register()                       │
│                   └→ UDM SSOT 写入                                              │
│                   └→ UCM 连接状态更新                                           │
│                   └→ CapabilityBus（能力传播，条件性，见 P1-003）               │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────┐
│                         兼容 / 索引 / 投影层（非 SSOT）                          │
│                                                                                 │
│  DeviceRegistry（core/device_registry.py）                                      │
│  ── 角色：兼容 / 索引 / 发现层（PR-4 明确定义）                                 │
│  ── 注册时代理写入 UDM first，本地索引为 snapshot / projection cache            │
│  ── disk persistence 仅保存 OFFLINE 状态设备，不代表当前 online 权威           │
│                                                                                 │
│  DevicePoolManager（core/device_pool_manager.py）                               │
│  ── 角色：调度层（health tracking、circuit-breaker、scheduling strategy）       │
│  ── register 时也 write-through 到 UDM（best-effort）                          │
│  ── 选设备时读自己本地池，不直接查询 UDM                                        │
│                                                                                 │
│  registered_devices compat cache（core/routes/_shared.py）                      │
│  ── 角色：遗留 compat 缓存（read-only compat surface）                          │
│  ── 明确降级：UDM 写入失败时本地不更新（gated on UDM success）                 │
│  ── is_authoritative=False，is_transitional=True                               │
│                                                                                 │
│  DeviceAgentManager（core/device_agent_manager.py）                             │
│  ── 角色：Agent 实例管理层（per-device agent 的创建 / 缓存）                    │
│  ── 注册时也写入 UDM，但以 "source=device_agent_manager" 标记                 │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────┐
│                   注册后节点纳管链（理想路径 vs 实际路径）                       │
│                                                                                 │
│  理想路径（设计意图）：                                                         │
│  注册 → UDM SSOT 写入 → CapabilityBus 传播 → CapabilityAssimilation           │
│       → DeviceReadiness 评估 → AttachedRuntimeSession 创建                     │
│       → MeshMembership 进入 → BodyMeshRegistry                                │
│       → MeshSession 可被创建 → 多设备联排候选池                                │
│                                                                                 │
│  实际路径（代码事实）：                                                         │
│  注册 → UDM SSOT 写入 ✅ → CapabilityBus 传播 ⚠️（条件性）                  │
│       → CapabilityAssimilation ⚠️（未在注册链中确认调用）                    │
│       → DeviceReadiness ✅（可查询）                                          │
│       → AttachedRuntimeSession ❌（未自动触发）                              │
│       → MeshMembership ❌（无自动进入）                                      │
│       → MeshSession ❌（无自动创建）                                         │
│       → 多设备联排 ❌（staging_mesh 需 formation，无自动 formation 创建）   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 各模块权威角色总结

| 模块 | 路径 | 架构角色 | 是否 SSOT | 生产写入者 |
|------|------|---------|-----------|------------|
| `UnifiedDeviceManager` | `core/unified/device_manager.py` | 设备状态 SSOT | ✅ 是 | DeviceRegistry、AndroidBridge、routes/devices、DeviceAgentManager |
| `UnifiedConnectionManager` | `core/unified/connection_manager.py` | 连接可路由状态权威 | ✅ 是（连接域） | WebSocketHandler、ssot.py |
| `galaxy_gateway.ssot` | `galaxy_gateway/ssot.py` | Gateway 写适配器 | ❌ 否（仅写透） | WebSocketHandler |
| `DeviceRegistry` | `core/device_registry.py` | 兼容层 / 索引 / 发现 | ❌ 否 | 自身 API（代理到 UDM） |
| `DevicePoolManager` | `core/device_pool_manager.py` | 调度健康层 | ❌ 否 | DeviceOrchestrator |
| `registered_devices` | `core/routes/_shared.py` | 遗留 compat 缓存 | ❌ 否 | routes/devices.py（镜像写） |
| `CapabilityBus` | `core/capability_bus.py` | 能力可见性传播 | 能力域权威 | UDM（自动触发）|
| `CapabilityAssimilationLayer` | `core/capability_assimilation.py` | 能力 → 图节点 | 能力图权威 | ⚠️ 注册链中未确认调用 |
| `AttachedRuntimeSessionRuntime` | `core/attached_runtime_session.py` | 运行时附着会话 | 附着域权威 | ❌ 无注册链自动触发 |
| `BodyMeshRegistry` | `core/mesh/body_mesh_registry.py` | Mesh 成员注册 | Mesh 成员域 | ❌ 无注册链自动进入 |

---

## 三、双仓系统现实架构图谱

> 每一块标注其性质：主工作层 / 次路径 / 增强层 / 记录层 / 定义层 / 兼容层 / 遗留层

### 3.1 控制面 / 启动面

**性质：主工作层**

```
main.py / unified_launcher.py
  └→ galaxy_gateway / bootstrap / lifecycle.py
       ├→ Phase A: UDM / UCM / DeviceManager 初始化
       ├→ Phase B: NATS Bus + GatewayNATSAdapter（可选，无 NATS 时静默跳过）
       ├→ Phase C: MasterBrain（GALAXY_MASTER_BRAIN_ENABLED 时激活）
       └→ WebSocket / REST API 就绪
```

关键状态：NATS 连接为可选项，单机模式下无 NATS 也正常运作。MasterBrain 是条件性激活。

---

### 3.2 设备控制面 / 节点纳管面

**性质：SSOT 骨架已完成（主工作层），节点纳管行为链（定义层 + 次路径）**

- UDM / UCM：主工作层（SSOT 写入已稳定）
- CapabilityBus：增强层（注册后自动触发，但 assimilation 调用待确认）
- DeviceReadiness：主工作层（可查询）
- DevicePoolManager：主工作层（调度用）
- DeviceRegistry：兼容层（降级明确）
- AttachedRuntimeSession：定义层（合同完整，无生产注册链触发）
- BodyMeshRegistry / MeshMembership：定义层（无自动进入）

---

### 3.3 主体 runtime

**性质：主工作层**

```
OpenClawd（core/openclawd.py）
  ├→ CommandRouter → TaskGraphRuntime → 任务图执行
  ├→ DesktopPresenceRuntime（本地 AI 执行）
  ├→ MultiLLMRouter（LLM 路由）
  ├→ SourceDispatchOrchestrator（PR-35，已有生产调用者）
  └→ _delegate_multi_device_orchestration()（条件性路由到 multi-device 层）
```

OpenClawd 是主体 runtime 的核心，已有生产调用。`_delegate_multi_device_orchestration` 在有 mesh session 的条件下才进入 `orchestrate_source_runtime_dispatch`，但 production 下 mesh session 通常为空。

---

### 3.4 多模态入口

**性质：主工作层（文本），增强层（其他模态）**

- 文本入口：WebSocket（Android）、REST、CLI — 主工作层
- 图像 / 视觉：vision_pipeline — 主工作层  
- 语音：multimodal ingress — 增强层
- WebRTC：webrtc_proxy — 次路径（条件性）

---

### 3.5 本地执行

**性质：主工作层**

OpenClawd._run_execution() → SafeExecutor → ToolGuardian → MCP工具链 / Skill链。  
本地执行路径最为成熟，是整个系统最稳定的执行面。

---

### 3.6 跨设备 Dispatch

**性质：次路径（Android 任务下发已通），定义层（能力路由）**

```
SourceDispatchOrchestrator.select_dispatch_mode()
  ├→ local（默认路径，主工作层）
  ├→ remote_handoff（有 target_device_id 时，次路径）
  └→ staged_mesh（2+ active mesh 参与者，定义层，production 下基本不触发）
```

Android 任务下发（`task_assign` via WebSocket）是次路径（实际工作），但不经过 `SourceDispatchOrchestrator`，而是通过 `AndroidBridge._fan_out_task_assign()` 直接操作，绕过了 canonical dispatch plan。

---

### 3.7 Handoff / Takeover

**性质：合同完整（定义层），runtime 双向闭环（未闭合）**

V2 侧：
- `HandoffEnvelopeV2`（合同）✅
- `execute_local_takeover()` / `TargetTakeoverHandler`（PR-34）✅ 定义完整
- `build_canonical_handoff_contract()` ✅
- 从 `AndroidBridge.assign_task()` 生成 handoff → WebSocket 推送 ✅

Android 侧（对称消费）：
- Android 接收 `task_assign` 消息并本地执行 ✅
- 但"以 HandoffEnvelopeV2 格式"进行原生 handoff ACK / 本地 takeover 路径 ⚠️ 未在双仓中确认为原生实现

---

### 3.8 Session Lifecycle

**性质：主工作层（conversation session），次路径 / 定义层（runtime session）**

```
SessionManager（conversation session）— 主工作层
AttachedRuntimeSessionRegistry — 定义层（无生产注册触发）
canonical_session_axis.py — 记录层（策略文档）
五大 session family 已完整定义，但 runtime attachment session 无自动生命周期驱动
```

---

### 3.9 Continuity / Recovery

**性质：合同完整（定义层），双边恢复循环（未闭合）**

- `DispatchContinuityContext` — 完整合同 ✅
- `MeshSessionPersistenceStore` — 本地持久化存储 ✅（文件后端）
- `recover_mesh_sessions()` — 可查询可恢复 sessions ✅
- Android 重连时 continuity token 重新提交路径 ⚠️ 未双边验证

---

### 3.10 Mesh / Multi-Device

**性质：合同定义层（完整），runtime 引擎（缺失）**

- `MeshSession` 合同 ✅
- `MeshMembership` 合同 ✅
- `MeshSessionCoordinator` 合同 ✅
- `BodyMeshRegistry` ✅（注册表，但需手动写入）
- `FormationRuntimeCoordinator` ✅（formation 重平衡）
- `MultiDeviceRuntimeHarness` ✅（readiness 触发）
- **活跃 coordinator engine（持续更新 participant 状态、barrier 协调）** ❌ 缺失
- **production 路径下 formation/mesh 自动建立** ❌ 缺失

---

### 3.11 Truth / Observability / Audit

**性质：主工作层（truth compiler），增强层（audit/replay）**

- `RuntimeTruthCompiler` / `compile_runtime_truth()` — 主工作层 ✅
- `ProjectionCompiler` — 主工作层 ✅
- `AuditEventSemantics` / `ReplayFoundation` — 增强层 ✅
- `OperatorSurface` — 主工作层（所有 operator 路由必须经此） ✅
- `MultiDeviceTruthConvergence` — 次路径（组装多设备真值快照）

---

### 3.12 Compat / Gates / Legacy Path

**性质：兼容层 / 遗留层，正在受控退役**

- `registered_devices` dict — 遗留 compat cache（read-only，降级明确）
- `DeviceRegistry` — 兼容索引层（PR-4 降级明确）
- `legacy_adapters/` — 遗留适配层，正在计划清除
- `legacy_purge_registry.py` — 遗留路径追踪注册

---

## 四、多链路全景图

### 链路 1：设备注册链

**入口**：Android WebSocket `device_register` 消息 / REST `POST /api/v1/devices/register`  
**关键调用序列**：
```
WebSocket 消息接收
  └→ parse_message_strict()（AIP v3+ 强制）
       └→ to_normalized_ingress_event()
            └→ handle_device_register()（android/handlers/registration.py）
                 └→ galaxy_gateway.ssot.udm_write_register()
                      └→ UnifiedDeviceManager.register_device()（UDM SSOT）
                           └→ CapabilityBus（能力自动传播）
                      └→ UCM 连接状态更新
                 └→ registered_devices compat 镜像写入
                 └→ 返回 device_register_ack
```
**真实参与模块**：WebSocketHandler、AIPv3 parser、RegistrationHandler、SSOT helper、UDM、UCM、CapabilityBus  
**当前状态**：✅ **已真实接通**（主链路稳定）  
**缺口**：CapabilityAssimilation 调用未确认；AttachedRuntimeSession 未自动创建

---

### 链路 2：Capability Ingestion 链

**入口**：`device_capabilities` AIP 消息 / 注册时 capabilities 字段  
**关键调用序列**：
```
device_register.capabilities 字段
  └→ UDM.register_device()（携带 capabilities list）
       └→ CapabilityBus.register_capability()（自动触发）
            └→ CapabilityAssimilationLayer.assimilate_device()（❓ 未确认）
                 └→ capability graph 更新
```
**真实参与模块**：UDM、CapabilityBus  
**当前状态**：⚠️ **部分接通**（UDM→CapabilityBus ✅，CapabilityBus→AssimilationLayer ❓）  
**缺口**：Android 设备能力是否真实进入 capability graph 做路由决策未验证

---

### 链路 3：心跳链

**入口**：Android `heartbeat` 消息 / NATS `galaxy.workers.heartbeat`  
**关键调用序列**：
```
WebSocket heartbeat 消息
  └→ handle_heartbeat()
       └→ ssot.udm_write_heartbeat()
            └→ UDM.heartbeat()
                 └→ UCM 更新 last_seen
       └→ 返回 heartbeat_ack
```
**真实参与模块**：WebSocketHandler、HeartbeatHandler、SSOT、UDM、UCM  
**当前状态**：✅ **已真实接通**  
**缺口**：NATS 心跳（节点侧）与 WebSocket 心跳（Android 侧）是两条独立链路，汇聚真值在 UDM 层

---

### 链路 4：Participant / Mesh 进入链

**入口**：设备注册后（理论上）  
**关键调用序列（理想）**：
```
注册成功
  └→ DeviceReadiness 评估
       └→ attach_runtime_session()
            └→ AttachedRuntimeSessionRuntime.push()
       └→ BodyMeshRegistry.register()
            └→ MeshMembership 创建
       └→ formation 分配
```
**当前状态**：❌ **未闭环**（无自动触发路径）  
**说明**：以上每个步骤都有实现，但没有任何生产代码在注册成功后自动将设备推进到这些状态

---

### 链路 5：Task_assign / Goal_execution 链

**入口**：服务端生成任务，向 Android 下发  
**关键调用序列**：
```
AndroidBridge.assign_task() / _fan_out_task_assign()
  └→ MessageBuilder.task_assign()
       └→ UCM.send_to_device()
            └→ WebSocket push → Android 设备接收
                 └→ Android 本地执行（AgentMessageHandler._handle_task_execute()）
                      └→ 执行完成 → task_result 消息返回
```
**真实参与模块**：AndroidBridge、MessageBuilder、UCM、WebSocketHandler  
**当前状态**：✅ **已真实接通**  
**缺口**：此路径绕过了 SourceDispatchOrchestrator / SourceDispatchPlan，dispatch 决策未被 canonical 记录

---

### 链路 6：Task_result / Goal_result 回送链

**入口**：Android `task_result` WebSocket 消息  
**关键调用序列**：
```
WebSocket task_result 消息
  └→ handle_task_result()（android/handlers/task_lifecycle.py）
       └→ 结果解析
       └→ memory backflow（可选）
       └→ GatewayNATSAdapter.resolve_task()（如果任务来自 NATS dispatch）
       └→ 结果返回给 caller
```
**真实参与模块**：TaskLifecycleHandler、GatewayNATSAdapter  
**当前状态**：✅ **已真实接通**（主链路）  
**缺口**：结果回送后是否写入 TaskGraphRuntime / OperatorSurface 未确认全覆盖

---

### 链路 7：Handoff / Takeover 链

**入口**：SourceDispatchOrchestrator 选择 `remote_handoff` 模式 / 直接调用  
**关键调用序列（V2 发送侧）**：
```
select_dispatch_mode() → remote_handoff
  └→ build_handoff_envelope_v2()
       └→ HandoffEnvelopeV2（合同 PR-31）
            └→ WebSocket push → Android 接收
```
**关键调用序列（Android 接收侧）**：
```
Android 接收 task_assign（handoff 类型）
  └→ 本地执行（AgentMessageHandler）
  └→ ??? HandoffEnvelopeV2 原生解析（未确认）
```
**当前状态**：⚠️ **部分接通**（V2 发送侧完整，Android 原生 HandoffEnvelopeV2 消费未确认）

---

### 链路 8：Runtime Attach 链

**入口**：手动调用 `attach_runtime_session()` / 无自动触发  
**关键调用序列**：
```
attach_runtime_session(device_id, source_runtime_posture="join_runtime")
  └→ classify_attach_lifecycle_action()
       └→ AttachedRuntimeSessionRecord 创建（attached 状态）
            └→ AttachedRuntimeSessionRuntime.push()（内存 ring buffer）
```
**当前状态**：⚠️ **定义层完整，但无注册链自动触发**  
**缺口**：注册成功后没有任何代码自动调用 `attach_runtime_session()`；只有显式调用才会创建附着记录

---

### 链路 9：Continuity / Reconnect 链

**入口**：Android 断连后重连  
**关键调用序列**：
```
设备重连 → device_register 重新发送
  └→ UDM upsert（保留首次注册时间）
  └→ UCM 更新连接状态
  └→ AttachedRuntimeSessionRegistry reconnect signal（❓ 未确认）
       └→ DispatchContinuityContext 重关联（❓ 未确认）
            └→ 执行恢复（❓ 未确认）
```
**当前状态**：❌ **未闭环**（continuity token 重提交路径未验证）

---

### 链路 10：Multi-Device Orchestration 链

**入口**：OpenClawd._delegate_multi_device_orchestration()（条件性）  
**关键调用序列**：
```
检测到 mesh session 有 2+ active 参与者
  └→ orchestrate_source_runtime_dispatch()
       └→ select_dispatch_mode() → staged_mesh
            └→ SourceDispatchPlan 构建
            └→ MeshSessionCoordinator 协调（❓ 无 live engine）
            └→ 多设备任务分发
```
**当前状态**：❌ **定义层 / 条件苛刻**（production 下 mesh session 通常为空，staged_mesh 路由实际不可达）

---

### 链路 11：Observability / Truth / Replay 链

**入口**：`/api/v1/projection/runtime-truth` / OperatorSurface 查询  
**关键调用序列**：
```
GET /api/v1/projection/runtime-truth
  └→ _assemble_runtime_truth_payload()
       └→ RuntimeTruthCompiler.compile_runtime_truth()
            ├→ MultiLLMRouter（topology）
            ├→ DevicePresenceRuntime（device_presence）
            ├→ NetworkTopologyRuntime（routing graph）
            └→ DesktopStatusBoardIntegrationPayload 汇总
```
**当前状态**：✅ **已真实接通**（truth 输出链稳定）

---

## 五、双仓行为闭环对照总表

| 消息 / 合同 / 字段 | V2 实际发送/消费 | Android 实际发送/消费 | 当前状态 | 问题说明 | 发送侧闭环 | 接收侧情况 |
|---|---|---|---|---|---|---|
| `device_register` | 消费（handlers/registration.py → UDM） | 发送（AgentWebSocket） | ✅ 双边闭合 | - | ✅ | ✅ |
| `device_register_ack` | 发送（registration handler 返回） | 消费（AgentWebSocket） | ✅ 双边闭合 | - | ✅ | ✅ |
| `heartbeat` | 消费（handlers/heartbeat.py → UDM） | 发送（AgentWebSocket） | ✅ 双边闭合 | - | ✅ | ✅ |
| `heartbeat_ack` | 发送 | 消费 | ✅ 双边闭合 | - | ✅ | ✅ |
| `task_assign` | 发送（AndroidBridge/MessageBuilder） | 消费（AgentMessageHandler） | ✅ 双边闭合 | 绕过 canonical dispatch plan | ✅ | ✅ |
| `task_result` | 消费（handlers/task_lifecycle.py） | 发送（执行完毕后） | ✅ 双边闭合 | result 是否写入 TaskGraphRuntime 未全确认 | ✅ | ✅ |
| `task_cancel` | ❌ 无 canonical handler | 发送（Android 用户取消） | ❌ 未闭环 | Android 发出取消，V2 静默忽略 | ❌ | 单边定义 |
| `task_status` | ❌ 无 canonical handler | 发送（状态查询） | ❌ 未闭环 | 状态查询无响应 | ❌ | 单边定义 |
| `goal_execution` | 消费（handlers/goal_execution.py） | 发送 | ✅ 单边处理 | V2 侧将其转为 task_assign 后下发，不是 goal_result 格式回送 | ⚠️ | 转发后处理 |
| `goal_result` | ❓ 未确认 | ❓ 未确认 | ⚠️ 漂移风险 | goal_result 格式是否与 task_result 对齐未验证 | ⚠️ | ⚠️ |
| `device_capabilities` | 消费（注册时） → UDM → CapabilityBus | 发送（device_register payload） | ⚠️ 部分接通 | CapabilityBus → AssimilationLayer 未确认 | ⚠️ | ✅ |
| `HandoffEnvelopeV2` | 发送（build_handoff_envelope_v2） | ❓ 消费路径未在双仓原生确认 | ⚠️ 单边完整 | Android 以 task_assign 接收，不以 HandoffEnvelopeV2 原生格式接收 | ✅ | ⚠️ |
| `LocalTakeoverResult` | 消费（execute_local_takeover） | ❓ 无对称实现确认 | ⚠️ 定义层 | V2 侧 target_takeover.py 完整，Android 对称路径未确认 | ✅ | ❌ |
| `MeshSession` | 使用（contracts） | ❓ 参与记录 | ⚠️ 部分接通 | Android 作为 participant 参与 mesh session，但 mesh session 创建在 V2 侧；production 下 mesh session 通常为空 | ⚠️ | ⚠️ |
| `AttachedRuntimeSessionRecord` | 定义 + 手动创建 | ❓ 无明确触发 | ❌ 未闭环 | 无自动 attach 链，无 Android 侧 ACK | ❌ | ❌ |
| `DispatchContinuityContext` | 定义完整 | ❓ 重连时提交路径未确认 | ❌ 未闭环 | continuity token 双边流转未验证 | ❌ | ❌ |
| `MeshMembership` | 定义完整，无自动进入 | 应参与 | ❌ 未闭环 | 无自动 mesh 进入机制 | ❌ | ❌ |
| `runtime_attachment_session_id` | 定义（canonical_session_axis） | ❓ 未确认传递 | ⚠️ 漂移风险 | session identity 是否双边同步未验证 | ⚠️ | ⚠️ |
| `posture / coordinator_state` | 使用于 SourceDispatchMode 选择 | ❓ Android 是否上报 posture | ⚠️ 部分 | source_runtime_posture 在合同中有字段，Android 上报时是否携带未确认 | ⚠️ | ⚠️ |
| `task_cancel_ack` | ❌ 不存在 | ❌ 未期望 | ❌ 未闭环 | 任务取消无 ACK | ❌ | ❌ |

---

## 六、问题清单（P0 / P1 / P2）

### P0：影响现有用户体验的关键缺口

#### P0-001：task_cancel 被 V2 静默忽略

**现状**：Android 用户取消任务后发送 `task_cancel` 消息，V2 无对应处理器，任务继续执行，Android UI 显示"已取消"但实际未取消。  
**真实代码证据**：`galaxy_gateway/android/handlers/` 目录中无 `task_cancel` handler；`android_bridge.py` 无 `_handle_task_cancel`。  
**影响**：用户体验严重损坏；任务资源浪费。  
**风险**：任务积压、Android 状态与服务端状态不一致。  
**建议方向**：在 `android/handlers/task_lifecycle.py` 中添加 `handle_task_cancel()`，调用 `CommandRouter.cancel_envelope(task_id)`，返回 `task_cancel_ack`。

---

#### P0-002：task_status 查询无响应

**现状**：Android 发送 `task_status` 查询，V2 无对应 handler，Android 无法知道任务当前进度。  
**真实代码证据**：同 P0-001，handlers 目录无 `task_status` handler。  
**影响**：Android 侧无法监控长时间任务的执行状态。  
**建议方向**：添加 `handle_task_status()`，读取 `TaskGraphRuntime` 状态，返回 `task_status_response`。

---

### P1：关键架构完整性缺口

#### P1-001：Capability Assimilation 未在注册链中确认接通

**现状**：Android 设备注册携带 `capabilities`，UDM 写入后 CapabilityBus 自动触发，但 `CapabilityAssimilationLayer.assimilate_device()` 是否在此路径中被调用未有明确代码证据。  
**真实代码证据**：`core/capability_bus.py` 中 CapabilityBus 的 subscriber 列表和注册逻辑需要人工确认是否包含 AssimilationLayer 订阅。  
**影响**：Android 设备可能在 UDM 中已注册但在 capability graph 中不可见，导致 capability-based routing 跳过 Android 设备。  
**风险**：能力路由选不到 Android 设备，多设备调度无效。  
**建议方向**：在注册 handler 或 UDM write 后端显式确认 AssimilationLayer.assimilate_device() 调用，并写测试验证。

---

#### P1-002：注册后无 AttachedRuntimeSession 自动创建

**现状**：`attach_runtime_session()` 存在且定义完整，但没有任何代码在设备注册成功后自动调用它。设备从"已注册"到"已附着运行时节点"之间有一个完全空白的过渡。  
**真实代码证据**：`core/attached_runtime_session.py` — `attach_runtime_session()` 无自动调用者。搜索整个 codebase，`attach_runtime_session` 的调用来自测试代码和少量内部工具，而非注册链。  
**影响**：`AttachedRuntimeSessionRecord` 永远为空，后续依赖 attached session 的功能（runtime continuity、reconnect session preservation）全部无法正常工作。  
**风险**：整个 attached runtime session 合同体系失去实际价值。  
**建议方向**：在 `handle_device_register()` 成功后，若设备的 `source_runtime_posture == "join_runtime"`，自动调用 `attach_runtime_session()`。

---

#### P1-003：Handoff 缺少 Android 侧原生 HandoffEnvelopeV2 消费路径

**现状**：`HandoffEnvelopeV2` 是完整且稳定的合同（PR-31），V2 侧可以构建并发送。但 Android 侧接收后，以 `task_assign` payload 处理，并不会原生解析 `HandoffEnvelopeV2` 的 source/target summary、session_context、takeover_policy 等字段。  
**真实代码证据**：`docs/ugcp/CROSS_REPO_HOMOMORPHIC_MAPPING_V1.md` 中标注 `HandoffEnvelopeV2` 的映射状态为 `≈`（近似对齐，wire-level union in-progress）。  
**影响**：Takeover policy、session context propagation 等高级语义在 Android 侧被忽略。  
**风险**：复杂 handoff 语义（例如 require_ack_before_takeover）无法端到端执行。  
**建议方向**：Android 侧添加对 `handoff` 类型消息的原生解析，消费 `HandoffEnvelopeV2` 字段并执行相应的 takeover policy。

---

#### P1-004：Continuity / Recovery 双边循环未验证

**现状**：`DispatchContinuityContext` 在 V2 侧定义和使用，`MeshSessionPersistenceStore` 实现了本地 JSON 持久化，`recover_mesh_sessions()` 可加载。但 Android 断连重连后，是否能以 continuity token 重关联上次执行上下文，整个双边路径缺乏测试验证。  
**真实代码证据**：`contracts/dispatch_continuity.py` 完整定义，但在 `android_bridge.py` 的 reconnect 处理路径中无 continuity context 查找与关联逻辑。  
**影响**：断线重连等场景下，任务执行上下文丢失，用户体验降级。  
**建议方向**：在设备重连处理（device_register 重发）时，查找该设备的最近 `AttachedRuntimeSessionRecord` 并触发 reconnect signal，关联 `DispatchContinuityContext`。

---

#### P1-005：MeshSession production path 不可达（staged_mesh 死路）

**现状**：`select_dispatch_mode()` 中 `staged_mesh` 路径在 mesh session 有 2+ active 参与者时才触发。但在生产路径中，没有任何机制自动创建 mesh session 和将设备加入其中。`BodyMeshRegistry` 需要显式写入，`formation` 创建需要显式触发。  
**真实代码证据**：`core/runtime/source_dispatch_orchestrator.py` 中 `staged_mesh` 的触发条件依赖 `_try_mesh_session()` 返回有 2+ active participants 的 session；而 `_try_mesh_session()` 从 `MeshSessionCoordinator` 读取，而 coordinator 只有在 formation 存在时才有数据。  
**影响**：多设备联排实际上无法在 production 中自然触发，需要手动构造 formation 和 mesh session。  
**建议方向**：建立 formation 自动创建机制（当 2+ 设备注册且能力互补时自动构建 formation），或提供 API 显式触发 formation 创建并写入 BodyMeshRegistry。

---

### P2：架构改善建议

#### P2-001：DeviceRegistry ↔ UDM 双写路径仍存在

**现状**：`DeviceRegistry.register()` 代理写入 UDM，但本地索引（`devices` dict、group/tag/capability 索引）仍然维护，存在与 UDM 状态漂移的可能。  
**建议方向**：长期应把 DeviceRegistry 彻底降级为 UDM 的 read-only 投影，消除任何本地写索引。

---

#### P2-002：dispatch_contract_metadata 在 Android fan-out 路径中缺失

**现状**：`AndroidBridge._fan_out_task_assign()` 直接构建 task_assign 消息，不经过 `SourceDispatchOrchestrator`，因此没有 `SourceDispatchPlan` 和 `dispatch_contract_metadata`。  
**建议方向**：fan-out 路径应通过 `SourceDispatchOrchestrator.build_source_dispatch_plan()` 获得 plan 后再构建 task_assign，将 dispatch plan ID 写入 metadata。

---

#### P2-003：MeshSessionCoordinator 缺少活跃 runtime engine

**现状**：`MeshSessionCoordinatorState` 合同定义完整，但没有持续更新 participant 状态、驱动 barrier、触发 merge 的活跃运行时类。coordinator 状态在构建时静态，不随执行进展更新。  
**建议方向**：实现 `LiveMeshSessionCoordinator` 类，订阅 task_result 事件，自动更新 participant 状态，触发 barrier 解除和结果 merge。

---

#### P2-004：goal_result 格式未与 task_result 对齐验证

**现状**：`handle_goal_execution()` 将 goal 转换为 task_assign 后下发，Android 执行后以 task_result 格式回送，但 goal_result 的语义字段（goal completion status、subtask breakdown 等）可能未被正确解析。  
**建议方向**：明确 goal_result 字段规范，与 task_result 对齐，或添加专用 goal_result 处理器。

---

#### P2-005：NATS 节点心跳与 UDM 设备状态的汇聚点不清晰

**现状**：节点心跳走 NATS（`galaxy.workers.heartbeat`），Android 设备心跳走 WebSocket。两者都最终写入 UDM，但汇聚路径不同：NATS 通过 `GatewayNATSAdapter`，WebSocket 通过 `ssot.udm_write_heartbeat()`。  
**建议方向**：确保两条心跳路径在 UDM 中以相同格式更新，避免节点 online 状态评估与设备 online 状态评估使用不同字段。

---

## 七、已有成熟度 / 完成度总表

| 系统层 | 成熟度判断 | 简短依据 |
|--------|-----------|---------|
| 启动 / 控制面 | ⭐⭐⭐⭐ 高 | main.py → lifecycle.py → UDM/UCM 初始化链完整，NATS 可选且静默降级 |
| 设备控制面 / 注册 | ⭐⭐⭐⭐ 高 | UDM SSOT 已定型，三路入口（REST/WS/DeviceRegistry）均代理到 UDM，兼容层明确降级 |
| 统一设备真值（UDM） | ⭐⭐⭐⭐ 高 | 单例、写透、去重语义、state_version、source 标记齐全 |
| 节点纳管（注册后行为）| ⭐⭐ 低 | 注册后无 attached session、无 mesh 进入、无 capability assimilation 确认 |
| 主体 runtime（OpenClawd）| ⭐⭐⭐⭐⭐ 完整 | 命令路由、任务图、LLM路由、工具链、结果输出均工作 |
| 多模态入口 | ⭐⭐⭐⭐ 高 | 文本、图像完整；语音 / WebRTC 增强层 |
| 本地执行 | ⭐⭐⭐⭐⭐ 完整 | SafeExecutor + MCP + Skill 链路最为成熟 |
| LLM 路由 | ⭐⭐⭐⭐⭐ 完整 | MultiLLMRouter + topology 完整 |
| 工具链 | ⭐⭐⭐⭐ 高 | MCP + Skill 接入完整，ToolGuardian 存在 |
| 跨设备发送链 | ⭐⭐⭐ 中 | task_assign via WebSocket 真实工作；但绕过 canonical dispatch，未通过 SourceDispatchOrchestrator |
| Android 执行链 | ⭐⭐⭐⭐ 高 | device_register → heartbeat → task_assign → task_result 主链路稳定 |
| 结果回送闭环 | ⭐⭐⭐⭐ 高 | task_result 处理完整；NATS resolve 完整 |
| Handoff / Takeover | ⭐⭐ 低 | V2 侧合同完整，Android 原生消费路径未确认，双向闭环未验证 |
| Attached Runtime Session | ⭐⭐ 低 | 合同完整、API 完整，无生产注册链触发 |
| Session Lifecycle | ⭐⭐⭐ 中 | conversation session 完整；runtime attachment session 定义层 |
| Continuity / Recovery | ⭐⭐ 低 | V2 侧结构完整，双边循环未验证 |
| Mesh / Multi-Device | ⭐⭐ 低 | 合同层极为完整，但运行时引擎缺失，production 路径不可达 |
| Task / Runtime Truth | ⭐⭐⭐⭐ 高 | runtime_truth_compiler 完整，audit/replay 增强层完整 |
| Observability / Trace | ⭐⭐⭐⭐ 高 | trace_id 全链传播，audit 路由，observability 端点稳定 |
| Contract / Gates / Validation | ⭐⭐⭐⭐ 高 | 大量 architecture invariants 检查，PR-N sentinel 体系完整 |
| Compat / Legacy Bridge | ⭐⭐⭐ 中 | 兼容层明确降级，但 DeviceRegistry 双写、registered_devices 仍存在 |
| 双仓行为闭环 | ⭐⭐⭐ 中 | 主链路（注册/心跳/任务/结果）闭合；高级语义（handoff/continuity/mesh）未闭合 |
| "任意设备操纵全网"能力 | ⭐ 极低 | 当前每个节点只能收发任务，不具备操纵全网的 routing authority 和 session authority |

---

## 八、总体完成度判断

| 维度 | 完成度区间 | 依据说明 |
|------|-----------|---------|
| 1. 核心单机 AI 助手能力 | **90–95%** | OpenClawd + MultiLLMRouter + 工具链 + 任务图均可靠工作 |
| 2. 服务端主链（API / WS / routing）| **85–90%** | 主链路稳定，部分边缘 handler 缺失（task_cancel/status） |
| 3. Android 执行侧（主任务链）| **75–80%** | 注册/心跳/task/result 主链闭合；cancel/status/goal_result 存在缺口 |
| 4. 设备控制面（UDM/UCM/SSOT）| **80–85%** | SSOT 骨架完整；capability assimilation 未确认接通 |
| 5. 节点纳管（注册后行为）| **20–30%** | attached session/mesh entry/formation 无自动触发 |
| 6. 跨设备发送链（task 下发）| **70–75%** | task_assign 工作；但绕过 canonical dispatch plan |
| 7. 双仓行为闭环（主链）| **70–75%** | 主链路闭合；高级语义链路未闭合 |
| 8. Handoff / Takeover | **25–35%** | V2 侧合同完整；双边行为闭环缺失 |
| 9. Attached Runtime / Session | **20–30%** | 合同完整；生产调用链缺失 |
| 10. Continuity / Recovery | **25–35%** | V2 侧结构完整；双边流转未验证 |
| 11. Mesh / Multi-Device | **25–35%** | 合同层完整；runtime engine / production 可达性缺失 |
| 12. Truth / Observability | **85–90%** | truth compiler + audit/replay + observability 链完整 |
| 13. Contract 行为化 | **50–60%** | 合同极为完整；但相当一部分合同未被 production caller 驱动 |
| 14. "任意设备操纵全网"能力 | **10–15%** | 概念架构已设计，但关键行为链（mesh/handoff/takeover/routing authority）未闭合 |
| **15. 完整中心分布智能体系统总体完成度** | **55–65%** | 单机 AI 层完整；设备纳管/多设备/continuity/handoff 等系统层次尚在定义→行为化过渡 |

---

## 九、系统级总 PR 规划（增强版）

### PR-X1：P0 修复 — task_cancel / task_status 双向协议

**标题**：Android task_cancel 和 task_status 双向协议闭环  
**目标模块**：`galaxy_gateway/android/handlers/task_lifecycle.py`, `core/command_router.py`  
**要打通的真实链路**：Android → `task_cancel` → CommandRouter.cancel_envelope() → `task_cancel_ack` → Android  
**非目标**：mesh session、continuity、handoff  
**验收标准**：
- Android 发送 task_cancel 后，任务实际停止执行
- Android 收到 task_cancel_ack
- Android 发送 task_status 后，收到包含真实执行状态的 task_status_response
- 单元测试：cancel propagation、status query  
**依赖**：无，可立即启动

---

### PR-X2：P1 修复 — Capability Assimilation 注册链确认

**标题**：Android 设备注册后能力确认进入 capability graph  
**目标模块**：`galaxy_gateway/android/handlers/registration.py`, `core/capability_assimilation.py`, `core/capability_bus.py`  
**要打通的真实链路**：device_register.capabilities → UDM → CapabilityBus → CapabilityAssimilationLayer.assimilate_device() → capability graph  
**非目标**：mesh session、routing 策略变更  
**验收标准**：
- Android 注册后，`CapabilityAssimilationLayer` 中可查到该设备的能力记录
- capability-based routing 可将该设备作为候选
- 集成测试：设备注册 → capability graph 包含设备条目  
**依赖**：无

---

### PR-X3：P1 修复 — 注册后自动 Attached Runtime Session 创建

**标题**：设备注册成功后自动创建 AttachedRuntimeSession  
**目标模块**：`galaxy_gateway/android/handlers/registration.py`, `core/attached_runtime_session.py`  
**要打通的真实链路**：device_register（join_runtime posture）→ attach_runtime_session() → AttachedRuntimeSessionRecord  
**非目标**：mesh session、continuity recovery（下一 PR）  
**验收标准**：
- 携带 `source_runtime_posture: join_runtime` 的设备注册后，`get_attached_runtime_session(device_id)` 返回 attached 记录
- control_only posture 设备不触发 attach
- 单元测试：posture gate 验证  
**依赖**：PR-X2（能力 assimilation 先确认接通）

---

### PR-X4：Continuity / Recovery 双边闭环

**标题**：Android 断连重连时 continuity context 自动恢复  
**目标模块**：`galaxy_gateway/android/handlers/registration.py`（重连判断）, `core/attached_runtime_session_registry.py`, `contracts/dispatch_continuity.py`  
**要打通的真实链路**：Android 重连 → 发现已有 AttachedRuntimeSessionRecord → 发送 reconnect signal → DispatchContinuityContext 关联 → 可恢复执行  
**非目标**：mesh session persistence  
**验收标准**：
- Android 断连后重连，`runtime_attachment_session_id` 保持不变（reconnect 语义）
- 之前未完成的任务可以通过 continuity context 重关联
- 端到端测试：disconnect → reconnect → task resumption  
**依赖**：PR-X3

---

### PR-X5：Handoff / Takeover 双向协议闭环

**标题**：HandoffEnvelopeV2 双边原生闭环  
**目标模块**：V2 `core/canonical_handoff_path.py`, Android 侧消费路径  
**要打通的真实链路**：V2 build_handoff_envelope_v2() → WebSocket push → Android 原生解析 HandoffEnvelopeV2 → 执行 takeover_policy → 返回 handoff_ack / result  
**非目标**：mesh session  
**验收标准**：
- Android 接收 handoff 类型消息时，以 HandoffEnvelopeV2 格式解析 source/target/takeover_policy
- `require_ack_before_takeover: true` 时，Android 在开始执行前发送 ACK
- 跨仓集成测试：V2 → handoff → Android 消费 → 返回结果  
**依赖**：PR-X3（attached session 先存在）

---

### PR-X6：Formation 自动构建与 Mesh 进入机制

**标题**：多设备 formation 自动构建与 mesh session 创建  
**目标模块**：`core/device_formation/`, `core/mesh/body_mesh_registry.py`, `core/mesh/mesh_session_lifecycle.py`  
**要打通的真实链路**：2+ 设备注册 → 自动 formation 构建 → BodyMeshRegistry 写入 → MeshMembership 创建 → MeshSession 可被 SourceDispatchOrchestrator 发现  
**非目标**：live coordinator engine（下一 PR）  
**验收标准**：
- 2 台 Android 设备注册后，`get_device_participation(device_id).mesh_member == True`
- `select_dispatch_mode()` 在 2+ 设备 active 时返回 `staged_mesh`
- 集成测试：multi-device registration → mesh session → staged_mesh mode  
**依赖**：PR-X3

---

### PR-X7：Live MeshSessionCoordinator Runtime Engine

**标题**：实现 LiveMeshSessionCoordinator，驱动 participant 状态、barrier、merge  
**目标模块**：`core/mesh/mesh_session_coordinator.py`（新增 runtime engine）  
**要打通的真实链路**：MeshSession → participant task 分发 → task_result 回送 → coordinator 更新 participant 状态 → barrier 解除 → merge 触发 → MeshSession 状态更新为 completed  
**非目标**：persistence（已有 MeshSessionPersistenceStore）  
**验收标准**：
- `MeshSessionCoordinatorState.participant_states` 随任务执行动态更新
- 所有参与者完成后 barrier 自动解除并触发 merge
- 端到端测试：staged_mesh 从 dispatch 到 merge 完整执行  
**依赖**：PR-X6

---

### PR-X8：SourceDispatchOrchestrator 覆盖 fan-out 路径

**标题**：Android fan-out task_assign 改走 canonical dispatch plan  
**目标模块**：`galaxy_gateway/android_bridge.py`, `core/runtime/source_dispatch_orchestrator.py`  
**要打通的真实链路**：_fan_out_task_assign → SourceDispatchOrchestrator.build_source_dispatch_plan() → SourceDispatchPlan → task_assign（含 dispatch_contract_metadata）  
**非目标**：staged_mesh（需 PR-X6/X7 先完成）  
**验收标准**：
- fan-out 生成的 task_assign 消息包含 `dispatch_plan_id` 和 `dispatch_contract_metadata`
- SourceDispatchPlan 可在 OperatorSurface 查到  
**依赖**：PR-X6

---

### PR-X9：双仓 Round-trip 行为测试 / Drift Gates

**标题**：双仓核心链路 round-trip 行为测试与 drift gates  
**目标模块**：`tests/test_cross_repo_*.py`（新增），`core/cross_repo_contract_finalization.py`  
**要打通的真实链路**：device_register → heartbeat → task_assign → task_result → handoff → continuity 的全链路模拟测试  
**非目标**：不引入真实 Android 设备  
**验收标准**：
- 使用 mock Android 客户端，验证 10+ 关键双边消息序列
- CI 中运行，任一消息格式漂移即 fail  
**依赖**：PR-X1、PR-X5

---

### PR-X10：Truth / Policy 进入可依赖系统层

**标题**：device posture / capability truth 进入 routing 和 dispatch 决策  
**目标模块**：`core/device_selection/`, `core/device_participation.py`, `core/runtime/source_dispatch_orchestrator.py`  
**要打通的真实链路**：UDM 设备状态 → DeviceReadiness → 能力路由 → SourceDispatchOrchestrator 目标选择 → 依赖 UDM truth 而非临时连接信息  
**非目标**：mesh engine  
**验收标准**：
- `select_dispatch_target()` 读取 UDM 设备能力作为候选池
- 设备离线后自动从候选池移除
- 能力不匹配的设备不被选中  
**依赖**：PR-X2

---

## 十、可直接复制续聊版摘要

以下为精炼摘要，可直接作为续聊母版上下文使用：

---

### Galaxy V2 系统现状速查摘要（2026-04-19）

**系统定位**：V2 是中心协调式分布智能体系统的控制面/主体 runtime。Android/Windows/平板为设备节点，接受 V2 调度、上报执行结果，最终目标是"任意设备可操纵全网"。

**已真实成立的层（可依赖）：**
- 单机 AI 核心（OpenClawd + MultiLLMRouter + 工具链 + 任务图）— 完整
- UDM（UnifiedDeviceManager）作为设备 SSOT — 已稳定，三路入口均代理到 UDM
- UCM（UnifiedConnectionManager）作为连接权威 — 已稳定
- Android 主任务链：`device_register → heartbeat → task_assign → task_result` — 双边闭合
- Runtime truth / observability：`compile_runtime_truth()` + 投影链 + audit 链 — 可靠
- 合同体系：HandoffEnvelopeV2、MeshSession、MeshMembership、LocalTakeoverResult、DispatchContinuityContext — 定义完整

**关键未闭合层（按优先级）：**
1. **P0**：`task_cancel` / `task_status` — Android 发出，V2 静默忽略，现有用户体验有损
2. **P1-001**：CapabilityAssimilation 未在注册链确认 — Android 设备能力可能不进入路由
3. **P1-002**：注册后无 AttachedRuntimeSession 自动创建 — attached session 合同无生产驱动
4. **P1-003**：HandoffEnvelopeV2 Android 原生消费路径未确认 — handoff 高级语义被忽略
5. **P1-004**：Continuity/Recovery 双边循环未验证 — 断线重连上下文丢失
6. **P1-005**：MeshSession production 路径不可达（staged_mesh 需要先有 formation，无自动机制）

**整体完成度速查：**
- 单机 AI：90–95% ✅
- 服务端主链：85–90% ✅
- Android 执行主链：75–80% ✅
- 设备控制面骨架：80–85% ✅
- 节点纳管行为：20–30% ❌
- Handoff/Takeover：25–35% ⚠️
- Mesh/Multi-Device：25–35% ⚠️
- Continuity/Recovery：25–35% ⚠️
- "任意设备操纵全网"：10–15% ❌
- 系统总体（分布智能体）：55–65% ⚠️

**后续 PR 优先顺序：**  
PR-X1（task_cancel/status）→ PR-X2（capability assimilation 确认）→ PR-X3（attached session 自动创建）→ PR-X4（continuity/recovery）→ PR-X5（handoff 双边闭环）→ PR-X6（formation/mesh 自动）→ PR-X7（live coordinator）→ PR-X8（dispatch plan）→ PR-X9（drift tests）→ PR-X10（truth 进入 routing）

**架构稳定性结论**：V2 的架构设计是合理且前瞻的，合同体系极为完整，SSOT 层已定型。当前最大的问题不是设计问题，而是"定义存在但无生产调用者"的行为化缺口，需要逐条补全注册链行为、handoff 双边协议、continuity 循环、mesh runtime engine。

---

> 本文档由系统级代码审查生成，基于 `ufo-galaxy-realization-v2` 仓库截至 2026-04-19 的代码现实。  
> 下次续聊时直接引用本摘要（第十节）即可恢复完整系统上下文。
