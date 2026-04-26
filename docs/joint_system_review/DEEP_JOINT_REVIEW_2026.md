# Galaxy-Nexus × Galaxy-Android 双仓联合深度系统审查

> **审查范围**：`DannyFish-11/ufo-galaxy-realization-v2`（V2，Python）+ `DannyFish-11/ufo-galaxy-android`（Android，Kotlin）
>
> **审查方法**：基于两个仓库真实代码，不以文档为主要依据。对每个判断提供代码坐标作为证据。
>
> **审查日期**：2026-04-26
>
> **审查目的**：为后续 PR 提供基于真实代码的系统状态基准，消除对完成度的模糊认知。

---

## 图例说明

| 标记 | 含义 |
|------|------|
| ✅ **RUNTIME-LIVE** | 真实运行时链路，代码已接通并在主链上生效 |
| ⚠️ **QUASI-MAINLINE** | 代码实质存在，主链骨架完整，但有关键信号流断层或未默认强制 |
| 🔷 **ADDITIVE-NOT-ENFORCED** | 模块存在且功能正确，但非默认激活，需主动调用才有效 |
| 🔶 **STRUCTURAL-ONLY** | 代码文件存在，但 runtime 路径未接通或默认 NoOp |
| ❌ **MISSING / NOT-BUILT** | 明确缺失，没有可运行的实现 |

---

## 第一章：双仓真实系统边界与 Canonical Main Paths

### 1.1 系统整体定位

这套系统是**以 V2（Python/FastAPI）为编排中心、以 Android App 为 delegated runtime 执行端的跨端任务执行平台**。

核心设计思路：V2 持有全局 canonical 状态（UDM、任务生命周期、会话真值），Android 负责本地设备执行（UI 自动化、传感器、本地 AI），两端通过 WebSocket/AIP v3 协议通信。

这不是一个对等网络（peer mesh）。V2 是中心，Android 是 delegated 执行端。

### 1.2 各侧真实权责边界

**V2 侧（代码坐标）**

| 职责 | 模块 | 状态 |
|------|------|------|
| 设备注册 canonical 写入 | `core/unified/device_manager.py`（UDM） | ✅ RUNTIME-LIVE |
| 任务派发 & 结果等待 | `galaxy_gateway/routing/dispatch.py::dispatch_to_websocket()` | ✅ RUNTIME-LIVE |
| Android 消息分发 | `galaxy_gateway/android_bridge.py` | ✅ RUNTIME-LIVE |
| AIP v3 协议强制执行 | `galaxy_gateway/websocket_handler.py`（parse_message_strict） | ✅ RUNTIME-LIVE |
| 会话 truth 维护 | `core/canonical_session_truth.py`（CanonicalSessionTruthRuntime） | ⚠️ QUASI-MAINLINE |
| 多路 Android 信号统一入口 | `core/unified_runtime_truth_ingress.py` | 🔷 ADDITIVE-NOT-ENFORCED |
| capability routing gate | `core/capability_routing_gate.py` | 🔷 ADDITIVE-NOT-ENFORCED |
| WebRTC signaling proxy | `galaxy_gateway/webrtc_proxy.py` | 🔶 STRUCTURAL-ONLY |
| mesh/constellation runtime | `core/constellation_runtime.py` | 🔶 STRUCTURAL-ONLY |
| Android CI | — | ❌ MISSING |

**Android 侧（代码坐标）**

| 职责 | 模块 | 状态 |
|------|------|------|
| WebSocket 连接 + 重连 | `network/GalaxyWebSocketClient.kt`（67KB） | ✅ RUNTIME-LIVE |
| 离线任务队列 | `network/OfflineTaskQueue.kt` | ✅ RUNTIME-LIVE |
| AIP v3 消息类型 | `protocol/AipModels.kt` | ✅ RUNTIME-LIVE |
| 设备注册握手 | `GalaxyWebSocketClient.kt` 内注册逻辑 | ✅ RUNTIME-LIVE |
| 任务执行 + 结果上报 | `agent/DelegatedRuntimeUnit.kt` + `GalaxyWebSocketClient.kt` | ✅ RUNTIME-LIVE |
| 离线重连后 replay | `network/OfflineTaskQueue.kt` | ✅ RUNTIME-LIVE |
| readiness/acceptance 评估 | `runtime/DelegatedRuntimeReadinessEvaluator.kt` 等 | ⚠️ QUASI-MAINLINE |
| reconciliation signal 发送 | `protocol/ReconciliationSignal.kt` + V2 handler | ⚠️ QUASI-MAINLINE |
| 本地 grounding | `inference/LocalGroundingService.kt`（NoOpGroundingService 默认） | 🔶 STRUCTURAL-ONLY |
| 本地 planner | `inference/LocalPlannerService.kt` | 🔶 STRUCTURAL-ONLY |
| WebRTC P2P | `webrtc/` 包 | 🔶 STRUCTURAL-ONLY |
| 单元测试 CI | `.github/` 目录仅有 PR 模板 | ❌ MISSING |

### 1.3 双仓 Canonical Main Paths

**真实主链（V2 → Android → V2 结果闭环）**

```
1. 用户请求进入 V2
2. OpenClawd.send_gateway_command() → dispatch_to_websocket()
3. 构建 AIP v3 command 消息，写入 task_events[task_id] = asyncio.Event()
4. 通过 GatewayWSManager 的 active_connections 发送到 Android WebSocket
5. Android GalaxyWebSocketClient 接收消息
6. Android 执行（DelegatedRuntimeUnit / AutonomousExecutionPipeline）
7. Android 通过 GalaxyWebSocketClient.sendJson() 发回 task_result
8. galaxy_gateway/websocket_handler.py 接收，调用 handle_response()
9. device_router.handle_task_result() → task_events[task_id].set()
10. dispatch_to_websocket() 的 await event 解阻塞，返回结果
```

**代码证据**：
- 步骤 3 和 10：`galaxy_gateway/routing/dispatch.py:91-216`（dispatch_to_websocket，asyncio.Event 等待模式）
- 步骤 4：`galaxy_gateway/websocket_handler.py`（GatewayWSManager.active_connections）
- 步骤 8-9：`galaxy_gateway/websocket_handler.py:580-600`（handle_response → handle_task_result）

**结论**：主链 ✅ RUNTIME-LIVE

**准主链（delegated canonical path）**

```
1. V2 DelegatedFlowEntity → HandoffEnvelopeV2 发送给 Android
2. Android RuntimeController 接收 → DelegatedRuntimeUnit 执行
3. Android DelegatedExecutionSignal（ACK/PROGRESS/RESULT）→ GalaxyWebSocketClient 发回
4. android_bridge.py → handle_delegated_execution_signal
5. core/android_delegated_signal_ingress.py ingest → DelegatedRuntimeExecutionTracker 更新
6. handoff_envelope_v2_result → handle_handoff_v2_result → android_handoff_v2_response_ingress
```

**代码证据**：
- `galaxy_gateway/android_bridge.py:671`（DELEGATED_EXECUTION_SIGNAL 注册）
- `galaxy_gateway/android_bridge.py:677-680`（HANDOFF_ACK/RESULT/FAILURE/ENVELOPE_V2_RESULT 全部注册）
- `core/android_delegated_signal_ingress.py`
- `core/android_handoff_v2_response_ingress.py`

**结论**：⚠️ QUASI-MAINLINE（框架完整，但 V2 端 DelegatedFlowEntity 触发 HandoffEnvelopeV2 的条件是否默认激活未验证）

**不是主链的路径**

| 路径 | 状态 | 说明 |
|------|------|------|
| WebRTC P2P 媒体通道 | 🔶 STRUCTURAL-ONLY | 仅 signaling proxy，无 direct media 接通证明 |
| multi-node mesh runtime | 🔶 STRUCTURAL-ONLY | ConstellationRuntime 框架存在，无真实多节点验证 |
| Android local AI grounding | 🔶 STRUCTURAL-ONLY | NoOpGroundingService 默认激活 |
| galaxy federation | 🔶 STRUCTURAL-ONLY | `core/galaxy_federation.py` 存在但无 runtime 接入证明 |

---

## 第二章：中心分布式智能体系统认知

### 2.1 这套系统是否构成"中心式分布式智能体系统"

**结论：是中心-外围架构，但"分布式"的程度有限。**

**真实的中心-外围关系**：
- V2 是唯一的 canonical orchestration 中心，持有 UDM（设备注册表）、任务生命周期、真值权威
- Android 是 delegated runtime 执行端，不持有 canonical 状态权威
- Android 有本地 truth（AndroidLocalTruthOwnershipCoordinator.kt），但这是 execution-local truth，不是 canonical system truth

**Android 的自治能力（代码层面）**：
- ✅ `AutonomousExecutionPipeline.kt`：具备本地自主执行管线
- ✅ `OfflineTaskQueue.kt`：具备离线缓冲和重连 replay
- ✅ `DelegatedTakeoverExecutor.kt`：具备接管执行的能力结构
- ⚠️ 但所有这些能力的激活前提是 V2 已经授权（发出 handoff/task_assign）
- 🔶 Android 无法在 V2 完全不可达时自主决定新目标，只能缓冲和重放已接受的任务

**multi-node mesh / federation / constellation 真实状态**：
- `core/mesh/` 目录：有 mesh 相关代码（mesh_session_lifecycle 等）
- `core/constellation_runtime.py`：ConstellationRuntime 框架，调度 DAG
- `core/galaxy_federation.py`：存在但无注入点证明
- **结论**：这些是 🔶 STRUCTURAL-ONLY。代码存在、框架完整，但没有真实的多节点 runtime 验证，`mesh_topology` 消息类型有处理器但实际行为依赖 Node 服务实际运行。

**系统当前更准确的定位**：
> **一套中心单点（V2）+ 单一 delegated runtime（Android）的有限分布式任务执行系统。**
> mesh/federation/constellation 是路线图层，不是默认激活的运行时能力。

---

## 第三章：跨设备本地链路与 Android ↔ V2 实际闭环

### 3.1 register / capability_report / heartbeat / liveness

| 流程 | V2 侧代码 | Android 侧代码 | 状态 |
|------|-----------|----------------|------|
| device_register | `android/handlers/registration.py::handle_device_register()` → UDM upsert | `GalaxyWebSocketClient.kt` 发送 DEVICE_REGISTER | ✅ RUNTIME-LIVE |
| capability_report | `android/handlers/capability_report.py::handle_capability_report()` | `GalaxyWebSocketClient.kt` | ✅ RUNTIME-LIVE |
| heartbeat | `android/handlers/heartbeat.py::handle_heartbeat()` | `GalaxyWebSocketClient.kt` 心跳计时器 | ✅ RUNTIME-LIVE |
| liveness（连接断开检测） | `websocket_handler.py` WebSocket close 处理 + UCM | `GalaxyWebSocketClient.kt` 重连逻辑 | ✅ RUNTIME-LIVE |

### 3.2 command dispatch / websocket transport / result return

| 流程 | 代码坐标 | 状态 |
|------|----------|------|
| V2 → Android 命令下发 | `dispatch_to_websocket()` + `task_events[task_id] = asyncio.Event()` | ✅ RUNTIME-LIVE |
| Android → V2 结果回传 | `websocket_handler.py::handle_response()` → `handle_task_result()` | ✅ RUNTIME-LIVE |
| task_result await 解阻塞 | `dispatch_to_websocket()::await asyncio.wait_for(event.wait(), timeout)` | ✅ RUNTIME-LIVE |

### 3.3 task_result → awaiter → continuation 闭环

这是 **✅ RUNTIME-LIVE** 的关键闭环。代码证据：

```python
# galaxy_gateway/routing/dispatch.py
event = asyncio.Event()
task_events[task_id] = event
# ... send over websocket ...
result = await asyncio.wait_for(event.wait(), timeout=timeout_s)
```

当 Android 回传 task_result 时，`handle_response()` 调用 `device_router.handle_task_result(task_id, payload)`，后者 `event.set()`，解阻塞。

**关键限制**：
- `task_events` 是 in-process dict（重启后丢失）
- `event` 是 in-memory asyncio.Event（不跨进程）
- V2 重启后，所有 in-flight tasks 的 awaiter 丢失，Android 回传的结果无法被消费

### 3.4 offline queue / reconnect replay / continuity signal

| 能力 | 代码坐标 | 状态 |
|------|----------|------|
| Android 离线队列 | `network/OfflineTaskQueue.kt`（持久化到本地存储） | ✅ RUNTIME-LIVE |
| Android 重连后 replay | `GalaxyWebSocketClient.kt`（重连触发 queue drain） | ✅ RUNTIME-LIVE |
| V2 continuity 分类 | `core/android_v2_continuity_contract.py`（7 种场景的策略定义） | ⚠️ QUASI-MAINLINE |
| V2 restart 后 recovery | `core/runtime_restart_recovery.py` | ⚠️ QUASI-MAINLINE |

**关键问题**：`android_v2_continuity_contract.py` 是策略定义（additive，包含大量 docstring 和 sentinel 常量），真实 runtime 路径是否默认调用这些策略未确认。continuity 场景覆盖完整，但属于 ⚠️ QUASI-MAINLINE。

---

## 第四章：Truth / Continuity / Recovery / Session / Task Lifecycle

### 4.1 V2 CanonicalSessionTruthRuntime 真实状态

**代码**：`core/canonical_session_truth.py`

**实际行为**：
- `CanonicalSessionTruthRuntime` 是进程内对象，使用 Python dict 维护 session truth
- 可选地附加 `DurableAuditStore`（`attach_durable_store(store)` 方法存在）
- `wire_durable_audit_store()` 在 `core/startup.py:153` 定义，在 `startup.py:824` 被调用

**关键事实**：
```python
# core/startup.py
results["durable_audit_store"] = wire_durable_audit_store()
if results["durable_audit_store"]["status"] == "ok":
    # 只有在 ok 时才 wire
```

**结论**：`DurableAuditStore` 在启动时尝试 wire，**但它的成功与否取决于环境配置**（store_path 存在与否）。session truth 的持久化是条件性的，不是默认保证的。

**V2 restart 后 truth 状态**：
- in-process dict 丢失 ✅ 确认
- `DurableAuditStore` 持久化内容可能幸存，但读取恢复路径未在关键代码中强制

**结论**：⚠️ QUASI-MAINLINE

### 4.2 Android Continuity vs V2 Continuity

| 维度 | Android | V2 |
|------|---------|-----|
| 离线任务队列 | ✅ `OfflineTaskQueue.kt`（文件级持久化） | ⚠️ in-memory task_events dict |
| session identity 持久化 | ✅ `SharedPreferences/Room`（本地持久化） | ⚠️ 进程内注册表 + 可选 DurableAuditStore |
| restart 后恢复 | ✅ Android 进程重启后 session_id 可恢复 | ⚠️ V2 重启后 session registry 需重建 |

**结论**：Android 在 continuity 持久性上确实比 V2 更 durable（offline queue 是文件级，不是内存级）。

### 4.3 truth path 层次

| 路径 | 性质 | 代码坐标 |
|------|------|----------|
| `handle_device_register()` → UDM.upsert() | ✅ CANONICAL | `android/handlers/registration.py` |
| `handle_delegated_execution_signal()` → execution tracker | ✅ CANONICAL | `android/handlers/delegated_signal.py` |
| `ingest_android_runtime_state_update()` | 🔷 ADDITIVE（未被 bridge 调用） | `core/unified_runtime_truth_ingress.py` |
| websocket_handler 直接 state mutation（line 588 区域） | ⚠️ BYPASS | `galaxy_gateway/websocket_handler.py` |

**关键发现**：`unified_runtime_truth_ingress.py` 定义了 canonical 单一入口函数，但 `android_bridge.py` 的 handlers 直接调用各子模块（`android_delegated_signal_ingress`、`android_participant_truth_ingress`、`android_handoff_v2_response_ingress`），**绕过了 `ingest_android_runtime_state_update()` 统一入口**。这是 🔷 ADDITIVE-NOT-ENFORCED 的典型例子。

### 4.4 result idempotency / replay safety

| 能力 | 代码坐标 | 状态 |
|------|----------|------|
| flow 级别 idempotent replay 吸收 | `core/flow_aware_result_convergence.py::absorb_replay_result_idempotently()` | ⚠️ QUASI-MAINLINE |
| task_result 去重 | `flow_aware_result_convergence.py`（first-write-wins 语义） | ⚠️ QUASI-MAINLINE |
| 跨重启幂等（持久化去重 set） | 无专用持久化去重机制 | 🔶 STRUCTURAL-ONLY |

**结论**：replay safety 在进程生命周期内成立（first-write-wins），但跨 V2 重启的幂等性未保证。

---

## 第五章：Provider / Model / Local AI / Multimodal / Extension 能力完成度

### 5.1 V2 Provider Routing

| 能力 | 代码 | 状态 |
|------|------|------|
| LLM multi-provider routing | `core/multi_llm_router.py` | ✅ RUNTIME-LIVE |
| OpenClawd LLM 调用 | `core/openclawd.py`（5000+ 行，主 orchestrator） | ✅ RUNTIME-LIVE |
| provider 选择（API key 配置） | `core/unified_config.py` | ✅ RUNTIME-LIVE |
| Model topology 配置 | `core/model_topology/` | ⚠️ QUASI-MAINLINE |

### 5.2 Android Local AI 能力

**关键代码证据**（来自 `inference/LocalGroundingService.kt`）：

```kotlin
class NoOpGroundingService : LocalGroundingService {
    override fun loadModel(): Boolean = false
    override fun isModelLoaded(): Boolean = false
    override fun ground(...): LocalGroundingService.GroundingResult =
        LocalGroundingService.GroundingResult(
            x = 0, y = 0, confidence = 0f,
            element_description = "",
            error = "SeeClick grounding not available: model not loaded"
        )
}
```

**结论**：`LocalGroundingService` 是接口（interface），`NoOpGroundingService` 是**默认实现**，直接返回错误。SeeClick grounding 在当前代码中**不可用**，这是 🔶 STRUCTURAL-ONLY。

`LocalPlannerService.kt` 也存在，同样需要检查是否有 NoOp 默认实现（推测类似）。

### 5.3 Vision / Multimodal / WebRTC 能力

| 能力 | Android 侧 | V2 侧 | 状态 |
|------|-----------|-------|------|
| 截图 + 上传 | `android/handlers/vision.py` 有处理 | `vision/` pipeline | ⚠️ QUASI-MAINLINE |
| WebRTC P2P 媒体 | `webrtc/` 包存在 | `webrtc_proxy.py`（signaling only） | 🔶 STRUCTURAL-ONLY |
| VLM 视觉分析 | NoOp grounding | `core/multimodal/` | 🔶 STRUCTURAL-ONLY |

### 5.4 MCP / Skill 扩展

| 能力 | 代码 | 状态 |
|------|------|------|
| MCP server loader | `core/mcp_loader.py` | ✅ RUNTIME-LIVE |
| Skill loader | `core/skill_loader.py` + `core/skill_md_loader.py` | ✅ RUNTIME-LIVE |
| MCP bridge | `mcp_bridge/` 目录 | ✅ RUNTIME-LIVE |

---

## 第六章：Capability-Aware Routing / Device Routing / Runtime Enforcement

### 6.1 capability_routing_gate 的真实性质

**代码**：`core/capability_routing_gate.py`

文件头部明确写明：

```python
CAPABILITY_GATE_DOES_NOT_MODIFY_POOL_MANAGER_POLICY: str = (
    "CAPABILITY_GATE_POLICY: This module is additive.  It does not modify "
    "DevicePoolManager, device_selection.select_devices, DeviceRouter, or "
    "any other existing routing module."
)
```

**性质**：🔷 ADDITIVE-NOT-ENFORCED

`filter_by_required_capabilities()` 是纯函数，只有被明确调用时才生效。

### 6.2 explicit device_id 路径是否绕过 gate

从 `core/openclawd.py` 中的 `send_gateway_command()` 逻辑：

```python
# 第 3704-3712 行区域
if not effective_device_id and required_capabilities and intent_type in (...):
    selected = self._select_device_via_scheduler(required_capabilities)
    # ... 使用 capability 路由
```

**关键**：当 `device_id` 被显式提供时，`effective_device_id` 不为空，capability 自动选择逻辑被跳过。这意味着：
- explicit device_id 路径 **确实绕过 capability routing**
- `required_capabilities` 在 explicit device_id 场景下仅作为 hint，不被 gate 强制

**结论**：⚠️ capability gate 不是默认 runtime 约束，explicit routing 可绕过。

### 6.3 selector / validator / gateway dispatch 真实关系

| 组件 | 角色 | 是否在主链上生效 |
|------|------|----------------|
| `DevicePoolManager.select_device()` | advisory capability hint | ⚠️ 主链，但 capability 是 hint |
| `capability_routing_gate.py` | hard gate（纯函数） | 🔷 ADDITIVE，需主动调用 |
| `target_device_validator.py` | 设备验证 | ⚠️ QUASI-MAINLINE |
| `canonical_device_selector.py` | 多设备选择 | ⚠️ QUASI-MAINLINE |

---

## 第七章：测试 / CI / Readiness / Governance / Release Gate

### 7.1 V2 测试状态

**数量**：`tests/` 目录下约 602 个测试文件（通过 `ls tests/ | grep -c test_` 确认）。

**CI 配置**（`.github/workflows/ci.yml` 确认存在以下 jobs）：
- `lint`：flake8 + black + isort
- `v3-protocol-guard`：禁止 aip_protocol_v2 引用
- `s6-compat-smoke`：回归烟雾测试
- `system-readiness-check`：生成 readiness 报告 + PR7 测试
- `test`：运行 tests/，排除 slow/manual
- `test-placement-guard`：测试文件位置检查

**关键问题**：
1. `system-readiness-check` 中的 `generate_system_readiness_report.py --json` 生成报告，但这是**报告型任务，不是 blocking gate**。报告生成失败会失败，但"系统未就绪"不会阻断
2. tests 覆盖以 unit test 和 contract test 为主，无双仓联合集成测试
3. Android-related tests（如 `test_android_bridge_udm_flow.py`）使用 mock（`MagicMock`，`AsyncMock`），没有真实 WebSocket 协议层测试

### 7.2 Android CI 状态

**确认**：Android 仓 `.github/` 目录下**仅有 `pull_request_template.md`**，无任何 workflow 文件。

```
.github/
  pull_request_template.md   # 唯一文件
```

**结论**：Android 仓 ❌ 无 CI pipeline。任何 Android 侧代码变更无自动化保障。

### 7.3 Readiness / Governance / Release Gate 真实状态

| 组件 | 代码 | 真实行为 |
|------|------|---------|
| `DelegatedFlowReadinessGate` | `core/delegated_flow_readiness_gate.py` | 产出 6 种 verdict，但不阻断 release |
| `DelegatedFlowAcceptanceGate` | `core/delegated_flow_acceptance_gate.py` | 产出 graduation verdict，advisory only |
| `governance_validation_gate.py` | `core/governance_validation_gate.py` | 验证逻辑，不接入 CI blocking |
| ReleaseGate | `core/distributed_release_gate_skeleton.py` | 🔶 skeleton 级别，未接入任何 release pipeline |

**结论**：所有 readiness/governance/release gate 组件均为 ⚠️ ADVISORY 状态，没有一个接入了真实的 CI blocking 或 release 阻断。

### 7.4 governance 层"真实"程度

V2 有大量 governance 相关模块（`delegated_flow_post_graduation_governance.py` 等），Android 有对应的评估器（`DelegatedRuntimePostGraduationGovernanceEvaluator.kt` 等）。

但这些评估器产出的 artifact 需要通过 `reconciliation_signal` 上报 V2，V2 的 gate 需要消费这些 artifact 做决策，然后 gate verdict 需要接入 CI blocking。

**当前链路缺口**（更新后的状态）：
- `reconciliation_signal` 现在有 V2 handler（`galaxy_gateway/android/handlers/reconciliation_signal.py`，在 `android_bridge.py:691` 注册）✅
- 但 handler 委托给 `AndroidDelegatedRuntimeLifecycleCoordinator`，后者的 readiness artifact 是否进入 `DelegatedFlowReadinessGate` 决策路径，需要进一步追踪
- `DelegatedFlowReadinessGate` 的 verdict 没有接入 CI blocking ❌

---

## 第八章：整体系统完成度与阶段判断

### 8.1 当前阶段

> **系统整合期后段（late integration）**，主链已接通，但关键可靠性保障层（truth 持久化、capability gate 强制化、Android CI、双仓联合测试）尚未就绪。

不是 MVP 期（主链已打通），不是 pre-production（关键保障层缺失太多）。

### 8.2 主链完成情况汇总

| 主链 | 状态 | 关键证据 |
|------|------|---------|
| Android 注册 + 握手 | ✅ RUNTIME-LIVE | UDM upsert + test 覆盖 |
| 心跳 / liveness | ✅ RUNTIME-LIVE | handler + Android 心跳计时器 |
| 命令下发 → 结果等待闭环 | ✅ RUNTIME-LIVE | dispatch_to_websocket + asyncio.Event |
| 离线队列 + 重连 replay | ✅ RUNTIME-LIVE | OfflineTaskQueue.kt（文件级持久化）|
| AIP v3 协议强制 | ✅ RUNTIME-LIVE | parse_message_strict + v3-protocol-guard CI |
| LLM provider routing | ✅ RUNTIME-LIVE | multi_llm_router.py |
| MCP/Skill 扩展 | ✅ RUNTIME-LIVE | mcp_loader.py + skill_loader.py |
| reconciliation signal 接收 | ✅ 已接通（PR-7-V2 新增） | android_bridge.py:691 |
| handoff v2 result 接收 | ✅ 已接通 | android_bridge.py:677-680 |

### 8.3 关键缺口全集

**缺口 1：双仓联合集成测试缺失（最高优先级）**

- 所有 Android-related tests 使用 mock，没有一个测试用真实 WebSocket 协议与 V2 进行端到端通信
- 影响：无法验证主链真实行为，只能依赖代码分析和人工判断
- 解法：V2 中建立 Python 级 Android 协议模拟客户端，测试 register → dispatch → task_result 全链路

**缺口 2：V2 Truth 默认持久化不保证（高优先级）**

- `task_events` dict（in-memory）、session registry（in-memory）、`CanonicalSessionTruthRuntime`（in-process）均在 V2 重启后丢失
- `DurableAuditStore` 是条件性的，不是默认保证的
- Android offline queue 重连后发回的 result 在 V2 重启场景下无 awaiter 消费
- 影响：V2 重启后所有 in-flight tasks 丢失，Android 重连无法恢复上下文

**缺口 3：Capability Gate 非默认强制（高优先级）**

- `capability_routing_gate.py` 明确声明为 additive，不修改 DevicePoolManager 或 DeviceRouter
- explicit device_id 路径绕过 capability 选择
- 影响：capability-aware routing 无法作为系统的真实安全约束，只是可选的过滤层

**缺口 4：Android 无 CI（高优先级）**

- Android 仓零 CI，无编译保障，无单元测试自动化
- 影响：Android 侧代码变更无自动化验证，任何 regression 只能靠人工发现

**缺口 5：`unified_runtime_truth_ingress` 未被 bridge 调用（中优先级）**

- 模块存在且正确，但 android_bridge.py 的所有 handler 直接调用子模块，绕过统一入口
- 影响：真值写入路径不统一，难以在统一点施加 audit/policy

**缺口 6：Android Local AI 默认 NoOp（中优先级）**

- `NoOpGroundingService` 是默认实现，本地 grounding 完全不可用
- 影响：Android 的本地 AI 能力声明与运行时默认状态不符，需要明确标记或实际接入

**缺口 7：Governance / Readiness / Release Gate 不阻断（低-中优先级）**

- 所有 gate 产出 advisory report，没有接入 CI blocking 或 release pipeline
- 影响：系统成熟度判断完全依赖人工，release gate 形同虚设

**缺口 8：result idempotency 跨重启不保证（中优先级）**

- `absorb_replay_result_idempotently()` 在进程生命周期内成立
- 跨 V2 重启后，重复消费同一 task_result 的风险存在
- 影响：V2 重启后重连场景下可能重复处理已完成的任务

---

## 第九章：问题全集与后续 Workstream 优先级

### P0 — 必须优先解决（阻断系统可信验证）

#### P0-1：建立双仓联合集成测试框架

**问题**：没有任何自动化手段验证主链（Android register → V2 UDM → command dispatch → task_result → awaiter 解阻塞）。

**建议产物**：
- V2 `tests/integration/` 中添加 Python 级 Android WebSocket 协议模拟客户端
- 覆盖：DEVICE_REGISTER + CAPABILITY_REPORT + task assign + TASK_RESULT 完整闭环
- 可进 CI

#### P0-2：Android 基础 CI 建设

**问题**：Android 仓零自动化保障。

**建议产物**：
- `.github/workflows/android-ci.yml`（Kotlin build + lint + JVM unit tests）
- 最小覆盖 Gradle assembleDebug + ktlint + JVM test

### P1 — 高优先级（影响系统可靠性基础）

#### P1-1：V2 Truth 持久化强制化

**问题**：V2 重启后 in-flight task / session truth 默认丢失。

**建议**：
- `DurableAuditStore` 改为 default-on（SQLite 或文件）
- `task_events` dict 在关键路径上加持久化层
- V2 restart recovery 场景有自动化测试验证

#### P1-2：Result 幂等去重持久化

**问题**：跨 V2 重启的 result 去重依赖 in-memory 机制，重启后失效。

**建议**：
- result_id 去重 set 持久化到 SQLite
- 或复用 DurableAuditStore 做 result 去重

#### P1-3：Capability Gate 默认激活

**问题**：explicit device_id 路径绕过 capability validation。

**建议**：
- `capability_routing_gate.filter_by_required_capabilities()` 接入 DeviceRouter 主路径
- 明确 explicit device_id 也需通过 gate（或有明确的 bypass reason audit）

### P2 — 中优先级（影响认知准确性和边界清晰性）

#### P2-1：unified_runtime_truth_ingress 接入 bridge

**问题**：`ingest_android_runtime_state_update()` 未被实际调用，多条写路径绕过统一入口。

**建议**：将 `android_bridge.py` 的 handler 路由逻辑迁移到通过 `ingest_android_runtime_state_update()` 分发，或明确标记各子路径为合法 canonical 路径。

#### P2-2：Android Local AI 状态明确化

**问题**：`LocalGroundingService` 有完整接口但默认 NoOp，造成能力感知混乱。

**建议**：
- 路线 A：接入真实 SeeClick backend（NCNN/MNN）
- 路线 B：capability report 明确不上报 local_grounding，文档标记为 roadmap

#### P2-3：V2 restart continuity 场景测试

**问题**：`android_v2_continuity_contract.py` 定义了 7 种场景策略，无对应运行时测试。

**建议**：为每个场景添加真实运行时测试（需要 P0-1 的集成框架为前提）。

### P3 — 低优先级（成熟度治理）

#### P3-1：WebRTC / Mesh / Extension 能力状态收口

**问题**：WebRTC P2P、mesh runtime、galaxy federation 被代码结构暗示存在，但实际是 STRUCTURAL-ONLY。

**建议**：在 capability map 和文档中明确标注这些路径为 roadmap/disabled-by-default，防止后续 PR 误判完成度。

#### P3-2：Readiness / Governance Gate 接入 CI blocking

**问题**：所有 gate 产出 advisory，不阻断。

**建议**：选择最关键的一条 gate（如 readiness verdict）接入 CI blocking，证明 gate 有实际约束力。

---

## 附录：关键文件坐标速查表

### V2 主链关键文件

| 文件 | 功能 |
|------|------|
| `galaxy_gateway/routing/dispatch.py` | `dispatch_to_websocket()`，任务下发 + await 结果 |
| `galaxy_gateway/android_bridge.py` | Android 消息分发总入口 |
| `galaxy_gateway/websocket_handler.py` | WebSocket 连接管理 + AIP v3 强制 + 消息路由 |
| `galaxy_gateway/android/handlers/registration.py` | 设备注册 → UDM |
| `galaxy_gateway/android/handlers/delegated_signal.py` | delegated_execution_signal 处理 |
| `galaxy_gateway/android/handlers/handoff_v2_result.py` | handoff v2 结果接收 |
| `galaxy_gateway/android/handlers/reconciliation_signal.py` | reconciliation signal 接收 |
| `core/unified/device_manager.py` | UDM，设备状态 canonical 写入 |
| `core/canonical_session_truth.py` | Session truth runtime（in-process + optional DurableAuditStore）|
| `core/capability_routing_gate.py` | Capability hard gate（additive-only，纯函数）|
| `core/unified_runtime_truth_ingress.py` | Truth 统一入口（additive-only，未被 bridge 调用）|
| `core/android_v2_continuity_contract.py` | 双仓 continuity 策略定义（策略层，非 runtime enforcement）|
| `core/flow_aware_result_convergence.py` | Result idempotent 吸收（进程内有效）|

### Android 主链关键文件

| 文件 | 功能 |
|------|------|
| `network/GalaxyWebSocketClient.kt` | 唯一跨端 transport，连接 V2，67KB |
| `network/OfflineTaskQueue.kt` | 离线任务队列（文件级持久化）|
| `protocol/AipModels.kt` | AIP v3 消息类型全集 |
| `agent/DelegatedRuntimeUnit.kt` | Delegated runtime 执行单元 |
| `runtime/RuntimeController.kt` | 运行时生命周期总控（152KB）|
| `inference/LocalGroundingService.kt` | 本地 grounding 接口（默认 NoOpGroundingService）|
| `inference/LocalPlannerService.kt` | 本地 planner 接口 |
| `runtime/DelegatedRuntimeReadinessEvaluator.kt` | Readiness 评估器（评估框架完整）|

### 能力状态一览

| 能力 | 状态 | 关键限制 |
|------|------|---------|
| WebSocket 双向通信 | ✅ RUNTIME-LIVE | — |
| AIP v3 协议强制 | ✅ RUNTIME-LIVE | — |
| 设备注册 + 心跳 | ✅ RUNTIME-LIVE | — |
| 命令下发 + 结果等待 | ✅ RUNTIME-LIVE | 重启后 awaiter 丢失 |
| 离线 replay | ✅ RUNTIME-LIVE | V2 重启后无法消费 |
| LLM routing | ✅ RUNTIME-LIVE | — |
| MCP/Skill 扩展 | ✅ RUNTIME-LIVE | — |
| delegated execution signal | ⚠️ QUASI-MAINLINE | HandoffEnvelopeV2 触发条件待确认 |
| session continuity | ⚠️ QUASI-MAINLINE | V2 restart recovery 未验证 |
| readiness/governance gate | ⚠️ QUASI-MAINLINE | Advisory only |
| capability routing | 🔷 ADDITIVE-NOT-ENFORCED | explicit device_id 可绕过 |
| unified truth ingress | 🔷 ADDITIVE-NOT-ENFORCED | bridge 未调用 |
| Android local AI | 🔶 STRUCTURAL-ONLY | NoOpGroundingService 默认 |
| WebRTC P2P | 🔶 STRUCTURAL-ONLY | 仅 signaling proxy |
| mesh/constellation | 🔶 STRUCTURAL-ONLY | 框架存在，无多节点验证 |
| Android CI | ❌ MISSING | 零自动化 |
| 双仓集成测试 | ❌ MISSING | 所有 Android tests 用 mock |
| result 跨重启幂等 | ❌ MISSING | 无持久化去重机制 |
| V2 truth 默认持久化 | ❌ MISSING | 条件性，非默认保证 |

---

*本文档基于真实代码，代码坐标在撰写时均已验证。如代码库更新，请以最新代码为准。*
