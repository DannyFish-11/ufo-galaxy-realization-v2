# PR1189：PR1188 后剩余系统体收口过渡（中文）

## 0. 本次 PR 的定位

这是 PR1188 之后的**剩余系统体最终收口过渡**。

PR1188 已经把三个核心系统体问题沉到结构层并可机读暴露：
- 原生三态尚未收敛的结论
- local/cross-device/multi-device 基础层三者的区分
- 任务系统体按执行切块的结构审计

本次 PR 的目标是：
1. 把原生三态问题推进到仓库允许的更远处——尤其明确 静态/阈限态/呈现态 与代码的对应关系
2. 把 local/cross-device/multi-device 推进为更可行的整系统模型，而不只是标签式区分
3. 把任务系统体推进到更清晰的结构真相
4. 把中心智能体的不完整性做更具体的分类
5. 在可行的地方让 board/operator/真值面更有用，不只是更诚实
6. 留下按仓库/层分类的清晰剩余工作图

---

## 1. 原生三态收口推进

### 1.1 直接结论

**当前代码里，`DesktopPresenceRuntime.TriState`（SILENT/LIMINAL/MANIFEST）是 静态/阈限态/呈现态 意图模型的唯一直接工程实现。**

| 中文术语 | 代码值 | 代码来源 | 含义 |
|---------|--------|---------|------|
| 静态 | `TriState.SILENT = "silent"` | `core.desktop_presence_runtime.TriState` | 主体静息；多模态感知在后台持续运行；无活跃认知请求 |
| 阈限态 | `TriState.LIMINAL = "liminal"` | `core.desktop_presence_runtime.TriState` | 请求已收到；OpenClawd 认知/执行正在进行；执行路径在分支选择中 |
| 呈现态 | `TriState.MANIFEST = "manifest"` | `core.desktop_presence_runtime.TriState` | 主体主动呈现输出；控制设备；运行跨设备执行循环；执行完成后回到静态 |

这个映射不是推断，是直接代码对应关系。

### 1.2 代码仅暗示的部分

`core.continuum.tri_state_phase` 使用了相同的 silent/liminal/manifest 术语，但其语义是**内部状态协议**（OpenClawd 认知阶段的内部状态），而非系统级主体生命周期三态。  
两者在术语上吻合，但在语义层级上不等价：
- `DesktopPresenceRuntime.TriState` = 主体对外可见的生命周期状态
- `continuum.tri_state_phase` = OpenClawd 认知引擎的内部阶段协议

这是暗示，不是直接反映。

### 1.3 仍然缺失的部分

1. **跨仓统一规范性 API**：V2 侧有 TriState 枚举，Android 侧没有等价的主体生命周期三态实现。
2. **中文术语权威入口**：静态/阈限态/呈现态 这三个术语在代码注释和文档里没有唯一权威的中文规范说明。
3. **多源三态语义边界固化**：TriState / tri_state_phase / ClosureState 三者的语义边界没有在单一机读文档中固化。

### 1.4 被工程近似遮蔽的部分

`core.current_state_backbone_audit.ClosureState`（established/partial/open）是**工程链路完备度状态**，表示"某条链路是否已闭合"，与 静态/阈限态/呈现态 的主体生命周期语义完全不同。  

**硬边界**：不要把 ClosureState(established/partial/open) 当作 静态/阈限态/呈现态 的等价物。  
**硬边界**：不要把 continuum tri_state_phase 当作系统级主体生命周期三态。

### 1.5 本次仓库侧修复

新增 `core.current_state_backbone_audit._build_native_three_state_closeout()`：
- 显式输出 静态/阈限态/呈现态 ↔ SILENT/LIMINAL/MANIFEST 的直接代码映射
- 显式区分：代码已反映 / 只是暗示 / 仍然缺失 / 被工程近似遮蔽
- 输出 `convergence_assessment`（当前为 `partial_single_canonical_source_identified`）
- 暴露 `canonical_source: core.desktop_presence_runtime.TriState`
- 通过 `build_system_backbone_snapshot()` 的 `native_three_state_closeout` 字段机读透出
- 通过 `core.routes.projection._build_foundational_system_truth()` 向 runtime-truth / desktop-status-board 透出

---

## 2. local / cross-device / multi-device 整系统模型完善

### 2.1 各层角色

| 层 | 角色 | 任务关系 | 代码锚点 |
|---|---|---|---|
| **local** | 单设备本地执行基础层 | 任务起源 → 本地执行 → 结果回流（设备内闭环） | `core.capability_orchestrator`（local 分支）、`core.local_agent_runtime` |
| **cross-device** | 中心将任务路由与委托到其他设备 | 任务起源（中心）→ 委托 → 远端执行 → 结果回传 → 中心聚合 | `core.command_router`、`galaxy_gateway.device_router`、`core.unified_result_ingress` |
| **multi-device** | 多个设备并行参与同一任务系统体 | 任务起源 → 中心拆分 → 多端并行执行 → 分阶段结果回流 → 中心汇总 | `core.mesh_coordinator`、`core.nats_bus`、`core.android_device_state_store` |

### 2.2 各层对任务链路的支撑

**任务起源**：
- local 和 cross-device 均有起源链路（`core.command_router` / `core.runtime.source_dispatch_orchestrator`）
- multi-device 的并发起源分发机制尚未完整闭合

**任务委托**：
- cross-device 委托通过 `galaxy_gateway.device_router` + `CommandRouter` 工程稳定
- multi-device 并行委托没有单一统一机制

**任务执行**：
- local 执行闭环存在（`core.local_agent_runtime`）
- cross-device 执行闭环存在（Android 侧 `execution_pipeline` + V2 侧接收结果）
- multi-device 并发执行稳定验收证据不足

**任务协作**：
- Mesh/NATS 协作通信基础存在，但多设备真实并发协作验收仍不足

**结果回流**：
- 单设备和跨设备回流通过 `core.unified_result_ingress` 工程稳定
- multi-device 并发回流聚合机制仍需完善

### 2.3 代码已支撑的部分

- local/cross-device 两层执行路径工程稳定
- `ModeId.LOCAL / CROSS_DEVICE / MULTI_DEVICE` 三层枚举存在并有状态
- `layered_mode_model` 包含 local_layer / cross_device_layer / multi_device_layer 结构
- `core.mesh_coordinator` 和 `core.nats_bus` 是 multi-device 协作骨架

### 2.4 仍然结构性缺失的部分

1. **统一执行策略引擎**：本地 vs 跨设备 vs mesh/relay/WS fallback 没有统一决策层
2. **多设备并发任务拆分**：把一个任务结构化分配到多台设备并行运行的机制
3. **多设备能力发现与协商**：动态感知各设备当前能力并据此分配的机制
4. **multi-device 稳定并发验收证据**

---

## 3. 任务系统体收口

### 3.1 结构审计（从系统体切块）

| 切块 | 闭合状态 | 代码锚点 | 缺口 |
|------|--------|---------|------|
| **任务起源与理解** | partial | `core.command_router`, `core.runtime.source_dispatch_orchestrator` | 任务语义理解无独立模块，分散拼接 |
| **计划与本地/远端选择** | partial | `core.runtime.source_dispatch_orchestrator`, `galaxy_gateway.routing.device_selection` | 统一规划器缺失，以路径分支代替规划 |
| **委托与执行** | established | `galaxy_gateway/device_router.py`, `core/capability_orchestrator.py` | 工程稳定，但缺设备能力匹配语义层 |
| **协作与恢复** | partial | `core/mesh_coordinator.py`, `core/nats_bus.py` | 协作通信骨架存在，但统一恢复策略缺失 |
| **结果聚合与回流** | established | `core/unified_result_ingress.py`, `core/canonical_completion_ingress.py` | 基本稳定，multi-device 并发聚合尚需验证 |
| **真值更新与操作面投影** | established | `core/result_truth_acceptance_gate.py`, `core/routes/projection.py` | 真值链存在，operator 端操作能力仍弱 |

### 3.2 结构真相说明

当前任务系统体的最大结构问题不是"链路不存在"，而是：
- **没有统一的任务理解/规划层**——当前以工程链路选择代替任务规划
- **设备能力匹配语义层缺失**——任务拆分无法根据设备能力做语义匹配
- **协作执行恢复无统一策略**——各模块有局部 fallback，没有系统级恢复编排

### 3.3 本次修复

PR1188 已在 `build_system_backbone_snapshot()` 中新增 `task_system_body_final_audit`（六切块机读结构）。  
本次 PR 在文档层把结构真相拆穿，不只停留在分层摘要，明确点出"以工程链路代替统一规划"的核心结构问题。

---

## 4. 中心智能体本体分类

### 4.1 当前 V2 中心侧真实已有的

| 组件 | 角色 | 分类 |
|------|------|------|
| `core.command_router.CommandRouter` | 跨设备执行路由 | 中心协调基础设施 |
| `core.capability_orchestrator` | 能力调度（本地 vs 跨设备决策） | 中心协调基础设施 |
| `core.runtime.source_dispatch_orchestrator` | 请求分发编排 | 中心协调基础设施 |
| `core.agent_factory` | Agent 创建（模板/LLM生成/分裂） | 中心智能（部分） |
| `core.rag_memory` | RAG 向量记忆 | 中心智能（部分） |
| `core.mesh_coordinator` / `core.nats_bus` | Mesh/NATS 协作通信骨架 | 中心协调基础设施 |
| `core.unified_result_ingress` | 结果汇聚管道 | 中心协调基础设施 |
| `core.routes.projection` | 真值投影层 | 中心协调基础设施 |

### 4.2 仅是协调基础设施，不等于中心智能体

以下这些**存在但不构成"中心智能体"**：
- 路由/调度/分发——是执行基础设施，不做任务理解
- 结果聚合管道——是数据管道，不做结果语义解析
- 真值投影——是状态暴露，不做运行时决策
- 设备路由——是连接管理，不做设备能力语义匹配

### 4.3 仍然缺失的中心智能体能力

| 缺失能力 | 详情 | 归属层 |
|---------|------|-------|
| 任务理解层 | 自然语言任务语义解析无统一独立模块 | V2 |
| 意图解析层 | intent parsing 分散，无显式独立模块 | V2 |
| 统一计划层 | 无单一规划器，以工程分支代替规划 | V2 |
| 设备能力匹配层 | 设备能力模型（类型/能力/限制/协商）不完整 | V2 + Android |
| 多设备任务拆分层 | 无结构化多设备并行任务分配机制 | V2 |
| 统一失败恢复策略 | 局部 fallback 存在，系统级恢复策略层缺失 | V2 |
| 长短期记忆持续化 | RAG 有向量记忆，跨会话持续化不完整 | V2 |
| 面向用户的可解释输出 | 为什么这么决策，无统一可解释输出层 | V2 + panel-fullstack |
| 面板可消费的智能体状态 | panel 无法实时投影中心智能体在做什么 | panel-fullstack |
| 多模态输入到执行计划转换 | 语音/视觉/屏幕到执行计划的统一管道未闭合 | V2 + multimodal |
| 外部工具/服务调用编排 | MCP 工具调用有基础，统一编排层缺失 | V2 + external-deps |

### 4.4 本次仓库侧修复

新增 `core.current_state_backbone_audit._build_central_agent_body_classification()`：
- 探测并分类现有中心组件（协调基础设施 vs 中心智能部分）
- 显式输出"仅是协调基础设施"的组件列表
- 显式输出缺失能力列表及其归属层
- 通过 `build_system_backbone_snapshot()` 的 `central_agent_body_classification` 字段机读透出
- 通过 `_build_foundational_system_truth()` 向 runtime-truth / desktop-status-board 透出

---

## 5. Board/Operator/真值面实用性提升

### 5.1 此前的问题

之前 board/operator 面的信息更多是诚实，但实用性不足：
- 知道系统"有什么"，不知道"可以做什么"
- 知道哪里是"partial"，不知道"下一步应该修什么"
- 知道有多个三态模型，不知道"哪个是正确的"

### 5.2 本次推进

**原生三态的实用性提升**：
- `native_three_state_closeout.zh_to_code_mapping` 字段：直接给出 静态/阈限态/呈现态 到代码的映射表
- `native_three_state_closeout.canonical_source` 字段：明确指出唯一权威代码源
- `native_three_state_closeout.still_absent` 字段：明确告知还缺什么，而不只是说"没收敛"
- `native_three_state_closeout.masked_by_engineering_approximation` 字段：明确警告工程近似遮蔽问题

**中心智能体的实用性提升**：
- `central_agent_body_classification.still_missing_capabilities` 字段：每项缺失都绑定归属层，使后续修复有明确目标
- `central_agent_body_classification.only_coordination_infrastructure` 字段：明确区分"有了协调基础设施"≠"有了中心智能体"

**剩余工作的实用性提升**：
- `remaining_work_split` 字段：按六个维度分层列出剩余工作，使每个工作方向有明确的施工边界

### 5.3 仍然无法在本次修复的

- operator 端的实际操作能力（手动指派/中止/重试）——需要 panel-fullstack 施工
- 中心智能体的实时状态向 panel 投影——需要 agent 状态机 + panel TypeScript 施工
- board 上的"为什么这么决策"解释层——需要规划层存在后才能解释

---

## 6. 最终剩余工作分层图

### 6.1 V2 中心侧

- 统一中心智能体任务理解/意图解析/规划层
- 设备能力模型（类型/能力/限制/协商）
- 多设备任务拆分与并行分发机制
- 统一失败恢复与重派策略层
- 跨会话长短期记忆持续化
- 面向用户的可解释决策输出层
- 原生三态单一规范性 API 跨仓统一
- 统一执行策略引擎（本地 vs 跨设备 vs mesh/relay fallback）

### 6.2 Android 设备侧

- Android 主动发起任务能力的完整闭合
- Android 局部自治决策机制
- Android 设备能力完整上报与协商接口
- Android 作为多设备协作节点的角色模型（非仅执行端）
- Android 侧原生三态（SILENT/LIMINAL/MANIFEST）对等实现
- Android 本地任务失败恢复与中心回报机制
- Mesh MESH_JOIN/MESH_RESULT/MESH_LEAVE 与 V2 侧规范对齐

### 6.3 Panel / 全栈 TypeScript

- 当前任务视图（任务树/阶段/分解/执行设备）
- 设备总览视图（列表/状态/能力/角色）
- 智能体决策状态视图（计划/决策原因/fallback 原因）
- 执行流路径视图（链路/节点/卡点）
- 结果回流视图（已完成/部分/失败原因）
- mesh/NATS/WS/relay 诊断视图
- operator 操作能力（手动指派/禁用/强制路径/中止/重试/接管）
- 真实 TypeScript operator 控制台（替代原生 JS 静态页）
- runtime truth 实时订阅接口

### 6.4 Desktop Shell / 三态助手

- Tauri/Electron/原生桌面壳（透明窗/悬浮窗/常驻进程）
- 三态切换原生桌面行为（静态/阈限态/呈现态的视觉和交互对应）
- 贴边助手/岛形助手/全屏工作台三种呈现模式
- 全局热键唤起
- 麦克风/摄像头/屏幕录制权限管理
- 系统通知与悬浮通知
- 与 V2 runtime truth 的桌面侧实时对接

### 6.5 多模态输入输出

- 语音输入完整闭合（ASR → 任务起源）
- 语音输出完整闭合（TTS → 呈现态输出）
- 屏幕内容理解（截图/OCR/视觉分析）到任务起源
- 图片/摄像头输入到执行计划转换
- 系统状态感知作为背景上下文
- 多设备上下文聚合
- 跨设备多模态输出协调

### 6.6 外部依赖 / 系统边界

- LLM/模型服务——生产级稳定接入与 fallback 策略
- NATS 基础设施——生产部署、认证、监控
- Mesh 网络——P2P 直连 vs relay fallback 稳定切换
- 语音服务（ASR/TTS）接线完整
- 视觉/屏幕理解服务接入
- 身份认证系统——跨设备身份生产级方案
- 设备发现/心跳/健康检查基础设施
- MCP 工具服务编排

---

## 7. 本次结构修复汇总

### 7.1 代码修复（不只是文档）

**`core/current_state_backbone_audit.py` 新增三个函数**：

1. `_build_native_three_state_closeout()`
   - 显式映射 静态/阈限态/呈现态 ↔ SILENT/LIMINAL/MANIFEST
   - 区分：代码已反映 / 仅暗示 / 仍缺失 / 被工程近似遮蔽
   - 输出 `convergence_assessment` 和 `canonical_source`

2. `_build_central_agent_body_classification()`
   - 探测并分类中心组件（协调基础设施 vs 中心智能部分）
   - 输出缺失能力列表，每项绑定归属层
   - 输出 `verdict_zh`（直接说清楚当前状态）

3. `_build_remaining_work_split()`
   - 按 V2/Android/panel-fullstack/desktop-shell/multimodal-io/external-deps 六路输出剩余工作
   - 使后续 PR 和施工有明确目标

**`build_system_backbone_snapshot()` 新增三个字段**：
- `native_three_state_closeout`
- `central_agent_body_classification`
- `remaining_work_split`

**`core/routes/projection.py` 更新 `_build_foundational_system_truth()`**：
- 新增透出以上三个字段到 runtime-truth 和 desktop-status-board 真值链路

### 7.2 代码真实锚点

- `core/current_state_backbone_audit.py` — 新增三个 `_build_*` 函数，更新 `build_system_backbone_snapshot()`
- `core/routes/projection.py` — 更新 `_build_foundational_system_truth()`
- `core/desktop_presence_runtime.py` — 三态权威实现（`TriState.SILENT/LIMINAL/MANIFEST`）
- `core/command_router.py` — 跨设备执行路由
- `core/capability_orchestrator.py` — 能力调度与本地/跨设备决策
- `core/agent_factory.py` — Agent 创建机制（部分智能层）
- `core/rag_memory.py` — 向量记忆（部分智能层）
- `galaxy_gateway/device_router.py` — 设备路由
- `core/mesh_coordinator.py` — Mesh 协作通信骨架
- `core/nats_bus.py` — NATS 消息总线
- `core/unified_result_ingress.py` — 结果汇聚管道

---

## 8. 仍然缺失（诚实边界）

1. **原生三态跨仓统一 API** 仍未实现——Android 侧无等价三态实现
2. **中心智能体完整性**仍未闭合——任务理解/规划/多设备拆分/统一恢复均缺失
3. **多设备并发协作稳定验收**仍不足——真实多设备并发验收证据不完整
4. **operator 操作能力**仍弱——board/panel 端实际操作层需 TypeScript 施工
5. **三态桌面壳**仍不存在——desktop shell 整层未建

本次 PR 的作用：把以上缺失沉到系统结构层并按层分类，使其机读可查，不再停留在文本描述层。
