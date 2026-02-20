# Node_114_OpenCode - OpenCode 专用节点

**为 OpenCode 提供深度集成，支持多模型、自动配置、代码质量验证。**

---

## 核心功能

### 1. 多模型支持 (Multi-Model Support)
- OpenAI (GPT-4, GPT-4-Turbo, GPT-3.5-Turbo)
- Anthropic (Claude-3-Opus, Claude-3-Sonnet, Claude-3-Haiku)
- DeepSeek (DeepSeek-Coder, DeepSeek-Chat)
- Groq (Llama-3-70B, Mixtral-8x7B)
- 本地模型

### 2. 自动配置管理 (Auto Configuration)
- 自动写入 `~/.opencode.json`
- API Key 管理（集成 Node_03_SecretVault）
- 模型参数配置

### 3. 代码质量验证 (Code Quality Validation)
- 语法检查
- 质量评分
- 集成 Node_102_DebugOptimize 进行优化

### 4. 深度系统集成 (Deep Integration)
- 与 Node_113_ExternalToolWrapper 协同
- 与 Node_108_MetaCognition 协同（评估生成质量）
- 与 Node_109_ProactiveSensing 协同（发现优化机会）

---

## API 端点

### 1. 生成代码

**POST** `/api/v1/generate_code`

```json
{
  "prompt": "write a fibonacci function in Python",
  "language": "python",
  "model": "gpt-4",
  "context": {}
}
```

**响应**:
```json
{
  "success": true,
  "code": "def fibonacci(n):\n    if n <= 1:\n        return n\n    return fibonacci(n-1) + fibonacci(n-2)",
  "language": "python",
  "model_used": "gpt-4",
  "execution_time": 2.35,
  "quality_score": 0.95,
  "validation_errors": [],
  "timestamp": 1737700000.0
}
```

---

### 2. 配置 OpenCode

**POST** `/api/v1/configure`

```json
{
  "model": "claude-3-opus",
  "provider": "anthropic",
  "api_key": "sk-ant-...",
  "temperature": 0.7
}
```

**响应**:
```json
{
  "success": true,
  "config": {
    "model": "claude-3-opus",
    "provider": "anthropic",
    "api_key": "sk-ant-...",
    "api_base": null,
    "temperature": 0.7,
    "max_tokens": 2000,
    "timeout": 30
  }
}
```

---

### 3. 安装 OpenCode

**POST** `/api/v1/install`

**响应**:
```json
{
  "success": true,
  "message": "OpenCode installed successfully",
  "path": "/usr/local/bin/opencode"
}
```

---

### 4. 获取状态

**GET** `/api/v1/status`

**响应**:
```json
{
  "installed": true,
  "opencode_path": "/usr/local/bin/opencode",
  "config": {
    "model": "gpt-4",
    "provider": "openai",
    "temperature": 0.7,
    "max_tokens": 2000,
    "timeout": 30
  },
  "supported_models": {
    "openai": ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"],
    "anthropic": ["claude-3-opus", "claude-3-sonnet", "claude-3-haiku"],
    "deepseek": ["deepseek-coder", "deepseek-chat"],
    "groq": ["llama-3-70b", "mixtral-8x7b"],
    "local": ["local-model"]
  },
  "generation_count": 42
}
```

---

### 5. 获取支持的模型

**GET** `/api/v1/supported_models`

**响应**: 提供商 -> 模型列表映射

---

### 6. 获取生成历史

**GET** `/api/v1/generation_history?limit=10`

**响应**: 最近的代码生成记录列表

---

## 使用示例

### Python 客户端

```python
import requests

NODE_URL = "http://localhost:9103"

# 1. 配置 OpenCode（使用 GPT-4）
response = requests.post(f"{NODE_URL}/api/v1/configure", json={
    "model": "gpt-4",
    "provider": "openai",
    "api_key": "sk-...",
    "temperature": 0.7
})
print(f"Configured: {response.json()}")

# 2. 生成 Python 代码
response = requests.post(f"{NODE_URL}/api/v1/generate_code", json={
    "prompt": "write a function to calculate factorial",
    "language": "python"
})
result = response.json()
print(f"Generated Code:\n{result['code']}")
print(f"Quality Score: {result['quality_score']}")

# 3. 生成 JavaScript 代码
response = requests.post(f"{NODE_URL}/api/v1/generate_code", json={
    "prompt": "create an async function to fetch user data from API",
    "language": "javascript",
    "model": "claude-3-sonnet"
})
result = response.json()
print(f"Generated Code:\n{result['code']}")

# 4. 获取状态
response = requests.get(f"{NODE_URL}/api/v1/status")
status = response.json()
print(f"Installed: {status['installed']}")
print(f"Generation Count: {status['generation_count']}")

# 5. 查看支持的模型
response = requests.get(f"{NODE_URL}/api/v1/supported_models")
models = response.json()
for provider, model_list in models.items():
    print(f"{provider}: {', '.join(model_list)}")
```

---

## 与其他节点的协同

### 依赖节点

| 节点 | 用途 |
| :--- | :--- |
| `Node_03_SecretVault` | 安全存储 API Keys |
| `Node_102_DebugOptimize` | 代码优化和调试 |
| `Node_113_ExternalToolWrapper` | 作为后备方案 |

### 被依赖节点

| 节点 | 用途 |
| :--- | :--- |
| `Node_115_NodeFactory` | 使用 OpenCode 生成新节点代码 |
| 所有节点 | 为所有节点提供代码生成能力 |

---

## 配置

### 环境变量

```bash
NODE_114_PORT=9103
NODE_HOST=0.0.0.0
OPENAI_API_KEY=sk-...  # OpenAI API Key
ANTHROPIC_API_KEY=sk-ant-...  # Anthropic API Key
DEEPSEEK_API_KEY=...  # DeepSeek API Key
```

### OpenCode 配置文件

位置: `~/.opencode.json`

```json
{
  "model": "gpt-4",
  "provider": "openai",
  "temperature": 0.7,
  "max_tokens": 2000,
  "api_key": "sk-..."
}
```

---

## 启动节点

```bash
cd /path/to/ufo-galaxy-enhanced-nodes/nodes/node_114_opencode
python server.py
```

访问 API 文档: http://localhost:9103/docs

---

## 测试

```bash
cd /path/to/ufo-galaxy-enhanced-nodes
python -m pytest tests/test_node_114.py -v
```

---

## 智能化水平

**L3 - 条件自主智能**

- ✅ 支持多种 AI 模型
- ✅ 自动配置管理
- ✅ 代码质量验证
- ✅ 深度系统集成
- ⏳ 尚未实现：自动模型选择（基于任务类型）

---

## 典型应用场景

### 场景一：快速原型开发

```python
# 生成完整的 REST API
response = requests.post(f"{NODE_URL}/api/v1/generate_code", json={
    "prompt": "create a FastAPI REST API with CRUD operations for a User model",
    "language": "python",
    "model": "gpt-4"
})
code = response.json()["code"]
# 直接保存并运行
```

### 场景二：多模型对比

```python
models = ["gpt-4", "claude-3-opus", "deepseek-coder"]
prompt = "write an efficient sorting algorithm"

for model in models:
    result = requests.post(f"{NODE_URL}/api/v1/generate_code", json={
        "prompt": prompt,
        "language": "python",
        "model": model
    }).json()
    
    print(f"{model}: Quality Score = {result['quality_score']}")
```

### 场景三：与 Node_115 协同生成新节点

```python
# Node_115 调用 Node_114 生成节点代码
response = requests.post(f"{NODE_URL}/api/v1/generate_code", json={
    "prompt": "create a FastAPI server for a weather forecast node",
    "language": "python",
    "context": {
        "node_number": 116,
        "node_name": "WeatherForecast"
    }
})
```

---

## 支持的语言

| 语言 | 支持程度 | 推荐模型 |
| :--- | :---: | :--- |
| **Python** | ✅ 完全支持 | GPT-4, DeepSeek-Coder |
| **JavaScript** | ✅ 完全支持 | Claude-3-Opus, GPT-4 |
| **TypeScript** | ✅ 完全支持 | Claude-3-Sonnet |
| **Java** | ✅ 完全支持 | GPT-4 |
| **C++** | ✅ 完全支持 | DeepSeek-Coder |
| **Go** | ✅ 完全支持 | Claude-3-Opus |
| **Rust** | ✅ 完全支持 | GPT-4 |

---

## 与 Node_113 的区别

| 特性 | Node_113 (通用包装器) | Node_114 (OpenCode 专用) |
| :--- | :---: | :---: |
| **工具范围** | 任何 CLI 工具 | 仅 OpenCode |
| **集成深度** | 浅层（命令执行） | 深层（配置、验证、优化） |
| **代码质量** | 无验证 | 语法检查 + 质量评分 |
| **多模型支持** | 无 | 5个提供商，15+模型 |
| **配置管理** | 无 | 自动配置文件管理 |
| **使用场景** | 探索新工具 | 生产级代码生成 |

---

## 版本历史

### v0.1.0 (2026-01-24)
- ✅ 核心 OpenCode 引擎
- ✅ 多模型支持（5个提供商）
- ✅ 自动配置管理
- ✅ 代码质量验证
- ✅ FastAPI 服务器
- ✅ 完整 API 文档

---

**作者**: Manus AI  
**节点编号**: 114  
**端口**: 9103
