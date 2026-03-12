"""
Node 11: GitHub - GitHub API 集成节点
======================================
提供 GitHub REST API v3 集成：仓库、Issues、Pull Requests、提交记录等
"""
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

# ── 配置 ──────────────────────────────────────────────────────────────────────
PORT = 8011
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_DEFAULT_OWNER = os.getenv("GITHUB_DEFAULT_OWNER", "")
GITHUB_DEFAULT_REPO = os.getenv("GITHUB_DEFAULT_REPO", "")
GITHUB_API_BASE = "https://api.github.com"

# ── 应用初始化 ────────────────────────────────────────────────────────────────
app = FastAPI(title="Node 11 - GitHub", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 统计 ──────────────────────────────────────────────────────────────────────
_stats: Dict[str, int] = {"total_requests": 0, "success_count": 0}

# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _require_token() -> None:
    if not GITHUB_TOKEN:
        raise HTTPException(
            status_code=503,
            detail={"error": "GITHUB_TOKEN not configured", "success": False},
        )
    if not HTTPX_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail={"error": "httpx not installed", "success": False},
        )


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _resolve(owner: Optional[str], repo: Optional[str]):
    o = owner or GITHUB_DEFAULT_OWNER
    r = repo or GITHUB_DEFAULT_REPO
    if not o or not r:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "owner and repo are required (or set GITHUB_DEFAULT_OWNER / GITHUB_DEFAULT_REPO)",
                "success": False,
            },
        )
    return o, r


async def _get(path: str) -> Any:
    _stats["total_requests"] += 1
    async with httpx.AsyncClient(base_url=GITHUB_API_BASE, timeout=30.0) as client:
        resp = await client.get(path, headers=_headers())
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=resp.status_code,
            detail={"error": resp.text, "success": False},
        )
    _stats["success_count"] += 1
    return resp.json()


async def _post(path: str, body: Dict[str, Any]) -> Any:
    _stats["total_requests"] += 1
    async with httpx.AsyncClient(base_url=GITHUB_API_BASE, timeout=30.0) as client:
        resp = await client.post(path, headers=_headers(), json=body)
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=resp.status_code,
            detail={"error": resp.text, "success": False},
        )
    _stats["success_count"] += 1
    return resp.json()


async def _patch(path: str, body: Dict[str, Any]) -> Any:
    _stats["total_requests"] += 1
    async with httpx.AsyncClient(base_url=GITHUB_API_BASE, timeout=30.0) as client:
        resp = await client.patch(path, headers=_headers(), json=body)
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=resp.status_code,
            detail={"error": resp.text, "success": False},
        )
    _stats["success_count"] += 1
    return resp.json()

# ── 请求模型 ──────────────────────────────────────────────────────────────────

class RepoInfoRequest(BaseModel):
    owner: Optional[str] = None
    repo: Optional[str] = None


class IssueListRequest(BaseModel):
    owner: Optional[str] = None
    repo: Optional[str] = None
    state: str = "open"
    labels: Optional[str] = None
    limit: int = 30


class IssueCreateRequest(BaseModel):
    owner: Optional[str] = None
    repo: Optional[str] = None
    title: str
    body: str = ""
    labels: List[str] = []


class IssueUpdateRequest(BaseModel):
    owner: Optional[str] = None
    repo: Optional[str] = None
    issue_number: int
    title: Optional[str] = None
    body: Optional[str] = None
    state: Optional[str] = None
    labels: Optional[List[str]] = None


class PullListRequest(BaseModel):
    owner: Optional[str] = None
    repo: Optional[str] = None
    state: str = "open"


class PullCreateRequest(BaseModel):
    owner: Optional[str] = None
    repo: Optional[str] = None
    title: str
    body: str = ""
    head: str
    base: str


class CommitListRequest(BaseModel):
    owner: Optional[str] = None
    repo: Optional[str] = None
    sha: Optional[str] = None
    limit: int = 30

# ── 端点 ──────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "success": True,
        "status": "healthy",
        "node_id": "11",
        "name": "GitHub",
        "port": PORT,
        "configured": bool(GITHUB_TOKEN),
        "httpx_available": HTTPX_AVAILABLE,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
async def status():
    rate_limit_info = None
    if GITHUB_TOKEN and HTTPX_AVAILABLE:
        try:
            rate_limit_info = await _get("/rate_limit")
        except Exception:
            pass
    return {
        "success": True,
        "token_set": bool(GITHUB_TOKEN),
        "default_owner": GITHUB_DEFAULT_OWNER or None,
        "default_repo": GITHUB_DEFAULT_REPO or None,
        "rate_limit_info": rate_limit_info,
        "stats": _stats,
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/repos/info")
async def repo_info(request: RepoInfoRequest):
    _require_token()
    owner, repo = _resolve(request.owner, request.repo)
    data = await _get(f"/repos/{owner}/{repo}")
    return {"success": True, "data": data}


@app.get("/repos/list")
async def repos_list(owner: str = Query(..., description="GitHub user or org name")):
    _require_token()
    data = await _get(f"/users/{owner}/repos?per_page=100&sort=updated")
    return {"success": True, "owner": owner, "repos": data, "count": len(data)}


@app.post("/issues/list")
async def issues_list(request: IssueListRequest):
    _require_token()
    owner, repo = _resolve(request.owner, request.repo)
    params = f"?state={request.state}&per_page={min(request.limit, 100)}"
    if request.labels:
        params += f"&labels={request.labels}"
    data = await _get(f"/repos/{owner}/{repo}/issues{params}")
    return {"success": True, "owner": owner, "repo": repo, "issues": data, "count": len(data)}


@app.post("/issues/create")
async def issues_create(request: IssueCreateRequest):
    _require_token()
    owner, repo = _resolve(request.owner, request.repo)
    body: Dict[str, Any] = {"title": request.title, "body": request.body}
    if request.labels:
        body["labels"] = request.labels
    data = await _post(f"/repos/{owner}/{repo}/issues", body)
    return {"success": True, "issue": data}


@app.post("/issues/update")
async def issues_update(request: IssueUpdateRequest):
    _require_token()
    owner, repo = _resolve(request.owner, request.repo)
    body: Dict[str, Any] = {}
    if request.title is not None:
        body["title"] = request.title
    if request.body is not None:
        body["body"] = request.body
    if request.state is not None:
        body["state"] = request.state
    if request.labels is not None:
        body["labels"] = request.labels
    if not body:
        raise HTTPException(status_code=400, detail={"error": "No fields to update", "success": False})
    data = await _patch(f"/repos/{owner}/{repo}/issues/{request.issue_number}", body)
    return {"success": True, "issue": data}


@app.post("/pulls/list")
async def pulls_list(request: PullListRequest):
    _require_token()
    owner, repo = _resolve(request.owner, request.repo)
    data = await _get(f"/repos/{owner}/{repo}/pulls?state={request.state}&per_page=100")
    return {"success": True, "owner": owner, "repo": repo, "pulls": data, "count": len(data)}


@app.post("/pulls/create")
async def pulls_create(request: PullCreateRequest):
    _require_token()
    owner, repo = _resolve(request.owner, request.repo)
    body = {
        "title": request.title,
        "body": request.body,
        "head": request.head,
        "base": request.base,
    }
    data = await _post(f"/repos/{owner}/{repo}/pulls", body)
    return {"success": True, "pull_request": data}


@app.post("/commits/list")
async def commits_list(request: CommitListRequest):
    _require_token()
    owner, repo = _resolve(request.owner, request.repo)
    params = f"?per_page={min(request.limit, 100)}"
    if request.sha:
        params += f"&sha={request.sha}"
    data = await _get(f"/repos/{owner}/{repo}/commits{params}")
    return {"success": True, "owner": owner, "repo": repo, "commits": data, "count": len(data)}


@app.get("/rate-limit")
async def rate_limit():
    _require_token()
    data = await _get("/rate_limit")
    return {"success": True, "rate_limit": data}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
