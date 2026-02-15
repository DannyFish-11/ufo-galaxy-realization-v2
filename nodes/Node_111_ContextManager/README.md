# Node_111_ContextManager - 上下文管理引擎

## 📋 概述

Node_111_ContextManager 是 UFO³ Galaxy 系统的上下文管理引擎，提供跨会话持久化、用户画像学习和智能上下文检索功能。

### 核心功能

1. **会话管理** - 跨会话持久化对话历史（SQLite + Qdrant）
2. **用户画像** - 学习用户偏好（调用 Node_73 Learning）
3. **智能检索** - 基于语义的上下文搜索（调用 Node_20 Qdrant）
4. **知识积累** - 持续积累领域知识

---

## 🚀 快速开始

### 1. 安装依赖

```bash
cd nodes/Node_111_ContextManager
pip install -r requirements.txt
```

### 2. 启动服务

```bash
python server.py --port 8111
```

### 3. 测试 API

```bash
curl -X POST "http://localhost:8111/api/v1/context/save" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "session_001",
    "user_id": "user_123",
    "messages": [
      {"role": "user", "content": "你好"},
      {"role": "assistant", "content": "你好！有什么可以帮助你的吗？"}
    ]
  }'
```

---

## 📡 API 文档

### 1. 保存上下文

**端点**: `POST /api/v1/context/save`

**请求体**:
```json
{
  "session_id": "session_001",
  "user_id": "user_123",
  "messages": [
    {"role": "user", "content": "帮我搜索 AI 新闻"},
    {"role": "assistant", "content": "好的，我来帮你搜索..."}
  ],
  "metadata": {"topic": "AI news"}
}
```

---

### 2. 获取上下文

**端点**: `GET /api/v1/context/{session_id}?limit=10`

**响应**:
```json
{
  "session_id": "session_001",
  "user_id": "user_123",
  "messages": [...],
  "metadata": {...},
  "created_at": "2026-01-24T12:00:00",
  "last_active": "2026-01-24T12:30:00"
}
```

---

### 3. 搜索上下文

**端点**: `POST /api/v1/context/search`

**请求体**:
```json
{
  "query": "AI 新闻",
  "user_id": "user_123",
  "limit": 5
}
```

---

### 4. 获取用户画像

**端点**: `GET /api/v1/user/profile/{user_id}`

**响应**:
```json
{
  "user_id": "user_123",
  "preferences": {...},
  "learned_patterns": {...},
  "interaction_count": 150,
  "created_at": "2026-01-01T00:00:00",
  "updated_at": "2026-01-24T12:00:00"
}
```

---

## 🔗 依赖节点

| 节点 | 用途 | 端口 |
| :--- | :--- | :---: |
| **Node_13_SQLite** | 本地数据库 | 8013 |
| **Node_20_Qdrant** | 向量搜索 | 8020 |
| **Node_73_Learning** | 用户偏好学习 | 8073 |
| **Node_100_MemorySystem** | 长期记忆 | 8100 |

---

## 📊 工作流程

```
保存上下文
    ↓
[存储到 SQLite] → Node_13
    ↓
[生成嵌入] → Node_20 (Qdrant)
    ↓
[学习偏好] → Node_73 (Learning)
    ↓
[更新用户画像]
```

---

## 🎯 预期效果

| 指标 | 提升幅度 |
| :--- | :---: |
| **任务理解准确度** | +50% |
| **用户输入** | -30% |
| **上下文相关性** | +60% |

---

## 📝 配置

编辑 `server.py` 中的 `context_manager_config`：

```python
context_manager_config = {
    "node_13_url": "http://localhost:8013",
    "node_20_url": "http://localhost:8020",
    "node_73_url": "http://localhost:8073",
    "node_100_url": "http://localhost:8100",
    "db_path": "context_manager.db"
}
```

---

**版本**: 1.0.0  
**最后更新**: 2026-01-24
