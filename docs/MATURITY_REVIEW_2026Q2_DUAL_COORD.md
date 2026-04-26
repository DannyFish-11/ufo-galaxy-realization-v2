# 双坐标系成熟度映射审查
## V2 × Android 六层运行时能力 ∩ AHE 平台治理层 — 2026Q2

> **审查性质**：本文不是系统综述，不是功能清单，也不是文档梳理。  
> **核心产出**：基于两个仓库主分支上的真实代码，对系统当前状态给出**层级达成度判断**。  
> **组织方式**：双坐标系交叉映射，而非并排描述。

---

## 一、真实执行链确认（审查基准）

审查所有判断必须可追溯到这两条真实可执行链。

### V2 主链（代码可证）

```
main.py
  └─ SystemOrchestrator.run_startup_sequence()        [core/system_orchestrator.py]
       ├─ run_startup_recovery()                       [core/runtime_restart_recovery.py]  ← 已接入
       └─ FastAPI app                                  [galaxy_gateway/app.py]
            └─ register_websocket_routes(app)          [galaxy_gateway/routes/websocket.py]
                 └─ /ws/device/{device_id}             [CANONICAL ingress, AIP v3]
                      ├─ normalise_to_v3_dict()        [protocol/compat.py]             ← compat 归一层
                      └─ android_bridge.handle_message()
                           ├─ handlers/registration.py     (device_register)
                           ├─ handlers/heartbeat.py        (heartbeat/device_status)
                           ├─ handlers/task_lifecycle.py   (task_result/task_end)
                           └─ handlers/goal_execution.py   (goal_execution_result)

DeviceRouter.route_task()                              [galaxy_gateway/device_router.py]
  ├─ Step 0: target_device_validator                  [admissibility pre-filter]
  ├─ Step 1: exec_mode via GatewayCapabilityRegistry
  ├─ Step 2: capability_routing_gate.filter_by_required_capabilities()  [硬门控, PR-3]
  ├─ Step 3: autonomous_filter
  └─ Step 4: DevicePoolManager.select_device()
       └─ routing/dispatch.dispatch_to_websocket()
            ├─ build_aip_message(device_id, task_id, trace_id, command)  [AIP v3.0]
            ├─ task_envelope_lifecycle_registry.register()               [内存注册]
            └─ asyncio.Event wait / timeout
```

### Android 主链（代码可证）

```
GalaxyConnectionService.onCreate()
  └─ GalaxyWebSocketClient.connect()    [OkHttp, /ws/device/{device_id}]
       └─ sendHandshake()               [device_register 消息]

GalaxyWebSocketClient.handleMessage()  [收到 task_assign]
  └─ Listener.onTaskAssign()
       └─ GalaxyConnectionService.handleTaskAssign()
            ├─ DelegatedRuntimeAcceptanceEvaluator.evaluate()
            └─ executeLocalTaskAssign()
                 └─ EdgeExecutor.handleTaskAssign()
                      ├─ screenshotProvider.captureJpeg()
                      ├─ plannerService.plan()          ← 接口注入；默认 NoOpPlannerService
                      │    [MobileVlmPlanner → HTTP 127.0.0.1:8080]  ← 需独立 llama.cpp 服务
                      ├─ groundingService.ground()      ← SeeClickGroundingEngine → HTTP 127.0.0.1:8081
                      ├─ accessibilityExecutor.execute()
                      └─ sendTaskResult()               → V2 task_result 消息
```

**关键边界**：Android 的 `plannerService` 在 `GalaxyConnectionService` 中默认被注入 `NoOpPlannerService`，除非在部署时显式替换为 `MobileVlmPlanner`。这是全局事实，不是局部实现细节。

---

## 二、六层运行时能力 — 达成度评级

> 评级说明：  
> **高（≥80%）** = 主链闭合、生产可用、有自动验证  
> **中（40-79%）** = 主链成立但有显著约束或缺口  
> **低（<40%）** = 代码存在但无法支撑真实运行时场景

### L1 交互层

| 维度 | V2 | Android |
|------|-----|---------|
| 协议规范化 | **高**：`normalise_to_v3_dict()` 统一所有入站消息 | **高**：AIPMessageV3.kt 格式完整 |
| 连接接入 | **高**：`/ws/device/{id}` 唯一 canonical ingress | **高**：OkHttp WS，自动重连逻辑 |
| 消息分发 | **高**：handler 体系完整（registration/heartbeat/task_lifecycle/goal） | **高**：`handleMessage` 分发完整 |
| 离线队列 | **中**：存在 replay 路径但 inflight 未跨重启 | **中**：`OfflineTaskQueue.kt` 完整，有文件持久化 |

**L1 整体达成度：高（V2）/ 高（Android）**  
交互层是双仓最成熟的层。协议版本一致性、归一化路径、handler 覆盖均属于真实运行时产物。Android 的 `OfflineTaskQueue` 有文件背后存储，优于 V2 的纯内存 inflight 注册。

---

### L2 上下文感知层

| 维度 | V2 | Android |
|------|-----|---------|
| 截图上下文 | **中**：桌面 Windows 侧有截图 pipeline，非跨平台 | **中**：`AccessibilityScreenshotProvider.kt` 仅 JPEG 截图 |
| UI 语义理解 | **低**：无统一 UI element 解析引擎 | **低**：仅依赖 Accessibility Tree（基础级别） |
| 屏幕 grounding | **低**：V2 不持有 grounding | **中（条件）**：`SeeClickGroundingEngine` → HTTP 127.0.0.1:8081，同需外部服务 |
| 多模态感知 | **低**：MultiLLM 有视觉模型接口但非主链 | **低**：MobileVLM 默认不可用 |

**L2 整体达成度：低-中（V2）/ 低-中（Android）**  
两侧都没有统一的上下文感知主链。V2 的 contextual awareness 主要靠云 LLM 解析文本；Android 的 grounding 依赖外部 HTTP 服务（SeeClick）。在未部署外部 AI 服务的情况下，上下文感知层实际退化为截图传递，没有语义理解。

---

### L3 记忆层

| 维度 | V2 | Android |
|------|-----|---------|
| task_result 持久化 | **中**：`DurableResultIdSet` 文件存储（`data/result_idempotency_set.json`），**但未在 task_lifecycle handler 中默认调用** | **低**：无独立持久层 |
| session truth | **低-中**：`CanonicalSessionTruthRuntime` 是 in-process ring-buffer；`set_audit_store()` 接口存在但非默认激活 | N/A |
| inflight task 持久 | **中**：`TaskLifecyclePersistenceStore` 完整实现（文件原子写），`RuntimeRestartRecovery` 已接入 startup，**但 DeviceRouter `_task_events` dict 仍是纯内存，recovery 后 futures 需重建** | **低**：无 inflight 持久化 |
| conversation history | **低**：无统一对话历史持久层（各 provider adapter 各自实现） | **低** |

**L3 整体达成度：中偏低（V2）/ 低（Android）**  
记忆层是系统当前最大的垂直缺口。V2 的持久化机制是存在的（三个独立模块），但**尚未在主链的关键节点上默认激活**：`check_result_idempotency` 不在 `handle_task_result` 中默认调用，`set_audit_store` 是 opt-in。Android 侧则几乎没有记忆层——任务结果直接回传 V2，不在本地保存语义历史。

---

### L4 任务编排层

| 维度 | V2 | Android |
|------|-----|---------|
| 任务路由 | **高**：4-step routing（admissibility → exec_mode → capability gate → pool）完整 | N/A |
| 设备选择 | **高**：`DevicePoolManager` + `CapabilityRoutingGate`（PR-3，硬门控） | N/A |
| dispatch | **高**：`dispatch_to_websocket`，AIP v3 封装，lifecycle registry 注册 | **高**（接收侧）：`handleTaskAssign` + `DelegatedRuntimeAcceptanceEvaluator` |
| 子任务 / TaskGraph | **中**：`TaskGraph` 模块存在，`task_graph_runtime.py`，但在主 routing 链中是 additive 而非强制 | **低**：`EdgeExecutor` 是线性单步执行，无子任务分解 |
| 多设备并发 | **中**：`CrossDeviceCoordinator` 存在，mesh 路径完整，但需配置激活 | N/A（被动执行端） |

**L4 整体达成度：高（V2 单设备路由）/ 中（V2 多设备）/ 中（Android 执行侧）**  
V2 的任务编排是系统第二强的层。单设备路由主链完整，已有 CI 验证。多设备编排结构存在但 operationally 依赖正确配置。Android 侧的 `DelegatedRuntimeAcceptanceEvaluator` 提供了准入判断，但执行模型是 plan → ground → execute 线性单步，不具备独立编排能力。

---

### L5 系统执行层

| 维度 | V2 | Android |
|------|-----|---------|
| 操作系统执行 | **中**：依赖 Windows Python client（截图+键鼠），非跨平台 | **高（条件）**：Accessibility executor 完整，BootReceiver 实现自启动 |
| 结果返回闭环 | **高**：task_result → `asyncio.Event` 解锁 → Future resolved | **高**：`sendTaskResult()` 完整 |
| 错误处理 | **中**：有 fallback / timeout，但 retry 语义不统一 | **中**：`replan` 接口存在，`NoOpPlannerService` 在本地 AI 不可用时保证不崩溃 |
| 本地 AI 执行 | **低**：V2 不持有本地执行模型 | **低（默认）**：`NoOpPlannerService` 是默认实现；`MobileVlmPlanner` 需独立部署 llama.cpp + 模型权重 |

**L5 整体达成度：中（V2）/ 中-高（Android，不含本地 AI）**  
Android 的 Accessibility 执行路径是系统中最接近"真实物理执行"的部分——给定云端规划结果，Android 可以真实操作 UI。但系统执行层的"本地 AI 自主决策能力"仍是 unavailable by default。

---

### L6 外部能力层

| 维度 | V2 | Android |
|------|-----|---------|
| 云 LLM | **高**：`MultiLLMRouter` 完整，支持 OpenAI/Claude/Gemini/DeepSeek/Ollama，故障转移 | **低**：无直接云 LLM 调用，依赖 V2 |
| MCP 扩展 | **中**：`mcp_loader.py` + MCP bridge 存在，但非所有场景默认激活 | **低** |
| Skill 扩展 | **中**：`skill_loader.py` + `SKILL.md` 格式，自动加载 | **低** |
| 本地 AI / VLM | **低**：接口预留，非主链默认 | **低（默认）**：`MobileVlmPlanner` 完整实现，依赖外部 HTTP 服务（127.0.0.1:8080） |
| SeeClick grounding | **低**：无 V2 侧 | **低（条件）**：`SeeClickGroundingEngine` → HTTP 127.0.0.1:8081 |
| WebRTC / mesh | **中**：WebRTC proxy 和 mesh coordinator 存在，非默认激活 | **中**：WebRTC client 完整，非主执行链 |

**L6 整体达成度：中-高（V2 云 LLM）/ 低（Android 外部能力）**  
V2 的云 LLM 外部能力是最强的外部能力成分，且有路由策略和 fallback。Android 的外部能力完全依赖 V2 作为 AI 决策代理，本地外部能力仅在部署了独立 inference server 时成立。

---

## 三、AHE 四层平台治理 — 达成度评级

### 接入适配层

**达成度：高（约 75-85%）**

- 协议归一化：`normalise_to_v3_dict()` 覆盖 AIP v1/v2/v3，所有 compat 路径有分类标记
- 身份注册：`handle_device_register()` → UDM 完整
- 能力上报：`handle_capability_report()` handler 完整，`GatewayCapabilityRegistry` 支撑 exec_mode 判断
- 协议版本守卫：`test_android_ci_baseline.py` 已验证 AIP v3 字段稳定性

**不足**：
- compat 路径的"deprecated → blocked"收口只有 PR-S6 标记，没有默认 hard-block（仍靠 guardrail log）
- 身份认证层较基础（无 mTLS / token 验证主链）

---

### 编排管理层

**达成度：中-高（约 55-65%）**

- V2 是真实 orchestrator：4-step routing，capability gate，pool selection
- TaskGraph 模块存在但在单设备场景中不是强制启用
- 任务生命周期注册：`TaskEnvelopeLifecycleRegistry` 完整，但纯内存（重启丢失）
- 低代码工作流：不存在，所有编排为程序化

**不足**：
- in-flight task 持久化：`TaskLifecyclePersistenceStore` 完整，但 `DeviceRouter._task_events` 仍是 `Dict[str, asyncio.Event]`，重启后 future 无法恢复
- 可视化编排：不存在
- 任务版本控制：不存在

---

### 协同决策层

**达成度：低（约 20-30%）**

- 当前能力：`capability_routing_gate.filter_by_required_capabilities()` 实现设备能力匹配（单维 filter），是系统中最接近协同决策的部分
- `AutonomousFilter` 决定任务是否进入自主执行路径
- 多设备场景：`CrossDeviceCoordinator` + mesh 存在，但未在默认场景激活
- 多智能体协商/博弈/强化学习：**不存在**
- 全局效用最大化：**不存在**
- 冲突消解：**不存在**（多设备时靠 pool selection 而非真正协商）

**结论**：协同决策层目前本质上是"单维度设备能力 filter + 静态 policy"，而不是真正的多智能体协同决策机制。这是系统相对于 AHE 参考架构最大的结构性缺口。

---

### 观测治理层

**达成度：中（约 40-50%）**

- 日志：标准 Python logging，有 structured log 在部分模块
- CI 自动化：V2 有 5-job dual-repo CI workflow（transport harness / protocol regression / contract drift guard / composite gate）
- Android CI：build / lint / unit test（无 emulator E2E）
- protocol drift guard：`test_android_ci_baseline.py` 验证 AIP v3 字段稳定性
- 健康检查：`/api/v1/health` 端点存在，`health_monitor.py` 有 startup 检查

**不足**：
- **链路追踪**：trace_id 在消息中存在，但无统一的分布式 trace 收集（无 Jaeger/Zipkin 集成）
- **指标监控**：`slo_metrics.py` 存在但无 Prometheus/Grafana 默认接入
- **故障自愈**：`healing_engine.py` 存在，实际效果未在 CI 中验证
- **Android E2E emulator 验证**：不存在，最大的治理盲区
- **合规/隐私**：无代码层面合规校验

---

## 四、双坐标系对照汇总表

| 六层能力 | V2 达成度 | Android 达成度 | 对应 AHE 层 | AHE 该层达成度 |
|---------|----------|--------------|------------|--------------|
| L1 交互层 | **高** | **高** | 接入适配层 | **高（75-85%）** |
| L2 上下文感知层 | **低-中** | **低-中** | 编排管理层（感知输入） | **中（部分）** |
| L3 记忆层 | **中偏低** | **低** | 编排管理层（状态持久） | **中（持久缺口）** |
| L4 任务编排层 | **高（单设备）** | **中（执行侧）** | 编排管理层 | **中-高（55-65%）** |
| L5 系统执行层 | **中** | **中-高（不含本地 AI）** | 协同决策层 | **低（20-30%）** |
| L6 外部能力层 | **中-高（云 LLM）** | **低（默认）** | 观测治理层 | **中（40-50%）** |

---

## 五、不均衡结构成因分析

系统形成了一个明显的**"交互/路由强，感知/记忆/协同弱"**的不均衡结构，原因有三：

### 原因 1：协议 + 路由优先建设
早期多轮 PR 集中解决双仓协议对齐（AIP v1→v3）、ingress 归一化、routing 4-step、capability gate。这类工作收效快、可测试性高、对系统可运行性贡献最直接，因此 L1 + L4 成为最成熟的层。

### 原因 2：持久化 / 记忆层晚启动
`DurableResultIdSet`、`TaskLifecyclePersistenceStore`、`CanonicalSessionTruthRuntime.set_audit_store` 均是较晚的 PR（PR-B2、PR-D1、PR-S5）产物，且设计为 opt-in additive。实际接入点（task_lifecycle handler、DeviceRouter future dict）尚未全部完成默认化。

### 原因 3：AI 执行层外部依赖未解决
上下文感知（SeeClick）和本地规划（MobileVLM）都需要独立部署的外部 HTTP 服务，而这个部署本身不属于仓库代码范围。这是一个**部署 gap，而非代码 gap**——代码完整，但 default runtime state 是 no-op。

### 原因 4：Android 仓天然被动角色
Android 作为执行参与者（非 orchestration authority），其上层能力（记忆、协同、观测）应由 V2 主动推送或 Android 本地部署，两条路都有缺口。

---

## 六、最强 / 最弱层一览

| 维度 | 最强 | 最弱 |
|------|------|------|
| 六层中（V2） | L4 任务编排层（routing 4-step + capability gate） | L3 记忆层（持久化未默认激活） |
| 六层中（Android） | L1 交互层（WebSocket + 协议） + L5 Accessibility 执行 | L3 记忆层（几乎不存在） |
| AHE 四层 | 接入适配层（协议归一化 + 注册 + 能力上报） | 协同决策层（无真实多智能体协同机制） |

---

## 七、最终系统定位判断

### 这套系统现在是什么

> **中心式分布式智能体系统雏形（主链可运行期，进入系统整合期早期）**

具体判断依据：

**已是真实系统（不只是结构系统）的方面**：
- 双仓 WebSocket 传输闭环成立（代码 + CI 双重验证）
- 单设备任务路由主链完整（V2 routing → dispatch → Android execute → result return）
- 协议稳定性有自动守卫（protocol regression + contract drift）
- Accessibility 执行路径真实可用（给定正确的 plan 输出）
- 云 LLM 路由有 failover（MultiLLMRouter）

**仍是结构系统而非成熟平台的方面**：
- 上下文感知 + 本地 AI 执行需独立部署（外部 HTTP 依赖）
- 记忆持久化机制存在但未默认激活
- 多智能体协同机制不存在（协同决策层仅有静态 filter）
- Android E2E 协议验证不存在
- 链路追踪 / 分布式 observability 未接入

### 相对于六层参考架构，已完成多少

**粗估：约 55%**（加权：交互 + 路由 强，上下文 + 记忆 + 协同 弱）

### 相对于 AHE 四层，已完成多少

**粗估：约 45%**（接入适配层高完成度；协同决策层几乎未实现，拉低整体）

### 距离平台化、治理化、持久化、协同化还差什么

| 目标 | 差距 |
|------|------|
| **持久化** | V2 truth/task lifecycle 持久化需在主链节点默认激活（非 opt-in） |
| **平台化** | 需要可视化编排 / 工作流 DSL / 任务版本控制 |
| **治理化** | 需要真实 hard-gate enforcement（而非 advisory guardrail）+ 分布式 trace 接入 |
| **协同化** | 需要真实多智能体协商机制，而不只是单维 capability filter |
| **Android 治理闭环** | 需要 emulator/真机 E2E 自动验证 + local AI inference 部署脚本 |

---

## 八、本次审查范围边界说明

- 本文基于 `DannyFish-11/ufo-galaxy-realization-v2` 和 `DannyFish-11/ufo-galaxy-android` 两个仓库截至 2026-04-26 的主分支真实代码。  
- 所有判断以可追溯到具体源文件和方法为准。  
- 不依赖 `docs/` 目录中既有审查文档的结论。  
- 本文是一次性映射审查，不是持续治理文档。  
- Android 仓代码基于 GitHub API 读取，未在本地构建运行。

---

*文件路径：`docs/MATURITY_REVIEW_2026Q2_DUAL_COORD.md`*  
*审查时间：2026-04-26*
