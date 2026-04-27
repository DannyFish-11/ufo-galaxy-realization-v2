# 双仓系统成熟化进展复评（基于当前主分支代码）

> **审查时间点**：2024 年当前主分支  
> **审查对象**：`DannyFish-11/ufo-galaxy-realization-v2` + `DannyFish-11/ufo-galaxy-android`  
> **定位**：不重复 #843/844/845 叙事，直接基于当前真实代码现状做进展判断  
> **证据原则**：所有结论以当前代码/测试/workflow 为主证据，不把"计划中"写成"已完成"

---

## 一、相比旧审查（843/844/845）时点，系统真实推进了多少

### 已推进为默认主链行为（从"结构存在"进入"真实运行"）

| 能力 | 旧状态 | 当前状态 | 代码证据 |
|------|--------|----------|----------|
| AIP v3 协议 | 有接口、有结构 | 默认主链，旧 v2 引用被 CI 强制阻断 | `ci.yml:v3-protocol-guard`，`galaxy_gateway/routes/websocket.py`，`android_bridge.py` 消息类型枚举 |
| capability_enforcement_hardener | 无 | STRICT 模式已实现，hard reject on missing caps，CI blocking 验证 | `core/capability_enforcement_hardener.py`，`dual_repo_integration.yml:capability-enforcement-gate` |
| canonical_capability_status 注册表 | 无 | 所有 capability 已有显式状态分类，local_ai/mesh/federation 明确标记 STRUCTURAL_ONLY | `core/canonical_capability_status.py:get_canonical_capability_status_registry()` |
| runtime_readiness_matrix + release_blocking_gate | 无 | 矩阵评估 + 阻断 CI（exit code 1） | `core/release_blocking_gate.py`，`dual_repo_integration.yml:release-readiness-gate` |
| 双仓 transport harness | 无 | protocol regression + transport harness + android runtime e2e 均已 CI blocking | `tests/integration/test_dual_repo_transport_harness.py`, `test_android_runtime_e2e.py` |
| durable_result_idempotency | 无 | 文件级原子写，进程重启后 result dedup 持续有效 | `core/durable_result_idempotency.py:DurableResultIdSet`（默认路径 `data/result_idempotency_set.json`） |
| task_lifecycle_persistence | 无 | in-flight task snapshot 文件持久化，disposition 分类，restart recovery 接口 | `core/task_lifecycle_persistence.py:TaskLifecyclePersistenceStore` |
| durable_audit_store 自动挂载 | 手动/可选 | startup 第 19 步自动挂载，wire 到 ReplayFoundation / CanonicalSessionTruth / AuditEventSemantics | `core/startup.py:824 wire_durable_audit_store()` |
| Android CI pipeline | 无 | `./gradlew :app:test` + `assembleDebug` + `lintDebug` 已 CI 自动运行 | `.github/workflows/android-ci.yml`（ufo-galaxy-android） |
| Android capability 状态明确上报 | 无 | `NoOpPlannerService` / `NoOpGroundingService` 有明确 WarmupResult，`capability_report` 可返回失败 warmup 状态 | `inference/LocalPlannerService.kt:warmupWithResult()`，`WarmupResult.kt` |
| openclawd.py 主链 capability gate 调用 | 无 | `enforce_explicit_route_capability_gate` 已在 `core/openclawd.py` 的 explicit-route dispatch path 被调用 | `core/openclawd.py:3722-3725` |
| WORKSTREAM_GAP_REGISTRY 机器可读 | 无 | 7 个已命名 gap 以代码可读结构存在，`resolved=False` 防止误标 | `core/dual_repo_system_map.py:WORKSTREAM_GAP_REGISTRY` |

### 仍停留在"结构存在/条件性激活"

| 能力 | 当前真实状态 |
|------|-------------|
| V2 session truth 默认持久化 | `CanonicalSessionTruthRuntime` ring buffer 仍是主运行时；`set_audit_store` 是 observational attachment，不替换运行时 truth authority；官方注释明确写 `# Optional durable snapshot store (default-on via startup wiring)` |
| inflight task 跨重启恢复 | `TaskLifecyclePersistenceStore` 已实现 snapshot + disposition，但 `runtime_restart_recovery.py` 的 `INFLIGHT_TASK_LIFECYCLE_RECOVERY_POLICY` 明确说是"policy sentinel"，实际 recover path 调用是否完整接通需专项验证 |
| single truth ingress 完全收口 | `GAP_RUNTIME_TRUTH_SINGLE_INGRESS` 仍 `resolved=False`；websocket_handler 的 UDM write-through 已存在（line 456-523），但旧 compat cache 仍存在 mirror write |
| capability gate 全路径强制 | `GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT` 仍 `resolved=False`；explicit-route path 已有，但 `send_gateway_command` 多数调用点不传 `required_capabilities`，gate 实质上 advisory 路径仍可绕 |
| Android local AI runtime（planner/grounding） | `LocalPlannerService` / `LocalGroundingService` 均以 `NoOpPlannerService` / `NoOpGroundingService` 为默认实现；`isModelLoaded()` 返回 `false`；planner 返回 `"MobileVLM planner not available: model not loaded"` |
| 真实 emulator/device 级 E2E | `test_android_runtime_e2e.py` 使用 `AndroidRuntimeSimulator` 在进程内模拟，不是真实 Android 设备/emulator；这是有价值的 runtime-level 测试，但不等于设备级 E2E |
| WebRTC / mesh / federation | 代码存在，明确标记 `STRUCTURAL_ONLY` 或 `EXPERIMENTAL`，capability 注册表已显式分类 |

---

## 二、V2 durable control plane 当前真实进展

### 已落地的改进

**durable_result_idempotency（真正 durable）**  
`core/durable_result_idempotency.py` 实现了文件级、原子写的 result ID dedup。默认路径 `data/result_idempotency_set.json`，进程重启后 dedup 状态持续有效。这是一个真实的 durable 闭环，不是可选接口。

**task_lifecycle_persistence（snapshot layer 已实现）**  
`core/task_lifecycle_persistence.py` 提供 `TaskLifecyclePersistenceStore`：原子写 snapshot，`InFlightTaskDisposition` 分类（RESUMABLE / REPLAY_ONLY / REISSUABLE / TERMINAL_ON_INTERRUPT），`restore_inflight_tasks_from_snapshot` 供 recovery 调用。

**durable_audit_store 自动挂载（startup step 19）**  
`core/startup.py:824` 调用 `wire_durable_audit_store()`，在进程启动时自动将 `DurableAuditStore` 接入 `ReplayFoundation`、`AuditEventSemantics`、`CanonicalSessionTruthRuntime`。这是 observational durability，不是 truth authority 本身。

### 仍是关键卡口

**session truth 仍是 in-memory ring buffer 为主运行时**  
`CanonicalSessionTruthRuntime` 的 `_store` 是 `deque`（in-memory ring buffer）。`set_audit_store` 挂载后，record 会被写到 durable store，但 runtime authority 仍是内存 deque。进程重启后，ring buffer 清空，session truth 需要从 audit store 重建——这条恢复路径目前没有显式接通的代码。

**inflight task recovery 调用链未完全验证**  
`restore_inflight_tasks_from_snapshot` 存在，`RuntimeRestartRecoveryCoordinator` 引用了 `INFLIGHT_TASK_LIFECYCLE_RECOVERY_POLICY`，但从 startup 到 coordinator 到实际任务重新分发的完整调用链，未见明确的端到端测试覆盖。`WORKSTREAM_GAP_REGISTRY` 中 `GAP_V2_TRUTH_PERSISTENCE` 仍 `resolved=False`。

**结论**：V2 control plane 相比旧审查时点确实有进展：result idempotency 已 durable，audit store 已自动挂载，task lifecycle snapshot 层已实现。但"完全 durable control plane"的核心要求——session truth 默认持久化 + 跨重启无损恢复——尚未完全跨过门槛，仍是"强编排 + 部分 durable"。

---

## 三、Android local intelligence runtime 当前真实进展

### Android 执行端（已成熟）

以下能力有真实代码主链，是当前最成熟的部分：

- **WebSocket transport**：`network/` 目录，AIP v3 格式，connect/register/capability_report/task_assign/task_result 完整消息序列
- **Accessibility 执行链**：`service/` 目录，真实 accessibility service + input service
- **offline queue + reconnect**：有 reconnect 逻辑，offline task queue
- **Android CI**：`./gradlew :app:test` + `assembleDebug` + `lintDebug` 已 CI 运行，有单元测试
- **capability report 诚实上报**：`WarmupResult` 机制使 planner/grounding 能上报 warmup 失败状态

### Android 本地智能端（NoOp 为默认）

当前代码状态直接、诚实：

```kotlin
// inference/LocalPlannerService.kt
class NoOpPlannerService : LocalPlannerService {
    override fun loadModel(): Boolean = false
    override fun isModelLoaded(): Boolean = false
    override fun plan(...): PlanResult = PlanResult(
        steps = emptyList(),
        error = "MobileVLM planner not available: model not loaded"
    )
}
```

```kotlin
// inference/LocalGroundingService.kt  
class NoOpGroundingService : LocalGroundingService {
    override fun loadModel(): Boolean = false
    override fun isModelLoaded(): Boolean = false
    override fun ground(...): GroundingResult = GroundingResult(
        x = 0, y = 0, confidence = 0f,
        element_description = "",
        error = "SeeClick grounding not available: model not loaded"
    )
}
```

- **LocalPlannerService 接口**：定义完整（`plan`/`replan`/`loadModel`/`unloadModel`/`warmupWithResult`），目标模型 `mtgv/MobileVLM_V2-1.7B`，目标 runtime `llama.cpp` 或 `MLC-LLM`
- **LocalGroundingService 接口**：定义完整，目标模型 `njucckevin/SeeClick`，目标 runtime `NCNN`/`MNN`
- **runtime/ 目录**：有 `AndroidAppLifecycleTransition.kt` 等多个 runtime 相关文件，但默认注入的 planner/grounding 实现均为 NoOp
- **模型资产管理**：无 manifest、无 sha256、无 model cache 管理器；HF 权重依赖手工下载或外部 localhost 服务
- `WORKSTREAM_GAP_REGISTRY` 中 `GAP_ANDROID_LOCAL_AI_DEFAULT_OFF` 仍 `resolved=False`

**结论**：Android 是"成熟的执行 participant + 接口完整的智能骨架 + NoOp 默认实现"。能力诚实性已有明确提升（`NoOp` 返回结构化错误而不是静默失败），但本地 AI runtime 离"默认可用"仍有整个实现距离。

---

## 四、双仓 runtime E2E / enforcement / release posture 当前真实进展

### 真实进展

**双仓 CI workflow 已建立（dual_repo_integration.yml）**  
7 个 CI jobs，全部 blocking：
- `transport-harness`：transport layer 协议验证
- `protocol-regression`：AIP v3 regression 覆盖
- `android-ci-baseline`：V2 侧 Android 合约验证
- `android-runtime-e2e`：`AndroidRuntimeSimulator` 六步序列（register→capability_report→task_assign→execution→task_result→continuation）
- `capability-enforcement-gate`：`CapabilityHardRejectError` 验证，override 需 audit reason
- `release-readiness-gate`：`release_blocking_gate.py` exit code 验证 + readiness matrix
- `protocol-contract-drift-guard`：AIP v3 版本字符串稳定性、dispatch 模块可导入性

**capability enforcement 已硬化（STRICT 模式）**  
`core/capability_enforcement_hardener.py` 中 `EnforcementMode.STRICT` 触发 `CapabilityHardRejectError`，携带 missing capabilities + audit_id。`SILENT_BYPASS_PROHIBITED_ON_MAINLINE_POLICY` 是有代码实体的策略 sentinel。

**capability status 注册表已覆盖 14+ capabilities**  
`tap`/`screenshot`/`task_assign`/`task_result`/`register` → `ACTIVE_MAINLINE`；`local_ai`/`mesh`/`federation` → `STRUCTURAL_ONLY`；`webrtc`/`advanced_handoff` → `EXPERIMENTAL`。分类由 CI blocking 验证（`capability-enforcement-gate` job）。

**release_blocking_gate.py 已 blocking**  
运行时检查四个 criteria：runtime smoke / capability state mismatch / protocol drift / readiness matrix BLOCKED。任何 critical failure exit code 1 阻断 CI。

### 仍是 gap

**真实 Android emulator/设备级 E2E 仍缺失**  
`test_android_runtime_e2e.py` 的 `AndroidRuntimeSimulator` 在进程内用 mock WebSocket 模拟，不启动 Android 进程、不走真实网络、不运行真实 accessibility service。这是 runtime-path 级别的验证，但 `GAP_JOINT_INTEGRATION_TEST` 明确标记 `resolved=False`：

```python
WorkstreamGapEntry(
    gap_id="GAP_JOINT_INTEGRATION_TEST",
    severity=GapSeverity.P0,
    description=(
        "No automated test framework verifies the full dual-repo path: "
        "V2 gateway → Android WebSocket → local capability execution → "
        "result return → V2 completion ingress. All current tests are "
        "single-repo unit or structural tests. A real Android device or "
        "Android emulator is required for true E2E coverage."
    ),
    resolved=False,
)
```

**GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT 仍 P0**  
`send_gateway_command` 的多数调用点不传 `required_capabilities`，gate 在这些路径上实质上跳过。enforcement 目前只对 explicit-route path 有效。

**Android CI 无 emulator smoke**  
`android-ci.yml` 运行 `./gradlew :app:test`（JVM 单测）+ `assembleDebug` + lint，但没有 emulator 级 instrumented test，没有 WebSocket 连接 smoke。

---

## 五、当前最成熟与最不成熟的部分

### 最成熟的部分（当前可被信任）

1. **AIP v3 协议层 + transport harness**  
   协议栈最成熟。消息格式、版本字符串、handler 注册、dispatch 路径均有 CI blocking 覆盖，旧 v2 引用被 CI 强制阻断。

2. **Android 执行端（websocket + accessibility + reconnect + offline queue）**  
   执行参与者链路成熟。从 WebSocket 建立到 task_assign 接收到 accessibility 执行到 task_result 回传的完整链路有代码主链支撑，Android CI 自动运行。

3. **capability status 注册表 + enforcement hardener**  
   能力边界分类最清晰。14+ capabilities 显式分类，STRICT 模式 hard reject，override 需 audit reason，CI blocking 验证。这是相比旧审查最大的单点进展之一。

4. **release_blocking_gate + readiness matrix**  
   治理层已有可执行的 blocking gate，不再纯 advisory。

5. **durable_result_idempotency**  
   result 去重已真正 durable（文件级，原子写），重启后有效。

### 最不成熟的部分（当前卡口）

1. **V2 session truth 跨重启恢复**（P0）  
   session truth ring buffer 重启后清空，从 audit store 重建的路径未完整接通。这是中心 authority 最核心的 durable 缺口。

2. **Android local AI runtime**（P1）  
   `NoOpPlannerService` / `NoOpGroundingService` 是默认实现。本地 AI 仍是"接口完整的骨架"，不是"默认可用的 runtime"。无模型资产管理，无 runtime lifecycle manager。

3. **真实设备/emulator 级 E2E**（P0）  
   所有 E2E 测试都在进程内 simulate，没有真实 Android 进程参与的自动化验证。

4. **capability gate 全路径强制**（P0）  
   `send_gateway_command` 多数调用点 gate 仍可绕过。

5. **inflight task recovery 完整调用链**（P0/P1）  
   snapshot 层和 disposition 分类已实现，但从 startup 到真实任务 re-dispatch 的完整恢复链路未见端到端覆盖。

---

## 六、当前阶段判断：是否从"强工作原型"进入"准成熟系统"？

**判断：尚未进入"准成熟系统"，但已明确超过"纯原型"阶段，处于"系统整合加固期"。**

### 支撑这个判断的代码证据

**正向证据（超过纯原型）**：
- CI 已有 7 个 blocking 验证 job（不再只是 smoke）
- capability enforcement 已有 hard reject 路径（不再纯 advisory）
- durable_result_idempotency 已真正跨重启有效
- release_blocking_gate 已产生 CI exit code
- Android CI 自动运行
- capability status 注册表已覆盖并机器可检查
- WORKSTREAM_GAP_REGISTRY 已代码化，防止误标 resolved

**阻断"准成熟"的证据**：
- `GAP_V2_TRUTH_PERSISTENCE` P0，`resolved=False`：V2 session truth 不默认 durable
- `GAP_JOINT_INTEGRATION_TEST` P0，`resolved=False`：无真实设备 E2E
- `GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT` P0，`resolved=False`：gate 仍可绕
- Android local AI：`NoOpPlannerService` 是默认实现

### 门槛差距

要进入"准成熟系统"，最少需要跨过两道门槛：

**门槛 A**：V2 session truth + inflight task recovery 默认 durable 并完整接通  
→ `GAP_V2_TRUTH_PERSISTENCE` 从 `resolved=False` 变为真实代码闭环

**门槛 B**：Android local AI 从 NoOp 变为有默认 runtime lifecycle manager  
→ 不是要求"完整本地 LLM 可用"，而是要求 runtime manager 存在、capability 状态诚实联动

这两道门槛对应的正是 PR-1（V2 durable control plane）和 PR-2（Android local intelligence runtime）的核心诉求。

---

## 七、PR-1/2/3 是否落在主链问题上

基于以上分析：

| PR | 目标 | 是否命中主链 gap | 优先度判断 |
|----|------|-----------------|------------|
| PR-1：V2 durable control plane | session truth 默认持久化 + inflight task 跨重启恢复 | ✅ 命中 `GAP_V2_TRUTH_PERSISTENCE`（P0）+ 完成 durable recovery 调用链 | 最高优先 |
| PR-2：Android local intelligence runtime | local runtime manager + capability honesty + degraded/fallback 显式 | ✅ 命中 `GAP_ANDROID_LOCAL_AI_DEFAULT_OFF`（P1）+ 从 NoOp 变为 managed runtime | 次高优先 |
| PR-3：dual-repo runtime E2E + enforcement + release | emulator E2E + capability gate 全路径强制 + release posture | ✅ 命中 `GAP_JOINT_INTEGRATION_TEST`（P0）+ `GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT`（P0）| 与 PR-1 并行可做 |

**三个 PR 都直接命中当前最大的未关闭 P0/P1 gap，没有在已解决的问题上做功。**

---

## 附：当前 WORKSTREAM_GAP_REGISTRY 状态速查

| Gap ID | Title | Severity | Resolved |
|--------|-------|----------|---------|
| GAP_JOINT_INTEGRATION_TEST | Dual-repo joint integration test framework missing | P0 | ❌ |
| GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT | capability_routing_gate not enforced by default | P0 | ❌ |
| GAP_V2_TRUTH_PERSISTENCE | V2 task lifecycle and session truth persistence on restart missing | P0 | ❌ |
| GAP_RUNTIME_TRUTH_SINGLE_INGRESS | Runtime truth ingress convergence incomplete | P1 | ❌ |
| GAP_ANDROID_CI | Android repository CI pipeline missing | P1 | ❌¹ |
| GAP_ANDROID_LOCAL_AI_DEFAULT_OFF | Android local AI / on-device inference not activated by default | P1 | ❌ |
| GAP_RELEASE_GATE_HARD_ENFORCEMENT | Governance/release gate not wired to hard CI | P2 | ❌² |

注：
- ¹ `GAP_ANDROID_CI` 在代码里标记 `resolved=False`，但 Android CI yml 已存在并运行 build + unit test + lint。需要确认 resolved 状态是否需要更新，或者 gap 描述的是更完整的 CI（emulator + protocol smoke）。
- ² `release_blocking_gate.py` 已 CI blocking，部分关闭了 P2 gap，但 `GAP_RELEASE_GATE_HARD_ENFORCEMENT` 代码里仍 `resolved=False`，需要专项确认。

---

*本文档基于当前主分支真实代码直接分析，不引用旧审查文档结论作为判断依据。所有"resolved=False"引用来自 `core/dual_repo_system_map.py:WORKSTREAM_GAP_REGISTRY`。*
