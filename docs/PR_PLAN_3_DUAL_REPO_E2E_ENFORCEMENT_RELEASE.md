# PR-3：Dual-Repo Runtime E2E / Enforcement / Release Closure

> **目标仓库**：`DannyFish-11/ufo-galaxy-realization-v2`（主要）+ `DannyFish-11/ufo-galaxy-android`（E2E 触发端）  
> **优先级**：P0（关闭 `GAP_JOINT_INTEGRATION_TEST` + `GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT`）  
> **可与 PR-1 并行推进**  
> **核心问题**：当前 E2E 是进程内模拟，capability gate 全路径仍可绕，release posture 部分仍 advisory

---

## Problem Statement

当前双仓验证状态：

1. **`test_android_runtime_e2e.py` 是进程内 simulation**：`AndroidRuntimeSimulator` 用 mock WebSocket，不启动 Android 进程，不走真实网络，不运行 accessibility service。这是有价值的 runtime-path 测试，但 `GAP_JOINT_INTEGRATION_TEST`（P0）明确说"A real Android device or Android emulator is required for true E2E coverage"，`resolved=False`
2. **`capability gate` 多数路径可绕**：`send_gateway_command` 多数调用不传 `required_capabilities`，`GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT`（P0）`resolved=False`
3. **`GAP_ANDROID_CI`** 代码里 `resolved=False`：Android CI 有 build + unit test，但无 emulator smoke，无 WebSocket 协议 smoke

---

## 目标

1. 建立双仓真实 runtime 级 E2E 验证（emulator 或 mock-process 级，不依赖真实硬件）
2. 将 capability gate 推进为 `send_gateway_command` 的默认行为（而不是需要传参才激活）
3. 关闭所有 P0 enforcement gap，使 release posture 真正 hard

---

## 具体工作项

### 1. 双仓 E2E：AndroidRuntimeProcess 级验证

**文件**：`tests/integration/test_android_runtime_process_e2e.py`

目标：从 V2 gateway 发起 task dispatch，到 Android 侧完整消费 + 执行 + 回传 task_result，由 V2 continuation resolver 关闭。

实现方案（不依赖真实设备）：
- 使用 Python 侧 WebSocket client 模拟 Android 设备的完整消息序列
- 但**不使用 mock WebSocket**，而使用真实 `asyncio`/`websockets` 连接到本地 V2 gateway 实例
- V2 gateway 以 `GALAXY_ENV=test` 启动，使用随机端口
- 验证序列：connect → register_ack → capability_report_ack → task_assign (V2→Android) → task_result (Android→V2) → continuation resolved

这等价于"Android 侧的网络级 integration test"，不需要 Android SDK，不需要 emulator，但网络栈是真实的。

```python
# 测试结构
async def test_dual_repo_runtime_e2e_network():
    """Full network-level E2E: real WebSocket, real gateway, protocol-level Android simulation."""
    async with GatewayTestInstance() as gateway:
        async with websockets.connect(f"ws://localhost:{gateway.port}/ws/device/test-device") as ws:
            # 1. register
            await ws.send(json.dumps({...device_register_payload...}))
            ack = json.loads(await ws.recv())
            assert ack["type"] == "device_register_ack"
            # 2. capability_report ... 3. receive task_assign ... 4. send task_result
            # 5. verify V2 continuation resolved
```

### 2. Android CI 增加 WebSocket 协议 smoke

**文件**：`.github/workflows/android-ci.yml`（ufo-galaxy-android）+ 新 `app/src/test/.../WebSocketProtocolSmokeTest.kt`

目标：Android CI 验证 AIP v3 消息格式正确性（在 JVM 单测中，不需要 emulator）。

```kotlin
@Test
fun testDeviceRegisterMessageFormat() {
    val msg = AIPMessageV3(
        type = "device_register",
        version = "3.0",
        deviceId = "test-device",
        ...
    )
    val json = Json.encodeToString(msg)
    assertNotNull(JsonParser.parseString(json))
    assertTrue(json.contains(\"version\"))
    assertTrue(json.contains(\"3.0\"))
}
```

### 3. Capability Gate 全路径强制（核心改动）

**文件**：`core/openclawd.py` 或 `galaxy_gateway/routing/dispatch.py`

当前：`send_gateway_command` 中只有 explicit-route path 调用 `enforce_explicit_route_capability_gate`，大多数调用点不传 `required_capabilities`。

需要：**在 `send_gateway_command` 的主路径上加入 capability gate**，使其成为默认行为，而不是可选传参。

```python
async def send_gateway_command(
    device_id: str,
    command: str,
    params: dict,
    required_capabilities: Optional[List[str]] = None,  # 现在：可选
    **kwargs
) -> dict:
    # 新增：如果未显式传 required_capabilities，从 command 推断
    effective_caps = required_capabilities or _infer_required_capabilities(command)
    if effective_caps:
        enforce_mainline_capability_gate(
            device_id=device_id,
            required_capabilities=effective_caps,
            device_capabilities=_get_device_capabilities(device_id),
            mode=EnforcementMode.STRICT,
            calling_site="send_gateway_command",
        )
    ...
```

### 4. 将 GAP_ANDROID_CI 标记为 resolved（完成 WebSocket smoke 后）

**文件**：`core/dual_repo_system_map.py`

当 Android CI 有 WebSocket 协议 smoke test 后，更新 `resolved=True`。

### 5. 将 GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT 标记为 resolved

**文件**：`core/dual_repo_system_map.py`

当 `send_gateway_command` 默认 enforce 后更新。

### 6. 将 GAP_JOINT_INTEGRATION_TEST 标记为 resolved（网络级 E2E 建立后）

**文件**：`core/dual_repo_system_map.py`

注意：这里 resolved 的定义是"有自动化的双仓网络级 E2E"，不是"真实物理设备 E2E"（后者是更高阶段的目标）。

### 7. Dual-Repo Integration CI 增加网络级 E2E job

**文件**：`.github/workflows/dual_repo_integration.yml`

新增一个 job，运行 `test_android_runtime_process_e2e.py`，标记为 BLOCKING。

### 8. Release Posture Matrix 增加 local_ai 状态维度

**文件**：`core/runtime_readiness_matrix.py`

新增维度 `android_local_ai_state`，结果可以是 `ready`/`degraded`/`off`，但这个维度**不**是 blocking（off 是允许的有效状态，不应阻断 release）。

---

## 验收标准

- [ ] `tests/integration/test_android_runtime_process_e2e.py` 使用真实 WebSocket 连接验证完整 6 步序列
- [ ] Android CI 有 WebSocket 消息格式 JVM 单测
- [ ] `send_gateway_command` 主路径默认 enforce capability gate
- [ ] `GAP_JOINT_INTEGRATION_TEST` `resolved=True`
- [ ] `GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT` `resolved=True`
- [ ] `GAP_ANDROID_CI` `resolved=True`
- [ ] `dual_repo_integration.yml` 的所有现有 blocking job 继续通过
- [ ] `release_blocking_gate.py` 继续通过

---

## 与 PR-1 / PR-2 的关系

PR-3 可以和 PR-1 并行推进：
- capability gate 强化（工作项 3）和 E2E 建立（工作项 1/2）不依赖 PR-1 的 durable recovery
- release posture matrix 新维度（工作项 8）最好等 PR-2 的 Android runtime manager 存在后添加

PR-3 完成后，系统获得：
- 真实网络级双仓 E2E（不是进程内 simulation）
- capability gate 无法绕过的默认强制
- 三个 P0 gap 全部关闭

---

## 预期影响

PR-1 + PR-2 + PR-3 全部完成后，系统的七个 gap 中六个（所有 P0 + 两个 P1）将关闭，剩余 `GAP_RUNTIME_TRUTH_SINGLE_INGRESS`（P1）可作为独立后续工作。此时系统满足"准成熟系统"的核心要求：默认 durable authority + 能力状态诚实 + 可证明的双仓 runtime 闭环。
