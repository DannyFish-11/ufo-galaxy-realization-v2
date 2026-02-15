# Node 106: GitHub Flow

GitHub 工作流自动化系统

---

## 功能

### 1. Issue 驱动开发

- 从任务自动创建 GitHub Issue
- 支持自定义标签
- 与任务管理系统（如 Memos）集成

### 2. 自动化代码生成

- 根据 Issue 内容生成代码
- 自动创建分支
- 生成提交信息

### 3. 自动化代码审查

- 自动审查 Pull Request
- 生成审查意见
- 发表评论

### 4. 代码知识库集成

- 将 GitHub 仓库索引到知识库（Node_105）
- 实现代码问答
- 支持代码搜索

---

## 安装

### 必需依赖

```bash
pip install fastapi uvicorn httpx pydantic
```

### 可选配置

#### GitHub Token

创建 GitHub Personal Access Token (PAT):

1. 访问 https://github.com/settings/tokens
2. 点击 "Generate new token (classic)"
3. 选择权限：
   - `repo` (完整仓库访问)
   - `workflow` (工作流)
4. 复制 Token

设置环境变量：

```bash
export GITHUB_TOKEN=your_github_token
```

---

## 使用

### 启动服务

```bash
cd nodes/Node_106_GitHubFlow
python main.py
```

服务将在 `http://localhost:8106` 启动。

### API 端点

#### 1. 健康检查

```bash
curl http://localhost:8106/health
```

#### 2. 创建 Issue

```bash
curl -X POST http://localhost:8106/create_issue \
  -H "Content-Type: application/json" \
  -d '{
    "repo": "username/repo",
    "title": "添加用户认证功能",
    "body": "需要实现基于 JWT 的用户认证系统",
    "labels": ["enhancement", "backend"]
  }'
```

#### 3. 根据 Issue 生成代码

```bash
curl -X POST http://localhost:8106/generate_code \
  -H "Content-Type: application/json" \
  -d '{
    "repo": "username/repo",
    "issue_number": 1,
    "branch_name": "feature/user-auth"
  }'
```

#### 4. 审查 Pull Request

```bash
curl -X POST http://localhost:8106/review_pr \
  -H "Content-Type: application/json" \
  -d '{
    "repo": "username/repo",
    "pr_number": 1
  }'
```

#### 5. 将仓库索引到知识库

```bash
curl -X POST http://localhost:8106/index_repo \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url": "https://github.com/username/repo.git"
  }'
```

#### 6. 完整工作流（Issue → PR）

```bash
curl "http://localhost:8106/workflow/issue_to_pr?repo=username/repo&issue_number=1"
```

---

## 工作流示例

### 场景 1: Issue 驱动开发

**步骤**:

1. 在 Memos 中创建任务：
   ```
   TODO: 添加用户认证功能
   - 实现 JWT 生成和验证
   - 添加登录和注册接口
   - 添加权限中间件
   ```

2. 调用 Node_106 创建 Issue：
   ```bash
   curl -X POST http://localhost:8106/create_issue \
     -H "Content-Type: application/json" \
     -d '{
       "repo": "myproject/backend",
       "title": "添加用户认证功能",
       "body": "实现 JWT 生成和验证...",
       "labels": ["enhancement"]
     }'
   ```

3. 根据 Issue 生成代码：
   ```bash
   curl -X POST http://localhost:8106/generate_code \
     -H "Content-Type: application/json" \
     -d '{
       "repo": "myproject/backend",
       "issue_number": 1
     }'
   ```

4. 手动创建分支、提交代码、创建 PR

5. 自动审查 PR：
   ```bash
   curl -X POST http://localhost:8106/review_pr \
     -H "Content-Type: application/json" \
     -d '{
       "repo": "myproject/backend",
       "pr_number": 1
     }'
   ```

### 场景 2: 代码知识库

**步骤**:

1. 将仓库索引到知识库：
   ```bash
   curl -X POST http://localhost:8106/index_repo \
     -H "Content-Type: application/json" \
     -d '{
       "repo_url": "https://github.com/myproject/backend.git"
     }'
   ```

2. 在 Node_105 中搜索代码：
   ```bash
   curl -X POST http://localhost:8105/search \
     -H "Content-Type: application/json" \
     -d '{
       "query": "JWT authentication",
       "top_k": 5
     }'
   ```

3. 在 Node_105 中问答：
   ```bash
   curl -X POST http://localhost:8105/ask \
     -H "Content-Type: application/json" \
     -d '{
       "question": "如何实现 JWT 认证？"
     }'
   ```

---

## 配置

### Mock 模式（默认）

无需任何配置，开箱即用。

**特点**:
- 不需要 GitHub Token
- 不需要 LLM API
- 生成模拟的 Issue、PR、代码审查
- 适合快速测试和演示

### 真实模式

需要配置 GitHub Token 和 LLM API。

**步骤**:

1. 设置 GitHub Token:
   ```bash
   export GITHUB_TOKEN=your_github_token
   ```

2. 修改 `main.py` 中的 `use_mock = False`

3. 配置 LLM API（如 OpenAI、DeepSeek）

4. 重启服务

---

## 与其他节点集成

### 与 Node_105 (Unified Knowledge Base) 集成

自动将代码索引到知识库：

```python
# 在 Node_106 中调用 Node_105
async def index_repo_to_kb(repo_url: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8105/add",
            json={
                "source_type": "github",
                "source": repo_url
            }
        )
        return response.json()
```

### 与 Node_80 (Memory System) 集成

从 Memos 任务创建 GitHub Issue：

```python
# 监听 Memos 任务
async def watch_memos_tasks():
    # 获取 Memos 中的 TODO
    tasks = await get_memos_tasks()
    
    for task in tasks:
        if task.startswith("TODO:"):
            # 创建 GitHub Issue
            await create_issue_from_task(task)
```

### 与 Node_07 (Git) 集成

自动化 Git 操作：

```python
# 调用 Node_07 创建分支
async def create_branch(repo_path: str, branch_name: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8007/branch",
            json={
                "repo_path": repo_path,
                "branch_name": branch_name,
                "action": "create"
            }
        )
        return response.json()
```

---

## 故障排查

### 问题 1: GitHub API 请求失败

**原因**: GitHub Token 无效或权限不足。

**解决**:
```bash
# 检查 Token
echo $GITHUB_TOKEN

# 重新生成 Token（确保权限正确）
```

### 问题 2: 无法索引仓库到知识库

**原因**: Node_105 未启动或网络问题。

**解决**:
```bash
# 检查 Node_105 是否运行
curl http://localhost:8105/health

# 如果未运行，启动 Node_105
cd nodes/Node_105_UnifiedKnowledgeBase
python main.py
```

### 问题 3: 代码生成质量不高

**原因**: Mock 模式生成的代码较简单。

**解决**: 切换到真实模式，配置 LLM API。

---

## 技术细节

### GitHub API

使用 GitHub REST API v3:
- 创建 Issue: `POST /repos/{owner}/{repo}/issues`
- 创建 PR: `POST /repos/{owner}/{repo}/pulls`
- 创建评论: `POST /repos/{owner}/{repo}/issues/{issue_number}/comments`

### 代码生成

- **Mock 模式**: 生成简单的 Python 模板
- **真实模式**: 调用 LLM API（如 GPT-4、DeepSeek）

### 代码审查

- **Mock 模式**: 生成简单的审查意见
- **真实模式**: 调用 LLM API 进行深度审查

---

## 未来增强

1. **支持更多 Git 操作**: 自动创建分支、提交代码、合并 PR
2. **支持更多代码审查规则**: 代码风格、安全漏洞、性能问题
3. **支持更多编程语言**: Java, C++, Go, Rust
4. **支持 CI/CD 集成**: 自动触发测试和部署
5. **支持团队协作**: 分配 Issue、审查者、里程碑

---

## 许可证

MIT License

---

**Node 106** | GitHub Flow | 2026-01-22
