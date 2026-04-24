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

### 缺口 1：ReconciliationSignal AIP wire 层缺失（最关键）

**问题描述（已通过代码验证）**：
Android 侧有完整的四层评估器（readiness/acceptance/governance/strategy），`ReconciliationSignal.kt`（PR-51）定义了 Android→V2 的 7 种 signal kind（含 `PARTICIPANT_STATE` 用于上报 readiness 变化），`DelegatedRuntimeReadinessEvaluator.kt` 第 `INTEGRATION_RUNTIME_CONTROLLER` 常量注明 artifacts 通过 "reconciliation signal channel" 转发。但：
- `AipModels.kt` 的 `MsgType` enum 最后一个条目是 `HANDOFF_ENVELOPE_V2`（代码末尾的 companion object 之前），**无 `reconciliation_signal` 消息类型**（搜索全文确认）
- `ReconciliationSignal.kt` 中的 wire key 常量（`KEY_KIND = "reconciliation_signal_kind"` 等）有了，但没有对应的 AipMessage 封装，`GalaxyWebSocketClient.sendJson()` 无调用路径
- V2 gate 无法接收 Android 的 readiness/governance artifact，导致发布决策缺少 Android 端维度

**影响**：V2 的 readiness/governance verdict 是在没有 Android 端评估输入的情况下做出的，准确性存疑。

---

### 缺口 2：HandoffEnvelopeV2 上行 response gateway 未挂接（中等关键）

**问题描述（已通过代码验证）**：
Android 有 `handoff_envelope_v2_result` 消息类型（`AipModels.kt` MsgType enum）和 `HandoffEnvelopeV2ResultPayload` data class。V2 有 `core/android_handoff_v2_response_ingress.py`。但 `galaxy_gateway/android/handlers/` 目录中列举的 handler 文件（`delegated_signal.py`、`diagnostics.py`、`file_transfer.py`、`generic.py`、`goal_execution.py`、`heartbeat.py`、`mesh_topology.py`、`peer_exchange.py`、`registration.py`、`task_lifecycle.py`、`task_submit.py`、`vision.py`）**无 handoff response handler**，`android_bridge.py` 也无 `handle_handoff_response` 的 import 语句，Android 的 handoff result 到达 V2 后会进入 `else` 分支被记录为未处理。

**影响**：V2 无法跟踪 handoff 执行结果，handoff 链路形成单向信道（V2 发出但不接收反馈）。

---

### 缺口 3：Android compat/legacy influence 上报路径（次关键）

**问题描述**：
V2 的 `CompatLegacyPathBlockingCanonicalization` 需要识别所有 compat/legacy 影响向量。Android 有 `AndroidCompatLegacyBlockingParticipant`，但它向 V2 上报 compat influence 的具体消息类型和路径在代码中不明确。与缺口 1 类似，可能也依赖 `ReconciliationSignal.PARTICIPANT_STATE` 路径，因此同样受 wire 层缺失影响。

---

### 缺口 4：Takeover executor 部分功能延迟（低优先级）

**问题描述**：
`AipModels.kt` `MsgType.TAKEOVER_REQUEST` 的 KDoc 注明："payload parsed; ack sent; full takeover executor deferred to PR-5"。说明基础协议路径已接通，但 takeover 的完整执行器实现被延迟到后续 PR。

---

## 4. 如果继续推进，下一阶段工作的自然方向

### 方向 1：建立 ReconciliationSignal 的 AIP 传输层（紧迫度：最高）

具体工作：
1. 在 `AipModels.kt` 中新增 `MsgType.RECONCILIATION_SIGNAL("reconciliation_signal")`（向后兼容：新增不影响现有 MsgType 处理逻辑，旧版 V2 通过 `else` 分支忽略未知类型，无 breaking change）
2. 新建 `ReconciliationSignalPayload` data class 封装 `ReconciliationSignal` 已有字段（复用现有 `KEY_KIND` 等 wire key 常量）
3. 在 `RuntimeController.kt` 中实现 `ReconciliationSignal → AipMessage → GalaxyWebSocketClient.sendJson()` 的发送路径
4. 在 V2 `galaxy_gateway/android/handlers/` 中新增 `reconciliation_signal.py` handler（参考 `delegated_signal.py` 结构）
5. 在 V2 `android_participant_truth_ingress.py` 中增加对 `PARTICIPANT_STATE` kind 的处理，将 readiness artifact 接入 `delegated_flow_readiness_gate.py` 的维度输入

### 方向 2：挂接 HandoffEnvelopeV2 response handler（紧迫度：高）

具体工作（无 AIP 协议变动，仅 V2 gateway 侧工作）：
1. 在 V2 `galaxy_gateway/android/handlers/` 新增 `handoff_response.py` handler（参考 `delegated_signal.py` 结构）
2. 在 `android_bridge.py` 中导入并注册该 handler，匹配 `MsgType.HANDOFF_ENVELOPE_V2_RESULT`
3. 确保 handler 调用 `core/android_handoff_v2_response_ingress.py` 的入站处理逻辑

### 方向 3：打通 compat influence 上报路径（紧迫度：中）

具体工作（前提：方向 1 完成后 ReconciliationSignal channel 可用）：
1. 在 `AndroidCompatLegacyBlockingParticipant` 生成 compat event 时，通过 `ReconciliationSignal.PARTICIPANT_STATE` 附带 compat 状态上报
2. 在 V2 compat gate 中增加从 Android 入站 compat signal 更新决策的逻辑

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
| Handoff / takeover | 🟡 部分成熟（65%） | 下行 handoff 接通，上行 response gateway handler 缺失（已验证断层） |
| Session/continuity/recovery | 🟡 基本成熟（75%） | 双端骨架完整，协调消息触发时机待验证 |
| Truth alignment | 🟡 部分成熟（60%） | 处理器完整，触发链不够清晰 |
| Result convergence | 🟢 成熟（85%） | V2 聚合逻辑完整 |
| Compat/legacy governance | 🟡 部分成熟（65%） | V2 阻断引擎完整，Android 侧上报路径弱 |
| Operator surface / audit | 🟡 部分成熟（65%） | V2 侧完整，Android artifacts 上报路径弱 |
| Readiness/acceptance gate | 🟠 框架完整，AIP 传输层断层（35%） | ReconciliationSignal 内部 DTO 存在，但 wire 层未建立（已验证） |
| Governance/strategy gate | 🟠 框架完整，AIP 传输层断层（30%） | 同上 |
| Default-on rollout | 🔴 尚未开始（10%） | 依赖以上缺口修复 |

**图例**：🟢 成熟（可信依赖）｜🟡 基本成熟（有效但有局限）｜🟠 框架存在（不可信依赖）｜🔴 尚未开始

---

## 6. 一句话系统现状

> **这个系统已经建立了完整的 delegated canonical path 骨架和双端治理评估框架，基础执行链路已经真实运转，但 readiness/governance 四层发布决策所需的跨端信号流仍有明显断层，系统目前处于"骨架建成、治理信号流打通"这一关键过渡阶段。**
