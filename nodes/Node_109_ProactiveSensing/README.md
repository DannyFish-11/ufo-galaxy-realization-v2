## Node_109_ProactiveSensing - 主动感知节点

**让系统能够主动发现环境变化、潜在问题和优化机会，而不是被动等待指令。**

---

## 核心功能

### 1. 环境状态监控 (Environment Monitoring)
- 注册和执行自定义监控器
- 实时收集系统指标
- 记录状态历史

### 2. 异常模式识别 (Anomaly Detection)
- 性能异常（响应时间过长）
- 错误异常（错误率过高）
- 模式异常（与历史模式偏离）
- 资源异常（CPU/内存使用率过高）

### 3. 机会发现 (Opportunity Discovery)
- 优化机会（基于异常历史）
- 集成机会（新工具、新服务）
- 学习机会（模式学习）
- 自动化机会（重复任务）

### 4. 主动预警 (Proactive Alerting)
- 三级预警（INFO / WARNING / CRITICAL）
- 自动从异常生成预警
- 预警确认机制

---

## API 端点

### 1. 扫描环境

**POST** `/api/v1/scan_environment`

**响应**:
```json
{
  "timestamp": 1737700000.0,
  "metrics": {
    "system_monitor": {
      "cpu_usage": 45.2,
      "memory_usage": 62.8
    },
    "response_time": 1200
  },
  "events": [],
  "context": {}
}
```

---

### 2. 检测异常

**POST** `/api/v1/detect_anomalies`

```json
{
  "current_state": null
}
```

**响应**:
```json
[
  {
    "anomaly_id": "anomaly_1737700000000",
    "type": "performance",
    "title": "响应时间过长",
    "description": "响应时间 6500ms 超过阈值 5000ms",
    "severity": 0.65,
    "timestamp": 1737700000.0,
    "metadata": {
      "response_time": 6500
    }
  }
]
```

---

### 3. 发现机会

**POST** `/api/v1/discover_opportunities`

```json
{
  "context": {
    "tools": ["OpenCode", "Antigravity"],
    "integration": true
  }
}
```

**响应**:
```json
[
  {
    "opportunity_id": "opp_1737700000000",
    "type": "integration",
    "title": "集成新工具",
    "description": "检测到可能的工具集成需求",
    "potential_value": 0.8,
    "effort_required": 0.6,
    "priority_score": 1.33,
    "timestamp": 1737700000.0,
    "metadata": {
      "tools": ["OpenCode", "Antigravity"]
    }
  }
]
```

---

### 4. 创建预警

**POST** `/api/v1/create_alert`

```json
{
  "level": "warning",
  "title": "系统负载过高",
  "description": "CPU 使用率持续超过 80%",
  "source": "system_monitor",
  "metadata": {
    "cpu_usage": 85.3
  }
}
```

**响应**:
```json
{
  "alert_id": "alert_1737700000000",
  "level": "warning",
  "title": "系统负载过高",
  "description": "CPU 使用率持续超过 80%",
  "source": "system_monitor",
  "timestamp": 1737700000.0,
  "metadata": {
    "cpu_usage": 85.3
  },
  "acknowledged": false
}
```

---

### 5. 确认预警

**POST** `/api/v1/acknowledge_alert`

```json
{
  "alert_id": "alert_1737700000000"
}
```

**响应**:
```json
{
  "success": true
}
```

---

### 6. 获取预警列表

**GET** `/api/v1/alerts?active_only=true`

**响应**:
```json
[
  {
    "alert_id": "alert_1737700000000",
    "level": "warning",
    "title": "系统负载过高",
    "description": "CPU 使用率持续超过 80%",
    "source": "system_monitor",
    "timestamp": 1737700000.0,
    "metadata": {},
    "acknowledged": false
  }
]
```

---

### 7. 获取机会列表

**GET** `/api/v1/opportunities?limit=10`

**响应**: 按优先级排序的机会列表

---

### 8. 获取异常列表

**GET** `/api/v1/anomalies?limit=10`

**响应**: 按时间排序的异常列表

---

### 9. 注册监控器

**POST** `/api/v1/register_monitor`

```json
{
  "name": "custom_monitor",
  "endpoint": "http://localhost:8000/metrics"
}
```

**响应**:
```json
{
  "status": "registered",
  "monitor_name": "custom_monitor"
}
```

---

## 使用示例

### Python 客户端

```python
import requests

NODE_URL = "http://localhost:9101"

# 1. 扫描环境
response = requests.post(f"{NODE_URL}/api/v1/scan_environment")
state = response.json()
print(f"Environment State: {state}")

# 2. 检测异常
response = requests.post(f"{NODE_URL}/api/v1/detect_anomalies", json={
    "current_state": None
})
anomalies = response.json()
print(f"Detected {len(anomalies)} anomalies")

# 3. 发现机会
response = requests.post(f"{NODE_URL}/api/v1/discover_opportunities", json={
    "context": {
        "tools": ["OpenCode"],
        "integration": True
    }
})
opportunities = response.json()
for opp in opportunities:
    print(f"Opportunity: {opp['title']} (Priority: {opp['priority_score']:.2f})")

# 4. 创建预警
response = requests.post(f"{NODE_URL}/api/v1/create_alert", json={
    "level": "warning",
    "title": "新工具集成需求",
    "description": "用户询问 OpenCode 集成",
    "source": "user_query_analyzer",
    "metadata": {"tool": "OpenCode"}
})
alert = response.json()
print(f"Alert Created: {alert['alert_id']}")

# 5. 获取活跃预警
response = requests.get(f"{NODE_URL}/api/v1/alerts?active_only=true")
active_alerts = response.json()
print(f"Active Alerts: {len(active_alerts)}")

# 6. 确认预警
if active_alerts:
    alert_id = active_alerts[0]['alert_id']
    response = requests.post(f"{NODE_URL}/api/v1/acknowledge_alert", json={
        "alert_id": alert_id
    })
    print(f"Alert Acknowledged: {response.json()}")
```

---

## 与其他节点的协同

### 依赖节点

| 节点 | 用途 |
| :--- | :--- |
| `Node_22_BraveSearch` | 搜索外部信息，发现新机会 |
| `Node_25_GoogleSearch` | 搜索外部信息，发现新机会 |
| `Node_108_MetaCognition` | 使用元认知能力评估感知结果 |

### 被依赖节点

| 节点 | 用途 |
| :--- | :--- |
| `Node_115_NodeFactory` | 主动感知到需要新节点时触发创建 |
| 所有节点 | 为所有节点提供主动监控和预警 |

---

## 配置

### 环境变量

```bash
NODE_109_PORT=9101
NODE_HOST=0.0.0.0
BRAVE_API_KEY=...  # 用于搜索
```

### 引擎配置

```python
engine.config = {
    "scan_interval": 60,  # 扫描间隔（秒）
    "history_window": 3600,  # 历史窗口（秒）
    "anomaly_threshold": 0.7,  # 异常阈值
    "opportunity_threshold": 0.6  # 机会阈值
}
```

---

## 启动节点

```bash
cd /path/to/ufo-galaxy-enhanced-nodes/nodes/node_109_proactive_sensing
python server.py
```

访问 API 文档: http://localhost:9101/docs

---

## 测试

```bash
cd /path/to/ufo-galaxy-enhanced-nodes
python -m pytest tests/test_node_109.py -v
```

---

## 智能化水平

**L3.5 - 条件自主智能（增强版）**

- ✅ 能够主动扫描环境
- ✅ 能够识别异常模式
- ✅ 能够发现优化机会
- ✅ 能够主动预警
- ⏳ 尚未实现：完全自主的定期扫描（需要后台任务调度）

---

## 典型应用场景

### 场景一：性能监控

```python
# 注册性能监控器
def performance_monitor():
    return {
        "response_time": get_average_response_time(),
        "throughput": get_requests_per_second()
    }

engine.register_monitor("performance", performance_monitor)

# 定期扫描
state = engine.scan_environment()
anomalies = engine.detect_anomalies()

# 如果检测到性能异常，自动创建预警
```

### 场景二：工具集成机会发现

```python
# 用户询问："能用 OpenCode 吗？"
opportunities = engine.discover_opportunities(context={
    "tools": ["OpenCode"],
    "user_query": "能用 OpenCode 吗？"
})

# 系统主动发现集成机会
# opportunity: "集成 OpenCode 工具"
# potential_value: 0.8
# effort_required: 0.6
```

### 场景三：异常模式学习

```python
# 持续监控一段时间后
engine.scan_environment()  # 每分钟执行一次

# 系统自动学习正常模式
# 当出现偏离时，自动检测为异常
anomalies = engine.detect_anomalies()
```

---

## 版本历史

### v0.1.0 (2026-01-24)
- ✅ 核心主动感知引擎
- ✅ 环境状态监控
- ✅ 异常检测（4种类型）
- ✅ 机会发现（4种类型）
- ✅ 主动预警机制
- ✅ FastAPI 服务器
- ✅ 完整 API 文档

---

**作者**: Manus AI  
**节点编号**: 109  
**端口**: 9101
