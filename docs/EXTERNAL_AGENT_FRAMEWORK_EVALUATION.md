# 外部 Agent 框架/协议评估：Tura / MFS / dsh-routing-suite / MHS

评估时间：2026-08-29（①②③）、2026-08-30（④ MHS）
结论：**四个都不接代码**，采纳其中一个想法（自己写）

这份文档留下的是**判断依据**，不是介绍。四个项目都真实存在，但落差各不相同：
①②③ 是宣传口径与可核实事实之间有距离；④ 是**根本还没有可实现的东西**。
记下来是为了下次遇到同类情况时，知道该先问什么。

---

## 核实方法与边界

* 事实来源：各项目 GitHub 仓库、npm registry、上游官方文档。
* **未能核实**的一律标注，不用推测填空。
* npm 下载量三个项目**都没查到** —— `api.npmjs.org` 与 `npm-stat.com` 在本环境被
  出网代理 403 拦截，registry 元数据本身不含下载数。
* **④ MHS 这一条的证据等级明显低于前三条，必须先说清楚**：`anthropic.com`、
  `modelhardwarestandard.com`、`siliconangle.com` 在本环境**全部被出网代理拦截**，
  一手页面一个都打不开。下面 MHS 的全部事实来自搜索结果摘要，属于**二手转述**。
  对照一下同期做 MCP 2026-07-28 时的做法 —— 那次是把官方
  `schema/2026-07-28/schema.ts` 原件拉下来 grep，确认 `initialize` 出现 0 次才动手；
  这次**没有任何等价物可拉**。

---

## ① Tura — 不接

| | |
|---|---|
| 仓库 | `Tura-AI/tura`，604★ / 32 fork，Rust |
| License | **AGPL-3.0**（npm 包 `AGPL-3.0-or-later`） |
| 活跃度 | 创建 2026-07-06，最近推送 2026-08-20；npm `tura-ai` 最新 0.1.37 |
| 形态 | **完整 Agent 运行时**（CLI / TUI / gateway / GUI），不是可单独取用的库 |

### 不接的两条硬理由

1. **AGPL-3.0**。对本仓是硬约束。
2. **它是整个运行时**。入口是 `tura` / `tura exec` / `tura_gateway`，要用它就是整体
   替换自建运行时 —— 而本仓的运行时（`core/agent/react_loop.py` + `core/openclawd.py`
   工具面 + `core/multi_llm_router.py`）是这套系统的骨架。

### 宣传数字的可信度：低，且转述有失真

数字确实有出处（`Tura-AI/benchmark`，MIT，9★，有可运行的 `benchmark.mjs`），
但该仓库**自己明文声明利益冲突**：

> "Tura-AI develops the Tura runtime, owns this benchmark repository, defines the
> Tura Balanced and Tura Direct configurations, and publishes comparisons against
> Codex. **This is a direct conflict of interest.**"

并补充 "do not provide independent task authorship, execution, or replication"、
"a **curated capability sample**, not a random sample"。样本 20 个 DeepSWE + 5 个
rewrite，2 replicates。**厂商自测、自定义对比配置、无第三方复现。**

流传的中文介绍还有三处与 README 对不上：

| 宣传说法 | 实际 |
|---|---|
| "DeepSWE 上多过 **10 个任务**" | README 是 "10 more of **60 binary task verifiers**" —— 多过 10 个**校验点** |
| "压缩后 2.6 轮 vs Codex 5.4 轮" | 5.4 是 README 自称 **estimated**；方法论文档里**找不到**该数字的测量出处 |
| "交互次数 **-70%**" | README 里没有这个数（有的是 Balanced −35.8% turns、matched-High 下 Direct −84.0% rounds） |

**可确认的**只有：Direct −77.5% tokens；Balanced 成功率 80.0% vs 63.3%（+16.7pp）。

### 借走的想法

"确定性步骤不该占模型往返"。落到本仓 → 见下方【已核实：不是缺口】。

---

## ② MFS — 不接代码，借一个能力

| | |
|---|---|
| 仓库 | `zilliztech/mfs` —— **Zilliz 官方**（Milvus 背后那家），不是个人项目 |
| License | Apache-2.0；130★ / 16 fork；199 commits |
| 活跃度 | 创建 2026-04-20，最近推送 2026-07-31；最新 release v0.4.6，**仍 pre-1.0** |
| 语言 | 多语言：`cli/` 与 `server-rs/` 是 Rust，`server/python/` 是 Python，`sdks/` 有 TS |
| 形态 | **有状态服务 + 瘦客户端**（server + CLI/SDK + 两个 Agent skills） |

三个里最扎实的一个。两处常见误传要更正：

* **不是"纯 Rust 项目"** —— GitHub 判定主语言是 Python，`mfs-server` 需 Python ≥3.10。
* **本地模式不需要自建 Milvus 集群** —— Milvus **Lite**（`~/.mfs/` 下的本地文件）
  \+ SQLite 元数据 + 本地 ONNX 嵌入（BGE-M3 int8，约 600 MB），官方原文
  "no API key, no GPU, no cloud account"。只有分布式生产档才要 Docker/K8s + Zilliz Cloud。

`docs/connectors/` 下确有 **19 个** connector 文档（bigquery / discord / feishu / file /
gdrive / github / gmail / hubspot / jira / linear / mongo / mysql / notion / postgres /
s3 / slack / snowflake / web / zendesk），不是空列表。但**未实测**任何 connector 的
实际可用性 —— 文档齐全 ≠ 生产可用。

### 不接的理由

本仓已有 `RAGMemory` 作为统一知识入口，多源收敛到同一条 `ingest_knowledge` 流水线 ——
与 MFS "新 connector 不必重新发明向量库" 是**同一个设计**。接 MFS 等于在已有检索栈
之外**再立一套**，而它还 pre-1.0。

### 采纳的能力：`mfs cat --locator` ——「从候选回到证据」

这一条本仓真缺，而且卡在自己定的规矩上，见下。

---

## ③ dsh-routing-suite — 不接，两处要警惕

| | |
|---|---|
| 仓库 | `yjh051108/dsh-routing-suite`，MIT，JavaScript |
| 数据 | **6,933★ / 140 fork**，但只有 **46 commits**、352 KB、创建于 2026-08-14 |
| 上游 | `@deepseek-ai/dsh` = **DeepSeek Harness**，官方开源，但仍是 **rc 预览**（0.1.1-rc.2），明确会有 breaking changes |
| 形态 | 第三方**插件/预设套件**，寄生在 DSH 之上 |

### 警惕点一：star 数据异常

创建 2 周、46 次提交、352 KB 的个人仓库拿到 6,933★，star:fork ≈ **50:1**
（健康项目通常 5–20:1）。**不构成刷星的证据，但这个数不能当质量或采用度的依据。**
内容以 preset 配置、文档和安装脚本为主，实际代码量很小。

### 警惕点二：一处技术表述被上游官方文档否定

上游 `docs/agent-lifecycle.md` 确实定义了这套词汇，但：

* ✅ `agent/pre-step` **属实** —— waterfall 钩子，可在 provider 请求发出前改写消息，
  所以"不额外增加 API 调用次数"**成立**。
* ⚠️ `agent/inbox/claimed` **表述不准确** —— 官方定义是 driver **认领消息之后**发出的
  **通知性事件**（`{ message, turn } per message`），**不是拦截器**。宣传所谓
  "在装配阶段拦截首条用户消息"与官方文档冲突。

### 其余

实验数据（P1–P23）全部作者自测自评，session 导出仅以 hash 引用未公开，分类标准自定；
实验主要跑在 **Claude 模型**上 —— 一个 DeepSeek harness 的路由套件用 Claude 验证，
代表性存疑。64 个 open issue 未处理。**实验性质，不建议生产依赖。**

### 不接的理由

钩子是 DSH 专有的，本仓是 Python 自建运行时，不通用。而 `agent/pre-step` 那个
**原则**（引导词同请求内拼入、不多花一次 API）本仓的 `multi_llm_router` 本来就是
这么做的，零增量。

---

## ④ MHS（Model Hardware Standard）— 想接也接不了：现在没有规范可实现

| | |
|---|---|
| 出品 | Anthropic，2026-08-27 发布研究预览；与 HHMI Janelia Research Campus 合作起步 |
| 是什么 | 让 AI agent 安全操作**物理设备**的共享规范 —— 定位是 MCP 的硬件侧对应物 |
| 标准化什么 | 设备如何向 AI 描述自己的**能力、状态、命令、物理特性、强制操作限值** |
| 怎么接入 | 据称 agent 经 **MCP**、命令行、或代码文件与 API 触达 |
| 启动伙伴 | AWS、Tecan、Universal Robots、Hugging Face LeRobot、QIAGEN、Raspberry Pi |
| 现状 | **限量研究预览**，`modelhardwarestandard.com` 走 waitlist；官方称"将来"开源 |

### 不接的理由：不是不想，是**没有东西可实现**

据搜索结果转述，当前 MHS **没有公开可下载的规范**，官方也**没有给出** SDK、schema、
源码仓库、license、一致性测试套件、版本号、治理模型 —— 一个都没有。

这跟 ①②③ 的"不接"是**完全不同性质**的判断：

* Tura 是**能看到代码但不该接**（AGPL、整体替换运行时）；
* MFS 是**能看到代码但没必要接**（本仓已有等价设计）；
* dsh 是**能看到代码但不通用**（DSH 专有钩子）；
* **MHS 是根本看不到代码。**

所以现在若要"接上 MHS"，唯一做法是照新闻稿把消息格式**编出来**。那不是实现协议，
是造一个同名的赝品 —— 等真规范开源，它一行都对不上。**不做。**

### 也不放占位模块

一个自然的折中是"先建个 `core/mhs_protocol.py` 骨架占位，等规范出来再填"。**不做，
本仓的历史就是理由**：删甲组 6 个审计产物模块、删乙组 5 个纯声明模块、删乙组 4 个
观测报告模块、删批次二 7 个声明式注册表模块 —— 一路删的正是这种"先声明、以后再实现"
的空架子。现在加一个，就是给下一轮清理预备的对象。

### 适配性：另一个独立问题，别混为一谈

MHS 打的是实验室与制造设备（显微镜、移液工作站、机械臂）。本仓驱动的是安卓手机、
WearOS 手表、桌面自动化 —— 表面上不是一回事。

但**不要把这条说死**：启动伙伴里有 Raspberry Pi 与 Hugging Face LeRobot，说明适用面
不限于实验室仪器。所以正确表述是"**规范开源后需要单独判一次适配性**"，而不是
"肯定用不上"。新协议出来不等于本仓就该接，这是两个独立判断。

### 一个真的有用的观察

据转述，MHS 的接入路径之一**就是 MCP**。如果属实，那么本仓 2026-08-29 刚做完的
MCP 双栈客户端（`core/mcp_protocol.py` + `core/mcp_loader.py` + `mcp_bridge/bridge.py`）
就是 MHS 将来天然的挂载点 —— 不需要另起一套传输。这条**降低了等待的成本**：
等规范开源再动手，不会因为"早没铺路"而多付代价。

### 宣传数字：同样是厂商自己发布，无第三方复现

流传的成绩包括：QuEra 量子计算机上 70 万美元激光的重新校准，700 次试验 99.3% 成功；
Genentech 无人干预跑完蛋白检测；华盛顿大学一周内接通 6 台仪器；集成时间"从数月降到
数小时甚至数分钟"。

按本文档 ① 那节立下的标准：**这些都是出品方自己发布的，没有独立复现，且本环境连
一手页面都打不开**。记录下来是为了将来比对，不是当作已确认的事实。

### 什么时候回来看

三件事任一发生就重新评估：

1. Anthropic 开源规范（有 schema/SDK/license 可拉）；
2. 拿到研究预览名额，能直接看到规范；
3. 明确决定"按公开描述先搭雏形" —— 那样做的话，**必须在代码里写死"这是按公开报道
   推测的形状，不是规范实现"**，并且接受它大概率要重写。

---

## 落到本仓：一处更正，一处采纳

### 【已核实：不是缺口】确定性尾巴本来就能一轮做完

看到 `engineer__` 是 6 阶段状态机（DIAGNOSE → GATHER_CONTEXT → PLAN_PATCH → APPLY →
VALIDATE → RECORD_OUTCOME）时，第一反应是"这不就是 Tura 宏命令要打的靶子"。

**实跑之后这个判断是错的。** `core/agent/react_loop.py` 的循环体是
`for tc in tool_calls` —— 一轮里模型发几个工具就顺序派发几个。用生产的
`run_react_tool_loop` 驱动验证：`apply` / `validate` / `record` 三个 tool_call 放进
同一轮，顺序执行、阶段门逐个校验、状态机走完三阶段并写入知识库，`llm_call` 只被调用
一次。**能力一直都在。**

真实残留只是**没人告诉模型**：三个工具的描述读起来像每步各占一轮。所以这次只改描述，
**不加宏命令工具** —— 加了就是第四种做同一件事的方式，与本仓一直在删的冗余同形。

描述里同时写死一条边界：`engineer__validate` **不替谁跑验证**，它只登记已经拿到的
结果。"可以合并"绝不能被读成"可以提前断言"。

### 【采纳】知识可回读：截断必须留下把手

`RAGMemory.format_rag_context` 此前是 `chunk.content[:500]`：

* 没有任何标记 —— 模型察觉不到自己看的是残篇；
* `chunk_id` 没有渲染出来 —— 就算有回读工具也没有把手；
* 而且根本没有回读工具 —— 剩下的内容在存储里好好的，模型够不着。

它在**三条生产路径**上：`galaxy_gateway/orchestrator/galaxy_orchestrator.py:892`、
`core/scheduler.py:559`、`core/routes/hybrid.py:111`。

**为什么这条不一致要紧。** 本仓会话侧的保证是**压缩可逆**：归档后可以用
`context__query_memory` 按段号把原文查回来。知识侧却是不可逆的截断。同一个系统里，
两条链对"截断"给了相反的承诺。而 `core/semantic_anchoring.py` 定的规矩是——会改变
控制流的读取不能从检索到的散文里反解结构；可当模型确实需要这条知识的全文时，此前它
唯一能做的是换个说法再检索一次，既不保证命中同一条，也读不到这一条的其余部分。

**修法**（三件事一起做）：

1. `format_rag_context` 标出被截、给出剩余字符数、渲染 `chunk_id`、写明怎么取回；
   没有 id 的来源**明说取不回来**，不让模型以为自己看到了全部。
2. `RAGMemory.read_knowledge(chunk_id, offset, limit)` —— 按 id 取回原文并分页
   （`next_offset` 续读）。查询顺序与 `query_knowledge` 一致：Node_105 →
   本地经验日志（`ingest_knowledge` 无论主后端成没成功都会同步写一份）。
   取不到时**明说取不到**，不返回空串冒充"这条是空的"。
3. 工具 `knowledge__read` 登记进工具表、`knowledge__` 进 `_INLINE_ONLY_PREFIXES`
   （不登记的前缀一经委派即死 —— academic / engineer / resource / ask_human 都栽过）。

这与 `context__query_memory` 是**同一个保证的另一条轴**：候选可以回到证据。

---

## 下次遇到同类宣传，先问这几个问题

1. **数字是谁测的？** 厂商自己的 benchmark 仓也算数据，但要看它有没有声明利益冲突、
   有没有第三方复现、样本多大。Tura 这条自己写得很坦白，反而是转述的人略过了。
2. **转述对得上原文吗？** 三处失真全出在中文介绍，README 原文并没有那么说。
3. **它是库还是运行时？** 运行时意味着整体替换，成本完全不同。
4. **License 能用吗？** AGPL 是硬约束，这一条要最先问。
5. **我这边真的缺吗？** 本次两条候选里有一条（宏命令）跑一遍就发现能力早就有了。
   **先验证自己缺不缺，再谈接不接。**
6. **有没有可实现的东西？**（MHS 加的这一条）规范、schema、SDK、license —— 一个都
   拿不到时，"接入"只能靠编。**出品方是谁都不改变这一点**：MHS 是 Anthropic 自己的
   标准，照样不能凭新闻稿实现。名气不能替代规范。
