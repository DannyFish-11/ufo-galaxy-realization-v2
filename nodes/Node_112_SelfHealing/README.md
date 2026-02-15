# Node_112_SelfHealing - 节点自愈引擎

## 📋 概述

Node_112_SelfHealing 是 UFO³ Galaxy 系统的节点自愈引擎，提供异常检测、自动诊断和自动修复功能。

### 核心功能

1. **异常检测** - 实时监控节点健康（集成 Node_67 HealthMonitor）
2. **自动诊断** - 分析故障原因（调用 Node_65 LoggerCentral）
3. **自动修复** - 重启、降级、切换备用节点（通过 Node_02 Tasker）
4. **故障预测** - 预测潜在故障（集成 Node_73 Learning）

---

## 🚀 快速开始

### 1. 安装依赖

```bash
cd nodes/Node_112_SelfHealing
pip install -r requirements.txt
```

### 2. 启动服务

```bash
python server.py --port 8112
```

### 3. 测试 API

```bash
# 获取系统健康状态
curl http://localhost:8112/api/v1/health/status

# 诊断节点
curl http://localhost:8112/api/v1/diagnose/Node_01_OneAPI

# 修复节点
curl -X POST "http://localhost:8112/api/v1/heal" \
  -H "Content-Type: application/json" \
  -d '{"node_id": "Node_01_OneAPI"}'
```

---

## 📡 API 文档

### 1. 获取系统健康状态

**端点**: `GET /api/v1/health/status`

**响应**:
```json
{
  "success": true,
  "total_nodes": 93,
  "status_counts": {
    "healthy": 85,
    "degraded": 5,
    "unhealthy": 2,
    "down": 1,
    "recovering": 0
  },
  "nodes": {
    "Node_01_OneAPI": {
      "status": "healthy",
      "health_score": 0.95,
      "failure_count": 0,
      "last_check": "2026-01-24T12:00:00"
    }
  }
}
```

---

### 2. 诊断节点故障

**端点**: `GET /api/v1/diagnose/{node_id}`

**响应**:
```json
{
  "success": true,
  "node_id": "Node_01_OneAPI",
  "status": "unhealthy",
  "health_score": 0.3,
  "root_cause": "memory_exhaustion",
  "error_patterns": [...],
  "recommended_actions": ["restart", "clear_cache"],
  "diagnosed_at": "2026-01-24T12:00:00"
}
```

---

### 3. 修复节点

**端点**: `POST /api/v1/heal`

**请求体**:
```json
{
  "node_id": "Node_01_OneAPI",
  "action": "restart"
}
```

**响应**:
```json
{
  "success": true,
  "node_id": "Node_01_OneAPI",
  "action": "restart",
  "result": {
    "success": true,
    "message": "Node Node_01_OneAPI restarted"
  },
  "recovery_attempts": 1
}
```

---

### 4. 预测潜在故障

**端点**: `GET /api/v1/predict/failures`

**响应**:
```json
{
  "success": true,
  "predictions": [
    {
      "node_id": "Node_20_Qdrant",
      "failure_probability": 0.75,
      "predicted_time": "2026-01-24T18:00:00",
      "reason": "memory_trend_increasing"
    }
  ],
  "predicted_at": "2026-01-24T12:00:00"
}
```

---

## 🔗 依赖节点

| 节点 | 用途 | 端口 |
| :--- | :--- | :---: |
| **Node_02_Tasker** | 执行修复动作 | 8002 |
| **Node_65_LoggerCentral** | 日志分析 | 8065 |
| **Node_67_HealthMonitor** | 健康监控 | 8067 |
| **Node_73_Learning** | 故障预测 | 8073 |

---

## 📊 工作流程

```
监控健康状态
    ↓
[检测异常] → Node_67
    ↓
[诊断故障] → Node_65
    ↓
[选择修复动作]
    ↓
[执行修复] → Node_02
    ↓
[验证恢复]
```

---

## 🎯 预期效果

| 指标 | 提升幅度 |
| :--- | :---: |
| **系统可用性** | +25% |
| **手动干预** | -80% |
| **故障恢复时间** | -60% |

---

## 📝 配置

编辑 `server.py` 中的 `healing_config`：

```python
healing_config = {
    "node_02_url": "http://localhost:8002",
    "node_65_url": "http://localhost:8065",
    "node_67_url": "http://localhost:8067",
    "node_73_url": "http://localhost:8073"
}
```

---

**版本**: 1.0.0  
**最后更新**: 2026-01-24
