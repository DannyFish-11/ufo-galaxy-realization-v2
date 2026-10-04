# 渲染契约：给前端的方向说明

> 这份文档的读者是**接手前端的人（或 AI）**。
> 它不描述界面长什么样——那还没定。它描述的是**后端到底在表达什么**，以及
> 前端必须尊重哪些结构，才不会做出一个"看起来能跑、但和系统真实状态对不上"的壳。

**唯一事实源**：`core/phase_contract.py`。
**生成的类型**：`electron/renderer/panel/src/types/phase_contract.gen.ts`（勿手改，改后端后重跑 `scripts/gen_ts_types.py`）。
**线上位置**：`state_event` 的 `payload.render`。

---

## 一、先记住一件事：这套契约不是设计出来的，是**接出来**的

后端早就有一套面向渲染的、媒介无关的参数模型——`core/continuum/types.py` 的
`ExpressionState`，它的类文档原话是：

> *Abstract, non-UI expression parameters describing system presence.
> **Consumers (rendering layers, audio engines, haptics, etc.)** translate these
> values into medium-specific signals. This model carries no widget, page, or view semantics.*

它一直在算，但**到达渲染端的字段数是 0**。所以本契约做的事只是把它送出来。

**推论**：当你想在前端"算一个视觉参数"时，先去 `core/continuum/` 看后端是不是已经算过了。
大概率算过。重新推导一遍的结果一定会和后端漂移。

---

## 二、两根轴，主次已定

系统里有**两个刻意区分的相位概念**。`TriState` 的类文档明确禁止混淆
（"not a UI state and not the internal continuum posture"）。契约同时携带两者：

| | 字段 | 取值 | 语义 |
|---|---|---|---|
| **主轴** | `lifecycle` | `silent` / `liminal` / `manifest` | 主体生命周期——用户能直接感知的节奏 |
| **副轴** | `continuum_phase` | `formless` / `liminal` / `manifest` / **`receding`** | 内部连续体姿态，多一相返回弧 |

### 整体编排跟**主轴**走

`lifecycle` 是在场桥一路维护的那一根，也是用户能感知的：休息 → 过渡 → 对外表达。
页面的大结构、区域的显隐、节奏的快慢，都应该由它驱动。

### 副轴提供主轴给不出的**纹理**

副轴唯一不可替代的价值在这里：

```
lifecycle = silent 时，副轴可能是 formless，也可能是 receding
    formless  → 静息。什么都没发生过。
    receding  → 刚做完一件事，正在消散。它携带着来处。
```

这两件事在视觉上应该**完全不同**：一个是空转的呼吸，一个是有来处的余辉衰减。
后端的 `ExpressionEngine` 对它们给出的参数就是截然不同的：

| | `formless` | `receding` |
|---|---|---|
| `form_signature` | `none` | `collapsing_field` |
| `spatial_presence` | `absent` | `peripheral` |
| `texture_hint` | `""` | `soft_dissolve` |
| `motion` | `0.0` | `presence_intensity × 0.3` |

用 `is_returning` 这一位就能分开。**不要用 `tri_state` 去画图**——那个投影正是把
返回弧抹平的那一步（它只给必须使用公共三态词汇的消费者，如状态板、API、文档）。

---

## 三、转移是有向的，且有禁止项

`PHASE_TRANSITIONS` 和 `FORBIDDEN_TRANSITIONS` 都在生成的 TS 里，源自
`docs/PHASE_TRANSITION_TABLE.md`。

```
formless ──→ liminal ──→ manifest
   ↑            │             │
   │            ↓             ↓
   └──────── formless      receding ──→ formless
```

**要点：`manifest` 的唯一出口是 `receding`。**

`manifest → liminal` 是**明令禁止**的（"结构不能不经 receding 就解体"）。所以从
表达期退出的动作永远该按「消散」编排，绝不是「退回上一档」。

`next_phases` 直接给出当前相位的合法去向——用它**提前**编排，而不是等相位跳变后才反应。

### 认出"发生过一次转移"：看驻留的序号，别只看一拍性的那位

主轴的转移性质有两种给法：

| 字段 | 性质 | 用法 |
|---|---|---|
| `transition_kind` | **一拍性**：只有转移之后组装的第一份广播带着 | 旧后端没有下面两位时的退路 |
| `transition_seq` | **驻留**：本进程主轴转移过几次，每一份消息都带着同一个数 | 跟自己上次见过的比，变了就是发生过转移 |
| `last_transition` | **驻留**：最近那次转移是哪一种（`TRANSITION_KINDS`） | 与 `transition_seq` 成对读 |

只认一拍性的那位，覆盖层中途才连上、或那一份恰好丢了，这一拍就整个没了 ——
「做完就散」的铺回动画不演，边光一直收着。第一次见到的序号只记下、不补演。
给**单个**新客户端发的快照不会把一拍性的那位用掉（`consume_edge=False`）。

> **历史教训**：旧的一维契约用 `retreat_tendency` 把 `manifest` 的深度朝 `liminal`
> 的锚点漂移，表达的正是这个被禁止的转移。**旧契约能表达状态机禁止的转移，却表达
> 不了它要求的那个（receding）。** 别重蹈。

---

## 四、`retreat_tendency` 的语义（容易读错）

后端原文是 *"Probability mass pushing toward retreat (manifest/liminal → **receding**)"*。

**它是"推向 receding 这个相"，不是"退回上一档"。** 一维遗留投影读错了这一条。

配对的 `collapse_tendency` 才是"推向下一档"（`liminal → manifest`）。

两者一起描述的是「离下一次转移有多近」——这就是你要的**"边缘模糊"**。它不是一个
深度标量，所以契约**刻意不带 depth**：再给一个位置数只会诱使前端重新自己推导一遍。

---

## 五、阈限态的内容（这是第二态之所以"空"的根因）

阈限态在面板上一直什么都没有，**不是因为动画简陋，是因为它的内容从没送出来过**。

智能体在真正落手之前，会先在影子沙盘里推演若干条候选路径
（`core/liminal_rehearsal.py`，借鉴 ICML'26 Gecko）：

- 只读工具**直通真实系统**（消除模拟偏差）
- 写状态工具**一律模拟**，永不落地
- 每次重试从同一初始快照重来，失败尝试不污染后续
- 可打断：barge-in/超时立即终止，零真实副作用

契约把它带出来了：

```ts
liminal_activity: "none" | "understanding" | "thinking" | "rehearsing"
simulation: {
  is_active, simulation_kind,
  candidate_paths,      // ← 正在权衡的那几条，这就是阈限态的可视内容
  committed_path, is_committed,
  step_count, scenario_label,
}
```

**覆盖层不画候选路径**（所有者的决定）：空间本身不写字，岛上只放一句它在干嘛
（正在理解 / 正在规划 / 正在推演）。`simulation` 照样在契约里 —— 给面板、调试和
以后别的表面用，不是给覆盖层往空间里画线的。

两条链路都给：
- `payload.render.simulation`——**持续**的，面板中途连上来也能立刻看到当前状态
- `skill.invoked` 事件（`kind="rehearsal"`, `simulated=true`）——**瞬时**的逐步过程。
  这条在 StateEventBus 上；面板桥对 `skill.*` 只安排设备清单推送，所以另有一帧 WS
  `type="rehearsal"`（`core/rehearsal_panel_push.py`）把每一步送到面板，面板在对话区与输入条
  之间照实画出来（`ui/rehearsal.ts`，每一行都写明「模拟」还是「真查了」）

### 一致性保证

契约层已经保证：`liminal_activity` 只在 `lifecycle === "liminal"` 时非 `none`。
你不会收到 `lifecycle=manifest` 且 `activity=rehearsing` 这种自相矛盾的帧。

但 `simulation` **会**在 `manifest` 期保留——那是结果不是活动，表达期仍要能显示
"按哪条候选提交的"。回到 `silent` 时才清空。

---

## 六、诚实标注：别把估计值当精确值画

```ts
source: "continuum" | "anchor_only"   // anchor_only = continuum 没跑，是兜底值
degraded: boolean                     // continuum 本拍跑在降级模式
degrade_reason: string | null
```

`anchor_only` 时，除主轴外的一切都是中性兜底值——**主轴仍然可信**（它来自在场
运行时，与 continuum 是两条独立链路）。别在这种帧上渲染"精确的内部状态"。

---

## 七、已知缺陷（接手时请先修，别在上面盖楼）

原先列在这里的三条都随 React 面板一起没了（`usePanelData.ts` 读错路径、`usePhase.ts`
三值开关 —— 面板已换成纯 TS 的 HUD，只读 `payload.render`）。后来查出来、已经修掉的，
记在这里防止回潮：

1. **边光的呼吸曾是 CSS 关键帧**：关键帧里的 `opacity` 压过同一属性的普通声明，
   `--rim` 写成 0（隐私急停、没有感知通路）也没用 —— 急停之后边光照样一明一暗地亮着，
   说的和事实正好相反。现在呼吸由 `app.js` 按帧给 `--breath`，与浓度在 CSS 里相乘。
2. **覆盖层的时间跟着帧率走**：每帧最多推进 0.05 秒，软件合成下第二态 4–6fps 时，
   1.7 秒的展开实际走了 5 秒以上。现在按墙钟推进（`STEP` / `MAX_GAP`）。
3. **朗读把空间重新推开**：说话时在场桥报的是 `liminal`（给已删掉的 React 面板打的补丁），
   每次语音回答空间开合两次。朗读是对外表达，现在报 `manifest`。
4. **面板的相位有两个写者**：SSE 的 `phase` 帧也往同一个状态位上写，线和岛会在两相之间
   跳一下。现在面板只认 WS 的 `render`。

5. **推演的逐步过程没有消费方**：`skill.invoked`（`kind="rehearsal"`）到面板只触发一次设备清单
   推送，步骤内容从没到过面板。2026-09-28 补上 WS `type="rehearsal"` 帧与面板那一段
   （`tests/test_rehearsal_panel_push.py`）。推的只有类型化字段，工具参数与模拟响应不推。

目前没有已知的仍然存在的缺陷。

---

## 八、遗留投影：`payload.posture`（别在新代码里用）

`posture` / `depth_factor` 是一维遗留投影（三个锚点串在一条 depth 轴上）。覆盖层
已经不读它了：展开度按主轴给（`OPEN_BY_LIFECYCLE`，第三态是**收回**，照 depth 画会越张
越大），`presence_motion.js` 的倾向与稳定度也从 `render` 里取。只有在后端**完全不发**
`render` 的时候（旧后端），覆盖层才逐位退回读 `payload.phase` / `payload.posture`。

新代码一律用 `payload.render`。

---

## 九、加了新字段之后

1. 改 `core/phase_contract.py` 的 `render_contract_schema()`
2. 跑 `python scripts/gen_ts_types.py`
3. `scripts/check_wiring.py --strict` 必须绿——它会抓「实现了但没有任何调用方」

> 第 3 条不是形式主义。本契约第一版就是**写完没接进桥**，而当时那个守卫因为一个
> 盲区（模块自己 `__all__` 里的字符串被算作"引用"）判了绿。盲区已修，现在拆掉唯一
> 调用方它会精确报红。

---

## 十、表达期的两种样子：出字出声，与动手

表达期（`lifecycle === "manifest"`）屏幕该是干净的。但它有两种样子，人对它们的需要完全不同：

- **出字、出声**：看着、听着就行。朗读也算这一种 —— 在场桥在说话时把主轴抬到 `manifest`，
  不会因为开口把空间重新推开。
- **动你的鼠标键盘**：整个流程里人最需要知道、也最需要能叫停的时刻。

契约里用两位把后者说清楚：

| 字段 | 含义 | 谁报 |
|---|---|---|
| `acting` | 此刻是否正在操作这台机器（键鼠、窗口、应用） | 真正落手的那几处自己报：`core.liminal_activity.acting()`，由 `core/computer_use_loop.py` 与 `core/hybrid_executor.py` 进出 |
| `stop_key` | 此刻按哪个键能叫停（如 `"Esc"`）；空串 = 没有 | `core/stop_key.py`，**只在键盘监听确实占到时才有值** |

`hybrid_execution` 分不开这两种样子（模式选完就一直为真，点名级别的执行又根本不登记），
所以 `acting` 单独一位，不从别的字段里猜。

**`stop_key` 不能从 `acting` 推出来。** 它自己动手时也会按 Esc（`press_key: esc`），所以叫停键
只认**真人按下**的那一下：pynput ≥ 1.8 在 Windows（`LLKHF_INJECTED`）与 macOS（事件源进程号）
上分得清，Linux 上分不清（XTest 注入的键与真按的一样），就不占 —— 那时 `acting` 为真而 `stop_key`
为空，渲染端照这一位**不写**「Esc 停止」。写着能停而按了没用，比不写更糟。

叫停本身走 `POST /api/v1/presence/stop`（面板的停止键也是这条）：取消在跑的请求（调用方拿到
`stopped=True` 的正常返回值，不会把整条自发注意力循环一起停掉）、掐断在念的话、打断双工里正在说
的那一句（会话留着）。

---

## 十一、被叫停 / 被中断时，正在飞的那一步：「不确定」，不是「失败」

电脑操作的点击是发给另一个节点的 HTTP 请求。叫停只能取消本端的等待 —— 请求可能已经到了、
点击可能已经发生；进程在两步之间崩了也一样：步骤记录在内存里，重启后没有任何痕迹。
这两种时刻，对「这一步执行了没有」的正确回答都是**不确定**：说「失败」，人会让它重来、重复点一次；
说「成功」是在编。借自 AFK-surf/Comma 的运行时（副作用先落盘再执行；写入结果不明返回
`commit_indeterminate` 且**不授予重放的权力**；明说「不承诺外部操作恰好执行一次」）。

`core/action_journal.py` 就是那一笔账：

| 时机 | 记什么 |
|---|---|
| 派发**之前** | `begin`：意图（动作、坐标、目标设备）先落盘、fsync，再动手 |
| 派发之后 | `end`：`ok` / `failed` / `unknown_after_cancel`（被取消时正在飞） |
| 进程重启 | 回放日志：只有 `begin` 没有 `end` 的，补记 `unknown_after_restart` 并报出来 —— **绝不自动重放** |

三个出口，都在场景里：

* **叫停的结果**：`stopped_result` 带 `unknown_actions`（`/chat/stream` 的 `done` 帧原样带上），
  面板说「最后这几步是否已经执行不确定：click(x=320, y=180) —— 先看一眼屏幕，再决定要不要让它继续」；
* **面板打开时**：`GET /api/v1/presence/unresolved-actions`（最近 15 分钟，再久屏幕早已不是当时的样子），
  非空就提示一次；
* **所有目标都记**（操作手机被取消同样不确定），但「正在操作 · Esc 停止」只对本机报
  （`core.presence_stop.operating`）。

记账的边界：`type` 的文字、密码类字段**只记长度**；磁盘写不了时降级为只在内存里记并**留痕**
（只说一次的告警 + 接口里的 `journal_degraded`），记账失败不拦动作；与
`core.unified.idempotency` / `core.durable_result_idempotency`（按 id 去重）是两件事，不互相替代。

---

## 十二、生命周期的性质测试（穷举，不挑例子）

`tests/test_lifecycle_properties.py`。借自 AFK-surf/Comma —— 它用 TLA+ 建模、让模型检查器把所有
交错走一遍；这里转移表本来就是数据、状态空间小，直接**穷举**：

* **转移表**：代码里的允许表 / 禁止表与 `docs/PHASE_TRANSITION_TABLE.md` 逐行一致；每个相位都有出口、
  没有孤岛；主轴上每一次真实的转移都有性质（`transition_kind_of`），没有「说不清」的一对。
* **桥上穷举**：所有长度 ≤ 3 的 (主轴, 说话, 动手) 序列 × 停止键占到 / 没占到，外加一条 3000 步的随机游走，
  每一步核对：转移序号只在主轴变了时加一；驻留的 `last_transition` 不会自己变；一拍性的 `transition_kind`
  只在转移后的第一份里；给单个新客户端的快照永远与随后的广播说同一件事；`stop_key` 非空必然 `acting`。
* **叫停**：请求停在「还在想 / 已落手 / 正在动手」任何一个阶段被叫停，都落回干净的静默 ——
  会话回到 SILENT、不再 `acting`、叫停键一份不多一份不少地还回去、从活跃表里摘掉、continuum 的 tick 停掉，
  只有动手阶段才带「结果不明」的那一步。

**主轴与副轴的出口不一样**（写这份测试时更正了先前一句过粗的话）：副轴 continuum 的 `manifest`
唯一出口是 `receding`；主轴上第三态有两个合法出口 —— `handoff`（做完接着下一轮，回阈限）与
`dissolving`（做完就散，回静默）。**说话**只把静默抬到表达，不改真正在阈限里的主轴（否则会把沙盘空间
在推演中途收掉）。

验证过它会响：故意改坏五处（序号不去重、快照用掉那一拍、叫停键不还、叫停结果丢掉「结果不明」、
允许表多开一个出口），五处都变红。

## 十三、覆盖层与面板的浏览器行为测试（让行为自己说话）

`electron/renderer/browser-tests/`（`harness.js`、`overlay.test.js`、`panel.test.js`）。借自 AFK-surf/Comma
的测试准则：**不要靠读实现的源码去推断运行行为**。覆盖层的坏法全是「不报错、画面不对」——最典型的一条：
边光的呼吸曾是 CSS 关键帧，关键帧里的 `opacity` 压过普通声明，隐私急停把 `--rim` 写成 0 也没用，屏幕上照样
一明一暗地亮着。读源码、读 CSS 文本都看不出来；要真开一个 Chromium，问它「算出来的 opacity 到底是多少」。

* **覆盖层（6 条）**：隐私急停后边光真的熄了；边光浓度跟着感知走；动手时岛上说「正在操作」、「Esc 停止」
  只在后端占到那个键时才写；「做完就散」的光从顶部铺回来，一拍性的那一位丢了也照样铺；中途才连上时第一帧只记序号、
  不补演；减少动效时呼吸停在定值。
* **面板（5 条）**：忙时发送键是停止键、先让后端停、正在飞的操作说「不确定」；自己发起的一轮不出现两遍而语音那边说的会出现；
  面板关着时说过的话重开就在（打开读后端对话主线）；此刻在哪一相只认 WS；打开时「上次中断留下的结果不明」提示一次、没有就一声不吭。
  后端用 Playwright 的路由 / `routeWebSocket` 替身，面板读的是真正入库的 `dist/`。
* **CI**：独立作业 `browser-behavior`（装 Chromium 要几十秒，不拖慢每次必过的 `panel-dist-consistency`）。
  作业里设 `GALAXY_REQUIRE_BROWSER=1` —— CI 里缺浏览器就是红的；本地没装时测试显式跳过并说怎么装，因为
  一条永远被跳过的绿线等于没有这条测试。Playwright 版本在 `package.json` 里钉死（不带 `^`），依赖走 `npm ci` 读 lock。
  `tests/test_browser_tests_run_in_ci.py` 守着这三件事（作业存在、要求浏览器、版本钉死），不让这道门悄悄变成摆设。
* **本地跑**：`cd electron/renderer/browser-tests && npm ci && npx playwright install chromium && npm test`。

验证过它会响：把面板的五处行为逐个改坏（停止键不先通知后端、叫停时丢掉「不确定」、SSE 的 phase 帧也能改相、打开时不读主线、
打开时不提示上次留下的「不确定」），每改一处重新构建，恰好对应的那一条测试变红，其余照常通过。**诚实的一条**：覆盖层里「只认序号来认一拍性」的那处改坏并不会让测试变红 —— `_stepRim`
里另有一条按状态推的铺回路径与它冗余，所以对应那条的标题与注释写的是「丢了那一位也照样铺」这个行为本身，而不是宣称单独钉住了序号。

## 十四、自发在场的治理：额度、期限、留痕、唤醒规则

`core/ambient_governance.py`（接进 `core/ambient_attention_loop.py`）。借自 AFK-surf/Comma 对「后台循环」的约束。
常驻注意力循环是三态里 SILENT→LIMINAL 的**自发入口**：用户没开口，它自己看、自己听、自己判断要不要开口或派活，
而且默认开。Comma 给这类东西立的几条规矩，对它同样成立 —— 此前只有一条「冷却 20 秒」：卡着**间隔**，不管**总量**，
更没有**期限**：一次委托卡住，整条循环就此无声地死掉（`running` 仍是 True，什么迹象都没有）。

| Comma 的规矩 | 这里对应的东西 |
|---|---|
| 活跃循环有配额 | 每滚动一小时：自发开口 12 次、自发委托 6 次（键 `GALAXY_AMBIENT_SPEAK_PER_HOUR` / `GALAXY_AMBIENT_DELEGATE_PER_HOUR`，面板「全部设置」里能调） |
| 事件有数量 / 体积上限 | 留痕最多 32 条；决策文字有字数上限（理由 1000 / 发言 1000 / 任务 4000，超出截断并标明） |
| 超过确认期限就判失败、说清楚、不静默重试 | 决策 90 秒、转写 45 秒、委托 15 分钟（与 Comma 的确认期同数）；到点叫停、写明原因、**不自动重试** |
| 只有显式 notify 才唤醒会话 | 只有 SPEAK 会出声、进面板、进对话主线；沉默、被压下、委托、委托失败一概不会 |

**不重造已有的东西。** 「同时跑几个、按来源配额、抢占」是 `core/request_admission.py` / `GlobalArbiter` 的事（并发轴），
自发委托走 `handle_request` 正门时已经受它管。本模块管的是它管不到的两条轴：时间轴上的**总量**与每一步的**期限**。
两边不共用计数器，也就不会出现「一边说满了一边说没满」。

* **额度不是静默的闸。** 超额的 SPEAK / DELEGATE 降级为 SILENT，**带着理由**写进决策（面板「它在想什么」那一行、
  工作记忆）：「本小时自发开口已用完（12/12），到 14:32 才恢复；原拟：…」。所以有配置键、降级写得出来 ——
  一个悄悄把陪伴型自发在场闷成哑巴的闸，比没有闸更糟。配置写错（非数字 / 非正）回到默认并**说一句**（同一个坏值只说一次）。
  **改了额度当场生效**：面板「全部设置」里保存之后，运行中的循环下一拍就用新的（每次取用都重新读环境），不必重启 ——
  这是本仓对设置页的硬要求（`tests/test_saving_a_setting_really_takes_effect.py`）。启动日志里写着此刻的额度。
  （节拍 / 冷却两个键仍是循环构造时读一次，那是既有行为，不在这次范围里。）
  **动手的那一刻才记一笔**：用户说了「等一下别说话」的那几分钟里，每一拍判出的 SPEAK 都被压下、一句没说，
  若在决策时就扣，hold 一解除就哑一个小时。被手表「别打扰」压下的也不算额度用完。
* **期限靠叫停，不靠放弃。** 到点取消的是**这一次委托本身**（经 `@stoppable` 的同一条取消通道），不是整条循环；
  运行时里它那一次请求落回干净的静默、不再「在动手」、叫停键还回去，已经发出去的那一步记成「结果不明」
  （第十一节）—— 这些由 `tests/test_ambient_loop_governance.py` 用真运行时钉住。没做完的写进下一拍的「最近注意到」，
  决策脑知道上一次没成，而不是当它成了。**期限分得清是谁的**：决策脑自己内部抛出的超时不会被记成「我们的期限到了」。
* **留痕只存类型与固定说明，不存异常原文**（那可能带路径 / 内部细节，而这份东西经接口交给面板）。同一类事十分钟内并成一条
  （计数 +1）—— 否则一个坏掉的决策脑每拍报同一个错，就把 32 个位置刷满、挤掉真正要紧的「委托超时」。
  委托没做完时**任务原文留着**，让人决定重来还是丢掉。
* **面板**：`GET /api/v1/presence/ambient-status`（额度、期限、留痕）。面板打开时问一次，**只**为「后台委托没做完」
  提示一次并说「不会自动重试」—— 那是循环自己悄悄派的活，人未必知道它曾经在做。额度用完是正常的治理、不是故障，
  不打扰人（降级当下已经写在决策的理由里）。提示过的时刻记在本机，同一件事不会每次打开都说。
* **唤醒规则的一处诚实的例外**：`GALAXY_AMBIENT_SHARE_SESSION`（默认开）下，委托续在用户**当前对话主线**上 ——
  委托的任务与回复会进主线。这是「自发在场不是一座孤岛」的代价，不是本节要翻的决定；额度与期限管着它做多少、做多久。
  想让后台活完全不进主线，把这个键关掉。委托的回复本身不会被念出来（运行时对 `source="ambient"` 抑制自动朗读，测试里有对照）。

**借了没借的**：Comma 的 incarnation 围栏（旧一代的调用被拒）没有借 —— `stop()` 取消循环任务时 `CancelledError` 会一路传出去，
旧任务不会在 stop 之后动手，也没有发现需要围栏的路径；没有失败场景的代码不加。顺手修了两处真问题：`running` 在任务意外死掉时
不再说谎、`start()` 也不再因为标志位还开着而永远起不来；`_delegate` 现在返回成败（此前吞掉异常、外面分不出「做完了」和「根本没做成」）。

**诚实的边界**：额度的计数在内存里，进程重启就清零 —— 它防的是「一直开着时的失控」，不是崩溃循环。

**搬家**：循环文件原先 992 行、逼近体量线，治理要接进来得先腾地方。三选一的数据类型搬到叶子模块 `core/ambient_types.py`，
默认决策脑与解析搬到 `core/ambient_decider.py`（治理层、决策脑、循环三方各自单向依赖类型，不循环 import），
原模块原样再导出，仓内与测试里既有的 `from core.ambient_attention_loop import …` 一行没改。循环文件现在 752 行。

验证过它会响：把治理层与接线逐处改坏（额度不拦、决策时就扣额度、开口不记额度、委托 / 决策 / 转写没有期限、
循环绕过任何一道、`_delegate` 失败也回成功、不截断、不合并、不设上限、留痕带异常原文、委托标志不复位、窗口不滑动、
把内部超时当成自己的期限、`running` / `start()` 只看标志位、额度冻结在构造那一刻、坏值每拍都说、显式额度被环境改写），
20 处每处恰好对应的测试变红；面板那条提示再改坏四处
（不分类别、提示过不记、根本不提示、不带记下的时刻去问），四处变红。
