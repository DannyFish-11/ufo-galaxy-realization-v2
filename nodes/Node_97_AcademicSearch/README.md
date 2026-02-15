# Node 97: Academic Search

学术搜索节点 - 多源学术论文检索系统

## 功能特性

### 支持的数据源

1. **arXiv** - 物理、数学、计算机科学预印本
2. **Semantic Scholar** - 跨学科学术搜索引擎
3. **PubMed** - 生物医学文献数据库

### 核心功能

- ✅ 多源并行搜索
- ✅ 自动保存到 Memos
- ✅ 论文元数据提取
- ✅ 标签自动分类
- ✅ RESTful API 接口

---

## 快速开始

### 1. 安装依赖

```bash
cd nodes/Node_97_AcademicSearch
pip install fastapi uvicorn httpx pydantic
```

### 2. 配置环境变量

```bash
# Memos 配置（可选）
export MEMOS_URL=http://localhost:5230
export MEMOS_TOKEN=your_access_token

# 端口配置
export NODE_97_PORT=8097
```

### 3. 启动节点

```bash
python main.py
```

服务将在 `http://localhost:8097` 启动。

---

## API 使用

### 健康检查

```bash
curl http://localhost:8097/health
```

**响应**:
```json
{
  "status": "healthy",
  "node": "Node_97_AcademicSearch",
  "version": "1.0.0",
  "memos_configured": true
}
```

### 搜索论文

```bash
curl -X POST http://localhost:8097/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "quantum machine learning",
    "source": "all",
    "max_results": 10,
    "save_to_memos": true
  }'
```

**参数说明**:
- `query`: 搜索关键词
- `source`: 数据源（`all`, `arxiv`, `semantic_scholar`, `pubmed`）
- `max_results`: 每个数据源的最大结果数
- `save_to_memos`: 是否自动保存到 Memos

**响应**:
```json
{
  "success": true,
  "query": "quantum machine learning",
  "source": "all",
  "total_results": 25,
  "papers": [
    {
      "paper_id": "2401.12345",
      "title": "Quantum Machine Learning: A Survey",
      "authors": ["Alice Smith", "Bob Johnson"],
      "abstract": "This paper surveys...",
      "published_date": "2024-01-15",
      "url": "https://arxiv.org/abs/2401.12345",
      "source": "arXiv",
      "tags": ["arXiv", "cs.LG", "quant-ph"]
    }
  ]
}
```

### 保存论文笔记

```bash
curl -X POST http://localhost:8097/save_note \
  -H "Content-Type: application/json" \
  -d '{
    "paper_id": "arxiv:2401.12345",
    "title": "Quantum Machine Learning",
    "authors": ["Alice Smith"],
    "abstract": "This paper...",
    "published_date": "2024-01-15",
    "url": "https://arxiv.org/abs/2401.12345",
    "source": "arXiv",
    "notes": "重要论文，需要深入阅读",
    "tags": ["量子计算", "机器学习"]
  }'
```

---

## 数据源详情

### arXiv

**特点**:
- 免费开放
- 无需 API Key
- 实时更新
- 覆盖物理、数学、计算机科学

**限制**:
- 每次请求最多 2000 条结果
- 建议请求间隔 3 秒

### Semantic Scholar

**特点**:
- 跨学科覆盖
- 引用关系
- 免费 API
- 无需注册

**限制**:
- 每分钟 100 次请求
- 每次最多 100 条结果

### PubMed

**特点**:
- 生物医学领域权威
- 免费开放
- 数据质量高

**限制**:
- 每秒 3 次请求
- 需要两次 API 调用（搜索 + 获取详情）

---

## 与 Memos 集成

### 自动保存格式

论文会以以下格式保存到 Memos:

```markdown
# 📄 论文标题

**来源**: arXiv  
**ID**: 2401.12345  
**发布日期**: 2024-01-15  
**链接**: https://arxiv.org/abs/2401.12345

## 作者

Alice Smith, Bob Johnson

## 摘要

This paper surveys the recent advances in quantum machine learning...

## 标签

#arXiv #cs.LG #quant-ph #量子计算 #机器学习

---
*由 UFO³ Galaxy Node_97 自动保存于 2026-01-22 12:00:00*
```

### 配置 Memos Token

1. 访问 Memos（`http://localhost:5230`）
2. 进入 **设置 → API Tokens**
3. 创建新 Token
4. 设置环境变量：`export MEMOS_TOKEN=your_token`

---

## 使用场景

### 场景 1：文献综述

```bash
# 搜索特定主题的论文
curl -X POST http://localhost:8097/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "transformer architecture",
    "source": "arxiv",
    "max_results": 50,
    "save_to_memos": true
  }'
```

### 场景 2：跟踪最新研究

```bash
# 每天自动搜索并保存
crontab -e

# 添加定时任务（每天上午 9 点）
0 9 * * * curl -X POST http://localhost:8097/search -H "Content-Type: application/json" -d '{"query":"quantum computing","source":"all","max_results":10,"save_to_memos":true}'
```

### 场景 3：多学科交叉研究

```bash
# 同时搜索多个数据源
curl -X POST http://localhost:8097/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "AI in healthcare",
    "source": "all",
    "max_results": 20,
    "save_to_memos": true
  }'
```

---

## 故障排查

### 问题 1：Memos 保存失败

**症状**: `未配置 MEMOS_TOKEN，跳过保存`

**解决**:
```bash
export MEMOS_TOKEN=your_access_token
```

### 问题 2：arXiv 搜索超时

**症状**: `arXiv 搜索失败: timeout`

**解决**:
- 检查网络连接
- 减少 `max_results`
- 增加超时时间（修改代码中的 `timeout=30.0`）

### 问题 3：Semantic Scholar 限流

**症状**: `429 Too Many Requests`

**解决**:
- 减少请求频率
- 等待 1 分钟后重试

---

## 扩展功能

### 添加新数据源

1. 在 `main.py` 中添加搜索函数
2. 在 `/search` 端点中调用
3. 更新 `SearchRequest.source` 枚举

### 自定义保存格式

修改 `save_to_memos()` 函数中的 Markdown 模板。

### 添加引用关系

集成 Semantic Scholar 的引用 API，构建论文引用网络。

---

## 性能指标

| 指标 | 值 |
|-----|---|
| **单次搜索延迟** | 2-5 秒 |
| **并发请求** | 10+ |
| **内存占用** | < 100 MB |
| **CPU 占用** | < 5% |

---

## 未来计划

- [ ] 添加 Google Scholar 支持
- [ ] 添加 IEEE Xplore 支持
- [ ] 实现论文全文下载
- [ ] 实现引用网络可视化
- [ ] 集成 AgentCPM 进行深度分析

---

## 许可证

Apache-2.0

---

**Node 97** | Academic Search | UFO³ Galaxy
