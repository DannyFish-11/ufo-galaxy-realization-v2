# Galaxy UI与L4主循环集成报告

> **统一主体架构说明**: `windows_client/`、`android_client/` 等 UI 客户端是
> **桌面"衣服"呈现层**（desktop clothing），不是主体入口。
>
> UI 状态 (`DORMANT/ISLAND/SIDESHEET/FULLAGENT`) 描述**桌面衣服的展开模式**，
> 不代表主体三态生命周期 (`silent/liminal/manifest`)，也不是 Continuum 姿态。
>
> 详见 [`docs/UNIFIED_SUBJECT_ARCHITECTURE.md`](docs/UNIFIED_SUBJECT_ARCHITECTURE.md) §3。

## 概述

本报告详细描述了Galaxy系统的UI与L4主循环的完整集成实现。通过4个关键集成点的实现，打通了用户输入到系统执行的完整链路。

---

## 集成架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Galaxy 集成架构                                 │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   Windows客户端   │     │   Android客户端   │     │   硬件触发器      │
│  (PyQt6 UI)      │     │  (Kotlin/Compose)│     │  (按键/手势)     │
└────────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘
         │                        │                        │
         │  1. UI → L4            │  1. UI → L4            │  3. 硬件 → UI
         │  (命令提交)             │  (WebSocket/HTTP)      │  (唤醒/手势)
         │                        │                        │
         ▼                        ▼                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           事件总线 (EventBus)                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  EventType:                                                         │   │
│  │  - GOAL_SUBMITTED, GOAL_DECOMPOSITION_*                             │   │
│  │  - PLAN_GENERATION_*, ACTION_EXECUTION_*                            │   │
│  │  - TASK_COMPLETED, ERROR_OCCURRED                                   │   │
│  │  - HARDWARE_TRIGGER_DETECTED, STATE_TRANSITION                      │   │
│  │  - ANIMATION_STARTED, ANIMATION_COMPLETED                           │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
         │                        │                        ▲
         │                        │                        │
         │  2. L4 → UI            │                        │  4. UI → 硬件
         │  (进度回调)             │                        │  (动画完成通知)
         ▼                        │                        │
┌─────────────────────────────────────────────────────────────────────────────┐
│                      L4主循环 (GalaxyMainLoopL4Enhanced)                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  核心功能:                                                           │   │
│  │  - receive_goal(): 接收外部目标                                      │   │
│  │  - run_cycle(): 执行完整L4周期                                       │   │
│  │  - _decompose_goal(): 目标分解                                       │   │
│  │  - _create_plan(): 计划生成                                          │   │
│  │  - _execute_plan(): 计划执行                                         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
         │
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      系统状态机 (SystemStateMachine)                          │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  状态: SLEEPING → ISLAND → SIDESHEET → FULLSCREEN                   │   │
│  │  触发: wakeup(), expand_to_sidesheet(), expand_to_fullscreen()      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4个集成点详细实现

### 1. UI → L4（用户输入到系统执行）

#### Windows客户端实现
**文件**: `windows_client/windows_client_integrated.py`

```python
def _on_command_submitted(self):
    """命令提交回调（UI → L4 集成点）"""
    command = self.input_field.text().strip()
    
    # 1. 解析用户意图
    intent = self._parse_user_intent(command)
    
    # 2. 提交到L4主循环
    goal_id = self.l4_thread.submit_goal(command)
    
    # 3. 创建UI任务并更新列表
    task = UITask(task_id=goal_id, description=command, status=TaskStatus.PENDING)
    self.tasks[goal_id] = task
    self._update_tasks_list()
```

**关键代码行数**: 约150行

#### Android客户端实现
**文件**: `android_client/MainActivityIntegrated.kt`

```kotlin
fun onCommandSubmitted(command: String) {
    // 1. 解析用户意图
    val intent = parseUserIntent(command)
    
    // 2. 通过WebSocket发送
    val message = JSONObject().apply {
        put("type", "goal_submit")
        put("description", command)
        put("intent", JSONObject().apply {
            put("type", intent.intentType)
            put("confidence", intent.confidence)
        })
    }
    webSocketManager.send(message.toString())
}
```

**关键代码行数**: 约200行

#### L4主循环接收端
**文件**: `core/galaxy_main_loop_l4_enhanced.py`

```python
def receive_goal(self, goal_description: str, goal_type: Any = None, 
                 constraints: List[str] = None, 
                 success_criteria: List[str] = None,
                 priority: int = 0) -> str:
    """接收外部目标（UI → L4 入口）"""
    goal_id = str(uuid.uuid4())
    
    pending_goal = PendingGoal(
        goal_id=goal_id,
        description=goal_description,
        goal_type=goal_type,
        constraints=constraints or [],
        success_criteria=success_criteria or [],
        deadline=None,
        priority=priority
    )
    
    # 添加到队列
    asyncio.create_task(self._goal_queue.put(pending_goal))
    
    # 发布事件
    event_bus.publish_sync(
        EventType.GOAL_SUBMITTED,
        "ui",
        {"goal_id": goal_id, "description": goal_description}
    )
    
    return goal_id
```

**关键代码行数**: 约80行

---

### 2. L4 → UI（系统执行到界面更新）

#### 事件总线实现
**文件**: `integration/event_bus.py`

```python
class UIProgressCallback:
    """UI进度回调类 - 用于L4主循环向UI报告进度"""
    
    def on_goal_decomposition_started(self, goal_description: str):
        event_bus.publish_sync(
            EventType.GOAL_DECOMPOSITION_STARTED,
            "l4",
            {"goal_description": goal_description}
        )
    
    def on_goal_decomposition_completed(self, goal_description: str, subtasks: List[Dict]):
        event_bus.publish_sync(
            EventType.GOAL_DECOMPOSITION_COMPLETED,
            "l4",
            {"goal_description": goal_description, "subtasks": subtasks}
        )
    
    def on_action_execution_progress(self, action_id: str, progress: float, message: str = ""):
        event_bus.publish_sync(
            EventType.ACTION_EXECUTION_PROGRESS,
            "l4",
            {"action_id": action_id, "progress": progress, "message": message}
        )
```

**关键代码行数**: 约120行

#### L4主循环中的进度回调
**文件**: `core/galaxy_main_loop_l4_enhanced.py`

```python
async def run_cycle(self) -> L4CycleResult:
    # 2. 分解：将目标分解为子任务
    self._progress_callback.on_goal_decomposition_started(goal.description)
    subtasks = await self._decompose_goal(goal)
    self._progress_callback.on_goal_decomposition_completed(...)
    
    # 3. 规划：创建执行计划
    self._progress_callback.on_plan_generation_started(goal.description)
    plan = await self._create_plan(goal, subtasks)
    self._progress_callback.on_plan_generation_completed(...)
    
    # 4. 执行：执行计划
    for action in actions:
        self._progress_callback.on_action_execution_started(action_id, action_command)
        # ... 执行中更新进度
        self._progress_callback.on_action_execution_progress(action_id, progress, message)
        self._progress_callback.on_action_execution_completed(action_id, success, result)
```

**关键代码行数**: 约100行

#### Android客户端接收端
**文件**: `android_client/MainActivityIntegrated.kt`

```kotlin
private fun handleServerMessage(message: String) {
    val json = JSONObject(message)
    val eventType = json.optString("event_type")
    
    when (eventType) {
        "GOAL_DECOMPOSITION_COMPLETED" -> {
            val count = data?.optInt("subtask_count", 0) ?: 0
            updateStatus("目标分解完成: $count 个子任务")
            addMessage(Message(...))
        }
        "ACTION_EXECUTION_PROGRESS" -> {
            val progress = data?.optDouble("progress", 0.0) ?: 0.0
            updateProgress(progress.toFloat())
        }
        "TASK_COMPLETED" -> {
            val success = data?.optBoolean("success", false) ?: false
            updateStatus("任务完成: ${if (success) "成功" else "失败"}")
        }
    }
}
```

**关键代码行数**: 约150行

---

### 3. 硬件触发 → UI（硬件事件到界面响应）

#### 状态机实现
**文件**: `system_integration/state_machine_ui_integration.py`

```python
class SystemStateMachine:
    def wakeup(self, trigger_type: TriggerType = TriggerType.HARDWARE_BUTTON,
               trigger_source: str = "hardware") -> bool:
        """唤醒系统（硬件触发 → UI 集成点）"""
        # 发布硬件触发事件
        event_bus.publish_sync(
            EventType.HARDWARE_TRIGGER_DETECTED,
            trigger_source,
            {"trigger_type": trigger_type.value, "action": "wakeup"}
        )
        
        # 转换到灵动岛状态
        success = self.transition_to(SystemState.ISLAND, trigger_type, trigger_source)
        return success
```

**关键代码行数**: 约80行

#### 硬件触发管理器
**文件**: `system_integration/state_machine_ui_integration.py`

```python
class HardwareTriggerManager:
    def __init__(self):
        # 注册UI回调（硬件触发 → UI 集成点）
        self.state_machine.register_state_enter_callback(
            SystemState.ISLAND, self._on_island_enter
        )
        self.state_machine.register_state_enter_callback(
            SystemState.SIDESHEET, self._on_sidesheet_enter
        )
    
    def _on_island_enter(self, state: SystemState):
        """灵动岛状态进入回调"""
        event_bus.publish_sync(
            EventType.UI_STATE_CHANGED,
            "state_machine",
            {"state": state.value, "action": "play_animation", "animation_type": "island_appear"}
        )
    
    def on_hardware_button_pressed(self, button_id: str):
        """硬件按键按下处理"""
        if button_id == "power" or button_id == "assistant":
            self.state_machine.wakeup(
                trigger_type=TriggerType.HARDWARE_BUTTON,
                trigger_source=f"button_{button_id}"
            )
    
    def on_gesture_detected(self, gesture_type: str):
        """手势检测处理"""
        if gesture_type == "swipe_up":
            self.state_machine.expand_to_sidesheet()
        elif gesture_type == "swipe_down":
            self.state_machine.collapse_to_island()
```

**关键代码行数**: 约150行

---

### 4. UI状态 → 硬件触发（界面状态到系统记录）

#### 动画状态管理
**文件**: `system_integration/state_machine_ui_integration.py`

```python
def start_animation(self, animation_id: str, animation_type: str):
    """开始动画（UI状态 → 硬件触发 集成点）"""
    animation = AnimationState(
        animation_id=animation_id,
        animation_type=animation_type,
        state="started",
        started_at=datetime.now()
    )
    self._animations[animation_id] = animation
    
    event_bus.publish_sync(
        EventType.ANIMATION_STARTED,
        "ui",
        {"animation_id": animation_id, "animation_type": animation_type}
    )

def complete_animation(self, animation_id: str, success: bool = True):
    """完成动画（UI状态 → 硬件触发 集成点）"""
    if animation_id in self._animations:
        animation = self._animations[animation_id]
        animation.state = "completed" if success else "error"
        animation.completed_at = datetime.now()
        
        event_bus.publish_sync(
            EventType.ANIMATION_COMPLETED,
            "ui",
            {
                "animation_id": animation_id,
                "animation_type": animation.animation_type,
                "success": success
            }
        )
        
        # 记录转换历史
        self._record_animation_transition(animation)
```

**关键代码行数**: 约80行

---

## 代码统计

| 模块 | 文件 | 代码行数 | 功能 |
|------|------|----------|------|
| 事件总线 | `integration/event_bus.py` | 350 | 事件发布订阅系统 |
| L4主循环增强版 | `core/galaxy_main_loop_l4_enhanced.py` | 450 | 带UI回调的L4主循环 |
| Windows客户端 | `windows_client/windows_client_integrated.py` | 550 | PyQt6 UI集成 |
| Android客户端 | `android_client/MainActivityIntegrated.kt` | 600 | Kotlin UI集成 |
| 状态机集成 | `system_integration/state_machine_ui_integration.py` | 500 | 状态机和硬件触发 |
| WebSocket服务器 | `integration/websocket_server.py` | 550 | 后端通信服务 |
| 集成测试 | `tests/test_integration.py` | 450 | 完整测试套件 |
| **总计** | **7个文件** | **~3450行** | **完整集成方案** |

---

## 数据流图

### UI → L4 数据流

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  用户输入    │───▶│  意图解析    │───▶│ 创建Goal对象 │───▶│ 添加到队列   │
│  (UI组件)   │    │ (_parse_)   │    │ (PendingGoal)│    │(async.Queue)│
└─────────────┘    └─────────────┘    └─────────────┘    └──────┬──────┘
                                                                  │
┌─────────────┐    ┌─────────────┐    ┌─────────────┐            │
│  L4主循环    │◀───│  获取目标    │◀───│  发布事件    │◀───────────┘
│ (run_cycle) │    │(_perceive_) │    │(GOAL_SUBMITTED)
└─────────────┘    └─────────────┘    └─────────────┘
```

### L4 → UI 数据流

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ 目标分解开始 │───▶│ 发布事件     │───▶│ 事件总线     │───▶│ 广播给客户端 │
│(_callback_) │    │(DECOMPOSING)│    │ (EventBus)  │    │(WebSocket)  │
└─────────────┘    └─────────────┘    └─────────────┘    └──────┬──────┘
                                                                  │
┌─────────────┐    ┌─────────────┐    ┌─────────────┐            │
│  UI更新显示  │◀───│ 处理消息     │◀───│ 接收事件     │◀───────────┘
│(更新进度条)  │    │(handleMsg)  │    │(onMessage)  │
└─────────────┘    └─────────────┘    └─────────────┘
```

### 硬件触发 → UI 数据流

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ 硬件按键按下 │───▶│ 触发管理器   │───▶│ 状态机转换   │───▶│ 发布事件     │
│(on_hardware)│    │(TriggerMgr) │    │ (wakeup)    │    │(STATE_TRANS)│
└─────────────┘    └─────────────┘    └─────────────┘    └──────┬──────┘
                                                                  │
┌─────────────┐    ┌─────────────┐    ┌─────────────┐            │
│ 播放动画     │◀───│ 执行回调     │◀───│ 接收事件     │◀───────────┘
│(灵动岛出现)  │    │(_on_island_)│    │(subscribe)  │
└─────────────┘    └─────────────┘    └─────────────┘
```

### UI状态 → 硬件触发 数据流

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ 动画开始     │───▶│ 状态机记录   │───▶│ 发布事件     │───▶│ 更新统计     │
│(UI组件)     │    │(start_anim) │    │(ANIM_START) │    │(statistics) │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘

┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ 动画完成     │───▶│ 状态机记录   │───▶│ 发布事件     │───▶│ 触发回调     │
│(UI组件)     │    │(complete_)  │    │(ANIM_COMP)  │    │(callback)   │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

---

## 测试方法

### 1. 单元测试

```bash
# 运行所有集成测试
cd /mnt/okcomputer/output/galaxy_integration
python -m pytest tests/test_integration.py -v
```

### 2. 端到端测试

```bash
# 1. 启动WebSocket服务器
python integration/websocket_server.py

# 2. 启动Windows客户端
python windows_client/windows_client_integrated.py

# 3. 在Android设备上安装并启动应用
```

### 3. 手动测试场景

| 测试场景 | 操作 | 预期结果 |
|----------|------|----------|
| UI → L4 | 在输入框输入"搜索新闻"并提交 | 目标被接收，任务列表更新 |
| L4 → UI | 等待目标处理完成 | 进度条更新，显示子任务列表 |
| 硬件 → UI | 按下硬件按键 | 系统唤醒，播放灵动岛动画 |
| UI → 硬件 | 等待动画完成 | 状态机记录转换历史 |

---

## 部署说明

### 1. 安装依赖

```bash
# Python依赖
pip install PyQt6 websockets aiohttp asyncio

# Android依赖
# 在build.gradle中添加:
# implementation "org.java-websocket:Java-WebSocket:1.5.3"
# implementation 'com.squareup.okhttp3:okhttp:4.10.0'
```

### 2. 配置服务器地址

```kotlin
// Android客户端配置
private const val WS_URL = "ws://your-server:8080/ws"
private const val HTTP_URL = "http://your-server:8080/api"
```

### 3. 启动服务

```bash
# 启动WebSocket和HTTP服务器
python integration/websocket_server.py
```

---

## 总结

通过本次集成实现，Galaxy系统的UI与L4主循环已经完全打通：

1. **UI → L4**: 用户输入通过Windows/Android客户端提交到L4主循环
2. **L4 → UI**: L4执行进度通过事件总线实时推送到UI
3. **硬件 → UI**: 硬件触发通过状态机管理器通知UI播放动画
4. **UI → 硬件**: UI动画完成时通知状态机记录转换历史

整个系统现在可以实现完整的用户输入→系统执行→界面更新的闭环。

---

## Round 2 (R-4) 更新：能力注册与连接管理

### 新增系统特性

在 Round 2 (R-4) 中，Galaxy 系统进行了重大架构升级，集成了：

#### 1. 能力注册与发现系统 (OpenClaw 风格)

**核心组件**: `core/capability_manager.py`

实现了统一的能力注册、发现和调用机制：

```python
# 能力注册
await capability_manager.register_capability(
    name="http_get",
    description="HTTP GET 请求",
    node_id="08",
    node_name="Fetch",
    category="http"
)

# 能力发现
capabilities = capability_manager.discover_capabilities(category="http")

# 状态更新
await capability_manager.update_capability_status(
    "http_get", CapabilityStatus.ONLINE
)
```

**特性**:
- ✅ 节点启动时自动注册能力
- ✅ 能力按分类、状态、节点筛选
- ✅ 实时状态跟踪 (online/offline/error)
- ✅ 持久化到 `config/capabilities.json`
- ✅ 与节点注册表 (`node_registry.py`) 深度集成

#### 2. 稳定连接管理 (向日葵风格)

**核心组件**: `core/connection_manager.py`

实现了健壮的连接生命周期管理：

```python
# 注册连接
await connection_manager.register_connection(
    connection_id="node_08",
    url="http://localhost:8008",
    config=ConnectionConfig(heartbeat_interval=30.0)
)

# 建立连接（自动启动心跳）
await connection_manager.connect("node_08")

# 自动重连（指数退避）
await connection_manager.reconnect("node_08")
```

**特性**:
- ✅ 心跳/保活机制（可配置间隔）
- ✅ 断线自动检测
- ✅ 指数退避重连策略
- ✅ 连接健康状态监控
- ✅ 回调机制（连接/断开事件）
- ✅ 持久化到 `config/connection_state.json`

#### 3. 统一运行时流程

系统启动流程已完全集成能力和连接管理：

```
配置加载 → 能力注册 → 节点启动 → 连接初始化 → 健康监控
    ↓           ↓           ↓            ↓            ↓
  环境变量   能力索引   进程管理    心跳/重连    状态报告
```

**集成点**:

1. **`unified_launcher.py`**: 
   - 初始化能力和连接管理器
   - 在配置检查阶段报告能力和连接状态

2. **`system_manager.py`**:
   - 节点启动时自动注册连接
   - 从 `node_dependencies.json` 读取并注册能力

3. **`health_monitor.py`**:
   - 健康检查时同步更新能力状态
   - 状态报告包含能力和连接统计

4. **`node_registry.py`**:
   - 节点注册时自动注册能力
   - 健康检查时更新能力状态

#### 4. 可观测性和验证

**验证工具**:

```bash
# 验证能力注册系统
python scripts/verify_capability_registry.py
# 输出: 能力管理器、连接管理器、系统集成验证

# 运行集成测试
python tests/test_capability_integration.py
# 输出: 9个测试用例全部通过
```

**状态查询**:

```python
# 能力统计
cap_stats = capability_manager.get_stats()
# {
#   "total_capabilities": 50,
#   "online": 45,
#   "offline": 5,
#   "categories": {"http": 10, "database": 15, ...}
# }

# 连接统计
conn_stats = connection_manager.get_stats()
# {
#   "total_connections": 102,
#   "connected": 98,
#   "disconnected": 2,
#   "error": 2
# }

# 健康报告（包含能力和连接）
health_report = health_monitor.get_summary()
# {
#   "total_nodes": 102,
#   "healthy_nodes": 98,
#   "capabilities": {...},
#   "connections": {...}
# }
```

#### 5. 配置文件

系统运行后生成两个关键配置文件：

**`config/capabilities.json`**:
```json
{
  "version": "1.0.0",
  "timestamp": "2026-02-11T08:00:00",
  "capabilities": [
    {
      "name": "http_get",
      "description": "HTTP GET 请求",
      "node_id": "08",
      "node_name": "Fetch",
      "category": "http",
      "status": "online",
      "last_updated": "2026-02-11T08:00:30"
    }
  ]
}
```

**`config/connection_state.json`**:
```json
{
  "timestamp": "2026-02-11T08:00:00",
  "connections": [
    {
      "connection_id": "node_08",
      "url": "http://localhost:8008",
      "state": "connected",
      "connected_at": "2026-02-11T08:00:05",
      "last_heartbeat": "2026-02-11T08:00:30",
      "total_reconnects": 0
    }
  ]
}
```

### 架构影响

R-4 更新后的系统架构：

```
┌─────────────────────────────────────────────────────────────┐
│                    统一启动器 (unified_launcher)              │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐ │
│  │ 配置管理       │  │ 能力管理器     │  │ 连接管理器     │ │
│  └────────────────┘  └────────────────┘  └────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    系统管理器 (system_manager)               │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 节点启动 → 能力注册 → 连接初始化 → 心跳启动          │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    节点注册表 (node_registry)                │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐ │
│  │ 节点注册       │  │ 能力索引       │  │ 健康检查       │ │
│  └────────────────┘  └────────────────┘  └────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    健康监控 (health_monitor)                 │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 节点健康 + 能力状态 + 连接状态 → 统一报告            │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 优势总结

通过 R-4 更新，Galaxy 系统获得了：

1. **完整的能力抽象层**: 不再直接依赖节点ID，通过能力名称调用
2. **健壮的通信层**: 自动重连和心跳，确保系统稳定性
3. **统一的监控视图**: 节点、能力、连接状态一目了然
4. **可扩展性**: 新节点只需注册能力，即可被系统发现和使用
5. **可观测性**: 完整的状态跟踪和日志记录

---

**Galaxy 现在是一个完整的系统群型架构，具备 L4 级自主性和企业级可靠性！** 🚀
