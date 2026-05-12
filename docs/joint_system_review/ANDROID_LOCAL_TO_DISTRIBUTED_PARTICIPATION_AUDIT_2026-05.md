# Android 本地态 → 跨设备启用 → 分布式参与 代码审计基线（Follow-up on #1129）

> 审计问题：**Android 到底在什么“真实代码条件”下，才从 local-only 进入 true cross-device-enabled / distributed-network participant。**  
> 范围：仅做审计/澄清/基线硬化；不实现新状态机或新功能。

---

## 0) 证据分层

- **Confirmed Runtime（本仓可直接验证）**：V2 侧真实运行代码路径与门控条件。  
- **Inferred Cross-Repo（跨仓推断）**：Android 仓代码位置由已入库审计材料锚定，但本仓不直接执行 Kotlin 源。

---

## 1) Android 是否已有“单一权威参与状态机”？

结论（当前基线）：

1. **存在部分显式状态/门控字段**，但分散在多处，不是单一 Android-originating authoritative state。  
2. 当前更接近“**多门控推断模型**”，而不是“一个统一 mode machine 对外宣告 full participant”。

### 已显式存在的状态/语义（Confirmed Runtime）

- `local-only / control-only`：`posture="control_only"` 会阻断本地执行资格与 dispatch target 资格  
  - `core/runtime/source_dispatch_orchestrator.py:1600-1604,1688-1698,1812-1818`
- `cross-device mode`（V2 推断态）：`AndroidDeviceMode` 有 `local/cross_device/transitioning/unknown`，由会话+快照门控推断  
  - `core/android_mode_gate_policy.py:173-199,914-922,1051-1060`
- `dispatch/takeover eligible`：由统一 gate verdict 给出 `is_dispatch_eligible/is_takeover_eligible`  
  - `core/android_mode_gate_policy.py:931-945,1065-1074`

### “fully attached / distributed participant”是否有单一状态？

- **无单一字段/枚举可直接等价于“已成为完整分布式参与者”**。  
- 现有语义是组合判断：  
  - 注册链完整性：`registration_fully_attached` + `registration_gaps`  
    - `galaxy_gateway/android/handlers/registration.py:600-607,620-645`
  - cross-device 可用性：`android_attached && capability_visible && active_session_count>0`  
    - `core/v2_unified_state_contract.py:182-200`
  - 运行时可派发：readiness + participation + posture 多 gate  
    - `core/runtime/source_dispatch_orchestrator.py:1784-1818`

---

## 2) Android 侧哪些模块定义/影响该转变？

## Inferred Cross-Repo（由已存审计基线锚定）

- `runtime/RuntimeController.kt`：连接/断开与恢复 watchdog 生命周期权威  
  - `audit/CENTER_DISTRIBUTED_SYSTEM_FINAL_VERDICT.md:169-193`
  - `audit/FRESH_INTEGRATED_CODE_REALITY_AUDIT_2026.md:61-64`
- `service/GalaxyConnectionService.kt`：AIP 消息分发、任务处理、连接服务宿主  
  - `audit/CENTER_DISTRIBUTED_SYSTEM_FINAL_VERDICT.md:202-215`
  - `audit/DUAL_REPO_REAL_CHAIN_BASELINE_2026.md:355-368`
- `network/GalaxyWebSocketClient.kt`：`device_register` 握手、`source_runtime_posture`、发送门控（cross-device 开关）  
  - `audit/CENTER_DISTRIBUTED_SYSTEM_FINAL_VERDICT.md:169-193,227-234`
  - `audit/FRESH_INTEGRATED_CODE_REALITY_AUDIT_2026.md:61-63`
- `protocol/AipModels.kt`：Android AIP v3 模型层（状态/信号载体）  
  - `audit/FRESH_INTEGRATED_CODE_REALITY_AUDIT_2026.md:66`

> 说明：本仓可验证的是 Android 信号被如何消费；Android 本地“最终参与状态机”本体仍需在 Android 仓实现层做最终权威化。

---

## 3) V2 侧哪些模块在推断/门控/消费 Android 参与状态？

- 注册与附着连续性：  
  - `galaxy_gateway/android/handlers/registration.py:600-645`
  - `core/attached_runtime_session_registry.py:114-125,160-163,1708-1712`
- 能力与快照吸收：  
  - `galaxy_gateway/android/handlers/capability_report.py:153-180,196-221`
  - `galaxy_gateway/android/handlers/device_state_snapshot.py:51-60,84-93,116-124`
- 模式门控聚合（V2 视角）：  
  - `core/android_mode_gate_policy.py:570-588,591-631,648-703,1009-1074`
- 统一状态契约（projection 侧 cross-device availability）：  
  - `core/v2_unified_state_contract.py:182-200,225-232`
- 实际派发目标资格（调度链）：  
  - `core/runtime/source_dispatch_orchestrator.py:1784-1818`
- Android 发起 cross-device NL 的入口 gate：  
  - `galaxy_gateway/android/handlers/goal_execution.py:153-179`

---

## 4) 当前转变是“显式强制”还是“隐式推断”？

当前判定：**部分显式 + 主要为多门控推断**。

- 显式强制（局部）：
  - `control_only` 明确阻断 dispatch target（强 gate）。
  - mode readiness 有明确 gate 与 blocking reason。
- 隐式推断（全局）：
  - “cross-device-enabled / fully attached / distributed participant”没有单一上游权威位。  
  - V2 通过注册完整性、会话活跃、posture、快照 gate、capability 可见性、cross-device switch 等组合推断。

---

## 5) 四层语义差异（必须分离）

1. **connected / registered**  
   - 已建立连接并 `device_register_ack(success=True)`。  
2. **fully attached**  
   - `registration_fully_attached=True` 且无 `registration_gaps`。  
3. **dispatch-eligible**  
   - 满足 mode/readiness/participation/posture 等派发门控。  
4. **true distributed-network participant**  
   - 当前没有单一 Android-originating authoritative bit；只能由上面多面信号综合推断。

---

## 6) 阻碍“可硬信任声明”的剩余代码缺口（仅基线，不实现）

要能在运行时可信地说“Android 现在是 full distributed-network participant”，仍缺：

1. **单一 Android-originating participation truth**（可被 V2 直接消费，而非多点重建）。  
2. **统一状态机语义映射**（local-only / control-only / capable / enabled / attached / dispatch-eligible / full-participant 的一一映射与迁移条件）。  
3. **V2 侧收敛入口**（将当前分散 gate 收敛到一个可审计、可回放、可投影的 authoritative state 字段）。  

---

## 基线结论（用于下一实现 PR 的起点）

- 当前系统**不是没有门控**，而是门控**分散且由 V2 多点推断**。  
- 当前系统可以表达“连接/附着/可派发”的分层，但尚不能给出一个来自 Android 单一权威状态机的“full distributed participant”硬声明。  
- 下一实现 PR 应聚焦“统一 runtime truth + network participation integrity”，而不是继续扩展分散语义。
