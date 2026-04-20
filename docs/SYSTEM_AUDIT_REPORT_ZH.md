# UFO Galaxy 双仓联排系统性审查报告（中文版）

> **审查范围**：`DannyFish-11/ufo-galaxy-realization-v2`（服务端控制平面）和
> `DannyFish-11/ufo-galaxy-android`（Android 设备运行时）。
>
> **审查原则**：以真实代码为准，不复述 README；明确区分"代码已闭环"与"仅为架构宣称"；
> 不为给出完整答案而编造不存在的闭环。
>
> **信息来源**：核心源文件（`core/`、`galaxy_gateway/`、`contracts/`）、架构完成度评分工具
> `tools/architecture/architecture_completion.py`（运行输出）、已有英文审查文档
> （`docs/DUAL_REPO_FULL_REAUDIT.md`、`docs/DUAL_REPO_GAP_MATRIX.md`、
> `docs/REAUDIT_FRESH_PASS_2.md` 等）、以及 550 个测试文件的覆盖分布。
>
> **架构完成度总分（工具实测）**：**80 / 100**（10 维度中 8 个 CANONICALIZED 或
> COMPLETE，2 个 PARTIAL）。

---

## 目录

1. [系统总体认知](#1-系统总体认知)
2. [两个仓库各自职责](#2-两个仓库各自职责)
3. [双仓真实交互链路](#3-双仓真实交互链路)
4. [主链路识别](#4-主链路识别)
5. [关键模块职责表](#5-关键模块职责表)
6. [系统完成度评估表](#6-系统完成度评估表)
7. [已识别问题清单](#7-已识别问题清单)
8. [最高优先级问题（P0）](#8-最高优先级问题p0)
9. [建议下一步排查顺序](#9-建议下一步排查顺序)
10. [深挖推荐文件清单](#10-深挖推荐文件清单)

---

## 1. 系统总体认知

### 1.1 产品目标与运行目标

UFO Galaxy 是一个 **L4 级自主性分布式智能体系统**，目标是：

- 在 Windows 桌面环境上运行一个具备多模态感知能力的主体智能体
- 通过 Android 设备扩展执行触达能力（GUI 操作、传感器、相机等）
- 支持 130+ 个专业功能节点（VLM、代码引擎、RAG、WebRTC 等）
- 提供两种执行模式：本地执行（Windows API）+ 跨设备执行（Android/远端）

系统的**核心运行目标**是：用户输入 → 主体理解意图 → 智能决策本地或跨设备执行 → 结果回传展示。

### 1.2 这是"本地执行优先 + 跨设备可选"还是"分布式优先 + 本地兜底"？

**基于代码判断：本地执行优先 + 跨设备可选。**

依据：
- `OpenClawd._determine_execution_path()` 的执行分支优先级顺序是 `local → cross_device → hybrid → none`
- Android 端连接是可选的（设备通过 WebSocket 动态注册）
- `DesktopPresenceRuntime` 在 Windows 本地运行，是主体外壳；Android 是扩展执行臂
- 即使无 Android 设备，系统仍可完整运行（本地节点路径）

### 1.3 系统架构的真实形态

系统是**三层架构**：

```
┌─────────────────────────────────────────────────────┐
│  第一层：V2 控制平面 (ufo-galaxy-realization-v2)      │
│  DesktopPresenceRuntime → OpenClawd → CommandRouter  │
│  节点网络（133 个节点）、能力调度、真相投影           │
└─────────────────────────────────────────────────────┘
                          ↕ WebSocket / AIP v3.0
┌─────────────────────────────────────────────────────┐
│  第二层：Android 设备运行时 (ufo-galaxy-android)      │
│  本地执行环路 + 跨设备接入模式                        │
│  GUI 操作 / 传感器 / 相机 / 网络执行                  │
└─────────────────────────────────────────────────────┘
                          ↕ 内部 HTTP / NATS
┌─────────────────────────────────────────────────────┐
│  第三层：节点网络（V2 仓库内部）                       │
│  133 个专业节点：VLM、WebRTC、RAG、代码引擎等          │
└─────────────────────────────────────────────────────┘
```

### 1.4 当前系统更接近"可运行产品"还是"高概念架构集合"？

**真实判断：已可运行的控制平面核心 + 仍处于"合约优先"阶段的多设备协同层**

- ✅ 本地执行主链路（Windows 单机）：**可运行**
- ✅ Android 单设备接入与任务分发：**基本可用**
- ⚠️ 多设备并行协同（MeshSession 等）：**合约定义已完整，运行引擎尚未实现**
- ⚠️ WebRTC 流任务：**完全孤立，未接入任务生命周期**
- ❌ 真正的多设备协调（屏障同步、角色交接、结果合并）：**未实现**

---

## 2. 两个仓库各自职责

### 2.1 `ufo-galaxy-realization-v2`：服务端控制平面（唯一权威真相源）

**真实职责**（基于代码）：

| 子系统 | 真实职责 | 是否主链路 |
|--------|---------|-----------|
| `core/desktop_presence_runtime.py` | 主体外壳，持有三态生命周期 + `runtime_session_id` | ✅ 核心 |
| `core/openclawd.py` | 主体认知核心，4阶段执行：摄入→连续体→分支→显现 | ✅ 核心 |
| `core/command_router.py` | 跨设备执行的唯一调度入口 | ✅ 核心 |
| `galaxy_gateway/` | Android/设备接入的内部执行基础设施 | ✅ 核心 |
| `core/api_routes.py` + `core/routes/` | 唯一权威 REST API | ✅ 核心 |
| `core/capability_assimilation.py` | 统一能力图（节点+设备统一注册） | ✅ 核心 |
| `nodes/（133个）` | 专业执行节点网络 | ✅ 核心 |
| `dashboard/` | 已退役前端 + 遗留兼容 headless 后端 | ❌ 遗留兼容层 |
| `windows_client/status_board_v2/` | 当前唯一运营状态面板（投影驱动） | ✅ 现役展示层 |
| `core/governance/` 系列 | 治理、稽核、一致性约束 | ⚠️ 架构治理层（非执行主链） |
| `android_client/` | 仅一个 README，指向独立仓库 | ❌ 占位符（无实际代码） |

**架构上的"超核"问题**：`core/` 目录拥有约 **300+ Python 文件、16.5 万行代码**，同时承载：
- 真正的执行主链（openclawd、command_router、api_routes 等）
- 治理/稽核层（architecture_invariants、truth_guards、governance 等）
- 协议适配层（ugcp_conformance、cross_repo_consistency 等）
- 实验性/合约优先模块（mesh_session、cross_runtime_result_merge 等）

这导致"哪些是主链路"极难从目录结构直接判断。

### 2.2 `ufo-galaxy-android`：Android 设备运行时（独立边缘智能体）

> ⚠️ **注意**：`ufo-galaxy-android` 仓库代码未在本次审查环境中可直接访问，
> 以下基于 V2 仓库中的文档（`docs/ANDROID_PROTOCOL_ALIGNMENT.md`、
> `docs/REAUDIT_ANDROID_PROTOCOL_V2.md`）和协议文件（`galaxy_gateway/protocol/aip_v3.py`）
> 进行评估。需要直接访问 Android 仓库代码才能做完整验证。

**真实职责**（基于文档和协议描述）：

| 模块 | 声称职责 | 代码验证状态 |
|------|---------|------------|
| `input/` | 输入路由（语音、触摸、键盘） | 需验证 |
| `local/` + `loop/` | 本地执行环路 | 需验证 |
| `runtime/` | Android 边缘运行时 | 需验证 |
| `network/` + `protocol/` | AIP v3.0 协议实现 | 部分验证（与 V2 的 aip_v3.py 对齐） |
| `inference/` | 本地 LLM 推理 | 需验证 |
| `memory/` | 设备端记忆 | 需验证 |
| `webrtc/` | 视频流传输 | 需验证 |
| `observability/` | 设备端可观测性 | 需验证 |

**Android 端是"独立智能体"还是"远端执行终端"？**

基于 V2 文档和协议设计，Android 端兼具两种能力：
- 默认模式：**本地执行智能体**（local-only，不需要服务端连接）
- 可选模式：**跨设备执行终端**（cross-device，接受服务端任务分配）

切换条件：设备通过 `ws://<host>:8765/ws/android` 连接服务端后，由 `CommandRouter` 的 `cross_device` 分支决定是否向该设备派发任务。

---

## 3. 双仓真实交互链路

### 3.1 Android 接入服务端的完整链路（已验证部分）

```
Android App
  │  WebSocket 连接
  ▼
galaxy_gateway/android_bridge.py (AIP v3.0 ingress)
  │  handle_device_register → UDM/UCM
  ▼
core/device_registry.py (兼容索引层)
  + core/unified_config.py (UnifiedDeviceManager — 真相源写入)
  │
  ▼ 【⚠️ 验证中】device_capabilities → CapabilityAssimilationLayer
  │  （文档声称自动转发，代码闭环未完全确认）
  ▼
core/capability_assimilation.py (统一能力图)
```

### 3.2 任务从服务端下发到 Android 的链路（已验证部分）

```
用户输入
  ▼
core/desktop_presence_runtime.py (主体外壳，LIMINAL 阶段)
  ▼
core/openclawd.py (主体核心)
  Stage 3: _determine_execution_path()
  → 分支判断: local / cross_device / hybrid / none
  ▼
  若 cross_device:
core/command_router.py (CommandRouter.route_envelope)
  → admissibility_chain（接纳性检查 Gate 1-3）
  → 【⚠️ 仅 Advisory】CapabilityAssimilation 查询（不是路由门控）
  ▼
galaxy_gateway/device_router.py (DeviceRouter) ← 【⚠️ 仍含策略残留】
  ▼
galaxy_gateway/android_bridge.py (MessageBuilder → 发送 AIP v3.0 消息)
  ▼
Android 设备执行
```

### 3.3 结果回传链路（已验证部分）

```
Android 执行完成
  ▼
galaxy_gateway/android_bridge.py
  handle_task_result / handle_task_end
  ▼
core/task_graph_runtime.py (TaskGraphRuntime)
  + core/replay_foundation.py (ReplayFoundation)
  + core/operator_surface.py (OperatorSurface)
  ▼
core/truth_integration_layer.py (TruthIntegrationLayer)
  ▼ 【⚠️ 部分闭环】compile_outward_truth() 被主要投影端点调用
GET /api/v1/projection/runtime
  ▼
windows_client/status_board_v2/ (状态展示)
```

### 3.4 协议一致性验证

| 协议要素 | V2 实现位置 | 对齐状态 |
|---------|-----------|---------|
| AIP v3.0 消息格式 | `galaxy_gateway/protocol/aip_v3.py` | ✅ V2 侧已定义 |
| 设备注册消息 | `galaxy_gateway/android_bridge.py` | ✅ 已实现 |
| 任务生命周期消息 | `galaxy_gateway/android/handlers/task_lifecycle.py` | ✅ 已实现 |
| task_cancel / task_status | `android_bridge.py` → `_handle_forward_log` | ❌ **仅日志，未传播到 CommandRouter** |
| session_migrate | `galaxy_gateway/session_roaming.py` + `core/routes/sessions.py` | ⚠️ **两套实现，无统一入口** |
| WAKE_EVENT / WAKE_ROUTE_RESULT | AIP v2 二进制 (0x70/0x71) | ❌ **未迁移到 AIP v3 JSON** |
| AIP v2 二进制屏幕/输入 (0x60/0x61) | `compat.py` 中有规范化 | ⚠️ **待迁移** |
| device_id / session_id / task_id 贯通 | `runtime_session_id` 在 DesktopPresenceRuntime 持有 | ⚠️ **Android 侧与 V2 侧的贯通未完全确认** |

---

## 4. 主链路识别

### 4.1 本地执行主链路（Windows 单机，可运行）

```
main.py (System Orchestrator)
  → unified_launcher.py (subordinate launcher)
       → DesktopPresenceRuntime.start()
            → SILENT → LIMINAL (触发: 用户消息/多模态输入)
                 → OpenClawd.process(text, runtime_session_id)
                      Stage 1: Ingest (PerceptionFrame + multimodal_context 融合)
                      Stage 2: ContinuumOrchestrator (意图 → 连续体状态)
                      Stage 3: _determine_execution_path() → "local"
                      Stage 4: Manifest
                           → DecisionExecutor (本地 Windows API 执行)
                                → LocalExecutionResult → 结果回写
                 → MANIFEST → SILENT
       → GET /api/v1/projection/runtime → status_board_v2 展示
```

**主链路文件**：
`main.py` → `unified_launcher.py` → `core/desktop_presence_runtime.py` →
`core/openclawd.py` → `core/agent/kernel.py` → `core/local_execution_chain.py` →
`core/api_routes.py` → `enhancements/clients/windows_client/status_board_v2/`

### 4.2 跨设备执行主链路（Android 扩展，基本可用）

```
（Stage 3 分支到 cross_device）
OpenClawd → CommandRouter.route_envelope(envelope)
  → admissibility_chain（接纳性检查）
  → galaxy_gateway/device_router.py（目标设备选择）
  → galaxy_gateway/android_bridge.py（AIP v3.0 消息构建与发送）
       → Android 设备执行
            → 结果 via handle_task_result()
                 → TaskGraphRuntime → TruthIntegrationLayer
                      → /api/v1/projection/runtime
```

### 4.3 哪些模块"看起来重要"但不在主执行链上

以下模块属于**治理/稽核/一致性层**，不在主执行链上，但占据大量代码空间：

| 模块类别 | 代表文件 | 真实作用 |
|---------|---------|---------|
| 架构诊断 | `core/architecture_diagnostics.py` | 架构不变量检查（CI 用） |
| 真相守卫 | `core/architecture_truth_guards.py` | 投影权威断言 |
| 合约一致性 | `core/cross_repo_consistency_gates.py` | 跨仓合约合规检查 |
| UGCP 合规 | `core/ugcp_conformance_surfaces.py` | 协议合规面检查 |
| 遗留退役 | `core/compat_surface_retirement.py` | 兼容面退役追踪 |
| 架构完成度 | `tools/architecture/architecture_completion.py` | 完成度评分工具 |
| 多设备哈尼 | `core/multi_device_runtime_harness.py` | 多设备运行时测试框架 |

---

## 5. 关键模块职责表

| 模块 | 职责层 | 真实职责描述 | 是否主链路 | 代码规模 |
|------|-------|------------|-----------|---------|
| `core/desktop_presence_runtime.py` | 主体外壳 | 三态生命周期 + runtime_session_id + 多模态摄入总线 | ✅ | ~1507 行 |
| `core/openclawd.py` | 主体核心 | 4 阶段认知执行流（Ingest → Continuum → Branch → Manifest） | ✅ | ~7627 行 |
| `core/command_router.py` | 跨设备基础设施 | 唯一跨设备任务调度入口（route_envelope） | ✅ | ~3984 行 |
| `core/api_routes.py` + `core/routes/` | API 层 | 唯一权威 REST API（聚合入口） | ✅ | ~80 行聚合 |
| `core/capability_assimilation.py` | 能力注册 | 节点+设备能力统一图（CapabilityAssimilationLayer） | ✅ | ~1193 行 |
| `core/device_registry.py` | 兼容索引层 | 设备发现/查询兼容辅助（非真相源写入） | ⚠️ 兼容层 | ~中等 |
| `core/truth_integration_layer.py` | 真相聚合 | 设备真相统一读取接口（TruthIntegrationLayer） | ⚠️ 部分 | 中等 |
| `galaxy_gateway/android_bridge.py` | Android 桥接 | AIP v3.0 协议收发+翻译（非调度权威） | ✅ | 中等 |
| `galaxy_gateway/device_router.py` | 设备路由基础设施 | 目标设备路由（仍含策略残留，待清理） | ⚠️ 含残留 | 中等 |
| `galaxy_gateway/protocol/aip_v3.py` | 协议定义 | AIP v3.0 消息类型枚举（多平台统一协议） | ✅ | 中等 |
| `core/task_graph_runtime.py` | 任务图运行时 | 任务生命周期驱动（结果回流） | ✅ | ~1711 行 |
| `contracts/registered_runtime_device.py` | 设备读合约 | 单设备权威读合约（SSOT 读接口） | ✅ | 小 |
| `contracts/mesh_session.py` | 网格会话合约 | 多设备会话合约（仅合约定义，无运行引擎） | ❌ 合约优先 | 小 |
| `core/multi_llm_router.py` | LLM 路由 | 多模型智能路由 | ✅ | ~1860 行 |
| `enhancements/clients/windows_client/status_board_v2/` | 运营面板 | 唯一现役运营状态展示面 | ✅ | 中等 |
| `dashboard/` | 遗留兼容 | 前端已退役；`backend/main.py` 仅保留兼容 headless | ❌ 遗留层 | 中等 |
| `nodes/（133 个）` | 执行节点 | 专业能力节点网络 | ✅ | 大量 |

---

## 6. 系统完成度评估表

以下评估基于代码存在性、入口闭环、工具实测评分（架构完成度工具返回 80/100）、
已知 Gap 矩阵和测试覆盖分布。

### 6.1 架构完成度

| 判断 | CANONICALIZED（8/10 维度）；总分 80/100 |
|------|----------------------------------------|
| **判断依据** | 工具实测：`get_architecture_completion_scorecard()` 返回 8 维 CANONICALIZED / COMPLETE，2 维 PARTIAL（能力集成完整性、可安装生态就绪度） |
| **主要风险** | `core/` 超核化，治理层代码量远超执行主链，导致真实主链难以识别 |
| **优先级** | P1 |

### 6.2 主链路完成度

| 判断 | 本地主链路已闭环；跨设备链路功能性可用但含已知缺陷 |
|------|---------------------------------------------------|
| **判断依据** | `main.py → DesktopPresenceRuntime → OpenClawd → CommandRouter → gateway` 链路代码存在且有测试覆盖；`task_cancel` / `task_status` 无法正确传播到 CommandRouter（仅日志） |
| **主要风险** | 任务取消缺陷会导致无法取消挂起任务；`DeviceRouter` 含策略残留造成调度路径模糊 |
| **优先级** | P0（task_cancel）/ P1（DeviceRouter 清理） |

### 6.3 Android ↔ 服务端跨仓协同完成度

| 判断 | 单设备接入与基本任务分发：中等就绪；多设备协同：低就绪 |
|------|-----------------------------------------------------|
| **判断依据** | 设备注册、心跳、基本任务分发已实现（AIP v3.0）；`task_cancel` 未传播（HIGH gap）；`session_migrate` 有两套实现无统一入口（HIGH gap）；Android capabilities → CapabilityAssimilation 转发未完全确认 |
| **主要风险** | 取消任务失效；会话迁移不可靠；多设备协调未实现（MeshSession 无运行引擎） |
| **优先级** | P0（task_cancel）/ P0（session_migrate 统一）/ P1（MeshSession 引擎） |

### 6.4 协议一致性完成度

| 判断 | AIP v3.0 核心协议已定义；长尾消息类型仍存在 v2 二进制未迁移 |
|------|-----------------------------------------------------------|
| **判断依据** | `galaxy_gateway/protocol/aip_v3.py` 是协议真相源；但 `WAKE_EVENT`（0x70/0x71）和屏幕/输入二进制类型（0x60/0x61）仍为 AIP v2 二进制格式；两套 session_migrate 实现 |
| **主要风险** | 协议兼容风险；旧客户端连接时行为不一致 |
| **优先级** | P1 |

### 6.5 可运行性完成度

| 判断 | 本地模式可运行；跨设备模式功能性可用但有 known bugs |
|------|--------------------------------------------------|
| **判断依据** | `python main.py` 是权威启动命令（已由 `CLONE_TO_USE_REALITY.md` 和 `scripts/validate_runtime.py` 确认）；但 Android task_cancel 缺陷、session_migrate 双路径问题影响实际可用性 |
| **主要风险** | 任务挂起无法取消；调试面分散 |
| **优先级** | P0 |

### 6.6 可测试性完成度

| 判断 | 架构不变量覆盖良好；主链路集成测试存在；端到端 Android 真实设备测试不确定 |
|------|------------------------------------------------------------------------|
| **判断依据** | 550 个测试文件，含 `test_pr9_integration_validation.py`、`test_android_server_e2e.py`、`test_pr47_canonical_cross_device_chain.py` 等；但 CI 安装测试未验证实际 GitHub addon 包 |
| **主要风险** | 部分测试用 mock 覆盖；Android 真实设备链路测试无法在 CI 中完全验证 |
| **优先级** | P1 |

### 6.7 可观测性完成度

| 判断 | COMPLETE（架构评分为最高级） |
|------|----------------------------|
| **判断依据** | 工具实测：`DIAGNOSTICS_OBSERVABILITY_MATURITY = COMPLETE`；已实现 ArchitectureDiagnostics、ArchitectureTruthGuards、DecisionTimeline、RoutingObservability、ArchitectureCompletionScorecard 等；`scripts/validate_runtime.py` 可验证启动路径 |
| **主要风险** | `LEGACY_DISPATCH` 哨兵仍为日志级别（未发出可观测 metrics）；desktop status board 部分独立于 NetworkTopologyRuntime |
| **优先级** | P2 |

### 6.8 可维护性完成度

| 判断 | 结构已规范化；但 `core/` 超核化严重影响可维护性 |
|------|----------------------------------------------|
| **判断依据** | PR-1 至 PR-10 等系列架构规范 PR 已建立权威边界和守卫；但 `core/` 有 300+ 文件、16.5 万行代码，大量治理/合约/合规文件与执行主链混杂 |
| **主要风险** | 新贡献者难以识别主链路；治理层代码持续增长会进一步模糊主链 |
| **优先级** | P1 |

### 6.9 文档可信度

| 判断 | 英文架构文档质量高，与代码一致性较好；但存在多份并存文档，优先级不清晰 |
|------|----------------------------------------------------------------------|
| **判断依据** | `docs/` 目录有 150+ 文档；`DUAL_REPO_FULL_REAUDIT.md`、`DUAL_REPO_GAP_MATRIX.md` 等高质量且与代码现实对齐；但文档数量庞大，新人难以判断哪份是权威文档 |
| **代码-文档冲突点** | `android_client/README.md` 指向 `DannyFish-11/galaxy-android`，而问题陈述和其他文档均指 `DannyFish-11/ufo-galaxy-android`（仓库名不一致，需确认） |
| **主要风险** | `dashboard/README.md` 仍有大量功能描述，容易误导读者认为其仍是主 UI |
| **优先级** | P1 |

### 6.10 生产可用性完成度

| 判断 | 单机本地模式：接近可用；分布式多设备协同：不可用于生产 |
|------|------------------------------------------------------|
| **判断依据** | 本地 Windows 智能体主链路稳定；但 `task_cancel` 缺陷、`MeshSession` 无运行引擎、WebRTC 孤立于任务生命周期等问题使分布式多设备场景不具备生产就绪性 |
| **主要风险** | 生产场景下无法可靠取消任务；多设备会话无屏障同步和结果合并；WebRTC 视频流任务静默失败 |
| **优先级** | P0（取消缺陷）/ P0（MeshSession 引擎）/ P1（WebRTC 接入） |

---

## 7. 已识别问题清单

### A. 架构问题

**A-01 `core/` 超核化（P1）**
- **描述**：`core/` 有 300+ Python 文件、16.5 万行，同时混杂执行主链、治理层、合约层、实验性模块
- **风险**：主链路认知成本极高；治理层代码体量超过执行层，导致新贡献者无法直接识别主链
- **建议**：将治理/诊断/合规模块迁移至 `tools/architecture/`（已开始：`architecture_completion.py` 已迁移）；为核心执行链模块增加 `#CORE_CHAIN` 标注

**A-02 多入口并存（P1）**
- **描述**：存在 `main.py`、`unified_launcher.py`、`galaxy_main_loop_l4.py`、`scripts/launcher_v2.py`、`launcher/` 子模块等多个启动入口
- **风险**：虽然 `main.py` 已声明为 "System Orchestrator Authority"，但 `scripts/launcher_v2.py` 仍存在独立的 `GalaxyLauncher`，容易造成多入口认知混乱
- **建议**：在 `scripts/launcher_v2.py` 中增加明确的 DEPRECATED 注释，说明权威启动路径是 `main.py`

**A-03 `DeviceRouter` 策略残留（P1）**
- **描述**：`galaxy_gateway/device_router.py` 的 `DeviceRouter._analyze_command()`（策略/分类逻辑）和 `_select_devices()`（设备选择逻辑）仍存在于调度路径中
- **风险**：形成第二条平行设备选择路径，与 `CommandRouter` + 接纳性链路的设备选择形成冲突
- **建议**：将 `_analyze_command` 迁移到 `CommandRouter` 预调度阶段；将 `_select_devices` 迁移至接纳性链路

**A-04 `ConstellationRuntime.DevicePool` 第三条选择路径（P1）**
- **描述**：`core/constellation_runtime.py` 的 `_run_dag_loop()` 调用 `pool.select_device(required_capabilities=caps)`，该 `DevicePool` 是否查询 `CapabilityAssimilationLayer` 未确认
- **风险**：可能存在第三条平行设备选择路径，彻底绕过统一能力图
- **建议**：审计 `DevicePool.select_device()` 实现；若未查询 `CapabilityAssimilationLayer`，强制重定向

**A-05 `dashboard/` 认知权威未完全收敛（P2）**
- **描述**：`dashboard/README.md` 有大量功能描述（节点管理、任务管理、日志等），虽然顶部有退役声明，但描述内容仍使读者误以为其是现役 UI
- **建议**：大幅精简 `dashboard/README.md`，仅保留退役声明和指向 `status_board_v2` 的跳转链接

### B. 跨仓协同问题

**B-01 `task_cancel` / `task_status` 未传播到 CommandRouter（P0 — HIGH）**
- **描述**：Android 发送的 `task_cancel` 和 `task_status` 消息在 `android_bridge.py` 中被 `_handle_forward_log` 捕获，仅记录日志，不传播到 `CommandRouter`
- **风险**：Android 端无法取消正在执行的任务；任务状态更新不传播，导致服务端任务状态不一致
- **建议**：实现 `task_cancel` → `CommandRouter.cancel_task(task_id)` 的传播路径；实现 `task_status` → `TaskGraphRuntime.update_status()` 的传播路径

**B-02 `session_migrate` 双路径无统一入口（P0 — HIGH）**
- **描述**：`galaxy_gateway/session_roaming.py` 和 `core/routes/sessions.py` 存在两套会话迁移实现，语义和持久化路径不同
- **风险**：Android 发起会话迁移时，行为不确定；会话状态可能在两处产生不一致
- **建议**：确定权威路径（建议 `core/routes/sessions.py` 作为权威 API 入口），将 `session_roaming.py` 降级为兼容层并增加守卫

**B-03 Android → `CapabilityAssimilationLayer` 转发未完全确认（P1）**
- **描述**：设备注册时的 `device_capabilities` 字段是否自动转发到 `CapabilityAssimilationLayer.assimilate_device()` 未在代码中完全确认
- **风险**：若不转发，则跨设备路由时无法基于能力匹配选择设备，降级为暴力匹配或随机选择
- **建议**：在 `android_bridge.py` 的 `handle_device_register` 中显式加入 `assimilate_device()` 调用并增加测试

**B-04 AIP v2 二进制消息类型未迁移（P1 — MEDIUM）**
- **描述**：`WAKE_EVENT`（0x70）、`WAKE_ROUTE_RESULT`（0x71）、`ANDROID_SCREEN`（0x60）、`ANDROID_INPUT`（0x61）仍为 AIP v2 二进制格式
- **风险**：新客户端使用 AIP v3.0 JSON 发送此类消息时，服务端无法正确处理
- **建议**：迁移到 AIP v3.0 JSON 类型（`screen_stream_data` / `action_execute` / `wake_event_v3` 等）

**B-05 `device_id` / `session_id` / `task_id` / `trace_id` 跨仓贯通不确定（P1）**
- **描述**：`DesktopPresenceRuntime` 持有 `runtime_session_id`；Android 设备有自己的 `device_id`；V2 的 `TaskEnvelope` 有 `task_id`；这些 ID 在跨仓链路中的贯通映射未有明确文档
- **风险**：分布式 trace 不可贯通；调试跨设备任务链路困难
- **建议**：制定 ID 贯通规范文档；在 `TaskEnvelope` 中显式携带 `runtime_session_id`

**B-06 Android 端本地状态与 V2 外向真相的同步协议未定义（P2）**
- **描述**：Android 端 `runtime/` 中的本地状态（会话快照、目标就绪状态、任务阶段）是否同步到 V2 的 `TruthIntegrationLayer` / `MultiDeviceRuntimeProjection` 未定义
- **风险**：V2 投影可能显示过期的 Android 设备状态
- **建议**：定义 Android → V2 状态同步事件协议（可复用 AIP v3.0 的 `heartbeat` / `device_status` 消息）

### C. 实现问题

**C-01 `MeshSession` / `MeshSessionCoordinator` 无运行引擎（P0 — HIGH）**
- **描述**：`contracts/mesh_session.py` 和 `contracts/mesh_session_coordinator.py` 合约定义完整（`MeshSessionStatus` 状态机、屏障等待、分配进度、合并触发），但无任何运行引擎驱动状态转换
- **风险**：所有声称支持"多设备协同执行"的能力在运行时实际不生效；`MeshSessionStatus` 永远处于初始状态
- **建议**：实现 `MeshSessionEngine`（可从最小可行版本开始：并行分发 + 结果收集 + 状态更新）

**C-02 `CrossRuntimeResultMerge` 无合并引擎（P0 — HIGH）**
- **描述**：`contracts/cross_runtime_result_merge.py` 合约定义了多设备结果合并策略，但无运行时进程驱动合并
- **风险**：多设备并行执行时，各设备结果独立返回，无统一合并，结果展示不完整
- **建议**：与 `MeshSessionEngine` 同步实现结果合并逻辑

**C-03 WebRTC 完全孤立于任务生命周期（P1）**
- **描述**：`galaxy_gateway/webrtc_proxy.py` 存在 WebRTC 信令基础设施，`Node_95_WebRTC_Receiver` 接收视频流，但两者都不与 `CommandRouter` / `TaskEnvelope` 交互
- **风险**：需要实时视频输入的任务（如设备屏幕监控）静默失败或无法启动 WebRTC 会话
- **建议**：在 `TaskEnvelope` 中增加 `requires_webrtc: bool` 字段；`CommandRouter` 在分发前触发 WebRTC 信令握手

**C-04 `CapabilityRegistry` 遗留加载器与规范目录并存（P1）**
- **描述**：部分节点/能力仍通过遗留加载器（而非 `CapabilityAssimilationLayer`）自注册
- **风险**：遗留注册路径上的能力在统一调度时被忽略；导致 `query_routable_executors()` 返回不完整的执行者集合
- **建议**：审计所有能力注册路径；强制通过 `CapabilityAssimilationLayer` 注册；遗留加载器增加守卫

**C-05 `CommandRouter` 能力图查询仅为 Advisory（P1）**
- **描述**：`CommandRouter.route_envelope()` 调用 `query_routable_executors()` / `query_network_path()`，但结果仅用于注解 envelope 元数据，不作为路由门控条件
- **风险**：跨设备路由仍可能选择能力不匹配的设备
- **建议**：将能力图查询结果提升为路由门控；若无匹配执行者则拒绝路由或降级到本地执行

**C-06 多设备 `DevicePool` 第三路径（P1）（同 A-04）**
- 见 A-04

### D. 工程问题

**D-01 `android_client/` 指向仓库名与文档不一致（P1）**
- **描述**：`android_client/README.md` 指向 `DannyFish-11/galaxy-android`，而问题陈述和多处文档均指 `DannyFish-11/ufo-galaxy-android`
- **风险**：读者不清楚 Android 仓库的正确地址
- **建议**：统一修正为实际仓库地址；如两者均存在，需说明其关系

**D-02 `galaxy_main_loop_l4.py` 作为顶层文件的职责不明（P2）**
- **描述**：项目根目录存在 `galaxy_main_loop_l4.py`（非 `main.py`），职责与 `main.py` / `unified_launcher.py` 的关系不清晰
- **风险**：维护者可能误将其作为启动入口
- **建议**：检查此文件是否仍被引用；若为遗留文件，增加 DEPRECATED 注释或删除

**D-03 `docs/` 文档数量过多（150+），优先级不清晰（P2）**
- **描述**：`docs/` 目录有 150+ 文档，读者无法判断哪些是权威文档、哪些是历史记录、哪些已过时
- **建议**：在 `docs/README.md` 中维护一个"权威文档索引"，明确标注每份文档的状态（ACTIVE / HISTORICAL / SUPERSEDED）

**D-04 CI 级别的 addon 安装测试缺失（P2）**
- **描述**：MCP / Skill addon 合约已定义（PR-4/PR-5），但 CI 未验证实际从 GitHub URL 安装 addon 包
- **风险**：addon 安装合约可能在实际安装时失败
- **建议**：添加 CI job：安装一个最小测试 addon 包并验证加载

---

## 8. 最高优先级问题（P0）

以下问题是最紧迫的，必须优先解决：

### P0-1：`task_cancel` / `task_status` 无法传播到 CommandRouter

**位置**：`galaxy_gateway/android_bridge.py` + `core/command_router.py`

**问题**：Android 发送的任务取消消息只记录日志，不传播。这意味着在 Android 端执行的任务一旦启动，服务端无法取消它。这是一个**正确性缺陷**，直接影响任务控制的可靠性。

**最小修复路径**：
1. 在 `android_bridge.py` 的 `handle_task_lifecycle.py::handle_task_cancel` 中增加对 `CommandRouter.cancel_task(task_id, device_id)` 的调用
2. 在 `CommandRouter` 中实现 `cancel_task()` 方法，向目标 `TaskEnvelope` 注入取消信号

---

### P0-2：`session_migrate` 双路径无统一入口

**位置**：`galaxy_gateway/session_roaming.py` vs `core/routes/sessions.py`

**问题**：两套实现，语义不同，Android 发起会话迁移时行为不确定。在多设备场景下会导致会话状态不一致。

**最小修复路径**：
1. 确认哪套实现为权威（建议 `core/routes/sessions.py`）
2. 在 `session_roaming.py` 中增加守卫，将请求重定向到权威路径
3. 更新协议文档说明权威入口

---

### P0-3：`MeshSession` / `MeshSessionCoordinator` 合约优先但无运行引擎

**位置**：`contracts/mesh_session.py`、`contracts/mesh_session_coordinator.py`

**问题**：多设备并行协同的所有合约已定义，但无任何引擎驱动状态转换。所有声称的多设备协同能力（屏障同步、角色交接、结果合并）在运行时均不生效。

**最小修复路径（MVP）**：
1. 实现最小可行 `MeshSessionEngine`：创建 MeshSession → 并行分发子任务 → 收集结果 → 更新状态 → 合并结果
2. 接入 `CommandRouter` 的多设备分发路径
3. 为最小功能集添加集成测试

---

### P0-4：本地执行链路可运行，但 `task_cancel` 缺陷影响任务控制可靠性

这是 P0-1 的后果：在系统对外声明为"可运行"的情况下，一个基本的任务生命周期控制（取消）已损坏，会导致用户体验严重降级。

---

## 9. 建议下一步排查顺序

以下排查顺序基于"修复收益 / 修复成本"的优先矩阵：

### 第一轮：修复正确性缺陷（1-2 周）

1. **修复 `task_cancel` 传播**（P0-1）
   - 文件：`galaxy_gateway/android/handlers/task_lifecycle.py`、`core/command_router.py`
   - 依赖：需要确认 `TaskEnvelope.task_id` 和 Android `task_id` 的映射关系

2. **统一 `session_migrate` 路径**（P0-2）
   - 文件：`galaxy_gateway/session_roaming.py`、`core/routes/sessions.py`
   - 依赖：架构决策（哪个是权威路径）

3. **确认 Android capabilities → CapabilityAssimilation 转发**（B-03）
   - 文件：`galaxy_gateway/android/handlers/registration.py`
   - 快速验证：在 handler 中打印 assimilation 调用；若无则立即添加

### 第二轮：清理调度路径（2-4 周）

4. **清理 `DeviceRouter` 策略残留**（A-03 / SCHED-003）
   - 将 `_analyze_command` 移到 `CommandRouter` 预调度阶段

5. **将 CommandRouter 能力图查询提升为门控**（C-05 / SCHED-001）
   - 修改 `route_envelope()` 使 `query_routable_executors()` 结果成为路由决策依据

6. **审计 `ConstellationRuntime.DevicePool`**（A-04 / SCHED-004）
   - 确认是否查询 `CapabilityAssimilationLayer`；若未查询则修复

### 第三轮：实现多设备运行引擎（MVP 级）（4-8 周）

7. **实现最小可行 `MeshSessionEngine`**（P0-3）
   - 依赖：先完成第一轮和第二轮修复

8. **接入 WebRTC 到任务生命周期**（C-03 / WEBRTC-001）
   - 在 `TaskEnvelope` 增加 WebRTC 触发条件；`CommandRouter` 在分发前触发信令

### 第四轮：工程整洁（持续进行）

9. **统一 android_client README 仓库地址**（D-01，立即可做）
10. **精简 `dashboard/README.md`**（A-05，立即可做）
11. **在 `scripts/launcher_v2.py` 增加 DEPRECATED 注释**（A-02，立即可做）
12. **添加 CI addon 安装测试**（D-04）
13. **建立 `docs/README.md` 文档索引**（D-03）

---

## 10. 深挖推荐文件清单

如需继续深入审查，建议按以下顺序阅读：

### 10.1 理解系统主链路

| 文件 | 理由 |
|------|------|
| `core/desktop_presence_runtime.py` | 主体外壳，理解三态生命周期 |
| `core/openclawd.py` | 主体核心，理解 4 阶段执行流（最关键，7627 行） |
| `core/command_router.py` | 跨设备路由，理解调度机制（3984 行） |
| `docs/CLONE_TO_USE_REALITY.md` | 权威启动路径（clone-to-use 真相） |
| `docs/UNIFIED_SUBJECT_ARCHITECTURE.md` | 统一主体架构详细说明 |
| `docs/LOCAL_EXECUTION_CHAIN.md` | 本地执行链路逐步说明 |
| `docs/CROSS_DEVICE_EXECUTION_CHAIN.md` | 跨设备执行链路逐步说明 |

### 10.2 理解 Android 接入链路

| 文件 | 理由 |
|------|------|
| `galaxy_gateway/android_bridge.py` | Android 桥接层，理解消息处理 |
| `galaxy_gateway/protocol/aip_v3.py` | AIP v3.0 协议定义（协议权威） |
| `galaxy_gateway/android/handlers/` | Android 消息处理器（注意 task_lifecycle.py 中的缺陷） |
| `docs/ANDROID_PROTOCOL_ALIGNMENT.md` | AIP v3.0 协议文档 |
| `docs/ANDROID_PROTOCOL_MATURITY_MATRIX.md` | 协议成熟度矩阵 |

### 10.3 理解已知 Gap 和优先级

| 文件 | 理由 |
|------|------|
| `docs/DUAL_REPO_GAP_MATRIX.md` | 最新结构化 Gap 矩阵（必读） |
| `docs/DUAL_REPO_FULL_REAUDIT.md` | 完整双仓再审查报告（英文，最权威） |
| `docs/REAUDIT_FRESH_PASS_2.md` | 独立新鲜审查视角 |
| `docs/FOLLOWUP_IMPLEMENTATION_ROADMAP.md` | 优先级实施路线图 |

### 10.4 理解多设备协同（Gap 区域）

| 文件 | 理由 |
|------|------|
| `contracts/mesh_session.py` | MeshSession 合约（无运行引擎） |
| `contracts/mesh_session_coordinator.py` | 协调器合约（无运行引擎） |
| `contracts/cross_runtime_result_merge.py` | 跨运行时结果合并合约（无引擎） |
| `docs/MESH_SESSION_CONTRACT.md` | Mesh 会话合约文档 |
| `docs/MULTI_DEVICE_RUNTIME_MATURITY.md` | 多设备运行时成熟度分类 |

### 10.5 理解架构完成度评分工具

| 文件 | 理由 |
|------|------|
| `tools/architecture/architecture_completion.py` | 完成度评分工具（可运行：`from tools.architecture.architecture_completion import get_architecture_completion_scorecard`） |
| `scripts/validate_runtime.py` | 运行时验证脚本 |
| `docs/ARCHITECTURE_COMPLETION_SCORECARD.md` | 评分框架文档 |
| `tests/test_pr9_integration_validation.py` | 集成验证测试套件 |

---

*本报告基于 `ufo-galaxy-realization-v2` 仓库代码的直接审查（2026年4月）。*
*由于 `ufo-galaxy-android` 仓库代码未在当前审查环境中可直接访问，*
*Android 端的评估部分基于 V2 仓库中的文档和协议定义进行推断，*
*标注为"需验证"的项目需要直接访问 Android 仓库代码后才能做最终确认。*
