# 系统现状（2026-09-27 复测）

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
> 复测基线：`main` @ `6489ff6`，外加本次 PR 的修复（第 6 节）。每节末尾附复测命令。

---

## 0. 结论

**完成度：单机主干已经闭合，并且真跑得起来。**
在没有配置任何 API Key 的干净环境里，`python main.py --backend` 约 45 秒就绪。自报「4 正常 · 7 降级」，
每一项降级都说清楚了缺什么、怎么装。11 个只读接口全部返回 200。没配 Key 时，对话会明确告诉用户
「AI 服务不可用，请检查 API Key」，不会崩。桌面三态和入口分流在真实 HTTP 上复测通过。
跨设备、多设备和联邦这三块代码都在，但**没有经过真机验证**，运行时自己也把它们登记为
`structural_only` / `experimental`。

**完善度：主路径扎实，外围有几处真断点，这次查出来最严重的是容器镜像。**
主分支上所有的 CI 门都是绿的，唯独 **Supply-Chain：三个容器镜像一个都构建不出来**，
而且就算构建出来，其中两个也跑不起来。从 2026-08-31 起，这条工作流在 main 上每周的定时运行都是红的
（至少连续 4 周）。PR 上却一直显示绿：在 PR 上它只跑哈希校验和节点报告两步，构建镜像那一步
只在 push 和定时运行时才跑。所以红灯只出现在 main 上，一直没人去查原因。本次 PR 已修复并加了守卫（第 6 节）。
另外还有几处较小的完善度问题，见第 7 节，留待决定。

**整体设计完成度：历史设计缺口基本关完，在建设计的阶段一已落地；最大的落差在文档。**
- 2026-04 审计列的 7 个关键缺口（G001–G007）：V2 侧 3 个已关，3 个由「静默」变成「可观测」（但仍不阻断），
  1 个属于安卓仓（不在本次范围）。
- 运行时闭合审计的 9 个残余缺口（GAP-512-001…009）**全部已在代码里关闭**，但清单里的描述一直没改，
  本次已更正。
- 后续路线图的 24 项里：15 项已落地（其中 A6 是以划边界的方式关闭的，A2/C1 有意保留了兜底路径），
  1 项有意保留（C4），6 项部分完成，2 项未做。
- 最大的落差在文档：286 份 Markdown 里，最近两个月只改过 9 份。

---

## 1. 规模与形态

| 部分 | Python 文件 | Python 行数 | 说明 |
|---|---:|---:|---|
| `core/` | 1,008 | 548,148 | 主体。中位文件 387 行；133 个文件超过 1000 行，8 个超过 3000 行（最大 `openclawd.py` 10,330） |
| `tests/` | 1,318 | ~638,000 | 测试行数多于 core 本身 |
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

`POST /api/v1/chat` 在没配 Key 时 0.5 秒返回 `success: true`，回复内容是「所有 AI 服务暂时不可用（已尝试: ），请检查 API Key 配置后重试。」
降级是明确的，不是崩溃；只是括号里「已尝试」后面是空的，见第 7 节。

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
| 全量测试 `pytest tests/` | **45,068 通过 / 6 失败 / 156 跳过**。6 个失败单独重跑全部通过，属于测试隔离问题，详见第 8 节 |
| 仓库守卫 `scripts/check_*.py` | 导入边界、文件复杂度、证据锚点、可达性、裁决独立性、元层、接线、债务冻结、主线路由、工作流 YAML、遗留回归、语义锚定、Agent 供给声明、仓库卫生 —— **全部通过**。`check_codeql_ledger` 本地判失败，原因是本地没有 SARIF 文件；它只在 CI 里有意义，并且是有意设计成「找不到就判失败」 |
| 结论保鲜 `check_assessment_freshness` | 18/18 条结论新鲜 |
| 就绪报告 `generate_system_readiness_report.py` | 42/42 通过。**注意它只查「文件在不在、模块能不能导入」**，所以它绿着的时候，镜像照样构建不出来 |
| 可达性 | 3 个模块不可达（已登记基线） |
| 未接线 | 756 个公开能力没有生产调用方（基线 760；这一轮接上了 4 个） |
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
| 渲染契约（`RENDER_CONTRACT_DIRECTION.md`） | **测试钉住**，剩 1 处已知缺口 | 第七节列出的 4 个缺陷已修；`skill.invoked`（`kind="rehearsal"`）**仍然没有任何消费方** |
| 面板表层收敛（`PANEL_SURFACE_CONVERGENCE.md`） | **部分** | 自述「未做」两项仍然成立：拓扑/可观测视图没有搬进面板；两套配置写入链路（ConfigService 写 config.json、CONFIG_SCHEMA 写 .env）没有合并 |
| 节点 HTTP 安全契约（`NODE_HTTP_SECURITY_CONTRACT.md`） | **测试钉住** | — |

### 5.2 历史缺口复核

**2026-04 完成度矩阵的 7 个关键缺口**（`audit/completion_matrix.json`，逐条复核记录在每个缺口的 `rederived_2026_09_27` 字段）：

| 缺口 | 当时 | 现在 | 依据 |
|---|---|---|---|
| G001 真相链静默降级 | P0 | **部分**：由静默变为可观测，但仍不阻断 | 真相链不完整的结果会记进 `IncompleteResultLedger`，并在 operator 可观测面上可见；没有硬失败、重试或死信 |
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
| 已落地（15） | A1, A2, A3, A4, A6（划边界关闭）, B1, B2, B4, B5, C1（兜底有意保留）, C2, D1, D2, D4, D6（V2 侧） |
| 有意保留（1） | C4：`galaxy_gateway/task_router.py` 仍在盘上，已登记为 LEGACY COMPAT 治理面；删不删是产品决定 |
| 部分（6） | A5, B3, B6, C3（指标有、告警没有）, C5, D5 |
| 未做（2） | C6（`/ws/ufo3` 仍在）, D3（会话迁移没有规范面 —— 见结论 `session-migration-has-no-canonical-home`） |

### 5.3 多设备这一块到底到了哪儿

代码层面，路线图 B 组要求的引擎基本都有了，只是名字和当初设计的不一样：
`mesh_session_progression_driver`（驱动会话状态）、`live_mesh_session_coordinator`、`live_mesh_runtime_engine`
（其中有参与方结果合并）、`mesh_session_persistence` / `body_mesh_persistence`（落盘与重启恢复）、
`formation_rebalance_engine`（编组重平衡）。

但是运行时把 `mesh`、`mesh_participation`、`federation` 登记为 `structural_only`，这个判断是对的：
这些引擎没有一个在真机多设备环境里跑过。**「代码写完」和「能用」之间，差的是真机证据，不是更多代码。**

---

## 6. 本次查出并已修复：三个容器镜像

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

---

## 7. 本次查出、没修，留给决定

| 问题 | 位置 | 后果 |
|---|---|---|
| 设备注册表的路径写死在仓库里 | `core/routes/_shared.py:54` 把路径写死成 `<repo>/data/registered_devices.json`，不跟 `GALAXY_DATA_DIR`。另外 15 个模块都跟这个变量，`tests/conftest.py` 也正是靠它把测试隔离开 | 测试注册的设备会写进真实的注册表：本次启动后 `/api/v1/devices` 列出了 **106 台测试设备**。改路径会让已设置 `GALAXY_DATA_DIR` 的部署「忘掉」已注册设备，需要做迁移兜底，因此没有顺手改 |
| 测试隔离：顺序依赖与孤儿进程 | 见第 8 节 | 本地一次跑全量会有 4 个假红；每跑一次全量都会留下 2 个常驻节点进程 |
| 版本号四处不一致 | 启动横幅 `v2.3.21`（`launcher/services.py`）、`core.__version__ = "3.0.0"`、镜像标签 `2.3.23`、README 抬头 `v10.0` | 用户和部署看到的版本号互相对不上 |
| 无 Key 时的提示里「已尝试」列表为空 | `POST /api/v1/chat` | 提示变成「（已尝试: ）」，少了信息 |
| LEGACY_DISPATCH 只有指标，没有告警规则 | `galaxy_gateway/observability.py` 有 `galaxy_legacy_dispatch_total`；`deploy/`、`config/` 里没有对应告警 | 路线图 C3 要求的「超过基线就告警」这一半没做 |
| 会话迁移没有规范面 | 见结论 `session-migration-has-no-canonical-home` | 路线图 D3 走不通；在建出规范面之前不应该合并两个 store |
| 自我改进总闸默认关闭 | `GALAXY_META_RSI`，默认 `off` | 由仓库所有者决定 |
| 未接线 / 不可达 | 756 个公开能力没有生产调用方；3 个模块不可达 | 都已登记基线，不会再增长；存量需要逐个判断删还是接 |
| 大文件 | core 有 133 个文件超过 1000 行 | 已有复杂度基线守着，只许拆、不许涨 |
| 文档漂移 | 286 份 Markdown 中，2026-08-05 之后只改过 9 份 | 本次给 41 份状态/审计类文档加了快照说明，指向本文 |

安卓仓和手表不在本次复测范围内。

---

## 8. 全量测试

`pytest tests/`（`--timeout=300`，本地 Python 3.11，与 CI 同版本），一次跑完整套：

| 通过 | 失败 | 跳过 | 用时 |
|---:|---:|---:|---|
| 45,068 | 6 | 156 | 31 分 25 秒 |

6 个失败**单独重跑全部通过**，都不是产品代码的问题，但都是真实的测试隔离缺陷：

- `tests/test_vision_backends_are_pluggable.py` ×3、`tests/test_the_vision_and_audio_lanes_use_the_same_keys.py` ×1：
  顺序依赖。只要 `tests/test_config_schema_ui_parity.py` 先跑，这 4 个就必定失败（本地稳定复现：
  `pytest -p no:randomly tests/test_config_schema_ui_parity.py tests/test_vision_backends_are_pluggable.py`）。
  前者留下的 key 被视觉后端的可用性判断读到了。CI 是绿的，只是因为分片把它们分开了。**这个问题 main 上本来就有。**
- `tests/test_launcher_doctor.py` ×2：依赖本机环境（有没有装 nats-py 等包）。补齐这些包之后单独跑能通过。

另外观察到两件事：
- 测试会拉起真实节点进程，并且测试结束后进程还在：
  `tests/test_device_drivers_are_reused_and_found.py`（Node_33_ADB）和 `tests/test_device_onboarding_taxonomy.py`（Node_45_DesktopAuto）。
  这两个进程的父进程是 1，套件结束后一直活着。
- 测试会写进仓库的 `data/registered_devices.json`，原因见第 7 节第一条。

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
