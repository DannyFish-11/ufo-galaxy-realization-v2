# 多设备三块：跨设备 / 多设备并行与任务分发 / 主脑

> 2026-10-04 盘点。所有者的设计：**跨设备是多设备的前提**；多设备涵盖各种列表（设备清单、候选、对端、编队）；
> 总共三块 —— ① 跨设备、② 多设备并行与任务分发、③ 主脑。所有者准备把它们组成一个。
> 这份文档只回答「相关的东西都有哪些、各自在哪、现在是什么状态」，**不做合并**。配置键表由实时登记表生成；
> 模块、接口、读取位置是对着代码查的，没有查到的地方明说。

## 先说清楚的五件事

1. **三块里配置面最厚的是①，②和③几乎没有开关。**
   ① 跨设备有 60 多个键（发现、接入、信任、传输、别的设备与实例）；② 多设备并行与任务分发只有 1 个数量上限
   （`GALAXY_MULTI_DEVICE_DISPATCH_LIMIT`，默认 8，**没登记**）加几个已经内置的保护；③ 主脑 3 个键 + worker 的 2 个未登记变量。
   ② 的并行、分发、列表、编队、唤醒排名等是**代码里一直在的机制**，没有「开 / 关」这回事 —— 它们能不能被用到，取决于①。
2. **「跨设备是多设备的前提」在代码里只有一部分成立。** 开关 `GALAXY_CROSS_DEVICE_ENABLED` 实际被这些地方查：
   网关的 `DeviceRouter`（两处）、`AgentBridge`（一处）、入口分流、安卓模式闸门、系统运行模式解析、桌面在场的跨设备模式。
   但核心这边的 `POST /api/v1/devices/parallel` 与 `POST /api/v1/devices/cross-device`（并行 / 跨设备分发的 REST 入口）
   以及 `core/command_router.py` 里，**我没有搜到对这个开关的检查** —— 也就是说开关关着时，核心这边的这两个入口是否照样收请求，需要实测，
   不能只看开关。
3. **默认状态下「跨设备关、消息总线开」同时成立。** `GALAXY_CROSS_DEVICE_ENABLED` 缺省关，`GALAXY_NATS_ENABLED` 缺省（没设）算开、
   启动会去拉 `nats-server`。启动日志里 `cross_device=False nats_enabled=True` 并排出现就是这个。另外 **只要设了 `GALAXY_NATS_URL`，
   系统会推断为跨设备**（`system_orchestrator`、`system_mode` 各推断了一遍，逻辑各写一份）。
4. **③ 主脑与 ① 跨设备在代码里互相独立。** 主脑（`GALAXY_MASTER_BRAIN_ENABLED`）只管启动时拉起主脑与 NATS worker，不检查跨设备开关；
   它依赖消息总线。worker 在运行中还可以在面板 Mesh 区手动启停（`/api/v1/mesh/worker`、`/toggle`，不用重启）。
   `GALAXY_DURABLE_EXEC`（任务状态落盘与重启续跑）的代码说明写着「只在跨设备分布式编排下才有意义」，所以它在这个划分里属于②任务分发（续跑要重派）。
5. **`NODE_*_URL`（33、45、71、92、95、97 号节点的地址）现在被「跨设备」整档按钮认领，但它们是内部服务节点，不是设备。** 归属存疑，建议不放进这三块。

## 现在面板上这一块长什么样

- 底部「跨设备」整档按钮（主键 `GALAXY_CROSS_DEVICE_ENABLED`，连带 4 个成员：局域网发现、mDNS、设备接入平面、消息总线）。
- 「全部设置」里还单列：主脑、联邦、WebRTC 数据通道、Tailscale Funnel、远程桌面（全部默认关的 opt-in），以及一批数值 / 文本键。
- 面板 Mesh 区：worker 显示与启停（`/api/v1/mesh/worker`）、对端清单（`/api/v1/mesh/peers`）、拓扑（`/api/v1/mesh/topology`）。
- 设备清单走面板 feed（WebSocket 推送）。

## 配置键（实时登记表 + 代码里读到的环境变量）

键表由 `python scripts/gen_multi_device_map.py --write` 从实时登记表生成（其余部分是 2026-10-04 对着代码查的快照，不会自动更新）。
「登记」= 在 `CONFIG_SCHEMA` 里；**未登记**的只能改 `.env` / 环境变量，面板的「全部设置」里根本没有。
「生效」列写**重启**的，是从读取位置核实过「改了要重启才生效」的（见 `core/routes/config_restart.py`）。


<!-- tables:start -->
### ① 跨设备

**总闸与运行模式**

| 键 | 默认 | 登记 | 面板 | 整档按钮 | 生效 |
|---|---|---|---|---|---|
| `GALAXY_CROSS_DEVICE_ENABLED` | 关 | 是 | 留在面板 | 跨设备 | 重启 |
| `GALAXY_SYSTEM_MODE` | desktop-local | 是 | 全部设置 | — |  |
| `GALAXY_NATS_URL` | nats://localho | 是 | 全部设置 | 跨设备 |  |

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
| `GALAXY_FABRIC_STRICT` | 关 | 是 | 运维 | 跨设备 |  |

**通道与传输**

| 键 | 默认 | 登记 | 面板 | 整档按钮 | 生效 |
|---|---|---|---|---|---|
| `GALAXY_NATS_ENABLED` | 开 | 是 | 并进按钮 | 跨设备（成员） | 重启 |
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
| `GALAXY_HEARTBEAT_INTERVAL` | 5 | 是 | 全部设置 | 跨设备 |  |
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


### ② 多设备并行与任务分发

**并行与分发**

| 键 | 默认 | 登记 | 面板 | 整档按钮 | 生效 |
|---|---|---|---|---|---|
| `GALAXY_MULTI_DEVICE_DISPATCH_LIMIT` | — | **未登记**（只能改 .env） | — | — | — |
| `GALAXY_DISPATCH_IDEMPOTENCY` | 开 | 是 | 内置 | — |  |
| `GALAXY_CANONICAL_DISPATCH_AUTHORITY_MODE` | strict | 是 | 全部设置 | — |  |
| `GALAXY_NATS_EXECUTOR_FALLBACK` | sync | 是 | 全部设置 | 跨设备 |  |
| `GALAXY_NATS_EXECUTOR_TIMEOUT` | 30 | 是 | 全部设置 | 跨设备 |  |
| `GALAXY_DURABLE_EXEC` | 开 | 是 | 内置 | — | 重启 |
| `GALAXY_NODE_HEALTH_RETRIES` | 空 | 是 | 全部设置 | — |  |
| `GALAXY_SLO_HEARTBEAT_WINDOW` | 60 | 是 | 全部设置 | — |  |
| `GALAXY_ENABLE_LEGACY_MULTIDEVICE` | — | **未登记**（只能改 .env） | — | — | — |


### ③ 主脑

**主脑与 worker**

| 键 | 默认 | 登记 | 面板 | 整档按钮 | 生效 |
|---|---|---|---|---|---|
| `GALAXY_MASTER_BRAIN_ENABLED` | 关 | 是 | 留在面板 | 跨设备 | 重启 |
| `GALAXY_MASTER_BRAIN_STATE_PATH` | 空 | 是 | 全部设置 | 跨设备 |  |
| `GALAXY_MASTER_BRAIN_SCALING_REEVAL_INTERVAL_S` | 300 | 是 | 全部设置 | 跨设备 |  |
| `GALAXY_WORKER_ID` | — | **未登记**（只能改 .env） | — | — | — |
| `GALAXY_WORKER_VERSION` | — | **未登记**（只能改 .env） | — | — | — |

共 81 个键，其中 **18** 个未登记。
<!-- tables:end -->

## 模块（按块归类；行数是文件当前行数）

**① 跨设备**
- 开关与模式：`galaxy_gateway/cross_device_switch.py`（网关的唯一开关）、`core/system_mode.py`（运行模式权威）、`core/system_orchestrator.py`（启动时解析模式）、`core/desktop_presence_runtime.py`（桌面在场的跨设备模式）、`core/android_mode_gate_policy.py`。
- 发现与接入：`core/lan_discovery.py`、`core/device_onboarding/`、`core/mesh/`、`core/mesh_coordinator.py`、`core/adapters/mesh_routing_adapter.py`。
- 信任与准入：`core/peer_trust.py`、`core/participant_admission.py`、`core/capability_token.py`、`core/routes/pairing.py`、`core/routes/participants.py`。
- 传输与通道：`core/nats_bus.py`、`core/nats_server.py`、`core/nats_heartbeat.py`、`core/nats_posture.py`、`core/nats_subjects.py`、`core/aip_transport.py`、`core/tailscale_manager.py`、`core/headscale_join.py`、`core/tailnet_self_join.py`、`core/proxy_relay.py`、`galaxy_gateway/smart_transport_router.py`、`galaxy_gateway/webrtc_proxy.py`、`core/multimodal/webrtc_ingress_bridge.py`。
- 别的实例 / 设备：`core/galaxy_federation.py`（+ `core/routes/federation.py`）、`core/remote_desktop.py`、`core/ha_bridge.py`。
- 文档：`docs/CROSS_DEVICE_CONTROL_PLANE_ARCHITECTURE.md`（九层控制面）、`docs/CROSS_DEVICE_EXECUTION_CHAIN.md`、`docs/CROSS_DEVICE_ROLE_ROUTING_POLICY.md`、`docs/NATS_CONTROL_PLANE.md`、`docs/MESH_MEMBERSHIP_CONTRACT.md`。

**② 多设备并行与任务分发**
- 设备清单与「各种列表」：`core/device_registry.py`、`core/device_pool_manager.py`（调度 / 健康 / 权重）、`core/device_selection/`、`core/device_formation/`（编队与多设备组）、`core/device_readiness.py`、`core/device_participation.py`、`core/cross_device_policy/`、`core/mesh_participation_summary.py`、`core/network_topology_runtime.py`。
- 并行与分发：`galaxy_gateway/device_router.py`（唯一的规范分发器；有界并发 `GALAXY_MULTI_DEVICE_DISPATCH_LIMIT`）、`core/command_router.py`、`core/swarm_coordinator.py`（多设备编排层）、`galaxy_gateway/cross_device_coordinator.py`、`galaxy_gateway/wake_router.py`（唤醒排名）、`core/canonical_task_dispatch_chain.py`、`core/canonical_dispatch_slot_authority.py`、`core/unified_dispatch_readiness_gate.py`、`core/durable_dispatch_idempotency.py`。
- 执行链与结果：`core/cross_device_execution_chain.py`、`core/cross_device_dispatch_boundary.py`、`core/cross_device_result_surface.py`、`core/cross_device_sync.py`、`core/multi_device_*`（治理、真相收敛、控制完整性、运行时 harness 等）、`core/takeover_tracking.py`。
- 续跑：`core/task_graph_runtime.py`、`core/task_graph_checkpoint.py`、`core/task_graph_resume_dispatch.py`（`GALAXY_DURABLE_EXEC`）。
- 文档：`docs/DEVICE_FORMATION_AND_MULTI_DEVICE_GROUPS.md`、`docs/MULTI_DEVICE_ARCHITECTURE_ANALYSIS.md`、`docs/MULTI_DEVICE_RUNTIME_MATURITY.md`、`docs/MULTI_DEVICE_E2E_ACCEPTANCE_MATRIX.md`。

**③ 主脑**
- `core/master_brain.py`（云端控制面编排器，2000 多行）、`core/worker_runtime.py`（NATS worker 消费循环；主脑开启时由启动序列拉起，也可在面板手动启停）、`core/device_worker_convergence.py`、`core/mesh_nats_fusion.py`。
- 待做的产品项（已在清单里）：主脑的自动增减（`SwarmScaler`）。

## 接口

| 块 | 接口 |
|---|---|
| ① | `/api/v1/pair/*`（配对、信任、对端、tailnet）、`/api/v1/participants/*`（非安卓设备接入）、`/api/v1/devices/register`、`/devices/discover`、`/devices/discover-active`、`/api/v1/federation/*`、`/api/remote-desktop/status`、`/enable`、`/disable` |
| ② | `/api/v1/devices`（清单）、`/devices/{id}`、`/devices/{id}/command`（单设备命令）、`/devices/parallel`（并行命令，走 `CommandRouter` 扇出）、`/devices/cross-device`（跨设备协同任务）、`/api/v1/mesh/send`、`/mesh/peers`、`/mesh/topology`、`/mesh/stats`、`/mesh/probe` |
| ③ | `/api/v1/mesh/worker`（状态）、`/api/v1/mesh/worker/toggle`（启停） |

## 查出来的不一致和问题（没有动）

1. **`galaxy_gateway/cross_device_switch.py` 文件开头的说明是过期的**：写着「开关默认开、缺省视为开」，函数实际是缺省关、只认 `1/true/yes`。
2. **`GALAXY_NATS_EXECUTOR_FALLBACK` 的三个选项里有两个不生效。** 登记表说它是 `sync / async / reject` 三选一，代码只把它当开关读（不是 `false`/`0` 就算开）——选 `reject`（NATS 不可用就拒绝）实际是**开着回退**，和选项的意思相反。
3. **同一个键在不同层缺省不一致**：`GALAXY_NATS_ENABLED` 缺省开（会拉 nats-server），而跨设备缺省关；设了 `GALAXY_NATS_URL` 又会被推断成跨设备（两处各写一份推断）。
4. **核心这边的 `/devices/parallel`、`/devices/cross-device` 没搜到对跨设备开关的检查**（见上面第 2 点）。
5. **18 个相关环境变量只在代码里读、没登记**（上表标「未登记」）。其中联邦 3 个、TURN 凭据 2 个、Tailscale 3 个、WebRTC 3 个、传输优先级 1 个、网状网络节点号与端口 2 个、`GALAXY_MULTI_DEVICE_DISPATCH_LIMIT`、`GALAXY_ENABLE_LEGACY_MULTIDEVICE`（旧的多设备层，默认禁用）、worker 的 id 与版本。
6. **「跨设备」整档按钮的 `owns` 里有 `NODE_*_URL`**（内部服务节点地址），不是设备。

## 如果要组成一个：两种组法（等你定，没有动）

**组法 A — 用现有机制（不新增任何键）**：「跨设备」按钮保持，主键 `GALAXY_CROSS_DEVICE_ENABLED`，成员就是现在这 4 个；
② 本来就没有开关（跟着①走），不需要任何东西；③ 主脑是默认关的 opt-in，按钮「开」不能替人打开，所以仍是「全部设置」里的一个独立开关，
旁边写明「需要消息总线」。优点：零新增、零行为变化；缺点：主脑没有并进来。

**组法 B — 一个「多设备」三档牌（像「自主」那样，新增 1 个选择型键）**：新增 `GALAXY_MULTI_DEVICE = off | cross_device | multi_device | master_brain`，
档位逐级包含（跨设备 ⊂ 多设备 ⊂ 主脑），每一档写哪些现有键由登记表一处定义：

| 档 | 写什么（现有键） | 备注 |
|---|---|---|
| off | `GALAXY_CROSS_DEVICE_ENABLED=false`，成员全 false，`GALAXY_MASTER_BRAIN_ENABLED=false` | 只在本机跑 |
| cross_device | 跨设备 true + 4 个成员回默认（发现 / mDNS / 接入平面 / 消息总线）；主脑 false | 设备能被发现、配对、收任务 |
| multi_device | 同上；② 没有现成的键 —— 要让这一档与上一档**真的不同**，得给并行 / 分发加一个闸（新增代码），否则这一档和上一档没有区别 | 需要你说这一档要管住什么 |
| master_brain | 在 multi_device 的基础上 `GALAXY_MASTER_BRAIN_ENABLED=true` | 需要消息总线；开了会拉起主脑与 worker |

组法 B 的代价：一个新键（取代 7 个现有开关的面板入口）、`multi_device` 那一档要新增行为，并且**要先决定核心的 `/devices/parallel` 在跨设备关着时是不是该拒绝**（现在不查）。
