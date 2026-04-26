# 双仓联合纯代码证据审查：系统真实完成度与边界判断

> **审查对象**：`DannyFish-11/ufo-galaxy-realization-v2`（以下 V2） + `DannyFish-11/ufo-galaxy-android`（以下 Android）
>
> **证据来源**：`core/`、`galaxy_gateway/`、`.github/workflows/`、`tests/`、Android `service/`、`network/`、`planner/`、`grounding/`、`inference/`、`webrtc/`、`runtime/`、测试目录及 CI workflow。
>
> **明确不依赖**：`docs/` 目录内容、既有 PR 文字总结。

---

## 0. 先说结论

这套系统是一个**以 V2 为中心编排权威、以 Android 为持久执行参与方的中心式分布式智能体系统**。它不是骨架，核心传输-协议-执行主链已有真实代码和真实自动化测试支撑。但它还不是成熟平台：V2 truth 默认持久性不足，Android 本地 AI 依赖外部进程、默认不可用，双仓真正的 E2E 运行时 CI 不存在。

---

## 1. 双仓真实 canonical main path

### 1.1 V2 启动与 ingress

```
main.py
  └─ SystemOrchestrator.run_startup_sequence()  [core/system_orchestrator.py]
       └─ unified_launcher.py
            └─ FastAPI app  [galaxy_gateway/app.py]
                 └─ galaxy_gateway/routes/websocket.py
                      └─ /ws/device/{device_id}   ← canonical ingress (AIP v3)
                           └─ _handle_android_ws()
                                └─ normalise_to_v3_dict()  [galaxy_gateway/protocol/compat.py]
                                └─ AndroidBridge.handle_message()  [galaxy_gateway/android_bridge.py]
                                     ├─ handlers/registration.py    (device_register)
                                     ├─ handlers/heartbeat.py       (heartbeat, device_status)
                                     ├─ handlers/task_lifecycle.py  (task_result, task_end)
                                     └─ handlers/goal_execution.py  (goal_execution_result)
```

`galaxy_gateway/app.py` 明确声明自己是**内部传输基底**（"NOT a primary subject entrypoint"），Subject 权威从 `DesktopPresenceRuntime` → `OpenClawd` → `CommandRouter` 流入，gateway 负责把路由决策传递到设备端点。

### 1.2 task routing 链

```
DeviceRouter.route_task()  [galaxy_gateway/device_router.py]
  └─ routing/policy.py   analyze_command()
  └─ routing/device_selection.py  select_devices()
       ├─ Step 0: target_device_validator 准入预过滤
       ├─ Step 1: GatewayCapabilityRegistry 确定 exec_mode
       ├─ Step 2: capability_routing_gate.filter_by_required_capabilities()  ← PR-3 能力门
       ├─ Step 3: autonomous_filter
       └─ Step 4: DevicePoolManager.select_device()
  └─ routing/dispatch.py  dispatch_to_websocket()
       └─ build_aip_message(device_id, task_id, trace_id, command)  [AIP v3.0]
            └─ WebSocket send → Android
```

`DeviceRouter` 的文档明确：**路由基底，非编排选择器**。它在每次连接生命周期事件时通过 `_sync_connection_state_to_udm()` 向 `UnifiedDeviceManager`（UDM）写入规范状态；本地 `self.devices` 只是运行时 WebSocket 会话的操作缓存，非设备事实来源。

### 1.3 Android 主链

```
GalaxyConnectionService.onCreate()  [service/GalaxyConnectionService.kt, 145 KB]
  └─ GalaxyWebSocketClient.connect()  [network/GalaxyWebSocketClient.kt, 67 KB, OkHttp]
       └─ sendHandshake()  → device_register (AIP v3.0)

GalaxyWebSocketClient.handleMessage()
  └─ 收到 task_assign
       └─ GalaxyConnectionService.handleTaskAssign()
            └─ DelegatedRuntimeAcceptanceEvaluator.evaluate()
            └─ executeLocalTaskAssign()
                 └─ EdgeExecutor.handleTaskAssign()
                      ├─ screenshotProvider.captureJpeg()
                      ├─ plannerService.plan()     [LocalPlannerService → 外部 HTTP]
                      ├─ groundingService.ground() [LocalGroundingService → 外部 HTTP]
                      └─ accessibilityExecutor.execute()
            └─ sendTaskResult()  → V2 (task_result 消息)
```

### 1.4 各段主链定性

| 段 | 定性 |
|---|---|
| V2 WebSocket ingress → normalise → handler dispatch | **runtime-live 主链** |
| device_register / capability_report / task_assign 回路 | **runtime-live 主链** |
| Android GalaxyWebSocketClient → task_assign → task_result | **runtime-live 主链** |
| Android AccessibilityExecutor 执行 | **runtime-live 主链** |
| Android OfflineTaskQueue 离线缓冲 | **条件成立（有连接则绕过，离线时激活）** |
| V2 Takeover/Handoff v2 | **准主链（代码完整，无 E2E 自动化测试）** |
| Android MobileVlmPlanner / SeeClickGroundingEngine | **结构存在+外部依赖（非默认可用，见 §4.2）** |
| WebRTC 信令 / mesh / federation | **结构存在（无 CI 验证，无主链集成）** |
| V2 跨重启 session continuity | **不成立（默认 in-memory，见 §4.1）** |

---

## 2. 真实系统边界划分

### Control plane
V2 侧。`SystemOrchestrator`、`UnifiedDeviceManager`（UDM）、`CanonicalTask`、`CommandRouter`、`DeviceRouter`（routing substrate）、`CanonicalSessionTruthRuntime`。V2 是单一编排权威，明确拒绝把 gateway 或 Android 提升为并列权威。

### Execution plane
Android 侧。`GalaxyConnectionService`、`EdgeExecutor`、`AccessibilityActionExecutor`、`OfflineTaskQueue`。Android 是**持久执行参与方**而非控制权威——注释明确："Android is the **durable participant runtime**… NOT the canonical orchestration authority."

### Transport plane
`GalaxyWebSocketClient`（OkHttp）↔ `galaxy_gateway/routes/websocket.py`（FastAPI）；协议 AIP v3.0；compat 层在 V2 ingress 处规范化 v1/v2 消息。

### Truth plane
V2 UDM（设备事实来源）+ `CanonicalSessionTruthRuntime`（session truth，in-process ring buffer）+ `AttachedRuntimeSessionRegistry`（session 单权威注册表）+ `replay_audit_persistence.py`（可选接入的持久审计存储，append-only JSONL）。

Android 侧有 `OfflineTaskQueue`（持久离线队列）和 `BootReceiver`（设备重启后服务重启），构成本地执行连续性保证。

### Provider plane
V2 侧通过 provider routing 对接外部 LLM/VLM（OpenAI / Claude / Gemini / OneAPI / Ollama 等）。Android 侧通过 `LocalPlannerService` / `LocalGroundingService` 对接本地推理端点（127.0.0.1:8080 / 8081），需外部独立启动。

---

## 3. 哪些能力已真实闭环

以下均有代码调用链 + 自动化测试双重支撑。

### 3.1 V2 ↔ Android 基础传输主链

**证据**：`tests/integration/test_dual_repo_transport_harness.py`

该测试通过 **FastAPI TestClient 的真实 WebSocket 传输层**（非 mock 函数调用）验证：
1. `device_register` → `device_register_ack`
2. `capability_report` → `capability_report_ack` + 持久化到 bridge
3. V2 dispatch Future → `task_assign` → `task_result` → waiter 解除阻塞
4. 完整 canonical chain：register → capability → dispatch → result

注释原文："exercises the real `_handle_android_ws` FastAPI route via `fastapi.testclient.TestClient`, so every message travels through the actual JSON-over-WebSocket transport pipeline"。

### 3.2 AIP v3.0 协议 CI 守卫

**证据**：`.github/workflows/ci.yml`，job `v3-protocol-guard`

该 job 在每次 push/PR 运行，禁止在 `galaxy_gateway/`、`core/`、`enhancements/`、`tests/` 中直接引用 `aip_protocol_v2`（仅允许 deprecated stub 本身和测试文件）。这是一个 **blocking CI 门**，真实存在且有效。

### 3.3 协议回归测试

**证据**：`.github/workflows/dual_repo_integration.yml`，job `protocol-regression`

验证非 happy-path 场景：
- 设备重连后 V2 状态连续性保留
- unknown task_id 的 `task_result` 不引发 crash
- offline queue replay 不重复
- V2 ingress compat 层正确降级处理 AIP v2 消息

该 workflow 在 `galaxy_gateway/`、`core/`、集成测试文件改动时触发，设为 blocking。

### 3.4 Android 单元测试 + build CI

**证据**：`.github/workflows/android-ci.yml`（Android 仓）

步骤：`./gradlew :app:test`（JVM unit tests）→ `./gradlew assembleDebug`（APK build）→ `./gradlew lintDebug`。所有步骤为 blocking（`continue-on-error: false`）。

Android 测试目录覆盖：`agent/`、`api/`、`capability/`、`client/`、`config/`、`coordination/`、`data/`、`debug/`、`e2e/`、`history/`、`input/`、`integration/`、`local/`、`loop/`、`memory/`、`model/`、`network/`、`nlp/`、`observability/`、`protocol/`、`runtime/`、`service/`、`session/`、`speech/`、`trace/`、`ui/`、`webrtc/`。规模相当可观。

### 3.5 Android AccessibilityExecutor 执行主链

**证据**：`service/AccessibilityActionExecutor.kt`（实现文件），`service/GalaxyConnectionService.kt`（145 KB，真实调用链），AndroidManifest.xml 中 Accessibility Service 声明。E2EContractTest 使用 `OkAccessibility` mock 验证合约。

### 3.6 Android OfflineTaskQueue 本地持久化

**证据**：`network/OfflineTaskQueue.kt`（10 KB），有 Room/SharedPreferences 持久化实现，有 replay/dedup 逻辑。

### 3.7 V2 S6 compat smoke + SLO metrics

**证据**：`.github/workflows/ci.yml`，jobs `s6-compat-smoke` + `slo-metrics-check`，均为 blocking，每次 PR 运行。

---

## 4. 哪些关键能力尚未完成

### 4.1 V2 truth/session/task lifecycle durability — 默认不足

**证据**：`core/canonical_session_truth.py`

> "Durable audit sink (PR-B2) — the ring-buffer runtime is still in-process authoritative; when a `DurableAuditStore` is attached via `set_audit_store`, each record is also written to the store so truth merge evidence survives process lifetime."

关键词：**"is still in-process authoritative"**；`DurableAuditStore`（`core/replay_audit_persistence.py` — append-only JSONL）是**可选接入**，非默认。

`core/replay_audit_persistence.py` 头注释：该存储"survive process lifetime"，但其接入路径是 `CanonicalSessionTruthRuntime.set_audit_store()`，非启动序列默认行为。

**结论**：V2 重启后，in-flight task 和 session truth 默认无法恢复。DurableAuditStore 提供了路径但非默认接通。

### 4.2 Android 本地 AI — 默认不可用

**证据**：`inference/LocalPlannerService.kt`、`inference/LocalGroundingService.kt`

两者都是 **interface**，默认实现是 `NoOpPlannerService` / `NoOpGroundingService`：

```kotlin
// NoOpPlannerService.plan()
return LocalPlannerService.PlanResult(
    steps = emptyList(),
    error = "MobileVLM planner not available: model not loaded"
)
// NoOpGroundingService.ground()
return LocalGroundingService.GroundingResult(
    x = 0, y = 0, confidence = 0f, element_description = "",
    error = "SeeClick grounding not available: model not loaded"
)
```

`MobileVlmPlanner.kt`（planner/）和 `SeeClickGroundingEngine.kt`（grounding/）调用外部 HTTP 端点 `127.0.0.1:8080` / `127.0.0.1:8081`。这两个服务**不打包在 APK 内**，需要在设备上独立部署 llama.cpp/NCNN 推理进程。`E2EContractTest.kt` 也使用 `OkPlanner`/`OkGrounder` mock 而非真实实现。

**结论**：Android 本地 AI 完整代码存在，接口设计清晰，但：(a) 默认 NoOp；(b) 真实推理需外部进程；(c) 没有 APK 级别自洽集成。

### 4.3 Android E2E CI — 不存在

**证据**：Android 的 `android-ci.yml` 只运行 JVM unit tests（`./gradlew :app:test`）。`app/src/test/java/com/ufo/galaxy/e2e/E2EContractTest.kt` 是纯 JVM 合约测试，使用 mock 实现（`OkPlanner`、`OkGrounder`、`OkAccessibility`），不涉及真实设备或模拟器。

该文件注释："For the full E2E manual test flow see docs/e2e-verification.md."——**E2E 是手工流程文档，非 CI 自动化**。

`tests/integration/test_android_ci_baseline.py`（V2 侧）注释："For full dual-repo CI, the `ufo-galaxy-android` repository should have its own CI pipeline that runs `./gradlew assembleDebug`... The Android-side CI is **outside the scope of this V2 repository** but is a required follow-up action."

**结论**：Android 侧无 emulator / instrumentation / real-device E2E 自动化 CI。

### 4.4 双仓真实跨仓 E2E — 不存在

**证据**：`dual_repo_integration.yml` 中的"Android" mock client（`AndroidProtocolClient`，Python 类，模拟 Android 协议行为）是 V2 侧 FastAPI TestClient 内运行的 Python mock，而非真实 Android APK 进程。

**结论**：双仓协同的"集成测试"实为"V2 侧用 Python mock 模拟 Android 协议"——这是重要的回归守卫，但不是真正双仓 E2E。

### 4.5 WebRTC / mesh / federation — 结构存在

**证据**：
- Android：`webrtc/IceCandidateManager.kt`、`webrtc/WebRTCSignalingClient.kt`、`webrtc/SignalingMessage.kt`、`webrtc/TurnConfig.kt`
- V2：`galaxy_gateway/p2p_connector.py`
- 测试：Android `app/src/test/java/com/ufo/galaxy/webrtc/` 目录存在

但 WebRTC 不在 `dual_repo_integration.yml` 的测试覆盖内，`android-ci.yml` 中也无 WebRTC 专项验证，且 V2 主链中不经过 WebRTC 路径。

**结论**：信令层代码完整，但未集成到任何 CI blocking gate，也未集成到主执行路径。

### 4.6 capability gate 强制执行 — 有条件

**证据**：`routing/device_selection.py`，Step 2 调用 `capability_routing_gate.filter_by_required_capabilities()`（PR-3 hard gate）。但 gate 的有效性依赖 capability 数据质量——如果 Android 端 capability_report 未上报准确字段（如 `accessibility_ready=false`），gate 可能放行不满足条件的设备，或因缺失数据而行为不确定。

### 4.7 V2 provider routing strict single-entry — 有条件

V2 的 provider routing 存在 legacy orchestrator facade 兼容路径。`core/canonical_task.py` 明确：
> "Legacy orchestrators remain as facade/planner helpers; they may *contribute* to a `CanonicalTask` but MUST NOT dispatch outside the spine."

这是架构约束文档，但 legacy façade 在代码中仍存在。Canonical spine 通过 `CommandRouter.route_envelope()` 强制，但 S6 compat smoke 测试正是为了守卫 legacy→compat→v3 回归而存在。

---

## 5. 双仓最关键不对称

| 维度 | V2 | Android |
|---|---|---|
| 连续性/持久化 | CanonicalSessionTruthRuntime **默认 in-memory**；DurableAuditStore 可选接入 | OfflineTaskQueue **默认持久**；BootReceiver 开机自启 |
| 本地执行成熟度 | 编排+路由+dispatch 已成熟 | Accessibility 执行已成熟 |
| 本地 AI | 通过 provider routing 调用外部 LLM（运行时按 API key 确定） | 本地 AI 接口完整但**默认 NoOp**，需外部推理进程 |
| E2E CI | V2 侧有 mock-Android 协议回归 CI | 无 emulator/device E2E CI |
| 协议守卫 | 有 v3-protocol-guard、S6 compat smoke（blocking） | Android 侧仅 JVM unit test + build |

**核心不对称**：Android 的**本地持久化**（OfflineTaskQueue、BootReceiver）比 V2 的**session truth durability** 更成熟；V2 的**编排架构**比 V2 的**durable recovery** 更成熟；Android 的**OS-level 执行**比 Android 的**本地 AI** 成熟得多。

---

## 6. 测试与 workflow 真实支持度

| 验证项 | 存在且 blocking | 骨架/Advisory |
|---|---|---|
| V2 lint (flake8 + black + isort) | ✅ `ci.yml` | — |
| AIP v3 协议守卫 | ✅ `ci.yml` v3-protocol-guard | — |
| S6 compat smoke | ✅ `ci.yml` | — |
| SLO metrics schema | ✅ `ci.yml` | — |
| V2 传输层集成（mock Android） | ✅ `dual_repo_integration.yml` transport-harness | — |
| V2 协议回归（reconnect/offline/compat） | ✅ `dual_repo_integration.yml` | — |
| CodeQL 安全扫描 | ✅ `codeql.yml` | — |
| node governance | ✅ `node-governance.yml` | — |
| supply chain | ✅ `supply-chain.yml` | — |
| Android build + JVM unit test + lint | ✅ `android-ci.yml` | — |
| Android emulator / instrumentation CI | — | ❌ 不存在 |
| Android E2E 运行时自动化 | — | ❌ 手工文档 |
| 双仓真实 APK ↔ V2 集成测试 | — | ❌ 不存在 |
| WebRTC CI 验证 | — | ❌ 不存在 |
| V2 跨重启 durable recovery CI | — | ❌ 不存在 |

V2 侧的测试目录有 **619 个** `.py` 测试文件，涵盖几乎所有模块。但测试数量≠全部为 blocking CI：很多测试文件并非都注册进 CI workflow；blocking 覆盖集中在 `tests/integration/`、`tests/test_s6_*`、`tests/test_slo_*` 等。

---

## 7. 关于用户提出的六层框架与 AHE 四层——代码侧判断

用户在对话中提出六层纵向运行时栈和 AHE 四层横向治理栈作为架构参照。基于代码现实，简要映射如下：

### 六层 → 代码对应与当前成熟度

| 层 | 对应代码（主要） | 当前成熟度 |
|---|---|---|
| 接入交互层 | FastAPI WebSocket ingress、`GalaxyWebSocketClient`、`normalise_to_v3_dict()` | ✅ 成熟 |
| 上下文与能力判定层 | `handlers/registration.py`、`capability_routing_gate`、`GatewayCapabilityRegistry`、`DelegatedRuntimeAcceptanceEvaluator` | ✅ 成熟（gate 有条件执行） |
| 状态与记忆层 | `CanonicalSessionTruthRuntime`（V2 in-memory）、`AttachedRuntimeSessionRegistry`、`OfflineTaskQueue`（Android 持久） | ⚠️ Android 侧 > V2 侧 |
| 任务编排层 | `OpenClawd`、`CommandRouter`、`DeviceRouter`、routing 三件套 | ✅ 成熟，最核心 |
| 执行运行时层 | `EdgeExecutor`、`GalaxyConnectionService`、`AccessibilityActionExecutor` | ✅ 成熟（Accessibility 链） |
| 外部能力与模型层 | V2 provider routing（LLM）、`MobileVlmPlanner`/`SeeClickGroundingEngine`（Android 本地 AI） | ⚠️ V2 成熟，Android 侧非默认可用 |

### AHE 四层 → 代码对应与当前成熟度

| AHE 层 | 对应代码 | 成熟度 |
|---|---|---|
| 接入适配层 | AIP v3 compat、`GalaxyWebSocketClient`、registration handlers | ✅ 成熟 |
| 编排管理层 | `SystemOrchestrator`、`CanonicalTask`、`CommandRouter`、task lifecycle | ✅ 成熟 |
| 协同决策层 | `routing/device_selection.py`、capability gate、acceptance evaluator | ⚠️ 骨架+部分真实（无多 Agent 博弈/全局最优决策） |
| 观测治理层 | CI workflows（blocking gates）、`replay_audit_persistence`、SLO metrics | ⚠️ 观测越来越强，部分已 blocking；durable recovery 仍不足 |

---

## 8. 最终系统阶段判断

### 不是骨架期

- 有真实传输主链（WebSocket ↔ FastAPI，有集成测试）
- 有真实协议 CI 守卫（blocking）
- 有真实 Android Accessibility 执行链
- 有真实 Android JVM 单元测试 + build CI
- V2 routing/dispatch/task lifecycle 已完整

### 还不是成熟平台/准生产

- V2 truth 默认非 durable（跨重启恢复路径存在但未接通）
- Android 本地 AI 默认 NoOp（推理能力依赖外部进程，非 APK 自洽）
- 无双仓真实 E2E CI（现有"双仓"测试是 V2 侧 Python mock）
- WebRTC / mesh / federation 无 CI 守卫，未接主链
- capability gate 的有效性依赖 Android 端上报准确度

### 当前阶段

> **有功能主链的工作原型，正在向平台化演进。**

核心卡口（优先级排序）：

1. **V2 truth/session durability 默认化**：`DurableAuditStore` + 跨重启任务恢复路径需接入启动序列，而非可选。
2. **Android 本地 AI 自洽化**：将推理进程（llama.cpp/NCNN）打包到 APK 或提供一键启动脚本，使 `NoOpPlannerService` 不再是默认实现。
3. **双仓真实 E2E CI**：在 Android 仓引入 emulator + 真实 WebSocket 连接 V2 mock server 的 instrumentation 测试，替换当前纯 JVM mock。

---

*本文档严格基于双仓 main branch 当前真实代码、真实调用链、真实测试、真实 CI/workflow，不代表任何历史阶段或规划方向。*
