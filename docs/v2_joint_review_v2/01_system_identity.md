# 系统本体重新识别

> **审查方法**：仅依据真实代码，不依据 README 或上一版审查结论。
> **代码来源**：
> - V2：`core/local_execution_chain.py`、`core/cross_device_execution_chain.py`、`core/system_orchestrator.py`、`galaxy_gateway/android_bridge.py`、`core/android_runtime_host.py`
> - Android：`loop/LoopController.kt`、`runtime/RuntimeController.kt`、`service/GalaxyConnectionService.kt`、`protocol/AipModels.kt`

---

## 1. 这个系统是什么：代码级回答

### 1.1 V2 侧 runtime 本质

V2 不是单纯的 HTTP 服务端，而是一个**多层自治 runtime 系统**：

**代码证据 — `core/system_orchestrator.py`**：
```python
# Staged bring-up phases
# Phase 1 — LOAD_CONFIG
# Phase 2 — RESOLVE_MODE
# Phase 3 — ENV_CHECKS
# Phase 4 — BACKGROUND_SUBSYSTEMS
# Phase 5 — RUNTIME_SUBJECT        ← 启动 runtime subject（非服务）
# Phase 6 — DESKTOP_SURFACE
# Phase 7 — READINESS_SUMMARY
```
V2 有自己的 staged runtime 启动合约，带 `READINESS_SUMMARY` 阶段，说明它本身是一个 runtime 主体，而不只是一个请求处理器。

**代码证据 — `core/local_execution_chain.py`**：
```
OpenClawd (routing authority)
    └─ AgentKernel (planning/cognition)
          └─ CommandRouter.route_envelope() [LOCAL_MANIFESTATION]
                └─ Local executor / capability / skill / MCP tool
```
V2 自己有完整的本地执行链，OpenClawd 是 routing authority，不是被动响应端。

**代码证据 — `core/cross_device_execution_chain.py`**：
```
OpenClawd (routing authority)
    └─ CommandRouter (cross-device sole router)
          └─ TaskEnvelope / CommandEnvelope
                └─ Gateway substrate
                      └─ Worker / Device / Node
```
V2 作为跨设备编排中心，维护完整的 cross-device 链路。

**结论**：V2 是一个具有**完整 agent runtime 特征**的系统——有自己的路由决策（OpenClawd）、有认知层（AgentKernel）、有本地执行链、有跨设备编排链，同时是所有跨端 canonical 状态的权威仲裁者。

---

### 1.2 Android 侧 runtime 本质

Android 也不是单纯的"客户端"，而是一个**具有本地自治执行能力的分布式 agent node**：

**代码证据 — `loop/LoopController.kt`**：
```kotlin
/**
 * Orchestrates the full local closed-loop automation pipeline:
 *   natural-language instruction
 *     → model readiness check / download
 *     → screenshot capture
 *     → LocalPlanner inference (MobileVLM)
 *     → stagnation / plan-repeat guard
 *     → ExecutorBridge action dispatch (SeeClick grounding + AccessibilityService)
 *     → post-action screenshot + PostActionObserver
 *     → StagnationDetector step guard
 *     → repeat until completion or budget/timeout/stagnation termination
 */
class LoopController(...)
```
Android 有完整的本地 think→act→observe 循环，含 LLM 推理、grounding、stagnation 检测——这是 agent 特征，不是简单客户端特征。

**代码证据 — `loop/LoopController.kt`（互斥调度）**：
```kotlin
@Volatile var isRemoteTaskActive: Boolean = false
    private set

fun cancelForRemoteTask() {        // 远程任务到来时暂停本地执行
    cancelRequested = true
    isRemoteTaskActive = true
}
fun clearRemoteTaskBlock() {       // 远程任务结束后恢复本地执行
    cancelRequested = false
    isRemoteTaskActive = false
}
```
本地执行和远程执行**共享同一个 Android runtime**，通过互斥信号协调——说明 Android 是真正的多模式 runtime，不是单一功能客户端。

**代码证据 — `service/GalaxyConnectionService.kt`**：
```kotlin
// 本地发起路径（路由判断）：
// 2a. cross-device ON + !require_local_agent → handoff to AgentRuntimeBridge
// 2b. cross-device OFF 或 require_local_agent → executeLocalTaskAssign (EdgeExecutor)
```
Android 自己做路由决策，判断是否本地执行或 cross-device——这是 agent-like 的路由自治特征。

**代码证据 — `runtime/RuntimeController.kt`**：
```kotlin
// 本地 reconciliation signal 流（PR-52）
private val _reconciliationSignals =
    MutableSharedFlow<ReconciliationSignal>(extraBufferCapacity = RECONCILIATION_SIGNAL_BUFFER_CAPACITY)

// 四层 readiness/acceptance/governance/strategy 评估器
// DelegatedRuntimeReadinessEvaluator
// DelegatedRuntimeAcceptanceEvaluator
// DelegatedRuntimeGovernanceDimension
// DelegatedRuntimeStrategyEvaluator
```
Android 有自己的四层评估框架，对自身运行状态持续监控，并在本地维护 truth——这是 distributed agent node 的特征。

**结论**：Android 不是被动执行端，而是一个**具备本地 agent runtime、自治评估、信号上报能力的分布式智能体节点**。

---

## 2. 为什么本地链路和跨设备链路间距都成立

### 2.1 本地链路：两端各有完整闭环

**V2 本地链路**（代码证据：`core/local_execution_chain.py`）：
- `OpenClawd` 决定本地执行 → `CommandRouter.route_envelope(LOCAL_MANIFESTATION)` → 本地 executor（capability/skill/MCP tool）→ 结果回流 OpenClawd → projection/memory backflow
- **完全不需要跨设备通信**，V2 自己就能完成一个完整的执行闭环。

**Android 本地链路**（代码证据：`loop/LoopController.kt`）：
- 用户通过 FloatingWindow/语音输入 instruction → `LoopController.execute(instruction)` → `LocalPlanner.plan()` → `ExecutorBridge` 执行 → 截图 → `PostActionObserver` 观测 → 循环直到完成
- **完全不需要连接 V2**，Android 自己就能完成一个完整的本地 agent 执行闭环。

### 2.2 跨设备链路：两端各为合法发起侧

**V2 侧发起**（代码证据：`core/cross_device_execution_chain.py`）：
- `OpenClawd` 路由决策 → `CommandRouter` 跨设备路由 → `TaskEnvelope` → gateway → Android 执行 → 结果回流
- V2 是 orchestration 发起方，Android 是 delegated 执行方。

**Android 侧发起**（代码证据：`service/GalaxyConnectionService.kt`，`EnhancedFloatingService.kt`）：
- 用户在 Android 上通过 FloatingWindow/语音 提出请求 → GalaxyConnectionService 路由判断（cross-device ON/OFF）→ 如果 cross-device，通过 AgentRuntimeBridge 发起 handoff → V2 接受并协调 → 结果返回 Android

两条路径在协议层都有对应的 handler，都是真实可用的发起模式，不存在"只有一端才是真正发起方"的限制。

### 2.3 等价性的代码证据

`loop/LoopController.kt` 的互斥调度机制本身就证明了等价性：
- `STOP_CANCELLED_BY_REMOTE`：本地 loop 因远程任务而终止
- `STOP_BLOCKED_BY_REMOTE`：本地 loop 被远程任务阻塞

这两个常量存在本身说明：**系统在运行时两种发起模式是并存的，需要明确的互斥协议来处理竞争**——而不是"只有一种模式是 canonical"。

---

## 3. 哪些模块体现 autonomy、delegation、handoff、reconciliation、continuity

### 3.1 Autonomy（自治）
| 仓库 | 模块 | 代码证据 |
|------|------|---------|
| Android | `loop/LoopController.kt` | 独立 think→act→observe 循环，无需 V2 指令 |
| Android | `local/StagnationDetector.kt` | 自主检测执行停滞 |
| Android | `runtime/LocalInferenceRuntimeManager.kt` | 本地模型管理与推理 |
| V2 | `core/openclawd.py` | 路由决策权威，自主判断本地/跨设备 |
| V2 | `core/agent_factory.py` | 自主 agent 实例化 |

### 3.2 Delegation（委托）
| 仓库 | 模块 | 代码证据 |
|------|------|---------|
| V2 | `core/delegated_flow_entity.py` | flow 生命周期权威 |
| V2 | `core/delegated_runtime_handoff_contract.py` | handoff 合同 |
| V2 | `core/delegated_runtime_execution_tracker.py` | in-flight 执行跟踪 |
| Android | `runtime/DelegatedExecutionTracker.kt` | Android 侧执行跟踪镜像 |
| Android | `runtime/DelegatedActivationRecord.kt` | 委托激活记录 |

### 3.3 Handoff（移交）
| 仓库 | 模块 | 代码证据 |
|------|------|---------|
| V2 | `contracts/handoff_envelope_v2.py` | HandoffEnvelopeV2 合同 |
| V2 | `core/canonical_handoff_path.py` | canonical handoff 路径 |
| V2 | `galaxy_gateway/android/message_builder.py` | 构建 handoff_dispatch 消息 |
| Android | `protocol/AipModels.kt` | `HANDOFF_ENVELOPE_V2` + `HANDOFF_ENVELOPE_V2_RESULT` MsgType |
| Android | `service/GalaxyConnectionService.kt` | `handleHandoffEnvelopeV2()` 处理器 |

### 3.4 Reconciliation（对账）
| 仓库 | 模块 | 代码证据 |
|------|------|---------|
| V2 | `core/android_execution_signal_reconciler.py` | 执行信号对账（PR-13） |
| V2 | `core/android_delegated_signal_ingress.py` | delegated signal 进入路径（PR-16） |
| V2 | `core/android_participant_truth_ingress.py` | 参与者真值对账（PR-4V2） |
| Android | `runtime/ReconciliationSignal.kt` | 7 种对账信号类型（PR-51） |
| Android | `runtime/RuntimeController.kt` | reconciliationSignals SharedFlow（PR-52） |

### 3.5 Continuity（连续性）
| 仓库 | 模块 | 代码证据 |
|------|------|---------|
| V2 | `core/android_v2_continuity_contract.py` | 7 种 continuity 场景合约（PR-L） |
| V2 | `core/flow_continuity_coordinator.py` | continuity 事件统一决策入口 |
| V2 | `core/attached_runtime_session_registry.py` | 会话注册与恢复 |
| Android | `runtime/DurableSessionContinuityRecord.kt` | 持久化会话连续性记录 |
| Android | `runtime/ReconnectRecoveryState.kt` | 重连恢复状态（PR-33） |
| Android | `network/OfflineTaskQueue.kt` | 离线任务队列 |

---

## 4. 为什么系统不能简单理解成"服务端判断 + 客户端执行"

### 理由一：Android 有独立的本地执行闭环
`LoopController` 完全不依赖 V2，可以独立完成 plan→execute→observe 循环。这不是"客户端响应服务端指令"，而是真正的"端侧自治执行"。

### 理由二：V2 自身也有独立的本地执行链
`core/local_execution_chain.py` 明确定义了 V2 本地执行路径，V2 自己就是一个 agent runtime host，不只是协调层。

### 理由三：两端都有各自的 truth ownership
- Android：`AndroidLocalTruthOwnershipCoordinator.kt`、`AndroidParticipantRuntimeTruth.kt`
- V2：`flow_level_truth_ownership.py`、`canonical_session_truth.py`

双端各自持有不同层次的 truth，V2 的 truth 是全局 canonical 权威，Android 的 truth 是本地执行事实——两种 truth 需要通过 reconciliation 协调，而不是简单的"服务端判断"。

### 理由四：路由决策分布在两端
- V2 侧：`OpenClawd` 决定路由（本地 vs 跨设备）
- Android 侧：`GalaxyConnectionService` 决定路由（本地 EdgeExecutor vs AgentRuntimeBridge handoff）

两端各自有路由自主权，这是分布式 agent 系统的典型特征。

---

## 5. 系统定义的最准确表述（代码支撑版本）

基于以上代码分析，系统最准确的定义是：

> **一个以 V2 为 canonical orchestration 权威、Android 为 delegated runtime 执行节点的中心分布式智能体系统。本地链路（V2 本地执行 + Android 本地 LoopController 执行）和跨设备链路（V2→Android delegation + Android→V2 handoff）均为合法主链路，任意侧发起均成立。两端各有独立的 agent runtime 特征、truth ownership 和自治评估能力。**

这个定义与上一版审查"V2 = canonical orchestration center，Android = delegated runtime execution side"的区别在于：
1. 强调了**本地链路也是合法主链路**（不只是降级路径）
2. 强调了**两端各有 agent-like runtime**（Android 不只是"执行端"）
3. 强调了**任意侧发起均成立**（不是单向发起）
