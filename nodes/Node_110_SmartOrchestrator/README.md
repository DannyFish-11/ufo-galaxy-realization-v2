# Node_110_SmartOrchestrator - 智能任务编排引擎

## 📋 概述

Node_110_SmartOrchestrator 是 UFO³ Galaxy 系统的智能任务编排引擎，能够自动分析、匹配、编排和执行复杂任务。

### 核心功能

1. **任务理解** - 调用 Node_01 (OneAPI) 理解自然语言任务
2. **能力匹配** - 查询 Node_67 (HealthMonitor) 和 Node_103 (KnowledgeGraph) 匹配最适合的节点
3. **动态编排** - 根据节点健康状态动态调整执行计划
4. **执行监控** - 通过 Node_02 (Tasker) 执行并监控任务
5. **知识积累** - 存储编排知识到 Node_103，持续优化

---

## 🚀 快速开始

### 1. 安装依赖

```bash
cd nodes/Node_110_SmartOrchestrator
pip install -r requirements.txt
```

### 2. 启动服务

```bash
python server.py --port 8110
```

### 3. 测试 API

```bash
curl -X POST "http://localhost:8110/api/v1/orchestrate" \
  -H "Content-Type: application/json" \
  -d '{
    "task_description": "帮我搜索最新的 AI 新闻，然后总结成一份报告"
  }'
```

---

## 📡 API 文档

### 1. 编排任务

**端点**: `POST /api/v1/orchestrate`

**请求体**:
```json
{
  "task_description": "任务描述（自然语言）",
  "user_context": {
    "user_id": "user123",
    "preferences": {}
  }
}
```

**响应**:
```json
{
  "task_id": "task_20260124123456789",
  "status": "completed",
  "execution_plan": {
    "steps": [
      {
        "step_id": 1,
        "description": "搜索 AI 新闻",
        "assigned_node": "Node_22_BraveSearch",
        "priority": 1,
        "status": "completed"
      },
      {
        "step_id": 2,
        "description": "总结报告",
        "assigned_node": "Node_01_OneAPI",
        "priority": 2,
        "status": "completed"
      }
    ],
    "total_steps": 2
  },
  "result": {
    "success": true,
    "task_id": "task_20260124123456789",
    "steps_completed": 2,
    "result": {...}
  }
}
```

---

### 2. 查询任务状态

**端点**: `GET /api/v1/orchestrate/{task_id}`

**响应**:
```json
{
  "task_id": "task_20260124123456789",
  "status": "completed",
  "created_at": "2026-01-24T12:34:56",
  "result": {...}
}
```

---

### 3. 优化执行计划

**端点**: `POST /api/v1/orchestrate/{task_id}/optimize`

**响应**:
```json
{
  "task_id": "task_20260124123456789",
  "optimized": true,
  "steps": [...]
}
```

---

### 4. 获取系统能力

**端点**: `GET /api/v1/capabilities`

**响应**:
```json
{
  "total_nodes": 93,
  "healthy_nodes": 85,
  "capabilities": [
    "search",
    "llm",
    "database",
    "device_control",
    ...
  ],
  "stats": {
    "total_tasks": 150,
    "completed_tasks": 142,
    "failed_tasks": 8,
    "avg_execution_time": 3.5,
    "optimization_count": 25
  }
}
```

---

## 🔗 依赖节点

| 节点 | 用途 | 端口 |
| :--- | :--- | :---: |
| **Node_01_OneAPI** | LLM 调用（任务分析） | 8001 |
| **Node_02_Tasker** | 任务执行 | 8002 |
| **Node_67_HealthMonitor** | 节点健康监控 | 8067 |
| **Node_103_KnowledgeGraph** | 知识存储 | 8103 |

---

## 📊 工作流程

```
用户请求
    ↓
[任务理解] → Node_01 (OneAPI)
    ↓
[能力匹配] → Node_67 (HealthMonitor) + Node_103 (KnowledgeGraph)
    ↓
[生成执行计划]
    ↓
[执行任务] → Node_02 (Tasker)
    ↓
[存储知识] → Node_103 (KnowledgeGraph)
    ↓
返回结果
```

---

## 🎯 预期效果

| 指标 | 提升幅度 |
| :--- | :---: |
| **任务执行时间** | -40% ~ -60% |
| **节点利用率** | +30% |
| **任务理解准确度** | +50% |

---

## 🧪 测试

### 单元测试

```bash
pytest tests/test_node_110.py
```

### 集成测试

```bash
python -m pytest tests/integration/test_orchestration.py
```

---

## 📝 配置

编辑 `server.py` 中的 `orchestrator_config`：

```python
orchestrator_config = {
    "node_01_url": "http://localhost:8001",  # Node_01 地址
    "node_02_url": "http://localhost:8002",  # Node_02 地址
    "node_67_url": "http://localhost:8067",  # Node_67 地址
    "node_103_url": "http://localhost:8103"  # Node_103 地址
}
```

---

## 🔧 故障排除

### 问题：Node_01 连接失败

**解决方案**：
1. 确保 Node_01 已启动：`curl http://localhost:8001/health`
2. 检查防火墙设置
3. 查看日志：`tail -f logs/node_110.log`

### 问题：任务执行超时

**解决方案**：
1. 增加超时时间：修改 `server.py` 中的 `timeout` 参数
2. 检查 Node_02 的负载情况
3. 优化执行计划：调用 `/api/v1/orchestrate/{task_id}/optimize`

---

## 📄 许可证

MIT License

---

## 👥 贡献者

- Manus AI - 初始开发
- UFO³ Galaxy Team - 系统集成

---

**版本**: 1.0.0  
**最后更新**: 2026-01-24
