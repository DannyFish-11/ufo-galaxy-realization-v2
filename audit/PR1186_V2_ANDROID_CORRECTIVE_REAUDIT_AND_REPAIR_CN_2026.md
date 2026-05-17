# PR1186：V2 + Android 全仓纠偏重审与可落地修复（中文）

## 0. 这次修什么（直接结论）

这次不是只写认知文档。  
这次同时做两件事：

1. 用真实代码重审系统基础模型（跨设备、多设备、三态、任务全链）。
2. 把能立刻修的 truth surface 修掉（runtime-truth 与 status_board_v2）。

---

## 1. 基础模型纠偏：跨设备 vs 多设备（必须分开）

### 1.1 跨设备（cross-device）在本系统里的真实定义

跨设备 = 任务从中心路由到“另一个设备”执行。  
它是**路由能力层**，不是“设备数量”的概念。

代码锚点（V2）：
- `core/current_state_backbone_audit.py`（`ModeId.CROSS_DEVICE`）
- `core/command_router.py`
- `galaxy_gateway/device_router.py`

### 1.2 多设备（multi-device）在本系统里的真实定义

多设备 = 多个设备同时接入并参与，形成参与矩阵与可调度集合。  
它是**参与结构层**，不是“是否跨设备派一次任务”。

代码锚点（V2）：
- `core/current_state_backbone_audit.py`（`ModeId.MULTI_DEVICE`）
- `core/routes/projection.py`（`_build_participation_truth_consumption`）
- `windows_client/status_board_v2/device_surface.py`

### 1.3 层关系（本地 → 跨设备 → 多设备）

系统真实层关系：
- 本地层：设备自执行能力（local）。
- 跨设备层：中心将任务路由给其他设备（cross-device）。
- 多设备层：多个设备并行参与同一系统（multi-device participation）。

这次已把该层关系输出到板面真值字段：
- `core/routes/projection.py` 新增 `_build_foundational_system_truth`

---

## 2. 三态纠偏：不是通用助手 UI 三态

这次明确采用**工程闭合三态**，来源是实际代码审计模型，而不是语音助手类比：

- `established`
- `partial`
- `open`

真实来源：
- `core/current_state_backbone_audit.py`（`ClosureState` + `build_system_backbone_snapshot`）

这次修复点：
- 把三态计数直接放进 runtime truth / desktop board payload；
- 在 `status_board_v2` 直接显示 `est/par/open`。

---

## 3. 任务系统全链重审（分层整体看，不拆碎）

任务链按真实代码分层：

1. 请求/派发链（request_dispatch）
2. 执行链（execution）
3. 结果回流链（result_backflow）
4. 闭环验收链（closure_acceptance）
5. 投影链（projection）

真实来源：
- `core/current_state_backbone_audit.py`（`ChainId` + `build_system_backbone_snapshot`）
- `core/unified_result_ingress.py`
- `core/routes/projection.py`

这次修复点：
- 任务分层闭合状态进入 `foundational_system_truth.task_system_layered_status`，让 operator 面可直接看到“哪条链是 partial/open”。

---

## 4. 这次做的“代码修复”（不是只写文档）

### 4.1 runtime-truth 与 desktop-status-board 新增基础真值块

文件：
- `core/routes/projection.py`

新增：
- `_build_foundational_system_truth(...)`
- `payload["foundational_system_truth"]` 注入到：
  - `/api/v1/projection/runtime-truth`
  - `/api/v1/projection/desktop-status-board`

### 4.2 status board 面板直接显示纠偏信息

文件：
- `windows_client/status_board_v2/device_surface.py`

新增显示：
- `Layer: cross_device=... | multi_device=...`
- `3-State: est=... par=... open=...`

目的：让操作面直接区分“跨设备能力”和“多设备参与结构”，并看到真实三态，而不是靠猜。

### 4.3 runtime-truth 读取链保持字段透传

文件：
- `windows_client/status_board_v2/projection_reader.py`

新增透传键：
- `foundational_system_truth`

---

## 5. 双仓代码证据锚点（V2 + Android）

V2：
- `core/current_state_backbone_audit.py`
- `core/command_router.py`
- `galaxy_gateway/device_router.py`
- `core/unified_result_ingress.py`
- `core/routes/projection.py`
- `windows_client/status_board_v2/device_surface.py`

Android（按已审计锚点）：
- `app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt`
- `app/src/main/java/com/ufo/galaxy/service/GalaxyConnectionService.kt`
- `app/src/main/java/com/ufo/galaxy/agent/AutonomousExecutionPipeline.kt`
- `app/src/main/java/com/ufo/galaxy/runtime/AndroidMeshParticipationContract.kt`

---

## 6. 诚实结论：已修与未完

### 已修
- 基础层语义（跨设备 vs 多设备）已进入板面可见真值。
- 三态已明确绑定工程闭合三态，且板面可见。
- 任务链分层闭合状态已进入板面载荷。

### 仍未完成
- 完整中心智能体（规划/记忆/策略恢复）仍是部分能力组合，不是单一完整体。
- Android 与 V2 的全量端到端多设备并行实操证据仍不充分（仍有 partial/open 项）。
- operator GUI 级交互闭环（不仅 CLI board）仍待继续建设。

---

## 7. 本 PR 的边界

本 PR 只做“可立即落地且风险可控”的纠偏修复：  
把真实系统基础层与三态/任务链真值接到 operator truth surface。  
没有伪造“已全部完成”，未完成项保持公开。
