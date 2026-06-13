# UI ↔ L4 Integration — 使用说明

> 架构定位：L4 增强主循环是后台增强层，统一主体
> （DesktopPresenceRuntime 外壳 + OpenClawd 核心）的 per-request 主链不经过它。
> 详见 [docs/UNIFIED_SUBJECT_ARCHITECTURE.md](docs/UNIFIED_SUBJECT_ARCHITECTURE.md)
> 与 [UI_L4_INTEGRATION_REPORT.md](UI_L4_INTEGRATION_REPORT.md)。

## 集成点

| 方向 | 机制 |
|---|---|
| UI → L4 | `GalaxyMainLoopL4.receive_goal()` 接收外部目标并入队 |
| L4 → UI | 通过 `integration.event_bus` 发布进度事件（`UIGalaxyEvent`） |
| 服务端 | `integration/websocket_server.py` 经 `get_galaxy_loop()` 获取单例并调用 `start()/stop()/get_status()/get_task_history()` |

## 快速使用

```python
from core.galaxy_main_loop_l4_enhanced import get_galaxy_loop

loop = get_galaxy_loop()
await loop.start()
goal_id = loop.receive_goal("整理今天的截图")
print(loop.get_status())
```

事件流转：`GOAL_SUBMITTED → GOAL_DECOMPOSED → PLAN_CREATED → EXECUTION_* → GOAL_COMPLETED/FAILED`，
UI 侧通过 `integration.event_bus.event_bus.subscribe(...)` 订阅。
