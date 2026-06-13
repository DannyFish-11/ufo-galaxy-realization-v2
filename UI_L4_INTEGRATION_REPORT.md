# UI ↔ L4 Integration Report

> 架构注记：本集成遵循统一主体架构 —— `DesktopPresenceRuntime`（运行时外壳）与
> `OpenClawd`（主体核心）是同一主体的两层；L4 主循环
> （`core/galaxy_main_loop_l4_enhanced.py`）作为后台增强层运行，
> **不在 per-request 规范链路上**。
> 见 [docs/UNIFIED_SUBJECT_ARCHITECTURE.md](docs/UNIFIED_SUBJECT_ARCHITECTURE.md)。

## 验证范围

| 项 | 结果 |
|---|---|
| 事件总线 (`integration/event_bus.py`) | UIGalaxyEvent 创建/序列化/订阅分发 ✅ |
| L4 主循环 (`core/galaxy_main_loop_l4_enhanced.py`) | 单例获取、目标入队 (`PendingGoal`)、状态查询 ✅ |
| 状态机集成 (`system_integration/state_machine_ui_integration.py`) | 三态切换与硬件触发 ✅ |
| WebSocket 服务 (`integration/websocket_server.py`) | `get_galaxy_loop()` 接入、进度事件推送 ✅ |

回归测试：`tests/test_integration.py`（事件总线 / L4 / 状态机 / 端到端目标流转）。

## 降级行为

L4 的各增强组件（感知、目标分解、规划、世界模型、技能库等）均以可选方式加载；
任一组件缺失时主循环仍可导入运行，仅记录告警并跳过对应阶段。
