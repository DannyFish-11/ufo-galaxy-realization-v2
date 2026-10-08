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
- `GALAXY_DATA_DIR` - 运行时数据目录（缺省仓库 `data/`）。**所有**持久化状态都认它，设备注册表也不例外 —— 新加的持久化点用 `core.data_paths.data_path(...)`，别写死 `"data/..."`，`tests/conftest.py` 靠它把测试状态隔离到临时目录。面板「保存设置」重写 `.env` 时，登记表之外的手写行（compose 口令、端口、镜像站……）原样带回（`core/routes/config_env_preserve.py`）

### 设备管理
- `core/device_registry.py` - 设备注册和发现
- `core/device_communication.py` - 设备通信协议
- `core/device_control_service.py` - 设备控制服务
- **系统只有两个模式**：**本地模式**（`desktop-local`，默认，只用这台电脑）与**跨设备模式**（`desktop-cross-device`）。**「现在是哪个」只有一条规则、一个出处**：
  `core.system_mode.cross_device_requested()` —— `GALAXY_CROSS_DEVICE_ENABLED` 为真**或** `GALAXY_SYSTEM_MODE=desktop-cross-device`，任一即是，否则本地。
  网关开关、启动流程、桌面在场、启动自检、模式接口都调它，**别再自己推导**；`GALAXY_NATS_URL` 只说总线在哪，**不参与**判模式。面板上切换的只有「跨设备」一个按钮（同时写两个键）。
  「混合」不是模式，是一个请求的走法（`local` / `cross_device` / `hybrid`，跨设备模式里系统自动判）；`core/hybrid_executor.py` 的「混合执行」是单台设备内部的降级链，别混。
- **多机模式** = 跨设备模式的整体内容（跨设备 · 多设备并行 · 任务派发与分配 · NATS Agent），四层 + 共用 NATS 底座，定义见 `docs/MULTI_MACHINE_MODE.md`：
  派发走 `CommandRouter.route_envelope()` 按 `executor_target_type` 分三条路（`local` / `android_device`·`node_service` → 网关 `DeviceRouter` / `go_worker` → `MasterBrain` → NATS → worker）。
  `GALAXY_MASTER_BRAIN_ENABLED` 默认关，且**只在跨设备模式里才起**（`master_brain_requested()`）：开了却在本地模式，启动日志说出原因；开了才拉起主脑、worker 消费循环、MCP over NATS。
- **模型只能请求、不能决定**打开跨设备模式：本地模式下的工具 `devices__request_cross_device`（`core/device_onboarding/mode_request.py`）只会问人；批准走设备接入已有的人在环，
  `GALAXY_ONBOARDING_AUTO=approve` 对它无效，后台自发回合连提出都不行；批准后走面板按钮同一个写入函数，要重启才完全生效

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
  回答不受影响 —— 所有者的决定是「自动重试，失败再隔离」，**不拒收**
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

### API 层
- `core/api_routes.py` - REST API 和 WebSocket 路由（挂 `core/routes/*`）
- `galaxy_gateway/app.py` - 设备网关；规范的设备 WebSocket 入口 `/ws/device/{device_id}` 在 `galaxy_gateway/routes/websocket.py`
- 原 `dashboard/` WebUI 后端已退役（`docs/DASHBOARD_RETIREMENT_AND_MIGRATION.md`），不要再找它

### UI 层
- `electron/` + `electron/renderer/panel/src/` - 桌面外壳与面板（纯 TS，只认 WS 的 `payload.render`，见 `docs/RENDER_CONTRACT_DIRECTION.md`）
- `core/desktop_presence_runtime.py` - 桌面三态运行时（silent / liminal / manifest）
- `core/rehearsal_panel_push.py` - 阈限态推演每一步推 WS `type="rehearsal"` 帧，面板 `ui/rehearsal.ts` 画出来
  （StateEventBus 的 `skill.*` 到面板只触发设备清单推送，步骤内容走的是这一帧）
- **事件循环里不跑同步聚合**：`core/routes/panel.py::build_panel_feed` 在工作线程里算、并发读取共用一次计算；面板只要「相位/在场强度/一致性」三个字段，走 `build_presence_slice()`，**不要**为了它去跑 18 段的 `build_unified_panel_payload`。麦克风采集的 AEC/VAD 在 `AudioIngestPipeline` 的专用单线程里算（回调仍回到事件循环）。真机上这两处曾让感知帧、音频、对话流请求成批变慢
- **设置页每一行的中文名、下拉每一档的中文名**在 `core/routes/config_labels.py`（`LABELS` / `OPTION_LABELS` / `HINTS`），由 `/api/config/all` 带给面板；行首画中文名、环境变量名在悬停提示里。**新增一个会列在面板上的配置，不补这张表 `tests/test_every_listed_setting_has_a_chinese_name.py` 会红**。整档按钮的主键（`CONFIG_BUNDLES[*].primary`）在 `/all` 里标 `bundle`，设置页不再摆第二个开关；取值有限的字符串键（`auto/1/0`）在表里登记档位后按下拉画
- **新增布尔开关要先回答「用户真有取舍吗」**：`core/routes/panel_switch_policy.py` 给每个布尔开关一个去处（`panel` 留在面板 / `builtin` 内置、默认开、不该有人关 / `ops` 开发运维逃生口 / `member` 并进某个整档按钮，随主键一起写，见 `core/routes/config_bundles.py` 的 `members`：判据是「主键关、它开」有没有意义），`tests/test_every_switch_has_a_disposition.py` 盯着；清单见 `docs/PANEL_SWITCHES.md`（脚本生成）。注意「保存设置」会把登记表的默认值整体写进 `.env` —— 登记表默认值必须与代码默认一致
- `core/ambient_yield.py` - 自发注意力循环给用户让路：用户请求在跑不碰模型、调用进行中用户来了就取消（Ollama 随之停掉生成）、用时 T 秒后歇 3T 秒。判「人在等」用 `core.presence_line.foreground_request_active`（后台自发来源与常驻在场不算）
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
- `POST /api/v1/devices/register` - 注册设备
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
- `POST /api/v1/results/isolated/{key}/retry` / `.../dismiss` - 再试一次（只重跑失败步骤）/ 知悉

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
