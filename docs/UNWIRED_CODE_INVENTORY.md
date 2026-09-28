# 未接线与不可达代码：到底是些什么东西（2026-09-28）

> 所有者的要求：**先确认清楚是些什么东西，再决定删还是接。** 本文只做清点。
> 本轮没有因为这份清单删掉或接上任何一行代码 —— 下文「随本轮任务顺带处理的」一节列出的，
> 是别的任务（会话迁移、配置写入合并）本来就要动、顺手接上的，每一处都写明了。
>
> 复测命令：
> - `python scripts/unwired_inventory.py --write` —— 刷新本文末尾的生成段（分类表 + 逐文件清单）
> - `python scripts/check_wiring.py --all` —— 原始名单（判据写在该脚本的模块说明里）
> - `python scripts/check_reachability.py --list` —— 从真实入口不可达的模块

## 1. 这 755 条是什么

**判据**（`scripts/check_wiring.py`）：`core/`、`galaxy_gateway/`、`nodes/`、`launcher/` 下名字不以 `_` 开头的
函数/方法，在全仓**除 `tests/` 以外**找不到任何按名字的引用，也不在豁免清单里。

所以它不是「755 个没接上的功能」，而是 **755 个没有生产调用方的公开函数/方法**：

| 事实 | 数 |
|---|---|
| 类方法 / 模块函数 | 486 / 269 |
| 分布在多少个文件 | 359 |
| 只有测试在引用（写了、测了、没接） | 500 |
| 全仓连测试都没引用 | 255 |
| 所在模块本身从入口不可达 | 4（都在下面三个不可达模块里） |

按**名字表明的角色**分（脚本用前缀/后缀做的初筛，不是逐条人工判定）：

| 角色 | 条数 | 这类没人调用意味着什么 |
|---|---|---|
| 动作/变更（record/set/register/route/send/persist…） | 335 | **该动作从没在生产里发生过**。最可能是「能力写了没生效」 |
| 只读查询（get/list/…_snapshot/…_summary） | 129 | 对象的查询面没人读；通常无害，但有时说明对应的观测面没做 |
| 计算/构造（build/derive/decide/normalize…） | 112 | 算法写了没用上；有的已被别的实现取代 |
| 判定谓词（is_/has_/can_/requires_…） | 106 | 同上 |
| 测试复位钩子（reset_/clear_/…_for_testing） | 34 | 基本都是给测试用的，本就不该有生产调用方 |
| 序列化/转换（to_/from_/as_） | 27 | 对象 API 面，无害 |
| 事件回调（on_*） | 12 | **回调写了但没挂到任何事件源上** —— 事件发生时它不会被叫 |

真正意味着「某项能力没生效」的，主要是**动作/变更 + 事件回调这 347 条**；其中连测试都没有的 159 条
（152 + 7）最像真死代码。其余四类多是对象的 API 面。

## 2. 按用途说：这 755 个函数到底是干什么的

上一节是按**名字**分的（查询还是动作）。这一节按**它属于系统的哪一块、原本是要干什么**分，
依据是每个函数自己写的说明（755 个里 701 个写了）和所在模块的说明。逐个函数的原文说明在文末生成段里。

「有测试」= 只有测试在调它；「没测试」= 全仓连测试都没引用。

| 用途 | 个数 | 有测试 / 没测试 | 一句话 |
|---|---:|---|---|
| 设备与节点：注册、发现、连接、通信、传输 | 109 | 43 / 66 | 早期「设备中心」设计里的操作面，主路径改走统一设备模型 + 网关 WS 之后没人再调。**没测试的最多，真死代码主要在这里** |
| 架构治理：权威声明、边界断言与自检 | 96 | 86 / 10 | 历次重构为「证明收敛了」写的规则库：谁说了算、哪条是主路径、有没有第二个写入方。有测试，但生产里没有一处在真正的决策点调用 |
| 智能体、认知与记忆 | 84 | 38 / 46 | 一半是半成品功能（数字孪生、身份目标、反馈学习），一半是没拆完的 OpenClawd 门面类 |
| 安卓协作的契约、治理与对账层 | 83 | 76 / 7 | 和「架构治理」同一性质，专管安卓：结果分类、恢复打分、协议状态映射。另有几个真动作没接（手表同步、灵动岛路由、显式重连） |
| 配置、启动、安全、扩展与通用基础件 | 80 | 47 / 33 | 安全策略热重载与细粒度判定、MCP 热重载与资源读取、技能包加载、TaskState 写方法、ConfigService 那几维 |
| 能力、模型与执行路由 | 76 | 52 / 24 | 模型下载 API、切换主脑、硬件感知路由三个入口、能力启停、能力总线注册 |
| 持久化、重启恢复与断点续跑 | 52 | 47 / 5 | 「重启后接着干」的能力：**写盘那一半没接**（读的一半接了），设备重连后续发待办也没接 |
| 指标、可观测与审计记录 | 51 | 48 / 3 | 采集点没接：SLO 计数、审计事件、执行事件规范化器。读取面在，所以看到的数不真实 |
| 多设备编组、协同网络与拓扑 | 50 | 39 / 11 | 拓扑运行时「吸收实时事件」的入口、编组加入与角色分配、Mesh 结果合并与 NATS 融合 |
| 节点服务里的方法 | 47 | 2 / 45 | 各独立节点进程里写了、但节点接口没暴露的操作（无人机录像/航点、视频合并、知识库导入导出……） |
| 语音、桌面在场与感知 | 27 | 22 / 5 | 基本是给面板/诊断的查询与测试辅助；没接的动作只有设声音/语速等几个 |

### 2.1 设备与节点（109）

- **设备注册表**：分组与标签（`add_to_group` / `add_tag` 及对应的移除）——设备没有「分组」「标签」这回事在运行；
  `DeviceAgentManager` 的「连接所有设备」「注册新的设备 Agent 类型」。
- **节点发现与注册**：节点加入/更新回调、注销节点、扫描本地 `nodes/` 目录、停止健康监控、网络分区检测。
- **传输**：TCP 直连与局域网找对等端、探测最佳传输；多模态传输的发视频/发截图/分块收发文件；断点续传的收文件。
- **协议转换**：安卓格式、WebSocket 格式的互转（`node_protocol`）。
- **网关杂项**：守护进程崩溃/过载通知三件、唤醒路由的决策回调、会话漫游的关闭/读快照/更新任务状态、旧任务分解器的两种分解。

判断：多数属于被新主路径（统一设备模型 + 网关 WS + 会话迁移规范面）取代的旧操作面。66 个没测试的，多半可以直接删。

### 2.2 架构治理（96）与安卓对账层（83）

这两块性质相同，合计约 180 个，是本仓最有特点的一类：**规则写成了代码，但只有测试在执行规则**。例如
`assert_no_competing_authority`（某个事实只能有一个权威来源）、`assert_canonical_is_decision_authority`
（决策必须走主路径）、`mainline_convergence` 的记录与判定、`release_governance_taxonomy` 的问题分类、
`production_baseline` 的「这个字段归谁」；安卓那边是结果分类、恢复质量打分、会话复用判定、UGCP 协议状态映射（`map_from_*`）。

它们证明的是「规则本身写对了」，**不是**「系统在运行时遵守了规则」——生产代码没有一处在真实的写入或决策点调用它们。
安卓那一块里另有几个真正的动作没接：WearOS 状态同步、给手表推决策、灵动岛式消息路由、`device_reconnect` 消息处理。

判断：要么挑关键的几条接到真实决策点（改热路径，有风险），要么承认它们是审计工具性质、整体降级。安卓那块按你的意思先放着。

### 2.3 智能体、认知与记忆（84）

- **没拆完的门面**：`core/orchestration/` 下的 execution / planning / reflection / helpers 把 OpenClawd 的私有方法包了一层，
  准备拆分大对象用；拆分没做完，门面没人调。
- **半成品功能**：数字孪生（向实体设备推命令、无人机/3D 打印机物理模型、批量耦合）；智能体身份（加/删长期目标、加价值观）；
  团队成员耦合/解耦；工作流的三种入口（单 agent / 团队 / 分形）；反馈学习（记录用户评价、「该不该用本地执行」）；
  用户偏好的「给任务推荐设备」。
- **小件**：认知层的状态判定（`is_narrow` / `is_liminal` 之类）、长期记忆按命名空间遗忘、模式挖掘全量扫描、会话证据导出 JSONL。

判断：门面类跟着「拆不拆 OpenClawd」一起定；半成品功能是产品决定（要就接，不要就删）。

### 2.4 配置、启动、安全、扩展与通用基础件（80）

- **安全**：安全策略按类别/场景判权限、热重载安全策略、检测策略文件变更——**安全策略的热重载和细粒度判定没在运行**；
  工具权限的动态加策略；MCP 调用守护包装（写成可选启用，但从没启用）。
- **扩展**：MCP 的热重载工具、向 worker 广播工具清单、读资源/列资源、通知工具列表变化；技能包加载。
- **任务状态**：统一状态模型 `TaskState` 的 5 个写方法（设目标、设阶段、记评审、标记通过、消除失败点）——那套 JudgeLoop 状态没被用上。
- **其余**：`ConfigService` 那几维（写的键运行时没人读，见 `PANEL_SURFACE_CONVERGENCE.md` 最后一节）、错误峰值检测与错误边界装饰器、
  队列强停、缓存节点状态、启动器的横幅/颜色/依赖顺序小工具。

### 2.5 能力、模型与执行路由（76）

- **模型管理**：`HuggingFaceModelManager` 的下载 LLM / VLM / ASR / Embedding 与后台下载；本地主脑的切换主脑、删除模型、
  「本地主脑优先」路由。
- **路由入口**：硬件感知多模态路由的视觉 / 语音识别 / 带图三个入口。
- **能力**：能力编排器的启用/禁用/重新加载/按关键字查；能力总线注册 MCP 工具、工程能力、资源能力。
- **小件**：选路解释（`explain_selection`）、算力调度器的查询、各种 `is_*` / `has_*` 判定。

### 2.6 持久化与恢复（52）、指标与审计（51）—— 最该先接的两块

- **持久化与恢复**：委托流持久化的 9 个 `persist_*` / `restore_*` 全没人调，恢复协调器却在读它 → 重启后「从检查点恢复」走不到；
  混合编排的「保存执行记录」没人调（加载/恢复有人调）→ 同样只读不写；任务信封的「超时取消」「设备重连后续发待办」没接。
- **指标与审计**：运行 SLO 的 13 个记录函数（`/metrics` 上恒为 0）；审计事件（路由决策、策略决策、故障域）三个发送函数；
  审计账本的哈希链校验；执行事件的四个规范化器。

这两块有个共同点：**读取面都已经对外了，写入/采集那一端没接**，所以看到的是「没出过事」「没有检查点」，而实际是「没人记」。

### 2.7 多设备编组与拓扑（50）

能力/网络运行时「吸收实时事件」的四个入口（设备上下线、心跳、能力变化、传输路径变化）没接 —— 拓扑运行时拿不到实时事件；
编组自动加入、按能力给在线设备分配角色、Mesh 会话协调器的三种结果合并、Mesh-NATS 融合的提交/订阅、蜂群自动扩缩、
代理中继（迁移 Agent、转发任务信封）。和运行时自己登记的 `structural_only` 一致：结构在，事件没接进来。

### 2.8 节点服务里的方法（47）

独立节点进程里写了、但节点的 HTTP 接口没暴露、也没人调的操作：无人机开始/停止录像与执行航点任务、FFmpeg 合并视频、
ADB 集群并行执行、知识库导入导出、自愈节点注册恢复处理器、主动感知节点注销传感器/规则、外部工具包装节点的自定义工具、
认证节点删除用户/查权限、多设备协调节点（Node_71）的故障切换主备设置……45 个没测试。

判断：节点功能「写了一半」—— 要么给节点补接口，要么删。

### 2.9 语音、桌面在场与感知（27）

绝大多数是给面板/诊断用的查询（权限与安全摘要、决策时间线回放、感知源质量）和测试辅助。真正没接的动作只有几个：
设置 TTS 默认声音/语速、语音循环的单次处理、回声判定的便捷函数、声道合成计划。影响很小。

## 3. 值得先看的几簇 —— 「看得见，但不生效」

这几簇的共同点：**对外有读取面，写入/触发端却没接**。读的人看到的是「一切正常」，其实是「没人记」。

1. **运行 SLO 指标只接了一半。** `core/operational_slo_metrics.py` 的 13 个 `record_*`（派发尝试/成功/失败、
   路由拒绝、回退触发、五种恢复结果、启动恢复扫描、审计落盘成败）全部零生产调用方；但 `/metrics`、
   `core/routes/monitoring.py` 的 JSON 指标端点、`core/routes/projection.py` 都在读它的 snapshot。
   结果：这些计数在生产里**恒为 0**。唯一接上的写入是 `openclawd` 里的 `ingest_latency_budget_summary`。
2. **委托流持久化只接了读。** `core/delegated_flow_persistence.py` 的 `persist_all` 与 8 个
   `persist_*`/`restore_*` 零生产调用方；`core/delegated_flow_recovery_coordinator.py` 却在
   `_has_durable_persistence()` 里读 `flow_entity_store` 判断「有没有持久化检查点」。没人写 → 永远读不到
   → 重启后「从检查点恢复」这条分支在生产里不会走到。
3. **会话漫游的一半生命周期没接。** `galaxy_gateway/session_roaming.py` 的 `close_session`、
   `load_snapshot`、`update_task_state` 零调用方；`auto_migrate_on_attention_shift` 只有测试引用。
   （本轮会话迁移规范面接上了迁移那一部分，`set_migration_callback` 也接上了，见第 5 节。）
4. **配置服务的写入口。** `core/config_service.py` 的 `set_provider_api_key`、`set_oneapi`、`set_network_url`、
   `set_toggle`、`set_native_mm_policy`、`set_android_inference_mode` 生产零调用方 —— 面板保存走的是
   `POST /api/config` → `.env` 那一条，两条写路径没合。（复核后发现那几维运行时没有读者，没有「合并」，见第 5 节。）
5. **设备注册表的分组与标签。** `core/device_registry.py` 的 `add_tag`/`remove_tag`/`add_to_group`/
   `remove_from_group` 零调用方、连测试都没有。
6. **事件回调没挂上。** 例如 `UnifiedConfig.on_change`、`ConnectionManager.on_connected`/`on_disconnected`、
   `NodeDiscoveryService.on_node_joined`/`on_node_updated`、`DeviceCommunication.on_device_message`：
   注册回调的入口存在，但没有任何生产代码去注册。

## 4. 三个从真实入口不可达的模块（共 1733 行）

「不可达」＝ 从顶层启动器、网关 app、OpenClawd、API 路由、`nodes/` 等真实入口出发，沿 import 边走不到
（`scripts/check_reachability.py`；**测试不是入口**）。

| 模块 | 行数 | 它是什么（取自它自己的说明） | 谁提到了它 | 为什么说它不生效 |
|---|---|---|---|---|
| `core.local_agent_runtime` | 423 | **端侧** Agent 执行沙盒：收 `AgentManifest`，在本地跑 ReAct / 顺序 / 自主三种循环，逐步回报 | 4 个测试；`orchestration_authority/legacy_paths.py` 把它登记为 `LEGACY_COMPATIBILITY`；`runtime_invariant_enforcement` 的 INV-008 与几处注释 | 设计上它跑在设备端，而设备端是安卓 App（另一仓，Kotlin）；本仓服务端按 PR-S5 明令不得用它做规划。本仓没有任何进程加载它 |
| `core.posture_contract_canonicalization` | 331 | `source_runtime_posture` 字段的契约校验层：规范化、边界断言、从 payload 取 posture，外加 5 个策略哨兵 | `core/runtime/__init__.py` 惰性再导出表里的**字符串**；3 个模块文档字符串里的「PR-1」 | 全仓没有任何生产代码取用它导出的任何一个名字 —— 校验层存在，但 posture 的产生/写入处没有调用它 |
| `core.truth_conflict_enforcement` | 979 | 设备/任务/会话三个真相面的写权威登记 + 写顺序守卫（`assert_canonical_write_precedes_compat_write` 等）+ 健康快照 | `compat_fallback_authority_guard`、`runtime_invariant_enforcement` 在**描述字符串**里提到它；1 个测试文件 | 没有任何写入点调用这些守卫 —— 它声称的「兼容写之前必先写规范源」在运行时从未被检查过 |

## 5. 随本轮任务顺带处理的

本轮别的任务本来就要动下面这些地方，顺手接上；除此之外清单里的条目**一条都没动**。

- 会话迁移规范面（D3）：漫游会话现在经规范面 `core/session_migration.py` 迁移；`core/event_bridge.py` 原先挂错了
  属性，现在经 `SessionRoamingManager.set_migration_callback` 挂上迁移回调 —— 这一条因此从清单里出去了。
- 面板配置写入合并：复核后没有做「合并」（生效的只有一条写入链路），`ConfigService` 那几个写方法**没动**，
  仍在清单里。见 `docs/PANEL_SURFACE_CONVERGENCE.md` 最后一节。

`config/wiring_baseline.json` 已重记（760 → 755）：基线里有 4 条（`current_runtime_session`、`forget`、
`handle_capability_gap`、`is_verified`）早已有了生产调用方，是过期条目；另 1 条是上面接上的 `set_migration_callback`。

## 6. 可选处置（等所有者定，本轮未执行）

> 所有者 2026-09-28：先把「是干什么的」讲清楚（第 2 节）；删还是接**后面做**，和设备注册下游步骤的「补跑 + 隔离」（G002）放在一块儿。

| 对象 | 选项 | 我的建议 |
|---|---|---|
| 「看得见但不生效」的几簇（第 3 节 1、2） | 接上写入端 / 撤掉读取面 | **接**。读取面已经对外，恒为 0 或恒读不到比没有更误导 |
| `core.local_agent_runtime` | 删 / 保留 | **删**（连同 `legacy_paths.py` 的登记与 4 个测试）。设备端不是 Python，服务端又明令不用 |
| `core.posture_contract_canonicalization` | 接到 posture 写入处 / 删 | 先看 posture 实际在哪几处产生；只有一两处就接，否则删 |
| `core.truth_conflict_enforcement` | 接到真相写入点 / 删 / 冻结 | 接线要改 UDM / CanonicalTask / 会话真相的**热路径**，风险最高；倾向删或明确标为冻结 |
| 无测试的动作类与事件回调（159 条） | 逐条删 / 接 | 逐条过，多数应删 |
| 有测试、无调用方的动作类（188 条） | 逐条删 / 接 | 逐条过；先看是否已被别的实现取代 |
| 查询、谓词、序列化、复位钩子（408 条） | 豁免 / 保持在基线 | 保持在基线即可；复位钩子可整类加进 `check_wiring.py` 的豁免 |

<!-- BEGIN GENERATED: scripts/unwired_inventory.py --write -->

未接线公开能力 **755** 条，分布在 **359** 个文件。

| 维度 | 数 |
|---|---|
| 类方法 / 模块函数 | 486 / 269 |
| 只有测试在引用（写了、测了、没接） | 500 |
| 全仓连测试都没引用 | 255 |
| 所在模块本身从入口不可达 | 4 |

### 按名字表明的角色

| 角色 | 合计 | 其中只有测试引用 | 其中连测试都没有 |
|---|---|---|---|
| 测试复位钩子 | 34 | 28 | 6 |
| 序列化/转换 | 27 | 14 | 13 |
| 事件回调 | 12 | 5 | 7 |
| 判定谓词 | 106 | 86 | 20 |
| 只读查询 | 129 | 96 | 33 |
| 计算/构造 | 112 | 88 | 24 |
| 动作/变更 | 335 | 183 | 152 |

### 按用途

| 用途 | 条数 | 其中只有测试引用 | 其中连测试都没有 | 文件数 |
|---|---|---|---|---|
| 节点服务里的方法 | 47 | 2 | 45 | 26 |
| 安卓协作的契约、治理与对账层 | 83 | 76 | 7 | 40 |
| 持久化、重启恢复与断点续跑 | 52 | 47 | 5 | 13 |
| 指标、可观测与审计记录 | 51 | 48 | 3 | 21 |
| 架构治理：权威声明、边界断言与自检 | 96 | 86 | 10 | 44 |
| 多设备编组、协同网络与拓扑 | 50 | 39 | 11 | 25 |
| 设备与节点：注册、发现、连接、通信、传输 | 109 | 43 | 66 | 45 |
| 能力、模型与执行路由 | 76 | 52 | 24 | 39 |
| 智能体、认知与记忆 | 84 | 38 | 46 | 45 |
| 语音、桌面在场与感知 | 27 | 22 | 5 | 17 |
| 配置、启动、安全、扩展与通用基础件 | 80 | 47 | 33 | 44 |

### 按子系统

| 子系统 | 条数 | 文件数 |
|---|---|---|
| `core/（其余单文件）` | 271 | 134 |
| `galaxy_gateway/` | 53 | 27 |
| `core/capability_*` | 25 | 9 |
| `core/device_*` | 25 | 10 |
| `core/node_*` | 23 | 8 |
| `core/android_*` | 20 | 13 |
| `core/delegated_*` | 20 | 5 |
| `core/cognitive/` | 19 | 8 |
| `core/unified/` | 19 | 8 |
| `core/mesh/` | 18 | 8 |
| `core/orchestration/` | 18 | 7 |
| `core/ugcp_*` | 15 | 3 |
| `nodes/Node_71_MultiDeviceCoordination/` | 15 | 7 |
| `core/task_*` | 11 | 6 |
| `core/attached_runtime_*` | 10 | 5 |
| `core/hybrid_*` | 10 | 2 |
| `core/model_topology/` | 10 | 5 |
| `core/desktop_*` | 9 | 3 |
| `core/canonical_*` | 8 | 3 |
| `core/runtime/` | 8 | 3 |
| `core/v2_*` | 8 | 2 |
| `core/control_plane/` | 7 | 5 |
| `core/cross_*` | 7 | 3 |
| `core/execution_observability/` | 7 | 4 |
| `core/continuation_*` | 6 | 1 |
| `core/flow_*` | 6 | 1 |
| `core/truth_*` | 6 | 3 |
| `launcher/` | 6 | 5 |
| `core/governance/` | 5 | 2 |
| `core/runtime_*` | 5 | 3 |
| `core/adapters/` | 4 | 3 |
| `core/nodes/` | 4 | 1 |
| `nodes/Node_70_AutonomousLearning/` | 4 | 1 |
| `core/agentic/` | 3 | 1 |
| `core/continuum/` | 3 | 2 |
| `core/device_formation/` | 3 | 2 |
| `core/multimodal/` | 3 | 1 |
| `core/perception/` | 3 | 2 |
| `core/presence/` | 3 | 2 |
| `core/resilience/` | 3 | 2 |
| `core/session_*` | 3 | 2 |
| `nodes/Node_112_SelfHealing/` | 3 | 1 |
| `nodes/Node_116_ExternalToolWrapper/` | 3 | 1 |
| `nodes/Node_43_MAVLink/` | 3 | 1 |
| `core/agent/` | 2 | 2 |
| `core/capability_runtime/` | 2 | 2 |
| `core/cross_device_policy/` | 2 | 1 |
| `core/tts/` | 2 | 1 |
| `nodes/Node_05_Auth/` | 2 | 1 |
| `nodes/Node_109_ProactiveSensing/` | 2 | 1 |
| `nodes/Node_54_SymbolicMath/` | 2 | 1 |
| `nodes/Node_72_KnowledgeBase/` | 2 | 1 |
| `core/audit_layer/` | 1 | 1 |
| `core/capabilities/` | 1 | 1 |
| `core/execution/` | 1 | 1 |
| `core/execution_*` | 1 | 1 |
| `core/generative_ui/` | 1 | 1 |
| `core/interaction/` | 1 | 1 |
| `core/operator_*` | 1 | 1 |
| `core/orchestration*` | 1 | 1 |
| `core/output/` | 1 | 1 |
| `core/persona/` | 1 | 1 |
| `core/queueing/` | 1 | 1 |
| `core/reliability_contract/` | 1 | 1 |
| `core/routing_explanation/` | 1 | 1 |
| `nodes/Node_04_Router/` | 1 | 1 |
| `nodes/Node_106_GitHubFlow/` | 1 | 1 |
| `nodes/Node_108_MetaCognition/` | 1 | 1 |
| `nodes/Node_110_SmartOrchestrator/` | 1 | 1 |
| `nodes/Node_127_BambuLab/` | 1 | 1 |
| `nodes/Node_14_FFmpeg/` | 1 | 1 |
| `nodes/Node_33_ADB/` | 1 | 1 |
| `nodes/Node_50_Transformer/` | 1 | 1 |
| `nodes/Node_58_ModelRouter/` | 1 | 1 |
| `nodes/Node_74_DigitalTwin/` | 1 | 1 |
| `nodes/Node_89_APIGateway/` | 1 | 1 |

### 从真实入口不可达的模块

| 模块 | 行数 |
|---|---|
| `core.local_agent_runtime` | 423 |
| `core.posture_contract_canonicalization` | 331 |
| `core.truth_conflict_enforcement` | 979 |

### 逐文件清单

按用途分组，每个函数后面是它**自己的说明**（docstring 第一行，原文照录；没写说明的标「无说明」）。
标记：`T` 只有测试在引用；`—` 连测试都没有。

<details><summary>节点服务里的方法 — 47 条</summary>

- `nodes/Node_04_Router/qwen_think_logic.py`
  - `QwenThinkRouter.plan_route` — — 利用 Qwen-Think-Max 进行深度思考并生成执行计划
- `nodes/Node_05_Auth/main.py`
  - `AuthManager.has_permission` — — 检查权限
  - `AuthManager.delete_user` — — 删除用户
- `nodes/Node_106_GitHubFlow/main.py`
  - `GitHubClient.create_pull_request` — — 创建 Pull Request
- `nodes/Node_108_MetaCognition/main.py`
  - `MetaCognitionEngine.comprehend` — — 理解层 - 分析和理解感知到的信息
- `nodes/Node_109_ProactiveSensing/main.py`
  - `ProactiveSensingEngine.unregister_sensor` — — 注销传感器
  - `ProactiveSensingEngine.remove_rule` — — 移除感知规则
- `nodes/Node_110_SmartOrchestrator/main_enhanced.py`
  - `QwenEnhancedOrchestrator.think_and_plan` — — 无说明
- `nodes/Node_112_SelfHealing/main.py`
  - `SelfHealingEngine.unregister_health_check` — — 注销健康检查
  - `SelfHealingEngine.register_recovery_handler` — — 注册恢复处理器
  - `SelfHealingEngine.run_once` T — 执行一轮自主自愈循环（Loop 1）：
- `nodes/Node_116_ExternalToolWrapper/main.py`
  - `ExternalToolWrapper.unregister_tool` — — 注销工具
  - `ExternalToolWrapper.register_custom_handler` — — 注册自定义处理器
  - `ExternalToolWrapper.execute_custom` — — 执行自定义工具
- `nodes/Node_127_BambuLab/enhanced_bambu_controller.py`
  - `EnhancedBambuController.add_to_history` — — 添加打印记录到历史
- `nodes/Node_14_FFmpeg/main.py`
  - `FFmpegManager.merge_videos` — — 合并视频
- `nodes/Node_33_ADB/cluster_manager.py`
  - `ADBClusterManager.parallel_execute` — — 在多个设备上并行执行命令
- `nodes/Node_43_MAVLink/universal_drone_controller.py`
  - `UniversalDroneController.start_recording` — — 开始录像
  - `UniversalDroneController.stop_recording` — — 停止录像
  - `UniversalDroneController.execute_waypoint_mission` — — 执行航点任务
- `nodes/Node_50_Transformer/enhanced_nlu_engine.py`
  - `EnhancedNLUEngine.generate_software_command` — — 生成软件操作命令
- `nodes/Node_54_SymbolicMath/main.py`
  - `CrossDisciplinaryVerifier.verify_physics` — — Verify physics formula.
  - `CrossDisciplinaryVerifier.verify_engineering` — — Verify engineering formula.
- `nodes/Node_58_ModelRouter/main.py`
  - `DatabaseManager.save_session_turn` T — Save a session turn to database.
- `nodes/Node_70_AutonomousLearning/core/autonomous_learning_engine.py`
  - `AutonomousLearningEngine.generalize_skill` — — 从模式中泛化技能
  - `AutonomousLearningEngine.find_similar_skills` — — 基于相似度查找相关技能
  - `AutonomousLearningEngine.process_observation` — — 处理 VLM 观察结果，生成下一步行动计划（增强版）
  - `AutonomousLearningEngine.update_experience_outcome` — — 更新经验结果（用于强化学习反馈）
- `nodes/Node_71_MultiDeviceCoordination/core/canonical_device_view_adapter.py`
  - `CoordinationDeviceView.mark_task_assigned` — — Record a coordination-local task assignment.
  - `CoordinationDeviceView.mark_task_released` — — Record that a task has been released from this device.
- `nodes/Node_71_MultiDeviceCoordination/core/device_discovery.py`
  - `DeviceDiscovery.add_device` — — 将已发现设备登记进本地发现表(规范写口)。
  - `DeviceDiscovery.discover_now` — — 立即执行发现
- `nodes/Node_71_MultiDeviceCoordination/core/fault_tolerance.py`
  - `FailoverManager.set_primary` — — 设置主设备
  - `FailoverManager.add_secondary` — — 添加备用设备
  - `FailoverManager.remove_secondary` — — 移除备用设备
  - `FailoverManager.register_health_checker` — — 注册健康检查函数
- `nodes/Node_71_MultiDeviceCoordination/core/state_synchronizer.py`
  - `StateSynchronizer.handle_gossip_message` — — 处理 Gossip 消息
- `nodes/Node_71_MultiDeviceCoordination/main.py`
  - `Device.to_unified_model` — — 转换为统一 DeviceModel。
  - `Device.from_unified_model` — — 从统一 DeviceModel 创建 Node_71 Device。
- `nodes/Node_71_MultiDeviceCoordination/models/device.py`
  - `DeviceRegistry.count_by_state` — — 按状态统计设备数
- `nodes/Node_71_MultiDeviceCoordination/models/task.py`
  - `Task.update_progress` — — 更新进度
  - `TaskQueue.dequeue` — — 出队
  - `TaskQueue.is_empty` — — 是否为空
- `nodes/Node_72_KnowledgeBase/knowledge_base_system.py`
  - `KnowledgeBaseSystem.export_knowledge` — — 导出知识库到 JSON 文件
  - `KnowledgeBaseSystem.import_knowledge` — — 从 JSON 文件导入知识库
- `nodes/Node_74_DigitalTwin/main.py`
  - `TwinDeviceRegistration.to_registered_runtime_device` — — 投影到唯一规范单设备读契约 RegisteredRuntimeDevice(专项③ anti-drift 锚定)。
- `nodes/Node_89_APIGateway/main.py`
  - `GatewayService.proxy_via_route` — — 无说明

</details>

<details><summary>安卓协作的契约、治理与对账层 — 83 条</summary>

- `core/android_acceptance_evidence_store.py`
  - `clear_device_acceptance_evidence` T — 清理 acceptance 证据（测试辅助）。
- `core/android_delegated_runtime_audit.py`
  - `record_delegated_execution_signal` T — Record receipt of an Android ``delegated_execution_signal`` wire event.
- `core/android_delegated_runtime_lifecycle_coordinator.py`
  - `AndroidDelegatedRuntimeLifecycleCoordinator.on_participant_truth_update` T — Handle an explicit Android participant truth update message.
- `core/android_device_state_store.py`
  - `reset_android_device_state_store` T — Reset the singleton (for test isolation only).
- `core/android_evaluator_artifact_ingress.py`
  - `AndroidEvaluatorArtifactRegistry.list_for_kind` — — Return up to *n* most-recent artifacts of the given *kind*.
- `core/android_mode_gate_policy.py`
  - `apply_mode_switch_to_registry` T — Apply mode-switch semantics to the AttachedRuntimeSessionRegistry entry.
- `core/android_network_participation.py`
  - `apply_participation_signal` T — Return a new :class:`AndroidNetworkParticipationState` after applying *signal*.
- `core/android_nl_semantic_chain_contract.py`
  - `is_android_nl_carrier` T — Return True when *source* is one of the recognized Android NL transport sources.
  - `build_android_nl_carrier_context` T — Build a canonical Android NL ingress_carrier_context dict.
  - `assert_v2_is_semantic_authority` T — Assert that *result* confirms V2 as the LLM semantic authority.
  - `assert_android_nl_carrier` T — Assert that *result* confirms an Android device is the NL carrier.
  - `assert_nl_path_type` T — Assert that *result* has the expected ``nl_path_type`` in its carrier context.
- `core/android_originated_authority_boundary.py`
  - `is_android_main_chain_eligible` T — Return True iff this participation type MUST enter the V2 main chain.
  - `assert_android_cannot_override_center` T — Assert that a classification never grants center authority override.
- `core/android_participant_evidence_ingress.py`
  - `AndroidParticipantStatus.is_negative` T — Return True for statuses that indicate the participant is not ready.
  - `build_android_participant_evidence_summary` T — Build a governance/audit summary dict for the Android participant evidence.
- `core/android_participant_truth_ingress.py`
  - `AndroidParticipantTruthKind.affects_canonical_state` T — Return True iff this kind materially updates V2 canonical state.
  - `AndroidParticipantTruthKind.is_non_closure_signal` — — Return True iff this kind must never assert canonical task closure.
- `core/android_v2_canonical_default_runtime_path.py`
  - `classify_android_v2_path` T — Classify the current Android-V2 runtime path.
- `core/android_v2_continuity_contract.py`
  - `is_android_v2_continuity_healthy` T — Return True iff the joint continuity contract snapshot has no failures.
- `core/attached_runtime_recovery_readiness.py`
  - `clear_seq_context_for_reconnect` T — Clear the sequence-index entry for *context_key* after a reconnect.
- `core/attached_runtime_reuse_binding.py`
  - `ReuseInvalidationReason.is_lifecycle_invalidation` T — Return True if the reason stems from an attachment lifecycle signal.
  - `AttachedRuntimeReuseBindingRecord.is_invalidated` T — Return True if the binding has been invalidated.
  - `AttachedRuntimeReuseBindingRecord.has_dispatch_binding` T — Return True if a dispatch binding id has been registered.
- `core/attached_runtime_reuse_dispatch.py`
  - `ReuseDispatchResolution.is_reusable` T — Return ``True`` when the resolution kind is ``reused``.
  - `ReuseDispatchResolution.has_no_binding` T — Return ``True`` when the resolution kind is ``no_binding``.
  - `ReuseDispatchResolution.is_new_binding` T — Return ``True`` when the resolution kind is ``new_binding``.
- `core/attached_runtime_session.py`
  - `AttachedRuntimeSessionRecord.is_eligible_for_execution` T — Return True if this session is eligible for execution scheduling.
- `core/attached_runtime_session_registry.py`
  - `lookup_session_by_attachment_id` T — Look up a registry entry by *runtime_attachment_session_id*.
  - `record_mode_switch_in_session` T — Record a mode transition in the active session entry for *device_id*.
- `core/conversation_continuity_truth.py`
  - `ConversationContinuityClass.is_terminal_loss` T — True when continuity is definitively lost and cannot be inferred.
- `core/cross_repo_protocol_consistency.py`
  - `is_canonical_surface` T — Return True iff the surface with *surface_id* is classified as canonical.
- `core/delegated_flow_entity.py`
  - `DelegatedFlowPhase.is_executing_or_later` T — Return True if Android execution has begun (executing, reconciling, or terminal).
- `core/delegated_flow_post_graduation_governance.py`
  - `GovernanceVerdict.is_violation` T — Return ``True`` when the verdict is any
- `core/full_system_baseline_v3.py`
  - `V3BaselineReport.blocking_subsystems` T — Return all entries whose state prevents a closed verdict.
- `core/inflight_task_continuity_contract.py`
  - `TaskContinuityStatus.requires_action` T — True when explicit external action is required to proceed.
- `core/inflight_task_continuity_taxonomy.py`
  - `build_task_continuity_verdict_from_report` T — Build a verdict directly from a :class:`~core.inflight_task_continuity_contract
- `core/mesh/android_mesh_participant_signal_adapter.py`
  - `classify_android_proof_quality_for_signals` T — Convenience wrapper: classify proof quality from a raw signal list.
  - `evaluate_center_runtime_status_with_android_signals` T — Evaluate center-side mesh runtime status driven by real Android signals.
  - `apply_android_participation_signals_batch` T — Apply a list of Android participation signals to a coordinator.
- `core/offline_replay_ordering_contract.py`
  - `evaluate_replay_sequence` T — Evaluate a replay sequence against the V2 offline replay ordering contract.
- `core/pr3_session_continuity_authority.py`
  - `govern_takeover_decision` T — Apply takeover governance rules for the given proof quality class.
  - `classify_local_ai_proposal` T — Classify an Android local-AI proposal against center authority.
- `core/pr4_operator_action_governance.py`
  - `clear_operator_action_audit_log` T — Clear the in-process audit log.  For testing only.
- `core/takeover_tracking.py`
  - `TakeoverTrackingRecord.was_rejected` T — Return True when the takeover was rejected.
  - `list_takeover_records_for_session` T — Return all :class:`TakeoverTrackingRecord` instances for *session_id*,
  - `takeover_tracking_snapshot` T — Return a :class:`TakeoverTrackingSnapshot` of the ring buffer.
- `core/ugcp_control_transfer_profile.py`
  - `map_from_dispatch_preparation_state` T — 无说明
  - `map_from_handoff_contract_status` T — 无说明
  - `map_from_takeover_status` T — 无说明
  - `map_from_delegated_signal` T — Map Android delegated signal kinds into canonical transfer state.
  - `infer_terminal_reason` T — 无说明
  - `build_transfer_merge_reason` T — 无说明
- `core/ugcp_coordination_profile.py`
  - `map_from_mesh_session_status` T — 无说明
  - `map_from_coordinator_status` T — 无说明
  - `map_from_participant_role` T — 无说明
  - `map_from_authority_scope` T — 无说明
  - `map_from_barrier_status` T — 无说明
  - `map_from_aggregation_mode` T — 无说明
  - `infer_terminal_outcome` T — 无说明
  - `build_coordination_merge_reason` T — 无说明
- `core/ugcp_truth_event_model.py`
  - `is_authoritative_transition_event` T — 无说明
- `core/v2_android_recovery_continuity_hardening.py`
  - `classify_session_reuse` T — Classify a session reuse attempt against real Android reconnect behavior.
  - `assess_attached_runtime_truth` T — Grade the truth of an attached Android runtime before delegation.
  - `classify_evidence_ingress` T — Classify the provenance of incoming recovery evidence.
  - `assess_recovery_closure_quality` T — Assess the quality of a recovery closure for a device/session.
  - `classify_result_delivery` T — Classify an inbound Android result relative to the task context.
  - `interpret_replay_sequence` T — Interpret an offline replay sequence against real Android behavioral constraints.
  - `build_recovery_participation_report` T — Assemble a full recovery participation report for a device/session.
- `core/v2_android_truth_ssot.py`
  - `build_v2_android_truth_block_multi` T — 为多个设备批量构建 Android truth block。
- `galaxy_gateway/android/handlers/generic.py`
  - `is_generic_forward_blocked_message_type` T — Return whether a message type must bypass generic forward.
  - `is_generic_forward_compat_message_type` T — Return whether a message type is allowed through generic-forward compat gate.
- `galaxy_gateway/android/handlers/registration.py`
  - `clear_registration_gaps` T — Remove registration gap records.
  - `handle_device_reconnect` — — Handle an explicit ``device_reconnect`` wire message.
- `galaxy_gateway/android/handlers/wearos_sync.py`
  - `handle_wearos_state_sync` — — Send state sync to Wear OS device.
- `galaxy_gateway/android_bridge.py`
  - `AndroidBridge.route_liquid_message` — — 灵动岛式消息路由。
  - `AndroidBridge.route_phase_change` — — Phase 变化的灵动岛式路由。
  - `AndroidBridge.cache_transport_handle` T — 将设备的 transport/session handle 写入 bridge 拥有的 operational cache。
  - `AndroidBridge.push_decision_to_wearos` — — 向 WearOS 设备推送决策通知。
  - `AndroidBridge.query_elements` T — Android GUI action adapter — translate element query to AIP protocol and send.
  - `AndroidBridge.send_takeover_request` T — Send a ``takeover_request`` downlink to an Android device.
  - `AndroidBridge.reconnect_device` T — 重新连接设备（WebSocket 断线重连时调用）.
- `galaxy_gateway/android_granular_adapter.py`
  - `AndroidGranularAdapter.dispatch_aip_message` T — Dispatch an AIP v3 message to the corresponding Android operation.

</details>

<details><summary>持久化、重启恢复与断点续跑 — 52 条</summary>

- `core/continuation_rebind_registry.py`
  - `ContinuationRebindRegistry.register_new_waiter` T — Record that a new waiter has been registered for *task_id* after re-dispatch.
  - `ContinuationRebindRegistry.is_pending_rebind` T — Return True if *task_id* is waiting for a rebind (re-dispatch pending).
  - `ContinuationRebindRegistry.is_loop_closed` T — Return True if the complete continuation loop for *task_id* is closed.
  - `ContinuationRebindRegistry.pending_rebind_count` T — Return the number of tasks still waiting for a rebind.
  - `ContinuationRebindRegistry.rebound_count` T — Return the number of tasks that have had a new waiter registered.
  - `ContinuationRebindRegistry.list_pending_task_ids` T — Return a list of task IDs that are still in pending_rebind state.
- `core/delegated_flow_decision_history.py`
  - `HistoryEvidenceStatus.allows_runtime_closure` T — Return ``True`` only when status permits runtime_closure_established=True.
  - `HistoryEvidenceStatus.is_definitive_gap` T — Return ``True`` when the status represents a clear evidence deficit.
  - `record_delegated_flow_event` T — Record a delegated flow event in the process-global singleton registry.
- `core/delegated_flow_persistence.py`
  - `DelegatedFlowPersistenceBundle.persist_all` T — Persist all four object categories in one call.
  - `persist_session_snapshot` T — Persist *sessions* to the durable session store.
  - `restore_sessions` T — Restore session entries from the durable store.
  - `persist_contract_snapshot` T — Persist *contracts* to the durable contract store.
  - `restore_contracts` T — Restore contract records from the durable store.
  - `persist_binding_snapshot` T — Persist *bindings* to the durable binding store.
  - `restore_bindings` T — Restore binding records from the durable store.
  - `persist_flow_entity_snapshot` T — Persist *flow_entities* to the durable flow-entity store.
  - `restore_flow_entities` T — Restore flow-entity objects from the durable store.
- `core/delegated_flow_recovery_coordinator.py`
  - `DelegatedFlowRecoveryCoordinator.list_recent_attempts` T — Return the *n* most-recent attempt records, newest first.
  - `decide_recovery` T — Convenience wrapper: decide recovery action for *flow_id*.
  - `decide_recovery_from_continuity_artifact` T — Convenience wrapper: decide recovery using a ContinuityDecisionArtifact.
  - `begin_recovery_attempt` T — Convenience wrapper: begin a new recovery attempt for *flow_id*.
  - `complete_recovery_attempt` T — Convenience wrapper: mark a recovery attempt as completed/failed.
  - `suppress_recovery_attempt` T — Convenience wrapper: explicitly suppress a recovery attempt.
- `core/flow_continuity_coordinator.py`
  - `coordinate_attach` T — Convenience wrapper: decide continuity for a fresh Android attach.
  - `coordinate_reattach_process_recreation` T — Convenience wrapper: decide continuity for process-recreation re-attach.
  - `coordinate_stale_identity` T — Convenience wrapper: decide continuity for a stale-identity signal.
  - `coordinate_duplicate_signal` T — Convenience wrapper: decide continuity for a potential duplicate signal.
  - `coordinate_partial_result` T — Convenience wrapper: decide continuity for a partial-result delivery.
  - `coordinate_v2_restart_recovery` T — Convenience wrapper: decide continuity after a V2 restart.
- `core/hybrid_orchestration_continuity.py`
  - `HybridOrchestrationContinuityRegistry.list_non_terminal` T — Return all records in non-terminal states.
  - `HybridOrchestrationContinuityRegistry.list_terminal` T — Return all records in terminal states.
  - `HybridOrchestrationContinuityRegistry.list_interrupted` T — Return all records in the ``interrupted`` state.
  - `HybridOrchestrationContinuityRegistry.clear_terminal` T — Remove all terminal records from the registry.
  - `save_hybrid_execution` — — Persist *record* to the durable store.
  - `load_hybrid_execution` T — Load a record by *execution_id* from the durable store.
  - `recover_hybrid_executions` T — Return restart-normalised, non-terminal records from the durable store.
- `core/mesh/mesh_session_lifecycle.py`
  - `MeshSessionLifecycleCoordinator.list_active_session_ids` T — Return a list of session IDs currently in ACTIVE status.
  - `MeshSessionLifecycleCoordinator.list_restorable_session_ids` — — Return a list of session IDs that are restorable (SUSPENDED).
  - `associate_resumed_execution_with_session` T — Associate a resumed execution with an active mesh session (PR-F).
- `core/recovery_truth_surface.py`
  - `RecoveryLevel.all_levels` T — 无说明
  - `RecoveryTruthReport.has_deferred` T — Return True when at least one dimension is explicitly deferred.
- `core/replay_audit_persistence.py`
  - `load_audit_records` T — Load audit records from the durable store.
- `core/replay_foundation.py`
  - `ReplayFoundation.replay_task_timeline` T — Return an ordered list of event dicts suitable for time-travel replay.
- `core/task_envelope_lifecycle_registry.py`
  - `TaskEnvelopeLifecycleRegistry.cancel_timed_out` — — Cancel all pending envelopes whose wall-clock age exceeds their timeout.
  - `TaskEnvelopeLifecycleRegistry.resume_for_device` — — Surface or retry pending envelopes for a reconnected device.
  - `TaskEnvelopeLifecycleRegistry.all_pending_task_ids` — — Return a snapshot list of currently pending task_ids.
- `core/task_graph_runtime.py`
  - `TaskGraphRuntime.register_fanin` T — Register a multi-target fanin from multiple children to one aggregator.
  - `result_envelope_to_node_update` T — Apply a ``ResultEnvelope`` (or compatible object) to a ``GraphNode``.
  - `project_workflow_to_graph` T — Project a workflow execution record dict onto the task graph runtime.
- `core/task_lifecycle.py`
  - `TaskLifecycleManager.mark_interrupted` T — Transition envelope to 'interrupted' terminal state.
  - `TaskLifecycleManager.run_with_lifecycle` T — Execute ``coro_factory(envelope)`` with automatic lifecycle bookkeeping.

</details>

<details><summary>指标、可观测与审计记录 — 51 条</summary>

- `core/audit_event_semantics.py`
  - `audit_route_decision` T — Emit a ROUTE_DECISION audit record.
  - `audit_policy_decision` T — Emit a POLICY_DECISION audit record.
  - `audit_failure_domain` T — Emit a FAILURE_DOMAIN_IDENTIFIED audit record.
- `core/control_plane/audit_ledger.py`
  - `AuditLedger.verify_chain` T — 校验哈希链完整性。返回 ``{"intact": bool, "count": int, "broken_at": int\|None}``。
  - `AuditLedger.to_dag` T — Return the full ledger as a DAG adjacency list.
- `core/decision_diff_telemetry.py`
  - `clear_diff_store` T — Clear all records from the in-memory ring buffer (for testing).
  - `record_candidate_diff` T — Record a cross-device candidate selection legacy-vs-canonical diff.
- `core/decision_timeline.py`
  - `record_source_switch_event` T — Convenience builder: derive and record a ``source_switch`` event from a
- `core/device_activation_registry.py`
  - `DeviceActivationRegistry.export_json` — — Export recent records as JSON-serializable dicts.
- `core/execution_observability/event_schema.py`
  - `ExecutionEvent.projection_summary` T — Return a compact summary suitable for Status Board / Manifest consumers.
- `core/execution_observability/executor_level.py`
  - `ExecutorLevel.from_win_exec_level` T — Convert a ``WinExecLevel`` enum value (or its string repr).
- `core/execution_observability/normalizers.py`
  - `normalize_e2e_context` T — Build an :class:`ExecutionEvent` from a ``core/e2e_orchestrator.py``
  - `normalize_task_envelope` T — Build an :class:`ExecutionEvent` from a ``TaskEnvelope`` or similar
  - `normalize_task_graph_result` T — Build an :class:`ExecutionEvent` from a ``TaskGraph.run()`` result dict.
  - `normalize_arbiter_attempt` T — Build an :class:`ExecutionEvent` from a ``WinExecAttempt`` (arbiter log).
- `core/execution_observability/trace_schema.py`
  - `TraceCorrelation.from_task_graph` T — Normalise from a :class:`~core.task_graph.TaskGraph` instance.
- `core/log_redaction.py`
  - `redact_secret` — — 把一个**已知是密钥**的值脱敏。
- `core/operational_slo_metrics.py`
  - `OperationalSLOMetrics.record_dispatch_attempt` T — Record one task dispatch attempt.
  - `OperationalSLOMetrics.record_dispatch_success` T — Record a successful task dispatch outcome.
  - `OperationalSLOMetrics.record_dispatch_failure` T — Record a failed task dispatch outcome.
  - `OperationalSLOMetrics.record_route_rejection` T — Record one route rejection with its reason.
  - `OperationalSLOMetrics.record_fallback_triggered` T — Record one fallback trigger.
  - `OperationalSLOMetrics.record_recovery_attempt` T — Record one recovery attempt (regardless of outcome).
  - `OperationalSLOMetrics.record_recovery_resumed` T — Record one recovery that resulted in a resumed execution.
  - `OperationalSLOMetrics.record_recovery_replayed` T — Record one recovery that resulted in a replayed execution.
  - `OperationalSLOMetrics.record_recovery_reissued` T — Record one recovery that resulted in a reissued dispatch.
  - `OperationalSLOMetrics.record_recovery_failed` T — Record one recovery attempt that failed.
  - `OperationalSLOMetrics.record_startup_recovery_scan` T — Record the outcome of a startup recovery scan.
  - `OperationalSLOMetrics.record_audit_persist_success` T — Record one successful durable audit record write.
  - `OperationalSLOMetrics.record_audit_persist_failure` T — Record one failed durable audit record write.
- `core/operator_execution_observability_surface.py`
  - `OperatorExecutionEvidenceEntry.requires_operator_attention` T — True iff operator intervention or review is indicated.
- `core/orchestration_review_surface.py`
  - `increment_legacy_dispatch_counter` T — Increment the legacy dispatch counter for a named compat surface.
- `core/protocol_drift_registry.py`
  - `drift_entries` T — 当前登记的全部漂移记录(按出现次数降序)。
  - `drift_summary` T — 给就绪/诊断面用的摘要。
  - `has_unrecognized_drift` T — 是否见过**不认识的取值**(契约已分叉的信号)。
  - `reset_protocol_drift_registry` T — 清空登记表。给测试用 —— 生产路径不该调用。
- `core/resilience/metrics.py`
  - `ResilienceMetrics.record_circuit_open` T — 无说明
  - `ResilienceMetrics.rejection_rate_per_minute` T — Rejections in the last 60 s (rolling window).
- `core/routing_explanation/live_decision.py`
  - `LiveRoutingDecisionBuilder.record_policy_band` — — Record the execution-policy band active at dispatch time.
- `core/routing_observability.py`
  - `ControlLoopMetrics.record_projection_mismatch` T — Increment the projection/control mismatch counter.
  - `reset_routing_metrics` T — Reset the global :class:`ControlLoopMetrics` singleton (primarily for tests).
  - `build_fallback_decision_event` T — Build a :class:`FallbackDecisionEvent` from a :class:`RoutingDecisionEvent`.
  - `build_routing_analytics_snapshot` T — Build a :class:`RoutingAnalyticsSnapshot` from the current global metrics.
- `core/runtime/runtime_observability_sink.py`
  - `RuntimeObservabilitySink.list_device_lifecycle_events` T — Return a copy of the current device lifecycle event buffer.
  - `RuntimeObservabilitySink.list_mesh_session_transition_events` T — Return a copy of the current mesh session transition event buffer.
  - `RuntimeObservabilitySink.list_dispatch_decision_events` T — Return a copy of the current dispatch decision event buffer.
  - `RuntimeObservabilitySink.list_recovery_decision_events` T — Return a copy of the current recovery decision event buffer.
  - `RuntimeObservabilitySink.counters` T — Return total emit counts per event kind.
- `core/slo_metrics.py`
  - `SLOMetrics.startup_duration_ms` T — Startup duration in milliseconds, or ``None`` if not yet recorded.
- `core/task_cost_ledger.py`
  - `current_task_bill` T — 无说明
- `galaxy_gateway/observability.py`
  - `TraceContext.child_span` T — Return a new TraceContext with the same trace_id and a fresh span_id.

</details>

<details><summary>架构治理：权威声明、边界断言与自检 — 96 条</summary>

- `core/acl.py`
  - `AntiCorruptionLayer.validate_mcp_call` — — Validate MCP tool call request from LLM.
  - `AntiCorruptionLayer.validate_worker_registration` — — Validate worker registration on first connect.
- `core/audit_layer/fresh_dual_repo_code_audit.py`
  - `assert_fresh_audit_invariants` T — Assert that the fresh audit sentinels are internally consistent.
- `core/authority_conflict_elimination.py`
  - `assert_no_competing_authority` T — Assert that no competing authority exists for *fact_name*.
- `core/bounded_subject_platform_boundary.py`
  - `assert_quasi_platform_state_intact` T — Assert that all five platform boundary axes are intact.
- `core/canonical_ownership_truth_bridge.py`
  - `is_recovery_eligible` T — Return ``True`` when *ownership_boundary* allows canonical recovery admission.
  - `build_ownership_aware_replay_execution_record` T — Return a copy of *base_record* with ``participant_ownership_boundary`` populated.
- `core/capability_tier.py`
  - `require_main_chain_capability` T — Assert MAIN_CHAIN and return the tier (convenience wrapper).
  - `list_capabilities_by_tier` T — Return all capability names registered under *tier*.
- `core/compat_fallback_authority_guard.py`
  - `assert_canonical_is_decision_authority` T — Assert that the canonical path is the primary decision authority.
  - `build_authority_hardening_snapshot` T — Build an aggregate snapshot of the authority hardening posture.
  - `block_compat_influence_at_decision_site` T — Evaluate a compat/legacy influence using the PR-8 blocking gate.
- `core/compat_legacy_path_blocking_canonicalization.py`
  - `CompatLegacyBlockingRecord.is_quarantined` T — Return True when this record represents a quarantine decision.
- `core/critical_path_harness.py`
  - `record_ingress_path` T — Record a multimodal ingress event in the harness ring buffer.
  - `record_execution_dispatch` T — Record an execution dispatch event in the harness ring buffer.
  - `snapshot_critical_path` T — Return a plain-dictionary snapshot of the critical path harness.
- `core/cross_device_dispatch_boundary.py`
  - `classify_dispatch_call` T — Classify a cross-device dispatch call into one of the four boundary
  - `is_canonical_dispatch` T — Return True when the call follows the primary canonical path.
  - `is_controlled_fallback` T — Return True when the call is a controlled canonical fallback.
  - `is_compat_fallback` T — Return True when the call is a compat fallback.
  - `is_legacy_bypass` T — Return True when the call is a legacy bypass.
- `core/device_node_domain_governance.py`
  - `classify_registry_surface` T — Look up a registry surface classification by its module path.
- `core/governance/budget_enforcer.py`
  - `BudgetEnforcer.enforce_pre_call` T — Check budgets before an LLM call.
  - `BudgetEnforcer.reset_session` T — Reset a session's cost counter (call when session ends).
  - `BudgetEnforcer.all_session_ids` — — Return all tracked session IDs.
- `core/governance/tool_governor.py`
  - `ToolGovernor.clear_audit_log` — — Clear the in-memory audit log.
  - `ToolGovernor.reset_bucket` T — Reset the token bucket for *tool_name* (useful in tests).
- `core/governance_validation_gate.py`
  - `evaluate_governance_validation` T — Module-level convenience function — evaluate governance validation.
- `core/health_evidence_policy.py`
  - `has_health_evidence` T — 这台设备有没有健康证据。
- `core/mainline_convergence.py`
  - `MainlineMetadataFrame.is_mainline` T — ``True`` when this frame carries the canonical authority role.
  - `MainlineExecutionTrace.visits_openclawd` T — ``True`` when the trace passed through the OpenClawd authority stage.
  - `MainlineExecutionTrace.visits_capability_dispatch` T — ``True`` when capability dispatch was used.
  - `MainlineExecutionTrace.visits_knowledge` T — ``True`` when any knowledge-core stage was visited.
  - `MainlineConvergenceRegistry.record_from_response` T — Extract and record a trace from an OpenClawd response dict.
  - `MainlineConvergenceRegistry.list_by_path_class` T — Return traces whose ``path_class`` matches *path_class*.
  - `MainlineConvergenceRegistry.assert_mainline_dominant` T — Return ``True`` when mainline traces dominate.
  - `reset_mainline_convergence_registry` T — Reset the module-level singleton (test helper).
  - `record_mainline_execution` T — Build, close, and record a :class:`MainlineExecutionTrace` in one call.
- `core/multi_device_canonical_governance.py`
  - `MultiDeviceGovernanceVerdict.is_single_device` T — Return ``True`` when verdict indicates single-device baseline.
- `core/multi_device_control_integrity.py`
  - `MultiDeviceIntegritySnapshot.gaps_by_area` T — Return gaps for a specific audit area.
  - `build_entry_unification_record` T — Construct an :class:`EntryUnificationRecord`.
- `core/multi_device_coordination_authority.py`
  - `coordination_role_description` — — Return the human-readable description for *role*.
- `core/multi_device_runtime_harness.py`
  - `MultiDeviceCoherenceHarness.to_canonical_projection` — — 返回本 harness 运行时读侧的规范投影(专项③ anti-drift 锚定)。
- `core/multi_subject_closure_machine.py`
  - `ClosureTerminalKind.is_success_family` T — 无说明
  - `ClosureTerminalKind.is_partial_family` T — 无说明
  - `ClosureTerminalKind.is_failure_family` T — 无说明
- `core/node_governance_runtime.py`
  - `reset_governance_runtime_cache` T — No-op reset hook for test isolation.
- `core/node_lifecycle_governor.py`
  - `node_governance_snapshot` T — Convenience wrapper — return a governor snapshot.
- `core/outward_runtime_truth.py`
  - `OutwardRuntimeTruthRuntime.snapshot_list` T — Return all buffered snapshots (oldest first).
  - `OutwardRuntimeTruthRuntime.compile_count` T — Total number of snapshots compiled since this runtime was created.
  - `classify_signal` T — Classify a runtime truth signal.
- `core/outward_truth_source_registry.py`
  - `assert_source_for_field` T — Assert that *field_key* is registered as coming from *claimed_source*.
  - `enforce_surface_contract` — — Raise when a surface violates registry governance constraints.
- `core/perception/perception_fact_boundary.py`
  - `classify_perception_surface` T — Return the catalog record for *surface_path*, when known.
- `core/peripheral_capability_boundary.py`
  - `classify_peripheral_capability_surface` T — 无说明
- `core/production_baseline.py`
  - `ProductionBaselineRegistry.openclawd_owned_artifacts` T — Return all artifacts owned by the subject core (OpenClawd).
  - `ProductionBaselineRegistry.shell_owned_artifacts` T — Return all artifacts owned by the runtime shell (DesktopPresenceRuntime).
  - `ProductionBaselineRegistry.is_canonical_primary` T — Return True if *metadata_key* is a CANONICAL_PRIMARY artifact.
  - `ProductionBaselineRegistry.is_derived_only` T — Return True if *metadata_key* is a DERIVED_ONLY surface.
  - `ProductionBaselineRegistry.is_legacy_secondary` T — Return True if *metadata_key* is a LEGACY_SECONDARY path.
- `core/release_governance_taxonomy.py`
  - `OperationalStatus.blocks_release` T — Return ``True`` when the status prevents release.
  - `TerminologyRegistry.blocking_terms` T — Return the set of all :class:`IssueClassification` values that
  - `TerminologyRegistry.advisory_only_terms` T — Return the set of all strictly advisory (non-blocking) terms.
  - `classify_issue` T — Classify a free-text condition description using the unified taxonomy.
  - `is_blocking_classification` T — Return ``True`` when *cls* represents a hard release block.
- `core/repo_layout_registry.py`
  - `RepoLayoutRegistry.legacy_entries` — — Return all legacy/transitional entries.
  - `RepoLayoutRegistry.entries_by_zone` — — Return all entries belonging to *zone*.
  - `is_active_desktop_status_directory` T — Return ``True`` if *path* is the canonical active desktop status surface.
  - `build_repo_layout_summary` T — Build a structured summary of the repository layout registry.
- `core/runtime_closure_audit.py`
  - `run_closure_audit` T — Run the full closure audit and return a snapshot.
  - `persist_conflict_artifacts` T — Durably record conflict detection artifacts to the audit store.
- `core/runtime_invariant_enforcement.py`
  - `check_invariant` T — Look up an invariant by ID and log a warning if it is not ENFORCED.
  - `check_cross_repo_assumption` T — Look up a cross-repo assumption by ID and log a warning if unvalidated.
- `core/runtime_readiness_matrix.py`
  - `is_release_blocked` T — Return ``True`` when the readiness matrix verdict is BLOCKED.
- `core/scheduling_truth_harness.py`
  - `query_routable_executors_for_task` T — Convenience wrapper: query routable executors for a task.
  - `assert_scheduling_truth_convergence` T — Convenience wrapper: assert that scheduling truth sources are convergent.
- `core/subject_facing_foreground.py`
  - `SubjectFacingForeground.is_completed` — — Return True iff subject has completed an action.
- `core/system_orchestrator.py`
  - `SystemOrchestrator.register_hook` T — Register an additional hook to run during *phase*.
- `core/task_result_canonical_truth_chain.py`
  - `IncompleteResultLedger.all_incomplete` T — Return a snapshot list of all recorded incomplete outcomes.
- `core/truth_conflict_enforcement.py`
  - `assert_canonical_write_precedes_compat_write` T — Assert that a canonical write has been performed before a compat write.
  - `assert_no_parallel_write_authority` T — Assert that *writer_module* is not acting as a parallel write authority.
  - `check_compat_write_is_mirror_only` T — Check that a compat write to *surface* is a mirror-only operation.
  - `is_truth_convergence_healthy` T — Return True when the in-process truth conflict enforcement posture is healthy.
- `core/truth_integration_layer.py`
  - `is_device_available_canonical` T — Return True iff the device is fully available per canonical truth.
- `core/truth_projection_boundary.py`
  - `classify_surface_boundary` T — 无说明
- `core/ui_surface_authority.py`
  - `is_legacy_surface` T — Return ``True`` if *surface_path* is registered as a legacy surface.
  - `is_projection_driven_surface` T — Return ``True`` if *surface_path* is the canonical projection-driven surface.
- `core/unified_action_lifecycle_surface.py`
  - `UnifiedActionLifecycleSurface.is_android_result_first_class` T — Return True iff an Android-side result has been set as first-class.
  - `UnifiedActionLifecycleSurface.has_blocker` T — Return True iff a canonical blocker is present.
  - `build_from_dispatch` T — Create a surface entry when an action is initially dispatched.
  - `build_from_normalizer_outcome` T — Build a surface entry from an AndroidResultNormalizerOutcome.
  - `apply_blocker` T — Converge a blocker into the surface, advancing phase to ``blocked``.
  - `apply_confirmation` T — Mark the surface as needing operator/user confirmation.
  - `close_surface` T — Mark the surface as closed.
- `core/unified_dispatch_readiness_gate.py`
  - `reset_dispatch_readiness_gate` T — No-op — this module is stateless.  Kept for API symmetry with other gates.
- `core/unified_execution_governance.py`
  - `resolve_execution_conflict` T — Compute the canonical conflict resolution for two execution types.

</details>

<details><summary>多设备编组、协同网络与拓扑 — 50 条</summary>

- `core/capability_network_bridge.py`
  - `explain_joint_selection` T — Produce a full human-readable explanation for a :class:`JointSelectionResult`.
  - `fallback_joint_select` T — Select a fallback provider+path when the primary selection has failed.
- `core/capability_network_runtime_policy.py`
  - `absorb_device_presence_event` T — Absorb a device presence/connectivity change into both canonical runtime layers.
  - `absorb_heartbeat_event` T — Absorb a heartbeat event into the capability assimilation layer.
  - `absorb_capability_change_event` T — Absorb an executor/provider capability change into the capability assimilation layer.
  - `absorb_path_change_event` T — Absorb a transport path change event into the network topology runtime.
  - `query_capable_device_executors` T — Query the canonical runtime for *device*-kind executors that are online
  - `snapshot_canonical_runtime` T — Return a unified snapshot of the canonical capability + network runtime state.
- `core/constellation_runtime.py`
  - `warn_legacy_path` T — Log a structured deprecation warning when a legacy orchestrator path is invoked.
- `core/control_plane/swarm_manifest.py`
  - `SwarmAgentManifest.to_agent_execute_payload` T — Convert to an ``agent_execute`` command payload dict.
- `core/control_plane/swarm_scaler.py`
  - `SwarmScaler.autoscale` T — Evaluate + act in a single call.
  - `SwarmScaler.managed_workers` — — Return the list of worker agent IDs managed by the scaler for *team_id*.
- `core/cross_device_policy/routing_policy.py`
  - `RoutingPolicy.source_assignment` T — Return the SOURCE assignment entry, if any.
  - `RoutingPolicy.devices_with_role` T — Return all assignments that match *role*.
- `core/cross_device_sync.py`
  - `push_task_state_to_device` — — Push task state update to a specific Android device.
- `core/device_formation/formation_auto_enrollment.py`
  - `FormationAutoEnrollmentManager.update_device_readiness` T — Notify the formation coordinator of a readiness change.
  - `FormationAutoEnrollmentManager.list_active_device_ids` T — Return the IDs of all active (enrolled) participants.
- `core/device_formation/formation_runtime_coordinator.py`
  - `FormationParticipantStatus.is_viable` T — Return True if this participant can contribute to execution.
- `core/device_worker_convergence.py`
  - `DeviceWorkerConvergence.is_worker_registered` — — Check if a device has been registered as a NATS Worker.
- `core/mesh/body_mesh_registry.py`
  - `BodyEntry.has_role` — — Return ``True`` if this entry carries the given role.
- `core/mesh/device_role_allocator.py`
  - `DeviceRoleAllocator.register_capability_rule` T — Add a custom capability keyword → role mapping.
  - `DeviceRoleAllocator.allocate_all` T — Allocate roles for all online devices in UnifiedDeviceManager.
- `core/mesh/live_mesh_session_coordinator.py`
  - `LiveMeshSessionCoordinator.on_android_participant_signal` T — Route an Android-originated mesh participation signal to this coordinator.
- `core/mesh/mesh_auto_enrollment.py`
  - `MeshAutoEnrollmentService.list_enrolled_device_ids` T — Return device IDs that are currently enrolled.
  - `notify_readiness_confirmed` T — Notify the singleton service of a readiness-confirmation event.
  - `notify_device_lost` T — Notify the singleton service that a device has been lost.
- `core/mesh/mesh_runtime_center_state.py`
  - `is_valid_center_transition` T — Return True when *from_status* → *to_status* is a valid transition.
  - `MeshParticipantEligibilityStatus.can_participate` T — Return True when this participant can meaningfully participate.
- `core/mesh/mesh_session_coordinator.py`
  - `MeshSessionCoordinator.update_with_dispatch_result` T — Incorporate a source dispatch result into the coordinator state.
  - `MeshSessionCoordinator.update_with_takeover_result` T — Incorporate a target takeover result into the coordinator state.
  - `MeshSessionCoordinator.update_with_merged_result` T — Incorporate a cross-runtime merged result into the coordinator state.
- `core/mesh_coordinator.py`
  - `inject_mesh_senders` — — 无说明
- `core/mesh_nats_fusion.py`
  - `MeshNATSConvergence.submit_participant_result` — — Submit a participant result back to the Mesh session.
  - `MeshNATSConvergence.subscribe_session` — — Subscribe to all participant results for a Mesh session.
  - `MeshNATSConvergence.unsubscribe_session` — — Unsubscribe from a session.
- `core/network_graph_runtime.py`
  - `reset_network_graph_runtime` T — Reset the :class:`NetworkGraphRuntime` singleton (for testing).
- `core/network_topology_runtime.py`
  - `NetworkTopologyRuntime.update_edge_state` T — Update an edge's state (and optionally its preference flag).
  - `assimilate_nats_state` T — Absorb NATS fabric state into the singleton runtime.
  - `assimilate_gateway_state` T — Absorb gateway substrate state into the singleton runtime.
  - `assimilate_device_connectivity` T — Absorb a device connectivity report into the singleton runtime.
  - `reset_network_topology_runtime` T — Reset the :class:`NetworkTopologyRuntime` singleton (for testing).
- `core/orchestration/global_arbiter.py`
  - `GlobalArbiter.suggest_device` T — Return the least-loaded candidate device based on current task origin
  - `reset_global_arbiter` T — Reset the singleton (for testing).
- `core/presence/presence_director.py`
  - `PresenceDirector.on_phase_transition` T — React to a cognitive phase transition.
  - `PresenceDirector.refresh_presence` T — Unconditionally project *cognitive_state* to all mesh devices.
- `core/presence/presence_projection.py`
  - `PresenceProjection.last_events` T — Return the most recent *n* projection events.
- `core/proxy_relay.py`
  - `ProxyRelay.relay_agent_manifest` — — Agent Manifest 中继 — 从一台设备迁移 Agent 到另一台
  - `ProxyRelay.relay_envelope` — — Relay a :class:`~core.schemas.task_envelope.TaskEnvelope`.
- `core/swarm_coordinator.py`
  - `SwarmCoordinator.build_execution_plan_for_orchestration` — — PR-11: Build a canonical :class:`~core.schemas.execution_plan.ExecutionPlan`
  - `SwarmCoordinator.device_candidates_from_canonical` T — Build a ``DeviceScoreInput`` list from canonical device projections.

</details>

<details><summary>设备与节点：注册、发现、连接、通信、传输 — 109 条</summary>

- `core/adapters/ble_adapter.py`
  - `BLEAdapter.list_connected` — — 返回已连接的设备地址列表。
- `core/adapters/tailscale_p2p_adapter.py`
  - `TailscaleP2PAdapter.list_registered_devices` — — Return all registered device_id → ts_ip mappings.
- `core/adapters/tcp_adapter.py`
  - `TCPAdapter.connect_to_peer` — — 主动连接到 P2P 对等端。
  - `TCPAdapter.discover_peers` — — 通过 mDNS 发现同一局域网内的 Galaxy 设备。
- `core/aip_transport.py`
  - `AIPTransport.transport_stats` — — 可观测:导出链路统计(供面板/诊断查看选路反哺依据)。
  - `AIPTransport.unregister_adapter` — — 无说明
  - `AIPTransport.probe_best_transport` — — 探测到目标设备的最佳传输。
  - `register_transport_adapter` — — 无说明
- `core/connection_manager.py`
  - `ConnectionManager.on_connected` — — 注册连接成功回调
  - `ConnectionManager.on_disconnected` — — 注册断开连接回调
- `core/device_agent_manager.py`
  - `DeviceAgentManager.register_agent_type` — — 注册新的设备 Agent 类型
  - `DeviceAgentManager.connect_all` — — 连接所有设备
  - `create_device_api` — — 创建设备管理 API
- `core/device_communication.py`
  - `DeviceMessage.to_aip_v3_dict` — — 转换为 AIP v3.0 格式的字典
  - `DeviceCommunication.list_connected_devices` T — 列出已连接的设备
  - `DeviceCommunication.on_device_message` — — 注册设备消息事件回调
- `core/device_execution_profile.py`
  - `build_thin_profile` T — Convenience factory for an explicitly thin device profile.
  - `build_rich_profile` T — Convenience factory for an explicitly rich device profile.
  - `build_unknown_profile` T — Convenience factory for a profile with no capability information.
- `core/device_node_resolver.py`
  - `DeviceNodeResolver.list_supported_device_types` T — Return all device types that have explicit mappings.
  - `DeviceNodeResolver.list_supported_transports` T — Return all transports that have explicit mappings.
- `core/device_orchestrator.py`
  - `DeviceOrchestrator.parallel_commands` T — 并行向多台设备发送命令。
  - `DeviceOrchestrator.sync_clipboard` T — 跨设备剪贴板同步。
  - `DeviceOrchestrator.register_device_in_pool` — — Register a device in the unified DevicePoolManager.
- `core/device_registry.py`
  - `DeviceRegistry.check_offline_devices` T — Mark timed-out devices as OFFLINE in the local compatibility cache.
  - `DeviceRegistry.negotiate_capability` T — 协商设备能力
  - `DeviceRegistry.add_to_group` — — 添加设备到分组
  - `DeviceRegistry.remove_from_group` — — 从分组移除设备
  - `DeviceRegistry.add_tag` — — 添加标签
  - `DeviceRegistry.remove_tag` — — 移除标签
  - `DeviceRegistry.project_to_contract` T — Project a registry-local record into the canonical ``RegisteredRuntimeDevice`` contract.
- `core/device_types.py`
  - `device_type_to_platform` T — 将简化 DeviceType 映射为 AIP DevicePlatform。
- `core/lan_discovery.py`
  - `_Listener.add_service` — — 无说明
  - `_Listener.update_service` — — 无说明
  - `_Listener.remove_service` — — 无说明
- `core/nats_bus.py`
  - `NATSBus.publish_legacy_task_result` T — [Legacy] Publish TaskResult — auto-converts to AIP v3 TASK_RESULT.
  - `NATSBus.publish_task_event` T — Publish to the canonical ``galaxy.task.*`` namespace with trace propagation.
  - `NATSBus.publish_device_event` T — Publish to the canonical ``galaxy.device.*`` namespace with trace propagation.
  - `NATSBus.publish_capability_event` T — Publish to the canonical ``galaxy.capability.*`` namespace with trace propagation.
- `core/node_capability_loader.py`
  - `NodeCapabilityLoader.list_node_actions` — — List actions provided by a specific node.
- `core/node_cognition_activation.py`
  - `evaluate_activation_eligibility` T — Evaluate whether *node_id* is eligible to be activated for *role*.
  - `transition_activation_state` T — Validate and apply an activation-state transition.
- `core/node_communication.py`
  - `NodeRegistry.detect_partitions` — — 检测网络分区
  - `UniversalCommunicator.activate_self` — — Node self-activation
- `core/node_discovery.py`
  - `NodeDiscoveryService.on_node_joined` — — 注册节点加入回调
  - `NodeDiscoveryService.on_node_left` T — 注册节点离开回调
  - `NodeDiscoveryService.on_node_updated` — — 注册节点更新回调
  - `NodeDiscoveryService.deregister_node` — — 注销节点
  - `NodeDiscoveryService.seed_from_registry` T — 从 node_registry.json 预填充节点，无需等待 UDP 广播。
  - `_DiscoveryProtocol.error_received` — — 无说明
  - `safe_scan_nodes_dir` — — 安全扫描本地 nodes/ 目录，返回可加载的节点列表
- `core/node_protocol.py`
  - `MessageRouter.send_request` — — 发送请求并等待响应
  - `ProtocolAdapter.to_android_format` — — 转换为 Android 端格式
  - `ProtocolAdapter.from_android_format` — — 从 Android 端格式转换
  - `ProtocolAdapter.to_websocket_format` — — 转换为 WebSocket 格式
  - `ProtocolAdapter.from_websocket_format` — — 从 WebSocket 格式转换
- `core/node_registry.py`
  - `NodeRegistry.register_node_class` — — 注册节点类（延迟实例化）
  - `NodeRegistry.start_health_monitor` T — 启动健康监控
  - `NodeRegistry.stop_health_monitor` — — 停止健康监控
  - `NodeRegistry.load_all_nodes` — — 加载所有节点，返回详细的加载报告
- `core/nodes/node_fabric_registry.py`
  - `NodeFabricRegistry.mark_offline_if_stale` T — 扫描所有节点，心跳超时的标记为 OFFLINE。返回被标记的节点 ID 列表。
  - `NodeFabricRegistry.list_by_capability` T — 返回具有指定能力的节点列表。
  - `NodeFabricRegistry.expire_stale_capabilities` T — 从 CapabilityRegistry 中移除来源为 "node" 且超过 TTL 的节点能力条目。
  - `reset_node_fabric_registry` T — 重置 NodeFabricRegistry 单例（测试用）。
- `core/peer_trust.py`
  - `trust_rank` — — 把任意信任级别表示折算成可比较的序数;不认识的按 UNKNOWN。
  - `PeerTrustBook.set_trust` — — 无说明
- `core/tailscale_manager.py`
  - `TailscaleManager.is_tailscale_installed` — — 检查tailscale命令是否安装。
  - `TailscaleManager.is_headscale_mode` — — Check if using custom Headscale control server.
- `core/target_device_validator.py`
  - `CanonicalValidationInput.from_legacy` T — Build a CanonicalValidationInput from legacy/compat caller data.
  - `validate_target_device_from_canonical` T — Validate a target device from a pre-normalised :class:`CanonicalValidationInput`.
- `galaxy_gateway/agent_bridge.py`
  - `AgentBridge.handoff_from_envelope` T — PR-2 primary entry point: delegate a TaskEnvelope to the agent runtime.
  - `AgentBridge.build_envelope_v2` T — PR-31: Build a Handoff Envelope v2 from a legacy :class:`HandoffContract`.
- `galaxy_gateway/cross_device_switch.py`
  - `guard_cross_device` T — Raise :class:`CrossDeviceDisabledError` when the switch is OFF.
- `galaxy_gateway/daemon_notifier.py`
  - `DaemonNotifier.notify_crash_restart` — — 无说明
  - `DaemonNotifier.notify_too_many_restarts` — — 无说明
  - `DaemonNotifier.notify_system_pressure` — — 无说明
- `galaxy_gateway/device_router.py`
  - `DeviceRouter.aggregate_results` T — Aggregate multi-device task results into a unified summary.
- `galaxy_gateway/enhanced_nlu_v2.py`
  - `DeviceRegistry.find_device_by_name` — — 通过名称或别名查找设备
- `galaxy_gateway/gateway_nats_adapter.py`
  - `GatewayNATSAdapter.resolve_task` T — Resolve a pending task future with the device result.
- `galaxy_gateway/handlers/device_manager.py`
  - `DeviceManager.find_best_device_for_task` — — 为任务找到最佳设备
- `galaxy_gateway/multimodal_transfer.py`
  - `MultimodalTransferManager.receive_image` — — 接收图片
  - `MultimodalTransferManager.send_video` — — 发送视频
  - `MultimodalTransferManager.send_file_chunk` — — 发送文件分块
  - `MultimodalTransferManager.receive_file_chunk` — — 接收文件分块
  - `MultimodalTransferManager.send_screenshot` — — 发送屏幕截图
- `galaxy_gateway/orchestrator/parallel_tracker.py`
  - `ParallelGroupTracker.finalize_if_complete` T — Return finalized status when all expected subtasks are recorded, else None.
  - `ParallelGroupTracker.expire_timeouts` T — Mark missing subtasks as *timeout* and finalize all overdue groups.
- `galaxy_gateway/orchestrator/task_orchestrator.py`
  - `TaskOrchestrator.reset_device_counts` — — Reset all device task counts. Useful when topology changes dramatically.
  - `MultiDeviceOrchestrator.submit_multi_device_task` T — 提交多设备协同任务 — PR-2: 所有多设备任务强制经过 TaskGraph.
- `galaxy_gateway/protocol/compat.py`
  - `extract_parallel_result_payload` — — Extract a :class:`~galaxy_gateway.protocol.aip_v3.ParallelResultPayload`
- `galaxy_gateway/resumable_transfer.py`
  - `ResumableTransferManager.receive_file` — — 接收文件（支持断点续传）
  - `ResumableTransferManager.write_chunk` — — 写入分块数据
- `galaxy_gateway/routing/router.py`
  - `RoutingOrchestrator.filter_eligible` T — Return *devices* that pass the online health gate.
  - `RoutingOrchestrator.build_message` T — Build an AIP v3 command envelope for WebSocket dispatch.
- `galaxy_gateway/session_roaming.py`
  - `SessionRoamingManager.update_task_state` — — 更新会话的任务状态
  - `SessionRoamingManager.close_session` — — 关闭会话
  - `SessionRoamingManager.auto_migrate_on_attention_shift` T — 根据用户注意力焦点变化自动迁移会话
  - `SessionRoamingManager.load_snapshot` — — 从磁盘加载会话快照。
- `galaxy_gateway/ssot.py`
  - `udm_write_upsert` T — Perform a partial or full device state update through UnifiedDeviceManager.
- `galaxy_gateway/task_decomposer.py`
  - `TaskDecomposer.decompose_search_and_open` — — 分解"搜索并打开"任务
  - `TaskDecomposer.decompose_conditional_task` — — 分解条件任务
- `galaxy_gateway/transport/websocket_server.py`
  - `WebSocketManager.handle_connection` T — 处理设备连接的完整生命周期
- `galaxy_gateway/wake_event_bus.py`
  - `WakeEventBus.clear_dedup_buffer` — — 手动清除去重缓冲区
- `galaxy_gateway/wake_router.py`
  - `WakeRouter.set_decision_callback` — — 设置路由决策完成后的回调函数
  - `WakeRouter.clear_dedup_cache` — — 清除去重缓存（用于测试或手动重置）
  - `WakeRouter.inject_device_info` T — 注入设备信息（主要用于测试）
- `galaxy_gateway/webrtc_proxy.py`
  - `order_ice_candidates` T — Sort and deduplicate an ICE candidate list by connectivity priority.
  - `clear_webrtc_task_session` — — Remove a WebRTC task session entry (idempotent).
- `galaxy_gateway/websocket_handler.py`
  - `handle_response` T — 处理任务/命令执行结果（接受 AIPMessage 对象）

</details>

<details><summary>能力、模型与执行路由 — 76 条</summary>

- `core/agent/intent_router.py`
  - `IntentResult.is_execution` T — 是否需要进入执行链路（task_execute 或 hybrid）。
- `core/canonical_task_dispatch_chain.py`
  - `classify_dispatch_path` T — Return the :class:`DispatchChainRecord` for *path_kind*.
  - `is_canonical_path` T — Return ``True`` when *path_kind* has role :attr:`DispatchPathRole.canonical`.
  - `is_android_inbound_path` T — Return ``True`` when *path_kind* is :attr:`DispatchPathKind.android_inbound`.
  - `build_dispatch_chain_snapshot` T — Build and return a :class:`DispatchChainSnapshot`.
- `core/capabilities/canonical_dispatcher.py`
  - `CanonicalDispatcher.bus_catalog` T — Return a snapshot of the :class:`~core.capability_bus.CapabilityBus`.
- `core/capability_assimilation.py`
  - `CapabilityAssimilationLayer.mark_stale_if_expired` T — Mark all nodes whose heartbeat is older than *heartbeat_ttl_secs* as STALE.
  - `reset_capability_assimilation_layer` T — Reset the :class:`CapabilityAssimilationLayer` singleton (for testing).
  - `assimilate_node` T — Convenience helper: assimilate a NodeInfo-compatible object or dict.
- `core/capability_aware_routing_default.py`
  - `apply_capability_aware_default` T — Apply capability-aware routing as the default main path.
- `core/capability_bus.py`
  - `CapabilityBusRole.from_tool_name` T — Infer :class:`CapabilityBusRole` from a canonical tool name.
  - `CapabilityBus.seed_from_node_registry` T — Seed :class:`CapabilityBusEntry` records from ``config/node_registry.json``.
  - `CapabilityBus.register_mcp_tool` T — Register an MCP server tool in the bus.
  - `CapabilityBus.register_engineering_capability` T — Register a mediated engineering loop capability in the bus.
  - `CapabilityBus.register_resource_capability` T — Register a governed system resource management capability in the bus.
- `core/capability_graph_selection.py`
  - `explain_selection` T — Produce a human-readable explanation for why *record* was selected.
- `core/capability_manager.py`
  - `CapabilityManager.find_capability_by_keyword` — — 通过关键字搜索能力
- `core/capability_orchestrator.py`
  - `CapabilityOrchestrator.reinitialize` — — 重新加载所有能力（MCP/Skill 变更后调用）
  - `CapabilityOrchestrator.list_capabilities` T — 列出所有能力
  - `CapabilityOrchestrator.enable_capability` — — 启用能力
  - `CapabilityOrchestrator.disable_capability` — — 禁用能力
- `core/capability_runtime/capability_constraint.py`
  - `CapabilityConstraintFlags.has_any_constraint` T — Return ``True`` if at least one flag is set.
- `core/capability_runtime/capability_preference.py`
  - `CapabilityPreference.has_preference` T — Return ``True`` if any non-default preference is expressed.
- `core/command_router.py`
  - `CommandRouter.normalize_legacy_ingress` T — Normalize a non-envelope payload to a ``TaskEnvelope`` and record it.
- `core/compute_scheduler.py`
  - `ModelAllocation.is_offloaded` — — 无说明
  - `ComputeScheduler.is_monitoring` — — 无说明
  - `ComputeScheduler.loaded_model_count` — — 无说明
  - `ComputeScheduler.estimate_quantized_size` — — Estimate model size after quantization.
- `core/concurrency_manager.py`
  - `LockManager.release_all` T — 释放某持有者的所有锁
  - `ConcurrencyManager.track_task` — — 注册一个后台任务到跟踪器，防止泄漏
  - `ConcurrencyManager.run_with_concurrency` T — 带并发控制的任务执行
  - `ConcurrencyManager.run_with_lock` T — 带锁的任务执行
- `core/degraded_operation_envelope.py`
  - `envelope_summary` T — Produce a compact, projection-safe summary dict from a
- `core/execution/decision_executor.py`
  - `PolicyGate.check_action_level` T — Return True when the action level is at least ``assist``.
- `core/execution_spine.py`
  - `route_via_spine` T — Normalize *payload* and route it through ``CommandRouter.route_envelope``.
- `core/fusion_entry_adapter.py`
  - `check_fusion_entry_compliance` T — Return ``True`` if *module* is a compliant fusion_entry adapter.
- `core/gateway_capability_default_enforcement.py`
  - `audit_gateway_override` T — Record an explicit capability gate override with a mandatory audit token.
- `core/hardware_aware_multimodal_router.py`
  - `HardwareAwareMultimodalRouter.route_vision` — — 视觉任务路由
  - `HardwareAwareMultimodalRouter.route_asr` — — 语音识别路由
  - `HardwareAwareMultimodalRouter.route_with_image` — — 带图片输入的路由
- `core/hf_endpoint.py`
  - `endpoint_reachable` — — 是否存在可达的 HF 下载端点(带缓存,见 pick_endpoint)。
- `core/huggingface_model_manager.py`
  - `HuggingFaceModelManager.download_llm` — — 下载文本生成模型
  - `HuggingFaceModelManager.download_vlm` — — 下载视觉语言模型
  - `HuggingFaceModelManager.download_asr` — — 下载 ASR 模型（默认 faster-whisper-medium）
  - `HuggingFaceModelManager.download_embedding` — — 下载 Embedding 模型
  - `HuggingFaceModelManager.download_background` — — Start a background download task. Returns the Task immediately
- `core/hybrid_execution_policy.py`
  - `HybridExecutionMode.is_concurrent` T — True if this mode launches multiple execution paths concurrently.
  - `HybridExecutionMode.is_degrade_chain` T — True if this mode follows a sequential fallback / degradation chain.
  - `HybridExecutionPolicy.describe_mode` T — Return a human-readable description of *mode*.
- `core/local_brain_manager.py`
  - `LocalBrainManager.switch_brain` — — 切换主脑模型
  - `LocalBrainManager.remove_model` — — 删除 Ollama 模型
  - `check_local_brain` — — 检查本地主脑状态的便捷函数
- `core/modality_bridge.py`
  - `resolve_audio_in` T — 当前档位的听通路：native / asr_bridge。
- `core/model_catalog.py`
  - `register_ephemeral_spec` T — 临时登记一个型号(仅本进程可查,不进目录、不进快照、不写状态)。
  - `clear_ephemeral_specs` T — 清空临时登记(测试收尾用)。
- `core/model_openness.py`
  - `audit_registry` T — 诊断用:把每家的模型成分摊开,便于看清哪家是 mixed、哪些型号判不出来。
- `core/model_topology/canonical_model_supply_state.py`
  - `NativeMultimodalCapabilityRegistry.register_many` T — Register multiple capability records.
- `core/model_topology/config_bridge.py`
  - `ConfigBridge.build_inventory` T — Build a full ``ProviderInventory`` from dashboard-era input.
- `core/model_topology/model_supply_graph.py`
  - `ModelSupplyGraph.edges_of_kind` T — 无说明
  - `ModelSupplyGraph.nodes_by_category` T — 无说明
  - `ModelSupplyGraph.nodes_by_provider` — — 无说明
- `core/model_topology/provider_inventory.py`
  - `ProviderInventory.unavailable_entries` T — 无说明
  - `ProviderInventory.top_by_quality` T — 无说明
  - `ProviderInventory.top_by_speed` T — 无说明
  - `ProviderInventory.top_by_composite` — — 无说明
- `core/model_topology/topology_router.py`
  - `TopologyRouter.route_all_phases` T — Produce plans for all three public tri-state phases.
- `core/multi_llm_router.py`
  - `MultiLLMRouter.route_local_brain_first` — — 本地主脑优先路由
  - `MultiLLMRouter.chat_cascade` T — L2 级联路由(任务感知的 FrugalGPT):按任务【实际复杂度】定起步档,再便宜→贵升级。
- `core/native_modal.py`
  - `is_native_active` T — 无说明
- `core/remote_execution_mode_resolver.py`
  - `ModeResolutionResult.as_remote_execution_mode` T — Return the resolved mode as a :class:`RemoteExecutionMode` enum.
- `core/runtime/execution_target_policy_engine.py`
  - `apply_failure_handling_policy` T — Apply the failure handling policy and return a
  - `apply_degraded_readiness_policy` T — Apply the degraded-readiness policy and return a
- `core/runtime/source_dispatch_orchestrator.py`
  - `reset_live_mesh_runtime_proof_snapshot` T — Reset in-memory live mesh runtime proof counters.
- `core/unified/capability_resolver.py`
  - `CapabilityResolver.resolve_by_tag` T — Return validated contracts whose tags include *tag*.
- `core/unified/llm_router.py`
  - `reset_routing_telemetry` T — 重置全局遥测单例（测试用）。
  - `UnifiedLLMRouter.reload_policy` T — 重新加载路由策略文件（运行时热更新）。

</details>

<details><summary>智能体、认知与记忆 — 84 条</summary>

- `core/agent/policy_loader.py`
  - `reload_policies` T — 强制重新从磁盘加载所有策略文件。
- `core/agent_factory.py`
  - `AgentMessageBus.notify_ack` — — 通知请求方消息已被处理
- `core/agent_identity_memory.py`
  - `AgentIdentityMemory.add_goal` — — Add a long-term goal.
  - `AgentIdentityMemory.remove_goal` — — Remove a long-term goal.
  - `AgentIdentityMemory.add_value` — — Add a core value.
- `core/agent_manifest.py`
  - `AgentManifest.create_multi_step_agent` T — 创建多步骤顺序执行 Agent
- `core/agent_team.py`
  - `AgentTeam.couple_member` — — 切换成员的耦合模式
  - `AgentTeam.decouple_member` — — 解耦成员
  - `TeamManager.list_teams` — — 列出所有团队
- `core/agentic/workflow.py`
  - `from_task_agent` — — 单 agent：``factory.execute_agent_task(agent_id, {"task": task})``。
  - `from_team` — — 团队（一站式）：``team_manager.execute_team_task(task, strategy, ...)``。
  - `from_fractal` — — 分形 agent：``fractal.execute(FractalTask(...))``。
- `core/ai_intent.py`
  - `SemanticSearch.initialize_qdrant` — — 尝试连接 Qdrant 向量数据库（保持向后兼容）
  - `SemanticSearch.index_document_vector` — — 索引文档到 Qdrant（向量模式）
- `core/canonical_session_axis.py`
  - `resolve_session_family_for_identifier` T — Return the session family record for the family that owns *field_name*.
  - `build_session_axis_snapshot` T — Build a point-in-time snapshot of the canonical session axis model.
- `core/cognitive/cognitive_activation_budget.py`
  - `ActivationBudget.is_narrow` T — Return True when breadth mode is narrow (passive/silent).
  - `ActivationBudget.is_moderate` T — Return True when breadth mode is moderate (liminal).
  - `ActivationBudget.is_broad` T — Return True when breadth mode is broad (manifest).
  - `apply_candidate_narrowing` T — Apply soft candidate narrowing based on activation budget.
- `core/cognitive/cognitive_execution_policy.py`
  - `CognitiveExecutionHint.is_manifest` — — Return True when the cognitive region is manifest.
  - `CognitiveExecutionHint.is_liminal` — — Return True when the cognitive region is liminal.
  - `CognitiveExecutionHint.is_passive` — — Return True when the cognitive region is passive / silent.
- `core/cognitive/cognitive_field_engine.py`
  - `CognitiveFieldEngine.add_tick_listener` T — Register a callable that is invoked on every tick.
  - `CognitiveFieldEngine.remove_tick_listener` T — Deregister a previously registered tick listener.
- `core/cognitive/liminal_dynamics.py`
  - `LiminalDynamics.can_transition_to_manifest` T — Return *True* if the system has dwelt long enough in liminal.
- `core/cognitive/long_term_memory.py`
  - `LongTermMemory.retrieve_entry` T — Retrieve the full :class:`LongTermMemoryEntry` dict or *None*.
  - `LongTermMemory.forget_namespace` T — Remove all entries in *namespace*. Returns the number removed.
- `core/cognitive/memory_bias_layer.py`
  - `MemoryBias.is_continuity` T — Return True when posture is continuity-seeking.
  - `MemoryBias.is_retrieval` T — Return True when posture is retrieval-seeking.
  - `MemoryBias.is_novelty` T — Return True when posture is novelty / low-memory.
  - `build_memory_bias_active_scope_diagnostics` T — Return structured diagnostics for the real active scope of memory bias.
- `core/cognitive/pattern_miner.py`
  - `PatternMiner.mine_full` — — Run full pattern mining scan on all TaskMemory records.
- `core/cognitive/state_interpreter.py`
  - `StateInterpreter.interpret_snapshot` T — Interpret a pre-computed state snapshot dict (no lock needed).
  - `StateInterpreter.last_region` T — The most recently derived region (thread-safe read).
- `core/continuum/return_engine.py`
  - `ReturnEngine.force_return` T — Force an immediate hard return to formless, bypassing all checks.
- `core/continuum/temporal_engine.py`
  - `DwellGuard.remaining_ms` T — Milliseconds remaining until the dwell requirement is satisfied.
  - `TemporalEngine.smoothed_signals` T — Read-only snapshot of the current EMA-smoothed signals.
- `core/dag_evolver.py`
  - `DAGEvolver.on_missing_capability` T — Insert a *capability-gap* node before the requesting task.
- `core/digital_twin_engine.py`
  - `DigitalTwin.push_to_physical` — — 从数字侧向物理设备推送命令
  - `DigitalTwin.register_physics_model` — — 注册物理模型用于预测
  - `DigitalTwinEngine.couple_all` — — 批量耦合所有孪生体
  - `DigitalTwinEngine.decouple_all` — — 批量解耦
  - `drone_flight_model` — — 无人机飞行物理模型
  - `printer_3d_model` — — 3D 打印机物理模型
- `core/e2e_orchestrator.py`
  - `run_multi_device_via_task_graph` T — Execute *subtasks* across multiple devices **always** via TaskGraph.
  - `process_user_input` T — 统一用户输入处理入口。
- `core/feedback_loop.py`
  - `FeedbackLoop.record_user_evaluation` — — Record explicit user feedback (good/bad/etc).
  - `FeedbackLoop.should_use_local` — — Recommend whether to use local execution based on history.
- `core/focus_stack.py`
  - `FocusStack.drop_current` T — 显式结束当前焦点,上一个自动恢复为当前。
- `core/galaxy_main_loop_l4_enhanced.py`
  - `GalaxyMainLoopL4.receive_goal` T — 接收外部目标（UI → L4 集成点）。
- `core/generative_ui/runtime.py`
  - `GenerativeUIRuntime.render_surface_dict` T — Convenience wrapper returning :meth:`SurfaceSpec.to_dict`.
- `core/grounded_planner.py`
  - `to_task_assign` T — 把规划出的动作落成 AIP v3 TASK_ASSIGN，带上当前结构化界面态。
- `core/interaction/pending_decision_registry.py`
  - `PendingDecisionRegistry.sweep_expired` — — Resolve any records whose wall-clock age exceeded their timeout.
- `core/microsoft_ufo_integration.py`
  - `create_ufo_api` — — 创建 UFO 集成 API
- `core/openclawd.py`
  - `OpenClawd.handle_device_command` — — 设备操控 — 通过 DeviceOrchestrator 执行设备命令
- `core/openclawd_memory_backflow.py`
  - `store_result_envelope` T — Canonical PR-7 backflow entry point for :class:`ResultEnvelope` results.
- `core/orchestration/execution.py`
  - `ExecutionPipeline.run_local` — — Delegate to ``openclawd_instance._run_execution()`` for local execution.
  - `ExecutionPipeline.run_remote` — — Delegate to OpenClawd's cross-device execution path.
- `core/orchestration/helpers.py`
  - `OrchestrationHelpers.emit_audit` T — Delegate to ``openclawd_instance._emit_audit()``.
  - `OrchestrationHelpers.emit_routing_decision_event` — — Delegate to ``openclawd_instance._emit_routing_decision_event()``.
  - `OrchestrationHelpers.apply_latency_budget` — — Delegate to ``openclawd_instance._apply_latency_budget()``.
  - `OrchestrationHelpers.build_permission_safety_state` — — Delegate to ``openclawd_instance._build_permission_safety_state()``.
  - `OrchestrationHelpers.apply_operator_overrides` — — Delegate to ``openclawd_instance._apply_operator_overrides()``.
- `core/orchestration/lifecycle.py`
  - `LifecycleManager.is_cancelled` T — Return True if *task_id* or *group_id* is in the cancel registry.
  - `LifecycleManager.finalise_plan` T — Thin delegation to _finalise_plan_lifecycle logic.
- `core/orchestration/planning.py`
  - `PlanningPipeline.determine_execution_path` T — Delegate to ``openclawd_instance._determine_execution_path()``.
  - `PlanningPipeline.build_intent_profile` — — Delegate to ``openclawd_instance._build_intent_profile()``.
- `core/orchestration/reflection.py`
  - `ReflectionPipeline.build_mainline_convergence_stamp` — — Delegate to ``openclawd_instance._build_mainline_convergence_stamp()``.
  - `ReflectionPipeline.build_execution_trace` — — Delegate to ``openclawd_instance._build_execution_trace()``.
  - `ReflectionPipeline.build_decision_timeline_snapshot` — — Delegate to ``openclawd_instance._build_decision_timeline_snapshot()``.
- `core/orchestration/state.py`
  - `SessionMemoryManager.record_turn` T — Append a conversation turn to *session_id*'s history.
  - `ContinuumStateAdapter.run_continuum` — — Delegate continuum execution to *orchestrator*.
- `core/persona/state_store.py`
  - `StateStore.reset_state` T — Reset *session_id* back to the calm/neutral baseline and return it.
- `core/react_progress.py`
  - `ToolOutcome.retriable` T — 是否值得原样重试。只有瞬时故障配。
- `core/safe_executor.py`
  - `SafeExecutor.as_tool_definition` — — 返回 OpenAI function calling 格式的工具定义
- `core/session_execution_lane.py`
  - `SessionExecutionLaneManager.list_lanes` — — 无说明
- `core/session_manager.py`
  - `SessionManager.record_verdict` — — 记录一次校验/审查（通过或否决 + 理由）。
  - `SessionManager.export_jsonl` — — 把会话证据链导出成 JSONL（可回放的「证据档案」），返回写出的文件路径。
- `core/task_memory.py`
  - `TaskMemory.evict_expired` T — 从热区移除已过期条目，返回移除数量。TTL 为 0 时为空操作。
- `core/user_preference_memory.py`
  - `UserPreferenceMemory.suggest_device_for_task` — — Suggest the best device for a task type based on history.
- `core/vector_backend.py`
  - `_QdrantBackend.add_document_vector` — — 带向量的索引（Qdrant 专用）
- `core/vision_pipeline.py`
  - `VisionResult.find_elements_by_type` — — 通过类型查找 GUI 元素
  - `VisionResult.find_element_at` — — 通过坐标查找 GUI 元素

</details>

<details><summary>语音、桌面在场与感知 — 27 条</summary>

- `core/desktop_consumption_adapter.py`
  - `DesktopClientViewModel.readiness_label` T — Return a short human-readable readiness label for display.
- `core/desktop_presence_runtime.py`
  - `DesktopPresenceRuntime.snapshot_continuous_perception` T — PR-16: Return the latest continuous host perception snapshot.
  - `DesktopPresenceRuntime.permission_safety_summary` T — PR-32: Return a shell-facing permission/trust/safety summary.
  - `DesktopPresenceRuntime.set_operator_override` T — PR-33: Commit an :class:`~core.operator_override.OperatorOverrideSet` as the active override.
  - `DesktopPresenceRuntime.operator_override_summary` T — PR-33: Return a shell-facing summary of the active operator override state.
  - `DesktopPresenceRuntime.decision_timeline_replay` T — PR-34: Return a shell-facing replay of the decision timeline.
- `core/desktop_presence_system.py`
  - `DesktopPresenceStateMachine.simulate_elapsed_time_for_testing` T — Testing helper: simulate elapsed monotonic time without sleeping.
  - `list_presence_mode_names` T — Helper for tests and schema checks.
  - `iter_presence_transition_targets` T — Helper for tests and schema checks.
- `core/duplex_presence_bridge.py`
  - `DuplexPresenceBridge.presence_handle` T — 常驻在场句柄;未开启时为 None。
- `core/fast_loop.py`
  - `active_loop_name` T — 当前生效的循环实现名("winloop"/"uvloop"/"default"),供自检展示。
- `core/interruptibility_registry.py`
  - `InterruptibilityRegistry.snapshot_all` T — 给面板/诊断看的全量视图,含陈旧标记(陈旧也要看得见,不能藏起来)。
- `core/multimodal/perception_source_registry.py`
  - `PerceptionSourceRegistry.update_quality` T — Update quality and/or latency metrics for a source.
  - `PerceptionSourceRegistry.sources_by_type` T — Return all records with the given ``source_type``.
  - `PerceptionSourceRegistry.degraded_sources` T — Return sources whose health is DEGRADED or UNAVAILABLE.
- `core/output/voice_channel.py`
  - `VoiceChannel.build_with_synthesis` — — Build a voice-channel plan with real TTS synthesis.
- `core/perception/desktop_perception_store.py`
  - `DesktopPerceptionStore.has_fresh_frame` T — 摄像头或屏幕任一有新鲜帧即为 True。隐私暂停时恒为 False。
  - `DesktopPerceptionStore.take_fresh_system_audio_for_autoinject` T — 取一段「新鲜且未被自动注入消费过」的**系统播放声**。
- `core/phase_contract.py`
  - `tri_state_of` T — 四相 → 三态公共投影。未知相位按 ``silent`` 处理。
- `core/speech_output.py`
  - `native_speech_backend_registered` T — 无说明
- `core/state_event_bus.py`
  - `StateEventBus.subscriber_count` T — Return the number of subscribers for *event_type* (or total if ``None``).
- `core/streaming_speech.py`
  - `IncrementalSpeaker.spoke_anything` T — 无说明
- `core/tts/edge_tts_engine.py`
  - `EdgeTTSEngine.set_voice` — — 设置默认声音。
  - `EdgeTTSEngine.set_rate` — — 设置语速。
- `core/voice_duplex_session.py`
  - `DuplexSession.next_event` T — 取一条事件;超时返回 None。供不想用异步迭代的调用方。
- `core/voice_echo_guard.py`
  - `is_self_echo` — — 便捷判定:这段转写是不是 AI 自己的回声。
- `core/voice_loop.py`
  - `VoiceLoop.process_once` — — 处理单次音频输入（非流式）。

</details>

<details><summary>配置、启动、安全、扩展与通用基础件 — 80 条</summary>

- `core/ascii_art.py`
  - `print_galaxy` — — 打印 Galaxy ASCII 艺术字（旧版接口，新代码请使用 print_banner()）。
- `core/cache.py`
  - `CacheManager.cache_node_status` — — 无说明
  - `CacheManager.cache_session` — — 无说明
- `core/channel_plugins.py`
  - `ConsoleChannelAdapter.inject` T — 向 inbox 注入消息（供测试使用）
  - `ChannelPluginLoader.unload_plugin` — — 卸载插件
- `core/config_hot_reload.py`
  - `HotReloadConfigManager.save_to_file` T — 原子保存配置到文件
- `core/config_preflight.py`
  - `require_env` T — Return the value of *var* or raise a descriptive RuntimeError.
- `core/config_service.py`
  - `ConfigService.set_provider_api_key` T — Store the API key for *provider* in ``runtime/secrets.env``.
  - `ConfigService.set_oneapi` T — Configure the OneAPI aggregator (lower-horizon position).
  - `ConfigService.set_toggle` T — Enable or disable a *provider* in ``runtime/config.json``.
  - `ConfigService.set_native_mm_policy` T — Set the native multimodal routing policy in ``runtime/config.json``.
  - `ConfigService.set_network_url` T — Set a network endpoint URL in ``runtime/config.json``.
  - `ConfigService.set_android_inference_mode` T — Set the Android inference mode in ``runtime/config.json``.
  - `ConfigService.describe_missing` T — Return a human-readable summary of missing or misconfigured items.
  - `ConfigService.is_provider_ready` T — Return ``True`` if *provider* is enabled and has an API key.
- `core/config_store.py`
  - `ConfigStore.write_secrets` T — Batch-write *data* to ``runtime/secrets.env``, merging with existing content.
- `core/container_runtime.py`
  - `set_runtime_choice` — — 无说明
  - `test_runtime` — — 无说明
- `core/control_plane/security_interceptor.py`
  - `SecurityInterceptor.check_and_intercept` T — Evaluate *action* / *tool* against the security policy and gate if needed.
- `core/control_plane/smart_scheduler.py`
  - `DeviceScoringEngine.rank_devices` T — Return all eligible candidates ranked best-first.
- `core/error_framework.py`
  - `ErrorTracker.is_error_spike` — — 检测是否有错误峰值
  - `error_boundary` — — 错误边界装饰器
- `core/failure_domains.py`
  - `map_to_pr_b_domain` T — Map a PR-13 implementation-specific domain to the PR-B canonical vocab.
- `core/github_installer.py`
  - `GitHubInstaller.install_dry_run` — — Validate a URL for installation without actually installing.
- `core/mcp_addon_contract.py`
  - `is_valid_mcp_addon_contract` T — Return ``True`` if *raw* passes :func:`validate_mcp_addon_contract`.
  - `build_mcp_addon_contract_summary` T — Return a compact summary dict for observability / logging.
- `core/mcp_gateway.py`
  - `MCPDynamicGateway.hot_reload_tool` — — Hot-reload a tool without restarting the gateway.
  - `MCPDynamicGateway.sync_tool_registry` — — Broadcast current tool manifest to all connected workers via NATS.
  - `MCPDynamicGateway.list_github_tools` — — Return tools registered via GitHub (source == 'github').
- `core/mcp_loader.py`
  - `MCPLoader.read_resource` — — 读取 MCP 资源
  - `MCPLoader.list_resources` — — 列出服务器的资源
  - `MCPLoader.load_from_config` T — 从配置文件加载 MCP 服务器。
  - `MCPLoader.notify_tools_list_changed` — — 向 MCP 服务器发送 tools/list_changed 通知。
- `core/message_interop.py`
  - `normalize_to_result_envelope` T — Convert a raw result dict to a canonical ``ResultEnvelope``.
- `core/operational_registration_path.py`
  - `assert_operational_registration_path_invariants` T — Assert that the operational registration path is internally consistent.
- `core/queueing/async_queue.py`
  - `AsyncTaskQueue.force_stop` — — Cancel all workers immediately without draining the queue.
- `core/reliability_contract/retry_policy.py`
  - `RetryPolicy.has_retries` T — Return ``True`` if this policy defines more than one attempt.
- `core/request_admission.py`
  - `admission_snapshot` T — 准入层的可观测快照，供诊断接口取用。
- `core/resilience/circuit_breaker.py`
  - `CircuitBreaker.trip` T — Force the circuit OPEN (useful for testing).
- `core/security_policy_loader.py`
  - `SecurityPolicy.is_category_allowed` — — 检查设备是否有权限执行某命令类别。
  - `SecurityPolicy.is_scene_allowed` — — 检查设备是否有权限触发指定场景。
  - `reload_security_policy` — — 热重载安全策略。
  - `check_policy_file_changed` — — 检查策略文件是否有变更（用于定时热重载）。
- `core/skill_contract.py`
  - `validate_skill_response` T — Validate a :class:`SkillResponse` and raise :class:`ValueError` on
- `core/skill_loader.py`
  - `SkillLoader.load_package` — — 加载技能包 (包含多个技能)
- `core/skill_package_contract.py`
  - `is_valid_skill_package_contract` T — Return ``True`` if *raw* passes :func:`validate_skill_package_contract`.
- `core/skill_registry.py`
  - `SkillRegistry.unregister_skill` T — Remove a skill from the registry.
- `core/system_mode.py`
  - `FabricConfig.is_desktop_local` T — Return ``True`` when running in ``desktop-local`` mode.
- `core/system_resource.py`
  - `seed_github_resource` T — Enroll the GitHub system resource into the registry.
  - `seed_academic_resource` T — Enroll the academic retrieval system resource into the registry.
  - `seed_engineering_resource` T — Enroll the mediated engineering loop resource into the registry.
  - `seed_device_resource` T — Enroll a runtime device resource into the registry.
  - `seed_local_tool_resource` T — Enroll a local execution tool resource into the registry.
- `core/tool_guardian.py`
  - `guarded_mcp_call` — — 对 MCPLoader.call_tool 的守护包装（可选启用）。
- `core/tool_permissions.py`
  - `ToolPermissionChecker.add_policy` — — 动态添加策略
  - `ToolPermissionChecker.reset_counters` — — 重置频率计数器
- `core/unified/command_envelope.py`
  - `CommandEnvelope.make_cancel` T — Create a CANCEL envelope targeting *task_id*.
  - `CommandEnvelope.make_interrupt` T — Create an INTERRUPT envelope targeting *task_id*.
  - `CommandEnvelope.is_cancel` T — Return ``True`` if this envelope carries a cancel or interrupt verb.
- `core/unified/device_health.py`
  - `DeviceHealthScorer.reset_device` T — Clear all samples for a device (e.g. after reconnect).
- `core/unified/error_mapper.py`
  - `ErrorMapper.from_legacy_gateway_error` T — Map a legacy gateway error type string to a canonical payload.
  - `ErrorMapper.from_legacy_device_error` T — Map a legacy device-level error string to a canonical payload.
  - `ErrorMapper.from_legacy_executor_error` T — Map a legacy executor-level error string to a canonical payload.
- `core/unified/idempotency.py`
  - `IdempotencyStore.record_failed` T — Mark *key* as FAILED (allows future re-submission of same key).
- `core/unified/release_gate.py`
  - `ReleaseGate.clear_override` T — Remove in-process override for *flag*, deferring to YAML.
  - `ReleaseGate.clear_all_overrides` T — 无说明
  - `ReleaseGate.list_flags` T — Return the current flag state (YAML + overrides merged).
- `core/unified/state_schema.py`
  - `TaskState.add_judge_record` — — Append a Judge decision to the history.
  - `TaskState.mark_verified` — — Mark an item as passed.
  - `TaskState.resolve_failure` — — Remove a failure point (on retry success).
  - `TaskState.set_goal` — — Set the user goal (Interpret step).
  - `TaskState.set_phase` — — Move to the next JudgeLoop phase.
- `core/unified_config.py`
  - `UnifiedConfig.on_change` — — 注册配置变更回调
- `core/unified_result_ingress.py`
  - `UnifiedResultIngress.reset_replay_session_state` T — Clear all tracked replay session state (test isolation helper).
- `launcher/bootstrap.py`
  - `SystemConfig.has_llm_api` T — 检查是否有可用的 LLM API
- `launcher/dependency_resolver.py`
  - `DependencyResolver.resolve_all_startup_order` — — Resolve startup order for all nodes
- `launcher/gateway.py`
  - `wait_for_gateway` T — 轮询到网关就绪，或超时。返回是否就绪。
- `launcher/nodes.py`
  - `equivalent_legacy_command` T — 给出这条新命令对应的**老**命令写法。
- `launcher/ui.py`
  - `render_banner` — — 横幅。原样走 ``ascii_art.print_banner``，一个像素不改。
  - `color_enabled` — — 当前是否会输出颜色。供调用方决定要不要走带色的分支。

</details>

<!-- END GENERATED -->
