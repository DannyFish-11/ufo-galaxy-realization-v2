# 系统现状（2026-09-27 复测，2026-09-28 更新）

> **这是当前状态的权威文档。** docs/ 下其余几十份状态、审计、成熟度文档（清单见第 9 节）都是**历史快照**：
> 它们在 2026-08-05 随仓库一起导入，之后没有跟着代码更新过。凡与本文冲突的，以本文为准。
>
> 本文只写**复测过的事实**，不打分。每条结论落在四档之一：
>
> | 档位 | 含义 |
> |---|---|
> | **实测可用** | 这次真的跑过（启动进程、真实 HTTP 请求、真实 docker 构建），结果符合预期 |
> | **测试钉住** | 代码在、接上了，有测试证明行为；这次没在真实环境里跑 |
> | **结构在、未验证** | 代码和契约都在，但没有经过真机/多设备验证；运行时自己也这么登记 |
> | **未做 / 缺口** | 设计要求了，代码里没有；或者有但已知是断的 |
>
> 复测基线：`main` @ `6489ff6`，外加 PR #1649 的修复（第 6.1–6.3 节）；2026-09-28 按所有者的决定又做了一轮
> （第 6.4 节）。每节末尾附复测命令。

---

## 0. 结论

**完成度：单机主干已经闭合，并且真跑得起来。**
在没有配置任何 API Key 的干净环境里，`python main.py --backend` 约 45 秒就绪。自报「4 正常 · 7 降级」，
每一项降级都说清楚了缺什么、怎么装。11 个只读接口全部返回 200。没配 Key 时，对话会明确告诉用户
「AI 服务不可用，请检查 API Key」，不会崩。桌面三态和入口分流在真实 HTTP 上复测通过。
跨设备、多设备和联邦这三块代码都在，但**没有经过真机验证**，运行时自己也把它们登记为
`structural_only` / `experimental`。

**完善度：主路径扎实。复测查出来的断点这次已全部修掉，剩下的需要决定或真机（第 7 节）。**
主分支上所有的 CI 门都是绿的，唯独 **Supply-Chain：三个容器镜像一个都构建不出来**，
而且就算构建出来，其中两个也跑不起来。从 2026-08-31 起，这条工作流在 main 上每周的定时运行都是红的
（至少连续 4 周）。PR 上却一直显示绿：在 PR 上它只跑哈希校验和节点报告两步，构建镜像那一步
只在 push 和定时运行时才跑。所以红灯只出现在 main 上，一直没人去查原因。
同样「写着但跑不起来」的还有：
- `deploy/compose/` 下的编排文件，路径全部指错了地方；
- prometheus 抓的端口是错的；
- 设备注册表不认数据目录；
- 版本号五处不一致；
- 测试会漏状态、留下常驻进程。

这些都已修复并加了守卫（第 6 节）。

**整体设计完成度：历史设计缺口基本关完，在建设计的阶段一已落地；最大的落差在文档。**
- 2026-04 审计列的 7 个关键缺口（G001–G007）：V2 侧 4 个已关（G001 按所有者选的「补跑 + 隔离」策略于
  2026-09-28 关闭），2 个由「静默」变成「可观测」（但仍不阻断），1 个属于安卓仓（不在本次范围）。
- 运行时闭合审计的 9 个残余缺口（GAP-512-001…009）**全部已在代码里关闭**，但清单里的描述一直没改，
  本次已更正。
- 后续路线图的 24 项里：17 项已落地（其中 A6 是以划边界的方式关闭的，A2/C1 有意保留了兜底路径；
  D3 会话迁移规范面 2026-09-28 落地），1 项有意保留（C4），5 项部分完成，1 项未做（C6）。
- 真相链不完整时，按所有者的决定**自动补跑一次、仍不收口就隔离待处理**，回答不受影响（第 6.4 节）。
- 最大的落差在文档：286 份 Markdown 里，最近两个月只改过 9 份。

---

## 1. 规模与形态

| 部分 | Python 文件 | Python 行数 | 说明 |
|---|---:|---:|---|
| `core/` | 1,008 | 548,148 | 主体。中位文件 387 行；133 个文件超过 1000 行，8 个超过 3000 行（最大 `openclawd.py` 10,330） |
| `tests/` | 1,322 | ~639,000 | 测试行数多于 core 本身 |
| `external/` | 807 | 204,021 | 外部代码原样入库（microsoft_ufo、agentcpm、channels、memos），不算本仓自写 |
| `nodes/` | 476 | 94,865 | 125 个 `Node_*` 目录 |
| `galaxy_gateway/` | 107 | 41,645 | 设备网关（规范的设备 WebSocket 入口） |
| `contracts/` | 28 | 27,182 | 跨运行时契约 |
| `launcher/` | 20 | 10,413 | 启动编排（`main.py` Phase 4–6 直接调用） |
| `electron/`（TS/JS） | 30 | 11,625 | 桌面外壳与面板 |

仓库共跟踪 4,973 个文件，其中 Python 3,975 个、约 163 万行；另有 286 份 Markdown 文档和 15 条 CI 工作流。
提交历史从 2026-08-05 开始，到本次复测时共 423 个提交。

**CI 只在 Python 3.11 上跑**（62 处 `python-version: "3.11"`，镜像也是 3.11）。README 写的 3.10+、AGENTS.md
原先写的 3.9+ 都没有被验证过。

```bash
git ls-files '*.py' | wc -l
git ls-files -z 'core/*.py' | xargs -0 cat | wc -l
```

---

## 2. 真实运行（本次实测）

### 2.1 启动

| 项 | 结果 |
|---|---|
| `python main.py --check-only` | 核心模块 16/16 可导入；节点 121/125 可导入。缺的 4 个都是可选依赖：`bs4`×2、`email-validator`、`asyncssh` |
| `python main.py --backend` | 约 45 秒 `/health/live` 返回 200；自报「就绪 · 4 正常 · 7 降级」 |
| 降级项 | 没有 Ollama（AI 大脑未就绪）、C 档跑不起来按 B 档启动、麦克风依赖缺失、Electron 覆盖层未启动、托盘缺 pystray、UFO 集成部分可用、L4 增强模块已加载但**未接入主循环**（自主性由常驻注意力循环承担）。**每一项都在启动输出里写明了原因和装法** |
| 首启副作用 | 会自动 `pip install` 5 个缺失包、从 `.env.example` 生成 `.env`、`npm install` Electron 依赖，**并拉起一个 NATS 服务** |

### 2.2 接口（真实 HTTP，带鉴权）

`/health/live`、`/health`、`/api/v1/agent/activity`、`/api/v1/system/status`、`/api/v1/devices`、
`/api/v1/participants`、`/api/v1/protocols/mcp`、`/api/v1/protocols/skills`、`/api/v1/system/mcp`、
`/api/v1/system/skills`、`/api/config/all` —— **全部返回 200**。

`POST /api/v1/chat` 在没配 Key 时 0.5 秒返回 `success: true`，回复是「还没有可用的 AI 服务：没有配置任何 API Key，
也没有检测到本地模型。请在面板「全部设置」里填一个 API Key，或者启动 Ollama 并拉取模型，然后再试。」
降级是明确的，不会崩溃。修复前这句是「所有 AI 服务暂时不可用（已尝试: ）」，括号里是空的，见第 6.3 节。

版本号：`/api/v1/system/status`、`/api/status`、OpenAPI 的 `info.version` 都是 `2.3.23`，启动总结卡是
「Galaxy L4 · v2.3.23」。修复后重启，`/api/v1/devices` 里不再有测试设备。OpenAPI 共 429 个路径
（其中约 420 个来自 `core/api_routes.py`，其余是启动器自己的 `/api/status` 等）。

### 2.3 入口分流：只有电脑发起的请求进桌面三态

用 `create_api_routes()` + uvicorn 起真实 HTTP，只把 LLM 的回复替换成桩，其余全走生产代码：

| 请求 | 进三态 | 桌面相位事件 | 在电脑上朗读 | 活动接口里的原因 |
|---|---|---|---|---|
| 非安卓参与方（iPad）注册 → 提交任务 → 心跳 → 断开 | 否 | 无 | 否 | `remote_source` |
| 桌面外壳发起 `/api/v1/chat/stream`（`client_surface=desktop_shell`） | **是** | liminal → manifest → silent | 是（边生成边念） | `desktop_shell` |
| 手机带自己的设备号走 `/api/v1/chat` | 否 | 无 | 否 | `other_device` |
| 智能体自己的心跳周期 | 否 | 无 | — | `agent_autonomous` |

流式响应的帧序列是 `phase, lockstep, meta, phase, delta, delta…`，锁步帧存在。
行为由 `tests/test_presence_line.py`、`tests/test_agent_runs_apart_from_the_desktop.py` 钉住。

2026-10-08 复查补了一处漏网的：**预演推演帧**（`core/rehearsal_panel_push.py`，面板阈限态里画的那一行行「模拟…」）此前不看请求从哪来，手机发起的请求只要走到预演，电脑面板上就会演它的推演。现在预演照常进行（认知不受分流影响），只在**电脑发起的请求**里才推给桌面面板；别的设备发起、中途在本机落手的请求，落手后交还桌面，之后的步骤照常推（与相位同一条规则）。`tests/test_rehearsal_panel_push.py` 钉住，去掉这处判断后该测试变红。

**对话主线也按设备分开了（所有者选的 A：各设备各有各的主线）**：对话主线（`core/conversation_mainline.py` → `SessionManager.get_primary_session_id`，语音回合 / 自发开口 / 自发委托 / 面板重开读的那一条）原先取「所有设备里最近活跃的真实对话」，手机发一句话电脑的主线就切到手机那段。现在建会话时记下**谁起的头**（`metadata["origin_device"]`，电脑上起头是空串，四个构造点共用的 `_apply_thread` 里记），主线只在电脑这边的对话里选（`core.presence_line.session_is_desktop_thread`）：

- 手机、手表（`wear_voice` 不带 session_id，按 `device::<手表id>` 另起并跨句复用）各有各的对话，说话不改电脑的主线；
- 别的设备要接电脑这条主线：显式带它的 session_id（`GET /api/v1/sessions/primary`），或经 `/api/v1/sessions/reconcile` 认领 —— 接进来后（`devices` 里多出手机 / 手表）它仍是电脑起头的那条，**所以判据看起头记录，不看 `devices`**；
- 手机起头、电脑后来也进了的会话，算电脑的；没记过起头的老会话（这条改动之前落盘的）判不出来，按原样算电脑的；
- 手表的另外两条路不受影响：回答一个**待决事项**（`human_input` → `pending_decision_registry.resolve`）本来就不产生对话轮次；`interruptibility` 是**信号**不是对话，照样喂给常驻注意力循环。
- 判据只看设备号：没带设备号的别的机器（浏览器直连）会话属主是 `device::default`，与电脑面板同一个属主，这一条这次没有动。

`tests/test_each_device_has_its_own_conversation_mainline.py` 8 条（把 `session_manager.py` 的改动去掉后 6 条变红）。

### 2.4 容器镜像

见第 6 节。修复前，三个镜像一个都产不出来；修复后，主镜像的全部 COPY 步骤都在真实 docker 里构建通过，
按镜像里实际拷进去的文件集合做导入扫描，零失败。

```bash
python main.py --check-only
GALAXY_API_TOKEN=t python main.py --backend --port 19000 --host 127.0.0.1   # 另开终端 curl
```

---

## 3. 验证体系的状态

| 项 | 结果 |
|---|---|
| 全量测试 `pytest tests/` | 修复后 **45,117 通过**，唯一 1 个失败已当场修掉（第 8 节）。复测前的 6 个失败都是测试隔离问题，已全部修复 |
| 仓库守卫 `scripts/check_*.py` | 导入边界、文件复杂度、证据锚点、可达性、裁决独立性、元层、接线、债务冻结、主线路由、工作流 YAML、遗留回归、语义锚定、Agent 供给声明、仓库卫生 —— **全部通过**。`check_codeql_ledger` 本地判失败，原因是本地没有 SARIF 文件；它只在 CI 里有意义，并且是有意设计成「找不到就判失败」 |
| 结论保鲜 `check_assessment_freshness` | 24/24 条结论新鲜（2026-09-27 新增 3 条：设备注册表认数据目录、版本号唯一来源、LEGACY_DISPATCH 告警；2026-09-28 新增 3 条：真相链补跑与隔离、config.json 那几维没有运行时读者、推演步骤到面板，并以 `session-migration-canonical-surface` 取代 `session-migration-has-no-canonical-home`） |
| 就绪报告 `generate_system_readiness_report.py` | 42/42 通过。**注意它只查「文件在不在、模块能不能导入」**，所以它绿着的时候，镜像照样构建不出来 |
| 可达性 | 3 个模块不可达（已登记基线） |
| 未接线 | 755 个公开能力没有生产调用方（基线 760 → 755：4 条早已接上的过期条目，加 2026-09-28 接上的 1 条）。是些什么东西见 `UNWIRED_CODE_INVENTORY.md` |
| 主分支 CI | CI、Engineering Guardrails、Node Governance、Dual-Repo Integration、CodeQL、Governance Gate 全绿。**Supply-Chain 自 2026-08-31 起每周定时运行都红**（最近一次 2026-09-26 run 36236799682），本次 PR 修复 |

```bash
for s in scripts/check_*.py; do python "$s" >/dev/null 2>&1 && echo "PASS $s" || echo "FAIL $s"; done
python scripts/check_assessment_freshness.py
```

---

## 4. 运行时自己登记的能力状态

来源：`core.canonical_capability_status.get_canonical_capability_status_registry()`，共 24 项。

| 状态 | 数量 | 能力 |
|---|---:|---|
| `active_mainline` | 14 | capability_report, continuous_host_perception, cross_device_dispatch, heartbeat, input_text, multimodal_ingest, offline_queue, reconnect, register, screenshot, swipe, tap, task_assign, task_result |
| `degraded` | 4 | local_ai, local_grounding, local_planner, on_device_inference |
| `experimental` | 3 | advanced_handoff, webrtc, webrtc_task_lifecycle |
| `structural_only` | 3 | federation, mesh, mesh_participation |

这张表是「运行时对自己的判断」，比任何文档都权威。mesh、federation 两块的引擎代码都在（见 5.3），
但运行时仍登记为 `structural_only`。要改成 operational，需要真机多设备的证据，不能靠补代码。

---

## 5. 设计完成度

### 5.1 在建设计

| 设计 | 结论 | 依据 |
|---|---|---|
| 元层与 RSI（`META_LAYER_RSI_ARCHITECTURE_CN_2026.md`） | **测试钉住**：阶段一的 M0–M7 全部落地 | 该文「落地状态」表，每一行都对应一个测试。总闸 `GALAXY_META_RSI` **默认 off**：是否默认打开由仓库所有者决定。`model_rsi` 阶段一不开写 |
| 入口分流 / 桌面三态（`core/presence_line.py`） | **实测可用** | 第 2.3 节 |
| 参与方通用接入（非安卓设备） | **实测可用** | 注册 → 提交 → 心跳 → 断开全链真实 HTTP 通过 |
| 设备接入平面 V1（`docs/architecture/DEVICE_ONBOARDING_PLANE_V1.md`） | **测试钉住** | `core/device_onboarding/` 共 15 个模块（taxonomy / join_paths / drivers / agent_tools / service…） |
| 渲染契约（`RENDER_CONTRACT_DIRECTION.md`） | **测试钉住** | 第七节列出的 5 个缺陷都已修；最后一个（推演逐步过程没有消费方）2026-09-28 补上 WS `rehearsal` 帧与面板那一段 |
| 面板表层收敛（`PANEL_SURFACE_CONVERGENCE.md`） | **部分** | 拓扑/可观测视图没有搬进面板。「两套配置写入链路没合并」经复核**前提不成立**：生效的只有一套（见第 6.4 节） |
| 节点 HTTP 安全契约（`NODE_HTTP_SECURITY_CONTRACT.md`） | **测试钉住** | — |

### 5.2 历史缺口复核

**2026-04 完成度矩阵的 7 个关键缺口**（`audit/completion_matrix.json`，逐条复核记录在每个缺口的 `rederived_2026_09_27` 字段）：

| 缺口 | 当时 | 现在 | 依据 |
|---|---|---|---|
| G001 真相链静默降级 | P0 | **已关**（按所有者选的策略） | 不完整的结果记进 `IncompleteResultLedger`；后台只重跑失败的步骤一次，收口了就撤账，仍不收口就进隔离队列（落盘、`/api/v1/results/isolated`、面板可见，可再试/知悉）。**不拒收**：回答照常先给用户 —— 这是所有者的决定（第 6.4 节） |
| G002 注册下游步骤静默降级 | P1 | **部分**：同上 | `registration.py` 逐设备记下失败的下游步骤，可查询；注册本身不因此失败 |
| G003 goal_result 缺真相链 | P1 | **已关** | goal_result 走 `UnifiedResultIngress`（含真相链）；ingress 不可用时回退为直接跑真相链 |
| G004 没有受理裁决 | P1 | **部分** | 逐条结果带 `acceptance_verdict`，缺省为 `unknown`，对应信任级 `provisional`，不再乐观地当成已受理；系统级裁决在 `core/system_final_acceptance_verdict.py`，执行证据分四档 `EvidenceTrustLevel`。HITL 审批没有成为必经门 |
| G005 安卓本地 LLM 可用性 | P2 | 不在本次范围 | 属于安卓仓 |
| G006 兼容 WS 路径真相链 | P2 | **已关** | 兼容 `/ws/device` 同样走统一 ingress，并且在受保护的跨设备模式下默认被挡 |
| G007 没有 E2E 集成测试 | P3 | **已关** | `tests/integration/` 下有 36 个文件，其中包括跨进程 WS E2E、多设备失败恢复 E2E |

**运行时闭合审计 GAP-512-001…009**：**全部已在代码里关闭**（001/002/004/006/007 由 PR-513 关闭；003/005/008 由 PR-514 关闭，
其中 008 是以划边界而非合并的方式关闭；009 由 PR-515 关闭）。`core/runtime_closure_audit._KNOWN_RESIDUAL_GAPS`
里的描述原来仍写着「尚未……」，本次已逐条改为「CLOSED by PR-5xx: 在哪里关的」，行数不变。

**后续路线图 A1–D6**：逐条状态见 `FOLLOWUP_IMPLEMENTATION_ROADMAP.md` 顶部的复核表。汇总：

| 结论 | 条目 |
|---|---|
| 已落地（17） | A1, A2, A3, A4, A6（划边界关闭）, B1, B2, B4, B5, C1（兜底有意保留）, C2, C3（指标 + 告警规则，本次补齐告警）, D1, D2, D3（2026-09-28）, D4, D6（V2 侧） |
| 有意保留（1） | C4：`galaxy_gateway/task_router.py` 仍在盘上，已登记为 LEGACY COMPAT 治理面；删不删是产品决定 |
| 部分（5） | A5, B3, B6, C5, D5 |
| 未做（1） | C6（`/ws/ufo3` 仍在） |

### 5.3 多设备这一块到底到了哪儿

代码层面，路线图 B 组要求的引擎基本都有了，只是名字和当初设计的不一样：
`mesh_session_progression_driver`（驱动会话状态）、`live_mesh_session_coordinator`、`live_mesh_runtime_engine`
（其中有参与方结果合并）、`mesh_session_persistence` / `body_mesh_persistence`（落盘与重启恢复）、
`formation_rebalance_engine`（编组重平衡）。

但是运行时把 `mesh`、`mesh_participation`、`federation` 登记为 `structural_only`，这个判断是对的：
这些引擎没有一个在真机多设备环境里跑过。**「代码写完」和「能用」之间，差的是真机证据，不是更多代码。**

---

## 6. 本次查出并已修复

### 6.1 三个容器镜像

2026-09-26 那次 Supply-Chain run（36236799682）里，三个镜像都失败了；从 2026-08-31 起每周的定时运行也都是红的。本地复现后逐一修复。

| 镜像 | 原因 | 修复 | 验证 |
|---|---|---|---|
| galaxy-main | `Dockerfile` 去 COPY 一个不存在的 `cli/`，构建在 COPY 处失败。就算删掉这一行，镜像里还缺 4 样东西：main.py 顶层 import 的 `entrypoint_role_contract.py`、Phase 4–6 import 的 `launcher/`、`core.perception` 顶层 import 的 `integration/`，以及 `core.system_completion_status` 顶层 import 的 `tools/architecture/`。缺了它们，CMD 一启动就 ModuleNotFoundError | 删 `cli/`，补上这 4 项，再加 `scripts/check_dependencies.py` | 真实 docker 构建：修复前在 `"/cli": not found` 处失败，修复后所有 COPY 步骤通过。按镜像实际拷进去的文件集合跑 `main.py --check-only` 通过，对 core/launcher/网关逐个模块导入，零失败 |
| galaxy-gateway | 网关镜像本身能构建，但缺 `contracts/`：网关的 37 个安卓处理器模块和 core 的一批模块在镜像里导入失败 | 补 `contracts/`、`integration/`、`tools/architecture/` | 同上，扫描零失败 |
| galaxy-node | `requirements.txt` 里的 pynput 在 Linux 上依赖 evdev，而 evdev 只有源码包；slim 镜像里没有编译器 | 装 `gcc` 和 `libc6-dev`（后者连带 `linux-libc-dev` 内核头） | 在 slim 镜像里复现了 evdev 构建失败；在带 gcc 和内核头的镜像里 evdev 构建成功 |
| SBOM 步骤 | 工作流同时写了 `outputs: type=docker,dest=…` 和 `load: true`，显式的 outputs 取代了 load，镜像只落成 tar、没进守护进程，下一步 syft 按 tag 找不到它 | 去掉 `outputs` | 用 docker-container 驱动的 buildx 在本地复现：旧写法镜像不在守护进程里，新写法在 |

防回潮：新增的 `tests/test_container_images_ship_what_they_run.py` 静态核对以下几点：
- 每条 COPY 的源路径都存在；
- 入口文件在镜像里；
- 镜像里所有**不设防的**本仓 import 都能在镜像里找到；
- 节点镜像带编译器；
- SBOM 这一步能找到它要扫描的镜像。

对修复前的文件运行这个测试，上面这些缺失会全部报出来。

### 6.2 部署编排与监控

| 问题 | 修复 | 验证 |
|---|---|---|
| `deploy/compose/` 下的 `full.yml`（`python main.py --docker-full` 用的就是它）、`production.yml`（部署文档里的生产入口）和 `kimi.yml`，把相对路径写成 `.`、`./core`、`.env`。Compose 按**文件所在目录**解析这些路径，结果都指向 `deploy/compose/`：116 个服务找不到 Dockerfile，`./core` 等挂载会拿空目录盖住容器里的代码，生产入口因为找不到 `env_file` 直接启动失败 | 所有指向仓库根的相对路径改成 `../..` | `docker compose config` 解析后，构建上下文和挂载源全部落在仓库根 |
| `config/prometheus.yml` 抓 `galaxy:8080` / `gateway:8000`，但服务实际都监听 9000；网关的指标出口是 `/gateway/metrics`（`/metrics` 在网关上是 404）。一个指标都没抓到过 | 目标改为 9000；网关改抓 `/gateway/metrics` | promtool：配置合法 |
| 路线图 C3 的告警这一半：`galaxy_legacy_dispatch_total` 有计数，没有告警 | 新增 `config/prometheus_alerts.yml`：`GalaxyLegacyDispatchUsed`（15 分钟内走到旧派发路径就告警）、`GalaxyTargetDown`；`production.yml` 把它挂进 prometheus 读规则的目录 | promtool：2 条规则识别到 |

防回潮：`tests/test_deploy_surfaces_resolve.py` 核对以下几点：
- compose 路径解析后真实存在；
- 抓取端口是服务在听的端口；
- 网关抓取路径真的存在；
- 告警引用的指标真的有代码在导出；
- 规则文件挂进了 prometheus 读的目录。

对修复前的文件运行这个测试，会有 6 项报红。

### 6.3 运行时与测试

| 问题 | 修复 | 验证 |
|---|---|---|
| 设备注册表路径写死成仓库的 `data/registered_devices.json`，是全仓唯一不认 `GALAXY_DATA_DIR` 的持久化点。测试注册的设备会写进真实注册表，复测时启动后列出过 106 台测试设备 | `core/routes/_shared.py` 改为跟随 `GALAXY_DATA_DIR`（没设时仍是仓库 `data/`，行为不变）。新位置还没有文件时，从旧位置读入一次，之后只写新位置，旧文件不删不改 | `tests/test_device_registry_follows_data_dir.py` |
| 版本号五处不一致：横幅和 `--version` 是 v2.3.21，`core`/网关的 `__version__` 是 3.0.0，状态接口是 2.0.0，镜像标签是 2.3.23，README 是 v10.0 | 唯一来源 `core/version.py`（2.3.23，取已出现过的最高版本号），Python 代码一律从这里 import；Dockerfile 的 LABEL、启动脚本横幅、三个 npm 包（用 `npm version` 改，锁文件同步）、README 由测试核对 | `tests/test_version_single_source.py`；`python main.py --version` → `Galaxy v2.3.23` |
| 没配任何 Key、也没有本地模型时，对话回「所有 AI 服务暂时不可用（已尝试: ）」，括号里是空的 | 一个都没试到时直接说缺什么、怎么补；试过但都失败时照旧列出试过哪些（`core/llm_unavailable_reply.py`） | `tests/test_llm_unavailable_reply.py`（含经过真实路由器的一条） |
| 测试顺序依赖：`test_config_schema_ui_parity.py` 先跑，后面 4 个视觉/密钥测试必红。根因是保存配置会把假 Key 写进 `os.environ`，并 reload 进程级 `UnifiedConfig` 单例；测试只隔离了文件 | 该测试的 fixture 同时隔离 `os.environ`，收尾后让单例从复原后的状态重新读一次 | 同样顺序连跑，52 个全部通过（修复前 4 个失败） |
| 测试遗留常驻节点进程：`GalaxyUnified.__init__` 会登记一个真的会起子进程的节点激活执行器（生产里正该如此），它是进程级全局，一直不撤。之后任何触发设备注册的测试都会拉起真实节点进程 | `tests/conftest.py` 在每个测试结束后把执行器复原成测试开始前的样子 | 复现序列之后残留节点进程数为 0（修复前为 2） |
| 网关 `/health` 报的 `version` 写死为 3.0.0 | 同上，从 `core/version.py` 取 | 同上 |
| 测试遗留后台重连客户端：`tests/test_a_laptop_joins_by_pairing.py` 起的真实 `DeviceClient` 测完不停，每 5 秒重连一次，持续整个会话；`tests/test_route_construction_is_offline.py` 进程级拦 `socket.connect`，把这些连接记到自己头上（本 PR 首次推送后 CI test-shard 4 因此红过一次） | 该文件每个测试结束都停掉客户端；离线用例只记本测试线程发起的连接（其它线程照常被拦，只是不记账） | 修复前：测完 11 秒内有 6 次后台连接；修复后为 0 次 |

### 6.4 2026-09-28：按所有者的决定做的

上一轮第 7 节列的待决事项，所有者给了答复：真相链「自动重试，失败再隔离」；会话迁移规范面、
面板配置写入合并、面板显示推演过程这三件要做；死代码「先确认清楚是些什么东西」再说。

| 事项 | 做了什么 | 验证 |
|---|---|---|
| 真相链不完整 | 后台延迟 5 秒**只重跑失败的步骤**一次（成功过的步骤不做第二遍）。补齐了就从账本撤掉；仍不收口就进隔离队列：落盘在 `$GALAXY_DATA_DIR/isolated_results.json`（重启后还在），`GET /api/v1/results/isolated` 可查，`…/{key}/retry`、`…/{key}/dismiss` 可再试或知悉，面板「全部设置」最上面一段显示（一条都没有时不占位置）。接口只给类型化字段，原始结果内容不外露。**顺带修了一处真问题**：回退路径上 1–3 步失败时，`TruthChainStepError` 会从 `handle_task_result` / `handle_goal_execution_result` 里直接抛出去，等待方拿不到结果、一直等到超时 —— 现在接住，回答照常先给出去 | `tests/test_truth_chain_recovery.py`（13 条，含「真相链抛错时等待方仍马上拿到结果」） |
| 会话迁移规范面（D3） | 新建 `core/session_migration.py`，四个外部入口（核心 REST、网关 REST、网关 WS、安卓桥）都调它。它先找会话在哪个存储里：核心会话走原来那套两阶段提交（逐行搬过来）；**唤醒事件建的漫游会话**交给 `SessionRoamingManager` 自己的两阶段提交 —— 以前网关 `GET /api/v1/sessions` 列的正是这些会话，拿同一个网关的迁移端点去迁却会 404，任何端点都迁不了它们。两个存储过同一道作用域判据；**不合并**两个存储。`core/routes/sessions.py` 的旧名保留为转发 | `tests/test_session_migration_canonical_surface.py`（9 条）；`tests/test_session_migration_consistency.py` 的 D 组改为钉新事实 |
| ↳ 顺带查出的两个问题 | ① `core/event_bridge.py` 日志写「SessionRoaming → EventBus 已连接」，挂的却是不存在的属性 `_on_session_migrated`（管理器调的是 `_on_migrated`），`SESSION_MIGRATED` 从没发出过；核心会话的迁移也从不发。现在两边都发，前端能收到。② 漫游会话落盘写死在 `~/.galaxy/session_roaming`，不认 `GALAXY_DATA_DIR`（测试每跑一次就往真实家目录写一批快照）；现在跟随，没设时仍是原位置，新位置没有文件时只读一次旧位置 | 同上 |
| 面板配置写入合并 | **复核后前提不成立，没有做「合并」。** `ConfigService` 写进 `runtime/config.json` 的 provider 开关、`native_multimodal_policy`、网络地址、安卓推理模式，运行时**没有任何读者**（仅有的读者 `validate()` 与 `model_topology/inventory_from_config` 自己也没有生产调用方）。生产里真正在写配置的只有一条：面板 → `POST /api/config`（非密钥进 `.env` 与进程环境，密钥经 `ConfigService.set_secret` 落 `secrets.env`）。把那几个开关接到面板上只会得到按了不起作用的按钮。真正生效的 provider/路由控制面板上都已经有。已如实改写 `PANEL_SURFACE_CONVERGENCE.md` 与 `core/operational_enablement_audit.py` 的说明。「有 Key 但先别用这家」的 provider 开关是新能力，所有者答复**不要** | 结论 `config-json-provider-dims-have-no-runtime-reader` |
| 面板显示推演过程 | `skill.invoked`（`kind="rehearsal"`）到面板只触发一次设备清单推送，步骤内容从没到过面板。新增 WS `type="rehearsal"` 帧（`core/rehearsal_panel_push.py`，只推类型化字段，工具参数与模拟响应不推），面板在对话区与输入条之间画出最近一次推演，每一行写明「模拟」还是「真查了（只读）」；发下一句话时清空。面板 dist 已重建 | `tests/test_rehearsal_panel_push.py`；`npm run build`（含 `tsc --noEmit`）通过 |
| 死代码 | **只清点，没删、没接。** 755 条未接线、3 个不可达模块逐类查清，写在 `docs/UNWIRED_CODE_INVENTORY.md`（可用 `python scripts/unwired_inventory.py --write` 重新生成）。其中「看得见但不生效」的几簇最值得先定：运行 SLO 指标的 13 个 `record_*` 没有生产调用方（`/metrics` 上那些计数恒为 0）；委托流持久化只接了读、没人写（重启后「从检查点恢复」走不到）。基线重记 760 → 755（4 条早已接上的过期条目 + 本轮接上的 `set_migration_callback`） | 同左 |

### 6.5 2026-10-04：所有者贴的两份真机启动日志里查出的

日志来自 Windows 真机（desktop-local 与 desktop-cross-device 各一次）。下面每一行都对着日志里的原句：

| 日志里的现象 | 根因 | 修复 | 验证 |
|---|---|---|---|
| `'PreflightReport' object has no attribute 'critical_findings'` | `system_orchestrator` 读的属性名写错了（实际叫 `criticals`），异常被泛化的 `except` 吞成一句「环境有欠缺」 | 改名 | `tests/test_preflight_sees_the_local_token.py` |
| 预检先红一行阻断「缺 `GALAXY_API_TOKEN`」，随后鉴权其实一切正常（`data/api_token.json` 已自签） | ① 预检在「签本机令牌」**之前**跑；② 鉴权开着时本机自签令牌就是身份，预检却把「没配共享口令」判成阻断 | Phase 3 先签令牌再预检；本机令牌已在时不再报阻断。`GALAXY_REQUIRE_API_TOKEN=true` 要的是共享口令，仍然阻断 | 同上（含「有本机令牌 / 没有 / 要求共享口令」三种） |
| 启动时约 100 条 `续跑重派失败 task=executor__Node_xx … resume payload unavailable` | 能力吸收把每个节点「能执行」投影进任务图成 `executor__<节点>` 节点，没有工具名也没有载荷、永远停在排队态；重启续跑把它们当待派发任务 | 投影节点不算可续跑任务（`resumable_nodes` / `resume_snapshot` 都跳过） | `tests/test_task_graph_durable_resume.py` 新增一条 |
| 每个请求一行 `认证成功: device_id=None`（604 行） | 按请求打 INFO | 降为 DEBUG | — |
| 停机时 `nats: encountered error` + `ConnectionRefusedError` 裸栈出现在「系统已停止」**之前** | Windows 控制台 Ctrl+C 同时发给 `nats-server` 子进程，它先于我们的停机流程死掉，客户端读到 EOF，nats-py 在我们静音它的日志之前就打了 ERROR | Windows 上让 `nats-server` 自成一个进程组，由 `stop()` 显式收 | `tests/test_startup_console_has_no_raw_stacks.py` |
| 就绪矩阵自检打一行 `capability gate HARD REJECT … smoke-device`（ERROR） | 自检故意造一次能力不匹配来验证严格模式会拒 | 自检调用点降到 INFO；真实调用点仍是 ERROR | 同上 |
| **面板卡顿**：`/api/perception/desktop/frame`、`/audio` 成批变慢（0.5~5 秒，同一时刻一批请求的耗时几乎相同），首次 `/api/v1/panel/feed` 11.5 秒，之后约每 30 秒一次 1~3 秒 | 事件循环被同步工作占住，同一进程里排队的请求一起变慢。三处：① `build_panel_feed` 是 async 函数，整份同步聚合直接在循环里跑，而且每次都**全量构建 18 段统一面板**（含系统现实检查点：一次构建里读盘恢复 mesh 会话 7 次、重算模型拓扑），只为取 3 个字段；Electron 每 30 秒一次的兜底对账就是日志里的 30 秒节拍。② 常驻麦克风采集每 100ms 一块的回声消除 / VAD / 特征提取在事件循环里算，AEC 首块还要现 import numpy 并建滤波器（日志里 3.3 秒，与 7 个请求的 3.33 秒吻合）。③ `OpenClawd.get_status()` 声明成 async 却一个 await 也没有，冷启动时在循环里做一串惰性 import | ① 聚合放工作线程，并发读取共用同一次计算；面板只取 3 个字段，走新增的 `build_presence_slice()`，不再跑全量。`/api/v1/panel/unified` 同样放线程。② 信号处理放专用单线程（块序不能乱），回调仍回到事件循环。③ 在工作线程里取 | `tests/test_panel_feed_does_not_block_the_loop.py`（聚合睡 0.4 秒时循环心跳不出现空洞）、`tests/test_audio_ingest.py` 新增两条。**在本沙箱按 Electron 的节拍（摄像头 + 屏幕每 2 秒、音频、面板轮询）回放负载：各接口 p50 15~27ms**；Windows 真机上的效果还没有实测 |
| 本地 gemma 一次决策 38~48 秒，用户发的「你好」排在后面，90 秒 `chat_stream 超时` | 自发注意力循环的 SILENT 决策不打冷却，场景一直在变就是一个调用接一个调用；Ollama 一次只算一个。整台机器的 CPU 也被占满，面板跟着卡 | 自发注意力给用户让路（`core/ambient_yield.py`）：用户请求在跑时不碰模型；调用进行中用户来了就取消这次调用（断开连接，Ollama 随之停掉生成）；一次调用用了 T 秒，之后至少歇 3T 秒。被挡下的那一拍记成「延后」，让路结束后补看一次 | `tests/test_ambient_yields_to_the_user.py`（10 条） |
| 面板窗口除了自己的圆角，四角还多出方形的角 | 窗口是透明的，但 `body` 的渐变背景（`html` 自己没有底）被当成画布底色铺满整个窗口矩形，圆角之外的四个角是方的、不透明的；另外透明窗口开着 `hasShadow`，系统阴影按窗口矩形画 | 在桌面外壳里把画布底去掉（`html[data-shell='desktop']`，由 `index.html` 里同步的内联脚本设置，避免闪一下）；面板窗口 `hasShadow: false`；`dist/` 已重建 | 用 Chromium 实测：修复前四角像素 alpha=255，修复后 alpha=0，圆角内侧仍不透明；`tests/test_panel_window_has_only_its_own_rounded_corners.py` |

**日志里有、但这次没有改的**（各自原因）：

- 系统托盘 8 秒内没出现在托盘区：启动阶段会等图标**真的**出现再报告，这是有意的诚实检查。（后续已查出图标在等菜单里的数，见 6.9。）
- `系统播放声采集不可用（no_wasapi_loopback_backend）`：需要在那台机器上 `pip install PyAudioWPatch`，不是代码问题。
- `这一轮带着 audio，但型号 gemma4:e2b 不接收它`：音频只有在 `GALAXY_NATIVE_AUDIO_CHAT=1`（默认关）时才会随对话发出，说明那台机器上这一项是开着的；本地 gemma 收不了音频，系统摘掉并在正文里写明，这是 `tests/test_audio_reaches_the_model_or_says_it_did_not.py` 钉住的行为，没改。
- 启动 3 分钟（Phase 0 探测 13.6 秒、语音依赖导入 15 秒、API 网关 48 秒、AI 大脑 38.8 秒、Podman 21.7 秒）：探测本身已经并发；其余是 Windows 上冷导入与子进程的实际耗时，需要真机逐段抓 profile。
- 一句「你好」被判 `heavy 0.692`：复杂度打分是对**整批消息**（系统提示词 + 随请求带上的上下文 + 用户这句）算的；单独一句「你好」加身份提示词只有 0.154，那一轮多出来的分数来自随请求带上的内容（日志里消息长 339 字符），没有逐项查清是哪一块。改打分口径会牵动全部路由测试，这次没动。

### 6.6 2026-10-04：面板开关整理

所有者要求：把面板上所有开关整理、分类，看哪些根本不需要开关。设置页 390 个键里有 96 个布尔开关，逐个对着生产代码核过
（每个都有真实的环境变量读取点，没有死键）。**完整清单与理由见 [PANEL_SWITCHES.md](PANEL_SWITCHES.md)**（由
`core/routes/panel_switch_policy.py` 生成，不手写）。

| 去处 | 个数 | 做了什么 |
|---|---|---|
| 留在面板 | 18 | 用户真有取舍（隐私、花费、对外暴露、对 AI 行为的偏好），按「声音 / 感知与在场 / 记忆与隐私 / 桌面操作与自治 / 模型与花费 / 多设备与网络 / 安全姿态」分组 |
| 内置 | 45 | 不再列在面板上：熔断器、派发幂等、回声消除、朗读回复、本机外放、桌面操作、任务状态落盘、鉴权、Esc 叫停、自回声闸门等不该有人去关的机制和系统自己的基本能力，默认开 |
| 开发 / 运维 | 28 | 不再列在面板上：`GALAXY_DEV_MODE`、Tauri 打包、「本机回环也封禁」、`GALAXY_NATIVE_AUDIO`（由本机模型档位自动开关的门控），对外部署的加固选项和危险逃生口（强制令牌、设备准入、权限从严、远程安装脚本、pickle 权重等），以及替补引擎（Kokoro / IndexTTS）的按需下载 |
| 并进整档按钮 | 5 | 不再单列，翻按钮时和主键一起写：「跨设备」带局域网发现 / mDNS / 设备接入平面 / NATS（只用本机时它们没有意义），「全模态」带主动开口续在哪条对话上 |

不列 ≠ 没接上：键仍在 `CONFIG_SCHEMA`，`POST /api/config` 照收、`.env` 照写、环境变量照读。

**清点时顺带查出的真问题**（都已修）：

| 问题 | 修复 | 验证 |
|---|---|---|
| 「保存设置」会把登记表里每个键的默认值整体写进 `.env`。`GALAXY_MEMORY_MEDIA` 登记成「默认开」而代码三处默认都是关 —— 保存一次，截图和录音就在没人点过的情况下开始落盘；另有 `GALAXY_ENTRYMODE_USE_READINESS`、`GALAXY_PREFLIGHT_FAIL_FAST` 与代码相反 | 登记表默认值对齐到代码；就绪度开关改为认 `true`/`1`/`on`（面板写的是 `true`，代码以前只认 `"1"`） | `tests/test_every_switch_has_a_disposition.py` |
| 设置页只认字面量 `"true"` 为开：`.env` 里手写的 `=1` / `=on`、登记表里写成 `1` 的默认值（`GALAXY_CONSENSUS_ROUND`）代码认作开，面板显示成关，点一下还会把它「关」成 `false` | `GET /api/config/all` 把布尔值统一规整成 `true` / `false`；登记表布尔默认值全部是字面量 | 同上 |
| `GALAXY_COMPUTER_USE_NATIVE_TOOL` 的类型登记成 `bool`，设置页把它画成文本框 | 归一为 `boolean` | 同上 |
| `GALAXY_CROSS_DEVICE_ENABLED` 登记成「默认开」，代码与 `.env.example` 都是关（opt-in）—— 保存一次设置，跨设备编排就在没人点过的情况下开了 | 登记表默认改为关 | 同上（`test_cross_device_is_off_in_the_registry_because_it_is_off_in_the_code`） |
| `GALAXY_NATIVE_AUDIO` 在面板上是个开关，但切到 B 档时 `core/native_modal.py` 会自动开它、离开时自动关 —— 同一个事实两处各存 | 改为运维项；用户的取舍是选哪一档，以及「每轮发不发录音」`GALAXY_NATIVE_AUDIO_CHAT` | 同上 |

新增布尔开关必须先在清单里说清是哪一种、为什么（同一个测试盯着）—— 这是「不要乱加开关」的可执行形式。
**安全姿态不再是一排开关**：11 个里 10 个不再列在面板上（系统自己的保护 → 内置；危险逃生口与部署加固 → 运维），只留「高危命令要不要你批准」这一个对 AI 行为的偏好；`GALAXY_HITL_CONFIRM_GATE` 的说明改成它真正做的事（只拦命中高危词表或零信任规则的命令）。
**声音只留语音总闸**（朗读回复、本机外放内置；两个模型自动下载是替补引擎的按需下载）；**桌面操作与任务状态落盘内置、默认开**。任务状态落盘以前默认关、检查点落在仓库 `runtime/` 且每次变更整份重写所有节点；默认开之前已改成落 `GALAXY_DATA_DIR`、有保留上限（`core/task_graph_checkpoint.py`），测试里一律关。后果：重启后自动重派没做完的任务（先过派发幂等守卫），想关写 `GALAXY_DURABLE_EXEC=false`。
**面板现在会说「重启后生效」**：`core/routes/config_restart.py` 是唯一清单（只登记从读取位置核实过的键），`/api/config/all` 与 `/api/config/bundles` 带 `restart_required`，验证 `tests/test_config_says_what_needs_a_restart.py`。
**已知、没有动的**：`GALAXY_MEMORY_MEDIA` 存储层默认开而入口默认关的边角；主脑与跨设备含义重叠但代码里互相独立。详见 PANEL_SWITCHES.md 末尾。

**「同一能力合并成一个按钮」**：`core/routes/config_bundles.py` 的 `members` 说哪些键和主键是同一件事的另一面。判据只有一条 ——
**（主键关、这个键开）这个组合有没有意义**；没有才并。写入语义：主键关 → 成员全写 `false`；主键开 → 成员回到登记表默认
（opt-in 不替人打开）；一次落盘（`POST /api/config/bundles`）。成员相对主键偏离时按钮显示「有偏离」。验证：`tests/test_bundle_members_follow_the_primary.py`。
**没有并**的（各有隐私/花费/暴露面的理由，列在 PANEL_SWITCHES.md 末尾）：系统声送进模型、听/朗读/本机外放、每轮发不发录音、主脑/联邦/WebRTC/Funnel 这些默认关的 opt-in、主动感知 —— 并了会替用户悄悄改一个选择。

### 6.7 2026-10-05 / 10-07：多机模式 = 跨设备模式的整体内容；模式只有一条规则

所有者要求把「跨设备 + 多设备并行 + 建立在两者之上的 NATS Agent 与任务派发分配」作为**一个模块**处理。定义、四层模型、一个任务怎么走完、各层配置键
（含 18 个只在代码里读、没登记的环境变量）/ 模块 / 接口，都在 **[MULTI_MACHINE_MODE.md](MULTI_MACHINE_MODE.md)**（键表由 `scripts/gen_multi_machine_map.py` 生成）。
2026-10-07 按所有者的决定收口：

- **系统只有两个模式**（本地 / 跨设备），**「现在是哪个」只有一条规则、一个出处**（`core.system_mode.cross_device_requested`：按钮开或手写跨设备模式，任一即是）。
  此前同一件事有三个各自推导的答案（网关只看按钮；启动流程另把「NATS 地址非空」当跨设备；`system_mode.py` 让写着 `desktop-local` 的模式键盖过按钮），
  于是面板按钮开着、`.env` 里躺着 `desktop-local` 时三处各说各话，「保存设置」写入的 `nats://localhost:4222` 还会把只想用本机的人悄悄切成跨设备。
  现在网关开关、启动流程、桌面在场、启动自检、模式接口都调那一个函数；NATS 地址不参与判模式；面板「跨设备」按钮同时写主键与模式名，「运行模式」下拉框不再列在面板上。
- ~~**主脑与 worker 只在跨设备模式里起**~~（2026-10-19 推翻，见 6.21：任务派发只看它自己的开关）。
- ~~**模型只能请求、不能决定**打开跨设备~~（2026-10-19 删除，见 6.21：模式不限制智能体，也就没有可请求的东西）。
- 另两处遗留真问题已修：主脑状态文件缺省落 `$GALAXY_DATA_DIR`（不再落系统临时目录）；`GALAXY_NATS_EXECUTOR_FALLBACK` 的 `reject` 真的不退回（登记只留 `sync` / `reject`）。
- 6 个数字 / 取值的登记默认对齐到代码（主脑缩放复评间隔、节点心跳、安卓快照保鲜、联邦心跳、SLO 心跳窗口、Tailscale 检查间隔）；清点时记的第 7 个（`GALAXY_HEADSCALE_USER`）核对后本来就一致。
- ~~**本地模式不往别的设备下发**~~（2026-10-19 推翻，见 6.21：那是把「电脑加入」误当成「智能体可以协调」；下面是当时的记录）（真机实测查出）：起真服务器、两台真配对的设备客户端，本地模式下 `/devices/parallel` 曾把命令送到设备并执行 —— 命令路由的设备执行桥直接发，网关开关只在两处查。
  现在并行 / 单设备命令 REST、设备执行桥、网关单设备下发、智能体 `devices__invoke` 五处统一拒绝（`cross_device_disabled`，并说明怎么办），按钮一翻即放行。
- 真机实测还查出并已修的三处：模型看不到「请求打开跨设备」工具（工具表超 24 个时被按词法相关性裁掉，现列入核心工具永不裁）；工具循环只把 `result` / `error` 交给模型，
  需要确认时模型不知道问什么、批准后不知道要重启（结果文案现在写进这两个字段）；POSIX 上端口预检不设 `SO_REUSEADDR`，设备连着时停掉服务再立刻起，会把旧连接的 TIME_WAIT
  误报成「端口被占」、API 网关起不来（横幅却照常报「就绪」）。
- 验证：`tests/test_one_rule_decides_the_system_mode.py`、`test_multi_machine_registry_defaults_match_the_code.py`（当时另两份钉住旧闸的测试已随 6.21 删除）。

### 6.8 2026-10-07：所有者第三份真机日志（代码版本 9dd1d9c2）+ 面板 / 厂商 / 开关

这一轮把日志里的问题和所有者列的几件事一起处理。**凡是能在本机复现的都起真服务器测过**（带卡顿探针：`scratchpad` 里的 `run_stall.py` 在事件循环线程每次连续跑超过 0.12 秒时记下它的调用栈）。

**面板与路由**
- **各家厂商 API Key 逐家有地方填**：此前面板只有「我的模型服务」（自定义端点），各家的 Key 退化成「全部设置」第 12 段里 35 行裸环境变量名。现在「模型服务商」按分组列出每一家：中文名、该填哪几个键、已配 / 未配、路由器里可用 / 不可用、验证、清除。
  目录由后端给（`core/provider_catalog.py`，`GET /api/v1/models/providers`），**不下发密钥值，只有布尔**；`PROVIDER_REGISTRY` 多一家而没写展示信息、或「供应商与密钥」类里有键没人认领，测试会红。
- **路由补全**：偏好表只列我们核实过的直连厂商，所以用户自加的端点、OneAPI、只配了 Groq 的人做推理任务，在失败转移链里「不存在」（面板上写着「通了才让它参与选路」，实际只有所有列出来的都不可用时才被碰到）。
  现在它们排在已列厂商**后面**，按同一个打分排序（`core/routing_tail.py`）；有意不自动参与的（智谱编码套餐）仍不进这一档。
- **中间态不再依赖壁纸深浅**：每面墙自己带一层深色底，**近端不透明**、沿同一条衰减曲线化回桌面，淡紫叠在这块底上 —— 浅壁纸与深壁纸上看到的是同一堵墙（实心的深紫近端、清楚的墙/天花/地板轮廓，往里按 (1-t)² 变淡）。浓度 `--n` 改乘进淡紫那层的 alpha，不再乘整面墙的 opacity（那会把底也压成半透明）。四条对角棱上能看到一道很淡的细线（相邻两面在棱上各自抗锯齿），与原来的设计稿一致，没有再去遮。灵动岛：248×33 → 上一版 216×40（更窄更高，方向反了，越改越像一块墩子）→ 现在 280×28（约 10:1，又薄又长，Windows 灵动岛那种），尺寸常量在 `electron/renderer/app.js` 的 `ISLE_*`，一处可调。
- **面板窗口圆角**：桌面外壳里 `html` 按 `--shell-r` 裁圆角，圆角外一个像素也不画。（Windows 上的实际观感这里无法复现，只验证了 Chromium 里四角像素全透明；Electron 在 Windows 上不会给透明窗口加框和阴影的依据见 6.9。）

**开关**
- 已经收好的开关（内置 / 运维 / 并进整档的）**不再被「保存设置」钉进 `.env`**：此前点一次保存，七十多个没人该碰的内部开关连同默认值整体写进去，既淹没真改过的几行，也会盖住以后代码里默认值的修正。改过的（值与默认不同）照旧写。
  默认位置在 `data/` 下的路径类键（账本、声音记忆库……）同理，免得把它们冻成相对路径、不再跟 `GALAXY_DATA_DIR` 走。
- **保存设置不再吞手写行**：写 `.env` 的函数只遍历登记表，而 `.env.example` 里一百个键不在登记表里（compose 必填的数据库口令、端口、`HF_ENDPOINT` 镜像站、`PICKLE_SECRET_KEY`、`BRAVE_API_KEY`、`TURN_*`……）—— 点一次保存它们整行消失，下次启动悄悄回到默认值。这很可能就是 `--docker-full` 报 `TEMPORAL_DB_PASSWORD is missing` 的原因。现在原样带回（`core/routes/config_env_preserve.py`）。
- **NATS 缺省只有一个答案**：显式写了 `GALAXY_NATS_ENABLED` 听它的，没写就**跟着模式走**（跨设备模式起、本地模式不起），三处不再各说各话（`core.system_mode.nats_wanted`）。**这反转了此前「没写就尝试启动」的注释**：本地模式默认不再起总线；想单独起设 `GALAXY_NATS_ENABLED=true`。
- `GALAXY_MEMORY_MEDIA` 缺省统一为关（此前登记表、网关、会话记忆各有各的默认）；多机模式 22 个只在代码里读的键补登记（密钥类走密钥库）；`NODE_*_URL` 不再误属于某个整档按钮。

**真机日志里的问题**
- **「节点启动失败（详情见日志 DEBUG）」**：慢的（进程活着、只是这台机器忙）→ 后台继续等，起来了自动登记；真起不来的 → 屏幕上带一句原因（取输出最后一行有信息的）；端口绑不上（占用 / Windows 保留端口段）单独说，并给出 `netsh int ipv4 show excludedportrange` 去哪看。
- **节点输出不再接管道**：`ServiceManager.start_service` 用 `stdout=PIPE, stderr=PIPE` 起节点，而启动器只在节点起不来时才读一次。没人读的管道写满，子进程就卡死在 `write()` 里 —— Windows 匿名管道默认缓冲只有 4KB，一个节点的启动日志加几十条访问日志就够了，表现是进程活着、端口开着、什么都不回应。现在写 `logs/nodes/<名字>.log`（人也能直接去看），失败原因读文件末尾。同一处把创建进程放进工作线程（Windows 上 `CreateProcess` 要上百毫秒，13 个节点串着在事件循环上做）。
- **事件循环被同步的事占住**（日志里「一堆请求在同一毫秒一起完成、各自显示 5–7 秒」）。挪出循环的：开麦克风 / 枚举并实测输入设备 / 探测回环设备（`语音交互 已开启` 之后紧跟着的 5 秒冻结）；第一次选 TTS 引擎（import 一串库 + 探测算力，是第一轮对话的 7 秒）；每个 httpx 客户端各载一遍 CA 证书（实测一次 40–80 毫秒，仓库里五十来处在循环线程上现建现用，现在进程内共用一份，`core/shared_tls.py`）；
  启动时一百多次能力登记各自把整张拓扑图序列化落盘（实测 106 次、最大 93KB，现在合成一次，`core/persist_batch.py`）；每轮对话都把所有设备所有能力重新登记一遍并整份落盘（现在批内合一，内容没变的节点不再重写文件）。
- **感知上传洪水**（前几轮已修，这轮补上 Electron 侧在途上限与纯 ASGI 的计时中间件）：真服务器上 40 帧 + 40 段音频同时压上来，循环上没有任何一次超过 0.12 秒的停顿，其余接口 ≤ 320 毫秒应答。
- **持久化路径认 `GALAXY_DATA_DIR`**：网络图 / 拓扑 / 节点注册表 / 委托执行追踪 / 成本账本 / Agent 状态 / 设备注册快照 / 三个记忆提供方，此前写死 `data/...`（容器里 `GALAXY_DATA_DIR` 指到别处时被劈成两处）。新加的持久化点用 `core.data_paths.data_path()`。
- **对话历史同一轮记两遍、且一份带内部注解**（截图时发现，面板上看得见）：走内核的请求，`AgentKernel._record_session`（带模态信息，用户那句却是追加过 `[Multimodal context: …]` / `[desktop_context_strategy …]` 的版本）与 `OpenClawd._record_turn`（干净版本）各记一遍。现在内核入库前只剥**追加在末尾**的机器注解（`strip_appended_annotations`，其余一个字不动），OpenClawd 在内核路径上只记进程内那份。真服务器上 2 次请求 → 历史 4 条（user/assistant × 2），文本干净、换行保留。
- 其余：FastAPI 的 `ORJSONResponse` 弃用警告每个请求刷一次（改用自己的响应子类）；常驻注意力循环在听写引擎下载期间不再每拍往线程池里塞一个空等的线程（屏幕上的「转写 45 秒没有回应」）。
- 验证：`tests/test_provider_catalog_covers_every_key.py`、`test_unlisted_providers_join_routing.py`、`test_saving_settings_keeps_env_lines_the_panel_does_not_own.py`、`test_env_file_carries_no_untouched_hidden_switches.py`、`test_node_output_never_fills_a_pipe.py`、`test_slow_nodes_are_waited_for_and_failures_say_why.py`、`test_microphone_open_does_not_run_on_the_event_loop.py`、`test_choosing_the_tts_engine_does_not_block_the_event_loop.py`、`test_httpx_clients_share_one_tls_context.py`、`test_startup_registration_writes_the_graph_once.py`、`test_ingest_admission_and_loopback_bypass.py`、`test_ambient_listening_does_not_park_threads_while_the_asr_downloads.py`、`test_one_turn_is_recorded_once_and_without_machine_annotations.py`、`test_the_walls_look_the_same_on_any_wallpaper.py`。

### 6.9 2026-10-08：只在 Windows 上出现的几项，逐项查证

没有 Windows 机器，所以只认两种证据：**第三方源码里读到的**（Electron 28.3.3 的 `native_window_views.cc`、pystray 0.19.5）和**在这里能复现的模型**。每一项下面写了哪些是证实的、哪些仍是推断。

| 现象 | 查到的 | 处置 |
|---|---|---|
| 系统托盘「8 秒内没出现在托盘区」 | **机制证实，耗时推断。** pystray 的 `setup` 回调（我们在里面置 `icon.visible` 并判「图标出现了」）要等 `_mark_ready()` 跑完才被调用；`_mark_ready()` 先 `update_menu()`，Windows 后端把**整棵菜单含惰性子菜单**建一遍。「本机模型实测」子菜单一求值就算整份实测账：探硬件、问 Ollama（2 秒超时）、第一次 import 路由模块。图标于是在等一张菜单上的数。用真 pystray + 一个 Windows 形状的后端 + 一份慢 3 秒的实测账复现，报出的正是真机上那句话。冷机器上到底慢多少，这里量不了 | 建菜单只读缓存，算数放后台线程，图标就绪后才起第一遍、算完刷新菜单。`tests/test_the_tray_shows_up_without_waiting_for_the_menu_numbers.py` |
| Podman「虚机没起来，试 `podman machine start` 后重跑」 | **证实。** `_bring_up` 对 Docker 会拉起 Docker Desktop 并等 60 秒；对 Podman 只在「引擎已通、API socket 没起来」时才 `machine start`，而虚机没跑时 `podman info` 就不通，直接放弃、叫人自己敲命令 | Windows / macOS 上 Podman 引擎不通时先查有没有虚机：有就 `machine start` 并等（同一个 `GALAXY_AUTO_DOCKER_DAEMON_WAIT`）；**一台都没建过**就不替人做（建虚机要下载镜像），直接说「先 `podman machine init`」。`tests/test_podman_is_not_docker.py` |
| `PyAudioWPatch` 没装 | **设计如此，不是缺陷。** 它在 Windows 档（`requirements-windows.txt`），只有 `python main.py install --all` / `install_windows.ps1` 会装；启动期自愈只装核心清单，语音类依赖**故意**不在启动期装（`launcher/deps.py` 模块头）。屏幕上已给出 `pip install PyAudioWPatch` | 不改 |
| 「VAD 从未判定为说话」 | **措辞误导。** 启动后 20 秒一次性诊断，「收到音频但没判过说话」既可能是麦克风坏了，也可能只是这 20 秒没人开口，原文却写「语音输入无效」 | 改成「麦克风在收音，但……没人说话就属正常；说了话还是这样才是增益 / 设备问题」。判据与阈值不变 |
| 首次启动 Ollama 的 Phase 0「这次没查完」 | **已经是诚实的。** 先问 HTTP（不依赖 PATH、不起子进程），问不到再 `ollama list`（8 秒），整项 12 秒到点放弃并记成「没等到」而不是「未安装」，依赖阶段重查 | 不改。冷启动的真实耗时需要在那台机器上抓 profile |
| 面板四个边角 | **Electron 28.3.3 源码里读到：透明窗口的构造函数里 `if (transparent()) thick_frame_ = false;`**，于是 Windows 上不加 `WS_THICKFRAME` / `WS_CAPTION`，系统不会给它画框或阴影；`hasShadow` 在 Windows 上只是存了个值（官方文档也没有 Windows 标注）。所以 Electron 这条路上，方角只可能来自页面本身（已验证：圆角外像素全透明）或渲染降级。**Tauri 壳**的面板窗口却漏了 `.shadow(false)`（覆盖层有）——无边框窗口在 Windows 上默认带按矩形画的系统阴影 | Tauri 面板补上 `.shadow(false)`。Electron 不改：没有证据支持再动 `thickFrame` / `roundedCorners`（后者在 28 里只有 macOS） |

要定位 Windows 上「圆角外仍有方角」，最省事的是看两样：`logs/electron.log` 开头有没有 `已禁用硬件加速`（软件渲染 / basic 降级下透明窗口行为不同），以及方角是**深色实心**（页面或降级）还是**一圈浅色细边**（系统）—— 两种的修法不同。

### 6.10 2026-10-08：面板上填 API 的那些，改成内嵌的行

所有者：「面板上 API 填入那些做成与面板一致的样式，内嵌的那种，融为一整体。」

- **之前**：「模型服务商」每家一块凸起的小卡（渐变底 + 内高光 + 投影，卡与卡之间 10px 缝），叠在「全部设置」那一页上像从别处贴来的 —— 那一页别的项全是平铺的行。
- **现在**：和 `.sf-row` 同一个节奏，**没有底、没有影**，只在悬停 / 正在填的那一行淡淡亮一下。每家一行两栏：**左**是谁、通没通、说明、Key 名 + 验证 / 型号与选路（小字）；**右**只剩输入框和保存键，一行高。有几把 Key 的（识屏 OCR 两把）每把仍各带自己的 Key 名站在输入框上面。详情就地展开。窄栏（设置浮层、小窗口）按**容器宽度**塌成一列，输入框占满整行。
- 范围：`.up-card` 本身改平，所以「我的模型服务」里自己加的端点、「没收口的结果」同样内嵌；它们的内容结构没动。
- 交互没动：填 Key 保存后立刻 1 token 试调、输入不被每秒的重画清掉、清除密钥、型号与选路的就地展开，都用真服务器 + Chromium 走了一遍。
- **动效**（所有者：给这些白块加上动效）：输入框 / 保存键 / 型号药丸 / 档位牌悬停浮起、按下沉回去；设置页一打开每一行按序浮起来（按 `data-open` 触发，每次打开都能看见）；详情展开、试调结论出现各自淡入；状态变了（没配 → 已配 → 通了 / 没通）那颗点扩一圈光。**全是一次性的**，没有一条在转的循环，不碰 0.17–0.25 Hz 那道门；`prefers-reduced-motion` 下 animation 全停、位移类一步到位（用真浏览器切换核对过）。
- 验证：`tests/test_the_api_entry_is_inline_rows_not_cards.py`（在旧的卡片样式上四条全红）、`tests/test_panel_motion_stops_when_asked.py`；`panel/dist/` 已重建；面板相关 65 个测试文件 1815 条通过。
- 截图里圆角外的「四个白角」是我渲染时没开透明背景（Chromium 截图默认白底），产品里窗口圆角外本来就是透明的（四角像素 alpha=0）；之后的截图一律透明背景 + 合成到壁纸上。

### 6.11 2026-10-08：面板「全部设置」——已并进整体的删掉，其余全部翻成中文

所有者：「所有面板多余的开关，该删的都删了，就是已经整合成一个整体的，该删的都删。如果不是的话，就把那些全部翻译成相关的中文。」

- **删掉（设置页不再摆）**：整档按钮的三个主键 —— `GALAXY_CROSS_DEVICE_ENABLED`（跨设备）、`GALAXY_AMBIENT_LOOP`（全模态）、`GALAXY_AUTONOMY`（自主）。底部那排按钮已经是它们的开关，设置页里又摆一行 = 同一件事两处能拨。后端 `/api/config/all` 给这三个键标 `bundle`（取自 `CONFIG_BUNDLES`，唯一来源），前端据此跳过；值照给、`POST /api/config` 照收。随主键走的成员开关与「内置 / 运维」开关此前就已经不列了。其余 `owns` 里的开关（主脑、联邦、Tailscale Funnel、WebRTC 数据通道、主动感知、屏幕变化触发开口、系统声进感知）**没有**删：它们是各自独立的取舍，不是「主键开它就该开」，理由写在 `config_bundles.py` 里。
- **翻译**：设置页 315 个键里 281 个列出（另 31 个是厂商卡认领的，卡拉不到时才会全列，也都有名字）。每行行首原先是环境变量名（`GALAXY_AEC_RES_FLOOR_DB`），现在是**短中文名**（`远端单讲的抑制下限`），环境变量名退到悬停提示；名字下面的说明去掉与名字重复的开头。每个下拉的每一档也有中文名（`best-effort`→「尽力而为」、`shadow`→「只在隔离区验证」、`ask`→「每次问我」……），下拉键的说明改用中文档名重写，不再夹 `env=` / `strict=` 这类原始取值。「已改过，默认 X」里的 X 也是中文档名。
- **取值其实只有几个的字符串键**（`auto / 1 / 0`：全双工、声字同文、自动拉容器、精简工具集、保留上轮工具、空闲预演、投机解码草稿；`enforce / warn / off`：MCP 清单复验、出站管控；`auto / container / builtin`：自写代码的隔离方式；`off / on`：按需加载工具）原先是一个让人敲字的文本框，现在按档位牌画；登记表里它们仍是 string（只改了展示层），默认值必须是其中一档（测试核对）。
- **顺带查出两个名实不符的登记**：`GALAXY_MODE` 登记的 `distributed / federated / standalone` 三档**没有任何读者**，代码里只有 `production` 有读者（强制开鉴权、要求令牌 ≥32 位）—— 改成 `standard / production`，说明里写明后果；`GALAXY_PREFLIGHT_MODE` 登记的 `normal / strict / skip` 命令行根本不认（`argparse choices` 是 `auto/all/core/gateway/android/ws/vault`），而「保存设置」会把默认值写进 `.env`，等于手动跑预检就报错 —— 改成它真正接受的取值，默认 `all`。
- 机制：`core/routes/config_labels.py`（`LABELS` / `OPTION_LABELS` / `HINTS`）只管**说法**，不管列不列、默认、生效与否；`tests/test_every_listed_setting_has_a_chinese_name.py` 钉住：`/api/config/all` 列出的每个键都有 2–20 字、含汉字、全表不重名的中文名；每个下拉取值都有中文名；表里没有过期的键；说明不重复名字、下拉说明不带原始取值；`GALAXY_MODE` / `GALAXY_PREFLIGHT_MODE` 的取值与代码读到的一致。**新增一个会列在面板上的配置，不补这张表测试会红。**
- 验证：真服务器 + Chromium 逐段看过（说话与听 / 安全与权限 / 进阶），281 行行首无一行英文键名、三个主键已不在；`panel/dist/` 已重建。

### 6.12 2026-10-08：手表（galaxy-wearos）接中心智能体——规范入口上此前一条都没通

设计（`docs/architecture/DEVICE_ONBOARDING_PLANE_V1.md` §2）：手表是「成员」（只响应），与中心智能体之间只有：人说的话交给智能体、智能体的提问送到手表、登记与回应、通话。三态是电脑上的东西，手表既不上报、网关也不往手表推。实测（真网关 + 手表真实帧形状，`probe` 见本节测试）发现这几件在规范入口 `/ws/device/{id}` 上**一件也没通**，各自的单元测试都是绿的：

- **认证**：手表的 AuthMessage 编进 `payload.token`，`handle_auth` 只读顶层的环境令牌；配对时拿到的令牌（`/api/v1/pair/claim`）也过不了。现与 `device_register` 共用 `evaluate_ingress_authentication`，认证结果绑到连接对象，断开作废。
- **命令**：`command` 帧（`voice_query` / `human_input` / `query_devices` / `interruptibility`）在规范入口没有处理器，只回通用 ack；真处理挂在没有挂载的旧入口。现接到同一份 `websocket_handler.handle_command`（`handlers/device_command.py`），处理前过 `sender_is_trusted`（`voice_query` 进智能体主链、`human_input` 能批准高风险操作，不能让没认证过的连接做；另开一条连接自报同一个 device_id 借不到别人的认证）。
- **通话**：`voice_call_*` 同样只被 ack，现转给 `voice_call_route`，通话路由按连接建、连接断开即收。
- **智能体找手表**：`_discover_target_devices` 只读旧管理器本地表和 REST 登记表，规范入口的手表两处都不在，「在手表上问人」永远找不到手表、一律退回「在对话里问」——而旧测试正是把它替换掉的。现以 UCM 为准。
- **回复认领**：`command_result.correlation_id` 填的是网关临时生成的 `message_id`，手表按自己发的 `cmd_N` 认领回复，所以语音回复从不进会话记录。现回复带发送方给这次请求起的名字（`galaxy_gateway/command_reply.py`）。
- **退役**：`phase_report` 命令（手表不再上报三态）回「已忽略」；`core/cross_device_sync._push_phase_to_wearos_devices` 与 `galaxy_gateway/android/handlers/wearos_sync.py`（往手表推三态）已删，手机的相位回推不变。
- **手表对智能体动作的回话（`command_result`）到不了等它的那个调用**：手表自己造的几种帧（登记、报能力、回话）不经共享协议的信封，没带 `version`，网关把它们当成 AIP/1.0；1.0 里的 `command_result` 是「任务结果」（`task_result`），被跨仓 schema 闸门以 `missing_schema_version_metadata` 拒收。结果是 `devices__invoke` 打到手表，手表执行了、回话也发了，调用方却每次都等满 30 秒超时。已在手表侧补上 `version: "3.0"`（V2 侧的测试用真实入口证明：带 version 通、不带不通）。
- 测试：`tests/test_watch_reaches_the_central_agent.py`（38 条，**不替换发现函数**，帧形状与手表 `WatchMember` 一致；含「智能体让手表做事并拿到回话 / 手表报失败带原因」「手表上说一句要放开跨设备 → 在手表上问戴表的人 → 批准才做、拒绝不做、后台自发回合连问都不问」）。

### 6.13 2026-10-08：手表出门直连——电脑自己不在网里时，别给手表发进网钥匙

手表配对时拿到一把一次性进网钥匙（`headscale`），为的是出门后还能直连这台电脑。查出两处让这条路"看着通、实际不通"：

- **桌面版从来没让电脑自己入网。** 自动入网（`core/tailnet_self_join.py`）和局域网广播（`_galaxy._tcp`）只写在网关 lifespan 里；桌面版由启动器自己建应用、只挂 `/ws/device/{id}`，不跑那个 lifespan。结果是钥匙发了、手表进了网，电脑不在里面。现在两处共用 `autojoin_at_startup` / `start_lan_announcer`，桌面启动器里由 `launcher/tailnet_startup.py` 在 `TailscaleManager.initialize()` **之前**入网、发布广播、停机时收掉；横幅区分"装了但没入成"（带处置）与"没装"，广播没发出去不再写成"已发布"。
- **配对不管电脑在不在网里都发钥匙。** 现在 `/api/v1/pair/claim` 先问 `desktop_gate`：电脑没装客户端、没登录、或登录在别的控制服务器时，配对照样成功、令牌照发，但**不发钥匙**，`tailnet_join_unavailable.reason = "desktop_not_on_tailnet"` 并带下一步；查不出来时放行；headscale 没配时仍报原来的原因码。手表侧把这个码翻成人话（"电脑还没加入 tailnet"）并在配对完成后展示。
- 测试：`tests/test_tailnet_key_needs_the_computer_in_the_network.py`（19 条；把门拿掉 3 条变红、把入网挪到探测之后 1 条变红）。
- **提示语跟系统模式走（2026-10-19 对着最新 main 复核）。** 桌面启动器现在只在**跨设备模式**入 tailnet、发布 `_galaxy._tcp`（见 `launcher/bus_phase.py`；默认是本地模式）。所以本地模式下 `desktop_gate` 不再说「重启就自动加入」——那是句假话，重启后照样不会入网——而是说「现在是本地模式，先在面板打开『跨设备』并重启」；立刻加入的 `POST /api/v1/tailnet/join-this-computer` 两种模式都可用。手表侧同步：配对完成页，以及「自动发现网关」没找到时给出两条出路（手填地址 / 打开跨设备）。
- 仍需真机：真 headscale + 真 tailscaled 上"电脑未入网 → 配对不发钥匙 → 入网后重新配对发钥匙"的整条路。

### 6.14 2026-10-08：「调数据方式」的开关撤出面板，改由智能体按人的话调

所有者：「面板上有很多调数据方式的开关，能不能全部设置成自适应的？如果不行，能通过对话让他自己调，这些开关其实也挺多余的。」

**先查了它们到底是什么**（95 个：86 个数字 + 9 个档位，见 `core/tuning.py` 的白名单）：

- **绝大多数本来就是某个自适应算法自己的常数，不是该人去调的东西**：回声消除是自适应滤波（时延自己估 `_estimate_delay`、滤波器自己收敛），并发限额是 AIMD（按实测延迟与错误率自己涨跌），熔断自己试探恢复，选模型的打分吃实测表现；默认值本来就空的（Ollama / llama.cpp 上下文窗口、节点健康重试……）就是「系统按本机情况定」。
- 「全部做成真自适应」我**没有**做：那要给每个参数找一个可测的信号、再配安全边界与回退，一百来个逐个造控制回路风险大、也验证不了；硬造等于又多一百个没人敢信的黑箱。能自适应的已经在自适应，剩下的是人想表达**效果**时才需要碰（「回声太大」「它老抢我话」「别老主动开口」「这个超时太短」）。

**做了什么**

- **撤出面板**：这 95 个键从「全部设置」不再列出（仍登记在 `CONFIG_SCHEMA`，`POST /api/config`、`.env`、环境变量照旧能用）。面板 281 行 → 186 行。留在面板上的是端口 / 地址 / 路径 / 密钥 / 安全类 / 模式与引擎的选择 / 会删数据的保留类。
- **智能体按人的话调**：两个工具 `tuning__list`（话题 → 参数 → 当前值 / 出厂值 / 允许范围）与 `tuning__set`（改一个、或 `reset=true` 一句话撤销回出厂调校）。实现在 `core/tuning.py`，经 `core/openclawd.py` 与 `devices__` / `home__` 同一条分发（三族合成一个分支，行数没涨）；工具表过长时也不被裁掉（`context_trim._CORE_TOOL_MARKERS`）。
- **边界（安全的一部分）**：只调白名单里的键，**每个键有硬范围**，越界不写；只在**人发起的回合**里调（文字 / 语音 / 手表），后台自发的回合连调都不行；一个回合最多改 5 个；**会放大智能体自己自主度的方向要人点头**（自发开口 / 委托额度调大、节拍调密、桌面操作步数调多，走设备接入已有的人在环 `_ask`，往收敛方向调不用问）；**不碰会删数据的键**（上下文归档上限与保留天数、相位账保留天数、媒体库容量、运维记录条数——调小就是自动删东西，只归人）；密钥 / 地址 / 路径 / 端口 / 安全类 / 模式类一个都不在白名单里。每次改动留痕（`$GALAXY_DATA_DIR/tuning_log.jsonl` + `[AUDIT]` 日志）；写入走面板「保存设置」同一个函数。
- **「要不要重启」如实说**：读取点在导入时的 19 个键（并发 / 熔断 / 心跳 / 视频帧率……）说「要重启」，由 `tests/test_tuning_knobs.py` 逐个核对源码；其余只说「多数在下一次用到时就按新值，没看到变化就重启」——没核实过的不说「已生效」。
- 真走了一遍：用真智能体循环的分发（`_dispatch_tool_call`）调 `tuning__set`，人发起的回合写进了 `.env` 与环境，后台回合被拒；`tuning__list` 查「回声」给出对应的 8 个参数。

**顺带查出并修掉的**（都是「登记的出厂值 ≠ 代码里真正用的默认值」）：并发的目标延迟登记 2000 / 代码 500、上限 200 / 50、熔断窗口 60 / 10、命令并发 50 / 20、全局并发 100 / 50、请求排队 1000 / 200、延迟统计窗口 300 / 1000、预演候选数 1 / 2 等共 13 个。「保存设置」会把登记的出厂值整体写进 `.env`，所以只要点过一次保存，这些就悄悄从代码默认变成登记值。已对齐，并有测试逐个核对；几处描述里写的「秒」其实是「最近几次」，也改了。**同时调参键不再被「保存设置」钉进 `.env`**（没人动过的不写）—— 钉了，以后代码里的自适应常数再调也不会生效。

**灵动岛**：所有者说边角太突兀，我先给顶上两侧加了向外张开的凹圆角，所有者看了说「过头了，上一版就可以」—— 已退回上一版（改前后逐像素相同），没有留任何改动。

`tests/test_tuning_knobs.py`（30 条）；`tests/test_every_listed_setting_has_a_chinese_name.py`、`test_voice_switches_reach_the_panel.py`、`test_speculative_draft.py`、`test_context_length_follows_reality.py` 里原先把这些键钉在面板上的断言，改成钉「在调参白名单里」。

### 6.15 2026-10-11：面板「全部设置」186 行 → 67 行：该删的删、该内置的内置、该对话里调的挪走、该留的留着

所有者：「完整再罗列一下，分个类，看还能把哪些直接内置装进去，不然这么多按钮谁调得过来」；看过分类后：「按照你的建议走，该内置的内置，该保留的保留，该删的删，该修的问题全部修了。」

**结果（真启动 `main.py`、用真面板数的）**：本地模式 **67 行**；切到跨设备模式 **82 行**（多出来的 15 行是跨设备专属）。没有一行是英文名。

| 去向 | 数量 | 在哪 |
|---|---|---|
| **删**（没有任何代码在读，面板上有一行、改了没有任何效果） | 7 | `UFO_NODE_HOST`、`MAIN_REPO_URL`、`GALAXY_MARKET_STORE_DIR`（技能市场 `core/api_market.py` 早已删除；技能走 `skills/` + `/api/v1/protocols/skills`，与它无关）、`GALAXY_MAX_CONTEXT_TOKENS`，以及每设备令牌注册表被删之后留下的 `GALAXY_DEVICE_TOKEN_STORE` / `_RETENTION_DAYS` / `_MAX_RECORDS` |
| **内置**（有一个对的默认，人填错只会弄坏） | 90 | `core/routes/panel_builtin.py`：路径、内部服务地址与端口、型号与规格、固定的严格默认、运维逃生口；连带 `GALAXY_HF_MIRROR` 在开关清单里登记为内置（下载源由 `core/hf_endpoint.py` 探测择优） |
| **对话里调**（人会说的是效果，不是去找一行设置） | +7 | 并进 `core/tuning.py`：开源优先、多模型合议、模型驻留时长、两个听写模型大小、两个音色名（共 102 个：86 数字 / 14 档位 / 2 名字）。音色名只收字母数字 `._-`，开关与档位只收登记的几档 |
| **只在跨设备模式下才列** | 15 | 总线 / 联邦 / 打洞与中继 / 设备名 / 网格口令……判模式只认 `core.system_mode.cross_device_requested()` |
| **留着**（账号与令牌、你自己的地址与位置、权限与安全、隐私取舍、会删数据的保留类） | 其余 | 面板 |

内置的键**仍登记**：`POST /api/config`、`.env`、环境变量照旧能用；只是 `GET /api/config/all` 不列、「保存设置」不再把它们的默认值钉进 `.env`（钉了，以后代码里的默认修正就永远盖不住）。有人明确写过的值照旧保留。

**对着代码核到的真问题（都修了）**

- **`CORS_ALLOWED_ORIGINS` / `CORS_ALLOWED_HEADERS` 登记默认是 `*`，代码的安全默认是「本机端口 + 显式请求头」。** 网关带 `allow_credentials=True` 挂这两个值：只要点过一次「保存设置」，`*` 就被钉进 `.env`，等于任何网页都能带着凭据跨站调本机接口。登记默认改为空（= 代码默认）；**已经被旧版本钉进 `.env` 的 `*` 会在下一次「保存设置」时清掉，重启后生效 —— 在那之前它仍然生效**，不会悄悄变。分不出旧版本钉的 `*` 与手写的 `*`，所以手写的也会被清；真要开放就写成明确的来源列表，或通过 API 明确写 `*`（明确写的照写）。
- **`CHROMA_PERSIST_DIR` 登记 `./chroma`，代码读的是 `./chroma_db`** —— 保存一次，向量库就换成一个空目录。登记默认改为空 = 数据总目录下的 `chroma_db`；已有旧目录 `./chroma_db` 继续用它。没有清理旧 `.env` 里钉着的 `./chroma`：那个目录里可能已经写了新数据。
- **「路径都跟着数据总目录走」只有一半是真的**：任务成本账本 / SimpleMem / 声音记忆库在登记表里写成 `data/…` `./data/…`（`GALAXY_DATA_DIR` 一改就劈成两处）；任务分配账、面板上一次操作结果落在 `runtime/`；安卓设备状态快照默认落**系统临时目录**（被清理就丢）；装进来的 GitHub 项目写死在源码树 `data/github_addons`，且 `GITHUB_INSTALL_DIR` 根本没登记。全部改成随 `GALAXY_DATA_DIR`，**数据目录下还没有、旧位置已经有东西时继续认旧位置**（`core/data_paths.py::data_path_or_legacy`），不把已有数据甩在后面；没配数据总目录时装进来的项目位置不变。
- 新增一道测试**扫全仓**：登记的默认值必须等于代码里的字面默认值；每个登记的键必须有代码在读（`tests/test_panel_builtin_keys.py`，22 条）。

**有意没动的（如实说）**

- `GALAXY_MEMORY_MEDIA_DIR` 仍是 `runtime/memory_media`：媒体库模块注释写明是有意「不进 git、不进备份」，且该功能默认关；`GALAXY_LOG_DIR` 仍是 `logs/`（日志不是状态）；`GALAXY_KOKORO_DIR` / `GALAXY_INDEXTTS_DIR` 仍在 `models/`（大权重不放数据目录）；`GALAXY_FEATURE_FLAGS_PATH` 是仓库里的配置文件 `config/feature_flags.yaml`，不是运行时状态。它们都只是不再上面板。
- 听写模型大小**没有**做硬件自动挑：`WhisperASR` 虽有按显存挑的逻辑，但默认值现在是 `base`，改成自动会让大显存机器悄悄去下载更大的模型。所以交给对话里调，而不是硬塞一个「自动」。
- 我没替人把存在旧 `.env` 里的其它内置键清掉，只清了上面已经证实有害的 `*`。

**验证**：受影响测试全跑（约 4.6 万条）：除两条 `test_pr4v2_android_evaluator_artifact_governance_flow.py::TestGroupJ_*`（与前面的测试同批跑时失败，**在干净的 HEAD 上同样失败**，单独跑通过，是既有的顺序依赖，与本次无关）外全部通过；另有一条 `test_the_wiring_gate_actually_blocks` 在我并行开多路测试时撞上别路测试临时建的文件，单独跑通过。守卫（import 边界 / 文件复杂度 / 可达性 / 接线 / 裁决独立 / 未接线清单 …）、black / isort / CI 的 flake8 全绿；`docs/PANEL_SWITCHES.md`、`docs/MULTI_MACHINE_MODE.md` 的键表重新生成；面板 `dist/` 重新构建。

### 6.16 2026-10-11：面板版式——模型说的话加紫底、左栏多余紫块、B 档颜色、左下对齐与实际值、本地主脑模型行

所有者对着真界面指出的几处（真服务器 + 真浏览器逐处对过改前改后）：

- **对话**：人说的是一块白底，模型说的此前是光秃秃的字。现在模型说的也是一块**紫底**：紫只兑进透明里（不兑进白里），是一层透得见底的紫纱。两边同一个形：圆角 18、朝说话人那一侧的下角收成 6 的「尾巴」，块里行距比正文略紧；同一方连着说的几句合成一组（间距收紧，只有最后一句带尾巴角）。新来的一句才播进场，生成中紫底的投影随脉冲起伏（周期用已登记的 `--c-pulse`，躲开 0.17–0.25 Hz）；整组重绘时旧的不重放。
- **左栏卡片里那块多余的小长方形**：它是活动柱状图里唯一有数据的一天（其余几天高度为 0 看不见），又被框沿切掉下半截。没抽出来时不画；抽出那张时才画，每天留一小截底、依次长出来。
- **右下档位 B**：先是黄字黄圈（「这台机器装不下」），第一次改成「沉下去」，所有者仍说与其它不一致 —— 现在**四档长得一样**。装不下 / 没评估过只在上面那行字（「这台机器装不下」/「硬件没探到，没评估过」）和悬停提示里说。「自主」那枚小牌子原先写英文 `guided`，现在写中文档名（`/api/config/bundles` 带上 `option_labels`）。
- **左下「接上了什么」**：标题、点、右侧文字、底下那根线与上面卡片同一条左右边（此前各差 2–4px）。最后一颗「不知道」的空心圈两次被指出与其它点不一致 —— 现在「不通」与「不知道」同一个样子（看得见的暗点，此前 0.18 的白在浅底上一列里像缺了三颗），区别由右边那几个字（没装 / 没接口 / 没拉到……）说。
- **右下设置浮层（第三轮）**：每一行同一条左边（整档那几行、「本机模型」与 ABCD、「全部设置」此前差 10px），名字那一行与开关同一条中线（名字行高 = 开关高，多行副标题不再把开关拽到两行字中间），字块与开关之间 16px、名字与副标题之间 6px；副标题只在「 · 」处换行（此前「开= / 跨设备模式」被拆开）。**「自主」改成和上面一样的推拉开关**：开 = 「不逐步问人」，关 = 「读放行·写审批」，当前档名写在副标题里；三档的细调（含「敏感操作全问」）在「全部设置」里留着一行 —— 多态主键不再在 `/api/config/all` 里标 `bundle`。
- **左下清单改名**：后端 → 本体；本机模型 / 模型服务 / 其他设备 → 模型 / 服务 / 设备；容器运行时 → 容器。设备那一行只写实时台数（这台电脑也算一台，「1 台」）。**本体没连上时六行全部写「无」**（原委在悬停那一句）。
- **设置页「本地主脑模型」那一行**：7 个型号一行放不下，名字被挤成竖着的窄条。档位多（或字长）的行改成叠放，档位自己换行。
- **左下清单写实际的那个东西（第四轮）**：本体写正在答话的 Agent 的名字（`OpenClawd`）；服务写「验过的 / 一共」（`1/1`）；感知此刻正在感知（契约里的 `is_sensing`，隐私暂停时不算）写「正在感知」，否则写「无」；容器写实际用的运行时（`docker` / `podman`），一个都没有写「无」。本体与容器这两条由新的 `GET /api/v1/panel/self` 给：Agent 名只读模块里那个单例（不为报个名字把智能体建出来），运行时由 `core.container_runtime.current_runtime()` 只读探测 —— 与启动器同一个先后，但不写选择记录、不弹交互、不跑 `docker info`。面板开机问一次、每次重新连上再问一次。还没问到的写「没拉到」，与「无」分开。
- **型号显示首字母大写**：`gemma4:e2b` → `Gemma4:e2b`、`openbmb/minicpm-o4.5` → `Openbmb/Minicpm-o4.5`（`ui/model_name.ts`，左下清单、设置页本地主脑模型那一排、右下档位说明、灵动岛都过这一道）。**只改显示**：档位牌的 `data-value`、悬停提示、存进设置的仍是原串 —— Ollama 按原样认标签。

`tests/test_panel_self_reports_the_real_agent_and_runtime.py`（11 条）钉 `/api/v1/panel/self` 与只读探测（不建智能体、不写选择记录、两个都装又没选过时不替启动器挑）；
`tests/test_panel_thread_blocks_and_left_column.py`（13 条）钉这几处的源码形状；`test_config_bundles_are_real_switches.py` 改成核「整档那几行都是同一个开关、同一列」；`test_panel_has_no_decorative_boxes.py` 的「有权带 1px 线」名单去掉了档位牌的三条和「不知道」那颗点（都不再是线）；`test_panel_says_what_is_actually_wired.py` 改成核「不知道」由文字说出来。

### 6.17 2026-10-12：右下角托盘改成桌宠、三只桌宠同步；前后端那条线断了会自己回来

**托盘 = 桌宠，三只是同一只。** 屏幕上的桌宠有三只：面板里那只（`panel/src/ui/pet.ts`）、覆盖层灵动岛上那只（`renderer/app.js`）、右下角托盘那只（新的 `windows_service/pet_icon.py`，原来是一张品牌星云图）。

- **同一份推导**：`electron/renderer/pet_state.js`，面板 import 进来打包、覆盖层用 `<script>` 加载；托盘是 Python，与 node 那边跑**同一张用例表**（`pet_state.cases.json`）。原来两份 JS 推导讲岔过一件事：进程里没有感知库时，覆盖层那只眼睛虚着（「不知道」），面板那只却睁着（等于替后端说「它正看着」）—— 现在三只都是虚着。
- **同一个样子**：外形、眼缝、各档眼睛的位置与高度、三相的大小与深浅、三种反应的姿势、颜色，三处逐个相等（`tests/test_every_pet_is_the_same_pet.py`）。统一时改了两处：覆盖层的眼睛几何改成与面板一致；颜色三只同一套（面板 `tokens.css` 的 `--pet-*`）。所有者随后要「眼睛和皮肤的颜色调换一下，整体更明亮」：身子改为同一支紫提亮（`#a58bb5`，色相 312° 与面板这道坡一致、彩度只到 0.067，仍在莫兰迪一侧），眼睛近白（`#fcf9fe`），静 / 阈限两相的身子不透明度从 .72 / .88 提到 .86 / .94 —— 只对调不提亮的话身子是墨色，在深色任务栏上几乎看不见（对过）。
- **同一份帧、实时**：托盘与后端同进程，直接订阅在场桥广播出去的那一份 `payload.render`（`core/presence_fanout.py`），相位、睁闭眼、在不在收、上一拍的反应（演 1.6 秒就撤）都跟着变；只比几位、变了才重画（托盘图标重画在 Windows 上会闪）。托盘不做呼吸和眨眼 —— 那两样不声称任何事，每秒重画托盘只会闪。悬停那一句补上「正在感知 / 感知已暂停」。
- **感知变了也广播**：按隐私暂停、开始 / 停止在收，原来**没有任何事件**会顺带广播 —— 静息相位里没有下一帧，三只桌宠的眼睛都闭不上。在场桥现在每秒核一次感知那几位，变了才推（算一次约 1.5 µs）。

**前后端那条线。** 逐条对过之后真实的断点与修法：

| 断点 | 修法 |
|---|---|
| 半开连接认不出来（合盖再打开、后端被硬杀、网卡切换）：WS 在浏览器这边一直「开着」，不会重连，静息时看着正常、实际早就聋了 | 面板与覆盖层共用一份 `electron/renderer/live_socket.js`：15 秒一次 ping、40 秒内什么都没收到就当场拆掉重连（不等 close 事件）；连接 8 秒没 open 就放弃这一次；退避 0.4 秒起翻倍、封顶 10 秒、加抖动；**收到第一帧才清零**（原来连上就清零，后端接下又立刻关掉时一秒撞好几次）；网回来 / 窗口切回来立刻重连或立刻探一下 |
| 覆盖层只靠 IPC 推送：没有快照（覆盖层比后端先起来时静息里等不到第一帧），Electron 那个端口被占时整条是死的 | 覆盖层也直连 `/ws/desktop-presence`（连上即有快照），IPC 降为后备 —— WS 连着时只认 WS（同一拍两条路先后不定，后到的旧帧会把画面拽回去）；覆盖层窗口也拿到 `--galaxy-base`，兜底地址从 `localhost` 改成 `127.0.0.1`（Windows 上 localhost 先解析到 ::1） |
| HTTP 请求没有期限：后端事件循环被占住或连接没断干净时请求一直挂着，那一块永远停在「正在拉」 | 面板每一条请求都过 `fetchT`：读 20 秒、网络抖一下**再试一次**；写 60 秒、**不重试**（不知道上一次到没到）；换档、装 GitHub 项目、喂文件、重跑步骤、对话流本来就慢，不设期限 |
| 开机那一拨只拉一次：面板比后端先起来时拉到的全是「没拉到」，之后再没人去拉 | 连上时补一遍：第一次连上只补没拉到的，再连上就全部重拉（档位、端点、整档开关、厂商、GitHub 项目、隔离队列、本体、历史）；正在出字或正在看某张卡时不动历史 |
| 把「没问到」当成「会话过期」：拉历史失败（后端还没起来）时把本地记的会话 id 删了，对话被忘了 | `fetchHistory` 分三种结果：读到 / 后端说不认识（404）/ 没问到；只有第二种才丢本地那条 |
| 重连上来的面板设备名册是旧的（名册只在设备事件时才推） | 新连上的客户端先补一份 `panel_feed`，不打扰别的客户端 |

连接本身的行为由 `live_socket.test.js`（node，假 WebSocket + 假时钟，12 条）钉住，桌宠推导由 `pet_state.test.js`（19 条）钉住，两份都进了 CI；接线与后端一侧由 `tests/test_frontend_backend_link_stays_up.py`（19 条）、`tests/test_every_pet_is_the_same_pet.py` 钉住。真服务器 + 真浏览器按时间线跑过一遍（每秒记一次两只桌宠与左下清单）：面板与覆盖层**先于后端**打开，后端就绪后 1–3 秒两边自己连上，面板补齐了本体 / 模型 / 服务 / 容器；按隐私暂停，两只桌宠 1 秒内一起闭眼，恢复后一起睁开；后端停掉，面板六行立刻全写「无」；后端重启，覆盖层立刻连回；后端被冻住（SIGSTOP，模拟半开连接 —— 端口还在、谁也不回），连着的覆盖层 37 秒后认出它死了（不等 close 事件），解冻后 1 秒内连回，面板解冻后约 4 秒连回并补齐。托盘（pystray）在这台无桌面的机器上起不来，画法按同一帧逐档渲染核对过，真机上的观感需要在 Windows 上看一眼。

### 6.18 2026-10-12：面板整张等比缩放、四角白边、任务栏桌宠；Windows 启动日志逐条；arXiv 本地文献库

**面板。** 所有者：「把上下左右角一放缩，有些东西就被揉起来了……像面团一样，不像一个完整的整体」「4 个角还是有那种矩形的白边」。

- **整张等比缩放**：桌面外壳里面板是一张 1200×700 的固定画布（`electron/renderer/panel_stage.js`，主进程与面板共用），窗口多大只决定把它整张放多大（`transform: scale`），里面不再重新排版；拉伸由面板四边四角的手柄发起、主进程按光标**锁宽高比**改窗口大小，下限 0.6 倍、上限工作区。真 Electron（xvfb）里跑过：拖右下角缩到 800×467，排版与 1200×700 那张逐像素同构，设置浮层一起缩；松手后锁住；拖过下限停在 720×420、对角不动。
- **四角白边**：页面这边四角早就是透明的（Chromium 实测 alpha=0）；剩下那一圈是 Windows 给带粗边框（WS_THICKFRAME / WS_CAPTION）的窗口沿**窗口矩形**描的系统边。面板窗口改成 `thickFrame: false` —— 系统不再描边，也不再替它拉伸，所以拉伸改由上面那套手柄做。Windows 上的观感需要真机看一眼。
- **任务栏图标**：旧的星云图换成同一只桌宠，由 `scripts/render_app_icons.py` 从托盘那套画法逐尺寸现画（.ico 九个尺寸、Electron / Tauri 两套），`tests/test_every_pet_is_the_same_pet.py` 核对文件就是现画的。

- **左下角「设备」只有一台电脑却写「2 台」**：后端名册里总有本机那一条（`desktop_local`「本机 Desktop」），面板那一行当它不在、再 +1，于是算了两遍。现在先剔掉本机那条再 +1（灵动岛上的「x / y 在线」本来就按名册原样数，两处口径一致）。
- **启动横幅还写「暖金边缘氛围光」**：覆盖层第一态早就是左·右·上三条边的紫调氛围光，横幅、外壳日志、网页图标（`core/brand_icon.py`，一圈暖金圆环）都没跟上。横幅与日志改成如实的说法；网页图标换成同一只桌宠（外形、眼缝、颜色与`windows_service/pet_icon.py` 逐项相等，`tests/test_the_panel_has_an_icon_instead_of_a_404.py` 核对，也守着这几处不再出现「暖金」）。

**启动前配置检查**：OPENAI / ANTHROPIC 两条只留「键名 — 谁的密钥」（所有者原话），不再出「怎么办」。

**Windows 启动日志逐条：**

| 日志里的样子 | 根因 | 修法 |
|---|---|---|
| 15:26:52 / 15:26:54 一批 GET 同一毫秒完成、各 3 秒 / 5 秒 | `WhisperASR` 在事件循环里同步做：探下载源、`import torch`、首次下 145 MB 模型、载入 | 挪到工作线程；另加 `core/loop_stall_watch.py`：事件循环停跳 1 秒以上就取那根线程的调用栈，恢复后记一行「卡了几秒、卡在仓库哪几行」—— 以后同类日志直接指出凶手 |
| faster-whisper 首次下载的四条进度条刷屏 | huggingface_hub 的 tqdm | 进度条关掉（`core/hf_endpoint.quiet_progress_bars`），改成一行「首次下载，只这一次」 |
| `Timeout from ollama (attempt 1/3), retrying` | 本机读期限 60 秒、超时整段重发 —— CPU 上长提示预填就要一两分钟，重发等于从头再算、负载翻倍 | 本机 Ollama：读 300 秒、连 5 秒，超时不重发，流式超时也不再换非流式重算（`core/local_llm_policy.py`） |
| 「4 降级」里有消息总线、L4 增强模块、节点 0/13 | 本地模式不起 NATS 是对的；L4 按设计不接主循环；13 个节点进程都活着只是 5 秒内没就绪（单个节点沙箱里 1 秒就绪，那台机器同时在下模型、跑推理） | 本地模式总线 ✓ 不进降级栏；L4 一行照说不算降级；节点全是「活着、还在起来」时说「N 个还在起来（起来后自动接上）」不算降级（`launcher/bus_phase.py`） |
| `mDNS: failed to start:`（冒号后面是空的） | 本地模式也在往局域网广播；名字被占用时 zeroconf 抛的异常没有消息文本 | 本地模式不入 tailnet、不广播（只用这台电脑）；跨设备模式下名字冲突自动换名；失败时连异常类型一起说 |
| Phase 0「⏱ Ollama 12s 没有回应」「⚠ 这次没查完」 | Ollama 服务没在跑时 `ollama list` 会先把它拉起来再等，首启十几秒 | 不画 ⚠，说「多半是它正在起来；后面会再确认」（依赖阶段与 AI 大脑那步本来就会再问） |
| 「请先运行 chcp 65001 再启动 Galaxy」 | 每次开机都教一遍 | 自己切到 UTF-8（`SetConsoleOutputCP`），退出时切回原来的代码页；切不了才提示 |
| 系统播放声采集不可用，同一件事两行 | 探测与开流两处各说一遍；PyAudioWPatch 只在日志里教人装 | 只说一次；Windows 上 PyAudioWPatch 随启动补装（几百 KB 的现成轮子） |
| 「20 秒内 VAD 从未判定为说话」 | 开机 20 秒没人说话是正常的 | 一直安静只记日志文件；有人声那么响（均方根 ≥ 0.02、≥ 5 块）却没判成说话才告警 |

感知帧 / 音频上传的 0.5–1 秒是 CPU 被本机推理占满时的排队（接口本身只存一份快照、鉴权只比字符串）；真正的大卡顿（9.8 秒、5 秒）是上面那几处。之后若还有，卡顿探测会写明卡在哪。

**arXiv 本地文献库。** 所有者问 Hugging Face 上那份 arXiv（`secemp9/arxiv-complete`，314 万篇、16.08 TB）怎么接：「调用好像要付费」「十几 TB 电脑塞不下」。从 Hugging Face 下载不收费；16 TB 里 15.8 TB 是 PDF / 源码 / PostScript，检索与阅读用不上。做法：

- **目录在本机**：只下 `metadata`（1.6 GB，固定版本 `cee89483`，2026-08-30 快照），流式导进 `$GALAXY_DATA_DIR/arxiv/library.sqlite3`，导完一个分片删一个、断了从没导完的那个接着来；标题 / 摘要 / 作者建 FTS5（BM25，标题 ×10），分类与日期按字段过滤（会改变控制流的读取走确定性查询）。可只导部分分类。
- **全文按需**：本机缓存 → 本机全文分片（若下过 70 GB 的 `paper_text`）→ 向 arXiv 要**这一篇**（HTML 版优先，没有再 PDF），gzip 存盘，总量 2 GB 封顶、最久没读的先丢。
- **每天增量**：建库后检索时离上次超过一天，后台走 arXiv 官方 OAI-PMH 补新论文 / 改动 / 撤稿。
- **守 arXiv 的规矩**：`core/arxiv_client.py` 是唯一出口 —— https、全进程每 3 秒最多一次、单连接、503 照 Retry-After 等。原先 `academic_retrieval` 与 Node_97 两处直连 `http://export.arxiv.org`、不限速，都改走它。
- **工具**：`academic__arxiv_search` / `academic__arxiv_read` / `academic__arxiv_library`；会下东西的维护只在人自己发起的回合里做，70 GB 全文分片还要人点头（`confirm`）。`pyarrow` 不进依赖锁定文件，第一次建库时按需补装。
- **没核实的**：本沙箱连不上 huggingface.co 与 arxiv.org，数据集的列名按数据集卡片与第三方项目里出现过的名字做了别名映射（认不出的列空着、不猜），导入流程用假分片端到端跑过；真下载要在能上网的机器上验一次。全文的许可按每篇论文自己的，只在本机检索、阅读。

### 6.19 2026-10-12：面板白边的真正原因；启动控制台只留结论；事件循环三处卡顿；模型下载误判

所有者拍了合并 #1663 后那次 Windows 启动的照片，六件事：

- **面板白边还在**：放大照片看清，白的是**窗口矩形本身**（方角），面板圆角落在里面，上沿还露一条白带 ——
  那台机器上面板窗口的透明没生效（同一台机器上覆盖层是透明的。两者一个已知差别：Electron 在 Windows 上会给
  `setIgnoreMouseEvents` 过的窗口加分层样式，覆盖层有、面板没有；但没有 Windows 环境复现，不能断定就是它）。
  页面这边早已全透明、按圆角裁过（沙箱里逐像素核过），再怎么改页面都没用。
  现在窗口的**外形交给系统裁**：主进程按 `PanelStage.shapeRects()`（画布那一块、四角按同一个半径倒圆）调
  `setShape`，每次改大小重算；圆角外、窗口比例没对上时多出来的那条，都不是窗口的一部分 —— 不画、不接鼠标，
  透明生不生效都一样。真 Electron（xvfb、无合成器）里截屏核过：圆角外与多出来的那条透出的是下层窗口。
  页面的裁剪与拉伸手柄也改成贴着画布而不是贴着窗口；画布偏移取整像素，边上不再有半透明的一整行。
- **补装依赖时 pip 输出整段上屏**：pip 不再直通终端；等的时候一行「· 补装缺的依赖 …」，装好擦掉，只留
  「✓ Python 核心依赖 已补装 PyAudioWPatch」。失败才把 pip 的原因带出来。
- **事件循环被卡住（三种）**：
  - `13.8 秒 —— 卡在 main.py emit`：卡在**往控制台写日志**上（Windows 控制台被选中文字时挂起所有写入）。
    日志改由一根专门的线程写（`core/console_log.py`，`QueueHandler` → `QueueListener`），事件循环只放进队列就走。
  - `2.1 秒 —— 卡在 proc_text.run_text`：网关一起来就写 `runtime/entrypoint.json`，里面同步跑 `tailscale ip -4`；
    「启动自检」的 `git log` 同理。两处都挪进线程。
  - `3.8 / 1.6 秒 —— 卡在 <frozen importlib…>`：先修了卡顿探测本身 —— `<frozen …>` 这种不是文件的帧被当成仓库代码，
    真正发起 import 的那行反而没露面。改完后沙箱真跑抓到完整栈：一是 FastAPI 0.141 在**第一个请求**时才在循环里
    给全部路由建校验模型（现在网关起来前在旁边线程里先生成一遍 OpenAPI，第一个请求 0.7 秒 → 0.01 秒）；二是周期
    清扫第一次在循环里 import 安全策略加载器、还要等别的线程的 import 锁（2.8 秒；清扫现在不替没人加载过的模块
    import）；三是托盘 import pystray / Pillow / win32（挪进线程）。
- **控制台上的 WARNING**（卡顿位置、慢请求、下载源探测、某个模型这次没拉下来）：启动器每一项自己有一行 ✓ / ⚠ 结论，
  这些是过程诊断。现在**控制台只上结论和错误**，警告一个字不少地进 `logs/lumiv.log`；`python main.py -v` 时照旧上屏。
- **两个模型下载失败、语音交互未启用**：`HF 下载源均不可达(hf-mirror.com / huggingface.co)` —— 同一台机器此前下过
  Whisper。原先每个源 2 秒、挨个探，启动那阵机器被压满时两边都超时，随后 5 分钟只认本地缓存。现在两个源**并发**探、
  每个 6 秒、全不通隔一秒再补探一轮；识别模型这次仍没下下来时，语音交互后台每 3 分钟强制重探一次，下好自动开启，不用重启。
- **Podman 首次拉镜像算成「降级」**：第一次拉镜像是「还在做」，改为与节点「还在起来」同一档（·），不进降级栏。

### 6.20 全面排查（每 7 小时一轮，直到彻底优化完成）

所有者：「把目前系统已经完整运行起来的能力，大大小小的问题全部排查一遍，并且全部解决，进行一整套完整的优化，
确保它稳定、持续、可行。还是每 7 小时定一次，直到彻底优化完成」。每一轮：独立数据目录真跑 `python main.py --backend -v`，
收集全部 WARNING / ERROR / 卡顿 / 慢请求 / 异常栈，再逐个打主要接口，逐条修根因、补测试钉住。沙箱里没有的东西
（Ollama、PortAudio、图形环境、HF / 微软 TTS 的网络）造成的告警只记不修。

**第 1 轮（2026-10-13）修了：**

- **没配模型时 ERROR 刷屏**：一条对话消息要路由七八次，每次都记 ERROR「没有可用的 LLM 提供商」+「所有提供商调用失败: []」，
  两分钟几十条，而且 ERROR 会上控制台。「一个都没配」是状态不是故障：每 10 分钟提醒一次（WARNING，`note_nothing_configured`）。
  试过却都失败的照旧是 ERROR。
- **事件循环卡顿（又两处）**：`GET /api/v1/projection/operability-contract` 等四条就绪度路由在循环里汇总报告（首次还要 import
  验收判定那一大块，1.1 秒）→ 工作线程里汇总；常驻注意力循环第一拍在循环里 import 感知存储（0.6–1 秒）→ 第一拍前在旁边
  线程里把每一拍要用的模块 import 好。
- **持久化状态没跟数据目录走**：会话（`sessions.json` 与证据链目录）、会话真相快照、生成的 MCP 工具目录写死在仓库 `data/` ——
  真跑设了独立数据目录，启动仍从仓库里读回了 200 条别处留下的会话真相。改为 `data_path_or_legacy`（仓库里已有的继续用），
  并加扫描测试：`core/` 里不许再写死仓库 `data/`。
- **记忆节点在本机建不了库**：`.env.example` 写着 `MEMORY_DB_PATH=/app/data/galaxy_memory.db`（容器路径），启动时自动从模板
  生成的 `.env` 把它带到本机，`--check-only` 报 `Node_100_MemorySystem: unable to open database file`。模板不再给值；
  节点遇到「容器路径而这里不是容器」或目录建不出来时回落到数据目录（已有 `.env` 里带着旧值的也一样能用）。
- **停机不安静**：Ctrl+C 后控制台冒出一段「--- Logging error ---」栈 + aiohttp ERROR「Unclosed client session」。在场桥共享的
  IPC 会话停机时关掉；解释器退出阶段的日志不再打栈（上一轮引入的日志队列在那一刻不能 `copy`）。
- **`--backend` 说错原因**：主动不起桌面壳，横幅却写「未启动」算进降级、日志猜「缺 Node.js」→ 照实写「按 --backend 跳过」（·，不算降级）。
- **设置明细把密钥原值发给任何人**：后端监听 `0.0.0.0`，设置这组又没挂鉴权，`GET /api/config/all` 却把 30 个密钥类键的**原值**
  整份返回（各家 API Key，连同鉴权令牌 `GALAXY_API_TOKEN` 本身）——同一局域网里任何一台机器 GET 一下就全拿走。面板本来就不回填
  密钥，只要「配没配」：现在密钥类给掩码 / 空串，写回来的掩码当没改；「什么算密钥」后端与面板 `ui/settings.ts` 用同一条规则
  （`_TOKENS` 也算，`tests/test_settings_never_send_secret_values.py` 核对两边一致）。

**所有者真机日志（同一轮，2026-10-13 第二张）：**

| 日志 | 原因 | 处理 |
|---|---|---|
| 事件循环被卡住 92.4 秒 —— 卡在 `main.py:382 emit`；紧跟着 `chat_stream 超时(90s)` 与十几条 93 秒的慢请求 | 行号对的是 #1664 之前的代码：控制台写入还在事件循环里，控制台被点选（QuickEdit）挂起了 92 秒，对话流的 90 秒期限就在这期间到点 | #1664 已修（写控制台在专门的线程；WARNING 只进日志文件，这张照片里的 WARNING 行也不会再上屏）。更新到最新即可 |
| 事件循环被卡住 2.2 秒 —— 卡在 `ollama_url_sentinel _sync_send ← _scan_local_models_sync ← route_hint_sync` | `OpenClawd._select_multimodal_route` 是同步的，问「本机有没有模型」时当场同步 `GET /api/tags`（3 秒超时），首次还要算硬件画像（import torch）；构造这个路由器时又同步探一次 Ollama | 事件循环里只读缓存，过期交给一根后台线程刷；构造不做 I/O |
| 事件循环被卡住 1.3 秒 —— 卡在 `tray_icon.py _redraw ← on_render ← presence_fanout _call` | 托盘桌宠跟着在场桥每一拍重画，回调在事件循环线程里；画一张桌宠 + 改托盘图标（`Shell_NotifyIcon`）就在循环里做 | 循环里只比变没变，真画交给一根专门的线程（按顺序画） |
| 事件循环被卡住 11.5 秒 —— 卡在 `lumiv_websocket_bridge.py:818 _try_ipc_http`（`session.post(...)`） | 这一行本身不会慢（连接异步、超时 1 秒）。最可能是循环线程在等 GIL：别的线程正 import 大的原生库（Windows 上一次好几秒）。只看循环线程的栈，这类卡顿永远指错人 | **没有猜着改**：卡顿记录现在多给两样 —— 最里面卡在库的哪一行、同一时刻别的线程在 import 什么；下次同类日志直接说出是谁 |
| 感知帧 / 音频上传各慢 0.5–1.2 秒（不在上面任何一次卡顿里） | 两个接口本身只是把数据放进内存；是循环被零点几秒的同步活占着，而卡顿记录的门槛是 1 秒，没留下凶手 | 卡顿记录门槛降到 0.5 秒（与慢请求门槛一致，只进日志文件） |

照片之后又真跑了一遍（独立数据目录 `python main.py --backend -v`）：照片里那几条接口单独打都是 3–30 ms，400 KB 的一帧 6 ms；
按面板的节奏（每 2 秒一帧 + 音频 + 面板轮询）压 30 秒，没有一条慢请求、没有一次 0.5 秒以上的卡顿。新的卡顿记录当场又抓出两处：

- **端口上已有 NATS 还再起一个**：容器基础设施已经拉起 NATS（4222），内置 nats-server 照样再起 —— 端口被占立刻退出，控制台一条
  原因为空的 ERROR「NATS server exited:」（输出接的是 DEVNULL，却去读 `process.stderr`），随后又连上容器那个、横幅照打 ✓。
  现在先看端口上应答的是不是 NATS（服务器先发 `INFO`），是就直接用；真起不来时说退出码、端口是不是被占。
- **停机时逐个等节点退出**：每个节点 terminate 后各等最多 5 秒，停机时间是各自之和（循环卡 2.6 秒）→ 一起 terminate、一起等。

（这次沙箱里的 `.env` 是旧模板生成的，里面明写着 `GALAXY_NATS_ENABLED=true`，所以本地模式也起了总线 —— 「写了就听它的」。
现在的模板已经把这一行注释掉；早先生成的 `.env` 里若还有它，删掉那一行即可回到「本地模式不起 NATS」。）

**第 2 轮（2026-10-13）：** 本机起一个假的 OpenAI 兼容模型（含流式），`OPENAI_API_BASE` 指过去，把对话全链路真跑一遍；
再从容器的局域网地址不带令牌把接口挨个打一遍。修了：

- **单 Agent 执行完，回答永远是「任务已完成」**：`ExecutionPlanner` 单 Agent 路径只读回执顶层的 `reply` / `result` /
  `success` / `tool_calls` / `provider`，而 `AgentFactory._run_agent` 的回执把它们都放在 `results[*]` 里 —— 模型说的话被丢掉，
  失败也算成功，工具调用与厂商记录全空（真跑：让它讲个笑话，回答「任务已完成」）。改由 `core/agent/agent_receipt.py` 读整棵回执
  （含分裂的子 Agent 与串行重跑）；执行失败就说没做成、没有模型就说没真正执行。单个任务的结果还带上了真正写出回答的**型号**
  —— 原先回答里报的是路由器默认型号（`gpt-5.6`），实际写回答的是 `gpt-6-astra`。
- **同一局域网不带令牌就能操作这台电脑**：鉴权默认是开的，但对话、设置（含 `POST /api/config` 改 `.env`、能把鉴权本身关掉）、
  自加模型、`/api/v1/ui/act`（点界面）、`/api/v1/computer-use/task`、记忆、会话、代码生成这几组挂载时没带 `_auth_deps`，
  后端又听 `0.0.0.0`。真测：不带令牌从局域网 `POST /api/v1/ui/act` 回 200。网关自己的 `/api/v1/chat` 本来就要鉴权，只是同路径这条
  先注册先命中。现在一起挂上鉴权；面板与 Electron 主进程每个请求都带本机令牌，不受影响（`tests/test_lan_cannot_drive_this_computer_without_a_token.py`）。
- **容器里重建一次就丢的状态**：自加的模型服务、OAuth 连接、档位与主脑、上下文归档（被压掉那段对话的唯一原文）、上下文实测、
  推测解码实测、Agent 供给偏差日志、元层 artifact 存储都写在仓库 `runtime/` 下 —— 容器里只有 `/app/data` 在持久卷上。改为随数据目录走，
  `runtime/` 里已有的继续用。`runtime/config.json` 与 `secrets.env` 有好几处读者、启动第一行就要读，留到下一轮单独做（动错会丢 Key）。
- **测试写进开发者自己的数据**：conftest 把数据目录指到临时目录，旧位置兜底又把它绕回仓库 `data/` / `runtime/`（仓库里留着
  `s6`、`sess_role_test` 这些测试会话）。测试里仓库自己的旧位置一律不算。
- **任务记忆存的不是用户说的话**：每条摘要后面挂着 `[Multimodal context: …]` 与 `[desktop_context_strategy …]`，经验制导拿它做 BM25。
  入库前剥掉（用已有的 `strip_appended_annotations`，用户自己写的方括号不动）。
- **启动卡 0.5 秒**：新的卡顿记录当场说出是 uvicorn 在循环里 `import uvicorn.protocols.http.auto` —— `config.load()` 挪到线程里先做。

**第 3 轮（2026-10-13）：** 接第 2 轮的待办；独立数据目录真跑两遍（改之前、改之后），从容器的局域网地址不带令牌把整个
权威 API 层逐条走一遍。修了：

- **面板存的 Key 随数据目录走**：`config.json` / `secrets.env` 原先写死源码树 `runtime/` —— 容器里只有数据目录是卷，重建一次
  面板上填的各家 Key 就没了。四处读者一起改（`ConfigStore`、`config_preflight`、`launcher/env_check`、`main.py` 启动第一步），
  `runtime/` 下已有的继续用（一个 Key 都不丢）；`main.py` 那一步跑在 import core 之前，只能照抄规则，测试逐个场景核对两边指向同一份
  （只有老位置 / 两处都有 / 数据目录只写在 `.env` 里 / `.env` 里写成注释或留空）。自建 tailnet 的 `deploy/headscale/init.sh` 往
  密钥库里写网关 Key，也按同一条规则。`data/.gitignore` 挡住 `*.env`。顺带两处：
  - 启动自检「`.env` 比模板少了哪些键」一直没把密钥库算进去 —— `from core.unified.config_store import …`，没有这个模块，异常被吞。
  - 真跑：`secrets.env` 建出来是 **0644**（同机任何账户都能读各家 Key），而且 `open(..., "w")` 先清空再写，写到一半进程被杀就全没了。
    改成与 JSON 状态文件同一个原子写（`atomic_write_text`，0600）。
- **同一局域网不带令牌还能调的写接口（74 条）**：把权威 API 层 499 条路由逐条展开看依赖，没挂鉴权的写接口 74 条，里面有
  `POST /api/v1/agents/linux/servers/{id}/execute`（在登记过的服务器上跑命令）与 `/api/v1/agents/sandbox/execute` —— 这两组是
  从网关并过来的，在网关 app 上它们在全局 Bearer 中间件后面，而后端这个 app 没有那层中间件；还有人在环的「批准」本身、给手机
  下命令、派发任务、对话记忆卡片（读）。现在除健康检查 / 文档 / 可观测 / 设备自注册外都要令牌，不带令牌能调的写接口只剩
  设备自注册与心跳、参与方（端点自己核验入口令牌）、配对、OAuth 登录；`test_every_write_needs_a_token_unless_listed` 逐条扫，
  新加的写接口忘了挂鉴权会红。真跑：局域网地址不带令牌全部 401，带本机令牌照常；面板与 Electron 主进程每个请求本来就带令牌。
- **「保存设置」把进程这一次推出来的值钉进 `.env`**：真跑（`--backend -v`）在面板上存一个 Key，`.env` 里多出
  `GALAXY_SKIP_ELECTRON=1`（之后正常启动也不开桌面窗口）、`GALAXY_VERBOSE=1`、`GALAXY_NATS_URL=nats://localhost:4222`（非空就算
  「要用总线」，本地模式也起 NATS —— 第 2 轮待办里「本地模式 `nats_enabled: true`」也有这一份）。保存是把 `os.environ` 整份写回，
  分不清人配的和进程运行中写进去的。现在后者经 `core.derived_env.export` 写，保存时换回人配的（没配过就不写）：`--backend` /
  `-v` / `--model`、内置总线地址、本机推理服务地址、B 档原生在线、按硬件临时降的档（注释写着只影响本进程，钉进去就是永久降档）。
- **每条消息整份重写 `sessions.json`，在事件循环里**：本机 20 个会话 11 ms 一次，30 个满会话 2.6 MB 76 ms 一次，一轮对话三次
  （`ensure_session` 每轮都写一次）。现在在工作线程里写、调用方照旧等写完；快照与写入同一把锁（后来的一定写后来的状态）；
  不缩进，`atomic_write_json` 改成先 `json.dumps` 再写 —— `json.dump` 不论缩进都走纯 Python 编码器，`dumps` 在不缩进时走 C 实现，
  快几倍，产出逐字节相同。
- **任务投影库写死仓库 `data/`、第一次建卡循环 0.6 秒**：`canonical_tasks.jsonl` 用 `os.path.join(…, "data")` 拼路径，上一轮那条
  「core 里不许写死 data/」的扫描没认出来 —— 容器重建就丢，测试也绕不开（仓库里那份被测试写到了 16 MB）。改为随数据目录走（已有的
  继续用）；热层只要最新的五百条，启动只读文件末尾 4 MB，并在启动时旁边线程里先建好。
- **测试隔离**：预检用例在别的用例核验过鉴权配置之后就不再签本机令牌、资源表用例撞上别的用例留在拓扑图单例里的 MagicMock、
  卡顿记录用例在机器忙时采到调用间隙 —— 三条只在特定顺序 / 负载下红，各自修掉。

- **设备自己从 REST 来登记，改成在面板上确认**（所有者定）：`POST /api/v1/devices/register` 与旧的 `/api/devices/register`
  原先不查任何凭据就写进设备表（UDM）—— 同一局域网谁都能登记一台假设备、接到派过去的任务（安卓走 WS 有带内认证；非安卓设备的
  通用入口自己核验入口令牌；只有这两个口敞着）。现在陌生设备只记成设备接入平面的候选（接入路径 `self_registered`，回 202），
  面板「全部设置」最上面多一段「等你同意的设备」，点「接入」才经接入服务按统一口径写 UDM、花名册、Mesh；点「不接入」以后它再来
  也被拒（403）。`GALAXY_ONBOARDING_AUTO=approve` 不放行这一类（不带凭据，除了人没有依据）。鉴权关着、带主人令牌、本来就是成员的
  照旧直接登记；心跳 / 状态对陌生设备本来就 404，不会顺手建出一台。对话里第一次见到时说一声去哪儿点。

**第 4 轮（2026-10-13）：** 接第 3 轮的待办；独立数据目录真跑，把不带令牌能读的接口逐条看完，再把运行日志里刷屏的那几条追到根上，
顺着同一种缺陷签名把全仓扫了一遍。修了：

- **不带令牌能读的接口（约 100 条）**：后端这个 app 没有网关那层全局 Bearer 中间件，读接口里有审计轨迹（带对话原文）、上下文层、
  设备列表与设备细节、运行时投影、隔离队列、SSE 事件流、可观测与监控两组。现在不带令牌能读的只剩健康检查、`/metrics`、客户端
  配置发现（`GET /api/v1/config`）、OAuth 登录那几条；`test_every_read_needs_a_token_unless_listed` 逐条扫，新加的读接口忘了挂鉴权
  会红。启动横幅里那条「状态面板」链接（指向投影接口，浏览器直接打开会 401）一并去掉。真跑：局域网地址不带令牌全部 401。
- **冒用设备号改资料**：设备号就写在请求体里。成员不带凭据来重新登记，原先拿请求里报的名字 / 类型 / 能力覆盖 UDM 与能力表 ——
  冒用一台手机的设备号就能改它的名字、给它添上没有的能力。现在只认已登记的（报到照收），改资料要主人的令牌。新旧两个登记口同一条规则。
- **PR 上 CodeQL 两条高危**：密钥库改走原子写时把写入点挪进了新函数（被识别成新的路径注入点）、`secrets.env` 的路径进了日志。
  `atomic_write_json` 恢复原结构、`atomic_write_text` 单独成函数；那几条日志不再带路径。
- **运行日志每 3 秒 24 条 WARNING**：设备参与度对每台设备各调三个**不存在的**入口（`BodyMeshRegistry.get_instance`、
  `get_active_session_for_device`、`get_active_mesh_session`），一轮真跑 600 多条 `Exception suppressed: cannot import name …`，
  而「这台设备在不在 mesh 里、在不在哪段会话里」从来答不出来。现在读进程里真有的两份：Body Mesh 注册表单例、mesh 会话生命周期
  协调器里状态为 active 的会话（还没开始的会话不算）。
- **同一种缺陷签名全仓扫一遍**（函数体里 `from 仓库模块 import 名字`，名字不存在，包在 `try` 里一声不响地退成「不可用」），19 处：
  - `/api/v1/vision/understand` **每次 500**：把协程方法丢进线程池，拿回没 await 的协程对象，序列化时炸 —— 这个接口从来没成功过；
    设备 WS 的 `ocr_request` 同一个错。`/api/v1/vision/ocr` **永远回失败**：`DeepSeekOCR2Adapter` / `process_image` 都不存在。
    现在 await 视觉管线（它自己按登记表逐档降级）；OCR 按模式调适配器上真有的方法，没配 Key 就说该配哪个。
  - 调度真相 harness 永远答「能力策略不可用」、永远判不收敛 —— 那两份真相是模块级函数，没有它调的单例。
  - 会话连续性权威快照里「恢复加固未加载」是假的（常量名写错）；多设备治理的附着会话从没算进去（函数名写错）；叙事层每次往 trace
    里记一条假的 `android_recovery_failed`；草稿基准数 token 永远走粗估。
  - 网关 `create_device_websocket_routes`：没人调用，一调就注册一个连上即关的 `/ws/device/{id}`；它和它依赖的 5 个不存在的名字删掉
    （规范入口是 `register_websocket_routes`，不受影响）。
  - 运维动作「挂起参与方 / 隔离设备 / 重开·确认·驳回闭环」里调的本地写入口从来不存在 —— 删掉死调用，行为不变（照旧只下发给设备 /
    记「已请求」）。
  - 守卫：`tests/test_lazy_imports_name_things_that_exist.py`（只核对本仓自己的模块；`external/` 与微软 UFO 的 `agents.*` 是外部代码）。
- **没模型时日志把原因说错**：一个模型都没配时，`chat_json` 拿给人看的降级说明去 `json.loads`，记一条「chat_json 解析失败」，
  Agent 工厂再记一条「schema 校验失败、回退模板」、任务分解记「LLM 返回非法 JSON」。现在 `chat_json` 认得出「没调通」，直接回
  `{"error": …, "unavailable": True}`，两个调用方按「没有模型」处理（Agent 用模板、任务按单任务），不再报解析 / 校验失败。

**第 5 轮（2026-10-13）：** 所有者定了三件事（「整合成一个整体，按现场情况挑」「选 A」「借 WisLand 的灵动岛做完整功能拓展，
桌宠不变」），连同第 4 轮待办里的前两条一起做完。

- **桌面自动化是一个整体，按现场挑**（`core/desktop_automation.py`）：系统接口（Win32）、控件（本仓 UIA 与微软 UFO）、坐标
  （自动控制节点 Node_92 与桌面操作节点 Node_36）、视觉（交给 Computer Use）原先是四套各自的入口，彼此不知道。现在仍从仲裁器
  （`core/windows_execution_arbiter.py`）一个口进，每一级下面是一张后端登记表：这一级谁能用（`make()` 说得出用不了的原因）、
  这一步该先试谁。排序看三样：动作本身（只给了坐标就跳过控件级、没给要找的名字就跳过系统接口级）、**当前前台应用**上各后端的
  战绩（按「应用 × 后端」记在数据目录 `desktop_backend_record.json`，试过三次以上、成功率低于三分之一的往后挪）、现场探测
  （库在不在、节点在不在）。**只重排，不删兜底**；视觉永远最后。Computer Use 在本机落手也走这条（原先直接派节点）；Windows
  Agent 在本机时同样走它（只用结构化三级，不递归回视觉）。微软 UFO 原先永远不生效（引用的类不存在），现在按它真有的
  `ControlReceiver` 接口接上；仓库里那份 `external/microsoft_ufo` 是不全的源码，要装了 `ufo` 包才算可用，没装就照实说。
  `GET /api/v1/computer-use/status` 多一段 `desktop`：每一级每个后端能不能用、为什么、此刻前台是谁。
- **Computer Use 的结果进真相链（选 A，`core/computer_use_verdict.py`）**：原先模型回一个 `done` 就算成功。现在那只记为自报
  （`claimed_done`）；裁决另起 —— 重新取一张**当前**屏幕，交给只看「任务 + 这张屏幕」的核对请求（看不到规划过程与自报，60 秒期限），
  结论由 `classify_execution_evidence()` 给四值：核对说做完了 → trusted；没做完 → quarantine；没法核对（没屏幕、没能看图的模型、
  回答认不出、超时）→ provisional，照实写「没法独立核对」。没收口的与 task_result 同一条规矩：后台把**没做完的部分**再做一次、
  再核对一次，仍不行进「没收口的结果」（`kind="computer_use"`）；人正在用电脑时不在后台动键鼠，直接进队列。模型自己放弃 /
  步数用完 / 看不到屏幕的本来就没说做完，不进队列。仲裁器视觉级只是调用方任务里的一步：核对照做，但不排后台重做（会和调用方的
  处置撞车）。
- **运维的「重开 / 确认 / 驳回」落在这个队列上**（第 4 轮待办）：重开 = 再试一次、确认 = 认可（新：`POST /api/v1/results/isolated/{key}/accept`，
  人看过、认它做完了）、驳回 = 知悉（判它没做成）。原先这三个动作调的写入口不存在却一律回 success —— 现在找不到这条就照实回 failed。
  面板「没收口的结果」多「认可」一个键，Computer Use 那类卡片写「说做完了，对着屏幕核对没通过：…」，后台在重做时显示「正在再做一次」、
  隔几秒自己刷新。
- **灵动岛（借 WinIslands 的上岛推送，`core/island_cards.py`）**：岛原先只在阈限态与动手时出现、只写一句状态。现在这台电脑上刚发生、
  人该余光知道的事会上岛成一张卡 —— 桌面操作走到第几步（带进度线，Esc / 「停下」）、核对的结论、有结果没收口（只给条数）、有设备在等你同意
  （面板上定了就撤）。一张卡一个 id 原地更新、分先后、会过期、只放类型化短字段、不改岛的长短（收起时宽 280–440，放不下截断）。点一下岛
  才展开（指针停上去不展开）：全文、队列里其余的卡、「停下」「打开面板」「知道了」；指针在岛上时窗口才接鼠标，离开就交还桌面，岛上没东西
  可点时不接。急停时卡不上岛（岛就是那道细线）。到岛上走 `/ws/desktop-presence` 一帧 `type="island"`，覆盖层刚连上补发一份；
  `GET / DELETE /api/v1/presence/island` 要令牌。**桌宠还是那一只**：外形、颜色、推导一处没动（三只同一只的核对照旧）。浏览器测试
  `electron/renderer/browser-tests/island.test.js` 真开 Chromium 看画面与请求。
- **灵动岛对齐 winsland（所有者确认指的是 [adityasrivastava5098/WinIsland](https://github.com/adityasrivastava5098/WinIsland)，启动脚本叫
  `winsland.bat`）**：岛上写什么、什么时候长出来、点了做什么从 `app.js` 拆进 `electron/renderer/island.js`（`IslandView`；`app.js` 只管它在
  三态编排里多大）。从它那里借的、在这里落成什么：音乐药丸（封面贴左端、声波贴右端）→ 整座岛的排法：**桌宠贴左端、字居中、尾巴（声波 /
  「+N」）贴右端，宽度跟着内容走**（下限 280 → 224，8:1 正好守住「瘦长」）；**它在说话**时「在说话」+ 一排声波（五根各走各的，取它那一组
  时长与错开），悬停换成「点一下可以叫它停下」，说完留 1.2 秒再收（两句之间不闪），点开有「停下」；「已复制」→ 原样借来，剪贴板一变亮 1.5 秒
  （主进程每 500 毫秒看一眼格式与文字摘要，**发给覆盖层的只有类别**，原文不出主进程，`electron/clipboard_watch.js`）；弹簧（stiffness 380 /
  damping 28）→ 同一组数，长出来过冲约 3%、半路掉头不跳、收回去碰到上沿就停，关了动效的人用临界阻尼；贴边模式下沿那道光 → 岛下沿一道淡光；
  点开后右上角换页 → 「动态 ↔ 感知」。隐私指示点**没借成岛旁边的小点**：第一版在岛右边另挂了一截放彩色点的小岛（绿摄像头 / 橙麦克风），所有者
  看了说比例与桌宠和字不协调、不要右边那个小岛、不要拿黄点表示在线、点要与面板一套色彩 —— 已拿掉。「它此刻在不在收」桌宠的眼睛本来就在说；
  每一路的状态在点开后的「感知」那一页，行前的点与面板 `.wired-dot` 同一套话：**用光和深度，不用颜色**（白芯带柔光 = 在收，只亮半边 = 通着没信号，
  沉下去 = 暂停 / 没通路）；进度线、声波、下沿那道光都取面板那根轴上的淡紫（`--a-pale`），只有出错取面板的 `--bad`。没借的：日历（这边没有
  日历来源）、多显示器各一座岛。桌宠还是那一只（外形、颜色、推导一处没动；`island.js` 只量它多宽来排版，测试钉着）。测试：弹簧与状态
  `electron/renderer/island.test.js`、剪贴板 `electron/clipboard_watch.test.js`（都进了 CI 的 node 那一步），浏览器里看画面、排法、点的颜色与请求
  `browser-tests/island.test.js`（12 条）。
- **补跑的后台协程没留引用**：`truth_chain_recovery` 排在事件循环上的重跑任务原先只有循环自己的弱引用，可能跑到一半被回收 —— 留引用、`reset()` 时取消。

真跑（独立数据目录 `python main.py --backend -v`，改前改后各一遍）又抓出四样，一并修了：

- **横幅说「桌面自动化 就绪」，而这台根本没有能操作的桌面**：沙箱是 Linux，系统接口、控件都没有，坐标级只剩两个节点 —— 桌面操作节点
  Node_36 自己就回「This node only works on Windows」，自动控制节点 Node_92 那条只认在设备控制服务里登记过的设备（它原先还被标成
  「本进程键鼠」，其实是 HTTP 打节点）。现在 Node_36 在非 Windows 上照实说用不上；Node_92 那条对没登记的设备回「不接」（不记成失败）；
  横幅分三种：能直接动手 = 就绪、是 Windows 却一条路都没有 = 部分可用、不是 Windows 桌面 = 「不适用」（`·`，不算降级、不进分母）。
- **启动时事件循环卡 0.4–0.9 秒，四处**（卡顿记录当场说出位置）：选主脑时在循环里 `import core.model_selection`、起节点时在循环里
  建日志目录和打开日志文件、L4 增强模块整段同步 import 与构造、设备列表第一次取上层端口时 import `galaxy_gateway.device_router`。
  前三处挪进工作线程，第四处在启动的预热线程里先取一遍（`core.upper_ports.warm`）。改后再真跑：卡顿记录一条都没有。
- **多设备投影里「任务图」那一路从来没接上**：图快照里的记录本来就是 dict，投影又调一次 `.to_dict()`，一有记录就抛错，投影永远报
  「GAP-517-008: TaskGraphRuntime unavailable」（真跑两遍都有）。原测试只在空图上跑，所以一直是绿的；补了「图里真有转移记录」的用例。

接口复查：带令牌把 245 条不带路径参数的 GET 全打一遍，240 条 200，其余 5 条是该有的拒绝（缺参数 422、OAuth 回调缺 code 400、没登录 OAuth 401、
跨设备关着 403、没给任务号 404）；没有 5xx，没有一条超过 1 秒。本轮新东西逐条过：Computer Use 在没有屏幕的沙箱里回 `no_perception`、岛上出一张
「没做成」；陌生设备登记 → 岛上出「有设备在等你同意」→ 面板点「不接入」→ 卡撤掉；新连上的覆盖层马上收到一帧 `type="island"`；不带令牌读卡片 401；
认可一条不存在的 404；运维「确认」一条不在队列里的任务回 failed（原先回 success）；「停下」200。停机干净，22 个子进程没有留下。

**下一轮待办：**

- 照片里那次 11.5 秒卡顿的真凶：等更新后的卡顿记录（会带上同一时刻别的线程在 import 什么）。
- 本机旧 `.env` 里的 `GALAXY_NATS_ENABLED=true`（旧模板生成）：写了就听它的，删掉那一行即可回到「本地模式不起 NATS」。
- 桌面自动化的「按现场挑」只在沙箱里用桩验证过：Win32 / UIA / 微软 UFO 三个后端要在 Windows 真机上跑一遍（沙箱没有 Windows）。
- 灵动岛的「已复制」在 Windows 真机上看一眼：Electron 在 Windows 上报的剪贴板格式名（图片 / 文件）要和 `clipboard_watch.js` 的判法对得上（沙箱里只用假剪贴板验证过）。

**第 6 轮（2026-10-19）：** 这一轮的沙箱第一次装了 Docker，基础设施（NATS / Redis / Qdrant / Neo4j / MongoDB）真的被拉起来了，
于是抓到几样以前看不见的。另外所有者看了第 5 轮的灵动岛后提了三点（比例与桌宠和字不协调、不要右边那座小岛、点要用面板那套色），已改完单独提交
（见上面「灵动岛对齐 winsland」一条）。

- **横幅说「nats / redis / qdrant / neo4j / mongodb 已就绪」，而 neo4j 在反复重启、qdrant 永远 unhealthy**：横幅只看 `compose up -d` 的
  退出码。现在 `up -d` 之后读一遍 `compose ps`，最多等几秒让还在起来的落定（`launcher/compose_health.py`）：全在跑且健康才说已就绪；
  反复重启 / 退出了 / 健康检查不过 / 没建出来就点名、算降级、给出 `docker compose logs <服务>`；到点还在起来说「还在起来」（不算降级）；
  读不到状态只说「已拉起」。一次轮询里见过坏的就记成坏（起不来的容器在「重启中」和「刚起来」之间来回切）。真跑核对过：停掉 qdrant →
  「qdrant 退出了，其余已就绪」；再起来 → 已就绪。
- **neo4j 起不来**：`NEO4J_PLUGINS=["apoc", "gds"]`，5.x 认的名字是 `graph-data-science`，写 `gds` 它直接退出（`docker-compose.yml` 与
  `deploy/compose/kimi.yml`；`full.yml` 本来就对）。内存三项也换成 5.x 的 `server.memory.*`（原先每次启动报弃用）。GDS 插件要联网下，
  这台下不到时 neo4j 照常起、只是不带 GDS（全仓没有代码调 `gds.*`）。
- **qdrant 永远 unhealthy**：健康检查调 `curl`，qdrant 镜像里没有 curl / wget / nc，只有 bash —— 三份 compose 都改成用 bash 的
  `/dev/tcp` 问 `/readyz`。真跑：两个容器 40 秒内都 healthy。
- **三个状态接口占着事件循环**：卡顿记录抓到循环被卡 0.4 秒。`/api/v1/operator/board/operable-truth` 在循环里同步聚合整块看板（约 0.45 秒）、
  `/api/v1/system/container-runtime`（及 `/test`、`/choice`）在循环里跑 docker / podman 子进程（这里 0.27 秒，Windows 上 Podman 虚机没起来时
  一次就是几秒）、`/api/v1/system/completion-status` 同步重建整份报告 —— 都挪进工作线程。改后再真跑：卡顿记录一条都没有。
  看板那份聚合查过：稳定下来每次 16–31 毫秒，0.4 秒是第一次调用顺带 import 一串惰性模块的钱 —— 正是不该在循环里付的那种。
- **arXiv 在线检索连不上时说成「没搜到」**：这台的代理不放行 export.arxiv.org，`academic__arxiv_search` 照样回 `success: true, papers: []`，
  模型会据此告诉人「没有相关论文」。现在没连上就回 `success: false` 和一句「没连上 arXiv……这次没查成 —— 不是没有相关论文」
  （`core/arxiv_client.py::search_or_why`；多源汇总的旧调用方仍用 `search()`，一个源没连上只是少几条）。
- **状态接口把自动控制节点那条路写成「pyautogui 可用」**，而启动日志同时说「pyautogui 没装」：那条路是 HTTP 打设备那头的 Node_92，
  能不能动手看那台设备登记了没有，本机装没装 pyautogui 无关 —— 现在照这个写原因。
- **选过的档位会被「保存设置」钉成强制档位**（全量测试里一条串味的测试顺藤摸出：tier D 的驻留量从 18000 掉到 8800）：`core/model_catalog.py`
  把档位 / 主脑 / 感知位直接写进 `os.environ`，`core/model_selection.py`、`core/container_runtime.py` 也有几处这样写。这几个键都在登记表里，
  而 `load_tier()` 让环境变量压过记录 —— 在面板上选过一次档位，之后随手点一次「保存设置」（保存任何一项），`GALAXY_MODEL_TIER` 就被写进
  `.env`，下次再换的档位一重启就被打回去；容器运行时同理。现在都经 `core.derived_env.export` 写（这一次运行照样生效，「保存设置」不钉；
  人在 `.env` 里强制过的照旧原样写回），并加了守卫：登记表里的键不许在 core / launcher / main.py 里直接赋给 `os.environ`。那条串味的测试本身也修了
  （夹具只 `delenv` 一个本来就没有的键时 monkeypatch 什么都不记，写进去的值漏给后面的用例）。
- **测试的顺序依赖**（前面 winsland 那次提交里一并修了）：自注册测试的夹具另换数据目录，`core.user_providers` 等在 import 时定下的落盘路径
  若恰好在它里面第一次 import，就钉在它的临时目录上，「状态随数据目录走」的核对随之变红。

全量测试（4 个分片）：11480 / 11586 / 11448 / 11972 通过（第二片第一次那 2 条就是上面那条串味，修后整片重跑全过）；`test_launcher_doctor`（会临时挪开 `launcher/shell.py`，不与别的分片同跑）单独 26 条全过。

接口复查（鉴权开着）：245 条不带路径参数的 GET 全打一遍，240 条 200，其余 5 条是该有的拒绝（同第 5 轮）；没有 5xx，没有一条超过 1 秒；
Computer Use 在没有屏幕的沙箱里回 `no_perception` 并上岛一张「没做成」；陌生设备登记 → 岛上一张卡 → 「不接入」→ 卡撤掉；新连上的覆盖层马上
收到 `type="island"`；不带令牌读卡片 401；对话在一个模型都没配时 0.15 秒回「还没有可用的 AI 服务……」。停机干净：14 个子进程没有留下
（基础设施容器有意常驻，不随后端停）。

**下一轮待办：**

- 照片里那次 11.5 秒卡顿的真凶：等更新后的卡顿记录（会带上同一时刻别的线程在 import 什么）。
- 本机旧 `.env` 里的 `GALAXY_NATS_ENABLED=true`（旧模板生成）：写了就听它的，删掉那一行即可回到「本地模式不起 NATS」（这一轮沙箱的 `.env` 也是这样）。
- 桌面自动化的「按现场挑」与灵动岛的「已复制」只在沙箱里验证过：Win32 / UIA / 微软 UFO 三个后端、Electron 在 Windows 上报的剪贴板格式名，
  要在 Windows 真机上看一遍。

**第 7 轮（2026-10-19）：** 这一轮多做了两件以前没做过的事：199 条写接口（POST / PUT / DELETE）各用空请求体、再用按 schema
填好的请求体打一遍（282 次调用）；真跑三次 —— 用沙箱里那份旧模板生成的 `.env` 原样跑（鉴权关、`GALAXY_NATS_ENABLED=true`），
按出厂默认跑（鉴权开、总线跟着模式走），修完再用旧 `.env` 跑一次。启动时给每个 aiohttp 会话记下创建位置，盯第 7 节那条
「Unclosed client session」。

- **多智能体辩论接口从没通过过**（`POST /api/v1/agents/debate` 回 500「服务 'agent_swarm' 端口未配置」）：端口按「服务」查，
  而端口表里只有节点 `Node_126_AgentSwarm`，一查就抛；就算连上，字段名（question / rounds 对 problem / max_rounds）、策略名
  （COT 对 chain_of_thought）都对不上，不带身份（节点 HTTP 面有鉴权），节点是 lazy 档也没人拉它起来。现在按节点端口表找它、
  字段与策略名照节点的模型发、带身份、第一次用到时把它和它依赖的 Node_58 一起拉起来；起不来回 503 说清楚。
- **模型路由节点 Node_58 编回答**：接通辩论之后回来的是每位辩手都答「[Mock Response] Processed by llama2」、结论「达成共识」。
  Node_58 的云端那一档是桩（从不调用模型，回「[Mock Cloud Response] Processed by gpt-4」），本地 Ollama 调不通也回一句 Mock。
  现在两档都走 `core.multi_llm_router`（与对话主链同一个路由器，人在面板上配的那几家）；一个模型都没有就 503，原因一路带回到
  辩论接口（真跑：「还没有可用的 AI 服务……请在面板「全部设置」里填一个 API Key」）。
- **三个节点缺东西时「模拟执行」并回成功**：ADB（没连手机：点屏、滑动都回 `success: true`）、OctoPrint（没配 Key：开始打印回成功）、
  GitHubFlow（没配 Token：回一个 `github.com/mock/repo/pull/1` 的新 PR；配了 Token 却没配 `GEMINI_API_KEY`：把一段写死的
  「✅ 代码审查通过……建议合并」**当评论发到真的 PR 上**）。没有调用方读 `mock` 那一位。现在缺什么就照实失败、说缺什么，
  模拟只在显式 `USE_MOCK_DRIVERS=true`（启动器本来就传给每个节点）时才有（`nodes/common/mock_drivers.py`）。
- **技能热重载从没重载过**：`reload_skill` 探测 `unload_skill` / `reload_skill` / `load_skill`，`SkillLoader` 一个都没有，整段空转
  却回「已加载、校验通过」—— 连根本不存在的技能也是（MCP 那一半早先修过）；「全部重载」与加载状态读 `list_skills()` 每项的
  `skill_id`，键其实是 `id`，一个技能也没重载过、状态里一个也没有。现在从技能当初的目录按同一个 id 再 load（读坏了旧的照旧在）；
  没登记过的名字（技能与 MCP）回 404。
- **调用方传错了东西回 500**：`/api/v1/vision/understand` 不带图（里面的 400 被外层改写成 500）、`/vision/understand` 与
  `/vision/ocr` 的图不是合法 base64、`/auth/oauth/device/poll` 一个没配的提供商 —— 都改成 400 并说错在哪。
- **同一个节点被并发激活会起两个进程**：真跑里两台安卓同一秒登记，`Node_33_ADB` 被起了两次；`register_service` 换掉条目，
  前一个进程没人记着，**后端停了它还活着**。现在 `start_service` 见已在跑 / 正在起就不再建进程，`register_service` 不换已有条目。
  修后真跑：两台同时登记只起一个，两次停机都没有留下子进程（修前那次留下了一个）。
- **节点登记在事件循环里整份落盘**（卡顿记录抓到启动时卡 0.3 秒）：每个节点健康检查通过登记一次、经 HTTP 再通知一次，每次把整张
  节点表（18KB）重新序列化写盘。现在启动那一批只落盘一次（与拓扑图同一个 `core/persist_batch.py`）；修后真跑启动卡顿记录为零。
- **本地模式下 Docker 照样起 nats；本机四个库对局域网开着**：基础设施那一步不看模式，nats 容器照起（4222 对局域网开着、不带认证）；
  redis / qdrant / neo4j / mongodb 的端口都绑 0.0.0.0，同一 Wi-Fi 下谁都能连，redis 还不带口令。现在 nats 只在要总线时起
  （与 `nats_wanted()` 同一判据），四个库只绑 127.0.0.1（容器之间走服务名，不受影响）。真跑：出厂默认下 nats 不起、四个库重建后只听本机。
- **启动那一行还在说「只用本机」**，旧 `.env` 让本地模式起了总线也不说为什么：改成「这台电脑不加入设备网络 / 加入设备网络」；
  写了 `GALAXY_NATS_ENABLED=true` 时说「消息总线照起:配置里写了 GALAXY_NATS_ENABLED(本地模式本用不到它;不要就删掉 .env 里那一行)」。
- 内部调用身份的守卫补了盲区：它认不出 `MODEL_ROUTER_URL = …get_node_port(...)` 这种名字（Node_126 打 Node_58 不带身份就是这么漏的），
  现在同一文件里由端口表算出来的 URL 常量、`get_node_url(...)` 都算。

接口复查：245 条 GET（鉴权关、鉴权开各一遍）全部非 5xx、没有一条超过 1 秒；写接口 282 次调用，修前 5 条 500，修后 0 条 ——
剩下 4 条 503 都是该有的「用不了」（没配模型的代码生成、没配 Google 登录、没有 TTS 引擎、没有视频源），各自说了原因。
三次真跑都没有出现「Unclosed client session」（已给每个会话记下创建位置，下次出现会带出处）。全量测试见下一段。

全量测试（4 个分片，同一台机器上并行）：11612 / 11335 / 11729 / 11881 通过，分片二、三各红 1 条 —— `test_stop_script_pid_ownership::test_stale_pid_file_is_cleaned_not_killed`（`stop.sh` 被一个 SIGTERM 打断，来源没查到；四个分片同机并行时，`stop.sh` 里按命令行模式的 `pkill` 有误伤别的进程的可能）与 `test_stop_while_it_acts::test_stop_cancels_the_request_but_the_caller_keeps_running`（4 核吃满时一个 5 秒的等待超时）。两条单独重跑 36 条全过，CI 上同一提交的 4 个分片全绿；`test_launcher_doctor` 单独 26 条全过。

**下一轮待办：**

- 照片里那次 11.5 秒卡顿的真凶：等更新后的卡顿记录（会带上同一时刻别的线程在 import 什么）。
- 本机旧 `.env` 里的 `GALAXY_NATS_ENABLED=true`：启动那一行现在会点名，删掉那一行即可回到「本地模式不起 NATS」。
- GitHubFlow（Node_106）生成 / 审查代码写死 Gemini，没走系统路由器：只配了别家 Key 的人这一步用不了（现在照实说没配 `GEMINI_API_KEY`，不再编）。
- 桌面自动化的「按现场挑」与灵动岛的「已复制」要在 Windows 真机上看一遍（Win32 / UIA / 微软 UFO、Electron 报的剪贴板格式名）。

### 6.21 2026-10-19：跨设备拆闸与正名（整体方案阶段 0）

所有者的定义：中心智能体协调一切；「主脑」是一个角色——智能体跑在哪台设备上，哪台就是主脑；每台有跨设备能力的设备打开**自己的**跨设备、登录加入，
手表配对即加入；**「跨设备」说的是这台设备加入，从不限制智能体**。整体设计见 **[CROSS_DEVICE_OVERALL_PLAN.md](CROSS_DEVICE_OVERALL_PLAN.md)**（7 个阶段），这一轮做阶段 0。

真机探针查出的现状：手表在本地模式下照样登记进 UDM / UCM、拿到 mesh 会话，可智能体的 `devices__invoke` 一律回 `cross_device_disabled`；按钮一关还把设备接入平面、
局域网发现、mDNS 一起写成 false，智能体的设备工具从 9 个只剩「请求打开跨设备」1 个。电脑的开关在 9 类地方拦着智能体，全部拆掉：

- **下发入口**：`devices__invoke`、单设备命令 REST、命令路由的设备执行桥、网关 `DeviceRouter` 三处与 `agent_bridge`、NATS 派发桥 —— 不再看模式，能不能下发由成员资格（名册、连接、权限门）决定。
- **手机那批**：就绪判定里的「V2 跨设备开关」门（`v2_cross_device_switch`）、手机发起的目标、接管请求 —— 只看手机自己的开关与就绪状态。
- **WebRTC 信令**：原先用电脑开关当门（开着时任何局域网客户端都能连、关着时已加入的手机也连不上），改成**凭成员令牌**：主人的 API 令牌，或发给这台设备的配对令牌，否则 4401。
- **删掉** `devices__request_cross_device` 与统一拒绝 `cross_device_refusal`（智能体不去开模式）。
- **按钮成员只留 `GALAXY_NATS_ENABLED`**；设备接入、局域网发现、mDNS 移出按钮。旧按钮留在 `.env` 里的三个 false（指纹：主键也是 false 且三项同时 false）启动时清回默认并说一声（`main.migrate_former_cross_device_members`）。
- **找得到、连得上不分模式**：mDNS 广播一直做（`GALAXY_MDNS=0` 可关）；配了 headscale 就入 tailnet，没配只给一行说明；headscale / TURN / STUN 配置项面板上一直显示（跨设备专属键 15 → 6）。
- **任务派发**（`MasterBrain` + worker）只看它自己的开关，开了就把 NATS 拉起来；面向人的叫法改成「任务派发」，选模型那块的「AI 主脑」改叫「模型」，「主脑」只指智能体所在的设备。
- 继续跟电脑开关走的（电脑作为设备加入）：桌面把自己登记进 UDM / mesh、入口判定（电脑自己的请求要不要整件交给别的设备）、NATS 默认开关、联邦、设备名、mesh 口令。
- **设备自己退出**：新增 `POST /api/v1/pair/leave`（凭签给本设备、还有效的配对令牌；免 API 令牌，端点自己核验）：令牌作废、移出对端名册 / 设备名册 / tailnet。手表加了「解除配对」。
- **真机实测查出并已修**（真后端 `main.py --backend` + 真 HTTP / WebSocket 客户端，本地模式）：
  - `POST /api/v1/devices/{id}/command` 发的是 `{type:"CONTROL_COMMAND", payload:{...}}` —— 手表、手机、AIP v3 都不认，接口却回「已发送」。改成设备认的唯一一种下发帧
    `{type:"command", command_id, command, params}`（与规范派发、`/devices/parallel` 同形）；
  - `/api/v1/system/mode-status` 的 `takeover_available` 原先等于电脑的开关，改成「有在线的安卓成员」。
- 验证：`tests/test_the_agent_coordinates_members_in_any_mode.py`（新）、`tests/test_cross_device_switch.py`（重写）、手表端到端 `tests/test_watch_reaches_the_central_agent.py`
  （本地模式下智能体让手表做事，走智能体真正调的工具入口）。真机探针 13 项全过：配对领令牌 → 规范入口登记 → 本地模式下单设备命令真送到手表 →
  WebRTC 信令陌生人 4401、配对过的手表放行、别人的令牌 4401 → 手表凭令牌自己退出、令牌失效、名册里没了、再登记被拒；启动时旧按钮留下的三个 false 被迁移掉。

### 6.22 2026-10-20：设备整体卡（整体方案阶段 1）

不给设备登记死的能力和角色：每台设备当成一个整体交给模型，由模型的泛化能力加工程流程约束决定它做什么。

- `devices__list`（以及给人看的 `GET /api/v1/onboarding/cards`，同一份）每台成员一张卡：是什么（名称、类型、形态）/ 能做什么（设备自己报的每个动作 + 一句说明）/
  现在怎么样（在线、电量、网络路径、忙不忙、手表能否打扰）/ 能否接派来的 Agent（手机、自己声明的载体能；手表、「手和眼」式电脑不能）/ 最近做过什么（任务流程图）。不再按固定角色分组。
- 设备报动作说明：手表 `capability_schemas[].description`、手机 `action_descriptions`，原样进能力权威面；没说明的常见动作用一句通用说明，不认识的不编。
- 每次单动作下发（智能体 `devices__invoke` 走的规范派发、单设备命令 REST）都记进任务流程图；UCM 记每台设备在等结果的下发条数（「忙不忙」）。
- 「感知 / 动作 / 在场」只留作观测标签：派发路径（网关路由、命令路由、规范派发、源端派发）都不读它，测试钉住。
- **真机实测查出并已修**：手表登记报 `device_name="OPPO Watch 3"`，名册里却叫「Android Device」—— 登记只认 `name`。现在依次取帧里的 `name` / `device_name`、配对时起的名字、型号，最后才是兜底。
- 验证：`tests/test_the_model_sees_each_device_as_a_whole.py`（手表真实帧经规范入口 → 卡片）；受影响的 204 个测试文件 6187 项全过；
  真机探针 12 项全过（`main.py --backend` + 真 WebSocket：手表报带说明的能力 → 卡片上名字、形态、说明、在线 / 本地网络、不能接 Agent、没有固定角色、下发进「最近」），阶段 0 探针 13 项复跑全过。

### 6.23 2026-10-20：对外 A2A（整体方案阶段 2）

中心智能体与派出去的 Agent（手机上的桥接 Agent、Linux / 云载体上的 Agent）之间的通话，跑在 AIP v3 上：一条 `type="a2a"` 帧，信封在 `payload` 里。

- 协议：`core/a2a_link.py`（V2）与安卓 `shared-protocol/.../A2A.kt`（手机、手表共用）线格式与语义逐字一致；V2 测试在有安卓 checkout 时逐字对照两边的消息类别和线上的键。
- 必达：发送方留着没确认的消息，重连后按序补发；接收方按消息号去重、每条都回确认（重复的也回）；同一会话按序号交付；缺口补不上时不卡死。
- **写的时候查出并已修**：链路状态只在内存里，任何一端重启都会坏 —— 手机重启后序号从 1 重数，中心当成旧消息确认了却吞掉；中心重启后从 1 等，手机接着发的全缓着不交付。
  现在每条信封带发送方链路这一次的身份（`epoch`）和还没确认的最小序号（`floor`）：对端换了身份就从 `floor` 重新数；同一身份里 `floor` 只往前推；对端重启前缓着、已确认过的照样按序交出。
  重启那一端没发出去的消息随进程没了（等它们的协程也没了）。
- 入口：规范设备入口 `/ws/device/{id}` 收 `a2a` 帧，先过同一道认证（没认证的连接回 `UNAUTHENTICATED`），一台设备只能以它自己那个 Agent（`agent:<device_id>`）说话（冒充回 `A2A_REJECTED`）；
  设备（重新）登记、登记确认写回之后，中心把发给它还没确认的消息按序补发。网格不镜像（私人内容、点对点，`core/aip_mesh_mirror.py` 豁免表）。
- 命名：混合执行里「直接调应用的 API / MCP」那一级原先也叫 A2A，改叫「API 直调」（`ExecutionLevel.API_DIRECT`，旧值 `a2a` 照旧认），A2A 只指 Agent 之间的通话。
- 验证：`tests/test_external_a2a_link.py` 20 项；安卓 `A2ALinkTest` 14 项；跨仓闸门 `REQUIRED_AIP_MESSAGE_TYPES` 加 `a2a`（1.1.0）；
  真后端探针 13 项全过（`main.py --backend` + 真 WebSocket：没认证拒收、确认带中心链路身份、重复照样确认但只交付一次、冒充拒收、畸形拒收、乱序都确认且按序交付；**杀掉后端重启**后手机接着发的下一条立刻被确认并交付，日志可见）。
- 收发处理器（各类消息到了做什么）随阶段 3 登记：派桥接 Agent、上下文交接、对话桥接、委派目标、交还。

### 6.24 2026-10-20：手机接管与对话桥接（整体方案阶段 3）

所有者最初的设计：手机打开跨设备并登录后，中心派一个 Agent 到手机；手机上的运行时接管本地正在跑的上下文，把本地这一整套并进网络。从此手机上的对话就是和中心智能体的对话。

- 接入握手：能接 Agent、且报能力时声明了 `bridge_agent: "bridge/1"` 的设备（新版手机；旧版 App 不认 `a2a` 帧也不回确认，不派）报完能力，中心在后台派 `agent_dispatch`（桥接 Agent 的说明：会话 `phone:<设备号>`、手机自己报的动作与说明、自治档位、要人确认的动作）→ 手机回 `agent_installed`。手表不派。
  断线重连后再派一次时，手机只回「装着呢」，上下文不再交一遍。
- 上交上下文：手机发 `context_handoff`（最近对话、正在跑的本地循环进度、最近几次本地执行；屏幕不传），落进中心这台手机的会话；重复交的同一句不重复记。
- 对话桥接：手机上说的话以 `conversation` 进中心智能体的同一个会话（来源 `phone_chat`：算人发起的回合、不进电脑三态，与手表同一套来源分类），回答以 `conversation` 回到手机界面；一轮对话在后台跑，不挡这台手机后面的帧。
- 委派：新工具 `devices__delegate` 把整段目标交给装了桥接 Agent 的设备（手机本地循环），带进度、等结果、记进任务流程图；没装上的设备当场说明原因，不干等。设备卡加 `agent_installed`。
- 交还：手机关跨设备时请中心交还（`context_return`），中心回这段对话的摘要与没做完的事，视为卸下桥接 Agent。手机那边的三个开关都先请交还、最多等 2 秒再断开。
- **真机顺序查出并已修**：安卓先发 `auth`（令牌在顶层），再发不带令牌的 `device_register`；规范入口的登记只认帧里的令牌（预留的 `_ingress_transport_token` 从没人填），认证开着时**真手机一直登记不上**（`INGRESS_AUTHENTICATION_FAILED`）。
  现在规范入口把这条连接自己的凭证（握手头里的 Bearer，或这条连接上回过 `auth_ok` 的令牌）带给没带令牌的帧，登记照样重新校验（配对令牌绑设备号）；没有凭证的连接照样被拒。
- 已知来源表挪进 `core/presence_line.AGENT_LOOP_SOURCES`（含别的设备转来的来源）：`phone_chat` / `wear_voice` / `wear_decision` 不再每次打一条 "unknown source" 警告。
- 验证：`tests/test_phone_joins_through_its_bridge_agent.py` 14 项（安卓真实帧顺序走规范入口：登记三种情形、派 / 不派、交接落进会话且不重复、对话进同一个会话且来源对、委派带进度拿结果、委派拒收、交还、设备卡）；
  安卓 `BridgeAgentRuntimeTest` 12 项；真后端探针 13 项全过（安卓真实顺序登记、派桥接 Agent、交接、对话走真的智能体主循环拿到回答、同一会话、交还、确认收干净），**杀掉后端重启**后 3 项全过（握手头登记、重新派、手机下一条立刻交付）。

### 6.25 2026-10-20：多步计划与每台设备的串行队列（整体方案阶段 4）

- 新工具 `devices__plan`（方案里叫 `tasks__plan`；放在设备工具一族，`core/task_plan.py`）：模型写出步骤、依赖、每步用哪台设备，
  每步要么是一个动作（同 `devices__invoke`），要么是一整段目标（同 `devices__delegate`，前面几步的结果随约束带过去）。
  执行用现成的 `ConstellationRuntime` 分层执行（依赖都成功了才轮到，同一轮并行）；拆解和挑设备听模型的，它的自动重排不开。
- 失败：一步失败带回设备给的原因，依赖它的步骤不做（标「前置步骤没成功」），不依赖它的照做；重试、换设备还是问人由模型定
  （自动重做一个发消息、下单的动作会重复动手）。
- 每台设备一个串行队列（`core/device_queue.py`，现成的带背压 `AsyncTaskQueue`，一个工位）：同一台手机不同时做两件事，
  不同设备照样并行；`devices__invoke`、`devices__delegate` 也走它。一台设备排了 32 件还没做完时当场说明。
  一份计划同时在做的步骤不超过 `GALAXY_MULTI_DEVICE_DISPATCH_LIMIT`（默认 8），名额在轮到之后才占，排在忙设备后面的步骤不挡别的设备。
- 重启续跑：计划随时写盘（`$GALAXY_DATA_DIR/task_plans.json`），启动时的任务图续跑顺带接着做没做完的计划（等相关设备重新连上，最多 5 分钟）：
  排着队还没动过设备的步骤接着做；崩溃时正在做的那一步记「结果不明」、不重做，依赖它的也不做；做完把结果记进发起计划的会话。
- 计划也记进任务流程图；查进度：`devices__plan` 只给 `plan_id`，或 `GET /api/v1/onboarding/plans/{plan_id}`；REST 交计划：`POST /api/v1/onboarding/plans`（要所有者令牌）。
- **顺带修掉**（阶段 1 留下的）：每次下发记进任务流程图的节点没有可重放的载荷，重启续跑却会拿它们去重派。现在这些节点标 `observation_only`，续跑跳过。
- 验证：`tests/test_the_agent_runs_a_multi_step_plan_across_devices.py` 17 项（计划校验、依赖顺序与同设备串行、失败原因与不做依赖、委派带前面的结果、
  写盘与任务图、重启只做该做的、排队的不记「正在做」、名额不被排队的步骤占住、队列满、真网关 + 真手表一步步做）；
  真后端 + 两只真 WebSocket 手表探针 9 项全过（两只表同时做、一只表一次一件、依赖等前一步、设备给的失败原因、依赖它的不做、独立的照做、事后能查），
  交计划后让第一步卡在手表上、**kill -9 杀掉后端**：盘上是「在做 / 排着」，重启后两只表重新连上，在做的那一步记「结果不明」没重做、排着的那一步做了、依赖结果不明的没做（6 项全过）。

### 6.26 2026-10-20：Agent 载体（整体方案阶段 5）

- 载体＝装在别的电脑、Linux 服务器、云主机上的 `python -m device_client --carrier`：同一个连接层（配对、令牌、续期、重连）+ 载体执行插件
  （`device_client/executors/carrier.py`）+ 载体上的 Agent（`device_client/carrier_agent.py`，和手机的桥接 Agent 说同一套对外 A2A）。
  凭据单独存（`carrier.json`），同一台机器可以既是「手和眼」式电脑又是载体。
- 能做的：读写列文件——只在载体自己的工作目录里，目录外一律拒；`run_code`——**只在 Docker 沙箱里**（不联网、512MB、1 核、128 进程、只读根、
  无特权用户、去掉全部 capability、超时强停、跑完即删），本机没有可用的 Docker 就不报这个动作；`get_status`（系统、CPU、内存、GPU、有无图形界面、沙箱）。
  每个动作带一句说明和参数，进设备整体卡，也是载体上推理循环的工具说明。
- 接入：`devices__invite kind=carrier` 给配对命令（原生一条；容器两步：先配对、再常驻——配对码只能用一次，带着它常驻的话容器一重启就反复失败）。
  报能力时声明 `bridge_agent`：中心记下它能接 Agent（设备卡 `can_take_agent`、`form: carrier`），并派一个 Agent 过去，会话 `carrier:<设备号>`。
- 整段目标：`devices__delegate`（以及多步计划里委派的那一步）给了 `steps` 就照这串动作按顺序做；只给一句话就在载体上跑推理加行动的循环
  （`core/local_agent_runtime.py`，端侧执行沙盒的本义），**模型经中心**：每一轮发 `tool_call`（`llm.chat`），中心用自己的模型答，钥匙只在中心。
- 部署：`deploy/carrier/Dockerfile`（只装 `websockets` + `pydantic`；容器里没有 Docker 所以不接 `run_code`）、`deploy/carrier/galaxy-carrier.service`
  （专用用户；要跑代码才把它加进 docker 组——那等同 root，文件里写明了；令牌失效退出码 3 时不再重启）。
- **真后端实测查出并已修**：
  - 中心一个模型都没有时，路由不抛错、回一句「还没有可用的 AI 服务」（给人看的降级）。载体的推理循环把这句当成最终答案，**报「做完了」**。
    现在 `llm.chat` 把这种回复当失败交回，载体如实报原因。
  - 后端重启或设备重连后的那半秒（登记会换掉元数据，能接 Agent 的声明要等报能力才到；中心还以为旧的 Agent 装着），交整段目标会被当场拒成
    「不能接整段目标」。现在登记时记下「待确认」，委派先等它报能力（≤3 秒）、再等它重新装上（≤15 秒）；从没声明过的设备照样当场说明。手机同样受益。
  - 本地 Agent 运行时的推理循环在没有模型、模型调不通、原地打转、轮数用完时一律报 `success=True`；现在报失败并带原因。
- `core.local_agent_runtime` 不再在不可达清单里（载体端接上；服务端仍不用它，INV-008 不变）；未接线清单的生成段已刷新。
- 验证：`tests/test_an_agent_carrier_takes_whole_goals.py` 12 项（配对接入派 Agent、设备卡、按步骤做整段目标、推理循环经中心的模型、中心没模型时如实失败、
  路由降级回复不当答案、单个动作与工作目录边界、重连与后端重启后那半秒里交的目标不被拒、「手和眼」式电脑不收整段目标、没沙箱不报 run_code、
  载体凭据单独存、轮数用完不报成功）+ 1 项真 Docker 沙箱（算对、不联网、超时强停）；
  真后端 + 真载体进程（配对码接入）12 项全过，**kill -9 杀掉后端**两轮，各 3 项全过（载体自己连回、重新装上、一连上就交的目标等它而不被拒）；
  容器里的载体（照 `deploy/carrier/Dockerfile` 构建，按邀请的两步走）12 项全过，含容器重启后凭据还在、不再配对、工作目录里的文件还在；
  手机桥接（阶段 3 探针）回归 13 + 3 项全过。
- 这里没法验证的：中心有真模型时推理循环的成功路径（这个环境没有 API Key、也没有本地模型）；它由真网关 + 真载体客户端 + 照剧本回答的模型那一项测试覆盖。

### 6.27 2026-10-20：桌面版装上传输适配器（整体方案阶段 6）

- 一种消息（AIP v3）、多种传输、自动选路（`core/aip_transport.py`）：传输适配器此前只在**独立运行网关**时装（`lifecycle` 的 Phase 8）；
  桌面版（`main.py` → 主 app 挂载网关）刻意不跑那段 lifespan，**一个适配器都没有**，每次 `get_aip_transport().send` 都回「没有可用传输」。
  现在两条启动路径共用 `galaxy_gateway/bootstrap/transports.register_transport_adapters`（桌面版经 `upper_ports` 调）：同一进程只装一次，不重复注册、不重复绑端口。
- 「websocket」这条传输改走规范设备入口上真的连接（`UnifiedConnectionManager`）：此前它接的是网关自己的 `WebSocketManager`，那里从没有任何连接，
  **哪种部署都没投递成功过**，每条消息都靠调用方自己直接写 socket 兜底。发给设备的帧不带选路用的内部字段。
- 端口被占（同一台机器上还有一个 Galaxy 进程）时那个适配器只发不收，日志说清是哪个端口、设哪个变量换（`GALAXY_AIP_TCP_PORT` / `GALAXY_AIP_UDP_PORT` / `GALAXY_MESH_PORT`，
  已登记进设置，不上面板）；UDP 两边都能绑（复用地址），单播只会到其中一个。MQTT 只在配了 `MQTT_BROKER` 时装（否则后台对着 localhost:1883 无休止重连）。
- TCP 入口的局域网广播（`_galaxy-aip3`，`lan_discovery` 靠它找对端）注册是阻塞的、这里要约 10 秒：此前在独立网关启动里同步做、卡住事件循环；现在放到后台线程。
- 诊断：`GET /api/v1/diagnostics/internals/transports` 多了「装了哪些传输」，链路统计里看得到每台设备实际走的哪条传输。
- **接通后查出并已修**：
  - 登记、重连时推给设备的「电脑当前三态」以前从没送到过（读的是一个不存在的方法，AIPTransport 失败又不抛异常）；传输接通后它第一次送到，
    还抢在登记确认前面。当时把它修通了；**之后按所有者的意思整个删掉**：电脑的三态不该推给设备，见 6.28。
  - 视觉结果此前一边作为处理器返回值回去、一边经 AIPTransport 另推一份；另推那份以前送不到，传输接通后手机会收到**两份**。现在只靠返回值（两个设备入口都把返回值写回）。
- **所有者 2026-10-21 定了：不做**。三态和智能体拆成两个进程、桌面壳连远端智能体（方案里的可选项）。现状是桌面壳与本机后端绑死：
  令牌从本机磁盘读、只给本机地址带令牌、壳自己拉起后端；而电脑三态（在场运行时）和智能体主循环跑在同一个进程里。要连远端智能体，得先把在场运行时
  拆出来、改成订阅远端智能体的状态流，再让壳能配远端地址与配对令牌 —— 这是架构级改动。不拆的话，别的电脑照样能以「手和眼」式电脑或 Agent 载体加入。
- 验证：`tests/test_the_desktop_backend_has_its_transports.py` 9 项（只装一次、websocket 投递到规范入口且不漏内部字段、真 TCP 帧进网关、端口被占只发不收、
  局域网广播不卡启动、视觉结果只回一份、两条启动路径共用一个函数；登记那一项后来改成「登记 / 重连都不推电脑的三态」，见 6.28）；
  真桌面版后端 6 项全过（TCP 19421、mesh 19422/tcp、UDP 19422 真在听；诊断里看得到；
  真 TCP 心跳帧得到 `heartbeat_ack`；命令照样到真手表、帧里不漏内部字段）。传输层的「websocket」这条在真后端上投递到了真手表（实测时由登记那一推经
  AIPTransport 触发，链路统计成功率 1.0；那一推后来改成直接走规范连接。REST 单设备命令本来就直接走规范连接，不经 AIPTransport）。
  同一台机器上第二个后端 3 项全过，kill -9 后重启端口照样绑上；
  阶段 0–5 的真机探针全部回归通过（13 / 12 / 10 / 13 / 9 / 12）。

### 6.28 2026-10-21：电脑的三态不推给设备

- 所有者：新设备直接对智能体就行，不需要知道电脑的三态。三态是电脑这具身体的表达（静默 / 思考 / 执行）；手机、手表、载体是
  直接对智能体的成员 —— 登记、报能力、说话、拿回答 —— 不跟着电脑的脸显示。
- 删掉的（V2）：电脑三态每次变化广播给所有连着的手机（`RuntimeSession.advance`）；新设备登记时补推一次电脑当前的三态（规范入口
  `routes/websocket.py` 与兼容入口 `websocket_handler.py`）；安卓设备重连时补推（`AndroidBridge.reconnect_device`）；没有调用方的
  `AndroidBridge.route_phase_change`（同样是全量广播）。
- 留下的只有一种：**别的设备发起的请求，智能体处理到哪了**（在想 / 在做 / 做完），只回给发起的那台手机类设备，手表不收
  （`core.presence_line.tell_origin` → `core.cross_device_sync.tell_origin_device`）。报文 `payload.sync_type = "request_progress"`，
  手机只认带这个标记的相位报文。这件请求在本机落手、交还桌面以后，手机照样看到它的进度；给桌面补放的那几步不重推
  （否则手机上会从「在做」跳回「在想」）。电脑发起的请求不往任何设备推相位。
- 安卓（同名分支）：主屏、小组件、磁贴不再显示电脑的三态，只显示「智能体正在想 / 正在做你这件事」，只认 `request_progress`。
- 验证：`tests/test_presence_line.py`（电脑发起的不推；别的设备发起的只回那台；交还桌面后照样回、补放不重推；手表、离线的、
  不认识的都不推；V2 里不再有往设备推三态的代码）；`tests/test_the_desktop_backend_has_its_transports.py` 真网关上电脑在
  执行 / 思考 / 静默时，新设备登记、再连一次都只收到登记确认、没有任何相位帧（改动前「执行」「思考」两项红）；
  `tests/test_phase_wire_shape_is_single_sourced.py` 全仓只有一处构造相位报文、没有别处再调它。

### 6.29 2026-10-21：实时语音里边说边做（手表通话、电脑自己的实时语音）

> 6.33 起：设备通话的来源改为 `device_call`（哪种设备都一样），下文的 `wear_call` 指当时的名字。

- 所有者：通话打通以后跟智能体说，就像跟人说，它可以边说边做；智能体是一个原生全模态的主体，本地的和云端的模型共存、
  按情况决定是说还是做，**不该默认只聊**。此前手表通话是一个独立的实时语音模型对话，**接不到智能体的工具**，要让智能体做事
  只能挂断改用语音问答；电脑自己的实时语音（双工）只旁录、从不交给智能体，说「帮我打开浏览器」它只会聊。
- 怎么接的（`core/voice_call_agent.py`）：接话的实时语音模型负责**说**，中心智能体负责**做**（同一个智能体、同一套工具与权限）。
  事情怎么交过去，看说话的模型会不会调工具。
- **会调工具**（手表通话、云端 OpenAI / Gemini）：会话里声明三个工具：
  - `agent_do(what)`：**立刻**回「已经开始做」，模型答应一声、接着说话；事情在后台跑（`handle_request(source="wear_call")`）。
    做完在没人说话时往通话里插一条【回报】，模型把结果说给人听。不让工具调用一直挂着等：实时接口里挂着的调用会卡住对话，
    而「异步工具调用」各家各型号支持不一（Gemini 有的型号收到 scheduling 字段反而断开会话）。
  - `agent_status()`、`agent_stop(task_id?)`：问进展、停下。
- **不会调工具、或者是电脑自己的实时语音**（阶跃、本机全模态 server 如 MiniCPM-o、电脑上的双工）：智能体自己**旁听**。
  人说完一句（实时转写），快档模型（`fast_response`，本地优先）判这句是要做事、要停、问进展，还是只是在聊；要做事就把**人的原话**
  交给智能体，后台做、【回报】插回会话都和上面一样；问进展插一条【进展】。附和（「嗯」「对」）、正在回答智能体提问的话不判；
  一个模型都没有时判不了，当在聊（那时智能体也做不了事）。说话的模型被告知「执行部分在旁边听着，答应一声就行，别说做不了、
  别说做完了」。电脑上一律旁听：智能体在电脑上本来就听得见人，交过去的是人的原话，来源 `voice_duplex`（和回合制语音一样算人说的），
  照常走电脑三态；智能体做事记在自己的一条会话里（`voice_duplex:desktop`），不用对话主线（人说的话旁录已经记进主线，
  再用主线这一句就记了两遍）；这一路的结果不再由电脑另外念一遍（由实时会话那个声音说，否则两个声音）。
- **实时语音连哪个后端，跟实际情况走**（所有者 2026-10-21，`DuplexSessionConfig.from_env`）：没显式配 `GALAXY_REALTIME_URL`、B 档原生开着时，本机全模态 server **在应答**就用本地，哪怕也填了云端 key（`OPENAI_API_KEY` 多半是给智能体做事填的，不该顺带把语音拉到按分钟计费的云端）；本地没在应答、有云端 key 才用云端；都没有照样试本地（试不通安全退回原生回合制）。连本地时用本地 server 的协议（OpenAI 兼容），不管云端配的是哪家。此前只要有云端 key 就不考虑本地。想在本地开着时仍用云端，把 `GALAXY_REALTIME_URL` 配成云端地址。
- 同一块手表的通话共用一条会话（`wear_call:<设备>`），智能体记得上一通电话说过的事；人这几句的原话作为上下文带过去。
- 智能体在问：要人批准、要人选的事也进通话（【智能体在问】）。只认问出口之后人的**原话**（实时转写）。
  - 普通问题：说中选项就是那个，明确的好 / 不好对应两选一，开放问题原话交回去；有选项却没说中的话不当回答。
  - 高风险的批准仍要在手表上点：嘴上说好不算（转写会听错、AI 的回声也可能被当成人说的），说不要算拒绝。
- 来源 `wear_call`：不进电脑三态；**不**算人亲口说的（调工具交过来的是语音模型的转述；旁听交过来的是转写，AI 的回声也可能被转写进来；
  对话里的确认不该被它满足）。
- 挂断后还没做完的照样做完，结果作为通知发到手表。手表通话界面多一行「在做 / 做完了 / 没做成 / 停下了」（galaxy-wearos `AgentTaskLine`）。
  智能体一个模型都调不通时（只回了一句「还没有可用的 AI 服务」），报「没做成」而不是「做完了」。
- 协议：OpenAI Realtime（`session.tools`、`response.output_item.done` 里的 `function_call`、`function_call_output` + `response.create`、
  system 消息）与 Gemini Live（`setup.tools.functionDeclarations`、`toolCall.functionCalls`、`toolResponse.functionResponses`、
  `clientContent`；顺带打开 `inputAudioTranscription`，否则收不到人说的话）。**阶跃不声明工具**（没有可核实的资料），走旁听。
  本地实时服务收不收 `tools` 没法预知（塞一个它不认的字段，失败方向是整通电话打不通），不塞、走旁听；`GALAXY_REALTIME_TOOLS=1`
  明确让它调工具。配不上也走旁听，绝不让电话打不通；只有 `GALAXY_VOICE_CALL_AGENT=0` 才只聊。
- 验证：`tests/test_talking_to_the_agent_on_a_watch_call.py` 28 项，覆盖三家的帧、事情怎么交过去、真 WebSocket 上的会话，
  边说边做的立即应答、后台做、没人说话才插回报、进展、停下、失败、没有模型、挂断后发通知、回报等不到回复不挡后面，
  通话里的问与答；旁听交人的原话、附和和回答不判、停下与进展、快档判断与没有模型；端到端：真 WebRTC 手表、真通话路由、
  本地真 WebSocket 上的 OpenAI 实时协议端（调工具一路、本地服务旁听一路），以及真 `VoiceLoop` 的电脑实时语音旁听交过去、回报插回。
  `tests/test_presence_line.py` 钉住电脑实时语音交过来的事走三态、不再另外念。
  把等人说完、问出口才听、高风险嘴上不算、工具调用不转给手表、旁听、回答时不判、附和不判、交原话、没有模型不判、
  本地服务不塞 tools、电脑接线、不另外念、进展任一条去掉，对应那项会红。
  真实环境（真后端 + 真手表连接 + aiortc 真 WebRTC 通话 + 后端连过去的本地实时协议端）OpenAI 与 Gemini 两种协议各 9 项全过：
  接通、会话声明工具、手表的声音经 WebRTC 真到实时端、交出去立刻应答、真智能体后台做完回报插回通话
  （这里没有模型，照实报「没做成」）、手表看到在做 / 没做成、没有让手表挂断的错误事件、问进展、挂断关掉会话。
  智能体在问的那一路要真模型触发（没有 HTTP 入口），由测试覆盖（用的是真的提问登记表）。

### 6.30 2026-10-25：智能体直接调手机的动作，手机真做得了

- 进入设备完整阶段的第一项（手机：打通所有相关功能）。查出的断点：手机向中心报了 12 个能直接调的动作，手机上
  一个执行都没有、清单里也没有对应权限；中心经 `devices__invoke` 调，发 `command` 帧（顶层 `command_id` + `command`），
  手机把它归一成 `task_assign` 当成一个空目标交给本地循环，也不回 `command_result`，中心干等 30 秒报超时。
- 手机侧（ufo-galaxy-android #539）：认出直接动作、交给新的执行层，做完回 `command_result`（和手表同一个形状）；
  只报做得了的（实现了、人也给了权限），权限变了只重发能力上报。做得了的：通知、定位、传感器、查通讯录、查日程、
  打开应用、截屏；发短信、打电话、加日程只备好，系统界面填好内容、弹通知，人点了才发 / 拨 / 存。拍照、听一段话
  这一版不报；整段目标仍走 `devices__delegate`。
- 中心侧（`galaxy_gateway/android/handlers/capability_report.py`）：设备这次没报的动作从能力权威面撤掉。设备整体卡
  列的是能力权威面里这台设备的全部 `gateway__<id>__*`，此前只增不减 —— 人收回了权限、新版 App 不再报的动作，
  卡上照样列着，智能体就会去调、再失败。
- 验证：`tests/test_the_agent_calls_a_phones_actions.py` 3 项，真网关 + 安卓真实帧顺序（先 auth、再登记、再能力
  上报）：智能体调手机的定位拿回经纬度；手机拒绝时原因原样带回；手机不再报的动作从设备卡撤掉（去掉撤除那一段
  这项会红）。手机那一侧的测试见安卓仓 `PhoneCommandExecutorTest`、`PhoneDirectCommandWireTest`。没上过真机。

### 6.31 2026-10-25：手机也能和智能体通话

> 6.33 起：通话不再按手表 / 手机分，来源统一为 `device_call`，挂断后的结果交给智能体决定怎么告诉人。

- 设备完整阶段第二项。此前只有手表能和智能体打电话；通话路由本来不挑设备，但几处写死了手表：给语音模型的说明、
  交给智能体的来源（`wear_call`）、挂断后用手表的 `notify` 动作弹通知（手机报的弹通知动作叫 `notification`）。
- 中心侧（`core/voice_call_agent.py`、`galaxy_gateway/voice_call_route.py`）：接通前按 UDM 登记的形态认手表还是手机
  （认不出按手表）；手机打来的：说明里是「用户正在手机上和你通话」，来源 `phone_call`（进 `REMOTE_SOURCES`，
  不进电脑三态，也不算人亲口说的），会话 `phone_call:<设备>`，挂断后做完的事用 `notification` 发到手机。
- 手机侧（ufo-galaxy-android #539）：通话信令状态机放进共享协议模块（与手表同一份逻辑），手机上的 WebRTC 控制器、
  麦克风型前台服务、通话界面；连接把网关的通话信令交给通话。
- 验证：`tests/test_talking_to_the_agent_on_a_watch_call.py` 新增 2 项（认手表 / 手机；真 WebRTC 设备 + 真通话路由 +
  本地真 WebSocket 实时端的手机来电：说明、来源、挂断后的通知动作），变异检查 4 处各自变红。手机那一侧的测试见
  安卓仓。没上过真机。

### 6.32 2026-10-25：工具返回了什么，模型就看到什么；手表、手机、中心接力跑通

- **查出的缺陷**：三个推理循环（`OpenClawd._react_loop`、`core/agent/react_loop`、`agent_factory` 的记录）只把工具返回体里的
  `result`（失败时 `error`）回喂给模型。不少工具把内容摊在顶层：`devices__list` 的设备卡在 `members`、`devices__invite`
  的配对码在 `code` / `tell_user`、调参的结果在 `tell_user`。这些在模型眼里一直是一段空白：看有哪些设备看到的是空的，
  邀请一块手表拿不到配对码。修法：共用 `core/react_progress.tool_result_text`，没有 `result` 也没有 `error` 时
  把整个返回体（去掉 `success` 和下划线开头的内部字段）交给模型；有 `result` / `error` 的照旧。
- **设备完整阶段第三、四项**：手表新增 `heart_rate`（现测一次）、`steps`（今天的步数与从几点开始算的），没传感器、
  没给权限的不报，权限变了重报（galaxy-wearos #24）。中心这边不用改：设备卡读设备自己报的动作与说明，不再报的动作
  按 6.30 撤掉，手表走的规范入口同样适用。
- 验证：
  - `tests/test_the_watch_the_phone_and_the_center_work_as_one.py` 4 项。手表、手机各一条真 WebSocket，真推理循环 + 真工具执行，
    只有模型按剧本：人在手表上问「我下午有什么安排」，模型从设备卡里自己挑出有日历的手机去查，答案回到手表；手机说做不了时
    手表上听到原因；智能体读手表心率；收回心率权限后设备卡上不再有心率。
  - `tests/test_the_model_sees_what_a_tool_returned.py` 6 项（含主循环把配对码交给模型）。
  - 把修法退回去，接力的两项变红（模型看到空的设备列表，手机收不到查询）。没上过真机。

### 6.33 2026-10-26：去掉两处按设备类型写死的地方

所有者定的方向：接口是通用的，什么设备都会有；代码里不写死设备的角色、不按类型分支，由智能体依据设备自报的能力和状态
判断，代码只守边界。按这个去掉两处：

- **通话**（`core/voice_call_agent.py`、`galaxy_gateway/voice_call_route.py`）。此前按手表 / 手机 / 电脑三种分开写：
  给语音模型的说明、交给智能体的来源（`wear_call` / `phone_call`）、挂断后用哪个动作发通知（`notify` / `notification`）；
  认不出的设备当手表。现在：
  - 说明里只有设备登记时自己报的名字；
  - 哪种设备打来都是同一个来源 `device_call`；
  - 挂断后才有结果的事交给智能体，它看设备卡片决定发到哪台、用哪个动作，代码不替它挑。这一轮用 `device_call` 交过去，
    不算人亲口说的。
- **能不能问人**（`core/interaction/pending_decision_registry.py`）。此前按类型名单认手表和手机：名单外的设备问不到，
  名单里的手机却收到它根本不显示的提问（手机 App 没有处理决策请求的代码）。现在：
  - 设备在能力上报里声明 `answers_decisions: true` 才问它，记在设备元数据上，不再声明就撤掉；
  - 设备卡片上有这一项，智能体看得见。
  - 手表声明（galaxy-wearos #24），手机不声明。
- 验证：通话与问人相关的 172 项通过；新增「什么类型都按声明问」「卡片上看得到」「说明里只有设备名」「挂断后交给智能体」。
  变异 4 处各自变红（不看声明全问、挂断后又直接发写死的动作、说明里写回设备类型、转告那一轮算成人说的）。
- 还没动的、同类的写死：`devices__list` 的工具说明里写着各类设备的典型情况（「手表能不能打扰」「手机能接 Agent、手表不能」）；
  `wear_voice` / `wear_decision` 这类按设备命名的入口来源。留给整体设计一起定。

### 6.34 2026-10-26：剩下按设备类型写死的地方全部去掉

接着 6.33，把剩下凡是「按设备类型决定行为」的地方都改成看设备自己说的。

- **设备自己声明的几件事**（新模块 `core/device_declarations.py`）。在能力上报里声明，中心按声明对待设备，不看类型；
  每次报能力都记一遍，不再声明就撤掉。
  - `answers_decisions`：问人发给它（6.33）。
  - `shows_messages`：`ask_human__notify` 默认发给它；智能体也可以用 `device_ids` 自己点名。此前借用问人的设备列表。
  - `shows_request_progress`：请求进度只推给它。此前是「除了手表都推」。

  手表声明前两项，手机声明第三项。
- **来源名不再按设备命名**：`wear_voice` → `device_voice`，`wear_decision` → `device_decision`，`phone_chat` → `device_chat`。
  接了桥接 Agent 的设备会话统一叫 `bridge:<设备号>`（此前手机 `phone:`、别的 `carrier:`）。
- **设备卡片**：
  - 能不能接 Agent 只看声明（`bridge_agent`）或登记时自报的 `join_runtime`，不再「完整运行时并且不是手表」；
  - 哪台设备报了可打扰性就显示哪台的，不再只给手表显示；
  - 形态（form）留作给模型看的描述，不拿来决定行为。
- **执行模型**（`taxonomy.execution_model_for`）：不再按类型给手机、平板「完整运行时」，给手表、电脑「部分运行时」。是不是完整
  运行时看设备明说的 `join_runtime`。这个值此前只回在 ack 里，现在登记时只记设备明说的、不补默认值，手机照旧是完整运行时。
- **配对发 tailnet 钥匙**（`core/routes/pairing.py`）：此前按类型名单（手表、几种电脑）发。现在客户端声明 `tailnet: embedded`
  （App 里自带进网进程）或 `system`（用系统 tailscale）才发。手表声明 embedded，电脑客户端 `device_client` 声明 system，
  手机不声明（自己装 Tailscale App 登录）。**旧版手表 / 旧版电脑客户端重新配对拿不到钥匙，要和新版一起装。**
- **邀请设备**（`devices__invite`）：按那台设备上跑什么分（`app` / `client` / `carrier` / `worker`），不按手机、手表、笔记本分。
  进网步骤智能体要了（`network=true`）才给。旧名字照旧认。提示文字里不再写「手机 / 手表」。
- **工具说明**（`devices__list` / `devices__remove` / `devices__delegate` / `ask_human__notify`）：不再写各类设备的典型情况，
  只说卡片上有什么、由智能体判断。
- **其他**：
  - 删掉按类型过滤设备能力的白名单（结果从来没人读）和认证时的「合法类型」名单（只打日志）；
  - 安全策略里「手表按键确认」改成「在弹出的确认上点一下」；删掉「未知设备按手表的权限处理」和「手表侧键三连击」，这两条早就不执行、
    也没实现；失效保护里按类型的边界清空（执行方早已不读）；
  - 执行画像（PR-6）不再按类型、也不按「有屏幕 / 摄像头」猜能不能跑 Agent，只看声明。它只用于观测，派发照旧；
  - 登记时没报类型的设备不再当成安卓手机，名字兜底用设备 id，不叫「Android Device」；
  - `e2e_pipeline` 兜底路由按名册里的设备 id / 名字认目标，不按「手机 / 电脑」这类词。
- **刻意留下的**：
  - 设备自报类型名的归一（`taxonomy` / `device_types`，比如 `wearos` → `android_wear`）：描述设备，不决定行为；
  - 按操作系统给不同的进网命令（`tailnet_self_join`）、UI 定位归属（`perception_grounding`，安卓在设备上定位、桌面由服务端定位）：
    是平台的技术差别，不是角色；
  - 面板拓扑图里的 `role` 只决定小方块画多宽；
  - `android_goal_execution` / `android_vision` 这两个按平台命名的入口来源，只用来给请求打来源标签，不决定哪台设备做什么。
    改名要动一串跨仓契约测试，行为不变，没动；
  - mesh / formation 的「感知 / 动作 / 在场」「主执行 / 辅助」角色：只用在投影和诊断，不进卡片、不进派发（设备卡片模块早就写明）。
- 验证：相关测试 473 项通过；新增「三项声明经真网关记下与撤掉」「按声明找设备」「消息可以点名」「只认设备明说的运行时姿态」
  「什么类型都按配对声明发钥匙」等。

### 6.35 2026-10-26：一个事件循环没收尾，会话不再从此写不进去

- **现象**：CI「环境耦合」检查在干净环境里红了 6 条：手机桥接交过来的对话没落进会话、设备播报没记进对话主线，
  日志里是 `Lock ... is bound to a different event loop`。
- **原因**：会话管理器是进程单例，原来用一把 `asyncio.Lock`。这把锁第一次有人排队时绑死在当时的事件循环上；
  那个循环在有人排队时被丢下（任务没取消），等待者永远挂在锁上，此后在任何别的循环里拿锁都报错。
  测试里是笔记本配对那组自己起的服务循环停了，配对播报还在等锁。生产里也不止一个循环：
  没有运行中循环的同步调用方会 `asyncio.run` 一个临时循环记一句（`announce_soon`）。
- **改了**：`core/loop_local_lock.py` 的 `LoopLocalLock`，每个事件循环各一把 `asyncio.Lock`。同一循环里照旧互斥，
  落盘另有线程锁。会话管理器改用它。
- 验证：新增 `test_a_dropped_event_loop_does_not_lock_sessions_out.py`。没有这个修复时，会话那条用例报的就是 CI 上那句错。
  会话相关测试 1494 项通过。

### 6.36 2026-10-26：设备自述与边界的整体设计（只有文档，还没动代码）

- 所有者批准方向，设计写在 `docs/DEVICE_SELF_DESCRIPTION_DESIGN.md`：
  - 设备用一份 `self_description` 描述自己（名字、一句形态描述、动作和每个动作的 `effect`、此刻做不了的动作和原因、四样设备级声明）；
  - 状态由设备报，中心不推断；动作给模型用，声明给边界用，`shows_messages` 并回各设备的通知或消息动作；
  - 代码只守一张边界清单，权限门按动作的 `effect` 判；
  - 评测用真实模型本地跑：中心挑设备 12 个场景；手机端测参考面壁 AgentCPM-GUI 的评测（定位、单步动作 TM/EM、端到端、端侧开销）。
- 读码时查出、要在实施里修的：设备动作（`device__<id>__<action>`）没有任何风险策略能匹配上，一律按 MODERATE 放行、不确认；
  自治档位只覆盖声明了白名单的节点，读写按动作名猜，`heart_rate`、`calendar` 这类读动作认不出来。
- 分 6 步实施，进度记在设计文档末尾。

### 6.37 2026-10-26：设备自述 v1（设计文档第 1 步）

- **设备怎么说自己**：能力上报里带 `self_description`（schema `contracts/device_self_v1.json`，`device_self/1`）。内容：
  - 名字、自报类型（只是描述）、一句形态描述；
  - 每个动作：一句说明、参数的 JSON Schema、做了会怎样（`effect`：只看 / 打扰人 / 改状态 / 对外发出 / 不可逆）、要不要人在设备上点（`needs_human`）；
  - 此刻做不了的动作和原因（`unavailable`）；
  - 四样设备级声明（`answers_decisions` / `shows_request_progress` / `hosts_agent` / `tailnet`）。
- **中心只在一处读**：`core/device_self.py`。新旧两种上报读成同一个对象，存进 UDM 元数据 `self_description`；
  带了自述的展开回旧字段（动作清单、说明、参数、声明、`bridge_agent`）再交给后面的处理，那几处不用知道有两种上报。
  读入是宽松的：不合 schema 的地方记日志、能用的照用；严格的是三边的契约测试。
- **设备卡片**：说了自己是什么的设备，卡上显示 `kind`、`about`、`unavailable`，每个动作带 `effect` / `needs_human`，不再按类型猜一个「形态」词；
  旧版设备照旧（`form` 还在）。名字：中心这边没有名字（或只有设备 id）时用设备自报的。
- **三边一份形状**：安卓仓 `shared-protocol` 新增 `DeviceSelfDescription.kt`，手机、手表共用；拼的时候就拒掉中心认不出的（动作名、`effect`、`tailnet`、空原因）。
  跨仓闸门升到 1.2.0，清单里写明 `device_self/1`；`tests/test_devices_describe_themselves.py` 进了 CI 里检出安卓仓同名分支的那一组，逐字对照 Kotlin 的键名与取值范围。
- **手机**：每个动作标 `effect` 和参数；发短信、打电话、加日程标 `needs_human`；权限没给的进 `unavailable`（「手机上还没给 Galaxy 打开:通讯录」）。
  还没有显示提问的界面，所以 `answers_decisions` 仍是 false（第 2 步加）。
- **手表**：通知、震动是打扰人，状态、心率、步数是只看；参数与执行器读的一致；心率、计步缺传感器或没给权限时进 `unavailable`，原因就是手表上那句。
- **验证**：
  - V2 新增 10 项，其中「安卓真拼出来的两份帧」是从 Kotlin 构造器导出的，不是照 schema 手写；变异两处（不展开自述、不把 `hosts_agent` 当成 `bridge_agent`）各自变红。
  - 受影响的 346 个测试文件 13367 项通过；守卫全过。
  - 安卓、手表的纯 Kotlin 部分本地 JVM 77 项通过；整 App 的编译和其余单测交给两边 CI。
- **合并顺序**：手表 PR 用安卓仓同名分支的 `shared-protocol`，要先合安卓 #539，再合手表 #24。

### 6.38 2026-10-26：动作与声明归位(设计文档第 2 步)

- **下发前过边界**(`core/device_boundaries.py`,`devices__invoke` 与多步计划的每一步都经过):
  - **参数**:按设备自述里这个动作的 `params` 校验,不合法不发,把原因和格式交回模型;
  - **要不要先问人**:按动作的 `effect`、`needs_human` 与自治档位判(表见设计文档第 5 节)。引导档(默认)下只看、打扰人的直接做,改设备状态的先问,对外发出、不可逆的走高风险确认;`needs_human`(手机只备好短信 / 拨号 / 日程、人点一下才生效)设备上那一下就是确认;设备没说 `effect` 的,动作名一看是读的按读,其余按改状态。
  - **怎么问**:有声明能回答提问的设备在线,就在那上面给「不要 / 仅此次 / 本会话 / 永久允许」,选了后两个记一条授权(`/api/v1/approval-grants` 能列出、撤销),下次不再问;没有就在对话里问,人答应了智能体再调一次。问不到、超时、含糊的回答都当没批准。
  - **此前**:`device__<id>__<action>` 匹配不上任何风险策略,一律放行不确认;自治档位按动作名猜读写。
- **授权记录挪进数据目录**:`approval_grants.json`(原来写在仓库根 `.galaxy_grants.json`,测试会写进仓库;已有的旧记录继续用)。
- **`shows_messages` 收掉**:发给谁是模型的判断。`ask_human__notify` 调点名设备(没点名就是发起这件事的那台)自己报的消息动作(`effect` 为 `notify`、收 `text`,手表的 `notify`、手机的 `notification`),和 `devices__invoke` 同一条路;报了自述却没有这样的动作就照实说送不到;还没有自述的旧版设备照旧收一条 `agent_message`。中心不再读这项声明,设备卡片上也不再有。
- **手机能回答提问了**(安卓 #539):`decision_request` 弹成通知,选项不多于三个直接放按钮,点开通知是列出全部选项的对话框;人点的选项以 `human_input` 回去(和手表同形),别处先答了收起通知。通知打得开才声明 `answers_decisions`。
- **电脑客户端与载体也带自述**(`device_client/self_description.py`):截屏、读窗口、读文件、列目录、读状态是只看,其余是改状态;载体跑代码也算改状态(只在不联网的沙箱里跑)。
- **测试替身照真设备拼**:`tests/device_self_frames.py` 取安卓仓 Kotlin 构造器真拼出来的两份自述;引导档下要先问的那几条(笔记本点屏幕、设备回失败)改成按自主档跑,先问那一道单独测。
- **验证**:
  - `tests/test_device_actions_pass_the_boundaries.py` 26 项:表的每一格、拿不准往严里算、参数、四种回答、对话里问、高风险与 `needs_human`、真网关上读直发 / 改状态先问 / 参数不全不发、手机被问后点「永久允许」照做且下次不问;去掉边界调用、去掉 `needs_human` 那条各自变红。
  - 受影响的测试约 39000 项通过(其中 1 项蓝牙假服务在并行负载下没起来,单独跑通过);相关的 53 个文件 1337 项在最后一版上全过;守卫全过。
  - 安卓 `DecisionFramesTest` 6 项、`PhoneSelfDescriptionTest` 更新,纯 Kotlin 部分本地 JVM 38 项通过;手表 `WatchMemberFramesTest` 更新。整 App 编译交给两边 CI。

### 6.39 2026-10-26：状态统一由设备报(设计文档第 3 步)

- **状态跟着心跳走**:心跳帧的 `payload.state`(schema `contracts/device_state_v1.json`,`device_state/1`),只有几个固定的键:电量、充电、屏幕、戴没戴着、通话、能不能打扰(`blocked` / `busy` / `neutral` / `free`)和一句 `note`。每一份都是此刻的全部,中心整份替换上一份 —— 这一份里没有的键就是设备现在不知道。
- **中心只在一处读**:`core/device_state.py`。只收认识的键,心率这类原始信号就算被塞上来也进不了中心;记进 UDM 元数据 `device_state`。`interruptible` 交给可打扰性登记处,这份没报就撤掉这台设备上一份的(手表说不出所以然时,上一份的「明确别打扰」不再挡着)。
- **卡片上的状态只有两种来源**:中心看到的(在线、最后见到、网络路径、有没有命令在跑)和设备报的。设备离线、或这份过了 25 分钟,设备报的就不写;从没报过的设备卡上只有中心看到的那几项。此前电量读 `device_status_report`、能不能打扰另读登记处,两处各读各的。
- **不再写死「手表」**:常驻注意力循环的提示词和被拦下时的理由写明是哪台设备说的(人叫它的名字);哪台设备报了 `blocked` 都一样拦主动开口。
- **旧帧照认一个版本**:旧版手表单独发的 `interruptibility` 帧(原因标签由中心译成一句话)、旧的 `device_status` 帧里的电量、充电、屏幕。
- **跨仓闸门升到 1.3.0**,清单里写明 `device_state/1`;`tests/test_devices_report_their_state.py` 进了 CI 里检出安卓仓同名分支的那一组,逐字对照 `DeviceState.kt` 的键名与取值。
- **手机**(安卓 #539):`shared-protocol` 新增 `DeviceState.kt`(手机、手表共用);手机每一拍心跳(30 秒)带上电量、充电、屏幕、通话;开着勿扰时报 `blocked`;戴没戴着手机不知道,不报。
- **手表**(手表 #24):可打扰性并进心跳的状态,不再发单独的帧;档位由手表判断,原因由手表写成一句话(「极可能在睡、静止」,证据不足时说一声),中心不再翻译标签;屏幕、充电、通话变了也报,没变最多每 10 分钟一条。戴没戴着现在测不出,不报。隐私契约测试改钉状态:键只能是那几个,原因只有词、没有数值。
- **验证**:
  - V2 新增 13 项,手机、手表的状态取自 Kotlin 构造器真拼出来的三份;变异六处(心跳不记状态、不撤上一份、离线也显示、卡片不筛键、读入收下认不出的键、卡片不读设备状态)各自变红。
  - 受影响的 1413 个测试文件 46774 项通过;另有 3 项是环境造成的,单独干净地跑通过:蓝牙假服务的套接字路径超长;仓库根有一份被忽略的 `.env`,是跑测试时从 `.env.example` 复制出来的,影响了两项密钥测试。守卫全过。
  - 安卓 `DeviceStateTest` 6 项、`PhoneStateTest` 4 项、`PhoneDirectCommandWireTest` +1;手表 `WatchStateTest` 9 项、节流 +1;纯 Kotlin 部分本地 JVM 通过。两边 CI(整 App 编译与单测)已绿。
- **合并顺序**:手表不再发单独的可打扰性帧,V2 要先于手表合(或同时合),否则旧中心看不到手表的可打扰性;安卓 #539 仍先于手表 #24。

### 6.40 2026-10-26：边界清单落成一个模块(设计文档第 4 步)

- **七条边界各一个函数**(`core/device_boundaries.py`),`BOUNDARIES` 与设计文档第 5 节那张表一一对应,测试逐条对照:
  1. `member` 成员资格:在名册里;讲 AIP 的设备此刻连着;开了设备准入(`GALAXY_REQUIRE_DEVICE_APPROVAL`)的,接入时批准过。
  2. `permission` 权限门与自治档位(第 2 步那张表)。
  3. `params_ok` 参数合法。
  4. `interrupt_budget` 主动打扰有额度:智能体自发(自发注意力、定时心跳、主动感知)的 `notify` 计入每小时额度,与自发开口同一个设置;有设备报了「此刻明确别打扰」时,自发的不发;人在等结果的请求不算主动打扰。
  5. `one_at_a_time` 每台设备串行且一定有结果(成了、没成的原因或超时);`record_start` / `record_end` 记进任务流程图。
  6. `as_reported` 结果以设备回的为准:设备说没成就是没成,原因用它的原话。
  7. `kept` 隐私:中心只记成没成和原因,不留设备回的数据(心率、通讯录、截屏)。
- **下发顺序**:先 1;讲 AIP 的设备再过 3 → 4 → 2(便宜的先查,问人放最后);发的时候 5;结果 6;记账 7。
- **补上的两个缺口**:
  - 开了设备准入时,没批准的设备此前只是不作为委派目标,`devices__invoke` 照样能给它下发动作。现在两条接入路径都把批没批记进 UDM 元数据 `admission_approved`,成员资格那条不放行。
  - 不在线的设备,此前要先问人批准、再在派发链上报「没有连接」;现在一开始就说不在线,不去问人。
  - 做完的多步计划此前把每一步的结果(可能是通讯录、心率)写在 `task_plans.json` 里留着;现在做完写盘时去掉,成没成和原因照留。进行中的照带结果,依赖它的步骤和崩溃后接着做要用。
- **验证**:
  - `tests/test_the_boundary_list_is_one_module.py` 18 项:表与代码对照,七条各有测试,其中准入一项经真网关(没带令牌登记的手表连着但不给它下发,带令牌的放行)。
  - 去掉任一条,对应测试变红(12 处变异,含「下发路径不调成员资格」「gate 不调额度」)。
  - 受影响的 1414 个测试文件 46793 项通过;另有 2 项是环境造成的(蓝牙假服务的套接字路径超长;仓库根那份被测试复制出来的 `.env`),单独干净地跑通过。守卫全过。
- **会看到的变化**:智能体自发的提醒,一小时超过自发开口的额度、或有设备报了明确别打扰时,不发,原因交回智能体。人自己要的提醒不受影响。

### 6.41 2026-10-26：评测(设计文档第 5 步)

行为交给模型以后,「挑对了没有」单测证明不了,只能用真模型跑场景来回答。这一步把两套评测搭好,第一轮真模型等所有者来跑。

- **中心:挑设备与守边界**(`scripts/eval_device_choice.py`,说明与每轮结果在 `docs/eval/device_choice.md`):
  - 跑真的推理循环(`OpenClawd._react_loop`)和真的工具执行(设备工具、设备边界、规范派发链);设备是按剧本回话的替身,人对提问的回答也按剧本,只有模型是真的。
  - 第一批 12 个场景(`config/eval_cases/devices/first_batch.jsonl`):提醒发到手表、手表离线、全都不在线、从手机日历排日程、心率没给权限、发短信要人点、开会时别打扰、手机离线只剩电脑、两台手机都有日历、删文件要确认、没见过的 Linux 载体跑代码、设备说没成。
  - 指标:设备挑对、动作挑对、参数合法、诚实、边界违例(必须为 0)、平均轮数与用时;每轮自动记一行、和上一轮比;有违例时退出码是 1。要真的模型 key,本地手动跑,不进 CI。
- **手机端测**(安卓仓 `tools/eval/`,结果记进 `docs/eval/phone_gui.md`):
  - 参考面壁 AgentCPM-GUI 的评测,数据是中文 App 基准 CAGUI。**判定细则照抄他们的代码**(点击阈值 0.14、滑动 0.04、大框放大 1.2、文字互相包含或编辑相似度),数字能直接和公开数字比。
  - L1 定位、L2 单步动作在电脑上跑:JVM 编译 App **自己的** `VlmPlanner` / `VlmGroundingEngine` 源码,连电脑上的 `llama-server`、载同一份 GGUF;截图按 App 的做法压(定位长边 720,规划由 `VisionContextBudget` 反推)。我们的动作格式换算成他们的(滚动方向内容↔手指要反过来),预测另写一份他们的 `all.jsonl`,可以拿他们的脚本再判一遍对照。
  - L3 端到端(20 个中文日常任务:打车、点外卖、发消息、设闹钟……,要花钱、要发出去的只做到确认那一步)和端侧开销(每步时延、加载、峰值内存、30 分钟耗电和温度)写进 `docs/REAL_DEVICE_CHECKLIST.md` 第 4 节。
  - 真机清单第 3 节同时补上第 3、4 步的验收:状态由设备报、有设备报别打扰时不主动开口、开了设备准入时不给没批准的设备下发。
- **验证**:
  - V2 `tests/test_the_device_choice_eval_judges_what_it_should.py` 6 项:用例里写好的标准做法 12 条全对、零违例,而且真走了边界(删文件走了高风险确认、载体跑代码先问了人、发短信不另外确认);一个不看卡片、挑第一台设备第一个动作直接调、然后说「办好了」的模型,动作挑对和诚实都过不了半,边界违例仍是 0;违例判得出;每轮记一行。
  - 安卓 `tools/eval` 单测 18 项:判定按他们的代码一步步算出的期望值逐条对照(去掉大框放大的变异会变红)、动作换算、对着一个 llama-server 替身跑通 L1 / L2 整条链。进安卓 CI。
  - 安卓 `:shared-protocol` 的单测(自述、状态、提问帧的契约,55 项)此前 CI 没跑,这次一并加上。
- **还没做**:真实模型的第一轮。本环境没有模型 key,也没有端侧模型;Hugging Face 被挡,取不到 CAGUI。所有者跑完,两份结果页各记一行。手机本地循环录轨迹的入口也还没做(App 的循环记录按设计不存截图),L2 暂时只用 CAGUI。

### 6.42 2026-10-27：设备侧清理(设计文档第 6 步,六步做完)

- **手机不再上报设备角色**:`device_role`(写死的 `"phone"`)从能力上报的 metadata、目标结果帧、对账信号的 `runtime_truth` 和拓扑节点里去掉。中心本来就不读它(唯一读的 `galaxy_gateway/autonomous_filter.py` 在没有角色时放行,且生产里没人传 `task_role`)。手机的导出契约 schema 升到 2,必备元数据 29 → 28。
- **手机不再按角色名判断**:删掉 `AndroidOperationalDeviceSupport.classify`(按 phone / tablet / hub 分级,只用在本地投影)。能不能参与执行、能力档、调度资格只看真实具备的执行维度、参与状态和就绪 / 健康。生产里角色一直是 `phone`,行为不变。
- **手机 `runtime/` 契约层冻结**:`tools/check_runtime_freeze.sh` 进安卓 CI 第一道,文件数只许减不许增(现在 227);少了也红,提醒把基线一起改小,收掉的位置不会被悄悄补回去。
- **手表文案**:README 写明设备自述(做不了的动作附原因)和随心跳报的状态,协议示例补上 `self_description` 和 `payload.state`。
- **中心**:测试里手机的能力上报不再带 `device_role`,和真手机一致。
- **验证**:
  - 安卓:原来「hub 被降级」的三项改成「换个角色名,执行参与、能力档、调度资格都一样」;在场与执行分开那项改用宿主待机造出「只在场」;结果帧序列化后不含 `device_role`;能力上报必备键、导出契约、对账真相的键跟上。会话两组测试本地 JVM 通过(44 + 16),其余依赖 Android 的由 CI 编译和跑。冻结检查加一个文件、删一个文件各验过一次,都红。
  - V2:相关测试照跑通过。
- **六步的整体结果**:设备用一份自述说自己是什么、能做什么、此刻做不了什么;状态由设备随心跳报;中心只在七条边界上设防,其余交给智能体看卡片决定;两套评测搭好,等所有者跑第一轮真模型;两端都不再按设备类型或角色名分支。真机上的验收见 `docs/REAL_DEVICE_CHECKLIST.md`。

## 7. 还没解决的（多数需要决定，或需要真机）

| 问题 | 位置 / 依据 | 为什么这次没改 |
|---|---|---|
| 多设备（mesh / federation）没有真机证据 | 运行时登记 `structural_only`（第 4、5.3 节） | 缺的是真机多设备环境里的运行证据，不是代码 |
| 注册下游步骤不完整时只记账、不阻断 | G002（第 5.2 节） | 所有者 2026-09-28 答复：**后面做**，和未接线代码的处置放在一块儿 |
| 面板：拓扑/可观测视图没搬进面板 | `PANEL_SURFACE_CONVERGENCE.md`「未做」 | 属于面板设计 |
| 旧 WS 路径 `/ws/ufo3` 未退役 | 路线图 C6 | 需要安卓侧先确认老客户端已迁走 |
| 自我改进总闸默认关闭 | `GALAXY_META_RSI=off` | 由仓库所有者决定 |
| 未接线 / 不可达：删还是接 | 755 条 + 3 个模块。**按用途说它们是干什么的**见 `docs/UNWIRED_CODE_INVENTORY.md` 第 2 节；**安卓以外 672 条每条该放在哪里**见第 7 节（接上 215、挂出来 134、删掉 170、随对象走 91、测试钩子 50、框架回调 4、产品决定 8；数据在 `config/unwired_placement.json`，`tests/test_unwired_placement.py` 守着它与清单对账）。逐条核对时新确认两处「看得见但不生效」：`PUT /api/v1/security/policy` 改的零信任规则表没有执行方；系统资源表有人读、没人登记 | 所有者要求先弄清楚再动；清单与去处已给，**没按它删或接任何一行**。所有者 2026-09-28：后面和 G002 放一块儿做 |
| 只在 Windows 上出现的几项 | 逐项查证见 6.9。托盘（图标等菜单数）和 Podman（引擎不通时不拉虚机）已修；`PyAudioWPatch`、Ollama 冷启动 Phase 0 是设计如此；仍需要真机的是：托盘 / 启动各段**到底慢多少**、面板圆角在 Windows 上的实际观感 | 这里是 Linux，复现不了；每一项屏幕上都已经说出原因和怎么办，没有静默 |
| 第一次对话仍要现 import 一百多个模块 | Linux 上约 0.3 秒，Windows 杀软逐个扫时会更长 | 启动时预热的收益有限，且要维护一份模块清单；没做 |
| 大文件 | core 有 133 个文件超过 1000 行 | 已有复杂度基线守着，只许拆、不许涨 |
| 进程退出时偶发 `Unclosed client session` | 某处 aiohttp 会话没关（复测时在 `tests/integration/test_android_nl_semantic_chain_e2e.py` 结尾出现过一次，复现不稳定） | 只影响退出时的一行日志；第 7 轮三次真跑都给每个会话记下了创建位置，一次也没出现 |
| 文档漂移 | 286 份 Markdown 中，2026-08-05 之后只改过 9 份 | 本次给 41 份状态/审计类文档加了快照说明，指向本文；正文保留原样 |

本地跑过测试的工作树里，旧位置的 `data/registered_devices.json` 可能已经混进了测试设备（修复前的测试写进去的）。
这个文件不进仓库，删掉即可。

安卓仓和手表不在本次复测范围内。

---

## 8. 全量测试

`pytest tests/`（`--timeout=300`，本地 Python 3.11，与 CI 同版本），一次跑完整套：

| 轮次 | 通过 | 失败 | 跳过 | 用时 |
|---|---:|---:|---:|---|
| 复测前（main @ 6489ff6 + 镜像修复） | 45,068 | 6 | 156 | 31 分 25 秒 |
| 本次全部修复后 | 45,117 | 1 → 0 | 151 | 31 分 54 秒 |
| 2026-09-28 这一轮（第 6.4 节）之后 | 45,197 | 3 → 0 | 152 | 34 分 46 秒 |

2026-09-28 那一轮的 3 个失败也是本轮自己改出来的（CI test-shard 1 同样红了）：隔离队列的路由原先用 `include_router`
挂进可观测性路由，新版 FastAPI 把被包含的子路由存成一个没有 `.path` 的条目，
`tests/test_pr4_execution_evidence_canonical_truth.py` 的 P 组遍历 `router.routes` 读 `.path` 时出错。改为把端点直接登记到
可观测性路由上（`core/routes/result_recovery.register`），那 3 条通过。

上一轮修复后唯一的失败，是我自己改出来的：`core/ascii_art.py` 改成从 `core.version` 取版本号以后，
被当脚本直接跑（`python core/ascii_art.py`）时仓库根不在 `sys.path` 上。已按 `core/release_blocking_gate.py`
的同一做法补上引导，那条用例（`tests/test_core_scripts_run_standalone.py`）通过。

复测前那 6 个失败**单独重跑全部通过**，都不是产品代码的问题，但都是真实的测试隔离缺陷，**本次都已修掉**（第 6.3 节）：

- `tests/test_vision_backends_are_pluggable.py` ×3、`tests/test_the_vision_and_audio_lanes_use_the_same_keys.py` ×1：
  顺序依赖。只要 `tests/test_config_schema_ui_parity.py` 先跑，这 4 个就必定失败（本地稳定复现：
  `pytest -p no:randomly tests/test_config_schema_ui_parity.py tests/test_vision_backends_are_pluggable.py`）。
  前者留下的 key 被视觉后端的可用性判断读到了。CI 是绿的，只是因为分片把它们分开了。**这个问题 main 上本来就有。**
- `tests/test_launcher_doctor.py` ×2：依赖本机环境（有没有装 nats-py 等包）。补齐这些包之后单独跑能通过。

另外观察到三件事，本次也都已修掉：
- 测试会拉起真实节点进程，并且测试结束后进程还在：
  `tests/test_device_drivers_are_reused_and_found.py`（Node_33_ADB）和 `tests/test_device_onboarding_taxonomy.py`（Node_45_DesktopAuto）。
  这两个进程的父进程是 1，套件结束后一直活着。
- 测试会写进仓库的 `data/registered_devices.json`（设备注册表不认 `GALAXY_DATA_DIR`）。
- `tests/test_a_laptop_joins_by_pairing.py` 起的真实设备客户端测完不停，网关关掉以后每 5 秒重连一次，
  一直持续到整个会话结束。`tests/test_route_construction_is_offline.py` 在进程级拦截 `socket.connect`，
  会把这些连接算到自己头上。本 PR 第一次推送后，CI 分片的组合变了，test-shard 4 因此红过一次。

```bash
python -m pytest -q -p no:cacheprovider --timeout=300 tests/
```

---

## 9. 文档地图

**现行（以这些为准）**
- 本文：当前状态
- `AGENTS.md`：代码地图与约定
- `META_LAYER_RSI_ARCHITECTURE_CN_2026.md`：元层（阶段一已落地）
- `RENDER_CONTRACT_DIRECTION.md`、`PANEL_SURFACE_CONVERGENCE.md`：前端契约与面板
- `architecture/DEVICE_ONBOARDING_PLANE_V1.md`：设备接入
- `CROSS_DEVICE_OVERALL_PLAN.md`：跨设备整体方案（阶段 0–6，已做完）
- `DEVICE_SELF_DESCRIPTION_DESIGN.md`：设备自述与边界（设备怎么描述自己、代码守哪些边界、怎么评测）
- `REAL_DEVICE_CHECKLIST.md`：手机 + 手表 + 电脑的真机验收清单（装哪个包、逐项怎么做、应该看到什么）
- `eval/`：评测怎么跑与每一轮的结果（`device_choice.md` 挑设备与守边界，`phone_gui.md` 手机端测）
- `NODE_HTTP_SECURITY_CONTRACT.md`：节点安全
- `UNWIRED_CODE_INVENTORY.md`：未接线与不可达代码逐类清单，以及安卓以外每个函数的去处（等所有者定删还是接）
- `config/assessment_claims.json`：可机械复验的结论清单（`python scripts/check_assessment_freshness.py`）
- `core.canonical_capability_status`：运行时对自身能力的登记

**历史快照**：以下文档的开头都已加上快照说明，正文保留原样（改写成像是从未存在过，比保留更失真）：

ARCHITECTURE_COMPLETION_SCORECARD · ARCHITECTURE_GAP_CLOSURE ·
AUTHORITATIVE_PATH_CONVERGENCE_AUDIT · CENTER_DISTRIBUTED_AGENT_JOINT_REVIEW_CN ·
CENTER_DISTRIBUTED_AGENT_SYSTEM_REVIEW · CODE_EVIDENCE_DUAL_REPO_SYSTEM_AUDIT · COMPLETE_SYSTEM_USABILITY_CLOSURE_PLAN ·
DUAL_REPO_COGNITION_AUDIT_ZH · DUAL_REPO_COGNITIVE_MAP · DUAL_REPO_FULL_REAUDIT · DUAL_REPO_GAP_MATRIX ·
DUAL_REPO_SYSTEM_COMPLETENESS_REVIEW · DUAL_REPO_UNRESOLVED_AUDIT ·
FINAL_INTEGRATED_SYSTEM_AUDIT · FOLLOWUP_IMPLEMENTATION_ROADMAP（顶部附复核表）· FULL_SYSTEM_JOINT_REVIEW ·
GALAXY_COMPLETE_FIX_REPORT · GALAXY_SYSTEM_FORMAL_BASELINE_COGNITION_ZH · JOINT_CODE_INVESTIGATION_REVIEW ·
JOINT_CODE_REVIEW_DUAL_REPO_2026Q2 · JOINT_SYSTEM_REVIEW_V2_ANDROID_2026Q2 · LEGACY_DECOMMISSION_AUDIT ·
MATURITY_PROGRESS_REVIEW_2024 · MATURITY_REVIEW_2026Q2_DUAL_COORD · MULTI_DEVICE_RUNTIME_MATURITY ·
NODE_SYSTEM_AUDIT · ORCHESTRATION_OBSERVABILITY_REVIEW · POST_1114_1115_DESKTOP_STATUS_BOARD_RECOGNITION_REVIEW ·
REAUDIT_ANDROID_PROTOCOL_V2 · REAUDIT_FOLLOWUP_ROADMAP_V2 · REAUDIT_FRESH_PASS_2 · REAUDIT_GAP_MATRIX_V2 ·
REAUDIT_MULTI_DEVICE_MATURITY_V2 · REAUDIT_SCHEDULING_AUTHORITY_V2 · RESIDUAL_GAP_MAP · SYSTEM_AUDIT_REPORT_ZH ·
SYSTEM_READINESS_REVIEW_PR8 · TRUTH_PROJECTION_CONVERGENCE_MAP · UNIFIED_SCHEDULING_AUTHORITY_MAP ·
V2_ANDROID_RUNTIME_CLOSURE_AUDIT · V2_READINESS_GOVERNANCE_EVIDENCE_MATRIX · ANDROID_PROTOCOL_MATURITY_MATRIX ·
`audit/completion_matrix.json`（分数是 2026-04-29 的；复核写在 `rederived_2026_09_27` 字段）

**下次复测怎么做**：把第 2、3 节的命令重跑一遍；`scripts/check_assessment_freshness.py` 报 stale 的结论要重新推导，
并且回头改它 `source` 指向的那份文档（`config/assessment_claims.json` 的 `_how_to_use` 里写着这条规矩）。
