# Node 79: Local LLM

本地大语言模型服务 - 集成 Ollama

## 功能特性

### 核心功能
1. **Ollama 集成**
   - 模型管理（下载、删除、列表）
   - 本地推理（同步/异步）
   - 流式输出
   - Function Calling（工具调用）

2. **Fallback 机制**
   - 本地模型失败自动切换到云端
   - 自动重试
   - 降级策略

### 3. 多模型支持
   - DeepSeek-Coder-6.7B (代码任务首选)
   - Qwen2.5-14B-Instruct (复杂任务)
   - Qwen2.5-7B-Instruct (常规任务)
   - Qwen2.5-3B-Instruct (简单任务)

### 4. 智能模型选择
   - 根据任务类型自动选择最优模型
   - 支持手动指定 task_type
   - 基于关键词智能识别

### 优势
- ✅ 离线可用
- ✅ 无 API 费用
- ✅ 响应速度快 (< 1s)
- ✅ 数据隐私保护
- ✅ 自动 Fallback

---

## 部署指南

### 1. 安装 Ollama

**Windows:**
```powershell
winget install Ollama.Ollama
```

**Linux:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**macOS:**
```bash
brew install ollama
```

### 2. 下载模型

```bash
# 代码任务首选：DeepSeek-Coder
ollama pull deepseek-coder:6.7b-instruct-q4_K_M

# 复杂任务：Qwen2.5-14B (如果内存 >= 16GB)
ollama pull qwen2.5:14b-instruct-q4_K_M

# 常规任务：Qwen2.5-7B
ollama pull qwen2.5:7b-instruct-q4_K_M

# 简单任务：Qwen2.5-3B (快速响应)
ollama pull qwen2.5:3b-instruct-q4_K_M
```

### 3. 启动 Ollama 服务

```bash
# 默认端口 11434
ollama serve
```

### 4. 配置环境变量

创建 `.env` 文件：

```bash
# Ollama 配置
OLLAMA_URL=http://localhost:11434
DEFAULT_MODEL=qwen2.5:7b-instruct-q4_K_M

# 多模型配置
CODE_MODEL=deepseek-coder:6.7b-instruct-q4_K_M
COMPLEX_MODEL=qwen2.5:14b-instruct-q4_K_M
NORMAL_MODEL=qwen2.5:7b-instruct-q4_K_M
SIMPLE_MODEL=qwen2.5:3b-instruct-q4_K_M

# Fallback 配置
FALLBACK_ENABLED=true
FALLBACK_URL=http://localhost:8001  # Node 01 (OneAPI)

# 日志级别
LOG_LEVEL=INFO
```

### 5. 启动 Node 79

```bash
cd nodes/Node_79_LocalLLM
pip install -r requirements.txt
python main.py
```

---

## API 使用示例

### 1. 健康检查

```bash
curl http://localhost:8079/health
```

**响应:**
```json
{
  "status": "healthy",
  "ollama_available": true,
  "fallback_available": true,
  "timestamp": "2026-01-21T22:00:00"
}
```

### 2. 列出模型

```bash
curl http://localhost:8079/models
```

**响应:**
```json
{
  "models": [
    {
      "name": "qwen2.5:7b-instruct-q4_K_M",
      "size": 4661211136,
      "digest": "abc123...",
      "modified_at": "2026-01-21T20:00:00Z"
    }
  ],
  "count": 1
}
```

### 3. 生成响应（同步）

**手动指定模型：**
```bash
curl -X POST http://localhost:8079/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "介绍一下 UFO³ Galaxy 系统",
    "model": "qwen2.5:7b-instruct-q4_K_M",
    "temperature": 0.7,
    "max_tokens": 500
  }'
```

**自动选择模型（推荐）：**
```bash
# 代码任务 - 自动使用 DeepSeek-Coder
curl -X POST http://localhost:8079/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Write a Python function to calculate fibonacci numbers",
    "task_type": "code"
  }'

# 复杂任务 - 自动使用 Qwen2.5-14B
curl -X POST http://localhost:8079/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Analyze the architecture of UFO³ Galaxy and suggest optimizations",
    "task_type": "complex"
  }'

# 简单任务 - 自动使用 Qwen2.5-3B
curl -X POST http://localhost:8079/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "你好，介绍一下你自己",
    "task_type": "simple"
  }'
```

**响应:**
```json
{
  "model": "qwen2.5:7b-instruct-q4_K_M",
  "response": "UFO³ Galaxy 是一个分布式 AI 代理系统...",
  "done": true,
  "total_duration": 1234567890,
  "eval_duration": 987654321
}
```

### 4. 生成响应（流式）

```bash
curl -X POST http://localhost:8079/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "写一首关于 AI 的诗",
    "stream": true
  }'
```

**响应 (SSE):**
```
data: {"chunk": "在"}
data: {"chunk": "数字"}
data: {"chunk": "的"}
data: {"chunk": "海洋"}
...
```

### 5. 聊天

```bash
curl -X POST http://localhost:8079/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "system", "content": "你是一个有帮助的助手"},
      {"role": "user", "content": "你好"}
    ],
    "model": "qwen2.5:7b-instruct-q4_K_M"
  }'
```

**响应:**
```json
{
  "model": "qwen2.5:7b-instruct-q4_K_M",
  "response": "你好！很高兴为您服务。有什么我可以帮助您的吗？",
  "done": true
}
```

### 6. Function Calling（工具调用）

```bash
curl -X POST http://localhost:8079/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "查询北京的天气",
    "tools": [
      {
        "name": "get_weather",
        "description": "获取指定城市的天气信息",
        "parameters": {
          "type": "object",
          "properties": {
            "city": {"type": "string", "description": "城市名称"}
          },
          "required": ["city"]
        }
      }
    ]
  }'
```

**响应:**
```json
{
  "model": "qwen2.5:7b-instruct-q4_K_M",
  "response": "我需要调用 get_weather 工具...",
  "done": true,
  "tool_calls": [
    {
      "name": "get_weather",
      "arguments": {"city": "北京"}
    }
  ]
}
```

---

## Python SDK 示例

### 基本使用

```python
import httpx
import asyncio

async def main():
    client = httpx.AsyncClient()
    
    # 自动选择模型
    response = await client.post(
        "http://localhost:8079/generate",
        json={
            "prompt": "介绍一下 Python",
            "temperature": 0.7,
            "max_tokens": 500
        }
    )
    
    data = response.json()
    print(data["response"])
    
    await client.aclose()

asyncio.run(main())
```

### 智能模型选择

```python
import httpx
import asyncio

async def generate_with_task_type(prompt: str, task_type: str):
    """根据任务类型生成响应"""
    client = httpx.AsyncClient()
    
    response = await client.post(
        "http://localhost:8079/generate",
        json={
            "prompt": prompt,
            "task_type": task_type,  # code, complex, normal, simple
            "temperature": 0.7
        }
    )
    
    data = response.json()
    print(f"Model used: {data['model']}")
    print(f"Response: {data['response']}")
    
    await client.aclose()

async def main():
    # 代码任务 - 使用 DeepSeek-Coder
    await generate_with_task_type(
        "Write a function to sort a list",
        "code"
    )
    
    # 复杂任务 - 使用 Qwen2.5-14B
    await generate_with_task_type(
        "Design a distributed system architecture",
        "complex"
    )
    
    # 简单任务 - 使用 Qwen2.5-3B
    await generate_with_task_type(
        "你好",
        "simple"
    )

asyncio.run(main())
```

---

## 性能指标

### 硬件需求

| 模型 | 内存 | 推荐 GPU | 速度 (tokens/s) |
|------|------|----------|----------------|
| Qwen2.5-7B (Q4) | 4-5GB | 可选 | 20-30 |
| Llama 3.1-8B (Q4) | 4-5GB | 可选 | 15-25 |
| Gemma 2-9B (Q4) | 5-6GB | 可选 | 15-20 |

### 响应时间

| 操作 | 本地 | 云端 (Fallback) |
|------|------|----------------|
| 首次加载 | 2-5s | - |
| 生成 (100 tokens) | 3-5s | 2-3s |
| 生成 (500 tokens) | 15-25s | 5-10s |

---

## Fallback 机制

当本地 Ollama 不可用时，自动切换到云端 LLM（Node 01）：

```
请求 → Node 79 (Local LLM)
         ↓ (失败)
         → Node 01 (OneAPI)
         → 云端 LLM (GPT-3.5/Claude)
```

**触发条件：**
- Ollama 服务未启动
- 模型未下载
- 推理超时
- 其他错误

---

## 故障排查

### 1. Ollama 服务未启动

**错误:**
```
Ollama health check failed: Connection refused
```

**解决:**
```bash
ollama serve
```

### 2. 模型未下载

**错误:**
```
model 'qwen2.5:7b-instruct-q4_K_M' not found
```

**解决:**
```bash
ollama pull qwen2.5:7b-instruct-q4_K_M
```

### 3. 内存不足

**错误:**
```
Out of memory
```

**解决:**
- 使用更小的模型（Q4 量化版）
- 减少 `max_tokens`
- 增加系统内存

### 4. Fallback 失败

**错误:**
```
Cloud fallback failed
```

**解决:**
- 检查 Node 01 (OneAPI) 是否运行
- 检查 `FALLBACK_URL` 配置
- 检查云端 API Key

---

## 最佳实践

### 1. 模型选择

**场景推荐：**
- **中文任务**: Qwen2.5-7B (最佳)
- **英文任务**: Llama 3.1-8B
- **多语言**: Gemma 2-9B

### 2. 参数调优

```python
# 创造性任务（写作、头脑风暴）
{
  "temperature": 0.9,
  "max_tokens": 2048
}

# 事实性任务（问答、翻译）
{
  "temperature": 0.3,
  "max_tokens": 500
}

# 代码生成
{
  "temperature": 0.2,
  "max_tokens": 1024
}
```

### 3. 性能优化

- 使用量化模型（Q4）减少内存占用
- 启用 GPU 加速（如果可用）
- 合理设置 `max_tokens` 避免浪费
- 使用流式输出提升用户体验

---

## 集成示例

### 与 Node 50 (Transformer) 集成

```python
# Node 50 调用 Node 79
async def understand_intent(user_input: str):
    response = await httpx.post(
        "http://localhost:8079/generate",
        json={
            "prompt": f"分析用户意图：{user_input}",
            "system": "你是一个意图识别专家",
            "temperature": 0.3,
            "max_tokens": 200
        }
    )
    
    return response.json()["response"]
```

### 与 Node 80 (Memory) 集成

```python
# 带记忆的对话
async def chat_with_memory(user_input: str, session_id: str):
    # 1. 从 Node 80 获取历史
    history = await get_conversation_history(session_id)
    
    # 2. 调用 Node 79 生成响应
    messages = [
        {"role": "system", "content": "你是一个有帮助的助手"},
        *history,
        {"role": "user", "content": user_input}
    ]
    
    response = await httpx.post(
        "http://localhost:8079/chat",
        json={"messages": messages}
    )
    
    # 3. 保存到 Node 80
    await save_to_memory(session_id, user_input, response.json()["response"])
    
    return response.json()["response"]
```

---

## 更新日志

### v1.0.0 (2026-01-21)
- ✅ 初始版本
- ✅ Ollama 集成
- ✅ 模型管理
- ✅ Function Calling
- ✅ Fallback 机制
- ✅ 流式输出

---

## 相关链接

- [Ollama 官网](https://ollama.com/)
- [Qwen2.5 模型](https://ollama.com/library/qwen2.5)
- [Llama 3.1 模型](https://ollama.com/library/llama3.1)
- [Node 01 (OneAPI)](../Node_01_OneAPI/README.md)
- [Node 80 (Memory)](../Node_80_MemorySystem/README.md)
