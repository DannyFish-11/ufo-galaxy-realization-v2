# 向量知识库后端配置指南

UFO Galaxy 的知识库节点（Node_72、Node_105、enhancements/Node_52）和 AI 意图引擎
均通过 `core/vector_backend.py` 统一向量后端对外提供知识检索能力。

后端按优先级自动检测并降级：

```
KB_VECTOR_BACKEND=chroma  →  尝试 ChromaDB，失败 → local
KB_VECTOR_BACKEND=qdrant  →  尝试 Qdrant，失败 → local
KB_VECTOR_BACKEND=local   →  直接使用 Jaccard 关键词搜索（默认，无外部依赖）
```

---

## 环境变量一览

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `KB_VECTOR_BACKEND` | 向量引擎选择：`chroma` \| `qdrant` \| `local` | `local` |
| `QDRANT_URL` | Qdrant 服务器地址（仅 `qdrant` 模式使用） | 空（不启用） |
| `CHROMA_PERSIST_DIR` | ChromaDB 持久化目录（仅 `chroma` 模式使用） | `./chroma_db` |
| `KB_COLLECTION` | 向量集合 / 索引名称 | `ufo_galaxy_knowledge` |
| `KB_VECTOR_SIZE` | 向量维度，需与 Embedding 模型匹配 | `384` |

配置方式：在 `.env` 文件中设置（参见 `.env.example`）或直接设置系统环境变量。

---

## 选项 1：本地关键词搜索（默认，零依赖）

```bash
KB_VECTOR_BACKEND=local
```

无需安装任何额外依赖。使用 Jaccard 相似度对文档关键词进行匹配，适合开发环境和
资源受限场景。

---

## 选项 2：ChromaDB（本地向量存储）

```bash
KB_VECTOR_BACKEND=chroma
CHROMA_PERSIST_DIR=./chroma_db   # 可选，指定持久化目录
```

### 安装

```bash
pip install chromadb
```

ChromaDB 会在首次运行时自动初始化集合。数据持久化到 `CHROMA_PERSIST_DIR` 指定的目录。

> **降级说明**：若 `chromadb` 未安装或初始化失败，系统自动降级为 `local` 模式，
> 启动不会因此中断。

---

## 选项 3：Qdrant（分布式向量数据库）

```bash
KB_VECTOR_BACKEND=qdrant
QDRANT_URL=http://localhost:6333
```

### 快速启动（Docker）

```bash
docker run -p 6333:6333 qdrant/qdrant
```

### 安装客户端

```bash
pip install qdrant-client
```

Qdrant 模式下，文本搜索（`search(query)` 接口）降级为关键词搜索；
向量搜索（`search_vector(vector)` 接口）使用 Qdrant 余弦相似度。

> **降级说明**：若 `qdrant-client` 未安装、`QDRANT_URL` 未设置或服务不可达，
> 系统自动降级为 `local` 模式。

---

## 架构说明

```
core/vector_backend.py          ← 统一向量后端（含自动降级）
    ├── _LocalKeywordBackend    ← Jaccard 关键词搜索（零依赖）
    ├── _ChromaBackend          ← ChromaDB（可选，pip install chromadb）
    └── _QdrantBackend          ← Qdrant（可选，pip install qdrant-client）

nodes/Node_72_KnowledgeBase/knowledge_base_system.py    ← 使用统一后端
nodes/Node_105_UnifiedKnowledgeBase/main.py             ← 使用统一后端
enhancements/nodes/Node_52_KnowledgeBase/               ← 代理 Node_72 实现
core/ai_intent.py (SemanticSearch)                      ← 使用统一后端
```

各节点优先调用 `core.vector_backend.get_shared_backend()` 获取共享实例，
也可通过 `create_vector_backend(backend=...)` 创建独立实例。

---

## 运行测试

```bash
# 测试向量后端（本地模式，无需外部服务）
pytest tests/test_vector_backend.py -v

# 测试跨设备集成（AIP v3.0）
pytest tests/test_cross_device_integration.py -v
```
