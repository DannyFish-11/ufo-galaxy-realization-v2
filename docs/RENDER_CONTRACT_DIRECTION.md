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
liminal_activity: "none" | "thinking" | "rehearsing"
simulation: {
  is_active, simulation_kind,
  candidate_paths,      // ← 正在权衡的那几条，这就是阈限态的可视内容
  committed_path, is_committed,
  step_count, scenario_label,
}
```

**这是第二态最值得画的东西。** 不是一个"思考中"的转圈，而是"它在这几条路之间
权衡，最后选了这条"。

两条链路都给：
- `payload.render.simulation`——**持续**的，面板中途连上来也能立刻看到当前状态
- `skill.invoked` 事件（`kind="rehearsal"`, `simulated=true`）——**瞬时**的逐步过程

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

1. **`usePanelData.ts` 读错路径**：`payload.presence_intensity` / `coherence` /
   `collapse_tendency` 是**顶层**路径，而 state_event 里它们在 `payload.posture.*`。
   `?? prev` 让它们永远保留初始 0——面板上「强度 0 / 连贯 0」就是这么来的，
   不是智能体闲着。
2. **面板不订阅预演事件**：`kind === "rehearsal"` 的 `skill.invoked` 全仓零消费方。
3. **`usePhase.ts` 是三值开关**：子串匹配消息 type 取三态之一，且
   `if (newPhase !== phaseRef.current)` 把相位内的移动全部丢弃——带内的连续变化
   在面板上不可见。**新代码请直接消费 `payload.render`，别扩展这个 hook。**

---

## 八、遗留投影：`payload.posture`（别在新代码里用）

`posture` / `depth_factor` 是一维遗留投影（三个锚点串在一条 depth 轴上）。保留它
**只为兼容既有覆盖层** `electron/renderer/presence_motion.js`——那份代码按这三个
锚点调过参，为换契约破坏它不值得。

新代码一律用 `payload.render`。

---

## 九、加了新字段之后

1. 改 `core/phase_contract.py` 的 `render_contract_schema()`
2. 跑 `python scripts/gen_ts_types.py`
3. `scripts/check_wiring.py --strict` 必须绿——它会抓「实现了但没有任何调用方」

> 第 3 条不是形式主义。本契约第一版就是**写完没接进桥**，而当时那个守卫因为一个
> 盲区（模块自己 `__all__` 里的字符串被算作"引用"）判了绿。盲区已修，现在拆掉唯一
> 调用方它会精确报红。
