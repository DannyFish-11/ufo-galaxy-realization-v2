# 04 关键主链路代码重建

本章对每条主要执行链路进行基于代码的逐步重建，精确到模块/函数级别。

---

## 链路 A：Android 本地自治执行链路（完整重建）

**触发点**：用户在 Android 应用中通过 UI 发起自然语言指令

```
android/.../ui/MainActivity  (or EnhancedFloatingService)
  ↓ 用户输入 instruction
  ↓ 调用 loopController.execute(instruction)

android/.../loop/LoopController.execute(instruction: String): LoopResult
  ↓ 检查 isRemoteTaskActive → 如果 true 返回 STOP_BLOCKED_BY_REMOTE
  ↓ cancelRequested = false, stagnationDetector.reset()
  ↓ GalaxyLogger.log(event="session_start", ...)
  ↓ _status.value = LoopStatus.Running(...)

  ↓ Phase 0: ensureModels(sessionId)
      android/.../model/ModelAssetManager.checkModelsPresent()
      → 如果缺失，调用 modelDownloader.download()

  ↓ Phase 1: captureScreenshot(sessionId) → JPEG base64
      android/.../agent/EdgeExecutor.ScreenshotProvider.capture()
      → MediaProjection API 截屏

  ↓ Phase 2: localPlanner.plan(screenshotBase64, instruction)
      android/.../loop/LocalPlanner.plan()
        → PlannerFallbackLadder 选择可用的 VLM 后端
        → MobileVLM / GGUF / remote inference
        → 返回 ActionSequence（含多个 ActionStep）

  ↓ Phase 3: executorBridge.execute(ActionStep)
      android/.../loop/ExecutorBridge.execute()
        → SeeClick grounding（坐标解析）
        → android/.../agent/EdgeExecutor.dispatchAction()
          → AccessibilityService 执行 click/input/scroll/...

  ↓ Phase 4: captureScreenshot() 动作后截屏

  ↓ Phase 5: postActionObserver.observe(before, after, action)
      android/.../local/PostActionObserver.observe()
        → 比对两张截屏，判断 UI 是否发生变化

  ↓ Phase 6: stagnationDetector.check(action, hasUIChange)
      android/.../local/StagnationDetector.check()
        → 检测重复动作 / 无 UI 变化的停滞

  ↓ 循环 goto Phase 2（直到 task_complete / max_steps / timeout / stagnation）

  ↓ 返回 LoopResult {sessionId, status, steps[], stopReason, failureCode}

android/.../service/GalaxyConnectionService
  ↓ 收到 LoopResult
  ↓ 发送 AIP v3 消息：
      type: "goal_execution_result" 或 "task_result"
      payload: {task_id, session_id, result, steps_count, stop_reason, ...}
  ↓ OpenClawd memory backflow: route_mode = "local" 或 "cross_device"
```

---

## 链路 B：V2 跨设备任务发起 → Android 执行 → 结果回收（完整重建）

**触发点**：V2 接收来自用户/API 的请求，决策分配给 Android 执行

```
v2 galaxy_gateway/routes/ (REST 入口或 WebSocket)
  ↓ 接收用户请求，解析 task 内容
  ↓ 进入 OpenClawd routing layer

v2 core/openclawd.py :: OpenClawd.route(request)
  ↓ 调用 CommandRouter.route_envelope(task_envelope)

v2 core/command_router.py :: CommandRouter.route_envelope()
  ↓ 检查 source_execution_eligibility
  ↓ 决策：cross-device

v2 galaxy_gateway/device_router.py :: DeviceRouter.route_task()
  ↓ core/delegated_target_selection_policy.py 选择目标 Android 设备
  ↓ core/target_device_validator.py 验证设备可用
  ↓ 构建 HandoffContract:
      source_runtime_posture / coordination_role resolved

v2 galaxy_gateway/agent_bridge.py :: AgentBridge.handoff(contract)
  ↓ 通过 WebSocket 发送 AIP v3 消息到 Android：
      type: "goal_execution" | "task_assign" | "handoff_envelope_v2"
      payload: {task_id, goal, session_id, contract_id, ...}

── WebSocket transport ──────────────────────────────────────────

android/.../network/GalaxyWebSocketClient.onMessage()
  ↓ GalaxyConnectionService 消息处理
  ↓ MsgType.GOAL_EXECUTION 或 TASK_ASSIGN

android/.../runtime/RuntimeController.onRemoteTaskStarted(taskId, msgType)
  ↓ loopController.cancelForRemoteTask()
      → LoopController.cancelRequested = true
      → LoopController.isRemoteTaskActive = true
  ↓ 中止任何正在运行的本地 execute() 会话

android/.../agent/DelegatedTakeoverExecutor.execute(payload)
  ↓ 解析 task/goal 内容
  ↓ (Optional) TakeoverEligibilityAssessor.assess() 评估资格
  ↓ 调用 loopController.execute(goal_instruction)
      → 运行完整本地 agent loop（见链路 A 内部步骤）
  ↓ 收到 LoopResult

android/.../runtime/RuntimeController.onRemoteTaskFinished(taskId, result)
  ↓ loopController.clearRemoteTaskBlock()
      → LoopController.isRemoteTaskActive = false

android/.../service/GalaxyConnectionService
  ↓ 发送 AIP v3 上行消息：
      type: "goal_execution_result" | "task_result"
      payload: {task_id, session_id, contract_id, result, status, ...}

── WebSocket transport ──────────────────────────────────────────

v2 galaxy_gateway/android_bridge.py :: AndroidBridge.handle_message()
  ↓ 识别 MessageType.GOAL_EXECUTION_RESULT → handle_goal_execution_result
  ↓ (或 TASK_RESULT → handle_task_result)
  ↓ galaxy_gateway/android/handlers/task_lifecycle.py
      → _try_reconcile(message)
        → core/android_execution_signal_reconciler.py::reconcile_inbound_message()
          → extract_signal_envelope(message) → AndroidExecutionSignalEnvelope
          → reconcile_android_execution_signal(envelope)
            → DelegatedRuntimeExecutionTracker 状态更新
            → 返回 AndroidSignalReconcileOutcome

v2 core/runtime/source_dispatch_orchestrator.py
  ↓ consume_android_behavioral_result(outcome) （来自 delegated_signal handler）
  ↓ 结果进入 OpenClawd feedback loop

v2 core/goal_result_aggregator.py / multi_device_truth_convergence.py
  ↓ result 对齐、projection、memory backflow
```

---

## 链路 C：Android DelegatedExecution Signal 专用上报链路（PR-16，完整重建）

**触发点**：Android 执行过程中发出 lifecycle signal（ack/progress/result/timeout/cancelled）

```
android/.../runtime/DelegatedExecutionSignalSink.kt
  ↓ 在执行生命周期各阶段被调用
  ↓ 构建 DelegatedExecutionSignal {
        signal_kind: ack | progress | result | timeout | cancelled
        result_kind: success | failure | unknown (仅 result 时)
        signal_id: UUID（用于幂等性）
        emission_seq: 单调递增序号
        task_id, session_id, contract_id, device_id, trace_id
    }
  ↓ 通过 GalaxyConnectionService 发送 AIP v3 消息：
      type: "delegated_execution_signal"
      payload: 以上字段

── WebSocket transport ──────────────────────────────────────────

v2 galaxy_gateway/android_bridge.py
  ↓ MessageType.DELEGATED_EXECUTION_SIGNAL → handle_delegated_execution_signal

v2 galaxy_gateway/android/handlers/delegated_signal.py
  ↓ ingest_delegated_execution_signal(message)
      core/android_delegated_signal_ingress.py
        ↓ extract_delegated_signal_envelope(message)
            → DelegatedExecutionSignalEnvelope {
                signal_kind, result_kind, signal_id, emission_seq,
                task_id, session_id, contract_id, device_id, trace_id
              }
        ↓ reconcile_android_execution_signal(envelope)
            core/android_execution_signal_reconciler.py
              ↓ resolve tracking record by contract_id or session_id
              ↓ apply_acknowledgment_signal() / apply_result()
              ↓ 返回 AndroidSignalReconcileOutcome {was_updated, record, reject_reason}
  ↓ 如果 result-kind 且 was_updated=True：
      core/runtime/source_dispatch_orchestrator.py
        ↓ consume_android_behavioral_result(outcome)
  ↓ 返回 ACK response
```

---

## 链路 D：HandoffEnvelopeV2 链路（部分重建，含断层标注）

**触发点**：V2 通过 handoff_envelope_v2 发送任务给 Android 原生消费

```
v2 contracts/handoff_envelope_v2.py :: HandoffEnvelopeV2 构建
  ↓ 序列化为 AIP v3 消息：
      type: "handoff_envelope_v2"
      payload: HandoffEnvelopeV2 内容

── WebSocket transport ──────────────────────────────────────────

android/.../network/GalaxyWebSocketClient.onMessage()
  ↓ MsgType.HANDOFF_ENVELOPE_V2
  ↓ GalaxyConnectionService 专用 stateful handler（PR-H promoted）
      android/.../agent/HandoffEnvelopeV2.kt 解析
      → HandoffContractValidator.validate()
      → DelegatedRuntimeUnit 执行
  ↓ 执行完成，构建 HandoffEnvelopeV2ResultPayload
  ↓ 发送 AIP v3 消息：
      type: "handoff_envelope_v2_result"   ← MsgType.HANDOFF_ENVELOPE_V2_RESULT
      payload: {handoff_id, task_id, status, result_summary, error, ...}

── WebSocket transport ──────────────────────────────────────────

v2 galaxy_gateway/android_bridge.py
  ↓ 收到消息 type="handoff_envelope_v2_result"
  ↓ 在 handler 注册表中查找 MessageType.HANDOFF_ENVELOPE_V2_RESULT
  ↓ ❌ 未注册该 handler → 降级到 handle_unregistered
                         → 消息丢失，V2 不知道 handoff 结果

v2 core/android_handoff_v2_response_ingress.py  ← 存在但未被调用
  ↓ ingest_android_handoff_response() 实现完整
  ↓ HandoffV2ResponseRuntime 有 registry 机制
  ↓ ❌ 但没有 gateway handler 调用此函数
```

**断层确认**：HANDOFF_ENVELOPE_V2_RESULT 上行消息在 V2 gateway 无 handler，
`core/android_handoff_v2_response_ingress.py` 存在但游离于 gateway 路由之外。

---

## 链路 E：Recovery / Reconnect 链路（部分重建）

**触发点**：WebSocket 连接断开，Android 尝试重连

```
android/.../network/GalaxyWebSocketClient.onConnectionLost()
  ↓ RuntimeController.onConnectionLost()
  ↓ _state.value = RuntimeState.Failed(reason)
  ↓ 如果 takeoverActive:
      _takeoverFailure.emit(TakeoverFallbackEvent(...))
  ↓ attachedSession?.detach(DetachCause.DISCONNECT)

android/.../runtime/ReconnectRecoveryState.kt
  ↓ 记录重连状态
  ↓ DurableSessionContinuityRecord 保存本地 session 快照

android/.../runtime/RuntimeController.connectIfEnabled()
  ↓ 读取 AppSettings.crossDeviceEnabled
  ↓ 如果 true: webSocketClient.connect()
  ↓ 重连成功 → start() → onRegistrationSuccess()
  ↓ RuntimeState.Active 恢复
  ↓ 重建 AttachedRuntimeSession

── WebSocket transport ──────────────────────────────────────────

v2 galaxy_gateway/android_bridge.py
  ↓ 收到 device_register（设备重新注册）
  ↓ handle_device_register

v2 core/attached_runtime_session_registry.py
  ↓ 查找之前的 session 记录
  ↓ core/attached_runtime_recovery_readiness.py 评估 recovery 准备情况
  ↓ 重建 session 绑定

v2 core/flow_continuity_coordinator.py（PR-3V2）
  ↓ 检查是否有未完成的 delegated flow
  ↓ replay_foundation.py 决定是否需要 replay
  ↓ 如果需要 replay: 重新发送 task_assign / goal_execution
```

**半闭环**：基础 reconnect + 重新注册流程是真实闭环。但 recovery 过程中 Android 端产生的 `DurableSessionContinuityRecord` 与 V2 端 session 状态之间没有正式的同步协议，两端各自依赖重新注册时传来的基本信息重建，而非精确的 continuity state 传递。
