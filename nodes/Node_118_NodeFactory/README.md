# Node_115_NodeFactory - 节点工厂

**让系统能够自主创建新节点，实现真正的自我扩展能力。**

---

## 核心功能

### 1. 动态节点生成 (Dynamic Node Generation)
- 从规格生成完整节点
- 从自然语言描述生成节点
- 自动创建目录结构

### 2. 代码自动生成 (Automatic Code Generation)
- 核心引擎代码
- FastAPI 服务器代码
- README 文档
- 测试文件

### 3. 代码质量验证 (Code Quality Validation)
- 语法检查
- 文件完整性检查
- 自动测试

### 4. 自动部署 (Auto Deployment)
- 启动节点服务器
- 验证节点运行状态
- 集成到系统

---

## API 端点

### 1. 生成节点（从规格）

**POST** `/api/v1/generate_node`

```json
{
  "node_number": 116,
  "node_name": "WeatherForecast",
  "node_type": "perception",
  "description": "实时天气预报节点",
  "port": 9105,
  "capabilities": ["weather_api", "forecast"],
  "dependencies": [22, 25],
  "api_endpoints": [
    {"method": "GET", "path": "/weather", "description": "获取天气"}
  ],
  "auto_deploy": false
}
```

**响应**:
```json
{
  "success": true,
  "node_spec": {
    "node_number": 116,
    "node_name": "WeatherForecast",
    "node_type": "perception",
    "description": "实时天气预报节点",
    "port": 9105,
    "capabilities": ["weather_api", "forecast"],
    "dependencies": [22, 25],
    "api_endpoints": [...]
  },
  "generated_files": {
    "engine": "/tmp/generated_nodes/node_116_weatherforecast/core/weatherforecast_engine.py",
    "server": "/tmp/generated_nodes/node_116_weatherforecast/server.py",
    "readme": "/tmp/generated_nodes/node_116_weatherforecast/README.md",
    "test": "/tmp/generated_nodes/tests/test_node_116.py"
  },
  "validation_results": {
    "engine": true,
    "server": true,
    "readme": true,
    "test": true
  },
  "errors": [],
  "timestamp": 1737700000.0
}
```

---

### 2. 生成节点（从描述）

**POST** `/api/v1/generate_node_from_description`

```json
{
  "description": "一个能够监控系统资源使用情况的节点，包括 CPU、内存、磁盘和网络",
  "node_number": 117,
  "port": 9106,
  "auto_deploy": false
}
```

**响应**: 同上

**工作流程**:
1. 使用 LLM 理解描述
2. 推断节点类型、能力、依赖
3. 生成节点规格
4. 调用 `generate_node` 生成代码

---

### 3. 获取生成历史

**GET** `/api/v1/generation_history?limit=10`

**响应**: 最近的节点生成记录列表

---

## 使用示例

### Python 客户端

```python
import requests

NODE_URL = "http://localhost:9104"

# 示例1：从规格生成节点
response = requests.post(f"{NODE_URL}/api/v1/generate_node", json={
    "node_number": 116,
    "node_name": "WeatherForecast",
    "node_type": "perception",
    "description": "实时天气预报节点",
    "port": 9105,
    "capabilities": ["weather_api", "forecast"],
    "dependencies": [22, 25],
    "api_endpoints": [
        {"method": "GET", "path": "/weather", "description": "获取天气"}
    ],
    "auto_deploy": False
})
result = response.json()

if result["success"]:
    print(f"✅ Node {result['node_spec']['node_number']} generated successfully!")
    print(f"Generated files:")
    for file_type, path in result["generated_files"].items():
        print(f"  - {file_type}: {path}")
else:
    print(f"❌ Generation failed: {result['errors']}")

# 示例2：从自然语言描述生成节点
response = requests.post(f"{NODE_URL}/api/v1/generate_node_from_description", json={
    "description": "一个能够监控系统资源使用情况的节点，包括 CPU、内存、磁盘和网络",
    "node_number": 117,
    "port": 9106,
    "auto_deploy": False
})
result = response.json()
print(f"Generated Node: {result['node_spec']['node_name']}")
print(f"Type: {result['node_spec']['node_type']}")

# 示例3：查看生成历史
response = requests.get(f"{NODE_URL}/api/v1/generation_history?limit=5")
history = response.json()
print(f"Generated {len(history)} nodes:")
for record in history:
    spec = record["node_spec"]
    print(f"  - Node_{spec['node_number']}_{spec['node_name']} ({spec['node_type']})")
```

---

## 与其他节点的协同

### 依赖节点

| 节点 | 用途 |
| :--- | :--- |
| `Node_114_OpenCode` | 生成高质量代码 |
| `Node_108_MetaCognition` | 评估生成的节点质量 |
| `Node_109_ProactiveSensing` | 主动发现需要新节点的场景 |
| `Node_01_OneAPI` | 理解自然语言描述 |

### 被依赖节点

| 节点 | 用途 |
| :--- | :--- |
| 所有节点 | 为整个系统提供自我扩展能力 |

---

## 配置

### 环境变量

```bash
NODE_115_PORT=9104
NODE_HOST=0.0.0.0
OPENAI_API_KEY=sk-...  # 用于理解描述
```

### 输出目录

默认: `/tmp/generated_nodes`

可通过初始化参数修改:
```python
engine = NodeFactoryEngine(output_dir="/path/to/output")
```

---

## 启动节点

```bash
cd /path/to/ufo-galaxy-enhanced-nodes/nodes/node_115_node_factory
python server.py
```

访问 API 文档: http://localhost:9104/docs

---

## 测试

```bash
cd /path/to/ufo-galaxy-enhanced-nodes
python -m pytest tests/test_node_115.py -v
```

---

## 智能化水平

**L4 - 完全自主智能**

- ✅ 能够自主创建新节点
- ✅ 能够从自然语言理解需求
- ✅ 能够生成完整的代码和文档
- ✅ 能够验证生成的代码
- ⏳ 尚未实现：自主决定何时需要新节点（需要更深的系统集成）

---

## 典型应用场景

### 场景一：用户请求新功能

```
用户: "我需要一个节点来监控股票价格"

系统:
1. Node_109 检测到新需求
2. Node_108 评估是否需要新节点
3. Node_115 生成 Node_116_StockMonitor
4. 自动部署并集成到系统
5. 通知用户："✅ 股票监控节点已就绪！"
```

### 场景二：系统自我优化

```
系统内部:
1. Node_108 反思："响应时间过长"
2. Node_109 发现："缺少缓存节点"
3. Node_115 生成 Node_117_CacheManager
4. 自动部署并集成
5. 性能提升 50%
```

### 场景三：批量生成节点

```python
# 生成一系列传感器节点
sensors = [
    {"name": "Temperature", "description": "温度传感器"},
    {"name": "Humidity", "description": "湿度传感器"},
    {"name": "Pressure", "description": "气压传感器"}
]

for i, sensor in enumerate(sensors, start=116):
    response = requests.post(f"{NODE_URL}/api/v1/generate_node_from_description", json={
        "description": sensor["description"],
        "node_number": i,
        "port": 9105 + i - 116,
        "auto_deploy": True
    })
    print(f"Generated: Node_{i}_{sensor['name']}")
```

---

## 节点类型

| 类型 | 说明 | 示例 |
| :--- | :--- | :--- |
| **perception** | 感知节点 | 传感器、监控、搜索 |
| **cognition** | 认知节点 | 分析、推理、决策 |
| **action** | 行动节点 | 执行、控制、操作 |
| **learning** | 学习节点 | 训练、优化、适应 |
| **integration** | 集成节点 | 连接、协调、转换 |

---

## 生成的文件结构

```
/tmp/generated_nodes/
├── node_116_weatherforecast/
│   ├── __init__.py
│   ├── server.py
│   ├── README.md
│   ├── api/
│   │   └── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   └── weatherforecast_engine.py
│   └── utils/
│       └── __init__.py
└── tests/
    └── test_node_116.py
```

---

## 限制与注意事项

1. **代码质量**: 生成的代码质量依赖 Node_114_OpenCode 的能力
2. **复杂度**: 复杂节点可能需要人工优化
3. **测试**: 生成的测试可能不够全面
4. **部署**: 自动部署功能需要系统权限

---

## 未来增强

1. **智能模板选择**: 基于节点类型选择最佳模板
2. **依赖自动推断**: 自动分析并添加依赖节点
3. **性能优化**: 生成的代码自动优化
4. **版本管理**: 节点版本控制和升级

---

## 版本历史

### v0.1.0 (2026-01-24)
- ✅ 核心节点工厂引擎
- ✅ 从规格生成节点
- ✅ 从描述生成节点
- ✅ 代码质量验证
- ✅ FastAPI 服务器
- ✅ 完整 API 文档

---

**作者**: Manus AI  
**节点编号**: 115  
**端口**: 9104  
**智能化水平**: L4 - 完全自主智能
