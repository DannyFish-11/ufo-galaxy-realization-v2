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
   〔2026-09-29 已接：`CommandRouter._is_high_risk_command` 是「内置高危词表 或 规则表要求确认」，表只能加确认；只因规则表命中的命令审批走 `check_and_intercept`。〕
2. **治理预算只能看，不管事。** 治理策略里的会话 / 每日 / 租户预算（超了 deny 或降级）由
   `BudgetEnforcer.enforce_pre_call` 执行，它零调用；用量也只有外部调 `POST /api/v1/governance/budget/record` 才记。
   模型路由自己的 `cost_budget` 只按单价给提供商重排，不是这套预算。
   〔2026-09-29 已接：`UnifiedLLMRouter` 调模型前问 `get_budget_enforcer()`（deny 策略在调用前拦下），调完按真实用量记账；治理端点读的是同一个执行器。〕
3. **系统资源表永远是空的。** OpenClawd 提供了列出 / 查询 / 设健康度的系统资源工具，
   投影编译器也在读 `get_system_resource_registry()`；但往表里登记资源的五个 `seed_*_resource` 零调用，没有任何地方登记。
   〔2026-09-29 已接：`core/startup.py` 第 9d 步 `seed_builtin_system_resources()` 登记 GitHub / 学术检索 / 工程循环 / 代码沙箱，设备随上下线由 `core/unified/presence_fanout.py` 登记并标可用 / 不可用；工程与资源两类能力同时进能力总线。〕
4. **操作者覆盖（PR-33）只有运行时一半。** `DesktopPresenceRuntime.set_operator_override` 与
   `operator_override_summary` 没有端点，也没有别的调用方 —— 覆盖设不进去，读覆盖的逻辑永远读到空。
5. **安全策略文件不热重载。** OpenClawd 只在初始化时 `load_security_policy()` 一次；
   `check_policy_file_changed` / `reload_security_policy` 零调用，改策略文件要重启才生效。
   〔2026-09-29 已接：`core/periodic_maintenance.py` 每 15 秒查一次，改了就重载（模型路由策略文件同样）。〕
6. **模型下载没有入口。** `HuggingFaceModelManager` 的下载 LLM / VLM / ASR / Embedding 与后台下载都没有端点；
   启动器缺模型时只打印一段 `python -c "..."` 让人手敲。

另有两处是**写了两份、在跑的是另一份**，归为「删掉」而不是「接上」：统一动作生命周期面的四个构造器
（`desktop_presence_runtime` 已就地从执行结果拼出同一张面）；`SecurityPolicy.is_category_allowed` / `is_scene_allowed`
（按设备类型判权，PR-SECURITY-V2 有意去掉了设备类型边界，现在所有设备同权、只看危险命令清单）。

<!-- BEGIN GENERATED: scripts/unwired_inventory.py --write -->

未接线公开能力 **382** 条，分布在 **205** 个文件。

| 维度 | 数 |
|---|---|
| 类方法 / 模块函数 | 225 / 157 |
| 只有测试在引用（写了、测了、没接） | 314 |
| 全仓连测试都没引用 | 68 |
| 所在模块本身从入口不可达 | 4 |

### 按名字表明的角色

| 角色 | 合计 | 其中只有测试引用 | 其中连测试都没有 |
|---|---|---|---|
| 测试复位钩子 | 7 | 7 | 0 |
| 序列化/转换 | 19 | 13 | 6 |
| 事件回调 | 4 | 4 | 0 |
| 判定谓词 | 78 | 70 | 8 |
| 只读查询 | 49 | 44 | 5 |
| 计算/构造 | 69 | 65 | 4 |
| 动作/变更 | 156 | 111 | 45 |

### 按用途

| 用途 | 条数 | 其中只有测试引用 | 其中连测试都没有 | 文件数 |
|---|---|---|---|---|
| 节点服务里的方法 | 15 | 0 | 15 | 7 |
| 安卓协作的契约、治理与对账层 | 83 | 76 | 7 | 40 |
| 持久化、重启恢复与断点续跑 | 27 | 27 | 0 | 8 |
| 指标、可观测与审计记录 | 9 | 9 | 0 | 9 |
| 架构治理：权威声明、边界断言与自检 | 56 | 55 | 1 | 25 |
| 多设备编组、协同网络与拓扑 | 30 | 24 | 6 | 19 |
| 设备与节点：注册、发现、连接、通信、传输 | 50 | 28 | 22 | 24 |
| 能力、模型与执行路由 | 31 | 26 | 5 | 22 |
| 智能体、认知与记忆 | 38 | 32 | 6 | 25 |
| 语音、桌面在场与感知 | 11 | 11 | 0 | 8 |
| 配置、启动、安全、扩展与通用基础件 | 32 | 26 | 6 | 18 |

### 每个函数放在哪里（安卓部分按所有者安排暂缓，不在其列）

逐条核对的结果在 `config/unwired_placement.json`。这是**去处**，不是已执行的处置：删与接都等所有者定。

| 去处 | 条数 | 意思 |
|---|---|---|
| 接上（`wire`） | 27 | 该有人调它：写明调用点（文件、第几行附近、在做什么的时候） |
| 挂出来（`surface`） | 0 | 该有人读它：写明挂到哪个端点 / 面板 / 诊断输出 |
| 删掉（`delete`） | 148 | 已被别的实现取代或根本没有用途：写明被什么取代 |
| 随对象走（`object`） | 121 | 对象上的判定 / 查询 / 扩展点：对象被用到那一处时自然会用，单独接没有意义 |
| 测试钩子（`testhook`） | 0 | 只为测试或断言存在（复位、注入、不变量断言），不该进生产路径 |
| 框架回调（`framework`） | 0 | 由第三方框架按名字回调（zeroconf、asyncio），清单误报 |
| 产品决定（`product`） | 3 | 接不接是功能取舍，不是技术问题：等所有者定 |
| 合计 | 299 | |

按用途 × 去处：

| 用途 | 接上 | 挂出来 | 删掉 | 随对象走 | 测试钩子 | 框架回调 | 产品决定 | 合计 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 节点服务里的方法 | 5 | 0 | 3 | 7 | 0 | 0 | 0 | 15 |
| 持久化、重启恢复与断点续跑 | 12 | 0 | 11 | 4 | 0 | 0 | 0 | 27 |
| 指标、可观测与审计记录 | 0 | 0 | 3 | 6 | 0 | 0 | 0 | 9 |
| 架构治理：权威声明、边界断言与自检 | 0 | 0 | 42 | 14 | 0 | 0 | 0 | 56 |
| 多设备编组、协同网络与拓扑 | 4 | 0 | 11 | 13 | 0 | 0 | 2 | 30 |
| 设备与节点：注册、发现、连接、通信、传输 | 6 | 0 | 27 | 16 | 0 | 0 | 1 | 50 |
| 能力、模型与执行路由 | 0 | 0 | 12 | 19 | 0 | 0 | 0 | 31 |
| 智能体、认知与记忆 | 0 | 0 | 14 | 24 | 0 | 0 | 0 | 38 |
| 语音、桌面在场与感知 | 0 | 0 | 5 | 6 | 0 | 0 | 0 | 11 |
| 配置、启动、安全、扩展与通用基础件 | 0 | 0 | 20 | 12 | 0 | 0 | 0 | 32 |

<details><summary>接上（wire）— 27 条</summary>

- `core/cross_device_sync.py`
  - `push_task_state_to_device`：安卓相关（推任务状态到手机），先放着；非安卓参与方要这个能力时，放在 core/participant_admission.py 的任务状态更新处
- `core/delegated_flow_decision_history.py`
  - `record_delegated_flow_event`：安卓委托流状态变化处（安卓相关，按你的意思先放着）
- `core/delegated_flow_recovery_coordinator.py` — `decide_recovery`、`decide_recovery_from_continuity_artifact`、`begin_recovery_attempt`、`complete_recovery_attempt`、`suppress_recovery_attempt`：安卓设备带着在途委托流重连时（galaxy_gateway/android/handlers/registration.py 的重连分支）：先 decide_recovery，再 begin / complete。整个协调器在生产里没有驱动方；安卓相关，按你的意思先放着
- `core/flow_continuity_coordinator.py` — `coordinate_attach`、`coordinate_reattach_process_recreation`、`coordinate_stale_identity`、`coordinate_duplicate_signal`、`coordinate_partial_result`、`coordinate_v2_restart_recovery`：安卓附着 / 重附着 / 重复信号 / 部分结果 / 重启恢复各自的处理点（galaxy_gateway/android/handlers/*）。便捷包装，底下的协调器方法才是本体；安卓相关，先放着
- `core/mesh/live_mesh_session_coordinator.py`
  - `LiveMeshSessionCoordinator.on_android_participant_signal`：安卓 Mesh 参与信号的入口，安卓相关，先放着
- `core/node_protocol.py` — `MessageRouter.send_request`、`ProtocolAdapter.to_android_format`、`ProtocolAdapter.from_android_format`、`ProtocolAdapter.to_websocket_format`、`ProtocolAdapter.from_websocket_format`：安卓 / WebSocket 旧格式互转与节点请求，安卓相关，按所有者的意思先放着；误删后已恢复
- `core/swarm_coordinator.py` — `SwarmCoordinator.build_execution_plan_for_orchestration`、`SwarmCoordinator.device_candidates_from_canonical`：随产品项 6（智能体清单下发的服务端一半）一起接：SwarmCoordinator.dispatch_team 是把智能体清单派到设备的编排入口，网关只把它挂在 app.state 上、没有调用方；device_candidates_from_canonical 补上「没给候选设备时从规范设备表取」
- `galaxy_gateway/ssot.py`
  - `udm_write_upsert`：安卓相关，先放着：唯一合适的调用点是 galaxy_gateway/android_bridge.py 的 _patch_runtime_state_to_udm（现在直连 UDM）；device_router 的同类写法被测试按 _get_udm 桩住
- `nodes/Node_33_ADB/cluster_manager.py`
  - `ADBClusterManager.parallel_execute`：安卓侧（ADB 多台手机并行执行），按所有者的意思先放着；误删后已恢复
- `nodes/Node_70_AutonomousLearning/core/autonomous_learning_engine.py` — `AutonomousLearningEngine.generalize_skill`、`AutonomousLearningEngine.find_similar_skills`、`AutonomousLearningEngine.process_observation`、`AutonomousLearningEngine.update_experience_outcome`：观察 → 泛化技能 → 生成 ADB 命令的学习流程，安卓相关，先放着。注意这份引擎副本目前没有任何进程加载（节点在跑的是 main.py 里的引擎）；误删后已恢复

</details>

<details><summary>删掉（delete）— 148 条</summary>

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
- `core/capability_network_runtime_policy.py`
  - `absorb_capability_change_event`：能力变化各来源早已直接写同化层：设备经 UDM 注册 / upsert，MCP / 技能 / 节点经 core/agent/capability_registry 的投影；再从这里写一份会用另一套 node_id 与种类覆盖掉已有记录
- `core/cognitive/cognitive_activation_budget.py`
  - `apply_candidate_narrowing`：现行决策点里没有一份可收窄的「候选节点清单」：策略选择只在 single/parallel/… 之间选，预算已经经 get_planner_breadth_guidance 作用在广度上；设备选择 _select_target_from_candidates 只取最高分一台（按列表顺序先截断只会丢掉可能更好的候选）；staged_mesh 的参与方是 mesh 会话计划好的，截掉会让 barrier 等不到人。有测试引用，删除待授权
- `core/cognitive/cognitive_field_engine.py` — `CognitiveFieldEngine.add_tick_listener`、`CognitiveFieldEngine.remove_tick_listener`：add/remove_tick_listener：每个 tick 已经发 cognitive.tick 事件（_emit_cognitive_event），想跟 tick 的走事件总线；桌面存在面按需读快照（desktop_existence_surface 读 tick_count / is_running），不需要推送。这是第二条重复的通知通道。有测试引用，删除待授权
- `core/command_router.py`
  - `CommandRouter.normalize_legacy_ingress`：非信封载荷已在各入口（android_bridge、app.py）各自转信封；这是第二套归一化
- `core/compat_fallback_authority_guard.py`
  - `block_compat_influence_at_decision_site`：登记册里的兼容影响点在生产里没有一个决策点调用 PR-9 的检查（check_canonical_authority_at_decision_site 只被本模块自己调）；门写好了、门后没有路
- `core/concurrency_manager.py`
  - `LockManager.release_all`：ConcurrencyManager 的锁在生产里没有获取方（run_with_lock 无调用），也就没有「持有者结束时释放全部锁」这个时刻。有测试引用，删除待授权
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
- `core/dag_evolver.py`
  - `DAGEvolver.on_missing_capability`：插入的 acquire_capability 节点没有执行方（全仓无此 action 的处理器），接上只会让下游任务被一个必败的前置节点卡死；真实的能力缺口处理在 MCPDynamicGateway.handle_capability_gap（MasterBrain 调，生成 → ACL → 沙箱 → 装载）。有测试引用，删除待授权
- `core/decision_diff_telemetry.py`
  - `record_candidate_diff`：迁移期的新旧选路差异遥测（模块自标 legacy）。唯一还在用的是 entrypoint_router 的 record_entry_mode_diff；跨设备候选选择已只剩新路径，没有「旧的」可比
- `core/delegated_flow_persistence.py` — `persist_session_snapshot`、`restore_sessions`、`persist_contract_snapshot`、`restore_contracts`、`persist_binding_snapshot`、`restore_bindings`、`persist_flow_entity_snapshot`：与 DelegatedFlowPersistenceBundle.persist_all / restore_all 逐项重复：周期落盘走 persist_all（core/periodic_maintenance.py），读回走 restore_all 与 rehydrate_flow_entity_runtime；有测试引用，删除待授权
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
- `core/failure_domains.py`
  - `map_to_pr_b_domain`：对外的失败域（CanonicalTask、operator 面）用的是 canonical_task.FailureDomain 另一套词表；core.failure_domains 的细分域只进本模块的记录，没有要消费 PR-B 归并结果的读取方。有测试引用，删除待授权
- `core/focus_stack.py`
  - `FocusStack.drop_current`：模块设计边界写明「不自动结束焦点」（容量 + 陈旧淘汰收口，焦点栈是工作记忆不是任务清单）；没有「用户显式结束一件事」的判定点，这个方法没有该被调用的时刻。有测试引用，删除待授权
- `core/galaxy_main_loop_l4_enhanced.py`
  - `GalaxyMainLoopL4.receive_goal`：launcher/services.py 第 2297 行注释已查明：主启动链不拉它，真正的自主性由 ambient_attention_loop → OpenClawd 承担
- `core/gateway_capability_default_enforcement.py`
  - `audit_gateway_override`：网关能力门禁没有任何「显式绕过」分支（device_selection 里不存在 override），审计一个不存在的动作；需要时 capability_enforcement_hardener.audit_capability_override 是同一件事的另一份
- `core/generative_ui/runtime.py`
  - `GenerativeUIRuntime.render_surface_dict`：to_dict 的便利包装
- `core/governance_validation_gate.py`
  - `evaluate_governance_validation`：模块级便利函数；调用方都直接用类
- `core/grounded_planner.py`
  - `to_task_assign`：core/routes/ui_act.py 的设计是本机经仲裁器执行，跨设备明确拒绝并指向 agent_deploy + agent_execute；把规划动作以 TASK_ASSIGN 直接下发设备正是它刻意不走的路。有测试引用，删除待授权
- `core/hybrid_orchestration_continuity.py` — `load_hybrid_execution`、`recover_hybrid_executions`：run_startup_recovery 第 4 步已直接用 store 读回；这个便捷包装是重复入口
- `core/mainline_convergence.py` — `MainlineMetadataFrame.is_mainline`、`MainlineExecutionTrace.visits_openclawd`、`MainlineExecutionTrace.visits_capability_dispatch`、`MainlineExecutionTrace.visits_knowledge`、`MainlineConvergenceRegistry.record_from_response`、`MainlineConvergenceRegistry.list_by_path_class`、`MainlineConvergenceRegistry.assert_mainline_dominant`、`reset_mainline_convergence_registry`、`record_mainline_execution`：legacy 的主线收敛登记；openclawd 只读了 trace 的三个属性，登记 / 断言侧无人调用
- `core/mcp_addon_contract.py`
  - `is_valid_mcp_addon_contract`：validate_mcp_addon_contract 的布尔包装
- `core/mesh/device_role_allocator.py`
  - `DeviceRoleAllocator.register_capability_rule`：只服务于 allocate_all 的第三套能力→角色映射（见上）。有测试引用，删除待授权
  - `DeviceRoleAllocator.allocate_all`：角色在接入时就分好了：通用参与方走 core/participant_admission.py 的 body_mesh_roles，安卓走 registration / capability_report 的位掩码映射，两处都直接写 BodyMeshRegistry 并进 Mesh 自动编组。allocate_all 会拿 UDM 全部设备以 session_id=None 重登记、覆盖掉编组的会话归属，是第三套并行的能力→角色映射。有测试引用，删除待授权
- `core/mesh/mesh_session_coordinator.py` — `MeshSessionCoordinator.update_with_dispatch_result`、`MeshSessionCoordinator.update_with_takeover_result`、`MeshSessionCoordinator.update_with_merged_result`：MeshSessionCoordinator 类是模块函数 coordinate_mesh_session 的无状态重复包装：实跑的 staged_mesh 路径（core/runtime/source_dispatch_orchestrator.py）用 coordinate_mesh_session 建状态、由 core/mesh/live_mesh_runtime_engine.run_live_mesh_session 推进参与方结果与合并；这个类全仓没有实例化。有测试引用，删除待授权
- `core/message_interop.py`
  - `normalize_to_result_envelope`：legacy 结果归一；ResultEnvelope 已在各入口直接构造
- `core/modality_bridge.py`
  - `resolve_audio_in`：ambient_attention_loop 的注释记录了它原先的短路用法已被撤掉；判定在 core/modality_capability 里
- `core/model_topology/config_bridge.py`
  - `ConfigBridge.build_inventory`：legacy：从 dashboard 时代输入建库存；dashboard 已退役
- `core/model_topology/topology_router.py`
  - `TopologyRouter.route_all_phases`：legacy：投影用单相 route()，三相一起算无人调用
- `core/multi_device_control_integrity.py` — `MultiDeviceIntegritySnapshot.gaps_by_area`、`build_entry_unification_record`：legacy 多设备完整性审计的构造器 / 查询
- `core/multi_llm_router.py`
  - `MultiLLMRouter.chat_cascade`：所有者决定：第 2/3/4 项不做，对应函数删除（有测试引用，删除待授权）
- `core/multimodal/perception_source_registry.py`
  - `PerceptionSourceRegistry.update_quality`：同上：没有按注册表 source_id 测到时延 / 质量的摄入点，回写的数没有来源。有测试引用，删除待授权
  - `PerceptionSourceRegistry.degraded_sources`：注册表里登记的麦克风/摄像头是 sounddevice / aiortc 本机设备，而实际进 bus 的帧来自桌面覆盖层 DesktopPerceptionStore，两者不是同一个源，没有按 source_id 回写的摄入点；恢复周期（SourceRecoveryPolicy.run_recovery_cycle）只看主源。有测试引用，删除待授权
- `core/native_modal.py`
  - `is_native_active`：modality_bridge 按档位自己判定；布尔包装无人用
- `core/nats_bus.py`
  - `NATSBus.publish_legacy_task_result`：[Legacy] 旧 TaskResult 发布；AIP v3 TASK_RESULT 是规范路径
  - `NATSBus.publish_task_event`：与 AIP v3 发布器重复：galaxy.task.* 平面载的是 AIP v3 消息（派发 / 结果早有发布器且都在调用），往这里再发一种 Unified*Event 形状会让订阅方收到两种格式；没有任何订阅方等这一种
  - `NATSBus.publish_device_event`：与 AIP v3 发布器重复：galaxy.device.* / galaxy.capability.* 平面载的是 AIP v3 消息（注册 / 心跳 / 能力上报早有发布器且都在调用），往这里再发一种 Unified*Event 形状会让订阅方收到两种格式；没有任何订阅方等这一种
  - `NATSBus.publish_capability_event`：与 AIP v3 发布器重复：galaxy.device.* / galaxy.capability.* 平面载的是 AIP v3 消息（注册 / 心跳 / 能力上报早有发布器且都在调用），往这里再发一种 Unified*Event 形状会让订阅方收到两种格式；没有任何订阅方等这一种
- `core/network_topology_runtime.py`
  - `assimilate_nats_state`：与 core/capability_network_runtime_policy 的 absorb_* 重复（absorb_* 直接调运行时同名方法，NATS / 网关两处早已接上）；本包装没有独立用途
  - `assimilate_gateway_state`：与 core/capability_network_runtime_policy 的 absorb_* 重复（absorb_* 直接调运行时同名方法，NATS / 网关两处早已接上）；本包装没有独立用途
  - `assimilate_device_connectivity`：与 core/capability_network_runtime_policy 的 absorb_* 重复（absorb_* 直接调运行时同名方法，NATS / 网关两处早已接上）；本包装没有独立用途；设备连接状态已由 UDM 在线翻转经 absorb_device_presence_event 写入
- `core/node_discovery.py`
  - `NodeDiscoveryService.seed_from_registry`：从 node_registry.json 预填充；实际启动走 core/node_discovery_runtime.seed_fabric_nodes_into_discovery（从 NodeFabricRegistry 种），这条被取代
- `core/node_lifecycle_governor.py`
  - `node_governance_snapshot`：legacy 的便利包装
- `core/openclawd_memory_backflow.py`
  - `store_result_envelope`：结果收口处 core/cross_device_result_surface 已自己建 ResultEnvelope 并 record_chain_execution；记忆回流由 store_task_result 在 openclawd / 安卓 task_result 处写。这里把两件事又做一遍，接上会重复登记链路记录。有测试引用，删除待授权
- `core/orchestration/global_arbiter.py`
  - `GlobalArbiter.suggest_device`：仲裁器登记运行中任务时不带 device_id（request_admission.admit 的 metadata 里没有），负载计数恒为 0、建议恒等于第一个候选；准入这一层也还没有候选设备列表。有测试引用，删除待授权
- `core/orchestration/helpers.py`
  - `OrchestrationHelpers.emit_audit`：PR-7 拆 openclawd 留下的门面，全部委托回 openclawd 私有方法且无人调用；真要拆 openclawd 是另一件大事
- `core/orchestration/planning.py`
  - `PlanningPipeline.determine_execution_path`：PR-7 拆 openclawd 留下的门面，全部委托回 openclawd 私有方法且无人调用；真要拆 openclawd 是另一件大事
- `core/orchestration_review_surface.py`
  - `increment_legacy_dispatch_counter`：已被网关的 galaxy_legacy_dispatch_total 指标（galaxy_gateway/observability.py，含告警规则）取代，两套计数重复
- `core/outward_runtime_truth.py` — `OutwardRuntimeTruthRuntime.snapshot_list`、`OutwardRuntimeTruthRuntime.compile_count`、`classify_signal`：legacy：对外真相由 core/routes/projection.py 的编译器产出，这几个分类 / 计数无人读
- `core/perception/desktop_perception_store.py`
  - `DesktopPerceptionStore.has_fresh_frame`：采集桥（ingest_runtime._desktop_perception_bridge_loop）取帧用 snapshot_media，它本身只返回新鲜帧、隐私暂停时全空 —— 这道门已经在那儿了。有测试引用，删除待授权
- `core/phase_contract.py`
  - `tri_state_of`：四相→三态的投影由 core.continuum.types.continuum_to_tri_state 负责（runtime_domain_resolver 等在用）；全仓没有手写的字符串映射可替换。有测试引用，删除待授权
- `core/repo_layout_registry.py` — `is_active_desktop_status_directory`、`build_repo_layout_summary`：legacy、零导入
- `core/runtime_invariant_enforcement.py` — `check_invariant`、`check_cross_repo_assumption`：零导入；不变量检查已由 scripts/check_* 守卫承担
- `core/scheduling_truth_harness.py` — `query_routable_executors_for_task`、`assert_scheduling_truth_convergence`：便利包装；query_routable_executors 已被 device_pool_manager 直接调用
- `core/skill_package_contract.py`
  - `is_valid_skill_package_contract`：validate_* 的布尔包装
- `core/system_mode.py`
  - `FabricConfig.is_desktop_local`：legacy；桌面本地判定由 core/presence_line.py 负责
- `core/target_device_validator.py`
  - `validate_target_device_from_canonical`：validate_target_device 的薄包装，只多盖一个来源标签；四个调用方（command_router ×2、网关 chat、device_selection）都直接用同样三个参数调 validate_target_device。有测试引用，删除待授权
- `core/task_graph_runtime.py`
  - `result_envelope_to_node_update`：被 TaskGraphRuntime.complete_from_result_envelope 取代：后者按 RESULT→COMPLETED/FAILED 走 transition 留记录（command_router / cross_device_result_surface 在用）；本函数就地改节点、不留迁移记录。有测试引用，删除待授权
- `core/task_lifecycle.py`
  - `TaskLifecycleManager.run_with_lifecycle`：mark_running / mark_done / mark_failed 的便捷包装；command_router 的标记散在 route_envelope 的不同分支（running 与 failed 在不同位置、done 在结果收口处），不是一个能整体包起来的协程。有测试引用，删除待授权
- `core/task_result_canonical_truth_chain.py`
  - `IncompleteResultLedger.all_incomplete`：账本原始视图；对外读面已是本轮的 GET /api/v1/results/isolated（只出类型化字段）
- `core/truth_conflict_enforcement.py` — `assert_canonical_write_precedes_compat_write`、`assert_no_parallel_write_authority`、`check_compat_write_is_mirror_only`、`is_truth_convergence_healthy`：legacy、零导入
- `core/truth_integration_layer.py`
  - `is_device_available_canonical`：resolve_device_truth(...).is_available 的一行包装；选设备的各调用方已各自按在线过滤，塞进 select_best_device 会把 UDM 里查不到的候选一律否决（池子的判据是「UDM 明确说不行才不行」）
- `core/ui_surface_authority.py` — `is_legacy_surface`、`is_projection_driven_surface`：legacy、零导入
- `core/unified/error_mapper.py` — `ErrorMapper.from_legacy_gateway_error`、`ErrorMapper.from_legacy_device_error`、`ErrorMapper.from_legacy_executor_error`：legacy 错误串映射；新错误已按规范载荷产出
- `core/unified_action_lifecycle_surface.py` — `build_from_dispatch`、`apply_blocker`、`apply_confirmation`、`close_surface`：core/desktop_presence_runtime.py 第 1515–1594 行已从执行结果就地拼出这张面（阶段、阻断、确认、收口全在），在跑的是那一份；这几个构造器是重复实现
- `core/unified_dispatch_readiness_gate.py`
  - `reset_dispatch_readiness_gate`：空操作，docstring 自称只为 API 对称
- `core/unified_execution_governance.py`
  - `resolve_execution_conflict`：resolve_execution_conflict：evaluate_execution_governance 已在同一张 _EXECUTION_TYPE_PRIORITY 表上做冲突裁决（安卓 goal_execution 与 source_dispatch_orchestrator 在用），这是同一规则的第二份计算。有测试引用，删除待授权
- `galaxy_gateway/agent_bridge.py`
  - `AgentBridge.handoff_from_envelope`：device_router 的跨设备分支手里没有 TaskEnvelope（只有 command / analysis / ctx），契约的 task 形状也不同（command+analysis+context vs tool_name+args）—— 换成它会丢掉 analysis 与上下文；全仓没有持 TaskEnvelope 去做 agent 交接的调用点。有测试引用，删除待授权（handoff_contract_from_envelope 随之一起）
  - `AgentBridge.build_envelope_v2`：旧 HandoffContract → Envelope v2 的转换；只被 legacy_paths 登记引用
- `galaxy_gateway/cross_device_switch.py`
  - `guard_cross_device`：抛异常版的开关检查；所有跨设备入口（device_router 两处、agent_bridge、webrtc_proxy）都用返回 dict 的 make_disabled_response 写法，没有需要抛异常的调用方
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
- `launcher/bootstrap.py`
  - `SystemConfig.has_llm_api`：「有没有可用 LLM Key」的判据在 launcher/env_check.py（api_keys_configured，doctor 复用的正是它）；这是第二份判据。有测试引用，删除待授权
- `launcher/gateway.py`
  - `wait_for_gateway`：模块零导入；launcher/services.py 起网关时自己轮询
- `nodes/Node_71_MultiDeviceCoordination/models/task.py` — `Task.update_progress`、`TaskQueue.dequeue`、`TaskQueue.is_empty`：Task.update_progress / TaskQueue.dequeue / TaskQueue.is_empty：调度器（core/task_scheduler.py）按优先级 + 依赖从 TaskQueue.snapshot() 挑任务再 remove，不走 FIFO 出队；进度在 _complete_task 直接置 1.0，调度器不追踪子任务完成数，没有要逐个更新进度的地方。有测试引用（本节点 tests/test_models.py），删除待授权

</details>

<details><summary>随对象走（object）— 121 条</summary>

- `core/adapters/tcp_adapter.py`
  - `TCPAdapter.connect_to_peer`：send() 已按需临时建连；长连接没有读循环，主动连局域网里所有 _galaxy 广播方也不是该默认做的事
- `core/agent/policy_loader.py`
  - `reload_policies`：策略文件缓存本身带 60 秒 TTL，改了会自己读到；进程里没有任何地方写这几个 .md，显式重载只给手工改文件后想立即生效的人用
- `core/agent_manifest.py`
  - `AgentManifest.create_multi_step_agent`：随 core/routes/nodes.py 创建 Agent 的端点：需要多步顺序 Agent 时从那里调
- `core/agent_team.py` — `AgentTeam.couple_member`、`AgentTeam.decouple_member`：耦合模式切换随团队对象：core/control_plane/swarm_scaler.py 扩缩容时用
- `core/aip_transport.py`
  - `AIPTransport.unregister_adapter`：注册 / 注销成对的适配器 API；关停走 close_all()，没有「运行中卸下某个传输」的场景
- `core/canonical_ownership_truth_bridge.py` — `is_recovery_eligible`、`build_ownership_aware_replay_execution_record`：唯一导入方是 core/android_participant_truth_ingress.py：安卓参与方真相那一侧，按所有者安排暂缓
- `core/capability_assimilation.py`
  - `CapabilityAssimilationLayer.mark_stale_if_expired`：按心跳年龄判 STALE 需要真实的心跳来源：本机 MCP / 技能提供方、启动器节点从不往同化层发心跳，直接按时扫会在 60 秒后把它们全判 STALE（query_routable_executors 只认 ONLINE，路由随之失效）。设备的离线已经经 UDM 的在线翻转写进同化层（core/unified/presence_fanout.py）。等这些提供方有了心跳再挂进 core/periodic_maintenance.py
- `core/capability_bus.py`
  - `CapabilityBusRole.from_tool_name`：随下面的 register_* 一起：登记时按工具名推断角色
- `core/capability_graph_selection.py`
  - `explain_selection`：选路解释的人话生成器，操作者检查端点目前只给结构化选路结果；要人话时由调用方直接调它（有测试钉住输出）
- `core/capability_network_bridge.py`
  - `explain_joint_selection`：同 explain_selection：联合选路的人话解释，对象方法，按需调用
- `core/capability_network_runtime_policy.py`
  - `query_capable_device_executors`：与已接线的 query_routable_executors（device_pool_manager 在用）重复的窄化版；要么删，要么在需要「只要设备型执行者」的地方替换调用
- `core/capability_runtime/capability_constraint.py`
  - `CapabilityConstraintFlags.has_any_constraint`：值对象上的判断方法，随 capability_runtime 这一对象被消费时一起用
- `core/capability_runtime/capability_preference.py`
  - `CapabilityPreference.has_preference`：值对象上的判断方法，随 capability_runtime 这一对象被消费时一起用
- `core/cognitive/cognitive_activation_budget.py` — `ActivationBudget.is_narrow`、`ActivationBudget.is_moderate`、`ActivationBudget.is_broad`：值对象判定方法，随 kernel/execution_planner 读预算时用
- `core/cognitive/cognitive_execution_policy.py` — `CognitiveExecutionHint.is_manifest`、`CognitiveExecutionHint.is_liminal`、`CognitiveExecutionHint.is_passive`：值对象判定方法（is_liminal / is_manifest / is_passive），调用方目前直接比枚举
- `core/cognitive/liminal_dynamics.py`
  - `LiminalDynamics.can_transition_to_manifest`：can_transition_to_manifest 刻意不接，理由与实测写在 core/cognitive/state_interpreter.py::_apply_hysteresis 的 docstring：驻留闸在转移那一刻分不出「越界后会掉回来」和「越界是对的」，会把分数稳定高的请求一起压成 planning/0.6。阈值调整与转移记账两半已接；驻留闸的取值域留在配置 cognitive_liminal_min_dwell_s，等有能区分两种情形的判据再开
- `core/cognitive/long_term_memory.py`
  - `LongTermMemory.retrieve_entry`：单条取回，随长期记忆被按 id 读取时用
- `core/cognitive/memory_bias_layer.py` — `MemoryBias.is_continuity`、`MemoryBias.is_retrieval`、`MemoryBias.is_novelty`：值对象判定方法，随 execution_planner 消费偏置时用
- `core/cognitive/state_interpreter.py` — `StateInterpreter.interpret_snapshot`、`StateInterpreter.last_region`：解释器的只读方法，随 cognitive_execution_policy 读状态时用
- `core/compat_legacy_path_blocking_canonicalization.py`
  - `CompatLegacyBlockingRecord.is_quarantined`：legacy 记录上的判定方法，随 block_compat_influence_at_decision_site 一起
- `core/concurrency_manager.py` — `ConcurrencyManager.run_with_concurrency`、`ConcurrencyManager.run_with_lock`：API 形状的便利方法；调用方都直接用信号量/锁。有新调用需求时才用，否则删
- `core/config_service.py`
  - `ConfigService.is_provider_ready`：随 describe_missing 一起用
- `core/continuum/return_engine.py`
  - `ReturnEngine.force_return`：强制回到静默由 PresenceDirector / 操作者覆盖（PUT /api/v1/operator/override）承担；ReturnEngine 自己的这个入口留作对象方法
- `core/continuum/temporal_engine.py` — `DwellGuard.remaining_ms`、`TemporalEngine.smoothed_signals`：只读快照 / 剩余驻留时长，随 continuum orchestrator 投影时用
- `core/control_plane/swarm_manifest.py`
  - `SwarmAgentManifest.to_agent_execute_payload`：清单对象的转换；core/swarm_coordinator.py 派发蜂群任务时用（它已持有这个对象）
- `core/control_plane/swarm_scaler.py`
  - `SwarmScaler.managed_workers`：随 autoscale 一起
- `core/cross_device_policy/routing_policy.py` — `RoutingPolicy.source_assignment`、`RoutingPolicy.devices_with_role`：策略对象自带查询；读 RoutingPolicy 的地方（model_topology、routing_explanation）按需调用
- `core/degraded_operation_envelope.py`
  - `envelope_summary`：降级信封的紧凑摘要，openclawd 构造信封后按需调用；投影端点已直接给出完整信封
- `core/delegated_flow_decision_history.py` — `HistoryEvidenceStatus.allows_runtime_closure`、`HistoryEvidenceStatus.is_definitive_gap`：证据状态自带判定；读这份历史的验收面（system_final_acceptance_verdict 等）按需调用
- `core/device_agent_manager.py`
  - `DeviceAgentManager.register_agent_type`：扩展点：新的设备 Agent 类型需要时由插件/启动配置调用；目前没有第二种类型，留着不接
  - `DeviceAgentManager.connect_all`：launcher/core_services.py 刚建出来的实例里没有任何 Agent，在那里调是空操作；设备 Agent 在 register_device 时各自连接，这是「全部重连」的备用 API
- `core/device_formation/formation_runtime_coordinator.py`
  - `FormationParticipantStatus.is_viable`：参与者状态自带判定；编组调度选参与者时用
- `core/device_orchestrator.py`
  - `DeviceOrchestrator.parallel_commands`：已被 POST /api/v1/devices/parallel 取代：那条路走 CommandRouter.route_envelope() 规范入口；这个方法直发各设备、绕过规范准入，不再挂出来
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
- `core/huggingface_model_manager.py` — `HuggingFaceModelManager.download_llm`、`HuggingFaceModelManager.download_vlm`、`HuggingFaceModelManager.download_asr`、`HuggingFaceModelManager.download_embedding`：按类别的便捷下载，带默认模型（ASR 默认 faster-whisper-medium、向量默认 bge-large-zh-v1.5）；所有者复核后保留。HTTP 下载接口 POST /api/v1/models/download 走同一个 download()，经 download_background 带进度与去重
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
- `core/nodes/node_fabric_registry.py`
  - `NodeFabricRegistry.mark_offline_if_stale`：启动器拉起的节点存活由进程 / HTTP 健康判（launcher/node_startup.py 进程退出时写 offline），从不往 NodeFabricRegistry 发心跳 —— 按心跳年龄扫，60 秒后全部节点会被判离线。只对真在发心跳的节点（远端自注册）才成立，等那类节点出现再按来源分开扫
  - `NodeFabricRegistry.list_by_capability`：NodeFabricRegistry 的只读查询面；按能力选路走的是 CapabilityRegistry 与能力网络联合选择（command_router 已在用），节点表按能力查是与 list_all / get 对称的读接口，保留
  - `NodeFabricRegistry.expire_stale_capabilities`：节点能力条目的时间戳只在注册时写一次，没有刷新来源；按时扫会在 5 分钟后把启动器节点的能力全部清出 CapabilityRegistry。等节点有了能力刷新 / 心跳再挂进 core/periodic_maintenance.py
- `core/operator_execution_observability_surface.py`
  - `OperatorExecutionEvidenceEntry.requires_operator_attention`：证据条目自带判定；operator 面汇总「需要人看」时用
- `core/orchestration/lifecycle.py` — `LifecycleManager.is_cancelled`、`LifecycleManager.finalise_plan`：LifecycleManager 已被 openclawd 使用；这两个方法是薄委托，调用方直接用内部实现
- `core/orchestration/state.py`
  - `SessionMemoryManager.record_turn`：openclawd 已持有 SessionMemoryManager；对话轮次写入目前走 session_manager，二者重叠，定一个
- `core/perception/desktop_perception_store.py`
  - `DesktopPerceptionStore.take_fresh_system_audio_for_autoinject`：系统播放声已经经 build_multimodal_context 作为原生模态注入请求；转写式注入目前只给麦克风开（GALAXY_DESKTOP_AUDIO_AUTOINJECT，默认关）。系统播放声比麦克风更敏感（会议、私信语音），要不要另开一道转写注入由所有者决定，不替你打开
- `core/presence/presence_director.py` — `PresenceDirector.on_phase_transition`、`PresenceDirector.refresh_presence`：跨设备在场投射只产出 PRESENCE_PROJECTED 事件，全仓没有把这类事件送到设备的传输 —— 唯一的通配订阅方是本机面板桥（只会触发本机面板重推）。接上只会在每次相位切换时产生没人收的事件。等设备侧有在场渲染通道再接（按「只有电脑发起的进三态」，也只在电脑发起的跨设备任务里触发）
- `core/recovery_truth_surface.py` — `RecoveryLevel.all_levels`、`RecoveryTruthReport.has_deferred`：报告对象自带判定；读恢复真相的验收面按需调用
- `core/reliability_contract/retry_policy.py`
  - `RetryPolicy.has_retries`：值对象判定，随重试策略被消费时用
- `core/remote_execution_mode_resolver.py`
  - `ModeResolutionResult.as_remote_execution_mode`：结果对象上的转换方法，调用方需要枚举时用
- `core/runtime_closure_audit.py`
  - `persist_conflict_artifacts`：随 run_closure_audit 一起：审计发现冲突时落盘
- `core/runtime_readiness_matrix.py`
  - `is_release_blocked`：core/routes/operator.py 已读就绪矩阵；需要布尔时用
- `core/slo_metrics.py`
  - `SLOMetrics.startup_duration_ms`：启动耗时已在 snapshot() 的 startup.duration_ms 里经 GET /api/v1/slo/metrics 给出；属性本身只是对象访问器
- `core/streaming_speech.py`
  - `IncrementalSpeaker.spoke_anything`：只读属性，core/routes/chat.py 判断是否已边生成边念时用
- `core/subject_facing_foreground.py`
  - `SubjectFacingForeground.is_completed`：对象判定，core/routes/chat.py 已持有该对象
- `core/system_orchestrator.py`
  - `SystemOrchestrator.register_hook`：启动编排的扩展点：插件要挂启动阶段钩子时用
- `core/target_device_validator.py`
  - `CanonicalValidationInput.from_legacy`：随 validate_target_device_from_canonical 一起：旧调用方数据 → 规范输入
- `core/task_cost_ledger.py`
  - `current_task_bill`：上下文变量访问器：HTTP 请求自己的上下文里永远没有在途账单，挂成端点恒为 null；结清的账单已由 GET /api/v1/cost/tasks 给出
- `core/unified/capability_resolver.py`
  - `CapabilityResolver.resolve_by_tag`：按标签查契约；随 CapabilityResolver 被按标签查询时用
- `core/unified/command_envelope.py` — `CommandEnvelope.make_cancel`、`CommandEnvelope.make_interrupt`、`CommandEnvelope.is_cancel`：make_cancel / make_interrupt / is_cancel：取消目前只在本进程生效（core/routes/tasks.py → OpenClawd cancel_registry），没有把取消下发到设备的通道；CommandEnvelope 在全仓只用来记审计日志（e2e_orchestrator / task_orchestrator 的 log_command_envelope），造出来的 CANCEL / INTERRUPT 信封没有发送方。设备侧有取消处理时再接
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
- `core/voice_loop.py`
  - `VoiceLoop.process_once`：所有者决定保留：VoiceLoop 的非流式一次性处理入口（预录音频）。实时路径 VoiceLoop.start() → AudioCaptureService.add_whisper_callback 已改走 modality_bridge.transcribe_pcm（原生听优先、回落 Whisper）；一次性转写的 HTTP 面是 /v1/audio/transcriptions
- `launcher/nodes.py`
  - `equivalent_legacy_command`：存在只为让「每种老用法都有新写法」可测（docstring 写明，tests/test_launcher_nodes.py 在用）；旧 system_manager.py 已退役，运行期不该再提示老写法
- `nodes/Node_116_ExternalToolWrapper/main.py`
  - `ExternalToolWrapper.register_custom_handler`：扩展点：随 execute_custom 一起
- `nodes/Node_127_BambuLab/enhanced_bambu_controller.py`
  - `EnhancedBambuController.add_to_history`：拓竹打印机增强控制（错误检查、温度 / 进度报告）：设备能力，等有真实打印机接入时接进 Node_127 main.py；误删后已恢复
- `nodes/Node_43_MAVLink/universal_drone_controller.py` — `UniversalDroneController.start_recording`、`UniversalDroneController.stop_recording`、`UniversalDroneController.execute_waypoint_mission`：无人机航点任务与录像：设备能力，等有真实无人机接入时由节点 app 挂出；误删后已恢复
- `nodes/Node_71_MultiDeviceCoordination/main.py` — `Device.to_unified_model`、`Device.from_unified_model`：统一 DeviceModel 与节点 Device 的互转，随 Node_71 对接网关设备模型时用

</details>

<details><summary>产品决定（product）— 3 条</summary>

- `core/control_plane/swarm_scaler.py`
  - `SwarmScaler.autoscale`：core/master_brain.py 已持有 SwarmScaler 但没驱动；要蜂群自动扩缩就放在 master_brain 的周期循环里 —— 这是产品决定
- `core/device_orchestrator.py`
  - `DeviceOrchestrator.sync_clipboard`：跨设备剪贴板是产品功能：要不要做由所有者决定；做就挂 core/routes/devices.py
- `core/proxy_relay.py`
  - `ProxyRelay.relay_agent_manifest`：把 Agent 从一台设备迁到另一台 —— 依赖端侧执行沙盒（不可达模块 local_agent_runtime），要做就和它一起定

</details>

### 按子系统

| 子系统 | 条数 | 文件数 |
|---|---|---|
| `core/（其余单文件）` | 114 | 68 |
| `galaxy_gateway/` | 32 | 16 |
| `core/android_*` | 20 | 13 |
| `core/delegated_*` | 17 | 5 |
| `core/cognitive/` | 16 | 7 |
| `core/ugcp_*` | 15 | 3 |
| `core/node_*` | 13 | 5 |
| `core/unified/` | 13 | 5 |
| `core/mesh/` | 12 | 6 |
| `core/attached_runtime_*` | 10 | 5 |
| `core/capability_*` | 9 | 6 |
| `core/device_*` | 9 | 5 |
| `core/v2_*` | 8 | 2 |
| `core/cross_*` | 7 | 3 |
| `core/flow_*` | 6 | 1 |
| `core/model_topology/` | 6 | 4 |
| `core/orchestration/` | 6 | 5 |
| `core/truth_*` | 5 | 2 |
| `nodes/Node_71_MultiDeviceCoordination/` | 5 | 2 |
| `core/execution_observability/` | 4 | 4 |
| `core/runtime_*` | 4 | 3 |
| `core/task_*` | 4 | 4 |
| `nodes/Node_70_AutonomousLearning/` | 4 | 1 |
| `core/continuum/` | 3 | 2 |
| `core/control_plane/` | 3 | 2 |
| `core/multimodal/` | 3 | 1 |
| `core/nodes/` | 3 | 1 |
| `launcher/` | 3 | 3 |
| `nodes/Node_43_MAVLink/` | 3 | 1 |
| `core/canonical_*` | 2 | 1 |
| `core/capability_runtime/` | 2 | 2 |
| `core/cross_device_policy/` | 2 | 1 |
| `core/hybrid_*` | 2 | 1 |
| `core/perception/` | 2 | 1 |
| `core/presence/` | 2 | 1 |
| `core/adapters/` | 1 | 1 |
| `core/agent/` | 1 | 1 |
| `core/desktop_*` | 1 | 1 |
| `core/device_formation/` | 1 | 1 |
| `core/execution/` | 1 | 1 |
| `core/execution_*` | 1 | 1 |
| `core/generative_ui/` | 1 | 1 |
| `core/operator_*` | 1 | 1 |
| `core/orchestration*` | 1 | 1 |
| `core/reliability_contract/` | 1 | 1 |
| `nodes/Node_116_ExternalToolWrapper/` | 1 | 1 |
| `nodes/Node_127_BambuLab/` | 1 | 1 |
| `nodes/Node_33_ADB/` | 1 | 1 |

### 从真实入口不可达的模块

| 模块 | 行数 |
|---|---|
| `core.local_agent_runtime` | 423 |
| `core.posture_contract_canonicalization` | 331 |
| `core.truth_conflict_enforcement` | 979 |

### 逐文件清单

按用途分组，每个函数后面是它**自己的说明**（docstring 第一行，原文照录；没写说明的标「无说明」）。
标记：`T` 只有测试在引用；`—` 连测试都没有。

<details><summary>节点服务里的方法 — 15 条</summary>

- `nodes/Node_116_ExternalToolWrapper/main.py`
  - `ExternalToolWrapper.register_custom_handler` — — 注册自定义处理器
- `nodes/Node_127_BambuLab/enhanced_bambu_controller.py`
  - `EnhancedBambuController.add_to_history` — — 添加打印记录到历史
- `nodes/Node_33_ADB/cluster_manager.py`
  - `ADBClusterManager.parallel_execute` — — 在多个设备上并行执行命令
- `nodes/Node_43_MAVLink/universal_drone_controller.py`
  - `UniversalDroneController.start_recording` — — 开始录像
  - `UniversalDroneController.stop_recording` — — 停止录像
  - `UniversalDroneController.execute_waypoint_mission` — — 执行航点任务
- `nodes/Node_70_AutonomousLearning/core/autonomous_learning_engine.py`
  - `AutonomousLearningEngine.generalize_skill` — — 从模式中泛化技能
  - `AutonomousLearningEngine.find_similar_skills` — — 基于相似度查找相关技能
  - `AutonomousLearningEngine.process_observation` — — 处理 VLM 观察结果，生成下一步行动计划（增强版）
  - `AutonomousLearningEngine.update_experience_outcome` — — 更新经验结果（用于强化学习反馈）
- `nodes/Node_71_MultiDeviceCoordination/main.py`
  - `Device.to_unified_model` — — 转换为统一 DeviceModel。
  - `Device.from_unified_model` — — 从统一 DeviceModel 创建 Node_71 Device。
- `nodes/Node_71_MultiDeviceCoordination/models/task.py`
  - `Task.update_progress` — — 更新进度
  - `TaskQueue.dequeue` — — 出队
  - `TaskQueue.is_empty` — — 是否为空

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

<details><summary>持久化、重启恢复与断点续跑 — 27 条</summary>

- `core/delegated_flow_decision_history.py`
  - `HistoryEvidenceStatus.allows_runtime_closure` T — Return ``True`` only when status permits runtime_closure_established=True.
  - `HistoryEvidenceStatus.is_definitive_gap` T — Return ``True`` when the status represents a clear evidence deficit.
  - `record_delegated_flow_event` T — Record a delegated flow event in the process-global singleton registry.
- `core/delegated_flow_persistence.py`
  - `persist_session_snapshot` T — Persist *sessions* to the durable session store.
  - `restore_sessions` T — Restore session entries from the durable store.
  - `persist_contract_snapshot` T — Persist *contracts* to the durable contract store.
  - `restore_contracts` T — Restore contract records from the durable store.
  - `persist_binding_snapshot` T — Persist *bindings* to the durable binding store.
  - `restore_bindings` T — Restore binding records from the durable store.
  - `persist_flow_entity_snapshot` T — Persist *flow_entities* to the durable flow-entity store.
- `core/delegated_flow_recovery_coordinator.py`
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
  - `load_hybrid_execution` T — Load a record by *execution_id* from the durable store.
  - `recover_hybrid_executions` T — Return restart-normalised, non-terminal records from the durable store.
- `core/recovery_truth_surface.py`
  - `RecoveryLevel.all_levels` T — 无说明
  - `RecoveryTruthReport.has_deferred` T — Return True when at least one dimension is explicitly deferred.
- `core/task_graph_runtime.py`
  - `result_envelope_to_node_update` T — Apply a ``ResultEnvelope`` (or compatible object) to a ``GraphNode``.
- `core/task_lifecycle.py`
  - `TaskLifecycleManager.run_with_lifecycle` T — Execute ``coro_factory(envelope)`` with automatic lifecycle bookkeeping.

</details>

<details><summary>指标、可观测与审计记录 — 9 条</summary>

- `core/decision_diff_telemetry.py`
  - `record_candidate_diff` T — Record a cross-device candidate selection legacy-vs-canonical diff.
- `core/execution_observability/event_schema.py`
  - `ExecutionEvent.projection_summary` T — Return a compact summary suitable for Status Board / Manifest consumers.
- `core/execution_observability/executor_level.py`
  - `ExecutorLevel.from_win_exec_level` T — Convert a ``WinExecLevel`` enum value (or its string repr).
- `core/execution_observability/normalizers.py`
  - `normalize_e2e_context` T — Build an :class:`ExecutionEvent` from a ``core/e2e_orchestrator.py``
- `core/execution_observability/trace_schema.py`
  - `TraceCorrelation.from_task_graph` T — Normalise from a :class:`~core.task_graph.TaskGraph` instance.
- `core/operator_execution_observability_surface.py`
  - `OperatorExecutionEvidenceEntry.requires_operator_attention` T — True iff operator intervention or review is indicated.
- `core/orchestration_review_surface.py`
  - `increment_legacy_dispatch_counter` T — Increment the legacy dispatch counter for a named compat surface.
- `core/slo_metrics.py`
  - `SLOMetrics.startup_duration_ms` T — Startup duration in milliseconds, or ``None`` if not yet recorded.
- `core/task_cost_ledger.py`
  - `current_task_bill` T — 无说明

</details>

<details><summary>架构治理：权威声明、边界断言与自检 — 56 条</summary>

- `core/canonical_ownership_truth_bridge.py`
  - `is_recovery_eligible` T — Return ``True`` when *ownership_boundary* allows canonical recovery admission.
  - `build_ownership_aware_replay_execution_record` T — Return a copy of *base_record* with ``participant_ownership_boundary`` populated.
- `core/compat_fallback_authority_guard.py`
  - `block_compat_influence_at_decision_site` T — Evaluate a compat/legacy influence using the PR-8 blocking gate.
- `core/compat_legacy_path_blocking_canonicalization.py`
  - `CompatLegacyBlockingRecord.is_quarantined` T — Return True when this record represents a quarantine decision.
- `core/cross_device_dispatch_boundary.py`
  - `classify_dispatch_call` T — Classify a cross-device dispatch call into one of the four boundary
  - `is_canonical_dispatch` T — Return True when the call follows the primary canonical path.
  - `is_controlled_fallback` T — Return True when the call is a controlled canonical fallback.
  - `is_compat_fallback` T — Return True when the call is a compat fallback.
  - `is_legacy_bypass` T — Return True when the call is a legacy bypass.
- `core/governance_validation_gate.py`
  - `evaluate_governance_validation` T — Module-level convenience function — evaluate governance validation.
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
- `core/repo_layout_registry.py`
  - `is_active_desktop_status_directory` T — Return ``True`` if *path* is the canonical active desktop status surface.
  - `build_repo_layout_summary` T — Build a structured summary of the repository layout registry.
- `core/runtime_closure_audit.py`
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

<details><summary>多设备编组、协同网络与拓扑 — 30 条</summary>

- `core/capability_network_bridge.py`
  - `explain_joint_selection` T — Produce a full human-readable explanation for a :class:`JointSelectionResult`.
- `core/capability_network_runtime_policy.py`
  - `absorb_capability_change_event` T — Absorb an executor/provider capability change into the capability assimilation layer.
  - `query_capable_device_executors` T — Query the canonical runtime for *device*-kind executors that are online
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
- `core/mesh/mesh_runtime_center_state.py`
  - `is_valid_center_transition` T — Return True when *from_status* → *to_status* is a valid transition.
  - `MeshParticipantEligibilityStatus.can_participate` T — Return True when this participant can meaningfully participate.
- `core/mesh/mesh_session_coordinator.py`
  - `MeshSessionCoordinator.update_with_dispatch_result` T — Incorporate a source dispatch result into the coordinator state.
  - `MeshSessionCoordinator.update_with_takeover_result` T — Incorporate a target takeover result into the coordinator state.
  - `MeshSessionCoordinator.update_with_merged_result` T — Incorporate a cross-runtime merged result into the coordinator state.
- `core/network_topology_runtime.py`
  - `assimilate_nats_state` T — Absorb NATS fabric state into the singleton runtime.
  - `assimilate_gateway_state` T — Absorb gateway substrate state into the singleton runtime.
  - `assimilate_device_connectivity` T — Absorb a device connectivity report into the singleton runtime.
- `core/orchestration/global_arbiter.py`
  - `GlobalArbiter.suggest_device` T — Return the least-loaded candidate device based on current task origin
- `core/presence/presence_director.py`
  - `PresenceDirector.on_phase_transition` T — React to a cognitive phase transition.
  - `PresenceDirector.refresh_presence` T — Unconditionally project *cognitive_state* to all mesh devices.
- `core/proxy_relay.py`
  - `ProxyRelay.relay_agent_manifest` — — Agent Manifest 中继 — 从一台设备迁移 Agent 到另一台
- `core/swarm_coordinator.py`
  - `SwarmCoordinator.build_execution_plan_for_orchestration` — — PR-11: Build a canonical :class:`~core.schemas.execution_plan.ExecutionPlan`
  - `SwarmCoordinator.device_candidates_from_canonical` T — Build a ``DeviceScoreInput`` list from canonical device projections.

</details>

<details><summary>设备与节点：注册、发现、连接、通信、传输 — 50 条</summary>

- `core/adapters/tcp_adapter.py`
  - `TCPAdapter.connect_to_peer` — — 主动连接到 P2P 对等端。
- `core/aip_transport.py`
  - `AIPTransport.unregister_adapter` — — 无说明
- `core/device_agent_manager.py`
  - `DeviceAgentManager.register_agent_type` — — 注册新的设备 Agent 类型
  - `DeviceAgentManager.connect_all` — — 连接所有设备
- `core/device_orchestrator.py`
  - `DeviceOrchestrator.parallel_commands` T — 并行向多台设备发送命令。
  - `DeviceOrchestrator.sync_clipboard` T — 跨设备剪贴板同步。
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
- `core/node_cognition_activation.py`
  - `evaluate_activation_eligibility` T — Evaluate whether *node_id* is eligible to be activated for *role*.
  - `transition_activation_state` T — Validate and apply an activation-state transition.
- `core/node_discovery.py`
  - `NodeDiscoveryService.seed_from_registry` T — 从 node_registry.json 预填充节点，无需等待 UDP 广播。
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
- `core/target_device_validator.py`
  - `CanonicalValidationInput.from_legacy` T — Build a CanonicalValidationInput from legacy/compat caller data.
  - `validate_target_device_from_canonical` T — Validate a target device from a pre-normalised :class:`CanonicalValidationInput`.
- `galaxy_gateway/agent_bridge.py`
  - `AgentBridge.handoff_from_envelope` T — PR-2 primary entry point: delegate a TaskEnvelope to the agent runtime.
  - `AgentBridge.build_envelope_v2` T — PR-31: Build a Handoff Envelope v2 from a legacy :class:`HandoffContract`.
- `galaxy_gateway/cross_device_switch.py`
  - `guard_cross_device` T — Raise :class:`CrossDeviceDisabledError` when the switch is OFF.
- `galaxy_gateway/enhanced_nlu_v2.py`
  - `DeviceRegistry.find_device_by_name` — — 通过名称或别名查找设备
- `galaxy_gateway/multimodal_transfer.py`
  - `MultimodalTransferManager.receive_image` — — 接收图片
  - `MultimodalTransferManager.send_video` — — 发送视频
  - `MultimodalTransferManager.send_file_chunk` — — 发送文件分块
  - `MultimodalTransferManager.receive_file_chunk` — — 接收文件分块
  - `MultimodalTransferManager.send_screenshot` — — 发送屏幕截图
- `galaxy_gateway/orchestrator/task_orchestrator.py`
  - `MultiDeviceOrchestrator.submit_multi_device_task` T — 提交多设备协同任务 — PR-2: 所有多设备任务强制经过 TaskGraph.
- `galaxy_gateway/resumable_transfer.py`
  - `ResumableTransferManager.receive_file` — — 接收文件（支持断点续传）
  - `ResumableTransferManager.write_chunk` — — 写入分块数据
- `galaxy_gateway/routing/router.py`
  - `RoutingOrchestrator.filter_eligible` T — Return *devices* that pass the online health gate.
  - `RoutingOrchestrator.build_message` T — Build an AIP v3 command envelope for WebSocket dispatch.
- `galaxy_gateway/ssot.py`
  - `udm_write_upsert` T — Perform a partial or full device state update through UnifiedDeviceManager.
- `galaxy_gateway/task_decomposer.py`
  - `TaskDecomposer.decompose_search_and_open` — — 分解"搜索并打开"任务
  - `TaskDecomposer.decompose_conditional_task` — — 分解条件任务
- `galaxy_gateway/transport/websocket_server.py`
  - `WebSocketManager.handle_connection` T — 处理设备连接的完整生命周期
- `galaxy_gateway/websocket_handler.py`
  - `handle_response` T — 处理任务/命令执行结果（接受 AIPMessage 对象）

</details>

<details><summary>能力、模型与执行路由 — 31 条</summary>

- `core/capability_assimilation.py`
  - `CapabilityAssimilationLayer.mark_stale_if_expired` T — Mark all nodes whose heartbeat is older than *heartbeat_ttl_secs* as STALE.
  - `assimilate_node` T — Convenience helper: assimilate a NodeInfo-compatible object or dict.
- `core/capability_aware_routing_default.py`
  - `apply_capability_aware_default` T — Apply capability-aware routing as the default main path.
- `core/capability_bus.py`
  - `CapabilityBusRole.from_tool_name` T — Infer :class:`CapabilityBusRole` from a canonical tool name.
  - `CapabilityBus.seed_from_node_registry` T — Seed :class:`CapabilityBusEntry` records from ``config/node_registry.json``.
- `core/capability_graph_selection.py`
  - `explain_selection` T — Produce a human-readable explanation for why *record* was selected.
- `core/capability_runtime/capability_constraint.py`
  - `CapabilityConstraintFlags.has_any_constraint` T — Return ``True`` if at least one flag is set.
- `core/capability_runtime/capability_preference.py`
  - `CapabilityPreference.has_preference` T — Return ``True`` if any non-default preference is expressed.
- `core/command_router.py`
  - `CommandRouter.normalize_legacy_ingress` T — Normalize a non-envelope payload to a ``TaskEnvelope`` and record it.
- `core/concurrency_manager.py`
  - `LockManager.release_all` T — 释放某持有者的所有锁
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
- `core/modality_bridge.py`
  - `resolve_audio_in` T — 当前档位的听通路：native / asr_bridge。
- `core/model_topology/canonical_model_supply_state.py`
  - `NativeMultimodalCapabilityRegistry.register_many` T — Register multiple capability records.
- `core/model_topology/config_bridge.py`
  - `ConfigBridge.build_inventory` T — Build a full ``ProviderInventory`` from dashboard-era input.
- `core/model_topology/model_supply_graph.py`
  - `ModelSupplyGraph.edges_of_kind` T — 无说明
  - `ModelSupplyGraph.nodes_by_category` T — 无说明
  - `ModelSupplyGraph.nodes_by_provider` — — 无说明
- `core/model_topology/topology_router.py`
  - `TopologyRouter.route_all_phases` T — Produce plans for all three public tri-state phases.
- `core/multi_llm_router.py`
  - `MultiLLMRouter.chat_cascade` T — L2 级联路由(任务感知的 FrugalGPT):按任务【实际复杂度】定起步档,再便宜→贵升级。
- `core/native_modal.py`
  - `is_native_active` T — 无说明
- `core/remote_execution_mode_resolver.py`
  - `ModeResolutionResult.as_remote_execution_mode` T — Return the resolved mode as a :class:`RemoteExecutionMode` enum.
- `core/unified/capability_resolver.py`
  - `CapabilityResolver.resolve_by_tag` T — Return validated contracts whose tags include *tag*.

</details>

<details><summary>智能体、认知与记忆 — 38 条</summary>

- `core/agent/policy_loader.py`
  - `reload_policies` T — 强制重新从磁盘加载所有策略文件。
- `core/agent_manifest.py`
  - `AgentManifest.create_multi_step_agent` T — 创建多步骤顺序执行 Agent
- `core/agent_team.py`
  - `AgentTeam.couple_member` — — 切换成员的耦合模式
  - `AgentTeam.decouple_member` — — 解耦成员
- `core/ai_intent.py`
  - `SemanticSearch.index_document` T — 索引文档（优先使用统一向量后端，降级到内置本地索引）
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
- `core/cognitive/memory_bias_layer.py`
  - `MemoryBias.is_continuity` T — Return True when posture is continuity-seeking.
  - `MemoryBias.is_retrieval` T — Return True when posture is retrieval-seeking.
  - `MemoryBias.is_novelty` T — Return True when posture is novelty / low-memory.
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
- `core/e2e_orchestrator.py`
  - `run_multi_device_via_task_graph` T — Execute *subtasks* across multiple devices **always** via TaskGraph.
  - `process_user_input` T — 统一用户输入处理入口。
- `core/focus_stack.py`
  - `FocusStack.drop_current` T — 显式结束当前焦点,上一个自动恢复为当前。
- `core/galaxy_main_loop_l4_enhanced.py`
  - `GalaxyMainLoopL4.receive_goal` T — 接收外部目标（UI → L4 集成点）。
- `core/generative_ui/runtime.py`
  - `GenerativeUIRuntime.render_surface_dict` T — Convenience wrapper returning :meth:`SurfaceSpec.to_dict`.
- `core/grounded_planner.py`
  - `to_task_assign` T — 把规划出的动作落成 AIP v3 TASK_ASSIGN，带上当前结构化界面态。
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
- `core/vector_backend.py`
  - `_QdrantBackend.add_document_vector` — — 带向量的索引（Qdrant 专用）

</details>

<details><summary>语音、桌面在场与感知 — 11 条</summary>

- `core/desktop_consumption_adapter.py`
  - `DesktopClientViewModel.readiness_label` T — Return a short human-readable readiness label for display.
- `core/duplex_presence_bridge.py`
  - `DuplexPresenceBridge.presence_handle` T — 常驻在场句柄;未开启时为 None。
- `core/multimodal/perception_source_registry.py`
  - `PerceptionSourceRegistry.update_quality` T — Update quality and/or latency metrics for a source.
  - `PerceptionSourceRegistry.sources_by_type` T — Return all records with the given ``source_type``.
  - `PerceptionSourceRegistry.degraded_sources` T — Return sources whose health is DEGRADED or UNAVAILABLE.
- `core/perception/desktop_perception_store.py`
  - `DesktopPerceptionStore.has_fresh_frame` T — 摄像头或屏幕任一有新鲜帧即为 True。隐私暂停时恒为 False。
  - `DesktopPerceptionStore.take_fresh_system_audio_for_autoinject` T — 取一段「新鲜且未被自动注入消费过」的**系统播放声**。
- `core/phase_contract.py`
  - `tri_state_of` T — 四相 → 三态公共投影。未知相位按 ``silent`` 处理。
- `core/streaming_speech.py`
  - `IncrementalSpeaker.spoke_anything` T — 无说明
- `core/voice_duplex_session.py`
  - `DuplexSession.next_event` T — 取一条事件;超时返回 None。供不想用异步迭代的调用方。
- `core/voice_loop.py`
  - `VoiceLoop.process_once` T — 处理单次音频输入（非流式）。

</details>

<details><summary>配置、启动、安全、扩展与通用基础件 — 32 条</summary>

- `core/cache.py`
  - `CacheManager.set_json` — — 无说明
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
  - `ConfigService.is_provider_ready` T — Return ``True`` if *provider* is enabled and has an API key.
- `core/config_store.py`
  - `ConfigStore.write_secrets` T — Batch-write *data* to ``runtime/secrets.env``, merging with existing content.
- `core/failure_domains.py`
  - `map_to_pr_b_domain` T — Map a PR-13 implementation-specific domain to the PR-B canonical vocab.
- `core/mcp_addon_contract.py`
  - `is_valid_mcp_addon_contract` T — Return ``True`` if *raw* passes :func:`validate_mcp_addon_contract`.
- `core/message_interop.py`
  - `normalize_to_result_envelope` T — Convert a raw result dict to a canonical ``ResultEnvelope``.
- `core/reliability_contract/retry_policy.py`
  - `RetryPolicy.has_retries` T — Return ``True`` if this policy defines more than one attempt.
- `core/skill_package_contract.py`
  - `is_valid_skill_package_contract` T — Return ``True`` if *raw* passes :func:`validate_skill_package_contract`.
- `core/system_mode.py`
  - `FabricConfig.is_desktop_local` T — Return ``True`` when running in ``desktop-local`` mode.
- `core/unified/command_envelope.py`
  - `CommandEnvelope.make_cancel` T — Create a CANCEL envelope targeting *task_id*.
  - `CommandEnvelope.make_interrupt` T — Create an INTERRUPT envelope targeting *task_id*.
  - `CommandEnvelope.is_cancel` T — Return ``True`` if this envelope carries a cancel or interrupt verb.
- `core/unified/error_mapper.py`
  - `ErrorMapper.from_legacy_gateway_error` T — Map a legacy gateway error type string to a canonical payload.
  - `ErrorMapper.from_legacy_device_error` T — Map a legacy device-level error string to a canonical payload.
  - `ErrorMapper.from_legacy_executor_error` T — Map a legacy executor-level error string to a canonical payload.
- `core/unified/idempotency.py`
  - `IdempotencyStore.record_failed` T — Mark *key* as FAILED (allows future re-submission of same key).
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
