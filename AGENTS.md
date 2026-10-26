# Galaxy - AI Agent 知识索引

> 本文件为 AI Agent 提供系统知识索引，每轮对话自动加载。
> 基于 Vercel 研究：被动上下文比主动调用更可靠。
>
> **系统当前做到了哪儿、哪里是断的：只看 `docs/SYSTEM_STATUS.md`**（逐项复测，附复测命令）。
> docs/ 下其余状态/审计/成熟度文档是历史快照，里面的缺口与分数可能已经过期。

## 系统概述

Galaxy 是一个 L4 级自主性智能系统，支持：
- 跨设备控制（手机、平板、电脑）
- 自然语言驱动
- MCP/Skill 扩展
- 多节点协作

## 核心架构

```
┌─────────────────────────────────────────────────────────────┐
│                      用户交互层                              │
│  WebUI (配置) │ 主 UI (对话) │ 手机 App (控制)              │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                      系统集成层                              │
│  unified_config.py │ system_integration.py                  │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                      核心模块层                              │
│  device_registry │ device_communication │ mcp_loader        │
│  skill_loader │ agent_factory │ api_routes                  │
└─────────────────────────────────────────────────────────────┘
```

## 关键文件索引

### 配置管理
- `core/unified_config.py` - 统一配置管理器
- `config.json` - 主配置文件
- `.env` - 环境变量（API Key）
- `GALAXY_DATA_DIR` - 运行时数据目录（缺省仓库 `data/`）。**所有**持久化状态都认它，设备注册表也不例外 —— 新加的持久化点用 `core.data_paths.data_path(...)`，别写死 `"data/..."`，`tests/conftest.py` 靠它把测试状态隔离到临时目录。面板「保存设置」重写 `.env` 时，登记表之外的手写行（compose 口令、端口、镜像站……）原样带回（`core/routes/config_env_preserve.py`）。
  面板存的密钥库 `secrets.env` 与 `config.json` 也在数据目录（`core.config_store.default_secrets_path`；`runtime/` 下已有的继续用；`main.py` 启动第一步在 import core 之前照抄同一条规则，测试核对两边）。
  进程这一次运行自己写进环境变量的值（`--backend` / `-v` / `--model`、内置总线地址、本机推理服务地址、临时降档）经 `core.derived_env.export` 写 —— 「保存设置」把 `os.environ` 整份写回 `.env`，裸写会被钉成「人配过」

### 设备管理
- `core/device_registry.py` - 设备注册和发现
- `core/device_communication.py` - 设备通信协议
- `core/device_control_service.py` - 设备控制服务
- **中心智能体 + 相对主体**：智能体是唯一做决定、做协调的地方；它跑在哪台设备上，哪台就是**主脑**（一个角色，不是一个模块）。
  手机、手表、别的电脑、Linux / 云载体都是**成员**：先登录登记进 UDM / UCM（配对码或网络连接），再由智能体经 mesh 协调、经 AIP v3 / NATS 通信。
  整体设计见 `docs/CROSS_DEVICE_OVERALL_PLAN.md`；设备怎么描述自己、代码守哪些边界、怎么评测见 `docs/DEVICE_SELF_DESCRIPTION_DESIGN.md`
  （动作给模型用、声明给边界用；设备级声明只有 `answers_decisions` / `shows_request_progress` / `hosts_agent` / `tailnet` 四样，要加得写明是哪条边界在用）。
- **「跨设备」开关只说这台设备自己进不进网络，从不限制智能体**：电脑上的开关 = 这台电脑作为设备加入（桌面登记成成员、电脑自己的请求可交给别的设备）；
  手机的开关 = 手机加入；手表配对即加入。**智能体协调已加入的设备不看任何模式** —— 能不能下发由成员资格（名册、连接、权限门）决定。
  **别再给「往别的设备下发」加模式判断**（以前的统一拒绝 `cross_device_refusal` 与「请求打开跨设备」工具都已删除，`tests/test_the_agent_coordinates_members_in_any_mode.py` 守着）。
  「现在是哪个模式」只有一条规则、一个出处：`core.system_mode.cross_device_requested()` —— `GALAXY_CROSS_DEVICE_ENABLED` 为真**或** `GALAXY_SYSTEM_MODE=desktop-cross-device`。
  `GALAXY_NATS_URL` 只说总线在哪，**不参与**判模式。面板上切换的只有「跨设备」一个按钮（写主键、`GALAXY_SYSTEM_MODE` 与唯一成员 `GALAXY_NATS_ENABLED`）。
  「混合」不是模式，是一个请求的走法（入口判定 `resolve_entry_mode`，跟着电脑的开关走）；`core/hybrid_executor.py` 的「混合执行」是单台设备内部的降级链，别混。
- **模型看的是每台设备的「整体卡」，不是固定角色**（`core/device_onboarding/device_card.py`，`devices__list` 与 `GET /api/v1/onboarding/cards` 同一份）：
  是什么 / 能做什么（设备自己报的动作 + 一句说明：`capability_report` 的 `capability_schemas[].description` 或 `action_descriptions`）/ 现在怎么样（在线、电量、网络路径、忙不忙、手表能否打扰）/
  能否接派来的 Agent（`can_take_agent`）/ 最近做过什么（任务流程图）。谁做什么由模型定，规则只过滤；「感知 / 动作 / 在场」（`core/mesh/device_role_allocator.py`）只是观测标签，
  **别让派发路径读它**（`tests/test_the_model_sees_each_device_as_a_whole.py` 守着）。每次单动作下发都记进任务流程图（`device_card.record_dispatch`）。
- **对外 A2A**（中心智能体 ↔ 派出去的 Agent：手机上的桥接 Agent、载体上的 Agent）：AIP v3 `a2a` 帧，信封与「必达」链路在 `core/a2a_link.py`，与安卓 `shared-protocol/.../A2A.kt` 线格式逐字一致（改一边必须改另一边，`tests/test_external_a2a_link.py` 对照）。
  发消息用 `a2a_link.send(device_id, kind, body)`（设备不在线也留着，登记后补发）；各类消息到了做什么用 `register_handler`（处理器要快，久的事自己起后台任务）。混合执行里「直接调 API」那一级叫「API 直调」，别再叫 A2A。
- **手机加入 = 中心派一个桥接 Agent 过去**（`core/phone_bridge.py`，手机那一半在安卓 `bridge/BridgeAgentRuntime.kt`）：报能力时声明了 `bridge_agent` 的才派；设备的本地对话 / 进度交接进会话 `bridge:<设备号>`（不分设备是什么）；设备上说的话来源是 `device_chat`（人发起、不进三态），
  回答回手机；整段目标用 `devices__delegate` 交给手机本地循环；关跨设备时交还。来源分类只有一处：`core/presence_line.py`（`REMOTE_SOURCES`、主循环认的 `AGENT_LOOP_SOURCES`）。
- **实时语音里边说边做**（`core/voice_call_agent.py`）：实时语音模型负责说，中心智能体负责做；**不默认只聊**。**不分设备是什么**：说明里只有设备自己报的名字，哪种设备打来都是来源 `device_call`。设备通话接云端 OpenAI / Gemini 时，会话里声明 `agent_do` / `agent_status` / `agent_stop`，`agent_do` 立刻回「已经开始做」，事情经 `handle_request(source="device_call")` 在后台跑，做完在没人说话时插【回报】。不会调工具的（阶跃、本机全模态 server）和电脑自己的实时语音由智能体**旁听**：人说完一句，快档模型判做 / 停 / 问 / 在聊，要做的把人的原话交过去（电脑上来源 `voice_duplex`，走三态、不另外念）。`device_call` 不进电脑三态，也**不**算人亲口说的。挂断后才有结果的事交给智能体，由它看设备卡片决定发到哪台、怎么说。智能体在问的事进通话，只认问出口之后人的原话；高风险批准仍要在弹出的确认上点。问人发给哪些设备看设备自己在能力上报里声明的 `answers_decisions`，不看类型。本地实时服务不塞 `tools`（`GALAXY_REALTIME_TOOLS=1` 打开）；配不上也绝不让电话打不通；只有 `GALAXY_VOICE_CALL_AGENT=0` 才只聊。
- **多步、多设备的事写成计划**：`devices__plan`（`core/task_plan.py`，方案里叫 `tasks__plan`）接现成的 ConstellationRuntime 分层执行；挑设备、失败后怎么办都听模型的，不开自动重排。
  给设备下发一律经 `core/device_queue.run_on_device`（每台设备串行）；计划在 `task_plans.json` 写盘，重启只做排着没做的步骤，崩溃时在做的那一步「结果不明」不重做。
  只为观测记进任务图的节点要标 `observation_only`，否则重启续跑会拿它去重派。
- **Agent 载体**＝`python -m device_client --carrier`（`device_client/carrier_agent.py` + `executors/carrier.py`）：和手机走同一套桥接（`core/phone_bridge.py`），
  报能力时声明 `bridge_agent` 才算能接 Agent。载体的模型经中心（`tool_call` `llm.chat`），载体上不放钥匙；代码只在 Docker 沙箱里跑，文件只在它的工作目录里。
  路由在没有模型时回的是一句说明（`provider == "none"`），别把它当答案。委派前先 `_settle`：刚登记还没报能力、或装过还没重新装上的设备要等一下再判。
- **传输适配器只在一处装**：`galaxy_gateway/bootstrap/transports.register_transport_adapters`（独立网关 lifespan 与桌面版 `core/startup.py` 共用，同一进程只装一次）。
  「websocket」传输走规范入口的 `UnifiedConnectionManager`。`get_aip_transport().send` 失败是**返回** `{"success": False}`、不抛异常 —— 调用方要看返回值再兜底；
  处理器的返回值已经由设备入口写回，别再经 AIPTransport 另推一份同样的帧。
  规范设备入口把连接自己的凭证（握手 Bearer / 回过 `auth_ok` 的令牌）带给不带令牌的帧 —— 安卓的 `device_register` 就不带令牌（`tests/test_phone_joins_through_its_bridge_agent.py` 守着）。
- **成员找得到、连得上智能体，不分模式**：mDNS 广播一直做（`GALAXY_MDNS=0` 可关）；配了自建 headscale 就入 tailnet；设备接入平面（智能体的设备工具）、
  局域网发现都不是「跨设备」的成员；headscale / TURN / STUN 配置项面板上一直显示。
- **任务派发**（`GALAXY_MASTER_BRAIN_ENABLED`，类名 `MasterBrain`：经 NATS 把任务派给 worker）是智能体的工具，**只看它自己的开关**，开了就把 NATS 拉起来；
  派发走 `CommandRouter.route_envelope()` 按 `executor_target_type` 分三条路（`local` / `android_device`·`node_service` → 网关 `DeviceRouter` / `go_worker` → 任务派发 → NATS → worker）。
  「主脑」一词只指智能体所在的设备；选模型那块叫「模型」。

### 桌面自动化（一个整体，按现场挑）
- `core/windows_execution_arbiter.py` - 桌面落手的**唯一入口**：系统接口 → 控件 → 坐标 → 视觉（Computer Use）四级降级链
- `core/desktop_automation.py` - 每一级下面的后端登记表（Win32 / 本仓 UIA / 微软 UFO / 自动控制节点 Node_92 / 桌面操作节点 Node_36）：谁能用（说得出原因）、
  这一步先试谁（动作本身 + 当前前台应用上的战绩 `desktop_backend_record.json` + 现场探测）。**只重排不删兜底，视觉永远最后**。
  Computer Use 在本机落手、Windows Agent 在本机都走它（后者只用结构化三级）；别再各写一份「直接调 pyautogui / 直接派节点」。
  微软 UFO 要装了 `ufo` 包才算可用（仓库里的 `external/microsoft_ufo` 是不全的源码），`core/microsoft_ufo_integration.py` 只是门面
- `core/computer_use_verdict.py` - Computer Use 模型说「做完了」只是自报（`claimed_done`）：另取一张当前屏幕交给只看任务与屏幕的核对请求，
  四值裁决由 `classify_execution_evidence()` 给；核对没通过 → 后台把没做完的部分再做一次 → 仍不行进「没收口的结果」（`kind="computer_use"`）。
  人正在用电脑时不在后台动键鼠；仲裁器视觉级只核对、不排后台重做

### 扩展系统
- `core/mcp_loader.py` - MCP 服务器加载器
- `core/skill_loader.py` - 技能加载器
- `core/skill_md_loader.py` - SKILL.md 格式加载器

### Agent 系统
- `core/agent_factory.py` - Agent 工厂
- `core/system_integration.py` - 系统集成层
- `core/agent/execution_planner.py` - 执行规划器（策略选择的唯一决策点）

### 策略选择的三层建议输入（都是 advisory，硬门禁永远优先）
`ExecutionPlanner._pick_strategy()` 按优先级消费三份制导，任何一份都**不能**
覆盖 task_type 映射、显式关键词、或更高优先级的制导：
- `core/cognitive/cognitive_activation_budget.py` - PR-18 认知预算 → 广度制导
- `core/cognitive/memory_bias_layer.py` - PR-19 记忆偏置（POLICY_4：优先级最低）
- `core/cognitive/experience_guidance.py` - 执行经验制导（对象锚定）

> **经验制导为什么是对象锚定的：** 它读 `TaskSummary` 的类型化字段
> （`strategy: str` / `success: bool`），作用域由 BM25 词法排序提供，
> 全程无正则、无 embedding。被它取代的旧实现把这些结构化事实写成散文、
> 向量召回 8 段、再用正则抠回结构——算出的"成功率"分母是相似度采样而非
> 真实执行总数，且直接覆写已选定的策略。
> **决策路径不得从检索到的文本里反解结构。**
> 与 `pattern_miner` 的策略模式挖掘存在职责重叠，边界见
> `EXPERIENCE_GUIDANCE_PATTERN_MINER_BOUNDARY` 哨兵。

### 面板上的「模型服务商」
- `core/provider_catalog.py` - 面板逐厂商填 Key 的目录（`GET /api/v1/models/providers`）：厂商中文名 / 分组 / 该填哪几个键 / 是否已配 / 路由器里是否可用。**不下发密钥值**，只有布尔。
  `PROVIDER_REGISTRY` 多一家而没写展示信息，`tests/test_provider_catalog_covers_every_key.py` 会红。
  画法是**内嵌的行**（`.vd-card` 左栏说明 + 右栏输入，与设置页 `.sf-row` 同一个节奏），不是凸起的卡片 —— `tests/test_the_api_entry_is_inline_rows_not_cards.py` 钉着。
- `core/routing_tail.py` - 偏好表没列、但已配好可用的厂商（用户自加端点、OneAPI、只配了 Groq 的人做推理任务）排在失败转移链的最后几档；有意不自动参与的（智谱编码套餐）不进这一档

### 事件循环里不跑阻塞的事
Windows 真机日志里「一堆请求在同一毫秒一起完成、各自显示 5–7 秒」= 循环被一件同步的事占住了。已经挪出循环的：开麦克风 / 枚举音频设备
（`core/multimodal/audio_ingest.py`、`system_audio_capture_service.py`）、第一次选 TTS 引擎（`core.speech_output.speech_engine_ready()`）、创建节点进程
（`launcher/service_manager.py`）、拓扑图整份落盘（启动时的一百多次登记合成一次，`core/persist_batch.py`）、每个 httpx 客户端各载一遍 CA 证书
（`core/shared_tls.py`）。**节点子进程的输出写 `logs/nodes/<名字>.log`，不接管道**（没人读的管道写满，子进程卡死在 write() 里；Windows 管道缓冲只有 4KB）。

### 节点（各自一个进程的微服务）
- **缺东西就照实失败，不模拟成功**：没连设备 / 没配 Key / 没有命令时，节点回 `success: false` 并说缺什么（`nodes/common/mock_drivers.py`）；
  模拟只在显式 `USE_MOCK_DRIVERS=true` 时才有。没有调用方读 `mock` 那一位，看的都是 `success`。Node_58 的 `/chat` 走 `core.multi_llm_router`（与对话主链同一个），没模型就 503
- core / 别的节点打节点端点要带身份：`core.internal_auth.internal_headers_for(url)`（节点 HTTP 面默认有鉴权）；`tests/test_all_node_http_surfaces_require_auth.py` 扫描调用点
- 同一个节点只起一份：`ServiceManager.start_service` 见已在跑 / 正在起就不再建进程，`register_service` 不换掉已有条目（并发激活曾起两份、前一个停机后还活着）；
  启动那一批节点的登记，节点表只落盘一次（`NodeFabricRegistry.batched_persistence()`）

### 模型选择：智能路由多一个「用途」维度
`core/multi_llm_router.py` 的打分（质量 × 复杂度、成本、延迟、实测表现）是**一个**函数 `_fit_scorer`，
`core/llm_types.py::RoutingPurpose` 是其中并列的又一个评定维度，不是另开路径：
- **对话推理**（`MultiLLMRouter.route()` → `chat()`）：本地优先照旧；云端厂商之间按打分排序（延迟计入），
  不再照 `TASK_ROUTING_PREFERENCES` 的写死顺序 —— 偏好表只决定谁有资格；故障转移顺序随之就是排名。
- **Agent 生成**（特种部队 `SPECIALIZED`、`select_brain_for_role/_task`）：质量第一（成本降权、延迟不计），
  优先最优云端 API，`rank_brains_for_task()` 给排名与备选。team / swarm / parallel / critic / pipeline 不变。
- 选型号**只读** `PROVIDER_MODEL_MAP`，`core/provider_registry.py` 的 `models` 只是目录 —— 新增型号两处都要改
  （`tests/test_every_catalogued_model_has_a_home.py` 守着）。没有一手来源的型号串不登记。

### 对象层（决策该去哪儿拿事实）
- `core/canonical_task.py` - CanonicalTask 任务本体 + 进程内运行时（权威）
- `core/canonical_task_store.py` - 任务对象的**持久可查询投影**。ring buffer 只有
  256 条且随进程消失，答不了"这个任务/设备之前怎么了"；本存储按类型化字段
  确定性查询（`GALAXY_CANONICAL_TASK_STORE`，默认 `shadow` 只写不读）
- `core/semantic_anchoring.py` - **判据 + 可执行守卫**：会改变控制流的读取必须走
  对象层确定性查询；只进 prompt 的读取继续走检索。守卫能扫出"先 `recall` 再
  `re.search` 抠结构"这个缺陷签名
- `core/ontology/links.py` - 显式关系层（Link Types）。把散在各 registry 的隐式
  关联提为可列举、可遍历的声明；纯只读投影，不存储、不改写、可整包删除

> **判据一句话：** 读取的结果若会改变控制流（选策略/选设备/判权限/决定是否执行），
> 走对象层；若只是进 prompt 供 LLM 参考，走检索。**该换的是决策路径，不是检索能力**
> ——`Node_105`、`academic_retrieval` 面对的本来就是非结构化文本，向量检索是对的工具。

### 元层（RSI）—— 一个被学习信号闭合、并被权威边界切过一次的循环
- `core/meta/` - Kernel（采集 → 提案 → 验证 → **裁决** → 生效/回滚 → lesson）+ 六型 artifact
  （内容寻址、lineage 一等）。`GALAXY_META_RSI=off|shadow|on`，默认 off。CLI：`scripts/meta_rsi.py`
- 面板「全部设置 → 自我改进」只列 `GALAXY_META_RSI` 这一个总闸。同组其余键（Agent 供给、Genome、验证超时）
  默认即生效，登记在 `core/routes/config.py::PANEL_HIDDEN_KEYS`：能存能读，只是不列给面板
- 三个算子各一个可写面：`data_rsi` → `config/eval_cases/`；`harness_rsi` → `config/genomes/`；
  `model_rsi` 阶段一不开写。算子**不得改验证器**（scripts/、tests/、scorer、证据模型 —— G6）
- `core/meta/curriculum.py` - 横轴：下一轮跑哪个算子（调度统计，不是裁决），每次选择可审计
- `core/meta/supply.py` - 元层用**独立的** router 实例；RSI API 空位只登记意图
- **裁决永远是四值 `EvidenceTrustLevel`，不是分数**：验证由 harness 跑（`core/engineering_verification.py`），
  结论由 `classify_execution_evidence()` 给。提案者自报的成败只记为 `claimed_passed` / divergence
  （`scripts/check_verdict_independence.py` 守着）
- `core/verification_ladder.py` - 改了什么只验受影响的：`python scripts/select_affected_tests.py <文件…>`
- 热路径模块（openclawd / command_router / desktop_presence_runtime / presence_line / …）**不得 import core.meta**（G10）

### 提示词与 Agent 供给
- `core/genome.py` + `config/genomes/<name>/` - 系统提示词与 Agent 模板提示词**不在代码里**。
  合并语义：缺省＝继承、`null`＝删除、空串是值（被拒）。优先级：显式参数 > `GALAXY_SYSTEM_PROMPT` >
  `GALAXY_GENOME` > `config/genomes/active.json` > default。default 与原硬编码逐字节一致（G9）
- `core/agent_supply.py` - AgentConfig 的三格**需求**声明（model_preference / modality_required /
  locus_constraint，只能是枚举，不点名供应商 —— G13）→ `SupplyDecision` 绑在 Agent 上；
  供不上就报（G14）。`GALAXY_AGENT_SUPPLY=off|shadow|on`，默认 on（没声明需求的 Agent 什么都不算、行为照旧）

### 结果真相与会话迁移
- `core/truth_chain_recovery.py` - task_result 真相链没收口时：后台**只重跑失败的步骤**一次，仍不收口就进隔离队列
  （落盘 `$GALAXY_DATA_DIR/isolated_results.json`，`GET /api/v1/results/isolated`，面板「全部设置」最上面）。
  回答不受影响 —— 所有者的决定是「自动重试，失败再隔离」，**不拒收**。条目不止一类（`kind`：`task_result` / `computer_use`，
  别的类登记重跑器 `register_rerunner`）。人的三个动作：再试一次 / 认可（`.../accept`）/ 知悉；运维的「重开 / 确认 / 驳回闭环」
  落的就是这三个（`core/pr4_operator_action_governance.py::_settle_closure_in_queue`），队列里没有这条就照实回 failed
- `core/session_migration.py` - 会话迁移的**唯一**入口（D3）。核心 REST、网关 REST/WS、安卓桥都调它；它先找会话在哪个
  存储（核心 `core.session_manager` / 唤醒建的漫游 `SessionRoamingManager`），**两个存储不合并**。
  `core/routes/sessions.py::migrate_session_via_canonical_manager` 只是旧名转发

### 入口分流与参与方
- `core/presence_line.py` - **只有电脑这边发起的请求进桌面三态**（本机感官、桌面控制面、桌面外壳声明
  `client_surface=desktop_shell` 的对话、带本机标识或不带设备号且连接来自本机的请求；电脑发起的跨设备/混合任务
  也算）。其余——任何别的设备、别的机器、智能体自己的定时心跳——都不进：直接交给智能体，不在电脑上朗读或
  边生成边念；真在本机落手时才交还桌面（回答仍归发起方）。这是架构，**没有开关**。自主工作用
  `DesktopPresenceRuntime.autonomous_session(kind)`；`GET /api/v1/agent/activity` 列出全部请求（含不进三态的）
- `core/ambient_governance.py` - **常驻注意力循环的治理**（借自 Comma 对后台循环的约束）：自发开口 / 委托每小时额度（`GALAXY_AMBIENT_SPEAK_PER_HOUR` / `GALAXY_AMBIENT_DELEGATE_PER_HOUR`）、决策 / 转写 / 委托各有期限、失败留痕（≤32 条）。超额与超时**一律说得出原因**，不静默、不自动重试；只有 SPEAK 出声、进对话。`GET /api/v1/presence/ambient-status`，面板打开时提示「后台任务没做完」。并发上限 / 按来源配额不在这里，那是 `core/request_admission.py`
- **对话主线只在电脑这边的对话里选**（语音 / 自发开口 / 自发委托 / 面板重开读的那一条，`SessionManager.get_primary_session_id`）：建会话时记 `metadata["origin_device"]`（谁起的头），判据 `core.presence_line.session_is_desktop_thread` —— 不看 `devices`（别的设备往里写话会被 append 进去）。手机 / 手表各有各的对话；要接电脑这条主线就显式带它的 session_id 或经 reconcile 认领，接进来仍是电脑的。是入口分流的另一面：三态管表达，这里管上下文
- `core/participant_admission.py` - 非安卓设备的通用接入（注册 → 进 mesh → 提交任务），
  全程不经安卓命名模块。`core/participant_truth_ingress.py` - 参与方真相的通用入口（P3）
- `core/runtime/__init__.py` 是 PEP 562 **惰性**再导出：导入 `core.runtime.*` 子模块不会装进安卓运行时

### 语音
- `core/speech_output.py` - "说"的权威：引擎链选择 + 失败降级。公开入口
  `speak_response()`（说）与 `synthesize_to_file()`（只合成不播放，供 HTTP 接口）
- `core/modality_bridge.py` - **"听"的收口**：`transcribe_b64()`。B 档原生后端在线时
  让全模态模型自己听，否则回落 Whisper/SenseVoice。**不要绕开它直连 ASR**——
  该模块文档记录过绕开的真实后果（语音循环直连 Whisper，"原生听"从未生效且无报错）
- `core/tts/compute_fit.py` - 引擎与本机算力的**事前**匹配预检。只告知不改选；
  显式选择永远被尝试。注意：本仓引擎绝大多数是 CPU 设计，真正吃算力的只有 indextts
- `core/tts/watermark.py` - 克隆音色的 AudioSeal 不可听水印（默认 `cloned_only`）。
  `GALAXY_TTS_WATERMARK_STRICT=1` 时打不上水印即丢弃音频
- `core/routes/openai_audio.py` - OpenAI 兼容端点 `/v1/audio/{speech,transcriptions,capabilities}`。
  说走 speech_output、听走 modality_bridge，**不另起一套引擎选择**

### 论文检索：本机 arXiv 文献库
- `core/arxiv_library.py` - 元数据整份在本机（HF `secemp9/arxiv-complete` 的 `metadata`，1.6 GB，固定版本），SQLite FTS5（BM25）+ 分类 / 日期字段过滤；全文按需取一篇缓存一篇（2 GB 封顶）。导入 / 每天 OAI-PMH 增量在 `core/arxiv_sync.py`（后台线程，可问进度）
- `core/arxiv_client.py` - arXiv 的**唯一**出口：https、全进程每 3 秒最多一次、单连接（arXiv 使用条款）。**别再直连 export.arxiv.org**（`tests/test_arxiv_local_library.py` 守着）
- 工具在 `core/academic_tools.py`（`academic__arxiv_search / arxiv_read / arxiv_library`，以及原来的 search / ingest / recall 的定义）；会下东西的只在人发起的回合里，70 GB 全文分片要 `confirm`

### 启动横幅与卡顿
- 电脑没加入网络、也没开任务派发时不起 NATS —— 这是对的状态，不算降级；mDNS 广播不分模式，没配 headscale 时不入 tailnet 只给一行说明（`launcher/bus_phase.py`）；节点进程活着只是慢，说「还在起来」不算降级
- `core/loop_stall_watch.py` - 事件循环停跳 0.5 秒以上时记下卡在仓库哪几行、最里面卡在库的哪一行、同一时刻别的线程在 import 什么（循环线程可能只是在等 GIL）。日志里「一批请求同一毫秒一起慢」先看它那一行
- 本机 Ollama 超时不重发（`core/local_llm_policy.py`）：慢不是故障，重发等于从头再算
- 基础设施那一行（Docker / Podman）按各服务此刻的状态说（`launcher/compose_health.py`）：`compose up -d` 退出码 0 不等于已就绪；起不来的点名。
  起哪几个也在这里定（`infra_services()`）：本地模式不起 nats 容器（与 `nats_wanted()` 同一判据）；redis / qdrant / neo4j / mongodb 的端口只绑 127.0.0.1
- **控制台只上结论和错误**（`core/console_log.py`）：WARNING 是过程诊断，进 `logs/lumiv.log`，`-v` 才上屏；写控制台在专门的线程里（Windows 控制台被选中文字时挂起写入，曾卡住事件循环 13.8 秒）。别再往控制台 `print` 诊断
- 事件循环里不 import、不跑子进程：周期清扫不替没人加载过的模块 import（`core/periodic_maintenance.py::_loaded`）；FastAPI 的路由校验模型在网关起来前由旁边线程先建（`launcher/services.py::_warm_routes`）
- HF 下载源探测（`core/hf_endpoint.py`）并发、每个 6 秒、两轮；语音识别模型没下下来时后台重试、下好自动开启
- 「一个模型都没配」是状态不是故障：`core/llm_unavailable_reply.py::note_nothing_configured` 每 10 分钟提醒一次；全面排查每一轮的结果与待办在 `docs/SYSTEM_STATUS.md` 6.20

### API 层
- `core/api_routes.py` - REST API 和 WebSocket 路由（挂 `core/routes/*`）
- `galaxy_gateway/app.py` - 设备网关；规范的设备 WebSocket 入口 `/ws/device/{device_id}` 在 `galaxy_gateway/routes/websocket.py`
- 原 `dashboard/` WebUI 后端已退役（`docs/DASHBOARD_RETIREMENT_AND_MIGRATION.md`），不要再找它

### UI 层
- `electron/` + `electron/renderer/panel/src/` - 桌面外壳与面板（纯 TS，只认 WS 的 `payload.render`，见 `docs/RENDER_CONTRACT_DIRECTION.md`）
- `core/desktop_presence_runtime.py` - 桌面三态运行时（silent / liminal / manifest）
- **三只桌宠是同一只**（面板 `panel/src/ui/pet.ts`、覆盖层 `renderer/app.js`、右下角托盘 `windows_service/pet_icon.py`）：推导只有一份 `electron/renderer/pet_state.js`（托盘是 Python，跑同一张用例表 `pet_state.cases.json`），样子三处逐个相等（`tests/test_every_pet_is_the_same_pet.py`）。托盘与后端同进程，经 `core/presence_fanout.py` 直接收在场桥广播的同一份 `payload.render`；感知那几位（隐私暂停、在不在收）变了，桥每秒核一次、变了就广播
- **面板与覆盖层的长连接只有一份** `electron/renderer/live_socket.js`（保活 ping/pong、半开连接认得出来、连接超时、退避加抖动、网回来立刻重连），别再各写一份重连；面板的 HTTP 请求一律过 `transport.ts` 的 `fetchT`（读有期限且重试一次，写不重试，本来就慢的不设期限）
- `core/island_cards.py` - **灵动岛上的卡**（借 WinIslands 的上岛推送）：这台电脑上刚发生、人该余光知道的事（桌面操作第几步 / 核对结论 /
  有结果没收口 / 有设备在等你同意）。一张卡一个 id 原地更新、分先后、会过期、只放类型化短字段、不改岛的长短；推 WS `type="island"`
  整份队列，覆盖层刚连上补发（`core/presence_fanout.py`）。推卡用 `post_card` / `remove_card`（永不抛出）；**别往岛上放原始结果、截图、参数**。
  岛本身对齐 winsland（adityasrivastava5098/WinIsland）：岛上写什么、点了做什么在 `electron/renderer/island.js`（`IslandView`：卡片 / 在说话的声波 /
  「已复制」/ 动态↔感知两页 / 那组弹簧），`app.js` 只管它在三态里多大；排法是桌宠贴左端、字居中、尾巴贴右端，宽度跟着内容走。**只有一座岛**
  （旁边不挂放点的小岛），**点用面板那套光和深度、不用颜色**（`data-light` on/part/off），颜色只取面板的 `--a-pale` / `--bad`。剪贴板提示在
  `electron/clipboard_watch.js`（只发类别，原文不出主进程）。指针在岛上时窗口才接鼠标。桌宠不归岛管
- `core/rehearsal_panel_push.py` - 阈限态推演每一步推 WS `type="rehearsal"` 帧，面板 `ui/rehearsal.ts` 画出来
  （StateEventBus 的 `skill.*` 到面板只触发设备清单推送，步骤内容走的是这一帧）
- **事件循环里不跑同步聚合**：`core/routes/panel.py::build_panel_feed` 在工作线程里算、并发读取共用一次计算；面板只要「相位/在场强度/一致性」三个字段，走 `build_presence_slice()`，**不要**为了它去跑 18 段的 `build_unified_panel_payload`。麦克风采集的 AEC/VAD 在 `AudioIngestPipeline` 的专用单线程里算（回调仍回到事件循环）。真机上这两处曾让感知帧、音频、对话流请求成批变慢
- **设置页每一行的中文名、下拉每一档的中文名**在 `core/routes/config_labels.py`（`LABELS` / `OPTION_LABELS` / `HINTS`），由 `/api/config/all` 带给面板；行首画中文名、环境变量名在悬停提示里。**新增一个会列在面板上的配置，不补这张表 `tests/test_every_listed_setting_has_a_chinese_name.py` 会红**。整档按钮的主键（`CONFIG_BUNDLES[*].primary`）在 `/all` 里标 `bundle`，设置页不再摆第二个开关；取值有限的字符串键（`auto/1/0`）在表里登记档位后按下拉画。**`/api/config/all` 不下发密钥的值**（后端听 `0.0.0.0`，这个 app 没有网关那层全局 Bearer 中间件：路由组都挂 `_auth_deps`，不带令牌能调的写接口只剩 `tests/test_lan_cannot_drive_this_computer_without_a_token.py` 的 `OPEN_BY_DESIGN`、能读的只剩同一文件的 `PUBLIC_READS`（健康检查 / `/metrics` / 客户端配置发现 / OAuth 登录），新加接口忘了挂鉴权那两条测试会红）：密钥类只给掩码 / 空串，写回的掩码当没改；「什么算密钥」与面板 `ui/settings.ts` 的 `SECRET_RE` 是同一条（`tests/test_settings_never_send_secret_values.py`）
- **「调数据方式」的参数（回声消除、并发 / 熔断常数、各种超时与窗口、`auto/1/0` 档位……共 102 个：86 个数字、14 个档位、2 个音色名）不上面板**：它们多半是自适应算法自己的常数，人会说的是效果。登记在 `core/tuning.py` 的白名单里（每个键有硬范围），由智能体的 `tuning__list` / `tuning__set` 按人的话调：只在人发起的回合、放大自主度的方向要人点头、不碰会删数据的键、留痕（`tuning_log.jsonl`）、可 `reset` 一句话撤销。**新增这类参数：登记进 `_NUMERIC` / `_CHOICES`（档位，开关也按两档）/ `_NAMES`（音色名这类一小段名字），别往面板上摆一行**；登记的出厂值必须等于代码里的默认值（`tests/test_tuning_knobs.py` 核对）；读取点在导入时的要登记进 `_AT_IMPORT`（改了要重启）
- **面板上不列的另两类设置**（`core/routes/panel_builtin.py`，`GET /api/config/all` 不下发、「保存设置」不往 `.env` 里钉默认值，但仍登记、`POST /api/config` / `.env` / 环境变量照旧能用）：**内置键 90 个**（路径、内部服务地址与端口、型号与规格、固定的严格默认、运维逃生口——有一个对的默认，人填错只会弄坏），**跨设备专属键 6 个**（总线地址 / 联邦 / 本机设备名 / 网格口令 / 本机传输顺序……只在 `core.system_mode.cross_device_requested()` 为真时才列；自建内网与 TURN / STUN 不在此列，手表手机连智能体要用）。**新增一个键，先回答它属于哪一类**：留在面板（用户真有取舍）/ 对话里调（`core/tuning.py`）/ 内置（加进 `BUILTIN_GROUPS`）/ 跨设备专属。**登记表的默认值必须等于代码里的默认值**（`tests/test_panel_builtin_keys.py` 逐个扫描核对；曾抓到 `CORS_ALLOWED_ORIGINS` 登记成 `*`，点一次保存就写成「任何网页都能带凭据调本机接口」），**路径默认一律随数据总目录走**（`core.data_paths.data_path_or_legacy` / `runtime_file`：数据目录下没有、旧位置有数据时继续认旧位置，不把已有的记忆 / 账本 / 装进来的项目甩在后面）；**没有任何代码在读的键不许登记**（同一份测试扫描）
- **新增布尔开关要先回答「用户真有取舍吗」**：`core/routes/panel_switch_policy.py` 给每个布尔开关一个去处（`panel` 留在面板 / `builtin` 内置、默认开、不该有人关 / `ops` 开发运维逃生口 / `member` 并进某个整档按钮，随主键一起写，见 `core/routes/config_bundles.py` 的 `members`：判据是「主键关、它开」有没有意义），`tests/test_every_switch_has_a_disposition.py` 盯着；清单见 `docs/PANEL_SWITCHES.md`（脚本生成）。注意「保存设置」会把登记表的默认值整体写进 `.env` —— 登记表默认值必须与代码默认一致
- `core/ambient_yield.py` - 自发注意力循环给用户让路：用户请求在跑不碰模型、调用进行中用户来了就取消（Ollama 随之停掉生成）、用时 T 秒后歇 3T 秒。判「人在等」用 `core.presence_line.foreground_request_active`（后台自发来源与常驻在场不算）
- **面板窗口的外形由系统裁**（`PanelStage.shapeRects` → `setShape`）：Windows 上面板窗口的透明不一定生效，画布外、圆角外不能靠页面透明
- **面板是一整张画布**：桌面外壳里按 `electron/renderer/panel_stage.js` 的 1200×700 排一次版，窗口只决定整张放多大（`panel/src/stage.ts`）；面板窗口 `thickFrame: false`（带粗边框时 Windows 沿窗口矩形描一圈方白边），拉伸由四边四角的手柄发起、主进程锁宽高比改大小。**别再写按视口重新排版的样式**（`tests/test_the_panel_scales_as_one_piece.py`）
- 任务栏 / 窗口 / 快捷方式的应用图标由桌宠现画：改了桌宠的样子或颜色，跑 `python scripts/render_app_icons.py`
- 面板窗口只能有它自己的圆角：桌面外壳里 `html[data-shell='desktop']` 的画布底是透明的（`index.html` 同步脚本设置），否则 `body` 的渐变会铺满窗口矩形、圆角外多出四个方角。`dist/` 是提交进仓库的产物，改样式后要 `npm run build`
- `enhancements/clients/windows_client/run_ui.py` 是**硬禁用的桩**，只会发一条弃用警告；原先写在这里的
  `scroll_paper_geek_ui.py` 不存在

## 消息协议

### 设备消息格式
```json
{
  "type": "command|response|heartbeat|ack|event|error",
  "action": "操作类型",
  "payload": { "数据" },
  "message_id": "消息ID",
  "timestamp": 时间戳,
  "device_id": "设备ID",
  "correlation_id": "关联请求ID"
}
```

### 消息类型
| 类型 | 用途 |
|------|------|
| command | 发送命令 |
| response | 响应命令 |
| heartbeat | 心跳保活 |
| ack | 确认消息 |
| event | 事件通知 |
| error | 错误报告 |

## API 端点索引

### 设备管理
- `POST /api/v1/devices/register` - 注册设备。**陌生设备不带凭据来登记不直接进 UDM**：记成接入候选（`core/routes/_self_register.py` →
  `core/device_onboarding/join_paths.py::SelfRegisteredPath`，回 202），主人在面板「全部设置」最上面「等你同意的设备」点「接入」才写进去；
  鉴权关着、带主人令牌、本来就是成员的照旧直接登记。旧的 `/api/devices/register` 同一条规则
- `GET /api/v1/devices` - 列出设备
- `GET /api/v1/devices/discover` - 发现设备
- `DELETE /api/v1/devices/{id}` - 注销设备

### MCP 管理
- `GET /api/v1/protocols/mcp` - 列出服务器
- `POST /api/v1/protocols/mcp/load` - 加载服务器
- `DELETE /api/v1/protocols/mcp/{name}` - 卸载服务器
- `GET /api/v1/protocols/mcp/{name}/tools` - 列出工具
- `POST /api/v1/protocols/mcp/{name}/call` - 调用工具
- `POST /api/v1/protocols/mcp/{name}/reload` - 重载服务器

> 前缀是 `/api/v1/protocols/`，不是 `/api/v1/mcp/`。本节原先写的 `/api/v1/mcp/*`
> 三条**从未存在过** —— 声明它们的 `core/api_loader.py` 是一份未挂载的重复实现
> （定义了 `APIRouter()`，但全仓没有任何 `include_router()` 引用它），已删除。
> 真正提供这些端点的是 `core/routes/protocols.py`，由 `core/api_routes.py` 挂载；
> 两者底层都调用同一个 `core.mcp_loader`。

### 技能管理
- `GET /api/v1/protocols/skills` - 列出技能
- `POST /api/v1/protocols/skills/load` - 加载技能
- `POST /api/v1/protocols/skills/{name}/execute` - 执行技能
- `DELETE /api/v1/protocols/skills/{name}` - 卸载技能
- `POST /api/v1/protocols/skills/{name}/reload` - 重载技能

只读概览另有 `GET /api/v1/system/mcp` 与 `GET /api/v1/system/skills`。

### 参与方（非安卓设备）
- `POST /api/v1/participants/register` - 按设备自己的声明接入（自带入口令牌校验）
- `POST /api/v1/participants/{id}/tasks` - 已接入的参与方提交任务
- `POST /api/v1/participants/{id}/heartbeat` / `.../disconnect` - 保活与主动离开（写安卓心跳/断连写的同一批模块）
- `GET /api/v1/participants` - 列表（需 API 鉴权）

### 没收口的结果（真相链隔离队列）
- `GET /api/v1/results/isolated` - 补跑后仍没收口的结果（只有类型化字段，原始结果不外露）
- `POST /api/v1/results/isolated/{key}/retry` / `.../accept` / `.../dismiss` - 再试一次（只重跑失败步骤；Computer Use 那类在后台做，先回 `retrying`）/ 认可（人认它做完了）/ 知悉（判它没做成）

### 灵动岛
- `GET /api/v1/presence/island` - 岛上此刻的卡（排好先后；覆盖层平时走 WS `type="island"` 帧）
- `DELETE /api/v1/presence/island/{id}` - 撤掉一张（岛上点「知道了」）

### 智能体活动
- `GET /api/v1/agent/activity` - 智能体正在处理的全部请求：发起方、是否在桌面三态里、相位（需 API 鉴权）

### WebSocket
- `/ws/device/{device_id}` - 设备连接
- `/ws/status` - 状态推送

## 常用操作

### 启动服务
```bash
python main.py                # 启动系统（权威入口）
# 服务编排在 launcher/services.py（GalaxyUnified），由 main.py 在 Phase 4-6 直接 import 调用；它没有自己的 CLI
```

容器：根目录 `docker-compose.yml`；`deploy/compose/{full,production,kimi}.yml` 里的相对路径按**文件所在目录**解析，
指向仓库根的一律写 `../..`（`tests/test_deploy_surfaces_resolve.py` 守着）。镜像要拷哪些目录由
`tests/test_container_images_ship_what_they_run.py` 按 import 关系核对 —— 新增顶层包被 core 顶层 import 时，Dockerfile 要跟着拷。

### 运行测试
```bash
python -m pytest tests/                                   # 全量（CI 用 Python 3.11）
python scripts/select_affected_tests.py <改过的文件…>      # 只跑受影响的
python main.py --check-only                               # 不起服务，只查依赖/配置/核心模块/节点导入
python scripts/unwired_inventory.py --write               # 刷新 docs/UNWIRED_CODE_INVENTORY.md（未接线/不可达代码逐类清单）
python scripts/unwired_inventory.py --check               # 核对 config/unwired_placement.json（安卓以外每个未接线函数的去处）与清单对得上
```
原先写在这里的 `test_system_real.py` 不存在。
包在 `try` 里的 `from 仓库模块 import 名字`，名字不存在不会报错，只会一声不响地退成「不可用」（第 4 轮扫出 19 处，含两个从没成功过的视觉接口）——
`tests/test_lazy_imports_name_things_that_exist.py` 全仓核对。

### 配置 API Key
```bash
cp .env.example .env
# 编辑 .env 填入 API Key
```

## 设备能力

### 自动检测的能力
- screen, touch, keyboard
- camera, microphone
- bluetooth, nfc, gps
- accelerometer, gyroscope

### 能力协商
设备注册时自动上报能力，服务端根据能力分配任务。

## 扩展指南

### 添加 MCP 服务器
1. 在 WebUI 中加载 MCP 服务器
2. 或通过 API: `POST /api/v1/protocols/mcp/load`（注意前缀是 `/protocols/`）

### 添加技能
1. 创建 `skills/your_skill/SKILL.md`
2. 系统自动加载

### 添加设备
1. 安装安卓 App
2. 配置服务器地址
3. 连接后自动注册

## 故障排除

### 无法连接服务器
- 检查网络连接
- 检查防火墙设置
- 确认服务器地址正确

### 设备未注册
- 检查 WebSocket 连接状态
- 查看服务端日志
- 重启 App 和服务端

### UI 自动化不工作
- 开启无障碍服务
- 授权悬浮窗权限
- 确保 App 在前台

## 版本信息

- 版本：v2.3.23，**唯一来源 `core/version.py`**。横幅、`--version`、`core`/`galaxy_gateway` 的 `__version__`、状态接口、镜像标签、启动脚本、npm 包、README 都从这里取或由 `tests/test_version_single_source.py` 核对 —— 改版本只改那一处
- Python：**3.11**（CI 与镜像唯一验证过的版本；更低版本未经验证）
- Android: 7.0+

## 相关文档

详细文档请参考：
- `docs/SYSTEM_STATUS.md` - **当前系统状态（权威）**
- `README.md` - 项目说明
- `docs/README.md` - 文档索引（标明哪些是现行、哪些是历史快照）
