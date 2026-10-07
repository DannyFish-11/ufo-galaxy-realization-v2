# 多机模式（跨设备 · 多设备并行 · 任务派发与分配 · NATS Agent）

> **状态：2026-10-05 定义并记录；2026-10-07 按所有者的决定收口：模式只有一条规则、一个出处（见「零、两个模式」），第六节里
> 会悄悄改变行为的几条已修。**
> 所有者的设计：把「让这台电脑加上别的设备 / 别的机器像一个整体干活」这一整块，作为**一个模块**来看 ——
> 跨设备是前提，多设备并行建立在它之上，再往上是 NATS 上的 Agent（主脑与 worker）和任务的派发与分配。
> 这份文档回答：这个模块**由哪几层组成、一个任务怎么走完、每一层有哪些配置键 / 模块 / 接口、现在哪里不一致**。
> 配置键表由 `python scripts/gen_multi_machine_map.py --write` 从实时登记表生成；其余是 2026-10-05 对着代码查的快照，
> 没有查到的地方明说，没有实测过的地方写「按代码读」。

## 零、两个模式（先看这一节）

系统只有两个模式（`core/system_mode.py`，设置里的 `GALAXY_SYSTEM_MODE`）：

- **本地模式**（`desktop-local`，默认）：只用这台电脑。
- **跨设备模式**（`desktop-cross-device`）：这台电脑加上别的设备一起干活。**本文说的整个多机模式 —— 多设备并行、任务派发与分配、
  主脑、NATS Agent —— 都是跨设备模式里面的功能，不是另一个模式。**

「混合」**不是模式**，是一个请求的走法：请求只在本机做（`local`）、只交给别的设备（`cross_device`）、或本机做一部分同时别的设备也做
（`hybrid`）。这是跨设备模式开了之后系统自动判断的（`resolve_entry_mode`），不用设置；本地模式下一律是 `local`。
另有 `core/hybrid_executor.py` 的「混合执行」（A2A → GUI → VLM 三级降级，在**一台设备内部**），与多设备无关，别混。

**「现在是哪个模式」只有一条规则**（`core.system_mode.cross_device_requested`）：`GALAXY_CROSS_DEVICE_ENABLED` 为真，**或**
`GALAXY_SYSTEM_MODE=desktop-cross-device`，任一即是跨设备模式，否则本地模式。`local` / `false` 是出厂默认（`.env.example` 带着、「保存设置」会写），
不是一次选择，盖不过别处明确的选择。网关开关、启动流程、桌面在场、启动自检、`/api/v1/system/mode-status` 都调这一个函数，不再各自推导。
面板上切换模式的只有「跨设备」这一个按钮，它同时写这两个键（`config_bundles.py` 的 `mirrors`），「运行模式」下拉框不再列在面板上。
`GALAXY_NATS_URL` **不参与**：它只说总线在哪；本地模式下把它指向别的机器，启动会说一句「要用别的设备请打开跨设备」，不替人切模式。

**本地模式不往别的设备下发**：每一个「把命令送到另一台设备」的入口（并行 / 单设备命令 REST、命令路由的设备执行桥、网关的单设备下发、智能体的 `devices__invoke`）
在本地模式下一律返回 `cross_device_disabled`，并告诉人 / 模型怎么办（打开「跨设备」；智能体可调 `devices__request_cross_device` 请用户同意）；设备仍可以配对、连上、出现在名册里。

**主脑只在跨设备模式里起**（`core.system_mode.master_brain_requested`）：主脑开关开着、却在本地模式 → 主脑与 worker 不起，启动日志说出原因；
`CommandRouter` 的 `go_worker` 路径此时返回 `WORKER_DISPATCH_UNAVAILABLE`，设备路径被网关 `DeviceRouter` 的两处入口拒绝（`cross_device_disabled`）。

**模型只能请求、不能决定**：本地模式下模型有一个工具 `devices__request_cross_device`，只会问人「要不要打开跨设备模式」；批准走设备接入已有的
人在环（问的那一回合不算数、只认人发起的回合、看人的原话、手表连着在手表上问），`GALAXY_ONBOARDING_AUTO=approve` 对它无效；批准后走面板按钮同一个写入函数，
要**重启**才完全生效。见 `core/device_onboarding/mode_request.py`。

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
| 第四层 NATS Agent | 主脑选 worker、worker 执行并回传 | `GALAXY_MASTER_BRAIN_ENABLED`（默认关；要在跨设备模式里才起） |

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
| `GALAXY_SYSTEM_MODE` | desktop-local | 是 | 全部设置 | 跨设备 | 重启 |

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
| `GALAXY_TAILSCALE_CHECK_INTERVAL` | 30 | 是 | 全部设置 | — |  |
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
| `ANDROID_DEVICE_SNAPSHOT_TTL_SECONDS` | 90 | 是 | 全部设置 | 跨设备 |  |
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
| `FEDERATION_HEARTBEAT_INTERVAL` | 15 | 是 | 全部设置 | 跨设备 |  |
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
| `GALAXY_SLO_HEARTBEAT_WINDOW` | 200 | 是 | 全部设置 | — |  |
| `GALAXY_ENABLE_LEGACY_MULTIDEVICE` | — | **未登记**（只能改 .env） | — | — | — |


### 共用底座 NATS 消息总线（第一层的设备 / 在场 / 能力平面，第四层的任务 / worker 平面都走它）

**总线**

| 键 | 默认 | 登记 | 面板 | 整档按钮 | 生效 |
|---|---|---|---|---|---|
| `GALAXY_NATS_ENABLED` | 开 | 是 | 并进按钮 | 跨设备（成员） | 重启 |
| `GALAXY_NATS_URL` | 空 | 是 | 全部设置 | 跨设备 |  |
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
| `GALAXY_MASTER_BRAIN_SCALING_REEVAL_INTERVAL_S` | 15 | 是 | 全部设置 | 跨设备 |  |
| `GALAXY_WORKER_ID` | — | **未登记**（只能改 .env） | — | — | — |
| `GALAXY_WORKER_VERSION` | — | **未登记**（只能改 .env） | — | — | — |
| `GALAXY_HEARTBEAT_INTERVAL` | 10 | 是 | 全部设置 | 跨设备 |  |

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

## 六、查出来的不一致和风险

**已修（2026-10-07）**

1. ~~点一次「保存设置」，下次启动运行模式会被推成跨设备。~~ 原因：`GALAXY_NATS_URL` 登记默认非空（`nats://localhost:4222`），保存写进 `.env`，启动序列又把
   「该地址非空」当成跨设备信号；而且就算登记默认改空，内嵌 NATS 起来后进程自己也会设这个变量，下次保存又写回。现在：登记默认改空，**启动流程不再用地址判模式**
   （模式只看 `cross_device_requested`），地址指向别的机器而没开跨设备时只是说出来。
2. ~~7 个数字 / 取值的登记默认与代码默认不一致。~~ 实际核对是 **6 个**（`GALAXY_HEADSCALE_USER` 代码写的是 `getenv(…, "").strip() or "galaxy"`，有效默认就是 `galaxy`，与登记一致，是清点时记错）。
   已对齐到代码：

   | 键 | 登记（原） | 登记（现）= 代码 |
   |---|---|---|
   | `GALAXY_MASTER_BRAIN_SCALING_REEVAL_INTERVAL_S` | 300 | 15 |
   | `GALAXY_HEARTBEAT_INTERVAL` | 5 | 10 |
   | `ANDROID_DEVICE_SNAPSHOT_TTL_SECONDS` | 300 | 90 |
   | `FEDERATION_HEARTBEAT_INTERVAL` | 10 | 15 |
   | `GALAXY_SLO_HEARTBEAT_WINDOW`（单位是「条」，不是秒） | 60 | 200 |
   | `GALAXY_TAILSCALE_CHECK_INTERVAL` | 60 | 30 |

   `tests/test_multi_machine_registry_defaults_match_the_code.py` 从读取点的源码里读默认值，与登记表逐个核对。
3. ~~核心的 `/devices/parallel`、`/devices/cross-device` 与 `CommandRouter` 没查跨设备开关。~~ **这一条曾被我误判成「下层已经拦了、不需要查」，真机实测推翻了它**：
   起真服务器、用真的设备客户端（`device_client`，真 WebSocket，真配对）连上两台设备，本地模式下 `/devices/parallel` 把命令送到了两台设备并执行 ——
   并行拆出的每台设备走命令路由的设备执行桥（`_command_node_executor`），直接 `send_to_device`；网关 `DeviceRouter` 只在「分析出要跨设备」与多设备协同两处查开关，
   显式指定一台目标的单设备下发（`dispatch_task`）也不查。现在 **五处入口统一拒绝**（`core.system_mode.cross_device_refusal`，错误码与网关同为 `cross_device_disabled`，并告诉人 / 模型怎么办）：
   `DeviceRouter.dispatch_task`、命令路由的设备执行桥、`POST /api/v1/devices/{id}/command`、智能体的 `devices__invoke`（讲 AIP 的设备；桥接的智能家居与驱动节点不在此列）、
   以及它们的上游 `/devices/parallel`、`/devices/cross-device`（经前两处）。`go_worker` 路径在主脑没起时返回 `WORKER_DISPATCH_UNAVAILABLE`。
   按钮一翻，下一条命令即放行（网关路由随时读开关，不用重启）。`tests/test_local_mode_does_not_reach_other_devices.py`、`test_local_mode_never_sends_commands_to_other_devices.py`、
   `test_master_brain_runs_only_in_cross_device_mode.py` 钉住。
4. ~~`galaxy_gateway/cross_device_switch.py` 文件开头的说明过期（写「默认开」）。~~ 已改成实际行为（缺省关、读 `cross_device_requested`）。
5. ~~「多设备总开关」叫法不一、主脑不检查跨设备开关。~~ 主脑现在要在跨设备模式里才起；面板上叫「跨设备」的就是模式的切换点。
6. ~~`GALAXY_NATS_EXECUTOR_FALLBACK` 登记成 `sync / async / reject` 三选一，代码只把它当开关读（选 `reject` 实际是开着回退）。~~ 现在 `reject`（以及 `false` / `0`）真的不退回、`sync`（以及 `true` / 空）退回本机执行；
   登记表只留代码分得清的两项（`sync`、`reject`）。`NATSExecutor` 本身仍没有被装成命令路由的执行器（只有可观测接口会读它的统计），这是产品决定，没有动。
7. ~~主脑状态文件缺省落在系统临时目录。~~ 现在缺省落 `$GALAXY_DATA_DIR/galaxy_master_brain_state.json`（`core/master_brain_state.py`；显式的 `GALAXY_MASTER_BRAIN_STATE_PATH` 仍优先）。
   旧位置（系统临时目录）的文件不再读取。
   `tests/test_the_two_leftover_multi_machine_defects_stay_fixed.py` 钉住这两条。

**还在、没有动的**

8. **「NATS 缺省开不开」三处各说各话**：`core/system_mode.py`（`GALAXY_NATS_ENABLED` 没写时：有显式 URL 或跨设备模式才开，本机模式关）；
   `core/nats_server.py` 与启动序列（没写 `false` 就拉 `nats-server`，缺省开）；登记表（`true`）。默认状态下「跨设备关、总线开」并存，启动日志里
   `cross_device=False nats_enabled=True` 并排出现就是它。它不再影响模式，只影响「本地模式下要不要白起一个进程内总线」。
9. **`CROSS_DEVICE_CONTROL_PLANE_ARCHITECTURE.md` 的第 6 层写的 `core/cross_device_candidates.py` 与 `resolve_cross_device_candidates()` 全仓不存在。**
10. **18 个相关环境变量只在代码里读、没登记**（上表标「未登记」）：联邦 3、TURN 凭据 2、Tailscale 3、WebRTC 3、传输优先级 1、网状网络节点号与端口 2、`GALAXY_MULTI_DEVICE_DISPATCH_LIMIT`、
   `GALAXY_ENABLE_LEGACY_MULTIDEVICE`（旧的多设备层，默认禁用）、worker 的 id 与版本。
11. **「跨设备」整档按钮的 `owns` 里有 `NODE_*_URL`**（内部服务节点地址），不是设备，归属存疑。
12. **`GALAXY_DURABLE_EXEC` 的代码说明写着「只在跨设备分布式编排下才有意义」**，现在已默认开（所有者的决定）；它在这个模块里属于第三层（重启后重派没做完的任务）。

## 七、怎么组成一个按钮（所有者的决定）

所有者的口径：**系统是两个模式，多机模式 = 跨设备模式的整体内容，「混合」是请求的走法。** 因此没有新增「多机模式四档牌」（原组法 B），也没有把主脑并进按钮（原组法 A 的口径）：

- 面板上切换的只有「跨设备」这一个按钮：关 = 本地模式，开 = 跨设备模式；它写主键、成员（发现 / mDNS / 设备接入 / NATS 总线）和模式名；
- 主脑仍是默认关的 opt-in（拉起常驻的主脑与 worker 有花费），独立一个开关，但要在跨设备模式里才起；
- 第二、三层（多设备并行、任务派发与分配）本来就没有开关，跟着跨设备模式走；
- 模型可以请求打开跨设备模式，批准只归人（见「零」）。
