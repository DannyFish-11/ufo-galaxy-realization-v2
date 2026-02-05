# UFO Galaxy UI-L4 集成方案

## 项目概述

本项目实现了UFO Galaxy系统的UI与L4主循环的完整集成，打通了用户输入到系统执行的完整链路。

## 目录结构

```
ufo_galaxy_integration/
├── core/
│   └── galaxy_main_loop_l4_enhanced.py  # 增强版L4主循环（带UI回调）
├── integration/
│   ├── __init__.py                       # 集成模块初始化
│   ├── event_bus.py                      # 事件总线系统
│   └── websocket_server.py               # WebSocket/HTTP服务器
├── windows_client/
│   └── windows_client_integrated.py      # Windows客户端（PyQt6）
├── android_client/
│   └── MainActivityIntegrated.kt         # Android客户端（Kotlin）
├── system_integration/
│   └── state_machine_ui_integration.py   # 状态机与UI集成
├── tests/
│   └── test_integration.py               # 集成测试套件
├── README.md                             # 本文件
└── UI_L4_INTEGRATION_REPORT.md           # 详细集成报告
```

## 快速开始

### 1. 安装依赖

```bash
# Python依赖
pip install PyQt6 websockets aiohttp asyncio

# 如果使用原始L4组件，还需要:
pip install -r /path/to/ufo-galaxy-realization/requirements.txt
```

### 2. 启动服务器

```bash
# 启动WebSocket和HTTP服务器
python integration/websocket_server.py

# 服务器将在以下地址运行:
# WebSocket: ws://0.0.0.0:8080
# HTTP: http://0.0.0.0:8081
```

### 3. 启动Windows客户端

```bash
# 启动Windows客户端
python windows_client/windows_client_integrated.py
```

### 4. 部署Android客户端

1. 将 `android_client/MainActivityIntegrated.kt` 复制到Android项目的 `app/src/main/java/com/ufo/galaxy/` 目录
2. 在 `build.gradle` 中添加依赖:
   ```gradle
   implementation "org.java-websocket:Java-WebSocket:1.5.3"
   implementation 'com.squareup.okhttp3:okhttp:4.10.0'
   ```
3. 修改服务器地址:
   ```kotlin
   private const val WS_URL = "ws://your-server-ip:8080/ws"
   private const val HTTP_URL = "http://your-server-ip:8080/api"
   ```
4. 构建并安装APK

## 4个集成点

### 1. UI → L4（用户输入到系统执行）

**Windows客户端**:
```python
# 在 _on_command_submitted 回调中
goal_id = self.l4_thread.submit_goal(command)
```

**Android客户端**:
```kotlin
// 通过WebSocket发送
webSocketManager.send(message.toString())
```

**L4主循环接收**:
```python
def receive_goal(self, goal_description: str, ...) -> str:
    # 添加到队列并发布事件
    asyncio.create_task(self._goal_queue.put(pending_goal))
    event_bus.publish_sync(EventType.GOAL_SUBMITTED, ...)
```

### 2. L4 → UI（系统执行到界面更新）

**L4主循环回调**:
```python
self._progress_callback.on_goal_decomposition_started(goal.description)
self._progress_callback.on_action_execution_progress(action_id, progress, message)
```

**事件总线广播**:
```python
event_bus.publish_sync(EventType.GOAL_DECOMPOSITION_COMPLETED, ...)
```

**Android客户端接收**:
```kotlin
private fun handleServerMessage(message: String) {
    when (eventType) {
        "GOAL_DECOMPOSITION_COMPLETED" -> { ... }
        "ACTION_EXECUTION_PROGRESS" -> { updateProgress(progress) }
    }
}
```

### 3. 硬件触发 → UI（硬件事件到界面响应）

```python
# 硬件按键检测
hardware_trigger_manager.on_hardware_button_pressed("assistant")

# 状态机转换
state_machine.wakeup(trigger_type=TriggerType.HARDWARE_BUTTON)

# UI回调执行
_on_island_enter() -> 播放灵动岛动画
```

### 4. UI状态 → 硬件触发（界面状态到系统记录）

```python
# 动画开始
state_machine.start_animation(animation_id, animation_type)

# 动画完成
state_machine.complete_animation(animation_id, success=True)

# 记录转换历史
_record_animation_transition(animation)
```

## 事件类型

| 事件类型 | 来源 | 描述 |
|----------|------|------|
| GOAL_SUBMITTED | UI | 目标已提交 |
| GOAL_DECOMPOSITION_STARTED | L4 | 目标分解开始 |
| GOAL_DECOMPOSITION_COMPLETED | L4 | 目标分解完成 |
| PLAN_GENERATION_STARTED | L4 | 计划生成开始 |
| PLAN_GENERATION_COMPLETED | L4 | 计划生成完成 |
| ACTION_EXECUTION_STARTED | L4 | 动作执行开始 |
| ACTION_EXECUTION_PROGRESS | L4 | 动作执行进度 |
| ACTION_EXECUTION_COMPLETED | L4 | 动作执行完成 |
| TASK_COMPLETED | L4 | 任务完成 |
| ERROR_OCCURRED | L4 | 错误发生 |
| HARDWARE_TRIGGER_DETECTED | Hardware | 硬件触发检测 |
| STATE_TRANSITION | StateMachine | 状态转换 |
| WAKEUP_SIGNAL | StateMachine | 唤醒信号 |
| ANIMATION_STARTED | UI | 动画开始 |
| ANIMATION_COMPLETED | UI | 动画完成 |

## 测试

```bash
# 运行所有集成测试
python tests/test_integration.py

# 运行特定测试
python -m pytest tests/test_integration.py::TestL4Integration -v
```

## API文档

### WebSocket API

#### 客户端发送

```json
{
  "type": "goal_submit",
  "description": "搜索关于AI的新闻",
  "intent": {
    "type": "search",
    "confidence": 0.8
  }
}
```

#### 服务器推送

```json
{
  "event_type": "GOAL_DECOMPOSITION_COMPLETED",
  "data": {
    "goal_description": "搜索关于AI的新闻",
    "subtasks": [...],
    "subtask_count": 3
  },
  "timestamp": "2024-01-01T00:00:00"
}
```

### HTTP API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/goals` | POST | 提交目标 |
| `/api/status` | GET | 获取系统状态 |
| `/api/tasks` | GET | 获取任务历史 |
| `/api/events` | GET | 获取事件历史 |

## 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         UI 层                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │Windows客户端 │  │Android客户端 │  │  硬件触发器   │          │
│  │  (PyQt6)     │  │  (Kotlin)    │  │(按键/手势)   │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
└─────────┼─────────────────┼─────────────────┼──────────────────┘
          │                 │                 │
          │  WebSocket/HTTP │                 │
          ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      通信层 (WebSocket/HTTP)                      │
│                    GalaxyWebSocketServer                          │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                      事件总线 (EventBus)                          │
│              发布-订阅模式，支持同步/异步回调                      │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    L4主循环 (GalaxyMainLoopL4)                    │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌────────────┐ │
│  │ 目标分解    │ │ 计划生成    │ │ 动作执行    │ │ 学习反思   │ │
│  │(Decomposer)│ │ (Planner)  │ │ (Executor) │ │ (Learner)  │ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └────────────┘ │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    状态机 (SystemStateMachine)                    │
│         SLEEPING → ISLAND → SIDESHEET → FULLSCREEN              │
└─────────────────────────────────────────────────────────────────┘
```

## 贡献

欢迎提交Issue和Pull Request！

## 许可证

MIT License
