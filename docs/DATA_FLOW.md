# UFO Galaxy 系统数据流文档

## 概述

本文档描述用户消息从输入到最终输出的完整流程。

## 架构层次

```
┌─────────────────────────────────────────────────────────┐
│  UI 层 (Dashboard / Android / Windows 客户端)           │
├─────────────────────────────────────────────────────────┤
│  API 层 (core/api_routes.py)                            │
│    ├─ /api/v1/chat          - 统一对话入口              │
│    ├─ /api/v1/dashboard/chat - Dashboard 专用入口       │
│    ├─ /api/v1/ai/parse      - 意图解析                  │
│    └─ /ws/device            - WebSocket 设备连接        │
├─────────────────────────────────────────────────────────┤
│  意图引擎 (core/ai_intent.py)                           │
│    ├─ IntentParser          - 规则 + LLM 意图解析       │
│    ├─ ConversationMemory    - 对话记忆                   │
│    └─ SmartRecommender      - 智能推荐                   │
├─────────────────────────────────────────────────────────┤
│  核心层 (core/galaxy_core.py)                           │
│    ├─ call_node()           - HTTP 节点调用              │
│    ├─ send_device_command() - 设备命令路由               │
│    └─ smart_call()          - 通过 Router 路由           │
├─────────────────────────────────────────────────────────┤
│  节点层 (nodes/ — 128+ 节点)                            │
│    ├─ Node_04_Router        - 路由分发                   │
│    ├─ Node_33_ADB           - Android 控制               │
│    ├─ Node_50_Transformer   - NLU / 聊天                │
│    ├─ Node_70_AutonomousLearning - 学习                 │
│    ├─ Node_92_AutoControl   - 自动控制                   │
│    └─ Node_108_MetaCognition - 元认知                   │
└─────────────────────────────────────────────────────────┘
```

## 完整消息处理流程

### 1. 用户输入

用户通过以下方式发送消息：

- **Dashboard Web UI** → `POST /api/v1/dashboard/chat` 或 `POST /api/v1/chat`
- **Android App** → `POST /api/v1/chat`
- **Windows Client** → `POST /api/v1/chat`
- **WebSocket** → `ws/device` 连接

请求数据格式：
```json
{
  "message": "帮我打开微信",
  "device_id": "android_001",
  "context": []
}
```

### 2. 对话记忆加载

**模块**: `core/ai_intent.ConversationMemory`

```
用户消息 → get_conversation_memory()
         → memory.add_turn(session_id, "user", message)
         → memory.get_context(session_id, max_turns=10)
```

- 自动记录每一轮对话
- 返回最近 10 轮对话作为上下文
- 学习用户偏好 (frequent_intents)

### 3. 意图解析

**模块**: `core/ai_intent.IntentParser`

```
消息 → _parse_by_rules()          [规则引擎, < 1ms]
     ↓
     置信度 < 0.7?
     ├─ 是 → _parse_by_llm()      [LLM 语义理解, 需 API Key]
     └─ 否 → 使用规则结果
     ↓
     返回 ParsedIntent {
       intent: "device_control",
       command: "device_control",
       targets: ["device"],
       params: {...},
       confidence: 0.85,
       suggestions: ["查看设备状态", ...]
     }
```

**意图类型映射**:

| 意图类型 | 目标节点 | 关键词示例 |
|---------|---------|----------|
| task_manage | Node_02_Tasker | 任务, 待办, 计划 |
| device_control | device | 打开, 关闭, 截图 |
| file_operation | Node_06_Filesystem | 文件, 上传, 下载 |
| search | Node_20_Qdrant | 搜索, 查找, 查询 |
| ocr | Node_15_OCR | 识别, 文字, 图片 |
| system_status | system | 状态, 健康, 监控 |
| chat | llm | 聊天, 对话 |
| code | Node_117_OpenCode | 代码, 编程 |

### 4. 意图分流 (core/api_routes.py)

**两条路径**:

```
              ┌─ 操作指令 (_is_action_intent=true)
              │   + LLM 可用
意图分流 ─────┤   → _handle_agent_action()
              │   → ReAct Agent 调度 (LLM + tool_call)
              │   → node_executor() 执行节点
              │
              └─ 纯聊天 / LLM 不可用
                  → _handle_pure_chat()
                  → LLM 直接回复
```

### 5a. 操作指令处理 (Agent ReAct)

```
_handle_agent_action()
  → scheduler.plan_and_execute()
    → LLM 生成执行计划
    → node_executor(node_id, action, params)
      → 查找节点目录
      → 加载 fusion_entry.py
      → _execute_node() 执行
    → 格式化执行步骤
  → 记录到对话记忆
  → 返回结果
```

### 5b. 纯聊天处理

```
_handle_pure_chat()
  → llm_manager.chat_completion(messages)
  → 记录到对话记忆
  → 返回回复
```

### 6. 节点调用 (core/galaxy_core.py)

```
call_node(node_id, action, params)
  → HTTP POST http://localhost:{port}/mcp/call
    → 成功 (200): 返回结果
    → 失败: 尝试 HTTP POST /{action}
      → raise_for_status() 检查
      → 超时限制: 10 秒
```

### 7. 响应返回

**统一响应格式 (UnifiedChatResponse)**:

```json
{
  "success": true,
  "response": "已打开微信",
  "intent": "device_control",
  "confidence": 0.85,
  "suggestions": ["查看设备状态", "截取屏幕"],
  "data": {},
  "error": null,
  "timestamp": "2025-01-01T12:00:00"
}
```

## 关键模块文件索引

| 文件 | 职责 |
|------|------|
| `core/api_routes.py` | 所有 REST API 路由定义 |
| `core/galaxy_core.py` | 核心编排层，节点调用 |
| `core/ai_intent.py` | 意图解析 + 对话记忆 + 推荐 |
| `dashboard/backend/main.py` | Dashboard 后端 API |
| `core/api_manager.py` | API Key 管理 |
| `core/llm_manager.py` | LLM Provider 管理 |
| `nodes/common/mcp_adapter.py` | MCP 协议适配器 |

## 环境变量依赖

启用完整功能所需的环境变量详见 `.env.example`。核心变量：

- `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` — LLM 意图解析和聊天
- `KB_VECTOR_BACKEND` — 向量搜索后端
- `UFO_GALAXY_MODE` — 运行模式
