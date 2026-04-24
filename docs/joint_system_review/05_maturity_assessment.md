# 成熟度与缺口审查

> 审查依据：基于真实代码，不基于愿景。
> 输出：当前系统所处阶段判断 + 已完成程度 + 最关键未闭合点 + 下一阶段方向

---

## 1. 当前阶段判断

> **基于代码反推：这个系统当前处于"canonical path 骨架收敛完成，进入 readiness/acceptance/governance 信号流打通阶段"。**

更准确地说：

- 不是基础骨架期（基础执行、transport、session 管理均已有实质实现）
- 不是纯 canonical path 收敛期（canonical path 骨架已经建成，包括双端评估器）
- 不是 default-on 成熟期（关键信号流仍有断层，还不能说系统已完全可信依赖 canonical path 做决策）
- **当前处于**：canonical path 骨架 → readiness/governance 信号流打通 → 真正可信发布治理 之间的过渡阶段

---

## 2. 已完成到什么程度

### 第一层：基础执行能力（✅ 完整）

| 能力 | 完成状态 |
|------|---------|
| AIP v3 传输协议双端对齐 | ✅ 完整 |
| WebSocket 连接 + 重连 + 心跳 | ✅ 完整 |
| 设备注册 + posture 声明 | ✅ 完整 |
| 基础任务执行（task_submit→task_result） | ✅ 完整 |
| Goal 执行（goal_execution→goal_execution_result） | ✅ 完整 |
| 离线任务队列（OfflineTaskQueue） | ✅ 完整 |

### 第二层：Delegated canonical path 骨架（✅ 完整）

| 能力 | 完成状态 |
|------|---------|
| Delegated flow entity + execution tracker | ✅ 完整 |
| Handoff contract + dispatch binding | ✅ 完整 |
| HandoffEnvelopeV2 native 消费（PR-H） | ✅ 完整 |
| Delegated execution signal 新格式（PR-16） | ✅ 完整 |
| Android runtime host 分类（PR-5）| ✅ 完整 |
| Attached session registry | ✅ 完整 |
| Continuity coordinator（7 种 continuity 场景） | ✅ 完整 |
| Result convergence（并行聚合 + duplicate 抑制） | ✅ 完整 |
| Compat/legacy blocking gate（5 种决策） | ✅ 完整 |

### 第三层：发布治理框架（⚠️ 框架完整，信号流待打通）

| 能力 | 完成状态 |
|------|---------|
| Readiness gate（V2 侧框架） | ✅ 框架完整，产出 6 种 verdict |
| Acceptance gate（V2 侧框架） | ✅ 框架完整，产出 graduation verdict |
| Post-graduation governance（V2 侧框架） | ✅ 框架完整，5 种 violation/compliant |
| Program strategy（V2 侧框架） | ✅ 框架完整，5 种 risk/on-track |
| Android readiness evaluator | ✅ 评估器完整，artifact 结构完整 |
| Android acceptance evaluator | ✅ 评估器完整，artifact 结构完整 |
| Android governance evaluator | ✅ 评估器完整，artifact 结构完整 |
| Android strategy evaluator | ✅ 评估器完整，artifact 结构完整 |
| **Android artifact 主动上报路径** | ❌ **尚无明确专用消息类型和推送触发器** |
| **V2 gate 从 Android artifact 读取输入** | ⚠️ **V2 gate 读取自内部模块，Android artifact 如何进入待明确** |

### 第四层：真正 default-on 可信运行（❌ 尚未完成）

| 能力 | 完成状态 |
|------|---------|
| Legacy path 默认关闭 | ❌ 未完成（compat gate 存在但 legacy 还在运行）|
| 基于 readiness verdict 自动阻断发布 | ❌ 框架存在但未接入 CI/release pipeline |
| 基于 governance verdict 自动 rollback | ❌ 框架存在但无自动触发 |
| 全量 legacy → canonical migration | ❌ 迁移仍在进行 |
| Readiness/governance 实时信号链路闭合 | ❌ 见上文断层 |

---

## 3. 当前最关键的未闭合点

### 缺口 1：Android readiness/acceptance/governance/strategy artifact 上报路径（最关键）

**问题描述**：
Android 侧有完整的四层评估器（readiness/acceptance/governance/strategy），每层都有 evaluator + artifact 数据结构。V2 侧有完整的四层门控（readiness gate/acceptance gate/governance/strategy）。但两者之间**没有找到明确的实时信号流**：
- `AipModels.kt` 中没有 `readiness_artifact`、`governance_artifact` 等专用消息类型
- V2 gate 的五维度读取来自内部模块，不是来自 Android 评估结果

**影响**：V2 的 readiness/governance verdict 无法包含 Android 端的评估视角，导致发布决策缺少 Android 侧维度。

**推测路径**：可能通过 `android_participant_truth_ingress.py` 的 `readiness_assessment` truth kind 进入，但需要专门验证。

---

### 缺口 2：Android compat/legacy influence 上报路径（次关键）

**问题描述**：
V2 的 `CompatLegacyPathBlockingCanonicalization` 需要识别所有 compat/legacy 影响向量。Android 有 `AndroidCompatLegacyBlockingParticipant`，但它向 V2 上报 compat influence 的具体消息类型和路径在代码中不明确。

**影响**：V2 compat 阻断决策可能缺少 Android 本地 compat 状态的输入，导致 compat governance 不完整。

---

### 缺口 3：Truth reconciliation 触发时机（中等重要）

**问题描述**：
V2 有 `android_participant_truth_ingress.py` 能处理 8 种 truth kind，Android 有 `LocalTruthEmitDecision.kt` 做上报决策。但在 Android 执行代码（`AutonomousExecutionPipeline.kt`、`RuntimeController.kt`）中，具体什么时间点、什么条件下会触发 truth 上报，以及走哪种 truth kind 消息，这条触发链的清晰程度有限。

---

### 缺口 4：Takeover executor 部分功能延迟（低优先级）

**问题描述**：
`AipModels.kt` 中对 `TAKEOVER_REQUEST` 的状态注明："payload parsed; ack sent; full takeover executor deferred to PR-5"。说明基础协议路径已接通，但 takeover 的完整执行器实现被延迟到后续 PR。

---

## 4. 如果继续推进，下一阶段工作的自然方向

### 方向 1：打通 Android artifact 上报路径（紧迫度：高）

具体工作：
1. 在 `AipModels.kt` 中新增专用消息类型（如 `delegated_readiness_report`、`delegated_governance_report`）
2. 在 Android 的四个 evaluator 中增加 report 发送触发器
3. 在 V2 `android_delegated_signal_ingress.py` 或新建专用 handler 中增加接收和处理逻辑
4. 将 Android artifact 数据接入 V2 readiness gate 的对应维度

### 方向 2：打通 compat influence 上报路径（紧迫度：中）

具体工作：
1. 确认 Android `AndroidCompatLegacyBlockingParticipant` 产生 compat event 的具体场景
2. 定义 compat influence 消息类型或借用现有 truth ingress 路径
3. 在 V2 compat gate 中增加从 Android 入站 compat signal 更新决策的逻辑

### 方向 3：明确 truth reconciliation 触发链（紧迫度：中）

具体工作：
1. 在 Android 执行关键节点（任务开始/结束、phase 变更、readiness 变化）增加明确的 truth emit 触发点
2. 在 `LocalTruthEmitDecision.kt` 中明确列出触发条件和对应 truth kind 映射
3. 确认 gateway handler 对这些消息的路由注册

### 方向 4：完成 takeover executor（紧迫度：低）

接续 PR-5 中延迟的 full takeover executor 实现，让 takeover 路径从"协议接通"升级到"完整执行闭环"。

### 方向 5：Legacy retirement（中期目标）

在以上信号流打通之后，才有信心：
1. 将 readiness gate verdict 接入 release pipeline
2. 将 compat gate 阻断升级到默认 block（而非 observation-only）
3. 开始真正的 legacy path default-off 推进

---

## 5. 成熟度总表

| 维度 | 成熟度 | 说明 |
|------|--------|------|
| 传输层（WebSocket/AIP v3） | 🟢 成熟（90%+） | 唯一缺项是 minimal-compat stub 类型 |
| 基础执行（task/goal） | 🟢 成熟（90%+） | 最完整的路径 |
| Delegated execution signal | 🟡 基本成熟（80%） | 新旧格式并存，旧格式依赖 compat 推断 |
| Handoff / takeover | 🟡 基本成熟（75%） | 协议接通，takeover executor 部分延迟 |
| Session/continuity/recovery | 🟡 基本成熟（75%） | 双端骨架完整，协调消息触发时机待验证 |
| Truth alignment | 🟡 部分成熟（60%） | 处理器完整，触发链不够清晰 |
| Result convergence | 🟢 成熟（85%） | V2 聚合逻辑完整 |
| Compat/legacy governance | 🟡 部分成熟（65%） | V2 阻断引擎完整，Android 侧上报路径弱 |
| Operator surface / audit | 🟡 部分成熟（65%） | V2 侧完整，Android artifacts 上报路径弱 |
| Readiness/acceptance gate | 🟠 框架完整，信号流待打通（40%） | 最关键的缺口 |
| Governance/strategy gate | 🟠 框架完整，信号流待打通（35%） | 同上 |
| Default-on rollout | 🔴 尚未开始（10%） | 依赖以上缺口修复 |

**图例**：🟢 成熟（可信依赖）｜🟡 基本成熟（有效但有局限）｜🟠 框架存在（不可信依赖）｜🔴 尚未开始

---

## 6. 一句话系统现状

> **这个系统已经建立了完整的 delegated canonical path 骨架和双端治理评估框架，基础执行链路已经真实运转，但 readiness/governance 四层发布决策所需的跨端信号流仍有明显断层，系统目前处于"骨架建成、治理信号流打通"这一关键过渡阶段。**
