# 未接线与不可达代码：到底是些什么东西（2026-09-28）

> 所有者的要求：**先确认清楚是些什么东西，再决定删还是接。** 本文只做清点。
> 本轮没有因为这份清单删掉或接上任何一行代码 —— 下文「随本轮任务顺带处理的」一节列出的，
> 是别的任务（会话迁移、配置写入合并）本来就要动、顺手接上的，每一处都写明了。
>
> 复测命令：
> - `python scripts/unwired_inventory.py --write` —— 刷新本文末尾的生成段（分类表 + 去处清单 + 逐文件清单）
> - `python scripts/unwired_inventory.py --check` —— 去处表（`config/unwired_placement.json`）与当前清单是否一一对得上
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
| 无测试的动作类与事件回调（159 条） | 逐条删 / 接 | 已逐条过（安卓以外），每条的去处见第 7 节 |
| 有测试、无调用方的动作类（188 条） | 逐条删 / 接 | 同上 |
| 查询、谓词、序列化、复位钩子（408 条） | 豁免 / 保持在基线 | 保持在基线即可；复位钩子可整类加进 `check_wiring.py` 的豁免 |

## 7. 每个函数放在哪里（安卓以外的 672 条）

> 所有者 2026-09-28：「700 多个函数，除了安卓部分，都搞清楚可以放在哪里」。
>
> 逐条的结论在 `config/unwired_placement.json`，文末生成段「每个函数放在哪里」按去处列全，每条写着具体放到哪。
> `python scripts/unwired_inventory.py --check` 与 `tests/test_unwired_placement.py` 守着它：清单里每条非安卓函数都要有去处，
> 表里写的每个名字都必须仍在清单里 —— 哪条接上或删掉了，表里那一条要一起删，否则测试失败。
> **这是去处，不是已执行的处置**：本轮没有按它删掉或接上任何一行，删与接仍等所有者安排（和 G002 放在一块儿）。

**怎么判的。** 每一条看四样东西：它自己的说明；它所在的模块被谁导入；同一个对象的其它方法在哪儿被用（「对象已经在那里，
只差这一个方法没调」是最常见的情形）；有没有别的实现已经在做同一件事。结论里提到行号的，都到调用点核对过。
安卓部分（83 条）按所有者安排暂缓，不在其列；另有几条函数本身不在安卓目录、但调用点在安卓处理器里，去处里写明了「安卓相关，先放着」。

| 去处 | 条数 | 说明 |
|---|---:|---|
| 接上 | 215 | 写明调用点。最集中的是 `core/command_router.py`（SLO 计数、审计事件、执行目标策略、扇出后的汇合登记）、启动（`core/startup.py`）、设备注册（`core/udm_registration_hook.py`）、重启恢复（`core/runtime_restart_recovery.py`）；节点服务里的 21 条接在各节点自己的进程里 |
| 挂出来 | 134 | 多数是给**已有**的只读路由补一个字段或端点：`core/routes/projection.py` 18、`diagnostics.py` 16、`operator.py` 14、`models.py` 9；节点自己的 HTTP 应用 15 |
| 删掉 | 170 | 每条写明被什么取代。集中在设备与节点（41，旧的设备中心操作面、零导入的传输模块）、架构治理（41，legacy 分类器与零导入的守卫模块）、配置与基础件（28，含 `ConfigService` 那几维与重复的配置写入口）、智能体（24，`core/orchestration/` 没拆完的门面、零导入的工作流模块） |
| 随对象走 | 91 | 对象上的判定 / 查询 / 扩展点。对象被用到那一处时自然会用，单独「接」没有意义；留在基线即可 |
| 测试钩子 | 50 | 复位、注入、不变量断言。本就不该有生产调用方，可整类加进 `check_wiring.py` 豁免 |
| 框架回调 | 4 | zeroconf 的 `add/update/remove_service` 与 asyncio 的 `error_received`：由框架按名字回调，清单误报 |
| 产品决定 | 8 | 跨设备剪贴板、孪生侧向实体设备下发命令、无人机 / 3D 打印机物理模型、FrugalGPT 级联作为默认对话路由、蜂群自动扩缩、Agent 跨设备迁移。接不接是功能取舍，等所有者定 |

### 7.1 逐条核对时新发现的「看得见，但不生效」

第 3 节那几簇之外，这次逐条看又确认了几处。都是**对外有入口或读取面，但执行端没接**：

1. **零信任安全策略改了不生效。** `PUT /api/v1/security/policy` 改的是 `core/routes/security_policy.py` 里那张规则表；
   这张表唯一的执行方是 `SecurityInterceptor.check_and_intercept`（`core/control_plane/security_interceptor.py`），
   它在生产里没人调。现在改那张表，只有 `/api/v1/security/policy/evaluate` 会按新规则回显，任何真实执行都不经过它。
   （设备命令下发前真正在拦的，是 `core/security_policy_loader.py` 的危险命令清单，那是另一份策略。）
2. **治理预算只能看，不管事。** 治理策略里的会话 / 每日 / 租户预算（超了 deny 或降级）由
   `BudgetEnforcer.enforce_pre_call` 执行，它零调用；用量也只有外部调 `POST /api/v1/governance/budget/record` 才记。
   模型路由自己的 `cost_budget` 只按单价给提供商重排，不是这套预算。
3. **系统资源表永远是空的。** OpenClawd 提供了列出 / 查询 / 设健康度的系统资源工具，
   投影编译器也在读 `get_system_resource_registry()`；但往表里登记资源的五个 `seed_*_resource` 零调用，没有任何地方登记。
4. **操作者覆盖（PR-33）只有运行时一半。** `DesktopPresenceRuntime.set_operator_override` 与
   `operator_override_summary` 没有端点，也没有别的调用方 —— 覆盖设不进去，读覆盖的逻辑永远读到空。
5. **安全策略文件不热重载。** OpenClawd 只在初始化时 `load_security_policy()` 一次；
   `check_policy_file_changed` / `reload_security_policy` 零调用，改策略文件要重启才生效。
6. **模型下载没有入口。** `HuggingFaceModelManager` 的下载 LLM / VLM / ASR / Embedding 与后台下载都没有端点；
   启动器缺模型时只打印一段 `python -c "..."` 让人手敲。

另有两处是**写了两份、在跑的是另一份**，归为「删掉」而不是「接上」：统一动作生命周期面的四个构造器
（`desktop_presence_runtime` 已就地从执行结果拼出同一张面）；`SecurityPolicy.is_category_allowed` / `is_scene_allowed`
（按设备类型判权，PR-SECURITY-V2 有意去掉了设备类型边界，现在所有设备同权、只看危险命令清单）。

<!-- BEGIN GENERATED: scripts/unwired_inventory.py --write -->

未接线公开能力 **630** 条，分布在 **314** 个文件。

| 维度 | 数 |
|---|---|
| 类方法 / 模块函数 | 409 / 221 |
| 只有测试在引用（写了、测了、没接） | 456 |
| 全仓连测试都没引用 | 174 |
| 所在模块本身从入口不可达 | 4 |

### 按名字表明的角色

| 角色 | 合计 | 其中只有测试引用 | 其中连测试都没有 |
|---|---|---|---|
| 测试复位钩子 | 14 | 12 | 2 |
| 序列化/转换 | 19 | 14 | 5 |
| 事件回调 | 10 | 5 | 5 |
| 判定谓词 | 96 | 81 | 15 |
| 只读查询 | 115 | 90 | 25 |
| 计算/构造 | 91 | 81 | 10 |
| 动作/变更 | 285 | 173 | 112 |

### 按用途

| 用途 | 条数 | 其中只有测试引用 | 其中连测试都没有 | 文件数 |
|---|---|---|---|---|
| 节点服务里的方法 | 39 | 2 | 37 | 20 |
| 安卓协作的契约、治理与对账层 | 83 | 76 | 7 | 40 |
| 持久化、重启恢复与断点续跑 | 52 | 47 | 5 | 13 |
| 指标、可观测与审计记录 | 48 | 45 | 3 | 21 |
| 架构治理：权威声明、边界断言与自检 | 75 | 67 | 8 | 36 |
| 多设备编组、协同网络与拓扑 | 47 | 36 | 11 | 24 |
| 设备与节点：注册、发现、连接、通信、传输 | 77 | 38 | 39 | 38 |
| 能力、模型与执行路由 | 63 | 46 | 17 | 33 |
| 智能体、认知与记忆 | 63 | 39 | 24 | 40 |
| 语音、桌面在场与感知 | 20 | 19 | 1 | 13 |
| 配置、启动、安全、扩展与通用基础件 | 63 | 41 | 22 | 36 |

### 每个函数放在哪里（安卓部分按所有者安排暂缓，不在其列）

逐条核对的结果在 `config/unwired_placement.json`。这是**去处**，不是已执行的处置：删与接都等所有者定。

| 去处 | 条数 | 意思 |
|---|---|---|
| 接上（`wire`） | 216 | 该有人调它：写明调用点（文件、第几行附近、在做什么的时候） |
| 挂出来（`surface`） | 135 | 该有人读它：写明挂到哪个端点 / 面板 / 诊断输出 |
| 删掉（`delete`） | 101 | 已被别的实现取代或根本没有用途：写明被什么取代 |
| 随对象走（`object`） | 91 | 对象上的判定 / 查询 / 扩展点：对象被用到那一处时自然会用，单独接没有意义 |
| 测试钩子（`testhook`） | 0 | 只为测试或断言存在（复位、注入、不变量断言），不该进生产路径 |
| 框架回调（`framework`） | 0 | 由第三方框架按名字回调（zeroconf、asyncio），清单误报 |
| 产品决定（`product`） | 4 | 接不接是功能取舍，不是技术问题：等所有者定 |
| 合计 | 547 | |

按用途 × 去处：

| 用途 | 接上 | 挂出来 | 删掉 | 随对象走 | 测试钩子 | 框架回调 | 产品决定 | 合计 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 节点服务里的方法 | 21 | 15 | 0 | 3 | 0 | 0 | 0 | 39 |
| 持久化、重启恢复与断点续跑 | 32 | 14 | 2 | 4 | 0 | 0 | 0 | 52 |
| 指标、可观测与审计记录 | 26 | 15 | 3 | 4 | 0 | 0 | 0 | 48 |
| 架构治理：权威声明、边界断言与自检 | 11 | 11 | 39 | 14 | 0 | 0 | 0 | 75 |
| 多设备编组、协同网络与拓扑 | 29 | 5 | 1 | 10 | 0 | 0 | 2 | 47 |
| 设备与节点：注册、发现、连接、通信、传输 | 33 | 13 | 21 | 9 | 0 | 0 | 1 | 77 |
| 能力、模型与执行路由 | 13 | 26 | 9 | 14 | 0 | 0 | 1 | 63 |
| 智能体、认知与记忆 | 20 | 15 | 7 | 21 | 0 | 0 | 0 | 63 |
| 语音、桌面在场与感知 | 5 | 10 | 1 | 4 | 0 | 0 | 0 | 20 |
| 配置、启动、安全、扩展与通用基础件 | 26 | 11 | 18 | 8 | 0 | 0 | 0 | 63 |

<details><summary>接上（wire）— 216 条</summary>

- `core/acl.py`
  - `AntiCorruptionLayer.validate_mcp_call`：core/mcp_gateway.py 执行 LLM 发起的工具调用前（它已用 acl 校验 MCP 注册，调用这一半没接）
  - `AntiCorruptionLayer.validate_worker_registration`：core/master_brain.py worker 首次接入处（它已持有 acl）
- `core/adapters/tcp_adapter.py`
  - `TCPAdapter.connect_to_peer`：core/lan_discovery.py 发现到局域网对端后主动建 TCP 直连；TCP 服务端已在 lifecycle.py 第 509 行起、入站帧已接进 message_handler
- `core/agent/intent_router.py`
  - `IntentResult.is_execution`：core/agent/kernel.py 拿到 intent 之后判断是否进执行链的地方（现在是就地比较 intent 字符串）
- `core/agent/policy_loader.py`
  - `reload_policies`：策略文件被改动后（core/routes/config.py 写配置之后）热重载；kernel.py 目前只在启动时加载一次
- `core/agent_factory.py`
  - `AgentMessageBus.notify_ack`：core/agent_team.py 成员处理完总线消息处回 ack（请求方现在只能等超时）
- `core/aip_transport.py`
  - `AIPTransport.unregister_adapter`：galaxy_gateway/bootstrap/lifecycle.py 关停阶段对称地卸下注册过的适配器
  - `AIPTransport.probe_best_transport`：AIPTransport 发送选路处（同文件 send 路径）在首选链路失败时先探测再切换；目前切换只靠静态优先级
- `core/audit_event_semantics.py`
  - `audit_route_decision`：core/command_router.py 的 CommandRouter.route_envelope 选定目标之后（与第 2562 行 emit_dispatch_decision_event 同处）；同文件的 audit_fallback_triggered / audit_retry_triggered 已在第 4056 / 4289 行这样接着
  - `audit_policy_decision`：core/runtime/execution_target_policy_engine.py 的 apply_failure_handling_policy / apply_degraded_readiness_policy 得出结论处（这两处本身也还没接，见「接上」里的 execution_target_policy_engine；接上时一起记审计）
  - `audit_failure_domain`：core/failure_domains.py 给失败定域的地方（command_router 捕获派发失败、归类 failure domain 之后）
- `core/capability_assimilation.py`
  - `CapabilityAssimilationLayer.mark_stale_if_expired`：与 NodeFabricRegistry.mark_offline_if_stale 放进同一个周期清扫（launcher/node_startup.py）
- `core/capability_bus.py`
  - `CapabilityBus.register_mcp_tool`：core/mcp_loader.py 装载 MCP 服务器后逐个工具登记进总线（现在总线里只有技能）
  - `CapabilityBus.register_engineering_capability`：core/engineering_verification.py 或工程循环启动处登记
  - `CapabilityBus.register_resource_capability`：系统资源治理能力登记处（core/concurrency_manager.py / compute_scheduler 初始化）
- `core/capability_network_bridge.py`
  - `fallback_joint_select`：core/command_router.py 联合选择（能力 + 网络路径）主选失败时（该文件已在用本模块的主选）
- `core/capability_network_runtime_policy.py`
  - `absorb_device_presence_event`：设备上下线处：core/udm_registration_hook.py 注册 / 注销时，与参与方断开（core/participant_admission.py）。同模块的 absorb_gateway_connectivity_event 已在 galaxy_gateway/gateway_nats_adapter.py 第 693 行这样接着
  - `absorb_heartbeat_event`：心跳处：core/participant_admission.py 参与方心跳、core/nats_heartbeat.py 节点心跳
  - `absorb_capability_change_event`：能力变化处：参与方接入时声明的能力（core/participant_admission.py），以及 MCP/技能装卸（core/mcp_loader.py、core/skill_loader.py）
  - `absorb_path_change_event`：core/aip_transport.py 第 446 行附近选路 / 切换传输处（该处已在读拓扑运行时）
- `core/capability_orchestrator.py`
  - `CapabilityOrchestrator.reinitialize`：docstring：MCP/Skill 变更后调用 —— core/routes/protocols.py 的 load/reload/unload 之后
- `core/cognitive/cognitive_activation_budget.py`
  - `apply_candidate_narrowing`：core/agent/execution_planner.py _pick_strategy 消费预算后收窄候选（AGENTS.md 里的三层制导之一，目前只用了广度判定）
- `core/cognitive/cognitive_field_engine.py` — `CognitiveFieldEngine.add_tick_listener`、`CognitiveFieldEngine.remove_tick_listener`：core/desktop_existence_surface.py 订阅场引擎 tick（它已持有引擎，现在是轮询）
- `core/cognitive/liminal_dynamics.py`
  - `LiminalDynamics.can_transition_to_manifest`：core/cognitive/state_interpreter.py 判定 liminal→manifest 迁移处用驻留时长守卫
- `core/cognitive/pattern_miner.py`
  - `PatternMiner.mine_full`：元层 / 夜间维护的周期任务里跑全量挖掘（增量挖掘已在用）；与 experience_guidance 的边界见 EXPERIENCE_GUIDANCE_PATTERN_MINER_BOUNDARY
- `core/compat_fallback_authority_guard.py`
  - `block_compat_influence_at_decision_site`：兼容 / 旧路径影响决策处的阻断门（PR-8 写好了门，决策点没调用）；具体决策点以 core/orchestration_authority/legacy_paths.py 登记的为准
- `core/compute_scheduler.py`
  - `ComputeScheduler.estimate_quantized_size`：core/local_model_backends.py 选量化档位前估大小
- `core/concurrency_manager.py`
  - `LockManager.release_all`：持有者（任务/会话）结束时释放它持有的全部锁；目前锁只能逐个释放
  - `ConcurrencyManager.track_task`：裸 asyncio.create_task 的后台任务处（core/truth_chain_recovery 等）登记，防泄漏
- `core/connection_manager.py`
  - `ConnectionManager.on_connected`：launcher/services.py 第 967 行 / launcher/nodes.py 第 360 行取到 get_connection_manager() 后登记回调，把上线写进 core/capability_network_runtime_policy.absorb_device_presence_event
  - `ConnectionManager.on_disconnected`：launcher/services.py 第 967 行 / launcher/nodes.py 第 360 行取到 get_connection_manager() 后登记回调，把上线写进 core/capability_network_runtime_policy.absorb_device_presence_event；下线时写 absorb_device_presence_event（与 mesh 组那条放置配对）
- `core/continuation_rebind_registry.py`
  - `ContinuationRebindRegistry.register_new_waiter`：core/runtime_restart_recovery.py 重启后重新派发、登记新的等待方处（该文件已在用这个注册表记「待重绑」，但从不记「已重绑」，于是闭环永远判不成）
- `core/control_plane/security_interceptor.py`
  - `SecurityInterceptor.check_and_intercept`：工具真正执行之前（openclawd ReAct 循环调工具处）。PUT /api/v1/security/policy 改的那张零信任规则表，唯一的读者就是它，而它在生产里没人调 —— 现在改那张表对任何执行都不起作用，只有 /evaluate 端点会回显
- `core/control_plane/smart_scheduler.py`
  - `DeviceScoringEngine.rank_devices`：galaxy_gateway/wake_router.py 选唤醒设备处要全排名（现在只取最佳）；或诊断里展示排名
- `core/critical_path_harness.py`
  - `record_ingress_path`：openclawd 多模态入口处（它已在同一模块调 record_provider_switch / record_route_selection）
  - `record_execution_dispatch`：openclawd 执行派发处（openclawd 已在同一模块调 record_provider_switch / record_route_selection）
- `core/cross_device_sync.py`
  - `push_task_state_to_device`：安卓相关（推任务状态到手机），先放着；非安卓参与方要这个能力时，放在 core/participant_admission.py 的任务状态更新处
- `core/dag_evolver.py`
  - `DAGEvolver.on_missing_capability`：core/constellation_runtime.py 执行 DAG 时遇到能力缺口的分支（它已持有 DAGEvolver）
- `core/decision_timeline.py`
  - `record_source_switch_event`：core/desktop_presence_runtime.py 感知源切换处（该文件第 2742 行已在往 decision_timeline 记别的事件）
- `core/delegated_flow_decision_history.py`
  - `record_delegated_flow_event`：安卓委托流状态变化处（安卓相关，按你的意思先放着）
- `core/delegated_flow_persistence.py`
  - `DelegatedFlowPersistenceBundle.persist_all`：launcher/shutdown.py 关闭前落一次，外加委托流实体状态变化后落盘；恢复协调器第 1101 行 _has_durable_persistence 读的正是这里写的东西
  - `persist_session_snapshot`：随 persist_all 一起
  - `restore_sessions`：core/runtime_restart_recovery.py run_startup_recovery 加一步：启动时读回委托流四类对象
  - `persist_contract_snapshot`：随 persist_all 一起
  - `restore_contracts`：core/runtime_restart_recovery.py run_startup_recovery 加一步：启动时读回委托流四类对象
  - `persist_binding_snapshot`：随 persist_all 一起（它的一部分）
  - `restore_bindings`：core/runtime_restart_recovery.py run_startup_recovery 加一步：启动时读回委托流四类对象
  - `persist_flow_entity_snapshot`：随 persist_all 一起
  - `restore_flow_entities`：core/runtime_restart_recovery.py run_startup_recovery 加一步：启动时读回委托流四类对象
- `core/delegated_flow_recovery_coordinator.py` — `decide_recovery`、`decide_recovery_from_continuity_artifact`、`begin_recovery_attempt`、`complete_recovery_attempt`、`suppress_recovery_attempt`：安卓设备带着在途委托流重连时（galaxy_gateway/android/handlers/registration.py 的重连分支）：先 decide_recovery，再 begin / complete。整个协调器在生产里没有驱动方；安卓相关，按你的意思先放着
- `core/device_agent_manager.py`
  - `DeviceAgentManager.connect_all`：launcher/core_services.py 第 32 行创建 DeviceAgentManager 之后调用一次
- `core/device_communication.py`
  - `DeviceCommunication.on_device_message`：core/startup.py 第 539 行创建 DeviceCommunication 之后，把设备消息接到 core/event_bridge.py（event_bridge 已在读同一对象）
- `core/device_formation/formation_auto_enrollment.py`
  - `FormationAutoEnrollmentManager.update_device_readiness`：core/mesh/mesh_auto_enrollment.py（已持有该管理器）收到就绪确认时
- `core/device_orchestrator.py`
  - `DeviceOrchestrator.register_device_in_pool`：core/udm_registration_hook.py 设备注册处同步进 DevicePoolManager（否则池里只有 command_router 自己放进去的设备）
- `core/error_framework.py`
  - `ErrorTracker.is_error_spike`：core/health_integration.py（已持有 ErrorTracker）健康判定里加错误峰值
- `core/execution_observability/normalizers.py`
  - `normalize_task_envelope`：core/command_router.py route_envelope 收到信封时产出执行事件（现在执行事件只有部分来源）
  - `normalize_task_graph_result`：core/task_graph_runtime.py 任务图跑完处
  - `normalize_arbiter_attempt`：core/orchestration/global_arbiter.py 仲裁记一次尝试处
- `core/failure_domains.py`
  - `map_to_pr_b_domain`：core/schemas/execution_failure.py 生成失败记录时归到 PR-B 规范词表（两套词表现在各说各的）
- `core/feedback_loop.py`
  - `FeedbackLoop.should_use_local`：本地 / 云端选择处（core/agent_supply.py 供给决策）作为建议输入
- `core/flow_continuity_coordinator.py` — `coordinate_attach`、`coordinate_reattach_process_recreation`、`coordinate_stale_identity`、`coordinate_duplicate_signal`、`coordinate_partial_result`、`coordinate_v2_restart_recovery`：安卓附着 / 重附着 / 重复信号 / 部分结果 / 重启恢复各自的处理点（galaxy_gateway/android/handlers/*）。便捷包装，底下的协调器方法才是本体；安卓相关，先放着
- `core/focus_stack.py`
  - `FocusStack.drop_current`：会话结束 / 用户明确切走话题处（core/session_memory_facade.py 已持有 FocusStack）
- `core/gateway_capability_default_enforcement.py`
  - `audit_gateway_override`：网关能力门禁被显式绕过处（galaxy_gateway/routing/device_selection.py 的 override 分支）记审计
- `core/governance/budget_enforcer.py`
  - `BudgetEnforcer.enforce_pre_call`：core/unified/llm_router.py 每次调模型前（超了按策略 deny 或降级到备用模型）。现在治理策略里的会话 / 每日 / 租户预算只能经 GET /api/v1/governance/budget/{session_id} 看、经 POST .../budget/record 由外部记，没有一次模型调用会因它被拦或降级；UnifiedLLMRouter 自己的 cost_budget 只按单价重排提供商，不是这套预算
  - `BudgetEnforcer.reset_session`：会话结束处（core/session_manager.py 关闭会话）
- `core/grounded_planner.py`
  - `to_task_assign`：core/routes/ui_act.py 已调 plan()，把规划出的动作落成 TASK_ASSIGN 下发设备时用它（现在规划完只返回）
- `core/health_evidence_policy.py`
  - `has_health_evidence`：core/device_pool_manager.py 第 237 行已用 no_evidence_score，判「有没有证据」时用它，别再各自手判
- `core/hybrid_orchestration_continuity.py`
  - `HybridOrchestrationContinuityRegistry.clear_terminal`：周期清理：与 run_startup_recovery 同处或一个定时任务，否则终态记录只增不减
  - `save_hybrid_execution`：core/hybrid_executor.py 每次 registry.transition 之后（第 521 行起共 8 处），或直接放进 HybridOrchestrationContinuityRegistry.transition 里：现在状态只在内存里变，从不落盘，重启恢复第 4 步读到的永远是空
- `core/interaction/pending_decision_registry.py`
  - `PendingDecisionRegistry.sweep_expired`：待决项的周期清扫（与 truth_chain_recovery 同类后台任务）；现在超时的待决项只在被读到时才发现
- `core/log_redaction.py`
  - `redact_secret`：core/routes/config.py 与 core/config_service.py 记日志涉及密钥值的地方（同模块别的函数已被节点用上）
- `core/mcp_addon_contract.py`
  - `build_mcp_addon_contract_summary`：core/github_installer.py 安装 MCP 插件后记日志 / 审计
- `core/mcp_gateway.py`
  - `MCPDynamicGateway.hot_reload_tool`：core/routes/protocols.py 的 MCP reload 端点（现在只重载 loader，网关侧工具不刷新）
  - `MCPDynamicGateway.sync_tool_registry`：MCP 装卸之后经 NATS 广播工具清单（多节点时才有意义）
- `core/mcp_loader.py`
  - `MCPLoader.load_from_config`：core/startup.py 启动时按配置装 MCP 服务器（owner 已被 startup 使用，本方法没有）
  - `MCPLoader.notify_tools_list_changed`：技能 / 工具变动后通知 MCP 服务器（core/github_installer.py 安装后）
- `core/mesh/device_role_allocator.py` — `DeviceRoleAllocator.register_capability_rule`、`DeviceRoleAllocator.allocate_all`：core/mesh/body_mesh_registry.py 设备上线 / 能力变化后给在线设备分配角色（allocate_all）；自定义规则在启动时登记。整个分配器目前只被 core/mesh/__init__ 导出
- `core/mesh/live_mesh_session_coordinator.py`
  - `LiveMeshSessionCoordinator.on_android_participant_signal`：安卓 Mesh 参与信号的入口，安卓相关，先放着
- `core/mesh/mesh_auto_enrollment.py`
  - `notify_readiness_confirmed`：设备就绪确认处：core/device_readiness.py 判定就绪后（同模块的 notify_device_registered / notify_capability_reported 已在注册、能力上报处接着）
  - `notify_device_lost`：设备失联处：core/udm_registration_hook.py 注销 / 心跳超时标离线时
- `core/mesh/mesh_session_coordinator.py` — `MeshSessionCoordinator.update_with_dispatch_result`、`MeshSessionCoordinator.update_with_takeover_result`、`MeshSessionCoordinator.update_with_merged_result`：core/mesh/live_mesh_runtime_engine.py 拿到派发结果 / 接管结果 / 合并结果时更新协调器（现在协调器状态只在投影读取时用，没人往里写结果）
- `core/mesh/mesh_session_lifecycle.py`
  - `associate_resumed_execution_with_session`：core/runtime_restart_recovery.py 恢复出 RESUMABLE 任务、且它属于某个 Mesh 会话时
- `core/mesh_coordinator.py`
  - `inject_mesh_senders`：galaxy_gateway/bootstrap/lifecycle.py 启动时把网关的发送函数注入 Mesh 协调器（不注入时协调器发不出消息）
- `core/mesh_nats_fusion.py` — `MeshNATSConvergence.submit_participant_result`、`MeshNATSConvergence.subscribe_session`、`MeshNATSConvergence.unsubscribe_session`：core/mesh/live_mesh_runtime_engine.py（已持有 MeshNATSConvergence）：会话开始订阅、参与方结果回来提交、会话结束退订
- `core/multimodal/perception_source_registry.py`
  - `PerceptionSourceRegistry.update_quality`：core/multimodal/ingest_runtime.py 每次摄入测到时延 / 质量时回写（它已持有注册表）
  - `PerceptionSourceRegistry.degraded_sources`：core/multimodal/source_recovery_policy.py 选恢复对象时
- `core/nats_bus.py`
  - `NATSBus.publish_task_event`：任务生命周期写点（core/canonical_task.py 状态迁移处）发 galaxy.task.*
  - `NATSBus.publish_device_event`：core/udm_registration_hook.py 注册/注销处发 galaxy.device.*
  - `NATSBus.publish_capability_event`：能力变化处（core/mcp_loader.py、core/skill_loader.py 装卸）发 galaxy.capability.*
- `core/network_topology_runtime.py`
  - `NetworkTopologyRuntime.update_edge_state`：core/aip_transport.py 探测到链路质量变化时
  - `assimilate_nats_state`：core/nats_bus.py 连上 / 断开 NATS 时
  - `assimilate_gateway_state`：galaxy_gateway/bootstrap/lifecycle.py 网关起停时
  - `assimilate_device_connectivity`：设备连接状态变化：core/udm_registration_hook.py 与参与方心跳
- `core/node_discovery.py`
  - `NodeDiscoveryService.on_node_joined`：现在没人订阅节点加入/离开/更新。订阅方放在 core/node_discovery_runtime.py（它已负责把 fabric 节点种进发现服务），转给 core/capability_network_runtime_policy.absorb_device_presence_event
  - `NodeDiscoveryService.on_node_left`：现在没人订阅节点加入/离开/更新。订阅方放在 core/node_discovery_runtime.py（它已负责把 fabric 节点种进发现服务），转给 core/capability_network_runtime_policy.absorb_device_presence_event
  - `NodeDiscoveryService.on_node_updated`：现在没人订阅节点加入/离开/更新。订阅方放在 core/node_discovery_runtime.py（它已负责把 fabric 节点种进发现服务），转给 core/capability_network_runtime_policy.absorb_device_presence_event
  - `NodeDiscoveryService.deregister_node`：launcher/node_startup.py 节点停止 / 健康检查失败处（那里已调 announce_node_to_discovery 做上线），对称地注销
- `core/nodes/node_fabric_registry.py`
  - `NodeFabricRegistry.mark_offline_if_stale`：launcher/node_startup.py 加一个周期清扫（该文件已持有 NodeFabricRegistry）
  - `NodeFabricRegistry.list_by_capability`：按能力选节点处（core/command_router.py 能力选路）；或 core/routes/projection.py 查询
  - `NodeFabricRegistry.expire_stale_capabilities`：launcher/node_startup.py 的周期清扫里，与 mark_offline_if_stale 一起跑
- `core/openclawd_memory_backflow.py`
  - `store_result_envelope`：openclawd / desktop_presence_runtime 目前用 store_task_result；拿到 ResultEnvelope 的地方（结果真相链收口处）改用规范入口
- `core/operational_slo_metrics.py`
  - `OperationalSLOMetrics.record_dispatch_attempt`：core/command_router.py route_envelope 派发前（第 2562 行 emit_dispatch_decision_event 同处）
  - `OperationalSLOMetrics.record_dispatch_success`：core/command_router.py route_envelope 派发前（第 2562 行 emit_dispatch_decision_event 同处）；派发结果成功时
  - `OperationalSLOMetrics.record_dispatch_failure`：core/command_router.py route_envelope 派发前（第 2562 行 emit_dispatch_decision_event 同处）；派发结果失败时
  - `OperationalSLOMetrics.record_route_rejection`：core/command_router.py 第 2099 / 2139 行「capability-mismatch/reject」分支
  - `OperationalSLOMetrics.record_fallback_triggered`：core/command_router.py 第 2077 行「capability-mismatch/fallback」分支与第 4056 行 audit_fallback_triggered 同处
  - `OperationalSLOMetrics.record_recovery_attempt`：core/runtime_restart_recovery.py 恢复协调器对每个在途任务定处置时
  - `OperationalSLOMetrics.record_recovery_resumed`：core/runtime_restart_recovery.py 恢复协调器对每个在途任务定处置时；处置为 RESUMABLE 并续上时
  - `OperationalSLOMetrics.record_recovery_replayed`：core/runtime_restart_recovery.py 恢复协调器对每个在途任务定处置时；处置为 REPLAY_ONLY 时
  - `OperationalSLOMetrics.record_recovery_reissued`：core/runtime_restart_recovery.py 恢复协调器对每个在途任务定处置时；重新派发时
  - `OperationalSLOMetrics.record_recovery_failed`：core/runtime_restart_recovery.py 恢复协调器对每个在途任务定处置时；恢复失败 / 放弃时
  - `OperationalSLOMetrics.record_startup_recovery_scan`：core/runtime_restart_recovery.py run_startup_recovery 得出报告后（报告里已有扫描数与动作数）
  - `OperationalSLOMetrics.record_audit_persist_success`：core/replay_audit_persistence.py ReplayAuditStore.append 返回 True 时
  - `OperationalSLOMetrics.record_audit_persist_failure`：core/replay_audit_persistence.py ReplayAuditStore.append 返回 True 时；返回 False / 抛错时
- `core/orchestration/global_arbiter.py`
  - `GlobalArbiter.suggest_device`：core/request_admission.py（已持有仲裁器）请求未指定设备时给建议
- `core/outward_truth_source_registry.py`
  - `enforce_surface_contract`：core/unified_panel_aggregation.py 组装面板字段时强制来源登记（它已 import 本模块）
- `core/peer_trust.py`
  - `trust_rank`：core/execution/readiness_gate.py 比较信任级别处（它已 import peer_trust）
- `core/perception/desktop_perception_store.py`
  - `DesktopPerceptionStore.has_fresh_frame`：core/multimodal/ingest_runtime.py 取帧前先判新鲜度（隐私暂停时恒 False，正好当门）
  - `DesktopPerceptionStore.take_fresh_system_audio_for_autoinject`：core/multimodal/system_audio_ingest.py 自动注入系统播放声处
- `core/phase_contract.py`
  - `tri_state_of`：四相 → 三态投影的调用方（core/lumiv_websocket_bridge.py、liminal_activity）目前各自手写映射，换成它
- `core/presence/presence_director.py` — `PresenceDirector.on_phase_transition`、`PresenceDirector.refresh_presence`：core/desktop_presence_runtime.py 相位切换时通知 PresenceDirector 把在场投射到其它设备 —— 这是跨设备在场，按「只有电脑发起的进三态」的规则，只在电脑发起的跨设备任务里触发
- `core/proxy_relay.py`
  - `ProxyRelay.relay_envelope`：core/scheduler.py（已持有 ProxyRelay）目标设备不可直达、需要经中继转发任务信封时
- `core/queueing/async_queue.py`
  - `AsyncTaskQueue.force_stop`：进程关停时（launcher 关停阶段）在排空超时后强停
- `core/react_progress.py`
  - `ToolOutcome.retriable`：openclawd ReAct 循环判断是否原样重试工具处
- `core/resilience/metrics.py`
  - `ResilienceMetrics.record_circuit_open`：core/resilience/circuit_breaker.py 第 214 / 245 行状态切到 OPEN 时
- `core/routing_explanation/live_decision.py`
  - `LiveRoutingDecisionBuilder.record_policy_band`：core/command_router.py 里用 LiveRoutingDecisionBuilder 组装选路解释的地方（已在用这个类），把当时的执行策略档一并记上
- `core/routing_observability.py`
  - `ControlLoopMetrics.record_projection_mismatch`：core/routes/projection.py 投影与控制面对账不一致处（现只统计不记数）
  - `build_fallback_decision_event`：core/openclawd.py 第 1992 行 record_routing_decision 同处，决策是回退时
- `core/runtime/execution_target_policy_engine.py`
  - `apply_failure_handling_policy`：command_router 派发失败分支
  - `apply_degraded_readiness_policy`：core/command_router.py 第 2749 行已调 apply_target_selection_policy，就绪度降级时再过这一条
- `core/safe_executor.py`
  - `SafeExecutor.as_tool_definition`：把安全执行器作为工具登记进 LLM 工具列表（core/routes/config_schema_registry.py 已引用 SafeExecutor）
- `core/security_policy_loader.py`
  - `reload_security_policy`：一个定时任务里：check_policy_file_changed() 为真就调它。openclawd 只在初始化时 load_security_policy() 一次，改策略文件现在要重启才生效。注意 core/routes/security_policy.py 管的是另一张零信任规则表，不是这份文件
  - `check_policy_file_changed`：一个定时任务里：文件变了就 reload_security_policy()。openclawd 只在初始化时 load_security_policy() 一次，改策略文件现在要重启才生效
- `core/session_manager.py`
  - `SessionManager.record_verdict`：裁决产生处（core/meta 裁决 / engineering_verification 结论）写进会话证据链
- `core/skill_contract.py`
  - `validate_skill_response`：core/skill_registry.py 执行技能拿到响应后校验
- `core/skill_loader.py`
  - `SkillLoader.load_package`：core/github_installer.py 装技能包处（现在逐个 load_skill）
- `core/skill_registry.py`
  - `SkillRegistry.unregister_skill`：core/routes/protocols.py DELETE /skills/{name} 卸载时同步移出注册表（现在只卸 loader）
- `core/swarm_coordinator.py` — `SwarmCoordinator.build_execution_plan_for_orchestration`、`SwarmCoordinator.device_candidates_from_canonical`：galaxy_gateway/wake_router.py / core/remote_execution_mode_resolver.py（已持有 SwarmCoordinator）需要多设备执行计划时
- `core/system_resource.py` — `seed_github_resource`、`seed_academic_resource`、`seed_engineering_resource`、`seed_device_resource`、`seed_local_tool_resource`：core/startup.py 启动时把 GitHub / 学术检索 / 工程循环 / 本地工具 / 设备登记进系统资源注册表（projection 在读这张表，但从没人写）
- `core/target_device_validator.py`
  - `validate_target_device_from_canonical`：core/command_router.py / galaxy_gateway/routing/device_selection.py 已 import 本模块，把它们的校验换成规范入口
- `core/task_envelope_lifecycle_registry.py`
  - `TaskEnvelopeLifecycleRegistry.cancel_timed_out`：周期任务：galaxy_gateway/gateway_nats_adapter.py 已持有这个注册表，放它的清扫循环里；否则超时的待办信封永远挂着
  - `TaskEnvelopeLifecycleRegistry.resume_for_device`：设备重连处：galaxy_gateway/android/handlers/registration.py 的 handle_device_reconnect / 参与方心跳恢复（core/participant_admission.py）—— 让重连设备续上待办
- `core/task_graph_runtime.py`
  - `TaskGraphRuntime.register_fanin`：core/command_router.py 的 _route_parallel_fanout_envelope 扇出子信封后，为汇总节点登记汇合边（该文件第 2462 行已把每个信封登记进 TaskGraphRuntime，只有扇出没有汇合）
  - `result_envelope_to_node_update`：core/unified_result_ingress.py 结果进来更新任务图节点处（现用自己的更新逻辑，可改为调这个）
  - `project_workflow_to_graph`：core/agentic/workflow.py 的 WorkflowRunner 跑完一个工作流之后，把记录投到任务图（strategy.py 经 `from core.agentic import workflow as wf` 在用这个模块）
- `core/task_lifecycle.py`
  - `TaskLifecycleManager.mark_interrupted`：叫停处：core/routes 的 /api/v1/presence/stop 与 launcher/shutdown.py 关闭时，把在途信封标为 interrupted
  - `TaskLifecycleManager.run_with_lifecycle`：core/command_router.py 第 1767 / 2944 行已在用 get_lifecycle_manager 手动 mark_*；本地执行那段可改为用它包起来
- `core/task_memory.py`
  - `TaskMemory.evict_expired`：core/task_lifecycle.py 周期维护里清热区（TTL 已配置但从未执行清理）
- `core/truth_integration_layer.py`
  - `is_device_available_canonical`：选设备前的可用性判定（smart_scheduler.select_best_device 过滤候选）
- `core/unified/command_envelope.py` — `CommandEnvelope.make_cancel`、`CommandEnvelope.make_interrupt`、`CommandEnvelope.is_cancel`：取消 / 中断任务处（core/routes/tasks.py cancel、presence_stop）构造 CANCEL / INTERRUPT 信封
- `core/unified/device_health.py`
  - `DeviceHealthScorer.reset_device`：设备重连时（core/udm_registration_hook.py 注册）清掉旧健康样本
- `core/unified/llm_router.py`
  - `UnifiedLLMRouter.reload_policy`：config/llm_routing_policy.yaml 被改动时（core/routes/config.py 写配置之后）热重载
- `core/unified_execution_governance.py`
  - `resolve_execution_conflict`：两种执行类型冲突处（hybrid_executor 同时起本地 / 远端时）求规范解
- `core/user_preference_memory.py`
  - `UserPreferenceMemory.suggest_device_for_task`：选设备处（smart_scheduler.select_best_device）作为建议输入
- `core/vision_pipeline.py` — `VisionResult.find_elements_by_type`、`VisionResult.find_element_at`：core/vision_ui_projection.py（已持有 VisionResult）按坐标 / 类型找元素，替换手写遍历
- `galaxy_gateway/agent_bridge.py`
  - `AgentBridge.handoff_from_envelope`：galaxy_gateway/device_router.py 第 1244 行现在先手工拼 HandoffContract 再调 bridge.handoff；手里本来就是 TaskEnvelope，改走这个 PR-2 规范入口
- `galaxy_gateway/cross_device_switch.py`
  - `guard_cross_device`：跨设备入口（galaxy_gateway/routes/chat.py、device_router 跨设备分支）；这些文件已 import 本模块但用的是 is_cross_device_enabled 手判
- `galaxy_gateway/device_router.py`
  - `DeviceRouter.aggregate_results`：多设备任务收口处：galaxy_gateway/orchestrator/parallel_tracker.py finalize 之后汇总
- `galaxy_gateway/gateway_nats_adapter.py`
  - `GatewayNATSAdapter.resolve_task`：本适配器订阅 galaxy.task.result 的回调里按 task_id 解开等待中的 future
- `galaxy_gateway/observability.py`
  - `TraceContext.child_span`：galaxy_gateway/device_router.py 一个任务扇出到多台设备时给每路一个子 span（该文件已在用 TraceContext）
- `galaxy_gateway/orchestrator/parallel_tracker.py`
  - `ParallelGroupTracker.finalize_if_complete`：record_parallel_fields 记录每个子结果之后调用
  - `ParallelGroupTracker.expire_timeouts`：网关周期任务（galaxy_gateway/bootstrap/lifecycle.py）定时清扫超时并行组
- `galaxy_gateway/session_roaming.py`
  - `SessionRoamingManager.update_task_state`：任务状态迁移处同步到漫游会话（会话里带着任务时）
  - `SessionRoamingManager.auto_migrate_on_attention_shift`：注意力焦点变化处（唤醒事件 galaxy_gateway/wake_router.py 判定出新设备后）经 core/session_migration.migrate_session 迁移
  - `SessionRoamingManager.load_snapshot`：漫游管理器初始化时从 GALAXY_DATA_DIR 读快照（本轮已让持久化目录跟随 GALAXY_DATA_DIR）
- `galaxy_gateway/ssot.py`
  - `udm_write_upsert`：设备状态增量更新处（handle_status / 感知上报）经 SSOT 写 UDM；register/heartbeat/unregister 已这样接
- `galaxy_gateway/wake_router.py`
  - `WakeRouter.set_decision_callback`：唤醒路由判定后的回调：接 SessionRoamingManager.auto_migrate_on_attention_shift（见上）
- `galaxy_gateway/webrtc_proxy.py`
  - `order_ice_candidates`：proxy_webrtc_signaling 转发 ICE 候选前排序去重（get_webrtc_endpoint_info 已宣称按此顺序）
  - `clear_webrtc_task_session`：core/command_router.py 第 1937 行附近 teardown_binding_on_task_terminal 处（任务终态时），与 register_webrtc_task_session 配对
- `launcher/bootstrap.py`
  - `SystemConfig.has_llm_api`：launcher/doctor.py 体检里报「没有可用 LLM API」
- `launcher/nodes.py`
  - `equivalent_legacy_command`：launcher/doctor.py 提示老命令写法时用
- `nodes/Node_108_MetaCognition/main.py`
  - `MetaCognitionEngine.comprehend`：本节点感知→理解→决策流程里的理解一步（core/metacognition_engine.py 是它的副本）
- `nodes/Node_112_SelfHealing/main.py`
  - `SelfHealingEngine.run_once`：本节点的自愈循环（server.py 起的周期任务）
- `nodes/Node_58_ModelRouter/main.py`
  - `DatabaseManager.save_session_turn`：本节点路由一次对话后记轮次（表已建，从没写过）
- `nodes/Node_70_AutonomousLearning/core/autonomous_learning_engine.py` — `AutonomousLearningEngine.generalize_skill`、`AutonomousLearningEngine.find_similar_skills`、`AutonomousLearningEngine.process_observation`、`AutonomousLearningEngine.update_experience_outcome`：本节点 fusion_entry.py 的学习循环（launcher/services.py 已起引擎，但观察→经验→泛化这几步没人调）
- `nodes/Node_71_MultiDeviceCoordination/core/canonical_device_view_adapter.py` — `CoordinationDeviceView.mark_task_assigned`、`CoordinationDeviceView.mark_task_released`：本节点 multi_device_coordinator_engine.py 分配 / 释放任务处
- `nodes/Node_71_MultiDeviceCoordination/core/device_discovery.py` — `DeviceDiscovery.add_device`、`DeviceDiscovery.discover_now`：本节点 coordinator engine 启动时发现 / 登记设备
- `nodes/Node_71_MultiDeviceCoordination/core/fault_tolerance.py` — `FailoverManager.set_primary`、`FailoverManager.add_secondary`、`FailoverManager.remove_secondary`、`FailoverManager.register_health_checker`：本节点 coordinator engine 设置主备设备与健康检查
- `nodes/Node_71_MultiDeviceCoordination/core/state_synchronizer.py`
  - `StateSynchronizer.handle_gossip_message`：本节点收到 gossip 消息的入口
- `nodes/Node_71_MultiDeviceCoordination/models/task.py` — `Task.update_progress`、`TaskQueue.dequeue`、`TaskQueue.is_empty`：本节点 task_scheduler.py 取任务 / 报进度处
- `nodes/Node_74_DigitalTwin/main.py`
  - `TwinDeviceRegistration.to_registered_runtime_device`：孪生设备登记时投影成规范 RegisteredRuntimeDevice 写入设备真相（docstring：anti-drift 锚定）
- `nodes/Node_89_APIGateway/main.py`
  - `GatewayService.proxy_via_route`：本节点代理请求处按路由表转发

</details>

<details><summary>挂出来（surface）— 135 条</summary>

- `core/adapters/ble_adapter.py`
  - `BLEAdapter.list_connected`：传输诊断：与 AIPTransport.transport_stats 一起进 core/routes/diagnostics.py（BLEAdapter 已在 galaxy_gateway/bootstrap/lifecycle.py 第 500 行注册）
- `core/adapters/tailscale_p2p_adapter.py`
  - `TailscaleP2PAdapter.list_registered_devices`：core/routes/pairing.py 的 Tailscale 状态里列出 device_id → 100.x 地址（适配器已在 lifecycle.py 第 482 行注册）
- `core/agent_identity_memory.py` — `AgentIdentityMemory.add_goal`、`AgentIdentityMemory.remove_goal`、`AgentIdentityMemory.add_value`：身份记忆的目标/价值增删：挂到 core/routes/ai.py（或面板「智能体」页）；现在只能读不能改
- `core/agent_team.py`
  - `TeamManager.list_teams`：core/routes/ai.py 列出团队
- `core/aip_transport.py`
  - `AIPTransport.transport_stats`：core/routes/diagnostics.py：链路统计（docstring 自己写着供面板/诊断查看选路依据）
- `core/canonical_session_axis.py` — `resolve_session_family_for_identifier`、`build_session_axis_snapshot`：core/routes/projection.py（已 import）给出会话轴快照
- `core/canonical_task_dispatch_chain.py` — `classify_dispatch_path`、`is_canonical_path`、`is_android_inbound_path`、`build_dispatch_chain_snapshot`：core/routes/projection.py（已 import 本模块）给出派发链快照 / 路径分类
- `core/capabilities/canonical_dispatcher.py`
  - `CanonicalDispatcher.bus_catalog`：诊断端点列出 CapabilityBus 快照；与 core/routes/protocols.py 的技能/MCP 列表放在一起
- `core/capability_graph_selection.py`
  - `explain_selection`：与 mesh 组的 explain_joint_selection 一起进 core/routes/operator.py 选路解释
- `core/capability_network_bridge.py`
  - `explain_joint_selection`：选路解释：core/routes/operator.py /api/v1/operator/inspect/route/{task_id} 一并给出人话解释
- `core/capability_network_runtime_policy.py`
  - `snapshot_canonical_runtime`：core/routes/projection.py 或诊断端点：能力 + 网络的统一快照
- `core/capability_orchestrator.py` — `CapabilityOrchestrator.list_capabilities`、`CapabilityOrchestrator.enable_capability`、`CapabilityOrchestrator.disable_capability`：core/routes/protocols.py 加能力启停；或整模块随旧能力层退役（legacy）
- `core/capability_tier.py`
  - `list_capabilities_by_tier`：core/routes/diagnostics.py 按层级列能力
- `core/channel_plugins.py`
  - `ChannelPluginLoader.unload_plugin`：core/routes/channels.py 加卸载渠道插件（已有加载）
- `core/cognitive/long_term_memory.py`
  - `LongTermMemory.forget_namespace`：记忆管理：「忘掉这一类」端点（与 core/routes/sessions.py 的会话删除同层）
- `core/cognitive/memory_bias_layer.py`
  - `build_memory_bias_active_scope_diagnostics`：core/routes/projection.py（已 import）给出记忆偏置作用域诊断
- `core/compat_fallback_authority_guard.py`
  - `build_authority_hardening_snapshot`：core/routes/projection.py 给出权威加固态势
- `core/compute_scheduler.py`
  - `ModelAllocation.is_offloaded`：core/routes/models.py /status 里带上算力监控是否在跑、已加载模型数；逐个分配标出是否被卸到 CPU
  - `ComputeScheduler.is_monitoring`：core/routes/models.py /status 里带上算力监控是否在跑、已加载模型数
  - `ComputeScheduler.loaded_model_count`：core/routes/models.py /status 里带上算力监控是否在跑、已加载模型数
- `core/config_service.py`
  - `ConfigService.describe_missing`：core/routes/config.py 的配置状态里给出人话缺项（它已持有 ConfigService）
- `core/container_runtime.py` — `set_runtime_choice`、`test_runtime`：core/routes/system.py 加「选容器运行时（docker/podman）/ 试一下」；launcher/services.py 已用本模块做探测
- `core/continuation_rebind_registry.py` — `ContinuationRebindRegistry.is_pending_rebind`、`ContinuationRebindRegistry.is_loop_closed`、`ContinuationRebindRegistry.pending_rebind_count`、`ContinuationRebindRegistry.rebound_count`、`ContinuationRebindRegistry.list_pending_task_ids`：core/routes/operator.py /api/v1/operator/inspect/recovery/{task_id} 一并返回「待重绑 / 已重绑 / 闭环」
- `core/continuum/return_engine.py`
  - `ReturnEngine.force_return`：操作者「立即回到静默」控制：core/routes/operator.py
- `core/control_plane/audit_ledger.py` — `AuditLedger.verify_chain`、`AuditLedger.to_dag`：core/routes/audit.py：/api/v1/audit/snapshot 旁加「账本完整性」与 DAG 导出（账本本身已被 31 个模块写入）
- `core/critical_path_harness.py`
  - `snapshot_critical_path`：core/routes/diagnostics.py 关键路径快照
- `core/degraded_operation_envelope.py`
  - `envelope_summary`：openclawd 已构造降级信封；投影时用它出紧凑摘要进 core/routes/projection.py
- `core/delegated_flow_recovery_coordinator.py`
  - `DelegatedFlowRecoveryCoordinator.list_recent_attempts`：core/routes/operator.py 恢复检查端点一并返回
- `core/desktop_presence_runtime.py`
  - `DesktopPresenceRuntime.snapshot_continuous_perception`：core/routes/perception.py 连续感知最新快照
  - `DesktopPresenceRuntime.permission_safety_summary`：core/routes/operator.py 或面板「全部设置」给出权限 / 信任 / 安全摘要
  - `DesktopPresenceRuntime.set_operator_override`：core/routes/operator.py 写操作者覆盖（core/routes 与网关路由里都没有 operator_override 端点；PR-33 只做了运行时一半）
  - `DesktopPresenceRuntime.operator_override_summary`：core/routes/operator.py 读当前操作者覆盖（core/routes 与网关路由里都没有 operator_override 端点）
  - `DesktopPresenceRuntime.decision_timeline_replay`：core/routes/operator.py 加决策时间线回放（PR-34 写好了，没有端点）
- `core/device_activation_registry.py`
  - `DeviceActivationRegistry.export_json`：core/routes/diagnostics.py 加一个只读端点（注册表由 udm_registration_hook / launcher 写入，没人能读出来）
- `core/device_communication.py`
  - `DeviceCommunication.list_connected_devices`：core/routes/twin.py 已持有 DeviceCommunication，可在设备孪生视图里列出当前连接
- `core/device_formation/formation_auto_enrollment.py`
  - `FormationAutoEnrollmentManager.list_active_device_ids`：诊断 / 面板：编组里当前有哪些设备
- `core/device_node_domain_governance.py`
  - `classify_registry_surface`：core/routes/projection.py（已 import）按模块路径查注册面分类
- `core/device_node_resolver.py` — `DeviceNodeResolver.list_supported_device_types`、`DeviceNodeResolver.list_supported_transports`：core/routes/diagnostics.py：列出解析器支持的设备类型 / 传输（resolver 已被 launcher/launcher_adapter.py、launcher/services.py 使用）
- `core/device_orchestrator.py`
  - `DeviceOrchestrator.parallel_commands`：core/routes/devices.py（已用 get_device_orchestrator）加「对多台设备并行下发」端点；或由 command_router 多设备分支调用
- `core/digital_twin_engine.py` — `DigitalTwinEngine.couple_all`、`DigitalTwinEngine.decouple_all`：core/routes/twin.py 批量耦合 / 解耦
- `core/fast_loop.py`
  - `active_loop_name`：docstring：供自检展示 —— main.py --check-only 输出与 core/routes/diagnostics.py
- `core/feedback_loop.py`
  - `FeedbackLoop.record_user_evaluation`：对话回答上的「好 / 不好」反馈端点（面板已有对话流，可加按钮）
- `core/github_installer.py`
  - `GitHubInstaller.install_dry_run`：core/routes/github.py 加「装之前先检查」
- `core/governance/budget_enforcer.py`
  - `BudgetEnforcer.all_session_ids`：core/routes/governance.py 列出被计费的会话
- `core/governance/tool_governor.py`
  - `ToolGovernor.clear_audit_log`：core/routes/governance.py 清审计日志（运维操作）
  - `ToolGovernor.reset_bucket`：core/routes/governance.py 加「复位某工具的限流桶」运维端点（check_wiring 的说明里明确点名它是真实的运行时操作，不是测试钩子）
- `core/huggingface_model_manager.py` — `HuggingFaceModelManager.download_llm`、`HuggingFaceModelManager.download_vlm`、`HuggingFaceModelManager.download_asr`、`HuggingFaceModelManager.download_embedding`、`HuggingFaceModelManager.download_background`：core/routes/models.py 加「下载模型」端点（后台下载 + 进度）；launcher/services.py 目前只在提示文字里教用户手敲 python -c
- `core/hybrid_execution_policy.py`
  - `HybridExecutionPolicy.describe_mode`：混合执行状态接口里给出人话模式说明（core/routes/hybrid.py）
- `core/hybrid_orchestration_continuity.py` — `HybridOrchestrationContinuityRegistry.list_non_terminal`、`HybridOrchestrationContinuityRegistry.list_terminal`、`HybridOrchestrationContinuityRegistry.list_interrupted`：core/operator_surface.py（已在读这个注册表）一并给出
- `core/interruptibility_registry.py`
  - `InterruptibilityRegistry.snapshot_all`：docstring：给面板 / 诊断看 —— core/routes/diagnostics.py
- `core/local_brain_manager.py`
  - `LocalBrainManager.switch_brain`：core/routes/models.py 加「切换本地主脑模型」（面板模型页）
  - `LocalBrainManager.remove_model`：core/routes/models.py 加「删除本地模型」
- `core/mcp_gateway.py`
  - `MCPDynamicGateway.list_github_tools`：core/routes/github.py 列出经 GitHub 装入的工具
- `core/mcp_loader.py`
  - `MCPLoader.read_resource`：core/routes/protocols.py 加 GET /api/v1/protocols/mcp/{name}/resources；读单个资源
  - `MCPLoader.list_resources`：core/routes/protocols.py 加 GET /api/v1/protocols/mcp/{name}/resources
- `core/mesh/mesh_auto_enrollment.py`
  - `MeshAutoEnrollmentService.list_enrolled_device_ids`：诊断端点 /api/v1/mesh/participation-summary 一并返回
- `core/mesh/mesh_session_lifecycle.py` — `MeshSessionLifecycleCoordinator.list_active_session_ids`、`MeshSessionLifecycleCoordinator.list_restorable_session_ids`：core/routes/diagnostics.py /api/v1/mesh/participation-summary 一并返回活跃 / 可恢复会话
- `core/model_openness.py`
  - `audit_registry`：docstring：诊断用 —— core/routes/models.py 加开放性审计视图
- `core/model_topology/provider_inventory.py` — `ProviderInventory.unavailable_entries`、`ProviderInventory.top_by_quality`、`ProviderInventory.top_by_speed`、`ProviderInventory.top_by_composite`：core/routes/projection.py（已读 ProviderInventory）给出按质量/速度/综合排序与不可用条目
- `core/multi_device_coordination_authority.py`
  - `coordination_role_description`：角色的人话说明：随多设备状态投影一起输出
- `core/multi_device_runtime_harness.py`
  - `MultiDeviceCoherenceHarness.to_canonical_projection`：core/routes/projection.py 给出多设备一致性 harness 的读侧投影（docstring：anti-drift 锚定）
- `core/node_capability_loader.py`
  - `NodeCapabilityLoader.list_node_actions`：core/routes/diagnostics.py：列某节点提供的动作（加载器已在 lifecycle.py 使用）
- `core/node_communication.py`
  - `NodeRegistry.detect_partitions`：core/routes/projection.py（已读 NodeRegistry）给出网络分区检测结果
- `core/peer_trust.py`
  - `PeerTrustBook.set_trust`：core/routes/pairing.py（已读 PeerTrustBook）加「设为信任 / 取消信任」端点
- `core/persona/state_store.py`
  - `StateStore.reset_state`：「重置情绪状态」：core/routes/sessions.py 会话重置时一并调用
- `core/presence/presence_projection.py`
  - `PresenceProjection.last_events`：诊断：最近的在场投射事件
- `core/protocol_drift_registry.py`
  - `drift_entries`：core/routes/diagnostics.py 加只读端点（漂移由安卓消息解析时 coerce_protocol_enum 登记，现在只进不出）
  - `drift_summary`：core/routes/diagnostics.py 加只读端点（漂移由安卓消息解析时 coerce_protocol_enum 登记，现在只进不出）；也可进 /api/v1/readiness
  - `has_unrecognized_drift`：core/routes/diagnostics.py 加只读端点（漂移由安卓消息解析时 coerce_protocol_enum 登记，现在只进不出）；就绪判定里作为一个告警项
- `core/replay_audit_persistence.py`
  - `load_audit_records`：core/routes/operator.py /api/v1/operator/inspect/audit-evidence/{task_id}（审计记录一直在写，接口读不回落盘的那部分）
- `core/replay_foundation.py`
  - `ReplayFoundation.replay_task_timeline`：core/routes/tasks.py（已在用 ReplayFoundation）加 /api/v1/tasks/{id}/timeline
- `core/request_admission.py`
  - `admission_snapshot`：docstring：供诊断接口取用 —— core/routes/diagnostics.py
- `core/resilience/metrics.py`
  - `ResilienceMetrics.rejection_rate_per_minute`：core/routes/resilience.py（该路由已读同一个指标对象）
- `core/routing_observability.py`
  - `build_routing_analytics_snapshot`：core/routes/observability.py /api/v1/observability/model-route 一并返回
- `core/runtime/runtime_observability_sink.py` — `RuntimeObservabilitySink.list_device_lifecycle_events`、`RuntimeObservabilitySink.list_mesh_session_transition_events`、`RuntimeObservabilitySink.list_dispatch_decision_events`、`RuntimeObservabilitySink.list_recovery_decision_events`、`RuntimeObservabilitySink.counters`：core/routes/observability.py 加只读端点：事件由安卓桥、Mesh、命令路由、参与方接入写入，现在只有 build_observability_snapshot 汇总读得到明细
- `core/runtime_closure_audit.py`
  - `run_closure_audit`：core/api_routes.py 已 import 本模块（只取了哨兵常量）；做成诊断端点，或 scripts/ 下的离线审计
- `core/session_execution_lane.py`
  - `SessionExecutionLaneManager.list_lanes`：GET /api/v1/agent/activity 一并列出会话执行通道（desktop_presence_runtime 已持有管理器）
- `core/session_manager.py`
  - `SessionManager.export_jsonl`：core/routes/sessions.py 加「导出会话证据」下载
- `core/slo_metrics.py`
  - `SLOMetrics.startup_duration_ms`：core/routes/monitoring.py /api/v1/slo/metrics（已读同一对象）
- `core/speech_output.py`
  - `native_speech_backend_registered`：core/routes/openai_audio.py /v1/audio/capabilities 报告原生说通路是否登记
- `core/state_event_bus.py`
  - `StateEventBus.subscriber_count`：core/routes/diagnostics.py 列出每类事件的订阅数（没订阅者的事件一眼可见）
- `core/tailscale_manager.py` — `TailscaleManager.is_tailscale_installed`、`TailscaleManager.is_headscale_mode`：core/routes/pairing.py 的 Tailscale 状态（是否安装、是否 Headscale）；launcher/services.py 已持有 TailscaleManager
- `core/task_cost_ledger.py`
  - `current_task_bill`：core/routes/cost.py 加「当前任务账单」（账单由 desktop_presence_runtime 开/关、openclawd 与路由器记账）
- `core/task_envelope_lifecycle_registry.py`
  - `TaskEnvelopeLifecycleRegistry.all_pending_task_ids`：launcher/shutdown.py 关闭时报告还有多少待办；或诊断端点
- `core/tool_permissions.py`
  - `ToolPermissionChecker.add_policy`：core/routes/security_policy.py 加工具权限策略
- `core/truth_projection_boundary.py`
  - `classify_surface_boundary`：core/routes/projection.py（已 import）按路径查真相边界分类
- `core/unified/release_gate.py`
  - `ReleaseGate.list_flags`：core/routes/diagnostics.py 列出发布闸门当前状态
- `core/voice_loop.py`
  - `VoiceLoop.process_once`：非流式单次处理：core/routes/openai_audio.py 语音转写→回答的一次性端点；否则删
- `galaxy_gateway/session_roaming.py`
  - `SessionRoamingManager.close_session`：galaxy_gateway/routes/sessions.py 加关闭漫游会话
- `nodes/Node_05_Auth/main.py`
  - `AuthManager.has_permission`：本节点 app 加 POST /check-permission；或在本节点受保护端点里用作门
  - `AuthManager.delete_user`：本节点 app 加 DELETE /users/{id}（已有 /register /login）
- `nodes/Node_106_GitHubFlow/main.py`
  - `GitHubClient.create_pull_request`：本节点 /workflow/issue_to_pr 流程的最后一步（现在停在生成代码）；或加 POST /create_pr
- `nodes/Node_109_ProactiveSensing/main.py` — `ProactiveSensingEngine.unregister_sensor`、`ProactiveSensingEngine.remove_rule`：本节点 app 加移除规则 / 注销传感器（已有登记）
- `nodes/Node_112_SelfHealing/main.py`
  - `SelfHealingEngine.unregister_health_check`：本节点 app 加注销健康检查
  - `SelfHealingEngine.register_recovery_handler`：本节点 app 加恢复处理器登记
- `nodes/Node_116_ExternalToolWrapper/main.py`
  - `ExternalToolWrapper.unregister_tool`：本节点 app 加 DELETE /tools/{tool_id}（已有 POST /tools、GET /tools/{tool_id}）
  - `ExternalToolWrapper.execute_custom`：本节点 app 执行自定义工具
- `nodes/Node_14_FFmpeg/main.py`
  - `FFmpegManager.merge_videos`：本节点 app 加 POST /merge（已有 /convert /clip /extract-audio /screenshot）
- `nodes/Node_54_SymbolicMath/main.py` — `CrossDisciplinaryVerifier.verify_physics`、`CrossDisciplinaryVerifier.verify_engineering`：本节点 /verify 按学科分派时调用（现在只做通用验证）
- `nodes/Node_71_MultiDeviceCoordination/models/device.py`
  - `DeviceRegistry.count_by_state`：本节点 /status 按状态统计设备
- `nodes/Node_72_KnowledgeBase/knowledge_base_system.py` — `KnowledgeBaseSystem.export_knowledge`、`KnowledgeBaseSystem.import_knowledge`：本节点 app 加导出 / 导入知识库（core/rag_memory.py 已持有该对象）

</details>

<details><summary>删掉（delete）— 101 条</summary>

- `core/ai_intent.py`
  - `SemanticSearch.index_document`：SemanticSearch 整个类在生产里没人实例化（原唯一调用方是已删的 index_document_vector）；知识检索走 core/rag_memory.py → 知识库节点
- `core/cache.py`
  - `CacheManager.set_json`：command_router 自己缓存节点状态 / 会话；这两个 Redis 缓存写入没有对应的读取方
- `core/capability_assimilation.py`
  - `assimilate_node`：便捷包装；core/participant_admission.py 等直接调 CapabilityAssimilationLayer
- `core/capability_aware_routing_default.py`
  - `apply_capability_aware_default`：command_router / openclawd 只用本模块的 infer_dispatch_capabilities；「能力感知为默认主路径」已在 command_router 里成立
- `core/capability_bus.py`
  - `CapabilityBus.seed_from_node_registry`：从 node_registry.json 种总线；节点能力已由 NodeFabricRegistry → CapabilityRegistry 提供
- `core/command_router.py`
  - `CommandRouter.normalize_legacy_ingress`：非信封载荷已在各入口（android_bridge、app.py）各自转信封；这是第二套归一化
- `core/config_hot_reload.py`
  - `HotReloadConfigManager.save_to_file`：生产里唯一在写配置的是 POST /api/config（SYSTEM_STATUS §6.4 复核结论）；第二个写入口不该接
- `core/config_preflight.py`
  - `require_env`：预检用 validate 汇总报缺，不逐个抛错；无调用方
- `core/config_service.py`
  - `ConfigService.set_provider_api_key`：密钥写入已经走 ConfigService.set_secret（POST /api/config 在用）；这是重复入口
  - `ConfigService.set_oneapi`：写 runtime/config.json 的 provider 开关，运行时没有读者（结论 config-json-provider-dims-have-no-runtime-reader）；所有者答复不要这项新能力
  - `ConfigService.set_toggle`：写 runtime/config.json 的 provider 开关，运行时没有读者（结论 config-json-provider-dims-have-no-runtime-reader）；所有者答复不要这项新能力
  - `ConfigService.set_native_mm_policy`：写 runtime/config.json 的 provider 开关，运行时没有读者（结论 config-json-provider-dims-have-no-runtime-reader）；所有者答复不要这项新能力；native_multimodal_policy 没有运行时读者
  - `ConfigService.set_network_url`：写 runtime/config.json 的 provider 开关，运行时没有读者（结论 config-json-provider-dims-have-no-runtime-reader）；所有者答复不要这项新能力
  - `ConfigService.set_android_inference_mode`：写 runtime/config.json 的 provider 开关，运行时没有读者（结论 config-json-provider-dims-have-no-runtime-reader）；所有者答复不要这项新能力；（安卓部分本就暂缓）
- `core/config_store.py`
  - `ConfigStore.write_secrets`：批量写密钥；生产走 set_secret 逐条写
- `core/constellation_runtime.py`
  - `warn_legacy_path`：为旧编排器路径打弃用告警用；旧路径已登记在 legacy_paths，有统一的 emit_legacy_guardrail
- `core/cross_device_dispatch_boundary.py` — `classify_dispatch_call`、`is_canonical_dispatch`、`is_controlled_fallback`、`is_compat_fallback`、`is_legacy_bypass`：legacy 的跨设备派发边界分类；派发的规范路径已由 command_router 决定，分类器没有决策点在读
- `core/decision_diff_telemetry.py`
  - `record_candidate_diff`：迁移期的新旧选路差异遥测（模块自标 legacy）。唯一还在用的是 entrypoint_router 的 record_entry_mode_diff；跨设备候选选择已只剩新路径，没有「旧的」可比
- `core/desktop_consumption_adapter.py`
  - `DesktopClientViewModel.readiness_label`：legacy 的桌面视图模型；面板只认 WS payload.render（docs/RENDER_CONTRACT_DIRECTION.md）
- `core/device_registry.py`
  - `DeviceRegistry.check_offline_devices`：兼容缓存的离线扫描；离线判定已由 NodeFabricRegistry.mark_offline_if_stale / UDM 心跳承担
  - `DeviceRegistry.negotiate_capability`：能力协商已由注册时的能力上报 + core/capability_network_runtime_policy 取代
- `core/device_types.py`
  - `device_type_to_platform`：简化 DeviceType → AIP 平台的映射，生产无人调用，只有测试
- `core/e2e_orchestrator.py`
  - `run_multi_device_via_task_graph`：多设备扇出已由 core/command_router.py 的 _route_parallel_fanout_envelope 承担，并登记进 TaskGraphRuntime
  - `process_user_input`：「统一用户输入入口」已由 openclawd / command_router 承担；本模块只有 process_wake_event 被 galaxy_gateway/websocket_handler.py 调用
- `core/execution_observability/normalizers.py`
  - `normalize_e2e_context`：产出源是 core/e2e_orchestrator.process_user_input，它本身无人调用、判为该删（见「删掉」）；e2e_orchestrator 里真正被用的只有 process_wake_event
- `core/execution_spine.py`
  - `route_via_spine`：legacy：CommandRouter.route_envelope 是唯一入口
- `core/galaxy_main_loop_l4_enhanced.py`
  - `GalaxyMainLoopL4.receive_goal`：launcher/services.py 第 2297 行注释已查明：主启动链不拉它，真正的自主性由 ambient_attention_loop → OpenClawd 承担
- `core/generative_ui/runtime.py`
  - `GenerativeUIRuntime.render_surface_dict`：to_dict 的便利包装
- `core/governance_validation_gate.py`
  - `evaluate_governance_validation`：模块级便利函数；调用方都直接用类
- `core/hybrid_orchestration_continuity.py` — `load_hybrid_execution`、`recover_hybrid_executions`：run_startup_recovery 第 4 步已直接用 store 读回；这个便捷包装是重复入口
- `core/mainline_convergence.py` — `MainlineMetadataFrame.is_mainline`、`MainlineExecutionTrace.visits_openclawd`、`MainlineExecutionTrace.visits_capability_dispatch`、`MainlineExecutionTrace.visits_knowledge`、`MainlineConvergenceRegistry.record_from_response`、`MainlineConvergenceRegistry.list_by_path_class`、`MainlineConvergenceRegistry.assert_mainline_dominant`、`reset_mainline_convergence_registry`、`record_mainline_execution`：legacy 的主线收敛登记；openclawd 只读了 trace 的三个属性，登记 / 断言侧无人调用
- `core/mcp_addon_contract.py`
  - `is_valid_mcp_addon_contract`：validate_mcp_addon_contract 的布尔包装
- `core/message_interop.py`
  - `normalize_to_result_envelope`：legacy 结果归一；ResultEnvelope 已在各入口直接构造
- `core/modality_bridge.py`
  - `resolve_audio_in`：ambient_attention_loop 的注释记录了它原先的短路用法已被撤掉；判定在 core/modality_capability 里
- `core/model_topology/config_bridge.py`
  - `ConfigBridge.build_inventory`：legacy：从 dashboard 时代输入建库存；dashboard 已退役
- `core/model_topology/topology_router.py`
  - `TopologyRouter.route_all_phases`：legacy：投影用单相 route()，三相一起算无人调用
- `core/multi_device_control_integrity.py` — `MultiDeviceIntegritySnapshot.gaps_by_area`、`build_entry_unification_record`：legacy 多设备完整性审计的构造器 / 查询
- `core/native_modal.py`
  - `is_native_active`：modality_bridge 按档位自己判定；布尔包装无人用
- `core/nats_bus.py`
  - `NATSBus.publish_legacy_task_result`：[Legacy] 旧 TaskResult 发布；AIP v3 TASK_RESULT 是规范路径
- `core/node_discovery.py`
  - `NodeDiscoveryService.seed_from_registry`：从 node_registry.json 预填充；实际启动走 core/node_discovery_runtime.seed_fabric_nodes_into_discovery（从 NodeFabricRegistry 种），这条被取代
- `core/node_lifecycle_governor.py`
  - `node_governance_snapshot`：legacy 的便利包装
- `core/orchestration/helpers.py`
  - `OrchestrationHelpers.emit_audit`：PR-7 拆 openclawd 留下的门面，全部委托回 openclawd 私有方法且无人调用；真要拆 openclawd 是另一件大事
- `core/orchestration/planning.py`
  - `PlanningPipeline.determine_execution_path`：PR-7 拆 openclawd 留下的门面，全部委托回 openclawd 私有方法且无人调用；真要拆 openclawd 是另一件大事
- `core/orchestration_review_surface.py`
  - `increment_legacy_dispatch_counter`：已被网关的 galaxy_legacy_dispatch_total 指标（galaxy_gateway/observability.py，含告警规则）取代，两套计数重复
- `core/outward_runtime_truth.py` — `OutwardRuntimeTruthRuntime.snapshot_list`、`OutwardRuntimeTruthRuntime.compile_count`、`classify_signal`：legacy：对外真相由 core/routes/projection.py 的编译器产出，这几个分类 / 计数无人读
- `core/repo_layout_registry.py` — `is_active_desktop_status_directory`、`build_repo_layout_summary`：legacy、零导入
- `core/runtime_invariant_enforcement.py` — `check_invariant`、`check_cross_repo_assumption`：零导入；不变量检查已由 scripts/check_* 守卫承担
- `core/scheduling_truth_harness.py` — `query_routable_executors_for_task`、`assert_scheduling_truth_convergence`：便利包装；query_routable_executors 已被 device_pool_manager 直接调用
- `core/skill_package_contract.py`
  - `is_valid_skill_package_contract`：validate_* 的布尔包装
- `core/system_mode.py`
  - `FabricConfig.is_desktop_local`：legacy；桌面本地判定由 core/presence_line.py 负责
- `core/task_result_canonical_truth_chain.py`
  - `IncompleteResultLedger.all_incomplete`：账本原始视图；对外读面已是本轮的 GET /api/v1/results/isolated（只出类型化字段）
- `core/truth_conflict_enforcement.py` — `assert_canonical_write_precedes_compat_write`、`assert_no_parallel_write_authority`、`check_compat_write_is_mirror_only`、`is_truth_convergence_healthy`：legacy、零导入
- `core/ui_surface_authority.py` — `is_legacy_surface`、`is_projection_driven_surface`：legacy、零导入
- `core/unified/error_mapper.py` — `ErrorMapper.from_legacy_gateway_error`、`ErrorMapper.from_legacy_device_error`、`ErrorMapper.from_legacy_executor_error`：legacy 错误串映射；新错误已按规范载荷产出
- `core/unified_action_lifecycle_surface.py` — `build_from_dispatch`、`apply_blocker`、`apply_confirmation`、`close_surface`：core/desktop_presence_runtime.py 第 1515–1594 行已从执行结果就地拼出这张面（阶段、阻断、确认、收口全在），在跑的是那一份；这几个构造器是重复实现
- `core/unified_dispatch_readiness_gate.py`
  - `reset_dispatch_readiness_gate`：空操作，docstring 自称只为 API 对称
- `galaxy_gateway/agent_bridge.py`
  - `AgentBridge.build_envelope_v2`：旧 HandoffContract → Envelope v2 的转换；只被 legacy_paths 登记引用
- `galaxy_gateway/enhanced_nlu_v2.py`
  - `DeviceRegistry.find_device_by_name`：零导入的旧 NLU 模块
- `galaxy_gateway/multimodal_transfer.py` — `MultimodalTransferManager.receive_image`、`MultimodalTransferManager.send_video`、`MultimodalTransferManager.send_file_chunk`、`MultimodalTransferManager.receive_file_chunk`、`MultimodalTransferManager.send_screenshot`：整个模块零导入；文件传输走 galaxy_gateway/android/handlers/file_transfer.py
- `galaxy_gateway/orchestrator/task_orchestrator.py`
  - `MultiDeviceOrchestrator.submit_multi_device_task`：PR-2 后多设备任务强制经 TaskGraph；本入口只被 legacy_paths 登记
- `galaxy_gateway/resumable_transfer.py` — `ResumableTransferManager.receive_file`、`ResumableTransferManager.write_chunk`：整个模块零导入；与 file_transfer handler 重复
- `galaxy_gateway/routing/router.py` — `RoutingOrchestrator.filter_eligible`、`RoutingOrchestrator.build_message`：RoutingOrchestrator 零导入；选设备 / 构造消息由同目录 device_selection.py、dispatch.py 承担
- `galaxy_gateway/task_decomposer.py` — `TaskDecomposer.decompose_search_and_open`、`TaskDecomposer.decompose_conditional_task`：已登记在 core/legacy_purge_registry.py 的旧任务分解器
- `galaxy_gateway/transport/websocket_server.py`
  - `WebSocketManager.handle_connection`：规范设备 WS 入口是 galaxy_gateway/routes/websocket.py → websocket_handler.handle_websocket
- `galaxy_gateway/websocket_handler.py`
  - `handle_response`：TASK_RESULT 在 handle_message 里已整体转给 android_bridge（_ANDROID_DOMAIN_KINDS），本函数没有分派入口
- `launcher/gateway.py`
  - `wait_for_gateway`：模块零导入；launcher/services.py 起网关时自己轮询

</details>

<details><summary>随对象走（object）— 91 条</summary>

- `core/agent_manifest.py`
  - `AgentManifest.create_multi_step_agent`：随 core/routes/nodes.py 创建 Agent 的端点：需要多步顺序 Agent 时从那里调
- `core/agent_team.py` — `AgentTeam.couple_member`、`AgentTeam.decouple_member`：耦合模式切换随团队对象：core/control_plane/swarm_scaler.py 扩缩容时用
- `core/canonical_ownership_truth_bridge.py` — `is_recovery_eligible`、`build_ownership_aware_replay_execution_record`：唯一导入方是 core/android_participant_truth_ingress.py：安卓参与方真相那一侧，按所有者安排暂缓
- `core/capability_bus.py`
  - `CapabilityBusRole.from_tool_name`：随下面的 register_* 一起：登记时按工具名推断角色
- `core/capability_network_runtime_policy.py`
  - `query_capable_device_executors`：与已接线的 query_routable_executors（device_pool_manager 在用）重复的窄化版；要么删，要么在需要「只要设备型执行者」的地方替换调用
- `core/capability_runtime/capability_constraint.py`
  - `CapabilityConstraintFlags.has_any_constraint`：值对象上的判断方法，随 capability_runtime 这一对象被消费时一起用
- `core/capability_runtime/capability_preference.py`
  - `CapabilityPreference.has_preference`：值对象上的判断方法，随 capability_runtime 这一对象被消费时一起用
- `core/cognitive/cognitive_activation_budget.py` — `ActivationBudget.is_narrow`、`ActivationBudget.is_moderate`、`ActivationBudget.is_broad`：值对象判定方法，随 kernel/execution_planner 读预算时用
- `core/cognitive/cognitive_execution_policy.py` — `CognitiveExecutionHint.is_manifest`、`CognitiveExecutionHint.is_liminal`、`CognitiveExecutionHint.is_passive`：值对象判定方法（is_liminal / is_manifest / is_passive），调用方目前直接比枚举
- `core/cognitive/long_term_memory.py`
  - `LongTermMemory.retrieve_entry`：单条取回，随长期记忆被按 id 读取时用
- `core/cognitive/memory_bias_layer.py` — `MemoryBias.is_continuity`、`MemoryBias.is_retrieval`、`MemoryBias.is_novelty`：值对象判定方法，随 execution_planner 消费偏置时用
- `core/cognitive/state_interpreter.py` — `StateInterpreter.interpret_snapshot`、`StateInterpreter.last_region`：解释器的只读方法，随 cognitive_execution_policy 读状态时用
- `core/compat_legacy_path_blocking_canonicalization.py`
  - `CompatLegacyBlockingRecord.is_quarantined`：legacy 记录上的判定方法，随 block_compat_influence_at_decision_site 一起
- `core/concurrency_manager.py` — `ConcurrencyManager.run_with_concurrency`、`ConcurrencyManager.run_with_lock`：API 形状的便利方法；调用方都直接用信号量/锁。有新调用需求时才用，否则删
- `core/config_service.py`
  - `ConfigService.is_provider_ready`：随 describe_missing 一起用
- `core/continuum/temporal_engine.py` — `DwellGuard.remaining_ms`、`TemporalEngine.smoothed_signals`：只读快照 / 剩余驻留时长，随 continuum orchestrator 投影时用
- `core/control_plane/swarm_manifest.py`
  - `SwarmAgentManifest.to_agent_execute_payload`：清单对象的转换；core/swarm_coordinator.py 派发蜂群任务时用（它已持有这个对象）
- `core/control_plane/swarm_scaler.py`
  - `SwarmScaler.managed_workers`：随 autoscale 一起
- `core/cross_device_policy/routing_policy.py` — `RoutingPolicy.source_assignment`、`RoutingPolicy.devices_with_role`：策略对象自带查询；读 RoutingPolicy 的地方（model_topology、routing_explanation）按需调用
- `core/delegated_flow_decision_history.py` — `HistoryEvidenceStatus.allows_runtime_closure`、`HistoryEvidenceStatus.is_definitive_gap`：证据状态自带判定；读这份历史的验收面（system_final_acceptance_verdict 等）按需调用
- `core/device_agent_manager.py`
  - `DeviceAgentManager.register_agent_type`：扩展点：新的设备 Agent 类型需要时由插件/启动配置调用；目前没有第二种类型，留着不接
- `core/device_formation/formation_runtime_coordinator.py`
  - `FormationParticipantStatus.is_viable`：参与者状态自带判定；编组调度选参与者时用
- `core/device_registry.py`
  - `DeviceRegistry.project_to_contract`：把旧记录投影成规范 RegisteredRuntime：留到旧注册表整体退役时一起删，退役前是迁移工具
- `core/device_worker_convergence.py`
  - `DeviceWorkerConvergence.is_worker_registered`：core/unified/device_manager.py（已用这个类）派发前判断设备是否已作为 NATS Worker 在线时用
- `core/duplex_presence_bridge.py`
  - `DuplexPresenceBridge.presence_handle`：只读属性，随 voice_loop / conversation_mainline 需要在场句柄时读
- `core/execution/decision_executor.py`
  - `PolicyGate.check_action_level`：随 PolicyGate 一起：openclawd 已用 PolicyGate 的其它判定
- `core/execution_observability/event_schema.py`
  - `ExecutionEvent.projection_summary`：ExecutionEvent 自带的摘要；/api/v1/observability/execution/* 返回事件时按需调用
- `core/execution_observability/executor_level.py`
  - `ExecutorLevel.from_win_exec_level`：枚举换算；构造执行事件时用
- `core/execution_observability/trace_schema.py`
  - `TraceCorrelation.from_task_graph`：TraceCorrelation 的构造器；从任务图出事件时用（随 normalize_task_graph_result 一起接）
- `core/hybrid_execution_policy.py` — `HybridExecutionMode.is_concurrent`、`HybridExecutionMode.is_degrade_chain`：枚举上的判定；core/hybrid_executor.py 分支判断处替换手写比较
- `core/mesh/body_mesh_registry.py`
  - `BodyEntry.has_role`：条目自带判定；core/routes/panel.py 等读 BodyEntry 的地方按角色筛选时用
- `core/mesh/mesh_runtime_center_state.py` — `is_valid_center_transition`、`MeshParticipantEligibilityStatus.can_participate`：状态机的判定函数；推进中心侧 Mesh 状态时用
- `core/model_topology/canonical_model_supply_state.py`
  - `NativeMultimodalCapabilityRegistry.register_many`：登记能力记录的批量版，随 NativeMultimodalCapabilityRegistry 被批量填充时用
- `core/model_topology/model_supply_graph.py` — `ModelSupplyGraph.edges_of_kind`、`ModelSupplyGraph.nodes_by_category`、`ModelSupplyGraph.nodes_by_provider`：图的查询方法：随 core/model_topology/routing_policy.py 需要按类别/供应商筛选时用
- `core/multi_device_canonical_governance.py`
  - `MultiDeviceGovernanceVerdict.is_single_device`：裁决对象上的判定，随 core/system_final_acceptance_verdict.py 读裁决时用
- `core/multi_subject_closure_machine.py` — `ClosureTerminalKind.is_success_family`、`ClosureTerminalKind.is_partial_family`、`ClosureTerminalKind.is_failure_family`：枚举分族判定，随 galaxy_gateway/multi_subject_closure_surface.py 需要时用
- `core/multimodal/perception_source_registry.py`
  - `PerceptionSourceRegistry.sources_by_type`：按类型查询，随调用方需要时用
- `core/node_cognition_activation.py` — `evaluate_activation_eligibility`、`transition_activation_state`：节点激活资格判定 + 状态迁移：随「节点按角色激活」这一对象一起接；core/routes/projection.py 已读本模块其余部分
- `core/node_registry.py`
  - `NodeRegistry.register_node_class`：随 NodeRegistry 这一对象：若保留则由 launcher/node_startup.py 调用；与 NodeFabricRegistry 职责重叠，二选一时一起定
  - `NodeRegistry.start_health_monitor`：随 NodeRegistry 这一对象：若保留则由 launcher/node_startup.py 调用；与 NodeFabricRegistry 职责重叠，二选一时一起定；健康监控目前由 NodeFabricRegistry 心跳超时承担
  - `NodeRegistry.stop_health_monitor`：随 NodeRegistry 这一对象：若保留则由 launcher/node_startup.py 调用；与 NodeFabricRegistry 职责重叠，二选一时一起定
  - `NodeRegistry.load_all_nodes`：随 NodeRegistry 这一对象：若保留则由 launcher/node_startup.py 调用；与 NodeFabricRegistry 职责重叠，二选一时一起定
- `core/operator_execution_observability_surface.py`
  - `OperatorExecutionEvidenceEntry.requires_operator_attention`：证据条目自带判定；operator 面汇总「需要人看」时用
- `core/orchestration/lifecycle.py` — `LifecycleManager.is_cancelled`、`LifecycleManager.finalise_plan`：LifecycleManager 已被 openclawd 使用；这两个方法是薄委托，调用方直接用内部实现
- `core/orchestration/state.py`
  - `SessionMemoryManager.record_turn`：openclawd 已持有 SessionMemoryManager；对话轮次写入目前走 session_manager，二者重叠，定一个
- `core/recovery_truth_surface.py` — `RecoveryLevel.all_levels`、`RecoveryTruthReport.has_deferred`：报告对象自带判定；读恢复真相的验收面按需调用
- `core/reliability_contract/retry_policy.py`
  - `RetryPolicy.has_retries`：值对象判定，随重试策略被消费时用
- `core/remote_execution_mode_resolver.py`
  - `ModeResolutionResult.as_remote_execution_mode`：结果对象上的转换方法，调用方需要枚举时用
- `core/runtime_closure_audit.py`
  - `persist_conflict_artifacts`：随 run_closure_audit 一起：审计发现冲突时落盘
- `core/runtime_readiness_matrix.py`
  - `is_release_blocked`：core/routes/operator.py 已读就绪矩阵；需要布尔时用
- `core/streaming_speech.py`
  - `IncrementalSpeaker.spoke_anything`：只读属性，core/routes/chat.py 判断是否已边生成边念时用
- `core/subject_facing_foreground.py`
  - `SubjectFacingForeground.is_completed`：对象判定，core/routes/chat.py 已持有该对象
- `core/system_orchestrator.py`
  - `SystemOrchestrator.register_hook`：启动编排的扩展点：插件要挂启动阶段钩子时用
- `core/target_device_validator.py`
  - `CanonicalValidationInput.from_legacy`：随 validate_target_device_from_canonical 一起：旧调用方数据 → 规范输入
- `core/unified/capability_resolver.py`
  - `CapabilityResolver.resolve_by_tag`：按标签查契约；随 CapabilityResolver 被按标签查询时用
- `core/unified/idempotency.py`
  - `IdempotencyStore.record_failed`：整个 IdempotencyStore 在生产里没有使用者（get_idempotency_store 只被 core/unified/__init__.py 再导出）；投递路径真接入幂等存储时，失败分支一并调它
- `core/unified/state_schema.py` — `TaskState.add_judge_record`、`TaskState.mark_verified`、`TaskState.resolve_failure`、`TaskState.set_goal`、`TaskState.set_phase`：TaskState 的 JudgeLoop 字段写入：core/task_lifecycle.py 已持有 TaskState，JudgeLoop 真跑起来时一起用
- `core/unified_action_lifecycle_surface.py`
  - `UnifiedActionLifecycleSurface.is_android_result_first_class`：对象上的判定方法，desktop_presence_runtime 拼出的那张面被读时用
  - `UnifiedActionLifecycleSurface.has_blocker`：对象上的判定方法，desktop_presence_runtime 拼出的那张面被读时用
  - `build_from_normalizer_outcome`：输入是 AndroidResultNormalizerOutcome：安卓结果那一侧，按所有者安排暂缓
- `core/vector_backend.py`
  - `_QdrantBackend.add_document_vector`：Qdrant 专用带向量索引，随 Node_105 知识库需要外部向量时用
- `core/voice_duplex_session.py`
  - `DuplexSession.next_event`：同步取事件的便利方法，异步迭代是规范用法
- `nodes/Node_116_ExternalToolWrapper/main.py`
  - `ExternalToolWrapper.register_custom_handler`：扩展点：随 execute_custom 一起
- `nodes/Node_71_MultiDeviceCoordination/main.py` — `Device.to_unified_model`、`Device.from_unified_model`：统一 DeviceModel 与节点 Device 的互转，随 Node_71 对接网关设备模型时用

</details>

<details><summary>产品决定（product）— 4 条</summary>

- `core/control_plane/swarm_scaler.py`
  - `SwarmScaler.autoscale`：core/master_brain.py 已持有 SwarmScaler 但没驱动；要蜂群自动扩缩就放在 master_brain 的周期循环里 —— 这是产品决定
- `core/device_orchestrator.py`
  - `DeviceOrchestrator.sync_clipboard`：跨设备剪贴板是产品功能：要不要做由所有者决定；做就挂 core/routes/devices.py
- `core/multi_llm_router.py`
  - `MultiLLMRouter.chat_cascade`：FrugalGPT 级联（便宜→贵升级）是否作为默认对话路径，由所有者定；定了就在 openclawd 对话入口切换
- `core/proxy_relay.py`
  - `ProxyRelay.relay_agent_manifest`：把 Agent 从一台设备迁到另一台 —— 依赖端侧执行沙盒（不可达模块 local_agent_runtime），要做就和它一起定

</details>

### 按子系统

| 子系统 | 条数 | 文件数 |
|---|---|---|
| `core/（其余单文件）` | 217 | 115 |
| `galaxy_gateway/` | 44 | 23 |
| `core/capability_*` | 22 | 8 |
| `core/android_*` | 20 | 13 |
| `core/delegated_*` | 20 | 5 |
| `core/cognitive/` | 19 | 8 |
| `core/mesh/` | 18 | 8 |
| `core/device_*` | 16 | 9 |
| `core/unified/` | 16 | 8 |
| `core/ugcp_*` | 15 | 3 |
| `nodes/Node_71_MultiDeviceCoordination/` | 15 | 7 |
| `core/node_*` | 14 | 6 |
| `core/task_*` | 11 | 6 |
| `core/attached_runtime_*` | 10 | 5 |
| `core/hybrid_*` | 10 | 2 |
| `core/model_topology/` | 10 | 5 |
| `core/canonical_*` | 8 | 3 |
| `core/v2_*` | 8 | 2 |
| `core/control_plane/` | 7 | 5 |
| `core/cross_*` | 7 | 3 |
| `core/execution_observability/` | 7 | 4 |
| `core/runtime/` | 7 | 2 |
| `core/continuation_*` | 6 | 1 |
| `core/desktop_*` | 6 | 2 |
| `core/flow_*` | 6 | 1 |
| `core/orchestration/` | 6 | 5 |
| `core/truth_*` | 6 | 3 |
| `core/governance/` | 5 | 2 |
| `core/runtime_*` | 5 | 3 |
| `nodes/Node_70_AutonomousLearning/` | 4 | 1 |
| `core/adapters/` | 3 | 3 |
| `core/continuum/` | 3 | 2 |
| `core/device_formation/` | 3 | 2 |
| `core/multimodal/` | 3 | 1 |
| `core/nodes/` | 3 | 1 |
| `core/presence/` | 3 | 2 |
| `core/session_*` | 3 | 2 |
| `launcher/` | 3 | 3 |
| `nodes/Node_112_SelfHealing/` | 3 | 1 |
| `nodes/Node_116_ExternalToolWrapper/` | 3 | 1 |
| `core/agent/` | 2 | 2 |
| `core/capability_runtime/` | 2 | 2 |
| `core/cross_device_policy/` | 2 | 1 |
| `core/perception/` | 2 | 1 |
| `core/resilience/` | 2 | 1 |
| `nodes/Node_05_Auth/` | 2 | 1 |
| `nodes/Node_109_ProactiveSensing/` | 2 | 1 |
| `nodes/Node_54_SymbolicMath/` | 2 | 1 |
| `nodes/Node_72_KnowledgeBase/` | 2 | 1 |
| `core/capabilities/` | 1 | 1 |
| `core/execution/` | 1 | 1 |
| `core/execution_*` | 1 | 1 |
| `core/generative_ui/` | 1 | 1 |
| `core/interaction/` | 1 | 1 |
| `core/operator_*` | 1 | 1 |
| `core/orchestration*` | 1 | 1 |
| `core/persona/` | 1 | 1 |
| `core/queueing/` | 1 | 1 |
| `core/reliability_contract/` | 1 | 1 |
| `core/routing_explanation/` | 1 | 1 |
| `nodes/Node_106_GitHubFlow/` | 1 | 1 |
| `nodes/Node_108_MetaCognition/` | 1 | 1 |
| `nodes/Node_14_FFmpeg/` | 1 | 1 |
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

<details><summary>节点服务里的方法 — 39 条</summary>

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
- `nodes/Node_112_SelfHealing/main.py`
  - `SelfHealingEngine.unregister_health_check` — — 注销健康检查
  - `SelfHealingEngine.register_recovery_handler` — — 注册恢复处理器
  - `SelfHealingEngine.run_once` T — 执行一轮自主自愈循环（Loop 1）：
- `nodes/Node_116_ExternalToolWrapper/main.py`
  - `ExternalToolWrapper.unregister_tool` — — 注销工具
  - `ExternalToolWrapper.register_custom_handler` — — 注册自定义处理器
  - `ExternalToolWrapper.execute_custom` — — 执行自定义工具
- `nodes/Node_14_FFmpeg/main.py`
  - `FFmpegManager.merge_videos` — — 合并视频
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

<details><summary>指标、可观测与审计记录 — 48 条</summary>

- `core/audit_event_semantics.py`
  - `audit_route_decision` T — Emit a ROUTE_DECISION audit record.
  - `audit_policy_decision` T — Emit a POLICY_DECISION audit record.
  - `audit_failure_domain` T — Emit a FAILURE_DOMAIN_IDENTIFIED audit record.
- `core/control_plane/audit_ledger.py`
  - `AuditLedger.verify_chain` T — 校验哈希链完整性。返回 ``{"intact": bool, "count": int, "broken_at": int\|None}``。
  - `AuditLedger.to_dag` T — Return the full ledger as a DAG adjacency list.
- `core/decision_diff_telemetry.py`
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
- `core/resilience/metrics.py`
  - `ResilienceMetrics.record_circuit_open` T — 无说明
  - `ResilienceMetrics.rejection_rate_per_minute` T — Rejections in the last 60 s (rolling window).
- `core/routing_explanation/live_decision.py`
  - `LiveRoutingDecisionBuilder.record_policy_band` — — Record the execution-policy band active at dispatch time.
- `core/routing_observability.py`
  - `ControlLoopMetrics.record_projection_mismatch` T — Increment the projection/control mismatch counter.
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

<details><summary>架构治理：权威声明、边界断言与自检 — 75 条</summary>

- `core/acl.py`
  - `AntiCorruptionLayer.validate_mcp_call` — — Validate MCP tool call request from LLM.
  - `AntiCorruptionLayer.validate_worker_registration` — — Validate worker registration on first connect.
- `core/canonical_ownership_truth_bridge.py`
  - `is_recovery_eligible` T — Return ``True`` when *ownership_boundary* allows canonical recovery admission.
  - `build_ownership_aware_replay_execution_record` T — Return a copy of *base_record* with ``participant_ownership_boundary`` populated.
- `core/capability_tier.py`
  - `list_capabilities_by_tier` T — Return all capability names registered under *tier*.
- `core/compat_fallback_authority_guard.py`
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
- `core/node_lifecycle_governor.py`
  - `node_governance_snapshot` T — Convenience wrapper — return a governor snapshot.
- `core/outward_runtime_truth.py`
  - `OutwardRuntimeTruthRuntime.snapshot_list` T — Return all buffered snapshots (oldest first).
  - `OutwardRuntimeTruthRuntime.compile_count` T — Total number of snapshots compiled since this runtime was created.
  - `classify_signal` T — Classify a runtime truth signal.
- `core/outward_truth_source_registry.py`
  - `enforce_surface_contract` — — Raise when a surface violates registry governance constraints.
- `core/repo_layout_registry.py`
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

<details><summary>多设备编组、协同网络与拓扑 — 47 条</summary>

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
- `core/network_topology_runtime.py`
  - `NetworkTopologyRuntime.update_edge_state` T — Update an edge's state (and optionally its preference flag).
  - `assimilate_nats_state` T — Absorb NATS fabric state into the singleton runtime.
  - `assimilate_gateway_state` T — Absorb gateway substrate state into the singleton runtime.
  - `assimilate_device_connectivity` T — Absorb a device connectivity report into the singleton runtime.
- `core/orchestration/global_arbiter.py`
  - `GlobalArbiter.suggest_device` T — Return the least-loaded candidate device based on current task origin
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

<details><summary>设备与节点：注册、发现、连接、通信、传输 — 77 条</summary>

- `core/adapters/ble_adapter.py`
  - `BLEAdapter.list_connected` — — 返回已连接的设备地址列表。
- `core/adapters/tailscale_p2p_adapter.py`
  - `TailscaleP2PAdapter.list_registered_devices` — — Return all registered device_id → ts_ip mappings.
- `core/adapters/tcp_adapter.py`
  - `TCPAdapter.connect_to_peer` — — 主动连接到 P2P 对等端。
- `core/aip_transport.py`
  - `AIPTransport.transport_stats` — — 可观测:导出链路统计(供面板/诊断查看选路反哺依据)。
  - `AIPTransport.unregister_adapter` — — 无说明
  - `AIPTransport.probe_best_transport` — — 探测到目标设备的最佳传输。
- `core/connection_manager.py`
  - `ConnectionManager.on_connected` — — 注册连接成功回调
  - `ConnectionManager.on_disconnected` — — 注册断开连接回调
- `core/device_agent_manager.py`
  - `DeviceAgentManager.register_agent_type` — — 注册新的设备 Agent 类型
  - `DeviceAgentManager.connect_all` — — 连接所有设备
- `core/device_communication.py`
  - `DeviceCommunication.list_connected_devices` T — 列出已连接的设备
  - `DeviceCommunication.on_device_message` — — 注册设备消息事件回调
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
  - `DeviceRegistry.project_to_contract` T — Project a registry-local record into the canonical ``RegisteredRuntimeDevice`` contract.
- `core/device_types.py`
  - `device_type_to_platform` T — 将简化 DeviceType 映射为 AIP DevicePlatform。
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
- `core/node_discovery.py`
  - `NodeDiscoveryService.on_node_joined` — — 注册节点加入回调
  - `NodeDiscoveryService.on_node_left` T — 注册节点离开回调
  - `NodeDiscoveryService.on_node_updated` — — 注册节点更新回调
  - `NodeDiscoveryService.deregister_node` — — 注销节点
  - `NodeDiscoveryService.seed_from_registry` T — 从 node_registry.json 预填充节点，无需等待 UDP 广播。
- `core/node_registry.py`
  - `NodeRegistry.register_node_class` — — 注册节点类（延迟实例化）
  - `NodeRegistry.start_health_monitor` T — 启动健康监控
  - `NodeRegistry.stop_health_monitor` — — 停止健康监控
  - `NodeRegistry.load_all_nodes` — — 加载所有节点，返回详细的加载报告
- `core/nodes/node_fabric_registry.py`
  - `NodeFabricRegistry.mark_offline_if_stale` T — 扫描所有节点，心跳超时的标记为 OFFLINE。返回被标记的节点 ID 列表。
  - `NodeFabricRegistry.list_by_capability` T — 返回具有指定能力的节点列表。
  - `NodeFabricRegistry.expire_stale_capabilities` T — 从 CapabilityRegistry 中移除来源为 "node" 且超过 TTL 的节点能力条目。
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
- `galaxy_gateway/device_router.py`
  - `DeviceRouter.aggregate_results` T — Aggregate multi-device task results into a unified summary.
- `galaxy_gateway/enhanced_nlu_v2.py`
  - `DeviceRegistry.find_device_by_name` — — 通过名称或别名查找设备
- `galaxy_gateway/gateway_nats_adapter.py`
  - `GatewayNATSAdapter.resolve_task` T — Resolve a pending task future with the device result.
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
  - `MultiDeviceOrchestrator.submit_multi_device_task` T — 提交多设备协同任务 — PR-2: 所有多设备任务强制经过 TaskGraph.
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
- `galaxy_gateway/wake_router.py`
  - `WakeRouter.set_decision_callback` — — 设置路由决策完成后的回调函数
- `galaxy_gateway/webrtc_proxy.py`
  - `order_ice_candidates` T — Sort and deduplicate an ICE candidate list by connectivity priority.
  - `clear_webrtc_task_session` — — Remove a WebRTC task session entry (idempotent).
- `galaxy_gateway/websocket_handler.py`
  - `handle_response` T — 处理任务/命令执行结果（接受 AIPMessage 对象）

</details>

<details><summary>能力、模型与执行路由 — 63 条</summary>

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
- `core/gateway_capability_default_enforcement.py`
  - `audit_gateway_override` T — Record an explicit capability gate override with a mandatory audit token.
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
- `core/modality_bridge.py`
  - `resolve_audio_in` T — 当前档位的听通路：native / asr_bridge。
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
  - `MultiLLMRouter.chat_cascade` T — L2 级联路由(任务感知的 FrugalGPT):按任务【实际复杂度】定起步档,再便宜→贵升级。
- `core/native_modal.py`
  - `is_native_active` T — 无说明
- `core/remote_execution_mode_resolver.py`
  - `ModeResolutionResult.as_remote_execution_mode` T — Return the resolved mode as a :class:`RemoteExecutionMode` enum.
- `core/runtime/execution_target_policy_engine.py`
  - `apply_failure_handling_policy` T — Apply the failure handling policy and return a
  - `apply_degraded_readiness_policy` T — Apply the degraded-readiness policy and return a
- `core/unified/capability_resolver.py`
  - `CapabilityResolver.resolve_by_tag` T — Return validated contracts whose tags include *tag*.
- `core/unified/llm_router.py`
  - `UnifiedLLMRouter.reload_policy` T — 重新加载路由策略文件（运行时热更新）。

</details>

<details><summary>智能体、认知与记忆 — 63 条</summary>

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
- `core/ai_intent.py`
  - `SemanticSearch.index_document` T — 索引文档（优先使用统一向量后端，降级到内置本地索引）
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
  - `DigitalTwinEngine.couple_all` — — 批量耦合所有孪生体
  - `DigitalTwinEngine.decouple_all` — — 批量解耦
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
- `core/openclawd_memory_backflow.py`
  - `store_result_envelope` T — Canonical PR-7 backflow entry point for :class:`ResultEnvelope` results.
- `core/orchestration/helpers.py`
  - `OrchestrationHelpers.emit_audit` T — Delegate to ``openclawd_instance._emit_audit()``.
- `core/orchestration/lifecycle.py`
  - `LifecycleManager.is_cancelled` T — Return True if *task_id* or *group_id* is in the cancel registry.
  - `LifecycleManager.finalise_plan` T — Thin delegation to _finalise_plan_lifecycle logic.
- `core/orchestration/planning.py`
  - `PlanningPipeline.determine_execution_path` T — Delegate to ``openclawd_instance._determine_execution_path()``.
- `core/orchestration/state.py`
  - `SessionMemoryManager.record_turn` T — Append a conversation turn to *session_id*'s history.
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

<details><summary>语音、桌面在场与感知 — 20 条</summary>

- `core/desktop_consumption_adapter.py`
  - `DesktopClientViewModel.readiness_label` T — Return a short human-readable readiness label for display.
- `core/desktop_presence_runtime.py`
  - `DesktopPresenceRuntime.snapshot_continuous_perception` T — PR-16: Return the latest continuous host perception snapshot.
  - `DesktopPresenceRuntime.permission_safety_summary` T — PR-32: Return a shell-facing permission/trust/safety summary.
  - `DesktopPresenceRuntime.set_operator_override` T — PR-33: Commit an :class:`~core.operator_override.OperatorOverrideSet` as the active override.
  - `DesktopPresenceRuntime.operator_override_summary` T — PR-33: Return a shell-facing summary of the active operator override state.
  - `DesktopPresenceRuntime.decision_timeline_replay` T — PR-34: Return a shell-facing replay of the decision timeline.
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
- `core/voice_duplex_session.py`
  - `DuplexSession.next_event` T — 取一条事件;超时返回 None。供不想用异步迭代的调用方。
- `core/voice_loop.py`
  - `VoiceLoop.process_once` — — 处理单次音频输入（非流式）。

</details>

<details><summary>配置、启动、安全、扩展与通用基础件 — 63 条</summary>

- `core/cache.py`
  - `CacheManager.set_json` — — 无说明
- `core/channel_plugins.py`
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
- `core/queueing/async_queue.py`
  - `AsyncTaskQueue.force_stop` — — Cancel all workers immediately without draining the queue.
- `core/reliability_contract/retry_policy.py`
  - `RetryPolicy.has_retries` T — Return ``True`` if this policy defines more than one attempt.
- `core/request_admission.py`
  - `admission_snapshot` T — 准入层的可观测快照，供诊断接口取用。
- `core/security_policy_loader.py`
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
- `core/tool_permissions.py`
  - `ToolPermissionChecker.add_policy` — — 动态添加策略
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
  - `ReleaseGate.list_flags` T — Return the current flag state (YAML + overrides merged).
- `core/unified/state_schema.py`
  - `TaskState.add_judge_record` — — Append a Judge decision to the history.
  - `TaskState.mark_verified` — — Mark an item as passed.
  - `TaskState.resolve_failure` — — Remove a failure point (on retry success).
  - `TaskState.set_goal` — — Set the user goal (Interpret step).
  - `TaskState.set_phase` — — Move to the next JudgeLoop phase.
- `launcher/bootstrap.py`
  - `SystemConfig.has_llm_api` T — 检查是否有可用的 LLM API
- `launcher/gateway.py`
  - `wait_for_gateway` T — 轮询到网关就绪，或超时。返回是否就绪。
- `launcher/nodes.py`
  - `equivalent_legacy_command` T — 给出这条新命令对应的**老**命令写法。

</details>

<!-- END GENERATED -->
