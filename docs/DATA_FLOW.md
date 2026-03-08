# Galaxy - 数据流文档

本文档描述用户消息从输入到最终输出的完整流程。

---

## 1. 总体架构

```
用户输入 (Android / Web / Windows)
    │
    ▼
┌─────────────────────────────────┐
│  API 入口                        │
│  POST /api/v1/chat              │  ← core/api_routes.py
│  POST /api/v1/dashboard/chat    │  ← dashboard/backend/main.py
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  对话记忆                        │
│  core/ai_intent.py              │
│  ConversationMemory             │
│  - 记录 user 消息                │
│  - 恢复上下文 (最近 10 轮)       │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  意图分流                        │
│  _is_action_intent() 关键词判断  │
│  IntentParser 规则 + LLM 两级    │
└──────┬──────────┬───────────────┘
       │          │
  操作指令      纯聊天
       │          │
       ▼          ▼
┌──────────┐  ┌──────────────────┐
│ Agent    │  │ _handle_pure_    │
│ ReAct    │  │ chat()           │
│ 调度     │  │                  │
└────┬─────┘  └───────┬──────────┘
     │                │
     ▼                ▼
┌──────────┐  ┌──────────────────┐
│ 节点执行  │  │ LLMManager       │
│ call_node │  │ chat_completion  │
└────┬─────┘  └───────┬──────────┘
     │                │
     ▼                ▼
┌─────────────────────────────────┐
│  统一响应 UnifiedChatResponse   │
│  core/unified_response.py       │
│                                  │
│  {success, response, intent,    │
│   confidence, mode, suggestions,│
│   data, error, session_id,      │
│   model, timestamp}             │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  对话记忆                        │
│  记录 assistant 回复             │
└──────────┬──────────────────────┘
           │
           ▼
       返回前端
```

---

## 2. 详细流程

### 2.1 API 入口

| 端点 | 文件 | 说明 |
|------|------|------|
| `POST /api/v1/chat` | `core/api_routes.py` | **主入口**，所有 UI 统一调用 |
| `POST /api/v1/dashboard/chat` | `dashboard/backend/main.py` | Dashboard 独立入口 |

两个端点都返回 `UnifiedChatResponse` 格式。

### 2.2 对话记忆

**模块:** `core/ai_intent.py` → `ConversationMemory`

```python
from core.ai_intent import get_conversation_memory
memory = get_conversation_memory()

# 记录用户消息
await memory.add_turn(session_id, "user", message)

# 获取上下文
context = await memory.get_context(session_id, max_turns=10)
```

- 短期记忆：内存中保留最近 20 轮
- 长期记忆：通过 Redis / 向量数据库持久化（可选）
- 用户偏好：自动学习用户的常用意图

### 2.3 意图解析

**两级解析：**

1. **规则引擎** (`IntentParser._parse_by_rules`)
   - 关键词匹配，延迟 < 1ms
   - 置信度 = 0.3 + 命中关键词数 × 0.2

2. **LLM 引擎** (`IntentParser._parse_by_llm`)
   - 需要 `OPENAI_API_KEY` 或 `DEEPSEEK_API_KEY`
   - 仅在规则引擎置信度 < 0.7 时调用
   - 返回结构化 JSON: `{intent, command, targets, params, confidence}`

**意图类型：**

| 意图 | 命令 | 目标节点 |
|------|------|---------|
| task_manage | task_manage | Node_02_Tasker |
| device_control | device_control | device |
| file_operation | file_operation | Node_06_Filesystem |
| search | search | Node_20_Qdrant |
| ocr | ocr | Node_15_OCR |
| system_status | system_status | system |
| chat | chat | llm |
| network | network | Node_82_NetworkGuard |
| code | code_execute | Node_117_OpenCode |

### 2.4 操作指令分流 (Agent ReAct)

**模块:** `core/api_routes.py` → `_handle_agent_action()`

```
用户消息 → LLM 规划 (plan_and_execute)
    │
    ├─ Step 1: 识别需要调用的节点
    ├─ Step 2: 构建参数
    ├─ Step 3: 执行节点 (node_executor)
    │   ├─ 本地节点: fusion_entry.py
    │   └─ 远程设备: WebSocket
    └─ Step N: 汇总结果
```

- 最多 5 轮迭代 (`max_turns=5`)
- LLM 不可用时自动降级到纯聊天

### 2.5 纯聊天分流

**模块:** `core/api_routes.py` → `_handle_pure_chat()`

```
用户消息 + 上下文 → LLMManager.chat_completion()
    │
    ├─ 尝试 Provider 1 (如 OpenAI)
    ├─ 尝试 Provider 2 (如 DeepSeek)
    └─ 所有 Provider 失败 → 返回配置提示
```

### 2.6 节点调用

**模块:** `core/galaxy_core.py` → `call_node()`

```
call_node(node_id, action, params)
    │
    ├─ 方式一: POST {endpoint}/mcp/call  (timeout=10s)
    │   └─ 成功 (200) → 返回结果
    │
    └─ 方式二: POST {endpoint}/{action}  (timeout=10s)
        └─ raise_for_status() → 返回结果
```

### 2.7 统一响应

所有端点统一返回 `UnifiedChatResponse`:

```json
{
  "success": true,
  "response": "已执行: 打开微信",
  "intent": "device_control",
  "confidence": 0.9,
  "mode": "agent_react",
  "suggestions": ["查看设备状态", "截取屏幕"],
  "data": {"steps": [...]},
  "error": "",
  "session_id": "device-001",
  "model": "gpt-4o-mini",
  "timestamp": "2026-03-06T10:30:00"
}
```

---

## 3. 关键模块索引

| 模块 | 文件路径 | 职责 |
|------|---------|------|
| API 路由 | `core/api_routes.py` | 所有 REST API 和 WebSocket |
| Dashboard 后端 | `dashboard/backend/main.py` | Dashboard 专用 API |
| 意图解析 | `core/ai_intent.py` | 规则 + LLM 意图理解 |
| 对话记忆 | `core/ai_intent.py` | 上下文管理 + 用户偏好 |
| 节点核心 | `core/galaxy_core.py` | 节点注册 + 调用 |
| LLM 管理 | `core/llm_manager.py` | 多 Provider LLM 调用 |
| 统一响应 | `core/unified_response.py` | 响应格式定义 |
| 安全执行 | `core/safe_executor.py` | 代码沙箱执行 |
| 智能推荐 | `core/ai_intent.py` | 基于偏好的推荐 |
