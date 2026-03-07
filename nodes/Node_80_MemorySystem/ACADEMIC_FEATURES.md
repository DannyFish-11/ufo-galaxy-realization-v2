# Node 80: Academic Features

学术功能扩展 - 论文笔记管理和引用网络

## 新增功能

### 1. 论文笔记管理

- ✅ 结构化论文笔记存储
- ✅ 自动格式化 Markdown
- ✅ 标签分类
- ✅ 引用关系追踪

### 2. 学术搜索

- ✅ 全文搜索论文笔记
- ✅ 标签过滤
- ✅ 多条件组合搜索

### 3. 引用网络

- ✅ 追踪论文引用关系
- ✅ 发现被引用论文
- ✅ 构建引用图谱

### 4. 导出功能

- ✅ BibTeX 格式导出
- ✅ 批量导出
- ✅ 标准引用格式

---

## API 使用

### 保存论文笔记

```bash
curl -X POST http://localhost:8080/academic/paper_note \
  -H "Content-Type: application/json" \
  -d '{
    "paper_id": "arxiv:2401.12345",
    "title": "Quantum Machine Learning: A Survey",
    "authors": ["Alice Smith", "Bob Johnson"],
    "abstract": "This paper surveys...",
    "published_date": "2024-01-15",
    "url": "https://arxiv.org/abs/2401.12345",
    "source": "arXiv",
    "notes": "重要论文，需要深入阅读",
    "tags": ["量子计算", "机器学习", "综述"],
    "citations": ["arxiv:2301.11111", "arxiv:2302.22222"]
  }'
```

**响应**:
```json
{
  "success": true,
  "paper_id": "arxiv:2401.12345",
  "title": "Quantum Machine Learning: A Survey"
}
```

### 搜索论文笔记

```bash
# 搜索关键词
curl "http://localhost:8080/academic/paper_notes?query=quantum+machine+learning"

# 按标签搜索
curl "http://localhost:8080/academic/paper_notes?tags=量子计算,机器学习"

# 组合搜索
curl "http://localhost:8080/academic/paper_notes?query=transformer&tags=深度学习"
```

**响应**:
```json
{
  "query": "quantum machine learning",
  "tags": ["量子计算", "机器学习"],
  "count": 5,
  "papers": [
    {
      "id": "memo_123",
      "content": "# 📄 Quantum Machine Learning...",
      "createdAt": "2026-01-22T12:00:00Z"
    }
  ]
}
```

### 获取引用网络

```bash
curl http://localhost:8080/academic/citation_network/arxiv:2401.12345
```

**响应**:
```json
{
  "paper_id": "arxiv:2401.12345",
  "cited_by": ["arxiv:2405.11111", "arxiv:2406.22222"],
  "cites": ["arxiv:2301.11111", "arxiv:2302.22222"]
}
```

### 根据标签获取论文

```bash
curl http://localhost:8080/academic/papers_by_tag/量子计算
```

**响应**:
```json
{
  "tag": "量子计算",
  "count": 10,
  "papers": [...]
}
```

### 获取最近的论文

```bash
# 获取最近 7 天的论文
curl "http://localhost:8080/academic/recent_papers?days=7"
```

**响应**:
```json
{
  "days": 7,
  "count": 15,
  "papers": [...]
}
```

### 导出 BibTeX

```bash
curl -X POST http://localhost:8080/academic/export_bibtex \
  -H "Content-Type: application/json" \
  -d '["arxiv:2401.12345", "arxiv:2402.67890"]'
```

**响应**:
```json
{
  "count": 2,
  "bibtex": "@article{arxiv_2401_12345,\n  title = {Quantum Machine Learning},\n  author = {Alice Smith and Bob Johnson},\n  year = {2024},\n  url = {https://arxiv.org/abs/2401.12345}\n}\n\n@article{arxiv_2402_67890,\n  ..."
}
```

---

## 与其他节点集成

### 与 Node_97（学术搜索）集成

Node_97 搜索到的论文会自动保存到 Node_80：

```python
# Node_97 搜索论文
papers = requests.post("http://localhost:8097/search", json={
    "query": "quantum machine learning",
    "source": "arxiv",
    "max_results": 10,
    "save_to_memos": true  # 自动保存到 Node_80
}).json()

# 在 Node_80 中检索
saved_papers = requests.get(
    "http://localhost:8080/academic/paper_notes",
    params={"query": "quantum machine learning"}
).json()
```

### 与 Node_104（AgentCPM）集成

Node_104 生成的研究报告会自动保存到 Node_80：

```python
# Node_104 生成研究报告
task = requests.post("http://localhost:8104/deep_research", json={
    "topic": "量子机器学习综述",
    "depth": "deep",
    "save_to_memos": true  # 自动保存到 Node_80
}).json()

# 在 Node_80 中检索报告
reports = requests.get(
    "http://localhost:8080/academic/paper_notes",
    params={"query": "量子机器学习综述"}
).json()
```

---

## 论文笔记格式

### 标准格式

```markdown
# 📄 论文标题

## 基本信息

- **来源**: arXiv
- **ID**: `arxiv:2401.12345`
- **发布日期**: 2024-01-15
- **链接**: https://arxiv.org/abs/2401.12345

## 作者

Alice Smith, Bob Johnson

## 摘要

This paper surveys the recent advances in quantum machine learning...

## 我的笔记

重要论文，需要深入阅读。

关键点：
1. 量子优势
2. 混合算法
3. 应用场景

## 引用文献

- `arxiv:2301.11111`
- `arxiv:2302.22222`

## 标签

#量子计算 #机器学习 #综述 #arXiv

---
*保存时间: 2026-01-22 12:00:00*
*由 UFO³ Galaxy Node_80 (Academic Extension) 管理*
```

---

## 使用场景

### 场景 1：文献综述

1. 使用 Node_97 搜索相关论文
2. 论文自动保存到 Node_80
3. 在 Node_80 中添加笔记和标签
4. 使用 Node_104 生成综述报告
5. 导出 BibTeX 用于论文写作

### 场景 2：追踪研究领域

1. 定期使用 Node_97 搜索最新论文
2. 自动保存到 Node_80
3. 使用标签分类
4. 查看引用网络
5. 发现重要论文

### 场景 3：论文写作

1. 在 Node_80 中搜索相关论文
2. 查看引用网络
3. 导出 BibTeX
4. 在论文中引用

---

## 配置要求

### 必需

- Memos 服务（http://localhost:5230）
- Memos Access Token

### 可选

- Node_97（学术搜索）
- Node_104（AgentCPM）

---

## 未来计划

- [ ] 可视化引用网络
- [x] 自动提取论文关键词
- [x] 论文相似度计算
- [x] 推荐相关论文
- [ ] 导出为其他格式（EndNote、Zotero）
- [ ] 集成 PDF 阅读器
- [x] 自动生成文献综述

---

**Node 80** | Academic Extension | UFO³ Galaxy
