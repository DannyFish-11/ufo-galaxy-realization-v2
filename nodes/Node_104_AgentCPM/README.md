# Node 104: AgentCPM Integration

AgentCPM 集成节点 - 深度搜索和研究报告生成

## 功能特性

### AgentCPM-Explore（深度搜索）

- ✅ 100+ 轮交互的深度搜索
- ✅ 多源交叉验证
- ✅ 动态策略调整
- ✅ 工具调用支持

### AgentCPM-Report（研究报告）

- ✅ 自动生成研究报告
- ✅ 深度信息挖掘
- ✅ 逻辑严谨的长文
- ✅ 多种输出格式

### 核心功能

- ✅ 异步任务处理
- ✅ 进度跟踪
- ✅ 自动保存到 Memos
- ✅ RESTful API 接口
- ✅ Mock 模式（无需 AgentCPM API 也可演示）

---

## 快速开始

### 1. 安装依赖

```bash
cd nodes/Node_104_AgentCPM
pip install fastapi uvicorn httpx pydantic
```

### 2. 配置环境变量

```bash
# AgentCPM API 配置（可选，未配置时使用 Mock 模式）
export AGENTCPM_API_KEY=your_api_key
export AGENTCPM_BASE_URL=https://api.agentcpm.com/v1

# AgentDock 配置（可选）
export AGENTDOCK_URL=http://localhost:8000

# Memos 配置（可选）
export MEMOS_URL=http://localhost:5230
export MEMOS_TOKEN=your_access_token

# 端口配置
export NODE_104_PORT=8104
```

### 3. 启动节点

```bash
python main.py
```

服务将在 `http://localhost:8104` 启动。

---

## API 使用

### 健康检查

```bash
curl http://localhost:8104/health
```

**响应**:
```json
{
  "status": "healthy",
  "node": "Node_104_AgentCPM",
  "version": "1.0.0",
  "agentcpm_configured": false,
  "agentdock_url": "http://localhost:8000",
  "memos_configured": true
}
```

### 深度搜索

```bash
curl -X POST http://localhost:8104/deep_search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "量子机器学习的最新进展",
    "max_turns": 100,
    "tools": ["search", "arxiv", "calculator"],
    "save_to_memos": true
  }'
```

**响应**:
```json
{
  "success": true,
  "task_id": "search_20260122120000",
  "message": "深度搜索任务已创建"
}
```

### 深度研究

```bash
curl -X POST http://localhost:8104/deep_research \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "量子计算在机器学习中的应用",
    "depth": "deep",
    "output_format": "markdown",
    "save_to_memos": true
  }'
```

**响应**:
```json
{
  "success": true,
  "task_id": "research_20260122120100",
  "message": "深度研究任务已创建"
}
```

### 查询任务状态

```bash
curl http://localhost:8104/task/search_20260122120000
```

**响应**:
```json
{
  "task_id": "search_20260122120000",
  "type": "deep_search",
  "query": "量子机器学习的最新进展",
  "status": "completed",
  "progress": 100,
  "result": {
    "id": "search_20260122120000",
    "model": "agentcpm-explore",
    "choices": [
      {
        "message": {
          "role": "assistant",
          "content": "# 深度搜索结果..."
        }
      }
    ]
  },
  "created_at": "2026-01-22T12:00:00"
}
```

### 列出所有任务

```bash
curl http://localhost:8104/tasks
```

---

## 部署 AgentCPM（可选）

### 方法 1：使用 Docker（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/OpenBMB/AgentCPM.git
cd AgentCPM/AgentCPM-Explore

# 2. 拉取 Docker 镜像
docker pull yuyangfu/agenttoleap-eval:v2.0

# 3. 启动容器
docker run -dit --name agenttoleap --gpus all --network host \
  -v $(pwd):/workspace yuyangfu/agenttoleap-eval:v2.0

# 4. 进入容器
docker exec -it agenttoleap /bin/bash
cd /workspace
```

### 方法 2：部署 AgentDock

```bash
# 1. 进入 AgentDock 目录
cd AgentCPM/AgentCPM-Explore/AgentDock

# 2. 启动服务
docker compose up -d

# 3. 验证服务
curl http://localhost:8000/health
```

### 方法 3：使用 API（最简单）

如果您有 AgentCPM 的 API 访问权限，只需配置环境变量：

```bash
export AGENTCPM_API_KEY=your_api_key
export AGENTCPM_BASE_URL=https://api.agentcpm.com/v1
```

---

## Mock 模式

如果未配置 AgentCPM API，Node_104 会自动使用 Mock 模式，提供演示功能：

- ✅ 模拟深度搜索过程
- ✅ 生成示例研究报告
- ✅ 完整的 API 响应格式
- ✅ 自动保存到 Memos

**Mock 模式的优势**:
- 无需部署 AgentCPM
- 快速体验功能
- 用于开发和测试

**Mock 模式的限制**:
- 不是真实的深度搜索
- 报告内容是模板
- 无法调用真实工具

---

## 使用场景

### 场景 1：学术研究

```bash
# 深度搜索某个主题
curl -X POST http://localhost:8104/deep_search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Transformer 架构的最新改进",
    "max_turns": 100,
    "tools": ["search", "arxiv", "semantic_scholar"],
    "save_to_memos": true
  }'

# 生成研究报告
curl -X POST http://localhost:8104/deep_research \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "Transformer 架构综述",
    "depth": "deep",
    "output_format": "markdown",
    "save_to_memos": true
  }'
```

### 场景 2：技术调研

```bash
# 调研某项技术
curl -X POST http://localhost:8104/deep_research \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "Rust 语言在系统编程中的应用",
    "depth": "medium",
    "output_format": "markdown",
    "save_to_memos": true
  }'
```

### 场景 3：市场分析

```bash
# 生成市场分析报告
curl -X POST http://localhost:8104/deep_research \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "AI 芯片市场现状与趋势",
    "depth": "deep",
    "output_format": "markdown",
    "save_to_memos": true
  }'
```

---

## 与其他节点集成

### 与 Node_97（学术搜索）集成

```python
# 1. 使用 Node_97 搜索论文
papers = requests.post("http://localhost:8097/search", json={
    "query": "quantum machine learning",
    "source": "all",
    "max_results": 10
}).json()

# 2. 使用 Node_104 生成综述报告
task = requests.post("http://localhost:8104/deep_research", json={
    "topic": "量子机器学习综述",
    "depth": "deep",
    "save_to_memos": true
}).json()

# 3. 查询任务状态
status = requests.get(f"http://localhost:8104/task/{task['task_id']}").json()
```

### 与 Node_80（记忆系统）集成

所有搜索结果和研究报告都会自动保存到 Memos（Node_80 的长期记忆层）。

---

## 性能指标

| 指标 | Mock 模式 | API 模式 |
|-----|----------|---------|
| **深度搜索延迟** | 5 秒 | 30-120 秒 |
| **报告生成延迟** | 10 秒 | 60-300 秒 |
| **并发任务** | 10+ | 5+ |
| **内存占用** | < 100 MB | < 500 MB |

---

## 故障排查

### 问题 1：AgentCPM API 调用失败

**症状**: `AgentCPM API 调用失败: 401 Unauthorized`

**解决**:
```bash
# 检查 API Key 是否正确
echo $AGENTCPM_API_KEY

# 重新设置
export AGENTCPM_API_KEY=your_correct_api_key
```

### 问题 2：任务一直处于 pending 状态

**症状**: 任务状态长时间不更新

**解决**:
- 检查后台任务是否正常运行
- 查看日志：`tail -f /var/log/node_104.log`
- 重启节点

### 问题 3：Memos 保存失败

**症状**: `未配置 MEMOS_TOKEN，跳过保存`

**解决**:
```bash
export MEMOS_TOKEN=your_access_token
```

---

## 未来计划

- [ ] 支持流式输出
- [ ] 添加任务队列（Redis）
- [ ] 实现任务优先级
- [ ] 添加任务取消功能
- [ ] 集成更多工具
- [ ] 支持自定义提示词
- [ ] 添加结果缓存

---

## 许可证

Apache-2.0

---

**Node 104** | AgentCPM Integration | UFO³ Galaxy
