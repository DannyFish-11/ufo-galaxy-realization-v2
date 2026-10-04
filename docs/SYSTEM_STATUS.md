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

- 系统托盘 8 秒内没出现在托盘区：启动阶段会等图标**真的**出现再报告，这是有意的诚实检查；等待本身是非致命的。没在 Windows 真机上不改。
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
| 留在面板 | 45 | 用户真有取舍（隐私、花费、硬件与网络、安全姿态），按「声音 / 感知与在场 / 记忆与隐私 / 桌面操作与自治 / 模型与花费 / 多设备与网络 / 安全姿态」分组 |
| 内置 | 33 | 不再列在面板上：熔断器、派发幂等、回声消除子参数、自回声闸门等不该有人去关的机制，默认开 |
| 开发 / 运维 | 18 | 不再列在面板上：`GALAXY_DEV_MODE`、Tauri 打包、「本机回环也封禁」等 |

不列 ≠ 没接上：键仍在 `CONFIG_SCHEMA`，`POST /api/config` 照收、`.env` 照写、环境变量照读。

**清点时顺带查出的三处真问题**（都已修）：

| 问题 | 修复 | 验证 |
|---|---|---|
| 「保存设置」会把登记表里每个键的默认值整体写进 `.env`。`GALAXY_MEMORY_MEDIA` 登记成「默认开」而代码三处默认都是关 —— 保存一次，截图和录音就在没人点过的情况下开始落盘；另有 `GALAXY_ENTRYMODE_USE_READINESS`、`GALAXY_PREFLIGHT_FAIL_FAST` 与代码相反 | 登记表默认值对齐到代码；就绪度开关改为认 `true`/`1`/`on`（面板写的是 `true`，代码以前只认 `"1"`） | `tests/test_every_switch_has_a_disposition.py` |
| 设置页只认字面量 `"true"` 为开：`.env` 里手写的 `=1` / `=on`、登记表里写成 `1` 的默认值（`GALAXY_CONSENSUS_ROUND`）代码认作开，面板显示成关，点一下还会把它「关」成 `false` | `GET /api/config/all` 把布尔值统一规整成 `true` / `false`；登记表布尔默认值全部是字面量 | 同上 |
| `GALAXY_COMPUTER_USE_NATIVE_TOOL` 的类型登记成 `bool`，设置页把它画成文本框 | 归一为 `boolean` | 同上 |

新增布尔开关必须先在清单里说清是哪一种、为什么（同一个测试盯着）—— 这是「不要乱加开关」的可执行形式。
**没有动**的合并（多设备四处总闸、出声两个、原生听两个、安全姿态做成一个档位）会改变行为，列在 PANEL_SWITCHES.md 末尾等你定。

## 7. 还没解决的（多数需要决定，或需要真机）

| 问题 | 位置 / 依据 | 为什么这次没改 |
|---|---|---|
| 多设备（mesh / federation）没有真机证据 | 运行时登记 `structural_only`（第 4、5.3 节） | 缺的是真机多设备环境里的运行证据，不是代码 |
| 注册下游步骤不完整时只记账、不阻断 | G002（第 5.2 节） | 所有者 2026-09-28 答复：**后面做**，和未接线代码的处置放在一块儿 |
| 面板：拓扑/可观测视图没搬进面板 | `PANEL_SURFACE_CONVERGENCE.md`「未做」 | 属于面板设计 |
| 旧 WS 路径 `/ws/ufo3` 未退役 | 路线图 C6 | 需要安卓侧先确认老客户端已迁走 |
| 自我改进总闸默认关闭 | `GALAXY_META_RSI=off` | 由仓库所有者决定 |
| 未接线 / 不可达：删还是接 | 755 条 + 3 个模块。**按用途说它们是干什么的**见 `docs/UNWIRED_CODE_INVENTORY.md` 第 2 节；**安卓以外 672 条每条该放在哪里**见第 7 节（接上 215、挂出来 134、删掉 170、随对象走 91、测试钩子 50、框架回调 4、产品决定 8；数据在 `config/unwired_placement.json`，`tests/test_unwired_placement.py` 守着它与清单对账）。逐条核对时新确认两处「看得见但不生效」：`PUT /api/v1/security/policy` 改的零信任规则表没有执行方；系统资源表有人读、没人登记 | 所有者要求先弄清楚再动；清单与去处已给，**没按它删或接任何一行**。所有者 2026-09-28：后面和 G002 放一块儿做 |
| 大文件 | core 有 133 个文件超过 1000 行 | 已有复杂度基线守着，只许拆、不许涨 |
| 进程退出时偶发 `Unclosed client session` | 某处 aiohttp 会话没关（复测时在 `tests/integration/test_android_nl_semantic_chain_e2e.py` 结尾出现过一次，复现不稳定） | 只影响退出时的一行日志；复现一次要 4 分钟，这次没有定位到创建点 |
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
