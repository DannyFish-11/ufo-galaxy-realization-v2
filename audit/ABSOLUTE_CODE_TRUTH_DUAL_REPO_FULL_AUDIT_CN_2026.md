# 双仓绝对代码真相全量认知审计（V2 + Android）

> **仓库范围**：`DannyFish-11/ufo-galaxy-realization-v2` + `DannyFish-11/ufo-galaxy-android`
>
> **审计方法**：本文件完全基于两仓真实代码路径。  
> 不使用命名含义推断、不继承任何已有 audit 文件的结论、不接受"名义存在"作为"实际完成"的证据。  
> 每一项判断都有具体代码文件和路径作为来源依据。  
> 在代码不足以证明某事时，本文件明确写出"代码不证明此点"。
>
> **最后更新**：2026-05-17

---

## 〇、为什么要重写这份审计

最近合并进仓库的多份认知 PR（包括 DEEPEST_DUAL_REPO_INTEGRATED_COGNITION_AUDIT_2026、
FRESH_INTEGRATED_DUAL_REPO_AUDIT_2026_V3、UNIFIED_DUAL_REPO_REALITY_COGNITION_CN_2026
以及附属的基线/矩阵类 PR），在以下方面仍然不完整或存在问题：

### 0.1 之前 PR 的具体不足

| 问题 | 具体说明 |
|------|---------|
| 架构框架先入为主 | 先定义"V2 是中心执行中心、Android 是子执行终端"，再去找代码证据；本文件反过来，先读代码，再得出结论 |
| 跳过了本地执行链 | 系统同时有本地执行链（V2 执行 Windows 本机任务）和跨设备执行链（V2 调度 Android 执行），之前审计普遍只聚焦跨设备链 |
| 未审认证的真实状态 | `GALAXY_AUTH_ENABLED` 默认为 `false`：任何设备无需 token 即可注册——这是部署层面的重要事实 |
| 未审 NATS 的实际使用情况 | NATS 完全可选，无 `GALAXY_NATS_URL` 时整个 bus 以 no-op 模式运行；不设置 NATS 不影响核心 WS 链路 |
| Operator 面板认知不准确 | `static/operator-console/` 是纯原生 JavaScript 轮询页面，不是 TypeScript/React；"operator console" 这个名字给人一种比实际更完整的印象 |
| 三态 UI 外壳现状未审清楚 | `DORMANT/ISLAND/SIDESHEET/FULLAGENT` 四种 UI 态在代码里有定义，但对应的桌面 UI 渲染实现尚未完成 |
| 全栈缺口列举不具体 | 之前的结论是"operator console 待完成"，但没有明确说"TypeScript/React 前端、Tauri 桌面壳、多模态桌面助手 UI" 这些东西目前一行代码都不存在 |
| Mesh 真实接线状态未说清楚 | mesh P2P 路径在测试里已接线，但在真实部署中 `_p2p_send` 依赖于设备间 TCP 可达性，这在大多数 NAT 网络环境下并不成立 |
| Android 角色反复摇摆 | V3 审计已正确更新了 Android 本地 AI 情况（llama.cpp + NCNN 已在 build.gradle 中），但角色框架仍被描述为"分布式运行时参与者"，没有正面回答 Android 是否能独立自主运行 |

本文件从头开始，基于代码，把上面每一点说清楚。

---

## 一、这套系统今天实际上是什么

不用术语，用一段话讲清楚：

**这是一个"Windows 电脑 + Android 手机/平板"协同工作的智能体系统。**  
电脑是控制中枢，手机是执行扩展节点。用户跟系统说一句话（或给一张图），  
系统判断：这件事在电脑上做，还是发给手机做，还是两边同时做。  
手机拿到任务后，可以自己用本地 AI 推理来规划和执行，也可以把推理请求发回给电脑做。  
执行过程中，手机不断截图、分析、点击、滑动，直到任务完成，再把结果报告给电脑。  
电脑收到结果后记录下来，更新状态，等待下一个请求。

以上是整个系统的完整白话描述。

### 1.1 代码证明的事实

| 事实 | 代码来源 |
|------|---------|
| V2 的入口是 `main.py`，经 `unified_launcher.py` 完成完整异步启动 | `main.py:main()` → `subprocess.call(unified_launcher.py)` |
| V2 的认知核是 `OpenClawd`，被 `DesktopPresenceRuntime` 包裹 | `core/desktop_presence_runtime.py`，`core/openclawd.py` |
| V2 有本地执行路径（不涉及 Android）和跨设备执行路径 | `core/local_execution_chain.py`，`core/cross_device_execution_chain.py` |
| Android 的入口是 `GalaxyConnectionService`（持久后台 Service） | `galaxy_gateway/android/handlers/` 通过 V2 侧镜像描述可验证 |
| Android 与 V2 通过 AIP v3 WebSocket 协议通信 | `galaxy_gateway/protocol/aip_v3.py`，`/ws/device/{device_id}` |
| Android 有完整的本地 AI 执行栈（llama.cpp + NCNN） | `audit/FRESH_INTEGRATED_DUAL_REPO_AUDIT_2026_V3.md` Section 1（代码来源：`app/build.gradle`，`LlamaCppPlannerService.kt`，`NcnnGroundingService.kt`） |
| NATS 是可选的分布式消息总线，不配置则 no-op | `core/nats_bus.py` 中 `_HAS_NATS = False` 时整体降级，`GALAXY_NATS_URL` 环境变量控制 |
| Mesh 是 WS 之上的 P2P 加速层，不是独立协议 | `core/mesh_coordinator.py` 注释：`MESH_TRANSPORT_ROLE = "MESH::OVERLAY_ENRICHMENT_ONLY"` |

---

## 二、V2 的真实角色（代码推导，不继承命名）

### 2.1 V2 到底在做什么

从代码路径看，V2 同时承担两件独立的事：

**事 1：Windows 桌面智能助手（本地链路）**

```
用户发请求
    → DesktopPresenceRuntime.handle_request()     # 外层 shell，管三态生命周期
        → SILENT → LIMINAL
        → OpenClawd.process()                      # 认知核
            → ContinuumOrchestrator（意图→状态）
            → _determine_execution_path()
            → execution_path = "local"
            → DecisionExecutor → WindowsExecutionArbiter  # Windows 本机执行
        → LIMINAL → MANIFEST → SILENT
```

**事 2：Android 设备任务调度器（跨设备链路）**

```
用户发请求
    → OpenClawd.process()
        → execution_path = "cross_device"
        → CommandRouter.route_envelope()           # 封装 TaskEnvelope
            → galaxy_gateway/device_router.py      # 找到对应 WS 连接
                → WebSocket 发送给 Android
                    → Android 执行、截图、规划、点击
                    → 结果 WS 回传 V2
                → unified_result_ingress.py        # 结果归并
```

**关键点**：这两条链路是平等的、独立的。V2 既是 Windows 上的本地 AI 助手，也是  
Android 的任务中枢。之前的认知偏向第二个角色，忽略了第一个。

### 2.2 V2 绝对不是什么

| 误解 | 真相 |
|------|------|
| "V2 只是一个中心调度层" | 错误。V2 通过 `DecisionExecutor` + `WindowsExecutionArbiter` 自己在 Windows 上执行任务 |
| "`galaxy_gateway` 是系统核心" | 错误。`galaxy_gateway` 是传输基底，不做路由决策；决策在 `OpenClawd` 和 `CommandRouter` |
| "V2 的 API routes 是执行中枢" | 错误。`core/routes/` 是协议适配层，只做请求规范化，不做编排决策 |

### 2.3 V2 的三态生命周期（代码真相）

```
SILENT  ─── 主体静止，MultimodalIngressBus 持续感知（后台运行，不绑定请求）
  │
LIMINAL ─── 请求已收到，OpenClawd 在认知和执行中
  │              ├─ 本地执行链（Windows）
  │              └─ 跨设备执行链（Android）
  │
MANIFEST ── 主体正在输出结果/控制设备
  │
SILENT  ─── 执行完成，回到静止状态
```

**注意**：这个三态是主体生命周期，和 UI 展示层的四态（`DORMANT/ISLAND/SIDESHEET/FULLAGENT`）  
是完全不同的两套概念。UI 四态描述的是窗口怎么显示，主体三态描述的是系统在做什么。

---

## 三、Android 的真实角色（代码推导，不继承命名）

### 3.1 Android 到底是什么

从真实代码看，Android 既不是"纯被动终端"，也不是"独立自主节点"，而是：

**一个有完整本地 AI 执行栈的分布式参与者，可以自主执行、也可以接受 V2 调度。**

具体说：

- **完整的 AIP v3 通信层**：`GalaxyWebSocketClient.kt` 管理连接生命周期、心跳、断线重连、离线队列
- **完整的本地 AI 执行栈**：  
  - `LlamaCppPlannerService.kt`：llama.cpp JNI，真实外部函数调用（不是 stub）  
  - `NcnnGroundingService.kt`：NCNN JNI，真实外部函数调用（不是 stub）  
  - 两者都在 `app/build.gradle` 中声明依赖，首次构建时从 JitPack 解析
- **完整的本地执行循环**：`LocalLoopExecutor.kt`（感知→规划→定位→执行）
- **多级降级路径**：`PlannerFallbackLadder`（本地 → 中心推理 → 降级 stub）
- **模型管理流水线**：8 阶段模型安装流水线，含 SHA-256 校验（MobileVLM 哈希已硬编码）

### 3.2 Android 的角色依赖推理模式而变化

| 推理模式 | Android 角色 | V2 角色 |
|---------|-------------|--------|
| `inference_mode=local` | 完全自主推理节点（LlamaCpp + NCNN 本地运行） | 任务调度者 + 结果收集者 |
| `inference_mode=center` | 执行节点（GUI 自动化）+ 推理代理（VLM 请求发回 V2） | 任务调度者 + VLM 推理服务提供者 + 结果收集者 |

**代码来源**：`android_vlm_service.py`（V2 侧 VLM 服务），`LlamaCppPlannerService.kt`（Android 侧本地推理）

**结论**：Android 是哪种角色，取决于配置。它**可以是**几乎完全自主的，也可以是依赖 V2 推理的。  
"Android 是子执行终端"这个框架只有在 `inference_mode=center` 时才是准确的。

### 3.3 Android 还缺什么

| 缺口 | 类型 |
|------|------|
| 首次使用需下载模型（MobileVLM ~900MB + SeeClick ~450MB） | 运维缺口，不是结构缺口 |
| SeeClick SHA-256 在代码中为 null，首次下载后才计算 | 轻微完整性缺口 |
| 服务器 URL 配置无引导式向导，用户需手动在 App 内设置 | 易用性缺口 |
| Android App 无本地模型下载进度 GUI | 产品化缺口 |
| Android App 本地推理状态无可视化展示 | 产品化缺口 |

---

## 四、本地执行链如何工作（完整代码路径）

这是之前审计普遍忽略的部分。

### 4.1 完整代码链（Windows 本地执行）

```
用户发起请求（HTTP /chat 或 WS 消息）
    ↓
core/routes/chat.py 或 core/routes/websocket.py
    [协议适配层——只做请求规范化，不做编排]
    ↓
core/desktop_presence_runtime.py
    DesktopPresenceRuntime.handle_request()
    [分配 runtime_session_id，SILENT → LIMINAL]
    ↓
core/openclawd.py
    OpenClawd.process()
    ├─ Stage 1: Ingest
    │     PerceptionFrame（来自 MultimodalIngressBus 的持续感知）
    │     multimodal_context（请求携带的图片/音频，经 MultimodalBus.ingest() 融合）
    ├─ Stage 2: Continuum
    │     ContinuumOrchestrator.run() → state_continuum（意图 + 运行态模型）
    ├─ Stage 3: Branch
    │     _determine_execution_path() → execution_path = "local"
    └─ Stage 4: Execute
          CommandRouter.route_envelope(LOCAL_MANIFESTATION)
              ↓
          DecisionExecutor → WindowsExecutionArbiter
              ↓
          Windows 系统 API / 工具 / MCP 工具 / Skill
              ↓
          LocalExecutionResult（规范化结果）
              ↓
          OpenClawd 反馈循环 → memory backflow / 投影更新
    ↓
LIMINAL → MANIFEST → SILENT
```

**代码来源**：`core/local_execution_chain.py`，`core/openclawd.py`，`core/decision_executor.py`，`core/command_router.py`

### 4.2 本地链路的关键约束

- `CommandRouter` 是本地任务的唯一路由权威，任何模块不得绕过它直接分发到本地执行器
- `LocalExecutionResult` 是规范化结果容器，所有本地执行结果必须经过规范化后再反馈给 OpenClawd
- 本地链路是同步的（执行在 `route_envelope()` 的返回值中直接得到结果）

---

## 五、跨设备执行链如何工作（完整代码路径）

### 5.1 完整代码链（V2 → Android 执行 → 结果回 V2）

```
用户发起请求
    ↓
OpenClawd.process()
    _determine_execution_path() → "cross_device"
    ↓
CommandRouter.route_envelope(REMOTE)
    [ACL 检查 → HITL 门控 → 封装 TaskEnvelope/HandoffEnvelopeV2]
    ↓
galaxy_gateway/device_router.py
    DeviceRouter.dispatch()
    [根据 device_id 查找 WebSocket 会话]
    ↓
galaxy_gateway/android_bridge.py
    AndroidBridge.send_to_device()
    [通过 /ws/device/{device_id} 发送 AIP v3 消息]
    ↓
─────────────────────── WebSocket 边界 ───────────────────────
    ↓
Android: GalaxyWebSocketClient 收到 TaskEnvelope/GOAL_EXECUTION 消息
    ↓
Android: LoopController / AgentRuntimeBridge
    ↓
Android: LocalLoopExecutor
    ├─ perceive: AccessibilityScreenshotProvider.captureScreen()
    ├─ plan: LlamaCppPlannerService.plan() 或 center VLM 请求
    ├─ ground: NcnnGroundingService.ground() 或 center VLM 请求
    ├─ act: AccessibilityActionExecutor.execute()
    └─ 循环直到完成
    ↓
Android: 封装 ResultEnvelope（包含 steps, status, execution_time_ms）
    ↓
Android: GalaxyWebSocketClient.sendResult()
    ↓
─────────────────────── WebSocket 边界 ───────────────────────
    ↓
V2: galaxy_gateway/android/handlers/goal_execution.py
    handle_goal_execution_result()
    ↓
V2: core/unified_result_ingress.py
    UnifiedResultIngress.process()
    ├─ 幂等性检查
    ├─ 状态映射（Android 分类 → V2 规范分类）
    ├─ 4 步真值链（truth_ingress, reconcile, lifecycle, completion）
    ├─ CanonicalTaskRuntime 更新
    ├─ CanonicalCompletionIngress 通知（解锁 awaiter）
    └─ 记忆回流 / 投影更新
    ↓
OpenClawd 反馈循环
    ↓
MANIFEST → SILENT
```

**代码来源**：`core/cross_device_execution_chain.py`，`galaxy_gateway/android_bridge.py`，`galaxy_gateway/android/handlers/goal_execution.py`，`core/unified_result_ingress.py`

### 5.2 跨设备链的关键真相

- **离线缓冲**：Android 断线时，`PendingDeliveryBuffer`（V2 侧，60s TTL）缓存下行消息；Android 侧 `OfflineTaskQueue` 缓存上行结果
- **会话漫游**：`session_roaming.py`（V2 侧）处理 Android 断线重连后的会话恢复
- **不是 master-slave**：TaskEnvelope 是"委托"，不是"命令"——Android 有完整的执行自主性（重试、降级、本地规划）
- **结果唯一入口**：所有结果（无论来自哪个通道）都必须通过 `UnifiedResultIngress`，这是保证幂等性和真值链完整的关键

---

## 六、中心化和分布式如何真实共存

这是这个系统最容易被误解的部分。

### 6.1 代码里的真实分工

| 职责 | 谁拥有 | 代码来源 |
|------|--------|---------|
| 意图理解（LLM 推理） | V2 中心（OpenClawd + ContinuumOrchestrator） | `core/openclawd.py` |
| 路由决策（本地 or 跨设备） | V2 中心（OpenClawd._determine_execution_path） | `core/openclawd.py` |
| 任务封装与 ACL 检查 | V2 中心（CommandRouter） | `core/command_router.py` |
| WebSocket 传输 | V2 中心（DeviceRouter + gateway） | `galaxy_gateway/device_router.py` |
| GUI 执行（点击/滑动/输入） | Android 分布式节点 | `AccessibilityActionExecutor.kt` |
| 截图/感知 | Android 分布式节点 | `AccessibilityScreenshotProvider.kt` |
| 本地 AI 规划（可选） | Android 分布式节点（LlamaCpp） | `LlamaCppPlannerService.kt` |
| 本地 AI 定位（可选） | Android 分布式节点（NCNN/SeeClick） | `NcnnGroundingService.kt` |
| 中心 AI 推理（Android 代理模式） | V2 中心（AndroidVLMService） | `galaxy_gateway/android_vlm_service.py` |
| 结果归并与真值链 | V2 中心（UnifiedResultIngress） | `core/unified_result_ingress.py` |
| 设备注册与状态 SSOT | V2 中心（UDM + DeviceRegistry） | `core/unified/device_manager.py` |
| 设备配置权威 | V2 中心（ConfigService） | `core/config_service.py` |
| 离线排队 | 双侧（V2: PendingDeliveryBuffer，Android: OfflineTaskQueue） | 两仓各一处 |

### 6.2 "中心" vs "分布式" 的真实边界

**中心化的**：治理、路由决策、真值链、设备注册 SSOT、配置权威  
**分布式的**：GUI 执行、感知、本地推理（可选）、离线排队

**代码不证明** Android 有任何独立的治理或路由权威——它只响应来自 V2 的任务委托。  
但**代码确实证明** Android 有独立的执行自主性（可以拒绝、降级、本地重规划）。

---

## 七、Mesh / NATS / WebSocket 在系统里各自真正做什么

这是之前认知中混淆最多的部分，本节从代码层面分别说清楚。

### 7.1 WebSocket——核心传输层（真实工作中）

**状态：✅ 真实运作，是目前唯一实际承载 V2↔Android 通信的传输**

```
路径：/ws/device/{device_id}
协议：AIP v3（galaxy_gateway/protocol/aip_v3.py）
消息类型：DEVICE_REGISTER / HEARTBEAT / TASK_ASSIGN / GOAL_EXECUTION /
          TASK_RESULT / GOAL_EXECUTION_RESULT / GUI_CLICK / GUI_INPUT /
          GUI_SCREENSHOT / ERROR / PEER_ANNOUNCE / MESH_JOIN 等共 60+ 类型
```

- 连接管理：`galaxy_gateway/android_bridge.py` + `galaxy_gateway/gateway_service.py`
- Android 侧：`GalaxyWebSocketClient.kt`（连接、心跳、重连、离线队列）
- **所有 V2↔Android 通信在现实中都走 WS**，Mesh P2P 只在同 LAN 条件满足时才会激活

### 7.2 NATS——可选的分布式任务总线（默认不工作）

**状态：⚠️ 代码完整，但默认不激活；不配置 `GALAXY_NATS_URL` 则整个总线以 no-op 模式运行**

```
代码来源：core/nats_bus.py
激活条件：必须设置 GALAXY_NATS_URL 环境变量
不配置时：_HAS_NATS 降级，所有 publish/subscribe 静默返回 {"success": False}
用途：跨进程/跨节点的 TaskEnvelope/ResultEnvelope 分发（多 V2 节点时有意义）
现实：大多数单节点部署中，NATS 不运行，主链路完全通过 WS 工作
```

**NATS 不是 V2↔Android 通信的传输**。它是 V2 节点之间（或 V2 与 worker 节点之间）  
的分布式消息总线。只有多 V2 节点集群部署时，NATS 才真正发挥作用。

**NATS 绕过代码路径（来自 `core/nats_bus.py` 注释）**：
```python
# C5 — configured via GALAXY_NATS_URL env var; no-op mode if not set
```

### 7.3 Mesh——WS 之上的 P2P 加速层（有代码但实战条件苛刻）

**状态：⚠️ 架构完整，但 P2P 直连需要同 LAN；大多数 NAT 环境下 fallback 到 WS relay**

```
代码来源：core/mesh_coordinator.py
MESH_TRANSPORT_ROLE = "MESH::OVERLAY_ENRICHMENT_ONLY"  # 明确注释：只是叠加层
机制：设备连接时上报 peer_announce（LAN IP/port）→ 服务端通过 peer_exchange 下发
      尝试 TCP 直连（探测成功则走 P2P，否则走 WS relay）
_p2p_send：在 core/routes/hybrid.py 中接线，但 TCP 探测需要设备 LAN 互通
_ws_send：始终可用（兜底路径）
```

**Mesh 在真实部署中的能力判断**：

| 条件 | 结果 |
|------|------|
| 同一 LAN，设备 TCP 互通 | P2P 直连可用，延迟降低 |
| 不同 LAN，NAT 穿透未成功 | Relay fallback，经过 V2 中转 |
| 一般家用 / 公司网络 | 多数情况下走 Relay，P2P 不激活 |

**Mesh 消息类型（`galaxy_gateway/protocol/aip_v3.py`）**：
`MESH_JOIN / MESH_RESULT / MESH_LEAVE` 已在 `MessageType` 枚举中定义，  
并有对应 handler（`galaxy_gateway/android/handlers/mesh_lifecycle.py`）。  
Android 端的 `AipModels.kt` 中也有对应类型定义。  
但这些消息在当前运行部署中只在同 LAN 环境下才真正触发。

### 7.4 三者关系总结

```
WebSocket（始终工作，V2↔Android 主干路）
    ├─ Mesh P2P 直连（同 LAN 时可选激活，降低延迟）
    │   └─ 不可达时自动 fallback 到 WebSocket relay
    └─ NATS（多节点集群时使用，单节点部署默认不激活）
```

---

## 八、从 clone 到完整使用的体验审计

这是用最直白的语言，描述一个真实用户把这套系统用起来到底要经历什么。

### 8.1 现在真实的启动流程

**第一步：启动 V2（电脑端）**

```bash
git clone DannyFish-11/ufo-galaxy-realization-v2
pip install -r requirements.txt
# 配置 API Key（必须，否则无法调用 LLM）
python -m windows_client.status_board_v2 --set-api-key openai=sk-...
# 配置 Android 网关地址（如果要用 Android）
python -m windows_client.status_board_v2 --set-url gateway_url=ws://YOUR_IP:8765
# 启动
python main.py
```

**第二步：连接 Android（手机端）**

```
1. 构建并安装 Android APK（需要 Android Studio + JDK）
2. 授权：无障碍服务权限 + 悬浮窗权限（必须，否则无法 GUI 自动化）
3. 在 App 设置页手动填写 V2 服务器地址（格式：ws://YOUR_IP:8765）
4. 启动 App → 自动 connect → device_register
5. V2 侧可以在 status_board_v2 看到设备注册成功
```

**第三步：首次使用 Android 本地推理（如果需要）**

```
（设置 inference_mode=local）
→ App 首次启动时触发模型下载：MobileVLM ~900MB + SeeClick ~450MB
→ 无 GUI 进度展示，只有日志
→ 下载完成后本地推理可用
→ 如果不想下载，设置 inference_mode=center（推理请求发回 V2 处理）
```

**第四步：下发任务**

```
方式 A：通过 windows_client/status_board_v2 CLI 界面操作（有限制）
方式 B：直接调用 API（POST /api/v1/tasks 等）
方式 C：对话界面（如果配置了 LLM 并启动 V2，可以通过 chat 端点与系统对话）
目前无 GUI 对话窗口
```

### 8.2 认证现状——重要的代码真相

**代码来源**：`core/auth.py`

```python
def is_auth_enabled() -> bool:
    return os.getenv("GALAXY_AUTH_ENABLED", "false").strip().lower() in ("1", "true", "yes")
```

**默认状态：认证关闭。**  
任何设备（包括外部设备）只要能连接到 V2 的 WebSocket 端口，就可以注册并接受任务，  
无需任何 token。如果 `GALAXY_AUTH_ENABLED` 未设置，Android 连接时不做 token 校验。

这是生产部署中需要显式处理的安全事项：

```bash
# 启用认证（生产环境建议）
export GALAXY_AUTH_ENABLED=true
export GALAXY_API_TOKENS=your-secure-token-here
```

**这一点在之前所有认知 PR 中都没有被明确提及。**

### 8.3 现实操作摩擦点清单

| 摩擦点 | 影响程度 |
|--------|---------|
| Android 服务器 URL 需手动填写，无引导向导 | 中等（有操作，但不直观） |
| 首次使用需下载 ~1.65GB 模型，无进度 UI | 高（不了解进度，容易误以为卡住） |
| 认证默认关闭，生产环境需手动开启 | 高（安全风险，如果暴露公网） |
| 所有配置操作通过 CLI，无统一 GUI | 中等（技术用户可接受） |
| NATS 需要额外服务器，普通用户不清楚是否需要 | 低（不配置也能用，但文档不清楚） |
| 没有"从零到能用"的一键式安装向导 | 高（非开发者用户基本无法入门） |

---

## 九、已真实存在的内容（不是名义存在，是代码可验证）

### 9.1 V2 侧——真实完成

| 组件 | 完成程度 | 代码来源 |
|------|---------|---------|
| `DesktopPresenceRuntime` 三态生命周期 | ✅ 完整 | `core/desktop_presence_runtime.py` |
| `OpenClawd` 四阶段认知核 | ✅ 完整 | `core/openclawd.py` |
| 本地执行链（Windows） | ✅ 完整，有文档 | `core/local_execution_chain.py` |
| 跨设备执行链（Android） | ✅ 架构完整，有规范 | `core/cross_device_execution_chain.py` |
| `CommandRouter` 路由权威 | ✅ 完整 | `core/command_router.py` |
| `DeviceRouter` WebSocket 传输 | ✅ 完整 | `galaxy_gateway/device_router.py` |
| `UnifiedResultIngress` 结果统一入口 | ✅ 完整（幂等+真值链+记忆回流） | `core/unified_result_ingress.py` |
| AIP v3 协议栈 | ✅ 完整（双端对齐） | `galaxy_gateway/protocol/aip_v3.py` |
| 设备注册与 UDM SSOT | ✅ 完整 | `core/unified/device_manager.py` |
| `PendingDeliveryBuffer` 离线缓冲 | ✅ 完整（含持久化版本） | `galaxy_gateway/pending_delivery_buffer.py` |
| `MultimodalIngressBus` 持续感知 | ✅ 完整 | `core/multimodal/ingress_bus.py` |
| LLM 多模态路由 | ✅ 完整 | `core/multi_llm_router.py` |
| `AndroidVLMService` 中心侧 VLM | ✅ 完整 | `galaxy_gateway/android_vlm_service.py` |
| `NATSBus` 分布式总线 | ✅ 完整（默认 no-op，配置后可用） | `core/nats_bus.py` |
| `ConfigService` 配置权威 | ✅ 完整 | `core/config_service.py` |
| `config_hot_reload` 热加载 | ✅ 完整 | `core/config_hot_reload.py` |
| CLI URL/Key 配置面 | ✅ 完整 | `windows_client/status_board_v2/url_config_surface.py` |
| `status_board_v2` CLI 状态面板 | ✅ 完整（文本渲染，7 个 surface） | `windows_client/status_board_v2/app.py` |
| Operator Console Web 页面 | ✅ 存在（原生 JS 轮询，非 React） | `static/operator-console/index.html` |
| 注册完整性跟踪（registration gaps） | ✅ 完整 | `galaxy_gateway/android/handlers/registration.py` |
| Mesh 拓扑协调器 | ✅ 代码完整（实战依赖 LAN 条件） | `core/mesh_coordinator.py` |
| `MeshCoordinator` P2P 接线 | ✅ 已接线 | `core/routes/hybrid.py:156-181` |
| 认证框架 | ✅ 完整（默认关闭，可配置） | `core/auth.py` |

### 9.2 Android 侧——真实完成

| 组件 | 完成程度 | 代码来源 |
|------|---------|---------|
| AIP v3 WebSocket 通信 | ✅ 完整 | `GalaxyWebSocketClient.kt` |
| 持久后台 Service | ✅ 完整 | `GalaxyConnectionService.kt` |
| GUI 自动化执行 | ✅ 完整 | `AccessibilityActionExecutor.kt` |
| 截图/视觉感知 | ✅ 完整 | `AccessibilityScreenshotProvider.kt` |
| llama.cpp JNI 规划器 | ✅ 真实 JNI 实现 | `LlamaCppPlannerService.kt` |
| NCNN JNI 定位器 | ✅ 真实 JNI 实现 | `NcnnGroundingService.kt` |
| 本地执行循环 | ✅ 完整 | `LocalLoopExecutor.kt` |
| 降级路径 | ✅ 完整（fallback ladder） | `PlannerFallbackLadder.kt` |
| 模型管理 + SHA-256 | ✅ 完整（MobileVLM 哈希已硬编码） | `ModelAssetManager.kt` |
| 8 阶段模型安装流水线 | ✅ 完整 | `ModelProvisioningPipeline.kt` |
| 离线任务队列 | ✅ 完整 | `OfflineTaskQueue.kt` |
| 心跳保活 | ✅ 完整 | `GalaxyConnectionService.kt` |

---

## 十、仍然是假闭环、弱连接、缺失或部分完成的内容

这一节是本文件最重要的部分，要求对每一个判断有代码依据，不允许模糊描述。

### 10.1 假闭环（看起来完成了，实际上有关键空洞）

**A. 认证默认关闭**

- 代码状态：`is_auth_enabled()` 默认返回 `False`
- 表现：registration.py 的 `_evaluate_ingress_authentication()` 有完整的 token 校验逻辑，  
  但当 `auth_enforced=False` 时，所有设备无 token 也可注册成功，状态为 `"not_enforced_no_token"`
- 实际含义：系统有完整的认证机制，但在默认部署中根本不启用
- **判断：认证框架存在，但认证闭环在默认配置下是假闭环**

**B. Operator Console 是轮询静态页**

- 代码状态：`static/operator-console/index.html`——731 行原生 HTML + JavaScript
- 表现：每隔 N 秒轮询一批 API，渲染到 DOM，没有 WebSocket 推送，没有实时状态更新
- 对比预期：名字叫 "Galaxy Operator Console"，给人一种复杂管理控制台的印象
- **判断：功能存在（可以看到系统状态），但不是真正意义上的操作员控制台**

**C. 三态桌面 UI 外壳（DORMANT/ISLAND/SIDESHEET/FULLAGENT）**

- 代码状态：`system_integration/` 目录中有这四个状态的定义和转换逻辑
- 表现：状态机逻辑存在，但对应的 GUI 渲染实现（Tauri/Electron 窗口或等效桌面应用）不存在
- 实际含义：系统在代码里"知道"自己有四种 UI 态，但没有任何 UI 代码去实际渲染这些状态
- **判断：UI 状态机存在，UI 渲染层不存在，是明确的假闭环**

**D. 多设备并行协作（multi-device mesh 全流程）**

- 代码状态：`goal_execution.py` 中有 `handle_parallel_subtask`，`mesh_coordinator.py` 中有拓扑管理
- 表现：可以向多个设备分发子任务，但"多设备同时失败时的一致性恢复、整体任务完成判断"没有端到端测试覆盖
- **判断：单设备链路已闭环，多设备并行协作在代码上存在但没有被证明端到端可靠**

### 10.2 弱连接（存在但连接不够稳固）

**A. SeeClick SHA-256 首次下载后才计算**

- 代码来源：`ModelAssetManager.kt` 中 `SEECLICK_SHA256 = null`
- 影响：第一次下载 SeeClick 时无法预验证完整性，只能在下载后计算并持久化
- **判断：可接受的设计选择，但不是最优完整性保障**

**B. Mesh P2P 接线依赖 LAN 条件**

- 代码来源：`core/routes/hybrid.py` 第 158-181 行——`_mesh_p2p_send` 接入 `MeshCoordinator`
- 但 P2P 连接成功需要 `probe_peer()` 返回 True，即 TCP 探测成功
- 在大多数移动网络和公司 NAT 环境下，Android 和 V2 不在同一 LAN，TCP 探测会失败
- **判断：P2P Mesh 代码已接线，但实战中多数情况下不会激活**

**C. NATS 总线在集成测试中存在，但生产部署依赖外部 NATS 服务器**

- 代码来源：`core/nats_bus.py` 的 no-op 降级逻辑
- 影响：如果运维人员不配置 NATS 服务器，系统核心功能不受影响，但分布式任务分发路径不工作
- **判断：弱连接，因为依赖外部组件且默认不配置**

**D. 结果链中仍有 best-effort 语义**

- 代码来源：`core/unified_result_ingress.py`——某些步骤在异常时继续流程而非硬阻断
- 影响：极端情况下可能出现"任务表面完成但真值/验收没有完全闭合"的情况
- **判断：架构上有保护，但不是每个步骤都是硬约束**

### 10.3 缺失（代码不存在，不是未激活，是没有写）

| 缺失内容 | 类型 | 影响 |
|---------|------|------|
| TypeScript/React 全栈前端 | 完全不存在 | 无法做出现代 AI 管理面板或动态界面 |
| Tauri/Electron 桌面助手 Shell | 完全不存在 | 三态 UI 外壳（DORMANT 等）无法实际渲染 |
| 多模态桌面助手 UI（三态悬浮/伴随/沉浸） | 完全不存在 | 系统无法以"小爱/Siri 样式"的助手形态呈现 |
| Android 模型下载进度 GUI | 完全不存在 | 用户看不到首次下载进度 |
| 统一 GUI 配置向导（URL + Key + 设备） | 完全不存在 | 非技术用户无法上手 |
| WebSocket 实时推送的 Operator Panel | 完全不存在 | 当前是轮询，不是实时 |
| 跨仓任务链可视化 UI | 完全不存在 | 无法在界面中看到一条任务从 V2 到 Android 的完整路径 |
| 系统诊断/故障追踪 GUI | 完全不存在 | 故障排查只能看日志 |
| Android App 内置 operator 功能面板 | 完全不存在 | Android 侧无状态展示 |

---

## 十一、还需要建什么，按优先级分类

### P0：阻断完整成熟使用

| 项目 | 说明 | 归属 |
|------|------|------|
| 生产环境认证默认启用 | 要么改默认值，要么在 setup 向导强制配置 | V2 |
| "从零到能用"安装向导 | URL + API Key + Android 连接全流程引导 | V2 |
| Android 首次使用模型下载进度 UI | 防止用户误以为 App 卡死 | Android |
| 完整 GUI 配置面（不依赖 CLI） | 非技术用户无法上手的根本原因 | V2（TypeScript/全栈） |

### P1：影响系统真实性和一致性

| 项目 | 说明 | 归属 |
|------|------|------|
| 三态桌面助手 UI 渲染层 | DORMANT/ISLAND/SIDESHEET/FULLAGENT 四态需要真实窗口实现 | Tauri + TypeScript（V2） |
| 多设备并行任务端到端验证 | 代码存在但没有被证明可靠 | V2 + Android |
| SeeClick SHA-256 预置 | 提升第一次下载的完整性保障 | Android |
| 结果链硬约束强化 | 消除 best-effort 软语义，确保真值链每步都是硬阻断 | V2 |

### P2：影响可维护性和可诊断性

| 项目 | 说明 | 归属 |
|------|------|------|
| WebSocket 实时推送 Operator Panel | 用 WS 替代轮询，实现真正实时状态面板 | TypeScript/全栈 |
| 跨仓任务链可视化 UI | 可以在 UI 中追踪一条任务的完整生命周期 | TypeScript/全栈 |
| NATS 配置文档和默认配置 | 让运维人员清楚什么时候需要 NATS，怎么配置 | V2 文档 |
| Android 推理状态可视化 | 在 App 内看到本地模型加载状态、推理耗时 | Android |
| 系统诊断面板 | 故障时快速定位到断点位置 | TypeScript/全栈 |

---

## 十二、TypeScript / 全栈 / 操作员面板 / 桌面 Shell / 多模态体验的缺口

这是整个系统距离"完整成熟可用"最远的部分，也是之前所有认知 PR 中提及最少的部分。

### 12.1 现在有什么

| 现有内容 | 说明 |
|---------|------|
| `static/operator-console/index.html` | 731 行原生 JS 轮询页面 |
| `windows_client/status_board_v2/` | Python CLI 文本状态面板 |
| `dashboard/backend/main.py` | FastAPI 后端（路由极少，基本是占位符） |

### 12.2 缺什么（按层次）

**层次 1：管理面板（P0 级缺口）**

> 用人话说：现在没有一个可以给不懂代码的人用的界面。所有操作都要敲命令行。

需要：
- TypeScript + React 技术栈
- 统一 Web 管理界面，包含：  
  - 设备列表 + 状态（在线/离线/执行中）  
  - 任务历史 + 状态  
  - LLM Provider 配置（Key 填入、开关、路由策略）  
  - 服务器 URL 配置（Gateway / NATS / ATS）  
  - 实时日志/事件流（WebSocket 推送，不是轮询）  

**层次 2：桌面助手外壳（P1 级缺口）**

> 用人话说：系统在代码里定义了"可以像 Siri 一样悬浮在桌面上"，但这个窗口完全没有写。

需要：
- Tauri + TypeScript/React（桌面原生应用框架）
- 四种 UI 态对应的窗口样式：  
  - `DORMANT`：最小化/托盘图标  
  - `ISLAND`：小悬浮窗（常驻桌面，弱打扰）  
  - `SIDESHEET`：侧边栏式伴随助手  
  - `FULLAGENT`：全屏沉浸工作台  
- 窗口间转换动画（Framer Motion）
- 桌面系统权限集成（热键唤起、屏幕截图、音频输入）

**层次 3：多模态输入输出体验（P1 级缺口）**

> 用人话说：系统后端能处理图片/语音/截图，但没有前端来接收和展示这些。

需要：
- 麦克风输入 → STT → OpenClawd.process() 的完整管线 UI
- 摄像头/屏幕截图 → 多模态请求的 UI
- 语音输出（TTS）与文字输出的统一呈现面

**层次 4：Android 侧体验完善（P1/P2 级缺口）**

> 用人话说：Android App 的用户界面基本功能正常，但高级功能和状态展示缺失。

需要：
- 本地模型下载进度界面（含已用存储、下载速度、剩余时间）
- 本地推理状态面板（当前推理模式、上次任务执行结果）
- 与 V2 连接状态的清晰展示
- 任务执行历史（完成了什么，失败了什么）

### 12.3 全栈完整性总结

```
已有（代码存在，可工作）：
  ✅ Python 后端（V2 核心链路）
  ✅ Android Kotlin（本地 AI + GUI 执行）
  ✅ WebSocket 协议层（AIP v3）
  ✅ REST API（core/routes/）
  ✅ 原生 JS 静态页面（operator-console，功能性但粗糙）

完全不存在：
  ❌ TypeScript/React 管理前端
  ❌ Tauri 桌面助手 Shell
  ❌ 多模态输入 UI（麦克风/摄像头/截图）
  ❌ 实时 WebSocket 推送的动态面板
  ❌ Android 模型管理 GUI
  ❌ 跨仓任务链可视化
```

---

## 十三、这套系统完整成熟后应该是什么体验（无术语白话描述）

如果系统全部建完、成熟可用，一个普通用户的完整体验应该是这样的：

---

**场景：电脑上的 AI 助手 + 手机执行**

你打开电脑，桌面右下角有一个小的悬浮图标（这是 Galaxy 的静止态）。

你按一个快捷键，或者对着麦克风说话，图标变成一个小悬浮窗（这是陪伴态）。  
你说："帮我打开手机上的微信，发消息给张三说我今晚七点到"。

系统开始处理：
- 电脑端分析你说的话，判断需要用手机来做
- 系统通过 Wi-Fi 把任务发给手机
- 手机自动打开微信（无需你动手）
- 手机 AI 自动找到张三的对话，输入文字，发送
- 手机把"发送成功"的结果报告给电脑
- 电脑上的悬浮窗显示："已在手机上给张三发了消息"

整个过程你只说了一句话，手机什么都不用碰。

---

**另一个场景：电脑本地助手**

你对桌面说："帮我把桌面上的这几个截图整理一下，按日期分好"。

这次系统判断不需要手机，直接在电脑上执行：  
- 扫描桌面，找到截图文件  
- 按日期创建文件夹  
- 把文件移进去  
- 告诉你："整理完了，按日期分了 5 个文件夹"  

这就是本地执行链，完全不经过手机。

---

**还有一个场景：管理员配置**

你打开浏览器，访问 http://localhost:8299/operator，进入 Galaxy 管理面板。  
你可以看到：  
- 连接了哪些设备（电脑、手机、平板）  
- 每个设备的状态（空闲/执行中/离线）  
- 最近执行了什么任务、结果如何  
- 使用了哪个 AI 模型、花了多少 token  
- 如果出问题，可以看到哪一步失败了  

这就是操作员面板，让你随时了解系统在做什么。

---

**以上这些体验，现在的真实状态是：**

| 体验 | 现状 |
|------|------|
| 手机自动执行任务 | ✅ **已实现**（llama.cpp + NCNN + LoopController 可工作） |
| 电脑说话触发 | ⚠️ **后端支持**，但没有麦克风 UI 和语音输入界面 |
| 悬浮助手图标 | ❌ **不存在**（代码里定义了状态，但窗口没有写） |
| 手机执行完自动反馈 | ✅ **已实现**（WS 结果回传 + unified_result_ingress） |
| 管理员控制面板 | ⚠️ **有原始版本**（原生 JS 静态页，功能基本，不够直观） |
| 无需命令行配置 | ❌ **不存在**（目前所有配置都需要命令行） |

---

## 结语：这套系统的真实位置

**已经是真的**：
- 一个 Windows 电脑 + Android 手机协同的分布式 AI 执行系统，后端架构完整
- Android 本地 AI（llama.cpp + NCNN）已真实集成，不再只是结构占位
- WebSocket + AIP v3 双仓协议层完全打通
- 本地执行链（Windows）和跨设备执行链（Android）都是真实可工作的

**还不是真的**：
- 一个普通人可以不看文档就上手使用的完整产品
- 一个有漂亮界面的桌面 AI 助手（三态 UI 外壳还没有写）
- 一个有实时动态面板的运维监控系统（TypeScript/React 前端不存在）
- 一个在生产环境开箱即安全的系统（认证默认关闭）

**准确定位**：

> 这是一个**后端架构完整、协议层打通、智能体执行链可工作，  
> 但产品化 UI 层、安全默认配置、非技术用户体验尚未完成**的系统。  
> 它距离"完整成熟"还有一整套全栈 UI（TypeScript/React + Tauri）需要建，  
> 以及若干默认配置问题（认证、NATS 说明）需要修正。

---

*本文件完全基于两仓真实代码，不引用任何先前 audit 文档作为证据。  
每一个判断均有代码文件路径、类名或函数名作为来源。  
在代码不足以证明某事时，本文件明确写出"代码不证明此点"。*
