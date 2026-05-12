# 双仓执行模型预实施基线（代码实况版）

> 范围：`DannyFish-11/ufo-galaxy-realization-v2` + `DannyFish-11/ufo-galaxy-android`（以 V2 仓内可验证代码证据为准）  
> 目的：在后续实现波次前，先锁定“真实运行路径/边界/缺口”的统一基线。  
> 约束：本基线不做新功能实现，不做 roadmap 许诺，只陈述当前代码已证实事实。

---

## 0. 证据分级（防止过度宣称）

- **已确认运行路径（Confirmed Runtime）**：当前仓代码中有直接调用链，运行时会触达。  
- **推断关系（Inferred）**：由当前仓与跨仓契约/回放证据推断，但本仓无法直接执行 Android 代码。  
- **契约/审计层（Contract/Audit）**：有模型/策略/报告语义，但非默认强制运行路径。

---

## 1. 真实执行主干（Natural Language → 分流 → Android 参与 → 结果闭环）

### 1.1 自然语言进入中心认知主干（Confirmed Runtime）

- HTTP 入口：`/api/v1/chat` 适配层调用 `DesktopPresenceRuntime.handle_request()`，再进入 `OpenClawd.process()`：  
  `core/routes/chat.py:110-128,179-197`
- WS 入口：`msg_type == "chat"` 同样调用 `DesktopPresenceRuntime.handle_request(...)`：  
  `core/api_routes.py:942-956`
- Runtime shell 负责 tri-state + `runtime_session_id` 传播，再 dispatch 到核心：  
  `core/desktop_presence_runtime.py:335-347,453-505,548-559`

### 1.2 V2 如何判定 local vs cross-device（Confirmed Runtime）

- `OpenClawd.process()` 明确四阶段（ingest/continuum/branch/manifest），branch 由 `_determine_execution_path()` 决定：  
  `core/openclawd.py:2908-2937,2737-2799`
- 路径语义是 `local | cross_device | hybrid | none`，并依赖 `entry_mode` 与 `cross_device_dispatched`：  
  `core/openclawd.py:2737-2799,2959-2963`

### 1.3 Android 如何参与被委派执行（Confirmed Runtime + Inferred）

- Cross-device canonical dispatch 入口是 `CommandRouter.route_envelope()`：  
  `core/command_router.py:1162-1183`
- OpenClawd 跨端发送链是 `send_gateway_command()` → `CommandRouter.route_envelope()`：  
  `core/openclawd.py:7712-7727,7835-7871`
- 设备接入 canonical WS 路径是 `/ws/device/{device_id}`，消息进入 `android_bridge.handle_message()`：  
  `galaxy_gateway/routes/websocket.py:7-17,69-79,199-212`
- Android 注册/能力/状态消息入站处理在 gateway handlers（注册、能力上报、状态快照）：  
  `galaxy_gateway/android/handlers/registration.py:324-352,417-519,620-645`  
  `galaxy_gateway/android/handlers/capability_report.py:153-180,206-221`  
  `galaxy_gateway/android/handlers/device_state_snapshot.py:51-60,127-137`

### 1.4 结果如何回到 canonical completion closure（Confirmed Runtime）

- Android `task_result` 入站后先过 continuity legality，再走 `run_task_result_truth_chain()` 四步：  
  `galaxy_gateway/android/handlers/task_lifecycle.py:556-575,604-620`
- 四步包括 participant truth ingress / reconcile / authority lifecycle update / canonical completion notify：  
  `core/task_result_canonical_truth_chain.py:38-49,559-620`
- completion linkage 实际通过 `CanonicalCompletionIngress.notify()` + `complete_pending_dispatch()`：  
  `core/task_result_canonical_truth_chain.py:432-463`

---

## 2. Local-path vs Cross-device-path 语义

### 2.1 Android local-only 的代码语义（Confirmed Runtime）

- 源设备姿态 `control_only` 会阻断本地执行资格（无远端目标则 blocked，有远端目标则 remote_handoff）：  
  `core/runtime/source_dispatch_orchestrator.py:1600-1604,1688-1698`
- 候选目标评分时，`control_only` 设备直接拒绝为 dispatch target：  
  `core/runtime/source_dispatch_orchestrator.py:1812-1818`

### 2.2 cross-device-enabled 的代码语义（Confirmed Runtime）

- 在统一状态契约中，`cross_device_available` 需要：Android attached + capability visible + active session：  
  `core/v2_unified_state_contract.py:196-200`
- `AndroidDeviceMode` 定义 local/cross_device，且 cross_device 要求三类 gate 全开（模块文档定义）：  
  `core/android_mode_gate_policy.py:173-188`

### 2.3 Android 成为“完整网络参与者”的必要条件（Confirmed Runtime）

- 仅“连接成功”不等于可调度；注册流程会记录 downstream gap，并在 ACK 中返回 `registration_fully_attached`/`registration_gaps`：  
  `galaxy_gateway/android/handlers/registration.py:27-35,73-82,600-645`
- 目标选择还需通过 readiness / participation / posture 三层 gate：  
  `core/runtime/source_dispatch_orchestrator.py:1784-1818`

---

## 3. Android 网络参与模型（注册/就绪/能力/会话/分布式参与）

### 3.1 注册与会话附着（Confirmed Runtime）

- 注册时先写 UDM，再更新 bridge 缓存，并进入 attached runtime session 流程：  
  `galaxy_gateway/android/handlers/registration.py:340-350,417-437`
- reconnect 连续性由 `runtime_attachment_session_id` + durable 字段判定 `continuity_resume` vs `new_attachment`：  
  `galaxy_gateway/android/handlers/registration.py:440-512,629-639`

### 3.2 就绪与能力（Confirmed Runtime）

- 能力上报会同步到 CapabilityAuthority runtime 侧，供后续调度读取：  
  `galaxy_gateway/android/handlers/capability_report.py:39-89,206-221`
- 状态快照/执行事件会吸收进 `android_device_state_store`，作为 V2 侧 Android runtime 事实输入：  
  `galaxy_gateway/android/handlers/device_state_snapshot.py:25-37,84-92,159-167`

### 3.3 “已连接”与“已完整附着参与”差异（Confirmed Runtime）

- 代码显式存在“partial registration”概念，并允许 `success=True` 同时附带 `registration_gaps`：  
  `galaxy_gateway/android/handlers/registration.py:600-607,620-645`
- 这说明连接/注册 ACK 与“可稳定参与分布式执行”在代码上是分层状态。

---

## 4. Authority 与 Continuity 模型

### 4.1 中心 authority 所在（Confirmed Runtime）

- 执行决策与分流核心在 `DesktopPresenceRuntime` + `OpenClawd`：  
  `core/routes/chat.py:116-127,179-197`  
  `core/openclawd.py:2924-2937`
- 跨端 dispatch spine authority 在 `CommandRouter.route_envelope()`：  
  `core/command_router.py:1162-1169,1204-1223`

### 4.2 Android 本地 authority（Confirmed Runtime + Inferred）

- V2 侧语义明确 Android 可处于 local mode（本地运行）或 cross_device mode（参与中心分发）：  
  `core/android_mode_gate_policy.py:173-188`
- 但 Android 本地执行细节实现在 Android 仓；本仓通过协议 handler + 状态回流进行“参与者建模”。

### 4.3 continuity（会话连续性、任务连续性）现状（Confirmed Runtime）

- 请求级连续性：`runtime_session_id` 在 shell/core 贯穿：  
  `core/desktop_presence_runtime.py:335-347,548-555`  
  `core/openclawd.py:2954-2958,2990-3004`
- Android 附着连续性：`runtime_attachment_session_id` + `classify_reconnect_outcome`：  
  `galaxy_gateway/android/handlers/registration.py:440-512`
- 结果闭环连续性：task_result truth chain + canonical completion ingress：  
  `galaxy_gateway/android/handlers/task_lifecycle.py:604-620`  
  `core/task_result_canonical_truth_chain.py:610-620`

---

## 5. 运行时强制路径 vs 契约/审计层

### 5.1 当前可确认的 true runtime path（Confirmed Runtime）

1. `core/routes/chat.py` / `core/api_routes.py` chat 入口  
2. `core/desktop_presence_runtime.py`  
3. `core/openclawd.py`  
4. `core/command_router.py`  
5. `galaxy_gateway/routes/websocket.py` + `galaxy_gateway/android_bridge.py` + handlers  
6. `galaxy_gateway/android/handlers/task_lifecycle.py`  
7. `core/task_result_canonical_truth_chain.py`  
8. `core/canonical_completion_ingress.py`（由 truth chain step4 调用）

### 5.2 契约/治理/审计层（存在但并非默认强制）

- `core/dual_repo_system_map.py` 明确把模块分为 `RUNTIME_CRITICAL / SEMI_EXECUTABLE / DECLARATIVE`，用于区分语义层级：  
  `core/dual_repo_system_map.py:34-40,425-433,476-485,553-565`
- 该映射本身是“分类与认知基线”，不是运行时自动强制器；它帮助避免把 policy/sentinel 文本误当成执行闭环。

---

## 6. 对后续 4 个收敛 PR 的硬基线（仅定义入口，不提前实现）

1. **runtime truth + network participation integrity**  
   以 `registration_fully_attached`、三层 gate、`cross_device_available` 为统一校验面。  
2. **natural-language-to-execution canonical closure**  
   以 `chat/ws chat -> runtime shell -> openclawd -> dispatch -> task_result truth chain` 为唯一闭环主干。  
3. **authority + continuity + takeover governance**  
   以 `runtime_session_id`、`runtime_attachment_session_id`、`continuity_outcome` 为连续性主轴。  
4. **operational surface + metrics + operator actionability**  
   以“已连接 vs fully_attached vs dispatch_eligible”分层暴露为最低运营要求。

---

## 7. 当前基线中的关键未完成点（不在本 PR 实现）

- Android 仓本地执行链细节在本仓不可直接执行验证；当前以协议/状态回流与跨仓证据回放为主。  
- truth chain 第 4 步 completion linkage 在实现上仍是 soft 路径（步骤 1-3 是 hardened 失败即抛错，步骤 4 记录 incomplete）：  
  `core/task_result_canonical_truth_chain.py:634-637,684-707`
- 注册流程中多个下游步骤为 non-fatal，说明“注册成功”与“完整可调度”仍可能分离：  
  `galaxy_gateway/android/handlers/registration.py:433-439,513-519,600-607`

---

本文件即本轮“预实施审计与形式化”基线，后续实现 PR 需以此基线逐条收敛，不得回退到仅文本宣称。
