# UFO Galaxy Bridge - 零破坏性桥接模块

## 设计理念

**核心原则：绝对不修改现有代码，只添加新的"外骨骼"模块。**

这个桥接器作为独立的增强层，实现 `ufo-galaxy` 与微软 UFO 之间的双向互调，确保两个系统可以无缝协同工作。

---

## 架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                     您的 Windows PC                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌───────────────────┐         ┌───────────────────┐            │
│  │ 微软 UFO          │         │ ufo-galaxy        │            │
│  │ (localhost:9000)  │         │ (localhost:8000)  │            │
│  │                   │         │                   │            │
│  │ • galaxy/         │         │ • nodes/          │            │
│  │ • ufo/            │         │ • galaxy_gateway/ │            │
│  └─────────┬─────────┘         └─────────┬─────────┘            │
│            │                             │                      │
│            │    ┌─────────────────────┐  │                      │
│            └────│ UFO Galaxy Bridge   │──┘                      │
│                 │ (零破坏性外骨骼)    │                         │
│                 │                     │                         │
│                 │ • 自动检测系统      │                         │
│                 │ • 双向互调          │                         │
│                 │ • 统一 API          │                         │
│                 └─────────────────────┘                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 功能特性

| 功能 | 描述 |
| :--- | :--- |
| **零破坏性** | 不修改任何现有代码，作为独立模块运行 |
| **自动检测** | 自动检测两个系统的可用性并建立连接 |
| **双向互调** | 支持从任一系统调用另一系统的功能 |
| **统一 API** | 提供统一的接口，屏蔽底层差异 |
| **智能回退** | 当一个系统不可用时，自动切换到另一个 |

---

## 快速开始

### 1. 启动两个系统

**启动 ufo-galaxy**：
```bash
cd E:\ufo-galaxy\galaxy_gateway
python gateway_service_v3.py
```

**启动微软 UFO**（如果您有）：
```bash
cd E:\UFO
python -m galaxy
```

### 2. 运行桥接器

```bash
cd E:\ufo-galaxy\enhancements\bridges
python ufo_galaxy_bridge.py
```

### 3. 使用示例

```python
from ufo_galaxy_bridge import UFOGalaxyBridge

# 初始化桥接器
bridge = UFOGalaxyBridge()
await bridge.initialize()

# 调用 ufo-galaxy 的视觉节点
result = await bridge.call_ufo_galaxy(
    node_id=90,
    action="analyze_screen",
    params={"query": "这个屏幕上显示的是什么？"}
)

# 使用统一的视觉分析接口（自动选择最佳系统）
result = await bridge.unified_vision_analysis(
    image_path="/path/to/screenshot.png",
    query="总结这个页面的主要内容"
)
```

---

## API 参考

### `UFOGalaxyBridge`

#### `initialize()`
初始化桥接器，自动检测两个系统的可用性。

#### `call_ufo_galaxy(node_id, action, params)`
调用 ufo-galaxy 的指定节点。

**参数**：
- `node_id` (int): 节点 ID，如 `90` 表示 Node_90_MultimodalVision
- `action` (str): 动作名称，如 `"analyze_screen"`
- `params` (dict): 参数字典

**返回**：
- `dict`: 执行结果

#### `call_microsoft_ufo(agent_name, task, params)`
调用微软 UFO 的指定 Agent。

**参数**：
- `agent_name` (str): Agent 名称，如 `"app_agent"`
- `task` (str): 任务描述
- `params` (dict): 参数字典

**返回**：
- `dict`: 执行结果

#### `unified_vision_analysis(image_path, query)`
统一的视觉分析接口，自动选择最佳系统。

**参数**：
- `image_path` (str): 图片路径
- `query` (str): 分析问题

**返回**：
- `dict`: 分析结果

---

## 部署建议

1. **单独运行**：将桥接器作为独立服务运行，监听一个新的端口（如 8888）。
2. **按需启动**：只在需要跨系统调用时启动桥接器。
3. **日志监控**：桥接器会输出详细的日志，方便排查问题。

---

## 常见问题

**Q: 如果只有一个系统可用怎么办？**
A: 桥接器会自动检测，只调用可用的系统。

**Q: 两个系统都不可用怎么办？**
A: 桥接器会以离线模式运行，返回错误信息。

**Q: 如何扩展桥接器？**
A: 在 `ufo_galaxy_bridge.py` 中添加新的方法即可，无需修改任何现有代码。

---

**作者**: Manus AI
**日期**: 2026-01-22
**版本**: 1.0
