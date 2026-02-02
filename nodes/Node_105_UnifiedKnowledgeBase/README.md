# Node 105: Unified Knowledge Base

统一知识库管理系统

---

## 功能

### 1. 统一数据源

支持从多种来源添加知识：

- **本地文件**: PDF, MD, DOCX, TXT, 代码文件
- **网页 URL**: 自动抓取网页内容
- **GitHub 仓库**: 自动克隆并索引代码文件
- **Memos 笔记**: 从 Memos 系统导入笔记

### 2. 增强 RAG

- **多种搜索方式**: 关键词搜索、向量搜索、混合搜索
- **Mock 模式**: 无需安装向量数据库即可使用
- **真实模式**: 支持 ChromaDB、Faiss、Pinecone（需配置）

### 3. 代码知识库

- 自动解析代码文件
- 支持多种编程语言（Python, JavaScript, Java, C++, Go, Rust）
- 实现代码问答和语义搜索

### 4. RAG 问答

- 基于检索的问答
- 自动引用来源
- 支持 LLM 集成（可选）

---

## 安装

### 必需依赖

```bash
pip install fastapi uvicorn httpx pydantic
```

### 可选依赖（真实模式）

```bash
# 向量数据库
pip install chromadb

# Embedding 模型
pip install sentence-transformers
```

---

## 使用

### 启动服务

```bash
cd nodes/Node_105_UnifiedKnowledgeBase
python main.py
```

服务将在 `http://localhost:8105` 启动。

### API 端点

#### 1. 健康检查

```bash
curl http://localhost:8105/health
```

#### 2. 添加知识

**从本地文件**:
```bash
curl -X POST http://localhost:8105/add \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "file",
    "source": "/path/to/document.md",
    "metadata": {"category": "documentation"}
  }'
```

**从 URL**:
```bash
curl -X POST http://localhost:8105/add \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "url",
    "source": "https://example.com/article",
    "metadata": {"category": "article"}
  }'
```

**从 GitHub 仓库**:
```bash
curl -X POST http://localhost:8105/add \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "github",
    "source": "https://github.com/username/repo.git",
    "metadata": {"category": "code"}
  }'
```

**从 Memos**:
```bash
curl -X POST http://localhost:8105/add \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "memos",
    "source": "http://localhost:5230",
    "metadata": {"tag": "research"}
  }'
```

**直接添加文本**:
```bash
curl -X POST http://localhost:8105/add \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "text",
    "content": "这是一段知识内容",
    "metadata": {"category": "note"}
  }'
```

#### 3. 搜索知识

**关键词搜索**:
```bash
curl -X POST http://localhost:8105/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "量子计算",
    "top_k": 5,
    "search_type": "keyword"
  }'
```

**混合搜索**:
```bash
curl -X POST http://localhost:8105/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "如何实现 RAG",
    "top_k": 5,
    "search_type": "hybrid"
  }'
```

#### 4. RAG 问答

```bash
curl -X POST http://localhost:8105/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "什么是量子纠缠？",
    "top_k": 3
  }'
```

#### 5. 统计信息

```bash
curl http://localhost:8105/stats
```

#### 6. 清空知识库

```bash
curl -X DELETE http://localhost:8105/clear
```

---

## 配置

### Mock 模式（默认）

无需任何配置，开箱即用。

**特点**:
- 不需要安装向量数据库
- 向量搜索退化为关键词搜索
- 适合快速测试和演示

### 真实模式

需要安装向量数据库和 Embedding 模型。

**步骤**:

1. 安装依赖:
   ```bash
   pip install chromadb sentence-transformers
   ```

2. 修改 `main.py` 中的 `use_mock = False`

3. 重启服务

---

## 使用场景

### 1. 文档知识库

将所有项目文档添加到知识库，实现快速检索和问答。

```bash
# 添加文档
curl -X POST http://localhost:8105/add \
  -H "Content-Type: application/json" \
  -d '{"source_type": "file", "source": "/docs/README.md"}'

# 搜索文档
curl -X POST http://localhost:8105/search \
  -H "Content-Type: application/json" \
  -d '{"query": "如何部署", "top_k": 5}'
```

### 2. 代码知识库

将 GitHub 仓库作为知识库，实现代码问答。

```bash
# 添加 GitHub 仓库
curl -X POST http://localhost:8105/add \
  -H "Content-Type: application/json" \
  -d '{"source_type": "github", "source": "https://github.com/user/repo.git"}'

# 搜索代码
curl -X POST http://localhost:8105/search \
  -H "Content-Type: application/json" \
  -d '{"query": "authentication function", "top_k": 5}'
```

### 3. 网页知识库

将网页内容添加到知识库。

```bash
# 添加网页
curl -X POST http://localhost:8105/add \
  -H "Content-Type: application/json" \
  -d '{"source_type": "url", "source": "https://example.com/article"}'

# 搜索网页内容
curl -X POST http://localhost:8105/search \
  -H "Content-Type: application/json" \
  -d '{"query": "关键词", "top_k": 5}'
```

### 4. Memos 集成

将 Memos 笔记导入知识库。

```bash
# 导入 Memos 笔记
curl -X POST http://localhost:8105/add \
  -H "Content-Type: application/json" \
  -d '{"source_type": "memos", "source": "http://localhost:5230"}'

# 搜索笔记
curl -X POST http://localhost:8105/search \
  -H "Content-Type: application/json" \
  -d '{"query": "研究笔记", "top_k": 5}'
```

---

## 与其他节点集成

### 与 Node_97 (Academic Search) 集成

自动将搜索到的论文添加到知识库：

```python
# 在 Node_97 中调用 Node_105
import httpx

async def save_to_kb(paper_content, paper_url):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8105/add",
            json={
                "source_type": "text",
                "content": paper_content,
                "metadata": {"source": "arxiv", "url": paper_url}
            }
        )
        return response.json()
```

### 与 Node_104 (AgentCPM) 集成

将研究报告添加到知识库：

```python
# 在 Node_104 中调用 Node_105
async def save_report_to_kb(report_content):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8105/add",
            json={
                "source_type": "text",
                "content": report_content,
                "metadata": {"source": "agentcpm", "type": "report"}
            }
        )
        return response.json()
```

### 与 Node_80 (Memory System) 集成

从 Memos 导入笔记：

```bash
curl -X POST http://localhost:8105/add \
  -H "Content-Type: application/json" \
  -d '{"source_type": "memos", "source": "http://localhost:8080"}'
```

---

## 故障排查

### 问题 1: 无法克隆 GitHub 仓库

**原因**: 没有安装 Git 或网络问题。

**解决**:
```bash
# 检查 Git 是否安装
git --version

# 如果未安装
sudo apt install git  # Ubuntu/Debian
brew install git      # macOS
```

### 问题 2: 无法抓取网页

**原因**: 网络问题或网站反爬虫。

**解决**: 检查网络连接，或尝试使用代理。

### 问题 3: 知识库文件过大

**原因**: 添加了大量知识。

**解决**: 定期清理不需要的知识，或使用真实的向量数据库（支持更高效的存储）。

---

## 技术细节

### 数据存储

- **Mock 模式**: 使用 JSON 文件存储（`./unified_kb/knowledge.json`）
- **真实模式**: 使用向量数据库（ChromaDB、Faiss、Pinecone）

### 搜索算法

- **关键词搜索**: 基于字符串匹配
- **向量搜索**: 基于 Embedding 相似度
- **混合搜索**: 合并关键词和向量搜索结果

### 代码解析

支持的编程语言：
- Python (`.py`)
- JavaScript (`.js`)
- Java (`.java`)
- C++ (`.cpp`, `.c`)
- Go (`.go`)
- Rust (`.rs`)
- Markdown (`.md`)

---

## 未来增强

1. **支持更多 Embedding 模型**: OpenAI, Cohere, HuggingFace
2. **支持更多向量数据库**: Weaviate, Milvus, Qdrant
3. **支持更多文档格式**: PDF, DOCX, PPTX
4. **支持增量更新**: 自动检测知识库变化
5. **支持权限管理**: 不同用户访问不同知识

---

## 许可证

MIT License

---

**Node 105** | Unified Knowledge Base | 2026-01-22
