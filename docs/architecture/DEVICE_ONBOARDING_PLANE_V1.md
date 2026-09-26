# 设备接入平面 V1(Device Onboarding Plane)

> 状态:设计 + 实现基线 · 所有者:`core/device_onboarding/`
> 前置:`unified_device_registration_runtime_participation_v1.md`(UDM 为唯一写权威)、
> `CANONICAL_DEVICE_IDENTITY_CONTRACT.md`(身份 ≠ 在线)、`REGISTERED_RUNTIME_DEVICE_CONTRACT.md`
> (唯一对外单设备读契约)、`DISTRIBUTED_SUBJECT_CONTRACT_V1.md`(有界相对主体)、
> `MESH_MEMBERSHIP_CONTRACT.md`。
>
> 本文**不另立**任何设备模型、在线态或能力表。它回答的是上面这些契约之间缺的那一段:
> **一台设备怎么从"被看见"走到"成为成员、能被智能体使用",并且尽量不需要人。**

---

## 0. 一句话

中心智能体 + 若干有界相对主体组成的分布式系统里,**协议层(AIP v3)与网络层(自建 tailnet + NATS)
已经铺好**;设备接入平面把各种来源发现的设备,经过**统一词汇 → 候选 → 接入路径 → UDM/UCM 登记 →
驱动解析 → 能力上总线 → 智能体工具 / 面板**这一条链,变成系统成员。能自动的全自动;必须人在场的
(物理配网码、新主体上的确认、执行一条命令)明确告诉人做什么,其余交给智能体。

---

## 1. 现状核对(代码证据)

下面每一条都是在本仓里核实过的,不是推测。

### 1.1 已经有、方向正确的

| 层 | 实现 | 说明 |
|---|---|---|
| 设备身份与状态写权威 | `core/unified/device_manager.py`(UDM) | `register_device` 一次登记,自动:能力上 CapabilityBus(`device__<id>__<cap>`)、同化进能力图、同步 CapabilityAuthority、登记为 NATS Worker、喂给设备解析平面 |
| 连接与在线态权威 | `core/unified/connection_manager.py`(UCM) | `UCM_CONNECTION_AUTHORITY`;`get_presence_view()` 是在线/可路由的权威投影 |
| 单设备读契约 | `contracts/registered_runtime_device.py` | 已有 `platform` / 细分 `device_type` / `form_factor` / `execution_model`(full_runtime_host · partial_runtime_device · command_oriented · observer_telemetry · **adapter_bridged_device**)/ `participant_tier` / `attached_via_adapter` + `bridge_id` |
| 设备→驱动 | `registry/device_node_map.yaml` + `core/device_node_resolver.py` + `core/node_activation_policy.py` + `launcher/launcher_adapter` | 按 AIP 细分类型 → 传输 → 能力 解析到节点,按需拉起 |
| 传输 | `core/aip_transport.py` + `core/adapters/` | 同一条 AIP v3 消息走 WS / Tailscale P2P / MQTT / TCP / UDP / BLE |
| 消息总线 | `core/nats_bus.py` | 核心组件;无外部 NATS 时自起内嵌,有 Tailscale 时绑 100.x |
| 网络 | 自建 headscale(`deploy/headscale`、`core/headscale_join.py`、`core/tailnet_*`) | 配对即发进网钥匙;设备列表与节点表对账;移除即收回 |
| 发现 | `core/lan_discovery.py`(mDNS)、`core/ha_bridge.py`(Home Assistant) | |
| 扩展能力 | `github__install`(智能体可用)、`core/mcp_gateway.py`(自造 MCP 工具) | |

### 1.2 断点(每条都会在本设计里被消掉)

| # | 断点 | 证据 | 后果 |
|---|---|---|---|
| G1 | **细分类型在进 UDM 时被截断** | `android_bridge.py` 把 `android_phone` 转 `UnifiedDeviceType` 失败 → `ANDROID`;`ssot.py` 取下划线前一段 | 解析器按 `android_phone` 建表,拿到的是 `android`:**真实注册的设备一台都解析不到驱动**(实测 `android/windows/iot → None`) |
| G2 | 能力词汇不统一 | 手机上报 `gui_read`(小写)/`tap`,映射表写 `GUI_READ`;解析器按原样比集合 | 能力匹配这条路同样走不通 |
| G3 | 智能体看不见设备 | `_collect_tools` 只收 MCP/SKILL/NODE,不收 `CapabilitySource.DEVICE`;`resource__list` 里从没登记过设备;节点能力表为空 | 智能体没有任何设备工具 |
| G4 | 发现 ≠ 接入 没有区分 | `lan_discovery` 直接以 `iot`+在线 写 UDM | 附近的投屏盒子与已接入的成员长得一样;同一台手机两个 id |
| G5 | 在线态只认 WebSocket | UCM `register_connection` 必须有 WebSocket;HA 设备、NATS worker、tailnet 节点的在线各记各的 | "在线"有 4 个来源,UCM 名为权威、实为半个 |
| G6 | UDM 只在内存 | `UnifiedDeviceManager._devices` 无持久化 | 重启后被桥接的成员消失,要等来源再推一次 |
| G7 | 并行设备表 | 面板花名册读 `core.routes._shared.registered_devices`(兼容缓存,只有 REST 注册会写);MasterBrain 另有 `_workers` | 面板上看不到经 WS 连上的手机手表;Go edge worker 不进 UDM |
| G8 | 闲置零件 | `MeshAutoEnrollmentService` 零调用;`mcp_gateway.handle_capability_gap` 零调用;Serial/DBus/CAN 适配器未注册;Node_71 的 SSDP 未接线 | 设计好的能力没有入口 |
| G9 | 智能家居不在统一映射里 | HA 实体只靠 `metadata.control_via` 旁路指向 Node_27 | 解析平面、面板、智能体各自认不出它是"经桥接的设备" |
| G10 | 配对入口不在面板 | 面板源码没有任何 `/api/v1/pair/*` 调用 | 配对码只能手敲接口拿 |

---

## 2. 统一模型:三种角色,全部复用已有契约词汇

不新造角色枚举。`RegisteredRuntimeDevice` 已经给了全部词汇,这里只规定**怎么取值**:

| 角色 | 例子 | `execution_model` | `participant_tier` | 进 tailnet | 讲 AIP v3 | 能发起 |
|---|---|---|---|---|---|---|
| **中心主体** | 跑智能体的电脑 | `full_runtime_host` | `primary` | 是 | 原生 | 能 |
| **有界相对主体** | 手机(本地模型、本地判断) | `full_runtime_host` | `secondary` | 是 | 原生 | 有界(见 DISTRIBUTED_SUBJECT_CONTRACT) |
| **成员** | 手表、其他电脑、树莓派、edge worker | `partial_runtime_device` / `command_oriented_device` | `secondary` | 是 | 原生 | 只响应 |
| **被接入设备** | 灯、插座、Matter、投屏、打印机 | `adapter_bridged_device` | `bridged` | 否 | 由桥代讲 | 不能,只上报 |
| 只观测设备 | 纯传感器 | `observer_telemetry_device` | `observer` | 视情况 | 视情况 | 不能 |

"能不能发起任务"由 `can_initiate` 派生(`execution_model == full_runtime_host`),不由设备自报。

**桥(bridge)**:一个跑在某台成员上、一边讲厂商协议一边讲 AIP v3 的适配者。被接入设备在 UDM 里
`bridge_id = "<桥类型>:<桥实例>"`(如 `ha:192.168.1.20:8123`),下行命令由桥执行。

---

## 3. 统一词汇(`core/device_onboarding/taxonomy.py`)

所有登记路径在**同一处**(`UDM.register_device` 入口)做归一化,不要求每个调用方记得做。

### 3.1 设备类型三件套

| 字段 | 取值 | 来源 |
|---|---|---|
| `device_type`(已有) | `UnifiedDeviceType` 粗类:android/windows/linux/iot… | 保持兼容,所有既有消费者照旧 |
| `aip_device_type`(新增) | `AIPDeviceType` 细分:android_phone / android_wear / linux_raspberry / iot_generic… | 调用方原值 → 元数据提示 → 由粗类+形态推导 |
| `form_factor`(新增) | phone / watch / desktop / laptop / tv / embedded / server… | 由细分类型推导 |

解析器、`from_udm_device`、面板都读 `aip_device_type`,不再依赖被截断的粗类(消 G1)。

### 3.2 能力两层

| 字段 | 含义 | 例子 |
|---|---|---|
| `capabilities`(已有) | 设备自报的**动作级**名字,原样保留,下行派发用 | `tap`、`screenshot`、`turn_on` |
| `capability_classes`(新增) | 归一后的**能力类**,路由/解析/面板用 | `GUI_WRITE`、`INPUT_TOUCH`、`HOME_POWER` |

能力类 = AIP v3 `DeviceCapability` 全部名字(大写) + 本仓侧扩展的 `HOME_*`(被接入设备的执行器类,
AIP 位图里没有):`HOME_POWER / HOME_LIGHT / HOME_CLIMATE / HOME_COVER / HOME_LOCK / HOME_MEDIA /
HOME_SENSOR / HOME_SCENE / HOME_VACUUM`。映射表是一张声明式字典(同义词 → 能力类),新增设备只需加词,
不改代码。解析器按能力类大小写不敏感匹配(消 G2)。

> `HOME_*` 暂不进 AIP 位图(那需要三仓同步改 Kotlin);被接入设备不在手机/手表上跑,不受影响。

### 3.3 传输

新增 `transport` 字段(解析器第二匹配路径本就读它,之前 UDM 里没有):`websocket` / `nats` /
`home_assistant` / `mdns` / `matter` / `ssdp` / `adb` …

---

## 4. 生命周期:候选 → 成员

```
   发现来源 ──observe()──► 候选(Candidate) ──join()──► 成员(Member) ──remove()──► 已移除
      │                     │  new                       │  UDM 登记(身份)
      │                     │  needs_human ◄─┐           │  UCM 在线(通道)
      │                     │  joining       │           │  驱动解析/拉起
      │                     │  ignored       │           │  能力上总线
      │                     │  failed ───────┘           │  Mesh 编入
      └── 已是成员 → 只刷新在线(不产生候选)                └── 花名册持久化
```

* **候选(`CandidateLedger`,持久化)**:"附近有这么个东西"。**不进 UDM、不进能力平面**,所以不会
  被路由、不会被当成已接入(消 G4)。
* **成员**:经某条接入路径成功后才写 UDM。
* **花名册(`MemberRoster`,持久化)**:记"谁是我的成员、怎么接入的、桥是谁"。进程启动时把成员
  以**离线**身份回灌 UDM(身份 ≠ 在线),等来源推在线时再亮(消 G6)。
* **去重/认领(identity link)**:观测到的东西先按强标识找已有成员:mDNS TXT 里的 `device_id`、
  HA `entity_id`、tailnet 节点名、Worker id、同一 IP。命中就只刷新成员在线,不产生候选
  (消"同一台手机两个 id")。

候选状态:`new`(可自动接入)、`needs_human`(需要人做一件具体的事,附说明)、`joining`、`joined`、
`ignored`(人说不要,之后再看见也不再打扰)、`failed`(附原因)。

---

## 5. 在线态:UCM 通道化(消 G5)

UCM 保持为**唯一**在线权威,但不再只认 WebSocket。新增 **presence 通道**:

| 通道 | 谁报 | 何时算在线 |
|---|---|---|
| `websocket` | 既有 `register_connection` | 不变 |
| `bridge` | HA 桥 / 其他桥 | 实体状态非 unavailable/unknown |
| `nats` | edge worker 心跳 | 心跳在 TTL 内 |
| `tailnet` | headscale 对账 | 节点 online |
| `lan` | mDNS/SSDP | 广播仍在 |

API:`UCM.report_presence(device_id, channel, online, *, routable=None, detail=None)`。
`get_presence_view()` 合并:WS 通道逻辑与之前**逐字一致**;无 WS 时取其他通道里最近的一条。
`is_device_connected()` 语义不变(仍只表示有 WS 句柄),新增 `is_present()` 表示"任一通道在线"。

---

## 6. 接入路径(Join Path)注册表 —— 可插拔、可复用

每条路径是一个类,声明:

```python
class JoinPath(Protocol):
    name: str
    human_step: HumanStep   # none | approve | physical_code | confirm_on_device | run_command
    def can_handle(self, cand: Candidate) -> bool: ...
    async def join(self, cand: Candidate, ctx: JoinContext) -> JoinOutcome: ...
```

`JoinOutcome` 要么是 `joined(device_id)`,要么是 `needs_human(说明 + 所需输入的结构化描述)`,
要么是 `failed(原因)`。**新增一种设备 = 新增一条路径类 + 注册一行**,服务本身不改。

V1 内置路径:

| 路径 | 处理 | 人要做什么 | 结果角色 |
|---|---|---|---|
| `ha_entity` | HA 里已有的实体 | 无(HA 已由人配置、是可信控制面) | 被接入,`bridge_id=ha:…` |
| `ha_discovered_flow` | HA 自己发现、等确认的集成(投屏、打印机、路由器、Hue…) | 无字段的一步确认:无;需要字段(PIN/配对码):按 HA 表单告诉人要填什么 | 集成建好后实体由 `ha_entity` 接入 |
| `matter_via_ha` | 局域网里可配网的 Matter 设备 | **物理配网码**(贴纸/二维码) | 经 HA Matter 集成 → 实体 → 被接入 |
| `galaxy_peer` | 开着本系统 App、还没配对的手机/手表 | **在设备上输入配对码**(码由智能体签发,推到手表/面板) | 主体或成员 |
| `tailnet_node` | 已在自建 tailnet 里、但不属于任何成员的节点 | 同上(签配对码);若是跑 edge worker 的电脑则见下 | 成员 |
| `edge_worker` | 在 NATS 上注册的 Go edge worker | **批准**一次(智能体在手表上问) | 成员(`partial_runtime_device`,transport=nats) |
| `computer_command` | 要加入的新电脑(人主动要求) | **执行一条命令**(tailnet 一次性钥匙 + 启动 worker) | 成员 |

**自动接入策略**(`GALAXY_ONBOARDING_AUTO`,默认 `none`):
`none` = 只有 `human_step=none` 的路径自动走;`approve` = 连"批准"类也自动;`off` = 全部等人/智能体。
物理码、设备上确认、执行命令这三类**永远不能自动**。

---

## 7. 驱动:解析 → 获取 → 回写(消 G1/G8/G9,接 MCP 与技能)

1. **解析**:成员登记后,解析平面用 `aip_device_type` → `transport` → `capability_classes` 查
   `device_node_map.yaml`。映射表补上:`transport: home_assistant → Node_27_SmartHome(shared)`。
   原生讲 AIP 的主体/成员(手机、手表)**不需要驱动**,解析为空是正确结果,标 `native`。
2. **获取**(没有驱动时,智能体可发起,`devices__acquire_driver`):
   1. 已安装的 MCP/技能里按标签找;
   2. 智能体给出的 GitHub 链接 → `github__install`(已有);
   3. 最后才 `mcp_gateway.handle_capability_gap` 让模型写一个 MCP 驱动(沙箱测试后加载、经 NATS
      广播给所有成员)。生成代码属于高风险,**必须在手表上批准**。
3. **回写**:获取成功后,这类设备以后怎么接,记进映射(驱动覆盖表 `data/driver_overrides.json`,
   解析器与 YAML 合并读取)——系统每接一种新设备就多会一种。

---

## 8. 智能体工具(`devices__*`,消 G3)

内联工具族(与 `ask_human__`、`home__` 同一模式),不把几百个 `device__<id>__<cap>` 灌进上下文:

| 工具 | 作用 |
|---|---|
| `devices__list` | 成员(按角色分组、在线、能力类、桥、是否能发起)+ 候选(来源、要人做什么) |
| `devices__join` | 接入一个候选;需要人时返回具体要做的事,并可推到手表 |
| `devices__ignore` | 不再提示某个候选 |
| `devices__remove` | 移除成员:注销 UDM、清花名册、收回 tailnet 节点、从 Mesh 退出 |
| `devices__invoke` | 调某台设备的一个动作:原生设备走 CanonicalDispatcher `device__…`(权限门照常);被接入设备走它的桥(HA → Node_27,自治档位审批照常) |
| `devices__acquire_driver` | 见 §7 |

`home__*`(智能家居按名字控制)保留:它是被接入设备里最常用的一类的便捷入口,底层与
`devices__invoke` 走同一条 Node_27 路。

---

## 9. REST 与面板(消 G7/G10)

REST(`core/routes/onboarding.py`):
`GET /api/v1/onboarding/overview`(成员分组 + 候选 + 在线汇总)· `POST /api/v1/onboarding/candidates/{id}/join`
· `POST …/ignore` · `DELETE /api/v1/onboarding/members/{device_id}` · `POST /api/v1/onboarding/scan`(立即扫一次)。

面板:
* 岛上的设备花名册改读 **UDM + UCM**(经 `RegisteredRuntimeDevice` 投影),不再读兼容缓存;
* 新增「设备」抽屉:成员按角色分组(主体 / 成员 / 被接入)、在线点、能力类、桥;候选一栏带「接入」
  「忽略」;需要人时就地显示要做什么(配对码、要填的字段、要执行的命令);顶部「添加设备」给出配对码
  与二维码链接、tailnet 状态。

---

## 10. 发现来源(统一走 `observe()`)

| 来源 | 实现 | 产出 |
|---|---|---|
| mDNS | `core/lan_discovery.py`(改为交给接入平面,而非直写 UDM) | `_galaxy*` → 认领已有成员或 `galaxy_peer` 候选;`_matterc` → `matter_via_ha`;其他 → 候选(若 HA 已配,提示经 HA 接入) |
| SSDP/UPnP | `core/device_onboarding/sources/ssdp.py`(新,轻量;Node_71 的实现在节点层,core 不能反向依赖) | 电视、路由器、DLNA、打印机 → 候选 |
| Home Assistant 实体 | `core/ha_bridge.py`(镜像时交给 `ha_entity` 路径) | 被接入成员 |
| HA 已发现的集成 | `sources/ha_flows.py`(轮询 `GET /api/config/config_entries/flow`) | `ha_discovered_flow` 候选 |
| headscale 未归属节点 | `core/tailnet_membership.annotate` 的 `tailnet_only` | `tailnet_node` 候选 |
| NATS edge worker | 订阅 `galaxy.workers.register` / `heartbeat` | `edge_worker` 候选;心跳 → UCM `nats` 通道 |
| 配对成功 | `core/routes/pairing.py` | 直接成员(配对本身就是人在场的确认) |

---

## 11. Mesh 编入(接上 `MeshAutoEnrollmentService`)

成员接入完成时调用 `on_device_registered(device_id, roles=…)`,角色由能力类推导(感知:相机/麦克风/
传感器;执行:GUI_WRITE/INPUT_*/HOME_*;在场:通知/屏幕);UCM 下线时 `on_device_lost`。

---

## 12. 安全

* 候选不进能力平面:没接入的东西不会被路由、不会被智能体调用。
* 人在场的三类步骤(物理码、设备上确认、执行命令)不能被任何配置自动化。
* 被接入设备的写动作仍经 Node_27 权限白名单 + 自治档位(guided 下在手表上问)。
* 生成驱动代码必须人批准;安装第三方 MCP/技能沿用 `github__install` 的既有审计。
* `devices__remove` 同时收回 tailnet 身份,丢失的设备不能再进网。

---

## 13. 配置

| 键 | 默认 | 说明 |
|---|---|---|
| `GALAXY_ONBOARDING_ENABLED` | true | 接入平面总开关 |
| `GALAXY_ONBOARDING_AUTO` | none | 自动接入到哪一级(off / none / approve) |
| `GALAXY_ONBOARDING_SCAN_INTERVAL_S` | 60 | 轮询类来源(HA 集成、SSDP、tailnet)的周期 |
| `GALAXY_ONBOARDING_STATE_DIR` | `data/` | 候选账本与花名册的位置 |

---

## 14. 扩展配方

* **新设备种类**:taxonomy 加同义词 → 若需要驱动,映射表加一行(或让智能体获取驱动后自动回写)。
* **新发现来源**:写一个把原始信息转成 `Observation` 的函数,调 `get_onboarding_service().observe()`。
* **新接入方式**:写一个 `JoinPath` 类,`register_join_path()` 一行。
* **新桥**:桥把设备以 `bridge_id=<type>:<instance>` 交给接入平面,并把下行命令实现为一个节点/MCP;
  `devices__invoke` 按 `bridge_id` 前缀路由,在 `BRIDGE_INVOKERS` 里注册一行。

---

## 15. 不在 V1 内(明确说明)

* 手机/手表**在设备上弹窗确认加入**:需要两个 App 各加一个界面;V1 用"设备上输入配对码"完成同样的确认。
* 协调者迁移(电脑关机时手机接管协调):另一个量级,见相对主体设计。
* `HOME_*` 进 AIP 位图:需三仓同步。
* Serial/DBus/CAN 适配器:只在对应硬件依赖存在时注册(启动时探测),不强起。
