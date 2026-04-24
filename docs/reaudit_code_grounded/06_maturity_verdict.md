# 06 — 当前成熟度判断与最关键下一步

> **审查方法**：不沿用 PR #793 的成熟度分级，完全从代码真实接通程度重新评估。

---

## 一、系统当前真实阶段判断

### 判断框架

| 阶段 | 描述 |
|------|------|
| A. Delegated canonical skeleton | 基础任务分发骨架，V2 → Android 单向链路 |
| B. Distributed agent skeleton（本阶段）| 双端均有真实 agent runtime，本地链路与跨设备链路并存，基础双向 signal 接通 |
| C. Full distributed agent system | 双端自治，readiness/governance 跨端闭合，handoff 双向，continuity 完整 |
| D. Stable production system | 所有关键链路接通，有完整可观测性，伪闭环链路已剪除或实现 |

### 当前阶段结论

> **系统当前处于阶段 B（Distributed agent skeleton）初期**，而非 PR #793 所描述的"delegated canonical skeleton + 双端评估框架已建成"。

**B 阶段成立的代码证据：**
1. 双端均有真实 agent runtime（非仅有任务分发）
2. 本地链路与跨设备链路并存（均有真实实现）
3. 基础双向 signal 接通（delegated_execution_signal 链路完整）
4. 任一侧均可合法发起（source_runtime_posture 双端对称）
5. 双端均有 agent-like autonomy 模块（AutonomousExecutionPipeline、EdgeExecutor、LocalGoalExecutor 等）

**B 阶段"初期"而非"成熟"的代码证据：**
1. HandoffEnvelopeV2 返回链断层（handoff 单向）
2. ReconciliationSignal wire 协议缺失（四层评估跨端未闭合）
3. Continuity 跨端 wire 集成程度待验证
4. 伪闭环链路（RELAY/SESSION_MIGRATE/RAG/HYBRID）尚未实现

---

## 二、已形成 Distributed Agent Skeleton 吗？

**基于代码的回答：已形成骨架，但不完整。**

| 特征 | 已成立 | 未完整成立 |
|------|--------|----------|
| 双端真实 runtime | ✅ | — |
| 本地链路闭环 | ✅ | — |
| 基础跨端信号双向 | ✅ | — |
| 任一侧发起合法 | ✅ | — |
| Handoff 双向闭环 | — | ❌ 上行断层 |
| Readiness/governance 跨端闭合 | — | ❌ wire 断层 |
| Continuity 跨端 | — | ⚠️ 待完整验证 |
| P2P / relay / hybrid | — | 🔶 伪闭环（stub 层） |

---

## 三、仍主要停留在 Delegated Canonical Skeleton 吗？

**不是。** 相比 PR #793 所描述的"delegated canonical skeleton"阶段，系统已经显著超越了这个阶段：

- **证据 1**：Android 有 `AutonomousExecutionPipeline.kt`（不是 delegated 执行，是真正自主执行）
- **证据 2**：Android 有 `LocalGoalExecutor.kt`（不依赖 V2 的独立 goal 执行）
- **证据 3**：Android 有 `TakeoverEligibilityAssessor.kt`（本地自主判断 takeover 资格，不是被动接受）
- **证据 4**：V2 有 `local_agent_runtime.py`（V2 自身具备 agent loop 能力，不只是编排者）
- **证据 5**：`source_runtime_posture` 双端对称（协议层支持任一侧声明 runtime 姿态）

---

## 四、距离真正稳定的双端自治 / 跨设备合法协作还差什么

### 最关键缺口（按优先级排序）

#### 缺口 1：HandoffEnvelopeV2 返回路由（最直接可修复）

| 项目 | 状态 |
|------|------|
| 缺失内容 | `galaxy_gateway/android/handlers/` 中缺 handoff_envelope_v2_result handler |
| 影响范围 | 所有 handoff 场景，V2 永远无法知道 handoff 是否成功 |
| 修复代价 | 中等（需新建 handler 文件 + `android_bridge.py` 注册一行 + 接入 `android_handoff_v2_response_ingress.py`）|
| 已有基础 | `core/android_handoff_v2_response_ingress.py` 完整实现等待接入 |

#### 缺口 2：ReconciliationSignal wire 协议（架构级缺口）

| 项目 | 状态 |
|------|------|
| 缺失内容 | `AipModels.kt` MsgType 枚举缺 `reconciliation_signal`（或等价类型）|
| 影响范围 | Android 四层评估器 artifact 无法到达 V2 readiness gate，四层评估链路跨端断裂 |
| 修复代价 | 较高（需 Android 侧增加 MsgType、payload 类型定义；V2 侧增加接收 handler 并连接到 gate）|
| 已有基础 | Android 四层评估器完整；V2 四层 gate 完整；中间缺 wire 协议类型 |

#### 缺口 3：Continuity 跨端 wire 集成（需进一步验证）

| 项目 | 状态 |
|------|------|
| 缺失内容 | Android 侧 continuity 信号如何通过 wire 触发 V2 `FlowContinuityCoordinator` 待验证 |
| 影响范围 | 跨设备任务在 Android 断开/重连后的 continuity 可靠性 |
| 修复代价 | 需代码 trace，确认 `android_v2_continuity_contract.py` 和 Android 侧的真实接入点 |

#### 缺口 4：伪闭环链路的后续决策（RELAY/SESSION_MIGRATE/RAG/HYBRID）

| 项目 | 状态 |
|------|------|
| 说明 | 这些链路目前是 stub/TODO，需要明确是实现还是剪除 |
| 影响范围 | 对当前功能无影响；但会累积技术债和假成熟状态 |
| 建议 | 在 AipModels.kt 中用更明确的注释标注，或通过 deprecation 路径清理 |

---

## 五、最关键的单个下一步

**基于代码判断，最高优先级的单个改动是：**

> **修复 `HANDOFF_ENVELOPE_V2_RESULT` 的 gateway 路由**

理由：
1. `core/android_handoff_v2_response_ingress.py` 已经完全实现，等待接入
2. 只需在 `galaxy_gateway/android/handlers/` 新建 handler 并在 `android_bridge.py` 注册一行
3. 修复代价最低，收益最高（从单向 handoff 变为真正的 request/response 双向闭环）
4. 不需要修改 Android 侧代码（Android 已经发送 `HANDOFF_ENVELOPE_V2_RESULT`，只是 V2 没有接收）

**第二优先级：**

> **在 `AipModels.kt` 增加 `reconciliation_signal` MsgType 并配套构建 payload、V2 ingress handler**

理由：
1. 这是四层评估（readiness/acceptance/governance/strategy）能真正跨端生效的基础
2. Android 侧评估器完整，V2 gate 完整，wire 协议是唯一缺失
3. 完成后系统将从"两端各自评估但无法协作"升级为"双端分布式 readiness 协作"

---

## 六、当前系统成熟度总结

```
已成立（稳定运行中）：
  ✅ 双端设备注册与 posture 协商
  ✅ 基础任务执行（task_assign / task_result）
  ✅ Goal 执行链
  ✅ Delegated execution signal 上报链
  ✅ 心跳 / 离线缓存 / 重连
  ✅ Android 本地 agent loop（autonomous pipeline / local goal / local loop）
  ✅ V2 本地 agent 执行（local_agent_runtime）
  ✅ Compat/legacy 路径阻断
  ✅ Operator surface 与 replay audit（V2 侧）

骨架存在、跨端未闭合：
  ⚠️ HandoffEnvelopeV2（下行成立，上行断层）
  ⚠️ 四层评估（readiness/acceptance/governance/strategy）
  ⚠️ Continuity 跨端协同（V2 侧完整，跨端 wire 待验证）
  ⚠️ Android 侧 observability artifact 集成

命名存在、实际未实现：
  🔶 RELAY / FORWARD / REPLY
  🔶 SESSION_MIGRATE
  🔶 RAG_QUERY / CODE_EXECUTE
  🔶 HYBRID_EXECUTE

最高优先级工程缺口：
  ❌ HANDOFF_ENVELOPE_V2_RESULT gateway 路由（可立即修复）
  ❌ ReconciliationSignal wire 协议（需双端协同实现）
```
