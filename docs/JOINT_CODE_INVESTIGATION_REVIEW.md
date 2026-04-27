# 双仓真实代码联合调查审查

> **V2 + Android 当前代码状态联合调查，只认真实代码**  
> 仓库：`DannyFish-11/ufo-galaxy-realization-v2` + `DannyFish-11/ufo-galaxy-android`  
> 调查时间：2026-04-27  
> 证据基准：两仓主分支当前代码、测试文件、workflow，不依赖文档

---

## 调查说明

本文不转述 PR #843/844/845/848 的结论，不以文档为主要证据，只认两仓当前真实代码。
每个结论均附关键证据文件与真实代码摘要。

---

## 核心问题 1：这套系统现在是否已经是一个"可被多设备接入和参与的中心式分布式智能体系统"？

### 结论：register/capability_report/task_result 主链真实成立；Android 是真实 participant 但执行上存在功能性前提条件

### 证据

**V2 侧协议层真实成立：**

`galaxy_gateway/android_bridge.py`（CI job 8 中动态验证）：
```python
required = {"device_register", "capability_report", "heartbeat", "task_result", "task_end"}
missing = required - registered
```
这 5 种 message type 均有 handler 注册，CI job 8 `protocol-contract-drift-guard` 是 blocking 验证。

`galaxy_gateway/routes/websocket.py`：路由 `/ws/device/{device_id}` 真实存在，CI job 8 验证其在 FastAPI 路由列表中。

**Android 侧 WebSocket 传输真实成立：**

`app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt`（67KB 实现）：真实 OkHttp WebSocket 客户端，不是 stub。包含重连逻辑、heartbeat、离线队列等。

`app/src/main/java/com/ufo/galaxy/network/OfflineTaskQueue.kt`：持久化离线任务队列，连接恢复后自动重发。

**capability_report 真实携带结构化向量：**

`app/src/main/java/com/ufo/galaxy/capability/AndroidCapabilityVector.kt`：
```kotlin
enum class ExecutionDimension(val wireValue: String) {
    LOCAL_INFERENCE("local_inference"),
    ACCESSIBILITY_EXECUTION("accessibility_execution"),
    PARALLEL_SUBTASK("parallel_subtask"),
    CROSS_DEVICE_COORDINATION("cross_device_coordination")
}
// LOCAL_INFERENCE 条件: settings.localModelEnabled && settings.modelReady
// ACCESSIBILITY_EXECUTION 条件: settings.accessibilityReady && settings.overlayReady
```
capability_report 中的 dimension 是基于 AppSettings 运行时状态动态生成的，不是固定声明。

**多设备参与的真实边界：**

当前系统中"多设备"的含义是：多个 Android 设备可以通过 AIP v3 WebSocket 分别连接到 V2 gateway，每个设备有独立的 device_id 注册、能力上报和任务分发。调度层（`core/scheduling_truth_harness.py`、`core/capability_network_runtime_policy.py`）有结构支持。

但 V2 侧同时调度多设备的测试 (`test_android_runtime_e2e.py`) 仅验证了单设备 `AndroidRuntimeSimulator`，多设备协同在代码层面有调度结构，在测试层面尚未有独立多设备 joint 验证。

---

## 核心问题 2：现在是否已经支持"任意一个接入设备在系统中承担接管/执行角色"？

### 结论：执行角色真实成立，接管角色在代码层面有完整结构但需满足功能前提，"从任意手机完全接管"当前代码层面有条件限制

### 证据

**Android 执行角色真实成立（具体执行条件已知）：**

`app/src/main/java/com/ufo/galaxy/agent/AutonomousExecutionPipeline.kt`：
```kotlin
// handleGoalExecution / handleParallelSubtask 均有以下前提
if (!settings.crossDeviceEnabled) return STATUS_DISABLED result
if (!settings.goalExecutionEnabled) return STATUS_DISABLED result
// 来自 CONTROL_ONLY posture 的任务也被拒绝
if (posture == CONTROL_ONLY) return STATUS_DISABLED with REASON_POSTURE_CONTROL_ONLY
```
执行角色依赖 `crossDeviceEnabled`、`goalExecutionEnabled`、合适的 `source_runtime_posture`。这些是运行时条件而非代码缺失。

**DelegatedTakeoverExecutor 存在真实代码路径：**

`app/src/main/java/com/ufo/galaxy/agent/DelegatedTakeoverExecutor.kt`（20KB）：真实实现。

`app/src/main/java/com/ufo/galaxy/agent/TakeoverEligibilityAssessor.kt`（7KB）：接管资格评估。

**V2 侧 takeover 支持：**

`core/android_v2_continuity_contract.py`、`core/android_delegated_runtime_lifecycle_coordinator.py` 等文件真实存在。`core/takeover_tracking.py` 提供运行时跟踪。

**"从任意手机接管"当前真实限制：**

1. 接管需满足 `TakeoverEligibilityAssessor` 评估通过
2. 本地 AI 能力（planning/grounding）在默认状态下是 NoOp（见核心问题 4）
3. 接管后的 local planning 调用会返回错误而不是真实计划
4. 调度角色、控制角色（作为 control plane 发起任务）：当前只在 V2 侧（desktop/server）成立，Android 侧作为调度发起者的路径未见真实激活

---

## 核心问题 3：这套系统现在到底有没有"真实记忆"？

### 结论：有多层真实持久化存储，但主 truth authority 仍是 in-memory ring buffer；continuations 跨重启重绑定未形成完整闭环

### 具体分层

**已真实成立（durable）：**

`core/session_truth_snapshot.py`：文件级 JSON 快照，atomic write-then-rename，process-level singleton，默认路径 `data/session_truth_snapshot.json`。每次 `record()` 追加时写文件。**这是 PR-1 后新增的真实 durable 路径。**

`core/task_lifecycle_persistence.py`：inflight task lifecycle 快照，同样 file-backed，write-then-rename 原子写。`InFlightTaskDisposition` 枚举决定恢复策略（RESUMABLE/REPLAY_ONLY/REISSUABLE/TERMINAL_ON_INTERRUPT）。

`core/runtime_restart_recovery.py`：`RuntimeRestartRecoveryCoordinator` 在 startup 时恢复 MeshSession 和 BodyMesh 状态。

`core/replay_audit_persistence.py`：replay 审计持久化，`DurableAuditStore` 可 attach 到 session truth runtime 作为 audit sink。

**仍主要是 in-memory（ring buffer 是主 authority）：**

`core/canonical_session_truth.py`（49KB）：
```python
# ring buffer 是 runtime truth 的主来源
# set_audit_store() 挂载 durable audit sink，但 runtime.record() 主路径仍先写 ring buffer
```
明确说明：`set_audit_store` 是 audit observational sink，不是 truth authority 替代。

**Continuations 跨重启重绑定：**

`core/runtime_restart_recovery.py` 的非目标明确写道：
```python
# Non-goals (intentionally ephemeral)
# * In-flight task queues — tasks pending in memory-only queues at the time
#   of restart.  These must be replayed by the task source.
```
task lifecycle persistence 提供 disposition 分类（RESUMABLE/REPLAY_ONLY 等），但 continuation/waiter 的跨重启重绑定在 coordinator 层尚无完整证据显示已形成闭环。

**Android 侧记忆：**

`app/src/main/java/com/ufo/galaxy/memory/`：存在 memory 目录（结构存在）。`app/src/main/java/com/ufo/galaxy/history/`：history 目录（存在）。`OfflineTaskQueue.kt` 持久化离线队列。Android 侧的 local state 主要是 in-process + 持久化队列，无证据有 durable session truth。

**当前记忆定性：**

- Runtime working memory（ring buffer）：✅ 真实
- Task lifecycle snapshot（file-backed, write-on-change）：✅ 真实（PR-1 后）
- Session truth snapshot（file-backed, append-on-record）：✅ 真实（PR-1 后）
- Continuation 跨重启重绑定：⚠️ 结构支撑有，闭环未完全证明
- 统一长期记忆主链（unified long-term memory）：❌ 尚无 — RAGMemory 是知识/经验层，不是 session truth 主链

---

## 核心问题 4：这套系统现在到底有没有"真实认知能力"？

### 结论：orchestration/routing/provider-selection 真实成立；capability gate 在主路径默认为 audit-not-reject；local AI（planning/grounding/inference）默认 NoOp 未成立

### orchestration / routing / provider selection：真实成立

`core/multi_llm_router.py`：多 LLM provider routing 真实。
`core/capabilities/canonical_dispatcher.py`：统一 dispatch 路径，支持 MCP/Skill/Node/GitHub 层。
`core/openclawd.py`：`process()` pipeline — ingest → continuum → execution_path determination (local/cross_device/hybrid/none) → manifest。真实运行。

### capability gate 当前默认语义：audit-not-reject（GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT 未完全关闭）

`core/mainline_routing_enforcement.py` 第 380 行：
```python
def enforce_explicit_route_capability_gate(
    ...
    raise_on_mismatch: bool = False,   # 默认 False = audit only
```

`core/openclawd.py` 第 3725 行（真实调用点）：
```python
_cap_audit = enforce_explicit_route_capability_gate(
    device_id=effective_device_id,
    required_capabilities=required_capabilities,
    calling_site="openclawd.process",
    # raise_on_mismatch 未传 = False = 遇到 mismatch 只记录 AUDITED_BYPASS，不阻断
)
```
这意味着 capability 不满足时，dispatch 继续进行，只是 audit 记录中标记为 `AUDITED_BYPASS`。`capability_enforcement_hardener.py` 存在更严格的 STRICT 模式，但其 `enforce_mainline_capability_gate()` 未被主路径 `send_gateway_command` 调用。

`core/openclawd.py` `send_gateway_command` 函数（第 7556 行）：不调用任何 capability gate。

**CI job 5** 验证 hardener 的 unit 行为，但那是 unit test，不等于主链默认已 enforce。

### local AI / planning / grounding：默认 NoOp，STRUCTURAL_ONLY 已被系统自身标记

`core/canonical_capability_status.py`：
```python
LOCAL_AI_IS_STRUCTURAL_ONLY_STATUS: str = (
    "STATUS::LOCAL_AI_STRUCTURAL_ONLY_V1: "
    "Android local AI / on-device inference (local_ai, local_grounding, "
    "local_planner, on_device_inference) is classified as STRUCTURAL_ONLY. "
    "The default implementations are NoOp stubs that return errors without "
    "performing inference.  This capability is NOT active mainline..."
)
```

Android 侧代码验证：
```kotlin
// LocalPlannerService.kt - NoOpPlannerService（默认实现）
override fun loadModel(): Boolean = false
override fun plan(...) = PlanResult(steps=emptyList(), error="MobileVLM planner not available: model not loaded")

// LocalGroundingService.kt - NoOpGroundingService（默认实现）  
override fun loadModel(): Boolean = false
override fun ground(...) = GroundingResult(x=0, y=0, confidence=0f, error="SeeClick grounding not available: model not loaded")
```

`AndroidCapabilityVector.kt`：
```kotlin
// LOCAL_INFERENCE 只有在 settings.localModelEnabled && settings.modelReady 时才进入维度集
if (settings.localModelEnabled && settings.modelReady) {
    add(ExecutionDimension.LOCAL_INFERENCE)
}
```
默认 `modelReady=false`，所以 `LOCAL_INFERENCE` 维度默认不在 capability_report 里。

**tool use / external knowledge / execution feedback loop：真实但需外部依赖**

MCP dispatch 路径（`core/mcp_loader.py`、`core/mcp_gateway.py`）真实。技能调度（`core/skill_loader.py`）真实。Node 工具调用真实。这些都是 active mainline 能力。

---

## 核心问题 5：知识库、外部知识、学术论文等资源在当前系统中能以什么方式被使用？

### 结论：retrieval/ingestion 路径真实存在，是辅助链而非主运行路径；local grounding 需要模型才能成立

**Academic retrieval 路径真实：**

`core/academic_retrieval.py`：
```python
# 三个规范入口点
search(query, source, max_results, ingest)  # 查询 arXiv/Semantic Scholar/PubMed/IEEE Xplore
ingest_paper(paper)                          # 注入单篇论文到 Knowledge Core
recall(query, top_k)                         # 从 Knowledge Core 检索
```
能力总线注册：`academic__search`、`academic__ingest`、`academic__recall`。

**RAGMemory / Knowledge Core 真实：**

`core/rag_memory.py`：RAGMemory 包含经验日志、知识 RAG、对话记忆、学习积累四层。写入路径优先 Node_105（in-process），兼容 Node_72、Node_80（Memos）。

**诚实判断：**

- "系统可以利用知识库和论文增强自身能力"这句话当前在有限意义上成立：agent 可以通过 `academic__search` 检索论文，通过 `recall` 检索已注入知识，并将结果注入到 system_prompt
- 这是辅助路径（agent 主动调用 tool），不是自动 grounding
- 检索后的 grounding（把论文内容转化为 Android UI 动作）需要本地 AI，而本地 AI 默认 NoOp
- 当前最真实的说法：知识检索工具真实可用，知识对 LLM 提示的增强真实可用，但"用论文增强 Android 上的本地执行"这一链路目前不成立

---

## 核心问题 6：模型端现在统一到了什么程度？

### 结论：V2 侧 provider routing 统一真实；Android 侧 local intelligence 默认 NoOp、capability reporting 与 modelReady 绑定但 modelReady 默认 false；两仓模型端"统一"不能诚实地说已达到

### V2 侧 provider routing / canonical path：真实统一

`core/multi_llm_router.py`：多 provider 路由真实。
`core/capabilities/canonical_dispatcher.py`：canonical dispatch path 统一。
CI 保护：`release_blocking_gate.py` + `dual_repo_integration.yml` job 6 blocking。

### Android 侧 local intelligence runtime：默认 NoOp，未统一

当前真实状态：
- `NoOpPlannerService` 是 DI 默认实现
- `NoOpGroundingService` 是 DI 默认实现
- `MobileVlmPlanner.kt` 存在（目标 MobileVLM V2-1.7B + llama.cpp/MLC-LLM backend），但是实现，不是默认激活的 runtime
- Local inference 仍依赖 localhost HTTP 外部进程（llama.cpp/MLC-LLM server 需要单独启动）
- `AndroidCapabilityVector.from()` 中，`LOCAL_INFERENCE` 维度只有在 `modelReady=true` 时才报告

### capability reporting 与 runtime readiness 的一致性：**部分一致**

`AndroidCapabilityVector` 的设计已经把 capability 声明绑定到 runtime state（`modelReady`、`accessibilityReady` 等），因此不会错误地声明 LOCAL_INFERENCE 能力。

但这种一致性是"我不撒谎"而不是"我真的具备"——`modelReady` 默认 false 意味着 LOCAL_INFERENCE 默认不声明，能力声明诚实，但实际 local AI 运行时默认不就位。

### 当前是否能诚实说"模型端已经统一"：**不能**

差距：
1. Android local intelligence runtime 没有 manager，没有统一 lifecycle
2. 模型权重（MobileVLM / SeeClick）不是受管资产，没有 manifest/checksum/下载逻辑
3. V2 侧是 managed LLM router，Android 侧是"如果你手动配好了 localhost 就能用"
4. 两仓 model capability 状态没有同步机制

---

## 核心问题 7：只靠当前这整套系统流程，能力上限大概到哪里？

### 已经超过了什么层级

**1. 单模型聊天**：已超过。有 multi-LLM routing、provider selection、工具调用链、技能系统。

**2. 单设备 agent**：已超过。有真实的跨设备 dispatch（V2 → Android），register/capability_report/task_assign/task_result 主链成立，Android 可以作为真实执行 participant（在 accessibility 权限就位的前提下）。

**3. 普通工具调用器**：已超过。有 MCP/Skill/Node 三层工具生态，有调度路由，有 capability gate 结构，有 observability 层。

**4. 无持久化 agent**：已超过。task lifecycle snapshot、session truth snapshot、replay audit persistence、offline task queue 均有真实文件持久化实现。

### 还明显没达到什么层级

**1. 统一长期记忆智能体**：主 truth authority 仍是 in-memory ring buffer，continuations 跨重启重绑定未形成完整闭环，session truth 快照是 append-style observational backup 而非 durable truth authority。

**2. 完全成熟多设备自治平台**：
   - local AI（planning/grounding）默认 NoOp，Android 作为"智能"participant 需要手工配置模型
   - 多设备协同的 joint integration test 仍是 in-process simulator（`AndroidRuntimeSimulator`），不是真实 WebSocket level
   - capability gate 在主路径默认 audit-not-reject（GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT 存在）

**3. 完全闭环的分布式 AI 系统**：mesh/federation/WebRTC 明确分类为 STRUCTURAL_ONLY 或 EXPERIMENTAL，不是 active mainline

### 当前真实能力边界

**已真实成立（可验证）：**
- AIP v3 协议层 V2 ↔ Android 通信
- V2 orchestration/routing 主链（MCP + Skill + Node 工具层）
- Android 设备作为执行 participant（当 accessibility/overlay 就位时）
- 任务 lifecycle 和 session truth 的文件级持久化
- Capability status 显式分类（STRUCTURAL_ONLY vs ACTIVE_MAINLINE 已区分）
- 多 LLM provider routing

**需要条件才能成立：**
- Android local AI（需要手工配置 localhost model server + `modelReady=true`）
- Android 接管执行（需要 crossDeviceEnabled + goalExecutionEnabled + 合适的 source posture）
- Continuations 跨重启恢复（task disposition 有，完整 rebind 未证明）

**明确不成立：**
- Local AI 默认激活
- Mesh/federation/WebRTC 作为主链能力
- Android 侧 CI 覆盖 WebSocket 协议/runtime 级验证（android-ci.yml 只有 unit test + build + lint）
- 双仓 joint integration 超过 in-process simulator 级别的网络验证

---

## 摘要表

| 能力维度 | 真实状态 | 证据文件 |
|---------|---------|---------|
| AIP v3 协议主链（V2侧） | ✅ ACTIVE_MAINLINE | `android_bridge.py`, CI job 8 |
| Android WebSocket 客户端 | ✅ 真实 | `GalaxyWebSocketClient.kt` (67KB) |
| Android capability_report（含 vector） | ✅ 真实（绑定运行时状态） | `AndroidCapabilityVector.kt` |
| V2 dispatch / routing | ✅ ACTIVE_MAINLINE | `canonical_dispatcher.py`, `openclawd.py` |
| Capability gate（主路径）| ⚠️ 默认 audit-not-reject | `mainline_routing_enforcement.py` L380 |
| Session truth snapshot（file-backed）| ✅ 真实（PR-1后）| `session_truth_snapshot.py` |
| Task lifecycle persistence | ✅ 真实 | `task_lifecycle_persistence.py` |
| Continuation 跨重启重绑定 | ⚠️ 结构有，闭环未完全证明 | `runtime_restart_recovery.py` |
| Academic retrieval / RAGMemory | ✅ 真实（辅助链）| `academic_retrieval.py`, `rag_memory.py` |
| Local AI planner（Android）| ❌ 默认 NoOp | `LocalPlannerService.kt` |
| Local AI grounding（Android）| ❌ 默认 NoOp | `LocalGroundingService.kt` |
| Android local intelligence runtime manager | ❌ 不存在 | — |
| Mesh / Federation / WebRTC | ❌ STRUCTURAL_ONLY/EXPERIMENTAL | `canonical_capability_status.py` |
| Android CI WebSocket/E2E 验证 | ❌ 不存在 | `android-ci.yml`（仅 unit test + build） |
| 双仓 joint integration test（真实网络层）| ❌ 仍是 in-process simulator | `test_android_runtime_e2e.py` |

---

## 附：关键证据文件路径索引

### V2 仓库
- `core/canonical_capability_status.py` — 能力状态分类注册表
- `core/capability_enforcement_hardener.py` — STRICT 模式 hardener（未挂主链）
- `core/mainline_routing_enforcement.py` — 主链 capability gate（默认 raise_on_mismatch=False）
- `core/openclawd.py` L3725 — capability gate 实际调用点
- `core/openclawd.py` L7556 — `send_gateway_command`（无 capability gate）
- `core/canonical_session_truth.py` — session truth ring buffer + durable audit sink
- `core/session_truth_snapshot.py` — 文件级 session truth 快照
- `core/task_lifecycle_persistence.py` — task lifecycle 持久化
- `core/runtime_restart_recovery.py` — 重启恢复（明确标注哪些是 ephemeral）
- `core/academic_retrieval.py` — 学术检索工具
- `core/rag_memory.py` — 知识/记忆 RAG 系统
- `galaxy_gateway/android_bridge.py` — V2 侧协议 handler
- `tests/integration/test_android_runtime_e2e.py` — E2E 测试（in-process simulator）
- `.github/workflows/dual_repo_integration.yml` — 双仓集成 CI（8 个 job）

### Android 仓库
- `app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt` — WebSocket 客户端
- `app/src/main/java/com/ufo/galaxy/capability/AndroidCapabilityVector.kt` — 能力向量
- `app/src/main/java/com/ufo/galaxy/inference/LocalPlannerService.kt` — 本地规划（NoOp 默认）
- `app/src/main/java/com/ufo/galaxy/inference/LocalGroundingService.kt` — 本地 grounding（NoOp 默认）
- `app/src/main/java/com/ufo/galaxy/agent/AutonomousExecutionPipeline.kt` — 执行管线
- `app/src/main/java/com/ufo/galaxy/agent/DelegatedTakeoverExecutor.kt` — 接管执行器
- `.github/workflows/android-ci.yml` — Android CI（仅 unit test + build + lint）
