# 多机模式（跨设备 · 多设备并行 · 任务派发与分配 · NATS Agent）

> **状态：2026-10-05 定义并记录。没有合并任何开关、没有改任何行为。**
> 所有者的设计：把「让这台电脑加上别的设备 / 别的机器像一个整体干活」这一整块，作为**一个模块**来看 ——
> 跨设备是前提，多设备并行建立在它之上，再往上是 NATS 上的 Agent（主脑与 worker）和任务的派发与分配。
> 这份文档回答：这个模块**由哪几层组成、一个任务怎么走完、每一层有哪些配置键 / 模块 / 接口、现在哪里不一致**。
> 配置键表由 `python scripts/gen_multi_machine_map.py --write` 从实时登记表生成；其余是 2026-10-05 对着代码查的快照，
> 没有查到的地方明说，没有实测过的地方写「按代码读」。

## 一、四层，外加一个共用底座

```
┌──────────────────────────────────────────────────────────────┐
│ 第四层  NATS Agent：主脑（MasterBrain）+ worker + 节点心跳注册      │
├──────────────────────────────────────────────────────────────┤
│ 第三层  任务派发与分配：CommandRouter → 三条执行路径、就绪闸、幂等、续跑 │
├──────────────────────────────────────────────────────────────┤
│ 第二层  多设备并行：设备清单、编队、选择、并行扇出、编排（SwarmCoordinator）│
├──────────────────────────────────────────────────────────────┤
│ 第一层  跨设备：发现、接入、信任、传输                              │
├──────────────────────────────────────────────────────────────┤
│ 共用底座  NATS 消息总线（第一层的设备/在场/能力平面 + 第四层的任务/worker 平面）│
└──────────────────────────────────────────────────────────────┘
```

依赖关系（从下往上）：第二层要第一层通；第三层要前两层；第四层要前两层**和** NATS 总线。
下两层是地基，上两层建立在地基上 —— 这就是所有者说的「后续建立在这两个基础之上」。

| 层 | 一句话 | 现在的开关 |
|---|---|---|
| 第一层 跨设备 | 设备能不能互相找到、认识、传话 | `GALAXY_CROSS_DEVICE_ENABLED`（面板「跨设备」整档按钮的主键）+ 约 60 个细调键 |
| 第二层 多设备并行 | 有哪些设备（各种列表）、怎么编队、怎么同时下发 | **几乎没有开关**：只有 1 个并发上限（默认 8，未登记）；其余是代码里一直在的机制 |
| 共用底座 NATS | 消息总线 | `GALAXY_NATS_ENABLED`、`GALAXY_NATS_URL` |
| 第三层 任务派发与分配 | 一个任务交给谁、走哪条路、怎么防重、重启怎么续 | 几个已内置的保护 + 任务状态落盘（默认开） |
| 第四层 NATS Agent | 主脑选 worker、worker 执行并回传 | `GALAXY_MASTER_BRAIN_ENABLED`（代码里自称「多设备总开关」，默认关） |

## 二、一个任务怎么走完

1. **入口**：对话、REST（`/api/v1/devices/{id}/command`、`/devices/parallel`、`/devices/cross-device`）等都归一成一个
   `TaskEnvelope`，交给 `CommandRouter.route_envelope()`。**系统级的事都在这里做**：权限（ACL）、生命周期状态、审计、trace。
2. **就绪与目标校验**：`unified_dispatch_readiness_gate`（派发前的唯一权威）、`target_device_validator`、
   `device_participation`（参与度 / 就绪，过滤掉不合格的设备）。
3. **按信封里的 `executor_target_type` 分三条路**（`core/schemas/remote_execution.py`）：

   | 目标类型 | 走哪 | 说明 |
   |---|---|---|
   | `local` | `_execute_command()` | 在本机运行时直接执行 |
   | `android_device` / `node_service` | `_route_cross_device_envelope()` → 网关 `DeviceRouter` | 经设备网关（WebSocket / AIP）下发到手机、手表、别的电脑或内部服务节点。**跨设备 / 多设备并行走这条** |
   | `go_worker` | `_route_worker_envelope()` → `MasterBrain` | 经 NATS 派给 worker。**主脑 / NATS Agent 走这条**；主脑没开时直接返回 `WORKER_DISPATCH_UNAVAILABLE` |

4. **多设备并行**：
   - `POST /api/v1/devices/parallel` 把一批命令归一成一个顶层信封，`CommandRouter` 扇出成每台设备一个子信封；
   - `DeviceRouter`（规范的唯一分发器）**有界并发**下发（`GALAXY_MULTI_DEVICE_DISPATCH_LIMIT`，默认 8），每一路一个子 span；
   - `SwarmCoordinator`（多设备编排层，在 CommandRouter 之上）先用 `DeviceScoringEngine` 选设备、生成 `OrchestrationPlan`，
     再并发分发；目标是实体设备时强制两步走：先 `agent_deploy`（推 `AgentManifest`）、成功后再 `agent_execute`。
5. **主脑这条路**（`go_worker`）：`MasterBrain.dispatch_task` → ACL 校验 → 选 worker（显式指定 > 按负载 / 设备类型匹配）→
   发 `task dispatch` 到 NATS → worker 执行（`core.node_invocation.invoke_node`）→ `task result` 回到主脑 → 回流。
6. **防重与续跑**：`durable_dispatch_idempotency`（落盘的派发幂等，崩溃前已派发的不二次触发副作用）；
   任务图检查点（`GALAXY_DURABLE_EXEC`，默认开，落 `GALAXY_DATA_DIR`），重启后只重派没做完的。
7. **结果**：`cross_device_result_surface` 收口，`multi_device_truth_convergence` 收敛真相；没收口的进隔离队列
   （`/api/v1/results/isolated`）。

## 三、NATS 这一层具体是什么

- **总线**：`core/nats_bus.py` 的 `NATSBus`（JetStream）。内置 `nats-server` 由 `core/nats_server.py` 拉起；连不上时**降级成进程内总线**
  （同进程 publish / subscribe 语义保留，没有网络）。
- **七条流**（`core/nats_subjects.py`，主题与流的唯一定义处）：`GALAXY_TASKS`、`GALAXY_MCP`、`GALAXY_EVENTS`、`GALAXY_DEVICE`、
  `GALAXY_CAPABILITY`、`GALAXY_PRESENCE`、`GALAXY_AUDIT`。主题平面：task、device、presence、capability、audit、workers（旧）、mcp。
  **task 主题单数（规范面）与复数（既有运转面）并存**，订阅侧两个都订。
- **Agent 有两种**：外部的 Go worker；本仓的 Python `WorkerRuntime`（订阅 `galaxy.tasks.dispatch.{worker_id}` → 规范执行器 → 回传）。
  内部节点用 `NodeHeartbeatSender` 以 worker 身份注册并定期心跳（`galaxy.workers.register` / `heartbeat`）。
- **主脑 `MasterBrain`**：worker 拓扑（注册 / 心跳 / 剔除）、任务派发、负载均衡、可选 Temporal 工作流、缩放监控；
  状态落盘（`GALAXY_MASTER_BRAIN_STATE_PATH`）。
- **启动**：`GALAXY_MASTER_BRAIN_ENABLED` 一开，启动序列做三件事 —— ① 起 `MasterBrain`（连 NATS、订阅结果与 worker 生命周期）；
  ② 起 worker 消费循环；③ 订阅「MCP over NATS」的网关一端（`galaxy.mcp.calls`）。全部 best-effort，失败不阻断单机启动；
  默认关时整段跳过。**运行中**还可以在面板 Mesh 区手动启停 worker（`GET /api/v1/mesh/worker`、`POST /api/v1/mesh/worker/toggle`），不用重启。
- **`NATSExecutor`**（命令经 NATS 派发 + 回退本机，`core/command_router.py`）：类和单例都在，但**我没有搜到启动序列把它设成 CommandRouter 的执行器**
  （`set_executor` 只有 `startup.py`、`routes/command.py` 两处，装的都不是它），只有可观测接口读它的统计。

## 四、配置键（实时登记表 + 代码里读到的环境变量）

「登记」= 在 `CONFIG_SCHEMA` 里；**未登记**的只能改 `.env` / 环境变量，面板「全部设置」里根本没有。
「生效」写**重启**的，是从读取位置核实过「改了要重启才生效」的（见 `core/routes/config_restart.py`）。
「整档按钮」是面板底部的整档开关认领了它（`core/routes/config_bundles.py`）。

<!-- tables:start -->
### 第一层 跨设备（通路：能发现、能认识、能传话）

**总闸与运行模式**

| 键 | 默认 | 登记 | 面板 | 整档按钮 | 生效 |
|---|---|---|---|---|---|
| `GALAXY_CROSS_DEVICE_ENABLED` | 关 | 是 | 留在面板 | 跨设备 | 重启 |
| `GALAXY_SYSTEM_MODE` | desktop-local | 是 | 全部设置 | — |  |

**发现与接入**

| 键 | 默认 | 登记 | 面板 | 整档按钮 | 生效 |
|---|---|---|---|---|---|
| `GALAXY_LAN_DISCOVERY` | 开 | 是 | 并进按钮 | 跨设备（成员） | 重启 |
| `GALAXY_LAN_DISCOVERY_TYPES` | 空 | 是 | 全部设置 | 跨设备 |  |
| `GALAXY_MDNS` | 开 | 是 | 并进按钮 | 跨设备（成员） | 重启 |
| `GALAXY_ONBOARDING_ENABLED` | 开 | 是 | 并进按钮 | 跨设备（成员） |  |
| `GALAXY_ONBOARDING_AUTO` | none | 是 | 全部设置 | — |  |
| `GALAXY_ONBOARDING_SSDP` | 开 | 是 | 内置 | — |  |
| `GALAXY_ONBOARDING_BLUETOOTH` | 开 | 是 | 内置 | — |  |
| `GALAXY_ONBOARDING_CAN` | 开 | 是 | 内置 | — |  |
| `GALAXY_ONBOARDING_SERIAL` | 开 | 是 | 内置 | — |  |
| `GALAXY_ONBOARDING_CAN_LISTEN_S` | 1.0 | 是 | 全部设置 | — |  |
| `GALAXY_ONBOARDING_SCAN_INTERVAL_S` | 60 | 是 | 全部设置 | — |  |
| `GALAXY_ONBOARDING_STATE_DIR` | 空 | 是 | 全部设置 | — |  |
| `GALAXY_MESH_DISCOVERY_TIMEOUT` | 2.0 | 是 | 全部设置 | 跨设备 |  |
| `GALAXY_MESH_NODE_ID` | — | **未登记**（只能改 .env） | — | — | — |
| `GALAXY_MESH_PORT` | — | **未登记**（只能改 .env） | — | — | — |
| `GALAXY_DEVICE_NAME` | 空 | 是 | 全部设置 | 跨设备 |  |
| `GALAXY_DEVICE_TYPE` | 空 | 是 | 全部设置 | 跨设备 |  |

**信任与准入**

| 键 | 默认 | 登记 | 面板 | 整档按钮 | 生效 |
|---|---|---|---|---|---|
| `GALAXY_REQUIRE_DEVICE_APPROVAL` | 关 | 是 | 运维 | — |  |
| `GALAXY_PEER_DEFAULT_TRUST` | ask | 是 | 全部设置 | — |  |
| `GALAXY_PEER_TRUST_PATH` | 空 | 是 | 全部设置 | — |  |
| `GALAXY_MESH_SECRET` | 空 | 是 | 全部设置 | 跨设备 |  |
| `GALAXY_DEVICE_TOKEN_STORE` | 空 | 是 | 全部设置 | 跨设备 |  |
| `GALAXY_DEVICE_TOKEN_RETENTION_DAYS` | 30 | 是 | 全部设置 | 跨设备 |  |
| `GALAXY_DEVICE_TOKEN_MAX_RECORDS` | 512 | 是 | 全部设置 | 跨设备 |  |

**传输通道（不含 NATS）**

| 键 | 默认 | 登记 | 面板 | 整档按钮 | 生效 |
|---|---|---|---|---|---|
| `GALAXY_TS_FUNNEL` | 关 | 是 | 留在面板 | 跨设备 | 重启 |
| `GALAXY_TS_ADVERTISE_RELAY` | 开 | 是 | 内置 | 跨设备 |  |
| `GALAXY_TAILSCALE_CHECK_INTERVAL` | 60 | 是 | 全部设置 | — |  |
| `GALAXY_TAILSCALE_ENABLED` | — | **未登记**（只能改 .env） | — | — | — |
| `GALAXY_TAILSCALE_HOST` | — | **未登记**（只能改 .env） | — | — | — |
| `GALAXY_TAILSCALE_TAG` | — | **未登记**（只能改 .env） | — | — | — |
| `GALAXY_HEADSCALE_URL` | 空 | 是 | 全部设置 | — |  |
| `GALAXY_HEADSCALE_API_KEY` | 空 | 是 | 全部设置 | — |  |
| `GALAXY_HEADSCALE_USER` | galaxy | 是 | 全部设置 | — |  |
| `GALAXY_HEADSCALE_AUTOJOIN` | 开 | 是 | 内置 | — |  |
| `GALAXY_TURN_URLS` | 空 | 是 | 全部设置 | 跨设备 |  |
| `GALAXY_TURN_USERNAME` | — | **未登记**（只能改 .env） | — | — | — |
| `GALAXY_TURN_CREDENTIAL` | — | **未登记**（只能改 .env） | — | — | — |
| `GALAXY_SIGNALING_TIMEOUT_S` | 空 | 是 | 全部设置 | 跨设备 |  |
| `GALAXY_ENABLE_WEBRTC_DATA_CHANNEL` | 关 | 是 | 留在面板 | 跨设备 | 重启 |
| `GALAXY_ENABLE_WEBRTC` | — | **未登记**（只能改 .env） | — | — | — |
| `GALAXY_WEBRTC_TASK_READY_TIMEOUT_S` | — | **未登记**（只能改 .env） | — | — | — |
| `GALAXY_USE_GATEWAY_FOR_WEBRTC` | — | **未登记**（只能改 .env） | — | — | — |
| `GALAXY_TRANSPORT_ADAPTIVE` | 开 | 是 | 内置 | — |  |
| `GALAXY_TRANSPORT_BULK_BYTES` | 65536 | 是 | 全部设置 | — |  |
| `GALAXY_TRANSPORT_PRIORITY` | — | **未登记**（只能改 .env） | — | — | — |
| `GALAXY_ANDROID_WS_ENABLED` | 关 | 是 | 运维 | 跨设备 |  |
| `ANDROID_DEVICE_SNAPSHOT_TTL_SECONDS` | 300 | 是 | 全部设置 | 跨设备 |  |
| `ANDROID_DEVICE_STATE_STORE_PATH` | 空 | 是 | 全部设置 | 跨设备 |  |

**别的设备 / 实例 / 家居接入**

| 键 | 默认 | 登记 | 面板 | 整档按钮 | 生效 |
|---|---|---|---|---|---|
| `GALAXY_REMOTE_DESKTOP` | 关 | 是 | 留在面板 | — | 重启 |
| `GALAXY_VNC_PORT` | 5900 | 是 | 全部设置 | — |  |
| `GALAXY_VNC_CMD` | 空 | 是 | 全部设置 | — |  |
| `FEDERATION_ENABLED` | 关 | 是 | 留在面板 | 跨设备 | 重启 |
| `FEDERATION_PEERS` | 空 | 是 | 全部设置 | 跨设备 |  |
| `FEDERATION_LOCAL_HOST` | 空 | 是 | 全部设置 | 跨设备 |  |
| `FEDERATION_HEARTBEAT_INTERVAL` | 10 | 是 | 全部设置 | 跨设备 |  |
| `FEDERATION_INSTANCE_ID` | — | **未登记**（只能改 .env） | — | — | — |
| `FEDERATION_MIN_HEARTBEAT_INTERVAL` | — | **未登记**（只能改 .env） | — | — | — |
| `FEDERATION_OFFLINE_THRESHOLD` | — | **未登记**（只能改 .env） | — | — | — |
| `GALAXY_HA_BRIDGE` | 开 | 是 | 内置 | — |  |
| `HOME_ASSISTANT_URL` | 空 | 是 | 全部设置 | — |  |
| `HOME_ASSISTANT_TOKEN` | 空 | 是 | 全部设置 | — |  |


### 第二层 多设备并行（设备清单、编队、并行）

**并行与健康**

| 键 | 默认 | 登记 | 面板 | 整档按钮 | 生效 |
|---|---|---|---|---|---|
| `GALAXY_MULTI_DEVICE_DISPATCH_LIMIT` | — | **未登记**（只能改 .env） | — | — | — |
| `GALAXY_NODE_HEALTH_RETRIES` | 空 | 是 | 全部设置 | — |  |
| `GALAXY_SLO_HEARTBEAT_WINDOW` | 60 | 是 | 全部设置 | — |  |
| `GALAXY_ENABLE_LEGACY_MULTIDEVICE` | — | **未登记**（只能改 .env） | — | — | — |


### 共用底座 NATS 消息总线（第一层的设备 / 在场 / 能力平面，第四层的任务 / worker 平面都走它）

**总线**

| 键 | 默认 | 登记 | 面板 | 整档按钮 | 生效 |
|---|---|---|---|---|---|
| `GALAXY_NATS_ENABLED` | 开 | 是 | 并进按钮 | 跨设备（成员） | 重启 |
| `GALAXY_NATS_URL` | nats://localho | 是 | 全部设置 | 跨设备 |  |
| `GALAXY_FABRIC_STRICT` | 关 | 是 | 运维 | 跨设备 |  |


### 第三层 任务派发与分配

**派发**

| 键 | 默认 | 登记 | 面板 | 整档按钮 | 生效 |
|---|---|---|---|---|---|
| `GALAXY_DISPATCH_IDEMPOTENCY` | 开 | 是 | 内置 | — |  |
| `GALAXY_CANONICAL_DISPATCH_AUTHORITY_MODE` | strict | 是 | 全部设置 | — |  |
| `GALAXY_NATS_EXECUTOR_FALLBACK` | sync | 是 | 全部设置 | 跨设备 |  |
| `GALAXY_NATS_EXECUTOR_TIMEOUT` | 30 | 是 | 全部设置 | 跨设备 |  |
| `GALAXY_DURABLE_EXEC` | 开 | 是 | 内置 | — | 重启 |


### 第四层 NATS Agent（主脑与 worker）

**主脑与 worker**

| 键 | 默认 | 登记 | 面板 | 整档按钮 | 生效 |
|---|---|---|---|---|---|
| `GALAXY_MASTER_BRAIN_ENABLED` | 关 | 是 | 留在面板 | 跨设备 | 重启 |
| `GALAXY_MASTER_BRAIN_STATE_PATH` | 空 | 是 | 全部设置 | 跨设备 |  |
| `GALAXY_MASTER_BRAIN_SCALING_REEVAL_INTERVAL_S` | 300 | 是 | 全部设置 | 跨设备 |  |
| `GALAXY_WORKER_ID` | — | **未登记**（只能改 .env） | — | — | — |
| `GALAXY_WORKER_VERSION` | — | **未登记**（只能改 .env） | — | — | — |
| `GALAXY_HEARTBEAT_INTERVAL` | 5 | 是 | 全部设置 | 跨设备 |  |

共 81 个键，其中 **18** 个未登记。
<!-- tables:end -->

## 五、模块、接口、面板入口

**模块**

- 第一层 跨设备：`galaxy_gateway/cross_device_switch.py`（网关的唯一开关）、`core/system_mode.py`（运行模式权威）、`core/system_orchestrator.py`（启动时解析模式）、
  `core/desktop_presence_runtime.py`（桌面在场的跨设备模式）、`core/android_mode_gate_policy.py`；发现与接入 `core/lan_discovery.py`、`core/device_onboarding/`、`core/mesh/`、`core/mesh_coordinator.py`；
  信任与准入 `core/peer_trust.py`、`core/participant_admission.py`、`core/capability_token.py`；传输 `core/aip_transport.py`、`core/tailscale_manager.py`、`core/headscale_join.py`、
  `core/proxy_relay.py`、`galaxy_gateway/smart_transport_router.py`、`galaxy_gateway/webrtc_proxy.py`；别的实例与设备 `core/galaxy_federation.py`、`core/remote_desktop.py`、`core/ha_bridge.py`。
- 第二层 多设备并行：设备清单 `core/device_registry.py`、`core/unified/device_manager.py`（UDM，设备状态的权威）、`core/device_pool_manager.py`（调度 / 健康 / 权重）；
  编队与选择 `core/device_formation/`、`core/device_selection/`、`core/cross_device_policy/`、`core/device_readiness.py`、`core/device_participation.py`、`core/mesh_participation_summary.py`、
  `core/network_topology_runtime.py`；编排 `core/swarm_coordinator.py`、`galaxy_gateway/cross_device_coordinator.py`、`galaxy_gateway/wake_router.py`（唤醒排名）；
  内部服务节点 `nodes/Node_71_MultiDeviceCoordination`。
- 共用底座：`core/nats_bus.py`、`core/nats_subjects.py`、`core/nats_server.py`、`core/nats_posture.py`、`core/aip_v3_nats_adapter.py`、`galaxy_gateway/gateway_nats_adapter.py`、`core/mesh_nats_fusion.py`。
- 第三层 任务派发与分配：`core/command_router.py`、`galaxy_gateway/device_router.py`、`core/unified_dispatch_readiness_gate.py`、`core/canonical_task_dispatch_chain.py`、
  `core/canonical_dispatch_slot_authority.py`、`core/durable_dispatch_idempotency.py`、`core/task_graph_runtime.py`、`core/task_graph_checkpoint.py`、`core/task_graph_resume_dispatch.py`、
  `core/cross_device_execution_chain.py`、`core/cross_device_dispatch_boundary.py`、`core/cross_device_result_surface.py`、`core/multi_device_*`（治理、真相收敛、控制完整性、runtime harness）。
- 第四层 NATS Agent：`core/master_brain.py`、`core/worker_runtime.py`、`core/nats_heartbeat.py`、`core/device_worker_convergence.py`、`core/temporal_workflows.py`、`core/mcp_gateway.py`、`core/acl.py`。

**接口**

| 层 | 接口 |
|---|---|
| 第一层 | `/api/v1/pair/*`（配对、信任、对端、tailnet）、`/api/v1/participants/*`、`/api/v1/devices/register`、`/devices/discover`、`/devices/discover-active`、`/api/v1/federation/*`、`/api/remote-desktop/status`、`/enable`、`/disable` |
| 第二层 | `/api/v1/devices`、`/devices/{id}`、`/devices/{id}/telemetry`、`/devices/parallel`、`/api/v1/mesh/send`、`/mesh/peers`、`/mesh/topology`、`/mesh/stats`、`/mesh/probe` |
| 第三层 | `/api/v1/devices/{id}/command`、`/devices/cross-device`、`/devices/parallel`、`/api/v1/results/isolated` |
| 第四层 | `/api/v1/mesh/worker`、`/api/v1/mesh/worker/toggle`、可观测接口里的主脑 / worker 拓扑 |

**面板入口**：底部「跨设备」整档按钮（主键 `GALAXY_CROSS_DEVICE_ENABLED`，连带局域网发现 / mDNS / 设备接入平面 / 消息总线 4 个成员）；
「全部设置」里单列的有主脑、联邦、WebRTC 数据通道、Tailscale Funnel、远程桌面、模型下载镜像，加一批数值 / 文本键；
Mesh 区的 worker 启停与对端清单；设备清单走面板 feed（WebSocket 推送）。

**已有的相关文档**：`CROSS_DEVICE_CONTROL_PLANE_ARCHITECTURE.md`（第一、二层的九层控制面）、`CROSS_DEVICE_EXECUTION_CHAIN.md`、`CROSS_DEVICE_ROLE_ROUTING_POLICY.md`、
`DEVICE_FORMATION_AND_MULTI_DEVICE_GROUPS.md`、`NATS_CONTROL_PLANE.md`、`MESH_MEMBERSHIP_CONTRACT.md`、`MULTI_DEVICE_ARCHITECTURE_ANALYSIS.md`、`MULTI_DEVICE_RUNTIME_MATURITY.md`。

## 六、查出来的不一致和风险（没有动）

**会悄悄改变行为的**

1. **点一次「保存设置」，下次启动运行模式会被推成跨设备。** 「保存设置」会把登记表里每个**非空**默认值整体写进 `.env`；`GALAXY_NATS_URL` 登记的默认是
   `nats://localhost:4222`（非空），而 `.env.example` 特意写成空（`GALAXY_NATS_URL=`）。启动序列第 2 阶段（`core/system_orchestrator.py`）把「`GALAXY_NATS_URL` 非空」
   当成跨设备的信号，**即使 `GALAXY_CROSS_DEVICE_ENABLED=false` 也一样**；`core/system_mode.py` 也把它当成「NATS 显式启用」。（按代码读，没有实测。）
   修法很小：登记默认改成空、说明里写「缺省 `nats://localhost:4222`」。
2. **7 个数字 / 取值的登记默认与代码默认不一致**，保存设置会用登记值覆盖代码默认：

   | 键 | 登记 | 代码 | 位置 |
   |---|---|---|---|
   | `GALAXY_MASTER_BRAIN_SCALING_REEVAL_INTERVAL_S` | 300 | 15 | `core/master_brain.py` |
   | `GALAXY_HEARTBEAT_INTERVAL` | 5 | 10（该文件的说明里也写 10） | `core/nats_heartbeat.py` |
   | `ANDROID_DEVICE_SNAPSHOT_TTL_SECONDS` | 300 | 90 | `core/android_device_state_store.py` |
   | `FEDERATION_HEARTBEAT_INTERVAL` | 10 | 15 | `core/galaxy_federation.py` |
   | `GALAXY_SLO_HEARTBEAT_WINDOW` | 60 | 200 | `core/slo_metrics.py` |
   | `GALAXY_TAILSCALE_CHECK_INTERVAL` | 60 | 30 | `core/tailscale_manager.py` |
   | `GALAXY_HEADSCALE_USER` | galaxy | 空 | `core/headscale_join.py` |

3. **「NATS 缺省开不开」三处各说各话**：`core/system_mode.py`（`GALAXY_NATS_ENABLED` 没写时：有显式 URL 或跨设备模式才开，本机模式关）；
   `core/nats_server.py` 与启动序列（没写 `false` 就拉 `nats-server`，缺省开）；登记表（`true`）。默认状态下「跨设备关、总线开」并存，启动日志里
   `cross_device=False nats_enabled=True` 并排出现就是它。

**文档 / 代码对不上的**

4. **`GALAXY_NATS_EXECUTOR_FALLBACK` 登记成 `sync / async / reject` 三选一，代码只把它当开关读**（不是 `false` / `0` 就算开）：选 `reject` 实际是开着回退，选项的意思相反；
   而读它的 `NATSExecutor` 我没有搜到被装成执行器（见第三节）。
5. **主脑状态文件缺省落在系统临时目录**（`GALAXY_MASTER_BRAIN_STATE_PATH` 没设时 `tempfile.gettempdir()`），不认 `GALAXY_DATA_DIR`（本仓所有持久化点的约定）；重启后可能读不到。
6. **核心的 `/devices/parallel`、`/devices/cross-device` 与 `core/command_router.py` 里没搜到对跨设备开关的检查**；开关只被网关的 `DeviceRouter`（两处）、`AgentBridge`、入口分流、安卓模式闸门、
   运行模式解析、桌面在场的跨设备模式查。开关关着时核心这两个入口是否照收请求，需要实测，不能只看开关。
7. **`galaxy_gateway/cross_device_switch.py` 文件开头的说明过期**：写着「默认开、缺省视为开」，函数实际缺省关、只认 `1/true/yes`。
8. **`CROSS_DEVICE_CONTROL_PLANE_ARCHITECTURE.md` 的第 6 层写的 `core/cross_device_candidates.py` 与 `resolve_cross_device_candidates()` 全仓不存在。**

**范围与口径**

9. **18 个相关环境变量只在代码里读、没登记**（上表标「未登记」）：联邦 3、TURN 凭据 2、Tailscale 3、WebRTC 3、传输优先级 1、网状网络节点号与端口 2、`GALAXY_MULTI_DEVICE_DISPATCH_LIMIT`、
   `GALAXY_ENABLE_LEGACY_MULTIDEVICE`（旧的多设备层，默认禁用）、worker 的 id 与版本。
10. **「多设备总开关」叫法不一**：`startup.py`、`worker_runtime.py` 的注释把 `GALAXY_MASTER_BRAIN_ENABLED` 叫「多设备总开关」，而面板上叫「跨设备」的是 `GALAXY_CROSS_DEVICE_ENABLED`；
    两者在代码里互相独立（主脑不检查跨设备开关）。
11. **「跨设备」整档按钮的 `owns` 里有 `NODE_*_URL`**（内部服务节点地址），不是设备，归属存疑。
12. **`GALAXY_DURABLE_EXEC` 的代码说明写着「只在跨设备分布式编排下才有意义」**，现在已默认开（所有者的决定）；它在这个模块里属于第三层（重启后重派没做完的任务）。

## 七、先放在这儿的：怎么组成一个按钮（等所有者定）

**组法 A — 用现有机制，不新增任何键**：「跨设备」按钮保持（主键 `GALAXY_CROSS_DEVICE_ENABLED`，成员就是现在这 4 个）；第二、三层本来就没有开关，跟着第一层走；
第四层主脑是默认关的 opt-in，按钮「开」不能替人打开（会拉起常驻的主脑与 worker、耗资源），所以仍是「全部设置」里一个独立开关，旁边写明「需要消息总线」。
优点：零新增、零行为变化；缺点：主脑没有并进来。

**组法 B — 一个「多机模式」四档牌（像「自主」那样，新增 1 个选择型键）**：`GALAXY_MULTI_MACHINE = off | cross_device | multi_device | master_brain`，逐级包含，每一档写哪些现有键由登记表一处定义：

| 档 | 写什么（现有键） | 备注 |
|---|---|---|
| off | 跨设备 false，4 个成员 false，主脑 false | 只在本机跑 |
| cross_device | 跨设备 true，4 个成员回默认；主脑 false | 设备能被发现、配对、收任务 |
| multi_device | 同上；第二层没有现成的键 | 要让这一档与上一档**真的不同**，得给并行 / 分发加一个闸（新增代码）；需要所有者说这一档要管住什么 |
| master_brain | 在上一档基础上主脑 true | 需要消息总线；开了拉起主脑、worker 与 MCP over NATS |

**无论选哪种，先要定的两件事**：
1. 总开关关着时，核心的 `/devices/parallel`、`/devices/cross-device` 要不要直接拒绝（现在没搜到检查，见第六节 6）；
2. 第六节 1 和 2（保存设置会改变行为的）要不要先修 —— 它们和「怎么组」无关，但都会让「保存设置」悄悄改变多机行为。
