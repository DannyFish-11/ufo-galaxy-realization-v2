"""
Node 11: GitHub
====================
GitHub API 集成

依赖库: requests
工具: create_repo, create_issue, get_repo, list_repos
"""

import os
import requests
from datetime import datetime
from typing import Dict, Any, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Node 11 - GitHub", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_BASE_URL = "https://api.github.com"

class GitHubTools:
    def __init__(self):
        self.token = GITHUB_TOKEN
        self.base_url = GITHUB_BASE_URL
        self.initialized = bool(self.token)
        
    def _get_headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        
    def get_tools(self):
        return [
            {"name": "create_repo", "description": "创建 GitHub 仓库", "parameters": {"name": "仓库名称", "private": "是否私有 (true/false)"}},
            {"name": "create_issue", "description": "创建 Issue", "parameters": {"owner": "所有者", "repo": "仓库名", "title": "标题", "body": "内容"}},
            {"name": "get_repo", "description": "获取仓库信息", "parameters": {"owner": "所有者", "repo": "仓库名"}},
            {"name": "list_repos", "description": "列出用户仓库", "parameters": {}}
        ]
        
    async def call_tool(self, tool: str, params: dict):
        if not self.initialized:
            raise RuntimeError("GitHub API not initialized")
        handler = getattr(self, f"_tool_{tool}", None)
        if not handler:
            raise ValueError(f"Unknown tool: {tool}")
        return await handler(params)
        
    async def _tool_create_repo(self, params: dict):
        name = params.get("name", "")
        private = params.get("private", False)
        if not name:
            return {"error": "仓库名称不能为空"}
        try:
            response = requests.post(f"{self.base_url}/user/repos", headers=self._get_headers(), json={"name": name, "private": private}, timeout=15)
            response.raise_for_status()
            data = response.json()
            return {"success": True, "repo_id": data["id"], "full_name": data["full_name"], "url": data["html_url"]}
        except Exception as e:
            return {"error": str(e)}
            
    async def _tool_create_issue(self, params: dict):
        owner = params.get("owner", "")
        repo = params.get("repo", "")
        title = params.get("title", "")
        body = params.get("body", "")
        if not all([owner, repo, title]):
            return {"error": "owner, repo, title 不能为空"}
        try:
            response = requests.post(f"{self.base_url}/repos/{owner}/{repo}/issues", headers=self._get_headers(), json={"title": title, "body": body}, timeout=15)
            response.raise_for_status()
            data = response.json()
            return {"success": True, "issue_number": data["number"], "url": data["html_url"]}
        except Exception as e:
            return {"error": str(e)}
            
    async def _tool_get_repo(self, params: dict):
        owner = params.get("owner", "")
        repo = params.get("repo", "")
        if not all([owner, repo]):
            return {"error": "owner, repo 不能为空"}
        try:
            response = requests.get(f"{self.base_url}/repos/{owner}/{repo}", headers=self._get_headers(), timeout=15)
            response.raise_for_status()
            data = response.json()
            return {"success": True, "name": data["name"], "full_name": data["full_name"], "description": data["description"], "stars": data["stargazers_count"], "forks": data["forks_count"], "url": data["html_url"]}
        except Exception as e:
            return {"error": str(e)}
            
    async def _tool_list_repos(self, params: dict):
        try:
            response = requests.get(f"{self.base_url}/user/repos", headers=self._get_headers(), params={"per_page": 30}, timeout=15)
            response.raise_for_status()
            data = response.json()
            repos = [{"name": r["name"], "full_name": r["full_name"], "private": r["private"], "url": r["html_url"]} for r in data]
            return {"success": True, "count": len(repos), "repos": repos}
        except Exception as e:
            return {"error": str(e)}

tools = GitHubTools()

@app.get("/health")
async def health():
    return {"status": "healthy" if tools.initialized else "degraded", "node_id": "11", "name": "GitHub", "timestamp": datetime.now().isoformat()}

@app.get("/tools")
async def list_tools():
    return {"tools": tools.get_tools()}

@app.post("/mcp/call")
async def mcp_call(request: dict):
    try:
        result = await tools.call_tool(request.get("tool", ""), request.get("params", {}))
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8011)
