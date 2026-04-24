# 关键主链路代码重建

> **目标**：从真实代码追踪每条主链路的完整调用路径，包括入口、传输、处理、回流、状态更新。
> **说明**：代码引用格式为 `文件路径:关键代码片段`，方便直接定位。

---

## 链路 1：Android 本地 agent 执行链（完整代码路径）

**入口**：`service/EnhancedFloatingService.kt` 或 `service/FloatingWindowService.kt`（用户 UI 输入）  
**类型**：Android 自治本地执行  
**状态**：✅ 真实闭环

```
[入口] 用户在 FloatingWindow 输入 instruction
   ↓
[调度] GalaxyConnectionService 或直接调用 LoopController
   ↓ 检查 isRemoteTaskActive（如果为 true，返回 STOP_BLOCKED_BY_REMOTE）
   ↓
[Phase 0] LoopController.ensureModels(sessionId)
   → modelAssetManager.checkAvailability()
   → if missing: modelDownloader.download()
   → 失败: 返回 LoopResult(status=failed, stopReason=STOP_MODEL_UNAVAILABLE)
   ↓
[Phase 1] screenshotProvider.capture()
   → AccessibilityScreenshotProvider.capture()
   → 失败: 返回 LoopResult(status=failed, stopReason=STOP_SCREENSHOT_FAILED)
   ↓
[Phase 2] localPlanner.plan(sessionId, instruction, base64Screenshot)
   → LocalPlanner → MobileVLM 推理 → ActionSequence
   → 失败: 返回 LoopResult(status=failed, stopReason=STOP_PLAN_FAILED)
   ↓
[Phase 3] stagnationDetector.checkForStagnation(step, action, uiChanged)
   → 检测重复动作/UI 无变化
   → 超阈值: 返回 LoopResult(status=failed, stopReason=STOP_STAGNATION)
   ↓
[Phase 4] executorBridge.executeStep(step)
   → GroundingFallbackLadder → SeeClick 坐标解析
   → AccessibilityService.performAction(action)
   ↓
[Phase 5] screenshotProvider.capture()  [后置截图]
   ↓
[Phase 6] postActionObserver.observe(preshot, postshot, step)
   → StepObservation (uiChanged=true/false)
   ↓
[状态更新] _status.emit(LoopStatus.Running(stepIndex, action))
   ↓ [继续循环或终止]
   ↓
[回流] LoopResult(status, stopReason, steps, sessionId, durationMs)
   → UI 层通过 status StateFlow 消费
```

---

## 链路 2：V2→Android task_assign 跨设备执行链

**入口**：`core/openclawd.py`（V2 路由决策）  
**类型**：V2 发起的跨设备任务委托  
**状态**：✅ 真实闭环

```
[V2 入口] OpenClawd.route_request(mode=CROSS_DEVICE_MANIFESTATION)
   ↓
[V2 路由] CommandRouter.route_envelope() → cross-device path
   ↓
[V2 任务构建] TaskEnvelope / CommandEnvelope 构建
   ↓
[V2 gateway] galaxy_gateway/android_bridge.py:
   AndroidBridge.dispatch_task(device_id, task_envelope)
   → MessageBuilder.build_task_assign_message()
   → WebSocket send: {"type":"task_assign", "task_id":..., "payload":{...}}
   ↓
[Android 接收] GalaxyConnectionService.onMessage()
   type = "task_assign"
   → handleTaskAssign(taskId, payloadJson, traceId)
   ↓
[Android 路由判断]
   if (crossDeviceEnabled && !require_local_agent):
       → AgentRuntimeBridge.handoff()  [再次跨设备]
       → if handoff 失败: fallback to executeLocalTaskAssign()
   else:
       → executeLocalTaskAssign(taskId, payload, traceId, routeMode)
   ↓
[Android 本地执行] executeLocalTaskAssign()
   → loopController.cancelForRemoteTask()  [暂停本地执行]
   → EdgeExecutor.execute(taskPayload)
   → 构建 TaskResultPayload
   ↓
[Android 回传] GalaxyWebSocketClient.send({
   "type": "task_result",
   "task_id": taskId,
   "payload": {status, result, ...}
})
   ↓
[Android 清理] RuntimeController.onRemoteTaskFinished()
   → loopController.clearRemoteTaskBlock()  [解除本地执行互斥]
   ↓
[V2 接收] galaxy_gateway/android/handlers/task_lifecycle.py:
   handle_task_result(bridge, websocket, message)
   ↓
[V2 reconcile] android_execution_signal_reconciler.reconcile_inbound_message(message)
   → extract_signal_envelope(message) → AndroidExecutionSignalEnvelope
   → reconcile_android_execution_signal(envelope)
   → DelegatedExecutionTrackingRuntime.apply(signal)  [更新追踪记录]
   ↓
[V2 结果反馈] OpenClawd.receive_result(ResultEnvelope)
   → Projection / Memory backflow
```

---

## 链路 3：HandoffEnvelopeV2 完整往返链路

**入口**：`core/canonical_handoff_path.py`（V2 handoff 决策）  
**类型**：V2→Android HandoffEnvelopeV2 + HANDOFF_ENVELOPE_V2_RESULT 回传  
**状态**：⚠️ 半闭环（下行 ✅，上行 routing 断层 ❌）

```
[V2 发起] canonical_handoff_path.py → 构建 HandoffEnvelopeV2
   ↓
[V2 合同] contracts/handoff_envelope_v2.py:
   HandoffEnvelopeV2(task_id, session_id, contract_id, trace_id, ...)
   ↓
[V2 注册] core/android_runtime_dispatch_binding.py:
   create_android_dispatch_binding(session, device, contract, tracker)
   → AndroidRuntimeDispatchBindingRecord（记录 binding 关系）
   ↓
[V2 发送] galaxy_gateway/android/message_builder.py:
   build_handoff_dispatch_message(envelope)
   → {"type":"handoff_envelope_v2", "payload": envelope.to_android_native_payload()}
   → AndroidBridge.send(ws, message)
   ↓
[Android 接收] GalaxyConnectionService.onMessage()
   type = "handoff_envelope_v2"
   → handleHandoffEnvelopeV2(taskId, payloadJson, traceId)
   ↓
[Android 执行]
   1. 解析 HandoffEnvelopeV2 payload
   2. loopController.cancelForRemoteTask()
   3. EdgeExecutor 或 AutonomousExecutionPipeline 执行
   4. 构建 HandoffEnvelopeV2ResultPayload(
        handoff_id, task_id, trace_id, status=ack/result/failure,
        result_summary, error_message
      )
   ↓
[Android 发送] sendHandoffEnvelopeV2Result(result, traceId)
   → GalaxyWebSocketClient.send({
       "type": "handoff_envelope_v2_result",  ← MsgType.HANDOFF_ENVELOPE_V2_RESULT
       "task_id": taskId,
       "payload": HandoffEnvelopeV2ResultPayload
     })

---

> ⚠️ **断层：V2 网关无法识别此消息**

**[断层 1] `galaxy_gateway/protocol/aip_v3.py` MessageType 枚举**：

`V2` 收到 `type = "handoff_envelope_v2_result"` 时执行：

```python
msg_type = MessageType("handoff_envelope_v2_result")
# → ValueError: "handoff_envelope_v2_result" is not a valid MessageType
# → 消息进入 "Unknown message type" 分支，被 AndroidBridge 丢弃
```

原因：V2 枚举当前仅有 `HANDOFF_DISPATCH / HANDOFF_ACK / HANDOFF_RESULT / HANDOFF_FAILURE`，缺少 `HANDOFF_ENVELOPE_V2_RESULT`。

**[断层 2] `galaxy_gateway/android_bridge.py` `_message_handlers` 注册表**：

即使补全 MessageType 枚举，`_message_handlers` 中也没有注册对应 handler：

```python
# 当前缺失（需要补充）：
# self._message_handlers[MessageType.HANDOFF_ENVELOPE_V2_RESULT] = _wrap(handle_handoff_envelope_v2_result)
```

[已实现但未接通] core/android_handoff_v2_response_ingress.py:
   ingest_android_handoff_response(message) → HandoffV2ResponseOutcome
   # 完整实现了 correlate → Future.set_result 逻辑
   # 但从未被 gateway 路由层调用

─── 以下链路未建立 ──────────────────────────────────────────────────────

[V2 ingress] core/android_handoff_v2_response_ingress.py（存在但未挂接）:
   ingest_android_handoff_response(message)
   → extract_handoff_response_envelope(message)
   → correlate by handoff_id / task_id / session_id
   → resolve Future(pending_dispatch) → set_result/exception
   → 返回 HandoffV2ResponseOutcome
   ↓（未建立）
[V2 状态更新] AndroidRuntimeDispatchBindingRuntime.advance(binding, signal=confirm)
   ↓（未建立）
[V2 flow 推进] delegated_flow_entity 接收 result → phase 推进
```

---

## 链路 4：ReconciliationSignal 链路

**入口**：`runtime/RuntimeController.kt`（Android 侧事件驱动）  
**类型**：Android→V2 结构化对账信号  
**状态**：❌ 断层（Android 内部流转，未接通 wire）

```
[Android 生成] RuntimeController 内部事件
   例如：publishTaskResult() / publishTaskCancelled() / publishParticipantState()
   ↓
[Android 内部流] emitReconciliationSignal(signal):
   _reconciliationSignals.tryEmit(ReconciliationSignal(
     kind = Kind.TASK_RESULT / Kind.TASK_CANCELLED / Kind.PARTICIPANT_STATE / ...,
     participantId, taskId, correlationId, status, payload,
     runtimeTruth, signalId, emittedAtMs, reconciliationEpoch
   ))
   ↓
[Android SharedFlow] reconciliationSignals: SharedFlow<ReconciliationSignal>
   # 只在 Android 进程内可消费，例如 UI 层收集展示

─── ❌ 断层：无 wire 协议支持 ──────────────────────────────────────────

[断层] protocol/AipModels.kt MsgType 枚举：
   # 没有 "reconciliation_signal" 对应的 MsgType 条目
   # 最后条目为：HANDOFF_ENVELOPE_V2_RESULT("handoff_envelope_v2_result")
   # ReconciliationSignal 不是 AIP 协议消息，只是 Android 进程内数据流

[断层] service/GalaxyConnectionService.kt：
   # 没有消费 RuntimeController.reconciliationSignals 并通过 WebSocket 发送的逻辑

─── 以下链路未建立 ──────────────────────────────────────────────────────

[未建立] 应有：
   GalaxyConnectionService 收集 reconciliationSignals
   → 序列化为 AIP 消息
   → GalaxyWebSocketClient.send({type:"reconciliation_signal", payload:...})
   ↓（未建立）
[未建立] V2 gateway handler：
   handle_reconciliation_signal(bridge, ws, message)
   → core/android_participant_truth_ingress.ingest_android_participant_truth_message()
   ↓（未建立）
[未建立] V2 canonical state 更新：
   reconcile_android_participant_truth(envelope) → AndroidParticipantReconcileOutcome
   → V2 canonical 状态刷新
```

---

## 链路 5：Reconnect Recovery 链路

**入口**：`network/GalaxyWebSocketClient.kt`（WebSocket 断开事件）  
**类型**：Android→V2 重连恢复  
**状态**：✅ 真实闭环

```
[事件] WebSocket onClosed / onFailure
   ↓
[Android RuntimeController] 推进 _reconnectRecoveryState:
   IDLE → RECONNECTING
   ↓
[Android 重连] GalaxyWebSocketClient.reconnect()
   → 指数退避重试
   ↓ 连接成功
[Android 重新注册] 发送:
   1. {"type": "device_register", ...}
   2. {"type": "capability_report", ...}
   3. AttachedRuntimeHostSessionSnapshot 更新
   ↓
[Android 状态] _reconnectRecoveryState: RECONNECTING → RECOVERED
   → V2MultiDeviceLifecycleEvent.DeviceReconnected 事件发出
   ↓
[V2 接收] handle_device_register(bridge, ws, message)
   → DeviceRegistry.update(device)
   → AttachedSessionRegistry.reopen(session)
   → android_v2_continuity_contract 场景 2（Android reconnect）
   ↓
[V2 状态] CanonicalSessionTruthRuntime.classify_reconnect()
   → continuity_resume 或 new_attachment（基于 session_id 是否匹配）
   ↓
[V2 in-flight 恢复] flow_continuity_coordinator.handle_reconnect(session)
   → 检查是否有 in-flight delegated task
   → 如果有：等待 Android re-attach 后呈现结果
   ↓
[Android 离线队列] OfflineTaskQueue.flush()
   → 发送离线期间积累的 task_result 等消息
```

---

## 链路 6：Android 本地发起 + V2 协调返回链路

**入口**：`service/GalaxyConnectionService.kt`（Android UI 本地 goal 请求）  
**类型**：Android 发起 goal，V2 协调，结果返回 Android  
**状态**：✅ 真实闭环

```
[Android 发起] 用户在 Android 端输入复杂 goal
   ↓
[Android 判断] GalaxyConnectionService 路由：
   if (crossDeviceEnabled):
       → AgentRuntimeBridge.handoff(goal)
       ↓ [发送到 V2]
       → {"type": "goal_execution", "task_id":..., "payload": GoalExecutionPayload}
       ↓
[V2 接收] handle_goal_execution(bridge, ws, message)
   → AutonomousExecutionPipeline 处理
   → 可能进一步分配给其他设备
   ↓
[V2 回传] {"type": "goal_execution_result", "task_id":..., "payload": GoalResultPayload}
   ↓
[Android 接收] GalaxyConnectionService.onMessage()
   type = "goal_execution_result"
   → 结果处理 + UI 更新 + RuntimeController.onRemoteTaskFinished()
```
