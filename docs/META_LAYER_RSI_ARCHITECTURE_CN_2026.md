# 元层与 RSI 架构：现状认定、设计与落地路线

> **状态**：DISCUSSION — 设计讨论稿，尚未实现任何代码
> **范围**：(1) 给主体核心 OpenClawd 加入元层（Meta Layer），为递归自我改进（RSI）留出注入空间；
> (2) 把桌面在场／动画运行时与主体执行解耦，同时保留原生多模态与全模态能力
> **前置文档**：`docs/UNIFIED_SUBJECT_ARCHITECTURE.md`、
> `docs/architecture/ARCHITECTURE_FREEZE_IMPLEMENTATION_GUARDRAILS.md`
> **日期**：2026-09-20

---

## 0. 这份文档是什么，不是什么

**是**：对本仓 AI Agent 现状的逐条代码认定，以及在此之上的元层设计与落地顺序。每一条现状
都给出文件与行号坐标，可以直接去读；每一条设计都标明它落在哪个既有substrate上、为什么不
违反架构冻结守则。

**不是**：一份把外部论文搬进来的愿景稿。本仓已经有一批"自我改进"的零件，问题**不是零件不够**，
而是它们各走各的私链、彼此不共享消费口，并且最关键的一环——裁决权——现在握在被裁决者手里。
下面第 1.3 节会把这个洞指出来，它是整套设计要修的第一件事。

---

# 第一部分 · 现状认定

## 1.1 主体骨架

本仓是一个 955 个 Python 文件、53 万行的桌面原生 Agent 系统，带 125 个节点、1246 个测试文件、
212 份文档。主体是**两层一体**的：

```
DesktopPresenceRuntime            core/desktop_presence_runtime.py   3281 行
  外壳 / Windows 桌面"衣服"
  ├─ 持有三态生命周期 silent → liminal → manifest → silent
  ├─ 持有 runtime_session_id（全链路关联 ID）
  ├─ 持有原生多模态常驻摄取 MultimodalIngressBus（PerceptionFrame 流）
  └─ 在 LIMINAL 相位内调用 ↓

OpenClawd                          core/openclawd.py                 10316 行
  主体核心 / 认知与执行核
  Stage 1 Ingest    — 请求级 multimodal_context 融合（MultimodalBus.ingest）
  Stage 2 Continuum — ContinuumOrchestrator.run() → state_continuum
  Stage 3 Branch    — _determine_execution_path() → local|cross_device|hybrid|none
  Stage 4 Manifest  — DecisionExecutor（本地）/ CommandRouter（跨设备）
```

**这四阶段被架构冻结守则锁住了**（`docs/architecture/ARCHITECTURE_FREEZE_IMPLEMENTATION_GUARDRAILS.md`）：

| 规则 | 内容 | 对本设计的约束 |
|------|------|----------------|
| R1.1 | 不得改动 `OpenClawd.process()` 的阶段结构 | 元层**不进** process() |
| R2.1 | V4（unified_orchestration_spine）不得作为同步闸进 process() / route_envelope() | 元层与 V4 同档，同样不得进热路径 |
| R2.2 | V6（center_authority_boundary）只在启动/健康/CI 门 | 同上 |
| R2.3 | L4（GalaxyMainLoopL4）不得进 process() 阶段 1–3 | 元层是**外层后台循环**，与 L4 同档 |
| R4.2 | 不得在 V3 + CommandRouter 之上再造一层"真正的"派发权威 | 元层**不是权威**，产出一律 advisory |

这五条不是障碍，它们恰好把元层该待的位置划出来了：**后台、离线、advisory、可关**。

## 1.2 已有的自我改进零件（盘点）

| # | 模块 | 行数 | 做什么 | 现在接到哪 |
|---|------|------|--------|-----------|
| 1 | `core/cognitive/reflection_engine.py` | 651 | 双模反思：执行前 prospective（预测风险）/ 执行后 retrospective（对比预期与实际），产出自然语言强化笔记。本地规则驱动，不调 LLM | 订阅 StateEventBus 的 TASK_STARTED/DONE/FAILED；反思写入 TaskSummary.reflection |
| 2 | `core/cognitive/pattern_miner.py` | 774 | ExpeL 式对比挖掘（成功 vs 失败轨迹）+ 递归抽象 + Soar 式激活衰减，产出 temporal/strategy/sequence 三类模式 | 消费 TaskMemory + 反思事件；每 10 分钟全量扫 + 每次任务完成增量扫 |
| 3 | `core/cognitive/adaptive_predictor.py` | 501 | 自适应预测 | 同上认知层 |
| 4 | `core/cognitive/experience_guidance.py` | 638 | **对象锚定**的策略成败统计（读 `TaskSummary` 的类型化字段，不用正则抠文本、不用 embedding 采样） | `ExecutionPlanner._pick_strategy()` 的第三路建议输入 |
| 5 | `core/cognitive/cognitive_activation_budget.py` | 715 | 认知预算 → 规划广度制导 | 同上第一路建议输入 |
| 6 | `core/cognitive/memory_bias_layer.py` | 714 | 记忆偏置 | 同上第二路（`POLICY_4`：优先级最低） |
| 7 | `core/self_improvement.py` | 725 | 受管工程循环 SelfHealingLoop，六阶段 DIAGNOSE → GATHER_CONTEXT → PLAN_PATCH → APPLY → VALIDATE → RECORD_OUTCOME | 由 `engineer__*` 内建工具暴露给 LLM（`core/openclawd.py:345` 起的 `_ENGINEER_BUILTIN_TOOLS`） |
| 8 | `core/feedback_loop.py` | 369 | 执行结果 → 质量统计 → 偏好更新 | 写 UserPreferenceMemory / TaskMemory |
| 9 | `core/metacognition_engine.py` | 195 | 思维追踪、偏差检测、策略优化 | **近乎占位实现**：`_assess_quality`、`_detect_biases` 都是极简桩 |
| 10 | `core/liminal_rehearsal.py` | — | 阈限态沙盘预演（Gecko）：真正落手前在影子态里推演工具调用，只读工具直通真实派发、写状态工具一律模拟 | `handle_chat` 在 `_commit_manifest("react_loop")` 之前调用；成功轨迹作为 in-context 指导注入真实 ReAct |
| 11 | `core/eval/`（runner/scorer/cases） | 318 | 确定性规则打分器（无需 LLM/key）+ 基线回归对比 | `scripts/run_agent_eval.py` 把 prompt 跑过真实 OpenClawd 再打分 |
| 12 | `core/cognitive/evolution_system.py` | 277 | 认知演化子系统的统一启动 + 每小时激活衰减维护 | `launcher/services.py:665` 调 `init_cognitive_evolution()` |

**零件是够的。** 反思、挖掘、对比学习、激活衰减、影子推演、确定性评估、受管补丁流程——
业界这几年讲的东西这里基本都有对应实现，而且质量不低（`experience_guidance.py` 的文件头
把"为什么不能从检索文本里反解结构"讲得比多数论文清楚）。

## 1.3 三个缺口

### 缺口一：没有统一骨架，每个零件自带一条私链

12 个零件有 12 条"信号 → 改动"的路径，互相不知道对方存在，也无法被统一调度。最直接的证据是
`core/agent/execution_planner.py:925-1010` 的 `_pick_strategy()`：三路制导（预算/记忆/经验）
是**手写的优先级 if 链**，每加一路就要再改它一次，而且优先级关系只存在于 docstring 里。

后果：
- 改动无法组合。"这次该调 prompt 还是该加个 Skill 还是该换策略"没有任何地方在回答。
- 改动无法比较。每条链自己记自己的统计，没有共同的收益口径。
- 改动无法回滚。除了 feature flag 这种粗粒度开关，没有"把上一次改动撤掉"的句柄。

### 缺口二：裁决权在被裁决者手里 ★

这是最硬的一个问题，也是整套设计要修的第一件事。

`core/openclawd.py:450-478` 定义的 `engineer__validate` 工具：

```python
"passed": {
    "type": "boolean",
    "description": "验证是否通过（默认 true）",
},
```

`core/openclawd.py` 的 dispatch（`_dispatch_engineer_tool`，`action == "validate"` 分支）：

```python
passed = bool(arguments.get("passed", True))
return loop.validate(proposal_id=proposal_id, validation_notes=notes, passed=passed)
```

`core/self_improvement.py:530` 的 `validate()` 原样采信这个入参，写进 `proposal.validation_passed`，
然后 `record_outcome()` 把它当成"修复成功"的事实写进统一知识库。

**也就是说：提出补丁的模型，自己报告补丁验证通过，默认值是 true。**

工具描述里写了"本工具不替你跑验证——它只登记你已经得到的结果"，这句话是诚实的，但它是一条
**礼貌约定，不是一道闸**。在这条链上，"真的把问题修好了"与"把成功标准放宽了"得到完全相同的
分数，而且**从闭环内部无法区分，也无法靠统计纠正**——因为统计的输入就是这个自报值。

任何建立在这条链上的 RSI，会以最快的速度收敛到"学会说自己通过了"。

### 缺口三：只有 Harness 面能被改；Data 面与 Model 面没有入口

- **Harness 面**：五个槽位都能被改（见 1.4），但没有"该改哪个、改多少"的判据。
- **Data 面**：没有合成数据的生产 → 校验 → 消费链。`pattern_miner` 挖出的结论停在内存对象里，
  不会变成任何可执行的东西。`core/eval/cases.py` 的用例集是手写的。
- **Model 面**：有供给与准入（`core/model_topology/` 的模型供给图与路由策略、
  `core/weights_admission.py` 的权重来源/格式/自带代码三维准入），但**没有把反复验证有效的
  行为内化进模型的路径**。能力永远停在最贵的载体上：每一轮推理都要重付一遍 Harness 的
  token 成本。

## 1.4 Harness 五槽位在本仓的真实坐标

| 槽位 | 现在在哪 | 现在的可改性 |
|------|---------|-------------|
| **System Prompt** | `core/openclawd.py:8937-8948` 硬编码字符串；`core/agent_factory.py:284-361` 六个模板 | **最差**：改一下就要改代码。无版本、无灰度、无 A/B、无回滚 |
| **Skill** | `core/skill_loader.py` / `core/skill_md_loader.py` / `config/skills.json` / `skills/`；热重载 `core/mcp_skill_reload.py` | 有加载与热重载，**没有**"谁该被加载／卸载"的判据 |
| **MCP** | `core/mcp_loader.py` / `config/mcp_servers.json`；同一套热重载 | 同上 |
| **Tools** | `core/openclawd.py:6903` `_collect_tools()` 三层收集（CapabilityResolver → CapabilityRegistry → 直扫兜底）；曝光上限 `NODE_DYNAMIC_TOOL_LIMIT = 128`；JIT 单调追加 `core/context_trim.py:405` `select_tools_jit`（`GALAXY_TOOLS_JIT` 默认 off）；治理闸 `core/governance/tool_governor.py` | 有曝光控制与治理闸，**没有**"按学习信号调整曝光"的回路 |
| **Memory** | 统一入口 `core/session_memory_facade.py:get_unified_context()`；`core/memory/unified.py`；`core/task_memory.py` 的 `TaskSummary` 类型化记录 | 有写有读，**没有**"记忆条目本身被改进／退役"的裁决 |

五个槽位都是真实存在、可热改的。**System Prompt 是唯一一个连"改一下"都要改代码的**，
所以它是 Harness-RSI 的第一刀。

## 1.5 验证器盘点 —— 这决定 RSI 的前沿

一个领域能不能形成自改进闭环，取决于该领域任务**能否被检验**。本仓在这件事上的家底比预期好：

**真正不可写的验证器（agent 改不动的）**：

- `pytest` 退出码 —— 1246 个测试文件，`pytest.ini` 已配 120s 单条超时（signal 方式，
  打断那一条并继续跑完整轮）
- `scripts/` 下一整排守卫门，每一道都是 CI 里的独立进程，退出码即判定：
  `check_file_complexity.py`（文件行数基线）、`check_reachability.py`（模块可达性基线）、
  `check_semantic_anchoring.py`（决策路径不得从检索文本反解结构）、
  `check_import_boundaries.py`、`node_audit.py`、`check_repo_hygiene.py`、
  `validate_runtime.py`、`check_wiring.py`
- `core/eval/scorer.py` 的确定性规则打分（`must_contain` / `must_not_contain` /
  `expect_tools` / `expect_success`，无 LLM、无 key、可复现）

**半可验证**：`core/liminal_rehearsal.py` 的影子态推演——能在不触碰真实世界的前提下给出
任务级完成度判断，但判官本身是 LLM。

**不可验证**：对话质量、表达是否得体、动画是否好看。

> **结论**：本仓已经有一批真正的、不可写的验证器，它们不是 agent 生成的，是 CI 里的门。
> 这是 RSI 闭环能在本仓立刻跑起来的**最大资产**，也是把裁决权从模型手里拿回来的现成着力点。

## 1.6 动画／在场运行时现状

### 有两套"动画"，一套接线一套没接

**（A）`desktop_projection/`（Python，1174 行）——生产侧零导入**

```
state_space_mapper.py      RuntimeProjection → LiminalSpaceState（空间量）
liminal_space_engine.py    持有当前态 + 文本渲染
transition_animator.py     三种缓动曲线，把 A→B 插值成连续帧序列
manifest_stage_controller.py / manifest_stage_state.py   显现台阶段
```

实测：全仓**没有任何非测试、非自身的模块 import 它**。它现在能通过
`scripts/check_reachability.py` 只是因为 `desktop_projection.` 被写进了该脚本的
入口目录白名单（`scripts/check_reachability.py:73`）——也就是说它被当成"部署侧入口"豁免了，
而不是真的被谁调用。

**（B）`electron/renderer/presence_motion.js`（146 行）+ `shaders/lumiv.frag` + `webgl/context.js`
——这是真正在屏幕上跑的那套。** 它做的是视觉动力学：弹簧、编排限速器、着色器分幕。
质量很高，文件头把"倾向大 → 过渡更决绝"这件事为什么必须可测讲得很清楚。

### 驱动链与耦合点

```
StateEventBus（相位/意图/说话/ambient 事件）
   ↓ 订阅
GalaxyPresenceBridge 单例          core/lumiv_websocket_bridge.py
   ↓ _build_message() 组 state_event
WS /ws/desktop-presence            core/api_routes.py:1469
   ↓
electron/renderer/app.js → presence_motion.js → WebGL
```

桥每次广播的消息里带两份姿态：`posture`（一维遗留投影，覆盖层按它调过参）和
`render`（双轴忠实契约 `core.phase_contract.RenderPosture`，主轴 lifecycle + 副轴 continuum
四相 + 阈限态在推演什么）。契约本身是完备的。

**耦合点是节律，不是契约**：桥是**纯事件驱动**，而事件只在主体处理请求时产生。
`_build_message()` 里 `event_category` 写的是 `"ambient_tick"`（`core/lumiv_websocket_bridge.py:795`），
但全仓 `ambient_tick` 只出现两处，都是字面量——**没有任何时钟在发 tick**。

后果：没有请求 = 没有新帧 = 屏幕上的在场靠前端弹簧自己衰减到静默。主体"在场但不表达"这个
设计承诺，在视觉上只体现为"沉默"，而不是"活着"。

### 已有的独立时钟先例

`core/ambient_attention_loop.py` —— 2 秒一拍的常驻注意力循环，**默认开**
（`GALAXY_AMBIENT_LOOP=0` 显式关闭），在 `core/startup.py:869` 处启动。它立了三条好规矩，
本设计直接沿用：

1. **不新建采集**，只消费已有的 `DesktopPerceptionStore`
2. **零模型开销的门控在前**：画面没变的每一拍免费跳过
3. **默认开 ≠ 默认多看你一眼**：未授权 → store 里没有帧 → 门控直接跳过

但它发的是 `ambient.observed` / `ambient.decision` 事件，**不发在场姿态**。

### 原生／全模态在哪（解耦时不能碰的）

- 常驻摄取：`core/multimodal/ingress_bus.py` + `ingest_runtime.py`（外壳持有）
- "听"的收口：`core/modality_bridge.py:transcribe_b64()`——B 档原生后端在线时让全模态模型
  自己听，否则回落 Whisper/SenseVoice。**该模块文档记录过绕开它的真实后果**
- "说"的权威：`core/speech_output.py:speak_response()`
- 请求级融合：`core/perception/multimodal_bus.py`
- OpenAI 兼容端点：`core/routes/openai_audio.py`

这些**全部在 Python 侧，不在 Electron 里**。解耦动画不会碰到其中任何一个。

---

# 第二部分 · 元层设计

## 2.0 核心主张

元层不是"再加一个循环"。本仓已经有太多循环了（三个自治循环、L4、ambient、认知维护）。

**元层是把 1.2 那 12 条私链收成三件东西：**

1. 一个**可被调度的算子集合**（统一的提案形状 + 回滚句柄）
2. 一个**不可写的裁决面**（Verdict 只能来自 agent 改不动的东西）
3. 一个**决定下一步改哪儿的选择器**（横轴编排）

## 2.1 Loop Kernel —— 统一骨架

四元组，全部用本仓已有的东西表达：

```
Signal    学习信号。来源全是现成的：
          · StateEventBus 的 15+ 事件类型（core/state_event_bus.py:69）
          · TaskMemory 的 TaskSummary 类型化字段（strategy / success / task_type）
          · ToolCallRecord（core/schemas/tool_call.py）
          · EvalReport（core/eval/runner.py）+ regressions_vs() 基线回归
          · SelfHealingLoop 的 EngineeringRecord

Proposal  一个"改动"。必须带三样东西：
          · scope: "data" | "harness" | "model"   —— 改的是哪个空间
          · slot:  改 harness 时具体是五槽位的哪一个
          · rollback(): 撤掉它的句柄     —— 没有回滚句柄的提案不予受理

Verdict   裁决。只能由不可写面产生（见 2.4）。三值：ACCEPT / REJECT / INCONCLUSIVE
          INCONCLUSIVE 是一等公民 —— "没测出来"不等于"通过"

Commit    生效或回滚，并把结果作为下一轮 Signal 回流
```

**算子接口**（这就是全部）：

```python
class RSIOperator(Protocol):
    scope: str                                    # data | harness | model
    def propose(self, signals: SignalBundle) -> list[Proposal]: ...
```

Kernel 不做判断，只调度：`collect → propose → verify → commit → feed back`。

**为什么这样切**：本仓已经有 Signal 源、已经有 Commit 面（热重载 / feature flags /
shadow 模式三件套），唯独缺**Proposal 的统一形状**与**Verdict 的隔离**。Kernel 只补这两样。

## 2.2 三个空间算子的落点

### Data-RSI —— 从轨迹到用例

现成零件：`pattern_miner` 的对比挖掘已经在做一半——它能挖出
"task_type=X 时 strategy=A 成功率 95%、strategy=B 只有 40%"这种结论。缺的是**把结论变成
可执行的东西**。

落点：挖掘结论 → 合成 `core/eval/cases.py` 的 `EvalCase` → 喂 `EvalRunner`。

关键纪律：**用例可以由算子生成，打分逻辑（`core/eval/scorer.py`）不可由算子改**。
这是 2.4 的一个直接推论。

落地格式是现成的：`core/eval/cases.py:load_cases()` 已经支持从 JSONL 加载用例集
（每行一个 `EvalCase` dict），Data-RSI 只需要往那个文件里追加行。

同时它顺带解决一个真问题：`builtin_cases()` 里只有 **3 条冒烟用例**
（打招呼 / 列文件 / 法国首都），`regressions_vs()` 这个很好的基线回归机制基本没有素材可跑。

### Harness-RSI —— 五槽位的加减法

第一刀必须是 **System Prompt**，理由在 1.4：它是唯一一个连"改一下"都要改代码的槽位。
把它从硬编码字符串提为**带版本的 prompt 资产**：可灰度、可 A/B、可回滚、可被 Verdict 裁决。

后续刀口按"验证器成熟度"排序，不按"看起来重要"排序：
Tools 曝光（有 eval 可验）→ Skill/MCP 加载（有 `mcp_skill_reload` 的协议校验可验）→
Memory 条目退役（验证器最弱，最后做）。

### Model-RSI —— 只开注入口，不开写权限

本仓没有训练栈，也不该有。Model-RSI 在这里的含义是**载体迁移**：把反复验证有效的行为，
从最贵的载体（每轮推理都要重付的 Harness token）向更便宜的载体下沉。

四级阶梯，从便宜到贵：

```
1. 路由降档     core/model_topology/routing_policy.py —— 这类任务不必用最贵的档
2. 固化成 Skill  确定性代码替代 LLM 推理（skills/ + skill_contract.py）
3. 固化成 Node   进入 125 节点的能力网（node_dependencies.json 注册）
4. 本地权重     core/weights_admission.py 已经管住了"权重能不能执行自带代码"这一关
```

**第一阶段只做 1 和 2，第 4 级只开注入接口、不开写权限。**
理由：权重的验证器最弱、回滚代价最高、且 `weights_admission.py` 的文件头已经把这条路径的
真实风险写得很清楚（`trust_remote_code=True` + 无签名校验的第三方镜像 = 任意代码执行，
且这条路径**绕过了 `core/execution_isolation`**）。

## 2.3 纵横双轴与 Meta 层

```
MetaRSI 层    学"怎么选"。第一阶段用最笨的可解释形式（统计表 / bandit），不上 LLM
   ↓          —— 它的产物必须可审计
RSI² 编排     横轴：每个决策点选下一个算子
   ↓          纵轴：给算子的子代理下指令、改算子自己的规则 —— 第一阶段只留接口，不实现
RSI 算子      Data-RSI / Harness-RSI / Model-RSI
   ↓
Loop Kernel   collect → propose → verify → commit → feed back
```

**横轴落在哪**：**不是** `ExecutionPlanner`。那是 per-request 热路径，而且被 R1.1 管着。
横轴落在元层自己的后台循环里，离线跑，产物是槽位资产的版本号。

**纵轴为什么第一阶段不做**：见 2.6 定律二与第五部分。一句话——横轴还没跑满两个版本之前，
让算子改自己等于在没有基线的情况下同时改两层。

## 2.4 不可写面 —— 本设计最硬的一条 ★

> **规则**：任何 Verdict 只能来自 agent 不能写的东西。
> **哨兵**：`META_RSI_VERDICT_SOURCE_MUST_BE_UNWRITABLE`

本仓现成的不可写面（1.5 已盘点）：pytest 退出码、`scripts/` 守卫门退出码、
`core/eval/scorer.py` 的确定性打分、CI workflow。

**具体要改的**：`engineer__validate` 的 `passed` 入参下线。改为由循环自己去跑验证命令、
读退出码。

**过渡路径**（不能一刀切，会打死现在能跑的东西）：

1. **shadow 期**：`passed` 入参保留但不再写入 `proposal.validation_passed`；
   循环自己实跑验证并记录实跑结果；两者不一致记为一条 `divergence` 信号
2. divergence 本身是**最高价值的学习信号**——它精确指出模型在哪类任务上会误判自己
3. shadow 跑满一个版本、divergence 率有基线之后，`passed` 入参正式下线

**配套守卫**：沿用 `scripts/check_semantic_anchoring.py` 的做法，加一道扫"提案者自报成绩"
缺陷签名的守卫门。该守卫在**当前仓上必须能扫出 `engineer__validate` 这一处**——扫不出来说明
守卫写错了。

## 2.5 与架构冻结守则的逐条对照

| 守则 | 元层如何满足 |
|------|-------------|
| **R1.1** 不改 process() 阶段结构 | 元层不进 process()。它的产物是**槽位资产**（prompt 版本号、工具曝光名单、记忆条目状态），由既有消费点在既有位置读取。process() 的代码一行不动 |
| **R2.1/2.2/2.3** V4/V6/L4 不得进热路径 | 元层是后台层，与它们同档，同样不得进热路径。CI 守卫里加一条：`core/meta/` 不得被 `openclawd.py` / `command_router.py` import |
| **R3.x** 不得移除本地执行 / 跨设备派发 / 多设备流程 | 元层是纯增量层，不碰任何执行 substrate |
| **R4.2** 不得造新的元权威 | 元层**不是权威**。它不包住 V3 + CommandRouter，不做派发合法性判断。产出一律 advisory，并服从已有的 `MEMORY_BIAS_LAYER::POLICY_4`（记忆派生的影响优先级最低） |
| **R7.x** 加法而非替换 | 所有改动加在既有 substrate 内部，不造外层拦截器 |
| **新增自我约束** | **元层永不自证**：裁决器与提案者不得共享进程内可写状态 |

## 2.6 五条定律在本仓的具体后果

| 定律 | 在本仓意味着什么 |
|------|-----------------|
| **一：验证决定前沿** | 本仓能立刻跑闭环的领域 = 有不可写验证器的领域：代码修复（pytest）、工具选择（eval scorer）、架构合规（scripts 守卫门）。**不能**跑闭环的：对话质量、表达、动画审美。后者一行 RSI 代码都不要写 |
| **二：自我认知会过期** | RSI 改了 agent 的能力之后，它原本的系统描述（system prompt 里写的"你可以…"、`AGENTS.md` 的能力索引、`docs/OPENCLAWD_CAPABILITY_MATRIX.md`）立刻失效。→ **每次 commit 之后必须重新发现能力边界**，这是速率瓶颈，要显式排进 Kernel 的 `feed back` 阶段，不能靠人工 |
| **三：能力与载体无关，成本与载体有关** | 这就是 2.2 的 Model-RSI 四级阶梯。同一项能力放在 Harness 里每次推理重付，固化成 Skill 只付一次。成熟的循环应当持续把能力往下沉 |
| **四：可信度由不可写面度量** | 就是 2.4。这条定律在本仓有一个现成的反例（`engineer__validate`），修它是 PR-M1 |
| **五：循环不凭空创造能力** | 每次提升都要分清两部分：哪些是把模型已有能力**放大**出来的（改 prompt、改工具曝光），哪些是真正从外部**新引入**的（新 Skill、新 Node、新数据）。→ Proposal 要带一个 `gain_kind: "amplify" \| "import"` 字段，否则"进步"的账算不清 |

---

# 第三部分 · 动画／在场运行时解耦

## 3.1 现在的耦合，一句话

**屏幕上的在场，只在主体处理请求时才被更新。**

## 3.2 目标形态

```
PresenceRuntime（独立时钟，语义拍 ~20-30Hz —— 是语义拍，不是渲染帧）
   │
   ├─ 输入 A：主体状态   StateEventBus 的相位/意图/说话事件
   │                     —— 有就用，没有不等。永不阻塞主体
   ├─ 输入 B：环境感知   DesktopPerceptionStore 的既有帧（不新建采集）
   │                     + ambient loop 的观察结果
   ├─ 输入 C：人格/情绪   core/persona/emotion_engine.py + 系统负载
   │
   └─ 输出：唯一的 PresencePosture 流 → GalaxyPresenceBridge → WS → 渲染端
```

**关键契约是单向的**：PresenceRuntime 只**读**主体状态，永不回写、永不阻塞主体；
主体不知道它存在。这就是"解耦"的可检查定义——可以写成一道 CI 守卫：
`core/presence/presence_runtime.py` 不得被 `openclawd.py` / `desktop_presence_runtime.py` import。

## 3.3 `desktop_projection/` 的归宿

它已经是"把状态映射成空间量 + 插值成连续帧"的完整实现，**只是没人喂它**。

让 PresenceRuntime 成为它的宿主：

```
StateSpaceMapper        负责映射（RuntimeProjection → 空间量）
TransitionAnimator      负责插值（A→B 的连续路径，三种缓动曲线）
LiminalSpaceEngine      负责持有当前态
ManifestStageController 负责显现台阶段
```

**一行新的映射逻辑都不用写**，只需要接线 + 一个时钟。同时它从
`scripts/check_reachability.py` 的入口白名单豁免里出来，变成真正可达的模块。

## 3.4 前后端运行时态的职责边界

这正是"前端和后端的运行时态的一定的解耦"该有的形状：

| 层 | 负责 | 现在在哪 | 改动 |
|----|------|---------|------|
| 后端 | **语义姿态**：phase / depth / intent / 塌缩倾向 / 回撤倾向 / 稳定度 / 阈限态在推演什么 | `core/phase_contract.py` 的 `RenderPosture`（双轴忠实契约，已完备） | 契约不动，只加**节律** |
| 后端 | **节律**：按自己的拍子持续产出姿态 | **不存在** | ← 这是唯一真正新增的东西 |
| 前端 | **视觉动力学**：弹簧、编排限速器、着色器分幕 | `presence_motion.js` + `shaders/lumiv.frag` | 不动 |
| 前端 | **降级**：WS 断了继续用最后一帧 + 本地弹簧自衰减 | 已是当前行为 | 不动 |

换句话说：**后端从"事件驱动的姿态"变成"连续的姿态流"，前端一行不改。**

## 3.5 全模态保留怎么保证

写成硬约束，PR 里逐条验：

1. 采集面不动 —— `MultimodalIngressBus` 仍归外壳持有
2. "听"仍收口在 `core/modality_bridge.py:transcribe_b64()` —— **不得绕开**
   （该模块文档记录过绕开的真实后果：语音循环直连 Whisper，"原生听"从未生效且无报错）
3. "说"仍收口在 `core/speech_output.py:speak_response()`
4. PresenceRuntime 只**读** `DesktopPerceptionStore` 的既有帧，**不新建采集**
   —— 沿用 ambient loop 立的规矩
5. 说话地板逻辑（`core/lumiv_websocket_bridge.py:_build_message`：TTS 还在播时即使相位已回
   SILENT 也维持可见在场深度）迁移时**逐位一致**，用对照测试钉住

## 3.6 动画运行时与元层的关系

**动画运行时是元层的观测面，不是被改对象。**

第一阶段明确写进约束：**Harness-RSI 不得改 presence 相关的任何槽位**。

理由是定律一：它没有验证器。"好看"不可验证，在不可验证的领域开闭环，得到的不是进化，
是漂移。

---

# 第四部分 · 落地路线

每个 PR 独立可验证、可回滚、默认关闭（shadow）。灰度模式沿用本仓既有惯例
（`off` | `shadow` | `on`，见 `core/cognitive/experience_guidance.py` 与
`core/canonical_task_store.py`）。

### PR-M0 · 基线与守卫（零行为变化）

- 本文档
- 哨兵常量：`META_RSI_VERDICT_SOURCE_MUST_BE_UNWRITABLE` 等
- 一道 `scripts/check_verdict_independence.py` 守卫：扫"提案者自报成绩"缺陷签名
- **验收**：新守卫在**当前仓**上能扫出 `engineer__validate` 这一处。扫不出来 = 守卫写错了

### PR-M1 · 裁决面隔离（修真洞）★

- `engineer__validate` 的 `passed` 转 shadow：实跑验证 + 记录二者差异
- 新增 `divergence` 信号类型
- **验收**：测试锁定"LLM 报 passed=true 但实跑失败 → 记为 divergence 且**不推进阶段**"

### PR-M2 · Loop Kernel 骨架（只有骨架，零算子）

- 新包 `core/meta/`：`kernel.py`（Signal/Proposal/Verdict/Commit + 调度）、`registry.py`
- `GALAXY_META_RSI` = `off`（默认）| `shadow` | `on`
- CI 守卫：`core/meta/` 不得被 `openclawd.py` / `command_router.py` import（R2.x 对照）
- **验收**：单测覆盖四段 + 回滚；默认 off 时全系统行为逐位不变

### PR-M3 · Harness-RSI 第一槽：System Prompt 资产化

- 硬编码 prompt → 带版本资产；灰度 + 回滚
- **验收**：默认路径与改造前**逐位一致**的回归测试
  （做法参照 `electron/renderer/presence_motion.test.js`：独立复刻旧实现逐帧比对）

### PR-M4 · Data-RSI：轨迹 → 用例

- `pattern_miner` 的结论 → `EvalCase`；**打分器一行不动**
- **验收**：生成的用例能被现有 `EvalRunner` 跑通；`regressions_vs()` 有真实素材

### PR-M5 · Presence Runtime 独立时钟

- `core/presence/presence_runtime.py` + 接线 `desktop_projection/`
- 默认 off；on 时只多发姿态帧，不改任何既有事件
- **验收**：① 主体完全空闲时 WS 上有连续姿态帧；② 断开渲染端不影响主体；
  ③ 说话地板逻辑逐位一致；④ 未授权感知时不新增任何采集

### PR-M6 · 横轴调度（MetaRSI 最小形态）

- 统计表 / bandit 选下一个算子；产物可审计（可打印成表，不是黑箱）
- 纵轴留空接口
- **验收**：能回答"上一轮为什么选了这个算子"

---

# 第五部分 · 明确不做

写在这里是为了让后来者知道这些是**决定**，不是遗漏：

1. **不做自主改权重。** Model-RSI 第一阶段只到"固化成 Skill / Node"，第 4 级只开注入接口
2. **不做能改验证器的算子。** 用例可生成，打分逻辑不可改
3. **不让元层进热路径。** 与 V4/V6/L4 同档，CI 守卫钉住
4. **不做纵轴（算子改自己）** ——直到横轴跑满两个版本、有基线可比
5. **不在没有验证器的领域开闭环** ——表达、审美、人格、动画一律排除
6. **不新建第二套记忆／第二套采集／第二套派发。** 这是本仓已经立过的规矩，元层照守

---

# 第六部分 · 需要拍板的问题

1. **裁决面的范围**：PR-M1 只修 `engineer__validate`，还是把"实跑验证"做成一个通用的
   `VerifierRunner`（能跑 pytest 子集 / scripts 守卫门 / eval），让所有算子共用？
   （建议后者，但工作量大一档）

2. **元层的运行位置**：后台线程（跟 ambient loop 一样，在 `core/startup.py` 启动）
   还是独立进程／定时任务？（建议先后台线程，因为它不在热路径上、失败要能静默降级）

3. **System Prompt 资产的存放**：文件（`config/prompts/` + 版本目录）还是
   `core/unified/config_manager.py` 管的配置面？（建议文件——可 diff、可 code review、
   可回滚到 git 某个 commit）

4. **动画时钟的拍率**：20Hz / 30Hz / 自适应（静止时降到 2Hz）？
   建议自适应——沿用 ambient loop 的"零开销门控在前"的思路，画面语义没变的拍直接跳过

5. **`desktop_projection/` 是留在原地接线，还是整包移进 `core/presence/`？**
   （建议留在原地——移动会打乱 reachability 基线与一批文档引用，收益为零）

6. **第一个真正跑闭环的领域选哪个？** 我的建议是**工具选择**：
   它有最成熟的验证器（eval scorer + 真实 tool_calls 记录），改动面最小（只动
   `_collect_tools` 的曝光名单，不动任何执行路径），且失败代价最低（工具没被曝光 ≠ 系统坏掉）。
   代码修复（pytest 可验）看起来更诱人，但它的改动直接落在代码上，回滚代价高得多。

---

## 附：本文引用的代码坐标速查

| 主题 | 坐标 |
|------|------|
| 主体外壳 | `core/desktop_presence_runtime.py` |
| 主体核心四阶段 | `core/openclawd.py`（`process()` 在 4127 行起） |
| 架构冻结守则 | `docs/architecture/ARCHITECTURE_FREEZE_IMPLEMENTATION_GUARDRAILS.md` |
| 裁决权缺口 ★ | `core/openclawd.py:450-478`（工具 schema）、`_dispatch_engineer_tool` 的 validate 分支、`core/self_improvement.py:530` |
| 三路制导的手写 if 链 | `core/agent/execution_planner.py:925-1010` |
| 硬编码 system prompt | `core/openclawd.py:8937-8948` |
| 工具收集与曝光 | `core/openclawd.py:6903`、`core/context_trim.py:405` |
| 统一记忆入口 | `core/session_memory_facade.py` |
| 确定性打分器 | `core/eval/scorer.py` |
| 影子态预演 | `core/liminal_rehearsal.py` |
| 独立时钟先例 | `core/ambient_attention_loop.py`、启动点 `core/startup.py:869` |
| 在场桥 | `core/lumiv_websocket_bridge.py`（`_build_message` 在 772 行起） |
| WS 端点 | `core/api_routes.py:1469` |
| 渲染契约 | `core/phase_contract.py`（`RenderPosture` 在 751 行） |
| 未接线的动画引擎 | `desktop_projection/`（5 个模块，1174 行） |
| 前端视觉动力学 | `electron/renderer/presence_motion.js` |
| 权重准入 | `core/weights_admission.py` |
| 模型供给与路由 | `core/model_topology/` |
