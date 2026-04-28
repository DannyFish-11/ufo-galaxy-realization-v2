# 联合双仓全系统真实代码审查报告
## ufo-galaxy-realization-v2 × ufo-galaxy-android — 2026 Q2

> **版本**：PR-10 · 全系统代码级深度审查（最完整版本）
>
> **审查方法**：直接阅读两仓主分支真实代码、测试文件、CI workflow，不依赖 `docs/` 中任何既有审查文档或注释口号。以调用链、模块边界、运行时路径、测试覆盖、持久化证据为主要判断依据。
>
> **格式说明**：
> - ✅ = 代码+测试双重支撑、已运行时闭环
> - 🟡 = 代码存在但未形成测试/运行时闭环
> - ⚠️ = 接口/占位/桩实现/局部实现未连通主链
> - ❌ = 当前代码无实现或明确不可用

---

## 目录

1. [系统本质与整体完成度总判断](#1-系统本质与整体完成度总判断)
2. [中心式与分布式协同架构的真实代码分析](#2-中心式与分布式协同架构的真实代码分析)
3. [本地链路（Local Link）代码实现与闭环状态](#3-本地链路local-link代码实现与闭环状态)
4. [跨设备链路（Cross-Device Link）代码实现与闭环状态](#4-跨设备链路cross-device-link代码实现与闭环状态)
5. [V2 × Android 真实耦合关系与协议分析](#5-v2--android-真实耦合关系与协议分析)
6. [端到端闭环分析：输入→调度→执行→回传→验证→收敛](#6-端到端闭环分析输入调度执行回传验证收敛)
7. [真实状态持久化审查](#7-真实状态持久化审查)
8. [错误处理与恢复能力审查](#8-错误处理与恢复能力审查)
9. [可观测性、日志与治理](#9-可观测性日志与治理)
10. [CI 测试覆盖与自动化验收矩阵](#10-ci-测试覆盖与自动化验收矩阵)
11. [已实现能力清单（代码支撑）](#11-已实现能力清单代码支撑)
12. [未闭环能力清单（只有局部实现）](#12-未闭环能力清单只有局部实现)
13. [接口/占位/壳层/伪闭环项](#13-接口占位壳层伪闭环项)
14. [已知问题 · 风险 · 断点 · 优先级清单](#14-已知问题--风险--断点--优先级清单)
15. [下一步建议](#15-下一步建议)

---

## 1. 系统本质与整体完成度总判断

### 1.1 系统本质

基于真实代码得出的唯一合理定性：

**这是一个以 V2 为中心编排权威、以 Android 为持久执行参与方的中心式分布式智能体系统。**

```
[中心侧 — ufo-galaxy-realization-v2]
    main.py (SYSTEM_ORCHESTRATOR_AUTHORITY, 7阶段启动)
    └─ core/system_orchestrator.py (run_startup_sequence)
         └─ unified_launcher.py (FastAPI/uvicorn)
              └─ galaxy_gateway/app.py (传输基底，非主体入口)
                   └─ galaxy_gateway/routes/websocket.py
                        └─ /ws/device/{device_id}  ← 唯一 canonical ingress (AIP v3.0)

[执行侧 — ufo-galaxy-android]
    GalaxyConnectionService.kt (145KB, 常驻后台服务)
    └─ GalaxyWebSocketClient.kt (67KB, OkHttp 出站连接)
         └─ 发送 device_register → V2 canonical ingress
         └─ 接收 task_assign → EdgeExecutor → AccessibilityActionExecutor
         └─ 发送 task_result → V2 task_lifecycle handler
```

**它不是对等 Mesh 系统**。Android 侧代码明确注释：
> "Android is the **durable participant runtime** — NOT the canonical orchestration authority."
> (`core/android_v2_continuity_contract.py`)

**它不是骨架系统**。以下能力有真实代码 + 真实自动化测试：
- AIP v3 WebSocket 传输主链（FastAPI TestClient 真实传输层验证）
- 设备注册/能力上报/任务分发/结果回传全流程
- 协议回归 CI（blocking，每次 PR 运行）
- Android Accessibility 执行链（真实无障碍服务调用）

**它距成熟平台还有明确距离**：
- V2 truth/task 默认 in-process（重启后 in-flight 状态不恢复）
- Android 本地 AI（MobileVLM/SeeClick）默认 NoOp，需外部进程
- 双仓无真实设备 E2E CI（所有跨端测试均为 V2 侧 mock）
- 多设备动态编排不完整（静态编排已实现）

### 1.2 整体完成度矩阵

| 维度 | 完成度 | 说明 |
|------|--------|------|
| V2 启动与基础服务 | ✅ 85% | 7阶段启动已验证，非致命降级路径存在 |
| V2 ↔ Android 传输链 | ✅ 80% | AIP v3 主链 + CI 验证完整 |
| Android 执行链 | ✅ 75% | Accessibility 主链可用，本地 AI 默认 NoOp |
| 本地执行链（Windows） | 🟡 60% | 结构完整，Windows 真实测试覆盖不足 |
| 跨设备任务调度 | 🟡 65% | 路由链完整，动态编排/formation 不完整 |
| session/task 持久化 | ⚠️ 30% | 默认 in-memory，Durable 路径可选未默认接通 |
| Android 本地 AI | ⚠️ 20% | 接口存在，默认 NoOp，需外部进程 |
| WebRTC/P2P/Mesh | ⚠️ 25% | 结构存在，无主链集成，无 CI |
| 多设备动态编排 | ⚠️ 40% | 静态形成已实现，动态调整不完整 |
| 双仓真实 E2E CI | ❌ 0% | 所有 E2E 测试均为 V2 侧 mock |

---

## 2. 中心式与分布式协同架构的真实代码分析

### 2.1 中心侧权威链（真实代码路径）

#### 启动权威
```python
# main.py — SYSTEM_ORCHESTRATOR_AUTHORITY
SYSTEM_ORCHESTRATOR_AUTHORITY = "main.py:SYSTEM_ORCHESTRATOR"

def _run_orchestrator_preflight() -> bool:
    # 7阶段前置检查
    # Phase 1: LOAD_CONFIG
    # Phase 2: RESOLVE_MODE
    # Phase 3: ENV_CHECKS
    # Phase 4: BACKGROUND_SUBSYSTEMS
    # Phase 5: RUNTIME_SUBJECT
    # Phase 6: DESKTOP_SURFACE
    # Phase 7: READINESS_SUMMARY
```

#### 设备状态权威
```python
# core/unified/device_manager.py
UDM_DEVICE_STATE_AUTHORITY = "UDM::CANONICAL_DEVICE_STATE_WRITE_AUTHORITY"

class UnifiedDeviceManager:
    # 单一写 SSOT：注册/注销/状态更新/能力传播
    # 所有下游（device_registry, device_pool_manager）只是 compat 层
```

#### 路由权威
```python
# galaxy_gateway/device_router.py
# DeviceRouter = "routing substrate" — NOT 编排选择器
# 路由基底，连接生命周期事件同步到 UDM via _sync_connection_state_to_udm()
```

#### 编排权威（主体核心）
```python
# core/openclawd.py — OpenClawd = Subject Core
# stage 1: Ingest (PerceptionFrame + multimodal_context)
# stage 2: Continuum / Liminal Cognition
# stage 3: _determine_execution_path → local / cross_device / hybrid / none
# stage 4: Manifest (DecisionExecutor local / CommandRouter cross-device)
```

### 2.2 分布式节点层（真实代码路径）

```
V2 nodes/ 目录 (130+ 节点)
├─ VLM 节点 (视觉语言模型)
├─ WebRTC 节点 (媒体传输)
├─ RAG 节点 (检索增强生成)
├─ Code 节点 (代码执行)
└─ ...其余专有能力节点

galaxy_gateway/routing/device_selection.py
    Step 0: target_device_validator 可接受性预过滤
    Step 1: GatewayCapabilityRegistry 确定 exec_mode
    Step 2: capability_routing_gate.filter_by_required_capabilities() [硬门控]
    Step 3: autonomous_filter
    Step 4: DevicePoolManager.select_device()
```

### 2.3 NATS 消息总线（真实代码）

```python
# core/nats_bus.py
NATS_FABRIC_CARRIER_AUTHORITY = "NATS::CARRIER_FABRIC_LAYER_V1"
# 分布式任务分发：TaskEnvelope / ResultEnvelope
# 约束 C5: 配置由 GALAXY_NATS_URL 环境变量，未设置则降级为 no-op 模式
# → 关键发现：NATS 默认是 no-op！只有设置 GALAXY_NATS_URL 才激活
```

**风险**：NATS 未配置时系统仍可启动（降级模式），但分布式任务分发实际不工作。这是一个**沉默降级**。

---

## 3. 本地链路（Local Link）代码实现与闭环状态

### 3.1 Local Link 规范定义（`core/local_execution_chain.py`）

```
DesktopPresenceRuntime (outer shell / Windows clothing)
    └─ 拥有: session, tri-state lifecycle, native multimodal ingress
    └─ 在 LIMINAL 阶段调用 OpenClawd.process()
          └─ OpenClawd (subject core)
                └─ CommandRouter.route_envelope() [LOCAL_MANIFESTATION]
                      └─ Local executor / capability / skill / MCP tool
                            └─ LocalExecutionResult (规范化结果)
                                  └─ OpenClawd feedback
                                        └─ Projection / Audit / Memory backflow
```

**6步规范链**（本地比跨设备少 1 步：无 gateway/task-envelope 步骤）

### 3.2 本地链路实际可用情况

| 组件 | 代码状态 | 测试 | 备注 |
|------|----------|------|------|
| `DesktopPresenceRuntime` | ✅ 代码完整 | 🟡 部分 | Windows 运行时壳 |
| `OpenClawd.process()` | ✅ 代码完整 | ✅ 单元测试 | 4阶段认知核心 |
| `CommandRouter.route_envelope[LOCAL]` | ✅ 代码完整 | 🟡 集成测试 | 本地 dispatch |
| Windows Accessibility Executor | 🟡 结构存在 | ⚠️ 无真实 Windows CI | 需 Windows 环境 |
| `LocalExecutionResult` | ✅ 数据结构定义完整 | ✅ 单元测试 | 规范化结果容器 |
| Memory backflow | 🟡 接口存在 | ⚠️ 无完整 E2E 测试 | 可选接入 |

**闭环判断**：本地链路代码结构完整，认知/路由逻辑有单元测试覆盖。**真正的 Windows 本地执行（调用 UIAutomation/Win32 API）在 CI 中无法验证**，因为 CI 在 Ubuntu runner 上运行。

---

## 4. 跨设备链路（Cross-Device Link）代码实现与闭环状态

### 4.1 Cross-Device Link 规范定义（`core/cross_device_execution_chain.py`）

```
OpenClawd (routing authority — 唯一决策方)
    └─ CommandRouter.route_envelope() (唯一跨设备路由器)
          └─ TaskEnvelope / CommandEnvelope (可序列化任务合约)
                └─ gateway substrate (执行管道，不做规划决策)
                      └─ Worker / Device / Node (纯执行者)
                            └─ ResultEnvelope (规范化结果)
                                  └─ OpenClawd feedback
                                        └─ Projection / Audit / Memory backflow
```

**7步规范链**

### 4.2 关键代码路径详细追踪

#### V2 侧派发链（可追踪）
```python
# 1. 决策入口
core/openclawd.py:OpenClawd._determine_execution_path()
    → execution_path = "cross_device" | "hybrid"

# 2. 路由入口
core/command_router.py:CommandRouter.route_envelope()
    → ACL 检查
    → NATS/WebSocket dispatch 选择

# 3. 设备选择
galaxy_gateway/routing/device_selection.py:select_devices()
    → Step 0: target_device_validator 预过滤
    → Step 1: exec_mode 确定
    → Step 2: capability_routing_gate (PR-3 硬门控)
    → Step 3: autonomous_filter
    → Step 4: DevicePoolManager.select_device()

# 4. 消息构建与发送
galaxy_gateway/routing/dispatch.py:dispatch_to_websocket()
    → build_aip_message(device_id, task_id, trace_id, command)  # AIP v3.0
    → WebSocket send → Android
```

#### Android 侧接收链（可追踪）
```kotlin
// 1. 消息接收
GalaxyWebSocketClient.kt:handleMessage()
    → 收到 task_assign

// 2. 任务接受评估
GalaxyConnectionService.kt:handleTaskAssign()
    → DelegatedRuntimeAcceptanceEvaluator.evaluate()
    → executeLocalTaskAssign()

// 3. 执行
EdgeExecutor.handleTaskAssign()
    → screenshotProvider.captureJpeg()  // 截图
    → plannerService.plan()             // 规划 (默认 NoOp!)
    → groundingService.ground()         // 定位元素 (默认 NoOp!)
    → accessibilityExecutor.execute()   // 无障碍执行 (真实)

// 4. 结果回传
GalaxyConnectionService.sendTaskResult()
    → V2 (task_result 消息, AIP v3.0)
```

### 4.3 跨设备链路闭环状态

| 链路段 | 代码完整性 | 自动化测试 | 真实 E2E | 备注 |
|--------|------------|------------|----------|------|
| V2 决策→路由 | ✅ | ✅ 单元/集成 | 🟡 V2侧mock | OpenClawd→CommandRouter |
| 设备选择 | ✅ | ✅ 单元测试 | 🟡 V2侧mock | 4步选择流程 |
| AIP v3 消息构建 | ✅ | ✅ 单元测试 | ✅ 传输层验证 | build_aip_message |
| V2→Android WebSocket | ✅ | ✅ 传输层测试 | ❌ 无真实设备CI | FastAPI TestClient mock |
| Android 任务接受 | ✅ (Kotlin) | ✅ JVM 测试 | ❌ 无真实设备CI | DelegatedRuntimeAcceptanceEvaluator |
| Android 规划（AI） | ⚠️ NoOp默认 | ⚠️ NoOp验证 | ❌ | MobileVLM 需外部进程 |
| Android 定位（AI） | ⚠️ NoOp默认 | ⚠️ NoOp验证 | ❌ | SeeClick 需外部进程 |
| Android Accessibility执行 | ✅ | ✅ mock E2E | ❌ 无真实设备CI | AccessibilityActionExecutor |
| task_result 回传 V2 | ✅ | ✅ 传输层测试 | ❌ 无真实设备CI | sendTaskResult() |
| V2 结果处理/回流 | ✅ | 🟡 部分覆盖 | ❌ | task_lifecycle handler |

---

## 5. V2 × Android 真实耦合关系与协议分析

### 5.1 协议层（AIP v3.0）

**协议单一事实来源**：`galaxy_gateway/protocol/aip_v3.py`

```python
class MessageType(str, Enum):
    # 完整枚举（V2 规范定义）
    DEVICE_REGISTER = "device_register"
    DEVICE_REGISTER_ACK = "device_register_ack"
    CAPABILITY_REPORT = "capability_report"
    TASK_ASSIGN = "task_assign"
    TASK_RESULT = "task_result"
    TASK_END = "task_end"
    TASK_STATUS = "task_status"
    HEARTBEAT = "heartbeat"
    DEVICE_STATUS = "device_status"
    GOAL_EXECUTION_RESULT = "goal_execution_result"
    # ...等 30+ 类型

class AIPDeviceType(str, Enum):
    # 全平台细分类型
    ANDROID_PHONE = "android_phone"
    WINDOWS_DESKTOP = "windows_desktop"
    CLOUD_AWS = "cloud_aws"
    # ...等 20+ 类型
```

**Android 侧对应文件**（按审查描述）：`AIPMessageV3.kt`、`MessageType.kt`

**协议对齐验证**：V2 `android_bridge.py` 注释：
> "与安卓端 AIPMessageV3.kt 完全对齐。"

**CI 保障**：`ci.yml` job `v3-protocol-guard`（blocking，每次 PR），禁止引用废弃的 `aip_protocol_v2`。

### 5.2 传输层

**V2 ingress（canonical）**：
```
galaxy_gateway/routes/websocket.py
    /ws/device/{device_id}   ← [CANONICAL] 唯一 canonical device ingress
    /ws/android/{device_id}  ← [COMPAT] Android 旧路径，委托给 canonical pipeline
    /ws/android              ← [COMPAT] Android fallback
    /ws/ufo3/{device_id}     ← [LEGACY-DISABLED] 默认关闭
    /ws/{device_id}          ← [DEPRECATED] 不要用于新客户端
```

**Compat 层**：`galaxy_gateway/protocol/compat.py:normalise_to_v3_dict()`
- 所有入站消息在 WS 层规范化为 v3 格式
- AIP v1/v2 消息在 ingress 处静默升级

### 5.3 消息处理链（handler 分解，PR-3 模块化）

```python
# galaxy_gateway/android_bridge.py:AndroidBridge.handle_message()
# 委托到子模块：
handlers/registration.py      # device_register, 未注册消息处理
handlers/heartbeat.py          # heartbeat, device_status, agent_ping, agent_status
handlers/task_lifecycle.py     # task_result, task_end, task_progress, command_result, error, task_cancel
handlers/goal_execution.py     # goal_execution_result
handlers/capability_report.py  # capability_report
handlers/delegated_signal.py   # delegated_flow 信号
handlers/handoff_v2_result.py  # handoff v2 结果
handlers/reconciliation_signal.py # 真实对齐信号
```

### 5.4 关键耦合接口：设备注册

```python
# handlers/registration.py:handle_device_register()
# V2 侧：
# 1. 提取 runtime_attachment_session_id（priority: 显式字段 > session_id > UUID）
# 2. _derive_body_mesh_roles(capabilities) → DeviceRole.PERCEPTION/ACTION/PRESENCE
# 3. UDM 设备注册
# 4. CanonicalSessionTruthRuntime 创建 session 记录
# 5. AttachedRuntimeSessionRegistry 注册
```

```kotlin
// Android 侧：GalaxyWebSocketClient.sendHandshake()
// 发送 device_register 消息（AIP v3.0）
// 携带：device_id, device_type, capabilities, source_runtime_posture
// source_runtime_posture: "control_only" | "join_runtime"
```

### 5.5 关键耦合接口：任务分发与执行

**V2→Android（task_assign）**：
```python
# galaxy_gateway/routing/dispatch.py:dispatch_to_websocket()
# 构建 AIP v3 task_assign 消息
# 携带：task_id, trace_id, command, parameters, timeout
```

**Android→V2（task_result）**：
```kotlin
// GalaxyConnectionService.sendTaskResult()
// AIP v3.0 task_result 消息
// 携带：task_id, status (SUCCESS/FAILURE/PARTIAL), result, execution_time_ms
```

**V2 接收 task_result**：
```python
# handlers/task_lifecycle.py:handle_task_result()
# 1. 信号去重（_signal_guard，512 slot LRU，防止 compat 层重复触发）
# 2. store_task_result → core/openclawd_memory_backflow（可选）
# 3. _reconcile_inbound_message → core/android_execution_signal_reconciler（可选）
# 4. _ingest_participant_truth → core/android_participant_truth_ingress（可选）
```

**注意**：步骤 2/3/4 全部是 `try/except ImportError → None` 的可选接入，非默认生效！

---

## 6. 端到端闭环分析：输入→调度→执行→回传→验证→收敛

### 6.1 完整 E2E 主链代码追踪

```
[输入] 用户自然语言请求
    ↓ galaxy_gateway/routes/chat.py 或 core/routes/chat.py:POST /api/v1/chat
    ↓
[调度-认知] core/openclawd.py:OpenClawd.process()
    ├─ Stage 1: Ingest — PerceptionFrame + multimodal_context 融合
    ├─ Stage 2: Continuum — ContinuumOrchestrator 意图→state_continuum
    ├─ Stage 3: Branch — _determine_execution_path()
    │       → "cross_device": 下派给 CommandRouter
    │       → "local": 下派给 DecisionExecutor
    │       → "hybrid": 两者并行
    │       → "none": 仅响应，不执行
    └─ Stage 4: Manifest
           ↓
[调度-路由] core/command_router.py:CommandRouter.route_envelope()
    ↓ ACL 检查
    ↓ galaxy_gateway/device_router.py:DeviceRouter.route_task()
    ↓ routing/device_selection.py (4步设备选择)
    ↓ routing/dispatch.py:dispatch_to_websocket()
    ↓
[传输] WebSocket AIP v3.0 task_assign → /ws/device/{device_id}
    ↓
[执行-Android] GalaxyConnectionService.executeLocalTaskAssign()
    ↓ DelegatedRuntimeAcceptanceEvaluator.evaluate()
    ↓ EdgeExecutor.handleTaskAssign()
    ↓ screenshotProvider.captureJpeg()
    ↓ plannerService.plan()        [⚠️ 默认 NoOp!]
    ↓ groundingService.ground()    [⚠️ 默认 NoOp!]
    ↓ accessibilityExecutor.execute() [✅ 真实执行]
    ↓
[回传] GalaxyWebSocketClient.sendTaskResult()
    ↓ AIP v3.0 task_result → V2 /ws/device/{device_id}
    ↓
[验证-V2] handlers/task_lifecycle.py:handle_task_result()
    ↓ 信号去重 (_signal_guard)
    ↓ store_task_result (可选)
    ↓ reconcile_inbound_message (可选)
    ↓ ingest_participant_truth (可选)
    ↓
[收敛] 响应回用户
    ↓ SSE / REST 响应
    ↓ core/routes/projection.py /api/v1/projection (状态投影，可观测)
```

### 6.2 E2E 闭环断点分析

| 断点位置 | 描述 | 优先级 |
|----------|------|--------|
| **Android 规划默认 NoOp** | `plannerService` / `groundingService` 默认返回空结果，AI 能力不可用 | P0 |
| **task_result 处理可选接入** | `store_task_result` / `reconcile_inbound` 均为可选 import，导致结果不一定回流 | P0 |
| **无真实设备 E2E CI** | 所有 E2E 测试均在 V2 侧通过 mock WebSocket 完成，从未连接真实 Android | P0 |
| **NATS 默认 no-op** | 分布式任务分发未配置 `GALAXY_NATS_URL` 时静默降级，开发者可能不知道 | P1 |
| **V2 重启后 in-flight task 丢失** | session/task truth 默认 in-memory ring buffer | P1 |
| **Windows 本地执行链无 CI** | CI 跑在 Ubuntu，Windows 真实执行路径从未被 CI 验证 | P1 |
| **多设备 formation 只支持静态** | 动态设备组合/formation 调整未完全实现 | P2 |
| **WebRTC 无 CI，无主链集成** | WebRTC 信令结构存在，但未纳入 canonical task lifecycle | P2 |

---

## 7. 真实状态持久化审查

### 7.1 设备状态持久化

```python
# core/device_registry.py（注释明确）
# "the on-disk storage is treated as a snapshot or projection cache,
#  *not* as a canonical source of device truth."
# "Devices restored from disk are always loaded in the OFFLINE state
#  and must re-register through UDM to obtain authoritative online status."
```

**结论**：设备状态磁盘持久化存在（JSON 文件），但仅作缓存/快照。重启后设备需重新注册。✅ 此行为有明确设计意图，属于合理设计。

### 7.2 Session/Task Truth 持久化（关键风险）

```python
# core/canonical_session_truth.py（注释原文）
# "Durable audit sink (PR-B2) — the ring-buffer runtime is still
#  in-process authoritative; when a DurableAuditStore is attached via
#  set_audit_store(), each record is also written to the store so truth
#  merge evidence survives process lifetime."
```

```python
# core/replay_audit_persistence.py
# append-only JSONL 审计存储，可通过 set_audit_store() 接入
# 但这是可选路径，非默认激活
```

**风险**：V2 重启后：
1. `CanonicalSessionTruthRuntime` 中所有 session/truth 记录丢失
2. 正在执行的任务（delegated to Android）状态不可恢复
3. Android 可能在 V2 重启后送回 task_result，V2 无对应 task 记录

`core/android_v2_continuity_contract.py` 明确定义了此场景（Scenario 4）：
> "V2 restart with in-flight tasks — Android may re-attach and present a result; V2 must accept the result against a recovered task record rather than creating a phantom entry."

代码定义了此策略，但实际持久化恢复路径未默认激活。

### 7.3 Android 本地持久化（相对健康）

```kotlin
// network/OfflineTaskQueue.kt (10KB)
// Room/SharedPreferences 持久化
// replay/dedup 逻辑
// → 离线期间任务缓冲，重连后重放
// → BootReceiver.kt：设备重启后自动重启 GalaxyConnectionService
```

**结论**：Android 侧持久化比 V2 侧更完整：有本地队列 + 重启恢复。

---

## 8. 错误处理与恢复能力审查

### 8.1 信号去重保护（已实现）

```python
# handlers/task_lifecycle.py
# _SIGNAL_GUARD_CAPACITY = 512 slot LRU OrderedDict
# 防止 compat 层将同一消息重复处理
# 优先用 idempotency_key，其次 message_id
```

✅ 有代码实现。

### 8.2 协议 compat 降级（已实现）

```python
# galaxy_gateway/protocol/compat.py:normalise_to_v3_dict()
# AIP v1/v2 → v3 规范化
# 错误解析时跳过消息（日志记录）
# 参见 galaxy_gateway/routes/websocket.py:_handle_android_ws()
```

✅ 有代码实现，有 CI 验证。

### 8.3 断线重连（Android 侧已实现）

```kotlin
// GalaxyWebSocketClient.kt — OkHttp WebSocket
// 断线重连逻辑已实现
// OfflineTaskQueue：离线期间任务缓冲
```

✅ Android 侧有实现。

### 8.4 V2 侧连接管理

```python
# core/unified/connection_manager.py — UnifiedConnectionManager
# 连接/presence 权威
# 设备超时检测：默认 heartbeat_timeout=60s, grace=30s
# (core/unified/device_manager.py:_DEFAULT_HEARTBEAT_TIMEOUT_SECS)
```

🟡 连接管理代码存在，但超时检测/自动清理的自动化测试覆盖不完整。

### 8.5 系统级恢复（重要缺口）

| 恢复场景 | 代码状态 | 默认可用 |
|----------|----------|----------|
| V2 重启后 in-flight task 恢复 | ⚠️ DurableAuditStore 可选路径存在 | ❌ 非默认 |
| Android 重连后 continuity_resume | ✅ 定义了 RECONNECT_CONTINUITY_RESUME 策略 | 🟡 部分 |
| Android 进程重建后重附策略 | ✅ 合约定义完整（android_v2_continuity_contract.py） | 🟡 合约完整但测试覆盖不全 |
| Stale participant identity 拒绝 | ✅ 策略定义 | 🟡 需运行时验证 |

---

## 9. 可观测性、日志与治理

### 9.1 可观测性基础设施

| 组件 | 代码 | 状态 |
|------|------|------|
| SLO 指标端点 | `core/slo_metrics.py` + `/api/v1/health` | ✅ CI 验证 |
| 系统健康检查 | `core/health_check.py` + `core/routes/health.py` | ✅ 有路由 |
| 监控仪表盘 | `core/monitoring.py` + `/api/v1/monitoring` | 🟡 路由存在，内部实现可观测 |
| 追踪/trace | `core/decision_timeline.py` 等多个追踪模块 | 🟡 结构存在 |
| 运行时状态投影 | `/api/v1/projection` | ✅ 有路由和投影契约 |
| 审计日志 | `replay_audit_persistence.py` (JSONL) | ⚠️ 可选，非默认 |

### 9.2 架构治理机制

```python
# 多个模块使用 sentinel 常量声明权威性：
CANONICAL_API_ROUTES_AUTHORITY = "core.api_routes"
UDM_DEVICE_STATE_AUTHORITY = "UDM::CANONICAL_DEVICE_STATE_WRITE_AUTHORITY"
NATS_FABRIC_CARRIER_AUTHORITY = "NATS::CARRIER_FABRIC_LAYER_V1"
CANONICAL_DEVICE_INGRESS_AUTHORITY = "galaxy_gateway.routes.websocket:..."
SYSTEM_ORCHESTRATOR_AUTHORITY = "main.py:SYSTEM_ORCHESTRATOR"
```

这些 sentinel 常量是**可被 grep/CI 工具核验的架构合规点**，是一种有效的轻量级治理机制。

### 9.3 已知治理缺口

- 遗留 compat 路径有 sentinel 记录，但无自动化检测确认它们不会被新代码无意使用
- `dashboard/backend/main.py` 被明确声明为 `LEGACY SURFACE`（注释存在），但实际是否还有调用者未做完整审计
- 多处 `try/except ImportError → None` 模式导致可选模块静默失效，缺少可观测性告警

---

## 10. CI 测试覆盖与自动化验收矩阵

### 10.1 V2 侧 CI 矩阵

| CI Job | 触发条件 | 覆盖范围 | Blocking | 备注 |
|--------|----------|----------|----------|------|
| `lint` | push/PR to main | `core/` flake8+black+isort | ✅ | 格式/lint |
| `v3-protocol-guard` | push/PR to main | 全仓库 `.py` 文件 | ✅ | 禁止 aip_v2 引用 |
| `s6-compat-smoke` | push/PR to main | compat 回归测试 | ✅ | legacy→v3 |
| `slo-metrics-check` | push/PR to main | SLO 指标结构 | ✅ | PR-G2 |
| `transport-harness` | gateway/core 改动 | V2 侧 WS 传输层 | ✅ | TestClient mock |
| `protocol-regression` | gateway/core 改动 | AIP 协议回归 | ✅ | 非 happy-path |
| `android-ci-baseline` | gateway/core 改动 | V2 侧 Android 合约 | ✅ | V2 侧 mock |
| `android-runtime-e2e` | gateway/core 改动 | Android 6步执行序 | ✅ BLOCKING | V2 侧 mock |
| `separated-process-ws` | gateway/core 改动 | 进程分离 WS E2E | ✅ | 本地服务器 |
| `multi-device-failure` | gateway/core 改动 | 多设备失败恢复 | ✅ | V2 侧 mock |

### 10.2 Android 仓 CI 矩阵

| CI Job | 工具 | 覆盖范围 | 备注 |
|--------|------|----------|------|
| `JVM unit tests` | `./gradlew :app:test` | 28个测试子包 | 规模可观 |
| `assembleDebug` | Gradle | APK 构建完整性 | 确保能出包 |
| `lintDebug` | Gradle | Android Lint | |

### 10.3 关键缺失 CI

| 缺失 CI | 影响 | 严重程度 |
|---------|------|----------|
| **真实 Android 设备 E2E CI** | 跨端主链从未在 CI 中验证 | P0 |
| **Windows 真实环境 CI** | 本地执行链（Win32/UIAutomation）从未被 CI 验证 | P1 |
| **V2 重启后 task 恢复集成测试** | 持久化恢复路径无自动化验证 | P1 |
| **NATS 集成测试** | NATS fabric 在 CI 中无真实服务验证 | P2 |
| **WebRTC 信令 E2E** | WebRTC 无任何 CI | P2 |

---

## 11. 已实现能力清单（代码支撑）

以下能力有代码实现 + 自动化测试双重支撑：

### 11.1 已实现 ✅

1. **V2 7阶段启动序列**
   - 证据：`main.py:_run_orchestrator_preflight()` + `core/system_orchestrator.py`

2. **AIP v3.0 WebSocket canonical ingress**
   - 证据：`galaxy_gateway/routes/websocket.py:/ws/device/{device_id}` + `ci.yml:v3-protocol-guard`

3. **设备注册/能力上报 V2 侧处理**
   - 证据：`handlers/registration.py:handle_device_register()` + `handlers/capability_report.py`
   - 测试：`tests/test_android_server_e2e.py` + `dual_repo_integration.yml:android-ci-baseline`

4. **任务分发（task_assign）传输链**
   - 证据：`galaxy_gateway/routing/dispatch.py:dispatch_to_websocket()` → AIP v3 消息 → WebSocket
   - 测试：`tests/integration/test_dual_repo_transport_harness.py`（真实 WS 传输层）

5. **task_result 接收与基础处理**
   - 证据：`handlers/task_lifecycle.py:handle_task_result()` + 信号去重

6. **AIP v1/v2→v3 compat 规范化**
   - 证据：`galaxy_gateway/protocol/compat.py:normalise_to_v3_dict()`
   - 测试：`dual_repo_integration.yml:protocol-regression`

7. **UDM 设备状态 SSOT**
   - 证据：`core/unified/device_manager.py:UnifiedDeviceManager`

8. **4步设备选择流程（capability gate）**
   - 证据：`galaxy_gateway/routing/device_selection.py` + `capability_routing_gate.py`

9. **Android Accessibility 执行链**
   - 证据：Android `AccessibilityActionExecutor.kt` + `GalaxyConnectionService.kt`
   - 测试：Android `./gradlew :app:test`

10. **Android OfflineTaskQueue 本地持久化**
    - 证据：`network/OfflineTaskQueue.kt`（Room/SharedPreferences）

11. **Android BootReceiver（服务重启）**
    - 证据：`AndroidManifest.xml:BootReceiver` + `GalaxyConnectionService.onCreate()`

12. **SLO 指标端点**
    - 证据：`core/slo_metrics.py` + `ci.yml:slo-metrics-check`

13. **信号去重（512 slot LRU）**
    - 证据：`handlers/task_lifecycle.py:_signal_guard_accept()`

---

## 12. 未闭环能力清单（只有局部实现）

以下能力代码结构存在，但尚未形成完整系统闭环：

### 12.1 局部实现 🟡

1. **V2 session truth 持久化**
   - 代码：`replay_audit_persistence.py` (JSONL)
   - 缺：未在启动序列默认接通

2. **Android 本地 AI 规划+定位**
   - 代码：`LocalPlannerService` / `LocalGroundingService` 接口
   - 缺：默认实现是 `NoOpPlannerService` / `NoOpGroundingService`

3. **task_result 内存回流**
   - 代码：`core/openclawd_memory_backflow.py:store_task_result`
   - 缺：`try/except ImportError → None`，非默认接通

4. **执行信号对齐**
   - 代码：`core/android_execution_signal_reconciler.py`
   - 缺：同上可选导入模式

5. **Windows 本地执行链**
   - 代码：`DecisionExecutor` + `WindowsExecutionArbiter`
   - 缺：无 CI 验证（需 Windows 环境）

6. **多设备动态 formation**
   - 代码：`core/device_formation/formation_resolver.py`（静态已实现）
   - 缺：动态 formation 调整不完整

7. **OpenClawd hybrid 执行路径**
   - 代码：`_determine_execution_path() → "hybrid"` 有分支
   - 缺：本地+跨设备并行的测试覆盖不完整

8. **V2 重启后 in-flight task 恢复**
   - 代码：`android_v2_continuity_contract.py` 合约完整定义了 7 种恢复场景
   - 缺：恢复路径未默认激活，无自动化 E2E 测试

---

## 13. 接口/占位/壳层/伪闭环项

以下内容仅为接口定义、占位符、壳层或存在"伪闭环"风险：

### 13.1 接口/占位 ⚠️

1. **Android 本地 AI NoOp 默认实现**
   ```kotlin
   // NoOpPlannerService.plan()
   return PlanResult(steps = emptyList(), error = "MobileVLM planner not available")
   // NoOpGroundingService.ground()
   return GroundingResult(x=0, y=0, confidence=0f, error = "SeeClick not available")
   ```
   - 系统"成功"执行了 plan()+ground()，但结果为空/错误——这是**伪闭环**：代码调用成功，但能力未实际工作。

2. **NATS 无配置时的 no-op 降级**
   - NATS bus 在无 `GALAXY_NATS_URL` 时所有方法返回 `{"success": False, "error": "not connected"}`
   - 系统不报错继续运行，但分布式任务分发实际不工作
   - **伪闭环风险**：开发者可能未注意到 NATS 功能已静默停用

3. **多处 `try/except ImportError → None` 可选模块**
   ```python
   # task_lifecycle.py 中：
   try:
       from core.openclawd_memory_backflow import store_task_result
   except ImportError:
       store_task_result = None
   try:
       from core.android_execution_signal_reconciler import reconcile_inbound_message
   except ImportError:
       _reconcile_inbound_message = None
   ```
   - 这些模块缺失时，task_result 处理会静默跳过关键步骤
   - **伪闭环风险**：表面上"处理了"，实际上关键步骤被跳过

4. **`dashboard/backend/main.py` 遗留表面**
   - 被声明为 `LEGACY SURFACE`（`DASHBOARD_LEGACY_SURFACE_AUTHORITY`）
   - 但实际是否有生产调用者仍未完整清理

5. **`/ws/{device_id}` 已弃用但仍注册**
   - `galaxy_gateway/routes/websocket.py` 中标注为 `[DEPRECATED]`
   - 仍存在于路由表，旧客户端可能仍在使用

6. **WebRTC `galaxy_gateway/webrtc_proxy.py`**
   - 结构存在，但：
     - 无 canonical task lifecycle 集成
     - 无 CI
     - 无 Android 侧 E2E 验证
   - 当前是独立的"媒体旁道"，非主系统闭环

---

## 14. 已知问题 · 风险 · 断点 · 优先级清单

### P0 — 阻塞性问题（影响系统基础可用性）

| # | 问题 | 位置 | 代码证据 |
|---|------|------|----------|
| P0-1 | **无真实 Android 设备 E2E CI** | 全系统 | 所有 CI 均为 V2 侧 mock，真实跨端主链从未自动化验证 |
| P0-2 | **Android 本地 AI 默认 NoOp** | Android `inference/` | `NoOpPlannerService`, `NoOpGroundingService` — plan+ground 结果恒为空 |
| P0-3 | **task_result 关键处理步骤可选** | `handlers/task_lifecycle.py` | `store_task_result`/`reconcile`/`ingest_truth` 均 try/ImportError→None |

### P1 — 重要缺口（影响可靠性和完整性）

| # | 问题 | 位置 | 代码证据 |
|---|------|------|----------|
| P1-1 | **V2 重启后 in-flight task 状态丢失** | `core/canonical_session_truth.py` | "in-process authoritative"，DurableAuditStore 非默认接通 |
| P1-2 | **NATS 默认 no-op，静默降级** | `core/nats_bus.py` | `GALAXY_NATS_URL` 未配置时分布式分发不工作 |
| P1-3 | **Windows 本地执行链无 CI 验证** | `core/local_execution_chain.py` | CI 跑 Ubuntu，Win32/UIAutomation 路径无法覆盖 |
| P1-4 | **session truth 跨重启恢复路径未接通** | `replay_audit_persistence.py` | 可选路径存在但未在启动序列激活 |
| P1-5 | **多处可选 import 导致静默降级** | `task_lifecycle.py` 等 | `try/ImportError→None` 模式无可观测性告警 |

### P2 — 中优先级问题（影响完整性和扩展性）

| # | 问题 | 位置 | 代码证据 |
|---|------|------|----------|
| P2-1 | **多设备动态 formation 不完整** | `core/device_formation/` | 静态已实现，动态调整未完成 |
| P2-2 | **WebRTC 无主链集成，无 CI** | `galaxy_gateway/webrtc_proxy.py` | 独立旁道，无 task lifecycle 集成 |
| P2-3 | **遗留路径（`/ws/{device_id}`等）未清理** | `galaxy_gateway/routes/websocket.py` | DEPRECATED 标注但仍注册 |
| P2-4 | **Android Body Mesh role 无动态更新** | `handlers/registration.py` | role 在注册时推导，无后续动态调整路径 |
| P2-5 | **OpenClawd hybrid 并行路径测试不足** | `core/openclawd.py` | `execution_path="hybrid"` 分支覆盖较薄 |

### P3 — 低优先级问题（代码质量/可维护性）

| # | 问题 | 位置 | 代码证据 |
|---|------|------|----------|
| P3-1 | `dashboard/backend/main.py` 遗留表面未完整清理 | dashboard/ | LEGACY_SURFACE 声明存在，清理未完成 |
| P3-2 | AIP 设备类型包含 iOS/IoT/Cloud 等未实现平台 | `aip_v3.py:AIPDeviceType` | 定义存在但无对应实现 |
| P3-3 | `DeviceRegistry` 与 UDM 双写路径职责边界略模糊 | `core/device_registry.py` | 注释已说明角色但调用链仍有冗余 |
| P3-4 | Android `source_runtime_posture` 语义无 V2 侧运行时 diff 告警 | `android_runtime_host.py` | 分类逻辑有，但分类变化无事件通知 |

---

## 15. 下一步建议

### 立即（P0 修复）

1. **接通 task_result 处理中的关键步骤**
   - 将 `store_task_result` / `reconcile_inbound_message` / `ingest_participant_truth` 改为强依赖或明确记录缺失告警
   - 具体：在 `task_lifecycle.py:handle_task_result()` 添加 `if store_task_result is None: logger.warning("Memory backflow not available — task results will not be persisted to OpenClawd memory")`

2. **激活 Android 本地 AI 的最小化路径**
   - 为 Android 提供一个最小化的本地规划/定位实现（哪怕是规则引擎），替代 NoOp
   - 或至少在 `EdgeExecutor` 中检测到 NoOp 时提前失败并告知用户，而不是静默继续

3. **建立真实 Android 设备 E2E CI**
   - 引入 Android Emulator（`emulator-vtx-x86_64`）+ `instrumentation tests`
   - 验证 V2→emulator 的完整 task_assign→task_result 主链
   - 即使仅覆盖注册+心跳+简单命令执行，也比当前的纯 mock 强

### 短期（P1 修复）

4. **默认接通 DurableAuditStore**
   - 在 `main.py` 启动序列中（Phase 4 或 Phase 5）默认调用 `set_audit_store()`
   - 激活 `replay_audit_persistence.py` 的 JSONL append-only 存储

5. **NATS 配置检测与告警**
   - 在启动序列中检测 `GALAXY_NATS_URL` 是否配置
   - 未配置时打印明确警告："[WARN] NATS not configured — distributed task dispatch is DISABLED"

6. **可选模块缺失的统一告警机制**
   - 引入 `core/optional_modules_registry.py` 记录所有可选模块
   - 在启动时统一打印"可选模块可用/不可用"状态摘要
   - 替代散落在各处的 `try/ImportError→None` 沉默降级

7. **Android continuity contract 验收测试**
   - 基于 `android_v2_continuity_contract.py` 中定义的 7 种场景编写集成测试
   - 重点覆盖：Scenario 4（V2重启后task恢复）、Scenario 3（Android进程重建）

### 中期（P2 完善）

8. **WebRTC 路径明确化**
   - 决定：WebRTC 是否要接入 canonical task lifecycle
   - 如是：在 `cross_device_execution_chain.py` 补充 WebRTC step；如否：在代码中明确标注"media-only sidecar"

9. **多设备动态 formation 完整实现**
   - 补全 `device_formation/` 的动态 formation 调整路径
   - 配套编写 multi-device formation 集成测试

10. **遗留路径清理**
    - 统计所有 `[DEPRECATED]` / `[COMPAT]` 路由的实际调用频次
    - 制定移除时间表，至少添加调用日志

### 长期（P3 改善）

11. **建立 Windows 本地执行链 CI**
    - 使用 GitHub Actions Windows Runner
    - 覆盖 `DesktopPresenceRuntime` + `DecisionExecutor` 的基础路径

12. **双仓接口稳定性合约（Interface Contract Testing）**
    - 将 AIP v3.0 消息 schema 提取为 JSON Schema 文件
    - V2 和 Android 两仓 CI 均验证自己实现的消息格式符合该 schema
    - 防止双仓协议悄悄分叉

---

## 附录 A：关键文件索引

| 文件路径 | 角色 |
|----------|------|
| `main.py` | 系统编排入口（SYSTEM_ORCHESTRATOR_AUTHORITY） |
| `core/system_orchestrator.py` | 7阶段启动序列 |
| `unified_launcher.py` | 下级 launcher，FastAPI 启动 |
| `galaxy_gateway/app.py` | FastAPI 应用，传输基底 |
| `galaxy_gateway/routes/websocket.py` | canonical device ingress |
| `galaxy_gateway/protocol/aip_v3.py` | AIP v3.0 协议定义（SSOT） |
| `galaxy_gateway/protocol/compat.py` | AIP v1/v2→v3 compat 层 |
| `galaxy_gateway/android_bridge.py` | Android action/payload 翻译适配器 |
| `galaxy_gateway/android/handlers/` | 按消息类型分解的处理器（PR-3 模块化） |
| `galaxy_gateway/device_router.py` | 路由基底（非编排选择器） |
| `galaxy_gateway/routing/device_selection.py` | 4步设备选择 |
| `core/unified/device_manager.py` | UDM — 设备状态 SSOT |
| `core/truth_integration_layer.py` | 设备 truth 收敛点 |
| `core/openclawd.py` | Subject Core（认知+执行核） |
| `core/command_router.py` | 跨设备路由器（唯一） |
| `core/desktop_presence_runtime.py` | Windows 运行时壳 |
| `core/local_execution_chain.py` | 本地执行链规范定义 |
| `core/cross_device_execution_chain.py` | 跨设备执行链规范定义 |
| `core/android_v2_continuity_contract.py` | Android-V2 连续性合约（7种场景） |
| `core/nats_bus.py` | NATS 消息总线（默认 no-op） |
| `core/session_manager.py` | 会话管理（JSON 文件持久化） |
| `core/replay_audit_persistence.py` | 可选 JSONL 审计持久化 |
| `core/canonical_session_truth.py` | Session truth（默认 in-memory） |
| `android: GalaxyConnectionService.kt` | Android 主服务（145KB） |
| `android: GalaxyWebSocketClient.kt` | Android WS 客户端（67KB） |
| `android: OfflineTaskQueue.kt` | Android 本地离线队列 |
| `android: AccessibilityActionExecutor.kt` | Android 无障碍执行 |
| `.github/workflows/ci.yml` | V2 主 CI（lint + v3 guard + compat smoke） |
| `.github/workflows/dual_repo_integration.yml` | 双仓集成 CI（传输+协议+Android E2E mock） |

---

## 附录 B：闭环状态汇总表（可复制粘贴）

| 能力 | 代码支撑 | CI 支撑 | 真实设备 | 结论 |
|------|----------|---------|----------|------|
| V2 启动序列 | ✅ | ✅ | — | 已闭环 |
| AIP v3 ingress | ✅ | ✅ | ❌ | 协议已闭环，设备需 mock |
| 设备注册回路 | ✅ | ✅ | ❌ mock | 已闭环（V2侧） |
| task_assign→Android | ✅ | ✅ | ❌ mock | 传输已闭环，设备需 mock |
| Android 执行（Accessibility） | ✅ | ✅ (JVM) | ❌ CI无 | 代码已闭环，CI 不含设备 |
| Android task_result 回传 | ✅ | ✅ mock | ❌ | 传输已闭环 |
| task_result 关键处理步骤 | ⚠️ 可选导入 | ❌ 不强制 | ❌ | **伪闭环** |
| Android 本地 AI 规划 | ⚠️ NoOp默认 | ❌ NoOp | ❌ | **伪闭环** |
| V2 session truth 持久化 | ⚠️ 可选路径 | ❌ 非默认 | ❌ | **未闭环** |
| V2 重启后 task 恢复 | ⚠️ 合约定义 | ❌ | ❌ | **未闭环** |
| NATS 分布式分发 | 🟡 no-op默认 | ❌ 无服务 | ❌ | **条件可用** |
| WebRTC | ⚠️ 旁道结构 | ❌ | ❌ | **未集成** |
| 多设备动态编排 | ⚠️ 静态已实现 | 🟡 部分 | ❌ | **局部闭环** |
| Windows 本地执行链 | 🟡 代码完整 | ❌ 无Windows CI | ❌ | **未 CI 验证** |
| 双仓真实 E2E | ❌ | ❌ | ❌ | **缺失** |

---

*本文档基于 `DannyFish-11/ufo-galaxy-realization-v2` 主分支代码及对 `DannyFish-11/ufo-galaxy-android` 的参照分析生成。不依赖 `docs/` 目录中任何既有审查文档。如需更新，请直接基于最新代码重新审查相关章节。*
