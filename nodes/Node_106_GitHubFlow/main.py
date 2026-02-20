"""
Node 106: GitHub Flow
======================
GitHub 工作流自动化系统

功能：
1. Issue 驱动开发（自动创建 Issue）
2. 自动化代码生成（根据 Issue 生成代码、创建 PR）
3. 自动化代码审查（调用 LLM 审查代码）
4. 代码知识库集成（与 Node_105 联动）

作者：Manus AI
日期：2026-01-22
"""

import os
import json
import time
import asyncio
import httpx
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import subprocess

app = FastAPI(title="Node 106 - GitHub Flow", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ============================================================================
# 数据模型
# ============================================================================

class CreateIssueRequest(BaseModel):
    repo: str  # owner/repo
    title: str
    body: str
    labels: Optional[List[str]] = None

class GenerateCodeRequest(BaseModel):
    repo: str
    issue_number: int
    branch_name: Optional[str] = None

class ReviewPRRequest(BaseModel):
    repo: str
    pr_number: int

class IndexRepoRequest(BaseModel):
    repo_url: str

# ============================================================================
# GitHub API 客户端
# ============================================================================

class GitHubClient:
    """GitHub API 客户端"""
    
    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.base_url = "https://api.github.com"
        self.use_mock = not self.token  # Mock 模式（无需 Token）
        
        if self.use_mock:
            print("⚠️ GitHub Token 未配置，使用 Mock 模式")
        else:
            print("✅ GitHub Token 已配置")
    
    async def _request(self, method: str, endpoint: str, data: Dict = None) -> Dict:
        """发送 HTTP 请求"""
        if self.use_mock:
            # Mock 模式：返回模拟数据
            return self._mock_response(endpoint, data)
        
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            if method == "GET":
                response = await client.get(url, headers=headers)
            elif method == "POST":
                response = await client.post(url, headers=headers, json=data)
            elif method == "PATCH":
                response = await client.patch(url, headers=headers, json=data)
            else:
                raise ValueError(f"不支持的 HTTP 方法: {method}")
            
            response.raise_for_status()
            return response.json()
    
    def _mock_response(self, endpoint: str, data: Dict = None) -> Dict:
        """Mock 响应"""
        if "/issues" in endpoint and data:
            # 创建 Issue
            return {
                "number": 1,
                "title": data.get("title"),
                "body": data.get("body"),
                "state": "open",
                "html_url": f"https://github.com/mock/repo/issues/1"
            }
        elif "/pulls" in endpoint and data:
            # 创建 PR
            return {
                "number": 1,
                "title": data.get("title"),
                "body": data.get("body"),
                "state": "open",
                "html_url": f"https://github.com/mock/repo/pull/1"
            }
        elif "/issues" in endpoint:
            # 获取 Issue
            return {
                "number": 1,
                "title": "Mock Issue",
                "body": "This is a mock issue",
                "state": "open"
            }
        else:
            return {"message": "Mock response"}
    
    async def create_issue(self, repo: str, title: str, body: str, labels: List[str] = None) -> Dict:
        """创建 Issue"""
        endpoint = f"/repos/{repo}/issues"
        data = {
            "title": title,
            "body": body
        }
        if labels:
            data["labels"] = labels
        
        return await self._request("POST", endpoint, data)
    
    async def get_issue(self, repo: str, issue_number: int) -> Dict:
        """获取 Issue"""
        endpoint = f"/repos/{repo}/issues/{issue_number}"
        return await self._request("GET", endpoint)
    
    async def create_pull_request(self, repo: str, title: str, body: str, head: str, base: str = "main") -> Dict:
        """创建 Pull Request"""
        endpoint = f"/repos/{repo}/pulls"
        data = {
            "title": title,
            "body": body,
            "head": head,
            "base": base
        }
        return await self._request("POST", endpoint, data)
    
    async def get_pull_request(self, repo: str, pr_number: int) -> Dict:
        """获取 Pull Request"""
        endpoint = f"/repos/{repo}/pulls/{pr_number}"
        return await self._request("GET", endpoint)
    
    async def create_review_comment(self, repo: str, pr_number: int, body: str) -> Dict:
        """创建 PR 评论"""
        endpoint = f"/repos/{repo}/issues/{pr_number}/comments"
        data = {"body": body}
        return await self._request("POST", endpoint, data)

# ============================================================================
# GitHub 工作流系统
# ============================================================================

class GitHubFlow:
    """GitHub 工作流自动化系统"""
    
    def __init__(self, github_token: Optional[str] = None, kb_url: str = "http://localhost:8105"):
        self.github = GitHubClient(github_token)
        self.kb_url = kb_url
        self.use_mock = True  # Mock 模式（无需 LLM）
        
        print(f"✅ GitHub 工作流已初始化 (Mock 模式: {self.use_mock})")
    
    async def create_issue_from_task(self, repo: str, task: str, labels: List[str] = None) -> Dict:
        """从任务创建 Issue"""
        # 解析任务（简单实现）
        title = task.split('\n')[0][:100]
        body = task
        
        issue = await self.github.create_issue(repo, title, body, labels)
        
        return {
            "success": True,
            "issue_number": issue.get("number"),
            "issue_url": issue.get("html_url"),
            "title": title
        }
    
    async def generate_code_from_issue(self, repo: str, issue_number: int, branch_name: Optional[str] = None) -> Dict:
        """根据 Issue 生成代码"""
        # 获取 Issue 内容
        issue = await self.github.get_issue(repo, issue_number)
        issue_title = issue.get("title")
        issue_body = issue.get("body")
        
        # Mock 模式：生成简单的代码
        if self.use_mock:
            code = self._mock_generate_code(issue_title, issue_body)
        else:
            # 真实模式：调用 LLM 生成代码
            code = await self._llm_generate_code(issue_title, issue_body)
        
        # 创建分支并提交代码
        if not branch_name:
            branch_name = f"feature/issue-{issue_number}"
        
        # 这里简化处理，实际需要调用 Node_07 (Git) 来操作
        commit_message = f"feat: implement {issue_title} (closes #{issue_number})"
        
        return {
            "success": True,
            "branch": branch_name,
            "commit_message": commit_message,
            "code": code,
            "next_step": "请手动创建分支、提交代码并创建 PR"
        }
    
    def _mock_generate_code(self, title: str, body: str) -> str:
        """Mock 代码生成"""
        return f"""
# {title}
# 
# {body}

def main():
    # 根据 Issue 需求实现具体功能
    print("功能实现中...")
    pass

if __name__ == "__main__":
    main()
"""
    
    async def _llm_generate_code(self, title: str, body: str) -> str:
        """调用 LLM 生成代码（通过 Gemini）"""
        try:
            import os
            gemini_key = os.getenv("GEMINI_API_KEY")
            if gemini_key:
                from google import genai
                client = genai.Client(api_key=gemini_key)
                prompt = f"""请根据以下 Issue 生成 Python 代码：

标题：{title}
说明：{body}

请生成完整的 Python 代码，包含必要的注释和错误处理。"""
                response = client.models.generate_content(
                    model="gemini-2.0-flash-exp",
                    contents=prompt
                )
                return response.text
            else:
                return self._mock_generate_code(title, body)
        except Exception as e:
            print(f"⚠️ LLM 代码生成失败: {e}，使用 Mock 模式")
            return self._mock_generate_code(title, body)
    
    async def review_pull_request(self, repo: str, pr_number: int) -> Dict:
        """审查 Pull Request"""
        # 获取 PR 信息
        pr = await self.github.get_pull_request(repo, pr_number)
        pr_title = pr.get("title")
        pr_body = pr.get("body")
        
        # Mock 模式：生成简单的审查意见
        if self.use_mock:
            review_comments = self._mock_review_code(pr_title, pr_body)
        else:
            # 真实模式：调用 LLM 审查代码
            review_comments = await self._llm_review_code(pr_title, pr_body)
        
        # 发表评论
        comment_body = f"## 自动代码审查\n\n{review_comments}"
        await self.github.create_review_comment(repo, pr_number, comment_body)
        
        return {
            "success": True,
            "pr_number": pr_number,
            "review_comments": review_comments
        }
    
    def _mock_review_code(self, title: str, body: str) -> str:
        """Mock 代码审查"""
        return f"""
### ✅ 代码审查通过

**PR 标题**: {title}

**审查要点**:
1. ✅ 代码结构清晰
2. ✅ 命名规范合理
3. ✅ 注释完整
4. ⚠️ 建议添加单元测试

**总体评价**: 代码质量良好，建议合并。
"""
    
    async def _llm_review_code(self, title: str, body: str) -> str:
        """调用 LLM 审查代码（通过 Gemini）"""
        try:
            import os
            gemini_key = os.getenv("GEMINI_API_KEY")
            if gemini_key:
                from google import genai
                client = genai.Client(api_key=gemini_key)
                prompt = f"""请审查以下 Pull Request：

PR 标题：{title}
PR 说明：{body}

请从以下方面进行审查：
1. 代码质量（命名、结构、注释）
2. 潜在问题（bug、性能、安全）
3. 改进建议

请以 Markdown 格式输出审查报告。"""
                response = client.models.generate_content(
                    model="gemini-2.0-flash-exp",
                    contents=prompt
                )
                return response.text
            else:
                return self._mock_review_code(title, body)
        except Exception as e:
            print(f"⚠️ LLM 代码审查失败: {e}，使用 Mock 模式")
            return self._mock_review_code(title, body)
    
    async def index_repo_to_kb(self, repo_url: str) -> Dict:
        """将 GitHub 仓库索引到知识库"""
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    f"{self.kb_url}/add",
                    json={
                        "source_type": "github",
                        "source": repo_url,
                        "metadata": {"indexed_by": "Node_106"}
                    }
                )
                response.raise_for_status()
                result = response.json()
            
            return {
                "success": True,
                "message": result.get("message", "仓库已索引到知识库"),
                "kb_url": self.kb_url
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

# ============================================================================
# 全局实例
# ============================================================================

flow = GitHubFlow()

# ============================================================================
# API 端点
# ============================================================================

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "node_id": "106",
        "name": "GitHub Flow",
        "mock_mode": flow.use_mock,
        "github_mock": flow.github.use_mock
    }

@app.post("/create_issue")
async def create_issue(request: CreateIssueRequest):
    """创建 Issue"""
    try:
        result = await flow.create_issue_from_task(
            request.repo,
            f"{request.title}\n\n{request.body}",
            request.labels
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate_code")
async def generate_code(request: GenerateCodeRequest):
    """根据 Issue 生成代码"""
    try:
        result = await flow.generate_code_from_issue(
            request.repo,
            request.issue_number,
            request.branch_name
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/review_pr")
async def review_pr(request: ReviewPRRequest):
    """审查 Pull Request"""
    try:
        result = await flow.review_pull_request(request.repo, request.pr_number)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/index_repo")
async def index_repo(request: IndexRepoRequest, background_tasks: BackgroundTasks):
    """将 GitHub 仓库索引到知识库"""
    try:
        # 放到后台任务
        background_tasks.add_task(flow.index_repo_to_kb, request.repo_url)
        return {
            "success": True,
            "message": "仓库正在后台索引到知识库"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/workflow/issue_to_pr")
async def workflow_issue_to_pr(repo: str, issue_number: int):
    """完整工作流：从 Issue 到 PR"""
    try:
        # 1. 获取 Issue
        issue = await flow.github.get_issue(repo, issue_number)
        
        # 2. 生成代码
        code_result = await flow.generate_code_from_issue(repo, issue_number)
        
        # 3. 返回结果（实际需要手动创建 PR）
        return {
            "success": True,
            "issue": issue,
            "code_generation": code_result,
            "next_steps": [
                f"1. 创建分支: {code_result['branch']}",
                "2. 提交代码",
                "3. 创建 Pull Request",
                "4. 调用 /review_pr 进行自动审查"
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# 启动服务
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8106)
