# 01 — 系统本体重识别

> **审查方法**：不预设系统角色，仅以真实代码中的类型定义、类名、函数入口、runtime/orchestrator/manager/executor/pipeline 等实质实现为依据，重新得出系统定义。

---

## 一、代码证据采集

### 1.1 Android 侧真实 agent runtime 能力（直接代码证据）

Android 仓库 `app/src/main/java/com/ufo/galaxy/` 下发现如下真实实现：

#### agent/ 目录
| 文件 | 代码级语义 |
|------|-----------|
| `AutonomousExecutionPipeline.kt` | **自主执行管线**。不依赖 V2 中心侧，Android 本地自主完成 plan→execute→observe 循环 |
| `LocalGoalExecutor.kt` | **本地目标执行器**。Android 独立接收 goal，在本地完成整个 goal 执行，不依赖远端编排 |
| `LocalCollaborationAgent.kt` | **本地协作 agent**。本地具备 agent-level 协作语义 |
| `EdgeExecutor.kt` | **边缘执行器**。Android 作为 edge node 的自主执行能力 |
| `DelegatedRuntimeUnit.kt` | **委托 runtime 单元**。接收 V2 handoff 后的完整执行单元 |
| `DelegatedTakeoverExecutor.kt` | **委托接管执行器**。Android 在 takeover 场景下的主动接管能力 |
| `TakeoverEligibilityAssessor.kt` | **接管资格评估器**。Android 本地判断是否具备接管资格 |
| `AgentRuntimeBridge.kt` | **Agent runtime bridge**。将上层 task 与本地 agent runtime 绑定 |
| `DelegatedHandoffContract.kt` | **委托 handoff 合约**。Android 侧持有 handoff 合约语义 |

#### local/ 目录
| 文件 | 代码级语义 |
|------|-----------|
| `LocalLoopExecutor.kt` | **本地循环执行器**。Android 独立执行 ReAct-style thought/action/observation 循环 |
| `LocalLoopReadiness.kt` | **本地循环就绪状态**。本地评估 agent loop 是否就绪 |
| `LocalLoopReadinessProvider.kt` | **本地循环就绪提供者**。提供 readiness 接口 |
| `LocalLoopState.kt` | **本地循环状态**。本地 loop 执行状态机 |
| `PlannerFallbackLadder.kt` | **规划降级梯**。Android 本地规划失败时的多级 fallback 策略 |
| `GroundingFallbackLadder.kt` | **grounding 降级梯**。本地 grounding 多级 fallback |
| `PostActionObserver.kt` | **动作后观察器**。观察动作执行结果，闭合 observe 环 |
| `StagnationDetector.kt` | **停滞检测器**。检测 agent loop 是否陷入 stagnation |

#### runtime/ 目录（Android 侧）
Android 侧的 `runtime/` 目录包含数十个文件（代码证据：目录树），涵盖：
- `AndroidAppLifecycleTransition.kt` — 生命周期状态转换管理
- 其他 runtime 管理模块（Android 真实 runtime 层，不只是 execution stub）

#### 关键类型定义
`AipModels.kt` 中 `source_runtime_posture` 出现在多个 payload 定义中（`GoalExecutionPayload`、`TaskAssignPayload` 等），包括以下合法值：
- `"local"` — 声明本地执行姿态
- `"remote_handoff"` — 声明跨设备 handoff 姿态
- `"fallback_local"` — 降级本地
- `"join_runtime"` — 加入 runtime fabric

这说明 Android 不是"被动接收端"，而是通过 posture 字段**主动声明参与模式**。

---

### 1.2 V2 侧本地 runtime 能力（直接代码证据）

V2 仓库 `core/` 下也存在本地执行能力：

| 文件 | 代码级语义 |
|------|-----------|
| `local_agent_runtime.py` | **本地 agent runtime**（注：文件注释明确标注这是 device-side execution sandbox，接受 AgentManifest 执行 ReAct/Sequential/Autonomous 三种 loop） |
| `core/runtime/source_dispatch_orchestrator.py` | `_try_run_local_execution()` — V2 中心侧自身执行本地任务的函数入口 |
| `local_execution_chain.py` | 本地执行链（作为 audit/projection 辅助模块） |

V2 侧的 `SourceDispatchOrchestrator` 在 `dispatch()` 链路中通过 `source_runtime_posture` 进行路由决策，支持以下分支：
- `local_execution` — V2 本地执行
- `android_bridge_dispatch` — 路由至 Android
- `remote_handoff` — 通过 handoff 路由至目标设备

---

### 1.3 协议层 `source_runtime_posture` 双端对称性

**V2 侧读取**（`source_dispatch_orchestrator.py`）：
```python
is_source_eligible_for_local_execution(source_runtime_posture, coordination_role)
```

**Android 侧写入**（`AipModels.kt` 的 `GoalExecutionPayload`）：
```kotlin
val source_runtime_posture: String? = null,
// 合法值: "local", "remote_handoff", "fallback_local", "join_runtime" 等
```

这是**协议层双端对称性**的直接代码证据：Android 可以主动声明自己的 runtime posture，V2 根据该 posture 选择下一步路由。

---

## 二、基于代码得出的系统定义（纠偏结论）

### PR #793 的错误定义

> "V2 是 canonical orchestration 中心，Android 是 delegated runtime 执行端"

此定义的问题：
1. 将 Android 定位为纯被动执行端，忽略了 Android 拥有的 `AutonomousExecutionPipeline`、`LocalGoalExecutor`、`LocalLoopExecutor` 等完整本地 agent runtime
2. 没有识别出 V2 自身也有 `local_agent_runtime.py`，即 V2 也可以作为本地执行节点
3. 没有识别出 `source_runtime_posture` 双端对称性
4. 隐含了"V2 发起，Android 响应"的固定方向，但代码中任一侧均可通过合法姿态声明发起

### 纠偏后的系统定义（基于代码）

> **Galaxy 系统是一个中心分布式智能体系统（central distributed agent system）。**
>
> - **V2 节点**：持有中心 canonical 状态（true source）、路由决策权、handoff/takeover 合约权威；同时自身具备本地 agent runtime 能力
> - **Android 节点**：具备完整的本地 agent runtime（local loop executor、autonomous pipeline、edge executor、goal executor）；通过 `source_runtime_posture` 声明参与模式，可本地自主执行也可加入 V2 执行织物
> - **链路关系**：本地链路与跨设备链路并存；任一侧均可合法发起，均受统一 UGCP 协议约束
> - **中心节点角色**：V2 不只是调度者，更是状态权威仲裁者（truth authority）；但 Android 在本地执行期间持有本地真值（local truth）
> - **系统特征**：既不是纯中心式，也不是纯对等式；而是以 V2 作为 canonical truth 锚点的分布式 agent 协作体系

---

## 三、系统是否接近"中心分布式智能体系统"

基于代码的回答：**是的，接近，且更接近此定义而非简单的主从模型。**

| 特征 | 代码证据 | 结论 |
|------|---------|------|
| 双端均有真实 runtime | V2: `local_agent_runtime.py`; Android: `LocalLoopExecutor.kt`, `AutonomousExecutionPipeline.kt` | ✅ 成立 |
| 双端均有 agent-like 自治能力 | Android: `EdgeExecutor.kt`, `TakeoverEligibilityAssessor.kt`, `PlannerFallbackLadder.kt` | ✅ 成立 |
| 任一侧均可发起链路 | `source_runtime_posture` 双端写入/读取；Android 有 `LocalGoalExecutor` 本地完整链路 | ✅ 成立 |
| 有统一协议约束双端行为 | `AipModels.kt` MsgType 枚举双端共享；UGCP 协议规则文件双端存在 | ✅ 成立 |
| 中心节点保持 canonical truth | V2: `FlowLevelTruthOwnership`, `CanonicalSessionTruth` | ✅ 成立 |
| 双端有对等 evidence/policy 能力 | Android: readiness/acceptance/governance/strategy 四层评估器（artifact 层）; V2: 对应四层 gate | ⚠️ 骨架成立，wire 信号链路未完整 |
