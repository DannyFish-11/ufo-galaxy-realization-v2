# 双仓一体化真实代码认知（V2 + Android）

> 范围：`DannyFish-11/ufo-galaxy-realization-v2` + `DannyFish-11/ufo-galaxy-android`
>
> 方法：只看真实代码入口、真实消息链、真实运行链，不用命名包装和口号判断系统成熟度。

---

## 1) 这套系统现在到底是什么

一句话：

**它是一个“中心在 V2、执行在 Android”的分布式任务系统。**

- V2 负责接收请求、做治理和路由、汇总结果、暴露状态。
- Android 负责实际执行（本地动作、目标执行、部分自治）并回传结果。
- 两边已经有一条可跑主链，但还没到“完整成熟可放心交付”的状态。

真实锚点（只列关键）：

- V2 入口和编排：`main.py`、`core/system_orchestrator.py`、`unified_launcher.py`
- V2 设备入口：`galaxy_gateway/routes/websocket.py`、`galaxy_gateway/android_bridge.py`
- V2 注册/执行/结果：
  - `galaxy_gateway/android/handlers/registration.py`
  - `galaxy_gateway/android/handlers/task_lifecycle.py`
  - `galaxy_gateway/android/handlers/goal_execution.py`
- V2 真值与投影：
  - `core/unified_result_ingress.py`
  - `core/task_result_canonical_truth_chain.py`
  - `core/routes/projection.py`
- Android 连接与执行：
  - `app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt`
  - `app/src/main/java/com/ufo/galaxy/service/GalaxyConnectionService.kt`
  - `app/src/main/java/com/ufo/galaxy/agent/AutonomousExecutionPipeline.kt`

---

## 2) 一条完整体验应该是什么（从 clone 到可用）

下面是“真正成熟可用”时，用户和开发者应该经历的完整过程：

1. clone 两个仓库。
2. 在 V2 配好环境（模型、网关地址、密钥、运行模式）。
3. 启动 V2（服务起来、路由可用、投影可读）。
4. 构建并安装 Android App，授权无障碍/悬浮窗等必需权限。
5. Android 连上 V2，完成 `device_register` 和 `capability_report`。
6. V2 确认设备进入“可参与可调度”状态。
7. 下发任务（`task_assign` / `goal_execution` / `parallel_subtask`）。
8. Android 执行并持续上报进度与结果。
9. V2 做结果归并、真值更新、验收闭环、状态面展示。
10. 断线后可恢复，结果不会丢、不会重放污染、不会把旧会话结果算进新会话。
11. 运维面可以看清“哪一步失败、为什么失败、下一步要做什么”。

**当前现实：1~8 大体可跑；9~11 还不够硬，不够一致，不够可审计。**

---

## 3) 已经真实实现的部分（不是口号）

### 3.1 中心-设备连接主链已打通

- Android 有稳定 WS 客户端、握手、心跳、重连、离线队列。
  - `GalaxyWebSocketClient.kt` 中可看到 `sendHandshake`、`sendJson`、`scheduleReconnect`、`discardForDifferentSession`。
- V2 侧有规范入口和 handler 体系，能接注册、执行、结果消息。

### 3.2 Android 已不是“纯被动终端”

- `GalaxyConnectionService.kt` 已处理 `task_assign`、`goal_execution`、`parallel_subtask`、`takeover_request`。
- `AutonomousExecutionPipeline.kt` 有执行门控和运行姿态判断，不是仅仅“收到就执行”。

### 3.3 V2 有统一结果入口和真值链骨架

- `core/unified_result_ingress.py` 统一收敛多来源结果。
- `core/task_result_canonical_truth_chain.py` 具备 4 步真值链结构。
- `core/routes/projection.py` 暴露 runtime truth / cross-repo acceptance chain 等投影面。

---

## 4) 半成品、假闭环、看起来有但不够硬的部分

### 4.1 “链路存在”不等于“闭环可靠”

- 结果链中有大量 best-effort 语义：失败时常常继续流程，不一定硬阻断。
- 这会造成“任务表面完成，但真值/验收没有完全闭合”的风险。

### 4.2 目标执行链和普通任务链收敛强度不一致

- `task_result` 链路和 `goal_execution_result` 链路在统一性、约束强度上仍有差异。
- 结果是：系统对不同执行路径的可解释性和可追责性不均衡。

### 4.3 多设备协作语义存在，但 full mesh 运行闭环仍不足

- 代码里已有 mesh/协作相关状态与契约。
- 但“多设备同时参与、失败恢复、顺序一致、最终验收”这套硬闭环还未证明成熟。

### 4.4 运维可见面仍偏“状态展示”，不是“故障闭环控制台”

- 当前主桌面面板以 `windows_client/status_board_v2/` 为核心。
- 但对一线运维最关键的“跨仓单任务全链追踪 + 一键定位断点”仍不完整。

---

## 5) 距离“成熟完整可用”还差什么（按领域）

## 5.1 后端 / runtime（V2）

硬阻断：

1. 结果真值链需要更强的硬门禁，不能长期依赖“失败后继续”。
2. `task_result`、`goal_execution_result`、委托执行结果的收敛策略要进一步统一。
3. 跨仓会话连续性需要更硬的判定和回放防污染证明。

次级增强：

- 投影面要补“因果级诊断字段”，不只是状态快照。

## 5.2 Android 侧

硬阻断：

1. 自治执行、并行子任务、接管路径需要统一可回归证据集（不是只看日志）。
2. 设备本地能力状态与中心 capability truth 要做强一致校准机制。

次级增强：

- 离线回放与重连恢复的极端场景（频繁断线、跨版本、跨 session）还需更系统化验证。

## 5.3 TypeScript / 全栈

硬阻断（当前最明显缺口之一）：

1. 这两个仓库当前没有成型的 TypeScript 全栈 operator 主界面工程。
2. `ufo-galaxy-realization-v2` 内 `dashboard/frontend/` 已退役/删除，现存主要是 Python + CLI/status board 路径。
3. 没有一个“浏览器端可用、强类型、可扩展”的统一运维控制台来承接真实生产操作闭环。

次级增强：

- 后续需补齐前后端契约（OpenAPI/typed client）、任务追踪 UI、诊断 drill-down UI、验收工作台 UI。

## 5.4 运维面 / 可见性

硬阻断：

1. 缺少“单任务跨仓全链路真值追踪”的第一现场视图。
2. 缺少“失败自动归因 + 恢复建议”的可执行控制面。

次级增强：

- 告警、报表、回归趋势、版本对比可视化不足。

## 5.5 测试 / 验证

硬阻断：

1. 缺少稳定的双仓联合验收流水线（含真实设备参与策略）。
2. 缺少对关键失败场景的强制回归门（断网、重复回放、消息乱序、部分成功）。

次级增强：

- 证据归档、回归对比、问题复现模板还可继续标准化。

## 5.6 智能体机制设计（现在“有骨架，未完整闭环”）

硬阻断：

1. 中心治理权与设备自治权虽已分层，但跨仓执行语义仍有局部漂移风险。
2. 规划-执行-验收-记忆回流的一致性仍需更硬的 contract + regression gate。

次级增强：

- 机制层应补“失败可解释模型”和“策略回放验证”。

---

## 6) 双仓对齐情况：哪里对齐，哪里没对齐

### 已对齐（可作为基础）

- 注册/心跳/重连/离线回放主通道存在。
- 任务下发与结果回传的主消息类型已形成事实标准路径。
- V2 具备统一结果入口，Android 有统一 sendJson 出口和执行入口。

### 未完全对齐（成熟度主要短板）

- 真值链闭环强度不统一：不同结果类型、不同执行路径存在强弱差。
- 多设备协作从“可表达”到“可稳定验收”之间仍有距离。
- 运营/开发共用的全栈 TypeScript 控制面缺失，影响长期可用性和可维护性。

---

## 7) 下一步应该怎么做（可直接拆后续 PR）

P0（先做，不做就谈不上成熟可用）

1. **统一结果硬门禁**：把关键真值步骤从“尽量做”提升为“必须完成或明确失败”。
2. **双仓联合验收流水线**：建立稳定的跨仓、跨 session、含断线恢复的回归门。
3. **TypeScript 全栈运维主面工程立项**：补统一 operator web console（强类型契约 + 任务全链追踪）。

P1（紧随其后）

1. **多设备协作强一致验证**：mesh 协作从语义成立推进到运行闭环可复现。
2. **智能体机制回放验证**：规划/执行/验收/记忆链路引入可重放检查。

P2（持续增强）

1. 可观测性和诊断体验优化。
2. 运维报表、趋势、版本对比、问题知识库联动。

---

## 8) 最直白结论

- 这不是“还没开始”的系统。
- 也不是“已经成熟可放心交付”的系统。
- 它处在“主链可跑、关键闭环仍需加固”的阶段。
- 真正的下一跳，不是再写一轮概念文档，而是：
  1) 把真值和验收做硬，
  2) 把双仓联合回归做实，
  3) 把 TypeScript 全栈运维面补齐。

做到这三点，系统才会从“能跑”进入“稳定可用、可审计、可持续演进”。
