# Node_113_ExternalToolWrapper - 通用工具包装器

**让系统能够动态学习和使用任何 CLI 工具，无需预先编写集成代码。**

---

## 核心功能

### 1. 工具自动发现 (Tool Discovery)
- 通过搜索引擎发现工具信息
- 使用 LLM 理解工具文档
- 自动提取安装方法和使用方式

### 2. 动态命令生成 (Dynamic Command Generation)
- 基于任务描述生成命令
- 智能参数推断
- 上下文感知

### 3. 自动安装 (Auto Installation)
- 支持多种安装方法（curl|bash, apt, pip, npm等）
- 安装后自动验证
- 错误处理和重试

### 4. 执行结果验证 (Result Verification)
- 语义验证（任务是否完成）
- 错误检测和分析
- 执行历史记录

---

## API 端点

### 1. 使用工具

**POST** `/api/v1/use_tool`

```json
{
  "tool_name": "jq",
  "task_description": "extract name field from json",
  "context": {
    "input_file": "data.json"
  }
}
```

**响应**:
```json
{
  "success": true,
  "stdout": "John Doe",
  "stderr": "",
  "return_code": 0,
  "execution_time": 0.15,
  "command": "jq '.name' data.json",
  "timestamp": 1737700000.0
}
```

**工作流程**:
1. 检查是否已知 `jq`
2. 如果未知，自动发现并学习
3. 检查是否已安装
4. 如果未安装，自动安装
5. 生成命令
6. 执行并返回结果

---

### 2. 手动教授工具

**POST** `/api/v1/learn_tool`

```json
{
  "tool_name": "opencode",
  "tool_type": "cli",
  "description": "AI-powered code generation tool",
  "install_command": "curl -fsSL https://opencode.dev/install.sh | bash",
  "examples": [
    "opencode -p 'write a fibonacci function'",
    "opencode -m gpt-4 -p 'create a REST API'"
  ]
}
```

**响应**:
```json
{
  "tool_name": "opencode",
  "tool_type": "cli",
  "description": "AI-powered code generation tool",
  "install_method": "curl_script",
  "install_command": "curl -fsSL https://opencode.dev/install.sh | bash",
  "config_path": null,
  "config_template": null,
  "common_commands": [],
  "parameters": [],
  "examples": [
    "opencode -p 'write a fibonacci function'",
    "opencode -m gpt-4 -p 'create a REST API'"
  ],
  "documentation_url": null,
  "learned_at": 1737700000.0
}
```

---

### 3. 自动发现工具

**POST** `/api/v1/discover_tool`

```json
{
  "tool_name": "ffmpeg"
}
```

**响应**: 工具知识（同上）

**工作流程**:
1. 搜索 "ffmpeg CLI tool usage"
2. 使用 LLM 理解搜索结果
3. 提取安装方法、常用命令、参数等
4. 存储到知识库

---

### 4. 获取已知工具

**GET** `/api/v1/known_tools`

**响应**:
```json
{
  "tools": ["jq", "curl", "ffmpeg", "opencode"]
}
```

---

### 5. 获取工具知识

**GET** `/api/v1/tool_knowledge/opencode`

**响应**: 工具知识详情

---

### 6. 忘记工具

**DELETE** `/api/v1/forget_tool`

```json
{
  "tool_name": "opencode"
}
```

**响应**:
```json
{
  "success": true
}
```

---

### 7. 获取执行历史

**GET** `/api/v1/execution_history?limit=10`

**响应**: 最近的执行记录列表

---

## 使用示例

### Python 客户端

```python
import requests

NODE_URL = "http://localhost:9102"

# 示例1：使用 jq 处理 JSON
response = requests.post(f"{NODE_URL}/api/v1/use_tool", json={
    "tool_name": "jq",
    "task_description": ".name",
    "context": {"input": '{"name": "John", "age": 30}'}
})
result = response.json()
print(f"Result: {result['stdout']}")

# 示例2：教授系统使用 OpenCode
response = requests.post(f"{NODE_URL}/api/v1/learn_tool", json={
    "tool_name": "opencode",
    "tool_type": "cli",
    "description": "AI code generation",
    "install_command": "curl -fsSL https://opencode.dev/install.sh | bash",
    "examples": ["opencode -p 'hello world function'"]
})
print(f"Learned: {response.json()['tool_name']}")

# 示例3：使用 OpenCode 生成代码
response = requests.post(f"{NODE_URL}/api/v1/use_tool", json={
    "tool_name": "opencode",
    "task_description": "-p 'write a fibonacci function in Python'",
    "context": {}
})
result = response.json()
print(f"Generated Code:\n{result['stdout']}")

# 示例4：自动发现 curl
response = requests.post(f"{NODE_URL}/api/v1/discover_tool", json={
    "tool_name": "curl"
})
knowledge = response.json()
print(f"Discovered: {knowledge['description']}")

# 示例5：获取已知工具
response = requests.get(f"{NODE_URL}/api/v1/known_tools")
tools = response.json()["tools"]
print(f"Known Tools: {', '.join(tools)}")
```

---

## 与其他节点的协同

### 依赖节点

| 节点 | 用途 |
| :--- | :--- |
| `Node_22_BraveSearch` | 搜索工具文档和教程 |
| `Node_01_OneAPI` | 理解文档，生成命令 |
| `Node_09_Sandbox` | 安全执行命令 |
| `Node_73_Learning` | 学习和沉淀工具使用经验 |

### 被依赖节点

| 节点 | 用途 |
| :--- | :--- |
| `Node_114_OpenCode` | 可以调用通用包装器作为后备 |
| `Node_115_NodeFactory` | 使用通用包装器测试新工具 |

---

## 配置

### 环境变量

```bash
NODE_113_PORT=9102
NODE_HOST=0.0.0.0
OPENAI_API_KEY=sk-...  # 用于 LLM 理解
BRAVE_API_KEY=...  # 用于搜索
```

### 引擎配置

```python
engine.config = {
    "max_search_results": 5,
    "command_timeout": 30,
    "auto_install": True,
    "verify_after_install": True
}
```

---

## 启动节点

```bash
cd /path/to/ufo-galaxy-enhanced-nodes/nodes/node_113_external_tool_wrapper
python server.py
```

访问 API 文档: http://localhost:9102/docs

---

## 测试

```bash
cd /path/to/ufo-galaxy-enhanced-nodes
python -m pytest tests/test_node_113.py -v
```

---

## 智能化水平

**L3 - 条件自主智能**

- ✅ 能够动态学习新工具
- ✅ 能够自动安装工具
- ✅ 能够生成和执行命令
- ✅ 能够验证执行结果
- ⏳ 尚未实现：深度语义理解（需要更强的 LLM 集成）

---

## 典型应用场景

### 场景一：用户询问"能用 OpenCode 吗？"

```python
# 1. 系统自动发现 OpenCode
knowledge = engine.discover_tool("opencode")

# 2. 自动安装
result = engine.use_tool(
    tool_name="opencode",
    task_description="-p 'hello world'",
    context={}
)

# 3. 返回结果给用户
print(f"Yes! OpenCode is now available. Generated: {result.stdout}")
```

### 场景二：批量处理文件

```python
# 使用 ffmpeg 转换视频格式
for video in videos:
    result = engine.use_tool(
        tool_name="ffmpeg",
        task_description=f"-i {video} -c:v libx264 output.mp4",
        context={"input_file": video}
    )
```

### 场景三：数据处理管道

```python
# 1. 使用 curl 下载数据
result1 = engine.use_tool("curl", "-o data.json https://api.example.com/data")

# 2. 使用 jq 提取字段
result2 = engine.use_tool("jq", ".items[] | .name", {"input_file": "data.json"})

# 3. 使用 sort 排序
result3 = engine.use_tool("sort", "-u", {"input": result2.stdout})
```

---

## 支持的工具类型

| 类型 | 示例 | 支持程度 |
| :--- | :--- | :---: |
| **CLI 工具** | jq, curl, ffmpeg, git | ✅ 完全支持 |
| **HTTP API** | REST APIs | ⚠️ 部分支持 |
| **代码库** | Python/Node.js 库 | ⏳ 计划中 |
| **GUI 应用** | VS Code, Photoshop | ⏳ 需要 Node_36_UIAWindows |

---

## 支持的安装方法

| 方法 | 示例 | 支持程度 |
| :--- | :--- | :---: |
| **curl \| bash** | `curl ... \| bash` | ✅ 完全支持 |
| **包管理器** | apt, yum, brew | ✅ 完全支持 |
| **pip** | `pip install ...` | ✅ 完全支持 |
| **npm** | `npm install -g ...` | ✅ 完全支持 |
| **下载二进制** | wget + chmod | ✅ 完全支持 |
| **手动安装** | 需要用户介入 | ⚠️ 部分支持 |

---

## 限制与注意事项

1. **安全性**: 自动执行命令存在安全风险，建议在沙箱环境中运行
2. **LLM 依赖**: 命令生成质量依赖 LLM 能力
3. **工具兼容性**: 某些工具可能需要特殊配置
4. **网络依赖**: 需要网络连接来搜索和下载工具

---

## 版本历史

### v0.1.0 (2026-01-24)
- ✅ 核心工具包装引擎
- ✅ 工具自动发现
- ✅ 动态命令生成
- ✅ 自动安装和验证
- ✅ 执行结果验证
- ✅ FastAPI 服务器
- ✅ 完整 API 文档

---

**作者**: Manus AI  
**节点编号**: 113  
**端口**: 9102
