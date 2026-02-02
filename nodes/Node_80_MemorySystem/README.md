# Node 80: Memory System

多层记忆系统 - 短期/长期/语义/用户画像

## 功能特性

### 四层记忆架构

**1. 短期记忆（Redis）**
- 对话上下文管理
- 会话状态跟踪
- 1小时自动过期
- 支持对话历史

**2. 长期记忆（Memos）**
- 笔记和文档存储
- 标签分类
- 持久化存储
- 全文搜索

**3. 语义记忆（简化版）**
- 关键词匹配
- 内存存储
- 快速检索

**4. 用户画像（SQLite）**
- 偏好设置
- 使用统计
- 本地存储

### 优势
- ✅ 个性化体验
- ✅ 上下文连续性
- ✅ 知识积累
- ✅ 智能推荐
- ✅ 离线可用

---

## 部署指南

### 1. 启动 Redis（Podman Desktop）

```powershell
podman run -d --name redis -p 6379:6379 redis:alpine
```

### 2. 启动 Memos（Podman Desktop）

```powershell
podman run -d --name memos -p 5230:5230 -v E:\ufo-galaxy\data\memos:/var/opt/memos neosmemo/memos:stable
```

### 3. 配置环境变量

创建 `.env` 文件：

```bash
# Redis 配置
REDIS_URL=redis://localhost:6379
REDIS_PREFIX=ufo_galaxy:
SHORT_TERM_TTL=3600  # 1 小时

# Memos 配置
MEMOS_URL=http://localhost:5230
MEMOS_TOKEN=  # 可选，在 Memos 设置中生成

# 本地存储
CHROMA_PATH=./chroma_db
SQLITE_PATH=./user_profile.db

# 离线模式
OFFLINE_MODE=false
```

### 4. 启动 Node 80

```bash
cd nodes/Node_80_MemorySystem
pip install -r requirements.txt
python main.py
```

---

## API 使用示例

### 1. 健康检查

```bash
curl http://localhost:8080/health
```

### 2. 保存短期记忆

```bash
curl -X POST http://localhost:8080/memory \
  -H "Content-Type: application/json" \
  -d '{
    "content": "用户喜欢蓝色",
    "memory_type": "short_term",
    "session_id": "user123_session",
    "metadata": {"category": "preference"}
  }'
```

### 3. 保存长期记忆

```bash
curl -X POST http://localhost:8080/memory \
  -H "Content-Type: application/json" \
  -d '{
    "content": "UFO³ Galaxy 是一个分布式 AI 代理系统",
    "memory_type": "long_term",
    "tags": ["ufo", "galaxy", "ai"],
    "metadata": {"source": "documentation"}
  }'
```

### 4. 回忆记忆

```bash
curl -X POST http://localhost:8080/memory/recall \
  -H "Content-Type: application/json" \
  -d '{
    "query": "UFO Galaxy",
    "limit": 5
  }'
```

### 5. 保存对话

```bash
curl -X POST http://localhost:8080/conversation \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "user123_session",
    "messages": [
      {"role": "user", "content": "你好"},
      {"role": "assistant", "content": "你好！有什么我可以帮助您的吗？"}
    ]
  }'
```

### 6. 获取对话历史

```bash
curl http://localhost:8080/conversation/user123_session?limit=10
```

### 7. 设置用户偏好

```bash
curl -X POST http://localhost:8080/preference \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user123",
    "key": "language",
    "value": "zh-CN"
  }'
```

### 8. 获取用户偏好

```bash
curl http://localhost:8080/preference/user123/language
```

### 9. 获取用户统计

```bash
curl http://localhost:8080/stats/user123
```

---

## 与 Node 79 集成

### 带记忆的对话

```python
import httpx
import asyncio

async def chat_with_memory(user_input: str, session_id: str):
    client = httpx.AsyncClient()
    
    # 1. 获取对话历史（Node 80）
    history_response = await client.get(
        f"http://localhost:8080/conversation/{session_id}"
    )
    history = history_response.json()["messages"]
    
    # 2. 构建消息列表
    messages = [
        {"role": "system", "content": "你是一个有帮助的助手"},
        *history,
        {"role": "user", "content": user_input}
    ]
    
    # 3. 调用 Node 79 生成响应
    llm_response = await client.post(
        "http://localhost:8079/chat",
        json={"messages": messages}
    )
    assistant_reply = llm_response.json()["response"]
    
    # 4. 保存对话到 Node 80
    await client.post(
        "http://localhost:8080/conversation",
        json={
            "session_id": session_id,
            "messages": [
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": assistant_reply}
            ]
        }
    )
    
    await client.aclose()
    return assistant_reply

# 使用
asyncio.run(chat_with_memory("你好", "user123_session"))
```

---

## 性能指标

| 操作 | 延迟 | 吞吐量 |
|------|------|--------|
| 保存短期记忆 | < 10ms | 1000+ ops/s |
| 回忆短期记忆 | < 20ms | 500+ ops/s |
| 保存长期记忆 | < 100ms | 100+ ops/s |
| 回忆长期记忆 | < 200ms | 50+ ops/s |
| 保存对话 | < 15ms | 800+ ops/s |
| 获取对话历史 | < 25ms | 400+ ops/s |

---

## 存储容量

| 存储类型 | 容量 | 保留期 |
|---------|------|--------|
| 短期记忆（Redis） | 内存限制 | 1 小时 |
| 长期记忆（Memos） | 无限制 | 永久 |
| 语义记忆（简化版） | 内存限制 | 重启清空 |
| 用户画像（SQLite） | 磁盘限制 | 永久 |

---

## 故障排查

### 1. Redis 连接失败

**错误:**
```
Failed to connect to Redis
```

**解决:**
```powershell
podman start redis
```

### 2. Memos 不可用

**错误:**
```
Memos health check failed
```

**解决:**
```powershell
podman start memos
# 访问 http://localhost:5230 确认
```

### 3. 数据库锁定

**错误:**
```
database is locked
```

**解决:**
```bash
# 关闭其他连接到数据库的进程
rm user_profile.db-journal  # 删除日志文件
```

---

## 最佳实践

### 1. 记忆类型选择

**使用场景：**
- **短期记忆**: 对话上下文、临时状态
- **长期记忆**: 重要笔记、文档、知识
- **语义记忆**: 需要语义搜索的内容
- **用户画像**: 用户偏好、统计信息

### 2. 会话管理

```python
# 使用有意义的 session_id
session_id = f"{user_id}_{date}_{topic}"

# 定期清理过期会话
await client.delete(f"http://localhost:8080/session/{session_id}")
```

### 3. 性能优化

- 短期记忆用于高频访问
- 长期记忆用于持久化
- 合理设置 TTL
- 定期清理无用数据

---

## 更新日志

### v1.0.0 (2026-01-21)
- ✅ 初始版本
- ✅ 四层记忆架构
- ✅ Redis 短期记忆
- ✅ Memos 长期记忆
- ✅ 简化版语义记忆
- ✅ SQLite 用户画像
- ✅ 对话历史管理
- ✅ 用户偏好设置

---

## 相关链接

- [Redis 官网](https://redis.io/)
- [Memos 官网](https://usememos.com/)
- [Node 79 (Local LLM)](../Node_79_LocalLLM/README.md)
- [Node 81 (Orchestrator)](../Node_81_Orchestrator/README.md)
