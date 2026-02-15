# Node_108_MetaCognition - 元认知节点

**让系统能够反思自己的思考过程，评估决策质量，并持续优化策略。**

---

## 核心功能

### 1. 思维过程追踪 (Thought Tracking)
- 记录系统的每一个思维步骤
- 分类思维类型：感知、分析、决策、行动、反思
- 评估思维质量
- 检测认知偏差

### 2. 决策质量评估 (Decision Evaluation)
- 记录决策过程和推理
- 跟踪决策结果
- 评估决策质量
- 分析置信度匹配度

### 3. 策略优化 (Strategy Optimization)
- 基于历史经验优化策略
- 识别改进机会
- 生成具体优化建议

### 4. 认知偏差检测 (Cognitive Bias Detection)
- 确认偏差 (Confirmation Bias)
- 锚定偏差 (Anchoring Bias)
- 可得性偏差 (Availability Bias)
- 沉没成本谬误 (Sunk Cost Fallacy)
- 过度自信 (Overconfidence)

---

## API 端点

### 1. 追踪思维

**POST** `/api/v1/track_thought`

```json
{
  "thought_type": "analysis",
  "content": "分析用户需求，发现需要集成外部工具",
  "context": {
    "task": "tool_integration",
    "user_query": "能否使用 OpenCode？"
  }
}
```

**响应**:
```json
{
  "thought_id": "thought_1737700000000",
  "thought_type": "analysis",
  "quality_score": 0.85,
  "biases_detected": [],
  "timestamp": 1737700000.0
}
```

---

### 2. 追踪决策

**POST** `/api/v1/track_decision`

```json
{
  "decision_content": "开发 Node_113_ExternalToolWrapper",
  "alternatives": [
    "直接为 OpenCode 开发专用节点",
    "手动编写集成脚本"
  ],
  "reasoning": "通用包装器可以支持任何 CLI 工具，扩展性最强",
  "confidence": 0.8
}
```

**响应**:
```json
{
  "decision_id": "decision_1737700000000",
  "decision_content": "开发 Node_113_ExternalToolWrapper",
  "confidence": 0.8,
  "timestamp": 1737700000.0
}
```

---

### 3. 评估决策

**POST** `/api/v1/evaluate_decision`

```json
{
  "decision_id": "decision_1737700000000",
  "outcome": {
    "success_score": 0.9,
    "actual_result": "成功开发并测试通过",
    "time_taken": 7200
  }
}
```

**响应**:
```json
{
  "decision_id": "decision_1737700000000",
  "overall_quality": 0.85,
  "success_score": 0.9,
  "confidence_match": 0.9,
  "reasoning_quality": 0.75
}
```

---

### 4. 反思

**POST** `/api/v1/reflect`

```json
{
  "time_window": 3600
}
```

**响应**:
```json
{
  "timestamp": "2026-01-24T12:00:00",
  "time_window": 3600,
  "thought_patterns": {
    "total_thoughts": 15,
    "type_distribution": {
      "perception": 3,
      "analysis": 6,
      "decision": 4,
      "action": 2
    },
    "average_quality": 0.82
  },
  "decision_patterns": {
    "total_decisions": 4,
    "average_confidence": 0.78,
    "average_alternatives": 2.5
  },
  "improvement_opportunities": [
    {
      "area": "alternatives",
      "suggestion": "在决策前考虑更多备选方案"
    }
  ],
  "cognitive_state": {
    "total_thoughts": 15,
    "total_decisions": 4,
    "average_decision_quality": 0.85,
    "detected_biases": {
      "confirmation_bias": 2
    }
  }
}
```

---

### 5. 优化策略

**POST** `/api/v1/optimize_strategy`

```json
{
  "task_description": "集成外部开发工具",
  "current_strategy": {
    "approach": "逐个工具开发专用节点",
    "priority": "OpenCode 优先"
  }
}
```

**响应**:
```json
{
  "original_strategy": {
    "approach": "逐个工具开发专用节点",
    "priority": "OpenCode 优先"
  },
  "analysis": {
    "task": "集成外部开发工具",
    "strategy_complexity": 2,
    "historical_performance": 0.85
  },
  "recommended_changes": [
    {
      "type": "bias_mitigation",
      "description": "引入偏差缓解机制",
      "details": ["主动寻找反驳性证据"]
    }
  ],
  "expected_improvements": []
}
```

---

### 6. 获取认知状态

**GET** `/api/v1/cognitive_state`

**响应**:
```json
{
  "total_thoughts": 15,
  "total_decisions": 4,
  "average_decision_quality": 0.85,
  "detected_biases": {
    "confirmation_bias": 2,
    "overconfidence": 1
  },
  "last_reflection": {
    "timestamp": "2026-01-24T12:00:00",
    "...": "..."
  }
}
```

---

## 使用示例

### Python 客户端

```python
import requests

NODE_URL = "http://localhost:9100"

# 1. 追踪思维
response = requests.post(f"{NODE_URL}/api/v1/track_thought", json={
    "thought_type": "analysis",
    "content": "分析系统架构，发现需要元认知能力",
    "context": {"task": "system_enhancement"}
})
thought = response.json()
print(f"Thought ID: {thought['thought_id']}")
print(f"Quality Score: {thought['quality_score']}")

# 2. 追踪决策
response = requests.post(f"{NODE_URL}/api/v1/track_decision", json={
    "decision_content": "开发 Node_108_MetaCognition",
    "alternatives": ["使用现有 LLM", "外部服务"],
    "reasoning": "需要深度集成到系统中",
    "confidence": 0.85
})
decision = response.json()
decision_id = decision['decision_id']

# 3. 评估决策（在决策执行后）
response = requests.post(f"{NODE_URL}/api/v1/evaluate_decision", json={
    "decision_id": decision_id,
    "outcome": {
        "success_score": 0.9,
        "actual_result": "成功部署并运行"
    }
})
evaluation = response.json()
print(f"Decision Quality: {evaluation['overall_quality']}")

# 4. 反思最近1小时的思维和决策
response = requests.post(f"{NODE_URL}/api/v1/reflect", json={
    "time_window": 3600
})
reflection = response.json()
print(f"Improvement Opportunities: {reflection['improvement_opportunities']}")
```

---

## 与其他节点的协同

### 依赖节点

| 节点 | 用途 |
| :--- | :--- |
| `Node_01_OneAPI` | 调用 LLM 进行深度分析 |
| `Node_103_KnowledgeGraph` | 存储和检索认知模式 |
| `Node_73_Learning` | 学习和沉淀元认知经验 |

### 被依赖节点

| 节点 | 用途 |
| :--- | :--- |
| `Node_109_ProactiveSensing` | 使用元认知能力评估感知结果 |
| `Node_115_NodeFactory` | 使用元认知能力评估生成的节点质量 |

---

## 配置

### 环境变量

```bash
NODE_108_PORT=9100
NODE_HOST=0.0.0.0
OPENAI_API_KEY=sk-...  # 用于调用 Node_01_OneAPI
```

---

## 启动节点

```bash
cd /path/to/ufo-galaxy-enhanced-nodes/nodes/node_108_metacognition
python server.py
```

访问 API 文档: http://localhost:9100/docs

---

## 测试

```bash
cd /path/to/ufo-galaxy-enhanced-nodes
python -m pytest tests/test_node_108.py -v
```

---

## 智能化水平

**L3.5 - 条件自主智能（增强版）**

- ✅ 能够反思自己的思考过程
- ✅ 能够评估自己的决策质量
- ✅ 能够识别认知偏差
- ✅ 能够优化策略
- ⏳ 尚未实现：自主触发反思（需要 Node_109_ProactiveSensing）

---

## 版本历史

### v0.1.0 (2026-01-24)
- ✅ 核心元认知引擎
- ✅ 思维追踪功能
- ✅ 决策评估功能
- ✅ 认知偏差检测
- ✅ 反思功能
- ✅ 策略优化功能
- ✅ FastAPI 服务器
- ✅ 完整 API 文档

---

**作者**: Manus AI  
**节点编号**: 108  
**端口**: 9100
