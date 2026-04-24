# 01 系统本体重新识别

## 结论先行

这是一个**中心分布式智能体系统（Centralized Distributed Agent System）**，而不是"服务端判断 + 客户端执行"的传统 C/S 架构。

核心特征：
1. **V2** 是路由/编排中心，持有全局 routing authority 和 canonical orchestration chain
2. **Android** 是具备完整自治能力的分布式执行节点，有自己的 agent runtime loop
3. **两端都可以发起执行**，本地执行路径与跨设备执行路径并存且都合法
4. 两端通过 AIP v3 协议（WebSocket）形成 signal-driven 协作，而非单向调度

---

## 证据 1：Android 具备完整的本地 agent runtime

**代码位置**：`android/app/src/main/java/com/ufo/galaxy/loop/LoopController.kt`

```
/**
 * Orchestrates the full local closed-loop automation pipeline:
 *
 *   natural-language instruction
 *     → model readiness check / download
 *     → screenshot capture
 *     → [LocalPlanner] inference (MobileVLM) via [PlannerFallbackLadder]
 *     → stagnation / plan-repeat guard
 *     → [ExecutorBridge] action dispatch (SeeClick grounding + AccessibilityService)
 *     → post-action screenshot + [PostActionObserver] observation
 *     → [StagnationDetector] step guard
 *     → repeat until completion or budget / timeout / stagnation termination
 */
class LoopController(
    private val localPlanner: LocalPlanner,
    private val executorBridge: ExecutorBridge,
    ...
)
```

`LoopController.execute(instruction: String): LoopResult` 是完整的 agent 执行循环：
- **自主感知**：截屏捕获当前界面
- **自主推理**：MobileVLM 推理下一步动作（LocalPlanner）
- **自主执行**：AccessibilityService 执行点击/输入（ExecutorBridge）
- **自主判断**：StagnationDetector 检测卡死状态并中止

**结论**：Android 端具备 perception → planning → execution → observation 的完整 agent 循环，不依赖 V2 做规划或执行决策。

---

## 证据 2：本地链路与跨设备链路共存且协调

**代码位置**：`android/.../runtime/RuntimeController.kt`

```kotlin
// 远程任务到来时，中止当前本地 Loop 会话并阻塞新的本地会话
fun cancelForRemoteTask() {
    cancelRequested = true
    isRemoteTaskActive = true
}

// 远程任务完成后，解除阻塞，允许本地 Loop 恢复
fun clearRemoteTaskBlock() {
    cancelRequested = false
    isRemoteTaskActive = false
}
```

**代码位置**：`android/.../loop/LoopController.kt`

```kotlin
// 如果当前有远程任务，直接拒绝新的本地会话
if (isRemoteTaskActive) {
    return@withContext LoopResult(
        ...
        stopReason = STOP_BLOCKED_BY_REMOTE,
        ...
    )
}
```

**结论**：`RuntimeController` 是双路径优先级协调者。本地 Loop 和跨设备任务不是互相隔离的两套系统，而是同一个 Android agent 上的两种执行模式，通过 `isRemoteTaskActive` 标志做动态切换。

**为什么"在哪种发起都 OK"**：
- **本地发起**：用户直接在 Android 上输入自然语言指令 → `LoopController.execute()` 运行本地 agent 循环
- **跨设备发起**：V2 通过 WebSocket 发送 `task_assign` / `goal_execution` → `RuntimeController.onRemoteTaskStarted()` 中止本地 Loop → `DelegatedTakeoverExecutor` / `DelegatedRuntimeReceiver` 处理远程任务 → 完成后调用 `onRemoteTaskFinished()` 解锁本地模式

两种发起路径在 Android 端都有完整的处理链路。

---

## 证据 3：V2 也有本地执行链路

**代码位置**：`v2/core/local_execution_chain.py`（类名 + 文件命名）
**代码位置**：`v2/core/local_agent_runtime.py`

```python
"""
LocalAgentRuntime — 端侧 Agent 执行沙盒
...
接收 AgentManifest → 反序列化 → 在本地执行 Thought/Action/Observation 循环。

执行模式:
1. REACT: LLM 驱动的 ReAct Loop
2. SEQUENTIAL: 按顺序执行预定义动作列表
3. AUTONOMOUS: 先发现本地 MCP 工具, 再自主规划执行
"""
```

`v2/core/cross_device_execution_chain.py` 中明确说明：

```python
"""
Both chains are canonical, parallel, and explicitly defined.  Neither is
more "real" than the other.
    LOCAL EXECUTION CHAIN      (core/local_execution_chain.py)
    CROSS-DEVICE EXECUTION CHAIN  ← this module
"""
```

**结论**：V2 也有本地执行链路（LocalAgentRuntime、LocalExecutionChain），不仅仅是跨设备的路由者。V2 本地 + Android 本地 + 跨设备 = 三种合法执行路径。

---

## 证据 4：Android 有完整的 agent-like 自治框架

**代码位置**：`android/.../runtime/` 目录（以下文件均真实存在）：
- `DelegatedRuntimeReadinessEvaluator.kt` — 评估是否 ready 接受委托任务
- `DelegatedRuntimeGovernanceEvaluator.kt` — 评估治理维度
- `DelegatedRuntimeStrategyEvaluator.kt` — 评估策略维度
- `DelegatedRuntimeAcceptanceEvaluator.kt` — 评估是否接受（acceptance）
- `ReconciliationSignal.kt` — reconciliation signal 数据模型
- `RuntimeController.kt` — lifecycle + 双路径协调
- `DelegatedExecutionTracker.kt` — 跟踪委托执行状态
- `AndroidLocalTruthOwnershipCoordinator.kt` — 本地 truth 所有权协调
- `AndroidDelegatedFlowBridge.kt` — 委托执行流与本地执行流的桥接
- `AndroidContractFinalizer.kt` — 合约终结

**代码位置**：`android/.../agent/` 目录：
- `AutonomousExecutionPipeline.kt` — 自治执行管道
- `DelegatedRuntimeUnit.kt` — 委托 runtime 执行单元
- `DelegatedRuntimeReceiver.kt` — 接收委托执行请求
- `DelegatedTakeoverExecutor.kt` — takeover 执行器
- `TakeoverEligibilityAssessor.kt` — 评估是否有资格 takeover
- `AgentRuntimeBridge.kt` — agent runtime bridge
- `EdgeExecutor.kt` — 端侧执行器

**结论**：Android 端拥有 readiness/acceptance/governance/strategy 四层评估框架，拥有 delegated execution unit、takeover executor、truth ownership coordinator 等 agent-level 组件。这不是"执行客户端"，而是一个具备自主判断、接受与否、治理语义的分布式 agent 节点。

---

## 证据 5：系统不能被理解为"服务端判断 + 客户端执行"的证据

**代码**：`android/.../loop/LoopController.kt` 中：

```kotlin
const val STOP_BLOCKED_BY_REMOTE = "blocked_by_remote_task"
```

当远程任务到来时，Android 本地执行被"阻塞"——这说明 Android 有自己持续运行的本地任务，服务端发任务是一种"抢占"而不是正常的"分配"。如果 Android 只是客户端执行，不需要这种抢占机制。

**代码**：`android/.../agent/TakeoverEligibilityAssessor.kt` — 这个类评估 Android 是否"有资格"接受 takeover。如果 Android 只是被动执行端，不需要评估资格。

**代码**：V2 侧 `core/local_agent_runtime.py` 注释：

```python
"""
LocalAgentRuntime is a **device-side execution sandbox**.  It receives
AgentManifest objects that have already been decided and dispatched by the
canonical server-side pipeline...
It must **not** be invoked as a server-side execution planner...
"""
```

这说明 V2 的 LocalAgentRuntime 也被定义为"端侧"执行沙盒，V2 并非只做服务端判断。

---

## 系统本体定义（重新修订）

这个双仓系统是：

> **一个以 V2 为 routing/orchestration 中心、以 Android（及其他节点）为分布式 agent 执行端的中心分布式智能体系统。**

特征：
- **中心**：V2 持有 routing authority（OpenClawd）、canonical execution chain、gateway 协议层
- **分布式**：每个节点（V2 local、Android、其他设备）都有自己的 agent runtime
- **智能体**：每个节点都有 planning、execution、observation 能力或其子集
- **本地与跨设备并存**：同一个节点可以在本地模式和跨设备模式之间动态切换
- **协作而非控制**：两端通过 AIP v3 协议传递 signal（registration, task, result, handoff, takeover），而非主从控制
